"""Early closings after the school day, and closing times late in the afternoon.

Every text here is a phrasing pattern written for these tests, not a claim
about a real school. Unless a row says otherwise it is posted at 6 a.m. on
Tuesday 20 January 2026 in New York, so "today" is Tuesday the 20th and
"tomorrow" Wednesday the 21st.

* An early closing at a time no school day ends ("TODAY: CLOSING EARLY AT
  05:00 PM", "Closing Early Monday 05:00 PM", "Early dismissal at 6:00 PM",
  "Closing early at 12:00 AM") closes the building for the evening or the
  night: kind ``other`` at 0.9 with the note ``activities_cancelled``, as
  "Closed after 5 PM" is, and no early dismissal in the schedule. The school
  day ends by 4:30 p.m.; 4:31 p.m. is the evening.
* An early dismissal in the early morning ("Early dismissal 7:00", "Early
  release at 6:30 AM") cannot be placed at all: ``other`` at 0.3.
* A closing time with no word saying it is early is an early dismissal up to
  2:30 p.m. ("Closing at 2:30 PM"). Later ("Closing at 3:00 PM") it is when
  many schools let out anyway, so it is unclear, as "Closed after 3:30" is;
  beside an early dismissal that gives no time ("Early release. Closing at
  3:00 today.") it is that dismissal's time.
* A closing at a time that runs over several days ("Closing at 1:00 PM today
  through Friday", "Closed from noon Wednesday through Thursday") is an early
  dismissal on its first day at 0.8. The days after it fit a closing at that
  time each day as well as a closure, so they state nothing.
"""

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from snowlight.classify import parse_status

TZ = "America/New_York"
ZONE = ZoneInfo(TZ)
TUE = datetime(2026, 1, 20, 6, 0, tzinfo=ZONE)
TUE_AFTERNOON = datetime(2026, 1, 20, 13, 0, tzinfo=ZONE)
MON_EVENING = datetime(2026, 1, 26, 18, 30, tzinfo=ZONE)


def jan(*days: int) -> tuple[date, ...]:
    return tuple(date(2026, 1, day) for day in days)


@dataclass(frozen=True)
class Row:
    text: str
    posted: datetime
    kind: str
    dates: tuple[date, ...]
    confidence: float
    notes: tuple[str, ...]
    opens_at: time | None
    dismissal: time | None
    reason: str | None


def row(  # noqa: PLR0913 - one table row
    text: str,
    kind: str,
    dates: tuple[date, ...] = (),
    *,
    posted: datetime = TUE,
    confidence: float = 0.9,
    notes: tuple[str, ...] = (),
    opens_at: time | None = None,
    dismissal: time | None = None,
    reason: str | None = None,
) -> object:
    case = Row(text, posted, kind, dates, confidence, notes, opens_at, dismissal, reason)
    return pytest.param(case, id=f"{text} @ {posted:%a %H:%M}")


def evening(text: str, *, posted: datetime = TUE, reason: str | None = None) -> object:
    """An early closing after the school day: the evening's activities, no status."""
    return row(text, "other", posted=posted, notes=("activities_cancelled",), reason=reason)


def unplaced(text: str) -> object:
    """An early dismissal at a time no school day could end: no status."""
    return row(text, "other", confidence=0.3, notes=("ambiguous",))


def check(case: Row) -> None:
    result = parse_status(case.text, posted_at=case.posted, tz=TZ)
    assert result.kind == case.kind
    assert result.dates == case.dates
    assert result.confidence == case.confidence
    assert result.notes == case.notes
    assert result.opens_at == case.opens_at
    assert result.dismissal_time == case.dismissal
    assert result.reason == case.reason
    if case.kind == "other":
        assert result.schedule == ()
    else:
        assert result.schedule[0].kind == case.kind


# "TODAY: CLOSING EARLY AT hh:mm PM", as some closings pages write every entry.
DAY_HEADED = [
    evening("TODAY: CLOSING EARLY AT 05:00 PM"),
    evening("TODAY: CLOSING EARLY AT 05:30 PM"),
    evening("TODAY: CLOSING EARLY AT 06:00 PM"),
    evening("TODAY: CLOSING EARLY AT 07:00 PM"),
    evening("TODAY: CLOSING EARLY AT 09:00 PM"),
    evening("TODAY: CLOSING EARLY AT 04:45 PM"),
    evening("TODAY: CLOSING EARLY AT 6::00 PM"),  # (a doubled colon: still 6 p.m.)
    evening("TOMORROW: CLOSING EARLY AT 05:00 PM"),
    evening("Today: Closing early at 5 PM"),
    evening("TODAY: CLOSING EARLY AT 05:00 PM", posted=TUE_AFTERNOON),
]

# "Closing Early <day> hh:mm PM" and "Closing Early at hh:mm PM <day>".
DAY_BETWEEN = [
    evening("Closing Early Monday 05:00 PM"),
    evening("Closing Early Tuesday 05:00 PM"),
    evening("Closing Early Wednesday 06:00 PM"),
    evening("Closing Early Thursday 07:00 PM"),
    evening("Closing Early Friday 11:00 PM"),
    evening("Closing Early Wednesday 05:00PM"),
    evening("Closing early tomorrow 6:30 PM"),
    evening("Closing Early Monday 05:00 PM", posted=MON_EVENING),
    evening("Closing Early at 5:00PM Thursday"),
    evening("Closing Early at 5:00 PM Wednesday"),
    evening("Closing early at 5:00 PM Today"),
    evening("Closing early today at 5:00 PM"),
    evening("Closing early at 5 pm tonight"),
    evening("Closing early Wednesday at 5:30 PM"),
]

# Other early-dismissal words at an evening time, and at night.
OTHER_WORDS = [
    evening("Early dismissal at 6:00 PM"),
    evening("Early dismissal at 6"),  # a bare 6 is 6 p.m.
    evening("Early Dismissal: 5:30 PM"),
    evening("Early dismissal time 6 PM"),
    evening("Early release at 5 pm"),
    evening("Early release at 5:15pm Wednesday"),
    evening("Early out at 7 pm"),
    evening("Closing early at 9:00 PM"),
    evening("Dismissing early at 6 PM"),
    evening("Released early at 5:30 pm"),
    evening("5:00 PM early dismissal"),
    evening("6 PM early release"),
    evening("Closing early at 7p"),
    evening("Tomorrow: Early dismissal at 6:00 PM due to snow", reason="Winter storm"),
    evening("Early dismissal at 6:00 PM, all activities cancelled"),
    evening("Closing early at 12:00 AM Today"),
    evening("Closing early at 2:30 AM Today"),
    # Before any school day could end: nothing to place.
    unplaced("Early dismissal 7:00"),
    unplaced("Early release at 6:30 AM"),
    unplaced("Closing early at 7:30 AM"),
]

# Beside a status of the school day, the evening closing is a side note.
BESIDE_A_STATUS = [
    row(
        "Early dismissal at 1:00 PM; closing early at 5 PM for evening activities",
        "early_dismissal",
        jan(20),
        notes=("activities_cancelled",),
        dismissal=time(13),
    ),
    row(
        "Closed tomorrow. Today: closing early at 5:00 PM",
        "closed",
        jan(21),
        confidence=0.95,
        notes=("activities_cancelled",),
    ),
    row(
        "Delayed start, opening at 10:00 on 1/21; closing early at 5:00 PM",
        "delayed",
        jan(21),
        confidence=0.95,
        notes=("activities_cancelled",),
        opens_at=time(10),
    ),
]

# Up to 4:30 p.m. an early closing is an early dismissal at that time.
SCHOOL_DAY = [
    row("Closing early at 4:30 PM", "early_dismissal", jan(20), dismissal=time(16, 30)),
    row("Closing early at 3:00 PM", "early_dismissal", jan(20), dismissal=time(15)),
    row("Early dismissal at 1:00 PM", "early_dismissal", jan(20), dismissal=time(13)),
    row("Early dismissal at 1p", "early_dismissal", jan(20), dismissal=time(13)),
    row(
        "TODAY: CLOSING EARLY AT 03:00 PM",
        "early_dismissal",
        jan(20),
        confidence=0.95,
        dismissal=time(15),
    ),
    row(
        "Closing Early Wednesday 03:00 PM",
        "early_dismissal",
        jan(21),
        confidence=0.95,
        dismissal=time(15),
    ),
    row(
        "Closing Early at 1:00PM Thursday",
        "early_dismissal",
        jan(22),
        confidence=0.95,
        dismissal=time(13),
    ),
]

# A closing time with no word saying it is early.
CLOSING_TIMES = [
    row("Closing at 2:30 PM", "early_dismissal", jan(20), dismissal=time(14, 30)),
    row("Closing at 2 PM", "early_dismissal", jan(20), dismissal=time(14)),
    row(
        "Closing at 11:30 AM Wednesday",
        "early_dismissal",
        jan(21),
        confidence=0.95,
        dismissal=time(11, 30),
    ),
    row("Closing at 3:00 PM", "other", confidence=0.3, notes=("ambiguous",)),
    row("Closing at 4pm", "other", confidence=0.3, notes=("ambiguous",)),
    row("Closing at 3:30 PM Today", "other", confidence=0.3, notes=("ambiguous",)),
    row("Closing at 3 p.m. Wednesday", "other", confidence=0.3, notes=("ambiguous",)),
    row("Wednesday: Closing at 3:00 PM", "other", confidence=0.3, notes=("ambiguous",)),
    row(
        "Closed at 3 PM Wednesday, no after care",
        "other",
        confidence=0.3,
        notes=("ambiguous", "childcare"),
    ),
    row("Closing at 5 PM", "other", confidence=0.3, notes=("ambiguous",)),
    # Beside an early dismissal with no time of its own, the closing time is its time.
    row(
        "Early release. Closing at 3:00 today.",
        "early_dismissal",
        jan(20),
        confidence=0.95,
        dismissal=time(15),
    ),
    row(
        "Early release. The school will be closing at 4:00 today.",
        "early_dismissal",
        jan(20),
        confidence=0.95,
        dismissal=time(16),
    ),
    # Offices closing at a time are the offices' news, and say nothing is closed.
    row(
        "Early dismissal at 1:00, offices close at 3",
        "early_dismissal",
        jan(20),
        dismissal=time(13),
    ),
]

# A closing at a time that runs over several days: its first day.
RUNS = [
    row(
        "Closing at 1:00 PM Today Through Friday",
        "early_dismissal",
        jan(20),
        confidence=0.8,
        notes=("ambiguous",),
        dismissal=time(13),
    ),
    row(
        "Closing at 1 PM today (Tuesday) through Friday",
        "early_dismissal",
        jan(20),
        confidence=0.8,
        notes=("ambiguous",),
        dismissal=time(13),
    ),
    row(
        "Closing at noon Wednesday through Thursday",
        "early_dismissal",
        jan(21),
        confidence=0.8,
        notes=("ambiguous",),
        dismissal=time(12),
    ),
    row(
        "Closed Wednesday 12p thru Thursday",
        "early_dismissal",
        jan(21),
        confidence=0.8,
        notes=("ambiguous",),
        dismissal=time(12),
    ),
    row(
        "Closed from noon Wednesday through Thursday",
        "early_dismissal",
        jan(21),
        confidence=0.8,
        notes=("ambiguous",),
        dismissal=time(12),
    ),
    row(
        "Closing at noon through Friday",
        "early_dismissal",
        jan(20),
        confidence=0.8,
        notes=("ambiguous",),
        dismissal=time(12),
    ),
    # The run's end still places its first day: Saturday before this Monday.
    row(
        "Closing 2 p.m. Saturday through Monday",
        "early_dismissal",
        jan(24),
        posted=MON_EVENING,
        confidence=0.7,
        notes=("ambiguous", "weekend"),
        dismissal=time(14),
    ),
    # "Early" says each day closes early; "all day" says the later day is closed.
    row(
        "Closing Early Wednesday thru Friday 1 Hour",
        "early_dismissal",
        jan(21, 22, 23),
        confidence=0.95,
    ),
    row(
        "Closing at 11:30 Wednesday and all day Thursday",
        "early_dismissal",
        jan(21),
        confidence=0.95,
        dismissal=time(11, 30),
    ),
    # "Dismissing" at a time each day is an early dismissal each day.
    row(
        "Dismissing at noon Wednesday through Friday",
        "early_dismissal",
        jan(21, 22, 23),
        confidence=0.8,
        dismissal=time(12),
    ),
    # Days listed before a run: the run could be closed all day, so the first day alone.
    row(
        "Closing at noon Wednesday; Thursday through Friday",
        "early_dismissal",
        jan(21),
        confidence=0.8,
        notes=("ambiguous",),
        dismissal=time(12),
    ),
    row(
        "Closing at noon Wednesday, and Thursday-Friday",
        "early_dismissal",
        jan(21),
        confidence=0.8,
        notes=("ambiguous",),
        dismissal=time(12),
    ),
    row(
        "Closing at noon Wednesday (Thursday - Friday)",
        "early_dismissal",
        jan(21),
        confidence=0.8,
        notes=("ambiguous",),
        dismissal=time(12),
    ),
]

# A day heading the entry names the run's first day again, and the two must agree.
HEADED_RUNS = [
    row(
        "Tuesday: Closing at noon today through Friday",
        "early_dismissal",
        jan(20),
        confidence=0.8,
        notes=("ambiguous",),
        dismissal=time(12),
    ),
    row(
        "Tuesday: Closing at noon through Friday",
        "early_dismissal",
        jan(20),
        confidence=0.8,
        notes=("ambiguous",),
        dismissal=time(12),
    ),
    row(
        "Wednesday: Closing at noon Wednesday through Friday",
        "early_dismissal",
        jan(21),
        confidence=0.8,
        notes=("ambiguous",),
        dismissal=time(12),
    ),
    row(
        "Wednesday: Closing at noon Thursday through Friday",
        "other",
        confidence=0.3,
        notes=("ambiguous", "date_mismatch"),
    ),
    # A run apart from the first day, with words between: which days close early is unclear.
    row(
        "Closing at noon Wednesday then Thursday through Friday",
        "other",
        confidence=0.3,
        notes=("ambiguous",),
    ),
]

# A time no clock has: the early dismissal stands, with no time.
NO_CLOCK = [
    row("Early dismissal at 25:00", "early_dismissal", jan(20)),
    row("Closing early at 13:75", "early_dismissal", jan(20)),
]

TABLES = (
    DAY_HEADED, DAY_BETWEEN, OTHER_WORDS, BESIDE_A_STATUS, SCHOOL_DAY, CLOSING_TIMES, RUNS,
    HEADED_RUNS, NO_CLOCK,
)  # fmt: skip


@pytest.mark.parametrize("case", DAY_HEADED)
def test_a_day_headed_early_closing_in_the_evening_is_no_dismissal(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", DAY_BETWEEN)
def test_an_early_closing_on_a_day_in_the_evening_is_no_dismissal(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", OTHER_WORDS)
def test_early_dismissal_words_at_night_are_no_dismissal(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", BESIDE_A_STATUS)
def test_an_evening_closing_beside_a_status_is_a_side_note(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", SCHOOL_DAY)
def test_an_early_closing_in_the_school_day_keeps_its_time(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", CLOSING_TIMES)
def test_a_closing_time_late_in_the_afternoon_is_unclear(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", RUNS)
def test_a_timed_closing_over_several_days_is_its_first_day(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", HEADED_RUNS)
def test_a_heading_before_a_timed_run_must_name_its_first_day(case: Row) -> None:
    check(case)


# A number after the words that is a count or a grade is no time, of the evening or any other.
@pytest.mark.parametrize(
    "text",
    [
        "Early dismissal 5th grade",
        "Early dismissal 7th and 8th grade",
        "Early dismissal at 5 schools",
        "Early Dismissal - 6 campuses",
        "Closing early at 5 locations",
    ],
)
def test_a_count_after_an_early_dismissal_is_no_evening(text: str) -> None:
    result = parse_status(text, posted_at=TUE, tz=TZ)
    assert "activities_cancelled" not in result.notes
    assert result.dismissal_time is None


@pytest.mark.parametrize("case", NO_CLOCK)
def test_a_time_no_clock_has_leaves_the_dismissal_without_one(case: Row) -> None:
    check(case)


def test_the_tables_cover_every_form() -> None:
    assert sum(map(len, TABLES)) >= 70


def test_an_evening_closing_leaves_no_schedule_entry() -> None:
    result = parse_status("Closing Early at 5:00PM Thursday", posted_at=TUE, tz=TZ)
    assert result.schedule == ()
    assert result.dismissal_time is None
    assert result.dates_stated is False


# Properties ---------------------------------------------------------------------------------

ZONES = ("America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles")
instants = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2032, 12, 31),
    timezones=st.sampled_from([ZoneInfo(name) for name in ZONES]),
)
EARLY_WORDS = (
    "Closing early at", "CLOSING EARLY AT", "Early dismissal at", "Early release at",
    "Dismissing early at", "Early Dismissal:", "Early out at", "Released early at",
)  # fmt: skip
DAYS = ("", "Today ", "TODAY: ", "Tomorrow: ", "Wednesday: ", "Friday ")
DAYS_AFTER = ("", " today", " Wednesday", " Friday", " tomorrow")


def _clock_text(value: time, style: int) -> str:
    """``value`` written one of the ways listings write times, with its meridiem."""
    hour = value.hour % 12 or 12
    meridiem = "PM" if value.hour >= 12 else "AM"
    if style == 0:
        return f"{hour}:{value.minute:02d} {meridiem}"
    if style == 1:
        return f"{hour:02d}:{value.minute:02d} {meridiem}"
    if style == 2:
        return f"{hour}:{value.minute:02d}{meridiem.lower()}"
    return f"{hour}:{value.minute:02d} {meridiem[0].lower()}.m."


evening_times = st.builds(
    time, st.integers(min_value=16, max_value=23), st.sampled_from((0, 15, 30, 45))
).filter(lambda value: value > time(16, 30))
school_day_times = st.builds(
    time, st.integers(min_value=9, max_value=16), st.sampled_from((0, 15, 30, 45))
).filter(lambda value: value <= time(16, 30))


@settings(max_examples=300, deadline=None)
@given(
    words=st.sampled_from(EARLY_WORDS),
    value=evening_times,
    style=st.integers(min_value=0, max_value=3),
    before=st.sampled_from(DAYS),
    after=st.sampled_from(DAYS_AFTER),
    posted=instants,
)
def test_an_early_closing_after_the_school_day_is_never_a_dismissal(  # noqa: PLR0913, PLR0917
    words: str, value: time, style: int, before: str, after: str, posted: datetime
) -> None:
    text = f"{before}{words} {_clock_text(value, style)}{after}"
    result = parse_status(text, posted_at=posted, tz=TZ)
    assert result.kind == "other"
    assert result.schedule == ()
    assert "activities_cancelled" in result.notes
    assert result.confidence == 0.9


@settings(max_examples=300, deadline=None)
@given(
    words=st.sampled_from(EARLY_WORDS),
    value=school_day_times,
    style=st.integers(min_value=0, max_value=3),
    posted=instants,
)
def test_an_early_closing_in_the_school_day_is_a_dismissal_at_that_time(
    words: str, value: time, style: int, posted: datetime
) -> None:
    text = f"{words} {_clock_text(value, style)} tomorrow"
    result = parse_status(text, posted_at=posted, tz=TZ)
    assert result.kind == "early_dismissal"
    assert result.dismissal_time == value
    assert all(entry.kind == "early_dismissal" for entry in result.schedule)


@settings(max_examples=200, deadline=None)
@given(
    value=st.builds(
        time, st.integers(min_value=14, max_value=16), st.sampled_from((0, 15, 30, 45))
    ).filter(lambda value: time(14, 30) < value <= time(16, 30)),
    style=st.integers(min_value=0, max_value=3),
    verb=st.sampled_from(("Closing at", "Closing", "Will close at", "Closes at", "CLOSING AT")),
    posted=instants,
)
def test_a_plain_closing_time_late_in_the_afternoon_is_never_a_status(
    value: time, style: int, verb: str, posted: datetime
) -> None:
    result = parse_status(f"{verb} {_clock_text(value, style)}", posted_at=posted, tz=TZ)
    assert result.kind == "other"
    assert result.confidence <= 0.3
