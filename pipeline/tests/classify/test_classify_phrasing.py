"""Table-driven tests of status phrasing.

Every text here is a phrasing pattern of the kind closings lists use, written
for these tests. None of them is a claim about a real school. All cases are
posted at 5:30 a.m. on Tuesday 20 January 2026 in New York unless a case says
otherwise, so an undated status applies to that Tuesday.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from snowlight.classify import ParsedStatus, parse_status
from snowlight.classify import parse as parse_module
from snowlight.classify.parse import _cached_analysis, _normalized_analysis

TZ = "America/New_York"
POSTED = datetime(2026, 1, 20, 5, 30, tzinfo=ZoneInfo(TZ))  # a Tuesday


def jan(*days: int) -> tuple[date, ...]:
    return tuple(date(2026, 1, day) for day in days)


@dataclass(frozen=True)
class Expect:
    kind: str
    dates: tuple[date, ...] | None = None
    delay: int | None = None
    opens: time | None = None
    dismissal: time | None = None
    early: int | None = None
    notes: frozenset[str] = field(default_factory=frozenset)
    offices_open: bool | None = None
    says_open: bool | None = None
    max_confidence: float | None = None
    min_confidence: float | None = None
    schedule: tuple[tuple[str, tuple[date, ...]], ...] | None = None


def case(text: str, kind: str, **fields: object) -> object:
    notes = fields.pop("notes", ())
    assert isinstance(notes, tuple)
    expect = Expect(kind, notes=frozenset(notes), **fields)  # type: ignore[arg-type]
    return pytest.param(text, expect, id=text or "<empty>")


def check(result: ParsedStatus, expect: Expect) -> None:
    assert result.kind == expect.kind
    if expect.kind == "other":
        assert result.dates == ()
        assert result.schedule == ()
    if expect.dates is not None:
        assert result.dates == expect.dates
    assert result.delay_minutes == expect.delay
    assert result.opens_at == expect.opens
    assert result.dismissal_time == expect.dismissal
    assert result.dismissal_early_minutes == expect.early
    assert expect.notes <= set(result.notes)
    if expect.offices_open is not None:
        assert result.offices_open is expect.offices_open
    if expect.says_open is not None:
        assert result.says_open is expect.says_open
    if expect.max_confidence is not None:
        assert result.confidence <= expect.max_confidence
    if expect.min_confidence is not None:
        assert result.confidence >= expect.min_confidence
    if expect.schedule is not None:
        assert tuple((entry.kind, entry.dates) for entry in result.schedule) == expect.schedule


T = time
TUE = jan(20)

CLOSED = [
    case("Closed", "closed", dates=TUE, min_confidence=0.9),
    case("CLOSED", "closed", dates=TUE),
    case("closed", "closed", dates=TUE),
    case("Closed today", "closed", dates=TUE, min_confidence=0.95),
    case("Closed Today - Snow", "closed", dates=TUE),
    case("Schools closed due to snow", "closed", dates=TUE),
    case("All schools closed", "closed", dates=TUE),
    case("All district schools closed", "closed", dates=TUE),
    case("School closed", "closed", dates=TUE),
    case("Closed for the day", "closed", dates=TUE),
    case("Closed; offices open", "closed", dates=TUE, offices_open=True),
    case("Closed - Offices Open", "closed", dates=TUE, offices_open=True),
    case("Closed (offices open)", "closed", dates=TUE, offices_open=True),
    case("Schools closed, offices open", "closed", dates=TUE, offices_open=True),
    case("Closed; district offices open", "closed", dates=TUE, offices_open=True),
    case("School closed, but offices open", "closed", offices_open=True),
    case("Closed today and tomorrow", "closed", dates=jan(20, 21)),
    case("Closed Today & Tomorrow", "closed", dates=jan(20, 21)),
    case("CLOSED TODAY AND TOMORROW", "closed", dates=jan(20, 21)),
    case("No school", "closed", dates=TUE),
    case("No School", "closed", dates=TUE),
    case("No school today", "closed", dates=TUE, min_confidence=0.95),
    case("No school for students", "closed", dates=TUE),
    case("No classes", "closed", dates=TUE),
    case("No classes today", "closed", dates=TUE),
    case("There will be no school today", "closed", dates=TUE),
    case("Classes cancelled", "closed", dates=TUE),
    case("Classes canceled", "closed", dates=TUE),
    case("All classes are cancelled", "closed", dates=TUE),
    case("School is cancelled", "closed", dates=TUE),
    case("School cancelled today", "closed", dates=TUE),
    case("Classes have been canceled for today", "closed", dates=TUE),
    case("Cancelled: all classes", "closed", dates=TUE),
    case("District cancels classes", "closed", dates=TUE),
    case("Snow day", "closed", dates=TUE),
    case("Snow Day", "closed", dates=TUE),
    case("Emergency closing", "closed", dates=TUE),
    case("Emergency closure", "closed", dates=TUE),
    case("Weather closure", "closed", dates=TUE),
    case("Calamity day", "closed", dates=TUE),
    case("Full closure", "closed", dates=TUE),
    case("Closed for students; staff report at 10", "closed", notes=("staff",)),
    case("Closed to students", "closed", dates=TUE),
    case("Closed for students and staff", "closed", dates=TUE),
    case("Closed for all students", "closed", dates=TUE),
    case("Closed - staff report on time", "closed", dates=TUE, notes=("staff",)),
    case("School will not be in session", "closed", dates=TUE),
    case("Schools are not in session today", "closed", dates=TUE),
    case("Classes will not meet", "closed", dates=TUE),
    case("School will not open today", "closed", dates=TUE),
    case("Schools shut down", "closed", dates=TUE),
    case("Closing today", "closed", dates=TUE),
    case("Closing tomorrow", "closed", dates=jan(21)),
    case("Closed for teacher workday", "closed", dates=TUE),
    case("Closed Friday for staff development", "closed", dates=jan(23)),
    case("Schools and offices closed", "closed", dates=TUE, notes=("offices_closed",)),
    case("All schools and district offices closed", "closed", notes=("offices_closed",)),
    case("Closed - Power outage", "closed", dates=TUE),
    case(
        "Closed; all activities canceled; no practices", "closed", notes=("activities_cancelled",)
    ),
    case(
        "No school today. All activities cancelled.",
        "closed",
        dates=TUE,
        notes=("activities_cancelled",),
    ),
    case("Closed and all activities cancelled", "closed", notes=("activities_cancelled",)),
]

DELAYED = [
    case("2 Hour Delay", "delayed", dates=TUE, delay=120),
    case("2-Hour Delay", "delayed", dates=TUE, delay=120),
    case("Two Hour Delay", "delayed", delay=120),
    case("two-hour delay", "delayed", delay=120),
    case("2hr delay", "delayed", delay=120),
    case("2 hrs delay", "delayed", delay=120),
    case("2 hr. delay", "delayed", delay=120),
    case("2 Hrs. Delay", "delayed", delay=120),
    case("2h delay", "delayed", delay=120),
    case("90 minute delay", "delayed", delay=90),
    case("90-Minute Delay", "delayed", delay=90),
    case("90 Min Delay", "delayed", delay=90),
    case("1.5 hour delay", "delayed", delay=90),
    case("1 1/2 hour delay", "delayed", delay=90),
    case("1-1/2 hour delay", "delayed", delay=90),
    case("1\u00bd hour delay", "delayed", delay=90),
    case("One and a half hour delay", "delayed", delay=90),
    case("Hour and a half delay", "delayed", delay=90),
    case("An hour and a half delay", "delayed", delay=90),
    case("3 hour delay", "delayed", delay=180),
    case("Three-hour delay", "delayed", delay=180),
    case("1 hour delay", "delayed", delay=60),
    case("One hour delay", "delayed", delay=60),
    case("45 minute delay", "delayed", delay=45),
    case("Half hour delay", "delayed", delay=30),
    case("2 hour late start", "delayed", delay=120),
    case("One-hour late start", "delayed", delay=60),
    case("2 Hour Delayed Start", "delayed", delay=120),
    case("2-hour delayed opening", "delayed", delay=120),
    case("Delayed 2 hours", "delayed", delay=120),
    case("Delayed two hours", "delayed", delay=120),
    case("Delay of 90 minutes", "delayed", delay=90),
    case("Delayed by one hour", "delayed", delay=60),
    case("Delay 2 Hrs", "delayed", delay=120),
    case("Delay - 2 hours", "delayed", delay=120),
    case("Late Start - 2 Hours", "delayed", delay=120),
    case("Opening 2 hours late", "delayed", delay=120),
    case("Schools open 2 hours late", "delayed", delay=120),
    case("School will start 2 hours late", "delayed", delay=120),
    case("Students report 2 hours late", "delayed", delay=120),
    case("2 hours late", "delayed", delay=120),
    case("Delayed opening", "delayed", dates=TUE),
    case("Delayed start", "delayed", dates=TUE),
    case("Late start", "delayed", dates=TUE),
    case("Late opening", "delayed", dates=TUE),
    case("Delayed", "delayed", dates=TUE),
    case("Delay", "delayed", dates=TUE),
    case("Opening at 10:00", "delayed", opens=T(10)),
    case("Opening at 10 am", "delayed", opens=T(10)),
    case("Opening at 10 a.m.", "delayed", opens=T(10)),
    case("School opens at 10", "delayed", opens=T(10)),
    case("Schools will open at 9:30 a.m.", "delayed", opens=T(9, 30)),
    case("Classes begin at 9:30", "delayed", opens=T(9, 30)),
    case("Classes start at 10:15 am", "delayed", opens=T(10, 15)),
    case("Students report at 10:00", "delayed", opens=T(10)),
    case("Will not open until 10 am", "delayed", opens=T(10)),
    case("Delayed Opening - 10:00 AM", "delayed", opens=T(10)),
    case("Delayed opening today at 10", "delayed", dates=TUE, opens=T(10)),
    case("Start time delayed to 10:00", "delayed", opens=T(10)),
    case("Opening at 10:00 (2 hour delay)", "delayed", delay=120, opens=T(10)),
    case("2 Hour Delay - No AM Kindergarten", "delayed", delay=120, notes=("partial_program",)),
    case("2 Hour Delay, No AM Pre-K", "delayed", delay=120, notes=("partial_program",)),
    case("2 hour delay; no morning preschool", "delayed", delay=120, notes=("partial_program",)),
    case("2 hour delay; buses on snow routes", "delayed", delay=120, notes=("transportation",)),
    case(
        "Two Hour Delay - Buses will run 2 hours late",
        "delayed",
        delay=120,
        notes=("transportation",),
    ),
    case("2-hour delay for students; staff report on time", "delayed", delay=120, notes=("staff",)),
    case("Students 2 hours late, staff 1 hour late", "delayed", delay=120, notes=("staff",)),
    case("2 hour delay for students; staff report at regular time", "delayed", delay=120),
    case("Two hour delay today", "delayed", dates=TUE, delay=120, min_confidence=0.95),
    case("2 hour delay tomorrow", "delayed", dates=jan(21), delay=120),
    case("2 hour delay; buses at 9:45", "delayed", delay=120),
    # A delay with a length, or a late start, until a day: a delay on each day.
    case("2 hour delay until Friday", "delayed", dates=jan(20, 21, 22), delay=120),
    case("Late start until Monday", "delayed", dates=jan(20, 21, 22, 23)),
    case("Delayed until further notice", "delayed", dates=TUE),
    case("Delay of 2 hours until Friday", "delayed", dates=jan(20, 21, 22), delay=120),
    case(
        "Delay of 2 hours until Friday; middle school 1 hour delay",
        "delayed",
        dates=jan(20, 21, 22),
        notes=("partial_program",),
    ),
    case("until Friday - Delayed start", "delayed", dates=jan(20, 21, 22)),
]

# A delay with no length or time until a day puts the start off to that day: closed before it.
DELAYED_UNTIL_A_DAY = [
    case("School delayed until Monday", "closed", dates=jan(20, 21, 22, 23), max_confidence=0.8),
    case("Delayed until Thursday", "closed", dates=jan(20, 21), max_confidence=0.8),
    case("Delayed opening until Monday", "closed", dates=jan(20, 21, 22, 23)),
    case("School delayed until Jan 26", "closed", dates=jan(20, 21, 22, 23)),
    case("Classes delayed until Wednesday due to snow", "closed", dates=TUE),
    # A level on a status of its own beside it, on no day said: no status of the district.
    case("Delayed until Friday; middle school 2 hour delay", "other", notes=("partial_program",)),
]

REMOTE = [
    case("NTI Day", "remote", dates=TUE),
    case("NTI day #3", "remote", dates=TUE),
    case("NTI", "remote"),
    case("Non-traditional instruction day", "remote"),
    case("AMI Day", "remote"),
    case("AMI day 2", "remote"),
    case("Alternative Methods of Instruction day", "remote"),
    case("e-Learning Day", "remote"),
    case("eLearning", "remote"),
    case("E-learning", "remote"),
    case("E learning day", "remote"),
    case("eLearning Day for all students", "remote"),
    case("Virtual learning day", "remote"),
    case("Virtual", "remote"),
    case("Virtual day", "remote"),
    case("Virtual instruction", "remote"),
    case("Remote learning", "remote"),
    case("Remote Learning Day", "remote"),
    case("Remote instruction", "remote"),
    case("Remote", "remote"),
    case("Flexible Instruction Day", "remote"),
    case("Flexible Instructional Day", "remote"),
    case("FID", "remote"),
    case("Flexible instructional day (FID)", "remote"),
    case("Asynchronous learning day", "remote"),
    case("Asynchronous", "remote"),
    case("Virtual snow day", "remote"),
    case("Closed - NTI Day", "remote", dates=TUE),
    case("Buildings closed, remote learning", "remote"),
    case("Closed to students; e-learning day", "remote"),
    case("Remote learning with a 2-hour delay", "remote", delay=120),
    case("Online learning", "remote"),
    case("Online classes", "remote"),
    case("Distance learning day", "remote"),
    case("Digital learning day", "remote"),
    case("Blizzard bag day", "remote"),
    case("Students learn from home", "remote"),
    case("At-home learning day", "remote"),
    case("Cyber day", "remote"),
    case("Classes will meet virtually", "remote"),
    case("Students should log in for eLearning", "remote"),
    case("E-Learning Day (Snow Day #3)", "remote"),
    case("No in-person classes; remote learning", "remote"),
    case("Remote learning Thursday and Friday", "remote", dates=jan(22, 23)),
    case("NTI Day Wednesday", "remote", dates=jan(21)),
]

EARLY = [
    case("Early dismissal", "early_dismissal", dates=TUE),
    case("Early Dismissal 1:00", "early_dismissal", dismissal=T(13)),
    case("Early dismissal at 1 pm", "early_dismissal", dismissal=T(13)),
    case("Early dismissal at 1:00 p.m.", "early_dismissal", dismissal=T(13)),
    case("Early Dismissal @ 12:30", "early_dismissal", dismissal=T(12, 30)),
    case("Early dismissal - 11:30 AM", "early_dismissal", dismissal=T(11, 30)),
    case("Early release", "early_dismissal"),
    case("Early release at noon", "early_dismissal", dismissal=T(12)),
    case("Early release 12:30", "early_dismissal", dismissal=T(12, 30)),
    case("Early dismissal today at 1:30", "early_dismissal", dates=TUE, dismissal=T(13, 30)),
    case("Dismissing 2 hours early", "early_dismissal", early=120),
    case("Dismissing two hours early", "early_dismissal", early=120),
    case("Dismissing at 1:00", "early_dismissal", dismissal=T(13)),
    case("Dismissing early", "early_dismissal"),
    case("Dismissing early at 12:45", "early_dismissal", dismissal=T(12, 45)),
    case("Closing at noon", "early_dismissal", dismissal=T(12)),
    case("Closing at 12:30 pm", "early_dismissal", dismissal=T(12, 30)),
    case("Closing early", "early_dismissal"),
    case("Closing early at 1:00", "early_dismissal", dismissal=T(13)),
    case("Closed at noon", "early_dismissal", dismissal=T(12)),
    case("Closes at 1 pm", "early_dismissal", dismissal=T(13)),
    case("2 hour early dismissal", "early_dismissal", early=120),
    case("Two-hour early release", "early_dismissal", early=120),
    case("90 minute early dismissal", "early_dismissal", early=90),
    case("Early dismissal of 2 hours", "early_dismissal", early=120),
    case("Early out", "early_dismissal"),
    case("Early-out 1:15", "early_dismissal", dismissal=T(13, 15)),
    case("Half day", "early_dismissal"),
    case("Half-day", "early_dismissal"),
    case("1/2 day", "early_dismissal"),
    case("Noon dismissal", "early_dismissal", dismissal=T(12)),
    case("12:30 dismissal", "early_dismissal", dismissal=T(12, 30)),
    case("1 pm early dismissal", "early_dismissal", dismissal=T(13)),
    case("Students released at 11:30", "early_dismissal", dismissal=T(11, 30)),
    case("Students will be dismissed at 1:00", "early_dismissal", dismissal=T(13)),
    case("Releasing students 2 hours early", "early_dismissal", early=120),
    case("Early Closing", "early_dismissal"),
    case("Closing 2 Hours Early", "early_dismissal", early=120),
    case("Early release: 11:30 elementary, 12:15 secondary", "early_dismissal"),
    case(
        "Early dismissal; all after-school activities cancelled",
        "early_dismissal",
        notes=("activities_cancelled",),
    ),
    case("Dismissing early due to heat", "early_dismissal"),
]

NOT_CLOSURES = [
    case("All activities cancelled", "other", notes=("activities_cancelled",), min_confidence=0.9),
    case("All after-school activities cancelled", "other", notes=("activities_cancelled",)),
    case("After school activities canceled", "other", notes=("activities_cancelled",)),
    case("Evening activities cancelled", "other", notes=("activities_cancelled",)),
    case("After school and evening activities cancelled", "other", notes=("activities_cancelled",)),
    case("Athletics cancelled", "other", notes=("activities_cancelled",)),
    case("All practices and games cancelled", "other", notes=("activities_cancelled",)),
    case("Tonight's games postponed", "other", notes=("activities_cancelled",)),
    case("Board meeting postponed", "other", notes=("activities_cancelled",)),
    case("PTA meeting cancelled", "other", notes=("activities_cancelled",)),
    case("Field trips cancelled", "other", notes=("activities_cancelled",)),
    case("Swim meet cancelled", "other", notes=("activities_cancelled",)),
    case("Ice cream social cancelled", "other", notes=("activities_cancelled",)),
    case("Evening classes cancelled", "other", notes=("activities_cancelled",)),
    case("Adult education classes cancelled", "other", notes=("activities_cancelled",)),
    case("No AM kindergarten", "other", notes=("partial_program",), min_confidence=0.9),
    case("No AM or PM kindergarten", "other", notes=("partial_program",)),
    case("No PM Pre-K", "other", notes=("partial_program",)),
    case("No pre-k", "other", notes=("partial_program",)),
    case("No preschool", "other", notes=("partial_program",)),
    case("No morning kindergarten", "other", notes=("partial_program",)),
    case("No half-day kindergarten", "other", notes=("partial_program",)),
    case("Pre-K closed", "other", notes=("partial_program",)),
    case("Kindergarten cancelled", "other", notes=("partial_program",)),
    case("No BOCES", "other", notes=("partial_program",)),
    case("No AM classes", "other", notes=("partial_program",)),
    case("Hot lunch cancelled", "other", notes=("partial_program",)),
    case("Daycare closed", "other", notes=("childcare",)),
    case("Kids Club cancelled", "other", notes=("childcare",)),
    case("Before and after care cancelled", "other", notes=("childcare",)),
    case("No latchkey", "other", notes=("childcare",)),
    case("No buses", "other", notes=("transportation",)),
    case("No bus service", "other", notes=("transportation",)),
    case("Buses on snow routes", "other", notes=("transportation",)),
    case("Buses running 2 hours late", "other", notes=("transportation",)),
    case("Limited bus service", "other", notes=("transportation",)),
    # A road listed among the closings: its direction of travel names it.
    case("NB still closed", "other", notes=("transportation",)),
    case("Northbound lanes closed", "other", notes=("transportation",)),
    case("Westbound ramp closed due to ice", "other", notes=("transportation",)),
    case("SB reopened; NB closed", "other", notes=("transportation",)),
    case("Offices closed", "other", notes=("offices_closed",)),
    case("District offices closed", "other", notes=("offices_closed",)),
    case("Central office closed", "other", notes=("offices_closed",)),
    case("School offices closed", "other", notes=("offices_closed",)),
    case("Staff report 2 hours late", "other", notes=("staff",)),
    case("Staff: 2 hour delay", "other", notes=("staff",)),
    case("12-month employees report at 10", "other", notes=("staff",)),
    case("Open", "other", says_open=True, min_confidence=0.9),
    case("Open on time", "other", says_open=True),
    case("Normal schedule", "other", says_open=True),
    case("School is open", "other", says_open=True),
    case("Regular schedule", "other", says_open=True),
    case("On time", "other", says_open=True),
    case("Offices open", "other", says_open=False, offices_open=True),
    case("No delay", "other", notes=("negated",), says_open=False),
    case("Not closed", "other", notes=("negated",)),
    case("No closings or delays", "other", notes=("negated",)),
    case("There are no delays or closings at this time", "other", notes=("negated",)),
    case("School will not be closed", "other", notes=("negated",)),
    case("Regular dismissal at 3:10", "other", max_confidence=0.1),
    case("Cold lunch will be served", "other", max_confidence=0.1),
]

AMBIGUOUS = [
    case("Cancelled", "other", max_confidence=0.3),
    case("Canceled", "other", max_confidence=0.3),
    case("Canceled due to weather", "other", max_confidence=0.3),
    case("Closing", "other", max_confidence=0.3),
    case("Closings", "other", max_confidence=0.3),
    case("Possible closing", "other", max_confidence=0.3, notes=("hedged",)),
    case("Possible early dismissal", "other", max_confidence=0.3, notes=("hedged",)),
    case("Closing possible", "other", max_confidence=0.3, notes=("hedged",)),
    case("2 hour delay possible", "other", max_confidence=0.3, notes=("hedged",)),
    case("Delays likely tomorrow", "other", max_confidence=0.3, notes=("hedged",)),
    case("May close early", "other", max_confidence=0.3, notes=("hedged",)),
    case("Might have a 2 hour delay", "other", max_confidence=0.3, notes=("hedged",)),
    case("Could be an NTI day", "other", max_confidence=0.3, notes=("hedged",)),
    case("Potential closure tomorrow", "other", max_confidence=0.3, notes=("hedged",)),
    case("Tentative 2 hour delay", "other", max_confidence=0.3, notes=("hedged",)),
    case("Expecting a delay tomorrow", "other", max_confidence=0.3, notes=("hedged",)),
    case("Monitoring conditions", "other", max_confidence=0.1),
    case("Decision by 6 am", "other", max_confidence=0.1),
    case("If roads are icy, school will be closed", "other", max_confidence=0.3, notes=("hedged",)),
    case("School will be closed if roads are icy", "other", max_confidence=0.3),
    case("Should conditions worsen, NTI day tomorrow", "other", max_confidence=0.3),
    case("In the event of a closure, it will be an NTI day", "other", max_confidence=0.3),
    case("Early dismissal at 1 if needed", "other", max_confidence=0.3),
    case("Inclement weather day", "other", max_confidence=0.3),
    case("Weather day", "other", max_confidence=0.3),
    case("Inclement weather", "other", max_confidence=0.3),
    case("Inclement weather schedule", "other", max_confidence=0.3),
    case("No in-person classes", "other", max_confidence=0.3),
    case("Closed. 2 hour delay.", "other", max_confidence=0.25, notes=("conflict",)),
    case("2 hour delay today. Closed.", "other", max_confidence=0.25, notes=("conflict",)),
    case("Closed Feb 30", "other", max_confidence=0.3, notes=("invalid_date",)),
    case("", "other", max_confidence=0.0),
    case("   ", "other", max_confidence=0.0),
    case("asdf qwerty", "other", max_confidence=0.1, notes=("unrecognized",)),
    case("Snowstorm", "other", max_confidence=0.1),
]

SEVERAL = [
    case(
        "Closed today, 2 hour delay tomorrow",
        "closed",
        dates=TUE,
        schedule=(("closed", jan(20)), ("delayed", jan(21))),
    ),
    case(
        "Today closed, tomorrow 2 hour delay",
        "closed",
        schedule=(("closed", jan(20)), ("delayed", jan(21))),
    ),
    case(
        "Closed today and 2 hour delay tomorrow",
        "closed",
        schedule=(("closed", jan(20)), ("delayed", jan(21))),
    ),
    case(
        "Closed Monday; NTI Tuesday",
        "remote",
        dates=TUE,
        schedule=(("closed", jan(19)), ("remote", jan(20))),
    ),
    case(
        "Monday 1/19: Closed. Tuesday 1/20: 2-hr delay.",
        "delayed",
        delay=120,
        schedule=(("closed", jan(19)), ("delayed", jan(20))),
    ),
    case("Tomorrow: 2 hour delay", "delayed", dates=jan(21), delay=120),
    case("Tuesday - Closed", "closed", dates=TUE),
    case("Closed - Wednesday", "closed", dates=jan(21)),
    case(
        "Early dismissal today at 1:00; closed tomorrow",
        "early_dismissal",
        dismissal=T(13),
        schedule=(("early_dismissal", jan(20)), ("closed", jan(21))),
    ),
    case(
        "2 hour delay Tuesday, Jan 20. Closed Wednesday.",
        "delayed",
        delay=120,
        schedule=(("delayed", jan(20)), ("closed", jan(21))),
    ),
    case(
        "Closed Friday; 2 hour delay Monday",
        "closed",
        schedule=(("closed", jan(23)), ("delayed", jan(26))),
    ),
    case(
        "Early dismissal today, closed tomorrow",
        "early_dismissal",
        schedule=(("early_dismissal", jan(20)), ("closed", jan(21))),
    ),
    case("2 hour delay changed to closed", "closed", notes=("superseded",)),
    case("Delay changed to closure", "closed", notes=("superseded",)),
    case("Now closed (was 2 hour delay)", "closed", notes=("superseded",)),
    case("Closed instead of 2-hour delay", "closed", notes=("superseded",)),
    case("Update: 2 hour delay now closed", "closed", notes=("superseded",)),
    case("Changed from a 2 hour delay to an e-learning day", "remote"),
    case("2 hour delay; early dismissal at 1:00", "delayed", delay=120, dismissal=T(13)),
    case(
        "Closed today. Will reassess tomorrow.",
        "closed",
        dates=TUE,
        schedule=(("closed", jan(20)),),
    ),
    case("Closed today and will reopen tomorrow", "closed", schedule=(("closed", jan(20)),)),
    case("Closed today, classes resume Thursday", "closed", schedule=(("closed", jan(20)),)),
    case("Closed today and possibly tomorrow", "closed", schedule=(("closed", jan(20)),)),
    case(
        "Closed today; may be closed tomorrow",
        "closed",
        schedule=(("closed", jan(20)),),
        notes=("hedged",),
    ),
    case("Closed today. Possible delay tomorrow.", "closed", schedule=(("closed", jan(20)),)),
]


@pytest.mark.parametrize(("text", "expect"), CLOSED)
def test_closed(text: str, expect: Expect) -> None:
    check(parse_status(text, posted_at=POSTED, tz=TZ), expect)


@pytest.mark.parametrize(("text", "expect"), DELAYED)
def test_delayed(text: str, expect: Expect) -> None:
    check(parse_status(text, posted_at=POSTED, tz=TZ), expect)


@pytest.mark.parametrize(("text", "expect"), DELAYED_UNTIL_A_DAY)
def test_delayed_until_a_day_is_closed_before_it(text: str, expect: Expect) -> None:
    check(parse_status(text, posted_at=POSTED, tz=TZ), expect)


@pytest.mark.parametrize(("text", "expect"), REMOTE)
def test_remote(text: str, expect: Expect) -> None:
    check(parse_status(text, posted_at=POSTED, tz=TZ), expect)


@pytest.mark.parametrize(("text", "expect"), EARLY)
def test_early_dismissal(text: str, expect: Expect) -> None:
    check(parse_status(text, posted_at=POSTED, tz=TZ), expect)


@pytest.mark.parametrize(("text", "expect"), NOT_CLOSURES)
def test_not_closures(text: str, expect: Expect) -> None:
    check(parse_status(text, posted_at=POSTED, tz=TZ), expect)


@pytest.mark.parametrize(("text", "expect"), AMBIGUOUS)
def test_ambiguous_is_never_a_status(text: str, expect: Expect) -> None:
    check(parse_status(text, posted_at=POSTED, tz=TZ), expect)


@pytest.mark.parametrize(("text", "expect"), SEVERAL)
def test_several_statuses(text: str, expect: Expect) -> None:
    check(parse_status(text, posted_at=POSTED, tz=TZ), expect)


def test_the_table_is_large() -> None:
    total = sum(map(len, (CLOSED, DELAYED, REMOTE, EARLY, NOT_CLOSURES, AMBIGUOUS, SEVERAL)))
    assert total >= 300


ALL_CASES = [
    *CLOSED, *DELAYED, *DELAYED_UNTIL_A_DAY, *REMOTE, *EARLY, *NOT_CLOSURES, *AMBIGUOUS, *SEVERAL,
]  # fmt: skip


@pytest.mark.parametrize(("text", "expect"), ALL_CASES)
def test_the_plain_text_shortcut_agrees_on_every_case(text: str, expect: Expect) -> None:
    del expect
    results = []
    for fast in (True, False):
        parse_module._FAST_PATH = fast
        _cached_analysis.cache_clear()
        _normalized_analysis.cache_clear()
        try:
            results.append(parse_status(text, posted_at=POSTED, tz=TZ))
        finally:
            parse_module._FAST_PATH = True
    assert results[0] == results[1]
