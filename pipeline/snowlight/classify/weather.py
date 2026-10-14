"""The weather a status text names, the reason labels it supports, and other causes.

Only words in the text count: nothing is inferred from the season, the place or
the weather feed. Each term maps to at most one reason label (see
:data:`snowlight.classify.model.REASONS`); broad words such as "weather",
"inclement weather", "storm" or "fog" name weather without supporting a label.

Words that look like weather but are not are skipped: "no heat" and "heating"
(a building problem), "cold lunch", "ice cream", "rain date", "blizzard bag" (a
take-home learning packet), flooding in a text that also names a burst pipe or
a water main, and a weather word that begins a school's name ("Hurricane
Middle School", "Cold Spring Elementary", "Storm Lake Community Schools").
Wildfire smoke, poor air quality and earthquakes are causes but not weather.
"Power outage" is a reason label but not weather: an outage has many causes,
so it does not set ``names_weather``.
"""

import re
import string
from collections.abc import Callable, Iterable
from functools import lru_cache, reduce
from operator import or_
from typing import NamedTuple

from snowlight.classify.model import REASONS, Reason
from snowlight.classify.text import WEATHER_START_SHIFT, Pieces, scan, starts, trie

type Category = Reason | None


class WeatherFindings(NamedTuple):
    """What :func:`find_weather` found in one text."""

    terms: tuple[str, ...]
    reasons: tuple[Reason, ...]
    other_causes: tuple[str, ...]

    @property
    def names_weather(self) -> bool:
        """Whether the text names any weather."""
        return bool(self.terms)


# (pattern, canonical term, reason label). Longer phrases come first.
_TERMS: tuple[tuple[str, str, Category], ...] = (
    (r"hurricanes?", "hurricane", "Hurricane"),
    (r"tropical\s+storms?", "tropical storm", "Severe storms"),
    (r"tropical\s+depressions?", "tropical depression", None),
    (r"storm\s+surge", "storm surge", "Flooding"),
    (r"winter\s+storms?", "winter storm", "Winter storm"),
    (r"snow\s*storms?", "snowstorm", "Winter storm"),
    (r"ice\s+storms?", "ice storm", "Ice"),
    (r"blizzards?(?!\s+bags?)", "blizzard", "Winter storm"),
    (r"nor'?\s?easters?", "nor'easter", "Winter storm"),
    (r"lake[- ]effect(?:\s+snow)?", "lake-effect snow", "Winter storm"),
    (r"winter\s+weather", "winter weather", "Winter storm"),
    (r"winter\s+mix|wintry\s+mix|wintery\s+mix", "wintry mix", "Winter storm"),
    (r"wintry|wintery", "wintry weather", "Winter storm"),
    (r"snow\s*melt", "snowmelt", "Flooding"),
    (r"snow(?:s|y|fall|falls|ing|ed|pack)?", "snow", "Winter storm"),
    (r"freezing\s+rain", "freezing rain", "Ice"),
    (r"freezing\s+drizzle", "freezing drizzle", "Ice"),
    (r"sleet", "sleet", "Ice"),
    (r"black\s+ice", "ice", "Ice"),
    (
        r"ic(?:e|y|ing|ed)(?!\s+(?:cream|skating|skate|rink|hockey|arena|breaker|machine|pack))",
        "ice",
        "Ice",
    ),
    (
        r"(?:extreme|bitter|dangerous(?:ly)?|severe|record|arctic|frigid)\s+cold",
        "extreme cold",
        "Extreme cold",
    ),
    (r"wind\s*chills?", "wind chill", "Extreme cold"),
    (r"sub[- ]?zero|below[- ]zero", "subzero temperatures", "Extreme cold"),
    (r"polar\s+vortex", "polar vortex", "Extreme cold"),
    (r"arctic(?:\s+(?:air|blast|front|outbreak))?", "arctic air", "Extreme cold"),
    (r"frigid(?:\s+(?:temperatures?|temps|air))?", "frigid temperatures", "Extreme cold"),
    (r"(?:freezing|low)\s+(?:temperatures?|temps)", "freezing temperatures", "Extreme cold"),
    (
        r"(?<!common\s)cold(?!\s*(?:lunch|lunches|meals?|breakfast|sandwich|food|and\s+flu|/\s*flu))"
        r"(?:\s+(?:weather|temperatures?|temps|snap))?",
        "cold",
        "Extreme cold",
    ),
    (r"flash\s+flood(?:s|ing|ed)?", "flash flooding", "Flooding"),
    (r"flood(?:s|ing|ed|waters?)?", "flooding", "Flooding"),
    (r"high\s+water|rising\s+water", "high water", "Flooding"),
    (
        r"water\s+(?:over|on|across)\s+(?:the\s+)?(?:roads?|roadways?|streets?)",
        "water over roads",
        "Flooding",
    ),
    (r"severe\s+(?:thunder)?storms?", "severe storms", "Severe storms"),
    (r"severe\s+weather", "severe weather", "Severe storms"),
    (r"thunder\s*storms?|t-storms?", "thunderstorms", "Severe storms"),
    (r"tornado(?:es|s)?", "tornado", "Severe storms"),
    (r"hail(?:storms?)?", "hail", "Severe storms"),
    (r"lightning", "lightning", "Severe storms"),
    (r"derechos?", "derecho", "Severe storms"),
    (r"damaging\s+winds?", "damaging winds", "Severe storms"),
    (r"(?:extreme|excessive|high|intense|dangerous)\s+heat", "extreme heat", "Heat"),
    (r"heat\s*waves?", "heat wave", "Heat"),
    (r"heat\s+(?:advisory|advisories|warnings?|index|emergency)", "extreme heat", "Heat"),
    (r"hot\s+(?:weather|temperatures?|temps|conditions)", "hot weather", "Heat"),
    (r"high\s+(?:temperatures?|temps)", "high temperatures", "Heat"),
    (
        r"(?<!no\s)(?<!without\s)(?<!of\s)(?<!lost\s)heat(?!ing|er)"
        r"(?!\s+(?:outage|is\s+out|issues?|problems?|not\s+working|failure|loss|system|pump))",
        "heat",
        "Heat",
    ),
    (r"(?:dense\s+)?fog(?:gy)?", "fog", None),
    (r"(?:high|strong|gusty)\s+winds?|wind\s+gusts?", "high winds", None),
    (r"(?:heavy\s+|torrential\s+)?rain(?:fall|s|y|storms?)?(?!\s+dates?)", "rain", None),
    (r"inclement\s+weather", "inclement weather", None),
    (
        r"(?<!non-)(?<!non\s)(?<!not\s)(?<!unrelated\sto\s)(?<!not\sdue\sto\s)weather",
        "weather",
        None,
    ),
    (r"storms?", "storm", None),
)
_POWER = re.compile(
    r"\b(?:power\s+(?:outages?|failures?|loss|is\s+out|out)|(?:no|without|loss\s+of|lost)\s+"
    r"(?:electric\s+)?power|electrical\s+outages?|electric\s+outages?|blackouts?)\b",
    re.ASCII,
)
_CAUSES: tuple[tuple[str, str], ...] = (
    (
        r"water\s+main|water\s+line|water\s+leak|no\s+water|water\s+outage|boil\s+water"
        r"|water\s+(?:issues?|problems?)|(?:burst|broken|frozen|leaking)\s+pipes?|pipes?\s+burst",
        "Water service",
    ),
    (
        r"no\s+heat|without\s+heat|lack\s+of\s+heat|loss\s+of\s+heat|heating|boiler|furnace"
        r"|heat\s+(?:outage|is\s+out|issues?|problems?|not\s+working|failure)",
        "Heating",
    ),
    (r"gas\s+(?:leak|odor|smell)|smell\s+of\s+gas", "Gas leak"),
    (
        r"(?:wildfire|forest\s+fire|brush\s+fire)\s+smoke|smoke\s+from\s+(?:the\s+)?"
        r"(?:wild|forest|brush)?fires?|smoky\s+(?:air|conditions)|air\s+quality|aqi"
        r"|unhealthy\s+air|poor\s+air",
        "Air quality",
    ),
    (
        r"wildfires?|forest\s+fires?|brush\s+fires?|grass\s+fires?|red\s+flag\s+warning"
        r"|fire\s+danger",
        "Wildfire",
    ),
    (r"earthquakes?|quake|seismic", "Earthquake"),
    (r"fire(?!\s+(?:drill|alarm\s+test|danger))", "Fire"),
    (r"illness|flu|influenza|sickness|virus|outbreak|covid(?:-19)?|norovirus|strep", "Illness"),
    (
        r"threats?|lockdown|shelter\s+in\s+place|police\s+activity|security\s+(?:issue|concern)s?"
        r"|bomb",
        "Security",
    ),
    (
        r"(?:staff|staffing|teacher|driver|bus\s+driver|substitute)\s+shortages?|shortage\s+of"
        r"|staffing",
        "Staffing",
    ),
    (
        # ("Closed, workday optional" is a storm closure that leaves staff the choice to work.)
        r"holiday|(?<!optional )(?:teacher\s+)?work\s*day(?!\s+(?:is\s+)?optional)"
        r"|professional\s+(?:development|learning)"
        r"|pd\s+day|in-?service|institute\s+day|records\s+day|parent-teacher\s+conferences?"
        r"|conferences|(?:winter|spring|fall|thanksgiving|christmas)\s+break|vacation"
        r"|election\s+day|mlk|martin\s+luther\s+king|presidents'?\s+day|memorial\s+day"
        r"|labor\s+day|veterans'?\s+day|thanksgiving|christmas|new\s+year'?s?",
        "Planned day",
    ),
    (
        # (Water inside a building is no flood of the area: "a flood in the gym".)
        r"flood(?:ing|ed)?\s+(?:in|at|inside)\s+(?:the\s+|our\s+|a\s+)?(?:school\s+)?"
        r"(?:gym|gymnasium|building|basement|classrooms?|cafeteria|hallways?|library|kitchen"
        r"|auditorium|boiler\s+room|locker\s+rooms?)"
        r"|flooded\s+(?:gym|gymnasium|building|basement|classrooms?|cafeteria|hallways?|library"
        r"|kitchen|auditorium|boiler\s+room|locker\s+rooms?)"
        r"|air\s+condition(?:ing|er)|\ba/c\b|hvac|mold|construction|maintenance|building\s+issues?"
        r"|internet\s+outage|network\s+outage|phone\s+outage|sewer|septic",
        "Building",
    ),
    (r"funeral", "Funeral"),
)


# A school's name after a weather word: up to two more name words, then the kind of school
# ("Hurricane Middle School", "Snow Hill Elementary"). A general word such as "schools" or
# "district" needs a name word before it: "Storm Lake Community Schools", not "snow schools".
_NAME_TAIL = re.compile(
    r"(?P<names>(?: [a-z]+){0,2}?) (?P<kind>elementary|intermediate|academy|montessori"
    r"|preparatory|isd|usd|cusd|(?:middle|high|primary|secondary) schools?|junior high|high"
    r"|schools?|district|community|public|charter|christian|catholic|county|township|unified"
    r"|consolidated)\b",
    re.ASCII,
)
NAME_KINDS = frozenset(
    {
        "elementary", "intermediate", "academy", "montessori", "preparatory", "isd", "usd",
        "cusd", "school", "schools", "junior", "high", "district", "community", "public", "charter",
        "christian", "catholic", "county", "township", "unified", "consolidated",
    }
)  # fmt: skip
"""Words one of which every school name :data:`_NAME_TAIL` reads holds: without one in the
text, no weather word begins a school's name."""
_SPECIFIC_KINDS = frozenset(
    {"elementary", "intermediate", "academy", "montessori", "preparatory", "isd", "usd", "cusd"}
)
# Words before a name: the text's start, a mark, or one of these.
_BEFORE_NAME = frozenset({"at", "and", "for", "to", "of"})
_MARKS = frozenset(",;:|.!?-/")
# Words that cannot be part of a name after a weather word: "snow closes Lincoln Elementary",
# "ice at Maple Elementary", "storm forces district to close".
_NOT_NAME = frozenset(
    {
        "a", "all", "an", "and", "are", "area", "at", "be", "both", "cancelled", "canceled",
        "cancels", "causes", "close", "closed", "closes", "closing", "closure", "closures",
        "conditions", "day", "days", "delay", "delayed", "delays", "dismissal", "early",
        "emergency", "for", "forces", "from", "has", "have", "hits", "impact", "impacts",
        "in", "is", "keeps", "late", "leads", "means", "morning", "near", "no", "of", "on",
        "or", "other", "prompts", "shuts", "the", "to", "today", "tomorrow", "tonight",
        "warning", "watch", "advisory", "was", "will", "with", "high", "wind", "winds",
        "heavy", "freezing", "icy", "ice", "snow", "snowy", "rain", "rainy", "storm", "storms",
        "sleet", "hail", "cold", "fog", "foggy", "weather", "gusty", "strong", "extreme",
        "dangerous", "bitter", "totals", "total", "chances", "chance", "risk", "levels",
        "level", "amounts", "accumulation", "accumulations", "danger", "threat", "potential",
        "chill", "chills", "index", "temps", "temperatures", "expected", "forecast", "remains",
        "stays", "running", "very", "too",
    }
)  # fmt: skip


# Words right before a weather term that say there is none: "no snow expected", "not due to
# weather".
_NEGATED = re.compile(
    r"\b(?:no|not|without)\s+(?:(?:due\s+to|because\s+of|related\s+to)\s+)?(?:(?:any|the)\s+)?\Z",
    re.ASCII,
)
# What follows a name that labels a listing: the end, or a mark ("Hurricane Schools: closed").
_LABEL_END = re.compile(r" ?(?:$|[:;,|]| -)", re.ASCII)


def begins_name(text: str, start: int, end: int) -> bool:
    """Whether the word at ``start:end`` begins a school's name: "Remote Valley School".

    The words after it must be up to two more name words and a kind of school
    ("Snow Canyon High", "Hurricane Middle School"), and it must start the text
    or follow a mark. A general kind ("schools", "district") needs a name word
    between, unless the name heads the text as a label: "Hurricane Schools: 2
    hour delay", not "snow schools closed".
    """
    return _in_name(text, start, end)


def _in_name(text: str, start: int, end: int) -> bool:
    """Whether the weather word at ``start:end`` begins a school's name."""
    tail = _NAME_TAIL.match(text, end)
    if tail is None:
        return False
    names = tail.group("names").split()
    kind = tail.group("kind")
    before = text[:start].rstrip()
    labelled = _LABEL_END.match(text, tail.end()) is not None
    if kind not in _SPECIFIC_KINDS and " " not in kind and not names and (before or not labelled):
        return False  # "snow schools closed": the weather, then who it closes
    if kind == "high" and not labelled:
        return False  # "snow totals high today": no name ("Snow Canyon High: closed" is one)
    if any(name in _NOT_NAME for name in names):
        return False
    return not before or before[-1] in _MARKS or before.rsplit(None, 1)[-1] in _BEFORE_NAME


def _alternation(patterns: tuple[str, ...]) -> re.Pattern[str]:
    """One pattern for all of ``patterns``: the match's ``lastindex`` is one more than the index
    of the one that matched (the patterns have no groups of their own)."""
    groups = "|".join(f"({pattern})" for pattern in patterns)
    return re.compile(rf"\b(?:{groups})\b", re.ASCII)


_WEATHER = _alternation(tuple(pattern for pattern, _term, _reason in _TERMS))
_OTHER = _alternation(tuple(pattern for pattern, _label in _CAUSES))


_LOOKAROUNDS = ("(?!", "(?<!", "(?=", "(?<=")


def _without_lookarounds(pattern: str) -> str:
    """A pattern with its lookahead and lookbehind groups left out: the words a term is spelt
    with, not those it must not stand beside ("ice" not before "cream", "fire" not "drill")."""
    kept: list[str] = []
    depth = 0  # how deep inside a lookaround group the scan is (0: outside every one)
    index = 0
    while index < len(pattern):
        if pattern.startswith(_LOOKAROUNDS, index) or (depth and pattern[index] == "("):
            depth += 1
        elif depth and pattern[index] == ")":
            depth -= 1
        elif not depth:
            kept.append(pattern[index])
        index += 1
    return "".join(kept)


def _term_words() -> frozenset[str]:
    """Every word that a weather term or a cause is spelt with ("freezing", "rain", "main")."""
    found: set[str] = set()
    for pattern in (
        *(pattern for pattern, _term, _reason in _TERMS),
        *(pattern for pattern, _label in _CAUSES),
    ):
        plain = re.sub(r"\\[a-zA-Z]", " ", _without_lookarounds(pattern))
        found.update(re.findall(r"[a-z]+", plain))
    return frozenset(found)


TERM_WORDS = _term_words()
"""Every word of the weather terms and the causes (see :func:`term_word` for whole words)."""


def term_word(token: str) -> bool:
    """Whether a word is a weather term or a cause all by itself: "snowy", "flooding", "icy"."""
    return _WEATHER.fullmatch(token) is not None or _OTHER.fullmatch(token) is not None


def _group_end(pattern: str, start: int) -> int:
    """Where the group that opens at ``start`` in ``pattern`` ends (just past its ")")."""
    depth = 0
    index = start
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            index += 2
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    message = f"unbalanced group in {pattern!r}"
    raise ValueError(message)


def _alternatives(pattern: str) -> list[str]:
    """The top-level alternatives of ``pattern`` (split at each "|" outside a group)."""
    parts: list[str] = []
    depth = 0
    last = 0
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            index += 2
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "|" and depth == 0:
            parts.append(pattern[last:index])
            last = index + 1
        index += 1
    parts.append(pattern[last:])
    return parts


def _first_chars(pattern: str) -> frozenset[str] | None:
    """The characters a match of ``pattern`` can start with, or ``None`` if this cannot tell.

    Reads the plain forms the patterns here are written in: a literal word
    character, a non-capturing group of alternatives (optional or not), and
    look-behinds or word boundaries, which match no character. Anything else
    gives ``None``, which puts the pattern in every table (see :func:`_by_first`).
    """
    found: set[str] = set()
    for alternative in _alternatives(pattern):
        rest = alternative
        while rest.startswith(("(?<!", "(?<=", "\\b")):
            rest = rest[2:] if rest.startswith("\\b") else rest[_group_end(rest, 0) :]
        if rest.startswith("(?:"):
            end = _group_end(rest, 0)
            inner = _first_chars(rest[3 : end - 1])
            if inner is None:
                return None
            found |= inner
            if rest[end : end + 1] in {"?", "*"}:
                after = _first_chars(rest[end + 1 :])
                if after is None:
                    return None
                found |= after
        elif rest and (rest[0].isalnum() or rest[0] in "'-") and rest[1:2] not in {"?", "*", "{"}:
            found.add(rest[0])
        else:
            return None
    return frozenset(found)


type _Matcher = Callable[[str, int], re.Match[str] | None]


def _by_first(patterns: tuple[str, ...]) -> dict[str, tuple[_Matcher, tuple[int, ...]]]:
    """For each character a run can start with: :func:`_alternation` of the patterns whose
    matches can start with it, and the ``lastindex`` of the full alternation each of its
    own stands for.

    A pattern left out cannot match where the run starts, so the first of the rest that
    matches there is the first of all that does, with the same span: the same match the
    full alternation finds, tried against far fewer alternatives.
    """
    firsts = [_first_chars(pattern) for pattern in patterns]
    table: dict[str, tuple[_Matcher, tuple[int, ...]]] = {}
    for char in (
        string.ascii_lowercase + string.digits
    ):  # what a run of letters and digits starts with
        chosen = [index for index, first in enumerate(firsts) if first is None or char in first]
        narrow = _alternation(tuple(patterns[index] for index in chosen)) if chosen else _NEVER
        table[char] = (narrow.match, (0, *(index + 1 for index in chosen)))
    return table


_NEVER = re.compile(r"(?!)")
_WEATHER_BY_FIRST = _by_first(tuple(pattern for pattern, _term, _reason in _TERMS))
_OTHER_BY_FIRST = _by_first(tuple(pattern for pattern, _label in _CAUSES))
# By the ``lastindex`` of a match of _WEATHER or _OTHER (see _alternation): what it found.
_TERM_FIELDS: tuple[tuple[str, Category], ...] = (
    ("", None),
    *((term, reason) for _pattern, term, reason in _TERMS),
)
_CAUSE_LABELS: tuple[str, ...] = ("", *(label for _pattern, label in _CAUSES))
_REASON_RANK: dict[Reason, int] = {reason: rank for rank, reason in enumerate(REASONS)}
_new = tuple.__new__  # builds a named tuple from its fields without a Python-level call
_FLOOD_TERMS = frozenset({"flooding", "flash flooding", "high water"})


# What every term in _TERMS, and every cause in _CAUSES, starts with.
_WEATHER_STARTS = (
    "hurrican", "tropical", "storm", "winter", "wintry", "wintery", "snow", "ic", "bliz",
    "nor'", "nore", "nor e", "lake-effect", "lake effect", "sleet", "black ice", "freez",
    "extreme", "bitter", "danger", "severe", "record cold", "arctic", "frigid", "wind",
    "subzero", "sub-zero", "sub zero", "below zero", "below-zero", "polar", "low temp",
    "cold", "flash", "flood", "high w", "high t", "high h", "rising water", "water over",
    "water on", "water across", "thunder", "t-storm", "tstorm", "tornad", "hail", "lightn",
    "derech", "damaging", "excess", "intense", "heat", "hot", "fog", "dense fog",
    "strong wind", "gust", "heavy", "torrent", "rain", "inclement", "weather",
)  # fmt: skip
_CAUSE_STARTS = (
    "water main", "water line", "water leak", "no water", "water outage", "boil water",
    "water issue", "water problem", "burst", "broken pipe", "frozen pipe", "leaking pipe",
    "pipe", "no heat", "without heat", "lack of heat", "loss of heat", "heating", "boiler",
    "furnace", "heat outage", "heat is out", "heat issue", "heat problem", "heat not",
    "heat failure", "gas leak", "gas odor", "gas smell", "smell of gas", "fire", "illness",
    "wildfire", "forest fire", "brush fire", "grass fire", "smoke from", "smoky", "air quality",
    "aqi", "unhealthy air", "poor air", "red flag", "earthquake", "quake", "seismic",
    "flu", "influenza", "sickness", "virus", "outbreak", "covid", "norovirus", "strep",
    "threat", "lockdown", "shelter in place", "police activity", "security issue",
    "security concern", "bomb", "staff shortage", "staffing", "teacher shortage",
    "driver shortage", "bus driver", "substitute shortage", "shortage of", "holiday",
    "teacher work", "work day", "workday", "professional development",
    "professional learning", "pd day", "in-service", "inservice", "institute day",
    "records day", "parent-teacher", "conferences", "winter break", "spring break",
    "fall break", "thanksgiving", "christmas", "vacation", "election day", "mlk",
    "martin luther", "presidents", "memorial day", "labor day", "veterans", "new year",
    "air condition", "a/c", "hvac", "mold", "construction", "maintenance", "building issue",
    "internet outage", "network outage", "phone outage", "sewer", "septic", "funeral", "flood",
)  # fmt: skip


_WEATHER_CANDIDATES = starts(_WEATHER_STARTS)
_CAUSE_CANDIDATES = starts(_CAUSE_STARTS)
# The same starts by their first character, for :func:`_candidate_at`.
_WEATHER_STARTS_BY_FIRST = {
    first: tuple(start for start in _WEATHER_STARTS if start[0] == first)
    for first in {start[0] for start in _WEATHER_STARTS}
}
_CAUSE_STARTS_BY_FIRST = {
    first: tuple(start for start in _CAUSE_STARTS if start[0] == first)
    for first in {start[0] for start in _CAUSE_STARTS}
}
_WORD_CHARS = frozenset(string.ascii_letters + string.digits + "_")


def _candidate_at(text: str, position: int, by_first: dict[str, tuple[str, ...]]) -> bool:
    """Whether a start of ``by_first`` begins a word at ``position``: what the matching
    pattern of :func:`~snowlight.classify.text.starts` finds there, read without the regex
    engine."""
    return text.startswith(by_first.get(text[position], ()), position) and (
        not position or text[position - 1] not in _WORD_CHARS
    )


# For deciding from a text's words alone whether to scan: a one-word start can begin a
# longer word ("flood" in "flooding"); a start of several words needs its first word whole.
_WEATHER_WORDS = tuple(start for start in _WEATHER_STARTS if " " not in start)
_WEATHER_FIRST = frozenset(start.split(" ")[0] for start in _WEATHER_STARTS if " " in start)
_CAUSE_WORDS = tuple(start for start in _CAUSE_STARTS if " " not in start)
_CAUSE_FIRST = frozenset(start.split(" ")[0] for start in _CAUSE_STARTS if " " in start)


# What a word can start, as bits of :func:`word_hints`.
WEATHER_START = 1
CAUSE_START = 2
_NOTHING = WeatherFindings((), (), ())
NO_FINDINGS = _NOTHING
"""What :func:`find_weather` returns for a text with no weather term and no cause (shared)."""

# What a run of letters and digits can start, as start-mask bits (see :func:`start_hint`): a
# weather term or a cause surely starts at a run that begins with a start written in letters
# and digits alone, and may start at a run that is the first word of a longer one ("black" of
# "black ice", "a" of "a/c"), which the scan checks against the text.
WEATHER_SURE = 1 << WEATHER_START_SHIFT
WEATHER_MAYBE = 2 << WEATHER_START_SHIFT
CAUSE_SURE = 4 << WEATHER_START_SHIFT
CAUSE_MAYBE = 8 << WEATHER_START_SHIFT
WEATHER_START_BITS = WEATHER_SURE | WEATHER_MAYBE | CAUSE_SURE | CAUSE_MAYBE


def _head(start: str) -> str:
    """The letters and digits a start opens with, up to its first other mark."""
    for index, char in enumerate(start):
        if not ("a" <= char <= "z" or "0" <= char <= "9"):
            return start[:index]
    return start


def _start_table(prefixes: tuple[str, ...], sure: int, maybe: int) -> dict[str, dict[str, int]]:
    table: dict[str, dict[str, int]] = {}
    for start in prefixes:
        head = _head(start)
        bit = sure if head == start else maybe
        table.setdefault(head[0], {})
        table[head[0]][head if bit == sure else head + "$"] = bit
    return table


def _merged(*tables: dict[str, dict[str, int]]) -> dict[str, tuple[tuple[str, int], ...]]:
    merged: dict[str, dict[str, int]] = {}
    for table in tables:
        for first, entries in table.items():
            for key, bit in entries.items():
                merged.setdefault(first, {})
                merged[first][key] = merged[first].get(key, 0) | bit
    return {first: tuple(entries.items()) for first, entries in merged.items()}


_STARTS_BY_FIRST = _merged(
    _start_table(_WEATHER_STARTS, WEATHER_SURE, WEATHER_MAYBE),
    _start_table(_CAUSE_STARTS, CAUSE_SURE, CAUSE_MAYBE),
)


def _grouped(
    entries: tuple[tuple[str, int], ...],
) -> tuple[dict[str, int], tuple[tuple[int, tuple[str, ...]], ...]]:
    """The whole-run entries of a first letter by run, and its prefixes grouped by their bits."""
    wholes: dict[str, int] = {}
    prefixes: dict[int, list[str]] = {}
    for key, bit in entries:
        if key.endswith("$"):
            wholes[key[:-1]] = wholes.get(key[:-1], 0) | bit
        else:
            prefixes.setdefault(bit, []).append(key)
    return wholes, tuple((bit, tuple(keys)) for bit, keys in prefixes.items())


_STARTS_GROUPED = {first: _grouped(entries) for first, entries in _STARTS_BY_FIRST.items()}
START_PREFIXES: tuple[str, ...] = tuple(
    prefix
    for _wholes, groups in _STARTS_GROUPED.values()
    for _bit, prefixes in groups
    for prefix in prefixes
)
"""The run prefixes a weather term or a cause can start at (see :func:`start_hint`)."""


@lru_cache(maxsize=65536)
def start_hint(run: str) -> int:
    """Whether a weather term or a cause can start at a run of letters and digits."""
    found = _STARTS_GROUPED.get(run[:1])
    if found is None:
        return 0
    wholes, groups = found
    mask = wholes.get(run, 0)
    for bit, prefixes in groups:
        if run.startswith(prefixes):
            mask |= bit
    return mask


def _scanned(
    pattern: re.Pattern[str], text: str, candidates: re.Pattern[str]
) -> list[tuple[int, int, int]]:
    """:func:`scan` of ``text``: where each match starts and ends, and its ``lastindex``."""
    return [
        (match.start(), match.end(), match.lastindex or 0)
        for match in scan(pattern, text, candidates)
    ]


type _Found = list[tuple[int, int, int]]

# The start-mask bits of a run where a weather term or a cause surely starts.
SURE_STARTS = WEATHER_SURE | CAUSE_SURE


def candidate_in(text: str, runs: Pieces) -> bool:
    """Whether any of ``runs`` can start a weather term or a cause, as :func:`_both_at` tries
    them: a run whose start mask holds a "sure" bit, or a "maybe" bit where its candidate
    begins in the text.

    With none, :func:`find_weather` given these runs finds nothing but "power" or
    "blackout" ("no school" can begin "no heat", and begins nothing here).
    """
    for base, places in runs:
        for offset, mask in places:
            if mask & SURE_STARTS:
                return True
            if (
                mask & CAUSE_MAYBE and _candidate_at(text, base + offset, _CAUSE_STARTS_BY_FIRST)
            ) or (
                mask & WEATHER_MAYBE
                and _candidate_at(text, base + offset, _WEATHER_STARTS_BY_FIRST)
            ):
                return True
    return False


def _both_at(text: str, runs: Pieces, hints: int) -> tuple[_Found, _Found]:
    """The causes and the weather terms that start at ``runs``: :func:`_scanned` of each.

    One walk over the runs serves both scans; each keeps to itself where its last
    match ended, and tries only the runs whose start mask holds its bits (a run
    with only the "maybe" bit where its candidate pattern matches). At a run,
    the narrower pattern for its first character is tried (see
    :func:`_by_first`). ``hints`` says which of the two scans can find anything.
    """
    cause_bits = CAUSE_SURE | CAUSE_MAYBE if hints & CAUSE_START else 0
    weather_bits = WEATHER_SURE | WEATHER_MAYBE if hints & WEATHER_START else 0
    causes: _Found = []
    terms: _Found = []
    cause_end = term_end = 0
    for base, places in runs:
        for offset, mask in places:
            position = base + offset
            if (
                mask & cause_bits
                and position >= cause_end
                and (mask & CAUSE_SURE or _candidate_at(text, position, _CAUSE_STARTS_BY_FIRST))
            ):
                match_at, indexes = _OTHER_BY_FIRST[text[position]]
                match = match_at(text, position)
                if match is not None:
                    cause_end = match.end()
                    causes.append((position, cause_end, indexes[match.lastindex or 0]))
            if (
                mask & weather_bits
                and position >= term_end
                and (mask & WEATHER_SURE or _candidate_at(text, position, _WEATHER_STARTS_BY_FIRST))
            ):
                match_at, indexes = _WEATHER_BY_FIRST[text[position]]
                match = match_at(text, position)
                if match is not None:
                    term_end = match.end()
                    terms.append((position, term_end, indexes[match.lastindex or 0]))
    return causes, terms


# Any word that starts with a one-word start, or is the first word of a longer one.
_ANY_START = re.compile(trie([*_WEATHER_WORDS, *_CAUSE_WORDS]), re.ASCII)
_ANY_FIRST = _WEATHER_FIRST | _CAUSE_FIRST
ANY_START = _ANY_START
"""Any word a weather term or a cause can start with, from its start (see word_hints)."""


@lru_cache(maxsize=65536)
def word_hints(word: str) -> int:
    """Whether one word can start a weather term or a cause, as bits (cached).

    So can a part of a word joined by a hyphen or a slash: the "snow" of "school-snow" in
    "No School-Snow Day".
    """
    hints = _hints_of(word)
    if "-" in word or "/" in word:
        for part in _JOINS.split(word):
            hints |= _hints_of(part)
    return hints


_JOINS = re.compile(r"[/-]", re.ASCII)  # the marks that join the parts of a word


def _hints_of(word: str) -> int:
    if word not in _ANY_FIRST and _ANY_START.match(word) is None:
        return 0  # most words: a quick no
    weather = word in _WEATHER_FIRST or word.startswith(_WEATHER_WORDS)
    cause = word in _CAUSE_FIRST or word.startswith(_CAUSE_WORDS)
    return (WEATHER_START if weather else 0) | (CAUSE_START if cause else 0)


def _inside(position: int, spans: list[tuple[int, int]]) -> bool:
    """Whether ``position`` is inside one of ``spans``."""
    for low, high in spans:  # noqa: SIM110 - (a loop costs less than a generator, per call)
        if low <= position < high:
            return True
    return False


def find_weather(  # noqa: PLR0912 - the gates on each scan
    text: str,
    vocabulary: Iterable[str] | None = None,
    hints: int | None = None,
    runs: Pieces | None = None,
    *,
    names: bool = True,
) -> WeatherFindings:
    """Return the weather terms, reason labels and other causes in normalized ``text``.

    ``hints`` is the union of :func:`word_hints` over the text's words, or
    ``vocabulary`` the set of them, when the caller has it; the scans that none
    of its words can start are skipped. ``runs``, when the caller has it, lists
    where the runs of letters and digits that can start something start in the
    text, in order, with their start-mask bits (see :func:`start_hint`), by the
    stretch that holds them (see :data:`~snowlight.classify.text.Pieces`): then
    only those runs are tried, which finds what a scan of the whole text finds.
    ``names`` is false when the caller knows no run of the text is one of
    :data:`NAME_KINDS`, so that no weather word can begin a school's name.
    """
    if hints is None:
        hints = (
            WEATHER_START | CAUSE_START
            if vocabulary is None
            else reduce(or_, map(word_hints, vocabulary), 0)
        )
    if not hints and "power" not in text and "blackout" not in text:
        return _NOTHING
    if runs is None:
        found_causes = _scanned(_OTHER, text, _CAUSE_CANDIDATES) if hints & CAUSE_START else []
        found_terms = _scanned(_WEATHER, text, _WEATHER_CANDIDATES) if hints & WEATHER_START else []
    else:
        found_causes, found_terms = _both_at(text, runs, hints)
    if not found_causes and not found_terms and "power" not in text and "blackout" not in text:
        return _NOTHING  # (what the rest finds in a text with none of them: nothing)
    causes: list[str] = []
    for _start, _end, index in found_causes:
        label = _CAUSE_LABELS[index]
        if label not in causes:
            causes.append(label)
    terms: list[str] = []
    categories: list[Reason] = []
    if found_terms:
        building_water = "Water service" in causes
        # "A flood in the gym": the building's water, found as a cause over the same words.
        inside = [
            (low, high) for low, high, index in found_causes if _CAUSE_LABELS[index] == "Building"
        ]
        for start, end, index in found_terms:
            term, category = _TERM_FIELDS[index]
            low = max(0, start - 32)
            if (
                (building_water and term in _FLOOD_TERMS)
                or (inside and _inside(start, inside))
                or (names and _in_name(text, start, end))
                or (
                    # (Every negation _NEGATED reads holds "no" or "without": a quick look.)
                    (text.find("no", low, start) >= 0 or text.find("without", low, start) >= 0)
                    and _NEGATED.search(text, low, start) is not None
                )
            ):
                continue
            if term not in terms:
                terms.append(term)
            if category is not None and category not in categories:
                categories.append(category)
    if ("power" in text or "blackout" in text) and _POWER.search(text) is not None:
        categories.append("Power outage")
    if len(categories) > 1:
        categories.sort(key=_REASON_RANK.__getitem__)
    return _new(WeatherFindings, (tuple(terms), tuple(categories), tuple(causes)))
