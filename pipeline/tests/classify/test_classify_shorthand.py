"""Short forms of a delay, a time before its late start, and times that are not the school's.

Every text here is a phrasing pattern written for these tests, not a claim
about a real school. Unless a row says otherwise it is posted at 6 a.m. on
Tuesday 20 January 2026 in New York, so "today" is Tuesday the 20th and
"tomorrow" Wednesday the 21st.

* "Dly" is a delay, as some closings feeds shorten it: "2 Hr Dly" is a delay of
  two hours. "Opening Later" is a late start; "opening later this week" is not.
* A time can come before the words of a late start: "10 a.m. Delayed Start",
  "9:30 AM Late Arrival" and "10AM start" open the school at that time, as
  "Delayed start at 10 a.m." does.
* A time after "until" is the opening, bare hour or not ("Delayed until 10"),
  and "a" or "p" after a time is "am" or "pm" ("Delayed until 9a").
* A time in a clause of its own about something besides the school is that
  thing's, not the school's: "Opening at 10 a.m., staff report at 9:30" opens
  the school at 10. Two times for the school itself still leave it unclear
  which one holds ("Opening at 10, classes begin at 10:15").
"""

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from snowlight.classify import parse_status

TZ = "America/New_York"
ZONE = ZoneInfo(TZ)
TUE = datetime(2026, 1, 20, 6, 0, tzinfo=ZONE)
TUE_EVENING = datetime(2026, 1, 20, 20, 0, tzinfo=ZONE)


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
    opens_at: time | None
    dismissal: time | None


def row(  # noqa: PLR0913 - one table row
    text: str,
    kind: str,
    dates: tuple[date, ...] = jan(20),
    *,
    posted: datetime = TUE,
    confidence: float = 0.9,
    notes: tuple[str, ...] = (),
    delay: int | None = None,
    opens_at: time | None = None,
    dismissal: time | None = None,
) -> object:
    case = Row(text, posted, kind, dates, confidence, notes, delay, opens_at, dismissal)
    return pytest.param(case, id=f"{text} @ {posted:%a %H:%M}")


def check(case: Row) -> None:
    result = parse_status(case.text, posted_at=case.posted, tz=TZ)
    assert result.kind == case.kind
    assert result.dates == case.dates
    assert result.confidence == case.confidence
    assert result.notes == case.notes
    assert result.delay_minutes == case.delay
    assert result.opens_at == case.opens_at
    assert result.dismissal_time == case.dismissal


# "Dly": a delay.
SHORT_DELAYS = [
    row("2 Hr Dly", "delayed", delay=120),
    row("2 HR DLY", "delayed", delay=120),
    row("2hr Dly", "delayed", delay=120),
    row("90 Min Dly", "delayed", delay=90),
    row("2 Hr Dly Wednesday", "delayed", jan(21), confidence=0.95, delay=120),
    row("2 Hr Dly Tomorrow", "delayed", jan(21), confidence=0.95, delay=120),
    row("2 Hr Dly Wednesday", "delayed", jan(21), posted=TUE_EVENING, confidence=0.95, delay=120),
    row("Dly 2 hrs Wednesday", "delayed", jan(21), confidence=0.95, delay=120),
    row("2 hr dly/no am pre-k", "delayed", delay=120, notes=("partial_program",)),
    row("2 Hr Dly due to icy roads", "delayed", delay=120),
    # Words with "dly" inside them are no delay.
    row("Friendly reminder: 2 hour delay", "delayed", delay=120),
    row("Friendly reminder: closed", "closed"),
    row("Kindly note: closed Wednesday", "closed", jan(21), confidence=0.95),
    row("Deadly cold: closed", "closed"),
]

# "Opening later": a late start, when nothing but a day or a mark follows.
OPENING_LATER = [
    row("Opening Later", "delayed"),
    row("OPENING LATER", "delayed"),
    row("Opening later today", "delayed"),
    row("Opening later Wednesday", "delayed", jan(21)),
    row("Opening later tomorrow", "delayed", jan(21)),
    row("Opening Later; buses on snow routes", "delayed", notes=("transportation",)),
    row("Opening later: 2 hours", "delayed", delay=120),
    row("Starting later", "delayed"),
    # Later in the week: no late start of any day the text names.
    row(
        "Opening later this week",
        "other",
        (),
        confidence=0.3,
        notes=("unreadable_date", "unrecognized"),
    ),
    row(
        "Schools will start one hour later than usual on Wednesdays.",
        "other",
        (),
        confidence=0.1,
        notes=("unrecognized",),
    ),
    row("Library open later", "other", (), notes=("activities_cancelled",)),
]

# A time before the words of a late start.
TIME_FIRST = [
    row("10 a.m. Delayed Start", "delayed", opens_at=time(10)),
    row("10 AM Delayed Start", "delayed", opens_at=time(10)),
    row("10:00 a.m. late start", "delayed", opens_at=time(10)),
    row("10:30 AM Late Start", "delayed", opens_at=time(10, 30)),
    row("9:30 AM Late Arrival", "delayed", opens_at=time(9, 30)),
    row("10 AM delayed opening", "delayed", opens_at=time(10)),
    row("Noon late start", "delayed", opens_at=time(12)),
    row("10 a.m. Delayed Start Wednesday", "delayed", jan(21), confidence=0.95, opens_at=time(10)),
    row("Wednesday: 10 a.m. Delayed Start", "delayed", jan(21), confidence=0.95, opens_at=time(10)),
    row(
        "10 a.m. Delayed Start, Buses Run 2 Hours Late",
        "delayed",
        notes=("transportation",),
        opens_at=time(10),
    ),
    # Past the hours a school could open: a delay with no time anyone can act on.
    row("2:00 PM delayed start", "delayed"),
    # A start time alone reads as "starting at 10" and "opening at 10" do: the listing is
    # there because the day starts then.
    row("10 AM Start", "delayed", opens_at=time(10)),
    row("10:00 Start", "delayed", opens_at=time(10)),
    row("10AM start", "delayed", opens_at=time(10)),
    row("10 a.m. start", "delayed", opens_at=time(10)),
    row("10a start", "delayed", opens_at=time(10)),
    row("Start time 10 AM", "delayed", opens_at=time(10)),
    row("Start time: 10:30", "delayed", opens_at=time(10, 30)),
    row("Wednesday: 10AM start", "delayed", jan(21), confidence=0.95, opens_at=time(10)),
    # Unless the words say it is the usual one.
    row("Regular 8:00 start", "other", (), confidence=0.1, notes=("unrecognized",)),
    row("Normal 7:45 AM start", "other", (), confidence=0.1, notes=("unrecognized",)),
]

# A time after "until": the opening, bare hour or not; "a" and "p" are "am" and "pm".
UNTIL_TIMES = [
    row("Delayed until 10", "delayed", opens_at=time(10)),
    row("Delayed til 10", "delayed", opens_at=time(10)),
    row("Delayed till 10:30", "delayed", opens_at=time(10, 30)),
    row("Delayed Until 9a", "delayed", opens_at=time(9)),
    row("Delayed until 9:30a", "delayed", opens_at=time(9, 30)),
    row("Delayed until 9:30a.m.", "delayed", opens_at=time(9, 30)),
    row("Delay until 10 am", "delayed", opens_at=time(10)),
    row("Late start 10a", "delayed", opens_at=time(10)),
    row("Opening 10a", "delayed", opens_at=time(10)),
    row("Early dismissal 1p", "early_dismissal", dismissal=time(13)),
    row("Early dismissal at 12:30p", "early_dismissal", dismissal=time(12, 30)),
    # A time no school opens at, or a date: no opening time.
    row("Delayed until 7p", "delayed"),
    row("Delayed until the 22nd", "closed", jan(20, 21), confidence=0.8),
]

# A time about something besides the school is not the school's.
OTHER_SUBJECTS = [
    row("Opening at 10 a.m., staff report at 9:30", "delayed", notes=("staff",), opens_at=time(10)),
    row("Opening at 10:00, staff report at 9:00", "delayed", notes=("staff",), opens_at=time(10)),
    row("Opening at 10, staff at 9", "delayed", opens_at=time(10)),
    row("Opening at 10:00, offices open at 8", "delayed", opens_at=time(10)),
    row("Opening at 10, buses at 9:15", "delayed", opens_at=time(10)),
    row("Opening at 10, daycare opens at 7", "delayed", notes=("childcare",), opens_at=time(10)),
    row(
        "Delayed ; Opening at 10:30 staff to report at 10:00",
        "delayed",
        notes=("staff",),
        opens_at=time(10, 30),
    ),
    row(
        "Opening Late at 11:00 AM Tuesday, Staff Report at 10:00 am",
        "delayed",
        notes=("staff",),
        opens_at=time(11),
    ),
    row(
        "Early dismissal at 1:00, offices close at 3",
        "early_dismissal",
        dismissal=time(13),
    ),
    # Two times for the school itself: which one holds depends on the school.
    row("Opening at 10, classes begin at 10:15", "delayed"),
    row("Early release at 11:30 elementary, 12:15 secondary", "early_dismissal"),
    row("Early release: 11:30 elementary, 12:15 secondary", "early_dismissal"),
    # A time for staff alone, with none for the school.
    row("Early dismissal, staff at 2:00", "early_dismissal"),
]


@pytest.mark.parametrize("case", SHORT_DELAYS)
def test_dly_is_a_delay(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", OPENING_LATER)
def test_opening_later_is_a_late_start(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", TIME_FIRST)
def test_a_time_before_a_late_start_is_its_opening(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", OTHER_SUBJECTS)
def test_a_time_about_something_besides_the_school_is_not_the_school_s(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", UNTIL_TIMES)
def test_a_time_after_until_or_with_a_or_p_is_read(case: Row) -> None:
    check(case)


def test_the_tables_cover_every_form() -> None:
    tables = (SHORT_DELAYS, OPENING_LATER, TIME_FIRST, OTHER_SUBJECTS, UNTIL_TIMES)
    assert sum(map(len, tables)) >= 70


# Properties ---------------------------------------------------------------------------------

ZONES = ("America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles")
instants = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2032, 12, 31),
    timezones=st.sampled_from([ZoneInfo(name) for name in ZONES]),
)
CLOCKS = {
    "9 AM": time(9), "9:30 AM": time(9, 30), "10 a.m.": time(10), "10:00": time(10),
    "10:30 am": time(10, 30), "11 AM": time(11), "Noon": time(12),
}  # fmt: skip
LATE_WORDS = (
    "Delayed Start", "Late Start", "Late Arrival", "Delayed Opening", "late start", "Start",
)  # fmt: skip
OTHERS = (
    "staff report at", "staff arrive at", "offices open at", "buses run at", "daycare opens at",
    "teachers report at", "employees report at",
)  # fmt: skip


@settings(max_examples=200, deadline=None)
@given(
    clock=st.sampled_from(tuple(CLOCKS)),
    words=st.sampled_from(LATE_WORDS),
    posted=instants,
    tz=st.sampled_from(ZONES),
)
def test_a_time_first_late_start_reads_as_the_time_after_it(
    clock: str, words: str, posted: datetime, tz: str
) -> None:
    first = parse_status(f"{clock} {words}", posted_at=posted, tz=tz)
    after = parse_status(f"{words} at {clock}", posted_at=posted, tz=tz)
    assert first.kind == after.kind
    assert first.dates == after.dates
    assert first.opens_at == after.opens_at
    if first.kind == "delayed":
        assert first.opens_at == CLOCKS[clock]


@settings(max_examples=200, deadline=None)
@given(
    clock=st.sampled_from(tuple(CLOCKS)),
    other=st.sampled_from(OTHERS),
    other_clock=st.sampled_from(("7:30", "8 AM", "9:15", "11:45 AM", "8:00 am")),
    mark=st.sampled_from((", ", "; ", " - ", ". ")),
    posted=instants,
)
def test_another_subject_s_time_never_changes_the_school_s_opening(
    clock: str, other: str, other_clock: str, mark: str, posted: datetime
) -> None:
    alone = parse_status(f"Opening at {clock}", posted_at=posted, tz=TZ)
    beside = parse_status(f"Opening at {clock}{mark}{other} {other_clock}", posted_at=posted, tz=TZ)
    assert beside.kind == alone.kind
    assert beside.dates == alone.dates
    assert beside.opens_at == alone.opens_at
    if alone.kind == "delayed":
        assert alone.opens_at == CLOCKS[clock]
