"""A delay's or an early dismissal's length after the day it is for.

Every text here is a phrasing pattern written for these tests, not a claim
about a real school. Unless a row says otherwise it is posted at 6 a.m. on
Tuesday 20 January 2026 in New York, so "today" is Tuesday the 20th and
"tomorrow" Wednesday the 21st.

* Some closings pages put the day between the status and its length:
  "Delayed Wednesday 2 Hours", "Opening Late Friday 90 Minutes", "Closing Early
  Tuesday 2 Hours", "Early Dismissal Friday 1 Hour". The length is the
  status's, as in "Delayed 2 Hours Wednesday": a delay of 120 minutes on
  Wednesday at 0.95. The day between can be today, tomorrow, a weekday, a date
  or a weekday with a date, several days listed, or a run of days ("Delayed
  Wednesday thru Friday 2 Hours", "Wednesday-Friday"), and a mark or "by" can
  stand before the length. A weekday cut short with a full stop ("Weds.") is
  the weekday, not the end of a sentence.
* A length that is a status of its own ("Delayed Wednesday, 2 hour delay
  Thursday") or one of several days' lengths ("Delayed Monday 2 hours, Tuesday
  3 hours") is not the first status's length: that one keeps none.
* A number with a half before its unit is a length, not a day number:
  "Delayed Wednesday 2 1/2 hours" is Wednesday, not Wednesday the 2nd.
* A dismissal time with no word saying it is early ("Dismissing at 1:15 PM") is
  an early dismissal at 0.8 up to 1:30 p.m. and unclear after it ("Dismissal
  at 3:00" is an ordinary afternoon).
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
FRI_EVENING = datetime(2026, 1, 16, 20, 0, tzinfo=ZONE)
SAT = datetime(2026, 1, 17, 10, 0, tzinfo=ZONE)


def jan(*days: int) -> tuple[date, ...]:
    return tuple(date(2026, 1, day) for day in days)


type Entry = tuple[str, tuple[date, ...], int | None]


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
    dismissal: time | None
    reason: str | None
    schedule: tuple[Entry, ...] | None


def row(  # noqa: PLR0913 - one table row
    text: str,
    kind: str,
    dates: tuple[date, ...] = (),
    *,
    posted: datetime = TUE,
    confidence: float = 0.95,
    notes: tuple[str, ...] = (),
    delay: int | None = None,
    early: int | None = None,
    dismissal: time | None = None,
    reason: str | None = None,
    schedule: tuple[Entry, ...] | None = None,
) -> object:
    case = Row(
        text, posted, kind, dates, confidence, notes, delay, early, dismissal, reason, schedule
    )
    return pytest.param(case, id=f"{text} @ {posted:%a %H:%M}")


def delayed(  # noqa: PLR0913 - one table row
    text: str,
    dates: tuple[date, ...],
    delay: int | None,
    *,
    posted: datetime = TUE,
    confidence: float = 0.95,
    notes: tuple[str, ...] = (),
    reason: str | None = None,
) -> object:
    """A delay of ``delay`` minutes on the days given, at 0.95 unless the row says otherwise."""
    return row(
        text,
        "delayed",
        dates,
        posted=posted,
        confidence=confidence,
        notes=notes,
        delay=delay,
        reason=reason,
    )


def early(  # noqa: PLR0913 - one table row
    text: str,
    dates: tuple[date, ...],
    minutes: int | None,
    *,
    posted: datetime = TUE,
    confidence: float = 0.95,
    reason: str | None = None,
) -> object:
    """An early dismissal ``minutes`` early on the days given, at 0.95 unless said otherwise."""
    return row(
        text,
        "early_dismissal",
        dates,
        posted=posted,
        confidence=confidence,
        early=minutes,
        reason=reason,
    )


def check(case: Row) -> None:
    result = parse_status(case.text, posted_at=case.posted, tz=TZ)
    assert result.kind == case.kind
    assert result.dates == case.dates
    assert result.confidence == case.confidence
    assert result.notes == case.notes
    assert result.delay_minutes == case.delay
    assert result.dismissal_early_minutes == case.early
    assert result.dismissal_time == case.dismissal
    if case.reason is not None:
        assert result.reason == case.reason
    if case.kind == "other":
        assert result.schedule == ()
    if case.schedule is not None:
        found = tuple(
            (
                entry.kind,
                entry.dates,
                entry.delay_minutes if entry.kind == "delayed" else entry.dismissal_early_minutes,
            )
            for entry in result.schedule
        )
        assert found == case.schedule


# The day between a delay and its length: the Gray TV and WRAL shapes, and their kin.
DELAYS_AFTER_A_DAY = [
    delayed("Delayed Wednesday 2 Hours", jan(21), 120),
    delayed("Delayed Wednesday 1 Hour", jan(21), 60),
    delayed("Delayed Wednesday 3 Hours", jan(21), 180),
    delayed("Delayed Thursday 2 Hours", jan(22), 120),
    delayed("Delayed Friday 1 Hour", jan(23), 60),
    delayed("Delayed Friday 3 Hours", jan(23), 180),
    delayed("Delayed Tuesday 2 Hours", jan(20), 120),
    delayed("Delayed Tuesday 1 Hour", jan(20), 60),
    delayed("Delayed Monday 2 Hours", jan(19), 120, posted=FRI_EVENING),
    delayed("Delayed Monday 2 Hours", jan(19), 120, posted=SAT),
    delayed("Delayed Saturday 1 Hour", jan(24), 60, confidence=0.7, notes=("weekend",)),
    delayed("Delayed Tomorrow 2 hours", jan(21), 120),
    delayed("Delayed Tomorrow 2 hours", jan(21), 120, posted=TUE_EVENING),
    delayed("Delayed today 2 hours", jan(20), 120),
    delayed("Delayed Wednesday 2 Hours", jan(21), 120, posted=TUE_EVENING),
    delayed("Opening Late Wednesday 2 Hours", jan(21), 120),
    delayed("Opening Late Friday 2 Hours", jan(23), 120),
    delayed("Opening Late Monday 2 Hours", jan(19), 120, posted=FRI_EVENING),
    delayed("Opening Late Tuesday 2 Hours", jan(20), 120),
    delayed("Opening Late Thursday 2 Hours", jan(22), 120),
    delayed("Opening Late Friday 1 Hour", jan(23), 60),
    delayed("Opening Late Wednesday 3 Hours", jan(21), 180),
    delayed("Opening Late Friday 90 Minutes", jan(23), 90),
    delayed("Opening Late Wednesday 90 Minutes", jan(21), 90),
    delayed("Opening late tomorrow 2 hours", jan(21), 120),
    delayed("Opening late today 1 hour", jan(20), 60),
    delayed("Late start Wednesday 2 hours", jan(21), 120),
    delayed("Late Start Wednesday 90 minutes", jan(21), 90),
    delayed("Delayed start Wednesday 2 hours", jan(21), 120),
    delayed("Delayed opening tomorrow 2 hours", jan(21), 120),
    delayed("Delay Wed 2 hrs", jan(21), 120),
    delayed("Delay Weds 2 hr", jan(21), 120),
    delayed("Delays Wednesday 2 hours", jan(21), 120),
    delayed("Delayed Wednesday two hours", jan(21), 120),
    delayed("Delayed Wednesday one hour", jan(21), 60),
    delayed("Delayed Wednesday 2hrs", jan(21), 120),
    delayed("Delayed Wednesday 2 1/2 hours", jan(21), 150),
    delayed("Delayed Wednesday 2 and a half hours", jan(21), 150),
    delayed("Delayed Wednesday 1.5 hours", jan(21), 90),
    delayed("Delayed Wednesday 45 minutes", jan(21), 45),
    delayed("Delayed Wednesday by 2 hours", jan(21), 120),
    delayed("Delayed Wednesday for 2 hours", jan(21), 120),
    delayed("Delayed Wednesday - 2 Hours", jan(21), 120),
    delayed("Delayed Wednesday: 2 Hours", jan(21), 120),
    delayed("Delayed Wednesday, 2 hours", jan(21), 120),
    delayed("DELAYED WEDNESDAY 2 HOURS", jan(21), 120),
    delayed("Delayed Wed. 1/21 2 hrs", jan(21), 120),
    delayed("Delayed 1/21 two hours", jan(21), 120),
    delayed("Delayed Jan. 21 2 hours", jan(21), 120),
    delayed("Delayed Wednesday, Jan. 21, 2 Hours", jan(21), 120),
    delayed("Delayed Tomorrow (Wednesday) 2 hours", jan(21), 120),
    delayed("Delayed Thursday and Friday 2 hours", jan(22, 23), 120),
    delayed("Delayed Thursday, Friday 2 hours", jan(22, 23), 120),
    delayed("Delayed Wednesday thru Friday 2 Hours", jan(21, 22, 23), 120),
    delayed("Delayed Wednesday through Friday 2 Hours", jan(21, 22, 23), 120),
    delayed("Delayed Wednesday-Friday 2 Hours", jan(21, 22, 23), 120),
    delayed("Delayed Wednesday - Friday 2 Hours", jan(21, 22, 23), 120),
    delayed("Delayed Wed-Fri 2 hrs", jan(21, 22, 23), 120),
    delayed("Delayed 1/21-1/23 2 hours", jan(21, 22, 23), 120),
    delayed("Opening Late Wednesday thru Friday 90 Minutes", jan(21, 22, 23), 90),
    delayed("Delayed Weds. 2 hrs.", jan(21), 120),
    delayed("Delayed Weds 2 hrs", jan(21), 120),
    delayed("Delayed Thurs. 2 hours", jan(22), 120),
    delayed("Delayed Tues. 2 hours", jan(20), 120),
    delayed("Delayed Wednesday 2 Hours due to snow", jan(21), 120, reason="Winter storm"),
    delayed("Delayed Wednesday 2 Hours - icy roads", jan(21), 120, reason="Ice"),
    delayed("Lincoln Elementary: Delayed Wednesday 2 Hours", jan(21), 120),
    delayed("Delayed Wednesday 2 Hours; Offices open", jan(21), 120),
    row(
        "Delayed Wednesday 2 hours, Thursday closed",
        "delayed",
        jan(21),
        delay=120,
        schedule=(("delayed", jan(21), 120), ("closed", jan(22), None)),
    ),
]

# The same with an early dismissal.
EARLY_AFTER_A_DAY = [
    early("Closing Early Wednesday 2 Hours", jan(21), 120),
    early("Closing Early Tuesday 2 Hours", jan(20), 120),
    early("Closing Early Tuesday 1 Hour", jan(20), 60),
    early("Closing Early Tuesday 3 Hours", jan(20), 180),
    early("Closing Early Monday 2 Hours", jan(19), 120, posted=FRI_EVENING),
    early("Closing Early Friday 1 Hour", jan(23), 60),
    early("Closing Early Wednesday 3 Hours", jan(21), 180),
    early("Closing early today 2 hours", jan(20), 120),
    early("Closing Early 2 hours Today", jan(20), 120),
    early("Closing Early 1 hour Today", jan(20), 60),
    early("Early Dismissal Friday 2 Hours", jan(23), 120),
    early("Early Dismissal Tuesday 1 Hour", jan(20), 60),
    early("Early dismissal tomorrow 2 hours", jan(21), 120),
    early("Early Release Wednesday 90 minutes", jan(21), 90),
    early("Early Out Wednesday 1 hour", jan(21), 60),
    early("Dismissing early Wednesday 2 hours", jan(21), 120),
    early("Dismissing Wednesday 2 hours early", jan(21), 120),
    early("Closing Wednesday 2 hours early", jan(21), 120),
    early("Releasing students Wednesday 90 minutes early", jan(21), 90),
    early("Closing Early Wednesday, 2 Hours", jan(21), 120),
    early("Closing Early Wed. 1/21 2 hrs", jan(21), 120),
    early("Closing early Thursday & Friday 1 hour", jan(22, 23), 60),
    early("Closing Early Wednesday thru Friday 1 Hour", jan(21, 22, 23), 60),
    early("Closing Early Wednesday-Friday 2 Hours", jan(21, 22, 23), 120),
    early("Early Dismissal Wednesday through Friday 2 Hours", jan(21, 22, 23), 120),
    early("Closing Early Weds. 2 Hours", jan(21), 120),
    early("Closing Early Wednesday 2 Hours due to ice", jan(21), 120, reason="Ice"),
]

# A length that is not the first status's: a status of its own, or one of several days'.
NOT_THE_STATUS_LENGTH = [
    row(
        "Delayed Wednesday 2 hour delay Thursday",
        "delayed",
        jan(21),
        confidence=0.9,
        schedule=(("delayed", jan(21), None), ("delayed", jan(22), 120)),
    ),
    row(
        "Closing early Wednesday 2 hour delay Thursday",
        "early_dismissal",
        jan(21),
        schedule=(("early_dismissal", jan(21), None), ("delayed", jan(22), 120)),
    ),
    delayed("Delayed Thursday 2 hours, Friday 3 hours", jan(22), None),
    delayed("Delayed Wednesday thru Friday 2 hours, Monday 3 hours", jan(21, 22, 23), None),
    delayed("Delayed Thursday 2 hours and Friday 3 hours", jan(22, 23), None),
    delayed("Delayed 2 hours Thursday and 3 hours Friday", jan(22, 23), None),
    delayed("Delayed 2 hours Thursday & 3 hours Friday", jan(22, 23), None),
    early("Closing early Thursday 2 hours, Friday 3 hours", jan(22), None),
    early("Closing early 2 hours Thursday and 3 hours Friday", jan(22, 23), None),
    # A sentence of its own for the other day leaves the first day's length alone.
    delayed("Delayed Thursday 2 hours; Friday 3 hours", jan(22), 120),
    # The same length for each day is that length.
    delayed("Delayed 2 hours Thursday and 2 hours Friday", jan(22, 23), 120),
    # Each status with a length of its own keeps it.
    row(
        "2 hour delay Thursday, 3 hour delay Friday",
        "delayed",
        jan(22),
        delay=120,
        schedule=(("delayed", jan(22), 120), ("delayed", jan(23), 180)),
    ),
    # A length that is not a day's leaves the status's alone.
    delayed("Delayed 2 hours, buses 30 minutes behind", jan(20), 120, confidence=0.9),
    # Out of the range of a school delay: no length, as with "Delayed 10 hours Wednesday".
    delayed("Delayed Wednesday 10 hours", jan(21), None, confidence=0.8),
    # A hedge or a question still demotes the status.
    row("Delayed Wednesday 2 hours?", "other", confidence=0.3, notes=("hedged",)),
    row("Possible delay Wednesday 2 hours", "other", confidence=0.3, notes=("hedged",)),
    row("Delayed Wednesday 2 hours, if roads are icy", "other", confidence=0.3, notes=("hedged",)),
]

# A number with a half is a length, not a day number.
HALVES = [
    delayed("Delayed Wednesday 2 1/2 hours", jan(21), 150),
    delayed("Delayed Jan. 21, 2 1/2 hours", jan(21), 150),
    row(
        "Closed Wednesday 2 1/2 hour delay Thursday",
        "closed",
        jan(21),
        schedule=(("closed", jan(21), None), ("delayed", jan(22), 150)),
    ),
    row(
        "Closed Wednesday, 2 and a half hour delay Thursday",
        "closed",
        jan(21),
        schedule=(("closed", jan(21), None), ("delayed", jan(22), 150)),
    ),
    row("Closed Wednesday the 21st", "closed", jan(21)),
    row("Closed Wednesday 21", "closed", jan(21)),
]


def plain(text: str, dismissal: time) -> object:
    return row(text, "early_dismissal", jan(20), confidence=0.8, dismissal=dismissal)


def unclear(text: str) -> object:
    return row(text, "other", confidence=0.3, notes=("ambiguous",))


# A dismissal time with no word saying it is early.
DISMISSAL_TIMES = [
    plain("Dismissing at 1:00 PM", time(13)),
    plain("Dismissing at 1:15 PM", time(13, 15)),
    plain("Dismissing at 1:15", time(13, 15)),
    plain("Dismissing at 1:30 PM", time(13, 30)),
    plain("Dismissing at 1:30", time(13, 30)),
    plain("Dismissing at 12:30 PM", time(12, 30)),
    plain("Dismissing at 12:45 PM", time(12, 45)),
    plain("Dismissing at 11:15 AM", time(11, 15)),
    plain("Releasing at 1:15 PM", time(13, 15)),
    plain("Students released at 1:30", time(13, 30)),
    plain("Students will be dismissed at 1:15 PM", time(13, 15)),
    unclear("Dismissing at 1:45 PM"),
    unclear("Dismissing at 2:00"),
    unclear("Releasing at 2:15 PM"),
    unclear("Dismissal at 3:00"),
    # With a word saying it is early, any time in the school day is early (no day named: 0.9).
    row(
        "Dismissing early at 1:45",
        "early_dismissal",
        jan(20),
        confidence=0.9,
        dismissal=time(13, 45),
    ),
    row(
        "Early dismissal at 2:30 PM",
        "early_dismissal",
        jan(20),
        confidence=0.9,
        dismissal=time(14, 30),
    ),
]


@pytest.mark.parametrize("case", DELAYS_AFTER_A_DAY)
def test_a_delay_keeps_its_length_after_the_day(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", EARLY_AFTER_A_DAY)
def test_an_early_dismissal_keeps_its_length_after_the_day(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", NOT_THE_STATUS_LENGTH)
def test_a_length_of_another_status_or_day_is_not_taken(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", HALVES)
def test_a_number_with_a_half_is_a_length_not_a_day(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", DISMISSAL_TIMES)
def test_a_plain_dismissal_time_is_early_up_to_half_past_one(case: Row) -> None:
    check(case)


def test_the_tables_cover_every_form() -> None:
    tables = (DELAYS_AFTER_A_DAY, EARLY_AFTER_A_DAY, NOT_THE_STATUS_LENGTH, HALVES, DISMISSAL_TIMES)
    assert sum(map(len, tables)) >= 100


# Properties ---------------------------------------------------------------------------------

ZONES = ("America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles")
instants = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2032, 12, 31),
    timezones=st.sampled_from([ZoneInfo(name) for name in ZONES]),
)
DAYS = (
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Mon", "Tue", "Wed", "Thurs",
    "Fri", "Today", "Tomorrow", "Jan. 21", "1/21", "Wednesday, Jan. 21", "Weds.", "Tues.",
    "Wednesday thru Friday", "Monday-Wednesday", "Thursday through Friday", "1/21-1/23",
)  # fmt: skip
LENGTHS = {
    "1 Hour": 60, "2 Hours": 120, "3 Hours": 180, "90 Minutes": 90, "2 hrs": 120,
    "two hours": 120, "2 1/2 hours": 150, "45 minutes": 45, "one hour": 60,
}  # fmt: skip
DELAY_WORDS = ("Delayed", "Opening Late", "Late Start", "Delay", "Delayed Opening")
EARLY_WORDS = ("Closing Early", "Early Dismissal", "Early Release", "Dismissing Early")
SEPARATORS = (" ", ", ", " - ", ": ", " by ")


@settings(max_examples=300, deadline=None)
@given(
    word=st.sampled_from(DELAY_WORDS),
    day=st.sampled_from(DAYS),
    length=st.sampled_from(tuple(LENGTHS)),
    separator=st.sampled_from(SEPARATORS),
    upper=st.booleans(),
    posted=instants,
    tz=st.sampled_from(ZONES),
)
def test_a_delay_reads_the_same_with_the_day_before_or_after_its_length(  # noqa: PLR0913, PLR0917
    word: str,
    day: str,
    length: str,
    separator: str,
    upper: bool,
    posted: datetime,
    tz: str,
) -> None:
    between = f"{word} {day}{separator}{length}"
    after = f"{word} {length} {day}"
    if upper:
        between, after = between.upper(), after.upper()
    first = parse_status(between, posted_at=posted, tz=tz)
    second = parse_status(after, posted_at=posted, tz=tz)
    assert first.kind == second.kind
    assert first.dates == second.dates
    assert first.schedule == second.schedule
    assert first.confidence == second.confidence
    if first.kind == "delayed":
        assert first.delay_minutes == LENGTHS[length]


@settings(max_examples=300, deadline=None)
@given(
    word=st.sampled_from(EARLY_WORDS),
    day=st.sampled_from(DAYS),
    length=st.sampled_from(tuple(LENGTHS)),
    separator=st.sampled_from(SEPARATORS[:4]),
    posted=instants,
    tz=st.sampled_from(ZONES),
)
def test_an_early_dismissal_reads_the_same_with_the_day_before_or_after_its_length(  # noqa: PLR0913, PLR0917
    word: str, day: str, length: str, separator: str, posted: datetime, tz: str
) -> None:
    first = parse_status(f"{word} {day}{separator}{length}", posted_at=posted, tz=tz)
    second = parse_status(f"{word} {length} {day}", posted_at=posted, tz=tz)
    assert first.kind == second.kind
    assert first.dates == second.dates
    assert first.schedule == second.schedule
    if first.kind == "early_dismissal":
        assert first.dismissal_early_minutes == LENGTHS[length]


@settings(max_examples=200, deadline=None)
@given(
    word=st.sampled_from(DELAY_WORDS),
    first_day=st.sampled_from(DAYS[:5]),
    second_day=st.sampled_from(DAYS[:5]),
    first=st.sampled_from(tuple(LENGTHS)),
    second=st.sampled_from(tuple(LENGTHS)),
    joiner=st.sampled_from((", ", "; ", " and ", " & ")),
    posted=instants,
)
def test_a_length_for_each_of_several_days_is_never_given_to_every_day(  # noqa: PLR0913, PLR0917
    word: str,
    first_day: str,
    second_day: str,
    first: str,
    second: str,
    joiner: str,
    posted: datetime,
) -> None:
    text = f"{word} {first_day} {first}{joiner}{second_day} {second}"
    result = parse_status(text, posted_at=posted, tz=TZ)
    for entry in result.schedule:
        if len(entry.dates) > 1 or entry.kind != "delayed":
            assert entry.delay_minutes is None or LENGTHS[first] == LENGTHS[second]


@settings(max_examples=300, deadline=None)
@given(
    hour=st.integers(min_value=8, max_value=16),
    minute=st.sampled_from((0, 15, 30, 45)),
    verb=st.sampled_from(("Dismissing at", "Releasing at", "Students released at")),
    marked=st.booleans(),
)
def test_a_plain_dismissal_time_is_early_only_through_half_past_one(
    hour: int, minute: int, verb: str, *, marked: bool
) -> None:
    stated = time(hour, minute)
    shown = hour if hour <= 12 else hour - 12
    mark = (" PM" if hour >= 12 else " AM") if marked else ""
    result = parse_status(f"{verb} {shown}:{minute:02d}{mark}", posted_at=TUE, tz=TZ)
    if result.kind == "early_dismissal":
        assert result.dismissal_time is not None
        assert result.dismissal_time <= time(13, 30)
        assert result.confidence == 0.8
    else:
        assert result.kind == "other"
        assert result.dismissal_time is None
    if marked:
        # With its half of the day stated, the time is read as given.
        expected = "early_dismissal" if stated <= time(13, 30) else "other"
        assert result.kind == expected
        if expected == "early_dismissal":
            assert result.dismissal_time == stated
