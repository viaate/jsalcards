"""A run with no first day of its own after a status that states its days.

Every text here is a phrasing pattern written for these tests, not a claim
about a real school. Unless a row says otherwise it is posted at 6 a.m. on
Wednesday 21 January 2026 in Chicago, so "today" is Wednesday the 21st,
"tomorrow" Thursday the 22nd and "Friday" the 23rd.

"Closed through Friday" alone runs from the posting day. After a status of its
kind that states its days ("Closed tomorrow. Closed through Friday.", "Closed
Thursday. Closure extended through Friday.", "Closed tomorrow. Closed for the
rest of the week."), the run starts with that status's first day, as the bare
"Closed tomorrow. Through Friday." does: the text says school is open today, so
no run after it claims today. After a status of another kind on a later day
("Wednesday will be an eLearning day; closed the rest of the week" posted on a
Tuesday) the run may start on either day, so its days are unclear. "All week"
and "this week" name the posting week whatever comes before them.
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
    ("Closed tomorrow. Closed through Friday.", MORNING, "closed", jan(22, 23)),
    ("Closed tomorrow; closed through Friday.", MORNING, "closed", jan(22, 23)),
    ("Closed tomorrow. Closure extended through Friday.", MORNING, "closed", jan(22, 23)),
    ("Closed tomorrow. Update: closure extended through Friday.", MORNING, "closed", jan(22, 23)),
    ("Closed tomorrow. Closure continues through Friday.", MORNING, "closed", jan(22, 23)),
    ("Closed tomorrow, and will remain closed through Friday.", MORNING, "closed", jan(22, 23)),
    ("Closed tomorrow. Closure extended until Friday.", MORNING, "closed", jan(22)),
    ("Closed tomorrow. Closed until Monday.", MORNING, "closed", jan(22, 23)),
    ("Closed tomorrow. Closed for the rest of the week.", MORNING, "closed", jan(22, 23)),
    ("Closed Thursday. Closure extended through Friday.", MORNING, "closed", jan(22, 23)),
    ("Closed 1/22. Closure extended through 1/23.", MORNING, "closed", jan(22, 23)),
    (
        "Closed Thursday 1/22. UPDATE 1/21: closure extended through Friday 1/23.",
        MORNING, "closed", jan(22, 23),
    ),
    (
        "Remote learning tomorrow; remote learning continues through Friday.",
        MORNING, "remote", jan(22, 23),
    ),
    ("eLearning Thursday; eLearning through Friday", MORNING, "remote", jan(22, 23)),
    ("Closed Monday. Closure extended through Wednesday.", SATURDAY, "closed", jan(26, 27, 28)),
    ("Closed tomorrow and the rest of the week.", MORNING, "closed", jan(22, 23)),
    ("Closed tomorrow and for the rest of the week.", MORNING, "closed", jan(22, 23)),
    ("Closed tomorrow. The rest of the week.", MORNING, "closed", jan(22, 23)),
    # A weekday that ends the run is the first one on or after the day it goes on from.
    ("Closed tomorrow. Closed until Monday.", MONDAY, "closed", jan(20, 21, 22, 23)),
    ("Closed tomorrow. Closed until Wednesday.", MORNING, "closed", jan(22, 23, 26, 27)),
    # Alone, or after a status of today, a run starts on the posting day; "all week" and
    # "this week" are the posting week.
    ("Closed through Friday.", MORNING, "closed", jan(21, 22, 23)),
    ("Closed tomorrow. Closed all week.", MORNING, "closed", jan(21, 22, 23)),
    ("Closed tomorrow and all week.", MORNING, "closed", jan(21, 22, 23)),
    ("Closed Thursday. Closed this week.", MORNING, "closed", jan(21, 22, 23)),
    ("Closed today. Closed through Friday.", MORNING, "closed", jan(21, 22, 23)),
    ("Closed tomorrow. Through Friday.", MORNING, "closed", jan(22, 23)),
    # The rest of the week after a day of a later week is the rest of that day's week.
    ("Closed Monday Jan 26 and the rest of the week.", MORNING, "closed", jan(26, 27, 28, 29, 30)),
    ("Closed next Monday and the rest of the week.", MORNING, "closed", jan(26, 27, 28, 29, 30)),
    ("Closed 1/27 and for the rest of the week.", MORNING, "closed", jan(27, 28, 29, 30)),
]  # fmt: skip


@pytest.mark.parametrize(("text", "posted", "kind", "dates"), ROWS)
def test_a_run_after_a_dated_status_starts_with_it(
    text: str, posted: datetime, kind: str, dates: tuple[date, ...]
) -> None:
    result = parse_status(text, posted_at=posted, tz=TZ)
    assert result.kind == kind
    assert result.dates == dates
    assert result.confidence >= 0.7


@pytest.mark.parametrize(
    "text",
    [
        "2 hour delay tomorrow. Closed through Friday.",
        "Closed tomorrow. 2 hour delay through Friday.",
        "2 hour delay tomorrow. Delay extended through Friday.",
    ],
)
def test_a_run_of_another_kind_claims_no_day_before_the_status_it_follows(text: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert date(2026, 1, 21) not in result.dates, text


_DAYS = {  # how each first day is named, posted Monday 19 or Wednesday 21 January
    MONDAY: (("tomorrow", 20), ("Wednesday", 21), ("Thursday", 22), ("1/21", 21), ("Jan 22", 22)),
    MORNING: (("tomorrow", 22), ("Thursday", 22), ("1/22", 22), ("Jan 22", 22), ("Friday", 23)),
}


@settings(max_examples=400, deadline=None)
@given(
    posted=st.sampled_from(sorted(_DAYS)),
    pick=st.integers(min_value=0, max_value=4),
    first=st.sampled_from(("Closed", "No school", "Remote learning", "eLearning", "Closing")),
    lead=st.sampled_from(("", "Update: ", "UPDATE - ")),
    again=st.sampled_from(
        (
            "closed", "closure extended", "will remain closed", "we will stay closed",
            "closure continues", "no school", "remote learning continues", "eLearning",
        )
    ),
    end=st.sampled_from(
        (
            "through Friday", "thru Fri", "until Monday", "through 1/23", "through Jan 23",
            "for the rest of the week",
        )
    ),
    mark=st.sampled_from((". ", "; ", ", and ")),
)  # fmt: skip
def test_a_later_run_never_claims_a_day_before_the_status_it_follows(  # noqa: PLR0913, PLR0917
    posted: datetime, pick: int, first: str, lead: str, again: str, end: str, mark: str
) -> None:
    name, day = _DAYS[posted][pick]
    text = f"{first} {name}{mark}{lead}{again} {end}."
    result = parse_status(text, posted_at=posted, tz=TZ)
    if result.kind != "other" and result.confidence >= 0.7:
        assert min(result.dates) >= date(2026, 1, day), text


def test_until_the_posting_weekday_is_unclear() -> None:
    # "Until Monday" posted on a Monday: this Monday leaves no day, the next one is a guess.
    result = parse_status("Closed until Monday.", posted_at=MONDAY, tz=TZ)
    assert result.kind == "other"
    assert result.confidence <= 0.3
    assert "unreadable_date" in result.notes


def test_a_run_from_a_past_date_ends_in_that_date_s_week() -> None:
    # Posted Friday 8 November about a closure from Wednesday 25 September at 4:30 p.m.
    # through "Friday": the closed days are the 26th and 27th.
    posted = datetime(2024, 11, 8, 19, 26, tzinfo=ZONE)
    text = "will close at 4:30 p.m. on Wednesday, September 25, and remain closed through Friday."
    result = parse_status(text, posted_at=posted, tz=TZ)
    assert set(result.dates) <= {date(2024, 9, 26), date(2024, 9, 27)}


# A closure that starts at a time of a day and that a later status continues ("remain closed",
# "stay closed"): school runs that day until the time, as an early dismissal or a full day, and
# the closure's days start on the next school day.
CONTINUED_ROWS = [
    ("Campus will close at 5 p.m. today and remain closed through Friday.", jan(22, 23), None),
    ("District will close at 6 p.m. today and remain closed through Friday.", jan(22, 23), None),
    ("Will close at 5 p.m. Thursday and remain closed Friday.", jan(23), None),
    ("Will close at 2 pm Thursday and remain closed through Friday.", jan(23), jan(22)),
    ("Will close Thursday at 2 pm and remain closed Friday.", jan(23), jan(22)),
    ("Will close at noon today and remain closed through Friday.", jan(22, 23), jan(21)),
    ("Schools will close at 1 pm Thursday and stay closed through Friday.", jan(23), jan(22)),
    ("Campus will close at 5 p.m. today and remain closed until further notice.", jan(22), None),
]  # fmt: skip


@pytest.mark.parametrize(("text", "closed", "early"), CONTINUED_ROWS)
def test_a_closure_continued_after_a_time_starts_the_next_school_day(
    text: str, closed: tuple[date, ...], early: tuple[date, ...] | None
) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    schedule = {entry.kind: entry.dates for entry in result.schedule}
    assert result.confidence >= 0.7, text
    assert schedule.get("closed") == closed, (text, result.schedule)
    assert schedule.get("early_dismissal") == early, (text, result.schedule)


def test_a_closure_continued_with_no_day_of_its_own_is_unclear() -> None:
    # Closed from 5 p.m. today, then for how long nobody says.
    result = parse_status(
        "Campus will close at 5 p.m. today and remain closed.", posted_at=MORNING, tz=TZ
    )
    assert result.kind == "other"
    assert result.confidence <= 0.3


@settings(max_examples=300, deadline=None)
@given(
    clock=st.sampled_from(("noon", "1 pm", "2:30 p.m.", "3 p.m.", "4:30 p.m.", "5 p.m.", "6 pm")),
    day=st.sampled_from((("today", 21), ("Thursday", 22), ("tomorrow", 22), ("1/22", 22))),
    verb=st.sampled_from(("will close", "Campus will close", "Schools close", "District closing")),
    rest=st.sampled_from(("and remain closed through Friday", ", and remain closed Friday",
                          "and will stay closed through Friday", "and remain closed until Monday")),
)  # fmt: skip
def test_a_closing_s_day_is_never_a_day_of_the_closure_it_starts(
    clock: str, day: tuple[str, int], verb: str, rest: str
) -> None:
    # Invariant: "<close at T> <d1> and remain closed through <d2>" never holds d1 closed for
    # sure: school runs that day until T.
    name, number = day
    text = f"{verb} at {clock} {name} {rest}."
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    closed = {d for entry in result.schedule if entry.kind == "closed" for d in entry.dates}
    if result.confidence >= 0.7:
        assert date(2026, 1, number) not in closed, (text, result.schedule)


def test_an_update_s_dated_heading_is_no_day_of_the_status_after_it() -> None:
    text = "Closed Thursday 1/22. Update 1/21: closed Thursday and Friday."
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.dates == jan(22, 23)
    alone = parse_status("Update 1/22: closed", posted_at=MORNING, tz=TZ)
    assert alone.dates == jan(22)


_LATER_WEEK = (  # a day of the week after the posting week (Wednesday 21 January), by its day
    ("next Monday", 26), ("Monday Jan 26", 26), ("1/27", 27), ("Tuesday, January 27", 27),
    ("Thursday 1/29", 29), ("Jan 30", 30),
)  # fmt: skip


@settings(max_examples=300, deadline=None)
@given(
    pick=st.integers(min_value=0, max_value=len(_LATER_WEEK) - 1),
    first=st.sampled_from(("Closed", "No school", "Remote learning", "Closing")),
    joint=st.sampled_from((" and ", ", and ", " & ", ". Closed ", "; closed ")),
    rest=st.sampled_from(
        ("the rest of the week", "for the rest of the week", "all week", "this week")
    ),
)
def test_the_rest_of_a_later_week_stays_in_that_week(
    pick: int, first: str, joint: str, rest: str
) -> None:
    # Never the posting week's days, nor a day past that week's Friday; "all week" or "this
    # week" after such a day names no week for sure.
    name, day = _LATER_WEEK[pick]
    text = f"{first} {name}{joint}{rest}."
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    if rest in {"all week", "this week"}:
        assert result.kind == "other" or result.confidence < 0.7, text
    elif result.kind != "other" and result.confidence >= 0.7:
        assert set(result.dates) <= set(jan(*range(day, 31))), text


@pytest.mark.parametrize(
    "text",
    [
        "Closed Monday Jan 26 and all week.",
        "Closed 1/27. Closed this week.",
        "Closed through April 10. This week, the governor spoke.",
        "Closed today and through April 10. This week, the governor spoke.",
        "Closed Saturday Jan 31 and the rest of the week.",
    ],
)
def test_this_week_or_all_week_after_a_day_of_a_later_week_is_unclear(text: str) -> None:
    # "This week" is the posting week, which a day of a later week is not in; "all week"
    # after one, or the rest of the week after a later weekend day, says no week for sure.
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other", text
    assert result.confidence <= 0.3, text


TUESDAY = datetime(2026, 1, 20, 5, 30, tzinfo=ZONE)


# After a status of another kind on a later day, "all week" and "this week" are still the
# posting week, the other status taking its own day out of it; the rest of the week, a
# "through" or an "until" may start on either day, so the days are unclear.
OTHER_KIND_ROWS = [
    ("Wednesday will be an eLearning day. Schools are closed all week.", jan(20, 22, 23),
     {"remote": jan(21)}),
    ("Schools closed all week; Wednesday will be an eLearning day.", jan(20, 22, 23),
     {"remote": jan(21)}),
    ("Remote learning Thursday. Closed all week.", jan(20, 21, 23), {"remote": jan(22)}),
    ("Remote learning Wednesday. Closed this week.", jan(20, 22, 23), {"remote": jan(21)}),
    ("Virtual Wednesday; closed this week.", jan(20, 22, 23), {"remote": jan(21)}),
    ("AMI day Wednesday, closed the remainder of the week.", None, {}),
    ("NTI day Thursday. Closed the rest of the week.", None, {}),
    ("Remote learning on Wednesday. No school the rest of the week.", None, {}),
    ("2 hour delay Wednesday; closed through Friday.", None, {}),
    ("Closed Wednesday, remote through Friday.", None, {}),
    ("Wednesday is an eLearning day; schools closed until Monday.", None, {}),
    # A status of today, or of the day a run starts on alone, leads the run as before.
    ("Today is an NTI day. No school the rest of the week.", jan(21, 22, 23),
     {"remote": jan(20)}),
    ("Snow day today. NTI day Wednesday. Closed through Friday.", jan(20, 22, 23),
     {"remote": jan(21)}),
]  # fmt: skip


@pytest.mark.parametrize(("text", "closed", "others"), OTHER_KIND_ROWS)
def test_a_run_after_a_day_of_another_kind(
    text: str, closed: tuple[date, ...] | None, others: dict[str, tuple[date, ...]]
) -> None:
    result = parse_status(text, posted_at=TUESDAY, tz=TZ)
    if closed is None:
        # Never a confident status that drops the posting day or claims a day for sure.
        assert result.kind == "other" or result.confidence < 0.7, (text, result)
        return
    schedule: dict[str, tuple[date, ...]] = {entry.kind: entry.dates for entry in result.schedule}
    assert result.confidence >= 0.7, text
    assert schedule.get("closed") == closed, (text, result.schedule)
    for kind, dates in others.items():
        assert schedule.get(kind) == dates, (text, result.schedule)


def test_the_rest_of_the_week_after_a_later_run_s_end_is_unclear() -> None:
    # "Through Monday", then "the rest of the week": which week, the posting week or
    # Monday's, cannot be told.
    for text in (
        "Closed through Monday - remainder of the week",
        "Closed through Monday and the rest of the week",
    ):
        result = parse_status(text, posted_at=MORNING, tz=TZ)
        assert result.kind == "other" or result.confidence < 0.7, text


_OTHER_FIRST = (("NTI day", "remote"), ("2 hour delay", "delayed"), ("Remote learning", "remote"),
                ("Early dismissal at noon", "early_dismissal"))  # fmt: skip


@settings(max_examples=300, deadline=None)
@given(
    first=st.sampled_from(_OTHER_FIRST),
    day=st.sampled_from((("tomorrow", 21), ("Wednesday", 21), ("Thursday", 22), ("1/22", 22),
                         ("Friday", 23))),
    mark=st.sampled_from((". ", "; ", ", ")),
    run=st.sampled_from(("closed all week", "closed this week", "schools are closed all week",
                         "closed the rest of the week", "closed through Friday",
                         "no school the remainder of the week", "closed until Monday")),
)  # fmt: skip
def test_a_run_after_another_kind_s_later_day_never_drops_the_posting_day(
    first: tuple[str, str], day: tuple[str, int], mark: str, run: str
) -> None:
    # Invariant: posted Tuesday morning, a closure run after a status of another kind on a
    # later day either gives no confident status or keeps Tuesday, the posting day, closed.
    name, _number = day
    text = f"{first[0]} {name}{mark}{run}."
    result = parse_status(text, posted_at=TUESDAY, tz=TZ)
    if result.kind != "other" and result.confidence >= 0.7:
        days = {day for entry in result.schedule if entry.kind == "closed" for day in entry.dates}
        assert date(2026, 1, 20) in days, (text, result.schedule)


def test_a_run_that_heads_a_clause_of_its_own_is_no_status_s() -> None:
    # "Through Friday, offices open": the run is the offices', not the closure's.
    for text in (
        "Closed tomorrow. Through Friday, offices open.",
        "Closed tomorrow; through Friday, call the office with questions.",
    ):
        result = parse_status(text, posted_at=MORNING, tz=TZ)
        assert result.dates == jan(22), text
