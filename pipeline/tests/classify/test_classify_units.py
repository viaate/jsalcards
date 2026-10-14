"""Unit tests for the parser's building blocks and the result model."""

import json
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from snowlight.classify import KINDS, REASONS, STATUS_KINDS, DatedStatus, parse_status
from snowlight.classify.dates import (
    GROUP_LINKS,
    GROUP_OPEN_START,
    Calendar,
    find_date_groups,
    find_unreadable,
    zone,
)
from snowlight.classify.model import CONFIDENCE_LEVELS
from snowlight.classify.text import MAX_CHARS, clock_time, duration_minutes, normalize
from snowlight.classify.weather import find_weather

TZ = "America/New_York"
POSTED = datetime(2026, 1, 20, 5, 30, tzinfo=ZoneInfo(TZ))


@pytest.mark.parametrize(
    ("text", "minutes"),
    [
        ("2 hour", 120),
        ("2-hour", 120),
        ("two hour", 120),
        ("2hr", 120),
        ("2 hrs", 120),
        ("1.5 hours", 90),
        ("1 1/2 hour", 90),
        ("1-1/2 hour", 90),
        ("one and a half hour", 90),
        ("an hour and a half", 90),
        ("hour and a half", 90),
        ("hour and 15 minutes", 75),
        ("half hour", 30),
        ("a half hour", 30),
        ("90 minute", 90),
        ("90-min", 90),
        ("2 hours 30 minutes", 150),
        ("2 hours and a half", 150),
        ("10 hour", None),
        ("5 minute", None),
        ("0 hour", None),
    ],
)
def test_duration_minutes(text: str, minutes: int | None) -> None:
    assert duration_minutes(text) == minutes


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("noon", time(12)),
        ("12 noon", time(12)),
        ("midday", time(12)),
        ("10:00", time(10)),
        ("10", time(10)),
        ("1:00", time(13)),
        ("1", time(13)),
        ("6:30", time(18, 30)),
        ("7", time(7)),
        ("12", time(12)),
        ("12:30", time(12, 30)),
        ("1 pm", time(13)),
        ("11 am", time(11)),
        ("12 am", time(0)),
        ("12 pm", time(12)),
        ("13:00", time(13)),
        ("0:30", None),
        ("0 am", None),
        ("13 pm", None),
        ("25:00", None),
        ("12:75", None),
        ("soon", None),
        # "a" and "p" for "am" and "pm".
        ("9a", time(9)),
        ("9:30a", time(9, 30)),
        ("1:30p", time(13, 30)),
        ("7p", time(19)),
        ("12a", time(0)),
        ("12p", time(12)),
        ("0a", None),
    ],
)
def test_clock_time(text: str, expected: time | None) -> None:
    assert clock_time(text) == expected


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("  Closed\u2014Offices   Open ", "closed-offices open"),
        ("Closed \u2013 Offices Open", "closed - offices open"),
        ("Opening at 10 a.m.", "opening at 10 am"),
        ("Opening at 10 A. M.", "opening at 10 am"),
        ("Closed Tues., Jan. 21", "closed tues, jan 21"),
        ("Closed\nOffices open", "closed ; offices open"),
        ("Snow &amp; ice; closed", "snow and ice; closed"),
        ("Snow & ice", "snow and ice"),
        ("Closed w/ remote learning", "closed with remote learning"),
        ("School\u2019s closed", "school's closed"),
        ("Zero\u200bwidth", "zerowidth"),
        ("1\u00bd hour delay", "1 1/2 hour delay"),
        ("After school activities", "after-school activities"),
        ("In the event of snow", "in case of snow"),
        ("Closed (snow)", "closed, snow"),
        ("Closed tomorrow (Thursday)", "closed tomorrow thursday"),
        ("Closed today ( Thurs. ), Friday", "closed today thurs, friday"),
        ("Closed today (snow), Friday", "closed today, snow, friday"),
        ("(Updated) Closed", "updated, closed"),
        ("Opening at 9:30a.m.", "opening at 9:30am"),
        ("TODAY: CLOSING EARLY AT 6::00 PM", "today: closing early at 6:00 pm"),
    ],
)
def test_normalize(raw: str, normalized: str) -> None:
    assert normalize(raw) == normalized


def test_normalize_cuts_very_long_text() -> None:
    assert len(normalize("closed " * 1000)) <= MAX_CHARS


def test_find_date_groups_links() -> None:
    groups = find_date_groups("closed monday, tuesday and wednesday; delay jan 21-23")
    assert [group[GROUP_LINKS] for group in groups] == [("list", "list"), ("range",)]
    until = find_date_groups("closed until thursday")
    assert until[0][GROUP_OPEN_START] == "until"
    through = find_date_groups("closed thru friday")
    assert through[0][GROUP_OPEN_START] == "range"
    assert find_date_groups("no dates here") == ()


def test_a_bare_hyphen_between_today_and_tomorrow_is_not_a_range() -> None:
    groups = find_date_groups("closed today - tomorrow delayed")
    assert len(groups) == 2


def test_fractions_are_not_dates() -> None:
    assert find_date_groups("1 1/2 hour delay") == ()
    assert find_date_groups("1/2 day") == ()


def test_calendar_week_end_on_weekend_is_next_friday() -> None:
    saturday = Calendar(datetime(2026, 1, 24, 10, tzinfo=ZoneInfo(TZ)), TZ)
    assert saturday.week_end() == date(2026, 1, 30)
    tuesday = Calendar(POSTED, TZ)
    assert tuesday.week_end() == date(2026, 1, 23)


def test_zone_is_cached_and_validated() -> None:
    assert zone(TZ) is zone(TZ)
    with pytest.raises(ValueError, match="unknown time zone"):
        zone("Nowhere/Special")


def test_results_are_immutable() -> None:
    result = parse_status("Closed", posted_at=POSTED, tz=TZ)
    with pytest.raises(AttributeError):
        result.kind = "delayed"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        result.schedule[0].dates = ()  # type: ignore[misc]
    assert isinstance(result.dates, tuple)
    assert isinstance(result.schedule, tuple)
    assert hash(result.schedule[0]) == hash(result.schedule[0])


def test_as_dict_is_json_ready() -> None:
    result = parse_status(
        "Early dismissal today at 1:30 due to ice; closed tomorrow; offices open",
        posted_at=POSTED,
        tz=TZ,
    )
    data = result.as_dict()
    assert json.loads(json.dumps(data)) == data
    assert data["kind"] == "early_dismissal"
    assert data["dismissal_time"] == "13:30"
    assert data["dates"] == ["2026-01-20"]
    assert data["reason"] == "Ice"
    assert data["offices_open"] is True
    schedule = data["schedule"]
    assert isinstance(schedule, list)
    assert [entry["kind"] for entry in schedule] == ["early_dismissal", "closed"]


def test_on_finds_the_status_for_a_day() -> None:
    result = parse_status("Closed today, 2 hour delay tomorrow", posted_at=POSTED, tz=TZ)
    tuesday = result.on(date(2026, 1, 20))
    wednesday = result.on(date(2026, 1, 21))
    assert isinstance(tuesday, DatedStatus)
    assert tuesday.kind == "closed"
    assert wednesday is not None
    assert wednesday.kind == "delayed"
    assert wednesday.delay_minutes == 120
    assert result.on(date(2026, 1, 22)) is None


def test_constants() -> None:
    assert set(STATUS_KINDS) < set(KINDS)
    assert len(REASONS) == 8
    assert list(CONFIDENCE_LEVELS) == sorted(CONFIDENCE_LEVELS, reverse=True)


def test_details_only_when_the_text_gives_one_value() -> None:
    two_delays = parse_status("2 hour delay for elementary. 1 hour delay.", posted_at=POSTED, tz=TZ)
    assert two_delays.kind == "delayed"
    assert two_delays.delay_minutes is None
    two_times = parse_status(
        "Early release: 11:30 elementary, 12:15 secondary", posted_at=POSTED, tz=TZ
    )
    assert two_times.dismissal_time is None


@pytest.mark.parametrize(
    "text",
    [
        "Opening at 3",  # an afternoon opening is not a late start
        "Early dismissal at 5 pm",  # after the school day
        "Dismissal at 7",
    ],
)
def test_times_outside_the_school_day_are_not_kept(text: str) -> None:
    result = parse_status(text, posted_at=POSTED, tz=TZ)
    assert result.opens_at is None
    assert result.dismissal_time is None


def test_find_unreadable_works_out_its_own_word_hints() -> None:
    for text, expected in (("closed next week", True), ("closed jan 22", False)):
        assert find_unreadable(text, find_date_groups(text), []) is expected


def test_find_weather_works_out_its_own_word_hints() -> None:
    found = find_weather("closed due to snow")
    assert found.names_weather
    assert found.terms == ("snow",)
    assert find_weather("closed due to snow", vocabulary={"closed", "due", "to", "snow"}) == found
    nothing = find_weather("closed today", vocabulary={"closed", "today"})
    assert not nothing.names_weather
    assert nothing.other_causes == ()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Closed 3/15 (10)", "closed 3/15"),
        ("(12) Closed (345) tomorrow", "closed, tomorrow"),
        ("Closed,, tomorrow", "closed, tomorrow"),
    ],
)
def test_a_bracketed_number_is_dropped(text: str, expected: str) -> None:
    assert normalize(text) == expected
