"""A later sentence that names a status's day again, or says more may come of its days.

Every text here is a phrasing pattern written for these tests, not a claim
about a real school. Unless a row says otherwise it is posted at 6 a.m. on
Wednesday 21 January 2026 in Chicago, so "today" is Wednesday the 21st,
"tomorrow" Thursday the 22nd and "Friday" the 23rd.

Once a status names its days, a sentence after it that names one of them
again either restates the status ("Closed Thursday and Friday. Friday closed
too."), says what else the day holds (a side note: "Friday's practice is
cancelled"; a part of the program; a service), or says the day is not settled.
The rules read the first two. Any other such sentence says something of the day
that no rule read: the day may be only possible ("Tomorrow might be virtual"),
still to be decided ("Friday will be evaluated tomorrow", "A decision about
Friday will be made tomorrow", "Tomorrow is up in the air", "Friday: will
advise"), or something else ("Buses will run Friday", "Friday is a full day").
Such a listing is ``other`` at 0.3: ``hedged`` when a status only possible
stands in the sentence, else ``unread_words``. A sentence whose words but the
days only add or repeat days ("Friday as well"), name who or what else
("No services Friday"), name the day the listing is for ("(For Fri. Jan 23)") or
are prose that says nothing of whether it may change ("Tickets purchased for
today will be refunded automatically") leaves the status standing.

A promise of an update after statuses for several days ("Closed today and
tomorrow, will update tonight", "Closed Thursday and Friday, update at 5am",
"..., stay tuned") leaves the days after the first open in the same way.

A day named again in a sentence of its own ("Closed Friday. Friday.") adds
nothing, and a day of its own there with no word that adds it ("Closed
Thursday. Friday.", "Closed Thursday. As for Friday, stay tuned.") is left out:
no list read across sentences can put the status's own weekdays in the week
before the posting.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from snowlight.classify import parse_status

TZ = "America/Chicago"
ZONE = ZoneInfo(TZ)
MORNING = datetime(2026, 1, 21, 6, 0, tzinfo=ZONE)  # Wednesday
EVENING = datetime(2026, 1, 21, 20, 0, tzinfo=ZONE)
SATURDAY = datetime(2026, 1, 24, 10, 0, tzinfo=ZONE)


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
    kind: str = "other",
    dates: tuple[date, ...] = (),
    *,
    posted: datetime = MORNING,
    confidence: float = 0.95,
    notes: tuple[str, ...] = (),
) -> object:
    label = f"{text} @ {posted:%a %H:%M}"
    return pytest.param(Row(text, posted, kind, dates, confidence, notes), id=label)


def hedged(text: str, *, posted: datetime = MORNING) -> object:
    """A status beside a sentence that says one of its days is only possible."""
    return row(text, posted=posted, confidence=0.3, notes=("hedged",))


def unread(text: str, *, posted: datetime = MORNING) -> object:
    """A status beside a sentence about one of its days that no rule read."""
    return row(text, posted=posted, confidence=0.3, notes=("unread_words",))


def check(case: Row) -> None:
    result = parse_status(case.text, posted_at=case.posted, tz=TZ)
    assert result.kind == case.kind
    assert result.dates == case.dates
    assert result.confidence == case.confidence
    assert set(case.notes) <= set(result.notes)
    if case.kind == "other":
        assert result.schedule == ()


# A later sentence that says one of the status's days is only possible.
POSSIBLE = [
    hedged("Closed today and tomorrow. Tomorrow might be virtual."),
    hedged("Closed today and tomorrow. Tomorrow may be virtual."),
    hedged("Closed today and tomorrow. Tomorrow could be a 2 hour delay."),
    hedged("Closed today and tomorrow. Tomorrow might be an NTI day."),
    hedged("Closed today and tomorrow. Tomorrow possibly virtual."),
    hedged("Closed today and tomorrow. Tomorrow likely virtual."),
    hedged("Closed today and tomorrow. Tomorrow may switch to virtual."),
    hedged("Closed Thursday and Friday; Friday might be virtual"),
    hedged("Closed Thursday and Friday; Friday might be remote"),
    hedged("Closed Thursday and Friday; Friday may be an eLearning day"),
    hedged("Closed Thursday and Friday; Friday could be NTI"),
    hedged("Closed Thursday and Friday; Friday may have a delay"),
    hedged("Closed Thursday and Friday; Friday may be an early dismissal"),
    hedged("Closed Thursday and Friday; Friday may be a half day"),
    hedged("Closed tomorrow. Tomorrow might be virtual."),
    hedged("2 hour delay today and tomorrow. Tomorrow could be closed."),
    hedged("NTI day Thursday and Friday. Friday may be a snow day."),
    hedged("Closed Thursday and Friday. Friday may be a delay instead."),
    hedged("Closed Thursday and Friday. Friday may become a delay"),
    hedged("Closed today and tomorrow. Tomorrow might be virtual.", posted=EVENING),
    # The day's status said to be possibly called off or changed: the day is in doubt.
    hedged("Closed today and tomorrow. Tomorrow's closure may be lifted."),
    hedged("Closed today and tomorrow. Tomorrow's closure could be cancelled."),
    hedged("Closed today and tomorrow. Tomorrow's closure is subject to change."),
    hedged("Closed Monday and Tuesday. Tuesday's closure may be lifted.", posted=SATURDAY),
    hedged("Closed Monday and Tuesday. Tuesday's closure could be lifted.", posted=SATURDAY),
    hedged("Closed Monday and Tuesday. The Tuesday closure may be lifted.", posted=SATURDAY),
]

# A decision to come about one of the status's days, by name ("we will reassess Friday
# tomorrow", "reassess tomorrow's status tonight") or as the last day it names ("will reassess
# Friday."): that day is in doubt, and the other days stand as a judgment call.
REASSESSED = [
    row("Closed Thursday and Friday; we will reassess Friday tomorrow", "closed", jan(22),
        confidence=0.8, notes=("hedged",)),
    row("Closed Thursday and Friday; we will reassess Friday", "closed", jan(22),
        confidence=0.8, notes=("hedged",)),
    row("Closed today and tomorrow. We will reassess tomorrow's status tonight.", "closed",
        jan(21), confidence=0.8, notes=("hedged",)),
    row("Closed today and tomorrow. We will reassess tomorrow tonight.", "closed", jan(21),
        confidence=0.8, notes=("hedged",)),
    row("Closed today and tomorrow. Will reassess tomorrow.", "closed", jan(21),
        confidence=0.8, notes=("hedged",)),
    row("Closed today and tomorrow; reassessing tomorrow tonight", "closed", jan(21),
        confidence=0.8, notes=("hedged",)),
    row("Possible closure tomorrow. Closed today and tomorrow.", "closed", jan(21),
        confidence=0.8, notes=("hedged",)),
    # A decision at a time of the day, or about days the status does not name: it stands.
    row("Closed today. We will reassess tomorrow.", "closed", jan(21)),
    row("Closed tomorrow. We will reassess tomorrow afternoon.", "closed", jan(22)),
]  # fmt: skip

# A later sentence that says one of the status's days is still to be decided.
UNDECIDED = [
    unread("Closed Thursday and Friday. Friday will be evaluated tomorrow."),
    unread("Closed Thursday and Friday. A decision about Friday will be made tomorrow."),
    unread("Closed Thursday and Friday; Friday's status will be reviewed tomorrow."),
    unread("Closed Thursday and Friday; Friday will be reassessed"),
    unread("Closed today and tomorrow; tomorrow will be reassessed tonight."),
    unread("Closed today and tomorrow; tomorrow will be re-evaluated tonight."),
    unread("Closed today and tomorrow. Tomorrow is up in the air."),
    unread("Closed Thursday and Friday. Friday is up in the air."),
    unread("Closed Thursday and Friday. Friday is still up in the air."),
    unread("Closed today and tomorrow. Tomorrow: we'll see."),
    unread("Closed Thursday and Friday. Friday: no word yet."),
    unread("Closed Thursday and Friday. Friday: don't know yet."),
    unread("Closed Thursday and Friday. Friday: check back tomorrow."),
    unread("Closed Thursday and Friday. Friday: will advise."),
    unread("Closed Thursday and Friday. Friday: we will advise tomorrow."),
    unread("Closed Thursday and Friday. Will notify families about Friday."),
    unread("Closed Thursday and Friday. Families will be notified about Friday."),
    unread("Closed Thursday and Friday. Friday is a game-time decision."),
    unread("Closed Thursday and Friday. Friday depending on conditions."),
    unread("Closed Thursday and Friday. We'll update about Friday tomorrow."),
    unread("Closed Thursday and Friday. Friday will be communicated tomorrow."),
    unread("Closed Thursday and Friday. More on Friday tomorrow."),
    unread("Closed Thursday and Friday. Friday: more info tomorrow."),
    unread("Closed Thursday and Friday. Friday: hope to reopen."),
    unread("2 hour delay Thursday and Friday. Friday will be reviewed tonight."),
    unread("Closed Thursday and Friday. Friday will be evaluated tomorrow.", posted=EVENING),
]

# A clause of a day the status names, with words of its own after it.
DAY_THEN_WORDS = [
    unread("Closed Thursday and Friday. Friday, stay tuned."),
    unread("Closed Thursday and Friday. As for Friday, we'll see."),
    unread("Closed Thursday and Friday. As for Friday, stay tuned."),
    unread("Closed Thursday and Friday. As for Friday, check back tomorrow."),
    unread("Closed Thursday and Friday. For Friday, stay tuned."),
    unread("Closed Thursday and Friday. On Friday, stay tuned."),
    unread("Closed Thursday and Friday. Friday, more info later."),
    unread("2 hour delay Thursday and Friday. As for Friday, stay tuned."),
    unread("Closed Thursday and Friday. Friday, stay tuned.", posted=EVENING),
    unread("Closed Thursday and Friday. As for Friday, we'll see.", posted=EVENING),
    unread("Closed Thursday. Thursday, stay tuned."),
]

# A later sentence that says something else of the day, which no rule read: school held,
# a full day.
SOMETHING_ELSE = [
    unread("Closed Thursday and Friday. Buses will run Friday."),
    unread("Closed Thursday and Friday. Friday full day."),
    unread("Closed Thursday and Friday. Friday is a full day."),
    unread("Closed today, tomorrow and Friday. Update: Friday is a full day."),
]

# A promise of an update after statuses for several days.
PROMISED = [
    unread("Closed today and tomorrow, will update tonight"),
    unread("Closed today and tomorrow - will update tonight"),
    unread("Closed Thursday and Friday, update at 5am"),
    unread("Closed Thursday and Friday, stay tuned"),
    unread("Closed Thursday and Friday. Stay tuned."),
    row("Closed today, Thursday and Friday, will update tonight", confidence=0.3),
    unread("Closed today through Friday. Updates to follow."),
    unread("2 hour delay today and tomorrow. Check back tonight."),
    # (A dash parts no promise from the days before it.)
    unread("Closed today and tomorrow - stay tuned"),
    unread("Closed today and tomorrow - check back for updates"),
]

# A day the status names again with words that only add or repeat days, say who or what else
# the day holds none of, name the day the listing is for, or say nothing of a change.
STANDING = [
    row("Closed Friday. Friday.", "closed", jan(23)),
    row("Closed Thursday and Friday. Friday.", "closed", jan(22, 23)),
    row("Closed Thursday and Friday. Friday as well.", "closed", jan(22, 23)),
    row("Closed Thursday and Friday. Friday too.", "closed", jan(22, 23)),
    row("Closed Thursday and Friday. Friday closed too.", "closed", jan(22, 23)),
    row("Closed Thursday and Friday. Jan. 23.", "closed", jan(22, 23)),
    row("Closed tomorrow. Jan. 22.", "closed", jan(22)),
    row("Closed Friday; No Friday services", "closed", jan(23)),
    row("Closed Thursday and Friday. No services Friday.", "closed", jan(22, 23)),
    row("Closed Thursday (For Thu. Jan 22)", "closed", jan(22)),
    row("Closed today. Tickets purchased for today will be refunded automatically.",
        "closed", jan(21)),
    row("Closed tomorrow. School will not run tomorrow.", "closed", jan(22)),
    row("Closed today. Will update tonight.", "closed", jan(21)),
    row("Closed tomorrow. Stay tuned for updates.", "closed", jan(22)),
    row("Closed Thursday and Friday. Friday's practice is cancelled.", "closed", jan(22, 23),
        notes=("activities_cancelled",)),
    row("Tuesday Morning: Closed | Tuesday Afternoon: No Services", "closed", jan(20),
        posted=datetime(2026, 1, 20, 5, 30, tzinfo=ZONE)),
]  # fmt: skip

# A day of a sentence of its own, with no word that adds it, is no status's.
LEFT_OUT = [
    row("Closed Thursday. Friday.", "closed", jan(22)),
    row("Closed today. Tomorrow.", "closed", jan(21)),
    row("Closed Thursday. As for Friday, stay tuned.", "closed", jan(22)),
    row("Closed Thursday. Friday depending on conditions.", "closed", jan(22)),
    row("Closed today. Also tomorrow.", "closed", jan(21, 22)),
    row("Closed today. Tomorrow as well.", "closed", jan(21, 22)),
]

# "Only" in a later sentence that no rule read, beside statuses for several days.
ONLY = [
    row("Closed today and tomorrow. Update: the only day closed is today", confidence=0.3,
        notes=("ambiguous",)),
    row("Closed today and tomorrow. Update: closed today only", "closed", jan(21),
        confidence=0.8, notes=("superseded",)),
]  # fmt: skip


@pytest.mark.parametrize("case", POSSIBLE)
def test_a_later_sentence_that_a_listed_day_is_only_possible(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", UNDECIDED)
def test_a_later_sentence_that_a_listed_day_is_undecided(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", REASSESSED)
def test_a_decision_to_come_about_a_listed_day_leaves_it_out(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", DAY_THEN_WORDS)
def test_a_listed_day_with_words_of_its_own_after_it(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", SOMETHING_ELSE)
def test_a_later_sentence_that_says_something_else_of_a_listed_day(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", PROMISED)
def test_an_update_promised_after_statuses_for_several_days(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", STANDING)
def test_a_listed_day_named_again_with_nothing_unread(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", LEFT_OUT)
def test_a_day_of_its_own_in_a_later_sentence(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", ONLY)
def test_only_in_a_later_sentence(case: Row) -> None:
    check(case)


# Properties --------------------------------------------------------------------------------

STATUSES = ("Closed", "No school", "2 hour delay", "NTI day", "Remote learning", "Snow day")
OTHER_STATUSES = ("virtual", "a 2 hour delay", "an NTI day", "closed", "an early dismissal",
                  "a snow day", "remote", "an eLearning day")  # fmt: skip
HEDGE_WORDS = ("may", "might", "could", "possibly", "likely", "may still", "could also")
# Two days the status names, posted on each weekday of a week, morning and evening.
PAIRS = (("today", "tomorrow"), ("Thursday", "Friday"), ("Monday", "Tuesday"),
         ("Tuesday", "Wednesday"), ("Wednesday", "Thursday"), ("Friday", "Monday"))  # fmt: skip
POSTINGS = st.builds(
    lambda day, hour: datetime(2026, 1, 19, hour, 0, tzinfo=ZONE) + timedelta(days=day),
    st.integers(0, 6),
    st.sampled_from((6, 20)),
)
# Words around a day the status names, in a sentence of their own, that no rule reads as the
# status: hedges, decisions to come, promises of more, and the like.
LEADS = ("", "As for ", "For ", "On ", "Regarding ", "About ")
CLOSERS = (", stay tuned", ", we'll see", ", check back tomorrow", ", more info later",
           " will be evaluated", " is up in the air", ": will advise", " depends on the roads",
           ": decision tomorrow", " is still to be decided")  # fmt: skip


def _week_start(posted: datetime) -> date:
    day = posted.date()
    return day - timedelta(days=day.weekday())


@settings(max_examples=500, deadline=None)
@given(
    status=st.sampled_from(STATUSES),
    pair=st.sampled_from(PAIRS),
    hedge=st.sampled_from(HEDGE_WORDS),
    other=st.sampled_from(OTHER_STATUSES),
    posted=POSTINGS,
)
def test_a_hedged_later_day_is_never_confident(
    status: str, pair: tuple[str, str], hedge: str, other: str, posted: datetime
) -> None:
    first, second = pair
    verb = "" if hedge in {"possibly", "likely"} else " be"
    text = f"{status} {first} and {second}. {second.capitalize()} {hedge}{verb} {other}."
    result = parse_status(text, posted_at=posted, tz=TZ)
    assert result.confidence < 0.7 or ("hedged" not in result.notes and len(result.dates) < 2), text


@settings(max_examples=500, deadline=None)
@given(
    status=st.sampled_from(STATUSES),
    pair=st.sampled_from(PAIRS),
    lead=st.sampled_from(LEADS),
    closer=st.sampled_from(CLOSERS),
    posted=POSTINGS,
)
def test_a_listed_day_said_again_never_moves_the_days_or_stays_sure(
    status: str, pair: tuple[str, str], lead: str, closer: str, posted: datetime
) -> None:
    first, second = pair
    day = second if lead else second.capitalize()
    text = f"{status} {first} and {second}. {lead}{day}{closer}."
    result = parse_status(text, posted_at=posted, tz=TZ)
    assert result.confidence < 0.7, text
    for scheduled in result.schedule:
        for listed in scheduled.dates:
            assert listed >= _week_start(posted), text


# Sentences that leave the second of two listed days in doubt: a decision to come about it, or
# its status possibly called off or changed ({day}: the day as named; {days}: its possessive).
DOUBTS = (
    "We will reassess {day} tonight.", "We will reassess {days} status tonight.",
    "Will reassess {day}.", "{Days} closure may be lifted.", "{Days} closure could be cancelled.",
    "{Day} might be virtual.", "{Day} may be a 2 hour delay.",
    "{Days} closure is subject to change.",
    "{Day} is up in the air.", "{Day} will be reassessed tonight.",
    "{Days} closure will be reviewed tonight.", "{Days} closure might be cancelled.",
)  # fmt: skip


@settings(max_examples=500, deadline=None)
@given(
    status=st.sampled_from(("Closed", "No school", "Snow day", "NTI day", "Remote learning")),
    pair=st.sampled_from((("today", "tomorrow"), ("Thursday", "Friday"))),
    doubt=st.sampled_from(DOUBTS),
)
def test_a_listed_day_in_doubt_is_never_a_sure_day(
    status: str, pair: tuple[str, str], doubt: str
) -> None:
    first, second = pair
    text = f"{status} {first} and {second}. " + doubt.format(
        day=second,
        days=f"{second}'s",
        Day=second.capitalize(),
        Days=f"{second.capitalize()}'s",
    )
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    doubted = date(2026, 1, 22 if second == "tomorrow" else 23)
    assert result.confidence < 0.7 or doubted not in result.dates, text
    if result.confidence >= 0.7 and "hedged" in result.notes:
        assert doubted not in result.dates, text
