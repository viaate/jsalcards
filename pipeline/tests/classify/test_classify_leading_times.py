"""A time before the closure words, or "at" a time after them, bounds the closure.

Every text here is a phrasing pattern written for these tests, not a claim
about a real school. Every row is posted at 6 a.m. on Wednesday 21 January 2026
in Chicago, so "today" is Wednesday the 21st.

"Classes cancelled until 10 am" is a late start and "Classes cancelled after 5
pm" the evening's; so is the same time said between who is closed and the
closure: "Classes before 10 am cancelled" opens at 10, "All classes after 5 pm
are cancelled" closes the building for the evening, and "All classes after 1 pm
cancelled" is an early dismissal at 1. A time the school day cannot start or
end at ("before 4 pm", "after 3 pm") says nothing anyone can act on: ``other``
at 0.3. A time a cancellation comes "at" says when, not from when: "Classes
cancelled at 1 pm" is unclear, and "Closed at 5 pm" closes the building after
school (a school-day time after a closure word is an early dismissal, as
"closing at 1:00" is). A time that ends a run of days is when the run ends ("closed through
Friday at 5 p.m."), and a bare hour is no time here ("after 2 snow days").
"""

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from snowlight.classify import parse_status

TZ = "America/Chicago"
ZONE = ZoneInfo(TZ)
MORNING = datetime(2026, 1, 21, 6, 0, tzinfo=ZONE)  # Wednesday


def jan(*days: int) -> tuple[date, ...]:
    return tuple(date(2026, 1, day) for day in days)


@dataclass(frozen=True)
class Row:
    text: str
    kind: str
    dates: tuple[date, ...]
    confidence: float
    notes: tuple[str, ...]
    opens_at: time | None
    dismissal: time | None


def row(  # noqa: PLR0913 - one table row
    text: str,
    kind: str = "other",
    dates: tuple[date, ...] = (),
    *,
    confidence: float = 0.3,
    notes: tuple[str, ...] = (),
    opens_at: time | None = None,
    dismissal: time | None = None,
) -> object:
    return pytest.param(Row(text, kind, dates, confidence, notes, opens_at, dismissal), id=text)


LEADING = [
    row("Classes before 10 am cancelled", "delayed", jan(21), confidence=0.9,
        opens_at=time(10)),
    row("Classes before noon cancelled", "delayed", jan(21), confidence=0.9, opens_at=time(12)),
    row("All classes before 10:30 am are cancelled", "delayed", jan(21), confidence=0.9,
        opens_at=time(10, 30)),
    row("Classes cancelled until 10 am", "delayed", jan(21), confidence=0.9, opens_at=time(10)),
    row("All classes before 4pm canceled.", notes=("ambiguous",)),
    row("Classes before 4 pm cancelled; game cancelled", notes=("ambiguous",)),
    row("All classes after 3pm Thursday canceled; facilities close at 7pm",
        notes=("ambiguous",)),
    row("Classes before 3:45PM on 1/22 CLOSED. Class 3:45pm on will be announced",
        notes=("ambiguous",)),
    row("All classes after 5 p.m. cancelled", confidence=0.9, notes=("activities_cancelled",)),
    row("All classes after 5 pm are cancelled", confidence=0.9,
        notes=("activities_cancelled",)),
    row("Classes cancelled after 5 pm", confidence=0.9, notes=("activities_cancelled",)),
    row("Classes after 4 pm cancelled", notes=("ambiguous",)),
    row("Classes after 1 pm cancelled", "early_dismissal", jan(21), confidence=0.9,
        dismissal=time(13)),
    row("Classes after 12:30 cancelled", "early_dismissal", jan(21), confidence=0.9,
        dismissal=time(12, 30)),
]  # fmt: skip

AT = [
    row("Classes cancelled at 1 pm", notes=("ambiguous",)),
    # (A closure word "at" a school-day time is an early dismissal, as "closing at" is.)
    row("Closed at 1:00 pm", "early_dismissal", jan(21), confidence=0.9, dismissal=time(13)),
    row("Closed at 5 pm", confidence=0.9, notes=("activities_cancelled",)),
    row("Closed at 5 p.m.", confidence=0.9, notes=("activities_cancelled",)),
    row("Closed after 5 PM", confidence=0.9, notes=("activities_cancelled",)),
    # A place, not a time; and a time that ends a run of days.
    row("Closed at 3 schools", confidence=0.9, notes=("partial_program",)),  # some of them
    row("Closed tomorrow and Friday at all schools", "closed", jan(22, 23), confidence=0.95),
    row("Closed through Friday at 5 p.m.", "closed", jan(21, 22, 23), confidence=0.95),
]  # fmt: skip


def check(case: Row) -> None:
    result = parse_status(case.text, posted_at=MORNING, tz=TZ)
    assert result.kind == case.kind
    assert result.dates == case.dates
    assert result.confidence == case.confidence
    assert set(case.notes) <= set(result.notes)
    assert result.opens_at == case.opens_at
    assert result.dismissal_time == case.dismissal


@pytest.mark.parametrize("case", LEADING)
def test_a_time_before_the_closure_words(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", AT)
def test_a_time_a_closure_comes_at(case: Row) -> None:
    check(case)
