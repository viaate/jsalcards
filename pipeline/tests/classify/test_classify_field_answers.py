"""Field answers, zero lengths, restated numbers and hyphen-joined phrases.

Every text here is a phrasing pattern written for these tests, not a claim
about a real school. Each is posted at 6 a.m. on Wednesday 21 January 2026 in
Chicago, so a status that names no day is for Wednesday the 21st.

* A status word used as a field label and answered with nothing ("Delay: 0",
  "Closed: --", "Early dismissal: 0") or with "no" or "not" ("Closed: No",
  "Closed - not") says the status does not apply: no status, noted as negated.
  So does a length of zero ("0 hour delay"), and a "not" that ends the
  status's clause ("Closed not").
* "Snowed out" is a closure; buses that will not run are news of
  transportation only.
* A number word restated in figures ("Two (2) hour delay") is one length, not a
  length and a bracketed count; figures that disagree with the word ("Two (3)")
  leave the length unsaid.
* Two phrases joined by a hyphen or a slash with no spaces ("No School-No
  Personnel Report Today", "Open/No Transportation") read as they do with
  spaced dashes: each "no" starts its own phrase. So does a "no", "not" or
  "none" joined to the status before it: "Closed/no virtual" is a closure with
  no virtual learning, as "Closed / no virtual" is, never a remote day;
  "2 hr delay/no virtual" is a delay, and "Open/not delayed" states nothing. A
  day that ends such a listing is the status's: "Closed/no virtual tomorrow" is
  closed tomorrow. A hyphen after a "no" of its own joins it to the word it
  denies: "No-delay" states nothing, and "Closed, no-virtual" is a closure.
* A day that heads a listing, or a sentence of it, reaches the status across
  a clause that only says where ("(Tomorrow) All locations-no classes",
  "Tomorrow, Lincoln Elementary - 2 hour delay"); a day that ends a listing
  reaches it across a "no ..." phrase the parser does not know ("Closed - no
  extended care; through January 23"). A clause with a hedge or a condition, or
  a sentence mark, stops it ("Tomorrow, if the roads are icy - closed"). A day
  no status takes that cannot be told (an impossible date, a run too long to be
  one closure) leaves an undated status's day unclear: it never falls on the
  posting day.
* An answer of "yes/no" left in a field ("Closed: yes/no") states nothing
  either way: the status is ambiguous.
* Link markup and web addresses say nothing: their words ("weather-and-
  emergency-information") are dropped.
* A day that ends a listing after a "no ..." note is the listing's day: "2 Hour
  Delay - No AM Pre-K 2/4" is a delay on the 4th with no AM Pre-K. A note of
  another kind keeps its day to itself ("Closed; concert cancelled Monday").
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
POSTED = datetime(2026, 1, 21, 6, 0, tzinfo=ZONE)  # Wednesday
WEDNESDAY = (date(2026, 1, 21),)
THURSDAY = (date(2026, 1, 22),)
FRIDAY = (date(2026, 1, 23),)


@dataclass(frozen=True)
class Row:
    text: str
    kind: str
    dates: tuple[date, ...]
    delay: int | None
    confidence: float
    notes: tuple[str, ...]


def row(  # noqa: PLR0913 - one table row
    text: str,
    kind: str,
    dates: tuple[date, ...] = (),
    *,
    delay: int | None = None,
    confidence: float = 0.9,
    notes: tuple[str, ...] = (),
) -> object:
    return pytest.param(Row(text, kind, dates, delay, confidence, notes), id=text)


def no_status(text: str) -> object:
    """A text that says the status does not apply: nothing stated, noted as negated."""
    return row(text, "other", notes=("negated",))


# A status word as a field label, answered with a zero, a dash or a "no".
FIELD_ANSWERS = [
    no_status("Delay: 0"),
    no_status("Delays: 0"),
    no_status("Delay:0"),
    no_status("Delay: 00"),
    no_status("Delay - 0"),
    no_status("Closed: 0"),
    no_status("Closed - 0"),
    no_status("Closings: 0"),
    no_status("Early dismissal: 0"),
    no_status("Early release: 0"),
    no_status("Remote learning: 0"),
    no_status("NTI: 0"),
    no_status("Late Start: 0"),
    no_status("2 hour delay: 0"),
    no_status("Delay: --"),
    no_status("Delay: -"),
    no_status("Closed: --"),
    no_status("2 hour delay: --"),
    no_status("Closed: No"),
    no_status("Delay: None"),
    # Answered "not", after a colon or a dash.
    no_status("Closed: not"),
    no_status("Closed - not"),
    no_status("Closed - Not"),
    no_status("Delay -- not"),
]

# A "not" that ends the status's clause denies it: "Closed not" is not closed.
TRAILING_NOT = [
    no_status("Closed not"),
    no_status("School closed not"),
    no_status("Closed not today"),
    no_status("Delay not"),
]

# A closure said as "snowed out"; buses that will not run are news of transportation only.
SNOWED_OUT_AND_BUSES = [
    row("Snowed out", "closed", WEDNESDAY),
    row("SNOWED OUT", "closed", WEDNESDAY),
    row("Snowed out tomorrow", "closed", THURSDAY),
    row("Basketball game snowed out", "other", notes=("activities_cancelled",)),
    row("Buses will not run", "other", notes=("transportation",)),
    row("Buses are not running", "other", notes=("transportation",)),
    row("Buses not operating", "other", notes=("transportation",)),
    row("Closed; buses will not run", "closed", WEDNESDAY, notes=("transportation",)),
]

# A length of zero: no delay and no early dismissal.
ZERO_LENGTHS = [
    no_status("0 hour delay"),
    no_status("0-hour delay"),
    no_status("0 hr delay"),
    no_status("0 minute delay"),
    no_status("Delay 0 hours"),
    no_status("Delayed: 0 hours"),
    no_status("Delay: 0 min"),
    no_status("Delayed 0 minutes"),
    no_status("Zero hour delay"),
    no_status("Zero-hour delay"),
    no_status("Zero hr delay"),
    no_status("Zero minute delay"),
    no_status("Zero hours late"),
    no_status("Zero hour late start"),
    no_status("Delayed zero hours"),
    no_status("0 Hour Delay Tomorrow"),
    no_status("Delayed Wednesday 0 hours"),
    no_status("Dismissing 0 hours early"),
    no_status("0 hours early dismissal"),
    no_status("Early dismissal 0 hours"),
    no_status("Closing early Tuesday 0 hours"),
]

# A number word restated in figures: one length.
RESTATED_NUMBERS = [
    row("Two (2) hour delay", "delayed", WEDNESDAY, delay=120),
    row("TWO (2) HOUR DELAY", "delayed", WEDNESDAY, delay=120),
    row("two(2) hour delay", "delayed", WEDNESDAY, delay=120),
    row("Two (2) Hour Delay Tomorrow", "delayed", THURSDAY, delay=120, confidence=0.95),
    row("Three (3) hour delay", "delayed", WEDNESDAY, delay=180),
    row("One (1) hour delay", "delayed", WEDNESDAY, delay=60),
    row("Ninety (90) minute delay", "delayed", WEDNESDAY, delay=90),
    # Figures that disagree with the word: the length is not said.
    row("Two (3) hour delay", "delayed", WEDNESDAY),
]

# Phrases joined by a hyphen or a slash read as they do with a spaced dash.
JOINED = [
    row("No School-No Personnel Report", "closed", WEDNESDAY, notes=("staff",)),
    row("No School-No Personnel Report Today", "closed", WEDNESDAY, confidence=0.95,
        notes=("staff",)),
    row("No School - No Personnel Report Today", "closed", WEDNESDAY, confidence=0.95,
        notes=("staff",)),
    row("NO SCHOOL-NO ACTIVITIES", "closed", WEDNESDAY, notes=("activities_cancelled",)),
    row("No school-no bus service", "closed", WEDNESDAY, notes=("transportation",)),
    row("No School-Snow Day", "closed", WEDNESDAY),
    row("Closed-No Activities", "closed", WEDNESDAY, notes=("activities_cancelled",)),
    row("Closed/No PM Activities", "closed", WEDNESDAY, notes=("activities_cancelled",)),
    row("CLOSED-NO DAY CARE", "closed", WEDNESDAY, notes=("childcare",)),
    row("2 Hr Dly/No AM Pre-K", "delayed", WEDNESDAY, delay=120, notes=("partial_program",)),
    row("Open-No Buses", "other", notes=("transportation",)),
    row("Open/No Transportation", "other", notes=("transportation",)),
    # A hyphened word after "no" is still one word: nothing is closed.
    no_status("No school-related closings"),
]  # fmt: skip

# A "no", "not" or "none" joined to the status before it by a slash or a hyphen denies what
# follows it, as it does spaced out: "Closed/no virtual" is a closure, never a remote day.
DENIED_BY_MARK = [
    row("Closed/no virtual", "closed", WEDNESDAY, notes=("negated",)),
    row("CLOSED/NO REMOTE", "closed", WEDNESDAY, notes=("negated",)),
    row("Closed/no remote learning", "closed", WEDNESDAY, notes=("negated",)),
    row("Closed/no e-learning", "closed", WEDNESDAY, notes=("negated",)),
    row("Closed/no NTI", "closed", WEDNESDAY, notes=("negated",)),
    row("Snow day/no virtual", "closed", WEDNESDAY, notes=("negated",)),
    row("2 hr delay/no virtual", "delayed", WEDNESDAY, delay=120, notes=("negated",)),
    row("Closed-no virtual", "closed", WEDNESDAY, notes=("negated",)),
    row("CLOSED-NO NTI", "closed", WEDNESDAY, notes=("negated",)),
    row("Closed/No Virtual Learning", "closed", WEDNESDAY, notes=("negated",)),
    row("Closed/no AMI", "closed", WEDNESDAY, notes=("negated",)),
    row("Closed/no eLearning day", "closed", WEDNESDAY, notes=("negated",)),
    row("Closed/not virtual", "closed", WEDNESDAY, notes=("negated",)),
    row("Closed/no delay", "closed", WEDNESDAY, notes=("negated",)),
    row("Delayed/not closed", "delayed", WEDNESDAY, notes=("negated",)),
    row("Early dismissal at 1:00/no virtual", "early_dismissal", WEDNESDAY, notes=("negated",)),
    row("Wednesday: Closed/no NTI", "closed", WEDNESDAY, confidence=0.95, notes=("negated",)),
    # A hyphen after a "no" of its own joins it to the word it denies.
    row("Closed, no-virtual", "closed", WEDNESDAY, notes=("negated",)),
    row("Closed/No-Virtual", "closed", WEDNESDAY, notes=("negated",)),
    row("No-School Today", "closed", WEDNESDAY, confidence=0.95),
    no_status("No-delay"),
    no_status("Open, no-delay"),
    no_status("No-school-related closings"),
    # Nothing stated: an open school, or a field answered no.
    no_status("Open/no delay"),
    no_status("Open/not delayed"),
    no_status("Open/Not Closed"),
    no_status("Closed/no"),
    no_status("Closed/none"),
    # The day that ends the listing is the status's, joined or spaced.
    row("Closed/no virtual tomorrow", "closed", THURSDAY, confidence=0.95, notes=("negated",)),
    row("Closed - no virtual tomorrow", "closed", THURSDAY, confidence=0.95,
        notes=("negated",)),
    row("Closed, no e-learning Friday", "closed", FRIDAY, confidence=0.95, notes=("negated",)),
    row("2 hr delay/no virtual Friday", "delayed", FRIDAY, delay=120, confidence=0.95,
        notes=("negated",)),
    row("Closed Tomorrow; Snow Day-No E-Learning", "closed", THURSDAY, confidence=0.95,
        notes=("negated",)),
    # "yes/no" is one word: an answer left open.
    row("Closed: yes/no", "other", confidence=0.3, notes=("ambiguous",)),
    row("Delay: Y/N", "other", confidence=0.3, notes=("ambiguous",)),
]  # fmt: skip

# A day that heads a listing, or ends it, reaches its status across a clause that says where
# or what else; a hedge, a condition or a sentence mark stops it.
ACROSS_A_SCOPE = [
    row("(Tomorrow) All locations-no classes", "closed", THURSDAY, confidence=0.95),
    row("(TOMORROW) ALL LOCATIONS - CLOSED", "closed", THURSDAY, confidence=0.95),
    row("Tomorrow, Lincoln Elementary - 2 hour delay", "delayed", THURSDAY, delay=120,
        confidence=0.95),
    row("Closed. Friday, all campuses - remote learning", "remote", FRIDAY, confidence=0.95),
    row("Closed - no extended care; through January 23", "closed",
        (*WEDNESDAY, *THURSDAY, *FRIDAY), confidence=0.95),
    row("CLOSED-NO EXTENDED CARE; THROUGH JANUARY 23", "closed",
        (*WEDNESDAY, *THURSDAY, *FRIDAY), confidence=0.95),
    row("Closed - no extended care; Friday", "closed", FRIDAY, confidence=0.95),
    row("Remote Learning Day - No Meal Services. (For Fri. Jan 23rd)", "remote", FRIDAY,
        confidence=0.95),
    row("(Tomorrow) All three campuses - closed", "closed", THURSDAY, confidence=0.95),
    row("Closed - no buses; Friday", "closed", FRIDAY, confidence=0.95,
        notes=("transportation",)),
    # A heading's day is its slot's, whatever the slot says: Thursday is open.
    row("(Wednesday) Lincoln Elementary - Closed | (Thursday) Lincoln Elementary - Open",
        "closed", WEDNESDAY, confidence=0.95),
    # A hedge, a condition, a sentence mark, a part of the day, a noun for something else
    # or part of the district between: the day is not the status's.
    row("Tomorrow, if the roads are icy - closed", "other", confidence=0.3, notes=("hedged",)),
    row("Tomorrow. All locations. Closed.", "other", confidence=0.3, notes=("undated",)),
    row("(Tomorrow) Evening - closed", "other", confidence=0.3, notes=("undated",)),
    row("Tomorrow, staff report - closed", "other", confidence=0.3, notes=("undated",)),
    row("(Tomorrow) North campus - closed", "other", confidence=0.3, notes=("undated",)),
    row("Tomorrow, probably - closed", "other", confidence=0.3, notes=("undated",)),
    # A day no status takes that cannot be told: the status's day is unclear.
    row("Closed; offices open through 2/30", "other", confidence=0.3, notes=("undated",)),
    row("Closed - no extended care; through 2/30", "other", confidence=0.3,
        notes=("invalid_date",)),
    row("Closed; offices open through April 24", "other", confidence=0.3, notes=("undated",)),
]  # fmt: skip

# The day that ends a listing after a "no ..." note: the status's day too.
LISTING_DAYS = [
    row("2 Hour Delay - No AM Pre-K 2/4", "delayed", (date(2026, 2, 4),), delay=120,
        confidence=0.95, notes=("partial_program",)),
    row("2 Hour Delay-No AM Pre-K 2/4", "delayed", (date(2026, 2, 4),), delay=120,
        confidence=0.95, notes=("partial_program",)),
    row("2 Hour Delay, No AM Pre-K Friday", "delayed", (date(2026, 1, 23),), delay=120,
        confidence=0.95, notes=("partial_program",)),
    row("CLOSED-NO ACTIVITIES Tuesday, January 27", "closed", (date(2026, 1, 27),),
        confidence=0.95, notes=("activities_cancelled",)),
    row("Closed - No activities Friday due to snow", "closed", (date(2026, 1, 23),),
        confidence=0.95, notes=("activities_cancelled",)),
    row("No School-No Personnel Report Tomorrow", "closed", THURSDAY, confidence=0.95,
        notes=("staff",)),
    row("Remote Learning-No In-Person Classes 1/23", "remote", (date(2026, 1, 23),),
        confidence=0.8, notes=("ambiguous",)),
    # Not the listing's day: another kind of note, or more after the day, or the day
    # before the status.
    row("Closed; concert cancelled Monday", "other", confidence=0.3,
        notes=("activities_cancelled", "undated")),
    row("Closed - No activities Friday. Offices open", "other", confidence=0.3,
        notes=("activities_cancelled", "undated")),
    row("No AM Pre-K 2/4 - 2 hour delay", "other", confidence=0.3,
        notes=("partial_program", "undated")),
    # A status with its own day keeps it.
    row("Closed Thursday - No activities Friday", "closed", THURSDAY, confidence=0.95,
        notes=("activities_cancelled",)),
]  # fmt: skip

# What still states a status: an answer that is not "no", or a length that is not zero.
STILL_STATED = [
    row("Closed: - Offices open", "closed", WEDNESDAY),
    row("Closed: Yes", "closed", WEDNESDAY),
    row("Closed: 2", "closed", WEDNESDAY),
    row("Delay: 0.5 hours", "delayed", WEDNESDAY, delay=30),
    row("Delay: 2 hours", "delayed", WEDNESDAY, delay=120),
    row("Delay: 10", "delayed", WEDNESDAY),
]

# A link's markup and a web address are dropped, words and all.
LINKS = [
    row('Closed. <a href="https://example.org/2-hour-delay-info" target="_blank">More Info</a>',
        "closed", WEDNESDAY),
    row("Closed - see https://example.org/2-hour-delay-info", "closed", WEDNESDAY),
    row("Closed. See www.example.org/snow-days-tuesday for more", "closed", WEDNESDAY),
    row('<a href="https://example.org/closures/delay-tuesday">More Info Here</a>', "other",
        confidence=0.1, notes=("unrecognized",)),
]  # fmt: skip

ALL_ROWS = (
    LINKS + FIELD_ANSWERS + TRAILING_NOT + SNOWED_OUT_AND_BUSES + ZERO_LENGTHS + RESTATED_NUMBERS
    + JOINED + DENIED_BY_MARK + ACROSS_A_SCOPE + LISTING_DAYS + STILL_STATED
)  # fmt: skip


@pytest.mark.parametrize("case", ALL_ROWS)
def test_reading(case: Row) -> None:
    result = parse_status(case.text, posted_at=POSTED, tz=TZ)
    assert result.kind == case.kind
    assert result.dates == case.dates
    assert result.delay_minutes == case.delay
    assert result.confidence == case.confidence
    assert result.notes == case.notes


LABELS = [
    "Delay", "Delays", "Closed", "Closing", "Closings", "Early dismissal", "Early release",
    "Remote learning", "NTI", "Late start", "2 hour delay",
]  # fmt: skip
EMPTY_ANSWERS = ["0", "00", "--", "-", "No", "None", "N/A"]
MARKS = [": ", ":", " : ", " - "]


@settings(max_examples=150, deadline=None)
@given(
    label=st.sampled_from(LABELS),
    mark=st.sampled_from(MARKS),
    answer=st.sampled_from(EMPTY_ANSWERS),
    upper=st.booleans(),
)
def test_an_empty_answer_to_a_status_field_states_nothing(
    label: str, mark: str, answer: str, upper: bool
) -> None:
    if mark == " - " and answer in {"--", "-"}:
        return  # ("Delay - --" is only dashes)
    text = f"{label}{mark}{answer}"
    result = parse_status(text.upper() if upper else text, posted_at=POSTED, tz=TZ)
    assert result.kind == "other"
    assert "negated" in result.notes


WORDS = {"one": 1, "two": 2, "three": 3, "four": 4}


@settings(max_examples=60, deadline=None)
@given(
    word=st.sampled_from(sorted(WORDS)),
    gap=st.sampled_from(["", " "]),
    unit=st.sampled_from(["hour", "Hour", "HOUR"]),
    agree=st.booleans(),
)
def test_a_number_word_restated_in_figures_is_one_length(
    word: str, gap: str, unit: str, agree: bool
) -> None:
    figures = WORDS[word] if agree else WORDS[word] + 1
    text = f"{word.title()}{gap}({figures}) {unit} delay"
    result = parse_status(text, posted_at=POSTED, tz=TZ)
    assert result.kind == "delayed"
    assert result.delay_minutes == (60 * WORDS[word] if agree else None)


NOTES = ["No Personnel Report", "No Activities", "No Bus Service", "No Preschool", "Snow Day"]


@settings(max_examples=60, deadline=None)
@given(
    head=st.sampled_from(["No School", "NO SCHOOL", "Closed"]),
    note=st.sampled_from(NOTES),
    day=st.sampled_from(["", " Today", " Tomorrow"]),
)
def test_a_hyphen_joins_phrases_as_a_spaced_dash_does(head: str, note: str, day: str) -> None:
    joined = parse_status(f"{head}-{note}{day}", posted_at=POSTED, tz=TZ)
    spaced = parse_status(f"{head} - {note}{day}", posted_at=POSTED, tz=TZ)
    assert joined == spaced
    assert joined.kind == "closed"
    assert joined.dates == (THURSDAY if day == " Tomorrow" else WEDNESDAY)


# A status and its kind, and the statuses a "no" after it can deny (none of its kind). ("No
# classes - no virtual" is unclear either way: see test_classify_negated_nouns.)
DENYING_HEADS = {
    "Closed": "closed", "CLOSED": "closed", "Snow Day": "closed", "School closed": "closed",
    "Classes cancelled": "closed", "2 hr delay": "delayed", "Two Hour Delay": "delayed",
    "Late start": "delayed", "Early dismissal": "early_dismissal", "Open": "other",
}  # fmt: skip
DENIED_NOUNS = {
    "virtual": "remote", "Virtual Learning": "remote", "remote": "remote",
    "remote learning": "remote", "e-learning": "remote", "eLearning": "remote", "NTI": "remote",
    "AMI": "remote", "NTI day": "remote", "online classes": "remote", "delay": "delayed",
    "closing": "closed",
}  # fmt: skip
DENIALS = ["no", "No", "NO", "not", "NOT"]
DENIED_DAYS = {"": WEDNESDAY, " today": WEDNESDAY, " tomorrow": THURSDAY, " Friday": FRIDAY}


@settings(max_examples=300, deadline=None)
@given(
    head=st.sampled_from(sorted(DENYING_HEADS)),
    mark=st.sampled_from(["/", "-"]),
    denial=st.sampled_from(DENIALS),
    noun=st.sampled_from(sorted(DENIED_NOUNS)),
    day=st.sampled_from(sorted(DENIED_DAYS)),
)
def test_a_denial_joined_by_a_mark_reads_as_a_spaced_one(
    head: str, mark: str, denial: str, noun: str, day: str
) -> None:
    kind = DENYING_HEADS[head]
    if DENIED_NOUNS[noun] == kind or (kind == "other" and DENIED_NOUNS[noun] == "remote"):
        return  # ("Closed/no closing" says nothing; "Open/no virtual" is no status either way)
    joined = parse_status(f"{head}{mark}{denial} {noun}{day}", posted_at=POSTED, tz=TZ)
    spaced = parse_status(f"{head} {mark} {denial} {noun}{day}", posted_at=POSTED, tz=TZ)
    assert joined == spaced
    assert joined.kind == kind
    assert "negated" in joined.notes
    assert joined.dates == (() if kind == "other" else DENIED_DAYS[day])
    if denial.lower() == "no":
        # A hyphen after the "no" joins it to the noun it denies: "Closed/no-virtual".
        hyphened = f"{head}{mark}{denial}-{noun}{day}"
        assert parse_status(hyphened, posted_at=POSTED, tz=TZ) == joined


@pytest.mark.parametrize(
    ("text", "terms", "reason"),
    [
        ("No School-Snow Day", ("snow",), "Winter storm"),
        ("No School - Snow Day", ("snow",), "Winter storm"),
        ("Closed/Icy Roads", ("ice",), "Ice"),
        ("Closed-Power Outage", (), "Power outage"),
        # The words of a web address name no weather.
        ('Closed. <a href="https://example.org/weather-and-snow">More Info</a>', (), None),
        ("Closed. See www.example.org/snow-and-ice for more", (), None),
    ],
)
def test_weather_in_joined_words_and_links(text: str, terms: tuple[str, ...], reason: str) -> None:
    result = parse_status(text, posted_at=POSTED, tz=TZ)
    assert result.weather_terms == terms
    assert result.reason == reason
