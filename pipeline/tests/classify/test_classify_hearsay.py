"""Hearsay is not the school's word: "Rumor: closed" states no closing.

Every text here is a phrasing pattern written for these tests, not a claim
about a real school. Each row is posted at 5:30 a.m. on Tuesday 20 January 2026
in New York, so "today" is Tuesday the 20th and "tomorrow" Wednesday the 21st.

A status that the text passes on as a rumour, as unconfirmed or unofficial, as
speculation or as a hoax ("Rumor: closed", "Unconfirmed report: 2 hour delay",
"Closed tomorrow (unverified)") is hedged: ``other`` at 0.3 with the note
``hedged``, as "Possible: closed" is. The word holds its clause, as every hedge
does: before the status, or just after it.

What stays a status: hearsay the text answers ("Despite rumors, we are closed
today", "Contrary to rumors, school is closed"), and hearsay about something else
in a sentence of its own ("Closed. Rumors of a delay are false").
"""

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from snowlight.classify import parse_status

TZ = "America/New_York"
MORNING = datetime(2026, 1, 20, 5, 30, tzinfo=ZoneInfo(TZ))  # Tuesday


def jan(*days: int) -> tuple[date, ...]:
    return tuple(date(2026, 1, day) for day in days)


@dataclass(frozen=True)
class Row:
    text: str
    kind: str
    dates: tuple[date, ...]
    confidence: float
    notes: tuple[str, ...]


def row(
    text: str,
    kind: str = "other",
    dates: tuple[date, ...] = (),
    *,
    confidence: float = 0.3,
    notes: tuple[str, ...] = ("hedged",),
) -> object:
    return pytest.param(Row(text, kind, dates, confidence, notes), id=text)


HEDGED = [
    row("Rumor: closed"),
    row("RUMOR: CLOSED"),
    row("Rumour: closed"),
    row("Rumors: 2 hour delay"),
    row("Rumor: Closed tomorrow"),
    row("Rumor has it: closed"),
    row("Rumored closed"),
    row("Rumoured closure tomorrow"),
    row("Unconfirmed: closed"),
    row("Unconfirmed report: closed"),
    row("Unverified: remote learning day"),
    row("Unofficial: closed tomorrow"),
    row("Speculation: closed"),
    row("Hearsay: early dismissal at noon"),
    row("Hoax: closed"),
    row("Closed (rumor)"),
    row("Closed tomorrow (unverified)"),
    row("Closed - unconfirmed"),
    row("2 hour delay - rumor"),
    row("Closed rumor"),
]

STANDING = [
    row("Despite rumors we are closed today", "closed", jan(20), confidence=0.95, notes=()),
    row("Contrary to rumors, school is closed", "closed", jan(20), confidence=0.9, notes=()),
    row("Ignore the rumors: closed", "closed", jan(20), confidence=0.9, notes=()),
    row("Regardless of rumors, closed tomorrow", "closed", jan(21), confidence=0.95, notes=()),
    row("Closed. Rumors of a delay are false", "closed", jan(20), confidence=0.9, notes=()),
]


def check(case: Row) -> None:
    result = parse_status(case.text, posted_at=MORNING, tz=TZ)
    assert result.kind == case.kind
    assert result.dates == case.dates
    assert result.confidence == case.confidence
    assert set(case.notes) <= set(result.notes)
    if case.kind == "other":
        assert result.schedule == ()


@pytest.mark.parametrize("case", HEDGED)
def test_hearsay_hedges_the_status(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", STANDING)
def test_answered_hearsay_leaves_the_status(case: Row) -> None:
    check(case)
