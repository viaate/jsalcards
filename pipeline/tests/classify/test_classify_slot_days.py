"""A day repeated in a closings page's slots, and a listing's day after a dashed side note.

Every text here is a phrasing pattern written for these tests, not a claim
about a real school. Times are in New York in January 2026: Monday the 19th,
Tuesday the 20th, Wednesday the 21st.

* A closings page shows a day's slots ("Tuesday Morning:", "Tuesday
  Afternoon:", "Tuesday Evening:") and schools often repeat the day's status
  in each: "Tuesday Morning: Closed Tuesday | Tuesday Afternoon: Closed
  Tuesday" closes Tuesday at 0.95, as "Tuesday Morning: Closed | Tuesday
  Afternoon: Closed" does. Before a closure that names its own days, an
  afternoon slot heading only names a day, as a morning one does: "Tuesday
  Afternoon: Closed Tuesday" closes Tuesday.
* An afternoon slot comes after the day's school has begun, so a closure in it
  that names another day by name or date is for that day: "Thursday
  Afternoon: Closed Friday" closes Friday (the morning slot is the day's own:
  "Tuesday Morning: Closed Wednesday" disagrees with itself). A word for today
  or tomorrow in it must agree with the slot's day, and a run with no first
  day ("Wednesday Afternoon: Closed through Friday") is left unclear.
* "Tuesday Morning: Closed Tuesday | Tuesday Afternoon: Closed" is one closure:
  the afternoon slot's bare "Closed" is the day's closure again, not an early
  dismissal beside it. Alone, "Tuesday Afternoon: Closed" is still the
  afternoon (an early dismissal at 0.8).
* A listing that joins a side note to its status with a dash and ends with the
  day ("Closed-Activities Canceled Today") states that day for both: closed
  today at 0.95, whenever it is posted. After a semicolon or a comma the note
  keeps its day to itself, and a closure posted in the evening that names no
  day of its own is unclear.
"""

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from snowlight.classify import parse_status

TZ = "America/New_York"
ZONE = ZoneInfo(TZ)
SUN_EVENING = datetime(2026, 1, 18, 20, 0, tzinfo=ZONE)
MON_EVENING = datetime(2026, 1, 19, 18, 0, tzinfo=ZONE)
TUE = datetime(2026, 1, 20, 5, 30, tzinfo=ZONE)
TUE_NOON = datetime(2026, 1, 20, 12, 0, tzinfo=ZONE)
WED = datetime(2026, 1, 21, 6, 20, tzinfo=ZONE)
WED_AFTERNOON = datetime(2026, 1, 21, 15, 49, tzinfo=ZONE)
WED_EVENING = datetime(2026, 1, 21, 17, 20, tzinfo=ZONE)
WED_NIGHT = datetime(2026, 1, 21, 21, 20, tzinfo=ZONE)
THU_AFTERNOON = datetime(2026, 1, 22, 13, 37, tzinfo=ZONE)
FRI = datetime(2026, 1, 23, 6, 0, tzinfo=ZONE)


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
    dismissal: time | None


def row(  # noqa: PLR0913 - one table row
    text: str,
    posted: datetime,
    kind: str,
    dates: tuple[date, ...] = (),
    *,
    confidence: float = 0.95,
    notes: tuple[str, ...] = (),
    dismissal: time | None = None,
) -> object:
    case = Row(text, posted, kind, dates, confidence, notes, dismissal)
    return pytest.param(case, id=f"{text} @ {posted:%a %H:%M}")


# The day's status repeated in each of its slots.
REPEATED = [
    row("Tuesday Morning: Closed Tuesday | Tuesday Afternoon: Closed Tuesday", TUE, "closed",
        jan(20)),
    row("Tuesday Morning: Closed Tuesday | Tuesday Afternoon: Closed Tuesday", MON_EVENING,
        "closed", jan(20)),
    row("Tuesday Morning: Closed Today | Tuesday Afternoon: Closed Today", TUE, "closed", jan(20)),
    row("Friday Morning: Closed Friday | Friday Afternoon: Closed Friday", FRI, "closed", jan(23)),
    row(
        "Tuesday Morning: Closed Tuesday | Tuesday Afternoon: Closed Tuesday | Tuesday Evening: "
        "Closed Tuesday",
        MON_EVENING,
        "closed",
        jan(20),
    ),
    row(
        "Sunday Evening: Closed Monday...... Monday Morning: Closed Monday, no activities...... "
        "Monday Afternoon: Closed Monday, no activities...",
        SUN_EVENING,
        "closed",
        jan(19),
    ),
    row("Tuesday Morning: Closed Tuesday | Tuesday Afternoon: Closed", MON_EVENING, "closed",
        jan(20)),
    row("Tuesday Morning: Closed Today | Tuesday Afternoon: Closed", TUE, "closed", jan(20)),
    row("Tuesday Morning: Closed | Tuesday Afternoon: Closed Tuesday", MON_EVENING, "closed",
        jan(20)),
    row("Closed Tuesday | Tuesday Afternoon: Closed", MON_EVENING, "closed", jan(20)),
    row("Tuesday Morning: No School Tuesday | Tuesday Afternoon: No School Tuesday", MON_EVENING,
        "closed", jan(20)),
    row("Tuesday Morning: Remote Learning Tuesday | Tuesday Afternoon: Remote Learning Tuesday",
        MON_EVENING, "remote", jan(20)),
    row("Tuesday Morning: 2 hour delay Tuesday | Tuesday Afternoon: 2 hour delay Tuesday",
        MON_EVENING, "delayed", jan(20)),
    row("Wednesday Morning: Closed through Friday", TUE, "closed", jan(21, 22, 23)),
    row("Wednesday Morning: Closed until Friday", TUE, "closed", jan(21, 22)),
]  # fmt: skip

# The afternoon slot heading before a closure that names its own days.
AFTERNOON_SLOTS = [
    row("Tuesday Afternoon: Closed Tuesday", TUE_NOON, "closed", jan(20)),
    row("Tuesday Afternoon: Closed Today", TUE_NOON, "closed", jan(20)),
    row("Tuesday Afternoon: Closed tomorrow", MON_EVENING, "closed", jan(20)),
    row("Thursday Afternoon: Closed Friday", THU_AFTERNOON, "closed", jan(23)),
    row("Tuesday Afternoon: Closed Wednesday", MON_EVENING, "closed", jan(21)),
    row("Tuesday Afternoon: Closed Jan 21", MON_EVENING, "closed", jan(21)),
    row("Tuesday Afternoon: Closed Wednesday and Thursday", MON_EVENING, "closed", jan(21, 22)),
    row("Wednesday Afternoon: Closed Thursday through Friday", TUE, "closed", jan(22, 23)),
    # A word for today or tomorrow that disagrees with the slot's day: no day to trust.
    row("Tuesday Afternoon: Closed Today", MON_EVENING, "other", confidence=0.3,
        notes=("date_mismatch",)),
    row("Wednesday Afternoon: Closed tomorrow | Wednesday Evening: Closed tomorrow",
        WED_AFTERNOON, "other", confidence=0.3, notes=("date_mismatch",)),
    row("Tuesday Morning: Closed Wednesday", MON_EVENING, "other", confidence=0.3,
        notes=("date_mismatch",)),
    # A run with no first day after the afternoon slot: the afternoon, or the whole day?
    row("Wednesday Afternoon: Closed through Friday", TUE, "other", confidence=0.3,
        notes=("ambiguous",)),
    row("Closed Wednesday afternoon through Friday", TUE, "other", confidence=0.3,
        notes=("ambiguous",)),
    # The afternoon slot alone, or with a time: the afternoon.
    row("Tuesday Afternoon: Closed", TUE, "early_dismissal", jan(20), confidence=0.8),
    row("Tuesday Afternoon: Closed this afternoon", TUE, "early_dismissal", jan(20),
        confidence=0.8),
    row("Tuesday Afternoon: Closed PM", TUE, "early_dismissal", jan(20), confidence=0.8),
    row("Tuesday Afternoon: Closed at 1", TUE, "early_dismissal", jan(20), dismissal=time(13)),
    row("Tuesday Afternoon: Closed after 11:30", TUE, "early_dismissal", jan(20),
        dismissal=time(11, 30)),
    # A whole-day closure and a closing time in the afternoon slot disagree.
    row("Tuesday Morning: Closed Tuesday | Tuesday Afternoon: Closed at 1", MON_EVENING, "other",
        confidence=0.25, notes=("conflict",)),
    row("Tuesday Morning: 2 hour delay | Tuesday Afternoon: Closed Tuesday", MON_EVENING,
        "other", confidence=0.25, notes=("conflict",)),
]  # fmt: skip

# The listing's day after a side note joined by a dash.
LISTING_DAYS = [
    row("Closed-Activities Canceled Today", WED, "closed", jan(21),
        notes=("activities_cancelled",)),
    row("Closed-Activities Canceled Today", WED_EVENING, "closed", jan(21),
        notes=("activities_cancelled",)),
    row("Closed-Activities Canceled Today", WED_NIGHT, "closed", jan(21),
        notes=("activities_cancelled",)),
    row("Closed - Activities Canceled Today", WED_EVENING, "closed", jan(21),
        notes=("activities_cancelled",)),
    row("Closed-Evening Activities Canceled Today", WED_EVENING, "closed", jan(21),
        notes=("activities_cancelled",)),
    row("Closed-After-School Activities Canceled Today", WED_EVENING, "closed", jan(21),
        notes=("activities_cancelled",)),
    row("Closed-Activities Canceled Tomorrow", WED_EVENING, "closed", jan(22),
        notes=("activities_cancelled",)),
    row("Closed-Activities Canceled Thursday", WED_EVENING, "closed", jan(22),
        notes=("activities_cancelled",)),
    row("Closed-Activities Canceled Today Through Friday", WED_EVENING, "closed",
        jan(21, 22, 23), notes=("activities_cancelled",)),
    row("Closed-Activities Canceled Today due to ice", WED_EVENING, "closed", jan(21),
        notes=("activities_cancelled",)),
    row("No School-No Personnel Report Today", WED_EVENING, "closed", jan(21), notes=("staff",)),
    row("Closed Today-Activities Canceled", WED_EVENING, "closed", jan(21),
        notes=("activities_cancelled",)),
    row("Closed today", WED_EVENING, "closed", jan(21)),
    # After a semicolon or a comma the note keeps its day: the closure's own is unclear.
    row("Closed; activities cancelled today", WED_EVENING, "other", confidence=0.3,
        notes=("activities_cancelled", "undated")),
    row("Closed, activities canceled today", WED_EVENING, "other", confidence=0.3,
        notes=("activities_cancelled", "undated")),
    row("Closed; concert cancelled Monday", WED_EVENING, "other", confidence=0.3,
        notes=("activities_cancelled", "undated")),
]  # fmt: skip


@pytest.mark.parametrize("case", REPEATED + AFTERNOON_SLOTS + LISTING_DAYS)
def test_slot_and_listing_days(case: Row) -> None:
    result = parse_status(case.text, posted_at=case.posted, tz=TZ)
    assert result.kind == case.kind
    assert result.dates == case.dates
    assert result.confidence == case.confidence
    assert set(case.notes) <= set(result.notes)
    assert result.dismissal_time == case.dismissal
    if case.kind == "other":
        assert result.schedule == ()
    for note in ("conflict", "date_mismatch", "undated", "ambiguous"):
        if note not in case.notes:
            assert note not in result.notes


def test_an_afternoon_slot_repeating_a_closure_adds_no_early_dismissal() -> None:
    for text in (
        "Tuesday Morning: Closed Tuesday | Tuesday Afternoon: Closed Tuesday",
        "Tuesday Morning: Closed Tuesday | Tuesday Afternoon: Closed",
        "Closed Tuesday | Tuesday Afternoon: Closed",
    ):
        result = parse_status(text, posted_at=MON_EVENING, tz=TZ)
        assert [entry.kind for entry in result.schedule] == ["closed"], text


def test_a_slot_for_another_day_keeps_its_afternoon() -> None:
    # "Closed Tuesday" closes Tuesday; Wednesday's afternoon slot is Wednesday's early closing.
    result = parse_status("Closed Tuesday | Wednesday Afternoon: Closed", posted_at=MON_EVENING,
                          tz=TZ)  # fmt: skip
    assert [(entry.kind, entry.dates) for entry in result.schedule] == [
        ("closed", jan(20)),
        ("early_dismissal", jan(21)),
    ]
