"""A status for only part of a district: exceptions, restrictions, places and named sites.

Every text here is a phrasing pattern written for these tests, not a claim about a
real school; the school and place names are made up or generic. Unless a row says
otherwise it is posted at 6 a.m. on Tuesday 20 January 2026 in New York, so
"today" is Tuesday the 20th and "tomorrow" Wednesday the 21st.

* A status that leaves some of the district's schools out ("All schools closed
  except Lincoln Elementary", "with the exception of", "other than", "All
  schools except Lincoln are closed", "for all schools but Lincoln", "Lincoln
  Elementary excluded"), is restricted to some ("Closed (Lincoln Elementary
  only)", "Closed only at Lincoln Elementary"), names a place ("Closed at some
  locations", "in the northern part of the district", "north of Route 9",
  "North campus closed", "All other schools on a 2 hour delay") or names its
  sites ("PTEC, Astrozon and Howard campuses closed") is about part of the
  program: ``other`` at 0.9, noted ``partial_program``, with no schedule. So is
  every status after the phrase in its sentence ("..., which will have a 2 hour
  delay"), and an "open" it limits says nothing of the school running as normal.
* Leaving out people or services that are not the school day keeps the status:
  "Closed except staff", "except essential staff", "except central office",
  "except for food service", "Closed - essential personnel only", "Remote
  learning only". So does a place named for the weather ("Closed due to
  flooding north of Route 9"), a school's own name with a direction ("North
  Elementary: Closed"), one site at either end of the text set off by a mark,
  which is the listing's own name ("Closed - Oak Ridge Campus", "Morehead State
  - Ashland Campus: Closed"), and every site at once ("All campuses closed").
* A school, a level or a site named open, or on a status of another kind,
  beside a status ("Closed. Lincoln Elementary open.", "Closed - high school
  open", "Closed. Lincoln Elementary on a 2 hour delay.") leaves the district no
  one status: ``other``, noted ``partial_program``, as an exception does. Its
  status on plainly other days leaves the status standing ("Closed today;
  Lincoln Elementary open tomorrow"), and so does a part of the program
  ("2 hour delay. AM preschool cancelled.") or a building open for a service.
* An exception for a day ("Closed Monday through Friday except Wednesday")
  leaves the days unread: ``other`` at 0.3, noted ``unreadable_date``.
* Two lengths for one delay ("2 or 3 hour delay") settle no length.
* A listing longer than the parser reads is read at its start and its end and
  noted ``truncated``: a status read is 0.8 at most, no status 0.3 at most.
"""

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from snowlight.classify import parse_status
from snowlight.classify import partial as partial_module
from snowlight.classify.text import MAX_CHARS

TZ = "America/New_York"
ZONE = ZoneInfo(TZ)
MORNING = datetime(2026, 1, 20, 6, 0, tzinfo=ZONE)  # Tuesday
EVENING = datetime(2026, 1, 20, 20, 0, tzinfo=ZONE)


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
    absent: tuple[str, ...]
    delay: int | None
    early: int | None


def row(  # noqa: PLR0913 - one table row
    text: str,
    kind: str = "other",
    dates: tuple[date, ...] = (),
    *,
    posted: datetime = MORNING,
    confidence: float = 0.9,
    notes: tuple[str, ...] = (),
    absent: tuple[str, ...] = (),
    delay: int | None = None,
    early: int | None = None,
) -> object:
    label = f"{text[:60]} @ {posted:%a %H:%M}"
    case = Row(text, posted, kind, dates, confidence, notes, absent, delay, early)
    return pytest.param(case, id=label)


def part(text: str, *, posted: datetime = MORNING) -> object:
    """A status about part of the district: no status for the district."""
    return row(text, posted=posted, notes=("partial_program",))


def kept(  # noqa: PLR0913 - one table row
    text: str,
    kind: str = "closed",
    dates: tuple[date, ...] = jan(20),
    *,
    confidence: float = 0.9,
    posted: datetime = MORNING,
    delay: int | None = None,
) -> object:
    """A status whose exception or restriction is not part of the school day: it stands."""
    return row(
        text,
        kind,
        dates,
        posted=posted,
        confidence=confidence,
        absent=("partial_program",),
        delay=delay,
    )


def check(case: Row) -> None:
    result = parse_status(case.text, posted_at=case.posted, tz=TZ)
    assert result.kind == case.kind
    assert result.dates == case.dates
    assert result.confidence == case.confidence
    assert set(case.notes) <= set(result.notes)
    assert not set(case.absent) & set(result.notes)
    assert result.delay_minutes == case.delay
    assert result.dismissal_early_minutes == case.early
    if case.kind == "other":
        assert result.schedule == ()
        assert not result.says_open


# Exceptions: the status leaves a school out, so it is no status of the district's.
EXCEPTIONS = [
    part("All schools closed except Lincoln Elementary"),
    part("All schools closed except Lincoln Elementary, which is open"),
    part("All schools closed with the exception of Lincoln Elementary"),
    part("All schools closed other than Lincoln"),
    part("All schools except Lincoln are closed"),
    part("2 hour delay except Lincoln Elementary"),
    part("2 hour delay for all schools but Lincoln"),
    part("All schools closed, except Lincoln Elementary"),
    part("Closed, except for Lincoln Elementary"),
    part("Closed (except Lincoln)"),
    part("Closed - except Lincoln"),
    part("Closed except Lincoln"),
    part("Closed - all buildings except Lincoln"),
    part("Except for Lincoln Elementary, all schools are closed"),
    part("With the exception of Lincoln Elementary, all schools are closed"),
    part("Schools closed excluding Lincoln Elementary"),
    part("All schools closed but Lincoln Elementary"),
    part("All schools closed but not Lincoln Elementary"),
    part("All schools closed besides Lincoln Elementary"),
    part("All schools closed save for Lincoln Elementary"),
    part("All schools closed apart from Lincoln Elementary"),
    part("All schools closed aside from Lincoln Elementary"),
    part("All schools closed minus Lincoln Elementary"),
    part("All schools are on a 2 hour delay but Lincoln Elementary"),
    part("Closed (excluding Lincoln Elementary)"),
    part("All schools closed, Lincoln Elementary excluded"),
    part("All schools closed, the high school excluded"),
    part("Schools closed. Exception: Lincoln Elementary."),
    part("ALL SCHOOLS CLOSED EXCEPT LINCOLN ELEMENTARY"),
    part("All district schools closed except LHS"),
    part("All schools closed except for the high school"),
    part("Closed except for the north campus"),
    part("Closed except for Pre-K"),
    part("No school except for the high school"),
    part("No school except for seniors"),
    part("Closed for all students other than seniors"),
    part("Closed except for Lincoln Elementary students"),
    part("Closed except Lincoln Elementary's preschool"),
    part("Closed except for a few"),
    part("All schools closed except as noted"),
    part("All schools closed except Lincoln Elementary and Washington Elementary"),
    part("2 hour delay for everyone but Lincoln"),
    part("All schools but Lincoln Elementary closed"),
    part("Every school but one is closed"),
    part("Remote learning except for Lincoln Elementary"),
    part("Remote learning for all students except those at Lincoln Elementary"),
    part("NTI day for all schools except Lincoln Elementary"),
    part("E-learning day except Lincoln Elementary"),
    part("Early dismissal at 1:00 except Lincoln"),
    part("Classes cancelled except at Lincoln Elementary"),
    part("Closed today due to snow, except Lincoln Elementary"),
    part("Closed Monday except for Lincoln Elementary"),
    part("Closed Wednesday except Lincoln Elementary"),
    part("Closed Thursday and Friday except Lincoln Elementary"),
    part("Closed tomorrow except Lincoln Elementary", posted=EVENING),
    part("All schools closed tomorrow except Maple Grove Middle School", posted=EVENING),
    part("Closed except Kaluzo Elementary"),  # a made-up name, which the parser masks
    part("Closed except Bakutemi Zorafa"),
    part("All schools closed today except Lincoln Elementary"),
    part("Schools are closed except for Lincoln Elementary School"),
    part("All buildings closed except Lincoln Elementary"),
    part("Closed for all students except seniors"),
    part("Remote learning day for all schools except the high school"),
    part("2-hour delay for all schools except Lincoln"),
    part("Delayed opening except Lincoln Elementary"),
    part("Early release for all schools except Lincoln Elementary"),
    part("No school for all students except those at the career center"),
    part("Closed excepting Lincoln Elementary"),
    part("All schools closed except Lincoln Elementary (2 hour delay)"),
    part("Except where noted, all schools closed"),
    part("All schools closed except where noted"),
    part("Closed until further notice except for Lincoln Elementary"),
]

# Every status after the exception in its sentence is the part left out's: no status stands.
AFTER_THE_EXCEPTION = [
    part(
        "All schools are closed today except for Lincoln Elementary, which will have a 2 hour delay"
    ),
    part(
        "All schools will be closed except for Lincoln Elementary School, which will operate "
        "on a 2-hour delay"
    ),
    part("2 hour delay for all schools except Lincoln Elementary (closed)"),
    part("All schools on a 2 hour delay except Lincoln Elementary, which is closed"),
    part("All schools closed. Except Lincoln Elementary, which has a 2 hour delay."),
    part("Open except Lincoln Elementary, which is closed"),
    part("Open on time except Lincoln Elementary"),
    part("All schools open except Lincoln Elementary closed due to a power outage"),
]

# Leaving out people or services that are not the school day: the status stands.
KEPT_EXCEPTIONS = [
    kept("Closed except staff"),
    kept("Closed except essential staff"),
    kept("Closed except for essential staff"),
    kept("Closed with the exception of essential staff"),
    kept("Closed except emergency personnel"),
    kept("Closed except for essential personnel"),
    kept("Closed except for essential employees"),
    kept("Closed except 12-month employees"),
    kept("Closed except administrators"),
    kept("Closed except custodians"),
    kept("Closed for everyone except staff"),
    kept("Closed for all except staff"),
    kept("All schools closed, staff excluded"),
    kept("All schools closed except central office"),
    kept("All buildings closed except the administration building"),
    kept("Closed except for food service"),
    kept("School closed except for daycare"),
    kept("Closed except for athletics"),
    kept("Closed except bus garage"),
    kept("Closed except for custodial staff"),
    kept("Closed except in emergencies"),
    kept("Closed except for maintenance crews"),
    kept("Closed except for meal pickup"),
    kept("No school except for essential staff"),
    kept("2 hour delay for all students except staff", "delayed", delay=120),
    kept("Remote learning for all students except staff", "remote"),
    kept("Closed tomorrow except essential staff", dates=jan(21), confidence=0.95),
    kept("Closed today, no exceptions", confidence=0.95),
    kept("No exceptions: all schools closed"),
    kept("School closed. Exceptions: none."),
    kept("Closed tomorrow. Other than that, normal schedule", dates=jan(21), confidence=0.95),
    kept("Closed tomorrow. Other than the above, normal schedule", dates=jan(21), confidence=0.95),
]

# An exception about something besides the status leaves the status as it is.
OTHER_EXCEPTIONS = [
    row(
        "Closed today. Activities cancelled except varsity basketball.",
        "closed",
        jan(20),
        confidence=0.95,
        notes=("activities_cancelled",),
        absent=("partial_program",),
    ),
    row(
        "Closed today, all activities cancelled except varsity basketball",
        "closed",
        jan(20),
        confidence=0.95,
        notes=("activities_cancelled",),
        absent=("partial_program",),
    ),
    # Another sentence's status stands, as a judgment call beside the part left out.
    row(
        "Closed today except Lincoln Elementary. Closed tomorrow.",
        "closed",
        jan(21),
        confidence=0.8,
        notes=("partial_program",),
    ),
    row(
        "Closed tomorrow. Open today except Lincoln Elementary.",
        "closed",
        jan(21),
        confidence=0.8,
        notes=("partial_program",),
    ),
]

# A restriction to some schools by name, or to a campus; not to a service or to people.
RESTRICTIONS = [
    part("Closed (Lincoln Elementary only)"),
    part("Closed (Lincoln only)"),
    part("Closed - Lincoln Elementary only"),
    part("Closed for Lincoln Elementary only"),
    part("2 hour delay Lincoln Elementary only"),
    part("Closed only at Lincoln Elementary"),
    part("Closed only for Lincoln"),
    part("Remote learning - north campus only"),
    part("Closed - east campus only"),
    part("Closed (high school only)"),
    part("Closed - Jefferson only"),
    part("Closed (Kaluzo only)"),
    part("Closed - Bakutemi Zorafa only"),
]
KEPT_RESTRICTIONS = [
    kept("Remote learning only", "remote"),
    kept("Virtual learning only", "remote"),
    kept("Remote learning only for students", "remote"),
    kept("Closed, online classes only", "remote"),
    kept("Closed - essential personnel only"),
    kept("Closed - emergency staff only"),
    kept("Closed. Essential staff only."),
    kept("Closed - students only"),
    kept("Closed for in-person learning only"),
    kept("Closed - meal pickup only"),
    kept("Closed today only", confidence=0.95),
    kept("Closed tomorrow only", dates=jan(21), confidence=0.95),
    kept("Closed for students only; staff report at 10"),
    kept("2 hour delay - buses on main roads only", "delayed", delay=120),
]

# A place: some locations, part of the area, one side of a road, one campus.
PLACES = [
    part("Closed at some locations"),
    part("Closed at select locations"),
    part("Closed at select schools"),
    part("Some locations closed"),
    part("Several buildings closed"),
    part("Closed in parts of the county"),
    part("Closed in some areas of the district"),
    part("Closed for affected areas"),
    part("Closed in the northern part of the district"),
    part("Closed in the southern part of the county"),
    part("Northern part of the district closed"),
    part("Closed in the north end of the county"),
    part("Closed on the east side of the county"),
    part("Closed north of Route 9"),
    part("Closed south of I-80"),
    part("Closed for students north of Route 9"),
    part("Closed for students who live north of Route 9"),
    part("Closed north of Route 9; 2 hour delay south of Route 9"),
    part("North campus closed"),
    part("South campus on 2 hour delay"),
    part("North campus closed, south campus 2 hour delay"),
    part("All remaining schools closed"),
    part("Lincoln Elementary closed. All other schools on a 2 hour delay."),
    part("Lincoln Elementary: closed. Other schools open."),
    part("2 hour delay for most schools"),
    part("Closed for some students"),
    part("Closed in the western part of the county"),
    part("Closed in the far northern part of the district"),
    part("Closed east of the river"),
    part("Closed for schools west of Highway 61"),
    part("Closed in outlying areas of the district"),
    part("Closed at certain schools"),
    part("Closed at multiple locations"),
    part("Closed for the following schools: Lincoln, Washington"),
    part("Remote learning at select campuses"),
    part("2 hour delay in some areas"),
    part("Closed for the north side of the county"),
    part("Other schools: open. Lincoln Elementary: closed."),
    part("Closed at some schools; 2 hour delay at others"),
    part("Closed at some locations due to power outages"),
]
KEPT_PLACES = [
    kept("Closed due to flooding north of Route 9"),
    kept("Closed due to snow in parts of the county"),
    kept("Closed. Heavy snow in the northern part of the county."),
    kept("Closed, storm moving north of us"),
    kept("Winter storm warning for areas north of I-80. Closed."),
    kept("North Elementary: Closed"),
    kept("West Side Elementary: Closed"),
    kept("East End Elementary: closed"),
    kept("Northwest Local Schools: closed"),
    kept("Closed in our area"),
    # A site at either end of the text, set off by a mark, is the listing's own name.
    kept("East campus: closed"),
    kept("North Campus: Closed"),
    kept("Closed - west building"),
    kept("Closed - North Campus"),
    kept("Snow north of I-70, closed"),
    kept("Closed, power outage in some areas"),
    kept("Some areas without power, closed"),
    kept("Closed, trees down in parts of the county"),
    kept("Closed, along with other schools in the area"),
    kept("Closed like other schools in the area"),
]

# Sites by name: some of a district's campuses or locations; not all of them, nor its own.
SITES = [
    part("Lincoln campus closed"),
    part("PTEC, Astrozon and Howard campuses closed"),
    part("Des Moines locations closed"),
    part("Monument, Palmer Lake, High Prairie locations closed"),
    part("Closed at the Lincoln site"),
    part("Southside campus closed"),
    part("Kaluzo campus closed"),
    part("Jefferson Davis campus closed"),
    part("Riverside campus on a 2 hour delay"),
    part("Maple and Oak campuses closed"),
    part("Downtown campus closed"),
    part("Lincoln building closed"),
    part("Elementary campuses closed"),
    part("High school campus closed"),
    part("Middle school buildings closed"),
    part("Closed: Des Moines locations"),
    part("Closed today at the Lincoln site", posted=MORNING),
    part("Closed today (Lincoln Elementary only)"),
]
KEPT_SITES = [
    kept("All campuses closed"),
    kept("Both campuses closed"),
    kept("Campus closed"),
    kept("Main campus closed"),
    kept("Our campus is closed"),
    kept("All locations closed"),
    kept("Closed at all locations"),
    kept("Our location is closed"),
    kept("This location closed today", confidence=0.95),
    kept("School site closed"),
    kept("Closed: all sites"),
    kept("School campuses closed"),
    kept("Each campus will be closed"),
    kept("Our main campus and all locations are closed"),
    kept("All buildings closed"),
    kept("School buildings closed"),
    kept("The building is closed"),
    kept("Main building closed"),
    # The listing's own name, before or after its status.
    kept("Closed - Kolemo Campus"),
    kept("Closed - Kolemo Campus."),
    kept("Late Start - Bomodo Campus", "delayed"),
    kept("Closed Today - Bebedu Campus", confidence=0.95),
    kept("Closed Tomorrow - Mokimo Campus", dates=jan(21), confidence=0.95),
    kept("Morehead State - Ashland Campus: Closed"),
    kept("Lancaster Mennonite School - Lancaster Campus: 2 hour delay", "delayed", delay=120),
    kept("Campus Rec and all activities cancelled", "other", (), confidence=0.9),
]

# A school named open beside a status: no status of the whole district.
NAMED_OPEN = [
    row("Closed. Lincoln Elementary open.", notes=("partial_program",)),
    row("Closed but Lincoln Elementary open", notes=("partial_program",)),
    row("2 hour delay. Lincoln Elementary on regular schedule.", notes=("partial_program",)),
    row("Closed - high school open", notes=("partial_program",)),
    row("Closed; high school open", notes=("partial_program",)),
    row("Closed. High school open.", notes=("partial_program",)),
    row("Closed. High school on regular schedule.", notes=("partial_program",)),
    row("Closed. Lincoln Elementary on a 2 hour delay.", notes=("partial_program",)),
    row("2 hour delay. Lincoln Elementary closed.", notes=("partial_program",)),
    row("Closed Tuesday; Early Childhood Center open", notes=("partial_program",)),
    row("All locations are open and operating on time, with the exception of the Kubaze "
        "Center. The Kubaze Center is closed.", notes=("partial_program",)),
    row("Closed today - Elementary and high school virtual", notes=("partial_program",)),
    # ... but not on plainly other days, nor a part of the program or a building's service.
    row("Closed today; Lincoln Elementary open tomorrow", "closed", jan(20), confidence=0.8,
        notes=("partial_program",)),
    row("2 hour delay. AM preschool cancelled.", "delayed", jan(20), confidence=0.8,
        delay=120, notes=("partial_program",)),
    row("Closed today. Lincoln Elementary open as a warming center.", "closed", jan(20),
        confidence=0.8, notes=("partial_program",)),
]  # fmt: skip

# A band of grades, a year or a program of students, or a count of schools: part of the
# district.
SCOPED = [
    row("No school for K-5", notes=("partial_program",)),
    row("Closed for K-5", notes=("partial_program",)),
    row("Snow day for K-5", notes=("partial_program",)),
    row("2 hour delay for K-8", notes=("partial_program",)),
    row("Remote learning for PK-8", notes=("partial_program",)),
    row("Closed for grades K-5", notes=("partial_program",)),
    row("Closed for students in grades 6 through 12", notes=("partial_program",)),
    row("Closed for students in grades K-5", notes=("partial_program",)),
    row("Closed for students in kindergarten through 5th grade", notes=("partial_program",)),
    row("Closed for kindergarten through 5th grade", notes=("partial_program",)),
    row("Closed for students in K-8", notes=("partial_program",)),
    row("Closed for students in 9th through 12th grade", notes=("partial_program",)),
    row("2 hour delay for all students in grades K-5", notes=("partial_program",)),
    # Classes at a time of the day, and a count of places in figures: part of the day or the
    # district.
    row("8:00 classes cancelled", notes=("partial_program",)),
    row("All 8:00 classes cancelled", notes=("partial_program",)),
    row("Classes at 8:00 cancelled", notes=("partial_program",)),
    row("Classes at 8 am cancelled", notes=("partial_program",)),
    row("10:00 classes cancelled", notes=("partial_program",)),
    row("Classes cancelled at 2 schools", notes=("partial_program",)),
    row("Closed at 2 locations today", notes=("partial_program",)),
    row("Closed for seniors", notes=("partial_program",)),
    row("No school for freshmen", notes=("partial_program",)),
    row("Three schools closed", notes=("partial_program",)),
    row("Two schools closed today", notes=("partial_program",)),
    row("Closed at two schools", notes=("partial_program",)),
    row("4 schools closed", notes=("partial_program",)),
    row("Closed for hybrid students", notes=("partial_program",)),
    row("Two Hour Delay - Lincoln Elementary closed at two campuses", notes=("partial_program",)),
    # A count of all of them is every one; a length is no count.
    row("Two hour delay", "delayed", jan(20), delay=120),
    row("All three campuses closed", "closed", jan(20)),
    row("(Tomorrow) All three campuses - closed", "closed", jan(21), confidence=0.95),
]  # fmt: skip

# An exception for a day: which days the status is for is not read.
DAYS_LEFT_OUT = [
    row("Closed Monday through Friday except Wednesday", confidence=0.3,
        notes=("unreadable_date",)),
    row("Closed this week except Wednesday", confidence=0.3, notes=("unreadable_date",)),
    row("Closed today and tomorrow except on Wednesday", confidence=0.3,
        notes=("unreadable_date",)),
    row("Closed except Thursday", confidence=0.3, notes=("unreadable_date",)),
]  # fmt: skip

# Two lengths for one delay settle neither; a date's day or a change's old length is no second.
LENGTHS = [
    row("2 or 3 hour delay", "delayed", jan(20), confidence=0.8),
    row("2 to 3 hour delay", "delayed", jan(20), confidence=0.8),
    row("Two or three hour delay", "delayed", jan(20), confidence=0.8),
    row("90 minutes to 2 hour delay", "delayed", jan(20), confidence=0.8),
    row("2 or 3 hours early dismissal", "early_dismissal", jan(20)),
    row("3/11-2 hour delay", "delayed", (date(2026, 3, 11),), confidence=0.95, delay=120,
        posted=datetime(2026, 3, 10, 7, 5, tzinfo=ZONE)),
    row("changed from 1 to 2 hour delay", "delayed", jan(20), delay=120),
    row("2 hour delay", "delayed", jan(20), delay=120),
    # A club's name is no closure.
    row("Closed Captioning Club cancelled", notes=("activities_cancelled",)),
]  # fmt: skip


@pytest.mark.parametrize(
    "case",
    EXCEPTIONS
    + AFTER_THE_EXCEPTION
    + KEPT_EXCEPTIONS
    + OTHER_EXCEPTIONS
    + RESTRICTIONS
    + KEPT_RESTRICTIONS
    + PLACES
    + KEPT_PLACES
    + SITES
    + KEPT_SITES
    + NAMED_OPEN
    + SCOPED
    + DAYS_LEFT_OUT
    + LENGTHS,
)
def test_a_status_for_part_of_a_district(case: Row) -> None:
    check(case)


def test_the_tables_are_large() -> None:
    tables = (
        EXCEPTIONS, AFTER_THE_EXCEPTION, KEPT_EXCEPTIONS, OTHER_EXCEPTIONS, RESTRICTIONS,
        KEPT_RESTRICTIONS, PLACES, KEPT_PLACES, SITES, KEPT_SITES, NAMED_OPEN, SCOPED,
        DAYS_LEFT_OUT, LENGTHS,
    )  # fmt: skip
    assert sum(len(table) for table in tables) >= 200


def test_an_excepted_school_open_says_nothing_of_school_running() -> None:
    result = parse_status("All schools closed except Lincoln Elementary, which is open",
                          posted_at=MORNING, tz=TZ)  # fmt: skip
    assert not result.says_open
    assert result.on(date(2026, 1, 20)) is None


# Properties ---------------------------------------------------------------------------

STATUS_KIND = {
    "Closed": "closed",
    "No school": "closed",
    "Schools closed": "closed",
    "2 hour delay": "delayed",
    "Delayed opening": "delayed",
    "Remote learning": "remote",
    "NTI day": "remote",
    "E-learning day": "remote",
    "Early dismissal at 1:00": "early_dismissal",
}
STATUSES = tuple(STATUS_KIND)
NAMES = (
    "Lincoln", "Maple Grove", "Oak Ridge", "Riverside", "Hillcrest", "Kaluzo", "Bakutemi Zorafa",
    "Washington", "Cedar Point", "Pine Hollow",
)  # fmt: skip
SCHOOL_TYPES = ("Elementary", "Middle School", "High School", "Academy", "campus", "")
EXCEPT_CUES = (
    "except", "except for", "with the exception of", "excluding", "other than", "besides",
    "save for", "apart from", "aside from", "minus",
)  # fmt: skip
PEOPLE = (
    "staff", "essential staff", "essential personnel", "emergency personnel", "custodians",
    "central office", "the district office", "food service", "daycare", "athletics",
    "12-month employees", "administrators",
)  # fmt: skip
DIRECTIONS = ("north", "south", "east", "west")
instants = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31),
    timezones=st.just(ZONE),
)


def school(name: str, kind: str) -> str:
    return f"{name} {kind}".strip()


@settings(max_examples=300, deadline=None)
@given(
    status=st.sampled_from(STATUSES),
    cue=st.sampled_from(EXCEPT_CUES),
    name=st.sampled_from(NAMES),
    kind=st.sampled_from(SCHOOL_TYPES),
    lead=st.booleans(),
    posted=instants,
)
def test_a_status_that_leaves_a_school_out_is_no_district_status(  # noqa: PLR0913, PLR0917
    status: str, cue: str, name: str, kind: str, lead: bool, posted: datetime
) -> None:
    text = (
        f"{cue.capitalize()} {school(name, kind)}, {status.lower()} for all schools"
        if lead
        else f"{status} {cue} {school(name, kind)}"
    )
    result = parse_status(text, posted_at=posted, tz=TZ)
    assert result.kind == "other", text
    assert result.schedule == (), text
    assert not result.says_open, text


@settings(max_examples=200, deadline=None)
@given(
    status=st.sampled_from(STATUSES),
    name=st.sampled_from(NAMES),
    kind=st.sampled_from(SCHOOL_TYPES),
    form=st.integers(0, 3),
    posted=instants,
)
def test_a_status_for_some_schools_by_name_is_no_district_status(
    status: str, name: str, kind: str, form: int, posted: datetime
) -> None:
    named = school(name, kind)
    text = (
        f"{status} ({named} only)",
        f"{status} only at {named}",
        f"{status} for all schools but {named}",
        f"All schools except {named}: {status.lower()}",
    )[form]
    result = parse_status(text, posted_at=posted, tz=TZ)
    assert result.kind == "other", text
    assert result.schedule == (), text


@settings(max_examples=200, deadline=None)
@given(
    status=st.sampled_from(STATUSES),
    direction=st.sampled_from(DIRECTIONS),
    route=st.integers(1, 99),
    form=st.integers(0, 4),
    posted=instants,
)
def test_a_status_for_part_of_the_area_is_no_district_status(
    status: str, direction: str, route: int, form: int, posted: datetime
) -> None:
    text = (
        f"{status} {direction} of Route {route}",
        f"{status} in the {direction}ern part of the district",
        f"{direction.capitalize()} campus {status.lower()}",
        f"{status} at some locations",
        f"{status} on the {direction} side of the county",
    )[form]
    result = parse_status(text, posted_at=posted, tz=TZ)
    assert result.kind == "other", text
    assert result.schedule == (), text


@settings(max_examples=200, deadline=None)
@given(
    status=st.sampled_from(STATUSES),
    cue=st.sampled_from(EXCEPT_CUES[:3]),
    people=st.sampled_from(PEOPLE),
)
def test_leaving_out_people_or_services_keeps_the_status(
    status: str, cue: str, people: str
) -> None:
    text = f"{status} today {cue} {people}"
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == STATUS_KIND[status], text
    assert result.dates == jan(20), text
    assert "partial_program" not in result.notes, text


@settings(max_examples=100, deadline=None)
@given(first=st.integers(1, 4), second=st.integers(1, 4), joiner=st.sampled_from(("or", "to")))
def test_two_lengths_settle_no_length(first: int, second: int, joiner: str) -> None:
    result = parse_status(f"{first} {joiner} {second} hour delay", posted_at=MORNING, tz=TZ)
    assert result.kind == "delayed"
    assert result.delay_minutes is None


# A long listing --------------------------------------------------------------------------

FILLER = "The district will share more about the storm as it comes. "


@settings(max_examples=60, deadline=None)
@given(
    repeats=st.integers(MAX_CHARS // len(FILLER) + 1, 4 * MAX_CHARS // len(FILLER)),
    head=st.sampled_from(("Closed today. ", "2 hour delay today. ", "")),
    tail=st.sampled_from(("UPDATE: open on time", "Closed today.", "", "Open on time.")),
)
def test_a_long_listing_is_read_at_its_start_and_its_end(
    repeats: int, head: str, tail: str
) -> None:
    text = head + FILLER * repeats + tail
    assert len(text) > MAX_CHARS
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert "truncated" in result.notes
    assert not result.says_open
    if result.kind == "other":
        assert result.confidence <= 0.3
    else:
        assert result.confidence <= 0.8
    if tail.startswith("UPDATE"):
        assert result.kind == "other"  # the update at the end is read
    elif head or tail.startswith("Closed"):
        # A status read at the start or the end stands, unless the two disagree.
        assert result.kind != "other" or "conflict" in result.notes


LONG = [
    ("Closed today. " + FILLER * 100 + "UPDATE: open on time", "other", 0.3),
    ("Closed today. " + FILLER * 100, "closed", 0.8),
    (FILLER * 100 + "Closed today.", "closed", 0.8),
    (FILLER * 100, "other", 0.1),
    ("Closed today. " + FILLER * 100 + "Activities cancelled tonight.", "closed", 0.8),
]


@pytest.mark.parametrize(("text", "kind", "confidence"), LONG, ids=range(len(LONG)))
def test_a_long_listing(text: str, kind: str, confidence: float) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == kind
    assert result.confidence == confidence
    assert "truncated" in result.notes
    assert not result.says_open


def test_a_listing_at_the_limit_is_read_whole() -> None:
    text = "Closed today. " + FILLER * ((MAX_CHARS - 14) // len(FILLER))
    assert len(text) <= MAX_CHARS
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "closed"
    assert "truncated" not in result.notes


def test_every_word_a_phrase_needs_opens_the_gate() -> None:
    """The parser reads these phrases only in a text with a word of CARVE_WORDS."""
    cues = (
        partial_module._EXCEPT_CUES,
        partial_module._EXCLUDED_CUES,
        partial_module._SITE_CUES,
        partial_module._PLACE_CUES,
    )
    for words in cues:
        assert words <= partial_module.CARVE_WORDS
    assert "only" in partial_module.CARVE_WORDS


@settings(max_examples=300, deadline=None)
@given(
    status=st.sampled_from(("closed", "on a 2 hour delay", "dismissing early", "on eLearning")),
    verb=st.sampled_from(("", "are ", "will be ")),
    name=st.sampled_from(NAMES),
    kind=st.sampled_from(("Elementary", "Middle School", "High School", "Academy")),
    negated=st.booleans(),
)
def test_all_schools_but_one_is_no_district_status(
    status: str, verb: str, name: str, kind: str, negated: bool
) -> None:
    text = f"All schools {verb}{status} but {'not ' if negated else ''}{school(name, kind)}"
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other", text
    assert result.schedule == (), text


@settings(max_examples=300, deadline=None)
@given(
    status=st.sampled_from(("Closed", "2 hour delay", "Remote learning", "Early dismissal")),
    who=st.sampled_from(("", "students in ", "all students in ", "pupils in ")),
    band=st.sampled_from(
        (
            "grades K-5",
            "grades 6 through 12",
            "K-8",
            "kindergarten through 5th grade",
            "9th through 12th grade",
            "grades 6-12",
            "PK-8",
        )
    ),
)
def test_a_status_for_a_band_of_grades_is_no_district_status(
    status: str, who: str, band: str
) -> None:
    text = f"{status} for {who}{band}"
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other", text
    assert "partial_program" in result.notes, text


@settings(max_examples=300, deadline=None)
@given(
    hour=st.integers(6, 12),
    minutes=st.sampled_from(("00", "15", "30", "45")),
    form=st.sampled_from(
        (
            "{clock} classes cancelled",
            "All {clock} classes cancelled",
            "Classes at {clock} cancelled",
            "{clock} class canceled",
            "The {clock} classes are cancelled",
        )
    ),
)
def test_classes_at_a_time_of_day_cancelled_are_no_closure(
    hour: int, minutes: str, form: str
) -> None:
    text = form.format(clock=f"{hour}:{minutes}")
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind != "closed", text
    assert result.schedule == () or result.confidence < 0.7, text


@settings(max_examples=300, deadline=None)
@given(
    status=st.sampled_from(
        ("Closed", "2 hour delay", "Remote learning", "eLearning", "Early dismissal", "Late start")
    ),
    first=st.sampled_from(("middle", "intermediate", "junior high", "elementary", "the middle")),
    join=st.sampled_from((" and ", " & ", "/")),
    second=st.sampled_from(
        ("high school", "high schools", "high school students", "middle school")
    ),
    label=st.booleans(),
)  # fmt: skip
def test_a_status_for_two_levels_is_no_district_status(
    status: str, first: str, join: str, second: str, label: bool
) -> None:
    levels = f"{first}{join}{second}"
    text = (
        f"{levels[0].upper()}{levels[1:]}: {status.lower()}" if label else f"{status} for {levels}"
    )
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other", text
    assert "partial_program" in result.notes, text


LEVEL_ROWS = [
    "Closed for middle and high school", "Closed for middle and high schools",
    "Closed for the middle and high schools", "Closed for middle & high school students",
    "Closed for intermediate and high school", "2 hour delay for middle and high school",
    "eLearning for middle and high school", "Secondary students: remote learning",
    "Elementary students: closed", "Early childhood center closed",
    "Early Childhood Center: Closed", "Kindergarten Center: Closed",
]  # fmt: skip


@pytest.mark.parametrize("text", LEVEL_ROWS)
def test_two_levels_a_level_s_students_or_a_program_s_center_is_part_of_the_district(
    text: str,
) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other"
    assert "partial_program" in result.notes


# A school of two levels named by its own name keeps the status, as a named school of one
# level does ("Lincoln Elementary School closed today"). (Synthetic names.)
NAMED_TWO_LEVELS = [
    ("Barrackville Elementary/Middle School in Marion County will be closing at 10:00 today",
     "early_dismissal"),
    ("Lincoln Elementary/Middle School closed today", "closed"),
    ("St. Mary Elementary/Middle School - Closed today", "closed"),
    ("Lincoln Middle/High School: Closed", "closed"),
    ("Lincoln Junior/Senior High School closed today", "closed"),
    ("Lincoln Jr./Sr. High School closed today", "closed"),
    ("Lincoln Jr./Sr. High School: 2 hour delay", "delayed"),
    ("Oak Ridge Middle/High School: remote learning today", "remote"),
    ("Update: Lincoln Middle/High School - closed today", "closed"),
]  # fmt: skip
# The same levels with no name before them, or after a heading's mark, are part of the
# district; so is a single level after a heading's mark.
UNNAMED_LEVELS = [
    "Middle/High School closed today", "Elementary/Middle School in Marion County will be closing",
    "Snow: Middle/High School closed", "Update: Middle/High School closed",
    "Update: Elementary School closed", "Weather Alert: Elementary School closed",
    "Due to snow, middle/high school closed today", "Our middle/high school is closed",
    "All middle/high schools closed", "Closed for middle/high school",
]  # fmt: skip


@pytest.mark.parametrize(("text", "kind"), NAMED_TWO_LEVELS)
def test_a_named_school_of_two_levels_keeps_its_status(text: str, kind: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == kind
    assert result.confidence >= 0.9
    assert result.dates == jan(20)
    assert "partial_program" not in result.notes


@pytest.mark.parametrize("text", UNNAMED_LEVELS)
def test_levels_with_no_name_of_their_own_are_part_of_the_district(text: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other"
    assert "partial_program" in result.notes


@settings(max_examples=200, deadline=None)
@given(
    name=st.sampled_from(("Lincoln", "Barrackville", "St. Mary", "Oak Ridge", "Maple Grove")),
    levels=st.sampled_from(
        ("Elementary/Middle", "Middle/High", "Junior/Senior High", "Jr./Sr. High", "Elementary")
    ),
    status=st.sampled_from(
        (("closed today", "closed"), ("2 hour delay today", "delayed"),
         ("remote learning today", "remote"), ("will be closing at 10:00 today", "early_dismissal"))
    ),
    mark=st.sampled_from((" ", ": ", " - ")),
    heading=st.sampled_from(("", "Update: ", "Marion County: ")),
)  # fmt: skip
def test_a_name_before_its_levels_decides_whose_status_it_is(
    name: str, levels: str, status: tuple[str, str], mark: str, heading: str
) -> None:
    # Invariant: the same levels read the school's own status with a name before them, and
    # part of the district's with none (a heading's word before a mark is no name).
    words, kind = status
    named = parse_status(f"{heading}{name} {levels} School{mark}{words}", posted_at=MORNING, tz=TZ)
    assert named.kind == kind, (name, levels, words)
    assert "partial_program" not in named.notes
    unnamed = parse_status(f"{heading}{levels} School{mark}{words}", posted_at=MORNING, tz=TZ)
    assert unnamed.kind == "other", (levels, words)
    assert "partial_program" in unnamed.notes


def test_besides_that_opens_a_later_sentence_leaves_nothing_out() -> None:
    # "Besides" opening a sentence of its own is no exception to the status before it.
    result = parse_status(
        "Closed today. Besides the snow, roads are icy.", posted_at=MORNING, tz=TZ
    )
    assert result.kind == "closed"
    assert "partial_program" not in result.notes
    first = parse_status("Besides Lincoln Elementary, all schools closed", posted_at=MORNING, tz=TZ)
    assert first.kind == "other"
    assert "partial_program" in first.notes


@pytest.mark.parametrize(
    "text",
    [
        "Community ed classes cancelled", "Driver's ed classes cancelled",
        "ECFE classes cancelled", "ESL classes cancelled", "GED classes cancelled",
        "Dance classes cancelled", "Religious ed classes cancelled", "CCD classes cancelled",
    ],
)  # fmt: skip
def test_a_program_s_own_classes_cancelled_is_no_closure(text: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other"


# Secondary schools and a private school's upper or lower school are part of the district, for
# every kind of status; a band of every grade or a list of every level is all of it.
DIVISIONS = [
    "Upper school closed; lower school open", "Secondary schools closed",
    "Secondary school closed", "Secondary schools: 2 hour delay", "Upper School: closed",
    "Lower school closed", "Closed for upper school", "Lower School: 2 hour delay",
    "Closed; lower school open", "Closed; upper school open", "2 hour delay; lower school open",
    "Secondary schools: remote learning today",
]  # fmt: skip
EVERY_GRADE = [
    "Closed for students in grades K-12", "Closed for PreK-12",
    "Closed for K-12 students and staff",
    "Closed for all elementary, middle and high schools",
    "All elementary, middle and high schools are closed", "K-12 closed",
]  # fmt: skip


@pytest.mark.parametrize("text", DIVISIONS)
def test_a_division_or_secondary_schools_are_part_of_the_district(text: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other", text
    assert "partial_program" in result.notes, text


@pytest.mark.parametrize("text", EVERY_GRADE)
def test_every_grade_or_every_level_is_the_whole_district(text: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "closed", text
    assert result.dates == jan(20), text
    assert "partial_program" not in result.notes, text


_LEVEL_NOUNS = ("Elementary", "Middle school", "High school", "Secondary schools", "Upper school",
                "Lower school", "Secondary", "Junior high")  # fmt: skip


@settings(max_examples=300, deadline=None)
@given(
    first=st.sampled_from(("", *_LEVEL_NOUNS)),
    status=st.sampled_from(("closed", "2 hour delay", "remote learning", "early dismissal at 1")),
    other=st.sampled_from(_LEVEL_NOUNS),
    mark=st.sampled_from(("; ", ". ", " - ", ", ")),
    opened=st.sampled_from(("open", "is open", "on a regular schedule", "open as usual")),
)  # fmt: skip
def test_a_level_open_beside_a_status_leaves_no_district_status(
    first: str, status: str, other: str, mark: str, opened: str
) -> None:
    # Invariant: "<level A> <status>; <level B> open" (or "<status>; <level B> open") never
    # leaves a status of the whole district at 0.7 or more.
    head = f"{first} {status}" if first else status.capitalize()
    text = f"{head}{mark}{other} {opened}"
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other" or result.confidence < 0.7, (text, result)


@pytest.mark.parametrize(
    "text",
    [
        "Early dismissal Thursday at 11 a.m. for Lower schools and 11:20 a.m. for Upper Schools",
        "Early dismissal Thursday at 11 a.m. for elementary schools and 11:20 for middle schools",
    ],
)
def test_times_given_by_level_give_the_district_none(text: str) -> None:
    # Each level leaves at its own time: no one time is the district's.
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.dismissal_time is None, text


@pytest.mark.parametrize(
    "text",
    [
        "Kindergarten Center: Closed", "Kindergarten Center - closed", "Kindergarten Center closed",
        "Kindergarten Center, closed", "Kindergarten Center - Wed. & Thurs. - closed",
        "Early Childhood Center - closed", "Early Childhood Center - Wednesday - closed",
    ],
)  # fmt: skip
def test_a_program_center_with_no_name_is_part_of_the_district_after_any_mark(text: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other", text
    assert "partial_program" in result.notes, text
    named = parse_status(f"Lincoln {text}", posted_at=MORNING, tz=TZ)
    assert named.kind == "closed", text


# An adverb between a status and its grades leaves them its grades: "Closed only grades 6-12",
# "Remote learning again for K-8", "Closed anymore grades 6-12" are part of the district, as
# "Closed for grades 6-12" is.
@settings(max_examples=300, deadline=None)
@given(
    status=st.sampled_from(("Closed", "2 hour delay", "Remote learning", "Early dismissal",
                            "Remote learning day")),
    adverb=st.sampled_from(("only", "again", "now", "also", "still", "anymore")),
    lead=st.sampled_from(("", "for ", "in ")),
    band=st.sampled_from(("grades K-5", "grades 6-12", "K-8", "PK-8", "9th through 12th grade")),
)  # fmt: skip
def test_an_adverb_before_the_grades_leaves_them_the_status_s(
    status: str, adverb: str, lead: str, band: str
) -> None:
    assume(lead or "grade" in band)  # (a bare band with no "for" or "in" is no grade's)
    text = f"{status} {adverb} {lead}{band}"
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other", text
    assert "partial_program" in result.notes, text


# A label before a day alone in its clause labels the status after the day: "Preschool -
# Wednesday - closed" is the preschool's, as "Preschool - closed" is; a school's name keeps
# its status ("Lincoln Elementary - Wednesday - closed").
@settings(max_examples=300, deadline=None)
@given(
    label=st.sampled_from(("Preschool", "Kindergarten", "Kindergarten Center", "AM Kindergarten",
                           "Early Childhood Center", "Head Start", "Pre-K")),
    day=st.sampled_from(("Wednesday", "Wed.", "Wed. & Thurs.", "Jan. 21", "1/21", "tomorrow")),
    mark=st.sampled_from((" - ", " \u2013 ", ", ")),
    status=st.sampled_from(("closed", "2 hour delay", "no school", "cancelled")),
)  # fmt: skip
def test_a_program_label_before_a_day_labels_the_status_after_it(
    label: str, day: str, mark: str, status: str
) -> None:
    text = f"{label}{mark}{day}{mark}{status}"
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other", text
    assert "partial_program" in result.notes, text


@settings(max_examples=200, deadline=None)
@given(
    label=st.sampled_from(("Lincoln Elementary", "Oak Grove Schools", "School and all activities",
                           "All schools")),
    day=st.sampled_from(("Wednesday", "Wed.", "Jan. 21", "1/21", "tomorrow")),
    mark=st.sampled_from((" - ", " \u2013 ")),
    status=st.sampled_from(("closed", "cancelled")),
)  # fmt: skip
def test_a_school_label_before_a_day_keeps_the_status_after_it(
    label: str, day: str, mark: str, status: str
) -> None:
    text = f"{label}{mark}{day}{mark}{status}"
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "closed", text
    assert result.confidence >= 0.9, text


# A level abbreviated, as listings write it, is a level as its full name is: part of the
# district alone or beside another level open, the school's own after a name of its own.
# ("HS" is also Head Start: part of the program either way.)
ABBREVIATED = {
    "HS": "High School", "ES": "Elementary", "MS": "Middle School", "Elem": "Elementary",
    "Elem.": "Elementary", "JH": "Junior High", "JHS": "Junior High School",
    "SHS": "Senior High School", "MS/HS": "Middle/High School",
}  # fmt: skip
ABBREVIATED_PARTS = [
    "HS closed; ES open", "Elem closed; MS & HS open", "HS closed", "ES closed", "MS/HS closed",
    "JH closed", "JHS closed", "SHS closed", "Elem. closed", "ES: 2 hour delay",
    "ES - 2 hour delay", "MS/HS: remote learning", "HS remote learning day",
    "Elem. Closing 11:40AM Mod. Kindergarden", "All HS centers closed tomorrow",
    "Closed for HS students", "2 hour delay for MS and HS", "Jr/Sr closed",
    # The full names these read as.
    "Closed; Middle/High School open", "Closed for Senior High School",
]  # fmt: skip
ABBREVIATED_NAMED = [
    ("Kubaze HS: closed", "closed"), ("Lomira Elem. closed", "closed"),
    ("Tavimo MS/HS: 2 hour delay", "delayed"), ("Zorafa Academy MS closed", "closed"),
]  # fmt: skip


@pytest.mark.parametrize("text", ABBREVIATED_PARTS)
def test_an_abbreviated_level_is_part_of_the_district(text: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other", text
    assert "partial_program" in result.notes, text


@pytest.mark.parametrize(("text", "kind"), ABBREVIATED_NAMED)
def test_a_named_school_s_abbreviated_level_keeps_its_status(text: str, kind: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == kind
    assert result.dates == jan(20)
    assert "partial_program" not in result.notes


@settings(max_examples=400, deadline=None)
@given(
    short=st.sampled_from(sorted(ABBREVIATED)),
    other=st.sampled_from(sorted(ABBREVIATED)),
    status=st.sampled_from(
        ("closed", "2 hour delay", "remote learning", "early dismissal at 1:00", "closed today")
    ),
    form=st.sampled_from(
        ("{a} {s}", "{a}: {s}", "{a} - {s}", "{S} for {a}", "{S}; {b} open", "{a} {s}; {b} open",
         "{a}: {s}. {b}: open.", "Kubaze {a}: {s}", "Update: {a} {s}")
    ),
)  # fmt: skip
def test_an_abbreviated_level_reads_as_its_full_name(
    short: str, other: str, status: str, form: str
) -> None:
    # Invariant: a level abbreviated reads as the level spelled out, in every form, so a
    # status for one level never reads as the district's when its full name would not.
    def text(a: str, b: str) -> str:
        return form.format(a=a, b=b, s=status, S=status.capitalize())

    spelled = text(ABBREVIATED[short], ABBREVIATED[other])
    full = parse_status(spelled, posted_at=MORNING, tz=TZ)
    result = parse_status(text(short, other), posted_at=MORNING, tz=TZ)
    assert (result.kind, result.dates, "partial_program" in result.notes) == (
        full.kind,
        full.dates,
        "partial_program" in full.notes,
    ), (text(short, other), spelled)
