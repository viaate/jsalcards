"""Building the Flights files from the history kept in RAM (``snowlight flights train`` and
``snowlight flights static``): the model file, the held-out report, and every published file
that is not live. Each writes under ``out``: ``heldout.md`` and ``summary.json`` for people, and
the published files under ``out/files/flights/``, checked by
:func:`snowlight.schemas.site.validate_site` before anything is said to be done.
"""

import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final

import polars as pl

from snowlight.flights import artifact as artifact_module
from snowlight.flights import model as fm
from snowlight.flights import obs, records, replays, report, schedules, spans, train
from snowlight.flights.airports import Airport, current_code, load
from snowlight.flights.bts import Month, kept_months, scan
from snowlight.flights.bts import months as months_between
from snowlight.schemas.flights import (
    FlightsAirportEntry,
    FlightsAirports,
    FlightsCarrierRecord,
    FlightsHeld,
    FlightsKind,
    FlightsRecord,
    FlightsRecordLine,
    FlightsVerdict,
)
from snowlight.schemas.site import validate_site

LEFT_OUT_DAYS: Final = (("MCI", date(2025, 1, 5), (date(2024, 11, 1), date(2025, 3, 31))),)
"""Past storm days before the test year, each replayed with a fit that leaves its winter out,
on usual rates from before its 12-month period, and shown through the airport's own gate. Two
choices were made on the validation year (October 2024 to September 2025), which holds this
winter, and so did see it: the usual rates' window length (one of three lengths) and which input
groups the model uses (each kept or left out, :func:`snowlight.flights.train.choose_inputs`).
Neither is a fit of the model's weights, which never see the winter; the replay says so."""
BUSY: Final = 100.0
"""Storm days for the replays are picked among airports with this many departures a day."""


def _say(line: str) -> None:
    """One output line, written at once."""
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _write(out: Path, path: str, data: bytes) -> None:
    target = out / "files" / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def _check(out: Path) -> int:
    result = validate_site(out / "files")
    for problem in result.problems:
        _say(f"flights: invalid: {problem}")
    _say(f"flights: {len(result.checked)} files valid, {len(result.problems)} problems")
    return 0 if not result.problems else 1


def observed_gaps(root: Path, first_run: date, oldest: Month, newest: Month) -> list[str]:
    """The months of hourly reports the fit needs and the store lacks: from the month before the
    first run (its observed-before inputs look 2 days back), or the oldest BTS month, to the
    newest BTS month."""
    start = max(
        Month(first_run.year, first_run.month).back(1), oldest, key=lambda m: (m.year, m.month)
    )
    return [
        month.key
        for month in months_between(start, newest)
        if not (root / f"{month.key}.parquet").is_file()
    ]


def _input_notes(
    checks: Sequence[tuple[str, str, int, float, float]],
    left: Sequence[str],
    together: Sequence[tuple[str, int, float, float, float]],
    chosen: tuple[str, ...],
    inputs: tuple[str, ...],
) -> list[str]:
    """The report's notes on the inputs: each group's check, the choice, the chosen inputs
    scored together on the validation year, and what was fitted."""
    notes: list[str] = []
    groups = {"day_": "Whole-day", "pre_": "Before-the-day", "obs_": "Observed-before"}
    for group, target, lead, every, fewer in checks:
        notes.append(
            f"{groups[group]} inputs ({group}*), checked on the validation year (the 12 months "
            f"before the test year), {target} lead {lead}: Brier {every:.6f} with them, "
            f"{fewer:.6f} without "
            f"({'better with them' if every < fewer else 'not better with them'})."
        )
    notes.append(
        "Inputs chosen on the validation year (a group stays only when it is better with it on "
        "every check): "
        + ", ".join(f"{groups[g]} ({g}*) {'left out' if g in left else 'kept'}" for g in groups)
        + "."
    )
    for target, lead, mine, every, no_day in together:
        notes.append(
            f"The chosen inputs together, on the validation year, {target} lead {lead}: Brier "
            f"{mine:.6f}, against {every:.6f} with every input and {no_day:.6f} without the "
            f"whole-day inputs ({'no worse than both' if mine <= min(every, no_day) else 'worse'})."
        )
    notes.append(
        "Inputs fitted: "
        + (
            "the chosen ones"
            if inputs == chosen
            else "not the chosen ones, which scored worse together"
        )
        + f" ({len(inputs)} of {len(fm.FEATURES)})."
    )
    return notes


def gate_notes(validated: Sequence[train.Tested], model: fm.Model) -> list[str]:
    """The report's notes on the gates (LR-H1): set on the validation year by a fit on the years
    before it, never on the test year, with that year's scores of the gating fit."""
    if not validated:
        return ["Gates: no validation year rows; nothing is published."]
    first, last = validated[0].split
    notes = [
        f"Gates (where a chance is published, and after a storm) set on the validation year, "
        f"{first} to {last}, by a fit on the years before it; the test year scores them once."
    ]
    for test in validated:
        shown = sum(
            1
            for (_, target, lead), ok in model.published.items()
            if ok and (target, lead) == (test.target, test.lead)
        )
        notes.append(
            f"Validation year, {test.target} lead {test.lead}: skill "
            f"{100 * test.pooled.skill:+.1f}% if shown at every airport, "
            f"{100 * test.confirmed.skill:+.1f}% out of selection, "
            f"{100 * test.as_published.skill:+.1f}% as published at {shown} airports; under "
            f"said heavy {test.as_published.under} of {test.as_published.heavy}."
        )
    return notes


def _iem_last(tables: train.Tables) -> date | None:
    """The last day of IEM's NBS runs the fit read (``None``: none)."""
    from snowlight.flights.pull import NBS_LAST  # noqa: PLC0415

    runs = tables.blocks["dep"].get_column("run")
    if runs.is_empty() or runs.min().date() > NBS_LAST:  # type: ignore[union-attr]
        return None
    older = runs.filter(runs.dt.date() <= NBS_LAST)
    return older.max().date()  # type: ignore[union-attr, no-any-return]


def nbs_rows(raw: Path) -> pl.LazyFrame:
    """Every kept NBS row: the bucket's bulletins (``nbs/``), and IEM's copy of the winters
    before them (``nbs-iem/``, :mod:`snowlight.flights.nbs_iem`) up to its last 00Z run."""
    rows = pl.scan_parquet(raw / "nbs" / "*.parquet")
    iem = raw / "nbs-iem"
    if iem.is_dir() and any(iem.glob("*.parquet")):
        from snowlight.flights.pull import NBS_LAST  # noqa: PLC0415

        older = pl.scan_parquet(iem / "*.parquet").filter(pl.col("run").dt.date() <= NBS_LAST)
        rows = pl.concat([older, rows], how="vertical")
    return rows


def _usual(tables: train.Tables) -> tuple[date, date]:
    """The usual rates' dated window (:attr:`snowlight.flights.train.Tables.usual_window`)."""
    if tables.usual_window is None:  # pragma: no cover - every assembled table sets it
        msg = "the tables hold no usual window"
        raise ValueError(msg)
    return tables.usual_window


def train_all(raw: Path, out: Path, model_path: Path, first_run: date) -> int:
    """Fit, test, and write the model file, the report, the track record and the replays."""
    airports = load()
    rows = nbs_rows(raw).filter(pl.col("run").dt.date() >= first_run)
    kept = kept_months(raw / "bts")
    gaps = observed_gaps(raw / "obs", first_run, kept[0], kept[-1])
    if gaps:
        # A missing month would count its storms as no weather: the day after a storm said low.
        _say(f"flights: the weather reports lack {len(gaps)} months ({', '.join(gaps[:6])})")
        return 1
    flags = pl.scan_parquet(raw / "obs" / "*.parquet")
    tables = train.assemble(raw / "bts", rows, airports, flags)
    checks = train.validation_day_features(tables)
    chosen, left = train.choose_inputs(checks)
    together = train.validation_chosen(tables, chosen)
    inputs = train.confirm_inputs(chosen, together)
    model, validated, tests = train.fit_and_gate(tables, inputs)
    base_dep, national_dep = artifact_module.base_tables(tables.base["dep"])
    base_arr, national_arr = artifact_module.base_tables(tables.base["arr"])
    rough, national_rough = artifact_module.rough_table(tables.rough)
    made = artifact_module.Artifact(
        model=model,
        test_first=tables.split.test_first,
        test_last=tables.split.test_last,
        base={"dep": base_dep, "arr": base_arr},
        rough=rough,
        national={"dep": national_dep, "arr": national_arr},
        national_rough=national_rough,
    )
    artifact_module.write(made, model_path)
    gates = made.gates()
    runs = tables.blocks["dep"].get_column("run")
    notes = [
        f"Forecast runs used: {str(runs.min())[:10]} to {str(runs.max())[:10]} (00Z NBS"
        + (
            f"; IEM's copy to {iem_last}, the AWS bucket after"
            if (iem_last := _iem_last(tables)) is not None
            else ""
        )
        + ").",
        "Usual rates: "
        + (
            f"the {tables.base_years} years before the test year"
            if tables.base_years
            else "every posted BTS month before the test year "
            f"({kept_months(raw / 'bts')[0].key} on)"
        )
        + " (the window chosen on the validation year, the 12 months before the test year): "
        + "{} to {}, the window the live files' usual rates average over too.".format(
            *_usual(tables)
        ),
        f"Airports: {len(airports)}.",
        *[
            f"Left out of fitting and testing, as not weather: {first} to {last}, {why}."
            for first, last, why in spans.NOT_WEATHER
        ],
        *[
            f"Left out of fitting and testing for {code} flights only, as not weather: {first} to "
            f"{last}, {why}."
            for code, first, last, why in spans.CARRIER_NOT_WEATHER
        ],
    ]
    leads = (
        tables.blocks["dep"]
        .group_by("lead_class")
        .agg(pl.col("lead").min().alias("low"), pl.col("lead").max().alias("high"))
        .sort("lead_class")
    )
    notes.append(
        "Hours from the run to the block's start: "
        + "; ".join(
            f"lead {row['lead_class']} {row['low']:.0f} to {row['high']:.0f} h"
            for row in leads.iter_rows(named=True)
        )
        + "."
    )
    legs = train.flight_test(tables, model, scan(raw / "bts", "legs"))
    if legs["flights"]:
        usual = legs["brier_usual"]
        skill = 1 - legs["brier"] / usual if usual else 0.0
        shown = 1 - legs["brier_published"] / usual if usual else 0.0
        notes.append(
            f"A flight's cancel chance (the higher of its two ends, lead 1), test year: "
            f"{legs['flights']:,.0f} flights, {legs['cancelled']:,.0f} cancelled, Brier "
            f"{legs['brier']:.5f} for the model's chances at every airport (skill "
            f"{100 * skill:+.1f}%), {legs['brier_published']:.5f} as published (skill "
            f"{100 * shown:+.1f}%), against {usual:.5f} for the usual rates."
        )
    notes += _input_notes(checks, left, together, chosen, inputs)
    notes += gate_notes(validated, model)
    out.mkdir(parents=True, exist_ok=True)
    (out / "heldout.md").write_text(report.markdown(tests, gates, notes), encoding="utf-8")
    now = _now()
    _write(
        out,
        "flights/track-record.json",
        report.track_record(tests, gates, now, _usual(tables)).to_json_bytes(),
    )
    made_replays = []
    busy = [a.code for a in airports if a.per_day >= BUSY]
    for code, day in replays.storm_days(tables, busy, model):
        found = replays.replay(tables, model, code, day, FlightsHeld.TEST_YEAR, now)
        if found is not None:
            made_replays.append(found)
    for code, day, span in LEFT_OUT_DAYS:
        # The chances from a fit without that winter; what is shown, from the airport's gate.
        apart = train.train(tables, exclude=span, inputs=model.inputs)
        found = replays.replay(tables, apart, code, day, FlightsHeld.LEFT_OUT, now, gate=model)
        if found is not None:
            made_replays.append(found)
    for found in made_replays:
        _write(out, f"flights/replays/{found.id.lower()}.json", found.to_json_bytes())
    _write(out, "flights/replays/index.json", replays.index(made_replays, now).to_json_bytes())
    summary = {
        "tests": [
            {
                "target": t.target,
                "lead": t.lead,
                "skill": round(t.pooled.skill, 4),
                "skill_published": round(t.as_published.skill, 4),
                "skill_confirmed": round(t.confirmed.skill, 4),
                "brier": round(t.pooled.brier, 6),
                "brier_usual": round(t.pooled.brier_base, 6),
                "airports": len(t.airports),
                "published": sum(
                    1 for m in gates.values() if m[fm.TARGETS.index(t.target)] >> (t.lead - 1) & 1
                ),
            }
            for t in tests
        ],
        "replays": [r.id for r in made_replays],
    }
    import json  # noqa: PLC0415

    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return _check(out)


def airports_file(
    airports: Sequence[Airport], newest: Month, generated_at: datetime
) -> FlightsAirports:
    """``flights/airports.json``."""
    first = newest.back(11)
    return FlightsAirports(
        schema_version=1,
        generated_at=generated_at,
        months=(f"{first.year}-{first.month:02d}", f"{newest.year}-{newest.month:02d}"),
        airports=tuple(
            FlightsAirportEntry(
                code=a.code,
                name=a.name,
                city=a.city or a.code,
                state=a.state if len(a.state) == 2 else "US",  # noqa: PLR2004
                lat=a.lat,
                lon=a.lon,
                tz=a.tz,
                per_day=a.per_day,
            )
            for a in airports
        ),
    )


def _line(line: records.Line) -> FlightsRecordLine:
    return FlightsRecordLine(
        kind=FlightsKind(int(line.kind)),
        blocks=line.blocks,
        bad=line.bad,
        days=line.days,
        bad_days=line.bad_days,
        share=records.per_mille(line.share),
        others=records.per_mille(line.others_share),
        worse=line.worse,
        better=line.better,
        verdict=FlightsVerdict(int(line.verdict)),
    )


def static_all(raw: Path, out: Path) -> int:
    """Write the airports, usual flights and own record files."""
    airports = load()
    codes = [a.code for a in airports]
    now = _now()
    newest = kept_months(raw / "bts")[-1]
    _write(out, "flights/airports.json", airports_file(airports, newest, now).to_json_bytes())
    for code, routes in schedules.build(
        raw / "bts", schedules.months_for(newest, now.date()), codes, now
    ).items():
        _write(out, f"flights/routes/{code.lower()}.json", routes.to_json_bytes())
    zones = pl.DataFrame(
        {"station": [a.wx for a in airports], "apt": codes, "tz": [a.tz for a in airports]}
    )
    kinds = obs.block_kinds(pl.scan_parquet(raw / "obs" / "*.parquet"), zones).collect()
    # The record covers the days both histories have: reports and posted flights.
    bts_last = newest.next().first - timedelta(days=1)
    bts_first = kept_months(raw / "bts")[0].first
    span = kinds.select(
        pl.max_horizontal(pl.col("day").min(), pl.lit(bts_first)).alias("first"),
        pl.min_horizontal(pl.col("day").max(), pl.lit(bts_last)).alias("last"),
    ).row(0)
    dep = scan(raw / "bts", "dep").filter(spans.carrier_weather()).with_columns(current_code("apt"))
    dep_blocks = dep.group_by("apt", "day", "block").agg(pl.col("n").sum(), pl.col("canc").sum())
    own = records.airport_lines(dep_blocks, kinds.lazy())
    carriers = records.carrier_lines(dep, kinds.lazy())
    for code in codes:
        lines = own.get(code, [])
        mine = sorted((carrier, found) for (apt, carrier), found in carriers.items() if apt == code)
        record = FlightsRecord(
            schema_version=1,
            generated_at=now,
            code=code,
            first=span[0],
            last=span[1],
            lines=tuple(_line(line) for line in lines),
            carriers=tuple(
                FlightsCarrierRecord(carrier=carrier, lines=tuple(_line(line) for line in found))
                for carrier, found in mine
                if any(line.verdict != records.Verdict.NONE for line in found)
            ),
        )
        _write(out, f"flights/records/{code.lower()}.json", record.to_json_bytes())
    return _check(out)
