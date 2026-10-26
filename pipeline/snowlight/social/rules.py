"""The deterministic checks every post passes before it is sent (docs/social.md, "Checks").

A post is refused when it is longer than :data:`MAX_WEIGHT` by X's weighting, holds a URL,
a domain or an @mention, more than one hashtag or emoji, ``!!``, a banned word (hype, a
competitor, the private model's words), or, for a waitlist post, no "link in my bio"; and
for what it claims:

* **Model first.** When the facts file holds LIVE model facts (ids ``model`` and
  ``model-*``), every post names one of them by its terms, and a Haiku post the one it was
  given for the day (:func:`model_fact_for`, rotating): Snowlight's chances come from a real
  prediction model trained on real closing records.
* **No one else.** A post says what Snowlight does and never describes, names or compares
  other products or sites: competitor names, "calculator", "competitor", "unlike", "other
  apps", "everyone else", "better than", "more accurate", "AI", any "-er than" or "more ...
  than", and any "guess" but "not a guess" are refused (:data:`BANNED`, :data:`HYPE`,
  :data:`OTHERS`).
* **Nothing to use yet.** "You can now", "check your school", "available now" and the like
  only of the waitlist, or worded as coming: the map is behind a lock until launch.

* **Not live called live.** A sentence that names a TESTING or COMING fact (by its terms)
  must say it is in testing or coming, and may never hold a live claim ("is live", "shows
  up", "ships", "works for everyone") or a negation of testing ("no longer", "done testing",
  "practice is over"). A sentence with a live claim that names no LIVE fact is refused too
  ("Snowlight is live").
* **Numbers.** Every number, in digits or in words (``fifty``, ``twenty-four``, ``first``),
  must be in ``social/facts.md`` in the same form and used as the facts use it (a word next
  to it is next to it in the facts too, so ``24/7`` never becomes "24 schools"). A number
  from the picture's description is never written: the card carries those, labeled.
* **Dates.** "tomorrow", "next week", "next Monday", a weekday or a month name only as the
  facts or the picture's description use it.
* **Older pictures.** When the picture is not current, nothing in the post says it is: no
  "now", "today", "currently", "as of", "just", "fresh", "latest" or a clock time.

Each problem is one plain line, which the writer is shown when it tries again. What these
rules cannot see (a true number in a misleading sentence) is left to Haiku's second check.

**Facts file.** One fact a line: ``- [LIVE] fact-id: text | terms: a, b | except: c, d``.
``terms`` are the words that name the fact's feature in a post; ``except`` the phrases that
hold a term but name another fact (``closings reader`` is the LIVE reader, not the COMING
closings on the map).
"""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Final, Literal

type Status = Literal["LIVE", "TESTING", "COMING"]
type Style = Literal["dev_log", "waitlist"]

MAX_WEIGHT: Final = 270
"""Weighted characters (X allows 280; 10 spare)."""
LIGHT: Final = ((0, 4351), (8192, 8205), (8208, 8223), (8242, 8247))
"""Code points X counts as one character (twitter-text v3); every other counts as two."""

FACT_LINE: Final = re.compile(
    r"^- \[(?P<status>LIVE|TESTING|COMING)\] (?P<id>[a-z0-9][a-z0-9-]*): (?P<text>.+?)"
    r"(?: \| terms: (?P<terms>.+?))?(?: \| except: (?P<except>.+))?$"
)
DOTS: Final = re.compile("[\u00b7\u2022\u2024\u2027\u2219\u22c5\u3002\ufe52\uff0e\uff61]")
"""Characters that read as a dot in a domain ("snowlight\u2024com")."""
SPOKEN_DOMAIN: Final = re.compile(r"\bdot\s+(?:com|org|net|io|app|co|ai|us)\b", re.IGNORECASE)
URL: Final = re.compile(
    r"https?:|www\.|(?<![\w@])[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.[a-z]{2,24}\b", re.IGNORECASE
)
MENTION: Final = re.compile("(?<!\\w)[@\uff20]\\w")
HASHTAG: Final = re.compile("(?<!\\w)[#\uff03]\\w")
NUMBER: Final = re.compile(r"(?<![\w])\d+(?:[.,:/]\d+)*%?")
"""A number as written: ``24/7``, ``1%``, ``118,211`` (commas dropped) and ``9:47`` are one."""
TOKEN: Final = re.compile(r"\d+(?:[.,:/]\d+)*%?|[a-z][a-z'-]*")
CALL_SIGN: Final = re.compile(r"\b[KW][A-Z]{2,3}\b")
"""A TV or radio station's call letters: the posts never name the lists they read."""
WINDOW: Final = 4
"""How many tokens either side of a number or date word make its use."""
STOP: Final = frozenset(
    [
        "a",
        "an",
        "the",
        "in",
        "on",
        "of",
        "to",
        "and",
        "or",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "at",
        "for",
        "it",
        "its",
        "it's",
        "i",
        "i'm",
        "my",
        "me",
        "we",
        "our",
        "with",
        "by",
        "from",
        "as",
        "that",
        "this",
        "these",
        "those",
        "than",
        "so",
        "but",
        "not",
        "no",
        "about",
        "into",
    ]
)
UNITS: Final = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
    "hundred",
    "thousand",
    "million",
    "billion",
    "dozen",
    "half",
]
ORDINALS: Final = [
    "first",
    "second",
    "third",
    "fourth",
    "fifth",
    "sixth",
    "seventh",
    "eighth",
    "ninth",
    "tenth",
    "eleventh",
    "twelfth",
    "thirteenth",
    "fifteenth",
    "twentieth",
    "thirtieth",
    "hundredth",
    "thousandth",
    "millionth",
]
SPELLED: Final = re.compile(
    r"(?<![a-z])(?:" + "|".join(sorted(UNITS + ORDINALS, key=len, reverse=True)) + r")"
    r"(?:-(?:" + "|".join(UNITS[:10] + ORDINALS[:9]) + r"))?s?(?![a-z])"
)
"""A number in words (``fifty``, ``twenty-four``, ``first``, ``thousands``)."""
NOT_SPELLED: Final = re.compile(r"\b(?:no|any|every|some) one\b|\bone another\b")
"""``one`` as a pronoun, not a number."""
DATE_WORDS: Final = re.compile(
    r"\b(?:tomorrow|yesterday|weekend|monday|tuesday|wednesday|thursday|friday|saturday"
    r"|sunday|january|february|april|june|july|august|september|october|november|december)\b"
    r"|\b(?:March|May)\b",
    re.IGNORECASE,
)
NEXT: Final = re.compile(
    r"\bnext (?:week|month|year|weekend|monday|tuesday|wednesday|thursday|friday|saturday"
    r"|sunday)\b|\bin (?:a|one|two|three|\d+) (?:days?|weeks?|months?)\b",
    re.IGNORECASE,
)
"""A coming date the facts never give."""
BANNED: Final = (
    "most accurate",
    "more accurate",
    "accuracy",
    "accurate",
    "revolutionary",
    "ai-powered",
    "ai powered",
    "guaranteed",
    "guarantee",
    "never wrong",
    "better than",
    "beats ",
    "snow day calculator",
    "snowdaycalculator",
    "snow day predictor",
    "snow day app",
    "snowday ai",
    "snow day ai",
    "snow day watch",
    "summer snow day",
    "accuweather",
    "weather channel",
    "perry weather",
    "calculator",
    "formula",
    "reconstruction",
    "snowlightmap",
    "game changer",
    "game-changer",
    "competitor",
    "most precise",
    "spot on",
    "spot-on",
    "world-class",
    "cutting-edge",
    "cutting edge",
    "next-level",
    "number one",
    "#1",
    "snow day predictor",
    "snowdaypredictor",
    "snow day bot",
    "snowdaybot",
    "snowday calculator",
    "unlike other",
    "unlike most",
    "unlike any",
    "everyone else",
    "anyone else",
    "nobody else",
    "no one else",
    "the competition",
    "ai-driven",
    "ai driven",
    "artificial intelligence",
    "machine learning",
    "more reliable",
    "most reliable",
    "smarter",
)
"""Banned anywhere in a post (as text: ``calculator`` also bans ``calculators``)."""
HYPE: Final = (
    "best",
    "only",
    "unlike",
    "beat",
    "beats",
    "vs",
    "versus",
    "precise",
    "perfect",
    "flawless",
    "insane",
    "other app",
    "other apps",
    "other site",
    "other sites",
    "other website",
    "other websites",
    "other predictor",
    "other predictors",
    "other predictions",
    "other tools",
    "other services",
    "other forecasters",
    "other models",
    "others",
    "the rest",
    "ai",
    "a.i.",
)
"""Banned as whole words: superlatives, comparisons and the other apps and sites."""
OTHERS: Final = re.compile(
    r"\b(?!rather\b)[a-z]+er\s+(?:[a-z]+\s+){0,2}than\b"
    r"|\b(?:more|less|fewer|worse)\s+(?:[a-z]+\s+){0,2}than\b"
    r"|\b(?:most|many|other|some|those|these|their)\s+(?:snow[ -]?day\s+)?"
    r"(?:apps?|sites?|websites?|predictors?|calculators?|tools?|services?|forecasters?|guessers?)\b"
    r"|\bthey\s+(?:just\s+)?guess|\blike\s+(?:they|them|others|the\s+rest|everyone)\b",
    re.IGNORECASE,
)
"""A comparison with, or a description of, someone else's product."""
GUESS: Final = re.compile(r"\bguess", re.IGNORECASE)
NOT_A_GUESS: Final = re.compile(
    r"\b(?:not|never|isn't|aren't)\s+(?:a\s+|just\s+a\s+)?guess(?:es|work)?\b", re.IGNORECASE
)
"""The one way a post may say "guess": of Snowlight's own chances, that they are not one."""
ACCESS: Final = (
    "you can now",
    "you can see",
    "you can check",
    "you can look up",
    "you can find",
    "you can search",
    "you can use",
    "check your school",
    "look up your school",
    "see your school",
    "find your school",
    "go check",
    "try it",
    "try snowlight",
    "available now",
    "now available",
    "is available",
    "are available",
    "open to everyone",
    "works for everyone",
    "for everyone now",
    "public now",
    "now public",
    "is public",
    "are public",
)
"""Words that say people can use Snowlight now: true only of the waitlist until launch."""
SDC: Final = re.compile(r"\bsdc\b", re.IGNORECASE)
NOT_LIVE_WORDS: Final[dict[Status, tuple[str, ...]]] = {
    "LIVE": (),
    "TESTING": (
        "testing",
        "test",
        "tests",
        "practice",
        "private",
        "privately",
        "only i ",
        "behind a lock",
        "trial",
        "not live",
        "not public",
        "not on the map yet",
        "before launch",
        "working on",
        "tuning",
    ),
    "COMING": (
        "coming",
        "soon",
        "next",
        "building",
        "working on",
        "will ",
        "planned",
        "plan to",
        "not live",
        "not yet",
        "before launch",
        "at launch",
        "launching",
        "this winter",
        "when snowlight goes live",
        "once snowlight goes live",
        "when it goes live",
        "when it launches",
        "once it launches",
    ),
}
"""Words that say a fact is not live. Either list does for a TESTING or a COMING fact ("the
map is coming" and "closings in testing" are both true of something not live yet)."""
NOT_LIVE: Final = tuple(dict.fromkeys(NOT_LIVE_WORDS["TESTING"] + NOT_LIVE_WORDS["COMING"]))
LIVE_CLAIMS: Final = (
    "is live",
    "are live",
    "now live",
    "live now",
    "went live",
    "is out",
    "are out",
    "now available",
    "available now",
    "is available",
    "are available",
    "you can now",
    "try it",
    "launched",
    "rolled out",
    "up and running",
    "works for everyone",
    "work for everyone",
    "open to everyone",
    "for everyone now",
    "public now",
    "now public",
    "is public",
    "are public",
    "went public",
    "ship",
    "ships",
    "shipped",
    "released",
    "is here",
    "are here",
    "show up",
    "shows up",
    "showing up",
)
"""A sentence holding one says what it names is live."""
NEGATIONS: Final = re.compile(
    r"\bno longer\b|\bnot\b[^.?!]*\banymore\b|\bnot (?:in |a )?(?:testing|practice|test)\b"
    r"|\b(?:done|finished|through|out of|past|over|wrapped(?: up)?)(?: with)? (?:the )?"
    r"(?:testing|practice|test|tests|beta)\b"
    r"|\b(?:testing|practice|the test|tests?|beta)(?: mode)?"
    r" (?:(?:is|are|was|were|has|have|got|been) )*(?:over|done|finished|wrapped|complete|ended"
    r"|behind|closed)\b|\bis over\b|\bare over\b",
    re.IGNORECASE,
)
"""A sentence holding one says testing or practice has ended: a live claim."""
NOW_WORDS: Final = (
    "right now",
    "now",
    "today",
    "tonight",
    "this morning",
    "this afternoon",
    "this evening",
    "at the moment",
    "currently",
    "as of",
    "just",
    "fresh",
    "latest",
    "live look",
    "at present",
)
"""Words that call a picture current: refused when it is an older one."""
CLOCK: Final = re.compile(r"\b\d{1,2}(?::\d{2})?\s?(?:a\.?m\.?|p\.?m\.?)(?![a-z])", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Fact:
    id: str
    status: Status
    text: str
    terms: tuple[str, ...]
    other: tuple[str, ...] = ()
    """Phrases that hold one of the terms but name another fact (``except:``)."""


@dataclass(frozen=True, slots=True)
class Facts:
    facts: tuple[Fact, ...]
    numbers: frozenset[str]
    text: str

    @property
    def said(self) -> str:
        """Every fact's text: what numbers, number words and dates may be taken from."""
        return "\n".join(fact.text for fact in self.facts)

    def get(self, fact_id: str) -> Fact | None:
        return next((fact for fact in self.facts if fact.id == fact_id), None)

    @property
    def model(self) -> tuple[Fact, ...]:
        """The LIVE facts about the prediction model (``model`` and ``model-*``), in file
        order: one of them is in every post."""
        return tuple(
            fact
            for fact in self.facts
            if fact.status == "LIVE" and (fact.id == "model" or fact.id.startswith("model-"))
        )


def model_fact_for(facts: Facts, day: date) -> Fact | None:
    """The model fact a Haiku post states on ``day``: the LIVE model facts in turn, one a day
    (with styles alternating, an odd count pairs each fact with both styles)."""
    model = facts.model
    return model[day.toordinal() % len(model)] if model else None


class FactsError(ValueError):
    """The facts file is malformed."""


def parse_facts(text: str) -> Facts:
    """The facts of ``social/facts.md``.

    Raises:
        FactsError: a fact line does not parse, an id repeats, or there are no facts.
    """
    facts: list[Fact] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.startswith("- ["):
            continue
        match = FACT_LINE.match(line.rstrip())
        if match is None:
            raise FactsError(f"facts line {number} does not parse")
        terms = tuple(
            term.strip().lower() for term in (match["terms"] or "").split(",") if term.strip()
        )
        other = tuple(
            phrase.strip().lower()
            for phrase in (match["except"] or "").split(",")
            if phrase.strip()
        )
        status: Status = match["status"]  # type: ignore[assignment]
        if status != "LIVE" and not terms:
            raise FactsError(f"facts line {number}: a {status} fact needs its terms")
        if any(not re.search("[a-z]", term) for term in terms):
            # "2,388" would split into "2" and "388", and "2" names the fact in "24/7".
            raise FactsError(f"facts line {number}: a term needs a word, not a number")
        facts.append(
            Fact(id=match["id"], status=status, text=match["text"], terms=terms, other=other)
        )
    ids = [fact.id for fact in facts]
    if not facts:
        raise FactsError("the facts file holds no facts")
    if len(set(ids)) != len(ids):
        raise FactsError("a fact id repeats")
    said = "\n".join(fact.text for fact in facts)
    return Facts(facts=tuple(facts), numbers=numbers_in(said), text=text)


def _number(written: str) -> str:
    return written.replace(",", "")


def numbers_in(text: str) -> frozenset[str]:
    """Every number in a text as written, without thousands separators."""
    return frozenset(_number(match) for match in NUMBER.findall(text))


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word  # noqa: PLR2004 - short words keep their s


def _tokens(text: str) -> list[str]:
    return [_number(token) for token in TOKEN.findall(text.lower())]


def _uses(text: str, item: str) -> list[frozenset[str]]:
    """The words around each use of ``item`` (a number or a word) in ``text``."""
    tokens = _tokens(text)
    found: list[frozenset[str]] = []
    for index, token in enumerate(tokens):
        if _stem(token) != _stem(item):
            continue
        near = tokens[max(0, index - WINDOW) : index] + tokens[index + 1 : index + 1 + WINDOW]
        found.append(
            frozenset(_stem(word) for word in near if word[0].isalpha() and word not in STOP)
        )
    return found


def used_as_in(post: str, item: str, sources: Iterable[str]) -> bool:
    """Whether every use of ``item`` in the post shares a word nearby with a use of it in
    one of ``sources`` (``24/7 in practice mode`` matches the facts; ``24 schools`` would
    not, and neither does ``launching tomorrow`` from ``today and tomorrow``)."""
    known = [use for source in sources for use in _uses(source, item)]
    return all(any(mine & theirs for theirs in known) for mine in _uses(post, item))


def weight(text: str) -> int:
    """The post's length as X counts it (NFC; light code points 1, all others 2)."""
    total = 0
    for char in unicodedata.normalize("NFC", text):
        point = ord(char)
        total += 1 if any(low <= point <= high for low, high in LIGHT) else 2
    return total


def _is_emoji(point: int) -> bool:
    return (
        0x1F000 <= point <= 0x1FAFF  # noqa: PLR2004 - Unicode blocks
        or 0x2600 <= point <= 0x27BF  # noqa: PLR2004
        or 0x2B00 <= point <= 0x2BFF  # noqa: PLR2004
        or 0x2300 <= point <= 0x23FF  # noqa: PLR2004
    )


def emoji_count(text: str) -> int:
    """Emoji, a ZWJ sequence and its modifiers counted once."""
    count = 0
    previous = ""
    for char in text:
        point = ord(char)
        if _is_emoji(point) and previous != "‍" and not 0x1F3FB <= point <= 0x1F3FF:  # noqa: PLR2004
            count += 1
        previous = char
    return count


def _sentences(text: str) -> list[str]:
    return [part for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]


def _has(sentence: str, words: Iterable[str]) -> str | None:
    padded = f" {sentence.lower()} "
    for word in words:
        if re.search(rf"(?<![a-z]){re.escape(word.strip())}(?![a-z])", padded):
            return word.strip()
    return None


def _without(sentence: str, phrases: Iterable[str]) -> str:
    lowered = sentence.lower()
    for phrase in phrases:
        lowered = re.sub(rf"(?<![a-z]){re.escape(phrase)}(?![a-z])", " ", lowered)
    return lowered


def _named(sentence: str, facts: Facts) -> list[tuple[Fact, str]]:
    """The facts a sentence names, each with the term that names it."""
    named: list[tuple[Fact, str]] = []
    for fact in facts.facts:
        if term := _has(_without(sentence, fact.other), fact.terms):
            named.append((fact, term))
    return named


def _claims(sentence: str, facts: Facts) -> list[str]:
    """What a sentence wrongly says is live (see the module's docstring)."""
    named = _named(sentence, facts)
    problems: list[str] = []
    if (
        (access := _has(sentence, ACCESS))
        and not any(fact.id == "waitlist" for fact, _ in named)
        and not _has(sentence, NOT_LIVE)
    ):
        problems.append(
            f"it says people can use Snowlight now ('{access}'); until launch only the waitlist"
            " is open"
        )
    claim = _has(sentence, LIVE_CLAIMS)
    if claim is None and (negation := NEGATIONS.search(sentence)) is not None:
        claim = negation.group().lower()
    if claim is not None:
        problems += [
            f"it calls '{term}' live ('{claim}'), but that is {fact.status} ({fact.id})"
            for fact, term in named
            if fact.status != "LIVE"
        ]
        if not named:
            problems.append(f"it says something is live ('{claim}') but names no LIVE fact")
        return problems
    return problems + [
        f"it names '{term}' without saying it is {fact.status.lower()} ({fact.id})"
        for fact, term in named
        if fact.status != "LIVE" and not _has(sentence, NOT_LIVE)
    ]


def _numbers(text: str, facts: Facts, image_description: str) -> list[str]:
    """Numbers in digits or words, and dates, the facts do not give as the post uses them."""
    problems: list[str] = []
    said = facts.said
    for number in sorted(numbers_in(text)):
        if number not in facts.numbers:
            where = " (the card shows the picture's)" if number in image_description else ""
            problems.append(f"the number {number} is not in the facts{where}")
        elif not used_as_in(text, number, [said]):
            problems.append(f"the number {number} is not used as the facts use it")
    lowered = NOT_SPELLED.sub(" ", text.lower())
    for word in sorted({match.group() for match in SPELLED.finditer(lowered)}):
        if not used_as_in(lowered, word, [said]) or not _uses(said, word):
            problems.append(f"the number word '{word}' is not used as the facts use it")
    if match := NEXT.search(text):
        problems.append(f"it gives a date ('{match.group().lower()}') the facts do not")
    for word in sorted({match.group().lower() for match in DATE_WORDS.finditer(text)}):
        sources = [said, image_description]
        if not any(_uses(source, word) for source in sources) or not used_as_in(
            text, word, sources
        ):
            problems.append(f"it says '{word}', which the facts and the picture do not")
    return problems


def _names(text: str, fact: Fact) -> bool:
    return _has(_without(text, fact.other), fact.terms) is not None


def _model_first(text: str, facts: Facts, model_fact: Fact | None) -> list[str]:
    """Every post names a LIVE model fact, and a Haiku post the one it was given."""
    model = facts.model
    if not model:
        return []
    if not any(_names(text, fact) for fact in model):
        return ["it says nothing about the prediction model: every post states one LIVE model fact"]
    if model_fact is not None and not _names(text, model_fact):
        return [f"it does not state the model fact it was given ({model_fact.id})"]
    return []


def _a_facts_hours(before: str, facts: Facts) -> bool:
    """Whether a clock time ending ``before`` closes hours the facts give ("4 to 9 AM")."""
    hours = re.search(r"\d{1,2} to \d{1,2}\s?\S+$", before.rstrip(".,;"))
    return hours is not None and hours.group().lower() in facts.said.lower()


def check(  # noqa: PLR0912, PLR0913 - one rule a branch; the post and what it is checked against
    text: str,
    *,
    style: Style,
    facts: Facts,
    image_description: str,
    image_is_today: bool,
    model_fact: Fact | None = None,
) -> list[str]:
    """The problems with a post; empty when it may be sent. ``model_fact`` is the model fact
    a Haiku post was given to state (:func:`model_fact_for`)."""
    problems: list[str] = []
    lowered = text.lower()
    if not text.strip():
        return ["the post is empty"]
    if (size := weight(text)) > MAX_WEIGHT:
        problems.append(f"it is {size} characters by X's count; the most is {MAX_WEIGHT}")
    plain = DOTS.sub(".", unicodedata.normalize("NFKC", text))
    if URL.search(plain) or SPOKEN_DOMAIN.search(plain):
        problems.append("it holds a URL or a domain; the link is in the bio")
    if MENTION.search(text):
        problems.append("it mentions an account (@)")
    if len(HASHTAG.findall(text)) > 1:
        problems.append("it has more than one hashtag")
    if emoji_count(text) > 1:
        problems.append("it has more than one emoji")
    if "!!" in text or "\u203c" in text:
        problems.append("it has '!!'")
    if "\u2014" in text:
        problems.append("it has an em dash")
    problems += [f"it says '{word.strip()}'" for word in BANNED if word in lowered]
    if word := _has(text, HYPE):
        problems.append(f"it says '{word}' (hype or a comparison)")
    if SDC.search(text):
        problems.append("it says 'SDC'")
    if match := OTHERS.search(text):
        problems.append(f"it compares or describes others ('{match.group().lower()}')")
    if GUESS.search(NOT_A_GUESS.sub(" ", text)):
        problems.append("it says 'guess' other than 'not a guess'")
    problems += _model_first(text, facts, model_fact)
    if CALL_SIGN.search(text):
        problems.append("it names a station's call letters")
    if style == "waitlist" and "link in my bio" not in lowered:
        problems.append("a waitlist post must say 'link in my bio'")
    problems += _numbers(text, facts, image_description)
    if not image_is_today:
        if now_word := _has(text, NOW_WORDS):
            problems.append(f"it says '{now_word}' but the picture is an older one")
        for clock in CLOCK.finditer(text):
            if not _a_facts_hours(text[: clock.end()], facts):
                problems.append(
                    f"it gives a time ('{clock.group()}') but the picture is an older one"
                )
                break
    for sentence in _sentences(text):
        problems += _claims(sentence, facts)
    return problems


def numbers_in_post(text: str) -> frozenset[str]:
    """The numbers a post states, whole (``3,146`` is 3146, never its parts)."""
    return numbers_in(text)
