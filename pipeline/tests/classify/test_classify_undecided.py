"""A status the text says is undecided, only possible, or one of two: no status for sure.

Every text here is a phrasing pattern written for these tests, not a claim
about a real school. Unless a row says otherwise it is posted at 6 a.m. on
Wednesday 21 January 2026 in Chicago, so "today" is Wednesday the 21st,
"tomorrow" Thursday the 22nd and "Friday" the 23rd.

A status that has not been decided ("Closing tomorrow has not been decided"),
that is not ruled out ("... is not out of the question"), that is one possibility
or option ("Closing tomorrow is a possibility", "... is an option"), that is
predicted ("Predicted school closure tomorrow", "Closure predicted for
tomorrow"), that is one of two statuses ("Either a delay or a closure
tomorrow"), or whose day is one of two ("Closed tomorrow or Friday", "Closed
today, Thursday or Friday") states nothing for sure: the listing is ``other``
at 0.3. After "no" the days joined by "or" are every one of them ("No school
tomorrow or Friday": no school on either), and a status of its own beside such
words stands ("Closed tomorrow; meals are an option").

A status stated beside a later one of another kind that is only possible and
names no day ("2 hour delay tomorrow. Possible closure.", "... A closure is a
possibility.", "... possibly developing into a closure", "2 Hours Late.
Possibility of closure") says nothing sure of the stated status's day either:
``other`` at 0.3, as a change to a status only possible is (see
test_classify_changes). A possible status of the same kind, one that can stand
on the same day (a late start and an early dismissal), or one with a day of its
own leaves the stated status as it is.
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


def jan(*days: int) -> tuple[date, ...]:
    return tuple(date(2026, 1, day) for day in days)


UNDECIDED = [
    "Closing tomorrow has not been decided", "Closing tomorrow has not yet been decided",
    "A 2 hour delay tomorrow has not been decided", "NTI day tomorrow has not been decided yet",
    "Closure tomorrow is not out of the question", "Closing tomorrow is not out of the question",
    "Closing tomorrow is a possibility", "Closing tomorrow is an option",
    "Closure is a possibility tomorrow", "A delay tomorrow is a possibility",
    "eLearning day Friday is an option", "Early dismissal today is a possibility",
    "Predicted school closure tomorrow", "Closure predicted for tomorrow",
    "Closed tomorrow (predicted)", "Projected closure tomorrow",
    "Either a delay or a closure tomorrow", "Either a 2 hour delay or closed tomorrow",
    "Either closed or remote learning tomorrow", "Closed tomorrow or Friday",
    "Closed Thursday or Friday", "2 hour delay tomorrow or Friday", "Closed Thursday, or Friday",
    "NTI day Thursday and/or Friday", "Closed today, Thursday or Friday",
    "Closed tomorrow (Thursday) or Friday", "Closed tomorrow or Friday. Stay tuned.",
]  # fmt: skip


@pytest.mark.parametrize("text", UNDECIDED)
def test_a_status_undecided_possible_or_one_of_two_is_no_status(text: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other"
    assert result.confidence <= 0.3
    assert result.schedule == ()


STANDS = [
    ("No school tomorrow or Friday", "closed", jan(22, 23)),
    ("No school today, Thursday or Friday", "closed", jan(21, 22, 23)),
    ("Closed - no classes today or tomorrow", "closed", jan(21, 22)),
    ("Closed tomorrow; meals are an option", "closed", jan(22)),
    ("Closed tomorrow and Friday", "closed", jan(22, 23)),
    ("Closed tomorrow or until further notice", "closed", jan(22)),
    ("Closing tomorrow has been decided", "closed", jan(22)),
]


@pytest.mark.parametrize(("text", "kind", "dates"), STANDS)
def test_a_status_stated_for_sure_stands(text: str, kind: str, dates: tuple[date, ...]) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == kind
    assert result.dates == dates
    assert result.confidence >= 0.7


STATUSES = (
    "Closing", "Closure", "A closure", "School closure", "A 2 hour delay", "Late start",
    "Early dismissal", "eLearning day", "NTI day", "Remote learning", "Virtual learning",
)  # fmt: skip
DAYS = ("today", "tomorrow", "Friday", "Jan. 22", "on Thursday")
UNDECIDED_PHRASES = (
    "has not been decided", "has not yet been decided", "is not decided yet",
    "is not out of the question", "is a possibility", "is an option", "is undecided",
    "is not yet determined", "is not confirmed", "is possible", "is being considered",
    "is under consideration", "is predicted", "is not ruled out", "is still being decided",
    "is still being discussed", "remains a possibility", "remains an option",
    "is still possible", "has been discussed", "was discussed", "is being determined",
)  # fmt: skip


@settings(max_examples=500, deadline=None)
@given(
    status=st.sampled_from(STATUSES),
    day=st.sampled_from(DAYS),
    phrase=st.sampled_from(UNDECIDED_PHRASES),
    lead=st.sampled_from(("", "Update: ", "Note: ")),
)
def test_a_status_said_undecided_is_never_confident(
    status: str, day: str, phrase: str, lead: str
) -> None:
    text = f"{lead}{status} {day} {phrase}"
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other", text
    assert result.confidence < 0.7, text


@settings(max_examples=400, deadline=None)
@given(
    first=st.sampled_from(
        ("Closed", "2 hour delay", "eLearning day", "Late start", "Early release")
    ),
    second=st.sampled_from(("closed", "a 2 hour delay", "remote learning", "a closure")),
    day=st.sampled_from(DAYS),
    days=st.sampled_from(
        ("tomorrow or Friday", "Thursday or Friday", "today, Thursday or Friday", "Jan. 22 or 23")
    ),
)
def test_alternatives_are_never_confident(first: str, second: str, day: str, days: str) -> None:
    for text in (f"Either {first.lower()} or {second} {day}", f"{first} {days}"):
        result = parse_status(text, posted_at=MORNING, tz=TZ)
        assert result.kind == "other", text
        assert result.confidence < 0.7, text


# A notice that a decision or news about a status is to come, or a status's state still
# pending, names no status: "Closure decision by 5 a.m.", "Closure update by 8 pm",
# "Closure status: TBD". A status stated beside such a heading stands.
NOTICES = [
    "Closure decision by 5 a.m.", "Closure decision: 5 a.m.", "Closure decision tomorrow at 5 a.m.",
    "Closing decision for tomorrow will be made tonight",
    "Closing decision for Thursday will be made tonight", "Closure status for tomorrow: TBD",
    "Closure status: TBD", "Closure update by 8 pm", "Closure update coming at 5 am",
    "Closure announcement tonight", "Closure announcement expected by 9 pm",
    "Closure call by 5 am", "Snow day decision at 5 am", "eLearning decision tonight",
    "Delay decision by 5 am", "Delay update at 5 am", "Delay/closure decision by 5:30 a.m.",
    "Weather closing decisions are made by 5:30 a.m.", "A closure tomorrow has been discussed",
    "Closing tomorrow is still being decided", "Closure tomorrow remains a possibility",
    # A watch for a status, as for a storm, is no status stated.
    "Closure watch for tomorrow", "On closure watch tomorrow", "Delay watch tomorrow",
    "Snow day watch Thursday",
    # A message to come about a status is no status stated.
    "Closure email will be sent by 6 am", "Closure emails go out by 5:30", "Closure text by 5:30",
    "Closure texts will go out by 5 am", "Closure voicemail by 6", "Closure letter to follow",
    "Delay email by 5 am", "Closure robocall by 5:30",
]  # fmt: skip
NOTICE_STANDS = [
    ("Closed UPDATE", "closed", jan(21)),
    # After a length, "report" is what staff do, no notice: the delay stands.
    ("2 hour delay report at 10", "delayed", jan(21)),
    ("2 hour delay, staff report at 9", "delayed", jan(21)),
    # After a word no notice follows, "report" is staff's too.
    ("No school, no personnel report", "closed", jan(21)),
    ("Closed - call by appointment", "closed", jan(21)),
    ("Delay update: 2 hour delay tomorrow", "delayed", jan(22)),
    ("Closure update: closed tomorrow", "closed", jan(22)),
    ("Closure status: closed tomorrow", "closed", jan(22)),
]


@pytest.mark.parametrize("text", NOTICES)
def test_a_notice_of_a_status_to_come_is_no_status(text: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other"
    assert result.confidence <= 0.3


@pytest.mark.parametrize(("text", "kind", "dates"), NOTICE_STANDS)
def test_a_status_beside_a_notice_s_words_stands(
    text: str, kind: str, dates: tuple[date, ...]
) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == kind
    assert result.dates == dates
    assert result.confidence >= 0.7


@settings(max_examples=400, deadline=None)
@given(
    status=st.sampled_from(
        ("Closure", "Closing", "Delay", "Snow day", "eLearning day", "School closure",
         "Early dismissal", "2 hour delay", "Remote learning", "Late start")
    ),
    noun=st.sampled_from(
        ("decision", "update", "announcement", "call", "decisions", "watch", "email", "emails",
         "text", "texts", "voicemail", "letter", "robocall", "tweet")
    ),
    when=st.sampled_from(
        ("by 5 am", "at 5 a.m.", "tonight", "tomorrow at 5 am", "by 8 pm", "expected by 9 pm",
         "coming at 5 am", "will be made tonight", "for tomorrow will be made by 9 pm")
    ),
    lead=st.sampled_from(("", "The ", "Our ")),
)  # fmt: skip
def test_a_notice_of_a_status_to_come_is_never_confident(
    status: str, noun: str, when: str, lead: str
) -> None:
    text = f"{lead}{status} {noun} {when}"
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other" or result.confidence < 0.7, text


@settings(max_examples=300, deadline=None)
@given(
    status=st.sampled_from(
        ("Closure", "Closing", "Delay", "Snow day", "eLearning day", "School closure",
         "Early dismissal", "Early release", "Remote learning", "Late start")
    ),
    noun=st.sampled_from(("report", "reports")),
    when=st.sampled_from(
        ("at 10", "at 9:30", "at 11 am", "at 10:00 a.m.", "by 5 am", "by 5:30 a.m.",
         "at 10 tomorrow", "go out by 6")
    ),
    lead=st.sampled_from(("", "The ", "Our ")),
)  # fmt: skip
def test_a_report_of_a_status_to_come_is_never_confident(
    status: str, noun: str, when: str, lead: str
) -> None:
    # Invariant: "report" right after a status with no length is a notice of it, and the
    # report's own time ("Closure report at 10") is the notice's: no status at 0.7 or more.
    text = f"{lead}{status} {noun} {when}"
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other" or result.confidence < 0.7, (text, result)


# A watch for a status beside a stated status: of another kind, it leaves the stated status in
# doubt, as a status only possible does ("2 hour delay tomorrow, possibility of closure"),
# whichever comes first; of the same kind, the stated status stands, with no doubt about it.
# A watch alone stays a notice (NOTICES above), and so does one beside a status denied.
WATCH_DOUBTS = [
    "Two hour delay tomorrow - closure watch in effect", "Closure watch: 2 hour delay tomorrow",
    "2 hour delay tomorrow; on closure watch", "Delay watch: Closed tomorrow",
    "Closure watch: Early dismissal at 1:00 today", "Closure watch: 2 hour delay Fri 1/23",
    "Closed tomorrow; remote learning watch in effect", "Remote learning watch: Closed tomorrow",
    "2 hour delay tomorrow; closing watch in effect",
    "2 hour delay tomorrow; closure watch for tomorrow",
    "Delay or closure watch for tomorrow", "No delay; closure watch for tomorrow",
    "Closure watch for tomorrow. No decision on a delay yet.",
]  # fmt: skip
WATCH_STANDS = [
    ("Closed tomorrow - closure watch", "closed", jan(22)),
    ("Closure watch: closed tomorrow", "closed", jan(22)),
    ("Closed tomorrow; closure watch in effect", "closed", jan(22)),
    ("Snow day watch: no school tomorrow", "closed", jan(22)),
    ("Delay watch: 2 hour delay tomorrow", "delayed", jan(22)),
    ("2 hour delay tomorrow - delay watch", "delayed", jan(22)),
    ("eLearning day watch: remote learning tomorrow", "remote", jan(22)),
]


@pytest.mark.parametrize("text", WATCH_DOUBTS)
def test_a_status_beside_a_watch_for_another_is_no_status_for_sure(text: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other"
    assert result.confidence <= 0.3


@pytest.mark.parametrize(("text", "kind", "dates"), WATCH_STANDS)
def test_a_status_beside_a_watch_for_its_own_kind_stands(
    text: str, kind: str, dates: tuple[date, ...]
) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert (result.kind, result.dates) == (kind, dates)
    assert result.confidence >= 0.9
    assert "hedged" not in result.notes


WATCHED_KINDS = {
    "closure": "closed", "school closure": "closed", "snow day": "closed", "delay": "delayed",
    "late start": "delayed", "early dismissal": "early_dismissal", "remote learning": "remote",
    "elearning day": "remote",
}  # fmt: skip
STATED_KINDS = {
    "Closed tomorrow": "closed", "No school tomorrow": "closed", "2 hour delay tomorrow": "delayed",
    "Early dismissal at 1:00 tomorrow": "early_dismissal", "Remote learning tomorrow": "remote",
    "eLearning day tomorrow": "remote",
}  # fmt: skip
WATCH_FORMS = (
    "{s}; {w} watch in effect", "{W} watch: {s}", "{s} - on {w} watch", "{W} watch in effect. {s}.",
    "{s}, {w} watches posted", "{s}. {W} watch for tomorrow.",
)  # fmt: skip


@settings(max_examples=400, deadline=None)
@given(
    watched=st.sampled_from(sorted(WATCHED_KINDS)),
    stated=st.sampled_from(sorted(STATED_KINDS)),
    form=st.sampled_from(WATCH_FORMS),
)
def test_a_watch_beside_a_status_never_leaves_a_sure_status_in_doubt(
    watched: str, stated: str, form: str
) -> None:
    # Invariant: beside a watch for another kind (but a late start beside an early dismissal,
    # which share a day), a stated status is never confident; beside one for its own kind, it
    # is never confident with a "hedged" note about that kind and day.
    text = form.format(s=stated, w=watched, W=watched.capitalize())
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    kind, own = WATCHED_KINDS[watched], STATED_KINDS[stated]
    alongside = {kind, own} == {"delayed", "early_dismissal"}
    if kind != own and not alongside:
        assert result.confidence < 0.7, (text, result)
    elif kind == own and result.confidence >= 0.7:
        assert "hedged" not in result.notes, (text, result)


# What a status means, as a page of answers says, is no status: "A 2 hour delay means school
# starts at 10:00", "What does a 2 hour delay mean? School starts at 10."
DEFINITIONS = [
    "A 2 hour delay means school starts at 10:00", "A delay means buses run 2 hours late",
    "A closure means no school for students", "Closure means all activities are cancelled",
    "Delayed start means classes begin at 10",
    "What does a 2 hour delay mean? School starts at 10.",
]  # fmt: skip


@pytest.mark.parametrize("text", DEFINITIONS)
def test_what_a_status_means_is_no_status(text: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other"
    assert result.confidence <= 0.3


@settings(max_examples=300, deadline=None)
@given(
    status=st.sampled_from(
        ("A 2 hour delay", "A delay", "A closure", "Closure", "Delayed start", "A snow day",
         "An eLearning day", "Early release", "A late start", "An NTI day")
    ),
    meaning=st.sampled_from(
        ("school starts at 10:00", "no school for students", "buses run 2 hours late",
         "classes begin at 10", "students learn from home", "dismissal at 1:00 pm",
         "all activities are cancelled")
    ),
    asked=st.booleans(),
)  # fmt: skip
def test_what_a_status_means_is_never_confident(status: str, meaning: str, asked: bool) -> None:
    if asked:
        noun = status.split(" ", 1)[1] if status.startswith(("A ", "An ")) else status
        text = f"What does a {noun.lower()} mean? {meaning[0].upper()}{meaning[1:]}."
    else:
        text = f"{status} means {meaning}"
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other" or result.confidence < 0.7, text


# A stated status, then a status of another kind only possible that names no day.
MAYBE_REPLACED = [
    "2 hour delay tomorrow. Possible closure.",
    "2 hour delay tomorrow. A closure is a possibility.",
    "2 hour delay tomorrow, possibly developing into a closure.",
    "2 hour delay today. Closure possible.", "2 hour delay today; a closure is possible",
    "2 hour delay today. Closure is likely.", "2 hour delay today. A closure may follow.",
    "2 Hours Late. possibility of closure", "2 hour delay. Chance of a closure later.",
    "Remote learning today. Possible closure.", "Early dismissal at 1:00 today. Possible closure.",
    "Closed today. Possible eLearning day.",
]  # fmt: skip


@pytest.mark.parametrize("text", MAYBE_REPLACED)
def test_a_status_another_may_replace_is_no_status_for_sure(text: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other"
    assert result.confidence <= 0.3
    assert "hedged" in result.notes


NOT_REPLACED = [
    ("2 hour delay today. Possible early dismissal.", "delayed", jan(21)),
    ("Closed today. Possible closure tomorrow.", "closed", jan(21)),
    ("Closed today. Possibility of closure tomorrow.", "closed", jan(21)),
    ("2 hour delay today. Possible closure tomorrow.", "delayed", jan(21)),
    ("Closed today. Rumors of a delay are false.", "closed", jan(21)),
    ("Closed today due to the possibility of flooding", "closed", jan(21)),
]


@pytest.mark.parametrize(("text", "kind", "dates"), NOT_REPLACED)
def test_a_possible_status_that_replaces_none_leaves_the_status(
    text: str, kind: str, dates: tuple[date, ...]
) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert (result.kind, result.dates) == (kind, dates)
    assert result.confidence >= 0.7


_STATED = {
    "delayed": ("2 hour delay", "Late start", "Delayed opening"),
    "closed": ("Closed", "No school"),
    "remote": ("Remote learning", "eLearning day"),
    "early_dismissal": ("Early dismissal at 1:00", "Early release"),
}
# A status of each kind as it follows "possible", and with its article.
_POSSIBLE = {
    "delayed": ("delay", "a delay"),
    "closed": ("closure", "a closure"),
    "remote": ("eLearning day", "an eLearning day"),
    "early_dismissal": ("early dismissal", "an early dismissal"),
}


@settings(max_examples=400, deadline=None)
@given(
    stated=st.sampled_from(sorted(_STATED)),
    possible=st.sampled_from(sorted(_POSSIBLE)),
    form=st.sampled_from(
        ("{status}{day}. Possible {bare}.", "{status}{day}. {Article} is a possibility.",
         "{status}{day}, possibly developing into {article}.",
         "{status}{day}. {Article} is likely.", "{status}{day}. Possibility of {article}.",
         "{status}{day}. Chance of {article}.")
    ),
    day=st.sampled_from((" today", " tomorrow", " Thursday", "")),
    pick=st.integers(min_value=0, max_value=2),
)  # fmt: skip
def test_a_status_another_only_possible_may_replace_is_never_confident(
    stated: str, possible: str, form: str, day: str, pick: int
) -> None:
    status = _STATED[stated][pick % len(_STATED[stated])]
    bare, article = _POSSIBLE[possible]
    text = form.format(
        status=status, day=day, bare=bare, article=article,
        Article=article[0].upper() + article[1:],
    )  # fmt: skip
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    if stated != possible and {stated, possible} != {"delayed", "early_dismissal"}:
        assert result.kind == "other" or result.confidence < 0.7, text
    elif result.confidence >= 0.7:
        assert result.kind == stated, text


# A status written as a field's label ("Closure status:", "Closure:", "Snow day alert:",
# "Closed schools:") is answered by what follows its colon: an answer that says no gives no
# status ("negated"), one that says nothing is decided leaves it open ("hedged").
LABEL_NO = [
    "Closure status: open", "Closure Status: OPEN", "School closure status: Open",
    "Weather closure status: open", "Closure status: in session",
    "Closure status: normal schedule", "Closure status: none", "Delay status: on time",
    "Delay status: none", "Closed: 0 schools", "Closed schools: 0", "Delayed: 0 schools",
    "Closure status: regular schedule.", "Delay status: none - buses on time",
]  # fmt: skip
LABEL_OPEN = [
    "Closure: maybe", "Delay: maybe", "2 hour delay: maybe", "Snow day alert: possible",
    "Closure: no decision yet", "Closure tomorrow: no decision yet", "Closure status: pending",
    "Delay status: not decided yet", "Closure update: to be determined",
]  # fmt: skip
# Notice nouns after a status: news of a decision to come, not the status.
NOTICES_SENT = [
    "Closure notice will be sent by 9 pm", "Closure notices go out by 5 am",
    "Closure alert at 5 am", "Closure alerts will be sent by text by 5:30 a.m.",
    "Closure message will go out by 6", "Closure news by 5 am", "Closure report by 5:30 a.m.",
    "Closure reports go out by 6", "Delay report by 5 am", "Closure post by 6 am",
    # The report's own time is the notice's, not a late start.
    "Closure report at 10", "Early dismissal report at 11",
    "Closure details to follow", "Closure updates on our Facebook page",
    "Delay notification by 5 am", "Delay details to follow",
]  # fmt: skip
# The label's answer states the status, or a day heads an answer of its own.
LABEL_STATED = [
    ("Closure status: closed", "closed"), ("Closure status: Closed today", "closed"),
    ("Delay status: 2 hours", "delayed"), ("Closure notice: all schools closed today", "closed"),
    ("Closure alert: schools closed today", "closed"),
    ("Current Status: Closed Tomorrow", "closed"),
]  # fmt: skip


@pytest.mark.parametrize("text", LABEL_NO)
def test_a_label_answered_no_states_no_status(text: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other", text
    assert "negated" in result.notes, text


@pytest.mark.parametrize("text", LABEL_OPEN + NOTICES_SENT)
def test_a_label_left_undecided_or_a_notice_states_no_status(text: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other", text
    assert result.confidence <= 0.3, text


@pytest.mark.parametrize(("text", "kind"), LABEL_STATED)
def test_a_label_answered_with_a_status_states_it(text: str, kind: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == kind, text
    assert result.confidence >= 0.9, text


@settings(max_examples=400, deadline=None)
@given(
    label=st.sampled_from(("Closure", "Closure status", "School closure status", "Delay status",
                           "Snow day alert", "Closed", "Closed schools", "2 hour delay",
                           "Closure tomorrow", "Delay")),
    answer=st.sampled_from(("open", "OPEN", "on time", "in session", "normal schedule", "none",
                            "0", "0 schools", "maybe", "possible", "undecided", "no decision yet",
                            "TBD", "pending", "not decided yet")),
    end=st.sampled_from(("", ".", "!", " - more info soon", ";")),
)  # fmt: skip
def test_no_label_answer_that_says_no_or_undecided_gives_a_status(
    label: str, answer: str, end: str
) -> None:
    # Invariant: a status label answered open, on time, none, zero, maybe or undecided gives
    # no status at 0.7 or more.
    text = f"{label}: {answer}{end}"
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other" or result.confidence < 0.7, (text, result)
