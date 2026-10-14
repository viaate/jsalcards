"""A status the text calls off: "2 hour delay cancelled", "Cancel delay", "Closure lifted".

Every text here is a phrasing pattern written for these tests, not a claim
about a real school. Unless a row says otherwise it is posted at 5:30 a.m. on
Tuesday 20 January 2026 in New York, so "today" is Tuesday the 20th and
"tomorrow" Wednesday the 21st.

A status that the text calls off is not in effect, so it never shows: the
listing is ``other`` (at 0.9, with the note ``revoked``), or the status that
replaces it when one is named ("Delay cancelled, now closed"). A calling-off
word is attached to a status in either order, across filler words, dates,
causes and light punctuation ("Delay: cancelled", "2 hour delay (cancelled)",
"Cancel delay", "We have cancelled tomorrow's 2 hour delay"). A "cancelled"
with a noun of its own belongs to that noun ("School cancelled" is a closure;
"2 hour delay; all activities cancelled" leaves the delay). One that could
either call a status off or restate it ("Snow day: cancelled", "Cancelled -
NTI day") is ambiguous, so the status is dropped at 0.3.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from snowlight.classify import parse_status
from snowlight.classify.mentions import find_mentions
from snowlight.classify.parse import _clauses
from snowlight.classify.revoke import pair_revocations
from snowlight.classify.text import normalize

TZ = "America/New_York"
ZONE = ZoneInfo(TZ)
MORNING = datetime(2026, 1, 20, 5, 30, tzinfo=ZONE)  # Tuesday
EVENING = datetime(2026, 1, 20, 20, 0, tzinfo=ZONE)
FRI_EVENING = datetime(2026, 1, 23, 19, 0, tzinfo=ZONE)
SUN_OVERNIGHT = datetime(2026, 1, 25, 1, 30, tzinfo=ZONE)


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
    says_open: bool | None


def row(  # noqa: PLR0913 - one table row
    text: str,
    kind: str = "other",
    dates: tuple[date, ...] = (),
    *,
    posted: datetime = MORNING,
    confidence: float = 0.9,
    notes: tuple[str, ...] = (),
    delay: int | None = None,
    says_open: bool | None = None,
) -> object:
    label = f"{text} @ {posted:%a %H:%M}"
    return pytest.param(
        Row(text, posted, kind, dates, confidence, notes, delay, says_open), id=label
    )


def called_off(text: str, *, posted: datetime = MORNING, says_open: bool | None = None) -> object:
    """A status called off, with nothing in its place."""
    return row(text, posted=posted, notes=("revoked",), says_open=says_open)


def check(case: Row) -> None:
    result = parse_status(case.text, posted_at=case.posted, tz=TZ)
    assert result.kind == case.kind
    assert result.dates == case.dates
    assert result.confidence == case.confidence
    assert set(case.notes) <= set(result.notes)
    if case.kind == "other":
        assert result.schedule == ()
    if case.delay is not None:
        assert result.delay_minutes == case.delay
    if case.says_open is not None:
        assert result.says_open is case.says_open


# The calling-off word after the status: "2 hour delay cancelled".
AFTER_THE_STATUS = [
    called_off("2 hour delay cancelled"),
    called_off("2 hour delay canceled"),
    called_off("2-hour delay CANCELLED"),
    called_off("2 hr delay cancelled"),
    called_off("Two hour delay has been cancelled"),
    called_off("90 minute delay cancelled"),
    called_off("Delay cancelled"),
    called_off("Delay canceled - school open on time", says_open=True),
    called_off("Delay: cancelled"),
    called_off("Delay - cancelled"),
    called_off("2 hour delay (cancelled)"),
    called_off("2 hour delay [cancelled]"),
    called_off("2 hour delay canceled, regular schedule", says_open=True),
    called_off("Open on regular schedule; 2 hour delay cancelled", says_open=True),
    called_off("The 2-hour delay has been cancelled. School will start on time.", says_open=True),
    called_off("Delay canceled, schools open at regular time", says_open=True),
    called_off("2 HOUR DELAY - CANCELLED - SCHOOL ON TIME", says_open=True),
    called_off("Delay has been called off"),
    called_off("Delay called off"),
    called_off("2 hour delay called off, school on regular schedule", says_open=True),
    called_off("Delay lifted"),
    called_off("Delay has been lifted"),
    called_off("Delay rescinded"),
    called_off("Delay revoked"),
    called_off("Delay withdrawn"),
    called_off("Delay no longer in effect"),
    called_off("Delay is no longer needed"),
    called_off("2 hour delay not needed"),
    called_off("2 hour delay is off"),
    called_off("The delay is now off"),
    called_off("Delay will not take place"),
    called_off("Delay does not go ahead"),
    called_off("Early dismissal will not happen"),
    called_off("NTI day won't take place; school in person"),
    called_off("Delay CANX"),
    called_off("2 hr delay - cxl"),
    called_off("Late start cancelled"),
    called_off("Late start - canceled"),
    called_off("Delayed opening cancelled"),
    called_off("Opening at 10:00 cancelled"),
    called_off("Delayed start canceled due to weather"),
    called_off("2 hour delay due to fog has been cancelled"),
    called_off("2 hour delay due to icy roads cancelled"),
    called_off("2 hour delay because of ice - lifted"),
    called_off("2 hour delay: cancelled due to improving conditions"),
    called_off("2 hour delay for all schools has been cancelled"),
    called_off("2 hour delay cancelled for all students"),
    called_off("The 2 hour delay for Lincoln Elementary has been cancelled"),
    called_off("2 hour delay at Maple Grove Middle School lifted"),
    called_off("Delay cancellation"),
    called_off("Update: 2 hour delay cancelled"),
    called_off("Early dismissal has been cancelled"),
    called_off("Early dismissal cancelled"),
    called_off("Early release canceled. Regular dismissal."),
    called_off("Early dismissal at 1:00 cancelled"),
    called_off("Early dismissal called off"),
    called_off("Early dismissal due to heat has been called off"),
    called_off("Early release day cancelled"),
    called_off("Half day cancelled"),
    called_off("Closing at noon cancelled"),
    called_off("Kindergarten early dismissal cancelled"),
    called_off("Closure cancelled"),
    called_off("Closure lifted"),
    called_off("Closure rescinded; school open", says_open=True),
    called_off("School closure cancelled"),
    called_off("Closing rescinded"),
    called_off("Snow day cancelled"),
    called_off("Snow day cancelled - school open", says_open=True),
    called_off("Inclement weather day cancelled"),
    called_off("NTI day cancelled"),
    called_off("AMI day canceled"),
    called_off("E-learning day cancelled; school in person"),
    called_off("eLearning day cancelled"),
    called_off("Remote learning day cancelled"),
    called_off("Remote learning cancelled; students report to school"),
    called_off("Virtual learning day called off"),
    called_off("Flexible instruction day cancelled"),
    called_off("Delay and early dismissal cancelled"),
    called_off("2 hour delay cancelled - Lincoln Elementary"),
    called_off("Lincoln Elementary: 2 hour delay cancelled"),
    called_off("Delay cancelled for Lincoln Elementary"),
    called_off("Delay cancelled (Bakuzo Temira Elementary)"),
]

# The calling-off word first, taking the status as its object: "Cancel delay".
BEFORE_THE_STATUS = [
    called_off("Cancel delay"),
    called_off("Cancelled delay"),
    called_off("Cancelled 2 hour delay"),
    called_off("Cancelled 2-hour delay for Lincoln Elementary"),
    called_off("We have cancelled the 2 hour delay"),
    called_off("District cancels 2-hour delay"),
    called_off("School district cancels delay"),
    called_off("The district has lifted the 2-hour delay"),
    called_off("Lifting the delay"),
    called_off("Rescinded: 2 hour delay"),
    called_off("Cancellation of 2 hour delay"),
    called_off("Cancelling today's early release"),
    called_off("Cancelled delay and early dismissal"),
    called_off("Called off the NTI day"),
]

# Called off on a named day, posted in the morning, the evening and on the day itself.
DATED = [
    called_off("Tomorrow's delay cancelled"),
    called_off("Delay for tomorrow cancelled"),
    called_off("2 hour delay tomorrow cancelled"),
    called_off("2 hour delay for Wednesday has been cancelled"),
    called_off("Wednesday: 2 hour delay (cancelled)"),
    called_off("Tuesday, January 20: 2 hour delay cancelled"),
    called_off("We have cancelled tomorrow's 2 hour delay"),
    called_off("Closure for Jan. 21 lifted"),
    called_off("Tomorrow's delay cancelled", posted=EVENING),
    called_off("2 hour delay tomorrow has been cancelled", posted=EVENING),
    called_off("Wednesday's early dismissal cancelled", posted=EVENING),
    called_off("NTI day tomorrow cancelled", posted=EVENING),
    called_off("Delay cancelled", posted=EVENING),
    called_off("Monday's delay cancelled", posted=FRI_EVENING),
    called_off("Closure lifted", posted=FRI_EVENING),
    called_off("Tomorrow's delay cancelled", posted=SUN_OVERNIGHT),
]

# A status called off and another named in its place, which takes its days.
REPLACED = [
    row("Delay cancelled, now closed", "closed", jan(20), notes=("revoked",)),
    row("Delay cancelled; closed", "closed", jan(20), notes=("revoked",)),
    row("2 hour delay cancelled - school closed", "closed", jan(20), notes=("revoked",)),
    row("Delay cancelled. Closed today.", "closed", jan(20), confidence=0.95, notes=("revoked",)),
    row("UPDATE: 2 hour delay cancelled. Schools closed.", "closed", jan(20), notes=("revoked",)),
    row("NTI day cancelled; closed", "closed", jan(20), notes=("revoked",)),
    row("Closure cancelled, 2 hour delay instead", "delayed", jan(20), delay=120),
    row("Closure cancelled. 2 hour delay.", "delayed", jan(20), delay=120),
    row("Tomorrow's delay cancelled. Closed.", "closed", jan(21), notes=("revoked",)),
    row("2 hour delay tomorrow cancelled. Update: now closed.", "closed", jan(21)),
    row("2 hour delay for Wednesday, Jan. 21 has been cancelled. Closed.", "closed", jan(21)),
    row("Tomorrow's closing rescinded. 2 hour delay.", "delayed", jan(21), delay=120),
    row("2 hour delay tomorrow cancelled. 3 hour delay.", "delayed", jan(21), delay=180),
    row("Early dismissal cancelled; 2 hour delay tomorrow", "delayed", jan(21), confidence=0.95),
    row("Closed today. Tomorrow's closure cancelled.", "closed", jan(20), confidence=0.95),
    row("No school today. Delay for tomorrow cancelled.", "closed", jan(20), confidence=0.95),
    row("Closed tomorrow. Delay cancelled.", "closed", jan(21), confidence=0.95),
    row("Delay cancelled, now closed", "closed", jan(21), posted=EVENING),
    row("Tomorrow's delay cancelled. Closed.", "closed", jan(21), posted=EVENING),
    row("Closure cancelled. Remote learning day.", "remote", jan(20)),
]

# A calling-off word that could as well restate the status, or close the school.
AMBIGUOUS = [
    row("Cancelled: 2 hour delay", confidence=0.3, notes=("ambiguous",)),
    row("Cancelled - NTI day", confidence=0.3, notes=("ambiguous",)),
    row("Cancelled - snow day", confidence=0.3, notes=("ambiguous",)),
    row("Snow day: cancelled", confidence=0.3, notes=("ambiguous",)),
    row("Closure - cancelled", confidence=0.3, notes=("ambiguous",)),
    row("Closed - cancelled", confidence=0.3, notes=("ambiguous",)),
    row("Closed (cancelled)", confidence=0.3, notes=("ambiguous",)),
    row("Closed. Cancelled.", confidence=0.3, notes=("ambiguous",)),
    row("Closed today - cancelled due to snow", confidence=0.3, notes=("ambiguous",)),
    row("No school tomorrow - cancelled", confidence=0.3, notes=("ambiguous",)),
    row("2 hour delay. Cancelled.", confidence=0.3, notes=("ambiguous",)),
    row("2 hour delay today, cancelled tomorrow", confidence=0.3, notes=("ambiguous",)),
    row("Status: cancelled - 2 hour delay", confidence=0.3, notes=("ambiguous",)),
    row("Called off: early dismissal", confidence=0.3, notes=("ambiguous",)),
    row("Update: cancelled - remote learning", confidence=0.3, notes=("ambiguous",)),
    row("2 hour delay (Lincoln Elementary) cancelled", confidence=0.25, notes=("ambiguous",)),
]

# Called off only maybe: the status is uncertain.
HEDGED = [
    row("Delay may be cancelled", confidence=0.3, notes=("hedged",)),
    row("Delay could be lifted later this morning", confidence=0.3, notes=("hedged",)),
    row("2 hour delay, which will be lifted if roads improve", confidence=0.3, notes=("hedged",)),
    row("2 hour delay cancelled?", confidence=0.3, notes=("hedged",)),
    row("Early dismissal might be called off", confidence=0.3, notes=("hedged",)),
    row("Delay likely to be lifted", confidence=0.3, notes=("hedged",)),
    row("Possibly cancelling the delay", confidence=0.3, notes=("hedged",)),
]

# The status stands: the calling off is denied, or the word belongs to another noun.
KEPT = [
    row("2 hour delay has not been cancelled", "delayed", jan(20), delay=120),
    row("2 hour delay will not be lifted", "delayed", jan(20), delay=120),
    row("The delay has not been lifted", "delayed", jan(20)),
    row("Delay remains in effect", "delayed", jan(20)),
    row("2 hour delay; students are off Friday", "delayed", jan(20), delay=120),
    row("Closed; practice will not take place", "closed", jan(20)),
    row("Classes canx", "closed", jan(20)),
    row("School cancelled", "closed", jan(20)),
    row("Classes cancelled", "closed", jan(20)),
    row("Classes canceled today", "closed", jan(20), confidence=0.95),
    row("School canceled due to snow", "closed", jan(20)),
    row("Cancelled classes", "closed", jan(20)),
    row("Cancelled: all classes", "closed", jan(20)),
    row("School called off", "closed", jan(20)),
    row("Classes called off today", "closed", jan(20), confidence=0.95),
    row("Calling off school tomorrow", "closed", jan(21), confidence=0.95),
    row("Lincoln Elementary: Cancelled", "closed", jan(20)),
    row("Snow day - school cancelled", "closed", jan(20)),
    row("Snow day; classes cancelled", "closed", jan(20)),
    row("No school today. Classes cancelled.", "closed", jan(20), confidence=0.95),
    row("School cancelled - NTI day", "remote", jan(20)),
    # In-person classes cancelled could also mean no school at all, as "No in-person
    # classes" could: the remote day beside it stands, with the doubt noted.
    row(
        "In-person classes cancelled; remote learning day",
        "remote",
        jan(20),
        confidence=0.8,
        notes=("ambiguous",),
    ),
    row(
        "E-learning day, in-person classes cancelled",
        "remote",
        jan(20),
        confidence=0.8,
        notes=("ambiguous",),
    ),
    row(
        "NTI day. In-person classes cancelled.",
        "remote",
        jan(20),
        confidence=0.8,
        notes=("ambiguous",),
    ),
    row(
        "No in-person classes; remote learning day",
        "remote",
        jan(20),
        confidence=0.8,
        notes=("ambiguous",),
    ),
    row("Classes cancelled, 2 hour delay for staff", "closed", jan(20), notes=("staff",)),
    row(
        "2 hour delay; after school activities cancelled",
        "delayed",
        jan(20),
        delay=120,
        notes=("activities_cancelled",),
    ),
    row("2 hour delay, cancelled all activities", "delayed", jan(20), delay=120),
    row("2 hour delay due to icy roads; bus routes cancelled", "delayed", jan(20), delay=120),
    row("Closed today; evening activities cancelled", "closed", jan(20), confidence=0.95),
    row("Closed due to snow; activities cancelled", "closed", jan(20)),
    row("Winter storm warning lifted, 2 hour delay", "delayed", jan(20), delay=120),
    row("2 hour delay; boil advisory lifted", "delayed", jan(20), delay=120),
    row("Boil water advisory lifted; school open", says_open=True),
    row("Weather advisory lifted", confidence=0.1, notes=("unrecognized",)),
    row("All activities cancelled", notes=("activities_cancelled",)),
    row("Evening activities cancelled", notes=("activities_cancelled",)),
]

# The text calls a status off and states it too: the day gets no status.
CONTRADICTED = [
    row("Closure cancelled. Closed.", confidence=0.25, notes=("conflict", "revoked")),
    row("Delay cancelled. 2 hour delay.", confidence=0.25, notes=("conflict", "revoked")),
    row(
        "Closed tomorrow. Tomorrow's closure has been cancelled.",
        confidence=0.25,
        notes=("conflict", "revoked"),
    ),
    row("2 hour delay for students, classes cancelled", confidence=0.25, notes=("conflict",)),
    # A later sentence that calls off a status of the kind with no day of its own: it is about
    # the status of that kind before it, on its days.
    row(
        "Closed tomorrow. Update: closure cancelled.",
        confidence=0.25,
        notes=("conflict", "revoked"),
    ),
    row("Closed tomorrow. Closure called off.", confidence=0.25, notes=("conflict", "revoked")),
    row("Closed tomorrow. The closure is off.", confidence=0.25, notes=("conflict", "revoked")),
    row("Closed tomorrow - closure cancelled", confidence=0.25, notes=("conflict", "revoked")),
    row("Closed tomorrow; closure rescinded", confidence=0.25, notes=("conflict", "revoked")),
    row("Closed today. Closure rescinded.", confidence=0.25, notes=("conflict", "revoked")),
    row(
        "Closed Thursday and Friday. Closure lifted.",
        confidence=0.25,
        notes=("conflict", "revoked"),
    ),
    row(
        "2 hour delay tomorrow. Update: delay cancelled.",
        confidence=0.25,
        notes=("conflict", "revoked"),
    ),
    row("2 hour delay tomorrow. Delay lifted.", confidence=0.25, notes=("conflict", "revoked")),
    row(
        "Early dismissal today. Update: early dismissal cancelled.",
        confidence=0.25,
        notes=("conflict", "revoked"),
    ),
    row(
        "eLearning day tomorrow. Update: eLearning day cancelled.",
        confidence=0.25,
        notes=("conflict", "revoked"),
    ),
    row("NTI day tomorrow. NTI day cancelled.", confidence=0.25, notes=("conflict", "revoked")),
    row(
        "2 hour delay tomorrow. Update: delay cancelled, school closed.",
        confidence=0.25,
        notes=("conflict", "revoked"),
    ),
]

# A bare "cancelled" attached to nothing, on another day than the status, or beside a
# closure it restates: the status stands, held at 0.8.
UNPLACED = [
    row("2 hour delay today. Cancelled tomorrow.", "delayed", jan(20), confidence=0.8),
    row("Cancelled due to weather; 2 hour delay tomorrow", "delayed", jan(21), confidence=0.8),
    row("Closed Thursday. Cancelled Friday.", "closed", jan(22), confidence=0.8),
    row("Closed; all cancelled", "closed", jan(20), confidence=0.8, notes=("ambiguous",)),
    row("Closings and cancellations: 2 hour delay", "delayed", jan(20), confidence=0.8),
    # A status of another kind called off, with no day: the status stated stands.
    row(
        "Closed tomorrow. Update: delay cancelled.",
        "closed",
        jan(21),
        confidence=0.95,
        notes=("revoked",),
    ),
    row(
        "Closed tomorrow. Friday's closure cancelled.",
        "closed",
        jan(21),
        confidence=0.95,
        notes=("revoked",),
    ),
]


@pytest.mark.parametrize("case", AFTER_THE_STATUS)
def test_a_word_after_the_status_calls_it_off(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", BEFORE_THE_STATUS)
def test_a_word_before_the_status_calls_it_off(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", DATED)
def test_a_status_called_off_on_a_named_day(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", REPLACED)
def test_the_status_named_instead_takes_its_place(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", AMBIGUOUS)
def test_a_word_that_could_restate_the_status_is_ambiguous(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", HEDGED)
def test_a_status_called_off_only_maybe_is_uncertain(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", KEPT)
def test_the_status_stands_when_nothing_calls_it_off(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", CONTRADICTED)
def test_a_status_called_off_and_stated_is_a_conflict(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", UNPLACED)
def test_a_bare_word_on_another_day_leaves_the_status(case: Row) -> None:
    check(case)


def test_a_status_called_off_keeps_its_details_out_of_the_result() -> None:
    result = parse_status("Early dismissal at 1:00 cancelled", posted_at=MORNING, tz=TZ)
    assert result.dismissal_time is None
    assert result.delay_minutes is None
    assert result.on(date(2026, 1, 20)) is None


def test_the_replacement_keeps_its_own_details() -> None:
    result = parse_status("Closure cancelled. Opening at 10:00 instead.", posted_at=MORNING, tz=TZ)
    assert result.kind == "delayed"
    assert result.opens_at == time(10, 0)


def test_words_that_call_nothing_off_are_left_out() -> None:
    text = normalize("Wind advisory lifted; closed")
    mentions = find_mentions(text)
    assert [mention.kind for mention in mentions] == ["revoke", "closed"]
    clauses = _clauses(text, [(mention.start, mention.end) for mention in mentions])
    pairing = pair_revocations(text, clauses, mentions, ())
    assert [mention.kind for mention in pairing.mentions] == ["closed"]
    assert pairing.revoked_by == {}


def test_the_status_called_off_is_marked_with_its_word() -> None:
    text = normalize("Cancelling the early release")
    mentions = find_mentions(text)
    clauses = _clauses(text, [(mention.start, mention.end) for mention in mentions])
    pairing = pair_revocations(text, clauses, mentions, ())
    assert [mention.kind for mention in pairing.mentions] == ["revoke", "early_dismissal"]
    assert pairing.mentions[1].revoked
    assert pairing.revoked_by == {1: 0}


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


CALLED_OFF_STATUSES = (
    "2 hour delay", "Two-hour delay", "2hr delay", "90 minute delay", "Delay", "Late start",
    "Delayed opening", "Early dismissal", "Early release", "Early dismissal at 1:00",
    "NTI day", "AMI day", "E-learning day", "Remote learning day", "Virtual learning day",
    "Flexible instruction day", "Closure", "Snow day",
)  # fmt: skip
AFTER_FORMS = (
    "{status} cancelled", "{status} canceled", "{status} has been cancelled",
    "{status} was called off", "{status} lifted", "{status} has been rescinded",
    "{status} revoked", "{status} {day} cancelled", "{day}: {status} cancelled",
    "{day}'s {status} cancelled", "{status} for {day} has been lifted",
    "{status} cancelled, regular schedule", "{status} cancelled - school open on time",
)  # fmt: skip
BEFORE_FORMS = (
    "Cancel {status}", "Cancelled {status}", "We have cancelled the {status}",
    "District cancels {day}'s {status}", "Lifting the {status}", "Rescinded: {status}",
)  # fmt: skip
MARKED_FORMS = ("{status}: cancelled", "{status} (cancelled)", "{status} - cancelled")
DAYS = ("today", "tomorrow", "Monday", "Wednesday", "Friday", "Jan. 22", "1/23")


@settings(max_examples=400, deadline=None)
@given(
    status=st.sampled_from(CALLED_OFF_STATUSES),
    form=st.sampled_from(AFTER_FORMS + BEFORE_FORMS + MARKED_FORMS),
    day=st.sampled_from(DAYS),
    posted=instants,
    tz=st.sampled_from(ZONES),
)
def test_a_status_called_off_never_shows(
    status: str, form: str, day: str, posted: datetime, tz: str
) -> None:
    text = form.format(status=status, day=day)
    result = parse_status(text, posted_at=posted, tz=tz)
    assert result.kind == "other"
    assert result.schedule == ()
    assert result.notes


@settings(max_examples=300, deadline=None)
@given(
    status=st.sampled_from(CALLED_OFF_STATUSES),
    form=st.sampled_from(AFTER_FORMS + BEFORE_FORMS),
    day=st.sampled_from(DAYS),
    name=st.sampled_from(("Lincoln Elementary", "Bakuzo Temira Middle School", "Oak Academy")),
    posted=instants,
    tz=st.sampled_from(ZONES),
)
def test_a_status_called_off_never_shows_beside_a_name(  # noqa: PLR0913, PLR0917 - drawn parts
    status: str, form: str, day: str, name: str, posted: datetime, tz: str
) -> None:
    for text in (f"{name}: {form}", f"{form} - {name}"):
        result = parse_status(text.format(status=status, day=day), posted_at=posted, tz=tz)
        assert result.kind == "other"


@settings(max_examples=300, deadline=None)
@given(
    subject=st.sampled_from(("School", "Classes", "All classes", "School for students")),
    verb=st.sampled_from(("cancelled", "canceled", "called off", "have been cancelled")),
    day=st.sampled_from(("today", "tomorrow", "Monday", "Jan. 22")),
    posted=instants,
    tz=st.sampled_from(ZONES),
)
def test_school_cancelled_is_still_a_closure(
    subject: str, verb: str, day: str, posted: datetime, tz: str
) -> None:
    result = parse_status(f"{subject} {verb} {day}", posted_at=posted, tz=tz)
    assert "revoked" not in result.notes
    if day == "Monday" and just_passed(0, posted, tz):
        assert result.kind == "other"  # the Monday just past, or the next: neither is stated
        assert "unreadable_date" in result.notes
        return
    assert result.kind == "closed"


@settings(max_examples=300, deadline=None)
@given(
    status=st.sampled_from(("2 hour delay", "Early dismissal", "NTI day", "Late start")),
    denial=st.sampled_from(
        ("has not been cancelled", "will not be lifted", "is not cancelled", "was not called off")
    ),
    posted=instants,
    tz=st.sampled_from(ZONES),
)
def test_a_denied_calling_off_keeps_the_status(
    status: str, denial: str, posted: datetime, tz: str
) -> None:
    with_denial = parse_status(f"{status} today {denial}", posted_at=posted, tz=tz)
    plain = parse_status(f"{status} today", posted_at=posted, tz=tz)
    assert with_denial.kind == plain.kind != "other"
    assert with_denial.dates == plain.dates


@settings(max_examples=300, deadline=None)
@given(
    status=st.sampled_from(CALLED_OFF_STATUSES),
    replacement=st.sampled_from(("Closed", "No school", "Schools closed")),
    link=st.sampled_from((", now ", "; ", ". ", " - ")),
    day=st.sampled_from(("Monday", "Wednesday", "Friday", "Jan. 22")),
    posted=instants,
    tz=st.sampled_from(ZONES),
)
def test_a_replacement_takes_the_days_of_the_status_called_off(  # noqa: PLR0913, PLR0917
    status: str, replacement: str, link: str, day: str, posted: datetime, tz: str
) -> None:
    replaced = parse_status(
        f"{day}'s {status} cancelled{link}{replacement}", posted_at=posted, tz=tz
    )
    stated = parse_status(f"{replacement} {day}", posted_at=posted, tz=tz)
    if status in {"Closure", "Snow day"}:
        # The replacement restates the closure called off: the text says both.
        assert replaced.kind == "other"
        return
    assert replaced.kind == stated.kind
    assert replaced.dates == stated.dates


UNDATED_CALLED_OFF = (
    ("Closed", ("Closure", "closure", "The closure", "School closure")),
    ("No school", ("Closure", "The closure")),
    ("2 hour delay", ("Delay", "delay", "The delay", "2 hour delay")),
    ("Late start", ("Late start", "The late start")),
    ("Early dismissal", ("Early dismissal", "The early dismissal")),
    ("Early release", ("Early release",)),
    ("eLearning day", ("eLearning day", "The eLearning day")),
    ("NTI day", ("NTI day",)),
    ("Remote learning", ("Remote learning",)),
)
UNDATED_REVOCATIONS = (
    "cancelled", "canceled", "has been cancelled", "lifted", "has been lifted", "rescinded",
    "called off", "has been called off", "is off", "revoked", "withdrawn",
)  # fmt: skip


@settings(max_examples=400, deadline=None)
@given(
    pair=st.sampled_from(UNDATED_CALLED_OFF),
    pick=st.integers(min_value=0, max_value=3),
    revocation=st.sampled_from(UNDATED_REVOCATIONS),
    lead=st.sampled_from(("", "Update: ", "UPDATE - ")),
    join=st.sampled_from((". ", "; ", " - ")),
    day=st.sampled_from(
        ("today", "tomorrow", "Monday", "Friday", "Jan. 22", "Thursday and Friday")
    ),
    posted=instants,
    tz=st.sampled_from(ZONES),
)
def test_a_later_status_called_off_with_no_day_leaves_no_confident_status(  # noqa: PLR0913, PLR0917
    pair: tuple[str, tuple[str, ...]],
    pick: int,
    revocation: str,
    lead: str,
    join: str,
    day: str,
    posted: datetime,
    tz: str,
) -> None:
    status, nouns = pair
    noun = nouns[pick % len(nouns)]
    text = f"{status} {day}{join}{lead}{noun} {revocation}."
    result = parse_status(text, posted_at=posted, tz=tz)
    assert result.kind == "other", text
    assert result.schedule == (), text


# A calling-off word right after a status calls that status off whatever follows it: "Closure
# cancelled for a 2 hour delay" calls off the closure, and the delay replaces it (a judgment
# call, 0.8). A post that withdraws itself ("Update: this has been rescinded", "This
# announcement has been withdrawn") leaves no status before it for sure.
CALLED_OFF_FOR = [
    ("Closure cancelled for a 2 hour delay", "delayed"),
    ("Closure scrapped for a 2 hour delay", "delayed"),
    ("Closure lifted for a 2 hour delay", "delayed"),
    ("Closed tomorrow. Closure cancelled for a 2 hour delay.", "other"),
    ("Closed tomorrow. Closure lifted for a 2 hour delay.", "other"),
    ("Early dismissal today. Early dismissal cancelled for a 2 hour delay.", "other"),
    ("eLearning day tomorrow. eLearning day cancelled for a 2 hour delay.", "other"),
    ("Closed tomorrow. Update: this has been rescinded.", "other"),
    ("Closed tomorrow. Update: the above is rescinded.", "other"),
    ("Closed tomorrow. This announcement has been withdrawn.", "other"),
    ("Closed tomorrow. This has been cancelled.", "other"),
]


@pytest.mark.parametrize(("text", "kind"), CALLED_OFF_FOR)
def test_a_status_called_off_for_another_never_stands(text: str, kind: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == kind
    assert result.confidence <= (0.8 if kind != "other" else 0.3)


@settings(max_examples=400, deadline=None)
@given(
    first=st.sampled_from(
        (("Closure", "closed"), ("2 hour delay", "delayed"), ("Early dismissal", "early_dismissal"),
         ("eLearning day", "remote"), ("Snow day", "closed"))
    ),
    verb=st.sampled_from(
        ("cancelled", "canceled", "called off", "lifted", "rescinded", "scrapped", "withdrawn",
         "revoked", "retracted")
    ),
    link=st.sampled_from(("for", "in favor of")),
    second=st.sampled_from(
        ("a 2 hour delay", "a closure", "remote learning", "an early dismissal")
    ),
    lead=st.sampled_from(("", "Closed tomorrow. ", "2 hour delay tomorrow. ", "Update: ")),
)  # fmt: skip
def test_a_status_called_off_never_stands_for_its_day(
    first: tuple[str, str], verb: str, link: str, second: str, lead: str
) -> None:
    phrase, kind = first
    text = f"{lead}{phrase} {verb} {link} {second}."
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    if result.kind == kind and result.confidence >= 0.7:
        assert "revoked" not in result.notes, text


@settings(max_examples=300, deadline=None)
@given(
    first=st.sampled_from(("Closure", "2 hour delay", "Early dismissal", "eLearning day")),
    verb=st.sampled_from(("cancelled", "canceled", "called off", "lifted", "rescinded")),
    noun=st.sampled_from(("students", "SMCS school", "families", "weather reasons", "safety")),
    second=st.sampled_from(("3 hour early dismissal", "2 hour delay", "Remote learning", "Closed")),
)
def test_a_status_called_off_for_something_else_trades_for_no_later_status(
    first: str, verb: str, noun: str, second: str
) -> None:
    # "for" and words that are no status, then a later sentence's status: no trade, so the
    # text reads as it does with no "for" phrase at all.
    traded = parse_status(
        f"{first} {verb} for {noun} on Friday. {second}.", posted_at=MORNING, tz=TZ
    )
    plain = parse_status(f"{first} {verb} on Friday. {second}.", posted_at=MORNING, tz=TZ)
    assert (traded.kind, traded.confidence) == (plain.kind, plain.confidence)


# "Zero hour" with no length word after it is the class period before the first bell, a
# program of the day, never a length of zero ("Zero hour delay" is no delay). A program or
# a period of the day called off "for" a status gives the status as the reason: the status
# stands, with the program noted ("Zero hour cancelled for the 2 hour delay").
PERIODS_CALLED_OFF = [
    ("Zero hour cancelled for the 2 hour delay", "delayed", ("partial_program",)),
    ("Zero-hour classes cancelled for the 2 hour delay", "delayed", ("partial_program",)),
    ("Zero period canceled for a 2 hour delay", "delayed", ("partial_program",)),
    ("2 hours late. Zero hour is canceled.", "delayed", ("partial_program",)),
    ("2 hour delay. No zero-hour classes.", "delayed", ("partial_program",)),
    ("Zero hour cancelled", "other", ("partial_program",)),
    ("Zero-hour classes cancelled", "other", ("partial_program",)),
    ("Early-bird classes cancelled", "other", ("partial_program",)),
    ("No zero period", "other", ("partial_program",)),
]


@pytest.mark.parametrize(("text", "kind", "notes"), PERIODS_CALLED_OFF)
def test_a_period_of_the_day_called_off_is_no_status(
    text: str, kind: str, notes: tuple[str, ...]
) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert (result.kind, result.notes) == (kind, notes)
    assert result.dates == (jan(20) if kind != "other" else ())


@settings(max_examples=300, deadline=None)
@given(
    thing=st.sampled_from(
        ("Zero hour", "Zero hour classes", "Zero-hour classes", "Zero period", "Breakfast",
         "AM preschool", "Early bird classes", "Early-bird classes", "Morning kindergarten",
         "Before-school activities", "Practice")
    ),
    verb=st.sampled_from(("cancelled", "canceled", "called off", "cancelled today")),
    status=st.sampled_from(
        (("the 2 hour delay", "delayed"), ("today's 90 minute delay", "delayed"),
         ("the late start", "delayed"), ("a 3 hour early dismissal", "early_dismissal"),
         ("the early dismissal", "early_dismissal"), ("the remote learning day", "remote"),
         ("the eLearning day", "remote"))
    ),
)  # fmt: skip
def test_a_program_called_off_for_a_status_leaves_the_status(
    thing: str, verb: str, status: tuple[str, str]
) -> None:
    phrase, kind = status
    text = f"{thing} {verb} for {phrase}"
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == kind, text
    assert "revoked" not in result.notes, text


# A status said not to hold "anymore" or "any longer" after it is stated is no status of the
# day's: "2 hour delay. Not delayed anymore." leaves no delay.
@settings(max_examples=200, deadline=None)
@given(
    stated=st.sampled_from(
        (("2 hour delay", "delayed"), ("Closed today", "closed"), ("Schools closed", "closed"),
         ("Delayed opening", "delayed"), ("Remote learning today", "remote"),
         ("90 minute delay", "on a delay"))
    ),
    lead=st.sampled_from((". Not ", "; not ", ". We are not ", " - not ")),
    since=st.sampled_from(("anymore", "any more", "any longer")),
)  # fmt: skip
def test_a_status_not_held_anymore_leaves_no_status(
    stated: tuple[str, str], lead: str, since: str
) -> None:
    status, again = stated
    text = f"{status}{lead}{again} {since}."
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other", text
    assert result.confidence <= 0.3, text
