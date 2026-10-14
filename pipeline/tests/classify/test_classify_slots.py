"""A closings page's slots for a day: "Tuesday Morning: Closed".

Every text here is a phrasing pattern written for these tests, not a claim
about a real school. Unless a row says otherwise it is posted at 6 a.m. on
Tuesday 20 January 2026 in New York, so "today" is Tuesday the 20th and
"tomorrow" Wednesday the 21st.

* Some closings pages split each day into a morning, an afternoon and an
  evening slot, head each slot's status with it and show only the slots still
  to come: "Tuesday Morning: Closed | Tuesday Afternoon: Closed | Tuesday
  Evening: Closed". The morning slot holds the school day's status, so a
  weekday's "Morning:" heading names the day, not its morning: "Tuesday
  Morning: Closed" closes Tuesday at 0.95, as "Tuesday Morning: 2 hour delay"
  delays it. A closure with remote learning in the same slot ("Tuesday Morning:
  Closed-Flexible Instruction Day") is remote learning that day at 0.95.
* The afternoon slot alone is still the afternoon: "Tuesday Afternoon: Closed"
  is an early dismissal at 0.8, as before. Beside a remote learning day in the
  day's morning slot it adds nothing: "Thursday Morning: Remote Learning Day |
  Thursday Afternoon: Closed" is remote learning on Thursday, as a delay in the
  morning slot stays a delay. A closing time in the afternoon slot ("Thursday
  Afternoon: Closing at 1:00") still conflicts with the remote day.
* The morning slot is only the morning when the day's other slots say the
  school opens later: "Tuesday Morning: Closed | Tuesday Afternoon: Opening At
  Noon" opens at noon; "... Tuesday Afternoon: Open" says nothing anyone can
  act on (``other`` at 0.3).
* Other words for the morning in a heading ("Tuesday AM:", "Tomorrow
  morning:", "Morning:") are not the slot and still say the morning.
* A day that heads an entry ("Tuesday:", "Tuesday Morning:") dates every
  status in it that adds to the one it heads: "Tuesday: Closed - NTI Day" is
  remote learning on Tuesday as stated, at 0.95.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from snowlight.classify import parse_status
from snowlight.classify.dates import find_date_groups
from snowlight.classify.dayparts import slot_heading

TZ = "America/New_York"
ZONE = ZoneInfo(TZ)
TUE = datetime(2026, 1, 20, 6, 0, tzinfo=ZONE)
TUE_NOON = datetime(2026, 1, 20, 12, 30, tzinfo=ZONE)
TUE_EVENING = datetime(2026, 1, 20, 20, 0, tzinfo=ZONE)
MON_EVENING = datetime(2026, 1, 19, 20, 0, tzinfo=ZONE)
FRI_EVENING = datetime(2026, 1, 16, 20, 0, tzinfo=ZONE)
SUN = datetime(2026, 1, 18, 15, 0, tzinfo=ZONE)


def jan(*days: int) -> tuple[date, ...]:
    return tuple(date(2026, 1, day) for day in days)


type Entry = tuple[str, tuple[date, ...]]


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
    opens_at: time | None = None,
    dismissal: time | None = None,
    reason: str | None = None,
    schedule: tuple[Entry, ...] | None = None,
) -> object:
    case = Row(
        text, posted, kind, dates, confidence, notes, delay, opens_at, dismissal, reason, schedule
    )
    return pytest.param(case, id=f"{text} @ {posted:%a %H:%M}")


def closed(  # noqa: PLR0913 - one table row
    text: str,
    dates: tuple[date, ...] = jan(20),
    *,
    posted: datetime = TUE,
    confidence: float = 0.95,
    notes: tuple[str, ...] = (),
    reason: str | None = None,
    schedule: tuple[Entry, ...] | None = None,
) -> object:
    """A closure of the days given, at 0.95 unless the row says otherwise."""
    return row(
        text,
        "closed",
        dates,
        posted=posted,
        confidence=confidence,
        notes=notes,
        reason=reason,
        schedule=schedule,
    )


def remote(
    text: str,
    dates: tuple[date, ...] = jan(20),
    *,
    posted: datetime = TUE,
    confidence: float = 0.95,
    notes: tuple[str, ...] = (),
) -> object:
    """Remote learning on the days given, at 0.95 unless the row says otherwise."""
    return row(text, "remote", dates, posted=posted, confidence=confidence, notes=notes)


def unclear(text: str, *, posted: datetime = TUE) -> object:
    return row(text, "other", posted=posted, confidence=0.3, notes=("ambiguous",))


# The morning slot closes the day it names.
CLOSED_SLOTS = [
    closed("Tuesday Morning: Closed"),
    closed("Tuesday Morning: Closed", posted=MON_EVENING),
    closed("Tuesday Morning: Closed", posted=TUE_NOON),
    closed("Wednesday Morning: Closed", jan(21)),
    closed("Wednesday Morning: Closed", jan(21), posted=TUE_EVENING),
    closed("Monday Morning: Closed", jan(19), posted=FRI_EVENING),
    closed("Monday Morning: Closed", jan(19), posted=SUN),
    closed("Friday Morning: Closed", jan(23)),
    closed("TUESDAY MORNING: CLOSED"),
    closed("tuesday morning: closed"),
    closed("Tuesday Morning:  Closed"),
    closed("Tuesday Morning:Closed"),
    closed("Tues Morning: Closed"),
    closed("Tue. Morning: Closed"),
    closed("Tuesday Morning: Closed, Workday Optional"),
    closed("Tuesday Morning: Closed, Workday Optional", posted=MON_EVENING),
    closed("Wednesday Morning: Closed, Workday Optional", jan(21), posted=TUE_EVENING),
    closed("Tuesday Morning: Closed, Staff to Report"),
    closed("Tuesday Morning: Closed, Teacher Leave"),
    closed("Tuesday Morning: Closed, Essential Personnel Only"),
    closed("Tuesday Morning: Closed, Offices Closed", notes=("offices_closed",)),
    closed("Tuesday Morning: Closed/All Activities Cancelled", notes=("activities_cancelled",)),
    closed("Tuesday Morning: Closed. No activities", notes=("activities_cancelled",)),
    closed("Tuesday Morning: Schools Closed"),
    closed("Tuesday Morning: School Closed"),
    closed("Tuesday Morning: No School"),
    closed("Tuesday Morning: Classes Cancelled"),
    closed("Tuesday Morning: All Locations Closed"),
    closed("Tuesday Morning: Closed due to snow", reason="Winter storm"),
    closed("Tuesday Morning: Closed due to icy roads", reason="Ice"),
    closed("Tuesday Morning: Closed - extreme cold", reason="Extreme cold"),
    # With a school's name or a word before it.
    closed("Lincoln Elementary - Tuesday Morning: Closed"),
    closed("Lincoln Elementary: Tuesday Morning: Closed"),
    closed("Lincoln Elementary Tuesday Morning: Closed"),
    closed("Update: Tuesday Morning: Closed"),
    # With the day's other slots.
    closed("Tuesday Morning: Closed | Tuesday Afternoon: Closed"),
    closed("Tuesday Morning: Closed...... Tuesday Afternoon: Closed"),
    closed("Tuesday Morning: Closed | Tuesday Afternoon: Closed | Tuesday Evening: Closed"),
    closed(
        "Tuesday Morning: Closed | Tuesday Evening: No evening activities",
        notes=("activities_cancelled",),
    ),
    closed(
        "Monday Evening: Closed | Tuesday Morning: Closed",
        posted=MON_EVENING,
        notes=("activities_cancelled",),
    ),
    closed("Tuesday Morning: Closed | Wednesday Morning: Closed", jan(20, 21)),
    closed("Wednesday Morning: Closed | Thursday Morning: Closed", jan(21, 22), posted=TUE_EVENING),
    closed(
        "Tuesday Morning: Closed | Wednesday Morning: 2 hour delay",
        posted=MON_EVENING,
        schedule=(("closed", jan(20)), ("delayed", jan(21))),
    ),
    closed(
        "Tuesday Morning: Closed | Tuesday Afternoon: Closed | Tuesday Evening: Closed | "
        "Wednesday Morning: Closed",
        jan(20, 21),
        posted=MON_EVENING,
    ),
]

# A closure with remote learning in the morning slot: remote learning that day.
REMOTE_SLOTS = [
    remote("Tuesday Morning: Closed-Flexible Instruction Day"),
    remote("Tuesday Morning: Closed-Flexible Instruction Day", posted=MON_EVENING),
    remote("Wednesday Morning: Closed-Flexible Instruction Day", jan(21)),
    remote("Wednesday Morning: Closed-Flexible Instruction Day", jan(21), posted=TUE_EVENING),
    remote("Monday Morning: Closed-Flexible Instruction Day", jan(19), posted=SUN),
    remote("Tuesday Morning: Closed - Flexible Instruction Day"),
    remote("Tuesday Morning: Closed, Flexible Instruction Day"),
    remote("Tuesday Morning: Closed-FID"),
    remote("TUESDAY MORNING: CLOSED-FLEXIBLE INSTRUCTION DAY"),
    remote("Tuesday Morning: In classes canceled,activate remote learning"),
    remote("Tuesday Morning: In classes canceled, activate remote learning"),
    remote("Tuesday Morning: In classes canceled,activate remote learning", posted=MON_EVENING),
    remote("Wednesday Morning: In classes canceled,activate remote learning", jan(21)),
    remote("Tuesday Morning: Closed - NTI Day"),
    remote("Tuesday Morning: Closed, AMI Day"),
    remote("Tuesday Morning: Closed, eLearning Day"),
    remote("Tuesday Morning: Closed - Virtual Learning Day"),
    remote("Tuesday Morning: Closed; Blizzard Bag Day"),
    remote("Tuesday Morning: Remote Learning Day"),
    remote("Tuesday Morning: E-Learning Day"),
    remote(
        "Tuesday Morning: Closed-Flexible Instruction Day | "
        "Tuesday Afternoon: Closed-Flexible Instruction Day"
    ),
    remote(
        "Tuesday Morning: In classes canceled,activate remote learning | "
        "Tuesday Afternoon: In classes canceled,activate remote learning"
    ),
    remote(
        "Tuesday Morning: Closed-Flexible Instruction Day | Tuesday Evening: No Evening Activities",
        notes=("activities_cancelled",),
    ),
    remote("Tuesday Morning: Closed | Tuesday Afternoon: Remote Learning Day"),
    remote("Lincoln Elementary - Tuesday Morning: Closed-Flexible Instruction Day"),
]

# A remote learning day's afternoon slot, closed: the day is remote.
REMOTE_AFTERNOONS = [
    remote("Tuesday Morning: Remote Learning Day | Tuesday Afternoon: Closed"),
    remote("Tuesday Morning: Remote Learning Day | Tuesday Afternoon: Closed", posted=MON_EVENING),
    remote(
        "Thursday Morning: Remote Learning Day | Thursday Afternoon: Closed",
        jan(22),
        posted=TUE_EVENING,
    ),
    remote("Wednesday Morning: Remote Learning Day | Wednesday Afternoon: Closed", jan(21)),
    remote(
        "Friday Morning: Virtual Learning Day | Friday Afternoon: Closed",
        jan(16),
        posted=datetime(2026, 1, 16, 6, 0, tzinfo=ZONE),
    ),
    remote(
        "Tuesday Morning: Remote Learning Day | Tuesday Afternoon: Closed | "
        "Tuesday Evening: No Evening Activities",
        notes=("activities_cancelled",),
    ),
    remote("Tuesday Morning: Closed-Flexible Instruction Day | Tuesday Afternoon: Closed"),
    remote("Tuesday Morning: NTI Day | Tuesday Afternoon: Closed"),
    remote("Tuesday Morning: E-Learning Day | Tuesday Afternoon: Closed"),
    remote("Tuesday Morning: Virtual Only | Tuesday Afternoon: Closed", confidence=0.9),
    remote("Tuesday: Remote Learning Day | Tuesday Afternoon: Closed"),
    remote("TUESDAY MORNING: REMOTE LEARNING DAY | TUESDAY AFTERNOON: CLOSED"),
    remote(
        "Sunday Morning: Remote Learning Day | Sunday Afternoon: Closed",
        jan(18),
        posted=datetime(2026, 1, 17, 10, 0, tzinfo=ZONE),
        confidence=0.7,
        notes=("weekend",),
    ),
    # Another day's afternoon slot is that day's early dismissal.
    row(
        "Tuesday Morning: Remote Learning Day | Wednesday Afternoon: Closed",
        "remote",
        jan(20),
        schedule=(("remote", jan(20)), ("early_dismissal", jan(21))),
    ),
    # A closing time in the afternoon slot, or a closure bounded again, still conflicts.
    row(
        "Tuesday Morning: Remote Learning Day | Tuesday Afternoon: Closing at 1:00",
        "other",
        confidence=0.25,
        notes=("conflict",),
    ),
    row(
        "Tuesday Morning: Remote Learning Day | Tuesday Afternoon: Closed PM",
        "other",
        confidence=0.25,
        notes=("conflict",),
    ),
]

# The same slot with a delay, or with a later slot that says when school opens.
DELAYED_SLOTS = [
    row("Tuesday Morning: 2 hour delay", "delayed", jan(20), delay=120),
    row("Tuesday Morning: 2 Hour Delay", "delayed", jan(20), posted=MON_EVENING, delay=120),
    row("Tuesday Morning: Opening At 10:00 AM", "delayed", jan(20), opens_at=time(10)),
    row("Tuesday Morning: Closed until 10", "delayed", jan(20), opens_at=time(10)),
    row(
        "Tuesday Morning: Closed | Tuesday Afternoon: Opening At Noon",
        "delayed",
        jan(20),
        opens_at=time(12),
    ),
    row(
        "Tuesday Morning: Closed | Tuesday Afternoon: Opening At 1:00 PM",
        "delayed",
        jan(20),
        opens_at=time(13),
    ),
    row(
        "Wednesday Morning: Closed | Wednesday Afternoon: Opening At Noon",
        "delayed",
        jan(21),
        posted=TUE_EVENING,
        opens_at=time(12),
    ),
    row("Tuesday Morning: Closed, reopening at 11", "delayed", jan(20), opens_at=time(11)),
]

# Still part of the day, or no slot at all.
NOT_THE_WHOLE_DAY = [
    row("Tuesday Afternoon: Closed", "early_dismissal", jan(20), confidence=0.8),
    row("Wednesday Afternoon: Closed", "early_dismissal", jan(21), confidence=0.8),
    row(
        "Tuesday Afternoon: Closed | Tuesday Evening: Closed",
        "early_dismissal",
        jan(20),
        confidence=0.8,
    ),
    row(
        "Tuesday Afternoon: Closed | Wednesday Morning: Closed",
        "early_dismissal",
        jan(20),
        posted=TUE_NOON,
        confidence=0.8,
        schedule=(("early_dismissal", jan(20)), ("closed", jan(21))),
    ),
    unclear("Tuesday AM: Closed"),
    unclear("Tue. AM: Closed"),
    unclear("Tomorrow morning: Closed"),
    unclear("This morning: Closed"),
    unclear("Morning: Closed"),
    unclear("Next Tuesday morning: Closed"),
    unclear("Closed Tuesday morning"),
    unclear("Tuesday Morning: Closed AM"),
    unclear("Tuesday Morning: Closed for the morning"),
    # A date, or several days, before "Morning:" is no slot of a closings page.
    unclear("Tuesday, Jan. 20 Morning: Closed"),
    unclear("Jan. 20 Morning: Closed"),
    unclear("Tuesday and Wednesday Morning: Closed"),
    # The day's other slot opens the school, with no time to act on.
    unclear("Tuesday Morning: Closed | Tuesday Afternoon: Open"),
    unclear("Tuesday Morning: Closed | Tuesday Afternoon: Reopening"),
    unclear("Tuesday Morning: Closed | Tuesday Afternoon: Opening At 3:00 PM"),
    unclear("Tuesday Morning: Closed | Tuesday Afternoon: Classes resume"),
]

# A closure with words of its own for the day: the slot heading only names the day, as
# "Tuesday:" would.
OWN_WORDS = [
    row(
        "Tuesday Morning: Closed after 11:30",
        "early_dismissal",
        jan(20),
        dismissal=time(11, 30),
    ),
    row("Tuesday Morning: Closed at noon", "early_dismissal", jan(20), dismissal=time(12)),
    row("Tuesday Morning: Closing At 11:30 AM", "early_dismissal", jan(20), dismissal=time(11, 30)),
    row(
        "Tuesday Morning: Closing At 11:30 AM | Tuesday Afternoon: Closed",
        "early_dismissal",
        jan(20),
        dismissal=time(11, 30),
    ),
    row("Tuesday Morning: Closed PM", "early_dismissal", jan(20), confidence=0.8),
    closed("Tuesday Morning: Closed today"),
    closed("Tuesday Morning: Closed Tuesday"),
    row("Tuesday Morning: Closed tomorrow", "other", confidence=0.3, notes=("date_mismatch",)),
    row(
        "Tuesday Morning: Closed after 5 PM",
        "other",
        confidence=0.9,
        notes=("activities_cancelled",),
    ),
    row(
        "Tuesday Morning: Closed AM kindergarten",
        "other",
        confidence=0.9,
        notes=("partial_program",),
    ),
]

# What the slot holds that is no school closure, or not one yet.
QUALIFIED = [
    row("Tuesday Morning: Possibly closed", "other", confidence=0.3, notes=("hedged",)),
    row("Tuesday Morning: Closed?", "other", confidence=0.3, notes=("hedged",)),
    row("Tuesday Morning: Closed if roads are icy", "other", confidence=0.3, notes=("hedged",)),
    row("Tuesday Morning: Closure cancelled", "other", confidence=0.9, notes=("revoked",)),
    row("Tuesday Morning: No closure", "other", confidence=0.9, notes=("negated",)),
    row("Tuesday Morning: No AM Kindergarten", "other", confidence=0.9, notes=("partial_program",)),
    row(
        "Tuesday Morning: All activities cancelled",
        "other",
        confidence=0.9,
        notes=("activities_cancelled",),
    ),
    row(
        "Tuesday Morning: Evening activities cancelled",
        "other",
        confidence=0.9,
        notes=("activities_cancelled",),
    ),
    row(
        "Tuesday Morning: Closed-Flexible Instruction Day | Tuesday Afternoon: Early dismissal",
        "other",
        confidence=0.25,
        notes=("conflict",),
    ),
]

# A day heading an entry dates every status in it that adds to the one it heads.
HEADED_ENTRIES = [
    remote("Tuesday: Closed-Flexible Instruction Day"),
    remote("Tuesday: Closed - NTI Day"),
    remote("Tuesday: Closed, remote learning"),
    remote("Tuesday: In classes canceled, activate remote learning"),
    remote("Wednesday: Closed - NTI Day", jan(21), posted=TUE_EVENING),
    remote("Lincoln Elementary Tuesday: Closed - NTI Day"),
    row(
        "Tuesday: 2 hour delay, early dismissal at 1:00",
        "delayed",
        jan(20),
        delay=120,
        dismissal=time(13),
    ),
    # Without a heading, the day reaches the second status by inference only.
    remote("Closed tomorrow. NTI day.", jan(21), confidence=0.9),
    # A heading does not date the status of another entry.
    row(
        "Tuesday: Closed | Wednesday: NTI Day",
        "closed",
        jan(20),
        posted=MON_EVENING,
        schedule=(("closed", jan(20)), ("remote", jan(21))),
    ),
]


def check(case: Row) -> None:
    result = parse_status(case.text, posted_at=case.posted, tz=TZ)
    assert result.kind == case.kind
    assert result.dates == case.dates
    assert result.confidence == case.confidence
    assert set(case.notes) <= set(result.notes)
    assert result.delay_minutes == case.delay
    assert result.opens_at == case.opens_at
    assert result.dismissal_time == case.dismissal
    if case.reason is not None:
        assert result.reason == case.reason
    if case.kind == "other":
        assert result.schedule == ()
        assert not result.says_open
    if case.schedule is not None:
        assert tuple((entry.kind, entry.dates) for entry in result.schedule) == case.schedule


@pytest.mark.parametrize("case", CLOSED_SLOTS)
def test_the_morning_slot_closes_the_day(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", REMOTE_SLOTS)
def test_the_morning_slot_with_remote_learning_is_remote_learning(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", REMOTE_AFTERNOONS)
def test_a_remote_learning_day_s_closed_afternoon_slot_adds_nothing(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", DELAYED_SLOTS)
def test_the_morning_slot_with_an_opening_is_a_late_start(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", NOT_THE_WHOLE_DAY)
def test_other_morning_headings_and_the_afternoon_slot_stay_part_of_the_day(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", OWN_WORDS)
def test_a_closure_with_its_own_words_for_the_day_reads_the_slot_as_a_day(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", QUALIFIED)
def test_a_qualified_slot(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", HEADED_ENTRIES)
def test_a_heading_dates_every_status_of_its_entry(case: Row) -> None:
    check(case)


def test_the_tables_cover_every_form() -> None:
    tables = (
        CLOSED_SLOTS, REMOTE_SLOTS, REMOTE_AFTERNOONS, DELAYED_SLOTS, NOT_THE_WHOLE_DAY,
        OWN_WORDS, QUALIFIED,
    )  # fmt: skip
    assert sum(map(len, tables)) + len(HEADED_ENTRIES) >= 100


# Properties ---------------------------------------------------------------------------------

ZONES = ("America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles")
instants = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2032, 12, 31),
    timezones=st.sampled_from([ZoneInfo(name) for name in ZONES]),
)
WEEKDAYS = {
    "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3, "Friday": 4, "Mon": 0,
    "Tues": 1, "Wed": 2, "Thurs": 3, "Fri": 4,
}  # fmt: skip
CLOSURES = ("Closed", "No school", "Classes cancelled", "Schools closed", "All Locations Closed")
SIDE_NOTES = (
    "", ", Workday Optional", "/All Activities Cancelled", ". No activities", ", Staff to Report",
    ", Offices Closed",
)  # fmt: skip
REMOTE = (
    "-Flexible Instruction Day", " - NTI Day", ", eLearning Day", ", AMI Day",
    " - Virtual Learning Day", ", activate remote learning",
)  # fmt: skip
CAUSES = ("", " due to snow", " because of icy roads")


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


@settings(max_examples=300, deadline=None)
@given(
    day=st.sampled_from(tuple(WEEKDAYS)),
    closure=st.sampled_from(CLOSURES),
    note=st.sampled_from(SIDE_NOTES),
    cause=st.sampled_from(CAUSES),
    upper=st.booleans(),
    posted=instants,
    tz=st.sampled_from(ZONES),
)
def test_a_morning_slot_closure_closes_that_weekday(  # noqa: PLR0913, PLR0917
    day: str, closure: str, note: str, cause: str, upper: bool, posted: datetime, tz: str
) -> None:
    text = f"{day} Morning: {closure}{note}{cause}"
    result = parse_status(text.upper() if upper else text, posted_at=posted, tz=tz)
    if just_passed(WEEKDAYS[day], posted, tz):
        assert result.kind == "other"
        assert "unreadable_date" in result.notes
        return
    assert result.kind in {"closed", "other"}
    assert result.schedule
    for entry in result.schedule:
        assert entry.kind == "closed"
        assert all(named.weekday() == WEEKDAYS[day] for named in entry.dates)


@settings(max_examples=300, deadline=None)
@given(
    day=st.sampled_from(tuple(WEEKDAYS)),
    closure=st.sampled_from(("Closed", "In classes canceled")),
    learning=st.sampled_from(REMOTE),
    posted=instants,
    tz=st.sampled_from(ZONES),
)
def test_a_morning_slot_closure_with_remote_learning_is_remote_that_weekday(
    day: str, closure: str, learning: str, posted: datetime, tz: str
) -> None:
    result = parse_status(f"{day} Morning: {closure}{learning}", posted_at=posted, tz=tz)
    if just_passed(WEEKDAYS[day], posted, tz):
        assert result.kind == "other"
        assert "unreadable_date" in result.notes
        return
    assert result.kind == "remote"
    for entry in result.schedule:
        assert entry.kind == "remote"
        assert all(named.weekday() == WEEKDAYS[day] for named in entry.dates)


@settings(max_examples=200, deadline=None)
@given(
    day=st.sampled_from(tuple(WEEKDAYS)),
    closure=st.sampled_from(CLOSURES),
    later=st.sampled_from(("Open", "Reopening", "Opening At Noon", "Opening At 1:00 PM")),
    posted=instants,
    tz=st.sampled_from(ZONES),
)
def test_a_morning_slot_the_day_opens_after_is_never_a_closure(
    day: str, closure: str, later: str, posted: datetime, tz: str
) -> None:
    text = f"{day} Morning: {closure} | {day} Afternoon: {later}"
    result = parse_status(text, posted_at=posted, tz=tz)
    assert result.kind in {"delayed", "other"}
    assert all(entry.kind == "delayed" for entry in result.schedule)


@settings(max_examples=200, deadline=None)
@given(
    day=st.sampled_from(tuple(WEEKDAYS)),
    learning=st.sampled_from(
        ("Remote Learning Day", "Closed-Flexible Instruction Day", "NTI Day", "E-Learning Day")
    ),
    evening=st.booleans(),
    posted=instants,
    tz=st.sampled_from(ZONES),
)
def test_a_remote_learning_day_with_a_closed_afternoon_slot_is_remote_that_weekday(
    day: str, learning: str, evening: bool, posted: datetime, tz: str
) -> None:
    text = f"{day} Morning: {learning} | {day} Afternoon: Closed"
    if evening:
        text += f" | {day} Evening: No Evening Activities"
    result = parse_status(text, posted_at=posted, tz=tz)
    if just_passed(WEEKDAYS[day], posted, tz):
        assert result.kind == "other"
        assert "unreadable_date" in result.notes
        return
    assert result.kind == "remote"
    assert len(result.schedule) == 1
    assert all(named.weekday() == WEEKDAYS[day] for named in result.schedule[0].dates)


@pytest.mark.parametrize(
    ("text", "slot"),
    [
        ("tuesday afternoon: closed", True),
        ("tues afternoon:closed", True),
        ("tuesday morning: remote | tuesday afternoon: closed", True),
        ("tuesday morning: closed", False),
        ("this afternoon: closed", False),
        ("tuesday pm: closed", False),
        ("tuesday afternoon closed", False),
    ],
)
def test_an_afternoon_slot_heading_is_one_weekday_before_afternoon(text: str, slot: bool) -> None:
    groups = find_date_groups(text)
    assert groups
    assert slot_heading(text, groups[-1], "afternoon") is slot


@pytest.mark.parametrize(
    ("text", "slot"),
    [
        ("tuesday morning: closed", True),
        ("tues morning: closed", True),
        ("tuesday morning:closed", True),
        ("update: tuesday morning: closed", True),
        ("lincoln elementary tuesday morning: closed", True),
        ("tuesday, jan. 20 morning: closed", False),
        ("tuesday and wednesday morning: closed", False),
        ("tuesday evening: closed", False),
        ("tuesday am: closed", False),
        ("tuesday morning closed", False),
        ("next tuesday morning: closed", False),
        ("tomorrow morning: closed", False),
        ("closed tuesday morning: roads", False),
    ],
)
def test_a_slot_heading_is_one_weekday_before_morning_at_the_start_of_an_entry(
    text: str, slot: bool
) -> None:
    groups = find_date_groups(text)
    assert groups
    assert slot_heading(text, groups[0]) is slot
