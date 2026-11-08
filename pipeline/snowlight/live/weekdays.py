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
* they hold a relative day word ("today", "tonight", "tomorrow", "yesterday", "this week",
  "next", "weekend"): its meaning depends on the posting time, which is unknown; or a word
  that puts the status before ("previously", "earlier", "was");
* they give a posting age (:func:`post_ages`: "(1w)", "6d", "2d", "1d", "1440m", "1 wk",
  "3 days ago", "a few hours ago") of a day or more, or one that cannot be read exactly; a
  length in days or more with no "ago" ("2 days") counts as one. An age under a day ("2h",
  "8h", "5m", "an hour ago", "just now") is left to the resolver, which takes it as a stamp
  of the read's day or the one before ("Closed Thursday • 8h" first seen Thursday at 06:00
  was posted Wednesday evening, as "Posted Wed 9pm" was) and bounds it the same from every
  read (:data:`snowlight.live.resolve.LONGEST_POST_AGE`). A delay's length of up to
  :data:`_LONGEST_DELAY` ("2 hr delay", "2 hr. delay", "Open 2 Hrs. Late", "90 Min. Delay",
  "2 hours late", "delayed 2 hours") is no age; a longer one, or one a bullet, a dot or a
  spaced dash parts from the delay word, is ("Delayed Thursday • 168h");
* they say the school is open again or back on its schedule ("open since", "reopened",
  "resumed", "back in session", "classes resume", "normal schedule", "now open", "lifted",
  "all clear"), or that the closure or delay is over ("closure over", "delay cancelled",
  "closing rescinded"): the row may report a closure that has ended;
* a weekday follows, in its clause, a word that makes it the end or another day than the
  one closed ("until Thursday", "reopens on Thursday", "back to school Thursday",
  "through Thursday", "next Thursday", "after Thursday", "instead of Friday", "rather
  than Friday", "not Friday", "moved to Friday"), starts a span ("Mon-Wed", "Monday to
  Friday"), or is followed by a day number that is not the day the row is dated by
  ("Thursday 29" on Nov. 5: another week's), or by one with a mark ("Thursday #5",
  "Thursday no. 5"), or follows one ("Closed 29 Thursday"); "Thursday 5" and "Thursday, the
  5" on Thursday Nov. 5 name it;
* a weekday is the day a notice went out: after a word that sends one ("Issued Friday",
  "Released Friday", "as announced on Monday"), before a notice word ("Friday post", "Friday
  notice") or as a possessive that owns no school day ("per Friday's notice"; "Thursday's
  classes are cancelled" names Thursday);
* they hold a number that may be a month and day ("1029", "#1105", "115": Jan. 15 or Nov.
  5), with a year or not ("1029-26", "102926", "10292026": Oct. 29, 2026), that does not
  name, in every reading, the day the row is dated by ("1105" and "110526" on Nov. 5 do),
  unless the words just around it make it exactly no date: a bus, a route, a room or a
  district's number ("Bus 1029", "Room 104", "USD 105"), a clock time ("at 1030", "1030 am",
  "0530 hrs") or a length ("120 minute delay"); "0530" alone may be May 30 and holds; or a
  day number standing alone as their first or last clause ("29: Closed Thursday", "Closed
  Thursday, 29"; never one of a list of numbers, "routes 2, 3, 4") that is not the day;
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
unreadable. A stamp's weekday alone is the latest such weekday, the read's day or the day
before ("Posted Wed 9pm" or "Posted Thu" read Thursday, "Updated last night"); one two or
more days back ("Posted Friday", "Updated Saturday", "Posted Mon" read Thursday) may be any
week's, or after the day the row is for, and makes the stamp unreadable. "Posted yesterday"
with a time ("at 9 PM", "evening") is the day before, as "Updated last night" is; with none
it is an age of about a day, and so is unreadable; an age in a stamp ("Updated 2 hours ago")
gives no day of its own and is bounded as every age is. The same guards keep
a date from dating its row: "Closed until Nov. 5", "Classes resume Nov. 5", "Closed Nov.
5-6", "Closed Nov. 5 (1w)", "Closed Nov. 5 1029" and "Closed Nov. 5; open since" state no
date for this rule.

A date is stated when the words hold it as a month and day ("Nov. 5", "November 5th,
2026"), a numeric date ("11/5", "11/5/26") or an ISO date, with no other year (after it:
"Nov. 5, 2025", "Nov. 5 '25"); a day number alone ("the 5th") states none here.

One class is left as built (the lead's ruling, WD-R4C3-P8): a source the ledger has never
held rows for, read cold for the first time while it shows an earlier week's row naming
today's weekday, lights on that read, since nothing bounds when the row went up; and a warm
read later the same local day carries it on, a tied successor escalating it ("2 hour delay
Thursday" then "Closed Thursday") included, as every successor carries its predecessor's
first sighting (:func:`snowlight.live.resolve._successor_earliest`). It never outlasts the
day the words name. The live ledger's own counts find such reads rare: in the four
consecutive live reads up to Nov. 7, 2026 that round 4 measured, every list group counted
"never read 0", and of the 193 rows its cold census held as ``unknown_start``, 0 came from a
first read of their source or a gap.
"""

import re
from bisect import bisect_right
from collections.abc import Iterable, Iterator
from datetime import date, timedelta
from functools import lru_cache
from typing import Final, NamedTuple

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
    r"[\s,]{0,3}(?:the\s+)?(?P<mark>no\.?\s*|#\s*)?(?P<number>0?[1-9]|[12]\d|3[01])(?![\d:]|\.\d)"
    r"(?!\s*(?:-?\s*(?:hours?|hrs?|h|minutes?|mins?)\b|[ap]\.?\s?m\b))",
    re.IGNORECASE,
)
"""A day number right after a weekday ("Thursday 29", "Thursday #29", "Thursday, the 29"),
no clock time or delay length: the weekday may be another week's. Only a plain one ("Thursday
5", "Thursday, the 5", never "#5" or "no. 5") can name the day its weekday names."""
_MONTH_DAY_NUMBER: Final = re.compile(
    r"(?<![\w/:.,\-#$])(?P<mark>#\s*)?(?:(?P<number>\d{3,4})(?:-(?P<year>\d{2}|\d{4}))?"
    r"|(?P<long>\d{6}|\d{8}))(?![\w/:]|[.,\-]\d)"
)
"""A 3- or 4-digit number standing alone ("1029", "#1105", "104"), with a year after a dash
("1029-26") or not, or a 6- or 8-digit one ("102926", "10292026"): it may be a month and day
written as one number."""
_NOT_A_DAY_BEFORE: Final = re.compile(
    r"\b(?:bus(?:es)?|routes?|rte|rt|rooms?|rm|units?|ext|suite|ste|bldg|building|hwy|highway|"
    r"exit|gate|door|lot|box|code|district|dist|usd|isd|csd|cusd|sd|at)\.?\s*$|@\s*$",
    re.IGNORECASE,
)
"""A word just before a number that makes it a bus, a route, a room, a district's number or a
clock time ("Bus 1029", "Room 104", "USD 105", "at 1030"), not a date."""
_NOT_A_DAY_AFTER: Final = re.compile(
    r"\s*-?\s*(?:[ap]\.?\s?m\b|hrs?\b|hours?\b|h\b|minutes?\b|mins?\b)", re.IGNORECASE
)
"""Words just after a number that make it a clock time or a length ("1030 am", "0530 hrs",
"120 minute delay", "120-min. delay")."""
_BEFORE_WINDOW: Final = 24
"""How far before a number or a weekday the words just before it are read (no word or mark
read there is longer): each is read in its own window, never over the whole row."""


_MONTH_DAYS: Final = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
_MMDD: Final = 4
"""Digits in a number written as a month and day "MMDD" ("1029"); three are "MDD" or "MMD"."""
_MMDDYY: Final = 6
"""Digits in a month, day and two-digit year written as one number ("102926")."""


def _valid(month: int, day: int) -> bool:
    return 1 <= month <= len(_MONTH_DAYS) and 1 <= day <= _MONTH_DAYS[month - 1]


def _month_day_readings(found: re.Match[str]) -> frozenset[tuple[int, int, int | None]]:
    """The months, days and years (``None`` for no year) a number ``found`` by
    :data:`_MONTH_DAY_NUMBER` can be read as: "1029" October 29, "104" January 4 or
    October 4, "115" January 15 or November 5, "1029-26" and "102926" October 29, 2026,
    "10292026" the same, "2026" none."""
    readings: set[tuple[int, int, int | None]] = set()
    long = found.group("long")
    if long is not None:
        month, day, stated = int(long[:2]), int(long[2:4]), int(long[4:])
        if _valid(month, day):
            readings.add((month, day, stated + 2000 if len(long) == _MMDDYY else stated))
        return frozenset(readings)
    number, year_text = found.group("number"), found.group("year")
    year = None if year_text is None else int(year_text)
    if year is not None and len(year_text or "") == 2:  # noqa: PLR2004 - a two-digit year
        year += 2000
    for cut in (2,) if len(number) == _MMDD else (1, 2):
        month, day = int(number[:cut]), int(number[cut:])
        if _valid(month, day):
            readings.add((month, day, year))
    return frozenset(readings)


def _numbers_name(words: str, day: date | None) -> bool:
    """Whether every number in ``words`` that may be a month and day ("1029", "1029-26",
    "102926", "10292026") names ``day`` in each reading ("1105" on Nov. 5; never "115",
    which may be Jan. 15, nor "110525", Nov. 5, 2025), or is told apart as no date by the
    words around it ("Bus 1029", "Room 104", "at 1030", "1030 am", "120 minute delay").
    With no ``day``, no such number may stand in the words."""
    if any(
        day is None or int(found.group("first") or found.group("last")) != day.day
        for found in _LONE_DAY_NUMBER.finditer(words)
    ):
        return False  # "29: Closed Thursday" on Nov. 5
    for found in _MONTH_DAY_NUMBER.finditer(words):
        readings = _month_day_readings(found)
        if not readings:
            continue
        if _NOT_A_DAY_BEFORE.search(
            words, max(0, found.start() - _BEFORE_WINDOW), found.start()
        ) or _NOT_A_DAY_AFTER.match(words, found.end()):
            continue
        if (
            day is None
            or found.group("mark")
            or len(readings) != 1
            or any(
                (month, number) != (day.month, day.day) or year not in {None, day.year}
                for month, number, year in readings
            )
        ):
            return False
    return True


_RELATIVE: Final = re.compile(
    r"\b(?:today|tonight|tomorrow|yesterday|this\s+(?:morning|afternoon|evening|week)|"
    r"next|last|weekend|week|ago|previously|earlier|was)\b",
    re.IGNORECASE,
)
"""Day words whose meaning depends on when the row was posted, and words that put the
status before it ("previously", "earlier", "was")."""
_COUNTS: Final = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}  # fmt: skip
"""Counts written as words that an age ("two hours ago") is read with."""
_UNITS: Final = (
    (re.compile(r"m|mins?|minutes?", re.IGNORECASE), timedelta(minutes=1)),
    (re.compile(r"h|hrs?|hours?", re.IGNORECASE), timedelta(hours=1)),
    (re.compile(r"d|days?", re.IGNORECASE), timedelta(days=1)),
    (re.compile(r"w|wks?|weeks?", re.IGNORECASE), timedelta(weeks=1)),
    (re.compile(r"mos?|mths?|months?", re.IGNORECASE), timedelta(days=28)),
    (re.compile(r"y|yrs?|years?", re.IGNORECASE), timedelta(days=365)),
)
"""Each unit an age is read in, and the least it can be (a month at least four weeks)."""
_AGE: Final = re.compile(
    r"(?<![\w.:/,'\u2019$#-])(?P<count>\d{1,5}|an?|one|two|three|four|five|six|seven|eight|"
    r"nine|ten|eleven|twelve|few|several|some|many|couple(?:\s+of)?)(?P<gap>\s*-?\s*)"
    r"(?P<unit>minutes?|mins?|m|hours?|hrs?|h|days?|d|weeks?|wks?|w|months?|mths?|mos?|years?|"
    r"yrs?|y)\b(?P<ago>\.?\s*ago\b)?"
    r"|(?P<now>\b(?:just\s+now|(?:a\s+)?(?:few\s+)?(?:moments?|seconds?|secs?)\s+ago)\b)",
    re.IGNORECASE,
)
"""An age in the words: how long before it was read the row was posted ("(1w)", "6d", "2h",
"5m", "3 days ago", "an hour ago", "just now"), or a length of time ("2 days")."""
_DELAY_BEFORE: Final = re.compile(
    r"\b(?:delay\w*|late|early|dismiss\w*|start\w*|release\w*)\b", re.IGNORECASE
)
_DELAY_AFTER: Final = re.compile(
    r"\.?\s*(?:delay\w*|late\w*|early|earlier|start\w*|dismiss\w*|release\w*|behind|"
    r"(?:of\s+)?(?:delay|late))\b",
    re.IGNORECASE,
)
"""Words around a length in hours or minutes that make it a delay's or an early release's
("2 hr delay", "2 hr. delay", "Open 2 Hrs. Late", "90 Min. Delay", "2 hours late",
"delayed 2 hours", "Delayed Tuesday 2 Hours", "dismissed 2 hours early"): right after it, or
before it in its clause (:data:`_DELAY_CLAUSE`, at most :data:`_DELAY_WINDOW` characters
back); it is no age when it is no longer than :data:`_LONGEST_DELAY`."""
_DELAY_CLAUSE: Final = re.compile(r"[.;,:/|!?()\n\u2022\u00b7\u2027\u2219]|\s[-\u2013\u2014]+\s")
"""What ends a clause for a delay word before a length: a clause mark, a bullet or a dot
("Delayed Thursday \u2022 168h"), or a dash between spaces ("2 hour delay - 7h")."""
_DELAY_WINDOW: Final = 48
_LONGEST_DELAY: Final = timedelta(hours=5)
"""The longest length a delay or an early release is read with: "Delayed Thursday 30h" gives an
age."""
_A_DAY: Final = timedelta(days=1)
_A_MINUTE: Final = timedelta(minutes=1)
_LONGEST_COUNT: Final = 3
"""Digits in the longest count an age is read with, but in minutes ("1440m", "10080 min ago"):
a longer number before another unit is a year or a clock time ("2024 y", "0530 hrs")."""


def _a_delay(text: str, found: re.Match[str], length: timedelta | None) -> bool:
    """Whether the length ``found`` in ``text`` (``length`` long, ``None`` when not exact) is
    a delay's or an early release's (:data:`_DELAY_AFTER`), and so no age."""
    if length is not None and length > _LONGEST_DELAY:
        return False
    if _DELAY_AFTER.match(text, found.end()):
        return True
    before = text[max(0, found.start() - _DELAY_WINDOW) : found.start()]
    return _DELAY_BEFORE.search(_DELAY_CLAUSE.split(before)[-1]) is not None


def _ages(text: str) -> Iterator[tuple[re.Match[str], timedelta | None]]:
    """Each age in ``text`` and how long it is (see :func:`post_ages`)."""
    for found in _AGE.finditer(text):
        if found.group("now"):
            yield found, timedelta(0)
            continue
        count, ago = found.group("count").casefold(), found.group("ago") is not None
        unit = next(size for pattern, size in _UNITS if pattern.fullmatch(found.group("unit")))
        if not count.isdigit() and len(found.group("unit")) == 1:
            continue  # "a m", "an h": no age
        if count.isdigit() and len(count) > _LONGEST_COUNT and unit != _A_MINUTE:
            continue  # a year or a clock time: "2024 y", "0530 hrs"; only "1440m" is an age
        length = (
            int(count) * unit
            if count.isdigit()
            else _COUNTS[count] * unit
            if count in _COUNTS
            else None  # "a few days ago", "several hours": no exact age
        )
        if unit < _A_DAY and not ago and _a_delay(text, found, length):
            continue  # a delay's length: "2 hr delay", "Open 2 Hrs. Late", "delayed 2 hours"
        yield found, length


def post_ages(text: str) -> tuple[timedelta | None, ...]:
    """The ages the row's words ``text`` give: how long before the read each says the row was
    posted ("(1w)", "6d", "2h", "5m", "1440m", "3 days ago", "an hour ago", "just now"),
    ``None`` for one it cannot read ("a few days ago", "several hours ago"). A length with no
    "ago" ("2 days", "1 wk", "2 hours") counts as an age too, since it may be one; a length
    of up to :data:`_LONGEST_DELAY` that is a delay's ("2 hr delay", "Open 2 Hrs. Late", "90
    Min. Delay", "2 hours late", "delayed 2 hours") is none, and so is a clock time ("0530
    hrs"). Never raises."""
    return tuple(age for _, age in _ages(text))


def _without_ages(words: str) -> str | None:
    """``words`` without the ages under a day they give ("2h ago", "5m", "just now"): the
    resolver bounds the row by them from the read time (:func:`post_ages`). ``None`` when they
    give one of a day or more, or one that cannot be read ("(1w)", "6d", "3 days ago")."""
    kept: list[str] = []
    at = 0
    for found, age in _ages(words):
        if age is None or age >= _A_DAY:
            return None
        kept.append(words[at : found.start()])
        at = found.end()
    kept.append(words[at:])
    return " ~ ".join(kept)  # a mark no word or number rule reads past ("Sunday. 4-H Club")


_REOPENED: Final = re.compile(
    r"\b(?:open(?:ed)?\s+(?:again\s+)?since|re-?open(?:ed|ing|s)?|resum(?:e|ed|es|ing)|"
    r"back\s+in\s+session|back\s+to\s+(?:school|class(?:es)?|normal|regular)|"
    r"(?:normal|regular|usual)\s+(?:schedule|day|hours|time|classes|operations|session)|"
    r"as\s+(?:normal|usual)|now\s+open|(?:has|have)\s+(?:now\s+)?(?:ended|reopened|resumed)|"
    r"lifted|all\s+clear|(?:closures?|closings?|delays?|cancell?ations?)\s+(?:is\s+|are\s+|has\s+|"
    r"have\s+)?(?:been\s+)?(?:now\s+)?(?:over|ended|done|cancell?ed|called\s+off|rescinded|"
    r"revoked|lifted))\b",
    re.IGNORECASE,
)
"""Words that say the school is open again or back on its schedule ("open since", "reopened",
"resumed", "back in session", "classes resume", "normal schedule", "all clear"), or that the
closure or delay is over ("closure over", "delay cancelled", "closing rescinded"): the row
may report a closure that has ended, so its words date it by no day."""
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
_SPAN_AFTER: Final = re.compile(r"\s*(?:-|\u2013|\u2014|to\b|through\b|thru\b)", re.IGNORECASE)
"""Words just after a weekday that make it the first day of a span ("Mon-Wed")."""
_HOLIDAY_AFTER: Final = re.compile(r"\s+(?:of\s+service|holiday|break|sale)\b", re.IGNORECASE)
"""Words just after a weekday that make it a holiday or a break ("Friday holiday")."""
_YEAR_AFTER: Final = re.compile(r",?\s*(?:['\u2018\u2019`]\s?(?P<short>\d{2})|(?P<long>\d{4}))\b")
"""A year just after a date: "Nov. 5, 2025", "Nov. 5 '25"."""


class _Clauses(NamedTuple):
    """Where the clause marks and the end words in some words are, found once for them, so
    that each day they hold is guarded in time independent of their length."""

    marks: list[int]
    end_starts: list[int]
    end_ends: list[int]

    @classmethod
    def of(cls, words: str) -> "_Clauses":
        ends = list(_END_WORDS.finditer(words))
        return cls(
            [found.start() for found in _CLAUSE.finditer(words)],
            [found.start() for found in ends],
            [found.end() for found in ends],
        )

    def end_word_before(self, at: int) -> bool:
        """Whether an end word stands in the clause before ``at``, after its last mark."""
        mark = bisect_right(self.marks, at - 1) - 1
        start = self.marks[mark] + 1 if mark >= 0 else 0
        last = bisect_right(self.end_ends, at) - 1
        return last >= 0 and self.end_starts[last] >= start


def _not_the_day(words: str, found: re.Match[str], clauses: _Clauses) -> bool:
    """Whether the day ``found`` in ``words`` (a weekday or a date) is not the day they are
    for: an end word in its clause before it ("until", "reopens", "back"), a holiday's name
    around it, or the start of a span. ``clauses`` is :class:`_Clauses` of ``words``."""
    start = found.start()
    return bool(
        clauses.end_word_before(start)
        or _HOLIDAY_BEFORE.search(words, max(0, start - _BEFORE_WINDOW), start)
        or _SPAN_AFTER.match(words, found.end())
        or _HOLIDAY_AFTER.match(words, found.end())
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


_POSSESSIVE: Final = re.compile(r"['\u2019]s\b(?:[ \t]+(?P<word>[^\W\d_]+))?", re.IGNORECASE)
_POSSESSED: Final = frozenset(
    {
        "school", "schools", "class", "classes", "activities", "activity", "events", "event",
        "sports", "athletics", "practice", "practices", "programs", "program", "session",
        "sessions", "schedule", "bus", "buses", "routes", "transportation", "closing",
        "closings", "closure", "closures", "cancellation", "cancellations", "delay", "delays",
        "dismissal", "release", "start", "instruction", "learning", "games", "game",
    }
)  # fmt: skip
"""What a possessive weekday may own when it names the day the row is for ("Thursday's
classes are cancelled"). Owning anything else, a notice above all ("per Friday's notice",
"Friday's message"), it names another day than the one closed."""
_POSTING_BEFORE: Final = re.compile(
    r"\b(?:issued|released|sent|announced|published|shared|e-?mailed|tweeted|texted|"
    r"circulated|distributed|decided|approved)\s+(?:on\s+)?\Z",
    re.IGNORECASE,
)
_POSTING_AFTER: Final = re.compile(
    r"\s+(?:post|posts|posting|notice|notices|message|messages|announcement|announcements|"
    r"update|updates|e-?mail|e-?mails|letter|alert|alerts|statement|tweet|newsletter|news|"
    r"call|decision|press)\b",
    re.IGNORECASE,
)
"""Words just around a weekday that make it the day a notice went out, not a day the row is
for ("Issued Friday", "Released Friday", "Friday post", "Friday notice", "per Friday's
notice")."""
_LONE_DAY_NUMBER: Final = re.compile(
    r"\A\s*(?:#\s*)?(?P<first>0?[1-9]|[12]\d|3[01])\s*(?=[;|!?()\n]|:(?!\d)|,(?!\s*\d)|\Z)"
    r"|(?<![\d\s])\s*[;,:|!?(\n]\s*(?:#\s*)?(?P<last>0?[1-9]|[12]\d|3[01])\s*\)?\s*\Z"
)
"""A day number standing alone as the first or the last clause of the words ("29: Closed
Thursday", "Closed Thursday, 29"), never one of a list of numbers ("routes 2, 3, 4"): it may
be another week's day."""
_DAY_NUMBER_BEFORE: Final = re.compile(
    r"(?<![\w/:.,\-#$])(?P<number>0?[1-9]|[12]\d|3[01])[ \t,]{1,3}\Z"
)
"""A day number right before a weekday ("Closed 29 Thursday", "5&6 Thursday"): the weekday
may be another week's, as with one after it."""


def _another_day_around(words: str, found: re.Match[str], day: date | None) -> bool:
    """Whether a day number or a possessive around the weekday ``found`` in ``words`` makes
    it another week's, or another day than the one closed: "Thursday 29" or "29 Thursday"
    on Nov. 5, "Thursday #5", "per Friday's notice" (see the module). Only a plain day
    number ("Thursday 5", "5 Thursday", never "#5") can name the day its weekday names."""
    weekday, start = _weekday_of(found), found.start()

    def another(number: re.Match[str] | None, *, marked: bool) -> bool:
        return number is not None and (
            day is None
            or marked
            or weekday != day.weekday()
            or int(number.group("number")) != day.day
        )

    after = _DAY_NUMBER_AFTER.match(words, found.end())
    before = _DAY_NUMBER_BEFORE.search(words, max(0, start - _BEFORE_WINDOW), start)
    if before is not None and _NOT_A_DAY_BEFORE.search(
        words, max(0, before.start() - _BEFORE_WINDOW), before.start()
    ):
        before = None  # "Opening at 9 Tuesday", "Bus 5 Thursday": a time or a number
    if another(after, marked=after is not None and bool(after.group("mark"))) or another(
        before, marked=False
    ):
        return True
    if _POSTING_BEFORE.search(words, max(0, start - _BEFORE_WINDOW), start) or _POSTING_AFTER.match(
        words, found.end()
    ):
        return True  # "Issued Friday", "Friday post": when it was posted
    possessive = _POSSESSIVE.match(words, found.end())
    return possessive is not None and (
        possessive.group("word") is None or possessive.group("word").casefold() not in _POSSESSED
    )


def _in_a_name(words: str, found: re.Match[str], *, mixed: bool) -> bool:
    """Whether the weekday ``found`` in ``words`` may be part of a proper name: a place word
    before it, or a word after it that is no status, date, time or connective word or is one
    that also names a school (:data:`_NAME_AFTER`; in mixed-case words, only a capitalised
    one: "Friday Harbor" and "Friday School", not "Friday harbor" or "Friday school")."""
    if _PLACE_BEFORE.search(words, max(0, found.start() - _BEFORE_WINDOW), found.start()):
        return True
    after = _NEXT_WORD.match(words, found.end())
    if after is None:
        return False
    word = after.group("word")
    if mixed and not word[0].isupper():
        return False
    folded = word.casefold().rstrip(".")
    return folded in _NAME_AFTER or folded not in _PLAIN_AFTER


@lru_cache(maxsize=4096)
def named_weekdays(text: str, name: str = "", day: date | None = None) -> frozenset[int]:
    """The weekdays (Monday 0) the status words ``text`` name as the days they are for, or
    none when the words cannot date their row by a weekday (see the module).

    ``name`` is the row's name: a weekday it holds is never read from ``text``. ``day`` is
    the day the words are read for: a day number after a weekday ("Thursday 5") or a month
    and day written as one number ("1105") may name it; with no ``day``, none may stand in
    the words.
    """
    words = _without_ages(STAMP_PHRASE.sub(" ", text))
    if (
        words is None
        or _EXPLICIT_DATE.search(words)
        or _OTHER_DATE.search(words)
        or _RELATIVE.search(words)
        or _REOPENED.search(words)
        or not _numbers_name(_without_name(words, name), day)
    ):
        return frozenset()
    in_name = weekdays_in([name])
    letters = [char for char in words if char.isalpha()]
    mixed = any(char.isupper() for char in letters) and any(char.islower() for char in letters)
    named: set[int] = set()
    clauses = _Clauses.of(words)
    for found in _WEEKDAY.finditer(words):
        if _not_the_day(words, found, clauses) or _in_a_name(words, found, mixed=mixed):
            return frozenset()
        if _another_day_around(words, found, day):
            return frozenset()  # "Thursday 29", "Thursday #5": another week's, or not exact
        weekday = _weekday_of(found)
        if weekday not in in_name:
            named.add(weekday)
    return frozenset(named)


def _without_name(words: str, name: str) -> str:
    """``words`` without the row's name, case-folded (only its numbers are read)."""
    named = name.strip().casefold()
    folded = words.casefold()
    return folded.replace(named, " ") if named else folded


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
    words = _without_ages(_status_words(text, name))
    if (
        words is None
        or _OTHER_DATE.search(words)
        or _REOPENED.search(words)
        or not _numbers_name(words, day)
    ):
        return False
    clauses = _Clauses.of(words)
    if any(_not_the_day(words, found, clauses) for found in _EXPLICIT_DATE.finditer(words)):
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
_STAMP_LAST_NIGHT: Final = re.compile(
    r"last\s+night\b|yesterday\s+(?P<part>morning|afternoon|evening|night)\b|(?P<bare>yesterday\b)",
    re.IGNORECASE,
)
"""The day before the read, at a time the stamp gives ("Updated last night", "Posted yesterday
at 9 PM", "Posted yesterday evening"): a stamp of the day before, as "Posted Wed 9pm" read
Thursday is. "Posted yesterday" with no time is an age of about a day (:func:`post_ages`), and
the stamp is unread."""
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
    unread = clocked = yesterday = False
    while at < end:
        if (found := _STAMP_CLOCK.match(stamp, at)) is not None:
            clocked = True
            at = found.end()
        elif (found := _STAMP_SEP.match(stamp, at) or _STAMP_NO_DAY.match(stamp, at)) is not None:
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
        elif (found := _STAMP_LAST_NIGHT.match(stamp, at)) is not None:
            yesterday = yesterday or found.group("bare") is not None
            days.append(today - timedelta(days=1))
            at = found.end()
        elif (found := _AGE.match(stamp, at)) is not None and (
            age := next(iter(_ages(found.group(0))), None)
        ) is not None:
            # an age the resolver bounds from the read time (post_ages); one of a day or
            # more, or one it cannot read, makes the stamp unreadable
            unread = unread or age[1] is None or age[1] >= _A_DAY
            at = found.end()
        else:
            unread = unread or _DATEISH.match(stamp, at) is not None  # a day it cannot read
            found = _STAMP_OTHER.match(stamp, at)
            at = len(stamp) if found is None else found.end()
    if unread or (yesterday and not clocked):
        return True, None  # "Posted yesterday": an age of about a day, at no time it gives
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
        back = (today.weekday() - weekdays[0]) % 7
        if len(set(weekdays)) > 1 or back > 1:
            return True, None  # which week's is unknown: "Posted Friday" read on a Thursday
        return True, today - timedelta(days=back)
    return False, None


def stamp_dates(text: str, today: date) -> tuple[date | None, ...]:
    """The dates the stamps in the row's words ``text`` say it was posted or updated on
    ("Posted 10/29", "Updated Oct. 29", "(updated Oct 29, 2025)", "Updated 2026-10-29",
    "Posted Wednesday, October 28", "Updated Wednesday 9:00 PM", "Updated last night"),
    read on the read's local day ``today``: a date with no year is the latest such date not
    after ``today``, a weekday alone the latest such weekday when that is ``today`` or the
    day before. ``None`` for a stamp that carries a day it does not read exactly ("Updated
    last week", "Posted 3 days ago", "Posted yesterday", "Posted Feb. 30", a weekday that
    is not its date's, a weekday alone two or more days back: "Posted Friday" read on a
    Thursday, "Posted by District 5"); a stamp with no day ("Updated 5:30 AM", "Posted by
    the district", "Updated 2 hours ago": an age, bounded by :func:`post_ages`) gives
    nothing. A stamp is
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
