"""Listings that differ only in a date's month and day share one analysis, and only those.

Every text here is a phrasing pattern written for these tests, not a claim about
a real school; the names are made up.

A plain date's month and day number are analysed as fixed ones of the same width
("Closed Feb. 9" as "Closed Jan. 5"), and the real ones put back before the date
is resolved (see ``parse._day_template``). That holds only while no step of the
analysis compares two dates: a listing with two dates or more ("Closed Jan. 15.
Never mind, open Jan. 21.") is analysed for its own dates alone, so what another
listing left in the caches never changes its reading. A result never depends on
what was parsed before.
"""

import random
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from snowlight.classify import ParsedStatus, parse_status
from snowlight.classify import parse as parse_module
from snowlight.classify.parse import _cached_analysis, _normalized_analysis

TZ = "America/New_York"
ZONE = ZoneInfo(TZ)
POSTED = datetime(2026, 1, 14, 6, 0, tzinfo=ZONE)


def cold(text: str, posted: datetime = POSTED) -> ParsedStatus:
    """``text`` parsed from empty caches, with nothing shared."""
    _cached_analysis.cache_clear()
    _normalized_analysis.cache_clear()
    parse_module._CANONICAL = parse_module._TEMPLATE = False
    try:
        return parse_status(text, posted_at=posted, tz=TZ)
    finally:
        parse_module._CANONICAL = parse_module._TEMPLATE = True


def after(first: str, second: str, posted: datetime = POSTED) -> ParsedStatus:
    """``second`` parsed right after ``first``, from caches ``first`` left."""
    _cached_analysis.cache_clear()
    _normalized_analysis.cache_clear()
    parse_status(first, posted_at=posted, tz=TZ)
    return parse_status(second, posted_at=posted, tz=TZ)


PAIRS = [
    # A change, then the day it changes: "Update: closings" on the delay's own day drops it.
    (
        "2 hour delay Jan. 15. Update: closings Jan. 21.",
        "2 hour delay Jan. 21. Update: closings Jan. 21.",
    ),
    (
        "2 hour delay 1/15. Update: possible closure 1/21.",
        "2 hour delay 1/21. Update: possible closure 1/21.",
    ),
    (
        "2 hour delay Jan. 21 morning. Update: closings Jan. 15.",
        "2 hour delay Jan. 21 morning. Update: closings Jan. 21.",
    ),
    # A closure taken back for its own day.
    ("Closed Jan. 15. Never mind, open Jan. 21.", "Closed Jan. 21. Never mind, open Jan. 21."),
    ("Closed Jan. 15. Correction: open Jan. 21.", "Closed Jan. 21. Correction: open Jan. 21."),
    ("Closed Feb. 15. Correction: open Mar. 21.", "Closed Jan. 21. Correction: open Jan. 21."),
    # Two dates of one status, alike or not.
    ("Closed Jan. 15, Jan. 21", "Closed Jan. 21, Jan. 21"),
    ("Closed Dec. 15 - Dec. 21", "Closed Jan. 21 - Jan. 21"),
]


@pytest.mark.parametrize(("first", "second"), PAIRS)
def test_a_listing_with_two_dates_never_takes_another_listing_s_reading(
    first: str, second: str
) -> None:
    assert after(first, second) == cold(second)
    assert after(second, first) == cold(first)


def test_listings_that_differ_only_in_a_month_share_an_analysis() -> None:
    _cached_analysis.cache_clear()
    _normalized_analysis.cache_clear()
    first = parse_status("Closed Mon, Jan. 5 due to snow", posted_at=POSTED, tz=TZ)
    kept = _normalized_analysis.cache_info().currsize
    second = parse_status("Closed Mon, Feb. 9 due to snow", posted_at=POSTED, tz=TZ)
    third = parse_status("Closed Mon, Dec. 9 due to snow", posted_at=POSTED, tz=TZ)
    assert _normalized_analysis.cache_info().currsize == kept  # (found, not made again)
    assert first.dates == (date(2026, 1, 5),)  # each its own day, put back
    assert second.dates == (date(2026, 2, 9),)
    assert third == cold("Closed Mon, Dec. 9 due to snow")
    # Each date is checked against its weekday as the text gives it: February 9, 2026 is a
    # Monday, and December 9 (posted in January: 2025) a Tuesday.
    assert second.notes == ()
    assert "date_mismatch" in third.notes


MONTHS = ("Jan.", "Feb.", "Mar.", "Apr.", "Jun.", "Sept.", "Oct.", "Dec.", "January", "October",
          "March", "April", "June", "July", "February", "November", "December", "May")  # fmt: skip
FORMS = (
    "Closed {d}", "2 hour delay {d} due to snow", "Closed {d}. No PM activities",
    "Closed tomorrow ({d})", "Closed {d} - Bakutemi campus", "Remote learning {d}; offices open",
    "Closed {d}, {e}", "Closed {d}. Never mind, open {e}.",
    "2 hour delay {d}. Update: closings {e}.",
    # A run after a day another kind's status named, which the run goes on from or leaves
    # unclear by that day (see parse._led_frame), or after a closing time on a day.
    "Remote learning {d}. Closed through Friday.", "NTI day {d}; closed the rest of the week.",
    "Remote learning {d}. No school all week.",
    "Will close at 1 pm on {d} and remain closed through Friday.",
)  # fmt: skip


@settings(max_examples=300, deadline=None)
@given(
    form=st.sampled_from(FORMS),
    months=st.lists(st.sampled_from(MONTHS), min_size=4, max_size=4),
    days=st.lists(st.integers(1, 28), min_size=4, max_size=4),
    numeric=st.booleans(),
    hours=st.integers(0, 24 * 30),
)
def test_what_was_parsed_before_never_changes_a_result(
    form: str,
    months: list[str],
    days: list[int],
    numeric: bool,
    hours: int,
) -> None:
    def date_text(index: int) -> str:
        month = random.Random(months[index]).randint(1, 12)  # noqa: S311 - a month for a test
        return f"{month}/{days[index]}" if numeric else f"{months[index]} {days[index]}"

    posted = POSTED + timedelta(hours=hours)
    first = form.format(d=date_text(0), e=date_text(1))
    second = form.format(d=date_text(2), e=date_text(3))
    assert after(first, second, posted) == cold(second, posted)
