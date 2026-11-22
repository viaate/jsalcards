"""The whole Flights pipeline on a made-up history: fit, test, files, live pass, monthly score."""

import dataclasses
import gzip
import itertools
import json
import shutil
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from flights.synth import AIRPORTS, bulletin, calm, world
from snowlight.flights import (
    airports,
    artifact,
    build,
    cli,
    fetch,
    history,
    inputs,
    live,
    monthly,
    nbs,
    replays,
    spans,
    train,
)
from snowlight.flights import model as fm
from snowlight.flights.bts import Month, kept_months, scan
from snowlight.schemas.flights import (
    FlightsAlert,
    FlightsArchive,
    FlightsHeld,
    FlightsLive,
    FlightsProgram,
    FlightsRecord,
    FlightsTrackRecord,
    FlightsVerdict,
    FlightsWhy,
)
from snowlight.schemas.site import validate_site


def _github_fake() -> type:
    """The live host's SYNTHETIC GitHub (tests/live/github_fake.py), loaded by its path."""
    import importlib.util  # noqa: PLC0415
    import sys  # noqa: PLC0415

    name = "flights_github_fake"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, Path(__file__).resolve().parents[1] / "live" / "github_fake.py"
        )
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    fake: type = sys.modules[name].GitHubFake
    return fake


GitHubFake = _github_fake()
FIRST = date(2023, 10, 1)
"""The made-up history starts a year before the fit's first run, so the oldest fit rows have
usual rates from the year before their own period."""
FIRST_RUN = date(2024, 10, 1)
LAST = date(2026, 9, 30)


@pytest.fixture(scope="module")
def raw(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("raw")
    world(root, FIRST, LAST)
    return root


@pytest.fixture(autouse=True)
def synthetic_airports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "airports.json"
    airports.dump(AIRPORTS, path)
    monkeypatch.setattr(airports, "AIRPORTS_FILE", path)


@pytest.fixture(scope="module")
def trained(raw: Path, tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    out = tmp_path_factory.mktemp("out")
    path = out / "model.json.gz"
    with pytest.MonkeyPatch.context() as patch:
        table = out / "airports.json"
        airports.dump(AIRPORTS, table)
        patch.setattr(airports, "AIRPORTS_FILE", table)
        assert build.train_all(raw, out, path, FIRST_RUN) == 0
    return out, path


def test_the_split_is_the_newest_twelve_months(raw: Path) -> None:
    assert kept_months(raw / "bts")[-1] == Month(2026, 9)
    cut = train.split(Month(2026, 9))
    assert (cut.test_first, cut.test_last) == (date(2025, 10, 1), date(2026, 9, 30))


def test_the_model_learns_snow_and_passes_only_where_it_beats_the_usual_rate(
    trained: tuple[Path, Path],
) -> None:
    out, path = trained
    made = artifact.read(path)
    assert made.model.is_published("AAA", "dep_canc", 1)
    # No day is whole three evenings ahead: no rough-day chance is published for lead 3.
    assert not any(made.model.is_published(a.code, "rough", 3) for a in AIRPORTS)
    report = (out / "heldout.md").read_text()
    assert "## Where a chance is published" in report
    assert "AAA | 1" in report
    assert "A flight's cancel chance" in report
    track = FlightsTrackRecord.from_json_bytes(
        (out / "files/flights/track-record.json").read_bytes()
    )
    lead1 = next(t for t in track.tests if int(t.target) == 0 and t.lead == 1)
    assert lead1.skill > 0
    gate = {g.code: g.passed for g in track.airports}
    assert gate["AAA"][0] & 1
    summary = json.loads((out / "summary.json").read_text())
    assert summary["replays"]
    index = json.loads((out / "files/flights/replays/index.json").read_text())
    assert index["replays"][0]["code"] == "AAA"


def test_static_files_are_valid(raw: Path, tmp_path: Path) -> None:
    assert build.static_all(raw, tmp_path) == 0
    record = FlightsRecord.from_json_bytes(
        (tmp_path / "files/flights/records/aaa.json").read_bytes()
    )
    # No other airport has snow on its snow days: no matched day, so no snow line at all.
    assert all(int(line.kind) != 2 for line in record.lines)
    assert all(line.verdict == FlightsVerdict.NONE for line in record.lines)
    routes = json.loads((tmp_path / "files/flights/routes/aaa.json").read_text())
    assert routes["months"][0]["flights"][0]["to_airport"] == "BBB"
    assert (tmp_path / "files/flights/airports.json").is_file()


NOW = datetime(2026, 11, 21, 18, 10, tzinfo=UTC)  # 12:10 in AAA, 13:10 in BBB
RUN_20 = datetime(2026, 11, 20, 0, tzinfo=UTC)
RUN_21 = datetime(2026, 11, 21, 0, tzinfo=UTC)
RUN_22 = datetime(2026, 11, 22, 0, tzinfo=UTC)


def _station_runs(run: datetime, *, snow: bool) -> list[nbs.StationRun]:
    heavy = [None if i % 2 else 60 for i in range(23)]
    rows = (
        calm(S06=heavy, PSN=[95] * 23, P06=[None if i % 2 else 90 for i in range(23)])
        if snow
        else calm()
    )
    return list(nbs.parse(bulletin(run, {"KAAA": rows, "KBBB": calm()})))


def _runs(snow: bool) -> list[nbs.StationRun]:
    return _station_runs(RUN_20, snow=snow) + _station_runs(RUN_21, snow=snow)


def _observed(snow_hours: int = 0, end: datetime = RUN_21) -> pl.DataFrame:
    """Hourly report flags read for the observed-before inputs: AAA's last ``snow_hours`` hours
    before ``end`` with falling snow, the rest calm."""
    rows = [
        {
            "station": station,
            "hour": end - timedelta(hours=back),
            "frz": False,
            "snow": station == "AAA" and back <= snow_hours,
            "thunder": False,
            "fog": False,
            "wind": False,
        }
        for station in ("AAA", "BBB")
        for back in range(1, 50)
    ]
    return pl.DataFrame(rows).with_columns(pl.col("hour").cast(pl.Datetime("us", "UTC")))


def _pass(
    made: artifact.Artifact,
    runs: list[nbs.StationRun],
    now: datetime,
    observed: pl.DataFrame | None = None,
) -> FlightsLive:
    read = live.Inputs(runs=runs, observed=_observed() if observed is None else observed)
    return live.Pass(artifact=made, airports=AIRPORTS, now=now, read=read).build()


def test_a_live_pass_shows_chances_usual_rates_and_what_was_not_read(
    trained: tuple[Path, Path],
) -> None:
    _, path = trained
    made = artifact.read(path)
    for key in list(made.model.published):
        if key[0] == "BBB":
            made.model.published[key] = False
    read = live.Inputs(runs=_runs(snow=True), weather=None, observed=_observed())
    document = live.Pass(artifact=made, airports=AIRPORTS, now=NOW, read=read).build()
    assert document.programs_at is None
    assert document.alerts_at is None
    assert document.weather_at is None
    assert document.run == RUN_21
    aaa, bbb = document.airports
    assert aaa.today == date(2026, 11, 21)
    # Today and tomorrow from the newest run that covers them whole; the day after from it
    # too (lead 3), up to the blocks it covers whole: its evening and night have no value.
    assert aaa.runs == (RUN_21, RUN_21, RUN_21)
    assert aaa.dep_canc[2][3] is None
    assert aaa.dep_canc[2][4] is None
    # Early and morning are over.
    assert aaa.dep_canc[0][0] is None
    assert aaa.dep_canc[0][1] is None
    tomorrow = aaa.dep_canc[1]
    assert all(v is not None for v in tomorrow)
    # The rest of today, from the evening before's run: the snow shows (tenths of a percent).
    assert max(v for v in aaa.dep_canc[0][2:] if v is not None) >= 200
    assert aaa.usual[0][0] == 0  # dep_canc today: the model's chances
    assert bbb.usual[0][1] == 31  # BBB shows its usual rate in every block
    assert 0 in [int(w) for w in aaa.why[1]]  # snow
    # A small usual rate is published in tenths of a percent, never as 0.
    assert all(v is not None and v > 0 for v in bbb.dep_canc[1])
    files = live.files(document)
    assert set(files) == {f"flights/live/{document.slot}.json", "flights/latest.json"}
    FlightsLive.from_json_bytes(files[f"flights/live/{document.slot}.json"])


def test_a_value_that_does_not_fit_the_file_leaves_out_that_value_or_airport_alone(
    trained: tuple[Path, Path],
) -> None:
    _, path = trained
    made = artifact.read(path)
    at = NOW - timedelta(minutes=20)
    weather = {
        "AAA": inputs.Report(at=at, kinds=(), visibility=150.0, gust=999),
        "BBB": inputs.Report(at=at, kinds=(), visibility=-1.0, gust=10),
    }
    faa = (NOW, [inputs.Program("AAA", FlightsProgram.GROUND_DELAY, 5000, None, "")])
    read = live.Inputs(
        runs=_runs(snow=True), observed=_observed(), weather=weather, weather_at=NOW, faa=faa
    )
    document = live.Pass(artifact=made, airports=AIRPORTS, now=NOW, read=read).build()
    aaa, bbb = document.airports
    assert aaa.now is not None
    assert (aaa.now.visibility, aaa.now.gust) == (None, None)
    assert bbb.now is not None
    assert (bbb.now.visibility, bbb.now.gust) == (None, None)
    assert aaa.programs is not None
    assert aaa.programs[0].minutes is None
    FlightsLive.from_json_bytes(live.files(document)[f"flights/live/{document.slot}.json"])
    snapshot = live.archive_document(document, read, made, {}, date(2026, 11, 22))
    assert [r.code for r in snapshot.reports] == ["AAA", "BBB"]
    # An airport whose entry makes but does not fit the file as read back (a report of the
    # year 1) shows its marked usual rate alone (LR-F3); the pass and the rest go on.
    old = datetime(1, 1, 1, tzinfo=UTC)
    odd = dataclasses.replace(
        read, weather={**weather, "BBB": dataclasses.replace(weather["BBB"], at=old)}
    )
    document = live.Pass(artifact=made, airports=AIRPORTS, now=NOW, read=odd).build()
    aaa, bbb = document.airports
    assert aaa.runs == (RUN_21, RUN_21, RUN_21)
    assert aaa.now is not None
    assert bbb.runs == (None, None, None)
    assert bbb.now is None
    assert bbb.rough_usual == 7
    assert all(v is not None for v in bbb.dep_canc[1])
    assert bbb.usual[0][1] == 31  # every block of tomorrow marked the usual rate
    assert bbb.dep_canc[1][0] == live.per_mille(made.usual("dep", "canc", "BBB", 0, 11))
    FlightsLive.from_json_bytes(live.files(document)[f"flights/live/{document.slot}.json"])
    # A source time that does not fit the file at all: that source alone as not read, at the
    # file and at every airport (never an empty list under it); the others unaffected.
    late = dataclasses.replace(read, faa=(old, faa[1]))
    document = live.Pass(artifact=made, airports=AIRPORTS, now=NOW, read=late).build()
    assert document.programs_at is None
    assert document.run == RUN_21
    assert document.weather_at == NOW
    assert [a.code for a in document.airports] == ["AAA", "BBB"]
    assert all(a.programs is None for a in document.airports)
    assert document.airports[0].runs == (RUN_21, RUN_21, RUN_21)
    FlightsLive.from_json_bytes(live.files(document)[f"flights/live/{document.slot}.json"])
    # A run time that does not fit: no chance made from it is shown, every airport at its usual
    # rate with every source as not read.
    odd_run = live.Pass(artifact=made, airports=AIRPORTS, now=NOW, read=read)
    odd_run.build()
    assert not odd_run._fits("run", old)
    assert odd_run._fits("run", RUN_21)
    # The FAA or NWS not read at all: every airport's programs (or alerts) as not read.
    unread = dataclasses.replace(read, faa=None, alerts=None)
    document = live.Pass(artifact=made, airports=AIRPORTS, now=NOW, read=unread).build()
    assert (document.programs_at, document.alerts_at) == (None, None)
    assert all(a.programs is None and a.alerts is None for a in document.airports)
    # An airport whose usual rate cannot be written either is left out, the rest go on.
    broken = [AIRPORTS[0], dataclasses.replace(AIRPORTS[1], code="TOOLONG")]
    document = live.Pass(artifact=made, airports=broken, now=NOW, read=read).build()
    assert [a.code for a in document.airports] == ["AAA"]


def test_an_airport_whose_chance_fails_keeps_its_programs_alerts_and_report(
    trained: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    # AAA is under a ground stop and an alert when its chance path raises: its marked usual
    # rate goes out with the program, the alert and the report as read (R5-B1), never an empty
    # list under a set programs_at or alerts_at.
    _, path = trained
    made = artifact.read(path)
    at = NOW - timedelta(minutes=20)
    weather = {"AAA": inputs.Report(at=at, kinds=(), visibility=2.0, gust=30)}
    faa = (NOW, [inputs.Program("AAA", FlightsProgram.GROUND_STOP, None, None, "")])
    alerts = (NOW, {"AAA": [FlightsAlert(0)]})
    read = live.Inputs(
        runs=_runs(snow=True),
        observed=_observed(),
        weather=weather,
        weather_at=NOW,
        faa=faa,
        alerts=alerts,
    )
    real = live.Pass._chance

    def failing(self: live.Pass, airport: Any, *args: Any) -> tuple[int, bool]:
        if airport.code == "AAA":
            raise ValueError("a model path that does not fit")
        return real(self, airport, *args)

    monkeypatch.setattr(live.Pass, "_chance", failing)
    document = live.Pass(artifact=made, airports=AIRPORTS, now=NOW, read=read).build()
    aaa, bbb = document.airports
    assert document.programs_at == NOW
    assert document.alerts_at == NOW
    assert aaa.runs == (None, None, None)
    assert aaa.rough_usual == 7
    assert aaa.programs is not None
    assert [p.program for p in aaa.programs] == [FlightsProgram.GROUND_STOP]
    assert aaa.alerts == (FlightsAlert(0),)
    assert aaa.now is not None
    assert aaa.now.gust == 30
    assert bbb.runs == (RUN_21, RUN_21, RUN_21)
    assert bbb.programs == ()
    assert bbb.alerts == ()
    FlightsLive.from_json_bytes(live.files(document)[f"flights/live/{document.slot}.json"])

    # A part that does not fit on its own is marked not read, never published empty.
    def odd(_: inputs.Program) -> Any:
        raise ValueError("odd program")

    monkeypatch.setattr(live, "program_now", odd)
    document = live.Pass(artifact=made, airports=AIRPORTS, now=NOW, read=read).build()
    assert document.programs_at == NOW
    assert document.airports[0].programs is None
    assert document.airports[0].alerts == (FlightsAlert(0),)


def test_a_source_time_after_the_pass_is_published_as_the_pass_time(
    trained: tuple[Path, Path],
) -> None:
    # A station or source clock a few minutes ahead (within the clock bound) never publishes a
    # time after generated_at: a reader's age never goes below zero (R5-S1).
    _, path = trained
    made = artifact.read(path)
    ahead = NOW + timedelta(minutes=9)
    weather = {"AAA": inputs.Report(at=ahead, kinds=(), visibility=2.0, gust=None)}
    read = live.Inputs(
        runs=_runs(snow=True),
        observed=_observed(),
        weather=weather,
        weather_at=ahead,
        faa=(ahead, []),
        alerts=(ahead, {}),
    )
    document = live.Pass(artifact=made, airports=AIRPORTS, now=NOW, read=read).build()
    for moment in (document.programs_at, document.alerts_at, document.weather_at):
        assert moment == NOW
    aaa = document.airports[0]
    assert aaa.now is not None
    assert aaa.now.at == NOW
    snapshot = live.archive_document(document, read, made, {}, date(2026, 11, 22))
    assert all(r.report.at <= document.generated_at for r in snapshot.reports)


def test_an_airport_whose_own_reports_lag_shows_the_usual_rate(
    trained: tuple[Path, Path],
) -> None:
    made = artifact.read(trained[1])
    for key in list(made.model.published):
        made.model.published[key] = True
    flags = _observed().filter(
        (pl.col("station") == "AAA") | (pl.col("hour") < RUN_21 - timedelta(hours=4))
    )
    read = live.Inputs(runs=_runs(snow=True), observed=flags)
    document = live.Pass(artifact=made, airports=AIRPORTS, now=NOW, read=read).build()
    assert document.observed_at == RUN_21 - timedelta(hours=1)
    aaa, bbb = document.airports
    assert aaa.usual[0][1] == 0  # AAA's own reports reach the run: the model's chances
    assert bbb.usual[0][1] == 31  # BBB's end 5 hours before it: the usual rate everywhere
    assert all(v is None or bbb.rough_usual >> day & 1 for day, v in enumerate(bbb.rough))
    empty = live.Inputs(runs=_runs(snow=True), observed=flags.clear())
    none = live.Pass(artifact=made, airports=AIRPORTS, now=NOW, read=empty).build()
    assert none.observed_at is None
    assert none.airports[0].usual[0][1] == 31


def test_without_the_observed_reports_every_chance_is_the_usual_rate(
    trained: tuple[Path, Path],
) -> None:
    made = artifact.read(trained[1])
    for key in list(made.model.published):
        made.model.published[key] = True
    read = live.Inputs(runs=_runs(snow=True), observed=None)
    aaa = live.Pass(artifact=made, airports=AIRPORTS, now=NOW, read=read).build().airports[0]
    # Not knowing whether a storm already came, no chance is shown: every value is marked usual.
    for day, masks in enumerate(zip(*aaa.usual, strict=True)):
        for target, mask in enumerate(masks):
            values = [aaa.dep_canc, aaa.dep_late, aaa.arr_canc, aaa.arr_late][target][day]
            for block, value in enumerate(values):
                if value is not None:
                    assert mask >> block & 1
    for day, value in enumerate(aaa.rough):
        assert value is None or aaa.rough_usual >> day & 1
    assert aaa.rough[0] is not None


def test_the_day_after_a_storm_shows_the_usual_rate_where_those_days_did_not_pass(
    trained: tuple[Path, Path],
) -> None:
    made = artifact.read(trained[1])
    for key in list(made.model.published):
        made.model.published[key] = True
    made.model.after = dict.fromkeys(made.model.fitted, False)
    calm_after = _pass(made, _runs(snow=True), NOW).airports[0]
    stormy = _pass(made, _runs(snow=True), NOW, _observed(snow_hours=fm.AFTER_STORM_HOURS))
    aaa = stormy.airports[0]
    assert calm_after.usual[0][0] == 0
    # Today's open blocks (afternoon on) come from the run after the storm: usual rates.
    assert aaa.usual[0][0] & 0b11100 == 0b11100
    assert FlightsWhy.BEFORE in aaa.why[0]  # the why names the storm that came
    made.model.after = dict.fromkeys(made.model.fitted, True)
    shown = _pass(made, _runs(snow=True), NOW, _observed(snow_hours=fm.AFTER_STORM_HOURS))
    assert shown.airports[0].usual[0][0] == 0


def test_a_newer_run_never_replaces_the_whole_rows_of_the_tested_run(
    trained: tuple[Path, Path],
) -> None:
    made = artifact.read(trained[1])
    alone = _pass(made, _station_runs(RUN_21, snow=True), NOW)
    # A later run of the same day (not 00Z) and the next 00Z run's partial or own-day rows
    # never mix into today: the chances stay those of the evening before's run.
    late_run = _station_runs(datetime(2026, 11, 21, 16, tzinfo=UTC), snow=False)
    mixed = _pass(made, _station_runs(RUN_21, snow=True) + late_run, NOW)
    assert mixed.airports[0].dep_canc == alone.airports[0].dep_canc
    assert mixed.airports[0].rough == alone.airports[0].rough
    assert mixed.run == RUN_21
    # At 20:00 in AAA on the 21st the 22nd's 00Z run is out: the 21st's night still comes
    # from the 21st's run (lead 1), the 22nd from the 22nd's.
    evening = datetime(2026, 11, 22, 2, 0, tzinfo=UTC)
    reports = _observed(end=RUN_22)
    both = _pass(
        made,
        _station_runs(RUN_21, snow=True) + _station_runs(RUN_22, snow=False),
        evening,
        reports,
    )
    aaa = both.airports[0]
    assert aaa.today == date(2026, 11, 21)
    assert aaa.runs[0] == RUN_21
    assert aaa.runs[1] == RUN_22
    only_21 = _pass(made, _station_runs(RUN_21, snow=True), evening, reports).airports[0]
    assert aaa.dep_canc[0] == only_21.dep_canc[0]
    assert aaa.dep_canc[0][4] is not None


def test_no_forecast_leaves_every_block_without_a_value(trained: tuple[Path, Path]) -> None:
    made = artifact.read(trained[1])
    document = live.Pass(artifact=made, airports=AIRPORTS, now=NOW, read=live.Inputs()).build()
    assert document.run is None
    assert all(v is None for day in document.airports[0].dep_canc for v in day)
    assert document.airports[0].rough == (None, None, None)
    assert document.airports[0].runs == (None, None, None)


def test_slots_turn_and_the_archive_is_a_bounded_ring(trained: tuple[Path, Path]) -> None:
    slots = {live.slot_of(NOW + timedelta(minutes=20 * i)) for i in range(3)}
    assert slots == {"slot-0", "slot-1", "slot-2"}
    day = date(2026, 11, 21)
    assert live.archive_path(day) == live.archive_path(day + timedelta(days=live.ARCHIVE_DAYS))
    assert live.archive_path(day) != live.archive_path(day + timedelta(days=1))
    made = artifact.read(trained[1])
    document = _pass(made, _runs(snow=False), datetime(2026, 11, 21, 1, 40, tzinfo=UTC))
    assert live.archive_day(document, datetime(2026, 11, 21, 1, 40, tzinfo=UTC)) == day
    assert live.archive_day(document, datetime(2026, 11, 21, 6, 0, tzinfo=UTC)) is None
    older = _pass(made, _station_runs(RUN_20, snow=False), datetime(2026, 11, 21, 0, 5, tzinfo=UTC))
    assert live.archive_day(older, datetime(2026, 11, 21, 0, 5, tzinfo=UTC)) is None
    assert live.kept_day(None) is None
    assert live.kept_day(b"junk") is None


def test_the_flights_files_stay_inside_their_host_budget(trained: tuple[Path, Path]) -> None:
    # The worst case: every airport of the real table with a run covering it, every TAF at its
    # longest, an FAA program and a weather report at each.
    made = artifact.read(trained[1])
    real = airports.load(airports.DATA_DIR / "airports.json")
    rows = {a.icao: calm() for a in real}
    runs = [
        run for when in (RUN_20, RUN_21) for run in nbs.parse(bulletin(when, rows), frozenset(rows))
    ]
    read = live.Inputs(runs=runs, observed=_observed())
    document = live.Pass(artifact=made, airports=real, now=NOW, read=read).build()
    assert all(entry.runs[0] is not None for entry in document.airports)
    tafs = {a.code: "T" * 5000 for a in real}
    archive = len(live.archive_bytes(document, read, made, tafs, NOW.date()))
    assert archive * live.ARCHIVE_DAYS <= live.ARCHIVE_BUDGET
    files = live.files(document)
    assert (
        3 * len(files[f"flights/live/{document.slot}.json"]) + len(files["flights/latest.json"])
        <= live.LIVE_BUDGET
    )
    assert live.ARCHIVE_BUDGET + live.LIVE_BUDGET + monthly.BUILD_BUDGET <= live.HOST_BUDGET


FAA = (
    b"<AIRPORT_STATUS_INFORMATION><Update_Time>Sat Nov 21 00:01:00 2026 GMT</Update_Time>"
    b"</AIRPORT_STATUS_INFORMATION>"
)


def _getter(answers: Mapping[str, bytes | None]) -> Callable[[str], bytes | None]:
    def get(url: str) -> bytes | None:
        for key, value in answers.items():
            if key in url:
                return value
        return None

    return get


def _live_get() -> Callable[[str], bytes | None]:
    text = bulletin(RUN_21, {"KAAA": calm(), "KBBB": calm()}).encode()
    return _getter(
        {
            "blend.20261121/00": text,
            "nasstatus": FAA,
            "alerts": b"{",
            "metars": None,
            "tafs": None,
        }
    )


def test_the_live_pass_publishes_through_the_live_host_with_its_archive(
    trained: tuple[Path, Path], tmp_path: Path
) -> None:
    _, path = trained
    clock = [datetime(2026, 11, 21, 1, 40, tzinfo=UTC)]
    fake = GitHubFake(clock=lambda: clock[0])
    host = fake.publisher()
    lines: list[str] = []
    now = clock[0]
    assert cli.live_pass(_live_get(), host.write, path, now, lines.append, host.read) == 0
    tree = fake.tree()
    key = f"v1/{live.archive_path(now.date())}"
    assert {"v1/flights/latest.json", key} <= set(tree)
    assert any(name.startswith("v1/flights/live/slot-") for name in tree)
    assert any("NWS alerts not read" in line for line in lines)
    snapshot = json.loads(tree[key])
    assert snapshot["day"] == "2026-11-21"
    assert snapshot["live"]["programs_at"] == "2026-11-21T00:01:00Z"
    assert {entry["code"] for entry in snapshot["usual_tomorrow"]} == {"AAA", "BBB"}
    # The snapshot validates against its schema, and the site check takes it.
    kept = FlightsArchive.from_json_bytes(tree[key])
    assert kept.slot == key.rsplit("/", 1)[1].removesuffix(".json")
    site = tmp_path / "site"
    for name, data in tree.items():
        if name.startswith("v1/flights/"):
            target = site / name.removeprefix("v1/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    result = validate_site(site)
    assert not result.problems
    assert "flights/archive/" + key.rsplit("/", 1)[1] in result.checked
    # Two writes: the live files first, the archive after.
    assert len(fake.uploads) == 2
    assert key not in fake.uploads[0][1]
    # The next pass reads the day's snapshot back and keeps no second one.
    clock[0] = now + timedelta(minutes=20)
    assert cli.live_pass(_live_get(), host.write, path, clock[0], lines.append, host.read) == 0
    assert len(fake.uploads) == 3


def test_passes_in_a_row_never_share_a_slot_and_a_raising_taf_read_keeps_the_archive(
    trained: tuple[Path, Path],
) -> None:
    _, path = trained
    clock = [datetime(2026, 11, 21, 1, 40, tzinfo=UTC)]
    fake = GitHubFake(clock=lambda: clock[0])
    host = fake.publisher()
    lines: list[str] = []
    base = _live_get()

    def get(url: str) -> bytes | None:
        if "tafs" in url or "model.json" in url:
            raise RuntimeError("a body that breaks the reader")
        return base(url)

    slots = []
    for minutes in (0, 15, 30, 45):  # 15 minutes apart: two land in one 20-minute window
        clock[0] = datetime(2026, 11, 21, 1, 40, tzinfo=UTC) + timedelta(minutes=minutes)
        assert cli.live_pass(get, host.write, path, clock[0], lines.append, host.read) == 0
        slots.append(json.loads(fake.tree()["v1/flights/latest.json"])["slot"])
    assert all(a != b for a, b in itertools.pairwise(slots))
    assert len({live.slot_of(clock[0] - timedelta(minutes=m)) for m in (30, 45)}) == 1
    assert any("TAFs not read for the archive (RuntimeError" in line for line in lines)
    assert any("the served model not read (RuntimeError" in line for line in lines)
    assert f"v1/{live.archive_path(clock[0].date())}" in fake.tree()
    assert live.next_slot(b"not json", clock[0]) == live.slot_of(clock[0])
    assert live.next_slot(None, clock[0]) == live.slot_of(clock[0])


def test_a_failed_archive_never_stops_the_live_file(trained: tuple[Path, Path]) -> None:
    _, path = trained
    written: dict[str, bytes] = {}
    lines: list[str] = []

    def write(files: Mapping[str, bytes]) -> None:
        if any("archive" in key for key in files):
            raise RuntimeError("refused")
        written.update(files)

    now = datetime(2026, 11, 21, 1, 40, tzinfo=UTC)
    assert cli.live_pass(_live_get(), write, path, now, lines.append, lambda _: None) == 0
    assert "v1/flights/latest.json" in written
    assert any("archive of 2026-11-21 not written" in line for line in lines)

    def broken(_key: str) -> bytes | None:
        raise RuntimeError("no answer")

    assert cli.live_pass(_live_get(), written.update, path, now, lines.append, broken) == 0
    assert any("archive not checked" in line for line in lines)
    # Nothing read: the pass stays dark and writes nothing.
    nothing: dict[str, bytes] = {}
    assert cli.live_pass(_getter({}), nothing.update, path, now, lines.append) == cli.EXIT_DARK
    assert nothing == {}


def test_a_pass_stops_asking_once_its_time_is_up() -> None:
    ticks = iter([0.0, 10.0, 400.0])
    asked: list[tuple[str, float]] = []

    def get(url: str, end: float) -> bytes | None:
        asked.append((url, end))
        return b"x"

    bounded = cli.budgeted(get, clock=lambda: next(ticks), seconds=cli.PASS_SECONDS)
    assert bounded("one") == b"x"
    with pytest.raises(cli.OutOfTimeError):
        bounded("two")
    # Each request is handed the pass's end, so a slow body never runs past it.
    assert asked == [("one", cli.PASS_SECONDS)]


def test_the_monthly_score_reads_the_evening_before(trained: tuple[Path, Path], raw: Path) -> None:
    made = artifact.read(trained[1])
    # A snapshot from the 00Z run of Sep 9, 2026 (the evening of the 8th in AAA) for Sep 9.
    run = datetime(2026, 9, 9, 0, tzinfo=UTC)
    runs = list(nbs.parse(bulletin(run, {"KAAA": calm(), "KBBB": calm()})))
    now = datetime(2026, 9, 9, 1, 5, tzinfo=UTC)
    document = _pass(made, runs, now)
    data = live.archive_bytes(document, live.Inputs(), made, {}, date(2026, 9, 9))
    store = {
        live.archive_path(date(2026, 9, 9)): data,
        live.archive_path(date(2026, 9, 2)): b"junk",
        # A ring slot still holding a day 120 days before is not that day's.
        live.archive_path(date(2026, 9, 3)): live.archive_bytes(
            document, live.Inputs(), made, {}, date(2026, 9, 3) - timedelta(days=120)
        ),
    }
    dep = (
        scan(raw / "bts", "dep")
        .filter(pl.col("day").is_between(date(2026, 9, 1), date(2026, 9, 30)))
        .group_by("apt", "day", "block")
        .agg(pl.col("n").sum(), pl.col("canc").sum())
        .collect()
    )
    scores = monthly.score_month(Month(2026, 9), store.get, dep)
    assert [int(s.target) for s in scores] == [0, 4]
    assert scores[0].units > 0
    # The store holds a few of September's 30 days: the scores say so (R6-B1), never a whole
    # month, and a month can never say more days scored than it has.
    assert all(s.days_in_month == 30 for s in scores)
    assert all(1 <= s.days_scored < s.days_in_month for s in scores)
    with pytest.raises(ValueError, match="days scored"):
        scores[0].model_validate({**scores[0].model_dump(), "days_scored": 31})
    assert monthly.snapshot(store.get, date(2026, 9, 3)) is None
    # A month scored again replaces all its rows; other months stay.
    older = scores[0].model_copy(update={"month": "2026-08"})
    merged = monthly.merge([older, scores[0]], scores)
    assert [(s.month, int(s.target)) for s in merged] == [
        ("2026-08", 0),
        ("2026-09", 0),
        ("2026-09", 4),
    ]
    assert monthly.score_month(Month(2026, 8), store.get, dep) == []


HISTORY_START = Month(2023, 10)


def _monthly(  # noqa: PLR0913 - the parts of one run
    raw: Path,
    out: Path,
    fake: Any,
    lines: list[str],
    *,
    budget: monthly.Budget | None = None,
    first: Month = HISTORY_START,
    committed_last: date = date(2026, 8, 31),
) -> monthly.Outcome:
    host = fake.publisher()
    return monthly.run(
        raw=raw,
        out=out,
        get=_getter({}),
        read_host=lambda key: host.read(f"v1/{key}"),
        write_host=host.write,
        log=lines.append,
        today=date(2026, 11, 22),
        committed_last=committed_last,
        train_all=build.train_all,
        static_all=build.static_all,
        stations=["AAA", "BBB"],
        wanted=frozenset({"KAAA", "KBBB"}),
        budget=budget,
        first_month=first,
        first_run=FIRST_RUN,
    )


def test_the_monthly_command_scores_refits_and_publishes_a_fixture_month(
    trained: tuple[Path, Path], raw: Path, tmp_path: Path
) -> None:
    made = artifact.read(trained[1])
    clock = [datetime(2026, 11, 22, 9, 41, tzinfo=UTC)]
    fake = GitHubFake(clock=lambda: clock[0])
    # The published model's year ends with Aug 2026 (the committed one, nothing published yet)
    # and the live job kept the snapshot of Sep 9.
    runs = list(nbs.parse(bulletin(datetime(2026, 9, 9, tzinfo=UTC), {"KAAA": calm()})))
    document = _pass(made, runs, datetime(2026, 9, 9, 1, 5, tzinfo=UTC))
    fake.commit_other(
        {
            f"v1/{live.archive_path(date(2026, 9, 9))}": live.archive_bytes(
                document, live.Inputs(), made, {}, date(2026, 9, 9)
            )
        }
    )
    lines: list[str] = []
    # Out of time before the history is whole: nothing is published, the next run goes on.
    spent = monthly.Budget(seconds=0.0)
    early = _monthly(raw, tmp_path / "a", fake, lines, budget=spent, first=Month(2023, 9))
    assert early.code == 0
    assert early.published == 0
    assert "history not whole" in early.said
    outcome = _monthly(raw, tmp_path / "b", fake, lines)
    assert outcome.code == 0, outcome.said
    assert outcome.scored == ("2026-09",)
    tree = fake.tree()
    model = json.loads(tree["v1/flights/model.json"])
    assert model["test_last"] == "2026-09-30"
    track = FlightsTrackRecord.from_json_bytes(tree["v1/flights/track-record.json"])
    assert [s.month for s in track.months] == ["2026-09", "2026-09"]
    assert "v1/flights/airports.json" in tree
    assert any(key.startswith("v1/flights/records/") for key in tree)
    # Every key is a JSON file the live host takes.
    assert all(key.endswith(".json") for key in tree)
    # The next day nothing is new: no write, nothing scored again.
    uploads = len(fake.uploads)
    again = _monthly(raw, tmp_path / "c", fake, lines)
    assert again.published == 0
    assert "nothing new" in again.said
    assert len(fake.uploads) == uploads
    # The served refit is the one the live pass then uses.
    assert cli.choose_model(made, tree["v1/flights/model.json"]).test_last == date(2026, 9, 30)


def test_running_out_in_the_oldest_reports_alone_does_not_hold_the_publish(
    raw: Path, tmp_path: Path
) -> None:
    copy = tmp_path / "raw"
    shutil.copytree(raw, copy)
    for key in ("2023_10", "2023_11"):  # before the month the fit's first run needs
        (copy / "obs" / f"{key}.parquet").unlink()
    late = [False]

    def get(url: str) -> bytes | None:
        late[0] = late[0] or "asos" in url
        return None

    budget = monthly.Budget(seconds=1.0, clock=lambda: 5.0 if late[0] else 0.0)
    monthly.fetch_history(
        get,
        copy,
        first_month=HISTORY_START,
        first_run=FIRST_RUN,
        newest=Month(2026, 9),
        stations=["AAA", "BBB"],
        wanted=frozenset({"KAAA", "KBBB"}),
        today=date(2026, 11, 22),
        log=lambda _: None,
        budget=budget,
    )
    assert budget.ran_out
    assert not budget.required_out
    assert build.observed_gaps(copy / "obs", FIRST_RUN, HISTORY_START, Month(2026, 9)) == []


def test_a_needed_month_that_cannot_be_fetched_is_warned(raw: Path, tmp_path: Path) -> None:
    copy = tmp_path / "raw"
    shutil.copytree(raw, copy)
    needed = copy / "obs" / f"{Month(2025, 1).key}.parquet"
    needed.unlink()
    fake = GitHubFake(clock=lambda: datetime(2026, 11, 23, 9, 41, tzinfo=UTC))
    lines: list[str] = []
    outcome = _monthly(copy, tmp_path / "out", fake, lines)
    assert outcome.published == 0
    assert outcome.said.startswith("::warning:: history not whole yet")
    assert needed.stem in outcome.said


def test_a_stuck_history_is_warned_on_a_day_that_kept_an_archive_copy(
    raw: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # After landing a new archive copy is kept nearly every day: the warning reads the history
    # fetch alone (R6-S2), and the run still says it kept something new.
    copy = tmp_path / "raw"
    shutil.copytree(raw, copy)
    needed = copy / "obs" / f"{Month(2025, 1).key}.parquet"
    needed.unlink()
    monkeypatch.setattr(monthly, "keep_archive", lambda *_: True)
    fake = GitHubFake(clock=lambda: datetime(2026, 11, 23, 9, 41, tzinfo=UTC))
    outcome = _monthly(copy, tmp_path / "out", fake, [])
    assert outcome.fetched
    assert outcome.said.startswith("::warning:: history not whole yet")
    assert needed.stem in outcome.said


@pytest.mark.parametrize(
    ("writes_copy", "says_fetched", "expected"),
    [(True, False, "true"), (False, True, "true"), (False, False, "false")],
)
def test_the_workflow_saves_the_cache_when_only_an_archive_copy_was_kept(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    writes_copy: bool,
    says_fetched: bool,
    expected: str,
) -> None:
    # R6-B1: a run that keeps only a copy of an archive day (no new BTS, NBS or report file)
    # must still say fetched=true, so the workflow saves the history cache with that copy.
    import argparse  # noqa: PLC0415
    import contextlib  # noqa: PLC0415

    raw_dir = tmp_path / "raw"
    (raw_dir / "bts").mkdir(parents=True)
    (raw_dir / "bts" / "2026_09.parquet").write_bytes(b"kept")
    output = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(cli, "_host", lambda _: (lambda _: None, lambda _: None))
    monkeypatch.setattr(fetch, "client", lambda **_: contextlib.nullcontext(None))

    def run(**kwargs: Any) -> monthly.Outcome:
        if writes_copy:
            monthly.kept_path(kwargs["raw"], date(2026, 11, 21)).parent.mkdir(parents=True)
            monthly.kept_path(kwargs["raw"], date(2026, 11, 21)).write_text("{}")
        return monthly.Outcome(monthly.EXIT_OK, fetched=says_fetched, said="done")

    monkeypatch.setattr(monthly, "run", run)
    args = argparse.Namespace(raw=raw_dir, out=tmp_path / "out", host="dir")
    assert cli.run_monthly(args) == monthly.EXIT_OK
    assert output.read_text() == f"fetched={expected}\n"
    assert ("archive/2026-11-21.json" in history.kept_files(raw_dir)) is writes_copy


@pytest.mark.usefixtures("trained")
def test_an_empty_host_gets_the_whole_build_with_no_new_month(raw: Path, tmp_path: Path) -> None:
    # The committed model already holds the newest posted month (Sep 2026, Oct not posted),
    # and the host has no Flights files: the run still builds and publishes them all, once.
    fake = GitHubFake(clock=lambda: datetime(2026, 11, 23, 9, 41, tzinfo=UTC))
    lines: list[str] = []
    first = _monthly(raw, tmp_path / "a", fake, lines, committed_last=date(2026, 9, 30))
    assert first.code == 0, first.said
    assert first.published > 0
    assert first.scored == ()
    tree = fake.tree()
    assert {"v1/flights/airports.json", "v1/flights/model.json"} <= set(tree)
    assert any(key.startswith("v1/flights/routes/") for key in tree)
    assert "host lacks the Flights files" in " ".join(lines)
    # The model and its track record come in the last write, after the files they name.
    assert set(fake.uploads[-1][1]) == {"v1/flights/model.json", "v1/flights/track-record.json"}
    again = _monthly(raw, tmp_path / "b", fake, lines, committed_last=date(2026, 9, 30))
    assert again.published == 0
    assert "nothing new" in again.said


def test_a_build_that_does_not_validate_or_is_over_its_budget_is_never_seeded(
    trained: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out, path = trained
    fake = GitHubFake(clock=lambda: datetime(2026, 11, 23, 9, 41, tzinfo=UTC))
    host = fake.publisher()
    lines: list[str] = []
    assert monthly.seed(tmp_path / "nothing", host.write, lines.append) == 1
    assert fake.uploads == []
    build_dir = tmp_path / "build"
    (build_dir / "files/flights").mkdir(parents=True)
    (build_dir / "files/flights/airports.json").write_bytes(b"{}")
    (build_dir / "model.json.gz").write_bytes(path.read_bytes())
    assert monthly.seed(build_dir, host.write, lines.append) == 1
    assert fake.uploads == []
    good = tmp_path / "good"
    (good / "files").mkdir(parents=True)
    for item in (out / "files").rglob("*.json"):
        target = good / "files" / item.relative_to(out / "files")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(item.read_bytes())
    (good / "files/flights/airports.json").write_bytes(
        build.airports_file(
            AIRPORTS, Month(2026, 9), datetime(2026, 11, 1, tzinfo=UTC)
        ).to_json_bytes()
    )
    (good / "model.json.gz").write_bytes(path.read_bytes())
    with monkeypatch.context() as patch:
        patch.setattr(monthly, "BUILD_BUDGET", 1000)
        assert monthly.seed(good, host.write, lines.append) == 1
        assert "over its 1,000" in lines[-1]
        assert fake.uploads == []
    assert monthly.seed(good, host.write, lines.append) == 0
    assert "v1/flights/model.json" in fake.tree()
    assert "seed: published" in lines[-1]


def test_the_monthly_score_skips_an_airport_day_with_no_usual_rate(
    trained: tuple[Path, Path],
) -> None:
    made = artifact.read(trained[1])
    runs = list(nbs.parse(bulletin(datetime(2026, 9, 9, tzinfo=UTC), {"KAAA": calm()})))
    document = _pass(made, runs, datetime(2026, 9, 9, 1, 5, tzinfo=UTC))
    snapshot = live.archive_document(document, live.Inputs(), made, {}, date(2026, 9, 9))
    alone = snapshot.model_copy(update={"usual_tomorrow": ()})
    dep = pl.DataFrame(
        {
            "apt": ["AAA"] * 5,
            "day": [date(2026, 9, 9)] * 5,
            "block": list(range(5)),
            "n": [10] * 5,
            "canc": [1] * 5,
        }
    )
    full = monthly.score_month(Month(2026, 9), lambda _: snapshot.to_json_bytes(), dep)
    assert full
    assert full[0].units == 50
    # Without the usual rates, the day is not scored: the chance is never held to itself.
    assert monthly.score_month(Month(2026, 9), lambda _: alone.to_json_bytes(), dep) == []
    # A snapshot that does not validate is not read.
    assert monthly.score_month(Month(2026, 9), lambda _: b'{"day": "2026-09-09"}', dep) == []


def test_malformed_history_bodies_are_skipped_and_the_earlier_work_kept(tmp_path: Path) -> None:
    from flights.synth import bts_rows, zipped  # noqa: PLC0415

    lines: list[str] = []
    body = zipped(bts_rows(date(2026, 10, 3), [{"dep": "AAA", "arr": "BBB"}]))
    get = _getter({"_2026_10.zip": body, "_2026_11.zip": b"<html>busy</html>"})
    before = history.kept_files(tmp_path)
    added = history.fetch_bts(
        get,
        tmp_path / "bts",
        tmp_path / "scratch",
        [Month(2026, 10), Month(2026, 11)],
        lines.append,
    )
    assert added == [Month(2026, 10)]
    assert any("2026_11 did not read" in line for line in lines)
    assert history.kept_files(tmp_path) != before
    kept = history.fetch_obs(
        _getter({"asos.py": b"#ERROR: server busy\n"}),
        tmp_path / "obs",
        ["AAA"],
        [Month(2026, 10)],
        lines.append,
    )
    assert kept == 0
    assert any("reports 2026_10 did not read" in line for line in lines)
    kept_runs = history.fetch_nbs(
        _getter({"blend.": b"\x00\x01 not a bulletin"}),
        tmp_path / "nbs",
        frozenset({"KAAA"}),
        first=date(2026, 11, 20),
        last=date(2026, 11, 20),
        log=lines.append,
    )
    assert kept_runs == 0

    def refuse(url: str) -> bytes | None:
        raise fetch.FetchError(url)

    assert history.newest_posted(refuse, Month(2026, 9)) is None
    output = tmp_path / "out.txt"
    cli.write_fetched(str(output), fetched=True)
    cli.write_fetched(None, fetched=True)
    assert output.read_text() == "fetched=true\n"


def test_history_fetchers_skip_what_is_kept(tmp_path: Path) -> None:
    from flights.synth import bts_rows, zipped  # noqa: PLC0415

    body = zipped(bts_rows(date(2026, 10, 3), [{"dep": "AAA", "arr": "BBB"}]))
    lines: list[str] = []
    get = _getter({"_2026_10.zip": body, "_2026_11.zip": None})
    added = history.fetch_bts(
        get,
        tmp_path / "bts",
        tmp_path / "scratch",
        [Month(2026, 10), Month(2026, 11)],
        lines.append,
    )
    assert added == [Month(2026, 10)]
    assert (
        history.fetch_bts(
            get, tmp_path / "bts", tmp_path / "scratch", [Month(2026, 10)], lines.append
        )
        == []
    )
    assert history.newest_posted(get, Month(2026, 9)) == Month(2026, 10)
    run = bulletin(datetime(2026, 11, 20, tzinfo=UTC), {"KAAA": calm()}).encode()
    kept = history.fetch_nbs(
        _getter({"blend.20261120": run}),
        tmp_path / "nbs",
        frozenset({"KAAA"}),
        first=date(2026, 11, 19),
        last=date(2026, 11, 20),
        log=lines.append,
    )
    assert kept == 1
    reports = (
        b"station,valid,sknt,gust,vsby,skyc1,skyc2,skyc3,skyl1,skyl2,skyl3,wxcodes\n"
        b"AAA,2026-10-01 00:53,5,M,10,CLR,M,M,M,M,M,\n"
    )
    assert (
        history.fetch_obs(
            _getter({"asos.py": reports}),
            tmp_path / "obs",
            ["AAA"],
            [Month(2026, 10)],
            lines.append,
        )
        == 1
    )
    assert (
        history.fetch_obs(_getter({}), tmp_path / "obs", ["AAA"], [Month(2026, 9)], lines.append)
        == 0
    )


def test_the_commands_are_registered() -> None:
    from snowlight.cli import build_parser  # noqa: PLC0415

    parser = build_parser()
    assert (
        parser.parse_args(["flights", "live", "--host", "dir", "--host-dir", "x"]).handler
        is cli.run_live
    )
    assert parser.parse_args(["flights", "train", "--out", "x"]).handler is cli.run_train
    assert parser.parse_args(["flights", "static", "--out", "x"]).handler is cli.run_static
    assert parser.parse_args(["flights", "monthly", "--out", "x"]).handler is cli.run_monthly


def test_a_newer_served_refit_is_used(trained: tuple[Path, Path]) -> None:
    committed = artifact.read(trained[1])
    newer = artifact.Artifact.from_bytes(committed.to_bytes())
    newer.test_last = date(2026, 10, 31)
    served = newer.to_bytes()
    assert cli.choose_model(committed, served).test_last == date(2026, 10, 31)
    assert cli.choose_model(committed, None) is committed
    assert cli.choose_model(committed, b"junk") is committed
    assert cli.choose_model(committed, committed.to_bytes()) is committed
    # A newer file that does not validate against its schema is never used.
    broken = json.loads(served)
    broken["fits"][0]["scale"][0] = -1.0
    assert cli.choose_model(committed, json.dumps(broken).encode()) is committed
    del broken["national"]
    assert cli.choose_model(committed, json.dumps(broken).encode()) is committed


@pytest.fixture(scope="module")
def tables(raw: Path) -> train.Tables:
    rows = pl.scan_parquet(raw / "nbs" / "*.parquet").filter(pl.col("run").dt.date() >= FIRST_RUN)
    return train.assemble(raw / "bts", rows, AIRPORTS)


def test_the_after_storm_gate_needs_its_out_of_selection_score_and_the_usual_window_is_dated(
    tables: train.Tables,
) -> None:
    # R6-S2: the after-storm gate passes only when the shown rows and the rows scored out of
    # selection (airports the even weeks chose on their odd-week rows, and the reverse) both
    # pass. R6-S4: the usual rates' window ends the day before the test year.
    model = train.train(tables)
    tests = train.evaluate(tables, model)
    assert tests
    for test in tests:
        both = fm.after_storm_ok(test.after_storm, test.after_lower) and fm.after_storm_ok(
            test.after_out, test.after_out_lower
        )
        assert model.after[(test.target, test.lead)] is both
        assert test.after_out.units <= test.pooled.units
        assert test.usual.units == test.pooled.units
    assert tables.usual_window is not None
    first, last = tables.usual_window
    assert last == tables.split.test_first - timedelta(days=1)
    assert first < last
    with pytest.raises(ValueError, match="usual window"):
        FlightsTrackRecord.model_validate(
            {
                **FlightsTrackRecord.from_json_bytes(
                    (
                        Path(__file__).parent.parent
                        / "schemas/examples/synthetic-flights-track-record.json"
                    ).read_bytes()
                ).model_dump(),
                "usual_last": "2025-10-01",
            }
        )


def test_a_replay_shows_what_the_airports_gate_allows(tables: train.Tables) -> None:
    model = train.train(tables)
    train.evaluate(tables, model)
    days = replays.storm_days(tables, ["AAA", "BBB"], model)
    assert days
    code, day = days[0]
    now = datetime(2026, 11, 22, tzinfo=UTC)
    shown = replays.replay(tables, model, code, day, FlightsHeld.TEST_YEAR, now)
    assert shown is not None
    # Every block from the one run of the evening before: the 00Z run on the day itself.
    assert (shown.run.date(), shown.run.hour) == (day, 0)
    assert shown.said_usual == 0
    # Left out of the fit, but the gate is the airport's own: where it fails, the usual rate.
    closed = train.train(tables)
    for key in list(model.published):
        closed.published[key] = False
    apart = replays.replay(tables, model, code, day, FlightsHeld.LEFT_OUT, now, gate=closed)
    assert apart is not None
    assert apart.said_usual == 31
    assert apart.rough_usual
    usual = (
        tables.blocks["dep"]
        .filter((pl.col("apt") == code) & (pl.col("day") == day) & (pl.col("run") == shown.run))
        .sort("block")
    )
    assert list(apart.said) == [live.per_mille(v) for v in usual.get_column("canc_base")]
    # The same storm days on every run: ties go to more departures, then the code.
    assert replays.storm_days(tables, ["BBB", "AAA"], model) == days
    # A rough day inside a non-weather span is never a past storm.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(spans, "NOT_WEATHER", ((day, day, "a made-up outage"),))
        assert day not in [d for _, d in replays.storm_days(tables, ["AAA", "BBB"], model)]


def test_rewriting_a_slot_is_said(trained: tuple[Path, Path]) -> None:
    made = artifact.read(trained[1])
    day = date(2026, 11, 21)
    old = day - timedelta(days=live.ARCHIVE_DAYS)
    document = _pass(made, _runs(snow=False), datetime(2026, 11, 21, 1, 5, tzinfo=UTC))
    kept = live.archive_bytes(document, live.Inputs(), made, {}, old)
    written: list[Mapping[str, bytes]] = []
    lines: list[str] = []
    host = {f"v1/{live.archive_path(old)}": kept}
    assert live.archive_path(old) == live.archive_path(day)
    now = datetime(2026, 11, 21, 1, 5, tzinfo=UTC)
    document = document.model_copy(update={"run": RUN_21})
    assert cli.archive(
        _getter({}), written.append, host.get, document, live.Inputs(), made, now, lines.append
    )
    assert any(line.endswith(f"held {old}, rewritten") for line in lines)
    assert f"v1/{live.archive_path(day)}" in written[0]


def test_the_monthly_job_keeps_each_day_before_the_host_ring_rewrites_it(
    trained: tuple[Path, Path], raw: Path, tmp_path: Path
) -> None:
    # The host holds 30 days (LR-F7); a month is scored about 80 days after its first day.
    # Each run copies the host's days into the history cache and scores from the copy, so a day
    # the ring has since rewritten is still scored; a day lost from both is said, never guessed.
    made = artifact.read(trained[1])
    run = datetime(2026, 9, 9, 0, tzinfo=UTC)
    runs = list(nbs.parse(bulletin(run, {"KAAA": calm(), "KBBB": calm()})))
    document = _pass(made, runs, datetime(2026, 9, 9, 1, 5, tzinfo=UTC))
    day = date(2026, 9, 9)
    host = {live.archive_path(day): live.archive_bytes(document, live.Inputs(), made, {}, day)}
    cache = tmp_path / "raw"
    lines: list[str] = []
    assert monthly.keep_archive(host.get, cache, day + timedelta(days=3), lines.append)
    assert monthly.kept_path(cache, day).exists()
    assert not monthly.keep_archive(host.get, cache, day + timedelta(days=4), lines.append)
    # 30 days later the ring slot holds another day: the host has lost it, the cache has not.
    later = day + timedelta(days=live.ARCHIVE_DAYS)
    host[live.archive_path(later)] = live.archive_bytes(document, live.Inputs(), made, {}, later)
    assert monthly.snapshot(host.get, day) is None
    found = monthly.snapshot(host.get, day, cache)
    assert found is not None
    assert found.day == day
    dep = (
        scan(raw / "bts", "dep")
        .filter(pl.col("day").is_between(date(2026, 9, 1), date(2026, 9, 30)))
        .group_by("apt", "day", "block")
        .agg(pl.col("n").sum(), pl.col("canc").sum())
        .collect()
    )
    assert monthly.score_month(Month(2026, 9), host.get, dep) == []
    assert monthly.score_month(Month(2026, 9), host.get, dep, cache)[0].units > 0
    # The days of September the cache lacks, older than the ring and unscored, are lost.
    today = date(2026, 11, 22)
    lost = monthly.lost_days(cache, set(), today)
    assert day not in lost
    assert date(2026, 9, 10) in lost
    assert (
        monthly.lost_days(
            cache, {"2026-09", "2026-10", "2026-08", "2026-07", "2026-06", "2026-05"}, today
        )
        == []
    )
    # Copies older than the cache keeps are dropped.
    monthly.keep_archive(
        lambda _: None, cache, day + timedelta(days=monthly.KEPT_DAYS + 1), lines.append
    )
    assert not monthly.kept_path(cache, day).exists()


BAD_NUMBERS = ("nan", "inf", "-inf", "-1", "-5", "99999999999", "1e999")
BAD_TIMES = (
    "0001-01-01T00:00:00",
    "0999-06-01T00:00:00",
    "9999-12-31T23:59:59",
    "2026-11-29T04:00:00",
)


def _bad_get(number: str, when: str, cell: int) -> Callable[[str], bytes | None]:
    """Every source, carrying an out-of-range number (``number``), a time off the clock
    (``when``) and a forecast cell out of range (``cell``) beside good rows."""
    nbs_text = bulletin(
        RUN_21, {"KAAA": calm(TMP=[cell] * 23, WSP=[cell] * 23, GST=[cell] * 23), "KBBB": calm()}
    ).encode()
    faa = (
        "<AIRPORT_STATUS_INFORMATION><Update_Time>Sat Nov 21 01:31:00 2026 GMT</Update_Time>"
        "<Delay_type><Name>General Arrival/Departure Delay Info</Name>"
        "<Arrival_Departure_Delay_List><Delay><ARPT>AAA</ARPT><Reason>WX:Snow</Reason>"
        f'<Arrival_Departure Type="Departure"><Max>{number} minutes</Max></Arrival_Departure>'
        "</Delay></Arrival_Departure_Delay_List></Delay_type>"
        "<Delay_type><Name>Ground Stop Programs</Name><Ground_Stop_List><Program><ARPT>BBB</ARPT>"
        f"<Reason>WX</Reason><End_Time>{number}</End_Time></Program></Ground_Stop_List>"
        "</Delay_type></AIRPORT_STATUS_INFORMATION>"
    ).encode()
    alerts = json.dumps(
        {
            "updated": "2026-11-21T01:30:00+00:00",
            "features": [
                {
                    "properties": {
                        "event": "Winter Storm Warning",
                        "status": "Actual",
                        "onset": f"{when}+00:00",
                        "ends": f"{when}+00:00",
                        "geocode": {"UGC": ["MOZ001"]},
                    }
                }
            ],
        }
    ).encode()
    head = (
        "raw_text,station_id,observation_time,wind_speed_kt,wind_gust_kt,visibility_statute_mi,"
        "wx_string,sky_cover,cloud_base_ft_agl\n"
    )
    metars = head + (
        f'"METAR KAAA",KAAA,2026-11-21T01:15:00.000Z,{number},{number},{number},SN,OVC,{number}\n'
        f'"METAR KAAA",KAAA,{when}.000Z,5,,10,,CLR,\n'
        f'"METAR KBBB",KBBB,{when}.000Z,{number},,{number},,OVC,{number}\n'
        '"METAR KBBB",KBBB,2026-11-21T01:10:00.000Z,5,,10,,CLR,\n'
    )
    reports = (
        "station,valid,sknt,gust,vsby,skyc1,skyc2,skyc3,skyl1,skyl2,skyl3,wxcodes\n"
        f"AAA,2026-11-20 23:53,{number},{number},{number},OVC,M,M,{number},M,M,SN\n"
        f"AAA,{when[:16].replace('T', ' ')},5,M,10,CLR,M,M,M,M,M,\n"
        "BBB,2026-11-20 23:53,5,M,10,CLR,M,M,M,M,M,\n"
        f"BBB,{when[:16].replace('T', ' ')},{number},M,{number},OVC,M,M,{number},M,M,\n"
    )
    return _getter(
        {
            "blend.20261121/00": nbs_text,
            "nasstatus": faa,
            "alerts": alerts,
            "metars": gzip.compress(metars.encode()),
            "asos": reports.encode(),
            "tafs": None,
        }
    )


@pytest.mark.parametrize(
    ("number", "when", "cell"),
    [
        (number, when, cell)
        for (number, when), cell in zip(
            itertools.product(BAD_NUMBERS, BAD_TIMES), itertools.cycle((-99, 999, 9999, -999))
        )
    ],
)
def test_bad_numbers_and_times_in_every_source_still_write_every_airport(
    trained: tuple[Path, Path], number: str, when: str, cell: int
) -> None:
    # LR-F3: nan, inf, negative, huge and out-of-range numbers and times in every source, and
    # the pass writes every airport, valid, with each source's warning line.
    _, path = trained
    now = datetime(2026, 11, 21, 1, 40, tzinfo=UTC)
    written: dict[str, bytes] = {}
    lines: list[str] = []
    assert cli.live_pass(_bad_get(number, when, cell), written.update, path, now, lines.append) == 0
    (slot,) = [key for key in written if "/flights/live/slot-" in key]
    document = FlightsLive.from_json_bytes(written[slot])
    assert [a.code for a in document.airports] == ["AAA", "BBB"]
    assert document.weather_at is not None
    aaa, bbb = document.airports
    # The real newest reports are the ones shown, never a time off the clock.
    assert aaa.now is not None
    assert aaa.now.at == datetime(2026, 11, 21, 1, 15, tzinfo=UTC)
    assert bbb.now is not None
    assert bbb.now.at == datetime(2026, 11, 21, 1, 10, tzinfo=UTC)
    for at in (document.programs_at, document.alerts_at, document.observed_at):
        assert at is None or at <= now
    assert any("times off the clock left out" in line for line in lines)
