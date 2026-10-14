"""A condition or a hedge after a status leaves it open, wherever the phrase stands.

Every text here is a phrasing pattern written for these tests, not a claim
about a real school. Unless a row says otherwise it is posted at 5:30 a.m. on
Tuesday 20 January 2026 in New York, so "today" is Tuesday the 20th and
"tomorrow" Wednesday the 21st.

A status followed by a condition ("Closed tomorrow, if the storm hits", "No
school Friday - weather permitting", "Closed tomorrow depending on the
forecast", "Closed tomorrow should the storm arrive") or by a hedge ("Closed
Friday (tentative)", "Closed tomorrow (TBD)", "Closed tomorrow - possible") is
not stated: ``other`` at 0.3 with the note ``hedged``. That holds after a
comma, a dash, "but", in brackets, with no mark at all, and after a sentence
mark when the next sentence is only the condition or the hedge ("Closed
tomorrow. Pending road conditions."). A policy ("When school is closed for
weather, students do NTI") states no status for a day either.

What stays a status: a hedge beside another day ("Closed tomorrow, possibly
Wednesday"), a hedge about something else ("more snow expected", "possibly
longer", "expected to reopen Thursday"), a phrase that holds regardless ("even
if the snow stops", "whether or not it snows", "unless otherwise noted"), words
to the reader ("if you have questions"), and a sentence that states its own
condition and its consequence ("If conditions improve we will reopen Thursday").
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
MORNING = datetime(2026, 1, 20, 5, 30, tzinfo=ZONE)  # Tuesday
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


def row(  # noqa: PLR0913 - one table row
    text: str,
    kind: str = "other",
    dates: tuple[date, ...] = (),
    *,
    posted: datetime = MORNING,
    confidence: float = 0.95,
    notes: tuple[str, ...] = (),
) -> object:
    label = f"{text} @ {posted:%a %H:%M}"
    return pytest.param(Row(text, posted, kind, dates, confidence, notes), id=label)


def hedged(text: str, *, posted: datetime = MORNING) -> object:
    """A listing whose status is left open: other at 0.3, noted as hedged."""
    return row(text, posted=posted, confidence=0.3, notes=("hedged",))


def check(case: Row) -> None:
    result = parse_status(case.text, posted_at=case.posted, tz=TZ)
    assert result.kind == case.kind
    assert result.dates == case.dates
    assert result.confidence == case.confidence
    assert set(case.notes) <= set(result.notes)
    if case.kind == "other":
        assert result.schedule == ()


# A condition after a comma, a dash, "but" or in brackets.
CONDITIONS_AFTER_A_MARK = [
    hedged("No school tomorrow, if the storm hits"),
    hedged("Closed tomorrow, if the storm hits"),
    hedged("Closed tomorrow, unless roads are cleared"),
    hedged("Closed tomorrow, weather permitting"),
    hedged("Closed tomorrow - weather permitting"),
    hedged("Closed tomorrow (weather permitting)"),
    hedged("Closed tomorrow, weather and road conditions permitting"),
    hedged("Closed tomorrow, depending on the forecast"),
    hedged("Closed tomorrow - depending on road conditions"),
    hedged("Closed tomorrow, dependent on road conditions"),
    hedged("Closed tomorrow, contingent on the forecast"),
    hedged("Closed tomorrow, should the storm arrive"),
    hedged("Closed tomorrow - should conditions worsen"),
    hedged("Closed tomorrow, pending road conditions"),
    hedged("Closed tomorrow - decision pending"),
    hedged("Closed tomorrow (pending road conditions)"),
    hedged("Closed tomorrow, provided the forecast holds"),
    hedged("Closed tomorrow, assuming the storm arrives"),
    hedged("Closed tomorrow, barring a change in the forecast"),
    hedged("Closed tomorrow, subject to change"),
    hedged("Closed tomorrow (subject to change)"),
    hedged("Closed tomorrow, as long as the storm arrives"),
    hedged("Closed tomorrow, in case of heavy snow"),
    hedged("Closed tomorrow (if needed)"),
    hedged("Closed tomorrow, if necessary"),
    hedged("Closed tomorrow but only if the storm hits"),
    hedged("Closed tomorrow, only if roads are icy"),
    hedged("Closed tomorrow, if the storm hits Tuesday night"),
    hedged("Closed tomorrow, Jan. 21, if the storm hits"),
    hedged("Closed Jan. 21, if the storm hits"),
    hedged("Closed 1/22, weather permitting"),
    hedged("Closed Friday, unless the forecast changes"),
    hedged("Closed today and tomorrow, if roads stay icy"),
    hedged("Closed Monday-Wednesday, depending on the forecast"),
    hedged("Closed tomorrow due to snow, if the storm hits"),
    hedged("Classes cancelled tomorrow, if the storm hits"),
    hedged("2 hour delay tomorrow, if roads are icy"),
    hedged("2 hour delay tomorrow - depending on conditions"),
    hedged("Two-hour delay Friday (weather permitting)"),
    hedged("NTI day tomorrow, if the storm hits"),
    hedged("E-learning day Friday, weather permitting"),
    hedged("Remote learning tomorrow, should power fail"),
    hedged("Early dismissal at 1:00 today, if the storm arrives early"),
    hedged("Early release today (pending the forecast)"),
    hedged("Closed, if the storm hits"),
    hedged("Closed tomorrow, if the storm hits", posted=EVENING),
    hedged("No school tomorrow - weather permitting", posted=EVENING),
    # A condition between two parts of a sentence is on both.
    hedged("Closed tomorrow, if the storm hits, NTI Thursday"),
]

# A phrase of its own that is only a hedge.
HEDGES_AFTER_A_MARK = [
    hedged("Closed Friday (tentative)"),
    hedged("Closed today (tentative)"),
    hedged("Closed (tentative)"),
    hedged("Closed tomorrow (TBD)"),
    hedged("Closed tomorrow - possible"),
    hedged("Closed tomorrow \u2013 tentative"),  # an en dash
    hedged("2 hour delay today (pending)"),
    hedged("Closed tomorrow, tentatively"),
    hedged("Closed tomorrow - tentative at this time"),
    hedged("Closed tomorrow (unconfirmed)"),
    hedged("Closed tomorrow (not confirmed)"),
    hedged("Closed tomorrow (not yet final)"),
    hedged("Closed tomorrow (not yet)"),
    hedged("Closed tomorrow (to be determined)"),
    hedged("Closed tomorrow (to be confirmed)"),
    hedged("Closed tomorrow, TBA"),
    hedged("Closed tomorrow (maybe)"),
    hedged("Closed tomorrow, likely"),
    hedged("Closed tomorrow, probably"),
    hedged("No school tomorrow - possibly"),
    hedged("Closed tomorrow - unlikely"),
    hedged("Closed tomorrow (preliminary)"),
    hedged("Closed tomorrow (?)"),
    hedged("2 hour delay tomorrow (possible)"),
    hedged("NTI day Friday (tentative)"),
    hedged("Early dismissal at noon (tentative)"),
    hedged("Closed Jan. 22 (tentative)"),
    hedged("Closed Friday (tentative)", posted=EVENING),
    # The status itself may still change.
    hedged("2 hour delay (may change)"),
    hedged("2 hour delay - could change"),
    hedged("Closed tomorrow, may change"),
    hedged("Delayed 2 hours, changes possible"),
    hedged("Closed tomorrow (change possible)"),
]

# After a sentence mark: a sentence that is only the hedge or the condition.
FRAGMENTS = [
    hedged("Closed tomorrow. Tentative."),
    hedged("Closed tomorrow. TBD"),
    hedged("Closed tomorrow; tentative"),
    hedged("2 hour delay tomorrow. Pending road conditions."),
    hedged("Closed tomorrow. Weather permitting."),
    hedged("Closed tomorrow. Subject to change."),
    hedged("Closed tomorrow. Depending on the forecast."),
    hedged("Closed tomorrow. If the storm hits."),
    hedged("Closed tomorrow. Only if roads are icy."),
]

# No mark between the status and the condition.
CONDITIONS_IN_THE_CLAUSE = [
    hedged("Closed tomorrow depending on the forecast"),
    hedged("Closed tomorrow should the storm arrive"),
    hedged("Closed tomorrow weather permitting"),
    hedged("Closed tomorrow pending road conditions"),
    hedged("Closed tomorrow assuming the storm arrives"),
    hedged("Closed tomorrow provided the storm arrives"),
    hedged("Closed tomorrow barring a change"),
    hedged("Closed tomorrow subject to change"),
    hedged("Closed tomorrow if the storm hits"),
    hedged("No school tomorrow unless roads clear"),
    hedged("Closed tentative"),
]

# The condition or the hedge before the status.
CONDITIONS_BEFORE = [
    hedged("Depending on conditions, 2 hour delay tomorrow"),
    hedged("Weather permitting, school will open on a 2 hour delay"),
    hedged("Pending road conditions, closed tomorrow"),
    hedged("Barring a change, closed tomorrow"),
    hedged("Should the storm arrive, NTI day tomorrow"),
    hedged("Tentative: closed tomorrow"),
]

# What a school does when it closes, not a status for a day.
POLICIES = [
    hedged("When school is closed for weather, students do NTI"),
    hedged("When schools close for snow, students complete NTI work"),
    hedged("Whenever school is closed, it is an e-learning day"),
    hedged("Students do NTI whenever school is closed"),
    hedged("Students do NTI, whenever school is closed"),
    hedged("In the event of a closure, students will do NTI"),
]

# A hedge or a condition about something else: the status stands.
STANDING = [
    row("Closed tomorrow, possibly Wednesday", "closed", jan(21)),
    row("Closed tomorrow, possibly longer", "closed", jan(21)),
    row("Closed tomorrow, expected to reopen Thursday", "closed", jan(21)),
    row("Closed tomorrow, more snow expected", "closed", jan(21)),
    row("Closed tomorrow, heavy snow possible", "closed", jan(21)),
    row("Closed tomorrow (confirmed)", "closed", jan(21)),
    row("Closed tomorrow for now", "closed", jan(21)),
    row("Closed today - make up day TBD", "closed", jan(20)),
    row("Closed today. Tomorrow TBD.", "closed", jan(20)),
    row("Closed today, decision on tomorrow pending", "closed", jan(20)),
    row("Closed Thursday, and if needed, Friday", "closed", jan(22)),
    row("Closed tomorrow even if the snow stops", "closed", jan(21)),
    row("Closed tomorrow, whether or not it snows", "closed", jan(21)),
    row("Closed tomorrow unless otherwise noted", "closed", jan(21)),
    row("Closed tomorrow, unless otherwise notified", "closed", jan(21)),
    row("Closed today, if you have questions call the office", "closed", jan(20)),
    row("Closed tomorrow, should you have questions call the office", "closed", jan(21)),
    row("Closed tomorrow. Unless you hear otherwise.", "closed", jan(21)),
    row("Closed tomorrow, students should check email", "closed", jan(21)),
    row("Closed tomorrow, when the storm arrives", "closed", jan(21)),
    row("Closed tomorrow; if conditions improve we will reopen Thursday", "closed", jan(21)),
    row("Closed tomorrow. If conditions improve, we will reopen.", "closed", jan(21)),
    row("Closed tomorrow. If you have questions, call the office.", "closed", jan(21)),
    row("2 hour delay tomorrow, possibly Thursday", "delayed", jan(21)),
    row("Closed tomorrow, to be safe", "closed", jan(21)),
    row("Closed tomorrow - not a drill", "closed", jan(21)),
    row("Closed tomorrow, to be safe; offices open, weather permitting", "closed", jan(21)),
    row("Closed tomorrow - not a drill. Makeup day TBD.", "closed", jan(21)),
]

# "Closed" as a word for something other than the school day.
NOT_CLOSURES = [
    row("Closed to visitors", confidence=0.9, notes=("activities_cancelled",)),
    row("Closed to spectators tonight", confidence=0.9, notes=("activities_cancelled",)),
    row("Buildings closed to the public", confidence=0.9, notes=("activities_cancelled",)),
    row("Closed campus lunch", confidence=0.1, notes=("unrecognized",)),
    row("Closed campus", confidence=0.1, notes=("unrecognized",)),
    row("Closed-campus lunch today", confidence=0.1, notes=("unrecognized",)),
    row("Campus closed today", "closed", jan(20)),
    row("Closed today; closed campus lunch resumes Monday", "closed", jan(20)),
    row("Schools closed to students and staff", "closed", jan(20), confidence=0.9),
]


@pytest.mark.parametrize("case", CONDITIONS_AFTER_A_MARK)
def test_a_condition_after_a_mark_leaves_the_status_open(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", HEDGES_AFTER_A_MARK)
def test_a_hedge_after_a_mark_leaves_the_status_open(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", FRAGMENTS)
def test_a_sentence_that_is_only_a_hedge_leaves_the_status_open(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", CONDITIONS_IN_THE_CLAUSE)
def test_a_condition_with_no_mark_leaves_the_status_open(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", CONDITIONS_BEFORE)
def test_a_condition_before_the_status_leaves_it_open(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", POLICIES)
def test_a_policy_states_no_status(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", STANDING)
def test_a_hedge_about_something_else_leaves_the_status_standing(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", NOT_CLOSURES)
def test_closed_for_something_other_than_the_school_day(case: Row) -> None:
    check(case)


def test_the_table_covers_every_form() -> None:
    tables = (
        CONDITIONS_AFTER_A_MARK, HEDGES_AFTER_A_MARK, FRAGMENTS, CONDITIONS_IN_THE_CLAUSE,
        CONDITIONS_BEFORE, POLICIES, STANDING, NOT_CLOSURES,
    )  # fmt: skip
    assert sum(map(len, tables)) >= 130


# A modal or a hedge between "and" and a day leaves that day open, as "possibly Friday" does:
# "Closed Thursday and may close Friday" is a closure on Thursday alone.
MODAL_DAYS = [
    ("Closed Thursday and may close Friday", jan(22)),
    ("Closed Thursday and could close Friday", jan(22)),
    ("Closed Thursday and may be Friday", jan(22)),
    ("Closed today and might close tomorrow", jan(20)),
    ("Closed today and could be tomorrow as well", jan(20)),
    ("Closed today and not yet decided for tomorrow", jan(20)),
    ("Closed Thursday and not yet decided for Friday", jan(22)),
    ("Closed Thursday and tentatively Friday", jan(22)),
    ("Closed Thursday and unlikely Friday", jan(22)),
]


@pytest.mark.parametrize(("text", "dates"), MODAL_DAYS)
def test_a_day_after_a_modal_is_left_open(text: str, dates: tuple[date, ...]) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "closed"
    assert result.dates == dates


@settings(max_examples=400, deadline=None)
@given(
    status=st.sampled_from(("Closed", "No school", "2 hour delay", "eLearning", "Remote learning")),
    first=st.sampled_from((("today", 20), ("Thursday", 22), ("tomorrow", 21), ("Jan. 22", 22))),
    hedge=st.sampled_from(
        ("may close", "might close", "could close", "may be", "could be", "might be",
         "tentatively", "not yet decided for", "unlikely", "possibly", "maybe", "may also close",
         "probably")
    ),
    second=st.sampled_from((("Friday", 23), ("Monday", 26), ("Jan. 23", 23))),
    join=st.sampled_from((" and ", ", and ", "; ")),
)  # fmt: skip
def test_a_day_after_a_hedge_is_never_claimed_for_sure(
    status: str, first: tuple[str, int], hedge: str, second: tuple[str, int], join: str
) -> None:
    text = f"{status} {first[0]}{join}{hedge} {second[0]}"
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    if result.kind != "other" and result.confidence >= 0.7:
        assert date(2026, 1, second[1]) not in result.dates, text


# A day said to be undecided ("Wednesday still undecided", "Friday not decided yet") is that
# day's hedge, never a later day's after a heading's mark; when it heads a status's other day,
# which day the status is for is unclear. (Posted Monday 19 January in Chicago.)
CHICAGO = ZoneInfo("America/Chicago")
MONDAY_EVENING = datetime(2026, 1, 19, 19, 30, tzinfo=CHICAGO)
UNDECIDED_HEADINGS = [
    ("Wednesday still undecided: tomorrow: closed", MONDAY_EVENING),
    ("Friday not decided yet: tomorrow: No classes", MONDAY_EVENING),
    ("Friday not decided yet: Tue. Jan. 20, 2026: No classes", MONDAY_EVENING),
    ("Friday not decided yet: Tue. Jan. 20, 2026: No classes",
     datetime(2026, 1, 20, 5, 30, tzinfo=CHICAGO)),
    ("Friday not decided yet: Tue. Jan. 20, 2026: No classes",
     datetime(2026, 1, 21, 0, 30, tzinfo=CHICAGO)),
    ("Thursday undecided: Tue. Jan. 20, 2026: Closed", MONDAY_EVENING),
    ("Wednesday still undecided: closed", MONDAY_EVENING),
    ("Closed tomorrow, Wednesday not decided yet", MONDAY_EVENING),
]  # fmt: skip


@pytest.mark.parametrize(("text", "posted"), UNDECIDED_HEADINGS)
def test_an_undecided_day_heading_a_status_leaves_it_unclear(text: str, posted: datetime) -> None:
    result = parse_status(text, posted_at=posted, tz="America/Chicago")
    assert result.kind == "other", text
    assert result.confidence <= 0.3, text


def test_an_undecided_later_day_leaves_the_stated_day() -> None:
    for text in (
        "Closed tomorrow. Wednesday still undecided.",
        "Closed tomorrow; Wednesday undecided",
    ):
        result = parse_status(text, posted_at=MONDAY_EVENING, tz="America/Chicago")
        assert result.kind == "closed", text
        assert result.dates == (date(2026, 1, 20),), text


_UNDECIDED = ("undecided", "still undecided", "not decided yet", "not yet decided", "is undecided",
              "may close", "could close", "is still to be decided")  # fmt: skip


@settings(max_examples=400, deadline=None)
@given(
    hedged=st.sampled_from((("Wednesday", 21), ("Thursday", 22), ("Friday", 23), ("1/22", 22))),
    hedge=st.sampled_from(_UNDECIDED),
    mark=st.sampled_from((": ", " - ", "; ", ". ", ", ")),
    day=st.sampled_from(("tomorrow", "Tue. Jan. 20, 2026", "Tuesday", "")),
    status=st.sampled_from(("closed", "No classes", "Closed", "2 hour delay", "remote learning")),
)
def test_a_status_never_lands_on_an_undecided_day(
    hedged: tuple[str, int], hedge: str, mark: str, day: str, status: str
) -> None:
    # Invariant: a day the text calls undecided, or one a modal leaves open, is never a day
    # of a confident status.
    name, number = hedged
    if hedge.startswith(("may", "could")):
        text = f"{status} tomorrow and {hedge} {name}"
    else:
        middle = f"{day}: " if day else ""
        text = f"{name} {hedge}{mark}{middle}{status}"
    result = parse_status(text, posted_at=MONDAY_EVENING, tz="America/Chicago")
    if result.kind != "other" and result.confidence >= 0.7:
        days = {d for entry in result.schedule for d in entry.dates}
        assert date(2026, 1, number) not in days, (text, result)


def test_an_expected_day_is_left_open_and_a_denied_one_stays_denied() -> None:
    # "and expected Friday" hedges Friday as "and possibly Friday" does; "not expected
    # tomorrow" still denies the status.
    for text in ("Closed Thursday and expected Friday", "Closed Thursday and anticipated Friday"):
        result = parse_status(text, posted_at=MONDAY_EVENING, tz="America/Chicago")
        assert result.dates == (date(2026, 1, 22),), text
    denied = parse_status("Closure not expected tomorrow", posted_at=MORNING, tz=TZ)
    assert denied.kind == "other"
    assert "negated" in denied.notes
