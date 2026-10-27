"""The deterministic checks every post passes before it is sent (docs/social.md, "Checks").

A post is refused when it is longer than :data:`MAX_WEIGHT` by X's weighting, holds a URL,
a domain or an @mention, more than one hashtag or emoji, ``!!``, a banned word (hype, a
competitor, the private model's words), or, for a waitlist post, no "link in my bio"; and
for what it claims:

* **Closed vocabulary.** Every word must be a word of the facts (their text, terms and excepted
  phrases), of the picture's description, of the commit subjects the writer was shown, a small
  word (:data:`FUNCTION_WORDS`) or a plain word of the founder's voice (:data:`VOICE_WORDS`),
  in any plural, past or -ing form (:func:`vocabulary`). So a post cannot name, describe or
  compare anything the facts do not ("SDCalc", "influencers", "industry-leading", "gold
  standard"), claim accuracy in new words ("results", "confident"), invent a feature, a hire,
  a partner or a user ("iPhone", "hired", "partnered", "a bunch of you"), or give a level or a
  place the picture does not ("could close", "the Rockies"). The rules below still hold for
  the words the facts do give.
* **Model first.** When the facts file holds LIVE model facts (ids ``model`` and
  ``model-*``), every post names one of them by its terms, and a Haiku post the one it was
  given for the day (:func:`model_fact_for`, rotating): Snowlight's chances come from a real
  prediction model trained on real closing records.
* **No one else.** A post says what Snowlight does and never describes, names or compares
  other products, sites or people: competitor names (also run together or spaced out,
  :data:`NAMES`, matched on the text with spaces, hyphens and dots taken out), "snow day"
  followed by a product word ("snow day sites", "snow day trackers": :data:`SNOW_DAY_THING`),
  "calculator", "competitor", "unlike", "other apps", "other people", "folks", "the usual",
  "famous", "popular", "elsewhere", "out there", "everyone else", "better than",
  "outperform", "superior", "more accurate", "AI", "ML", "neural", "ChatGPT", any "-er than"
  or "more ... than", and any "guess" but "not a guess" are refused (:data:`BANNED`,
  :data:`HYPE`, :data:`OTHER_PEOPLE`, :data:`OTHERS`); so are what others do or use ("instead
  of", rivals, alternatives, the radar, rumors, vibes, tricks, weathermen, the news, TV), any
  plural of a product word ("news sites", "TV stations": :data:`PLURAL_OTHERS`), uniqueness
  ("the first", "the largest", "unique", "unmatched"), "SDC" however it is spaced or dotted, and
  any letter outside the Latin script or invisible character (a Cyrillic a in
  "calculator", a zero-width space inside a name).
* **No accuracy, no made-up product.** No accuracy claim with or without a number ("always
  right", "called most snow days right", "hit rate", "reliable", "correct": :data:`ACCURACY`),
  and nothing the facts do not say about the product or who uses it ("download", "the app",
  "free", "schools use", "trusted by", a team, investors, "daily emails", "never shared", a
  growing waitlist: :data:`PRODUCT`). No school, district, station or person is named
  (:data:`DISTRICT_NAME`, :data:`CALL_SIGN`, :data:`PERSON`), no state unless the picture's
  description names it (:data:`STATES`), and no version or other run-together
  letter-and-digit word the facts do not hold ("v3").
* **Nothing to use yet.** "You can now", "check your school", "see your district", "find it
  on" and the like only of the waitlist, or worded as coming: the map is behind a lock until
  launch. A post that names the waitlist says "link in my bio".

* **Not live called live.** Each TESTING or COMING term is judged where it stands: a word
  that says it is not live must be said of it (:func:`_excused`: next to it in its clause, or
  nearer to it than to anything else not live, or as "testing them" after it), and only a
  word true of it (a COMING fact is "coming", never "in testing" or "in practice"; "practice"
  excuses only the reader's practice mode). "Closings glow on the map; notifications are
  coming" names the closings with nothing said of them. A term with "already", "works", "is
  on", "turned on" or "ends" near it is refused whatever else is said (:data:`ALREADY`). A
  sentence with a live claim ("is live", "shows up", "ships", "works for everyone") or a
  negation of testing ("no longer", "done testing", "practice is over") may name no TESTING or
  COMING fact, and must name a LIVE one ("Snowlight is live" is refused).
* **Numbers.** Every number, in digits or in words (``fifty``, ``twenty-four``, ``first``),
  must be in ``social/facts.md`` in the same form and used as the facts use it: a word near it
  is near it in the facts too, the word right after it (its noun) is among the facts' first
  three after it, and a number in digits shares a word before it in its sentence with the
  facts' sentence (``24/7`` never becomes "24 schools", ``11 past winters`` never "11 states",
  "the directory holds 118,211 schools" never "the reader checks 118,211 schools"). A number
  from the picture's description is never written: the card carries those, labeled.
* **Dates.** "tomorrow", "next week", "next Monday", a weekday or a month name only as the
  facts or the picture's description use it.
* **Chances while TESTING.** While the facts file marks ``chances`` TESTING (the site is
  locked until the chances are ready, :func:`chances_shown`), no post gives a chance: no
  percent, no "percent", no odds and no level ("a high chance", "chances are low"), no
  likelihood of a closing in other words near a closing word ("a coin flip", "near certain",
  "probably close", "expects closings": :data:`GUESSED_LEVEL`), and the facts file itself may
  hold no percent then. A sentence may still say where the chances come
  from when it names a LIVE model fact whose own words speak of them ("each district's chance
  comes from a statistical model"), but only with no word that offers them to anyone
  (:data:`OFFERED`: "see your district's chance", "chances are up", "posted", "already
  checking", "now", "you").
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
from itertools import pairwise
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
NOT_SPELLED: Final = re.compile(
    r"\b(?:no|any|every|some|each|this|that|which|the|a|new) one\b|\bone another\b"
    r"|\bone (?:of|day)\b"
)
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
    "machine-learning",
    "deep learning",
    "more reliable",
    "most reliable",
    "smarter",
    "outperform",
    "superior",
    "chatgpt",
)
"""Banned anywhere in a post (as text: ``calculator`` also bans ``calculators``)."""
NAMES: Final = (
    "snowdaycalculator",
    "snowdaypredictor",
    "snowdayprediction",
    "snowdayai",
    "snowdaywatch",
    "snowdaybot",
    "snowdaydetector",
    "snowdaychecker",
    "snowdaytracker",
    "accuweather",
    "weatherchannel",
    "perryweather",
    "chatgpt",
    "openai",
    "snowdaycalc",
    "snowdaypredict",
    "sdcalc",
)
"""Other products' names as they read with spaces, hyphens and dots taken out ("Snowday
Predictor", "Snow-Day Calculator", "snow day A.I.")."""
SNOW_DAY_THING: Final = re.compile(
    r"\bsnow[\s-]?days?\s+(?:[a-z']+\s+)?(?:sites?|websites?|apps?|trackers?|predictors?"
    r"|predictions?|tools?|services?|calculators?|bots?|forecasters?|guessers?|pages?"
    r"|accounts?|checkers?|detectors?)\b",
    re.IGNORECASE,
)
""""snow day" followed by a product word: a post about Snowlight never needs to say it of
others."""
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
    "ml",
    "gpt",
    "llm",
    "neural",
    "outdo",
    "outdoes",
    "outdid",
    "outperforms",
    "famous",
    "popular",
    "elsewhere",
    "out there",
    "the usual",
    "gut",
    "rival",
    "rivals",
    "alternative",
    "alternatives",
    "instead",
    "radar",
    "rumor",
    "rumors",
    "rumour",
    "rumours",
    "vibe",
    "vibes",
    "weatherman",
    "weathermen",
    "weather man",
    "meteorologist",
    "meteorologists",
    "forecaster",
    "trick",
    "tricks",
    "biggest",
    "largest",
    "unique",
    "uniquely",
    "unmatched",
    "unrivaled",
    "unparalleled",
    "one of a kind",
    "one-of-a-kind",
    "first ever",
    "first-ever",
    "first of its kind",
    "huge",
    "massive",
    "news",
    "tv",
    "forget the",
    "other product",
    "other products",
    "other service",
    "other people's",
)
"""Banned as whole words: superlatives, uniqueness ("the largest set", "unique",
"unmatched"), hype ("huge", "massive") and others or what they do: rivals, alternatives, "instead
of", the radar, rumors, vibes, weathermen, the news and TV, tricks."""
PLURAL_OTHERS: Final = re.compile(
    r"\b(?:sites|websites|stations|channels|apps|products|services|accounts|pages|forecasters"
    r"|predictors|calculators|trackers|bots|tools)\b",
    re.IGNORECASE,
)
"""Any "<noun> sites", "TV stations", "news apps": Snowlight is one map, so a plural of a
product word is always about others."""
OTHER_PEOPLE: Final = (
    "other people",
    "most people",
    "many people",
    "lots of people",
    "some people",
    "a lot of people",
    "folks",
    "everybody else",
    "the internet",
)
"""Other people as a contrast ("other people eyeball the radar"): a post says what Snowlight
does."""
ACCURACY: Final = (
    "always right",
    "right about",
    "never misses",
    "never miss",
    "hit rate",
    "track record",
    "nailed",
    "nails it",
    "correct",
    "correctly",
    "reliable",
    "reliably",
    "trustworthy",
    "brier",
    "calibrated",
    "error rate",
    "success rate",
    "wrong",
    "rarely wrong",
    "seldom wrong",
    "proven",
    "proves",
    "proved",
    "it works",
    "works well",
    "worked well",
    "held up",
    "holds up",
    "hold up",
    "scored well",
    "scores well",
    "did well",
    "does well",
    "performs",
    "performed",
    "count on",
    "precision",
    "precisely",
    "science-backed",
    "backed by science",
    "scientific",
    "validated",
    "verified",
    "dependable",
    "held its own",
    "holds its own",
    "hold its own",
    "holding its own",
    "results",
    "result",
    "impressed",
    "impressive",
    "impresses",
    "confident",
    "confidence",
    "nails",
    "solid",
    "lands",
    "landed",
    "calls",
    "spot",
    "on point",
    "on target",
    "trust",
)
"""Accuracy claims with or without a number: the past records lean toward storm days, so no
accuracy is ever posted."""
ACCURACY_CALL: Final = re.compile(
    r"\b(?:call(?:s|ed)?|get(?:s)?|got|gotten|predict(?:s|ed)?|guess(?:es|ed)?)\b"
    r"(?:\s+[a-z']+){0,4}\s+right\b",
    re.IGNORECASE,
)
""""called most snow days right", "gets it right"."""
PRODUCT: Final = (
    "download",
    "downloads",
    "app store",
    "play store",
    "the snowlight app",
    "our app",
    "my app",
    "free",
    "schools use",
    "parents use",
    "families use",
    "people use",
    "teachers use",
    "used by",
    "trusted by",
    "trust",
    "trusts",
    "team",
    "teams",
    "we",
    "we're",
    "we've",
    "our",
    "ours",
    "co-founder",
    "cofounder",
    "investor",
    "investors",
    "backed by",
    "funded",
    "funding",
    "daily emails",
    "daily email",
    "weekly",
    "newsletter",
    "newsletters",
    "shared",
    "growing",
    "grows",
    "signups",
    "sign-ups",
    "subscribers",
    "followers",
    "love",
    "loves",
    "loved",
    "joined",
    "signed up",
    "partnered",
    "partner",
    "featured",
    "hired",
)
"""What the facts never say of the product or its maker: an app to download, a price, who
uses it, a team or investors (I build it alone), more email than the one at launch, an email
"never shared" (the fact says never sold), a growing waitlist."""
PERSON: Final = re.compile(
    r"\b(?:my\s+)?(?:friend|friends|buddy|dad|father|mom|mother|brother|sister|teacher|coach"
    r"|cousin|uncle|aunt|classmate|neighbor|partner)\s+[A-Z][a-z]+",
)
""""My friend Jake": the posts name no person."""
DISTRICT_NAME: Final = re.compile(
    r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:Public\s+Schools?|School\s+District|City\s+Schools?"
    r"|County\s+Schools?|Area\s+Schools?|Community\s+Schools?|Unified|Schools?|Academy"
    r"|High(?:\s+School)?|Middle(?:\s+School)?|Elementary(?:\s+School)?)(?:'s|\u2019s)?\b"
    r"|\b(?:ISD|CISD|USD|CUSD|UFSD|CSD)\b"
)
"""A school or district by name, plural, singular or possessive ("Bozeman Public Schools",
"Denver Public School's", "Lincoln High's", "Katy ISD"): never named."""
SPACED_AI: Final = re.compile(r"\bA\.?\s+I\b\.?|\bM\.\s?L\.")
""""A I" and "M.L." spelled apart."""
LETTERS_AND_DIGITS: Final = re.compile(r"\b(?=[a-z0-9]*[a-z])(?=[a-z0-9]*\d)[a-z0-9]+\b", re.I)
"""A word run together of letters and digits ("v3", "2x", "5th"): only as the facts write it."""
OTHERS: Final = re.compile(
    r"\b(?!rather\b)[a-z]+er\s+(?:[a-z]+\s+){0,2}than\b"
    r"|\b(?:more|less|fewer|worse)\s+(?:[a-z]+\s+){0,2}than\b"
    r"|\b(?:most|many|other|some|those|these|their|popular|famous|big|usual)\s+"
    r"(?:snow[ -]?day\s+)?"
    r"(?:apps?|sites?|websites?|predictors?|calculators?|tools?|services?|forecasters?|guessers?"
    r"|trackers?|bots?|pages?|accounts?)\b"
    r"|\bthey\s+(?:just\s+)?guess|\blike\s+(?:they|them|others|the\s+rest|everyone)\b",
    re.IGNORECASE,
)
"""A comparison with, or a description of, someone else's product."""
GUESS: Final = re.compile(r"\bguess", re.IGNORECASE)
PRACTICE: Final = re.compile(r"\bpractic", re.IGNORECASE)
"""Practice mode: said only while a fact's text speaks of it (the reader left it when the owner
switched it on, so "the reader runs in practice mode" is stale once the facts drop it)."""
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
    "see your",
    "look up your",
    "check your",
    "find your",
    "find it",
    "pull up",
    "up on snowlight",
    "is up on",
    "are up on",
    "already checking",
    "already using",
    "already use",
)
"""Words that say people can use Snowlight now: true only of the waitlist until launch."""
OFFERED: Final = (
    "you",
    "your",
    "yours",
    "see",
    "look",
    "looking",
    "check",
    "checking",
    "find",
    "view",
    "posted",
    "are up",
    "is up",
    "up on",
    "up for",
    "already",
    "now",
    "here",
    "today",
    "tonight",
    "visible",
    "everyone",
    "anyone",
    "parents",
    "families",
)
"""Words that offer a TESTING thing to someone ("see your district's chance", "the chances
are up", "posted for every district"): a sentence naming the TESTING chances by a LIVE model
fact's words is excused only without them."""
SDC: Final = re.compile(r"\bs[\s.\-_*]*d[\s.\-_*]*c", re.IGNORECASE)
"""'SDC' however it is spaced or dotted ("S.D.C.", "S D C"), also run into more letters
("SDCalc")."""
CALC: Final = re.compile(r"\bcalc", re.IGNORECASE)
"""A word starting "calc" ("Snow Day Calc", "calcs"): another product's name or the calculator
the posts never speak of."""
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
        "yet",
        "at launch",
        "launching",
        "this winter",
        "when snowlight goes live",
        "once snowlight goes live",
        "when it goes live",
        "when it launches",
        "once it launches",
        "once",
    ),
}
"""Words that say a fact is not live, each excusing only the facts it is true of
(:func:`_excuses`): a COMING fact only by the COMING words (closings, the glow, notifications
and the model's learning are not "in testing" or "in practice": they are not on at all), a
TESTING fact by either list, and "practice" only a fact whose own text speaks of practice
mode (the reader's practice, never the map, the glow or the closings). "Before launch" is a
TESTING word only ("only I can open it before launch"): "before launch I put every closed
school on the map" calls the closings done."""
NOT_LIVE: Final = tuple(dict.fromkeys(NOT_LIVE_WORDS["TESTING"] + NOT_LIVE_WORDS["COMING"]))
EXCUSE_GAP: Final = 6
"""The most words between a TESTING or COMING term and the word that says it is not live, in
one clause ("phone alerts and closings are coming"; not "closings glow on the map tonight and
phone alerts are coming")."""
CLAUSE: Final = re.compile(
    r"\s*[,;:\u2013\u2014()]\s*|\s+-\s+|\s+(?:but|so|yet|although|though)\s+"
    r"|\s+and\s+(?=(?:i|i'm|i've|i'll|it|it's|they|they're|we|you|there|now|then)\b)",
    re.IGNORECASE,
)
"""Where a sentence's clauses part: each TESTING or COMING term is judged in its own clause, so
a "coming" said of one thing never excuses another ("Closings glow on the map, notifications
next.")."""
VAGUE: Final = (
    "more coming",
    "more to come",
    "more soon",
    "more on the way",
    "more is coming",
    "with more",
    "adding more",
    "and more",
    "once a",
    "once an",
    "once every",
    "once more",
    "once again",
    "at once",
)
"""Words of "more to come" that say nothing is not live: they never excuse a term."""
ALREADY: Final = re.compile(
    r"\balready\b|\bworks?\b(?!\s+out)|\bworking\b(?!\s+on)|\b(?:turned|switched)\s+on\b"
    r"|\b(?:is|are|now)\s+on\b(?!\s+(?:the|a|an|my|your|every|each|its|their|this|that)\b)"
    r"|\bend(?:s|ed|ing)?\b",
    re.IGNORECASE,
)
"""Words that say a thing is on or done ("already", "works", "is on", "turned on", "ends"): a
clause holding one never names a TESTING or COMING fact, whatever else it says ("Watches
already raise chances while I test them", "Practice mode ends this week")."""
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
    r"|\b(?:done|finished|through|out of|past|over|wrapped(?: up)?|left|leaves|leaving|exited"
    r"|exits|beyond|graduated(?: from)?|graduates(?: from)?|moved (?:past|on from|out of)"
    r"|came out of|comes out of|coming out of|out of)(?: with)? (?:the |its |private )?"
    r"(?:testing|practice|test|tests|beta|lock)\b"
    r"|\bout of beta\b"
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
CHANCES_ID: Final = "chances"
"""The facts file's switch: chances are shown in posts and cards only while this fact is LIVE."""
CLOSINGS_ID: Final = "closings"
"""The facts file's switch for closings: a picture, card or alt text shows or counts closings
only while this fact is LIVE (practice-mode closings are checked before anything goes
public)."""
CLOSINGS_WORDS: Final = re.compile(
    r"\b(?:closed|closings?(?!\s+(?:records?|lists?|reader))|closures?|delay(?:s|ed)?"
    r"|lit\s+up|lights?\s+up|glow\w*|dismissing\s+early|early\s+dismissal)\b",
    re.IGNORECASE,
)
"""Any word of closings on the map (not the reader, its lists or the model's closing
records): what a picture's description, alt text and card hold none of while closings are not
LIVE."""
CHANCE_NUMBER: Final = re.compile(
    r"[%\uff05\ufe6a\u2030]|\bper\s?cent|\bpercent|\bpct\b|\bodds\b|\b\d+\s*(?:in|out of)\s*\d+\b"
    r"|\b(?:one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:in|out of)\s+"
    r"(?:two|three|four|five|six|seven|eight|nine|ten|\d+)\b",
    re.IGNORECASE,
)
"""A chance given as a number: a percent sign or word, odds, "3 in 4", "one out of ten"."""
CHANCE_WORDS: Final = re.compile(
    r"[%\uff05\ufe6a\u2030]|\bper\s?cent|\bpercent|\bodds\b|\bchances?\b|\blikelihood\b"
    r"|\bprobabilit(?:y|ies)\b",
    re.IGNORECASE,
)
"""Any word of a chance: what a picture's description, alt text and card hold none of while
chances are TESTING."""
LEVEL: Final = (
    "low",
    "lower",
    "lowest",
    "high",
    "higher",
    "highest",
    "tiny",
    "small",
    "slim",
    "big",
    "bigger",
    "huge",
    "good",
    "decent",
    "strong",
    "zero",
    "none",
    "nil",
    "likely",
    "unlikely",
    "rising",
    "rises",
    "rose",
    "jumped",
    "jumps",
    "spiked",
    "spikes",
    "climbing",
    "dropped",
    "falling",
    "minimal",
    "flat",
    "nothing",
    "near-zero",
    "slight",
    "certain",
    "up",
    "down",
    "hot",
    "cold",
    "warm",
)
"""Words that give a chance's level, refused near "chance" while chances are TESTING."""
GUESSED_LEVEL: Final = (
    "coin flip",
    "coin-flip",
    "coin toss",
    "fifty-fifty",
    "50-50",
    "50/50",
    "toss-up",
    "toss up",
    "certain",
    "certainly",
    "near certain",
    "probable",
    "probably",
    "likely",
    "unlikely",
    "expect",
    "expects",
    "expected",
    "expecting",
    "watching",
    "sure thing",
    "sure bet",
    "safe bet",
    "good bet",
    "odds-on",
    "could",
    "might",
    "looking",
    "looks",
    "eye on",
    "per the model",
    "says the model",
    "the model says",
)
"""Words that give a closing's chance without the word "chance" ("a coin flip", "near
certain", "probably close"): refused near :data:`CLOSING_WORDS` while chances are TESTING."""
CLOSING_WORDS: Final = (
    "snow day",
    "snow days",
    "no school",
    "close",
    "closes",
    "closed",
    "closing",
    "closings",
    "closure",
    "closures",
    "delay",
    "delays",
    "delayed",
    "district",
    "districts",
    "school",
    "schools",
)
STATES: Final = re.compile(
    r"\b(?:Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida"
    r"|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland"
    r"|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada"
    r"|New\s+Hampshire|New\s+Jersey|New\s+Mexico|New\s+York|North\s+Carolina|North\s+Dakota"
    r"|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode\s+Island|South\s+Carolina|South\s+Dakota"
    r"|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West\s+Virginia|Wisconsin|Wyoming"
    r"|Puerto\s+Rico|Guam|Canada|Mexico)\b"
)
"""A state (or a place outside the lower 48) by name: a post names one only as the picture's
description or the facts do ("watching Montana closely" is a chance in other words)."""
EMAIL_OFTEN: Final = re.compile(
    r"\bemails\b|\bemail\b(?:\W+[a-z']+){0,5}?\W+(?:every|each|daily|weekly|morning|mornings"
    r"|night|nights|whenever|anytime|day|days|alert|alerts|update|updates)\b"
    r"|\b(?:every|each|daily|weekly|morning)\b(?:\W+[a-z']+){0,3}?\W+emails?\b",
    re.IGNORECASE,
)
"""More email than the one the waitlist fact gives ("an email every morning there's a snow
day", "emails")."""
PLACE_CHANCE: Final = re.compile(
    r"\b(?!Snowlight)[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:'s|\u2019s)\s+(?:\w+\s+)?"
    r"(?:chances?|odds|numbers?)\b"
)
""""Denver's chance": a place's chance, never named."""
VOICE_WORDS: Final = frozenset(
    """
    dev log devlog update updates quick note notes week weekend night nights morning evening
    spent spend spending built build building fixed fix fixes fixing wrote write writing
    added add adding made make making worked working work kept keep keeping checked check
    checking got get getting went go going goes want wanted need needed needs mean means meant
    think thought know knew happen happened happens issue issues issued join link bio post
    posts posting thing things part parts step steps piece goal plain simple hard long code
    started start again still even back finally myself founder small honest quietly careful
    carefully soon testing tested test tests coming next planned plan yet launch winter
    private privately trial tuning tune tuned lock locked behind until quiet teach taught few
    far everyone snowlight now right look
    """.split()  # noqa: SIM905 - a word list reads best as text
)
"""Plain words of the founder's own voice a post may use besides the words of the facts, the
picture's description and the recent work (:func:`vocabulary`): what I did ("spent the night
on", "fixed", "built"), when ("this week"), the not-live words, and the waitlist's "link in my
bio". Nothing here names a product, a person, a place, a level or a quality."""
FUNCTION_WORDS: Final = frozenset(
    """
    a an the and or but nor so yet of to in on at by for from with without into onto upon over
    under up down out off about as than then that this these those there here it its it's
    itself i i'm i've i'll i'd me my mine you you're you'll you've your yours they them their
    they're is are was were be been being am do does did doing done has have had having will
    would can cannot can't won't wouldn't isn't aren't wasn't weren't don't doesn't didn't
    hasn't haven't not no never what which who when where why how if while because also too
    very each every all both any either neither such there's that's what's here's let's just
    one
    """.split()  # noqa: SIM905 - a word list reads best as text
)
"""Words that carry no claim of their own, left out of the closed vocabulary. "could",
"might", "may", "per", "some", "most", "many", "other", "another" and "else" are not among
them: each is a claim (a chance's level, a comparison) the facts must hold."""
HASHTAGS: Final = frozenset(["buildinpublic", "devlog", "snowday", "snowdays", "indiedev"])
"""The hashtags a post may use outside the closed vocabulary (at most one a post)."""
HASHTAG_WORD: Final = re.compile("[#\uff03](\\w+)")
VOCAB_WORD: Final = re.compile(r"[a-z]+(?:'[a-z]+)?")


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


def chances_shown(facts: Facts) -> bool:
    """Whether posts and cards may show a chance: only while the facts file marks the
    ``chances`` fact LIVE (the lead marks it LIVE when the owner unlocks the site). A file
    without it shows none."""
    fact = facts.get(CHANCES_ID)
    return fact is not None and fact.status == "LIVE"


def still_true(line: str, facts: Facts) -> bool:
    """Whether a card's line is still true per the facts: words of a LIVE fact's text (the
    model line is part of the LIVE fact ``model``), or the whole text of a COMING fact, which
    says itself that it is coming (a part of one could drop the "coming")."""
    wanted = line.strip().rstrip(".").lower()
    return any(
        (fact.status == "LIVE" and wanted in fact.text.lower())
        or (fact.status == "COMING" and fact.text.strip().rstrip(".").lower() == wanted)
        for fact in facts.facts
    )


def closings_shown(facts: Facts) -> bool:
    """Whether pictures and cards may show closings: only while the facts file marks the
    ``closings`` fact LIVE. A file without it shows none."""
    fact = facts.get(CLOSINGS_ID)
    return fact is not None and fact.status == "LIVE"


def mentions_closings(text: str) -> bool:
    """Whether ``text`` holds any word of closings on the map (:data:`CLOSINGS_WORDS`)."""
    return CLOSINGS_WORDS.search(text) is not None


def mentions_chance(text: str) -> bool:
    """Whether ``text`` holds any word of a chance (:data:`CHANCE_WORDS`)."""
    return CHANCE_WORDS.search(text) is not None


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
    shown = any(fact.id == CHANCES_ID and fact.status == "LIVE" for fact in facts)
    if not shown and CHANCE_NUMBER.search(said):
        # A post may use any number the facts hold: while chances are TESTING none of them
        # may be a chance.
        raise FactsError("a fact gives a chance as a number while chances are not LIVE")
    return Facts(facts=tuple(facts), numbers=numbers_in(said), text=text)


def _number(written: str) -> str:
    return written.replace(",", "")


def numbers_in(text: str) -> frozenset[str]:
    """Every number in a text as written, without thousands separators."""
    return frozenset(_number(match) for match in NUMBER.findall(text))


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word  # noqa: PLR2004 - short words keep their s


def _tokens(text: str) -> list[str]:
    return [
        _number(token).removesuffix("'s").removesuffix("\u2019s")
        for token in TOKEN.findall(text.lower().replace("\u2019", "'"))
    ]


def _forms(word: str) -> frozenset[str]:
    """``word`` and the stems its plural, past or -ing form may come from ("closes", "closed"
    and "closing" all hold "close"; "learned" and "learning" hold "learn")."""
    word = word.removesuffix("'s")
    forms = {word}
    if len(word) > 3:  # noqa: PLR2004 - short words keep their endings
        if word.endswith("ies"):
            forms.add(word[:-3] + "y")
        if word.endswith("es"):
            forms.add(word[:-2])
        if word.endswith("s") and not word.endswith("ss"):
            forms.add(word[:-1])
        if word.endswith("ied"):
            forms.add(word[:-3] + "y")
        if word.endswith("ed"):
            forms |= {word[:-2], word[:-1]}
            if len(word) > 4 and word[-3] == word[-4]:  # noqa: PLR2004 - "planned"
                forms.add(word[:-3])
        if word.endswith("ing") and len(word) > 4:  # noqa: PLR2004 - "sing" is a word
            forms |= {word[:-3], word[:-3] + "e"}
            if len(word) > 5 and word[-4] == word[-5]:  # noqa: PLR2004 - "planning"
                forms.add(word[:-4])
    return frozenset(forms)


def _vocab_words(text: str) -> list[str]:
    return VOCAB_WORD.findall(text.lower().replace("\u2019", "'"))


def vocabulary(facts: Facts, image_description: str, commits: Iterable[str] = ()) -> frozenset[str]:
    """The closed vocabulary of a post (every form, :func:`_forms`): the words of every fact's
    text, terms and excepted phrases, of the picture's description and of the commit subjects
    the writer was shown, and :data:`VOICE_WORDS`."""
    sources = [facts.said, image_description, *commits]
    sources += [" ".join(fact.terms + fact.other) for fact in facts.facts]
    sources += NOT_LIVE
    words = {word for source in sources for word in _vocab_words(source)} | VOICE_WORDS
    return frozenset(form for word in words for form in _forms(word))


def _closed(text: str, allowed: frozenset[str]) -> list[str]:
    """The words of ``text`` outside the closed vocabulary (:func:`vocabulary`) and
    :data:`FUNCTION_WORDS`, each once, in order; a hashtag of :data:`HASHTAGS` is fine."""
    unknown: list[str] = []
    plain = HASHTAG_WORD.sub(
        lambda match: " " if match.group(1).lower() in HASHTAGS else match.group(1), text
    )
    for word in _vocab_words(plain):
        if word in FUNCTION_WORDS or word.removesuffix("'s") in FUNCTION_WORDS:
            continue
        if not _forms(word) & allowed and word not in unknown:
            unknown.append(word)
    return unknown


def _hype(text: str, facts: Facts) -> str | None:
    """The first word of :data:`HYPE` in ``text`` that is not used as a fact's own words: a
    run of three words holding it that a fact's text also holds ("fit only to the winters
    before it" is the model-tested fact's; "the only prediction model" is hype)."""
    said = " ".join(_vocab_words(facts.said))
    words = _vocab_words(text)
    for word in HYPE:
        if _has(text, [word]) is None:
            continue
        parts = word.split()
        own = False
        for index in range(len(words) - len(parts) + 1):
            if words[index : index + len(parts)] != parts:
                continue
            windows = [
                words[start : start + len(parts) + 2]
                for start in range(max(0, index - 2), index + 1)
                if start + len(parts) + 2 <= len(words)
            ]
            own = any(f" {' '.join(window)} " in f" {said} " for window in windows)
            if not own:
                break
        if not own:
            return word
    return None


@dataclass(frozen=True, slots=True)
class Use:
    """One use of a number or a word: the words near it, the words before it in its
    sentence, and the first words after it (stop words left out)."""

    near: frozenset[str]
    before: frozenset[str]
    after: tuple[str, ...]


def _uses_of(text: str, item: str) -> list[Use]:
    found: list[Use] = []
    for sentence in _sentences(text):
        tokens = _tokens(sentence)
        for index, token in enumerate(tokens):
            if _stem(token) != _stem(item):
                continue
            ahead = tokens[index + 1 : index + 1 + WINDOW]
            near = tokens[max(0, index - WINDOW) : index] + ahead
            found.append(
                Use(
                    near=frozenset(
                        _stem(word) for word in near if word[0].isalpha() and word not in STOP
                    ),
                    before=frozenset(
                        _stem(word)
                        for word in tokens[:index]
                        if word[0].isalpha() and word not in STOP
                    ),
                    after=tuple(
                        _stem(word.strip("-'"))
                        for word in ahead
                        if word[0].isalpha() and len(word.strip("-'")) > 1 and word not in STOP
                    ),
                )
            )
    return found


def _uses(text: str, item: str) -> list[frozenset[str]]:
    """The words around each use of ``item`` (a number or a word) in ``text``."""
    return [use.near for use in _uses_of(text, item)]


def _same_use(mine: Use, theirs: Use, *, strict: bool, digits: bool) -> bool:
    """Whether a post's use of a number is a use of it in the facts: a word nearby in common
    and, ``strict``, the word right after it (its noun) among the facts' first three after
    it ("2,388 real past school days", never "2,388 followers"; "11 past winters", never "11
    states") and, for a number in ``digits``, when both have words before it in their
    sentences, one of them in common ("the directory holds 118,211 schools", never "the reader
    checks 118,211 schools")."""
    if not mine.near & theirs.near:
        return False
    if not strict:
        return True
    if mine.after and (not theirs.after or mine.after[0] not in theirs.after[:3]):
        return False
    return not (digits and mine.before and theirs.before and not mine.before & theirs.before)


def used_as_in(post: str, item: str, sources: Iterable[str], *, strict: bool = False) -> bool:
    """Whether every use of ``item`` in the post is a use of it in one of ``sources``
    (:func:`_same_use`): ``24/7 in practice mode`` matches the facts; ``24 schools`` would
    not, and neither does ``launching tomorrow`` from ``today and tomorrow``."""
    known = [use for source in sources for use in _uses_of(source, item)]
    return all(
        any(_same_use(mine, theirs, strict=strict, digits=item[0].isdigit()) for theirs in known)
        for mine in _uses_of(post, item)
    )


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


def _odd_letters(text: str) -> str | None:
    """The first letter outside the Latin script ("calculator" written with a Cyrillic a) or
    invisible format character (a zero-width space, a soft hyphen) in ``text``, named;
    ``None`` when there is none. An emoji's zero-width joiner is fine."""
    for char in text:
        category = unicodedata.category(char)
        name = unicodedata.name(char, f"U+{ord(char):04X}")
        if (category.startswith("L") and not name.startswith("LATIN")) or (
            category == "Cf" and char != "\u200d"
        ):
            return name.lower()
    return None


def _sentences(text: str) -> list[str]:
    return [part for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]


def _has(sentence: str, words: Iterable[str]) -> str | None:
    padded = f" {sentence.lower()} "
    for word in words:
        if re.search(rf"(?<![a-z]){re.escape(word.strip())}(?![a-z])", padded):
            return word.strip()
    return None


def _without(sentence: str, phrases: Iterable[str]) -> str:
    """The sentence in lower case with each of ``phrases`` blanked out (same length, so a
    position in it is a position in the sentence)."""
    lowered = sentence.lower()
    for phrase in phrases:
        lowered = re.sub(
            rf"(?<![a-z]){re.escape(phrase)}(?![a-z])",
            lambda match: " " * len(match.group()),
            lowered,
        )
    return lowered


def _spans(text: str, words: Iterable[str]) -> list[tuple[int, int]]:
    """Where each of ``words`` stands in ``text`` (lower case, whole words)."""
    found: list[tuple[int, int]] = []
    for word in words:
        found += [
            match.span()
            for match in re.finditer(rf"(?<![a-z]){re.escape(word.strip())}(?![a-z])", text)
        ]
    return found


def _gap(text: str, one: tuple[int, int], other: tuple[int, int]) -> int:
    """How many words stand between two spans of ``text`` (0 when they touch or overlap)."""
    start, end = (one[1], other[0]) if one[0] <= other[0] else (other[1], one[0])
    return len(re.findall(r"[a-z0-9']+", text[start:end])) if start < end else 0


def _clauses(sentence: str) -> list[str]:
    return [part for part in CLAUSE.split(sentence) if part.strip()]


def _excuses(fact: Fact) -> tuple[str, ...]:
    """The words that may say ``fact`` is not live (see :data:`NOT_LIVE_WORDS`)."""
    words = NOT_LIVE_WORDS["COMING"] if fact.status == "COMING" else NOT_LIVE
    practice = "practice" in fact.text.lower()
    return tuple(word for word in words if word != "practice" or practice)


def _named(sentence: str, facts: Facts) -> list[tuple[Fact, str]]:
    """The facts a sentence names, each with the term that names it."""
    named: list[tuple[Fact, str]] = []
    for fact in facts.facts:
        if term := _has(_without(sentence, fact.other), fact.terms):
            named.append((fact, term))
    return named


FUTURE: Final = (
    "will",
    "you'll",
    "you will",
    "at launch",
    "after launch",
    "once snowlight goes live",
    "when snowlight goes live",
    "once it goes live",
    "when it goes live",
    "once it launches",
    "when it launches",
    "when snowlight launches",
    "once snowlight launches",
)
"""The only words that excuse a word of :data:`ACCESS`: said as what people will be able to do
("at launch you can search by ZIP code"). A testing or coming word near it never does ("You
can search by ZIP code while I keep testing" says people can search now)."""


def _access(sentence: str, named: list[tuple[Fact, str]]) -> list[str]:
    """A clause that says people can use Snowlight now, not worded as what they will do
    (:data:`FUTURE`)."""
    if any(fact.id == "waitlist" for fact, _ in named):
        return []
    for clause in _clauses(sentence.replace("\u2019", "'")):
        text = _without(clause, VAGUE)
        if (access := _has(clause, ACCESS)) is None:
            continue
        near = _spans(text, FUTURE)
        if not any(
            _gap(text, one, other) <= EXCUSE_GAP for one in _spans(text, [access]) for other in near
        ):
            return [
                f"it says people can use Snowlight now ('{access}'); until launch only the"
                " waitlist is open"
            ]
    return []


BACK: Final = ("that", "it", "them", "these", "those", "both")
"""Words by which a testing word speaks of what came before it in the sentence, as its object
("Watches can raise a chance; I am testing that")."""
BACK_GAP: Final = 2
BACK_WORDS: Final = ("testing", "test", "tests", "tuning", "trial")
"""The only not-live words that speak of an earlier TESTING term through a word of
:data:`BACK` ("testing it"): a COMING word never does ("and I will keep polishing it" says
nothing of closings named before it)."""
NEAREST_SLACK: Final = 2
"""How many words farther than the nearest TESTING or COMING term in its clause a term of
another fact may stand from a not-live word and still be the one it speaks of."""
LIST_WORDS: Final = frozenset(["and", "or", "nor", "plus", "the", "a", "an", "both", "also"])
"""The words that may join two terms in a list ("phone alerts and closings are coming"): one
not-live word speaks of every item of a list, never across a verb ("closed schools glow and
phone alerts are coming")."""
JOIN_WORDS: Final = LIST_WORDS | frozenset(
    ["on", "in", "of", "for", "across", "at", "from", "like", "its", "every", "each", "with"]
)
"""The words that may join a term to the next one it holds as a list item or a phrase of
place or kind ("closings on the map start this winter", "glow on the map like city lights"):
never a verb ("closed schools glow"), and never nothing (two terms side by side, "closings
glow")."""
LEAD_WORDS: Final = LIST_WORDS | frozenset(["every", "each", "all", "my"])
"""What may stand before the first of a run of terms in its clause when the not-live word comes
after them all ("Every closing on the map ..., coming"; never "Schools glow and phone alerts
are coming")."""
FRAGMENT_WORDS: Final = frozenset(
    [
        "still",
        "both",
        "all",
        "too",
        "also",
        "quietly",
        "in",
        "the",
        "background",
        "this",
        "winter",
        "soon",
        "yet",
        "and",
        "for",
        "later",
        "not",
        "live",
        "being",
        "under",
    ]
)
"""The words besides its not-live words that a clause of its own may hold and still speak of
the clause before it ("Every school closing on one map, coming this winter"; "watches, still
in testing")."""


@dataclass(frozen=True, slots=True)
class Named:
    """A TESTING or COMING term where it stands in a sentence, and its clause."""

    fact: Fact
    term: str
    span: tuple[int, int]
    clause: int


def _clause_of(boundaries: list[int], at: int) -> int:
    return sum(1 for boundary in boundaries if boundary <= at)


def _not_live_named(text: str, facts: Facts, boundaries: list[int]) -> list[Named]:
    """Every TESTING or COMING term in ``text``, except inside a longer term ("prediction" in
    "prediction model" is the LIVE model, not the TESTING predictions; "phone" in "phone
    alerts" is judged as "phone alerts")."""
    every = [
        span for fact in facts.facts for span in _spans(_without(text, fact.other), fact.terms)
    ]
    return [
        Named(fact, term, span, _clause_of(boundaries, span[0]))
        for fact in facts.facts
        if fact.status != "LIVE"
        for term in fact.terms
        for span in _spans(_without(text, fact.other), [term])
        if not any(
            start <= span[0] and span[1] <= end and end - start > span[1] - span[0]
            for start, end in every
        )
    ]


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text)


def _joined(text: str, first: Named, second: Named) -> bool:
    """Whether two terms in a row are joined by :data:`JOIN_WORDS` only (and some)."""
    if first.span[1] > second.span[0]:
        return True
    joined = _words(text[first.span[1] : second.span[0]])
    return bool(joined) and all(token in JOIN_WORDS for token in joined)


def _listed(text: str, one: Named, word: tuple[int, int], named: list[Named]) -> Named | None:
    """The term of the run nearest the not-live ``word`` when every other fact's term between
    ``one`` and ``word`` is joined to the term before it by list or place words only
    (:data:`JOIN_WORDS`) and, when ``word`` comes after them, the run they make (with the
    terms joined to it before ``one``) has nothing but :data:`LEAD_WORDS` before it in its
    clause: then the not-live word speaks of the whole run. ``None`` otherwise."""
    low, high = min(one.span[0], word[0]), max(one.span[1], word[1])
    between = sorted(
        (
            other
            for other in named
            if other.fact.id != one.fact.id
            and low < other.span[0] < high
            and not (word[0] <= other.span[0] < word[1])
        ),
        key=lambda other: other.span[0],
    )
    if not between:
        return one
    chain = sorted([one, *between], key=lambda other: other.span[0])
    if not all(_joined(text, first, second) for first, second in pairwise(chain)):
        return None
    if word[0] < one.span[0]:
        return chain[0]
    head = one
    earlier = sorted(
        (other for other in named if other.span[1] <= one.span[0]),
        key=lambda other: other.span[0],
        reverse=True,
    )
    for other in earlier:
        if not _joined(text, other, head):
            break
        head = other
    clause_start = max(index for index in _clause_starts(text) if index <= head.span[0])
    lead = _words(text[clause_start : head.span[0]])
    return chain[-1] if all(token in LEAD_WORDS for token in lead) else None


def _clause_starts(text: str) -> list[int]:
    return [0, *(match.end() for match in CLAUSE.finditer(text))]


def _excused(text: str, one: Named, named: list[Named], boundaries: list[int]) -> bool:
    """Whether a not-live word for ``one``'s fact (:func:`_excuses`) says it is not live, in
    ``one``'s own clause only: within :data:`EXCUSE_GAP` words of it, or about as near to it as
    to any other TESTING or COMING term of the clause (:data:`NEAREST_SLACK`), with any other
    fact's terms between them only as items of one list (:func:`_listed`); or as a clause of
    its own holding nothing but the not-live phrase, right after ``one``'s ("Every school
    closing on one map, coming this winter"); or, for a TESTING term, as a testing word after
    it with a word of :data:`BACK` as its object ("..., and I am testing them"). A not-live
    word said of another thing never counts ("Closings glow on the map; notifications are
    coming", "Phone alerts are coming; closings light up every state")."""
    starts = _clause_starts(text)
    for word in _spans(text, _excuses(one.fact)):
        clause = _clause_of(boundaries, word[0])
        if clause == one.clause:
            in_clause = [other for other in named if other.clause == clause]
            nearest = min(_gap(text, other.span, word) for other in in_clause)
            run = _listed(text, one, word, in_clause)
            gap = None if run is None else _gap(text, run.span, word)
            if gap is not None and (gap <= EXCUSE_GAP or gap <= nearest + NEAREST_SLACK):
                return True
            continue
        if _fragment(clause, one, named) and _in_fragment(text, starts, clause, one.fact):
            return True
        if (
            one.fact.status == "TESTING"
            and word[0] >= one.span[1]
            and _has(text[word[0] : word[1]], BACK_WORDS)
            and any(
                back[0] >= word[1] and _gap(text, word, back) <= BACK_GAP
                for back in _spans(text, BACK)
            )
        ):
            return True
    return False


def _fragment(clause: int, one: Named, named: list[Named]) -> bool:
    """Whether ``clause`` comes right after ``one``'s (or one later, with no TESTING or COMING
    term in the clause between) and names nothing itself."""
    return 0 < clause - one.clause <= 2 and not any(  # noqa: PLR2004 - right after, or one more
        one.clause < other.clause <= clause for other in named
    )


def _in_fragment(text: str, starts: list[int], clause: int, fact: Fact) -> bool:
    """Whether a clause holds nothing but ``fact``'s not-live words and
    :data:`FRAGMENT_WORDS` ("coming this winter", "still in testing")."""
    end = starts[clause + 1] if clause + 1 < len(starts) else len(text)
    part = _without(text[starts[clause] : end], _excuses(fact))
    return all(token in FRAGMENT_WORDS for token in _words(part))


def _judged(sentence: str, facts: Facts) -> list[str]:
    """Each TESTING or COMING term of a sentence, judged where it stands: refused with a word
    of :data:`ALREADY` near it in its clause, or with no not-live word for it
    (:func:`_excused`), unless it is the TESTING chances as a LIVE model fact named in the
    sentence speaks of them, with no word in the sentence that offers them to anyone
    (:data:`OFFERED`)."""
    text = _without(sentence, VAGUE)
    boundaries = [match.start() for match in CLAUSE.finditer(text)]
    named = _not_live_named(text, facts, boundaries)
    live = [fact for fact, _ in _named(sentence, facts) if fact.status == "LIVE"]
    problems: list[str] = []
    seen: set[tuple[str, str]] = set()
    for one in named:
        if (one.fact.id, one.term) in seen:
            continue
        on = next(
            (
                match
                for match in ALREADY.finditer(text)
                if _clause_of(boundaries, match.start()) == one.clause
                and _gap(text, one.span, match.span()) <= EXCUSE_GAP
            ),
            None,
        )
        if on is not None:
            problems.append(
                f"it says '{on.group()}' of '{one.term}', which is {one.fact.status}"
                f" ({one.fact.id})"
            )
        elif not _excused(text, one, named, boundaries) and not (
            one.fact.status == "TESTING"
            and any(_speaks_of(other, one.term) for other in live)
            and not _has(sentence, OFFERED)
        ):
            problems.append(
                f"it names '{one.term}' without saying it is {one.fact.status.lower()} next to"
                f" it ({one.fact.id})"
            )
        else:
            continue
        seen.add((one.fact.id, one.term))
    return problems


def _claims(sentence: str, facts: Facts) -> list[str]:
    """What a sentence wrongly says is live (see the module's docstring)."""
    named = _named(sentence, facts)
    problems = _access(sentence, named)
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
    return problems + _judged(sentence, facts)


def _speaks_of(fact: Fact, term: str) -> bool:
    """Whether a LIVE fact's own text uses ``term`` (or its plural or singular): a sentence
    naming that fact may use the term as the fact does ("each district's chance comes from a
    statistical model" names the LIVE model, whose text speaks of chances, while the chances
    themselves are TESTING)."""
    forms = {term, term + "s", term.removesuffix("s")}
    return _has(fact.text, forms) is not None


def _chance_given(text: str) -> list[str]:
    """What gives a chance in a post while chances are TESTING (see the module's docstring)."""
    problems: list[str] = []
    if match := CHANCE_NUMBER.search(text):
        problems.append(
            f"it gives a chance as a number ('{match.group().lower()}'); no chance is posted"
            " while the chances are in testing"
        )
    tokens = TOKEN.findall(text.lower())
    for index, token in enumerate(tokens):
        if _stem(token) not in {"chance", "likelihood"}:
            continue
        near = tokens[max(0, index - 4) : index + 7]
        if level := next((word for word in near if word in LEVEL), None):
            problems.append(
                f"it says how high or low a chance is ('{level}'); no chance is posted while"
                " the chances are in testing"
            )
            break
    lowered = text.lower()
    closings = _spans(lowered, CLOSING_WORDS)
    for level, span in ((word, span) for word in GUESSED_LEVEL for span in _spans(lowered, [word])):
        if any(_gap(lowered, span, other) <= WINDOW * 2 for other in closings):
            problems.append(
                f"it says how likely a closing is ('{level}'); no chance is posted while the"
                " chances are in testing"
            )
            break
    return problems


def _numbers(text: str, facts: Facts, image_description: str) -> list[str]:
    """Numbers in digits or words, and dates, the facts do not give as the post uses them."""
    problems: list[str] = []
    said = facts.said
    for number in sorted(numbers_in(text)):
        if number not in facts.numbers:
            where = " (the card shows the picture's)" if number in image_description else ""
            problems.append(f"the number {number} is not in the facts{where}")
        elif not used_as_in(text, number, [said], strict=True):
            problems.append(f"the number {number} is not used as the facts use it")
    lowered = NOT_SPELLED.sub(" ", text.lower())
    for word in sorted({match.group() for match in SPELLED.finditer(lowered)}):
        if not used_as_in(lowered, word, [said], strict=True) or not _uses(said, word):
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


def _others_and_claims(text: str, facts: Facts) -> list[str]:  # noqa: PLR0912 - a rule a branch
    """Banned words, other products and people, accuracy and product claims, names and
    run-together letters and digits (see the module's docstring)."""
    problems: list[str] = []
    lowered = text.lower()
    problems += [f"it says '{word.strip()}'" for word in BANNED if word in lowered]
    squashed = re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKC", text).lower())
    problems += [f"it names another product ('{name}')" for name in NAMES if name in squashed]
    if match := SNOW_DAY_THING.search(text):
        problems.append(f"it speaks of other snow day products ('{match.group().lower()}')")
    if word := _hype(text, facts):
        problems.append(f"it says '{word}' (hype or a comparison)")
    if match := CALC.search(text):
        problems.append(f"it names another product ('{match.group().lower()}')")
    if match := EMAIL_OFTEN.search(text):
        problems.append(
            f"it promises more email than the facts give ('{match.group().lower()}'): one email"
            " when Snowlight goes live"
        )
    if match := PLACE_CHANCE.search(text):
        problems.append(f"it gives a place's chance ('{match.group()}')")
    if word := _has(text, OTHER_PEOPLE):
        problems.append(f"it describes what others do ('{word}'); say what Snowlight does")
    if (word := _has(text, ACCURACY)) or (call := ACCURACY_CALL.search(text)):
        said = word or (call.group().lower() if call else "")
        problems.append(f"it claims accuracy ('{said}'); no accuracy is ever posted")
    if word := _has(text, PRODUCT):
        problems.append(f"it says '{word}', which the facts do not say of Snowlight")
    if match := DISTRICT_NAME.search(text):
        problems.append(f"it names a school or district ('{match.group()}')")
    if match := PERSON.search(text):
        problems.append(f"it names a person ('{match.group()}')")
    if match := PLURAL_OTHERS.search(text):
        problems.append(f"it speaks of other products ('{match.group().lower()}')")
    if match := SPACED_AI.search(text):
        problems.append(f"it says '{match.group()}' (AI or ML words)")
    said_lower = facts.said.lower()
    for match in LETTERS_AND_DIGITS.finditer(text):
        if match.group().lower() not in said_lower:
            problems.append(f"it writes '{match.group()}', which the facts do not")
            break
    return problems


def check(  # noqa: PLR0912, PLR0913, PLR0915 - one rule a branch; the post and its sources
    text: str,
    *,
    style: Style,
    facts: Facts,
    image_description: str,
    image_is_today: bool,
    model_fact: Fact | None = None,
    commits: Iterable[str] = (),
) -> list[str]:
    """The problems with a post; empty when it may be sent. ``model_fact`` is the model fact
    a Haiku post was given to state (:func:`model_fact_for`); ``commits`` the commit subjects
    its writer was shown, whose words join the closed vocabulary (:func:`vocabulary`)."""
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
    if odd := _odd_letters(text):
        problems.append(f"it has a letter or mark that is not plain Latin text ({odd})")
    if unknown := _closed(text, vocabulary(facts, image_description, commits)):
        shown = ", ".join(f"'{word}'" for word in unknown[:6])
        problems.append(
            f"it uses words the facts, the picture's description and the recent work do not"
            f" ({shown}); a post says only what they say, in their words"
        )
    problems += _others_and_claims(text, facts)
    if SDC.search(text):
        problems.append("it says 'SDC'")
    if match := OTHERS.search(text):
        problems.append(f"it compares or describes others ('{match.group().lower()}')")
    if GUESS.search(NOT_A_GUESS.sub(" ", text)):
        problems.append("it says 'guess' other than 'not a guess'")
    if PRACTICE.search(text) and not PRACTICE.search(facts.said):
        problems.append("it says 'practice', but no fact is in practice mode now")
    problems += _model_first(text, facts, model_fact)
    if CALL_SIGN.search(text):
        problems.append("it names a station's call letters")
    if style == "waitlist" and "link in my bio" not in lowered:
        problems.append("a waitlist post must say 'link in my bio'")
    elif "waitlist" in lowered and "link in my bio" not in lowered:
        problems.append("a post that names the waitlist must say 'link in my bio'")
    for state in sorted({" ".join(match.group().split()) for match in STATES.finditer(text)}):
        if state not in " ".join(f"{image_description} {facts.said}".split()):
            problems.append(f"it names {state}, which the picture's description does not")
    if not chances_shown(facts):
        problems += _chance_given(text)
        if mentions_chance(image_description):
            problems.append("the picture's description gives a chance while chances are TESTING")
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
