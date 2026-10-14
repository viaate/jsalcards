"""Table-driven tests of the ways a listing names its day.

Every text here is a phrasing pattern written for these tests, not a claim
about a real school. Unless a row says otherwise, it is posted at 5:30 a.m. on
Tuesday 20 January 2026 in New York, so "today" is Tuesday the 20th and
"tomorrow" Wednesday the 21st.

Three rules are held here:

* A day the parser cannot read ("1-21", "next week", "Wensday", a day number
  that does not stand clear: "the 21st everyone")
  makes the listing ``other`` at 0.3 with the note ``unreadable_date``: the
  status could be for that day, so it is not put on the posting day.
* Two ways of naming one day that disagree give the date's day when one of
  them is a date or a day number ("tomorrow, Jan. 22", "Wednesday the 22nd"),
  at 0.5 with the note ``date_mismatch``. When neither is ("tomorrow
  (Thursday)"), nothing says which is right: the listing is ``other`` at 0.3
  with the note ``date_mismatch``.
* Weekday names listed together are one forward run of days.
"""

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from snowlight.classify import parse_status

TZ = "America/New_York"
ZONE = ZoneInfo(TZ)
TUE = datetime(2026, 1, 20, 5, 30, tzinfo=ZONE)
WED_OVERNIGHT = datetime(2026, 1, 21, 0, 30, tzinfo=ZONE)
WED = datetime(2026, 1, 21, 6, 0, tzinfo=ZONE)
FRI = datetime(2026, 1, 23, 10, 0, tzinfo=ZONE)
EARLY = datetime(2026, 1, 10, 9, 0, tzinfo=ZONE)
SAT = datetime(2026, 1, 24, 10, 0, tzinfo=ZONE)


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
    dates: tuple[date, ...] = (),
    *,
    confidence: float,
    notes: tuple[str, ...] = (),
    posted: datetime = TUE,
) -> object:
    label = text if posted is TUE else f"{text} @ {posted:%a %H:%M}"
    return pytest.param(Row(text, kind, dates, confidence, notes, posted), id=label)


def unreadable(text: str, posted: datetime = TUE) -> object:
    return row(text, "other", confidence=0.3, notes=("unreadable_date",), posted=posted)


def unsettled(text: str, posted: datetime = TUE) -> object:
    return row(text, "other", confidence=0.3, notes=("date_mismatch",), posted=posted)


UNREADABLE = [
    # Day numbers with no month that do not stand clear, or a bare number with no "the".
    unreadable("Closed on 22"),
    unreadable("Closed the 21st everyone"),
    unreadable("Closed the 21st and 22nd sessions"),
    unreadable("2 hour delay the 21st students"),
    unreadable("NTI day on the 22nd snowfall"),
    # Month and day forms that could be something else.
    unreadable("Closed 1-21"),
    unreadable("Closed 01-21"),
    unreadable("Closed 1.21"),
    unreadable("Closed 2026/01/21"),
    unreadable("Early dismissal 1-21"),
    unreadable("Closed. Make up 1-21"),
    unreadable("Closed 21-22 January"),
    # Periods and counts of days.
    unreadable("Closed next week"),
    unreadable("Closed early next week"),
    unreadable("Closed later this week"),
    unreadable("Closed for the week"),
    unreadable("Closed the week of Jan 26"),
    unreadable("Closed Wed next week"),
    unreadable("Closed day after tomorrow"),
    unreadable("Closed the day after tomorrow"),
    unreadable("Closed tomorrow and the next day"),
    unreadable("Closed 3 days"),
    unreadable("Closed for two days"),
    unreadable("Closed the next two days"),
    unreadable("Closed one more day"),
    unreadable("Closed over the weekend"),
    unreadable("Closed Sat"),
    # Named days.
    unreadable("Closed Presidents' Day"),
    unreadable("Closed MLK Day"),
    unreadable("Closed Monday (MLK Day)"),
    # Misspelled or clipped day words.
    unreadable("Closed Wednsday"),
    unreadable("Closed Wensday"),
    unreadable("Closed Thrusday"),
    unreadable("Closed Tusday"),
    unreadable("Closed tomorrrow"),
    unreadable("Closed tmrrow"),
    unreadable("Closed tody"),
    unreadable("Closed 2day"),
    unreadable("Closed Th"),
    unreadable("Closed T/Th"),
    unreadable("Closed M/W/F"),
    unreadable("Closed M-F"),
    unreadable("Closed Wednesday next"),
    # "Next Wednesday" early in the week: this Wednesday or the one after.
    unreadable("Closed next Wednesday"),
    unreadable("Closed next Friday"),
    unreadable("Closed next Wednesday", posted=WED_OVERNIGHT),
    # Weekday names that would have to run backwards.
    unreadable("Closed Wednesday and Tuesday"),
    unreadable("Closed Tuesday and Monday"),
    unreadable("Closed Wednesday; NTI Tuesday"),
    unreadable("NTI Tuesday. Closed Monday"),
    unreadable("Closed Thursday; 2 hour delay Monday"),
]

READ = [
    row("Closed Weds", "closed", jan(21), confidence=0.95),
    row("Delay Weds", "delayed", jan(21), confidence=0.9),
    row("Closed Wed.", "closed", jan(21), confidence=0.95),
    row("Closed WED", "closed", jan(21), confidence=0.95),
    row("Closed Thurs", "closed", jan(22), confidence=0.95),
    row("Closed 21 January", "closed", jan(21), confidence=0.95),
    row("Closed 21st January", "closed", jan(21), confidence=0.95),
    row("Closed the 21st of January", "closed", jan(21), confidence=0.95),
    row("Closed on the 22 January", "closed", jan(22), confidence=0.95),
    # A day of the month alone: the first date with that number from the posting day on.
    row("Closed the 21st", "closed", jan(21), confidence=0.95),
    row("Closed on the 22nd", "closed", jan(22), confidence=0.95),
    row("Closed 22nd", "closed", jan(22), confidence=0.95),
    row("Closed on the 22", "closed", jan(22), confidence=0.95),
    row("Closed the 21st and 22nd", "closed", jan(21, 22), confidence=0.95),
    row("Closed through the 23rd", "closed", jan(20, 21, 22, 23), confidence=0.95),
    row("2 hour delay the 21st", "delayed", jan(21), confidence=0.95),
    row("NTI day on the 22nd", "remote", jan(22), confidence=0.95),
    row("Closed 2morrow", "closed", jan(21), confidence=0.95),
    row("Closed tomm", "closed", jan(21), confidence=0.95),
    row("Closed tmrw", "closed", jan(21), confidence=0.95),
    row("Closed tommorow", "closed", jan(21), confidence=0.95),
    row("Closed 1-21-26", "closed", jan(21), confidence=0.95),
    row("Closed 1.21.26", "closed", jan(21), confidence=0.95),
    row("Wednesday, January 21: Closed", "closed", jan(21), confidence=0.95),
    row("Closed Wednesday the 21st", "closed", jan(21), confidence=0.95),
    row("Closed next Monday", "closed", jan(26), confidence=0.95),
    row("Closed next Tuesday", "closed", jan(27), confidence=0.95),
    row("Closed next Wednesday the 28th", "closed", jan(28), confidence=0.95),
    row("Closed next Wednesday, Jan 28", "closed", jan(28), confidence=0.95),
    row("Closed next Wednesday", "closed", jan(28), confidence=0.95, posted=FRI),
    row("Closed next Wednesday", "closed", jan(28), confidence=0.95, posted=SAT),
    # Hours of a meal service on a closed day, not a month and day.
    row("Closed. Meal pickup 11-1.", "closed", jan(20), confidence=0.9),
    row("Closed. Grab and go meals 10-12.", "closed", jan(20), confidence=0.9),
    row("Closed. Lunch served 11-1", "closed", jan(20), confidence=0.9),
    row("Closed. Meals available 11-1.", "closed", jan(20), confidence=0.9),
    row("Closed; breakfast and lunch pick-up 10-12", "closed", jan(20), confidence=0.9),
    row("Closed tomorrow. Meal distribution 10-12.", "closed", jan(21), confidence=0.95),
    row("Closed. Pick up 11-1", "closed", jan(20), confidence=0.9),
    row("Closed. Grab and go 10-12", "closed", jan(20), confidence=0.9),
    row("Closed. Grab-n-go 10-12", "closed", jan(20), confidence=0.9),
]

# A day word and a date or a day number that disagree ("tomorrow, Jan. 22" posted on a
# Tuesday, Jan. 20): either could be the one meant, so neither can be trusted.
MISMATCHED = [
    unsettled("School closed tomorrow, Jan 22"),
    unsettled("Closed tomorrow Jan 22"),
    unsettled("Closed tomorrow 1/22"),
    unsettled("Closed today - Jan 21"),
    unsettled("Closed today, Jan 21"),
    unsettled("Closed Wed 1/22"),
    unsettled("Closed Wednesday, Jan. 22"),
    unsettled("Closed Jan 21 (Thursday)"),
    unsettled("Closed 1/22 (Wed)"),
    unsettled("Closed Tuesday 21st"),
    unsettled("Closed Wednesday the 22nd"),
    unsettled("Closed tomorrow the 22nd"),
    unsettled("Closed on the 23 Thursday"),
    unsettled("School closed tomorrow. Thursday, January 22"),
    unsettled("Closed Thursday 1/22 and Friday 1/24"),
    unsettled("Closed tomorrow (Thursday, Jan 22)"),
]

# Two day words that disagree with no date to settle them: neither can be trusted.
UNSETTLED = [
    unsettled("Closed tomorrow (Thursday)"),
    unsettled("Closed tomorrow (Friday)"),
    unsettled("Closed today (Wednesday)"),
    unsettled("Closed today, Wednesday"),
    unsettled("Closed tomorrow due to snow (Thursday)"),
    unsettled("Closed tomorrow for snow on Thursday"),
    unsettled("Thursday: closed tomorrow"),
    unsettled("Tomorrow - Thursday: closed"),
    unsettled("Closed today for the storm, Wednesday"),
    unsettled("2 hour delay tomorrow, Thursday"),
    unsettled("Closed today and tomorrow (Wednesday and Thursday)"),
    unsettled("NTI day tomorrow (Monday)"),
    unsettled("Closed tomorrow (Thursday). No school."),
    unsettled("Closed Monday (tomorrow)", WED),
]

AGREEING = [
    row("Closed tomorrow (Wednesday)", "closed", jan(21), confidence=0.95),
    row("Closed today (Tuesday)", "closed", jan(20), confidence=0.95),
    row("School closed tomorrow, Jan 21", "closed", jan(21), confidence=0.95),
    row("Closed tomorrow 1/21", "closed", jan(21), confidence=0.95),
    row("Closed today - Jan 20", "closed", jan(20), confidence=0.95),
    row("Closed Wed 1/21", "closed", jan(21), confidence=0.95),
    row("Closed Jan 21 (Wednesday)", "closed", jan(21), confidence=0.95),
    row("Closed tomorrow due to snow (Wednesday)", "closed", jan(21), confidence=0.95),
    row("Wednesday: closed tomorrow", "closed", jan(21), confidence=0.95),
    row(
        "Closed today and tomorrow (Tuesday and Wednesday)", "closed", jan(20, 21), confidence=0.95
    ),
    # "Also" and "and" add a day rather than restate one.
    row("Closed tomorrow and also Thursday", "closed", jan(21, 22), confidence=0.95),
    row("Closed today and Thursday", "closed", jan(20, 22), confidence=0.95),
    # Posted overnight, "tomorrow" beside the day after the one that has begun means it.
    row(
        "Closed tomorrow (Thursday)",
        "closed",
        jan(22),
        confidence=0.8,
        notes=("overnight",),
        posted=WED_OVERNIGHT,
    ),
]

RUNS = [
    row("Closed Monday and Tuesday", "closed", jan(19, 20), confidence=0.95),
    row("Closed Monday & Tuesday", "closed", jan(19, 20), confidence=0.95),
    row("Closed Monday, Tuesday", "closed", jan(19, 20), confidence=0.95),
    row("Closed Mon/Tue", "closed", jan(19, 20), confidence=0.95),
    # Seen on a Wednesday, Monday and Tuesday just passed: the listing is most likely still up
    # after them, and the run a week on is not what it says.
    unreadable("Closed Monday and Tuesday", posted=WED),
    row("Closed Monday and Tuesday", "closed", jan(26, 27), confidence=0.95, posted=SAT),
    row("Closed Mon-Wed", "closed", jan(19, 20, 21), confidence=0.95),
    row("Closed Monday and Wednesday", "closed", jan(19, 21), confidence=0.95),
    row("Closed Monday, Wednesday and Friday", "closed", jan(19, 21, 23), confidence=0.95),
    row("Closed Thursday and Friday", "closed", jan(22, 23), confidence=0.95),
    row("Closed Friday and Monday", "closed", jan(23, 26), confidence=0.95),
    unreadable("Closed Wednesday and Thursday", posted=FRI),
    row("Closed Weds & Thurs", "closed", jan(21, 22), confidence=0.95),
    row("Closed Wed./Thu.", "closed", jan(21, 22), confidence=0.95),
    row("Closed Tue, Wed & Thu", "closed", jan(20, 21, 22), confidence=0.95),
    row("Closed Wednesday through Monday", "closed", jan(21, 22, 23, 26), confidence=0.95),
    row("Closed Monday; NTI Tuesday", "remote", jan(20), confidence=0.95),
    row("Closed Friday; 2 hour delay Monday", "closed", jan(23), confidence=0.95),
]

EVENINGS = [
    row("Closed tonight", "other", confidence=0.9, notes=("activities_cancelled",)),
    row("Closed tomorrow night", "other", confidence=0.9, notes=("activities_cancelled",)),
    row("Closed Tuesday evening", "other", confidence=0.9, notes=("activities_cancelled",)),
    row("Closed this evening", "other", confidence=0.9, notes=("activities_cancelled",)),
    row("Closed tonight and tomorrow", "closed", jan(21), confidence=0.95),
    row("Closed today and tonight", "closed", jan(20), confidence=0.95),
]

# A day after a cause ("due to snow tomorrow") is the status's day when the status
# names none, but only as a judgment call; a possessive dates the cause instead.
CAUSES = [
    row("No school due to snow tomorrow", "closed", jan(21), confidence=0.8),
    row("2 hour delay due to fog Thursday", "delayed", jan(22), confidence=0.8),
    row("Closed due to snow Wednesday", "closed", jan(21), confidence=0.8),
    row("Closed because of ice Thursday", "closed", jan(22), confidence=0.8),
    row("Closed due to inclement weather Wednesday", "closed", jan(21), confidence=0.8),
    row("Closed today due to snow Wednesday", "closed", jan(20), confidence=0.8),
    row("Closed Wednesday because of the forecast for Thursday", "closed", jan(21), confidence=0.8),
    row("Closed due to Monday's storm", "closed", jan(20), confidence=0.9),
    row("Closed Wednesday due to Tuesday's storm", "closed", jan(21), confidence=0.95),
    row("Closed tomorrow due to snow", "closed", jan(21), confidence=0.95),
    row("Closed due to inclement weather", "closed", jan(20), confidence=0.9),
    row("Inclement weather", "other", confidence=0.3, notes=("ambiguous",)),
    row("Closed due to possible flooding tomorrow", "other", confidence=0.3, notes=("hedged",)),
]

# A run of weekday names ending on a date runs up to that date; one date after the
# run dates only its last name.
DATED_RUNS = [
    row(
        "Closed Wednesday through January 28",
        "closed",
        jan(21, 22, 23, 26, 27, 28),
        confidence=0.95,
    ),
    row("Closed Wednesday through 1/28", "closed", jan(21, 22, 23, 26, 27, 28), confidence=0.95),
    row("Closed Wednesday until Jan 28", "closed", jan(21, 22, 23, 26, 27), confidence=0.95),
    row(
        "Closed Wednesday through Wednesday, January 28",
        "closed",
        jan(21, 22, 23, 26, 27, 28),
        confidence=0.95,
    ),
    row(
        "Closed Monday through Friday, January 30",
        "closed",
        jan(26, 27, 28, 29, 30),
        confidence=0.95,
    ),
    row(
        "Closed Monday through Friday, January 30",
        "closed",
        jan(26, 27, 28, 29, 30),
        confidence=0.95,
        posted=EARLY,
    ),
    row("Closed Wednesday through Friday, Jan. 23", "closed", jan(21, 22, 23), confidence=0.95),
    row("Closed Wednesday and Thursday, January 22", "closed", jan(21, 22), confidence=0.95),
    row(
        "Closed Wednesday and Thursday, January 22",
        "closed",
        jan(21, 22),
        confidence=0.95,
        posted=EARLY,
    ),
    row("Closed Wed, Thu, Fri, Jan 23", "closed", jan(21, 22, 23), confidence=0.95),
    row(
        "Closed Wednesday, Thursday and Friday, January 23",
        "closed",
        jan(21, 22, 23),
        confidence=0.95,
    ),
    row("Closed Wednesday through tomorrow", "closed", jan(21), confidence=0.95),
    row("Closed Friday through Jan 28", "closed", jan(23, 26, 27, 28), confidence=0.95),
    unsettled("Closed Wednesday and Thursday, January 23"),
    row("Jan 21 and 22: Remote learning", "remote", jan(21, 22), confidence=0.95),
    row("Jan 21-23: Early dismissal", "early_dismissal", jan(21, 22, 23), confidence=0.95),
    row("Closed 1/21-22: all schools", "closed", jan(21, 22), confidence=0.95),
    row("Closed Jan 21 until 23", "closed", jan(21, 22), confidence=0.95),
    row("Closed Jan 21, 22", "closed", jan(21, 22), confidence=0.95),
    row("Closed Jan 21, 19", "closed", jan(21), confidence=0.95),
    row("Closed Jan 21 (10)", "closed", jan(21), confidence=0.95),
    row("Early release Friday, Jan. 23 (15)", "early_dismissal", jan(23), confidence=0.95),
]

# Days that run backward, or a weekday counted back from now: which days are meant is unclear.
BACKWARD = [
    unreadable("Closed today through Jan 19"),
    unreadable("Closed Jan 23 through Jan 21"),
    unreadable("Closed Jan 21-19"),
    unreadable("Closed tomorrow and Jan 19"),
    unreadable("Closed Jan 22 and tomorrow"),
    unreadable("Closed Friday and Jan 22"),
    unreadable("Closed Thursday and tomorrow"),
    unreadable("Closed tomorrow until Wednesday"),
    unreadable("Closed tomorrow and Thursday, Jan 22", SAT),
    unreadable("Closed last Monday"),
    unreadable("Closed this past Monday"),
    unreadable("Closed previous Friday"),
    # A day number heading the status reads as a day of the month.
    row("23rd, delay", "delayed", jan(23), confidence=0.9),
    row("the 23rd - Remote learning", "remote", jan(23), confidence=0.95),
]

# A part of the day goes with its date wherever the date sits.
DAY_PARTS = [
    row("2 hr delay Wednesday morning", "delayed", jan(21), confidence=0.95),
    row("Wednesday morning - 2 hr delay", "delayed", jan(21), confidence=0.95),
    row("2 hr delay, Wednesday AM", "delayed", jan(21), confidence=0.95),
    # Closed for the morning only, with no opening time: nothing anyone can act on.
    row("Schools closed Wednesday morning", "other", confidence=0.3, notes=("ambiguous",)),
    row("Wednesday AM: Schools closed", "other", confidence=0.3, notes=("ambiguous",)),
    # A closings page's morning slot for the day heads the day's status: the whole day.
    row("Wednesday morning: Schools closed", "closed", jan(21), confidence=0.95),
    row("Wednesday afternoon: Schools closed", "early_dismissal", jan(21), confidence=0.8),
    row("Wednesday afternoon - early dismissal", "early_dismissal", jan(21), confidence=0.95),
    row(
        "Wednesday AM kindergarten: no school",
        "other",
        confidence=0.9,
        notes=("partial_program",),
    ),
]

# How the calendar reads "next", a day named several ways, and runs across a text.
CALENDAR = [
    row("Closed next Monday and Tuesday", "closed", jan(26, 27), confidence=0.95),
    row(
        "Closed next Monday and Tuesday",
        "closed",
        jan(26, 27),
        confidence=0.95,
        posted=WED_OVERNIGHT,
    ),
    row("Closed tonight, Wednesday", "closed", jan(21), confidence=0.95),
    unsettled("Closed Wednesday the 31st"),
    row("Closed next Wednesday (Jan 28)", "closed", jan(28), confidence=0.95),
    row("Closed next Wednesday, Jan 21", "closed", jan(21), confidence=0.95),
    row("Closed tomorrow, Wednesday, Jan 21", "closed", jan(21), confidence=0.95),
    row(
        "Closed tomorrow, Wednesday, Jan 21",
        "closed",
        jan(21),
        confidence=0.8,
        notes=("overnight",),
        posted=WED_OVERNIGHT,
    ),
    unsettled("Closed tomorrow, Thursday, Jan 22"),
    row("Closed next Wednesday and Thursday, Jan 28-29", "closed", jan(28, 29), confidence=0.95),
    unreadable("Closed next Wednesday and Thursday"),
    unreadable("Closed Monday through next Wednesday"),
    row(
        "Closed Monday; NTI Tuesday and Wednesday, Jan 20-21",
        "remote",
        jan(20, 21),
        confidence=0.95,
    ),
    row("Closed rest of the week and Monday", "closed", jan(20, 21, 22, 23, 26), confidence=0.95),
]


@pytest.mark.parametrize(
    "case",
    UNREADABLE
    + READ
    + MISMATCHED
    + UNSETTLED
    + AGREEING
    + RUNS
    + EVENINGS
    + CAUSES
    + DATED_RUNS
    + BACKWARD
    + DAY_PARTS
    + CALENDAR,
)
def test_day_forms(case: Row) -> None:
    result = parse_status(case.text, posted_at=case.posted, tz=TZ)
    assert result.kind == case.kind
    assert result.dates == case.dates
    assert result.confidence == case.confidence
    assert set(case.notes) <= set(result.notes)
    if case.kind == "other":
        assert result.schedule == ()
    if "date_mismatch" not in case.notes:
        assert "date_mismatch" not in result.notes
    if "unreadable_date" not in case.notes:
        assert "unreadable_date" not in result.notes


def test_a_weekday_run_is_contiguous_and_in_text_order() -> None:
    for posted in (TUE, FRI, SAT):
        result = parse_status("Closed Monday and Tuesday", posted_at=posted, tz=TZ)
        first, second = result.dates
        assert (first.weekday(), second.weekday()) == (0, 1)
        assert (second - first).days == 1
    # Seen on a Wednesday, the run that just passed or the one a week on: neither is stated.
    assert parse_status("Closed Monday and Tuesday", posted_at=WED, tz=TZ).kind == "other"


def test_an_unreadable_day_hides_every_status() -> None:
    result = parse_status("Closed today. 2 hour delay next week", posted_at=TUE, tz=TZ)
    assert result.kind == "other"
    assert result.schedule == ()
    assert result.confidence == 0.3
    assert "unreadable_date" in result.notes


@pytest.mark.parametrize(
    ("text", "kind", "opens"),
    [
        ("Closed until noon", "delayed", time(12)),
        ("Closed until 10", "delayed", time(10)),
        ("Closed until 10 am", "delayed", time(10)),
        ("School will not open until 10:30", "delayed", time(10, 30)),
    ],
)
def test_closed_until_a_time_is_a_late_start(text: str, kind: str, opens: time) -> None:
    result = parse_status(text, posted_at=TUE, tz=TZ)
    assert result.kind == kind
    assert result.opens_at == opens
    assert result.dates == jan(20)


@pytest.mark.parametrize(
    "text",
    [
        "Closed for the remainder of the day",
        "Closing for the rest of the day",
        "Students dismissed for the rest of the day",
    ],
)
def test_closed_for_the_rest_of_the_day_is_an_early_dismissal(text: str) -> None:
    result = parse_status(text, posted_at=TUE, tz=TZ)
    assert result.kind == "early_dismissal"
    assert result.dates == jan(20)


@pytest.mark.parametrize(
    "text",
    [
        "No school (AM kindergarten only)",
        "No school - AM kindergarten only",
        "AM kindergarten: no school",
        "AM Kindergarten - No School",
        "Closed - preschool only",
        "2 hour delay (elementary only)",
        "2 hour delay - high school only",
        "Closed today, 3rd grade only",
        "Closed tomorrow, 3rd graders only",
        "No school for 3rd grade",
        "No school for third grade",
        "3rd grade: no school",
        "Closed today for kindergarten",
        "Closed today for 2nd grade",
        "Closed today. Kindergarten only.",
        "Closed today; kindergarten only",
        "2 hour delay tomorrow for high school",
    ],
)
def test_a_label_or_restriction_narrows_the_status(text: str) -> None:
    result = parse_status(text, posted_at=TUE, tz=TZ)
    assert result.kind == "other"
    assert "partial_program" in result.notes


def test_a_bracketed_noun_phrase_settles_a_bare_cancelled() -> None:
    result = parse_status("Cancelled (all classes)", posted_at=TUE, tz=TZ)
    assert result.kind == "closed"
    assert result.dates == jan(20)


def test_an_ordinary_dismissal_time_is_not_an_early_dismissal() -> None:
    result = parse_status("Dismissal at 3:00", posted_at=TUE, tz=TZ)
    assert result.kind == "other"
    assert result.confidence == 0.3
    assert "ambiguous" in result.notes


@pytest.mark.parametrize(
    "text",
    [
        "Closed due to inclement weather",
        "Closed because of inclement weather",
        "No school for inclement weather",
    ],
)
def test_inclement_weather_as_a_cause_is_not_ambiguous(text: str) -> None:
    result = parse_status(text, posted_at=TUE, tz=TZ)
    assert result.kind == "closed"
    assert "ambiguous" not in result.notes
    assert result.weather_terms == ("inclement weather",)


def test_closing_at_a_time_on_a_named_day_is_an_early_dismissal() -> None:
    result = parse_status("Closing Wed at noon", posted_at=TUE, tz=TZ)
    assert result.kind == "early_dismissal"
    assert result.dates == jan(21)
    assert result.dismissal_time == time(12)


def test_a_noun_after_the_date_still_scopes_the_status() -> None:
    result = parse_status("Closed tomorrow for staff", posted_at=TUE, tz=TZ)
    assert result.kind == "other"
    assert "staff" in result.notes
    students = parse_status("Closed tomorrow for students", posted_at=TUE, tz=TZ)
    assert (students.kind, students.dates) == ("closed", jan(21))


def test_an_open_until_that_has_passed_keeps_only_its_last_day() -> None:
    result = parse_status("Closed until Jan 20", posted_at=TUE, tz=TZ)
    assert (result.kind, result.dates) == ("closed", jan(19))
