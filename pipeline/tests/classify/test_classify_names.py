"""Names in a listing, and the word checks behind them.

The parser shares one analysis between listings that differ only in their
names, at their start or end or inside the text (see ``parse.canonical``).
These tests hold that this never changes a result, whatever words, marks and
numbers stand around the names. The names are made up from syllables for these
tests (synthetic, never real schools).
"""

import random
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from snowlight.classify import ParsedStatus, parse_status
from snowlight.classify import parse as parse_module
from snowlight.classify.dates import (
    _DAY_NAMES,
    _NOT_DAY_WORDS,
    _READ_DAY_WORDS,
    _TOMORROW_LIKE,
    _UNREAD_DAY_WORDS,
    daylike_word,
)
from snowlight.classify.lexicon import FILLERS, HEDGES, MODIFIERS, NEGATIONS, SCOPES
from snowlight.classify.mentions import _EXACT, _PARTS, _SUB_BITS, rule_mask
from snowlight.classify.parse import _cached_analysis, _normalized_analysis, canonical
from snowlight.classify.text import normalize

TZ = "America/Chicago"
ZONE = ZoneInfo(TZ)
ZONES = ("America/Chicago", "America/New_York", "America/Denver", "America/Los_Angeles")
instants = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2032, 12, 31),
    timezones=st.sampled_from([ZoneInfo(name) for name in ZONES]),
)

SYLLABLES = ("ba", "ku", "te", "mi", "zo", "ra", "fa", "lo", "vi", "de", "na", "po", "si", "gu")
TRICKY_NAMES = (
    "Christian", "Lincoln", "Washington", "Monroe", "Sunnyside", "Noonan", "Gradeville",
    "Powers", "Backus", "Returning", "Earlyville", "Hourglass", "Tilden", "Nightingale",
    "Mayfield", "Marshall", "Dayton", "Friday", "Morning", "Only", "No", "For", "At", "The",
    "Snow", "Closed", "Open", "Staff",
)  # fmt: skip
INSTITUTIONS = (
    "Elementary", "Middle School", "High School", "Academy", "School District",
    "Public Schools", "Preschool", "Christian School", "County Schools", "Junior High",
    "Montessori", "Community Schools", "Center",
)  # fmt: skip
STATUSES = (
    "Closed", "No school", "Classes cancelled", "2 hour delay", "Two-hour delay",
    "90 minute delay", "Opening at 10:00", "Late start", "Early dismissal at 1:00",
    "Dismissing 2 hours early", "Closing at noon", "NTI day", "E-learning day",
    "Remote learning", "Closed; offices open", "Closed today and tomorrow",
    "All activities cancelled", "No AM kindergarten", "Possible early dismissal",
    "2 hour delay cancelled", "Delay: cancelled", "Cancel the delay", "Early dismissal lifted",
    "Cancelled - NTI day", "Closure rescinded", "Delay cancelled, now closed",
)  # fmt: skip
AROUND = (
    "", "today", "tomorrow", "Friday", "Jan 22", "1/23", "due to snow", "at 10", "2 hour",
    "hour delay", "hours late", "days", "am", "jan", "- 14", "and 22", "through 23",
    "or 3 days", "1.21", "3rd", "grade", "the 21st", "next week", "tonight", "?", "if",
    "only", "for students", "was", "now", "no", "not", "cancelled", "lifted", "has been",
)  # fmt: skip
SEPARATORS = (": ", " - ", ", ", "; ", ". ", " | ", " (", "), ", " ", "-", ": ")
ENDINGS = ("", ".", ")", "?", " only", ",")


def made_up_name(pick: random.Random) -> str:
    """A name from syllables, or a word that could be a name, a school noun and a number."""
    parts = []
    for _ in range(pick.randint(1, 3)):
        roll = pick.random()
        if roll < 0.55:
            parts.append("".join(pick.choice(SYLLABLES) for _ in range(pick.randint(2, 4))))
        elif roll < 0.8:
            parts.append(pick.choice(TRICKY_NAMES))
        else:
            parts.append(str(pick.randint(1, 2030)))
    if pick.random() < 0.7:
        parts.append(pick.choice(INSTITUTIONS))
    if pick.random() < 0.4:
        parts.append(f"#{pick.randint(1, 99)}")
    return " ".join(parts)


# A made-up name word (see made_up_name): the words renamed in a text's siblings.
MADE_UP = re.compile("(?:" + "|".join(SYLLABLES) + "){2,4}")


def renamed(text: str, pick: random.Random) -> str:
    """``text`` with each made-up name word in it replaced by another made-up word."""
    return MADE_UP.sub(
        lambda _word: "".join(pick.choice(SYLLABLES) for _ in range(pick.randint(2, 4))), text
    )


def both_ways(text: str, posted: datetime, tz: str) -> tuple[ParsedStatus, ParsedStatus]:
    """Parse ``text`` with names collapsed and without, from cold caches.

    With names collapsed two siblings of the text, the same but for its made-up
    names, come first and leave the analysis of their names collapsed, which the
    text then shares when its own names collapse alike (and reads the same way
    when not).
    """
    pick = random.Random(text)  # noqa: S311 - made-up names for a test
    results: list[ParsedStatus] = []
    for collapse in (True, False):
        parse_module._CANONICAL = collapse
        _cached_analysis.cache_clear()
        _normalized_analysis.cache_clear()
        try:
            if collapse:
                for _ in range(2):
                    parse_status(renamed(text, pick), posted_at=posted, tz=tz)
            results.append(parse_status(text, posted_at=posted, tz=tz))
        finally:
            parse_module._CANONICAL = True
    return results[0], results[1]


@settings(max_examples=600, deadline=None)
@given(
    seed=st.integers(0, 2**32 - 1),
    status=st.sampled_from(STATUSES),
    before=st.sampled_from(AROUND),
    after=st.sampled_from(AROUND),
    head=st.sampled_from(SEPARATORS),
    tail=st.sampled_from(SEPARATORS),
    ending=st.sampled_from(ENDINGS),
    where=st.sampled_from(("start", "end", "both")),
    posted=instants,
    tz=st.sampled_from(ZONES),
)
def test_collapsing_names_changes_no_result(  # noqa: PLR0913, PLR0917 - the drawn parts
    seed: int,
    status: str,
    before: str,
    after: str,
    head: str,
    tail: str,
    ending: str,
    where: str,
    posted: datetime,
    tz: str,
) -> None:
    pick = random.Random(seed)  # noqa: S311 - made-up names for a test
    text = " ".join(part for part in (before, status, after) if part)
    if where in {"start", "both"}:
        text = made_up_name(pick) + head + text
    if where in {"end", "both"}:
        text = text + tail + made_up_name(pick) + ending
    collapsed, direct = both_ways(text, posted, tz)
    assert collapsed == direct


CORPUS_WORDS = (
    [*SCOPES, *MODIFIERS, *NEGATIONS, *HEDGES, *FILLERS]
    + [status.lower() for status in STATUSES]
    + [word.lower() for word in AROUND if word]
)


@settings(max_examples=400, deadline=None)
@given(
    seed=st.integers(0, 2**32 - 1),
    body=st.lists(st.sampled_from(CORPUS_WORDS), min_size=1, max_size=6),
    marks=st.lists(st.sampled_from(("", ",", ";", ".", " -", ":", "?")), min_size=6, max_size=6),
    posted=instants,
)
def test_collapsing_names_changes_no_result_in_word_soup(
    seed: int, body: list[str], marks: list[str], posted: datetime
) -> None:
    pick = random.Random(seed)  # noqa: S311 - made-up names for a test
    middle = " ".join(word + mark for word, mark in zip(body, marks, strict=False))
    text = f"{made_up_name(pick)}{pick.choice(SEPARATORS)}{middle}"
    text += f"{pick.choice(SEPARATORS)}{made_up_name(pick)}{pick.choice(ENDINGS)}"
    collapsed, direct = both_ways(text, posted, TZ)
    assert collapsed == direct


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("Closed - Bakutemi Zorafa Elementary", "closed - qq elementary"),
        ("Bakutemi Zorafa Elementary: 2 hour delay", "qq elementary: 2 hour delay"),
        # A reference number is dropped when the text is normalized; a bare one stays short.
        ("Closed - Bakutemi Zorafa Elementary #12", "closed - qq elementary"),
        ("Bakutemi Zorafa Elementary #12: Closed", "qq elementary: closed"),
        ("Closed - Bakutemi Zorafa Elementary 12", "closed - qq elementary 1"),
        ("Bakutemi Zorafa Elementary 12: Closed", "qq elementary 1: closed"),
        ("Closed (Bakutemi Academy)", "closed, qq academy"),
        ("Bakutemi, Zorafa - NTI day", "qq, qq - nti day"),
        # Left alone: a date's own marks, a number at a dash.
        ("Closed 1.21.26", "closed 1.21.26"),
        ("Bakutemi 2 - hour delay", "qq 2 - hour delay"),
        ("Closed - Christian Academy", "closed - christian academy"),
        ("Closed - Lincoln Elementary", "closed - lincoln elementary"),
        ("Closed today", "closed today"),
        ("$12 Bakutemi Academy: Closed - Zorafa", "$12 qq academy: closed - qq"),
        # Names alone, and names inside the text: masked letter for letter.
        ("Bakutemi Zorafa", "qqqqqqqq qqqqqq"),
        ("Closed; Maple Bus Garage open", "closed; qqqqq bus garage open"),
        ("Closed, Bakutemi bag day", "closed, qqqqqqqq bag day"),
        ("Closed Bakutemi Zorafa Elementary", "closed qqqqqqqq qqqqqq elementary"),
        ("All Bakutemi schools closed", "all qqqqqqqq schools closed"),
        ("Closed for Zorafa students", "closed for qqqqqq students"),
        # A date after names at the end keeps its place: a window looks back from it.
        ("Closed - Bakutemi Zorafa Elementary 1.21", "closed - qqqqqqqq qqqqqq elementary 1.21"),
        ("Returning 1/22 - Bakutemi Zorafa 1.21", "returning 1/22 - qqqqqqqq qqqqqq 1.21"),
        # Words some pattern reads, if only with a letter it may leave out ("bags?").
        ("Blizzard bag day", "blizzard bag day"),
        ("Closed, bag day", "closed, bag day"),
    ],
)
def test_canonical_keys(text: str, key: str) -> None:
    assert canonical(normalize(text)) == key


def test_listings_that_differ_only_in_names_share_an_analysis() -> None:
    _cached_analysis.cache_clear()
    _normalized_analysis.cache_clear()
    posted = datetime(2026, 1, 21, 6, 0, tzinfo=ZONE)
    first = parse_status("Closed - Bakutemi Zorafa Elementary", posted_at=posted, tz=TZ)
    # The names are collapsed in the first listing: its analysis stands for them all.
    assert _normalized_analysis.cache_info().currsize == 1
    second = parse_status("Closed - Lovipo Gusipo Elementary", posted_at=posted, tz=TZ)
    assert _normalized_analysis.cache_info().currsize == 1  # (found, not made again)
    third = parse_status("Closed - Sifade Elementary", posted_at=posted, tz=TZ)
    assert first == second == third
    assert _normalized_analysis.cache_info().currsize == 1  # (found, not made again)


def read_directly(text: str, posted: datetime) -> ParsedStatus:
    """``text`` parsed from cold caches with no names collapsed and no day number fixed."""
    _cached_analysis.cache_clear()
    _normalized_analysis.cache_clear()
    parse_module._CANONICAL = parse_module._TEMPLATE = False
    try:
        return parse_status(text, posted_at=posted, tz=TZ)
    finally:
        parse_module._CANONICAL = parse_module._TEMPLATE = True


def test_the_placeholder_is_a_word_nothing_reads() -> None:
    assert parse_module._role_free(parse_module._PLACEHOLDER)
    assert parse_module._PLACEHOLDER not in parse_module._VOCABULARY
    assert not parse_module._PLACEHOLDER.strip(parse_module._MASK)  # a word of the mask
    for length in range(2, 16):
        assert parse_module._role_free(parse_module._MASK * length)


def test_listings_that_differ_only_in_a_name_inside_share_an_analysis() -> None:
    _cached_analysis.cache_clear()
    _normalized_analysis.cache_clear()
    posted = datetime(2026, 1, 21, 6, 0, tzinfo=ZONE)
    first = parse_status("Closed Jan 22; Bakute Bus Garage open", posted_at=posted, tz=TZ)
    second = parse_status("Closed Jan 22; Zorafa Bus Garage open", posted_at=posted, tz=TZ)
    kept = _normalized_analysis.cache_info().currsize
    # (The first is kept under its day template with its name; the second, masked.)
    third = parse_status("Closed Jan 23; Lovipo Bus Garage open", posted_at=posted, tz=TZ)
    assert first == second
    assert _normalized_analysis.cache_info().currsize == kept  # (found, not made again)
    assert third.dates == (date(2026, 1, 23),)  # its own day, put back
    assert third == read_directly("Closed Jan 23; Lovipo Bus Garage open", posted)


def test_forgetting_every_cache_changes_no_result() -> None:
    posted = datetime(2026, 1, 21, 6, 0, tzinfo=ZONE)
    texts = [
        "Closed - Bakutemi Zorafa Elementary",
        "Closed Jan 22; Bakute Bus Garage open",
        "2 hour delay 1/23 due to snow (updated 5:43 AM) #4411",
        "Lovipo Gusipo Academy: early dismissal at 1:00 today",
    ]
    before = [parse_status(text, posted_at=posted, tz=TZ) for text in texts]
    parse_module._forget_words()
    assert _normalized_analysis.cache_info().currsize == 0
    assert [parse_status(text, posted_at=posted, tz=TZ) for text in texts] == before


def test_an_analysis_is_kept_from_the_second_time_its_text_comes() -> None:
    _cached_analysis.cache_clear()
    _normalized_analysis.cache_clear()
    posted = datetime(2026, 1, 21, 6, 0, tzinfo=ZONE)
    first = parse_status("Closed Wednesday due to snow", posted_at=posted, tz=TZ)
    assert _cached_analysis.cache_info().currsize == 0  # seen once: not kept
    assert _normalized_analysis.cache_info().currsize == 0
    assert parse_status("Closed Wednesday due to snow", posted_at=posted, tz=TZ) == first
    assert _cached_analysis.cache_info().currsize == 1
    assert _normalized_analysis.cache_info().currsize == 1
    assert parse_status("Closed Wednesday due to snow", posted_at=posted, tz=TZ) == first


def test_a_template_is_kept_the_first_time() -> None:
    # A key with a day number or names replaced stands for other texts: kept at once.
    _cached_analysis.cache_clear()
    _normalized_analysis.cache_clear()
    posted = datetime(2026, 1, 21, 6, 0, tzinfo=ZONE)
    parse_status("Closed Jan 22 due to snow", posted_at=posted, tz=TZ)
    assert _cached_analysis.cache_info().currsize == 0
    assert _normalized_analysis.cache_info().currsize == 1


def test_a_template_kept_with_one_texts_days_serves_another_texts_days() -> None:
    # The first text's own analysis stands for its template, with its own day (22); the
    # next, whose day is the template's own number (15), gets its day put back as well.
    _cached_analysis.cache_clear()
    _normalized_analysis.cache_clear()
    posted = datetime(2026, 1, 12, 6, 0, tzinfo=ZONE)
    first = parse_status("Closed Jan 22 due to snow", posted_at=posted, tz=TZ)
    second = parse_status("Closed Jan 15 due to snow", posted_at=posted, tz=TZ)
    assert _normalized_analysis.cache_info().currsize == 1  # (the first's, shared)
    assert first.dates == (date(2026, 1, 22),)
    assert second.dates == (date(2026, 1, 15),)
    assert second == read_directly("Closed Jan 15 due to snow", posted)


def test_names_collapsed_before_a_day_number_share_the_template() -> None:
    # Collapsing the names moves the day number, so the text with its names collapsed and
    # its day fixed is read in their place, and each text's day is put back.
    _cached_analysis.cache_clear()
    _normalized_analysis.cache_clear()
    posted = datetime(2026, 1, 12, 6, 0, tzinfo=ZONE)
    texts = [
        f"{name} Elementary: Closed Jan {day}"
        for name, day in (("Bakutemi Zorafa", 22), ("Lovipo", 23), ("Sifade Gusipo", 26))
    ]
    results = [parse_status(text, posted_at=posted, tz=TZ) for text in texts]
    assert [result.dates for result in results] == [
        (date(2026, 1, 22),), (date(2026, 1, 23),), (date(2026, 1, 26),),
    ]  # fmt: skip
    assert results == [read_directly(text, posted) for text in texts]


TEXTS = ["closed", "2 hour delay", "remote learning day"]


def test_a_full_text_cache_starts_over() -> None:
    cache = parse_module._TextCache(parse_module._analyse_normalized, maxsize=2)
    first = [cache(text) for text in TEXTS]  # seen once: none kept
    assert cache.cache_info() == (0, 2)
    assert [cache(text) for text in TEXTS] == first  # the third finds it full: starts over
    assert cache.cache_info() == (1, 2)
    cache.cache_clear()
    assert cache.cache_info() == (0, 2)


def test_the_texts_seen_once_are_forgotten_past_a_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(parse_module, "_MOST_SEEN", 2)
    cache = parse_module._TextCache(parse_module._analyse_normalized, maxsize=8)
    first = [cache(text) for text in TEXTS]  # the third starts the texts seen over
    assert cache(TEXTS[0]) == first[0]  # forgotten: seen once more, not kept
    assert cache(TEXTS[2]) == first[2]  # remembered: kept
    assert cache.cache_info() == (1, 8)


def test_the_caches_parse_status_keeps_stay_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    # parse_status keeps its own texts, and the texts they normalize to, as _TextCache does.
    posted = datetime(2026, 1, 21, 6, 0, tzinfo=ZONE)
    texts = [
        "Closed Today", "CLOSED today", "2 Hour Delay", "Closed Jan 22", "Remote Learning Day",
    ]  # fmt: skip
    expected = [read_directly(text, posted) for text in texts]
    monkeypatch.setattr(parse_module, "_MOST_SEEN", 2)
    monkeypatch.setattr(parse_module, "_MOST_KEPT", 1)
    _cached_analysis.cache_clear()
    _normalized_analysis.cache_clear()
    for _ in range(3):  # (each text twice in a row: kept, then found)
        twice = [text for text in texts for _ in range(2)]
        found = [parse_status(text, posted_at=posted, tz=TZ) for text in twice]
        assert found == [result for result in expected for _ in range(2)]
        assert len(parse_module._RAW_SEEN) <= 2
        assert len(parse_module._RAW_KEPT) <= 1
        assert len(parse_module._NORMALIZED_SEEN) <= 2
        assert len(parse_module._NORMALIZED_KEPT) <= 1


@pytest.mark.parametrize(
    "word", ["bag", "bags", "meal", "mile", "point", "method", "deg", "min", "hour"]
)
def test_words_a_pattern_reads_are_no_names(word: str) -> None:
    # "blizzard bags?" reads "bag", "miles?" reads "mile": each has a role.
    assert not parse_module._role_free(word)


@pytest.mark.parametrize(
    "text",
    [
        "Snow Returning School District: pending - Sitefate Mira 1.21.",
        "Returning 1/22 - Bakutemi Zorafa 1.21",
        "3rd grade closed - Bakutemi Zorafa Academy 12-14",
        "Closed; Maple Bus Garage open",
        "Closed, bag day",
        "Delayed - Bakutemi; Zorafa blizzard bag day",
        "Bakutemi Zorafa",
        "Closed | Lovipo Gusipo 10:00",
        "Early dismissal; Bakutemi Zorafa at 1:00",
    ],
)
def test_names_masked_change_no_result(text: str) -> None:
    for hours in (0, 7, 13, 21, 30, 55):
        posted = datetime(2026, 1, 19, 5, 0, tzinfo=ZONE) + timedelta(hours=hours)
        collapsed, direct = both_ways(text, posted, TZ)
        assert collapsed == direct


GAP_WORDS = ("bag", "Bags", "meal", "Mile", "point", "method", "yr", "Maple", "Garage", "Bus")
MARKS = (", ", "; ", ": ", " - ", ". ", " | ", "! ", " (", ") ", " / ", " & ", " and ", " ")


def _segment(pick: random.Random) -> str:
    """A phrase of a status, words around one, a made-up name, or a word some pattern reads."""
    roll = pick.random()
    if roll < 0.3:  # the share of statuses
        return pick.choice(STATUSES)
    if roll < 0.5:  # the share of words around one
        return pick.choice(AROUND) or "today"
    parts = [
        made_up_name(pick) if pick.random() < 0.75 else pick.choice(GAP_WORDS)
        for _ in range(pick.randint(1, 2))
    ]
    if pick.random() < 0.3:  # a number or a date inside the name
        parts.append(pick.choice(("12", "1.21", "10:00", "1/21", "3rd", "1-3", "2026")))
    if pick.random() < 0.4:  # a noun or a status word after it
        parts.append(pick.choice(("day", "days", "delay", "closed", "open", "only", "lunch")))
    return " ".join(parts)


@settings(max_examples=500, deadline=None)
@given(seed=st.integers(0, 2**32 - 1), count=st.integers(1, 5), posted=instants)
def test_masking_names_inside_changes_no_result(seed: int, count: int, posted: datetime) -> None:
    pick = random.Random(seed)  # noqa: S311 - made-up names for a test
    text = _segment(pick)
    for _ in range(count - 1):
        text += pick.choice(MARKS) + _segment(pick)
    collapsed, direct = both_ways(text + pick.choice(ENDINGS), posted, TZ)
    assert collapsed == direct


def _osa(word: str, target: str) -> int:
    """Optimal string alignment distance, written out plainly as the oracle."""
    rows = [[0] * (len(target) + 1) for _ in range(len(word) + 1)]
    for i in range(len(word) + 1):
        rows[i][0] = i
    for j in range(len(target) + 1):
        rows[0][j] = j
    for i in range(1, len(word) + 1):
        for j in range(1, len(target) + 1):
            cost = 0 if word[i - 1] == target[j - 1] else 1
            rows[i][j] = min(rows[i - 1][j] + 1, rows[i][j - 1] + 1, rows[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and word[i - 1] == target[j - 2] and word[i - 2] == target[j - 1]:
                rows[i][j] = min(rows[i][j], rows[i - 2][j - 2] + 1)
    return rows[len(word)][len(target)]


def _daylike_oracle(word: str) -> bool:
    """``daylike_word`` with the plain distance above in place of the library's."""
    stem = word.removesuffix("'s")
    if stem in _READ_DAY_WORDS or word in _NOT_DAY_WORDS:
        return False
    if stem in _UNREAD_DAY_WORDS or _TOMORROW_LIKE.fullmatch(stem) is not None:
        return True
    if len(stem) < 4 or not stem.isalpha():
        return False
    return any(
        name[0] == stem[0]
        and abs(len(name) - len(stem)) <= 2
        and _osa(stem, name) <= (1 if min(len(name), len(stem)) <= 6 else 2)
        for name in _DAY_NAMES
    )


@settings(max_examples=500, deadline=None)
@given(
    name=st.sampled_from(_DAY_NAMES),
    edits=st.lists(
        st.tuples(st.integers(0, 3), st.integers(0, 12), st.sampled_from("abcdefghijklmnoprstuwy")),
        max_size=3,
    ),
)
def test_misspelled_day_names_match_the_plain_distance(
    name: str, edits: list[tuple[int, int, str]]
) -> None:
    word = list(name)
    for operation, place, letter in edits:
        at = min(place, len(word) - 1)
        if operation == 0 and len(word) > 1:
            del word[at]
        elif operation == 1:
            word.insert(at, letter)
        elif operation == 2:
            word[at] = letter
        elif at + 1 < len(word):
            word[at], word[at + 1] = word[at + 1], word[at]
    spelled = "".join(word)
    assert daylike_word.__wrapped__(spelled) == _daylike_oracle(spelled)


@settings(max_examples=300, deadline=None)
@given(word=st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=11))
def test_any_word_matches_the_plain_distance(word: str) -> None:
    assert daylike_word.__wrapped__(word) == _daylike_oracle(word)


@settings(max_examples=500, deadline=None)
@given(word=st.text(alphabet="abcdefghijklmnopqrstuvwxyz'/-01", min_size=1, max_size=12))
def test_rule_mask_quick_reject_matches_the_full_scan(word: str) -> None:
    mask = 0
    for key, rules in _PARTS:
        if key in word:
            for index in rules:
                mask |= _SUB_BITS[index]  # (each rule's sub-rules: see mentions._SUB_RULES)
    # A word a rule needs whole, alone or joined to others by a hyphen or a slash.
    for part in {word, *re.split(r"[/-]", word)}:
        for index in _EXACT.get(part, ()):
            mask |= _SUB_BITS[index]
    assert rule_mask.__wrapped__(word) == mask


# Name words the precision gate can read apart by their spelling: one that ends in "ly" may be
# an adverb ("Kubaly - closed" is unread where "Kubaze - closed" is a name's: see
# gate.unread_sentence), one that ends in "ed" a past participle. Given names and made-up words.
SPELLED_NAMES = (
    "Holly", "Kelly", "Beverly", "Emily", "Ely", "Kimberly", "Shelly", "Lilly", "Polly",
    "Kubaly", "Zorafly", "Tavely", "Reed", "Fred", "Mildred", "Kubazed", "Lomired",
    "Kubaze", "Lomira", "Tavimo", "Zorafa", "Kulosil", "Venex", "Sifade", "Bakute",
)  # fmt: skip
NAME_FORMS = (
    "{n} - {s}", "{n}: {s}", "{n} -- {s}", "{n}, {s}", "{n} and Lomira - {s}",
    "{s}; {n} Head Start open", "{s} - {n}", "{s}, including {n}", "{s}. {n} campus open",
    "{s} at {n}", "{n} {s}", "{s} for {n} students", "{s}; {n} with a 2 hour delay",
)  # fmt: skip
NAME_STATUSES = (
    "No school", "Closed", "E-learning day", "2 hour delay", "Two-hour delay", "Closed today",
    "Closed. Offices open", "Early dismissal at 1:00", "Remote learning tomorrow",
)  # fmt: skip


def fresh(text: str, posted: datetime) -> ParsedStatus:
    """``text`` parsed with every cache and word table empty."""
    parse_module._forget_words()
    return parse_status(text, posted_at=posted, tz=TZ)


@settings(max_examples=600, deadline=None)
@given(
    form=st.sampled_from(NAME_FORMS),
    status=st.sampled_from(NAME_STATUSES),
    name=st.sampled_from(SPELLED_NAMES),
    other=st.one_of(
        st.sampled_from(SPELLED_NAMES),
        st.text(alphabet="bdfgklmnprstvz", min_size=3, max_size=8),
    ),
    same_length=st.booleans(),
    hours=st.integers(0, 24 * 7),
)
def test_a_sibling_with_another_name_never_changes_a_result(  # noqa: PLR0913, PLR0917 - drawn
    form: str, status: str, name: str, other: str, same_length: bool, hours: int
) -> None:
    # Texts that differ only in a name word share one analysis (see parse.canonical): never
    # when the gate reads the two words apart, so whichever was parsed first decides nothing.
    if same_length:
        other = (other * len(name))[: len(name)].capitalize()
    posted = datetime(2026, 1, 20, 5, 30, tzinfo=ZONE) + timedelta(hours=hours)
    text = form.format(n=name, s=status)
    sibling = form.format(n=other.capitalize(), s=status)
    alone = fresh(text, posted)
    parse_module._forget_words()
    parse_status(sibling, posted_at=posted, tz=TZ)
    parse_status(sibling, posted_at=posted, tz=TZ)  # (kept from the second time)
    assert parse_status(text, posted_at=posted, tz=TZ) == alone
    assert parse_status(text, posted_at=posted, tz=TZ) == alone


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Holly - No school", "Kulosil Kumi - No school"),
        ("Kulosil Kumi - No school", "Holly - No school"),
        ("Two-hour delay; Holly Head Start open", "Two-hour delay; Venex Head Start open"),
        ("Two-hour delay; Venex Head Start open", "Two-hour delay; Holly Head Start open"),
        ("Kubaz: E-learning day", "Kelly: E-learning day"),
        ("Kelly: E-learning day", "Kubaz: E-learning day"),
        ("Kulosa - No school", "Dooly - No school"),
        ("Kubazet: Closed", "Beverly: Closed"),
        ("Kubaze Area Schools: Closed", "Holly Area Schools: Closed"),
        ("Emily: Closed", "Kubaz: Closed"),
        ("Kubaze: Closed today", "Kimberly: Closed today"),
    ],
)
def test_a_name_read_apart_by_the_gate_shares_no_analysis(first: str, second: str) -> None:
    posted = datetime(2026, 1, 20, 5, 30, tzinfo=ZONE)
    alone = fresh(second, posted)
    parse_module._forget_words()
    for _ in range(2):
        parse_status(first, posted_at=posted, tz=TZ)
    assert parse_status(second, posted_at=posted, tz=TZ) == alone
