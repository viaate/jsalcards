"""The part of a day a closure is limited to: "closed this afternoon", "closed after 11:30".

A closure is for whole days unless the words beside it say otherwise. Closed for
the afternoon ("closed this afternoon", "closed Wednesday PM", "Wednesday
afternoon: closed", "closed for the afternoon", "closed after lunch") or from a
time on ("closed after 11:30", "closed from noon") sends students home during a
day that has begun: an early dismissal, at that time when one is given. Closed
for the morning ("closed Wednesday AM", "closed tomorrow morning") is a late
start when the text says when school opens ("closed tomorrow until 10") and
otherwise states nothing anyone can act on. A part of the day before a program
noun ("closed AM kindergarten") closes that program, and a time after the school
day ("closed after 5 PM") closes the building for the evening.

:func:`closure_bounds` reads these around one closure, given the date groups the
closure holds. A part named right after the closure words ("closed PM"), or
before them as a heading of its own ("PM: closed"), bounds every day of the
closure; one named with a day ("Wednesday afternoon", "this afternoon") bounds
that day only, so "closed this afternoon and tomorrow" is an early dismissal
today and a closure tomorrow. A weekday's "Morning:" heading at the start of an
entry ("Tuesday Morning: Closed") is a closings page's slot for the whole day
(see :func:`slot_heading`), which the parser reads as such unless the day's
other slots say the school opens later. Before a closure that names its own
days, any slot heading only names a day: "Tuesday Afternoon: Closed Tuesday"
closes Tuesday, while "Tuesday Afternoon: Closed" alone is the afternoon
slot's early closing. What cannot be told apart safely is ``unclear``:
a part after a list of days ("closed Monday and Tuesday afternoon"), a part
beside a range of days ("closed Wednesday afternoon through Friday"), a window
of hours ("closed from 8 to noon"), or two parts that disagree.
"""

import re
from collections.abc import Sequence
from datetime import time
from typing import Literal, NamedTuple

from snowlight.classify.dates import (
    ATOM_END,
    ATOM_EVENING,
    ATOM_KIND,
    ATOM_MODIFIER,
    ATOM_START,
    GROUP_ATOMS,
    GROUP_END,
    GROUP_LINKS,
    GROUP_OPEN_START,
    GROUP_START,
    DateAtom,
    DateGroup,
)
from snowlight.classify.lexicon import MODIFIERS, SCOPES
from snowlight.classify.text import CLOCK, by_char, clock_time

type Part = Literal["afternoon", "morning", "program", "evening", "unclear"]
"""What a bound leaves of the closure: the afternoon (an early dismissal), the morning (a late
start), part of the program, the evening after school, or a reading nobody can trust."""


class Bound(NamedTuple):
    """The part of the day a closure is limited to, with the time that bounds it if any."""

    part: Part
    dismissal: time | None = None  # "afternoon": when students go home ("after 11:30")
    opens_at: time | None = None  # "morning": when school opens ("until 10")


class Split(NamedTuple):
    """A closure whose days are bounded differently: "closed this afternoon and tomorrow".

    Each piece is a bound (``None``: the whole day stays closed) and the date
    groups it holds for.
    """

    pieces: tuple[tuple[Bound | None, tuple[DateGroup, ...]], ...]


UNCLEAR = Bound("unclear")
# The bound of each part of the day with no time, shared: a bound is never changed.
_BOUNDS: dict[Part, Bound] = {
    part: Bound(part) for part in ("afternoon", "morning", "program", "evening", "unclear")
}
_BOUNDS["unclear"] = UNCLEAR
_new = tuple.__new__  # builds a named tuple from its fields without a Python-level call

# A closure from a time on is an early dismissal from 9 a.m. to 2:30 p.m. Before that the school
# day has hardly begun ("closed from 8 am" closes the day), and after it the time is when school
# lets out anyway, so "closed after 3:30" can be facility hours as much as an early release;
# from 4:30 p.m. it is the evening ("closed after 5 PM").
_EARLIEST_DISMISSAL = time(9, 0)
_LATEST_DISMISSAL = time(14, 30)
_EVENING = time(16, 30)
_EARLIEST_OPENING = time(6, 0)
_LATEST_OPENING = time(13, 0)

_PARTS: dict[str, Part] = {
    "morning": "morning",
    "mornings": "morning",
    "am": "morning",
    "afternoon": "afternoon",
    "afternoons": "afternoon",
    "pm": "afternoon",
}
_PART_WORD = r"(?:mornings?|afternoons?|am|pm)"
# A part of the day right after the closure or a day: "closed PM", "closed for the afternoon",
# "closed in the morning", "closed all afternoon", "closed the rest of the afternoon". ("this
# afternoon" is a date group of its own; see _inner_part.) A second part after it ("AM and PM")
# names the whole day.
_PART = re.compile(
    r" (?:(?:for|in|during|through|thru|throughout)\s+)?(?:(?:the|all)\s+)?"
    r"(?:(?:rest|remainder|balance)\s+of\s+the\s+)?"
    rf"(?P<part>{_PART_WORD})\b(?!['-])"
    rf"(?:\s*(?:and|or|&|/)\s*(?P<other>{_PART_WORD})\b)?"
    r"(?:\s+(?:sessions?|only))?",
    re.ASCII,
)
# A time the closure runs from, or until: "after 11:30", "from noon", "starting at 1 pm", "after
# lunch", "after 1st period"; "until 10", "till noon"; or a time it comes at, which says no more
# than that unless it is the evening ("closed at 1 pm", "classes cancelled at 1 pm"; "closed at
# 5 pm" closes the building after school).
_TIMED = re.compile(
    r" (?:(?P<until>until|till|til)|(?P<at>at)|after|from|starting(?:\s+at)?|beginning(?:\s+at)?"
    r"|as\s+of|effective(?:\s+at)?)\s+"
    rf"(?:(?P<clock>{CLOCK})\b|(?P<meal>lunch(?:time)?|recess)\b"
    r"|(?P<period>(?:the\s+)?(?:first|second|third|fourth|1st|2nd|3rd|4th)\s+"
    r"(?:period|hour|block|class))\b)",
    re.ASCII,
)
# The words, or their starts, that the space before a bound can be followed by: the first
# words _PART and _TIMED can read after it. With none of them there, neither can match. ("At"
# only before a time: "closed at 1 pm", "at noon"; "at all schools" bounds nothing.)
_BOUND_WORDS = (
    "for", "in", "during", "thr", "the", "all", "rest", "remainder", "balance", "morning",
    "afternoon", "am", "pm", "until", "til", "after", "from", "starting", "beginning", "as",
    "effective", *(f"at {digit}" for digit in "0123456789"), "at noon", "at midday",
)  # fmt: skip
_BOUND_BY_FIRST = by_char(_BOUND_WORDS, 0)  # (by their first character)
_BOUND_MARKS = frozenset({",", ":"})  # the marks a bound can come after (never "": see there)
# A time that starts a window of hours: "from 8 to noon", "after 12-3" (not "until 10 - 2 hour
# delay", where the number is a length).
_WINDOW = re.compile(
    r"\s*(?:-|to|until|till|'?til|thru|through)\s*(?:noon|midday|\d{1,2}(?:[:.]\d\d)?(?:\s*[ap]m)?\b"
    r"(?!\s*-?\s*(?:hours?|hrs?|h|minutes?|mins?|m)\b))",
    re.ASCII,
)
_NEXT_WORD = re.compile(r" ([a-z0-9][a-z0-9'/-]*)", re.ASCII)
# A comma or a colon before a bound (up to the space before it), and the end of a phrase.
_MARKS_SPACED = (", ", ": ")
_PHRASE_END = re.compile(r"\s*(?:[,;.!?|]|-|$)", re.ASCII)
# A second part of the day after a day that names one: "this morning and afternoon".
_AND_PART = re.compile(rf"\s*(?:and|&|/)\s*(?:the\s+)?({_PART_WORD})\b", re.ASCII)
# What may follow a bare hour ("after 12") for it to be a time and not a count ("after 2 snow
# days"): the end, a mark, a date ("after 12 1/21") or one of these words.
_AFTER_HOUR = frozenset(
    {
        "today", "tomorrow", "tonight", "due", "because", "for", "and", "on", "o'clock",
        "oclock", "this", "so", "as", "with", "through", "thru", "until", "till", "til",
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "mon",
        "tue", "tues", "wed", "weds", "thu", "thur",
        "thurs", "fri", "sat", "sun", "jan", "january", "feb", "february", "mar", "march", "apr",
        "april", "jun", "june", "jul", "july", "aug", "august", "sep", "sept", "september", "oct",
        "october", "nov", "november", "dec", "december",
    }
)  # fmt: skip
_NUMERIC_DATE = re.compile(r"\d{1,2}/\d{1,2}(?:/\d{2,4})?\Z", re.ASCII)
_MARKS = frozenset(",;.:!?|-")
# A part of the day as a heading of its own, right before the closure: "PM: closed", "AM - closed".
_HEADING_MARKS = ":-"
_HEADING_TAIL = frozenset(_HEADING_MARKS + " ")  # (what a heading ends with)
# A part of the day right before a colon, as a slot heading writes it (see _bound_at).
_SLOT_PARTS = (" morning:", " afternoon:")
FAST_PATH = True
"""Whether the shortcuts for the most common bounds are taken (tests compare both ways)."""
# The slots after a weekday that heads an entry: "Tuesday Morning:", "Tuesday Afternoon:" (see
# slot_heading).
_SLOTS: dict[str, re.Pattern[str]] = {
    "morning": re.compile(r" morning ?:", re.ASCII),
    "afternoon": re.compile(r" afternoon ?:", re.ASCII),
}
# The words that end a school's name, after which an entry can start (see entry_start).
_NAME_ENDS = frozenset(
    {
        "elementary", "school", "schools", "academy", "high", "middle", "intermediate",
        "primary", "district", "isd", "usd", "cusd", "preschool", "montessori", "prep",
        "preparatory", "center", "campus", "charter",
    }
)  # fmt: skip
# The words that open a bound after a closure word, for the mention rules (see
# snowlight.classify.mentions): "closing after lunch", "closing this afternoon".
_BOUND_START = re.compile(
    r" (?:this\s+(?:morning|afternoon)\b|(?:(?:for|in|during|all)\s+)?(?:the\s+)?"
    rf"{_PART_WORD}\b|(?:until|till|til|after|from|starting|beginning|as\s+of|effective)\s)",
    re.ASCII,
)


def _timed_at(text: str, position: int, at: bool = True) -> tuple[Bound, int] | None:
    """The bound a time or a meal right at ``position`` sets: " after 11:30", " until 10"; with
    ``at``, a time the closure comes at too (" at 1 pm")."""
    match = _TIMED.match(text, position)
    if match is None or (not at and match.group("at") is not None):
        return None
    end = match.end()
    clock = match.group("clock")
    if clock is None:
        return _BOUNDS["afternoon"], end  # "after lunch", "after 1st period"
    if _WINDOW.match(text, end) is not None:
        return UNCLEAR, end
    if clock.isdigit() and (match.group("at") is not None or not _clear_after(text, end)):
        return None  # "after 2 snow days": a count, not a time; "at 3 schools" a place
    value = clock_time(clock)
    if match.group("at") is not None:
        # "closed at 1 pm": when, not from when; the evening is the building's ("at 5 pm").
        return (_BOUNDS["evening"] if value is not None and value >= _EVENING else UNCLEAR), end
    return _clock_bound(value, until=match.group("until") is not None), end


def _leading_bound(text: str, start: int) -> Bound | None:
    """The bound a time before the closure words sets, between who is closed and the closure:
    "Classes before 10 am cancelled" (a late start, as "cancelled until 10 am"), "All classes
    after 3 pm Thursday canceled" (as "cancelled after 3 pm"), "Classes before 3:45 PM on 1/22
    closed". A bare hour is no time here ("after 2 snow days")."""
    # (A mark between the time and the closure keeps the pattern from matching: "Open after
    # 10 am, classes cancelled".)
    low = max(0, start - _LEADING_REACH)
    window = text[low:start]
    if _CLOCK_HINT(window) is None or _LEADING_HINT(window) is None:
        return None  # (no time there, or no word before one)
    match = _LEADING.search(text, low, start)
    if match is None or match.group("clock").isdigit():
        return None
    value = clock_time(match.group("clock"))
    return _clock_bound(value, until=match.group("prep") in _LEADING_UNTIL)


# A time before the closure words, after who is closed: "classes before 10 am cancelled", "all
# classes after 3 pm Thursday are canceled", "classes before 3:45 pm on 1/22 closed" (see
# _leading_bound): its word, its time, and a day and the verb's helpers after it.
_LEADING = re.compile(
    rf"\b(?P<prep>before|until|till|til|after|from)\s+(?P<clock>{CLOCK})"
    r"(?:\s+on)?(?:\s+[a-z0-9][a-z0-9/.]*){0,2}?"
    r"(?:\s+(?:are|is|were|was|will\s+be|have\s+been|has\s+been|to\s+be|being))?\s*\Z",
    re.ASCII,
)
_LEADING_UNTIL = frozenset({"before", "until", "till", "til"})
# The links before the last day of a run, whose time is when the run ends (see _atom_bounds).
_RUN_END_LINKS = frozenset({"range", "until", "first"})
_LEADING_REACH = 48
# (What every match of _LEADING holds: a word before a time, and the time.)
_LEADING_HINT = re.compile(r"\b(?:before|until|till|til|after|from)\s", re.ASCII).search
_CLOCK_HINT = re.compile(r"\d|noon|midday", re.ASCII).search


def _leading_found(text: str, start: int, end: int) -> tuple[Bound, int] | None:
    """The bound a time before the closure at ``start``-``end`` sets, as :func:`_bound_at`
    gives one: "Classes before 10 am cancelled" (see :func:`_leading_bound`)."""
    leading = _leading_bound(text, start)
    return None if leading is None else (leading, end)


def _clock_bound(value: time | None, *, until: bool) -> Bound:
    """The bound a closure until a time ("until 10") or from one ("after 11:30") sets."""
    if until:
        if value is None or not _EARLIEST_OPENING <= value <= _LATEST_OPENING:
            return UNCLEAR
        return _new(Bound, ("morning", None, value))
    if value is not None and value >= _EVENING:
        return _BOUNDS["evening"]  # "closed after 5 PM": the building, after school
    if value is None or not _EARLIEST_DISMISSAL <= value <= _LATEST_DISMISSAL:
        return UNCLEAR
    return _new(Bound, ("afternoon", value, None))


def _clear_after(text: str, position: int) -> bool:
    """Whether a bare hour ending at ``position`` stands as a time: at the end, a mark or a day."""
    if position >= len(text) or text[position] in _MARKS:
        return True
    following = _NEXT_WORD.match(text, position)
    word = "" if following is None else following.group(1)
    return word in _AFTER_HOUR or _NUMERIC_DATE.match(word) is not None


def _bound_at(text: str, position: int, at: bool = True) -> tuple[Bound, int] | None:
    """The bound that starts right at ``position`` (a space after a closure or a day), if any.

    After a comma or a colon (a bracket becomes a comma) the bound must end its
    phrase: "closed tomorrow (afternoon only)", "closed today (after 12:30)";
    "closed tomorrow, PM activities cancelled" names something else.
    """
    mark = text[position : position + 1]
    if mark in _BOUND_MARKS:
        return _marked_bound_at(text, position, at)
    if mark != " " or not text.startswith(
        _BOUND_BY_FIRST.get(text[position + 1 : position + 2], ()), position + 1
    ):
        return None  # (see _BOUND_WORDS)
    if FAST_PATH and text.startswith(_SLOT_PARTS, position):
        # A closings page's slot heading, " Morning:" or " Afternoon:": the part alone, as
        # _PART reads it there (a colon follows it, which neither another part, a noun nor a
        # time can come after).
        part: Part = "morning" if text[position + 1] == "m" else "afternoon"
        return _BOUNDS[part], position + len(part) + 1
    match = _PART.match(text, position)
    return _timed_at(text, position, at) if match is None else _part_at(text, match)


def _part_at(text: str, match: re.Match[str]) -> tuple[Bound, int] | None:
    """The bound a part of the day sets (see :data:`_PART`), with a time after it if any."""
    part = _PARTS[match.group("part")]
    end = match.end()
    other = match.group("other")
    if other is not None and _PARTS[other] != part:
        return None  # "AM and PM": the whole day
    following = _NEXT_WORD.match(text, end)
    if following is not None and (following.group(1) in SCOPES or following.group(1) in MODIFIERS):
        return _BOUNDS["program"], end  # "closed AM kindergarten": part of the program
    timed = _timed_at(text, end)
    if timed is None:
        return _BOUNDS[part], end
    bound, end = timed
    return (bound if bound.part == part else UNCLEAR), end


def _marked_bound_at(text: str, position: int, at: bool = True) -> tuple[Bound, int] | None:
    """A bound after a comma or a colon, which must end its phrase (see :func:`_bound_at`)."""
    found = _bound_at(text, position + 1, at) if text.startswith(_MARKS_SPACED, position) else None
    if found is None or _PHRASE_END.match(text, found[1]) is None:
        return None
    return found


def _heading(text: str, start: int) -> Bound | None:
    """A part of the day alone before a mark, heading the closure: "PM: closed", "AM - closed"."""
    last = start  # (the text before the closure, less the spaces at its end)
    while last and text[last - 1].isspace():
        last -= 1
    if not last or text[last - 1] not in _HEADING_MARKS:
        return None
    # The heading's last word ends before the marks and spaces at its end; the text before
    # the word, less the spaces at its end, must end with a mark (read in place: the text
    # before a closure can be long).
    end = last - 1
    while end and text[end - 1] in _HEADING_TAIL:
        end -= 1
    word_start = text.rfind(" ", 0, end) + 1
    part = _PARTS.get(text[word_start:end])
    if part is None:
        return None
    before = word_start
    while before and text[before - 1].isspace():
        before -= 1
    if before and text[before - 1] not in _MARKS:
        return None  # "Wednesday afternoon: closed" is read with its day; see closure_bounds
    return _BOUNDS[part]


def slot_heading(
    text: str, group: DateGroup, part: Literal["morning", "afternoon"] = "morning"
) -> bool:
    """Whether a weekday heads its entry as a closings page's slot: "Tuesday Morning:".

    Some closings pages split each day into a morning, an afternoon and an
    evening slot and head each slot's status with it ("Tuesday Morning: Closed |
    Tuesday Afternoon: Closed"), showing only the slots still to come. The
    morning slot is where the school day's status goes: "Tuesday Morning:
    Closed" closes Tuesday, as "Tuesday Morning: 2 hour delay" delays it. The
    heading must start an entry (see :func:`entry_start`) and name one weekday
    alone: "this Tuesday morning:", "tomorrow morning:", "Tuesday, Jan. 20
    morning:" and "Tuesday AM:" are words about the morning, not the slot.
    ``part`` names the slot: the morning, or the afternoon ("Tuesday Afternoon:").
    """
    if len(group[GROUP_ATOMS]) != 1:
        return False
    atom = group[GROUP_ATOMS][0]
    if atom[ATOM_KIND] != "weekday" or atom[ATOM_EVENING] or atom[ATOM_MODIFIER] is not None:
        return False
    return _SLOTS[part].match(text, group[GROUP_END]) is not None and entry_start(
        text, group[GROUP_START]
    )


def entry_start(text: str, position: int) -> bool:
    """Whether an entry of a listing can start at ``position``.

    It can at the start of the text, after a mark, or right after a school's
    name ("Lincoln Elementary Tuesday Morning: Closed").
    """
    end = position  # (the text before the place, less the spaces at its end)
    while end and text[end - 1].isspace():
        end -= 1
    if not end or text[end - 1] in _MARKS:
        return True
    return text[text.rfind(" ", 0, end) + 1 : end] in _NAME_ENDS


def _inner_part(text: str, atom: DateAtom) -> Bound | None:
    """The part of the day a date atom names itself: "this afternoon", "this morning"."""
    if atom[ATOM_KIND] != "relative":
        return None
    if text.endswith("afternoon", atom[ATOM_START], atom[ATOM_END]):
        return _BOUNDS["afternoon"]
    if text.endswith("morning", atom[ATOM_START], atom[ATOM_END]):
        return _BOUNDS["morning"]
    return None


def _combine(first: Bound | None, second: Bound) -> Bound:
    """One bound from two said of the same day ("tomorrow morning ... until 10")."""
    if first is None or first == second:
        return second
    if first.part != second.part:
        return UNCLEAR
    for mine, theirs in ((first.dismissal, second.dismissal), (first.opens_at, second.opens_at)):
        if mine is not None and theirs is not None and mine != theirs:
            return UNCLEAR  # two times for one day
    return Bound(
        first.part,
        second.dismissal if first.dismissal is None else first.dismissal,
        second.opens_at if first.opens_at is None else first.opens_at,
    )


def time_follows(text: str, position: int) -> bool:
    """Whether "after" at ``position`` starts a time of the day: "after 11:30", "after lunch".

    Such an "after" bounds the day rather than ending the words that date the
    status ("closed after 11:30 today and all day tomorrow").
    """
    return (
        position > 0
        and text.startswith("after", position)
        and _timed_at(text, position - 1) is not None
    )


def bound_follows(text: str, position: int) -> bool:
    """Whether words that could bound a closure to part of a day start at ``position``.

    Used for "closing", which is a closure only when something says when:
    "closing after lunch", "closing this afternoon".
    """
    return _BOUND_START.match(text, position) is not None


def _one_day_bound(text: str, group: DateGroup) -> list[Bound | None] | None:
    """:func:`_atom_bounds` of one group of one day, the most common closure's ("Tuesday
    Morning: Closed"): no other day for a bound to reach into, and no list, range or
    restatement to read."""
    atom = group[GROUP_ATOMS][0]
    bound = _inner_part(text, atom)
    if bound is not None:
        also = _AND_PART.match(text, atom[ATOM_END])
        if also is not None and _PARTS[also.group(1)] != bound.part:
            bound = None  # "this morning and afternoon": the whole day
    # (A time at the end of a run is when it ends: "through Friday at 5 p.m.")
    found = _bound_at(text, atom[ATOM_END], group[GROUP_OPEN_START] is None)
    if found is not None:
        bound = _combine(bound, found[0])
    if bound is not None and group[GROUP_OPEN_START] is not None:
        return None  # "closed this afternoon through Friday"
    return [bound]


def _atom_bounds(text: str, groups: Sequence[DateGroup]) -> list[Bound | None] | None:
    """Each atom's own bound, in order; ``None`` when a bound sits where it cannot be placed."""
    if FAST_PATH and len(groups) == 1 and len(groups[0][GROUP_ATOMS]) == 1:
        return _one_day_bound(text, groups[0])
    bounds: list[Bound | None] = []
    # Where each atom starts, and the text's end: the next atom's start is at ``count + 1``.
    starts = [atom[ATOM_START] for group in groups for atom in group[GROUP_ATOMS]]
    starts.append(len(text))
    count = 0
    for index, group in enumerate(groups):
        inner: list[Bound | None] = []
        for number, atom in enumerate(group[GROUP_ATOMS]):
            count += 1
            limit = starts[count]  # where the next day starts: no bound reaches into it
            bound = _inner_part(text, atom)
            also = _AND_PART.match(text, atom[ATOM_END]) if bound is not None else None
            if also is not None and bound is not None and _PARTS[also.group(1)] != bound.part:
                bound = None  # "this morning and afternoon": the whole day
            found = _bound_at(
                text,
                atom[ATOM_END],
                group[GROUP_OPEN_START] is None
                and (not number or group[GROUP_LINKS][number - 1] not in _RUN_END_LINKS),
            )
            if found is not None and found[1] <= limit:
                if (
                    number
                    and group[GROUP_LINKS][number - 1] == "list"
                    and inner[number - 1] is None
                ):
                    return None  # "closed Monday and Tuesday afternoon": which days?
                bound = _combine(bound, found[0])
            inner.append(bound)
        if not any(inner):
            bounds.extend(inner)
            continue
        if (
            group[GROUP_OPEN_START] is not None
            or "range" in group[GROUP_LINKS]
            or "until" in group[GROUP_LINKS]
        ):
            return None  # "closed this afternoon through Friday"
        following = groups[index + 1] if index + 1 < len(groups) else None
        if (
            inner[-1] is not None
            and following is not None
            and following[GROUP_OPEN_START] is not None
            and not slot_heading(text, group)  # "Friday Morning: Closed thru January 14th"
        ):
            return None  # "closed Wednesday afternoon through Friday"
        if "appos" in group[GROUP_LINKS] or "lead" in group[GROUP_LINKS]:
            # "this afternoon, Jan. 20": one day named twice, so one bound for both.
            shared: Bound | None = None
            for bound in inner:
                if bound is not None:
                    shared = _combine(shared, bound)
            inner = [shared] * len(inner)
        bounds.extend(inner)
    return bounds


_SLOT_BOUND = Bound("morning")
_AFTERNOON_SLOT_BOUND = Bound("afternoon")


def _drop_slots(
    text: str,
    start: int,
    groups: Sequence[DateGroup],
    bounds: list[Bound | None],
    whole: Bound | None,
) -> None:
    """Read the slot headings of a closure with other words for its day as days alone.

    "Tuesday Morning: Closed after 11:30", "Tuesday Morning: Closed PM" and
    "Tuesday Morning: Closed tomorrow" say the rest themselves: the slot heading
    only names a day, as "Tuesday:" would. So does an afternoon slot heading
    when the closure's own words name whole days and nothing else bounds it:
    "Tuesday Afternoon: Closed Tuesday" closes Tuesday, as a closings page
    repeats the day's closure in each of its slots. (A slot heading alone
    before its closure is read in snowlight.classify.parse, which knows the
    day's other slots: "Tuesday Afternoon: Closed" alone is the afternoon.)
    """
    position = 0
    for group in groups:
        bound = bounds[position]
        if bound is not None and group[GROUP_END] < start:
            if bound == _SLOT_BOUND:
                if slot_heading(text, group):
                    bounds[position] = None
            elif (
                bound == _AFTERNOON_SLOT_BOUND
                and whole is None
                and bounds.count(None) == len(bounds) - 1  # (every other day is whole)
                and slot_heading(text, group, "afternoon")
            ):
                bounds[position] = None
        position += len(group[GROUP_ATOMS])


def own_bound(text: str, start: int, end: int) -> Bound | None:
    """What bounds the closure at ``start``-``end`` besides its days, if anything.

    The same as :func:`closure_bounds` given no date groups: a bound right
    after the closure ("closed PM", "closed after 11:30") or a part of the day
    heading it ("PM: closed").
    """
    found = _bound_at(text, end)
    return found[0] if found is not None else _heading(text, start)


def _bound_starts(text: str, position: int) -> bool:
    """Whether a bound can start at ``position``: what :func:`_bound_at` checks first."""
    mark = text[position : position + 1]
    if mark in _BOUND_MARKS:  # (see _marked_bound_at)
        return text[position + 1 : position + 2] == " " and text.startswith(
            _BOUND_BY_FIRST.get(text[position + 2 : position + 3], ()), position + 2
        )
    return mark == " " and text.startswith(
        _BOUND_BY_FIRST.get(text[position + 1 : position + 2], ()), position + 1
    )


def may_bound(
    text: str, start: int, end: int, groups: Sequence[DateGroup], leading: bool = True
) -> bool:
    """Whether :func:`closure_bounds` can find anything for the closure at ``start``-``end``.

    A quick look at where a bound would have to be: right after the closure or
    one of its days, a part of the day that is itself a day ("this afternoon"),
    a mark before the closure for a heading, or (with ``leading``: the text has
    a word a time before the closure follows, and a time) such a time. With
    none there, :func:`closure_bounds` returns ``None``.
    """
    if _bound_starts(text, end):
        return True
    last = start  # (as _heading reads the text before the closure)
    while last and text[last - 1].isspace():
        last -= 1
    if last and text[last - 1] in _HEADING_MARKS:
        return True
    if leading and _leading_bound(text, start) is not None:
        return True  # "Classes before 10 am cancelled"
    for group in groups:
        for atom in group[GROUP_ATOMS]:
            if _bound_starts(text, atom[ATOM_END]) or (
                atom[ATOM_KIND] == "relative"
                and text.endswith(("afternoon", "morning"), atom[ATOM_START], atom[ATOM_END])
            ):
                return True
    return False


def closure_bounds(
    text: str, start: int, end: int, groups: Sequence[DateGroup], leading: bool = True
) -> Bound | Split | None:
    """The part of the day the closure at ``start``-``end`` is limited to, if any.

    ``groups`` are the date groups the closure holds, in text order. Returns a
    :class:`Bound` for every day of the closure, a :class:`Split` when its days
    are bounded differently, or ``None`` when it closes whole days. With
    ``leading`` false, the text has no time before the closure words to look
    for (see :func:`_leading_bound`).
    """
    group_next = False
    for group in groups:
        if group[GROUP_START] == end + 1:
            group_next = True
            break
    found = (
        None
        if group_next
        else _bound_at(text, end) or (_leading_found(text, start, end) if leading else None)
    )
    whole = found[0] if found is not None else _heading(text, start)
    bounds = _atom_bounds(text, groups)
    if bounds is None:
        return UNCLEAR
    if len(bounds) > 1 or (whole is not None and bounds):
        _drop_slots(text, start, groups, bounds, whole)
    if whole is not None:
        if not bounds:
            return whole
        bounds = [_combine(bound, whole) for bound in bounds]
    if not any(bounds):
        return None
    first = bounds[0]
    if bounds.count(first) == len(bounds):  # (all the same)
        return first
    if UNCLEAR in bounds:
        return UNCLEAR
    pieces: dict[Bound | None, list[DateGroup]] = {}
    position = 0
    for group in groups:
        own = bounds[position : position + len(group[GROUP_ATOMS])]
        position += len(group[GROUP_ATOMS])
        if own.count(own[0]) == len(own):  # (all the same)
            pieces.setdefault(own[0], []).append(group)
            continue
        for atom, bound in zip(group[GROUP_ATOMS], own, strict=True):
            pieces.setdefault(bound, []).append(
                (atom[ATOM_START], atom[ATOM_END], (atom,), (), None)
            )
    return Split(tuple((bound, tuple(held)) for bound, held in pieces.items()))
