"""The quick tests that stand in front of a pattern never change what the pattern finds.

Some patterns are tried only where a cheap test on the text says they can match:
the weather and cause scans at a run that only may start one, the bound after a
closure, the words after a weekday or "tomorrow", and a full stop between two
digits. Each shortcut here is checked against the pattern alone on made-up text.
"""

import re

from hypothesis import given, settings
from hypothesis import strategies as st

from snowlight.classify import dates, dayparts, gate, mentions, parse, partial, revoke, weather
from snowlight.classify import text as text_module

# Pieces of text near the words each shortcut looks for, joined in any order.
PIECES = (
    "no", "no water", "no heat", "water", "water main", "heat", "gas", "gas leak", "staff",
    "bus", "bus driver", "high", "high winds", "snow", "ice", "icy", "red", "red flag",
    "morning", "afternoon", "am", "pm", "for", "in", "the", "all", "rest of the", "until",
    "till", "til", "after", "from", "starting", "beginning", "as of", "effective", "noon",
    "lunch", "10", "10:30", "1.21", "12", "jan", "night", "evening", "nite", "'s", "tomorrow",
    "monday", "closed", "then", "may", "x",
)  # fmt: skip
MARKS = (" ", " ", " ", ", ", ": ", "-", "/", ".", "  ", " , ", "_", "")
texts = st.lists(
    st.tuples(st.sampled_from(PIECES), st.sampled_from(MARKS)), min_size=1, max_size=8
).map(lambda parts: "".join(piece + mark for piece, mark in parts))
_RUN_START = re.compile(r"(?<![a-z0-9])[a-z0-9]", re.ASCII)


@settings(max_examples=400, deadline=None)
@given(text=texts)
def test_a_start_is_found_where_its_pattern_finds_one(text: str) -> None:
    for run in _RUN_START.finditer(text):
        position = run.start()
        for pattern, table in (
            (weather._CAUSE_CANDIDATES, weather._CAUSE_STARTS_BY_FIRST),
            (weather._WEATHER_CANDIDATES, weather._WEATHER_STARTS_BY_FIRST),
        ):
            expected = pattern.match(text, position) is not None
            assert weather._candidate_at(text, position, table) is expected


def _bound_by_pattern(text: str, position: int) -> tuple[dayparts.Bound, int] | None:
    """:func:`dayparts._bound_at` as it read before its quick test on the next word."""
    if text.startswith((",", ":"), position):
        return dayparts._marked_bound_at(text, position)
    if not text.startswith(" ", position):
        return None
    match = dayparts._PART.match(text, position)
    return dayparts._timed_at(text, position) if match is None else dayparts._part_at(text, match)


@settings(max_examples=400, deadline=None)
@given(text=texts)
def test_a_bound_is_found_where_its_patterns_find_one(text: str) -> None:
    for position in range(len(text) + 1):
        assert dayparts._bound_at(text, position) == _bound_by_pattern(text, position)


def _dot_pair_by_steps(text: str) -> bool:
    dot = text.find(".", 1)
    while dot != -1:
        if text[dot - 1].isdigit() and text[dot + 1 : dot + 2].isdigit():
            return True
        dot = text.find(".", dot + 1)
    return False


@settings(max_examples=400, deadline=None)
@given(text=st.text(alphabet="0129. a:", max_size=24))
def test_a_full_stop_between_digits_is_found(text: str) -> None:
    assert dates.dot_pair(text) is _dot_pair_by_steps(text)


@settings(max_examples=400, deadline=None)
@given(word=st.sampled_from(("monday", "tomorrow", "today", "friday")), rest=texts)
def test_a_plain_day_is_read_as_the_pattern_reads_it(word: str, rest: str) -> None:
    text = word + rest
    code = dates._PLAIN_CODES[word]
    length = dates._PLAIN_TAILS[code][0]
    adds = dates._ADDS_AFTER_PLAIN(text, length) is not None
    atom = dates._plain_atom(text, 0, code)
    assert (atom is None) is adds
    if atom is not None:
        assert atom[:2] == (0, length)  # (its start and end)


def _weather_runs(text: str) -> list[tuple[int, tuple[tuple[int, int], ...]]]:
    """Every run of letters and digits with its start mask, as the parser passes them."""
    found: list[tuple[int, tuple[tuple[int, int], ...]]] = []
    for run in re.finditer(r"[a-z0-9]+", text):
        mask = weather.start_hint(run.group())
        if mask:
            found.append((run.start(), ((0, mask),)))
    return found


@settings(max_examples=400, deadline=None)
@given(text=texts)
def test_no_candidate_run_means_no_weather_found(text: str) -> None:
    runs = _weather_runs(text)
    hints = weather.WEATHER_START | weather.CAUSE_START
    if not weather.candidate_in(text, runs) and "power" not in text and "blackout" not in text:
        assert weather.find_weather(text, hints=hints, runs=runs) is weather.NO_FINDINGS


@settings(max_examples=400, deadline=None)
@given(text=texts)
def test_an_unread_day_needs_a_hint_or_a_full_stop_between_digits(text: str) -> None:
    hints = 0
    for word in re.findall(r"[a-z0-9]+(?:['/-][a-z0-9]+)*", text):
        hints |= dates.word_hints(word)
    if dates.unreadable_possible(text, hints):
        assert hints & dates.UNREADABLE_HINTS or dates.dot_pair(text)


# Pieces of listings near an update stamp, and near what normalizing takes out of a text.
STAMP_PIECES = (
    "Updated", "updated", "UPDATED", "Last Updated:", "posted", "Posted on", "revised",
    "Modified", "edited", "As of", "as of", "AS OF", "update", "upd", "ated", "Jan 28",
    "1/19/2026", "01/09/2025", "5:13am", "1:58 PM", "17:30", "at", "on", "Closed", "Friday",
    "&amp;", "&eacute;", "&#x65;", "<b>", "</b>", "www.example.org", "https://x.org/updated",
    "(10)", "Two (2)", "#12", "\n", "\t", "  ", "a.m.", "p.m.", "\u00e9", "\u017f", "\u00a0", "w/o",
    "zero", "in the event of", "after school",
)  # fmt: skip
stamp_texts = st.lists(
    st.tuples(st.sampled_from(STAMP_PIECES), st.sampled_from((" ", "", ", ", ": ", "-"))),
    min_size=1,
    max_size=8,
).map(lambda parts: "".join(piece + mark for piece, mark in parts))


@settings(max_examples=600, deadline=None)
@given(text=stamp_texts)
def test_a_text_said_to_hold_no_stamp_holds_none(text: str) -> None:
    normalized, stamped = text_module.normalize_stamped(text)
    assert normalized == text_module.normalize(text)
    if not stamped:
        assert text_module.written_at(text) is None


def _abbreviation_periods_by_pattern(text: str) -> str:
    """:func:`text._drop_abbreviation_periods` as it read with its pattern at each full stop."""
    pieces: list[str] = []
    last = 0
    dot = text.find(".")
    while dot != -1:
        before = max(0, dot - text_module._LONGEST_ABBREVIATION)
        if dot and text_module._ABBREVIATION_BEFORE.search(text, before, dot) is not None:
            pieces.append(text[last:dot])
            last = dot + 1
        dot = text.find(".", dot + 1)
    return "".join((*pieces, text[last:]))


ABBREVIATION_PIECES = (
    "jan", "sept", "sep", "approx", "st", "mt", "wed", "x", "xjan", "5", "_", "é", "a",
    "fri", "closed", "jr", "min", "mins", "hrs", "tues", "thurs", "dec", "zzapprox",
)  # fmt: skip
abbreviation_texts = st.lists(
    st.tuples(st.sampled_from(ABBREVIATION_PIECES), st.sampled_from((".", ". ", " ", "..", ""))),
    min_size=1,
    max_size=8,
).map(lambda parts: "".join(piece + mark for piece, mark in parts))


@settings(max_examples=600, deadline=None)
@given(text=abbreviation_texts)
def test_an_abbreviation_is_found_where_its_pattern_finds_one(text: str) -> None:
    assert text_module._drop_abbreviation_periods(text) == _abbreviation_periods_by_pattern(text)


COUNT_PIECES = (
    "2", "12", "one", "done", "someone", "of", "school", "preschool", "another", "few", "x",
    "day", "days", "daysx", "week", "weeks", "weekday", "today", "-", " - ", "on", "the", "moon",
    "bathe", "_", "5", "22", "\t",
)  # fmt: skip
count_texts = st.lists(
    st.tuples(st.sampled_from(COUNT_PIECES), st.sampled_from((" ", "", "-", ", "))),
    min_size=1,
    max_size=8,
).map(lambda parts: "".join(piece + mark for piece, mark in parts))


@settings(max_examples=800, deadline=None)
@given(text=count_texts)
def test_a_counted_day_or_a_bare_day_is_found_where_its_pattern_finds_one(text: str) -> None:
    counted = dates._COUNTED_DAY.search(text) is not None
    assert (dates._COUNTED_DAY_BACKWARDS.search(text[::-1]) is not None) is counted
    bare = dates._BARE_DAY.search(text) is not None
    assert (dates._BARE_DAY_FAST.search(text) is not None) is bare


# Patterns written so that each branch opens with a character of its own (see text.one_of),
# each held to the plain pattern it stands for.
MARK_PIECES = (
    "a", "p", "m", ".", "..", ",", ";", ":", "|", "!", "?", "/", "-", "--", " ", "  ", "\t",
    "\n", "but", "however", "xbut", "butx", "10", "9", "_", "a.m.", "p. m", "10a.m.", "x",
)  # fmt: skip
mark_texts = st.lists(st.sampled_from(MARK_PIECES), min_size=1, max_size=10).map("".join)
PLAIN_PATTERNS = (
    (parse._SENTENCE_END, r"\.(?=\s|$)|[;!?|]"),
    (parse._PARTING, r"[,;|!?]|[.:](?=\s)|(?:^|\s)-+(?=\s|$)"),
    (revoke._STRONG, r"[;!?|]|\.(?=\s|$)"),
    (revoke._WEAK, r"[,:/]|(?:^|\s)-+(?=\s|$)|\b(?:but|however)\b"),
    (revoke._MARKS, r"[;!?|,:/]|\.(?=\s|$)|(?:^|\s)-+(?=\s|$)"),
)


@settings(max_examples=800, deadline=None)
@given(text=mark_texts, start=st.integers(0, 6))
def test_a_mark_is_found_where_its_plain_pattern_finds_one(text: str, start: int) -> None:
    for pattern, plain in PLAIN_PATTERNS:
        expected = re.compile(plain, re.ASCII)
        assert [found.span() for found in pattern.finditer(text, start)] == [
            found.span() for found in expected.finditer(text, start)
        ]
        assert pattern.split(text) == expected.split(text)
    meridiem = re.compile(r"([ap])(?:(?<=\b[ap])|(?<=\d[ap]))\.\s?m\b\.?", re.ASCII)
    assert text_module._MERIDIEM.sub("m", text) == meridiem.sub(r"\1m", text)


TRIGGER = re.compile(
    "|".join(
        (
            "^(?:" + parse._VOCABULARY_START.pattern + ")",
            "^(?:"
            + text_module.trie(
                sorted(
                    {
                        *(prefix for group in mentions.PREFIX_STARTS for prefix in group),
                        *dates.SURE_STARTS,
                        *weather.START_PREFIXES,
                        "twenty",
                        "thirty",
                    }
                )
            )
            + ")",
            "^(?:" + dates.DATE_STARTS.pattern + ")",
            "^(?:" + weather.ANY_START.pattern + ")",
            mentions.ANY_PART.pattern,
            r"grade|hour|hr|min|noon|midday|early|power|blackout|thr|til|night|nite",
        )
    ),
    re.ASCII,
)
WORD_PIECES = (
    "a", "b", "e", "k", "l", "m", "o", "q", "u", "z", "clos", "dela", "snow", "ice", "mon",
    "hour", "night", "til", "thr", "grade", "am", "pm", "x", "1", "2",
)  # fmt: skip


@settings(max_examples=800, deadline=None)
@given(word=st.lists(st.sampled_from(WORD_PIECES), min_size=1, max_size=5).map("".join))
def test_a_word_triggers_a_scan_where_the_one_pattern_says_it_does(word: str) -> None:
    triggered = TRIGGER.search(word) is not None
    assert (parse._TRIGGER_START(word) is not None or parse._TRIGGER_PART(word) is not None) is (
        triggered
    )
    gates = re.compile(r"grade|hour|hr|min|noon|midday|early|power|blackout|thr|til|night|nite")
    assert (parse._GATES.search(word) is None) is (gates.search(word) is None)


# Pieces of listings near the words of a withdrawal, a field's answer, a date after a weekday
# name, and "only".
QUICK_PIECES = (
    "closed", "is", "was", "not", "true", "untrue", "false", "fake", "news", "in error",
    "by mistake", "mistakenly", "disregard", "ignore", "removed", "wrong", "incorrect", "an",
    "error", "only", "lonely", "at", "for", "in", "no", "none", "n/a", "0", "--", "evening", "snow",
    "night", "nite", "the", "jan", "mar", "21", "1/21", "monday", "tomorrow", "x",
)  # fmt: skip
QUICK_MARKS = (" ", " ", " ", ", ", ": ", " - ", "-", "/", ".", "  ", "_", "\t", "")
quick_texts = st.lists(
    st.tuples(st.sampled_from(QUICK_PIECES), st.sampled_from(QUICK_MARKS)),
    min_size=1,
    max_size=8,
).map(lambda parts: "".join(piece + mark for piece, mark in parts))


@settings(max_examples=800, deadline=None)
@given(text=quick_texts)
def test_a_withdrawal_holds_a_word_a_stretch_bit_says_it_holds(text: str) -> None:
    if parse._WITHDRAWAL_CUES.search(text) is not None:
        assert any(parse._WITHDRAWAL_PART(stretch) for stretch in text.split(" "))


@settings(max_examples=800, deadline=None)
@given(text=quick_texts)
def test_an_answer_no_starts_where_its_quick_look_says_it_can(text: str) -> None:
    for position in range(len(text) + 1):
        if parse._ANSWERED_NO.match(text, position) is not None:
            assert text.startswith(parse._ANSWER_LEADS, position)


@settings(max_examples=800, deadline=None)
@given(text=quick_texts)
def test_only_is_found_where_its_plain_pattern_finds_it(text: str) -> None:
    plain = re.compile(r"\bonly\b(?:\s+(?P<prep>at|for|in)\b)?", re.ASCII)
    expected = [(match.span(), match.span("prep")) for match in plain.finditer(text)]
    assert [(match.span(), match.span("prep")) for match in partial._ONLY.finditer(text)] == (
        expected
    )


@settings(max_examples=800, deadline=None)
@given(
    word=st.sampled_from([*dates._PLAIN_WEEKDAYS, *dates._PLAIN_RELATIVE]),
    rest=quick_texts,
)
def test_a_plain_day_that_takes_more_is_matched_as_the_atom_pattern_matches_it(
    word: str, rest: str
) -> None:
    text = word + rest
    code = dates._PLAIN_CODES[word]
    if dates._plain_atom(text, 0, code) is not None:
        return
    expected = dates._match_atom(text, 0)
    found = dates._match_plain(text, 0, code)
    assert (found is None) is (expected is None)
    if found is not None and expected is not None:
        assert found.span() == expected.span()
        assert found.lastgroup == expected.lastgroup
        assert found.groupdict() == expected.groupdict()


@settings(max_examples=800, deadline=None)
@given(text=quick_texts)
def test_a_text_of_stretches_that_read_as_written_is_its_own_normalized_text(text: str) -> None:
    read = parse._read_stretches(text)
    if read is not None:
        normalized, facts = read
        assert normalized == " ".join(stretch[6] for stretch in facts)


@settings(max_examples=600, deadline=None)
@given(
    text=quick_texts,
    at=st.integers(0, 200),
    bracket=st.sampled_from("{}[]<>"),
    slot=st.sampled_from(("", "date", "DATE", "{date}", "Insert date")),
)
def test_a_text_with_a_bracket_is_never_read_stretch_by_stretch(
    text: str, at: int, bracket: str, slot: str
) -> None:
    # (parse_status looks for a template's slot in such a text only when normalize reads it:
    # one read stretch by stretch can hold a "%DATE%" slot alone.)
    at = min(at, len(text))
    assert parse._read_stretches(text[:at] + bracket + slot + text[at:]) is None


CLOCK_PIECES = (
    "at", "@", "by", "until", "till", "'til", "10", "10:30", "1", "12", "9a", "1 pm", "2pm",
    "noon", "12 noon", "midday", "staff", "report", "closing", "mar 16", "1/21", "a", "p",
    "am", "today", "x",
)  # fmt: skip
clock_texts = st.lists(
    st.tuples(st.sampled_from(CLOCK_PIECES), st.sampled_from(QUICK_MARKS)),
    min_size=1,
    max_size=8,
).map(lambda parts: "".join(piece + mark for piece, mark in parts))


def _clocks_by_pattern(text: str, start: int, end: int) -> set[str]:
    """:func:`mentions._clocks` as it read before its quick looks at the span."""
    return {
        match.group("clock") or match.group("strict")
        for match in mentions._HARVEST_CLOCK.finditer(text, start, end)
        if not mentions._another_subject(text, start, match.start())
    }


@settings(max_examples=800, deadline=None)
@given(text=clock_texts, start=st.integers(0, 12), length=st.integers(0, 40))
def test_a_clock_time_is_found_where_its_pattern_finds_one(
    text: str, start: int, length: int
) -> None:
    end = min(len(text), start + length)
    assert mentions._clocks(text, start, end) == _clocks_by_pattern(text, start, end)


HEADING_PIECES = (
    "monday", "morning", "afternoon", "evening", "am", "pm", "night", ":", "closed", "x",
)  # fmt: skip


@settings(max_examples=800, deadline=None)
@given(
    text=st.lists(
        st.tuples(st.sampled_from(HEADING_PIECES), st.sampled_from(QUICK_MARKS)),
        min_size=1,
        max_size=6,
    ).map(lambda parts: "".join(piece + mark for piece, mark in parts))
)
def test_a_heading_ends_where_its_pattern_says_it_does(text: str) -> None:
    for end in range(len(text) + 1):
        group = (0, end, (), (), None)
        assert parse._heading(text, group) is (parse._HEADING_END.match(text, end) is not None)


@settings(max_examples=800, deadline=None)
@given(text=quick_texts, start=st.integers(0, 40))
def test_a_negation_before_a_term_holds_no_or_without(text: str, start: int) -> None:
    low = max(0, start - 32)
    if weather._NEGATED.search(text, low, start) is not None:
        assert "no" in text[low:start] or "without" in text[low:start]


LENGTH_PIECES = (
    "2", "1", "90", "1/2", "11/2", "1.5", "0", "one", "two", "a", "an", "half", "and", "hour",
    "hours", "hr", "h", "minutes", "min", "m", "thirty", "twenty", "five", "ten", "fifteen",
    "delayed", "delay", "late start", "early dismissal", "early release", "until", "at", "@",
    "is", "will be", "of", "by", "for", "tomorrow", "monday", "jan 21", "1/21", "thru", "noon",
    "10:30", "pm", "early", "x",
)  # fmt: skip
length_texts = st.lists(
    st.tuples(st.sampled_from(LENGTH_PIECES), st.sampled_from(QUICK_MARKS)),
    min_size=1,
    max_size=8,
).map(lambda parts: "".join(piece + mark for piece, mark in parts))


def _without_looks(pattern: str) -> str:
    for look in (
        text_module._HALF_LOOK, text_module._MINUTES_LOOK, mentions._DELAY_TAIL_LOOK,
        mentions._EARLY_TAIL_LOOK,
    ):  # fmt: skip
        pattern = pattern.replace(look, "")
    return pattern


def _spans(match: re.Match[str] | None) -> list[tuple[int, int]] | None:
    return None if match is None else [match.span(group) for group in range(match.re.groups + 1)]


@settings(max_examples=600, deadline=None)
@given(text=length_texts)
def test_a_length_or_a_status_is_matched_as_its_pattern_without_looks_matches_it(
    text: str,
) -> None:
    patterns = [re.compile(text_module.DURATION, re.ASCII)]
    patterns += list({selected[2] for selected in mentions._selected(mentions.RULE_BITS)})
    for pattern in patterns:
        plain = re.compile(_without_looks(pattern.pattern), pattern.flags)
        for position in range(len(text)):
            assert _spans(pattern.match(text, position)) == _spans(plain.match(text, position))


BRACKET_PIECES = (
    "Today", "today", "TOMORROW", "tmrw", "2nite", "yesterday", "xtoday", "(", "( ", "Thu",
    "thursday", "FRI", "fri.", "Mon,", ")", "x", "tom", "_today", "1today", "café",
)  # fmt: skip


@settings(max_examples=800, deadline=None)
@given(
    text=st.lists(
        st.tuples(st.sampled_from(BRACKET_PIECES), st.sampled_from(QUICK_MARKS)),
        min_size=1,
        max_size=8,
    ).map(lambda parts: "".join(piece + mark for piece, mark in parts))
)
def test_a_bracketed_weekday_is_taken_out_as_its_pattern_takes_it_out(text: str) -> None:
    expected = text_module._BRACKETED_WEEKDAY.sub(r"\g<day> ", text)
    assert text_module._bracketed_weekdays(text) == expected


@settings(max_examples=600, deadline=None)
@given(text=quick_texts, start=st.integers(0, 30), length=st.integers(0, 40))
def test_the_words_of_a_span_are_read_the_same_from_the_table(
    text: str, start: int, length: int
) -> None:
    end = start + length
    first = text_module.words(text, start, end)
    assert first == text_module._words(text[start:end])
    first.append("x")  # (each call gets a list of its own: the table's words stay as read)
    assert text_module.words(text, start, end) == text_module._words(text[start:end])


@settings(max_examples=800, deadline=None)
@given(text=quick_texts.map(lambda text: text + " 2019 1/20 just"))
def test_the_text_bits_of_its_stretches_say_what_the_text_holds(text: str) -> None:
    for sample in (text, text[: len(text) // 2], text[len(text) // 3 :]):
        normalized = text_module.normalize(sample)
        bits = 0
        for chunk in normalized.split(" "):
            bits |= parse._chunk_lookup(chunk)[0]
        assert bool(bits & parse._YEAR_TEXT) is ("20" in normalized or "19" in normalized)
        assert bool(bits & parse._ONLY_TEXT) is ("only" in normalized or "just" in normalized)
        assert bool(bits & parse._CONTINUE_TEXT) is ("remain" in normalized or "stay" in normalized)
        assert bool(bits & parse._OPTION_TEXT) is (parse._OPTION_PART(normalized) is not None)
        assert bool(bits & parse._REPORT_TEXT) is ("report" in normalized)
        if parse._OPTION_HINT(normalized) is not None:  # (the bit gates that look)
            assert bits & parse._OPTION_TEXT
        if parse._WITHDRAWAL_CUES.search(normalized) is not None:
            assert bits & parse._WITHDRAWAL_TEXT


# Pieces near the words of the answer, alternative, change and count quick looks.
GATE_PIECES = (
    "closed", "delay", "or", "and/or", "or/and", "either/or", "order", "to", "into", "(to",
    "onto", "no", "n", "n/a", "none", "false", "0", "00", "0:00", "00:00", "10:00", "1:00",
    "at", "in", "for", "2", "12", "schools", "schools-based", "sites", "campuses", "school",
    "non", "non-closed", "post-closure", "pre-k", "x",
)  # fmt: skip
GATE_MARKS = (" ", " ", " ", ", ", ": ", " - ", "-", "/", ",", "")
gate_texts = st.lists(
    st.tuples(st.sampled_from(GATE_PIECES), st.sampled_from(GATE_MARKS)),
    min_size=1,
    max_size=8,
).map(lambda parts: "".join(piece + mark for piece, mark in parts))


def _rare_bits(text: str) -> int:
    """The rare bits of a text's stretches, as the parser reads them (see parse._chunk_facts)."""
    bits = 0
    for stretch in text.split(" "):
        if stretch:
            bits |= parse._chunk_facts(stretch)[0]
    return bits >> parse._RARE_SHIFT


@settings(max_examples=800, deadline=None)
@given(text=gate_texts)
def test_a_form_answer_and_a_zero_time_are_found_where_their_quick_looks_say(text: str) -> None:
    for position in range(len(text) + 1):
        if parse._ANSWERED_FORM(text, position) is not None:
            assert len(text) - position <= parse._FORM_REACH or text[-1] == "0"
            assert text[-2:] in parse._FORM_ENDS
        if parse._ZERO_CLOCK(text, max(0, position - 9), position) is not None:
            assert text.endswith(parse._ZERO_CLOCKS, 0, position)
        if text.endswith(parse._ZERO_CLOCKS, 0, position):
            assert text[position - 2 : position - 1] in parse._ZERO_CLOCK_MARKS


@settings(max_examples=800, deadline=None)
@given(text=gate_texts)
def test_a_joining_word_or_a_prefix_is_in_the_stretch_bits(text: str) -> None:
    found = set(text_module.words(text))
    rare = _rare_bits(text)
    if found & {"or", "and/or", "or/and"}:
        assert rare & parse._OR_RARE
    if found & {"to", "into"}:
        assert rare & parse._TO_RARE
    for start in range(3, len(text)):
        # (A status word starts with a letter or a digit, right after the prefix's hyphen.)
        if (
            text[start].isalnum()
            and text[start - 1] == "-"
            and text.endswith(parse._STATUS_PREFIXES, 0, start)
        ):
            assert rare & parse._PREFIXED_RARE


@settings(max_examples=800, deadline=None)
@given(text=gate_texts)
def test_a_count_of_places_is_found_only_among_the_words(text: str) -> None:
    if partial._COUNTED_PLACE(text) is not None:
        assert partial._COUNTED_CUES & set(text_module.words(text))


# The pattern of a field answered no as written alternative by alternative, each reading the
# spaces before its mark again: parse._ANSWERED_NO reads them once and finds the same.
ANSWERED_NO_BY_ALTERNATIVE = re.compile(
    r"\s*(?::|-+)\s*(?:no|none|n/a|na|false|nope|not)(?=\s*(?:$|[;,.|!?]|-+(?:\s|$)|\s-))"
    r"|\s*(?::|-+)\s*n(?=\s*(?:$|[;,|!?]))"
    r"|\s*(?::|-+)\s*0+(?::0+)?(?=\s*(?:$|[;,|!?]|\.(?:\s|$)|-+(?:\s|$)|\s-))"
    r"|\s*:\s*-+(?=\s*(?:$|[;,|!?]|\.(?:\s|$)))"
    r"|(?P<empty>\s?:)(?=$| ?\|)",
    re.ASCII,
)
ANSWER_PIECES = (
    "closed", "delay", "no", "none", "n/a", "na", "n", "not", "nope", "false", "0", "00", "0:00",
    "n.", "main", "x", "1", "--", "-", ":", "|", ";", ".", ",", "!", "  ", "   ", "\t", "",
)  # fmt: skip
ANSWER_MARKS = (" ", "", ":", " : ", " - ", "-", "--", "  ", "    ", "\n", "|", " |")
answer_texts = st.lists(
    st.tuples(st.sampled_from(ANSWER_PIECES), st.sampled_from(ANSWER_MARKS)),
    min_size=1,
    max_size=10,
).map(lambda parts: "".join(piece + mark for piece, mark in parts))


@settings(max_examples=1500, deadline=None)
@given(text=answer_texts)
def test_a_field_answered_no_is_read_as_its_alternatives_read_it(text: str) -> None:
    for position in range(len(text) + 1):
        found = parse._ANSWERED_NO.match(text, position)
        expected = ANSWERED_NO_BY_ALTERNATIVE.match(text, position)
        assert (found is None) is (expected is None), (text, position)
        if found is not None and expected is not None:
            assert found.span() == expected.span(), (text, position)
            assert found.group("empty") == expected.group("empty"), (text, position)


@settings(max_examples=800, deadline=None)
@given(text=gate_texts.filter(bool))
def test_a_text_s_answer_facts_are_read_as_each_status_reads_them(text: str) -> None:
    rare = _rare_bits(text)
    bits = (parse._COLON if ":" in text else 0) | parse._ANSWER
    fields, form, zero, either = parse._answers(text, bits, rare)
    assert fields == (":" in text or "-" in text)
    for position in range(len(text) + 1):
        assert (form == position) == (parse._ANSWERED_FORM(text, position) is not None)
        if text.startswith(parse._ANSWER_LEADS, position):
            lead = text[position : position + 1]
            if lead == " ":
                lead = text[position + 1 : position + 2]
            assert lead in parse._LEAD_CHARS
        if text.endswith(parse._ZERO_CLOCKS, 0, position):
            assert zero
    assert either == ("/n" in text or " or no" in text)


# Pieces of a stretch of letters and of words a stretch's text bits look for (see
# parse._text_bits), and of nouns spelt one letter off (see gate._misspelt_noun).
LETTER_PIECES = (
    "noon", "midday", "saturday", "sunday", "power", "blackout", "only", "just", "error",
    "true", "wrong", "withdrawn", "correct", "make", "moved", "instead", "typo", "change",
    "oops", "ba", "ku", "zo", "te", "mi", "ra", "x", "é", "20", "19", "0:00", ":", ".", "?",
    "-", "non-", "/n", "1.2", "opt", "who", "unable", "cannot", "quarantin", "isolat", "choose",
    "remain", "stay", "report",
)  # fmt: skip


def _text_bits_alone(chunk: str) -> int:
    """parse._text_bits as each of its looks reads a stretch, with no quick look first."""
    return (
        (parse._NOON if "noon" in chunk or "midday" in chunk else 0)
        | (parse._WEEKEND if "saturday" in chunk or "sunday" in chunk else 0)
        | (parse._COLON if ":" in chunk else 0)
        | (parse._POWER if "power" in chunk or "blackout" in chunk else 0)
        | (parse._DOT_PAIR if "." in chunk and dates.dot_pair(chunk) else 0)
        | (parse._HELD_HINT if "?" in chunk else 0)
        | (parse._WITHDRAWAL_TEXT if parse._WITHDRAWAL_PART(chunk) is not None else 0)
        | (parse._YEAR_TEXT if "20" in chunk or "19" in chunk else 0)
        | (parse._ONLY_TEXT if "only" in chunk or "just" in chunk else 0)
        | (parse._PREFIXED_TEXT if "-" in chunk and parse._STATUS_PREFIX(chunk) is not None else 0)
        | (parse._ZERO_TEXT if "0:00" in chunk else 0)
        | (parse._SLASH_N_TEXT if "/n" in chunk else 0)
        | (parse._CORRECTION_TEXT if parse._CORRECTION_PART(chunk) is not None else 0)
        | (parse._OPTION_TEXT if parse._OPTION_PART(chunk) is not None else 0)
        | (parse._CONTINUE_TEXT if "remain" in chunk or "stay" in chunk else 0)
        | (parse._REPORT_TEXT if "report" in chunk else 0)
    )


@settings(max_examples=1500, deadline=None)
@given(pieces=st.lists(st.sampled_from(LETTER_PIECES), min_size=1, max_size=4))
def test_a_stretch_s_text_bits_are_its_looks_bits(pieces: list[str]) -> None:
    chunk = "".join(pieces)
    assert parse._text_bits(chunk) == _text_bits_alone(chunk), chunk


def _misspelt_noun_alone(token: str) -> int:
    """gate._misspelt_noun with every word one letter off looked up, in order."""
    found = gate._NOUN_DELETIONS.get(token, 0)
    for short in gate._deletions(token):
        found = found or gate._NOUNS.get(short, 0) or gate._NOUN_DELETIONS.get(short, 0)
    return found


_LONG_NOUNS = sorted(word for word in gate._NOUNS if len(word) >= 6 and word.isalpha())


@settings(max_examples=1500, deadline=None)
@given(
    noun=st.sampled_from(_LONG_NOUNS),
    edit=st.sampled_from(("drop", "add", "change", "swap", "none", "name")),
    place=st.integers(min_value=0, max_value=20),
    letter=st.sampled_from("abcdeiklmnorstuyz"),
)
def test_a_noun_spelt_one_letter_off_is_found_as_every_lookup_finds_it(
    noun: str, edit: str, place: int, letter: str
) -> None:
    word = list(noun)
    index = place % len(word)
    if edit == "drop":
        del word[index]
    elif edit == "add":
        word.insert(index, letter)
    elif edit == "change":
        word[index] = letter
    elif edit == "swap" and index + 1 < len(word):
        word[index], word[index + 1] = word[index + 1], word[index]
    elif edit == "name":
        word = list(letter + "akuzotemira"[: 6 + place % 6])
    token = "".join(word)
    if len(token) >= gate._MISSPELT_LENGTH:
        assert gate._misspelt_noun(token) == _misspelt_noun_alone(token), token
