"""The plain details a listing states beside its status, as codes the site says in its own words.

A listing often says more than its status: which buses run, whether breakfast is served,
whether staff report. The site never republishes those words. It recognizes a closed set of
details (:class:`~snowlight.schemas.vocab.Detail`) and says each in its own plain English
(``web/src/copy-details.ts``), the same way for every list:

* who: students and staff; staff report (students stay home); staff report late;
* buses: snow routes, emergency routes, paved roads only, limited routes, no buses;
* meals: no breakfast, no lunch, no hot lunch, grab-and-go meals;
* pre-K: no morning pre-K, no afternoon pre-K, no pre-K;
* after school: activities, after-school activities or evening activities cancelled;
  childcare closed or open;
* offices: closed or open.

**Words that clearly state it.** A text is cut into clauses at list marks (``. , ; | !`` and
line breaks) and at scoping marks (a colon, a parenthesis or bracket, a slash between words,
a spaced dash). A detail is read only from a clause that is that detail and nothing else, as
one of the patterns below (a negation only as the pattern spells it, such as "no" before the
program or "will not be served" after it). A clause with anything more gives nothing: a part
of the buses, the day or the staff, a place, a route, a time, a hedge.

**The rest of the row** (:func:`read_details`) must be plain too, or the row states no detail
at all: every other clause is a status in a closed set of plain shapes with at most a day, a
clock time and a weather reason, or a day alone (:data:`_PLAIN`). A clause that could limit,
hedge, negate or contradict a detail (a word such as none, optional or TBD, a part of the
staff, a school's, area's, road's or route's name, a second sentence about the same buses or
staff) is none of those, so it voids every detail in the row, wherever it stands. So does a
question mark anywhere, a detail set off by a parenthesis or a bracket, followed by a colon,
or joined to a clause that is not a detail by a slash or a dash after it. A text that names
more than one day (which day a detail is for is not said; a weekday is one day with its own
date only), a text with a part-of-day label before a colon, and a text whose other words name
part of a district or a school (:func:`~snowlight.live.guards.names_part`) give none either.
Unknown words never give a detail and never pass as plain; nothing is inferred from the
status, the weather or another detail.

**One row's details** (:func:`row_details`): the details are for the one status the row
gives, on one day; a row that gives two days or two kinds gives none. Each detail says
something only beside some statuses (:data:`FOR_STATUS`): bus and breakfast details only on a
delayed or early-dismissal day, staff reporting only on a closed or remote day, staff
reporting late only on a delayed one; a detail beside any other status is dropped. Evening
activities cancelled counts only for a row first seen on the day it lights. Two details of
one group that cannot both hold (snow routes and no buses) drop the group.

**A school-day's details** (:func:`agreed`) are the ones its winning rows state
(:mod:`snowlight.live.merge`): for each group, the rows that state something of it must state
the same; otherwise the group is dropped. A detail never changes a status, a time or whether
a row lights: it is read only for a row that already lights a status, and goes with it.
"""

import re
from collections.abc import Iterable, Mapping
from functools import lru_cache
from typing import Final

from snowlight.live.guards import names_part
from snowlight.schemas.vocab import DETAIL_BY_CODE, Detail

type Group = str

GROUP: Final[Mapping[Detail, Group]] = {
    Detail.STUDENTS_AND_STAFF: "who",
    Detail.STAFF_REPORT: "who",
    Detail.STAFF_LATE: "who",
    Detail.BUSES_SNOW_ROUTES: "buses",
    Detail.BUSES_EMERGENCY_ROUTES: "buses",
    Detail.BUSES_PAVED_ROADS: "buses",
    Detail.BUSES_LIMITED: "buses",
    Detail.NO_BUSES: "buses",
    Detail.NO_BREAKFAST: "meals",
    Detail.NO_LUNCH: "meals",
    Detail.NO_HOT_LUNCH: "meals",
    Detail.GRAB_AND_GO: "meals",
    Detail.NO_AM_PREK: "prek",
    Detail.NO_PM_PREK: "prek",
    Detail.NO_PREK: "prek",
    Detail.ACTIVITIES_CANCELLED: "activities",
    Detail.AFTER_SCHOOL_CANCELLED: "activities",
    Detail.EVENING_CANCELLED: "activities",
    Detail.CHILDCARE_CLOSED: "childcare",
    Detail.CHILDCARE_OPEN: "childcare",
    Detail.OFFICES_CLOSED: "offices",
    Detail.OFFICES_OPEN: "offices",
}
"""Each detail's group: two rows that disagree within a group drop it."""

_EXCLUSIVE: Final = frozenset({"who", "buses", "childcare", "offices"})
"""Groups where one row may state only one detail (two say opposite things)."""

_ANY: Final = frozenset({"closed", "delayed", "remote", "early_dismissal"})
_SHIFTED: Final = frozenset({"delayed", "early_dismissal"})
_HOME: Final = frozenset({"closed", "remote"})
FOR_STATUS: Final[Mapping[Detail, frozenset[str]]] = {
    Detail.STUDENTS_AND_STAFF: _ANY,
    Detail.STAFF_REPORT: _HOME,
    Detail.STAFF_LATE: frozenset({"delayed"}),
    Detail.BUSES_SNOW_ROUTES: _SHIFTED,
    Detail.BUSES_EMERGENCY_ROUTES: _SHIFTED,
    Detail.BUSES_PAVED_ROADS: _SHIFTED,
    Detail.BUSES_LIMITED: _SHIFTED,
    Detail.NO_BUSES: _SHIFTED,
    Detail.NO_BREAKFAST: frozenset({"delayed"}),
    Detail.NO_LUNCH: _SHIFTED,
    Detail.NO_HOT_LUNCH: _SHIFTED,
    Detail.GRAB_AND_GO: _HOME,
    Detail.NO_AM_PREK: _SHIFTED | {"remote"},
    Detail.NO_PM_PREK: _SHIFTED | {"remote"},
    Detail.NO_PREK: _SHIFTED | {"remote"},
    Detail.ACTIVITIES_CANCELLED: _ANY,
    Detail.AFTER_SCHOOL_CANCELLED: _ANY,
    Detail.EVENING_CANCELLED: _ANY,
    Detail.CHILDCARE_CLOSED: _ANY,
    Detail.CHILDCARE_OPEN: _ANY,
    Detail.OFFICES_CLOSED: _ANY,
    Detail.OFFICES_OPEN: _ANY,
}
"""The statuses beside which each detail says something (a closed day has no buses to route
and no breakfast to skip)."""

SAME_DAY: Final = frozenset({Detail.EVENING_CANCELLED})
"""Details that count only for a row first seen on the day it lights (:func:`row_details`)."""

CODES: Final = frozenset(DETAIL_BY_CODE)
"""The codes a derivation stores (:attr:`~snowlight.live.resolve.Derived.details`)."""

# --- the clause patterns -------------------------------------------------------------------

_CANCELLED = r"(?:cancel+ed|canceled|called\s+off)"
_ARE = r"(?:\s+(?:is|are|will\s+be|have\s+been|has\s+been|been))?"
_BUSES = r"(?:all\s+)?(?:am\s+and\s+pm\s+|am/pm\s+)?(?:school\s+)?bus(?:es|ses)?"
_BUS_RUN = (
    rf"{_BUSES}(?:\s+(?:will|are|to))?(?:\s+be)?"
    r"(?:\s+(?:run(?:ning)?|operat(?:e|ing)|travel(?:l?ing)?|on|using|use|follow(?:ing)?))?"
    r"(?:\s+(?:on|using))?"
)
_DAY = (
    r"(?:\s+(?:today|tonight|tomorrow|on\s+(?:mon|tues|wednes|thurs|fri|satur|sun)day|"
    r"(?:mon|tues|wednes|thurs|fri|satur|sun)day))?"
)
"""A day word a clause may end on (an evening's activities cancelled tonight): the row names
one day at most (:func:`read_details`), so it is the row's own."""
_PREK = (
    r"(?:pre[- ]?k(?:indergarten)?|pre[- ]?school|pk|4k)"
    r"(?:\s+(?:classes|class|program|programs))?"
)
_CARE = (
    r"(?:child\s*care|day\s*care|before\s+and\s+after(?:[- ]school)?\s+care|"
    r"before\s+or\s+after(?:[- ]school)?\s+care|before-\s+(?:and|or)\s+after-?\s*care|"
    r"before\s+and\s+after\s+school\s+(?:care|programs?)|latchkey|extended\s+day|"
    r"school[- ]age\s+child\s*care)"
)
_ACTIVITIES = (
    r"(?:all\s+)?(?:school\s+)?(?:activities|extra[- ]?curricular\s+activities|"
    r"activities\s+(?:and|&)\s+(?:athletics|sports|events)|"
    r"(?:athletics|sports|events)\s+(?:and|&)\s+activities)"
)
_AFTER = (
    r"(?:all\s+)?(?:after[- ]?school|pm|afternoon)\s+(?:activities|sports|athletics|"
    r"activities\s+(?:and|&)\s+(?:athletics|sports)|activities/sports)"
)
_EVENING = r"(?:all\s+)?(?:evening|night)\s+(?:activities|events|activities\s+(?:and|&)\s+events)"
_OFFICES = (
    r"(?:all\s+)?(?:(?:district|central|administrative|admin|school\s+district)\s+offices?|"
    r"(?:the\s+)?(?:district|central)\s+office|all\s+offices|offices)"
)
_SERVED = r"(?:\s+(?:will\s+be\s+)?(?:served|provided|offered|available))?"
_NOT_SERVED = r"\s+(?:will\s+not|won't|is\s+not|not)\s+be\s+(?:served|provided|offered)"
_STAFF = r"(?:all\s+)?(?:staff|employees|faculty\s+and\s+staff|staff\s+members)"

_PATTERNS: Final[tuple[tuple[Detail, str], ...]] = (
    (
        Detail.STUDENTS_AND_STAFF,
        r"(?:closed\s+)?(?:for\s+)?(?:all\s+)?(?:students\s+(?:and|&)\s+staff|"
        r"staff\s+(?:and|&)\s+students)",
    ),
    (
        Detail.STAFF_REPORT,
        rf"{_STAFF}(?:\s+(?:must|should|will|to|are\s+to))?\s+report(?:\s+to\s+work)?"
        r"(?:\s+as\s+(?:normal|usual|scheduled))?",
    ),
    (
        Detail.STAFF_LATE,
        rf"{_STAFF}(?:\s+(?:must|should|will|to|are\s+to))?\s+report\s+(?:late|"
        r"(?:\d|one|two|three)\s*(?:-|\s)?(?:hours?|hrs?)\s+late)",
    ),
    (
        Detail.BUSES_SNOW_ROUTES,
        rf"(?:{_BUS_RUN}\s+snow\s+routes?|snow\s+routes)(?:\s+in\s+effect)?",
    ),
    (Detail.BUSES_EMERGENCY_ROUTES, rf"(?:{_BUS_RUN}\s+)?emergency\s+routes?(?:\s+in\s+effect)?"),
    (
        Detail.BUSES_PAVED_ROADS,
        rf"(?:{_BUS_RUN}\s+)?(?:hard[- ]?surface(?:d)?|paved)\s+(?:roads?|routes?)\s+only",
    ),
    (
        Detail.BUSES_LIMITED,
        rf"(?:{_BUS_RUN}\s+)?limited\s+(?:bus\s+)?(?:routes?|bus\s+service|transportation)",
    ),
    (
        Detail.NO_BUSES,
        r"(?:no\s+(?:school\s+)?(?:bus(?:es|ses)?|bus\s+service|busing|bussing|transportation)"
        rf"{_SERVED}|{_BUSES}(?:\s+(?:will|are))?\s+not\s+(?:run(?:ning)?|operat(?:e|ing))|"
        r"(?:there\s+will\s+be\s+)?no\s+transportation\s+(?:service|provided))",
    ),
    (
        Detail.NO_BREAKFAST,
        rf"(?:no\s+breakfast(?:\s+(?:program|service))?{_SERVED}|"
        rf"breakfast(?:\s+(?:program|service))?(?:{_NOT_SERVED}|{_ARE}\s+{_CANCELLED}))",
    ),
    (
        Detail.NO_LUNCH,
        rf"(?:no\s+lunch(?:\s+service)?{_SERVED}|lunch(?:{_NOT_SERVED}|{_ARE}\s+{_CANCELLED}))",
    ),
    (
        Detail.NO_HOT_LUNCH,
        rf"(?:no\s+hot\s+lunch(?:\s+service)?{_SERVED}|hot\s+lunch(?:{_NOT_SERVED}|"
        rf"{_ARE}\s+{_CANCELLED}))",
    ),
    (
        Detail.GRAB_AND_GO,
        r"grab[- ](?:and|&|n)[- ]go\s+(?:meals?|breakfast(?:\s+and\s+lunch)?|lunch(?:es)?)"
        r"(?:\s+(?:will\s+be\s+|are\s+|is\s+)?(?:available|provided|served|offered))?",
    ),
    (
        Detail.NO_AM_PREK,
        rf"(?:no\s+(?:am|morning)\s+{_PREK}|(?:am|morning)\s+{_PREK}{_ARE}\s+(?:{_CANCELLED}|closed))",
    ),
    (
        Detail.NO_PM_PREK,
        rf"(?:no\s+(?:pm|afternoon)\s+{_PREK}|(?:pm|afternoon)\s+{_PREK}{_ARE}\s+(?:{_CANCELLED}|closed))",
    ),
    (
        Detail.NO_PREK,
        rf"(?:no\s+(?:am\s+and\s+pm\s+|am/pm\s+)?{_PREK}{_SERVED}|(?:all\s+)?{_PREK}{_ARE}\s+(?:{_CANCELLED}|closed)|"
        rf"no\s+(?:half[- ]day\s+)?kindergarten\s+or\s+{_PREK})",
    ),
    (
        Detail.ACTIVITIES_CANCELLED,
        rf"(?:{_ACTIVITIES}{_ARE}\s+{_CANCELLED}|no\s+(?:school\s+)?(?:activities|"
        r"extra[- ]?curricular\s+activities))",
    ),
    (
        Detail.AFTER_SCHOOL_CANCELLED,
        rf"(?:{_AFTER}{_ARE}\s+{_CANCELLED}|no\s+(?:after[- ]?school|pm|afternoon)\s+"
        r"(?:activities|sports|athletics)(?:\s*/\s*no\s+after[- ]?school\s+sports)?|"
        r"no\s+before\s+(?:or|and)\s+after[- ]school\s+activities)",
    ),
    (
        Detail.EVENING_CANCELLED,
        rf"(?:{_EVENING}{_ARE}\s+{_CANCELLED}|no\s+(?:evening|night)\s+(?:activities|events))",
    ),
    (
        Detail.CHILDCARE_CLOSED,
        rf"(?:no\s+{_CARE}{_SERVED}|{_CARE}{_ARE}\s+(?:closed|{_CANCELLED}))",
    ),
    (
        Detail.CHILDCARE_OPEN,
        rf"{_CARE}{_ARE}\s+open(?:\s+(?:as\s+(?:normal|usual|scheduled)|regular\s+hours))?",
    ),
    (
        Detail.OFFICES_CLOSED,
        rf"(?:(?:all\s+)?(?:schools?|campuses)\s+(?:and|&)\s+)?{_OFFICES}{_ARE}\s+closed",
    ),
    (
        Detail.OFFICES_OPEN,
        rf"{_OFFICES}{_ARE}\s+open(?:\s+(?:as\s+(?:normal|usual|scheduled)|regular\s+hours))?",
    ),
)

_LEAD: Final = r"(?:(?:and|also|plus|but)\s+)?(?:there\s+(?:will\s+be|is)\s+)?"
_COMPILED: Final[tuple[tuple[Detail, re.Pattern[str]], ...]] = tuple(
    (detail, re.compile(rf"{_LEAD}(?:{pattern}){_DAY}", re.IGNORECASE))
    for detail, pattern in _PATTERNS
)

# --- the clauses a detail may stand beside -------------------------------------------------

_WD = r"(?:mon|tues?|wed(?:nes)?|thu(?:rs?)?|fri|sat(?:ur)?|sun)(?:day)?\.?"
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_ON_DATE = (
    rf"(?:{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+(?:19|20)\d\d)?|"
    r"\d{1,2}/\d{1,2}(?:/(?:\d\d){1,2})?)"
)
_ONE_DAY = rf"(?:today|tomorrow|tonight|{_WD}(?:,?\s+(?:the\s+)?{_ON_DATE})?|{_ON_DATE})"
_AT = r"(?:at|@)\s*(?:\d{1,2}(?::\d{2})?\s*(?:am|pm)?|noon)"
_WEATHER = (
    r"(?:the|inclement|winter|severe|extreme|bad|hazardous|icy|ice|snow|snowfall|weather|"
    r"road|roads|conditions|cold|freezing|rain|wind|chill|temperatures|storm|anticipated|"
    r"forecast(?:ed)?|and|&)"
)
_HOURS = r"(?:\d|one|two|three|four)(?:\.5)?\s*(?:-\s*)?(?:hours?|hrs?\.?)"
_STATUS = (
    r"(?:closed|closing|closure|close|cancel+ed|canceled|no\s+(?:school|classes)|"
    rf"(?:school|classes)\s+(?:cancel+ed|canceled)|delayed(?:\s+(?:start|opening))?(?:\s+{_HOURS})?|"
    rf"(?:a\s+)?{_HOURS}\s+(?:delay(?:ed)?(?:\s+(?:start|opening))?|late(?:\s+start)?)|delay|"
    r"late\s+(?:start|opening|arrival)|"
    r"(?:remote|virtual|distance|online|e-?|at[- ]home|flexible|non[- ]traditional)\s*"
    r"(?:learning|instruction)(?:\s+day)?|nti\s+day|amu\s+day|"
    r"early\s+(?:dismissal|release)|dismiss(?:ing|ed|al)?\s+early|releas(?:e|ing|ed)\s+early|"
    rf"closing\s+early|(?:dismissal|dismissing)\s+{_AT}|"
    rf"(?:school|classes)\s+(?:will\s+)?(?:starts?|begins?)\s+{_AT})"
)
_TAIL = rf"(?:\s+(?:(?:on|for)\s+)?{_ONE_DAY}|\s+{_AT}|\s+due\s+to(?:\s+{_WEATHER})+)"
_PLAIN: Final = re.compile(
    r"(?:(?:all\s+)?(?:(?:the\s+)?(?:schools?|classes|district|school\s+district|campuses|"
    r"buildings|school\s+buildings)\s+)?(?:(?:is|are|will\s+be|will|to\s+be)\s+)?"
    rf"{_STATUS}{_TAIL}{{0,3}}|(?:(?:for|on|effective)\s+)?{_ONE_DAY}|(?:19|20)\d\d)",
    re.IGNORECASE,
)
"""The other clauses a detail may stand beside: a status in a closed set of plain shapes, with
at most a day, a clock time and a weather reason (a delay of some hours, schools closed on a
weekday, an early dismissal at a clock time), a day alone, or a year. Any other clause may
limit, hedge, negate or contradict a detail (a word such as TBD or optional, a part of the
staff, a school's or an area's name, a second sentence about the staff), so a row with one
states none."""

# --- clauses and days ----------------------------------------------------------------------

_FOLD: Final = (
    (re.compile(r"\ba\.\s?m\.?(?=\W|$)", re.IGNORECASE), "am"),
    (re.compile(r"\bp\.\s?m\.?(?=\W|$)", re.IGNORECASE), "pm"),
    (re.compile(r"\b(am)\s*/\s*(pm)\b", re.IGNORECASE), r"\1 and \2"),
    (re.compile(r"\bbefore\s*/\s*after\b", re.IGNORECASE), "before and after"),
    (re.compile("[\u2010-\u2015\u2212]"), "-"),
    (re.compile("[\u2018\u2019]"), "'"),
    (re.compile(r"\b(closed|delayed|cancel+ed)-(?=[a-z])", re.IGNORECASE), r"\1 - "),
)
_SPLIT: Final = re.compile(
    r"(\.(?=\s|$)|[;|!?\n,()\[\]]|(?<!\d):|:(?!\d)|(?<!\d)/|/(?!\d)|\s-\s)",
    re.IGNORECASE,
)
_SPACE: Final = re.compile(r"\s+")
_LIST: Final = frozenset({".", ",", ";", "|", "!", "\n"})
"""Marks that list one clause after another: a detail may stand on either side of them."""
_LEADS: Final = _LIST | {":", "-"}
"""Marks a detail may follow: a status, then a colon or a spaced dash, then the detail."""
_BETWEEN: Final = _LIST | {"-", "/"}
"""Marks a detail may be followed by when another detail comes next (two meals with a slash
between them)."""
_WEEKDAY: Final = re.compile(
    r"\b(?:(mon|tues?|wed(?:nes)?|thu(?:rs?)?|fri|sat(?:ur)?|sun)(?:day)?|today|tonight|tomorrow)\b",
    re.IGNORECASE,
)
_DATE: Final = re.compile(
    r"\b(?:\d{1,2}/\d{1,2}(?:/\d{2,4})?|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)"
    r"[a-z]*\.?\s+\d{1,2})\b",
    re.IGNORECASE,
)


_PAIRED: Final = re.compile(
    rf"{_WEEKDAY.pattern}\.?,?\s+(?:the\s+)?({_DATE.pattern})", re.IGNORECASE
)
"""A weekday written with its date: one day."""
_DAY_PARTS: Final = re.compile(r"\b(?:morning|afternoon|evening|night|tonight)\s*:", re.IGNORECASE)
"""A label that scopes what follows it to part of a day (an evening's label before a detail)."""


def _folded(text: str) -> str:
    for pattern, replacement in _FOLD:
        text = pattern.sub(replacement, text)
    return text


def _trimmed(part: str) -> str:
    return _SPACE.sub(" ", part).strip(" -*'\".")


def _marks(text: str) -> list[tuple[str, frozenset[str]]]:
    """A text's clauses (folded, trimmed, never empty), each with the marks between it and the
    clause before it (a spaced dash as ``-``; the first clause's marks are the empty set),
    then a last entry ``("", marks)`` with the marks after the last clause."""
    parts = _SPLIT.split(_folded(text))
    found: list[tuple[str, frozenset[str]]] = []
    marks: set[str] = set()
    for index, part in enumerate(parts):
        if index % 2:
            marks.add(part.strip(" \t") or part)
        elif clause := _trimmed(part):
            found.append((clause, frozenset(marks)))
            marks = set()
    found.append(("", frozenset(marks)))
    return found


def clauses(text: str) -> list[str]:
    """The clauses of a text (folded: "a.m." as "am", "AM/PM" as "am and pm"), trimmed."""
    return [clause for clause, _ in _marks(text)[:-1]]


def _day_key(found: re.Match[str]) -> str:
    word = found.group(0).casefold()
    stem = found.group(1)
    return word if stem is None else stem.casefold()[:3]


def names_days(text: str) -> int:
    """How many different days a text names: weekdays, "today", "tonight" and "tomorrow" ("Mon"
    and "Monday" are one), and calendar dates. A weekday written with its date ("Tuesday,
    February 5th", "Thu. Dec 1st") is one day; "today" and "tonight" are one; any other
    weekday and date are two, as a weekday cannot be told to be that date."""
    paired = {_SPACE.sub(" ", found.group(2).casefold()) for found in _PAIRED.finditer(text)}
    rest = _PAIRED.sub(" ", text)
    weekdays = {_day_key(found) for found in _WEEKDAY.finditer(rest)}
    if {"today", "tonight"} <= weekdays:
        weekdays.discard("tonight")
    dates = {_SPACE.sub(" ", found.group(0).casefold()) for found in _DATE.finditer(rest)}
    return len(paired | dates) + len(weekdays)


def _clause_detail(clause: str) -> Detail | None:
    for detail, pattern in _COMPILED:
        if pattern.fullmatch(clause):
            return detail
    return None


@lru_cache(maxsize=4096)
def read_details(text: str) -> tuple[Detail, ...]:
    """The details a text states, from its words alone (sorted, at most one of an exclusive
    group); none when any of its words might limit, hedge, negate or contradict one: a
    question mark, two days, a part-of-day label, a clause that is neither a detail nor a plain
    status or day (:data:`_PLAIN`), a detail set off by a parenthesis or bracket, followed by a
    colon, or joined to a clause that is not a detail by a slash or a dash after it, or other
    words that name part of a district or a school."""
    if "?" in text or names_days(text) > 1 or _DAY_PARTS.search(text):
        return ()
    marked = _marks(text)
    read = [_clause_detail(clause) for clause, _ in marked[:-1]]
    found: set[Detail] = set()
    rest: list[str] = []
    for index, (clause, before) in enumerate(marked[:-1]):
        detail = read[index]
        if detail is None:
            if _PLAIN.fullmatch(clause) is None:
                return ()
            rest.append(clause)
            continue
        after = marked[index + 1][1]
        follows = index > 0 and read[index - 1] is not None
        leads = index + 1 < len(read) and read[index + 1] is not None
        if not before <= (_LEADS | {"/"} if follows else _LEADS):
            return ()
        if not after <= (_BETWEEN if leads else _LIST):
            return ()
        found.add(detail)
    if not found or names_part(". ".join(rest)):
        return ()
    return _settled(found)


def _settled(found: set[Detail]) -> tuple[Detail, ...]:
    """One row's details with its own contradictions settled: an exclusive group stating two
    details is dropped; morning and afternoon pre-K are no pre-K; a broader activities detail
    covers the narrower ones."""
    if {Detail.NO_AM_PREK, Detail.NO_PM_PREK} <= found:
        found -= {Detail.NO_AM_PREK, Detail.NO_PM_PREK}
        found.add(Detail.NO_PREK)
    if Detail.NO_PREK in found and found & {Detail.NO_AM_PREK, Detail.NO_PM_PREK}:
        found -= {Detail.NO_PREK, Detail.NO_AM_PREK, Detail.NO_PM_PREK}
    if {Detail.NO_LUNCH, Detail.NO_HOT_LUNCH} <= found:
        found.discard(Detail.NO_HOT_LUNCH)
    if Detail.ACTIVITIES_CANCELLED in found:
        found -= {Detail.AFTER_SCHOOL_CANCELLED, Detail.EVENING_CANCELLED}
    for group in _EXCLUSIVE:
        members = {detail for detail in found if GROUP[detail] == group}
        if len(members) > 1:
            found -= members
    return tuple(sorted(found))


def row_details(
    text: str, kinds: Iterable[str], days: int, *, posted_that_day: bool
) -> tuple[str, ...]:
    """The detail codes a row that lights ``kinds`` on ``days`` days gives (stored codes, in
    :class:`~snowlight.schemas.vocab.Detail` order): none unless it lights one kind on one day,
    and only the details that say something beside that status (:data:`FOR_STATUS`).
    ``posted_that_day``: the row was first seen on the day it lights, in every zone of its
    schools. Evening activities cancelled, posted the evening before beside the next day's
    closing, may be about that evening, so it counts only then (:data:`SAME_DAY`)."""
    lit = set(kinds)
    if days != 1 or len(lit) != 1:
        return ()
    (kind,) = lit
    return tuple(
        detail.name.lower()
        for detail in read_details(text)
        if kind in FOR_STATUS[detail] and (posted_that_day or detail not in SAME_DAY)
    )


def agreed(rows: Iterable[Iterable[str]]) -> tuple[Detail, ...]:
    """A school-day's details from its winning rows' codes: for each group, what the rows that
    state something of it state, when they all state the same; a group they disagree on is
    dropped, and a row that states nothing of a group is left out of it."""
    said: dict[Group, set[frozenset[Detail]]] = {}
    for codes in rows:
        details = {DETAIL_BY_CODE[code] for code in codes if code in DETAIL_BY_CODE}
        for group in {GROUP[detail] for detail in details}:
            said.setdefault(group, set()).add(
                frozenset(detail for detail in details if GROUP[detail] == group)
            )
    kept = [next(iter(choices)) for choices in said.values() if len(choices) == 1]
    return tuple(sorted(detail for chosen in kept for detail in chosen))
