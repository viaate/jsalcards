"""A correction that moves a status's day or time: never the old one for sure.

Every text here is a phrasing pattern written for these tests, not a claim
about a real school. Unless a row says otherwise it is posted at 6 a.m. on
Wednesday 21 January 2026 in Chicago, so "today" is Wednesday the 21st,
"tomorrow" Thursday the 22nd and "Friday" the 23rd.

A later sentence that a correction's words lead and that names another day
("Closed Thursday. Correction: Friday.", "... Correction: closed Friday.", "...
date changed to Friday", "... Update: closure moved to Friday", "... Update:
closed Friday instead"), a move from one day to another ("Closure moved from
Thursday to Friday") or a bare new time ("Early dismissal at 1:00. Correction:
12:30.") may replace the old day or time or join it: when the status still
holds the old one, no status is sure (``other``, 0.3, ``ambiguous``). A
correction that denies the old day ("Correction: closed Friday, not
Thursday") leaves the new one.
"""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from snowlight.classify import parse_status

TZ = "America/Chicago"
ZONE = ZoneInfo(TZ)
MORNING = datetime(2026, 1, 21, 6, 0, tzinfo=ZONE)  # Wednesday

MOVED = [
    "Closed Thursday. Correction: Friday.", "Closed Thursday. CORRECTION: Friday",
    "Closed Thursday. Correction - should be Friday.", "Closed Thursday; date corrected to Friday",
    "Closed Thursday; date changed to Friday", "Closed Thursday. Date change: Friday.",
    "Closed Thursday. Update: make that Friday.", "Closed Thursday. Correction: closed Friday.",
    "Closed Thursday. Update: closed Friday instead.", "Closure moved from Thursday to Friday",
    "Closed Thursday. Update: closure moved to Friday.",
    "Closed Thursday. The closure has been moved to Friday.", "Closed 1/22. Correction: 1/23.",
    "Closed Jan 22. Correction: Jan 23.", "Closed tomorrow. Correction: today.",
    "Closed today. Correction: tomorrow.", "Closed today. Correction: closed tomorrow.",
    "2 hour delay Thursday. Correction: Friday.", "Early dismissal Thursday. Correction: Friday.",
    "eLearning Thursday. Correction: eLearning Friday.",
    "Early dismissal at 1:00. Correction: 12:30.",
    "Early dismissal at 1:00. Update: dismissal moved to 12:30.",
]  # fmt: skip


@pytest.mark.parametrize("text", MOVED)
def test_a_correction_that_moves_the_day_or_time_leaves_no_status(text: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other"
    assert result.confidence <= 0.3


STANDS = [
    ("Closed Thursday. Correction: closed Friday, not Thursday.", "closed", (date(2026, 1, 23),)),
    ("Correction: closed Friday, not Thursday", "closed", (date(2026, 1, 23),)),
    ("Closure moved to Friday", "closed", (date(2026, 1, 23),)),
    ("2 hour delay tomorrow. Correction: 3 hour delay.", "delayed", (date(2026, 1, 22),)),
    ("Opening at 10:00. Correction: opening at 11:00.", "delayed", (date(2026, 1, 21),)),
]


@pytest.mark.parametrize(("text", "kind", "dates"), STANDS)
def test_a_correction_that_names_the_new_day_alone_stands(
    text: str, kind: str, dates: tuple[date, ...]
) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == kind
    assert result.dates == dates


def test_a_corrected_time_is_never_the_old_one() -> None:
    result = parse_status("Early dismissal at 1:00; now 12:30", posted_at=MORNING, tz=TZ)
    assert result.dismissal_time in (None, time(12, 30))


_DAYS = (("Thursday", 22), ("Friday", 23), ("tomorrow", 22), ("Jan 22", 22), ("1/23", 23))


@settings(max_examples=400, deadline=None)
@given(
    status=st.sampled_from(("Closed", "2 hour delay", "eLearning", "Early dismissal", "No school")),
    old=st.sampled_from(_DAYS),
    new=st.sampled_from(_DAYS),
    lead=st.sampled_from(
        ("Correction: ", "CORRECTION - ", "Correction: closed ", "Update: make that ",
         "Date change: ", "Correction - should be ", "Update: moved to ")
    ),
)  # fmt: skip
def test_a_corrected_day_is_never_the_old_one_for_sure(
    status: str, old: tuple[str, int], new: tuple[str, int], lead: str
) -> None:
    text = f"{status} {old[0]}. {lead}{new[0]}."
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    if old[1] != new[1] and result.kind != "other" and result.confidence >= 0.7:
        assert date(2026, 1, old[1]) not in result.dates, text


# A correction in brackets, after a dash or a comma, or led by now, revised, revision, erratum,
# change, updated to, shifted to, postponed to or now on, moves the day as a sentence led by
# "Correction:" does.
MOVED_TOO = [
    "Closed Thursday (correction: Friday)", "Closed Thursday [correction: Friday]",
    "Closed Thursday - correction: Friday", "2 hour delay Thursday (correction: Friday)",
    "Closed Thursday (CORRECTION - Friday)", "Closed Thursday, correction, Friday",
    "Closed Thursday - now Friday", "Closed Thursday. Now Friday.",
    "Closed Thursday. Now closed Friday.", "Closed Thursday. Revised: Friday.",
    "Closed Thursday. Erratum: Friday.", "Closed Thursday. *Updated to Friday*",
    "Closed Thursday. Revision: closed Friday.", "Closed Thursday. Change: closed Friday.",
    "Closed Thursday. Closure shifted to Friday.", "Closed Thursday. Closure now on Friday.",
    "Closed Thursday. Postponed to Friday.", "Closed Thursday. Closure postponed to Friday.",
    "Early dismissal Thursday. Now Friday.", "Early dismissal at 1:00 (correction: 12:30)",
    "Early dismissal at 1:00. Revised to 12:30.", "2 hour delay, opening at 10. Revised to 11:00.",
    "Closed Thursday. Correct date: Friday.", "Closed Thursday. Correct date is Friday.",
    "Closed Thursday. Change of date: Friday.", "Closed Thursday. Updated date: Friday.",
]  # fmt: skip
# A day added, not moved, keeps both days.
ADDED = [
    ("Closed Thursday. Now closed Friday too.", (22, 23)),
    ("Closed Thursday. Now closed Friday as well.", (22, 23)),
    ("Closed Thursday, Friday.", (22, 23)),
]


@pytest.mark.parametrize("text", MOVED_TOO)
def test_a_correction_in_any_form_leaves_no_status(text: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other", text
    assert result.confidence <= 0.3, text


@pytest.mark.parametrize(("text", "days"), ADDED)
def test_a_day_added_is_no_correction(text: str, days: tuple[int, ...]) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "closed", text
    assert result.dates == tuple(date(2026, 1, day) for day in days), text


@settings(max_examples=400, deadline=None)
@given(
    status=st.sampled_from(("Closed", "2 hour delay", "eLearning", "Early dismissal", "No school")),
    old=st.sampled_from(_DAYS),
    new=st.sampled_from(_DAYS),
    form=st.sampled_from(
        ("{s} {o} (correction: {n})", "{s} {o} - correction: {n}", "{s} {o}. Now {n}.",
         "{s} {o} - now {n}", "{s} {o}. Revised: {n}.", "{s} {o}. Erratum: {n}.",
         "{s} {o}, correction, {n}", "{s} {o}. Postponed to {n}.", "{s} {o}. Now on {n}.",
         "{s} {o}. Correct date: {n}.", "{s} {o}. Change of date: {n}.",
         "{s} {o}. Updated date: {n}.", "{s} {o}. Correct date is {n}.")
    ),
)  # fmt: skip
def test_a_corrected_day_in_any_form_is_never_the_old_one_for_sure(
    status: str, old: tuple[str, int], new: tuple[str, int], form: str
) -> None:
    text = form.format(s=status, o=old[0], n=new[0])
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    if old[1] != new[1] and result.kind != "other" and result.confidence >= 0.7:
        assert date(2026, 1, old[1]) not in result.dates, text


@settings(max_examples=300, deadline=None)
@given(
    status=st.sampled_from(
        ("Early dismissal at {o}", "Dismissing early at {o}", "Early release at {o}",
         "2 hour delay, opening at {o}", "Opening at {o}")
    ),
    old=st.sampled_from(
        (("1:00", time(13, 0)), ("11:30", time(11, 30)), ("12:15 pm", time(12, 15)))
    ),
    new=st.sampled_from(("12:30", "2:00 pm", "10:45")),
    form=st.sampled_from(
        ("{s}. Revised to {n}.", "{s}. Correction: {n}.", "{s} (correction: {n})",
         "{s}. Updated to {n}.", "{s}. Changed to {n}.", "{s}; now {n}", "{s}. Change: {n}.")
    ),
)  # fmt: skip
def test_a_corrected_time_in_any_form_is_never_the_old_one_for_sure(
    status: str, old: tuple[str, time], new: str, form: str
) -> None:
    text = form.format(s=status.format(o=old[0]), n=new)
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    if result.confidence >= 0.7:
        assert old[1] not in (result.dismissal_time, result.opens_at), text
