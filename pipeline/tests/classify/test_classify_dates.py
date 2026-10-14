"""Local dates: posting time, time zones, weekends, explicit dates and ranges.

The texts are phrasing patterns written for these tests, not real listings.
"""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from snowlight.classify import parse_status

NY = "America/New_York"
LA = "America/Los_Angeles"


def at(text: str, tz: str = NY) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=ZoneInfo(tz))


def d(month: int, day: int, year: int = 2026) -> date:
    return date(year, month, day)


TUE_MORNING = at("2026-01-20T05:30")
TUE_LATE_MORNING = at("2026-01-20T11:30")
TUE_AFTERNOON = at("2026-01-20T13:00")
TUE_LATE_AFTERNOON = at("2026-01-20T15:30")
TUE_EVENING = at("2026-01-20T20:00")
WED_OVERNIGHT = at("2026-01-21T00:30")
FRI_EVENING = at("2026-01-23T21:00")
SAT_MORNING = at("2026-01-24T10:00")
SUN_EVENING = at("2026-01-25T19:00")
DEC_30 = at("2025-12-30T06:00")
JAN_2 = at("2026-01-02T06:00")
DEC_26_EVENING = at("2025-12-26T21:00")

DATE_CASES = [
    # Each row: the text, when it was posted, the kind, the dates, and whether the text named them.
    ("Closed", TUE_MORNING, "closed", (d(1, 20),), False),
    ("Closed", TUE_EVENING, "closed", (d(1, 21),), False),
    ("Closed tomorrow", TUE_EVENING, "closed", (d(1, 21),), True),
    ("2 hour delay", TUE_EVENING, "delayed", (d(1, 21),), False),
    ("Early dismissal", TUE_EVENING, "early_dismissal", (d(1, 21),), False),
    ("Closed today", TUE_EVENING, "closed", (d(1, 20),), True),
    ("Closed Wednesday", TUE_EVENING, "closed", (d(1, 21),), True),
    ("Closed Tuesday", TUE_EVENING, "closed", (d(1, 20),), True),
    ("Closed", TUE_LATE_MORNING, "closed", (d(1, 20),), False),
    ("2 hour delay", TUE_LATE_MORNING, "delayed", (d(1, 21),), False),
    ("Early dismissal at 1", TUE_LATE_MORNING, "early_dismissal", (d(1, 20),), False),
    # A closure first seen between noon and 3 p.m. could be today's or tomorrow's.
    ("Closed", TUE_AFTERNOON, "other", (), False),
    ("Closed", at("2026-01-20T15:00"), "closed", (d(1, 21),), False),
    ("Remote learning day", TUE_AFTERNOON, "other", (), False),
    # Posted on a Friday evening or a Saturday, the next school day is days off: a status
    # that names no day could be for the weekend's events as well as for Monday.
    ("Closed", at("2026-01-24T13:00"), "other", (), False),
    ("Early dismissal at 2:00", TUE_AFTERNOON, "early_dismissal", (d(1, 20),), False),
    ("Early dismissal", TUE_LATE_AFTERNOON, "early_dismissal", (d(1, 21),), False),
    ("Closed tomorrow", WED_OVERNIGHT, "closed", (d(1, 21),), True),
    ("Closed", WED_OVERNIGHT, "closed", (d(1, 21),), False),
    ("Closed today", WED_OVERNIGHT, "closed", (d(1, 21),), True),
    ("Closed Tuesday", WED_OVERNIGHT, "closed", (d(1, 20),), True),
    ("Closed", FRI_EVENING, "other", (), False),
    ("Closed Monday", FRI_EVENING, "closed", (d(1, 26),), True),
    ("2 hour delay", FRI_EVENING, "other", (), False),
    ("Closed tomorrow", FRI_EVENING, "closed", (d(1, 24),), True),
    ("Closed", SAT_MORNING, "other", (), False),
    ("Closed", at("2026-01-24T01:00"), "other", (), False),
    ("2 hour delay", at("2026-01-23T11:30"), "other", (), False),
    # From Sunday, Monday is the next day.
    ("Closed", SUN_EVENING, "closed", (d(1, 26),), False),
    ("Closed", at("2026-01-25T09:00"), "closed", (d(1, 26),), False),
    ("Remote learning day", at("2026-01-25T13:00"), "remote", (d(1, 26),), False),
    ("Closed", at("2026-01-26T01:00"), "closed", (d(1, 26),), False),
    ("NTI day Monday", SAT_MORNING, "remote", (d(1, 26),), True),
    ("Closed Monday and Tuesday", SAT_MORNING, "closed", (d(1, 26), d(1, 27)), True),
    ("Closed all week", SAT_MORNING, "closed", tuple(d(1, n) for n in range(26, 31)), True),
    ("Closed tomorrow", SUN_EVENING, "closed", (d(1, 26),), True),
    ("Closed Jan 2", DEC_30, "closed", (d(1, 2),), True),
    ("Closed Friday, Jan. 2", DEC_30, "closed", (d(1, 2),), True),
    ("Closed January 2nd", DEC_30, "closed", (d(1, 2),), True),
    ("Closed Dec 31", JAN_2, "closed", (d(12, 31, 2025),), True),
    ("Closed 12/31/2025", JAN_2, "closed", (d(12, 31, 2025),), True),
    ("Closed 12/31/25", JAN_2, "closed", (d(12, 31, 2025),), True),
    ("Closed Monday", DEC_26_EVENING, "closed", (d(12, 29, 2025),), True),
    ("Closed Dec 31 - Jan 2", DEC_30, "closed", (d(12, 31, 2025), d(1, 1), d(1, 2)), True),
    ("Closed next Monday", TUE_MORNING, "closed", (d(1, 26),), True),
    ("Closed this Friday", TUE_MORNING, "closed", (d(1, 23),), True),
    ("Closed next Tuesday", TUE_MORNING, "closed", (d(1, 27),), True),
    ("Closed yesterday and today", TUE_MORNING, "closed", (d(1, 19), d(1, 20)), True),
    # A closure for part of a day: the afternoon is an early dismissal, the morning is unclear.
    ("Closed this afternoon", TUE_MORNING, "early_dismissal", (d(1, 20),), True),
    ("Closed this afternoon", TUE_EVENING, "early_dismissal", (d(1, 20),), True),
    ("Closed this morning", TUE_MORNING, "other", (), False),
    # An evening is after the school day: "Closed tonight" is not a school closure.
    ("Closed tonight", TUE_MORNING, "other", (), False),
    ("Closed today and tonight", TUE_MORNING, "closed", (d(1, 20),), True),
    # A weekday range is the run that includes or follows the posting day.
    (
        "Closed Thursday through Tuesday",
        TUE_MORNING,
        "closed",
        (d(1, 15), d(1, 16), d(1, 19), d(1, 20)),
        True,
    ),
    (
        "Closed Thursday through Tuesday",
        at("2026-01-21T06:00"),
        "closed",
        (d(1, 22), d(1, 23), d(1, 26), d(1, 27)),
        True,
    ),
    ("Closed Jan 23-27", TUE_MORNING, "closed", (d(1, 23), d(1, 26), d(1, 27)), True),
    ("Closed 1/21-1/23", TUE_MORNING, "closed", (d(1, 21), d(1, 22), d(1, 23)), True),
    ("Closed Jan 21 through Jan 23", TUE_MORNING, "closed", (d(1, 21), d(1, 22), d(1, 23)), True),
    (
        "Closed Monday through Wednesday",
        TUE_MORNING,
        "closed",
        (d(1, 19), d(1, 20), d(1, 21)),
        True,
    ),
    ("Closed Mon-Wed", TUE_MORNING, "closed", (d(1, 19), d(1, 20), d(1, 21)), True),
    ("Closed through Wednesday", TUE_EVENING, "closed", (d(1, 21),), True),
    ("Closed thru Friday", TUE_MORNING, "closed", tuple(d(1, n) for n in range(20, 24)), True),
    ("Closed until Thursday", TUE_MORNING, "closed", (d(1, 20), d(1, 21)), True),
    ("Closed Monday until Thursday", SUN_EVENING, "closed", (d(1, 26), d(1, 27), d(1, 28)), True),
    ("Closed rest of the week", TUE_MORNING, "closed", tuple(d(1, n) for n in range(20, 24)), True),
    ("Closed tomorrow (Wednesday)", TUE_MORNING, "closed", (d(1, 21),), True),
    ("Closed today (Tuesday 1/20)", TUE_MORNING, "closed", (d(1, 20),), True),
    ("No School Tues 1/20 & Wed 1/21", TUE_MORNING, "closed", (d(1, 20), d(1, 21)), True),
    ("Closed Tuesday 1/20 and Wednesday 1/21", TUE_MORNING, "closed", (d(1, 20), d(1, 21)), True),
    (
        "Closed Wednesday and Thursday, January 21-22",
        TUE_MORNING,
        "closed",
        (d(1, 21), d(1, 22)),
        True,
    ),
    ("Closed 2026-01-22", TUE_MORNING, "closed", (d(1, 22),), True),
    ("Closed Thursday, January 22, 2026", TUE_MORNING, "closed", (d(1, 22),), True),
    ("Closed Jan. 21, 22 and 23", TUE_MORNING, "closed", (d(1, 21), d(1, 22), d(1, 23)), True),
    # A year after a run of day numbers is the year of them all.
    ("Closed January 21-23, 2026", TUE_MORNING, "closed", (d(1, 21), d(1, 22), d(1, 23)), True),
    ("Closed Jan 21-23 2026", TUE_MORNING, "closed", (d(1, 21), d(1, 22), d(1, 23)), True),
    ("Closed January 21 - 23, 2026", TUE_MORNING, "closed", (d(1, 21), d(1, 22), d(1, 23)), True),
    (
        "Closed January 21st-23rd, 2026.",
        TUE_MORNING,
        "closed",
        (d(1, 21), d(1, 22), d(1, 23)),
        True,
    ),
    (
        "Closed Jan. 21, 22 and 23, 2026",
        TUE_MORNING,
        "closed",
        (d(1, 21), d(1, 22), d(1, 23)),
        True,
    ),
    ("Closed 1/21-23, 2026", TUE_MORNING, "closed", (d(1, 21), d(1, 22), d(1, 23)), True),
    (
        "2 hour delay January 21-22, 2027",
        TUE_MORNING,
        "delayed",
        (d(1, 21, 2027), d(1, 22, 2027)),
        True,
    ),
    ("Closed Jan 21 and 22", TUE_MORNING, "closed", (d(1, 21), d(1, 22)), True),
]


@pytest.mark.parametrize(
    ("text", "posted", "kind", "dates", "stated"),
    [pytest.param(*row, id=f"{row[0]} @ {row[1]:%a %H:%M}") for row in DATE_CASES],
)
def test_dates(
    text: str, posted: datetime, kind: str, dates: tuple[date, ...], stated: bool
) -> None:
    result = parse_status(text, posted_at=posted, tz=NY)
    assert result.kind == kind
    assert result.dates == dates
    assert result.dates_stated is stated


def test_overnight_tomorrow_is_the_day_that_has_begun() -> None:
    result = parse_status("Closed tomorrow", posted_at=WED_OVERNIGHT, tz=NY)
    assert result.dates == (d(1, 21),)
    assert "overnight" in result.notes
    assert result.confidence <= 0.8


def test_a_weekend_only_status_is_less_certain() -> None:
    result = parse_status("Closed tomorrow", posted_at=FRI_EVENING, tz=NY)
    assert "weekend" in result.notes
    assert result.confidence <= 0.7


def test_posting_close_to_the_cutoff_is_less_certain() -> None:
    assert parse_status("Closed", posted_at=TUE_LATE_MORNING, tz=NY).confidence <= 0.8
    assert parse_status("Closed", posted_at=TUE_MORNING, tz=NY).confidence == 0.9


def test_rest_of_the_week_on_a_friday_night_is_not_invented() -> None:
    result = parse_status("Closed rest of the week", posted_at=FRI_EVENING, tz=NY)
    assert result.kind == "other"
    assert "invalid_date" in result.notes


def test_weekday_that_does_not_match_the_date() -> None:
    # Jan. 21 is a Wednesday: either name could be the day meant, so neither is trusted.
    result = parse_status("Closed Tuesday, Jan. 21", posted_at=TUE_MORNING, tz=NY)
    assert result.kind == "other"
    assert result.dates == ()
    assert "date_mismatch" in result.notes
    assert result.confidence <= 0.3


@pytest.mark.parametrize("text", ["Closed Feb 30", "Closed 13/45", "Closed 2/30/2026"])
def test_impossible_dates_are_not_statuses(text: str) -> None:
    result = parse_status(text, posted_at=TUE_MORNING, tz=NY)
    assert result.kind == "other"
    assert result.confidence <= 0.3


@pytest.mark.parametrize("text", ["Closed 2/29", "Closed February 29", "Closed Feb. 29th"])
def test_february_29_in_a_year_with_none_is_no_day(text: str) -> None:
    # Posted in February 2027: the nearest February has no 29th, and one a year off is no
    # day the text means.
    posted = datetime(2027, 2, 26, 6, 0, tzinfo=ZoneInfo(NY))
    result = parse_status(text, posted_at=posted, tz=NY)
    assert result.kind == "other"
    assert "invalid_date" in result.notes
    assert result.confidence <= 0.3
    leap = parse_status(text, posted_at=datetime(2028, 2, 26, 6, 0, tzinfo=ZoneInfo(NY)), tz=NY)
    assert leap.dates == (d(2, 29, 2028),)


def test_a_range_longer_than_three_months_keeps_only_its_start() -> None:
    result = parse_status("Closed Jan 5 through June 20", posted_at=TUE_MORNING, tz=NY)
    assert result.dates == (d(1, 5),)
    assert "invalid_date" in result.notes
    assert result.confidence <= 0.5


def test_a_range_of_weeks_keeps_every_school_day() -> None:
    result = parse_status("Closed Jan 5 through Mar 20", posted_at=TUE_MORNING, tz=NY)
    assert result.schedule[0].dates[0] == d(1, 5)
    assert result.schedule[0].dates[-1] == d(3, 20)
    assert len(result.schedule[0].dates) == 55  # the weekdays from Jan 5 to Mar 20
    assert "invalid_date" not in result.notes


def test_until_further_notice() -> None:
    result = parse_status("Closed until further notice", posted_at=TUE_MORNING, tz=NY)
    assert result.until_further_notice
    assert result.dates == (d(1, 20),)
    assert result.dates_stated is False
    started = parse_status(
        "Closed starting Wednesday until further notice", posted_at=TUE_MORNING, tz=NY
    )
    assert started.dates == (d(1, 21),)
    assert started.until_further_notice
    assert parse_status("Closed indefinitely", posted_at=TUE_MORNING, tz=NY).until_further_notice


def test_time_zone_decides_the_local_day() -> None:
    instant = datetime(2026, 1, 21, 6, 30, tzinfo=UTC)  # 1:30 a.m. Wed in NY, 10:30 p.m. Tue in LA
    assert parse_status("Closed today", posted_at=instant, tz=NY).dates == (d(1, 21),)
    assert parse_status("Closed today", posted_at=instant, tz=LA).dates == (d(1, 20),)
    assert parse_status("Closed tomorrow", posted_at=instant, tz=NY).dates == (d(1, 21),)
    assert parse_status("Closed tomorrow", posted_at=instant, tz=LA).dates == (d(1, 21),)


def test_same_instant_any_offset_gives_the_same_answer() -> None:
    local = at("2026-01-20T20:00")
    as_utc = local.astimezone(UTC)
    assert parse_status("Closed", posted_at=local, tz=NY) == parse_status(
        "Closed", posted_at=as_utc, tz=NY
    )


def test_primary_status_is_the_first_current_one() -> None:
    result = parse_status(
        "Closed Monday 1/19. 2 hour delay Tuesday 1/20.", posted_at=TUE_MORNING, tz=NY
    )
    assert result.kind == "delayed"
    assert result.on(d(1, 19)) is not None
    past = parse_status("Closed Jan 5", posted_at=TUE_MORNING, tz=NY)
    assert past.kind == "closed"
    assert past.dates == (d(1, 5),)


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        parse_status("Closed", posted_at=datetime(2026, 1, 20, 6, 0), tz=NY)


@pytest.mark.parametrize("tz", ["Mars/Olympus_Mons", "", "../etc/passwd", "not a zone"])
def test_unknown_time_zone_is_rejected(tz: str) -> None:
    with pytest.raises(ValueError, match="unknown time zone"):
        parse_status("Closed", posted_at=TUE_MORNING, tz=tz)


SUN_OVERNIGHT = at("2026-01-25T01:30")
SAT_OVERNIGHT = at("2026-01-24T01:30")


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Closed tomorrow", "closed"),
        ("2 hour delay tomorrow", "delayed"),
        ("Closed tomorrow (Monday)", "closed"),
        ("Closed tomorrow, Jan. 26", "closed"),
        ("NTI day tomorrow", "remote"),
    ],
)
def test_overnight_tomorrow_on_a_sunday_is_the_monday(text: str, kind: str) -> None:
    # Early on a Sunday the day that has begun holds no school: "tomorrow" is Monday.
    result = parse_status(text, posted_at=SUN_OVERNIGHT, tz=NY)
    assert result.kind == kind
    assert result.dates == (d(1, 26),)
    assert "overnight" in result.notes
    assert "weekend" not in result.notes
    assert result.confidence == 0.8


def test_overnight_tomorrow_on_a_saturday_is_still_the_saturday() -> None:
    # Written on the Friday evening, "tomorrow" is the Saturday that has begun.
    result = parse_status("Closed tomorrow", posted_at=SAT_OVERNIGHT, tz=NY)
    assert result.dates == (d(1, 24),)
    assert "weekend" in result.notes
    assert result.confidence == 0.7
