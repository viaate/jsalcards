"""Days joined to a status by a hyphen or a slash, and day words that are never a posting day.

Every text here is a phrasing pattern written for these tests, not a claim about
a real school. Unless a row says otherwise, it is posted at 7:05 a.m. on Tuesday
10 March 2026 in New York, so "today" is Tuesday the 10th and "tomorrow"
Wednesday the 11th.

Four rules are held here:

* A day joined to a status by a hyphen, a dash or a slash reads as it does
  spaced out: "Closed-Wednesday", "No School-Tomorrow", "Closed/3/11",
  "eLearning-Wed" and "Wed-Closed" read as "Closed - Wednesday" does, so the
  day is never dropped for the posting day. A mark between two words that are
  not days ("e-learning", "2-hour", "K-12") or two that are ("Mon-Fri",
  "today/tomorrow") stays as it is.
* A day word the parser cannot read, joined or not, makes the listing
  ``other`` at 0.3 with the note ``unreadable_date``: a misspelling
  ("Closed-Wendsday"), a Spanish name ("Closed ma\u00f1ana"), a day letter alone
  ("Closed W"), a count of days ("Closed-2 days") or a date in a form the
  patterns do not read ("3-11/Closed").
* A day after a dash, with the status's time, length, cause or school noun,
  is the status's day ("Early Dismissal - Wednesday 1:00", "Closed - Wednesday
  due to snow"). A day that no status takes, in a heading or a clause of its
  own, keeps a status that names none from the posting day unless it is that
  day ("Closed; offices open - Wednesday").
* A run of weekday names that ends on the posting day, seen after school, is
  as much the run ending as the next one when the next starts on the next
  school day ("Closed Mon.-Fri." seen on a Friday evening): no day is stated.
"""

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from snowlight.classify import parse_status
from snowlight.classify.parse import _cached_analysis, _normalized_analysis, _read_stretches
from snowlight.classify.text import (
    MONTH_WORDS,
    NEAR_DAY_WORDS,
    WEEKDAY_NAMES,
    normalize,
    spaced_joins,
)

TZ = "America/New_York"
ZONE = ZoneInfo(TZ)
TUE = datetime(2026, 3, 10, 7, 5, tzinfo=ZONE)
THU = datetime(2026, 1, 22, 7, 0, tzinfo=ZONE)
FRI = datetime(2026, 1, 23, 8, 0, tzinfo=ZONE)
FRI_MORNING = datetime(2026, 1, 23, 7, 0, tzinfo=ZONE)
FRI_EVENING = datetime(2026, 1, 23, 19, 0, tzinfo=ZONE)
SAT = datetime(2026, 1, 24, 10, 0, tzinfo=ZONE)


NO_LENGTH = 0  # a row's delay when the listing gives none the parser can read


def mar(*days: int) -> tuple[date, ...]:
    return tuple(date(2026, 3, day) for day in days)


def jan(*days: int) -> tuple[date, ...]:
    return tuple(date(2026, 1, day) for day in days)


@dataclass(frozen=True)
class Row:
    text: str
    kind: str
    dates: tuple[date, ...]
    confidence: float
    notes: tuple[str, ...]
    posted: datetime
    delay: int | None
    dismissal: time | None


def row(  # noqa: PLR0913 - one table row
    text: str,
    kind: str,
    dates: tuple[date, ...] = (),
    *,
    confidence: float = 0.95,
    notes: tuple[str, ...] = (),
    posted: datetime = TUE,
    delay: int | None = None,
    dismissal: time | None = None,
) -> object:
    return pytest.param(
        Row(text, kind, dates, confidence, notes, posted, delay, dismissal),
        id=f"{text} @ {posted:%a %m-%d %H:%M}",
    )


def unread(text: str, *, posted: datetime = TUE) -> object:
    """A listing that names a day the parser cannot read: no day is stated."""
    return row(text, "other", confidence=0.3, notes=("unreadable_date",), posted=posted)


def check(case: Row) -> None:
    result = parse_status(case.text, posted_at=case.posted, tz=TZ)
    assert result.kind == case.kind
    assert result.dates == case.dates
    assert result.confidence == case.confidence
    assert set(case.notes) <= set(result.notes)
    if case.delay is not None:
        assert result.delay_minutes == (case.delay or None)  # (0: no length is read)
    if case.dismissal is not None:
        assert result.dismissal_time == case.dismissal
    if case.kind == "other":
        assert result.schedule == ()
    if "unreadable_date" not in case.notes:
        assert "unreadable_date" not in result.notes


# A day joined to the status by a hyphen, a dash or a slash: the day the spaced form names.
JOINED = [
    row("Closed-Wednesday", "closed", mar(11)),
    row("Closed-Wed", "closed", mar(11)),
    row("Closed-Wed.", "closed", mar(11)),
    row("Closed-Weds", "closed", mar(11)),
    row("Closed-Thursday", "closed", mar(12)),
    row("Closed-Thurs", "closed", mar(12)),
    row("Closed-Thur", "closed", mar(12)),
    row("Closed-Friday", "closed", mar(13)),
    row("Closed-Fri", "closed", mar(13)),
    row("Closed-Tomorrow", "closed", mar(11)),
    row("Closed-tmrw", "closed", mar(11)),
    row("Closed-2morrow", "closed", mar(11)),
    row("Closed-Today", "closed", mar(10)),
    row("Closed-3/11", "closed", mar(11)),
    row("Closed-3/11/26", "closed", mar(11)),
    row("Closed-Mar 11", "closed", mar(11)),
    row("Closed-March 11th", "closed", mar(11)),
    row("Closed-11th", "closed", mar(11)),
    row("Closed\u2013Wed", "closed", mar(11)),
    row("Closed\u2014Wednesday", "closed", mar(11)),
    row("Closed/Wed", "closed", mar(11)),
    row("Closed/Tomorrow", "closed", mar(11)),
    row("CLOSED-WEDNESDAY", "closed", mar(11)),
    row("No School-Wednesday", "closed", mar(11)),
    row("No School-Wed", "closed", mar(11)),
    row("No School-Tomorrow", "closed", mar(11)),
    row("No School-3/11", "closed", mar(11)),
    row("No School-Mon. 3/16", "closed", mar(16)),
    row("Remote Learning-Wednesday", "remote", mar(11)),
    row("eLearning-Wed", "remote", mar(11)),
    row("NTI-Tomorrow", "remote", mar(11)),
    row("AMI Day-Wednesday", "remote", mar(11)),
    row("Remote-Wed", "remote", mar(11), confidence=0.9),
    row("2 Hr Delay-Thurs", "delayed", mar(12), delay=120),
    row("2-Hour Delay-Wednesday", "delayed", mar(11), delay=120),
    row("Two Hour Delay/Thursday", "delayed", mar(12), delay=120),
    row("Delayed-Wednesday 2 Hours", "delayed", mar(11), delay=120),
    row("Early Dismissal-Wed 1:00", "early_dismissal", mar(11), dismissal=time(13, 0)),
    row("Early Release-Wed @ 1:00", "early_dismissal", mar(11), dismissal=time(13, 0)),
    row("Closed-Wed & Thurs", "closed", mar(11, 12)),
    row("Closed-Wed/Thurs", "closed", mar(11, 12)),
    row("Closed-Wednesday-Thursday", "closed", mar(11, 12)),
    row("Closed-This Afternoon", "early_dismissal", mar(10), confidence=0.8),
    row("Closed-Until Further Notice", "closed", mar(10), confidence=0.9),
    # The day first.
    row("Wed-Closed", "closed", mar(11)),
    row("Wed.-Closed", "closed", mar(11)),
    row("Tomorrow-Closed", "closed", mar(11)),
    row("Wednesday-No School", "closed", mar(11)),
    row("3/11-Closed", "closed", mar(11)),
    # Two ways of naming the day, joined: they must agree.
    row("Closed Wed-3/11", "closed", mar(11)),
    # A day word joined to a date it disagrees with: neither can be trusted.
    row("Closed today/3/11", "other", confidence=0.3, notes=("date_mismatch",)),
    row("Closed today-11th", "other", confidence=0.3, notes=("date_mismatch",)),
    row("Closed Wed-12th", "other", confidence=0.3, notes=("date_mismatch",)),
    # A clock time joined to the day.
    row("Opening at 10:00-11th", "delayed", mar(11)),
    row("Early dismissal 1:00-3/11", "early_dismissal", mar(11), dismissal=time(13, 0)),
    # Posted on a Thursday and on a Friday morning.
    row("No School-Tomorrow", "closed", jan(23), posted=THU),
    row("Closed/Tomorrow", "closed", jan(23), posted=THU),
    row("Closed-1/26", "closed", jan(26), posted=THU),
    row("Closed-Jan 26", "closed", jan(26), posted=THU),
    row("Closed-Monday", "closed", jan(26), posted=FRI),
    row("Closed - Monday", "closed", jan(26), posted=FRI),
]

# A mark between two words that are not days, or between two days, stays as it is.
UNCHANGED = [
    row("E-Learning Day", "remote", mar(10), confidence=0.9),
    row("2-Hour Delay", "delayed", mar(10), confidence=0.9, delay=120),
    row("1.5-hour delay", "delayed", mar(10), confidence=0.9, delay=90),
    row("Closed K-12", "closed", mar(10), confidence=0.9),
    row("Non-traditional learning day", "remote", mar(10), confidence=0.9),
    row("Grades 6-8/closed", "other", confidence=0.9, notes=("partial_program",)),
    row("Closed 1st-3rd grades", "other", confidence=0.9, notes=("partial_program",)),
    row(
        "After-school activities cancelled",
        "other",
        confidence=0.9,
        notes=("activities_cancelled",),
    ),
    row("Half-day kindergarten", "other", confidence=0.9, notes=("partial_program",)),
    row("Half day kindergarten", "other", confidence=0.9, notes=("partial_program",)),
    row("Closed Wed-Fri", "closed", mar(11, 12, 13)),
    row("Closed today/tomorrow", "closed", mar(10, 11)),
    row("Closed Jan-26th", "closed", jan(26), posted=THU),
]

# A day word the parser cannot read: the status could be for that day, so none is stated.
UNREAD = [
    unread("Closed manana"),
    unread("Closed ma\u00f1ana"),
    unread("Closed-Ma\u00f1ana"),
    unread("No school ma\u00f1ana"),
    unread("Closed lunes"),
    unread("Closed mi\u00e9rcoles"),
    unread("Closed W"),
    unread("Closed-W"),
    unread("Closed W."),
    unread("Closed, W"),
    unread("Closed: W"),
    unread("Closed - W"),
    unread("Closed (W)"),
    unread("Closed Th"),
    unread("No School - T"),
    unread("Remote Learning F"),
    unread("W: Closed"),
    unread("Closed-Wendsday"),
    unread("Closed-Wendesday"),
    unread("Closed-Thrusday"),
    unread("No School-Wensday"),
    unread("Closed-January"),
    unread("Closed-Jan"),
    unread("Closed-mid-Jan"),
    unread("Closed-Next Week"),
    unread("Closed-last Monday"),
    unread("Closed-day after tomorrow"),
    unread("Closed-2 days"),
    unread("Closed-3-days"),
    unread("Closed-several days"),
    unread("Closed-Sat"),
    unread("Closed-3-11"),
    unread("Closed-3.11"),
    unread("3-11/Closed"),
    unread("3.11/Closed"),
    unread("Early Dismissal 3.11"),
    unread("Early dismissal 1:00-3-11"),
    unread("Closed-11 March"),
]

# A day after a dash, with the status's time, length, cause or school noun: the status's day.
AFTER_A_DASH = [
    row("Early Dismissal - Wednesday 1:00", "early_dismissal", mar(11), dismissal=time(13, 0)),
    row("Early Dismissal - Wednesday at 1 PM", "early_dismissal", mar(11), dismissal=time(13, 0)),
    row("Early Release - Wed @ 1:00", "early_dismissal", mar(11), dismissal=time(13, 0)),
    row("Early Dismissal 11th", "early_dismissal", mar(11)),
    row("Delayed - Wednesday 2 Hours", "delayed", mar(11), delay=120),
    row("Delayed - Wednesday, 2 hours", "delayed", mar(11), delay=120),
    row("Closing early - Wednesday 2 hours", "early_dismissal", mar(11)),
    row("Opening late - Wednesday 10 AM", "delayed", mar(11), confidence=0.9),
    row("Closed - Wednesday due to snow", "closed", mar(11)),
    row("Closed-Wednesday due to snow", "closed", mar(11)),
    row("Closed, Wednesday for students", "closed", mar(11)),
    row("Closed - Tomorrow due to icy roads", "closed", mar(11)),
    row("Closed. Wednesday due to snow.", "closed", mar(11)),
    row("Closed - Wednesday per the board", "closed", mar(11)),
    # A day of its own, with a time or a length, is no day of a status that names one.
    row("Delayed Thursday 2 hours, Friday 3 hours", "delayed", mar(12)),
    # A date or a day number, a slash or a hyphen, and a length: the length is the status's.
    row("3/11/2 Hour Delay", "delayed", mar(11), delay=120),
    row("11th-2 Hour Delay", "delayed", mar(11), delay=120),
    row("3/11-2 hour delay", "delayed", mar(11), delay=120),
    # A half: "1/2 hour" is half an hour, "2 1/2" two and a half; "11/2 hour" could be "1 1/2"
    # or a date, so no length is read from it, and "Mar 11/2" keeps its day.
    row("1/2 hour delay", "delayed", mar(10), confidence=0.9, delay=30),
    row("2 1/2 hour delay", "delayed", mar(10), confidence=0.9, delay=150),
    row("1-1/2 hour delay", "delayed", mar(10), confidence=0.9, delay=90),
    row("11/2 hour delay", "delayed", mar(10), confidence=0.9, delay=NO_LENGTH),
    row("Mar 11/2 Hour Delay", "delayed", mar(11), confidence=0.9, delay=NO_LENGTH),
]

# A day that no status takes keeps a status that names none from the posting day.
SIDE_DAYS = [
    row("Closed; offices open - Wednesday", "other", confidence=0.3, notes=("undated",)),
    row("Closed; offices open, Wednesday", "other", confidence=0.3, notes=("undated",)),
    row("Closed; offices open (Wednesday)", "other", confidence=0.3, notes=("undated",)),
    row("Closed; offices open: Tomorrow", "other", confidence=0.3, notes=("undated",)),
    row("Closed; offices open 3/11", "other", confidence=0.3, notes=("undated",)),
    row("Closed; offices open 11th", "other", confidence=0.3, notes=("undated",)),
    row("Wednesday Afternoon: UPDATE; Closed", "other", confidence=0.3, notes=("undated",)),
    row(
        "Wednesday Afternoon: Day services, Skills Training and Career Connection Ctr classes "
        "cancelled",
        "other",
        confidence=0.3,
        notes=("undated",),
    ),
    # The posting day among the days named, or a day that is no status's.
    row("Closed; offices open 3/10", "closed", mar(10), confidence=0.9),
    row("2 hour delay; students are off Friday", "delayed", mar(10), confidence=0.9, delay=120),
    row("Closed. Back on Monday", "closed", mar(10), confidence=0.9),
    row("Closed. School resumes Monday", "closed", mar(10), confidence=0.9),
    row("Closed; make-up day Friday", "closed", mar(10), confidence=0.9),
    row("Closed - back on Monday", "closed", mar(10), confidence=0.9),
    row("Closed, school resumes Monday", "closed", mar(10), confidence=0.9),
    row("Closed - make-up day Friday", "closed", mar(10), confidence=0.9),
    # A day after a dash with words that are not the status's: no day can be trusted.
    row("Closed - Wednesday staff report", "other", confidence=0.3, notes=("undated",)),
    row("Weather alert Wednesday - Closed", "other", confidence=0.3, notes=("undated",)),
    # A closure or a remote day has no time to take: "at 1:00" could be when it closes.
    row("Closed. Wednesday at 1:00.", "other", confidence=0.3, notes=("undated",)),
    row("Closed - Wednesday 2 hours", "other", confidence=0.3, notes=("undated",)),
    row(
        "UPDATE: Virtual Learning - Thursday, March 12 at 1:00",
        "other",
        confidence=0.3,
        notes=("undated",),
    ),
    row("Closed; offices open. 3/11 at 1:00", "other", confidence=0.3, notes=("undated",)),
    row("Offices: Wednesday - Open; Schools: Closed", "other", confidence=0.3, notes=("undated",)),
    # When the listing was written is no rival either.
    row("Closed - updated Monday", "closed", mar(10), confidence=0.9),
]

# A day slot: the day heads what follows it, and a label before it says nothing of it.
SLOTS = [
    row("Wednesday - Closed, Thursday - Open", "closed", mar(11)),
    row("Wednesday-Closed-Thursday-Open", "closed", mar(11)),
    row("Wednesday - Closed | Thursday - Open", "closed", mar(11)),
    row("Wednesday - Closed; Thursday - Open", "closed", mar(11)),
    row(
        "Wednesday - Closed, Thursday - Evening activities cancelled",
        "closed",
        mar(11),
        notes=("activities_cancelled",),
    ),
    row("UPDATE: Wednesday - Closed", "closed", mar(11)),
    row(
        "UPDATE: Wednesday, Early dismissal at 1 PM",
        "early_dismissal",
        mar(11),
        dismissal=time(13, 0),
    ),
    row("Weather: Wed, NTI Day due to snow", "remote", mar(11)),
    row("2 hour delay. Wednesday 10 AM.", "delayed", mar(11), delay=120),
]

# The building that holds the district's offices is no school.
OFFICES = [
    row("Administration building closed", "other", confidence=0.9, notes=("offices_closed",)),
    row("Admin building closed today", "other", confidence=0.9, notes=("offices_closed",)),
    row("Administrative building closed", "other", confidence=0.9, notes=("offices_closed",)),
    row("Administration Building - Closed", "other", confidence=0.9, notes=("offices_closed",)),
    row("District administration closed", "other", confidence=0.9, notes=("offices_closed",)),
    row(
        "Schools and administration building closed",
        "closed",
        mar(10),
        confidence=0.9,
        notes=("offices_closed",),
    ),
]

# A run of weekday names that ends on the posting day, seen after school.
WEEKS = [
    row(
        "Closed Mon.-Fri.", "other", confidence=0.3, notes=("unreadable_date",), posted=FRI_EVENING
    ),
    row(
        "Closed Monday through Friday",
        "other",
        confidence=0.3,
        notes=("unreadable_date",),
        posted=FRI_EVENING,
    ),
    row(
        "Monday-Friday: Remote learning",
        "other",
        confidence=0.3,
        notes=("unreadable_date",),
        posted=FRI_EVENING,
    ),
    # Seen in the morning, the run is the one under way; seen on a Saturday, the next one.
    row("Closed Mon.-Fri.", "closed", jan(19, 20, 21, 22, 23), posted=FRI_MORNING),
    row("Closed Mon.-Fri.", "closed", jan(26, 27, 28, 29, 30), posted=SAT),
    # The next run starts later than the next school day, or the run starts on the posting day.
    row("Closed Thursday and Friday", "closed", jan(22, 23), posted=FRI_EVENING),
    row("Closed Friday", "closed", jan(23), posted=FRI_EVENING),
    row("Closed Monday through Wednesday", "closed", jan(26, 27, 28), posted=FRI_EVENING),
]


@pytest.mark.parametrize("case", JOINED + UNCHANGED + AFTER_A_DASH + SLOTS)
def test_a_joined_or_dashed_day_is_the_status_day(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", UNREAD)
def test_a_day_word_that_is_not_read_is_never_the_posting_day(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", SIDE_DAYS + OFFICES + WEEKS)
def test_a_day_no_status_takes_and_a_week_just_ending(case: Row) -> None:
    check(case)


def test_the_closed_offices_listing_says_the_offices_are_open() -> None:
    result = parse_status("Closed; administration building open", posted_at=TUE, tz=TZ)
    assert result.kind == "closed"
    assert result.offices_open


@pytest.mark.parametrize(
    ("text", "spaced"),
    [
        ("closed-wednesday", "closed - wednesday"),
        ("closed/tomorrow", "closed / tomorrow"),
        ("no school-3/11", "no school - 3/11"),
        ("e-learning-wed", "e-learning - wed"),
        ("wed-closed", "wed - closed"),
        ("3/11-closed", "3/11 - closed"),
        ("closed-next week", "closed - next week"),
        ("closed-2 days", "closed - 2 days"),
        ("opening at 10:00-11th", "opening at 10:00 - 11th"),
        ("closed today/3/11", "closed today / 3/11"),
        ("mon-fri", "mon-fri"),
        ("jan-26th", "jan-26th"),
        ("today/tomorrow", "today/tomorrow"),
        ("k-12", "k-12"),
        ("2-hour", "2-hour"),
        ("1.5-hour", "1.5-hour"),
        ("1st-3rd", "1st-3rd"),
        ("sun-valley", "sun-valley"),
        ("closed-next", "closed-next"),
        ("closed-may", "closed-may"),
        ("closed-may 4", "closed - may 4"),
        ("10:00-11:00", "10:00-11:00"),
        ("9pm-9am", "9pm-9am"),
        # A denial joined to the word before it: the "no" starts a phrase of its own.
        ("closed/no virtual", "closed / no virtual"),
        ("2 hr delay/no virtual", "2 hr delay / no virtual"),
        ("closed-no nti", "closed - no nti"),
        ("open/not delayed", "open / not delayed"),
        ("closed/none", "closed / none"),
        ("closed/no", "closed / no"),
        ("k-12/no school", "k-12 / no school"),
        ("closed/no-virtual", "closed / no virtual"),
        ("no-delay", "no delay"),
        ("open, no-delay", "open, no delay"),
        ("no-school-related", "no school-related"),
        ("nano-tech", "nano-tech"),
        ("piano-lessons", "piano-lessons"),
        ("closed tomorrow/no virtual", "closed tomorrow / no virtual"),
        # Not a denial: "yes/no" is one word, and "no" must be a word of its own.
        ("yes/no", "yes/no"),
        ("closed: yes/no", "closed: yes/no"),
        ("closed/nonsense", "closed/nonsense"),
        ("closed/notice", "closed/notice"),
        ("no/virtual", "no/virtual"),
    ],
)
def test_spaced_joins_spaces_out_only_a_mark_beside_a_day_or_a_denial(
    text: str, spaced: str
) -> None:
    assert spaced_joins(text) == spaced


def test_the_day_names_are_the_ones_the_date_patterns_read() -> None:
    from snowlight.classify import dates  # noqa: PLC0415 - the lists checked here

    assert set(WEEKDAY_NAMES) == set(dates.WEEKDAYS)
    assert set(MONTH_WORDS) == set(dates.MONTHS)
    assert set(NEAR_DAY_WORDS) == set(dates._TODAY_WORDS + dates._TOMORROW_WORDS) | {"yesterday"}


# Property tests ----------------------------------------------------------------------------

ZONES = ("America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles")
zones = st.sampled_from(ZONES)
instants = st.datetimes(
    min_value=datetime(2015, 1, 1),  # hypothesis adds the zone
    max_value=datetime(2035, 12, 31),
    timezones=st.sampled_from([ZoneInfo(name) for name in ZONES]),
)
# Statuses that end in a word, as joined listings write them.
STATUSES = (
    "Closed", "No School", "Schools Closed", "Remote Learning", "eLearning", "NTI Day",
    "AMI Day", "Virtual Learning", "2 Hour Delay", "2-Hour Delay", "Two Hour Delay",
    "Delayed", "Late Start", "Early Dismissal", "Early Release", "Snow Day",
    "Classes Cancelled", "Closed; offices open", "No Classes", "Early dismissal at 1 PM",
)  # fmt: skip
# Days the date patterns read.
DAYS = (
    "Monday", "Mon", "Tuesday", "Tues", "Wednesday", "Wed", "Weds", "Thursday", "Thurs",
    "Friday", "Fri", "Today", "Tomorrow", "tmrw", "3/11", "1/26", "12/1", "Mar 11",
    "Jan. 26", "11th", "Wed 3/11", "Wed & Thurs", "Wed-Thurs", "Tonight",
)  # fmt: skip
MONTH_DAYS = ("Mar 11", "Jan. 26")
# Days the date patterns do not read.
UNREAD_DAYS = (
    "Wendsday", "Wensday", "Thrusday", "Fridy", "Tomorrrow", "tmrow", "ma\u00f1ana", "manana",
    "lunes", "jueves", "next week", "2 days", "several days", "3-11", "3.11", "W", "Th",
    "day after tomorrow", "last Friday", "Sat",
)  # fmt: skip
MARKS = ("-", "/", "\u2013", "\u2014")


def _parse_fresh(text: str, posted: datetime, tz: str) -> object:
    _cached_analysis.cache_clear()
    _normalized_analysis.cache_clear()
    return parse_status(text, posted_at=posted, tz=tz)


@settings(max_examples=400, deadline=None)
@given(
    status=st.sampled_from(STATUSES),
    day=st.sampled_from(DAYS),
    mark=st.sampled_from(MARKS),
    day_first=st.booleans(),
    posted=instants,
    tz=zones,
)
def test_a_day_joined_by_a_mark_reads_as_the_spaced_day(  # noqa: PLR0913, PLR0917 - one text
    status: str, day: str, mark: str, day_first: bool, posted: datetime, tz: str
) -> None:
    # (A month and a day number before a slash and a length are left as they are: "Mar
    # 11/2 Hour Delay" could be "Mar 1 1/2", so the day is read and the length is not.)
    assume(not (day_first and mark == "/" and status[0].isdigit() and day in MONTH_DAYS))
    first, second = (day, status) if day_first else (status, day)
    spaced_mark = "/" if mark == "/" else "-"
    joined = _parse_fresh(f"{first}{mark}{second}", posted, tz)
    spaced = _parse_fresh(f"{first} {spaced_mark} {second}", posted, tz)
    assert joined == spaced


@settings(max_examples=400, deadline=None)
@given(
    status=st.sampled_from(STATUSES),
    day=st.sampled_from(UNREAD_DAYS),
    mark=st.sampled_from((*MARKS, " ", " - ", ", ", ": ")),
    posted=instants,
    tz=zones,
)
def test_a_day_that_is_not_read_never_gives_a_status(
    status: str, day: str, mark: str, posted: datetime, tz: str
) -> None:
    result = parse_status(f"{status}{mark}{day}", posted_at=posted, tz=tz)
    assert result.kind == "other"
    assert result.schedule == ()
    assert result.confidence <= 0.3  # (the ceiling of a listing that states no day)
    # (A letter right after "no school" can also be the noun it says no to: "ambiguous".)
    assert {"unreadable_date", "ambiguous"} & set(result.notes)


JOIN_PIECES = (
    "Closed", "No School", "e-Learning", "2-Hour", "Delay", "Wed", "Wednesday", "tomorrow",
    "today", "3/11", "3-11", "11th", "next", "week", "may", "4", "2", "days", "Jan", "26th",
    "K-12", "Mon", "Fri", "10:00", "1.5", "hour", "sun", "valley", "mid",
)  # fmt: skip
join_texts = st.lists(
    st.tuples(st.sampled_from(JOIN_PIECES), st.sampled_from(("-", "/", " ", " - ", "\u2013"))),
    min_size=1,
    max_size=6,
).map(lambda parts: "".join(piece + mark for piece, mark in parts).strip())


@settings(max_examples=600, deadline=None)
@given(text=join_texts)
def test_reading_stretch_by_stretch_normalizes_as_normalize_does(text: str) -> None:
    read = _read_stretches(text)
    if read is not None:
        assert read[0] == normalize(text)
