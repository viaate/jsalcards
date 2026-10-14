"""What a status word is about: the school's day, or something else that is late or off.

"Delayed", "cancelled" and "closed" say nothing of the school when their
subject is something else: "Payroll delayed", "Graduation delayed", "School
pictures cancelled", "Lightning delay", "Weather delay at the stadium". Nor
does a delay of the end of the day: "Dismissal delayed", "Delayed dismissal due
to severe weather", "Afternoon dismissal delayed 30 minutes" hold students
past the bell, which is no late start. Such a status word becomes a side note
that is ``ambiguous`` (see :func:`settle_subjects`): the listing reads
``other`` at a low confidence unless another status in it is the school's.

The subject is the noun phrase right before the status word in its clause,
read back from the word: past verbs and their helpers ("is being", "will
be"), verbs whose object the status is ("District announces 2 hour delay",
"BPS will be observing an early release"; see :data:`_OBJECT_VERBS`), days,
times and lengths ("Monday", "2 hour"), and a phrase after a
preposition ("Classes at Lincoln cancelled" is about the classes, "Opening of
the new school delayed" about an opening). Its last word, the head, decides:

* no subject at all ("Delayed", "Tomorrow: 2 hour delay"), or a word that
  qualifies the status rather than naming its subject ("No", "Possible",
  "Now", "Due to snow") leaves the status as it is;
* the school and the start of its day ("School", "All classes", "Opening",
  "Start", "Arrival", "Lincoln Elementary", "Oak Academy", "District") leave
  it as it is, and so does any noun the scope rules read (offices, buses,
  activities, part of the program: see :data:`~snowlight.classify.lexicon.SCOPES`),
  which they turn into their own notes;
* a delay named after the weather that causes it ("Snow delay", "Fog delay",
  "Weather delay") is the school's, but not the delays of games and meets
  ("Lightning delay", "Rain delay");
* the end of the day ("Dismissal", "Release", "Pickup") makes a delay a held
  dismissal, and is no school day's status with any other word ("Trash pickup
  cancelled");
* the first day or the start of a year or a term ("First day of school
  delayed", "Start of the school year delayed", "Opening of the new school
  delayed") is no day's status;
* a single class ("Prenatal class cancelled"), classes held in person ("In-person
  classes cancelled": they may be held another way), and any other noun
  ("Payroll", "Results", "Picture day", "School pictures", where "school" only
  says which pictures) make the status about that noun.

A name the parser does not know reads as any other noun: "Lincoln delayed" is
``other``, as "Payroll delayed" is, while "Lincoln Elementary delayed" names a
school. One that has the status as the object of a verb names the school:
"BPS will be observing an early release schedule" and "FPS is operating on a
2 hour delay" are the school's, as who observes a schedule or runs on a delay
is. A word after "delayed" that it describes ("Delayed dismissal",
"Delayed bus routes", "Delayed payroll") decides the same way, and so does a
noun after "delay in" or "delay of" ("Delay in dismissal"). A label before a
word that calls something off names what is called off ("School Pictures:
Cancelled"); a label before any other status word is the listing's own name
("Lincoln: Closed"), as the parser reads labels everywhere.

A delay after the morning ("Delayed this afternoon") is no late start either,
and nor is a closure for good: "Closed permanently", "Closed for renovation".
"""

import re
from collections.abc import Sequence
from typing import NamedTuple

from snowlight.classify.dates import names_day
from snowlight.classify.lexicon import (
    CAUSES,
    CONDITION_OPENERS,
    CONDITIONALS,
    FILLERS,
    HEDGES,
    HEDGES_AFTER,
    MAKE_UP_WORDS,
    MODIFIERS,
    NEGATIONS,
    ORDINARY,
    REGION_STOPS,
    SCOPES,
    SUPERSEDED,
    SUPERSEDING,
    SUPERSEDING_WITH,
    UNVERIFIED,
)
from snowlight.classify.mentions import SCOPE_NOTES, Mention
from snowlight.classify.text import by_char

# Helpers of a verb, and words that only point at or count the subject: read past them.
_GLUE = frozenset(
    {
        "is", "are", "was", "were", "be", "been", "being", "has", "have", "had", "having",
        "will", "shall", "does", "do", "did", "get", "gets", "got", "getting", "also",
        "again", "still", "currently", "officially", "temporarily", "hereby", "already",
        "just", "the", "a", "an", "our", "their", "its", "this", "that", "these", "those",
        "any", "every", "each", "all", "next", "coming", "following", "run", "runs",
        "running", "ran", "go", "goes", "going",
        "went", "remain", "remains", "remained", "stay", "stays", "stayed", "staying",
        "entire", "whole", "move", "moves", "moving", "switch", "switches", "shift", "shifts",
        "shifted", "shifting", "transition", "transitions", "transitioned", "transitioning",
        "convert", "converts", "revert", "reverts", "reverted", "reverting", "placed", "put",
        "replace", "replaces", "follow", "follows", "followed", "begin", "begins", "using",
        "experience", "experiences", "experiencing",
    }
)  # fmt: skip
# Verbs whose object is the status: who announces, observes or follows a status is the school
# or the district that has it, whatever its name ("BPS will be observing an early release
# schedule", "District announces 2 hour delay", "Schools will begin on a 2 hour delay").
_OBJECT_VERBS = frozenset(
    {
        "announce", "announces", "announced", "announcing", "observe", "observes", "observed",
        "observing", "implement", "implements", "implemented", "implementing", "declare",
        "declares", "declared", "declaring", "issued", "issuing", "calls", "called", "calling",
        "enact", "enacts", "enacted", "enacting", "adopt", "adopts", "adopted", "adopting",
        "utilize", "utilizes", "utilizing", "posted", "operate", "operates", "operating",
        "operated",
    }
)  # fmt: skip
# Times of the day and the units of a length: "Tuesday morning delayed", "2 hour delay".
_TIMES = frozenset(
    {
        "morning", "afternoon", "evening", "night", "tonight", "am", "pm", "noon", "midday",
        "hour", "hours", "hr", "hrs", "minute", "minutes", "min", "mins", "half", "one", "two",
        "three", "four", "five", "six", "ten", "fifteen", "twenty", "thirty", "forty",
        "forty-five", "fifty", "sixty", "ninety", "o'clock", "oclock",
    }
)  # fmt: skip
# Words that open a phrase the subject cannot be inside: "Classes at Lincoln cancelled".
_PREPOSITIONS = frozenset(
    {
        "for", "at", "in", "of", "on", "across", "throughout", "from", "to", "with", "by",
        "near", "inside", "outside", "within", "past", "after", "before", "until", "till",
        "til", "during", "per", "via", "into", "onto", "under", "over", "around", "between",
        "among", "through", "thru", "since", "except", "excepting", "excluding", "including",
        "besides", "but", "than",
    }
)  # fmt: skip
# Words that end the subject's phrase on their side: a joining word, or a word that qualifies
# the status itself, which the rules for it read ("No delay", "Possible closure", "Now
# delayed", "Due to snow, delayed", "Only closed today", "No longer closed").
_ENDS = (
    frozenset(
        {
            "only",
            "longer",
            "and",
            "or",
            "nor",
            "plus",
            "then",
            "yet",
            "so",
            "while",
            "however",
            "as",
            "which",
            "who",
            "whom",
            "whose",
            "where",
            "there",
            "here",
            "instead",
            "rather",
            "update",
            "updated",
            "status",
            "correction",
            "announcement",
            "notice",
            "alert",
            "reminder",
            "note",
            "news",
            "breaking",
            "attention",
            "important",
            "urgent",
            "if",
            "when",
            "whenever",
            "unless",
            "otherwise",
        }
    )
    | NEGATIONS
    | HEDGES
    | HEDGES_AFTER
    | CONDITIONALS
    | CONDITION_OPENERS
    | CAUSES
    | SUPERSEDING
    | SUPERSEDED
    | frozenset(SUPERSEDING_WITH)
    | MAKE_UP_WORDS
    | UNVERIFIED
    | ORDINARY
)
# The school, its day and its people as a subject: "Schools delayed", "Opening delayed",
# "We are delayed", "All locations closed".
_SCHOOL_SUBJECTS = frozenset(
    {
        *(word for word, scope in SCOPES.items() if scope == "school" and " " not in word),
        "opening", "openings", "start", "starts", "start-up", "startup", "arrival", "arrivals",
        "session", "sessions", "reporting", "report", "entry", "bell", "bells", "doors",
        "schedule", "schedules", "it", "we", "they", "everything", "everyone", "everybody",
        "us", "both", "location", "locations", "site", "sites", "classroom", "classrooms",
        "center", "centers", "centre", "centres", "complex", "learning", "operations",
        # Part of the district, which the rules for part of a district read (see
        # snowlight.classify.partial): "Northern part of the district closed".
        "part", "parts", "portion", "portions", "area", "areas", "section", "sections", "zone",
        "zones", "region", "regions", "side", "branch", "branches", "others", "rest",
        "districtwide", "district-wide", "countywide", "county-wide", "systemwide",
        "system-wide", "schoolwide", "school-wide", "campuswide", "campus-wide", "statewide",
        "state-wide",
        # The status words themselves: "2 hour delay for Lincoln cancelled" is about the delay.
        "delay", "delays", "closure", "closures", "closing", "closings", "cancellation",
        "cancellations", "nti", "ami", "e-learning", "elearning", "virtual", "remote",
        "online",
        # The words that end a school's or a district's name: "Oak Academy delayed".
        "academy", "academies", "institute", "prep", "preparatory", "montessori", "county",
        "counties", "parish", "parishes", "borough", "isd", "usd", "cusd", "csd", "sd",
        "unified", "consolidated", "regional", "township", "local", "magnet", "charter",
        "christian", "catholic", "lutheran", "college", "colleges", "university", "seminary",
        "elem", "es", "ms", "hs", "jhs", "jh", "shs", "jr", "sr", "ps",
        # Who calls school off, as the subject of an active verb: "Superintendent cancels
        # classes" (the object after the verb is what is called off; see revoke._AGENTS).
        "superintendent", "superintendents", "board", "administration", "administrators",
        "officials", "principal", "principals",
    }
)  # fmt: skip
# Weather that can delay a school's start, named before "delay": "Snow delay", "Fog delay".
_WEATHER = frozenset(
    {
        "snow", "snowy", "snowfall", "snowstorm", "ice", "icy", "sleet", "freezing", "frost",
        "frozen", "fog", "foggy", "cold", "chill", "windchill", "wind", "winds", "winter",
        "wintry", "storm", "storms", "weather", "weather-related", "storm-related",
        "inclement", "blizzard", "flood", "flooding", "flooded", "hurricane", "tropical",
        "power", "outage", "heat", "emergency", "precautionary", "hazardous", "slick",
        "slippery", "visibility", "conditions",
    }
)  # fmt: skip
# Words before a status that say which kind it is, not what it is about: "a full closing",
# "an emergency early dismissal", "planned delay".
_STATUS_KINDS = frozenset(
    {
        "planned", "unplanned", "mandatory", "special", "additional", "extended", "modified",
        "full", "complete", "total", "temporary", "official", "unexpected", "immediate",
        "short", "brief", "slight", "minor", "district", "early", "late", "midday",
        "mid-day", "unscheduled",
    }
)  # fmt: skip
# The end of the school day: a delay of it holds students past the bell.
_DISMISSAL = frozenset(
    {"dismissal", "dismissals", "release", "releases", "pickup", "pick-up", "pickups", "dismiss"}
)
# The first or last day, or the start of a year or a term: no day's status.
_FIRST_OR_LAST = frozenset({"first", "last", "final", "1st"})
_CALENDAR = frozenset(
    {"year", "years", "semester", "semesters", "term", "terms", "trimester", "quarter",
     "season", "new"}
)  # fmt: skip
# Kinds of day that are a status, or the day itself: "Snow day", "NTI day", "School day".
_STATUS_DAYS = frozenset(
    {
        "snow", "weather", "inclement", "cold", "ice", "storm", "emergency", "calamity", "nti",
        "ami", "e-learning", "elearning", "remote", "virtual", "learning", "instruction",
        "instructional", "school", "flex", "flexible", "fid", "makeup", "make-up",
    }
)  # fmt: skip
# How a class is held: "In-person classes cancelled" may move them online.
_IN_PERSON = frozenset({"in-person", "face-to-face", "on-site", "onsite", "in-building"})
# Two- and three-word forms read as one word: "in person classes", "face to face classes".
_PAIRED = re.compile(r"\b(?:in person|face to face|on site)\b", re.ASCII)
# Weather that delays games and meets, not a school's start: "Lightning delay", "Rain delay".
_GAME_WEATHER = frozenset({"lightning", "thunder", "thunderstorm", "thunderstorms", "rain"})
_REACH = 80  # how far back the subject's phrase is read
# Words after "delay" that open what the delay is of or where it is: "Delay in dismissal",
# "Weather delay at the stadium".
_PLACE_PREPOSITIONS = frozenset({"in", "of", "to", "at", "during"})
# Scopes a place after "delay at" can have and still be the school's: "at the high school".
_SCHOOL_PLACES = frozenset({"school", "partial"})
_DIGIT = re.compile(r"\d", re.ASCII)
# What can follow "delayed" without being what it describes: "delayed until 10", "delayed
# Wednesday", "delayed again", "delayed due to ice".
_AFTER_DELAYED = (
    _GLUE | _TIMES | _PREPOSITIONS | _ENDS | FILLERS | REGION_STOPS | _SCHOOL_SUBJECTS
    | frozenset(MODIFIERS)
    | frozenset(
        {
            "indefinitely", "further", "notice", "today", "tomorrow", "dly", "open", "opens",
            "begin", "begins", "starting", "anymore",
        }
    )
)  # fmt: skip

type _Reading = str | None
"""What a subject makes of a status: ``None`` (leave it), ``"other"`` (about something
else, or a held dismissal), ``"unclear"`` (a status of the school, but not which one), or
a scope noun's word for its note (``"bus"``)."""


def settle_subjects(text: str, mentions: Sequence[Mention]) -> None:
    """Turn each status word whose subject is not the school into an ``ambiguous`` side note.

    ``text`` is the normalized text the ``mentions`` were found in, in order.
    Called before anything else reads them (see the module notes).
    """
    low = 0
    for mention in mentions:
        kind = mention.kind
        if kind in _LOOKED_AT and mention.dropped is None:
            start = mention.start
            # A quick look first: a word right before the status, or one right after a delay
            # word or a closure that can tell what it is about (see _reading). (The kinds in
            # the order they are most often met.)
            if start > low + 1 and text[start - 1] == " " and text[start - 2] not in _MARKS:
                look = kind != "ambiguous" or mention.revokes == "cancel"
            elif kind == "closed":
                look = text.startswith(_LASTING_STARTS, mention.end)
            elif kind == "delayed":
                # (Every word these looks start with follows a space: a table by the character
                # after the space holds the few that can start there.)
                end = mention.end
                second = text[end + 1 : end + 2]
                look = text.startswith(" ", end) and (
                    text.startswith(_AFTER_NOUN_BY_SECOND.get(second, ()), end)
                    or (
                        text.endswith("delayed", start, end)
                        and not text.startswith(_PLAIN_AFTER_BY_SECOND.get(second, ()), end)
                    )
                )
            elif kind == "ambiguous":
                # "School Pictures: Cancelled": maybe a label before the word
                look = start > low and mention.revokes == "cancel"
            else:
                look = False  # an early dismissal with no word before it
            if look:
                reading = _reading(text, mention, low)
                if reading is not None:
                    _side_note(mention, reading)
        low = mention.end


_CHECKED = frozenset({"closed", "delayed", "early_dismissal"})
# ... and an "ambiguous" word that can call a status off ("cancelled"), when it does.
_LOOKED_AT = _CHECKED | {"ambiguous"}
# The words that most often follow "delayed" and say nothing of what it is about (a quick
# look: see _described).
_PLAIN_AFTER_DELAYED = (
    " until ", " til ", " till ", " due ", " today ", " tomorrow ", " because ", " by ", " one ",
    " two ", " three ", " an ", " a ", " 1", " 2", " 3", " 9", " 90 ",
)  # fmt: skip
# The closure words that take a subject before them: "Payroll office closed", "Track closed".
_CLOSED_WORDS = ("closed", "closing", "closure", "shut")
_MARKS = frozenset(",;:.!?|()[]-/")
_LABEL_MARKS = frozenset(":-")  # (what ends a label before a status: "Picture day: cancelled")
# (Where _LASTING can match: a quick look.)
_LASTING_STARTS = (" permanently", ", permanently", " for ", ", for ")


# Words after a closure that make it no day's status: the building is gone or being rebuilt.
_LASTING = re.compile(
    r",? (?:permanently|for good|for (?:the |a |an )?(?:renovations?|construction|remodel(?:ing)?"
    r"|demolition|rebuilding|reconstruction))\b",
    re.ASCII,
)


def _side_note(mention: Mention, reading: str) -> None:
    mention.scope_rule = "none"
    mention.needs_school_noun = False
    if reading == "unclear":
        # "In-person classes cancelled": maybe no school at all, maybe classes held another
        # way. Unclear as a bare "cancelled" is (a status beside it that school is held
        # conflicts with it), but never a closure by its noun.
        mention.kind = "ambiguous"
        mention.note = "ambiguous"
        return
    mention.kind = "note"
    mention.note = "ambiguous" if reading == "other" else SCOPE_NOTES[SCOPES[reading]]
    mention.negatable = False
    mention.revokes = None
    mention.delay = mention.opens_at = mention.dismissal = mention.early = None


def _reading(text: str, mention: Mention, low: int) -> _Reading:  # noqa: PLR0911 - one per form
    """What the words before ``mention`` (from ``low``) and after it make of it."""
    start, end = mention.start, mention.end
    kind = mention.kind
    if kind == "delayed":
        after = _after_delay(text, mention)
        if after is not None:
            return after
    elif kind == "closed":
        if text.startswith(_LASTING_STARTS, end) and _LASTING.match(text, end) is not None:
            return "other"  # "Closed permanently", "Closed for renovations": no day's status
        if not text.startswith(_CLOSED_WORDS, start):
            return None  # "No school", "Not in session", "Snow day": no subject before them
    # The subject is right before the words, past spaces only: none after a mark or at a
    # mention (a quick look before the words are read).
    last = start - 1
    while last >= low and text[last] == " ":
        last -= 1
    if last < low:
        return None
    if text[last] in _MARKS:
        return _label_reading(text, low, last) if kind == "ambiguous" else None
    window = text[max(low, start - _REACH) : start]
    if (
        (  # (as _changed_to reads the last words: quick looks at the window's end)
            " to " in (tail := window[-_CHANGE_REACH:])
            or " into " in tail
            or " for " in tail
            or " with " in tail
            or " of " in tail
        )
        and not text.startswith(_VERB_STARTS, start)
        and _changed_to(_WORDS.findall(window))
    ):
        # "Closure cut to a 2 hour delay", "Closed today, amended to a 2 hour delay": the
        # status is what something was changed to, with no subject of its own here (not a
        # verb's "to": "Arc to open at 12 PM", "Next attempt to open at 10").
        return None
    return _window_reading(window)


def _label_reading(text: str, low: int, mark: int) -> _Reading:
    """What a label before a word that calls something off makes of it: "School Pictures:
    Cancelled" names what is called off, and the label's last word is what it is.

    The scope rules read a label that names the school or a noun they know ("Lincoln
    Elementary: Cancelled", "Field trip: cancelled"); this reads only one that names
    something else.
    """
    if text[mark] not in _LABEL_MARKS or mark <= low:
        return None
    return "other" if _window_reading(text[max(low, mark - _REACH) : mark]) == "other" else None


# The text before a status up to the last mark that ends a clause in it (the greedy run finds
# the last). "-" and "/" end one only as a word of their own: "closed - payroll delayed".
_LAST_MARK = re.compile(r"(?s).*(?:[,;:.!?|()\[\]]|\s[-/]+(?=\s))", re.ASCII)


class _Readings(dict[str, _Reading]):
    """What the words before a status make of it, worked out once: listings repeat the words
    before their statuses ("all schools "). Only the words of the status's own clause count:
    those after the last mark that ends one."""

    def __missing__(self, window: str) -> _Reading:
        mark = _LAST_MARK.match(window)
        subject = _subject(window if mark is None else window[mark.end() :])
        reading = None if subject is None else _judge(subject)
        if len(self) >= _MOST_WINDOWS:
            self.clear()  # a bound on memory; a reading is the same worked out again
        self[window] = reading
        return reading


_window_reading = _Readings().__getitem__


class _Subject(NamedTuple):
    """The subject before a status word: its head, the words before the head in its phrase,
    the words of the phrases after a preposition between the two, and every word of the
    clause before the status word."""

    head: str
    modifiers: list[str]
    objects: list[str]
    clause: list[str]
    agent: bool  # the status is the object of a verb after the subject (see _OBJECT_VERBS)


def _subject(window: str) -> _Subject | None:
    """The subject in the words of a clause before a status word (see :class:`_Subject`)."""
    if " " in window and ("person" in window or "face" in window or "site" in window):
        window = _PAIRED.sub(lambda match: match.group().replace(" ", "-"), window)
    tokens = _WORDS.findall(window)
    if tokens and (_then_status(tokens) or _chance_of(tokens)):
        # "Closed, later a 2 hour delay": a second status, in no stated order; "2 hour delay.
        # Possibility of closure": the school's status, only possible (see parse._dropped).
        return None
    phrase: list[str] = []  # the words of the subject's phrase, last word first
    objects: list[str] = []
    agent = False
    for token in reversed(tokens):
        role = _role(token)
        if role == _CONTENT:
            phrase.append(token)
        elif role == _GLUE_WORD:
            continue
        elif role == _END or (phrase and role in _ENDS_A_PHRASE):
            # "Monday payroll delayed": a day before the phrase ends it, and so does a verb
            # whose object it is ("District announces payroll delayed": the payroll is).
            break
        elif role == _PREPOSITION and phrase:
            objects += phrase
            phrase = []
        elif role == _OBJECT_VERB:
            agent = True  # with no phrase yet, the status is its object: "BPS announces delay"
    if not phrase:
        return None
    return _Subject(phrase[0], phrase[:0:-1], objects, tokens, agent)


_WORDS = re.compile(r"[a-z0-9&]+(?:['/-][a-z0-9]+)*", re.ASCII)
# Words that put a status after another with no order stated, when the status (or an
# article, then the status) follows them: "Closed, later a 2 hour delay". Before anything
# else they are a subject's words: "Check back later for updates on the closure of Main St".
_THEN_WORDS = frozenset({"later", "afterwards", "afterward", "subsequently"})


def _then_status(tokens: list[str]) -> bool:
    """Whether the last word before a status, past an article, is one of :data:`_THEN_WORDS`."""
    position = len(tokens) - 1
    while position > 0 and tokens[position] in _ARTICLES:
        position -= 1
    return tokens[position] in _THEN_WORDS


# Nouns of the odds of a status, before "of" or "for" and the status: "possibility of closure".
_CHANCE_NOUNS = frozenset(
    {"possibility", "possibilities", "chance", "chances", "odds", "likelihood", "probability"}
)


def _chance_of(tokens: list[str]) -> bool:
    """Whether the last words before a status, past an article, are a noun of its odds and
    "of" or "for": "possibility of closure", "chance of a delay"."""
    position = len(tokens) - 1
    while position > 0 and tokens[position] in _ARTICLES:
        position -= 1
    return (
        position > 0 and tokens[position] in {"of", "for"} and tokens[position - 1] in _CHANCE_NOUNS
    )


def _changed_to(tokens: list[str]) -> bool:
    """Whether the words right before a status make it what something was changed to: a verb,
    then "to" or "into", then an article at most ("cut to a", "amended to", "walked back to",
    "developing into a"); not a time's or a place's "to" ("prior to 10 am", "next to")."""
    position = len(tokens) - 1
    while position >= 0 and tokens[position] in _ARTICLES:
        position -= 1
    if position > 0 and tokens[position] in _TRADED_FOR:
        # "Closure swapped for a 2 hour delay", "substituted with", "dropped in favor of"
        if tokens[position] == "of" and tokens[position - 1 : position] in (["favor"], ["favour"]):
            position -= 2  # (past "in favor")
        if position > 1 and tokens[position - 1] in _PARTICLES:
            position -= 1  # (past "over": "passed over for")
        return position > 0 and (
            tokens[position - 1].endswith("ed") or tokens[position - 1] in {"set", "put"}
        )
    return (
        position > 0
        and tokens[position] in _CHANGED_TO
        and tokens[position - 1] not in _NOT_CHANGED_TO
        and not tokens[position - 1][0].isdigit()
    )


_TRADED_FOR = frozenset({"for", "with", "of"})  # after a verb that trades one status for another
# How far from its end a window that _changed_to can read as a change holds its "to", "into",
# "for", "with" or "of": the word, then an article at most (" with the ").
_CHANGE_REACH = 11
_PARTICLES = frozenset({"over", "aside", "off", "out", "up", "down", "back", "away"})


_ARTICLES = frozenset({"a", "an", "the"})
# Status words that are verbs after "to" ("to open at 10", "to close early", "to delay").
_VERB_STARTS = ("open", "close", "closing", "dismiss", "release", "start", "begin", "delay ",
                "cancel", "resume", "reopen", "shut", "end")  # fmt: skip
_CHANGED_TO = frozenset({"to", "into"})
# Words before "to" that make it no change's: "prior to", "due to", "up to", "next to".
_NOT_CHANGED_TO = frozenset(
    {"prior", "due", "next", "according", "owing", "close", "closer", "adjacent",
     "related", "subject", "thanks", "compared", "similar", "addition", "regard", "respect",
     "listen", "attention", "welcome", "go", "goes", "went", "come", "comes", "came", "drive",
     "travel", "walk", "ride", "report", "reports", "return", "returns", "returning"}
)  # fmt: skip
_JOINED = re.compile(r"[-/]", re.ASCII)


_CONTENT, _GLUE_WORD, _DATED, _PREPOSITION, _END, _OBJECT_VERB = range(6)
_ENDS_A_PHRASE = frozenset({_DATED, _OBJECT_VERB})  # (once the phrase has a word)
# A district's letter and number, which end its name: "Hillsboro R-3", "Bayless C-4".
_DISTRICT_CODE = re.compile(r"[a-z]{1,2}-\d{1,3}", re.ASCII)


class _Roles(dict[str, int]):
    """What each word is to a subject's phrase, worked out once (listings reuse their words)."""

    def __missing__(self, token: str) -> int:
        if token in _GLUE:
            role = _GLUE_WORD
        elif token in _OBJECT_VERBS:
            role = _OBJECT_VERB
        elif _DISTRICT_CODE.fullmatch(token) is not None:
            role = _CONTENT  # "Hillsboro R-3": a district's number ends its name
        elif _dated(token):
            role = _DATED
        elif token in _PREPOSITIONS:
            role = _PREPOSITION
        elif token in _ENDS:
            role = _END
        else:
            role = _CONTENT
        if len(self) >= _MOST_WORDS:
            self.clear()  # a bound on memory; a word's role is the same worked out again
        self[token] = role
        return role


_MOST_WORDS = 65536
_MOST_WINDOWS = 16384
_role = _Roles().__getitem__


def _dated(token: str) -> bool:
    """Whether ``token`` is a day, a time or a length: "Monday", "wed-thurs", "1/21", "2-hr"."""
    if token in _TIMES or _DIGIT.search(token) or names_day(token):
        return True
    if "-" in token or "/" in token:
        return all(part in _TIMES or names_day(part) for part in _JOINED.split(token) if part)
    return False


def _judge(subject: _Subject) -> _Reading:
    """What a subject makes of a status (see the module notes)."""
    head, modifiers, objects, clause, agent = subject
    if "/" in head:
        head = head.rsplit("/", 1)[1]  # "classes/activities": the last of a list
    head = head.removesuffix("'s")
    if _DISTRICT_CODE.fullmatch(head) is not None:
        return None  # "Hillsboro R-3 closed": a district's name
    if "-" in head and head not in _KNOWN_JOINED:
        # "School-Staff report at 10" (the staff's), "Part-Day closed" (a day's program).
        *joined, head = head.split("-")
        modifiers = [*modifiers, *joined]
        if SCOPES.get(head, "school") != "school":
            return head  # "Offices-Courthouse closed": the scope rules do not split the word
    if head in _STARTS and (
        not _CALENDAR.isdisjoint(modifiers) or not _CALENDAR.isdisjoint(objects)
    ):
        return "other"  # "Start of the school year delayed", "New school opening delayed"
    if head in {"day", "days"}:
        return _day(modifiers)
    if head in {"time", "times"} and modifiers:
        head, modifiers = modifiers[-1], modifiers[:-1]  # "start time", "dismissal time"
    if head in _DISMISSAL:
        # "Dismissal delayed": students held past the bell. "Trash pickup cancelled": not
        # the school's day. (A status's own words, "Early dismissal cancelled", are a
        # mention, with no subject read before the word that calls it off.)
        return "other"
    return _noun(head, modifiers, clause, agent=agent)


def _noun(  # noqa: PLR0911 - one per rule
    head: str, modifiers: list[str], clause: list[str], *, agent: bool = False
) -> _Reading:
    """What a subject whose head is a noun makes of a status (see the module notes)."""
    if head == "class" and modifiers:
        return "other"  # "Prenatal class cancelled": one class
    if head in _IN_PERSON or (head in _SCHOOL_SUBJECTS and not _IN_PERSON.isdisjoint(modifiers)):
        return "unclear"  # "In-person classes cancelled": they may be held another way
    if head in _SCHOOL_SUBJECTS or head in SCOPES or f"{_last(modifiers)} {head}" in SCOPES:
        return None  # the school, or a noun the scope rules read
    if head in _GAME_WEATHER:
        return "other"
    if head in _WEATHER or head in MODIFIERS or head in _STATUS_KINDS:
        return None
    if _names_other_scope(clause):
        # "Adult services closed", "All activities & worship cancelled", "Teacher in-service
        # cancelled": the scope rules read the noun they know.
        return None
    # "BPS will be observing an early release schedule", "FPS is operating on a 2 hour delay":
    # who has the status by name is the school.
    return None if agent else "other"


# Words joined by a hyphen that are read whole.
_KNOWN_JOINED = frozenset(
    word
    for words in (_SCHOOL_SUBJECTS, SCOPES, _IN_PERSON, _WEATHER, _DISMISSAL, MODIFIERS)
    for word in words
    if "-" in word
)
# Heads that are the start of something: with a year or a term beside them, its first day.
_STARTS = frozenset(
    {"opening", "openings", "start", "starts", "start-up", "startup", "beginning", "arrival"}
)


def _names_other_scope(tokens: list[str]) -> bool:
    """Whether ``tokens`` hold a noun of a scope besides the school ("adult", "activities")."""
    for index, token in enumerate(tokens):
        scope = SCOPES.get(token)
        if scope is not None and scope != "school":
            return True
        if index and SCOPES.get(f"{tokens[index - 1]} {token}", "school") != "school":
            return True
    return False


def _last(modifiers: list[str]) -> str:
    return modifiers[-1] if modifiers else ""


def _day(modifiers: list[str]) -> _Reading:
    """A subject that is a day: the school's own ("Snow day"), or an event's ("Field day")."""
    if not modifiers:
        return None
    word = modifiers[-1]
    if word in _STATUS_DAYS:
        return None
    if word in SCOPES or f"{_last(modifiers[:-1])} {word}" in SCOPES:
        return None  # "Sports day cancelled": the scope rules read it
    return "other"  # "Field day", "Picture day", "First day of school"


def _after_delay(text: str, mention: Mention) -> _Reading:
    """What the words right after a delay word say it is about: "Delayed dismissal",
    "Delay in dismissal", "30 minute delayed dismissal", "Delayed bus routes", "Delayed
    payroll"."""
    start, end = mention.start, mention.end
    if text.endswith("delay", start, end):
        # (Only a word for the end of the day, or a preposition, can say what it is of.)
        if not text.startswith(_AFTER_NOUN_BY_SECOND.get(text[end + 1 : end + 2], ()), end):
            return None
        return _after_noun(_WORDS.findall(text[end : end + 48])[:5])
    if not text.endswith("delayed", start, end) or not text.startswith(" ", end):
        return None
    tokens = _WORDS.findall(text[end : end + 48])[:5]
    if not tokens:
        return None
    if _held_dismissal(tokens):
        return "other"  # "Delayed dismissal", "Delayed afternoon dismissal"
    # A length read with the delay leaves no word for "delayed" to describe.
    return None if mention.delay is not None else _described(tokens[0])


# The part of the day a delay cannot start school in.
_LATE_IN_THE_DAY = frozenset({"afternoon", "pm", "evening"})
# Where the words after the noun "delay" can say what it is of: "delay in dismissal", "delay
# dismissal", "delay afternoon dismissal", "delay at the stadium" (a quick look).
_AFTER_NOUN_STARTS = (
    " in ", " of ", " to ", " at ", " during ", " for ", " dismiss", " releas", " pick",
    " afternoon ", " pm ", " evening ", " school ", " student", " the ", " all ", " this ",
    " bus ", " car ", " parent", " end-of-day", " regular ", " normal ", " usual ",
    " today's ",
)  # fmt: skip
_AFTER_NOUN_BY_SECOND = by_char(_AFTER_NOUN_STARTS, 1)
_PLAIN_AFTER_BY_SECOND = by_char(_PLAIN_AFTER_DELAYED, 1)


def _held_dismissal(tokens: list[str]) -> bool:
    """Whether ``tokens`` open with the end of the day, as "afternoon dismissal" does, or
    with the afternoon alone ("delayed this afternoon": no late start)."""
    for token in tokens:
        if token in _DISMISSAL:
            return True
        if token not in _DISMISSAL_LEADS:
            return False
    return bool(tokens) and tokens[-1] in _LATE_IN_THE_DAY


# Words between a delay word and the end of the day it holds: "delayed afternoon dismissal".
_DISMISSAL_LEADS = frozenset(
    {
        "afternoon", "pm", "evening", "school", "student", "students", "the", "all", "today's",
        "this", "bus", "car", "parent", "end-of-day", "regular", "normal", "usual",
    }
)  # fmt: skip


def _after_noun(tokens: list[str]) -> _Reading:
    """What the words after the noun "delay" say it is of: "Delay in dismissal", "Weather
    delay at the stadium", "Delay during the game"; "Delay for all schools" is the school's."""
    if _held_dismissal(tokens):
        return "other"  # "Delay dismissal", "30 minute delay afternoon dismissal"
    first = tokens[0]
    if first not in _PLACE_PREPOSITIONS and first != "for":
        return None
    rest = [token for token in tokens[1:] if token not in _GLUE]
    if not rest:
        return None
    if _held_dismissal(rest):
        return "other"  # "Delay in dismissal", "30 minute delay for dismissal"
    if first == "for":
        return None  # "Delay for all schools", "Delay for buses" (see parse._scope_after)
    scope = SCOPES.get(" ".join(rest[:2])) or SCOPES.get(rest[0])
    return "other" if scope is not None and scope not in _SCHOOL_PLACES else None


def _described(word: str) -> _Reading:
    """What the word after "delayed" makes of it when "delayed" describes it."""
    if (
        word in _AFTER_DELAYED
        or len(word) < 3  # noqa: PLR2004 - a letter or a short form: "w/", "pm"
        or _DIGIT.search(word)
        or names_day(word)
        or word in _WEATHER
    ):
        return None  # "Delayed until 10", "Delayed Wednesday", "Delayed due to ice"
    scope = SCOPES.get(word)
    if scope is None:
        return "other"  # "Delayed payroll", "Delayed results"
    # "Delayed bus routes": news of the buses, as "Buses delayed" is.
    return None if scope == "school" else word
