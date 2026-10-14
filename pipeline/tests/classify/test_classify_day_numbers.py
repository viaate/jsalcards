"""A weekday with a day number, long ranges, and runs of days said in two parts.

Every text here is a phrasing pattern written for these tests, not a claim
about a real school. Unless a row says otherwise it is posted at 6 a.m. on
Tuesday 20 January 2026 in New York, so "today" is Tuesday the 20th and
"tomorrow" Wednesday the 21st.

* A weekday with a day number names the date with that number on that
  weekday, even a week or more past the weekday's next date: "Closed
  Wednesday the 28th" is January 28, at 0.95. Only when no such date lies
  between a week before the weekday's next date and a month after it do the
  two disagree ("Wednesday the 22nd": 0.5, ``date_mismatch``, the number wins).
* A number after a weekday that counts something ("Wednesday, 12-Month
  Employees", "Wednesday 12 noon", "Monday, 3 schools") is no day number. A
  count of weeks ("closed 2 weeks") is a day the parser cannot read.
* A range can run for weeks, as closures after a hurricane do ("Closed through
  October 25" posted on October 1): every school day in it. Past about three
  months a range is more likely misread than meant: its first day only, at 0.5.
* A run can be said in two parts: "Closed Wednesday; through Friday", "Closed
  tomorrow. Through Friday.", "Closed Wednesday, until Friday". "Until further
  notice; through Jan. 30" runs from the posting day to the 30th.
* A day heading an entry names the first day of the run in it again:
  "Wednesday: Closed Wednesday and Thursday" is the 21st and 22nd, never the
  Wednesday a week before; "Wednesday: Closed Thursday and Friday" names two
  different days as one, so it states no day.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from snowlight.classify import parse_status

TZ = "America/New_York"
ZONE = ZoneInfo(TZ)
TUE = datetime(2026, 1, 20, 6, 0, tzinfo=ZONE)
THU_EVENING_MARCH = datetime(2026, 3, 19, 21, 0, tzinfo=ZONE)
WED_MAY = datetime(2026, 5, 20, 6, 0, tzinfo=ZONE)
WED_OCTOBER = datetime(2025, 10, 1, 7, 0, tzinfo=ZONE)
MON_MARCH = datetime(2026, 3, 16, 7, 0, tzinfo=ZONE)


def jan(*days: int) -> tuple[date, ...]:
    return tuple(date(2026, 1, day) for day in days)


def school_days(first: date, last: date) -> tuple[date, ...]:
    """The weekdays from ``first`` through ``last``."""
    span = (last - first).days + 1
    days = (first + timedelta(days=offset) for offset in range(span))
    return tuple(day for day in days if day.weekday() < 5)


@dataclass(frozen=True)
class Row:
    text: str
    posted: datetime
    kind: str
    dates: tuple[date, ...]
    confidence: float
    notes: tuple[str, ...]
    until_further_notice: bool


def row(  # noqa: PLR0913 - one table row
    text: str,
    kind: str,
    dates: tuple[date, ...] = (),
    *,
    posted: datetime = TUE,
    confidence: float = 0.95,
    notes: tuple[str, ...] = (),
    until_further_notice: bool = False,
) -> object:
    case = Row(text, posted, kind, dates, confidence, notes, until_further_notice)
    return pytest.param(case, id=f"{text} @ {posted:%Y-%m-%d %H:%M}")


def check(case: Row) -> None:
    result = parse_status(case.text, posted_at=case.posted, tz=TZ)
    assert result.kind == case.kind
    assert result.dates == case.dates
    assert result.confidence == case.confidence
    assert result.notes == case.notes
    assert result.until_further_notice == case.until_further_notice


# A weekday with its day number.
DAY_NUMBERS = [
    row("Closed Wednesday the 28th", "closed", jan(28)),
    row("Closed through Wednesday the 28th", "closed", jan(20, 21, 22, 23, 26, 27, 28)),
    row("Closed Wednesday 28", "closed", jan(28)),
    row("Remote learning Friday the 30th", "remote", jan(30)),
    row("Closed Thursday the 22nd", "closed", jan(22)),
    row("Closed Wednesday the 21st", "closed", jan(21)),
    row("Closed Monday the 2nd", "closed", (date(2026, 2, 2),)),
    row(
        "Closed Through Sunday the 29th",
        "closed",
        school_days(date(2026, 3, 20), date(2026, 3, 29)),
        posted=THU_EVENING_MARCH,
    ),
    row(
        "Closed through Sunday, the 29th",
        "closed",
        school_days(date(2026, 3, 20), date(2026, 3, 29)),
        posted=THU_EVENING_MARCH,
    ),
    row(
        "Closed Through Sunday the 5th",
        "closed",
        school_days(date(2026, 3, 20), date(2026, 4, 5)),
        posted=THU_EVENING_MARCH,
    ),
    row(
        "Closed Through Sunday the 31st",
        "closed",
        school_days(date(2026, 5, 20), date(2026, 5, 31)),
        posted=WED_MAY,
    ),
    # No date with that number falls on that weekday nearby: the two disagree, and either
    # could be the day meant.
    row("Closed Wednesday the 22nd", "other", confidence=0.3, notes=("date_mismatch",)),
    row("Closed Sunday the 29th", "other", confidence=0.3, notes=("date_mismatch",)),
    row("Closed Wednesday the 31st", "other", confidence=0.3, notes=("date_mismatch",)),
    row("Closed tomorrow the 22nd", "other", confidence=0.3, notes=("date_mismatch",)),
]

# A number after a weekday that counts something.
COUNTS = [
    row("Closed Wednesday, 12-Month Employees Report", "closed", jan(21)),
    row("Closing Wednesday 12 noon", "early_dismissal", jan(21)),
    row("Closed Thursday, 3 schools affected", "closed", jan(22)),
    row("Closed Wednesday 2 weeks", "other", confidence=0.3, notes=("unreadable_date",)),
    row("Closed for two weeks", "other", confidence=0.3, notes=("unreadable_date",)),
]

# Ranges of weeks.
LONG_RANGES = [
    row(
        "Closed through October 25 due to hurricane damage",
        "closed",
        school_days(date(2025, 10, 1), date(2025, 10, 25)),
        posted=WED_OCTOBER,
    ),
    row(
        "Closed Oct 1 through Oct 31",
        "closed",
        school_days(date(2025, 10, 1), date(2025, 10, 31)),
        posted=WED_OCTOBER,
    ),
    row(
        "Closed through November 14",
        "closed",
        school_days(date(2025, 10, 1), date(2025, 11, 14)),
        posted=WED_OCTOBER,
    ),
    row(
        "Remote learning through November 7",
        "remote",
        school_days(date(2025, 10, 1), date(2025, 11, 7)),
        posted=WED_OCTOBER,
    ),
    row(
        "Closed through April 24",
        "closed",
        school_days(date(2026, 3, 16), date(2026, 4, 24)),
        posted=MON_MARCH,
    ),
    row(
        "Closed March 16 through May 1",
        "closed",
        school_days(date(2026, 3, 16), date(2026, 5, 1)),
        posted=MON_MARCH,
    ),
    # Longer than about three months: the first day only.
    row(
        "Closed Oct 1 through Jan 30",
        "closed",
        (date(2025, 10, 1),),
        posted=WED_OCTOBER,
        confidence=0.5,
        notes=("invalid_date",),
    ),
]

# A run said in two parts.
RUNS = [
    row("Closed Wednesday; through Friday", "closed", jan(21, 22, 23)),
    row("Closed Wednesday, through Friday", "closed", jan(21, 22, 23)),
    row("Closed tomorrow. Through Friday.", "closed", jan(21, 22, 23)),
    row("Closed tomorrow, through Friday", "closed", jan(21, 22, 23)),
    row("Closed Wednesday. Until Friday.", "closed", jan(21, 22)),
    row("Closed Wednesday, until Friday", "closed", jan(21, 22)),
    row("Remote learning Wednesday, through Friday", "remote", jan(21, 22, 23)),
    row("NTI day tomorrow; through Friday", "remote", jan(21, 22, 23)),
    row("Closed Jan 21, through Jan 23", "closed", jan(21, 22, 23)),
    row("Closed Monday, Tuesday and through Friday", "closed", jan(19, 20, 21, 22, 23)),
    row(
        "Closed until further notice; through Jan 30",
        "closed",
        school_days(date(2026, 1, 20), date(2026, 1, 30)),
        until_further_notice=True,
    ),
    row(
        "Closed until further notice, through Jan 30",
        "closed",
        school_days(date(2026, 1, 20), date(2026, 1, 30)),
        until_further_notice=True,
    ),
    row(
        "Closed until further notice (through Jan 30)",
        "closed",
        school_days(date(2026, 1, 20), date(2026, 1, 30)),
        until_further_notice=True,
    ),
    row(
        "Closed until further notice. Through Friday.",
        "closed",
        jan(20, 21, 22, 23),
        until_further_notice=True,
    ),
    row(
        "Closed until further notice; until Jan 30",
        "closed",
        school_days(date(2026, 1, 20), date(2026, 1, 29)),
        until_further_notice=True,
    ),
    row(
        "Closed through Jan 30; until further notice",
        "closed",
        school_days(date(2026, 1, 20), date(2026, 1, 30)),
        until_further_notice=True,
    ),
]

# A day heading an entry and the run in it name its first day twice: once, and alike.
HEADINGS = [
    row("Wednesday: Closed Wednesday through Friday", "closed", jan(21, 22, 23)),
    row("Monday: Closed Monday through Wednesday", "closed", jan(19, 20, 21)),
    row("Thursday: Closed Thursday and Friday", "closed", jan(22, 23)),
    row("Wednesday Morning: Closed Wednesday and Thursday", "closed", jan(21, 22)),
    row(
        "Wednesday: Closed Thursday through Friday",
        "other",
        confidence=0.3,
        notes=("date_mismatch",),
    ),
    row("Wednesday: Closed Thursday and Friday", "other", confidence=0.3, notes=("date_mismatch",)),
    row("Tomorrow: Closed tomorrow and Friday", "closed", jan(21, 23)),
    row("Today: Closed tomorrow and Friday", "other", confidence=0.3, notes=("date_mismatch",)),
    row("Jan 22: Closed Jan 22 and Jan 23", "closed", jan(22, 23)),
    row("Jan 21: Closed Jan 22 and Jan 23", "other", confidence=0.3, notes=("date_mismatch",)),
]

TABLES = (DAY_NUMBERS, COUNTS, LONG_RANGES, RUNS, HEADINGS)


@pytest.mark.parametrize("case", DAY_NUMBERS)
def test_a_weekday_with_a_day_number_names_that_date(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", COUNTS)
def test_a_count_after_a_weekday_is_no_day_number(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", LONG_RANGES)
def test_a_range_of_weeks_keeps_every_school_day(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", RUNS)
def test_a_run_said_in_two_parts_is_one_run(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", HEADINGS)
def test_a_heading_restating_a_run_s_first_day_is_read_once(case: Row) -> None:
    check(case)


def test_the_tables_cover_every_form() -> None:
    assert sum(map(len, TABLES)) >= 40


# Properties ---------------------------------------------------------------------------------

WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
posted_days = st.dates(min_value=date(2020, 1, 1), max_value=date(2032, 12, 31))


def _ordinal(day: int) -> str:
    if day in {11, 12, 13}:
        return f"{day}th"
    return f"{day}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th') }"


# Up to 20 days ahead no other date with that number falls on that weekday nearer the named
# day: the same date four weeks back is more than a week before it. (From 21 days on, "Monday
# the 1st" posted on Tuesday, February 2, 2021 could as well be the day before.)
@settings(max_examples=300, deadline=None)
@given(
    posted=posted_days,
    ahead=st.integers(min_value=1, max_value=20),
    status=st.sampled_from(("Closed", "Remote learning", "Closed through")),
)
def test_a_weekday_and_its_own_day_number_always_agree(
    posted: date, ahead: int, status: str
) -> None:
    target = posted + timedelta(days=ahead)
    text = f"{status} {WEEKDAY_NAMES[target.weekday()]} the {_ordinal(target.day)}"
    result = parse_status(
        text, posted_at=datetime(posted.year, posted.month, posted.day, 6, tzinfo=ZONE), tz=TZ
    )
    assert "date_mismatch" not in result.notes
    days = {day for entry in result.schedule for day in entry.dates}
    assert target in days or target.weekday() >= 5
    assert all(day <= target for day in days)


@settings(max_examples=200, deadline=None)
@given(
    posted=posted_days.filter(lambda day: day.weekday() < 5),
    weeks=st.integers(min_value=1, max_value=12),
)
def test_a_range_of_up_to_twelve_weeks_keeps_every_school_day(posted: date, weeks: int) -> None:
    last = posted + timedelta(weeks=weeks)
    text = f"Closed through {last:%B} {last.day}, {last.year}"
    result = parse_status(
        text, posted_at=datetime(posted.year, posted.month, posted.day, 6, tzinfo=ZONE), tz=TZ
    )
    assert result.kind == "closed"
    assert result.dates == school_days(posted, last)
    assert "invalid_date" not in result.notes
