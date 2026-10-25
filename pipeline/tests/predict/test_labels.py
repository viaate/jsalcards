"""District-day labels from settled statuses and reads (synthetic)."""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import polars as pl
import pytest

from snowlight.predict.config import PredictConfig
from snowlight.predict.labels import (
    DayLit,
    LabelInputs,
    LitStatus,
    Outcome,
    ReadRecord,
    Shares,
    audiences,
    carries,
    did_of,
    district_markets,
    fold_label_days,
    label_changes,
    label_day,
    label_days,
    listings_before,
    outcome_of,
    parse_reads,
    read_stations,
    reads_before,
    shares,
    station_stats,
    storm_absences,
    weather_positive,
    with_day_after,
)
from snowlight.predict.situations import WeatherClass
from snowlight.schemas.vocab import Reason, Status

SETTINGS = PredictConfig.load().labels
CHICAGO = "America/Chicago"
DAY = date(2025, 1, 6)
CLOSED_SNOW = LitStatus(Status.CLOSED, Reason.WINTER_STORM)


def read(source: str, when: str, state: str = "populated", rows: int = 12) -> ReadRecord:
    return ReadRecord(source, datetime.fromisoformat(when).replace(tzinfo=UTC), state, rows)


def inputs(**changes: Any) -> LabelInputs:
    base: dict[str, Any] = {
        "eligible": {"d1": ("s1", "s2", "s3", "s4"), "d2": ("s5", "s6"), "d3": ("s7",)},
        "zone_of": {"d1": CHICAGO, "d2": CHICAGO, "d3": CHICAGO},
        "audience": {
            "kaaa": {"d1": date(2024, 9, 3), "d2": date(2025, 1, 6)},
            "kbbb": {"d3": date(2024, 9, 3)},
        },
        # 13:00 UTC is 07:00 in Chicago: inside the 06:30 to 09:30 read window.
        "reads": [read("kaaa", "2025-01-06T13:00:00")],
        "market_of": {"kaaa": "Kansas City", "kbbb": "Kansas City"},
        "weather": {("d1", DAY): WeatherClass.SNOW_WARNING},
        "district_of": {
            f"s{i}": d
            for d, ids in {"d1": (1, 2, 3, 4), "d2": (5, 6), "d3": (7,)}.items()
            for i in ids
        },
    }
    base.update(changes)
    return LabelInputs(**base)


def outcomes(rows: list[dict[str, object]]) -> dict[object, object]:
    return {row["district"]: row["outcome"] for row in rows}


def test_lit_share_thresholds() -> None:
    lit = {"s1": CLOSED_SNOW, "s2": CLOSED_SNOW}
    assert outcomes(label_day(DAY, inputs(), lit, SETTINGS))["d1"] == "no_school"
    lit = {"s1": CLOSED_SNOW}
    assert outcomes(label_day(DAY, inputs(), lit, SETTINGS))["d1"] == "unknown"
    delayed = LitStatus(Status.DELAYED, Reason.ICE)
    lit = {"s1": delayed, "s2": delayed, "s3": CLOSED_SNOW}
    assert outcomes(label_day(DAY, inputs(), lit, SETTINGS))["d1"] == "delayed"
    # Read, nothing lit: open. A tenth or less lit with any status is still open.
    assert outcomes(label_day(DAY, inputs(), {}, SETTINGS))["d1"] == "open"
    big = {f"x{i}": () for i in range(10)}
    eligible = {"d1": tuple(f"x{i}" for i in range(10))}
    lit = {"x0": LitStatus(Status.EARLY_DISMISSAL, None)}
    found = label_day(
        DAY, inputs(eligible=eligible, district_of=dict.fromkeys(big, "d1")), lit, SETTINGS
    )
    assert outcomes(found)["d1"] == "open"


def test_unknown_when_no_station_of_its_audience_read() -> None:
    found = outcomes(label_day(DAY, inputs(), {}, SETTINGS))
    assert "d3" not in found  # kbbb never read: no row at all, never open
    lit = {"s7": CLOSED_SNOW}
    weather = {("d3", DAY): WeatherClass.SNOW_WARNING}
    # Lit closed but not read that morning: still no row (closings and open days are
    # labeled from the same reads).
    assert "d3" not in outcomes(label_day(DAY, inputs(weather=weather), lit, SETTINGS))


def test_an_evening_list_lights_a_district_only_read_that_morning() -> None:
    evening = [read("kaaa", "2025-01-06T02:00:00")]  # 20:00 the evening before
    lit = {"s5": LitStatus(Status.CLOSED, Reason.ICE), "s6": LitStatus(Status.REMOTE, Reason.ICE)}
    # The evening read alone: never open, and no closing either.
    assert outcomes(label_day(DAY, inputs(reads=evening), {}, SETTINGS)) == {}
    assert outcomes(label_day(DAY, inputs(reads=evening), lit, SETTINGS)) == {}
    # Read that morning too: what the evening list lit counts.
    both = [*evening, read("kaaa", "2025-01-06T13:00:00")]
    assert outcomes(label_day(DAY, inputs(reads=both), lit, SETTINGS))["d2"] == "no_school"


def test_an_empty_read_is_void_when_a_market_peer_holds_rows() -> None:
    empty = read("kaaa", "2025-01-06T13:00:00", state="empty", rows=0)
    busy = read("kbbb", "2025-01-06T13:30:00", rows=6)
    quiet = read("kbbb", "2025-01-06T13:30:00", rows=4)
    market = {"kaaa": "Kansas City", "kbbb": "Kansas City"}
    assert read_stations(DAY, CHICAGO, [empty, busy], market, SETTINGS) == {"kbbb"}
    assert read_stations(DAY, CHICAGO, [empty, quiet], market, SETTINGS) == {"kaaa", "kbbb"}
    deferred = read("kaaa", "2025-01-06T13:00:00", state="deferred", rows=0)
    assert read_stations(DAY, CHICAGO, [deferred], market, SETTINGS) == frozenset()
    rows = label_day(DAY, inputs(reads=[empty, busy]), {}, SETTINGS)
    assert outcomes(rows) == {"d1": "unknown", "d2": "unknown", "d3": "open"}
    assert whys(rows)["d1"] == "voided_empty"
    assert Shares(0.0, 0.0, 0.0).remote == 0.0


def test_heat_and_a_no_reason_closing_on_a_clear_day_are_unknown() -> None:
    heat = LitStatus(Status.CLOSED, Reason.HEAT)
    assert not weather_positive(heat, WeatherClass.SNOW_WARNING)
    bare = LitStatus(Status.CLOSED, None)
    assert not weather_positive(bare, WeatherClass.NONE)
    assert weather_positive(bare, WeatherClass.ADVISORY)
    assert not weather_positive(LitStatus(Status.EARLY_DISMISSAL, Reason.ICE), WeatherClass.ICE)
    lit = {"s5": bare, "s6": bare}
    assert outcomes(label_day(DAY, inputs(), lit, SETTINGS))["d2"] == "unknown"
    lit = {"s5": heat, "s6": heat}
    assert outcomes(label_day(DAY, inputs(), lit, SETTINGS))["d2"] == "unknown"


def test_shares_outcomes_and_what_the_district_did() -> None:
    remote = LitStatus(Status.REMOTE, Reason.WINTER_STORM)
    found = shares(("a", "b", "c"), {"a": remote, "b": remote, "c": CLOSED_SNOW}, WeatherClass.NONE)
    assert found.no_school == 1.0
    assert did_of(Outcome.NO_SCHOOL, found) == "remote"
    assert did_of(Outcome.NO_SCHOOL, Shares(1.0, 0.0, 1.0, 0.5)) == "closed"
    assert did_of(Outcome.DELAYED, found) == "delayed"
    assert did_of(Outcome.OPEN, found) == "open"
    assert did_of(Outcome.UNKNOWN, found) is None
    assert shares((), {}, WeatherClass.NONE) == Shares(0.0, 0.0, 0.0)
    assert outcome_of(Shares(0.0, 0.0, 0.0), read=False, settings=SETTINGS) is Outcome.UNKNOWN


def test_audiences_need_two_days_and_markets_follow_listings() -> None:
    listings = [
        ("kaaa", "d1", date(2025, 1, 6)),
        ("kaaa", "d1", date(2025, 1, 6)),
        ("kaaa", "d2", date(2025, 1, 6)),
        ("kaaa", "d2", date(2025, 1, 7)),
        ("kbbb", "d1", date(2025, 1, 8)),
    ]
    assert audiences(listings, 2) == {"kaaa": {"d2": date(2025, 1, 6)}}
    # A station carries a district only from the first day it listed it: never open before.
    carried = {"kaaa": {"d2": date(2025, 1, 6)}}
    assert carries(carried, "kaaa", date(2025, 1, 6)) == ["d2"]
    assert carries(carried, "kaaa", date(2024, 1, 8)) == []
    found = label_day(
        date(2024, 1, 8), inputs(reads=[read("kaaa", "2024-01-08T13:00:00")]), {}, SETTINGS
    )
    assert "d2" not in outcomes(found)
    markets = district_markets(listings, {"kaaa": "KC", "kbbb": "Wichita"})
    assert markets == {"d1": "KC", "d2": "KC"}


def test_label_days_skips_the_pandemic_and_marks_the_day_after() -> None:
    lit_by_day = {
        date(2025, 1, 6): {"s1": CLOSED_SNOW, "s2": CLOSED_SNOW},
        date(2025, 1, 7): {},
    }
    reads = [read("kaaa", "2025-01-06T13:00:00"), read("kaaa", "2025-01-07T13:00:00")]
    frame = label_days(
        [date(2020, 4, 1), date(2025, 1, 6), date(2025, 1, 7)],
        inputs(reads=reads),
        lambda day: DayLit(lit_by_day.get(day, {})),
        SETTINGS,
    )
    d1 = frame.filter(pl.col("district") == "d1").sort("day")
    assert d1["outcome"].to_list() == ["no_school", "open"]
    assert d1["after"].to_list() == [False, True]
    assert d1["did"].to_list() == ["closed", "open"]
    assert date(2020, 4, 1) not in frame["day"].to_list()
    empty = with_day_after(frame.head(0))
    assert empty.is_empty()


def test_parse_reads() -> None:
    lines = [
        '{"source_id":"kaaa","fetched_at":"2025-01-06T13:00:00Z","state":"populated","rows":3}',
        "",
        '{"source_id":"kbbb","fetched_at":"2025-01-06T13:00:00Z","state":"empty","rows":null}',
    ]
    found = parse_reads(lines)
    assert [item.rows for item in found] == [3, 0]
    assert found[0].fetched_at.tzinfo is not None


def whys(rows: list[dict[str, object]]) -> dict[object, object]:
    return {row["district"]: row["unknown_why"] for row in rows}


MORNING = datetime(2025, 1, 6, 13, 0, tzinfo=UTC)


def test_a_read_the_replay_step_dropped_never_shows_a_district_open() -> None:
    # The station's only morning read was dropped (read_low_match): nothing in it lit, so
    # nothing it carries is open, closed or anything: unknown, with why.
    dropped = DayLit({}, kept=frozenset())
    rows = label_day(DAY, inputs(), dropped, SETTINGS)
    assert outcomes(rows) == {"d1": "unknown", "d2": "unknown"}
    assert whys(rows) == {"d1": "dropped_read", "d2": "dropped_read"}
    assert all(row["readers"] == 0 for row in rows)
    # Statuses lit from an evening list still never make a closing without a kept read.
    lit = DayLit({"s1": CLOSED_SNOW, "s2": CLOSED_SNOW}, kept=frozenset())
    assert outcomes(label_day(DAY, inputs(), lit, SETTINGS))["d1"] == "unknown"
    # The same read kept: open and closed as before.
    kept = DayLit({}, kept=frozenset({("kaaa", MORNING)}))
    assert outcomes(label_day(DAY, inputs(), kept, SETTINGS)) == {"d1": "open", "d2": "open"}
    # A dropped read's rows never void a peer's empty read either.
    empty = read("kbbb", "2025-01-06T13:10:00", state="empty", rows=0)
    found = label_day(
        DAY, inputs(reads=[read("kaaa", "2025-01-06T13:00:00"), empty]), dropped, SETTINGS
    )
    assert outcomes(found)["d3"] == "open"


def test_a_station_with_few_captures_never_reads_a_district() -> None:
    rows = label_day(DAY, inputs(captures={"kaaa": 4, "kbbb": 9}), {}, SETTINGS)
    assert outcomes(rows) == {"d1": "unknown", "d2": "unknown"}
    assert whys(rows)["d1"] == "thin_station"
    assert outcomes(label_day(DAY, inputs(captures={"kaaa": 5}), {}, SETTINGS))["d1"] == "open"
    # Its empty reads still count (here with a market peer reading too).
    empty = read("kaaa", "2025-01-06T13:00:00", state="empty", rows=0)
    peer = read("kbbb", "2025-01-06T13:20:00", state="empty", rows=0)
    found = label_day(DAY, inputs(reads=[empty, peer], captures={"kaaa": 1}), {}, SETTINGS)
    assert outcomes(found)["d1"] == "open"
    counts, medians = station_stats(
        [read("kaaa", "2025-01-06T13:00:00", rows=10), read("kaaa", "2025-01-07T13:00:00", rows=30),
         read("kaaa", "2025-01-08T13:00:00", state="empty", rows=0)]
    )  # fmt: skip
    assert counts == {"kaaa": 2}
    assert medians == {"kaaa": 20.0}


def test_a_partial_capture_on_a_storm_day_shows_no_one_open() -> None:
    # 12 rows against a median of 40: on d1's storm day the list is partial, so d1 (snow
    # warning) is unknown; d2 (no alert) is still read by it.
    rows = label_day(DAY, inputs(median_rows={"kaaa": 40.0}), {}, SETTINGS)
    assert outcomes(rows) == {"d1": "unknown", "d2": "open"}
    assert whys(rows)["d1"] == "small_capture"
    assert (
        outcomes(label_day(DAY, inputs(median_rows={"kaaa": 24.0}), {}, SETTINGS))["d1"] == "open"
    )


def test_an_empty_read_alone_on_a_storm_day_needs_a_market_peer() -> None:
    empty = read("kaaa", "2025-01-06T13:00:00", state="empty", rows=0)
    rows = label_day(DAY, inputs(reads=[empty]), {}, SETTINGS)
    assert outcomes(rows) == {"d1": "unknown", "d2": "open"}  # d2 has no alert
    assert whys(rows)["d1"] == "empty_uncorroborated"
    peer = read("kbbb", "2025-01-06T13:20:00", state="empty", rows=0)
    assert outcomes(label_day(DAY, inputs(reads=[empty, peer]), {}, SETTINGS))["d1"] == "open"
    # A peer in another market does not corroborate.
    elsewhere = {"kaaa": "Kansas City", "kbbb": "Wichita"}
    found = label_day(DAY, inputs(reads=[empty, peer], market_of=elsewhere), {}, SETTINGS)
    assert outcomes(found)["d1"] == "unknown"


def test_likely_break_days_are_never_labeled() -> None:
    day = date(2024, 12, 19)
    reads = [read("kaaa", "2024-12-19T13:00:00")]
    rows = label_day(day, inputs(reads=reads), {}, SETTINGS)
    assert outcomes(rows) == {"d1": "unknown"}  # d2 is carried only from Jan 6
    assert set(whys(rows).values()) == {"break"}


def test_a_district_a_list_names_in_a_row_left_unlit_is_never_open() -> None:
    # The morning list names d1 ("Closed Monday") but the replay step could not light it (a
    # conflict, a status it could not date): d1 is not absent from the list, so not open.
    rows = label_day(DAY, inputs(), DayLit({}, listed=frozenset({"d1"})), SETTINGS)
    assert outcomes(rows) == {"d1": "unknown", "d2": "open"}
    assert whys(rows)["d1"] == "listed_unread"
    # A district the step did light closed is still a closing.
    lit = DayLit({"s1": CLOSED_SNOW, "s2": CLOSED_SNOW}, listed=frozenset({"d1"}))
    assert outcomes(label_day(DAY, inputs(), lit, SETTINGS))["d1"] == "no_school"


def test_absence_from_the_lists_is_not_open_when_the_market_closed() -> None:
    rows = [
        # day, district, outcome, weather, lit share
        ("a", "no_school", 5, 1.0),
        ("b", "no_school", 5, 1.0),
        ("c", "open", 5, 0.0),  # absent while 2 of its 3 peers closed: unknown
        ("d", "open", 5, 0.05),  # a status of its own lit: still open
        ("e", "open", 0, 0.0),  # no alert: open
    ]
    frame = pl.DataFrame(
        {
            "district": [r[0] for r in rows],
            "day": [DAY] * len(rows),
            "outcome": [r[1] for r in rows],
            "did": ["closed" if r[1] == "no_school" else "open" for r in rows],
            "unknown_why": [None] * len(rows),
            "readers": [1] * len(rows),
            "weather": [r[2] for r in rows],
            "lit_share": [r[3] for r in rows],
            "cluster": ["KC"] * len(rows),
        },
        schema_overrides={"readers": pl.Int32, "unknown_why": pl.String},
    )
    found = storm_absences(frame, 0.5)
    by = dict(zip(found["district"], found["outcome"], strict=True))
    assert by == {"a": "no_school", "b": "no_school", "c": "unknown", "d": "open", "e": "open"}
    why = dict(zip(found["district"], found["unknown_why"], strict=True))
    assert why["c"] == "absent_in_storm"
    assert found.filter(pl.col("district") == "c")["did"].to_list() == [None]
    # Another market's closings do not count.
    other = frame.with_columns(
        pl.when(pl.col("district").is_in(["a", "b"]))
        .then(pl.lit("Wichita"))
        .otherwise(pl.col("cluster"))
        .alias("cluster")
    )
    assert (
        dict(zip(*storm_absences(other, 0.5).select("district", "outcome"), strict=True))["c"]
        == "open"
    )


def test_a_fold_builds_audiences_and_gates_from_its_own_days_only() -> None:
    listings = [
        ("kaaa", "d1", date(2018, 1, 8)),
        ("kaaa", "d1", date(2019, 1, 8)),
        ("kaaa", "d2", date(2018, 1, 9)),
    ]
    before = date(2018, 7, 1)
    assert listings_before(listings, before) == [listings[0], listings[2]]
    # Built from the whole archive, kaaa carries d1 in 2018 only because 2019 named it again.
    assert audiences(listings, 2) == {"kaaa": {"d1": date(2018, 1, 8)}}
    assert audiences(listings_before(listings, before), 2) == {}
    reads = [read("kaaa", "2018-06-30T23:59:00"), read("kaaa", "2018-07-01T00:00:00")]
    assert reads_before(reads, before) == reads[:1]


def test_label_changes_count_known_labels_that_move() -> None:
    def frame(rows: list[tuple[str, str]]) -> pl.DataFrame:
        return pl.DataFrame(
            {
                "district": [d for d, _ in rows],
                "day": [DAY] * len(rows),
                "outcome": [o for _, o in rows],
            }
        )

    whole = frame([("d1", "open"), ("d2", "no_school"), ("d3", "unknown"), ("d4", "open")])
    fold = frame([("d1", "open"), ("d2", "unknown"), ("d3", "delayed"), ("d5", "unknown")])
    found = label_changes(whole, fold)
    assert found.training == 3
    assert found.changed == 2  # d2 to unknown, d4 to no row
    assert found.added == 1  # d3 from unknown
    assert found.pairs == {
        ("no_school", "unknown"): 1,
        ("open", "no_row"): 1,
        ("unknown", "delayed"): 1,
    }
    assert found.share == 1.0
    assert label_changes(whole, whole).share == 0.0
    assert label_changes(whole.head(0), whole.head(0)).share == 0.0


FOLD_START = date(2018, 7, 1)
"""The fold's test season (2018-19) starts here; 2017-18 is its training season."""
EARLY_DAYS = [date(2018, 2, 5), date(2018, 2, 6), date(2018, 2, 7)]
LATER_DAYS = [date(2019, 1, 8), date(2019, 1, 9), date(2019, 1, 10)]
STORM_DAY = date(2018, 2, 6)


def morning(day: date, rows: int = 12, source: str = "kaaa") -> ReadRecord:
    """A populated read at 07:00 Chicago (13:00 UTC) on ``day``."""
    return read(source, f"{day.isoformat()}T13:00:00", rows=rows)


def gate_reads(days: int, rows: int = 12, start: date = date(2018, 1, 15)) -> list[ReadRecord]:
    """``days`` populated reads of kaaa at 20:00 UTC (outside the read window) from ``start``."""
    return [
        read("kaaa", f"{date.fromordinal(start.toordinal() + i).isoformat()}T20:00:00", rows=rows)
        for i in range(days)
    ]


@dataclass(frozen=True, slots=True)
class Channel:
    """One way a later season could reach a fold's labels: what the seasons before the fold
    hold (``early_*``) and what a later season adds (``later_*``)."""

    early_listings: list[tuple[str, str, date]]
    early_reads: list[ReadRecord]
    later_listings: list[tuple[str, str, date]]
    later_reads: list[ReadRecord]
    weather: dict[tuple[str, date], WeatherClass] = field(default_factory=dict)
    market_of: dict[str, str] = field(
        default_factory=lambda: {"kaaa": "Kansas City", "kccc": "Topeka"}
    )


def two_days(district: str, station: str = "kaaa") -> list[tuple[str, str, date]]:
    return [(station, district, EARLY_DAYS[0]), (station, district, EARLY_DAYS[1])]


CHANNELS: dict[str, Channel] = {
    # d2 is listed once before the fold and once after: only a later season gives it an audience.
    "audiences": Channel(
        [*two_days("d1"), ("kaaa", "d2", EARLY_DAYS[0])],
        [*gate_reads(5), *(morning(day) for day in EARLY_DAYS)],
        [("kaaa", "d2", LATER_DAYS[0])],
        [morning(day) for day in LATER_DAYS],
    ),
    # kaaa has 3 populated captures before the fold (under the gate of 5), 20 with a later season.
    "captures": Channel(
        two_days("d1"),
        [morning(day) for day in EARLY_DAYS],
        [("kaaa", "d1", day) for day in LATER_DAYS],
        [*gate_reads(17, start=date(2019, 2, 1)), *(morning(day) for day in LATER_DAYS)],
    ),
    # kaaa's median list before the fold is 10 rows, so 6 rows on a storm morning is a whole list;
    # a later season's 40-row lists would make it a partial one (small_capture).
    "median_rows": Channel(
        two_days("d1"),
        [
            *gate_reads(5, rows=10),
            morning(EARLY_DAYS[0], 10),
            morning(STORM_DAY, 6),
            morning(EARLY_DAYS[2], 10),
        ],
        [("kaaa", "d1", day) for day in LATER_DAYS],
        [*gate_reads(20, rows=40, start=date(2019, 2, 1)), *(morning(d, 40) for d in LATER_DAYS)],
        weather={("d1", STORM_DAY): WeatherClass.SNOW_WARNING},
    ),
    # Before the fold kaaa (Kansas City) lists d1; a later season's Topeka lists outnumber it.
    "markets": Channel(
        two_days("d1"),
        [*gate_reads(5), *(morning(day) for day in EARLY_DAYS)],
        [("kccc", "d1", day) for day in (*LATER_DAYS, date(2019, 1, 11))],
        [morning(day) for day in LATER_DAYS],
    ),
}


def channel_builds(
    channel: Channel,
) -> tuple[tuple[pl.DataFrame, dict[str, str]], ...]:
    """(the fold's build, the build from the seasons before it alone, the whole archive's
    build of the same days)."""

    def build(
        days: list[date],
        listings: list[tuple[str, str, date]],
        reads: list[ReadRecord],
        cut: date | None,
    ) -> tuple[pl.DataFrame, dict[str, str]]:
        return fold_label_days(
            days,
            inputs(
                reads=sorted(reads, key=lambda item: item.fetched_at),
                audience={},
                weather=channel.weather,
                market_of=channel.market_of,
            ),
            listings,
            lambda _day: DayLit({}),
            SETTINGS,
            cut,
        )

    listings = [*channel.early_listings, *channel.later_listings]
    reads = [*channel.early_reads, *channel.later_reads]
    days = [*EARLY_DAYS, *LATER_DAYS]
    fold = build(days, listings, reads, FOLD_START)
    alone = build(EARLY_DAYS, channel.early_listings, channel.early_reads, None)
    whole, whole_markets = build(days, listings, reads, None)
    return fold, alone, (whole.filter(pl.col("day") < FOLD_START), whole_markets)


@pytest.mark.parametrize("name", sorted(CHANNELS))
def test_a_folds_labels_never_depend_on_a_later_season(name: str) -> None:
    (fold, fold_markets), (alone, alone_markets), (whole, whole_markets) = channel_builds(
        CHANNELS[name]
    )
    assert fold.height > 0  # the fold labels days, so the comparison is not of empty frames
    assert fold.equals(alone)
    assert fold_markets == alone_markets
    assert all(day < FOLD_START for day in fold["day"].to_list())
    # The whole archive's build of the same days differs, through this channel only.
    if name == "markets":
        assert fold_markets == {"d1": "Kansas City"}
        assert whole_markets == {"d1": "Topeka"}
    else:
        assert not whole.equals(fold)


def test_each_channel_moves_the_labels_the_way_its_later_season_would() -> None:
    def outcomes_of(frame: pl.DataFrame) -> set[tuple[object, ...]]:
        return set(frame.select("district", "day", "outcome", "unknown_why").iter_rows())

    (fold, _), _alone, (whole, _) = channel_builds(CHANNELS["audiences"])
    assert not fold.filter(pl.col("district") == "d2").height
    assert ("d2", EARLY_DAYS[1], "open", None) in outcomes_of(whole)
    (fold, _), _alone, (whole, _) = channel_builds(CHANNELS["captures"])
    assert {row[2:] for row in outcomes_of(fold)} == {("unknown", "thin_station")}
    assert {row[2] for row in outcomes_of(whole)} == {"open"}
    (fold, _), _alone, (whole, _) = channel_builds(CHANNELS["median_rows"])
    assert ("d1", STORM_DAY, "open", None) in outcomes_of(fold)
    assert ("d1", STORM_DAY, "unknown", "small_capture") in outcomes_of(whole)
