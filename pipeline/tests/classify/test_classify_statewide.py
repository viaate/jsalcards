"""A statewide list's sentences, non-traditional learning, and stamps that say when a listing
was written.

Every text here is a phrasing pattern written for these tests, not a claim
about a real school: the counties and schools are made up. Unless a row says
otherwise it is posted at 1:58 p.m. on Wednesday 28 January 2026 in New York,
so "tomorrow" is Thursday the 29th.

* A statewide list writes one sentence per county or school: "As of Jan 28,
  1:58pm: All schools in Alder County will be non-traditional learning on Thu.
  Jan. 29, 2026 due to continuing effects of the winter storm, Code NTID." It is
  remote learning on the 29th at 0.95. "Will be closed on", "will be on a
  2-hour delay on" and "will be dismissing 2 hours early on" read the same way,
  and a sentence about one school ("Maple Ridge High School Complex in Alder
  County will be closed on ...") is about that school, not part of a program.
* The "As of Jan 28, 1:58pm:" heading says when the entry was written. Its day
  is never a day the status applies to.
* "Non-traditional learning" (with or without "day"), "nontraditional
  learning", "NTID", "Code NTID" and "flexible instruction" without "day" are
  remote learning, as "NTI" and "flexible instruction day" are. "Closed.
  Flexible instruction" is remote learning, as "Closed; NTI day" is.
* A stamp with a date and a time ("As of Jan 28, 5:30am:", "Last Updated:
  01/27/2026 08:13pm", "posted Jan. 27 at 9:00 PM") says when the listing was
  written, which is when its "today", "tomorrow" and weekday names were meant:
  "Closed tomorrow - Last Updated: 01/27/2026 08:13pm" first seen on the 28th is
  the 28th. A stamp more than an hour after the posting time, one for a day that
  does not exist, and one whose time could be morning or evening ("5:30") are
  not read.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from snowlight.classify import parse_status
from snowlight.classify.text import normalize, written_at

TZ = "America/New_York"
ZONE = ZoneInfo(TZ)
WED = datetime(2026, 1, 28, 13, 58, tzinfo=ZONE)  # the list's afternoon
WED_MORNING = datetime(2026, 1, 28, 6, 0, tzinfo=ZONE)
WED_EVENING = datetime(2026, 1, 28, 20, 0, tzinfo=ZONE)
THU_MORNING = datetime(2026, 1, 29, 6, 0, tzinfo=ZONE)
DEC_EVENING = datetime(2025, 12, 10, 21, 0, tzinfo=ZONE)


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


def row(  # noqa: PLR0913 - one table row
    text: str,
    kind: str = "remote",
    dates: tuple[date, ...] = jan(29),
    *,
    posted: datetime = WED,
    confidence: float = 0.95,
    notes: tuple[str, ...] = (),
    delay: int | None = None,
) -> object:
    case = Row(text, posted, kind, dates, confidence, notes, delay)
    return pytest.param(case, id=f"{text} @ {posted:%a %d %H:%M}")


def check(case: Row) -> None:
    result = parse_status(case.text, posted_at=case.posted, tz=TZ)
    assert result.kind == case.kind
    assert result.dates == case.dates
    assert result.confidence == case.confidence
    assert result.notes == case.notes
    assert result.delay_minutes == case.delay


# The statewide list's sentence for a county's non-traditional learning day.
NON_TRADITIONAL_SENTENCES = [
    row(
        "As of Jan 28, 1:58pm: All schools in Alder County will be non-traditional learning on"
        " Thu. Jan. 29, 2026 due to continuing effects of the winter storm, Code NTID."
    ),
    row(
        "As of Jan 28, 11:08am: All schools in Alder County will be non-traditional learning on"
        " Thu. Jan. 29, 2026 due to Weather.",
        posted=datetime(2026, 1, 28, 11, 8, tzinfo=ZONE),
    ),
    row(
        "As of Jan 28, 12:34pm: All schools in Quarry County will be non-traditional learning on"
        " Thu. Jan. 29, 2026."
    ),
    row(
        "As of Jan 28, 1:48pm: All schools in Quarry County will be non-traditional learning on"
        " Thu. Jan. 29, 2026 due to continued inclement weather."
    ),
    row(
        "As of Jan 28, 2:59pm: All schools in Quarry County will be non-traditional learning on"
        " Thu. Jan. 29, 2026 due to poor secondary road conditions and low temperatures.",
        posted=WED_EVENING,
    ),
    row(
        "As of Jan 28, 3:15pm: All schools in Fernhill County will be non-traditional learning on"
        " Thu. Jan. 29, 2026, Code C.",
        posted=WED_EVENING,
    ),
    row(
        "As of Jan 28, 4:07pm: All schools in Fernhill County will be non-traditional learning on"
        " Thu. Jan. 29, 2026, Code orange.",
        posted=WED_EVENING,
    ),
    row(
        "As of Jan 28, 5:00pm: All schools in Fernhill County will be non-traditional learning on"
        " Thu. Jan. 29, 2026 due to cold temperatures and wind chill.",
        posted=WED_EVENING,
    ),
    row(
        "As of Jan 28, 4:03pm: All schools in Birchmont County will be non-traditional learning"
        " on Thu. Jan. 29, 2026 due to winter weather conditions.",
        posted=WED_EVENING,
    ),
    row(
        "As of Jan 28, 3:00pm: All schools in Birchmont County will be non-traditional learning"
        " on Thu. Jan. 29, 2026 due to Inclement Weather Conditions.",
        posted=WED_EVENING,
    ),
    # Seen the next morning: the day is the one the sentence names.
    row(
        "As of Jan 28, 1:58pm: All schools in Alder County will be non-traditional learning on"
        " Thu. Jan. 29, 2026.",
        posted=THU_MORNING,
    ),
    # Without the heading, and for two days.
    row("All schools in Quarry County will be non-traditional learning on Thu. Jan. 29, 2026."),
    row(
        "All schools in Quarry County will be non-traditional learning on Thu. Jan. 29, 2026 and"
        " Fri. Jan. 30, 2026.",
        dates=jan(29, 30),
    ),
    row(
        "As of Jan 28, 9:08am: All schools in Quarry County will be non-traditional learning day"
        " on Wed. Jan. 28, 2026.",
        dates=jan(28),
    ),
]

# The same list's other sentences: the heading's day is never the status's day.
OTHER_SENTENCES = [
    row(
        "As of Jan 28, 12:23pm: All schools in Quarry County will be closed on Thu. Jan. 29, 2026"
        " due to snow.",
        "closed",
    ),
    row(
        "As of Jan 28, 1:34pm: All schools in Quarry County will be closed on Thu. Jan. 29, 2026,"
        " Code A.",
        "closed",
    ),
    row(
        "As of Jan 28, 2:55pm: All schools in Quarry County will be closed on Thu. Jan. 29, 2026"
        " due to Road Conditions.",
        "closed",
        posted=WED_EVENING,
    ),
    row(
        "As of Dec 10, 6:00pm: All schools in Fernhill County will be on a 2-hour delay on Thu."
        " Dec. 11, 2025 due to forecasted inclement weather conditions.",
        "delayed",
        (date(2025, 12, 11),),
        posted=DEC_EVENING,
        delay=120,
    ),
    row(
        "As of Dec 10, 7:34pm: All schools in Fernhill County will be on a 3-hour delay on Thu."
        " Dec. 11, 2025.",
        "delayed",
        (date(2025, 12, 11),),
        posted=DEC_EVENING,
        delay=180,
    ),
    row(
        "As of Dec 10, 9:37pm: All schools in Fernhill County will be on a 2-hour delay on Thu."
        " Dec. 11, 2025, Code B.",
        "delayed",
        (date(2025, 12, 11),),
        posted=DEC_EVENING + timedelta(hours=1),
        delay=120,
    ),
    row(
        "As of Jan 28, 9:08am: All schools in Quarry County will be dismissing 2 hours early on"
        " Wed. Jan. 28, 2026 due to weather.",
        "early_dismissal",
        jan(28),
    ),
    row(
        "As of Jan 28, 9:08am: All schools in Quarry County will be on a 2-hour early dismissal"
        " on Wed. Jan. 28, 2026.",
        "early_dismissal",
        jan(28),
    ),
    # One school's entry is about that school.
    row(
        "As of Dec 10, 8:10pm: Maple Ridge High School Complex in Alder County will be closed on"
        " Thu. Dec. 11, 2025 due to Water break.",
        "closed",
        (date(2025, 12, 11),),
        posted=DEC_EVENING,
    ),
    row(
        "Maple Ridge High School in Alder County will be closed on Thu. Jan. 29, 2026.",
        "closed",
    ),
    row("Maple Ridge Elementary in Alder County will be non-traditional learning on Thu. Jan. 29."),
    row(
        "Maple Ridge Elementary in Alder County will be on a 2-hour delay on Thu. Jan. 29, 2026.",
        "delayed",
        delay=120,
    ),
    # Part of a county's schools is part of the program.
    row(
        "As of Jan 28, 9:08am: Some schools in Quarry County will be closed on Thu. Jan. 29, 2026.",
        "other",
        (),
        confidence=0.9,
        notes=("partial_program",),
    ),
    row(
        "As of Jan 28, 9:08am: All elementary schools in Quarry County will be closed on Thu. Jan."
        " 29, 2026.",
        "other",
        (),
        confidence=0.9,
        notes=("partial_program",),
    ),
    row(
        "Maple Ridge High School in the county will be closed tomorrow",
        "other",
        (),
        confidence=0.9,
        notes=("partial_program",),
    ),
    row(
        "High school in Quarry County will be closed on Thu. Jan. 29, 2026.",
        "other",
        (),
        confidence=0.9,
        notes=("partial_program",),
    ),
]

# Non-traditional learning and flexible instruction said on their own.
REMOTE_WORDING = [
    row("Non-traditional learning day", dates=jan(28), posted=WED_MORNING, confidence=0.9),
    row("Non-Traditional Learning Day", dates=jan(29), posted=WED_EVENING, confidence=0.9),
    row("NON-TRADITIONAL LEARNING DAY", dates=jan(28), posted=WED_MORNING, confidence=0.9),
    row("Non-traditional learning", dates=jan(28), posted=WED_MORNING, confidence=0.9),
    row("Nontraditional learning", dates=jan(28), posted=WED_MORNING, confidence=0.9),
    row("Non traditional learning days", dates=jan(29), posted=WED_EVENING, confidence=0.9),
    row(
        "Non-Traditional Learning Day; All Staff Report",
        dates=jan(28),
        posted=WED_MORNING,
        confidence=0.9,
    ),
    row("Non-traditional learning day tomorrow"),
    row("Thursday: Non-traditional learning day"),
    row("NTID", dates=jan(28), posted=WED_MORNING, confidence=0.9),
    row("Code NTID", dates=jan(29), posted=WED_EVENING, confidence=0.9),
    row("NTID tomorrow"),
    row("Thursday: NTID"),
    row("Closed tomorrow - NTID", confidence=0.9),
    row("Flexible instruction", dates=jan(28), posted=WED_MORNING, confidence=0.9),
    row("flexible instruction", dates=jan(29), posted=WED_EVENING, confidence=0.9),
    row("FLEXIBLE INSTRUCTION", dates=jan(28), posted=WED_MORNING, confidence=0.9),
    row("Flex instruction", dates=jan(28), posted=WED_MORNING, confidence=0.9),
    row("Flexible instruction tomorrow"),
    row("Flexible instruction Thursday"),
    row("Flexible instruction day", dates=jan(28), posted=WED_MORNING, confidence=0.9),
    row("Non-traditional instruction", dates=jan(28), posted=WED_MORNING, confidence=0.9),
    # A closure that says it is a day of learning at home is that day.
    row("CLOSED. FLEXIBLE INSTRUCTION", dates=jan(28), posted=WED_MORNING, confidence=0.9),
    row("closed, flexible instruction", dates=jan(28), posted=WED_MORNING, confidence=0.9),
    row("closed. flexible instruction", dates=jan(29), posted=WED_EVENING, confidence=0.9),
    row("CLOSED. FLEX INSTRUCTION", dates=jan(28), posted=WED_MORNING, confidence=0.9),
    row("Closed - Flexible Instructional Day", dates=jan(28), posted=WED_MORNING, confidence=0.9),
    row("Closed Thursday - Flexible Instruction Day", confidence=0.9),
    row("Closed. All Virtual", dates=jan(28), posted=WED_MORNING, confidence=0.9),
    row("Closed; NTI day", dates=jan(28), posted=WED_MORNING, confidence=0.9),
    row("Closed tomorrow; non-traditional learning day", confidence=0.9),
    row("Tomorrow: Non-traditional learning day"),
    row("Non-traditional learning day Thursday and Friday", dates=jan(29, 30)),
    row("Flexible instruction Thursday; staff report at 9:00", notes=("staff",)),
    row("Non-traditional day", dates=jan(28), posted=WED_MORNING, confidence=0.9),
    row("Non-Traditional Instruction Day (NTID) tomorrow"),
    row("No school NTID", dates=jan(28), posted=WED_MORNING, confidence=0.9),
    row(
        "No school - non-traditional learning day",
        dates=jan(28),
        posted=WED_MORNING,
        confidence=0.9,
    ),
    row(
        "No school non-traditional learning day", dates=jan(28), posted=WED_MORNING, confidence=0.9
    ),
    row("Wednesday Morning: Non-Traditional Learning Day", dates=jan(28), posted=WED_MORNING),
    # Called off, or not settled.
    row(
        "Non-traditional learning day cancelled",
        "other",
        (),
        posted=WED_MORNING,
        confidence=0.9,
        notes=("revoked",),
    ),
    row("NTID cancelled", "other", (), posted=WED_MORNING, confidence=0.9, notes=("revoked",)),
    row(
        "Possible non-traditional learning day tomorrow",
        "other",
        (),
        confidence=0.3,
        notes=("hedged",),
    ),
    row(
        "Non-traditional learning day tomorrow (tentative)",
        "other",
        (),
        confidence=0.3,
        notes=("hedged",),
    ),
    # Posted at midday with no day named: today or tomorrow, which the text does not say.
    row("Non-traditional learning day", "other", (), confidence=0.3, notes=("undated",)),
    row("Flexible instruction", "other", (), confidence=0.3, notes=("undated",)),
]

# Stamps that say when the listing was written.
STAMPS = [
    row("As of Jan 28, 5:30am: Closed", "closed", jan(28), posted=WED_EVENING, confidence=0.9),
    row("As of Jan 28, 5:30am: Closed", "closed", jan(28), posted=WED_MORNING, confidence=0.9),
    row("Updated Jan 28, 5:30am: Closed", "closed", jan(28), posted=WED_EVENING, confidence=0.9),
    row(
        "As of Jan 28, 5:30 AM EST: 2 hour delay",
        "delayed",
        jan(28),
        posted=WED_EVENING,
        confidence=0.9,
        delay=120,
    ),
    row(
        "As of Jan. 27, 8:15 p.m.: 2 hour delay tomorrow",
        "delayed",
        jan(28),
        posted=WED_EVENING,
        delay=120,
    ),
    row("Closed tomorrow - Last Updated: 01/27/2026 08:13pm", "closed", jan(28)),
    row(
        "Closed tomorrow - Last Updated: 01/28/2026 07:13pm", "closed", jan(29), posted=WED_EVENING
    ),
    row(
        "Closed Friday - Last Updated: 01/28/2026 05:12am",
        "closed",
        jan(30),
        posted=datetime(2026, 1, 31, 9, 0, tzinfo=ZONE),
    ),
    row("Closed today. Posted Jan. 27 at 9:00 PM", "closed", jan(27), posted=WED_MORNING),
    row("Closed tomorrow. Updated 9:00 PM on 1/27", "closed", jan(28), posted=WED_MORNING),
    row("Closed tomorrow. Updated Dec 31 9:00 PM", "closed", jan(1), posted=WED_MORNING),
    # A time alone, a time that could be morning or evening, a stamp more than an hour
    # after the posting time and a day that does not exist leave the posting time.
    row("As of 5:30 AM: Closed", "closed", jan(29), posted=WED_EVENING, confidence=0.9),
    row("Closed (updated 5:43 AM)", "closed", jan(29), posted=WED_EVENING, confidence=0.9),
    row("Updated 1/27 5:30: Closed tomorrow", "closed", jan(29), posted=WED_EVENING),
    row("Closed today (updated Jan 29 5:43 AM)", "closed", jan(28), posted=WED_MORNING),
    row("Updated Feb 30 1:00 PM: Closed today", "closed", jan(28), posted=WED_MORNING),
    # "As of" with a time first says when something takes effect, not when it was written.
    row(
        "As of 2:00pm, Tuesday, January 27, all offices will close due to weather.",
        "other",
        (),
        confidence=0.1,
        notes=("unrecognized",),
    ),
]


@pytest.mark.parametrize("case", NON_TRADITIONAL_SENTENCES)
def test_a_statewide_non_traditional_learning_sentence_is_remote_on_its_day(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", OTHER_SENTENCES)
def test_a_statewide_sentence_applies_to_its_own_day_only(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", REMOTE_WORDING)
def test_non_traditional_learning_and_flexible_instruction_are_remote(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", STAMPS)
def test_a_stamp_with_a_date_and_a_time_is_when_the_listing_was_written(case: Row) -> None:
    check(case)


def test_the_tables_cover_every_form() -> None:
    tables = (NON_TRADITIONAL_SENTENCES, OTHER_SENTENCES, REMOTE_WORDING, STAMPS)
    assert sum(map(len, tables)) >= 80


@pytest.mark.parametrize(
    ("text", "written"),
    [
        ("Remote learning day Friday - Last Updated: 01/09/2025 05:13am", (1, 9, 2025, 5, 13)),
        ("As of Jan. 28, 1:58 p.m.: All schools", (1, 28, None, 13, 58)),
        ("Posted Jan. 19 at 9:00 PM: closed", (1, 19, None, 21, 0)),
        ("last updated: 1/19/26 8:45:12 PM EST", (1, 19, 2026, 20, 45)),
        ("Updated 9:00 PM on 1/19", (1, 19, None, 21, 0)),
        ("updated 1/28 17:30", (1, 28, None, 17, 30)),
        ("Updated Sept. 3, 2025 12:05 am", (9, 3, 2025, 0, 5)),
        ("Revised: Monday, Jan 26 7 PM", (1, 26, None, 19, 0)),
        ("Closed (updated 5:43 AM)", None),
        ("updated 1/28 5:30", None),
        ("updated 1/28 13:75", None),
        ("updated 1/28 0:30 am", None),
        ("As of 2:00pm, Tuesday, January 10, all offices will close", None),
        ("Closed tomorrow", None),
        ("Updated to a 2 hour delay", None),
    ],
)
def test_written_at_reads_a_stamp_with_a_date_and_a_time(
    text: str, written: tuple[int, int, int | None, int, int] | None
) -> None:
    assert written_at(text) == written


def test_an_as_of_heading_is_dropped_from_the_text() -> None:
    assert normalize("As of Jan 28, 1:58pm: All schools closed") == "all schools closed"
    assert (
        normalize("As of 2:00pm, Tuesday: offices close") == "as of 2:00pm, tuesday: offices close"
    )


# Properties ---------------------------------------------------------------------------------

SYLLABLES = ("al", "der", "quar", "ry", "fern", "hill", "birch", "mont", "wil", "low", "ash")
counties = st.lists(st.sampled_from(SYLLABLES), min_size=2, max_size=3).map(
    lambda parts: "".join(parts).title()
)
STATUSES = {
    "will be non-traditional learning on": ("remote", None),
    "will be non-traditional learning day on": ("remote", None),
    "will be closed on": ("closed", None),
    "will be on a 2-hour delay on": ("delayed", 120),
    "will be on a 3-hour delay on": ("delayed", 180),
}
ENDINGS = (
    ".", " due to Weather.", " due to continued inclement weather.", ", Code C.", " due to snow.",
    " due to poor secondary road conditions and low temperatures.", ", Code orange.",
)  # fmt: skip
# The code for a non-traditional instruction day ends only a sentence that says one.
REMOTE_ENDINGS = (*ENDINGS, " due to continuing effects of the winter storm, Code NTID.")


def _with_ending(status: str) -> st.SearchStrategy[tuple[str, str]]:
    endings = REMOTE_ENDINGS if STATUSES[status][0] == "remote" else ENDINGS
    return st.tuples(st.just(status), st.sampled_from(endings))


WEEKDAY_ABBREVIATIONS = ("Mon.", "Tue.", "Wed.", "Thu.", "Fri.", "Sat.", "Sun.")
MONTH_ABBREVIATIONS = (
    "Jan.", "Feb.", "Mar.", "Apr.", "May", "Jun.", "Jul.", "Aug.", "Sep.", "Oct.", "Nov.", "Dec.",
)  # fmt: skip


def _clock(moment: time) -> str:
    hour = moment.hour % 12 or 12
    return f"{hour}:{moment.minute:02d}{'am' if moment.hour < 12 else 'pm'}"


@settings(max_examples=300, deadline=None)
@given(
    county=counties,
    sentence=st.sampled_from(tuple(STATUSES)).flatmap(_with_ending),
    written_day=st.dates(min_value=date(2021, 11, 1), max_value=date(2030, 3, 31)),
    written_time=st.times(min_value=time(6, 0), max_value=time(22, 59)),
    ahead=st.integers(min_value=1, max_value=3),
    seen_after=st.integers(min_value=0, max_value=600),
)
def test_a_statewide_sentence_is_its_status_on_the_day_it_names(  # noqa: PLR0913, PLR0917
    county: str,
    sentence: tuple[str, str],
    written_day: date,
    written_time: time,
    ahead: int,
    seen_after: int,
) -> None:
    status, ending = sentence
    day = written_day + timedelta(days=ahead)
    stated = (
        f"{WEEKDAY_ABBREVIATIONS[day.weekday()]} {MONTH_ABBREVIATIONS[day.month - 1]}"
        f" {day.day}, {day.year}"
    )
    heading = f"As of {MONTH_ABBREVIATIONS[written_day.month - 1].rstrip('.')} {written_day.day}"
    text = f"{heading}, {_clock(written_time)}: All schools in {county} County {status} {stated}"
    written = datetime.combine(written_day, written_time, tzinfo=ZONE)
    result = parse_status(
        text + ending, posted_at=written + timedelta(minutes=seen_after), tz="America/New_York"
    )
    kind, delay = STATUSES[status]
    assert written_day not in result.dates
    if day.weekday() >= 5:  # Saturday and Sunday
        return  # (a weekend day is noted and weighed, see the weekend tables)
    assert result.kind == kind
    assert result.dates == (day,)
    assert result.confidence == 0.95
    assert result.delay_minutes == delay


REMOTE_PHRASES = (
    "Non-traditional learning day", "Non-Traditional Learning", "Nontraditional learning",
    "NTID", "Code NTID", "Flexible instruction", "Flexible instruction day",
    "CLOSED. FLEXIBLE INSTRUCTION", "Closed, flexible instruction", "Closed - NTID",
    "Non-traditional instruction", "NTI day",
)  # fmt: skip


@settings(max_examples=300, deadline=None)
@given(
    phrase=st.sampled_from(REMOTE_PHRASES),
    day_word=st.sampled_from(("", " tomorrow", " Thursday", " Thu. Jan. 29")),
    posted=st.datetimes(
        min_value=datetime(2026, 1, 28, 4, 0), max_value=datetime(2026, 1, 28, 23, 59)
    ).map(lambda moment: moment.replace(tzinfo=ZONE)),
)
def test_non_traditional_learning_is_never_a_closure(
    phrase: str, day_word: str, posted: datetime
) -> None:
    # (Posted from 4 a.m. on: before then "tomorrow" is the day that has begun.)
    result = parse_status(phrase + day_word, posted_at=posted, tz=TZ)
    assert result.kind in {"remote", "other"}
    assert all(entry.kind == "remote" for entry in result.schedule)
    if day_word:
        assert result.kind == "remote"
        assert result.dates == jan(29)
