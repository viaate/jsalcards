"""The precision gate: a confident result only when every word that bears on it is read.

Every text here is a phrasing pattern written for these tests, not a claim about a
real school; the names are made up from syllables. Unless a row says otherwise it is
posted at 6 a.m. on Wednesday 21 January 2026 in Chicago, so "today" is Wednesday the
21st, "tomorrow" Thursday the 22nd and "Friday" the 23rd.

Each rule of the grammar accounts for the words it reads (see
``snowlight.classify.gate``): status words and their modifiers, days and dates, times
and lengths, a cause to the end of its clause, who is affected (a name too, up to the
noun that ends it), filler, and the statements the parser reads whole. A sentence that
names a status or a day, or opens, holds school, hedges or corrects, and holds a word
left over, gives ``other`` at 0.3 (note ``unread_words``): "Closed tomorrow,
unofficially", "No school Friday - parade". So does a clause after a status that only
hedges it, holds school or corrects it, with no rule that read it: "Closed tomorrow,
decision tonight", "Closed tomorrow, classes will be held", "... - still on". A
sentence that names none of those leaves the result standing ("Stay safe!", "More info
on our website"), and so does a clause about another day ("Closed tomorrow. Friday
TBD.").
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from snowlight.classify import parse_status
from snowlight.classify.gate import (
    CAUSE,
    NAME_END,
    NOTE_SPAN,
    names_read,
    unread_sentence,
    word_class,
)
from snowlight.classify.parse import _forget_words

TZ = "America/Chicago"
ZONE = ZoneInfo(TZ)
WED = datetime(2026, 1, 21, 6, 0, tzinfo=ZONE)


def jan(*days: int) -> tuple[date, ...]:
    return tuple(date(2026, 1, day) for day in days)


# A word no rule reads, in a sentence with a status or a day.
UNREAD = [
    "Closed zorblax tomorrow", "Closed tomorrow, unofficially", "Closed tomorrow, allegedly",
    "NTI day Friday, supposedly", "Closed tomorrow (draft)", "No school Friday - parade",
    "2 hour delay for the yearbook signing", "Early dismissal at 1:00 today, hypothetically",
    "Remote learning tomorrow, sort of", "Closed tomorrow. Friday kinda iffy.",
    "Kubaze closed tomorrow", "Closed Thursday and Friday per the rumor mill grapevine",
    "Late start tomorrow - tentativeish", "Closed today and tomorrow, Friday iffy",
    "Classes cancelled tomorrow for the zombie drill", "Closed tomorrow, LOL",
    "Virtual learning day Friday unless bemuda", "Two hour delay tomorrow, pinky promise",
]  # fmt: skip


@pytest.mark.parametrize("text", UNREAD)
def test_a_word_no_rule_reads_leaves_no_confident_status(text: str) -> None:
    result = parse_status(text, posted_at=WED, tz=TZ)
    assert result.kind == "other"
    assert result.confidence <= 0.3


# A clause after a status that only hedges it, holds school or corrects it: no rule read it.
UNREAD_STATEMENTS = [
    "Closed tomorrow, decision tonight", "Closed today and tomorrow, decision tonight",
    "Closed today and tomorrow. Decision tonight.", "Closed tomorrow, no decision yet",
    "Closed Thursday and Friday, no decision yet", "Closed tomorrow, still on",
    "Closed today and tomorrow - still on", "Closed tomorrow, classes will be held",
    "Closed today and tomorrow, classes will be held", "Closed tomorrow, is a school day",
    "Closed tomorrow, hopefully not", "2 hour delay tomorrow, we hope not",
    "Closed tomorrow - ?", "Closed today, tomorrow either", "Closed today and tomorrow, as planned",
    "Closed today and tomorrow, on schedule", "Closed today and tomorrow, decision at 5am",
    "Closed tomorrow, disregard", "NTI day tomorrow, still deciding",
    "Closed Thursday and Friday - school as usual", "Closed tomorrow, school is on",
    "Closed today and tomorrow - school is on", "Closed tomorrow, or delayed",
    "Closed tomorrow - or not", "Closed tomorrow. Never mind.", "Closed tomorrow - drill",
    "(TODAY) CLOSED ON THURSDAY TOO", "Closed tomorrow, school is open",
    "Closed today and tomorrow, regular schedule", "Closed tomorrow, schools are open",
    "Closed today. Classes on time.", "Closed. School on time.",
    "Closed. Classes will run as scheduled.", "Closed today. Students report as usual.",
    "Closed Thursday and Friday. School will run Friday.",
    # A later sentence, with no day of its own, that holds school or says the post no longer
    # holds, whatever day the status names: it could be about that day.
    "Closed tomorrow. Update: school will be held.",
    "Closed tomorrow. Update: classes will be held.",
    "Closed tomorrow. Update: school is on.", "Closed tomorrow. Update: back on.",
    "Closed tomorrow. Update: change of plans, we will have school.",
    "Closed tomorrow. Change of plans: open.", "Closed tomorrow. That is no longer the case.",
    "Closed tomorrow. This notice is outdated.", "Closed tomorrow. This is outdated.",
    "Closed tomorrow. Not anymore.", "Closed tomorrow. Update: never mind.",
    "Closed tomorrow. School will be in session.",
    "Closed tomorrow. Classes will meet as scheduled.",
    "Closed tomorrow. We will have school.", "Closed tomorrow. There will be school.",
    "Closed tomorrow. School is on as scheduled.", "Closed tomorrow. Open as normal.",
    "Closed tomorrow. Normal day.", "Closed tomorrow. Regular day.",
    "Closed tomorrow. Business as usual.", "Closed tomorrow. Full day of school.",
    "Closed tomorrow. Open.", "Closed. Open.", "2 hour delay tomorrow. School will start on time.",
    "2 hour delay tomorrow. Regular schedule.", "Closed tomorrow. Correction: school will be held.",
    "Closed tomorrow. Update: plans have changed.", "Closed tomorrow. Update: not closed.",
    "Closed Thursday and Friday. No longer closed.", "2 hour delay tomorrow. No longer delayed.",
    "NTI day tomorrow. Update: not an NTI day.",
]  # fmt: skip


@pytest.mark.parametrize("text", UNREAD_STATEMENTS)
def test_a_statement_no_rule_read_leaves_no_confident_status(text: str) -> None:
    result = parse_status(text, posted_at=WED, tz=TZ)
    assert result.kind == "other"
    assert result.confidence <= 0.3


# School said to be held or open beside a status for its day disagrees with it.
HELD_BESIDE = [
    "Closed tomorrow, classes will be held", "Closed tomorrow, school is open",
    "Closed today. Classes on time.", "Closed Thursday and Friday. School will run Friday.",
    "Closed tomorrow. Update: school will be held.", "Closed tomorrow. School will be in session.",
    "Closed tomorrow. We will have school.", "Closed tomorrow. Open.",
    "Closed tomorrow. Update: not closed.", "2 hour delay tomorrow. School will start on time.",
]  # fmt: skip


@pytest.mark.parametrize("text", HELD_BESIDE)
def test_school_held_beside_a_status_for_its_day_is_a_conflict(text: str) -> None:
    result = parse_status(text, posted_at=WED, tz=TZ)
    assert result.kind == "other"
    assert "conflict" in result.notes


# Forms archived listings hold, rephrased: every word is read, so the status stands. Names
# before the noun that ends them, a name's label before a colon, causes, conditions, closers,
# codes and plans, staff and service notes, lengths in words, and statements about other days.
READ_ROWS = [
    ("Closed today. Stay safe and warm!", "closed", jan(21)),
    ("Closed today; more info on our website", "closed", jan(21)),
    ("Closed tomorrow. Thank you for your patience.", "closed", jan(22)),
    ("Closed tomorrow. Check the website for details.", "closed", jan(22)),
    ("Closed tomorrow, Employee Code 2", "closed", jan(22)),
    ("Closed, Code Red", "closed", jan(21)),
    ("Level 3 remote day tomorrow", "remote", jan(22)),
    ("Two Hour Delay, No AM Pre-K", "delayed", jan(21)),
    ("Friday Morning: Two Hour Delay", "delayed", jan(23)),
    ("Closed through at least Friday", "closed", jan(23)),
    ("Current status: closed tomorrow", "closed", jan(22)),
    ("Closed indefinitely", "closed", jan(21)),
    ("Remote learning will continue Thursday", "remote", jan(22)),
    ("Holding virtual classes tomorrow", "remote", jan(22)),
    ("Independent learning day Friday", "remote", jan(23)),
    ("Blizzard bag day tomorrow", "remote", jan(22)),
    ("Closed tomorrow; grab and go meals at the high school", "closed", jan(22)),
    ("Closed today; no worship services", "closed", jan(21)),
    ("Closed today; essential personnel report at 10", "closed", jan(21)),
    ("Delayed 2 hours; liberal leave for staff", "delayed", jan(21)),
    ("Closed tomorrow due to a water main break near Kubaze Road", "closed", jan(22)),
    ("Closed tomorrow out of an abundance of caution", "closed", jan(22)),
    ("Closed tomorrow; if roads are clear we will reopen Friday", "closed", jan(22)),
    ("All Bakuzo schools closed tomorrow", "closed", jan(22)),
    ("Closed tomorrow - Bakuzo Bus Garage open", "closed", jan(22)),
    ("Kubaze Learning Center closed tomorrow", "closed", jan(22)),
    ("Temira State - Bakuzo Campus: Closed", "closed", jan(21)),
    ("2 Hour Delay - Dumi Made Elementary School", "delayed", jan(21)),
    ("Closed tomorrow. Friday TBD.", "closed", jan(22)),
    ("Closed tomorrow, possibly Friday", "closed", jan(22)),
    ("Closed tomorrow, decision about Friday tonight", "closed", jan(22)),
    ("Closed today and Friday, school tomorrow as usual", "closed", jan(21, 23)),
    ("Delayed 2 Hrs, No AM BOCES, Final decision", "delayed", jan(21)),
    ("Closed tomorrow. Status update at 5 AM.", "closed", jan(22)),
    ("Closed tomorrow - stay tuned", "closed", jan(22)),
    ("Closed Thursday and Friday; staff report", "closed", jan(22, 23)),
    ("Closed tomorrow; Kubaze Senior Center will be closed too", "closed", jan(22)),
    ("Closed Thursday; morning Mass cancelled", "closed", jan(22)),
    ("Closed tomorrow; virtual hearings only", "closed", jan(22)),
    ("2 Hour Delay, No AM Kdg", "delayed", jan(21)),
    ("Closed Thursday; Plan B in effect", "closed", jan(22)),
    ("Closed Thursday, Employee Code A", "closed", jan(22)),
    ("Closed today; Sunday worship online", "closed", jan(21)),
    ("Closed today; telehealth appointments only", "closed", jan(21)),
    ("Closed today; no meal delivery", "closed", jan(21)),
    ("Closed today - more info here", "closed", jan(21)),
    ("Closed today. Watch our Facebook page for updates.", "closed", jan(21)),
    ("Closed today, all locations", "closed", jan(21)),
    ("Closed today; essential staff only", "closed", jan(21)),
    ("Closed today; teacher workday optional", "closed", jan(21)),
    ("Delayed 2 hours; buses on snow routes", "delayed", jan(21)),
    ("Three hour delay tomorrow", "delayed", jan(22)),
    ("Closed today; Kubaze Senior Center closed too", "closed", jan(21)),
    ("Bakuzo County Schools: two hour delay", "delayed", jan(21)),
    ("Closed today and tomorrow - Last Updated: 01/21/2026 05:10am", "closed", jan(21, 22)),
    ("Closed today due to icy roads and downed trees", "closed", jan(21)),
    ("Closed today, state of emergency declared", "closed", jan(21)),
    ("Closed today; travel ban in effect", "closed", jan(21)),
    ("Closed tomorrow (For Thu. Jan 22nd)", "closed", jan(22)),
    ("Closed tomorrow - not a drill", "closed", jan(22)),
    # School not held, school held on another day, and something else held or open.
    ("Closed tomorrow. School will not run tomorrow.", "closed", jan(22)),
    ("Closed tomorrow. Other than that, normal schedule", "closed", jan(22)),
    ("Schools closed. District office (Kubaze) open regular hours.", "closed", jan(21)),
    ("Today: school closed. Board of Ed. mtg. will be held as scheduled.", "closed", jan(21)),
    ("Closed tomorrow. School will be held Friday.", "closed", jan(22)),
    ("Closed today. School will be in session tomorrow.", "closed", jan(21)),
    ("Closed tomorrow. Offices open.", "closed", jan(22)),
    ("Closed tomorrow. District offices will be open as normal.", "closed", jan(22)),
    # A status of another kind denied: no news of the status stated.
    ("2 hour delay today. Not closed.", "delayed", jan(21)),
    ("Closed tomorrow. Not delayed.", "closed", jan(22)),
    ("eLearning day tomorrow. Not closed.", "remote", jan(22)),
    # Slots headed by a day in brackets: each slot's status is its own day's.
    ("(TODAY) CLOSED | (TOMORROW) OPEN", "closed", jan(21)),
    ("(TODAY) NTI DAY | (TOMORROW) NTI DAY", "remote", jan(21, 22)),
    ("(TODAY) CLOSED | (TOMORROW) TO BE ANNOUNCED", "closed", jan(21)),
    ("(TODAY) CLOSED | (TOMORROW) OPEN, NO BUSES, STAFF TO REPORT", "closed", jan(21)),
    # Services, places, events and staff, in the other number or spelt a letter off.
    ("Closed until Friday but available by phone and email", "closed", jan(21, 22)),
    ("Closed today. Crisis hotline still available.", "closed", jan(21)),
    ("Remote learning Thursday and Friday. Dorm open Thursday.", "remote", jan(22, 23)),
    ("Closed today; residence halls and dorms open", "closed", jan(21)),
    ("Closed today, no activites", "closed", jan(21)),
    ("Virtual instruction tomorrow, no transporation", "remote", jan(22)),
    ("Closed tomorrow. No preformances or practicies.", "closed", jan(22)),
    ("Closed tomorrow; all meetings/functions cancelled", "closed", jan(22)),
    ("Closed tomorrow; preschool extension cancelled", "closed", jan(22)),
    ("Closed tomorrow; bake sale postponed", "closed", jan(22)),
    ("Closed today; 12 mo. employees report", "closed", jan(21)),
    ("Closed today, mandatory workday for staff", "closed", jan(21)),
    ("Closed tomorrow; morning mass will be celebrated online", "closed", jan(22)),
    ("Comprehensive distance learning tomorrow", "remote", jan(22)),
    ("Closed today; non-essential staff stay home", "closed", jan(21)),
    ("Closed tomorrow; no sanitation pickup", "closed", jan(22)),
    ("Closed tomorrow; nightly activities cancelled", "closed", jan(22)),
    ("Closed today; limited availability by phone", "closed", jan(21)),
    ("Classes online only format tomorrow", "remote", jan(22)),
    ("Closed tomorrow. No programs will occur.", "closed", jan(22)),
    ("Closed today; this closure affects all campuses", "closed", jan(21)),
    ("Closed today; see website for previous services", "closed", jan(21)),
    ("Delayed 2 hours; carline opens at 10:15", "delayed", jan(21)),
    # A cause about something besides the school, and a clause that starts again after one.
    ("Closed today due to bus delays", "closed", jan(21)),
    ("Closed today due to weather and will have a 2 hour delay tomorrow", "closed", jan(21)),
]


@pytest.mark.parametrize(("text", "kind", "dates"), READ_ROWS)
def test_a_listing_whose_words_are_all_read_keeps_its_status(
    text: str, kind: str, dates: tuple[date, ...]
) -> None:
    result = parse_status(text, posted_at=WED, tz=TZ)
    assert result.kind == kind
    assert result.dates == dates
    assert result.confidence >= 0.7
    assert "unread_words" not in result.notes


# A clause that says school is held on a day, or a correction that withdraws one, takes the
# day from the status beside it; a day the text only calls possible is no day of the status.
# (None: no status for sure, ``other`` with a low confidence.)
HELD_AND_CORRECTED = [
    ("Closed today. School tomorrow.", jan(21)),
    ("Closed today; school tomorrow", jan(21)),
    ("Closed today, classes tomorrow", jan(21)),
    ("Closed today. Students tomorrow.", jan(21)),
    ("Closed today. All schools tomorrow.", jan(21)),
    ("Closed Thursday. School Friday.", jan(22)),
    ("No classes Thursday. Classes Friday.", jan(22)),
    ("Closed Thursday 1/22. School Friday 1/23.", jan(22)),
    ("Closed Jan 22. School Jan 23.", jan(22)),
    ("Closed Thursday and Friday. School Friday.", jan(22)),
    ("Closed Thursday and Friday. Friday classes.", jan(22)),
    ("Closed Thursday and Friday. School Monday.", jan(22, 23)),
    ("Closed Thursday and Friday. There will be school Friday.", jan(22)),
    ("Closed Thursday and Friday. Friday school as usual.", jan(22)),
    ("Closed Thursday and Friday. Students report Friday.", jan(22)),
    ("Closed Thursday and Friday. Friday is back on.", jan(22)),
    ("Closed Thursday and Friday. Friday no longer closed.", jan(22)),
    ("Closed today, tomorrow and Friday. Update: disregard Friday.", jan(21, 22)),
    ("Closed today, tomorrow and Friday. Update: Friday was posted in error.", jan(21, 22)),
    ("Closed today, tomorrow and Friday. Update: we will have school Friday.", jan(21, 22)),
    ("Closed today, tomorrow and Friday. Correction: Friday was listed by mistake.", jan(21, 22)),
    ("Closed today through Friday. Update: closed through tomorrow.", jan(21, 22)),
    ("Closed today through Friday. Update: now only through tomorrow.", jan(21, 22)),
    ("Closed tomorrow. Friday also possible.", jan(22)),
    ("Closed today, tomorrow; Friday also possible", jan(21, 22)),
    ("Closed today, tomorrow and Friday. Monday possible.", jan(21, 22, 23)),
    ("Closed today, tomorrow and Friday with Monday possible", jan(21, 22, 23)),
    ("Closed tomorrow. Update: there will be school tomorrow.", None),
    ("Closed tomorrow. Update: we will have school tomorrow.", None),
    ("Closed tomorrow. Update: all buildings open tomorrow for students", None),
    ("Closed tomorrow - FALSE", None),
    ("Closed tomorrow is false", None),
    ("Ignore posts saying we are closed tomorrow", None),
    ("Closed tomorrow. Update: closure notice was a mistake.", None),
    ("Closed today, Thursday and Friday games postponed", None),
    ("Closed today, tomorrow games postponed", None),
    ("Closed today, Thursday and Friday, decision tonight", None),
    ("Closed today, tomorrow - no decision yet", None),
    ("Closed today, tomorrow (still on)", None),
]


@pytest.mark.parametrize(("text", "dates"), HELD_AND_CORRECTED)
def test_school_held_a_correction_or_a_hedged_day_is_read(
    text: str, dates: tuple[date, ...] | None
) -> None:
    result = parse_status(text, posted_at=WED, tz=TZ)
    if dates is None:
        assert result.kind == "other"
        assert result.schedule == ()
    else:
        assert result.kind == "closed"
        assert result.dates == dates
        assert {day for entry in result.schedule for day in entry.dates} == set(dates)


# A status phrase inside a cause that follows its clause's words says why, not what the
# listing's status is.
CAUSED = [
    "Liberal leave tomorrow due to school delays", "Staff report at 10 due to school delays",
    "Schools closed tomorrow due to a training day that will now be virtual",
    "Offices closed tomorrow due to school closures",
    "Closed Thursday because of a power outage that delayed repairs",
]  # fmt: skip


@pytest.mark.parametrize("text", CAUSED)
def test_a_status_phrase_inside_a_cause_is_no_status_of_the_listing(text: str) -> None:
    result = parse_status(text, posted_at=WED, tz=TZ)
    assert result.kind == "other"
    assert result.confidence <= 0.3


# A word the gate reads and one it does not, in the same place: texts that differ only in names
# share an analysis (see parse.canonical), so a word the gate reads is never taken for a name.
SAME_PLACE = [
    ("Closed - BPS", "Closed - Zorblax"),
    ("Closed Jan 22 - BPS", "Closed Jan 22 - Zorblax"),
    ("Closed tomorrow for activites", "Closed tomorrow for zorblaxes"),
    ("Closed tomorrow, open dorm", "Closed tomorrow, open zorb"),
    ("Closed - Lincoln HS", "Closed - Lincoln ZQ"),
]


@pytest.mark.parametrize(("read", "unread"), SAME_PLACE)
def test_a_word_read_and_a_word_unread_never_share_a_reading(read: str, unread: str) -> None:
    _forget_words()
    first = parse_status(read, posted_at=WED, tz=TZ)
    second = parse_status(unread, posted_at=WED, tz=TZ)
    _forget_words()
    assert parse_status(unread, posted_at=WED, tz=TZ) == second
    assert parse_status(read, posted_at=WED, tz=TZ) == first
    assert first.confidence >= 0.7
    assert second.confidence <= 0.3


# A noun of who is affected, a place or a service is read in its other number and spelt one
# letter off; a status, a day or a hedge is read only as it is listed.
@pytest.mark.parametrize(
    "word", ["activites", "transporation", "personel", "preformances", "dorm", "emails"]
)
def test_a_noun_in_its_other_number_or_spelt_a_letter_off_is_read(word: str) -> None:
    assert word_class(word)


@pytest.mark.parametrize("word", ["canceld", "indefinitley", "tentativly", "possibley"])
def test_a_status_or_a_hedge_spelt_a_letter_off_is_not_read(word: str) -> None:
    assert not word_class(word)


# ... but for the misspellings of "indefinitely" listings use most, which are listed.
@pytest.mark.parametrize("word", ["indefinately", "indefinetly", "indefinte"])
def test_the_common_misspellings_of_indefinitely_are_read(word: str) -> None:
    assert word_class(word)


# names_read is a quick test that unread_sentence finds nothing: it may leave the question
# open, but never says so wrongly.
GATE_WORDS = (
    "zorb", "kubaze", "qq", "schools", "campus", "elementary", "main", "early", "closed",
    "delay", "tomorrow", "friday", "due", "to", "snow", "and", "&", "-", "remain", "all",
    "no", "activities", "office", "learning", "center", "but",
)  # fmt: skip
MARKS = ("", "", "", ",", ".", ":", ";", " |")


@settings(max_examples=800, deadline=None)
@given(
    words=st.lists(
        st.tuples(st.sampled_from(GATE_WORDS), st.sampled_from(MARKS)), min_size=1, max_size=12
    ),
    cuts=st.lists(st.tuples(st.integers(0, 80), st.integers(1, 20), st.integers(0, 2)), max_size=3),
)
def test_names_read_never_contradicts_the_full_reading(
    words: list[tuple[str, str]], cuts: list[tuple[int, int, int]]
) -> None:
    text = " ".join(word + mark for word, mark in words)
    spans = sorted((low, low + length, kind) for low, length, kind in cuts)
    anchors = sorted(low for low, _length, kind in spans if kind != NOTE_SPAN)
    if names_read(text, spans):
        assert not unread_sentence(text, spans, anchors), text


# Words the grammar does not know: made-up words and ordinary English words outside it.
ORDINARY = (
    "parade", "bonfire", "allegedly", "unofficially", "supposedly", "hypothetically",
    "banana", "rumble", "glitter", "wobbly", "sandcastle", "trombone", "lol", "pinky",
    "kinda", "iffy", "sorta", "pretend", "doodle", "spaghetti", "maybeish", "doubly",
    "mustard", "galaxy", "velvet", "kayak", "lantern", "pickle", "umbrella", "puzzle",
    "whistle", "marmalade", "toaster", "walrus", "noodle", "saxophone",
)  # fmt: skip
SYLLABLES = ("ba", "ke", "zu", "lo", "mi", "ra", "to", "vi", "qu", "xe")
MADE_UP = st.lists(st.sampled_from(SYLLABLES), min_size=3, max_size=4).map("".join)
TOKENS = st.one_of(st.sampled_from(ORDINARY), MADE_UP).filter(lambda token: not word_class(token))
# Listings whose every sentence names a status or a day.
STATUSES = (
    "Closed", "No school", "2 hour delay", "Two hour delay", "NTI day", "Remote learning",
    "Early dismissal at 1:00", "Classes cancelled", "Opening at 10:00", "Virtual learning day",
    "Late start", "Closed for students",
)  # fmt: skip
DAYS = ("today", "tomorrow", "Thursday", "Friday", "January 23", "1/23", "today and tomorrow")
SHAPES = ("{status} {day}", "{status} {day} due to snow", "{status} {day}. Classes resume Monday.")
POSTINGS = st.builds(
    lambda day, hour: datetime(2026, 1, 19, hour, 0, tzinfo=ZONE) + timedelta(days=day),
    st.integers(0, 6),
    st.sampled_from((6, 20)),
)


def test_the_pool_holds_only_words_the_grammar_does_not_know() -> None:
    assert [word for word in ORDINARY if word_class(word)] == []


@settings(max_examples=600, deadline=None)
@given(
    shape=st.sampled_from(SHAPES),
    status=st.sampled_from(STATUSES),
    day=st.sampled_from(DAYS),
    token=TOKENS,
    place=st.integers(0, 1000),
    sentence=st.integers(0, 1),
    posted=POSTINGS,
)
def test_a_word_the_grammar_does_not_know_never_leaves_a_confident_result(  # noqa: PLR0913, PLR0917
    shape: str, status: str, day: str, token: str, place: int, sentence: int, posted: datetime
) -> None:
    listing = shape.format(status=status, day=day)
    sentences = listing.split(". ")
    chosen = min(sentence, len(sentences) - 1)
    words = sentences[chosen].rstrip(".").split(" ")
    at = place % (len(words) + 1)
    lowered = [word.lower().strip(",.:") for word in words]
    if at < len(words) and word_class(lowered[at]) & NAME_END:
        return  # (before a noun that ends a name, the word is the name's: "Kubaze School")
    if any(word_class(word) & CAUSE for word in lowered[:at]):
        return  # (after "due to", the rest of the clause is the cause's)
    words.insert(at, token)
    sentences[chosen] = " ".join(words) + ("." if sentences[chosen].endswith(".") else "")
    text = ". ".join(sentences)
    result = parse_status(text, posted_at=posted, tz=TZ)
    assert result.confidence < 0.7, text


# A later sentence, with no day of its own, that holds school, says it runs as usual, or says
# the post no longer holds (see parse._unread_statement and parse._bare_statement), and the
# status's kind denied after it (see parse._denied_later).
HELD_LATER = (
    "School will be held", "Classes will be held", "School is on", "We will have school",
    "There will be school", "School will be in session", "Classes will meet as scheduled",
    "School is on as scheduled", "Open as normal", "Normal day", "Regular day",
    "Business as usual", "Full day of school", "School open", "Open on time",
    "Regular schedule", "Back on", "Change of plans: open", "That is no longer the case",
    "This notice is outdated", "Not anymore", "Never mind", "Classes will run as normal",
    "School will start on time", "School is open", "Schools are open", "Classes are on",
    "Students will attend", "Disregard", "This was posted in error", "Open", "We are open",
    "We will be open", "School will open on time", "All schools open", "Normal schedule",
    "Classes as usual", "School as usual", "Plans have changed", "Change of plans",
)  # fmt: skip
STATED = (
    "Closed", "No school", "2 hour delay", "eLearning day", "NTI day", "Early dismissal",
    "Late start", "Virtual learning", "School closed",
)  # fmt: skip
DENIED_LATER = (
    ("Closed", "Not closed"), ("School closed", "No longer closed"),
    ("2 hour delay", "Not delayed"), ("Remote learning", "No remote learning"),
)  # fmt: skip


@settings(max_examples=800, deadline=None)
@given(
    status=st.sampled_from(STATED),
    day=st.sampled_from(("today", "tomorrow", "Friday", "Jan. 22", "Thursday and Friday", "")),
    held=st.sampled_from(HELD_LATER),
    lead=st.sampled_from(("", "Update: ", "UPDATE - ", "Correction: ")),
    join=st.sampled_from((". ", "; ")),
    posted=st.datetimes(
        min_value=datetime(2026, 1, 1), max_value=datetime(2026, 3, 1), timezones=st.just(ZONE)
    ),
)
def test_school_held_or_a_withdrawal_after_a_status_leaves_no_confident_status(  # noqa: PLR0913, PLR0917
    status: str, day: str, held: str, lead: str, join: str, posted: datetime
) -> None:
    text = f"{status} {day}".strip() + f"{join}{lead}{held}."
    result = parse_status(text, posted_at=posted, tz=TZ)
    # (An update that opens the school replaces the status: "other", sure that school is open.)
    assert result.kind == "other", text
    assert result.schedule == (), text


@settings(max_examples=300, deadline=None)
@given(
    pair=st.sampled_from(DENIED_LATER),
    day=st.sampled_from(("today", "tomorrow", "Friday", "Jan. 22", "")),
    lead=st.sampled_from(("", "Update: ", "Correction: ")),
    join=st.sampled_from((". ", "; ")),
)
def test_a_status_denied_after_it_with_no_day_leaves_no_confident_status(
    pair: tuple[str, str], day: str, lead: str, join: str
) -> None:
    status, denial = pair
    text = f"{status} {day}".strip() + f"{join}{lead}{denial}."
    result = parse_status(text, posted_at=WED, tz=TZ)
    assert result.kind == "other", text
    assert result.confidence < 0.7, text
