"""Dates in status text, and the local calendar they resolve against.

Finding and resolving are separate steps. :func:`find_date_groups` reads the
normalized text alone and returns :class:`DateGroup` spans ("today and
tomorrow", "Monday-Wednesday", "Tues., Jan. 21", "through Friday"). A
:class:`Calendar`, built from the posting time and the school's time zone, turns
a group into local dates:

* ``today`` is the posting date in the school's zone; ``tomorrow`` the day after.
  An evening ("tonight", "tomorrow night", "Tuesday evening") is after the
  school day, so a status for it is not a status for that day.
  A post between midnight and 4 a.m. was written the evening before (or first
  seen after midnight), so its ``tomorrow`` is the day that has just begun,
  unless a weekday or a date beside it names the day after.
* A weekday name is its next occurrence counting the posting day ("Monday"
  posted Monday evening is that Monday). Overnight posts also reach back one
  day. ``next Monday`` skips the posting day.
* A month and day without a year takes the year that puts it closest to the
  posting date. A day of the month alone ("the 27th", "on the 22nd", "through
  the 30th", "until 27th") is the first date with that number on or after the
  posting day, at most 30 days on: posted on January 30, "through the 2nd"
  runs to February 2. A number that fell in the week before the posting day
  is that past day ("closed through the 22nd" still listed on the 23rd ran
  out yesterday, and does not run for another month). With no such date ("the
  31st" posted on April 10) the day is invalid. The number must stand clear:
  "the 2nd shift", "the 3rd grade" and "the 22 buses" name no day. A weekday
  written with a date, or a day number written with a weekday or "tomorrow"
  ("Wednesday the 21st"), is a check: when the two disagree the date or day
  number is kept and the group is marked as a mismatch (which the parser
  reads as no day it can trust). A weekday with a day
  number names the date with that number on that weekday, even when it is not
  the weekday's next occurrence: "Wednesday the 28th" posted on Tuesday,
  January 20 is January 28.
* Weekday names listed or ranged together are one run of days: the run that
  includes or follows the posting day ("Monday and Tuesday" or
  "Monday-Wednesday" posted on a Tuesday started yesterday; "next Monday and
  Tuesday" starts next week). Ranges ("through Friday", "rest of the week") keep
  school days only, skipping Saturdays and Sundays; ``until`` excludes its end
  day. "Rest of the week" ends on the posting week's Friday; posted after that,
  it states no day. A range longer than about three months is kept to its
  first day and marked invalid.
* A run that ends on a date runs up to that date: "Wednesday through January
  28" (a Wednesday) is eight days, "Monday through Friday, January 30" the week
  ending on the 30th.
* Weekday names across one text keep the text's order: "Closed Monday; NTI
  Tuesday" posted on a Tuesday is yesterday and today, not next Monday (the
  parser counts a closings page's day headings among them, and reads weekday
  names that were a day or two ago as no day at all: see
  :mod:`snowlight.classify.parse`). Days in
  one list or range that run backward ("tomorrow and Jan. 19", "Jan. 23 through
  Jan. 21", "tomorrow until Wednesday" posted on a Tuesday) are marked unclear.
* Two kinds of day written side by side name the same days: "tomorrow
  (Thursday)", "tomorrow, Jan. 22", "Wednesday and Thursday, January 21-22".
  When they agree the group is those days. When they disagree the group is the
  most explicit one's days (a date over a weekday over "today" or "tomorrow")
  and is marked as a mismatch; with no date or day number among them
  ("tomorrow (Friday)") it is also marked unsettled, and names no day at all.
* A weekday named twice in one text ("Monday: Closed Monday") is one day.
* A status that names no day applies to the next school day at or after the
  posting time, when that day is the posting day or the day after (see
  :mod:`snowlight.classify.parse` for the cut-offs).

:func:`find_unreadable` finds day-like words the patterns here cannot read
("Weds" is read, but "1-21", "next week", "day after tomorrow", "last Monday", "3 days",
"2 weeks", "Presidents Day", a day number that does not stand clear ("the 21st everyone"),
a day letter alone after a status or heading a slot ("Closed W", "W: Closed"), Spanish
day names ("mañana", "miércoles") and misspelled day names, joined to another word or not
("Closed-Wendsday"), are not): a listing with one of them states no day the parser can
trust.
"""

import re
from collections.abc import Callable, Iterable, Sequence
from datetime import date, datetime, timedelta
from functools import lru_cache, reduce
from itertools import pairwise
from operator import or_
from typing import Final, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from rapidfuzz.distance import OSA

from snowlight.classify.lexicon import MODIFIERS, SCOPES
from snowlight.classify.text import DATE_START_SHIFT, Pieces, by_char, scan, starts, trie, words

type AtomKind = Literal["explicit", "weekday", "relative", "week", "further_notice", "recurring"]
type Link = Literal["list", "range", "until", "appos", "first", "lead"]
"""How two date atoms are joined. ``first`` is a range of which only the first day is
meant: the parser joins a run with it when the days after the first state nothing
(see :func:`snowlight.classify.parse._first_of_run`). The run's end still places the
day before it, as a range's does; as a group's ``open_start``, only the day the run
starts on is meant. ``appos`` joins two kinds of day that name the same days. ``lead``
is a plain comma after a relative day, before the first of a list of weekday names ("today,
Thursday and Friday"): ``appos``, unless the days make a run (see
:meth:`Calendar._led_run`)."""

WEEKDAYS: dict[str, int] = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tues": 1,
    "tue": 1,
    "wednesday": 2,
    "weds": 2,
    "wed": 2,
    "thursday": 3,
    "thurs": 3,
    "thur": 3,
    "thu": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}
MONTHS: dict[str, int] = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sept": 9,
    "sep": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}
# Spellings of today, tomorrow and yesterday that are read as those days.
_TODAY_WORDS = ("today", "tonight", "tonite", "2nite", "2night")
_TOMORROW_WORDS = (
    "tomorrow", "tmrw", "tmw", "tmr", "tmrrw", "tomorow", "tommorow", "tommorrow", "tomorro",
    "tomoro", "tomm", "tomarrow", "tommrow", "2morrow", "2morow", "2moro", "2mrw", "2mrrw",
)  # fmt: skip
_YESTERDAY_WORDS = ("yesterday",)
SCHOOL_DAY_WORDS: tuple[str, ...] = ("today", *_TOMORROW_WORDS)
"""The spellings of today and tomorrow read as a school day (not "tonight")."""
_RELATIVE_TODAY = frozenset(_TODAY_WORDS)
_EVENING_WORDS = frozenset(_TODAY_WORDS[1:])
_RELATIVE_TOMORROW = frozenset(_TOMORROW_WORDS)

# Name lists as character tries (see :func:`snowlight.classify.text.trie`), longest match first.
_WD_ANY = trie(WEEKDAYS)
# Standalone weekday words. "sat" and "sun" are left out: alone they are ordinary words.
_WD_SOLO = trie(name for name in WEEKDAYS if name not in {"sat", "sun"})
_MONTH = trie(MONTHS)
# After a day number, "may" is the verb ("grades 6-8 may be dismissed"), never the month.
_MONTH_AFTER_DAY = trie(name for name in MONTHS if name != "may")
_RELATIVE = trie(_TODAY_WORDS + _TOMORROW_WORDS + _YESTERDAY_WORDS)
# A half after a number makes it part of a length too: "2 1/2 hours", "two and a half hours".
_HALF_AFTER = r"(?:\s*-?\s*1/2|(?:\s*-\s*|\s+)and(?:\s*-\s*|\s+)(?:a|one)(?:\s*-\s*|\s+)half)?"
_NOT_A_LENGTH = rf"(?!{_HALF_AFTER}\s*-?\s*(?:hours?|hrs?|h|minutes?|mins?|am|pm)\b)"
_ORDINAL = r"(?:st|nd|rd|th)"
# A day number checking a weekday or a relative day: "Wednesday the 21st", "tomorrow 21st".
_DAY_CHECK = (
    rf"(?:\s*,?\s*(?:the\s+(?P<{{0}}_day>\d{{{{1,2}}}}){_ORDINAL}?|(?P<{{0}}_day2>\d{{{{1,2}}}}){{1}})"
    rf"\b(?![-:/.]?\d)(?!{_HALF_AFTER}\s*-?\s*(?:hours?|hrs?|h|minutes?|mins?|m|am|pm|a|p|days?"
    r"|weeks?|months?|mos?|years?|yrs?|noon|midnight|o'?clock|grades?|graders?|schools?|students?"
    r"|buildings?|campus(?:es)?|locations?|sites?|buses|busses|routes?|employees?|staff"
    r"|teachers?|classes|districts?)\b))?"
)
# A day of the month alone: "the 27th", "the 22", "27th". A number with no ordinal needs
# "the": "until 10" is a time. A month after it makes it a day-and-month date ("the 22nd of
# January"), which the "dm" form reads.
_DAY_NUMBER = r"(?:0?[1-9]|[12]\d|3[01])"
_BARE_DAY_NUMBER = (
    rf"(?:\bthe\s+(?P<dn_day>{_DAY_NUMBER}){_ORDINAL}?|(?<![\d/.:-])\b(?P<dn_day2>{_DAY_NUMBER})"
    rf"{_ORDINAL})\b(?![:/.]?\d){_NOT_A_LENGTH}(?!(?:\s*-\s*|\s+of\s+|\s*)(?:{_MONTH_AFTER_DAY})\b)"
)
# What a day of the month alone must be followed by, after any day numbers that continue it
# ("the 22nd and 23rd"): the end, a mark, or a word that joins days, gives a cause or goes on
# to say more ("until the 22nd when school reopens"). Any other word can be what the number
# counts or ranks ("the 2nd shift", "the 22 buses"): a number so followed is no day (see
# find_unreadable).
_DAY_NUMBER_FOLLOWS = re.compile(
    r"\s*(?:$|[,;.!?:/|)]|-(?![a-z])|(?:and|or|through|thru|to|until|till|til|due|because"
    rf"|owing|for|also|only|as|but|so|plus|when|at|with|{_WD_ANY})\b)",
    re.ASCII,
).match
# The kinds of date atom, in the order they are tried: each with the characters it can start
# at, and its pattern (see _ATOM).
_WEEKDAY_FIRST = frozenset(name[0] for name in WEEKDAYS)
_DIGITS = frozenset("0123456789")
_ATOM_BRANCHES: tuple[tuple[frozenset[str], str], ...] = (
    (
        _WEEKDAY_FIRST | {name[0] for name in MONTHS},
        # ("may" before a date in figures is the verb: "Closed may 1/22 and 1/23".)
        rf"""(?P<md>(?:\b(?P<md_wd>{_WD_ANY})\s*,?\s*)?\b(?P<md_mon>(?P<md_may>may\b)|{_MONTH_AFTER_DAY})
        (?:\s*-\s*|\s*)(?P<md_day>\d{{1,2}}){_ORDINAL}?\b{_NOT_A_LENGTH}(?!:\d)(?(md_may)(?![/.]\d))
        (?:\s*,?\s*(?P<md_year>20\d\d)\b)?)""",
    ),
    (
        _WEEKDAY_FIRST | _DIGITS,
        rf"""(?P<num>(?:\b(?P<num_wd>{_WD_ANY})\s*,?\s*)?(?<![\d/.])(?P<num_m>\d{{1,2}})/(?P<num_d>\d{{1,2}})
        (?:/(?P<num_y>\d{{4}}|\d{{2}}))?(?![\d/])(?!\s*-?\s*(?:day|days|hour|hours|hr|hrs|h)\b))""",
    ),
    (
        _WEEKDAY_FIRST | _DIGITS,
        rf"""(?P<mdy>(?:\b(?P<mdy_wd>{_WD_ANY})\s*,?\s*)?(?<![\d/.-])(?P<mdy_m>\d{{1,2}})(?P<mdy_sep>[-.])
        (?P<mdy_d>\d{{1,2}})(?P=mdy_sep)(?P<mdy_y>20\d\d|\d\d)(?![\d./-]))""",
    ),
    (frozenset("2"), r"(?P<iso>\b(?P<iso_y>20\d\d)-(?P<iso_m>\d\d)-(?P<iso_d>\d\d)\b)"),
    (
        _WEEKDAY_FIRST | _DIGITS,
        rf"""(?P<dm>(?:\b(?P<dm_wd>{_WD_ANY})\s*,?\s*(?:the\s+)?)?(?<![\d/.:-])\b(?P<dm_day>\d{{1,2}})
        {_ORDINAL}?(?:\s*-\s*|\s+of\s+|\s*)(?P<dm_mon>{_MONTH_AFTER_DAY})\b
        (?:\s*,?\s*(?P<dm_year>20\d\d)\b)?)""",
    ),
    (
        frozenset(word[0] for word in _TODAY_WORDS + _TOMORROW_WORDS + _YESTERDAY_WORDS) | {"t"},
        rf"""(?P<rel>\b(?P<rel_word>{_RELATIVE})\b(?:'s)?(?:\s+(?P<rel_eve>night|nite|evening)\b)?
        {_DAY_CHECK.format("rel", _ORDINAL)}
        |\bthis\s+(?P<rel_part>morning|afternoon|evening)\b)""",
    ),
    (
        frozenset("trbae"),
        r"""(?P<week>\b(?:the\s+)?(?P<rest>rest|remainder|balance)\s+of\s+(?:the\s+|this\s+)?week\b
        |\b(?:all|this|the\s+entire|the\s+whole|entire)\s+week\b)""",
    ),
    (frozenset("t") | _DIGITS, rf"(?P<dn>{_BARE_DAY_NUMBER})"),
    (frozenset("ui"), r"(?P<ufn>\buntil\s+further\s+notice\b|\bindefinitely\b)"),
    (
        frozenset("emtwfs"),
        rf"(?P<rec>\bevery\s+(?:{_WD_SOLO})\b|\b(?:mon|tues|wednes|thurs|fri|satur|sun)days\b)",
    ),
    (
        frozenset("ntc") | _WEEKDAY_FIRST,
        rf"""(?P<wd>\b(?:(?P<wd_mod>next|this\s+coming|this|coming)\s+)?(?P<wd_name>{_WD_SOLO})\b(?:'s)?
        (?:\s+(?P<wd_eve>night|nite|evening)\b)?{_DAY_CHECK.format("wd", _ORDINAL + "?")})""",
    ),
)
_ATOM = re.compile("|".join(branch for _first, branch in _ATOM_BRANCHES), re.VERBOSE | re.ASCII)
"""A date atom: the first of the branches above that matches."""


def _atom_matcher(branches: Iterable[str]) -> Callable[[str, int], re.Match[str] | None]:
    pattern = "|".join(branches)
    return re.compile(pattern or r"(?!)", re.VERBOSE | re.ASCII).match


# By the character a date atom starts with: _ATOM less the branches that cannot start there,
# which the regex engine would try and reject. A branch left out cannot match, and the first
# of the rest that matches is the one _ATOM finds, with the same named groups.
_ATOM_BY_FIRST: dict[str, Callable[[str, int], re.Match[str] | None]] = {
    char: _atom_matcher(branch for chars, branch in _ATOM_BRANCHES if char in chars)
    for char in "abcdefghijklmnopqrstuvwxyz0123456789"
}
# A weekday name with no date after it ("Monday due to snow", not "Monday, Jan. 26" or
# "Monday the 26th") can only be a weekday: every other branch that can start at a weekday
# name needs a month, a digit or "the" after it, past spaces and a comma.
_WEEKDAY_ONLY = _atom_matcher([_ATOM_BRANCHES[-1][1]])
# What those branches need after the weekday name, past spaces and a comma: a digit, "the"
# and a digit, or a month name and a digit.
_DATE_AFTER = re.compile(rf"\s*,?\s*(?:\d|the\s+\d|(?:{_MONTH})(?:\s*-\s*|\s*)\d)", re.ASCII)
# A word for today, tomorrow or yesterday ("tomorrow", "2nite") can only start a relative day:
# every branch before that one needs a weekday name, a month name or a date's digits there.
_RELATIVE_ONLY = _atom_matcher([_ATOM_BRANCHES[5][1]])
_RELATIVE_WORDS = frozenset(_TODAY_WORDS + _TOMORROW_WORDS + _YESTERDAY_WORDS)
_RUN_AT = re.compile(r"[a-z0-9]+", re.ASCII)
# The first characters of the words that take one of the two short cuts above.
_SHORT_CUT_FIRST = _WEEKDAY_FIRST | {word[0] for word in _RELATIVE_WORDS}


def _match_atom(text: str, position: int) -> re.Match[str] | None:
    """:data:`_ATOM` matched at ``position`` (which starts a run of letters and digits)."""
    first = text[position]
    match_at = _ATOM_BY_FIRST.get(first)
    if match_at is None:
        return _ATOM.match(text, position)
    if first in _SHORT_CUT_FIRST:
        run = _RUN_AT.match(text, position)
        if run is not None:
            word = run.group()
            if word in _RELATIVE_WORDS:
                return _RELATIVE_ONLY(text, position)
            if word in WEEKDAYS and _DATE_AFTER.match(text, run.end()) is None:
                return _WEEKDAY_ONLY(text, position)
    return match_at(text, position)


_CONTINUATION = re.compile(
    rf"\s*(?P<link>,\s*and|,|and|-|through|thru|to|until|till)\s*(?P<day>\d{{1,2}}){_ORDINAL}?\b"
    rf"(?!:\d|[/\d]){_NOT_A_LENGTH}",
    re.ASCII,
)
# The words that can join two date atoms, with spaces folded and none around commas.
_LIST_GAPS = frozenset({"", ",", "and", ",and", "/", "as well as", "plus", "also"})
# A comma may come before the range word: "Wednesday, through Friday".
_RANGE_GAPS = frozenset(
    {"-", "through", "thru", "to", "and through", ",through", ",thru", ",and through"}
)
_UNTIL_GAPS = frozenset({"until", "till", "til", ",until", ",till", ",til"})
# Joins that, between two kinds of day, restate rather than add: "tomorrow (Thursday)".
_APPOSITION_GAPS = frozenset({"", ",", "/", ":", "-"})
# The longest join, with its spaces taken out, and a length a gap longer than it with single
# spaces can reach (a gap no longer than that is read in full; see _link).
_LONGEST_GAP = max(
    len(gap.replace(" ", "")) for gap in _LIST_GAPS | _RANGE_GAPS | _UNTIL_GAPS | _APPOSITION_GAPS
)
_LONGEST_RAW_GAP = 2 * _LONGEST_GAP + 2
_OPEN_START = re.compile(
    r"(?:\b(?P<through>through|thru)|\b(?P<until>until|till|til))\s*$", re.ASCII
)
# The kinds of day that can restate each other, by how explicit they are.
_EXPLICITNESS: dict[AtomKind, int] = {"relative": 0, "weekday": 1, "explicit": 2}

_SATURDAY = 5
_FRIDAY = 4
_WEEK = 7
# A closure after a hurricane or during an epidemic can run for weeks ("closed through October
# 25" posted on October 1, "closed through April 24" in mid-March). A range longer than about
# a quarter of a year is more likely misread than meant: only its first day is kept.
_LONGEST_RANGE_DAYS = 92
_OVERNIGHT_END_MINUTES = 4 * 60
_OPEN_START_CUTOFF = 12 * 60  # an open start posted from noon on counts from the next school day
_TWO_DIGIT_YEAR = 100
_HALF_YEAR = 6
# A day of the month alone ("the 27th") is the first date with that number from the posting
# day on, at most this many days on; one that fell at most _DAY_NUMBER_PAST days before the
# posting day is that past day (see Calendar.day_of_month).
_DAY_NUMBER_AHEAD = 30
_DAY_NUMBER_PAST = 7
_DECEMBER = 12


# One date expression in the normalized text. A plain tuple, read by the field numbers
# below: a named tuple's field is read several times slower, and one is made several times
# slower, and the parser makes and reads date atoms and groups for most texts.
type DateAtom = tuple[
    int,  # ATOM_START
    int,  # ATOM_END
    AtomKind,  # ATOM_KIND
    int | None,  # ATOM_WEEKDAY: weekday atoms: the day; explicit atoms: a weekday to check
    int | None,  # ATOM_MONTH
    int | None,  # ATOM_DAY: explicit atoms: the day; weekday and relative atoms: a day to check
    int | None,  # ATOM_YEAR
    int,  # ATOM_OFFSET: relative atoms: -1 yesterday, 0 today, 1 tomorrow
    str | None,  # ATOM_MODIFIER: weekday atoms: "next", "this", "coming"
    bool,  # ATOM_REST_OF_WEEK
    int | None,  # ATOM_INNER: explicit atoms with a weekday: where the date itself starts
    bool,  # ATOM_NAMED: explicit atoms: the month is written as a name ("Jan. 21")
    bool,  # ATOM_EVENING: "tonight", "Tuesday evening": after the school day
]
ATOM_START: Final = 0
ATOM_END: Final = 1
ATOM_KIND: Final = 2
ATOM_WEEKDAY: Final = 3
ATOM_MONTH: Final = 4
ATOM_DAY: Final = 5
ATOM_YEAR: Final = 6
ATOM_OFFSET: Final = 7
ATOM_MODIFIER: Final = 8
ATOM_REST_OF_WEEK: Final = 9
ATOM_INNER: Final = 10
ATOM_NAMED: Final = 11
ATOM_EVENING: Final = 12
# Date atoms joined by list and range words, with the span they cover; a plain tuple too.
type DateGroup = tuple[
    int,  # GROUP_START
    int,  # GROUP_END
    tuple[DateAtom, ...],  # GROUP_ATOMS
    tuple[Link, ...],  # GROUP_LINKS: links[i] joins atoms[i] and atoms[i + 1]
    Link | None,  # GROUP_OPEN_START: "through Friday" (range) or "until Friday" (until)
]
GROUP_START: Final = 0
GROUP_END: Final = 1
GROUP_ATOMS: Final = 2
GROUP_LINKS: Final = 3
GROUP_OPEN_START: Final = 4


def date_atom(
    start: int,
    end: int,
    kind: AtomKind,
    *,
    weekday: int | None = None,
    day: int | None = None,
) -> DateAtom:
    """A date atom with the fields most atoms leave unset (for the few made by hand)."""
    return (start, end, kind, weekday, None, day, None, 0, None, False, None, False, False)


# What went wrong, or needs saying, resolving a group: bits of :attr:`Resolved.flags`.
FURTHER_NOTICE = 1  # "until further notice"
INVALID = 2  # an impossible date, or a range too long to be one closure
MISMATCH = 4  # two ways of naming the day disagree: no day anyone can trust (see parse)
OVERNIGHT = 8  # "tomorrow" posted after midnight
RECURRING = 16  # "Wednesdays", "every Friday": a standing schedule, not a date
UNCLEAR = 32  # "next Wednesday" posted early in the week: this one or the next
EVENING = 64  # a day's evening ("tonight"), which no school day status is for


class Resolved:
    """The dates a group stands for, with what went wrong resolving it (``flags``)."""

    __slots__ = ("dates", "flags")

    def __init__(self) -> None:
        self.dates: set[date] = set()
        self.flags = 0


def _year(text: str | None) -> int | None:
    if text is None:
        return None
    year = int(text)
    return year + 2000 if year < _TWO_DIGIT_YEAR else year


def _split_weekday(atom: DateAtom) -> tuple[DateAtom, DateAtom]:
    """Split "Friday, Jan. 23" into the weekday name and the date."""
    inner = atom[ATOM_END] if atom[ATOM_INNER] is None else atom[ATOM_INNER]
    named = date_atom(atom[ATOM_START], inner, "weekday", weekday=atom[ATOM_WEEKDAY])
    # (The date from ``inner`` on, with no weekday and no inner start: fields 0, 3 and 10.)
    return named, (inner, atom[1], atom[2], None, *atom[4:10], None, atom[11], atom[12])


# The groups of each explicit form: weekday, month, day, year, where the date starts after a
# weekday, and whether the month is a name.
_EXPLICIT_FORMS: dict[str, tuple[str, str, str, str, str, bool]] = {
    "md": ("md_wd", "md_mon", "md_day", "md_year", "md_mon", True),
    "dm": ("dm_wd", "dm_mon", "dm_day", "dm_year", "dm_day", True),
    "num": ("num_wd", "num_m", "num_d", "num_y", "num_m", False),
    "mdy": ("mdy_wd", "mdy_m", "mdy_d", "mdy_y", "mdy_m", False),
}


_new = tuple.__new__  # builds a named tuple from its fields without a Python-level call
_EXPLICIT_TAIL = (0, None, False, None, False, False)  # a DateAtom's fields after ``year``
_REL_GROUPS = ("rel_word", "rel_eve", "rel_part", "rel_day", "rel_day2")
_WD_GROUPS = ("wd_mod", "wd_name", "wd_eve", "wd_day", "wd_day2")


def _atom(match: re.Match[str]) -> DateAtom:  # noqa: PLR0911 - one return per atom kind
    start, end = match.span()
    kind = match.lastgroup or ""
    form = _EXPLICIT_FORMS.get(kind)
    if form is not None:
        wd_group, month_group, day_group, year_group, date_group, named = form
        wd, month, day, year = match.group(wd_group, month_group, day_group, year_group)
        return (
            start,
            end,
            "explicit",
            None if wd is None else WEEKDAYS[wd],
            MONTHS[month] if named else int(month),
            int(day),
            None if year is None else _year(year),
            0,
            None,
            False,
            None if wd is None else match.start(date_group),
            named,
            False,
        )
    if kind == "rel":
        word, eve, part, day, day2 = match.group(*_REL_GROUPS)
        if word is None:  # "this morning", "this evening"
            evening = part == "evening"
            return (
                start,
                end,
                "relative",
                None,
                None,
                None,
                None,
                0,
                None,
                False,
                None,
                False,
                evening,
            )
        offset = 0 if word in _RELATIVE_TODAY else 1 if word in _RELATIVE_TOMORROW else -1
        evening = word in _EVENING_WORDS or eve is not None
        number = day or day2
        checked = None if number is None else int(number)
        return (
            start,
            end,
            "relative",
            None,
            None,
            checked,
            None,
            offset,
            None,
            False,
            None,
            False,
            evening,
        )
    if kind == "wd":
        modifier, name, eve, day, day2 = match.group(*_WD_GROUPS)
        number = day or day2
        weekday_fields = (
            WEEKDAYS[name],
            None,
            None if number is None else int(number),
            None,
            0,
            None if modifier is None else modifier.split()[-1],
            False,
            None,
            False,
            eve is not None,
        )
        return (start, end, "weekday", *weekday_fields)
    if kind == "dn":  # "the 27th": a day of the month, with no month (see Calendar.explicit)
        number = match.group("dn_day") or match.group("dn_day2")
        return (start, end, "explicit", None, None, int(number), None, *_EXPLICIT_TAIL)
    if kind == "iso":
        year, month, day = match.group("iso_y", "iso_m", "iso_d")
        return (start, end, "explicit", None, int(month), int(day), int(year),
                               0, None, False, None, False, False)  # fmt: skip
    if kind == "week":
        rest_of_week = match.group("rest") is not None
        return (start, end, "week", None, None, None, None, 0, None, rest_of_week,
                               None, False, False)  # fmt: skip
    if kind == "ufn":
        return (start, end, "further_notice", *_BARE_TAIL)
    return (start, end, "recurring", *_BARE_TAIL)


# The fields of an atom of a kind that holds no day, after its start, end and kind.
_BARE_TAIL = (None, None, None, None, 0, None, False, None, False, False)


def _continuations(text: str, atom: DateAtom) -> list[DateAtom]:
    """Bare day numbers after a date: the 22 and 23 of "Jan. 21, 22 and 23" or "1/21-23".

    A number after a bare comma continues the dates only when it comes later in
    the month: the 10 of "3/15, 10" is some other number. A year after the last
    number is the year of them all ("January 21-23, 2025"): the last one ends
    after it, and the date before them takes it (see :func:`_with_year`).
    """
    found: list[DateAtom] = []
    position = atom[ATOM_END]
    last = atom[ATOM_DAY] or 0
    while (match := _CONTINUATION.match(text, position)) is not None:
        day = int(match.group("day"))
        if day <= last and match.group("link") == ",":
            break
        position, last = match.end(), day
        found.append(
            (
                match.start("day"),
                position,
                "explicit",
                None,
                atom[ATOM_MONTH],
                day,
                atom[ATOM_YEAR],
                *_EXPLICIT_TAIL,
            )
        )
    if found and atom[ATOM_YEAR] is None:
        year = _YEAR_AFTER(text, position)
        if year is not None:
            value = int(year.group(1))
            found = [_with_year(continued, value) for continued in found]
            found[-1] = (found[-1][ATOM_START], year.end(), *found[-1][ATOM_KIND:])
    return found


# A year after the day numbers that continue a date: the ", 2025" of "January 21-23, 2025".
_YEAR_AFTER = re.compile(r"\s*,?\s*(20\d\d)\b(?![/.:-]?\d)", re.ASCII).match


def _with_year(atom: DateAtom, year: int) -> DateAtom:
    """``atom`` with its year: the year a run of day numbers after it ends with."""
    return (*atom[:ATOM_YEAR], year, *atom[ATOM_OFFSET:])


def restates(left: DateAtom, right: DateAtom) -> bool:
    """Whether two atoms are different kinds of day, which side by side name the same days."""
    left_kind, right_kind = left[2], right[2]  # (an atom's kind is its third field)
    return left_kind != right_kind and left_kind in _EXPLICITNESS and right_kind in _EXPLICITNESS


def _link(text: str, left: DateAtom, right: DateAtom) -> Link | None:  # noqa: PLR0911
    raw = text[left[ATOM_END] : right[ATOM_START]]
    # (A gap with no whitespace but spaces, as in a normalized text, is as long without its
    # spaces as its length less their count.)
    if (
        len(raw) > _LONGEST_RAW_GAP
        and len(raw) - raw.count(" ") > _LONGEST_GAP
        and (raw.isprintable() or len("".join(raw.split())) > _LONGEST_GAP)
    ):
        return None  # more words between them than any join has
    gap = " ".join(raw.split()).replace(" ,", ",").replace(", ", ",")
    if restates(left, right) and gap in _APPOSITION_GAPS:
        # A spaced dash beside "today" or "tomorrow" separates clauses ("Closed today -
        # Wednesday: 2 hour delay"); a clause of bare dates after it is handled there.
        if gap == "-" and "relative" in (left[ATOM_KIND], right[ATOM_KIND]) and raw.strip() != raw:
            return None
        return "appos"
    if gap in _LIST_GAPS:
        return "list"
    if left[ATOM_KIND] == "further_notice":
        # "Until further notice, through Jan. 30": no range starts at "further notice", so
        # the date after it is a group of its own, counted from the posting day.
        return None
    if gap in _UNTIL_GAPS:
        return "until"
    if gap in _RANGE_GAPS:
        # A bare hyphen between "today" and "tomorrow" is punctuation, not a range.
        if gap == "-" and "relative" in (left[ATOM_KIND], right[ATOM_KIND]):
            return None
        return "range"
    return None


# Every date atom starts with a digit or one of these words (or their first letters).
_DATE_STARTS = starts(
    [str(digit) for digit in range(10)]
    + list(WEEKDAYS)
    + list(MONTHS)
    + ["tod", "ton", "tom", "tmr", "tmw", "yesterday", "this", "next", "coming", "the"]
    + ["rest", "remainder", "balance", "all", "entire", "until", "indefinitely", "every"]
)
# Where a date atom can start, looking ahead as far as needed to rule out the numbers and
# words that start none ("2 hour", "the storm", "all activities"). Every position where
# :data:`_ATOM` matches is one of these, so scanning only these finds the same atoms.
_DATE_CANDIDATES = re.compile(
    r"\b(?:"
    + trie(
        list(WEEKDAYS)
        + list(MONTHS)
        + ["tod", "ton", "tom", "tmr", "tmw", "2n", "2m", "yesterday", "next", "coming"]
        + ["rest", "remainder", "balance", "entire", "indefinitely", "every"]
    )
    + r"|this\b|the(?=\s+(?:(?:rest|remainder|balance|entire|whole)\b|\d))|all(?=\s+week)"
    + r"|until(?=\s+further)"
    + rf"|\d{{1,2}}(?=[/.-]\d|{_ORDINAL}?(?:\s*-\s*|\s+of\s+|\s*)(?:{_MONTH_AFTER_DAY})\b)"
    + rf"|\d{{1,2}}{_ORDINAL}\b"
    + r"|20\d\d(?=-\d))",
    re.ASCII,
)
# The same test for a run that only may start a date (see start_hint): "the", "all", "until"
# or a run that opens with a digit. Only one branch of the pattern above can match at each,
# so each is tried alone, by the run's first character.
_DIGIT_CANDIDATE = re.compile(
    rf"2n|2m|\d{{1,2}}(?=[/.-]\d|{_ORDINAL}?(?:\s*-\s*|\s+of\s+|\s*)(?:{_MONTH_AFTER_DAY})\b)"
    rf"|\d{{1,2}}{_ORDINAL}\b|20\d\d(?=-\d)",
    re.ASCII,
).match
_MAYBE_CANDIDATES: dict[str, Callable[[str, int], re.Match[str] | None]] = {
    "t": re.compile(r"the(?=\s+(?:(?:rest|remainder|balance|entire|whole)\b|\d))", re.ASCII).match,
    "a": re.compile(r"all(?=\s+week)", re.ASCII).match,
    "u": re.compile(r"until(?=\s+further)", re.ASCII).match,
    **dict.fromkeys("0123456789", _DIGIT_CANDIDATE),
}


# Runs that start a date candidate (see find_date_groups): a run that begins with one of
# these surely does; a run that is "the", "all" or "until", or begins with a digit, may.
_SURE_STARTS = (
    *WEEKDAYS, *MONTHS, "tod", "ton", "tom", "tmr", "tmw", "yesterday", "next", "coming", "rest",
    "remainder", "balance", "entire", "indefinitely", "every",
)  # fmt: skip
_SURE_BY_FIRST: dict[str, tuple[str, ...]] = {
    first: tuple(word for word in _SURE_STARTS if word[0] == first)
    for first in {word[0] for word in _SURE_STARTS}
}
_MAYBE_WHOLE = frozenset({"the", "all", "until"})
SURE_STARTS = _SURE_STARTS
"""The prefixes of the runs that surely start a date candidate (see :func:`start_hint`)."""
DATE_STARTS = _DATE_STARTS
"""Any word that can start a date expression, from its start (see :func:`word_hints`)."""
DATE_SURE = 1 << DATE_START_SHIFT
"""A run's start-mask bit: a date candidate starts at the run."""
DATE_MAYBE = 2 << DATE_START_SHIFT
"""A run's start-mask bit: a date candidate may start at the run."""
DATE_START_BITS = DATE_SURE | DATE_MAYBE

# A weekday name or a word for today, tomorrow or yesterday is a whole date atom by itself
# unless what follows it adds to it: a date or a day number ("Monday, Jan. 26", "Monday the
# 26th"), an evening ("Monday night") or a possessive "'s". Such a run carries, above the
# other start-mask bits, the number of its entry in _PLAIN_ATOMS, and find_date_groups builds
# its atom without the regex engine when nothing after it could add to it.
_PLAIN_SHIFT = 40
_PLAIN_MASK = 63
_PLAIN_WEEKDAYS = tuple(name for name in WEEKDAYS if name not in {"sat", "sun"})
_PLAIN_RELATIVE = tuple(
    word for word in (*_TODAY_WORDS, *_TOMORROW_WORDS, *_YESTERDAY_WORDS) if word[0] != "2"
)
# (length, kind, weekday, offset, evening) of each plain atom, numbered from 1.
_PLAIN_ATOMS: tuple[tuple[int, AtomKind, int | None, int, bool], ...] = (
    (0, "weekday", None, 0, False),
    *((len(name), "weekday", WEEKDAYS[name], 0, False) for name in _PLAIN_WEEKDAYS),
    *(
        (
            len(word),
            "relative",
            None,
            0 if word in _RELATIVE_TODAY else 1 if word in _RELATIVE_TOMORROW else -1,
            word in _EVENING_WORDS,
        )
        for word in _PLAIN_RELATIVE
    ),
)
_PLAIN_CODES: dict[str, int] = {
    word: code for code, word in enumerate((*_PLAIN_WEEKDAYS, *_PLAIN_RELATIVE), start=1)
}
# What, after spaces and a comma, can add to a plain atom (or start a date that holds it):
# a digit, "the" (a day number), a month name, or an evening.
_ADDS_TO_PLAIN = ("the", "night", "nite", "evening", *{name[:3] for name in MONTHS})
# The same test as one pattern, at the atom's end: a possessive "'s", or past spaces and a
# comma, a digit or a word that starts with one of _ADDS_TO_PLAIN. (A normalized text has no
# two spaces in a row.)
_ADDS_AFTER_PLAIN = re.compile(
    r"'| *(?:, *)?(?:[0-9]|" + trie(sorted(_ADDS_TO_PLAIN)) + ")", re.ASCII
).match
# What the pattern can match with, right at the atom's end: an apostrophe, a comma, a digit
# or a letter (a word of _ADDS_TO_PLAIN). After a space, it can only match with another space,
# a comma, a digit or a word of _ADDS_TO_PLAIN.
_ADDS_AT = frozenset("',0123456789abcdefghijklmnopqrstuvwxyz")
_SPACED_ADDS = (
    "  ",
    " ,",
    *(" " + digit for digit in "0123456789"),
    *(" " + word for word in _ADDS_TO_PLAIN),
)
_SPACED_ADDS_BY_SECOND = by_char(_SPACED_ADDS, 1)  # (by the character after the space)
# Each plain atom's fields after its start and end (see _PLAIN_ATOMS), with its length.
type _Tail = tuple[
    AtomKind, int | None, int | None, int | None, int | None, int, str | None, bool, int | None,
    bool, bool,
]  # fmt: skip
_PLAIN_TAILS: tuple[tuple[int, _Tail], ...] = tuple(
    (length, (kind, weekday, None, None, None, offset, None, False, None, False, evening))
    for length, kind, weekday, offset, evening in _PLAIN_ATOMS
)


@lru_cache(maxsize=65536)
def start_hint(run: str) -> int:
    """Whether a date candidate starts at a run of letters and digits: start-mask bits.

    A run that is a weekday name or a word for a nearby day also carries the
    number of its entry in :data:`_PLAIN_ATOMS` (see :func:`_plain_atom`).
    """
    if run == "this" or run.startswith(_SURE_BY_FIRST.get(run[:1], ())):
        return DATE_SURE | _PLAIN_CODES.get(run, 0) << _PLAIN_SHIFT
    if run in _MAYBE_WHOLE:
        return DATE_MAYBE
    if run[:1].isdigit():
        # A run of digits starts a date only in its first two ("1/21", "21 January") or as
        # a year before a hyphen ("2026-01-21"): three or more digits start none.
        return DATE_MAYBE if len(run) <= 2 or not run.isdigit() or run.startswith("20") else 0  # noqa: PLR2004
    return 0


def _plain_atom(text: str, start: int, code: int) -> DateAtom | None:
    """The atom of a weekday name or a nearby day's word at ``start``, when it stands alone.

    ``None`` when what follows could add to it (see :data:`_ADDS_TO_PLAIN`); the
    date patterns then read it. Otherwise this is the atom they would read.
    """
    length, tail = _PLAIN_TAILS[code]
    end = start + length
    # (What can add to it starts at once, or after a space with one of _SPACED_ADDS: a mark
    # or the text's end right after the word adds nothing, and needs no pattern.)
    after = text[end : end + 1]
    if (
        after in _ADDS_AT
        or (
            after == " "
            and text.startswith(_SPACED_ADDS_BY_SECOND.get(text[end + 1 : end + 2], ()), end)
        )
    ) and _ADDS_AFTER_PLAIN(text, end) is not None:
        return None  # "Monday's", "Monday, Jan. 26", "Monday the 26th", "Monday night"
    return (start, end, *tail)


def _match_plain(text: str, start: int, code: int) -> re.Match[str] | None:
    """:func:`_match_atom` at a plain atom's word (see :data:`_PLAIN_ATOMS`) that something
    after it can add to ("Monday evening", "tomorrow night"), its word known by its ``code``.

    Its run of letters and digits is the word, so the short cuts of :func:`_match_atom` are
    taken as there, with no look at the run.
    """
    length, tail = _PLAIN_TAILS[code]
    if tail[0] == "relative":
        return _RELATIVE_ONLY(text, start)  # (a word of _RELATIVE_WORDS)
    end = start + length
    # (A weekday name with no date after it: an evening after it is none, the most common.)
    if text.startswith(_EVENING_AFTER, end) or _DATE_AFTER.match(text, end) is None:
        return _WEEKDAY_ONLY(text, start)
    return _ATOM_BY_FIRST[text[start]](text, start)


# The evenings after a weekday name that _DATE_AFTER reads as no date: "Monday evening".
_EVENING_AFTER = (" evening", " night", " nite")


def find_date_groups(
    text: str,
    vocabulary: Iterable[str] | None = None,
    *,
    possible: bool = True,
    runs: Pieces | None = None,
) -> tuple[DateGroup, ...]:
    """Return the date groups in normalized ``text``, in order.

    A text none of whose words can start a date (``vocabulary`` is the set of
    its words; ``possible`` is false when the caller already knows none can)
    is not scanned. ``runs``, when the caller has it, lists where the runs of
    letters and digits that can start a date start in the text, in order, with
    their start-mask bits (see :func:`start_hint`), by the stretch that holds
    them (see :data:`~snowlight.classify.text.Pieces`): then only those runs
    are tried, which finds the dates a scan of the whole text finds.
    """
    if not possible or (
        vocabulary is not None and not any(word_hints(word) & DATE_START for word in vocabulary)
    ):
        return ()
    if runs is None:
        places = [(candidate.start(), DATE_SURE) for candidate in _DATE_CANDIDATES.finditer(text)]
    else:
        places = [(base + offset, mask) for base, found in runs for offset, mask in found]
    return date_groups_at(text, places)


def date_groups_at(  # noqa: PLR0912, PLR0915 - one scan, then the joins between atoms
    text: str, runs: Sequence[tuple[int, int]]
) -> tuple[DateGroup, ...]:
    """:func:`find_date_groups` of a text whose ``runs`` the caller has (see there), one by
    one: each as where it starts in the text and its start mask."""
    found: list[DateAtom] = []
    end = 0
    # (The atoms come in order and apart, each read from a run after the one before it ends,
    # but for the day numbers that continue a date: runs after it can start inside them.)
    ordered = True
    candidate_at = _DATE_CANDIDATES.match
    for start, mask in runs:
        if start < end:
            continue  # inside a date found already ("21" of "Jan. 21")
        plain = mask >> _PLAIN_SHIFT & _PLAIN_MASK
        if plain:
            atom = _plain_atom(text, start, plain)
            if atom is not None:  # "Monday", "tomorrow": the atom _match_atom would read
                end = atom[1]  # (its end)
                found.append(atom)
                continue
            match = _match_plain(text, start, plain)
        elif (
            not mask & DATE_SURE
            and _MAYBE_CANDIDATES.get(text[start], candidate_at)(text, start) is None
        ):
            continue  # "the", "all" or a number that starts no date ("2 hour", "5:43")
        else:
            match = _match_atom(text, start)
        if match is None:
            continue
        end = match.end()
        atom = _atom(match)
        form = match.lastgroup
        if form == "dn":  # "the 27th": read only when it stands clear ("the 2nd shift" is not)
            continued = _continuations(text, atom)
            last = continued[-1][ATOM_END] if continued else end
            if not _stands_clear(text, start, last):
                end = last
                continue
            found.append(atom)
            if continued:
                found.extend(continued)
                ordered = False
            continue
        found.append(atom)
        if form in _CONTINUED and end < len(text):
            continued = _continuations(text, atom)
            if continued:
                if atom[ATOM_YEAR] is None and continued[-1][ATOM_YEAR] is not None:
                    found[-1] = _with_year(atom, continued[-1][ATOM_YEAR])  # "Jan 21-23, 2025"
                found.extend(continued)
                ordered = False
    # An open start ("through Friday", "until Friday") needs "thr" or "til" before the group.
    opens = "thr" in text or "til" in text
    if len(found) < 2:  # noqa: PLR2004 - one atom or none: nothing to order or join
        return (_group(text, found, [], opens=opens),) if found else ()
    atoms: list[DateAtom] = found
    if not ordered:
        atoms = []
        for atom in sorted(found, key=_atom_order):
            if not atoms or atom[ATOM_START] >= atoms[-1][ATOM_END]:
                atoms.append(atom)
    if "this week" in text:
        atoms = _this_week(text, atoms)
        if not atoms:
            return ()
    groups: list[DateGroup] = []
    current = [atoms[0]]
    links: list[Link] = []
    for atom in atoms[1:]:
        if atom[ATOM_INNER] is not None and _plain_weekday(current[-1]):
            # "Thursday and Friday, Jan. 22-23": the weekday before the date ends a list of
            # weekday names, and the dates restate the whole list.
            named, dated = _split_weekday(atom)
            joined = _link(text, current[-1], named)
            if joined in {"list", "range", "until"}:
                current.extend((named, dated))
                links.extend((joined, "appos"))
                continue
        link = _link(text, current[-1], atom)
        if link == "appos" and not links and _leads_list(text, current[0], atom):
            link = "lead"  # "Closed today, Thursday and Friday": see Calendar._led_run
        elif link is None and links and links[0] == "lead":
            if _ends_led_list(text, current, atom):
                link = "list"  # "No school today, Thursday or Friday": see Calendar._led_run
            elif len(current) == 2:  # noqa: PLR2004 - a pair is no list
                links[0] = "appos"  # "Closed today, Thursday": one day named twice
        if link is None:
            groups.append(_group(text, current, links, opens=opens))
            current, links = [atom], []
        else:
            current.append(atom)
            links.append(link)
    if links and links[0] == "lead" and len(current) == 2:  # noqa: PLR2004 - a pair is no list
        links[0] = "appos"
    groups.append(_group(text, current, links, opens=opens))
    return tuple(groups)


def _this_week(text: str, atoms: list[DateAtom]) -> list[DateAtom]:
    """The atoms with "this week" taken out where it says which week days named beside it are
    in, not a run of days: "Closed Thursday this week", "Thursday and Friday of this week",
    "Friday only this week", "Closed this week: Thursday and Friday". The first weekday name
    it qualifies is this week's (:meth:`Calendar.weekday` with ``"week"``), and those after it
    in its run go on from it."""
    kept = list(atoms)
    index = 0
    while index < len(kept):
        atom = kept[index]
        if atom[ATOM_KIND] != "week" or not text.startswith("this", atom[ATOM_START]):
            index += 1
            continue
        before = kept[index - 1] if index else None
        after = kept[index + 1] if index + 1 < len(kept) else None
        if (
            before is not None
            and before[ATOM_KIND] in _THIS_WEEK_DAYS
            and _this_week_after(text, before, atom)
        ):
            first = index - 1
            while (
                first
                and _plain_weekday(kept[first - 1])
                and len(text[kept[first - 1][ATOM_END] : kept[first][ATOM_START]]) <= _RUN_GAP
            ):
                first -= 1
        elif (
            after is not None
            and after[ATOM_KIND] in _THIS_WEEK_DAYS
            and text[atom[ATOM_END] : after[ATOM_START]].strip() == ":"
        ):
            first = index + 1
        else:
            index += 1
            continue
        del kept[index]
        if first > index:
            first -= 1
        lead = kept[first]
        if _plain_weekday(lead) and lead[ATOM_MODIFIER] is None:
            kept[first] = (*lead[:ATOM_MODIFIER], "week", *lead[ATOM_MODIFIER + 1 :])  # type: ignore[assignment]
    return kept


def _this_week_after(text: str, before: DateAtom, atom: DateAtom) -> bool:
    """Whether "this week" at ``atom`` says which week the day before it is in: right after
    it ("Closed Thursday this week only", "Thursday and Friday of this week"), or after a mark
    when nothing but "only" follows it in its sentence ("Closed Thursday - this week only",
    "Closed Thursday; for this week only", "Closed Thursday / this week only", "Closed
    Thursday. This week."), never a run of days from the day before it."""
    gap = text[before[ATOM_END] : atom[ATOM_START]].strip(" ,")
    return gap in _THIS_WEEK_GAPS or (
        _THIS_WEEK_MARKED(gap) is not None and _THIS_WEEK_END(text, atom[ATOM_END]) is not None
    )


# The kinds of day "this week" can qualify, the words between them, and how far apart two
# weekday names of one run can be ("Thursday and Friday", "Thursday, Friday"). After a mark,
# "this week" qualifies the day before it when it ends its sentence, "only" at most after it.
_THIS_WEEK_DAYS = frozenset({"weekday", "relative", "explicit"})
_THIS_WEEK_GAPS = frozenset({"", "of", "only", "only of", "of the", "only this", "for"})
_THIS_WEEK_MARKED = re.compile(
    r"[-;.|:(\[/\\]+ ?(?:(?:for|only|just)(?: (?:for|only|just))?)?", re.ASCII
).fullmatch
_THIS_WEEK_END = re.compile(r" ?(?:only)? ?[)\]]? ?(?:[.!;|]|$)", re.ASCII).match
_RUN_GAP = 9


_CONTINUED = frozenset({"md", "num"})  # the forms a bare day number can continue: "Jan. 21, 22"
_MOVED_MODIFIERS = frozenset({"next", "week"})  # (the weekday modifiers that move the day)
_OR_GAPS = frozenset({"or", ",or"})


def _leads_list(text: str, first: DateAtom, atom: DateAtom) -> bool:
    """Whether a relative day and a weekday name after it can start a list of days.

    Only a plain comma between them can: "Closed today, Thursday and Friday".
    Any other join names the day again ("today (Thursday)", "today [Thursday]",
    "today/Thursday", "today: Thursday", "today Thursday"), and a list after it
    goes on from the weekday (see :meth:`Calendar._led_run`). (A bracket after
    the relative day is gone from the normalized text, with no comma in its
    place: see :func:`~snowlight.classify.text.normalize`.)
    """
    return (
        first[ATOM_KIND] == "relative"
        and first[ATOM_DAY] is None
        and _plain_weekday(atom)
        and atom[ATOM_MODIFIER] is None
        and text[first[ATOM_END] : atom[ATOM_START]].strip() == ","
    )


def _ends_led_list(text: str, current: list[DateAtom], atom: DateAtom) -> bool:
    """Whether "or" ends a list of weekday names that a relative day leads.

    "No school today, Thursday or Friday" lists its days as "No school today,
    Thursday and Friday" does (see :meth:`Calendar._led_run`); elsewhere "or"
    leaves the days in groups of their own.
    """
    if (
        current[0][ATOM_KIND] != "relative"
        or not _plain_weekday(current[-1])
        or not _plain_weekday(atom)
    ):
        return False
    gap = " ".join(text[current[-1][ATOM_END] : atom[ATOM_START]].split()).replace(", ", ",")
    return gap in _OR_GAPS


def _stands_clear(text: str, start: int, end: int) -> bool:
    """Whether a day of the month alone at ``start``-``end`` names a day ("the 27th").

    A grade nearby makes it a grade ("grades K through the 3rd"), and any word
    after it but one that joins days or gives a cause makes it a count or a
    rank ("the 2nd shift"): see :data:`_DAY_NUMBER_FOLLOWS`.
    """
    if "grade" in text[max(0, start - _GRADE_WINDOW) : end + _GRADE_WINDOW]:
        return False
    return _DAY_NUMBER_FOLLOWS(text, end) is not None


def _atom_order(atom: DateAtom) -> tuple[int, int]:
    return atom[ATOM_START], -atom[ATOM_END]


def _group(text: str, atoms: list[DateAtom], links: list[Link], *, opens: bool) -> DateGroup:
    """The group of ``atoms`` joined by ``links``, with the open start before it, if any.

    ``opens`` is false when the text holds neither "thr" nor "til", which every
    open start does.
    """
    start = atoms[0][0]  # (the first atom's start; atom[1] is an atom's end)
    if opens:
        low = max(0, start - 12)
        lead = (
            _OPEN_START.search(text, low, start)
            if text.find("thr", low, start) >= 0 or text.find("til", low, start) >= 0
            else None
        )
        if lead is not None and text[lead.end() : start].strip() == "":
            start = lead.start()
            return (
                start,
                atoms[-1][1],
                tuple(atoms),
                tuple(links),
                "range" if lead.group("through") else "until",
            )
    return (start, atoms[-1][1], tuple(atoms), tuple(links), None)


def join_groups(first: DateGroup, second: DateGroup, link: Link) -> DateGroup:
    """Return one group that holds ``first`` then ``second``, joined by ``link``.

    Used for a clause of bare dates that restates, or adds to, the dates of a
    status in the clause beside it ("Closed tomorrow. Jan. 22.").
    """
    return (
        first[GROUP_START],
        second[GROUP_END],
        first[GROUP_ATOMS] + second[GROUP_ATOMS],
        (*first[GROUP_LINKS], link, *second[GROUP_LINKS]),
        first[GROUP_OPEN_START],
    )


# Unreadable day words --------------------------------------------------------------------

_ORDINAL_WORDS = (
    "first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth"
    "|thirteenth|fourteenth|fifteenth|sixteenth|seventeenth|eighteenth|nineteenth|twentieth"
    "|thirtieth"
)
# Words after a number that make it a count or a measure rather than a day of the month.
_UNITS = (
    r"(?:hours?|hrs?|h|minutes?|mins?|m|am|pm|a|p|inches|inch|in|ft|feet|foot|degrees?|deg|f"
    r"|percent|miles?|mi|mph|grades?|graders?|years?|yrs?|students?|points?|kids|children"
    r"|cm|mm|weeks?|days?)"
)
_HOLIDAYS = (
    r"(?:mlk|martin\s+luther\s+king(?:\s+jr)?|presidents'?|president's|washington'?s|lincoln'?s"
    r"|labor|memorial|veterans'?|veteran's|columbus|indigenous\s+peoples'?|election"
    r"|independence|groundhog|valentine'?s|st\s+patrick'?s|arbor|patriots'?|casimir\s+pulaski"
    r"|cesar\s+chavez)\s+day\b"
    r"|\b(?:thanksgiving|christmas|xmas|juneteenth|easter|new\s+year'?s|good\s+friday"
    r"|black\s+friday|cyber\s+monday|rosh\s+hashanah|yom\s+kippur|eid|diwali"
    r"|lunar\s+new\s+year|spring\s+break|winter\s+break|fall\s+break|mid-?winter\s+break)"
)
_COUNT = r"(?:\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)"
# Day letters as schedules write them: "M/W/F", "T/Th", "M-F".
_LETTER_DAY = r"(?:th|tu|sa|su|[mtwrf])"
_UNREADABLE = re.compile(
    rf"""
    (?P<ord>(?<![\d/.-])\b\d{{1,2}}{_ORDINAL}\b)
    |(?P<ordword>\bthe\s+(?:{_ORDINAL_WORDS})\b
        |\b(?:twenty|thirty)[- ]?(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth)\b)
    |(?P<md>(?<![\d/.:-])\b(?:0?[1-9]|1[0-2])[-.](?:0?[1-9]|[12]\d|3[01])(?![\d/]|[-.]\d)
        (?!\s*-?\s*{_UNITS}\b))
    |(?P<ymd>\b20\d\d/\d{{1,2}}/\d{{1,2}}\b)
    |(?P<period>\b(?:next|following|coming|upcoming|previous|last)\s+(?:school\s+)?
        (?:week|weekend|days?|few\s+days|several\s+days|couple\s+(?:of\s+)?days
        |(?:\d{{1,2}}|two|three|four|five)\s+(?:school\s+)?days)\b
        |\bweek\s+of\b|\b(?:later|end|early|middle|beginning|start)\s+(?:of\s+)?
        (?:this|the|next)\s+week\b|\bfor\s+the\s+week\b|\bmidweek\b
        |\bday\s+after\s+(?:tomorrow|next)\b|\bthe\s+day\s+(?:after|before)\b|\bovermorrow\b
        |\b(?:last|previous|past)\s+(?:{_WD_SOLO})\b)
    |(?P<weekend>\b(?:this|the|next|all|over\s+the)\s+weekend\b)
    |(?P<span>\b(?:last|next|previous|following|coming|upcoming|past|this)\s+(?:school\s+)?
        (?:years?|months?|semesters?|terms?|seasons?|summer|quarter)\b
        |\b(?:for\s+the\s+)?(?:rest|remainder|balance)\s+of\s+the\s+(?:school\s+)?
        (?:year|semester|term|season)\b
        |\bfor\s+the\s+(?:school\s+)?(?:year|summer|season|semester|term|month)\b)
    |(?P<count>(?<![/\d.-])\b(?:{_COUNT}(?:\s*(?:-|to|or)\s*{_COUNT})?
        |several|few|couple(?:\s+of)?|multiple)\s*-?\s*(?:more\s+|additional\s+|extra\s+
        |consecutive\s+|straight\s+|school\s+)?(?:days?|weeks?)\b
        |\b(?:another|one\s+more|an\s+(?:additional|extra))\s+(?:school\s+)?day\b)
    |(?P<holiday>\b{_HOLIDAYS})
    |(?P<satsun>\b(?:sat|sun)\b(?=\s*$|\s*[,;.:!?/&-]|\s+(?:and|or|through|thru|to|until|till
        |due|because|for|only|as|at|with|but|morning|afternoon|evening|night)\b))
    |(?P<bare>\b(?:on|the)\s+(?:the\s+)?(?P<bare_day>[12]?\d|3[01])\b(?![:/.]\d)
        (?=\s*(?:$|[-,;.!?:/]|(?:and|or|through|thru|to|until|till)\b|(?:{_WD_ANY}|{_MONTH})\b)))
    |(?P<letters>\b{_LETTER_DAY}[/-]{_LETTER_DAY}\b)
    |(?P<letter>(?:(?<=[a-z][a-z]\s)|(?<=[a-z][a-z][-/])|(?<=[a-z][,:]\s)|(?<=[a-z]\s[-/]\s))
        {_LETTER_DAY}(?=\s*(?:$|[,;.!?|]))
        |(?:^|(?<=[;|]\s)){_LETTER_DAY}(?=\s*:\s))
    |(?P<wdnext>\b(?:{_WD_SOLO})\s+next\b(?=\s*(?:$|[-,;.!?:])))
    """,
    re.VERBOSE | re.ASCII,
)
# Words after an ordinal that make it a rank rather than a day: "3rd grade", "2nd snow day".
_RANK_NOUNS = frozenset(
    [
        "grade",
        "grades",
        "grader",
        "graders",
        "period",
        "periods",
        "hour",
        "hours",
        "block",
        "blocks",
        "floor",
        "street",
        "st",
        "ave",
        "avenue",
        "place",
        "day",
        "days",
        "snow",
        "nti",
        "ami",
        "e-learning",
        "elearning",
        "virtual",
        "remote",
        "calamity",
        "emergency",
        "weather",
        "inclement",
        "straight",
        "consecutive",
        "time",
        "times",
        "year",
        "years",
        "annual",
        "quarter",
        "semester",
        "round",
        "week",
        "weeks",
        "delay",
        "delays",
        "closure",
        "closures",
        "closing",
        "closings",
        "cancellation",
        "cancellations",
        "flex",
        "make-up",
        "makeup",
        "school",
        "anniversary",
        "birthday",
        "edition",
        "century",
        "amendment",
        "district",
        "precinct",
        "ward",
        "inning",
        "half",
        "prize",
        "cold",
        "storm",
        "winter",
        "snowstorm",
    ]
)
# Words just before a number pair that make it a grade span, an age or a time: "grades 6-12",
# and the hours of a meal service on a closed day ("meal pickup 11-1", "grab and go meals
# 10-12", "lunch served 11-1").
_SPAN_WORDS = frozenset(
    [
        "grade",
        "grades",
        "ages",
        "age",
        "room",
        "rooms",
        "route",
        "routes",
        "bus",
        "buses",
        "at",
        "by",
        "from",
        "k",
        "pk",
        "tk",
        "between",
        "hours",
        "meal",
        "meals",
        "lunch",
        "lunches",
        "breakfast",
        "breakfasts",
        "pickup",
        "pick-up",
        "grab-n-go",
        "grab-and-go",
        "distribution",
        "served",
        "available",
    ]
)
# Two words that do the same: "pick up 11-1", "grab and go 10-12".
_SPAN_PAIRS = frozenset({("pick", "up"), ("and", "go"), ("n", "go"), ("grab", "go")})
_GRADE_WINDOW = 24


_RANK_NEXT = re.compile(r" ([a-z][a-z'-]*)", re.ASCII)


def _next_word(text: str, position: int) -> str:
    following = words(text, position, min(len(text), position + 24))
    return following[0] if following else ""


def _is_rank(text: str, match: re.Match[str]) -> bool:
    """Whether an ordinal is a rank ("3rd grade", "the second time") rather than a day."""
    if "grade" in text[max(0, match.start() - _GRADE_WINDOW) : match.end() + _GRADE_WINDOW]:
        return True
    # Only a noun right after it: in "23rd, delay" or "the 23rd - remote" it is a day.
    following = _RANK_NEXT.match(text, match.end())
    return following is not None and following.group(1) in _RANK_NOUNS


def _is_span(text: str, match: re.Match[str]) -> bool:
    """Whether a number pair is a grade span, an age range or a time rather than a date."""
    before = words(text, max(0, match.start() - _GRADE_WINDOW), match.start())
    if before and (before[-1] in _SPAN_WORDS or tuple(before[-2:]) in _SPAN_PAIRS):
        return True
    return "grade" in text[max(0, match.start() - _GRADE_WINDOW) : match.start()]


# A day after these words says when school is back, not when a status holds.
_REOPENING = re.compile(
    r"\b(?:resum(?:e|es|ing)|return(?:s|ing)?|reopen(?:s|ing)?|back\s+(?:in|on|to))\b[^.;!?]*$",
    re.ASCII,
)
_REOPENING_WINDOW = 48


def _unreadable_match(text: str, match: re.Match[str]) -> bool:
    kind = match.lastgroup
    if _REOPENING.search(text, max(0, match.start() - _REOPENING_WINDOW), match.start()):
        return False
    if kind in {"ord", "ordword"}:
        return not _is_rank(text, match)
    if kind == "md":
        return not _is_span(text, match)
    if kind == "weekend":
        following = _next_word(text, match.end())
        return following not in SCOPES and following not in MODIFIERS
    return True


# Close misspellings of these are day words the parser cannot read ("Wensday", "tomorow" is read).
_DAY_NAMES = (
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "today",
    "tonight", "tomorrow", "yesterday", "january", "february", "april", "august", "september",
    "october", "november", "december",
)  # fmt: skip
_READ_DAY_WORDS = frozenset(
    [*WEEKDAYS, *MONTHS, *_TODAY_WORDS, *_TOMORROW_WORDS, *_YESTERDAY_WORDS]
    + [f"{name}s" for name in ("monday", "tuesday", "wednesday", "thursday", "friday")]
    + ["saturdays", "sundays", "tomorrows", "todays", "tonights"]
)
# Short forms that stand for a day but are not read: "2day" could also be "2-day".
_UNREAD_DAY_WORDS = frozenset(
    [
        "2day",
        "tday",
        "tdy",
        "yday",
        "yest",
        "ystrdy",
        "thr",
        "thrs",
        "wedn",
        "wednes",
        "wensday",
        "frid",
        "satur",
        "sund",
        "mond",
        "tmrow",
        "tmro",
        "2mro",
        "tmoro",
        "2mor",
        "tmorrow",
        "tomrw",
        "th",
        "tu",
        # Spanish names of days, which the patterns do not read ("Closed mañana").
        "manana",
        "hoy",
        "lunes",
        "martes",
        "miercoles",
        "jueves",
        "viernes",
        "sabado",
        "domingo",
    ]
)
# Spellings of "tomorrow" beyond the ones read: "tmrrow", "tomorrrow", "2mrow".
_TOMORROW_LIKE = re.compile(r"(?:t|2)o?m{1,2}[aeiou]?r+[aeiou]*r*[aeiou]*w*(?:'?s)?", re.ASCII)
# Real words close to a day name.
_NOT_DAY_WORDS = frozenset(
    [
        "sundae",
        "sundaes",
        "sundry",
        "sunray",
        "augusta",
        "toady",
        "toddy",
        "tokay",
        "nonmember",
        "deceiver",
        "decenter",
        "tuesdays'",
        "mondays'",
        "fridays'",
        "todays'",
        "tonite's",
    ]
)
_JOIN_MARKS = re.compile(r"[-/]", re.ASCII)
_SHORTEST_FUZZY = 4
_TIGHT_LENGTH = 6
_TIGHT_EDITS = 1
_LOOSE_EDITS = 2
# The day names by first letter: a misspelling keeps the first letter ("Wensday", "Thrusday").
_NAMES_BY_FIRST: dict[str, tuple[str, ...]] = {
    first: tuple(name for name in _DAY_NAMES if name[0] == first)
    for first in {name[0] for name in _DAY_NAMES}
}


@lru_cache(maxsize=65536)
def daylike_word(word: str) -> bool:
    """Whether ``word`` names a day or month in a form the date patterns do not read.

    A close misspelling is within one edit of a day or month name (two for a
    long one), counting a swap of neighbouring letters as one edit (optimal
    string alignment distance).
    """
    if "-" in word or "/" in word:
        # A day word joined to another by a mark is a day word too ("closed-wendesday").
        return any(map(daylike_word, _JOIN_MARKS.split(word)))
    stem = word.removesuffix("'s")
    if stem in _READ_DAY_WORDS or word in _NOT_DAY_WORDS:
        return False
    if stem in _UNREAD_DAY_WORDS or _TOMORROW_LIKE.fullmatch(stem) is not None:
        return True
    if len(stem) < _SHORTEST_FUZZY or not stem.isalpha():
        return False
    for name in _NAMES_BY_FIRST.get(stem[0], ()):
        if abs(len(name) - len(stem)) > _LOOSE_EDITS:
            continue
        limit = _TIGHT_EDITS if min(len(name), len(stem)) <= _TIGHT_LENGTH else _LOOSE_EDITS
        if OSA.distance(stem, name, score_cutoff=limit) <= limit:
            return True
    return False


def names_day(word: str) -> bool:
    """Whether ``word`` names a day or a month, read or not: "Friday", "Jan", "tmrw", "Wensday"."""
    return word.removesuffix("'s") in _READ_DAY_WORDS or daylike_word(word)


# Month names other than "may", which after a day number or alone is the verb.
_MONTH_WORDS = frozenset(name for name in MONTHS if name != "may")
MONTH_NAMES = _MONTH_WORDS
"""The month names the date patterns read only in a date ("may" is a verb as often)."""
# Words that can start a phrase :data:`_UNREADABLE` matches, besides numbers.
_SCAN_WORDS = frozenset(_ORDINAL_WORDS.split("|")) | frozenset(
    [
        "next",
        "following",
        "coming",
        "upcoming",
        "previous",
        "last",
        "past",
        "rest",
        "remainder",
        "balance",
        "year",
        "years",
        "summer",
        "semester",
        "season",
        "week",
        "weekend",
        "midweek",
        "after",
        "before",
        "overmorrow",
        "another",
        "additional",
        "extra",
        "several",
        "few",
        "couple",
        "multiple",
        "sat",
        "sun",
        "break",
        "mlk",
        "martin",
        "presidents",
        "presidents'",
        "president's",
        "washington's",
        "washingtons",
        "lincoln's",
        "lincolns",
        "labor",
        "memorial",
        "veterans",
        "veterans'",
        "veteran's",
        "columbus",
        "indigenous",
        "election",
        "independence",
        "groundhog",
        "valentine's",
        "valentines",
        "patrick's",
        "patricks",
        "arbor",
        "patriots",
        "patriots'",
        "pulaski",
        "chavez",
        "thanksgiving",
        "christmas",
        "xmas",
        "juneteenth",
        "easter",
        "year's",
        "years",
        "good",
        "black",
        "cyber",
        "rosh",
        "yom",
        "eid",
        "diwali",
        "lunar",
    ]
)
_NUMBER_WORDS = frozenset(
    ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]
)
# Number tokens that could be a day: "21st", "1-21", "2026/01/21", "2-day".
_DAYLIKE_NUMBER = re.compile(
    r"\d{1,2}(?:(?:st|nd|rd|th)(?![a-z])|-\d|(?:-\d{1,2})?-days?$)|20\d\d/", re.ASCII
)
# Tokens that are day letters: "m/w/f", "t-th".
_LETTER_TOKEN = re.compile(rf"{_LETTER_DAY}[/-]{_LETTER_DAY}(?![a-z])", re.ASCII)
# The holidays with "break" in them (see _HOLIDAYS): "break" is the word that hints at them.
_BREAK_HOLIDAY = re.compile(r"\b(?:spring|winter|fall|mid-?winter)\s+break\b", re.ASCII)
# A number or a counting word just before "day": what the "count" form needs.
_COUNTS = (
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "several",
    "few", "couple", "of", "multiple", "more", "additional", "extra", "consecutive", "straight",
    "school", "another",
)  # fmt: skip
_COUNTED_DAY = re.compile(
    r"(?:\d|\b(?:" + "|".join(_COUNTS) + r"))\s*-?\s*(?:days?|weeks?)\b", re.ASCII
)
_COUNTED_UNITS = frozenset({"day", "days", "week", "weeks"})
_BARE_DAY = re.compile(r"\b(?:on|the)\s+(?:the\s+)?\d", re.ASCII)  # "on the 22"
# The same two tests as patterns the regex engine can scan fast, which _scan_possible uses:
# each opens with a letter (a word boundary before it is looked for after the letter, in a
# look back over it and the character before), so the engine skips to the few places where
# one of those letters is. _COUNTED_DAY opens with a digit or any of many words, so its
# test reads the text backwards, from the unit ("yad" of "day") on: a match of
# _COUNTED_DAY_BACKWARDS in the reversed text is a match of _COUNTED_DAY in the text.
_NOT_AFTER_WORD = "(?<![A-Za-z0-9_]{0})"
_COUNTED_DAY_BACKWARDS = re.compile(
    r"(?:"
    + "|".join(
        unit[0] + _NOT_AFTER_WORD.format(unit[0]) + unit[1:]
        for unit in ("syad", "yad", "skeew", "keew")
    )
    + r")\s*-?\s*(?:\d|(?:"
    + "|".join(count[::-1] for count in _COUNTS)
    + r")(?![A-Za-z0-9_]))",
    re.ASCII,
)
_BARE_DAY_FAST = re.compile(
    r"(?:"
    + "|".join(word[0] + _NOT_AFTER_WORD.format(word[0]) + word[1:] for word in ("on", "the"))
    + r")\s+(?:the\s+)?\d",
    re.ASCII,
)
# Where a phrase :data:`_UNREADABLE` matches can start. Day letters and "Wednesday next"
# are found by what follows them, so not every word starting with "t" is tried.
_UNREADABLE_STARTS = re.compile(
    r"\b(?:"
    + trie(
        [str(digit) for digit in range(10)]
        + ["the", "twenty", "thirty", "next", "following", "coming", "upcoming", "previous"]
        + ["last", "past", "week", "later", "end", "early", "middle", "beginning", "start"]
        + ["for", "midweek", "day", "overmorrow", "this", "all", "over", *_NUMBER_WORDS, "several"]
        + ["few", "couple", "multiple", "another", "an", "sat", "sun", "on", "rest", "remainder"]
        + [
            "mlk",
            "martin",
            "president",
            "washington",
            "lincoln",
            "labor",
            "memorial",
            "veteran",
            "columbus",
        ]
        + [
            "indigenous",
            "election",
            "independence",
            "groundhog",
            "valentine",
            "st",
            "arbor",
            "patriot",
            "casimir",
        ]
        + [
            "cesar",
            "thanksgiving",
            "christmas",
            "xmas",
            "juneteenth",
            "easter",
            "new",
            "good",
            "black",
            "cyber",
            "rosh",
        ]
        + ["yom", "eid", "diwali", "lunar", "spring", "winter", "fall", "mid"]
    )
    + rf"|{_LETTER_DAY}(?=[/-]|\s*(?:$|[,;.!?|]|:\s))|(?:{_WD_SOLO})(?=\s+next\b))",
    re.ASCII,
)


# A day letter alone, after a status or heading a slot: "Closed W", "W: Closed".
_DAY_LETTERS = frozenset({"m", "t", "w", "r", "f", "th", "tu", "sa", "su"})


def _scan_word(word: str) -> bool:
    """Whether ``word`` can start a phrase :data:`_UNREADABLE` matches."""
    return (
        word in _SCAN_WORDS
        or word in _DAY_LETTERS
        or word.startswith(("twenty", "thirty"))
        or (word[0].isdigit() and _DAYLIKE_NUMBER.match(word) is not None)
        or (("/" in word or "-" in word) and _LETTER_TOKEN.match(word) is not None)
    )


# What a word can be, as bits of :func:`word_hints`.
DATE_START = 1  # it can start a date expression
MONTH_WORD = 2  # a month name the date patterns read only in a date
DAYLIKE = 4  # a day word in a form not read ("Wensday", "tmrrow")
UNREADABLE_START = 8  # it can start a phrase :data:`_UNREADABLE` matches
COUNT_WORD = 16  # a number, which before "day" or "days" counts days
DAY_WORD = 32  # "day", "days", "week" or "weeks"
ON_THE = 64  # "on" or "the", which before a bare number make it a day ("on the 22")
DAY_NUMBER = 128  # a number that could be a day of the month
BREAK_WORD = 256  # "break", which after "spring", "winter" or "fall" names a holiday
HINT_BITS = 511


@lru_cache(maxsize=65536)
def word_hints(word: str) -> int:
    """What one word can be in a date, as bits (cached: listings reuse a small vocabulary).

    The union over a text's words tells :func:`find_date_groups` and
    :func:`find_unreadable` which scans can find anything.
    """
    digits = word.isdigit()
    return (
        (DATE_START if _DATE_STARTS.match(word) is not None else 0)
        | (MONTH_WORD if word in _MONTH_WORDS else 0)
        | (DAYLIKE if daylike_word(word) else 0)
        | (UNREADABLE_START if word != "break" and _scan_word(word) else 0)
        | (BREAK_WORD if word == "break" else 0)
        | (COUNT_WORD if digits or word in _NUMBER_WORDS else 0)
        | (DAY_WORD if word in _COUNTED_UNITS else 0)
        | (ON_THE if word in {"on", "the"} else 0)
        | (DAY_NUMBER if digits and len(word) <= 2 else 0)  # noqa: PLR2004 - a day of the month
    )


def find_unreadable(  # noqa: PLR0913 - the text, what is read of it, and what the caller knows
    text: str,
    groups: Sequence[DateGroup],
    read: Sequence[tuple[int, int]],
    tokens: Sequence[str] | None = None,
    hints: int | None = None,
    *,
    months: int | None = None,
) -> bool:
    """Whether normalized ``text`` names a day that the date patterns do not read.

    ``groups`` are the text's date groups and ``read`` the spans already
    understood (date groups and status phrases): a day-like phrase wholly
    inside one of them is read. Holiday names count even inside a read span:
    "Good Friday" is not this Friday. ``tokens`` are the text's words in order
    and ``hints`` the union of :func:`word_hints` over them, when the caller
    has them.
    """
    if hints is None:
        tokens = words(text) if tokens is None else tokens
        hints = reduce(or_, map(word_hints, tokens), 0)
    if hints & MONTH_WORD:
        # Each month name the date patterns read belongs to one date atom.
        if months is None:
            tokens = words(text) if tokens is None else tokens
            months = sum(map(_MONTH_WORDS.__contains__, tokens))
        for group in groups:
            for atom in group[GROUP_ATOMS]:
                months -= atom[ATOM_NAMED]
        if months > 0:
            return True
    if hints & DAYLIKE and any(
        map(
            daylike_word,
            (word for low, high in _gaps(read, len(text)) for word in words(text, low, high)),
        )
    ):
        return True
    if not _scan_possible(text, hints):
        return False
    for match in scan(_UNREADABLE, text, _UNREADABLE_STARTS):
        # A bare day number ("on the 22") is read when a date group holds it ("the 22 January").
        start, end = match.span("bare_day" if match.lastgroup == "bare" else 0)
        inside_read = any(low <= start and end <= high for low, high in read)
        if (not inside_read or match.lastgroup == "holiday") and _unreadable_match(text, match):
            return True
    return False


_SCAN_HINTS = UNREADABLE_START | BREAK_WORD | DAY_WORD | ON_THE
UNREADABLE_HINTS = DAYLIKE | _SCAN_HINTS
"""The hints :func:`unreadable_possible` reads: with none of them, and no full stop in the text,
it is false (a quick look for the caller)."""


def _scan_possible(text: str, hints: int) -> bool:
    """Whether the scan for :data:`_UNREADABLE` can find anything in ``text``.

    Every phrase it matches holds a word that hints at it (see :func:`word_hints`),
    and some forms need a pattern the text must hold too.
    """
    if not hints & _SCAN_HINTS and "." not in text:
        return False  # (every form below needs one of these hints, or a full stop)
    return bool(
        hints & UNREADABLE_START
        or (hints & BREAK_WORD and _BREAK_HOLIDAY.search(text) is not None)  # "winter break"
        or (  # "a 2 day closure", "one more day" (see _COUNTED_DAY_BACKWARDS)
            hints & DAY_WORD
            and hints & COUNT_WORD
            and _COUNTED_DAY_BACKWARDS.search(text[::-1]) is not None
        )
        or (hints & ON_THE and hints & DAY_NUMBER and _BARE_DAY_FAST.search(text) is not None)
        or ("." in text and dot_pair(text))  # "1.21"
    )


# A full stop between two digits. The pattern opens with the full stop, so the regex engine
# skips from one to the next (a run of them, as in "closed...... open", costs no more).
_DOT_PAIR = re.compile(r"\.(?<=[0-9]\.)[0-9]", re.ASCII).search


def dot_pair(text: str) -> bool:
    """Whether a full stop stands between two digits: "1.21", a date the patterns do not read.

    (Two digits and the stop between them hold no space: in a normalized text, a stretch
    between spaces holds each such pair whole.)
    """
    return _DOT_PAIR(text) is not None


# What may not stand right before a year that stands alone: a letter, a digit or a mark that
# joins it to more ("1/2026", "v2026", "-2026"); and right after one, a time in hours.
_BEFORE_YEAR = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_/.:-")
_HOURS_AFTER = re.compile(r"\s*-?\s*(?:hours?|hrs?|h)\b", re.ASCII)


def year_alone(text: str, groups: Sequence[DateGroup]) -> bool:
    """Whether ``text`` names a year outside its date groups, a time the parser cannot place:
    "closed in 2019", "closed since 2020", "2025-2026 school year".

    A year in a date ("Jan. 21, 2026", "1/21/2026") belongs to the date that holds it, and
    "1900 hours" is a time. (The words are looked through by hand: a search for each year's
    first two digits is quicker here than a pattern.)
    """
    size = len(text)
    for lead in ("19", "20"):
        start = text.find(lead)
        while start >= 0:
            end = start + 4
            if (
                end <= size
                and text[start + 2 : end].isdigit()
                and (start == 0 or text[start - 1] not in _BEFORE_YEAR)
                and (end == size or not (text[end].isalnum() or text[end] == "_"))
                and not (text.startswith((".", ":"), end) and text[end + 1 : end + 2].isdigit())
                and _HOURS_AFTER.match(text, end) is None
                and not any(group[GROUP_START] <= start < group[GROUP_END] for group in groups)
            ):
                return True
            start = text.find(lead, start + 1)
    return False


def unreadable_possible(text: str, hints: int) -> bool:
    """Whether :func:`find_unreadable` can find more than an unread month name in ``text``.

    ``hints`` is the union of :func:`word_hints` over the text's words. When this
    is false, the text names an unread day only if it holds more month names
    than its date groups read.
    """
    return bool(hints & DAYLIKE) or _scan_possible(text, hints)


def _dated(group: DateGroup, index: int) -> bool:
    """Whether a group's atom is a date, or a day name with a date beside it."""
    atoms, links = group[GROUP_ATOMS], group[GROUP_LINKS]
    return atoms[index][ATOM_KIND] == "explicit" or (
        index < len(links) and links[index] == "appos" and atoms[index + 1][ATOM_KIND] == "explicit"
    )


_ORDERED_KINDS = frozenset({"explicit", "weekday", "relative"})


def _backward(group: DateGroup, points: Sequence[date | None]) -> bool:
    """Whether a day in a list or range falls before the day written ahead of it.

    "Closed tomorrow and Jan. 19", "Jan. 23 through Jan. 21": the text contradicts
    itself, so which days it means is unclear. Days named two ways ("appos") are
    compared elsewhere.
    """
    previous: date | None = None
    for index, point in enumerate(points):
        if point is None or group[GROUP_ATOMS][index][ATOM_KIND] not in _ORDERED_KINDS:
            previous = None
            continue
        if previous is not None and point < previous and group[GROUP_LINKS][index - 1] != "appos":
            return True
        previous = point
    return False


def _rejoin_last_date(group: DateGroup) -> DateGroup | None:
    """Put a run's last weekday back with the one date that follows it.

    The dates after a run of weekday names restate the whole run ("Thursday and
    Friday, Jan. 22-23"), but a single date dates only the last name: "Monday
    through Friday, January 30" is the week that ends on the 30th. ``None``
    when the group is not of that form.
    """
    atoms, links = group[GROUP_ATOMS], group[GROUP_LINKS]
    if len(atoms) < 3 or links[-1] != "appos" or "appos" in links[:-1]:  # noqa: PLR2004
        return None
    named, dated = atoms[-2], atoms[-1]
    if not (
        _plain_weekday(named) and dated[ATOM_KIND] == "explicit" and dated[ATOM_WEEKDAY] is None
    ):
        return None
    # (The date from the weekday on, with the weekday: fields 0, 3 and 10.)
    joined: DateAtom = (
        named[ATOM_START], dated[1], dated[2], named[ATOM_WEEKDAY], *dated[4:10],
        dated[ATOM_START], dated[11], dated[12],
    )  # fmt: skip
    return (group[0], group[1], (*atoms[:-2], joined), links[:-1], group[4])


def _gaps(spans: Sequence[tuple[int, int]], length: int) -> list[tuple[int, int]]:
    """The stretches of a text of ``length`` that no span covers."""
    gaps: list[tuple[int, int]] = []
    position = 0
    for low, high in sorted(spans):
        if low > position:
            gaps.append((position, low))
        position = max(position, high)
    if position < length:
        gaps.append((position, length))
    return gaps


def _anchor_pair(
    atoms: tuple[DateAtom, ...], first: date | None, second: date | None
) -> tuple[set[date | None], set[int]]:
    """The days of two atoms read as a list, a weekday name taking the other's date if it fits.

    Return the days and the positions of the weekday names so placed (see
    :meth:`Calendar._anchor_weekdays`).
    """
    points = [first, second]
    anchored: set[int] = set()
    for index, atom in enumerate(atoms):
        other = 1 - index
        fixed = points[other]
        if (
            _plain_weekday(atom)
            and fixed is not None
            and atoms[other][ATOM_KIND] in {"explicit", "relative"}
            and fixed.weekday() == atom[ATOM_WEEKDAY]
        ):
            points[index] = fixed
            anchored.add(index)
    return set(points), anchored


def _school_day_between(weekday: int, step: int) -> bool:
    """Whether a school day comes after ``weekday`` and before ``step`` days after it."""
    for gap in range(1, step):  # noqa: SIM110 - (a loop costs less than a generator, per call)
        if (weekday + gap) % _WEEK < _SATURDAY:
            return True
    return False


def weekdays_out_of_order(groups: Iterable[DateGroup]) -> bool:
    """Whether weekday names, read in text order, skip back over a school day.

    Listed weekday names read forward: "Monday and Wednesday", "Friday and
    Monday" (over the weekend), "Closed Monday; NTI Tuesday". A name repeated
    ("Monday morning: closed. Monday afternoon: closed") is the same day. "Wednesday and
    Tuesday" or "Closed Thursday; NTI Monday" would jump back over school days
    (or forward nearly a week), so the days they mean are unclear. Ranges
    ("Wednesday through Monday") and names with "next" or a day number are
    not checked; a date or a relative day between two names starts afresh.
    """
    previous: int | None = None
    for group in groups:
        for index, atom in enumerate(group[GROUP_ATOMS]):
            if not _plain_weekday(atom) or atom[ATOM_WEEKDAY] is None:
                previous = None
                continue
            ranged = index > 0 and group[GROUP_LINKS][index - 1] in {"range", "until", "first"}
            if atom[ATOM_WEEKDAY] == previous and not ranged:
                continue  # the same day named again: "Monday: Closed Monday"
            if previous is not None and atom[ATOM_MODIFIER] is None and not ranged:
                step = (atom[ATOM_WEEKDAY] - previous) % _WEEK or _WEEK
                if atom[ATOM_WEEKDAY] <= previous and _school_day_between(previous, step):
                    return True
            previous = atom[ATOM_WEEKDAY]
    return False


# The calendar -----------------------------------------------------------------------------


@lru_cache(maxsize=64)
def zone(name: str) -> ZoneInfo:
    """Return the IANA time zone ``name``; raise ``ValueError`` if it is unknown."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as error:
        message = f"unknown time zone: {name!r}"
        raise ValueError(message) from error


@lru_cache(maxsize=4096)
def _school_days(first: date, last: date) -> tuple[date, ...]:
    """The weekdays from ``first`` through ``last``, or every day when none is a weekday.

    Kept per pair: a run to a named day ("closed until April 6") comes back in many
    listings, and its days are the same each time.
    """
    days = [first + timedelta(days=n) for n in range((last - first).days + 1)]
    weekdays = tuple(day for day in days if day.weekday() < _SATURDAY)
    return weekdays or tuple(days)


_RUN_LINKS = frozenset({"list", "range", "until", "first"})
_SUNDAY = 6
_ONE_DAY = timedelta(days=1)
# timedelta(days=n) for n from -7 to 7, by n (a negative index counts from the end).
_DAYS: tuple[timedelta, ...] = (
    *(timedelta(days=n) for n in range(8)),
    *(timedelta(days=n) for n in range(-7, 0)),
)
# From each weekday (Monday first) to the first school day on or after it (False) or after
# it (True).
_TO_SCHOOL_DAY: dict[bool, tuple[timedelta, ...]] = {
    after: tuple(
        timedelta(
            days=next(
                step for step in range(after, after + _WEEK) if (weekday + step) % _WEEK < _SATURDAY
            )
        )
        for weekday in range(_WEEK)
    )
    for after in (False, True)
}


def _plain_weekday(atom: DateAtom) -> bool:
    """A weekday name with no day number to pin it: its week is chosen by context."""
    return atom[ATOM_KIND] == "weekday" and atom[ATOM_DAY] is None


def _same_day(left: DateAtom, right: DateAtom) -> bool | None:
    """Whether two day atoms of one kind name the same day; ``None`` for other pairs.

    An evening ("Sunday evening") names no school day to compare.
    """
    if left[ATOM_KIND] != right[ATOM_KIND] or left[ATOM_EVENING] or right[ATOM_EVENING]:
        return None
    if left[ATOM_KIND] == "weekday":
        return left[ATOM_WEEKDAY] == right[ATOM_WEEKDAY]
    if left[ATOM_KIND] == "relative":
        return left[ATOM_OFFSET] == right[ATOM_OFFSET]
    if left[ATOM_KIND] == "explicit":
        if left[ATOM_MONTH] is None or right[ATOM_MONTH] is None:  # "Jan. 22: closed the 22nd"
            return left[ATOM_DAY] == right[ATOM_DAY]
        return (left[ATOM_MONTH], left[ATOM_DAY]) == (right[ATOM_MONTH], right[ATOM_DAY])
    return None


def _without_repeats(group: DateGroup) -> DateGroup:
    """The group less each atom that restates the one before it as itself ("Monday: Monday")."""
    keep = [0]
    links: list[Link] = []
    for index, link in enumerate(group[GROUP_LINKS]):
        left, right = group[GROUP_ATOMS][keep[-1]], group[GROUP_ATOMS][index + 1]
        if link == "appos" and _same_day(left, right):
            continue
        keep.append(index + 1)
        links.append(link)
    if len(keep) == len(group[GROUP_ATOMS]):
        return group
    atoms = tuple(group[GROUP_ATOMS][index] for index in keep)
    return (group[0], group[1], atoms, tuple(links), group[4])


def _other_day_restated(group: DateGroup) -> bool:
    """Whether a day is restated as a different day of its own kind.

    Two weekdays, two relative days or two dates side by side name one day
    ("Monday: Closed Monday"), so they must be the same one: "Wednesday: Closed
    Thursday through Friday" names two. (A pair alone is checked on the
    calendar; see :meth:`Calendar._resolve_pair`.)
    """
    return any(
        link == "appos"
        and _same_day(group[GROUP_ATOMS][index], group[GROUP_ATOMS][index + 1]) is False
        for index, link in enumerate(group[GROUP_LINKS])
    )


_RELATIVE_AND_WEEKDAY: frozenset[AtomKind] = frozenset({"relative", "weekday"})


def _run_length(atoms: tuple[DateAtom, ...], index: int, step: int) -> int:
    """How many atoms of the kind of ``atoms[index]`` run from it, stepping by ``step``."""
    kind = atoms[index][ATOM_KIND]
    count = 0
    while 0 <= index < len(atoms) and atoms[index][ATOM_KIND] == kind:
        count += 1
        index += step
    return count


def _month_shift(day: date, months: int) -> tuple[int, int]:
    index = day.year * 12 + day.month - 1 + months
    return index // 12, index % 12 + 1


def check_moment(posted_at: datetime, tz: str) -> None:
    """Raise ``ValueError`` if ``posted_at`` is naive or ``tz`` is not a known time zone.

    The checks :class:`Calendar` makes, for a caller that needs no calendar.
    """
    tzinfo = posted_at.tzinfo
    if tzinfo is None or (type(tzinfo) is not ZoneInfo and posted_at.utcoffset() is None):
        message = "posted_at must be timezone-aware"
        raise ValueError(message)
    if type(tzinfo) is not ZoneInfo or tzinfo.key != tz:
        zone(tz)  # (a moment in the zone named is in a known zone: no lookup)


class Calendar:
    """Resolves date expressions for one posting time in one time zone."""

    __slots__ = ("minutes", "overnight", "today")

    def __init__(self, posted_at: datetime, tz: str) -> None:
        tzinfo = posted_at.tzinfo
        # A ZoneInfo always gives an offset; any other tzinfo is asked.
        if type(tzinfo) is ZoneInfo:
            if tzinfo.key == tz:
                local = posted_at  # (in the zone named already, the most common: no lookup)
            else:
                place = zone(tz)
                local = posted_at if tzinfo is place else posted_at.astimezone(place)
        elif tzinfo is None or posted_at.utcoffset() is None:
            message = "posted_at must be timezone-aware"
            raise ValueError(message)
        else:
            local = posted_at.astimezone(zone(tz))
        minutes = local.hour * 60 + local.minute
        self.today = local.date()
        self.minutes = minutes
        self.overnight = minutes < _OVERNIGHT_END_MINUTES

    def _start(self, default: date | None) -> date:
        """The day an open start counts from (see :meth:`resolve`)."""
        return self.next_school_day(_OPEN_START_CUTOFF) if default is None else default

    def next_school_day(self, cutoff_minutes: int) -> date:
        """Return the first weekday at or after the posting day, or after it past ``cutoff``."""
        after = not self.overnight and self.minutes >= cutoff_minutes
        return self.today + _TO_SCHOOL_DAY[after][self.today.weekday()]

    def undated_day(self, today_until: int, tomorrow_from: int) -> date | None:
        """Return the day a status that names no day applies to, or ``None`` if unclear.

        Before ``today_until`` minutes after midnight it is the posting day (or
        the next school day); from ``tomorrow_from`` on it is the next school
        day after it. Between the two it could be either. A school day more than
        a day after the posting day (Monday, for a post on Friday evening or on
        Saturday) is too far off to be read from the posting time alone.
        """
        weekday = self.today.weekday()
        if self.overnight or self.minutes < today_until:
            step = _TO_SCHOOL_DAY[False][weekday]
        elif self.minutes >= tomorrow_from:
            step = _TO_SCHOOL_DAY[True][weekday]
        elif weekday == _SUNDAY:
            step = _ONE_DAY  # both readings land on Monday
        else:
            return None
        return self.today + step if step <= _ONE_DAY else None

    def near_cutoff(self, today_until: int, tomorrow_from: int | None = None) -> bool:
        """Whether the post falls in the hour before ``today_until`` or 3 hours after the switch."""
        switch = today_until if tomorrow_from is None else tomorrow_from
        return today_until - 60 <= self.minutes < today_until or switch <= self.minutes < (
            switch + 180
        )

    def relative(self, offset: int) -> date:
        """Return the date for yesterday (-1), today (0) or tomorrow (1)."""
        if offset == 1 and self.overnight:
            return self._overnight_tomorrow()
        return self.today + _DAYS[offset]

    def _overnight_tomorrow(self) -> date:
        """The day "tomorrow" means, posted after midnight: the one that has begun.

        Written the evening before, "tomorrow" is the posting day. Early on a
        Sunday that day holds no school, so a closing for "tomorrow" is for the
        Monday the calendar names.
        """
        if self.today.weekday() == _SUNDAY:
            return self.today + _ONE_DAY
        return self.today

    def weekday(self, weekday: int, modifier: str | None) -> date:
        """Return the date a weekday name refers to.

        ``"week"`` is this week's ("Thursday this week"; from a weekend, the coming week's),
        even a day of it already past ("Monday this week" posted on a Wednesday).
        """
        if modifier is None or modifier not in _MOVED_MODIFIERS:
            first = self.today - _ONE_DAY if self.overnight else self.today
        elif modifier == "next":
            first = self.today + _ONE_DAY
        else:
            base = self.today - _ONE_DAY if self.overnight else self.today
            if base.weekday() >= _SATURDAY:
                return base + _DAYS[_WEEK - base.weekday() + weekday]
            return base + _DAYS[weekday] - _DAYS[base.weekday()]
        return first + _DAYS[(weekday - first.weekday()) % _WEEK]

    def days_ahead(self, weekday: int) -> int:
        """How many days after the posting day a weekday name alone falls (see :meth:`weekday`).

        From -1 (overnight: the day that has just ended) to 6.
        """
        if self.overnight:
            return (weekday - self.today.weekday() + 1) % _WEEK - 1
        return (weekday - self.today.weekday()) % _WEEK

    def _unclear(self, atom: DateAtom) -> bool:
        """Whether a weekday atom is "next <weekday>" with nothing yet to say which week."""
        return (
            atom[ATOM_MODIFIER] == "next"
            and atom[ATOM_DAY] is None
            and atom[ATOM_WEEKDAY] is not None
            and self.next_is_unclear(atom[ATOM_WEEKDAY])
        )

    def next_is_unclear(self, weekday: int) -> bool:
        """Whether "next <weekday>" could mean this week's or next week's.

        Posted on a school day (in the evening, for an overnight post) before that
        weekday comes round, "next Thursday" is read both ways. After it, or
        from a weekend, the coming one is meant.
        """
        base = self.today - _ONE_DAY if self.overnight else self.today
        return base.weekday() < _SATURDAY and weekday > base.weekday()

    def explicit(self, month: int | None, day: int, year: int | None) -> date | None:
        """Return the date for a month and day, choosing the nearest year if none is given.

        With no month it is a day of the month alone (see :meth:`day_of_month`).
        """
        if month is None:
            return self.day_of_month(day)
        if year is None:
            # Months more than half a year away belong to the neighbouring year.
            shift = month - self.today.month
            if shift not in {_HALF_YEAR, -_HALF_YEAR}:
                guess = self.today.year - (shift > _HALF_YEAR) + (shift < -_HALF_YEAR)
                try:
                    return date(guess, month, day)
                except ValueError:
                    # "2/29" in a year with no such day: no day at all, not one years off.
                    return None
        years = (
            (year,)
            if year is not None
            else (self.today.year - 1, self.today.year, self.today.year + 1)
        )
        candidates: list[date] = []
        for candidate_year in years:
            try:
                candidates.append(date(candidate_year, month, day))
            except ValueError:
                continue
        if not candidates:
            return None
        today = self.today
        nearest = candidates[0]
        for candidate in candidates[1:]:
            if abs((candidate - today).days) < abs((nearest - today).days):
                nearest = candidate  # (the first of the nearest, as min takes it)
        return nearest

    def day_of_month(self, day: int) -> date | None:
        """Return the date a day of the month written alone stands for ("the 27th").

        It is the first date with that number on or after the posting day, at
        most 30 days on: posted on January 30, "the 2nd" is February 2. A
        listing can stay up after its day has passed: a number that fell in the
        week before the posting day is that past day, not a day a month on
        ("closed through the 22nd" posted on the 23rd ran out yesterday). With
        no such date ("the 31st" posted on April 10) there is none: ``None``.
        """
        today = self.today
        past = ahead = None
        for shift in (-1, 0, 1):
            year, month = _month_shift(today, shift)
            try:
                candidate = date(year, month, day)
            except ValueError:
                continue
            gap = (candidate - today).days
            if -_DAY_NUMBER_PAST <= gap < 0:
                past = candidate
            elif 0 <= gap <= _DAY_NUMBER_AHEAD and ahead is None:
                ahead = candidate
        return ahead if past is None else past

    def run_from(self, start: date, group: DateGroup) -> Resolved | None:
        """The days of a run that goes on from ``start``, a day named before it, to the end
        its one atom names counted from that day: a weekday name alone, the first such day on
        or after it ("Wednesday, September 25, and remain closed through Friday": through the
        27th), or the rest of its week (unclear for "this week" or "all week" after a day of a
        later week, or after a weekend day of one). ``None`` for a run of any other form, which
        resolves as one from the posting day does."""
        atoms = group[GROUP_ATOMS]
        if len(atoms) != 1:
            return None
        atom = atoms[0]
        link = group[GROUP_OPEN_START]
        if atom[ATOM_KIND] == "week" and link is None:
            if start > self.week_end() and (
                start.weekday() > _FRIDAY or not atom[ATOM_REST_OF_WEEK]
            ):
                # "Closed 1/27. Closed this week.", "Closed Monday Jan 26. Closed all week.":
                # which week, after a day of a later week, cannot be told (see _add_week).
                unclear = Resolved()
                unclear.flags |= UNCLEAR
                return unclear
            if start.weekday() > _FRIDAY:
                return None
            last, link = start + _DAYS[_FRIDAY - start.weekday()], "range"
        elif (
            link in {"range", "until"}
            and _plain_weekday(atom)
            and atom[ATOM_MODIFIER] is None
            and not atom[ATOM_EVENING]
            and atom[ATOM_WEEKDAY] is not None
        ):
            last = start + _DAYS[(atom[ATOM_WEEKDAY] - start.weekday()) % _WEEK]
        else:
            return None
        result = Resolved()
        self._add_span(result, start, last, link)
        return result

    def week_end(self) -> date:
        """Return the Friday that ends the posting week (next week's, on a weekend)."""
        today = self.today
        if today.weekday() >= _SATURDAY:
            return today + timedelta(days=_WEEK - today.weekday() + _FRIDAY)
        return today + timedelta(days=_FRIDAY - today.weekday())

    def resolve(
        self, group: DateGroup, default: date | None = None, latest: date | None = None
    ) -> Resolved:
        """Return the local dates ``group`` stands for.

        ``default`` is the day an open start ("through Friday", "rest of the
        week", "until further notice") counts from; ``None`` means the next
        school day at or after the posting time, the posting day until noon.
        ``latest`` is the date of a
        weekday named later in the same text: weekday names here are moved back
        a week if needed so the text reads in date order ("Closed Monday; NTI
        Tuesday" posted on a Tuesday means yesterday and today).
        """
        result = Resolved()
        _start, _end, atoms, links, open_start = group
        if len(atoms) == 1 and open_start is None and (atom := atoms[0])[ATOM_KIND] != "week":
            point = self._point(atom, default, result, late_tomorrow=False)
            if latest is not None:
                point = self._not_after(atom, point, latest)
            if point is not None:
                result.dates.add(point)
            if atom[ATOM_MODIFIER] == "next" and self._unclear(atom):
                result.flags |= UNCLEAR
            return result
        led = False
        if "lead" in links:
            # "Closed today, Thursday and Friday": "today" named again, or a list it leads.
            led = links[0] == "lead"
            links = tuple(["appos" if link == "lead" else link for link in links])
            group = (_start, _end, atoms, links, open_start)
        if "appos" in links:
            if len(atoms) == 2:  # noqa: PLR2004 - one day named two ways
                pair = self._resolve_pair(group, default, latest)
                if pair is not None:
                    return pair
            rejoined = _rejoin_last_date(group)
            if rejoined is None:
                restated = self._resolve_restated(group, default, latest, led=led)
                if _other_day_restated(group):
                    # "Wednesday: Closed Thursday through Friday", "Jan. 21: Closed Jan. 22 and
                    # 23": two names of one kind for one day, neither of which can win.
                    restated.flags |= MISMATCH
                return restated
            group = rejoined
        self._resolve_into(result, group, default, latest, late_tomorrow=False)
        return result

    def _resolve_pair(
        self, group: DateGroup, default: date | None, latest: date | None
    ) -> Resolved | None:
        """Resolve one day named two ways: "tomorrow (Thursday)", "today, Jan. 21".

        The outcome of :meth:`_resolve_restated` for the common two-atom group,
        worked out directly; ``None`` for the forms that need the general path
        (an evening, a day number beside a weekday or "tomorrow", an impossible
        date).
        """
        atoms = group[GROUP_ATOMS]
        for atom in atoms:
            if atom[ATOM_EVENING] or (atom[ATOM_KIND] != "explicit" and atom[ATOM_DAY] is not None):
                return None
        flags = Resolved()
        points = [self._point(atom, default, flags, late_tomorrow=False) for atom in atoms]
        if latest is not None:
            points = [
                self._not_after(atom, point, latest)
                for atom, point in zip(atoms, points, strict=True)
            ]
        first, second = points
        if first is None or second is None:
            return None
        top = 0 if _EXPLICITNESS[atoms[0][ATOM_KIND]] > _EXPLICITNESS[atoms[1][ATOM_KIND]] else 1
        top_point = (first, second)[top]
        both, anchored = _anchor_pair(atoms, first, second)
        if flags.flags & OVERNIGHT and both != {top_point}:
            # Posted overnight, "tomorrow" beside the day after the one that has begun means it.
            late = [
                self._point(atom, default, Resolved(), late_tomorrow=True)
                if atom[ATOM_KIND] == "relative"
                else point
                for atom, point in zip(atoms, points, strict=True)
            ]
            late_both, late_anchored = _anchor_pair(atoms, late[0], late[1])
            if late_both == {top_point}:
                both, anchored = late_both, late_anchored
        flags.dates = {top_point}
        if both != flags.dates:
            flags.flags |= MISMATCH
        for index, atom in enumerate(atoms):  # (a loop costs less than any(), per call)
            # (The top day's, or one no other day anchors: see _unclear, which needs "next".)
            if (
                atom[ATOM_MODIFIER] == "next"
                and (index == top or index not in anchored)
                and self._unclear(atom)
            ):
                flags.flags |= UNCLEAR
                break
        return flags

    def _resolve_restated(
        self, group: DateGroup, default: date | None, latest: date | None, *, led: bool = False
    ) -> Resolved:
        """Resolve a group in which two kinds of day restate each other.

        The group reads as the days of its most explicit kind. Read with every
        restatement as a plain list, it must come to the same days (weekday
        names taking the week of a date or a relative day that has their
        weekday); otherwise the kinds disagree and the group is a mismatch.
        A day restated as itself ("Wednesday: Closed Wednesday and Thursday")
        is read once. With ``led``, a comma joined its first two days ("today,
        Thursday and Friday"), so it can be a list instead (see :meth:`_led_run`).
        """
        group = _without_repeats(group)
        if "appos" not in group[GROUP_LINKS]:
            result = Resolved()
            self._resolve_into(result, group, default, latest, late_tomorrow=False)
            return result
        top_kind = max(
            (atom[ATOM_KIND] for atom in group[GROUP_ATOMS] if atom[ATOM_KIND] in _EXPLICITNESS),
            key=_EXPLICITNESS.__getitem__,
        )
        top = self._resolve_kind(group, top_kind, default, latest)
        listed: DateGroup = (
            *group[:3],
            tuple("list" if link == "appos" else link for link in group[GROUP_LINKS]),
            group[4],
        )
        whole = Resolved()
        self._resolve_into(whole, listed, default, latest, late_tomorrow=False, anchor=True)
        if whole.dates != top.dates and whole.flags & OVERNIGHT:
            # Posted overnight, "tomorrow" beside the day after the one that has begun means it.
            late = Resolved()
            self._resolve_into(late, listed, default, latest, late_tomorrow=True, anchor=True)
            if late.dates == top.dates:
                whole = late
                whole.flags |= OVERNIGHT
        top.flags |= whole.flags
        if whole.dates != top.dates:
            run = self._led_run(group, default, latest) if led else None
            if run is not None:
                return run  # "Closed today, Thursday and Friday": a list, not a restatement
            top.flags |= MISMATCH
        elif self._pair_disagrees(group, default, latest, top.dates):
            top.flags |= MISMATCH
        return top

    def _pair_disagrees(
        self, group: DateGroup, default: date | None, latest: date | None, days: set[date]
    ) -> bool:
        """Whether a relative day and a weekday name that restate each other disagree, or
        name a day the group's ``days`` leave out.

        The days of the whole group can hide it: "Closed today (Friday) and
        Monday" posted on a Monday comes to Friday and Monday read either way,
        though "today" is no Friday; and posted overnight, "tomorrow (Tuesday),
        Friday and Monday" agrees on Tuesday the 20th while the weekdays as a run
        end on the posting day. A list restating a list ("today and tomorrow
        (Wednesday and Thursday)") is compared as a whole only.
        """
        atoms, links = group[GROUP_ATOMS], group[GROUP_LINKS]
        for index, link in enumerate(links):
            if link != "appos":
                continue
            left, right = atoms[index], atoms[index + 1]
            if {left[ATOM_KIND], right[ATOM_KIND]} != _RELATIVE_AND_WEEKDAY:
                continue
            if _run_length(atoms, index, -1) == _run_length(atoms, index + 1, 1) > 1:
                continue  # (a list named again, day by day)
            pair: DateGroup = (left[ATOM_START], right[ATOM_END], (left, right), ("appos",), None)
            resolved = self._resolve_pair(pair, default, latest)
            if resolved is not None and (resolved.flags & MISMATCH or not resolved.dates <= days):
                return True
        return False

    def _led_run(
        self, group: DateGroup, default: date | None, latest: date | None
    ) -> Resolved | None:
        """The days of a relative day that leads a list of weekday names, when they make a run.

        "Closed today, Thursday and Friday" posted on a Wednesday lists three
        days, as "Closed today, tomorrow and Friday" does: the comma after
        "today" reads as a restatement only when the weekday after it is that
        day (see :meth:`_resolve_restated`). Read as a list, the days must be
        school days one after another, in the order written ("Closed tomorrow,
        Friday and Monday" posted on a Wednesday), the relative day the first of
        them; any other reading ("Closed today, Friday and Monday", "Closed
        tomorrow, Wednesday and Thursday", "Closed tomorrow, Monday and Tuesday"
        posted on a Friday, when tomorrow is a Saturday) stays a mismatch.
        ``None`` when the group is not of that form, or its days make no such
        run. Only a plain comma after the relative day starts such a list (see
        :func:`_leads_list`): "Closed today (Thursday) and Friday" names today
        again, and stays a mismatch. (Whether the words after the list leave its
        days to the status before it is the parser's call: see
        ``parse._carried_elsewhere``.)
        """
        atoms, links = group[GROUP_ATOMS], group[GROUP_LINKS]
        if (
            len(atoms) < 3  # noqa: PLR2004 - a relative day and two weekday names at least
            or group[GROUP_OPEN_START] is not None
            or atoms[0][ATOM_KIND] != "relative"
            or atoms[0][ATOM_DAY] is not None
            or links[0] != "appos"
            or any(link != "list" for link in links[1:])
            or not all(_plain_weekday(atom) and atom[ATOM_MODIFIER] is None for atom in atoms[1:])
        ):
            return None
        result = Resolved()
        points = [self._point(atom, default, result, late_tomorrow=False) for atom in atoms]
        if latest is not None:
            points = [
                self._not_after(atom, point, latest)
                for atom, point in zip(atoms, points, strict=True)
            ]
        previous = points[0]
        if previous is None or previous.weekday() >= _SATURDAY:
            # "Closed tomorrow, Monday and Tuesday" posted on a Friday: a run starts on a
            # school day, and a Saturday or a Sunday is no run's first day.
            return None
        for point in points[1:]:
            if point is None or point != previous + _TO_SCHOOL_DAY[True][previous.weekday()]:
                return None
            previous = point
        listed: DateGroup = (*group[:3], ("list", *links[1:]), group[GROUP_OPEN_START])
        self._resolve_into(result, listed, default, latest, late_tomorrow=False)
        return result

    def _resolve_kind(
        self, group: DateGroup, kind: AtomKind, default: date | None, latest: date | None
    ) -> Resolved:
        """Resolve only the atoms of one kind, joined as they are joined in ``group``."""
        indexes = [
            index for index, atom in enumerate(group[GROUP_ATOMS]) if atom[ATOM_KIND] == kind
        ]
        links: list[Link] = []
        for left, right in pairwise(indexes):
            joins = [link for link in group[GROUP_LINKS][left:right] if link != "appos"]
            links.append(joins[-1] if joins else "list")
        atoms = tuple(group[GROUP_ATOMS][index] for index in indexes)
        sub: DateGroup = (
            atoms[0][ATOM_START],
            atoms[-1][ATOM_END],
            atoms,
            tuple(links),
            group[GROUP_OPEN_START] if indexes[0] == 0 else None,
        )
        result = Resolved()
        self._resolve_into(result, sub, default, latest, late_tomorrow=False)
        return result

    def _resolve_into(  # noqa: PLR0913 - the resolution options are independent switches
        self,
        result: Resolved,
        group: DateGroup,
        default: date | None,
        latest: date | None,
        *,
        late_tomorrow: bool,
        anchor: bool = False,
    ) -> None:
        points = [self._point(atom, default, result, late_tomorrow) for atom in group[GROUP_ATOMS]]
        if latest is not None:
            points = [
                self._not_after(atom, point, latest)
                for atom, point in zip(group[GROUP_ATOMS], points, strict=True)
            ]
        self._align_runs(group, points)
        moved: list[DateAtom] | None = None  # the week atoms that go on from the day before
        for index in range(1, len(points)):
            # "Closed tomorrow and the rest of the week": the rest of the week after the day
            # named before it, not from the posting day. ("Closed tomorrow and all week" is the
            # posting week, as "all week" alone is, unless the day is of a later week.)
            previous = points[index - 1]
            if (
                (atom := group[GROUP_ATOMS][index])[ATOM_KIND] == "week"
                and previous is not None
                and (point := points[index]) is not None
                and point < previous
                and (atom[ATOM_REST_OF_WEEK] or previous > self.week_end())
            ):
                if (
                    index == 1
                    and group[GROUP_OPEN_START] is not None
                    and previous > self.week_end()
                ):
                    # "Closed through Monday - remainder of the week": the week after a run's
                    # last day, of a later week, says which week no more than "all week" does.
                    result.flags |= UNCLEAR
                points[index] = previous
                moved = [*(moved or ()), group[GROUP_ATOMS][index]]
        anchored = self._anchor_weekdays(group, points) if anchor else set()
        if not anchor and _backward(group, points):
            result.flags |= UNCLEAR
        for index, atom in enumerate(group[GROUP_ATOMS]):
            if self._unclear(atom) and index not in anchored:
                result.flags |= UNCLEAR
                break
        if group[GROUP_OPEN_START] == "first":
            result.dates.add(self._start(default))  # the day the run starts, alone
            return
        self._add_points(result, group, points, default)
        for atom, point in zip(group[GROUP_ATOMS], points, strict=True):
            if atom[ATOM_KIND] == "week" and point is not None:
                self._add_week(result, atom, point, later=moved is not None and atom in moved)

    def _add_week(self, result: Resolved, atom: DateAtom, point: date, *, later: bool) -> None:
        """Add the days of a week atom from ``point``, its day: the rest of the posting week.
        A day past its end is no day of it, unless the week goes on from a day of a later week
        named before it (``later``): "Closed Monday Jan 26 and the rest of the week" is the rest
        of that day's week, as a run after a day named before it is (see run_from). Which week
        "this week" or "all week" after such a day is, or the rest of the week after a weekend
        day of a later week, cannot be told."""
        end = self.week_end()
        if point > end:
            if not later:
                result.flags |= INVALID
                result.dates.discard(point)
                return
            if point.weekday() > _FRIDAY or not atom[ATOM_REST_OF_WEEK]:
                result.flags |= UNCLEAR
                return
            end = point + _DAYS[_FRIDAY - point.weekday()]
        self._add_span(result, point, end, "range")

    def _add_points(
        self, result: Resolved, group: DateGroup, points: list[date | None], default: date | None
    ) -> None:
        """Add the days a group's placed points stand for: each point, or the run it ends."""
        first = 0
        if group[GROUP_OPEN_START] is not None and points[0] is not None:
            start = self._start(default)
            if (
                group[GROUP_OPEN_START] == "until"
                and points[0] <= start
                and group[GROUP_ATOMS][0][ATOM_KIND] == "weekday"
            ):
                # "Closed until Monday" posted on a Monday, or after "Closed Tuesday": this
                # Monday, which leaves no day, or the next one.
                result.flags |= UNCLEAR
                return
            self._add_span(result, start, points[0], group[GROUP_OPEN_START], open_start=True)
            first = 1
        for index in range(first, len(points)):
            point = points[index]
            if point is None:
                continue
            previous = points[index - 1] if index > 0 else None
            link = group[GROUP_LINKS][index - 1] if index > 0 else "list"
            if link == "first":
                break  # the rest of the run only placed the days before it
            if link in {"range", "until"} and previous is not None:
                self._add_span(result, previous, point, link)
            else:
                result.dates.add(point)

    def _not_after(self, atom: DateAtom, point: date | None, latest: date) -> date | None:
        if not _plain_weekday(atom) or atom[ATOM_MODIFIER] == "next" or point is None:
            return point
        return self._back_to(point, latest)

    def _back_to(self, point: date, latest: date) -> date:
        """``point`` moved back a week at a time while after ``latest``, to 6 days before today."""
        earliest = self.today - _DAYS[_WEEK - 1]
        while point > latest and point - _DAYS[_WEEK] >= earliest:
            point -= _DAYS[_WEEK]
        return point

    def weekday_by(self, weekday: int, modifier: str | None, latest: date | None) -> date:
        """Return the date a weekday name alone refers to, named before a day on ``latest``.

        As :meth:`weekday`, but kept in the text's order as :meth:`resolve` keeps
        it: moved back a week at a time while after ``latest``, no further than 6
        days before the posting day. "Next" looks ahead and is not moved.
        """
        point = self.weekday(weekday, modifier)
        if latest is None or modifier == "next":
            return point
        return self._back_to(point, latest)

    @staticmethod
    def _align_runs(group: DateGroup, points: list[date | None]) -> None:
        """Place weekday names listed or ranged together in one run of days.

        The run ends on the last name's own date ("Monday and Tuesday" posted on
        a Tuesday is yesterday and today), or starts on the first one's when it
        says "next" or "this" ("next Monday and Tuesday"). A weekday name that
        starts a range to a relative day ends up on or before that end, and one
        that starts a range to a date ends up before it ("Wednesday through
        January 28", a Wednesday, is eight days).
        """
        atoms = group[GROUP_ATOMS]
        index = 0
        while index < len(atoms):
            last = index
            while (
                last + 1 < len(atoms)
                and _plain_weekday(atoms[last])
                and _plain_weekday(atoms[last + 1])
                and atoms[last + 1][ATOM_MODIFIER] is None
                and group[GROUP_LINKS][last] in _RUN_LINKS
            ):
                last += 1
            if last > index and atoms[index][ATOM_MODIFIER] is not None:
                for position in range(index + 1, last + 1):
                    Calendar._place(group, points, position, forward=True)
            else:
                for position in range(last - 1, index - 1, -1):
                    Calendar._place(group, points, position, forward=False)
            index = last + 1
        # From the end: a weekday name that starts a range to another kind of day, or a
        # list or range of them that ends on a dated weekday ("Wednesday, Thursday and
        # Friday, January 23"), is placed back from that day.
        placed = False
        for position in range(len(atoms) - 2, -1, -1):
            link, follows = group[GROUP_LINKS][position], atoms[position + 1]
            if follows[ATOM_KIND] in {"weekday", "week"}:
                placed = placed and _plain_weekday(follows) and link in _RUN_LINKS
            elif follows[ATOM_KIND] == "explicit" and follows[ATOM_WEEKDAY] is not None:
                placed = link in _RUN_LINKS
            else:
                placed = link in {"range", "until", "first"}
            placed = placed and _plain_weekday(atoms[position])
            if placed:
                Calendar._place(group, points, position, forward=False)

    @staticmethod
    def _place(
        group: DateGroup, points: list[date | None], position: int, *, forward: bool
    ) -> None:
        """Move one weekday name next to its neighbour in a run (see :meth:`_align_runs`)."""
        anchor_at = position - 1 if forward else position + 1
        anchor, own = points[anchor_at], group[GROUP_ATOMS][position][ATOM_WEEKDAY]
        if anchor is None or own is None or points[position] is None:
            return  # an evening ("Sunday evening and Monday") names no school day to place
        link = group[GROUP_LINKS][min(position, anchor_at)]
        if forward:
            step = (own - anchor.weekday()) % _WEEK
            points[position] = anchor + _DAYS[step or (_WEEK if link == "list" else 0)]
        else:
            # "Wednesday through January 28" (a Wednesday) is a week, not one day; but
            # "Wednesday through tomorrow" posted on a Tuesday is only Wednesday.
            full = link == "list" or _dated(group, anchor_at)
            step = (anchor.weekday() - own) % _WEEK
            points[position] = anchor - _DAYS[step or (_WEEK if full else 0)]

    @staticmethod
    def _anchor_weekdays(group: DateGroup, points: list[date | None]) -> set[int]:
        """Give each weekday name the date of a date or relative day in the group with its weekday.

        Return the positions of the names so placed.
        """
        fixed = [
            point
            for atom, point in zip(group[GROUP_ATOMS], points, strict=True)
            if point is not None and atom[ATOM_KIND] in {"explicit", "relative"}
        ]
        anchored: set[int] = set()
        for position, atom in enumerate(group[GROUP_ATOMS]):
            point = points[position]
            if not _plain_weekday(atom) or point is None:
                continue
            same = [day for day in fixed if day.weekday() == atom[ATOM_WEEKDAY]]
            if same:
                points[position] = min(same, key=lambda day: (abs((day - point).days), day))
                anchored.add(position)
        return anchored

    def _point(  # noqa: PLR0911 - one return per atom kind
        self, atom: DateAtom, default: date | None, result: Resolved, late_tomorrow: bool
    ) -> date | None:
        (
            _start, _end, kind, weekday, month, day, year, offset, modifier, _rest, _inner,
            _named, evening,
        ) = atom  # fmt: skip
        if evening:
            result.flags |= EVENING
            return None
        if kind == "relative":
            if offset == 1 and self.overnight:
                result.flags |= OVERNIGHT
                point = self.today + _ONE_DAY if late_tomorrow else self.relative(1)
            else:
                point = self.relative(offset)
            return self._check_day(atom, point, result)
        if kind == "weekday" and weekday is not None:
            point = self.weekday(weekday, modifier)
            if modifier == "next" and day is not None and self.next_is_unclear(weekday):
                # "Next Thursday the 29th" posted on a Tuesday: the day number says which.
                later = point + _DAYS[_WEEK]
                if day == later.day:
                    return later
            return self._check_day(atom, point, result)
        if kind == "week":
            return self._start(default)
        if kind == "further_notice":
            result.flags |= FURTHER_NOTICE
            return None
        if kind == "recurring":
            result.flags |= RECURRING
            return None
        # Explicit atoms always carry a day, and a month unless the day stands alone ("the
        # 27th"); 0 (never valid) keeps the types total.
        found = self.explicit(month, day or 0, year)
        if found is None:
            result.flags |= INVALID
        elif weekday is not None and weekday != found.weekday():
            result.flags |= MISMATCH
        return found

    @staticmethod
    def _check_day(atom: DateAtom, point: date, result: Resolved) -> date | None:
        """Check a weekday or relative day against the day number written with it.

        A weekday with a day number names the date with that number that falls
        on that weekday, from a week before the weekday's own date to a month
        after it: "Wednesday the 28th" posted on Tuesday, January 20 is January
        28, a week later than the nearest Wednesday. When no such date exists
        (or the day is "tomorrow"), the two disagree and the day number wins:
        the date with that number nearest the named day.
        """
        if atom[ATOM_DAY] is None or atom[ATOM_DAY] == point.day:
            return point
        candidates: list[date] = []
        for shift in (-1, 0, 1):
            year, month = _month_shift(point, shift)
            try:
                candidates.append(date(year, month, atom[ATOM_DAY]))
            except ValueError:
                continue
        nearest = sorted(candidates, key=lambda day: (abs((day - point).days), day))
        if atom[ATOM_KIND] == "weekday":
            earliest = point - _DAYS[_WEEK]
            for day in nearest:
                if day.weekday() == atom[ATOM_WEEKDAY] and day >= earliest:
                    return day
        result.flags |= MISMATCH
        if not nearest:
            result.flags |= INVALID
            return None
        return nearest[0]

    def _add_span(
        self, result: Resolved, first: date, last: date, link: Link, *, open_start: bool = False
    ) -> None:
        """Add the school days from ``first`` through ``last`` (or until it, not counting it).

        An open start ("until Jan. 20" posted on the 20th) that ends before it
        begins is just its last day. Between two named days, "tomorrow until
        Wednesday" posted on a Tuesday leaves nothing between them: it may mean next
        Wednesday, so the days are unclear.
        """
        if link == "until":
            last -= _ONE_DAY
        if last < first:
            if not open_start:
                result.flags |= UNCLEAR
                return
            first = last
        if (last - first).days > _LONGEST_RANGE_DAYS:
            result.flags |= INVALID
            result.dates.add(first)
            return
        result.dates.update(_school_days(first, last))
