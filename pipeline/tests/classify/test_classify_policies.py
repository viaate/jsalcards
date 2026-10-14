"""Rules for statuses to come, and headings: no status for any day.

Every text here is a phrasing pattern written for these tests, not a claim
about a real school. Unless a row says otherwise it is posted at 6 a.m. on
Wednesday 21 January 2026 in Chicago, so "today" is Wednesday the 21st and
"tomorrow" Thursday the 22nd.

A sentence that states a rule for statuses to come ("Any closure tomorrow will
be an eLearning day", "Our next snow day will be an NTI day", "Future closures
will be remote learning days", "Snow days will be remote learning days", "Any
delay will be 2 hours", "On early release days, dismissal is at 1:00") is a
condition, as "If school is closed, it will be an eLearning day" is: ``other``
at 0.3, noted ``hedged``, whatever day it names. A status in another sentence
stands ("Closed today. Any future closures will be eLearning days."), and "any"
after a denial is none ("No schools have reported any closings").

A heading names a page or a list, not a status: status nouns listed together
("Closings and delays", "School Closings & Delays"), a status noun before a
noun of what the page holds ("Snow day procedures", "NTI day information", "AMI
packets"), and a list's header with no subject of its own ("The following
schools are closed today:"). Its status words are ``ambiguous``: ``other`` at
0.3.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from snowlight.classify import parse_status

TZ = "America/Chicago"
ZONE = ZoneInfo(TZ)
MORNING = datetime(2026, 1, 21, 6, 0, tzinfo=ZONE)  # Wednesday


def jan(*days: int) -> tuple[date, ...]:
    return tuple(date(2026, 1, day) for day in days)


@dataclass(frozen=True)
class Row:
    text: str
    kind: str
    dates: tuple[date, ...]
    confidence: float
    notes: tuple[str, ...]


def row(
    text: str,
    kind: str = "other",
    dates: tuple[date, ...] = (),
    *,
    confidence: float = 0.3,
    notes: tuple[str, ...] = (),
) -> object:
    return pytest.param(Row(text, kind, dates, confidence, notes), id=text)


def rule(text: str) -> object:
    return row(text, notes=("hedged",))


def heading(text: str) -> object:
    return row(text, notes=("ambiguous",))


POLICIES = [
    rule("Any closure tomorrow will be an eLearning day"),
    rule("Any delay tomorrow will be 2 hours"),
    rule("Our next snow day will be an eLearning day"),
    rule("The next closure will be an NTI day"),
    rule("Next closure will be remote"),
    rule("Snow days will be remote learning days"),
    rule("All snow days will be NTI days"),
    rule("Any weather-related closures will be eLearning days"),
    rule("Closures will be NTI days"),
    rule("All closures will be AMI days"),
    rule("Future closures will be remote learning days"),
    rule("Any future snow days will be virtual"),
    rule("Any early dismissal will be at 1:00"),
    rule("Any delay will be 2 hours"),
    rule("Every snow day will be an NTI day"),
    rule("Each closure this winter will be a remote learning day"),
    rule("On early release days, dismissal is at 1:00"),
    rule("On delay days, school starts at 10:00"),
    rule("On snow days, students complete NTI packets"),
    rule("If school is closed, it will be an eLearning day"),
    # Plural and singular rules, with or without hyphens, and rules for days of a kind.
    rule("Any weather related closure will be an e-learning day"),
    rule("Inclement weather days will be eLearning days"),
    rule("Inclement weather days will be virtual learning days"),
    rule("Closures this winter will be NTI days"),
    rule("Weather days will be virtual"),
    rule("Bad weather days will be remote learning days"),
    rule("Snow days are eLearning days"),
    rule("Early dismissals will be at 12:30"),
    rule("Early release days: dismissal at 1:00"),
    rule("Delayed start days begin at 10:00"),
    rule("2 hour delay days: school starts at 10:00"),
    # A sentence that opens with a status as a case.
    rule("On 2 hour delay days, buses run 2 hours late"),
    rule("On a 2 hour delay, buses run 2 hours late"),
    rule("For a 2 hour delay, buses run 2 hours late"),
    rule("During a 2 hour delay, breakfast is not served"),
    rule("With a 2 hour delay, no AM kindergarten"),
    rule("In the event of a closure, classes will be virtual"),
]

STANDING = [
    row("Closed today. Any future closures will be eLearning days.", "closed", jan(21),
        confidence=0.95),
    row("No schools have reported any closings", confidence=0.9, notes=("negated",)),
    row("NTI days Thursday and Friday", "remote", jan(22, 23), confidence=0.95),
    row("Closed next Monday", "closed", jan(26), confidence=0.95),
    row("Closed today. On delay days, breakfast is not served.", "closed", jan(21),
        confidence=0.95, notes=("hedged",)),
    row("Closed today; snow days are eLearning days", "closed", jan(21), confidence=0.95),
    row("eLearning days start tomorrow", "remote", jan(22), confidence=0.95),
    row("2 hour delay today, buses run 2 hours late", "delayed", jan(21), confidence=0.95),
    row("School will be on a 2 hour delay, buses run 2 hours late", "delayed", jan(21),
        confidence=0.9),
]  # fmt: skip

HEADINGS = [
    heading("Closings and delays"),
    heading("School Closings & Delays"),
    heading("Closures and delays"),
    heading("Snow day procedures"),
    heading("Closure procedures"),
    heading("NTI day information"),
    heading("AMI packets"),
    heading("Remote learning guidelines"),
    heading("The following schools are closed today:"),
    heading("The following schools/districts are closed for weather related reasons on 1/22:"),
    heading("The following schools are closed today: Kubaze Elementary"),
]


def check(case: Row) -> None:
    result = parse_status(case.text, posted_at=MORNING, tz=TZ)
    assert result.kind == case.kind
    assert result.dates == case.dates
    assert result.confidence == case.confidence
    assert set(case.notes) <= set(result.notes)


@pytest.mark.parametrize("case", POLICIES)
def test_a_rule_for_statuses_to_come_states_no_status(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", STANDING)
def test_a_status_beside_a_rule_or_a_denied_any_stands(case: Row) -> None:
    check(case)


@pytest.mark.parametrize("case", HEADINGS)
def test_a_heading_states_no_status(case: Row) -> None:
    check(case)


OPENERS = ("Any", "Our next", "The next", "Future", "Any future", "All future", "Every")
SUBJECTS = ("closure", "closures", "snow day", "snow days", "delay", "delays",
            "early dismissal", "NTI day", "eLearning days", "weather-related closures")  # fmt: skip
DAYS = ("", " tomorrow", " this week", " on Friday", " this winter")
CONSEQUENCES = ("an eLearning day", "remote learning days", "a 2 hour delay", "2 hours",
                "at 1:00", "an NTI day", "virtual", "closed")  # fmt: skip


@settings(max_examples=400, deadline=None)
@given(
    opener=st.sampled_from(OPENERS),
    subject=st.sampled_from(SUBJECTS),
    day=st.sampled_from(DAYS),
    consequence=st.sampled_from(CONSEQUENCES),
    days_on=st.integers(0, 6),
)
def test_a_rule_never_gives_a_confident_status(
    opener: str, subject: str, day: str, consequence: str, days_on: int
) -> None:
    text = f"{opener} {subject}{day} will be {consequence}"
    result = parse_status(text, posted_at=MORNING + timedelta(days=days_on), tz=TZ)
    assert result.confidence < 0.7, text


KINDS = ("2 hour delay", "two hour delay", "delay", "late start", "delayed start",
         "early release", "early dismissal", "eLearning", "e-learning", "NTI", "snow",
         "inclement weather", "weather", "remote learning", "virtual")  # fmt: skip
RULE_FORMS = (
    "{Kind} days will be {consequence}", "{Kind} days are {consequence}",
    "On {kind} days, {consequence_clause}", "{Kind} days: {consequence_clause}",
    "Any {kind} day will be {consequence}", "Any {kind} days will be {consequence}",
)  # fmt: skip
CASE_FORMS = (
    "On a {kind}, {consequence_clause}", "For a {kind}, {consequence_clause}",
    "During a {kind}, {consequence_clause}", "With a {kind}, {consequence_clause}",
)  # fmt: skip
CLAUSES = ("buses run 2 hours late", "breakfast is not served", "no AM kindergarten",
           "dismissal is at 1:00", "school starts at 10:00", "students work from home")  # fmt: skip


@settings(max_examples=500, deadline=None)
@given(
    kind=st.sampled_from(KINDS),
    form=st.sampled_from(RULE_FORMS),
    consequence=st.sampled_from(CONSEQUENCES),
    clause=st.sampled_from(CLAUSES),
)
def test_a_rule_for_a_kind_of_day_never_gives_a_confident_status(
    kind: str, form: str, consequence: str, clause: str
) -> None:
    text = form.format(
        kind=kind,
        Kind=kind[0].upper() + kind[1:],
        consequence=consequence,
        consequence_clause=clause,
    )
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other" or result.confidence < 0.7, text
    assert result.schedule == (), text


@settings(max_examples=300, deadline=None)
@given(
    kind=st.sampled_from(
        (
            "2 hour delay",
            "delay",
            "late start",
            "closure",
            "early dismissal",
            "snow day",
            "two hour delay",
            "90 minute delay",
        )
    ),
    form=st.sampled_from(CASE_FORMS),
    clause=st.sampled_from(CLAUSES),
)
def test_a_status_opening_a_sentence_as_a_case_never_gives_a_confident_status(
    kind: str, form: str, clause: str
) -> None:
    text = form.format(kind=kind, consequence_clause=clause)
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other" or result.confidence < 0.7, text
    assert result.schedule == (), text
