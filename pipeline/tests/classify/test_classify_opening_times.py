"""An opening time at the hour many schools open anyway: "Opening at 7:30".

Every text here is a phrasing pattern written for these tests, not a claim about
a real school. Unless a row says otherwise it is posted at 6 a.m. on Wednesday
21 January 2026 in Chicago, so "today" is Wednesday the 21st.

An opening time with no word that says it is late is a late start only from
9:30 a.m., after any regular school day begins. Earlier ("Opening at 7:30",
"School starts at 8:00") it says nothing unusual, as "Dismissal at 3:00" says
nothing early: the listing is ``other`` at 0.3, noted ``ambiguous``. A word that
says the start is late keeps the time a delayed opening ("Delayed opening at
8:00", "8:00 late start", "Not opening until 8"), and so does a delay beside it
("2 hour delay, opening at 9:00", "Late start, doors open at 8:00"), unless the
delay's length puts the regular start before 7 a.m. ("2 hour delay, opening at
7:30" would start school at 5:30 on a regular day): the time and the length then
disagree, so the delay stands with its length alone, with no opening time, as a
judgment call (0.8). A change to a late time is a late start
("Opening at 8 AM changed to 10 AM"), as a judgment call. An opening time about
the offices or the staff stays their news, and closes nothing.
"""

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from snowlight.classify import parse_status

TZ = "America/Chicago"
ZONE = ZoneInfo(TZ)
WED = datetime(2026, 1, 21, 6, 0, tzinfo=ZONE)
TODAY = (date(2026, 1, 21),)


@dataclass(frozen=True)
class Row:
    text: str
    kind: str
    opens_at: time | None = None
    delay: int | None = None
    confidence: float = 0.9
    notes: tuple[str, ...] = ()


REGULAR_HOURS = [
    Row("Opening at 7:00 AM", "other", confidence=0.3, notes=("ambiguous",)),
    Row("Opening at 7:30", "other", confidence=0.3, notes=("ambiguous",)),
    Row("Opening at 6:45 AM", "other", confidence=0.3, notes=("ambiguous",)),
    Row("Opening at 9:15", "other", confidence=0.3, notes=("ambiguous",)),
    Row("School opens at 8:00", "other", confidence=0.3, notes=("ambiguous",)),
    Row("Doors open at 7:30", "other", confidence=0.3, notes=("ambiguous",)),
    Row("Classes begin at 8:15", "other", confidence=0.3, notes=("ambiguous",)),
    Row("8:00 start", "other", confidence=0.3, notes=("ambiguous",)),
    Row("Start time: 8:00", "other", confidence=0.3, notes=("ambiguous",)),
    Row("Opening at 8:00 due to snow", "other", confidence=0.3, notes=("ambiguous",)),
    Row("Opening at 8 AM changed to 9 AM", "other", confidence=0.3, notes=("ambiguous",)),
    Row("Opening at 8 AM changed to Thursday", "other", confidence=0.3, notes=("ambiguous",)),
    Row(
        "Opening at 7:30, staff report at 7", "other", confidence=0.3, notes=("ambiguous", "staff")
    ),
]

LATE_STARTS = [
    Row("Opening at 9:30", "delayed", opens_at=time(9, 30)),
    Row("Opening at 10:00", "delayed", opens_at=time(10)),
    Row("Delayed opening at 8:00", "delayed", opens_at=time(8)),
    Row("8:00 late start", "delayed", opens_at=time(8)),
    Row("8:00 delayed start", "delayed", opens_at=time(8)),
    Row("Late start, doors open at 8:00", "delayed", opens_at=time(8)),
    Row("Not opening until 8", "delayed", opens_at=time(8)),
    Row("Closed until 8:00", "delayed", opens_at=time(8)),
    Row("2 hour delay, opening at 9:00", "delayed", opens_at=time(9), delay=120),
    Row("1 hour delay, opening at 8:00", "delayed", opens_at=time(8), delay=60),
    Row("90 minute delay, opening at 8:30", "delayed", opens_at=time(8, 30), delay=90),
    Row("Opening at 9:15 - two hour delay", "delayed", opens_at=time(9, 15), delay=120),
    # A length that would start a regular day before 7:00: the time is left untold.
    Row("2 hour delay, opening at 7:30", "delayed", delay=120, confidence=0.8),
    Row("2 hour delay - opening at 7:30", "delayed", delay=120, confidence=0.8),
    Row("Opening at 7:30, 2 hour delay", "delayed", delay=120, confidence=0.8),
    Row("Opening at 7:30 AM - 2 hour delay", "delayed", delay=120, confidence=0.8),
    Row("2 hour delay, opening at 8:45", "delayed", delay=120, confidence=0.8),
    Row("90 minute delay, opening at 8:00", "delayed", delay=90, confidence=0.8),
    Row(
        "Opening at 8 AM changed to 10 AM",
        "delayed",
        opens_at=time(10),
        confidence=0.8,
        notes=("superseded",),
    ),
]


@pytest.mark.parametrize("case", REGULAR_HOURS + LATE_STARTS, ids=lambda case: case.text)
def test_an_opening_time_is_a_late_start_only_when_it_is_late_or_said_so(case: Row) -> None:
    result = parse_status(case.text, posted_at=WED, tz=TZ)
    assert result.kind == case.kind
    assert result.opens_at == case.opens_at
    assert result.delay_minutes == case.delay
    assert result.confidence == case.confidence
    assert result.notes == case.notes
    assert result.dates == (() if case.kind == "other" else TODAY)


def test_an_opening_time_about_the_offices_closes_nothing() -> None:
    alone = parse_status("Offices open at 7:30", posted_at=WED, tz=TZ)
    assert alone.kind == "other"
    assert "offices_closed" not in alone.notes
    closed = parse_status("Closed. Offices open at 8:00", posted_at=WED, tz=TZ)
    assert closed.kind == "closed"
    assert closed.dates == TODAY
    assert "offices_closed" not in closed.notes


REGULAR_CLOCKS = ("6:30", "7:00", "7:15 AM", "7:45", "8 AM", "8:30 a.m.", "9:00", "9:15 AM")
OPENING_WORDS = ("Opening at", "School opens at", "Doors open at", "Classes start at")


@settings(max_examples=200, deadline=None)
@given(
    clock=st.sampled_from(REGULAR_CLOCKS),
    words=st.sampled_from(OPENING_WORDS),
    day=st.sampled_from(("", " today", " tomorrow", " Thursday")),
)
def test_a_regular_opening_time_alone_is_never_a_confident_delay(
    clock: str, words: str, day: str
) -> None:
    result = parse_status(f"{words} {clock}{day}", posted_at=WED, tz=TZ)
    assert result.kind == "other"
    assert result.confidence <= 0.3
    assert result.opens_at is None


@settings(max_examples=200, deadline=None)
@given(
    hours=st.integers(1, 3),
    clock=st.sampled_from(("7:00", "7:30", "7:45", "8:00", "8:15", "8:30", "8:45", "9:00", "9:15")),
    before=st.booleans(),
)
def test_an_opening_time_beside_a_delay_is_never_one_the_delay_contradicts(
    hours: int, clock: str, before: bool
) -> None:
    delay = f"{hours} hour delay"
    text = f"Opening at {clock}, {delay}" if before else f"{delay} - opening at {clock}"
    result = parse_status(text, posted_at=WED, tz=TZ)
    assert result.kind == "delayed"
    assert result.delay_minutes == hours * 60
    hour, minute = map(int, clock.split(":"))
    regular_start = hour * 60 + minute - hours * 60
    if regular_start < 7 * 60:
        assert result.opens_at is None
        assert result.confidence == 0.8
    else:
        assert result.opens_at == time(hour, minute)
