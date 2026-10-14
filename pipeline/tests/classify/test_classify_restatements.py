"""An undated status beside a dated one: "Closed Friday. No school."

Every text here is a phrasing pattern written for these tests, not a claim
about a real school. Unless a row says otherwise it is posted at 6 a.m. on
Wednesday 21 January 2026 in Chicago, so "today" is Wednesday the 21st,
"tomorrow" Thursday the 22nd and "Friday" the 23rd.

Once the text names a day, the posting time says nothing about a status that
names none: read from the posting time, "No school" would close today, which
the text never says. Such a status

* is a restatement when a dated status of the same kind says all it says
  ("Closed Friday. No school."), and adds nothing;
* joins the dated status it restates when it adds to it ("Closed tomorrow.
  NTI day." is remote learning tomorrow; "2 hour delay tomorrow. Opening at
  10:00." gives the opening time);
* takes the days of the status it updates or replaces ("2 hour delay
  tomorrow. Update: now closed.");
* and otherwise names no day. It is left out, and the rest is held at 0.8,
  unless the posting time would put it on a day the text names for a status
  it would change: then that day could be either ("2 hour delay today.
  Closed.") and gets no status.
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
MORNING = datetime(2026, 1, 21, 6, 0, tzinfo=ZONE)  # Wednesday
EVENING = datetime(2026, 1, 21, 20, 0, tzinfo=ZONE)
THU_OVERNIGHT = datetime(2026, 1, 22, 1, 0, tzinfo=ZONE)
FRI_MORNING = datetime(2026, 1, 23, 6, 0, tzinfo=ZONE)
FRI_EVENING = datetime(2026, 1, 23, 20, 0, tzinfo=ZONE)
MON_MORNING = datetime(2026, 1, 26, 5, 30, tzinfo=ZONE)
SUN_EVENING = datetime(2026, 1, 25, 19, 0, tzinfo=ZONE)


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
    dates: tuple[date, ...] = (),
    *,
    posted: datetime = MORNING,
    confidence: float = 0.95,
    notes: tuple[str, ...] = (),
) -> object:
    label = f"{text} @ {posted:%a %H:%M}"
    return pytest.param(Row(text, posted, kind, dates, confidence, notes), id=label)


# "<day> closed. No school." and its variants: one status, said twice.
RESTATED_MORNING = [
    row("Closed tomorrow. No school.", "closed", jan(22)),
    row("Closed Friday - No school", "closed", jan(23)),
    row("Closed Friday. No school.", "closed", jan(23)),
    row("Friday: Closed. No school for students.", "closed", jan(23)),
    row("No school Friday. Classes cancelled.", "closed", jan(23)),
    row("Closed Friday due to snow. Classes cancelled.", "closed", jan(23)),
    row("Thursday: No school - closed", "closed", jan(22)),
    row("Closed Friday, Jan 23 - No classes", "closed", jan(23)),
    row("Closed Thursday; no school", "closed", jan(22)),
    row("Closed tomorrow. All schools closed.", "closed", jan(22)),
    row("CLOSED THURSDAY. NO SCHOOL.", "closed", jan(22)),
    row("Thursday - Closed - No school", "closed", jan(22)),
    row("No school. Closed Friday.", "closed", jan(23)),
    row("No school - closed tomorrow", "closed", jan(22)),
    row("Closed, no school tomorrow", "closed", jan(22)),
    row("Snow day tomorrow. No school.", "closed", jan(22), confidence=0.9),
    row("Closed Thursday and Friday. No school.", "closed", jan(22, 23)),
    row("Closed Jan 22. No school.", "closed", jan(22)),
    row("Closed Thursday, January 22. Classes cancelled.", "closed", jan(22)),
    row("Closed Friday. No school. Offices open.", "closed", jan(23)),
    row(
        "Closed tomorrow. No school, all activities cancelled.",
        "closed",
        jan(22),
        notes=("activities_cancelled",),
    ),
    row("Closed tomorrow. No school. Closed.", "closed", jan(22)),
    row("Closed today. Remote learning tomorrow. No school.", "closed", jan(21)),
    row("Closed Thursday; NTI Friday. No school.", "closed", jan(22)),
    row("Closed Friday. 2 hour delay Monday. No school.", "closed", jan(23)),
]

RESTATED_EVENING = [
    row("Closed Friday - No school", "closed", jan(23), posted=EVENING),
    row("Closed tomorrow. No school.", "closed", jan(22), posted=EVENING),
    row("Closed Thursday. No school.", "closed", jan(22), posted=EVENING),
    row("No school Friday. Classes cancelled.", "closed", jan(23), posted=EVENING),
    row("Thursday: No school - closed", "closed", jan(22), posted=EVENING),
    row("Closed Friday, Jan 23 - No classes", "closed", jan(23), posted=EVENING),
    row("No school. Closed Friday.", "closed", jan(23), posted=EVENING),
    row("Closed Monday. No school.", "closed", jan(26), posted=FRI_EVENING),
    row("Closed tomorrow. No school.", "closed", jan(26), posted=SUN_EVENING),
]

# Posted on the day the text names.
RESTATED_SAME_DAY = [
    row("Closed today. No school.", "closed", jan(21)),
    row("Closed Wednesday - No school", "closed", jan(21)),
    row("Closed Friday. No school.", "closed", jan(23), posted=FRI_MORNING),
    row("Closed today - no school", "closed", jan(23), posted=FRI_MORNING),
    row("Closed Friday - No school", "closed", jan(23), posted=FRI_EVENING),
    row("Monday: No school - closed", "closed", jan(26), posted=MON_MORNING),
    row("Closed Thursday; no school", "closed", jan(22), posted=THU_OVERNIGHT),
    row("Closed Jan 23. Classes cancelled.", "closed", jan(23), posted=FRI_MORNING),
]

# The undated status adds to the dated one: a closure that is remote learning, a detail.
JOINED = [
    row("Closed tomorrow. NTI day.", "remote", jan(22), confidence=0.9),
    row("No school Friday. E-learning day.", "remote", jan(23), confidence=0.9),
    row("Closed Friday - Remote learning day", "remote", jan(23), confidence=0.9),
    row("NTI day tomorrow. No school.", "remote", jan(22)),
    row("2 hour delay tomorrow. Opening at 10:00.", "delayed", jan(22)),
    row("Closed tomorrow. Closed until further notice.", "closed", jan(22)),
]

# The undated status updates or replaces the dated one: the day weighs both.
UPDATED = [
    row(
        "2 hour delay tomorrow. Update: now closed.",
        "closed",
        jan(22),
        confidence=0.8,
        notes=("superseded",),
    ),
    row(
        "2 hour delay tomorrow. Changed to closed.",
        "closed",
        jan(22),
        confidence=0.8,
        notes=("superseded",),
    ),
    row(
        "Closed tomorrow (was a 2 hour delay)",
        "closed",
        jan(22),
        confidence=0.8,
        notes=("superseded",),
    ),
]

# Nothing to restate: the undated status names no day.
UNPLACED = [
    row("Closed. 2 hour delay tomorrow.", "delayed", jan(22), confidence=0.8, notes=("undated",)),
    row("2 hour delay tomorrow. Closed.", "delayed", jan(22), confidence=0.8, notes=("undated",)),
    row(
        "Early dismissal at 1:00. Closed tomorrow.",
        "closed",
        jan(22),
        confidence=0.8,
        notes=("undated",),
    ),
    row(
        "2 hour delay tomorrow. 90 minute delay.",
        "delayed",
        jan(22),
        confidence=0.8,
        notes=("undated",),
    ),
    row(
        "Closed Monday. NTI. Closed Tuesday.",
        "closed",
        jan(26, 27),
        posted=FRI_MORNING,
        confidence=0.8,
        notes=("undated",),
    ),
    row("Closed Friday. 2 hour delay.", "closed", jan(23), confidence=0.8, notes=("undated",)),
    row("Closed tonight. No school.", "other", confidence=0.3, notes=("undated",)),
    row("Closed tonight. Update: now closed.", "other", confidence=0.3, notes=("undated",)),
    # Read from the posting time it would be on a named day, but would not change it.
    row("NTI day today. Delayed opening.", "remote", jan(21), confidence=0.8, notes=("undated",)),
    row(
        "2 hour delay today. Early dismissal.",
        "delayed",
        jan(21),
        confidence=0.8,
        notes=("undated",),
    ),
    row("Early release Wednesdays. Closed.", "other", confidence=0.3, notes=("undated",)),
    # Read from the posting time it would be on a named day, and change it: that day is unclear.
    row("2 hour delay today. Closed.", "other", confidence=0.25, notes=("conflict",)),
    row("Closed today. 2 hour delay.", "other", confidence=0.25, notes=("conflict",)),
    row(
        "Closed. 2 hour delay tomorrow.",
        "other",
        confidence=0.25,
        notes=("conflict",),
        posted=EVENING,
    ),
    row(
        "Closed Friday. 2 hour delay.",
        "other",
        confidence=0.25,
        notes=("conflict",),
        posted=datetime(2026, 1, 22, 20, 0, tzinfo=ZONE),
    ),
]


@pytest.mark.parametrize(
    "case", RESTATED_MORNING + RESTATED_EVENING + RESTATED_SAME_DAY + JOINED + UPDATED + UNPLACED
)
def test_undated_beside_dated(case: Row) -> None:
    result = parse_status(case.text, posted_at=case.posted, tz=TZ)
    assert result.kind == case.kind
    assert result.dates == case.dates
    assert result.confidence == case.confidence
    assert set(case.notes) <= set(result.notes)
    # No day the text does not name: every day in the schedule is in the expected set, or
    # (for a text with two dated statuses) another status's own day.
    if case.kind == "other":
        assert result.schedule == ()


@pytest.mark.parametrize("case", RESTATED_MORNING + RESTATED_EVENING + RESTATED_SAME_DAY)
def test_a_restatement_adds_no_day(case: Row) -> None:
    """The restating status puts nothing on the posting day, or on any day, of its own."""
    result = parse_status(case.text, posted_at=case.posted, tz=TZ)
    assert "undated" not in result.notes
    assert "conflict" not in result.notes
    assert all(entry.dates_stated for entry in result.schedule)


def test_joined_details_are_kept() -> None:
    result = parse_status("2 hour delay tomorrow. Opening at 10:00.", posted_at=MORNING, tz=TZ)
    assert (result.delay_minutes, result.opens_at) == (120, time(10))
    result = parse_status("Closed tomorrow. Closed until further notice.", posted_at=MORNING, tz=TZ)
    assert result.until_further_notice


def test_a_left_out_status_keeps_the_details_of_the_dated_one() -> None:
    result = parse_status("2 hour delay tomorrow. 90 minute delay.", posted_at=MORNING, tz=TZ)
    assert result.delay_minutes == 120
    assert len(result.schedule) == 1


# Property: a closure restated in any closure wording, before or after, in any order and
# posted at any time, gives exactly the schedule of the dated closure alone.
CLOSED_DATED = ("Closed", "No school", "Classes cancelled", "Schools closed")
RESTATEMENTS = ("No school", "Closed", "Classes cancelled", "All schools closed", "No classes")
DAYS = (
    "today",
    "tomorrow",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Jan 22",
    "Thursday, Jan 22",
    "1/23",
    "Monday and Tuesday",
    "through Friday",
)
SEPARATORS = (". ", " - ", "; ", ", ")
ZONES = ("America/Chicago", "America/New_York", "America/Denver", "America/Los_Angeles")
instants = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2032, 12, 31),
    timezones=st.sampled_from([ZoneInfo(name) for name in ZONES]),
)


@settings(max_examples=400, deadline=None)
@given(
    status=st.sampled_from(CLOSED_DATED),
    day=st.sampled_from(DAYS),
    day_first=st.booleans(),
    restatement=st.sampled_from(RESTATEMENTS),
    separator=st.sampled_from(SEPARATORS),
    restatement_first=st.booleans(),
    posted=instants,
    tz=st.sampled_from(ZONES),
)
def test_a_restated_closure_is_the_dated_closure_alone(  # noqa: PLR0913, PLR0917 - the drawn parts
    status: str,
    day: str,
    day_first: bool,
    restatement: str,
    separator: str,
    restatement_first: bool,
    posted: datetime,
    tz: str,
) -> None:
    dated = f"{day}: {status}" if day_first else f"{status} {day}"
    text = (
        f"{restatement}{separator}{dated}"
        if restatement_first
        else f"{dated}{separator}{restatement}"
    )
    alone = parse_status(dated, posted_at=posted, tz=tz)
    both = parse_status(text, posted_at=posted, tz=tz)
    assert both.schedule == alone.schedule
    assert (both.kind, both.dates, both.confidence) == (alone.kind, alone.dates, alone.confidence)
