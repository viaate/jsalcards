"""What a status is about: facilities, events held remotely, classes online, neither way of
holding school, some of the schools, and an event's new date.

Every text here is a phrasing pattern written for these tests, not a claim
about a real school. Unless a row says otherwise it is posted at 6 a.m. on
Tuesday 20 January 2026 in New York, so "today" is Tuesday the 20th and
"tomorrow" Wednesday the 21st.

* A facility or a service closing is not the school closing: "Cafeteria
  closed", "Parking lot closed", "Stadium closed", "Registration closed" are
  ``other`` at 0.9 with ``activities_cancelled``, as "Gym closed" is. A school
  named after a place ("Stadium Drive Elementary: Closed") is still a school.
* "Virtual" or "remote" before an event, a service or work says how that is
  held: "Virtual open house", "Remote meeting", "Remote work day", "Virtual job
  fair cancelled" are no remote learning day. Work with learning beside it
  ("Remote work and learning Wednesday") is one. "Virtual kindergarten" is part
  of the program.
* "Online" after classes is remote learning: "Classes will be online",
  "Classes moved online", "Closed. All classes will be online." Online alone
  ("Registration online") is nothing.
* Neither way of holding school is a closure: "No in-person or remote
  classes", "No day or evening classes", "No AM or PM classes". One part of
  the day ("No evening classes", "No AM kindergarten") is not.
* Some of the schools ("Some schools closed", "Closed: some schools") and one
  level alone ("Closed kindergarten only") are part of the program: ``other``
  with ``partial_program``.
* An event's new date ("Closed; concert rescheduled to Jan. 30") is no day of
  the school's: the closure is read from the posting time as if the date were
  not there. A side note's own day ("Closed; offices open Monday") still leaves
  the closure's day unclear.
"""

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from snowlight.classify import parse_status

TZ = "America/New_York"
ZONE = ZoneInfo(TZ)
TUE = datetime(2026, 1, 20, 6, 0, tzinfo=ZONE)
TUE_EVENING = datetime(2026, 1, 20, 20, 0, tzinfo=ZONE)


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


def row(  # noqa: PLR0913 - one table row
    text: str,
    kind: str,
    dates: tuple[date, ...] = jan(20),
    *,
    posted: datetime = TUE,
    confidence: float = 0.9,
    notes: tuple[str, ...] = (),
) -> object:
    case = Row(text, posted, kind, dates, confidence, notes)
    return pytest.param(case, id=f"{text} @ {posted:%a %H:%M}")


def activities(text: str) -> object:
    return row(text, "other", (), notes=("activities_cancelled",))


def partial(text: str) -> object:
    return row(text, "other", (), notes=("partial_program",))


def unrecognized(text: str) -> object:
    return row(text, "other", (), confidence=0.1, notes=("unrecognized",))


def check(case: Row) -> None:
    result = parse_status(case.text, posted_at=case.posted, tz=TZ)
    assert result.kind == case.kind
    assert result.dates == case.dates
    assert result.confidence == case.confidence
    assert result.notes == case.notes


# A facility or a service closing.
FACILITIES = [
    activities("Cafeteria closed"),
    activities("Kitchen closed"),
    activities("Playground closed"),
    activities("Parking lot closed"),
    activities("Stadium closed"),
    activities("Registration closed"),
    activities("Enrollment closed"),
    activities("Gymnasium closed"),
    activities("Auditorium closed"),
    activities("Weight room closed"),
    activities("Field house closed"),
    activities("Open house cancelled"),
    activities("Cafeteria closed today"),
    activities("Stadium closed Wednesday"),
    activities("Online registration closed"),
    activities("Gym closed"),
    activities("Fields closed"),
    activities("Tennis courts closed"),
    activities("Dining hall closed"),
    activities("Food pantry closed Thursday"),
    activities("Health center closed"),
    activities("Recreation center closed today"),
    activities("Courthouse closed"),
    row("Early learning center closed", "closed"),
    row("Fields Elementary: Closed", "closed"),
    # Beside the school's own closure: a note on it.
    row("School closed; stadium closed", "closed", notes=("activities_cancelled",)),
    row("Closed, playground closed", "closed", notes=("activities_cancelled",)),
    row(
        "Closed today; registration closed",
        "closed",
        confidence=0.95,
        notes=("activities_cancelled",),
    ),
    # A school named after a place is a school.
    row("Stadium Drive Elementary: Closed", "closed"),
    row("Community Elementary: Closed", "closed"),
    row("Library Road Elementary: Closed", "closed"),
    row("Pool Elementary: Closed", "closed"),
]

# "Virtual" and "remote" before an event, a service or work.
HELD_REMOTELY = [
    unrecognized("Virtual open house"),
    unrecognized("Remote meeting"),
    unrecognized("Remote work day"),
    unrecognized("Remote work only tomorrow"),
    unrecognized("Virtual family math night"),
    unrecognized("Virtual board meeting tonight"),
    unrecognized("Virtual parent-teacher conferences"),
    unrecognized("Virtual tour"),
    unrecognized("Virtual orientation tonight"),
    activities("Virtual job fair cancelled"),
    partial("Virtual kindergarten"),
    # Remote learning itself.
    row("Virtual today", "remote"),
    row("Virtual Wednesday", "remote", jan(21)),
    row("Remote K-12", "remote"),
    row("Remote", "remote"),
    row("Remote day", "remote"),
    row("Remote e-learning day", "remote"),
    row("Virtual for all students", "remote"),
    row("Remote work and learning Wednesday", "remote", jan(21)),
    row("Remote work & learn Wednesday", "remote", jan(21)),
    row("Remote work, classes on Wednesday", "remote", jan(21)),
    row("Remote Valley School: Closed", "closed"),
]

# "Online" after classes.
ONLINE = [
    row("Classes will be online", "remote"),
    row("Classes online", "remote"),
    row("Classes moved online", "remote"),
    row("Classes to be held online", "remote"),
    row("Classes online Wednesday and Thursday", "remote", jan(21, 22), confidence=0.95),
    row("Students will learn online Wednesday", "remote", jan(21), confidence=0.95),
    row("Closed. All classes will be online.", "remote"),
    row("Campus closed; classes online", "remote"),
    row("Online classes", "remote"),
    row("Classes will be online", "remote", jan(21), posted=TUE_EVENING),
    unrecognized("Registration online"),
    unrecognized("Check online for updates"),
    unrecognized("Updates posted online"),
]

# Neither way of holding school, and the whole school day.
NEITHER_WAY = [
    row("No in-person or remote classes today", "closed", confidence=0.95),
    row("No In-Person or Remote 1/21/26", "closed", jan(21), confidence=0.95),
    row(
        "There will be no in-person or virtual learning tomorrow",
        "closed",
        jan(21),
        confidence=0.95,
    ),
    row("No remote or in-person instruction", "closed"),
    row("Closed; closed no in person or remote learning", "closed"),
    row("No day or evening classes", "closed"),
    row("No day classes", "closed"),
    row("No Day Classes Wednesday", "closed", jan(21), confidence=0.95),
    row("No AM or PM classes", "closed"),
    # A list after "no" that ends with the school covers it too.
    row("No activities or classes", "closed"),
    row("No activities or school today", "closed", confidence=0.95),
    row("No practice, games or classes", "closed"),
    # (A list that runs on past a few nouns is unclear.)
    row(
        "No practice, games, concerts, dances, clubs, events, trips or classes",
        "other",
        (),
        confidence=0.3,
        notes=("ambiguous",),
    ),
    activities("No practice, games"),
    row("No buses or school", "closed"),
    activities("No activities or school events"),
    activities("No evening activities or classes"),
    row("No activities or school closures", "other", (), notes=("negated",)),
    row("No morning or afternoon classes", "closed"),
    # One way, or one part of the day: not the school day.
    row("No in-person classes", "other", (), confidence=0.3, notes=("ambiguous",)),
    partial("No AM or PM kindergarten"),
    partial("No AM kindergarten"),
    partial("No afternoon or evening classes"),
    row("No day care", "other", (), notes=("childcare",)),
    row("No day care today", "other", (), notes=("childcare",)),
    activities("No evening or night classes"),
    activities("No evening classes"),
]

# Some of the schools, and one level alone.
SOME_SCHOOLS = [
    partial("Some schools closed"),
    partial("Some schools will be closed tomorrow"),
    partial("Select schools closed"),
    partial("Several schools closed"),
    partial("Certain schools closed"),
    partial("Most schools closed"),
    partial("Closed: some schools"),
    partial("Closed for some schools"),
    partial("Some schools on 2 hour delay"),
    partial("Closed kindergarten only"),
    partial("Closed - kindergarten only"),
    partial("2 hour delay kindergarten only"),
    partial("Remote learning elementary only"),
    partial("Closed tomorrow kindergarten only"),
    row("All schools closed", "closed"),
    row("Schools closed", "closed"),
    row("Closed students only", "closed"),
    row("Closed today only", "closed", confidence=0.95),
    row("Closed for all schools", "closed"),
    partial("Several schools will be on a 2 hour delay tomorrow"),
]

# An event's new date.
MOVED_EVENTS = [
    row("Closed; concert rescheduled to Jan. 30", "closed", notes=("activities_cancelled",)),
    row(
        "Closed, open house rescheduled to Feb. 13 at 5:30 p.m.",
        "closed",
        notes=("activities_cancelled",),
    ),
    row("Closed. Game postponed until Friday", "closed", notes=("activities_cancelled",)),
    row("Closed, program postponed to 2/27", "closed", notes=("activities_cancelled",)),
    row(
        "Closed; concert rescheduled to Jan. 30",
        "closed",
        jan(21),
        posted=TUE_EVENING,
        notes=("activities_cancelled",),
    ),
    # A side note's own day: the closure could be for that day as well.
    row("Closed; offices open Monday", "other", (), confidence=0.3, notes=("undated",)),
    row(
        "Closed; concert cancelled Monday",
        "other",
        (),
        confidence=0.3,
        notes=("activities_cancelled", "undated"),
    ),
]


@pytest.mark.parametrize("case", FACILITIES)
def test_a_facility_closing_is_not_the_school_closing(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", HELD_REMOTELY)
def test_an_event_held_remotely_is_no_remote_learning_day(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", ONLINE)
def test_classes_online_are_remote_learning(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", NEITHER_WAY)
def test_neither_way_of_holding_school_is_a_closure(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", SOME_SCHOOLS)
def test_some_of_the_schools_are_part_of_the_program(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", MOVED_EVENTS)
def test_an_event_s_new_date_is_no_day_of_the_school_s(case: Row) -> None:
    check(case)


def test_the_tables_cover_every_form() -> None:
    tables = (FACILITIES, HELD_REMOTELY, ONLINE, NEITHER_WAY, SOME_SCHOOLS, MOVED_EVENTS)
    assert sum(map(len, tables)) >= 100


# Properties ---------------------------------------------------------------------------------

instants = st.datetimes(min_value=datetime(2020, 1, 1), max_value=datetime(2032, 12, 31)).map(
    lambda moment: moment.replace(tzinfo=ZONE)
)
FACILITY_NOUNS = (
    "Cafeteria", "Kitchen", "Playground", "Parking lot", "Stadium", "Registration",
    "Enrollment", "Gymnasium", "Auditorium", "Weight room", "Field house", "Gym", "Pool",
    "Library", "Open house", "Fields", "Dining hall", "Food pantry", "Health center",
    "Museum", "Bookstore", "Concession stand",
)  # fmt: skip
CLOSING_WORDS = ("closed", "closed today", "closed tomorrow", "cancelled", "is closed")
EVENTS = (
    "open house", "meeting", "board meeting", "job fair", "family night", "work day",
    "parent-teacher conferences", "concert", "tour",
)  # fmt: skip


@settings(max_examples=300, deadline=None)
@given(noun=st.sampled_from(FACILITY_NOUNS), words=st.sampled_from(CLOSING_WORDS), posted=instants)
def test_a_facility_closing_never_closes_the_school(
    noun: str, words: str, posted: datetime
) -> None:
    alone = parse_status(f"{noun} {words}", posted_at=posted, tz=TZ)
    assert alone.kind == "other"
    assert all(entry.kind != "closed" for entry in alone.schedule)
    # Beside the school's closure, a facility's own closing leaves it as it is. (A day the
    # facility's closing names can leave the school's day unclear: see MOVED_EVENTS.)
    undated = words.removesuffix(" today").removesuffix(" tomorrow")
    beside = parse_status(f"School closed; {noun.lower()} {undated}", posted_at=posted, tz=TZ)
    school = parse_status("School closed", posted_at=posted, tz=TZ)
    assert beside.kind == school.kind
    assert beside.dates == school.dates


@settings(max_examples=300, deadline=None)
@given(
    word=st.sampled_from(("Virtual", "Remote", "virtual", "REMOTE")),
    event=st.sampled_from(EVENTS),
    after=st.sampled_from(("", " cancelled", " tonight", " postponed")),
    posted=instants,
)
def test_an_event_held_remotely_never_makes_a_remote_day(
    word: str, event: str, after: str, posted: datetime
) -> None:
    result = parse_status(f"{word} {event}{after}", posted_at=posted, tz=TZ)
    assert result.kind == "other"
    assert result.schedule == ()


@settings(max_examples=300, deadline=None)
@given(
    first=st.sampled_from(("in-person", "In-Person", "in person", "face-to-face")),
    second=st.sampled_from(("remote", "virtual", "online")),
    joiner=st.sampled_from(("or", "and", "nor")),
    noun=st.sampled_from(("", " classes", " learning", " instruction", " school")),
    reverse=st.booleans(),
    posted=instants,
)
def test_neither_way_of_holding_school_always_closes_it(  # noqa: PLR0913, PLR0917
    first: str, second: str, joiner: str, noun: str, reverse: bool, posted: datetime
) -> None:
    ways = f"{second} {joiner} {first}" if reverse else f"{first} {joiner} {second}"
    result = parse_status(f"No {ways}{noun} today", posted_at=posted, tz=TZ)
    closed_today = parse_status("Closed today", posted_at=posted, tz=TZ)
    assert result.kind == "closed"
    assert result.dates == closed_today.dates
