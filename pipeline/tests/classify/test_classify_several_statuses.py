"""Listings with several statuses read the same through the parser's shortcuts.

A closings page's day slots ("Tuesday Morning: Closed | Tuesday Afternoon:
Closed"), a status beside an "open" for another day, a status called off, and a
field left blank each take a shortcut when nothing in the text could make the
general steps read them otherwise: settling with no scope noun, qualifying word
or condition in the text, a closure's one day bounded by its slot heading, one
mention's dates taken directly, and the days of a text's statuses resolved once
per day named. Each case is read with the shortcuts on and off. The texts are
phrasing patterns, not claims about any real school.
"""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from snowlight.classify import ParsedStatus, parse_status
from snowlight.classify import dayparts as dayparts_module
from snowlight.classify import parse as parse_module
from snowlight.classify.parse import _cached_analysis, _normalized_analysis

TZ = "America/New_York"
POSTED = datetime(2026, 1, 20, 6, 30, tzinfo=ZoneInfo(TZ))  # a Tuesday morning

# Each text, and what it reads as: its kind, its days, its dismissal time and opening time
# (as written, or None) and its confidence.
type Expected = tuple[str, tuple[str, ...], str | None, str | None, float]
CASES: list[tuple[str, Expected]] = [
    (
        "Tuesday Morning: Closed | Tuesday Afternoon: Closed",
        ("closed", ("2026-01-20",), None, None, 0.95),
    ),
    (
        "Tuesday Morning: Closed...... Tuesday Evening: No activities",
        ("closed", ("2026-01-20",), None, None, 0.95),
    ),
    (
        "Tuesday Afternoon: Closed | Tuesday Evening: Closed",
        ("early_dismissal", ("2026-01-20",), None, None, 0.8),
    ),
    (
        "Friday Evening: Closed | Saturday Morning: Closed | Saturday Afternoon: Closed",
        ("closed", ("2026-01-24",), None, None, 0.7),
    ),
    (
        "Wednesday Morning: Remote Learning Day | Wednesday Afternoon: Closed",
        ("remote", ("2026-01-21",), None, None, 0.95),
    ),
    (
        "Tuesday Morning: Closed | Tuesday Afternoon: Opening At Noon",
        ("delayed", ("2026-01-20",), None, "12:00", 0.95),
    ),
    (
        "Tuesday: 2 hour delay | Wednesday: regular schedule",
        ("delayed", ("2026-01-20",), None, None, 0.95),
    ),
    ("Closed today; business as usual tomorrow", ("closed", ("2026-01-20",), None, None, 0.95)),
    ("Closed today, in session tomorrow", ("closed", ("2026-01-20",), None, None, 0.95)),
    ("2 hour delay cancelled. Closed tomorrow", ("closed", ("2026-01-21",), None, None, 0.95)),
    ("Closed tomorrow. Delay: --", ("closed", ("2026-01-21",), None, None, 0.95)),
    ("Delay: --, or closed", ("closed", ("2026-01-20",), None, None, 0.9)),
    (
        "Wednesday Morning: Closed after 11:30 | Wednesday Afternoon: Closed",
        ("early_dismissal", ("2026-01-21",), "11:30", None, 0.95),
    ),
    (
        "Thursday Morning: Closing At 1:00 PM | Thursday Afternoon: Closing At 1:00 PM",
        ("early_dismissal", ("2026-01-22",), "13:00", None, 0.95),
    ),
    # The morning and the afternoon of one day named together are the whole day, beside
    # another day or with the date restating it.
    (
        "Closed this morning and afternoon and tomorrow",
        ("closed", ("2026-01-20", "2026-01-21"), None, None, 0.95),
    ),
    ("Closed this morning and afternoon, Jan. 20", ("closed", ("2026-01-20",), None, None, 0.95)),
    # A part of one day that a run of days reaches: which days it bounds is unclear.
    ("Closed through Friday afternoon", ("other", (), None, None, 0.3)),
    ("Closed thru Thursday PM", ("other", (), None, None, 0.3)),
]


def _read(text: str, *, fast: bool) -> ParsedStatus:
    parse_module._FAST_PATH = fast
    dayparts_module.FAST_PATH = fast
    _cached_analysis.cache_clear()
    _normalized_analysis.cache_clear()
    try:
        return parse_status(text, posted_at=POSTED, tz=TZ)
    finally:
        parse_module._FAST_PATH = True
        dayparts_module.FAST_PATH = True


@pytest.mark.parametrize(("text", "expected"), CASES)
def test_several_statuses(text: str, expected: Expected) -> None:
    kind, days, dismissal, opens, confidence = expected
    result = _read(text, fast=True)
    assert result.kind == kind
    assert result.dates == tuple(date.fromisoformat(day) for day in days)
    assert result.dismissal_time == (None if dismissal is None else time.fromisoformat(dismissal))
    assert result.opens_at == (None if opens is None else time.fromisoformat(opens))
    assert result.confidence == confidence
    assert result == _read(text, fast=False)
