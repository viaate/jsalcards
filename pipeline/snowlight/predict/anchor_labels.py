"""The one adapter from the outcome-blind live labels (advisory-sane L1) to the class anchor's
live update (:mod:`snowlight.predict.anchor`, Addendum B2).

L1 (:mod:`snowlight.predict.live_read`) keeps its private record in its ``READS_DIR``,
``out/internal/predict/reads/`` (restored from its own Actions cache before the passes):
``rows/<day>.json``, one labeled school day (its ``ReadDay``: the alerted districts' rows,
``district``, ``weather`` (the class number), ``after``, ``label``, ``tier``, ``market``, and
``sources``, the lists that read it, counted only), and ``trials/<day>.jsonl``, its
co-listing trials (``tier``, ``named``). The folder is L1's own constant; the files are read
as plain JSON, so a day L1's models would refuse is left out and said here, never fatal.

Only rows a read labeled (``no_school``, ``delayed``, ``unnamed``, the last counting open, the
owner's O5) with a tier enter; ``unknown`` and ``not_read`` rows do not. With no record (no day
labeled yet, or the reads cache lost it) the labels are empty and the anchor serves its prior's
level, which is correct. A day that does not read is left out and said, never fatal: a broken
day must not darken a pass.

The take-back (predict-next ONE-STORM, ``learn.excluded_days`` and ``learn.excluded_rows``): a
day found misread is skipped by its name, unread; one district's row of a day is dropped, with
its trials, from the day as read. The record's files are never rewritten, and the labels are
those of a record that never held them, so the fit is too.
"""

import json
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Final, cast

from snowlight.predict import live_read
from snowlight.predict.anchor import (
    Anchor,
    AnchorSettings,
    LabelKind,
    LeftOut,
    LiveLabels,
    LiveRow,
    Plausible,
    Ramp,
    Tier,
    Trials,
    fit,
)
from snowlight.predict.artifact import ModelArtifact
from snowlight.predict.config import PIPELINE_ROOT, LearnSettings, PredictConfig
from snowlight.predict.exposure import CLASSES, EXPOSURE_PATH, Exposure
from snowlight.predict.exposure import load as load_exposure
from snowlight.predict.forecast_adjust import CLIMATE_PATH, AdjustSettings
from snowlight.predict.forecast_adjust import load as load_climate
from snowlight.predict.geography import REGION_OF
from snowlight.predict.situations import Situation, WeatherClass

READS_DIR: Final = live_read.READS_DIR
"""L1's private record."""
LABELS: Final[frozenset[str]] = frozenset({"no_school", "delayed", "unnamed"})
TIERS: Final[frozenset[str]] = frozenset({"A", "B"})
RECORD_SCHEMA: Final = 1


def _day_of(path: Path) -> date | None:
    try:
        return date.fromisoformat(path.stem)
    except ValueError:
        return None


def _rows(day: date, body: object) -> list[LiveRow]:
    """One day's labeled rows.

    Raises:
        ValueError: the day's file is not one L1 writes.
    """
    if not isinstance(body, dict) or body.get("schema_version") != RECORD_SCHEMA:
        raise ValueError("not a read day of schema 1")
    if body.get("day") != day.isoformat():
        raise ValueError(f"names day {body.get('day')!r}")
    rows = body.get("rows")
    if not isinstance(rows, list):
        raise ValueError("no rows")
    found: list[LiveRow] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("a row is not an object")
        label, tier = row.get("label"), row.get("tier")
        if label not in LABELS or tier not in TIERS:
            continue
        district, weather, market = row.get("district"), row.get("weather"), row.get("market")
        if not isinstance(district, str) or not isinstance(weather, int):
            raise ValueError("a row has no district or class")
        situation = Situation.of(WeatherClass(weather), row.get("after") is True)
        sources = row.get("sources")
        lists = len({s for s in sources if isinstance(s, str)}) if isinstance(sources, list) else 0
        found.append(
            LiveRow(
                day=day,
                district=district,
                market=market if isinstance(market, str) else None,
                tier=cast("Tier", tier),
                label=cast("LabelKind", label),
                weather=situation.key,
                lists=max(lists, 1),
            )
        )
    return found


def day_rows(day: date, body: object) -> list[LiveRow]:
    """One day's labeled rows (``no_school``, ``delayed`` or ``unnamed``, tier A or B) from
    its ``rows/<day>.json`` body, as the anchor reads them (the live switch's labels too).

    Raises:
        ValueError: the day's file is not one L1 writes.
    """
    return _rows(day, body)


def _trials(
    path: Path,
    day: date,
    tally: dict[str, list[int]],
    dates: dict[str, set[date]],
    left_out: frozenset[str] = frozenset(),
) -> int:
    """Add one day's closed co-listing trials (hits, trials) per tier, less the lines of the
    districts ``left_out`` that day (a line with no ``district`` is kept); returns how many
    lines were left out.

    Raises:
        ValueError: a line does not read.
    """
    dropped = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        trial = json.loads(line)
        if left_out and isinstance(trial, dict) and trial.get("district") in left_out:
            dropped += 1
            continue
        tier = trial.get("tier") if isinstance(trial, dict) else None
        named = trial.get("named") if isinstance(trial, dict) else None
        if tier not in TIERS or not isinstance(named, bool):
            raise ValueError("a trial has no tier or naming")
        found = tally.setdefault(str(tier), [0, 0])
        found[0] += int(named)
        found[1] += 1
        dates.setdefault(str(tier), set()).add(day)
    return dropped


def read_labels(
    folder: Path = READS_DIR,
    *,
    since: date | None = None,
    warn: Callable[[str], None] = lambda _line: None,
    excluded: LearnSettings | None = None,
) -> LiveLabels:
    """The record's labeled rows and trials (empty, ``found`` false, when there is none).

    ``since``: the first day the fit reads (``live_update.fit_from``); a day file before it is
    skipped by its name, unread, with its trials, so a record kept forever costs each process
    only the days the fit can use (R3-S4). ``excluded``: the take-back lists (``config.learn``):
    an excluded day's rows file and trials file are skipped by name, unread and not counted in
    ``days``; in a day that is read, each listed pair's row is dropped, and each trial line
    of a listed pair's district that day. What was listed and what of it the record held is
    counted (``left_out``); nothing is warned and no file is written."""
    listed = (
        LeftOut()
        if excluded is None
        else LeftOut(
            days_listed=len(set(excluded.excluded_days)),
            rows_listed=len(set(excluded.excluded_rows)),
        )
    )
    root = folder / "rows"
    if not root.is_dir():
        return LiveLabels(left_out=listed)
    rows: list[LiveRow] = []
    tally: dict[str, list[int]] = {}
    dates: dict[str, set[date]] = {}
    days = 0
    skipped = gone_rows = gone_trials = 0
    for path in sorted(root.glob("*.json")):
        day = _day_of(path)
        if day is None or (since is not None and day < since):
            continue
        if excluded is not None and excluded.excludes_day(day):
            skipped += 1
            continue
        gone = excluded.districts_left_out(day) if excluded is not None else frozenset()
        try:
            found = _rows(day, json.loads(path.read_text(encoding="utf-8")))
            trials = folder / "trials" / f"{day.isoformat()}.jsonl"
            mine: dict[str, list[int]] = {}
            mine_dates: dict[str, set[date]] = {}
            dropped = _trials(trials, day, mine, mine_dates, gone) if trials.is_file() else 0
        except (OSError, ValueError, KeyError) as error:
            warn(f"anchor: the live labels of {day}: {type(error).__name__}: left out")
            continue
        if gone:
            kept = [row for row in found if row.district not in gone]
            gone_rows += len(found) - len(kept)
            gone_trials += dropped
            found = kept
        rows.extend(found)
        for tier, (hits, count) in mine.items():
            total = tally.setdefault(tier, [0, 0])
            total[0] += hits
            total[1] += count
        for tier, seen in mine_dates.items():
            dates.setdefault(tier, set()).update(seen)
        days += 1
    return LiveLabels(
        rows=tuple(rows),
        trials={
            cast("Tier", tier): Trials(hits=hits, trials=count, dates=len(dates.get(tier, ())))
            for tier, (hits, count) in sorted(tally.items())
        },
        days=days,
        found=True,
        left_out=replace(listed, days=skipped, rows=gone_rows, trials=gone_trials),
    )


ANCHOR_REPORT: Final = PIPELINE_ROOT / "out" / "internal" / "predict" / "anchor.json"
"""The private report of the class levels a process serves (never published)."""


def serving_anchor(  # noqa: PLR0913 - the config, the model and where each file is
    config: PredictConfig,
    artifact: ModelArtifact,
    *,
    folder: Path = READS_DIR,
    exposure_path: Path = EXPOSURE_PATH,
    climate_path: Path = CLIMATE_PATH,
    warn: Callable[[str], None] = lambda _line: None,
) -> Anchor | None:
    """The class anchor a serving process uses (``serve.anchor``; off: ``None``), fitted on
    the live labels the record holds now (Addendum A item 4: refreshed with each day's run).

    An exposure file that does not read leaves every unit at its class level (no exposure
    term, no region delta) and says so: never back to an archive closure share. With
    ``serve.forecast_adjust`` on it carries the forecast climate and the registered adjustment
    (:mod:`snowlight.predict.forecast_adjust`); a climate file that does not read leaves every
    day at its class level, and says so. The take-back lists (``config.learn``) are honored
    when the record is read (:func:`read_labels`). A class whose fit as built raised (made
    for the log line only, :func:`snowlight.predict.anchor.ramped`) is said once; what it
    serves is untouched."""
    if not config.serve.anchor:
        return None
    settings = AnchorSettings.of(config)
    try:
        exposure = load_exposure(exposure_path)
    except (OSError, ValueError, KeyError) as error:
        warn(f"anchor: the exposure file: {type(error).__name__}: serving the class levels alone")
        exposure = Exposure((), {}, {}, {}, {}, {})
    labels = read_labels(folder, since=settings.fit_from, warn=warn, excluded=config.learn)
    places = {
        leaid: (entry.county, REGION_OF.get(entry.state) if entry.state else None)
        for leaid, entry in artifact.districts.items()
    }
    anchor = fit(settings, exposure, labels, places)
    for key, found in anchor.fits.items():
        if found.ramp is not None and found.ramp.built_error is not None:
            warn(f"anchor: the fit as built of {key}: {found.ramp.built_error}: not in the line")
    if config.serve.forecast_adjust != "on":
        return anchor
    try:
        adjust = AdjustSettings.of(config)
        climate = load_climate(climate_path)
    except (OSError, ValueError, KeyError) as error:
        warn(f"anchor: the forecast climate: {type(error).__name__}: the class levels alone")
        return anchor
    return replace(anchor, climate=climate, adjust=adjust)


TEMPERED_SAID: Final = 6
"""The log line names this many tempered storms, then counts the rest (``anchor.json`` holds
every one)."""


def _ramp_said(key: str, ramp: Ramp) -> str:
    """One class's ramp: its weight, what binds it, and the tempered posterior's and the fit
    as built's level and delay share."""
    said = f"{key} w {ramp.w:.3f}"
    if ramp.bound == "none":
        return f"{said} no rows"
    full = ramp.full
    if ramp.bound == "rows":
        said += f" by rows {ramp.rows} of {full.rows:g}"
    elif ramp.bound == "storms":
        said += f" by storms {ramp.storms:.2f} of {full.storms:g}"
    elif ramp.bound == "market_days":
        said += f" by market_days {ramp.market_days:.2f} of {full.market_days or 0:g}"
    else:
        said += " full"
    said += f" raw {ramp.raw.level:.3f} q {ramp.raw.q:.3f}"
    if ramp.built is None:
        return f"{said} built unavailable"
    return f"{said} built {ramp.built.level:.3f} q {ramp.built.q:.3f}"


def _tempered_said(ramps: Sequence[tuple[str, Ramp]]) -> str:
    """The storms held to their class's share, by class then first date."""
    found: list[str] = []
    for key, ramp in ramps:
        for storm in ramp.tempered:
            said = f"{key} {storm.storm.isoformat()} x{len(storm.dates)}"
            if storm.weight < 1:
                said += f" level {storm.share:.3f} to {ramp.cap:.3f}"
            if storm.delay_weight < 1:
                said += f" delays {storm.delay_share:.3f} to {ramp.cap:.3f}"
            found.append(said)
    if not found:
        return "tempered none"
    more = len(found) - TEMPERED_SAID
    return (
        "tempered " + ", ".join(found[:TEMPERED_SAID]) + (f" and {more} more" if more > 0 else "")
    )


def _take_back_said(left_out: LeftOut) -> str:
    """Both take-back lists, each with what it names and what of it the record held."""
    if not left_out.days_listed and not left_out.rows_listed:
        return "take-back none listed"
    days = "day" if left_out.days_listed == 1 else "days"
    rows = "row" if left_out.rows_listed == 1 else "rows"
    return (
        f"take-back {left_out.days_listed} {days} listed ({left_out.days} in the record), "
        f"{left_out.rows_listed} {rows} listed ({left_out.rows} in the record)"
    )


def anchor_line(anchor: Anchor) -> str:
    """One log line (counts and numbers only): each class's level at the reference district
    with its 80% band, its delay share and the live rows it rests on; each class's ramp (its
    weight, the count that binds it, the tempered posterior's level and the fit as built's:
    what ``ramp: "off"`` would serve); the storms held to their share; what the take-back
    lists name and what of it the record held; and the labeled days read."""
    parts = []
    for key, found in anchor.fits.items():
        low, high = found.band
        parts.append(
            f"{key} {float(found.level(0.0)):.3f} ({low:.3f}-{high:.3f}) q {found.q:.3f} "
            f"rows {found.rows} on {found.dates} dates"
        )
    ramps = [(key, anchor.fits[key].ramp) for key in CLASSES if key in anchor.fits]
    told = [(key, ramp) for key, ramp in ramps if ramp is not None]
    if anchor.settings.ramp == "off" or not told:
        parts.append("ramp off")
    else:
        parts.append("ramp " + ", ".join(_ramp_said(key, ramp) for key, ramp in told))
        parts.append(_tempered_said(told))
    parts.append(_take_back_said(anchor.labels.left_out))
    record = f"{anchor.labels.days} labeled days" if anchor.labels.found else "no read record"
    return f"anchor: {'; '.join(parts)}; {record}"


def write_report(
    anchor: Anchor, path: Path = ANCHOR_REPORT, *, plausible: Plausible | None = None
) -> None:
    """Keep the private report (``anchor.json``), with what the plausibility check did on the
    served districts once a serving model is built (``plausible``)."""
    body = anchor.summary()
    if plausible is not None:
        body["plausibility"] = plausible.summary()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, sort_keys=True, indent=1) + "\n", encoding="utf-8")
