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
  spaced dash parts from the delay word, is ("Delayed Thursday • 168h"); an age glued to the
  word before it is one too ("Closed Thursday,5d", "Thursday.5d", "Thursday:6d",
  "Thursday/6d", "Thursday 6:00:5d", "11/5,5d", "Thursday.1.5d"), a decimal one is what it
  says ("1.5d", "1.5 days ago"), a count in thousands groups before a minute or hour unit is
  its whole number ("2,880 min"), one grouped with a "." or a space before a minute or second
  unit cannot be read exactly ("1.440 min", "1 440 min"), seconds are read grouped or of four
  digits or more ("86,400 s"; "the 1990s" is none), "dy" and "dys" are days ("5dys"), no age is
  the end of another number ("10:30m", "3-6 hours"), and the end of a spaced span of lengths
  cannot be read exactly ("1 - 2w", "9 to 3 hours"; "delayed 2 to 3 hours" is a delay's);
* they say the school is open again or back on its schedule ("open since", "reopened",
  "resumed", "back in session", "is in session", "open on time", "classes resume", "normal
  schedule", "now open", "open again", "open once more", "back open", "lifted", "all clear"),
  or that the closure or delay is over ("closure over", "is over", "(over)", "[over]", "-
  over", "ended", "expired", "no longer", "delay cancelled", "closing rescinded"), or was
  ("had been closed", "were cancelled"): the row may report a closure that has ended;
* any of their words, its stamps too, void the post or call it an old one, in either order
  around the status (:data:`_VOID`: "Revoked. Closed Thursday", "Closed Thursday rescinded",
  "(old)", "Old. Closed Thursday", "Archived", "Past event", "Not in effect", "Sent in error",
  "Nevermind", "Ignore previous", "Correction - Closed Thursday", "(corrected)"), or an update
  heading says the school is open ("Update: open. Closed Thursday", "Update - school open");
* they name more than :data:`_MOST_WEEKDAYS` weekdays: a schedule or a list of days;
* a weekday follows, in its clause, a word that makes it the end or another day than the
  one closed ("until Thursday", "reopens on Thursday", "back to school Thursday",
  "through Thursday", "next Thursday", "after Thursday", "instead of Friday", "rather
  than Friday", "not Friday", "moved to Friday"), starts a span ("Mon-Wed", "Monday to
  Friday"), or is followed by a day number that is not the day the row is dated by
  ("Thursday 29" on Nov. 5: another week's), or by one with a mark ("Thursday #5",
  "Thursday no. 5") or a letter ("Thursday 5d"), or follows one ("Closed 29 Thursday");
  "Thursday 5" and "Thursday, the 5" on Thursday Nov. 5 name it;
* a weekday is the day a notice went out: after a word that sends one, with an object of up
  to four words or none ("Issued Friday", "Released Friday", "sent out Friday", "as announced
  on Monday", "notified families Friday", "sent to all families Friday", "confirmed Friday"),
  after a notice word that follows other words ("Closed Thursday, message Friday", "update
  Friday", "decision made Friday"), before a notice word ("Friday post", "Friday notice",
  "Friday text", "Friday release") or as a possessive that owns no school day ("per Friday's
  notice"; "Thursday's classes are cancelled" names Thursday);
* a weekday's clause ends in a bare "late", "early", "AM" or "PM" with no status word before
  it ("Closed Thursday \u00b7 Friday late", "Closed Thursday \u00b7 Friday PM"): a late start
  or a post's time, read exactly as neither ("Early dismissal Thursday PM" names Thursday);
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

A weekday with a clock time right by it and no status word in its clause (:func:`_clocked`:
"Closed Thursday \u00b7 Fri 9:14 PM", "Closed Thursday Sat 7:12am", "Friday (9:14pm)", "9:14 PM
Fri", "at 9:14 PM Friday", "Friday at 9", "Friday around 9 PM", "Fri 2114", "Closed Thursday
\u00b7 Friday evening", "Friday late evening", "Thursday 0900"; past any run of marks too, as
long as it is (:data:`_MARK_RUN`: "Friday: 9:14 PM", "Friday | 9:14 PM", "9:14 PM - Friday",
"9:14 PM (Friday)", "Friday...9:14 PM", "Friday::9:14 PM", "Friday _9:14 PM", "9:14 PM--
Friday", "9:14 PM\u2013 Friday", "5:14 AM ----- Thursday"), each Unicode space read as a space
(:data:`_SPACES`)) is a posting stamp with no stamp word: it names no day the row is
for, and :func:`stamp_dates` reads it as the stamp "Posted Fri 9:14 PM" (two or more days
back, or after the read, it is unreadable and the row keeps its hold); "Early dismissal
Thursday 1:30 PM", "Opening at 10 AM Thursday", "Closing at 1 p.m. Thursday", "No 8 AM Mass
Thursday" and "Thursday Afternoon: Closed" name Thursday. A span of
hours ("9 AM - 3 PM", "8:30-3:15", "10 AM to 3 PM", "9 AM until 3 PM") owns a weekday's clock
time only when a status or an event word stands in that weekday's clause or around the span
(:func:`_span_words`: "Closed Thursday \u00b7 Friday closed 9 AM - 3 PM", "Early dismissal
Friday 1:30-2 PM", "Closed 6 a.m. to 8 p.m. on Friday", "6 a.m. to 8 p.m. on Friday: closed");
otherwise the weekday is a stamp as above ("Closed Wednesday \u00b7 Thursday 9 AM - 3 PM",
"Closed Thursday \u00b7 Friday 9 AM - 3 PM", "Wednesday closed, Thursday 7:45-2:45"). So is a
weekday with a clock time, a span or bare hours (:data:`_HOUR_SPAN`, :data:`_OTHER_SPAN`)
further on in its clause, or in the clauses past the marks that end it, read on over each clause
and run of marks to the first with a status or event word, either way round
(:func:`_past_marks`), and no status or event word there, whatever other words stand between
("Closed Wednesday \u00b7 Thursday | hours (8:30-3:15)", "Thursday | office | hours 8:30-3:15",
"Thursday:9 to 3", "Thursday...9", "9a-3p >> Friday", "Closed Wednesday \u00b7
Thursday hours 8:30-3:15", "Thursday office hours 9:00-11:00", "Thursday: from 9 AM to 3 PM",
"Thursday hours: 9 AM - 3 PM", "9 AM - 3 PM: hours Thursday", "Thursday: 9 to 3", "Thursday
posted 5:14 AM", "Friday: 9 a"); words that name hours are no status (:data:`_HOURS_OF`:
"Thursday school hours 8:30-3:15"), and one clock time something runs until is no stamp's
(:data:`_OPEN_UNTIL`: "Friday Evening: help desk available until 8:30 PM"). A stamp's span of
hours gives no time a row went up at: :func:`stamp_dates` reads it as unreadable. A weekday
right before a
stamp word that starts its clause is the stamp's day (:func:`_stamp_day_before`: "Closed
Wednesday \u00b7 Thursday posted 5:14 AM" is "Posted Thursday 5:14 AM"; "Closed Thursday,
updated 5 AM" names Thursday). A weekday
the words are for whose clock time, right by it or in its clause, no start, opening, closing,
dismissal, event or span of hours owns ("Closed Friday 9:14 PM", "Friday closed 9:14 PM") is
read the same way: read Friday at 06:00, it may be last Friday night's post, and keeps the
hold. A clock time past a run of marks is only ever a stamp's: by a weekday with a status word
it is that day's time only when a start or a dismissal owns it ("Early dismissal Friday: 1:30
PM"), and otherwise one with no day ("Closed Friday @ 9:14 PM", "Closed Friday \"9:14 PM\""),
read as below. Words that own a clock time and are no status word ("begins", "in effect",
"effective", a report or an arrival, and "dismiss", "starting", "started" or "opened" with no
status word: :data:`_OWNS_ONE`, :data:`_OWNS_WITH`, :data:`_OWNS_CLOCK`) own only a single
clock time in the weekday's own clause with no mark between the weekday, the word and the clock
time, wherever the word stands and "at" or "@" after it or not, never a span of hours or one a
mark parts from the weekday, a "~" too ("Closed Wednesday \u00b7 Thursday | begins
(8:30-3:15)", "Closed Wednesday \u00b7 Thursday: staff report 9:14 PM", "Closed Wednesday
\u00b7 in effect Thursday: 9:14 PM", "Closed Wednesday \u00b7 9:14 PM: Thursday begins",
"Closed Wednesday \u00b7 Thursday = begin 9:14 PM", "Closed Wednesday \u00b7 Thursday | dismiss
9:14 PM", "Closed Wednesday \u00b7 Thursday: started at 9:14 PM", "Closed Wednesday \u00b7
Thursday begins ~ 9:14 PM" are stamps), save a dismissal at a single clock time the status
reader reads a dismissal at (:func:`_dismissed_at`: "Thursday: dismiss at 1:30"). A bare number
of one or two digits on either side of a weekday's run of marks, glued or spaced, with words
after it or none, after the "." a weekday ends with too, with a mark glued before it before the
marks, and with a line break in or by the marks (:data:`_MARK_LINES`, :data:`_BARE_NUMBER`:
"10.Thursday", "9...Thursday", "Thursday: 9 | info", "Thursday.45", ":9 \u00b7 Thursday",
"#12 :: Thursday"), is a stamp's number that cannot be read when no status word stands in the
weekday's clause; a clock time, a date and a count with a delay's length unit
are read as before ("Thursday: 2 hour delay"), and a spaced dash in a span of bare hours ends
no clause ("Thursday: 2 - 3 hour delay").

On the weekday path, a clock time that gives no day, in a stamp ("Updated 7 AM", "Posted this
evening") or in a clause of its own with no other number and no word that makes it a time of
the day's status or of an event (:func:`_lone_clocks`, :data:`_STATUS_TIME`: "Closed Thursday
\u00b7 7:14 AM", "Thursday: Closed. 7:14 AM", "Closed Thursday. 7:14 AM update", "Closed
Thursday. Released 7:14 AM", "Closed Thursday | Fr 9:14 PM", "Closed Thursday. 7:14 AM upd"),
after the read on the read's day
makes :func:`stamp_dates` give an unreadable stamp: the row went up at that time on an earlier
day, which it does not say ("Closed Thursday. Updated 9:14 PM" read Thursday at 06:00 is held,
as "Closed Thursday 9:14 PM" is). At or before the read it bounds nothing. The date path reads
no such stamp. Each row is read in time linear in its length, however many clock times,
weekdays or stamps it holds.

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
gives no day of its own and is bounded as every age is. A stamp of the read's day at a clock
time after the read ("Posted Thu 6:02 AM" or "Updated 11/5 6:30 AM" read at 06:00) is
unreadable: it may be the same weekday's a week before. On the weekday path the resolver holds
a row whose stamp, dated or not, falls two or more days before the read
(:data:`snowlight.live.resolve.STAMP_LATEST_BACK`: "Updated Fri 10/30" read Thursday Nov. 5).
The same guards keep a date from dating its row: "Closed until Nov. 5", "Classes resume Nov.
5", "Closed Nov. 5-6", "Closed Nov. 5 (1w)", "Closed Nov. 5 1029" and "Closed Nov. 5; open
since" state no date for this rule.

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
import sys
from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Iterator
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from functools import lru_cache
from typing import Final, NamedTuple
from zoneinfo import ZoneInfo

from snowlight.classify.dates import WEEKDAYS as READER_WEEKDAYS
from snowlight.classify.text import clock_time as reader_clock
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
_GLUED_WEEKDAY: Final = re.compile(
    rf"_(?:{'|'.join(_SPELLINGS)})(?![^\W_])|(?<![^\W_])(?:{'|'.join(_SPELLINGS)})_",
    re.IGNORECASE,
)
"""A weekday glued to a "_" ("5:14 AM| . _Friday", "Closed_Thursday"), which :data:`_WEEKDAY`
does not find: what it is in the words cannot be read, so the words date their row by no
weekday (:func:`named_weekdays`)."""
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
    r"next|last|weekend|week|ago|previously|earlier|was|wasn['\u2019]?t|were|weren['\u2019]?t|had)\b",
    re.IGNORECASE,
)
"""Day words whose meaning depends on when the row was posted, and words that put the
status before it ("previously", "earlier", "was", "were", "had been")."""
_COUNTS: Final = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}  # fmt: skip
"""Counts written as words that an age ("two hours ago") is read with."""
_UNITS: Final = (
    (re.compile(r"m|mins?|minutes?", re.IGNORECASE), timedelta(minutes=1)),
    (re.compile(r"h|hrs?|hours?", re.IGNORECASE), timedelta(hours=1)),
    (re.compile(r"d|days?|dys?", re.IGNORECASE), timedelta(days=1)),
    (re.compile(r"w|wks?|weeks?", re.IGNORECASE), timedelta(weeks=1)),
    (re.compile(r"mos?|mths?|months?", re.IGNORECASE), timedelta(days=28)),
    (re.compile(r"y|yrs?|years?", re.IGNORECASE), timedelta(days=365)),
)
"""Each unit an age is read in, and the least it can be (a month at least four weeks)."""
_AGE: Final = re.compile(
    # every age starts with a digit or one of these letters: read only from there, so each
    # other place in the words is passed at once
    r"(?=[\dajotfsenmc])(?:"
    r"(?P<count>(?P<decimal>(?:(?<![\d.:])|(?<=[^\W\d_]\.))\d{1,3}\.\d{1,2}(?![\d.]))"
    r"|(?P<grouped>(?<![\d.:,/$#-])\d{1,3}(?:,\d{3})+(?![\d,])(?=\s*-?\s*(?:minutes?|mins?|m|hours?|"
    r"hrs?|h)\b))"
    r"|(?<!\d)(?:(?<!\d[.:,/-])|(?<=\d:\d\d[.,/:-])|(?<=\d,)(?=\d{1,2}(?!\d)))\d{1,5}|(?<![\w.:/,'\u2019$#-])(?:an?|one|two|three|four|"
    r"five|six|seven|eight|nine|ten|eleven|twelve|few|several|some|many|couple(?:\s+of)?))"
    r"(?P<gap>\s*-?\s*)"
    r"(?P<unit>minutes?|mins?|m|hours?|hrs?|h|days?|dys?|d|weeks?|wks?|w|months?|mths?|mos?|years?|"
    r"yrs?|y)\b(?P<ago>\.?\s*ago\b)?"
    r"|(?P<now>\b(?:just\s+now|(?:a\s+)?(?:few\s+)?(?:moments?|seconds?|secs?)\s+ago)\b)"
    r"|(?P<ambiguous>(?=\d)(?<![\w.:,/$#-])\d{1,3}(?:[. ]\d{3})+(?![\d.,])"
    r"(?=\s*-?\s*(?:minutes?|mins?|m|seconds?|secs?|s)\b))"
    r"|(?P<seconds>(?=\d)(?<![\w.:,/$#-])(?:\d{1,3}(?:,\d{3})+|\d{4,6})(?![\d.,]))"
    r"(?:\s*-?\s*(?:seconds?|secs?)|\s+s|(?<=,\d{3})s)\b(?:\.?\s*ago\b)?"
    r")",
    re.IGNORECASE,
)
"""An age in the words: how long before it was read the row was posted ("(1w)", "6d", "2h",
"5m", "3 days ago", "an hour ago", "just now"), or a length of time ("2 days"). A count is
read glued to what comes before it as well ("Thursday,5d", "Thursday.5d", "Thursday:6d",
"Thursday/6d", "Thursday5d") or to a clock time ("Thursday 6:00,5d", "Thursday 6:00:5d"), and
a decimal one as what it says ("1.5d", "1.5 days ago": a day and a half; glued to a word's "."
too: "Thursday.1.5d"), a count in thousands groups before a minute or hour unit as its whole
number ("2,880 min", "1,440 m": a day or more), and one of one or two digits after a number and
a comma ("11/5,5d"), never as the end of another number: a clock time, a date, a thousands
group or a range ("10:30m", "11/5d", "3-6 hours")."""
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
_A_SECOND: Final = timedelta(seconds=1)
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


_RANGE_END: Final = re.compile(
    r"(?:\d[ \t]*(?:-|\u2013|\u2014|to\b)|\bbetween[ \t]+\d{1,2}[ \t]+and)[ \t]*\Z", re.IGNORECASE
)
"""A number and a dash or "to", or "between", a number and "and", right before a count: the count
ends a span ("9 to 3 hours", "1 - 2w", "between 9 and 3 hours"), an age or a length that cannot be
read exactly (a delay's, "delayed 2 to 3 hours", is none)."""


@lru_cache(maxsize=4096)
def _ages(text: str) -> tuple[tuple[re.Match[str], timedelta | None], ...]:
    """Each age in ``text`` and how long it is (see :func:`post_ages`), read once for each
    words (the row's own and its weekday words are often the same)."""
    return tuple(_each_age(text))


def _each_age(text: str) -> Iterator[tuple[re.Match[str], timedelta | None]]:
    """Each age in ``text`` and how long it is, in order (:func:`_ages`)."""
    for found in _AGE.finditer(text):
        if found.group("now"):
            yield found, timedelta(0)
            continue
        if found.group("ambiguous"):
            yield found, None  # "1.440 min", "1 440 min": a day, or a minute and a half
            continue
        if found.group("seconds"):
            # "86,400 s", "86,400s", "3600 sec"; never a decade ("the 1990s")
            yield found, int(found.group("seconds").replace(",", "")) * _A_SECOND
            continue
        count, ago = found.group("count").casefold(), found.group("ago") is not None
        unit = next(size for pattern, size in _UNITS if pattern.fullmatch(found.group("unit")))
        if found.group("grouped"):
            yield found, int(count.replace(",", "")) * unit  # "2,880 min": two days
            continue
        if found.group("decimal"):
            decimal = float(count) * unit  # "1.5d": a day and a half
            if not (unit < _A_DAY and not ago and _a_delay(text, found, decimal)):
                yield found, decimal  # "2.5 hr delay" is a delay's length
            continue
        if not count.isdigit() and len(found.group("unit")) == 1:
            continue  # "a m", "an h": no age
        if count.isdigit() and len(count) > _LONGEST_COUNT and unit != _A_MINUTE:
            continue  # a year or a clock time: "2024 y", "0530 hrs"; only "1440m" is an age
        ranged = count.isdigit() and (
            _RANGE_END.search(text, max(0, found.start() - _BEFORE_WINDOW), found.start())
            is not None
        )
        length = (
            None  # "1 - 2w", "9 to 3 hours": the end of a span, read exactly as no age
            if ranged
            else int(count) * unit
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


_GLUED: Final = re.compile(r"[\w.:/,'\u2019$#-]")
"""What an age's count may be glued to: before round 6, :data:`_AGE` read no count right after
one of these, and it reads a count in every place it read one then."""


def _without_ages(words: str) -> str | None:
    """``words`` without the ages under a day they give ("2h ago", "5m", "just now"): the
    resolver bounds the row by them from the read time (:func:`post_ages`). ``None`` when they
    give one of a day or more, or one that cannot be read ("(1w)", "6d", "3 days ago"). An
    age under a day glued to what comes before it ("Thursday,2h") is left in the words: the
    rules there read it as they did before such ages were read, so reading them only holds."""
    kept: list[str] = []
    at = 0
    for found, age in _ages(words):
        if age is None or age >= _A_DAY:
            return None
        if (
            found.group("decimal")
            or found.group("grouped")
            or found.group("seconds")
            or _GLUED.match(words, max(0, found.start() - 1), found.start())
        ):
            continue  # "Thursday,2h", "3-6 hours", "1.5 hr": left as it was
        kept.append(words[at : found.start()])
        at = found.end()
    kept.append(words[at:])
    return " ~ ".join(kept)  # a mark no word or number rule reads past ("Sunday. 4-H Club")


_REOPENED: Final = re.compile(
    r"\b(?:open(?:ed)?\s+(?:again\s+)?since|re-?open(?:ed|ing|s)?|resum(?:e|ed|es|ing)|"
    r"open(?:ed|ing|s)?\s+(?:again|once\s+more|anew)|back\s+open|ended|expired|no\s+longer|"
    r"(?:is|are|now|all|it\s+is|it['\u2019]?s|that['\u2019]?s)\s+over|"
    r"back\s+in\s+session|(?:is|are)\s+in\s+session|(?:open\w*|start\w*|running)\s+on\s+time|"
    r"back\s+to\s+(?:school|class(?:es)?|normal|regular)|"
    r"(?:normal|regular|usual)\s+(?:schedule|day|hours|time|classes|operations|session)|"
    r"as\s+(?:normal|usual)|now\s+open|(?:has|have)\s+(?:now\s+)?(?:ended|reopened|resumed)|"
    r"lifted|all\s+clear|(?:closures?|closings?|delays?|cancell?ations?)\s+(?:is\s+|are\s+|has\s+|"
    r"have\s+)?(?:been\s+)?(?:now\s+)?(?:over|ended|done|cancell?ed|called\s+off|rescinded|"
    r"revoked|lifted))\b"
    r"|\bover\s*(?=[^\w\s]|\Z)",
    re.IGNORECASE,
)
"""Words that say the school is open again or back on its schedule ("open since", "reopened",
"resumed", "back in session", "is in session", "open on time", "classes resume", "normal
schedule", "all clear", "open again", "back open", "open once more"), or that the closure or
delay is over ("closure over", "is over", "(over)", "[over]", "*over*", "- over", "over" ending
the words or a clause, "ended", "expired", "no longer", "delay cancelled", "closing
rescinded"): the row may report a closure that has ended, so its words date it by no day."""
_VOID: Final = re.compile(
    r"\b(?:revoked|rescinded|withdrawn|reversed|retracted|resolved|voided|archived?|"
    r"(?:not|no\s+longer)\s+in\s+effect|in\s+error|never\s*mind|ignored?|disregard\w*|"
    r"past\s+(?:events?|posts?|notices?|alerts?|closings?|closures?|delays?|news|items?))\b"
    r"|(?:\A|[(\[{*~|/\u00b7\u2022:;,.!?\n-])[ \t]*(?:old|past|expired)[ \t]*"
    r"(?=[)\]}*~|/\u00b7\u2022:;,.!?\n-]|\Z)"
    r"|\bcorrect(?:ions?|ed)\b"
    r"|\bupdates?\b[ \t]*[:\-\u2013\u2014][^.;|\n]{0,40}?\bopen\w*\b",
    re.IGNORECASE,
)
"""Words that void the post or say it is an old one, in either order around its status
("Revoked. Closed Thursday", "Closed Thursday rescinded", "(old)", "Old. Closed Thursday",
"Archived", "Past event", "Not in effect", "Sent in error", "Nevermind", "Ignore previous"),
and an update heading that says the school is open ("Update: open. Closed Thursday", "Update -
school open"): read over all the words, its stamps too, the row is dated by no day."""
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
    """The weekday (Monday 0) a :data:`_WEEKDAY` match is: its one named group, "w0" to "w6"."""
    group = found.lastgroup
    if group is not None and group.startswith("w"):
        return int(group[1:])
    return next(number for number in range(len(_SPELLINGS)) if found.group(f"w{number}"))


def weekdays_in(names: Iterable[str]) -> frozenset[int]:
    """The weekdays (Monday 0) any of ``names`` holds as a word ("Friday Harbor SD": Friday):
    a weekday a directory name of the row's schools or districts holds is never read from
    its words."""
    return frozenset(_weekday_of(found) for name in names for found in _WEEKDAY.finditer(name))


_NEXT_WORD: Final = re.compile(r"[ \t]+(?P<word>[^\W\d_][\w'\u2019-]*)")
"""The word right after a weekday, with nothing but spaces between (no clause mark)."""
_STATUS_WORDS: Final = frozenset(
    {
        "closed", "closing", "closings", "closure", "closures", "close", "cancel", "canceled",
        "cancelled", "cancels", "cancellation", "cancellations", "delay", "delayed", "delays",
        "late", "start", "starts", "early", "dismissal", "dismissed", "dismissing", "release",
        "released", "out", "off", "remote", "virtual", "online", "e-learning", "elearning",
        "nti", "ami", "flex", "flexible", "learning", "instruction", "no", "school", "schools",
        "class", "classes", "activities", "activity", "events", "event", "sports", "athletics",
        "practice", "practices", "programs", "program", "open", "opening", "opens", "normal",
        "regular", "schedule", "session", "sessions", "bus", "buses", "routes", "transportation",
    }
)  # fmt: skip
"""Words that say what a school does on a day: a weekday with one of them in its clause is a
day the words are for, never a posting stamp (:func:`_clock_stamps`)."""
_PLAIN_AFTER: Final = frozenset(
    _STATUS_WORDS
    | {
        # more status words
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
    r"\b(?:issued|released|sent(?:\s+out)?|(?:put|went|going|goes|send|sends|sending)\s+out|"
    r"announced|published|shared|e-?mailed|mailed|tweeted|texted|notified|informed|alerted|"
    r"messaged|communicated|broadcast(?:ed)?|called|reported|confirmed|"
    r"circulated|distributed|decided|approved)"
    r"(?P<object>(?:[ \t]+[^\W\d_][\w'\u2019-]*){0,4}?)[ \t]+(?:on[ \t]+)?\Z"
    r"|\b(?P<notice>alerts?|messages?|notifications?|notices?|announcements?|e-?mails?|texts?|"
    r"letters?|statements?|tweets?|calls?|posts?|updates?|news|decisions?|robocalls?|"
    r"bulletins?)[ \t]+(?:(?:sent|issued|from|of|dated|made|given|posted|reached)[ \t]+)?"
    r"(?:on[ \t]+)?\Z",
    re.IGNORECASE,
)
_POSTING_AFTER: Final = re.compile(
    r"\s+(?:post|posts|posting|notice|notices|message|messages|announcement|announcements|"
    r"update|updates|e-?mail|e-?mails|letter|alert|alerts|statement|tweet|newsletter|news|"
    r"call|calls|decision|press|texts?|notifications?|release|robocalls?|bulletins?)\b",
    re.IGNORECASE,
)
"""Words just around a weekday that make it the day a notice went out, not a day the row is
for: a verb that sends a notice, with an object of up to four words that are no status words
or none ("Issued Friday", "Released Friday", "sent out Friday", "notified families Friday",
"notified all parents and staff Friday", "confirmed Friday"; "called off Friday" names
Friday), a notice word before it after other words ("Closed Thursday, message Friday", "alert
sent Friday", "update Friday", "decision made Friday"; never as the words' first: "Alert
Sunday. Online service only") or after it ("Friday post", "Friday notice", "Friday text",
"Friday release"), or a possessive ("per Friday's notice")."""
_BARE_PART_AFTER: Final = re.compile(
    r"[ \t]+(?:late|early|[ap]\.?[ \t]?m\b\.?)"
    r"(?=[ \t]*(?:[.;,:/|!?()\n\u00b7\u2022\u2027\u2219]|[ \t][-\u2013\u2014][ \t]|\Z))",
    re.IGNORECASE,
)
"""A bare "late", "early", "AM" or "PM" ending a weekday's clause ("Closed Thursday \u00b7 Friday
late", "Closed Thursday \u00b7 Friday PM"): with no status word before the weekday in its clause
it says neither a status nor a time exactly (a late start, a time of the post), and the words
name no day."""
_POSTING_WINDOW: Final = 48
"""How far before a weekday a notice verb and its object are read (:data:`_POSTING_BEFORE`)."""
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
    glued = after is not None and words[after.end() : after.end() + 1].isalpha()  # "5d", "5x"
    before = _DAY_NUMBER_BEFORE.search(words, max(0, start - _BEFORE_WINDOW), start)
    if before is not None and _NOT_A_DAY_BEFORE.search(
        words, max(0, before.start() - _BEFORE_WINDOW), before.start()
    ):
        before = None  # "Opening at 9 Tuesday", "Bus 5 Thursday": a time or a number
    if another(after, marked=glued or (after is not None and bool(after.group("mark")))) or another(
        before, marked=False
    ):
        return True
    if _BARE_PART_AFTER.match(words, found.end()) and not any(
        word.casefold() in _STATUS_WORDS
        for word in _A_WORD.findall(
            _DELAY_CLAUSE.split(words[max(0, start - _POSTING_WINDOW) : start])[-1]
        )
    ):
        return True  # "Closed Thursday \u00b7 Friday late": a late start, or a post's time
    posting = _POSTING_BEFORE.search(words, max(0, start - _POSTING_WINDOW), start)
    if posting is not None and posting.group("notice") and not words[: posting.start()].strip():
        posting = None  # "Alert Sunday. Online service only": the alert's own day, as a heading
    if (
        posting is not None
        and not any(
            word.casefold() in _STATUS_WORDS
            for word in _A_WORD.findall(posting.group("object") or "")
        )
    ) or _POSTING_AFTER.match(words, found.end()):
        return (
            True  # "Issued Friday", "notified families Friday", "Friday post": when it was posted
        )
    possessive = _POSSESSIVE.match(words, found.end())
    return possessive is not None and (
        possessive.group("word") is None or possessive.group("word").casefold() not in _POSSESSED
    )


_CLOCK_TEXT: Final = (
    r"(?:\d{1,2}(?::\d{2}){0,2}\s*[ap]\.?\s?m(?![^\W_])\.?|\d{1,2}:\d{2}(?::\d{2})?(?!\d)|noon(?![^\W_])|"
    r"midnight(?![^\W_]))(?:\s*\(?(?:[ecmp][sd]?t|ak[sd]?t|h[sd]?t|gmt|utc)\b\)?)?"
)
"""A clock time, with its US zone (the reader's, :mod:`snowlight.classify.text`; never a
month: "5:30 AM Oct. 29"), glued to a "_" after it too ("9:14 PM_ Friday")."""
_ABOUT_WORD: Final = r"(?:\b(?:around|about|approx(?:imately|\.)?|circa|ca\.)|~)"
_ABOUT: Final = rf"{_ABOUT_WORD}[ \t]*"
"""A word that makes a clock time an approximate one ("around 9 PM", "about 9:14 PM")."""
_BARE_HOUR: Final = r"\d{1,2}(?:[ \t]*o['\u2019]?clock\b|(?![\w:\u2019']|[.,]\d))"
"""An hour with no minutes and no "a.m." or "p.m.", a clock time only after "at", "@" or an
approximation word ("Friday at 9", "around 9", "at 9 o'clock")."""
_HHMM_TEXT: Final = (
    r"(?:(?:00|1[3-9]|2[0-3])[0-5]\d(?![\d:])(?:[ \t]*(?:hrs?|hours)\b)?"
    r"|(?:0[1-9]|1[0-2])[0-5]\d(?![\d:])"
    r"(?=[ \t]*(?:hrs?|hours)\b|[ \t]*(?:-|\u2013|\u2014|to\b)[ \t]*(?:[01]\d|2[0-3])[0-5]\d(?!\d))"
    r"(?:[ \t]*(?:hrs?|hours)\b)?"
    r"|(?:0?[1-9]|1[0-2])[0-5]\d[ \t]*[ap]\.?[ \t]?m(?![^\W_])\.?)"
)
_HHMM: Final = rf"(?<![\d:./]){_HHMM_TEXT}"
"""A clock time with no colon: a 24-hour one that cannot be a month and day ("2114", "1530
hrs"), one from 01:00 to 12:59 with "hrs" or "hours" after it or starting a span of such times
("0514 hrs", "0900-1500", "1000 to 1200"), or one with "a.m." or "p.m." ("1030 am", "930pm");
right after a weekday and its marks (:data:`_CLOCK_AFTER`) with nothing before it to check."""
_ZERO_HHMM: Final = r"0[1-9][0-5]\d(?![\d:])"
"""A 24-hour clock time with a leading zero ("0900"): one right after a weekday and its marks
("Thursday 0900"), which no month and day reads ("0900" is none; "0530" may be May 30 and keeps
the hold as a number, :func:`_numbers_name`)."""
_MARK: Final = r"(?:[^\w\s]|_)"
_MARK_RUN: Final = rf"(?:{_MARK}++[ \t]*+)+"
"""A run of marks (any character that is no letter, digit or space, and "_"), as long as it
is, with spaces or none between: between a weekday and its clock time, either way round, it is
a stamp mark ("Friday: 9:14 PM", "Friday...9:14 PM", "Friday::9:14 PM", "Friday _9:14 PM",
"Friday ,.9:14 PM", "9:14 PM-- Friday", "9:14 PM ----- Friday", "9:14 PM\u2013 Friday", "9:14
PM - Friday"), read as a stamp's only when the weekday is one (:func:`_clocked`); a clock time
may start right after it. Each mark and the spaces after it are read once (possessively), so a
long run is read in time linear in its length."""
_MARK_LINES: Final = rf"(?:{_MARK}++\s*+)+"
"""A run of marks (:data:`_MARK_RUN`) with line breaks between too ("Thursday:\\n45", "45\\n\u00b7
Thursday"): what parts a bare number or a span of hours from a weekday (:data:`_BY_MARKS`), as
a line break parts a clock time from it past its marks (:func:`_past_marks`)."""
_CLOCK_START: Final = (
    r"(?:(?<![\w:./$#,])|(?<=\D[:./,])|(?<=[^\w\s][$#])|(?<=[$#])(?=[^\W\d_])|(?<=_))"
)
"""Where a clock time or a span of hours in a weekday's clause may start: never glued to a word
or to another number ("10:30", "1.5", "11/5", "$9", "#9"; "#between 9 and 3" is no number), but
right after a run of marks, as long as it is, glued to it too ("Thursday:9 to 3", "Thursday...9
to 3", "Thursday//9 to 3", "Friday!#9 to 3", "Friday _9 to 3", "Thursday|,9 to 3", "Friday
\u25cf ,9 to 3"): every clock reader here starts there."""
_HOUR: Final = r"(?:[01]?\d|2[0-4])"
_HOUR_SPAN_TEXT: Final = (
    rf"(?:between[ \t]+{_HOUR}[ \t]+and[ \t]+{_HOUR}"
    rf"|{_HOUR}[ \t]*(?:-|\u2013|\u2014|to\b|until\b|till\b|thru\b|through\b)[ \t]*{_HOUR})"
    r"(?![^\W_]|[:.,]\d)"
    r"(?![ \t]*(?:[\u00b0%\"\u2033\u201d]|(?:degrees?|deg|inch(?:es)?|in(?![ \t]+effect)|feet|"
    r"foot|ft|cm|mm|percent|mph|miles?|mi|students?(?![ \t]+(?:reports?|arriv\w*))|kids|children|"
    r"people|grades?|years?|yrs|months?|weeks?|"
    r"days?|games?|points?|pts|wins?|losses?|goals?|runs?|record|below|above|wind)\b))"
)
_HOUR_SPAN: Final = re.compile(rf"{_CLOCK_START}{_HOUR_SPAN_TEXT}", re.IGNORECASE)
"""A span of bare hours in a weekday's clause ("9 to 3", "9 - 3", "between 9 and 3"), with no
unit or count word after it that makes it a span of something else ("0-5 degrees", "2 to 4
inches", "3-5 students", "4 to 6 days"; "9 to 3 students report", "9 to 3 in effect" are
hours): read
there as a span of clock times (:func:`_inner_clock`), so a weekday it stands by with no status
or event word is a posting stamp as one with "9 AM - 3 PM" is."""
_CLIPPED: Final = r"\d{1,2}(?::\d{2})?[ \t]*[ap]\.?"
_H_CLOCK: Final = r"(?:[01]?\d|2[0-3])h[0-5]\d"
_OTHER_SPAN_TEXT: Final = (
    rf"(?:{_CLIPPED}|{_H_CLOCK})[ \t]*(?:-|\u2013|\u2014|to\b|until\b|till\b)[ \t]*"
    rf"(?:{_CLIPPED}|{_H_CLOCK})(?![^\W_])"
)
_INNER_CLOCK: Final = re.compile(rf"{_CLOCK_START}(?:{_CLOCK_TEXT}|{_HHMM_TEXT})", re.IGNORECASE)
"""A clock time standing on its own in a weekday's clause ("Friday closed 9:14 PM"), right
after a run of marks too ("Friday closed...9:14 PM"), never the end of another number
(:data:`_CLOCK_START`)."""
_DAYPART: Final = (
    r"(?P<part>(?:(?:late|early)[ \t]+)?(?:morning|afternoon|evening|night|overnight))\b"
)
"""A part of the day right after a weekday ("Closed Thursday \u00b7 Friday evening"): a time
only for a posting stamp, since a status's day is often named with one ("Activities cancelled
Friday evening")."""
_CLOCK_AFTER: Final = re.compile(
    rf"[ \t]*(?P<mark>{_MARK_RUN})?"
    rf"(?P<clock>(?:(?:at|@)[ \t]*)?(?:{_ABOUT})?(?:{_CLOCK_TEXT}|{_HHMM_TEXT}|{_ZERO_HHMM})"
    rf"|(?:(?:at|@)[ \t]*(?:{_ABOUT})?|{_ABOUT}){_BARE_HOUR}|{_DAYPART})",
    re.IGNORECASE,
)
"""A clock time right after a weekday ("Fri 9:14 PM", "Sat 7:12am", "Wed. 2 a.m.", "Friday at
noon", "Friday at 9", "Friday around 9 PM", "Fri 2114", "Friday evening"), or after a run of
marks (:data:`_MARK_RUN`: "Friday, 21:14", "Friday (9:14pm)", "Friday [9:14 PM]", "Friday
\\"9:14 PM\\"", "Friday...9:14 PM")."""
_MONTH_WORD: Final = rf"(?:{'|'.join(MONTHS)})"
_A_LENGTH: Final = (
    r"[ \t]*-?[ \t]*(?:(?:and[ \t]+a[ \t]+half|1/2|\u00bd)[ \t]*-?[ \t]*)?"
    r"(?:hours?|hrs?|h|minutes?|mins?)\b"
)
_BARE_NUMBER: Final = (
    rf"(?P<bare>\d{{1,2}})(?![^\W_]|[:.,/\-\u2013\u2014]\d|{_A_LENGTH}"
    rf"|[ \t]*{_MONTH_WORD}\b)"
)
"""A bare number of one or two digits that is no part of a clock time, a date, a decimal or
a count with a delay's length unit ("9", "9_", "9'", never "9:14", "11/5", "1.5", "5 Nov", "2
hour delay", "2-hr. delay", "2 1/2 hour delay", "90 minute late start", "2 hours behind"): by a
weekday's run of marks, on either side of it, a stamp's number that cannot be read."""
_SPAN_AFTER_MARKS: Final = re.compile(
    rf"\s*(?P<mark>{_MARK_LINES})"
    rf"(?P<clock>{_HOUR_SPAN_TEXT}|{_OTHER_SPAN_TEXT}|{_BARE_NUMBER})",
    re.IGNORECASE,
)
"""A span of hours (:data:`_HOUR_SPAN`, :data:`_OTHER_SPAN`) right past a run of marks right
after a weekday, glued to it too ("Friday#9 to 3", "Thursday:9 to 3"), or a bare number
(:data:`_BARE_NUMBER`) there, with words after it or none ("Thursday...9", "Thursday ... 9",
"Thursday: 9 | info"): hours, or a stamp's number that cannot be read, so a weekday with no
status word in its clause is a stamp that :func:`stamp_dates` reads as unreadable; with a status
word it is read as it was before ("Closed Thursday: 9", "Closed Thursday:9 to 3"), and a delay's
length is read as before ("Thursday: 2 hour delay")."""
_BARE_BEFORE_MARKS: Final = re.compile(
    rf"(?<![\w\u00bd])(?<!\d[:./,])(?P<clock>{_BARE_NUMBER})\s*(?P<mark>{_MARK_LINES})"
    rf"(?:(?:on|at)\s+(?P<open>{_MARK_LINES})?)?\Z",
    re.IGNORECASE,
)
"""A bare number (:data:`_BARE_NUMBER`) right before a run of marks right before a weekday,
glued or spaced ("10.Thursday", "9...Thursday", "9:: Thursday"), with a mark glued before it
too ("#12 :: Thursday", ":9 \u00b7 Thursday", "$9 \u00b7 Thursday"), as :data:`_SPAN_AFTER_MARKS`
reads one after: a stamp's number that cannot be read when no status word is in the weekday's
clause, and read as before with one; never the end of a clock time, a date or a decimal ("10:30",
"11/5", "1.5", "1,5": a digit before its mark), and never a month's day number ("Nov. 5 \u00b7
Thursday", :data:`_MONTH_BEFORE`)."""
_MONTH_BEFORE: Final = re.compile(rf"\b{_MONTH_WORD}\.?[ \t]*\Z", re.IGNORECASE)
_CLOCK_BEFORE: Final = re.compile(
    rf"(?P<clock>(?<![\w:./])(?:{_CLOCK_TEXT}|{_HHMM}|0[1-9][0-5]\d(?=[ \t]*{_MARK}))"
    rf"|(?:\bat|@|{_ABOUT_WORD})[ \t]*(?:{_ABOUT})?(?<![\w:./])\d{{1,2}}(?![\w:]))"
    rf"[ \t]*(?P<mark>{_MARK_RUN})?(?:(?:on|at)[ \t]+(?P<open>{_MARK_RUN})?)?\Z",
    re.IGNORECASE,
)
"""A clock time right before a weekday, with nothing but spaces, a run of marks
(:data:`_MARK_RUN`), "on" or "at" between ("9:14 PM Fri", "21:14 Fri", "9:14 PM, Friday", "at
9:14 PM Friday", "(9:14 PM) Friday", "9:14 PM-- Friday"), and a 24-hour one with a leading zero
before a run of marks ("0900: } Friday", as :data:`_ZERO_HHMM` after one)."""
_BY_MARKS: Final = (_SPAN_AFTER_MARKS, _BARE_BEFORE_MARKS)
"""What a weekday's run of marks parts from a span of hours or a bare number by it: a stamp's
hours or number when no status word is in its clause, and with one read as before."""
_CLOCK_BEFORE_WINDOW: Final = 40
"""How far before a weekday a clock time right before it is read."""
_OWNS_CLOCK: Final = re.compile(
    r"\b(?:(?:delay\w*|late|early|dismiss\w*|start\w*|release\w*|open\w*)\b"
    r"|clos(?:e|es|ing)\s+(?:early\s+)?(?:at|by)\b|clos(?:e|es|ing)\s*@)",
    re.IGNORECASE,
)
"""Words in a weekday's clause that make its clock time when the school starts, opens, closes
or lets out on that day ("Early dismissal Thursday 1:30 PM", "Thursday 10 AM start", "Opening
at 10 AM Thursday", "Closing at 3 p.m. Friday", "Thursday: dismiss at 1:30"). With a status or
an event word in the clause they own any clock time or span; otherwise, as words the status
reader reads no status from ("dismiss", "starting", "started", "opened", "releasing"), only a
single clock time in the weekday's own clause with no mark between, "at" or "@" between them
or not ("Closed Wednesday \u00b7 Thursday | dismiss 9:14 PM", "Closed Wednesday \u00b7
Thursday | starting (8:30-3:15)", "Closed Wednesday \u00b7 Thursday: started at 9:14 PM",
"Closed Wednesday \u00b7 Thursday opened at 9 to 3" are stamps), save a dismissal at a time
the reader reads as one (:func:`_dismissed_at`: "Thursday: dismiss at 1:30")."""
_OWNS_ONE: Final = re.compile(r"\b(?:begin\w*|effect\w*)\b", re.IGNORECASE)
"""Words in a weekday's clause that make its clock time when a notice begins or takes effect
on that day ("In effect at 5 p.m. Saturday", "Thursday begins 5 a.m."): no status word, so they
own only a single clock time in the weekday's own clause, never a span of hours or one past its
marks ("Closed Wednesday \u00b7 Thursday | begins (8:30-3:15)", "Closed Wednesday \u00b7 Thursday
in effect 9 to 3" are stamps), as :data:`_OWNS_WITH` does."""
_OWNS_WITH: Final = re.compile(
    r"\b(?P<who>(?:staff|students?|teachers?|employees?|faculty|everyone)[ \t]+)?"
    r"(?:reports?|arriv\w*)\b",
    re.IGNORECASE,
)
"""Words that make a weekday's clock time a time on that day only with a status or an event
word in its clause, or with who it is for right before ("Closed Thursday, report 10 AM",
"Staff report Thursday 9 AM", "Students arrive 7:45 AM Thursday"): on their own they own no
clock time, and the weekday is a posting stamp ("Closed
Wednesday \u00b7 Thursday report 5:14 AM", "Closed Wednesday \u00b7 Thursday arrival 7:45
AM")."""


def _owned_by_words(clause: str, tight: str | None, *, dismissed: bool) -> bool:
    """Whether a word owns a weekday's clock time: in its ``clause``, a start, opening, closing
    or dismissal word (:data:`_OWNS_CLOCK`) or a report or an arrival (:data:`_OWNS_WITH`) with
    a status or an event word there (:func:`_a_status_or_event`), or a dismissal at the single
    clock time the reader reads as one (``dismissed``, :func:`_dismissed_at`: "Thursday:
    dismiss at 1:30"); and, only when the clock time is a single one in the weekday's own
    clause with no mark between them (``tight``, the words between and around both up to the
    first mark each way, else ``None``: :func:`_tight`), any of :data:`_OWNS_CLOCK`,
    :data:`_OWNS_ONE` or :data:`_OWNS_WITH` with who it is for there ("Thursday begins 5
    a.m.", "Staff report Thursday 9 AM"). An owner word that is no status word owns no span of
    hours and no clock time past a mark, wherever it stands and "at" or "@" after it or not
    ("Closed Wednesday \u00b7 Thursday | begins (8:30-3:15)", "Closed Wednesday \u00b7 in
    effect Thursday: 9:14 PM", "Closed Wednesday \u00b7 9:14 PM: Thursday begins", "Closed
    Wednesday \u00b7 Thursday | dismiss 9:14 PM", "Closed Wednesday \u00b7 Thursday = begin
    9:14 PM", "Closed Wednesday \u00b7 Thursday: started at 9:14 PM" are stamps)."""
    if dismissed:
        return True
    clause = _HOURS_OF.sub(" ", clause)
    if (
        _OWNS_CLOCK.search(clause) is not None or _OWNS_WITH.search(clause) is not None
    ) and _a_status_or_event(clause):
        return True
    if tight is None:
        return False
    tight = _HOURS_OF.sub(" ", tight)
    return (
        _OWNS_CLOCK.search(tight) is not None
        or _OWNS_ONE.search(tight) is not None
        or any(found.group("who") for found in _OWNS_WITH.finditer(tight))
    )


_OWNS_AT: Final = re.compile(r"\bdismiss\w*(?:[ \t]+at\b|[ \t]*@)[ \t]*\Z", re.IGNORECASE)
"""A dismissal word with "at" or "@" right before a clock time ("dismiss at 1:30", "dismisses
@ 12:30"): the one owner word that is no status word (:data:`_STATUS_WORDS`) the status reader
reads a status from with a time (:func:`_dismissed_at`)."""
_AT_CLOCK: Final = re.compile(
    rf"(?:(?:at|@)[ \t]*)?(?:{_ABOUT})?(?P<clock>\d{{1,2}}(?::\d{{2}})?(?:[ \t]*[ap]\.?[ \t]?m\.?)?"
    r"|noon)(?:[ \t]*\(?(?:[ecmp][sd]?t|ak[sd]?t|h[sd]?t|gmt|utc)\b\)?)?",
    re.IGNORECASE,
)
"""A single clock time as :data:`_CLOCK_AFTER` or :data:`_INNER_CLOCK` finds it, "at" and an
approximation word before it and its zone after it set apart (:func:`_dismissed_at`)."""
_DISMISSED_FROM: Final = time(8)
_DISMISSED_UNTIL: Final = time(13, 30)
"""The clock times a dismissal word at one is an early dismissal at for the status reader
(:mod:`snowlight.classify.mentions`: from 8 a.m., the earliest dismissal, up to 1:30 p.m., the
latest plain one; "dismiss at 3:00" is an ordinary afternoon and "dismiss at 9:14 PM" none)."""


def _dismissed_at(lead: str, text: str) -> bool:
    """Whether a dismissal word with "at" or "@" right before a single clock time ``text``
    (``lead`` the words right before it, :data:`_OWNS_AT`) is a dismissal on the weekday at a
    time the status reader reads as one (:data:`_DISMISSED_FROM` to :data:`_DISMISSED_UNTIL`,
    read as the reader reads a clock time, :func:`snowlight.classify.text.clock_time`: "1:30"
    is 1:30 p.m.): then it owns the clock time past the weekday's marks too ("Thursday: dismiss
    at 1:30", "Thursday | dismiss @ 1:30"); at any other time it owns only one in the weekday's
    own clause (:func:`_tight`: "Closed Wednesday \u00b7 Thursday | dismiss at 9:14 PM" is a
    stamp)."""
    text = text.strip()
    found = _AT_CLOCK.fullmatch(text)
    # "dismiss at 11 Thursday": the "at" may be the clock time's own
    if found is None or _OWNS_AT.search(f"{lead}{text[: found.start('clock')]}") is None:
        return False
    value = reader_clock(found.group("clock").casefold().replace(".", "").replace(" ", ""))
    return value is not None and _DISMISSED_FROM <= value <= _DISMISSED_UNTIL


_TIGHT_MARK: Final = re.compile(r"(?!['\u2019]s\b)(?:[^\w\s]|_)")
"""A mark (:data:`_MARK`) that parts an owner word, a weekday and its clock time, any of them,
other than a possessive's ("Thursday's staff report 9 AM")."""
_ABOUT_END: Final = re.compile(
    r"\b(?:around|about|approx(?:imately|\.)?|circa|ca\.)[ \t]*\Z", re.IGNORECASE
)
"""An approximation word right before a clock time ("around 9 AM", "approx. 9 AM"): part of
it. A "~" is a mark there as anywhere by a weekday (:data:`_MARK_RUN`: "Closed Wednesday
\u00b7 Thursday begins ~ 9:14 PM", "... Thursday begins ~9:14 PM" are stamps, as "Thursday ~
9:14 PM" is)."""


def _tight(
    words: str, weekday: re.Match[str], clock: tuple[int, int], clause: tuple[int, int]
) -> str | None:
    """The words in ``words`` between ``weekday`` and its clock time at ``clock`` and those
    that stand by them with no mark between any of them (:data:`_TIGHT_MARK`), in the weekday's
    clause from ``clause[0]`` to ``clause[1]``: those an owner word that is no status word owns
    a single clock time in (:func:`_owned_by_words`); ``None`` when a mark, or the "." a full
    weekday name ends with, parts the weekday from its clock time ("Thursday: 9:14 PM begins",
    "9:14 PM = Thursday begins", "Thursday # staff report 9:14 PM")."""
    at, end = clock
    about = _ABOUT_END.search(words, max(0, at - _BEFORE_WINDOW), at)
    at = at if about is None else about.start()
    ended = weekday.group(0).endswith(".") and len(weekday.group(0)) > _FULL_NAME
    if at >= weekday.end():
        if ended or _TIGHT_MARK.search(words, weekday.end(), at) is not None:
            return None
        low, high = weekday.start(), end
    else:
        if _TIGHT_MARK.search(words, end, weekday.start()) is not None:
            return None
        low, high = at, weekday.end()
    marks = list(_TIGHT_MARK.finditer(words, clause[0], low))
    first = clause[0] if not marks else marks[-1].end()
    last = high if ended else max(high, clause[1])
    mark = _TIGHT_MARK.search(words, high, last)
    last = last if mark is None else mark.start()
    # the weekday and the clock time are not their own owner words ("Friday late evening")
    cuts = sorted(((weekday.start(), weekday.end()), (at, end)))
    return " ".join(
        (words[first : cuts[0][0]], words[cuts[0][1] : cuts[1][0]], words[cuts[1][1] : last])
    )


_OPEN_UNTIL: Final = re.compile(r"\b(?:until|till|operat\w*|available)\b", re.IGNORECASE)
"""Words that make a clock time further on in a weekday's clause, or past its marks, the time
something on that day runs until ("Friday Evening: help desk available until 8:30 PM"): no posting
stamp's (:func:`_clocked_one`), unless it is a span of hours ("Thursday hours 9 AM until 3 PM"
is a stamp)."""
_EVENT: Final = (
    r"(?:mass(?:es)?|services?|worship|liturg\w*|bible\s+study|studies|study|practices?|"
    r"games?|matche?s?|meets?|meetings?|events?|rehearsals?|concerts?|performances?|shows?|"
    r"lessons?|testing|tests?|exams?|sessions?|programs?|activit(?:y|ies)|class(?:es)?|ccd|"
    r"religious\s+ed\w*|youth\s+group|(?:small\s+)?groups?|choir|toddler\s+time|story\s?time|"
    r"banquet|dinner|lunch|breakfast|practice|tournament|club|bingo|screening|clinic|prayers?)"
)
_EVENT_AFTER: Final = re.compile(rf"[ \t]*{_EVENT}\b", re.IGNORECASE)
_EVENT_WORD: Final = re.compile(rf"\b{_EVENT}\b", re.IGNORECASE)
_EVENT_BEFORE: Final = re.compile(
    rf"\b{_EVENT}[ \t]*(?:(?:at|@|from|is|are|begins?|starts?|for|before|after|until|till|by|on)"
    r"[ \t]*)?"
    r"(?:[\d:.apm \t]+(?:&|and|or|,|-)[ \t]*)?\Z",
    re.IGNORECASE,
)
"""An event a clock time is the time of, named right after it or right before it ("8 a.m.
mass", "10am Sunday worship", "No 8:30 AM service", "Services at 8:30 or 11:00 on Sunday"):
the clock time is the event's, not a posting stamp's, and owns no post's day."""
_CLOSES_BEFORE: Final = re.compile(
    r"\bclos(?:e|es|ing)(?:\s+early)?(?:\s+(?:at|by)\b|\s*@)?\s*\Z"
    r"|\bclosed(?:\s+early)?(?:\s+(?:at|by)\b|\s*@)\s*\Z",
    re.IGNORECASE,
)
_CLOSING_BEFORE: Final = re.compile(r"\bclos(?:e|es|ing)(?:\s+early)?\s*\Z", re.IGNORECASE)
_AT: Final = re.compile(r"(?:at|by)\b|@", re.IGNORECASE)
"""A closing time right before a clock time ("Closing 1pm Sunday", "Closed at 3 p.m.
Tuesday", "Closing early at noon"), or before a weekday whose clock time is "at" one
("Building closing Wednesday at 5pm"): the clock time is when the school closes that day,
no posting stamp; "Closed Friday 9:14 PM" is no closing time."""
_RANGE_AFTER: Final = re.compile(
    r"\s*(?:-|\u2013|\u2014|to\b|until\b|till\b|thru\b|through\b)\s*(?:\d|noon|midnight)",
    re.IGNORECASE,
)
_RANGE_BEFORE: Final = re.compile(
    r"(?:\d[ \t]*(?:[ap]\.?[ \t]?m\b\.?)?|noon|midnight)[ \t]*"
    r"(?:-|\u2013|\u2014|to\b|until\b|till\b|thru\b|through\b)[ \t]*\Z",
    re.IGNORECASE,
)
"""A span of hours a clock time starts or ends ("6 a.m. to 8 p.m. on Thursday", "from 9-11
Friday"): the hours of a status on that day, never a posting stamp's time."""
_LAST_CLAUSE: Final = re.compile(r"[\s.,;!)\]}\"'\u201d\u2019]*\Z")
"""Nothing but marks to the end of the words: a part of the day there is a posting stamp's
("Closed Thursday \u00b7 Friday evening"), never a heading's ("Thursday Afternoon: Closed")."""
_A_WORD: Final = re.compile(r"[^\W\d_][\w'\u2019-]*")
_STAMP_CLAUSE_WINDOW: Final = 80
"""How far before and after a weekday with a clock time its clause is read for a status word:
a status word further away makes it no day the row is for (it stays a stamp, which only
holds)."""
_PAST_MARKS_REACH: Final = 400
"""How far past the run of marks that ends a weekday's clause after it the clauses on to the
next weekday, or to the first with a status or an event word, are read for a clock time or a
span of hours (:func:`_past_marks`): far enough for any clause of words with no status word
there, and a bound that keeps each row read in time linear in its length."""
_FULL_NAME: Final = 6
"""Letters in the shortest full weekday name ("Monday"): a "." after one ends a sentence
("Closed Sunday. Online service 10:15 AM"), where one after "Sun." may not."""


class _Clocked(NamedTuple):
    """A weekday in a row's words with a clock time right before or after it, or in its
    clause."""

    start: int
    """Where the weekday stands in the words."""
    weekday: int
    """Which weekday it is (Monday 0)."""
    clock: str
    """Its clock time ("9:14 PM", "at 9", "21:14 CST")."""
    stamp: bool
    """Whether it is a posting stamp with no stamp word: its clock time right before or after
    it, and no status word in its clause and none that owns the clock time."""
    owned: bool
    """Whether a start, opening, closing or dismissal word in its clause, or an event named
    next to the clock time, owns the clock time."""
    end: int
    """Where the weekday and its clock time right by it end."""
    span: tuple[int, int]
    """Where its clock time stands in the words."""
    lone: bool = False
    """Whether its clock time, past a run of marks and owned by nothing, is read as one with no
    day, as :func:`_lone_clocks` reads one: the weekday's own clause names no time."""
    hours: bool = False
    """Whether its clock time starts or ends a span of hours ("9 AM - 3 PM", "8:30-3:15", "9 to
    3", "9a-3p") or is a bare number past a run of marks ("Thursday...9"): as a stamp it gives no
    time a row was posted at, and :func:`stamp_dates` reads it as unreadable."""


_ANY_CLOCK: Final = re.compile(r"\d|noon|midnight|morning|afternoon|evening|night", re.IGNORECASE)
_SENTENCE_END: Final = re.compile(r"\s+[A-Z]|\s*\Z")


@lru_cache(maxsize=4096)
def _mask_clocks(words: str) -> str:
    """``words`` with each clock time blanked, so the clause marks it holds ("10:00", "a.m.")
    end no clause; a "." that ends one before a capital or the end ("9 a.m. Closed") still
    does."""

    def blank(clock: re.Match[str]) -> str:
        text = clock.group(0)
        if text.endswith(".") and _SENTENCE_END.match(words, clock.end()):
            return " " * (len(text) - 1) + "."
        return " " * len(text)

    return _ABOUT_MASK.sub(lambda about: " " * len(about.group(0)), _STAMP_CLOCK.sub(blank, words))


_ABOUT_MASK: Final = re.compile(_ABOUT_WORD, re.IGNORECASE)
"""A word that makes a clock time an approximate one ("approx.", "ca."): blanked with the clock
times, so its "." ends no clause ("Thursday | from approx. 9 AM to 3 PM")."""


_CLIPPED_CLOCK: Final = re.compile(r"(?<![\w:./])\d{1,2}(?::\d{2})?[ \t]*[ap]\b\.?", re.IGNORECASE)
"""A clock time with its "a.m." or "p.m." cut short ("9 a", "9:14 p"): read in a weekday's
clause after it as a clock time (:func:`_clocks_in`), never a day ("Parking ban 6A Thursday" is
read as before)."""
_OTHER_SPAN: Final = re.compile(rf"{_CLOCK_START}{_OTHER_SPAN_TEXT}", re.IGNORECASE)
"""A span of clock times cut short ("9a-3p", "9 a to 3 p") or written with an "h" ("8h30-15h15"):
read on either side of a weekday as a span of hours (:class:`_Clocks`)."""


class _Clocks(NamedTuple):
    """The clock times (:data:`_INNER_CLOCK`), spans of bare hours (:data:`_HOUR_SPAN`), clock
    times cut short (:data:`_CLIPPED_CLOCK`) and spans of them (:data:`_OTHER_SPAN`) in some
    words, found once and sorted by where they start, so that each weekday's clause is read for
    them in time independent of the words' length. One that starts in a clause is read whole,
    past the clause's end too (a span's dash blanked with its clock times ends no clause:
    "8:30-3:15")."""

    found: list[re.Match[str]]
    starts: list[int]

    @classmethod
    def of(cls, words: str, weekdays: Iterable[re.Match[str]]) -> "_Clocks":
        """The clock times in ``words`` around each of ``weekdays``, as far as its clause, or
        the clause past its marks, is read (:data:`_STAMP_CLAUSE_WINDOW` and a run of marks
        each way, and the longest clock time past that), never over the rest of the words."""
        reach = 2 * _STAMP_CLAUSE_WINDOW + _LONGEST_CLOCK
        windows = _merged(
            (
                max(0, weekday.start() - reach),
                min(len(words), weekday.end() + reach + _PAST_MARKS_REACH),
            )
            for weekday in weekdays
        )
        found = sorted(
            {
                (*match.span(), index): match
                for start, stop in windows
                # a span cut short first: "9a-3p" is read whole, not as "9a"
                for index, pattern in enumerate(
                    (_OTHER_SPAN, _INNER_CLOCK, _HOUR_SPAN, _CLIPPED_CLOCK)
                )
                for match in pattern.finditer(words, start, stop)
            }.values(),
            key=lambda match: match.start(),
        )
        return cls(found, [match.start() for match in found])


_LONGEST_CLOCK: Final = 40
"""Characters in the longest clock time or span of hours read ("12:00:00 a.m. (CDT) - 1:00:00
p.m."): one that ends in a clause before a weekday is read, whatever clause it starts in."""


def _clocks_in(
    scan: "_Scan", start: int, stop: int, *, before: bool = False
) -> list[re.Match[str]]:
    """Each clock time, span of bare hours or clock time cut short (:class:`_Clocks`) that
    starts in ``scan.words`` from ``start`` to ``stop``, in order; ``before`` a weekday, each
    that ends there instead (a span's dash blanked with its clock times may end a clause in it:
    "8:30-3:15 hours on Thursday"), and never one cut short ("Parking ban 6A Thursday")."""
    clocks = scan.clocks
    first = bisect_left(clocks.starts, start - _LONGEST_CLOCK if before else start)
    return [
        match
        for match in clocks.found[first : bisect_left(clocks.starts, stop)]
        if not before or (match.end() > start and match.re is not _CLIPPED_CLOCK)
    ]


def _merged(spans: Iterable[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    """``spans`` sorted, those that overlap joined into one."""
    joined: list[tuple[int, int]] = []
    for start, stop in sorted(spans):
        if joined and start < joined[-1][1]:
            joined[-1] = (joined[-1][0], max(stop, joined[-1][1]))
        else:
            joined.append((start, stop))
    return tuple(joined)


def _taken(claimed: tuple[tuple[int, int], ...], at: int) -> bool:
    """Whether ``at`` stands in one of the spans ``claimed`` (:func:`_merged`)."""
    index = bisect_right(claimed, (at, sys.maxsize)) - 1
    return index >= 0 and claimed[index][0] <= at < claimed[index][1]


def _inner_clock(
    scan: "_Scan", after: tuple[int, int], before: tuple[int, int]
) -> re.Match[str] | None:
    """The first clock time or span of bare hours (:func:`_clocks_in`) in ``scan.words`` that
    starts in the span ``after`` a weekday or else ``before`` it, in its clause ("Friday closed 9:14
    PM", "9:14 PM closed Friday", "Thursday hours 8:30-3:15", "9 to 3 on Thursday"), and stands
    in no span ``scan.claimed`` by a weekday it is right by."""
    for inner in (*_clocks_in(scan, *after), *_clocks_in(scan, *before, before=True)):
        if not _taken(scan.claimed, inner.start()):
            return inner
    return None


def _owns(
    words: str, text: str, clock: tuple[int, int], span: tuple[int, int], *, spans: bool = True
) -> bool:
    """Whether a closing time or an event named next to the clock time ``text`` that stands at
    ``clock`` in ``words`` owns it (:data:`_CLOSES_BEFORE`, :data:`_EVENT_AFTER`,
    :data:`_EVENT_BEFORE`), or, with ``spans``, a span of hours it starts or ends
    (:data:`_RANGE_AFTER`, :data:`_RANGE_BEFORE`); ``span`` is where its weekday and the clock
    time right by it stand."""
    (at, end), (left, right) = clock, span
    return (
        _CLOSES_BEFORE.search(words, max(0, at - _BEFORE_WINDOW), at) is not None
        or (
            _CLOSING_BEFORE.search(words, max(0, left - _BEFORE_WINDOW), left) is not None
            and _AT.match(text) is not None
        )
        or (spans and _RANGE_AFTER.match(words, end) is not None)
        or (spans and _RANGE_BEFORE.search(words, max(0, at - _BEFORE_WINDOW), at) is not None)
        or _EVENT_AFTER.match(words, end) is not None
        or _EVENT_AFTER.match(words, right) is not None
        or _EVENT_BEFORE.search(words, max(0, at - _BEFORE_WINDOW), at) is not None
        or _EVENT_BEFORE.search(words, max(0, left - _BEFORE_WINDOW), left) is not None
    )


def _span_words(scan: "_Scan", index: int, clock: tuple[int, int], begin: int) -> str | None:
    """The words around the span of hours ("9 AM - 3 PM", "8:30-3:15", "6 a.m. to 8 p.m.") the
    clock time at ``clock`` in ``scan.words`` starts or ends, for the weekday
    ``scan.found[index]``: its clause (:data:`_DELAY_CLAUSE`) from the weekday and the span, back
    to ``begin`` at most and on to the next weekday, past a ":" right after them (a heading's:
    "Thursday 9 AM - 3 PM: closed"), clock times blanked; ``None`` when it starts or ends no
    span."""
    words, masked, found = scan.words, scan.masked, scan.found
    at, end = clock
    after = _RANGE_AFTER.match(words, end)
    before = _RANGE_BEFORE.search(words, max(0, at - _BEFORE_WINDOW), at)
    if after is None and before is None:
        return None
    weekday = found[index]
    first = min(at if before is None else before.start(), weekday.start())
    last = max(end if after is None else after.end(), weekday.end())
    stop = found[index + 1].start() if index + 1 < len(found) else len(words)
    head = masked[max(begin, first - _STAMP_CLAUSE_WINDOW) : first] if begin < first else ""
    tail = masked[last : max(last, min(stop, last + _STAMP_CLAUSE_WINDOW))]
    tail = _HEADING.sub(" ", tail, count=1)  # "6 a.m. to 8 p.m. on Thursday: closed"
    return f"{_DELAY_CLAUSE.split(head)[-1]} {masked[first:last]} {_DELAY_CLAUSE.split(tail)[0]}"


_HEADING: Final = re.compile(r"\A[ \t]*:")
_MARKS_AFTER: Final = re.compile(rf"[ \t]*{_MARK_RUN}")
_MARKS_BEFORE: Final = re.compile(rf"{_MARK_RUN}\Z")
"""A run of marks right after or right before a weekday (:data:`_MARK_RUN`)."""


def _past_marks(
    scan: "_Scan",
    index: int,
    weekday: tuple[int, int],
    begin: int,
    clause: tuple[str, str],
) -> tuple[re.Match[str], str] | None:
    """For the weekday ``scan.found[index]`` (from ``weekday[0]`` to ``weekday[1]``) whose own
    clause, ``clause`` before and after it, holds no clock time: the first clock time or span
    of hours (:func:`_clocks_in`) in the clauses past the run of marks that ends its clause
    after it, read on over each clause and run of marks with no status or event word
    (:func:`_a_status_or_event`) to the first that holds one ("Thursday: from 9 AM to 3 PM",
    "Thursday | hours 9 AM - 3 PM", "Thursday hours: 9 AM - 3 PM", "Thursday | hours
    (8:30-3:15)", "Thursday | office | hours 8:30-3:15", "Thursday: hours - 8:30-3:15"), or else
    the same way before it ("9 to 3: Thursday", "0900-1500 | Thursday", "9 AM - 3 PM: hours
    Thursday", "(8:30-3:15) | hours | Thursday"), at most :data:`_STAMP_CLAUSE_WINDOW` characters
    away, back to ``begin`` at most and on to no other weekday; and the words from the weekday
    to the end of the clause it stands in, clock times blanked. ``None`` when there is none
    before a clause with a status or event word ("Thursday | closed | 8:30-3:15")."""
    words, masked, found, claimed, _ = scan
    left, right = weekday
    before, after = clause
    edge = right + len(after)  # where the weekday's clause after it ends: at a mark, or not
    run = _MARKS_AFTER.match(words, edge) if edge < right + _STAMP_CLAUSE_WINDOW else None
    if run is not None:
        start = run.end()
        stop = found[index + 1].start() if index + 1 < len(found) else len(words)
        stop = min(stop, start + _PAST_MARKS_REACH)
        for at, end in _pieces(masked, start, stop):
            for inner in _clocks_in(scan, at, end):
                if not _taken(claimed, inner.start()):
                    return inner, masked[right:end]
            if _a_status_or_event(masked[at:end]):
                break  # "Thursday | closed | 8:30-3:15": read as before
    edge = left - len(before)  # where the weekday's clause before it starts
    run = _MARKS_BEFORE.search(words, max(begin, edge - _BEFORE_WINDOW), edge)
    if begin < edge and run is not None:
        stop = run.start()
        for at, end in reversed(_pieces(masked, max(begin, stop - _STAMP_CLAUSE_WINDOW), stop)):
            for inner in _clocks_in(scan, at, end, before=True):
                if not _taken(claimed, inner.start()):
                    return inner, masked[at:left]
            if _a_status_or_event(masked[at:end]):
                break
    return None


def _pieces(masked: str, start: int, stop: int) -> list[tuple[int, int]]:
    """Where each clause (:data:`_DELAY_CLAUSE`) in ``masked`` from ``start`` to ``stop``
    starts and ends, in order."""
    pieces: list[tuple[int, int]] = []
    at = start
    for mark in _DELAY_CLAUSE.finditer(masked, start, stop):
        pieces.append((at, mark.start()))
        at = mark.end()
    pieces.append((at, stop))
    return pieces


_HOURS_OF: Final = re.compile(
    r"\b(?:school|office|open(?:ing)?|regular|normal|usual|business|building|class)\s+"
    r"(?:hours|hrs)\b",
    re.IGNORECASE,
)
"""Words that name a school's or an office's hours ("school hours", "office hours", "regular
hours"): no status a day has, so a clock time or a span by them is no status's time."""


def _a_status(clause: str) -> bool:
    """Whether ``clause`` holds a status word (:data:`_STATUS_WORDS`) that names no hours
    (:data:`_HOURS_OF`: "Thursday school hours 8:30-3:15" holds none)."""
    return any(
        word.casefold() in _STATUS_WORDS for word in _A_WORD.findall(_HOURS_OF.sub(" ", clause))
    )


def _a_status_or_event(clause: str) -> bool:
    """Whether ``clause`` holds a status word (:func:`_a_status`) or names an event
    (:data:`_EVENT_WORD`)."""
    return _EVENT_WORD.search(_HOURS_OF.sub(" ", clause)) is not None or _a_status(clause)


def _near(words: str, weekday: re.Match[str]) -> tuple[re.Match[str], re.Match[str] | None, bool]:
    """``weekday`` in ``words``, the clock time right after it (:data:`_CLOCK_AFTER`) or else
    right before it (:data:`_CLOCK_BEFORE`), or ``None``, and whether that clock time follows
    it."""
    # the "." a weekday ends with starts its run of marks too ("Thursday.45", "Thu. 50 info")
    stop = weekday.end() - 1 if weekday.group(0).endswith(".") else weekday.end()
    clock = _CLOCK_AFTER.match(words, weekday.end()) or _SPAN_AFTER_MARKS.match(words, stop)
    if (
        clock is not None
        and clock.re is _CLOCK_AFTER
        and clock.group("part")
        and not _LAST_CLAUSE.match(words, clock.end())
    ):
        clock = None  # "Thursday Afternoon: Closed": a part of the day as a heading
    if clock is not None:
        return weekday, clock, True  # a part of the day with a status word is dropped later
    start = max(0, weekday.start() - _CLOCK_BEFORE_WINDOW)
    before = _CLOCK_BEFORE.search(words, start, weekday.start())
    if before is None:
        before = _BARE_BEFORE_MARKS.search(words, start, weekday.start())
        if before is not None and _MONTH_BEFORE.search(
            words, max(0, before.start() - _BEFORE_WINDOW), before.start()
        ):
            before = None  # "Closed Nov. 5 \u00b7 Thursday": a date's day number
    return weekday, before, False


def _marked(clock: re.Match[str] | None) -> bool:
    """Whether a run of marks parts the clock time ``clock`` from its weekday (:data:`_MARK_RUN`:
    "Friday: 9:14 PM", "9:14 PM-- Friday", "9:14 PM (Friday)")."""
    if clock is None:
        return False
    return bool(clock.group("mark") or (clock.re is _CLOCK_BEFORE and clock.group("open")))


@lru_cache(maxsize=4096)
def _clocked(words: str) -> tuple[_Clocked, ...]:
    """Each weekday in ``words`` with a clock time right after it (:data:`_CLOCK_AFTER`: "Fri
    9:14 PM", "Friday (9:14pm)", "Friday at 9", "Friday around 9 PM") or right before it
    (:data:`_CLOCK_BEFORE`: "9:14 PM Fri", "21:14 Fri", "at 9:14 PM Friday"), or, with a
    status word, one further on in its clause no other weekday has right by it ("Friday
    closed 9:14 PM", "9:14 PM closed Friday"); whether it is a posting stamp with no stamp
    word: a clock time right by it and no status word (:data:`_STATUS_WORDS`) in its clause,
    before it back to the weekday before, or after it when no other weekday follows in that
    clause (a status word there is that weekday's), each read at most
    :data:`_STAMP_CLAUSE_WINDOW` characters away; and whether a start, opening, closing or
    dismissal word there (:data:`_OWNS_CLOCK`) or an event named next to the clock time
    (:data:`_EVENT_AFTER`, :data:`_EVENT_BEFORE`) owns it."""
    if _ANY_CLOCK.search(words) is None:
        return ()
    found = list(_WEEKDAY.finditer(words))
    near = [_near(words, weekday) for weekday in found]
    claimed = _merged(
        clock.span("clock") for _, clock, _ in near if clock is not None and not _marked(clock)
    )
    clocked: list[_Clocked] = []
    clocks = _Clocks.of(words, found)
    scan = _Scan(words, _unbroken(_mask_clocks(words), clocks), found, claimed, clocks)
    for index, (_, first, follows) in enumerate(near):
        near_clock = first
        one = _clocked_one(scan, index, near_clock, follows=follows)
        if near_clock is not None and near_clock.re in _BY_MARKS and not (one and one.stamp):
            near_clock = None  # "Closed Thursday: 9", "Closed 9...Thursday": a number, as before
            one = _clocked_one(scan, index, None, follows=follows)
        if _marked(near_clock) and (one is None or not (one.stamp or one.owned)):
            # "Closed Friday: 9:14 PM": past a run of marks, a clock time is a stamp's, never
            # a day's: one further on in the clause is the day's, and with none the clock time
            # is read as one with no day (stamp_dates), whatever words its clause holds
            again = _clocked_one(scan, index, None, follows=follows)
            one = again if again is not None or one is None else one._replace(lone=True)
        if one is not None:
            clocked.append(one)
    kept = {clock.span for clock in clocked if not clock.lone}
    # "Closed Thursday \u00b7 9:14 PM Wed": a clock time another weekday has is that one's
    return tuple(clock for clock in clocked if not (clock.lone and clock.span in kept))


_DASH: Final = re.compile(r"[-\u2013\u2014]")


def _unbroken(masked: str, clocks: _Clocks) -> str:
    """``masked`` with the dashes in each span of hours in ``clocks`` (:data:`_HOUR_SPAN`,
    :data:`_OTHER_SPAN`) blanked, so a spaced one ends no clause ("Thursday 2 - 3 hour delay",
    "Thursday: grades 9 - 12 closed" keep their status words in the weekday's clause)."""
    chars: list[str] | None = None
    for match in clocks.found:
        if match.re is _HOUR_SPAN or match.re is _OTHER_SPAN:
            for dash in _DASH.finditer(masked, match.start(), match.end()):
                if chars is None:
                    chars = list(masked)
                chars[dash.start()] = " "
    return masked if chars is None else "".join(chars)


class _Scan(NamedTuple):
    """What :func:`_clocked` finds once in some words: the words, their clock times blanked
    (:func:`_mask_clocks`), their weekdays, the clock times right by one and all their clock
    times (:class:`_Clocks`)."""

    words: str
    masked: str
    found: list[re.Match[str]]
    claimed: tuple[tuple[int, int], ...]
    clocks: _Clocks


def _clocked_one(
    scan: _Scan, index: int, clock: re.Match[str] | None, *, follows: bool
) -> _Clocked | None:
    """The weekday ``scan.found[index]`` as :func:`_clocked` reads it, with the clock time
    ``clock`` right by it (and whether that ``follows`` it), or ``None`` when it has none."""
    words, masked, found, _, _ = scan
    weekday = found[index]
    right = weekday.end()
    ended = weekday.group(0).endswith(".") and len(weekday.group(0)) > _FULL_NAME
    if clock is None and ended:
        right -= 1  # "Closed Sunday. Online service 10:15 AM": the "." ends the clause
    left = weekday.start() if clock is None or follows else clock.start()
    right = clock.end() if clock is not None and follows else right
    begin = max(found[index - 1].end() if index else 0, left - _STAMP_CLAUSE_WINDOW)
    before = _DELAY_CLAUSE.split(masked[begin:left])[-1] if begin < left else ""
    after = _DELAY_CLAUSE.split(masked[right : right + _STAMP_CLAUSE_WINDOW])[0]
    if _WEEKDAY.search(after):
        after = ""  # "Fri 9:14 PM Closed Thursday": "Closed" is Thursday's
    clause = f"{before} {after}"
    marked_only = False
    if clock is None:
        # a clock time further on in its clause: a time on its day with a status word there,
        # and with none a posting stamp ("Closed Wednesday \u00b7 Thursday hours 8:30-3:15")
        inner_clock = _inner_clock(scan, (right, right + len(after)), (left - len(before), left))
        if inner_clock is None:
            # past a run of marks: "Thursday: from 9 AM to 3 PM", "9 to 3: Thursday"
            past = _past_marks(scan, index, (left, right), begin, (before, after))
            if past is None:
                return None
            inner_clock, region = past
            clause = f"{clause} {region}"
            marked_only = True
        at, end, text = inner_clock.start(), inner_clock.end(), inner_clock.group(0)
    else:
        at, end, text = clock.start("clock"), clock.end("clock"), clock.group("clock")
    spanned = _span_words(scan, index, (at, end), begin)
    hours = (
        spanned is not None
        or _HOUR_SPAN.fullmatch(text) is not None  # "9 until 3"
        or _OTHER_SPAN.fullmatch(text) is not None  # "9a-3p"
        # "Thursday...9", "Friday#9-3", "9...Friday"
        or (clock is not None and clock.re in _BY_MARKS)
    )
    tight = (
        None
        if hours or marked_only or _marked(clock)  # "Thursday ~ 9:14 PM begins"
        else _tight(words, weekday, (at, end), (left - len(before), right + len(after)))
    )
    owned = (
        # owner words that are no status word own only a single clock time in the weekday's
        # own clause with no mark between ("Closed Wednesday \u00b7 Thursday | begins
        # (8:30-3:15)", "Closed Wednesday \u00b7 Thursday: staff report 9:14 PM", "Closed
        # Wednesday \u00b7 9:14 PM: Thursday begins" are stamps)
        _owned_by_words(
            clause,
            tight,
            # a dismissal at a single clock time only, never a span ("Closed Wednesday \u00b7
            # Thursday started at 9 AM - 3 PM" is a stamp)
            dismissed=not hours and _dismissed_at(words[max(0, at - _BEFORE_WINDOW) : at], text),
        )
        or _owns(words, text, (at, end), (left, right), spans=False)
        # a span of hours is a status's on its weekday only when a status or an event word
        # is in its clause or around the span ("Friday closed 9 AM - 3 PM", "Closed 6 a.m. to
        # 8 p.m. on Friday"); "Closed Thursday \u00b7 Friday 9 AM - 3 PM" is a stamp
        or (spanned is not None and _a_status_or_event(f"{clause} {spanned}"))
        # a span cut short is owned the same way ("Closed Thursday 9a-3p")
        or (_OTHER_SPAN.fullmatch(text) is not None and _a_status_or_event(clause))
    )
    if clock is None:
        # a clock time in the weekday's clause, or past its marks, owned by nothing and with no
        # status or event word in that clause: the weekday is a posting stamp that names no
        # day the row is for ("Thursday hours 8:30-3:15", "Thursday posted 5:14 AM")
        stamp = (
            not owned
            and not _a_status_or_event(clause)
            and (hours or _OPEN_UNTIL.search(clause) is None)
        )
        if marked_only and not stamp:
            return None  # "Friday: closed 9 AM - 3 PM": read as before (_lone_clocks)
    else:
        stamp = not owned and not _a_status(clause)
    if clock is not None and clock.re is _CLOCK_AFTER and not stamp:
        if clock.group("part"):
            return None  # "Activities cancelled Friday evening": no time, a day the row is for
        if ended:
            return None  # "Services canceled Sunday. 9:15 and 11 a.m. online": a new sentence
    return _Clocked(
        weekday.start(),
        _weekday_of(weekday),
        text,
        stamp,
        owned,
        max(end, right),
        (at, end),
        hours=hours,
    )


_STATUS_TIME: Final = re.compile(
    r"\b(?:delay\w*|late[rs]?|lateness|early|earlier|dismiss\w*|start\w*|begin\w*|began|begun|"
    r"open\w*|re-?open\w*|resum\w*|effect\w*|arriv\w*|depart\w*|until|till|til|from|between|"
    r"through|thru|after|before|clos(?:e|es|ing)|pick\w*|drop\w*|bus(?:es)?|routes?|"
    r"transportation|half|students?|staff|teachers?|faculty|employees?|meals?|food|moved|"
    r"reschedul\w*|postpon\w*|pushed|offices?|prayers?|schedules?|run|runs|running|leav\w*|"
    r"live|live-?stream\w*|stream\w*|online|re-?evaluat\w*|evaluat\w*|decision|decid\w*|"
    r"assess\w*|times?|normal\w*|regular\w*|teams?|for|elementary|middle|high|academy|campus|"
    r"preschool|grades?)\b"
    rf"|{_EVENT_WORD.pattern}",
    re.IGNORECASE,
)
"""Words in a clock time's clause that make it the time of a status or an event on its day, not
a post's: a start, an opening, a delay, a dismissal, a closing time, a span's end, a bus, a
staff call, an office's hours, a meal, a stream, a schedule, a decision still to come or an
event ("2 hour delay, buses 10 AM", "Game at 7 PM", "front office at 9:50am", "decision by
6:45a", "Livestream only at 10:15", "10:50 a.m. for Delta Elementary"). Any other word leaves it
a post's time ("7:14 AM update", "7:14 AM upd", "7:14 AM revised")."""
_STATUS_TIME_BEFORE: Final = re.compile(r"\breports?\b", re.IGNORECASE)
"""A word before a clock time in its clause that makes it the time of a call ("Staff report
10 AM"); after one it is a notice noun ("7:14 AM report")."""


def _starts(pattern: re.Pattern[str], text: str) -> list[int]:
    """Where each match of ``pattern`` in ``text`` starts, in order."""
    return [found.start() for found in pattern.finditer(text)]


def _any_in(starts: list[int], start: int, stop: int) -> bool:
    """Whether one of the sorted ``starts`` falls from ``start`` to ``stop`` (not included)."""
    index = bisect_left(starts, start)
    return index < len(starts) and starts[index] < stop


def _lone_clocks(words: str) -> tuple[str, ...]:
    """Each clock time in ``words`` read as a posting time with no day: each of
    :func:`_lone_candidates` that :func:`_owns` gives to no closing time, event or span of
    hours."""
    return tuple(
        text
        for text, at, end in _lone_candidates(words)
        if not _owns(words, text, (at, end), (at, end))
    )


@lru_cache(maxsize=4096)
def _lone_candidates(words: str) -> tuple[tuple[str, int, int], ...]:
    """Each clock time in ``words`` that no weekday has (:func:`_clocked`) and that stands in
    its own clause with no other number and no word that makes it the time of a status or an
    event on its day (:data:`_STATUS_TIME`: "Closed Thursday \u00b7 7:14 AM", "Thursday:
    Closed. 7:14 AM", "Friday: Closed 9:14 PM", "Closed Thursday. 7:14 AM upd", "Closed
    Thursday. 7:14 AM revised"), with where it stands: owned by no closing time, event or span
    of hours (:func:`_owns`, which :func:`_lone_clocks` and :func:`stamp_dates` ask), it is a
    posting time with no day. Read after the read, it is an earlier day's, and
    :func:`stamp_dates` reads it as unreadable. Each clause is read once, so the words are
    read in time linear in their length, however many clock times they hold."""
    if _ANY_CLOCK.search(words) is None:
        return ()
    taken = _merged(clock.span for clock in _clocked(words))
    masked = _mask_clocks(words)
    ends = [found.start() for found in _DELAY_CLAUSE.finditer(masked)]
    marks = [0, *(found.end() for found in _DELAY_CLAUSE.finditer(masked))]
    digits = [at for at, char in enumerate(masked) if char.isdigit()]
    status: list[int] | None = None
    status_before: list[int] = []
    lone: list[tuple[str, int, int]] = []
    for inner in _INNER_CLOCK.finditer(words):
        at, end = inner.span()
        if _taken(taken, at):
            continue
        start = marks[bisect_right(marks, at) - 1]
        following = bisect_left(ends, end)
        stop = ends[following] if following < len(ends) else len(masked)
        if _any_in(digits, start, at) or _any_in(digits, end, stop):
            continue  # "2 hour delay, buses 10 AM", "9 AM to 3 PM to 5 PM"
        if status is None:  # read once, and only for words with such a clock time
            status = _starts(_STATUS_TIME, masked)
            status_before = _starts(_STATUS_TIME_BEFORE, masked)
        if (
            _any_in(status, start, at)
            or _any_in(status, end, stop)
            or _any_in(status_before, start, at)
        ):
            continue  # "Closed Thursday. Game at 7 PM", "front office at 9:50am"
        lone.append((inner.group(0), at, end))
    return tuple(lone)


def _clock_stamps(words: str) -> tuple[_Clocked, ...]:
    """Each weekday in ``words`` that is a posting stamp with no stamp word (see
    :func:`_clocked`): a weekday with a clock time right before or after it and no status
    word in its clause ("Closed Thursday \u00b7 Fri 9:14 PM", "Closed Thursday Sat 7:12am",
    "Closed Thursday \u00b7 Friday (9:14pm)", "Closed Thursday \u00b7 9:14 PM Fri", "Closed
    Thursday \u00b7 Friday at 9", "Fri 9:14 PM Closed Thursday"). It names when the row went
    up, not a day the row is for; "Early dismissal Thursday 1:30 PM", "Early dismissal
    Thursday (1:30 PM)" and "Thursday 10 AM start" name Thursday."""
    return tuple(clocked for clocked in _clocked(words) if clocked.stamp)


_STAMP_DAY_BEFORE: Final = re.compile(
    rf"(?:{_WEEKDAY.pattern})[ \t]*(?:(?:{_MARK}++[ \t]*+)+)?\Z", re.IGNORECASE
)
"""A weekday right before a stamp word, with spaces or a run of marks between ("Thursday posted
5:14 AM", "Friday - updated 9 PM", "Thursday. Posted 5:14 AM")."""


def _stamp_day_before(text: str, start: int) -> int | None:
    """Where the weekday right before the stamp word at ``start`` in ``text``
    (:data:`_STAMP_DAY_BEFORE`) starts when it is the stamp's day ("Closed Wednesday \u00b7
    Thursday posted 5:14 AM", "Closed Wednesday \u00b7 Thursday. Posted 5:14 AM": "Posted
    Thursday 5:14 AM"): it starts its clause, since a word before it there makes it a day the
    row is for ("Closed Thursday, updated 5 AM", "Snow day Thursday. Updated 5 AM"); ``None``
    when there is none."""
    day = _STAMP_DAY_BEFORE.search(text, max(0, start - _BEFORE_WINDOW), start)
    if day is None:
        return None
    clause = _DELAY_CLAUSE.split(text[max(0, day.start() - _POSTING_WINDOW) : day.start()])[-1]
    return None if _A_WORD.search(clause) else day.start()


def _without_stamps(text: str) -> str:
    """``text`` without its stamps (:data:`STAMP_PHRASE`), each with the weekday that is its day
    right before it (:func:`_stamp_day_before`)."""
    kept: list[str] = []
    at = 0
    for stamp in STAMP_PHRASE.finditer(text):
        start = _stamp_day_before(text, stamp.start())
        start = stamp.start() if start is None or start < at else start
        kept.append(text[at:start])
        kept.append(" ")
        at = stamp.end()
    kept.append(text[at:])
    return "".join(kept)


_SPACES: Final = dict.fromkeys((0xA0, 0x1680, *range(0x2000, 0x200B), 0x202F, 0x205F, 0x3000), " ")
"""Each Unicode space but the plain one ("\u00a0", "\u2009", "\u202f"), read as a plain
space: "Thursday\u00a05:14 AM" is "Thursday 5:14 AM"."""


@lru_cache(maxsize=4096)
def _weekday_words(text: str) -> str | None:
    """The words :func:`named_weekdays` reads in ``text``: each Unicode space a plain one
    (:data:`_SPACES`), without its stamps and its ages under a day, ``None`` when an age keeps
    the row from being dated (:func:`_without_ages`)."""
    return _without_ages(_without_stamps(text.translate(_SPACES)))


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


_MOST_WEEKDAYS: Final = 16
"""The most weekdays words are read with: more make them a schedule or a list of days, which
names no day the row is for exactly and gives no stamp that can be read (the archive's lit rows
hold at most ten), and keeps the time each row is read in bounded."""


@lru_cache(maxsize=4096)
def _too_many_weekdays(words: str) -> bool:
    """Whether ``words`` hold more than :data:`_MOST_WEEKDAYS` weekdays."""
    return any(index >= _MOST_WEEKDAYS for index, _ in enumerate(_WEEKDAY.finditer(words)))


@lru_cache(maxsize=4096)
def named_weekdays(text: str, name: str = "", day: date | None = None) -> frozenset[int]:
    """The weekdays (Monday 0) the status words ``text`` name as the days they are for, or
    none when the words cannot date their row by a weekday (see the module).

    ``name`` is the row's name: a weekday it holds is never read from ``text``. ``day`` is
    the day the words are read for: a day number after a weekday ("Thursday 5") or a month
    and day written as one number ("1105") may name it; with no ``day``, none may stand in
    the words.
    """
    words = _weekday_words(text)
    if (
        words is None
        or _VOID.search(_without_name(text, name))
        or _GLUED_WEEKDAY.search(words)
        or _EXPLICIT_DATE.search(words)
        or _OTHER_DATE.search(words)
        or _RELATIVE.search(words)
        or _REOPENED.search(words)
        or not _numbers_name(_without_name(words, name), day)
        or _too_many_weekdays(words)
    ):
        return frozenset()
    in_name = weekdays_in([name])
    letters = [char for char in words if char.isalpha()]
    mixed = any(char.isupper() for char in letters) and any(char.islower() for char in letters)
    named: set[int] = set()
    clauses = _Clauses.of(words)
    stamped = {stamp.start for stamp in _clock_stamps(words)}
    for found in _WEEKDAY.finditer(words):
        if _not_the_day(words, found, clauses) or _in_a_name(words, found, mixed=mixed):
            return frozenset()
        if _another_day_around(words, found, day):
            return frozenset()  # "Thursday 29", "Thursday #5": another week's, or not exact
        if found.start() in stamped:
            continue  # "Closed Thursday \u00b7 Fri 9:14 PM": when it went up (stamp_dates)
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
    if _date_patterns(day).search(text) is None:
        return False  # no such date in the words: none is read from them, so none is read fast
    words = _without_ages(_status_words(text, name))
    if (
        words is None
        or _VOID.search(_without_name(text, name))
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
_STAMP_CLOCK: Final = re.compile(_CLOCK_TEXT, re.IGNORECASE)
"""A clock time, with its US zone (the reader's, :mod:`snowlight.classify.text`; never a
month: "5:30 AM Oct. 29"): it bounds no day."""
_RUN_ON: Final = re.compile(r"[ \t]*(?P<dot>\.)?[ \t,]*(?:(?:at|on)[ \t]+|@[ \t]*)?", re.IGNORECASE)
"""What may stand between a stamp's day and a clock time or a date that runs on after it,
past a "." too ("Posted Nov. 5 7:00 AM", "Updated Thu. 7:00 AM", "Updated Thu., 7:00 AM",
"Updated Thu. Nov. 5 7:00 AM", "Updated Nov. 5. 7:00 AM")."""
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
    r"(?:today|(?P<part>tonight|this\s+(?:morning|afternoon|evening)))\b", re.IGNORECASE
)
"""The read's day in a stamp, at a part of the day or not ("Posted today", "Posted this
evening": read Thursday at 06:00, a time after the read, and unreadable)."""
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


def _read_stamp(  # noqa: PLR0913 - the stamp's span, its read day and time, and the path
    stamp: str,
    at: int,
    end: int,
    today: date,
    now: datetime | None = None,
    *,
    clock_only: bool = False,
) -> tuple[bool, date | None, int]:
    """Whether the stamp in ``stamp`` from ``at`` (what follows a stamp word) to ``end``
    carries a day, and which (``None`` when it carries one that cannot be read exactly: any
    number, month, weekday or relative day word in it that no date, time or day form here
    reads, wherever it stands). A date or time that starts before ``end`` is read whole,
    past it too ("Oct. 29", "6 a.m."). A stamp of the read's day ``today`` at a clock time
    after the read ``now`` is unreadable (:func:`_after_the_read`). With ``clock_only``, so is
    a stamp that gives a clock time and no day ("Updated 7 AM" read at 06:00): it went up at
    that time on an earlier day, and which one it does not say. Last, where what it read ends,
    a date or a clock time that runs on past ``end`` included (:func:`_run_on`)."""
    days: list[date | None] = []
    weekdays: list[int] = []
    clocks: list[str] = []
    unread = yesterday = False
    while at < end:
        if (found := _STAMP_CLOCK.match(stamp, at)) is not None:
            clocks.append(found.group(0))
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
        elif (
            found := _STAMP_TODAY.match(stamp, at) or _STAMP_LAST_NIGHT.match(stamp, at)
        ) is not None:
            yesterday = _relative_day(found, today, days, clocks) or yesterday
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
    _, read = _stamp_of(days, weekdays, today)
    later, stop = _run_on(stamp, at, today, days, clocks) if days or weekdays else ([], at)
    if unread or (yesterday and not clocks):
        return True, None, stop  # "Posted yesterday": an age of about a day, at no time it gives
    if clock_only and clocks and not (days or weekdays):
        # "Updated 7 AM" read at 06:00: an earlier day's 7 AM, which day unknown
        return _after_the_read(today, clocks, today, now) is None, None, stop
    if read is None and (days or weekdays):
        return True, None, stop  # "Updated Mon. Nov. 2" read Thursday: what runs on reads no day
    dated, day = _stamp_of(days, weekdays, today)
    return dated, _after_the_read(day, [*clocks, *later], today, now), stop


def _relative_day(
    found: re.Match[str], today: date, days: list[date | None], clocks: list[str]
) -> bool:
    """Add the day a stamp's relative day word ``found`` (:data:`_STAMP_TODAY`,
    :data:`_STAMP_LAST_NIGHT`) names to ``days``, and a part of the day it gives to ``clocks``
    ("this evening"); whether it is a bare "yesterday", at no time it gives."""
    if found.re is _STAMP_TODAY:
        days.append(today)
        if found.group("part"):
            clocks.append(found.group("part"))  # "Posted this evening": a time it gives
        return False
    days.append(today - timedelta(days=1))
    return found.group("bare") is not None


def _run_on(
    stamp: str, at: int, today: date, days: list[date | None], clocks: list[str]
) -> tuple[list[str], int]:
    """Read on in ``stamp`` from ``at``, past the end of a stamp whose day ran on past a "."
    ("Posted Nov. 5 7:00 AM", "Updated Thu. 7:00 AM", "Updated Thu. Nov. 5 7:00 AM"), each
    clock time and date that follows right after it (:data:`_RUN_ON`): a date joins ``days``
    and a clock time ``clocks``, or, once a "." is passed ("Updated Nov. 5. 7:00 AM"), the
    clock times it gives back, which only bound the stamp from after the read, and where what
    runs on ends. A day that cannot be read stays unread whatever runs on (:func:`_stamp_of`)."""
    later: list[str] = []
    dotted = False
    while (gap := _RUN_ON.match(stamp, at)) is not None:  # it may be empty: always a match
        dotted = dotted or gap.group("dot") is not None
        if (found := _STAMP_CLOCK.match(stamp, gap.end())) is not None:
            (later if dotted else clocks).append(found.group(0))
        elif (found := _STAMP_WORDED.match(stamp, gap.end())) is not None:
            days.append(_stamp_day(found, today, worded=True))
        elif (found := _STAMP_NUMERIC.match(stamp, gap.end())) is not None:
            days.append(_stamp_day(found, today, worded=False))
        else:
            break
        at = found.end()
    return later, at


_CLOCK_PARTS: Final = re.compile(
    r"(?P<noon>noon)|(?P<midnight>midnight)|(?P<part>morning|afternoon|evening|night|overnight)"
    r"|(?<!\d)(?:(?P<hhmm>\d{3,4})(?!\d)|(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?)"
    r"(?::\d{2})?\s*(?:(?P<half>[ap])\.?\s?m\b)?",
    re.IGNORECASE,
)
_CLOCK_ZONE: Final = re.compile(
    r"\b(?P<zone>[ecmp][sd]?t|ak[sd]?t|h[sd]?t|gmt|utc)\b", re.IGNORECASE
)
_ZONES: Final[dict[str, tzinfo]] = {
    **{
        name: timezone(timedelta(hours=hours))
        for name, hours in {
            "est": -5, "edt": -4, "cst": -6, "cdt": -5, "mst": -7, "mdt": -6, "pst": -8,
            "pdt": -7, "akst": -9, "akdt": -8, "hst": -10, "hdt": -9, "gmt": 0, "utc": 0,
        }.items()
    },
    **{
        name: ZoneInfo(zone)
        for name, zone in {
            "et": "America/New_York", "ct": "America/Chicago", "mt": "America/Denver",
            "pt": "America/Los_Angeles", "akt": "America/Anchorage", "ht": "Pacific/Honolulu",
        }.items()
    },
}  # fmt: skip
"""The US zones a stamp's clock time is read in (the reader's, :data:`_STAMP_CLOCK`)."""
_PART_STARTS: Final = {
    "morning": time(5), "afternoon": time(12), "evening": time(17), "night": time(18),
    "overnight": time(0),
}  # fmt: skip
"""When a part of the day a posting stamp gives starts, at the earliest: "Thu evening" read
Thursday at 06:00 is after the read."""
_HALF_DAY: Final = 12
_LAST_HOUR: Final = 23
_LAST_MINUTE: Final = 59


def _clock_of(text: str) -> tuple[time, tzinfo | None] | None:
    """The time of day a stamp's clock time ``text`` gives ("9:14 PM", "21:14", "6 a.m. CST",
    "noon"), with its zone when it states one; ``None`` when it is no time of day."""
    found = _CLOCK_PARTS.search(text)
    if found is None:
        return None
    zone = _CLOCK_ZONE.search(text, found.end())
    stated = None if zone is None else _ZONES.get(zone.group("zone").casefold())
    if found.group("part"):
        return _PART_STARTS[found.group("part").casefold()], stated
    if found.group("noon") or found.group("midnight"):
        return time(_HALF_DAY if found.group("noon") else 0), stated
    hhmm = found.group("hhmm")
    if hhmm is not None:
        hour, minute = int(hhmm[:-2]), int(hhmm[-2:])
    else:
        hour, minute = int(found.group("hour")), int(found.group("minute") or 0)
    half = (found.group("half") or "").casefold()
    if half:
        if not 1 <= hour <= _HALF_DAY:
            return None
        hour = hour % _HALF_DAY + (_HALF_DAY if half == "p" else 0)
    if hour > _LAST_HOUR or minute > _LAST_MINUTE:
        return None
    return time(hour, minute), stated


_BARE: Final = re.compile(r"(?<![\d:])\d{1,2}(?!\s*[:\d])(?!\s*[ap]\.?\s?m\b)", re.IGNORECASE)
"""An hour with no minutes and no "a.m." or "p.m." ("at 9"): it may be the morning's or the
evening's."""


def _after_the_read(
    day: date | None, clocks: Iterable[str], today: date, now: datetime | None
) -> date | None:
    """``day``, a stamp's day, unless it is the read's day ``today`` or the day before and a
    clock time the stamp gives, read in the zone it states or else the read's, is after the
    read ``now`` (local, aware) or is no time of day: then ``None``, since the stamp may be
    from the same weekday a week before ("Closed Thursday \u00b7 Thu 5:02 AM" read at 04:00,
    "Updated 11/4 11:30 PM PT" read at 23:00 Pacific), or is unreadable. A bare hour ("at 9")
    is after the read when it is so in the morning or in the evening."""
    if day is None or now is None or day < today - _A_DAY:
        return day
    for text in clocks:
        clock = _clock_of(text)
        if clock is None:
            return None
        zone = (clock[1] if now.tzinfo is not None else None) or now.tzinfo
        bare = _BARE.search(text) if clock[0].hour < _HALF_DAY else None
        hours = (
            (clock[0].hour, clock[0].hour + _HALF_DAY)
            if bare and clock[0].hour
            else (clock[0].hour,)
        )
        for hour in hours:
            moment = datetime.combine(day, clock[0].replace(hour=hour), tzinfo=zone)
            if moment > now:
                return None
    return day


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


def _clock_stamp_day(words: str, clock: _Clocked, today: date, now: datetime | None) -> date | None:
    """The day a weekday with a clock time in ``words`` (:func:`_clocked`) dates its stamp: the
    latest such weekday when that is ``today`` or the day before, or the date that runs on
    after it when that is its weekday's ("Wed 9 PM, Oct. 28"); ``None`` when it is two or more
    days back, or the clock time is after the read ``now`` (:func:`_after_the_read`)."""
    day = _stamp_of([], [clock.weekday], today)[1]
    days: list[date | None] = []
    times = [clock.clock]
    _run_on(words, clock.end, today, days, times)
    if day is not None and days:
        day = _stamp_of(days, [clock.weekday], today)[1]
    return _after_the_read(day, times, today, now)


def _outside(text: str, spans: list[tuple[int, int]]) -> Iterator[str]:
    """The parts of ``text`` outside ``spans`` (in order), with a space for each span."""
    at = 0
    for start, stop in spans:
        yield text[at:start] if start >= at else ""
        yield " "
        at = max(at, stop)
    yield text[at:]


def _clock_dates(
    text: str, words: str, read: list[tuple[int, int]], today: date, now: datetime | None
) -> Iterator[date | None]:
    """The dates the clock times in a row's weekday words ``words`` (of ``text``, whose
    stamps were read over the spans ``read``) give as stamps (see :func:`stamp_dates`)."""
    if _too_many_weekdays(words):
        yield None  # a schedule or a list of days: no stamp is read exactly in it
        return
    for clock in _clocked(words):
        if clock.lone:
            if _after_the_read(today, [clock.clock], today, now) is None:
                yield None  # "Closed Thursday @ 9:14 PM" read at 06:00: an earlier day's
        elif clock.stamp and clock.hours:
            yield None  # "Closed Thursday \u00b7 Wednesday 9 AM - 3 PM": hours, no stamp
        elif clock.stamp or not clock.owned:
            # "Closed Thursday \u00b7 Fri 9:14 PM": a weekday-only stamp, at the time it gives;
            # "Closed Friday 9:14 PM" read Friday morning: that time is no start or dismissal,
            # so it may be the same weekday's a week before, as a stamp's would be
            yield _clock_stamp_day(words, clock, today, now)
    rest = _weekday_words("".join(_outside(text, read))) if read else words
    # without the stamps and what runs on after them ("Updated Wed. 9:14 PM"), read already
    after: dict[str, bool] = {}
    for clock_text, at, end in () if rest is None else _lone_candidates(rest):
        if clock_text not in after:
            after[clock_text] = _after_the_read(today, [clock_text], today, now) is None
        if after[clock_text] and not _owns(rest or "", clock_text, (at, end), (at, end)):
            yield None  # "Closed Thursday \u00b7 7:14 AM" read at 06:00: an earlier day's
            return  # one is enough: the stamp is unreadable


def stamp_dates(
    text: str, today: date, now: datetime | None = None, *, clocked: bool = True
) -> tuple[date | None, ...]:
    """The dates the stamps in the row's words ``text`` say it was posted or updated on
    ("Posted 10/29", "Updated Oct. 29", "(updated Oct 29, 2025)", "Updated 2026-10-29",
    "Posted Wednesday, October 28", "Updated Wednesday 9:00 PM", "Updated last night"),
    read on the read's local day ``today``: a date with no year is the latest such date not
    after ``today``, a weekday alone the latest such weekday when that is ``today`` or the
    day before. ``None`` for a stamp that carries a day it does not read exactly ("Updated
    last week", "Posted 3 days ago", "Posted yesterday", "Posted Feb. 30", a weekday that
    is not its date's, a weekday alone two or more days back: "Posted Friday" read on a
    Thursday, "Posted by District 5", a stamp of ``today`` at a clock time after the read
    ``now`` when it is given: "Posted Thu 6:02 AM" read at 06:00); a stamp with no day
    ("Updated 5:30 AM", "Posted by the district", "Updated 2 hours ago": an age, bounded by
    :func:`post_ages`) gives nothing. A stamp is
    read over all :data:`STAMP_PHRASE` cuts from the words the other rules read: from its
    stamp word to the first ".", ";" or "|", across lines, and a date or time that runs on
    past a "." whole (:func:`_read_stamp`). With ``clocked``, a weekday that is a posting stamp
    with no stamp word (:func:`_clock_stamps`: "Closed Thursday \u00b7 Fri 9:14 PM") is read as
    one too, after the others. Never raises."""
    found: list[date | None] = []
    read: list[tuple[int, int]] = []
    spaced = ""
    for word in _STAMP_WORD.finditer(text):
        if read and word.start() < read[-1][1]:
            continue  # "Posted by the district, updated Wed 9 PM": read with the stamp before
        cut = STAMP_PHRASE.match(text, word.start())
        end = word.end() if cut is None else cut.end()
        start, at = word.start(), word.end()
        if clocked and not spaced:
            spaced = text.translate(_SPACES)
        day_before = _stamp_day_before(spaced, start) if clocked else None
        if day_before is not None and (not read or day_before >= read[-1][1]):
            start = at = day_before  # "Friday posted 9 PM" is "Posted Friday 9 PM"
        dated, day, stop = _read_stamp(text, at, end, today, now, clock_only=clocked)
        read.append((start, stop))
        if dated:
            found.append(day)
    words = _weekday_words(text) if clocked else None
    if words is not None:
        found.extend(_clock_dates(text, words, read, today, now))
    return tuple(found)
