"""Words after a list of days, in its clause, that could make its last days their own.

Every text here is a phrasing pattern written for these tests, not a claim about
a real school. Unless a row says otherwise it is posted at 6 a.m. on Wednesday
21 January 2026 in Chicago, so "today" is Wednesday the 21st, "tomorrow"
Thursday the 22nd and "Friday" the 23rd.

A list of days reads as the days of the status before it only when the words
after its last day, in its clause, are ones that leave it its days: words that
restate or add to it ("too", "as well", "also", "again"), who it is for ("for
all students", "all schools"), a reason ("snow", "inclement weather"), a cause
("due to the ice storm"), what it closes too ("and all evening activities"), the
time or the length of a late start or an early dismissal ("by 2 hours", "at
1:00"), a part of the day that fits the status ("2 hour delay Thursday and
Friday morning") and a status of its own kind ("No school today and tomorrow
snow days"). Any other word could make the last days its own subject ("Closed
today, tomorrow under review", "Closed today, Thursday and Friday not
affected", "... students return", "... stay tuned"), and so could a status of
the same kind that is denied ("... not closed"): the text says no status for
sure, ``other`` at 0.3. That holds for a pair of days ("today, tomorrow"), for a
list led by a relative day ("today, Thursday and Friday") and for weekdays
("Thursday, Friday"). A day named again in the clause ends the words read: what
follows it is that day's ("Closed today and tomorrow reopening Friday"). "In"
and "at" leave a list its days ("at all schools") but before a word that says
students attend ("students in class", "in school"), and "as per usual" is no
cause.
"""

from datetime import date, datetime, timedelta
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


# Words after the last day that could make it, and the days before it in the list, their own.
TRAILERS = [
    " not closed", " no closure", " under review", " is under review", " are under review",
    " not affected", " unaffected", " still on", " are still on", " unchanged", ": no changes",
    ": stay tuned", " stay tuned", " unknown", " unclear", " being monitored",
    " being evaluated", " will be reassessed", " decision tonight", "'s decision tonight",
    " will update tonight", " will be decided tonight", " we will be back", " back to school",
    " students return", " classes will be held", " classes as planned", " are a go",
    " all good", " OK", " fine", " too soon to tell", " is a school day", " on schedule",
    ": check back", " check back tonight", " school is on", " is not affected",
    " as per usual", " students in class", " in school", " at school", " being assessed",
]  # fmt: skip
# The three forms of a list: two relative days, a relative day leading weekday names, and
# weekday names.
FORMS = ["Closed today, tomorrow", "Closed today, Thursday and Friday", "Closed Thursday, Friday"]
CARRIED = [form + trailer for form in FORMS for trailer in TRAILERS] + [
    "No school today, tomorrow under review",
    "2 hour delay today, tomorrow under review",
    "Virtual today, tomorrow under review",
    "Closed today, tomorrow and Friday under review",
    "Closed Wednesday, Thursday and Friday not affected",
    "Closed Wednesday and Thursday, Friday not affected",
    "Closed today, tomorrow and Friday unchanged",
    "No school today, Thursday or Friday not closed",
    "NTI today, tomorrow students return",
    "Closed today and tomorrow decision tonight",
    "Closed Thursday, Friday decision Thursday night",
    "Thursday and Friday under review: closed",
    "Closed today, tomorrow reopen schools",
    # After a mark: a decision to come, or students back with no day of their own.
    "Closed today, tomorrow - decision pending",
    "Closed today, tomorrow - students back",
    "Closed today, Thursday and Friday - students return",
    "Closed today, tomorrow - back to school",
    "Closed today and tomorrow - we will be back",
]


@pytest.mark.parametrize("text", CARRIED)
def test_words_that_could_take_the_last_days_leave_no_status(text: str) -> None:
    for posted in (WED, WED_EVENING):
        result = parse_status(text, posted_at=posted, tz=TZ)
        assert result.kind == "other", (text, posted)
        assert result.dates == ()
        assert result.confidence <= 0.3
        assert "ambiguous" in result.notes or "hedged" in result.notes


# Words that leave the list its days: (text, kind, days).
STANDING = [
    ("Closed today, tomorrow too", "closed", jan(21, 22)),
    ("Closed today, tomorrow as well", "closed", jan(21, 22)),
    ("Closed today, tomorrow also", "closed", jan(21, 22)),
    ("No school today, tomorrow no school either", "closed", jan(21, 22)),
    ("Closed today, Thursday and Friday too", "closed", jan(21, 22, 23)),
    ("Closed today, Thursday and Friday as well", "closed", jan(21, 22, 23)),
    ("Closed Thursday, Friday again", "closed", jan(22, 23)),
    ("Closed today, tomorrow due to ice", "closed", jan(21, 22)),
    ("Closed today, Thursday and Friday because of icy roads", "closed", jan(21, 22, 23)),
    ("Closed Thursday, Friday for all students", "closed", jan(22, 23)),
    ("Closed today, tomorrow all schools", "closed", jan(21, 22)),
    ("Closed today, tomorrow districtwide", "closed", jan(21, 22)),
    ("Closed Thursday, Friday district wide", "closed", jan(22, 23)),
    ("Closed today and tomorrow at all schools", "closed", jan(21, 22)),
    ("Closed today and tomorrow in the district", "closed", jan(21, 22)),
    ("2 hour delay today and tomorrow in all schools", "delayed", jan(21, 22)),
    ("Closed today and tomorrow per the superintendent", "closed", jan(21, 22)),
    ("Closed Thursday and Friday, winter storm", "closed", jan(22, 23)),
    ("Closed today and tomorrow snow", "closed", jan(21, 22)),
    ("No school today, tomorrow snow days", "closed", jan(21, 22)),
    ("Closed today and tomorrow all day", "closed", jan(21, 22)),
    ("AMI today and tomorrow days 3 and 4", "remote", jan(21, 22)),
    ("Delayed Thursday and Friday by 2 1/2 hours", "delayed", jan(22, 23)),
    ("2 hour delay Thursday and Friday morning", "delayed", jan(22, 23)),
    ("Late start Thursday and Friday until 10", "delayed", jan(22, 23)),
    ("Early dismissal today and tomorrow at 1:00 pm", "early_dismissal", jan(21, 22)),
    ("Dismissing today and tomorrow 2 hours early", "early_dismissal", jan(21, 22)),
    ("Closed today and tomorrow reopening Friday", "closed", jan(21, 22)),
    ("Closed today and tomorrow - students back Friday", "closed", jan(21, 22)),
    ("No school Thursday and Friday not Monday", "closed", jan(22, 23)),
    ("Closed today, tomorrow and Friday only", "closed", jan(21, 22, 23)),
    # A school's name: after the list, and as the subject of the status the list heads.
    ("Closed today and tomorrow for Oak Ridge Elementary", "closed", jan(21, 22)),
    ("Thursday and Friday: Lincoln County Schools closed", "closed", jan(22, 23)),
    ("Thursday & Friday: all Maple Valley schools closed", "closed", jan(22, 23)),
    ("Today and tomorrow: schools closed", "closed", jan(21, 22)),
]


@pytest.mark.parametrize(("text", "kind", "days"), STANDING, ids=[row[0] for row in STANDING])
def test_words_that_leave_the_list_its_days(text: str, kind: str, days: tuple[date, ...]) -> None:
    result = parse_status(text, posted_at=WED, tz=TZ)
    assert (result.kind, result.dates) == (kind, days)
    assert result.confidence >= 0.9


# Predicates that make the days before them their own subject: a hedge, a decision or news to
# come, a school day that runs, or a status denied.
PREDICATES = (
    "under review", "being reviewed", "under consideration", "unknown", "unclear",
    "undecided", "TBD", "to be determined", "possible", "likely", "pending", "tentative",
    "decision tonight", "decision in the morning", "will be announced", "stay tuned",
    "check back later", "still on", "is on", "on schedule", "as scheduled", "regular day",
    "normal", "open", "in session", "students return", "classes will be held", "back to normal",
    "not affected", "unaffected", "unchanged", "no changes", "not closed", "no school? no",
    "a go", "all good", "fine", "is a school day", "school as usual", "being monitored",
    "as per usual", "students in class", "in school",
)  # fmt: skip
LEADS = ("Closed", "No school", "2 hour delay", "Virtual learning", "NTI", "Late start")
LISTS = (
    "today, tomorrow",
    "today, Thursday and Friday",
    "Thursday, Friday",
    "today, tomorrow and Friday",
    "Wednesday, Thursday and Friday",
    "today and tomorrow",
    "Thursday and Friday",
    "tomorrow, Friday and Monday",
    "today, Thursday or Friday",
)
# Posted on each day of the week, in the morning or the evening.
POSTINGS = st.builds(
    lambda day, hour: datetime(2026, 1, 19, hour, 0, tzinfo=ZONE) + timedelta(days=day),
    st.integers(0, 6),
    st.sampled_from((6, 20)),
)


@settings(max_examples=500, deadline=None)
@given(
    posted=POSTINGS,
    lead=st.sampled_from(LEADS),
    days=st.sampled_from(LISTS),
    predicate=st.sampled_from(PREDICATES),
    joiner=st.sampled_from((" ", ": ", " are ", " is ")),
)
def test_a_list_before_a_hedge_or_an_open_school_is_never_a_confident_status_on_its_last_days(
    posted: datetime, lead: str, days: str, predicate: str, joiner: str
) -> None:
    listed = parse_status(f"{lead} {days}", posted_at=posted, tz=TZ)
    trailing = set(listed.dates[1:])  # the days after the list's first
    text = f"{lead} {days}{joiner}{predicate}"
    result = parse_status(text, posted_at=posted, tz=TZ)
    if result.kind in {"closed", "delayed", "remote"} and result.confidence >= 0.7:
        named = {day for entry in result.schedule for day in entry.dates}
        assert not named & trailing, text
