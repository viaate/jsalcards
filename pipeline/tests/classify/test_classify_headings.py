"""Day headings, school names and side notes around a status.

Every text here is a phrasing pattern written for these tests, not a claim
about a real school. Unless a row says otherwise it is posted at 6 a.m. on
Wednesday 21 January 2026 in Chicago.

* Closings pages often head each entry with a day ("Monday: Closed"), repeat
  the day inside it ("Monday: Closed Monday") or split one day into parts
  ("Monday Morning: Closed...... Monday Afternoon: Closed"). A day named again
  is the same day. A heading that names a different day from the status
  ("Sunday: Closed Monday") is two day words that disagree with no date to
  settle them, so that status is left out.
* A school's own name before a status ("Lincoln Elementary: Closed") is about
  the school; a bare level ("Elementary: closed") is part of the program.
* A status that names no day is read from the posting time only when a day
  named for a side note agrees with it ("Closed; offices open Monday").
"""

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from snowlight.classify import parse_status

TZ = "America/Chicago"
ZONE = ZoneInfo(TZ)
WED = datetime(2026, 1, 21, 6, 0, tzinfo=ZONE)
WED_EVENING = datetime(2026, 1, 21, 20, 0, tzinfo=ZONE)
SUN = datetime(2026, 1, 25, 15, 0, tzinfo=ZONE)
TUE_EVENING = datetime(2026, 1, 20, 18, 30, tzinfo=ZONE)


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
    kind: str,
    dates: tuple[date, ...] = (),
    *,
    posted: datetime = WED,
    confidence: float = 0.95,
    notes: tuple[str, ...] = (),
) -> object:
    return pytest.param(
        Row(text, posted, kind, dates, confidence, notes), id=f"{text} @ {posted:%a %H:%M}"
    )


HEADINGS = [
    row("Monday: Closed Monday", "closed", jan(26), posted=SUN),
    row("Thursday: Closed Thursday", "closed", jan(22), posted=WED_EVENING),
    row("Monday: Closed Monday, no activities", "closed", jan(26), posted=SUN),
    row("Wednesday: Closing at 10:30am Wednesday", "early_dismissal", jan(21)),
    row("Monday Morning: Closed...... Monday Afternoon: Closed", "closed", jan(26), posted=SUN),
    row(
        "Monday Morning: Closed...... Monday Afternoon: Closed...... Tuesday: 2 hour delay",
        "closed",
        jan(26),
        posted=SUN,
    ),
    row(
        "Wednesday Morning: Closed...... Wednesday Afternoon: Closed...... Thursday: Closed",
        "closed",
        jan(21, 22),
        posted=TUE_EVENING,
    ),
    row(
        "Monday Morning: Closed...... Monday Evening: No activities",
        "closed",
        jan(26),
        posted=SUN,
        notes=("activities_cancelled",),
    ),
    row("Monday Morning: Closed...... Monday Evening: Closed", "closed", jan(26), posted=SUN),
    # A heading and a day inside the status that disagree: that status is left out.
    row("Sunday: Closed Monday", "other", posted=SUN, confidence=0.3, notes=("date_mismatch",)),
    row("Wednesday: Closed Thursday", "other", confidence=0.3, notes=("date_mismatch",)),
    row(
        "Sunday: Closed Monday...... Monday: Closed Monday",
        "closed",
        jan(26),
        posted=SUN,
        confidence=0.8,
        notes=("date_mismatch",),
    ),
    row(
        "Wednesday: Closed on Thursday...... Thursday: Closed on Thursday",
        "closed",
        jan(22),
        posted=WED_EVENING,
        confidence=0.8,
        notes=("date_mismatch",),
    ),
    # An evening names no school day, even in a run of weekday names.
    row("Sunday Evening: Closed Monday", "closed", jan(26), posted=SUN),
    row("Closed Sunday evening and Monday", "closed", jan(26), posted=SUN),
    row(
        "Sunday Evening: No evening activities...... Monday: Closed",
        "closed",
        jan(26),
        posted=SUN,
        notes=("activities_cancelled",),
    ),
]

SCHOOL_NAMES = [
    row("Lincoln Elementary: Closed", "closed", jan(21), confidence=0.9),
    row("Maple Grove Middle School: Closed", "closed", jan(21), confidence=0.9),
    row(
        "Oak Ridge High School: Early dismissal at 1:00", "early_dismissal", jan(21), confidence=0.9
    ),
    row("Holy Family Preschool: Closed", "closed", jan(21), confidence=0.9),
    row("Lincoln Kindergarten Center: Closed", "closed", jan(21), confidence=0.9),
    row("Lincoln Early Childhood Center: Closed", "closed", jan(21), confidence=0.9),
    row("Lincoln and Washington Elementary: Closed", "closed", jan(21), confidence=0.9),
    row("St. Mary Elementary: Closed", "closed", jan(21), confidence=0.9),
    row("Vantrelle County Elementary School: Closed tomorrow", "closed", jan(22)),
    row("Lincoln Elementary - 2 Hour Delay", "delayed", jan(21), confidence=0.9),
    row("Closed - Lincoln Elementary", "closed", jan(21), confidence=0.9),
    row("Closed - Bakutemi Zorafa Elementary #12", "closed", jan(21), confidence=0.9),
    # A road in the name ("Mill Road", "Oak Street") is part of the name, not the buses.
    row("Mill Road Elementary closed", "closed", jan(21), confidence=0.9),
    row("Oak Street Elementary: 2 hour delay", "delayed", jan(21), confidence=0.9),
    row("Bridge Street Elementary: Closed", "closed", jan(21), confidence=0.9),
    row("Route 9 Elementary - NTI day", "remote", jan(21), confidence=0.9),
    row("Flood Road Elementary closed", "closed", jan(21), confidence=0.9),
    row("Roads elementary closed", "other", confidence=0.9, notes=("partial_program",)),
    # Words that also name things in a pair ("central office", "early childhood") and the
    # opening of a level ("junior high") are part of a name before its level.
    row("Central High School: Closed", "closed", jan(21), confidence=0.9),
    row("Central Middle School: 2 hour delay", "delayed", jan(21), confidence=0.9),
    row("Central Elementary: Closed", "closed", jan(21), confidence=0.9),
    row("Central Catholic High School: Closed", "closed", jan(21), confidence=0.9),
    row("Early College High School: Closed", "closed", jan(21), confidence=0.9),
    row("Lincoln Junior High School: Closed", "closed", jan(21), confidence=0.9),
    row("Lincoln Senior High School: Closed", "closed", jan(21), confidence=0.9),
    row("Career Tech High School: 2 hour delay", "delayed", jan(21), confidence=0.9),
    # A status word that begins a school's name is part of the name.
    row("Remote Valley School: Closed", "closed", jan(21), confidence=0.9),
    row("Virtual Ridge Elementary: 2 hour delay", "delayed", jan(21), confidence=0.9),
    # A level of the program, with no name: part of the program.
    row("Senior high school: closed", "other", confidence=0.9, notes=("partial_program",)),
    row("Junior high: closed", "other", confidence=0.9, notes=("partial_program",)),
    row("Early childhood: closed", "other", confidence=0.9, notes=("partial_program",)),
    row("Central office: closed", "other", confidence=0.9, notes=("offices_closed",)),
    row("Elementary: closed", "other", confidence=0.9, notes=("partial_program",)),
    row("High school: closed", "other", confidence=0.9, notes=("partial_program",)),
    row("All elementary schools closed", "other", confidence=0.9, notes=("partial_program",)),
    row(
        "Middle and high schools: 2 hour delay", "other", confidence=0.9, notes=("partial_program",)
    ),
    row("K-5 elementary closed", "other", confidence=0.9, notes=("partial_program",)),
    row("Hot lunch cancelled", "other", confidence=0.9, notes=("partial_program",)),
    # A listing that gives parts of the program their own statuses names schools within it.
    row(
        "Lincoln Elementary closed today, middle school 2 hour delay",
        "other",
        confidence=0.9,
        notes=("partial_program",),
    ),
    # ... and so does one school on another status beside the district's: no one status.
    row(
        "2 hour delay. Washington Elementary closed.",
        "other",
        confidence=0.9,
        notes=("partial_program",),
    ),
]

SIDE_NOTE_DAYS = [
    row("Closed; offices open Monday", "other", confidence=0.3, notes=("undated",)),
    row("Closed; offices open Monday", "closed", jan(26), posted=SUN, confidence=0.8),
    row("Closed; offices open today", "closed", jan(21), confidence=0.9),
    row(
        "Closed. All activities cancelled through Friday.",
        "closed",
        jan(21),
        confidence=0.9,
        notes=("activities_cancelled",),
    ),
    row(
        "Closed. Activities cancelled tonight.",
        "closed",
        jan(21),
        confidence=0.9,
        notes=("activities_cancelled",),
    ),
    row(
        "Closed. Saturday activities cancelled.",
        "closed",
        jan(21),
        confidence=0.9,
        notes=("activities_cancelled",),
    ),
    row(
        "2 hour delay. No AM kindergarten tomorrow.",
        "other",
        confidence=0.3,
        notes=("undated", "partial_program"),
    ),
    row(
        "2 hour delay. No AM kindergarten tomorrow.",
        "delayed",
        jan(22),
        posted=WED_EVENING,
        confidence=0.9,
        notes=("partial_program",),
    ),
    row(
        "Closed. Offices closed Friday.",
        "other",
        confidence=0.3,
        notes=("undated", "offices_closed"),
    ),
]

# A statewide list gives each district's statuses as fields answered for all its schools,
# some of them or none: "Closings: All; Delays: None; Dismissals: None; Non-traditional: None".
FIELDS = [
    row(
        "Closings: All; Delays: None; Dismissals: None; Non-traditional: None; Bus info: None",
        "closed",
        jan(21),
        confidence=0.9,
        notes=("negated",),
    ),
    row(
        "Closings: All; Delays: None; Dismissals: None; Non-traditional: None; Bus info: None",
        "closed",
        jan(22),
        posted=WED_EVENING,
        confidence=0.9,
        notes=("negated",),
    ),
    row(
        "Closings: None; Delays: All; Dismissals: None; Non-traditional: None; Bus info: None",
        "delayed",
        jan(21),
        confidence=0.8,
        notes=("negated",),
    ),
    row(
        "Closings: None; Delays: None; Dismissals: None; Non-traditional: All; Bus info: None",
        "remote",
        jan(21),
        confidence=0.9,
        notes=("negated",),
    ),
    row(
        "Closings: None; Delays: All; Dismissals: None; Non-traditional: Some; Bus info: None",
        "delayed",
        jan(21),
        confidence=0.8,
        notes=("partial_program",),
    ),
    row(
        "Closings: Some; Delays: None; Dismissals: None; Non-traditional: None; Bus info: None",
        "other",
        confidence=0.9,
        notes=("partial_program",),
    ),
    row(
        "Closings: None; Delays: None; Dismissals: None; Non-traditional: None; Bus info: None",
        "other",
        confidence=0.9,
        notes=("negated",),
    ),
    row("Closings: All", "closed", jan(21), confidence=0.9),
    row("Closures: All", "closed", jan(21), confidence=0.9),
    row("Non-traditional: All", "remote", jan(21), confidence=0.9),
    row("Non traditional: All", "remote", jan(21), confidence=0.9),
    row("Non-traditional: None", "other", confidence=0.9, notes=("negated",)),
    row("Non-traditional: Yes", "remote", jan(21), confidence=0.9),
    row("Closings: see website", "other", confidence=0.3, notes=("ambiguous",)),
]

# A label set off by a dash names what the status after it is about, as a colon does
# ("District offices: Closed"): the offices, not the school. So does a hyphen with no spaces
# around it, and an en or em dash.
DASHED_LABELS = [
    row("District offices - Closed", "other", confidence=0.9, notes=("offices_closed",)),
    row(
        "Albany and Corvallis offices - Closed",
        "other",
        confidence=0.9,
        notes=("offices_closed",),
    ),
    row("Albany, Corvallis offices - closed", "other", confidence=0.9, notes=("offices_closed",)),
    row(
        "Administrative offices - closed today",
        "other",
        confidence=0.9,
        notes=("offices_closed",),
    ),
    row("County offices - closed", "other", confidence=0.9, notes=("offices_closed",)),
    row("Offices-Closed", "other", confidence=0.9, notes=("offices_closed",)),
    row("Office-closed", "other", confidence=0.9, notes=("offices_closed",)),
    row("District Offices-Closed", "other", confidence=0.9, notes=("offices_closed",)),
    row("Offices\u2013Closed", "other", confidence=0.9, notes=("offices_closed",)),
    row("District offices \u2014 Closed", "other", confidence=0.9, notes=("offices_closed",)),
    row("Offices -- Closed", "other", confidence=0.9, notes=("offices_closed",)),
    row(
        "Main Office - Closed; Schools - 2 hour delay",
        "delayed",
        jan(21),
        confidence=0.9,
        notes=("offices_closed",),
    ),
    # A school's name, the schools or a level before the dash: the school, or part of it.
    row("Lincoln Elementary - Closed", "closed", jan(21), confidence=0.9),
    row("Schools - Closed", "closed", jan(21), confidence=0.9),
    row("AM Kindergarten - No School", "other", confidence=0.9, notes=("partial_program",)),
    # The listing's day after a side note joined by a dash is the status's day too.
    row(
        "Closed-Activities Canceled Today",
        "closed",
        jan(21),
        confidence=0.95,
        notes=("activities_cancelled",),
    ),
    # A clause before a comma that ends with a noun is no label.
    row("Thursday determined by individual offices, closed on Friday", "closed", jan(23)),
]

CLOCK_THEN_DATE = [
    row("Opening at 10:00 Jan 22", "delayed", jan(22)),
    row("Opening at 10:00 on Jan 22", "delayed", jan(22)),
    row("Early dismissal at 1:00 Jan 22", "early_dismissal", jan(22)),
    row("Early dismissal at 1:00 1/22", "early_dismissal", jan(22)),
    row("Closing at noon Jan 22", "early_dismissal", jan(22)),
]


@pytest.mark.parametrize(
    "case", HEADINGS + SCHOOL_NAMES + SIDE_NOTE_DAYS + FIELDS + DASHED_LABELS + CLOCK_THEN_DATE
)
def test_heading_name_and_side_note(case: Row) -> None:
    result = parse_status(case.text, posted_at=case.posted, tz=TZ)
    assert result.kind == case.kind
    assert result.dates == case.dates
    assert result.confidence == case.confidence
    assert set(case.notes) <= set(result.notes)
    if case.kind == "other":
        assert result.schedule == ()


def test_a_clock_before_a_date_keeps_both() -> None:
    result = parse_status("Opening at 10:00 Jan 22", posted_at=WED, tz=TZ)
    assert (result.opens_at, result.dates) == (time(10), jan(22))
    result = parse_status("Early dismissal at 1:00 Jan 22", posted_at=WED, tz=TZ)
    assert (result.dismissal_time, result.dates) == (time(13), jan(22))


def test_a_heading_never_puts_a_status_on_its_own_day() -> None:
    # "Sunday: Closed Monday" is never a closure on the Sunday.
    for text in ("Sunday: Closed Monday", "Sunday Evening: Closed Monday"):
        result = parse_status(text, posted_at=SUN, tz=TZ)
        assert result.on(date(2026, 1, 25)) is None


@pytest.mark.parametrize("mark", [": ", " - ", "-", " \u2013 ", "\u2014", " -- "])
@pytest.mark.parametrize("label", ["Offices", "District offices", "Albany and Corvallis offices"])
def test_an_office_label_reads_alike_after_a_colon_or_a_dash(label: str, mark: str) -> None:
    closed = parse_status(f"{label}{mark}Closed", posted_at=WED, tz=TZ)
    assert (closed.kind, closed.notes, closed.offices_open) == ("other", ("offices_closed",), False)
    opened = parse_status(f"{label}{mark}Open", posted_at=WED, tz=TZ)
    assert (opened.kind, opened.offices_open, opened.says_open) == ("other", True, False)


def test_a_clause_ending_with_a_noun_before_a_comma_labels_nothing() -> None:
    result = parse_status(
        "Thursday determined by individual offices, closed on Friday", posted_at=WED, tz=TZ
    )
    assert "offices_closed" not in result.notes
    # An opening after a comma takes no label from the clause before it either.
    result = parse_status(
        "Essential personnel Tuesday, normal operations Wednesday", posted_at=WED, tz=TZ
    )
    assert "staff" not in result.notes
    assert not result.offices_open


# "Schools and offices closed" is about the schools and notes the offices: the note says what
# the status says of the offices, as the offices' own status would ("Offices 2 hour delay"
# is no "offices closed"), and a status denied or hedged notes nothing of them.
@pytest.mark.parametrize(
    ("text", "kind", "notes", "offices_open", "says_open"),
    [
        ("Schools and offices - closed", "closed", ("offices_closed",), False, False),
        ("Schools and offices: closed", "closed", ("offices_closed",), False, False),
        ("Schools and offices closed", "closed", ("offices_closed",), False, False),
        ("Schools and offices open", "other", (), True, True),
        ("Schools and offices - open", "other", (), True, True),
        ("Schools and offices 2 hour delay", "delayed", (), False, False),
        ("All schools and offices 2 hour delayed opening", "delayed", (), False, False),
        ("Schools and offices closing early", "early_dismissal", (), False, False),
        ("Schools and offices are not closed", "other", ("negated",), False, False),
        ("Schools and offices are not open", "closed", ("offices_closed",), False, False),
        ("Schools and offices may be closed", "other", ("hedged",), False, False),
        ("Schools and buses closed", "closed", ("transportation",), False, False),
        ("Schools and buses open", "other", ("transportation",), False, True),
        ("Schools and activities open", "other", (), False, True),
    ],
)
def test_a_second_noun_is_noted_as_its_status_says(
    text: str, kind: str, notes: tuple[str, ...], offices_open: bool, says_open: bool
) -> None:
    result = parse_status(text, posted_at=WED, tz=TZ)
    assert (result.kind, result.notes) == (kind, notes)
    assert (result.offices_open, result.says_open) == (offices_open, says_open)
