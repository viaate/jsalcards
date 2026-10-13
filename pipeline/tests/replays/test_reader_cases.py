"""The real status reader against the replay gates (active once ``snowlight.classify`` lands).

The gates restate what they need of the reader (``gates.Parsed``, ``gates.Entry``,
the 0.8 and 0.1 levels, the allowed notes). These tests hold the restatement to
the reader itself, and run the named traps through the reader and the claim
gates. Every case is a fresh, generic text: none is copied from a station list.
"""

import inspect
from datetime import UTC, date, datetime
from typing import get_args
from zoneinfo import ZoneInfo

import pytest

from replays.test_gates import NOTE_LITERALS
from snowlight.replays import cli
from snowlight.replays.build import DISPUTED_VOTE, vote_of
from snowlight.replays.gates import (
    ALLOWED_NOTES,
    MIN_CONFIDENCE,
    UNREAD_CONFIDENCE,
    Drop,
    ParseFn,
    claim_for_day,
)
from snowlight.replays.rows import reader_text

classify = pytest.importorskip("snowlight.classify")
model = pytest.importorskip("snowlight.classify.model")

CHICAGO = "America/Chicago"


def _at(local: str) -> datetime:
    return datetime.fromisoformat(local).replace(tzinfo=ZoneInfo(CHICAGO)).astimezone(UTC)


def test_the_restated_notes_and_levels_are_the_readers() -> None:
    notes = set(get_args(model.Note.__value__))
    assert notes == set(NOTE_LITERALS)
    assert notes >= ALLOWED_NOTES
    assert model.JUDGMENT == MIN_CONFIDENCE
    assert model.UNKNOWN == UNREAD_CONFIDENCE


def test_the_reader_is_called_as_the_protocol_says() -> None:
    params = inspect.signature(classify.parse_status).parameters
    assert params["posted_at"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["tz"].kind is inspect.Parameter.KEYWORD_ONLY
    parse: ParseFn = cli.check_reader(classify, model)
    assert parse is classify.parse_status


def test_a_real_reading_passes_the_gates_as_the_protocol_shapes_it() -> None:
    at = _at("2024-01-15 19:07")
    parsed = classify.parse_status("Closed Tuesday", posted_at=at, tz=CHICAGO)
    entry = claim_for_day(parsed, date(2024, 1, 16), at, CHICAGO, text="Closed Tuesday")
    assert not isinstance(entry, Drop)
    assert entry.kind == "closed"
    assert entry.dates_stated


@pytest.mark.parametrize(
    ("status", "detail", "local", "day"),
    [
        ("Closed January 6, 2024", "", "2025-01-05 18:38", "2025-01-06"),  # the year typo
        ("1/7-In-service", "", "2025-01-06 19:00", "2025-01-07"),
        ("Closed for Martin Luther King Jr. Day", "", "2024-01-14 19:00", "2024-01-15"),
        ("Closed", "", "2024-01-14 19:00", "2024-01-15"),  # Sunday evening, bare
        ("Closed tomorrow", "", "2024-01-16 00:30", "2024-01-17"),  # overnight "tomorrow"
        ("Closed today", "", "2024-01-16 00:30", "2024-01-16"),  # yesterday's list after midnight
        ("Closed Wednesday", "Optional Teacher Work Day", "2024-01-16 16:00", "2024-01-17"),
        ("Closed", "Teacher Planning Day", "2024-01-16 06:00", "2024-01-16"),
        ("Closed - Semester break", "", "2024-01-16 06:00", "2024-01-16"),
        ("Closed tomorrow", "", "2024-01-15 08:00", "2024-01-16"),  # left up from Sunday evening
        ("Closed today. Updated Monday 4:00 PM", "", "2024-01-16 00:30", "2024-01-16"),
        (
            "Open; Kestrel Academy will open on time; dismissal at 1:00 pm following our "
            "Tuesday early release schedule",
            "",
            "2024-01-16 05:00",
            "2024-01-16",
        ),
        ("Open on time. Early release at 1 pm", "", "2024-01-16 05:00", "2024-01-16"),
        ("Closed Tuesday", "Snow Packet 1", "2024-01-15 16:00", "2024-01-16"),
        ("Closed Tuesday", "eDay", "2024-01-15 16:00", "2024-01-16"),
        ("Closed - Teacher Institute", "", "2024-01-16 06:00", "2024-01-16"),
        ("Closed Tomorrow; E-Day", "", "2025-01-09 14:00", "2025-01-10"),
        ("Closed - Snow Packet Day", "", "2024-01-16 06:00", "2024-01-16"),
        ("Closed. Students work from home", "", "2024-01-16 06:00", "2024-01-16"),
        ("Closed - Exam Day", "", "2024-01-16 06:00", "2024-01-16"),
        ("TEST - Closed", "", "2024-01-16 06:00", "2024-01-16"),
    ],
)
def test_the_named_traps_end_as_drops(status: str, detail: str, local: str, day: str) -> None:
    at = _at(local)
    text = reader_text(status, detail)
    parsed = classify.parse_status(text, posted_at=at, tz=CHICAGO)
    result = claim_for_day(
        parsed, date.fromisoformat(day), at, CHICAGO, text=text, name="Wrenfield R-3", detail=detail
    )
    assert isinstance(result, Drop), (text, result)


@pytest.mark.parametrize("detail", ["AMI Day", "NTI Day", "E-Learning", "Remote Learning Day"])
def test_a_learning_comment_beside_closed_reads_as_remote(detail: str) -> None:
    at = _at("2024-01-15 16:00")
    text = reader_text("Closed Tuesday", detail)
    parsed = classify.parse_status(text, posted_at=at, tz=CHICAGO)
    result = claim_for_day(parsed, date(2024, 1, 16), at, CHICAGO, text=text, detail=detail)
    assert not isinstance(result, Drop)
    assert result.kind == "remote"


def test_a_bare_closed_reads_another_day_at_an_old_posted_time() -> None:
    """What the posted-time check relies on: the reader resolves a bare status from posted_at."""
    captured, posted = _at("2025-01-08 05:26"), _at("2025-01-06 16:39")
    now = classify.parse_status("Closed", posted_at=captured, tz=CHICAGO).on(date(2025, 1, 8))
    then = classify.parse_status("Closed", posted_at=posted, tz=CHICAGO).on(date(2025, 1, 8))
    assert now is not None
    assert then is None


@pytest.mark.parametrize(
    "status",
    [
        "Closing rescinded",
        "Delay cancelled",
        "Not closed",
        "No delay",
        "Closed. Lincoln Elementary open.",
        "Closed - CANCELED",
        "Closed - Teacher In-Service",
        "Closed - Snow Packet Day",
        "Open",
        # the retraction's own phrase names no day, or names the day by an ordinal or a list
        "Closing rescinded. Make-up day will be Friday",
        "Closing rescinded - make up day Feb 19",
        "Closing cancelled - buses will run Wednesday",
        "Disregard closing - closed Wednesday only",
        "Closure rescinded - closed 1/17",
        "Closings for Jan 15th-17th have been rescinded",
        "Closings for January 15 & 16 cancelled",
        "Delays Jan 15 and 16 are cancelled",
        "Closures 1/15 & 16 rescinded",
        "Today's closure has been rescinded; closed tomorrow",
        "Delay rescinded for today; 2 hour delay tomorrow",
    ],
)
def test_a_reading_that_takes_back_narrows_or_recauses_the_status_votes_against_a_claim(
    status: str,
) -> None:
    """Another list's or the school's own row: the reader's reading of it stops the claim."""
    at = _at("2024-01-16 05:26")
    day = date(2024, 1, 16)
    parsed = classify.parse_status(status, posted_at=at, tz=CHICAGO)
    vote = vote_of(parsed, parsed.on(day), day, text=status)
    assert vote in {DISPUTED_VOTE, "open"}, (status, parsed)


@pytest.mark.parametrize(
    "status",
    [
        "Closed. Snow Packet Days Jan 15-17",
        "Closed. Google Classroom days: Mon-Wed",
        "Closed. Snow Packet Days through Friday",
        "Closed; Students and staff work from home",
        "Closed - operating as an E-Day",
        "No School/Snow Packet Day",
        "No School-Snow Packet Day",
        "Closed. No school-snow packet day",
        "Closed. Snow Packet Days Jan 15th-17th",
        "Closed. Snow Packet Days Jan. 15th through 17th",
        "Closed. Snow Packet Days Jan 15, 16 and 17",
        "Closed. Snow Packet Days 1/15 & 16",
        "Closed. Packet days Jan 15th, 16th",
        "Closed 1/16; Snow Packet Day #2 Jan 15th-17th",
        "Closed today and Wednesday - Snow Packet Days",
        "Closed - Google Classroom Day 2 (Day 1 was Monday)",
        "Closed. No bus-eDay",
        "Closed. Students do not report-Snow Packet Day",
        "Closed - Teachers will post work on Google Classroom",
        "Closed - Flexible Learning Day",
        "Closed. Flexible Learning Day",
        "Closed - Digital Day",
        "Closed Tuesday - Digital Day",
        "Closed - Flex learning",
        "Closed - Snow Packet Day, SAT testing moved",
    ],
)
def test_a_learning_day_the_reader_reads_closed_never_lights_closed(status: str) -> None:
    at = _at("2024-01-16 06:00")
    day = date(2024, 1, 16)
    parsed = classify.parse_status(status, posted_at=at, tz=CHICAGO)
    result = claim_for_day(parsed, day, at, CHICAGO, text=status)
    assert isinstance(result, Drop) or result.kind == "remote", (status, parsed)


@pytest.mark.parametrize(
    ("status", "day"),
    [
        ("Closed Wednesday - no heat", "2024-01-17"),  # a cause alone, no non-weather word
        ("Closed Wednesday - boil water advisory", "2024-01-17"),
        ("Tuesday's closure has been rescinded; closed Wednesday", "2024-01-16"),
        ("Delay for Tuesday cancelled. 2 hour delay Wednesday", "2024-01-16"),
    ],
)
def test_a_reading_that_recauses_or_takes_back_the_day_votes_against_another_lists_claim(
    status: str, day: str
) -> None:
    at = _at("2024-01-15 19:00")
    when = date.fromisoformat(day)
    parsed = classify.parse_status(status, posted_at=at, tz=CHICAGO)
    assert vote_of(parsed, parsed.on(when), when, text=status) == DISPUTED_VOTE, (status, parsed)


def test_a_retraction_of_tomorrow_votes_by_the_captures_date() -> None:
    """Posted the Monday evening, "Tomorrow's closing cancelled" takes back the Tuesday; a
    retraction of Monday's closing alone says nothing of it."""
    at = _at("2024-01-15 20:00")
    day = date(2024, 1, 16)
    posted = date(2024, 1, 15)
    text = "Tomorrow's closing cancelled - closed Wednesday instead"
    parsed = classify.parse_status(text, posted_at=at, tz=CHICAGO)
    assert vote_of(parsed, parsed.on(day), day, text=text, posted=posted) == DISPUTED_VOTE
    other = "Monday's closing rescinded"
    parsed = classify.parse_status(other, posted_at=at, tz=CHICAGO)
    assert vote_of(parsed, parsed.on(day), day, text=other, posted=posted) is None, parsed
