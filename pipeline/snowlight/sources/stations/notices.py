"""District alert channels and status boards: the rows that announce a closing, and the proof gate.

A TV station's closings list proves itself with any row: the list exists only for
closings. Two kinds of this part's sources do not:

* A school district's alert channel (:data:`GENERAL_CHANNEL_ADAPTERS`): its homepage
  banner (Apptegy), page pops (Finalsite), pop-up alerts (Smart Sites), homepage
  alert (Edlio), organization alerts (SchoolBlocks), Pasco's emergency banner,
  Miami-Dade's alerts file, Northside ISD's homepage notices and SharpSchool's
  emergency alerts (and its homepages' hero sliders) carry whatever the district
  posts, and most days that
  is a superintendent's appointment, a hiring call or a referendum. Such a
  channel is proven only by a row that announced a closing, a delay, an early
  dismissal, a remote day, cancelled classes or no school: Martin County's "HURRICANE
  MILTON UPDATE: All MCSD-operated schools and offices will be closed ...", not Lake
  County's "School Board names Chad Farnsworth next Superintendent". A notice that only
  concerns the weather ("Cold Weather Update", "Learn more about the storm, including
  shelter information") or keeps the day ("Schools are OPEN and IN SESSION", "school at
  regular time tomorrow", "Schools to Remain Open if Buses Can Run") is not a closing and
  proves nothing (since 2026-10-13: the owner's rule that a source is proven only when its
  list was seen holding closings), nor is a pandemic's closure ("COVID-19 School Closure
  Update").
* A status board (:data:`STATUS_BOARD_ADAPTERS`): a county's or a state's table
  naming every school or school system with its status (Flathead County's
  closures page, the Shasta and Trinity county offices' sheets, GOHSEP's parish
  layer). It holds rows every day, most of them "Open", so a row proves nothing
  until one of them has a status other than open: "Closed", "Early Dismissal",
  "Remote", "Closing at 12:45".

:func:`announces_closing` is the channel rule (deterministic, word patterns only,
in English and, for South Texas' and Miami's districts, Spanish;
it does not read dates or decide what kind of closure a row is, which the status
reader does). A planned calendar day with no closure word ("Staff Development Day
... There is NO school for students") and a reopening with no weather word
("schools will be OPEN Friday") do not qualify. :func:`board_status_announces` is
the board rule: a status that announces a closing, or names a remote day, a delay,
a late start or a shortened day. :func:`gate_proofs` applies them to the proofs of
the gated stations (by their platform's adapter): a proof (a populated read, live,
archived or a committed fixture) is kept only when one of its rows qualifies. The
rows come from the ``rows.jsonl`` written beside each ``reads.jsonl`` (matched by
source and read time) and, for a fixture, from reading the fixture with its
adapter. The report it returns goes into ``coverage.json`` (internal) as
``district_notice_gate``::

    {source_id: {"kind": "channel" | "board",
                 "kept": n, "kept_proofs": [{"mode", "captured_at", "url", "basis", "row"}, ...],
                 "dropped_count": n,
                 "dropped": [{"mode", "captured_at", "url", "basis", "reason", "row"}, ...],
                 "corroborated": [{..., "warning": {"day", "weight", "county"}}, ...]}}

(``corroborated``, present only when there are any, lists every proof kept as a dated
closing on a warning day, :func:`dated_closing`; :func:`annotate_warnings` copies the
warning into the station's ``proof`` when that proof is one of them.)

(``row`` is the first qualifying row of a kept proof, the first row of a dropped
one, as ``name | status``.) :func:`annotate_unproven` adds each gated station's
dropped count to its entry in the ``unproven`` list, so that list says why a
populated read did not prove it.

Rows that are text rather than a channel's own notices prove less. A *page-text*
row (``raw_extra["section"] == "page-text"``: a closing line or a weather status line of
a district homepage's own text, read beside its alert channel by
:mod:`snowlight.sources.stations.homepage`) qualifies only when it announces a
closing, a delay, a remote day or cancelled classes for weather or an emergency, and
is not a teaser or an explainer (:func:`page_text_closing`); a line that states the
schools' weather status for a named day without a closing (:func:`page_text_status`:
"School will be in session ... today, Wednesday, January 5, 2022") is read but proves
nothing: a calendar's "No School Friday, February 15th and
Monday, February 18th" (Presidents' Day) never does, nor "EXLP Snow Day at Aziz
Farms" (an event) or "Utah is a winter state ... Read More About Snow Days". A row
of a section of story cards (:data:`WEATHER_GATED_VARIANTS`: Cowles'
``/schoolclosures/`` section pages of 2019-2021) qualifies only when it announces a
closing *and* names weather or an emergency (:func:`weather_closing`): a story on a
COVID-19 closure does not. A station whose platform is not gated (a TV station's
list) has its proofs of a weather-gated variant checked the same way; its other
proofs are kept as they are.

A closing that names no reason is corroborated by the weather service instead
(:func:`dated_closing`): a channel's or a page's notice of a closing, a delay, a
remote day, cancelled classes or no school for a day it names (or two or three), posted
near that day, proves its channel when an NWS warning (not an advisory alone) covered
one of the district's counties on a day it names and no day it names is a weekend,
holiday or break (:func:`school_break`). Granite's "Distance Learning Day for Granite
School District - Wednesday, February 22, 2023" (a Winter Storm Warning over Salt Lake
County that morning) proves Granite's channel; Canyons' "Schools, District Office Closed
Feb. 21" (2022, Presidents' Day) does not, nor does a run of days ("No School, April
4-8"). The warning (day, weight, county) is listed with the proof it kept. The warning days are
the closure weights' NWS record (:mod:`snowlight.sources.stations.storms`), given to
:func:`gate_proofs` by the coverage command.

Which text is read: a channel row's status, and its name too when the name is the
notice's own title (Finalsite, Smart Sites, Edlio, Miami-Dade), not when it is the
district's name (Apptegy, Schoolwires, Campus Suite, SchoolBlocks, Pasco:
:data:`ORG_NAMED_VARIANTS`), so a district called "Storm Lake" never proves itself;
a board row's status only.
"""

import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, MutableMapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import NamedTuple, Protocol

from snowlight.output import JSONValue
from snowlight.sources.stations.adapters import adapter_for
from snowlight.sources.stations.model import ShapeError
from snowlight.sources.stations.registry import Registry
from snowlight.sources.stations.storms import WarningDay, school_day

GENERAL_CHANNEL_ADAPTERS = frozenset(
    {
        "apptegy",
        "dadeschools",
        "edlio",
        "finalsite",
        "pasco",
        "schoolblocks",
        "smartsites",
        "nisd",
        "sharpschool",
        "district-homepage",
        "apptegy-feed",
    }
)
"""Adapters of general alert channels (whose rows need not be closings)."""

STATUS_BOARD_ADAPTERS = frozenset({"coesheet", "flathead", "gohsep"})
"""Adapters of status boards (every school or system listed, most of them open)."""

ORG_NAMED_VARIANTS = frozenset(
    {
        "apptegy-nuxt-state",
        "apptegy-nuxt2-state",
        "schoolwires-important-announcements",
        "pasco-emergency-banner",
        "pasco-red-rectangle",
        "schoolblocks-org-alerts",
        "campussuite-alert-banner",
        "wcm-announcements",
        "googlesites-banner",
        "nisd-notices",
        "apptegy-live-feed",
    }
)
"""Variants whose rows are named by the district itself, not by the notice."""

WEATHER_GATED_VARIANTS = frozenset({"cowles-section-cards"})
"""Variants whose rows are story cards: they prove only a weather or emergency closing."""

CHANNEL_HISTORY_VARIANTS = frozenset({"apptegy-live-feed"})
"""Feeds of a district's every post (a field trip cancelled for weather, a gym closed for a
holiday): a post proves the feed only as a weather or emergency closing
(:func:`weather_closing`), live, archived or in the feed's dated history."""

PAGE_TEXT = "page-text"
"""``raw_extra["section"]`` of a homepage's text read as a row (see the module docstring)."""

MAX_LISTED = 20
"""At most this many kept and dropped proofs are listed per station (the counts are complete)."""

_I = re.IGNORECASE
_SUBJECT = (
    r"(?:schools?|offices?|campus(?:es)?|buildings?|facilities|district|classes|"
    r"school\s+day|in-person\s+(?:classes|instruction|learning)|\w{0,6}(?:isd|usd))"
)
"""What closes. A district named by its initials counts ("Victoria ISD Will Remain Closed
Through Tuesday Due To Inclement Weather", its homepage's news of 2021-02-16; "Edinburg
CISD", "PSUSD")."""
_STATUS = [
    # "All schools and offices will be closed", "Schools/offices will remain closed",
    # "School Closure", "Schools To Be Closed September 27"
    re.compile(rf"\b{_SUBJECT}\b[^.!?]{{0,60}}?\bclos(?:e|ed|es|ing|ure|ures)\b", _I),
    # the closing named first, then what closes (the closure of all district schools)
    re.compile(rf"\bclos(?:ed|ing|ures?)\b[^.!?]{{0,40}}?\b{_SUBJECT}\b", _I),
    # a notice whose title or status is the closing itself: "CLOSED TODAY", "Closed Monday"
    re.compile(
        r"^\W*(?:closed|closing|closure)\b"
        r"|\bclosed\s+(?:(?:through|thru|until)\s+)?(?:today|tomorrow|on\s+\w+day|\w+day)\b",
        _I,
    ),
    re.compile(r"\b(?:\d+|one|two|three)[- ]?(?:hours?|hrs?)\.?[- ](?:delay|late\s+start)", _I),
    # "all buses will run two hours late"
    re.compile(
        r"\b(?:run|running|arrive|arriving)\s+(?:an?|one|two|three|\d+)\s+hours?\s+late\b", _I
    ),
    re.compile(r"\bdelay(?:ed|s)?\s+(?:start|opening|arrival|schedule)\b", _I),
    re.compile(r"\blate\s+(?:start|arrival|opening)\b", _I),
    # "SCSD #9 schools will start school an hour late today"
    re.compile(r"\bstart\s+(?:school\s+|classes\s+)?(?:an?|one|two|\d+)\s+hours?\s+late\b", _I),
    re.compile(r"\bearly\s+(?:dismissal|release|out)\b", _I),
    re.compile(r"\b(?:dismiss(?:ed|al|ing)?|released?)\s+early\b", _I),
    re.compile(
        r"\b(?:remote|virtual|online|e-?learning|distance)[- ](?:learning|instruction)\s+days?\b",
        _I,
    ),
    re.compile(r"\be-?learning\s+days?\b", _I),
    re.compile(
        r"\b(?:shift|move|switch|transition)\w*\s+to\s+(?:an?\s+)?"
        r"(?:remote|virtual|online|e-?learning|distance)\b",
        _I,
    ),
    re.compile(
        r"\b(?:school|classes)\s+(?:is\s+|are\s+|has\s+been\s+|have\s+been\s+|will\s+be\s+)?"
        r"cancel(?:l)?ed\b",
        _I,
    ),
    re.compile(r"\bcancel(?:l)?(?:ed|ing|s)?\s+(?:all\s+)?(?:school|classes)\b", _I),
    # a named storm's closing, the headline saying what closes for it: "Hurricane Debby
    # Closure" (Madison County Schools' district news of 2024-08-04)
    re.compile(
        r"\b(?:hurricane|tropical\s+(?:storm|depression))\s+[a-z]+\s*:?\s+"
        r"(?:updates?\s*:?\s+)?clos(?:ings?|ures?)\b",
        _I,
    ),
]
"""A closing, a delay, an early dismissal, a remote day or cancelled classes."""

_NOT_A_CLOSING = re.compile(
    r"\b(?:enrollment|registration|applications?|window|portal|survey|nominations?|voting|"
    r"polls?|bids?|sign[- ]?ups?|deadline|orders?|sales?|tickets?|auditions?|tryouts?|"
    r"comment\s+period)\b[^.!?]{0,40}?\bclos(?:e|es|ed|ing)\b"
    r"|\bclosed[- ](?:sessions?|caption\w*|campus(?:\s+(?:lunch|policy))?)\b"
    r"|\bclos(?:e|es|ed|ing)\s+(?:the\s+)?(?:achievement\s+|opportunity\s+|learning\s+)?gaps?\b"
    r"|\bclosing\s+(?:ceremon\w+|remarks|date|bell|of\s+(?:the\s+)?(?:school\s+)?year)\b"
    # A school closed for good (a building's future use, a consolidation), not for a day:
    # "the best future use of three closed schools", "closed school buildings".
    r"|\b(?:\d+|two|three|four|five|six|several|these|those|former)\s+closed\s+"
    r"(?:schools?|buildings?|campus(?:es)?|sites?)\b"
    r"|\bclosed\s+(?:school\s+)?(?:buildings?|sites?|properties|facilities)\b"
    r"|\bpermanent(?:ly)?\s+clos\w+|\bclos\w+\s+permanently\b"
    # a page about closings, not one: "Potential Hurricane Helene: Closure Information and
    # Updates" (Duval's homepage card of 2024-09-26)
    r"|\bclos(?:ure|ing)s?\s+(?:information|info|details|procedures?|guidelines?)\b",
    _I,
)
"""A deadline's "closes" ("enrollment closes Friday"), a closed session, a closed
campus, closing a gap or a ceremony, a school closed for good (a closed school's
future use, a closed building), or a page of closure information: not a school closing."""

_PART_CLOSED = re.compile(
    r"\b(?:librar(?:y|ies)|classrooms?|entrances?|doors?|gym(?:nasium)?s?|weight\s+rooms?"
    r"|pools?|parking\s+lots?|playgrounds?|cafeterias?|kitchens?|hallways?|restrooms?"
    r"|bathrooms?|locker\s+rooms?|auditoriums?)\b"
    r"(?:(?!\b(?:schools?|class(?:es)?|campus(?:es)?|district)\b)[^.!?]){0,60}?"
    r"\bclos(?:e|es|ed|ing|ures?)\b",
    _I,
)
"""A part of a building closed ("the northwest and southwest entrances to the facility will
be closed. The library and one classroom will be closed tomorrow"), the span to "closed"
naming no school, class, campus or district. Struck out only from a notice that says its
school keeps its day (:func:`_strike_kept_day`): Shelby (MT)'s press release of May 2024,
its students "scheduled for classes as normal". A TV list's row "Erie County Public
Library | Closed Wednesday" is a closing of the list's own."""


def _strike_kept_day(text: str) -> str:
    """``text`` with what is not a closing struck out: a deadline's or a ceremony's
    "closes" (:data:`_NOT_A_CLOSING`), a day said to be ordinary (:data:`_NEGATED`,
    :data:`_KEPT_DAY`) and, when the notice says its school keeps its day, a part of the
    building closed (:data:`_PART_CLOSED`)."""
    cleaned = _NOT_A_CLOSING.sub(" ", text)
    if _KEPT_DAY.search(cleaned) or _NEGATED.search(cleaned):
        cleaned = _PART_CLOSED.sub(" ", cleaned)
    return _KEPT_DAY.sub(" ", _NEGATED.sub(" ", cleaned))


_PLANNED = re.compile(
    r"\b(?:staff|professional|teacher|employee)\s+(?:development|work\s*days?|planning|in-?service)"
    r"|\bin-?service\b|\bPLCs?\b|\bconferences?\b|\bholidays?\b"
    r"|\b(?:winter|spring|fall|thanksgiving|christmas|mid-?winter|semester|harvest)\s+break\b"
    r"|\b(?:winter|spring|fall|thanksgiving|christmas|holiday|mid-?winter)\s+recess\b"
    r"|\b(?:thanksgiving|labor\s+day|memorial\s+day|veterans\s+day|presidents'?\s+day"
    r"|martin\s+luther\s+king|MLK|juneteenth|columbus\s+day|indigenous\s+peoples'?\s+day"
    r"|independence\s+day|new\s+year'?s|good\s+friday|graduation|election\s+day)\b"
    r"|\bevery\s+(?:monday|tuesday|wednesday|thursday|friday)\b|\bweekly\b"
    r"|\bearly\s+release\s+days?\b|\bminimum\s+days?\b|\bmake-?up\s+days?\b"
    # a testing day ("SAT Day is March 13 ... NO school for freshmen, sophomores and seniors",
    # Idaho Falls' homepage of 2024-02-26), a staff day ("this day is dedicated to planning and
    # preparation for our teachers and staff", Sharyland's of 2026-09-29), a student holiday
    # ("Student Holiday/Teacher Duty Day", Volusia's of 2024-10-14)
    r"|\b(?:P?SAT|ACT|testing|test|exam|assessment|state\s+testing)\s+days?\b"
    r"|\b(?:take|taking|administer\w*)\s+(?:the\s+)?(?:P?SAT|ACT)\b"
    r"|\bstudent\s+(?:holidays?|free\s+days?)\b|\bnon-?student\s+days?\b"
    r"|\b(?:teacher|staff|employee|faculty)\s+(?:duty|work|planning|prep(?:aration)?|records?"
    r"|grading|collaboration|learning)\s*days?\b|\bwork\s*days?\b|\bduty\s+days?\b"
    r"|\bplanning\s+(?:and|&)\s+preparation\b"
    r"|\b(?:planning|preparation)\s+for\s+(?:our\s+)?(?:teachers|staff)\b"
    r"|\bprofessional\s+learning\b|\bparent[- ]teacher\b|\bgrading\s+days?\b",
    _I,
)
"""A planned day (a holiday, a break, staff development, a testing day, a student holiday,
a teachers' planning or duty day, a calendar's early release or minimum day): not a weather
or emergency notice."""

_WEATHER = re.compile(
    r"\bhurricane\b|\btropical\s+(?:storm|depression|system)|\bnamed\s+storm"
    r"|\b(?:the|this|a|winter|ice|snow|tropical|severe|approaching|upcoming|major)\s+storms?\b"
    r"|\bstorm\s+(?:updates?|warnings?|watch(?:es)?|damage|preparations?|days?|conditions?)\b"
    r"|\bsnow(?:fall|storm|y)?\b(?!\s+(?:white|cones?|ball|queen|globes?|sculptures?))"
    r"|\bblizzard|\bice\s+storm|\bicy\b|\bsleet\b|\bfreezing\s+(?:rain|drizzle|temperatures)"
    r"|\bhard\s+freeze|\bfreeze\s+(?:warning|watch)|\b(?:extreme|dangerous|bitter|severe)\s+cold"
    r"|\bsub-?zero\b|\bwind\s?chills?\b"
    r"|\b(?:inclement|severe|winter|wintry|bad|cold|extreme|hazardous|dangerous|current|forecast(?:ed)?)"
    r"\s+weather\b|\bweather[- ](?:conditions?|related|forecasts?|alerts?|warnings?|advisory|event|"
    r"delays?|closures?|emergency|updates?|statement)\b|\bdue\s+to\s+(?:the\s+)?weather\b"
    r"|\bflood(?:ing|ed|s|\s+warning|\s+watch)?\b(?!\s+of\b)|\btornado(?:es|s)?\b(?!\s+drills?)"
    r"|\bpower\s+outages?|\bwithout\s+power|\blost\s+power|\bno\s+power|\bwildfires?\b"
    r"|\bair\s+quality\s+(?:alert|advisory|warning|index)|\bwildfire\s+smoke|\bsmoke\s+(?:advisory|conditions)"
    r"|\bevacu(?:ation|ate|ated|ees?)\b(?!\s+drills?)|\bextreme\s+heat|\bheat\s+(?:advisory|warning)"
    r"|\bboil[- ]water\s+(?:notice|advisory|order)|\bwater\s+main\s+break"
    r"|\b(?:dangerously|extremely)\s+(?:low|cold)\b|\blow\s+(?:wind\s+)?temperatures\b|\bfrigid\b"
    r"|\bclear(?:ing)?\s+(?:the\s+)?(?:roads?|routes|streets)\b|\bsnow\s*plows?\b",
    _I,
)
"""Weather, or an emergency that closes schools (an outage, a fire, an evacuation), and
the cold or the snow by what it does ("Dangerously Low Wind Temperatures", "to allow
crews to clear routes")."""

_ROADS = re.compile(r"\b(?:road|driving|travel)\s+conditions\b", _I)
"""Road conditions, which are weather's in a line that also announces a closing or a delay
("Due to road conditions SCSD #9 schools will start school an hour late today", Sublette
County School District #9's homepage, January 2017): a reason for :func:`page_text_closing`
and :func:`weather_closing`, which need the closing too, but not a notice's subject by
itself for :func:`announces_closing` (a TV list's "ROAD CONDITIONS" link is no closing)."""

_PLANNING = re.compile(
    r"\b(?:hazard\s+mitigation|mitigation\s+plan|preparedness\s+(?:plans?|guides?|month|week|fair)"
    r"|emergency\s+(?:operations\s+)?plans?|safety\s+plans?|input\s+needed|your\s+(?:feedback|input)"
    r"|public\s+comment|surveys?)\b",
    _I,
)
"""A planning document or a call for feedback that names hazards ("Input Needed on
Beaumont USD Local Hazard Mitigation Plan ... flash flooding, high windstorms"): its
weather words are not a weather notice, so it qualifies only by a closing of its own."""

_SPANISH_WEATHER = re.compile(
    r"\bhurac[aá]n\b|\btormenta\s+(?:tropical|invernal|de\s+invierno)|\bmal\s+tiempo\b"
    r"|\bclima\s+(?:inclemente|severo|extremo)|\bcondiciones\s+(?:del\s+clima|clim[aá]ticas)"
    r"|\bheladas?\b|\bcongelaci[oó]n\b|\bnieve\b|\bnevada\b|\bfr[ií]o\s+extremo\b"
    r"|\binundaci(?:[oó]n|ones)\b|\bapag[oó]n\b|\bsin\s+electricidad\b",
    _I,
)
"""Weather or an emergency in Spanish, as South Texas' and Miami's districts post it
("debido al mal tiempo", "huracán", "tormenta invernal")."""

_SPANISH_STATUS = re.compile(
    r"\b(?:escuelas?|campus|clases|oficinas|distrito)\b[^.!?]{0,60}?\b(?:cerrad[oa]s?|cancelad[oa]s|suspendid[oa]s)\b"
    r"|\b(?:cierre|cancelaci[oó]n|suspensi[oó]n)\s+de\s+(?:las\s+)?(?:escuelas|clases|campus)\b"
    r"|\bsuspende[n]?\s+(?:las\s+)?clases\b|\bsalida\s+temprana\b"
    r"|\b(?:inicio|horario|entrada)\s+(?:tard[ií]o|retrasad[oa]|demorad[oa])\b",
    _I,
)
"""A closing, cancelled or suspended classes, an early dismissal or a delay, in Spanish
("las escuelas estarán cerradas", "clases canceladas", "salida temprana")."""

_SPANISH_PLANNED = re.compile(
    r"\bvacaciones\b|\bd[ií]as?\s+(?:festivos?|feriados?)\b|\bacci[oó]n\s+de\s+gracias\b"
    r"|\bdesarrollo\s+(?:profesional|del\s+personal)\b|\bd[ií]a\s+de\s+(?:trabajo|servicio)\b",
    _I,
)
"""A planned day in Spanish (a holiday, a break, staff development)."""

_BOARD_STATUS = re.compile(
    r"\b(?:clos(?:e|ed|es|ing|ure|ures)|remote|virtual|online|e-?learning|distance\s+learning"
    r"|delay(?:ed|s)?|late\s+(?:start|arrival)|early\s+(?:dismissal|release|out)|minimum\s+day"
    r"|shortened\s+day|modified\s+schedule|cancel(?:l)?ed)\b",
    _I,
)
"""A status board's statuses other than open ("Closed", "Planned Closure", "Remote",
"2 Hour Delay", "Closing at 12:45")."""


_SERVICE = re.compile(
    r"\bnotif(?:y|ying|ies|ications?)\b[^.!?]{0,80}?\babout\b|\bsign\s+up\b|\bsubscribe\b"
    r"|\bprocedures?\b|\bguidelines?\b|\bpolic(?:y|ies)\b|\bfaqs?\b|\bfrequently\s+asked\b"
    r"|\bhow\s+(?:we|the\s+district|schools?)\s+(?:decides?|makes?|determines?)\b",
    _I,
)
"""A standing description of how closings are announced or decided, not a notice:
Missoula's announcements app's "Notifying students and staff about severe
weather-related school closures or delays", "Inclement Weather Procedures". With no
day or date it never qualifies (a dated notice that names its procedure does)."""


_PANDEMIC = re.compile(r"\b(?:covid(?:-?19)?|coronavirus|pandemic)\b", _I)
"""A pandemic's closing ("COVID-19 School Closure Update", 2020): a closure of months, which
proves nothing of a channel's notices of a day's closing."""

_HEALTH_ORDER = re.compile(
    r"\bhealth\s+officer\b|\b(?:public\s+)?health\s+orders?\b|\border\s+of\s+the\s+health\b"
    r"|\bdepartment\s+of\s+public\s+health\b|\bstay[- ]at[- ]home\b|\bshelter[- ]in[- ]place\b"
    r"|\bsocial(?:ly)?\s+distanc\w+|\bnovel\s+virus\b|\bhealth\s+concerns?\b",
    _I,
)
"""A health order's closing, which a pandemic's shutdown cites without naming the virus
(and a list's "Health Concerns", Gray's reason for its rows of the 2020 and 2022 waves)
("Alvord School District Takes Action on School Closures ... ORDER OF THE HEALTH OFFICER OF
THE COUNTY OF RIVERSIDE", Alvord's homepage of 2020-03-18). With a weather or emergency word
(a health officer's order for wildfire smoke) it is that emergency's, not a pandemic's."""

_SHUTDOWN = re.compile(
    r"\b(?:remote(?:ly)?|distance|online|on-?line|virtual|home)\s+(?:learning|instruction)\b"
    r"|\blearn(?:ing)?\s+(?:remotely|from\s+home|at\s+home|online)\b"
    r"|\bduring\s+(?:the\s+)?(?:school\s+)?closures?\b|\bschool\s+closure\s+period\b"
    r"|\b(?:meal|lunch|breakfast)\w*\s+(?:&\s+\w+\s+)?pick[- ]?ups?\b|\bgrab[- ]and[- ]go\b",
    _I,
)
"""What the 2020 shutdown's notices say in place of the virus: learning remotely or from home,
"during school closure", meal pick-ups."""

SHUTDOWN_FROM = date(2020, 3, 1)
SHUTDOWN_TO = date(2021, 6, 30)
"""The pandemic's school shutdowns: from March 2020 through the 2020-21 school year."""


def pandemic(text: str, when: datetime | None = None) -> bool:
    """Whether a notice is a pandemic's closing, which proves nothing of a channel.

    It names the virus or the pandemic (:data:`_PANDEMIC`); or, naming no weather or
    emergency, it cites a health order (:data:`_HEALTH_ORDER`); or, read in the shutdown
    (:data:`SHUTDOWN_FROM` to :data:`SHUTDOWN_TO`, when ``when`` is given) and naming no
    weather or emergency, it speaks of learning remotely, of "school closure" as a period or
    of meal pick-ups (:data:`_SHUTDOWN`): Alvord's "help students learn remotely ... during
    school closure" (2020-03-18) names no virus.
    """
    if _PANDEMIC.search(text):
        return True
    if _WEATHER.search(text) or _SPANISH_WEATHER.search(text):
        return False
    if _HEALTH_ORDER.search(text):
        return True
    return (
        when is not None
        and SHUTDOWN_FROM <= when.astimezone(UTC).date() <= SHUTDOWN_TO
        and _SHUTDOWN.search(text) is not None
    )


_KEPT_DAY = re.compile(
    r"\b(?:no|not|never|won't|will\s+not|aren't|isn't|are\s+not|is\s+not)\s+"
    r"(?:be\s+|been\s+|have\s+|any\s+)*"
    r"(?:clos(?:ed|ing|ures?)|delay(?:ed|s)?|cancel(?:l)?(?:ed|ations?)|early\s+(?:dismissal|release))\b"
    r"|\bremain\s+open\b|\b(?:as\s+(?:normal|usual|scheduled)|at\s+(?:the\s+)?regular\s+time)\b"
    # "No school closures or delays today", "no school delay or closure"
    r"|\bno\s+(?:school|class(?:es)?)\s+(?:clos(?:ures?|ings?)|delays?|cancel(?:l)?ations?)"
    r"(?:\s+(?:or|and|/)\s+(?:clos(?:ures?|ings?)|delays?|cancel(?:l)?ations?))?\b"
    # "We are not cancelling school today"
    r"|\b(?:not|won't|isn't|aren't)\s+(?:be\s+)?(?:cancel(?:l)?(?:ing|ed)|clos(?:ing|ed)|delay(?:ing|ed))"
    r"\s+(?:school|classes)\b",
    _I,
)
"""A notice that says the day goes on: "Schools will not be closed", "no closures or delays",
"No school closures or delays today", "We are not cancelling school today", "Schools to
Remain Open", "classes as normal", "school at regular time"."""


_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_THAT_DAY = re.compile(r"\b(?:on\s+)?(?:this|that|the\s+same)\s+day\b", _I)


def strike_planned(text: str) -> str:
    """``text`` without its sentences that name a planned day (:data:`_PLANNED`), and without
    a sentence right after one that refers back to it ("Monday, Oct. 14, will still be a
    Student Holiday/Teacher Duty Day. There is no school for students on this day.")."""
    kept: list[str] = []
    struck = False
    for sentence in _SENTENCE.split(text):
        planned = bool(_PLANNED.search(sentence) or _SPANISH_PLANNED.search(sentence))
        if planned or (struck and _THAT_DAY.search(sentence)):
            struck = True
            continue
        struck = False
        kept.append(sentence)
    return " ".join(kept)


def announces_closing(status: str, title: str | None = None, when: datetime | None = None) -> bool:
    """Whether a notice announces a closing, a delay, an early dismissal, a remote day,
    cancelled classes or no school.

    ``status`` is the notice's text; ``title``, when given, its own title (not the
    district's name). Only the closing itself qualifies: a notice that merely concerns
    weather ("Cold Weather Update", "Learn more about the storm, including shelter
    information", "Tropical Weather Update #5") or says the schools keep their day
    ("Schools are OPEN and IN SESSION", "ADISD will have school at regular time
    tomorrow", "Schools to Remain Open if Buses Can Run", "scheduled for classes as
    normal": :data:`_NEGATED` and :data:`_KEPT_DAY` are struck out before the closing words
    are looked for) never does, nor a pandemic's closing (:data:`_PANDEMIC`: a closure
    of months, not the channel's notice of a day). A planned day (a holiday, a break,
    staff development) that names no weather does not; a description of how closings
    are announced or decided that names no day (:data:`_SERVICE`) does not; a deadline's
    "closes", a closed session or a closed campus is not a closing.

    A notice that names weather keeps only its sentences that name no planned day
    (:func:`strike_planned`: Volusia's post-Milton letter, whose one "no school" is a
    student holiday, does not qualify). A bare "no school" (:data:`_NO_SCHOOL`: "No School
    on January 27th.", "No School Wednesday, November 22 - Friday, November 24th") is how a
    calendar writes its days off: it qualifies only with a weather or emergency word, as
    a page's text does, and otherwise only when the NWS corroborates its day
    (:func:`dated_closing`). A pandemic's closing (:func:`pandemic`, read at ``when``) never
    qualifies.
    """
    text = " ".join(part for part in (title, status) if part).replace("\u2019", "'")
    if _SERVICE.search(text) and not DAY.search(text):
        return False
    if pandemic(text, when):
        return False
    weather = _WEATHER.search(text) or _SPANISH_WEATHER.search(text)
    if not weather and (_PLANNED.search(text) or _SPANISH_PLANNED.search(text)):
        return False
    cleaned = _strike_kept_day(strike_planned(text))
    return (
        any(pattern.search(cleaned) for pattern in _STATUS)
        or _SPANISH_STATUS.search(cleaned) is not None
        or (bool(weather) and _NO_SCHOOL.search(cleaned) is not None)
    )


def weather_closing(status: str, title: str | None = None) -> bool:
    """Whether a notice announces a closing and names weather or an emergency.

    The rule for rows that are text rather than a channel's notices (page-text rows,
    story cards): a closing, a delay, a dismissal, a remote day, cancelled classes or
    no school (:data:`_STATUS`, :data:`_SPANISH_STATUS`, or "no school", "snow day")
    that is not a planned day, and a weather or emergency word that is not a planning
    document's. A road's closing for a flood names no school's ("Heavy rain floods
    roads, prompts road closures"), and a closing for a COVID-19 case names no weather.
    """
    text = " ".join(part for part in (title, status) if part)
    weather = _WEATHER.search(text) or _SPANISH_WEATHER.search(text) or _ROADS.search(text)
    if not weather or _PLANNING.search(text) or _PANDEMIC.search(text):
        return False
    if _PLANNED.search(text) or _SPANISH_PLANNED.search(text):
        return False
    cleaned = _strike_kept_day(text)
    return (
        any(pattern.search(cleaned) for pattern in _STATUS)
        or _SPANISH_STATUS.search(cleaned) is not None
        or _NO_SCHOOL.search(cleaned) is not None
    )


_NO_SCHOOL = re.compile(
    r"\bno\s+(?:school|classes|in-person\s+(?:school|classes|learning))\b"
    r"(?!\s+(?:clos(?:ures?|ings?)|delays?|cancel(?:l)?ations?))"
    r"|\b(?:will\s+not|won't)\s+have\s+(?:school|classes)\b"
    r"|\bsnow\s+days?\b|\bsin\s+clases\b",
    re.IGNORECASE,
)
"""No school or a snow day ("No School Monday", "Snow Day"), for :func:`weather_closing`."""

_NO_CLASSES = re.compile(
    r"\bno\s+(?:school|classes|in-person\s+(?:school|classes|learning))\b"
    r"(?!\s+(?:clos(?:ures?|ings?)|delays?|cancel(?:l)?ations?))|\bsin\s+clases\b"
    r"|\b(?:will\s+not|won't)\s+have\s+(?:school|classes)\b",
    re.IGNORECASE,
)
"""No school, for :func:`page_text_closing`: "snow day" is not one there (an event's name,
"EXLP Snow Day at Aziz Farms", or a calendar's label, "(SNOW DAYS)")."""

DAY = re.compile(
    r"\b(?:today|tonight|tomorrow|this\s+(?:morning|afternoon|evening))\b"
    r"|\b(?:mon|tues|wednes|thurs|fri|satur|sun)day\b"
    r"|\b(?:mon|tue|tues|wed|thu|thur|thurs|fri)\.(?=\s)"
    r"|\b(?:jan|feb|mar|apr|aug|sept?|oct|nov|dec)\.?\s+\d{1,2}(?:st|nd|rd|th)?\b"
    r"|\b(?:january|february|march|april|may|june|july|august|september|october|november|"
    r"december)\s+\d{1,2}(?:st|nd|rd|th)?\b"
    r"|\b(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])(?:/\d{2,4})?\b",
    re.IGNORECASE,
)
"""A day or a date: today, tomorrow, a weekday, "Jan. 26", "FEB. 14th", "11/9"."""

_EXPLAINER = re.compile(
    r"\b(?:procedures?|process|polic(?:y|ies)|protocols?|guidelines?|faqs?|frequently\s+asked"
    r"|information|the\s+latest\s+on|read\s+more|learn\s+more|this\s+link|click\s+here"
    r"|preparing\s+for|what\s+to\s+expect|throwback)\b",
    re.IGNORECASE,
)
"""A teaser or a page about closings ("The Latest on Hurricane Eta and School Closures",
"Preparing for Extreme Snow Days", "Please use this link to read communications related
to school closures"): with no day or date, not a closing itself."""


def page_text_closing(status: str, title: str | None = None) -> bool:
    """Whether a line of a homepage's own text proves its district's channel.

    A homepage's text is whatever the page shows: news teasers, a calendar's entries,
    a page about how closings are decided. A line proves the channel only when it
    announces a closing, a delay, a late start, a remote day, cancelled classes or no
    school (:data:`_STATUS`, :data:`_SPANISH_STATUS`, :data:`_NO_CLASSES`) and names
    weather or an emergency (:data:`_WEATHER`), is not a planned day or a planning
    document, and is not a teaser or an explainer (:data:`_EXPLAINER`) unless it names
    the day: "SDIRC Closed Monday Nov. 9 Due to Potential Storm Impacts From Tropical
    Storm Eta" and "Hurricane Ian: BPS Announces School and District Closure" do. A
    closing that names no reason never does by this rule ("Delayed Start to Class on
    Jan 26, 2026", Edinburg's homepage the morning of the January 2026 cold; "School
    Closure, Tuesday, Jan. 31"): a calendar's planned days read the same ("No School on
    Feb 15th, 2019 and Feb 18th, 2019", Presidents' Day weekend). Only an NWS warning
    over the district that day can corroborate it (:func:`dated_closing`).
    """
    text = " ".join(part for part in (title, status) if part)
    weather = _WEATHER.search(text) or _SPANISH_WEATHER.search(text) or _ROADS.search(text)
    if not weather or _PLANNING.search(text):
        return False
    if _PLANNED.search(text) or _SPANISH_PLANNED.search(text):
        return False
    cleaned = _strike_kept_day(text)
    if (_EXPLAINER.search(cleaned) or _SERVICE.search(cleaned)) and not DAY.search(cleaned):
        return False
    return (
        any(pattern.search(cleaned) for pattern in _STATUS)
        or _SPANISH_STATUS.search(cleaned) is not None
        or _NO_CLASSES.search(cleaned) is not None
    )


_OPEN_STATUS = re.compile(
    r"\b(?:schools?|classes|campus(?:es)?|district|buildings?|offices?)\b[^.!?]{0,60}?"
    r"\b(?:open|in\s+session)\b"
    r"|\b(?:regular|normal)\s+(?:schedules?|start\s+times?|bell\s+schedules?)\b"
    r"|\b(?:start|open|begin)\w*\s+on\s+time\b",
    _I,
)
"""A schools' status that is not a closing: open or in session, a regular schedule or an
on-time start ("Schools will be in session on Friday"). A game or an activity cancelled
for the weather is not the schools' status."""


_QUESTION = re.compile(r"\?|^\W*(?:why|how|what|when|should|will\s+schools?)\b", _I)
"""A question: an article's title ("Why Do Schools Try to Stay Open in Bad Weather?",
Murray's homepage of 2022-12-05), not a status."""


def page_text_status(status: str, title: str | None = None) -> bool:
    """Whether a line of a homepage's own text is the district's weather status for a day.

    A district that posts its schools' status for a storm on its homepage uses the
    homepage for its weather notices, whether the schools close or not: "School will be
    in session and follow regular schedules at all PCSD 25 schools today, Wednesday,
    January 5, 2022. Please continue to expect winter driving conditions" (Pocatello's
    homepage that morning), "Weather Update - Schools will be open Friday" (Okaloosa's,
    2019-10-17). Such a line names weather or an emergency (or road conditions), names
    the day (:data:`DAY`), and states the schools' status (open, in session, a regular
    schedule or an on-time start: :data:`_OPEN_STATUS`, or a closing); a game postponed,
    a planned day, a planning document and a policy that names no day ("schools
    will be open on all regularly scheduled school days unless ...") are not. It is the
    channel rule's weather notice (:func:`announces_closing`: Bozeman's "Cold Weather
    Update: ALL BSD7 schools are OPEN") held to a named day, as a page's text is.
    """
    text = " ".join(part for part in (title, status) if part)
    weather = _WEATHER.search(text) or _SPANISH_WEATHER.search(text) or _ROADS.search(text)
    if not weather or _PLANNING.search(text) or _QUESTION.search(text):
        return False
    if _PLANNED.search(text) or _SPANISH_PLANNED.search(text):
        return False
    cleaned = _NOT_A_CLOSING.sub(" ", text)
    if not DAY.search(cleaned):
        return False
    return _OPEN_STATUS.search(cleaned) is not None or page_text_closing(status, title)


def page_text_proves(status: str, title: str | None = None) -> bool:
    """Whether a page-text row proves its district's channel: a weather closing
    (:func:`page_text_closing`). A line that states the schools' weather status without a
    closing (:func:`page_text_status`: "School will be in session ... today") is the
    district's notice, but no closing, and so proves nothing."""
    text = " ".join(part for part in (title, status) if part)
    return _PANDEMIC.search(text) is None and page_text_closing(status, title)


def board_status_announces(status: str) -> bool:
    """Whether a status board's status is other than open: a closing, a delay, a remote day.

    The status is the board's own column for one school, so a bare word counts
    ("Closed", "Remote"); "Open", an empty status and a planned closing ("Planned
    Closure", GOHSEP's layer of June 2026) never do.
    """
    if _PLANNED_STATUS.search(status):
        return False
    return bool(_BOARD_STATUS.search(status)) or announces_closing(status)


_PLANNED_STATUS = re.compile(r"\bplanned\b|\bscheduled\b", _I)
"""A board's status for a closing the calendar planned ("Planned Closure")."""


def row_qualifies(  # noqa: PLR0913 - the row, its kind and when it was read
    name: str,
    status: str,
    variant: str,
    *,
    board: bool = False,
    section: str | None = None,
    when: datetime | None = None,
) -> bool:
    """Whether one row of a gated source announces a closing.

    A channel's row by :func:`announces_closing` (its name read as the notice's
    title unless the variant names rows by the district); a status board's row by
    :func:`board_status_announces`, its status only; a page-text row (``section``
    :data:`PAGE_TEXT`) by :func:`page_text_proves`; a row of a
    :data:`WEATHER_GATED_VARIANTS` variant (a story card) by :func:`weather_closing`, and a
    post of a district's feed (:data:`CHANNEL_HISTORY_VARIANTS`) the same way, its status
    alone. ``when`` is when the row was read (for :func:`pandemic`).
    """
    if section == PAGE_TEXT:
        return page_text_proves(status, None if name == status else name)
    if variant in CHANNEL_HISTORY_VARIANTS:
        return weather_closing(status, None)
    if variant in WEATHER_GATED_VARIANTS:
        return weather_closing(status, None if name == status else name)
    if board:
        return board_status_announces(status)
    title = None if variant in ORG_NAMED_VARIANTS else name
    return announces_closing(status, title, when)


# A dated closing on a warning day ------------------------------------------------------

DATED_BEFORE = timedelta(days=5)
"""How long before the capture's school day the day a dated closing names may lie: a notice
still up in the school week after its day (Converse #1's "No School in Converse 1-October
13, 2021", captured on the 16th)."""
DATED_MOST = 3
"""The most days one dated closing may name (Putnam's "All Putnam County schools will be
closed on Friday, September 8th, and Monday, September 11th, 2017", Hurricane Irma)."""
DATED_AFTER = timedelta(days=3)
"""How long after the capture's school day it may lie (a closing announced the evening
before, or on a Friday for the Monday)."""
DATED_WEIGHT = 0.5
"""The weakest NWS code that corroborates a dated closing: a warning (an Extreme Cold, Wind
Chill or Tropical Storm Warning, or stronger), not a Winter Weather Advisory alone, which in
the mountain states covers many a planned day off."""

_MONTH_NAMES = (
    r"(?:january|jan|february|feb|march|mar|april|apr|may|june|jun|july|jul|august|aug"
    r"|september|sept|sep|october|oct|november|nov|december|dec)"
)
_PINNED_DAY = re.compile(
    r"\b(?:(mon|tues|wednes|thurs|fri|satur|sun)day[,.]?\s+)?"
    rf"({_MONTH_NAMES})\.?\s+([0-9]{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+([0-9]{{4}})\b)?"
    r"|\b(0?[1-9]|1[0-2])/(0?[1-9]|[12][0-9]|3[01])(?:/([0-9]{4}|[0-9]{2}))?\b",
    _I,
)
"""A calendar day a notice names: "Wednesday, February 22, 2023", "Friday. Dec. 2", "Jan 26,
2026", "1/26/2026". A day named only by its weekday ("Delayed start Tuesday") pins nothing."""
_MONTH_NUMBER = {
    name: number
    for number, names in enumerate(
        (
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sept", "sep"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ),
        start=1,
    )
    for name in names
}
_CENTURY = 100
"""A year written with two digits ("1/26/26") is this century's."""
_DECEMBER = 12
_SATURDAY = 5
_HOLIDAYS_FROM = (12, 20)
_HOLIDAYS_TO = (1, 2)
"""The winter holidays: from 20 December to 2 January, inclusive."""
_WEEKDAY_NUMBER = {"mon": 0, "tues": 1, "wednes": 2, "thurs": 3, "fri": 4, "satur": 5, "sun": 6}
_SPAN = re.compile(
    rf"\b{_MONTH_NAMES}\.?\s+[0-9]{{1,2}}(?:st|nd|rd|th)?\s*(?:-|\u2013|\u2014|to|and|&)\s*"
    rf"(?:{_MONTH_NAMES}\.?\s+)?[0-9]{{1,2}}(?:st|nd|rd|th)?\b"
    r"|\b(?:mon|tues|wednes|thurs|fri)day\s*(?:-|\u2013|\u2014|to|and|&)\s*"
    r"(?:mon|tues|wednes|thurs|fri)day\b"
    r"|\b(?:through|thru|until|extended|remain(?:s)?\s+closed)\b",
    _I,
)
"""Days in a run ("No School, April 4-8", "Dec. 20 - 31", "February 18th and 19th", "Monday
through Friday", "closure extended"): a break, or a closure longer than a day's."""
_NEGATED = re.compile(
    r"\b(?:no|not\s+(?:an?|have\s+an?|be\s+an?)|without(?:\s+an?)?)\s+"
    r"(?:early\s+(?:dismissal|release|out)|(?:\w+[- ]hours?[- ])?(?:delay(?:ed)?(?:\s+start)?"
    r"|late\s+start))\b"
    r"|\b(?:normal|regular|full)\s+(?:school\s+)?(?:day|schedule)\b|\bon\s+time\b"
    r"|\b(?:will\s+be|are|is)\s+(?:open|in\s+session)\b",
    _I,
)
"""A notice that says the day is ordinary: "Feb 14th is a normal School Day with no early
dismissal", "There is NO Early Out Thursday, February 14th" (Darby's homepage, 2019)."""


def pinned_days(text: str, near: date) -> set[date]:
    """The calendar days ``text`` names, each read in the year that puts it nearest ``near``.

    A month and day with its year is that day; with its weekday, the nearest year whose
    calendar puts the weekday there; alone, the nearest year (the caller holds the day
    near the capture, where a month and day is not ambiguous). "M/D" and "M/D/YYYY" are
    read the same way.
    """
    found: set[date] = set()
    for match in _PINNED_DAY.finditer(text):
        weekday, month_name, day_text, year_text, month_num, day_num, year_num = match.groups()
        if month_name is not None:
            month, day = _MONTH_NUMBER[month_name.lower()], int(day_text)
            year = int(year_text) if year_text else None
        else:
            month, day = int(month_num), int(day_num)
            year = int(year_num) if year_num else None
            year = year + 2000 if year is not None and year < _CENTURY else year
        years = [year] if year is not None else [near.year - 1, near.year, near.year + 1]
        candidates: list[date] = []
        for value in years:
            try:
                candidates.append(date(value, month, day))
            except ValueError:
                continue
        if weekday is not None:
            wanted = _WEEKDAY_NUMBER[weekday.lower()]
            candidates = [found_day for found_day in candidates if found_day.weekday() == wanted]
        if candidates:
            found.add(min(candidates, key=lambda candidate: abs((candidate - near).days)))
    return found


def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (nth - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    following = date(year + month // _DECEMBER, month % _DECEMBER + 1, 1)
    last = following - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def school_break(day: date) -> bool:
    """Whether ``day`` is a weekend, a federal holiday, a day of Thanksgiving week's break or
    of the winter holidays (20 December to 2 January): a day schools are off by the calendar.

    The federal holidays are New Year's Day, Martin Luther King Jr. Day, Presidents' Day,
    Memorial Day, Juneteenth, Independence Day, Labor Day, Columbus (Indigenous Peoples') Day,
    Veterans Day and Thanksgiving (with the Wednesday before and the Friday after).
    """
    if day.weekday() >= _SATURDAY:
        return True
    if (day.month, day.day) in {(1, 1), (6, 19), (7, 4), (11, 11)}:
        return True
    if day >= date(day.year, *_HOLIDAYS_FROM) or day <= date(day.year, *_HOLIDAYS_TO):
        return True
    thanksgiving = _nth_weekday(day.year, 11, 3, 4)
    holidays = {
        _nth_weekday(day.year, 1, 0, 3),
        _nth_weekday(day.year, 2, 0, 3),
        _last_weekday(day.year, 5, 0),
        _nth_weekday(day.year, 9, 0, 1),
        _nth_weekday(day.year, 10, 0, 2),
        thanksgiving - timedelta(days=1),
        thanksgiving,
        thanksgiving + timedelta(days=1),
    }
    return day in holidays


_OTHER_REASON = re.compile(
    r"\b(?:covid(?:-?19)?|coronavirus|pandemic|illness(?:es)?|influenza|flu|sickness"
    r"|staff(?:ing)?\s+shortages?|threats?|lockdowns?|funerals?|testing)\b",
    _I,
)
"""A reason other than weather ("San Benito CISD will be CLOSED Thursday, January 20 and
Friday, January 21, 2022 due to COVID-related health and safety issues"): no warning
corroborates such a closing."""
_NOT_DATED = (
    _OTHER_REASON,
    _HEALTH_ORDER,
    _PLANNED,
    _SPANISH_PLANNED,
    _PLANNING,
    _SERVICE,
    _EXPLAINER,
    _QUESTION,
    _NEGATED,
    _SPAN,
)
"""What a dated closing may not be: a closing for another reason, a planned day, a planning
document, a description of procedures, a teaser, a question, an ordinary day or a run of
days."""


def dated_closing(
    status: str,
    title: str | None,
    captured_at: datetime,
    warnings: Mapping[date, WarningDay],
) -> WarningDay | None:
    """The NWS warning that corroborates a notice's closing of the days it names, if any.

    A district's notice of a closing, a delay, a remote day, cancelled classes or no school
    for a day it names, with no reason given, proves its channel when the NWS had a warning
    over one of the district's counties that school day: Granite's "Distance Learning Day
    for Granite School District - Wednesday, February 22, 2023" (a Winter Storm Warning over
    Salt Lake County that morning) and Canyons' "Remote-Learning Day Announced for all CSD
    Schools for Friday. Dec. 2" (2022). The notice must name one day, or at most
    :data:`DATED_MOST` days that are not a run (:data:`_SPAN`: "No School, April 4-8",
    "Dec. 20 - 31", "through"), each by its date (:func:`pinned_days`) and each between
    :data:`DATED_BEFORE` before and :data:`DATED_AFTER` after the capture's school day
    (posted for the storm, not a calendar's entry read weeks ahead); no day it names may be a
    weekend, a holiday or a break (:func:`school_break`: Canyons' "Schools, District Office
    Closed Feb. 21" of 2022 was Presidents' Day, under a Winter Weather Advisory); and a
    warning of at least :data:`DATED_WEIGHT` (an advisory alone does not corroborate) must
    have covered one of them. A closing for another reason (:data:`_OTHER_REASON`: COVID-19,
    an illness, a threat), a planned day, a planning document, a description of procedures,
    a teaser, a question and a notice that the day is ordinary ("no early dismissal",
    :data:`_NEGATED`) never qualify. Returns the strongest such warning (its
    day, weight and county), recorded with the proof.
    """
    text = " ".join(part for part in (title, status) if part).replace("\u2019", "'")
    if not warnings or any(pattern.search(text) for pattern in _NOT_DATED):
        return None
    cleaned = _NOT_A_CLOSING.sub(" ", text)
    closing = (
        any(pattern.search(cleaned) for pattern in _STATUS)
        or _SPANISH_STATUS.search(cleaned) is not None
        or _NO_CLASSES.search(cleaned) is not None
    )
    near = school_day(captured_at.astimezone(UTC))
    days = sorted(pinned_days(text, near)) if closing else []
    if not 0 < len(days) <= DATED_MOST or any(
        not near - DATED_BEFORE <= day <= near + DATED_AFTER or school_break(day) for day in days
    ):
        return None
    found = [warnings[day] for day in days if day in warnings]
    strongest = max(found, key=lambda warning: warning.weight, default=None)
    return strongest if strongest is not None and strongest.weight >= DATED_WEIGHT else None


# A post of a channel's dated history ------------------------------------------------

CORROBORATING_WEIGHT = 0.25
"""The weakest NWS code that corroborates a post's weather: a Winter Weather Advisory."""
EMERGENCY = re.compile(
    r"\bpower\s+outages?|\bwithout\s+power|\blost\s+power|\bno\s+power"
    r"|\bboil[- ]water\b|\bwater\s+main\s+break|\bno\s+(?:running\s+)?water\b"
    r"|\bevacu(?:ation|ate|ated)\b|\bgas\s+leak|\bwildfires?\b",
    re.IGNORECASE,
)
"""An emergency the NWS does not record, which a post may close for (no warning needed)."""


def days_in_window(text: str, published: datetime) -> bool:
    """Whether every day ``text`` names lies within the dated window of its publication."""
    near = school_day(published)
    return all(near - DATED_BEFORE <= day <= near + DATED_AFTER for day in pinned_days(text, near))


def corroborated(
    text: str, published: datetime, warnings: Mapping[date, WarningDay]
) -> WarningDay | str | None:
    """The NWS code that corroborates a post's weather, or the emergency it names.

    The code must be at least :data:`CORROBORATING_WEIGHT` over one of the source's
    counties on the school day the post is about
    (:func:`~snowlight.sources.stations.storms.school_day`: from about 4 PM local time on,
    the next morning), the school day before it (the storm
    whose drifts close the roads the next morning: Shoshoni's "Due to the extreme weather and
    road conditions, there will be no school on Friday, March 7, 2025", posted the afternoon
    of a Winter Storm Warning), or, when the day is a weekend, the Monday after.
    """
    found = EMERGENCY.search(text)
    if found is not None:
        return found.group(0).lower()
    near = school_day(published)
    later = near
    while later.weekday() >= _SATURDAY:  # a post of a Friday evening is about Monday
        later += timedelta(days=1)
    for day in (near, near - timedelta(days=1), later):
        warning = warnings.get(day)
        if warning is not None and warning.weight >= CORROBORATING_WEIGHT:
            return warning
    return None


_NOT_TODAYS_CLOSING = re.compile(
    r"\bas\s+(?:scheduled|usual|normal)\b"
    r"|\bif\b[^.!?]{0,120}?\b(?:we|schools?|the\s+district|classes)\s+(?:will|may|might)\b",
    _I,
)
"""A post saying school goes on (as scheduled) or what will happen if the weather turns
("PreK-6th grade will have school as scheduled today ... If the storm begins to produce
dangerous conditions, we will proceed with an early dismissal", Glenrock's of 2025-03-06):
no closing yet."""


def history_row_proves(  # noqa: PLR0913 - the row, its time, the warnings and its kind
    name: str,
    status: str,
    *,
    title: str | None,
    published: datetime,
    warnings: Mapping[date, WarningDay],
    tv_list: bool,
) -> WarningDay | str | None:
    """Whether one row of a history read proves its source, and what corroborates it.

    ``title`` is the text read with the status (a district channel's post is read by its
    status alone; a closings article's row with the article's title, which names the day).
    Returns the corroborating warning or emergency, or None when the row does not prove.
    """
    text = " ".join(part for part in (title, name, status) if part)
    if not tv_list and (
        not weather_closing(status, None)
        or _NEGATED.search(status) is not None
        or _NOT_TODAYS_CLOSING.search(status) is not None
    ):
        return None
    if tv_list and not (name.strip() or status.strip()):
        return None
    if not days_in_window(text, published):
        return None
    return corroborated(text, published, warnings)


def row_text(name: str, status: str, variant: str, section: str | None) -> tuple[str, str | None]:
    """A gated row's status and the title read with it, as :func:`row_qualifies` reads them."""
    if section == PAGE_TEXT or variant in WEATHER_GATED_VARIANTS:
        return status, None if name == status else name
    return status, None if variant in ORG_NAMED_VARIANTS else name


class Captured(Protocol):
    """What the page-text rule reads of a proof: when its page was read."""

    @property
    def captured_at(self) -> datetime: ...


class ProofLike(Protocol):
    """What the gate reads of a proof (``snowlight.sources.stations.proof.Proof``)."""

    @property
    def source_id(self) -> str: ...
    @property
    def mode(self) -> str: ...
    @property
    def url(self) -> str: ...
    @property
    def captured_at(self) -> datetime: ...
    @property
    def variant(self) -> str: ...
    @property
    def basis(self) -> str: ...


class GateRow(NamedTuple):
    """A row as the gate reads it: its name, its status, its ``raw_extra["section"]`` and
    the row's own stamp (a status board's or an alert's update time, ``raw_updated_text``,
    or a board's closure date, ``raw_extra["closure_date"]``), when it gives one."""

    name: str
    status: str
    section: str | None
    stamp: str | None = None
    note: str | None = None
    """The row's comments, when its list gives them (Gray's ``comments``: "Health Concerns")."""


type RowIndex = Mapping[tuple[str, datetime], list[GateRow]]


def _instant(text: str) -> datetime:
    value = datetime.fromisoformat(text)
    return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)


def load_rows(paths: Iterable[Path], source_ids: set[str]) -> RowIndex:
    """Rows of ``rows.jsonl`` files, by (source, read time), for the given sources only."""
    found: dict[tuple[str, datetime], list[GateRow]] = defaultdict(list)
    for path in paths:
        if not path.is_file():
            continue
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                source = row.get("source_id")
                if source not in source_ids:
                    continue
                key = (str(source), _instant(str(row["fetched_at"])))
                extra = row.get("raw_extra")
                section = extra.get("section") if isinstance(extra, dict) else None
                closure = extra.get("closure_date") if isinstance(extra, dict) else None
                stamp = closure if isinstance(closure, str) else row.get("raw_updated_text")
                found[key].append(
                    GateRow(
                        str(row["raw_name"]),
                        str(row.get("raw_status") or ""),
                        section if isinstance(section, str) else None,
                        stamp if isinstance(stamp, str) and stamp.strip() else None,
                        _note(extra),
                    )
                )
    return dict(found)


_NOTE_FIELDS = ("comments", "comments_line1", "comments_line2", "comments_line3", "comment")


def _note(extra: object) -> str | None:
    """A row's comments (``raw_extra``), joined, or None."""
    if not isinstance(extra, dict):
        return None
    parts = [str(extra[key]) for key in _NOTE_FIELDS if isinstance(extra.get(key), str)]
    text = " ".join(part for part in parts if part.strip())
    return text or None


SHUTDOWN_WAVE = (date(2020, 3, 13), date(2020, 6, 30))
"""The first wave of the pandemic's shutdowns, when a list's closings were the pandemic's
whatever their text said (Twin Falls' KMVT: "Closed Through Sunday 3/29")."""


def pandemic_read(rows: Iterable[GateRow], captured_at: datetime) -> bool:
    """Whether every row of a list's read is a pandemic's closing: the read was made in
    :data:`SHUTDOWN_WAVE`, or each row's text and comments are a pandemic's
    (:func:`pandemic`: KMVT's "North Valley Academy | Closed Through Monday", its comment
    "Health Concerns", 2022-01-27)."""
    day = captured_at.astimezone(UTC).date()
    if SHUTDOWN_WAVE[0] <= day <= SHUTDOWN_WAVE[1]:
        return True
    found = list(rows)
    return bool(found) and all(
        pandemic(" ".join(part for part in (row.name, row.status, row.note) if part), captured_at)
        for row in found
    )


def pandemic_only_lists[P: ProofLike](
    proofs: Mapping[str, list[P]],
    registry: Registry,
    *,
    live_rows: Iterable[Path],
    archive_rows: Iterable[Path],
) -> list[str]:
    """The closings lists (stations no notice gate judges) every proof of which is a pandemic
    read (:func:`pandemic_read`): lists never seen holding a closing for anything but the
    pandemic. A list's proof stands on any row (it lists closings only, and its schools
    entered these); this says which proven lists have shown no weather day yet."""
    gated = gated_adapters(registry)
    wanted = {
        sid
        for sid, items in proofs.items()
        if sid in registry.stations
        and sid not in gated
        and items
        and all(not item.basis.startswith("fixture ") for item in items)
    }
    rows = {"live": load_rows(live_rows, wanted), "archive": load_rows(archive_rows, wanted)}
    found: list[str] = []
    for source_id in sorted(wanted):
        reads = [
            (item, rows.get(item.mode, {}).get((source_id, item.captured_at.astimezone(UTC))))
            for item in proofs[source_id]
        ]
        if all(
            found_rows is not None and pandemic_read(found_rows, item.captured_at)
            for item, found_rows in reads
        ):
            found.append(source_id)
    return found


def _fixture_rows(root: Path, basis: str, adapter: str) -> list[GateRow] | None:
    relative = basis.removeprefix("fixture ").strip()
    path = root / relative
    if not path.is_file():
        return None
    try:
        listing = adapter_for(adapter)(path.read_bytes())
    except ShapeError:
        return None
    return [
        GateRow(
            row.name,
            row.status,
            _section(row.extra.get("section")),
            _section(row.extra.get("closure_date")) or row.updated_text,
        )
        for row in listing.rows
    ]


def _section(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _rows_of(
    item: ProofLike, rows: Mapping[str, RowIndex], fixtures: Path | None, adapter: str
) -> list[GateRow] | None:
    if item.basis.startswith("fixture "):
        return _fixture_rows(fixtures, item.basis, adapter) if fixtures is not None else None
    index = rows.get(item.mode, {})
    return index.get((item.source_id, item.captured_at.astimezone(UTC)))


def gated_adapters(registry: Registry) -> dict[str, bool]:
    """Each gated station's id, and whether it is a status board (else a channel)."""
    found: dict[str, bool] = {}
    for station in registry.stations.values():
        adapter = registry.platform_of(station).adapter
        if adapter in GENERAL_CHANNEL_ADAPTERS or adapter in STATUS_BOARD_ADAPTERS:
            found[station.id] = adapter in STATUS_BOARD_ADAPTERS
    return found


def _listed(item: ProofLike, row: GateRow | None) -> dict[str, JSONValue]:
    return {
        "mode": item.mode,
        "captured_at": item.captured_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "url": item.url,
        "basis": item.basis,
        "row": " | ".join(row[:2])[:300] if row is not None else None,
        **({"section": row[2]} if row is not None and row[2] else {}),
    }


def _dated_row(
    item: ProofLike, rows: Iterable[GateRow], warnings: Mapping[date, WarningDay]
) -> tuple[GateRow, WarningDay] | None:
    """The first of a proof's rows that is a dated closing on a warning day, and the warning."""
    if not warnings:
        return None
    for row in rows:
        status, title = row_text(row[0], row[1], item.variant, row[2])
        warning = dated_closing(status, title, item.captured_at, warnings)
        if warning is not None:
            return row, warning
    return None


HISTORY = "history"
"""The mode of a proof read from a channel's dated history (``ReadMode.HISTORY``)."""


def _history_row(
    item: ProofLike,
    rows: Iterable[GateRow],
    warnings: Mapping[date, WarningDay],
    *,
    board: bool,
) -> tuple[GateRow, WarningDay | str] | None:
    """The first row of a history read that proves its source, and what corroborates it.

    A district channel's post by :func:`history_row_proves` (its status read alone); a
    TV list's row (a station's closings article, whose source is not gated) by the same
    rule as a list's row, any row. A status board has no history mode.
    """
    if board:
        return None
    tv_list = item.variant not in CHANNEL_HISTORY_VARIANTS
    for row in rows:
        why = history_row_proves(
            row[0],
            row[1],
            title=None,
            published=item.captured_at,
            warnings=warnings,
            tv_list=tv_list,
        )
        if why is not None:
            return row, why
    return None


def _corroboration(why: WarningDay | str) -> dict[str, JSONValue]:
    if isinstance(why, WarningDay):
        return {"warning": _warning_json(why)}
    return {"emergency": why}


def _judge_history(
    item: ProofLike,
    found: list[GateRow] | None,
    warnings: Mapping[date, WarningDay],
    *,
    board: bool,
) -> tuple[dict[str, JSONValue], bool]:
    """A history proof's entry in the gate's report, and whether it is kept."""
    history = _history_row(item, found or [], warnings, board=board)
    if history is None:
        entry = _listed(item, found[0] if found else None)
        entry["reason"] = (
            "rows not found"
            if found is None
            else "no post announces a closing for weather or an emergency, published near the "
            "days it names, with the NWS or an emergency to corroborate it"
        )
        return entry, False
    row, why = history
    return {**_listed(item, row), **_corroboration(why)}, True


def _judge_channel(  # noqa: PLR0913 - the proof, its rows, the warnings and the rules in force
    item: ProofLike,
    found: list[GateRow] | None,
    warnings: Mapping[date, WarningDay],
    *,
    board: bool,
    dated_ok: bool,
    known: object,
    first_seen: Mapping[str, datetime] | None = None,
) -> tuple[dict[str, JSONValue], bool, bool]:
    """A gated channel's or board's proof: its report entry, whether kept, whether dated."""
    proving = next(
        (
            row
            for row in found or []
            if row_qualifies(
                row[0], row[1], item.variant, board=board, section=row[2], when=item.captured_at
            )
            and _text_current(row, item, warnings, known is not None, first_seen)
            and stamp_current(row, item.captured_at)
        ),
        None,
    )
    if proving is not None:
        return _listed(item, proving), True, False
    dated = _dated_row(item, found or [], warnings) if dated_ok else None
    if dated is not None:
        row, warning = dated
        return {**_listed(item, row), "warning": _warning_json(warning)}, True, True
    entry = _listed(item, found[0] if found else None)
    qualifying = [
        row
        for row in found or []
        if row_qualifies(
            row[0], row[1], item.variant, board=board, section=row[2], when=item.captured_at
        )
    ]
    leftover = bool(qualifying)
    if found is None:
        entry["reason"] = "rows not found"
    elif qualifying and not any(stamp_current(row, item.captured_at) for row in qualifying):
        entry["reason"] = (
            "a row announces a closing but is a leftover: its own date or update stamp lies "
            "more than a week before the read (or more than three days after it)"
        )
        entry["row"] = " | ".join(qualifying[0][:2])[:300]
    elif board and any(_PLANNED_STATUS.search(row[1]) for row in found):
        entry["reason"] = "every row's status other than open is a planned closing"
    elif board:
        entry["reason"] = "every row's status is open"
    elif leftover:
        entry["reason"] = (
            "a line of the page's text announces a closing but is a leftover, not the day's "
            "news: it names a day far from the read, or names none and the page already "
            "showed it on an earlier school day or no NWS advisory or warning covered the "
            "district near the read"
        )
    else:
        entry["reason"] = (
            "no row announces a closing, delay, early dismissal, remote day or no school"
        )
    return entry, False, False


_DAYS_AGO = re.compile(r"^\s*(\d{1,3})\s+days?\s+ago\b", _I)


def stamp_day(stamp: str | None, captured_at: datetime) -> date | None:
    """The day a row's own stamp names, or None.

    A stamp is an instant or a date in ISO 8601 ("2026-06-18", GOHSEP's closure date;
    "2024-01-15T21:20:00Z", an alert's), a count of days before the read ("3 days ago",
    Smart Sites'), or a date as a page writes it ("9/10 9:45", the Shasta office's sheet;
    "September 25, 26 8:11 AM", Flathead's), read in the year nearest the read.
    """
    if stamp is None or not stamp.strip():
        return None
    text = stamp.strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    ago = _DAYS_AGO.search(text)
    if ago is not None:
        return captured_at.astimezone(UTC).date() - timedelta(days=int(ago.group(1)))
    days = pinned_days(text, school_day(captured_at.astimezone(UTC)))
    return max(days) if days else None


STAMP_BEFORE = timedelta(days=7)
"""How long before the read's school day a row's own stamp may lie: a storm's notice stays up
through the closing it announces (Gulf Shores' of 2026-10-07, for a hurricane closing and a
fall break through 12 October, read the morning of the 13th)."""


def stamp_current(row: GateRow, captured_at: datetime) -> bool:
    """Whether a row's own stamp (:func:`stamp_day`) lies near the read: no more than
    :data:`STAMP_BEFORE` before the read's school day nor :data:`DATED_AFTER` after it. A row
    with no stamp passes. A status still shown long after its own date is a leftover:
    Shasta's "Black Butte Elementary | Closing at 12:45", updated "9/10 9:45" and read from
    2026-09-27 to 2026-10-13; GOHSEP's "Ascension | Closed" of 2026-06-18, read in October."""
    day = stamp_day(row.stamp, captured_at)
    if day is None:
        return True
    near = school_day(captured_at.astimezone(UTC))
    return near - STAMP_BEFORE <= day <= near + DATED_AFTER


TEXT_WARNING_DAYS = 2
"""How many school days either side of a capture an NWS code must lie within for an undated
line of a homepage's text to count (:func:`_text_current`)."""


_POSTED_ROW = re.compile(
    r"\(posted\s+((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})\)\s*$",
    _I,
)
"""A page-text row's posting stamp (:data:`snowlight.sources.stations.homepage.POSTED_MARK`)."""


def posted_day(text: str) -> date | None:
    """The day a page-text row's news card says it was posted, or None."""
    found = _POSTED_ROW.search(text)
    if found is None:
        return None
    words = collapse_spaces(found.group(1).replace(",", " ").replace(".", " ")).split(" ")
    try:
        return datetime.strptime(f"{words[0][:3]} {words[1]} {words[2]}", "%b %d %Y").date()
    except (ValueError, IndexError):
        return None


def collapse_spaces(text: str) -> str:
    """Runs of white space as one space, trimmed."""
    return " ".join(text.split())


def line_key(row: GateRow) -> str:
    """A page-text row's text as the leftover rule compares it (case and spacing aside)."""
    return collapse_spaces(" ".join(part for part in row[:2] if part)).lower()


def _text_current(
    row: GateRow,
    item: Captured,
    warnings: Mapping[date, WarningDay],
    known: bool,
    first_seen: Mapping[str, datetime] | None = None,
) -> bool:
    """Whether a page-text row was the day's news when its page was read, not a leftover.

    A homepage keeps its news items long after the day (Greenville's "GPSD closed on
    January 16, 2024 (Due to inclement weather)", still up on 2026-10-13; North Gem's
    "all North Gem schools are closed today", up from 2026-02-18 through the spring and
    still on 2026-10-13). A line of a page's text (``section`` page-text) proves only:

    * when it carries its news card's posting stamp (:data:`_POSTED_ROW`: Gulf's "SCHOOL
      CLOSURES: Hurricane Isaias", posted 2026-10-07), as a dated post of that day: no
      day it names lies outside the dated window of the posting, and an NWS code
      corroborates its weather on the school day it was posted, the day before or, for a
      stamp that gives no time, the next (:func:`corroborated`);
    * otherwise, when no day it names lies outside the dated window of the read
      (:data:`DATED_BEFORE` before, :data:`DATED_AFTER` after), and, when it names no day,
      an NWS advisory or warning covered one of the district's counties within
      :data:`TEXT_WARNING_DAYS` days of the read (when the warning days are ``known``),
      and the page did not already show the same line on an earlier school day
      (``first_seen``: the earliest read of the station's page that held it). A line
      repeated unchanged is the news of the school day it first appeared on ("closed
      today") and a leftover on every later one.

    Other rows are a channel's own notices, judged as before.
    """
    if row[2] != PAGE_TEXT:
        return True
    text = " ".join(part for part in row[:2] if part)
    day = posted_day(text)
    if day is not None:
        return not known or _posted_current(text, day, warnings)
    if not days_in_window(text, item.captured_at):
        return False
    near = school_day(item.captured_at)
    named = pinned_days(text, near)
    if named or not known:
        return True
    first = (first_seen or {}).get(line_key(row))
    if first is not None and school_day(first) != near:
        return False
    span = timedelta(days=TEXT_WARNING_DAYS)
    return any(
        near - span <= day <= near + span and warning.weight >= CORROBORATING_WEIGHT
        for day, warning in warnings.items()
    )


def _posted_current(text: str, day: date, warnings: Mapping[date, WarningDay]) -> bool:
    """Whether a card posted on ``day`` (no time given) is corroborated as a dated post."""
    moments = (
        datetime(day.year, day.month, day.day, 17, tzinfo=UTC),  # about noon at home
        datetime(day.year, day.month, day.day, 23, 30, tzinfo=UTC),  # the evening
    )
    return any(
        days_in_window(text, moment) and corroborated(text, moment, warnings) is not None
        for moment in moments
    )


def first_appearances(
    items: Iterable[tuple[datetime, list[GateRow] | None]],
) -> dict[str, datetime]:
    """When each undated page-text line was first read on a station's page (any read)."""
    seen: dict[str, datetime] = {}
    for captured_at, found in sorted(items, key=lambda pair: pair[0]):
        for row in found or []:
            if row[2] != PAGE_TEXT:
                continue
            key = line_key(row)
            if key not in seen or captured_at < seen[key]:
                seen[key] = captured_at
    return seen


def gate_proofs[P: ProofLike](  # noqa: PLR0913, PLR0915 - the proofs, their rows, the warnings
    proofs: MutableMapping[str, list[P]],
    registry: Registry,
    *,
    live_rows: Iterable[Path],
    archive_rows: Iterable[Path],
    fixtures: Path | None,
    warnings: Mapping[str, Mapping[date, WarningDay]] | None = None,
    chosen: MutableMapping[str, P] | None = None,
) -> dict[str, JSONValue]:
    """Keep a gated station's proofs only when a row of theirs announces a closing.

    Gated stations are those whose platform's adapter is a general alert channel
    or a status board; proofs of every other station are left as they are. A
    proof whose rows cannot be found is dropped. A channel's proof none of whose
    rows qualifies by :func:`row_qualifies` is kept when one is a dated closing on a
    warning day (:func:`dated_closing`, given ``warnings``: each station's NWS warning
    days, :func:`snowlight.sources.stations.storms.warning_days`); the warning is
    listed with it (``warning``: its day, weight and county). Returns the report
    written into ``coverage.json`` as ``district_notice_gate`` (see the module
    docstring). With ``chosen``, each gated station's proof to record is put there
    (:func:`_preferred`: a kept proof whose row names weather or an emergency, or that
    the NWS corroborated, before any other; the earliest of them first).
    """
    boards = gated_adapters(registry)
    cards = {
        sid
        for sid, items in proofs.items()
        if sid not in boards
        and sid in registry.stations
        and any(item.variant in WEATHER_GATED_VARIANTS for item in items)
    }
    histories = {
        sid
        for sid, items in proofs.items()
        if sid in registry.stations and any(item.mode == HISTORY for item in items)
    }
    adapters = {
        sid: registry.platform_of(registry.stations[sid]).adapter
        for sid in set(boards) | cards | histories
        if sid in registry.stations
    }
    wanted = (set(boards) | cards | histories) & set(proofs)
    rows = {
        "live": load_rows(live_rows, wanted),
        "archive": load_rows(archive_rows, wanted),
    }
    report: dict[str, JSONValue] = {}
    for source_id in sorted(wanted):
        board = boards.get(source_id, False)
        kept: list[P] = []
        kept_listed: list[JSONValue] = []
        kept_strong: list[bool] = []
        corroborated: list[JSONValue] = []
        dropped: list[JSONValue] = []
        station_warnings = (warnings or {}).get(source_id, {})
        channel = source_id in boards and not board
        found_by_item = (
            [_rows_of(item, rows, fixtures, adapters[source_id]) for item in proofs[source_id]]
            if channel
            else []
        )
        first_seen = (
            first_appearances(
                (item.captured_at, found)
                for item, found in zip(proofs[source_id], found_by_item, strict=True)
                if item.mode != HISTORY
            )
            if channel
            else {}
        )
        for index, item in enumerate(proofs[source_id]):
            if item.mode == HISTORY:
                found = _rows_of(item, rows, fixtures, adapters[source_id])
                listed, proves = _judge_history(item, found, station_warnings, board=board)
                if proves:
                    kept.append(item)
                    kept_listed.append(listed)
                    kept_strong.append(True)
                    corroborated.append(listed)
                else:
                    dropped.append(listed)
                continue
            if source_id not in boards and source_id not in cards:
                kept.append(item)  # a TV list's own live or archived proof: any row proves it
                kept_strong.append(False)
                continue
            if source_id in cards and item.variant not in WEATHER_GATED_VARIANTS:
                kept.append(item)  # a TV list's own proof: any row proves it
                kept_strong.append(False)
                continue
            found = (
                found_by_item[index]
                if channel
                else _rows_of(item, rows, fixtures, adapters[source_id])
            )
            dated_ok = warnings is not None and not board and source_id not in cards
            listed, proves, dated = _judge_channel(
                item,
                found,
                station_warnings,
                board=board,
                dated_ok=dated_ok,
                known=warnings,
                first_seen=first_seen,
            )
            if proves:
                kept.append(item)
                kept_listed.append(listed)
                kept_strong.append(dated or _names_weather(listed.get("row")))
                if dated:
                    corroborated.append(listed)
            else:
                dropped.append(listed)
        proofs[source_id] = kept
        if chosen is not None and kept and source_id in boards:
            chosen[source_id] = _preferred(kept, kept_strong)
        kind = "board" if board else ("cards" if source_id in cards else "channel")
        summary: dict[str, JSONValue] = {
            "kind": kind if source_id in boards or source_id in cards else "list",
            "kept": len(kept),
            "kept_proofs": kept_listed[:MAX_LISTED],
            "dropped_count": len(dropped),
            "dropped": dropped[:MAX_LISTED],
        }
        if corroborated:
            summary["corroborated"] = corroborated
        report[source_id] = summary
    return report


def _names_weather(row: JSONValue) -> bool:
    """Whether a kept proof's listed row names weather or an emergency (or road conditions)."""
    text = row if isinstance(row, str) else ""
    return bool(_WEATHER.search(text) or _SPANISH_WEATHER.search(text) or _ROADS.search(text))


def _preferred[P: ProofLike](kept: list[P], strong: list[bool]) -> P:
    """The proof a gated station records: the earliest kept proof whose row names weather or
    an emergency or was corroborated by the NWS, else the earliest kept proof. Idaho Falls'
    "D91 is cancelling school on Monday, Jan. 30, because of extreme weather and cold"
    (2023-01-31), not a later read; Sublette #9's first capture of its late start, not a
    repeat of it."""
    pool = [item for item, good in zip(kept, strong, strict=True) if good] or kept
    return min(pool, key=lambda item: item.captured_at)


def _warning_json(warning: WarningDay) -> dict[str, JSONValue]:
    return {"day": warning.day.isoformat(), "weight": warning.weight, "county": warning.county}


def annotate_warnings(
    result: MutableMapping[str, JSONValue], report: Mapping[str, JSONValue]
) -> None:
    """Add to each station's proof in ``result`` the NWS warning that corroborated it, if any.

    A proof the gate kept as a dated closing on a warning day (``corroborated`` in the
    gate's report) carries its ``warning`` (day, weight, county) in the station's
    ``proof``, so the record says what the row alone did not.
    """
    stations = result.get("stations")
    if not isinstance(stations, dict):
        return
    for source_id, gate in report.items():
        entry = stations.get(source_id)
        if not isinstance(gate, dict) or not isinstance(entry, dict):
            continue
        found = entry.get("proof")
        corroborated = gate.get("corroborated")
        if not isinstance(found, dict) or not isinstance(corroborated, list):
            continue
        for listed in corroborated:
            if (
                isinstance(listed, dict)
                and listed.get("captured_at") == found.get("captured_at")
                and listed.get("url") == found.get("url")
            ):
                found["warning"] = listed.get("warning")
                break


def annotate_unproven(
    result: MutableMapping[str, JSONValue], report: Mapping[str, JSONValue]
) -> None:
    """Say in each unproven gated station's ``checked`` how many of its reads the gate dropped."""
    unproven = result.get("unproven")
    if not isinstance(unproven, list):
        return
    for entry in unproven:
        if not isinstance(entry, dict):
            continue
        gate = report.get(str(entry.get("id")))
        checked = entry.get("checked")
        if not isinstance(gate, dict) or not isinstance(checked, dict):
            continue
        checked["notice_gate"] = {
            "kind": gate.get("kind"),
            "populated_reads_dropped": gate.get("dropped_count"),
            "rule": "board: a status other than open"
            if gate.get("kind") == "board"
            else "channel: a closing, delay, dismissal, remote day, weather or emergency notice",
        }
