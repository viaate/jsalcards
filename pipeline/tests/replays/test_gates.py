"""The replay gates, one rule at a time, on SYNTHETIC readings (see ``world.py``)."""

import ast
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import pytest

from replays.world import CHICAGO, DAY, DENVER, FakeEntry, FakeParsed, registry, station, stub_parse
from snowlight.listed.scope import EXCLUDED_PLATFORMS
from snowlight.replays.gates import (
    ALLOWED_NOTES,
    DISTRICT_SITES,
    KNOWN_OUT,
    NON_WEATHER_WORDS,
    REPLAY_PLATFORMS,
    STATUS_BOARDS,
    UNCLASSIFIED,
    Drop,
    capture_window,
    claim_for_day,
    day_ok,
    directory_year,
    dissents,
    holidays,
    in_window,
    learning_mode,
    low_match,
    names_day,
    nth_monday,
    rejected_notes,
    relative_today,
    relative_tomorrow,
    says_open,
    school_year_of,
    source_drop,
    station_median,
    unread_share,
    unreadable,
)
from snowlight.replays.rows import reader_text
from snowlight.sources.stations.registry import load_registry

NOTE_LITERALS = (
    "activities_cancelled",
    "ambiguous",
    "childcare",
    "conflict",
    "date_mismatch",
    "hedged",
    "invalid_date",
    "negated",
    "offices_closed",
    "overnight",
    "partial_program",
    "recurring",
    "revoked",
    "staff",
    "superseded",
    "transportation",
    "truncated",
    "undated",
    "unreadable_date",
    "unread_words",
    "unrecognized",
    "weekend",
)
"""The reader's 22 ``Note`` literals (``classify/model.py``), restated: no reader needed."""

TOMORROW = DAY + timedelta(days=1)
MORNING = datetime(2024, 1, 16, 11, 26, tzinfo=UTC)  # 05:26 in Chicago on the day
OTHER_DAY = date(2024, 1, 19)


def _local(text: str, zone: str = CHICAGO) -> datetime:
    from zoneinfo import ZoneInfo  # noqa: PLC0415 - local to the helper

    return datetime.fromisoformat(text).replace(tzinfo=ZoneInfo(zone)).astimezone(UTC)


def _parsed(**changes: Any) -> FakeParsed:
    base: dict[str, Any] = {
        "kind": "closed",
        "schedule": (FakeEntry("closed", (DAY,)),),
        "reason": "Winter storm",
    }
    base.update(changes)
    return FakeParsed(**base)


def test_a_clean_dated_claim_passes() -> None:
    result = claim_for_day(_parsed(), DAY, MORNING, CHICAGO)
    assert isinstance(result, FakeEntry)
    assert result.kind == "closed"


@pytest.mark.parametrize(
    ("parsed", "text", "expected"),
    [
        (_parsed(confidence=0.7), "", Drop.LOW_CONFIDENCE),
        (
            _parsed(schedule=(FakeEntry("closed", (DAY + timedelta(days=1),)),)),
            "",
            Drop.NOT_FOR_DAY,
        ),
        (_parsed(schedule=(FakeEntry("other", (DAY,)),)), "", Drop.NOT_FOR_DAY),
        (_parsed(notes=("hedged",)), "", Drop.NOTE),
        (_parsed(says_open=True), "", Drop.SAYS_OPEN),
        (_parsed(other_causes=("water main break",)), "", Drop.OTHER_CAUSE),
        (
            _parsed(schedule=(FakeEntry("closed", (DAY,), until_further_notice=True),)),
            "",
            Drop.OPEN_ENDED,
        ),
        (_parsed(), "Quillfeather R-7 1/16-In-service", Drop.NON_WEATHER_WORDS),
        (
            _parsed(
                schedule=(
                    FakeEntry("closed", (DAY,)),
                    FakeEntry("closed", (date(2023, 1, 6),)),
                )
            ),
            "",
            Drop.DATE_OUT_OF_RANGE,
        ),
    ],
)
def test_each_claim_gate_drops(parsed: FakeParsed, text: str, expected: Drop) -> None:
    assert claim_for_day(parsed, DAY, MORNING, CHICAGO, text=text) is expected


EARLY = _parsed(
    kind="early_dismissal", schedule=(FakeEntry("early_dismissal", (DAY,)),), confidence=0.9
)
"""A SYNTHETIC early-dismissal reading for the day, with no note and says_open false: what the
reader makes of a row that says the school opens on time and lets out early by its schedule."""


@pytest.mark.parametrize(
    "text",
    [
        # SYNTHETIC, in the shape of a charter school's own weekly early release
        "Open; Kestrel PCS will Open On Time on 1/16/2024; Dismissal will be at 1:00 pm "
        "following our Tuesday Early Release Schedule",
        "Open on time. Early release at 1 pm",
        "Open. Regular early dismissal at 1:00",
        "On time; dismissal at 12:30 per normal Tuesday schedule",
        "OPEN on-schedule",
        "Normal schedule",
        "Open Tuesday",
        "Early dismissal at 1:00. Kestrel will open on time",
    ],
)
def test_a_row_that_says_the_school_is_open_never_lights(text: str) -> None:
    result = claim_for_day(EARLY, DAY, MORNING, CHICAGO, text=text)
    assert result in {Drop.SAYS_OPEN, Drop.NON_WEATHER_WORDS}
    assert says_open(text) or NON_WEATHER_WORDS.search(text)


@pytest.mark.parametrize(
    ("text", "detail", "open_"),
    [
        ("Open", "", True),
        ("Open; dismissal at 1:00", "", True),
        ("Closed Tuesday", "Open on time Wednesday", True),  # a comment that opens
        ("Closed Tuesday", "Normal schedule", True),
        ("Open 2 Hrs. Late", "", False),  # a late opening is a delay
        ("Open at 10:00 AM", "", False),
        ("Open at noon", "", False),
        ("Opening at 10:00 AM", "", False),
        ("Delayed 2 hours; Offices Open on Time", "", False),  # the offices, not the school
        ("Closed Tuesday", "Office open at 10", False),
        ("Closed", "", False),
    ],
)
def test_says_open(text: str, detail: str, open_: bool) -> None:
    assert says_open(reader_text(text, detail), detail) is open_


def test_a_late_opening_that_begins_with_open_lights() -> None:
    delayed = _parsed(kind="delayed", schedule=(FakeEntry("delayed", (DAY,)),))
    for text in ("Open 2 Hrs. Late", "Open at 10:00 AM", "Delayed 2 hours; Offices Open on Time"):
        assert isinstance(claim_for_day(delayed, DAY, MORNING, CHICAGO, text=text), FakeEntry)


def test_the_gate_reads_the_entry_for_the_day_not_the_primary_kind() -> None:
    parsed = _parsed(
        kind="other",
        schedule=(FakeEntry("delayed", (DAY,)),),
    )
    result = claim_for_day(parsed, DAY, MORNING, CHICAGO)
    assert isinstance(result, FakeEntry)
    assert result.kind == "delayed"


def test_the_confidence_floor_is_the_judgment_level() -> None:
    assert isinstance(claim_for_day(_parsed(confidence=0.8), DAY, MORNING, CHICAGO), FakeEntry)
    assert claim_for_day(_parsed(confidence=0.79), DAY, MORNING, CHICAGO) is Drop.LOW_CONFIDENCE


def test_the_note_literals_are_the_readers() -> None:
    assert len(NOTE_LITERALS) == 22
    assert set(NOTE_LITERALS) >= ALLOWED_NOTES


@pytest.mark.parametrize("note", NOTE_LITERALS)
def test_every_note_literal_is_allowed_or_dropped(note: str) -> None:
    result = claim_for_day(_parsed(notes=(note,)), DAY, MORNING, CHICAGO)
    if note in {"undated", "unread_words"}:
        assert isinstance(result, FakeEntry)
    else:
        assert result is Drop.NOTE
        assert rejected_notes(_parsed(notes=(note, "undated"))) == [note]


@pytest.mark.parametrize(
    "text",
    [
        "1/7-In-service",
        "In service day",
        "Teacher Work Day",
        "teacher workday",
        "Professional Development",
        "PD Day",
        "Staff Development",
        "Records Day",
        "Parent-teacher conferences",
        "Closed - Teacher Planning Day",
        "Closed - Semester break",
        "Closed - Snow make-up day",
        "Closed. Winter Break",
        "Closed for the holiday",
        "Closed. Optional teacher workday",
        "Closed - grading day",
        "Closed - end of quarter",
        "Closed - Teacher Institute",
        "Closed - Institute Day",
        "Closed for Inauguration Day",
        "Closed - Fair Day",
        "Closed. Scheduled day off",
        "Closed - previously scheduled",
        "No school for students",
        "Early release day",
        "Early Dismissal. Minimum day",
        "Dismissal at 1:00 following our Wednesday Early Release Schedule",
        "Dismissal at 12:30 per normal Wednesday schedule",
        "Regular early dismissal at 1:00",
        "Dismissal at 1:00, our regularly scheduled early release",
    ],
)
def test_non_weather_words(text: str) -> None:
    assert claim_for_day(_parsed(), DAY, MORNING, CHICAGO, text=text) is Drop.NON_WEATHER_WORDS


def test_non_weather_words_in_the_name_or_the_comment() -> None:
    """The comment reaches the gate in the reader's text; the name is checked on its own."""
    closed = "Closed Tuesday. Teacher Planning Day"
    assert claim_for_day(_parsed(), DAY, MORNING, CHICAGO, text=closed) is Drop.NON_WEATHER_WORDS
    named = claim_for_day(_parsed(), DAY, MORNING, CHICAGO, text="Closed", name="PD Day Camp")
    assert named is Drop.NON_WEATHER_WORDS


@pytest.mark.parametrize(
    "detail",
    [
        "AMI Day",
        "NTI Day #2",
        "E-Learning",
        "eLearning Day",
        "Remote Learning Day",
        "Synchronous eLearning Day",
        "Virtual learning",
        "Flexible Instruction Day",
        "Snow Packet 1",
        "Packet day",
        "eDay",
        "E-Day #3",
        "Google Classroom",
        "Work from home",
    ],
)
def test_a_comment_that_names_a_learning_mode_lights_only_remote(detail: str) -> None:
    """A "Closed Tuesday" row whose comment says AMI Day is a learning day, not a closing."""
    text = f"Closed Tuesday. {detail}"
    closed = claim_for_day(_parsed(), DAY, MORNING, CHICAGO, text=text, detail=detail)
    assert closed is Drop.DETAIL_MODE
    remote = _parsed(kind="remote", schedule=(FakeEntry("remote", (DAY,)),))
    assert isinstance(
        claim_for_day(remote, DAY, MORNING, CHICAGO, text=text, detail=detail), FakeEntry
    )


@pytest.mark.parametrize(
    "text",
    [
        "Closed - Snow Packet Day",
        "Closed - eDay",
        "Closed - E-Day",
        "Closed. Google Classroom",
        "Closed. Work from home",
        "Closed Tuesday; Snow Packet 1",
        "Closed - Students work from home",
        "Closed Tomorrow; E-Day",
        "Closed - AMI Day 3",
        "Closed; remote learning",
        "TOMORROW: CLOSED: E-DAY POLICY IN EFFECT",
        "Closed Monday | Tuesday: Remote learning day",  # the clause names the day itself
        # a span of days that holds the day: it names other days, but may be about this one
        "Closed. Snow Packet Days Jan 15-17",
        "Closed. Snow Packet Days 1/15 - 1/17",
        "Closed. Snow Packet Days through Friday",
        "Closed. Google Classroom days: Mon-Wed",
        "Closed. Remote learning Monday through Friday",
        "Closed; remote learning starting Monday",
        "Closed; e-days this week",
        "Closed Jan. 16; eLearning Jan. 16 and 17",  # the abbreviation's dot ends no clause
        # the staff with the students, and no staff word that is not one
        "Closed; Students and staff work from home",
        "Closed - Staff and students: Snow Packet Day",
        "Closed - Students and teachers work from home",
        "Closed. Faculty and students: eDay",
        "Closed - operating as an E-Day",
        "Closed - Operating on Snow Packet Day",
        # a negation that is not of the learning word
        "No School/Snow Packet Day",
        "No school - eLearning day",
        "No School-Snow Packet Day",
        "Closed. No school-snow packet day",
        "Closed. No school snow packet day",  # "school" is no word a negation may skip
        "Closed. No school NTI day",  # one word between: the lookahead keeps "school"
        "Closed. No school eLearning day",
        "Closed. No school e-day",
        "Closed. No classes NTI day",
        "Closed. No bus-eDay",  # a word glued on with a hyphen
        "Closed. Students do not report-Snow Packet Day",
        # the teachers' words that are the students' learning
        "Closed - Teachers will post work on Google Classroom",
        # ordinals, listed days and spaced spans that hold the day
        "Closed. Snow Packet Days Jan 15th-17th",
        "Closed. Snow Packet Days Jan. 15th - 17th",
        "Closed. Snow Packet Days January 15th through 17th",
        "Closed. Snow Packet Days January 15th - 17th",
        "Closed. Snow Packet Days Jan 15, 16 and 17",
        "Closed. Snow Packet Days January 15 & 16",
        "Closed. Snow Packet Days Jan 15 and 16",
        "Closed. Snow Packet Days 1/15 & 16",
        "Closed. Snow Packet Days January 15th & 16th",
        "Closed. Packet days Jan 15th, 16th",
        "Closed 1/16; Snow Packet Day #2 Jan 15th-17th",
        # a relative day word, a numbered day, a run of days beside another day
        "Closed today and Wednesday - Snow Packet Days",
        "Closed - Google Classroom Day 2 (Day 1 was Monday)",
        "Closed Monday, Snow Packet Days the rest of the week",
        "Closed; remote learning this week (Mon 1/15)",
        # each span form that may hold the day
        "Closed Monday; remote learning Jan 15 to 17",
        "Closed Monday; remote learning until Friday",
        "Closed Monday; remote learning through 1/19",
        "Closed Monday; remote learning through next Friday",
        "Closed Monday; remote learning 1/15/24-1/17/24",
        "Closed Wednesday; e-learning Fri-Tue",  # a span over the weekend
        "Closed Monday; remote learning 2024-01-16",
        "Closed Monday; remote learning 2/30",  # no such date: it may be the day
        # the districts' own names for a learning day
        "Closed - Flexible Learning Day",
        "Closed. Flexible Learning Day",
        "Closed - Digital Day",
        "Closed Tuesday - Digital Day",
        "Closed - Digital Days Tuesday and Wednesday",
        "Closed - Flex learning",
        "Closed - Flex Learning Day 2",
        # an all-caps SAT is the test, not Saturday
        "Closed - Snow Packet Day, SAT testing moved",
        "Closed - eLearning day, SAT moved",
    ],
)
def test_a_learning_word_in_the_status_itself_lights_only_remote(text: str) -> None:
    """The status names the learning mode the reader misses: the whole text is held to it."""
    assert claim_for_day(_parsed(), DAY, MORNING, CHICAGO, text=text) is Drop.DETAIL_MODE
    assert learning_mode(text, DAY)
    remote = _parsed(kind="remote", schedule=(FakeEntry("remote", (DAY,)),))
    assert isinstance(claim_for_day(remote, DAY, MORNING, CHICAGO, text=text), FakeEntry)


@pytest.mark.parametrize(
    "text",
    [
        "Closed; no virtual learning",
        "Closed Tuesday. NO REMOTE LEARNING",
        "Closed - not an e-learning day",
        "No NTI - treat as a snow day",
        "Closed. Staff working remotely",
        "Closed. Offices operating remotely",
        "Closed. Complete the online form for meals",
        "Closed Tuesday; Asynchronous learning Wednesday and Thursday",  # other days' clause
        "Tuesday Morning: Closed | Wednesday Morning: Closed-Flexible Instruction",
        "Closed Tuesday; eLearning Jan. 17 and 18",  # "Jan." keeps its number in the clause
        "Closed Tuesday; remote learning 1/17",
        "Closed Tuesday; remote learning Wed-Fri",  # a span that cannot hold the day
        "Closed Tuesday; remote learning 1/17-1/19",
        "Closed Tuesday; Snow packet days Jan 17-19",
        "Closed Tuesday; remote learning starting Wednesday",
        "Closed Monday; remote learning through Monday",
        "Closed for students; staff work from home",  # the staff's own clause
        "Closed Through Wednesday. University students-virtual learning Wednesday",
        "Closed Tues. Remote learning Wed.",  # a full stop after an abbreviation ends a clause
        "Closed Tuesday; remote learning Fri-Mon",  # a span over the weekend that misses Tuesday
        "Closed Tuesday; remote learning through 1/15",
        "Closed Tuesday; remote learning 2024-01-17",
        "Closed Tuesday; remote learning Jan 17th & 18th",
    ],
)
def test_a_learning_word_that_is_denied_or_about_staff_or_a_form_is_no_learning_mode(
    text: str,
) -> None:
    assert not learning_mode(text, DAY)
    assert isinstance(claim_for_day(_parsed(), DAY, MORNING, CHICAGO, text=text), FakeEntry)


@pytest.mark.parametrize(
    ("clause", "learning"),
    [
        ("remote learning SAT prep", True),  # the test, not the day
        ("remote learning Saturday", False),
        ("remote learning SATURDAY", False),
        ("remote learning Sat", False),
        ("remote learning sat.", False),
    ],
)
def test_an_all_caps_sat_is_no_saturday(clause: str, learning: bool) -> None:
    """A learning clause that names Saturday is about another day; one that names the SAT is not."""
    assert learning_mode(f"Closed Tuesday; {clause}", DAY) is learning


def test_today_and_tomorrow_beside_a_learning_word_are_read_against_the_capture() -> None:
    """ "Closed Wednesday; remote learning tomorrow", for the Tuesday: "tomorrow" may be the
    Tuesday in a capture on the Monday or the Tuesday (a list left up), and in none later."""
    text = "Closed Wednesday; remote learning tomorrow"
    assert learning_mode(text, DAY, DAY - timedelta(days=1))
    assert learning_mode(text, DAY, DAY)
    assert learning_mode(text, DAY)  # the capture's date not known
    assert not learning_mode(text, DAY, DAY + timedelta(days=1))
    today = "Closed Wednesday; remote learning today"
    assert learning_mode(today, DAY, DAY + timedelta(days=1))  # left up from the Tuesday
    assert not learning_mode(today, DAY, DAY + timedelta(days=2))
    assert learning_mode("Closed Wednesday; remote learning tonight", DAY, DAY)
    assert not learning_mode("Closed Monday; remote learning yesterday", DAY, DAY)


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("Closed - Exam Day", ""),
        ("Closed - Mid-term exams", ""),
        ("Closed - midterms", ""),
        ("Closed for final exams", ""),
        ("Closed - semester exams", ""),
        ("Closed - Staff Training", ""),
        ("Closed - Day off", ""),
        ("Closed - Non-student day", ""),
        ("TEST - Closed", ""),
        ("Closed Today; Testing status - Disregard", ""),
        ("Closed - this is a test listing", ""),
        ("Closed - please disregard", ""),
        ("Closed", "Test school 1"),
        ("Closed Today; Friday is Student Holiday", ""),
    ],
)
def test_exams_days_off_and_test_rows_are_not_weather(text: str, name: str) -> None:
    result = claim_for_day(_parsed(), DAY, MORNING, CHICAGO, text=text, name=name)
    assert result is Drop.NON_WEATHER_WORDS


@pytest.mark.parametrize(
    "text",
    [
        "Closed. Exams postponed",
        "Closed; exams will be rescheduled",
        "Closed today",
        "Closed. Final exams postponed",
        "Closed; semester exams will be rescheduled",
        "Closed. Mid-terms postponed",
        "Closed. Midterm exams postponed",
        "Closed - disregard previous message, closed today",
    ],
)
def test_exams_put_off_for_the_weather_are_weather(text: str) -> None:
    assert isinstance(claim_for_day(_parsed(), DAY, MORNING, CHICAGO, text=text), FakeEntry)


NO_ENTRY = FakeParsed(kind="other", schedule=(), confidence=0.9)
SUNDAY = date(2024, 1, 14)


NEXT_DAY_ONLY = (FakeEntry("closed", (date(2024, 1, 17),)),)
"""A schedule that holds only the day after the day read."""


@pytest.mark.parametrize(
    ("parsed", "text", "name"),
    [
        (replace(NO_ENTRY, notes=("revoked",)), "Closing rescinded", ""),
        (replace(NO_ENTRY, notes=("negated",)), "No delay", ""),
        (replace(NO_ENTRY, notes=("superseded",)), "Closed; now 2 hour delay", ""),
        (replace(NO_ENTRY, notes=("partial_program",)), "Closed. Lincoln Elementary open.", ""),
        (replace(NO_ENTRY, confidence=0.3, notes=("ambiguous",)), "Closed - CANCELED", ""),
        (_parsed(other_causes=("Heating",)), "Closed - no heat", ""),  # a cause alone
        (_parsed(), "Closed. Teacher In-Service", ""),
        (_parsed(), "Closed", "Kestrel Teacher Institute"),
        (_parsed(), "Closed. NTI Day", ""),
        (_parsed(), "Closed - Snow Packet Day", ""),
        # the reading takes back the day it names and schedules another
        (
            _parsed(schedule=NEXT_DAY_ONLY, notes=("revoked",)),
            "Tuesday's closure has been rescinded; closed Wednesday",
            "",
        ),
        (
            _parsed(schedule=NEXT_DAY_ONLY, notes=("revoked",)),
            "Delay for 1/16 cancelled. 2 hour delay 1/17",
            "",
        ),
        # no status stated: it names the day, or no day but in its stamp
        (replace(NO_ENTRY, notes=("revoked",)), "Closed Monday. Tuesday closing cancelled.", ""),
        (replace(NO_ENTRY, notes=("revoked",)), "Closing rescinded. Updated Monday 5:00 PM", ""),
        (replace(NO_ENTRY, notes=("revoked",)), "Closings rescinded for Jan 15-17", ""),
        # the retraction's own phrase names no day, though another phrase does
        (
            replace(NO_ENTRY, notes=("revoked",)),
            "Closing rescinded. Make-up day will be Friday",
            "",
        ),
        (replace(NO_ENTRY, notes=("revoked",)), "Closing rescinded - make up day Feb 19", ""),
        (replace(NO_ENTRY, notes=("revoked",)), "Closing cancelled - buses will run Wednesday", ""),
        (
            replace(NO_ENTRY, confidence=0.3, notes=("ambiguous", "revoked")),
            "Disregard closing - closed Wednesday only",
            "",
        ),
        (
            _parsed(schedule=NEXT_DAY_ONLY, notes=("revoked",)),
            "Closure rescinded; school in session. Wednesday 2 hr delay",
            "",
        ),
        (
            _parsed(schedule=NEXT_DAY_ONLY, notes=("revoked",)),
            "Closure rescinded - closed 1/17",
            "",
        ),
        (
            _parsed(schedule=(FakeEntry("early_dismissal", (OTHER_DAY,)),), notes=("revoked",)),
            "Delay cancelled. Early dismissal Friday",
            "",
        ),
        # the retraction names the day by an ordinal, a list or a relative word
        (
            replace(NO_ENTRY, notes=("revoked",)),
            "Closings for Jan 15th-17th have been rescinded",
            "",
        ),
        (replace(NO_ENTRY, notes=("revoked",)), "Closings for January 15 & 16 cancelled", ""),
        (replace(NO_ENTRY, notes=("revoked",)), "Closure for Jan 15th - 17th rescinded", ""),
        (replace(NO_ENTRY, notes=("revoked",)), "Delays Jan 15 and 16 are cancelled", ""),
        (replace(NO_ENTRY, notes=("revoked",)), "Closures 1/15 & 16 rescinded", ""),
        (
            _parsed(schedule=NEXT_DAY_ONLY, notes=("revoked",)),
            "Today's closure has been rescinded; closed tomorrow",
            "",
        ),
        (
            _parsed(schedule=NEXT_DAY_ONLY, notes=("revoked",)),
            "Delay rescinded for today; 2 hour delay tomorrow",
            "",
        ),
        # an entry for the day carries the note, whatever the words name
        (_parsed(notes=("revoked",)), "Monday's closing rescinded; closed today", ""),
        (_parsed(notes=("superseded",)), "Monday: 2 hour delay", ""),
        (_parsed(notes=("ambiguous",)), "Closed Monday", ""),
    ],
)
def test_a_reading_that_takes_back_narrows_or_recauses_the_status_dissents(
    parsed: FakeParsed, text: str, name: str
) -> None:
    assert dissents(parsed, DAY, text=text, name=name)


def test_a_cause_alone_dissents() -> None:
    """A cause the reader names that no non-weather word repeats ("no heat", "boil water")."""
    text = "Closed - boil water advisory"
    assert not NON_WEATHER_WORDS.search(text)
    assert dissents(_parsed(other_causes=("Water service",)), DAY, text=text)
    assert not dissents(_parsed(), DAY, text=text)


@pytest.mark.parametrize(
    ("parsed", "text"),
    [
        (_parsed(), "Closed"),  # counted
        (_parsed(confidence=0.5, notes=("hedged",)), "May close"),  # low confidence, hedged
        (_parsed(notes=("activities_cancelled",)), "Closed. All activities canceled"),
        (_parsed(other_causes=("holiday",), schedule=(FakeEntry("closed", (OTHER_DAY,)),)), "x"),
        (_parsed(kind="remote", schedule=(FakeEntry("remote", (DAY,)),)), "AMI Day"),
        (NO_ENTRY, "Kestrel Teacher In-Service"),  # no status for the day
        (  # a status taken back for another day: it says nothing of this one
            _parsed(schedule=(FakeEntry("closed", (OTHER_DAY,)),), notes=("superseded",)),
            "Closed on Friday 1/19",
        ),
        (  # no status stated, and the words name another day only (a long note left up)
            replace(NO_ENTRY, confidence=0.3, notes=("ambiguous", "activities_cancelled")),
            "Closed on Monday 1/15. Offices closed tomorrow, January 15. Activities canceled",
        ),
        (  # a stamp names the day, the words do not
            _parsed(schedule=NEXT_DAY_ONLY, notes=("revoked",)),
            "Wednesday closing rescinded. Updated Tuesday 5:00 AM",
        ),
        # the retraction's own phrase names other days only
        (replace(NO_ENTRY, notes=("revoked",)), "Monday's closing rescinded"),
        (replace(NO_ENTRY, notes=("negated",)), "No delay Monday"),
        (replace(NO_ENTRY, notes=("revoked",)), "Closings for Jan 17th & 18th cancelled"),
        (replace(NO_ENTRY, notes=("superseded",)), "Closed on Friday 1/19"),  # no retraction word
    ],
)
def test_a_reading_that_names_the_status_or_nothing_for_the_day_does_not_dissent(
    parsed: FakeParsed, text: str
) -> None:
    """Read in a capture on the Sunday before, so "tomorrow" is Monday (or Sunday)."""
    assert not dissents(parsed, DAY, text=text, posted=SUNDAY)


def test_a_retraction_of_tomorrow_is_read_against_the_capture() -> None:
    """ "Tomorrow's closing cancelled - closed Wednesday instead", read for the Tuesday: in a
    capture on the Monday evening it takes the Tuesday back; on the Wednesday it does not."""
    parsed = _parsed(schedule=NEXT_DAY_ONLY, notes=("revoked",))
    text = "Tomorrow's closing cancelled - closed Wednesday instead"
    assert dissents(parsed, DAY, text=text, posted=DAY - timedelta(days=1))
    assert dissents(parsed, DAY, text=text)
    assert not dissents(parsed, DAY, text=text, posted=OTHER_DAY - timedelta(days=2))


def test_tomorrow_in_a_note_is_read_against_the_capture() -> None:
    """The same long note captured on the Monday, or on an unknown day, may be about Tuesday."""
    parsed = replace(NO_ENTRY, confidence=0.3, notes=("ambiguous",))
    text = "Closed on Monday 1/15. Offices closed tomorrow. Activities canceled"
    assert not dissents(parsed, DAY, text=text, posted=SUNDAY)
    assert dissents(parsed, DAY, text=text, posted=DAY - timedelta(days=1))
    assert dissents(parsed, DAY, text=text)


def test_the_year_typo_is_out_of_range() -> None:
    """A 2025 list that says "January 6, 2024": a stated date a year before the capture."""
    capture = _local("2025-01-05 18:38")
    parsed = FakeParsed(
        kind="closed",
        schedule=(FakeEntry("closed", (date(2024, 1, 6),)),),
        reason="Winter storm",
    )
    assert claim_for_day(parsed, date(2025, 1, 6), capture, CHICAGO) is Drop.NOT_FOR_DAY
    both = FakeParsed(
        kind="closed",
        schedule=(
            FakeEntry("closed", (date(2025, 1, 6),)),
            FakeEntry("closed", (date(2024, 1, 6),)),
        ),
    )
    assert claim_for_day(both, date(2025, 1, 6), capture, CHICAGO) is Drop.DATE_OUT_OF_RANGE


def test_the_date_range_runs_two_days_back_and_six_ahead() -> None:
    capture = _local("2024-01-16 05:00")
    for offset, inside in ((-2, True), (-3, False), (6, True), (7, False)):
        when = date(2024, 1, 16) + timedelta(days=offset)
        parsed = FakeParsed(
            kind="closed",
            schedule=(FakeEntry("closed", (DAY,)), FakeEntry("closed", (when,))),
        )
        result = claim_for_day(parsed, DAY, capture, CHICAGO)
        assert isinstance(result, FakeEntry) is inside, offset


@pytest.mark.parametrize("zone", [CHICAGO, DENVER])
@pytest.mark.parametrize(
    ("local", "dated", "inside"),
    [
        ("2024-01-16 03:59:59", False, False),
        ("2024-01-16 04:00:00", False, True),
        ("2024-01-16 11:59:59", False, True),
        ("2024-01-16 12:00:00", False, False),
        ("2024-01-15 19:07:00", False, False),
        ("2024-01-14 11:59:59", True, False),
        ("2024-01-14 12:00:00", True, True),
        ("2024-01-16 11:59:59", True, True),
        ("2024-01-16 12:00:00", True, False),
    ],
)
def test_window_boundaries_in_two_zones(local: str, dated: bool, inside: bool, zone: str) -> None:
    capture = _local(local, zone)
    assert in_window(capture, DAY, zone, dated=dated) is inside
    parsed = _parsed(schedule=(FakeEntry("closed", (DAY,), dates_stated=dated),), notes=())
    result = claim_for_day(parsed, DAY, capture, zone)
    assert (result is not Drop.OUTSIDE_WINDOW) is inside


def test_the_window_follows_the_entry_not_the_undated_note() -> None:
    """The reader's ``undated`` note means a status naming no day was left out, not this entry."""
    evening = _local("2024-01-15 19:07")
    dated = _parsed(schedule=(FakeEntry("closed", (DAY,), dates_stated=True),), notes=("undated",))
    assert isinstance(claim_for_day(dated, DAY, evening, CHICAGO), FakeEntry)
    bare = _parsed(schedule=(FakeEntry("closed", (DAY,), dates_stated=False),), notes=())
    assert claim_for_day(bare, DAY, evening, CHICAGO) is Drop.OUTSIDE_WINDOW


@pytest.mark.parametrize(
    ("text", "local", "undated_window"),
    [
        ("Closed today", "2024-01-16 00:30", True),
        ("Closed Today", "2024-01-16 03:59", True),
        ("Closed tonight and this morning", "2024-01-16 01:00", True),
        ("Closed today, Tuesday", "2024-01-16 00:30", False),
        ("Closed today 1/16", "2024-01-16 00:30", False),
        ("Closed today, Jan. 16", "2024-01-16 00:30", False),
        ("Closed today and tomorrow", "2024-01-15 19:00", False),
        ("Closed", "2024-01-16 00:30", False),
        ("Closed today. Updated Monday 4:00 PM", "2024-01-16 00:30", True),  # another day's word
        ("Closed today. Updated 1/15 4:00 PM", "2024-01-16 00:30", True),
        ("Closed today (Tues.)", "2024-01-16 00:30", False),
    ],
)
def test_today_after_midnight_is_held_to_the_undated_window(
    text: str, local: str, undated_window: bool
) -> None:
    """A list left up from the day before still says "today" after midnight."""
    capture = _local(local)
    assert relative_today(text, capture, DAY, CHICAGO) is undated_window
    parsed = _parsed(schedule=(FakeEntry("closed", (DAY,), dates_stated=True),))
    result = claim_for_day(parsed, DAY, capture, CHICAGO, text=text)
    assert (result is Drop.OUTSIDE_WINDOW) is undated_window
    morning = claim_for_day(parsed, DAY, _local("2024-01-16 05:00"), CHICAGO, text=text)
    assert isinstance(morning, FakeEntry)


@pytest.mark.parametrize(
    ("text", "local", "posted", "undated_window"),
    [
        ("Closed tomorrow", "2024-01-15 08:00", None, True),  # left up from Sunday evening
        ("Closed tomorrow", "2024-01-15 03:00", None, True),
        ("Closed tomorrow", "2024-01-15 11:59", None, True),
        ("Closed tomorrow", "2024-01-15 08:00", "2024-01-15", False),  # posted that morning
        ("Closed tomorrow", "2024-01-15 08:00", "2024-01-14", True),
        ("Closed tomorrow", "2024-01-15 12:00", None, False),  # from noon, the day's own list
        ("Closed tomorrow, Tuesday", "2024-01-15 08:00", None, False),
        ("Closed tomorrow. Updated Sunday", "2024-01-15 08:00", None, True),
        ("Closed Tuesday", "2024-01-15 08:00", None, False),
    ],
)
def test_tomorrow_the_morning_before_is_held_to_the_undated_window(
    text: str, local: str, posted: str | None, undated_window: bool
) -> None:
    """A "Closed tomorrow" from the evening before still reads as the next day in the morning."""
    capture = _local(local)
    on = None if posted is None else date.fromisoformat(posted)
    assert relative_tomorrow(text, capture, DAY, CHICAGO, on) is undated_window
    parsed = _parsed(schedule=(FakeEntry("closed", (DAY,), dates_stated=True),))
    result = claim_for_day(parsed, DAY, capture, CHICAGO, text=text, posted_on=on)
    assert (result is Drop.OUTSIDE_WINDOW) is undated_window


@pytest.mark.parametrize(
    ("text", "named"),
    [
        ("Closed Tuesday", True),
        ("Closed Tues.", True),
        ("Closed TUE", True),
        ("Closed Jan. 16", True),
        ("Closed January 16th", True),
        ("Closed 1/16", True),
        ("Closed 01/16/2024", True),
        ("Closed 2024-01-16", True),
        ("Closed Monday", False),
        ("Closed 1/15", False),
        ("Closed 11/16", False),
        ("Closed 1/160", False),
        ("Closed Jan. 1", False),
        ("Closed today", False),
        ("Closed today. Updated Tuesday 5:00 AM", False),  # the stamp's day
        ("Closed today; last updated 1/16 04:50", False),
        ("Closed today; posted Tuesday. Tuesday schedule", True),
    ],
)
def test_names_day(text: str, named: bool) -> None:
    assert names_day(text, DAY) is named


def test_the_same_instant_is_inside_one_zone_and_outside_another() -> None:
    capture = _local("2024-01-16 04:30", CHICAGO)  # 03:30 in Denver
    assert in_window(capture, DAY, CHICAGO, dated=False)
    assert not in_window(capture, DAY, DENVER, dated=False)
    start, end = capture_window(DAY, DENVER, dated=False)
    assert (start.hour, end.hour) == (11, 19)


def test_an_evening_bare_closed_lights_neither_day() -> None:
    """A bare "Closed" at 18:38 is read as the next day (as the reader does) and counts for none."""
    capture = _local("2024-01-15 18:38")
    parsed = stub_parse("closed", posted_at=capture, tz=CHICAGO)
    assert claim_for_day(parsed, DAY, capture, CHICAGO) is Drop.OUTSIDE_WINDOW
    assert claim_for_day(parsed, DAY - timedelta(days=1), capture, CHICAGO) is Drop.NOT_FOR_DAY


def test_a_dated_evening_row_counts() -> None:
    capture = _local("2024-01-14 18:38")
    parsed = stub_parse("closed;on=2024-01-16", posted_at=capture, tz=CHICAGO)
    assert isinstance(claim_for_day(parsed, DAY, capture, CHICAGO), FakeEntry)


def test_the_window_can_be_another_days() -> None:
    """The D+7 control asks for a later day over the same captures, with no date-range gate."""
    later = DAY + timedelta(days=7)
    parsed = _parsed(schedule=(FakeEntry("closed", (later,)),))
    result = claim_for_day(parsed, later, MORNING, CHICAGO, window_day=DAY)
    assert result is Drop.DATE_OUT_OF_RANGE
    unshielded = claim_for_day(parsed, later, MORNING, CHICAGO, window_day=DAY, check_range=False)
    assert isinstance(unshielded, FakeEntry)


# --- day gates ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2024, 1, 13), Drop.WEEKEND),
        (date(2024, 1, 14), Drop.WEEKEND),
        (date(2024, 1, 15), Drop.HOLIDAY),
        (date(2025, 1, 20), Drop.HOLIDAY),
        (date(2025, 2, 17), Drop.HOLIDAY),
        (date(2024, 12, 24), Drop.HOLIDAY),
        (date(2024, 12, 31), Drop.HOLIDAY),
        (date(2025, 1, 1), Drop.HOLIDAY),
        (date(2023, 1, 2), Drop.HOLIDAY),
        (date(2024, 1, 16), None),
        (date(2025, 1, 6), None),
        (date(2026, 1, 26), None),
        (date(2023, 1, 10), Drop.DAY_SCHOOL_YEAR),
        (date(2027, 1, 12), Drop.DAY_SCHOOL_YEAR),
    ],
)
def test_day_ok(day: date, expected: Drop | None) -> None:
    assert day_ok(day, 2024) is expected


def test_holidays_are_computed_per_year() -> None:
    assert nth_monday(2024, 1, 3) == date(2024, 1, 15)
    assert nth_monday(2025, 2, 3) == date(2025, 2, 17)
    assert date(2026, 1, 19) in holidays(2026)
    assert date(2024, 1, 2) not in holidays(2024)


def test_school_years() -> None:
    assert school_year_of(date(2024, 1, 16)) == 2023
    assert school_year_of(date(2024, 8, 20)) == 2024
    assert directory_year(["2024-2025", "2023-2024", ""]) == 2024
    with pytest.raises(ValueError, match="no school year"):
        directory_year([])


# --- source gates -------------------------------------------------------------------------------


def test_source_gates() -> None:
    reg = registry(
        station("gray-syn"),
        station("apptegy-syn"),
        station("gohsep-syn"),
        station("ecc-syn"),
        station("hearst-syn", leaids=["9900001"]),
    )
    assert source_drop(reg.stations["gray-syn"]) is None
    for name in ("apptegy-syn", "gohsep-syn", "ecc-syn"):
        assert source_drop(reg.stations[name]) is Drop.PLATFORM
    assert source_drop(reg.stations["hearst-syn"]) is Drop.DISTRICT_SOURCE
    assert source_drop(None) is Drop.UNKNOWN_SOURCE


def test_every_registry_platform_is_classified() -> None:
    """Each platform of the committed registry is on the allowlist or out by name."""
    platforms = set(load_registry().platforms)
    assert platforms >= REPLAY_PLATFORMS
    assert len(REPLAY_PLATFORMS) == 26
    assert platforms <= REPLAY_PLATFORMS | KNOWN_OUT
    assert not REPLAY_PLATFORMS & KNOWN_OUT
    assert set(EXCLUDED_PLATFORMS) <= DISTRICT_SITES
    assert len(STATUS_BOARDS) == 6
    assert len(UNCLASSIFIED) == 8


# --- read gates ---------------------------------------------------------------------------------


def test_the_unreadable_share() -> None:
    assert unread_share([]) == 0.0
    assert not unreadable([0.1, 0.9, 0.9, 0.9])  # exactly a quarter
    assert unreadable([0.1, 0.0, 0.9, 0.9])
    assert not unreadable([0.11, 0.9])


def test_the_low_match_gate() -> None:
    assert station_median([0.5, 0.6]) is None
    assert station_median([0.2, 0.6, 0.4]) == 0.4
    assert low_match(0.19, 0.4)
    assert not low_match(0.2, 0.4)
    assert not low_match(0.0, None)


EXPECTED_NAMES: Final = frozenset({"expected", "drop", "reason"})
"""Parametrize names that hold the value a test asserts."""


def _asserted_drops(tree: ast.AST) -> set[str]:
    """Every ``Drop.<NAME>`` in an assert, or in an expected value of a parametrized test."""
    found: set[str] = set()

    def drops(node: ast.AST) -> set[str]:
        return {
            item.attr
            for item in ast.walk(node)
            if isinstance(item, ast.Attribute)
            and isinstance(item.value, ast.Name)
            and item.value.id == "Drop"
        }

    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            found |= drops(node)
        if not (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "parametrize"):
            continue
        names_node, values = node.args[0], node.args[1]
        if isinstance(names_node, ast.Constant) and isinstance(names_node.value, str):
            names = [name.strip() for name in names_node.value.split(",")]
        elif isinstance(names_node, ast.Tuple):
            names = [str(item.value) for item in names_node.elts if isinstance(item, ast.Constant)]
        else:
            continue
        slots = [i for i, name in enumerate(names) if name in EXPECTED_NAMES]
        for case in values.elts if isinstance(values, ast.List) else ():
            items = case.elts if isinstance(case, ast.Tuple) else [case]
            for i in slots:
                if i < len(items):
                    found |= drops(items[i])
    return found


def test_every_drop_reason_is_named_once_and_tested() -> None:
    """Each reason is asserted somewhere (in an assert or a parametrized expected value)."""
    values = [drop.value for drop in Drop]
    assert len(values) == len(set(values))
    asserted: set[str] = set()
    for path in sorted(Path(__file__).parent.glob("test_*.py")):
        asserted |= _asserted_drops(ast.parse(path.read_text(encoding="utf-8")))
    assert sorted(drop.name for drop in Drop if drop.name not in asserted) == []


def test_the_drop_check_does_not_take_a_prefix_or_an_input_for_a_test() -> None:
    tree = ast.parse(
        "import pytest\n"
        "@pytest.mark.parametrize(('parsed', 'expected'), [(Drop.CONFLICT, Drop.SUPERSEDED)])\n"
        "def test_x(parsed, expected):\n"
        "    assert f(parsed) is Drop.CONFLICT_IN_LIST\n"
    )
    assert _asserted_drops(tree) == {"SUPERSEDED", "CONFLICT_IN_LIST"}
