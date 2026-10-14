"""Weekday names that just passed: day headings in order, and a lone weekday a day or two ago.

Every text here is a phrasing pattern, not a claim about a real school. The
rows under "Archived shapes" repeat the wording of listings kept in the
project's archive of station closings pages (businesses and churches, at the
time the archive first saw them), as shapes of text only; the rest are written
for these tests. Unless a row says otherwise, times are in Chicago in January
2026: Monday the 19th to Monday the 26th.

* A closings page lists a day's slots in date order, whatever each slot says,
  a status or not: "Wednesday: Closed...... Thursday: Open on time" seen on a
  Thursday morning closed yesterday, as "Wednesday: Closed...... Thursday:
  Opening At 10:00 AM" does. So every weekday that heads a slot ("Thursday:",
  "Thursday Morning:", "Thursday Evening:") orders the days before it, and a
  heading that runs backward ("Thursday: Open...... Wednesday: Closed") makes
  the days unclear.
* A weekday name alone stands for its next occurrence. When that is 5 or 6
  days on, the one it last stood for was a day or two ago: "2-hr delay Tues."
  seen on a Thursday is most likely a listing still up after its day, and
  not a delay next week. Nothing says which, so the listing is ``other`` at
  0.3 with the note ``unreadable_date``. So is a run of weekday names that
  ends 5 or 6 days on and starts no sooner than 4 ("Closed Monday and
  Tuesday" seen on a Thursday), and a run from the posting time whose last day
  is 5 or 6 days on ("Closed through Wednesday" seen on a Thursday).
* "Next" and "coming" look ahead, and a date or a day number pins the week, so
  "Closed next Monday" and "Closed Monday, January 26" seen on a Wednesday
  stand. So does a run that starts within 3 days ("Closed Thursday through
  Monday" seen on a Wednesday) or one that started before the posting day
  ("Closed Friday and Monday" seen on a Saturday). A run that reaches the
  posting day pins its earlier days to the days just past: "Closed Tuesday and
  Wednesday" seen on a Wednesday is yesterday and today, at full confidence,
  where "Closed Tuesday" alone seen then is unclear, as no day of it is the
  posting day's. And so does a stamp that says when
  the listing was written puts its weekday names in that week. (A run that
  ends on the posting day, seen after school, when the next one would start
  on the next school day, is the exception: "Closed Mon.-Fri." seen on a
  Friday evening is the week ending or the next, so no day is stated. See
  test_classify_joined_days.py.)
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from snowlight.classify import parse_status
from snowlight.classify.parse import _raw_analysis, _weekday_lead, _with_groups

TZ = "America/Chicago"
ZONE = ZoneInfo(TZ)
UTC = ZoneInfo("UTC")
MON_EVENING = datetime(2026, 1, 19, 20, 0, tzinfo=ZONE)
TUE = datetime(2026, 1, 20, 6, 0, tzinfo=ZONE)
TUE_EVENING = datetime(2026, 1, 20, 20, 0, tzinfo=ZONE)
WED = datetime(2026, 1, 21, 6, 0, tzinfo=ZONE)
WED_NIGHT = datetime(2026, 1, 21, 23, 9, tzinfo=ZONE)
THU_OVERNIGHT = datetime(2026, 1, 22, 0, 9, tzinfo=ZONE)
THU_ONE_AM = datetime(2026, 1, 22, 1, 0, tzinfo=ZONE)
THU = datetime(2026, 1, 22, 6, 0, tzinfo=ZONE)
THU_EVENING = datetime(2026, 1, 22, 20, 0, tzinfo=ZONE)
FRI = datetime(2026, 1, 23, 6, 0, tzinfo=ZONE)
SAT = datetime(2026, 1, 24, 10, 0, tzinfo=ZONE)
SUN = datetime(2026, 1, 25, 10, 0, tzinfo=ZONE)
SUN_EVENING = datetime(2026, 1, 25, 20, 0, tzinfo=ZONE)
MON = datetime(2026, 1, 26, 6, 0, tzinfo=ZONE)


def jan(*days: int) -> tuple[date, ...]:
    return tuple(date(2026, 1, day) for day in days)


@dataclass(frozen=True)
class Row:
    text: str
    posted: datetime
    tz: str
    kind: str
    dates: tuple[date, ...]
    confidence: float
    notes: tuple[str, ...]
    schedule: tuple[tuple[str, tuple[date, ...]], ...] | None


def row(  # noqa: PLR0913 - one table row
    text: str,
    posted: datetime,
    kind: str,
    dates: tuple[date, ...] = (),
    *,
    confidence: float = 0.95,
    notes: tuple[str, ...] = (),
    tz: str = TZ,
    schedule: tuple[tuple[str, tuple[date, ...]], ...] | None = None,
) -> object:
    local = posted.astimezone(ZoneInfo(tz))
    return pytest.param(
        Row(text, posted, tz, kind, dates, confidence, notes, schedule),
        id=f"{text} @ {local:%a %Y-%m-%d %H:%M}",
    )


def past(text: str, posted: datetime, *notes: str, tz: str = TZ) -> object:
    """A listing whose weekday names most likely just passed: no day is stated."""
    return row(
        text,
        posted,
        "other",
        confidence=0.3,
        notes=tuple(sorted({*notes, "unreadable_date"})),
        tz=tz,
    )


def opened(text: str, posted: datetime, *notes: str) -> object:
    """Days just past with statuses, and the posting day open: the news is that it is open."""
    return row(text, posted, "other", confidence=0.9, notes=tuple(sorted({*notes, "superseded"})))


def check(case: Row) -> None:
    result = parse_status(case.text, posted_at=case.posted, tz=case.tz)
    assert result.kind == case.kind
    assert result.dates == case.dates
    assert result.confidence == case.confidence
    assert result.notes == case.notes
    if case.schedule is not None:
        assert [(entry.kind, entry.dates) for entry in result.schedule] == list(case.schedule)
    if case.kind == "other":
        assert result.schedule == ()
    assert result.says_open is (case.kind == "other" and "superseded" in case.notes)


# A day heading after a status's day, whatever its slot says, is a later day. Seen on a
# Thursday morning, Wednesday is yesterday. When the later slot says school is open and every
# status is past, the past is history and the news is that school runs as normal: ``other``
# at 0.9, ``says_open``, noted ``superseded`` (see test_classify_status_subjects.py).
HEADINGS = [
    opened("Wednesday: Closed...... Thursday: Open on time", THU),
    opened("Wednesday Morning: Closed | Thursday Morning: Open", THU),
    opened("Wednesday: Closed. Thursday: Normal schedule", THU),
    row(
        "Wednesday Morning: Closed | Thursday Evening: No Evening Activities",
        THU,
        "closed",
        jan(21),
        notes=("activities_cancelled",),
    ),
    row(
        "Wednesday Morning: 2 Hour Delay | Thursday Afternoon: All Activities Cancelled",
        THU,
        "delayed",
        jan(21),
        notes=("activities_cancelled",),
    ),
    row("Wednesday: Closed...... Thursday: No First Shift", THU, "closed", jan(21)),
    opened("Tuesday: Closed...... Wednesday: Closed...... Thursday: Open", THU),
    opened("Wednesday: Remote Learning Day | Thursday: Open on time", THU),
    opened("Wednesday Afternoon: Closed | Thursday Morning: Open", THU),
    opened("Wednesday: Early Dismissal at 1:00 PM...... Thursday: Normal Schedule", THU),
    opened(
        "Tuesday Evening: No Evening Activities | Wednesday: Closed | Thursday: Open",
        THU,
        "activities_cancelled",
    ),
    opened("Monday: Closed | Tuesday: Open on time", TUE),
    opened("Friday: Closed...... Monday: Open on time", MON),
    opened("Wednesday: Closed. Thursday: Closed. Friday: Open", FRI),
    # A status called off before them names no day of its own.
    opened(
        "Tuesday: 2 Hour Delay Cancelled...... Wednesday: Closed...... Thursday: Open on time",
        THU,
        "revoked",
    ),
    # Overnight, the day that has just ended is still the one the listing is about.
    row("Wednesday: Closed...... Thursday: Open on time", THU_OVERNIGHT, "closed", jan(21)),
    # Without an open slot, the days just past keep their statuses.
    row("Wednesday: Closed...... Thursday Evening: No Evening Activities", THU, "closed",
        jan(21), notes=("activities_cancelled",)),
    row("Tuesday: Closed...... Wednesday: Closed...... Thursday: No First Shift", THU,
        "closed", jan(20, 21)),
    row("Wednesday: Early Dismissal at 1:00 PM...... Thursday Evening: No Evening Activities",
        THU, "early_dismissal", jan(21), notes=("activities_cancelled",)),
    # With a status in the later slot too, each day keeps its own.
    row(
        "Wednesday: Closed...... Thursday: Opening At 10:00 AM",
        THU,
        "delayed",
        jan(22),
        schedule=(("closed", jan(21)), ("delayed", jan(22))),
    ),
    row(
        "Wednesday: NTI Day | Thursday: 2 Hour Delay",
        THU,
        "delayed",
        jan(22),
        schedule=(("remote", jan(21)), ("delayed", jan(22))),
    ),
    # Seen before the days, the same listing looks ahead.
    row("Wednesday: Closed...... Thursday: Open on time", TUE_EVENING, "closed", jan(21)),
    row("Wednesday: Closed...... Thursday: Open on time", WED, "closed", jan(21)),
    row("Friday: Closed. Monday: Closed", WED, "closed", jan(23, 26)),
    row("Thursday: Closed. Friday: Closed. Monday: Closed", WED, "closed", jan(22, 23, 26)),
    # Seen on the Friday after, both days a week on or just past: neither is stated.
    past("Wednesday: Closed...... Thursday: Open on time", FRI),
    past(
        "Wednesday Morning: Closed | Thursday Evening: No Evening Activities",
        FRI,
        "activities_cancelled",
    ),
    past("Wednesday: Closed...... Thursday: Opening At 10:00 AM", FRI),
    # A heading that runs backward: the days are unclear.
    past("Thursday: Open...... Wednesday: Closed", TUE),
    past("Thursday Morning: Normal Schedule | Wednesday Morning: Closed", TUE),
]  # fmt: skip

# Archived shapes, at the time the archive first saw them, in the station's zone.
WYFF = datetime(2014, 2, 13, 10, 27, 3, tzinfo=UTC)  # Thursday, 5:27 a.m. in Greenville, SC
WXII_THU = datetime(2014, 2, 14, 0, 48, 32, tzinfo=UTC)  # Thursday, 7:48 p.m. in Winston-Salem
WXII_SAT = datetime(2016, 1, 23, 22, 15, 54, tzinfo=UTC)  # Saturday, 5:15 p.m.
KKTV = datetime(2015, 2, 26, 6, 9, 5, tzinfo=UTC)  # Wednesday, 11:09 p.m. in Colorado Springs
WXIX = datetime(2025, 12, 15, 14, 13, 29, tzinfo=UTC)  # Monday, 9:13 a.m. in Cincinnati
WBKO = datetime(2023, 1, 3, 22, 17, tzinfo=UTC)  # Tuesday, 4:17 p.m. in Bowling Green, KY
EAST = "America/New_York"
MOUNTAIN = "America/Denver"
FEB_12_2014 = (date(2014, 2, 12),)
JAN_22_2016 = (date(2016, 1, 22),)
ARCHIVED = [
    row("Tuesday: Closed...... Wednesday: All Services Canceled...... Thursday: All Services "
        "Canceled", WYFF, "closed", (date(2014, 2, 11),), confidence=0.8, notes=("ambiguous",),
        tz=EAST),
    row("Wednesday: Closed...... Thursday: No First Shift", WYFF, "closed", FEB_12_2014, tz=EAST),
    row("Tuesday: Closed...... Wednesday: Closed...... Thursday: Opening At 2:00 PM", WYFF,
        "closed", (date(2014, 2, 11), date(2014, 2, 12)), tz=EAST),
    row("Wednesday Afternoon: Closed...... Wednesday Evening: No Third Shift...... Thursday "
        "Morning: No First Shift...... Thursday Afternoon: No Second Shift", WYFF,
        "early_dismissal", FEB_12_2014, confidence=0.8, tz=EAST),
    row("Wednesday: Closed...... Thursday: No First Shift, Normal Second Shift", WYFF, "closed",
        FEB_12_2014, tz=EAST),
    row("Wednesday: Closed...... Thursday Afternoon: Opening At 1:30 PM", WYFF, "closed",
        FEB_12_2014, tz=EAST),
    row("Wednesday: Closed...... Thursday: Opening At 2:00 PM", WYFF, "closed", FEB_12_2014,
        tz=EAST),
    row("Wednesday: Closing at 10:30am Wednesday...... Thursday: Opening at 2:30pm", WYFF,
        "early_dismissal", FEB_12_2014, tz=EAST),
    row("Tuesday Evening: No Second Shift...... Wednesday: Closed...... Thursday: No First Shift",
        WYFF, "closed", FEB_12_2014, tz=EAST),
    row("Wednesday: Closed...... Saturday: Meal Canceled, Meal Canceled", WXII_THU, "closed",
        FEB_12_2014, confidence=0.8, notes=("ambiguous",), tz=EAST),
    row("Wednesday Afternoon: Closed...... Wednesday Evening: All Events Canceled...... Thursday "
        "Evening: All Events Canceled", WXII_THU, "early_dismissal", FEB_12_2014, confidence=0.8,
        notes=("activities_cancelled",), tz=EAST),
    row("Friday: Closed...... Saturday Morning: Inclement Weather Plan In Effect...... Saturday "
        "Afternoon: Inclement Weather Plan In Effect...... Sunday: Inclement Weather Plan In "
        "Effect", WXII_SAT, "closed", JAN_22_2016, confidence=0.8, notes=("ambiguous",), tz=EAST),
    row("Friday Morning: Closed...... Friday Afternoon: Closed...... Friday Evening: Winter "
        "Weather Policy In Effect...... Saturday Morning: Inclement Weather Plan In Effect...... "
        "Saturday Afternoon: Inclement Weather Plan In Effect...... Saturday Evening: Closing at "
        "5:30 PM...... Sunday: Inclement Weather Plan In Effect", WXII_SAT, "closed", JAN_22_2016,
        confidence=0.8, notes=("ambiguous",), tz=EAST),
    row("Friday Morning: Closed, Office Closed...... Friday Afternoon: Closed, Office "
        "Closed...... Friday Evening: All Events Canceled...... Saturday Morning: All Events "
        "Canceled...... Saturday Afternoon: All Events Canceled...... Sunday: Services Canceled",
        WXII_SAT, "closed", JAN_22_2016, confidence=0.8,
        notes=("activities_cancelled", "ambiguous", "offices_closed"), tz=EAST),
    past("2-hr delay Tues.", KKTV, tz=MOUNTAIN),
    past("Closed Sunday", WXIX, tz=EAST),
    # A date pins the week, however far on: a Monday 13 days after a Tuesday.
    row("Closed Monday 01/16", WBKO, "closed", (date(2023, 1, 16),)),
]  # fmt: skip

# A weekday name alone, a day or two after it: the one just past, or the one a week on.
LONE = [
    past("2-hr delay Tues.", THU_OVERNIGHT),
    past("2-hr delay Tues.", WED_NIGHT),
    past("Closed Monday", TUE),
    past("Closed Monday", TUE_EVENING),
    past("Closed Monday", WED),
    past("Closed Tuesday", WED),  # (with "and Wednesday" it reaches today: see NEAR)
    past("Closed Friday", SAT),
    past("Closed Friday", SUN),
    past("Closed Wednesday", THU),
    past("Closed Wednesday", THU_EVENING),
    past("Closed this Monday", WED),
    past("No school Monday", WED),
    past("NTI day Tuesday", THU),
    past("Remote learning Tuesday", THU),
    past("2 hour delay Monday", WED),
    past("Early dismissal Monday at 1:00", WED),
    past("Monday: Closed", WED),
    past("Monday Morning: Closed", WED),
    past("Tuesday Morning: Closed-Flexible Instruction Day", THU),
    past("Closed Monday due to snow", WED),
    past("Closed Monday; offices open Tuesday", WED),
    past("Closed. 2 hour delay Wednesday", FRI),
    # A run that ends a day or two ago, or a week on, and starts no sooner than 4 days on.
    past("Closed Monday and Tuesday", THU),
    past("Closed Monday through Wednesday", THU),
    past("Monday: Closed. Tuesday: 2 hour delay", THU),
    past("Tuesday Evening: Closed...... Wednesday: Closed...... Thursday: Closed", SAT),
    # A run from the posting time whose last day closed was a day or two ago, or a week on.
    past("Closed through Wednesday", THU),
    past("Closed until Wednesday", THU),
]

# The days stand: they are near, the text pins the week, or the run started before.
NEAR = [
    row("2-hr delay Tues.", MON_EVENING, "delayed", jan(20)),
    row("Closed Monday", THU, "closed", jan(26)),
    row("Closed Monday", SUN_EVENING, "closed", jan(26)),
    row("Closed Monday", MON, "closed", jan(26)),
    row("Closed Friday", MON, "closed", jan(30)),
    row("Closed Friday", THU_EVENING, "closed", jan(23)),
    # Written the evening before: Wednesday is the day that has just ended.
    row("Closed Wednesday", THU_ONE_AM, "closed", jan(21)),
    row("Closed next Monday", WED, "closed", jan(26)),
    row("Closed this coming Monday", WED, "closed", jan(26)),
    row("Closed Monday, January 26", WED, "closed", jan(26)),
    row("Closed Monday the 26th", WED, "closed", jan(26)),
    row("Closed Monday 1/26", WED, "closed", jan(26)),
    row("Closed Monday - Last Updated: 01/19/2026 05:13am", WED, "closed", jan(19)),
    row("Closed Monday - Last Updated: 01/16/2026 05:13am", WED, "closed", jan(19)),
    row("Closed Monday and Tuesday", FRI, "closed", jan(26, 27)),
    row("Closed Monday and Wednesday", FRI, "closed", jan(26, 28)),
    row("Closed Thursday through Monday", WED, "closed", jan(22, 23, 26)),
    row("Closed Friday and Monday", SAT, "closed", jan(23, 26)),
    # A run that reaches the posting day: its earlier days are the days just past.
    row("Closed Tuesday and Wednesday", WED, "closed", jan(20, 21)),
    row("Closed Monday through Wednesday", WED, "closed", jan(19, 20, 21)),
    row("Closed Tuesday, Wednesday and Thursday", WED, "closed", jan(20, 21, 22)),
    row("Closed Thursday and Friday", FRI, "closed", jan(22, 23)),
    row("Closed tomorrow and Monday", THU, "closed", jan(23, 26)),
    row("Closed through Friday", THU, "closed", jan(22, 23)),
    row("Closed through Monday", FRI, "closed", jan(23, 26)),
    row("Closed until Monday", WED, "closed", jan(21, 22, 23)),
    # A heading that looks ahead pins the week for the days before it.
    row("Wednesday: Closed...... Next Thursday: Open", FRI, "closed", jan(28)),
    # Only an evening is named for a status: no school day to place.
    row("Friday Evening: Closed | Sunday Morning: Service at 10am", MON, "other",
        confidence=0.9, notes=("activities_cancelled",)),
]  # fmt: skip


@pytest.mark.parametrize("case", HEADINGS)
def test_a_day_heading_orders_the_days_before_it(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", ARCHIVED)
def test_archived_shapes_resolve_to_the_days_just_past(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", LONE)
def test_a_weekday_just_past_states_no_day(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", NEAR)
def test_a_near_or_pinned_weekday_stands(case: Row) -> None:
    check(case)


def test_the_tables_hold_enough_cases() -> None:
    assert len(HEADINGS) + len(ARCHIVED) + len(LONE) + len(NEAR) >= 80
    assert len(ARCHIVED) == 17


def test_a_delay_in_a_slot_keeps_its_length_and_time() -> None:
    result = parse_status(
        "Wednesday Morning: 2 Hour Delay | Thursday Afternoon: All Activities Cancelled",
        posted_at=THU,
        tz=TZ,
    )
    assert result.delay_minutes == 120
    opening = parse_status(
        "Wednesday: Closed...... Thursday: Opening At 10:00 AM", posted_at=THU, tz=TZ
    )
    assert opening.opens_at == time(10, 0)
    dismissal = parse_status(
        "Wednesday: Early Dismissal at 1:00 PM...... Thursday Evening: No Evening Activities",
        posted_at=THU,
        tz=TZ,
    )
    assert dismissal.dismissal_time == time(13, 0)


def test_a_status_that_names_no_day_leaves_the_week_to_the_posting_time() -> None:
    # Beside a status read from the posting time, weekday names cannot all be a week off.
    (status,) = _raw_analysis("Closed Monday")[1]
    assert _weekday_lead([status], ()) == status[9]
    assert _weekday_lead([status, _with_groups(status, ())], ()) is None


# Properties ---------------------------------------------------------------------------------

ZONES = ("America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles")
instants = st.datetimes(
    min_value=datetime(2018, 1, 1),
    max_value=datetime(2034, 12, 31),
    timezones=st.sampled_from([ZoneInfo(name) for name in ZONES]),
)
NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
STATUSES = (
    "Closed {day}", "No school {day}", "2 hour delay {day}", "{day}: Closed",
    "{day} Morning: Closed", "NTI day {day}", "Remote learning {day}", "{day}: E-Learning Day",
    "Early dismissal {day} at 1:00",
)  # fmt: skip


def ahead(weekday: int, posted: datetime, tz: str) -> int:
    """How many days after the posting day a weekday name alone falls (worked out here).

    Its next occurrence counting the posting day, or the day before it for a post
    between midnight and 4 a.m. (written the evening before).
    """
    local = posted.astimezone(ZoneInfo(tz))
    first = local.date() - timedelta(days=1 if local.hour < 4 else 0)
    return (first + timedelta(days=(weekday - first.weekday()) % 7) - local.date()).days


@settings(max_examples=400, deadline=None)
@given(
    status=st.sampled_from(STATUSES),
    weekday=st.integers(0, 4),
    posted=instants,
    tz=st.sampled_from(ZONES),
)
def test_a_weekday_alone_is_never_a_status_5_or_6_days_on(
    status: str, weekday: int, posted: datetime, tz: str
) -> None:
    text = status.format(day=NAMES[weekday])
    result = parse_status(text, posted_at=posted, tz=tz)
    local = posted.astimezone(ZoneInfo(tz)).date()
    if ahead(weekday, posted, tz) >= 5:
        assert result.kind == "other"
        assert result.confidence == 0.3
        assert "unreadable_date" in result.notes
    for entry in result.schedule:
        for day in entry.dates:
            assert -1 <= (day - local).days <= 4


@settings(max_examples=300, deadline=None)
@given(
    first=st.integers(0, 4),
    later=st.sampled_from(
        ("Open on time", "Normal Schedule", "No First Shift", "No Evening Activities")
    ),
    part=st.sampled_from(("", " Morning", " Afternoon", " Evening")),
    status=st.sampled_from(("Closed", "2 Hour Delay", "Remote Learning Day", "NTI Day")),
    posted=instants,
    tz=st.sampled_from(ZONES),
)
def test_a_slot_listing_never_puts_its_status_a_week_on(  # noqa: PLR0913, PLR0917 - drawn parts
    first: int, later: str, part: str, status: str, posted: datetime, tz: str
) -> None:
    # "Wednesday: Closed...... Thursday: Open on time": whatever the next slot says, the status
    # is on the day before the heading's day, never 5 or 6 days on.
    second = (first + 1) % 5
    text = f"{NAMES[first]}: {status}...... {NAMES[second]}{part}: {later}"
    result = parse_status(text, posted_at=posted, tz=tz)
    local = posted.astimezone(ZoneInfo(tz)).date()
    for entry in result.schedule:
        for day in entry.dates:
            assert day.weekday() == first
            assert (day - local).days <= 4
