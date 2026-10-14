"""The gates a row, a read and a day pass before a replay lights a school.

Everything here is a pure function. Each failure is a :class:`Drop`, so the
report counts every row, school or read left out by its reason.

* Source gates (:func:`source_drop`): only multi-organization TV and radio lists
  (:data:`REPLAY_PLATFORMS`); status boards, district sites, unclassified
  platforms and district-level sources (``leaids``) are out.
* Claim gates (:func:`claim_for_day`): the status reader's entry for the day,
  confidence, notes, open, cause, open-ended, non-weather words, dates and the
  capture window.
* Read gates (:func:`unreadable`, :func:`low_match`): a read that looks like a
  broken adapter drops whole.
* Day gates (:func:`day_ok`): a weekday, not a holiday, a school year the
  directory can speak for.

The status reader is reached only through :class:`ParseFn`, a protocol shaped
like ``snowlight.classify.parse_status``, so this package does not import it.
"""

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from statistics import median
from typing import Final, Protocol
from zoneinfo import ZoneInfo

from snowlight.listed.scope import EXCLUDED_PLATFORMS
from snowlight.schemas.vocab import STATUS_BY_KIND
from snowlight.sources.stations.registry import Station


class Drop(StrEnum):
    """Why a row, a school or a read does not light anything."""

    UNKNOWN_SOURCE = "unknown_source"
    """The row's source is not in the registry."""
    PLATFORM = "platform"
    """The source's platform is not on :data:`REPLAY_PLATFORMS`."""
    DISTRICT_SOURCE = "district_source"
    """The source speaks for named districts only (``leaids``)."""
    NOT_MATCHED = "not_matched"
    """The matcher did not accept the listing."""
    PLACE_GUARD = "place_guard"
    """The row's own list places it away from the matched records."""
    OUT_OF_STATE = "out_of_state"
    """A matched school lies outside its station's states."""
    SECTION = "section"
    """The row's list files it under private schools and the school is public, or the reverse."""
    SCHOOL_YEAR = "school_year"
    """A school the directory lists as new (or, through its district, as moved) after the storm."""
    VIRTUAL = "virtual"
    """A virtual or online school (by the directory's flag or its name) reached only through its
    host district's row."""
    FACILITY = "facility"
    """A school in a detention center, a hospital or a treatment program, or a homebound program,
    reached only through its host district's row."""
    PART_OF_DISTRICT = "part_of_district"
    """A district row that names one school, campus, site or program: it does not speak for
    every school."""
    UNANCHORED = "unanchored"
    """A public school a row names by its name alone: no place, level word or district of its own
    backs the match, so the row may be a private namesake."""
    ZONE_UNKNOWN = "zone_unknown"
    """A matched school has no known time zone."""
    ZONE_SPLIT = "zone_split"
    """The row's schools span zones and the readings disagree on the day."""
    READ_UNREADABLE = "read_unreadable"
    """Over a quarter of the read's rows hold nothing the reader recognizes."""
    READ_LOW_MATCH = "read_low_match"
    """The read matches under half its station's median share."""
    LOW_CONFIDENCE = "low_confidence"
    NOT_FOR_DAY = "not_for_day"
    NOTE = "note"
    SAYS_OPEN = "says_open"
    OTHER_CAUSE = "other_cause"
    OPEN_ENDED = "open_ended"
    NON_WEATHER_WORDS = "non_weather_words"
    DETAIL_MODE = "detail_mode"
    """The row's comment names a learning mode the reading does not give (e-learning, AMI, NTI)."""
    DATE_OUT_OF_RANGE = "date_out_of_range"
    OUTSIDE_WINDOW = "outside_window"
    STALE_POST = "stale_post"
    """Read at the row's own posted time, the row says something else for the day."""
    CONFLICT_IN_LIST = "conflict_in_list"
    """Two readings of one station disagree for a school."""
    SUPERSEDED = "superseded"
    """A later capture of the same list no longer holds the claim."""
    CONFLICT = "conflict"
    """Two stations give the school different statuses (counted or not)."""
    WITHDRAWN = "withdrawn"
    """A station's later list withdrew the school or contradicted itself: no claim lights it."""
    WEEKEND = "weekend"
    HOLIDAY = "holiday"
    DAY_SCHOOL_YEAR = "day_school_year"


# --- the status reader, as a protocol ---------------------------------------------------------


class Entry(Protocol):
    """One dated status the reader states (shaped like ``classify.DatedStatus``)."""

    @property
    def kind(self) -> str: ...
    @property
    def dates(self) -> Sequence[date]: ...
    @property
    def dates_stated(self) -> bool: ...
    @property
    def until_further_notice(self) -> bool: ...


class Parsed(Protocol):
    """What the reader makes of one listing (shaped like ``classify.ParsedStatus``)."""

    @property
    def kind(self) -> str: ...
    @property
    def schedule(self) -> Sequence[Entry]: ...
    @property
    def reason(self) -> str | None: ...
    @property
    def other_causes(self) -> Sequence[str]: ...
    @property
    def confidence(self) -> float: ...
    @property
    def says_open(self) -> bool: ...
    @property
    def notes(self) -> Sequence[str]: ...

    def on(self, day: date, /) -> Entry | None:
        """The status the text states for local date ``day``, if any."""
        ...


class ParseFn(Protocol):
    """``parse_status(text, *, posted_at, tz)``: the status reader (f5)."""

    def __call__(self, text: str, *, posted_at: datetime, tz: str) -> Parsed: ...


# --- source gates -------------------------------------------------------------------------------

REPLAY_PLATFORMS: Final[frozenset[str]] = frozenset(
    {
        "gray",
        "nexstar",
        "nexstar-typed",
        "sinclair",
        "tegna",
        "scripps",
        "scripps-typed",
        "hearst",
        "fox-owned",
        "cbs-owned",
        "nbc-owned",
        "abc-owned",
        "cox",
        "graham",
        "hubbard",
        "cowles",
        "spectrum",
        "news12",
        "allen",
        "flashalert",
        "blox",
        "radio",
        "townsquare",
        "wral",
        "wtop",
        "whdh",
    }
)
"""Multi-organization TV and radio closing lists: the only rows a replay reads."""
STATUS_BOARDS: Final[frozenset[str]] = frozenset(
    {"gohsep", "flathead", "coesheet", "wveis", "alsde", "delaware"}
)
"""State and county status boards, out (a board can keep a stale layer up for days)."""
DISTRICT_SITES: Final[frozenset[str]] = frozenset(
    {
        "apptegy",
        "finalsite",
        "edlio",
        "schoolblocks",
        "sharpschool",
        "smartsites",
        "district-homepage",
        "nisd",
        "santacruzcoe",
        "pasco",
        "dadeschools",
        "hcoe",
        "district-pages",
        "apptegy-feed",
    }
)
"""A district's own site or banner: it speaks for itself, not a market."""
UNCLASSIFIED: Final[frozenset[str]] = frozenset(
    {
        "ecc",
        "eventdelay",
        "heritage",
        "lockwood",
        "ncpr",
        "npg",
        "npg-articles",
        "riba",
        "weatherthreat",
    }
)
"""Platforms no replay critic has classified yet, out until one does."""
KNOWN_OUT: Final[frozenset[str]] = (
    frozenset(EXCLUDED_PLATFORMS) | STATUS_BOARDS | DISTRICT_SITES | UNCLASSIFIED
)
"""Every platform that is out by name; a platform in neither set is out as well."""


def source_drop(station: Station | None) -> Drop | None:
    """Why a source's rows never light a replay, or ``None`` when they may."""
    if station is None:
        return Drop.UNKNOWN_SOURCE
    if station.platform not in REPLAY_PLATFORMS:
        return Drop.PLATFORM
    if station.leaids:
        return Drop.DISTRICT_SOURCE
    return None


# --- claim gates --------------------------------------------------------------------------------

MIN_CONFIDENCE: Final = 0.8
"""The reader's judgment-call level (``classify.model.JUDGMENT``): below it, no claim."""
ALLOWED_NOTES: Final[frozenset[str]] = frozenset({"undated", "unread_words"})
"""The only reader notes a counted claim may carry."""
NON_WEATHER_WORDS: Final = re.compile(
    r"\b(?:in[\s-]?service|teacher\s+work\s*days?|professional\s+development|pd\s+days?|"
    r"staff\s+development|records?\s+days?|conferences?|planning|teacher\s+days?|"
    r"staff\s+days?|work\s*days?|grading\s+days?|breaks?|make[\s-]?up\s+days?|holidays?|"
    r"vacation|semester(?!\s+exams?\b)|end\s+of\s+(?:the\s+)?(?:quarter|term)|"
    r"teachers?'?\s+institute|institute\s+days?|inaugurat\w*|fair\s+days?|minimum\s+days?|"
    r"early\s+release\s+(?:schedule|days?)|(?:previously\s+)?scheduled|"
    r"regular(?:ly)?\s+(?:scheduled|schedule|early|weekly)|"
    r"(?:normal|per|usual)\b[^.;|]{0,40}\bschedule|no\s+school\s+for\s+students|"
    r"exam\s+days?|(?:(?:final|semester|mid-?term)\s+exams?|exams?|mid-?terms?)"
    r"(?!\s+(?:exams?\s+)?(?:(?:will\s+be|are|have\s+been|is)\s+)?"
    r"(?:postponed|rescheduled|moved|delayed|cancell?ed))|staff\s+training|days?\s+off|non[\s-]?student|"
    r"test(?:ing)?\s+(?:school|entry|status|message|only|row|listing)|"
    r"disregard(?!\s+(?:the\s+|our\s+|any\s+)?(?:previous|prior|earlier|last|above)\b)|"
    r"^\W*test(?:ing)?\b)\b",
    re.IGNORECASE,
)
"""Words for a planned non-weather day off or a school's own schedule (an early release it
holds every week, a day it scheduled, an exam day, a day off), or a list's test row ("TEST -
Closed", "Testing status - Disregard"). Exams put off for the weather ("Final exams postponed")
and a message that replaces an earlier one ("disregard previous message") are weather. A stop-gap
until the reader names them as causes."""
LEARNING_WORDS: Final = re.compile(
    r"\b(?:e[\s-]?learning|elearning|nti|ami|virtual|remote|remotely|online|synchronous|"
    r"asynchronous|distance\s+learning|flexible\s+instruction|digital\s+learning|"
    r"at[\s-]home\s+learning|non[\s-]?traditional\s+instruction|"
    r"alternative\s+methods?\s+of\s+instruction|packets?|e[\s-]?days?|google\s+classroom|"
    r"work(?:ing)?\s+from\s+home|flex(?:ible)?\s+learning|digital\s+days?)\b",
    re.IGNORECASE,
)
"""Words for a learning mode. A row with one of them lights only a remote-learning reading."""
NOT_LEARNING_BEFORE: Final = re.compile(
    r"\b(?:no|not|without|nor)\b(?:\s+(?:an?|the|more))?"
    r"(?:\s+(?!(?:school|schools|classes|class|students?)\b)\w+)?\s+$"
    r"|\b(?:no|not|without|nor)[\s-]$",
    re.IGNORECASE,
)
"""Right before a learning word: a negation ("No remote learning", "not an e-learning day",
"No NTI", "No-NTI"). One other word may stand between, apart by a space: not "school" or
"classes" ("No School/Snow Packet Day" and "No school snow packet day" are packet days), and not
a word glued on with a hyphen ("No bus-eDay" and "do not report-Snow Packet Day" are e-days)."""
STAFF_BEFORE: Final = re.compile(
    r"\b(?:staff|offices?|employees|faculty|personnel|teachers?)\b[^.;|]{0,25}$", re.IGNORECASE
)
"""Before a learning word: the staff or offices ("staff working remotely", "offices operating
remotely"): it says nothing of the students, unless its clause names them too."""
STUDENT_WORDS: Final = re.compile(
    r"\b(?:students?|pupils?|kids|learners?|children|scholars|families)\b", re.IGNORECASE
)
"""Words for the students: a clause that names them with the staff ("Students and staff work
from home", "Faculty and students: eDay") says the students learn that way."""
NOT_LEARNING_AFTER: Final = re.compile(
    r"^\s+(?:forms?|enrollment|registration|resources?|services?|application|payments?|store|"
    r"at\b|for\s+(?:more|updates))",
    re.IGNORECASE,
)
"""After "online" and the like: a form, a service or a page, not a way of learning."""
OPEN_HEAD: Final = re.compile(
    r"^\W*(?:open|on[\s-]?time|normal)\b(?P<rest>[^;.|,]*)", re.IGNORECASE
)
"""A status or comment that begins by saying the school is open ("Open", "On time", "Normal")."""
LATE_WORDS: Final = re.compile(r"\d|@|\b(?:late|later|delay\w*|at|noon|until)\b", re.IGNORECASE)
"""Words after an opening "Open" that make it a late opening ("Open 2 hours late", "Open at 10")."""
OPEN_ON_TIME: Final = re.compile(
    r"(?<!\boffices\s)(?<!\boffice\s)\bopen(?:s|ing)?\s+on[\s-]?time\b", re.IGNORECASE
)
"""The school "will open on time" (not its offices)."""
TODAY_WORDS: Final = re.compile(
    r"\b(?:today|tonight|this\s+(?:morning|afternoon|evening))\b", re.IGNORECASE
)
"""Day words that mean the posting day: they name the day the list was posted, not the capture's."""
TOMORROW_WORDS: Final = re.compile(r"\b(?:tomorrow|tonight)\b", re.IGNORECASE)
"""Day words that mean the day after the posting day (tonight, for a list posted in the evening)."""
WEEKDAYS: Final = (
    r"mon(?:day)?",
    r"tue(?:s|sday)?",
    r"wed(?:nesday)?",
    r"thu(?:r|rs|rsday)?",
    r"fri(?:day)?",
    r"(?!(?-i:SAT)\b)sat(?:urday)?",
    r"sun(?:day)?",
)
"""Each weekday's words, Monday first. An all-caps "SAT" is the test, not Saturday ("SAT testing
moved"); "SATURDAY" and "Sat" are the day."""
MONTHS: Final = (
    r"jan(?:uary)?",
    r"feb(?:ruary)?",
    r"mar(?:ch)?",
    r"apr(?:il)?",
    r"may",
    r"june?",
    r"july?",
    r"aug(?:ust)?",
    r"sept?(?:ember)?",
    r"oct(?:ober)?",
    r"nov(?:ember)?",
    r"dec(?:ember)?",
)
"""Each month's words, January first."""
RANGE_BEFORE: Final = 2
RANGE_AFTER: Final = 6
"""Every date the reader states lies within these days of the capture's local date."""
DATED_FROM: Final = time(12)
UNDATED_FROM: Final = time(4)
WINDOW_END: Final = time(12)
REMOTE: Final = "remote"


def capture_window(day: date, zone: str, *, dated: bool) -> tuple[datetime, datetime]:
    """The UTC span a capture must fall in to count for ``day`` in ``zone``.

    A row that states its date counts from noon two days before; a row with no
    date of its own counts only from 04:00 to noon of the day itself, so an
    evening list never lights the next day.
    """
    tz = ZoneInfo(zone)
    first = day - timedelta(days=RANGE_BEFORE) if dated else day
    start = datetime.combine(first, DATED_FROM if dated else UNDATED_FROM, tzinfo=tz)
    end = datetime.combine(day, WINDOW_END, tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)


def in_window(captured_at: datetime, day: date, zone: str, *, dated: bool) -> bool:
    """Whether a capture falls in ``day``'s window (see :func:`capture_window`)."""
    start, end = capture_window(day, zone, dated=dated)
    return start <= captured_at < end


STAMP_PHRASE: Final = re.compile(
    r"\b(?:(?:last\s+)?updated|posted|as\s+of|edited|modified)\b[^.;|]*", re.IGNORECASE
)
"""A stamp in the row's words ("Updated Tuesday 5:00 AM"): the day it names is when the row was
written, not the day the status is for."""


def names_day(text: str, day: date) -> bool:
    """Whether ``text`` names ``day`` itself: its weekday, its month and day, or its date.

    A day named only in a stamp phrase (:data:`STAMP_PHRASE`) does not count.
    """
    text = STAMP_PHRASE.sub(" ", text)
    weekday = re.compile(rf"\b{WEEKDAYS[day.weekday()]}\b\.?", re.IGNORECASE)
    month = MONTHS[day.month - 1]
    worded = re.compile(rf"\b{month}\.?\s*0?{day.day}(?!\d)", re.IGNORECASE)
    numeric = re.compile(
        rf"(?<![\d/])0?{day.month}/0?{day.day}(?![\d])|\b{day.isoformat()}\b", re.IGNORECASE
    )
    return bool(weekday.search(text) or worded.search(text) or numeric.search(text))


def relative_today(text: str, captured_at: datetime, day: date, zone: str) -> bool:
    """Whether ``text`` names ``day`` only as "today", in a capture made on ``day`` itself.

    Such a text was posted on some day and still says "today": a list left up
    from the day before, captured after midnight, would name the wrong day. It
    gets the undated window (from 04:00), as if it stated no date. Only a word
    that names ``day`` itself ("Tuesday", "1/16") dates it; another day's word
    ("Updated Monday") does not.
    """
    local = captured_at.astimezone(ZoneInfo(zone)).date()
    return local == day and bool(TODAY_WORDS.search(text)) and not names_day(text, day)


def relative_tomorrow(
    text: str, captured_at: datetime, day: date, zone: str, posted_on: date | None = None
) -> bool:
    """Whether ``text`` names ``day`` only as "tomorrow", in a capture before noon the day before.

    The reader reads "tomorrow" against the capture, so a "Closed tomorrow" left
    up from the evening before, captured the next morning, names a day too late.
    Unless the list's own posted stamp is on the day before ``day`` or later, the
    row gets the undated window, as if it stated no date.
    """
    local = captured_at.astimezone(ZoneInfo(zone))
    before = day - timedelta(days=1)
    if local.date() != before or local.time() >= DATED_FROM:
        return False
    if posted_on is not None and posted_on >= before:
        return False
    return bool(TOMORROW_WORDS.search(text)) and not names_day(text, day)


CLAUSE_END: Final = re.compile(r"[.;|]")
"""What ends a clause of a row's words ("Closed Wednesday; Remote learning Thursday")."""
ABBREVIATION_DOT: Final = re.compile(
    r"\b(?:mon|tues?|wed|thu|thur|thurs|fri|sat|sun|jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec)"
    r"\.(?=\s*\d)",
    re.IGNORECASE,
)
"""A weekday's or month's abbreviation and its dot before a number ("Jan. 9", "Thurs. 1/9"):
the dot ends no clause. A full word's dot ("Closed through Wednesday.") does."""
ORDINAL: Final = r"(?:st|nd|rd|th)?"
"""An ordinal's suffix after a day's number ("Jan 15th")."""


def _clause(text: str, start: int, end: int, ends: re.Pattern[str] = CLAUSE_END) -> str:
    """The clause of ``text`` around ``text[start:end]`` (between ``.``, ``;`` or ``|``, or
    the marks ``ends`` matches).

    The dot of a weekday's or month's abbreviation ends no clause ("eLearning Jan. 9").
    """
    marks = ABBREVIATION_DOT.sub(lambda found: found.group(0)[:-1] + " ", text)
    before = [found.end() for found in ends.finditer(marks, 0, start)]
    after = ends.search(marks, end)
    return text[before[-1] if before else 0 : after.start() if after else len(text)]


def _day_token(prefix: str) -> str:
    """A weekday, a month and day, or a numeric date, in groups named with ``prefix``."""
    return (
        rf"(?:\b(?P<{prefix}wd>{'|'.join(WEEKDAYS)})\b\.?"
        rf"|\b(?P<{prefix}mo>{'|'.join(MONTHS)})\.?\s*(?P<{prefix}md>\d{{1,2}}){ORDINAL}(?!\d)"
        rf"|(?<![\d/])(?P<{prefix}nm>\d{{1,2}})/(?P<{prefix}nd>\d{{1,2}})(?:/\d{{2,4}})?(?![\d/]))"
    )


SPAN: Final = re.compile(
    rf"{_day_token('a')}\s*(?:-|\u2013|\u2014|\bto\b|\bthrough\b|\bthru\b|\buntil\b|\btill\b)\s*"
    rf"(?:{_day_token('b')}|(?P<bday>\d{{1,2}}){ORDINAL}(?![\d/]))",
    re.IGNORECASE,
)
"""A span of days ("Mon-Wed", "Jan 15-17", "Jan 15th - 17th", "1/15 - 1/17", "Tuesday
through Friday")."""
OPEN_SPAN: Final = re.compile(
    rf"\b(?P<op>through|thru|until|till|starting|beginning|from)\s+(?:(?:this|next)\s+)?"
    rf"{_day_token('c')}",
    re.IGNORECASE,
)
"""A span with one end ("through Friday", "starting Jan 15")."""
DAY_LIST: Final = re.compile(
    rf"{_day_token('l')}(?P<more>(?:\s*(?:,|&|\+|\band\b|\bor\b)\s*(?:and\s+|&\s*)?"
    rf"\d{{1,2}}{ORDINAL}(?![\d/:])(?!\s*(?:h|hrs?|hours?|am|pm|a\.m|p\.m|min\w*)\b))*)",
    re.IGNORECASE,
)
"""One day, or a month's day and more days of the same month after it ("Jan 15, 16 and 17",
"January 15th & 16th", "1/15 & 16"); a number of hours or a time after it is no day."""
ISO_DATE: Final = re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})\b")
"""A date in ISO form ("2024-01-16")."""
RELATIVE_DAY: Final = re.compile(
    r"\b(?:(?P<today>today|this\s+(?:morning|afternoon|evening))|(?P<tonight>tonight)|"
    r"(?P<tomorrow>tomorrow)|(?P<yesterday>yesterday))(?:'?s)?\b",
    re.IGNORECASE,
)
"""A day named by its distance from the posting day."""
RELATIVE_OFFSETS: Final[Mapping[str, tuple[int, ...]]] = {
    "today": (0, -1),
    "tonight": (0, 1),
    "tomorrow": (1, 0),
    "yesterday": (-1, -2),
}
"""The days after the capture's local date that a relative word may name. A list may have been
posted the day before its capture and left up, so "today" may be the day before and "tomorrow"
the capture's own day; "tonight" may be the evening's own day or the school day after it."""
UNRESOLVED_DAY: Final = re.compile(
    rf"\b\d{{1,2}}(?:st|nd|rd|th)\b|\b(?:{'|'.join(MONTHS)})\.?\s*\d|\bday\s*#?\s*\d{{1,2}}\b"
    r"|#\s*\d{1,2}\b",
    re.IGNORECASE,
)
"""Day words left over when the known forms are read: an ordinal on its own ("17th"), a month
with a number in no known form, a numbered day ("Day 2", "#3"). Any of them may be the day."""
WEEK_SPAN: Final = re.compile(
    r"\b(?:(?:this|all|the|next|rest\s+of\s+(?:the|this)|remainder\s+of\s+(?:the|this))\s+week|"
    r"until\s+further\s+notice|daily|every\s*day|each\s+day)\b",
    re.IGNORECASE,
)
"""Words for a run of days whose ends are not named ("this week", "until further notice")."""
CLOSE_YEAR: Final = 183
"""A month and day with no year is in the year that puts it nearest the day."""


def _when(found: re.Match[str], prefix: str, day: date) -> int | date | None:
    """The weekday (``0`` is Monday) or the date a day token names, nearest ``day``."""
    weekday = found.group(f"{prefix}wd")
    if weekday is not None:
        return next(i for i, words in enumerate(WEEKDAYS) if re.fullmatch(words, weekday, re.I))
    month_word = found.group(f"{prefix}mo")
    if month_word is not None:
        month = next(
            i for i, words in enumerate(MONTHS, 1) if re.fullmatch(words, month_word, re.I)
        )
        return _near(month, int(found.group(f"{prefix}md")), day)
    return _near(int(found.group(f"{prefix}nm")), int(found.group(f"{prefix}nd")), day)


def _near(month: int, number: int, day: date) -> date | None:
    """``month``/``number`` in the year nearest ``day``, or ``None`` when no such date exists."""
    for year in (day.year, day.year + 1, day.year - 1):
        try:
            when = date(year, month, number)
        except ValueError:
            return None
        if abs((when - day).days) <= CLOSE_YEAR:
            return when
    return None  # pragma: no cover - one of three years is always within half a year


def _span_covers(first: int | date | None, last: int | date | None, day: date) -> bool:
    """Whether a span from ``first`` to ``last`` may hold ``day`` (yes, unless both ends say
    it cannot)."""
    if isinstance(first, int) and isinstance(last, int):
        if first > last:  # over the weekend ("Fri-Mon")
            return day.weekday() >= first or day.weekday() <= last
        return first <= day.weekday() <= last
    if isinstance(first, date) and isinstance(last, date):
        return first <= day <= last
    return True


def _span_may_hold(found: re.Match[str], day: date) -> bool:
    """Whether a :data:`SPAN` may hold ``day``."""
    first = _when(found, "a", day)
    bare = found.group("bday")
    last: int | date | None
    if bare is not None:
        last = _near(first.month, int(bare), day) if isinstance(first, date) else None
    else:
        last = _when(found, "b", day)
    return _span_covers(first, last, day)


def _from_or_until(found: re.Match[str], day: date) -> bool:
    """Whether a span with one end ("through Friday", "starting Jan 15") may hold ``day``."""
    end = _when(found, "c", day)
    until = found.group("op").casefold() in {"through", "thru", "until", "till"}
    if isinstance(end, int):
        return day.weekday() <= end if until else day.weekday() >= end
    if isinstance(end, date):
        return day <= end if until else day >= end
    return True


def _list_may_hold(found: re.Match[str], day: date) -> bool:
    """Whether a :data:`DAY_LIST` may name ``day``: a day it names cannot be resolved, or is
    ``day``."""
    first = _when(found, "l", day)
    if isinstance(first, int):
        return first == day.weekday()
    if first is None or first == day:
        return True
    more = (_near(first.month, int(number), day) for number in re.findall(r"\d+", found["more"]))
    return any(when is None or when == day for when in more)


def _iso_may_be(found: re.Match[str], day: date) -> bool:
    """Whether an :data:`ISO_DATE` may be ``day`` (an impossible date may)."""
    try:
        return date(int(found["y"]), int(found["m"]), int(found["d"])) == day
    except ValueError:
        return True


def _relative_may_be(found: re.Match[str], day: date, posted: date | None) -> bool:
    """Whether a :data:`RELATIVE_DAY` may name ``day``, for a capture made on the local date
    ``posted`` (with none known, it may)."""
    if posted is None:
        return True
    offsets = RELATIVE_OFFSETS[found.lastgroup or "today"]
    return any(posted + timedelta(days=offset) == day for offset in offsets)


def day_words(text: str, day: date, posted: date | None = None) -> tuple[bool, bool]:
    """Whether ``text`` names any day, and whether one of the days it names may be ``day``.

    Every day word is read: a weekday, a month and day (with an ordinal: "Jan
    15th"), a numeric or ISO date, a list of a month's days ("Jan 15, 16 and
    17"), a span ("Jan 15-17", "Mon-Wed", "through Friday"), a run of days
    ("this week") and a relative word ("today", "tomorrow"), read against
    ``posted``, the capture's local date (see :data:`RELATIVE_OFFSETS`). A day
    word that cannot be resolved ("17th" alone, "Day 2", a date such as 2/30)
    may be ``day``. A day named only in a stamp phrase (:data:`STAMP_PHRASE`)
    does not count.
    """
    words = STAMP_PHRASE.sub(" ", text)
    if names_day(words, day) or WEEK_SPAN.search(words):
        return True, True
    seen: list[bool] = []

    def read(check: Callable[[re.Match[str]], bool]) -> Callable[[re.Match[str]], str]:
        def mark(found: re.Match[str]) -> str:
            seen.append(check(found))
            return " "

        return mark

    words = SPAN.sub(read(lambda found: _span_may_hold(found, day)), words)
    words = OPEN_SPAN.sub(read(lambda found: _from_or_until(found, day)), words)
    words = ISO_DATE.sub(read(lambda found: _iso_may_be(found, day)), words)
    words = DAY_LIST.sub(read(lambda found: _list_may_hold(found, day)), words)
    words = RELATIVE_DAY.sub(read(lambda found: _relative_may_be(found, day, posted)), words)
    if UNRESOLVED_DAY.search(words):
        seen.append(True)
    return bool(seen), any(seen)


def could_name(clause: str, day: date, posted: date | None = None) -> bool:
    """Whether a clause may be about ``day``: one of the days it names may be ``day``
    (:func:`day_words`).

    "Snow Packet Days Jan 15-17", "Google Classroom days: Mon-Wed", "Remote
    learning through Friday", "E-days this week" and "Packet days Jan 15th, 16th"
    may all hold a Tuesday, Jan 16.
    """
    return day_words(clause, day, posted)[1]


def about_other_days(text: str, day: date, posted: date | None = None) -> bool:
    """Whether ``text`` names days and every one of them is resolved and none may be ``day``
    (:func:`day_words`)."""
    named, may = day_words(text, day, posted)
    return named and not may


STAFF_WORDS_FOR: Final = re.compile(
    r"^(?:remote|remotely|virtual|online|work(?:ing)?\s+from\s+home)$", re.IGNORECASE
)
"""The learning words that may say where the staff work ("staff working remotely"), not how
the students learn. A packet, an e-day or a Google Classroom day is the students' own."""


def learning_mode(text: str, day: date | None = None, posted: date | None = None) -> bool:
    """Whether ``text`` says the students learn another way (e-learning, AMI, a packet day).

    A negated learning word ("No remote learning", "No NTI - treat as a snow
    day"), one about the staff or offices alone ("staff working remotely") and
    an online form or service ("complete the online form") do not count. With
    ``day``, neither does one in a clause whose day words are all resolved and
    none may be ``day`` ("Closed Wednesday; Remote learning Thursday and Friday"
    for the Wednesday): that clause is about the other days
    (:func:`about_other_days`, with ``posted`` the capture's local date for
    "today" and "tomorrow"). A clause with a day word that cannot be resolved
    may be about ``day``.
    """
    for found in LEARNING_WORDS.finditer(text):
        before = text[max(0, found.start() - 40) : found.start()]
        if NOT_LEARNING_BEFORE.search(before) or NOT_LEARNING_AFTER.match(text[found.end() :]):
            continue
        clause = _clause(text, found.start(), found.end())
        if (
            STAFF_WORDS_FOR.match(found.group(0))
            and STAFF_BEFORE.search(before)
            and not STUDENT_WORDS.search(clause)
        ):
            continue
        if day is not None and about_other_days(clause, day, posted):
            continue
        return True
    return False


def says_open(text: str, detail: str = "") -> bool:
    """Whether the row's status or one of its comments says the school is open.

    It begins with "Open", "On time" or "Normal" and no late opening follows
    ("Open 2 hours late" is a delay), or it says the school opens on time. The
    reader may miss these beside another status ("Open; dismissal at 1:00
    following our Wednesday early release schedule").
    """
    parts = [text, *(part for part in detail.split(". ") if part)]
    for part in parts:
        head = OPEN_HEAD.match(part)
        if head is not None and not LATE_WORDS.search(head.group("rest")):
            return True
    return bool(OPEN_ON_TIME.search(text))


def claim_for_day(  # noqa: PLR0911, PLR0913 - one return per gate; the row and its day
    parsed: Parsed,
    day: date,
    captured_at: datetime,
    zone: str,
    *,
    text: str = "",
    name: str = "",
    detail: str = "",
    window_day: date | None = None,
    check_range: bool = True,
    posted_on: date | None = None,
) -> Entry | Drop:
    """The reader's entry for ``day``, when every claim gate holds; else the first failure.

    ``parsed`` is the reader's result for ``text`` (the row's status and its
    comments, :func:`snowlight.replays.rows.reader_text`), read with
    ``posted_at=captured_at`` and ``tz=zone``. ``name`` and ``text`` are checked
    for :data:`NON_WEATHER_WORDS`, and ``text`` for a learning mode
    (:func:`learning_mode`) unless the entry is remote; ``detail`` (the comments
    alone) is checked for an open comment (:func:`says_open`). The
    capture window is ``window_day``'s (by default ``day``'s); the D+7 control
    asks for a later day from the same captures, and with ``check_range=False``
    so the date-range gate does not hide what the reader dated there.
    ``posted_on`` is the local date of the row's own posted stamp, when its list
    gives one (:func:`relative_tomorrow`).

    A dated entry whose only day word is relative gets the undated window: "today"
    in a capture after midnight (:func:`relative_today`), and "tomorrow" in a
    capture before noon the day before, unless the row was posted that day or
    later (:func:`relative_tomorrow`).
    """
    if parsed.confidence < MIN_CONFIDENCE:
        return Drop.LOW_CONFIDENCE
    entry = parsed.on(day)
    if entry is None or entry.kind not in STATUS_BY_KIND:
        return Drop.NOT_FOR_DAY
    if not set(parsed.notes) <= ALLOWED_NOTES:
        return Drop.NOTE
    if parsed.says_open or says_open(text, detail):
        return Drop.SAYS_OPEN
    if parsed.other_causes:
        return Drop.OTHER_CAUSE
    if entry.until_further_notice:
        return Drop.OPEN_ENDED
    if NON_WEATHER_WORDS.search(name) or NON_WEATHER_WORDS.search(text):
        return Drop.NON_WEATHER_WORDS
    local = captured_at.astimezone(ZoneInfo(zone)).date()
    if entry.kind != REMOTE and learning_mode(text, day, local):
        return Drop.DETAIL_MODE
    low, high = local - timedelta(days=RANGE_BEFORE), local + timedelta(days=RANGE_AFTER)
    if check_range and any(
        not low <= when <= high for item in parsed.schedule for when in item.dates
    ):
        return Drop.DATE_OUT_OF_RANGE
    dated = (
        entry.dates_stated
        and not relative_today(text, captured_at, day, zone)
        and not relative_tomorrow(text, captured_at, day, zone, posted_on)
    )
    if not in_window(captured_at, window_day or day, zone, dated=dated):
        return Drop.OUTSIDE_WINDOW
    return entry


def speaks_for(
    parsed: Parsed, entry: Entry | None, day: date, text: str, posted: date | None = None
) -> bool:
    """Whether a reading may be about ``day``: it gives ``day`` a status, its words name
    ``day``, or it states no status and its words do not name other days only
    (:func:`about_other_days`, with ``posted`` the capture's local date)."""
    if entry is not None or names_day(text, day):
        return True
    return not parsed.schedule and not about_other_days(text, day, posted)


RETRACT_WORDS: Final = re.compile(
    r"\b(?:rescind\w*|cancel\w*|revok\w*|disregard\w*|withdr[ae]wn?|withdraw\w*|retract\w*|"
    r"called\s+off|no\s+longer|revers\w*|never\s*mind|lift\w*|supersed\w*|in\s+error|mistake\w*|"
    r"erroneous\w*|not|no|now|instead|changed?|correct\w*)\b",
    re.IGNORECASE,
)
"""Words that take a status back, deny it or replace it ("rescinded", "cancelled", "Disregard",
"No delay", "now 2 hour delay"): where a reading's retraction stands in its words."""
PHRASE_END: Final = re.compile(r"[.;|,()!?]|\s[-\u2013\u2014]+\s|[\u2013\u2014]")
"""What ends the phrase that holds a retraction word: a clause's end, a comma, a parenthesis or
a dash between spaces ("Closing rescinded - make up day Feb 19")."""


def retracts(entry: Entry | None, day: date, text: str, posted: date | None = None) -> bool:
    """Whether a reading the reader finds revoked, negated or superseded takes back ``day``.

    It does when it gives ``day`` a status or its words name ``day``. Otherwise
    each retraction word (:data:`RETRACT_WORDS`) is read in its own phrase
    (:data:`PHRASE_END`): the reading takes back ``day`` unless every such phrase
    names days that are all resolved and none of them may be ``day``
    (:func:`about_other_days`: "Monday's closing rescinded" for a Tuesday). A
    phrase that names no day ("Closing rescinded. Make-up day will be Friday",
    "Closing cancelled - buses will run Wednesday") or a day it may hold
    ("Today's closure has been rescinded; closed tomorrow", "Closings for Jan
    15th-17th have been rescinded") takes back ``day``. Words with no retraction
    word in them take it back unless they name other days only.
    """
    if entry is not None or names_day(text, day):
        return True
    words = STAMP_PHRASE.sub(" ", text)
    found = list(RETRACT_WORDS.finditer(words))
    if not found:
        return not about_other_days(words, day, posted)
    return any(
        not about_other_days(_clause(words, word.start(), word.end(), PHRASE_END), day, posted)
        for word in found
    )


RETRACT_NOTES: Final[frozenset[str]] = frozenset({"revoked", "negated", "superseded"})
"""Reader notes that take a status back, deny it or replace it."""
DOUBT_NOTES: Final[frozenset[str]] = frozenset({"ambiguous", "partial_program", "conflict"})
"""Reader notes that narrow a status to part of the school or find statuses that disagree."""
DISSENT_NOTES: Final[frozenset[str]] = RETRACT_NOTES | DOUBT_NOTES
"""Reader notes that take back, deny or narrow a status, or find statuses that disagree."""


def dissents(
    parsed: Parsed, day: date, *, text: str = "", name: str = "", posted: date | None = None
) -> bool:
    """Whether a reading says the school's weather status for ``day`` is not what it seems.

    The reading takes the status back, denies it or replaces it
    (:data:`RETRACT_NOTES`) and takes back ``day`` (:func:`retracts`); or it
    narrows it to part of the school or is unsure which status holds
    (:data:`DOUBT_NOTES`) and may be about ``day`` (:func:`speaks_for`: a
    reading that states no status and whose words name only other days, such as
    "Closed on Monday 1/6" with a long note the reader finds ambiguous, is about
    those days). Or it gives a status for ``day`` that is not a weather closing:
    a cause other than weather, a planned day off or test row
    (:data:`NON_WEATHER_WORDS`), or a learning mode beside a status that is not
    remote (:func:`learning_mode`). Such a reading drops another row's or
    another list's claim for the school (it votes ``disputed``); the claim gates
    drop it itself. ``posted`` is the capture's local date, for "today" and
    "tomorrow". A reading uncounted only for its window, its confidence or a
    note not on these lists does not dissent: it votes its own kind.
    """
    entry = parsed.on(day)
    notes = set(parsed.notes)
    if RETRACT_NOTES & notes and retracts(entry, day, text, posted):
        return True
    if DOUBT_NOTES & notes and speaks_for(parsed, entry, day, text, posted):
        return True
    if entry is None:
        return False
    return bool(
        parsed.other_causes
        or NON_WEATHER_WORDS.search(name)
        or NON_WEATHER_WORDS.search(text)
        or (entry.kind != REMOTE and learning_mode(text, day, posted))
    )


def rejected_notes(parsed: Parsed) -> list[str]:
    """The reader notes of ``parsed`` that are not on :data:`ALLOWED_NOTES`, sorted."""
    return sorted(set(parsed.notes) - ALLOWED_NOTES)


# --- read gates ---------------------------------------------------------------------------------

UNREAD_CONFIDENCE: Final = 0.1
"""The reader's level for "nothing recognized" (``classify.model.UNKNOWN``)."""
UNREADABLE_SHARE: Final = 0.25
LOW_MATCH_FACTOR: Final = 0.5
MIN_MEDIAN_READS: Final = 3


def unread_share(confidences: Sequence[float]) -> float:
    """The share of a read's rows the reader recognizes nothing in."""
    if not confidences:
        return 0.0
    return sum(1 for value in confidences if value <= UNREAD_CONFIDENCE) / len(confidences)


def unreadable(confidences: Sequence[float]) -> bool:
    """Whether a read looks like a broken adapter: over a quarter of its rows unread."""
    return unread_share(confidences) > UNREADABLE_SHARE


def station_median(shares: Iterable[float]) -> float | None:
    """A station's median accepted-match share, or ``None`` with fewer than 3 reads."""
    values = sorted(shares)
    if len(values) < MIN_MEDIAN_READS:
        return None
    return float(median(values))


def low_match(share: float, station_median_share: float | None) -> bool:
    """Whether a read matches under half its station's median share (when there is one)."""
    if station_median_share is None:
        return False
    return share < LOW_MATCH_FACTOR * station_median_share


# --- day gates ----------------------------------------------------------------------------------

SATURDAY: Final = 5
SUNDAY: Final = 6
JANUARY: Final = 1
FEBRUARY: Final = 2
JULY: Final = 7
MONDAY: Final = 0
THIRD: Final = 3


def nth_monday(year: int, month: int, nth: int) -> date:
    """The ``nth`` Monday of a month."""
    first = date(year, month, 1)
    offset = (MONDAY - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (nth - 1))


def holidays(year: int) -> frozenset[date]:
    """The days no replay is built for in calendar ``year``.

    Dec 24 to Jan 1 (and Jan 2 when New Year's Day is a Sunday and observed on
    Monday), Martin Luther King Jr. Day and Presidents' Day.
    """
    days = {date(year, 12, day) for day in range(24, 32)}
    days.add(date(year, 1, 1))
    if date(year, 1, 1).weekday() == SUNDAY:
        days.add(date(year, 1, 2))
    days.add(nth_monday(year, JANUARY, THIRD))
    days.add(nth_monday(year, FEBRUARY, THIRD))
    return frozenset(days)


def school_year_of(day: date) -> int:
    """The first calendar year of the July-to-June school year ``day`` is in."""
    return day.year if day.month >= JULY else day.year - 1


def directory_year(school_years: Iterable[str]) -> int:
    """The directory's public school year (its latest ``YYYY-YYYY``), as its first year.

    Raises:
        ValueError: no school year is given.
    """
    years = [int(text[:4]) for text in school_years if text]
    if not years:
        raise ValueError("the directory names no school year")
    return max(years)


def day_ok(day: date, public_year: int) -> Drop | None:
    """Why no replay is built for ``day``, or ``None`` when one may be.

    ``public_year`` is the first year of the directory's public school year
    (:func:`directory_year`); the storm's school year must be within one of it.
    """
    if day.weekday() >= SATURDAY:
        return Drop.WEEKEND
    if day in holidays(day.year):
        return Drop.HOLIDAY
    if abs(school_year_of(day) - public_year) > 1:
        return Drop.DAY_SCHOOL_YEAR
    return None
