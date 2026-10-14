"""A list of days led by "today" or "tomorrow": "Closed today, Thursday and Friday".

Every text here is a phrasing pattern written for these tests, not a claim about
a real school. Unless a row says otherwise it is posted at 6 a.m. on Wednesday
21 January 2026 in Chicago, so "today" is Wednesday the 21st, "tomorrow"
Thursday the 22nd and "Friday" the 23rd.

A comma after "today" or "tomorrow" can restate the day ("Closed tomorrow,
Thursday") or start a list ("Closed today, Thursday and Friday"). Days joined by
"or" are alternatives, one day or another, unless "no" leads them ("No school
today, Thursday or Friday" is no school on any of them): "Closed today, Thursday
or Friday" says no status for sure (see test_classify_undecided). With two
weekday names or more after it, joined as a list ("and", commas, or "or" after
"no"), the
words list their days when those days run one school day after another from
the relative day, in the order written; the weekend between Friday and Monday
counts as no gap. A restatement that agrees ("Closed tomorrow, Thursday and
Friday") reads as before, and any other reading is a mismatch, left ``other``
at 0.3: "Closed today, Friday and Monday" skips Thursday, and "Closed today,
Thursday" names one day two ways that disagree. The relative day must be a
school day itself: posted on a Friday, "Closed tomorrow, Monday and Tuesday"
starts on a Saturday, and is a mismatch too. Only a plain comma after the
relative day starts a list: a bracket, a slash, a colon, a dash or a bare space
names the day again ("Closed today (Thursday), Friday", "Closed today/Thursday
and Friday", "Closed today: Thursday and Friday", "Closed today - Thursday and
Friday", "Closed today Thursday and Friday"), and a weekday that disagrees with
it is a mismatch, whatever follows ("Closed tomorrow (Thursday) and Friday",
which agrees, is Thursday and Friday; "Closed today - also Thursday and Friday"
adds the days).

A list of days reads as the days of the status before it only when nothing after
it could take its last days for itself: a status of another kind with no day of
its own, in its sentence ("Closed today, Thursday and Friday 2 hour delay", "NTI
today, Thursday and Friday closed", "Closed today, tomorrow and Friday - 2 hour
delay"), an open school ("... open", "... on time", "... as scheduled", "...
normal"), a hedge or a decision to come ("... 2 hour delay possible", "... will
be announced"), or a part of the day ("... Friday nights") - in its clause any
word but the few that leave a list its days (see test_classify_list_trailers) -
as well as a part of today leading it ("Closed this afternoon, Thursday and
Friday"). Then the text
says no status for sure: ``other`` at 0.3, noted ``ambiguous``. That holds for
every list, led by a relative day or not ("Closed today, tomorrow and Friday
open", "Closed Wednesday, Thursday and Friday open", "Closed today, tomorrow
open"). A cause, an audience, a side note, an open office or a status of the
same kind leaves the list its days ("... due to the ice storm", "... for
students", "... - offices open", "No school today and tomorrow - snow days"), as
does a remote day after a mark, which adds to a closure ("Closed today and
tomorrow - NTI days"), and a status that names a day of its own ("..., 2 hour
delay Monday"). A day right after "not" is not the status's ("Closed today and
not tomorrow" is closed today), and a status left with no day of its own says
nothing sure ("No school not Monday"). A list led by a relative day says no
status for sure either when the text says school is open, or reopens, on one of
its days anywhere ("Closed today, Thursday and Friday. Open Friday.", "...
Friday: regular schedule", "... We will reopen Friday.").
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
WED = datetime(2026, 1, 21, 6, 0, tzinfo=ZONE)
WED_EVENING = datetime(2026, 1, 21, 21, 30, tzinfo=ZONE)
THU = datetime(2026, 1, 22, 6, 0, tzinfo=ZONE)
FRI = datetime(2026, 1, 23, 6, 0, tzinfo=ZONE)
FRI_EVENING = datetime(2026, 1, 23, 19, 0, tzinfo=ZONE)
SAT = datetime(2026, 1, 24, 9, 0, tzinfo=ZONE)
SUN = datetime(2026, 1, 25, 9, 0, tzinfo=ZONE)
SAT_NIGHT_MARCH = datetime(2026, 3, 7, 22, 0, tzinfo=ZONE)


def jan(*days: int) -> tuple[date, ...]:
    return tuple(date(2026, 1, day) for day in days)


@dataclass(frozen=True)
class Row:
    text: str
    kind: str
    dates: tuple[date, ...]
    posted: datetime = WED
    delay: int | None = None


LISTS = [
    Row("Closed today, Thursday and Friday", "closed", jan(21, 22, 23)),
    Row("Closed today, Thursday, and Friday", "closed", jan(21, 22, 23)),
    Row("Closed today, Thursday, Friday", "closed", jan(21, 22, 23)),
    Row("No school today, Thursday or Friday", "closed", jan(21, 22, 23)),
    Row("No school today, Thursday, or Friday", "closed", jan(21, 22, 23)),
    Row("Closed today, Thu and Fri", "closed", jan(21, 22, 23)),
    Row("Closed today, Thursday, Friday and Monday", "closed", jan(21, 22, 23, 26)),
    Row("Closed tomorrow, Friday and Monday", "closed", jan(22, 23, 26)),
    Row("2 hour delay today, Thursday and Friday", "delayed", jan(21, 22, 23), delay=120),
    Row("Virtual today, Thursday and Friday", "remote", jan(21, 22, 23)),
    Row("Remote learning today, Thursday & Friday", "remote", jan(21, 22, 23)),
    # Posted on a Friday: Monday is the next school day.
    Row("Closed today, Monday and Tuesday", "closed", jan(23, 26, 27), posted=FRI),
    # Posted in the evening: "today" is still the posting day.
    Row("Closed tomorrow, Friday and Monday", "closed", jan(22, 23, 26), posted=WED_EVENING),
    # A restatement that agrees, and the lists that already read as lists.
    Row("Closed tomorrow, Thursday and Friday", "closed", jan(22, 23)),
    Row("Closed today, Wednesday and Thursday", "closed", jan(21, 22)),
    Row("Closed Wednesday, Thursday and Friday", "closed", jan(21, 22, 23)),
    Row("Closed today, tomorrow and Friday", "closed", jan(21, 22, 23)),
    Row("Closed tomorrow, Thursday. Open Jan. 23.", "closed", jan(22)),
    # Posted on a Sunday: tomorrow is Monday, a school day to run from.
    Row("Closed tomorrow, Tuesday and Wednesday", "closed", jan(26, 27, 28), posted=SUN),
    Row("Closed tomorrow, Monday and Tuesday", "closed", jan(26, 27), posted=SUN),
    # What follows the list leaves it its days: a cause, an audience, an open office.
    Row("Closed today, Thursday & Friday due to ice storm", "closed", jan(21, 22, 23)),
    Row("Closed today, Thursday and Friday (snow)", "closed", jan(21, 22, 23)),
    Row("Closed today, Thursday and Friday for students", "closed", jan(21, 22, 23)),
    Row("Closed today, Thursday and Friday - offices open", "closed", jan(21, 22, 23)),
    Row("Closed today, tomorrow and Friday - offices open", "closed", jan(21, 22, 23)),
]

MISMATCHES = [
    Row("Closed today, Friday and Monday", "other", ()),  # Thursday skipped
    Row("Closed today, Thursday and Saturday", "other", ()),  # a weekend day in the run
    Row("Closed tomorrow, Monday and Tuesday", "other", ()),  # Friday skipped
    Row("No school today, Friday or Monday", "other", ()),
    Row("Closed today, Saturday and Monday", "other", (), posted=FRI),
    # One day named two ways that disagree: a restatement, not a list.
    Row("Closed today, Thursday", "other", ()),
    Row("Closed today, Friday", "other", ()),
    Row("Closed tomorrow, Friday", "other", ()),
    # A relative day on a weekend starts no run of school days.
    Row("Closed tomorrow, Monday and Tuesday", "other", (), posted=FRI),
    Row("Closed tomorrow, Monday and Tuesday", "other", (), posted=FRI_EVENING),
    Row("No school tomorrow, Monday or Tuesday", "other", (), posted=FRI_EVENING),
    Row("2 hour delay tomorrow, Monday and Tuesday", "other", (), posted=FRI_EVENING),
    Row("Closed today, Monday and Tuesday", "other", (), posted=SAT),
    Row("Closed tomorrow, Monday and Tuesday", "other", (), posted=SAT),
    Row("No school today, Monday or Tuesday", "other", (), posted=SAT),
    Row("2 hour delay today, Monday and Tuesday", "other", (), posted=SAT),
    Row("Closed today, Monday and Tuesday", "other", (), posted=SUN),
    Row("No school today, Monday or Tuesday", "other", (), posted=SUN),
    Row("2 hour delay today, Monday and Tuesday", "other", (), posted=SUN),
    Row("Closed tomorrow, Monday and Tuesday", "other", (), posted=SAT_NIGHT_MARCH),
]

# A weekday after "today" or "tomorrow" with anything but a plain comma between them names
# the day again: when it disagrees, the text is a mismatch, whatever list follows it.
RESTATED = [
    Row("Closed today (Thursday), Friday", "other", ()),
    Row("Closed today (Thursday) and Friday", "other", ()),
    Row("Closed today (Thursday), Friday, and Monday", "other", ()),
    Row("Closed today (Thurs.), Friday and Monday", "other", ()),
    Row("Closed today [Thursday], Friday", "other", ()),
    Row("Closed today [Thursday] and Friday", "other", ()),
    Row("Closed today/Thursday and Friday", "other", ()),
    Row("Closed today: Thursday and Friday", "other", ()),
    Row("Closed today Thursday and Friday", "other", ()),
    Row("Closed today Thursday, Friday", "other", ()),
    Row("Closed today - Thursday - and Friday", "other", ()),
    # A dash names the day again as a colon does.
    Row("Closed today - Thursday and Friday", "other", ()),
    Row("Closed today \u2013 Thursday and Friday", "other", ()),
    Row("Closed today \u2014 Thursday and Friday", "other", ()),
    Row("Closed today -- Thursday and Friday", "other", ()),
    Row("No school today - Thursday and Friday", "other", ()),
    Row("2 hour delay today - Thursday and Friday", "other", ()),
    Row("Closed tomorrow - Friday and Monday", "other", ()),
    Row("Closed today - Jan 22 and 23", "other", ()),
    Row("Closed today ( Thurs ) & Fri", "other", ()),
    Row("2 hour delay today (Thursday) and Friday", "other", ()),
    Row("NTI today (Thursday) and Friday", "other", ()),
    Row("Closed tomorrow (Friday) and Monday", "other", ()),
    Row("Closed tomorrow (Friday), Monday and Tuesday", "other", ()),
    Row("Closed tomorrow - Friday - and Monday", "other", ()),
    Row("Closed tomorrow [Fri] and Monday", "other", ()),
    Row("No school tomorrow (Fri.) or Monday", "other", ()),
    Row("Closed today (Friday), Monday and Tuesday", "other", (), posted=THU),
    Row("Closed today (Thursday)", "other", ()),
    Row("Closed today Thursday", "other", ()),
]
# ... and when it agrees, the days are the restated day and the list after it.
RESTATED_AGREEING = [
    Row("Closed tomorrow (Thursday) and Friday", "closed", jan(22, 23)),
    Row("Closed tomorrow (Thursday), Friday", "closed", jan(22, 23)),
    Row("Closed tomorrow ( Thursday ) and Friday", "closed", jan(22, 23)),
    Row("Closed tmrw (Thurs) & Fri", "closed", jan(22, 23)),
    Row("Closed tomorrow [Thursday] and Friday", "closed", jan(22, 23)),
    Row("Closed tomorrow/Thursday and Friday", "closed", jan(22, 23)),
    Row("Closed tomorrow Thursday and Friday", "closed", jan(22, 23)),
    Row("Closed today (Wednesday), Thursday and Friday", "closed", jan(21, 22, 23)),
    Row("Closed tomorrow (Thursday)", "closed", jan(22)),
    Row("Closed tomorrow - Thursday and Friday", "closed", jan(22, 23)),
    Row("Closed today - Thursday and Friday", "closed", jan(22, 23), posted=THU),
    Row("Closed today - Wednesday and Thursday", "closed", jan(21, 22)),
    Row("Closed tomorrow - Jan 22 and 23", "closed", jan(22, 23)),
    # A word that adds the days after the dash lists them.
    Row("Closed today - also Thursday and Friday", "closed", jan(21, 22, 23)),
]

# A led list beside a word that school is open on one of its days, anywhere in the text.
OPENED = [
    "Closed today, Thursday and Friday. Open Friday.",
    "Closed today, Thursday and Friday. Friday: regular schedule",
    "Closed today, Thursday and Friday. Friday: open",
    "Closed today, Thursday and Friday. Thursday on time.",
    "Closed today, Thursday and Friday. We will reopen Friday.",
    "Closed today, Thursday and Friday; classes resume Friday",
    "Closed today, Thursday and Friday. Update: open Friday",
    "Open Friday. Closed today, Thursday and Friday.",
    "NTI today, Thursday and Friday. Open Friday.",
]

# Words after the list that could take its last days: no status is said for sure.
CARRIED_AFTER = [
    " open", " regular schedule", " on time", " normal", " as scheduled", " regular day",
    " - normal", ", regular day", " virtual", " will be virtual", " remote learning", " NTI",
    " e-learning", " 2 hour delay", " - 2 hour delay", ", 2 hour delay", " delayed",
    " late start", " half day", " early release", " early dismissal", " 2 hours late",
    " 2 hour delay possible", " will be announced", " updates to follow", " staff report",
    " nights",
]  # fmt: skip
CARRIED = [
    *(f"Closed today, Thursday and Friday{after}" for after in CARRIED_AFTER),
    *(f"Closed today, tomorrow and Friday{after}" for after in CARRIED_AFTER),
    "NTI today, Thursday and Friday closed",
    "NTI today, tomorrow and Friday closed",
    "2 hour delay today, Thursday and Friday closed",
    "2 hour delay today, tomorrow and Friday closed",
    "2 hour delay today, Thursday and Friday - closed",
    "Virtual today, Thursday and Friday closed",
    "No school today, tomorrow and Friday - open",
    "Closed this afternoon, Thursday and Friday",
    "Closed this morning, Thursday and Friday",
    "Closed Wednesday, Thursday and Friday open",
    "Closed Wednesday, Thursday and Friday virtual",
    "Closed Wednesday, Thursday and Friday 2 hour delay",
    "Closed today, tomorrow open",
    "Closed today, tomorrow 2 hour delay",
    "Closed today and tomorrow - 2 hour delay",
    "Closed today through Thursday, Friday open",
]

# A day right after "not" is not the status's; a status left with no day says nothing sure.
DENIED = [
    Row("Closed today and not tomorrow", "closed", jan(21)),
    Row("Closed today not tomorrow", "closed", jan(21)),
    Row("Closed today - not tomorrow", "closed", jan(21)),
    Row("Closed today, but not tomorrow", "closed", jan(21)),
    Row("2 hour delay today not tomorrow", "delayed", jan(21), delay=120),
    Row("No school Thursday and Friday not Monday", "closed", jan(22, 23)),
    Row("Closed Wednesday, Thursday not Friday", "closed", jan(21, 22)),
    Row("Closed today, Thursday not Friday", "other", ()),  # (today is not Thursday)
    Row("No school not Monday", "other", ()),
    Row("Closed - not tomorrow", "other", ()),
]


@pytest.mark.parametrize("case", LISTS, ids=lambda case: case.text)
def test_a_relative_day_leading_a_run_of_weekdays_lists_them(case: Row) -> None:
    result = parse_status(case.text, posted_at=case.posted, tz=TZ)
    assert result.kind == case.kind
    assert result.dates == case.dates
    assert result.delay_minutes == case.delay
    assert result.confidence >= 0.9
    assert "date_mismatch" not in result.notes


def test_a_led_list_keeps_its_days_beside_a_later_weekday() -> None:
    # A weekday named later places the days before it no later than itself: the run stands.
    result = parse_status(
        "Closed today, Thursday and Friday; 2 hour delay Monday", posted_at=WED, tz=TZ
    )
    assert [(entry.kind, entry.dates) for entry in result.schedule] == [
        ("closed", jan(21, 22, 23)),
        ("delayed", jan(26)),
    ]


@pytest.mark.parametrize("case", MISMATCHES, ids=lambda case: f"{case.text} @ {case.posted}")
def test_days_that_make_no_run_stay_a_mismatch(case: Row) -> None:
    result = parse_status(case.text, posted_at=case.posted, tz=TZ)
    assert result.kind == "other"
    assert result.dates == ()
    assert result.confidence <= 0.3


@pytest.mark.parametrize("case", RESTATED, ids=lambda case: f"{case.text} @ {case.posted}")
def test_a_weekday_restating_the_lead_is_no_list(case: Row) -> None:
    result = parse_status(case.text, posted_at=case.posted, tz=TZ)
    assert result.kind == "other"
    assert result.dates == ()
    assert result.confidence <= 0.3
    assert "date_mismatch" in result.notes


@pytest.mark.parametrize("case", RESTATED_AGREEING, ids=lambda case: case.text)
def test_a_weekday_restating_the_lead_as_it_is_keeps_the_list(case: Row) -> None:
    result = parse_status(case.text, posted_at=case.posted, tz=TZ)
    assert (result.kind, result.dates, result.confidence) == (case.kind, case.dates, 0.95)


@pytest.mark.parametrize("text", OPENED)
def test_a_led_list_with_an_open_day_anywhere_says_no_status(text: str) -> None:
    result = parse_status(text, posted_at=WED, tz=TZ)
    assert result.kind == "other"
    assert result.dates == ()
    assert result.confidence <= 0.3
    assert "ambiguous" in result.notes


def test_a_led_list_keeps_its_days_beside_an_open_day_it_does_not_name() -> None:
    for text in (
        "Closed today, Thursday and Friday. Open Monday.",
        "Closed today, Thursday and Friday; reopening Monday",
    ):
        result = parse_status(text, posted_at=WED, tz=TZ)
        assert (result.kind, result.dates, result.confidence) == ("closed", jan(21, 22, 23), 0.95)


@pytest.mark.parametrize("text", CARRIED)
def test_a_list_whose_last_days_other_words_could_take_says_no_status(text: str) -> None:
    for posted in (WED, WED_EVENING):
        result = parse_status(text, posted_at=posted, tz=TZ)
        assert result.kind == "other"
        assert result.dates == ()
        assert result.confidence <= 0.3
        assert "ambiguous" in result.notes or "hedged" in result.notes


@pytest.mark.parametrize("case", DENIED, ids=lambda case: case.text)
def test_a_day_after_not_is_left_out(case: Row) -> None:
    result = parse_status(case.text, posted_at=case.posted, tz=TZ)
    assert result.kind == case.kind
    assert result.dates == case.dates
    assert result.delay_minutes == case.delay
    if case.kind == "other":
        assert result.confidence <= 0.3
    else:
        assert result.confidence == 0.95


def test_words_that_add_to_a_list_or_name_their_own_day_leave_it_its_days() -> None:
    def schedule(text: str) -> list[tuple[str, tuple[date, ...]]]:
        result = parse_status(text, posted_at=WED, tz=TZ)
        assert result.confidence >= 0.9
        return [(entry.kind, entry.dates) for entry in result.schedule]

    assert schedule("Closed today, Thursday and Friday 2 hour delay Monday") == [
        ("closed", jan(21, 22, 23)),
        ("delayed", jan(26)),
    ]
    assert schedule("Closed today and tomorrow, 2 hour delay Friday") == [
        ("closed", jan(21, 22)),
        ("delayed", jan(23)),
    ]
    assert schedule("Tuesday and Wednesday - closed, Thursday - 2 hour delay") == [
        ("closed", jan(20, 21)),
        ("delayed", jan(22)),
    ]
    assert schedule("No school today and tomorrow - snow days") == [("closed", jan(21, 22))]
    assert schedule("Closed today and tomorrow, NTI days") == [("remote", jan(21, 22))]
    assert schedule("Closed today and tomorrow reopening Friday") == [("closed", jan(21, 22))]
    assert schedule("2 hour delay today and tomorrow with normal dismissal") == [
        ("delayed", jan(21, 22))
    ]
    assert schedule("2 hour delay Thursday and Friday morning") == [("delayed", jan(22, 23))]
    assert schedule("Closed today and tomorrow and all evening activities") == [
        ("closed", jan(21, 22))
    ]
    assert schedule("Closed today and tomorrow including evening activities") == [
        ("closed", jan(21, 22))
    ]
    assert schedule("Closed today and tomorrow, offices open regular hours") == [
        ("closed", jan(21, 22))
    ]
    # (A judgment call, as it was: "no in-person classes" does not say what is held.)
    result = parse_status(
        "Virtual learning today and tomorrow - no in-person classes", posted_at=WED, tz=TZ
    )
    assert (result.kind, result.dates, result.confidence) == ("remote", jan(21, 22), 0.8)


WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def school_days_after(day: date, count: int) -> list[date]:
    """The ``count`` school days after ``day``, in order."""
    found: list[date] = []
    while len(found) < count:
        day += timedelta(days=1)
        if day.weekday() < 5:
            found.append(day)
    return found


# Posted on each school day of a week, in the morning.
POSTINGS = [datetime(2026, 1, 19 + offset, 7, 0, tzinfo=ZONE) for offset in range(5)]


@settings(max_examples=200, deadline=None)
@given(
    posted=st.sampled_from(POSTINGS),
    relative=st.sampled_from(("today", "tomorrow")),
    count=st.integers(2, 3),
    joiner=st.sampled_from((" and ", ", and ", " or ", ", ")),
    skip=st.booleans(),
)
def test_a_led_list_is_its_run_of_days_and_a_list_with_a_gap_is_unclear(
    posted: datetime, relative: str, count: int, joiner: str, skip: bool
) -> None:
    start = posted.date() + timedelta(days=0 if relative == "today" else 1)
    if start.weekday() >= 5:
        # Tomorrow is a Saturday: no school day to run from, so no run, with a gap or not.
        names = [WEEKDAYS[day.weekday()] for day in school_days_after(start, count + 1)]
        text = f"Closed {relative}, {', '.join(names[:-1])}{joiner}{names[-1]}"
        result = parse_status(text, posted_at=posted, tz=TZ)
        assert result.kind == "other"
        assert result.confidence <= 0.3
        return
    following = school_days_after(start, count + 1)
    named = following[1:] if skip else following[:count]  # (with a gap: a day left out)
    if not skip and named[0] == start:
        return  # (the weekday after "tomorrow" restates it: a list of its own kind)
    names = [WEEKDAYS[day.weekday()] for day in named]
    text = f"Closed {relative}, {', '.join(names[:-1])}{joiner}{names[-1]}"
    result = parse_status(text, posted_at=posted, tz=TZ)
    if skip or "or" in joiner.split():
        # A gap, or the last day one of two ("Closed today, Thursday or Friday"): no status for
        # sure. (After "no" the days are every one of them: see the rows above.)
        assert result.kind == "other"
        assert result.confidence <= 0.3
    else:
        assert result.kind == "closed"
        assert result.dates == (start, *named)


# Posted at any time of day, any day of a school week, or on the weekend after it.
ANY_POSTING = st.builds(
    lambda day, hour: datetime(2026, 1, day, hour, 0, tzinfo=ZONE),
    st.integers(19, 25),
    st.sampled_from((6, 9, 13, 19, 22)),
)
LEADS = {
    "closed": ("Closed", "No school", "Classes cancelled", "Snow day"),
    "remote": ("Virtual", "NTI", "Remote learning", "eLearning"),
    "delayed": ("2 hour delay", "Two-hour delay", "Late start"),
}
# Words after the list, by the kinds whose days they could take, with the joins they can
# follow (a status of another kind after a mark; an open word or a hedge anywhere).
TRAILING = {
    "closed": ("closed", "no school"),
    "remote": ("virtual", "NTI", "e-learning"),
    "delayed": ("2 hour delay", "delayed", "late start"),
    "early_dismissal": ("early release", "early dismissal"),
    "open": ("open", "on time", "regular schedule", "as scheduled", "normal"),
    "hedge": ("possible", "TBD", "likely", "will be announced"),
}


@settings(max_examples=300, deadline=None)
@given(
    posted=ANY_POSTING,
    lead_kind=st.sampled_from(sorted(LEADS)),
    lead_index=st.integers(0, 3),
    days=st.sampled_from(
        (
            "today, Thursday and Friday",
            "today, tomorrow and Friday",
            "tomorrow, Friday and Monday",
            "today and tomorrow",
            "Wednesday, Thursday and Friday",
            "today, Thursday or Friday",
        )
    ),
    trailing_kind=st.sampled_from(sorted(TRAILING)),
    trailing_index=st.integers(0, 4),
    joiner=st.sampled_from((" ", " - ", ", ")),
)
def test_a_list_followed_by_a_word_that_could_take_its_days_is_never_a_confident_status(  # noqa: PLR0913, PLR0917
    posted: datetime,
    lead_kind: str,
    lead_index: int,
    days: str,
    trailing_kind: str,
    trailing_index: int,
    joiner: str,
) -> None:
    if trailing_kind == lead_kind:
        return  # (a status of the same kind restates the list's)
    if joiner != " " and {lead_kind, trailing_kind} == {"closed", "remote"}:
        return  # (after a mark, a remote day adds to a closure: "Closed today - NTI")
    if joiner != " " and trailing_kind == "hedge":
        return  # (a hedge in a clause of its own hedges the status: see the hedge tests)
    leads, trailing = LEADS[lead_kind], TRAILING[trailing_kind]
    lead = leads[lead_index % len(leads)]
    word = trailing[trailing_index % len(trailing)]
    text = f"{lead} {days}{joiner}{word}"
    result = parse_status(text, posted_at=posted, tz=TZ)
    assert result.kind == "other", text
    assert result.confidence <= 0.3, text


# The ways to name a relative day again that are no list's comma: "today (Thursday)",
# "today [Thursday]", "today/Thursday", "today: Thursday", "today Thursday".
RESTATING_JOINS = (("(", ")"), ("[", "]"), ("/", ""), (": ", ""), (" ", ""), (" (", ")"))
# As ANY_POSTING, and overnight too, when "tomorrow" can mean the day that has begun.
ANY_HOUR_POSTING = st.builds(
    lambda day, hour: datetime(2026, 1, day, hour, 0, tzinfo=ZONE),
    st.integers(19, 25),
    st.sampled_from((1, 6, 9, 13, 19, 22)),
)


@settings(max_examples=400, deadline=None)
@given(
    posted=ANY_HOUR_POSTING,
    relative=st.sampled_from(("today", "tomorrow")),
    join=st.sampled_from(RESTATING_JOINS),
    named=st.sampled_from(WEEKDAYS[:5]),
    tail=st.lists(st.sampled_from(WEEKDAYS[:5]), min_size=1, max_size=2),
    joiner=st.sampled_from((" and ", ", ", ", and ", " or ")),
    lead=st.sampled_from(("Closed", "No school", "2 hour delay", "NTI")),
)
def test_a_weekday_restating_a_relative_day_never_makes_a_list_of_the_wrong_days(  # noqa: PLR0913, PLR0917
    posted: datetime,
    relative: str,
    join: tuple[str, str],
    named: str,
    tail: list[str],
    joiner: str,
    lead: str,
) -> None:
    opening, closing = join
    text = f"{lead} {relative}{opening}{named}{closing}"
    text += joiner + tail[0] if len(tail) == 1 else f", {tail[0]}{joiner}{tail[1]}"
    result = parse_status(text, posted_at=posted, tz=TZ)
    alone = parse_status(f"{lead} {relative}", posted_at=posted, tz=TZ)
    day = alone.dates[0] if alone.dates else None
    if day is not None and WEEKDAYS[day.weekday()] == named:
        return  # (the weekday agrees: "tomorrow (Thursday) and Friday" lists both)
    # The weekday names the relative day again and disagrees with it: no day is trusted, and
    # least of all the relative day and the weekdays after it read as one list.
    if result.kind != "other":
        assert result.confidence < 0.7 or day not in result.dates, text
