"""Status mentions: the phrases in a listing that state a status or a side note.

Each rule is a regular expression over the normalized text plus a builder that
turns a match into a :class:`Mention` (or rejects it). Matches from every rule
are collected, then overlapping ones are resolved in favour of the one that
starts first and, among those, the longest: "closing at noon" beats "closing",
"virtual snow day" beats "snow day", "no AM kindergarten" is one mention.

A mention's ``kind`` is a status (``closed``, ``delayed``, ``remote``,
``early_dismissal``), ``open`` (school runs as normal), ``note`` (news about
something other than the school day: activities, offices, part of the
program, buses) or ``ambiguous`` (a status word that does not say what it is
about, such as a bare "cancelled"). Which noun a status is about, and whether it
is negated, hedged or replaced, is decided later with the clause around it.

A word that can call a status off carries ``revokes``: "cancelled", "called
off" and "suspended" (``cancel``) can also mean the school itself is off
("School cancelled"), while "lifted", "rescinded", "revoked" and the like
(``revoke``, a mention of kind ``revoke``) only ever call something off. Which
status such a word calls off, if any, is decided with the text around it.
"""

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import time
from functools import lru_cache, reduce
from operator import or_
from typing import Literal

from snowlight.classify.dates import MONTH_NAMES, SCHOOL_DAY_WORDS, WEEKDAYS, names_day
from snowlight.classify.dayparts import bound_follows
from snowlight.classify.lexicon import MODIFIERS, NEGATIONS, ORDINARY, PURPOSES, SCOPES, Scope
from snowlight.classify.model import CERTAIN, INFERRED, JUDGMENT, Note
from snowlight.classify.text import (
    CLOCK,
    CLOCK_STRICT,
    DURATION,
    Pieces,
    clock_time,
    duration_minutes,
    trie,
    words,
)
from snowlight.classify.weather import begins_name

type MentionKind = Literal[
    "closed", "delayed", "remote", "early_dismissal", "open", "note", "ambiguous", "revoke"
]
type ScopeRule = Literal["both", "after", "none"]
"""Where to look for the noun a mention is about: before and after it, after only, nowhere."""
type Revokes = Literal["cancel", "revoke"]
"""A word that calls something off: one that can also mean "closed", or one that cannot."""

SCOPE_NOTES: dict[Scope, Note] = {
    "staff": "staff",
    "office": "offices_closed",
    "activities": "activities_cancelled",
    "partial": "partial_program",
    "childcare": "childcare",
    "transportation": "transportation",
}

_EARLIEST_OPENING = time(6, 0)
_LATEST_OPENING = time(13, 0)
_EARLIEST_DISMISSAL = time(8, 0)
_LATEST_DISMISSAL = time(16, 30)
# A dismissal time given with no word saying it is early ("students released at 11:30",
# "dismissing at 1:15 PM") is read as an early dismissal only up to 1:30 p.m., before any
# regular school day ends, while "dismissal at 3:00" is an ordinary afternoon.
_LATEST_PLAIN_DISMISSAL = time(13, 30)
# A closing time with no word saying it is early ("closing at 11:30", "closes at 1 pm") is an
# early dismissal up to 2:30 p.m. Later ("closing at 3:00 PM") it is when many schools let out
# anyway, so it can be the building's hours as much as an early release, as "closed after
# 3:30" is (see snowlight.classify.dayparts); "closing early at 3:00 PM" still says so.
_LATEST_PLAIN_CLOSING = time(14, 30)
# An opening time with no word saying it is late ("opening at 10:00", "classes begin at 9:30")
# is a late start from 9:30 a.m., after any regular school day begins. Earlier ("opening at
# 7:30", "school starts at 8:00") it is when many schools open anyway, so it says nothing
# unusual: unclear, as "dismissal at 3:00" is. "Delayed opening at 8:00", "8:00 late start"
# and "not opening until 8" say so (see snowlight.classify.parse for one beside a delay).
_EARLIEST_PLAIN_OPENING = time(9, 30)


@dataclass(slots=True)
class Mention:
    """One status phrase, with what the clause around it decides about it."""

    start: int
    end: int
    kind: MentionKind
    strength: float
    note: Note | None = None
    delay: int | None = None
    opens_at: time | None = None
    dismissal: time | None = None
    early: int | None = None
    scope_rule: ScopeRule = "both"
    negatable: bool = True
    needs_school_noun: bool = False
    # Decided with the clause:
    narrowed: MentionKind | None = None  # the status kind, when it was about part of the program
    dropped: Note | None = None
    superseding: bool = False
    superseded: bool = False
    named: bool = False  # about the school because a noun is in the school's name
    revokes: Revokes | None = None  # the word can call a status off ("cancelled", "lifted")
    revoked: bool = False  # a word beside it calls this status off ("2 hour delay cancelled")
    today: bool = False  # its words name the posting day: "closed for the rest of the day"
    elsewhere: bool = False  # an "open" about something besides the school: "offices open"


def _opening(text: str | None) -> time | None:
    value = None if text is None else clock_time(text)
    if value is None or not _EARLIEST_OPENING <= value <= _LATEST_OPENING:
        return None
    return value


def _dismissal(text: str | None) -> time | None:
    value = None if text is None else clock_time(text)
    if value is None or not _EARLIEST_DISMISSAL <= value <= _LATEST_DISMISSAL:
        return None
    return value


def school_opening(text: str) -> time | None:
    """The time a clock time stands for, when a school day can start then ("10:00")."""
    return _opening(text)


def late_opening(text: str) -> time | None:
    """The time a clock time stands for, when it is later than a regular school day starts."""
    value = _opening(text)
    return None if value is None or value < _EARLIEST_PLAIN_OPENING else value


def school_dismissal(text: str) -> time | None:
    """The time a clock time stands for, when a school day can end early then ("12:30")."""
    return _dismissal(text)


# What may follow a bare hour ("early dismissal at 6") for it to be a time and not a count or
# a grade ("early dismissal 5th grade", "at 5 schools", "6-12"): the end, a mark that ends the
# phrase, or a day word.
_BARE_HOUR_END = re.compile(
    r"\s*(?:$|[,;.!?|)]|(?:today|tomorrow|tonight|o'?clock|oclock|due|because|for|on|this"
    rf"|{trie(WEEKDAYS)})\b)",
    re.ASCII,
)


def _out_of_hours(match: re.Match[str], text: str, group: str) -> Mention | None:
    """An early closing at a time no school day ends, or ``None`` for any other time.

    "Closing early at 5:00 PM", "early dismissal at 6 PM" and "closing early at
    12:00 AM" close the building after the school day: evening activities, not
    an early dismissal, as "closed after 5 PM" is. An early dismissal in the
    early morning ("early dismissal 7:00", "early release at 6:30 AM") cannot be
    placed at all. The time is the match's ``group``. A time no clock has
    ("25:00"), and a bare number that is not a time ("early dismissal 5th
    grade"), are left out: the phrase stays an early dismissal with no time.
    """
    clock_text = match.group(group)
    value = clock_time(clock_text)
    if value is None or _EARLIEST_DISMISSAL <= value <= _LATEST_DISMISSAL:
        return None
    if clock_text.isdigit() and _BARE_HOUR_END.match(text, match.end(group)) is None:
        return None
    start, end = match.span()
    if value > _LATEST_DISMISSAL or value < _EARLIEST_OPENING:
        return Mention(
            start,
            end,
            "note",
            CERTAIN,
            note="activities_cancelled",
            scope_rule="none",
            negatable=False,
        )
    return Mention(start, end, "ambiguous", CERTAIN, note="ambiguous", scope_rule="none")


def _minutes(text: str | None) -> int | None:
    return None if text is None else duration_minutes(text)


def _ordinary_before(match: re.Match[str], text: str) -> bool:
    """Whether the word just before the match is "regular", "normal" and the like."""
    before = text[max(0, match.start() - 12) : match.start()].split()
    return bool(before) and before[-1] in ORDINARY


# Builders --------------------------------------------------------------------------------


# A length of nothing: "0 hour delay", "delayed 0 hours", "0 minutes early" say no delay.
_ZERO_LENGTH = re.compile(r"0+(?:\.0+)?\s*-?\s*(?:hours?|hrs?|h|minutes?|mins?|m)", re.ASCII)


def _zero(duration: str | None) -> bool:
    """Whether a length (see :data:`~snowlight.classify.text.DURATION`) is none at all."""
    return (
        duration is not None
        and duration.startswith("0")  # (as every match does: a quick look first)
        and _ZERO_LENGTH.fullmatch(duration) is not None
    )


# A length and "or" or "to" right before a length: "2 or 3 hour delay", "90 minutes to 2 hour
# delay". The text gives two lengths, and settles neither. (Not a date's day, "3/11 to 2 hour
# delay", nor a change, "from 1 to 2 hour delay".)
_ALTERNATIVE_BEFORE = re.compile(
    r"(?<![\w/.:])(?<!from )(?:\d+(?:\.\d+)?|one|two|three|four|five|six|1/2|half)"
    r"(?:\s*-?\s*(?:hours?|hrs?|h|minutes?|mins?))?\s+(?:or|to)\s*\Z",
    re.ASCII,
)


def _length_first(match: re.Match[str], text: str) -> int | None:
    """The minutes of the length a status opens with, unless another length stands before it
    as its alternative ("2 or 3 hour delay")."""
    start = match.start("dur")
    low = max(0, start - 20)
    # (A length before it takes four characters at least: "1 or ".)
    if start - low > 3 and _ALTERNATIVE_BEFORE.search(text, low, start) is not None:  # noqa: PLR2004
        return None
    return _minutes(match.group("dur"))


def _delay_with_length(match: re.Match[str], text: str) -> Mention | None:
    if _zero(match.group("dur")):
        return _negated(match.start(), match.end(), "delayed")  # "0 hour delay": no delay
    minutes = _length_first(match, text)
    strength = CERTAIN if minutes is not None else JUDGMENT
    return Mention(match.start(), match.end(), "delayed", strength, delay=minutes)


# A closure word before "starting at noon", with at most two days between ("closing Saturday
# starting at noon"): the time the closure starts, not the school's opening.
_CLOSURE_BEFORE = re.compile(
    r"(?:clos(?:ed|ing|es|e|ure)|shut(?:\s+down)?|dismiss(?:ed|al|ing)?|releas(?:ed|ing)"
    r"|cancel(?:l?ed|l?ing)|no\s+(?:school|classes))\s+"
    r"(?:(?:(?:today|tomorrow|mon|tue|wed|thu|fri|sat|sun)[a-z]*|(?:jan|feb|mar|apr|may|jun|jul"
    r"|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?),?\s+){0,2}\Z",
    re.ASCII,
)


# A time before "start", "opening" or "arrival" with no word saying it is late: "8:00 start".
_PLAIN_START = re.compile(r"\s+(?:start|opening|arrival)\b", re.ASCII).match


def _opens_at(match: re.Match[str], text: str) -> Mention | None:
    opens = _opening(
        match.group("clock")
        or match.group("clock2")
        or match.group("clock3")
        or match.group("clock4")
    )
    if opens is None or _ordinary_before(match, text):
        return None
    start = match.start()
    if text.startswith(("start", "begin"), start) and _CLOSURE_BEFORE.search(
        text, max(0, start - 48), start
    ):
        return None  # "closed starting at noon": see snowlight.classify.dayparts
    negatable = match.group("until") is None
    if (
        opens < _EARLIEST_PLAIN_OPENING
        and negatable
        and (match.group("clock4") is None or _PLAIN_START(text, match.end("clock4")) is not None)
    ):
        # "Opening at 7:30", "School starts at 8:00": a regular start time (see above).
        return Mention(start, match.end(), "ambiguous", CERTAIN, note="ambiguous", opens_at=opens)
    return Mention(start, match.end(), "delayed", CERTAIN, opens_at=opens, negatable=negatable)


def _head_end(match: re.Match[str], text: str) -> int:
    """Where the status words end before a day named between them and a length.

    "Delayed Wednesday 2 hours" is the delay "delayed" with a length of two
    hours; the day is left outside the mention, so it is read as the status's
    date like any other day beside it.
    """
    end = match.start("when")
    while end > match.start() and text[end - 1] in " ,:-":
        end -= 1
    return end


def _delay_word(match: re.Match[str], text: str) -> Mention | None:
    """A delay word, with the length that follows it if any: "delayed 2 hours", "late start".

    A day can come between the word and the length: "Delayed Wednesday 2 Hours",
    "Opening Late Friday 90 Minutes".
    """
    if match.group("dur") is not None:
        end = match.end() if match.group("when") is None else _head_end(match, text)
        if _zero(match.group("dur")):
            return _negated(match.start(), end, "delayed")  # "delayed 0 hours": no delay
        minutes = _minutes(match.group("dur"))
        strength = CERTAIN if minutes is not None else JUDGMENT
        return Mention(match.start(), end, "delayed", strength, delay=minutes)
    strength = JUDGMENT if match.group("word") == "delays" else INFERRED
    return Mention(match.start(), match.end(), "delayed", strength)


def _early_with_length(match: re.Match[str], text: str) -> Mention | None:
    if _zero(match.group("dur")):
        return _negated(match.start(), match.end(), "early_dismissal")  # "0 hours early"
    return Mention(
        match.start(), match.end(), "early_dismissal", CERTAIN, early=_length_first(match, text)
    )


def _early_length_first(match: re.Match[str], text: str) -> Mention | None:
    """ "Dismissing 2 hours early", and with a day between: "Closing Wednesday 2 hours early"."""
    if match.group("when") is not None:
        return _early_after_day(match, text)
    return _early_with_length(match, text)


def _early_after_day(match: re.Match[str], text: str) -> Mention:
    """An early dismissal with a day between it and its length: "Closing Early Tuesday 2 Hours"."""
    if _zero(match.group("dur")):
        return _negated(match.start(), _head_end(match, text), "early_dismissal")
    early = _minutes(match.group("dur"))
    return Mention(match.start(), _head_end(match, text), "early_dismissal", CERTAIN, early=early)


def _early_main(match: re.Match[str], text: str) -> Mention | None:
    if match.group("when") is not None:
        return _early_after_day(match, text)
    clock_text = match.group("clock")
    if clock_text is not None and not clock_text.strip("0:"):
        # "Early dismissal: 0", "... 0:00": a field answered with none, not a time.
        return _negated(match.start(), match.end(), "early_dismissal")
    dismissal = _dismissal(clock_text)
    if clock_text is not None and dismissal is None:
        late = _out_of_hours(match, text, "clock")
        if late is not None:
            return late  # "early dismissal at 6:00 PM": the evening
    end = match.end() if clock_text is None or dismissal is not None else match.start("clock")
    if _zero(match.group("dur")):
        return _negated(match.start(), end, "early_dismissal")  # "early dismissal: 0 hours"
    return Mention(
        match.start(),
        end,
        "early_dismissal",
        CERTAIN,
        dismissal=dismissal,
        early=_minutes(match.group("dur")),
    )


def _timed_dismissal(
    start: int, end: int, dismissal: time, *, early: bool, dismissal_verb: bool
) -> Mention:
    """A dismissal at a clock time: early when it says so, or when the time is early."""
    if early or (not dismissal_verb and dismissal <= _LATEST_PLAIN_CLOSING):
        return Mention(start, end, "early_dismissal", CERTAIN, dismissal=dismissal)
    if dismissal_verb and dismissal <= _LATEST_PLAIN_DISMISSAL:
        return Mention(start, end, "early_dismissal", JUDGMENT, dismissal=dismissal)
    if not dismissal_verb:
        # "Closing at 3:00 PM": unclear for the school, but "offices close at 3" is the
        # offices' news, so the noun it is about is looked for. (The time it keeps marks it
        # as a closing time, which closes nothing before it; see snowlight.classify.parse.)
        return Mention(start, end, "ambiguous", CERTAIN, note="ambiguous", dismissal=dismissal)
    return Mention(start, end, "ambiguous", CERTAIN, note="ambiguous", scope_rule="none")


def _early_at(match: re.Match[str], text: str) -> Mention | None:
    """A dismissal verb and a time: "dismissing at 1:15", "closing schools early at noon".

    Or the school day's end and a time: "classes end at noon" is an early
    dismissal as "dismissing at noon" is, when the time is early enough (see
    :func:`_timed_dismissal`); "school ends at 3:15" says nothing early.
    """
    verb = match.group("verb") or ""
    clock_text = match.group("clock")
    if clock_text is None and not verb.startswith(("dismiss", "releas", "clos")):
        return None  # ("Classes end 3:15" and "leaving 12:30" give no time a dismissal has)
    if not verb and _modified(text, match.start()):
        return None  # "morning classes end at 11", "summer school ends at noon": not the day's
    clock_text = clock_text or match.group("strict")
    if clock_text is not None and clock_text.isdigit() and _COUNTED_AFTER(text, match.end()):
        return None  # "Closed at 2 locations": a count of places, not a time
    dismissal = _dismissal(clock_text)
    if _ordinary_before(match, text):
        return None
    early = "early" in match.group()
    if dismissal is None:
        # "Closing early at 5:00 PM", "Closing Early Monday 05:00 PM": the evening. (With no
        # "early", "closing at 5 PM" is read by the closure rule.)
        group = "clock" if match.group("clock") is not None else "strict"
        return _out_of_hours(match, text, group) if early else None
    # "Closing Wednesday at noon": the day between the verb and the time is left outside the
    # phrase, so it is read as the status's date.
    if match.group("when") is None:
        end = match.end()
    else:
        end = match.end("verb") if verb else match.end("ends")
    return _timed_dismissal(
        match.start(),
        end,
        dismissal,
        early=early,
        dismissal_verb=not verb.startswith("clos"),
    )


# A noun of places or people after a bare number: the number counts them ("at 2 locations").
_COUNTED_AFTER = re.compile(
    r"\s+(?:schools|campuses|buildings|sites|locations|branches|centers)\b", re.ASCII
).match
# The word right before a place in the text, if a word ends there.
_WORD_BEFORE = re.compile(r"(?<![a-z0-9'-])([a-z][a-z'-]*)\s+\Z", re.ASCII)


def _modified(text: str, start: int) -> bool:
    """Whether the word right before ``start`` moves a school noun to another scope."""
    before = _WORD_BEFORE.search(text, max(0, start - 24), start)
    return before is not None and before.group(1) in MODIFIERS


def _early_clock_first(match: re.Match[str], text: str) -> Mention | None:
    dismissal = _dismissal(match.group("clock"))
    if _ordinary_before(match, text):
        return None
    if dismissal is None:
        # "5:00 PM early dismissal": the evening. ("6 PM dismissal" says nothing is early.)
        early = "early" in match.group()
        return _out_of_hours(match, text, "clock") if early else None
    return _timed_dismissal(
        match.start(),
        match.end(),
        dismissal,
        early="early" in match.group(),
        dismissal_verb=True,
    )


def _early_bare(match: re.Match[str], text: str) -> Mention | None:
    """ "Dismissing early", "half day", and a length after "early": "closing early 2 hours"."""
    if match.group("when") is not None:
        return _early_after_day(match, text)
    if match.group("dur") is not None:
        return _early_with_length(match, text)
    phrase = match.group()
    if "day" in phrase:
        following = words(text, match.end(), min(len(text), match.end() + 24))
        if following and SCOPES.get(following[0]) == "partial":
            end = match.end() + text[match.end() :].index(following[0]) + len(following[0])
            return Mention(
                match.start(), end, "note", CERTAIN, note="partial_program", scope_rule="none"
            )
        return Mention(match.start(), match.end(), "early_dismissal", JUDGMENT)
    return Mention(match.start(), match.end(), "early_dismissal", CERTAIN)


def _rest_of_day(match: re.Match[str], _text: str) -> Mention | None:
    return Mention(match.start(), match.end(), "early_dismissal", CERTAIN, today=True)


# A status field of a statewide list answered for all of a district's schools or some of them:
# "Closings: All; Delays: None; Non-traditional: Some". ("None" is answered no; see
# snowlight.classify.parse.)
_FIELD_ANSWER = re.compile(r"\s*:\s*(all|some)(?=\s*(?:$|[;,.|]))", re.ASCII)
_FIELD_LABELS = frozenset(
    {"closings", "closures", "non-traditional", "nontraditional", "non traditional"}
)


def _field(start: int, answer: re.Match[str], kind: MentionKind) -> Mention:
    """The status a field answers: for every school ("all"), or part of the program ("some")."""
    if answer.group(1) == "all":
        return Mention(start, answer.end(), kind, CERTAIN)
    return Mention(start, answer.end(), "note", CERTAIN, note="partial_program", scope_rule="none")


def _remote(match: re.Match[str], text: str) -> Mention | None:
    phrase = match.group()
    start, end = match.span()
    if phrase in _FIELD_LABELS:  # "Non-traditional: All" (the rule reads it before a colon)
        answer = _FIELD_ANSWER.match(text, end)
        if answer is not None:
            return _field(start, answer, "remote")
        return Mention(start, end, "remote", INFERRED)  # ("Non-traditional: None" is no)
    if phrase == "online":
        if _ONLINE_BEFORE.search(text, max(0, start - _ONLINE_REACH), start) is None:
            return None  # "registration online", "check online"
        return Mention(start, end, "remote", CERTAIN)  # "classes will be online"
    if phrase in {"virtual", "virtually", "remote", "remotely", "async", "fid"}:
        return _bare_remote(start, end, text)
    return Mention(start, end, "remote", CERTAIN)


def _bare_remote(start: int, end: int, text: str) -> Mention | None:
    """A word alone for remote learning ("virtual", "remote"), unless it is part of a name or
    says how something besides the school day is held."""
    if begins_name(text, start, end):
        return None  # "Remote Valley School: Closed": a school's name
    held, end = _held_remotely(text, end)
    if held == "partial":  # "virtual kindergarten": part of the program
        return Mention(start, end, "note", CERTAIN, note="partial_program", scope_rule="none")
    if held is not None:
        return None  # "Virtual open house", "remote meeting": how an event is held
    return Mention(start, end, "remote", INFERRED)


# "Online" alone says how school is held after a school noun and a verb: "classes will be
# online", "classes moved online", "students will learn online", "school online".
_ONLINE_BEFORE = re.compile(
    r"\b(?:classes|class|instruction|learning|school|students)"
    r"(?: (?:will|shall|are|is|be|to|now|all|moved?|moving|go|goes|going|held|conducted"
    r"|shift(?:ed|ing|s)?|switch(?:ed|ing|es)?|transition(?:ed|ing|s)?|meet(?:ing|s)?"
    r"|continue|continues|continuing|learn|learning|work|working))* $",
    re.ASCII,
)
_ONLINE_REACH = 60
# Nouns for work, which "remote" before them makes a place of work, not of learning.
_WORK_NOUNS = frozenset(
    {"work", "working", "workday", "workdays", "work-day", "work-days", "job", "jobs", "career"}
)
# Learning named next to "remote work": "remote work and learning", "remote work, classes".
_LEARNING_TOO = re.compile(
    r" ?(?:,|/|and|or|plus|with) ?(?:remote |virtual |online )?"
    r"(?:learn|learning|classes|class|instruction|school|students)\b",
    re.ASCII,
)


def _held_remotely(text: str, end: int) -> tuple[Scope | None, int]:
    """What "virtual" or "remote" ending at ``end`` describes when not the school's day,
    and where the phrase it opens ends.

    "Virtual open house", "remote meeting", "remote work day", "virtual job fair
    cancelled", "virtual family night": the noun phrase after the word names an
    event, a service or work that is held that way (``activities`` and the other
    scopes of :data:`SCOPES`). "Virtual kindergarten" is part of the program
    (``partial``). "Virtual classes", "remote K-12" and "virtual today" give
    ``None``, and so does work with learning beside it ("remote work and learning",
    "remote work, classes on Monday"), whose phrase runs through the learning.
    """
    phrase = _phrase_after(text, end)
    for index, (word, word_end) in enumerate(phrase):
        if word in _WORK_NOUNS:
            learning = _LEARNING_TOO.match(text, word_end)
            return (None, learning.end()) if learning is not None else ("staff", end)
        pair = f"{word} {phrase[index + 1][0]}" if index + 1 < len(phrase) else word
        scope = SCOPES.get(pair) or SCOPES.get(word)
        if scope is None and MODIFIERS.get(word) == "activities":
            return "activities", end  # "virtual family night"
        if scope is not None:
            return (None if scope == "school" else scope), end
        if word in _CLOSURE_WORDS:
            return None, end  # "remote snow day"
    return None, end


_MODIFIER_WORDS = {
    "half": "half-day",
    "after": "after-school",
    "before": "before-school",
    "full": "full-day",
    "in": "in-person",
}


# "No" before a noun ------------------------------------------------------------------
#
# "No school" closes the school only when nothing makes "school" part of a longer noun.
# "No school closures today", "no school changes", "no school or district closings" and
# "no schools affected" say that nothing happens: the "no" is about the status or news
# noun at the end of the phrase. "No school activities" and "no school buses" are news
# about activities and buses. Any other noun after it ("no school pictures", "no school
# board meeting") leaves the phrase unclear, so "no school" reads as a closure only before
# the end of the phrase, a day, a filler word, or a word for weather or a status ("no
# school today", "no school due to snow", "no school snow day"). A school noun that is the
# subject of a status verb negates it too ("no schools are closed", "no school has
# announced a closure"); one that reports anything else ("no school has announced plans"),
# and a news noun after a slash ("no school/closings"), leave the phrase unclear. The same
# holds for "no school" said with "not": "there will not be school", "we do not have
# classes", "there will not be school closures".

# Nouns for a status, or for news about one, that a "no" before them negates.
_NEGATED_NOUNS: dict[str, MentionKind] = {
    **dict.fromkeys(
        (
            "closure", "closures", "closing", "closings", "shutdown", "shutdowns",
            "shut-down", "shut-downs", "cancellation", "cancellations", "cancelation",
            "cancelations",
        ),
        "closed",
    ),
    **dict.fromkeys(
        ("delay", "delays", "start", "starts", "opening", "openings", "arrival"), "delayed"
    ),
    **dict.fromkeys(("dismissal", "dismissals", "release", "releases"), "early_dismissal"),
    **dict.fromkeys(
        (
            "change", "changes", "update", "updates", "announcement", "announcements", "alert",
            "alerts", "news", "notice", "notices", "adjustment", "adjustments", "modification",
            "modifications", "disruption", "disruptions", "interruption", "interruptions",
            "impact", "impacts", "status", "schedule", "schedules",
        ),
        "ambiguous",
    ),
}  # fmt: skip
# Participles after "no schools": "No schools closed" negates, "No school closed" could be
# "No school. Closed." as well. These negate after any school noun: "No school affected".
_PARTICIPLES = frozenset(
    {
        "closed", "delayed", "cancelled", "canceled", "dismissed", "released", "shut",
        "suspended", "postponed",
    }
)  # fmt: skip
_ALWAYS_NEGATED = frozenset({"affected", "impacted", "changed", "altered"})
_PLURAL_SCHOOL_NOUNS = frozenset(
    {"schools", "classes", "students", "campuses", "buildings", "districts", "facilities"}
)
# Words that end the noun phrase after "no school" and leave it a closure.
_PHRASE_ENDS = frozenset(
    {
        "for", "on", "due", "because", "owing", "per", "until", "till", "til", "thru",
        "through", "from", "but", "as", "at", "in", "to", "by", "with", "without", "again",
        "either", "both", "all", "any", "whatsoever", "anywhere", "is", "are", "was", "were",
        "will", "shall", "has", "have", "had", "be", "being", "been", "held", "scheduled",
        "planned", "the", "this", "that", "these", "those", "next", "coming", "so", "then",
        "still", "also", "except", "including", "if", "unless", "should", "whether", "when",
        "while", "after", "before", "since", "anymore", "tonight", "yesterday", "a", "an",
        "now", "instead",
        "districtwide", "district-wide", "countywide", "county-wide", "systemwide",
        "system-wide", "campuswide", "campus-wide", "citywide", "city-wide", "statewide",
        "state-wide", "divisionwide", "division-wide", "parishwide", "parish-wide",
        "k-12", "pk-12", "prek-12", "tk-12", "k12", "pk12",
        # A condition or a hedge after it: "no school pending road conditions", "no school
        # weather permitting", "no school tentative".
        "pending", "depending", "dependent", "contingent", "provided", "providing",
        "assuming", "barring", "subject", "whenever", "permitting", "tentative",
        "tentatively", "tbd", "tba", "tbc", "possible", "possibly", "likely", "probably",
        "maybe", "perhaps", "expected", "anticipated", "unconfirmed",
    }
)  # fmt: skip
# Words for weather or a status that can stand in the phrase: "no school snow day".
_CLOSURE_WORDS = frozenset(
    {
        "snow", "snowy", "snowday", "ice", "icy", "sleet", "freezing", "frigid", "cold",
        "extreme", "severe", "winter", "wintry", "storm", "storms", "blizzard", "flood",
        "flooding", "hurricane", "tornado", "heat", "fog", "wind", "weather",
        "weather-related", "inclement", "hazardous", "emergency", "calamity", "power",
        "outage", "nti", "ntid", "non-traditional", "nontraditional", "flexible", "ami",
        "e-learning", "elearning", "virtual", "remote", "online", "distance", "digital",
        "cyber", "flex", "fid", "async", "asynchronous", "learning", "instruction",
        "instructional", "day", "days",
    }
)  # fmt: skip
_JOINING = frozenset({"or", "and", "nor"})
_PHRASE_WORDS = 4  # how far the noun phrase after "no school" is read
_NEXT_WORD = re.compile(r" ([a-z0-9]+(?:['/-][a-z0-9]+)*)", re.ASCII)
# A word joined to the noun by a slash: "no school/closings".
_SLASHED_WORD = re.compile(r"/([a-z0-9]+(?:['-][a-z0-9]+)*)", re.ASCII)
# "No schools are closed", "no school will be delayed", "no school has announced a closure",
# "no schools at this time have reported any closings".
_VERB_AFTER = re.compile(
    r"(?: (?:currently|now|presently|yet|also|so far|at this time|at present|as of now))?"
    r" (?:is|are|was|were|will|shall|has|have|had)"
    r"(?: (?:be|been|being|currently|now|yet|already|officially))*"
    r"(?: (?P<report>announced|reported|called|issued|posted|made|declared))?"
    r"(?: (?:a|an|any|the))? (?P<verb>[a-z][a-z'/-]*)",
    re.ASCII,
)
# The verb that says "no school" happens: "no school will be held tomorrow". The phrase runs
# through it, so the day after it is the closure's.
_IN_SESSION_AFTER = re.compile(
    r" (?:(?:will|shall) be|is|are|has been|have been)"
    r" (?:in session|held|scheduled|planned|conducted)\b| (?:will|shall) (?:take place|meet)\b",
    re.ASCII,
)
_STATUS_VERBS: dict[str, MentionKind] = {
    **dict.fromkeys(
        (
            "closed", "closing", "close", "closes", "cancelled", "canceled", "cancelling",
            "canceling", "cancel", "shut", "shutting",
        ),
        "closed",
    ),
    **dict.fromkeys(("delayed", "delaying"), "delayed"),
    **dict.fromkeys(
        ("dismissed", "dismissing", "dismiss", "released", "releasing"), "early_dismissal"
    ),
    **dict.fromkeys(("affected", "impacted", "changed", "altered"), "ambiguous"),
}  # fmt: skip
_GRADE = r"(?:k|pk|tk|\d{1,2}(?:st|nd|rd|th)?)"
# A grade or a span of grades, then "grade": "no school 3rd grade", "no school 6-8th graders".
_GRADES_AFTER = re.compile(
    rf" {_GRADE}(?:\s*-\s*{_GRADE})?(?: and {_GRADE})? grad(?:es?|ers?)\b", re.ASCII
)


def _ends_phrase(word: str) -> bool:
    """Whether a word after "no school" ends its noun phrase ("today", "for", "mon/tue")."""
    if "/" in word:
        word = word.partition("/")[0]  # "today/tomorrow", "Thurs/Fri"
    return word in _PHRASE_ENDS or word in NEGATIONS or word[0].isdigit() or names_day(word)


def _phrase_after(text: str, position: int) -> list[tuple[str, int]]:
    """The words right after ``position`` in the same phrase, with where each ends.

    The phrase stops at a punctuation mark or a word that ends it ("today",
    "for", "due"); at most :data:`_PHRASE_WORDS` words are read.
    """
    found: list[tuple[str, int]] = []
    while len(found) < _PHRASE_WORDS:
        match = _NEXT_WORD.match(text, position)
        if match is None or _ends_phrase(match.group(1)):
            break
        found.append((match.group(1), match.end()))
        position = match.end()
    return found


def _negated(start: int, end: int, kind: MentionKind) -> Mention:
    return Mention(start, end, kind, CERTAIN, scope_rule="none", negatable=False, dropped="negated")


# One item of a list of nouns after "no school": "or district", ", county", "and area".
_LIST_STEP = re.compile(r"(,)? (?:(or|and|nor) )?([a-z][a-z'/-]*)", re.ASCII)
# Words a list of nouns ending in a news or status noun may hold before it: "no school or
# district weather-related closings", "no school, district or county closings".
_LIST_WORDS = frozenset(
    {
        "county", "counties", "area", "local", "public", "private", "parochial", "charter",
        "regional", "other", "related", "weather-related", "school-related", "district-wide",
        "districtwide", "systemwide", "system-wide", "countywide", "county-wide", "campus",
    }
)  # fmt: skip
_LIST_STEPS = 6


def _listed_noun(start: int, text: str, end: int) -> Mention | None:
    """A "no" before a list of nouns that ends in a status or news noun it negates.

    "No school or district weather-related closings" and "no school, district or
    county closings" say nothing closes. The list must be joined by "or", "and"
    or "nor", and hold only nouns, scope words and weather words before its last
    noun; "no school or activities today" and "no school, closure due to snow"
    are closures. A list that runs on past a few such words is unclear.
    """
    position = end
    joined = False
    for _step in range(_LIST_STEPS):
        step = _LIST_STEP.match(text, position)
        if step is None:
            return None
        comma, joiner, word = step.groups()
        if comma is not None and joined:
            return None  # the list has ended: "no school or activities, closure due to snow"
        joined = joined or joiner is not None
        kind = _negated_kind(word)
        if kind is not None:
            return _negated(start, step.end(), kind) if joined else None
        if not (word in SCOPES or word in _CLOSURE_WORDS or word in _LIST_WORDS):
            return None
        position = step.end()
    return _unclear(start, position)  # a list too long to tell what it is about


def _negated_kind(word: str) -> MentionKind | None:
    """The status a noun "no" can negate is about: "closings", "changes", "closings/delays"."""
    kind = _NEGATED_NOUNS.get(word)
    if kind is None and "/" in word:
        for part in word.split("/"):
            kind = _NEGATED_NOUNS.get(part)
            if kind is not None:
                break
    return kind


def _unclear(start: int, end: int) -> Mention:
    return Mention(
        start, end, "ambiguous", CERTAIN, note="ambiguous", scope_rule="none", negatable=False
    )


def _negated_noun(  # noqa: PLR0911 - one return per reading of the words after the noun
    start: int, text: str, end: int, phrase: list[tuple[str, int]]
) -> Mention | None:
    """A "no" before a status it negates: "no school closures", "no schools are closed".

    A noun of news after a slash ("no school/closings") could be a second label
    or part of the phrase, so the phrase is unclear. So is a school noun that
    announces or reports something other than a status: "no school has
    announced plans" is not "no school".
    """
    position = end
    for word, word_end in phrase:
        if SCOPES.get(word) != "school":
            break
        position = word_end  # "no school district or county closings"
    if text.startswith((",", " or ", " and ", " nor "), position):
        listed = _listed_noun(start, text, position)
        if listed is not None:
            return listed  # "no school or district closings", "no school, district or ..."
    for word, word_end in phrase:
        kind = _negated_kind(word)
        if kind is not None:
            return _negated(start, word_end, kind)
        if word in _PARTICIPLES or word in _ALWAYS_NEGATED:
            return None
    if phrase:
        return None
    if text.startswith("/", end):
        slashed = _SLASHED_WORD.match(text, end)
        if slashed is not None and _negated_kind(slashed.group(1)) is not None:
            return _unclear(start, slashed.end())
        return None
    verb = _VERB_AFTER.match(text, end)
    if verb is None:
        return None
    kind = _STATUS_VERBS.get(verb.group("verb")) or _negated_kind(verb.group("verb"))
    if kind is not None:
        return _negated(start, verb.end(), kind)
    return None if verb.group("report") is None else _unclear(start, verb.end())


def _no_school(  # noqa: PLR0911 - one return per reading of the phrase
    start: int, end: int, obj: str, text: str, phrase: list[tuple[str, int]]
) -> Mention:
    """What "no school" is, given the rest of its noun phrase (see above)."""
    if text.startswith(" ", end):  # (both patterns open with a space)
        grades = _GRADES_AFTER.match(text, end)
        if grades is not None:  # "no school 3rd grade": part of the program
            return Mention(start, grades.end(), "note", CERTAIN, note="partial_program",
                           scope_rule="none", negatable=False)  # fmt: skip
        session = _IN_SESSION_AFTER.match(text, end)
        if session is not None:  # "no school will be held", "no school is in session"
            end = session.end()
    closure = Mention(start, end, "closed", CERTAIN, scope_rule="after", negatable=False)
    words_after = [word for word, _end in phrase]
    while words_after and SCOPES.get(words_after[0]) == "school":
        words_after.pop(0)  # "no school district today"
    if not words_after or words_after[0] in _JOINING or words_after == ["only"]:
        return closure  # "no school", "no school or activities today", "no school only today"
    first = words_after[0]
    last = phrase[len(phrase) - len(words_after)][1]
    if first in _ALWAYS_NEGATED or (first in _PARTICIPLES and obj in _PLURAL_SCHOOL_NOUNS):
        return _negated(start, last, "closed")
    for index, word in enumerate(words_after):
        pair = " ".join(words_after[index : index + 2])
        scope = SCOPES.get(pair) or SCOPES.get(word)
        if scope in (None, "school"):
            continue
        following = words_after[index + 1] if index + 1 < len(words_after) else None
        if following in PURPOSES:
            return closure  # "no school staff development day"
        if following in _STATUS_VERBS:
            # "No school buses delayed": the "no" is about the buses and what they do.
            following_end = phrase[len(phrase) - len(words_after) + index + 1][1]
            return _negated(start, following_end, _STATUS_VERBS[following])
        if scope == "office":
            break  # "no school offices open" could be "No school; offices open"
        return Mention(
            start,
            phrase[len(phrase) - len(words_after) + index][1],
            "note",
            CERTAIN,
            note=SCOPE_NOTES[scope],
            scope_rule="none",
            negatable=False,
        )
    if all(part in _CLOSURE_WORDS for word in words_after for part in word.split("/")):
        return closure  # "no school snow day"
    return Mention(
        start, last, "ambiguous", CERTAIN, note="ambiguous", scope_rule="none", negatable=False
    )


def _hyphened_school_noun(obj: str) -> str | None:
    """The school noun that opens a hyphened word after "no", when the hyphen parts phrases.

    "NO SCHOOL-SNOW DAY" and "No school-today" say "no school" and then more; "no
    school-related closings" and "no school-wide closures" do not.
    """
    head, _mark, tail = obj.partition("-")
    if SCOPES.get(head) == "school" and (tail in _CLOSURE_WORDS or names_day(tail)):
        return head
    return None


def _no(match: re.Match[str], text: str) -> Mention | None:  # noqa: PLR0911 - one per form
    if match.group("both") is not None:  # "no in-person or remote classes"
        return Mention(
            match.start(), match.end(), "closed", CERTAIN, scope_rule="after", negatable=False
        )
    obj = match.group("obj")
    second = match.group("obj2")
    if obj not in SCOPES and "-" in obj:
        head = _hyphened_school_noun(obj)
        if head is None:
            return None
        return _no_school(match.start(), match.start("obj") + len(head), head, text, [])
    pair = f"{obj} {second}" if second else None
    end = match.end("obj")
    if pair is not None and pair in SCOPES:
        scope: Scope | None = SCOPES[pair]
        end = match.end("obj2")
    else:
        scope = SCOPES.get(obj)
    if scope is None:
        return None
    if text[end : end + 1] not in _READ_ON:
        # The end, or a mark: every pattern read after the noun needs a space, a comma or a
        # slash there, so nothing after it negates or extends the phrase ("No School.").
        return _no_noun(match, text, scope, end, [])
    phrase = _phrase_after(text, end)
    negated = _negated_noun(match.start(), text, end, phrase)
    if negated is not None:
        return negated  # "no school closures", "no schools are closed"
    return _no_noun(match, text, scope, end, phrase)


# What the patterns read after the noun of "no ..." start with: _NEXT_WORD, _VERB_AFTER,
# _GRADES_AFTER, _IN_SESSION_AFTER and _LIST_STEP a space (or a comma), and _SLASHED_WORD a
# slash.
_READ_ON = frozenset({" ", ",", "/"})  # (one character: never "", at the end)


def _no_noun(
    match: re.Match[str], text: str, scope: Scope, end: int, phrase: list[tuple[str, int]]
) -> Mention:
    """What "no" before a noun is when nothing after the noun negates instead."""
    modifier = match.group("mod")
    if modifier is not None:
        first = modifier.split()[0]
        first = _MODIFIER_WORDS.get(first, first)
        if first == "in-person":
            return Mention(
                match.start(),
                end,
                "ambiguous",
                CERTAIN,
                note="ambiguous",
                scope_rule="none",
                negatable=False,
            )
        if scope == "school" and not _whole_day(first, match.group("mod2")):
            scope = MODIFIERS.get(first, "partial")
    if scope == "school":
        return _no_school(match.start(), end, match.group("obj"), text, phrase)
    if phrase and phrase[0][0] in _STATUS_VERBS:
        # "No buses delayed", "no offices closed": nothing is, for them or for the school.
        return _negated(match.start(), phrase[0][1], _STATUS_VERBS[phrase[0][0]])
    listed = (
        _listed_school(text, end) if modifier is None and text[end : end + 1] in _READ_ON else None
    )
    if listed is not None:  # "no activities or school today"
        return Mention(match.start(), listed, "closed", CERTAIN, scope_rule="none",
                       negatable=False)  # fmt: skip
    return Mention(
        match.start(),
        end,
        "note",
        CERTAIN,
        note=SCOPE_NOTES[scope],
        scope_rule="none",
        negatable=False,
    )


def _listed_school(text: str, end: int) -> int | None:
    """Where a school noun that ends a list after "no" and another noun ends.

    "No activities or school today", "no practice, games or classes": the "no"
    covers the school too. The list is joined by "or", "and" or "nor" and holds
    only nouns of :data:`SCOPES`, and the school noun ends the phrase ("no
    activities or school events" is about events).
    """
    step = _LIST_STEP.match(text, end)
    while step is not None:
        comma, joiner, word = step.groups()
        scope = SCOPES.get(word)
        if (comma is None and joiner is None) or scope is None:
            return None  # the list has ended, or holds something else
        if scope == "school" and joiner is not None:
            following = _NEXT_WORD.match(text, step.end())
            if following is None or _ends_phrase(following.group(1)):
                return step.end()
            return None
        step = _LIST_STEP.match(text, step.end())
    return None


def _whole_day(first: str, second: str | None) -> bool:
    """Whether the words before a school noun cover the school day: "no day or evening
    classes", "no AM or PM classes", "no morning or afternoon classes"."""
    said = {first, second}
    return "day" in said or said in ({"am", "pm"}, {"morning", "afternoon"})


def _not_in_session(match: re.Match[str], text: str) -> Mention | None:
    if match.group() == "no session":
        # "No session changes": the "no" is about the noun at the end of the phrase.
        phrase = _phrase_after(text, match.end())
        negated = _negated_noun(match.start(), text, match.end(), phrase)
        if negated is not None:
            return negated
    return Mention(match.start(), match.end(), "closed", CERTAIN, negatable=False)


_DATE_WORDS = frozenset(
    [
        "today",
        "tomorrow",
        "tonight",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "mon",
        "tue",
        "tues",
        "wed",
        "thu",
        "thur",
        "thurs",
        "fri",
        "for",
        "all",
    ]
)


# "Closed campus", "closed-campus lunch": a school that keeps students on its grounds, not a
# closure. ("Closed campus: Lincoln" is a heading, and "closed campuses" a list of them.)
_CLOSED_CAMPUS = re.compile(r"[ -]campus(?![a-z0-9:-]| :)", re.ASCII)


# A bare "closing" that a change or an update leads to is the school's new status: "2 hour
# delay is now a closing", "delay changed to a full closing", "2 hr delay - now a closing",
# "UPDATE: Closing", "turned into a closing", "replaced with a closing". So is a "full" or
# "complete" closing. (Between the change and the closing there is at most "to", an article
# and a word for the whole day.)
_CHANGED_TO = re.compile(
    r"(?:\b(?:now|updated?|changed?|switched|converted|upgraded|bec[ao]mes?|becoming"
    r"|turn(?:ed|s)\s+(?:in)?to|replaced\s+(?:with|by))\s*[:-]?\s*(?:to\s+)?(?:an?\s+)?"
    r"(?:(?:full|complete|total)(?:\s+day)?\s+)?"
    r"|\b(?:full|complete|total)(?:\s+day)?\s+)$",
    re.ASCII,
)
# What may follow such a closing for it to be one: the end, a mark, the cause, or what it
# covers. ("Now closing times" and "a closing time" are about a time.)
_CLOSING_END = re.compile(
    r"\s*(?:$|[.,;:!?|()\[\]]|-|(?:for|due|because|of|all|districtwide|district-wide|schools?"
    r"|buildings?|campus(?:es)?|day)\b)",
    re.ASCII,
)
# A closing in place of another status: "Closing instead of 2 hour delay".
_CLOSING_INSTEAD = re.compile(r"\s*,?\s*instead\b", re.ASCII)
_CHANGE_REACH = 48  # (how far back the words before "closing" can start)


def changed_to_closing(text: str, start: int, end: int) -> bool:
    """Whether the "closing" at ``start``..``end`` is a change to a closure ("is now a closing").

    The words just before it are a change or an update, or "full", and what
    follows it ends the phrase; or "instead" follows it.
    """
    if _CLOSING_INSTEAD.match(text, end) is not None:
        return True
    return (
        _CLOSING_END.match(text, end) is not None
        and _CHANGED_TO.search(text, max(0, start - _CHANGE_REACH), start) is not None
    )


def _closed(match: re.Match[str], text: str) -> Mention | None:
    phrase = match.group()
    start, end = match.span()
    if phrase == "closed" and (
        # "Closed Captioning Club cancelled": a name, not a closure.
        text.startswith(" caption", end)
        or (
            text[end + 1 : end + 7] == "campus"  # (a quick test before the pattern)
            and _CLOSED_CAMPUS.match(text, end) is not None
        )
    ):
        return None
    if phrase in {"closings", "closures"}:
        answer = _FIELD_ANSWER.match(text, end)
        if answer is not None:
            return _field(start, answer, "closed")  # "Closings: All", "Closings: Some"
        return Mention(start, end, "ambiguous", CERTAIN, note="ambiguous", scope_rule="none")
    if phrase == "closing":
        following = words(text, end, min(len(text), end + 24))[:2]
        # "Closing tomorrow", and "closing after lunch" or "closing this afternoon": a closure
        # for part of the day (see snowlight.classify.dayparts). Else "closing" can be a noun,
        # unless what comes before it makes it the school's new status (see _CHANGED_TO).
        if (
            _DATE_WORDS.isdisjoint(following)
            and not bound_follows(text, end)
            and not changed_to_closing(text, start, end)
        ) or (following and following[0] == "all" and _all_elsewhere(text, end)):
            return Mention(start, end, "ambiguous", CERTAIN, note="ambiguous")
        return Mention(start, end, "closed", INFERRED)
    strength = (
        INFERRED
        if phrase in {"snow day", "shut", "closure", "snowed out"} or phrase[0] == "n"
        else CERTAIN
    )  # "no-school day" too
    return Mention(start, end, "closed", strength)


def _all_elsewhere(text: str, end: int) -> bool:
    """Whether "all" after a "closing" ending at ``end`` opens a noun for something else.

    "Closing all offices" and "closing all district offices" are the offices'
    news, as "closing offices" is; "closing all day", "closing all schools" and
    "closing all elementary schools" are the schools'.
    """
    nouns = words(text, end, min(len(text), end + 40))[1:3]
    return any(SCOPES.get(noun, "school") not in _SCHOOL_SCOPES for noun in nouns)


_SCHOOL_SCOPES = frozenset({"school", "partial"})


def _cancelled(match: re.Match[str], _text: str) -> Mention | None:
    postponed = match.group() in {"postponed", "rescheduled"}
    return Mention(
        match.start(),
        match.end(),
        "ambiguous",
        CERTAIN,
        note="ambiguous",
        needs_school_noun=not postponed,
        revokes=None if postponed else "cancel",
    )


def _revoke(match: re.Match[str], _text: str) -> Mention | None:
    """A word that only calls something off: "lifted", "rescinded", "no longer in effect"."""
    return Mention(
        match.start(),
        match.end(),
        "revoke",
        CERTAIN,
        scope_rule="none",
        negatable=False,
        revokes="revoke",
    )


def _ambiguous_day(match: re.Match[str], text: str) -> Mention | None:
    if match.group() == "inclement weather" and _CAUSE_BEFORE.search(text, 0, match.start()):
        return None  # "closed due to inclement weather": the cause, not a status
    return Mention(
        match.start(), match.end(), "ambiguous", CERTAIN, note="ambiguous", scope_rule="none"
    )


# "Due to inclement weather", "due to continued inclement weather", "because of the
# forecasted inclement weather", "for inclement weather".
_CAUSE_BEFORE = re.compile(
    r"\b(?:(?:due\s+to|because\s+of|owing\s+to)(?:\s+[a-z][a-z-]*){0,2}|for)\s+$", re.ASCII
)


def _open(match: re.Match[str], _text: str) -> Mention | None:
    return Mention(match.start(), match.end(), "open", INFERRED)


def _transportation(match: re.Match[str], _text: str) -> Mention | None:
    return Mention(
        match.start(),
        match.end(),
        "note",
        CERTAIN,
        note="transportation",
        scope_rule="none",
        negatable=False,
    )


# Rules -------------------------------------------------------------------------------

_D = DURATION
_C = CLOCK
_CS = CLOCK_STRICT
_EARLY_NOUN = r"(?:dismissal|release|out|closing|closure|dismiss)"
_DISMISS_VERB = (
    r"(?:dismiss(?:ing|ed|es|al)?|releas(?:ing|ed|es|e)|clos(?:ing|es|ed|e)|let(?:ting)?\s+out"
    r"|sending\s+(?:students\s+)?home|leav(?:ing|e))"
)
# What a dismissal verb can name before "early", a length or a time: "closing all schools early
# at noon", "dismissing students 2 hours early", "closing the school at 1 pm".
_DISMISSED = (
    r"(?:(?:all\s+(?:of\s+)?(?:our\s+|the\s+)?|our\s+|the\s+)?"
    r"(?:students|schools?|classes|buildings?|campus(?:es)?)\s+)?"
)
# The school day said to end, before its time: "classes end at noon", "school will let out at
# 12:30", "the school day ends at 1 pm".
_DAY_ENDS = r"(?:classes|school(?:\s+day)?)\s+(?:will\s+)?(?:end|ends|ending|let\s+out|lets\s+out)"
# A day named between a dismissal verb and its time: "closing Wednesday at noon".
_DAY_WORD = (
    r"(?:today|tomorrow|tonight|this\s+afternoon|mon(?:day)?|tue(?:s(?:day)?)?"
    r"|wed(?:s|nesday)?|thu(?:r(?:s(?:day)?)?)?|fri(?:day)?)"
)
# A day named between a status and its length: "delayed wednesday 2 hours", "opening late
# tomorrow, jan 21, 90 minutes", "closing early tuesday 2 hours". Today, tomorrow or a
# weekday, a date by month name or number, or a day word and a date together; a second may
# follow in apposition ("tomorrow, wednesday"), up to three can be listed ("delayed
# thursday and friday 2 hours"), and two can make a run of days ("delayed wednesday thru
# friday 2 hours", "wednesday-friday"). The days are left outside the mention, so they are
# read as the status's dates like any other days beside it (see _head_end).
_WHEN_DATE = (
    rf"(?:{trie(sorted(MONTH_NAMES))}\s*\d{{1,2}}(?:st|nd|rd|th)?|\d{{1,2}}/\d{{1,2}}"
    r"(?:/\d{2,4})?)\b"
)
_WHEN_ONE = (
    rf"(?:(?:{trie([*SCHOOL_DAY_WORDS, *WEEKDAYS])})\b(?:\s*,?\s*{_WHEN_DATE})?|{_WHEN_DATE})"
)
_WHEN = (
    rf"(?P<when>{_WHEN_ONE}"
    r"(?:\s*(?:,\s*(?:and\s+)?|and\s+|&\s*|/\s*|-+\s*|(?:thru|through)\s+)?"
    rf"{_WHEN_ONE}){{0,2}})"
    r"\s*[,:-]?\s*(?:(?:by|of|for)\s+)?"
)
# A day after "opening later" that makes it a late start that day: "opening later Wednesday".
_LATER_DAY = trie([*SCHOOL_DAY_WORDS, *WEEKDAYS])
# After a length: a word that makes it a status of its own ("2 hour delay", "2 hours early
# dismissal"), which a length read after a day must not be.
_NO_STATUS_AFTER = (
    r"(?!\s*-?\s*(?:early|delay|delayed|dly|late|dismiss|dismissal|release|start|opening"
    r"|arrival)\b)"
)
# A length tied to a day, which is that day's: "friday 3 hours", "3 hours friday".
_DAY_LENGTH = re.compile(
    rf"\b(?:{_WHEN_ONE}\s*[,:-]?\s*(?:(?:by|of|for)\s+)?(?P<after>{DURATION}){_NO_STATUS_AFTER}"
    rf"|(?P<before>{DURATION}){_NO_STATUS_AFTER}\s*,?\s*(?:on\s+)?{_WHEN_ONE})",
    re.ASCII,
)
# The characters the optional part after "delayed" and after "early dismissal" can start with,
# past spaces: a word before a length or a time ("of", "by", "at", "is"), a mark, a day (see
# _WHEN), a length (see DURATION) or a time (see CLOCK). A look at it first: "delayed until
# 10", "early dismissal; offices open" try none of the part's patterns.
_DELAY_TAIL_LOOK = r"(?=\s*[-0-9:abdefhjmnostw])"
_EARLY_TAIL_LOOK = r"(?=\s*[-0-9:@abdefhijmnostw])"
type Builder = Callable[[re.Match[str], str], Mention | None]

_RULES: tuple[tuple[str, Builder], ...] = (
    (
        rf"\b(?P<dur>{_D})\s*-?\s*(?:(?:delay(?:ed)?|dly)"
        r"(?:\s+(?:start|opening|arrival|schedule|entry))?"
        r"|late(?:\s+(?:start|opening|arrival))?(?!\s+(?:dismissal|release))"
        r"|delayed\s+(?:start|opening|arrival))\b",
        _delay_with_length,
    ),
    (
        r"\b(?P<word>late\s+(?:start|opening|arrival)|delayed\s+(?:start|opening|arrival|schedule)"
        r"|delay(?:ed|s)?|dly|(?:opening|open|start(?:ing)?)\s+(?:late|delayed"
        # "Opening Later", "Opening later Wednesday", but not "opening later this week".
        rf"|later(?=\s*(?:$|[;,.|!?(:-]|{_LATER_DAY}\b))))\b"
        rf"(?:{_DELAY_TAIL_LOOK}\s*(?:of|by|for|:|-)?\s*(?:{_WHEN})?(?P<dur>{_D})"
        rf"(?(when){_NO_STATUS_AFTER}|(?!\s*-?\s*early)))?",
        _delay_word,
    ),
    (
        r"\b(?:open(?:ing|s)?|start(?:ing|s)?|begin(?:ning|s)?|report(?:ing|s)?|arriv(?:e|ing|es)"
        r"|run(?:ning|s)?|operat(?:e|ing|es)|be|in\s+session)\s+(?:will\s+be\s+|is\s+|are\s+)?"
        rf"(?P<dur>{_D})\s+late\b",
        _delay_with_length,
    ),
    (
        # "Not opening until 10", "closed until noon": a late start, not a closure.
        r"\b(?:(?P<until>(?:(?:will\s+not|won't|not)\s+(?:be\s+)?(?:open|opening|start|starting"
        r"|begin|beginning)|clos(?:ed|ing))\s+(?:until|till|til))"
        rf"\s*(?P<clock3>{_C})"
        r"|(?:(?:re-?)?open(?:ing|s)?|start(?:ing|s)?|begin(?:ning|s)?|report(?:ing|s)?"
        r"|arriv(?:e|ing|es)|doors\s+open|start\s+time(?:\s*:|\s+(?:is|will\s+be))?)"
        r"(?:\s+(?:will\s+be|is))?"
        rf"\s*(?:(?:at|@)\s*(?P<clock>{_C})|(?P<clock2>{_CS}))"
        # "10 a.m. delayed start", "10AM start": the time before the words.
        rf"|(?P<clock4>{_CS})\s+(?:(?:delayed|late)\s+)?(?:start|opening|arrival)\b)",
        _opens_at,
    ),
    (rf"\b(?P<dur>{_D})\s*-?\s*early\s+{_EARLY_NOUN}\b", _early_with_length),
    (
        rf"\b(?:early\s+{_EARLY_NOUN}|early-out|earlyout)(?:\s+(?:day|time))?"
        rf"(?:{_EARLY_TAIL_LOOK}"
        r"\s*(?:at|@|of|:|-|by|is\s+at|is|will\s+be\s+at|will\s+be|starting\s+at|beginning\s+at"
        r"|begins\s+at|begin\s+at)?\s*"
        rf"(?:(?:{_WHEN})?(?P<dur>{_D})(?(when){_NO_STATUS_AFTER}|(?!\s*-?\s*(?:delay|late)))"
        rf"|(?P<clock>{_C})))?",
        _early_main,
    ),
    (
        rf"\b{_DISMISS_VERB}\s+{_DISMISSED}(?:{_WHEN})?(?:will\s+be\s+)?"
        rf"(?P<dur>{_D})\s+early\b",
        _early_length_first,
    ),
    (
        rf"\b(?:(?P<verb>{_DISMISS_VERB})\s+{_DISMISSED}|(?P<ends>{_DAY_ENDS})\s+)(?:early\s+)?"
        rf"(?:(?P<when>{_DAY_WORD})\s+)?(?:time\s+)?"
        rf"(?:will\s+be\s+|is\s+)?(?:(?:at|@)\s*(?P<clock>{_C})|(?P<strict>{_CS}))",
        _early_at,
    ),
    (rf"\b(?P<clock>{_CS})\s+(?:early\s+)?(?:dismissal|release|dismiss)\b", _early_clock_first),
    (
        rf"\b(?:{_DISMISS_VERB}\s+{_DISMISSED}early\b(?:\s*(?:by|:|-)?\s*(?:{_WHEN})?(?P<dur>{_D})"
        rf"{_NO_STATUS_AFTER})?|half[- ]day|half\s+day|1/2\s+day|noon\s+dismissal)\b",
        _early_bare,
    ),
    (
        # "Closed for the remainder of the day": sent home during the school day.
        rf"\b{_DISMISS_VERB}\s+(?:students\s+)?(?:for\s+)?(?:the\s+)?(?:rest|remainder|balance)"
        r"\s+of\s+(?:the\s+|today'?s?\s+)?(?:school\s+)?day\b",
        _rest_of_day,
    ),
    (
        # "NTI" and "NTID" (non-traditional instruction, or its day), "non-traditional
        # learning" (West Virginia's statewide list), "flexible instruction" with or without
        # "day", "AMI" (alternative methods of instruction).
        r"\b(?:ntid|nti(?:\s+days?)?"
        r"|non-?\s?traditional\s+(?:(?:instruction(?:al)?|learning)(?:\s+days?)?|days?)"
        r"|non-?\s?traditional(?=\s*:)"
        r"|ami(?:\s+days?)?|alternative\s+methods?\s+(?:of\s+)?instruction(?:\s+days?)?"
        r"|alternat(?:e|ive)\s+(?:learning|instruction(?:al)?)\s+days?"
        r"|e-?\s?learning(?:\s+days?)?"
        r"|virtual(?:ly)?(?:\s+(?:learning|instruction(?:al)?|classes|school|snow))?(?:\s+days?)?"
        r"|remote(?:ly)?(?:\s+(?:learning|instruction(?:al)?|classes|snow))?(?:\s+days?)?"
        r"|online(?:\s+(?:learning|instruction|classes|school)(?:\s+days?)?)?"
        r"|distance\s+learning(?:\s+days?)?|flex(?:ible)?\s+instruction(?:al)?(?:\s+days?)?|fid"
        r"|a?synchronous(?:\s+(?:learning|instruction))?(?:\s+days?)?|async(?:\s+days?)?"
        r"|(?:at-?\s?)?home\s+learning(?:\s+days?)?|learn(?:ing)?\s+(?:from|at)\s+home"
        r"|digital\s+learning(?:\s+days?)?|cyber\s+(?:days?|school|learning)"
        r"|blizzard\s+bags?(?:\s+days?)?|independent\s+learning\s+days?"
        r"|innovative\s+learning\s+days?)\b",
        _remote,
    ),
    (
        # "No school", and the same said with "not": "there will not be school", "we do not
        # have classes".
        r"\b(?:no|(?:(?:there|we|students)\s+(?:(?:will|shall|do|does)\s+not|won't|wont|don't"
        r"|is\s+not|isn't|are\s+not|aren't)|(?:we're|there's)\s+not)"
        r"(?:\s+be)?(?:\s+(?:have|having))?(?:\s+any)?)"
        # "No in-person or remote classes": neither way of holding school.
        r"\s+(?:(?P<both>(?:in[- ]person|face[- ]to[- ]face)\s+(?:or|and|nor)"
        r"\s+(?:remote|virtual|online)"
        r"|(?:remote|virtual|online)\s+(?:or|and|nor)\s+(?:in[- ]person|face[- ]to[- ]face))"
        r"(?:\s+(?:classes|class|learning|instruction|school))?\b"
        # "No AM kindergarten", "no day or evening classes", "no AM or PM classes".
        r"|(?P<mod>(?:am|pm|morning|afternoon|evening|day(?!\s+care\b)|half-day|half\s+day"
        r"|full-day|after-school|after\s+school|before-school|in-person|in\s+person)\s+"
        r"(?:(?:or|and|nor)\s+(?P<mod2>am|pm|morning|afternoon|evening|night|day)\s+)?)?"
        # (A hyphen before another "no" parts two phrases: "No School-No Personnel Report",
        # and so does one before the staff: "No School-Staff Report at 10".)
        r"(?P<obj>[a-z0-9][a-z0-9']*(?:-(?!(?:no|staff|personnel|employees|teachers|faculty)\b)"
        r"[a-z0-9']*)*)(?:\s+(?P<obj2>[a-z][a-z'-]*))?)",
        _no,
    ),
    (
        r"\b(?:not\s+in\s+session|no\s+session|(?:will|shall)\s+not\s+(?:be\s+in\s+session|meet"
        r"|open|hold\s+(?:school|classes))|won't\s+(?:be\s+in\s+session|meet|open)"
        r"|(?:is|are|will\s+be)\s+not\s+open|(?:school|classes)\s+(?:will\s+)?not\s+(?:be\s+)?held)"
        r"\b(?!\s+(?:until|on\s+time|at|before|late))",
        _not_in_session,
    ),
    (
        r"\b(?:closed|closure|closures|closings?|shut\s*down|shut|snow\s+day|calamity\s+day"
        r"|no-school\s+days?|snowed\s+out"
        r"|emergency\s+(?:closing|closure)|(?:inclement\s+)?weather\s+(?:closing|closure)"
        r"|full\s+closure)\b",
        _closed,
    ),
    (
        # "canx", "cxl" and "cncl" are the short forms some closings feeds use.
        r"\b(?:cancel(?:l?ed|l?ing|s|l?ations?)?|canx|cxld?|cncld?|call(?:ed|ing|s)?\s+off"
        r"|postponed|rescheduled|suspended)\b",
        _cancelled,
    ),
    (
        r"\b(?:lift(?:ed|ing|s)?|rescind(?:ed|ing|s)?|revok(?:ed|ing|es|e)"
        r"|withdr(?:awn|awing|aws|aw|ew)|retract(?:ed|ing|s)?|revers(?:ed|ing|es|e)"
        r"|scrap(?:ped|ping|s)?|no\s+longer\s+(?:in\s+(?:effect|place)|happening|needed"
        r"|necessary|required|planned|scheduled)|(?:is|are)\s+(?:now\s+)?off"
        r"|(?:(?:will|shall|does|do|is|are)\s+not|won't|isn't|aren't)\s+(?:be\s+)?"
        r"(?:take\s+place|happen(?:ing)?|occur(?:ring)?|go(?:ing)?\s+ahead|needed|necessary"
        r"|required)|not\s+(?:needed|necessary|required))\b",
        _revoke,
    ),
    (
        r"\b(?:(?:inclement\s+weather|winter\s+weather|weather|cold|storm|emergency|ice|flex)"
        r"\s+(?:days?|schedule|plan|procedures?)|inclement\s+weather)\b",
        _ambiguous_day,
    ),
    (
        r"\b(?:open(?:s|ed)?(?!\s+(?:at|until|till|late|(?:one|two|three|an?)\s+hours?|house|houses"
        r"|gym|enrollment|registration|forum|mic|swim|skate)\b)"
        r"(?!\s*\d(?!\d?(?:/\d|(?:st|nd|rd|th)\b)))|on\s+time"
        r"|(?:regular|normal|usual)\s+(?:schedule|hours|day|start|start\s+time"
        r"|time|session|operations|bell\s+schedule|school\s+day)|business\s+as\s+usual"
        r"|as\s+scheduled|in\s+session)\b",
        _open,
    ),
    (
        r"\b(?:(?:buses|busses|bus)\s+(?:(?:will|are|is)\s+)?not\s+(?:be\s+)?(?:run(?:ning)?"
        r"|operat(?:e|ing))"
        r"|(?:buses|busses|bus)\s+(?:will\s+)?(?:be\s+)?(?:on|run(?:ning)?\s+on|running|using"
        r"|follow(?:ing)?)\s+(?:snow|emergency|hazard(?:ous)?|inclement\s+weather|alternate"
        r"|limited|paved|main)\s+(?:roads?\s+|bus\s+)?routes?|(?:snow|emergency|hazardous|hazard"
        r"|inclement\s+weather)\s+(?:bus\s+)?routes?|limited\s+(?:bus\s+service|transportation"
        r"|busing|bussing)|paved\s+roads\s+only|main\s+roads\s+only)\b",
        _transportation,
    ),
)


# Which rules can match: every match of a rule contains one of its trigger words, and a
# clock time or a length when the rule needs one. One scan of the text finds the
# trigger words present, so only the rules that can match are run.
type Need = Literal["clock", "length"] | None

_DISMISS_KEYS = ("dismiss", "releas", "clos", "let", "sending", "leav")
_TRIGGERS: tuple[tuple[tuple[str, ...], Need], ...] = (
    (("dela", "late", "dly"), "length"),
    (("dela", "late", "dly"), None),
    (("late",), "length"),
    (("open", "start", "begin", "report", "arriv", "door", "clos"), "clock"),
    (("early",), "length"),
    (("early",), None),
    (("early",), "length"),
    ((*_DISMISS_KEYS, "end"), "clock"),
    (("dismiss", "releas"), "clock"),
    (("early", "half", "1/2", "noon"), None),
    (("rest", "remainder", "balance"), None),
    (
        (
            "nti", "traditional", "ami", "instruction", "learning", "virtual", "remote",
            "online", "distance", "flex", "fid", "synchronous", "async", "home", "digital",
            "cyber", "blizzard",
        ),
        None,
    ),
    (("no ", " not", " won't", " wont", " don't", " isn't", " aren't"), None),
    (("not", "session", "won't"), None),
    (("clos", "shut", "snow", "calamity", "no-school"), None),
    (("cancel", "canx", "cxl", "cncl", "call", "postpon", "reschedul", "suspend"), None),
    (
        (
            "lift", "rescind", "revok", "withdr", "retract", "revers", "scrap", "longer", " off",
            " place", "happen", "occur", " ahead", "needed", "necessary", "required",
        ),
        None,
    ),
    (("weather", "storm", "emergency", "inclement", " cold", " ice", " flex"), None),
    (("open", "on time", "regular", "normal", "usual", "business", "scheduled", "session"), None),
    (("route", "limited", "roads only", " not"), None),
)  # fmt: skip
_COMPILED: tuple[tuple[re.Pattern[str], Builder, Need], ...] = tuple(
    (re.compile(pattern, re.ASCII), builder, need)
    for (pattern, builder), (_words, need) in zip(_RULES, _TRIGGERS, strict=True)
)
_RULES_BY_WORD: dict[str, tuple[int, ...]] = {}
for _index, (_words, _need) in enumerate(_TRIGGERS):
    for _word in _words:
        _RULES_BY_WORD[_word] = (*_RULES_BY_WORD.get(_word, ()), _index)
# Triggers with a space name the word that must be present: "no school" needs "no".
_WHOLE_WORDS: dict[str, tuple[str, ...]] = {
    " cold": ("cold",),
    " ice": ("ice",),
    " flex": ("flex",),
    "no ": ("no",),
    " not": ("not",),
    " won't": ("won't",),
    " wont": ("wont",),
    " don't": ("don't",),
    " isn't": ("isn't",),
    " aren't": ("aren't",),
    "on time": ("time",),
    "roads only": ("only",),
    " off": ("off",),
    " place": ("place",),
    " ahead": ("ahead",),
}
_PARTS = tuple((key, rules) for key, rules in _RULES_BY_WORD.items() if key not in _WHOLE_WORDS)
# Any of the parts, anywhere in a word: most words (names above all) hold none.
PART_KEYS: tuple[str, ...] = tuple(key for key, _rules in _PARTS)
"""The parts of words some rule needs (see :func:`rule_mask`)."""
_ANY_PART = re.compile(trie(PART_KEYS), re.ASCII)
ANY_PART = _ANY_PART
"""Any part of a word some rule needs (see :func:`rule_mask`), anywhere in a word."""
_EXACT: dict[str, tuple[int, ...]] = {}
for _key, _forms in _WHOLE_WORDS.items():
    for _form in _forms:
        _EXACT[_form] = (*_EXACT.get(_form, ()), *_RULES_BY_WORD[_key])


# Where each rule's matches start. Every rule opens with a word boundary and a word, so a
# match starts where a run of letters and digits does: these are that run's opening letters
# (a prefix: "clos" fits "closed" and "closing") or, ending in "$", the whole run ("in$" is
# the "in" of "in session", "won$" the "won" of "won't"). Trying a rule only at the runs one
# of its entries fits finds the matches a scan of the whole text finds (see find_mentions).
# A length starts with a number: digits, a number word, "a" or "an" ("an hour", or joined to
# its unit: "ahr"), "half" or "hour" ("hour and a half"). A word that only starts a length
# with a space after it is whole ("a$"); one that can run into its unit stays a prefix.
_NUMBER_STARTS = (
    *"0123456789", "one", "two", "three", "four", "five", "a$", "an$", "ah", "anh", "a1",
    "an1", "half$", "halfh", "half1", "twenty", "forty", "seventy", "fifteen", "thirty",
    "fifty", "sixty", "eighty", "ninety", "ten$", "tenm", "hour$",
)  # fmt: skip
# The forms of _DISMISS_VERB, each followed by a space in every rule that opens with it.
_DISMISS_STARTS = (
    "dismiss$", "dismissing$", "dismissed$", "dismisses$", "dismissal$", "releasing$",
    "released$", "releases$", "release$", "closing$", "closes$", "closed$", "close$", "let$",
    "letting$", "sending$", "leaving$", "leave$",
)  # fmt: skip
_STARTS: tuple[tuple[str, ...], ...] = (
    _NUMBER_STARTS,
    (
        "late$", "delay$", "delayed$", "delays$", "dly$", "open$", "opening$", "start$",
        "starting$",
    ),
    (
        "open$", "opening$", "opens$", "start$", "starting$", "starts$", "begin$", "beginning$",
        "begins$", "report$", "reporting$", "reports$", "arrive$", "arriving$", "arrives$",
        "run$", "running$", "runs$", "operate$", "operating$", "operates$", "be$", "in$",
    ),
    (
        "will$", "won$", "not$", "closed$", "closing$", "open", "reopen", "re$", "start", "begin",
        "report", "arriv", "doors$", *"0123456789", "noon$", "midday$",
    ),
    _NUMBER_STARTS,
    ("early$", "earlyout$"),
    _DISMISS_STARTS,
    (*_DISMISS_STARTS, "classes$", "school$"),
    (*"0123456789", "noon$", "midday$"),
    (*_DISMISS_STARTS, "half$", "1$", "noon$"),
    _DISMISS_STARTS,
    (
        "nti", "non", "ami", "alternat", "elearning", "e$", "virtual", "remote", "online",
        "distance", "flex", "fid", "async", "synchronous", "at$", "athome", "home", "learn",
        "digital", "cyber", "blizzard", "independent", "innovative",
    ),
    ("no$", "there$", "we$", "students$"),
    ("not$", "no$", "will$", "shall$", "won$", "is$", "are$", "school$", "classes$"),
    (
        "closed$", "closure$", "closures$", "closing$", "closings$", "shut$", "shutdown$",
        "snow$", "calamity$", "no$", "emergency$", "inclement$", "weather$", "full$", "snowed$",
    ),
    ("cancel", "canx", "cxl", "cncl", "call", "postponed", "rescheduled", "suspended"),
    (
        "lift", "rescind", "revok", "withdr", "retract", "revers", "scrap", "no$", "is$", "are$",
        "will$", "shall$", "does$", "do$", "won$", "isn$", "aren$", "not$",
    ),
    ("inclement$", "winter$", "weather$", "cold$", "storm$", "emergency$", "ice$", "flex$"),
    (
        "open$", "opens$", "opened$", "on$", "regular$", "normal$", "usual$", "business$", "as$",
        "in$",
    ),
    (
        "bus$", "buses$", "busses$", "snow$", "emergency$", "hazard$", "hazardous$",
        "inclement$", "limited$", "paved$", "main$",
    ),
)  # fmt: skip
# Words every match of a rule holds after the place it starts: a length's rule reads the
# delay or "early" after it. A rule is not tried where no such word follows.
_LATER_WORDS: dict[int, tuple[str, ...]] = {
    0: ("delay", "dly", "late"),
    2: ("late",),
    4: ("early",),
    6: ("early",),
    8: ("dismiss", "releas"),
    10: ("day",),
    17: ("day", "schedule", "plan", "procedure", "weather"),
}
# Rules whose matches start at words of different families, each family with words that
# every match starting at one of its words holds after it: "closed until 10" holds "til", "10
# am start" holds "start", "snow day" holds "day". Such a rule is tried as one sub-rule per
# family, so that where a family's words are missing it is not tried at all (see
# mentions_at). The families of a rule share out its start entries (see _STARTS).
_FAMILIES: dict[int, tuple[tuple[tuple[str, ...], tuple[str, ...] | None], ...]] = {
    3: (
        (("will$", "won$", "not$", "closed$", "closing$"), ("til",)),  # "until", "till", "til"
        (("open", "reopen", "re$", "start", "begin", "report", "arriv", "doors$"), None),
        ((*"0123456789", "noon$", "midday$"), ("start", "opening", "arrival")),
    ),
    9: (
        (_DISMISS_STARTS, ("early",)),
        (("half$", "1$"), ("day",)),
        (("noon$",), ("dismiss",)),
    ),
    11: (
        (("at$",), ("home",)),
        (tuple(entry for entry in _STARTS[11] if entry != "at$"), None),
    ),
    14: (
        (
            (
                "closed$",
                "closure$",
                "closures$",
                "closing$",
                "closings$",
                "shut$",
                "shutdown$",
                "snowed$",
            ),
            None,
        ),
        (("snow$", "calamity$", "no$"), ("day",)),
        (("emergency$", "inclement$", "weather$", "full$"), ("clos",)),
    ),
    18: (
        (("open$", "opens$", "opened$"), None),
        (("on$",), ("time",)),  # "on time"
        (
            ("regular$", "normal$", "usual$"),  # "regular schedule", "normal school day"
            ("schedule", "hours", "day", "start", "time", "session", "operations"),
        ),
        (("business$",), ("usual",)),  # "business as usual"
        (("as$",), ("scheduled",)),  # "as scheduled"
        (("in$",), ("session",)),  # "in session"
    ),
}
# The sub-rules, in the rules' order: each rule's index (its "slot"), where it can start and
# the words it needs after that. A rule with no families is one sub-rule of its own.
_SUB_RULES: tuple[tuple[int, tuple[str, ...], tuple[str, ...] | None], ...] = tuple(
    sub
    for _index, _entries in enumerate(_STARTS)
    for sub in (
        tuple((_index, family, later) for family, later in _FAMILIES[_index])
        if _index in _FAMILIES
        else ((_index, _entries, _LATER_WORDS.get(_index)),)
    )
)
assert all(  # noqa: S101 - the families of a rule are its start entries, shared out
    sorted(entry for family, _later in families for entry in family) == sorted(_STARTS[index])
    for index, families in _FAMILIES.items()
)
_SLOTS: tuple[int, ...] = tuple(slot for slot, _entries, _later in _SUB_RULES)
_SLOT_COUNT = len(_COMPILED)
# Two rules that few listings trigger and few words can start ("early dismissal", and "snow
# day" read as a day of its own kind): their sub-rules take the top two bits, so the masks of
# nearly every text and run fit in 30 bits, which Python works on as one small number. The
# sub-rules keep their order (see mentions_at); only the bit that stands for each one moves.
_RARE_RULES = frozenset({5, 17})
_BY_BIT = sorted(range(len(_SUB_RULES)), key=lambda order: (_SLOTS[order] in _RARE_RULES, order))
_BIT_OF: tuple[int, ...] = tuple(1 << _BY_BIT.index(order) for order in range(len(_SUB_RULES)))
"""The bit that stands for each sub-rule (by its order in _SUB_RULES)."""
_SUB_BITS: tuple[int, ...] = tuple(
    reduce(or_, (_BIT_OF[order] for order, slot in enumerate(_SLOTS) if slot == index))
    for index in range(_SLOT_COUNT)
)
"""The bits of each rule's sub-rules."""
RULE_BITS = (1 << len(_SUB_RULES)) - 1
"""The bits :func:`rule_mask` can set: one for each sub-rule (see _SUB_RULES and _BIT_OF)."""
CLOCK_RULES = reduce(
    or_, (_SUB_BITS[index] for index, (_w, need) in enumerate(_TRIGGERS) if need == "clock")
)
"""The rules whose every match holds a clock time: a digit, "noon" or "midday"."""
_WHOLE_STARTS: dict[str, int] = {}
_PREFIX_STARTS: dict[str, dict[str, int]] = {}  # by first letter: prefix -> rules
for _order, (_slot, _entries, _later) in enumerate(_SUB_RULES):
    for _entry in _entries:
        if _entry.endswith("$"):
            _WHOLE_STARTS[_entry[:-1]] = _WHOLE_STARTS.get(_entry[:-1], 0) | _BIT_OF[_order]
        else:
            _group = _PREFIX_STARTS.setdefault(_entry[0], {})
            _group[_entry] = _group.get(_entry, 0) | _BIT_OF[_order]
_PREFIXES_BY_FIRST: dict[str, tuple[tuple[str, int], ...]] = {
    first: tuple(group.items()) for first, group in _PREFIX_STARTS.items()
}
PREFIX_STARTS: tuple[tuple[str, ...], ...] = tuple(
    tuple(group) for group in _PREFIX_STARTS.values()
)
"""The run prefixes the rules can start at, by first letter (see :func:`start_mask`)."""
START_WORDS: tuple[str, ...] = tuple(
    sorted({*_WHOLE_STARTS, *(p for g in _PREFIX_STARTS.values() for p in g)})
)
"""Every run, or run prefix, that some rule can start at."""


# The prefixes of each first letter, grouped by the rules they start: one test per group.
_PREFIX_GROUPS: dict[str, tuple[tuple[int, tuple[str, ...]], ...]] = {}
for _first, _pairs in _PREFIXES_BY_FIRST.items():
    _by_rules: dict[int, list[str]] = {}
    for _prefix, _rules in _pairs:
        _by_rules.setdefault(_rules, []).append(_prefix)
    _PREFIX_GROUPS[_first] = tuple((rules, tuple(keys)) for rules, keys in _by_rules.items())


@lru_cache(maxsize=65536)
def start_mask(run: str) -> int:
    """The rules whose matches can start at a run of letters and digits, as bits."""
    mask = _WHOLE_STARTS.get(run, 0)
    for rules, prefixes in _PREFIX_GROUPS.get(run[:1], ()):
        if run.startswith(prefixes):
            mask |= rules
    return mask


# The parts of _PARTS by their first letter, each with the bits of the rules it triggers: a
# word holds a part only where it holds the part's first letter, so only those are looked for.
_PARTS_BY_FIRST: dict[str, tuple[tuple[str, int], ...]] = {}
for _part, _part_rules in _PARTS:
    _PARTS_BY_FIRST[_part[0]] = (
        *_PARTS_BY_FIRST.get(_part[0], ()),
        (_part, reduce(or_, (_SUB_BITS[_rule] for _rule in _part_rules), 0)),
    )


@lru_cache(maxsize=65536)
def rule_mask(word: str) -> int:
    """The rules one word can trigger, as bits (cached: listings reuse a small vocabulary).

    A word a rule needs whole counts as a part of a word joined by a hyphen or a
    slash too, as the rules' patterns read it: the "no" of "school-no" in "No
    School-No Personnel Report".
    """
    mask = 0
    if _ANY_PART.search(word) is not None:
        for first in set(word):
            for key, bits in _PARTS_BY_FIRST.get(first, ()):
                if key in word:
                    mask |= bits
    parts = (word, *_JOINS.split(word)) if "-" in word or "/" in word else (word,)
    for part in parts:
        for index in _EXACT.get(part, ()):
            mask |= _SUB_BITS[index]
    return mask


_JOINS = re.compile(r"[/-]", re.ASCII)  # the marks that join the parts of a word ("school-no")


@lru_cache(maxsize=4096)
def _selected(mask: int) -> tuple[tuple[int, int, re.Pattern[str], Builder, Need], ...]:
    """The sub-rules a mask of :func:`rule_mask` bits selects, in order, each with its slot."""
    return tuple(
        (order, slot, *_COMPILED[slot])
        for order, slot in enumerate(_SLOTS)
        if mask & _BIT_OF[order]
    )


# Every clock time a "clock" rule needs has a colon, am or pm, noon, or follows "at" or "until".
_CLOCK_HINT = re.compile(
    r"\d(?::\d\d|\s*[ap]m\b)|(?:\b(?:at|until|till|til)\s*|@\s*)\d|noon|midday", re.ASCII
)
# Every length has a unit: "hour", "hr", "min", or "h" or "m" right after its number.
_SHORT_UNIT = re.compile(r"\d\s*-?\s*[hm]\b", re.ASCII)


def _has_length(text: str) -> bool:
    return (
        "hour" in text
        or "hr" in text
        or "min" in text
        or (("h" in text or "m" in text) and _SHORT_UNIT.search(text) is not None)
    )


# Nouns for an institution or a program, which a status phrase before them names rather than
# states: "Ohio Virtual Academy", "eLearning Academy", "Late Start Program".
INSTITUTION_NOUNS = frozenset(
    {
        "academy", "academies", "program", "programs", "institute", "institutes", "center",
        "centers", "centre", "centres", "charter",
    }
)  # fmt: skip
_INSTITUTION_AFTER = re.compile(r" (?:" + trie(sorted(INSTITUTION_NOUNS)) + r")\b", re.ASCII)
_STATUS_KINDS: frozenset[MentionKind] = frozenset(
    {"closed", "delayed", "remote", "early_dismissal"}
)


def _names_institution(text: str, mention: Mention) -> bool:
    """Whether a status phrase is the start of an institution's name: "Virtual Academy"."""
    return mention.kind in _STATUS_KINDS and _INSTITUTION_AFTER.match(text, mention.end) is not None


def find_mentions(  # noqa: PLR0912 - the gates on each rule, then the overlap pass
    text: str,
    vocabulary: Iterable[str] | None = None,
    rules: int | None = None,
    runs: Pieces | None = None,
    *,
    institutions: bool = True,
) -> list[Mention]:
    """Return the non-overlapping mentions in normalized ``text``, in order.

    ``rules`` is the union of :func:`rule_mask` over the text's words, when the
    caller has it; otherwise it is worked out from ``vocabulary`` (the set of
    the text's words) or the text. Where several rules match at the same place
    the longest match wins (the earlier rule on a tie); a mention hides every
    match that starts inside it.

    ``runs``, when the caller has it, lists where every run of letters and
    digits that a rule can start at starts in the text, in order, with its
    :func:`start_mask` bits (more runs will do), by the stretch that holds it
    (see :data:`~snowlight.classify.text.Pieces`). Each rule is then tried only
    at its runs rather than scanned across the whole text: the matches are the
    same, since a match starts at a run the rule's :data:`_STARTS` fit.

    A status phrase right before a noun of :data:`INSTITUTION_NOUNS` names an
    institution or a program ("Virtual Academy: closed", "Late Start Program:
    open") and is no mention. ``institutions`` is false when the caller knows
    the text holds none of those nouns.
    """
    if rules is None:
        vocabulary = set(words(text)) if vocabulary is None else vocabulary
        rules = reduce(or_, map(rule_mask, vocabulary), 0)
    if not rules:
        return []
    if runs is not None:
        places = [(base + offset, mask) for base, found in runs for offset, mask in found]
        return mentions_at(text, rules, places, institutions)
    # (start, minus length, rule): unique per match, so the mentions are never compared.
    candidates: list[tuple[int, int, int, Mention]] = []
    clock = length = None
    tried = 0  # the rules scanned already (a rule's sub-rules share its pattern)
    for _order, order, pattern, builder, need in _selected(rules):
        if tried >> order & 1:
            continue
        tried |= 1 << order
        if need == "clock":
            if clock is None:
                clock = _CLOCK_HINT.search(text) is not None
            if not clock:
                continue
        elif need == "length":
            if length is None:
                length = _has_length(text)
            if not length:
                continue
        for match in pattern.finditer(text):
            mention = builder(match, text)
            if mention is not None:
                candidates.append((mention.start, mention.start - mention.end, order, mention))
    if institutions and candidates:
        candidates = [
            candidate for candidate in candidates if not _names_institution(text, candidate[3])
        ]
    if len(candidates) < 2:  # noqa: PLR2004 - one mention or none: nothing overlaps
        return [candidate[3] for candidate in candidates]
    candidates.sort()
    chosen: list[Mention] = []
    end = -1
    for start, _length, _order, mention in candidates:
        if start >= end:
            chosen.append(mention)
            end = mention.end
    return chosen


type _Trial = tuple[
    int,
    int,
    Callable[[str, int], re.Match[str] | None],
    Builder,
    str | tuple[str, ...] | None,
    int,
]


def _trials(mask: int) -> tuple[_Trial, ...]:
    """The sub-rules a mask of rule bits holds, in order: each with its slot, its pattern's
    ``match``, its builder, the words its matches hold after their start (see
    :data:`_SUB_RULES`; the word itself when there is one), and the mask that clears its bit.

    Worked out the first time a mask is met, and kept (a mask is a set of the rules, so there
    are few); a plain dict, which the walk reads with one lookup (see :func:`mentions_at`).
    """
    trials: list[_Trial] = []
    for order, slot, pattern, builder, _need in _selected(mask):
        later = _SUB_RULES[order][2]
        single = later[0] if later and len(later) == 1 else later
        trials.append((order, slot, pattern.match, builder, single, ~_BIT_OF[order]))
    found = tuple(trials)
    _TRIALS[mask] = found
    return found


_TRIALS: dict[int, tuple[_Trial, ...]] = {}
_trials_of = _TRIALS.get
# The limit of each rule (see _candidates_at) before it is worked out: none for a rule that
# needs no word after its start.
_UNKNOWN = -2
_NO_LIMITS = [_UNKNOWN if later else 1 << 62 for _slot, _entries, later in _SUB_RULES]


def mentions_at(  # noqa: PLR0912 - one walk: the gates on each trial, then the choice
    text: str, rules: int, runs: Sequence[tuple[int, int]], institutions: int
) -> list[Mention]:
    """The mentions :func:`find_mentions` returns, from the ``rules`` tried at ``runs``.

    ``runs`` are the runs of :func:`find_mentions` one by one, each as where it
    starts in the text and its start mask.

    Every match of a rule starts at a run whose start mask holds the rule (see
    :func:`start_mask`), so trying each rule at those runs in order, each at or
    after the end of the rule's last match, finds the matches a scan of the
    whole text finds; a run past the last of the words a sub-rule needs after
    its start (see :data:`_SUB_RULES`) can start none of its matches. The runs
    are walked once, and at each only the sub-rules its mask holds are tried.
    A rule's sub-rules share its pattern, and where its last match ended (its
    slot): they start at different words, so at any place only one of them can
    be tried, and the rule's matches are found as the one rule would find them.

    The mentions are chosen as the walk goes, since the runs come in order: at
    each place, the longest match (the earlier rule on a tie), unless it starts
    inside the mention chosen last. A match that starts there is hidden, so a
    rule is not tried at such a place; but where a rule's hidden match would
    have ended still bars its matches up to there, so the places it skipped are
    tried first when it is next tried at a place that is not hidden.
    """
    ends = [0] * _SLOT_COUNT  # each rule's last match ends here
    # Each sub-rule's matches start before this: for one that needs a word after its start,
    # where the last of those words starts (-1: none does), worked out when first needed.
    limits = _NO_LIMITS.copy()
    alive = rules  # the runs come in order: a sub-rule past its limit is tried nowhere after
    chosen: list[Mention] = []
    chosen_end = 0  # where the mention chosen last ends
    skipped: dict[int, list[int]] = {}  # by rule: the hidden places it was not tried at
    for position, mask in runs:
        selected = mask & alive
        if not selected:
            continue
        hidden = position < chosen_end
        best: Mention | None = None
        trials = _trials_of(selected) or _trials(selected)
        for order, slot, match_at, builder, later, clear in trials:
            if position < ends[slot]:
                continue
            if later is not None:
                limit = limits[order]
                if limit == _UNKNOWN:
                    limit = limits[order] = (
                        text.rfind(later) if type(later) is str else max(map(text.rfind, later))
                    )
                if position >= limit:
                    alive &= clear
                    continue
            if hidden:
                skipped.setdefault(slot, []).append(position)
                continue
            if skipped and slot in skipped:
                for earlier in skipped.pop(slot):
                    if earlier >= ends[slot]:
                        passed = match_at(text, earlier)
                        if passed is not None:
                            ends[slot] = passed.end()
                if position < ends[slot]:
                    continue
            match = match_at(text, position)
            if match is None:
                continue
            ends[slot] = match.end()
            mention = builder(match, text)
            if mention is None or (
                institutions  # (see _names_institution)
                and mention.kind in _STATUS_KINDS
                and _INSTITUTION_AFTER.match(text, mention.end) is not None
            ):
                continue
            if best is None or mention.end > best.end:
                best = mention  # (the rules come in order: on a tie the earlier stays)
        if best is not None:
            chosen.append(best)
            chosen_end = best.end
    return chosen


def _clock_possible(text: str) -> bool:
    """Whether a clock time a "clock" rule needs can be in ``text`` (see :data:`_CLOCK_HINT`)."""
    return (
        ":" in text
        or "m" in text  # "am", "pm", "midday"
        or "noon" in text
        or "at" in text
        or "til" in text
        or "@" in text
    ) and _CLOCK_HINT.search(text) is not None


# A time after "at", "by" or "until" may be a bare hour ("delayed until 10"); elsewhere it must
# look like a time ("delayed, doors open 9:45"). A bare hour before letters ("until 10th") is
# no time.
_HARVEST_CLOCK = re.compile(
    rf"(?:\b(?:at|@|by|until|till|'?til)\s*(?P<clock>{_C})(?![a-z])|\b(?P<strict>{_CS}))",
    re.ASCII,
)
_ANY_DIGIT = re.compile(r"\d", re.ASCII)
# Every time _HARVEST_CLOCK finds holds a colon, "noon" or "midday", or follows "at", "@", "by"
# or "til" (and "until", "till"), or is a number before "a" or "p" ("1 pm", "9a"): a span with
# none of them holds none.
_DIGIT_BEFORE_MERIDIEM = re.compile(r"\d\s*[ap]", re.ASCII).search
_HARVEST_EARLY = re.compile(rf"\b(?P<dur>{_D})\s+early\b", re.ASCII)


def _clocks(text: str, start: int, end: int) -> set[str]:
    """The clock times stated in ``text[start:end]`` that can be the status's own.

    A time whose own clause names something besides the school is that thing's:
    "Opening at 10 a.m., staff report at 9:30" opens at 10.
    """
    return _clocks_found(text, start, end)[0]


def _clocks_found(text: str, start: int, end: int) -> tuple[set[str], list[re.Match[str]]]:
    """:func:`_clocks`, and every clock time found in the span (see :func:`_times_by_level`)."""
    if start >= end or (
        _ANY_DIGIT.search(text, start, end) is None and "noon" not in text and "midday" not in text
    ):
        return set(), []  # (every clock time holds a digit, "noon" or "midday")
    span = text[start:end]
    if not (
        ":" in span
        or "at" in span
        or "noon" in span
        or "midday" in span
        or "@" in span
        or "by" in span
        or "til" in span
    ) and (_DIGIT_BEFORE_MERIDIEM(span) is None):
        return set(), []  # (a day's number, the most common: no time, see _DIGIT_BEFORE_MERIDIEM)
    found = list(_HARVEST_CLOCK.finditer(text, start, end))
    own = {
        match.group("clock") or match.group("strict")
        for match in found
        if not _another_subject(text, start, match.start())
    }
    return own, found


def _another_subject(text: str, start: int, end: int) -> bool:
    """Whether the clause before ``end``, from ``start`` on, names something besides the school.

    The clause starts after the last comma, semicolon or bar before ``end``. A
    noun of :data:`~snowlight.classify.lexicon.SCOPES` for staff, offices,
    activities, part of the program, childcare or buses names such a thing.
    """
    mark = max(
        text.rfind(",", start, end), text.rfind(";", start, end), text.rfind("|", start, end)
    )
    found = words(text, max(start, mark + 1), end)
    for index, word in enumerate(found):
        scope = SCOPES.get(word)
        if scope is None and index + 1 < len(found):
            scope = SCOPES.get(f"{word} {found[index + 1]}")
        if scope is not None and scope != "school":
            return True
    return False


def _times_by_level(text: str, start: int, end: int, found: list[re.Match[str]]) -> bool:
    """Whether the span gives times by level: two clock times (``found`` holds every one, see
    :func:`_clocks`), one of them after a noun for part of the program in its clause ("at 11
    am for elementary schools and 11:20 am for middle schools"), which :func:`_clocks` leaves
    out as another subject's."""
    if len(found) < _TWO_TIMES:
        return False
    marks = text.count(" am", start, end) + text.count(" pm", start, end)
    if marks + text.count(":", start, end) < _TWO_TIMES:
        return False
    # (A noun before the last time is before every time after it: the first noun before the
    # last time is the one before any time after it.)
    return _subject_scope(text, start, found[-1].start()) == "partial"


_TWO_TIMES = 2  # (the clock marks two times need at least: see _times_by_level)


def _subject_scope(text: str, start: int, end: int) -> str | None:
    """The scope of the first noun of :data:`SCOPES` besides the school's in the words before
    ``end`` from ``start`` on (see :func:`_another_subject`)."""
    found = words(text, start, end)
    for index, word in enumerate(found):
        scope = SCOPES.get(word)
        if scope is None and index + 1 < len(found):
            scope = SCOPES.get(f"{word} {found[index + 1]}")
        if scope is not None and scope != "school":
            return scope
    return None


def _other_day_length(text: str, start: int, end: int, minutes: int) -> bool:
    """Whether another day is given a length of its own, unlike ``minutes``, in the span."""
    for match in _DAY_LENGTH.finditer(text, start, end):
        found = _minutes(match.group("after") or match.group("before"))
        if found is not None and found != minutes:
            return True
    return False


def _withdraw_length(mention: Mention, text: str, end: int) -> None:
    """Withdraw the length of a status whose days have lengths of their own before ``end``."""
    if mention.kind == "delayed":
        if mention.delay is not None and _other_day_length(text, mention.end, end, mention.delay):
            mention.delay = None
    elif mention.early is not None and _other_day_length(text, mention.end, end, mention.early):
        mention.early = None


def length_after(text: str, start: int) -> bool:
    """Whether a length can be stated in ``text`` after ``start`` (a quick check)."""
    return (
        text.find("hour", start) >= 0
        or text.find("hr", start) >= 0
        or text.find("min", start) >= 0
        or _SHORT_UNIT.search(text, start) is not None
    )


def harvest_details(mention: Mention, text: str, end: int) -> None:
    """Fill in, or withdraw, a time or length stated after ``mention`` but before ``end``.

    "Early dismissal today at 1:00" and "delayed opening Tuesday at 10" put a
    date between the status and its time. "Early release: 11:30 elementary,
    12:15 secondary" gives two times, so the mention keeps none: which one
    applies depends on the school. "Delayed 2 hours Thursday and 3 hours
    Friday" gives each day a length of its own, so the mention, which holds
    both days, keeps none.
    """
    _withdraw_length(mention, text, end)
    if mention.kind == "early_dismissal":
        own, found = _clocks_found(text, mention.end, end)
        times = {_dismissal(clock) for clock in own} - {None}
        if mention.dismissal is not None:
            times.add(mention.dismissal)
        if len(times) > 1 or (times and _times_by_level(text, mention.end, end, found)):
            mention.dismissal = None
        elif mention.dismissal is None and mention.early is None and times:
            mention.dismissal = times.pop()
        length = (
            _HARVEST_EARLY.search(text, mention.end, end)
            if text.find("early", mention.end, end) >= 0
            else None
        )
        if length is not None and mention.early is None and mention.dismissal is None:
            mention.early = _minutes(length.group("dur"))
    elif mention.kind == "delayed":
        own, found = _clocks_found(text, mention.end, end)
        times = {_opening(clock) for clock in own} - {None}
        if mention.opens_at is not None:
            times.add(mention.opens_at)
        if len(times) > 1 or (times and _times_by_level(text, mention.end, end, found)):
            mention.opens_at = None
        elif mention.opens_at is None and mention.delay is None and times:
            mention.opens_at = times.pop()
