"""Words that are no name's, and a sentence after a status that corrects it or puts it off.

Every text here is a phrasing pattern written for these tests, not a claim
about a real school. Every row is posted at 6 a.m. on Wednesday 21 January 2026
in Chicago, so "tomorrow" is Thursday the 22nd.

The precision gate takes the words no rule reads right before a noun that ends a
name ("Kubaze schools closed tomorrow") or in a label ("Kubaze: closed
tomorrow") for a name's. A word that is no name's is unread there too: an
adverb ("Apparently school is closed tomorrow", "Unofficially, schools closed
tomorrow"), a past participle that opens its sentence ("Averted school closure
tomorrow", "Expired: closed tomorrow"), or a word of doubt, of a correction or
of a status past ("Imminent school closure tomorrow", "Iffy: closed tomorrow").
A label of a status past or a trial ("Previous:", "Old:", "Test:") is read as
such. A name keeps its status: "Kubaze: closed tomorrow", "Old Town Elementary:
closed tomorrow".

A sentence after a status that is a word no rule reads alone ("Closed tomorrow.
Oops."), a correction ("Not happening.", "No longer.", "Wrong school."), a
change of plans, or a look at the status to come ("Will reassess at 5 am.", "A
final determination will be made by 5 am.", "Final call at 5 am.", "Could
change overnight.", "Awaiting approval.") leaves it open: ``other`` at 0.3. A
sentence of courtesy, or of where to read more, leaves it standing.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from snowlight.classify import parse_status
from snowlight.classify.gate import not_name, word_class

TZ = "America/Chicago"
MORNING = datetime(2026, 1, 21, 6, 0, tzinfo=ZoneInfo(TZ))  # Wednesday
TOMORROW = (date(2026, 1, 22),)

NOT_NAMES = [
    "Previous: closed tomorrow",
    "Old: closed tomorrow",
    "Outdated: closed tomorrow",
    "Expired: closed tomorrow",
    "Archived: closed tomorrow",
    "Proposed: closed tomorrow",
    "TEST: closed tomorrow",
    "Draft: closed tomorrow",
    "Iffy: closed tomorrow",
    "Apparently school is closed tomorrow",
    "Reportedly schools closed tomorrow",
    "Supposedly schools closed tomorrow",
    "Allegedly schools closed tomorrow",
    "Unofficially, schools closed tomorrow",
    "Averted school closure tomorrow",
    "Avoided school closure tomorrow",
    "Prevented school closure tomorrow",
    "Proposed school closure tomorrow",
    "Imminent school closure tomorrow",
    "Threatened school closure tomorrow",
    "Feared school closure tomorrow",
    "Contemplated school closure tomorrow",
]

PUT_OFF = [
    "Closed tomorrow. Not happening.",
    "Closed tomorrow. No longer.",
    "Closed tomorrow. Nope.",
    "Closed tomorrow. Void.",
    "Closed tomorrow. Expired.",
    "Closed tomorrow. Outdated.",
    "Closed tomorrow. Oops.",
    "Closed tomorrow. Wrong school.",
    "Closed tomorrow. Plans have changed.",
    "Closed tomorrow. Awaiting approval.",
    "Closed tomorrow. Needs board approval.",
    "Closed tomorrow. Will reassess at 5 am.",
    "Closed tomorrow. A final determination will be made by 5 am.",
    "Closed tomorrow. Could change overnight.",
    "Closed tomorrow. Final call at 5 am.",
    "Closed tomorrow. Final decision at 5 am.",
    "2 hour delay tomorrow. Will re-evaluate at 7am.",
    "2 hour delay tomorrow; re-evaluating at 7:30",
]

STANDING = [
    "Kubaze: closed tomorrow",
    "Kubaze schools closed tomorrow",
    "Lincoln Elementary: closed tomorrow",
    "Old Town Elementary: closed tomorrow",
    "Closed tomorrow. Stay safe!",
    "Closed tomorrow. Thank you for your patience.",
    "Closed tomorrow. Stay tuned for updates.",
    "Closed tomorrow. More info on our website.",
    "Closed tomorrow. Roads are unplowed and icy.",
    "Closed tomorrow. Everett, Seattle, Renton, Tacoma.",
    "Closed today. Will reassess tomorrow.",
]


@pytest.mark.parametrize("text", NOT_NAMES)
def test_a_word_that_is_no_name_leaves_no_confident_status(text: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other"
    assert result.confidence <= 0.3


@pytest.mark.parametrize("text", PUT_OFF)
def test_a_sentence_that_corrects_or_puts_off_the_status(text: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "other"
    assert result.confidence <= 0.3


@pytest.mark.parametrize("text", STANDING)
def test_a_name_or_a_courtesy_keeps_the_status(text: str) -> None:
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.kind == "closed"
    assert result.confidence >= 0.8
    assert result.dates in {TOMORROW, (date(2026, 1, 21),)}


# English words that name no school: adverbs, past participles, and words of doubt, of a
# correction or of a status past. None is read by the grammar, and each is no name's.
WORDS = (
    "apparently", "reportedly", "supposedly", "allegedly", "purportedly", "unofficially",
    "hypothetically", "seemingly", "presumably", "evidently", "admittedly", "averted",
    "avoided", "prevented", "proposed", "contemplated", "postulated", "outdated", "expired",
    "archived", "superseded", "reconsidered", "nope", "oops", "void", "iffy", "toss-up",
    "dicey", "shaky", "murky", "wobbly", "borderline", "unsure", "questionable", "premature",
    "imminent",
    "doubtful-ish", "unclear-ish",
)  # fmt: skip
SHAPES = (
    "{word}: closed tomorrow",
    "{word} schools closed tomorrow",
    "{word} school closure tomorrow",
    "{word}, schools closed tomorrow",
    "{word} - closed tomorrow",
    "Closed tomorrow. {word}.",
    "2 hour delay tomorrow. {word}.",
    "{word}: 2 hour delay tomorrow",
)


def test_the_pool_holds_words_that_are_no_name() -> None:
    assert [word for word in WORDS if word_class(word) or not not_name(word)] == []


@settings(max_examples=400, deadline=None)
@given(word=st.sampled_from(WORDS), shape=st.sampled_from(SHAPES), upper=st.booleans())
def test_a_word_that_is_no_name_is_never_taken_for_one(word: str, shape: str, upper: bool) -> None:
    shown = word.capitalize() if upper else word
    text = shape.format(word=shown)
    text = text[0].upper() + text[1:]
    result = parse_status(text, posted_at=MORNING, tz=TZ)
    assert result.confidence < 0.7, text
