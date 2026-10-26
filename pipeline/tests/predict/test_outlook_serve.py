"""The outlook on the serving pass (S7-F F3, spec-f s. 7, 8, 10): off and shadow publish S7-L's
pass byte for byte, shadow keeps a private record, on publishes the outlook's line and its sum.
SYNTHETIC alerts, forecasts and T only (:mod:`predict.night`)."""

import json
from dataclasses import replace
from datetime import timedelta
from typing import Any

import numpy as np
import pytest

from predict import night, world
from predict.test_publish import MemoryHost, make_pass
from snowlight.predict import cli, learn
from snowlight.predict import outlook as outlook_module
from snowlight.predict.outlook import OutlookMode
from snowlight.predict.outlook_live import outlook_mode_of
from snowlight.predict.outlook_record import NOT_TAKEN8, NOT_TAKEN16, Record, unpack
from snowlight.predict.outlook_serve import OutlookServe
from snowlight.predict.publish import Mode, State
from snowlight.predict.serve import build_model
from snowlight.predict.situations import HeadsUp, WeatherClass
from snowlight.schemas.predictions import Forecast, OutlookReason, PredictionsFile
from snowlight.sources.nws.alerts import parse_active

GOLDEN = json.loads(night.GOLDEN.read_text(encoding="utf-8"))["digests"]
KS = outlook_module.STATES.index("KS")


def test_off_publishes_the_pass_before_s7f_byte_for_byte() -> None:
    files, run, _host = night.run_night()
    assert night.digests(files) == GOLDEN
    assert run.state.products == []
    assert run.state.outlook == {}
    assert "products" not in run.state.as_json()
    assert "outlook" not in run.state.as_json()


def test_shadow_publishes_as_off_and_keeps_a_private_record(capsys: Any) -> None:
    files, run, host = night.run_night(prepare=night.with_outlook(OutlookMode.SHADOW))
    assert night.digests(files) == GOLDEN
    assert list(host.files) == [night.KEY]  # nothing new is published
    out = capsys.readouterr().out
    assert "predict (shadow): outlook record:" in out
    content = learn.content_key(world.directory())
    record = Record.from_json(run.state.outlook, content, len(world.DISTRICTS))
    day = world.utc("2026-01-07T00:00").date()
    assert day in record.days
    entry = record.days[day]
    # Every Chicago sample from 09:00 (the first pass, 15:07Z) is taken; 08:00 is not
    # (no pass within 15 minutes after it): never imputed.
    chicago = [
        i for i, leaid in enumerate(world.DISTRICTS) if world.ZONES[leaid].endswith("Chicago")
    ]
    assert 0 not in entry.samples or "America/Chicago" not in entry.samples[0].taken
    taken = sorted(k for k, part in entry.samples.items() if "America/Chicago" in part.taken)
    assert taken == list(range(1, 21))
    # 20:00 (sample 12) in Kansas City: the watch is out for Missouri, the advisory in Kansas.
    c0, heads, bucket = unpack(entry.samples[12].values)
    mo, ks = 1, 0
    assert (int(c0[mo]), int(heads[mo])) == (WeatherClass.SNOW_WARNING, HeadsUp.NONE)
    assert (int(c0[ks]), int(heads[ks]), int(bucket[ks])) == (WeatherClass.ADVISORY, 0, 4)
    # At 16:00 (sample 8, 22Z): the watch, not yet upgraded, and Kansas quiet.
    c0, heads, bucket = unpack(entry.samples[8].values)
    assert (int(c0[mo]), int(heads[mo]), int(bucket[mo])) == (0, HeadsUp.WINTER_STORM_WATCH, 4)
    assert int(c0[ks]) == WeatherClass.ADVISORY  # issued at 22:00Z, the sample's hour exactly
    # The 8 PM chances: the file's and the outlook's, for every Chicago district.
    assert entry.chance_v2 is not None
    assert entry.chance_f is not None
    assert "America/Chicago" in entry.chance_v2.taken
    published = PredictionsFile.from_json_bytes(
        files[night.times().index(world.utc("2026-01-07T02:07"))] or b""
    )
    d = published.days.index(day)
    for i in chicago:
        day_entry = published.districts[i].days[d]
        assert isinstance(day_entry, Forecast)
        assert entry.chance_v2.values[i] == round(day_entry.p_no_school * 100)
        assert entry.chance_f.values[i] != NOT_TAKEN8
    # The 05:00 record: Kansas's advisory was cancelled at 03:00Z (21:00 the evening before):
    # none; Missouri woke up to the warning.
    assert entry.morning is not None
    assert int(entry.morning.values[ks]) == WeatherClass.NONE
    assert int(entry.morning.values[mo]) == WeatherClass.SNOW_WARNING
    assert run.state.outlook_health["at"]


def test_shadow_never_darkens_or_changes_a_pass(capsys: Any) -> None:
    def broken(*_args: Any) -> Any:
        raise RuntimeError("the reader broke")

    files, run, _host = night.run_night(
        prepare=night.with_outlook(OutlookMode.SHADOW, broken),
        at=night.times()[20:24],
    )
    off, _run, _host = night.run_night(at=night.times()[20:24])
    assert files == off
    assert "outlook shadow: RuntimeError: nothing recorded this pass" in capsys.readouterr().err
    assert run.state.outlook == {}


def test_a_sample_whose_forecast_did_not_read_is_skipped_never_imputed() -> None:
    read = night.fake_forecast(error_zones=frozenset({"America/Chicago"}))
    _files, run, _host = night.run_night(
        prepare=night.with_outlook(OutlookMode.SHADOW, read), at=[world.utc("2026-01-07T02:07")]
    )
    record = Record.from_json(
        run.state.outlook, learn.content_key(world.directory()), len(world.DISTRICTS)
    )
    day = world.utc("2026-01-07T00:00").date()
    sample = record.days[day].samples.get(12)
    assert sample is None or "America/Chicago" not in sample.taken
    if sample is not None:
        assert (sample.values[:4] == NOT_TAKEN16).all()


def test_a_stale_forecast_records_bucket_unknown_as_the_history_does() -> None:
    _files, run, _host = night.run_night(
        prepare=night.with_outlook(OutlookMode.SHADOW, night.fake_forecast(stale=True)),
        at=[world.utc("2026-01-07T02:07")],
    )
    record = Record.from_json(
        run.state.outlook, learn.content_key(world.directory()), len(world.DISTRICTS)
    )
    entry = record.days[world.utc("2026-01-07T00:00").date()]
    _c0, _heads, bucket = unpack(entry.samples[12].values)
    assert (bucket[:4] == 13).all()
    assert entry.chance_f is not None
    # The outlook's chance is the issued-alerts-only one (the identity): here the published
    # one, as the synthetic v3 rates are the v2 model's.
    assert entry.chance_v2 is not None
    assert np.array_equal(entry.chance_f.values[:4], entry.chance_v2.values[:4])
    stale = run.state.outlook_health["stale"]
    assert isinstance(stale, int)
    assert stale > 0


def quiet_pass(mode: OutlookMode, read: Any = None) -> tuple[PredictionsFile, cli.Pass]:
    """One pass at 8:07 PM in Kansas City with no alert at all."""
    host = MemoryHost()
    run = make_pass(host, mode=Mode.ON, directory=world.directory())
    now = world.utc("2026-01-07T02:07")
    run.now = lambda: now
    run.alerts = lambda: (parse_active(world.feed_bytes([], now.isoformat())), True)
    night.with_outlook(mode, read)(run)
    assert cli.one_pass(run) == 0
    return PredictionsFile.from_json_bytes(host.files[night.KEY]), run


def test_on_shows_the_outlook_line_and_it_sums_to_the_chance() -> None:
    made, _run = quiet_pass(OutlookMode.ON)
    assert made.forecast_at == night.run_time(world.utc("2026-01-07T02:07"))
    d = made.days.index(world.utc("2026-01-07T00:00").date())
    ks = made.districts[0].days[d]
    assert isinstance(ks, Forecast)
    line = ks.why.reasons[0]
    assert isinstance(line, OutlookReason)
    assert ks.why.base.points + line.points == round(ks.p_no_school * 100)
    assert line.points > 0
    assert line.now == 0  # nothing issued, no heads-up
    assert line.f == (0, 6.0, 9.0)  # 6.2 to 8.7 inches, rounded outward
    assert line.to == WeatherClass.SNOW_WARNING
    assert (line.scope, line.share) == (0, 60)  # Kansas: 180 of 300 cases
    assert line.like == (4, 4, 0)
    # The class it names moved the chance the way the points go (spec-f s. 8, ``became``).
    rates, _table = night.outlook_model()
    model = build_model(world.directory(), rates, world.CONFIG, lambda _x, _y: None)
    from snowlight.predict.serve import SITUATION_POSITION  # noqa: PLC0415

    to_rate = model.p_rate[0, SITUATION_POSITION["snow_warning"]]
    c0_rate = model.p_rate[0, SITUATION_POSITION["none"]]
    assert (to_rate - c0_rate) * line.points > 0
    # A quiet district keeps its base alone; Utah has no line.
    ut = made.districts[4].days[d]
    assert isinstance(ut, Forecast)
    assert not ut.why.reasons


def test_on_with_a_stale_forecast_serves_the_issued_alerts_only_chance(capsys: Any) -> None:
    made, _run = quiet_pass(OutlookMode.ON, night.fake_forecast(stale=True))
    assert made.forecast_at is None
    for entry in made.districts:
        for day in entry.days:
            assert not isinstance(day, Forecast) or not day.why.reasons
    assert "issued-alerts-only chance (identity)" in capsys.readouterr().out


def test_shadow_records_what_on_shows() -> None:
    made_on, _ = quiet_pass(OutlookMode.ON)
    _made, shadow = quiet_pass(OutlookMode.SHADOW)
    record = Record.from_json(
        shadow.state.outlook, learn.content_key(world.directory()), len(world.DISTRICTS)
    )
    day_of = world.utc("2026-01-07T00:00").date()
    entry = record.days[day_of]
    assert entry.chance_f is not None
    d = made_on.days.index(day_of)
    for i, district in enumerate(made_on.districts):
        if world.ZONES[world.DISTRICTS[i]] != "America/Chicago":
            continue
        day = district.days[d]
        assert isinstance(day, Forecast)
        assert int(entry.chance_f.values[i]) == round(day.p_no_school * 100)


@pytest.mark.parametrize(
    ("value", "mode"),
    [(None, OutlookMode.OFF), ("", OutlookMode.OFF), ("shadow", OutlookMode.SHADOW),
     (" On ", OutlookMode.ON)],
)  # fmt: skip
def test_the_switch(value: str | None, mode: OutlookMode) -> None:
    assert outlook_mode_of(value) is mode


def test_the_switch_refuses_anything_else() -> None:
    with pytest.raises(ValueError, match="PREDICT_OUTLOOK"):
        outlook_mode_of("maybe")


def test_the_state_round_trips_the_outlook_keys() -> None:
    _files, run, _host = night.run_night(
        prepare=night.with_outlook(OutlookMode.SHADOW), at=night.times()[22:24]
    )
    kept = State.from_json(json.loads(json.dumps(run.state.as_json())))
    assert kept.products == run.state.products
    assert kept.outlook == run.state.outlook
    assert kept.products_since == run.state.products_since
    assert np.isfinite(timedelta(seconds=1).total_seconds())


# --- what a line may say -------------------------------------------------------------------------


def test_a_line_s_share_is_true_of_the_raw_count_of_every_place_it_names() -> None:
    from snowlight.predict.outlook_serve import says  # noqa: PLC0415
    from snowlight.predict.share import says_true  # noqa: PLC0415

    _rates, table = night.outlook_model()
    rng = np.random.default_rng(7)
    for _trial in range(300):
        cell = int(rng.integers(0, table.nation.shape[0]))
        state = int(rng.integers(-1, len(outlook_module.STATES)))
        to = int(rng.integers(0, 8))
        found = says(table, cell, state, to)
        if found is None:
            continue
        scope, share = found
        counts = (
            table.state[state, cell]
            if scope == 0
            else table.region[outlook_module.REGION_OF_STATE[state], cell]
            if scope == 1
            else table.nation[cell]
        )
        y, n = float(counts[to]), float(counts.sum())
        assert y > 0
        assert says_true(np.array([share]), np.array([y]), np.array([n]), 0.05).all(), (y, n, share)
        assert (share == 100) == (y == n)  # "every case" exactly when every case


def test_a_share_says_every_case_only_when_every_case_ended_so() -> None:
    from dataclasses import replace  # noqa: PLC0415

    from snowlight.predict.outlook_serve import says  # noqa: PLC0415

    _rates, table = night.outlook_model()
    cell = outlook_module.cell_index(5, 0, 0, 4)
    assert table.nights_state[KS, cell] >= 20
    warned = int(WeatherClass.SNOW_WARNING)
    for hits, others, want in ((400, 0, 100), (399, 1, 99), (1, 399, 1), (0, 400, None)):
        state = table.state.copy()
        state[KS, cell] = 0
        state[KS, cell, warned] = hits
        state[KS, cell, int(WeatherClass.NONE)] = others
        found = says(replace(table, state=state), cell, KS, warned)
        if want is None:
            assert found is None or found[0] > 0  # no share of none at the state: it moves up
        else:
            assert found == (0, want)


def test_a_merged_cell_s_line_names_the_merged_cell_and_its_scope() -> None:
    from snowlight.predict.outlook_serve import says  # noqa: PLC0415

    _rates, table = night.outlook_model()
    # Slot 5, nothing issued, 9+ inches (bucket 5): no case of its own anywhere, so it is backed
    # off to a merged cell that holds 6-9 inches' 60 nights (the ladder's nearer bucket first).
    cell = outlook_module.cell_index(5, 0, 0, 5)
    like = table.likes[cell]
    assert like.low < 5 <= like.high
    assert like.heads == 0
    assert table.nights_state[KS, cell] >= 20  # the merged cell's nights at Kansas
    scope, share = says(table, cell, KS, int(WeatherClass.SNOW_WARNING)) or (None, None)
    assert scope == 0
    counts = table.state[KS, cell]
    assert share == round(100 * counts[5] / counts.sum())
    # A state with no case of the merged cell names its region, then the nation.
    ny = outlook_module.STATES.index("NY")
    assert says(table, cell, ny, int(WeatherClass.SNOW_WARNING))[0] == 2  # type: ignore[index]
    # A class no place counts in the cell gives no line.
    assert says(table, cell, KS, int(WeatherClass.TROPICAL)) is None


@pytest.mark.parametrize(
    ("bucket", "given", "expected"),
    [
        (4, {"snow_low": 6.2, "snow_high": 8.7}, (0, 6.0, 9.0)),
        (4, {"snow_low": 6.0, "snow_high": 9.0}, (0, 6.0, 9.0)),
        (7, {"ice_low": 0.104, "ice_high": 0.2201}, (1, 0.1, 0.23)),
        (11, {"feels_low": -18.4, "feels_high": -10.2}, (2, -19.0, -10.0)),
        (0, {}, None),
        (11, {"feels_low": None, "feels_high": -10.2}, None),
        (4, {"snow_low": float("nan"), "snow_high": 8.0}, None),
    ],
)
def test_a_forecast_range_is_rounded_outward_or_not_said(
    bucket: int, given: dict[str, float | None], expected: tuple[int, float, float] | None
) -> None:
    from snowlight.predict.forecast_values import DistrictForecast  # noqa: PLC0415
    from snowlight.predict.outlook_serve import f_range  # noqa: PLC0415

    assert f_range(bucket, DistrictForecast(code=bucket, **given)) == expected  # type: ignore[arg-type]


def test_an_unknown_bucket_has_no_range() -> None:
    from snowlight.predict.outlook_serve import f_range  # noqa: PLC0415

    with pytest.raises(ValueError, match="bucket 13"):
        f_range(13, None)


def test_the_own_class_guard_publishes_no_number_for_a_class_with_no_rate() -> None:
    from snowlight.predict.forecast_values import DistrictForecast, Forecasts  # noqa: PLC0415
    from snowlight.predict.outlook_serve import Inputs, outlook_chances  # noqa: PLC0415

    rates, table = night.outlook_model()
    model = build_model(world.directory(), rates, world.CONFIG, lambda _x, _y: None)
    model.p_rate = model.p_rate.copy()
    model.p_rate[0, :] = np.nan  # district 0 has no rate in any situation
    serve = OutlookServe.of(model, table)
    day = world.utc("2026-01-07T00:00").date()
    forecasts = Forecasts({day: {i: DistrictForecast(code=4, snow_low=6.0, snow_high=8.0)
                                 for i in range(5)}})  # fmt: skip
    inputs = Inputs(
        c0=np.zeros((5, 1), dtype=np.int64),
        heads=np.zeros((5, 1), dtype=np.int64),
        after=np.zeros((5, 1), dtype=np.bool_),
        slot=np.full((5, 1), 5, dtype=np.int64),
        bucket=np.full((5, 1), 4, dtype=np.int64),
        forecasts=forecasts,
        days=(day,),
    )
    found = outlook_chances(serve, inputs, floor=0.01, ceiling=0.99)
    assert found.no_rate == 1
    assert np.isnan(found.p[0, 0])
    assert np.isnan(found.base[0, 0])
    assert (0, 0) not in found.lines
    assert np.isfinite(found.p[1:, 0]).all()


def test_on_with_a_stale_forecast_goes_dark_only_when_the_config_says_dark(capsys: Any) -> None:
    serve = world.CONFIG.serve.model_copy(update={"forecast_stale": "dark"})
    config = world.CONFIG.model_copy(update={"serve": serve})
    host = MemoryHost()
    run = make_pass(host, mode=Mode.ON, directory=world.directory(), config=config)
    now = world.utc("2026-01-07T02:07")
    run.now = lambda: now
    run.alerts = lambda: (parse_active(world.feed_bytes([], now.isoformat())), True)
    night.with_outlook(OutlookMode.ON, night.fake_forecast(stale=True))(run)
    assert cli.one_pass(run) == cli.EXIT_DARK
    assert "forecast_stale" in capsys.readouterr().err


def test_an_outlook_file_over_the_budget_steps_down_to_the_issued_alerts_only_chances() -> None:
    made, _run = quiet_pass(OutlookMode.ON)
    size = len(made.to_json_bytes())
    serve = world.CONFIG.serve.model_copy(update={"budget_raw_bytes": size - 1})
    config = world.CONFIG.model_copy(update={"serve": serve})
    host = MemoryHost()
    run = make_pass(host, mode=Mode.ON, directory=world.directory(), config=config)
    now = world.utc("2026-01-07T02:07")
    run.now = lambda: now
    run.alerts = lambda: (parse_active(world.feed_bytes([], now.isoformat())), True)
    night.with_outlook(OutlookMode.ON)(run)
    assert cli.one_pass(run) == 0
    smaller = PredictionsFile.from_json_bytes(host.files[night.KEY])
    assert smaller.forecast_at is None
    assert all(
        not isinstance(day, Forecast) or not any(r.kind == "outlook" for r in day.why.reasons)
        for entry in smaller.districts
        for day in entry.days
    )


def test_the_loop_runs_a_pass_for_the_outlook_only_when_it_is_on() -> None:
    from snowlight.predict.cli import outlook_changed  # noqa: PLC0415

    run = make_pass(MemoryHost(), directory=world.directory())
    run.serve_model(world.directory())
    last = world.utc("2026-01-07T01:20")  # 7:20 PM in Kansas City: slot 4
    assert not outlook_changed(run, last, world.utc("2026-01-07T01:27"))  # off
    run.outlook_mode = OutlookMode.SHADOW
    assert not outlook_changed(run, last, world.utc("2026-01-07T01:35"))
    run.outlook_mode = OutlookMode.ON
    assert not outlook_changed(run, last, world.utc("2026-01-07T01:27"))
    assert outlook_changed(run, last, world.utc("2026-01-07T01:31"))  # 7:31 PM: slot 5
    assert outlook_changed(run, world.utc("2026-01-07T11:55"), world.utc("2026-01-07T12:01"))  # 12Z
    assert not outlook_changed(run, None, world.utc("2026-01-07T01:31"))
    run.outlook_newest = lambda _now: world.utc("2026-01-07T00:46")
    run.state.outlook_health = {"forecast_run": "2026-01-06T23:46:00+00:00"}
    assert outlook_changed(run, last, world.utc("2026-01-07T01:27"))
    run.state.outlook_health = {"forecast_run": "2026-01-07T00:46:00+00:00"}
    assert not outlook_changed(run, last, world.utc("2026-01-07T01:27"))


def test_the_predict_workflow_runs_the_outlook_in_shadow() -> None:
    import yaml  # type: ignore[import-untyped, unused-ignore]  # noqa: PLC0415

    workflow = yaml.safe_load(
        (night.GOLDEN.parents[4] / ".github" / "workflows" / "predict.yml").read_text()
    )
    env = workflow["jobs"]["predict"]["env"]
    assert env["PREDICT_OUTLOOK"] == "${{ vars.PREDICT_OUTLOOK || 'shadow' }}"
    assert world.CONFIG.serve.forecast_stale == "identity"


# --- the golden table the web derives the slot and the window from -------------------------------

SLOTS = night.GOLDEN.parent / "outlook_slots.json"
"""Shared with web/src/data/tests/outlook-slots.test.ts: for each zone, school day and file
time, the slot (spec-f s. 5) and the forecast window's start and end on the school's clock.
Set SNOWLIGHT_WRITE_GOLDEN=1 to write it again after a deliberate change."""


def slot_rows() -> list[dict[str, object]]:
    from datetime import UTC, date, datetime  # noqa: PLC0415
    from zoneinfo import ZoneInfo  # noqa: PLC0415

    from snowlight.predict.outlook_states import slot_at  # noqa: PLC0415

    zones = ("America/New_York", "America/Chicago", "America/Denver", "America/Phoenix",
             "America/Los_Angeles")  # fmt: skip
    days = (date(2026, 1, 7), date(2026, 3, 9), date(2026, 11, 2))
    rows: list[dict[str, object]] = []
    for zone in zones:
        tz = ZoneInfo(zone)
        for day in days:
            start = datetime(day.year, day.month, day.day, tzinfo=UTC)
            for hours in range(-30, 21, 1):
                for minute in (0, 31):
                    at = start + timedelta(hours=hours, minutes=minute)
                    rows.append(
                        {
                            "zone": zone,
                            "day": day.isoformat(),
                            "at": at.isoformat().replace("+00:00", "Z"),
                            "slot": slot_at(day, zone, at),
                            "window_from": start.astimezone(tz).strftime("%H:%M"),
                            "window_until": (start + timedelta(hours=18))
                            .astimezone(tz)
                            .strftime("%H:%M"),
                        }
                    )
    return rows


def test_the_slot_golden_is_the_pipeline_s() -> None:
    import os  # noqa: PLC0415

    rows = slot_rows()
    if os.environ.get("SNOWLIGHT_WRITE_GOLDEN") == "1":
        lines = ",\n".join(json.dumps(row, separators=(",", ":")) for row in rows)
        SLOTS.write_text(f"[\n{lines}\n]\n", encoding="utf-8")
    assert json.loads(SLOTS.read_text(encoding="utf-8")) == rows
    assert {row["slot"] for row in rows} == set(range(8))


OUTLOOK_GOLDEN = night.GOLDEN.parent / "synthetic_outlook.json"
"""The outlook's contract golden: the file a pass with the outlook on writes at 8:07 PM in
Kansas City with no alert and a SYNTHETIC 6 to 9 inch forecast for two districts, read by
web/src/data/tests/predictions.contract.test.ts. SNOWLIGHT_WRITE_GOLDEN=1 writes it again."""


def test_the_outlook_golden_is_the_pass_s() -> None:
    import os  # noqa: PLC0415

    made, _run = quiet_pass(OutlookMode.ON)
    data = made.to_json_bytes()
    if os.environ.get("SNOWLIGHT_WRITE_GOLDEN") == "1":
        OUTLOOK_GOLDEN.write_bytes(data)
    assert OUTLOOK_GOLDEN.read_bytes() == data
    lines = [
        reason
        for entry in made.districts
        for day in entry.days
        if isinstance(day, Forecast)
        for reason in day.why.reasons
        if isinstance(reason, OutlookReason)
    ]
    assert len(lines) == 2  # Kansas's and Missouri's districts with the 6 to 9 inch forecast


def test_the_longest_outlook_line_is_what_the_size_note_counts() -> None:
    """The longest line any district-day can carry (docs/predict.md, Size: 108 bytes)."""
    longest = 0
    for f in ((2, -80.0, -80.0), (1, 99.99, 119.99), (0, 100.0, 120.0), None):
        for points in (-100, -99, 99):
            line = OutlookReason(
                kind="outlook", points=points, now=11, f=f, like=(13, 13, 6), to=7, share=100,
                scope=2,
            )  # fmt: skip
            longest = max(longest, len(json.dumps(line.to_json_value(), separators=(",", ":"))))
    assert longest == 108


def test_a_district_that_read_another_run_keeps_the_issued_alerts_only_chance() -> None:
    base = night.fake_forecast()

    def mixed(*args: Any) -> Any:
        found = base(*args)
        older = {}
        for day, by_district in found.by_day.items():
            mine = dict(by_district)
            given = mine.get(1)
            if given is not None and given.run_time is not None:
                mine[1] = replace(given, run_time=given.run_time - timedelta(hours=1))
            older[day] = mine
        return replace(found, by_day=older)

    made, _run = quiet_pass(OutlookMode.ON, mixed)
    d = made.days.index(world.utc("2026-01-07T00:00").date())
    ks, mo = made.districts[0].days[d], made.districts[1].days[d]
    assert isinstance(ks, Forecast)
    assert isinstance(mo, Forecast)
    assert [r.kind for r in ks.why.reasons] == ["outlook"]
    assert not mo.why.reasons  # its run is not the file's forecast_at: no line
    off, _ = quiet_pass(OutlookMode.ON, night.fake_forecast({"2000004": (4, 6.2, 8.7)}))
    plain = off.districts[1].days[d]
    assert isinstance(plain, Forecast)
    assert (mo.p_no_school, mo.p_delay) == (plain.p_no_school, plain.p_delay)


def test_the_worded_share_is_the_configured_covered_share() -> None:
    """The outlook's line says what is out as covering half a district's schools
    (``web/src/copy-chance.ts``, held to the same config by ``web/src/data/tests/
    outlook.test.ts``): the class rule's share in config/predict.yaml must be that half, or
    every such sentence would be false."""
    from snowlight.predict.config import PredictConfig  # noqa: PLC0415
    from snowlight.predict.outlook_serve import WORDED_SHARE  # noqa: PLC0415

    assert PredictConfig.load().weather.covered_share == WORDED_SHARE == 0.5
