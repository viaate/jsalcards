"""Statuses that cover only part of a district: exceptions, restrictions and places.

A district's listing can leave some of its schools out of a status:

* an exception: "All schools closed except Lincoln Elementary", "with the
  exception of Lincoln Elementary", "other than Lincoln", "All schools except
  Lincoln are closed", "2 hour delay for all schools but Lincoln";
* a restriction to a school by name: "Closed (Lincoln Elementary only)",
  "Closed - east campus only", "Closed only at Lincoln";
* a place: "Closed at some locations", "Closed in the northern part of the
  district", "Closed north of Route 9", "North campus closed", "All other
  schools on a 2 hour delay", or named sites ("PTEC, Astrozon and Howard
  campuses closed", "Des Moines locations closed").

Read as the district's own status, such a listing would give the schools it
leaves out a status they do not have. :func:`carved` finds these phrases and
the statuses they limit: the status they belong to, and every status after
them in the same sentence ("All schools closed except Lincoln Elementary,
which will have a 2 hour delay"). The parser makes each of those a status
about part of the program (see :mod:`snowlight.classify.parse`), so the text
states no status for the district as a whole.

Leaving out people or services that are not the school day keeps the status
whole: "Closed except staff", "Closed except essential staff", "Closed except
central office", "Closed except for meal pickup", "Closed - students only",
"Remote learning only". A place named for the cause belongs to the cause
("Closed due to flooding north of Route 9"), and one site at either end of the
text, set off by a mark, is the listing's own name ("Closed - Oak Ridge
Campus", "Morehead State - Ashland Campus: Closed"). An exception for a day
("Closed Monday through Friday except Wednesday") leaves the days of the status
unread.
"""

import re
from bisect import bisect_right
from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from typing import Literal

from snowlight.classify.dates import GROUP_END, GROUP_START, DateGroup
from snowlight.classify.lexicon import CAUSES, CONDITIONALS, HEDGES, MODIFIERS, NEGATIONS, SCOPES
from snowlight.classify.mentions import Mention
from snowlight.classify.text import words
from snowlight.classify.weather import CAUSE_START, WEATHER_START
from snowlight.classify.weather import word_hints as weather_hints

# The compass directions, and their adjectives ("northern", "southeastern").
_DIRECTION = r"(?:(?:north|south)(?:-?(?:east|west))?|east|west)"
_DIRECTION_ADJECTIVE = rf"{_DIRECTION}(?:ern)?"
# Words that pick out some places, not all: "at some locations", "for select schools".
_SOME = (
    r"(?:some|select(?:ed)?|certain|several|a\s+few|various|specific|multiple|individual"
    r"|the\s+following|these|those|listed|affected|impacted|designated"
    # A count of them is some of them ("at two schools", "Closed at 3 campuses"), but all of
    # them ("all three locations", "both campuses") is every one.
    r"|(?<!all )(?<!the )(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|[2-9]"
    r"|[1-9]\d))"
)
# Nouns for a place a district runs: "locations", "sites", "campuses".
_PLACES = (
    r"(?:locations?|sites?|campus(?:es)?|buildings?|facilities|branch(?:es)?|areas?|parts"
    r"|regions?|zones?|communities|neighborhoods)"
)
# Nouns for part of an area: "part", "portion", "end".
_PARTS = r"(?:parts?|portions?|areas?|half|end|sections?|corners?|regions?|side)"
# A school level after a direction and a campus names a school: "North Campus High School".
_LEVEL_AFTER = (
    r"(?!\s+(?:high|middle|elementary|school|academy|junior|senior|primary|intermediate|prep"
    r"|preparatory)\b)"
)

# An exception, with the part it leaves out after it ("except Lincoln", "all schools but
# Lincoln").
_EXCEPT = re.compile(
    r"\b(?:except(?:ing)?(?:\s+for)?|with\s+the\s+exception\s+of|excluding|other\s+than"
    r"|besides|save\s+for|apart\s+from|aside\s+from|minus"
    r"|(?<!no\s)exceptions?\s*(?=:)"
    r"|(?:all|every|each)(?:\s+of\s+(?:the|our))?(?:\s+[a-z][a-z'-]*)?\s+(?:schools?|buildings?"
    r"|campus(?:es)?|sites?|locations?|branch(?:es)?|students|classes|grades)"
    # ... and the status between them: "All schools closed but Lincoln Elementary".
    r"(?:\s+(?!but\b)[a-z0-9'-]+){0,8}\s+but(?:\s+not)?"
    r"|every(?:one|body|thing)\s+but)\b",
    re.ASCII,
)
# The exception words that open a sentence as often as they follow a status: "Besides the
# snow, roads are icy" leaves nothing out (see _exceptions).
_LOOSE_EXCEPTS = ("besides", "save", "apart", "aside", "minus")
# The same after the part it leaves out: "Lincoln Elementary excluded".
_EXCLUDED = re.compile(r"\b(?:excluded|excepted|exempt(?:ed)?)\b", re.ASCII)
# A count in figures of places ("at 2 schools", "in 3 buildings"): a place phrase can hold it.
_COUNTED_PLACE = re.compile(
    r"\b(?:at|in|for)\s+\d{1,2}\s+(?:schools|campuses|buildings|sites|locations)\b"
    r"(?![-'/][a-z0-9])",  # (the noun is a word of its own, as words reads it: see _phrases)
    re.ASCII,
).search
# A place that limits a status, as a phrase of its own.
_PLACE = re.compile(
    r"\b(?:"
    rf"(?:(?:at|in|for)\s+)?{_SOME}\s+(?:school\s+)?{_PLACES}"
    rf"|(?:at|in|for)\s+{_SOME}\s+schools"
    # "All other schools", "the remaining schools", "Other schools: open" (not "along with
    # other schools").
    r"|(?:all\s+(?:the\s+)?|the\s+|(?<![a-z0-9'] )(?<![a-z0-9']))(?:other|remaining)\s+"
    r"(?:schools|locations|sites|campuses|buildings|branches|students|grades)"
    r"|at\s+others"
    rf"|in\s+(?:(?:some|certain|many|most|several|the|outlying)\s+)?"
    rf"(?:(?:far\s+)?{_DIRECTION_ADJECTIVE}\s+)?{_PARTS}\s+of"
    rf"|(?:on|in|for)\s+the\s+(?:far\s+)?{_DIRECTION_ADJECTIVE}\s+{_PARTS}"
    rf"|(?:far\s+)?{_DIRECTION_ADJECTIVE}\s+{_PARTS}\s+of"
    rf"|{_DIRECTION}\s+of(?=\s+[a-z0-9])"
    r")\b",
    re.ASCII,
)
# A site by its direction: "North campus closed", "south buildings".
_DIRECTION_SITE = re.compile(
    rf"\b{_DIRECTION_ADJECTIVE}\s+(?P<noun>campus(?:es)?|buildings?|sites?|locations?|wing"
    rf"|branch(?:es)?|annex)\b{_LEVEL_AFTER}",
    re.ASCII,
)
# "Only" after the part it restricts a status to ("Lincoln Elementary only"), or before it
# with a preposition ("only at Lincoln Elementary").
# (The boundary before it is read after it, looking back: the pattern opens with the word, so
# the regex engine skips from one "only" to the next.)
_ONLY = re.compile(r"only(?<!\wonly)\b(?:\s+(?P<prep>at|for|in)\b)?", re.ASCII)
# A noun for a place, after which a name is a school's site: "PTEC and Howard campuses".
_SITE = re.compile(
    rf"\b(?P<noun>locations?|campus(?:es)?|sites?|branch(?:es)?|buildings?)\b{_LEVEL_AFTER}",
    re.ASCII,
)
# Marks that can end a text, after its last word.
_END_MARKS = " .;,:!?|-"
# The site nouns for one site, which can end a school's own name: "Lancaster Campus".
_ONE_SITE = frozenset({"campus", "building", "site", "location", "branch", "wing", "annex"})
# A mark that ends a phrase, and one that ends a sentence.
_MARK = re.compile(r"[,;:!?|]|\.(?=\s|$)|(?:^|\s)-+(?=\s|$)", re.ASCII)
# The text up to the end of the last of those marks (the greedy run finds the last at once).
_UP_TO_MARK = re.compile(r"(?s).*(?:[,;:!?|]|\.(?=\s|$)|(?:^|\s)-+(?=\s|$))", re.ASCII).match
_SENTENCE_END = re.compile(r"[;!?|]|\.(?=\s|$)", re.ASCII)

CARVE_WORDS = frozenset(
    {
        "except", "excepting", "exception", "exceptions", "excluding", "excluded", "excepted",
        "exempt", "exempted", "other", "remaining", "others", "only", "besides", "save",
        "apart", "aside", "minus",
        "but", "everyone", "everybody", "everything", "north", "south", "east", "west",
        "northeast", "northwest", "southeast", "southwest", "north-east", "north-west",
        "south-east", "south-west", "northern", "southern", "eastern", "western",
        "northeastern", "northwestern", "southeastern", "southwestern", "part", "parts",
        "portion", "portions", "area", "areas", "region", "regions", "section", "sections",
        "corner", "corners", "locations", "location", "sites", "site", "campus", "campuses",
        "branch", "branches", "building", "buildings", "some", "select", "selected", "certain",
        "several", "various", "specific", "multiple", "individual", "following", "affected",
        "impacted", "designated", "zones", "zone", "communities", "neighborhoods", "facilities",
        "few", "these", "those", "listed",
    }
)  # fmt: skip
"""Words one of the phrases read here holds: a text with none of them has none (but for a
count before a noun of schools or places: see :data:`COUNT_CUES`)."""
COUNT_CUES = frozenset(
    {"two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"}
)
"""Counts in words, which a phrase of :data:`_PLACE` can hold ("at two locations"); the caller
reads a text with one before such a noun as it would one with a word of :data:`CARVE_WORDS`."""
# The nouns of places a count in figures can come before ("at 2 schools": see _COUNTED_PLACE).
_COUNTED_CUES = frozenset({"schools", "campuses", "buildings", "sites", "locations"})
_PRESENT_WORDS = CARVE_WORDS | COUNT_CUES | _COUNTED_CUES
# The words each form of phrase needs one of (see _phrases).
_EXCEPT_CUES = frozenset(
    {"except", "excepting", "exception", "exceptions", "excluding", "excluded", "excepted",
     "exempt", "exempted", "other", "but", "besides", "save", "apart", "aside", "minus"}
)  # fmt: skip
_EXCLUDED_CUES = frozenset({"excluded", "excepted", "exempt", "exempted"})
_SITE_CUES = frozenset(
    {"location", "locations", "campus", "campuses", "site", "sites", "branch", "branches",
     "building", "buildings"}
)  # fmt: skip
_PLACE_CUES = frozenset(
    {
        "some", "select", "selected", "certain", "several", "few", "various", "specific",
        "multiple", "individual", "following", "these", "those", "listed", "affected",
        "impacted", "designated", "other", "remaining", "others", "part", "parts", "portion",
        "portions", "area", "areas", "section", "sections", "corner", "corners", "region",
        "regions", "north", "south", "east", "west", "northeast", "northwest", "southeast",
        "southwest", "north-east", "north-west", "south-east", "south-west", "northern",
        "southern", "eastern", "western", "northeastern", "northwestern", "southeastern",
        "southwestern",
    }
)  # fmt: skip

# The kinds of status a phrase here can limit ("open" too: "Open except Lincoln").
_LIMITED = frozenset({"closed", "delayed", "remote", "early_dismissal", "open"})
# Who or what an exception can leave out and keep the status whole: not part of the school
# day. ("Closed except essential staff", "except central office", "except for meal pickup".)
_KEPT_SCOPES = frozenset({"staff", "office", "childcare", "transportation", "activities"})
_KEPT_WORDS = frozenset(
    {
        "essential", "emergency", "emergencies", "critical", "designated", "required",
        "necessary", "key", "crew", "crews", "worker", "workers", "maintenance", "custodial",
        "food", "meal", "meals", "nutrition", "pickup", "pick-up", "grab-and-go",
        "distribution", "delivery", "deliveries", "payroll", "security", "police",
        "administrative", "offices", "office",
    }
)  # fmt: skip
# Words that open the part an exception leaves out without being it: "except for the".
_LEADS = frozenset({"the", "all", "our", "any", "those", "a", "an", "of", "for", "its", "their"})
_LEADS_ONLY = _LEADS | frozenset({"at", "in", "to", "students", "student", "on"})
# Words that end the part an exception leaves out: "except Lincoln, which is open", "except
# Lincoln are closed", "except if roads are icy".
_ENDS = frozenset(
    {
        "which", "who", "that", "where", "when", "whenever", "if", "unless", "will", "would",
        "shall", "are", "is", "was", "were", "has", "have", "had", "remain", "remains", "can",
        "should", "may", "must", "due", "because", "owing",
    }
)  # fmt: skip
# Words for "that" which an exception can leave out and mean the rest of the text: "Other
# than that, normal schedule".
_NOT_PARTS = frozenset({"that", "this", "these", "those", "normal", "usual", "regular", "above"})
# Words that point to a list of the schools left out: "except where noted".
_NOTED = frozenset({"noted", "listed", "indicated", "stated", "shown", "specified", "posted"})
# Answers that leave out nothing: "Exceptions: none".
_NONE = frozenset({"none", "no", "n/a", "na", "nothing", "nobody", "noone"})
# Words a status leaves out by day, before a date: "except on Wednesday", "except for 1/21".
_DATE_LEADS = frozenset({"for", "on", "the"})
# Nouns for a place that a name before them makes one site: "Lincoln campus", "Des Moines
# locations".
_SITE_NOUNS = frozenset(
    {
        "campus", "campuses", "building", "buildings", "site", "sites", "location", "locations",
        "branch", "branches", "center", "centre", "academy", "annex", "wing", "school",
    }
)  # fmt: skip
# Words for a level of school, which before a site noun pick out some of the sites.
_LEVELS = frozenset(
    {
        "elementary", "middle", "high", "secondary", "primary", "intermediate", "junior",
        "senior", "upper", "lower", "school", "schools",
    }
)  # fmt: skip
# Words before a site noun that make it every site, or the school's own: "all locations",
# "our campus", "main campus".
_EVERY_SITE = frozenset(
    {
        "all", "both", "our", "the", "every", "each", "any", "its", "their", "his", "her", "this",
        "that", "main", "entire", "whole", "district", "school", "schools", "county", "city",
        "other", "remaining", "of", "at", "in", "for", "on", "and", "no", "home", "same",
    }
)  # fmt: skip
# Words that open a phrase naming a site without being its name: "at the Lincoln site".
_SITE_LEADS = frozenset({"at", "in", "for", "on", "the"})
# Words that say how something is held or what is offered, not where: "online service only",
# "meal pickup only", "virtual learning only".
_SERVICES = frozenset(
    {
        "service", "services", "learning", "instruction", "online", "virtual", "remote",
        "remotely", "streaming", "stream", "livestream", "livestreamed", "live", "broadcast",
        "worship", "mass", "masses", "meal", "meals", "food", "pickup", "delivery", "curbside",
        "appointment", "appointments", "emergency", "emergencies", "essential", "phone",
        "email", "takeout", "carryout", "session", "sessions", "shift", "shifts", "day", "days",
        "week", "weekend", "today", "tomorrow", "tonight", "morning", "afternoon", "evening",
        "night", "lunch", "breakfast", "dinner", "zoom", "facebook", "youtube", "website",
        "drive-thru", "drive-through", "walk-in", "walk-ins", "in-person", "inperson", "person",
        "elearning", "e-learning", "nti", "ami", "snow", "weather", "storm", "ice", "cold",
        "heat", "power", "water", "roads", "road", "routes", "route", "one", "first", "second",
        "third", "half", "full", "partial", "time", "hours", "hour", "minutes", "am", "pm",
    }
)  # fmt: skip
_JOINERS = frozenset({"and", "plus", "or"})
# Words that are no part of a school's name (see _name_word).
_NOT_NAMES = (
    frozenset(noun for noun in SCOPES if " " not in noun)
    | MODIFIERS.keys()
    | NEGATIONS
    | HEDGES
    | CONDITIONALS
    | _SERVICES
    | _EVERY_SITE
    | _ENDS
    | _LEADS_ONLY
    | _JOINERS
    | frozenset({"only", "also", "just", "not", "but", "be", "been", "being", "now", "still"})
)
_MOST_WORDS = 4  # the most words a part left out or restricted to runs to
_MOST_NAME_WORDS = 6  # the most words the names before a site noun run to


# How a phrase limits a status: an exception ("except Lincoln"), a place ("north of Route
# 9"), a restriction with "only" before its part ("only at Lincoln") or after it ("Lincoln
# Elementary only"), or named sites ("PTEC and Howard campuses").
type _Form = Literal["except", "place", "only", "only_after", "sites"]
# The forms whose phrase comes before the status it limits, as a subject does.
_SUBJECTS: frozenset[_Form] = frozenset({"place", "only_after", "sites"})


def carved(
    text: str, mentions: Sequence[Mention], groups: Sequence[DateGroup]
) -> tuple[frozenset[int], bool]:
    """Return the statuses a phrase limits to part of the district, by index in ``mentions``,
    and whether an exception leaves out a day.

    ``text`` is the normalized text; ``mentions`` its settled mentions (a status
    already about something else, denied, hedged or called off is left as it is);
    ``groups`` its date groups.
    """
    limited: set[int] = set()
    dated = False
    # Where the words of a phrase can start after: the end of a status or of a date.
    stops = sorted([mention.end for mention in mentions] + [group[GROUP_END] for group in groups])
    for start, end, form in _phrases(text, mentions, stops):
        target = _target(text, mentions, stops, start, end, form)
        if target is None or not _limits(mentions[target]):
            continue
        if form == "except" and _day_left_out(text, groups, end):
            dated = True  # "Closed Monday through Friday except Wednesday"
            continue
        limited.add(target)
        sentence_end = _sentence_end(text, end)
        limited.update(
            index
            for index, mention in enumerate(mentions)
            if end <= mention.start < sentence_end and _limits(mention)
        )
    return frozenset(limited), dated


def _phrases(
    text: str, mentions: Sequence[Mention], stops: Sequence[int]
) -> list[tuple[int, int, _Form]]:
    """Each phrase that limits a status to part of the district: its span, and its form.

    Each form's patterns run only when the text holds a word they need.
    """
    present = _PRESENT_WORDS.intersection(words(text))
    found = _exceptions(text, mentions, stops, present) if present & _EXCEPT_CUES else []
    if (
        present & _PLACE_CUES
        or present & COUNT_CUES
        or (present & _COUNTED_CUES and _COUNTED_PLACE(text) is not None)
    ):
        found.extend((match.start(), match.end(), "place") for match in _PLACE.finditer(text))
    if "only" in present:
        found.extend(_restrictions(text, mentions, stops))
    if not present & _SITE_CUES:
        return found
    for match in _DIRECTION_SITE.finditer(text) if present & _PLACE_CUES else ():
        start, end = match.span()
        if match.group("noun") not in _ONE_SITE or not _own_name(text, mentions, start, end):
            found.append((start, end, "sites"))
    for match in _SITE.finditer(text):
        start = _phrase_start(text, stops, match.start())
        named = words(text, start, match.start())
        while len(named) > 1 and named[0] in _SITE_LEADS:
            named.pop(0)  # "closed at the Lincoln site"
        if (
            named
            and _named_site(named)
            and (
                match.group("noun") not in _ONE_SITE
                or not _own_name(text, mentions, start, match.end())
            )
        ):
            found.append((start, match.end(), "sites"))
    return found


def _own_name(text: str, mentions: Sequence[Mention], start: int, end: int) -> bool:
    """Whether ``start:end`` is in the listing's own name: before a mark that ends the words
    before its first status ("Morehead State - Ashland Campus: Closed"), or after a mark
    that follows its last status ("Closed - Oak Ridge Campus"), the name running to the end.

    A school's own name can end with a site noun; a phrase there names the school, not a
    site of a district's.
    """
    statuses = [mention for mention in mentions if mention.kind != "revoke"]
    if not statuses:
        return False
    head = text[: statuses[0].start].rstrip()
    if head and head[-1] in ":-,|" and end <= len(head):
        return True
    after = -1  # where the words after the last mark past the last status start
    for mark in _MARK.finditer(text, statuses[-1].end, len(text.rstrip(_END_MARKS))):
        after = mark.end()
    return 0 <= after <= start


def _exceptions(
    text: str, mentions: Sequence[Mention], stops: Sequence[int], present: AbstractSet[str]
) -> list[tuple[int, int, _Form]]:
    """The exceptions that leave part of the school day out: "except Lincoln Elementary",
    "Lincoln Elementary excluded" (not "except essential staff"). ``present`` are the words of
    :data:`CARVE_WORDS` the text holds."""
    found: list[tuple[int, int, _Form]] = []
    for match in _EXCEPT.finditer(text):
        if (
            match.group().startswith(_LOOSE_EXCEPTS)
            and text[: match.start()].strip()
            and text[: match.start()].rstrip()[-1] in ".;!?|"
        ):
            continue  # "Closed today. Besides the snow, roads are icy.": no status's exception
        # (After "Exception:", the part starts after the colon.)
        after = match.end() + 1 if text.startswith(":", match.end()) else match.end()
        part = _part_after(text, mentions, after)
        if part and _left_out(part, match.group()):
            found.append((match.start(), match.end(), "except"))
    for match in _EXCLUDED.finditer(text) if present & _EXCLUDED_CUES else ():
        start = _phrase_start(text, stops, match.start())
        part = words(text, start, match.start())
        while part and part[0] in _LEADS:
            part.pop(0)
        if part and len(part) <= _MOST_WORDS and _left_out(part, match.group()):
            found.append((start, match.end(), "except"))
    return found


def _restrictions(
    text: str, mentions: Sequence[Mention], stops: Sequence[int]
) -> list[tuple[int, int, _Form]]:
    """The restrictions with "only" to some of a district's schools: "Lincoln Elementary only",
    "only at Lincoln Elementary" (not "essential personnel only", "remote learning only")."""
    found: list[tuple[int, int, _Form]] = []
    for match in _ONLY.finditer(text):
        if _inside_mention(mentions, match.start(), match.end()):
            continue  # "paved roads only": a status's own words
        if match.group("prep") is not None:
            part = _part_after(text, mentions, match.end())
            if part and _a_place(part):
                found.append((match.start(), match.end(), "only"))
            continue
        if _service_before(text, stops, match.start()):
            continue  # "Online services only", "Remote learning only": no place
        start = _phrase_start(text, stops, match.start())
        part = words(text, start, match.start())
        while part and part[0] in _LEADS_ONLY:
            part.pop(0)
        if part and _a_place(part):
            found.append((start, match.end(), "only_after"))
    return found


def _service_before(text: str, stops: Sequence[int], only: int) -> bool:
    """Whether the word right before an "only" at ``only`` is one of :data:`_SERVICES` that
    the part it restricts holds: then no place is (see :func:`_a_place`). A quick look, before
    the phrase is read."""
    if text[only - 1 : only] != " ":
        return False
    start = text.rfind(" ", 0, only - 1) + 1
    word = text[start : only - 1]
    if word not in _SERVICES or word in _LEADS_ONLY or not word.isalpha():
        return False
    stop = bisect_right(stops, only)
    return not stop or stops[stop - 1] <= start  # (no status or date ends inside the word)


def _part_after(text: str, mentions: Sequence[Mention], start: int) -> list[str]:
    """The words of the part an exception leaves out, from ``start`` to the end of its phrase."""
    end = len(text)
    mark = _MARK.search(text, start)
    if mark is not None:
        end = mark.start()
    for mention in mentions:
        if start <= mention.start < end:
            end = mention.start
            break
    found = words(text, start, end)
    if found[:1] == ["where"] and found[1:2] and found[1] in _NOTED:
        return found[:2]  # "except where noted": the schools noted
    part: list[str] = []
    for word in found:
        if word in _ENDS:
            break
        part.append(word)
    while part and part[0] in _LEADS:
        part.pop(0)
    return part[:_MOST_WORDS]


def _left_out(part: list[str], cue: str) -> bool:
    """Whether an exception that leaves out ``part`` leaves out part of the school day."""
    if cue.startswith("other") and part[0] in _NOT_PARTS:
        return False  # "Other than that, normal schedule"
    if part[0] in _NONE:
        return False  # "Exceptions: none"
    for index, word in enumerate(part):
        pair = f"{word} {part[index + 1]}" if index + 1 < len(part) else ""
        scope = SCOPES.get(pair) or SCOPES.get(word)
        if word in _KEPT_WORDS or scope in _KEPT_SCOPES:
            return False  # "except essential staff", "except central office"
    return True


def _day_left_out(text: str, groups: Sequence[DateGroup], start: int) -> bool:
    """Whether the part an exception leaves out is a day: "except Wednesday", "except on 1/21"."""
    for group in groups:
        if group[GROUP_END] <= start:
            continue
        between = words(text, start, group[GROUP_START])
        return all(word in _DATE_LEADS for word in between)
    return False


def _phrase_start(text: str, stops: Sequence[int], end: int) -> int:
    """Where the phrase that ends at ``end`` starts: after the last mark, status or date before
    it (``stops`` are where the statuses and the dates end, in order)."""
    marked = _UP_TO_MARK(text, 0, end)
    start = 0 if marked is None else marked.end()
    stop = bisect_right(stops, end)
    return max(start, stops[stop - 1]) if stop else start


def _inside_mention(mentions: Sequence[Mention], start: int, end: int) -> bool:
    for mention in mentions:  # noqa: SIM110 - (a loop costs less than any(), per call)
        if mention.start < end and start < mention.end:
            return True
    return False


def _name_word(word: str) -> bool:
    """Whether ``word`` can be a word of a place's name: "Lincoln", "Astrozon", "Moines"."""
    return word.isalpha() and len(word) > 1 and word not in _NOT_NAMES


def _a_place(part: list[str]) -> bool:
    """Whether a status restricted to ``part`` ("Lincoln Elementary only") is restricted to
    some of a district's schools, not to a service or to some of its people."""
    if len(part) > _MOST_WORDS or any(word in _SERVICES for word in part):
        return False
    last = part[-1]
    pair = " ".join(part[-2:]) if len(part) > 1 else ""
    scope = SCOPES.get(pair) or SCOPES.get(last)
    if scope == "partial":
        return True  # "high school only", "elementary only"
    if scope is not None and scope != "school" and last not in _SITE_NOUNS:
        return False  # "staff only", "buses only"
    if last in _SITE_NOUNS or scope == "school":
        # "Lincoln school only", "east campus only"; not "school only", "students only".
        return any(_name_word(word) for word in part[:-1]) and all(
            _name_word(word) or word in _JOINERS for word in part[:-1]
        )
    return all(_name_word(word) or word in _JOINERS for word in part) and _name_word(part[0])


def _named_site(named: list[str]) -> bool:
    """Whether the words before a site noun name some of a district's sites: "PTEC, Astrozon
    and Howard campuses", "Des Moines locations"; not "all campuses" or "our campus"."""
    if len(named) > _MOST_NAME_WORDS or named[0] in _EVERY_SITE:
        return False
    if named[0] in _LEVELS and all(word in _LEVELS for word in named):
        return True  # "Elementary campuses closed", "High school campus closed"
    return _name_word(named[0]) and all(_name_word(word) or word in _JOINERS for word in named)


def _target(  # noqa: PLR0913, PLR0917 - the text's parts, and the phrase
    text: str, mentions: Sequence[Mention], stops: Sequence[int], start: int, end: int, form: _Form
) -> int | None:
    """The status a phrase at ``start:end`` limits, in its sentence.

    A phrase that comes before its status, as a subject does ("North campus
    closed", "All schools except Lincoln are closed"), limits the status right
    after it; any other limits the nearest status before it in the sentence,
    or failing that the first after it.
    """
    sentence_start = _sentence_start(text, start)
    if form == "except" and sentence_start > 0 and not words(text, sentence_start, start):
        # "All schools closed. Exception: Lincoln Elementary.": an exception that opens its
        # sentence is to the status before it.
        sentence_start = _sentence_start(text, sentence_start - 1)
    sentence_end = _sentence_end(text, end)
    before: int | None = None
    after: int | None = None
    inside: int | None = None
    for index, mention in enumerate(mentions):
        if mention.kind == "revoke":
            continue
        if sentence_start <= mention.start and mention.end <= start:
            before = index
        elif end <= mention.start < sentence_end and after is None:
            after = index
        elif start <= mention.start and mention.end <= end and inside is None:
            inside = index  # "All schools closed but Lincoln": the status inside the phrase
    chosen: int | None = inside if inside is not None else before if before is not None else after
    if (
        form in _SUBJECTS
        and after is not None
        and _MARK.search(text, end, mentions[after].start) is None
        and len(words(text, end, mentions[after].start)) <= 3  # noqa: PLR2004 - "will be on a"
    ):
        chosen = after
    if chosen is None:
        return None
    if form == "place":
        low, high = (
            (mentions[chosen].end, start) if chosen == before else (end, mentions[chosen].start)
        )
        between = words(text, low, high)
        if chosen != before:
            between += words(text, _phrase_start(text, stops, start), start)
        if any(_of_weather(word) for word in between):
            # "Closed due to flooding north of Route 9", "Snow north of I-70, closed": the
            # weather's place.
            return None
    return chosen


# Words that say where weather goes or what it does ("storm moving north of us"), and the
# damage it does ("power outage in some areas").
_WEATHER_VERBS = frozenset(
    {
        "moving", "moves", "heading", "headed", "expected", "forecast", "power", "outage",
        "outages", "blackout", "blackouts", "electricity", "electric", "heating", "gas", "leak",
        "damage", "damaged", "impassable", "flooded", "downed", "trees", "lines",
    }
)  # fmt: skip


def _of_weather(word: str) -> bool:
    """Whether a word between a status and a place names a cause or the weather, whose place
    the place is: "due", "snow", "storm moving", "power"."""
    return (
        word in CAUSES
        or word in _WEATHER_VERBS
        or bool(weather_hints(word) & (WEATHER_START | CAUSE_START))
    )


def _limits(mention: Mention) -> bool:
    """Whether a mention is a status, or "open", that stands as the school's."""
    return (
        mention.kind in _LIMITED
        and mention.dropped is None
        and not mention.revoked
        and mention.narrowed is None
        and not mention.elsewhere  # "offices open"
    )


def _sentence_start(text: str, position: int) -> int:
    start = 0
    for mark in _SENTENCE_END.finditer(text, 0, position):
        start = mark.end()
    return start


def _sentence_end(text: str, position: int) -> int:
    mark = _SENTENCE_END.search(text, position)
    return len(text) if mark is None else mark.start()
