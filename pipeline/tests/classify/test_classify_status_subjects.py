"""Whose status a status word states: the school's day, or something else that is late or off.

Every text here is a phrasing pattern written for these tests, not a claim
about a real school. Unless a row says otherwise it is posted at 6 a.m. on
Tuesday 13 January 2026 in New York, so "today" is Tuesday the 13th and
"tomorrow" Wednesday the 14th.

* A delay of the end of the day holds students past the bell; it is no late
  start, so it is never ``delayed``: "Delayed dismissal due to severe
  weather", "Dismissal delayed", "Afternoon dismissal delayed 30 minutes",
  "Delay in dismissal", "Dismissal will be 30 minutes late" are ``other`` at
  0.3 with ``ambiguous``.
* A status word whose subject is a noun other than the school, its classes,
  its opening, start or arrival is about that noun: "Payroll delayed",
  "Graduation delayed", "Report cards delayed", "Lightning delay", "Weather
  delay at the stadium", "School pictures cancelled" (where "school" only says
  which pictures), "School store closed", "Prom cancelled", "School Pictures:
  Cancelled" are ``other`` at 0.3 with ``ambiguous``, as "Field day cancelled"
  is. A name the parser does
  not know reads as such a noun ("Lincoln delayed"); a school's name with its
  level does not ("Lincoln Elementary delayed").
* A verb whose object is the status leaves its subject the subject: "District
  announces 2 hour delay" and "Schools will begin on a 2 hour delay" are the
  school's. Who announces, observes, implements or runs on a status by a name
  the parser does not know is the school: "BPS will be observing an early
  release schedule", "FPS is operating on a 2 hour delay". Something else
  delayed stays so whatever verb comes before it ("District announces payroll
  delayed", "Graduation will follow a delayed schedule").
* The first day or the start of a year or a term is no day's status ("First
  day of school delayed", "Start of the school year delayed").
* A noun the scope rules know keeps its own note ("Staff delayed 2 hours",
  "Delayed bus routes", "School board meeting cancelled", "Grades delayed").
  The noun right before "cancelled" is what it calls off, whatever noun
  follows it with nothing between them: "Classes cancelled today buses
  running" is a closure, while "Cancelled buses" is the buses' news.
* Classes held in person called off may be held another way: "In-person
  classes cancelled" is ``other`` at 0.3, as "No in-person classes" is, and
  beside a remote day it is that remote day.
* Beside the school's own status, such a side note leaves the status
  standing, at 0.8 with ``ambiguous``: "2 hour delay. Field day cancelled",
  "Closed today. Payroll delayed.", "Dismissal delayed; 2 hour delay
  tomorrow".
* A year, a span of years or terms, or a closure for good is no day's status:
  "Closed in 2019", "Closed since 2020", "closed last year", "Closed for the
  summer", "Closed permanently", "Closed for renovation".
* What a dismissal verb names before "early", a length or a time is whose
  day ends early: "The district is closing schools early at 1 pm", "Closing all
  schools 2 hours early" and "Dismissing students early" are early dismissals,
  never closures; "Closing all offices early at noon" and "Closing all district
  offices" are the offices' news, as "Closing offices" is (``other`` at 0.3).
* The school day said to end at an early time is an early dismissal at 0.8
  ("Classes end at noon today", "School ends at 1:00 today"), at 0.9 with
  "early"; a time when the day can end anyway says nothing ("School ends at
  3:15"), and nor does the end of part of the program or of something else
  ("Morning classes end at 11 am", "Summer school ends at noon", "Storm should
  end at 10 am").
* An open day as past as the statuses is history too: "Open Friday 1/9;
  closed Monday 1/12" seen on the 13th is the closure on the 12th, as stated.
* Every status past and the posting day open is the news that school is open:
  "Yesterday's closure: snow. Today: open" is ``other`` at 0.9, ``says_open``,
  noted ``superseded``. A delay until later today is today's ("Delayed until
  this afternoon at 1").
"""

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from snowlight.classify import parse_status
from snowlight.classify import subjects as subjects_module

TZ = "America/New_York"
ZONE = ZoneInfo(TZ)
TUE = datetime(2026, 1, 13, 6, 0, tzinfo=ZONE)
TUE_EVENING = datetime(2026, 1, 13, 20, 0, tzinfo=ZONE)
TODAY = (date(2026, 1, 13),)
TOMORROW = (date(2026, 1, 14),)


@dataclass(frozen=True)
class Row:
    text: str
    posted: datetime
    kind: str
    dates: tuple[date, ...]
    confidence: float
    notes: tuple[str, ...]
    delay: int | None


def row(  # noqa: PLR0913 - one table row
    text: str,
    kind: str = "other",
    dates: tuple[date, ...] = (),
    *,
    posted: datetime = TUE,
    confidence: float = 0.9,
    notes: tuple[str, ...] = (),
    delay: int | None = None,
) -> object:
    case = Row(text, posted, kind, dates, confidence, notes, delay)
    return pytest.param(case, id=f"{text} @ {posted:%a %H:%M}")


def unclear(text: str) -> object:
    """Not the school's status: ``other`` at 0.3, noted ``ambiguous``."""
    return row(text, confidence=0.3, notes=("ambiguous",))


def check(case: Row) -> None:
    result = parse_status(case.text, posted_at=case.posted, tz=TZ)
    assert result.kind == case.kind
    assert result.dates == case.dates
    assert result.confidence == case.confidence
    assert result.notes == case.notes
    assert result.delay_minutes == case.delay
    if case.kind == "other":
        assert result.schedule == ()


# A delay of the end of the day: students held past the bell, never a late start.
HELD_DISMISSALS = [
    unclear("Delayed dismissal"),
    unclear("Delayed dismissal due to severe weather"),
    unclear("Dismissal delayed"),
    unclear("Afternoon dismissal delayed 30 minutes"),
    unclear("Dismissal will be delayed 30 minutes due to storms"),
    unclear("Dismissal delayed due to storm"),
    unclear("Dismissal is delayed until the storm passes"),
    unclear("Delayed release"),
    unclear("Release delayed due to lightning"),
    unclear("Delay in dismissal"),
    unclear("Dismissal delay"),
    unclear("School dismissal delayed"),
    unclear("Dismissal times delayed"),
    unclear("Afternoon pickup delayed"),
    unclear("Delayed afternoon dismissal"),
    unclear("Delayed school dismissal"),
    unclear("2 hour delayed dismissal"),
    unclear("30 minute delayed dismissal due to storms"),
    unclear("30 minute delay for dismissal"),
    unclear("Delay in afternoon dismissal"),
    unclear("Delayed dismissal for all students"),
    unclear("Dismissal will be 30 minutes late"),
    unclear("Students will be dismissed 30 minutes late"),
    unclear("Dismissing 30 minutes late"),
    unclear("Delayed release today"),
    unclear("DELAYED DISMISSAL"),
    unclear("30 minute delay afternoon dismissal"),
    # A delay after the morning is no late start.
    unclear("Delayed this afternoon"),
    unclear("2 hour delay this afternoon"),
    unclear("Delayed this evening"),
]

# The delays of games and meets, and of places that are not the school.
GAME_DELAYS = [
    unclear("Lightning delay"),
    unclear("Weather delay at the stadium"),
    unclear("Rain delay"),
    unclear("Thunderstorm delay"),
    unclear("Delay during the game"),
    row("Football game delayed", notes=("activities_cancelled",)),
    row("Game delayed due to lightning", notes=("activities_cancelled",)),
]

# Something else is late: its delay is no late start.
OTHER_DELAYS = [
    # Something else delayed, whatever verb comes before it.
    unclear("District announces payroll delayed"),
    unclear("Graduation will follow a delayed schedule"),
    unclear("Graduation will be on a 2 hour delay"),
    unclear("UPS delayed"),
    unclear("Payroll delayed"),
    unclear("Paychecks delayed"),
    unclear("Deliveries delayed"),
    unclear("Meals delayed"),
    unclear("Snowplows delayed"),
    unclear("Snowplows delayed due to ice"),
    unclear("Repairs delayed"),
    unclear("Graduation delayed"),
    unclear("Bond vote delayed"),
    unclear("Board vote delayed"),
    unclear("Kickoff delayed"),
    unclear("Results delayed"),
    unclear("Newsletter delayed"),
    unclear("Picture day delayed"),
    unclear("Picture retakes delayed"),
    unclear("Report cards delayed"),
    unclear("Construction delayed"),
    unclear("Mail delayed"),
    unclear("Yearbook delayed"),
    unclear("Yearbooks delayed due to weather"),
    unclear("Testing delayed"),
    unclear("Snow removal delayed"),
    unclear("Trash pickup delayed"),
    unclear("REFUSE Pickup Delay"),
    unclear("Payroll delayed 2 hours"),
    unclear("Graduation delayed 2 hours"),
    unclear("Payroll will be delayed"),
    unclear("Report cards have been delayed until Friday"),
    unclear("Delayed payroll"),
    unclear("Delayed results"),
    unclear("Delayed graduation"),
    unclear("Lincoln delayed 2 hours"),
    unclear("Payroll/benefits delayed"),
    # The start of a year or a term, or of a new building: no day's late start.
    unclear("Opening of new school delayed"),
    unclear("Start of school year delayed"),
    unclear("Start of the second semester delayed"),
    unclear("First day of school delayed"),
    unclear("First day of school delayed to Sept 8"),
    unclear("Opening day delayed"),
]

# Something else is called off or closed: "school" before it only says which.
OTHER_CANCELLATIONS = [
    unclear("School pictures cancelled"),
    unclear("School photos cancelled"),
    unclear("School play cancelled"),
    unclear("School picture day cancelled"),
    unclear("School spirit week cancelled"),
    unclear("School walkout cancelled"),
    unclear("School nurse visits cancelled"),
    unclear("School musical cancelled"),
    unclear("School pictures have been cancelled"),
    unclear("School pictures postponed"),
    # A label names what is called off: its last word says what it is.
    unclear("School Pictures: Cancelled"),
    unclear("School play: cancelled"),
    unclear("Picture day: cancelled"),
    unclear("Picture day cancelled"),
    unclear("Field day cancelled"),
    unclear("Prom cancelled"),
    unclear("Musical cancelled"),
    unclear("Graduation cancelled"),
    unclear("Math class cancelled"),
    unclear("Wednesday Afternoon: Prenatal Class cancelled"),
    unclear("School store closed"),
    unclear("Track closed"),
    unclear("Polls closed"),
    unclear("Applications closed"),
    unclear("Polls closing early"),
    unclear("Lincoln dismissing early"),
]

# The school, its classes, its opening, start or arrival: the status stands.
SCHOOL_SUBJECTS = [
    # A verb whose object is the status: its subject is the subject.
    row("District announces 2 hour delay", "delayed", TODAY, delay=120),
    row("The district announced a 2 hour delay", "delayed", TODAY, delay=120),
    row("Superintendent has called a 2 hour delay", "delayed", TODAY, delay=120),
    row("All schools will observe a 2 hour delay", "delayed", TODAY, delay=120),
    row("Schools will follow a 2 hour delay schedule", "delayed", TODAY, delay=120),
    row("The district is implementing a 2 hour delay", "delayed", TODAY, delay=120),
    row("Schools will begin on a 2 hour delay", "delayed", TODAY, delay=120),
    row("District declares an early release", "early_dismissal", TODAY),
    row("We will be observing an early release schedule", "early_dismissal", TODAY),
    # A name the parser does not know, as the subject of such a verb.
    row("BPS will be observing an early release schedule", "early_dismissal", TODAY),
    row("FPS is operating on a 2 hour delay", "delayed", TODAY, delay=120),
    row("RSD will observe a 2 hour delay", "delayed", TODAY, delay=120),
    row("Delayed", "delayed", TODAY),
    row("2 hour delay", "delayed", TODAY, delay=120),
    row("Lincoln Elementary delayed", "delayed", TODAY),
    row("Lincoln Elementary will be delayed 2 hours", "delayed", TODAY, delay=120),
    row("Lincoln Elementary will be on a 2 hour delay", "delayed", TODAY, delay=120),
    row("Lincoln Elementary is closed", "closed", TODAY),
    row("Lincoln Elementary will be closed tomorrow", "closed", TOMORROW, confidence=0.95),
    row("Maple Grove Middle School will be closed", "closed", TODAY),
    row("South Campus High School closed", "closed", TODAY),
    row("North Campus High School: 2 hour delay", "delayed", TODAY, delay=120),
    row("Schools delayed 2 hours", "delayed", TODAY, delay=120),
    row("School delayed", "delayed", TODAY),
    row("All schools delayed", "delayed", TODAY),
    row("Classes delayed until 10", "delayed", TODAY),
    row("School start delayed 2 hours", "delayed", TODAY, delay=120),
    row("Start delayed 2 hours", "delayed", TODAY, delay=120),
    row("Opening delayed 2 hours", "delayed", TODAY, delay=120),
    row("School opening delayed", "delayed", TODAY),
    row("Arrival delayed", "delayed", TODAY),
    row("Morning arrival delayed due to fog", "delayed", TODAY),
    row("Students delayed 2 hours", "delayed", TODAY, delay=120),
    row("Fog delay", "delayed", TODAY),
    row("Snow delay", "delayed", TODAY),
    row("Weather delay", "delayed", TODAY),
    row("Weather-related delay", "delayed", TODAY),
    row("Ice delay tomorrow", "delayed", TOMORROW),
    row("School will be delayed 2 hours", "delayed", TODAY, delay=120),
    row("We are delayed 2 hours", "delayed", TODAY, delay=120),
    row("Tomorrow: delayed 2 hours", "delayed", TOMORROW, confidence=0.95, delay=120),
    row("Delayed opening", "delayed", TODAY),
    row("Delayed start", "delayed", TODAY),
    row("Delayed opening for all schools", "delayed", TODAY),
    row("District delayed 2 hours", "delayed", TODAY, delay=120),
    row("Washington County Schools delayed 2 hours", "delayed", TODAY, delay=120),
    row("Lincoln Academy delayed 2 hours", "delayed", TODAY, delay=120),
    row("Kelly Elem delayed 2 hours", "delayed", TODAY, delay=120),
    row("Smith HS delayed 2 hours", "delayed", TODAY, delay=120),
    row("The district is on a 2 hour delay", "delayed", TODAY, delay=120),
    row("All schools will operate on a two-hour delay", "delayed", TODAY, delay=120),
    row("Precautionary 2 hour delay", "delayed", TODAY, delay=120),
    row("District-wide 2 hour delay", "delayed", TODAY, delay=120),
    row("Because of snow schools are delayed 2 hours", "delayed", TODAY, delay=120),
    row("2 hour delay, dismissal at regular time", "delayed", TODAY, delay=120),
    row("School cancelled", "closed", TODAY),
    row("Classes cancelled", "closed", TODAY),
    row("All classes cancelled", "closed", TODAY),
    row("Class cancelled", "closed", TODAY),
    row("Classes for today cancelled", "closed", TODAY, confidence=0.95),
    row("Today's classes cancelled", "closed", TODAY, confidence=0.95),
    row("School for tomorrow cancelled", "closed", TOMORROW, confidence=0.95),
    row("School closed", "closed", TODAY),
    row("Campus closed", "closed", TODAY),
    row("District closed", "closed", TODAY),
    row("University closed", "closed", TODAY),
    row("School day delayed 2 hours", "delayed", TODAY, delay=120),
    row("Students/staff delayed 2 hours", "delayed", TODAY, delay=120),
    row("2 hour delay for all", "delayed", TODAY, delay=120),
    row("Delayed -", "delayed", TODAY),
    row("Delayed this morning", "delayed", TODAY),
    row("Hillsboro R-3 closed", "closed", TODAY),
    row("Bayless C-4 delayed 2 hours", "delayed", TODAY, delay=120),
    row("PS 21 closed", "closed", TODAY),
    row("Superintendent has cancelled school", "closed", TODAY),
    row("Superintendent cancels classes", "closed", TODAY),
    row("Schools dismissing 2 hours early", "early_dismissal", TODAY),
    row("Lincoln Elementary dismissing early", "early_dismissal", TODAY),
]

# A noun the scope rules know: its own note.
KNOWN_NOUNS = [
    row("Grades delayed", notes=("partial_program",)),
    row("Lunch delayed", notes=("partial_program",)),
    row("Staff delayed 2 hours", notes=("staff",)),
    row("Delayed bus routes", notes=("transportation",)),
    row("Bus routes delayed", notes=("transportation",)),
    row("School bus delayed", notes=("transportation",)),
    row("School board meeting cancelled", notes=("activities_cancelled",)),
    row("School dance cancelled", notes=("activities_cancelled",)),
    row("Book fair cancelled", notes=("activities_cancelled",)),
    row("Sports day cancelled", notes=("activities_cancelled",)),
    row("Parent-teacher conferences delayed", notes=("activities_cancelled",)),
    row("Adult services closed today", notes=("activities_cancelled",)),
    row("Offices-Courthouse Closed Today", notes=("activities_cancelled",)),
    row("Main office closed", notes=("offices_closed",)),
    row("Field trip: cancelled", notes=("activities_cancelled",)),
    row("Classes: cancelled", "closed", TODAY),
    row("Lincoln Elementary: Cancelled", "closed", TODAY),
    row("No School-Staff Report at 10", "closed", TODAY, notes=("staff",)),
    # A noun right before "cancelled" is what it calls off; one right after it with nothing
    # between them starts another phrase, unless it is the school or part of it.
    row("Classes cancelled today buses running", "closed", TODAY, confidence=0.95),
    row("School cancelled today staff report", "closed", TODAY, confidence=0.95),
    row("Classes cancelled today offices open", "closed", TODAY, confidence=0.95),
    row("Practices cancelled today buses running", notes=("activities_cancelled",)),
    row("Cancelled buses", notes=("transportation",)),
    row("Classes cancelled AM kindergarten", notes=("partial_program",)),
]

# Classes held in person called off: perhaps held another way.
IN_PERSON = [
    unclear("In-person classes cancelled"),
    unclear("In person learning cancelled"),
    unclear("Face to face classes cancelled"),
    row(
        "In person canceled - Opening at 11:00 AM",
        confidence=0.25,
        notes=("ambiguous", "conflict"),
    ),
    row(
        "In-person classes cancelled; remote learning day",
        "remote",
        TODAY,
        confidence=0.8,
        notes=("ambiguous",),
    ),
]

# Beside the school's own status, a side note leaves it standing.
BESIDE = [
    row("2 hour delay. Field day cancelled", "delayed", TODAY, confidence=0.8,
        notes=("ambiguous",), delay=120),
    row("Field day cancelled. 2 hour delay", "delayed", TODAY, confidence=0.8,
        notes=("ambiguous",), delay=120),
    row("Payroll delayed. Closed today.", "closed", TODAY, confidence=0.8,
        notes=("ambiguous",)),
    row("Closed today. Payroll delayed.", "closed", TODAY, confidence=0.8,
        notes=("ambiguous",)),
    row("2 hour delay; report cards delayed", "delayed", TODAY, confidence=0.8,
        notes=("ambiguous",), delay=120),
    row("School is closed; graduation postponed", "closed", TODAY, confidence=0.8,
        notes=("ambiguous",)),
    row("Schools closed. School pictures cancelled.", "closed", TODAY, confidence=0.8,
        notes=("ambiguous",)),
    row("Dismissal delayed; 2 hour delay tomorrow", "delayed", TOMORROW, confidence=0.8,
        notes=("ambiguous",), delay=120),
    row("Dismissal delayed today. 2 hour delay tomorrow.", "delayed", TOMORROW,
        posted=TUE_EVENING, confidence=0.8, notes=("ambiguous",), delay=120),
    row("Delayed dismissal today, 2 hour delay tomorrow", "delayed", TOMORROW,
        confidence=0.8, notes=("ambiguous",), delay=120),
    # A status called off keeps its subject: the delay, not a noun before the word.
    row("2 hour delay for Lincoln Elementary cancelled", notes=("revoked",)),
    row("Delay at Lincoln Elementary has been lifted", notes=("revoked",)),
]  # fmt: skip

# A year, a span of years or terms, or a closure for good: no day's status.
NO_DAY = [
    row("School closed in 2019", confidence=0.3, notes=("unreadable_date",)),
    row("Closed in 2019", confidence=0.3, notes=("unreadable_date",)),
    row("Closed since 2020", confidence=0.3, notes=("unreadable_date",)),
    row(
        "Lincoln Elementary closed last year and merged with Washington",
        confidence=0.3,
        notes=("unreadable_date",),
    ),
    row("Closed next year", confidence=0.3, notes=("unreadable_date",)),
    row("Closed for the summer", confidence=0.3, notes=("unreadable_date",)),
    row("Closed for the year", confidence=0.3, notes=("unreadable_date",)),
    row("Closed for the rest of the school year", confidence=0.3, notes=("unreadable_date",)),
    row(
        "Closed for renovations through 2027",
        confidence=0.3,
        notes=("ambiguous", "unreadable_date"),
    ),
    unclear("Permanently closed"),
    unclear("Closed permanently"),
    unclear("Closed for good"),
    unclear("Closed for renovation"),
    # A year inside a date is read with it; so is one in an update stamp.
    row("Closed Jan 13, 2026", "closed", TODAY, confidence=0.95),
    row("Closed 1/13/2026", "closed", TODAY, confidence=0.95),
    row("2 Hour Delay on Tuesday, January 13, 2026", "delayed", TODAY, confidence=0.95,
        delay=120),
    row("Closed today. Updated 1/13/2026 5:43 AM", "closed", TODAY, confidence=0.95),
    row("Closed for the rest of the day", "early_dismissal", TODAY, confidence=0.95),
]  # fmt: skip


# Every status past, and the posting day open: the past is history, the news is "open".
OPEN_AFTER_PAST = [
    ("Yesterday's closure: snow. Today: open", TUE, ("superseded",)),
    ("Closed yesterday. Open today.", TUE, ("superseded",)),
    ("School was closed yesterday. Open today", TUE, ("superseded",)),
    ("Closed Jan 12. Open Jan 13.", TUE, ("superseded",)),
    ("Monday: Closed | Tuesday: Open on time", TUE, ("superseded",)),
]
# A past status alone, or beside one for today, is still read as it is.
PAST_KEPT = [
    # A school open on a day as past as the closure: both are history, read as stated.
    (
        "Schools will be open on Friday, January 9. Closed Monday, January 12",
        "closed",
        (date(2026, 1, 12),),
    ),
    ("Open Friday 1/9; closed Monday 1/12", "closed", (date(2026, 1, 12),)),
    ("School was closed yesterday", "closed", (date(2026, 1, 12),)),
    ("Closed yesterday and today", "closed", (date(2026, 1, 12), date(2026, 1, 13))),
    ("Yesterday: closed. Today: 2 hour delay", "delayed", TODAY),
    ("Closed today. Open tomorrow.", "closed", TODAY),
]


# What a dismissal verb names, and the school day's end: (text, kind, dismissal time,
# confidence, notes). An early dismissal is for the posting day.
DAY_ENDS = [
    ("The district is closing schools early at 1 pm", "early_dismissal", time(13, 0), 0.9, ()),
    ("Closing school early at 1 pm", "early_dismissal", time(13, 0), 0.9, ()),
    ("We are closing all schools early at noon", "early_dismissal", time(12, 0), 0.9, ()),
    ("Closing all of our schools early at 11:30", "early_dismissal", time(11, 30), 0.9, ()),
    ("Closing the school at 1 pm", "early_dismissal", time(13, 0), 0.9, ()),
    ("Closing all buildings early at noon", "early_dismissal", time(12, 0), 0.9, ()),
    ("Closing all schools 2 hours early", "early_dismissal", None, 0.9, ()),
    ("Closing school 2 hours early", "early_dismissal", None, 0.9, ()),
    ("Dismissing students early", "early_dismissal", None, 0.9, ()),
    ("Releasing students early today", "early_dismissal", None, 0.95, ()),
    ("Dismissing all students early at 11:30 due to ice", "early_dismissal", time(11, 30), 0.9,
     ()),
    ("Classes end at noon today", "early_dismissal", time(12, 0), 0.8, ()),
    ("School ends at 1:00 today", "early_dismissal", time(13, 0), 0.8, ()),
    ("The school day will end at 12:30", "early_dismissal", time(12, 30), 0.8, ()),
    ("Classes will end early at 1 pm", "early_dismissal", time(13, 0), 0.9, ()),
    ("Lincoln Elementary classes end at noon", "early_dismissal", time(12, 0), 0.8, ()),
    # Not the school's day ending early.
    ("Closing all offices early at noon", "other", None, 0.3, ("ambiguous",)),
    ("Closing all district offices at noon", "other", None, 0.3, ("ambiguous",)),
    ("Closing all offices", "other", None, 0.3, ("ambiguous",)),
    ("Closing all buses", "other", None, 0.3, ("ambiguous",)),
    ("School ends at 3:15", "other", None, 0.3, ("ambiguous",)),
    ("Morning classes end at 11 am", "other", None, 0.1, ("unrecognized",)),
    ("Afternoon classes end at 1 pm", "other", None, 0.1, ("unrecognized",)),
    ("Summer school ends at noon", "other", None, 0.1, ("unrecognized",)),
    ("Evening classes end at 9 pm", "other", None, 0.1, ("unrecognized",)),
    ("Storm should end at 10 am", "other", None, 0.1, ("unrecognized",)),
    ("Classes end at noon on Fridays", "other", None, 0.9, ("recurring",)),
    # The school's closure stays one.
    ("Closing all schools", "closed", None, 0.9, ()),
    ("Closing all day", "closed", None, 0.9, ()),
    ("Closing all district schools", "closed", None, 0.9, ()),
]  # fmt: skip


# A delay until a later part of the posting day is that day's late start, not a closure of
# the days before it (which, seen that morning, would be the day before).
UNTIL_LATER_TODAY = [
    ("Delayed until this afternoon", None),
    ("Delayed until this afternoon at 1", time(13, 0)),
    ("Opening delayed until noon today", time(12, 0)),
]


@pytest.mark.parametrize(("text", "opens"), UNTIL_LATER_TODAY)
def test_a_delay_until_later_today_is_todays(text: str, opens: time | None) -> None:
    result = parse_status(text, posted_at=TUE, tz=TZ)
    assert result.kind == "delayed"
    assert result.dates == TODAY
    assert result.opens_at == opens


@pytest.mark.parametrize(("text", "kind", "dismissal", "confidence", "notes"), DAY_ENDS)
def test_what_a_dismissal_verb_names_and_the_school_days_end(
    text: str, kind: str, dismissal: time | None, confidence: float, notes: tuple[str, ...]
) -> None:
    result = parse_status(text, posted_at=TUE, tz=TZ)
    assert result.kind == kind
    assert result.dates == (() if kind == "other" else TODAY)
    assert result.dismissal_time == dismissal
    assert result.confidence == confidence
    assert result.notes == notes


DISMISS_VERBS = ["Closing", "Dismissing", "Releasing", "We are closing", "The district is closing"]
SCHOOL_OBJECTS = [
    "schools", "all schools", "school", "the school", "our schools", "all of our schools",
    "students", "all students", "classes", "buildings", "all campuses",
]  # fmt: skip
OTHER_OBJECTS = ["offices", "all offices", "district offices", "all district offices"]
EARLY_TIMES = {"11:00": time(11, 0), "11:30 am": time(11, 30), "noon": time(12, 0),
               "1 pm": time(13, 0), "12:45 PM": time(12, 45)}  # fmt: skip


@settings(max_examples=150, deadline=None)
@given(
    verb=st.sampled_from(DISMISS_VERBS),
    noun=st.sampled_from(SCHOOL_OBJECTS + OTHER_OBJECTS),
    early=st.booleans(),
    clock=st.sampled_from(sorted(EARLY_TIMES)),
)
def test_what_a_dismissal_verb_names_ends_its_day_early(
    verb: str, noun: str, early: bool, clock: str
) -> None:
    text = f"{verb} {noun} {'early ' if early else ''}at {clock}"
    result = parse_status(text, posted_at=TUE, tz=TZ)
    if noun in OTHER_OBJECTS:
        # The offices' news: never the school's closure or early dismissal.
        assert result.kind == "other"
        assert result.schedule == ()
        return
    if not verb.endswith("closing") and noun not in {"students", "all students", "classes"}:
        return  # ("Dismissing schools at noon" is no way a listing puts it)
    assert result.kind == "early_dismissal"
    assert result.dates == TODAY
    assert result.dismissal_time == EARLY_TIMES[clock]


@pytest.mark.parametrize(("text", "posted", "notes"), OPEN_AFTER_PAST)
def test_an_open_day_after_past_statuses_is_the_news(
    text: str, posted: datetime, notes: tuple[str, ...]
) -> None:
    result = parse_status(text, posted_at=posted, tz=TZ)
    assert result.kind == "other"
    assert result.schedule == ()
    assert result.says_open
    assert result.confidence == 0.9
    assert result.notes == notes


@pytest.mark.parametrize(("text", "kind", "dates"), PAST_KEPT)
def test_a_past_status_without_an_open_day_is_kept(
    text: str, kind: str, dates: tuple[date, ...]
) -> None:
    result = parse_status(text, posted_at=TUE, tz=TZ)
    assert result.kind == kind
    assert result.dates == dates
    assert not result.says_open


@pytest.mark.parametrize("case", HELD_DISMISSALS)
def test_a_held_dismissal_is_never_a_late_start(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", GAME_DELAYS)
def test_a_game_delay_is_never_a_late_start(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", OTHER_DELAYS)
def test_something_else_delayed_is_never_a_late_start(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", OTHER_CANCELLATIONS)
def test_something_else_called_off_never_closes_the_school(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", SCHOOL_SUBJECTS)
def test_the_school_as_subject_keeps_its_status(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", KNOWN_NOUNS)
def test_a_known_noun_keeps_its_own_note(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", IN_PERSON)
def test_classes_held_in_person_called_off_are_unclear(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", BESIDE)
def test_a_side_note_beside_a_status_leaves_it_standing(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", NO_DAY)
def test_a_year_or_a_closure_for_good_is_no_days_status(case: Row) -> None:
    check(case)


def test_the_tables_hold_enough_cases() -> None:
    tables = (
        HELD_DISMISSALS, GAME_DELAYS, OTHER_DELAYS, OTHER_CANCELLATIONS, SCHOOL_SUBJECTS,
        KNOWN_NOUNS, IN_PERSON, BESIDE, NO_DAY, OPEN_AFTER_PAST, PAST_KEPT, UNTIL_LATER_TODAY,
        DAY_ENDS,
    )  # fmt: skip
    assert sum(len(table) for table in tables) >= 200


def test_reading_words_again_once_forgotten_reads_them_the_same(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Each word's role and each subject's reading are kept up to a bound, then forgotten.
    monkeypatch.setattr(subjects_module, "_MOST_WORDS", 1)
    monkeypatch.setattr(subjects_module, "_MOST_WINDOWS", 1)
    for text in ("Zorvanite delayed", "Kelbrun pictures cancelled", "Quillary Academy closed"):
        first = parse_status(text, posted_at=TUE, tz=TZ)
        again = parse_status(f"{text} today", posted_at=TUE, tz=TZ)
        assert first.kind == again.kind
    assert parse_status("Zorvanite delayed", posted_at=TUE, tz=TZ).kind == "other"
    assert parse_status("Quillary Academy closed", posted_at=TUE, tz=TZ).kind == "closed"


def test_the_quick_look_after_a_delay_finds_every_word_that_reads_there() -> None:
    # The quick look (see subjects._AFTER_NOUN_STARTS) must let through every word the full
    # reading of the words after "delay" acts on.
    starts = subjects_module._AFTER_NOUN_STARTS
    for word in (*subjects_module._DISMISSAL, *subjects_module._DISMISSAL_LEADS):
        assert f" {word} ".startswith(starts), word
    for word in (*subjects_module._PLACE_PREPOSITIONS, "for"):
        assert f" {word} ".startswith(starts), word
    # Nor may the words it passes over after "delayed" be any that the reading acts on.
    plain = subjects_module._PLAIN_AFTER_DELAYED
    for word in (*subjects_module._DISMISSAL, *subjects_module._DISMISSAL_LEADS, "today's"):
        assert not f" {word} ".startswith(plain), word


# Properties ------------------------------------------------------------------------------

instants = st.datetimes(min_value=datetime(2021, 1, 1), max_value=datetime(2031, 12, 31)).map(
    lambda moment: moment.replace(tzinfo=ZONE)
)
# Nouns for things that are late or off and are not the school's day.
OTHER_NOUNS = (
    "Payroll", "Paychecks", "Deliveries", "Meals", "Snowplows", "Repairs", "Graduation",
    "Bond vote", "Board vote", "Kickoff", "Results", "Newsletter", "Picture day",
    "Report cards", "Construction", "Mail", "Yearbook", "Testing", "Picture retakes",
    "Prom", "Musical", "Spirit week", "Walkout", "Photos", "Pictures", "Trash pickup",
    "Snow removal", "Lincoln", "Nurse visits", "School pictures", "School play",
    "School store", "School photos",
)  # fmt: skip
OTHER_VERBS = (
    "delayed", "is delayed", "will be delayed", "has been delayed", "delayed 2 hours",
    "delayed until Friday", "cancelled", "canceled", "has been cancelled", "postponed",
    "closed", "delay",
)  # fmt: skip
TAILS = ("", " today", " tomorrow", " due to snow", " due to the storm", ".", " Wednesday")


@settings(max_examples=400, deadline=None)
@given(
    noun=st.sampled_from(OTHER_NOUNS),
    verb=st.sampled_from(OTHER_VERBS),
    tail=st.sampled_from(TAILS),
    upper=st.booleans(),
    posted=instants,
)
def test_something_else_late_or_off_never_glows(
    noun: str, verb: str, tail: str, upper: bool, posted: datetime
) -> None:
    text = f"{noun} {verb}{tail}"
    result = parse_status(text.upper() if upper else text, posted_at=posted, tz=TZ)
    assert result.kind == "other"
    assert result.schedule == ()


@settings(max_examples=200, deadline=None)
@given(
    noun=st.sampled_from(OTHER_NOUNS),
    verb=st.sampled_from(("cancelled", "Cancelled", "canceled", "postponed", "CANCELLED")),
    mark=st.sampled_from((": ", " - ", ":")),
    posted=instants,
)
def test_something_else_called_off_under_a_label_never_glows(
    noun: str, verb: str, mark: str, posted: datetime
) -> None:
    result = parse_status(f"{noun}{mark}{verb}", posted_at=posted, tz=TZ)
    assert result.kind == "other"
    assert result.schedule == ()


DISMISSAL_LEADS = ("", "Afternoon ", "School ", "Today's ", "PM ")
DISMISSAL_NOUNS = ("dismissal", "release", "pickup")
DISMISSAL_VERBS = (
    " delayed", " is delayed", " will be delayed", " delayed 30 minutes", " delayed 1 hour",
    " will be delayed 30 minutes", " delay", " has been delayed",
)  # fmt: skip
CAUSES = ("", " due to storms", " due to severe weather", " due to lightning", " today")


@settings(max_examples=400, deadline=None)
@given(
    lead=st.sampled_from(DISMISSAL_LEADS),
    noun=st.sampled_from(DISMISSAL_NOUNS),
    verb=st.sampled_from(DISMISSAL_VERBS),
    cause=st.sampled_from(CAUSES),
    flipped=st.booleans(),
    posted=instants,
)
def test_a_held_dismissal_never_reads_as_a_late_start(  # noqa: PLR0913, PLR0917 - drawn parts
    lead: str, noun: str, verb: str, cause: str, flipped: bool, posted: datetime
) -> None:
    text = f"Delayed {lead.lower()}{noun}{cause}" if flipped else f"{lead}{noun}{verb}{cause}"
    result = parse_status(text[0].upper() + text[1:], posted_at=posted, tz=TZ)
    assert result.kind != "delayed"
    assert all(entry.kind != "delayed" for entry in result.schedule)


SCHOOL_NOUNS = (
    "School", "Schools", "All schools", "Classes", "All classes", "Opening", "School start",
    "Start", "Arrival", "District", "Lincoln Elementary", "Maple Grove Middle School",
    "Oak Ridge High School", "Washington County Schools", "The district",
)  # fmt: skip
SCHOOL_VERBS = (
    "delayed", "delayed 2 hours", "is delayed 2 hours", "will be delayed 2 hours",
    "delayed until 10",
)  # fmt: skip


@settings(max_examples=300, deadline=None)
@given(
    noun=st.sampled_from(SCHOOL_NOUNS),
    verb=st.sampled_from(SCHOOL_VERBS),
    tail=st.sampled_from(("", " today", " due to snow", " due to icy roads")),
    posted=instants,
)
def test_the_school_delayed_is_a_late_start(
    noun: str, verb: str, tail: str, posted: datetime
) -> None:
    result = parse_status(f"{noun} {verb}{tail}", posted_at=posted, tz=TZ)
    delayed = parse_status(f"2 hour delay{tail}", posted_at=posted, tz=TZ)
    assert result.kind == delayed.kind
    assert result.dates == delayed.dates


STATUSES = ("Closed today", "2 hour delay today", "NTI day today", "Early dismissal at 1 PM")


@settings(max_examples=300, deadline=None)
@given(
    status=st.sampled_from(STATUSES),
    noun=st.sampled_from(OTHER_NOUNS),
    verb=st.sampled_from(("delayed", "cancelled", "postponed", "delayed 2 hours")),
    first=st.booleans(),
    posted=instants,
)
def test_a_side_note_never_changes_the_status_beside_it(
    status: str, noun: str, verb: str, first: bool, posted: datetime
) -> None:
    note = f"{noun} {verb}"
    text = f"{note}. {status}." if first else f"{status}. {note}."
    result = parse_status(text, posted_at=posted, tz=TZ)
    alone = parse_status(status, posted_at=posted, tz=TZ)
    assert result.kind == alone.kind
    assert result.dates == alone.dates
