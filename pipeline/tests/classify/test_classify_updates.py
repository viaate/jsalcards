"""Words after a status that take it back or leave it pending, and programs on weekend days.

Every text here is a phrasing pattern written for these tests, not a claim
about a real school. Unless a row says otherwise it is posted at 6 a.m. on
Tuesday 20 January 2026 in New York, so "today" is Tuesday the 20th and
"tomorrow" Wednesday the 21st.

* A decision still to come after a status ("Closed tomorrow. Decision at 5
  AM.", "Closed tomorrow - final decision by 5 a.m.") leaves it open: ``other``
  at 0.3, noted ``hedged``. A decision already taken, or one about another day
  ("Decision about Thursday by 5 PM"), leaves it standing.
* The school opening after a word that takes back what came before it
  ("Closed. Update: open.", "Closed. Just kidding, open.") replaces the status:
  ``other`` at 0.9, noted ``superseded``, and ``says_open``. An opening for
  another day, an opening on a delay, and offices opening do not.
* A program on a weekend day ("Saturday school cancelled") is not the school
  day: ``other`` at 0.9 with ``activities_cancelled``.
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
MORNING = datetime(2026, 1, 20, 6, 0, tzinfo=ZONE)  # Tuesday
EVENING = datetime(2026, 1, 20, 20, 0, tzinfo=ZONE)
THU_MORNING = datetime(2026, 1, 22, 6, 0, tzinfo=ZONE)


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
    says_open: bool


def row(  # noqa: PLR0913 - one table row
    text: str,
    kind: str = "other",
    dates: tuple[date, ...] = (),
    *,
    posted: datetime = MORNING,
    confidence: float = 0.95,
    notes: tuple[str, ...] = (),
    says_open: bool = False,
) -> object:
    label = f"{text} @ {posted:%a %H:%M}"
    return pytest.param(Row(text, posted, kind, dates, confidence, notes, says_open), id=label)


def pending(text: str, *, posted: datetime = MORNING) -> object:
    return row(text, posted=posted, confidence=0.3, notes=("hedged",))


def reopened(text: str, *, posted: datetime = MORNING) -> object:
    return row(text, posted=posted, confidence=0.9, notes=("superseded",), says_open=True)


def weekend(text: str) -> object:
    return row(text, confidence=0.9, notes=("activities_cancelled",))


def check(case: Row) -> None:
    result = parse_status(case.text, posted_at=case.posted, tz=TZ)
    assert result.kind == case.kind
    assert result.dates == case.dates
    assert result.confidence == case.confidence
    assert set(case.notes) <= set(result.notes)
    assert result.says_open is case.says_open
    if case.kind == "other":
        assert result.schedule == ()


DECISIONS = [
    pending("Closed tomorrow. Decision at 5 AM."),
    pending("Closed tomorrow. Decision at 5 AM.", posted=EVENING),
    pending("Closed tomorrow - final decision by 5 a.m."),
    pending("Closed tomorrow — final decision by 5 a.m."),
    pending("Closed tomorrow. Final decision will be made by 5 AM."),
    pending("Closed tomorrow. We will decide in the morning."),
    pending("Closed tomorrow. Decisions by 5 AM."),
    pending("No school tomorrow (final decision by 5:30 am)"),
    pending("2 hour delay tomorrow. Decision on any changes by 5 AM."),
    # A decision taken, or about another day, leaves the status standing.
    row("Closed tomorrow. The decision was made after consulting road crews.", "closed", jan(21)),
    row("Closed tomorrow; decision made", "closed", jan(21)),
    row("Closed tomorrow. Decision has been made.", "closed", jan(21)),
    row("Closed tomorrow. Decision about Thursday by 5 PM.", "closed", jan(21)),
    row("Closed tomorrow. Decision regarding Thursday at noon.", "closed", jan(21)),
    row("Closed tomorrow. Status update at 5 AM.", "closed", jan(21)),
]

RETRACTIONS = [
    reopened("Closed. Update: open."),
    reopened("Closed. Update: open.", posted=EVENING),
    reopened("Closed. Update: open on time."),
    reopened("Closed. Just kidding, open."),
    reopened("Closed. JK, open on time."),
    reopened("Closed. Never mind, open."),
    reopened("Closed. Disregard, school is open."),
    reopened("Closed. Correction: open."),
    reopened("Closed tomorrow. Update: open tomorrow."),
    reopened("2 hour delay. Update: now open on time."),
    # Another day, a delay, or the offices: the status stands.
    row("Closed Thursday. Update: open Friday.", "closed", jan(22)),
    row("Closed today, open tomorrow", "closed", jan(20)),
    row("Closed. Update: open on a 2 hour delay.", "delayed", jan(20), confidence=0.9,
        notes=("superseded",)),
    row("Closed. Update: offices open.", "closed", jan(20), confidence=0.9),
    row("Open on a 2 hour delay", "delayed", jan(20), confidence=0.9),
]  # fmt: skip

WEEKEND_PROGRAMS = [
    weekend("Saturday school cancelled"),
    weekend("Saturday classes cancelled"),
    weekend("Saturday school is cancelled due to snow"),
    weekend("Saturday academy closed"),
    weekend("Sunday school cancelled"),
    # A weekend day heading a closure, or named alone, is still that day.
    row("Saturday: school cancelled", "closed", jan(24), confidence=0.7, notes=("weekend",)),
    row("Closed Saturday", "closed", jan(24), confidence=0.7, notes=("weekend",)),
    # Beside a school day's status, that status stands.
    row("Saturday school cancelled. Closed Monday.", "closed", jan(26), posted=THU_MORNING,
        notes=("activities_cancelled",)),
    row("Saturday school cancelled. 2 hour delay Monday.", "delayed", jan(26),
        posted=THU_MORNING, notes=("activities_cancelled",)),
    # Seen on a Tuesday, the Monday is most likely the one just past: no day is stated.
    row("Saturday school cancelled. Closed Monday.", confidence=0.3,
        notes=("activities_cancelled", "unreadable_date")),
]  # fmt: skip


@pytest.mark.parametrize("case", DECISIONS)
def test_a_decision_still_to_come_leaves_the_status_open(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", RETRACTIONS)
def test_an_update_to_open_replaces_the_status(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", WEEKEND_PROGRAMS)
def test_a_weekend_program_is_not_the_school_day(case: Row) -> None:
    check(case)


def test_the_table_covers_every_form() -> None:
    assert len(DECISIONS) + len(RETRACTIONS) + len(WEEKEND_PROGRAMS) >= 35


ZONES = ("America/New_York", "America/Chicago", "America/Los_Angeles")
instants = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2032, 12, 31),
    timezones=st.sampled_from([ZoneInfo(name) for name in ZONES]),
)
STATUSES = ("Closed", "No school", "2 hour delay", "Early dismissal at 1:00", "NTI day")
DAYS = ("", "today", "tomorrow", "Wednesday")
DECISION_PHRASES = (
    "Decision at 5 AM",
    "final decision by 5 a.m.",
    "Final decision will be made by 5:30 AM",
    "We will decide in the morning",
)
MARKS = (". {}.", " - {}", ", {}", " ({})")


@settings(max_examples=300, deadline=None)
@given(
    status=st.sampled_from(STATUSES),
    day=st.sampled_from(DAYS),
    phrase=st.sampled_from(DECISION_PHRASES),
    mark=st.sampled_from(MARKS),
    posted=instants,
    tz=st.sampled_from(ZONES),
)
def test_a_pending_decision_after_any_status_leaves_it_open(  # noqa: PLR0913, PLR0917
    status: str, day: str, phrase: str, mark: str, posted: datetime, tz: str
) -> None:
    text = f"{status} {day}".strip() + mark.format(phrase)
    result = parse_status(text, posted_at=posted, tz=tz)
    assert result.kind == "other"
    assert result.confidence <= 0.3
