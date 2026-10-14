"""A closure limited to part of a day is not a closure of the day.

Every text here is a phrasing pattern written for these tests, not a claim
about a real school. Unless a row says otherwise it is posted at 6 a.m. on
Tuesday 20 January 2026 in New York, so "today" is Tuesday the 20th and
"tomorrow" Wednesday the 21st.

* Closed for the afternoon ("Closed this afternoon", "Closed Wednesday PM",
  "Wednesday afternoon: Closed", "Closed for the afternoon", "Closed after
  lunch") sends students home during a day that has begun: an early dismissal,
  at 0.8 as the time is not given. Closed from a time on ("Closed after 11:30",
  "Closed from noon", "Closed after 12") is an early dismissal at that time.
* Closed for the morning ("Closed Wednesday AM", "Closed tomorrow morning") is a
  late start when the text says when school opens ("Closed tomorrow until 10",
  "Closed Wednesday AM, reopening at 11"), and otherwise ``other`` at 0.3.
* A part of the day before a program noun ("Closed AM kindergarten") is part of
  the program; a time after the school day ("Closed after 5 PM") the evening.
* A day bounded among others keeps the others closed: "Closed this afternoon
  and tomorrow" is an early dismissal today and a closure tomorrow.
* The morning and the afternoon together are the whole day ("Closed AM and PM").
"""

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from snowlight.classify import parse_status

TZ = "America/New_York"
ZONE = ZoneInfo(TZ)
MORNING = datetime(2026, 1, 20, 6, 0, tzinfo=ZONE)  # Tuesday
AFTERNOON = datetime(2026, 1, 20, 13, 0, tzinfo=ZONE)
EVENING = datetime(2026, 1, 20, 20, 0, tzinfo=ZONE)


def jan(*days: int) -> tuple[date, ...]:
    return tuple(date(2026, 1, day) for day in days)


def at(hour: int, minute: int = 0) -> time:
    return time(hour, minute)


type Entry = tuple[str, tuple[date, ...]]


@dataclass(frozen=True)
class Row:
    text: str
    posted: datetime
    kind: str
    dates: tuple[date, ...]
    confidence: float
    notes: tuple[str, ...]
    dismissal: time | None
    opens_at: time | None
    delay: int | None
    schedule: tuple[Entry, ...] | None


def row(  # noqa: PLR0913 - one table row
    text: str,
    kind: str = "other",
    dates: tuple[date, ...] = (),
    *,
    posted: datetime = MORNING,
    confidence: float = 0.8,
    notes: tuple[str, ...] = (),
    dismissal: time | None = None,
    opens_at: time | None = None,
    delay: int | None = None,
    schedule: tuple[Entry, ...] | None = None,
) -> object:
    label = f"{text} @ {posted:%a %H:%M}"
    case = Row(text, posted, kind, dates, confidence, notes, dismissal, opens_at, delay, schedule)
    return pytest.param(case, id=label)


def early(
    text: str,
    dates: tuple[date, ...],
    *,
    posted: datetime = MORNING,
    confidence: float = 0.8,
    dismissal: time | None = None,
) -> object:
    """An early dismissal: at 0.8 with no time, at the status's own confidence with one."""
    return row(
        text,
        "early_dismissal",
        dates,
        posted=posted,
        confidence=confidence,
        dismissal=dismissal,
        schedule=(("early_dismissal", dates),),
    )


def unclear(text: str, *, posted: datetime = MORNING, notes: tuple[str, ...] = ()) -> object:
    """A closure nobody can act on: other at 0.3, noted as ambiguous."""
    return row(text, posted=posted, confidence=0.3, notes=("ambiguous", *notes))


def check(case: Row) -> None:
    result = parse_status(case.text, posted_at=case.posted, tz=TZ)
    assert result.kind == case.kind
    assert result.dates == case.dates
    assert result.confidence == case.confidence
    assert set(case.notes) <= set(result.notes)
    assert result.dismissal_time == case.dismissal
    assert result.opens_at == case.opens_at
    assert result.delay_minutes == case.delay
    if case.kind == "other":
        assert result.schedule == ()
    if case.schedule is not None:
        assert tuple((entry.kind, entry.dates) for entry in result.schedule) == case.schedule


# The forms the afternoon takes: an early dismissal with no time given.
AFTERNOONS = [
    early("Closed this afternoon", jan(20)),
    early("Closed this afternoon", jan(20), posted=AFTERNOON),
    early("Closed this afternoon", jan(20), posted=EVENING),
    early("Closed Wednesday afternoon", jan(21)),
    early("Closed Wednesday afternoon", jan(21), posted=EVENING),
    early("Wednesday afternoon: Closed", jan(21)),
    early("Wednesday afternoon - Closed", jan(21)),
    early("Closed PM", jan(20)),
    early("Closed PM", jan(20), posted=AFTERNOON),
    early("Closed PM", jan(21), posted=EVENING),
    early("Closed P.M.", jan(20)),
    early("Closed PM only", jan(20)),
    early("Closed Wednesday PM", jan(21)),
    early("Closed Wed. p.m.", jan(21)),
    early("Closed tomorrow afternoon", jan(21), posted=EVENING),
    early("Closed for the afternoon", jan(20)),
    early("Closed for the afternoon", jan(21), posted=EVENING),
    early("Closed in the afternoon", jan(20)),
    early("Closed all afternoon", jan(20)),
    early("Closed the rest of the afternoon", jan(20)),
    early("Closed for the afternoon session", jan(20)),
    early("Closed Wednesday for the afternoon", jan(21)),
    early("Closed after lunch", jan(20)),
    early("Closed after lunch", jan(20), posted=AFTERNOON),
    early("Closed after lunchtime", jan(20)),
    early("Closed after recess", jan(20)),
    early("Closed after 1st period", jan(20)),
    early("Closed after 3rd period", jan(20)),
    early("Closed after first period today", jan(20)),
    early("Closed Wednesday afternoon and evening", jan(21)),
    early("Closed for the afternoon and evening", jan(20)),
    early("Closed 1/21 PM", jan(21)),
    early("Closed Wednesday 1/21 afternoon", jan(21)),
    early("PM: Closed", jan(20)),
    early("Afternoon: closed", jan(20)),
    early("Wednesday PM: Closed", jan(21)),
    early("This afternoon: closed", jan(20)),
    early("No school this afternoon", jan(20)),
    early("No school Wednesday afternoon", jan(21)),
    early("No school in the afternoon", jan(20)),
    early("Classes cancelled this afternoon", jan(20)),
    early("Classes cancelled for the afternoon", jan(20)),
    early("School closed this afternoon due to snow", jan(20)),
    early("Schools closed this afternoon; activities cancelled", jan(20)),
    early("Closing this afternoon", jan(20)),
    early("Closing Wednesday afternoon", jan(21)),
    early("Schools closing after lunch", jan(20)),
    early("Closing after 1st period", jan(20)),
    # In brackets, or after a comma, the part ends its phrase.
    early("Closed (PM)", jan(20)),
    early("Status: Closed (PM)", jan(20)),
    early("Closed tomorrow (afternoon only)", jan(21)),
    early("Closed tomorrow, after lunch.", jan(21)),
    # One day named twice: one bound for both.
    early("Closed this afternoon (Jan. 20)", jan(20)),
    early("Closed this afternoon, Jan. 20", jan(20)),
]

# From a time on: an early dismissal at that time.
FROM_A_TIME = [
    early("Closed after 11:30", jan(20), confidence=0.9, dismissal=at(11, 30)),
    early("Closed after 11:30", jan(20), posted=AFTERNOON, confidence=0.9, dismissal=at(11, 30)),
    early("Closed after 11:30", jan(21), posted=EVENING, confidence=0.9, dismissal=at(11, 30)),
    early("Closed after 11:30 am", jan(20), confidence=0.9, dismissal=at(11, 30)),
    early("Closed from noon", jan(20), confidence=0.9, dismissal=at(12)),
    early("Closed from 12 noon", jan(20), confidence=0.9, dismissal=at(12)),
    early("Closed after noon", jan(20), confidence=0.9, dismissal=at(12)),
    early("Closed after 12", jan(20), confidence=0.9, dismissal=at(12)),
    early("Closed after 1", jan(20), confidence=0.9, dismissal=at(13)),
    early("Closed after 12:30 PM", jan(20), confidence=0.9, dismissal=at(12, 30)),
    early("Closed after 2 PM due to snow", jan(20), confidence=0.9, dismissal=at(14)),
    early("Closed starting at noon", jan(20), confidence=0.9, dismissal=at(12)),
    early("Closed beginning at 1 pm", jan(20), confidence=0.9, dismissal=at(13)),
    early("Closed as of noon", jan(20), confidence=0.9, dismissal=at(12)),
    early("Closed effective 11:00", jan(20), confidence=0.9, dismissal=at(11)),
    early("Closed after 12 due to icy roads", jan(20), confidence=0.9, dismissal=at(12)),
    early("Schools closing after 11:30 today", jan(20), confidence=0.9, dismissal=at(11, 30)),
    early("Closed tomorrow after 11:30", jan(21), confidence=0.95, dismissal=at(11, 30)),
    early("Closed after 11:30 today", jan(20), confidence=0.95, dismissal=at(11, 30)),
    early("Closed after 11:30 tomorrow", jan(21), confidence=0.95, dismissal=at(11, 30)),
    early("Closed Wednesday from noon", jan(21), confidence=0.95, dismissal=at(12)),
    early("Closed this afternoon after 1", jan(20), confidence=0.95, dismissal=at(13)),
    early("Closed Wednesday afternoon from 12:30", jan(21), confidence=0.95, dismissal=at(12, 30)),
    early("Closed today (after 12:30)", jan(20), confidence=0.95, dismissal=at(12, 30)),
    early("Closed after 12:00 on Wednesday", jan(21), confidence=0.95, dismissal=at(12)),
    # The same with the verbs that already read this way.
    early("Closing at 2 PM due to snow", jan(20), confidence=0.9, dismissal=at(14)),
    early("Closed at 1 PM", jan(20), confidence=0.9, dismissal=at(13)),
    early("Closed tomorrow at noon", jan(21), confidence=0.95, dismissal=at(12)),
]

# The morning alone, with no opening time: other at 0.3.
MORNINGS = [
    unclear("Closed Wednesday AM"),
    unclear("Closed Wednesday AM", posted=EVENING),
    unclear("Closed tomorrow morning"),
    unclear("Closed tomorrow morning", posted=EVENING),
    unclear("Closed this morning"),
    unclear("Closed AM"),
    unclear("Closed A.M."),
    unclear("Closed for the morning"),
    unclear("Closed in the morning"),
    unclear("Closed Wednesday in the morning"),
    # ("Wednesday Morning: Closed" is a closings page's slot for the day: see
    # test_classify_slots.py. Other words for the morning in a heading say the morning.)
    unclear("Wednesday AM: Closed"),
    unclear("Wed. AM: Closed"),
    unclear("Tomorrow morning: Closed"),
    unclear("This morning: Closed"),
    unclear("Next Wednesday morning: Closed"),
    unclear("AM - Closed"),
    unclear("Morning: closed"),
    unclear("No school tomorrow morning"),
    unclear("No school Wednesday morning"),
    unclear("Classes cancelled tomorrow morning"),
    unclear("Closed tomorrow morning due to icy roads"),
    unclear("Closed tomorrow (morning)"),
    unclear("Closed: AM"),
    # A status beside it that names no day could be for that day as much as any.
    unclear("Closed tomorrow morning. No school.", notes=("undated",)),
    unclear("Closed tomorrow morning. Remote learning.", notes=("undated",)),
    # The opening time of one site is that site's, not the school's: the morning stays unclear.
    unclear("Closed this morning. Learning Center to open at 10.", notes=("ambiguous",)),
    unclear("This morning: Closed due to snow: Learning Center to open at 10.",
            notes=("ambiguous",)),
    unclear("Closed tomorrow morning. Main campus will open at 10.", notes=("ambiguous",)),
    unclear("Closed Wednesday AM; the annex opens at 11", notes=("ambiguous",)),
]  # fmt: skip

# The morning with the time school opens: a late start.
REOPENINGS = [
    row("Closed tomorrow until 10", "delayed", jan(21), confidence=0.95, opens_at=at(10)),
    row("Closed tomorrow until 10", "delayed", jan(21), posted=EVENING, confidence=0.95,
        opens_at=at(10)),
    row("Closed tomorrow until noon", "delayed", jan(21), confidence=0.95, opens_at=at(12)),
    row("Closed tomorrow morning until 10:30", "delayed", jan(21), confidence=0.95,
        opens_at=at(10, 30)),
    row("Closed Wednesday AM, reopening at 11", "delayed", jan(21), confidence=0.95,
        opens_at=at(11)),
    row("Closed Wednesday AM, re-opening at 11", "delayed", jan(21), confidence=0.95,
        opens_at=at(11)),
    row("Closed tomorrow morning, opening at 11:00", "delayed", jan(21), confidence=0.95,
        opens_at=at(11)),
    row("Closed tomorrow morning. Opening at 10 AM.", "delayed", jan(21), confidence=0.95,
        opens_at=at(10)),
    row("Closed this morning, reopening at noon", "delayed", jan(20), confidence=0.95,
        opens_at=at(12)),
    row("Closed Wednesday AM; 2 hour delay", "delayed", jan(21), confidence=0.95, delay=120),
    row("Closed Wednesday morning; late start", "delayed", jan(21), confidence=0.9),
    row("Closed tomorrow morning due to icy roads, opening at 10", "delayed", jan(21),
        confidence=0.95, opens_at=at(10)),
    row("Closed tomorrow morning, buses on snow routes, opening at 10", "delayed", jan(21),
        confidence=0.95, opens_at=at(10), notes=("transportation",)),
    # The school's own opening, or its buildings': the school's late start.
    row("Closed this morning: school to open at 10.", "delayed", jan(20), confidence=0.95,
        opens_at=at(10)),
    row("Closed tomorrow morning; buildings open at 10", "delayed", jan(21), confidence=0.95,
        opens_at=at(10)),
    # Already read this way.
    row("Closed until 11", "delayed", jan(20), confidence=0.9, opens_at=at(11)),
    row("Reopening at 10:00", "delayed", jan(20), confidence=0.9, opens_at=at(10)),
    row("School reopens at 11 AM", "delayed", jan(20), confidence=0.9, opens_at=at(11)),
]  # fmt: skip

# Part of the program, or the evening: no school day status.
NOT_THE_DAY = [
    row("Closed AM kindergarten", confidence=0.9, notes=("partial_program",)),
    row("Closed PM kindergarten", confidence=0.9, notes=("partial_program",)),
    row("Closed AM pre-k", confidence=0.9, notes=("partial_program",)),
    row("Wednesday PM kindergarten: closed", confidence=0.9, notes=("partial_program",)),
    row("PM kindergarten closed", confidence=0.9, notes=("partial_program",)),
    # A time for part of the program: the day's time is left unsaid.
    row(
        "Closed after 11:30. Kindergarten early dismissal at 10:30.",
        "early_dismissal",
        jan(20),
        notes=("partial_program",),
    ),
    row("Afternoon classes cancelled", confidence=0.9, notes=("partial_program",)),
    row("Closed after 5 PM", confidence=0.9, notes=("activities_cancelled",)),
    row("Closing after 5 PM", confidence=0.9, notes=("activities_cancelled",)),
    row("Closed after 6:30 pm", confidence=0.9, notes=("activities_cancelled",)),
    row("Closed Wednesday evening", confidence=0.9, notes=("activities_cancelled",)),
]

# Hours that cannot be read safely: other at 0.3.
UNCLEAR_HOURS = [
    unclear("Closed from 8 to noon"),
    unclear("Closed from 12 to 3"),
    row("Closed after 12-3", confidence=0.3, notes=("unreadable_date",)),
    unclear("School closed Wednesday from 8 am"),
    unclear("Buildings closed after 3 PM"),
    unclear("Closed Wednesday until 2 PM"),
    unclear("Closed tomorrow morning after 9"),
    unclear("Closed Monday and Tuesday afternoon"),
    unclear("Closed Wednesday afternoon through Friday"),
    unclear("Closed this afternoon through Friday"),
    unclear("Closed after 12 'til 3"),
    # Two parts, or two times, for one day.
    unclear("Closed PM tomorrow morning"),
    unclear("Closed this afternoon until noon"),
    unclear("Closed from noon tomorrow after 1 pm"),
    unclear("Closed PM today and tomorrow morning"),
    unclear("Closed PM Wednesday afternoon and Thursday morning"),
]

# A bounded day among others: the others stay closed.
SPLITS = [
    row("Closed this afternoon and tomorrow", "early_dismissal", jan(20),
        schedule=(("early_dismissal", jan(20)), ("closed", jan(21)))),
    row("Closed this afternoon and tomorrow", "early_dismissal", jan(20), posted=EVENING,
        schedule=(("early_dismissal", jan(20)), ("closed", jan(21)))),
    row("Closed Wednesday afternoon and Thursday", "early_dismissal", jan(21),
        schedule=(("early_dismissal", jan(21)), ("closed", jan(22)))),
    row("Closed Wednesday afternoon, Thursday and Friday", "early_dismissal", jan(21),
        schedule=(("early_dismissal", jan(21)), ("closed", jan(22, 23)))),
    row("Closed Wednesday after 11:30 and Thursday", "early_dismissal", jan(21),
        confidence=0.95, dismissal=at(11, 30),
        schedule=(("early_dismissal", jan(21)), ("closed", jan(22)))),
    row("Closed today after 12:30 and all day tomorrow", "early_dismissal", jan(20),
        confidence=0.95, dismissal=at(12, 30),
        schedule=(("early_dismissal", jan(20)), ("closed", jan(21)))),
    row("Closed this afternoon. Closed tomorrow.", "early_dismissal", jan(20),
        schedule=(("early_dismissal", jan(20)), ("closed", jan(21)))),
    row("Closed for the rest of the day and tomorrow", "early_dismissal", jan(20),
        confidence=0.95, schedule=(("early_dismissal", jan(20)), ("closed", jan(21)))),
    # A morning left unclear beside a day that is not.
    row("Closed Wednesday afternoon and Thursday morning", "early_dismissal", jan(21),
        notes=("ambiguous",), schedule=(("early_dismissal", jan(21)),)),
    row("Closed Wednesday morning and Thursday", "closed", jan(22), notes=("ambiguous",),
        schedule=(("closed", jan(22)),)),
    row("Closed Wednesday after 5 PM and Thursday", "closed", jan(22), confidence=0.95,
        notes=("activities_cancelled",), schedule=(("closed", jan(22)),)),
    # A timed closing beside a day closed all day.
    row("Closing at 11:30 AM Wednesday and all day Thursday", "early_dismissal", jan(21),
        confidence=0.95, dismissal=at(11, 30),
        schedule=(("early_dismissal", jan(21)), ("closed", jan(22)))),
    row("Closing at noon today and all day tomorrow", "early_dismissal", jan(20),
        confidence=0.95, dismissal=at(12),
        schedule=(("early_dismissal", jan(20)), ("closed", jan(21)))),
    row("Closing at noon Wednesday, Thursday all day", "early_dismissal", jan(21),
        confidence=0.95, dismissal=at(12),
        schedule=(("early_dismissal", jan(21)), ("closed", jan(22)))),
    row("Closing at noon today and all day tomorrow and Friday", "early_dismissal", jan(20),
        confidence=0.95, dismissal=at(12),
        schedule=(("early_dismissal", jan(20)), ("closed", jan(21, 23)))),
    row("Closing at noon Wednesday and Thursday", "early_dismissal", jan(21, 22),
        confidence=0.95, dismissal=at(12), schedule=(("early_dismissal", jan(21, 22)),)),
]  # fmt: skip

# The whole day, or no part of it named: a closure.
WHOLE_DAYS = [
    row("Closed AM and PM", "closed", jan(20), confidence=0.9),
    row("Closed tomorrow AM and PM", "closed", jan(21), confidence=0.95),
    row("Closed Wednesday morning and afternoon", "closed", jan(21), confidence=0.95),
    row("Closed this morning and afternoon", "closed", jan(20), confidence=0.95),
    row("Morning: closed. Afternoon: closed.", "closed", jan(20), confidence=0.9),
    row("Wednesday morning: closed. Wednesday afternoon: closed.", "closed", jan(21),
        confidence=0.95),
    row("Closed tomorrow", "closed", jan(21), confidence=0.95),
    row("Closed tomorrow; afternoon activities cancelled", "closed", jan(21), confidence=0.95,
        notes=("activities_cancelled",)),
    row("Closed tomorrow, PM activities cancelled", "closed", jan(21), confidence=0.95,
        notes=("activities_cancelled",)),
    row("Closed Thursday after school", "closed", jan(22), confidence=0.95),
    row("Closed after the storm", "closed", jan(20), confidence=0.9),
    row("Closed after 3 inches of snow", "closed", jan(20), confidence=0.9),
    row("Closed until further notice", "closed", jan(20), confidence=0.9),
    row("Closed Jan 21 until 23", "closed", jan(21, 22), confidence=0.95),
    row("Closed tomorrow (AM and PM)", "closed", jan(21), confidence=0.95),
    row("Closed tomorrow AM/PM", "closed", jan(21), confidence=0.95),
    # A time or a part before a colon that heads something else.
    row("As of 2 PM: closed tomorrow", "closed", jan(21), confidence=0.95),
    row("PM Update: Closed tomorrow", "closed", jan(21), confidence=0.95),
    row("5 AM: Closed", "closed", jan(20), confidence=0.9),
    row("Closed Wednesday; AM kindergarten closed Thursday", "closed", jan(21), confidence=0.8,
        notes=("partial_program",)),
]  # fmt: skip

# "Closed for the rest of the day" is the posting day's, whenever it was posted.
REST_OF_THE_DAY = [
    early("Closed for the rest of the day", jan(20), confidence=0.95),
    early("Closed for the rest of the day", jan(20), posted=EVENING, confidence=0.95),
    early("Closed for the remainder of the day", jan(20), posted=AFTERNOON, confidence=0.95),
    early("Closing for the rest of the day", jan(20), posted=EVENING, confidence=0.95),
    early("Closed for the rest of the day today", jan(20), confidence=0.95),
    early(
        "Dismissing at noon, closed for the rest of the day",
        jan(20),
        confidence=0.95,
        dismissal=at(12),
    ),
]

# A part-day closure that is hedged, denied or called off is none.
QUALIFIED = [
    row("Possible closure this afternoon", confidence=0.3, notes=("hedged",)),
    row("Closed this afternoon?", confidence=0.3, notes=("hedged",)),
    row("No closure this afternoon", confidence=0.9, notes=("negated",)),
    row("Closure this afternoon cancelled", confidence=0.9, notes=("revoked",)),
    row("Remote learning this afternoon", "remote", jan(20), confidence=0.95),
]


@pytest.mark.parametrize("case", AFTERNOONS)
def test_closed_for_the_afternoon_is_an_early_dismissal(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", FROM_A_TIME)
def test_closed_from_a_time_is_an_early_dismissal_at_that_time(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", MORNINGS)
def test_closed_for_the_morning_alone_states_nothing(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", REOPENINGS)
def test_closed_for_the_morning_with_an_opening_time_is_a_late_start(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", NOT_THE_DAY)
def test_part_of_the_program_or_the_evening_is_no_school_day_status(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", UNCLEAR_HOURS)
def test_hours_that_cannot_be_placed_leave_the_closure_unclear(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", SPLITS)
def test_a_bounded_day_among_others_leaves_them_closed(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", WHOLE_DAYS)
def test_the_whole_day_is_a_closure(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", REST_OF_THE_DAY)
def test_the_rest_of_the_day_is_the_posting_day(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", QUALIFIED)
def test_a_qualified_part_day_closure(case: Row) -> None:
    check(case)


def test_the_table_covers_every_form() -> None:
    tables = (
        AFTERNOONS, FROM_A_TIME, MORNINGS, REOPENINGS, NOT_THE_DAY, UNCLEAR_HOURS, SPLITS,
        WHOLE_DAYS, REST_OF_THE_DAY, QUALIFIED,
    )  # fmt: skip
    assert sum(map(len, tables)) >= 150


# Properties ---------------------------------------------------------------------------------

ZONES = ("America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles")
instants = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2032, 12, 31),
    timezones=st.sampled_from([ZoneInfo(name) for name in ZONES]),
)
CLOSURES = ("Closed", "No school", "Classes cancelled", "School closed", "Schools closed")
DAYS = ("", "today", "tomorrow", "Wednesday", "Friday", "Wed.", "1/21", "Jan. 22")
AFTERNOON_WORDS = ("afternoon", "PM", "p.m.")
AFTERNOON_PHRASES = ("for the afternoon", "in the afternoon", "after lunch", "PM only")
MORNING_WORDS = ("morning", "AM", "a.m.")
CAUSES = ("", "due to snow", "because of icy roads")
TIMES = {"11:30": time(11, 30), "noon": time(12), "12": time(12), "1 pm": time(13)}


def afternoon_texts() -> st.SearchStrategy[str]:
    """A closure bounded to the afternoon, in the forms a listing uses."""
    day_part = st.builds(
        lambda closure, day, word, cause: f"{closure} {day} {word} {cause}",
        st.sampled_from(CLOSURES),
        st.sampled_from(DAYS[1:]),
        st.sampled_from(AFTERNOON_WORDS),
        st.sampled_from(CAUSES),
    )
    phrase = st.builds(
        lambda closure, day, phrase, cause: f"{closure} {day} {phrase} {cause}",
        st.sampled_from(CLOSURES),
        st.sampled_from(DAYS),
        st.sampled_from(AFTERNOON_PHRASES),
        st.sampled_from(CAUSES),
    )
    heading = st.builds(
        lambda day, word, closure: f"{day} {word}: {closure}",
        st.sampled_from(DAYS[1:]),
        st.sampled_from(AFTERNOON_WORDS),
        st.sampled_from(CLOSURES),
    )
    return st.one_of(day_part, phrase, heading)


@settings(max_examples=400, deadline=None)
@given(text=afternoon_texts(), posted=instants, tz=st.sampled_from(ZONES))
def test_an_afternoon_closure_is_never_a_closure(text: str, posted: datetime, tz: str) -> None:
    result = parse_status(text, posted_at=posted, tz=tz)
    assert result.kind in {"early_dismissal", "other"}
    assert all(entry.kind == "early_dismissal" for entry in result.schedule)
    assert result.confidence <= 0.8


@settings(max_examples=300, deadline=None)
@given(
    closure=st.sampled_from(CLOSURES),
    day=st.sampled_from(DAYS),
    word=st.sampled_from(("after", "from", "starting at")),
    clock=st.sampled_from(tuple(TIMES)),
    posted=instants,
    tz=st.sampled_from(ZONES),
)
def test_a_closure_from_a_time_is_an_early_dismissal_at_that_time(  # noqa: PLR0913, PLR0917
    closure: str, day: str, word: str, clock: str, posted: datetime, tz: str
) -> None:
    text = f"{closure} {day} {word} {clock}"
    result = parse_status(text, posted_at=posted, tz=tz)
    assert result.kind in {"early_dismissal", "other"}
    for entry in result.schedule:
        assert entry.kind == "early_dismissal"
        assert entry.dismissal_time == TIMES[clock]


@settings(max_examples=400, deadline=None)
@given(
    closure=st.sampled_from(CLOSURES),
    day=st.sampled_from(DAYS[1:]),
    word=st.sampled_from(MORNING_WORDS),
    cause=st.sampled_from(CAUSES),
    heading=st.booleans(),
    posted=instants,
    tz=st.sampled_from(ZONES),
)
def test_a_morning_closure_alone_is_never_stated(  # noqa: PLR0913, PLR0917
    closure: str, day: str, word: str, cause: str, heading: bool, posted: datetime, tz: str
) -> None:
    # A weekday's "Morning:" heading is a closings page's slot for the whole day (see
    # test_classify_slots.py); every other morning heading says the morning.
    assume(not (heading and word == "morning" and day in {"Wednesday", "Friday", "Wed."}))
    text = f"{day} {word}: {closure} {cause}" if heading else f"{closure} {day} {word} {cause}"
    result = parse_status(text, posted_at=posted, tz=tz)
    assert result.kind == "other"
    assert result.confidence <= 0.3


@settings(max_examples=300, deadline=None)
@given(
    closure=st.sampled_from(CLOSURES),
    day=st.sampled_from(DAYS[1:]),
    word=st.sampled_from(MORNING_WORDS),
    opening=st.sampled_from(("until {}", ", reopening at {}", ". Opening at {}.")),
    clock=st.sampled_from(("10", "10:30", "11 am", "noon")),
    posted=instants,
    tz=st.sampled_from(ZONES),
)
def test_a_morning_closure_with_an_opening_time_is_a_late_start(  # noqa: PLR0913, PLR0917
    closure: str, day: str, word: str, opening: str, clock: str, posted: datetime, tz: str
) -> None:
    text = f"{closure} {day} {word} {opening.format(clock)}".replace(" ,", ",").replace(" .", ".")
    result = parse_status(text, posted_at=posted, tz=tz)
    assert result.kind in {"delayed", "other"}
    expected = {"10": time(10), "10:30": time(10, 30), "11 am": time(11), "noon": time(12)}
    for entry in result.schedule:
        assert entry.kind == "delayed"
        assert entry.opens_at == expected[clock]


@settings(max_examples=200, deadline=None)
@given(
    day=st.sampled_from(("this", "tomorrow", "Wednesday")),
    site=st.sampled_from(
        ("Learning Center", "Main campus", "The annex", "Early Childhood Center", "North building",
         "Central office")
    ),
    verb=st.sampled_from(("to open at", "will open at", "opens at", "is to open at")),
    clock=st.sampled_from(("10", "10:30", "11 am", "noon")),
    mark=st.sampled_from((". ", "; ", ": ", ", ")),
)  # fmt: skip
def test_a_site_s_opening_after_a_morning_closure_is_no_late_start(
    day: str, site: str, verb: str, clock: str, mark: str
) -> None:
    text = f"Closed {day} morning{mark}{site} {verb} {clock}"
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other" or result.confidence < 0.7, text
