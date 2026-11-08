"""Self-dated rows: the weekdays or dates a row's status words name as the days they are for.

A row whose posting time is unknown (no row stamp near its first sighting and ``lo``
unknown: ``UNKNOWN_START``) is held back, since its words could be left over from an
earlier day. A status that names its own weekday ("Closed Thursday") or date ("Closed Nov.
5") carries its day, so the resolver (:mod:`snowlight.live.resolve`) dates such a row by it
when it is the school's local today at the first sighting, or tomorrow on an evening read.
:func:`named_weekdays` says which weekdays the words name, :func:`names_date` whether they
state a date and :func:`stamp_dates` which dates their stamps give; all are pure and read
only the status words. The weekday spellings are the reader's own
(:data:`snowlight.classify.dates.WEEKDAYS`: "Weds", "Thurs"), so a weekday is read here
exactly when the reader reads it.

The words name no weekday for this rule, and the row stays held as before, when:

* they hold an explicit date (a month and day, a numeric or ISO date, an ordinal day):
  the date wins over a weekday; or a date in a form not read here ("29 October", "10-29",
  "10.29" or "29.10", "20261029", "(29)", a month alone), which names no day for this rule
  either;
* they hold a relative day word ("today", "tonight", "tomorrow", "this week", "next",
  "weekend", "3 days ago"): its meaning depends on the posting time, which is unknown; or a
  word that puts the status before ("previously", "earlier", "was");
* a weekday follows, in its clause, a word that makes it the end or another day than the
  one closed ("until Thursday", "reopens on Thursday", "back to school Thursday",
  "through Thursday", "next Thursday", "after Thursday", "instead of Friday", "rather
  than Friday", "not Friday", "moved to Friday"), starts a span ("Mon-Wed", "Monday to
  Friday"), or is followed by a day number ("Thursday 29", "Thursday #29": another week's);
* a weekday is part of a holiday's name ("Ash Wednesday", "Black Friday", "Good
  Friday", "Friday holiday");
* a weekday may be part of a proper name: in words with both cases, it is followed by a
  capitalised word that is no status, date, time or connective word ("Friday Harbor
  schools closed", "Monday Creek campus closed") or is a status word that also names a
  school ("Friday School closed"); in words of one case, where case tells nothing, by any
  such word ("closed friday harbor", "FRIDAY SCHOOL CLOSED"); or it follows a place word
  ("St. Friday", "Lake Monday").

A weekday the row's name holds ("Friday Harbor SD") is never read from the words, and the
resolver drops too every weekday a directory name of the row's schools or matched record
holds (:func:`weekdays_in`). A weekday or date inside a stamp ("Updated Wednesday 9:00 PM",
"Posted 10/29") never names the day the row is for: it is when the row was written, which
:func:`stamp_dates` reads, and the resolver bounds the row by it as by its row date (a
stamp from a week before the day, after the read, or with a day it cannot read exactly
keeps the hold). A stamp is read over all the words the weekday rule leaves out as a stamp
(to the first ".", ";" or "|", across lines; a date or time that runs on past a "." is read
whole: "Oct. 29"), passing over words that give no day ("Posted by the district on 10/29");
any number, month, weekday or relative day word in it that it cannot read makes it
unreadable. Words left in the status words that date it from its posting ("3 days ago")
are relative day words. The same guards keep a
date from dating its row: "Closed until Nov. 5", "Classes resume Nov. 5" and "Closed
Nov. 5-6" state no date for this rule.

A date is stated when the words hold it as a month and day ("Nov. 5", "November 5th,
2026"), a numeric date ("11/5", "11/5/26") or an ISO date, with no other year (after it:
"Nov. 5, 2025", "Nov. 5 '25"); a day number alone ("the 5th") states none here.
"""

import re
from collections.abc import Iterable
from datetime import date, timedelta
from functools import lru_cache
from typing import Final

from snowlight.classify.dates import WEEKDAYS as READER_WEEKDAYS
from snowlight.replays.gates import MONTHS, STAMP_PHRASE

SATURDAY: Final = 5
_SPELLINGS: Final = tuple(
    "|".join(
        sorted((word for word, day in READER_WEEKDAYS.items() if day == number), key=len)[::-1]
    )
    for number in range(7)
)
"""Each weekday's spellings the reader reads, Monday first, longest first."""
_WEEKDAY: Final = re.compile(
    "|".join(
        # an all-caps "SAT" is the test, not Saturday (as in replays.gates.WEEKDAYS)
        rf"(?P<w{number}>\b{r'(?!(?-i:SAT)\b)' if number == SATURDAY else ''}"
        rf"(?:{words})\b\.?)"
        for number, words in enumerate(_SPELLINGS)
    ),
    re.IGNORECASE,
)
_EXPLICIT_DATE: Final = re.compile(
    rf"\b(?:{'|'.join(MONTHS)})\.?\s*\d{{1,2}}(?!\d)"
    r"|(?<![\d/])\d{1,2}/\d{1,2}(?![\d])"
    r"|\b\d{4}-\d{2}-\d{2}\b"
    r"|\b\d{1,2}(?:st|nd|rd|th)\b",
    re.IGNORECASE,
)
"""A date stated in the words: it wins over any weekday."""
_OTHER_DATE: Final = re.compile(
    rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{'|'.join(MONTHS)})\b"
    r"|(?<![\d-])(?:0?[1-9]|1[0-2])-(?:0?[1-9]|[12]\d|3[01])(?:-\d{2,4})?(?![\d-])"
    r"|(?<![\d.])(?:0?[1-9]|[12]\d|3[01])\.(?:0?[1-9]|[12]\d|3[01])(?:\.\d{2,4})?(?![\d.])"
    r"(?!\s*(?:hours?|hrs?|h)\b)"
    r"|\(\s*(?:0?[1-9]|[12]\d|3[01])\s*\)"
    r"|\b20\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\b"
    rf"|\b(?!(?i:may|march)\b)(?:{'|'.join(MONTHS)})\b(?!\.?\s*\d)",
    re.IGNORECASE,
)
"""A date in a form no rule here reads ("29 October", "10-29", "10.29" or "29.10",
"20261029", a day number in parentheses "(29)", a month alone): it may name another day, so
the words name no weekday or date for this rule."""
_DAY_NUMBER_AFTER: Final = re.compile(
    r"[\s,]{0,3}(?:the\s+|no\.?\s*)?#?\s*(?:0?[1-9]|[12]\d|3[01])(?![\d:]|\.\d)"
    r"(?!\s*(?:-?\s*(?:hours?|hrs?|h|minutes?|mins?)\b|[ap]\.?\s?m\b))",
    re.IGNORECASE,
)
"""A day number right after a weekday ("Thursday 29", "Thursday #29", "Thursday, the 29"),
no clock time or delay length: the weekday may be another week's."""
_RELATIVE: Final = re.compile(
    r"\b(?:today|tonight|tomorrow|yesterday|this\s+(?:morning|afternoon|evening|week)|"
    r"next|last|weekend|week|ago|previously|earlier|was)\b",
    re.IGNORECASE,
)
"""Day words whose meaning depends on when the row was posted, and words that put the
status before it ("previously", "earlier", "was")."""
_CLAUSE: Final = re.compile(r"[.;,:/|!?()\n]")
"""What ends a clause: the words before a weekday are read back to the last of these."""
_END_WORDS: Final = re.compile(
    r"\b(?:until|till|til|through|thru|reopen\w*|re-open\w*|return\w*|resum\w*|back|"
    r"after|before|since|from|starting|beginning|begin\w*|start\w*|next|last|this|by|"
    r"instead|rather|place\s+of|lieu|not|except\w*|other\s+than|moved|rescheduled|"
    r"postponed|pushed|switched|swapped|replac\w*)\b",
    re.IGNORECASE,
)
"""Words before a weekday in its clause that make it the end or another day than the one
closed ("reopens on Thursday", "back to school Thursday", "next Thursday", "instead of
Friday", "rather than Friday", "not Friday", "moved to Friday")."""
_HOLIDAY_BEFORE: Final = re.compile(
    r"\b(?:ash|black|good|holy|maundy|cyber|easter|palm|fat|super|shrove|giving)\W{1,3}$",
    re.IGNORECASE,
)
"""A word just before a weekday that makes it a holiday's name ("Ash Wednesday")."""
_SPAN_AFTER: Final = re.compile(r"^\s*(?:-|\u2013|\u2014|to\b|through\b|thru\b)", re.IGNORECASE)
"""Words just after a weekday that make it the first day of a span ("Mon-Wed")."""
_HOLIDAY_AFTER: Final = re.compile(r"^\s+(?:of\s+service|holiday|break|sale)\b", re.IGNORECASE)
"""Words just after a weekday that make it a holiday or a break ("Friday holiday")."""
_YEAR_AFTER: Final = re.compile(r",?\s*(?:['\u2018\u2019`]\s?(?P<short>\d{2})|(?P<long>\d{4}))\b")
"""A year just after a date: "Nov. 5, 2025", "Nov. 5 '25"."""


def _not_the_day(words: str, found: re.Match[str]) -> bool:
    """Whether the day ``found`` in ``words`` (a weekday or a date) is not the day they are
    for: an end word in its clause before it ("until", "reopens", "back"), a holiday's name
    around it, or the start of a span."""
    before, after = words[: found.start()], words[found.end() :]
    return bool(
        _END_WORDS.search(_CLAUSE.split(before)[-1])
        or _HOLIDAY_BEFORE.search(before)
        or _SPAN_AFTER.search(after)
        or _HOLIDAY_AFTER.search(after)
    )


def _weekday_of(found: re.Match[str]) -> int:
    return next(number for number in range(len(_SPELLINGS)) if found.group(f"w{number}"))


def weekdays_in(names: Iterable[str]) -> frozenset[int]:
    """The weekdays (Monday 0) any of ``names`` holds as a word ("Friday Harbor SD": Friday):
    a weekday a directory name of the row's schools or districts holds is never read from
    its words."""
    return frozenset(_weekday_of(found) for name in names for found in _WEEKDAY.finditer(name))


_NEXT_WORD: Final = re.compile(r"[ \t]+(?P<word>[^\W\d_][\w'\u2019-]*)")
"""The word right after a weekday, with nothing but spaces between (no clause mark)."""
_PLAIN_AFTER: Final = frozenset(
    {
        # status words
        "closed", "closing", "closings", "closure", "closures", "close", "cancel", "canceled",
        "cancelled", "cancels", "cancellation", "cancellations", "delay", "delayed", "delays",
        "late", "start", "starts", "early", "dismissal", "dismissed", "dismissing", "release",
        "released", "out", "off", "remote", "virtual", "online", "e-learning", "elearning",
        "nti", "ami", "flex", "flexible", "learning", "instruction", "no", "school", "schools",
        "class", "classes", "activities", "activity", "events", "event", "sports", "athletics",
        "practice", "practices", "programs", "program", "open", "opening", "opens", "normal",
        "regular", "schedule", "session", "sessions", "bus", "buses", "routes", "transportation",
        "students", "staff", "day", "days", "all", "hour", "hours", "two", "one", "three",
        "half", "snow", "weather", "storm", "emergency", "inclement", "make-up", "makeup",
        "distance", "teachers", "both",
        # date and time words
        "morning", "afternoon", "evening", "night", "noon", "am", "pm", "a", "p", "only",
        # connective words
        "and", "or", "but", "due", "for", "because", "with", "as", "also", "plus", "too", "at",
        "in", "the", "is", "are", "will", "be", "to",
    }
    | set(READER_WEEKDAYS)
    | {"jan", "january", "feb", "february", "mar", "march", "apr", "april", "may", "jun",
       "june", "jul", "july", "aug", "august", "sep", "sept", "september", "oct", "october",
       "nov", "november", "dec", "december"}
)  # fmt: skip
"""Words that may follow a weekday the words are for: status, date and time words and
connective words. Another word right after a weekday can make the weekday part of a proper
name ("Friday Harbor", "Monday Creek", "Sunday River")."""
_NAME_AFTER: Final = frozenset(
    {"school", "schools", "academy", "preschool", "learning", "day", "early"}
)
"""Words after a weekday that are status words but also name a school ("Friday School",
"Monday Learning Center", "Sunday Day School"): capitalised in words of both cases, or in
words of one case, they may make the weekday part of a proper name."""
_PLACE_BEFORE: Final = re.compile(
    r"\b(?:st|ste|saint|mt|mount|ft|fort|port|lake|cape|camp|glen|point|east|west|north|"
    r"south|new|old|upper|lower)\.?\s+$",
    re.IGNORECASE,
)
"""A word just before a weekday that makes it part of a place's name ("St. Friday")."""


def _in_a_name(words: str, found: re.Match[str], *, mixed: bool) -> bool:
    """Whether the weekday ``found`` in ``words`` may be part of a proper name: a place word
    before it, or a word after it that is no status, date, time or connective word or is one
    that also names a school (:data:`_NAME_AFTER`; in mixed-case words, only a capitalised
    one: "Friday Harbor" and "Friday School", not "Friday harbor" or "Friday school")."""
    if _PLACE_BEFORE.search(words[: found.start()]):
        return True
    after = _NEXT_WORD.match(words, found.end())
    if after is None:
        return False
    word = after.group("word")
    if mixed and not word[0].isupper():
        return False
    folded = word.casefold().rstrip(".")
    return folded in _NAME_AFTER or folded not in _PLAIN_AFTER


def named_weekdays(text: str, name: str = "") -> frozenset[int]:
    """The weekdays (Monday 0) the status words ``text`` name as the days they are for, or
    none when the words cannot date their row by a weekday (see the module).

    ``name`` is the row's name: a weekday it holds is never read from ``text``.
    """
    words = STAMP_PHRASE.sub(" ", text)
    if _EXPLICIT_DATE.search(words) or _OTHER_DATE.search(words) or _RELATIVE.search(words):
        return frozenset()
    in_name = weekdays_in([name])
    letters = [char for char in words if char.isalpha()]
    mixed = any(char.isupper() for char in letters) and any(char.islower() for char in letters)
    named: set[int] = set()
    for found in _WEEKDAY.finditer(words):
        if (
            _not_the_day(words, found)
            or _in_a_name(words, found, mixed=mixed)
            or _DAY_NUMBER_AFTER.match(words, found.end())
        ):
            return frozenset()
        weekday = _weekday_of(found)
        if weekday not in in_name:
            named.add(weekday)
    return frozenset(named)


def _status_words(text: str, name: str) -> str:
    """``text`` without its stamps and without the row's name, case-folded."""
    words = STAMP_PHRASE.sub(" ", text).casefold()
    named = name.strip().casefold()
    return words.replace(named, " ") if named else words


def states_a_date(text: str, name: str = "") -> bool:
    """Whether the status words ``text`` hold an explicit date (see the module)."""
    return _EXPLICIT_DATE.search(_status_words(text, name)) is not None


@lru_cache(maxsize=1024)
def _date_patterns(day: date) -> re.Pattern[str]:
    month = MONTHS[day.month - 1]
    return re.compile(
        rf"\b(?:{month})\.?\s*0?{day.day}(?:st|nd|rd|th)?(?!\d)(?:,?\s*(?P<year>\d{{4}})\b)?"
        rf"|(?<![\d/])0?{day.month}/0?{day.day}(?:/(?P<numeric_year>\d{{4}}|\d{{2}}))?(?![\d/])"
        rf"|\b{day.isoformat()}\b",
        re.IGNORECASE,
    )


def names_date(text: str, day: date, name: str = "") -> bool:
    """Whether the status words ``text`` state ``day`` as an explicit date (a month and day,
    a numeric date or an ISO date) in no other year ("Nov. 5, 2025" and "Nov. 5 '25" are
    another year's); ``name`` is the row's name, which is never read.

    No date counts when any date in the words is guarded as a weekday is (see the module):
    "Closed until Nov. 5", "Classes resume Nov. 5", "Closed through Nov. 5" and "Nov. 5-6"
    name no day here, the end word making it the end or another day than the one closed.
    """
    words = _status_words(text, name)
    if _OTHER_DATE.search(words) or any(
        _not_the_day(words, found) for found in _EXPLICIT_DATE.finditer(words)
    ):
        return False
    for found in _date_patterns(day).finditer(words):
        year = found.group("year") or found.group("numeric_year")
        if year is None and (after := _YEAR_AFTER.match(words, found.end())) is not None:
            year = after.group("short") or after.group("long")
        if year is None or int(year) in {day.year, day.year % 100}:
            return True
    return False


_STAMP_WORD: Final = re.compile(STAMP_PHRASE.pattern.removesuffix(r"[^.;|]*"), re.IGNORECASE)
"""The words that start a stamp in the row's words (:data:`STAMP_PHRASE`'s)."""
_STAMP_OTHER: Final = re.compile(r"[^\W\d_]+|[^.;|]")
"""A word or character a stamp holds that gives no day ("by", "the district", "per")."""
_STAMP_SEP: Final = re.compile(r"(?:[\s:,(\-\u2013\u2014]+|(?:on|at)\b|t(?=\d))", re.IGNORECASE)
_STAMP_CLOCK: Final = re.compile(
    r"(?:\d{1,2}(?::\d{2}){0,2}\s*[ap]\.?\s?m\b\.?|\d{1,2}:\d{2}(?::\d{2})?(?!\d)|noon\b|"
    r"midnight\b)(?:\s*\(?(?:[ecmp][sd]?t|ak[sd]?t|h[sd]?t|gmt|utc)\b\)?)?",
    re.IGNORECASE,
)
"""A clock time, with its US zone (the reader's, :mod:`snowlight.classify.text`; never a
month: "5:30 AM Oct. 29"): it bounds no day."""
_STAMP_WORDED: Final = re.compile(
    rf"(?P<month>{'|'.join(MONTHS)})\.?\s*(?P<day>\d{{1,2}})(?:st|nd|rd|th)?(?!\d)"
    r"(?:,?\s*(?P<year>\d{4})\b|\s*['\u2018\u2019`]\s?(?P<short>\d{2})\b)?",
    re.IGNORECASE,
)
_STAMP_NUMERIC: Final = re.compile(
    r"(?P<month>\d{1,2})/(?P<day>\d{1,2})(?:/(?P<year>\d{4}|\d{2}))?(?![\d/])"
)
_STAMP_ISO: Final = re.compile(r"(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})(?!\d)")
_STAMP_TODAY: Final = re.compile(
    r"(?:today|tonight|this\s+(?:morning|afternoon|evening))\b", re.IGNORECASE
)
_STAMP_YESTERDAY: Final = re.compile(r"(?:yesterday|last\s+night)\b", re.IGNORECASE)
_STAMP_NO_DAY: Final = re.compile(
    r"(?:\d{1,2}|one|two|three|four)\s*-?\s*(?:hours?|hrs?)\b(?=\s*(?:late|later|delay|delayed|"
    r"early)\b)|(?:delayed|delay(?:ed)?\s+by|late\s+by)\s+(?:\d{1,2}|one|two|three|four)\s+"
    r"(?:hours?|hrs?)\b|(?:snow|learning|e-?learning|instructional|school|virtual|remote|"
    r"weather|half|full|teacher|work|flex)\s+days?\b",
    re.IGNORECASE,
)
"""Status words a stamp's words may run on into that carry no day: a delay's length ("a 2
hour delay", "two hours later", "delayed 2 hours") and a kind of day ("snow day", "learning
day"). "2 hours ago" is no delay and stays unread."""
_DATEISH: Final = re.compile(
    rf"\d|(?:{'|'.join(MONTHS)})\b|(?:{'|'.join(_SPELLINGS)})\b|"
    r"(?:today|tonight|tomorrow|yesterday|weeks?|ago|last|night|morning|afternoon|evening|"
    r"days?|hours?|hrs?|minutes?|mins?|earlier|recently)\b",
    re.IGNORECASE,
)
"""What makes a stamp carry a day: a number, a month, a weekday or a relative day word."""
_MONTH_NUMBER: Final = tuple(re.compile(rf"(?:{month})\Z", re.IGNORECASE) for month in MONTHS)


def _month_of(text: str) -> int:
    return next(n for n, month in enumerate(_MONTH_NUMBER, start=1) if month.match(text))


def _stamp_day(found: re.Match[str], today: date, *, worded: bool) -> date | None:
    """The date a stamp's month and day (and year, if any) name: with no year, the latest
    such date not after ``today``; ``None`` when it does not exist."""
    parts = found.groupdict()
    month = _month_of(parts["month"]) if worded else int(parts["month"])
    year_text = parts.get("year") or parts.get("short")
    try:
        if year_text is None:
            day = date(today.year, month, int(parts["day"]))
            return day if day <= today else date(today.year - 1, month, int(parts["day"]))
        year = int(year_text)
        return date(year + 2000 if year < 100 else year, month, int(parts["day"]))  # noqa: PLR2004 - a two-digit year
    except ValueError:
        return None


def _read_stamp(stamp: str, at: int, end: int, today: date) -> tuple[bool, date | None]:
    """Whether the stamp in ``stamp`` from ``at`` (what follows a stamp word) to ``end``
    carries a day, and which (``None`` when it carries one that cannot be read exactly: any
    number, month, weekday or relative day word in it that no date, time or day form here
    reads, wherever it stands). A date or time that starts before ``end`` is read whole,
    past it too ("Oct. 29", "6 a.m.")."""
    days: list[date | None] = []
    weekdays: list[int] = []
    unread = False
    while at < end:
        if (
            (found := _STAMP_SEP.match(stamp, at)) is not None
            or (found := _STAMP_CLOCK.match(stamp, at)) is not None
            or (found := _STAMP_NO_DAY.match(stamp, at)) is not None
        ):
            at = found.end()
        elif (found := _STAMP_WORDED.match(stamp, at)) is not None:
            days.append(_stamp_day(found, today, worded=True))
            at = found.end()
        elif (found := _STAMP_NUMERIC.match(stamp, at) or _STAMP_ISO.match(stamp, at)) is not None:
            days.append(_stamp_day(found, today, worded=False))
            at = found.end()
        elif (found := _WEEKDAY.match(stamp, at)) is not None:
            weekdays.append(_weekday_of(found))
            at = found.end()
        elif (found := _STAMP_TODAY.match(stamp, at)) is not None:
            days.append(today)
            at = found.end()
        elif (found := _STAMP_YESTERDAY.match(stamp, at)) is not None:
            days.append(today - timedelta(days=1))
            at = found.end()
        else:
            unread = unread or _DATEISH.match(stamp, at) is not None  # a day it cannot read
            found = _STAMP_OTHER.match(stamp, at)
            at = len(stamp) if found is None else found.end()
    if unread:
        return True, None
    return _stamp_of(days, weekdays, today)


def _stamp_of(
    days: list[date | None], weekdays: list[int], today: date
) -> tuple[bool, date | None]:
    """Whether the dates and weekdays a stamp holds carry a day, and which (see
    :func:`_read_stamp`)."""
    if days:
        stated = set(days)
        day = stated.pop() if len(stated) == 1 else None
        if day is not None and any(weekday != day.weekday() for weekday in weekdays):
            return True, None  # "Posted Wednesday, October 29" when the 29th is a Thursday
        return True, day
    if weekdays:
        if len(set(weekdays)) > 1:
            return True, None
        return True, today - timedelta(days=(today.weekday() - weekdays[0]) % 7)
    return False, None


def stamp_dates(text: str, today: date) -> tuple[date | None, ...]:
    """The dates the stamps in the row's words ``text`` say it was posted or updated on
    ("Posted 10/29", "Updated Oct. 29", "(updated Oct 29, 2025)", "Updated 2026-10-29",
    "Posted Wednesday, October 28", "Updated Wednesday 9:00 PM", "Posted yesterday"), read
    on the read's local day ``today``: a date with no year is the latest such date not
    after ``today``, a weekday alone the latest such weekday. ``None`` for a stamp that
    carries a day it does not read exactly ("Updated last week", "Posted 3 days ago",
    "Posted Feb. 30", a weekday that is not its date's, "Posted by District 5"); a stamp
    with no day ("Updated 5:30 AM", "Posted by the district") gives nothing. A stamp is
    read over all :data:`STAMP_PHRASE` cuts from the words the other rules read: from its
    stamp word to the first ".", ";" or "|", across lines, and a date or time that runs on
    past a "." whole (:func:`_read_stamp`). Never raises."""
    found: list[date | None] = []
    for word in _STAMP_WORD.finditer(text):
        cut = STAMP_PHRASE.match(text, word.start())
        end = word.end() if cut is None else cut.end()
        dated, day = _read_stamp(text, word.end(), end, today)
        if dated:
            found.append(day)
    return tuple(found)
