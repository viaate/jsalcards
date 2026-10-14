"""The precision gate reads names where names stand, and the prose around a status.

Every text here is a phrasing pattern written for these tests, not a claim about a
real school; the names are made up from syllables. Unless a row says otherwise it is
posted at 6 a.m. on Wednesday 21 January 2026 in Chicago, so "today" is Wednesday the
21st, "tomorrow" Thursday the 22nd and "Friday" the 23rd.

Archived station and district listings name their schools, towns, programs and
storms, and write prose around the status. A word no rule reads is a name's where a
name stands (see ``snowlight.classify.gate.unread_sentence``): before the noun that
ends it ("Kubaze Learning Center"), in a list that such a noun ends or that runs into
a side note's subject, in a label at a sentence's start before a colon, a dash or a
slash (or a comma, after a list joined by "and" or "&"), after a word that opens one
("including", "no" outside a status, "at", "in", "of", "from" or "on" after a noun of
a place or of who is affected, "in" after a status or a day, "for" after a noun that
ends a name, "hurricane", "fort"), the subject of a place said to be open ("Kubaze will
be open"), and a web address. Anywhere else it could say anything of the status, and
the listing stays ``other``. So does a word that ends in "ly" in those places but
before a noun ("including Kubaze, allegedly"), a label that holds another word ("Kubaze
update: closed"), a word alone before a comma ("Kubaze, closed"), and hearsay beside a
status ("per unconfirmed reports").
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from snowlight.classify import parse_status

TZ = "America/Chicago"
ZONE = ZoneInfo(TZ)
WED = datetime(2026, 1, 21, 6, 0, tzinfo=ZONE)


def jan(*days: int) -> tuple[date, ...]:
    return tuple(date(2026, 1, day) for day in days)


# Names where names stand, and the prose that says nothing of the status: forms archived
# listings hold, rephrased with made-up names.
NAMED = [
    # A label before a colon, a dash or a slash.
    ("Kubaze - Closed", "closed", jan(21)),
    ("Kubaze and Lomira -- 2 hour delay", "delayed", jan(21)),
    ("Montessori School of Kubaze - Closed tomorrow", "closed", jan(22)),
    ("Kubaze / NTI Day", "remote", jan(21)),
    ("Lomira: Closed tomorrow", "closed", jan(22)),
    # A list's label before a comma: its names are joined by "and" or "&".
    ("Kubaze and Lomira, 2 hours late", "delayed", jan(21)),
    ("Kubaze & Lomira, closed tomorrow", "closed", jan(22)),
    # A list that a noun ends, or that runs into a side note's subject.
    ("Kubaze, Lomira and Tavi schools closed tomorrow", "closed", jan(22)),
    ("Closed tomorrow; Kubaze families please check email", "closed", jan(22)),
    ("Closed today; Kubaze services Sunday", "closed", jan(21)),
    # After a word that opens a name.
    ("Closed today, including Kubaze", "closed", jan(21)),
    ("Two hour delay, no AM Kubaze", "delayed", jan(21)),
    ("Closed today. Childcare at Kubaze is open.", "closed", jan(21)),
    ("Classes at 200 Kubaze St are remote today", "remote", jan(21)),
    ("Centers closed today in Kubaze, Lomira and Tavi", "closed", jan(21)),
    ("Hurricane Kubaze update: schools closed tomorrow", "closed", jan(22)),
    ("Closed tomorrow at Fort Kubaze", "closed", jan(22)),
    ("Closed tomorrow, no Kubaze program Friday", "closed", jan(22)),
    # The subject of a place said to be open, and a web address.
    ("Closed today; Kubaze will be open", "closed", jan(21)),
    ("Closed today; Lomira Club open", "closed", jan(21)),
    ("Closed tomorrow. Details at kubaze.org", "closed", jan(22)),
    ("Remote learning today, visit kubaze.lomira.edu/alerts", "remote", jan(21)),
    # Prose: what is said and where, health, travel, work, the cleanup, courtesy, events.
    ("2 hour delay; any changes to the schedule will be communicated by 6 AM", "delayed", jan(21)),
    ("Closed today. Families should dress warmly and stay safe.", "closed", jan(21)),
    (
        "Closed today. Tickets purchased for today will be refunded automatically.",
        "closed",
        jan(21),
    ),
    ("Remote learning today; students should check Canvas for assignments", "remote", jan(21)),
    ("Closed today. Crews are visiting all sites to assess damage.", "closed", jan(21)),
    ("Closed tomorrow; staff should use their best judgment when traveling", "closed", jan(22)),
    (
        "Closed today and tomorrow; school resumes Monday once cleanup is complete",
        "closed",
        jan(21, 22),
    ),
    ("Closed today; no soup supper tonight", "closed", jan(21)),
    ("Closed indefinately", "closed", jan(21)),
    ("Closed today. In Kubaze, buses will not run.", "closed", jan(21)),
    ("Closed today; early voting sites may vary", "closed", jan(21)),
    ("Virtual learning today; tax deadline extended to Friday", "remote", jan(21)),
    (
        "After consulting with local officials, Kubaze ISD is canceling classes for Friday.",
        "closed",
        jan(23),
    ),
    ("Out of an overabundance of caution, closed tomorrow.", "closed", jan(22)),
    ("Closing at noon today; Ash Wednesday service still on", "early_dismissal", jan(21)),
    ("Closed tomorrow; deliberative session moved to Friday", "closed", jan(22)),
]


@pytest.mark.parametrize(("text", "kind", "dates"), NAMED)
def test_a_name_where_a_name_stands_and_plain_prose_keep_the_status(
    text: str, kind: str, dates: tuple[date, ...]
) -> None:
    result = parse_status(text, posted_at=WED, tz=TZ)
    assert (result.kind, result.dates) == (kind, dates)
    assert result.confidence >= 0.7
    assert "unread_words" not in result.notes


# Words in those places that are no name, and statements beside a status that no rule read.
NOT_NAMED = [
    "Closed tomorrow including Kubaze, allegedly", "Allegedly - closed tomorrow",
    "Prediction: closed tomorrow", "Draft - 2 hour delay tomorrow",
    "Kubaze update: closed tomorrow",
    "Closed tomorrow per unconfirmed reports", "Closed tomorrow in theory",
    "Closed tomorrow -- not true", "Closed tomorrow - not correct", "Closed tomorrow or delayed",
    "No school tomorrow, no wait, 2 hour delay", "Closed tomorrow. Update: Kubaze open tomorrow.",
    "Kubaze closed tomorrow", "Closed tomorrow walrus", "Closed tomorrow, technically",
    "Closed tomorrow - Kubaze parade", "No school Friday - parade",
    "Kubaze - closed tomorrow - kayak", "Kubaze, closed tomorrow", "Closed tomorrow kubaze.walrus",
]  # fmt: skip


@pytest.mark.parametrize("text", NOT_NAMED)
def test_a_word_where_no_name_stands_leaves_no_confident_status(text: str) -> None:
    result = parse_status(text, posted_at=WED, tz=TZ)
    assert result.kind == "other"
    assert result.confidence <= 0.3


# A status in place of another one ("instead"), and a scope after "only for".
REPLACED = [
    ("Closed tomorrow; 2 hour delay instead", "delayed", jan(22)),
    ("No school tomorrow; 2 hour delay instead", "delayed", jan(22)),
    ("2 hour delay tomorrow; closed instead", "closed", jan(22)),
]


@pytest.mark.parametrize(("text", "kind", "dates"), REPLACED)
def test_a_status_instead_of_another_replaces_it(
    text: str, kind: str, dates: tuple[date, ...]
) -> None:
    result = parse_status(text, posted_at=WED, tz=TZ)
    assert (result.kind, result.dates) == (kind, dates)
    assert "superseded" in result.notes


# A status that names no day beside one denied for a day: that day is the one it is for.
LENT = [
    ("No closure tomorrow; 2 hour delay instead", "delayed", jan(22)),
    ("Not closing tomorrow, but 2 hour delay", "delayed", jan(22)),
    ("Closed. No distance learning on Friday", "closed", jan(23)),
    ("2 Hour Delay - Tomorrow No Early Dismissal", "delayed", jan(22)),
    ("No school delays today; closed", "closed", jan(21)),
]


@pytest.mark.parametrize(("text", "kind", "dates"), LENT)
def test_a_status_naming_no_day_is_for_the_day_of_one_denied(
    text: str, kind: str, dates: tuple[date, ...]
) -> None:
    result = parse_status(text, posted_at=WED, tz=TZ)
    assert (result.kind, result.dates) == (kind, dates)
    assert result.confidence >= 0.7


def test_a_status_naming_no_day_beside_one_only_possible_takes_no_day_from_it() -> None:
    result = parse_status("Possible closure Friday. 2 hour delay.", posted_at=WED, tz=TZ)
    assert 23 not in [day.day for day in result.dates]


def test_a_delay_only_for_the_buses_is_no_late_start() -> None:
    result = parse_status("Delay only for buses tomorrow", posted_at=WED, tz=TZ)
    assert result.kind == "other"
    assert "transportation" in result.notes


def test_the_school_and_its_campus_open_is_the_school_open() -> None:
    result = parse_status(
        "Closed tomorrow. Update: school and campus open tomorrow.", posted_at=WED, tz=TZ
    )
    assert result.kind == "other"
    assert result.says_open


def test_today_and_tomorrow_posted_after_midnight_with_the_school_open_are_unclear() -> None:
    # Written the evening before, "today" is the day before and "tomorrow" the posting day; or
    # written after midnight, the posting day and the day after: no day can be told.
    text = "(TODAY) SCHOOL & CAMPUS CLOSED ALL DAY. | (TOMORROW) SCHOOL & CAMPUS OPEN"
    result = parse_status(text, posted_at=datetime(2026, 1, 21, 0, 3, tzinfo=ZONE), tz=TZ)
    assert result.kind == "other"
    assert result.confidence < 0.7
