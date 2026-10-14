""" "Only" beside a status's day: "Closed today only", "only on Thursday", "only closed today".

Every text here is a phrasing pattern written for these tests, not a claim about
a real school. Unless a row says otherwise it is posted at 6 a.m. on Wednesday
21 January 2026 in Chicago, so "today" is Wednesday the 21st, "tomorrow"
Thursday the 22nd and "Friday" the 23rd.

"Only" right after a day ("today only"), right before it ("only today", "only on
Thursday") or before the status ("only closed today") says the status is for that
day and no other. An update or a correction that says so ("Closed today and
tomorrow. Update: closed today only.") replaces every status of its kind before
it: the days it leaves out are left with a status the text marks as replaced,
so they get none, and the day it keeps is a judgment call, at 0.8, noted
``superseded``, as "Update: closed today; tomorrow regular schedule" is. With no
such mark, another day of the same kind of status contradicts the "only"
("Closed today only, Thursday and Friday", "Closed Wednesday only; Thursday and
Friday", "Closed Monday. Closed today only."), and so does a day "only" restricts
that no status takes ("Closed Thursday and Friday. Correction - only Thursday"):
``other`` at 0.3, noted ``ambiguous``. "Only" before a list restricts the status
to the whole list ("Closed only today, Thursday and Friday"), "only if" opens a
condition and "not only" adds days; a later update of the same kind replaces the
"only" in turn.
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
WED = datetime(2026, 1, 21, 6, 0, tzinfo=ZONE)
WED_EVENING = datetime(2026, 1, 21, 20, 0, tzinfo=ZONE)


def jan(*days: int) -> tuple[date, ...]:
    return tuple(date(2026, 1, day) for day in days)


@dataclass(frozen=True)
class Row:
    text: str
    kind: str
    dates: tuple[date, ...]
    confidence: float
    note: str | None = None


def replaced(text: str, kind: str = "closed", dates: tuple[date, ...] = jan(21)) -> Row:
    """An update restricted to one day: the other days are replaced."""
    return Row(text, kind, dates, 0.8, "superseded")


def contradicted(text: str) -> Row:
    """An "only" that another day of the status contradicts."""
    return Row(text, "other", (), 0.3, "ambiguous")


ROWS = [
    # An update or a correction restricts the status to its day.
    replaced("Closed today, Thursday and Friday. Correction: closed today only."),
    replaced("Closed today, Thursday and Friday. Update: closed today only."),
    replaced("Closed today and tomorrow. Correction: closed today only."),
    replaced("Closed today and tomorrow. Update: closed today only."),
    replaced("Closed today and tomorrow. UPDATE: only closed today"),
    replaced("Closed today and tomorrow. Correction: closed only today"),
    replaced("Closed Wednesday, Thursday and Friday. Correction: closed today only."),
    replaced("Closed today, tomorrow and Friday. Correction: closed today only."),
    replaced("No school today and tomorrow. Update: no school today only"),
    replaced("NTI today and tomorrow. Update: NTI today only", "remote"),
    replaced("2 hour delay today and tomorrow. Update: 2 hour delay today only", "delayed"),
    replaced("Closed today and tomorrow. Update: closing just for today"),
    replaced("Closed today and tomorrow. Update: closed just for today"),
    # With no such mark, another day of the status contradicts the "only".
    contradicted("Closed today only, Thursday and Friday"),
    contradicted("Closed today only, tomorrow and Friday"),
    contradicted("Closed today only; tomorrow and Friday"),
    contradicted("Closed today only. Thursday and Friday"),
    contradicted("Closed Wednesday only, Thursday and Friday"),
    contradicted("No school today only, Thursday and Friday"),
    contradicted("2 hour delay today only, Thursday and Friday"),
    contradicted("Closed Monday. Closed today only."),
    contradicted("Closed today only. Closed Friday too."),
    contradicted("Closed Thursday and Friday. Correction - only Thursday"),
    contradicted("Closed today and tomorrow. Update: just for today"),
    # "Only" that restricts nothing else stands.
    Row("Closed today only", "closed", jan(21), 0.95),
    Row("Closed only today", "closed", jan(21), 0.95),
    Row("Closed just for today", "closed", jan(21), 0.95),
    Row("Only closed today", "closed", jan(21), 0.95),
    Row("Today only: closed", "closed", jan(21), 0.95),
    Row("No school today only", "closed", jan(21), 0.95),
    Row("Closed Thursday only", "closed", jan(22), 0.95),
    Row("Closed today only (Wednesday)", "closed", jan(21), 0.95),
    Row("Closed today only; tomorrow TBD", "closed", jan(21), 0.95),
    Row("Closed today only for students", "closed", jan(21), 0.95),
    Row("Closed today only, offices open", "closed", jan(21), 0.95),
    Row("Closed today, tomorrow and Friday only", "closed", jan(21, 22, 23), 0.95),
    Row("Closed only today, Thursday and Friday", "closed", jan(21, 22, 23), 0.95),
    Row("Closed not only today but also tomorrow", "closed", jan(21, 22), 0.95),
    Row("Closed today only if roads are icy", "other", (), 0.3, "hedged"),
    # A status of another kind on another day contradicts nothing.
    Row("Closed today only. 2 hour delay tomorrow.", "closed", jan(21), 0.95),
    # A later update replaces the "only".
    Row("Closed today only. Update: closed tomorrow too", "closed", jan(21, 22), 0.95),
]


@pytest.mark.parametrize("case", ROWS, ids=lambda case: case.text)
def test_only_restricts_a_status_to_its_day(case: Row) -> None:
    result = parse_status(case.text, posted_at=WED, tz=TZ)
    assert result.kind == case.kind
    assert result.dates == case.dates
    assert result.confidence == case.confidence
    if case.note is not None:
        assert case.note in result.notes


LEADS = ("Closed", "No school", "2 hour delay", "NTI", "Virtual learning")
WIDER = ("today and tomorrow", "today, tomorrow and Friday", "today, Thursday and Friday")
MARKS = ("Update:", "UPDATE -", "Correction:", "Updated:", "")
RESTRICTED = ("{lead} today only", "{lead} only today", "today only")


@settings(max_examples=300, deadline=None)
@given(
    lead=st.sampled_from(LEADS),
    wider=st.sampled_from(WIDER),
    mark=st.sampled_from(MARKS),
    restricted=st.sampled_from(RESTRICTED),
    first=st.booleans(),
    posted=st.sampled_from((WED, WED_EVENING)),
)
def test_a_day_left_out_by_only_is_never_a_confident_status(  # noqa: PLR0913, PLR0917
    lead: str, wider: str, mark: str, restricted: str, first: bool, posted: datetime
) -> None:
    if first and mark:
        return  # (a later update replaces the "only": "Closed today only. Update: ...")
    narrow = restricted.format(lead=lead)
    widest = f"{lead} {wider}"
    text = f"{narrow}. {mark} {widest}" if first else f"{widest}. {mark} {narrow}"
    result = parse_status(text, posted_at=posted, tz=TZ)
    today = posted.date()
    if result.kind != "other" and result.confidence >= 0.7:
        named = {day for entry in result.schedule for day in entry.dates}
        assert named <= {today}, text
