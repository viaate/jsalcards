"""Self-dating: a row held for an unknown posting time whose status names today's weekday or
date (or, on an evening read, tomorrow's) is dated by it, unless the row's own date says it is
older. Every name and text is SYNTHETIC."""

import itertools
import os
import sqlite3
import time
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from live.world import (
    ALPHA_DISTRICT,
    ALPHA_SCHOOL,
    PACIFIC,
    _school,
    accepted,
    at,
    default_matcher,
    directory,
    lit,
    reasons,
    row,
    station,
    stub_reader,
)
from live.world import World as Unwatched
from snowlight.live.ledger import (
    SCHEMA_VERSION,
    Ledger,
    LedgerRow,
    Outcome,
    SeenRow,
    Start,
    seen_row,
)
from snowlight.live.merge import UNBOUNDED, Item
from snowlight.live.resolve import (
    Derived,
    StatusReader,
    _posted_before,
    _successor_earliest,
    f5_reader,
)
from snowlight.live.weekdays import (
    _ages,
    _clocked,
    _lone_candidates,
    _mask_clocks,
    _weekday_words,
    named_weekdays,
    names_date,
    post_ages,
    stamp_dates,
    states_a_date,
    weekdays_in,
)
from snowlight.sources.stations.model import JsonScalar, RawRow

F5 = f5_reader()
THURSDAY = "2026-11-05"
FRIDAY = "2026-11-06"
SOURCE = "gray-synthetic"
WATCHING = "2026-10-01 12:00"
"""When the tests' ledgers first read a source: a ledger that has watched for weeks."""


@dataclass
class World(Unwatched):
    """A test world whose ledger has watched another source since :data:`WATCHING`, so a
    source it reads first is one no ledger read before."""

    def __post_init__(self) -> None:
        self.ledger.observe(
            "seed-synthetic", Outcome.OK, at(WATCHING), [row("SYNTHETIC Seed School")]
        )


def _cold(  # noqa: PLR0913 - the parts of one cold row
    when: str,
    text: str,
    *,
    reader: StatusReader = F5,
    name: str = ALPHA_SCHOOL,
    row_date: str = "",
    row_stamp: str | None = None,
) -> World:
    """A world whose list is first read at ``when`` (UTC) holding one row: a cold start."""
    world = World(reader=reader)
    stamp = None if row_stamp is None else at(row_stamp)
    world.read(at(when), [row(name, text, row_date=row_date, row_stamp=stamp)])
    return world


# --- what the words name ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "name", "named"),
    [
        ("Closed Thursday", "", {3}),
        ("CLOSED THURSDAY", "", {3}),
        ("Closed Thurs.", "", {3}),
        ("Closed Thursday, all activities cancelled", "", {3}),
        ("Closed Thursday (7 days ago)", "", set()),
        # a date in a form not read here may name another day
        ("Closed Thursday 10-29", "", set()),
        ("Closed Thursday 10.29", "", set()),
        ("Closed Thursday, 29 October", "", set()),
        ("Closed Thursday 20261029", "", set()),
        ("Closed Thursday. Posted 6 a.m. 29 October", "", set()),
        ("Closed Thursday. Posted by Supt. Lee 10-29", "", set()),
        ("Closed Thursday. October", "", set()),
        ("Closed Thursday, buses may run late", "", {3}),
        ("Closed Thursday, March band cancelled", "", {3}),
        ("Closed Thursday. Posted by Dr. Jones 3 days ago", "", set()),
        ("Closed Thu & Fri", "", {3, 4}),
        ("Closed Weds", "", {2}),
        ("Closed Weds.", "", {2}),
        ("Weds: Closed", "", {2}),
        ("Closed Weds and Thurs", "", {2, 3}),
        ("Closed Tues", "", {1}),
        ("Closed SAT", "", set()),
        ("Closed Sat", "", {5}),
        ("Closed Wednes", "", set()),  # the reader does not read it either
        ("Closed Thursday and Friday", "", {3, 4}),
        ("Closed Thursday. Updated Wednesday 9:00 PM", "", {3}),
        ("Closed", "", set()),
        ("Reopens Thursday", "", set()),
        ("Closed, reopens on Thursday", "", set()),
        ("Closed until Thursday", "", set()),
        ("Closed through Thursday", "", set()),
        ("Closed Wednesday, back to school Thursday", "", set()),
        ("Closed, students return Thursday", "", set()),
        ("Closed next Thursday", "", set()),
        ("Closed Mon-Wed", "", set()),
        ("Closed Monday to Wednesday", "", set()),
        ("Closed Ash Wednesday", "", set()),
        ("Closed for Black Friday", "", set()),
        ("Closed Thursday, Nov. 12", "", set()),
        ("Closed Thursday 11/12", "", set()),
        ("Closed Thursday the 12th", "", set()),
        ("Closed today, Thursday", "", set()),
        ("Closed tomorrow (Thursday)", "", set()),
        ("Friday Harbor SD - Closed", "Friday Harbor SD", set()),
        ("Closed Friday", "Friday Harbor SD", set()),
        ("Closed Thursday", "Friday Harbor SD", {3}),
    ],
)
def test_named_weekdays(text: str, name: str, named: set[int]) -> None:
    assert named_weekdays(text, name) == frozenset(named)


NOV5 = date(2026, 11, 5)


@pytest.mark.parametrize(
    ("text", "name", "states", "names"),
    [
        ("Closed Nov. 5", "", True, True),
        ("Closed Nov 5", "", True, True),
        ("Closed November 5th", "", True, True),
        ("Closed Thursday, November 5, 2026", "", True, True),
        ("Closed Nov 5, 2025", "", True, False),
        ("Closed Nov. 5 '25", "", True, False),
        ("Closed Nov. 5 '26", "", True, True),
        ("Closed until Nov. 5", "", True, False),
        ("Closed Nov. 5, reopens Nov. 9", "", True, False),
        ("Classes resume 11/5", "", True, False),
        ("Closed 11/5", "", True, True),
        ("Closed 11/05/26", "", True, True),
        ("Closed 11/5/2025", "", True, False),
        ("Closed 2026-11-05", "", True, True),
        ("Closed Nov. 15", "", True, False),
        ("Closed 11/15", "", True, False),
        ("Closed Nov. 6", "", True, False),
        ("Closed the 5th", "", True, False),
        ("Closed", "", False, False),
        ("Closed Thursday", "", False, False),
        ("Closed. Updated 11/5 6:00 AM", "", False, False),
        ("Nov 5 Academy - Closed", "Nov 5 Academy", False, False),
        ("Closed Nov. 5, notice of 10-29", "", True, False),  # a date it does not read
        ("Closed Nov. 5 (29 October notice)", "", True, False),
    ],
)
def test_names_date(text: str, name: str, states: bool, names: bool) -> None:
    assert states_a_date(text, name) is states
    assert names_date(text, NOV5, name) is names


# --- the trial miss: a cold row naming today -----------------------------------------------


def test_closed_thursday_read_thursday_morning_on_a_cold_start_lights_thursday() -> None:
    world = _cold("2026-11-05 12:00", "Closed Thursday")  # Thu 06:00 Central
    (resolved,) = world.resolve()
    assert reasons([resolved]) == [None]
    assert resolved.counts["weekday_dated"] == 1
    (result,) = resolved.rows
    assert result.row.lo is None
    assert result.derived.dated_by == "weekday"
    assert result.derived.announced_at is None
    merged = world.publish(at("2026-11-05 12:01"))
    assert lit(merged) == {(0, THURSDAY): "CLOSED"}
    (closing,) = merged.closings
    assert closing.announced_at is None


def test_a_bare_closed_on_a_cold_start_stays_held() -> None:
    world = _cold("2026-11-05 12:00", "Closed")
    assert reasons(world.resolve()) == ["unknown_start"]
    assert lit(world.publish(at("2026-11-05 12:01"))) == {}


def test_closed_thursday_read_friday_is_not_lit() -> None:
    world = _cold("2026-11-06 12:00", "Closed Thursday")  # Fri 06:00 Central
    (resolved,) = world.resolve()
    assert reasons([resolved]) == ["unknown_start"]
    assert "weekday_dated" not in resolved.counts
    assert lit(world.publish(at("2026-11-06 12:01"))) == {}


def test_closed_thursday_read_wednesday_evening_is_dated_tomorrow() -> None:
    world = _cold("2026-11-05 01:00", "Closed Thursday")  # Wed 19:00 Central
    assert lit(world.publish(at("2026-11-05 01:01"))) == {(0, THURSDAY): "CLOSED"}


@pytest.mark.parametrize("when", ["2026-11-04 12:00", "2026-11-04 19:00"])
def test_closed_thursday_read_wednesday_morning_or_midday_stays_held(when: str) -> None:
    world = _cold(when, "Closed Thursday")  # Wed 06:00 and 13:00 Central
    assert reasons(world.resolve()) == ["unknown_start"]
    assert lit(world.publish(at(when) + timedelta(minutes=1))) == {}


@pytest.mark.parametrize("when", ["2026-11-03 01:00", "2026-11-02 12:00"])
def test_a_weekday_two_or_more_days_ahead_stays_held(when: str) -> None:
    world = _cold(when, "Closed Thursday")  # Mon 19:00 and Mon 06:00 Central
    assert reasons(world.resolve()) == ["unknown_start"]


def test_closed_thu_and_fri_read_friday_lights_friday_only() -> None:
    world = _cold("2026-11-06 12:00", "Closed Thu & Fri")  # Fri 06:00 Central
    assert reasons(world.resolve()) == [None]
    merged = world.publish(at("2026-11-06 12:01"))
    assert lit(merged) == {(0, FRIDAY): "CLOSED"}  # Thursday is a past day
    assert merged.withheld.get("past_day") == 1


@pytest.mark.parametrize(
    "text", ["Reopens Thursday", "Closed until Thursday", "Closed, reopens on Thursday"]
)
def test_an_end_day_is_unchanged(text: str) -> None:
    world = _cold("2026-11-05 12:00", text)
    held = reasons(world.resolve())
    assert held != [None]
    assert lit(world.publish(at("2026-11-05 12:01"))) == {}


def test_a_weekday_in_the_name_and_not_the_status_is_unchanged() -> None:
    name = "SYNTHETIC Friday Harbor School"
    for text in ("Closed", "Closed Friday"):
        world = _cold("2026-11-06 12:00", text, name=name)
        world.matcher.table[name] = world.matcher.table[ALPHA_SCHOOL]
        assert reasons(world.resolve()) == ["unknown_start"]


def test_an_explicit_date_wins_over_the_weekday() -> None:
    world = _cold("2026-11-05 12:00", "Closed Thursday, Nov 12")
    assert reasons(world.resolve()) == ["unknown_start"]
    assert lit(world.publish(at("2026-11-05 12:01"))) == {}


# --- an explicit date dates a cold row as a weekday does (WD-R1-S3) ------------------------


@pytest.mark.parametrize(
    "text", ["Closed Nov. 5", "Closed Thursday Nov. 5", "Closed 11/5", "Closed Nov. 5 '26"]
)
def test_a_cold_row_stating_todays_date_lights_today(text: str) -> None:
    world = _cold("2026-11-05 12:00", text)  # Thu 06:00 Central
    (resolved,) = world.resolve()
    assert reasons([resolved]) == [None]
    assert resolved.counts["date_dated"] == 1
    assert "weekday_dated" not in resolved.counts
    assert resolved.rows[0].derived.dated_by == "date"
    assert lit(world.publish(at("2026-11-05 12:01"))) == {(0, THURSDAY): "CLOSED"}


@pytest.mark.parametrize(
    ("when", "text"),
    [
        ("2026-11-05 12:00", "Closed Friday Nov. 5"),  # the weekday and the date disagree
        ("2026-11-05 12:00", "Closed Nov 5, 2025"),  # another year
        ("2026-11-05 12:00", "Closed until Nov. 9"),  # the date is the end
        ("2026-11-05 12:00", "Closed Nov. 5 and 6"),  # Nov 6 is not stated as a date
        ("2026-11-05 12:00", "Reopens Nov. 5"),
        # an end word holds a date as it holds a weekday (WD-R2-S2), today's date too
        ("2026-11-05 12:00", "Closed until Nov. 5"),
        ("2026-11-05 12:00", "Closed until Nov 5th"),
        ("2026-11-05 12:00", "Classes resume Nov. 5"),
        ("2026-11-05 12:00", "Classes resume 11/5"),
        ("2026-11-05 12:00", "Back in session Nov. 5"),
        ("2026-11-05 12:00", "Closed. Will reopen on Nov. 5"),
        ("2026-11-05 12:00", "Closed through Nov. 5"),
        ("2026-11-05 12:00", "Closed Nov. 5-6"),
        # a year after the date in any form (WD-R2-S4)
        ("2026-11-05 12:00", "Closed Thursday, Nov. 5 '25"),
        ("2026-11-05 12:00", "Closed Nov. 5 \u201925"),
        ("2026-11-05 12:00", "Closed 11/5 2025"),
        ("2026-11-05 12:00", "Closed Nov. 6"),  # tomorrow, on a morning read
        ("2026-11-05 12:00", "Closed Nov. 4"),  # a past day
        ("2026-11-04 12:00", "Closed Nov. 5"),  # Wed 06:00: tomorrow on a morning read
    ],
)
def test_a_cold_row_stating_another_date_stays_dark(when: str, text: str) -> None:
    world = _cold(when, text)
    assert reasons(world.resolve()) != [None]
    assert lit(world.publish(at(when) + timedelta(minutes=1))) == {}


def test_a_cold_row_stating_tomorrows_date_on_an_evening_read_lights_tomorrow() -> None:
    world = _cold("2026-11-05 01:00", "Closed Nov. 5")  # Wed 19:00 Central
    assert lit(world.publish(at("2026-11-05 01:01"))) == {(0, THURSDAY): "CLOSED"}


# --- the row's own date bounds it (WD-R1-B1) -------------------------------------------------


@pytest.mark.parametrize(
    ("row_date", "shown"),
    [
        ("2026-10-29", False),  # last Thursday: "Thursday" was last week's
        ("10/29/2026", False),
        ("2026-10-22", False),
        ("2026-10-30", True),  # last Friday: the next Thursday is this one
        ("2026-11-04", True),  # the day before
        ("2026-11-05", True),  # the day itself
        ("2026-11-06", False),  # after the read
        ("2026-11-12", False),
        ("Thursday, November 5, 2026", True),  # a board's form
        ("SYNTHETIC unreadable", False),  # a row date that cannot be read keeps the hold
    ],
)
def test_the_rows_own_date_bounds_a_weekday_row(row_date: str, shown: bool) -> None:
    world = _cold("2026-11-05 12:00", "Closed Thursday", row_date=row_date)
    assert reasons(world.resolve()) == ([None] if shown else ["unknown_start"])
    expected = {(0, THURSDAY): "CLOSED"} if shown else {}
    assert lit(world.publish(at("2026-11-05 12:01"))) == expected


def test_an_evening_read_bounds_by_the_day_it_dates() -> None:
    # read Wed 19:00 for Thursday: a row dated last Thursday is last week's, last Friday's not
    for row_date, expected in (("2026-10-29", {}), ("2026-10-30", {(0, THURSDAY): "CLOSED"})):
        world = _cold("2026-11-05 01:00", "Closed Thursday", row_date=row_date)
        assert lit(world.publish(at("2026-11-05 01:01"))) == expected


@pytest.mark.parametrize(
    ("stamp", "shown"), [("2026-10-29 12:00", False), ("2026-11-02 12:00", True)]
)
def test_an_old_row_stamp_bounds_a_weekday_row(stamp: str, shown: bool) -> None:
    # a stamp older than the stamp window dates nothing, but still says when it was posted
    world = _cold("2026-11-05 12:00", "Closed Thursday", row_stamp=stamp)
    assert reasons(world.resolve()) == ([None] if shown else ["unknown_start"])


def test_the_rows_own_date_bounds_a_date_row() -> None:
    world = _cold("2026-11-05 12:00", "Closed Nov. 5", row_date="2026-10-29")
    assert reasons(world.resolve()) == ["unknown_start"]


def test_a_gray_row_dated_last_week_stays_held() -> None:
    raw = RawRow(
        source_id=SOURCE,
        fetched_at=at("2026-11-05 12:00"),
        raw_name=ALPHA_SCHOOL,
        raw_status="Closed Thursday",
        raw_updated_text="2026-10-29",
        raw_extra={"updated_scope": "row"},
    )
    seen = seen_row(raw, variant="", platform="gray", zone="America/Chicago")
    world = World(reader=F5)
    world.read(at("2026-11-05 12:00"), [seen])
    assert reasons(world.resolve()) == ["unknown_start"]
    assert lit(world.publish(at("2026-11-05 12:01"))) == {}


def test_a_dated_row_is_never_extended_past_its_day() -> None:
    world = _cold("2026-11-05 12:00", "Closed Thursday")
    assert lit(world.publish(at("2026-11-05 12:01"))) == {(0, THURSDAY): "CLOSED"}
    world.read(at("2026-11-06 12:00"), [row(ALPHA_SCHOOL, "Closed Thursday")])
    merged = world.publish(at("2026-11-06 12:01"))
    assert lit(merged) == {}
    assert merged.withheld.get("past_day") == 1


def test_a_warm_row_is_read_as_before() -> None:
    world = World(reader=F5)
    world.read(at("2026-11-04 14:00"), [])  # Wednesday, the school day before
    world.read(at("2026-11-05 11:45"), [])
    world.read(at("2026-11-05 12:00"), [row(ALPHA_SCHOOL, "Closed Thursday")])
    (resolved,) = world.resolve()
    assert not resolved.rows[0].derived.dated_by
    assert lit(world.publish(at("2026-11-05 12:01"))) == {(0, THURSDAY): "CLOSED"}


def test_the_stub_reader_gives_the_same() -> None:
    world = _cold("2026-11-05 12:00", "Closed Thursday", reader=stub_reader)
    assert lit(world.publish(at("2026-11-05 12:01"))) == {(0, THURSDAY): "CLOSED"}


def test_a_held_note_keeps_the_row_held() -> None:
    # the reader's activities note is a hold of its own (``NOTE``), weekday or not
    world = _cold("2026-11-05 12:00", "Closed Thursday, all activities cancelled")
    assert reasons(world.resolve()) == ["unknown_start"]


def test_a_board_row_keeps_its_board_rule() -> None:
    board = "flathead-synthetic"
    world = World(reader=F5, stations={board: station(board)})
    world.read(at("2026-11-05 12:00"), [row(ALPHA_SCHOOL, "Closed Thursday")], source=board)
    assert reasons(world.resolve()) == ["unknown_start"]


# --- clocks: daylight saving and zones -------------------------------------------------------


def test_the_dst_weekend() -> None:
    # Sunday Nov 1 2026 the clocks fall back; 01:00Z Monday is Sunday 19:00 Central
    evening = _cold("2026-11-02 01:00", "Closed Monday")
    assert lit(evening.publish(at("2026-11-02 01:01"))) == {(0, "2026-11-02"): "CLOSED"}
    morning = _cold("2026-11-02 11:30", "Closed Monday")  # Monday 05:30 Central (CST)
    assert lit(morning.publish(at("2026-11-02 11:31"))) == {(0, "2026-11-02"): "CLOSED"}
    # Sunday 00:30 Central (CDT, before the change) is Saturday's night, no evening read
    early = _cold("2026-11-01 05:30", "Closed Monday")
    assert reasons(early.resolve()) == ["unknown_start"]
    # Saturday 19:00 Central (CDT): Monday is two days ahead
    saturday = _cold("2026-11-01 00:00", "Closed Monday")
    assert reasons(saturday.resolve()) == ["unknown_start"]


@pytest.mark.parametrize(
    ("when", "shown"),
    [
        ("2026-11-08 06:30", False),  # Sun 00:30 Central
        ("2026-11-08 14:00", False),  # Sun 08:00: the reader dates a bare "Closed" Monday,
        ("2026-11-08 20:00", False),  # Sun 14:00   but no weekday read then is an evening's
        ("2026-11-09 01:00", True),  # Sun 19:00
        ("2026-11-09 05:00", True),  # Sun 23:00
    ],
)
def test_a_sunday_reads_monday_as_tomorrow_only_in_the_evening(when: str, shown: bool) -> None:
    world = _cold(when, "Closed Monday")
    assert reasons(world.resolve()) == ([None] if shown else ["unknown_start"])
    expected = {(0, "2026-11-09"): "CLOSED"} if shown else {}
    assert lit(world.publish(at(when) + timedelta(minutes=1))) == expected


def test_closed_weds_read_wednesday_lights_wednesday() -> None:
    world = _cold("2026-11-04 12:00", "Closed Weds")  # Wed 06:00 Central
    assert lit(world.publish(at("2026-11-04 12:01"))) == {(0, "2026-11-04"): "CLOSED"}


@pytest.fixture
def tokyo_runner() -> Iterator[None]:
    """The runner's own zone set far from the source's."""
    before = os.environ.get("TZ")
    os.environ["TZ"] = "Asia/Tokyo"
    time.tzset()
    yield
    if before is None:
        del os.environ["TZ"]
    else:
        os.environ["TZ"] = before
    time.tzset()


@pytest.mark.usefixtures("tokyo_runner")
def test_a_source_in_another_zone_than_the_runner() -> None:
    # 06:30Z Friday is Thursday 22:30 Pacific and Friday 15:30 in Tokyo
    pacific = "SYNTHETIC Pacific School"
    thursday = _cold("2026-11-06 06:30", "Closed Thursday", name=pacific)
    assert lit(thursday.publish(at("2026-11-06 06:31"))) == {(7, THURSDAY): "CLOSED"}
    friday = _cold("2026-11-06 06:30", "Closed Friday", name=pacific)
    assert lit(friday.publish(at("2026-11-06 06:31"))) == {(7, FRIDAY): "CLOSED"}
    assert friday.dir.schools[PACIFIC].zones == ("America/Los_Angeles",)


# --- merge: a weekday-dated row may have been posted at any time ----------------------------


def test_an_older_retraction_from_another_source_still_darkens_it() -> None:
    other = "gray-synthetic2"
    world = World(reader=F5, stations={SOURCE: station(), other: station(other)})
    world.read(at("2026-11-04 14:00"), [], source=other)
    world.read(at("2026-11-05 10:45"), [], source=other)
    world.read(at("2026-11-05 11:00"), [row(ALPHA_SCHOOL, "Closing rescinded")], source=other)
    world.read(at("2026-11-05 12:00"), [row(ALPHA_SCHOOL, "Closed Thursday")])
    resolved = {source.source_id: source for source in world.resolve()}
    assert resolved[SOURCE].rows[0].derived.dated_by == "weekday"
    merged = world.publish(at("2026-11-05 12:01"))
    assert lit(merged) == {}
    assert merged.withheld.get("conflict") == 1
    # the same words watched appearing after the retraction are newer, and light
    warm = World(reader=F5, stations={SOURCE: station(), other: station(other)})
    for source in (SOURCE, other):
        warm.read(at("2026-11-04 14:00"), [], source=source)
        warm.read(at("2026-11-05 10:45"), [], source=source)
    warm.read(at("2026-11-05 11:00"), [row(ALPHA_SCHOOL, "Closing rescinded")], source=other)
    warm.read(at("2026-11-05 11:45"), [])
    warm.read(at("2026-11-05 12:00"), [row(ALPHA_SCHOOL, "Closed Thursday")])
    assert lit(warm.publish(at("2026-11-05 12:01"))) == {(0, THURSDAY): "CLOSED"}


def test_item_posted_lo_is_unbounded_for_a_weekday_row() -> None:
    world = _cold("2026-11-05 12:00", "Closed Thursday")
    (resolved,) = world.resolve()
    (result,) = resolved.rows
    claim = result.derived.claims[0]
    item = Item("claim", 0, "200000100001", claim.day, claim, "school", SOURCE, result)
    assert item.posted_lo == UNBOUNDED
    assert item.posted_hi == result.row.hi


# --- storage ---------------------------------------------------------------------------------


def test_the_flag_is_stored_and_old_payloads_read_without_it() -> None:
    world = _cold("2026-11-05 12:00", "Closed Thursday")
    derived = world.resolve()[0].rows[0].derived
    stored = derived.to_json()
    assert stored["dated_by"] == "weekday"
    assert Derived.from_json(stored) == derived
    old = {key: value for key, value in stored.items() if key != "dated_by"}
    assert Derived.from_json(old) == replace(derived, dated_by="")
    with pytest.raises(ValueError, match="dated by"):
        Derived.from_json({**stored, "dated_by": "yes"})


def test_a_reused_derivation_keeps_lighting_its_day_only() -> None:
    world = _cold("2026-11-05 12:00", "Closed Thursday")
    world.resolve()
    world.read(at("2026-11-05 12:15"), [row(ALPHA_SCHOOL, "Closed Thursday")])
    (again,) = world.resolve()
    assert again.counts["reused"] == 1
    assert again.counts["weekday_dated"] == 1
    assert lit(world.publish(at("2026-11-05 12:16"))) == {(0, THURSDAY): "CLOSED"}


def test_a_real_row_shape_reaches_the_rule() -> None:
    raw = RawRow(
        source_id=SOURCE,
        fetched_at=at("2026-11-05 12:00"),
        raw_name=ALPHA_SCHOOL,
        raw_status="Closed Thursday",
        raw_updated_text="2026-11-04",
        raw_extra={"updated_scope": "row"},
    )
    seen = seen_row(raw, variant="", platform="gray", zone="America/Chicago")
    assert seen.row_stamp is None  # a date with no time dates nothing
    world = World(reader=F5)
    world.read(at("2026-11-05 12:00"), [seen])
    assert lit(world.publish(at("2026-11-05 12:01"))) == {(0, THURSDAY): "CLOSED"}
    assert date.fromisoformat(THURSDAY).weekday() == 3


def test_a_district_row_naming_part_of_its_district_keeps_its_hold() -> None:
    world = _cold("2026-11-05 12:00", "Closed Thursday: high school campus", name=ALPHA_DISTRICT)
    assert reasons(world.resolve()) == ["unknown_start"]
    assert lit(world.publish(at("2026-11-05 12:01"))) == {}


@pytest.mark.parametrize("text", ["Closed Thursday", "Closed"])
def test_a_re_keyed_list_stays_held_even_with_new_names(text: str) -> None:
    # a churn read may re-key last week's rows or re-serve an old copy: nothing bounds when
    # a row of it went up, so it is never dated by its weekday (WD-R3-B1)
    world = World(reader=F5)
    before = [row(f"SYNTHETIC Old School {number}", "Closed") for number in range(6)]
    world.read(at("2026-11-04 14:00"), before)
    world.read(at("2026-11-05 11:45"), before)
    after = [row(f"SYNTHETIC New School {number}", "Closed") for number in range(5)]
    world.read(at("2026-11-05 12:00"), [*after, row(ALPHA_SCHOOL, text)])
    (resolved,) = world.resolve()
    ours = [r for r in resolved.rows if r.derived.targets or r.derived.withheld == "churn"]
    assert {r.derived.withheld for r in ours} == {"churn"}
    assert "self_dated:churn" not in resolved.counts
    assert "weekday_dated" not in resolved.counts
    assert lit(world.publish(at("2026-11-05 12:01"))) == {}


# --- a key the ledger saw before (WD-R2-B1) --------------------------------------------------

OTHERS = [
    row(f"SYNTHETIC Other School {number}", "Closed until further notice") for number in range(6)
]
THURSDAY_ROW = row(ALPHA_SCHOOL, "Closed Thursday")


def _hours(world: World, start: str, end: str, rows: list[SeenRow], step: int = 6) -> None:
    """Read the list every ``step`` hours from ``start`` up to ``end`` (UTC)."""
    moment = at(start)
    while moment < at(end):
        world.read(moment, rows)
        moment += timedelta(hours=step)


def _ours(world: World) -> Derived:
    (resolved,) = world.resolve()
    (ours,) = [r for r in resolved.rows if r.row.key == world.ledger.key(SOURCE, THURSDAY_ROW)]
    return ours.derived


def test_a_row_listed_last_week_that_flaps_off_and_back_this_thursday_stays_held() -> None:
    world = World(reader=F5)
    world.read(at("2026-10-28 23:00"), OTHERS)
    _hours(world, "2026-10-29 00:00", "2026-11-04 12:00", [THURSDAY_ROW, *OTHERS])  # Wed 19:00
    _hours(world, "2026-11-04 12:00", "2026-11-05 12:00", OTHERS)  # off for a day, nothing new
    world.read(at("2026-11-05 12:00"), [THURSDAY_ROW, *OTHERS])  # back Thu 06:00 Central
    entry = world.ledger.row(world.ledger.key(SOURCE, THURSDAY_ROW))
    assert entry is not None
    # first seen on a warm read with no link: bounded by the source's read before (WD-R4C2-B1)
    assert (entry.hi, entry.lo, entry.earliest) == (
        at("2026-11-05 12:00"),
        None,
        at("2026-10-28 23:00"),
    )
    derived = _ours(world)
    assert (derived.withheld, derived.dated_by) == ("unknown_start", "")
    assert {k: v for k, v in lit(world.publish(at("2026-11-05 12:01"))).items() if k[0] == 0} == {}


def test_a_row_off_the_list_a_whole_week_and_back_on_its_weekday_stays_held() -> None:
    world = World(reader=F5)
    world.read(at("2026-10-29 10:00"), OTHERS)
    world.read(at("2026-10-29 11:00"), [THURSDAY_ROW, *OTHERS])  # last Thursday 06:00
    _hours(world, "2026-10-29 12:00", "2026-11-05 12:00", OTHERS)
    world.read(at("2026-11-05 12:00"), [THURSDAY_ROW, *OTHERS])
    assert _ours(world).withheld == "unknown_start"
    assert {k: v for k, v in lit(world.publish(at("2026-11-05 12:01"))).items() if k[0] == 0} == {}


def test_a_gone_row_back_after_a_reader_gap_stays_held() -> None:
    # off the list while it showed something new (gone), then no read for two days: back on a
    # cold start, it is still the row first seen last week
    world = World(reader=F5)
    world.read(at("2026-10-28 23:00"), OTHERS)
    _hours(world, "2026-10-29 00:00", "2026-11-02 12:00", [THURSDAY_ROW, *OTHERS])
    fresh = row("SYNTHETIC New School", "Closed until further notice")
    _hours(world, "2026-11-02 12:00", "2026-11-03 12:00", [fresh, *OTHERS])
    world.read(at("2026-11-05 12:00"), [THURSDAY_ROW, fresh, *OTHERS])
    entry = world.ledger.row(world.ledger.key(SOURCE, THURSDAY_ROW))
    assert entry is not None
    # back after a gap: bounded by every sighting of the source too (WD-R4C1-B1)
    assert (entry.lo, entry.start, entry.earliest) == (None, Start.COLD, at("2026-10-28 23:00"))
    assert _ours(world).withheld == "unknown_start"
    assert {k: v for k, v in lit(world.publish(at("2026-11-05 12:01"))).items() if k[0] == 0} == {}


def test_a_row_first_seen_the_evening_before_that_flaps_still_lights() -> None:
    # first seen on a cold start Wed 19:00 (for Thursday), off for 6 hours, back Thursday: its
    # earliest sighting dates it to Thursday too, as if it had never left
    world = World(reader=F5)
    world.read(at("2026-11-05 00:00"), [THURSDAY_ROW, *OTHERS])
    assert lit(world.publish(at("2026-11-05 00:01"))) == {(0, THURSDAY): "CLOSED"}
    world.read(at("2026-11-05 03:00"), OTHERS)
    world.read(at("2026-11-05 09:00"), OTHERS)
    world.read(at("2026-11-05 12:00"), [THURSDAY_ROW, *OTHERS])
    entry = world.ledger.row(world.ledger.key(SOURCE, THURSDAY_ROW))
    assert entry is not None
    assert (entry.hi, entry.lo, entry.earliest) == (at("2026-11-05 12:00"), None, at("2026-11-05"))
    assert _ours(world).dated_by == "weekday"
    assert lit(world.publish(at("2026-11-05 12:01"))) == {(0, THURSDAY): "CLOSED"}


def test_a_new_key_on_a_cold_start_has_no_earlier_sighting_and_lights() -> None:
    world = _cold("2026-11-05 12:00", "Closed Thursday")
    (entry,) = world.ledger.rows(SOURCE)
    assert (entry.lo, entry.start, entry.earliest) == (None, Start.COLD, at("2026-11-05 12:00"))
    assert lit(world.publish(at("2026-11-05 12:01"))) == {(0, THURSDAY): "CLOSED"}


@pytest.mark.parametrize(
    ("first", "shown"), [("2026-10-29 11:00", False), ("2026-11-05 11:00", True)]
)
def test_a_successor_of_tied_keys_is_bounded_by_their_first_sighting(
    first: str, shown: bool
) -> None:
    world = World(reader=F5)
    twins = [row(ALPHA_SCHOOL, "Closed"), row(ALPHA_SCHOOL, "2 hour delay")]
    world.read(at(first) - timedelta(hours=1), OTHERS)
    _hours(world, first, "2026-11-05 12:00", [*twins, *OTHERS], step=3)
    world.read(at("2026-11-05 12:00"), [THURSDAY_ROW, *OTHERS])
    entry = world.ledger.row(world.ledger.key(SOURCE, THURSDAY_ROW))
    assert entry is not None
    # the twins, first seen on a warm read with no link, keep the read before (WD-R4C2-B1)
    assert (entry.lo, entry.pred, entry.earliest) == (None, None, at(first) - timedelta(hours=1))
    assert _ours(world).withheld == (None if shown else "unknown_start")
    expected = {(0, THURSDAY): "CLOSED"} if shown else {}
    assert {
        k: v for k, v in lit(world.publish(at("2026-11-05 12:01"))).items() if k[0] == 0
    } == expected


def test_a_ledger_from_before_the_column_opens_and_keeps_its_rows(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite"
    ledger = Ledger(path)
    ledger.observe(SOURCE, Outcome.OK, at("2026-11-05 12:00"), [THURSDAY_ROW])
    ledger.close()
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("ALTER TABLE rows DROP COLUMN earliest")  # as written before it
    reopened = Ledger(path)
    (entry,) = reopened.rows(SOURCE)
    assert (entry.hi, entry.earliest) == (at("2026-11-05 12:00"), None)
    # a row written before the column has no known earliest sighting: it is never self-dated
    world = World(reader=F5, ledger=reopened)
    world.last[SOURCE] = [THURSDAY_ROW]
    assert reasons(world.resolve()) == ["unknown_start"]
    assert lit(world.publish(at("2026-11-05 12:01"))) == {}
    reopened.close()
    with closing(sqlite3.connect(path)) as db:  # code from before reads it unchanged
        old = db.execute(
            "SELECT key, source_id, hi, lo, start, row_stamp, last_seen, absent_since, gone,"
            " ident, pred, lapsed FROM rows WHERE source_id = ?",
            (SOURCE,),
        ).fetchall()
        assert len(old) == 1
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


# --- never raising (WD-R2-S1) ----------------------------------------------------------------

MALFORMED = [
    "2026-02-30 12:00",
    "9999-99-99 12:00",
    "2026-11-31T06:00:00",
    "2026-11-05 25:00",
    "2026-00-10 06:00",
]


@pytest.mark.parametrize("platform", ["gray", "wveis", "gohsep", "flathead"])
@pytest.mark.parametrize("row_date", MALFORMED)
def test_a_row_date_that_does_not_exist_keeps_the_hold_and_never_raises(
    platform: str, row_date: str
) -> None:
    source = f"{platform}-synthetic"
    world = World(reader=F5, stations={source: station(source)})
    world.read(
        at("2026-11-05 12:00"),
        [row(ALPHA_SCHOOL, "Closed Thursday", row_date=row_date)],
        source=source,
    )
    (resolved,) = world.resolve()
    assert reasons([resolved]) != [None]
    assert "weekday_dated" not in resolved.counts
    assert lit(world.publish(at("2026-11-05 12:01"))) == {}


@settings(max_examples=400, deadline=None)
@given(
    st.one_of(
        st.text(max_size=30),
        st.from_regex(r"\A\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?\Z"),
        st.from_regex(r"\A\d{1,2}/\d{1,2}/\d{2,4}( \d{1,2}:\d{2} ?[AP]M)?\Z"),
    )
)
def test_the_rows_own_date_never_raises(row_date: str) -> None:
    seen = row(ALPHA_SCHOOL, "Closed Thursday", row_date=row_date)
    hi = at("2026-11-05 12:00")
    entry = LedgerRow(
        key=b"k",
        source_id=SOURCE,
        hi=hi,
        lo=None,
        start=Start.COLD,
        row_stamp=None,
        last_seen=hi,
        absent_since=None,
        gone=False,
        ident=b"i",
        pred=None,
        lapsed=False,
    )
    _posted_before(seen, entry, ["America/Chicago", "America/Denver"], date(2026, 11, 5))


# --- counts (WD-R2-S3) -----------------------------------------------------------------------


def test_self_dated_rows_are_counted_by_why_they_were_held() -> None:
    (resolved,) = _cold("2026-11-05 12:00", "Closed Thursday").resolve()
    assert resolved.counts["self_dated:unknown_start"] == 1
    assert resolved.counts["kept"] == 1
    assert "withheld:unknown_start" not in resolved.counts


def test_a_row_scoped_stamp_that_does_not_exist_reads_as_none_and_keeps_the_hold() -> None:
    raw = RawRow(
        source_id=SOURCE,
        fetched_at=at("2026-11-05 12:00"),
        raw_name=ALPHA_SCHOOL,
        raw_status="Closed Thursday",
        raw_updated_text="2026-02-30 12:00",
        raw_extra={"updated_scope": "row"},
    )
    seen = seen_row(raw, variant="", platform="gray", zone="America/Chicago")
    assert (seen.row_stamp, seen.row_date) == (None, "2026-02-30 12:00")
    world = World(reader=F5)
    world.read(at("2026-11-05 12:00"), [seen])
    assert reasons(world.resolve()) == ["unknown_start"]
    assert lit(world.publish(at("2026-11-05 12:01"))) == {}


def test_a_row_date_reader_that_raises_keeps_the_hold(monkeypatch: pytest.MonkeyPatch) -> None:
    # the live boundary holds even if a row-date reader it calls ever raises again
    def raising(*_: object) -> None:
        raise ValueError("SYNTHETIC")

    monkeypatch.setattr("snowlight.live.resolve.posted_stamp", raising)
    world = _cold("2026-11-05 12:00", "Closed Thursday", row_date="2026-11-04")
    assert reasons(world.resolve()) == ["unknown_start"]


# --- re-keyed lists, reader gaps and old copies (WD-R3-B1) -----------------------------------


def _listing(section: str) -> list[SeenRow]:
    """The Thursday row and the others, under one section header."""
    return [
        row(ALPHA_SCHOOL, "Closed Thursday", section=section),
        *[
            row(f"SYNTHETIC Other School {number}", "Closed until further notice", section=section)
            for number in range(6)
        ],
    ]


def _alpha_lit(world: Unwatched, when: str) -> dict[tuple[int, str], str]:
    return {k: v for k, v in lit(world.publish(at(when))).items() if k[0] == 0}


def _alpha_entry(world: Unwatched) -> LedgerRow:
    """The ledger row of the last read's first row (the Thursday row)."""
    entry = world.ledger.row(world.ledger.key(SOURCE, world.last[SOURCE][0]))
    assert entry is not None
    return entry


def test_a_stale_row_re_sectioned_on_a_warm_read_stays_held() -> None:
    # listed since Wed Oct 28 19:00 Central (for Oct 29), the section renamed Thu Nov 5
    world = World(reader=F5)
    world.read(at("2026-10-28 23:00"), _listing("Schools")[1:])
    _hours(world, "2026-10-29 00:00", "2026-11-05 12:00", _listing("Schools"), step=3)
    world.read(at("2026-11-05 12:00"), _listing("Public Schools"))
    entry = _alpha_entry(world)
    assert (entry.start, entry.lo, entry.pred) == (Start.CHURN, None, None)
    assert entry.earliest is not None
    assert entry.earliest <= at("2026-10-29 00:00")
    (resolved,) = world.resolve()
    assert "weekday_dated" not in resolved.counts
    assert _alpha_lit(world, "2026-11-05 12:01") == {}


def test_a_stale_row_re_sectioned_after_a_reader_gap_stays_held() -> None:
    world = World(reader=F5)
    world.read(at("2026-10-28 23:00"), _listing("Schools")[1:])
    _hours(world, "2026-10-29 00:00", "2026-11-03 12:00", _listing("Schools"))
    world.read(at("2026-11-05 12:00"), _listing("Public Schools"))  # back after 2 days, re-keyed
    entry = _alpha_entry(world)
    assert (entry.start, entry.lo) == (Start.COLD, None)
    assert entry.earliest is not None
    assert entry.earliest <= at("2026-10-29 00:00")
    (resolved,) = world.resolve()
    assert "weekday_dated" not in resolved.counts
    assert _alpha_lit(world, "2026-11-05 12:01") == {}


def test_a_new_row_after_a_reader_gap_is_bounded_by_the_read_before_the_gap() -> None:
    # nothing vanished: the row went up some time in the gap, perhaps last Thursday
    world = World(reader=F5)
    _hours(world, "2026-10-27 12:00", "2026-11-03 12:00", OTHERS)
    world.read(at("2026-11-05 12:00"), [THURSDAY_ROW, *OTHERS])
    entry = world.ledger.row(world.ledger.key(SOURCE, THURSDAY_ROW))
    assert entry is not None
    assert (entry.start, entry.lo, entry.earliest) == (Start.COLD, None, at("2026-10-27 12:00"))
    assert _ours(world).withheld == "unknown_start"
    assert _alpha_lit(world, "2026-11-05 12:01") == {}


@pytest.mark.parametrize("last", ["2026-11-03 12:00", "2026-11-04 12:00", "2026-11-04 23:59"])
def test_no_cold_read_of_a_source_read_before_self_dates(last: str) -> None:
    # read Fri 06:00 Central, more than 36 hours after the read before (a cold read): never
    # self-dated, even when the read before was a Wednesday evening (17:59 Central)
    world = World(reader=F5)
    world.read(at(last), OTHERS)
    friday = row(ALPHA_SCHOOL, "Closed Friday")
    world.read(at("2026-11-06 12:00"), [friday, *OTHERS])
    (resolved,) = world.resolve()
    assert "weekday_dated" not in resolved.counts
    assert _alpha_lit(world, "2026-11-06 12:01") == {}


def test_a_source_read_before_whose_rows_were_all_pruned_stays_held() -> None:
    world = World(reader=F5)
    world.read(at("2026-10-10 12:00"), OTHERS)
    fresh = [row(f"SYNTHETIC Fresh School {number}", "Closed") for number in range(6)]
    world.read(at("2026-11-05 12:00"), [THURSDAY_ROW, *fresh])
    assert len(world.ledger.rows(SOURCE)) == 7  # the old rows are pruned
    entry = world.ledger.row(world.ledger.key(SOURCE, THURSDAY_ROW))
    assert entry is not None
    assert entry.earliest == at("2026-10-10 12:00")
    assert _ours(world).withheld == "unknown_start"
    assert _alpha_lit(world, "2026-11-05 12:01") == {}


OLD_COPY = [row(f"SYNTHETIC Old Copy School {number}", "Closed") for number in range(6)]
TODAYS = [row(f"SYNTHETIC Today School {number}", "Closed") for number in range(6)]


def test_an_old_copy_of_the_page_served_on_a_warm_read_stays_held() -> None:
    # this morning's list, then an old copy of last week's page from a cache: a churn read
    world = World(reader=F5)
    world.read(at("2026-11-05 10:00"), TODAYS)
    world.read(at("2026-11-05 11:00"), TODAYS)
    world.read(at("2026-11-05 12:00"), [THURSDAY_ROW, *OLD_COPY])
    entry = world.ledger.row(world.ledger.key(SOURCE, THURSDAY_ROW))
    assert entry is not None
    assert entry.start is Start.CHURN
    assert _ours(world).withheld == "churn"
    assert _alpha_lit(world, "2026-11-05 12:01") == {}


def test_an_old_copy_of_the_page_served_after_a_reader_gap_stays_held() -> None:
    world = World(reader=F5)
    world.read(at("2026-11-03 10:00"), TODAYS)
    world.read(at("2026-11-05 12:00"), [THURSDAY_ROW, *OLD_COPY])
    assert _ours(world).withheld == "unknown_start"
    assert _alpha_lit(world, "2026-11-05 12:01") == {}


def test_a_new_list_on_a_truly_cold_first_read_still_lights() -> None:
    # the one class accepted: a source the ledger never read before
    world = World(reader=F5)
    world.read(at("2026-11-05 12:00"), [THURSDAY_ROW, *OTHERS])
    entry = world.ledger.row(world.ledger.key(SOURCE, THURSDAY_ROW))
    assert entry is not None
    assert (entry.start, entry.earliest) == (Start.COLD, at("2026-11-05 12:00"))
    assert _alpha_lit(world, "2026-11-05 12:01") == {(0, THURSDAY): "CLOSED"}


def test_a_static_notice_first_seen_last_thursday_lights_only_last_thursday() -> None:
    world = World(reader=F5)
    world.read(at("2026-10-29 11:00"), [THURSDAY_ROW, *OTHERS])  # a truly cold first read
    assert _alpha_lit(world, "2026-10-29 11:01") == {(0, "2026-10-29"): "CLOSED"}
    _hours(world, "2026-10-29 17:00", "2026-11-05 12:00", [THURSDAY_ROW, *OTHERS])
    world.read(at("2026-11-05 12:00"), [THURSDAY_ROW, *OTHERS])
    assert _alpha_lit(world, "2026-11-05 12:01") == {}


# --- part of a list re-keyed on a warm read (WD-R4C2-B1, B2) --------------------------------


def _twins(section: str, first: str, second: str) -> list[SeenRow]:
    """Two listings of the Alpha school under one section (a tie when both change), and six
    others that stay put (so re-sectioning the two is no churn)."""
    return [
        row(ALPHA_SCHOOL, first, section=section),
        row(ALPHA_SCHOOL, second, section=section),
        *OTHERS,
    ]


def _alpha_rows(world: World) -> list[Derived]:
    (resolved,) = world.resolve()
    keys = {world.ledger.key(SOURCE, seen) for seen in world.last[SOURCE][:2]}
    return [r.derived for r in resolved.rows if r.row.key in keys]


# words the reader reads with a note that holds them on a warm read too, and plain words
NOTE_WORDS = ("Closed Thursday - all activities cancelled", "Thursday: Closed, no activities")
PLAIN_WORDS = ("Closed Thursday", "Thursday: Closed")


def _re_sectioned_twins(words: tuple[str, str]) -> World:
    """Last week's Thursday rows (up since Wed Oct 28 19:00 Central), moved alone to another
    section on Wed Nov 4 21:00 Central (a warm read, no churn: dated from the last read)."""
    world = World(reader=F5)
    world.read(at("2026-10-28 23:00"), OTHERS)
    _hours(world, "2026-10-29 00:00", "2026-11-05 02:00", _twins("Schools", *words), step=3)
    world.read(at("2026-11-05 02:00"), _twins("Schools", *words))
    world.read(at("2026-11-05 03:00"), _twins("Closings", *words))
    return world


@pytest.mark.parametrize("words", [NOTE_WORDS, PLAIN_WORDS])
def test_a_key_re_sectioned_without_churn_keeps_the_sources_earliest_sighting(
    words: tuple[str, str],
) -> None:
    world = _re_sectioned_twins(words)
    entries = [_alpha_entry(world)]
    second = world.ledger.row(world.ledger.key(SOURCE, world.last[SOURCE][1]))
    assert second is not None
    entries.append(second)
    for entry in entries:
        assert (entry.start, entry.lo, entry.pred) == (Start.WARM, at("2026-11-05 02:00"), None)
        assert entry.earliest == at("2026-10-28 23:00")


@pytest.mark.parametrize("words", [NOTE_WORDS, PLAIN_WORDS])
def test_tied_successors_of_a_list_part_re_sectioned_on_a_warm_read_stay_held(
    words: tuple[str, str],
) -> None:
    world = _re_sectioned_twins(words)
    world.resolve()
    _hours(world, "2026-11-05 04:00", "2026-11-05 12:00", _twins("Closings", *words), step=1)
    world.resolve()
    # Thu 06:00 Central: both re-worded at once, a tie: successors with no predecessor
    world.read(
        at("2026-11-05 12:00"), _twins("Closings", "School closed Thursday", "No school Thursday")
    )
    entry = _alpha_entry(world)
    assert (entry.start, entry.lo, entry.pred) == (Start.COLD, None, None)
    assert entry.earliest is not None
    assert entry.earliest <= at("2026-10-29 00:00")
    derived = _alpha_rows(world)
    assert [d.dated_by for d in derived] == ["", ""]
    assert [d.withheld for d in derived] == ["unknown_start", "unknown_start"]
    if words == NOTE_WORDS:  # the reader never lights these words: nothing may light them
        assert _alpha_lit(world, "2026-11-05 12:01") == {}


def test_a_list_part_re_sectioned_on_a_warm_read_and_back_on_a_later_day_stays_held() -> None:
    world = World(reader=F5)
    alpha = [row(ALPHA_SCHOOL, "Closed Thursday", section="Closings")]
    world.read(at("2026-10-28 23:00"), OTHERS)
    _hours(
        world, "2026-10-29 00:00", "2026-11-05 03:00", [*_listing("Schools")[:1], *OTHERS], step=3
    )
    world.read(at("2026-11-05 02:00"), [*_listing("Schools")[:1], *OTHERS])
    world.read(at("2026-11-05 03:00"), [*alpha, *OTHERS])  # Wed 21:00 Central, re-sectioned
    world.resolve()
    _hours(world, "2026-11-05 04:00", "2026-11-05 12:00", OTHERS, step=1)  # off 8 hours
    world.resolve()
    world.read(at("2026-11-05 12:00"), [*alpha, *OTHERS])  # back Thu 06:00 Central
    entry = _alpha_entry(world)
    assert (entry.start, entry.lo) == (Start.COLD, None)
    assert entry.earliest is not None
    assert entry.earliest <= at("2026-10-29 00:00")
    derived = _ours_alpha(world)
    assert (derived.withheld, derived.dated_by) == ("unknown_start", "")
    assert _alpha_lit(world, "2026-11-05 12:01") == {}


def test_a_new_row_on_a_warm_read_lights_by_its_window_and_its_returns_stay_held() -> None:
    # a genuinely new row read warm lights by its window; its earliest sighting is the
    # source's oldest, so a return on a later day is not self-dated (the cost of the bound)
    world = World(reader=F5)
    _hours(world, "2026-11-04 12:00", "2026-11-05 11:00", OTHERS, step=1)
    world.read(at("2026-11-05 11:00"), [THURSDAY_ROW, *OTHERS])
    entry = world.ledger.row(world.ledger.key(SOURCE, THURSDAY_ROW))
    assert entry is not None
    assert (entry.start, entry.lo, entry.earliest) == (
        Start.WARM,
        at("2026-11-05 10:00"),
        at("2026-11-04 12:00"),
    )
    assert _alpha_lit(world, "2026-11-05 11:01") == {(0, THURSDAY): "CLOSED"}


def test_tied_successors_on_a_new_ledger_stay_held() -> None:
    # a new (or lost) ledger first reads the list Thu 04:00 Central, last week's rows on it
    world = Unwatched(reader=F5)
    for when in ("2026-11-05 10:00", "2026-11-05 11:00"):
        world.read(at(when), _twins("", *PLAIN_WORDS))
        assert _alpha_lit(world, f"{when[:-2]}01") == {}
    world.read(at("2026-11-05 12:00"), _twins("", "School closed Thursday", "No school Thursday"))
    entry = _alpha_entry(world)
    assert (entry.start, entry.pred, entry.earliest) == (Start.COLD, None, at("2026-11-05 10:00"))
    assert entry.earliest != entry.hi
    (resolved,) = world.resolve()
    assert "weekday_dated" not in resolved.counts
    assert _alpha_lit(world, "2026-11-05 12:01") == {}


@pytest.mark.parametrize(
    ("watching", "shown"), [("2026-10-29 06:00", False), ("2026-10-28 12:00", True)]
)
def test_the_new_ledger_hold_asks_of_the_rows_earliest_sighting(watching: str, shown: bool) -> None:
    # a row first seen Wed 19:00 Central that flaps and is back Thu 06:00: its earliest
    # sighting (Wed) must be a week into the ledger's watch, not only its own (Thu)
    world = Unwatched(reader=F5)
    world.ledger.observe("seed-synthetic", Outcome.OK, at(watching), [row("SYNTHETIC Seed")])
    world.read(at("2026-11-05 00:00"), [THURSDAY_ROW, *OTHERS])
    world.read(at("2026-11-05 03:00"), OTHERS)
    world.read(at("2026-11-05 09:00"), OTHERS)
    world.read(at("2026-11-05 12:00"), [THURSDAY_ROW, *OTHERS])
    entry = world.ledger.row(world.ledger.key(SOURCE, THURSDAY_ROW))
    assert entry is not None
    assert (entry.hi, entry.earliest) == (at("2026-11-05 12:00"), at("2026-11-05 00:00"))
    expected = {(0, THURSDAY): "CLOSED"} if shown else {}
    assert _alpha_lit(world, "2026-11-05 12:01") == expected


# --- successors (WD-R4C1-B1, B2) -------------------------------------------------------------


def _with_alpha(text: str) -> list[SeenRow]:
    return [row(ALPHA_SCHOOL, text), *OTHERS]


@pytest.mark.parametrize("last", ["2026-10-28 12:00", "2026-11-03 12:00", "2026-11-03 23:59"])
@pytest.mark.parametrize("before", ["2 hour delay", "Closed until further notice", "Open"])
def test_a_successor_first_seen_after_a_reader_gap_stays_held(last: str, before: str) -> None:
    # the listing read hourly, then the reader down until Thu 06:00 Central: its new words went
    # up some time in the gap, perhaps last Thursday
    world = World(reader=F5)
    _hours(world, "2026-10-26 00:00", last, _with_alpha(before), step=1)
    world.read(at(last), _with_alpha(before))
    world.resolve()
    world.read(at("2026-11-05 12:00"), _with_alpha("Closed Thursday"))
    entry = _alpha_entry(world)
    assert (entry.start, entry.lo) == (Start.COLD, None)
    assert entry.pred is not None
    assert entry.earliest is not None
    assert entry.earliest <= at("2026-10-26 00:00")
    (resolved,) = world.resolve()
    assert "weekday_dated" not in resolved.counts
    assert "self_dated:unknown_start" not in resolved.counts
    assert _alpha_lit(world, "2026-11-05 12:01") == {}


def test_a_successor_after_a_gap_on_a_source_whose_other_rows_are_new_stays_held() -> None:
    # every row first seen the day before the gap: the predecessor's own sighting bounds it
    world = World(reader=F5)
    _hours(world, "2026-10-28 12:00", "2026-10-29 06:00", _with_alpha("2 hour delay"), step=1)
    world.resolve()
    world.read(at("2026-11-05 12:00"), _with_alpha("Closed Thursday"))
    assert _alpha_entry(world).earliest == at("2026-10-28 12:00")
    assert _ours_alpha(world).withheld == "unknown_start"
    assert _alpha_lit(world, "2026-11-05 12:01") == {}


def _ours_alpha(world: World) -> Derived:
    (resolved,) = world.resolve()
    key = world.ledger.key(SOURCE, world.last[SOURCE][0])
    (ours,) = [r for r in resolved.rows if r.row.key == key]
    return ours.derived


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Closed Thursday", "School closed Thursday"),
        ("Closed Thursday", "Closed Thursday due to weather"),
        ("CLOSED THURSDAY", "Closed Thursday"),
        ("Closed Thursday", "Closed Thursday."),
    ],
)
def test_a_cold_held_row_re_worded_on_the_next_warm_read_stays_held(
    first: str, second: str
) -> None:
    # read without the row until Oct 28, then down a week: the row first seen cold on Thu
    # Nov 5 is held (it may be last Thursday's), and re-worded two hours later it still is
    world = World(reader=F5)
    _hours(world, "2026-10-26 00:00", "2026-10-28 12:00", OTHERS, step=1)
    world.resolve()
    world.read(at("2026-11-05 10:00"), _with_alpha(first))
    assert _ours_alpha(world).withheld == "unknown_start"
    assert _alpha_lit(world, "2026-11-05 10:01") == {}
    world.read(at("2026-11-05 12:00"), _with_alpha(second))
    entry = _alpha_entry(world)
    assert entry.earliest is not None
    assert entry.earliest <= at("2026-10-26 00:00")
    (resolved,) = world.resolve()
    assert "weekday_dated" not in resolved.counts
    assert _alpha_lit(world, "2026-11-05 12:01") == {}


def test_a_self_dated_row_re_worded_on_the_next_warm_read_still_lights() -> None:
    # a truly cold first read lights it; re-worded two hours later it says the same either way
    world = World(reader=F5)
    world.read(at("2026-11-05 10:00"), _with_alpha("Closed Thursday"))
    assert _ours_alpha(world).dated_by == "weekday"
    world.read(at("2026-11-05 12:00"), _with_alpha("School closed Thursday"))
    assert _alpha_entry(world).earliest == at("2026-11-05 10:00")
    assert _alpha_lit(world, "2026-11-05 12:01") == {(0, THURSDAY): "CLOSED"}


def test_a_successor_or_return_of_a_row_from_before_the_column_has_no_earliest() -> None:
    # the words a row written before the column carries are of unknown age, and so are those
    # of a key back after 3 hours or a successor that may re-render them
    world = World(reader=F5)
    _hours(world, "2026-11-04 12:00", "2026-11-05 06:00", _with_alpha("Closed"), step=1)
    world.ledger._db.execute("UPDATE rows SET earliest = NULL WHERE source_id = ?", (SOURCE,))
    world.read(at("2026-11-05 12:00"), _with_alpha("Closed Thursday"))  # warm successor
    assert _alpha_entry(world).earliest is None
    world.read(at("2026-11-05 13:00"), OTHERS)
    world.read(at("2026-11-05 17:00"), _with_alpha("Closed Thursday"))  # back after 4 hours
    assert _alpha_entry(world).earliest is None
    cold = World(reader=F5)
    _hours(cold, "2026-11-01 12:00", "2026-11-02 12:00", OTHERS, step=1)
    cold.ledger._db.execute("UPDATE rows SET earliest = NULL WHERE source_id = ?", (SOURCE,))
    cold.read(at("2026-11-05 12:00"), _with_alpha("Closed Thursday"))  # new after a gap
    assert _alpha_entry(cold).earliest is None
    assert _ours_alpha(cold).withheld == "unknown_start"


def test_the_resolver_bounds_a_successor_by_its_predecessor() -> None:
    hi = at("2026-11-05 12:00")
    entry = LedgerRow(
        key=b"k",
        source_id=SOURCE,
        hi=hi,
        lo=None,
        start=Start.COLD,
        row_stamp=None,
        last_seen=hi,
        absent_since=None,
        gone=False,
        ident=b"i",
        pred=b"p",
        lapsed=False,
        earliest=hi,
    )
    pred = entry._replace(key=b"p", hi=at("2026-11-05 10:00"), earliest=at("2026-10-26 00:00"))
    assert _successor_earliest(entry, pred) == at("2026-10-26 00:00")
    assert _successor_earliest(entry, pred._replace(earliest=hi)) == at("2026-11-05 10:00")
    assert _successor_earliest(entry, pred._replace(earliest=None)) is None
    assert _successor_earliest(entry._replace(earliest=None), pred) is None
    assert _successor_earliest(entry, None) == hi


# --- stamps in the words (WD-R3-B2) ----------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "dates"),
    [
        ("Closed Thursday. Posted 10/29", (date(2026, 10, 29),)),
        ("Closed Thursday. Updated Oct 29", (date(2026, 10, 29),)),
        ("Closed Thursday (updated Oct. 29)", (date(2026, 10, 29),)),
        ("Closed Thursday. Updated 2026-10-29", (date(2026, 10, 29),)),
        ("Closed Thursday. Posted Wednesday, October 28", (date(2026, 10, 28),)),
        ("Closed Thursday. Updated Nov. 4", (date(2026, 11, 4),)),
        ("Closed Thursday. Updated Wednesday 9:00 PM", (date(2026, 11, 4),)),
        ("Closed Thursday. Updated 10/29 5:30 AM", (date(2026, 10, 29),)),
        ("Updated at 5:30 AM CST on 10/29", (date(2026, 10, 29),)),
        ("updated 2026-10-29T05:30:00", (date(2026, 10, 29),)),
        ("Last updated: Nov 4, 2026 at 6:00 a.m.", (date(2026, 11, 4),)),
        ("Updated Oct 29 '25", (date(2025, 10, 29),)),
        ("Posted 11/6", (date(2025, 11, 6),)),  # no year: the latest such date
        ("Posted 11/6/2026", (date(2026, 11, 6),)),
        ("Posted yesterday", (None,)),  # an age of about a day, at no time (WD-R5)
        ("Posted yesterday at 9 PM", (date(2026, 11, 4),)),  # the night before (WD-R5C1-S6)
        ("Posted 9 PM yesterday", (date(2026, 11, 4),)),
        ("Updated yesterday evening", (date(2026, 11, 4),)),
        ("Updated this morning", (date(2026, 11, 5),)),
        ("Posted Mon Tue", (None,)),  # two weekdays: which is unknown
        ("Posted 10/29 10/30", (None,)),
        ("as of 6 AM Thursday", (date(2026, 11, 5),)),
        ("Updated last week", (None,)),
        ("Posted 3 days ago", (None,)),
        ("Posted Feb. 30", (None,)),
        ("Posted Wednesday, October 29", (None,)),  # the 29th is a Thursday
        ("Updated Oct 29 at 5", (None,)),
        ("Updated 5:30 AM", ()),
        ("Posted by the district. Closed Thursday", ()),
        ("Closed Thursday", ()),
        ("Posted 10/29; updated Nov. 4", (date(2026, 10, 29), date(2026, 11, 4))),
        # words between the stamp word and its date, and a stamp across lines (WD-R4C1-B3)
        ("Posted by the district on 10/29", (date(2026, 10, 29),)),
        ("Updated per district, 10/29", (date(2026, 10, 29),)),
        ("Updated by district office on Oct 29", (date(2026, 10, 29),)),
        ("Posted by Superintendent Oct. 29", (date(2026, 10, 29),)),
        ("Closed Thursday. Updated\nOct 29", (date(2026, 10, 29),)),
        ("Closed Thursday. Posted\nby the district\n10/29", (date(2026, 10, 29),)),
        ("Updated by the district office at 5:30 AM", ()),
        ("Posted by the district", ()),
        ("Posted by District 5", (None,)),  # a number it cannot read as a day
        ("Updated by staff, 29 October", (None,)),
        ("Updated by the district Nov. 4 at 6 a.m. per the superintendent", (date(2026, 11, 4),)),
        ("Updated by admin last week", (None,)),
        ("Posted 5:30 AM Oct. 29", (date(2026, 10, 29),)),  # a month after a time is no zone
        ("Posted 5:30 AM (CST) Oct 29", (date(2026, 10, 29),)),
        ("Updated 6:00 AM CDT", ()),
        ("Updated 6:00 AM AKST, 6:00 AM HST", ()),
        # status words the stamp runs on into that carry no day
        ("Updated: schools on a 2 hour delay", ()),
        ("Posted Nov. 4 - classes start two hours later", (date(2026, 11, 4),)),
        ("Updated: delayed 2 hours, buses 2-hour late", ()),
        ("Posted: snow day, e-learning day", ()),
        ("Updated 2 hours ago", ()),  # an age the resolver bounds (WD-R5)
        ("Updated two hours ago", ()),
        ("Posted: a snow day 10/29", (date(2026, 10, 29),)),
        ("Updated: 2 hour delay on 10/29", (date(2026, 10, 29),)),
        ("Updated: snow day tomorrow", (None,)),
        # read over what the weekday rule leaves out as the stamp, to its first "." (or a
        # date or time that runs on past one), not into the status words after it
        ("As of Nov. 4, 6:00 PM: schools closed on Thursday, Nov. 5", (date(2026, 11, 4),)),
        ("Posted 6 a.m. Oct. 29", ()),  # its date is left in the status words
        ("Posted by Supt. Lee on Oct. 29", ()),  # the date is left in the status words
        (
            "Updated Nov. 4 by admin, originally posted Oct 29",
            (date(2026, 11, 4), date(2026, 10, 29)),
        ),
    ],
)
def test_stamp_dates(text: str, dates: tuple[date | None, ...]) -> None:
    assert stamp_dates(text, NOV5) == dates


@pytest.mark.parametrize(
    "text",
    [
        "Closed Thursday. Posted 10/29",
        "Closed Thursday. Updated Oct 29",
        "Closed Thursday (updated Oct. 29)",
        "Closed Thursday. Updated 2026-10-29",
        "Closed Thursday. Posted Wednesday, October 28",
        "Closed Thursday. Last updated: 10/29/2026",
        "Closed Thursday as of 10/29",
        "Closed Thursday. Updated last week",
        "Closed Thursday. Posted 3 days ago",
        "Closed Thursday. Posted Feb. 30",
        "Closed Thursday. Posted 11/6/2026",
        "Closed Nov. 5. Posted Oct. 29",
        "Closed Thursday. Updated by district office on Oct 29",
        "Closed Thursday. Posted by Superintendent Oct. 29",
        "Closed Thursday (updated per district, 10/29)",
        "Closed Thursday. Posted by the district 10/29",
        "Closed Thursday. Posted by the district on 10/29",
        "Closed Thursday. Updated\nOct 29",
        "Closed Nov. 5. Updated by the district\non Oct. 29",
        "Closed Thursday. Updated by District 5",
        "Closed Thursday. Posted by Supt. Lee on Oct. 29",
        "Closed Thursday. Posted by Dr. Jones 3 days ago",
        "Closed Thursday (7 days ago)",
    ],
)
def test_a_stamp_in_the_words_from_an_earlier_week_or_unread_keeps_the_hold(text: str) -> None:
    world = _cold("2026-11-05 12:00", text)  # Thu 06:00 Central, a truly cold read
    assert reasons(world.resolve()) == ["unknown_start"]
    assert lit(world.publish(at("2026-11-05 12:01"))) == {}


@pytest.mark.parametrize(
    ("text", "dated_by"),
    [
        ("Closed Thursday. Updated Nov. 4", "weekday"),
        ("Closed Thursday. Updated Wednesday 9:00 PM", "weekday"),
        ("Closed Thursday. Updated Nov. 4 9:00 PM", "weekday"),
        ("Closed Nov. 5. Updated Nov. 4 9:00 PM", "date"),
        ("As of Nov. 4, 6:00 PM: schools closed Thursday, Nov. 5", "date"),
    ],
)
def test_a_stamp_in_the_words_from_this_week_still_lights(text: str, dated_by: str) -> None:
    world = _cold("2026-11-05 12:00", text)
    (resolved,) = world.resolve()
    (result,) = resolved.rows
    assert result.derived.dated_by == dated_by
    assert lit(world.publish(at("2026-11-05 12:01"))) == {(0, THURSDAY): "CLOSED"}


@settings(max_examples=300, deadline=None)
@given(
    st.sampled_from(["Posted", "Updated", "Last updated", "as of", "Edited", "modified"]),
    st.lists(
        st.sampled_from(
            ["by", "the", "district", "office", "per", "to", "for", "website", "Superintendent",
             "staff", "admin", "on", "at", "\n", ",", "-", "(", ":", "5:30 AM", "6 a.m.",
             "a 2 hour delay", "snow day", "two hours later", "5:30 AM CST"]
        ),
        max_size=6,
    ),
    st.sampled_from(
        ["10/29", "Oct 29", "Oct. 29", "October 29", "2026-10-29", "Thursday, October 29",
         "10/29/2026", "Oct 29, 2026", "last week", "3 days ago", "1w ago", "29 October",
         "10-29", "10.29", "Oct 28 at 9 PM", "Wednesday, October 28"]
    ),
)  # fmt: skip
def test_a_dated_stamp_from_an_earlier_week_bounds_the_row_wherever_its_date_stands(
    word: str, between: list[str], stamp: str
) -> None:
    # whatever stands between the stamp word and its date, the row is held: the stamp's day
    # is read (or is unreadable), or the date is left in the status words, where it keeps the
    # row from being dated by its weekday (WD-R4C1-B3)
    text = f"Closed Thursday. {word} {' '.join(between)} {stamp}"
    found = stamp_dates(text, NOV5)
    assert all(day is None or day <= date(2026, 10, 29) for day in found)
    assert found or not named_weekdays(text)
    assert not names_date(text, NOV5)
    hi = at("2026-11-05 12:00")
    entry = LedgerRow(
        key=b"k",
        source_id=SOURCE,
        hi=hi,
        lo=None,
        start=Start.COLD,
        row_stamp=None,
        last_seen=hi,
        absent_since=None,
        gone=False,
        ident=b"i",
        pred=None,
        lapsed=False,
        earliest=hi,
    )
    assert not named_weekdays(text) or not _posted_before(
        row(ALPHA_SCHOOL, text), entry, ["America/Chicago"], NOV5
    )


@settings(max_examples=400, deadline=None)
@given(
    st.one_of(
        st.text(max_size=40),
        st.from_regex(r"\AClosed Thursday\. (Posted|Updated|as of) [0-9A-Za-z/:,.' -]{0,30}\Z"),
    )
)
def test_stamps_in_the_words_never_raise(text: str) -> None:
    stamp_dates(text, NOV5)
    stamp_dates(text, date(2026, 1, 1))
    seen = row(ALPHA_SCHOOL, text)
    hi = at("2026-11-05 12:00")
    entry = LedgerRow(
        key=b"k",
        source_id=SOURCE,
        hi=hi,
        lo=None,
        start=Start.COLD,
        row_stamp=None,
        last_seen=hi,
        absent_since=None,
        gone=False,
        ident=b"i",
        pred=None,
        lapsed=False,
        earliest=hi,
    )
    _posted_before(seen, entry, ["America/Chicago", "Pacific/Honolulu"], NOV5)


# --- weekdays inside proper names (WD-R3-B3) -------------------------------------------------

PROPER_NAMES = [
    ("2026-11-06 12:00", "Closed. Friday Harbor campus only"),
    ("2026-11-06 12:00", "Friday Harbor Elementary closed"),
    ("2026-11-06 12:00", "Closed: Friday Harbor buses cancelled"),
    ("2026-11-06 12:00", "Closed - Friday Harbor"),
    ("2026-11-06 12:00", "Closed (Friday Harbor)"),
    ("2026-11-06 12:00", "Friday Harbor schools closed"),
    ("2026-11-06 12:00", "Closed for Friday Harbor district"),
    ("2026-11-06 12:00", "Closed Friday Harbor SD"),
    ("2026-11-06 12:00", "closed friday harbor"),
    ("2026-11-06 12:00", "CLOSED FRIDAY HARBOR SD"),
    ("2026-11-09 12:00", "Monday Creek campus closed"),
    ("2026-11-09 12:00", "Closed, includes Monday Creek Elementary"),
    ("2026-11-08 14:00", "Sunday River routes closed"),
    ("2026-11-06 12:00", "St. Friday School closed"),
    ("2026-11-06 12:00", "Friday School closed"),
    ("2026-11-06 12:00", "Closed at Friday School"),
    ("2026-11-06 12:00", "FRIDAY SCHOOL CLOSED"),
]


@pytest.mark.parametrize(("when", "text"), PROPER_NAMES)
def test_a_weekday_inside_a_proper_name_never_dates_the_row(when: str, text: str) -> None:
    assert named_weekdays(text, ALPHA_SCHOOL) == frozenset()
    world = _cold(when, text)
    assert reasons(world.resolve()) != [None]
    assert lit(world.publish(at(when) + timedelta(minutes=1))) == {}


@pytest.mark.parametrize(
    ("text", "named"),
    [
        ("Closed Friday", {4}),
        ("CLOSED FRIDAY", {4}),
        ("closed friday", {4}),
        ("Closed Friday due to weather", {4}),
        ("CLOSED FRIDAY DUE TO SNOW", {4}),
        ("closed friday, harbor road flooded", {4}),
        ("Closed Friday harbor", {4}),  # mixed case: only a capitalised word makes a name
        ("Closed Thursday No Activities", {3}),
        ("Closed Thursday / No Activities", {3}),
        ("No School Thursday And Friday", {3, 4}),
        ("Closed Thursday Morning", {3}),
        ("closed thursday staff report", {3}),
        ("Closed Thursday Distance Learning Day", {3}),
        ("Closed Thursday Both Campuses", {3}),
        ("Thursday AMI Day", {3}),
        ("closed thursday harbor", set()),
        ("Closed Thursday Harbor", set()),
        ("Lake Monday School closed", set()),
        # a school word after a weekday (WD-R4C2-S2)
        ("Friday School closed", set()),
        ("Closed at Friday School", set()),
        ("Girl Friday Schools closed", set()),
        ("FRIDAY SCHOOL CLOSED", set()),
        ("friday academy closed", set()),
        ("Monday Learning Center closed", set()),
        ("No School Friday", {4}),
        ("Closed Friday, school activities cancelled", {4}),
        ("Closed Friday school and activities", {4}),  # mixed case, lower: no name
        # another day than the one closed (WD-R4C2-S1)
        ("Closed Thursday instead of Friday", set()),
        ("Closed Thursday rather than Friday", set()),
        ("Closed Thursday in place of Friday", set()),
        ("Closed Thursday in lieu of Friday", set()),
        ("Closed Thursday, not Friday", set()),
        ("Not closed Thursday", set()),
        ("Closed every day except Thursday", set()),
        ("Make-up day moved to Friday", set()),
        ("Thursday game postponed to Friday", set()),
        # a date in a form no rule reads, or a word that puts it earlier (WD-R4C2-S2)
        ("Closed Thursday 29.10", set()),
        ("Closed Thursday 29.10.2026", set()),
        ("Closed Thursday (29)", set()),
        ("Closed Thursday #29", set()),
        ("Closed Thursday 29", set()),
        ("Closed Thursday, the 29", set()),
        ("Closed Thursday no. 29", set()),
        ("Closed on Thursday previously", set()),
        ("Closed Thursday earlier", set()),
        ("Closing Thursday was cancelled", set()),
        ("Closed Thursday, 2 hour delay Friday", {3, 4}),
        ("Closed Thursday 2.5 hour delay", {3}),
        ("Closed Thursday 10 am", {3}),
        ("Closed Thursday 9:30", {3}),
        ("Closed Thursday, 2-hour delay Friday", {3, 4}),
    ],
)
def test_named_weekdays_and_proper_names(text: str, named: set[int]) -> None:
    assert named_weekdays(text) == frozenset(named)


def test_weekdays_in_names() -> None:
    assert weekdays_in(["SYNTHETIC Friday Harbor SD", "SYNTHETIC Alpha"]) == frozenset({4})
    assert weekdays_in(["SYNTHETIC Fridays"]) == frozenset()
    assert weekdays_in([]) == frozenset()


HARBOR_ROW = "SYNTHETIC Harbor Elementary"
HARBOR = "200000100099"


def _harbor_world(school_name: str, best_name: str = "SYNTHETIC") -> World:
    matcher = default_matcher()
    matcher.table[HARBOR_ROW] = replace(accepted(direct=(HARBOR,)), best_name=best_name)
    world = World(
        reader=F5,
        matcher=matcher,
        dir=directory([_school(HARBOR, 11, name=school_name)]),
    )
    world.read(at("2026-11-06 12:00"), [row(HARBOR_ROW, "Closed Friday")])  # Fri 06:00
    return world


@pytest.mark.parametrize(
    ("school_name", "best_name", "shown"),
    [
        ("SYNTHETIC Harbor Elementary", "SYNTHETIC Harbor Elementary", True),
        ("SYNTHETIC Friday Harbor Elementary", "SYNTHETIC Harbor Elementary", False),
        ("SYNTHETIC Harbor Elementary", "SYNTHETIC Friday Harbor SD", False),
    ],
)
def test_a_weekday_in_a_directory_name_of_the_row_is_never_read(
    school_name: str, best_name: str, shown: bool
) -> None:
    world = _harbor_world(school_name, best_name)
    assert reasons(world.resolve()) == ([None] if shown else ["unknown_start"])
    expected = {(11, FRIDAY): "CLOSED"} if shown else {}
    assert lit(world.publish(at("2026-11-06 12:01"))) == expected


# --- the trial row's shape -------------------------------------------------------------------


def test_the_trial_rows_shape_names_its_weekday_but_its_note_keeps_it_held() -> None:
    # "No Activities" gives the reader's activities_cancelled note, a NOTE hold of its own
    # (reported, not changed here): the weekday rule dates it, the note gate holds it
    text = "Closed Thursday / No Activities"
    assert named_weekdays(text, ALPHA_SCHOOL) == frozenset({3})
    world = _cold("2026-11-05 12:00", text)
    assert reasons(world.resolve()) == ["unknown_start"]
    assert lit(world.publish(at("2026-11-05 12:01"))) == {}


# --- a new ledger (WD-R3 self-audit) ---------------------------------------------------------


@pytest.mark.parametrize(
    ("watching", "shown"),
    [(None, False), ("2026-11-05 11:00", False), ("2026-10-30 12:00", False), (WATCHING, True)],
)
def test_a_ledger_that_has_watched_less_than_a_week_self_dates_no_first_read(
    watching: str | None, shown: bool
) -> None:
    # a new ledger (a lost file, a new schema version) reads every source as never read
    world = Unwatched(reader=F5)
    if watching is not None:
        world.ledger.observe("seed-synthetic", Outcome.OK, at(watching), [row("SYNTHETIC Seed")])
    world.read(at("2026-11-05 12:00"), [THURSDAY_ROW])
    (resolved,) = world.resolve()
    assert ("weekday_dated" in resolved.counts) is shown
    expected = {(0, THURSDAY): "CLOSED"} if shown else {}
    assert lit(world.publish(at("2026-11-05 12:01"))) == expected


def test_watching_since_is_the_earliest_good_read_kept() -> None:
    ledger = Ledger(":memory:")
    assert ledger.watching_since() is None
    ledger.observe("a-synthetic", Outcome.OK, at("2026-11-02 12:00"), [THURSDAY_ROW])
    ledger.observe("b-synthetic", Outcome.OK, at("2026-11-03 12:00"), [THURSDAY_ROW])
    assert ledger.watching_since() == at("2026-11-02 12:00")
    ledger.observe("c-synthetic", Outcome.OK, at("2026-11-04 12:00"), [THURSDAY_ROW])
    assert ledger.watching_since() == at("2026-11-02 12:00")


# --- a page's own stamp (WD-R3 self-audit) ---------------------------------------------------


@pytest.mark.parametrize(
    ("scope", "stamp", "shown"),
    [
        ("page", "2026-10-29 06:00", False),
        ("page", "10/29/2026", False),
        (None, "2026-10-29 06:00", False),  # unmarked
        ("page", "2026-10-30 06:00", True),
        ("page", "2026-11-05 05:30", True),
        ("page", "not a date", True),  # no day read: it bounds nothing
        ("page", "2026-02-30 12:00", True),
    ],
)
def test_a_page_stamp_from_a_week_before_keeps_the_hold(
    scope: str | None, stamp: str, shown: bool
) -> None:
    extra: dict[str, JsonScalar] = {} if scope is None else {"updated_scope": scope}
    raw = RawRow(
        source_id=SOURCE,
        fetched_at=at("2026-11-05 12:00"),
        raw_name=ALPHA_SCHOOL,
        raw_status="Closed Thursday",
        raw_updated_text=stamp,
        raw_extra=extra,
    )
    seen = seen_row(raw, variant="", platform="gray", zone="America/Chicago")
    assert (seen.row_stamp, seen.row_date, seen.page_date) == (None, "", stamp)
    world = World(reader=F5)
    world.read(at("2026-11-05 12:00"), [seen])
    expected = {(0, THURSDAY): "CLOSED"} if shown else {}
    assert lit(world.publish(at("2026-11-05 12:01"))) == expected


def test_a_page_stamp_never_keys_or_dates_a_row() -> None:
    ledger = Ledger(":memory:")
    one = row(ALPHA_SCHOOL, "Closed Thursday")
    assert ledger.key(SOURCE, one) == ledger.key(SOURCE, replace(one, page_date="2026-11-05"))


# --- words that name another day or an earlier one (WD-R4C2-S1, S2) -------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Closed Thursday instead of Friday",
        "Closed Thursday rather than Friday",
        "Closed Thursday, not Friday",
        "Closed Thursday 29.10",
        "Closed Thursday (29)",
        "Closed Thursday #29",
        "Closed on Thursday previously",
    ],
)
def test_a_cold_row_naming_another_day_or_an_earlier_one_stays_held(text: str) -> None:
    world = _cold("2026-11-05 12:00", text)
    assert reasons(world.resolve()) != [None]
    assert lit(world.publish(at("2026-11-05 12:01"))) == {}


# --- posting ages in the words (WD-R5-1) -----------------------------------------------------


@pytest.mark.parametrize(
    ("text", "ages"),
    [
        ("Closed Thursday (1w)", (timedelta(weeks=1),)),
        ("Closed Thursday • 6d", (timedelta(days=6),)),
        ("Closed Thursday 2d", (timedelta(days=2),)),
        ("Closed Thursday 1 wk", (timedelta(weeks=1),)),
        ("Closed Thursday. 3 days ago", (timedelta(days=3),)),
        ("Closed Thursday • 2h", (timedelta(hours=2),)),
        ("Closed Thursday • 5m", (timedelta(minutes=5),)),
        ("Closed Thursday (2h ago)", (timedelta(hours=2),)),
        ("Closed Thursday. Updated an hour ago", (timedelta(hours=1),)),
        ("Closed Thursday. Updated two hours ago", (timedelta(hours=2),)),
        ("Closed Thursday. Updated just now", (timedelta(0),)),
        ("Closed Thursday. Posted moments ago", (timedelta(0),)),
        ("Closed Thursday 1mo", (timedelta(days=28),)),
        ("Closed Thursday 1y", (timedelta(days=365),)),
        ("Closed Thursday, a few days ago", (None,)),
        ("Closed Thursday, several hours ago", (None,)),
        # a delay's length is no age
        ("Thursday: 2 hr delay", ()),
        ("Thursday: 2 hours late", ()),
        ("Thursday 90 min delay", ()),
        ("Delayed 2 hours Thursday", ()),
        ("2-hour delay Thursday", ()),
        ("Thursday 2hr delay", ()),
        ("Thursday: dismissed 2 hours early", ()),
        ("Delayed Thursday 2 Hours.", ()),  # a delay word anywhere before, in its clause
        ("Opening Late Thursday 2 Hours", ()),
        # with a period after its unit (WD-R5C1-B1)
        ("Thursday: Open 2 Hrs. Late", ()),
        ("Thursday: 2 hr. delay", ()),
        ("Thursday: 90 Min. Delay", ()),
        ("Thursday: 2 hrs. late", ()),
        ("Thursday: 120 minute delay", ()),
        # a length too long for a delay, or in another clause, is an age (WD-R5C1-S1)
        ("Delayed Thursday • 168h", (timedelta(hours=168),)),
        ("Delayed Thursday • 30h", (timedelta(hours=30),)),
        ("Delayed Thursday 30h", (timedelta(hours=30),)),
        ("Delay Thursday · 13h", (timedelta(hours=13),)),
        ("Thursday 2 hour delay - 7h", (timedelta(hours=7),)),
        ("Thursday: 6 hour delay", (timedelta(hours=6),)),
        ("Thursday: 5 hour delay", ()),
        # a count of four or five digits (self-audit): an age, or a clock time
        ("Closed Thursday 1440m", (timedelta(days=1),)),
        ("Closed Thursday 10080 min ago", (timedelta(weeks=1),)),
        ("Closed Thursday 0530 hrs", ()),
        ("Closed Thursday 1030 h", ()),
        ("Closed Thursday 2400 hrs", ()),
        ("Clases canceladas jueves, 2024 y 2025", ()),  # a year, never an age
        ("Closed Thursday, many hours ago", (None,)),
        ("Closed Thursday, some hrs ago", (None,)),
        ("Closed Thursday", ()),
        ("Closed Thursday 10 am", ()),
        ("Closed Thursday 5:30", ()),
        ("Closed Thursday 29", ()),
    ],
)
def test_post_ages(text: str, ages: tuple[timedelta | None, ...]) -> None:
    assert post_ages(text) == ages


@pytest.mark.parametrize(
    "text",
    [
        "Closed Thursday (1w)",
        "Closed Thursday • 6d",
        "Closed Thursday 2d",
        "Closed Thursday 1d",
        "Closed Thursday 1 wk",
        "Closed Thursday. 3 days ago",
        "Closed Thursday 1mo",
        "Closed Thursday, a few hours ago",
        "Closed Thursday 24 hours",
        "Closed Thursday yesterday",
        "Closed Thursday. Posted yesterday",
        "Closed Thursday. Posted 3d ago",
        "Closed Thursday • 24h",
        "Closed Thursday • 30h",
        "Closed Thursday • 168h",
        "Closed Thursday 1440m",
        # a length of a day or more is never a delay's (WD-R5C1-S1)
        "Delayed Thursday • 168h",
        "Delayed Thursday • 30h",
        "Delayed Thursday 168 hours",
        "Thursday 2 hour delay - 2d",
        "Closed Nov. 5 (1w)",
        "Closed Nov. 5 • 6d",
        "Closed Nov. 5. Posted 3 days ago",
    ],
)
def test_a_posting_age_of_a_day_or_more_keeps_the_hold(
    text: str,
) -> None:
    world = _cold("2026-11-05 12:00", text)  # Thu 06:00 Central, a truly cold read
    assert reasons(world.resolve()) == ["unknown_start"]
    assert lit(world.publish(at("2026-11-05 12:01"))) == {}


@pytest.mark.parametrize(
    ("when", "text", "day", "status"),
    [
        ("2026-11-05 12:00", "Closed Thursday • 2h", THURSDAY, "CLOSED"),
        ("2026-11-05 12:00", "Closed Thursday • 5m", THURSDAY, "CLOSED"),
        ("2026-11-05 12:00", "Closed Thursday (2h ago)", THURSDAY, "CLOSED"),
        ("2026-11-05 12:00", "Closed Thursday. Updated 1 hour ago", THURSDAY, "CLOSED"),
        ("2026-11-05 12:00", "Closed Thursday. Updated just now", THURSDAY, "CLOSED"),
        ("2026-11-05 12:00", "Closed Nov. 5 • 2h", THURSDAY, "CLOSED"),
        ("2026-11-05 07:00", "Closed Thursday • 30m", THURSDAY, "CLOSED"),  # 01:00
        ("2026-11-06 01:00", "Closed Friday • 3h", FRIDAY, "CLOSED"),  # Thu 19:00
        # posted the evening or the night before, as "Posted Wed 9pm" (WD-R5C1-B2, S6)
        ("2026-11-05 12:00", "Closed Thursday • 8h", THURSDAY, "CLOSED"),  # Wed 22:00
        ("2026-11-05 12:00", "Closed Thursday. Updated 7 hours ago", THURSDAY, "CLOSED"),
        ("2026-11-05 12:00", "Closed Thursday • 23h", THURSDAY, "CLOSED"),  # Wed 07:00
        ("2026-11-05 12:00", "Closed Thursday. Posted yesterday at 9 PM", THURSDAY, "CLOSED"),
        ("2026-11-05 12:00", "Closed Thursday. Updated last night", THURSDAY, "CLOSED"),
        # a delay's length is no age
        ("2026-11-05 12:00", "Thursday: 2 hr delay", THURSDAY, "DELAYED"),
        ("2026-11-05 12:00", "Thursday: 2 hours late", THURSDAY, "DELAYED"),
        ("2026-11-05 12:00", "Thursday 90 min delay", THURSDAY, "DELAYED"),
        ("2026-11-05 12:00", "Delayed 2 hours Thursday", THURSDAY, "DELAYED"),
        # with a period after its unit, first read before the length after midnight: B1
        ("2026-11-05 07:00", "Thursday: Open 2 Hrs. Late", THURSDAY, "DELAYED"),  # 01:00
        ("2026-11-05 07:00", "Thursday: 2 hr. delay", THURSDAY, "DELAYED"),
        ("2026-11-05 06:45", "Thursday: 90 Min. Delay", THURSDAY, "DELAYED"),  # 00:45
        ("2026-11-05 07:00", "Thursday: 2 hrs. late", THURSDAY, "DELAYED"),
        ("2026-11-05 12:00", "Thursday: 120 minute delay", THURSDAY, "DELAYED"),
        ("2026-11-05 12:00", "Thursday: 120-min. delay", THURSDAY, "DELAYED"),
    ],
)
def test_an_age_under_a_day_still_lights(when: str, text: str, day: str, status: str) -> None:
    world = _cold(when, text)
    assert reasons(world.resolve()) == [None]
    assert lit(world.publish(at(when) + timedelta(minutes=1))) == {(0, day): status}


def test_an_age_is_bounded_the_same_in_every_zone() -> None:
    # 12:00Z is 06:00 Central and 02:00 in Honolulu: "3h" was the evening before in
    # Honolulu, as "Posted Wed 9pm" would be; "1d" is a day before in both
    hi = at("2026-11-05 12:00")
    entry = LedgerRow(
        key=b"k",
        source_id=SOURCE,
        hi=hi,
        lo=None,
        start=Start.COLD,
        row_stamp=None,
        last_seen=hi,
        absent_since=None,
        gone=False,
        ident=b"i",
        pred=None,
        lapsed=False,
        earliest=hi,
    )
    seen = row(ALPHA_SCHOOL, "Closed Thursday • 3h")
    assert _posted_before(seen, entry, ["America/Chicago"], NOV5)
    assert _posted_before(seen, entry, ["America/Chicago", "Pacific/Honolulu"], NOV5)
    a_day = row(ALPHA_SCHOOL, "Closed Thursday • 1d")
    assert not _posted_before(a_day, entry, ["America/Chicago"], NOV5)
    assert not _posted_before(a_day, entry, ["America/Chicago", "Pacific/Honolulu"], NOV5)


@settings(max_examples=300, deadline=None)
@given(
    st.integers(min_value=1, max_value=999),
    st.sampled_from(["d", " d", "day", " days", "w", " wk", " weeks", "mo", " months", "y"]),
    st.sampled_from(["", " ago"]),
    st.sampled_from(["(", "• ", "- ", "", ". Posted ", ". Updated "]),
    st.integers(min_value=0, max_value=47),
)
def test_an_age_of_a_day_or_more_never_lights(
    count: int, unit: str, ago: str, before: str, hour: int
) -> None:
    text = f"Closed Thursday {before}{count}{unit}{ago}{')' if before == '(' else ''}"
    when = at("2026-11-05 00:00") + timedelta(hours=hour)
    world = _cold(f"{when:%Y-%m-%d %H:%M}", text)
    world.resolve()
    assert lit(world.publish(when + timedelta(minutes=1))) == {}


_TOKENS = [
    *"0123456789 .,:;-/#@$()'\u2019\u2022\u00b7\n",
    *("Thursday", "Thu", "Friday's", "many", "some", "few", "several", "a", "an", "two"),
    *("h", "hr", "hrs", "hrs.", "hours", "m", "min", "Min.", "d", "days", "w", "wk", "mo", "y"),
    *("ago", "delay", "late", "Late", "early", "dismissal", "Open", "Closed", "Bus", "Room"),
    *("at", "Posted", "Updated", "yesterday", "last night", "9 PM", "Nov.", "Issued", "post"),
    *("notice", "closure", "over", "all clear", "1029", "110526", "1029-26", "0530", "1440"),
    *("many hrs", "some hours", "few h", "0530 hrs", "2 Hrs. Late", "1440m", "30h", "29:"),
]


@settings(max_examples=500, deadline=None)
@given(st.lists(st.sampled_from(_TOKENS), max_size=24))
def test_the_word_rules_never_raise(tokens: list[str]) -> None:
    text = " ".join(tokens)
    for day in (NOV5, None):
        named_weekdays(text, "", day)
        named_weekdays(text, "Thu", day)
    names_date(text, NOV5)
    states_a_date(text)
    stamp_dates(text, NOV5)
    post_ages(text)


@settings(max_examples=300, deadline=None)
@given(st.text(max_size=40), st.integers(min_value=0, max_value=47))
def test_ages_never_raise(text: str, hour: int) -> None:
    post_ages(text)
    hi = at("2026-11-05 00:00") + timedelta(hours=hour)
    entry = LedgerRow(
        key=b"k",
        source_id=SOURCE,
        hi=hi,
        lo=None,
        start=Start.COLD,
        row_stamp=None,
        last_seen=hi,
        absent_since=None,
        gone=False,
        ident=b"i",
        pred=None,
        lapsed=False,
        earliest=hi,
    )
    _posted_before(row(ALPHA_SCHOOL, f"Closed Thursday {text}"), entry, ["Pacific/Honolulu"], NOV5)


# --- month and day numbers (WD-R5-2) ---------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "day", "named"),
    [
        ("Closed Thursday 1029", None, set()),
        ("Closed Thursday 1029", NOV5, set()),
        ("Closed Thursday 1105", None, set()),
        ("Closed Thursday 1105", NOV5, {3}),
        ("Closed Thursday 115", NOV5, set()),  # Jan. 15 or Nov. 5: not exact
        ("Closed Thursday 105", NOV5, set()),  # Jan. 5 or Oct. 5
        ("Closed Thursday #1105", NOV5, set()),
        ("Closed Thursday 0530", NOV5, set()),  # May 30, or a time with nothing to say so
        ("Closed Thursday, 120 students", NOV5, set()),
        ("Closed Thursday 2026", NOV5, {3}),  # no month and day
        ("Closed Thursday, 911 calls only", NOV5, set()),  # may be Sept. 11
        ("Closed Thursday, 100 students", NOV5, {3}),  # no month and day
        # an age under a day, taken out of the words, never joins the words around it
        ("Opening Late Thursday 2 Hours. No 4K Classes.", NOV5, {3}),
        ("Activity Canceled Thursday. 4-H Officer Training", NOV5, {3}),
        # told apart by the words around it
        ("Closed Thursday, Bus 1029 runs late", NOV5, {3}),
        ("Closed Thursday, bus #1029 late", NOV5, {3}),
        ("Closed Thursday, Route 104", NOV5, {3}),
        ("Closed Thursday, Room 104", NOV5, {3}),
        ("Closed Thursday, USD 105", NOV5, {3}),
        ("Closed Thursday, meeting at 1030", NOV5, {3}),
        ("Closed Thursday, meeting @ 1030", NOV5, {3}),
        ("Closed Thursday 1030 am", NOV5, {3}),
        ("Closed Thursday 0530 hrs", NOV5, {3}),
        # a day number after the weekday
        ("Closed Thursday 5", None, set()),
        ("Closed Thursday 5", NOV5, {3}),
        ("Closed Thursday, the 5", NOV5, {3}),
        ("Closed Thursday 29", NOV5, set()),
        ("Closed Thursday 6", NOV5, set()),
        ("Closed Thursday #5", NOV5, set()),
        ("Closed Thursday no. 5", NOV5, set()),
        ("Closed Wednesday 5 and Thursday", NOV5, set()),
        ("Closed Thursday 5 and Friday 6", NOV5, set()),  # Friday 6 is not Nov. 5
    ],
)
def test_numbers_that_may_be_a_month_and_day(text: str, day: date | None, named: set[int]) -> None:
    assert named_weekdays(text, "", day) == frozenset(named)


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("Closed Thursday 1029", False),
        ("Closed Thursday 1028", False),
        ("Closed Thursday 115", False),
        ("Closed Thursday #1105", False),
        ("Closed Thursday 29", False),
        ("Closed Thursday 6", False),
        ("Closed Thursday 1105", True),
        ("Closed Thursday 5", True),
        ("Closed Thursday, Bus 1029 runs late", True),
        ("Closed Thursday, Room 104", True),
        ("Closed Thursday, meeting at 1030", True),
        ("Closed Nov. 5 1029", False),
        ("Closed Nov. 5, Bus 1029", True),
    ],
)
def test_a_month_and_day_number_lights_only_on_its_own_day(text: str, shown: bool) -> None:
    world = _cold("2026-11-05 12:00", text)
    assert reasons(world.resolve()) == ([None] if shown else ["unknown_start"])
    expected = {(0, THURSDAY): "CLOSED"} if shown else {}
    assert lit(world.publish(at("2026-11-05 12:01"))) == expected


def test_a_month_and_day_number_on_an_evening_read_names_tomorrow() -> None:
    evening = "2026-11-06 01:00"  # Thu 19:00 Central
    assert lit(_cold(evening, "Closed Friday 1106").publish(at(evening))) == {(0, FRIDAY): "CLOSED"}
    assert lit(_cold(evening, "Closed Friday 1105").publish(at(evening))) == {}
    assert lit(_cold(evening, "Closed Friday 6").publish(at(evening))) == {(0, FRIDAY): "CLOSED"}


# --- reopening words (WD-R5-3) ---------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Closed on Thursday due to the storm; open since",
        "Closed Thursday. Reopened",
        "Closed Thursday; classes resumed",
        "Closed Thursday. Classes resume at 10",
        "Closed Thursday, back in session",
        "Closed Thursday, normal schedule",
        "Closed Thursday. Regular schedule",
        "Closed Thursday; back to normal",
        "Closed Thursday. Now open",
        "Closed Thursday. Classes have resumed",
        "Closed Thursday; closure lifted",
        "CLOSED THURSDAY - RE-OPENED",
        "Closed Nov. 5; open since",
        "Closed Nov. 5. Normal schedule",
        "Closed Nov. 5, classes resumed",
    ],
)
def test_reopening_words_keep_the_hold(text: str) -> None:
    assert not named_weekdays(text, "", NOV5)
    assert not names_date(text, NOV5)
    world = _cold("2026-11-05 12:00", text)
    assert reasons(world.resolve()) != [None]
    assert lit(world.publish(at("2026-11-05 12:01"))) == {}


@pytest.mark.parametrize(
    ("text", "status"),
    [
        ("Closed Thursday, open Friday", "CLOSED"),
        ("Delayed opening Thursday", "DELAYED"),
        ("Closed Thursday", "CLOSED"),
    ],
)
def test_words_that_only_name_an_opening_still_light(text: str, status: str) -> None:
    world = _cold("2026-11-05 12:00", text)
    assert lit(world.publish(at("2026-11-05 12:01"))) == {(0, THURSDAY): status}


# --- weekday-only posting stamps (WD-R5-4) ---------------------------------------------------


@pytest.mark.parametrize(
    ("text", "dates"),
    [
        ("Posted Friday", (None,)),
        ("Updated Saturday", (None,)),
        ("Posted Mon", (None,)),
        ("Posted Tue 9pm", (None,)),
        ("Posted Wed", (date(2026, 11, 4),)),
        ("Posted Wed 9pm", (date(2026, 11, 4),)),
        ("Posted Thu", (date(2026, 11, 5),)),
        ("Updated last night", (date(2026, 11, 4),)),
        ("Posted 3d ago", (None,)),
        ("Updated 5 min ago", ()),
    ],
)
def test_weekday_stamps_two_or_more_days_back_are_unread(
    text: str, dates: tuple[date | None, ...]
) -> None:
    assert stamp_dates(text, NOV5) == dates


@pytest.mark.parametrize(
    ("when", "text", "day"),
    [
        ("2026-11-05 12:00", "Closed Thursday. Posted Friday", None),
        ("2026-11-05 12:00", "Closed Thursday. Posted Saturday", None),
        ("2026-11-05 12:00", "Closed Thursday. Updated Saturday", None),
        ("2026-11-05 12:00", "Closed Thursday. Posted Mon", None),
        ("2026-11-05 12:00", "Closed Thursday. Posted Tuesday", None),
        ("2026-11-05 12:00", "Closed Nov. 5. Posted Friday", None),
        ("2026-11-06 01:00", "Closed Friday. Posted Tuesday", None),
        ("2026-11-05 12:00", "Closed Thursday. Posted Wed 9pm", THURSDAY),
        ("2026-11-05 12:00", "Closed Thursday (posted Wed)", THURSDAY),
        ("2026-11-05 12:00", "Closed Thursday. Posted Thu", THURSDAY),
        ("2026-11-05 12:00", "Closed Thursday. Updated last night", THURSDAY),
        ("2026-11-05 12:00", "Closed Nov. 5. Posted Wed", THURSDAY),
        ("2026-11-06 01:00", "Closed Friday. Posted Thursday", FRIDAY),
        ("2026-11-06 01:00", "Closed Friday. Posted Wednesday", FRIDAY),
    ],
)
def test_a_weekday_only_stamp_lights_only_from_the_read_day_or_the_day_before(
    when: str, text: str, day: str | None
) -> None:
    world = _cold(when, text)
    world.resolve()
    expected = {} if day is None else {(0, day): "CLOSED"}
    assert lit(world.publish(at(when) + timedelta(minutes=1))) == expected


# --- a feed age that ticks between reads (WD-R5C1-B2) ----------------------------------------


@pytest.mark.parametrize(
    "reads",
    [
        # posted Thu 04:00 Central, read three times that day
        [
            ("2026-11-05 11:00", "Closed Thursday · 1h"),
            ("2026-11-05 12:00", "Closed Thursday · 2h"),
            ("2026-11-05 18:00", "Closed Thursday · 8h"),
        ],
        # posted Wed 21:00 Central: tomorrow on the evening read, today the next morning
        [
            ("2026-11-05 04:00", "Closed Thursday · 1h"),
            ("2026-11-05 12:00", "Closed Thursday · 9h"),
        ],
        [
            ("2026-11-05 03:00", "Closed Thursday · 1h"),
            ("2026-11-05 12:00", "Closed Thursday · 10h"),
        ],
        [
            ("2026-11-05 03:00", "Closed Thursday. Posted Wed 8pm"),
            ("2026-11-05 12:00", "Closed Thursday. Posted Wed 8pm"),
        ],
    ],
)
def test_a_lit_row_whose_feed_age_ticks_stays_lit(reads: list[tuple[str, str]]) -> None:
    world = World(reader=F5)
    for when, text in reads:
        world.read(at(when), [row(ALPHA_SCHOOL, text)])
        assert lit(world.publish(at(when))) == {(0, THURSDAY): "CLOSED"}, (when, text)


def test_a_successor_whose_age_reaches_a_day_is_held() -> None:
    world = World(reader=F5)
    world.read(at("2026-11-05 11:00"), [row(ALPHA_SCHOOL, "Closed Thursday · 23h")])
    assert lit(world.publish(at("2026-11-05 11:00"))) == {(0, THURSDAY): "CLOSED"}
    world.read(at("2026-11-05 12:00"), [row(ALPHA_SCHOOL, "Closed Thursday · 1d")])
    assert lit(world.publish(at("2026-11-05 12:00"))) == {}


# --- more month and day numbers, reopening words and possessives (WD-R5C1-S2-S5) -------------


@pytest.mark.parametrize(
    ("text", "day", "named"),
    [
        # a month and day with a year (WD-R5C1-S2): Oct. 29, 2026 was last week's Thursday
        ("Closed Thursday 1029-26", NOV5, set()),
        ("Closed Thursday 102926", NOV5, set()),
        ("Closed Thursday 10292026", NOV5, set()),
        ("Closed Thursday 110525", NOV5, set()),  # Nov. 5, 2025
        ("Closed Thursday 1105-25", NOV5, set()),
        ("Closed Thursday 110526", NOV5, {3}),
        ("Closed Thursday 11052026", NOV5, {3}),
        ("Closed Thursday 1105-26", NOV5, {3}),
        ("Closed Thursday 110526", None, set()),
        ("Closed Thursday, 123456 students", NOV5, {3}),  # no month and day
        ("Closed Thursday, call 608-555-1029", NOV5, {3}),  # a phone number
        # a length in minutes is no date (WD-R5C1-B1)
        ("Thursday: 120 minute delay", NOV5, {3}),
        ("Thursday: 120-min. delay", NOV5, {3}),
        ("Thursday: 110 mins late", NOV5, {3}),
        # a day number before the weekday (WD-R5C1-S5)
        ("Closed 29 Thursday", NOV5, set()),
        ("Closed 6 Thursday", NOV5, set()),
        ("Closed 5 Thursday", NOV5, {3}),
        ("Closed 5 Thursday", None, set()),
        ("5&6 Thursday and Friday", NOV5, set()),
        ("Opening at 9 Thursday", NOV5, {3}),  # a clock time
        ("Closed Thursday, Bus 5 Thursday route", NOV5, {3}),
        # a possessive weekday that owns no school day (WD-R5C1-S4)
        ("Closed Thursday, per Friday's notice", NOV5, set()),
        ("Closed Thursday, per Friday\u2019s notice", NOV5, set()),
        ("Closed Thursday as in Monday's message", NOV5, set()),
        ("Closed Thursday per Friday's", NOV5, set()),
        ("Thursday's classes are cancelled", NOV5, {3}),
        ("Thursday's activities canceled", NOV5, {3}),
        # a weekday a notice went out on (self-audit of the critic's shapes)
        ("Closed Thursday. Released Friday", NOV5, set()),
        ("Closed Thursday. Issued Friday", NOV5, set()),
        ("Closed Thursday. Friday post", NOV5, set()),
        ("Closed Thursday, see Friday notice", NOV5, set()),
        ("Closed Thursday as announced on Monday", NOV5, set()),
        # a day number standing alone as a clause
        ("29: Closed Thursday", NOV5, set()),
        ("Closed Thursday, 29", NOV5, set()),
        ("5: Closed Thursday", NOV5, {3}),
        ("29: Closed Thursday", None, set()),
        ("Closed 11/05: Thursday", NOV5, set()),  # a date wins
        ("Closed Thursday, 6:30 start", NOV5, {3}),  # a clock time
        ("Closed Thursday, routes 2, 3, 4", NOV5, {3}),  # a list of numbers
        ("Closed Thursday, 52", NOV5, {3}),  # no day of a month
        ("Closed Thursday (29)", NOV5, set()),
    ],
)
def test_more_numbers_and_possessives(text: str, day: date | None, named: set[int]) -> None:
    assert named_weekdays(text, "", day) == frozenset(named)


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("Closed Thursday 1029-26", False),
        ("Closed Thursday 102926", False),
        ("Closed Thursday 10292026", False),
        ("Closed Thursday 110526", True),
        ("Closed 29 Thursday", False),
        ("Closed Thursday, per Friday's notice", False),
        ("Thursday's classes are cancelled", True),
        ("Closed Nov. 5 102926", False),
        ("Closed Nov. 5 110526", True),
    ],
)
def test_a_dated_number_or_a_possessive_lights_only_on_its_own_day(text: str, shown: bool) -> None:
    world = _cold("2026-11-05 12:00", text)
    world.resolve()
    expected = {(0, THURSDAY): "CLOSED"} if shown else {}
    assert lit(world.publish(at("2026-11-05 12:01"))) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Closed Thursday. Closure over",
        "Closed Thursday. Closure is over",
        "Closed Thursday. All clear",
        "Closed Thursday; closing ended",
        "Closed Thursday. Closure has been lifted",
        "Thursday: 2 hour delay. Delay cancelled",
        "Thursday 2 hour delay; delay is over",
        "Closed Thursday. Closing rescinded",
        "Closed Nov. 5. All clear",
    ],
)
def test_words_that_end_the_closure_keep_the_hold(text: str) -> None:
    assert not named_weekdays(text, "", NOV5)
    assert not names_date(text, NOV5)
    world = _cold("2026-11-05 12:00", text)
    world.resolve()
    assert lit(world.publish(at("2026-11-05 12:01"))) == {}


# --- pass time on long rows (WD-R5C1-S7) -----------------------------------------------------


_CACHED = (named_weekdays, _weekday_words, _clocked, _lone_candidates, _ages, _mask_clocks)
"""What the reader keeps for words it has read: cleared before each timed read."""


@pytest.mark.parametrize(
    "text",
    [
        "Closed Thursday " + "Bus 1029 " * 220,
        "Closed Thursday " + "2h " * 660,
        "2 hour delay Thursday " + "2 hours late " * 150,
        "Closed Thursday " + "Thursday " * 220,
        "Closed Thursday " + "word " * 400,
        "Closed Thursday " + "Fri 9:14 PM " * 170,
        "Closed Thursday " + "Thursday 9 AM start " * 100,
        "Closed Thursday " + "Updated 11/5 6:30 AM. " * 90,
        # many clock times, spans, stamp words and weekdays with marks (WD-R7C1-B2)
        "9:14 " * 400,
        "9 PM " * 400,
        "noon " * 400,
        "9 AM to " * 250,
        "Closed Thursday " + "9:14 PM closed " * 140,
        "Closed Thursday " + "8:30-3:15 " * 200 + " 9:14 PM Friday",
        "Closed Thursday " + "9 to 3 " * 285,
        "Closed Thursday " + "9 a " * 500,
        "posted " * 290,
        "Closed Thursday " + "Thursday posted " * 125,
        "Closed Thursday " + "Thu _ " * 330,
        "Closed Thursday " + "Thursday: from 9 AM to 3 PM " * 75,
        # bare numbers by runs of marks, and a span far past them (round 8)
        "Closed Thursday " + "9...Thu " * 250,
        "Closed Thursday " + "Thursday: 9 | info " * 105,
        "Closed Thursday · Friday | " + "word " * 400 + "(9 AM - 3 PM)",
    ],
)
def test_a_long_row_is_read_in_time_linear_in_its_length(text: str) -> None:
    def took(length: int) -> float:
        words = text[:length]
        best = float("inf")
        for _ in range(3):
            for cached in _CACHED:
                cached.cache_clear()
            began = time.perf_counter()
            named_weekdays(words, "", NOV5)
            names_date(words, NOV5)
            post_ages(words)
            stamp_dates(words, NOV5, THU_0600)
            best = min(best, time.perf_counter() - began)
        return best

    # four times as long (the archive's longest row is 2000 characters) takes about four
    # times as long, never the sixteen a reading over each whole prefix would
    assert took(2000) < 9 * took(500) + 0.002  # linear, with room for noise


# --- round 6: clock stamps, glued ages, over words, dated stamps two or more days back -------

THU_0600 = at("2026-11-05 12:00").astimezone(ZoneInfo("America/Chicago"))
"""The read the round 6 word tests are read at: Thursday Nov. 5, 06:00 Central."""


@pytest.mark.parametrize(
    ("text", "named", "stamps"),
    [
        # a weekday with a clock time and no status word is a posting stamp (WD-R5C2-S1)
        ("Closed Thursday · Fri 9:14 PM", {3}, (None,)),
        ("Closed Thursday | Fri 9:14 PM", {3}, (None,)),
        ("Closed Thursday · Friday, 9:14 PM", {3}, (None,)),
        ("Closed Thursday · Friday 21:14", {3}, (None,)),
        ("Closed Thursday · Friday at 9:14 PM", {3}, (None,)),
        ("Closed Thursday Sat 7:12am", {3}, (None,)),
        ("Closed Thursday Sat. 7:12am", {3}, (None,)),
        ("Closed Thursday. Fri 9:14 PM", {3}, (None,)),
        ("Closed Thursday (Fri 9pm)", {3}, (None,)),
        ("2 hour delay Thursday · Fri 9:14 PM", {3}, (None,)),
        ("Closed Thursday · Wed 9:14 PM", {3}, (date(2026, 11, 4),)),
        ("Closed Thursday · Thu 5:02 AM", {3}, (date(2026, 11, 5),)),
        ("Closed Thursday · Thu 6:02 AM", {3}, (None,)),  # after the read: a week back
        ("Closed. Thursday 5:02 AM", set(), (date(2026, 11, 5),)),
        ("Fri 9:14 PM Closed Thursday", {3}, (None,)),  # "Closed" is Thursday's
        ("Fri 9:14 PM: Closed Thursday", {3}, (None,)),
        # a status word in its clause makes it a day the row is for
        ("Early dismissal Thursday 1:30 PM", {3}, ()),
        ("Thursday 10 AM start", {3}, ()),
        ("Opening late at 10:00 AM Thursday, 9 AM buses", {3}, ()),
        ("Closed Thursday 6 AM", {3}, (date(2026, 11, 5),)),  # a time on its day: by the read
        ("Closed Thursday, 2 hour delay Friday 10 AM start", {3, 4}, ()),
        ("Thursday 10 AM start, Friday closed", {3, 4}, ()),
    ],
)
def test_a_weekday_with_a_clock_time_and_no_status_word_is_a_stamp(
    text: str, named: set[int], stamps: tuple[date | None, ...]
) -> None:
    assert named_weekdays(text, "", NOV5) == frozenset(named)
    assert stamp_dates(text, NOV5, THU_0600) == stamps


@pytest.mark.parametrize(
    ("text", "ages"),
    [
        # an age glued to the word before it is an age (WD-R5C2-S2)
        ("Closed Thursday,5d", (timedelta(days=5),)),
        ("Closed Thursday.5d", (timedelta(days=5),)),
        ("Closed Thursday:6d", (timedelta(days=6),)),
        ("Closed Thursday/6d", (timedelta(days=6),)),
        ("Closed Thursday5d", (timedelta(days=5),)),
        ("Closed Thursday,30h", (timedelta(hours=30),)),
        ("Closed Thursday,2h", (timedelta(hours=2),)),
        # never the end of another number
        ("2.5 hr delay", ()),
        ("Updated 10:30m", ()),
        ("Closed 11/5d", ()),
        ("1,440 students, 2,000 ft", ()),
        ("Snow for 3-6 hours", ()),
    ],
)
def test_glued_ages(text: str, ages: tuple[timedelta, ...]) -> None:
    assert post_ages(text) == ages


@pytest.mark.parametrize(
    ("text", "named"),
    [
        ("Closed Thursday,5d", set()),
        ("Closed Thursday.5d", set()),
        ("Closed Thursday:6d", set()),
        ("Closed Thursday/6d", set()),
        ("Closed Thursday 5d", set()),
        ("Closed Thursday 5x", set()),  # a day number with a letter glued names no day
        ("Closed Thursday,2h", {3}),  # an age under a day: left to the resolver
        ("Closed Thursday 5", {3}),
        # open again and over words (WD-R5C2-S3)
        ("Closed Thursday. Open again", set()),
        ("Closed Thursday. Opening again Friday", set()),
        ("Closed Thursday. Back open", set()),
        ("Closed Thursday (over)", set()),
        ("Closed Thursday ( over )", set()),
        ("Closed Thursday. It is over", set()),
        ("Closed Thursday, it\u2019s over", set()),
        ("Closed Thursday. Over.", set()),
        ("Closed Thursday • over", set()),
        ("Closed Thursday. Ended", set()),
        ("Closed Thursday; expired", set()),
        ("Closed Thursday, no longer in effect", set()),
        ("Closed Thursday, sent out Friday", set()),
        ("Closed Thursday. Notice went out Friday", set()),
        ("Closed Thursday, mailed Friday", set()),
        ("Closed Thursday over 6 inches of snow", {3}),
        ("Closed Thursday as recommended", {3}),
    ],
)
def test_glued_ages_and_over_words_in_the_words(text: str, named: set[int]) -> None:
    assert named_weekdays(text, "", NOV5) == frozenset(named)


@pytest.mark.parametrize(
    ("text", "stamps"),
    [
        # a stamp of the read's day at a clock time after the read is unreadable
        ("Closed Thursday. Updated 11/5 6:30 AM", (None,)),
        ("Closed Thursday. Updated 11/5 6:30 AM CST", (None,)),
        ("Closed Thursday. Updated 11/5 6:30 AM EST", (date(2026, 11, 5),)),  # 5:30 Central
        ("Closed Thursday. Updated 11/5 5:30 AM", (date(2026, 11, 5),)),
        ("Closed Thursday. Posted Thu 6:02 AM", (None,)),
        ("Closed Thursday. Posted Nov. 5 7:00 AM", (None,)),  # its date runs on past "."
        ("Closed Thursday. Posted Nov 5 at noon", (None,)),
        ("Closed Thursday. Updated today at 7 AM", (None,)),
        ("Closed Thursday. Updated 11/4 11:00 PM", (date(2026, 11, 4),)),
        ("Closed Thursday. Updated Fri 10/30", (date(2026, 10, 30),)),
    ],
)
def test_a_stamp_after_the_read_is_unread(text: str, stamps: tuple[date | None, ...]) -> None:
    assert stamp_dates(text, NOV5, THU_0600) == stamps


def test_with_no_read_time_a_clock_time_bounds_nothing() -> None:
    assert stamp_dates("Closed Thursday. Updated 11/5 6:30 AM", NOV5) == (date(2026, 11, 5),)
    assert stamp_dates("Closed Thursday · Thu 6:02 AM", NOV5) == (date(2026, 11, 5),)
    assert stamp_dates("Closed Thursday · Fri 9:14 PM", NOV5, clocked=False) == ()


@pytest.mark.parametrize(
    ("when", "text"),
    [
        # a weekday with a clock time and no status word: a stamp (WD-R5C2-S1)
        ("2026-11-05 12:00", "Closed Thursday · Fri 9:14 PM"),
        ("2026-11-05 12:00", "Closed Thursday | Fri 9:14 PM"),
        ("2026-11-05 12:00", "Closed Thursday · Friday, 9:14 PM"),
        ("2026-11-05 12:00", "Closed Thursday · Friday 21:14"),
        ("2026-11-05 12:00", "Closed Thursday · Fri 9pm"),
        ("2026-11-05 12:00", "Closed Thursday · Sat 7:12 AM"),
        ("2026-11-05 12:00", "Closed Thursday · Sun 10:00 PM"),
        ("2026-11-05 12:00", "Closed Thursday Sat 7:12am"),
        ("2026-11-05 12:00", "Closed Thursday Sat. 7:12am"),
        ("2026-11-05 12:00", "Closed Thursday. Fri 9:14 PM"),
        ("2026-11-05 12:00", "Closed Thursday. Friday at 9:14 PM"),
        ("2026-11-05 12:00", "2 hour delay Thursday · Fri 9:14 PM"),
        ("2026-11-05 12:00", "Fri 9:14 PM Closed Thursday"),
        ("2026-11-06 12:00", "Closed Friday · Sat 7:12 AM"),
        ("2026-11-09 12:00", "Closed Monday · Tue 8:00 PM"),
        ("2026-11-05 10:30", "Closed Thursday · Thu 5:02 AM"),  # 04:30: after the read
        # glued ages (WD-R5C2-S2)
        ("2026-11-05 12:00", "Closed Thursday,5d"),
        ("2026-11-05 12:00", "Closed Thursday.5d"),
        ("2026-11-05 12:00", "Closed Thursday:6d"),
        ("2026-11-05 12:00", "Closed Thursday/6d"),
        ("2026-11-05 12:00", "Closed Thursday,30h"),
        # open again and over words, a notice sent out (WD-R5C2-S3)
        ("2026-11-05 12:00", "Closed Thursday. Open again"),
        ("2026-11-05 12:00", "Closed Thursday (over)"),
        ("2026-11-05 12:00", "Closed Thursday. It is over"),
        ("2026-11-05 12:00", "Closed Thursday. Ended"),
        ("2026-11-05 12:00", "Closed Thursday, no longer in effect"),
        ("2026-11-05 12:00", "Closed Thursday, sent out Friday"),
        ("2026-11-05 12:00", "Closed Nov. 5. Open again"),
        # dated stamps two or more days back (WD-R5C2-S4, lead ruling: hold)
        ("2026-11-05 12:00", "Closed Thursday. Updated Fri 10/30"),
        ("2026-11-05 12:00", "Closed Thursday. Posted 10/30"),
        ("2026-11-05 12:00", "Closed Thursday. Posted Oct 30"),
        ("2026-11-05 12:00", "Closed Thursday. Updated Oct. 30 4:00 PM"),
        ("2026-11-05 12:00", "Closed Thursday. Updated 10/31 6:00 AM"),
        ("2026-11-05 12:00", "Closed Thursday. Posted Mon 11/2"),
        ("2026-11-05 12:00", "Closed Thursday. Updated Nov. 3"),
        ("2026-11-05 12:00", "Closed Thursday (updated 11/3/2026)"),
        ("2026-11-05 01:00", "Closed Thursday. Posted 11/2"),  # Wed 19:00: two days back
        # a stamp of the read's day after the read
        ("2026-11-05 12:00", "Closed Thursday. Updated 11/5 6:30 AM"),
        ("2026-11-05 12:00", "Closed Thursday. Posted Thu 6:02 AM"),
        ("2026-11-05 01:00", "Closed Thursday. Posted Wed 8:00 PM"),
    ],
)
def test_round_6_shapes_keep_the_hold(when: str, text: str) -> None:
    world = _cold(when, text)
    world.resolve()
    assert lit(world.publish(at(when) + timedelta(minutes=1))) == {}


@pytest.mark.parametrize(
    ("when", "text", "day", "status"),
    [
        ("2026-11-05 12:00", "Closed Thursday · Thu 5:02 AM", THURSDAY, "CLOSED"),
        ("2026-11-05 12:00", "Early dismissal Thursday 1:30 PM", THURSDAY, "EARLY_DISMISSAL"),
        ("2026-11-05 12:00", "Thursday 10 AM start", THURSDAY, "DELAYED"),
        ("2026-11-05 12:00", "Thursday: 2 hour delay, 10:00 AM start", THURSDAY, "DELAYED"),
        ("2026-11-05 12:00", "Closed Thursday 6 AM", THURSDAY, "CLOSED"),
        ("2026-11-05 12:00", "Closed Thursday,2h", THURSDAY, "CLOSED"),
        ("2026-11-05 12:00", "Closed Thursday over 6 inches of snow", THURSDAY, "CLOSED"),
        ("2026-11-05 12:00", "Closed Thursday. Updated Nov. 4", THURSDAY, "CLOSED"),
        ("2026-11-05 12:00", "Closed Thursday. Updated 11/5 5:30 AM", THURSDAY, "CLOSED"),
        ("2026-11-05 12:00", "Closed Thursday. Updated 11/5 6:30 AM EST", THURSDAY, "CLOSED"),
        ("2026-11-05 12:00", "Closed Thursday. Posted Wed 9pm", THURSDAY, "CLOSED"),
        ("2026-11-05 01:00", "Closed Thursday. Posted 11/3", THURSDAY, "CLOSED"),
        ("2026-11-05 01:00", "Closed Thursday. Posted Wed 6:00 PM", THURSDAY, "CLOSED"),
        # a date names its day exactly: a stamp days before it is a notice given ahead
        ("2026-11-05 12:00", "Closed Nov. 5. Posted 10/30", THURSDAY, "CLOSED"),
    ],
)
def test_round_6_shapes_that_still_light(when: str, text: str, day: str, status: str) -> None:
    world = _cold(when, text)
    world.resolve()
    assert lit(world.publish(at(when) + timedelta(minutes=1))) == {(0, day): status}


def test_a_dated_stamp_two_or_more_days_back_holds_only_on_the_weekday_path() -> None:
    hi = at("2026-11-05 12:00")
    entry = LedgerRow(
        key=b"k",
        source_id=SOURCE,
        hi=hi,
        lo=None,
        start=Start.COLD,
        row_stamp=None,
        last_seen=hi,
        absent_since=None,
        gone=False,
        ident=b"i",
        pred=None,
        lapsed=False,
        earliest=hi,
    )
    zones = ["America/Chicago"]
    for text, recent in [
        ("Closed Thursday. Posted 10/30", False),
        ("Closed Thursday. Posted 11/3", False),
        ("Closed Thursday. Posted 11/4", True),
        ("Closed Thursday. Posted 11/5 5:00 AM", True),
        ("Closed Thursday. Posted 11/5 7:00 AM", False),
        ("Closed Thursday · Fri 9:14 PM", False),
        ("Closed Thursday · Wed 9:14 PM", True),
    ]:
        seen = row(ALPHA_SCHOOL, text)
        assert _posted_before(seen, entry, zones, NOV5) is recent, text
        assert _posted_before(seen, entry, zones, NOV5, weekday=False) is (
            recent or "Fri" in text or "10/30" in text or "11/3" in text
        ), text


@settings(max_examples=300, deadline=None)
@given(
    st.lists(
        st.sampled_from(
            ["Closed", "Thursday", "Fri", "Sat.", "9:14", "PM", "7:12am", "21:14", "noon", "at",
             "@", "·", "|", ".", ",", "5d", ",5d", ".6d", "2h", "over", "(over)", "again",
             "open", "sent", "out", "Updated", "Posted", "11/5", "10/30", "6:30 AM", "EST",
             "CST", "ET", "99:99", "13 pm", "0 am", "midnight", "start", "dismissal"]
        ),
        max_size=12,
    ),
    st.integers(min_value=0, max_value=23),
    st.booleans(),
)  # fmt: skip
def test_round_6_rules_never_raise(tokens: list[str], hour: int, aware: bool) -> None:
    text = " ".join(tokens)
    now = THU_0600.replace(hour=hour)
    if not aware:
        now = now.replace(tzinfo=None)
    named_weekdays(text, "", NOV5)
    post_ages(text)
    stamp_dates(text, NOV5, now)
    stamp_dates(text, NOV5, now, clocked=False)


# --- round 6, critic round 1: clock forms, named days at a time after the read, more words --


@pytest.mark.parametrize(
    ("when", "text"),
    [
        # a second weekday with a clock time and no status word is a stamp in every form
        # (WD-R6C1-B1): in brackets or quotes, before the weekday, a bare or approximate hour
        ("2026-11-05 12:00", "Closed Thursday · Friday (9:14pm)"),
        ("2026-11-05 12:00", "Closed Thursday · Fri (21:14)"),
        ("2026-11-05 12:00", "Closed Thursday · Friday [9:14 PM]"),
        ("2026-11-05 12:00", "Closed Thursday · Friday {9:14 PM}"),
        ("2026-11-05 12:00", 'Closed Thursday · Friday "9:14 PM"'),
        ("2026-11-05 12:00", "Closed Thursday · 9:14 PM Friday"),
        ("2026-11-05 12:00", "Closed Thursday · 9:14 PM, Friday"),
        ("2026-11-05 12:00", "Closed Thursday · at 9:14 PM Friday"),
        ("2026-11-05 12:00", "Closed Thursday · 9:14 PM Fri"),
        ("2026-11-05 12:00", "Closed Thursday · 21:14 Fri"),
        ("2026-11-05 12:00", "Closed Thursday · Friday at 9"),
        ("2026-11-05 12:00", "Closed Thursday · Fri at 9"),
        ("2026-11-05 12:00", "Closed Thursday · Friday around 9 PM"),
        ("2026-11-05 12:00", "Closed Thursday · Friday about 9:14 PM"),
        ("2026-11-05 12:00", "Closed Thursday · Fri 2114"),
        ("2026-11-05 12:00", "Closed Thursday · Friday evening"),
        ("2026-11-05 12:00", "Closed Thursday · Friday night"),
        # a named weekday whose clock time is after the read on its day (WD-R6C1-S2)
        ("2026-11-06 12:00", "Closed Friday 9:14 PM"),
        ("2026-11-06 12:00", "Friday 9:14 PM Closed"),
        ("2026-11-06 12:00", "Friday closed 9:14 PM"),
        ("2026-11-06 12:00", "Fri 9:14 PM closed"),
        ("2026-11-06 12:00", "School closed Fri 9:14 PM"),
        ("2026-11-05 12:00", "Closed Thursday · Fri 9:14 PM closed"),
        ("2026-11-05 12:00", "Closed Thursday · Fri 9:14 PM school"),
        ("2026-11-05 12:00", "Closed Thursday 7:00 AM update"),
        ("2026-11-05 12:00", "Closed Thursday 1030 am"),
        # a stamp whose weekday or date ends in "." before its clock time (WD-R6C1-S1)
        ("2026-11-05 12:00", "Closed Thursday. Updated Thu. 7:00 AM"),
        ("2026-11-05 12:00", "Closed Thursday. Updated Thu., 7:00 AM"),
        ("2026-11-05 12:00", "Closed Thursday. Updated Thu. Nov. 5 7:00 AM"),
        ("2026-11-05 12:00", "Closed Thursday. Updated Nov. 5. 7:00 AM"),
        # over, again, past-tense and notice words (WD-R6C1-S3)
        ("2026-11-05 12:00", "Closed Thursday [over]"),
        ("2026-11-05 12:00", "Closed Thursday *over*"),
        ("2026-11-05 12:00", "Closed Thursday ~ over"),
        ("2026-11-05 12:00", "Closed Thursday / over"),
        ("2026-11-05 12:00", "Closed Thursday over"),
        ("2026-11-05 12:00", "Closed Thursday. Open once more"),
        ("2026-11-05 12:00", "School had been closed Thursday"),
        ("2026-11-05 12:00", "Classes were cancelled Thursday"),
        ("2026-11-05 12:00", "Closed Thursday, notified families Friday"),
        ("2026-11-05 12:00", "Closed Thursday, communicated Friday"),
        ("2026-11-05 12:00", "Closed Thursday, broadcast Friday"),
        ("2026-11-05 12:00", "Closed Thursday, called Friday"),
        ("2026-11-05 12:00", "Closed Thursday, reported Friday"),
        ("2026-11-05 12:00", "Closed Thursday, confirmed Friday"),
        ("2026-11-05 12:00", "Closed Thursday, message Friday"),
        ("2026-11-05 12:00", "Closed Thursday, alert Friday"),
        ("2026-11-05 12:00", "Closed Thursday, notification Friday"),
        # an age glued to a clock time (WD-R6C1-S4)
        ("2026-11-05 12:00", "Closed Thursday 6:00,5d"),
        # a stamp of the day before in a stated zone, after the read (WD-R6C1-S7)
        ("2026-11-05 07:00", "Closed Thursday. Updated 11/4 11:30 PM PT"),
        ("2026-11-05 07:00", "Closed Thursday · Wed 11:30 PM PT"),
    ],
)
def test_round_6_critic_shapes_keep_the_hold(when: str, text: str) -> None:
    world = _cold(when, text)
    world.resolve()
    assert lit(world.publish(at(when) + timedelta(minutes=1))) == {}


@pytest.mark.parametrize(
    ("when", "text", "day", "status"),
    [
        # a start, opening, closing or dismissal time owns the clock: the day still lights
        ("2026-11-05 12:00", "Early dismissal Thursday (1:30 PM)", THURSDAY, "EARLY_DISMISSAL"),
        ("2026-11-05 12:00", "Opening at 10 AM Thursday", THURSDAY, "DELAYED"),
        ("2026-11-05 12:00", "Closing at 1 p.m. Thursday", THURSDAY, "EARLY_DISMISSAL"),
        ("2026-11-06 12:00", "Closed Friday 5:30 AM", FRIDAY, "CLOSED"),  # before the read
        # a part of the day as a heading, an alert's own day, "called off"
        ("2026-11-05 12:00", "Thursday Afternoon: Closed", THURSDAY, "EARLY_DISMISSAL"),
        ("2026-11-05 12:00", "Alert Thursday. Closed Thursday", THURSDAY, "CLOSED"),
        ("2026-11-05 12:00", "School called off Thursday", THURSDAY, "CLOSED"),
        ("2026-11-05 12:00", "Closed Thursday 6:00, 2h", THURSDAY, "CLOSED"),
        # a stamp with a "." before its clock time, read after that time
        ("2026-11-05 14:00", "Closed Thursday. Updated Thu. 7:00 AM", THURSDAY, "CLOSED"),
        ("2026-11-05 14:00", "Closed Thursday. Updated Thu., 7:00 AM", THURSDAY, "CLOSED"),
        ("2026-11-05 14:00", "Closed Thursday. Updated Thu. Nov. 5 7:00 AM", THURSDAY, "CLOSED"),
        ("2026-11-05 14:00", "Closed Thursday. Updated Nov. 5. 7:00 AM", THURSDAY, "CLOSED"),
        # night-before stamps on an evening read light tomorrow (WD-R6C1-S5): the stamp's
        # weekday names no status day, so the row is dated by the day it names
        ("2026-11-05 03:30", "Thursday closed. Wed 9:14 PM", THURSDAY, "CLOSED"),
        ("2026-11-05 03:30", "Closed Thursday | Wed 9:14 PM", THURSDAY, "CLOSED"),
        ("2026-11-05 03:30", "Thursday closed (Wed 9:14 PM)", THURSDAY, "CLOSED"),
        ("2026-11-06 12:00", "Closed Friday. Posted yesterday Nov. 5 9 PM", FRIDAY, "CLOSED"),
    ],
)
def test_round_6_critic_shapes_that_still_light(
    when: str, text: str, day: str, status: str
) -> None:
    world = _cold(when, text)
    world.resolve()
    assert lit(world.publish(at(when) + timedelta(minutes=1))) == {(0, day): status}


THU_0100 = at("2026-11-05 07:00").astimezone(ZoneInfo("America/Chicago"))
"""Thursday Nov. 5, 01:00 Central: Wednesday 23:00 Pacific."""


@pytest.mark.parametrize(
    ("text", "now", "named", "stamps"),
    [
        # clock forms (WD-R6C1-B1)
        ("Closed Thursday · Friday (9:14pm)", THU_0600, {3}, (None,)),
        ("Closed Thursday · 9:14 PM Fri", THU_0600, {3}, (None,)),
        ("Closed Thursday · at 9 Friday", THU_0600, {3}, (None,)),
        ("Closed Thursday · Fri 2114", THU_0600, {3}, (None,)),
        ("Closed Thursday · Wed (9:14 PM)", THU_0600, {3}, (date(2026, 11, 4),)),
        ("Closed Thursday · 9:14 PM Wed", THU_0600, {3}, (date(2026, 11, 4),)),
        ("Closed Thursday · Wed evening", THU_0600, {3}, (date(2026, 11, 4),)),
        ("Closed Thursday · Thu evening", THU_0600, {3}, (None,)),
        # a bare hour is after the read if it is so in the morning or the evening
        ("Closed Thursday · Thu at 5", THU_0600, {3}, (None,)),
        ("Closed Thursday · Thu at 5", THU_0600.replace(hour=18), {3}, (date(2026, 11, 5),)),
        # a status word or an owner keeps the weekday a day the row is for
        ("Early dismissal Thursday (1:30 PM)", THU_0600, {3}, ()),
        ("Opening at 10 AM Thursday", THU_0600, {3}, ()),
        ("Closing 1pm Thursday", THU_0600, {3}, ()),
        ("Building closing Thursday at 5pm", THU_0600, {3}, ()),
        ("Activities cancelled Thursday evening", THU_0600, {3}, ()),
        ("Thursday Afternoon: Closed", THU_0600, {3}, ()),
        ("No 8 AM Mass Thursday", THU_0600, {3}, ()),
        ("10am Thursday worship canceled", THU_0600, {3}, ()),
        ("Services at 8:30 or 11:00 on Thursday cancelled", THU_0600, {3}, ()),
        ("6 a.m. to 8 p.m. on Thursday: closed", THU_0600, {3}, ()),
        ("Staff report at 9am Thursday, closed to students", THU_0600, {3}, ()),
        # a named weekday's clock time is a time on its day: after the read, it holds
        ("Closed Thursday 9:14 PM", THU_0600, {3}, (None,)),
        ("Thursday closed 9:14 PM", THU_0600, {3}, (None,)),
        ("Closed Thursday 5:30 AM", THU_0600, {3}, (date(2026, 11, 5),)),
        ("Closed Friday 6 AM", THU_0600.replace(hour=20), {4}, (None,)),  # a week back
        # a stamp's clock time past its "." (WD-R6C1-S1)
        ("Closed Thursday. Updated Thu. 7:00 AM", THU_0600, {3}, (None,)),
        ("Closed Thursday. Updated Nov. 5. 7:00 AM", THU_0600, {3}, (None,)),
        ("Closed Thursday. Updated Nov. 5. 5:00 AM", THU_0600, {3}, (date(2026, 11, 5),)),
        ("Closed Thursday. Updated Mon. Nov. 2", THU_0600, set(), (None,)),
        ("Closed Thursday. Posted yesterday. 9 AM start", THU_0600, {3}, (None,)),
        # a stamp of the day before in a stated zone, after the read (WD-R6C1-S7)
        ("Closed Thursday. Updated 11/4 11:30 PM PT", THU_0100, {3}, (None,)),
        ("Closed Thursday · Wed 11:30 PM PT", THU_0100, {3}, (None,)),
        ("Closed Thursday. Updated 11/4 10:30 PM PT", THU_0100, {3}, (date(2026, 11, 4),)),
        ("Closed Thursday. Updated 11/4 11:30 PM", THU_0100, {3}, (date(2026, 11, 4),)),
        # a weekday-only stamp with its date run on
        ("Closed Thursday · Wed 9 PM, Nov. 4", THU_0600, set(), (date(2026, 11, 4),)),
        ("Closed Thursday · Wed 9 PM, Oct. 28", THU_0600, set(), (date(2026, 10, 28),)),
    ],
)
def test_round_6_clock_forms_and_stamps(
    text: str, now: datetime, named: set[int], stamps: tuple[date | None, ...]
) -> None:
    assert named_weekdays(text, "", now.date()) == frozenset(named)
    assert stamp_dates(text, now.date(), now) == stamps


@pytest.mark.parametrize(
    ("text", "named"),
    [
        ("Closed Thursday [over]", set()),
        ("Closed Thursday *over*", set()),
        ("Closed Thursday - over", set()),
        ("Closed Thursday over", set()),
        ("Closed Thursday over 6 inches of snow", {3}),
        ("Closed Thursday; moreover, buses", {3}),
        ("Closed Thursday. Open once more", set()),
        ("School had been closed Thursday", set()),
        ("Classes were cancelled Thursday", set()),
        ("Closed Thursday, notified families Friday", set()),
        ("Closed Thursday, communicated to parents Friday", set()),
        ("Closed Thursday, message Friday", set()),
        ("Closed Thursday, alert sent Friday", set()),
        ("Alert Thursday. Closed Thursday", {3}),  # the alert's own day, as a heading
        ("Games called off Thursday", {3}),
        ("District announced school closed Thursday", {3}),
    ],
)
def test_round_6_over_past_and_notice_words(text: str, named: set[int]) -> None:
    assert named_weekdays(text, "", NOV5) == frozenset(named)


@pytest.mark.parametrize(
    ("text", "ages"),
    [
        ("Closed Thursday 6:00,5d", (timedelta(days=5),)),
        ("Closed Thursday 6:00/5d", (timedelta(days=5),)),
        ("Updated 10:30,2h", (timedelta(hours=2),)),
        ("Updated 10:30m", ()),
        ("1,440 students, 2,000 ft", ()),
    ],
)
def test_round_6_an_age_glued_to_a_clock_time(text: str, ages: tuple[timedelta, ...]) -> None:
    assert post_ages(text) == ages


# --- round 6, critic round 2 -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("when", "text"),
    [
        # a second weekday's clock time past a clause mark is a stamp (WD-R6C2-B1)
        ("2026-11-05 12:00", "Closed Thursday · Friday: 9:14 PM"),
        ("2026-11-05 12:00", "Closed Thursday · Friday; 9:14 PM"),
        ("2026-11-05 12:00", "Closed Thursday · Friday | 9:14 PM"),
        ("2026-11-05 12:00", "Closed Thursday · Friday/9:14 PM"),
        ("2026-11-05 12:00", "Closed Thursday · Friday · 9:14 PM"),
        ("2026-11-05 12:00", "Closed Thursday · Friday • 9:14 PM"),
        ("2026-11-05 12:00", "Closed Thursday · Fri ·9:14 PM"),
        ("2026-11-05 12:00", "Closed Thursday · 9:14 PM - Friday"),
        ("2026-11-05 12:00", "Closed Thursday · 9:14 PM \u2013 Friday"),
        ("2026-11-05 12:00", "Closed Thursday · 9:14 PM (Friday)"),
        ("2026-11-05 12:00", "Closed Thursday · 9:14 PM · Friday"),
        ("2026-11-05 12:00", "Closed Thursday · 9:14 PM • Friday"),
        ("2026-11-05 12:00", "Closed Thursday · 9:14 PM; Friday"),
        ("2026-11-05 12:00", "Closed Thursday · 9:14 PM | Friday"),
        ("2026-11-05 12:00", "Closed Thursday · 9:14 PM / Friday"),
        # a clock time with no day after the read: an earlier day's (WD-R6C2-S1)
        ("2026-11-05 12:00", "Closed Thursday. Updated 7 AM"),
        ("2026-11-05 12:00", "Closed Thursday. Updated 07:00"),
        ("2026-11-05 12:00", "Closed Thursday. Posted @ 7:00"),
        ("2026-11-05 12:00", "Closed Thursday. Updated 11 PM"),
        ("2026-11-05 12:00", "Closed Thursday. Updated noon"),
        ("2026-11-05 12:00", "Closed Thursday. Updated 4:30 AM PT"),
        ("2026-11-05 12:00", "Closed Thursday · 7:14 AM"),
        ("2026-11-05 12:00", "Closed Thursday · 7 AM"),
        ("2026-11-05 12:00", "Closed Thursday | 7:14 AM"),
        ("2026-11-05 12:00", "Thursday: Closed. 7:14 AM"),
        ("2026-11-05 12:00", "Closed Thursday 7:14 AM"),
        ("2026-11-05 12:00", "Closed Thursday (7:14 AM)"),
        ("2026-11-06 12:00", "Friday: Closed 9:14 PM"),
        ("2026-11-06 12:00", "Closed Friday · 9:14 PM"),
        ("2026-11-05 03:00", "Closed Thursday. Updated 9:30 PM"),
        ("2026-11-05 03:00", "Closed Thursday. Updated 21:30"),
        ("2026-11-05 03:00", "Closed Thursday · 9:30 PM"),
        ("2026-11-05 03:00", "Thursday closed. 9:30 PM"),
        ("2026-11-05 07:00", "Closed Thursday. Updated 1:30 AM"),
        ("2026-11-05 12:00", "Closed Thursday. Posted this afternoon"),
        ("2026-11-05 12:00", "Closed Thursday. Posted this evening"),
        ("2026-11-05 12:00", "Closed Thursday. Posted tonight"),
        # more notice words (WD-R6C2-S2)
        ("2026-11-05 12:00", "Closed Thursday, update Friday"),
        ("2026-11-05 12:00", "Closed Thursday, news Friday"),
        ("2026-11-05 12:00", "Closed Thursday, decision made Friday"),
        ("2026-11-05 12:00", "Closed Thursday, sent to all families Friday"),
        ("2026-11-05 12:00", "Closed Thursday, notified all parents and staff Friday"),
        ("2026-11-05 12:00", "Closed Thursday. Friday release"),
        ("2026-11-05 12:00", "Closed Thursday. Friday text"),
        ("2026-11-05 12:00", "Closed Thursday. Friday notification"),
        ("2026-11-05 12:00", "Closed Thursday. Friday robocall"),
        ("2026-11-05 12:00", "Closed Thursday. Friday bulletin"),
        # decimal ages and an age after a clock time with seconds (WD-R6C2-S3)
        ("2026-11-05 12:00", "Closed Thursday · 1.5d"),
        ("2026-11-05 12:00", "Closed Thursday. Posted 1.5 days ago"),
        ("2026-11-05 12:00", "Closed Thursday,1.5d"),
        ("2026-11-05 12:00", "Closed Thursday 6:00:5d"),
        ("2026-11-05 12:00", "Closed Thursday 6:00.5d"),
        ("2026-11-05 12:00", "Closed Thursday 11/5,5d"),
        # a part of the day after "late", a bare "late" or "PM" (WD-R6C2-S4)
        ("2026-11-05 12:00", "Closed Thursday · Friday late evening"),
        ("2026-11-05 12:00", "Closed Thursday · Friday late night"),
        ("2026-11-05 12:00", "Closed Thursday · Friday late"),
        ("2026-11-05 12:00", "Closed Thursday · Friday PM"),
        ("2026-11-05 12:00", "Closed Thursday · Friday p.m."),
        ("2026-11-05 12:00", "Closed Thursday, Friday early"),
    ],
)
def test_round_6_second_critic_shapes_keep_the_hold(when: str, text: str) -> None:
    world = _cold(when, text)
    world.resolve()
    assert lit(world.publish(at(when) + timedelta(minutes=1))) == {}


@pytest.mark.parametrize(
    ("when", "text", "day", "status"),
    [
        # a start or a dismissal owns a clock time past a clause mark: the day lights
        ("2026-11-06 12:00", "Early dismissal Friday: 1:30 PM", FRIDAY, "EARLY_DISMISSAL"),
        ("2026-11-06 12:00", "Friday: Early dismissal 1:30 PM", FRIDAY, "EARLY_DISMISSAL"),
        ("2026-11-06 12:00", "Friday: 10 AM start", FRIDAY, "DELAYED"),
        ("2026-11-05 12:00", "Closed Thursday; offices open 8 AM - 4 PM", THURSDAY, "CLOSED"),
        # a stamp's day past a mark, the day before
        ("2026-11-05 12:00", "Closed Thursday | Wed | 9:14 PM", THURSDAY, "CLOSED"),
        # a clock time with no day at or before the read
        ("2026-11-05 12:00", "Closed Thursday · 5:14 AM", THURSDAY, "CLOSED"),
        ("2026-11-05 12:00", "Closed Thursday. Updated 5:14 AM", THURSDAY, "CLOSED"),
        ("2026-11-05 12:00", "Thursday: Closed. 5:14 AM", THURSDAY, "CLOSED"),
        ("2026-11-05 03:00", "Closed Thursday. Updated 8:30 PM", THURSDAY, "CLOSED"),
        ("2026-11-05 03:00", "Closed Thursday · 8:30 PM", THURSDAY, "CLOSED"),
        ("2026-11-05 12:00", "Closed Thursday. Posted this morning", THURSDAY, "CLOSED"),
        # a notice word as the heading, a status after a notice verb, an early release
        ("2026-11-05 12:00", "Update Thursday: closed", THURSDAY, "CLOSED"),
        ("2026-11-05 12:00", "District announced school closed Thursday", THURSDAY, "CLOSED"),
        ("2026-11-05 12:00", "Early release Thursday", THURSDAY, "EARLY_DISMISSAL"),
        # an age under a day, a delay's decimal length, a late start, a dismissal "PM"
        ("2026-11-05 12:00", "Closed Thursday · 1.5h", THURSDAY, "CLOSED"),
        ("2026-11-05 12:00", "Delayed Thursday 1.5 hr delay", THURSDAY, "DELAYED"),
        ("2026-11-05 12:00", "Thursday late start", THURSDAY, "DELAYED"),
        ("2026-11-05 12:00", "Early dismissal Thursday PM", THURSDAY, "EARLY_DISMISSAL"),
    ],
)
def test_round_6_second_critic_shapes_that_still_light(
    when: str, text: str, day: str, status: str
) -> None:
    world = _cold(when, text)
    world.resolve()
    assert lit(world.publish(at(when) + timedelta(minutes=1))) == {(0, day): status}


@pytest.mark.parametrize(
    ("text", "now", "named", "stamps"),
    [
        # past a clause mark, a weekday's clock time is a stamp's only
        ("Closed Thursday · Friday: 9:14 PM", THU_0600, {3}, (None,)),
        ("Closed Thursday · 9:14 PM (Friday)", THU_0600, {3}, (None,)),
        ("Closed Thursday · 9:14 PM; Friday", THU_0600, {3}, (None,)),
        ("Closed Thursday · Wed: 9:14 PM", THU_0600, {3}, (date(2026, 11, 4),)),
        ("Closed Thursday · 9:14 PM · Wed", THU_0600, {3}, (date(2026, 11, 4),)),
        ("Early dismissal Friday: 1:30 PM", THU_0600, {4}, ()),
        ("Delayed Thursday 10 AM | Friday closed", THU_0600, {3, 4}, ()),
        ("Closed Friday | 10 AM delay Saturday", THU_0600, {4, 5}, ()),
        # a clock time with no day: after the read it is an earlier day's, unreadable
        ("Closed Thursday · 7:14 AM", THU_0600, {3}, (None,)),
        ("Closed Thursday · 5:14 AM", THU_0600, {3}, ()),
        ("Closed Thursday. Updated 7 AM", THU_0600, {3}, (None,)),
        ("Closed Thursday. Updated 5:30 AM", THU_0600, {3}, ()),
        ("Closed Thursday. Updated 9:14 PM", THU_0600.replace(hour=21, minute=30), {3}, ()),
        ("Closed Thursday. Posted this evening", THU_0600, {3}, (None,)),
        ("Closed Thursday. Posted this morning", THU_0600, {3}, (date(2026, 11, 5),)),
        # owned, or in a clause with other words: no posting time
        ("Closed Thursday. Game at 7 PM", THU_0600, set(), ()),
        ("Closed Thursday. Updated Wed. 9:14 PM", THU_0600, {3}, (date(2026, 11, 4),)),
        ("Closed Thursday. Updated Nov. 5. 7:00 AM", THU_0600, {3}, (None,)),
        ("Closed Thursday; offices open 8 AM - 4 PM", THU_0600, {3}, ()),
        ("Delayed Thursday. Buses run 2 hours late, 10 AM start", THU_0600, {3}, ()),
    ],
)
def test_round_6_marks_and_clock_only_stamps(
    text: str, now: datetime, named: set[int], stamps: tuple[date | None, ...]
) -> None:
    assert named_weekdays(text, "", now.date()) == frozenset(named)
    assert stamp_dates(text, now.date(), now) == stamps


def test_a_clock_only_stamp_is_read_only_on_the_weekday_path() -> None:
    # the date path keeps its bound (WD-R6C2-S5 is the lead's): no clock-only stamp is read
    for text in ("Closed Nov. 5. Updated 7 AM", "Closed Nov. 5 · 7:14 AM"):
        assert stamp_dates(text, THU_0600.date(), THU_0600, clocked=False) == ()
    assert stamp_dates("Closed Nov. 5. Updated 7 AM", THU_0600.date(), THU_0600) == (None,)


@pytest.mark.parametrize(
    ("text", "named"),
    [
        ("Closed Thursday, update Friday", set()),
        ("Closed Thursday, decision made Friday", set()),
        ("Closed Thursday, notified all parents and staff Friday", set()),
        ("Closed Thursday. Friday text", set()),
        ("Closed Thursday · Friday late", set()),
        ("Closed Thursday · Friday PM", set()),
        ("Closed Thursday · Friday late evening", {3}),  # a stamp: a part of the day
        ("Update Thursday: closed", {3}),
        ("Early release Thursday", {3}),
        ("Early dismissal Thursday PM", {3}),
        ("Thursday late start", {3}),
        ("Open late Thursday", {3}),
    ],
)
def test_round_6_more_notice_and_bare_words(text: str, named: set[int]) -> None:
    assert named_weekdays(text, "", NOV5) == frozenset(named)


@pytest.mark.parametrize(
    ("text", "ages"),
    [
        ("Closed Thursday · 1.5d", (timedelta(days=1.5),)),
        ("Posted 1.5 days ago", (timedelta(days=1.5),)),
        ("Closed Thursday,1.5d", (timedelta(days=1.5),)),
        ("Closed Thursday · 1.5h", (timedelta(hours=1.5),)),
        ("Delayed Thursday 1.5 hr delay", ()),
        ("2.5 hr delay", ()),
        ("Closed Thursday 6:00:5d", (timedelta(days=5),)),
        ("Closed Thursday 6:00.5d", (timedelta(days=5),)),
        ("Closed Thursday 9:14:22 PM", ()),
        ("Closed Thursday 11/5,5d", (timedelta(days=5),)),
        ("1,440 students, 2,000 ft", ()),
        ("routes 2,3,4", ()),
    ],
)
def test_round_6_decimal_ages_and_ages_after_seconds(
    text: str, ages: tuple[timedelta, ...]
) -> None:
    assert post_ages(text) == ages


# --- round 7: spans, mark runs, void words, grouped ages ---------------------------------------


@pytest.mark.parametrize(
    ("when", "text"),
    [
        # a span of hours with no status or event word by its weekday is a stamp (WD-R6C3-B1):
        # it never lights the stamp's day, the day the row was posted
        ("2026-11-05 12:00", "Closed Wednesday · Thursday 9 AM - 3 PM"),
        ("2026-11-05 12:00", "Closed Wednesday · Thursday 8:30-3:15"),
        ("2026-11-05 12:00", "Closed Wednesday · Thursday 10 AM to 3 PM"),
        ("2026-11-05 12:00", "Closed Wednesday · Thursday 9 AM until 3 PM"),
        ("2026-11-05 12:00", "Closed Wednesday · Thursday 7 AM - 9 AM"),
        ("2026-11-05 12:00", "Closed Wed · Thu 9:00-11:00"),
        ("2026-11-05 12:00", "Wednesday closed, Thursday 7:45-2:45"),
        ("2026-11-05 12:00", "Closed Thursday · Friday 9 AM - 3 PM"),
        ("2026-11-05 12:00", "Closed Thursday · Friday 9:14-9:30 PM"),
        ("2026-11-05 12:00", "Closed Thursday · Friday 6 a.m. to 8 p.m."),
        ("2026-11-05 12:00", "Closed Thursday · Friday (9:14-9:30 PM)"),
        ("2026-11-05 12:00", "Closed Thursday · Friday: 9 AM - 3 PM"),
        ("2026-11-05 12:00", "Closed Thursday · 9 AM to 3 PM on Friday"),
        ("2026-11-05 12:00", "Closed Thursday · Friday 9 AM until 3 PM"),
        # any run of marks between a weekday and its clock time is a stamp mark (WD-R6C3-B2)
        ("2026-11-05 12:00", "Closed Wednesday · Thursday::5:14 AM"),
        ("2026-11-05 12:00", "Closed Wednesday · 5:14 AM-- Thursday"),
        ("2026-11-05 12:00", "Closed Wednesday · Thursday...6:14 AM"),
        ("2026-11-05 12:00", "Closed Thursday · Friday...9:14 PM"),
        ("2026-11-05 12:00", "Closed Thursday · Friday::9:14 PM"),
        ("2026-11-05 12:00", "Closed Thursday · 9:14 PM-- Friday"),
        ("2026-11-05 12:00", "Closed Thursday · 9:14 PM- Friday"),
        ("2026-11-05 12:00", "Closed Thursday · 9:14 PM\u2013 Friday"),
        ("2026-11-05 12:00", "Closed Thursday · 9:14 PM\u2014 Friday"),
        ("2026-11-05 12:00", "Closed Thursday · Friday _9:14 PM"),
        ("2026-11-05 12:00", "Closed Thursday · Friday,.9:14 PM"),
        ("2026-11-05 12:00", "Closed Thursday · Friday:/9:14 PM"),
        ("2026-11-05 12:00", "Closed Thursday · Friday)/9:14 PM"),
        ("2026-11-05 12:00", "Closed Thursday · Friday(:9:14 PM"),
        ("2026-11-05 12:00", "Closed Thursday · Friday~/9:14 PM"),
        ("2026-11-05 12:00", "Closed Thursday · Friday*:9:14 PM"),
        ("2026-11-05 12:00", "Closed Thursday · Friday…/9:14 PM"),
        ("2026-11-05 12:00", "Closed Thursday · Friday=:9:14 PM"),
        ("2026-11-05 12:00", "Closed Thursday · Friday ,.: 9:14 PM"),
        ("2026-11-05 12:00", "Closed Thursday · Fri::2114"),
        ("2026-11-05 12:00", "Closed Thursday @ 9:14 PM"),
        ("2026-11-05 12:00", 'Closed Thursday "9:14 PM"'),
        # glued decimal and grouped ages, and "dys" (WD-R6C3-S1)
        ("2026-11-05 12:00", "Closed Thursday.1.5d"),
        ("2026-11-05 12:00", "Closed Thursday.2.5 days"),
        ("2026-11-05 12:00", "Closed Thursday · 2,880 min"),
        ("2026-11-05 12:00", "Closed Thursday · 2,880m"),
        ("2026-11-05 12:00", "Closed Thursday · 5dys"),
        # void and old-post words in either order (WD-R6C3-S2)
        ("2026-11-05 12:00", "Revoked. Closed Thursday"),
        ("2026-11-05 12:00", "Withdrawn. Closed Thursday"),
        ("2026-11-05 12:00", "Closed Thursday rescinded"),
        ("2026-11-05 12:00", "Closed Thursday (old)"),
        ("2026-11-05 12:00", "Old. Closed Thursday"),
        ("2026-11-05 12:00", "Archived. Closed Thursday"),
        ("2026-11-05 12:00", "Past event. Closed Thursday"),
        ("2026-11-05 12:00", "Closed Thursday past event"),
        ("2026-11-05 12:00", "Not in effect. Closed Thursday"),
        ("2026-11-05 12:00", "Sent in error. Closed Thursday"),
        ("2026-11-05 12:00", "Closed Thursday nevermind"),
        ("2026-11-05 12:00", "Closed Thursday ignore previous"),
        ("2026-11-05 12:00", "Update: open. Closed Thursday"),
        ("2026-11-05 12:00", "Update - school open. Closed Thursday"),
        ("2026-11-05 12:00", "Closed Thursday school is in session"),
        ("2026-11-05 12:00", "Closed Nov. 5. Revoked"),
        # a notice word or a weekday's first letters by a lone clock time (WD-R6C3-S3)
        ("2026-11-05 12:00", "Closed Thursday. 7:14 AM update"),
        ("2026-11-05 12:00", "Closed Thursday. Released 7:14 AM"),
        ("2026-11-05 12:00", "Closed Thursday | Fr 9:14 PM"),
    ],
)
def test_round_7_shapes_keep_the_hold(when: str, text: str) -> None:
    world = _cold(when, text)
    world.resolve()
    assert lit(world.publish(at(when) + timedelta(minutes=1))) == {}


@pytest.mark.parametrize(
    ("when", "text", "days"),
    [
        # a status word by the weekday or right before the span owns it: the day still lights
        (
            "2026-11-05 12:00",
            "Closed Thursday · Friday 9 AM - 3 PM closed",
            {THURSDAY: "CLOSED", FRIDAY: "CLOSED"},
        ),
        ("2026-11-06 12:00", "Early dismissal Friday 1:30-2 PM", {FRIDAY: "EARLY_DISMISSAL"}),
        ("2026-11-06 12:00", "Closed 6 a.m. to 8 p.m. on Friday", {FRIDAY: "CLOSED"}),
        ("2026-11-06 12:00", "6 a.m. to 8 p.m. on Friday: closed", {FRIDAY: "CLOSED"}),
        ("2026-11-05 12:00", "Early dismissal Thursday: 1:30 PM", {THURSDAY: "EARLY_DISMISSAL"}),
        # two weekdays a status word is said with, ages under a day, a dated stamp of the day
        ("2026-11-05 12:00", "Closed Thursday and Friday", {THURSDAY: "CLOSED", FRIDAY: "CLOSED"}),
        (
            "2026-11-05 12:00",
            "Thursday: Closed. Friday: 2 hour delay",
            {THURSDAY: "CLOSED", FRIDAY: "DELAYED"},
        ),
        ("2026-11-05 12:00", "Closed Thursday · 1,200 m", {THURSDAY: "CLOSED"}),
        ("2026-11-05 12:00", "Closed Thursday. Updated 11/05", {THURSDAY: "CLOSED"}),
        ("2026-11-05 12:00", "Update: Closed Thursday", {THURSDAY: "CLOSED"}),
        ("2026-11-05 12:00", "2 hour delay Thursday, 10 AM start", {THURSDAY: "DELAYED"}),
    ],
)
def test_round_7_shapes_that_still_light(when: str, text: str, days: dict[str, str]) -> None:
    world = _cold(when, text)
    world.resolve()
    assert lit(world.publish(at(when) + timedelta(minutes=1))) == {
        (0, day): status for day, status in days.items()
    }


@pytest.mark.parametrize(
    ("text", "named", "stamps"),
    [
        # a span with no status word by its weekday: a stamp, read as one
        ("Closed Wednesday · Thursday 9 AM - 3 PM", {2}, (None,)),
        ("Closed Thursday · Friday: 9 AM - 3 PM", {3}, (None,)),
        ("Closed Wednesday · Thursday 7:45-9:00 AM", {2}, (None,)),
        # a span of hours is no time a row went up at: its stamp is unreadable (round 8)
        ("Closed Wednesday · Thursday 5 AM - 3 PM", {2}, (None,)),
        # owned by a status word in its clause, around the span or a heading after it
        ("Closed Thursday · Friday closed 9 AM - 3 PM", {3, 4}, ()),
        ("Closed Thursday · Friday 9 AM - 3 PM closed", {3, 4}, ()),
        ("6 a.m. to 8 p.m. on Thursday: closed", {3}, ()),
        ("Thursday 7:45-2:45, closed Wednesday", {2}, (None,)),
        # a run of marks, either way round
        ("Closed Thursday · Friday...9:14 PM", {3}, (None,)),
        ("Closed Thursday · 9:14 PM-- Wed", {3}, (date(2026, 11, 4),)),
        ("Closed Thursday · Wed::9:14 PM", {3}, (date(2026, 11, 4),)),
        ("Closed Thursday · Wed _9:14 PM", {3}, (date(2026, 11, 4),)),
        # past a run of marks and owned by nothing, a clock time has no day
        ("Closed Thursday @ 9:14 PM", {3}, (None,)),
        ("Closed Thursday @ 5:14 AM", {3}, (date(2026, 11, 5),)),
        ('Closed Thursday "9:14 PM"', {3}, (None,)),
        ("Closed Thursday · 9:14 PM Wed", {3}, (date(2026, 11, 4),)),
    ],
)
def test_round_7_spans_and_mark_runs(
    text: str, named: set[int], stamps: tuple[date | None, ...]
) -> None:
    assert named_weekdays(text, "", THU_0600.date()) == frozenset(named)
    assert stamp_dates(text, THU_0600.date(), THU_0600) == stamps


@pytest.mark.parametrize(
    "marks",
    [
        "".join(run)
        for size in (1, 2, 3)
        for run in __import__("itertools").product(".:/,(-_~|", repeat=size)
    ],
)
def test_round_7_no_run_of_marks_lights_a_stamp_day(marks: str) -> None:
    # the whole class at the function level: a stamp's weekday with its clock time past any
    # run of up to three marks, either way round and spaced or glued, is never a status day
    for gap in ("", " "):
        for text in (
            f"Closed Thursday · Friday{gap}{marks}{gap}9:14 PM",
            f"Closed Thursday · 9:14 PM{gap}{marks}{gap}Friday",
            f"Closed Wednesday · Thursday{gap}{marks}{gap}5:14 AM",
            f"Closed Wednesday · 5:14 AM{gap}{marks}{gap}Thursday",
        ):
            named = named_weekdays(text, "", THU_0600.date())
            stamp_weekday = 4 if "Friday" in text else 3
            assert stamp_weekday not in named or None in stamp_dates(
                text, THU_0600.date(), THU_0600
            ), text


@pytest.mark.parametrize(
    ("text", "ages"),
    [
        ("Closed Thursday.1.5d", (timedelta(days=1.5),)),
        ("Closed Thursday.2.5 days", (timedelta(days=2.5),)),
        ("Closed Thursday · 2,880 min", (timedelta(days=2),)),
        ("Closed Thursday · 2,880m", (timedelta(days=2),)),
        ("Posted 1,440 min ago", (timedelta(days=1),)),
        ("Closed Thursday · 1,200 m", (timedelta(hours=20),)),
        ("Closed Thursday · 5dys", (timedelta(days=5),)),
        ("Closed Thursday · 5dy", (timedelta(days=5),)),
        # never a decimal after a number's "." nor a group after money or a mark
        ("Closed 11.1.5d", ()),
        ("$1,500 m raised", ()),
        ("1,440 students, 2,000 ft", ()),
    ],
)
def test_round_7_glued_decimal_and_grouped_ages(text: str, ages: tuple[timedelta, ...]) -> None:
    assert post_ages(text) == ages


@pytest.mark.parametrize(
    ("text", "named"),
    [
        ("Revoked. Closed Thursday", set()),
        ("Reversed. Closed Thursday", set()),
        ("Closed Thursday withdrawn", set()),
        ("Closed Thursday (old)", set()),
        ("Closed Thursday [OLD]", set()),
        ("Old. Closed Thursday", set()),
        ("Closed Thursday · archived", set()),
        ("Closed Thursday past event", set()),
        ("Closed Thursday - not in effect", set()),
        ("Closed Thursday, sent in error", set()),
        ("Never mind: closed Thursday", set()),
        ("Please disregard. Closed Thursday", set()),
        ("Update - school open. Closed Thursday", set()),
        ("Closed Thursday open on time", set()),
        ("Posted Wednesday: ignore. Closed Thursday", set()),
        # the same letters in other words name the day as before
        ("Old Mill school closed Thursday", {3}),
        ("Closed Thursday for the past storm", {3}),
        ("UPDATE: Closed Thursday", {3}),
        ("Closed Thursday, all past due fees waived", {3}),
    ],
)
def test_round_7_void_words(text: str, named: set[int]) -> None:
    assert named_weekdays(text, "", NOV5) == frozenset(named)


def test_round_7_void_words_hold_on_the_date_path() -> None:
    assert names_date("Closed Nov. 5", NOV5)
    assert not names_date("Closed Nov. 5 (old)", NOV5)
    assert not names_date("Rescinded: closed Nov. 5", NOV5)


# --- round 7, critic round 1: spans and clocks past words or marks, long runs, spaces -------

_R7C1_HOLD = [
    # a span or clock time in a weekday's clause, or past its marks, with no status or event
    # word there: the weekday is a stamp, never a status day (WD-R7C1-B1)
    "Closed Wednesday · Thursday hours 8:30-3:15",
    "Closed Wednesday · Thursday hrs 8:30-3:15",
    "Closed Wednesday · Thursday times 8:30-3:15",
    "Closed Wednesday · Thursday by 8:30-3:15",
    "Closed Wednesday · Thursday office hours 8:30-3:15",
    "Closed Wednesday · Thursday school hours 8:30-3:15",
    "Closed Wednesday · Thursday hours 9:00-11:00",
    "Closed Wednesday · Thursday hours 1:00-3:00 PM",
    "Closed Wednesday · Thursday hours 9 AM until 3 PM",
    "Closed Wednesday · Thursday: from 9 AM to 3 PM",
    "Closed Wednesday · Thursday, from 9 AM to 3 PM",
    "Closed Wednesday · Thursday | from 9 AM - 3 PM",
    "Closed Wednesday · Thursday | from approx. 9 AM - 3 PM",
    "Closed Wednesday · Thursday hours: 9 AM - 3 PM",
    "Closed Wednesday · 9 AM - 3 PM: hours Thursday",
    "Closed Wednesday · 8:30-3:15 hours on Thursday",
    "Closed Thursday · Friday hours 8:30-3:15",
    "Closed Thursday · Friday: from 9 AM to 3 PM",
    "Closed Thursday · Friday | hours 9 AM - 3 PM",
    "Closed Thursday · Friday: between 9 AM and 3 PM",
    # bare hours, clock times with a leading zero or cut short (WD-R7C1-S1)
    "Closed Wednesday · Thursday: 9 to 3",
    "Closed Wednesday · 9 to 3 on Thursday",
    "Closed Wednesday · Thursday: 0900-1500",
    "Closed Wednesday · Thursday 0900",
    "Closed Wednesday · Thursday 0514 hrs",
    "Closed Thursday · Friday: 9 - 3",
    "Closed Thursday · Friday 0900",
    "Closed Thursday · Friday: 9 a",
    # a run of five or more marks (WD-R7C1-S2) and Unicode spaces (WD-R7C1-S3)
    "Closed Wednesday · 5:14 AM ----- Thursday",
    "Closed Wednesday · Thursday .......... 5:14 AM",
    "Closed Thursday · Friday ---------- 9:14 PM",
    "Closed Wednesday · Thursday\u00a05:14 AM",
    "Closed Wednesday · Thursday:\u20095:14 AM",
    "Closed Wednesday · 5:14\u202fAM Thursday",
    "Closed Wednesday · 5:14 AM\u3000Thursday",
    # a stamp word after the weekday (WD-R7C1-S4)
    "Closed Wednesday · Thursday posted 5:14 AM",
    "Closed Wednesday · Thursday. Posted 5:14 AM",
    "Closed Wednesday · Thursday hours 5:14 AM",
    "Closed Wednesday · Thursday issued 5:14 AM",
    "Closed Thursday · Friday posted 9 PM",
    # a lone clock time with no start, delay, dismissal or event word; a correction; ages a
    # day long or that cannot be read exactly (WD-R7C1-S5)
    "Closed Thursday. 7:14 AM upd",
    "Closed Thursday. 7:14 AM revised",
    "Closed Thursday. 7:14 AM edit",
    "Closed Thursday. 7:14 AM by admin",
    "Closed Thursday. 7:14 AM entry",
    "Closed Thursday. 7:14 AM tweet",
    "Closed Thursday. 7:14 AM report",
    "Closed Thursday. 7:14 AM info",
    "Correction: open. Closed Thursday",
    "Correction - Closed Thursday",
    "Closed Thursday · 1.440 min",
    "Closed Thursday · 1 440 min",
    "Closed Thursday · 86,400 s",
    "Closed Thursday · 1 - 2w",
]


@pytest.mark.parametrize(
    ("when", "text"),
    [
        *(("2026-11-05 12:00", text) for text in _R7C1_HOLD),
        # the evening path: tomorrow is no stamp's day either
        ("2026-11-05 01:00", "Closed Tuesday · Wednesday hours 8:30-3:15"),
        ("2026-11-06 01:00", "Closed Thursday · Friday office hours 9:00-11:00"),
    ],
)
def test_round_7_critic_shapes_keep_the_hold(when: str, text: str) -> None:
    world = _cold(when, text)
    world.resolve()
    assert lit(world.publish(at(when) + timedelta(minutes=1))) == {}


@pytest.mark.parametrize(
    ("when", "text", "days"),
    [
        # a status or event word by the weekday owns its span or clock time
        ("2026-11-06 12:00", "Early dismissal Friday hours 1:30-2 PM", {FRIDAY: "EARLY_DISMISSAL"}),
        ("2026-11-05 12:00", "Closed Thursday hours 8:30-3:15", {THURSDAY: "CLOSED"}),
        ("2026-11-05 12:00", "Thursday: closed. Office hours 9 AM - 3 PM", {THURSDAY: "CLOSED"}),
        # a weekday with words before it in its clause is no stamp's day
        ("2026-11-05 12:00", "Closed Thursday, updated 5:00 AM", {THURSDAY: "CLOSED"}),
        ("2026-11-05 12:00", "Snow day Thursday. Updated 5:00 AM", {THURSDAY: "CLOSED"}),
        # a clock time with a start, an office or a school by it is the day's, not a post's
        ("2026-11-05 12:00", "Closed Thursday. 5:14 AM update", {THURSDAY: "CLOSED"}),
        (
            "2026-11-05 06:48",
            "Thursday Morning: 2 hour delay, classes start at 10:15am, front office at 9:50am",
            {THURSDAY: "DELAYED"},
        ),
        (
            "2026-11-05 12:00",
            "2 hour delay Thursday; 10:40 a.m. for Gamma Middle; 10:50 a.m. for Delta Elementary",
            {THURSDAY: "DELAYED"},
        ),
        # a span of something else than hours names its weekday as before
        (
            "2026-11-05 12:00",
            "Due to 0-5 degree wind chills on Thursday, all schools open 2 hours late",
            {THURSDAY: "DELAYED"},
        ),
    ],
)
def test_round_7_critic_shapes_that_still_light(when: str, text: str, days: dict[str, str]) -> None:
    world = _cold(when, text)
    world.resolve()
    assert lit(world.publish(at(when) + timedelta(minutes=1))) == {
        (0, day): status for day, status in days.items()
    }


def _a_stamp_day_lights(text: str, weekday: int) -> bool:
    """Whether ``text``, read Thursday at 06:00, names ``weekday`` as a status day with no
    stamp that keeps the row held."""
    return weekday in named_weekdays(text, "", THU_0600.date()) and None not in stamp_dates(
        text, THU_0600.date(), THU_0600
    )


@pytest.mark.parametrize(
    "mark", ["", ":", " :", " |", ",", " ·", " -", " \u2013", ".", ";", " (", " -----", "\u00a0"]
)
def test_round_7_critic_no_span_or_clock_by_a_weekday_names_its_day(mark: str) -> None:
    # the class at the function level: a weekday with a span or a clock time after it or
    # before it, past any marks and any words that are no status or event word, is no day
    for between in ("", "hours", "office hours", "school hours", "by", "from", "between", "posted"):
        gap = f"{mark} {between} " if between else f"{mark} "
        for span in (
            "8:30-3:15",
            "9 AM - 3 PM",
            "9 AM until 3 PM",
            "9 to 3",
            "0900-1500",
            "5:14 AM",
        ):
            for lead, day, weekday in (
                ("Closed Wednesday · ", "Thursday", 3),
                ("Closed Thursday · ", "Friday", 4),
            ):
                after = f"{lead}{day}{gap}{span}"
                before = f"{lead}{span}{gap}{'' if mark else 'on '}{day}"
                assert not _a_stamp_day_lights(after, weekday), after
                assert not _a_stamp_day_lights(before, weekday), before


@pytest.mark.parametrize(
    "run", ["-----", "..........", "_______", "· · · · · ·", "-.-.-.-", "=====>", "~~~~~~~~~~~~"]
)
def test_round_7_critic_a_long_run_of_marks_is_a_stamp_mark(run: str) -> None:
    for gap in ("", " "):
        for text, weekday in (
            (f"Closed Thursday · Friday{gap}{run}{gap}9:14 PM", 4),
            (f"Closed Thursday · 9:14 PM{gap}{run}{gap}Friday", 4),
            (f"Closed Wednesday · Thursday{gap}{run}{gap}5:14 AM", 3),
            (f"Closed Wednesday · 5:14 AM{gap}{run}{gap}Thursday", 3),
        ):
            assert not _a_stamp_day_lights(text, weekday), text


@pytest.mark.parametrize(
    "space",
    ["\u00a0", "\u1680", "\u2002", "\u2007", "\u2009", "\u200a", "\u202f", "\u205f", "\u3000"],
)
def test_round_7_critic_a_unicode_space_is_a_space(space: str) -> None:
    for text, weekday in (
        (f"Closed Wednesday · Thursday{space}5:14 AM", 3),
        (f"Closed Wednesday · Thursday:{space}5:14 AM", 3),
        (f"Closed Wednesday · 5:14{space}AM{space}Thursday", 3),
        (f"Closed Thursday · Friday{space}9:14{space}PM", 4),
    ):
        assert not _a_stamp_day_lights(text, weekday), text
    assert named_weekdays(f"Closed{space}Thursday", "", NOV5) == frozenset({3})


@pytest.mark.parametrize(
    ("text", "named", "stamps"),
    [
        # a weekday right before a stamp word, starting its clause, is the stamp's day
        ("Closed Wednesday · Thursday posted 5:14 AM", {2}, (date(2026, 11, 5),)),
        ("Closed Wednesday · Thursday - updated 5:14 AM", {2}, (date(2026, 11, 5),)),
        ("Closed Thursday · Friday posted 9 PM", {3}, (None,)),
        ("Closed Thursday · Wednesday posted 9:14 PM", {3}, (date(2026, 11, 4),)),
        # with a word before it, the day the row is for, as before
        ("Closed Thursday, updated 5:00 AM", {3}, ()),
        ("Snow day Thursday. Updated 5:00 AM", {3}, ()),
        # a span of hours as a stamp gives no time a row went up at
        ("Closed Wednesday · Thursday hours 7:45-9:00", {2}, (None,)),
        ("Closed Wednesday · Thursday: 4 to 5", {2}, (None,)),
        # a span of something else is no span of hours
        ("Closed Thursday · 0-5 degrees", {3}, ()),
        ("Closed Thursday · 2 to 4 inches", {3}, ()),
        # more than sixteen weekdays are a schedule: no day, and no stamp read
        ("Closed " + "Thursday, " * 17, set(), (None,)),
        ("Closed Thursday, Thursday, Thursday", {3}, ()),
    ],
)
def test_round_7_critic_stamp_days_spans_and_schedules(
    text: str, named: set[int], stamps: tuple[date | None, ...]
) -> None:
    assert named_weekdays(text, "", THU_0600.date()) == frozenset(named)
    assert stamp_dates(text, THU_0600.date(), THU_0600) == stamps


@pytest.mark.parametrize(
    ("text", "ages"),
    [
        # thousands grouped with a "." or a space may be a day or a minute and a half
        ("Closed Thursday · 1.440 min", (None,)),
        ("Closed Thursday · 1 440 min", (None,)),
        # seconds, grouped or of four digits or more
        ("Closed Thursday · 86,400 s", (timedelta(days=1),)),
        ("Closed Thursday · 3600 sec", (timedelta(hours=1),)),
        ("Closed Thursday · 86,400s", (timedelta(days=1),)),
        ("Temps in the 30s; the 1990s", ()),
        # the end of a span of lengths cannot be read exactly; a delay's is no age
        ("Closed Thursday · 1 - 2w", (None,)),
        ("Closed Thursday · 9 to 3 hours", (None,)),
        ("Delayed 2 to 3 hours Thursday", ()),
        ("Thursday 3-6 hours", ()),
    ],
)
def test_round_7_critic_ages(text: str, ages: tuple[timedelta | None, ...]) -> None:
    assert post_ages(text) == ages


@pytest.mark.parametrize(
    "text",
    [
        "Correction: open. Closed Thursday",
        "Correction - Closed Thursday",
        "Closed Thursday (corrected)",
    ],
)
def test_round_7_critic_a_correction_holds(text: str) -> None:
    assert not named_weekdays(text, "", NOV5)
    assert not names_date(text.replace("Thursday", "Nov. 5"), NOV5)


# --- round 7, critic round 2: clauses past the connector, glued spans, weak owners ----------

_R7C2_HOLD = [
    # past the weekday's marks, a span or clock time further on, over words and marks with no
    # status or event word, makes the weekday a stamp (WD-R7C2-B1)
    "Closed Wednesday · Thursday | hours (8:30-3:15)",
    "Closed Wednesday · Thursday: hours (9 AM - 3 PM)",
    "Closed Wednesday · Thursday, hours (9 AM to 3 PM)",
    "Closed Wednesday · Thursday | from (9 AM - 3 PM)",
    "Closed Wednesday · Thursday | from (9:14-9:30 PM)",
    "Closed Wednesday · Thursday | hours (9:14-9:30 PM)",
    "Closed Wednesday · Thursday: hours - 8:30-3:15",
    "Closed Wednesday · Thursday: hours. 8:30-3:15",
    "Closed Wednesday · Thursday | hours: 8:30-3:15",
    "Closed Wednesday · Thursday | hours | 8:30-3:15",
    "Closed Wednesday · Thursday | office | hours 8:30-3:15",
    "Closed Wednesday · Thursday: office (8:30-3:15)",
    "Closed Wednesday · Thursday | hours (5:14 AM)",
    "Closed Wednesday · (8:30-3:15) | hours | Thursday",
    "Closed Wednesday · between 9 and 3 hours Thursday",
    "Closed Thursday · Friday | hours (9 AM - 3 PM)",
    "Closed Thursday · Friday | from (9:14-9:30 PM)",
    # a span or a bare number right past a run of marks, glued to it too (WD-R7C2-B2)
    "Closed Wednesday · Thursday:9 to 3",
    "Closed Wednesday · Thursday...9 to 3",
    "Closed Wednesday · Thursday...9 - 3",
    "Closed Wednesday · Thursday//9 to 3",
    "Closed Wednesday · Thursday...between 9 and 3",
    "Closed Wednesday · Thursday:between 9 and 3",
    "Closed Wednesday · Thursday?:9 to 3",
    "Closed Wednesday · Thu✔/9 to 3",
    "Closed Wednesday · Thursday...9",
    "Closed Wednesday · Thursday ... 9",
    "Closed Wednesday · 9 to 3_ Thursday",
    "Closed Wednesday · noon_ °.Thursday",
    "Closed Thursday · Friday!#9 to 3",
    "Closed Thursday · Friday+ _9 to 3",
    "Closed Thursday · Friday#between 9 and 3",
    "Closed Thursday\nFriday ● ,9 to 3",
    "Closed Thursday; 0900: } Friday",
    # a weekday glued to a "_" is no day the words can be read for
    "Closed Thursday · 5:14 AM| . ► _Friday",
    # "report" and "arrival" own no clock time on their own (WD-R7C2-S1)
    "Closed Wednesday · Thursday report 5:14 AM",
    "Closed Wednesday · Thursday arrival 7:45 AM",
    "Closed Thursday · Friday report 9:14 PM",
    "Closed Thursday · Friday report 0900-1500",
    "Closed Thursday • 8:30-3:15 report Friday",
    # spans cut short or written with an "h", on either side (WD-R7C2-S2)
    "Closed Thursday • 9a-3p >> Friday",
    "Closed Wednesday • 9a-3p at Thursday",
    "Closed Thursday · 9a-3p hours (Friday",
    "Closed Wednesday · Thursday time 8h30-15h15",
    "Closed Wednesday • 8h30-15h15: Thursday",
]


@pytest.mark.parametrize(
    ("when", "text"),
    [
        *(("2026-11-05 12:00", text) for text in _R7C2_HOLD),
        # the evening path: tomorrow is no stamp's day either
        ("2026-11-05 01:00", "Closed Wednesday · Thursday | hours (9:14-9:30 PM)"),
        ("2026-11-05 01:00", "Closed Wednesday · Thursday|,9 to 3"),
        ("2026-11-05 01:00", "Closed Wednesday · Thursday =¶\\,between 9 and 3"),
    ],
)
def test_round_7_second_critic_shapes_keep_the_hold(when: str, text: str) -> None:
    world = _cold(when, text)
    world.resolve()
    assert lit(world.publish(at(when) + timedelta(minutes=1))) == {}


@pytest.mark.parametrize(
    ("when", "text", "days"),
    [
        # a status word in the weekday's clause owns its span or clock time past the marks
        ("2026-11-05 12:00", "Thursday: closed (9 AM - 3 PM)", {THURSDAY: "CLOSED"}),
        ("2026-11-05 12:00", "Thursday: closed (between 9 and 3)", {THURSDAY: "CLOSED"}),
        ("2026-11-05 12:00", "Thursday | closed | 8:30-3:15", {THURSDAY: "CLOSED"}),
        ("2026-11-06 12:00", "Early dismissal Friday | (1:30 PM)", {FRIDAY: "EARLY_DISMISSAL"}),
        # a glued span with a status word is read as a spaced one
        ("2026-11-05 12:00", "Closed Thursday: 9 to 3", {THURSDAY: "CLOSED"}),
        ("2026-11-05 12:00", "Closed Thursday:9 to 3", {THURSDAY: "CLOSED"}),
        # the evening path
        ("2026-11-05 01:00", "Thursday: closed (9 AM - 3 PM)", {THURSDAY: "CLOSED"}),
    ],
)
def test_round_7_second_critic_shapes_that_still_light(
    when: str, text: str, days: dict[str, str]
) -> None:
    world = _cold(when, text)
    world.resolve()
    assert lit(world.publish(at(when) + timedelta(minutes=1))) == {
        (0, day): status for day, status in days.items()
    }


_R7C2_SPANS = (
    "9 to 3",
    "between 9 and 3",
    "9 - 3",
    "9a-3p",
    "8h30-15h15",
    "(9:14-9:30 PM)",
    "8:30-3:15",
)
_R7C2_MARKS = ".,:;!?-/|\\()[]{}<>'`~@#$^&*_+=·•…►✔"


def _r7c2_shapes(run: str, span: str) -> Iterator[tuple[str, int]]:
    """Each shape of ``span`` and a weekday with the run of marks ``run`` between, either way
    round, glued or spaced, with the other weekday's status before: the weekday it names."""
    for lead, day, weekday in (
        ("Closed Wednesday · ", "Thursday", 3),
        ("Closed Thursday · ", "Friday", 4),
    ):
        for text in (
            f"{lead}{day}{run}{span}",
            f"{lead}{day} {run}{span}",
            f"{lead}{span}{run}{day}",
            f"{lead}{span}{run} {day}",
        ):
            yield text, weekday


@pytest.mark.parametrize("gap", ["", " "])
@pytest.mark.parametrize("size", [1, 2, 3])
def test_round_7_second_critic_no_run_of_marks_by_a_span_names_its_day(size: int, gap: str) -> None:
    # the class at the function level: one, two or three marks (of 33, every pair, and every
    # triple of the first 10), glued or spaced, between a weekday and a span of hours either way
    # round, read Thursday at 06:00, never light the weekday; each run is read with one of the
    # spans in turn (8,712 shapes of two marks for each gap)
    pool = _R7C2_MARKS if size < 3 else _R7C2_MARKS[:10]
    for index, combo in enumerate(itertools.product(pool, repeat=size)):
        run = gap.join(combo)
        for text, weekday in _r7c2_shapes(run, _R7C2_SPANS[index % len(_R7C2_SPANS)]):
            assert not _a_stamp_day_lights(text, weekday), text


@pytest.mark.parametrize(
    "between",
    ["hours", "hrs", "times", "from", "between", "by", "office", "at", "around", "office hours"],
)
def test_round_7_second_critic_a_span_past_a_connector_and_more_marks_names_no_day(
    between: str,
) -> None:
    marks = ("", ":", " |", ",", " ·", " -", ".", " (", ";", " /", " •", " >>", " [")
    for first, second in itertools.product(marks, repeat=2):
        for span in ("8:30-3:15", "9 AM - 3 PM", "(9:14-9:30 PM)", "9 to 3", "5:14 AM", "9a-3p"):
            for lead, day, weekday in (
                ("Closed Wednesday · ", "Thursday", 3),
                ("Closed Thursday · ", "Friday", 4),
            ):
                after = f"{lead}{day}{first} {between}{second} {span}"
                before = f"{lead}{span}{first} {between}{second} {day}"
                assert not _a_stamp_day_lights(after, weekday), after
                assert not _a_stamp_day_lights(before, weekday), before


@pytest.mark.parametrize(
    ("text", "named"),
    [
        # a status or event word on the way keeps the weekday a status day, as before
        ("Thursday | closed | 8:30-3:15", {3}),
        ("Thursday: closed (9 AM - 3 PM)", {3}),
        ("Early dismissal Friday | (1:30 PM)", {4}),
        ("Closed Thursday:9 to 3", {3}),
        # a status word makes a call a time on that day; who reports past the weekday's marks,
        # with no status word, owns no clock time there (WD-R7C3-B1)
        ("Thursday: students report 10 AM", set()),
        ("2 hour delay Thursday, staff report 9 AM", {3}),
        # "in effect" and "begins" still own a clock time
        ("Parking ban in effect at 5 p.m. Saturday", {5}),
        # a weekday glued to a "_" names no day
        ("Closed_Thursday", set()),
        ("Closed Thursday · 5:14 AM _Friday", set()),
        ("Closed Thursday_ 5:14 AM", set()),
    ],
)
def test_round_7_second_critic_status_days(text: str, named: set[int]) -> None:
    assert named_weekdays(text, "", THU_0600.date()) == frozenset(named)


@pytest.mark.parametrize(
    ("text", "ages"),
    [
        # the end of "between" two numbers is the end of a span: no exact age
        ("Closed Wednesday · between 9 and 3 hours Thursday", (None,)),
        ("Closed Thursday, posted between 2 and 3 hours ago", (None,)),
        # a delay's is still no age
        ("Delayed between 1 and 2 hours Thursday", ()),
    ],
)
def test_round_7_second_critic_ages(text: str, ages: tuple[timedelta | None, ...]) -> None:
    assert post_ages(text) == ages


# --- round 8: owner words own a single own-clause clock; bare numbers by a mark run --------

_R8_HOLD = [
    # owner words that are no status word own no span and no clock past the marks (WD-R7C3-B1)
    "Closed Wednesday · Thursday | begins (8:30-3:15)",
    "Closed Wednesday · Thursday in effect 9 to 3",
    "Closed Wednesday · Thursday | effective (9:14-9:30 PM)",
    "Closed Wednesday · Thursday | students report (9 AM)",
    "Closed Wednesday · Thursday: staff report 9:14 PM",
    "Closed Thursday · Friday in effect 9 AM - 3 PM",
    "Closed Wednesday · 9 to 3 in effect Thursday",
    "Closed Wednesday · 9 to 3 students arrive Thursday",
    "Closed Wednesday · 8:30-3:15 | teachers arrive Thursday",
    "Closed Wednesday · Thursday: teachers arrive 9:14 PM",
    # a bare number on either side of a weekday's run of marks (WD-R7C3-B2)
    "Closed Wednesday · 10.Thursday",
    "Closed Wednesday · 9...Thursday",
    "Closed Wednesday · 9:: Thursday",
    "Closed Wednesday · Thursday: 9 | info",
    "Closed Thursday · 9...Friday",
    "Closed Wednesday · 3_ Thursday · info",
    "Closed Wednesday · Thursday ... 12 notes",
    "Closed Thursday · Friday | 7 update",
    # a non-status owner word owns no clock time past a mark, wherever it stands: before the
    # weekday, or after the clock time on either side, or with a mark that ends no clause, as
    # WD-R8C1-B1 found
    "Closed Wednesday · in effect Thursday: 9:14 PM",
    "Closed Wednesday · 9:14 PM: Thursday begins",
    "Closed Wednesday · Thursday: 9:14 PM begins",
    "Closed Wednesday · Thursday: 9:14 PM effective immediately",
    "Closed Wednesday · Thursday; 5:14 AM staff report",
    "Closed Wednesday · Thursday = begin 9:14 PM",
    "Closed Wednesday · Thursday # students report 9:14 PM",
    "Closed Wednesday · in effect = Thursday 9:14 PM",
    'Closed Wednesday · Thursday effective "9:14 PM"',
    # a bare number past a weekday's own ".", and one with a mark glued before it before the
    # weekday's marks (WD-R8C1-B2)
    "Closed Wednesday · Thursday.45",
    "Closed Wednesday · Thursday. 60 info",
    "Closed Wednesday · Thu.50 info",
    "Closed Thursday · Friday.75",
    "Closed Wednesday · :9 · Thursday",
    "Closed Wednesday · #12 :: Thursday",
    "Closed Wednesday · ,9 · Thursday",
    "Closed Wednesday · $9 · Thursday",
    # a start, opening or dismissal word that is no status word owns no span and no clock
    # time past the marks (WD-R8C1-B3)
    "Closed Wednesday · Thursday | dismiss 9:14 PM",
    "Closed Wednesday · Thursday | starting (8:30-3:15)",
    "Closed Wednesday · Thursday: opened 9:14 PM",
    # past the marks, a span further on than 80 characters (S2)
    "Closed Wednesday · Thursday | the front desk and the main phones line will be staffed for "
    "families during this time of day while the office works through the list (9 AM - 3 PM)",
    # a start or opening word that is no status word owns no clock time past the marks and no
    # span with "at" or "@" before it either (WD-R8C2-B1)
    "Closed Wednesday · Thursday: started at 9:14 PM",
    "Closed Wednesday · Thursday: started at 5:14 AM",
    "Closed Wednesday · Thursday | started @ 5:14 AM",
    "Closed Wednesday · Thursday; opened at 5:14 AM",
    "Closed Wednesday · started at 9:14 PM: Thursday",
    "Closed Wednesday · opened at 9:14 PM, Thursday",
    "Closed Wednesday · Thursday started at 9 AM - 3 PM",
    "Closed Wednesday · Thursday opened at 9 to 3",
    "Closed Wednesday · opened at 9a-3p Thursday",
    "Closed Thursday · Friday: opened at 9:14 PM",
    "Closed Thursday · Friday started at 8:30-3:15",
    "Closed Wednesday · Thursday | releasing @ 9:14 PM",
    # a dismissal at a time the reader reads no dismissal at owns no clock past the marks, as
    # the round 8 second critic's S4 found
    "Closed Wednesday · Thursday | dismiss at 9:14 PM",
    "Closed Wednesday · Thursday: dismiss at 9:14 PM",
    "Closed Wednesday · Thursday: dismiss at 7:30",
    "Closed Wednesday · Thursday: dismiss @ 3:00 PM",
    "Closed Wednesday · Thursday: dismiss at 8:30-3:15",
    # a "~" by an owner word and a clock time is a mark (WD-R8C2-S1)
    "Closed Wednesday · Thursday begins ~ 9:14 PM",
    "Closed Wednesday · Thursday begins ~9:14 PM",
    # a bare number across a line break from a weekday's marks (WD-R8C2-S2)
    "Closed Wednesday · Thursday:\n45",
    "Closed Wednesday · Thursday:\n45 info",
    "Closed Wednesday · Thursday |\n9 info",
    "Closed Wednesday · Thursday:\n9 info",
    "Closed Wednesday · 9:\nThursday",
    "Closed Wednesday · 45\n· Thursday",
    "Closed Wednesday · 9\n: Thursday",
    "Closed Thursday · Friday:\n45 info",
    "Closed Wednesday · Thursday:\n9:14 PM",
    "Closed Wednesday · 9:14 PM:\nThursday",
]


@pytest.mark.parametrize("when", ["2026-11-05 12:00", "2026-11-05 01:00"])
@pytest.mark.parametrize("text", _R8_HOLD)
def test_round_8_shapes_keep_the_hold(when: str, text: str) -> None:
    # read Thursday at 06:00 and Wednesday at 19:00
    world = _cold(when, text)
    world.resolve()
    assert lit(world.publish(at(when) + timedelta(minutes=1))) == {}


@pytest.mark.parametrize(
    ("when", "text", "days"),
    [
        # a status-like owner word still owns a clock past the marks
        ("2026-11-05 12:00", "Thursday: dismiss at 1:30", {THURSDAY: "EARLY_DISMISSAL"}),
        # a single clock time in the weekday's own clause is still owned
        ("2026-11-05 12:00", "Thursday 10 AM start", {THURSDAY: "DELAYED"}),
        # a count with a delay's length unit is no stamp's number
        ("2026-11-05 12:00", "Thursday: 2 hour delay", {THURSDAY: "DELAYED"}),
        ("2026-11-05 12:00", "Thursday: 90 minute delay", {THURSDAY: "DELAYED"}),
        ("2026-11-05 12:00", "Thursday: 2-hr. delay", {THURSDAY: "DELAYED"}),
        # a spaced dash in a span of bare hours ends no clause (S1)
        ("2026-11-05 12:00", "Thursday: 2 - 3 hour delay", {THURSDAY: "DELAYED"}),
        # the evening path
        ("2026-11-05 01:00", "Thursday: 2 hour delay", {THURSDAY: "DELAYED"}),
        ("2026-11-05 01:00", "Thursday: dismiss at 1:30", {THURSDAY: "EARLY_DISMISSAL"}),
        # a dismissal word with "at" or "@" right before the clock time owns it past the marks
        # at a time the reader reads a dismissal at, 8 a.m. to 1:30 p.m. (WD-R8C2-S4)
        ("2026-11-05 12:00", "Thursday | dismiss @ 1:30", {THURSDAY: "EARLY_DISMISSAL"}),
        ("2026-11-05 12:00", "Thursday: dismiss at 8:00", {THURSDAY: "EARLY_DISMISSAL"}),
        ("2026-11-05 12:00", "Thursday: dismiss at 12:30 PM", {THURSDAY: "EARLY_DISMISSAL"}),
        ("2026-11-05 12:00", "Thursday: dismisses at noon", {THURSDAY: "EARLY_DISMISSAL"}),
        ("2026-11-05 01:00", "Thursday | dismiss @ 11", {THURSDAY: "EARLY_DISMISSAL"}),
        # and a single clock time in the weekday's own clause, "at" before it or not
        ("2026-11-05 12:00", "Thursday dismiss at 1:30", {THURSDAY: "EARLY_DISMISSAL"}),
        # a bare number across a line break with a status word is read as before (WD-R8C2-S2)
        ("2026-11-05 12:00", "Closed Thursday:\n2 schools", {THURSDAY: "CLOSED"}),
        ("2026-11-05 12:00", "Thursday:\n2 hour delay", {THURSDAY: "DELAYED"}),
        # a delay's length after a weekday's own "." is no stamp's number
        ("2026-11-05 12:00", "Thursday. 2 hour delay", {THURSDAY: "DELAYED"}),
    ],
)
def test_round_8_shapes_that_still_light(when: str, text: str, days: dict[str, str]) -> None:
    world = _cold(when, text)
    world.resolve()
    assert lit(world.publish(at(when) + timedelta(minutes=1))) == {
        (0, day): status for day, status in days.items()
    }


@pytest.mark.parametrize(
    ("text", "named"),
    [
        # a status word in the weekday's clause makes the bare number by its marks a number
        ("Closed Thursday: 9 schools", {3}),
        ("Thursday: grades 9 - 12 closed", {3}),
        ("Thursday: 2 - 3 hour delay", {3}),
        # a month's day number before the marks is no stamp's
        ("Closed Wednesday · Nov. 5 · Thursday", set()),
        # who reports, past the marks, owns no clock there
        ("Thursday: students report 10 AM", set()),
        ("Staff report Thursday 9 AM", {3}),
        # a "~" by a weekday and a clock time is a mark, an owner word between or not, while an
        # approximation word is part of the clock time (WD-R8C2-S1)
        ("Thursday begins ~ 9:14 PM", set()),
        ("Thursday begins ~9:14 PM", set()),
        ("Thursday ~ 9:14 PM", set()),
        ("Thursday begins around 9:14 PM", {3}),
        ("Thursday begins approx. 9:14 PM", {3}),
        # a dismissal past the marks at a time the reader reads none at (WD-R8C2-S4)
        ("Thursday: dismiss at 1:35", set()),
        ("Thursday: dismiss at 7:55", set()),
        ("Thursday: dismiss at 9:14 PM", set()),
        ("Thursday: dismiss at 1:30", {3}),
        # a status word keeps a bare number after a weekday's "." a number, as before
        ("Closed Thursday. 45 schools", {3}),
        # the end of a clock time before the marks is no bare number
        ("Closed Wednesday · 10:30 · Thursday", {2}),
    ],
)
def test_round_8_status_days(text: str, named: set[int]) -> None:
    assert named_weekdays(text, "", THU_0600.date()) == frozenset(named)


_R8_OWNERS = (
    "begins",
    "beginning",
    "in effect",
    "effective",
    "takes effect",
    "staff report",
    "students report",
    "teachers arrive",
    "employees report",
    "faculty arrival",
    "everyone reports",
    # start, opening and dismissal words that are no status word (WD-R8C1-B3)
    "dismiss",
    "dismisses",
    "starting",
    "started",
    "releases",
    "opened",
    "delaying",
)
_R8_SPANS = (
    "8:30-3:15",
    "9 AM - 3 PM",
    "(9:14-9:30 PM)",
    "9 to 3",
    "between 9 and 3",
    "9a-3p",
    "0900-1500",
    "9 AM until 3 PM",
    "8h30-15h15",
)
_R8_CLOCKS = ("5:14 AM", "9:14 PM", "21:14", "noon", "(9 AM)", "10 AM")
_R8_MARKS = (":", " |", ",", " ·", ".", ";", " /", " -", " (", " •", " ...", " ::", " |,")
_R8_OTHER_MARKS = (" =", " ~", " #", " *", " »", " [", " >", " +")
"""Marks that end no clause but part a weekday from its clock time as a stamp's do."""
_R8_PLACES = (
    "{d}{m} {o} {x}",
    "{d} {o}{m} {x}",
    "{x}{m} {o} {d}",
    "{x} {o}{m} {d}",
    "{o} {d}{m} {x}",
    "{x}{m} {d} {o}",
    "{d}{m}{x} {o}",
    "{d}{m} {x} {o}",
    "{o}{m} {d} {x}",
)
"""Where an owner word (o) stands by a weekday (d), its clock time or span (x) and a mark (m):
between the weekday and the clock time either side of the mark, before the weekday, after the
clock time, and before the mark before the weekday."""
_R8_DAYS = (
    ("Closed Wednesday · ", date(2026, 11, 5), "2026-11-05"),
    ("Closed Thursday · ", date(2026, 11, 6), "2026-11-06"),
)
"""The other weekday's status, and the day each sweep's weekday is, read the morning of that
day at 06:00 and the evening before at 19:00 (Chicago)."""


def _lights_on(text: str, day: date, now: datetime) -> bool:
    """Whether ``text``, read at ``now`` (the morning of ``day`` or the evening before), names
    ``day``'s weekday as a status day with no stamp that keeps the row held, as the live
    guards read a weekday-dated row."""
    today = now.date()
    if states_a_date(text, "") or day.weekday() not in named_weekdays(text, "", day):
        return False
    return all(
        stamp is not None and today - timedelta(days=1) <= stamp <= today
        for stamp in stamp_dates(text, today, now)
    ) and all(age is not None and age < timedelta(days=1) for age in post_ages(text))


def _r8_reads(lead: str, day: date, iso: str) -> Iterator[tuple[str, date, datetime]]:
    """The two reads of a sweep's row: the morning of ``day`` and the evening before."""
    for clock in ("12:00", "01:00"):
        yield lead, day, at(f"{iso} {clock}").astimezone(ZoneInfo("America/Chicago"))


def _r8_owner_shapes(owner: str, clocks: tuple[str, ...]) -> Iterator[tuple[str, date, datetime]]:
    """Each shape of the owner word ``owner`` with each span in the weekday's own clause, and
    with each of ``clocks`` and each mark in each of the nine places (:data:`_R8_PLACES`), with
    each read (:data:`_R8_DAYS`): the shape, the weekday's day and the read."""
    for lead, day, now in (read for days in _R8_DAYS for read in _r8_reads(*days)):
        name = day.strftime("%A")
        shapes = [
            shape
            for span in _R8_SPANS
            for shape in (f"{lead}{name} {owner} {span}", f"{lead}{span} {owner} {name}")
        ]
        for mark, clock, place in itertools.product(
            _R8_MARKS + _R8_OTHER_MARKS, clocks, _R8_PLACES
        ):
            if mark == "." and clock.endswith("M") and place.startswith("{x}{m}"):
                continue
            shapes.append(lead + place.format(d=name, m=mark, o=owner, x=clock))
        for text in shapes:
            yield text, day, now


@pytest.mark.parametrize("owner", _R8_OWNERS)
def test_round_8_owner_words_own_no_span_and_no_clock_past_the_marks(owner: str) -> None:
    # the class at the function level: each owner word that is no status word with each span
    # in the weekday's own clause, and with each span or clock time and each mark, clause mark
    # or not, in each of nine places (between the weekday and the clock time on either side of
    # the mark, before the weekday, after the clock time on either side, before the mark before
    # the weekday), read the morning of the day at 06:00 and the evening before at 19:00, never
    # lights the weekday (11,312 shapes and reads for each owner word); a clock time whose
    # "a.m." or "p.m." takes the "." stays in the clause, and owned there, as a single clock
    # time is
    for text, day, now in _r8_owner_shapes(owner, _R8_SPANS + _R8_CLOCKS):
        assert not _lights_on(text, day, now), (text, now)


_R8_AT_OWNERS = (
    "started",
    "starting",
    "opened",
    "releasing",
    "releases",
    "delaying",
    "begins",
    "in effect",
    "staff report",
)
"""Owner words that are no status word, which "at" or "@" after them makes no status word."""
_R8_NO_DISMISSAL = ("5:14 AM", "9:14 PM", "21:14", "7:30", "7:55 AM", "1:35", "3:00 PM", "6 PM")
"""Clock times the reader reads no dismissal at ("dismiss at 1:35" is an ordinary afternoon)."""


@pytest.mark.parametrize("at_word", [" at", " @"])
@pytest.mark.parametrize("owner", _R8_AT_OWNERS)
def test_round_8_owner_words_with_at_own_no_span_and_no_clock_past_the_marks(
    owner: str, at_word: str
) -> None:
    # the class at the function level with "at" or "@" between the owner word and the clock
    # time (WD-R8C2-B1): each owner word that is no status word, with each span and clock time
    # and each mark in each of the nine places, read the morning of the day and the evening
    # before, never lights the weekday
    for text, day, now in _r8_owner_shapes(f"{owner}{at_word}", _R8_SPANS + _R8_CLOCKS):
        assert not _lights_on(text, day, now), (text, now)


@pytest.mark.parametrize("at_word", [" at", " @"])
@pytest.mark.parametrize("owner", ["dismiss", "dismisses"])
def test_round_8_a_dismissal_at_owns_no_span_and_no_time_the_reader_reads_none_at(
    owner: str, at_word: str
) -> None:
    # "dismiss at" owns a clock time past the marks only at a time the reader reads a
    # dismissal at, and never a span (WD-R8C2-B1, WD-R8C2-S4)
    for text, day, now in _r8_owner_shapes(f"{owner}{at_word}", _R8_SPANS + _R8_NO_DISMISSAL):
        assert not _lights_on(text, day, now), (text, now)


_R8_NUMBERS = ("9", "10", "1", "12", "07", "45", "60", "99", "32")
_R8_GLUED = ("", ":", "#", "/", ".", ",", "$")
"""A mark glued before a bare number before a weekday's marks, with no digit before it."""
_R8_TAILS = ("", " info", " | info", " update", " posted", ".")


@pytest.mark.parametrize("gap", ["", " "])
@pytest.mark.parametrize("size", [1, 2, 3])
def test_round_8_no_bare_number_by_a_run_of_marks_names_its_day(size: int, gap: str) -> None:
    # the class at the function level: a bare number of one or two digits (up to 99) on either
    # side of a run of one, two or three marks (of 33, every pair, and every triple of the
    # first 10) by a weekday, glued or spaced, with a mark glued before it before the weekday
    # or none, with words after it or none, read the morning of the day at 06:00 and the
    # evening before at 19:00, never lights the weekday (21,780 shapes and reads of two marks
    # for each gap)
    pool = _R7C2_MARKS if size < 3 else _R7C2_MARKS[:10]
    for index, combo in enumerate(itertools.product(pool, repeat=size)):
        run = gap.join(combo)
        number = _R8_NUMBERS[index % len(_R8_NUMBERS)]
        tail = _R8_TAILS[index % len(_R8_TAILS)]
        glued = _R8_GLUED[index % len(_R8_GLUED)]
        for lead, day, now in (read for days in _R8_DAYS for read in _r8_reads(*days)):
            name = day.strftime("%A")
            for text in (
                f"{lead}{name}{run}{number}{tail}",
                f"{lead}{name} {run} {number}{tail}",
                f"{lead}{name}.{number}{tail}",
                f"{lead}{glued}{number}{run}{name}{tail}",
                f"{lead}{glued}{number} {run} {name}{tail}",
            ):
                assert not _lights_on(text, day, now), (text, now)


@pytest.mark.parametrize("mark", list(_R7C2_MARKS))
def test_round_8_no_bare_number_across_a_line_break_from_a_run_of_marks_names_its_day(
    mark: str,
) -> None:
    # a line break in a weekday's run of marks parts a bare number from it as spaces do
    # (WD-R8C2-S2): each mark, each number and each tail, with the line break on either side of
    # the mark, either way round, read the morning of the day and the evening before
    for number, tail in itertools.product(_R8_NUMBERS, _R8_TAILS):
        for lead, day, now in (read for days in _R8_DAYS for read in _r8_reads(*days)):
            name = day.strftime("%A")
            for text in (
                f"{lead}{name}{mark}\n{number}{tail}",
                f"{lead}{name} {mark}\n{number}{tail}",
                f"{lead}{name}{mark} \n {number}{tail}",
                f"{lead}{number}{mark}\n{name}{tail}",
                f"{lead}{number}\n{mark} {name}{tail}",
                f"{lead}{number}\n{mark}\n{name}{tail}",
            ):
                assert not _lights_on(text, day, now), (text, now)
