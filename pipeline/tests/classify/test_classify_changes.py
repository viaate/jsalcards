"""A status the text says was replaced by another: "2 hour delay is now a closing".

Every text here is a phrasing pattern written for these tests, not a claim
about a real school. Unless a row says otherwise it is posted at 6 a.m. on
Tuesday 20 January 2026 in New York, so "today" is Tuesday the 20th and
"tomorrow" Wednesday the 21st.

* A change after a status ("is now", "changed to", "became", "has become",
  "turned into", "replaced with", "replaced by", "switched to", "reduced to",
  "downgraded to", "scaled back to", "now", "UPDATE:")
  hands the day to the status named after it, as a judgment call: that status
  at 0.8, noted ``superseded``, with none of the old status's details (a delay's
  length). "A closing", "a full closing" and a bare "Closing" after a change are
  a closure.
* A change to nothing that reads as a status ("2 hour delay has been changed",
  "delay is now a full day"), to something unclear ("2 hour delay. UPDATE:
  Closings") or to something only possible ("2 hour delay. Update: possible
  closure") leaves no status: ``other`` at 0.3. The old status never shows.
* A new length after a change is the delay's ("2 hour delay - now 3 hours"),
  and a new day is the status's ("2 hour delay Wednesday moved to Thursday"),
  both at 0.8.
* A change denied ("will not change to a closure"), a change of something else
  ("Closed. Bus routes changed"), a status named as the one before ("changed
  from a closure") and a status only said to hold ("2 hour delay is now in
  effect") leave the status as it is.
"""

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from snowlight.classify import parse_status

TZ = "America/New_York"
ZONE = ZoneInfo(TZ)
MORNING = datetime(2026, 1, 20, 6, 0, tzinfo=ZONE)  # Tuesday
EVENING = datetime(2026, 1, 20, 20, 0, tzinfo=ZONE)


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
    opens: time | None
    dismissal: time | None
    early: int | None
    says_open: bool


def row(  # noqa: PLR0913 - one table row
    text: str,
    kind: str = "other",
    dates: tuple[date, ...] = (),
    *,
    posted: datetime = MORNING,
    confidence: float = 0.8,
    notes: tuple[str, ...] = (),
    delay: int | None = None,
    opens: time | None = None,
    dismissal: time | None = None,
    early: int | None = None,
    says_open: bool = False,
) -> object:
    label = f"{text} @ {posted:%a %H:%M}"
    fields = (delay, opens, dismissal, early, says_open)
    return pytest.param(Row(text, posted, kind, dates, confidence, notes, *fields), id=label)


def replaced(
    text: str, kind: str, dates: tuple[date, ...] = jan(20), *, posted: datetime = MORNING
) -> object:
    """A status replaced by the one named after the change."""
    return row(text, kind, dates, posted=posted, notes=("superseded",))


def unread(text: str, *, posted: datetime = MORNING) -> object:
    """A status changed into nothing the parser reads."""
    return row(text, posted=posted, confidence=0.3, notes=("ambiguous", "superseded"))


def possible(text: str, *, posted: datetime = MORNING) -> object:
    """A status changed into one that is only possible."""
    return row(text, posted=posted, confidence=0.3, notes=("hedged", "superseded"))


def check(case: Row) -> None:
    result = parse_status(case.text, posted_at=case.posted, tz=TZ)
    assert result.kind == case.kind
    assert result.dates == case.dates
    assert result.confidence == case.confidence
    assert set(case.notes) <= set(result.notes)
    assert result.delay_minutes == case.delay
    assert result.opens_at == case.opens
    assert result.dismissal_time == case.dismissal
    assert result.dismissal_early_minutes == case.early
    assert result.says_open is case.says_open
    if case.kind == "other":
        assert result.schedule == ()


# The phrasings of the gap: each one the status named after the change, never the old one.
REPLACED = [
    replaced("2 hour delay is now a closing", "closed"),
    replaced("UPDATE: 2 hour delay is now a closing", "closed"),
    replaced("Delay changed to a closing", "closed"),
    replaced("2 hr delay - now a closing", "closed"),
    replaced("2 hour delay. UPDATE: Closing", "closed"),
    replaced("2 hour delay. UPDATE: Now closing", "closed"),
    replaced("Delay became an early dismissal", "early_dismissal"),
    replaced("2 hr delay turned into an e-learning day", "remote"),
    replaced("2 hour delay replaced with an e-learning day", "remote"),
    replaced("2 hour delay is now a closure", "closed"),
    replaced("2 hr delay has become a closure", "closed"),
    # The same, said in other words.
    replaced("2 hour delay changed to a full closing", "closed"),
    replaced("UPDATE: 2 hr delay - now a full closing", "closed"),
    replaced("Two hour delay has been changed to a closing", "closed"),
    replaced("90 minute delay is now a full closing", "closed"),
    replaced("2 hour delay switched to a closing", "closed"),
    replaced("2 hour delay upgraded to a closing", "closed"),
    replaced("2 hour delay replaced by closure", "closed"),
    replaced("2 hour delay turned to closure", "closed"),
    replaced("2 hour delay turned into a closure", "closed"),
    replaced("Late start is now a closing", "closed"),
    replaced("Delay became a closure", "closed"),
    replaced("Delay became closed", "closed"),
    replaced("2 hour delay, now closed", "closed"),
    replaced("2 hour delay. UPDATE: Closed", "closed"),
    replaced("2 hour delay has been changed. Schools closed.", "closed"),
    replaced("Delay has become an e-learning day", "remote"),
    replaced("2 hour delay turned into an NTI day", "remote"),
    replaced("2 hour delay replaced with remote learning", "remote"),
    replaced("2 hour delay now e-learning day", "remote"),
    replaced("Delay is now an early dismissal", "early_dismissal"),
    replaced("Early dismissal is now a closing", "closed"),
    replaced("Early release at 1 PM became a closure", "closed"),
    replaced("Remote learning day is now a closing", "closed"),
    replaced("Remote learning today has been changed to a closing", "closed"),
    replaced("E-learning day became a closure", "closed"),
    replaced("Closed - now a remote learning day", "remote"),
    replaced("Early dismissal at 1 PM is now a full closing", "closed"),
    replaced("2 hour delay now a closing day", "closed"),
    replaced("2 hour delay UPDATED to closing", "closed"),
    replaced("Delayed 2 hours; update: closing", "closed"),
    replaced("2 hour delay. UPDATE 6:15 AM: Closing", "closed"),
    replaced("2 HOUR DELAY IS NOW A CLOSING", "closed"),
    replaced("2 Hour Delay - Changed To Closed", "closed"),
    replaced("Delay changed to: Closed", "closed"),
    replaced("Was 2 hour delay, now closed", "closed"),
    replaced("2 hour delay (now closed)", "closed"),
    replaced("Two-hour delay has been upgraded to a full closure", "closed"),
    replaced("2 hour delay converted to e-learning day", "remote"),
    replaced("2 hour delay switched to NTI", "remote"),
    # "Instead" after the closing names the status it replaces.
    replaced("Closing instead of 2 hour delay", "closed"),
    replaced("No school instead of a 2 hour delay", "closed"),
    row("Closed, now 2 hours late", "delayed", jan(20), notes=("superseded",), delay=120),
    # An arrow from one status to the next.
    replaced("2 hr delay -> closed", "closed"),
    replaced("2 hr delay => closing", "closed"),
    replaced("Delay => Closing", "closed"),
    replaced("2 hour delay >> closed", "closed"),
    replaced("2 hour delay \u2192 e-learning", "remote"),
    # The old status's day, and an evening post's next day, go to the new status.
    replaced("2 hour delay tomorrow is now a closing", "closed", jan(21)),
    replaced("2 hour delay tomorrow. UPDATE: Closing", "closed", jan(21)),
    replaced("Wednesday: 2 hour delay is now a closing", "closed", jan(21)),
    replaced("2 hour delay is now a closing", "closed", jan(21), posted=EVENING),
    replaced("Delay became an early dismissal", "early_dismissal", jan(21), posted=EVENING),
    replaced("2 hr delay turned into an e-learning day", "remote", jan(21), posted=EVENING),
    # A new status with details of its own keeps them.
    row("Delay changed to an early dismissal at 1:00", "early_dismissal", jan(20),
        notes=("superseded",), dismissal=time(13)),
    row("2 hour delay is now a 3 hour delay", "delayed", jan(20), delay=180),
    row("2 hour delay, now 3 hour delay", "delayed", jan(20), delay=180),
    row("1 hour delay has been changed to a 2 hour delay", "delayed", jan(20), delay=120),
    # A closure lessened to another status: the later one replaces it, as a change does.
    row("Update: closure reduced to a 2 hour delay", "delayed", jan(20), notes=("superseded",),
        delay=120),
    row("Closure downgraded to 2 hour delay", "delayed", jan(20), notes=("superseded",),
        delay=120),
    replaced("Closure reduced to a delay", "delayed"),
    replaced("Closure downgraded to an early dismissal", "early_dismissal"),
    row("Closed today. Closure reduced to a 2 hour delay.", "delayed", jan(20),
        notes=("superseded",), delay=120),
    row("2 hour delay reduced to 1 hour delay", "delayed", jan(20), delay=60),
    row("2 hour delay lowered to a 1 hour delay", "delayed", jan(20), delay=60),
]  # fmt: skip

# A change to nothing that reads as a status, or to something unclear: no status.
UNREAD = [
    unread("2 hour delay has been changed"),
    unread("2 hour delay has been changed."),
    unread("2 hour delay changed"),
    unread("Delay changed to a full day"),
    unread("2 hour delay is now a full day"),
    unread("2 hr delay - now a full day"),
    unread("2 hour delay has become something else"),
    unread("2 hour delay turned into a full day"),
    unread("2 hour delay replaced with a new plan"),
    unread("UPDATE: 2 hour delay is now a full day"),
    unread("2 hour delay tomorrow has been changed"),
    unread("2 hour delay has been changed", posted=EVENING),
    unread("2 hour delay. UPDATE: Closings"),
    unread("2 hour delay, now closings"),
    unread("2 hour delay tomorrow. UPDATE: Closings"),
    unread("2 hour delay has been changed; all activities cancelled"),
    # A new time no school day could start or end early at.
    unread("Early dismissal at 1 PM - now 5:00 PM"),
    unread("Opening at 10 AM changed to 3 PM"),
    # A length the old status has no place for.
    unread("Closed - now 2 hours"),
    unread("Early dismissal at 1 - now 2 hours"),
    # Only possible: no status either.
    possible("2 hour delay. Update: possible closure"),
    possible("2 hour delay tomorrow. Update: possible closure"),
    possible("2 hour delay, possibly becoming a closure later"),
    possible("2 hour delay; may change to a closure"),
    possible("2 hour delay. Early dismissal cancelled. Update: possible closure"),
]

# Two statuses joined by a verb no change rule reads, or a heading that names two kinds: the
# text does not say which holds, so neither does (``other``, 0.3 at most).
UNORDERED = [
    "Closure cut to a 2 hour delay", "Closure trimmed to a 2 hour delay",
    "Closure adjusted to a 2 hour delay", "Closure eased to a 2 hour delay",
    "Closure relaxed to a 2 hour delay", "Closure softened to a 2 hour delay",
    "Closure walked back to a 2 hour delay", "Closure rolled back to a 2 hour delay",
    "Closure pulled back to a 2 hour delay", "Closure dialed back to a 2 hour delay",
    "Closure amended to a 2 hour delay", "Closure altered to a 2 hour delay",
    "Closure bumped up to a 2 hour delay", "Closed today, amended to a 2 hour delay",
    "Closed - amended to 2 hour delay", "2 hour delay bumped to a closure",
    "2 hour delay escalated to a closure", "Remote day cut to a 2 hour delay",
    "NTI day amended to a 2 hour delay", "Closed, later a 2 hour delay",
    "Delay and closure information", "Delay and closure info", "Delay and closure policy",
    "Delay/closure information", "Closure and delay information", "Closing & delay procedures",
]  # fmt: skip

# A new length or a new day.
MOVED = [
    row("2 hour delay - now 3 hours", "delayed", jan(20), notes=("superseded",), delay=180),
    row("2 hour delay is now 3 hours", "delayed", jan(20), notes=("superseded",), delay=180),
    row("90 minute delay changed to 2 hours", "delayed", jan(20), notes=("superseded",),
        delay=120),
    row("2 hour delay. UPDATE: 3 hours", "delayed", jan(20), notes=("superseded",), delay=180),
    row("Delayed 2 hours, now 3 hours. Buses on snow routes.", "delayed", jan(20),
        notes=("superseded", "transportation"), delay=180),
    row("Opening at 10 AM changed to 11 AM", "delayed", jan(20), notes=("superseded",),
        opens=time(11)),
    row("Delayed opening at 10:00 is now 11:00", "delayed", jan(20), notes=("superseded",),
        opens=time(11)),
    row("Early dismissal at 12:30 today has been changed to 11:30", "early_dismissal",
        jan(20), notes=("superseded",), dismissal=time(11, 30)),
    row("Early dismissal at 1 PM - now 12:30", "early_dismissal", jan(20),
        notes=("superseded",), dismissal=time(12, 30)),
    row("Early dismissal - now 2 hours early", "early_dismissal", jan(20),
        notes=("superseded",), early=120),
    row("Dismissing 1 hour early, now 2 hours early", "early_dismissal", jan(20),
        notes=("superseded",), early=120),
    row("2 hour delay Wednesday has been changed to Thursday", "delayed", jan(22),
        notes=("superseded",), delay=120),
    row("2 hour delay Wednesday moved to Thursday", "delayed", jan(22), notes=("superseded",),
        delay=120),
    row("Closed Wednesday - moved to Thursday", "closed", jan(22), notes=("superseded",)),
    row("Closed Wednesday and Thursday - moved to Friday", "closed", jan(23),
        notes=("superseded",)),
    # A change that names the day alone: that day, as stated.
    row("2 hour delay changed to Wednesday", "delayed", jan(21), confidence=0.95, delay=120),
    row("2 hour delay moved to Wednesday", "delayed", jan(21), confidence=0.95, delay=120),
    row("Closure changed to Thursday", "closed", jan(22), confidence=0.9),
    # An arrow to a day only names the day; to a length, a new length.
    row("Closed -> Thursday", "closed", jan(22), confidence=0.95),
    row("Closed -> 1/22", "closed", jan(22), confidence=0.95),
    row("2 hr delay -> Tomorrow", "delayed", jan(21), confidence=0.95, delay=120),
    row("2 hour delay -> 3 hour delay", "delayed", jan(20), delay=180),
]  # fmt: skip

# The school opening in its place: no status, and the school runs.
OPENED = [
    row("2 hour delay changed to open on time", confidence=0.9, notes=("superseded",),
        says_open=True),
    row("2 hour delay changed to open", confidence=0.9, notes=("superseded",), says_open=True),
    row("2 hour delay turned into a regular day", confidence=0.9, notes=("superseded",),
        says_open=True),
    row("2 hour delay is now a regular schedule", confidence=0.9, notes=("superseded",),
        says_open=True),
    row("Delay downgraded to on time", confidence=0.9, notes=("superseded",), says_open=True),
    row("Delay downgraded to regular schedule", confidence=0.9, notes=("superseded",),
        says_open=True),
]  # fmt: skip

# No change of this status: it stands as stated.
KEPT = [
    row("Delay will not change to a closing", "delayed", jan(20), confidence=0.9,
        notes=("negated",)),
    row("Delay has not been changed to a closure", "delayed", jan(20), confidence=0.9),
    row("2 hour delay will not be upgraded to a closure", "delayed", jan(20), confidence=0.9,
        delay=120),
    row("2 hour delay has not been changed", "delayed", jan(20), confidence=0.9, delay=120),
    row("2 hour delay (changed from a closure)", "delayed", jan(20), notes=("superseded",),
        delay=120),
    row("2 hour delay is now in effect", "delayed", jan(20), confidence=0.9, delay=120),
    row("2 hour delay now in effect", "delayed", jan(20), confidence=0.9, delay=120),
    row("2 hour delay. Updated 2 hours ago", "delayed", jan(20), confidence=0.9, delay=120),
    row("2 hour delay (updated 5:43 AM)", "delayed", jan(20), confidence=0.9, delay=120),
    row("2 hour delay (updated 7:15 AM)", "delayed", jan(20), confidence=0.9, delay=120),
    row("Early dismissal at 1 PM (updated 11:30 AM)", "early_dismissal", jan(20),
        confidence=0.9, dismissal=time(13)),
    row("Closed. Bus routes changed", "closed", jan(20), confidence=0.9),
    row("Closed. Schedule changed.", "closed", jan(20), confidence=0.9),
    row("Closed. Lunch menu changed to pizza", "closed", jan(20), confidence=0.9),
    row("Power turned off, closed today", "closed", jan(20), confidence=0.95),
    row("Heat turned off so school is closed", "closed", jan(20), confidence=0.9),
    row("Closed today. Now open tomorrow", "closed", jan(20), confidence=0.95),
    row("Closed today. Update: possible closure tomorrow", "closed", jan(20), confidence=0.95,
        notes=("hedged",)),
    row("Closed today. Update: possible 2 hour delay tomorrow", "closed", jan(20),
        confidence=0.95, notes=("hedged",)),
    row("UPDATE: Closing tomorrow", "closed", jan(21), confidence=0.9),
    row("Full closing", "closed", jan(20), confidence=0.9),
    row("No school now through Friday", "closed", jan(20, 21, 22, 23), confidence=0.95),
    # A closing that is a noun, or a time, stays what it was.
    row("Closing", confidence=0.3, notes=("ambiguous",)),
    row("A closing", confidence=0.3, notes=("ambiguous",)),
    row("2 hour delay, now closing at noon", "early_dismissal", jan(20), notes=("superseded",),
        dismissal=time(12)),
]  # fmt: skip


@pytest.mark.parametrize("case", REPLACED)
def test_the_status_named_after_a_change_replaces_the_old_one(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", UNREAD)
def test_a_change_to_nothing_read_leaves_no_status(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", MOVED)
def test_a_change_of_length_or_day_moves_the_status(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", OPENED)
def test_a_change_to_open_leaves_no_status(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", KEPT)
def test_no_change_of_the_status_leaves_it_standing(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("text", UNORDERED)
def test_two_statuses_no_rule_orders_leave_no_status(text: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other"
    assert result.confidence <= 0.3


def test_the_table_covers_every_form() -> None:
    assert len(REPLACED) + len(UNREAD) + len(MOVED) + len(OPENED) + len(KEPT) >= 100


ZONES = ("America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles")
instants = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2032, 12, 31),
    timezones=st.sampled_from([ZoneInfo(name) for name in ZONES]),
)
OLD = (
    "2 hour delay", "2 hr delay", "Two hour delay", "90 minute delay", "Delay", "Late start",
    "Early dismissal at 1:00", "Early release", "E-learning day", "Remote learning day",
)  # fmt: skip
CHANGES = (
    " is now ", " changed to ", " has been changed to ", " became ", " has become ",
    " turned into ", " replaced with ", " replaced by ", " switched to ", " - now ",
    ". UPDATE: ", ". Update: now ", ", now ", " downgraded to ", " reduced to ",
)  # fmt: skip
NEW = (
    ("a closing", "closed"),
    ("a full closing", "closed"),
    ("a closure", "closed"),
    ("closed", "closed"),
    ("a snow day", "closed"),
    ("an e-learning day", "remote"),
    ("an NTI day", "remote"),
    ("remote learning", "remote"),
    ("a virtual learning day", "remote"),
)
UNREAD_TAILS = ("a full day", "a new plan", "a different schedule", "an adjusted plan")
STRONG = (
    " is now ", " has been changed to ", " became ", " turned into ", " replaced with ", " - now ",
)  # fmt: skip


@settings(max_examples=400, deadline=None)
@given(
    old=st.sampled_from(OLD),
    change=st.sampled_from(CHANGES),
    new=st.sampled_from(NEW),
    day=st.sampled_from(("", " today", " tomorrow")),
    posted=instants,
)
def test_a_replaced_status_never_shows(
    old: str, change: str, new: tuple[str, str], day: str, posted: datetime
) -> None:
    phrase, kind = new
    text = f"{old}{day}{change}{phrase}"
    result = parse_status(text, posted_at=posted, tz=str(posted.tzinfo))
    assert result.kind in (kind, "other")
    assert result.delay_minutes is None
    assert result.confidence <= 0.8
    for entry in result.schedule:
        assert entry.kind == kind
        assert entry.delay_minutes is None


@settings(max_examples=300, deadline=None)
@given(
    old=st.sampled_from(OLD),
    change=st.sampled_from(STRONG),
    tail=st.sampled_from(UNREAD_TAILS),
    posted=instants,
)
def test_a_change_to_nothing_read_never_shows_the_old_status(
    old: str, change: str, tail: str, posted: datetime
) -> None:
    result = parse_status(f"{old}{change}{tail}", posted_at=posted, tz=str(posted.tzinfo))
    assert result.kind == "other"
    assert result.confidence <= 0.3
    assert result.schedule == ()


# Verbs no change rule lists: whatever links two statuses, the first never stands for sure.
LINKS = (
    "cut", "trimmed", "adjusted", "eased", "relaxed", "softened", "walked back", "rolled back",
    "pulled back", "dialed back", "amended", "altered", "bumped", "bumped up", "escalated",
    "scaled back", "tweaked", "modified", "revised", "changed", "moved", "switched", "upgraded",
    "downgraded", "reduced", "converted", "shifted",
)  # fmt: skip
FIRST = (
    ("Closure", "closed"), ("Closing", "closed"), ("2 hour delay", "delayed"),
    ("Late start", "delayed"), ("Remote day", "remote"), ("NTI day", "remote"),
    ("Early dismissal", "early_dismissal"),
)  # fmt: skip
SECOND = (
    ("a 2 hour delay", "delayed"), ("a closure", "closed"), ("remote learning", "remote"),
    ("an early dismissal", "early_dismissal"), ("an NTI day", "remote"),
)  # fmt: skip


@settings(max_examples=500, deadline=None)
@given(
    first=st.sampled_from(FIRST),
    link=st.sampled_from(LINKS),
    second=st.sampled_from(SECOND),
    lead=st.sampled_from(("", "Update: ")),
    join=st.sampled_from((" ", ", ", " - ")),
    day=st.sampled_from(("", " today", " tomorrow")),
)
def test_a_status_linked_to_another_is_never_the_first_for_sure(  # noqa: PLR0913, PLR0917
    first: tuple[str, str], link: str, second: tuple[str, str], lead: str, join: str, day: str
) -> None:
    phrase, kind = first
    target, other = second
    assume(other != kind)
    text = f"{lead}{phrase}{day}{join}{link} to {target}"
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert not (result.kind == kind and result.confidence >= 0.7), text


# A verb's own "to" after a status is no change: "Early dismissal today at 1 PM with the Learning
# Center to open at 10 AM" says what the center does, not that the dismissal became an opening.
VERB_TO = [
    ("2 hour delay tomorrow with the Learning Center to open at 10 AM", "delayed"),
    ("2 hour delay tomorrow, the office to close at noon", "delayed"),
    ("Late start tomorrow and buses to start at 9", "delayed"),
    ("Remote learning tomorrow, the clinic to reopen at 11", "remote"),
    ("Early dismissal today at 1 PM with the gym to open at 3 PM", "early_dismissal"),
    ("Closing early today at 12:30, the office to close at noon", "early_dismissal"),
]


@pytest.mark.parametrize(("text", "kind"), VERB_TO)
def test_a_verb_s_own_to_after_a_status_changes_nothing(text: str, kind: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == kind
    assert "superseded" not in result.notes


@settings(max_examples=400, deadline=None)
@given(
    first=st.sampled_from(
        (
            ("Early dismissal today at 1 PM", "early_dismissal"),
            ("2 hour delay tomorrow", "delayed"),
            ("Remote learning tomorrow", "remote"),
            ("Late start tomorrow", "delayed"),
            ("Closing early today at 12:30", "early_dismissal"),
        )
    ),
    join=st.sampled_from((" with ", ", ", " and ")),
    noun=st.sampled_from(("the Learning Center", "the office", "the clinic", "buses", "the gym")),
    verb=st.sampled_from(
        ("open at 10 AM", "close at noon", "reopen at 11", "start at 9", "begin at 10:30")
    ),
)
def test_a_verb_s_own_to_never_hands_the_day_to_another_status(
    first: tuple[str, str], join: str, noun: str, verb: str
) -> None:
    phrase, kind = first
    text = f"{phrase}{join}{noun} to {verb}"
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert "superseded" not in result.notes, text
    assert result.kind == kind or (result.kind == "other" and result.confidence <= 0.3), text


# "Later" ends a subject only right before a status ("Closed, later a 2 hour delay"). Before an
# update's words it is part of them, and the status they are about is a side note: "Check back
# later for updates on the closure of Main Street" says where news will come, not a closure.
LATER_NOTES = [
    "Check back later for updates on the closure of Main Street",
    "More information later on the graduation delay",
    "Details later on the delay in report cards",
    "Information later on the closure of Highway 9",
    "Details later on the power outage closure at the stadium",
    "Check back later for updates on the closure of the gym",
    "Watch for updates later on the closure tomorrow",
    "Tomorrow: Check back later for updates on the 2 hour delay",
]


@pytest.mark.parametrize("text", LATER_NOTES)
def test_a_status_after_later_and_an_update_s_words_is_no_status(text: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other"
    assert result.confidence <= 0.3


def test_today_closed_and_tomorrow_to_check_later_is_today_s_closure_alone() -> None:
    # Posted Thursday evening: the closure is Thursday's; tomorrow's slot only says to check.
    posted = datetime(2026, 1, 22, 19, 45, tzinfo=ZONE)
    text = "(TODAY) CLOSED | (TOMORROW) CHECK LATER FOR UPDATES Closed."
    result = parse_status(text, posted_at=posted, tz=TZ)
    assert date(2026, 1, 23) not in result.dates
    assert result.kind == "other" or result.dates == jan(22)


@settings(max_examples=300, deadline=None)
@given(
    lead=st.sampled_from(
        (
            "Check back later", "More information later", "Details later",
            "Watch for updates later", "Information to follow later", "We will post more later",
            "Updates will be posted later", "Look for news afterwards",
        )
    ),
    preposition=st.sampled_from(("on", "about", "regarding", "for", "of", "concerning")),
    noun=st.sampled_from(
        ("graduation", "Main Street", "report card", "stadium", "bus route", "gym", "concert")
    ),
    status=st.sampled_from(
        ("closure", "delay", "cancellation", "early dismissal", "closing", "2 hour delay")
    ),
)  # fmt: skip
def test_a_status_after_later_and_a_preposition_is_never_sure(
    lead: str, preposition: str, noun: str, status: str
) -> None:
    text = f"{lead} {preposition} the {noun} {status}"
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other" or result.confidence < 0.7, text


# A status traded for another by a verb with "for", "with" or "in favor of": as with "to", the
# text does not say for sure which holds ("Closure swapped for a 2 hour delay", "Closure
# substituted with a 2 hour delay", "Closure dropped in favor of a 2 hour delay").
TRADED = [
    "Closure swapped for a 2 hour delay", "Closure traded for a 2 hour delay",
    "Closure exchanged for a 2 hour delay", "Closure substituted with a 2 hour delay",
    "Closure dropped for a 2 hour delay", "Closure dropped in favor of a 2 hour delay",
    "Closure abandoned for a 2 hour delay", "Closed today, swapped for a 2 hour delay",
    "2 hour delay swapped for a closure", "2 hour delay traded for a closure",
]  # fmt: skip


@pytest.mark.parametrize("text", TRADED)
def test_a_status_traded_for_another_is_no_status(text: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other"
    assert result.confidence <= 0.3


@settings(max_examples=400, deadline=None)
@given(
    first=st.sampled_from(FIRST),
    verb=st.sampled_from(
        ("swapped", "traded", "exchanged", "substituted", "dropped", "abandoned", "passed over",
         "set aside", "replaced")
    ),
    link=st.sampled_from(("to", "into", "for", "with", "in favor of", "in favour of")),
    second=st.sampled_from(SECOND),
    join=st.sampled_from((" ", ", ", " - ")),
    day=st.sampled_from(("", " today", " tomorrow")),
)  # fmt: skip
def test_a_status_traded_for_another_is_never_the_first_for_sure(  # noqa: PLR0913, PLR0917
    first: tuple[str, str], verb: str, link: str, second: tuple[str, str], join: str, day: str
) -> None:
    phrase, kind = first
    target, other = second
    assume(other != kind)
    text = f"{phrase}{day}{join}{verb} {link} {target}"
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert not (result.kind == kind and result.confidence >= 0.7), text
