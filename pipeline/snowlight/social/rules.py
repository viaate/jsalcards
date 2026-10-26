"""The deterministic checks every post passes before it is sent (docs/social.md, "Checks").

A post is refused when it is longer than :data:`MAX_WEIGHT` by X's weighting, holds a URL,
a domain or an @mention, more than one hashtag or emoji, ``!!``, a banned word (hype, a
competitor, the private model's words), a number that neither ``social/facts.md`` nor its
image's description holds, a sentence that names a TESTING or COMING fact without saying it
is in testing or coming (or that calls it live), or, for a waitlist post, no "link in my
bio". Each problem is one plain line, which the writer is shown when it tries again.

**Facts file.** One fact a line: ``- [LIVE] fact-id: text | terms: a, b``. ``terms`` are the
words that name the fact's feature in a post (for TESTING and COMING facts, what the
status check looks for).
"""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Literal

type Status = Literal["LIVE", "TESTING", "COMING"]
type Style = Literal["dev_log", "waitlist"]

MAX_WEIGHT: Final = 270
"""Weighted characters (X allows 280; 10 spare)."""
LIGHT: Final = ((0, 4351), (8192, 8205), (8208, 8223), (8242, 8247))
"""Code points X counts as one character (twitter-text v3); every other counts as two."""

FACT_LINE: Final = re.compile(
    r"^- \[(?P<status>LIVE|TESTING|COMING)\] (?P<id>[a-z0-9][a-z0-9-]*): (?P<text>.+?)"
    r"(?: \| terms: (?P<terms>.+))?$"
)
URL: Final = re.compile(
    r"https?:|www\.|(?<![\w@])[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.[a-z]{2,24}\b", re.IGNORECASE
)
MENTION: Final = re.compile("(?<!\\w)[@\uff20]\\w")
HASHTAG: Final = re.compile("(?<!\\w)[#\uff03]\\w")
NUMBER: Final = re.compile(r"\d+(?:[.,:]\d+)*")
CALL_SIGN: Final = re.compile(r"\b[KW][A-Z]{2,3}\b")
"""A TV or radio station's call letters: the posts never name the lists they read."""
SPELLED: Final = ("dozen", "hundred", "thousand", "million", "billion")
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
)
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
    ),
}
LIVE_CLAIMS: Final = (
    "is live",
    "are live",
    "now live",
    "live now",
    "went live",
    "is out",
    "now available",
    "available now",
    "is available",
    "are available",
    "you can now",
    "try it",
    "launched",
    "rolled out",
    "up and running",
)
NOW_WORDS: Final = ("right now", "tonight", "this morning", "this evening", "at the moment")


@dataclass(frozen=True, slots=True)
class Fact:
    id: str
    status: Status
    text: str
    terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Facts:
    facts: tuple[Fact, ...]
    numbers: frozenset[str]
    text: str

    def get(self, fact_id: str) -> Fact | None:
        return next((fact for fact in self.facts if fact.id == fact_id), None)


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
        status: Status = match["status"]  # type: ignore[assignment]
        if status != "LIVE" and not terms:
            raise FactsError(f"facts line {number}: a {status} fact needs its terms")
        facts.append(Fact(id=match["id"], status=status, text=match["text"], terms=terms))
    ids = [fact.id for fact in facts]
    if not facts:
        raise FactsError("the facts file holds no facts")
    if len(set(ids)) != len(ids):
        raise FactsError("a fact id repeats")
    return Facts(facts=tuple(facts), numbers=numbers_in(text), text=text)


def numbers_in(text: str) -> frozenset[str]:
    """Every number in a text, without thousands separators."""
    found: set[str] = set()
    for match in NUMBER.findall(text):
        found.add(match.replace(",", ""))
        found.update(part for part in re.split(r"[.,:]", match) if part)
    return frozenset(found)


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


def check(  # noqa: PLR0912 - one rule a branch
    text: str,
    *,
    style: Style,
    facts: Facts,
    image_description: str,
    image_is_today: bool,
) -> list[str]:
    """The problems with a post; empty when it may be sent."""
    problems: list[str] = []
    lowered = text.lower()
    if not text.strip():
        return ["the post is empty"]
    if (size := weight(text)) > MAX_WEIGHT:
        problems.append(f"it is {size} characters by X's count; the most is {MAX_WEIGHT}")
    if URL.search(text):
        problems.append("it holds a URL or a domain; the link is in the bio")
    if MENTION.search(text):
        problems.append("it mentions an account (@)")
    if len(HASHTAG.findall(text)) > 1:
        problems.append("it has more than one hashtag")
    if emoji_count(text) > 1:
        problems.append("it has more than one emoji")
    if "!!" in text or "‼" in text:
        problems.append("it has '!!'")
    if "—" in text:
        problems.append("it has an em dash")
    for word in BANNED:
        if word in lowered:
            problems.append(f"it says '{word.strip()}'")
    if SDC.search(text):
        problems.append("it says 'SDC'")
    if CALL_SIGN.search(text):
        problems.append("it names a station's call letters")
    if style == "waitlist" and "link in my bio" not in lowered:
        problems.append("a waitlist post must say 'link in my bio'")
    allowed = facts.numbers | numbers_in(image_description)
    for number in sorted(numbers_in_post(text) - allowed):
        problems.append(f"the number {number} is not in the facts or the image's description")
    for word in SPELLED:
        if re.search(rf"\b{word}s?\b", lowered) and word not in facts.text.lower():
            problems.append(f"the number word '{word}' is not in the facts")
    if not image_is_today and (now_word := _has(text, NOW_WORDS)):
        problems.append(f"it says '{now_word}' but the image is not from today")
    for sentence in _sentences(text):
        for fact in facts.facts:
            if fact.status == "LIVE" or not (term := _has(sentence, fact.terms)):
                continue
            if claim := _has(sentence, LIVE_CLAIMS):
                problems.append(
                    f"it calls '{term}' live ('{claim}'), but that is {fact.status} ({fact.id})"
                )
            elif not _has(sentence, NOT_LIVE_WORDS[fact.status]):
                problems.append(
                    f"it names '{term}' without saying it is {fact.status.lower()} ({fact.id})"
                )
    return problems


def numbers_in_post(text: str) -> frozenset[str]:
    """The numbers a post states, whole (``3,146`` is 3146, never its parts)."""
    return frozenset(match.replace(",", "") for match in NUMBER.findall(text))
