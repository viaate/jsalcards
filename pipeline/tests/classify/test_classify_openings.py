"""A closure beside a word that school is open, or reopens, on one of its days.

Every text here is a phrasing pattern written for these tests, not a claim about
a real school. Unless a row says otherwise it is posted at 6 a.m. on Wednesday
21 January 2026 in Chicago, so "today" is Wednesday the 21st, "tomorrow"
Thursday the 22nd and "Friday" the 23rd.

* An open day after the closure takes that day from it: "Closed Thursday and
  Friday. Open Friday." is closed on Thursday. With a word that marks it as an
  update ("Update: open Friday", "Correction: ...") the closure's other days
  stand at 0.95; with none they are a judgment call, at 0.8. Noted
  ``superseded``. So does a day the school reopens or resumes on ("We will
  reopen Friday", "Classes resume Friday"), a day students return or classes
  are held on ("Students return Friday", "Back to school Friday", "Classes will
  be held Friday"), and a day named in another way ("Open tomorrow" posted on a
  Wednesday is Thursday). Staff returning, a return denied ("will not return
  until Monday") and "Check back Friday" are no return to school.
* A closure left with no day by it ("Closed tomorrow. Open tomorrow."), an open
  day before the closure ("Open tomorrow. Closed tomorrow.") and a day named open
  and closed in one breath ("Update: open today, Today: Closed") say nothing for
  sure: ``other`` at 0.25, noted ``conflict``. A closure marked as the update
  ("Open tomorrow. Update: closed tomorrow.") stands.
* A status denied on a day it names ("Update: tomorrow is not closed", "Not
  closed Friday", "no closure tomorrow", "Closed today but not tomorrow",
  "Update: not tomorrow", "Update: no delay tomorrow") takes that day from the
  statuses of its kind as an open day does, and before a status it contradicts
  it. It leaves a status of another kind standing ("NTI day tomorrow - school is
  not closed tomorrow"), and so does a delay of another length denied ("not a 3
  hour delay") or something else's status ("No buses delayed tomorrow").
* A school of the district open on a day of the closure ("Lincoln Elementary open
  Friday") leaves the district no one status: ``other`` at 0.9, noted
  ``partial_program``.
* A reopening that is only possible ("may reopen Friday", "reopening Friday
  weather permitting", "Reopen Friday?") or a decision to come ("will reassess
  Thursday", for the days after it) leaves those days out, and the closure's
  other days at 0.8, noted ``hedged``.
* An open office, a school open for staff only, buildings, part of the district,
  activities resuming, a service ("The portal will be open Friday for
  assignments", "Open Friday for students who need meals", "Update: open today
  for meal pickup") and a day the closure does not name change nothing; nor
  does an update that opens the buildings ("Update: buildings open today").
* A weekday and a date that disagree ("Thursday 1/23", when the 23rd is a
  Friday) give no day anyone can trust: ``other`` at 0.3, noted
  ``date_mismatch``.
"""

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from snowlight.classify import parse_status

TZ = "America/Chicago"
ZONE = ZoneInfo(TZ)
WED = datetime(2026, 1, 21, 6, 0, tzinfo=ZONE)
WED_EVENING = datetime(2026, 1, 21, 20, 0, tzinfo=ZONE)
MON = datetime(2026, 1, 19, 6, 0, tzinfo=ZONE)
THU = datetime(2026, 1, 22, 6, 0, tzinfo=ZONE)
NEW_YEARS_EVE = datetime(2026, 12, 31, 6, 0, tzinfo=ZONE)


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


def row(  # noqa: PLR0913 - one table row
    text: str,
    kind: str,
    dates: tuple[date, ...],
    confidence: float,
    notes: tuple[str, ...] = (),
    *,
    posted: datetime = WED,
) -> object:
    case = Row(text, kind, dates, confidence, notes, posted)
    return pytest.param(case, id=f"{text} @ {posted:%a %H:%M}")


def conflict(text: str, *, posted: datetime = WED) -> object:
    return row(text, "other", (), 0.25, ("conflict",), posted=posted)


def corrected(text: str, kind: str, dates: tuple[date, ...]) -> object:
    return row(text, kind, dates, 0.8, ("superseded",))


def updated(text: str, dates: tuple[date, ...]) -> object:
    return row(text, "closed", dates, 0.95, ("superseded",))


def hedged(text: str, dates: tuple[date, ...]) -> object:
    return row(text, "closed", dates, 0.8, ("hedged",))


def unchanged(text: str, kind: str, dates: tuple[date, ...], *notes: str) -> object:
    return row(text, kind, dates, 0.8 if "partial_program" in notes else 0.95, notes)


def mismatch(text: str, *, posted: datetime = WED) -> object:
    return row(text, "other", (), 0.3, ("date_mismatch",), posted=posted)


ROWS = [
    # The one day named closed and open, with nothing that says which came last.
    conflict("Closed tomorrow. Open tomorrow."),
    conflict("Open tomorrow. Closed tomorrow."),
    conflict("Closed Thursday. Open Thursday."),
    conflict("Thursday: Closed. Thursday: Open."),
    conflict("Closed tomorrow. Tomorrow: regular schedule."),
    conflict("Closed tomorrow. Open Thursday."),  # (tomorrow is Thursday)
    conflict("E-learning day tomorrow. Open tomorrow."),
    conflict("Update: open today, Today: Closed"),
    conflict("School will reopen Thursday - Thursday: Closed"),
    # A closure that names no day is for the posting time's day: the evening's is tomorrow.
    conflict("Closed. Open tomorrow.", posted=WED_EVENING),
    conflict("No school. School will reopen tomorrow.", posted=WED_EVENING),
    # An open day after the closure takes that day from it.
    corrected("Closed Thursday and Friday, open Friday", "closed", jan(22)),
    corrected("Closed Thursday and Friday; open Friday", "closed", jan(22)),
    corrected("Closed Thursday and Friday. Open Friday.", "closed", jan(22)),
    corrected("Closed Thursday and Friday. Friday: open", "closed", jan(22)),
    corrected("Closed Thursday and Friday. Friday open.", "closed", jan(22)),
    corrected("Closed Thursday and Friday. We will reopen Friday.", "closed", jan(22)),
    corrected("Closed Thursday and Friday. Classes resume Friday.", "closed", jan(22)),
    corrected("Closed Thursday and Friday. Friday on time.", "closed", jan(22)),
    corrected("Closed Thursday and Friday. Friday: regular day", "closed", jan(22)),
    corrected("Closed Thursday and Friday. Open tomorrow.", "closed", jan(23)),
    corrected("Closed Jan 22 and 23. Open Jan 23.", "closed", jan(22)),
    # (Texts that differ only in one date share their reading: each keeps its own date.)
    corrected("Closed Thursday and Friday. Open Jan. 23.", "closed", jan(22)),
    corrected("Closed Thursday and Friday. Open Jan. 22.", "closed", jan(23)),
    corrected("Closed Thursday through Friday. School reopens Friday.", "closed", jan(22)),
    corrected(
        "Remote learning Thursday and Friday. In-person classes resume Friday.", "remote", jan(22)
    ),
    # A return to school, or a school day held, on a day the closure names.
    corrected("Closed today and tomorrow. Students return tomorrow.", "closed", jan(21)),
    corrected("Closed today, tomorrow, students return Thursday", "closed", jan(21)),
    corrected("Closed today and tomorrow, kids back tomorrow", "closed", jan(21)),
    corrected("Closed Thursday and Friday. Back to school Friday.", "closed", jan(22)),
    corrected("Closed Thursday and Friday. We will be back Friday.", "closed", jan(22)),
    corrected("Closed Thursday and Friday; students return to class Friday", "closed", jan(22)),
    corrected("Closed Thursday and Friday. Classes will be held Friday.", "closed", jan(22)),
    corrected("Closed Thursday, Friday. Regular classes Friday.", "closed", jan(22)),
    updated("Closed Thursday and Friday. UPDATE: students return Friday.", jan(22)),
    hedged("Closed Thursday and Friday. We hope to be back Friday.", jan(22)),
    row(
        "Closed today, Thursday and Friday; we will be back Thursday",
        "other",
        (),
        0.3,
        ("ambiguous",),
    ),
    # ... but not one on another day, denied, or someone else's.
    unchanged("Closed today and tomorrow. Students return Friday.", "closed", jan(21, 22)),
    unchanged("Closed Thursday and Friday. Staff return Friday.", "closed", jan(22, 23)),
    unchanged("Closed Thursday and Friday. Teachers will be back Friday.", "closed", jan(22, 23)),
    unchanged(
        "Closed Thursday and Friday. Students will not return until Monday.", "closed", jan(22, 23)
    ),
    unchanged("Closed Thursday and Friday. Power should be back Friday", "closed", jan(22, 23)),
    # A later sentence that names one of the closure's days and says more of it than the rules
    # read leaves the days open: no return, but no sure closure either (see
    # test_classify_said_again).
    row(
        "Closed Thursday and Friday. Check back Friday for updates.",
        "other",
        (),
        0.3,
        ("unread_words",),
    ),
    row(
        "Closed Thursday and Friday. Library books due back Friday",
        "other",
        (),
        0.3,
        ("unread_words",),
    ),
    unchanged(
        "Closed today and tomorrow. No classes will be held tomorrow.", "closed", jan(21, 22)
    ),
    # A status denied on a day it names takes that day from it, for its kind only.
    row(
        "Closed tomorrow. Update: tomorrow is not closed",
        "other",
        (),
        0.9,
        ("negated", "superseded"),
    ),
    row(
        "Closed tomorrow. Update: no closure tomorrow", "other", (), 0.9, ("negated", "superseded")
    ),
    row(
        "Closed Thursday and Friday. Update: not closed Friday",
        "closed",
        jan(22),
        0.95,
        ("negated", "superseded"),
    ),
    row(
        "Closed Thursday and Friday. Not closed Friday.",
        "closed",
        jan(22),
        0.8,
        ("negated", "superseded"),
    ),
    row(
        "Closed today and tomorrow. Tomorrow is not closed.",
        "closed",
        jan(21),
        0.8,
        ("negated", "superseded"),
    ),
    corrected(
        "Closed today and tomorrow. Update: closed today but not tomorrow", "closed", jan(21)
    ),
    updated("Closed today and tomorrow. Update: not tomorrow", jan(21)),
    updated("Closed Thursday and Friday. Update: not Friday", jan(22)),
    updated("Closed today and tomorrow. Closed today but not tomorrow.", jan(21)),
    row(
        "Closed Monday through Friday, not Wednesday",
        "closed",
        jan(19, 20, 22, 23),
        0.8,
        ("superseded",),
        posted=MON,
    ),
    row(
        "2 hour delay today and tomorrow. Update: no delay tomorrow",
        "delayed",
        jan(21),
        0.95,
        ("negated", "superseded"),
    ),
    row("Not closed tomorrow. Closed tomorrow.", "other", (), 0.25, ("conflict", "negated")),
    # ... but not one of another kind, at another length, before an update, or someone else's.
    row("Not closed tomorrow. Update: closed tomorrow.", "closed", jan(22), 0.95, ("negated",)),
    row("NTI day tomorrow - school is not closed tomorrow", "remote", jan(22), 0.95, ("negated",)),
    row("2 hour delay tomorrow, not a 3 hour delay", "delayed", jan(22), 0.95, ("negated",)),
    row("Closed tomorrow. Not delayed tomorrow.", "closed", jan(22), 0.95, ("negated",)),
    row("Closed tomorrow. No buses delayed tomorrow.", "closed", jan(22), 0.95, ("negated",)),
    unchanged("Closed tomorrow; offices not closed tomorrow", "closed", jan(22)),
    # ... and with a word that marks it as an update, the other days stand as stated.
    updated("Closed Wednesday, Thursday and Friday. UPDATE: open Friday", jan(21, 22)),
    updated("Closed Wednesday, Thursday and Friday - updated: open Friday", jan(21, 22)),
    updated("Closed today and tomorrow. UPDATE: open tomorrow", jan(21)),
    updated("Closed today, tomorrow and Friday. UPDATE: open Friday", jan(21, 22)),
    updated("Closed today and tomorrow. Update: tomorrow is a regular day", jan(21)),
    updated("Closed today and tomorrow. Update: tomorrow on time", jan(21)),
    updated("Closed today and tomorrow. Update: school will reopen tomorrow", jan(21)),
    updated("Closed Thursday and Friday. Correction: open Friday", jan(22)),
    # The closure is the update: it stands.
    row("Open tomorrow. Update: closed tomorrow", "closed", jan(22), 0.95),
    # A reopening that is only possible, or a decision to come.
    hedged("Closed Wednesday, Thursday and Friday, may reopen Friday", jan(21, 22)),
    hedged("Closed today and tomorrow, may reopen tomorrow", jan(21)),
    hedged("Closed Wednesday, Thursday and Friday, will reassess Thursday", jan(21, 22)),
    hedged("Closed tomorrow and Friday; will reassess tomorrow", jan(22)),
    hedged("Closed Thursday and Friday. May reopen Friday.", jan(22)),
    hedged("Closed Thursday and Friday; reopening Friday weather permitting", jan(22)),
    hedged("Closed Thursday and Friday; if roads are clear we will reopen Friday", jan(22)),
    hedged("Closed Thursday, Friday. Reopen Friday?", jan(22)),
    hedged("Closed Thursday and Friday. Open Friday?", jan(22)),
    hedged("Closed Thursday and Friday. Possibly open Friday.", jan(22)),
    hedged("Closed Thursday and Friday. We hope to reopen Friday.", jan(22)),
    hedged("Closed Monday through Friday; may reopen Wednesday", jan(19, 20)),
    row("Closed tomorrow, may reopen tomorrow", "other", (), 0.3, ("hedged",)),
    # Nothing open on a day the closure names.
    unchanged("Closed today, open tomorrow", "closed", jan(21)),
    unchanged("Closed Thursday. Open Friday.", "closed", jan(22)),
    unchanged("Closed Thursday; reopening Friday", "closed", jan(22)),
    unchanged("Closed Thursday and Friday; reopening Monday", "closed", jan(22, 23)),
    unchanged("Closed until Friday; reopening Friday", "closed", jan(21, 22)),
    unchanged("Closed through Friday. Classes resume Monday.", "closed", jan(21, 22, 23)),
    unchanged("Closed Thursday and Friday. Offices open Friday.", "closed", jan(22, 23)),
    unchanged(
        "Closed Thursday and Friday; open Friday for staff only", "closed", jan(22, 23), "staff"
    ),
    unchanged("Closed Thursday and Friday. School will not reopen Friday.", "closed", jan(22, 23)),
    unchanged("Closed Thursday and Friday; activities resume Friday", "closed", jan(22, 23)),
    unchanged("Closed Thursday and Friday; bus routes resume Friday", "closed", jan(22, 23)),
    unchanged("Closed Thursday and Friday; buildings reopen Friday", "closed", jan(22, 23)),
    unchanged(
        "Remote learning Thursday; school buildings open Thursday for meal pickup",
        "remote",
        jan(22),
    ),
    unchanged("NTI Thursday and Friday. Buildings open Friday.", "remote", jan(22, 23)),
    unchanged("2 hour delay tomorrow. Open tomorrow at 10.", "delayed", jan(22)),
    # A school of the district open on a day of the closure: no status of the district.
    row(
        "Closed Thursday and Friday; Lincoln Elementary open Friday",
        "other",
        (),
        0.9,
        ("partial_program",),
    ),
    unchanged("Closed tomorrow. We will reassess tomorrow afternoon.", "closed", jan(22)),
    unchanged("Closed tomorrow; will reassess tomorrow for Friday", "closed", jan(22)),
    unchanged("Closed tomorrow, opening Friday at 10", "closed", jan(22)),
    # Another place or service open on the day, or the school open for one.
    unchanged("Closed tomorrow. Shelter open tomorrow.", "closed", jan(22)),
    unchanged("Closed tomorrow; schools open tomorrow as warming centers", "closed", jan(22)),
    unchanged("NTI day tomorrow. Open tomorrow for meal pickup.", "remote", jan(22)),
    unchanged("Closed Thursday and Friday. Meal sites open Friday.", "closed", jan(22, 23)),
    unchanged("Closed Thursday and Friday. Warming center open Friday.", "closed", jan(22, 23)),
    unchanged("Closed Thursday and Friday. Not open Friday.", "closed", jan(22, 23)),
    unchanged(
        "Closed Thursday and Friday. The portal will be open Friday for assignments.",
        "closed",
        jan(22, 23),
    ),
    unchanged(
        "Closed Thursday and Friday. Open Friday for students who need meals.",
        "closed",
        jan(22, 23),
    ),
    unchanged(
        "Closed Thursday and Friday. Open Friday for families needing meals.", "closed", jan(22, 23)
    ),
    unchanged("Closed Thursday and Friday. Food pantry open Friday.", "closed", jan(22, 23)),
    # An update that opens the buildings or a service, as one that opens the offices.
    unchanged("Closed today. Update: buildings open today", "closed", jan(21)),
    unchanged("Closed tomorrow. Update: buildings open tomorrow", "closed", jan(22)),
    unchanged("Closed today. Update: offices open today", "closed", jan(21)),
    unchanged("Closed today. Update: open today for meal pickup", "closed", jan(21)),
    unchanged("Closed today. Update: open today for students who need meals", "closed", jan(21)),
    unchanged("Closed tomorrow. UPDATE: school buildings will be open tomorrow", "closed", jan(22)),
    # ... while the school open for its students is an opening.
    corrected("Closed Thursday and Friday. Open Friday for students.", "closed", jan(22)),
    corrected("Closed Thursday and Friday. Open Friday for in-person classes.", "closed", jan(22)),
    unchanged("Closed Thursday and Friday. Friday: not open", "closed", jan(22, 23)),
    # An open day that cannot be told is no day of the closure's.
    unchanged("Closed Thursday and Friday. Open Friday, Jan. 30", "closed", jan(22, 23)),
    unchanged("Closed Thursday and Friday. Open next Friday", "closed", jan(22, 23)),
    # A weekday and a date, or a relative day and a weekday, that disagree.
    mismatch("Closed Thursday 1/23"),
    mismatch("Closed Friday, Jan 2", posted=NEW_YEARS_EVE),
    mismatch("Closed today, Thursday 1/29 and Friday"),
    mismatch("Closed today (Friday) and Monday", posted=MON),
    mismatch("Closed Monday and today (Friday)", posted=MON),
    mismatch("Closed tomorrow (Thursday) and Friday", posted=THU),
    # The status that disagrees is left out; another stands as a judgment call.
    row("Closed Thursday 1/23. 2 hour delay Monday.", "delayed", jan(26), 0.8, ("date_mismatch",)),
]


@pytest.mark.parametrize("case", ROWS)
def test_an_open_day_beside_a_closure(case: Row) -> None:
    result = parse_status(case.text, posted_at=case.posted, tz=TZ)
    assert result.kind == case.kind
    assert result.dates == case.dates
    assert result.confidence == case.confidence
    assert result.notes == case.notes


def test_a_status_left_with_both_open_and_closed_says_no_school_is_open() -> None:
    result = parse_status("Closed tomorrow. Open tomorrow.", posted_at=WED, tz=TZ)
    assert not result.says_open  # (which one holds is unknown)
    replaced = parse_status("Closed tomorrow. Update: open tomorrow", posted_at=WED, tz=TZ)
    assert (replaced.kind, replaced.says_open, replaced.confidence) == ("other", True, 0.9)


def test_the_days_an_open_day_leaves_keep_their_status_in_the_schedule() -> None:
    result = parse_status(
        "Closed Thursday and Friday. Open Friday. 2 hour delay Monday.", posted_at=WED, tz=TZ
    )
    assert [(entry.kind, entry.dates) for entry in result.schedule] == [
        ("closed", jan(22)),
        ("delayed", jan(26)),
    ]
    assert result.confidence == 0.8


# The property: whatever the wording, a closure or a remote day beside a word that school is
# open on one of its days is never confident on that day.
DAY_WORDS = (
    "today", "tomorrow", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Jan. 22",
    "1/23",
)  # fmt: skip
STATUSES = (
    "Closed {days}", "No school {days}", "Classes cancelled {days}", "{Days}: Closed",
    "School closed {days}", "NTI {days}", "Virtual learning {days}", "eLearning day {days}",
    "Snow day {days}",
)  # fmt: skip
OPENINGS = (
    "Open {day}", "{Day}: open", "{Day} open", "School will reopen {day}", "Classes resume {day}",
    "{Day}: regular schedule", "{Day} on time", "Update: open {day}", "We may reopen {day}",
    "School open {day}", "{Day}: regular day", "Open {day}?", "Students return {day}",
    "Back to school {day}", "We will be back {day}", "Classes will be held {day}",
)  # fmt: skip
POSTINGS = st.builds(
    lambda day, hour: datetime(2026, 1, day, hour, 0, tzinfo=ZONE),
    st.integers(19, 25),
    st.sampled_from((1, 6, 13, 19, 22)),
)


def capitalized(text: str) -> str:
    return text[0].upper() + text[1:]


@settings(max_examples=500, deadline=None)
@given(
    posted=POSTINGS,
    day=st.sampled_from(DAY_WORDS),
    extra=st.sampled_from((None, *DAY_WORDS)),
    status=st.sampled_from(STATUSES),
    opening=st.sampled_from(OPENINGS),
    join=st.sampled_from((". ", "; ", ", ", " - ")),
    open_first=st.booleans(),
)
def test_a_status_beside_an_open_day_is_never_confident_on_that_day(  # noqa: PLR0913, PLR0917
    posted: datetime,
    day: str,
    extra: str | None,
    status: str,
    opening: str,
    join: str,
    open_first: bool,
) -> None:
    alone = parse_status(f"Closed {day}", posted_at=posted, tz=TZ)
    if len(alone.dates) != 1 or extra == day:
        return  # (a day word that names no single day at this time, or one named twice)
    opened = alone.dates[0]
    days = day if extra is None else f"{day} and {extra}"
    stated = status.format(days=days, Days=capitalized(days))
    said_open = opening.format(day=day, Day=capitalized(day))
    text = f"{said_open}{join}{stated}" if open_first else f"{stated}{join}{said_open}"
    result = parse_status(text, posted_at=posted, tz=TZ)
    if result.confidence >= 0.7:
        for entry in result.schedule:
            assert not (entry.kind in {"closed", "remote"} and opened in entry.dates), text


# The property for denials: a status beside a word that denies its kind on one of its days is
# never confident on that day. (status, its kind) and (denial, the kind it denies).
DENIED_STATUSES = (
    ("Closed {days}", "closed"), ("No school {days}", "closed"), ("{Days}: Closed", "closed"),
    ("Classes cancelled {days}", "closed"), ("2 hour delay {days}", "delayed"),
    ("NTI {days}", "remote"),
)  # fmt: skip
DENIALS = (
    ("Not closed {day}", "closed"), ("{Day} is not closed", "closed"),
    ("No closure {day}", "closed"), ("Update: not closed {day}", "closed"),
    ("Correction: no school closure {day}", "closed"), ("We are not closed {day}", "closed"),
    ("{Day}: not closed", "closed"), ("No delay {day}", "delayed"), ("No NTI {day}", "remote"),
    ("Update: not {day}", None),
)  # fmt: skip


@settings(max_examples=500, deadline=None)
@given(
    posted=POSTINGS,
    day=st.sampled_from(DAY_WORDS),
    extra=st.sampled_from((None, *DAY_WORDS)),
    status=st.sampled_from(DENIED_STATUSES),
    denial=st.sampled_from(DENIALS),
    join=st.sampled_from((". ", "; ", ", ", " - ")),
    denial_first=st.booleans(),
)
def test_a_status_beside_its_denial_is_never_confident_on_that_day(  # noqa: PLR0913, PLR0917
    posted: datetime,
    day: str,
    extra: str | None,
    status: tuple[str, str],
    denial: tuple[str, str | None],
    join: str,
    denial_first: bool,
) -> None:
    (stated_form, kind), (denial_form, denied) = status, denial
    alone = parse_status(f"Closed {day}", posted_at=posted, tz=TZ)
    if len(alone.dates) != 1 or extra == day or denied not in {kind, None}:
        return  # (a day word that names no single day, one named twice, or another kind)
    target = alone.dates[0]
    days = day if extra is None else f"{day} and {extra}"
    stated = stated_form.format(days=days, Days=capitalized(days))
    said = denial_form.format(day=day, Day=capitalized(day))
    text = f"{said}{join}{stated}" if denial_first else f"{stated}{join}{said}"
    result = parse_status(text, posted_at=posted, tz=TZ)
    if result.confidence >= 0.7:
        for entry in result.schedule:
            assert not (entry.kind == kind and target in entry.dates), text


# After the school says it is open, a remote day offered as an option to some students is not
# the district's day: "Open, virtual option available", "Open; remote learning for students in
# quarantine".
REMOTE_OPTIONS = [
    "Open, virtual option available",
    "Open; virtual learning option available for students who cannot travel safely",
    "Open as scheduled; eLearning available for those unable to attend",
    "Open with an optional virtual day",
    "Open; remote learning for students in quarantine",
    "Open on time. Remote learning available for families who choose it.",
]


@pytest.mark.parametrize("text", REMOTE_OPTIONS)
def test_a_remote_option_beside_an_open_school_is_no_remote_day(text: str) -> None:
    result = parse_status(text, posted_at=WED, tz=TZ)
    assert result.kind != "remote" or result.confidence < 0.7


@settings(max_examples=300, deadline=None)
@given(
    opened=st.sampled_from(("Open", "School is open", "Open as scheduled", "Open on time")),
    mark=st.sampled_from((", ", "; ", ". ", " - ")),
    remote=st.sampled_from(("virtual learning", "eLearning", "remote learning", "online learning")),
    offer=st.sampled_from(
        ("option available", "available for those unable to attend",
         "for students in quarantine", "optional for families who choose it",
         "available for students who cannot travel")
    ),
)  # fmt: skip
def test_a_remote_option_beside_an_open_school_is_never_a_remote_day(
    opened: str, mark: str, remote: str, offer: str
) -> None:
    text = f"{opened}{mark}{remote} {offer}"
    result = parse_status(text, posted_at=WED, tz=TZ)
    assert result.kind != "remote" or result.confidence < 0.7, text


# A remote mention offered to some students only, with no word that the school is open before
# it, is still an option, not the district's day.
REMOTE_OFFERED = [
    "Remote learning available for students who cannot get to school",
    "Virtual option for students who cannot travel safely",
    "Remote learning for students unable to travel",
    "Remote learning option available today",
]
# A remote day stated, with a note to some students after it, stands.
REMOTE_STATED = [
    "Remote learning today. Students who cannot log in should call the office.",
    "Remote learning today for all students",
]


@pytest.mark.parametrize("text", REMOTE_OFFERED)
def test_a_remote_option_with_no_opening_is_no_remote_day(text: str) -> None:
    result = parse_status(text, posted_at=WED, tz=TZ)
    assert result.kind == "other", text
    assert result.confidence <= 0.3, text


@pytest.mark.parametrize("text", REMOTE_STATED)
def test_a_remote_day_with_a_note_to_some_students_stands(text: str) -> None:
    result = parse_status(text, posted_at=WED, tz=TZ)
    assert result.kind == "remote", text


@settings(max_examples=300, deadline=None)
@given(
    remote=st.sampled_from(("Remote learning", "Virtual learning", "eLearning", "Virtual option",
                            "Remote instruction", "Online learning")),
    qualifier=st.sampled_from(("available for students who cannot get to school",
                               "for students unable to travel", "option available today",
                               "available for those who cannot attend", "optional today",
                               "for students who choose to stay home")),
)  # fmt: skip
def test_a_remote_mention_offered_as_an_option_is_never_a_remote_day(
    remote: str, qualifier: str
) -> None:
    # Invariant: "<remote mention> <option qualifier>" never gives remote at 0.7 or more.
    result = parse_status(f"{remote} {qualifier}", posted_at=WED, tz=TZ)
    assert result.kind != "remote" or result.confidence < 0.7, (remote, qualifier, result)


# A remote day said to be possible for some students only, after a status stated for the
# day, is an option offered beside that status, not a remote day to come that puts it in
# doubt: the stated status stands.
@settings(max_examples=300, deadline=None)
@given(
    stated=st.sampled_from(
        (("Closed today.", "closed"), ("Schools closed today.", "closed"),
         ("2 hour delay today.", "delayed"), ("Early dismissal at 1 pm today.", "early_dismissal"))
    ),
    remote=st.sampled_from(
        ("Remote learning", "Virtual learning", "eLearning", "Online learning",
         "Remote instruction")
    ),
    offer=st.sampled_from(
        ("will be possible for some students", "is possible for those who need it",
         "may be possible for individual students", "is possible as an option",
         "is possible for students unable to travel")
    ),
)  # fmt: skip
def test_a_remote_option_possible_for_some_leaves_the_stated_status(
    stated: tuple[str, str], remote: str, offer: str
) -> None:
    text, kind = stated
    result = parse_status(f"{text} {remote} {offer}.", posted_at=WED, tz=TZ)
    assert result.kind == kind, (text, remote, offer, result)
    assert result.confidence >= 0.9, (text, remote, offer, result)
    assert result.dates == (date(2026, 1, 21),)
