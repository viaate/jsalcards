"""Closure seasons (snowlight.sources.stations.seasons) and the live reader's staleness rule.

The closure days and markets here are synthetic (named ``synthetic_*``), except where a
test says it copies an event from the NWS record (``closure-days.json`` of 2026-10-13).
The list bodies the synthetic servers serve are real fixtures (fixtures/gray/: KCTV's
live export of 2026-09-26, an empty list).
"""

import json
from datetime import UTC, date, datetime, timedelta
from functools import partial
from pathlib import Path

import httpx
import polars as pl
import pytest

from snowlight.cli import main
from snowlight.sources.nws.http import CachedFile, Provenance
from snowlight.sources.stations import cli as stations_cli
from snowlight.sources.stations import fetch, seasons
from snowlight.sources.stations.http import USER_AGENT, ConditionalStore, PoliteClient, Timing
from snowlight.sources.stations.model import HealthStatus
from snowlight.sources.stations.registry import load_registry
from snowlight.sources.stations.seasons import (
    ClosureEvent,
    ClosureSeasons,
    SeasonsError,
)
from snowlight.weights import archive
from snowlight.weights import count as weights_count

REGISTRY = load_registry()
EMPTY_EXPORT = Path(__file__).parent / "fixtures" / "gray" / "kctv-export-live-20260926174949.json"
WTOC = "gray-wtoc"
READ_AT = datetime(2026, 10, 13, 6, 0, tzinfo=UTC)

# Copied from the NWS record (closure-days.json of 2026-10-13): Savannah's last closure
# event, the snow of 22 January 2025.
SAVANNAH_SNOW = ClosureEvent(date(2025, 1, 22), date(2025, 1, 22), 1.0, ("WS.W",))


def test_only_the_closure_codes_make_closure_days() -> None:
    tally = weights_count.Tally(years=[2024])
    counts = tally.counties["13051"][2024]
    synthetic_day = date(2025, 1, 22)
    counts.by_code["WS.W"] = {synthetic_day: {"GAZ117"}}
    counts.by_code["TR.W"] = {synthetic_day: {"GAZ117"}, synthetic_day + timedelta(1): {"GAZ117"}}
    counts.by_code["WW.Y"] = {synthetic_day + timedelta(2): {"GAZ117"}}
    counts.by_code["EC.W"] = {synthetic_day + timedelta(3): {"GAZ117"}}
    found = seasons.county_closure_days([tally])
    assert found == {
        "13051": {
            synthetic_day: {"WS.W", "TR.W"},
            synthetic_day + timedelta(1): {"TR.W"},
        }
    }


def test_a_market_s_closure_events() -> None:
    synthetic_market = {"00001": 60, "00002": 40}
    monday = date(2025, 1, 20)
    synthetic_days = {
        "00001": {
            monday: {"WS.W"},
            monday + timedelta(days=4): {"IS.W"},  # Friday: four days on, a new event
            monday + timedelta(days=7): {"WS.W"},  # the next Monday: three days on, the same
            monday + timedelta(days=30): {"HU.W"},
        },
        "00002": {
            monday: {"BZ.W"},
            monday + timedelta(days=1): {"WS.W"},  # 40% of the schools: not a closure day
        },
    }
    events = seasons.market_events(synthetic_market, synthetic_days)
    assert events == (
        ClosureEvent(monday, monday, 1.0, ("BZ.W", "WS.W")),
        ClosureEvent(monday + timedelta(days=4), monday + timedelta(days=7), 0.6, ("IS.W", "WS.W")),
        ClosureEvent(monday + timedelta(days=30), monday + timedelta(days=30), 0.6, ("HU.W",)),
    )
    assert seasons.market_events({}, synthetic_days) == ()
    assert events[1].describe() == "2025-01-24 to 2025-01-27 (IS.W, WS.W over 60% of its schools)"
    assert events[0].describe() == "2025-01-20 (BZ.W, WS.W over 100% of its schools)"


def test_a_list_written_after_the_last_closure_event_is_idle() -> None:
    record = ClosureSeasons(date(2026, 10, 12), {WTOC: (SAVANNAH_SNOW,)})
    verdict = record.judge(WTOC, datetime(2025, 1, 24, 17, 12, 20, tzinfo=UTC))
    assert verdict is not None
    assert not verdict.stale
    assert verdict.before == SAVANNAH_SNOW
    assert "idle, not abandoned" in verdict.explain()
    assert "counted through 2026-10-12" in verdict.explain()
    assert "the last before it: 2025-01-22 (WS.W over 100% of its schools)" in verdict.explain()
    assert record.knows(WTOC)
    assert not record.knows("gray-wvue")
    assert record.judge("gray-wvue", READ_AT) is None


def test_a_list_not_written_for_a_closure_event_is_stale() -> None:
    synthetic_hurricane = ClosureEvent(date(2025, 9, 10), date(2025, 9, 11), 0.9, ("HU.W",))
    record = ClosureSeasons(date(2026, 10, 12), {WTOC: (SAVANNAH_SNOW, synthetic_hurricane)})
    verdict = record.judge(WTOC, datetime(2024, 10, 12, 2, 0, tzinfo=UTC))
    assert verdict is not None
    assert verdict.stale
    assert verdict.missed == (SAVANNAH_SNOW, synthetic_hurricane)
    assert verdict.before is None
    assert verdict.explain() == (
        "weather that closes schools came to its market after that, and the list was not "
        "written for it: 2025-01-22 (WS.W over 100% of its schools), and 1 more since, the "
        "last 2025-09-10 to 2025-09-11 (HU.W over 90% of its schools)"
    )
    # A list written the day before an event's first day was written for it.
    day_before = record.judge(WTOC, datetime(2025, 1, 21, 23, 0, tzinfo=UTC))
    assert day_before is not None
    assert day_before.missed == (synthetic_hurricane,)
    two_days_before = record.judge(WTOC, datetime(2025, 1, 20, 23, 0, tzinfo=UTC))
    assert two_days_before is not None
    assert two_days_before.missed[0] == SAVANNAH_SNOW
    # Events after the record's end are not known to have happened.
    short = ClosureSeasons(date(2025, 9, 1), {WTOC: (SAVANNAH_SNOW, synthetic_hurricane)})
    late = short.judge(WTOC, datetime(2025, 2, 1, tzinfo=UTC))
    assert late is not None
    assert not late.stale


def test_build_keeps_events_through_the_record_s_end() -> None:
    synthetic_days = {"00001": {date(2025, 1, 22): {"WS.W"}, date(2026, 1, 5): {"WS.W"}}}
    record = seasons.build(
        {"x": {"00001": 3}, "y": {"00002": 1}}, synthetic_days, date(2025, 6, 15)
    )
    assert record.events == {
        "x": (ClosureEvent(date(2025, 1, 22), date(2025, 1, 22), 1.0, ("WS.W",)),),
        "y": (),
    }


def test_the_record_file_round_trips(tmp_path: Path) -> None:
    record = ClosureSeasons(date(2026, 10, 12), {WTOC: (SAVANNAH_SNOW,), "gray-x": ()})
    path = tmp_path / seasons.SEASONS_FILE
    seasons.write(path, record, READ_AT, directory={"schools": 1})
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["codes"] == ["BZ.W", "HU.W", "IS.W", "LE.W", "TR.W", "WS.W"]
    assert document["market_share"] == seasons.MARKET_SHARE
    assert document["directory"] == {"schools": 1}
    assert document["stations"][WTOC] == [["2025-01-22", "2025-01-22", 1.0, "WS.W"]]
    assert ClosureSeasons.load(path) == record


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "{}",
        '{"counted_through": "2026-10-12", "stations": {"x": [[1, 2]]}}',
        '{"counted_through": "2026-10-12", "stations": {"x": [["a", "b", 1, ""]]}}',
    ],
)
def test_a_malformed_record_is_refused(tmp_path: Path, content: str) -> None:
    path = tmp_path / seasons.SEASONS_FILE
    path.write_text(content, encoding="utf-8")
    with pytest.raises(SeasonsError):
        ClosureSeasons.load(path)


def test_a_station_s_market_is_its_county_list_or_its_districts() -> None:
    wtoc = REGISTRY.stations[WTOC]
    assert wtoc.counties is not None
    district = next(s for s in REGISTRY.stations.values() if s.leaids)
    bare = next(s for s in REGISTRY.stations.values() if s.counties is None and not s.leaids)
    synthetic_counties = dict.fromkeys(wtoc.counties.fips, 2)
    synthetic_districts = {district.leaids[0]: {"99999": 5}}
    markets = seasons.station_markets(REGISTRY, synthetic_counties, synthetic_districts)
    assert markets[WTOC] == dict.fromkeys(wtoc.counties.fips, 2)
    assert markets[district.id] == {"99999": 5}
    assert bare.id not in markets


def test_the_current_school_years() -> None:
    assert seasons.current_years(date(2026, 10, 13)) == [2026]
    assert seasons.current_years(date(2026, 7, 31)) == []
    assert seasons.current_years(date(2027, 9, 1)) == [2026, 2027]


def _file(year: int, checked_at: str, *, final: bool) -> archive.SchoolYearFile:
    provenance = Provenance(
        url=f"https://example.test/{year}.csv",
        sha256="0" * 64,
        size=0,
        retrieved_at=checked_at,
        checked_at=checked_at,
        etag=None,
        last_modified=None,
    )
    return archive.SchoolYearFile(
        year, (), archive.ReadStats(), CachedFile(Path("x"), provenance, False), final
    )


class _Counted:
    def __init__(self) -> None:
        self.tally = weights_count.Tally(years=[2025])
        self.tally.counties["13051"][2025].by_code["WS.W"] = {date(2025, 1, 22): {"GAZ117"}}
        self.files = [_file(2025, "2026-09-26T00:00:00Z", final=True)]
        self.catalog = object()
        self.counties = object()


def test_closure_weather_counts_the_current_school_year_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = weights_count.Tally(years=[2026])
    current.counties["01003"][2026].by_code["HU.W"] = {date(2026, 10, 9): {"ALZ265"}}
    loaded: list[list[int]] = []

    def load_years(_cache: object, years: list[int]) -> list[archive.SchoolYearFile]:
        loaded.append(years)
        return [_file(year, "2026-10-13T08:13:12Z", final=False) for year in years]

    monkeypatch.setattr(seasons, "count_weather", lambda _cache: _Counted())
    monkeypatch.setattr(archive, "load_years", load_years)
    monkeypatch.setattr(weights_count, "count_years", lambda *_args: current)
    counted = seasons.count_closure_weather(object(), date(2026, 10, 13))  # type: ignore[arg-type]
    assert loaded == [[2026]]
    assert counted.counted_through == date(2026, 10, 12)
    assert counted.county_days == {
        "13051": {date(2025, 1, 22): {"WS.W"}},
        "01003": {date(2026, 10, 9): {"HU.W"}},
    }
    record = seasons.provenance(counted.files)
    assert record["2025-26"] == {
        **counted.files[0].file.provenance.as_json(),
        "final": True,
    }
    current_year = record["2026-27"]
    assert isinstance(current_year, dict)
    assert current_year["final"] is False
    # Before the next school year begins, the record ends on the last one's last day.
    summer = seasons.count_closure_weather(object(), date(2026, 7, 1))  # type: ignore[arg-type]
    assert summer.counted_through == date(2026, 6, 15)


# The live reader -----------------------------------------------------------------------


class Ticker:
    def __init__(self, now: datetime) -> None:
        self.now = now
        self.mono = 0.0

    def clock(self) -> datetime:
        return self.now

    def monotonic(self) -> float:
        return self.mono

    def sleep(self, seconds: float) -> None:
        self.mono += seconds
        self.now += timedelta(seconds=seconds)


def _serve(request: httpx.Request) -> httpx.Response:
    assert request.headers["User-Agent"] == USER_AGENT
    if request.url.path == "/robots.txt":
        return httpx.Response(404)
    assert str(request.url) == REGISTRY.stations[WTOC].poll_url
    return httpx.Response(
        200,
        content=EMPTY_EXPORT.read_bytes(),
        headers={"Last-Modified": "Fri, 24 Jan 2025 17:12:20 GMT"},
    )


def _client(tmp_path: Path) -> PoliteClient:
    ticker = Ticker(READ_AT)
    return PoliteClient(
        httpx.Client(transport=httpx.MockTransport(_serve), headers={"User-Agent": USER_AGENT}),
        ConditionalStore(tmp_path / "cache"),
        timing=Timing(clock=ticker.clock, monotonic=ticker.monotonic, sleep=ticker.sleep),
    )


def test_an_idle_list_file_reads_as_empty(tmp_path: Path) -> None:
    record = ClosureSeasons(date(2026, 10, 12), {WTOC: (SAVANNAH_SNOW,)})
    station = REGISTRY.stations[WTOC]
    result = fetch.read_station(
        REGISTRY, station, _client(tmp_path), READ_AT, fetch.Judges(seasons=record)
    )
    (health,) = result.health
    assert (health.status, health.rows) == (HealthStatus.EMPTY, 0)
    assert health.last_modified == datetime(2025, 1, 24, 17, 12, 20, tzinfo=UTC)
    assert health.reason is not None
    assert health.reason.startswith(
        "the list file was last modified 2025-01-24T17:12:20Z, before the last winter began "
        "(2025-11-01T00:00:00Z); no weather that closes schools has come to its market since"
    )
    assert "idle, not abandoned" in health.reason


def test_a_list_file_that_missed_a_storm_is_stale(tmp_path: Path) -> None:
    synthetic_storm = ClosureEvent(date(2026, 1, 26), date(2026, 1, 27), 0.8, ("IS.W",))
    record = ClosureSeasons(date(2026, 10, 12), {WTOC: (SAVANNAH_SNOW, synthetic_storm)})
    station = REGISTRY.stations[WTOC]
    result = fetch.read_station(
        REGISTRY, station, _client(tmp_path), READ_AT, fetch.Judges(seasons=record)
    )
    (health,) = result.health
    assert health.status is HealthStatus.STALE
    assert health.reason is not None
    assert "not written for it: 2026-01-26 to 2026-01-27 (IS.W over 80%" in health.reason
    # Without the record (or without the market in it) such a list is stale too.
    for judges in (fetch.NO_JUDGES, fetch.Judges(seasons=ClosureSeasons(date(2026, 1, 1), {}))):
        (health,) = fetch.read_station(
            REGISTRY, station, _client(tmp_path / "again"), READ_AT, judges
        ).health
        assert health.status is HealthStatus.STALE
        assert "no closure-season record measures its market" in (health.reason or "")


def test_cli_seasons_then_fetch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    wtoc = REGISTRY.stations[WTOC]
    assert wtoc.counties is not None
    directory = tmp_path / "schools.parquet"
    pl.DataFrame(
        {
            "county_fips": [wtoc.counties.fips[0]] * 3 + ["99999"],
            "district_id": ["1300001", "1300001", None, "9999999"],
        }
    ).write_parquet(directory)
    counted = seasons.Counted(
        {wtoc.counties.fips[0]: {SAVANNAH_SNOW.first: {"WS.W"}}},
        date(2026, 10, 12),
        (_file(2025, "2026-09-26T00:00:00Z", final=True),),
    )
    monkeypatch.setattr(seasons, "count_closure_weather", lambda _cache, _today: counted)
    out = tmp_path / seasons.SEASONS_FILE
    assert main(["stations", "seasons", "--directory", str(directory), "--out", str(out)]) == 0
    assert "closure events, counted through 2026-10-12" in capsys.readouterr().out
    record = ClosureSeasons.load(out)
    assert record.events[WTOC] == (SAVANNAH_SNOW,)
    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["directory"]["schools"] == 4
    assert document["school_years"]["2025-26"]["final"] is True

    ticker = Ticker(READ_AT)
    monkeypatch.setattr(
        stations_cli,
        "make_client",
        lambda: httpx.Client(
            transport=httpx.MockTransport(_serve), headers={"User-Agent": USER_AGENT}
        ),
    )
    monkeypatch.setattr(
        stations_cli,
        "PoliteClient",
        partial(
            PoliteClient,
            timing=Timing(clock=ticker.clock, monotonic=ticker.monotonic, sleep=ticker.sleep),
        ),
    )
    monkeypatch.setattr(stations_cli, "system_clock", ticker.clock)
    code = main(
        [
            "stations",
            "fetch",
            "--only",
            WTOC,
            "--out-dir",
            str(tmp_path / "out"),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--typed-history",
            str(tmp_path / "typed-history.json"),
            "--archive-dir",
            str(tmp_path / "no-archive"),
            "--closure-days",
            str(out),
        ]
    )
    assert code == 0
    printed = capsys.readouterr().out
    assert "1 sources: 0 ok, 1 empty, 0 stale" in printed
    assert "closure seasons: " in printed
    health = json.loads((tmp_path / "out" / "health.json").read_text(encoding="utf-8"))
    assert health["sources"][0]["status"] == "empty"
    # A malformed record stops the run.
    out.write_text("{}", encoding="utf-8")
    refused = [
        "stations",
        "fetch",
        "--only",
        WTOC,
        "--typed-history",
        str(tmp_path / "typed-history.json"),
        "--archive-dir",
        str(tmp_path / "no-archive"),
        "--closure-days",
        str(out),
    ]
    assert main(refused) == 1
