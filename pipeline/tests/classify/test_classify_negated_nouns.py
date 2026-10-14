"""A "no" before a noun phrase: "no school" closes, "no school closures" says nothing does.

Every text here is a phrasing pattern written for these tests, not a claim
about a real school. Unless a row says otherwise it is posted at 5:30 a.m. on
Tuesday 20 January 2026 in New York, so "today" is Tuesday the 20th and
"tomorrow" Wednesday the 21st.

"No school" is a closure only when no noun follows it: the phrase ends there,
at a day ("no school today"), at a word such as "for" or "due", or at a word
for weather or a status ("no school snow day"). When a noun for a status or
for news about one follows ("no school closures", "no school closings", "no
school delays", "no school cancellations", "no school changes") the "no" is
about that noun: the listing states that nothing happens, so it is ``other``
(at 0.9, with the note ``negated``), never ``closed``. So is a school noun that
is the subject of a status verb ("no schools are closed", "no school has
announced a closure"). A noun that leaves the phrase unclear ("no school
pictures", "no school/closings", "no school has announced plans") gives
``other`` at 0.3 with the note ``ambiguous``.

"No school" said with "not" is a closure too ("there will not be school
tomorrow", "we do not have classes today"), and the same nouns after it negate
("there will not be school closures"). A status followed by "not" and a word
that denies it ("closure not expected", "a delay is not planned") is negated; one
followed by a word that leaves it open ("closure unlikely", "delay not yet
decided", "closure not ruled out") is hedged, ``other`` at 0.3.

A status in a clause about making up a lost day ("snow day make-up day", "the
snow day will be made up on March 2") states nothing about the day it names:
``other`` at 0.3. Nor does a report of a past status on a weekday ("school was
closed Friday" could be any Friday), and a past status beside one that stands is
no status for a day of its own ("We were closed Monday. Closed again today.").

The same rows check lengths of time written in parts: "two-and-a-half hour
delay", "2 hour, 30 minute delay", "two hour and thirty minute delay".
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from snowlight.classify import parse_status
from snowlight.classify.text import duration_minutes

TZ = "America/New_York"
ZONE = ZoneInfo(TZ)
MORNING = datetime(2026, 1, 20, 5, 30, tzinfo=ZONE)  # Tuesday
EVENING = datetime(2026, 1, 20, 20, 0, tzinfo=ZONE)
FRI_EVENING = datetime(2026, 1, 23, 19, 0, tzinfo=ZONE)


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
    delay: int | None = None,
    early: int | None = None,
) -> object:
    label = f"{text} @ {posted:%a %H:%M}"
    return pytest.param(Row(text, posted, kind, dates, confidence, notes, delay, early), id=label)


def negated(text: str, *, posted: datetime = MORNING) -> object:
    """A listing that says no status happens: other at 0.9, noted as negated."""
    return row(text, posted=posted, notes=("negated",))


def unclear(text: str, *, posted: datetime = MORNING) -> object:
    """A listing whose words could be read two ways: other at 0.3, noted as ambiguous."""
    return row(text, posted=posted, confidence=0.3, notes=("ambiguous",))


def check(case: Row) -> None:
    result = parse_status(case.text, posted_at=case.posted, tz=TZ)
    assert result.kind == case.kind
    assert result.dates == case.dates
    assert result.confidence == case.confidence
    assert set(case.notes) <= set(result.notes)
    if case.kind == "other":
        assert result.schedule == ()
    assert result.delay_minutes == case.delay
    assert result.dismissal_early_minutes == case.early


# "No school" and then a noun for a status: the "no" is about that noun.
STATUS_NOUNS = [
    negated("There is no school closure today"),
    negated("No school closure today"),
    negated("No school closure"),
    negated("No school closures"),
    negated("NO SCHOOL CLOSURES TODAY"),
    negated("No school closures tomorrow", posted=EVENING),
    negated("No school closing today"),
    negated("No school closings today"),
    negated("No School Closings"),
    negated("No school closings."),
    negated("NO SCHOOL CLOSINGS AT THIS TIME."),
    negated("There are no school closings"),
    negated("There are no school closings at this time"),
    negated("Currently, there are no school closings."),
    negated("Update: no school closings today"),
    negated("No school closings reported"),
    negated("No school delay today"),
    negated("No school delays"),
    negated("No school delays today"),
    negated("No school delays tomorrow", posted=EVENING),
    negated("No school cancellation today"),
    negated("No school cancellations"),
    negated("No school cancellations today"),
    negated("No school cancelations today"),
    negated("No school changes"),
    negated("No school changes today"),
    negated("No school changes Monday", posted=FRI_EVENING),
    negated("No school schedule changes"),
    negated("No school status changes"),
    negated("No school shutdown"),
    negated("No school shutdowns today"),
    negated("No school late starts"),
    negated("No school early dismissals"),
    negated("No school early releases today"),
    negated("No school dismissal changes"),
    negated("No school openings delayed"),
    negated("No school closing notices"),
]

# "No school" and then a noun for news about the schools: nothing happens either.
NEWS_NOUNS = [
    negated("No school updates at this time"),
    negated("No school announcements today"),
    negated("No school alerts"),
    negated("No school news today"),
    negated("No school disruptions"),
    negated("No school impacts"),
    negated("No school adjustments today"),
    negated("No school schedule modifications"),
]

# Several nouns in a list, a noun that joins "school" to another, a hyphen or a slash.
LISTS_AND_JOINS = [
    negated("No school closures or delays"),
    negated("No school closings or delays today"),
    negated("There are currently no school closings or delays"),
    negated("At this time there are no school delays or closings"),
    negated("No school closings, delays or cancellations"),
    negated("No school closings & delays"),
    negated("No school closings/delays"),
    negated("No school closings/cancellations today"),
    negated("No school-related closings"),
    negated("No school-closings today"),
    negated("No school or district closings"),
    negated("No school or district weather-related closings"),
    negated("No school or district closings or delays"),
    negated("No school district weather related closures"),
    negated("No school or after-school activity cancellations"),
    negated("No school, district or county closings"),
    negated("No school, district, county or area closings"),
    negated("No school or bus delays"),
    negated("No school district closures"),
    negated("No school district closings today"),
    negated("No weather-related school closings"),
    negated("No weather closings today"),
    negated("No snow closings today"),
    negated("No closure"),
    negated("No closings"),
    negated("No closings or delays today"),
    negated("No closings for schools today"),
    negated("School: no closures today"),
    negated("Schools: no closings or delays"),
    negated("Our school has no closures today"),
]

# A school noun as the subject of a status verb, or of a verb that reports a status.
SUBJECTS = [
    negated("No schools are closed"),
    negated("No schools closed today"),
    negated("No schools closing today"),
    negated("No schools will close today"),
    negated("No school will close today"),
    negated("No school will be closed today"),
    negated("No school is closing today"),
    negated("No school is delayed today"),
    negated("No school is being delayed"),
    negated("No school is currently closed"),
    negated("No schools affected"),
    negated("No school affected"),
    negated("No schools have announced closures"),
    negated("No school has announced a closure"),
    negated("No schools have reported any closings"),
    negated("No school has reported a delay"),
    negated("No district has announced closures"),
    negated("No school has any closures today"),
    negated("No school has closings today"),
    negated("No school at this time has announced closures"),
]

# "No" before a noun for buses, offices, staff or activities and a status word after it:
# nothing happens to them, and nothing is said of the school.
OTHER_NOUNS = [
    negated("No buses delayed"),
    negated("No school buses delayed"),
    negated("No school buses delayed today"),
    negated("No offices closed"),
    negated("No staff delayed"),
    negated("No activities cancelled"),
    negated("No after-school activities cancelled"),
    negated("No buses cancelled"),
    row("No activities cancelled today; school closed", "closed", jan(20), notes=("negated",)),
    row("No after-school activities", notes=("activities_cancelled",)),
    row("No bus service", notes=("transportation",)),
]

# A list that ends before a status noun, or a restatement after a comma: a closure.
LISTS_THAT_CLOSE = [
    row("No school or activities today", "closed", jan(20), confidence=0.95),
    row("No school or activities, closure due to snow", "closed", jan(20)),
    row("No school, closure due to snow", "closed", jan(20)),
    row("No school, snow day", "closed", jan(20)),
    row("No school, offices open", "closed", jan(20)),
    row("No school, all activities cancelled", "closed", jan(20),
        notes=("activities_cancelled",)),
    row("No school and no activities", "closed", jan(20), notes=("activities_cancelled",)),
    row("No school and county offices closed", "closed", jan(20), notes=("offices_closed",)),
]  # fmt: skip

# "No school" beside a status another "no" denies, with no day named: two answers of no
# ("no school closing, no delay") as much as a closure. Unclear. With a day, a closure.
PARALLEL_NO = [
    row("No school, no delays", confidence=0.3, notes=("ambiguous", "negated")),
    row("No school - no delay", confidence=0.3, notes=("ambiguous", "negated")),
    row("No school; no delay", confidence=0.3, notes=("ambiguous", "negated")),
    row("No delay - no school", confidence=0.3, notes=("ambiguous", "negated")),
    row("No school - no early dismissal", confidence=0.3, notes=("ambiguous", "negated")),
    row("No school today - no delay tomorrow", "closed", jan(20), confidence=0.95,
        notes=("negated",)),
    row("No school, no after-school activities", "closed", jan(20),
        notes=("activities_cancelled",)),
]  # fmt: skip

# A name before or after the phrase changes nothing.
NAMED = [
    negated("Lincoln Elementary: no school closings today"),
    negated("No school closings - Lincoln Elementary"),
    negated("Maple Grove Middle School - no school delays"),
    negated("No school changes (Oak Ridge Academy)"),
]

# Part of the program, a session noun, or a status answered no.
OTHER_FORMS = [
    row("No school 3rd grade", notes=("partial_program",)),
    row("No school for 3rd grade", notes=("partial_program",)),
    row("No school AM kindergarten", notes=("partial_program",)),
    negated("No session changes today"),
    negated("No school weather/closings"),
    negated("No school snow/closings"),
    negated("Closed: No"),
    negated("Closing: no"),
    negated("2 hour delay - none"),
    negated("Delayed: N/A"),
]

# Words that could be read two ways: other at 0.3.
UNCLEAR = [
    unclear("No school closed"),
    unclear("No school pictures today"),
    unclear("No school offices open"),
    unclear("No school/closings today"),
    unclear("No school/delays"),
    unclear("No school has announced plans"),
    unclear("No in-person classes today"),
    unclear("No school AM/PM"),
    unclear("No school or county area local public private charter closings"),
]

# "No school" with nothing after it, or only a day, a cause, a filler word or a word for
# weather or a status: a closure.
CLOSURES = [
    row("No school", "closed", jan(20)),
    row("No School Today", "closed", jan(20), confidence=0.95),
    row("No school tomorrow", "closed", jan(21), confidence=0.95),
    row("No school tomorrow", "closed", jan(21), posted=EVENING, confidence=0.95),
    row("No school Monday", "closed", jan(26), posted=FRI_EVENING, confidence=0.95),
    row("No school on Friday", "closed", jan(23), confidence=0.95),
    row("No school today or tomorrow", "closed", jan(20, 21), confidence=0.95),
    row("NO SCHOOL - SNOW DAY", "closed", jan(20)),
    row("NO SCHOOL-SNOW DAY", "closed", jan(20)),
    row("No school snow day", "closed", jan(20)),
    row("No school today due to snow", "closed", jan(20), confidence=0.95),
    row("No school due to icy roads", "closed", jan(20)),
    row("No school due to power outage", "closed", jan(20)),
    row("No school: winter storm", "closed", jan(20)),
    row("No school for students", "closed", jan(20)),
    row("No school, offices open", "closed", jan(20)),
    row("No school or activities today", "closed", jan(20), confidence=0.95),
    row("No school staff development day", "closed", jan(20)),
    row("No school districtwide", "closed", jan(20)),
    row("No school K-12", "closed", jan(20)),
    row("No school again tomorrow", "closed", jan(21), confidence=0.95),
    row("No school will be held tomorrow", "closed", jan(21), confidence=0.95),
    row("There will be no school tomorrow", "closed", jan(21), confidence=0.95),
    row("There is no school today", "closed", jan(20), confidence=0.95),
    row("No school is in session today", "closed", jan(20), confidence=0.95),
    row("No school is scheduled Thursday", "closed", jan(22), confidence=0.95),
    row("No school/closed", "closed", jan(20)),
    row("No School/Closed Today", "closed", jan(20), confidence=0.95),
    row("No school (closed)", "closed", jan(20)),
    row("No classes today", "closed", jan(20), confidence=0.95),
    row("No classes held today", "closed", jan(20), confidence=0.95),
    row("No school district today", "closed", jan(20), confidence=0.95),
    row("No session today", "closed", jan(20), confidence=0.95),
    row("No school today/tomorrow", "closed", jan(20, 21), confidence=0.95),
    row("No school Tues/Wed", "closed", jan(20, 21), confidence=0.95),
    row("No classes Thurs/Fri", "closed", jan(22, 23), confidence=0.95),
    row("No school 1/22", "closed", jan(22), confidence=0.95),
    row("No school snow/ice", "closed", jan(20)),
]

# A negated noun beside a status that stands: the status keeps its day.
BESIDE_A_STATUS = [
    row("No school closings; 2 hour delay today", "delayed", jan(20), confidence=0.95,
        notes=("negated",), delay=120),
    row("No school closures - 2 hour delay", "delayed", jan(20), notes=("negated",), delay=120),
    row("No school closings but a 2 hour delay today", "delayed", jan(20), confidence=0.95,
        notes=("negated",), delay=120),
    row("No school closure, 2 hour delay", "delayed", jan(20), notes=("negated",), delay=120),
    row("Closed today. No school closures tomorrow.", "closed", jan(20), confidence=0.95,
        notes=("negated",)),
    row("No school today. No school closings tomorrow.", "closed", jan(20), confidence=0.95,
        notes=("negated",)),
    row("No school delays today; closed", "closed", jan(20), notes=("negated",)),
    row("No school changes today; NTI day tomorrow", "remote", jan(21), confidence=0.95,
        notes=("negated",)),
]  # fmt: skip

# "No school" said with "not": a closure, and the same nouns after it negate.
SAID_WITH_NOT = [
    row("There will not be school tomorrow", "closed", jan(21), confidence=0.95),
    row("There will not be school tomorrow", "closed", jan(21), posted=EVENING, confidence=0.95),
    row("There won't be school tomorrow", "closed", jan(21), confidence=0.95),
    row("There will not be any school tomorrow", "closed", jan(21), confidence=0.95),
    row("There is not school today", "closed", jan(20), confidence=0.95),
    row("We won't have school tomorrow", "closed", jan(21), confidence=0.95),
    row("We do not have school today", "closed", jan(20), confidence=0.95),
    row("We are not having school tomorrow", "closed", jan(21), confidence=0.95),
    row("We will not have classes Thursday", "closed", jan(22), confidence=0.95),
    row("Students will not have school tomorrow", "closed", jan(21), confidence=0.95),
    row("We're not having school tomorrow", "closed", jan(21), confidence=0.95),
    row("There's not school today", "closed", jan(20), confidence=0.95),
    negated("We're not having school closures"),
    row("We will not have school or activities tomorrow", "closed", jan(21), confidence=0.95),
    negated("There will not be school closures"),
    negated("There are not any school closings"),
    negated("We do not have school delays today"),
    negated("We will not have a 2 hour delay"),
    negated("There will not be a delay"),
    negated("We will not be closing"),
    row("We will not have AM kindergarten", notes=("partial_program",)),
    row("We will not have school buses", notes=("transportation",)),
    row("If we do not have school tomorrow, NTI day", confidence=0.3, notes=("hedged",)),
]

# A status and then "not" with a word that denies it, or a word that leaves it open.
DENIED_OR_OPEN = [
    negated("Closure not expected"),
    negated("Closure is not expected tomorrow"),
    negated("Closure is not currently expected"),
    negated("Closure not anticipated"),
    negated("Closure not likely"),
    negated("Delay not planned"),
    negated("A closure is not planned"),
    negated("A delay is not expected"),
    negated("Delay isn't expected"),
    negated("NTI day not scheduled"),
    negated("Early dismissal is not planned today"),
    row("Closure unlikely", confidence=0.3, notes=("hedged",)),
    row("Delay unlikely tomorrow", confidence=0.3, notes=("hedged",)),
    row("Closing is unlikely", confidence=0.3, notes=("hedged",)),
    row("Closure doubtful", confidence=0.3, notes=("hedged",)),
    row("Closure improbable", confidence=0.3, notes=("hedged",)),
    row("Closure not ruled out", confidence=0.3, notes=("hedged",)),
    row("Delay not yet decided", confidence=0.3, notes=("hedged",)),
    row("Early dismissal not confirmed", confidence=0.3, notes=("hedged",)),
    row("Delayed opening not expected to change", confidence=0.3, notes=("hedged",)),
    row("Closure not expected to happen", confidence=0.3, notes=("hedged",)),
    row("Closed not delayed", "closed", jan(20), notes=("negated",)),
    row("2 hour delay, not closed", "delayed", jan(20), notes=("negated",), delay=120),
    row("Closed today, not expected to reopen until Monday", "closed", jan(20),
        confidence=0.95),
]  # fmt: skip

# A date between the status and the words after it, with or without a preposition: the
# words still reach the status.
DATE_BETWEEN = [
    row("Closing for Jan. 22 possible", confidence=0.3, notes=("hedged",)),
    row("Delay on Friday possible", confidence=0.3, notes=("hedged",)),
    row("Closure on Friday unlikely", confidence=0.3, notes=("hedged",)),
    row("Closure Friday unlikely", confidence=0.3, notes=("hedged",)),
    negated("Closure for Jan. 22 not expected"),
    negated("Closure for Friday is not expected"),
    row("Closed on Friday for staff", notes=("staff",)),
    row("Closed for Friday for staff", notes=("staff",)),
    row("Closed Friday for staff", notes=("staff",)),
    row("Closed on Friday for students", "closed", jan(23), confidence=0.95),
    row("Cancelled on Friday for all classes", "closed", jan(23), confidence=0.95),
    row("Closed for possible flooding", "closed", jan(20)),
    row("Closed for Friday due to snow", "closed", jan(23), confidence=0.95),
]

# A status in a clause about making up a lost day names no status of the day it names.
MAKE_UP_DAYS = [
    unclear("Snow day make-up day"),
    unclear("Make-up day for snow day"),
    unclear("Snow day makeup: Feb 16"),
    unclear("Feb 16 will be a make-up day for the snow day"),
    unclear("Students will make up the snow day on Feb 16"),
    unclear("Snow day to be made up Friday"),
    unclear("The snow day will be made up on March 2"),
    unclear("Students will not have to make up the snow day"),
    unclear("NTI day will be made up on Feb 16"),
    row("Closed today. Snow day will be made up Feb 16.", "closed", jan(20), confidence=0.8,
        notes=("ambiguous",)),
    row("Closed today; make-up day is Feb 16", "closed", jan(20), confidence=0.95),
    row("Closed today, will be made up on Feb 16", "closed", jan(20), confidence=0.95),
    row("Closed today - make up day TBD", "closed", jan(20), confidence=0.95),
]  # fmt: skip

# A report of a past status: a weekday name could be any week, so it names no day; a
# relative day or a date still does. Beside a status that stands, a past one on a day of
# its own is no status for that day.
PAST_REPORTS = [
    row("We were closed Monday", confidence=0.3, notes=("unreadable_date",)),
    row("School was closed Friday", confidence=0.3, notes=("unreadable_date",)),
    row("Schools were closed Monday and Tuesday", confidence=0.3, notes=("unreadable_date",)),
    row("School was closed all week", confidence=0.3, notes=("unreadable_date",)),
    row("Schools were closed Monday due to snow and will reopen Wednesday", confidence=0.3,
        notes=("unreadable_date",)),
    row("School was closed", confidence=0.3, notes=("undated",)),
    row("School was closed yesterday", "closed", jan(19), confidence=0.95),
    row("Was closed today", "closed", jan(20), posted=EVENING, confidence=0.95),
    row("School was delayed this morning", "delayed", jan(20)),
    row("School was closed Friday, Jan. 16", "closed", jan(16), confidence=0.95),
    row("We were closed Monday. Closed again today.", "closed", jan(20), confidence=0.95,
        notes=("superseded",)),
    row("School was closed yesterday. Closed again today.", "closed", jan(20),
        confidence=0.95, notes=("superseded",)),
    row("Previously 2 hour delay Wednesday. Update: closed Thursday", "closed", jan(22),
        confidence=0.95, notes=("superseded",)),
    row("Closed tomorrow (was a 2 hour delay)", "closed", jan(21), confidence=0.8,
        notes=("superseded",)),
]  # fmt: skip

# Lengths of time written in parts.
LENGTHS = [
    row("Two-and-a-half hour delay", "delayed", jan(20), delay=150),
    row("two and one-half hour delay", "delayed", jan(20), delay=150),
    row("two-and-one-half-hour delay", "delayed", jan(20), delay=150),
    row("Two and a half hour delay", "delayed", jan(20), delay=150),
    row("2 and a half hour delay", "delayed", jan(20), delay=150),
    row("2 1/2 hour delay", "delayed", jan(20), delay=150),
    row("2.5 hour delay", "delayed", jan(20), delay=150),
    row("One-and-a-half-hour delay", "delayed", jan(20), delay=90),
    row("one and a half hour delay", "delayed", jan(20), delay=90),
    row("an hour and a half delay", "delayed", jan(20), delay=90),
    row("three and a half hour delay", "delayed", jan(20), delay=210),
    row("two hour and thirty minute delay", "delayed", jan(20), delay=150),
    row("two hours and thirty minutes delay", "delayed", jan(20), delay=150),
    row("two hour thirty minute delay", "delayed", jan(20), delay=150),
    row("1 hour 30 minute delay", "delayed", jan(20), delay=90),
    row("1 hr 30 min delay", "delayed", jan(20), delay=90),
    row("2 hour, 30 minute delay", "delayed", jan(20), delay=150),
    row("Two hour, thirty minute delay", "delayed", jan(20), delay=150),
    row("Delayed 2 hours, 30 minutes", "delayed", jan(20), delay=150),
    row("Delayed two and a half hours", "delayed", jan(20), delay=150),
    row("Delay of two-and-a-half hours", "delayed", jan(20), delay=150),
    row("Opening two and a half hours late", "delayed", jan(20), delay=150),
    row("Dismissing two and a half hours early", "early_dismissal", jan(20), early=150),
    row("Two-and-a-half hour early dismissal", "early_dismissal", jan(20), early=150),
    row("Dismissing 1 hour, 30 minutes early", "early_dismissal", jan(20), early=90),
    # Two lengths run together state no one length: the delay stands without one.
    row("2 hour, 90 minute delay", "delayed", jan(20), confidence=0.8),
    row("1 hour 90 minute delay", "delayed", jan(20), confidence=0.8),
]


@pytest.mark.parametrize("case", STATUS_NOUNS)
def test_no_school_before_a_status_noun_is_negated(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", NEWS_NOUNS)
def test_no_school_before_a_news_noun_is_negated(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", LISTS_AND_JOINS)
def test_negated_nouns_in_lists_and_joined_words(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", SUBJECTS)
def test_a_school_noun_as_the_subject_of_a_status_is_negated(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", OTHER_NOUNS)
def test_no_before_another_noun_and_a_status_word_is_negated(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", LISTS_THAT_CLOSE)
def test_a_list_that_ends_before_a_status_noun_is_a_closure(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", PARALLEL_NO)
def test_no_school_beside_another_no_is_unclear(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", NAMED)
def test_a_name_beside_a_negated_noun_changes_nothing(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", OTHER_FORMS)
def test_part_of_the_program_and_answers(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", UNCLEAR)
def test_a_phrase_that_reads_two_ways_is_ambiguous(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", CLOSURES)
def test_no_school_with_no_noun_after_it_is_a_closure(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", BESIDE_A_STATUS)
def test_a_negated_noun_leaves_the_status_beside_it(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", SAID_WITH_NOT)
def test_no_school_said_with_not(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", DENIED_OR_OPEN)
def test_not_after_a_status_denies_it_or_leaves_it_open(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", DATE_BETWEEN)
def test_a_date_between_a_status_and_its_words(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", MAKE_UP_DAYS)
def test_a_day_to_be_made_up_is_no_status(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", PAST_REPORTS)
def test_a_past_report_names_no_day_ahead(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", LENGTHS)
def test_lengths_written_in_parts(case: Row) -> None:
    check(case)


@pytest.mark.parametrize(
    ("text", "minutes"),
    [
        ("2 hour, 30 minute", 150),
        ("2 hours, 30 minutes", 150),
        ("1 hour, 15 min", 75),
        ("two-and-a-half hour", 150),
        ("two and one-half hour", 150),
        ("2 hour, 90 minute", None),
        ("1 hour 60 minutes", None),
    ],
)
def test_duration_in_parts(text: str, minutes: int | None) -> None:
    assert duration_minutes(text) == minutes


# Properties ------------------------------------------------------------------------------

ZONES = ("America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles")
instants = st.datetimes(
    min_value=datetime(2021, 1, 1),
    max_value=datetime(2031, 12, 31),
    timezones=st.sampled_from([ZoneInfo(name) for name in ZONES]),
)


def just_passed(weekday: int, posted: datetime, tz: str) -> bool:
    """Whether a weekday name alone was a day or two before the posting day (worked out here).

    Its next occurrence (counting the posting day, or the day before it for a post
    between midnight and 4 a.m.) is then 5 or 6 days on, and the parser states no day:
    the listing is most likely still up after its day.
    """
    local = posted.astimezone(ZoneInfo(tz))
    first = local.date() - timedelta(days=1 if local.hour < 4 else 0)
    ahead = first + timedelta(days=(weekday - first.weekday()) % 7)
    return (ahead - local.date()).days >= 5


# The weekday names the properties below draw, by their number.
NAMED_WEEKDAYS = {"Monday": 0, "Friday": 4, "on Thursday": 3}
LEADS = (
    "", "There is ", "There are ", "There are currently ", "Currently there are ",
    "At this time there are ", "Update: ", "Reminder - there are ",
)  # fmt: skip
SUBJECT_NOUNS = ("school", "schools", "School District", "school district", "district")
NOUNS = (
    "closure", "closures", "closing", "closings", "delay", "delays", "cancellation",
    "cancellations", "cancelations", "change", "changes", "schedule changes", "shutdowns",
    "late starts", "early dismissals", "updates", "announcements", "closings or delays",
    "closures, delays or cancellations", "delays/closings", "weather-related closings",
    "or district closings", "or district weather-related closures", ", district or county closings",
    "buses delayed", "offices closed", "activities cancelled",
)  # fmt: skip
TAILS = (
    "", " today", " tomorrow", " Monday", " for Jan. 22", " at this time", " reported",
    " to report", " due to weather", ".", " today.",
)  # fmt: skip
NAMES = ("", "Lincoln Elementary: ", "Bakuzo Temira Middle School - ")


@settings(max_examples=600, deadline=None)
@given(
    lead=st.sampled_from(LEADS),
    subject=st.sampled_from(SUBJECT_NOUNS),
    noun=st.sampled_from(NOUNS),
    tail=st.sampled_from(TAILS),
    name=st.sampled_from(NAMES),
    upper=st.booleans(),
    posted=instants,
    tz=st.sampled_from(ZONES),
)
def test_no_school_before_a_noun_never_glows(  # noqa: PLR0913, PLR0917 - drawn parts
    lead: str,
    subject: str,
    noun: str,
    tail: str,
    name: str,
    upper: bool,
    posted: datetime,
    tz: str,
) -> None:
    text = f"{name}{lead}no {subject}{'' if noun.startswith(',') else ' '}{noun}{tail}"
    result = parse_status(text.upper() if upper else text, posted_at=posted, tz=tz)
    assert result.kind == "other"
    assert result.schedule == ()
    assert "negated" in result.notes


VERB_PHRASES = (
    "are closed", "is closed", "will close", "will be closed", "are closing", "is delayed",
    "will be delayed", "have announced closures", "has announced a closure",
    "have reported any closings", "has reported a delay", "are affected",
    "at this time have announced closures",
)  # fmt: skip


@settings(max_examples=300, deadline=None)
@given(
    subject=st.sampled_from(("school", "schools", "district", "districts")),
    verb=st.sampled_from(VERB_PHRASES),
    tail=st.sampled_from(TAILS),
    posted=instants,
    tz=st.sampled_from(ZONES),
)
def test_a_school_noun_as_a_subject_never_glows(
    subject: str, verb: str, tail: str, posted: datetime, tz: str
) -> None:
    result = parse_status(f"No {subject} {verb}{tail}", posted_at=posted, tz=tz)
    assert result.kind == "other"
    assert "negated" in result.notes


@settings(max_examples=300, deadline=None)
@given(
    subject=st.sampled_from(("school", "School", "NO SCHOOL")),
    day=st.sampled_from(("today", "tomorrow", "Monday", "Friday", "Jan. 22", "on Thursday")),
    cause=st.sampled_from(("", " due to snow", " - winter storm", " (icy roads)", ", snow day")),
    posted=instants,
    tz=st.sampled_from(ZONES),
)
def test_no_school_before_a_day_is_a_closure(
    subject: str, day: str, cause: str, posted: datetime, tz: str
) -> None:
    text = f"NO SCHOOL {day}{cause}" if subject == "NO SCHOOL" else f"No {subject} {day}{cause}"
    result = parse_status(text, posted_at=posted, tz=tz)
    assert "negated" not in result.notes
    if day in NAMED_WEEKDAYS and just_passed(NAMED_WEEKDAYS[day], posted, tz):
        # A weekday a day or two ago: the one just past or the next, neither stated.
        assert result.kind == "other"
        assert "unreadable_date" in result.notes
        return
    # A named day always states a status; a Saturday or Sunday one is only noted as such.
    assert result.kind == "closed"


DENIED_STATUSES = (
    "Closure", "A closure", "School closure", "Closing", "2 hour delay", "A delay", "Delay",
    "Late start", "Early dismissal", "Early release", "NTI day", "E-learning day", "Snow day",
)  # fmt: skip
DENIALS = (
    "not expected", "is not expected", "is not currently expected", "not anticipated",
    "is not planned", "not likely", "isn't expected", "unlikely", "is unlikely",
    "doubtful", "not yet decided", "not confirmed", "not ruled out", "is not scheduled",
)  # fmt: skip


@settings(max_examples=400, deadline=None)
@given(
    status=st.sampled_from(DENIED_STATUSES),
    denial=st.sampled_from(DENIALS),
    day=st.sampled_from(("", " today", " tomorrow", " Monday", " for Jan. 22")),
    name=st.sampled_from(NAMES),
    posted=instants,
    tz=st.sampled_from(ZONES),
)
def test_a_denied_or_unlikely_status_never_glows(  # noqa: PLR0913, PLR0917 - drawn parts
    status: str, denial: str, day: str, name: str, posted: datetime, tz: str
) -> None:
    for text in (f"{name}{status}{day} {denial}", f"{name}{status} {denial}{day}"):
        result = parse_status(text, posted_at=posted, tz=tz)
        assert result.kind == "other"
        assert result.schedule == ()


@settings(max_examples=300, deadline=None)
@given(
    subject=st.sampled_from(
        (
            "There will not be",
            "There won't be",
            "We will not have",
            "We do not have",
            "We don't have",
            "Students will not have",
            "We're not having",
        )
    ),
    noun=st.sampled_from(("school", "classes", "any school")),
    day=st.sampled_from(("today", "tomorrow", "Monday", "Friday", "on Jan. 22")),
    posted=instants,
    tz=st.sampled_from(ZONES),
)
def test_no_school_said_with_not_matches_no_school(
    subject: str, noun: str, day: str, posted: datetime, tz: str
) -> None:
    said = parse_status(f"{subject} {noun} {day}", posted_at=posted, tz=tz)
    plain = parse_status(f"No {noun.removeprefix('any ')} {day}", posted_at=posted, tz=tz)
    stale = day in NAMED_WEEKDAYS and just_passed(NAMED_WEEKDAYS[day], posted, tz)
    assert said.kind == plain.kind == ("other" if stale else "closed")
    assert said.dates == plain.dates


@settings(max_examples=300, deadline=None)
@given(
    subject=st.sampled_from(("School was", "Schools were", "We were", "The district was")),
    status=st.sampled_from(("closed", "delayed 2 hours", "dismissed early", "on a 2 hour delay")),
    day=st.sampled_from(("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "all week")),
    posted=instants,
    tz=st.sampled_from(ZONES),
)
def test_a_past_report_on_a_weekday_never_glows(
    subject: str, status: str, day: str, posted: datetime, tz: str
) -> None:
    result = parse_status(f"{subject} {status} {day}", posted_at=posted, tz=tz)
    assert result.kind == "other"
    assert result.schedule == ()


@settings(max_examples=300, deadline=None)
@given(
    hours=st.integers(min_value=1, max_value=4),
    minutes=st.sampled_from((15, 30, 45)),
    form=st.sampled_from(
        (
            "{h} hour, {m} minute delay",
            "{h} hour {m} minute delay",
            "{h} hours and {m} minutes delay",
            "{h} hr {m} min delay",
            "{h}-hour, {m}-minute delay",
            "Delayed {h} hours, {m} minutes",
        )
    ),
)
def test_hours_and_minutes_add_up(hours: int, minutes: int, form: str) -> None:
    text = form.format(h=hours, m=minutes)
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "delayed"
    assert result.delay_minutes == hours * 60 + minutes


@settings(max_examples=200, deadline=None)
@given(
    whole=st.sampled_from((("one", 1), ("two", 2), ("three", 3), ("1", 1), ("2", 2), ("3", 3))),
    join=st.sampled_from((" and a half", "-and-a-half", " and one-half", " and one half", " 1/2")),
    unit=st.sampled_from((" hour delay", "-hour delay", " hr delay", " hours late")),
)
def test_a_half_adds_thirty_minutes(whole: tuple[str, int], join: str, unit: str) -> None:
    word, number = whole
    if join == " 1/2" and not word.isdigit():
        join = " and a half"  # "two 1/2" is not written
    result = parse_status(f"{word}{join}{unit}", posted_at=MORNING, tz=TZ)
    assert result.kind == "delayed"
    assert result.delay_minutes == number * 60 + 30
