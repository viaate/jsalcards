""" "This week" beside days a status names: which week they are in, not a run of days.

Every text here is a phrasing pattern written for these tests, not a claim
about a real school. Unless a row says otherwise it is posted at 6 a.m. on
Wednesday 21 January 2026 in Chicago, so "today" is Wednesday the 21st,
"Thursday" the 22nd and "Friday" the 23rd.

"Closed this week" alone runs from the posting day to Friday. After named days
("Closed Thursday this week", "Thursday and Friday of this week", "Friday only
this week") or before them with a colon ("Closed this week: Thursday and
Friday") it says which week they are in: this week's, or from a weekend the
coming week's, even a day of it already past ("Monday this week" posted on a
Wednesday is the 19th).
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
SATURDAY = datetime(2026, 1, 24, 10, 0, tzinfo=ZONE)
MONDAY = datetime(2026, 1, 19, 6, 0, tzinfo=ZONE)


def jan(*days: int) -> tuple[date, ...]:
    return tuple(date(2026, 1, day) for day in days)


ROWS = [
    ("Closed Thursday this week", MORNING, "closed", jan(22)),
    ("Closed Thursday and Friday this week", MORNING, "closed", jan(22, 23)),
    ("Closed Thursday and Friday of this week", MORNING, "closed", jan(22, 23)),
    ("Closed Thursday & Friday this week due to ice", MORNING, "closed", jan(22, 23)),
    ("Closed this week: Thursday and Friday", MORNING, "closed", jan(22, 23)),
    ("Closed Friday only this week", MORNING, "closed", jan(23)),
    ("Closed today only this week", MORNING, "closed", jan(21)),
    ("Closed Thursday this week only", MORNING, "closed", jan(22)),
    ("Closed Monday this week", MORNING, "closed", jan(19)),
    ("2 hour delay Thursday and Friday this week", MORNING, "delayed", jan(22, 23)),
    ("eLearning Thursday and Friday this week", MORNING, "remote", jan(22, 23)),
    ("Closed Monday and Tuesday this week", SATURDAY, "closed", jan(26, 27)),
    # "This week" alone is a run from the posting day.
    ("Closed this week", MORNING, "closed", jan(21, 22, 23)),
]


@pytest.mark.parametrize(("text", "posted", "kind", "dates"), ROWS)
def test_this_week_says_which_week_the_days_are_in(
    text: str, posted: datetime, kind: str, dates: tuple[date, ...]
) -> None:
    result = parse_status(text, posted_at=posted, tz=TZ)
    assert result.kind == kind
    assert result.dates == dates


_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")


@settings(max_examples=400, deadline=None)
@given(
    status=st.sampled_from(("Closed", "No school", "2 hour delay", "eLearning", "Remote learning")),
    first=st.integers(min_value=0, max_value=4),
    count=st.integers(min_value=1, max_value=2),
    form=st.sampled_from(("{days} this week", "{days} of this week", "{days} only this week",
                          "this week: {days}")),
    posted=st.sampled_from((MONDAY, MORNING)),
)  # fmt: skip
def test_named_days_this_week_are_exactly_those_days(
    status: str, first: int, count: int, form: str, posted: datetime
) -> None:
    names = _NAMES[first : first + count]
    days = " and ".join(names)
    text = f"{status} {form.format(days=days)}"
    result = parse_status(text, posted_at=posted, tz=TZ)
    monday = date(2026, 1, 19)
    wanted = {date.fromordinal(monday.toordinal() + _NAMES.index(name)) for name in names}
    if result.kind != "other" and result.confidence >= 0.7:
        assert set(result.dates) == wanted, text


# After a mark ("Closed Thursday - this week only", "Closed Thursday; this week", "Closed
# Thursday. This week."), "this week" with nothing but "only" after it in its sentence still
# says which week the days are in: never a run from the named day to Friday.
MARKED = [
    ("Closed Tuesday - this week only", MONDAY, "closed", jan(20)),
    ("Closed Wednesday - this week only", MONDAY, "closed", jan(21)),
    ("Closed Thursday - this week only", MORNING, "closed", jan(22)),
    ("Closed Thursday - This week only.", MORNING, "closed", jan(22)),
    ("2 hour delay Thursday - this week only", MORNING, "delayed", jan(22)),
    ("No school Thursday - this week only", MORNING, "closed", jan(22)),
    ("eLearning Thursday - this week only", MORNING, "remote", jan(22)),
    ("Remote learning Thursday - This week only.", MORNING, "remote", jan(22)),
    ("Late start Thursday - this week only", MORNING, "delayed", jan(22)),
    ("Closed Thursday - this week", MORNING, "closed", jan(22)),
    ("Closed Thursday; this week", MORNING, "closed", jan(22)),
    ("Closed Thursday. This week.", MORNING, "closed", jan(22)),
    ("Closed Thursday - for this week only", MORNING, "closed", jan(22)),
    ("Closed Thursday | just this week", MORNING, "closed", jan(22)),
    ("Closed Thursday and Friday - this week only", MORNING, "closed", jan(22, 23)),
    ("Closed Thursday / this week only", MORNING, "closed", jan(22)),
    ("Closed Thursday/this week only", MORNING, "closed", jan(22)),
    ("Closed Thursday / This Week Only", MORNING, "closed", jan(22)),
    ("2 hour delay Thursday / this week only", MORNING, "delayed", jan(22)),
    ("Remote learning Thursday / this week", MORNING, "remote", jan(22)),
]


@pytest.mark.parametrize(("text", "posted", "kind", "dates"), MARKED)
def test_this_week_after_a_mark_says_which_week_the_days_are_in(
    text: str, posted: datetime, kind: str, dates: tuple[date, ...]
) -> None:
    result = parse_status(text, posted_at=posted, tz=TZ)
    assert result.kind == kind, text
    assert result.dates == dates, text


@settings(max_examples=400, deadline=None)
@given(
    status=st.sampled_from(("Closed", "No school", "2 hour delay", "eLearning", "Late start",
                            "Remote learning")),
    name=st.sampled_from((("Thursday", 22), ("Friday", 23), ("Wednesday", 21))),
    sep=st.sampled_from((" - ", " -- ", "; ", ". ", " | ", ": ", ", ", " (", " ", " / ", "/",
                         " // ", " \\ ")),
    tail=st.sampled_from(("this week", "this week only", "This week only.", "for this week only",
                          "just this week", "this week only)")),
)  # fmt: skip
def test_this_week_after_a_named_day_never_adds_a_day(
    status: str, name: tuple[str, int], sep: str, tail: str
) -> None:
    # Invariant: "<status> <weekday d> <sep> this week [only]" never gives a date other than d
    # at 0.7 or more.
    day, number = name
    text = f"{status} {day}{sep}{tail}"
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    if result.confidence >= 0.7:
        assert set(result.dates) <= {date(2026, 1, number)}, (text, result.dates)
