"""A day of the month written alone: "Closed through the 27th", "Closed on the 22nd".

Every text here is a phrasing pattern written for these tests, not a claim
about a real school. Unless a row says otherwise it is posted at 6 a.m. on
Tuesday 20 January 2026 in New York, so "today" is Tuesday the 20th.

* A day of the month with no month ("the 27th", "the 22", "27th") is the
  first date with that number on or after the posting day, at most 30 days
  on, in the school's time zone. Posted on January 30, "through the 2nd" runs
  to February 2; posted on December 30, "the 2nd" is January 2 of the next
  year.
* "Through the 27th" and "until the 27th" are runs from the first day the
  status can hold, as "through 1/27" and "until 1/27" are: from the posting
  day until noon, the next school day after it. "Until" stops the day before.
* A listing can stay up after its day: a number that fell in the week before
  the posting day is that past day, never a day a month on ("Closed through
  the 19th" seen on the 20th ran out yesterday).
* With no date of that number in reach ("the 31st" posted in April, "the
  30th" in February) the day is impossible: ``other`` at 0.3 with the note
  ``invalid_date``.
* The number must stand clear. A noun after it makes it a count or a rank
  ("the 2nd shift", "the 3rd straight day"), and a grade beside it a grade
  ("grades K through the 3rd"): no day is read from it. An ordinal followed
  by a word the parser cannot place leaves the listing ``unreadable_date``.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from snowlight.classify import parse_status
from snowlight.classify.dates import Calendar, find_date_groups

TZ = "America/New_York"
ZONE = ZoneInfo(TZ)
TUE = datetime(2026, 1, 20, 6, 0, tzinfo=ZONE)
TUE_AFTERNOON = datetime(2026, 1, 20, 14, 0, tzinfo=ZONE)
TUE_OVERNIGHT = datetime(2026, 1, 20, 1, 30, tzinfo=ZONE)
MON_AFTERNOON = datetime(2026, 1, 26, 14, 38, tzinfo=ZONE)
THU_END = datetime(2026, 1, 29, 7, 0, tzinfo=ZONE)
FRI_END = datetime(2026, 1, 30, 6, 0, tzinfo=ZONE)
FRI_LATE_MORNING = datetime(2026, 1, 30, 10, 27, tzinfo=ZONE)
TUE_2025 = datetime(2025, 1, 21, 6, 53, tzinfo=ZONE)
TUE_DECEMBER = datetime(2025, 12, 30, 7, 0, tzinfo=ZONE)
FRI_APRIL = datetime(2026, 4, 10, 6, 0, tzinfo=ZONE)
THU_APRIL_END = datetime(2026, 4, 30, 6, 0, tzinfo=ZONE)
FRI_MAY = datetime(2026, 5, 1, 6, 0, tzinfo=ZONE)
TUE_FEBRUARY = datetime(2026, 2, 10, 6, 0, tzinfo=ZONE)
MON_FEBRUARY_END = datetime(2026, 2, 23, 6, 0, tzinfo=ZONE)


def jan(*days: int) -> tuple[date, ...]:
    return tuple(date(2026, 1, day) for day in days)


def feb(*days: int) -> tuple[date, ...]:
    return tuple(date(2026, 2, day) for day in days)


@dataclass(frozen=True)
class Row:
    text: str
    kind: str
    dates: tuple[date, ...]
    confidence: float
    notes: tuple[str, ...]
    posted: datetime
    delay: int | None
    dismissal: time | None


def row(  # noqa: PLR0913 - one table row
    text: str,
    kind: str,
    dates: tuple[date, ...] = (),
    *,
    confidence: float = 0.95,
    notes: tuple[str, ...] = (),
    posted: datetime = TUE,
    delay: int | None = None,
    dismissal: time | None = None,
) -> object:
    case = Row(text, kind, dates, confidence, notes, posted, delay, dismissal)
    return pytest.param(case, id=f"{text} @ {posted:%Y-%m-%d %H:%M}")


def impossible(text: str, posted: datetime) -> object:
    return row(text, "other", confidence=0.3, notes=("invalid_date",), posted=posted)


def unreadable(text: str) -> object:
    return row(text, "other", confidence=0.3, notes=("unreadable_date",))


# "Through", "until" and "on" the day of the month, and the day alone.
WORDINGS = [
    row("Closed through the 23rd", "closed", jan(20, 21, 22, 23)),
    row("Closed Through the 27th", "closed", jan(20, 21, 22, 23, 26, 27)),
    row("Closed thru the 22nd", "closed", jan(20, 21, 22)),
    row("Closed through 22nd", "closed", jan(20, 21, 22)),
    row("Closed until the 22nd", "closed", jan(20, 21)),
    row("Closed until 22nd", "closed", jan(20, 21)),
    row("Closed till the 23rd", "closed", jan(20, 21, 22)),
    row("Closed on the 22nd", "closed", jan(22)),
    row("Closed on 22nd", "closed", jan(22)),
    row("Closed the 22nd", "closed", jan(22)),
    row("Closed 22nd", "closed", jan(22)),
    row("Closed the 22", "closed", jan(22)),
    row("Closed on the 22", "closed", jan(22)),
    row("Closed on the 22nd.", "closed", jan(22)),
    row("Closed on the 22nd due to snow", "closed", jan(22)),
    row("Closed on the 22nd because of ice", "closed", jan(22)),
    row("School closed on the 21st for students and staff", "closed", jan(21)),
    row("No school the 21st", "closed", jan(21)),
    row("Classes cancelled on the 22nd", "closed", jan(22)),
    row("the 23rd - Remote learning", "remote", jan(23)),
    row("On the 21st: Closed", "closed", jan(21)),
    row("Closed until the 22nd when school reopens", "closed", jan(20, 21)),
    row("Closed the 22nd at all schools", "closed", jan(22)),
    # A day for something else: a reopening, or an event's new date.
    row("Closed. Classes resume on the 22nd", "closed", jan(20), confidence=0.9),
    row("Closed through the 21st, classes resume the 22nd", "closed", jan(20, 21)),
    row(
        "Closed today, concert rescheduled to the 29th",
        "closed",
        jan(20),
        notes=("activities_cancelled",),
    ),
    row("Closed today; semester exams moved to the 27th", "closed", jan(20)),
    # Every kind of status.
    row("Virtual Learning Through the 23rd", "remote", jan(20, 21, 22, 23)),
    row("NTI day the 21st", "remote", jan(21)),
    row("E-learning day on the 22nd", "remote", jan(22)),
    row("2 hour delay on the 21st", "delayed", jan(21), delay=120),
    row("Opening 2 hours late the 22nd", "delayed", jan(22), delay=120),
    row("Early dismissal at 1:00 on the 21st", "early_dismissal", jan(21), dismissal=time(13)),
    row("Early release the 22nd", "early_dismissal", jan(22)),
    # Lists and ranges of days of the month.
    row("Closed the 21st and 22nd", "closed", jan(21, 22)),
    row("Closed the 21st & 22nd", "closed", jan(21, 22)),
    row("Closed the 21st and the 22nd", "closed", jan(21, 22)),
    row("Closed the 21st, 22nd and 23rd", "closed", jan(21, 22, 23)),
    row("Closed the 21st-23rd", "closed", jan(21, 22, 23)),
    row("Closed the 21st through the 23rd", "closed", jan(21, 22, 23)),
    row("Closed the 22nd through 26th", "closed", jan(22, 23, 26)),
    row("Closed Wednesday through the 23rd", "closed", jan(21, 22, 23)),
    row("Closed today through the 22nd", "closed", jan(20, 21, 22)),
    row("Closed the 21st. Remote learning the 22nd", "closed", jan(21)),
    # Beside a weekday or a date that names the same day.
    row("Closed the 22nd (Thursday)", "closed", jan(22)),
    row("Closed Thursday, the 22nd", "closed", jan(22)),
    row("Closed the 22nd, Thursday", "closed", jan(22)),
    row("Jan. 22: Closed the 22nd", "closed", jan(22)),
    row("Closed the 22nd of January", "closed", jan(22)),
    row("Jan. 22: Closed the 22nd and 23rd", "closed", jan(22, 23)),
    row("The 22nd: Closed Jan. 22 and 23", "closed", jan(22, 23)),
    # Disagreeing with a weekday: either could be the day meant, so neither is trusted.
    row("Closed the 22nd (Wednesday)", "other", confidence=0.3, notes=("date_mismatch",)),
    row("Closed on the 23 Thursday", "other", confidence=0.3, notes=("date_mismatch",)),
    # A date heading the status and a different day of the month in it: no day to trust.
    row("Jan. 21: Closed the 22nd and 23rd", "other", confidence=0.3, notes=("date_mismatch",)),
]

# The station template, as such listings write it, posted when they are seen.
TEMPLATES = [
    row("Closed Through the 27th", "closed", jan(27), posted=MON_AFTERNOON),
    row("Virtual Learning Through the 30th", "remote", jan(30), posted=FRI_LATE_MORNING),
    row(
        "Closed Through the 22nd",
        "closed",
        (date(2025, 1, 21), date(2025, 1, 22)),
        posted=TUE_2025,
    ),
    row("Closed Through the 22nd", "closed", jan(21, 22), posted=TUE_AFTERNOON),
]

# Into the next month, and the next year.
ROLLOVER = [
    row("Closed through the 2nd", "closed", (*jan(30), *feb(2)), posted=FRI_END),
    row("Closed until the 3rd", "closed", (*jan(30), *feb(2)), posted=FRI_END),
    row("Closed on the 2nd", "closed", feb(2), posted=FRI_END),
    row("Closed the 30th and 2nd", "closed", (*jan(30), *feb(2)), posted=FRI_END),
    row("Remote learning through the 1st", "remote", jan(29, 30), posted=THU_END),
    row("Closed the 2nd", "closed", (date(2026, 1, 2),), posted=TUE_DECEMBER),
    row(
        "Closed through the 2nd",
        "closed",
        (date(2025, 12, 30), date(2025, 12, 31), date(2026, 1, 1), date(2026, 1, 2)),
        posted=TUE_DECEMBER,
    ),
    row(
        "Closed on the 31st",
        "closed",
        (date(2026, 5, 31),),
        posted=FRI_MAY,
        confidence=0.7,
        notes=("weekend",),
    ),
    row("Closed the 2nd", "closed", (date(2026, 3, 2),), posted=MON_FEBRUARY_END),
    row("Closed the 12th", "closed", feb(12)),
]

# A day that fell in the week before the posting day is that past day.
PAST = [
    row("Closed on the 19th", "closed", jan(19)),
    row("Closed through the 19th", "closed", jan(19)),
    row("Closed the 13th", "closed", jan(13)),
    row("Closed on the 19th", "closed", jan(19), posted=TUE_OVERNIGHT),
]

# No date with that number within reach.
IMPOSSIBLE = [
    impossible("Closed on the 31st", FRI_APRIL),
    impossible("Closed through the 31st", FRI_APRIL),
    impossible("Remote learning the 31st", FRI_APRIL),
    impossible("Closed on the 31st", THU_APRIL_END),
    impossible("Closed the 30th", TUE_FEBRUARY),
    impossible("Closed the 29th", TUE_FEBRUARY),
    impossible("2 hour delay on the 31st", FRI_APRIL),
]

# A number that is no day of the month.
NOT_DAYS = [
    row("Closed for the 3rd straight day", "closed", jan(20), confidence=0.9),
    row("Closed for the 2nd day in a row", "closed", jan(20), confidence=0.9),
    row("Closed, 2nd snow day", "closed", jan(20), confidence=0.9),
    row("Delayed until 2nd period", "delayed", jan(20), confidence=0.9),
    row("Closed for grades K through the 3rd", "other", confidence=0.9, notes=("partial_program",)),
    row("Closed for 1st grade", "other", confidence=0.9, notes=("partial_program",)),
    # Grades right after the status, with no "for": part of the program, as "for grades 1-3" is.
    row("Closed grades 1-3", "other", confidence=0.9, notes=("partial_program",)),
    row("Closed 1st-3rd grades", "other", confidence=0.9, notes=("partial_program",)),
    row("Closed 1st grade", "other", confidence=0.9, notes=("partial_program",)),
    row("Closed for 1st and 2nd grade", "other", confidence=0.9, notes=("partial_program",)),
    row("Closed K-3rd grade", "other", confidence=0.9, notes=("partial_program",)),
    row("No school grades 1-3", "other", confidence=0.9, notes=("partial_program",)),
    row("Closed tomorrow grades 1-3", "other", confidence=0.9, notes=("partial_program",)),
    row("2 hour delay grades 6-12", "other", confidence=0.9, notes=("partial_program",)),
    unreadable("Closed the 21st everyone"),
    unreadable("Closed the 2nd shift"),
    unreadable("1st and 2nd shifts closed"),
    unreadable("Closed the 21st and 22nd sessions"),
    unreadable("Closed on 22"),
    unreadable("Closed January the 22nd"),
]


@pytest.mark.parametrize("case", WORDINGS + TEMPLATES + ROLLOVER + PAST + IMPOSSIBLE + NOT_DAYS)
def test_a_day_of_the_month_alone(case: Row) -> None:
    result = parse_status(case.text, posted_at=case.posted, tz=TZ)
    assert result.kind == case.kind
    assert result.dates == case.dates
    assert result.confidence == case.confidence
    assert set(case.notes) <= set(result.notes)
    assert result.delay_minutes == case.delay
    assert result.dismissal_time == case.dismissal
    if case.kind == "other":
        assert result.schedule == ()
    for note in ("unreadable_date", "invalid_date", "date_mismatch"):
        if note not in case.notes:
            assert note not in result.notes


def test_a_status_of_its_own_on_another_day_of_the_month() -> None:
    result = parse_status("Closed the 21st. Remote learning the 22nd", posted_at=TUE, tz=TZ)
    assert [(entry.kind, entry.dates) for entry in result.schedule] == [
        ("closed", jan(21)),
        ("remote", jan(22)),
    ]


def test_texts_that_differ_only_in_the_day_number_keep_their_own_days() -> None:
    # The parser keeps what it learns of a text's words; the day number is the text's own.
    # (Each with the ending its number takes: "21th" is no day anyone can trust.)
    for day in (21, 22, 23, 26, 27, 28, 29, 30):
        end = {21: "st", 22: "nd", 23: "rd"}.get(day, "th")
        for text in (
            f"Closed Through the {day}{end}",
            f"Closed the {day}",
            f"Closed on {day}{end}",
        ):
            result = parse_status(text, posted_at=TUE, tz=TZ)
            assert result.dates[-1] == date(2026, 1, day), text


def test_the_day_number_is_found_as_a_date_group() -> None:
    (group,) = find_date_groups("closed through the 27th")
    assert group[4] == "range"  # (the open start: "through")
    (atom,) = group[2]
    assert atom[2:7] == ("explicit", None, None, 27, None)  # no month: a day of the month alone


def expected_day(today: date, day: int) -> date | None:
    """The day a day of the month alone stands for, worked out day by day.

    A date with that number in the week before ``today`` (there is at most one), or else
    the first on or after it, at most 30 days on.
    """
    for back in range(1, 8):
        candidate = today - timedelta(days=back)
        if candidate.day == day:
            return candidate
    for ahead in range(31):
        candidate = today + timedelta(days=ahead)
        if candidate.day == day:
            return candidate
    return None


@settings(max_examples=300, deadline=None)
@given(
    st.datetimes(min_value=datetime(2024, 1, 1), max_value=datetime(2028, 12, 31)),
    st.integers(min_value=1, max_value=31),
    st.sampled_from(["the {}{}", "on the {}{}", "{}{}"]),
)
def test_a_day_of_the_month_is_the_nearest_such_date_ahead(
    moment: datetime, day: int, form: str
) -> None:
    posted = moment.replace(tzinfo=ZONE)
    suffix = {1: "st", 2: "nd", 3: "rd", 21: "st", 22: "nd", 23: "rd", 31: "st"}.get(day, "th")
    text = "Closed " + form.format(day, suffix)
    result = parse_status(text, posted_at=posted, tz=TZ)
    today = posted.date()
    wanted = expected_day(today, day)
    assert Calendar(posted, TZ).day_of_month(day) == wanted
    if wanted is None:
        assert result.kind == "other"
        assert "invalid_date" in result.notes
        return
    assert result.dates == (wanted,)
    assert result.kind == "closed"
    assert -7 <= (wanted - today).days <= 30


@settings(max_examples=200, deadline=None)
@given(
    st.datetimes(min_value=datetime(2024, 1, 1), max_value=datetime(2028, 12, 31)),
    st.integers(min_value=1, max_value=31),
)
def test_through_a_day_of_the_month_never_runs_past_it(moment: datetime, day: int) -> None:
    posted = moment.replace(tzinfo=ZONE)
    result = parse_status(f"Closed through the {day}th", posted_at=posted, tz=TZ)
    wanted = Calendar(posted, TZ).day_of_month(day)
    if wanted is None:
        assert result.kind == "other"
        return
    for status in result.schedule:
        assert all(each <= wanted for each in status.dates)
        assert len(status.dates) <= 23  # (at most 31 days: 23 weekdays)
