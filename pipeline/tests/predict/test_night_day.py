"""The night chart's day and window: one definition (``schemas/predictions.py``), written to
``golden/night_day.json`` for the site's twin (``web/src/data/night.ts``)."""

import json
import os
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from snowlight.schemas.predictions import (
    NIGHT_MAX_BARS,
    night_close,
    night_day,
    night_hours,
    night_open,
    night_window,
)

GOLDEN = Path(__file__).parent / "golden" / "night_day.json"

NY = "America/New_York"
CHICAGO = "America/Chicago"
DENVER = "America/Denver"
PHOENIX = "America/Phoenix"
LA = "America/Los_Angeles"
ZONES = (NY, CHICAGO, DENVER, PHOENIX, LA)
WINTER = date(2026, 1, 27)  # a Tuesday: its night is Monday's evening
SUMMER = date(2026, 7, 14)
LOCAL_TIMES = (
    (-1, time(6, 59)),
    (-1, time(7)),
    (-1, time(7, 30)),
    (-1, time(7, 59)),
    (-1, time(8)),
    (-1, time(14)),
    (-1, time(17)),
    (-1, time(17, 59)),
    (-1, time(18)),
    (-1, time(21, 7)),
    (-1, time(23, 59)),
    (0, time(0)),
    (0, time(3, 7)),
    (0, time(5, 0)),
    (0, time(5, 59)),
    (0, time(6)),
    (0, time(6, 59)),
    (0, time(7)),
)
UTC_TIMES = (time(10, 59), time(11), time(11, 30))
# Both clock changes of 2026 (Sunday 2 AM): the nights of the Saturday and the Sunday.
DST_DAYS = (date(2026, 3, 8), date(2026, 11, 1))


def _local(day: date, offset: int, clock: time, zone: str) -> datetime:
    return datetime.combine(day + timedelta(days=offset), clock, tzinfo=ZoneInfo(zone)).astimezone(
        UTC
    )


def _moments() -> list[tuple[str, datetime]]:
    found: list[tuple[str, datetime]] = []
    for zone in ZONES:
        for day in (WINTER, SUMMER, *DST_DAYS):
            found.extend((zone, _local(day, offset, clock, zone)) for offset, clock in LOCAL_TIMES)
            found.extend((zone, datetime.combine(day, clock, tzinfo=UTC)) for clock in UTC_TIMES)
    return found


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def night_day_json() -> bytes:
    """Every case: the moment, its zone, its night day, whether open, and the window."""
    rows = []
    for zone, moment in _moments():
        start, end = night_window(moment, zone)
        rows.append(
            {
                "zone": zone,
                "at": _iso(moment),
                "day": night_day(moment, zone).isoformat(),
                "open": night_open(moment, zone),
                "start": _iso(start),
                "end": _iso(end),
                "hours": night_hours(moment, zone),
            }
        )
    lines = ",\n".join(json.dumps(row, separators=(",", ":")) for row in rows)
    return f"[\n{lines}\n]\n".encode()


def test_the_golden_night_days_are_what_the_rule_says() -> None:
    # web/src/data/tests/night.contract.test.ts checks nightDay and nightOpen against this.
    data = night_day_json()
    if os.environ.get("SNOWLIGHT_WRITE_GOLDEN") == "1":
        GOLDEN.write_bytes(data)
    assert GOLDEN.read_bytes() == data


@pytest.mark.parametrize(
    ("clock", "day", "is_open"),
    [
        (time(6, 59), date(2026, 7, 13), False),
        (time(7), date(2026, 7, 14), True),
        (time(7, 30), date(2026, 7, 14), True),
        (time(7, 59), date(2026, 7, 14), True),
        (time(8), date(2026, 7, 14), True),
    ],
)
def test_the_eastern_daylight_morning_edge(clock: time, day: date, is_open: bool) -> None:
    moment = datetime.combine(date(2026, 7, 13), clock, tzinfo=ZoneInfo(NY))
    assert night_day(moment, NY) == day
    assert night_open(moment, NY) is is_open


def test_the_window_closes_at_six_local_and_reopens_at_seven() -> None:
    day = WINTER
    for zone in ZONES:
        close = night_close(day, zone)
        assert close == datetime.combine(day, time(6), tzinfo=ZoneInfo(zone))
        assert night_open(close - timedelta(minutes=1), zone)
        assert not night_open(close, zone)
        seven = datetime.combine(day, time(7), tzinfo=ZoneInfo(zone))
        assert not night_open(seven - timedelta(minutes=1), zone)
        assert night_open(seven, zone)
        assert night_day(seven, zone) == day + timedelta(days=1)


def test_the_window_runs_from_the_next_hour_or_six_pm_to_seven_am() -> None:
    at = datetime.combine(WINTER - timedelta(days=1), time(21, 7), tzinfo=ZoneInfo(NY))
    start, end = night_window(at, NY)
    assert start == datetime.combine(at.date(), time(22), tzinfo=ZoneInfo(NY))
    assert end == datetime.combine(WINTER, time(7), tzinfo=ZoneInfo(NY))
    assert night_hours(at, NY) == 9
    morning = datetime.combine(WINTER - timedelta(days=1), time(8), tzinfo=ZoneInfo(CHICAGO))
    start, _ = night_window(morning, CHICAGO)
    assert start == datetime.combine(morning.date(), time(18), tzinfo=ZoneInfo(CHICAGO))
    assert night_hours(morning, CHICAGO) == NIGHT_MAX_BARS
    late = datetime.combine(WINTER, time(5, 30), tzinfo=ZoneInfo(LA))
    assert night_hours(late, LA) == 1
    on_the_hour = datetime.combine(WINTER, time(3), tzinfo=ZoneInfo(DENVER))
    assert night_window(on_the_hour, DENVER)[0] == on_the_hour + timedelta(hours=1)


def test_one_pass_can_hold_two_night_days() -> None:
    # The close is local: at 11:30Z in summer the East is on the next day, the West is not.
    at = datetime.combine(SUMMER, time(11, 30), tzinfo=UTC)
    assert night_day(at, NY) == SUMMER + timedelta(days=1)
    assert night_open(at, NY)
    assert night_day(at, LA) == SUMMER
    assert night_open(at, LA)


def test_every_open_minute_of_a_year_has_a_window_of_1_to_13_hours() -> None:
    moment = datetime(2026, 1, 1, tzinfo=UTC)
    for zone in ZONES:
        at = moment
        while at < datetime(2027, 1, 1, tzinfo=UTC):
            day = night_day(at, zone)
            seven = datetime.combine(day, time(7), tzinfo=ZoneInfo(zone))
            assert seven - timedelta(days=1) <= at < seven
            if night_open(at, zone):
                hours = night_hours(at, zone)
                # The clock changes fall on Sunday nights, never a school day's: 12 or 14 there.
                assert 1 <= hours <= NIGHT_MAX_BARS + 1
            at += timedelta(minutes=17)
