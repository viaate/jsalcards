"""Malformed or placeholder values where a day, an answer or a time should be.

Every text here is a phrasing pattern written for these tests, not a claim
about a real school. Unless a row says otherwise it is posted at 6 a.m. on
Wednesday 21 January 2026 in Chicago, so "today" is Wednesday the 21st and
"tomorrow" Thursday the 22nd.

A day number whose ordinal ending disagrees with it ("the 2rd", "the 3th",
"Jan 22st") names no day anyone can trust: the listing is ``other`` at 0.3
(note ``unreadable_date``), as any day the parser cannot read is. One whose ending
agrees ("1st", "2nd", "3rd", "11th", "22nd", "23rd") is read as before.

A day held by a placeholder ("Closed (date TBD)", "Closure date: TBD", "Closed on
N/A", "Closed - date to be announced") or a template's slot never filled in ("Closed
{date}", "Closed [DATE]", "2 hour delay on %DATE%", "Closed on <date>", "Closed %s",
"Closed ___", "_ hour delay") is a day or a length no one wrote: the listing is ``other``
at 0.3 (note ``unreadable_date``).

A form's field answered no in any of its forms ("Closed: N", "Delayed: N",
"Closed=false", "closed=0", "Delay: 0:00", "00:00 delay") denies the status, as
"Closed: No" does; a field left empty ("Closed:") answers nothing (``other`` at 0.3).

A post that says it is a test or an old post ("This is a test.", "Test message",
"(test)", "ARCHIVE:"), a status's odds ("Snow day chance: 90%"), a status word with
a prefix that makes it something else ("Non-closed", "Post-closure update"), and a
link to a status's page ("Click here for the 2 hour delay schedule", "eLearning day
plans") state no status.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from snowlight.classify import parse_status

TZ = "America/Chicago"
ZONE = ZoneInfo(TZ)
MORNING = datetime(2026, 1, 21, 6, 0, tzinfo=ZONE)  # Wednesday


def jan(*days: int) -> tuple[date, ...]:
    return tuple(date(2026, 1, day) for day in days)


BAD_ORDINALS = [
    "Closed the 2rd", "Closed the 2st", "Closed the 3th", "Closed the 1th",
    "Closed Thursday and the 2rd", "Closed today and the 23nd", "Closed Jan 22rd",
    "Closed Jan 22st", "Closed the 12nd", "2 hour delay on the 23th", "Closed Monday, Jan 26st",
]  # fmt: skip


@pytest.mark.parametrize("text", BAD_ORDINALS)
def test_a_day_number_with_an_ending_that_disagrees_is_no_day(text: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other"
    assert result.confidence <= 0.3
    assert "unreadable_date" in result.notes


GOOD_ORDINALS = [
    ("Closed Jan 22nd", jan(22)), ("Closed the 22nd", jan(22)), ("Closed Jan 23rd", jan(23)),
    ("Closed Jan 21st", jan(21)), ("Closed Monday, Jan 26th", jan(26)),
]  # fmt: skip


@pytest.mark.parametrize(("text", "dates"), GOOD_ORDINALS)
def test_a_day_number_with_its_own_ending_is_read(text: str, dates: tuple[date, ...]) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "closed"
    assert result.dates == dates
    assert result.confidence >= 0.7


def ending(number: int) -> str:
    """The ordinal ending a number takes (worked out here, as a reader would)."""
    if 11 <= number % 100 <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")


@settings(max_examples=400, deadline=None)
@given(
    number=st.integers(1, 31),
    suffix=st.sampled_from(("st", "nd", "rd", "th")),
    form=st.sampled_from(
        ("Closed the {}", "Closed Jan {}", "Closed Feb {}", "2 hour delay the {}")
    ),
)
def test_an_ordinal_ending_must_agree_with_its_number(number: int, suffix: str, form: str) -> None:
    result = parse_status(form.format(f"{number}{suffix}"), posted_at=MORNING, tz=TZ)
    if suffix != ending(number):
        assert result.kind == "other"
        assert "unreadable_date" in result.notes
    else:
        assert "unreadable_date" not in result.notes


PLACEHOLDERS = [
    "Closed (date TBD)", "Closed - date to be announced", "Closure date: TBD", "Closed on TBD",
    "Closed on N/A", "Closed {date}", "Closed [DATE]", "Closed %DATE%", "Closed on <date>",
    "2 hour delay on {date}", "Closed on TBA", "Closed: date TBA", "Closed on [date]",
    "Closed {{date}}", "Early dismissal on [Insert date]", "Closed until TBD",
    "NTI day {weekday}", "Closed - date is still to be determined", "Closed %s", "Closed on %s",
    "Closed %d", "Closed ___", "Closed _____ due to snow", "_ hour delay",
]  # fmt: skip

# Marks beside words that are no slot: a percent after a number, an underscore inside a word.
NOT_SLOTS = ["Closed today. 50% chance of snow", "Closed today_", "Closed __today__"]


@pytest.mark.parametrize("text", NOT_SLOTS)
def test_a_mark_that_is_no_slot_leaves_the_status(text: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "closed"
    assert result.confidence >= 0.7


@pytest.mark.parametrize("text", PLACEHOLDERS)
def test_a_day_held_by_a_placeholder_or_a_template_slot_is_no_day(text: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other"
    assert result.confidence <= 0.3
    assert "unreadable_date" in result.notes


@settings(max_examples=300, deadline=None)
@given(
    status=st.sampled_from(("Closed", "2 hour delay", "Early dismissal", "NTI day", "Late start")),
    slot=st.sampled_from(
        (
            "{date}",
            "{{date}}",
            "[DATE]",
            "[date]",
            "%DATE%",
            "<date>",
            "{day}",
            "[Insert date]",
            "date TBD",
            "date: TBA",
            "on TBD",
            "on N/A",
            "(date to be announced)",
            "%s",
            "___",
        )
    ),
    lead=st.sampled_from(("", " on", " -", ":")),
)
def test_a_placeholder_day_never_gives_a_status(status: str, slot: str, lead: str) -> None:
    result = parse_status(f"{status}{lead} {slot}", posted_at=MORNING, tz=TZ)
    assert result.kind == "other", (status, lead, slot)
    assert result.confidence <= 0.3


ANSWERED_NO = [
    "Closed: N", "Delayed: N", "Closed=false", "closed=0", "Delay: 0:00", "00:00 delay",
    "Delay - 0:00", "Closed: No", "Early dismissal: N",
]  # fmt: skip


@pytest.mark.parametrize("text", ANSWERED_NO)
def test_a_field_answered_no_states_no_status(text: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other"
    assert result.schedule == ()


def test_a_field_left_empty_answers_nothing() -> None:
    result = parse_status("Closed:", posted_at=MORNING, tz=TZ)
    assert result.kind == "other"
    assert result.confidence <= 0.3


ANSWERED_YES = [("Closed: Y", "closed"), ("Closed: yes", "closed"), ("Closed=true", "closed")]


@pytest.mark.parametrize(("text", "kind"), ANSWERED_YES)
def test_a_field_answered_yes_keeps_its_status(text: str, kind: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == kind
    assert result.dates == jan(21)


@settings(max_examples=300, deadline=None)
@given(
    field=st.sampled_from(("Closed", "Delayed", "Delay", "Early dismissal", "2 hour delay")),
    mark=st.sampled_from((": ", " - ", "=", " = ")),
    answer=st.sampled_from(("N", "No", "no", "false", "FALSE", "0", "00", "0:00", "None", "N/A")),
)
def test_a_field_answered_no_never_gives_a_status(field: str, mark: str, answer: str) -> None:
    text = f"{field}{mark}{answer}"
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other", text
    assert result.schedule == (), text


# A time that is not zero before a status is no answer: "Buses at 10:00 - delay".
NOT_ZERO = [
    ("Buses at 10:00 - delay", "delayed"), ("20:00 closed", "closed"),
    ("Start at 10:00 - 2 hour delay", "delayed"), ("Opening at 10:00: delayed", "delayed"),
]  # fmt: skip


@pytest.mark.parametrize(("text", "kind"), NOT_ZERO)
def test_a_time_not_zero_before_a_status_leaves_it(text: str, kind: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == kind
    assert "negated" not in result.notes


@settings(max_examples=300, deadline=None)
@given(
    hour=st.integers(1, 23),
    minutes=st.sampled_from(("00", "30")),
    mark=st.sampled_from((" ", " - ", ": ")),
    status=st.sampled_from(("delay", "closed", "2 hour delay", "early dismissal")),
)
def test_only_a_zero_time_before_a_status_denies_it(
    hour: int, minutes: str, mark: str, status: str
) -> None:
    text = f"Buses at {hour}:{minutes}{mark}{status}"
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert "negated" not in result.notes, text
    for zero in ("0:00", "00:00"):
        denied = parse_status(f"{zero}{mark}{status}", posted_at=MORNING, tz=TZ)
        assert denied.kind == "other", (zero, mark, status)
        assert denied.schedule == ()


NOT_THE_NEWS = [
    "This is a test. Closed tomorrow.", "Test message - closed tomorrow", "Closed tomorrow (test)",
    "ARCHIVE: closed tomorrow", "Closed tomorrow - this is only a test", "Snow day chance: 90%",
    "Closure odds: 70%", "Non-closed", "Post-closure update",
    "Click here for the 2 hour delay schedule", "See the delayed start schedule",
    "eLearning day plans", "NTI day plans",
]  # fmt: skip


@pytest.mark.parametrize("text", NOT_THE_NEWS)
def test_a_test_odds_a_prefix_or_a_link_states_no_status(text: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other"
    assert result.confidence <= 0.3


STILL_THE_NEWS = [
    ("Closed tomorrow for state testing", "closed", jan(22)),
    ("2 hour delay tomorrow; ACT test moved to Friday", "delayed", jan(22)),
    ("Friday Morning: Delay Schedule", "delayed", jan(23)),
    ("Pre-K closed today; all other schools open", "other", ()),
]


@pytest.mark.parametrize(("text", "kind", "dates"), STILL_THE_NEWS)
def test_a_test_or_a_schedule_of_its_own_leaves_the_status(
    text: str, kind: str, dates: tuple[date, ...]
) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == kind
    assert result.dates == dates


@settings(max_examples=200, deadline=None)
@given(
    status=st.sampled_from(
        (
            ("2 hour delay today.", "delayed", ("delay", "2 hour delay", "delayed start")),
            ("Closed today.", "closed", ("closure", "snow day")),
            ("Early dismissal at 1 pm today.", "early_dismissal", ("early dismissal",)),
            ("eLearning day today.", "remote", ("eLearning day",)),
        )
    ),
    pick=st.integers(min_value=0, max_value=2),
    noun=st.sampled_from(("schedule", "plan", "calendar")),
)
def test_a_link_to_a_stated_status_s_page_leaves_the_status_sure(
    status: tuple[str, str, tuple[str, ...]], pick: int, noun: str
) -> None:
    # "2 hour delay today. Click here for the delay schedule.": the page of the status the
    # text states, which adds no doubt to it.
    stated, kind, words = status
    text = f"{stated} Click here for the {words[pick % len(words)]} {noun}."
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == kind, text
    assert "ambiguous" not in result.notes, text
    assert result.dates == jan(21), text


@settings(max_examples=300, deadline=None)
@given(
    prefix=st.sampled_from(("Non", "non", "Post", "post", "Pre", "pre", "Anti", "anti")),
    word=st.sampled_from(("closed", "closure", "closing", "delay", "delayed", "dismissal")),
    lead=st.sampled_from(("", "Today: ", "Update - ")),
    tail=st.sampled_from(("", " update", " schedule today", " procedures tomorrow")),
)
def test_a_status_word_joined_to_a_prefix_never_gives_a_status(
    prefix: str, word: str, lead: str, tail: str
) -> None:
    text = f"{lead}{prefix}-{word}{tail}"
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other", text
    assert result.confidence <= 0.3, text


# A day held by a placeholder in a sentence of its own about something else leaves the status
# beside it as it is: "Closed today. Graduation date TBD." (In the status's own sentence it is
# the status's day, which no one can read: "Closed (date TBD)".)
@pytest.mark.parametrize(
    "text",
    [
        "Closed today. Graduation date TBD.",
        "Closed today. Reopening date TBD.",
        "Closed today. Concert date TBA",
        "Closed today. Conferences moved to a date TBD.",
    ],
)
def test_an_event_s_placeholder_day_leaves_the_status_as_it_is(text: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "closed"
    assert "unreadable_date" not in result.notes


# A day number with an ordinal ending that no month has ("the 32nd", "the 40th") is a day that
# cannot be read, as "the 0th" and "Jan 35th" are: never the posting day for sure.
IMPOSSIBLE_ORDINALS = [
    "Closed the 32nd", "Closed on the 32nd", "Closed the 40th", "Closed 32nd",
    "No school the 32nd", "2 hour delay the 32nd", "Closed the 32nd and 33rd",
    "Closed 1/22 and the 32nd",
]  # fmt: skip


@pytest.mark.parametrize("text", IMPOSSIBLE_ORDINALS)
def test_an_impossible_ordinal_day_is_unreadable(text: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other", text
    assert result.confidence <= 0.3, text


@settings(max_examples=300, deadline=None)
@given(
    status=st.sampled_from(("Closed", "No school", "2 hour delay", "Remote learning")),
    lead=st.sampled_from(("", "on ", "the ", "on the ")),
    number=st.integers(min_value=32, max_value=99),
)
def test_a_day_number_past_31_never_gives_a_confident_status(
    status: str, lead: str, number: int
) -> None:
    # Invariant: "<status> [on] the <N><suffix>" with N > 31 gives confidence < 0.7.
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th") if number % 100 // 10 != 1 else "th"
    text = f"{status} {lead}{number}{suffix}"
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.confidence < 0.7, (text, result)


def test_a_status_beside_an_impossible_run_is_a_judgment() -> None:
    # "Closed Today; Closed through April 6" posted on New Year's Eve: the run cannot be one
    # closure and is dropped; today stays, as a judgment, not at full confidence.
    posted = datetime(2026, 12, 31, 23, 30, tzinfo=ZoneInfo("UTC"))
    result = parse_status(
        "Closed Today; Closed through April 6", posted_at=posted, tz="America/New_York"
    )
    assert result.kind == "closed"
    assert "invalid_date" in result.notes
    assert result.confidence <= 0.8


def test_a_printf_token_where_no_day_stands_is_no_slot() -> None:
    # "%d" after "Reply" stands for a number to text, not a day: the status stands.
    result = parse_status("Closed today. Reply %d for details.", posted_at=MORNING, tz=TZ)
    assert result.kind == "closed"
    assert result.dates == (date(2026, 1, 21),)
    for text in ("Closed %s", "Closed on %s", "Delayed until ___"):
        assert parse_status(text, posted_at=MORNING, tz=TZ).kind == "other", text


# A status said not to be on a day is no status of that day, nor of today: "Two hour delay will
# not be Thursday", "2 hour delay won't be Thursday". A day before the denial keeps its status
# ("Closed today, will not be Thursday").
@settings(max_examples=300, deadline=None)
@given(
    status=st.sampled_from(("Two hour delay", "2 hour delay", "Closure", "Classes cancelled",
                            "Early dismissal", "Remote learning", "School closed")),
    deny=st.sampled_from(("will not be", "won't be", "will not be on", "won't be on", "is not",
                          "isn't", "will not be for")),
    day=st.sampled_from(("Thursday", "tomorrow", "Friday", "Jan. 23", "1/23")),
)  # fmt: skip
def test_a_status_denied_for_a_day_is_no_status(status: str, deny: str, day: str) -> None:
    result = parse_status(f"{status} {deny} {day}", posted_at=MORNING, tz=TZ)
    assert result.kind == "other", (status, deny, day, result)


@pytest.mark.parametrize(
    ("text", "kind", "days"),
    [
        ("Closed today, will not be Thursday", "closed", (21,)),
        ("Closed today and not Thursday", "closed", (21,)),
        # "may" before a date in figures is the verb, never the month.
        ("Closed may 1/22 and 1/23", "other", ()),
        ("Closed May 22", "closed", ()),
    ],
)
def test_a_denied_day_or_a_verb_may_names_no_day_of_the_status(
    text: str, kind: str, days: tuple[int, ...]
) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == kind, text
    if days:
        assert result.dates == tuple(date(2026, 1, day) for day in days), text
    assert date(2026, 5, 1) not in result.dates, text
