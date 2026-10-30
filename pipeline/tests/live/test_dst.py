"""Daylight saving time ends Sun 2026-11-01 at 02:00 local (S6): the live reader's clocks across
the change, frozen at real moments, with the real zone rules (SYNTHETIC stations and rows).

Every contiguous zone a school can be in, Arizona (no daylight saving time), and Alaska and
Hawaii where the reader names them (the ledger's earlier-day rule). The cadence windows, the
morning alert window, the school's day (a 25-hour Nov 1 in every zone that changes), the
day boundaries every school's today lies inside, the interval samples across the repeated
hour, the morning record's band, the learning's read window, the picture's 07:30 school-day
rule (the panel's under-way rule), and the health and soak clocks, which keep UTC only.
"""

from collections import deque
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from zoneinfo import ZoneInfo

import pytest

from live.test_cadence import station
from snowlight.live.alerts import morning
from snowlight.live.cadence import BOOSTED, CALM_FLOOR, GRID, Cadence, grid_slot, in_window
from snowlight.live.history import is_final
from snowlight.live.ingest import Ingest
from snowlight.live.ledger import US_ZONES, Outcome, _earlier_day
from snowlight.live.merge import day_start, school_today
from snowlight.live.morning import READ_BAND, in_band, slot_of
from snowlight.live.resolve import samples
from snowlight.live.soak import gaps, parse_moment
from snowlight.predict.config import PredictConfig
from snowlight.predict.live_labels import window_of
from snowlight.schemas.live import local_days
from snowlight.social.picture import chance_day

CONTIGUOUS = (
    "America/New_York",
    "America/Detroit",
    "America/Indiana/Indianapolis",
    "America/Kentucky/Louisville",
    "America/Chicago",
    "America/Menominee",
    "America/North_Dakota/Center",
    "America/Denver",
    "America/Boise",
    "America/Phoenix",
    "America/Los_Angeles",
)
"""Every contiguous US zone a school's county can be in (the NWS boundary files' names)."""
NO_DST = frozenset({"America/Phoenix"})
ALL = (*CONTIGUOUS, "America/Anchorage", "Pacific/Honolulu")
CHANGE = date(2026, 11, 1)
HOUR = timedelta(hours=1)


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def marks(start: datetime, end: datetime, step: timedelta = GRID) -> Iterator[datetime]:
    moment = start
    while moment < end:
        yield moment
        moment += step


def offset(zone: str, day: date) -> timedelta:
    found = datetime.combine(day, time(12), ZoneInfo(zone)).utcoffset()
    assert found is not None
    return found


# --- the zone rules themselves ---------------------------------------------------------------


@pytest.mark.parametrize("zone", ALL)
def test_the_zone_rules_change_on_nov_1_except_in_arizona_and_hawaii(zone: str) -> None:
    before, after = offset(zone, date(2026, 10, 31)), offset(zone, date(2026, 11, 2))
    if zone in NO_DST or zone == "Pacific/Honolulu":
        assert before == after
    else:
        assert after == before - HOUR


# --- the cadence windows -------------------------------------------------------------------


def window_marks(zone: str, day: date) -> dict[str, list[datetime]]:
    """The UTC grid marks of ``day`` (local) inside each of the zone's windows."""
    tz = ZoneInfo(zone)
    start = datetime.combine(day, time(0), tz).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time(0), tz).astimezone(UTC)
    found: dict[str, list[datetime]] = {"morning": [], "evening": []}
    for moment in marks(start, end):
        if in_window(zone, moment):
            local = moment.astimezone(tz)
            found["morning" if local.hour < 12 else "evening"].append(moment)
    return found


@pytest.mark.parametrize("zone", CONTIGUOUS)
@pytest.mark.parametrize("day", [date(2026, 10, 31), CHANGE, date(2026, 11, 2)])
def test_each_window_is_five_local_hours_on_either_side_of_the_change(zone: str, day: date) -> None:
    tz = ZoneInfo(zone)
    found = window_marks(zone, day)
    for name, start, end in (("morning", time(4), time(9)), ("evening", time(18), time(23))):
        moments = found[name]
        assert len(moments) == 60
        assert moments[0] == datetime.combine(day, start, tz).astimezone(UTC)
        assert moments[-1] == datetime.combine(day, end, tz).astimezone(UTC) - GRID
        assert all(b - a == GRID for a, b in pairwise(moments))


@pytest.mark.parametrize("zone", CONTIGUOUS)
def test_the_morning_window_moves_an_hour_later_in_utc_after_the_change(zone: str) -> None:
    saturday = window_marks(zone, date(2026, 10, 31))["morning"][0]
    monday = window_marks(zone, date(2026, 11, 2))["morning"][0]
    shift = (monday - saturday) - timedelta(days=2)
    assert shift == (timedelta(0) if zone in NO_DST else HOUR)


def test_no_window_holds_the_repeated_hour() -> None:
    """01:00-02:00 comes twice on Nov 1; both lie outside 04:00-09:00 and 18:00-23:00."""
    for zone in CONTIGUOUS:
        tz = ZoneInfo(zone)
        first = datetime(2026, 11, 1, 1, 30, tzinfo=tz)
        second = first.replace(fold=1)
        for moment in (first, second):
            assert not in_window(zone, moment.astimezone(UTC))


@pytest.mark.parametrize(
    ("zone", "fips"),
    [
        ("America/New_York", "36061"),
        ("America/Chicago", "20091"),
        ("America/Denver", "08031"),
        ("America/Phoenix", "04013"),
        ("America/Los_Angeles", "06037"),
    ],
)
def test_a_station_is_read_on_its_cadence_through_the_25_hour_day(zone: str, fips: str) -> None:
    """Passes on every grid mark from Oct 31 12:00Z to Nov 2 18:00Z: inside its windows the
    station is read every pass, outside every 30 minutes; never twice in a slot, never sooner
    than 4 minutes, never a calm wait over 30 minutes."""
    source = station("synthetic-dst", fips=(fips,))
    cadence = Cadence({source.id: source}, {fips: zone}, lambda _s: 10)
    reads: list[datetime] = []
    for moment in marks(utc("2026-10-31T12:00:00"), utc("2026-11-02T18:00:00")):
        start = moment + timedelta(seconds=3)  # a pass starts a few seconds after its mark
        if cadence.due(start, [source.id]):
            cadence.record(start, [(source.id, Outcome.OK, None)])
            reads.append(start)
    for before, after in pairwise(reads):
        assert grid_slot(after) > grid_slot(before)
        gap = after - before
        assert gap >= BOOSTED - timedelta(minutes=1)
        boosted = in_window(zone, before) or in_window(zone, after - GRID)
        assert gap <= (BOOSTED if boosted and in_window(zone, after) else CALM_FLOOR)
    tz = ZoneInfo(zone)
    windows = [moment for moment in reads if in_window(zone, moment)]
    # Nov 1: the whole morning and evening windows (60 passes each), read every pass
    on_change = [moment for moment in windows if moment.astimezone(tz).date() == CHANGE]
    assert len(on_change) == 120


def test_the_alert_morning_follows_each_zone_across_the_change() -> None:
    # 04:00 EST on Monday is 09:00Z; 04:00 EDT on Saturday was 08:00Z.
    assert morning(utc("2026-10-31T08:00:00"))
    # 08:30Z Monday: 03:30 EST, 02:30 CST, 01:30 MST, 00:30 PST: no main zone's morning yet
    assert not morning(utc("2026-11-02T08:30:00"))
    assert morning(utc("2026-11-02T09:00:00"))
    # 16:30Z Monday: 08:30 PST is the last morning
    assert morning(utc("2026-11-02T16:55:00"))
    assert not morning(utc("2026-11-02T17:00:00"))
    # Saturday: 08:30 PDT is 15:30Z, and 16:00Z is past every morning
    assert not morning(utc("2026-10-31T16:00:00"))


# --- a school's day ---------------------------------------------------------------------------


@pytest.mark.parametrize("zone", CONTIGUOUS)
def test_nov_1_is_25_hours_long_where_the_clocks_change(zone: str) -> None:
    length = day_start(date(2026, 11, 2), (zone,)) - day_start(CHANGE, (zone,))
    assert length == (timedelta(hours=24) if zone in NO_DST else timedelta(hours=25))
    assert day_start(CHANGE, (zone,)) - day_start(date(2026, 10, 31), (zone,)) == timedelta(
        hours=24
    )


@pytest.mark.parametrize("zone", CONTIGUOUS)
def test_the_school_today_turns_at_local_midnight_on_both_sides(zone: str) -> None:
    for day in (date(2026, 10, 31), CHANGE, date(2026, 11, 2)):
        start = day_start(day, (zone,))
        assert school_today((zone,), start) == day
        assert school_today((zone,), start - timedelta(seconds=1)) == day - timedelta(days=1)
    # all through the repeated hour, Nov 1 is still the school's today
    tz = ZoneInfo(zone)
    first = datetime(2026, 11, 1, 1, 0, tzinfo=tz).astimezone(UTC)
    for moment in marks(first, first + 2 * HOUR):
        assert school_today((zone,), moment) == CHANGE


def test_a_school_in_two_zones_takes_the_later_date_through_the_change() -> None:
    zones = ("America/Chicago", "America/New_York")
    # 04:30Z Nov 2 is 23:30 EST and 22:30 CST on Nov 1: still Nov 1 in both
    assert school_today(zones, utc("2026-11-02T04:30:00")) == CHANGE
    # 05:00Z Nov 2 is Nov 2 in New York: a day passed anywhere is past
    assert school_today(zones, utc("2026-11-02T05:00:00")) == date(2026, 11, 2)
    assert day_start(date(2026, 11, 2), zones) == utc("2026-11-02T06:00:00")


# --- the day boundaries every school's day lies inside ---------------------------------------


def test_every_school_today_and_tomorrow_lie_inside_the_files_days_across_the_change() -> None:
    """``local_days`` (the closings file's day bounds) holds every contiguous school's today
    and tomorrow at every 5-minute mark from Oct 30 to Nov 3, in daylight and standard time."""
    for moment in marks(utc("2026-10-30T00:00:00"), utc("2026-11-03T00:00:00")):
        first, last = local_days(moment)
        for zone in CONTIGUOUS:
            today = moment.astimezone(ZoneInfo(zone)).date()
            assert first <= today
            assert today + timedelta(days=1) <= last


def test_a_day_is_final_only_once_it_is_over_in_every_contiguous_zone() -> None:
    for moment in marks(utc("2026-10-30T00:00:00"), utc("2026-11-03T00:00:00")):
        for day in (date(2026, 10, 31), CHANGE, date(2026, 11, 2)):
            if is_final(day, moment):
                assert all(moment.astimezone(ZoneInfo(zone)).date() > day for zone in CONTIGUOUS)
    # Nov 1 ends 08:00Z Nov 2 in Los Angeles (PST): final from then on, not before
    assert not is_final(CHANGE, utc("2026-11-02T07:59:59"))
    assert is_final(CHANGE, utc("2026-11-02T08:00:00"))
    # Oct 31 ends 07:00Z Nov 1 in Los Angeles (PDT); the bound waits an hour longer
    assert not is_final(date(2026, 10, 31), utc("2026-11-01T07:30:00"))
    assert is_final(date(2026, 10, 31), utc("2026-11-01T08:00:00"))


# --- the interval samples across the repeated hour ------------------------------------------


@pytest.mark.parametrize("zone", sorted(set(CONTIGUOUS) - NO_DST))
def test_the_samples_hold_every_local_half_hour_of_both_one_oclocks(zone: str) -> None:
    """A row first seen after the night of the change is read at every local :00 and :30 of
    its interval: both 01:30s (the daylight one and the standard one) are samples."""
    tz = ZoneInfo(zone)
    one = datetime(2026, 11, 1, 1, 0, tzinfo=tz)
    lo = (one - 2 * HOUR).astimezone(UTC) + timedelta(minutes=10)
    hi = lo + 5 * HOUR
    found = set(samples(lo, hi, (zone,), step=timedelta(hours=10)))
    daylight = datetime(2026, 11, 1, 1, 30, tzinfo=tz).astimezone(UTC)
    standard = datetime(2026, 11, 1, 1, 30, fold=1, tzinfo=tz).astimezone(UTC)
    assert standard - daylight == HOUR
    assert {daylight, standard} <= found
    halves = [moment for moment in found if moment not in {lo, hi}]
    assert all(moment.minute in {0, 30} for moment in halves)
    # every half hour of the interval, none missing: 5 hours, 10 marks
    assert len(halves) == 10


def test_the_samples_in_arizona_are_unchanged_by_the_night() -> None:
    lo, hi = utc("2026-11-01T05:10:00"), utc("2026-11-01T10:10:00")
    found = samples(lo, hi, ("America/Phoenix",), step=timedelta(hours=10))
    halves = [f"{hour:02d}:{minute:02d}" for hour in range(5, 11) for minute in (0, 30)]
    assert [moment.strftime("%H:%M") for moment in found] == ["05:10", *halves[1:-1], "10:10"]


# --- the ledger's earlier local day -----------------------------------------------------------


def test_the_earlier_day_rule_holds_in_alaska_and_hawaii_through_the_change() -> None:
    assert {"America/Anchorage", "Pacific/Honolulu"} <= set(US_ZONES)
    # Nov 1 begins at 10:00Z in Honolulu: a first sighting at 09:00Z and a return at 10:30Z
    # fall on two local dates there
    assert _earlier_day(utc("2026-11-01T09:00:00"), utc("2026-11-01T10:30:00"))
    # inside New York's first 01:00 hour no zone's date turns (Denver turns at 06:00Z)
    assert not _earlier_day(utc("2026-11-01T05:10:00"), utc("2026-11-01T05:50:00"))
    assert _earlier_day(utc("2026-11-01T05:50:00"), utc("2026-11-01T06:10:00"))
    # Anchorage turns at 09:00Z on Nov 2 (AKST), 08:00Z on Nov 1 (AKDT)
    assert _earlier_day(utc("2026-11-01T07:50:00"), utc("2026-11-01T08:10:00"))
    assert not _earlier_day(utc("2026-11-02T08:20:00"), utc("2026-11-02T08:50:00"))


# --- the morning record and the learning's read window -----------------------------------------


@pytest.mark.parametrize("zone", CONTIGUOUS)
@pytest.mark.parametrize("day", [date(2026, 10, 31), CHANGE, date(2026, 11, 2)])
def test_the_morning_band_holds_every_zones_morning_reads(zone: str, day: date) -> None:
    tz = ZoneInfo(zone)
    start = datetime.combine(day, time(6, 30), tz).astimezone(UTC)
    end = datetime.combine(day, time(9, 30), tz).astimezone(UTC)
    assert all(in_band(moment) for moment in marks(start, end))
    assert (time(9), time(21)) == READ_BAND


def test_the_morning_slots_are_utc_half_hours_on_the_night_of_the_change() -> None:
    # 05:40Z and 06:40Z are both 01:40 in New York; their slots differ in UTC
    assert slot_of(utc("2026-11-01T05:40:00")) == "05:30"
    assert slot_of(utc("2026-11-01T06:40:00")) == "06:30"


@pytest.mark.parametrize("zone", CONTIGUOUS)
def test_the_learning_read_window_is_local_on_the_25_hour_day(zone: str) -> None:
    settings = PredictConfig.load().labels
    span = datetime.combine(CHANGE, settings.read_until) - datetime.combine(
        CHANGE, settings.read_from
    )
    for day in (date(2026, 10, 31), CHANGE, date(2026, 11, 2)):
        start, end = window_of(day, zone, settings)
        assert end - start == span
        expected = datetime.combine(day, settings.read_from, ZoneInfo(zone)).astimezone(UTC)
        assert start.astimezone(UTC) == expected
        assert all(in_band(moment) for moment in marks(start.astimezone(UTC), end))
    sunday = window_of(CHANGE, zone, settings)[0].astimezone(UTC)
    monday = window_of(date(2026, 11, 2), zone, settings)[0].astimezone(UTC)
    assert sunday.time() == monday.time()  # Nov 1's morning is already standard time


# --- the picture's school-day rule (07:30 local) ------------------------------------------------


def test_the_school_day_turns_at_0730_local_after_the_change() -> None:
    file = {"days": ["2026-11-02", "2026-11-03"], "districts": [{"time_zone": "America/Chicago"}]}
    # 07:30 CST on Monday is 13:30Z (CDT would have been 12:30Z)
    assert chance_day(file, utc("2026-11-02T12:30:00")) == date(2026, 11, 2)
    assert chance_day(file, utc("2026-11-02T13:29:00")) == date(2026, 11, 2)
    assert chance_day(file, utc("2026-11-02T13:30:00")) == date(2026, 11, 3)
    saturday = {"days": ["2026-10-31"], "districts": [{"time_zone": "America/Chicago"}]}
    # 07:30 CDT on the Saturday before the change is 12:30Z
    assert chance_day(saturday, utc("2026-10-31T12:29:00")) == date(2026, 10, 31)
    assert chance_day(saturday, utc("2026-10-31T12:30:00")) is None


# --- the health and soak clocks: UTC only ------------------------------------------------------


def test_the_health_window_counts_utc_minutes_through_the_repeated_hour() -> None:
    """The share counts the last 15 minutes of real time: 05:55Z and 06:05Z (01:55 EDT and
    01:05 EST in New York) are 10 minutes apart, not 50 minutes back."""
    ingest = Ingest.__new__(Ingest)
    ingest.recent = deque(
        [
            (utc("2026-11-01T05:55:00"), "synthetic-a", True),
            (utc("2026-11-01T06:05:00"), "synthetic-b", True),
        ]
    )
    ingest.due = frozenset({"synthetic-a", "synthetic-b"})
    assert ingest.healthy_share(utc("2026-11-01T06:08:00")) == 1.0
    assert ingest.healthy_share(utc("2026-11-01T06:12:00")) == 0.5


def test_the_soak_reads_moments_in_utc_through_the_change() -> None:
    assert parse_moment("2026-11-01T05:30Z") == utc("2026-11-01T05:30:00")
    moments = [utc("2026-11-01T05:50:00"), utc("2026-11-01T05:55:00"), utc("2026-11-01T06:00:00")]
    found = gaps(moments, ())
    assert found["max_minutes"] == 5.0
    assert found["stale_minutes_by_day"] == {}
