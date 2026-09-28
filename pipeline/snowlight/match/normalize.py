"""Turn a school or district name into a form that compares across spellings.

Both sides go through the same steps, so ``"St. Mary's Elem."`` from a closings
list and ``"ST MARYS ELEMENTARY SCHOOL"`` from NCES end up as the same
:class:`NameForm`:

1. :func:`fold`: Unicode compatibility decomposition with the accents dropped,
   typographic quotes and dashes made ASCII, then case folding.
2. Punctuation: ``&`` becomes ``and``, apostrophes go (``marys``), dotted
   acronyms close up (``U.F.S.D.`` to ``ufsd``) but a person's dotted initials
   before a name stay letters (``"J.F. Kennedy"`` is ``j f kennedy``, not the
   ``jf`` of no one), ``No.``, ``#`` and ``Number`` before a number go, and the
   text splits into letter and digit runs.
3. Canonical words (:mod:`snowlight.match.lexicon`): abbreviations expand both
   ways, ``St`` becomes ``saint`` before a name and ``street`` after one, ``El``
   is Elementary only where Pennsylvania and Texas use it (``El Sch``, ``Bonham
   El``) and never in ``El Paso``, ``H S`` and ``J H`` are high and junior high,
   Roman numerals become numbers (``R-IV`` to ``r 4``; a lone ``I``, ``V`` or
   ``X`` only after a numbering word, and never as a dotted initial: ``"J. I.
   Watson"`` is a man), ``junior high`` becomes one level, and leading zeros go.
4. District codes are read (:func:`district_codes`): a designator of a series
   of its own and its number anywhere (``RSU 13``, ``MSAD 17``, ``AOS 98``) and a
   district designator and number at the start (``USD 320 Wamego``, ``D-3
   Widefield``) go from the words, so ``"USD 320 Wamego"`` reads as
   ``"Wamego USD 320"`` does; the code names the district, and a school named
   after it is one of that district's. Numbers leave the word list and form a
   set of their own (``28-J`` is ``28j``), and the letters that only prefix them
   (``R-``, ``RE-``, ``C-``) go.
5. Designators, the words that say what kind of body a name is rather than which
   one, are stripped from the end (``School District``, ``Public Schools``,
   ``ISD``, ``School System``, ``Parish School Board``) and from the front
   (``School District of``). For a district name the legal-form words go too
   (``Unified``, ``Community``, ``Central``, ``Union Free``, ``Municipal``,
   ``Union``), but never the last remaining word, and so do the ones before the
   levels and qualifiers a district's name ends with (``"Westside Union
   Elementary"``, ``"Sycamore Community City"``, ``"Oak Hill Union Local"``),
   and Michigan's ``of the City of`` (``"Flint School District of the City
   of"``), which makes the name imply ``City``.
6. What remains is sorted into school levels (elementary, middle, high ...),
   place qualifiers (county, township, city, local, area ...) and the
   identifying words, whose trailing plural or possessive ``s`` is dropped
   (``marys`` to ``mary``), though the form keeps which words were written so
   (:attr:`NameForm.plurals`): ``"Parks"`` is not ``"Park"``, nor ``"Brooks"``
   ``"Brook"``, but ``"St. Marys"`` is ``"St. Mary's"``. A level word that
   begins a name before a place qualifier names the place (New Jersey's
   ``"Middle Township"``).
7. A school's name that begins with a person's forenames or initials (``"John F
   Kennedy"``, ``"J F Kennedy"``, ``"Charles White"``) says how many
   (:attr:`NameForm.forenames`, :func:`forenames`), which a list may leave out.

A directory name is first read apart from the brackets NCES ends some names with
(:func:`directory_name`): Arizona's entity number (``"(4192)"``), a county that
tells namesakes apart (``"Evergreen School District (Clark)"``), a legal form
(``"(CHARTER)"``) or a second name a district is known by (``"HAVERSTRAW-STONY
POINT CSD (NORTH ROCKLAND)"``) is no part of the name a closings list uses, and a
person's forenames in brackets after the surname (California's and Delaware's
``"Kennedy (John F.) Elementary"``) go before it, where a list says them.

:func:`clean_listing` removes what a closings list adds around a name: a status
in brackets (``"(Closed)"``) or after a separator (``"- 2 Hour Delay"``), clock
times, and ``"All Schools"``; it also keeps the parts between separators, so a
city or district named beside a school can be read as context. :func:`non_k12`
and :func:`not_school` read those parts for what is no K-12 school at all: a
college (``"Boston College"``), a civic body (``"City of Monessen"``, ``"Sabine
Pass Senior Center"``) or a business (``"Royston, LLC"``).
"""

import html
import itertools
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Final, NamedTuple

from snowlight.match import lexicon
from snowlight.match.forenames import GIVEN_NAMES


class Level(StrEnum):
    """What a listing's own words say it names."""

    DISTRICT = "district"
    SCHOOL = "school"
    UNKNOWN = "unknown"


class NameForm(NamedTuple):
    """A name reduced to the parts the matcher compares.

    Attributes:
        tokens: the identifying words in order, canonical and stemmed.
        token_set: the same words as a set.
        levels: school levels named (``elementary``, ``juniorhigh``, ``high`` ...).
        qualifiers: place qualifiers named (``county``, ``city``, ``township`` ...).
        numbers: numbers named, as canonical strings (``"4"``, ``"28j"``).
        compact: the tokens joined without spaces, so ``Oak Ridge`` meets ``Oakridge``.
        hint: whether the words read as a district, one school, or either.
        says_school: the words name a school outright (``School``, ``Academy``,
            ``Charter``), not only a level; always false for a directory name.
        affiliations: the church, faith or school tradition named (``catholic``,
            ``lutheran``, ``montessori`` ...), see :data:`lexicon.AFFILIATIONS`.
        system: the words name a group of private schools (``"Omaha Catholic
            Schools"``), so one school of a given level is at most one of them;
            always false for a directory name.
        implied: place qualifiers the name implies without saying them, which
            a listing may say or leave out (``county`` for Colorado's ``"School
            District No. 1 in the county of Denver"``, and for South Carolina's
            ``"Greenville 01"``, which :class:`~snowlight.match.index.NameIndex`
            adds).
        school_of: the words say ``School of`` or ``School for`` (``"Valley
            School of Ligonier"``, ``"Pressley Ridge School for Autism"``): a
            name whose order its words alone do not give.
        codes: district codes of a series of their own, as series and number
            (``"rsu 13"``, ``"sad 17"``, see :data:`lexicon.DISTRICT_SERIES`).
            Their numbers are in :attr:`numbers` too.
        district_numbers: the other numbers that name a district rather than a
            school: one after a district designator at the start (``"USD 320
            Wamego"``), after a district prefix (``"RE-2"``, ``"R-IV"``) or after
            ``District`` or ``Unit`` (``"CUSD 300"``, ``"School District No.
            5"``). A subset of :attr:`numbers`. In a listing that names a school
            they, like :attr:`codes`, say which district it is in (``"D-3
            Widefield High School"``, ``"RSU 13 Oceanside High School"``).
        public_school: the name ends ``Public School`` (singular) and says
            nothing else of its kind: ``"Elba Public School"`` is how a closings
            list names a town's whole school system, and ``"Carey Public School"``
            is one school's NCES name.
        names_kind: the name says what kind of school it is: ``School`` or
            ``Schools``, a level, or a noun such as ``Academy`` or ``Center``
            (``"Birches School"``, ``"Lincoln Elementary"``), unlike a bare name
            (``"Gloria Deo"``).
        directions: the compass directions among the tokens (``east`` for
            ``"E. Lansing"``, see :func:`expand_directions`): ``"East Lansing"``
            is not ``"Lansing"``.
        devoted: the name is a saint's or a devotion's (``"St. Mary's"``,
            ``"Sacred Heart"``, see :data:`lexicon.DEVOTIONS`), so a listing may
            leave out its church.
        one_school: the name ends ``School`` (singular) and not ``Public
            School``: one school's name, which a district of one school carries
            (``"St. Paul City School"``, a charter school), unlike a town's
            system (``"Saint Paul Public Schools"``).
        school_named: a district's name reads as one school's, or as a group of
            schools of one level, and says nothing of a district (:func:`named_as_school`):
            ``"Premier High Schools"``, ``"Arrow Academy"``, ``"Orenda Charter
            School"``, unlike ``"Fortuna Elementary"`` or ``"Hunterdon Central
            Regional High School District"``. A charter network is often named so.
        qualifier_first: the name begins with a place qualifier, so the word
            names rather than qualifies (``"City University Schools"``,
            ``"Village Academy"``), unlike ``"Murfreesboro City Schools"`` and
            ``"Township of Union"``, which :func:`name_first` reads as ``"Union
            Township"``.
        grades: for a directory school whose name says no level, its grades
            (:attr:`~snowlight.match.directory.DirectoryRecord.span`, prekindergarten
            ``-1``, kindergarten ``0``), which say the levels a listing may name it
            by (:func:`~snowlight.match.grades.fit`): NCES's ``"Lincoln"`` of K-5 is
            the lists' ``"Lincoln Elementary"``. ``None`` for any other name, and
            for such a school whose grades are unknown; the
            :class:`~snowlight.match.index.NameIndex` sets it.
        forenames: for a school's name that begins with a person's name, how
            many of its first tokens may be the person's forenames, initials and
            title rather than the surname (:func:`forenames`): ``2`` for ``"John F
            Kennedy Middle"``, ``"J F Kennedy Middle"`` and ``"Martin Luther King
            Jr Elementary"``, ``1`` for ``"Charles White Elementary"``. A list may
            name the school by the surname and what follows it
            (``"Kennedy Middle School"``), leaving the forenames out.
        forenames_sure: the name's forenames are surely a person's whatever their
            words, as NCES gave them in brackets after the surname
            (``"Lincoln (Abraham) Elementary"``, see :func:`directory_name`).
            Otherwise forenames are sure only where they end with an initial
            (``"John F"``, ``"R. D."``): a given name alone may be a place's word
            (``"Grace Hill"``, ``"Glen Park"``).
        plurals: the tokens whose word was written with a trailing ``s`` the token
            drops (``park`` for ``"Parks"``, ``oak`` for ``"The Oaks"``), which is
            another word than the one written without it, but for a saint's
            possessive (``"St. Marys"``).
        possessives: the tokens whose word was written with an apostrophe's
            ``s`` (``king`` for ``"King's Academy"``), which may be written
            ``"Kings"`` as well as ``"King"``.
        letters: each run of two or more single letters among the tokens, run
            together (``fc`` for ``"F. C. Boyd"``): the initials a name may write
            as one word (``"FC BOYD"``).
    """

    tokens: tuple[str, ...]
    token_set: frozenset[str]
    levels: frozenset[str]
    qualifiers: frozenset[str]
    numbers: frozenset[str]
    compact: str
    hint: Level
    says_school: bool = False
    affiliations: frozenset[str] = frozenset()
    system: bool = False
    implied: frozenset[str] = frozenset()
    school_of: bool = False
    codes: frozenset[str] = frozenset()
    district_numbers: frozenset[str] = frozenset()
    public_school: bool = False
    names_kind: bool = False
    directions: frozenset[str] = frozenset()
    devoted: bool = False
    one_school: bool = False
    school_named: bool = False
    qualifier_first: bool = False
    grades: tuple[int, int] | None = None
    forenames: int = 0
    forenames_sure: bool = False
    plurals: frozenset[str] = frozenset()
    possessives: frozenset[str] = frozenset()
    letters: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        """True when nothing identifying is left (``"Schools"``, ``"(Closed)"``)."""
        return not (self.tokens or self.numbers or self.qualifiers or self.levels)

    @property
    def context_numbers(self) -> frozenset[str]:
        """The numbers that name a district: :attr:`district_numbers` and the codes'."""
        if not self.codes:
            return self.district_numbers
        return self.district_numbers | {code.split(" ", 1)[1] for code in self.codes}


# Typographic quotes, dashes and spaces, by code point, mapped to ASCII.
_TYPOGRAPHY: Final = str.maketrans(
    {
        **dict.fromkeys(map(chr, (0x2018, 0x2019, 0x02BC, 0x0060, 0x00B4)), "'"),
        **dict.fromkeys(map(chr, (0x201C, 0x201D)), '"'),
        **dict.fromkeys(map(chr, (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015)), "-"),
        chr(0x00A0): " ",
    }
)
_AMPERSAND: Final = re.compile(r"&|\+")
_DOTTED: Final = re.compile(r"\b(?:[a-z]\.){2,}")
_BOARD_OF_ED: Final = re.compile(r"\bb(?:oar)?d\.?\s+of\s+ed(?:uc(?:ation)?)?\b\.?")
_DEPARTMENT_OF_ED: Final = re.compile(r"\bdep(?:t|artment)\.?\s+of\s+ed(?:uc(?:ation)?)?\b\.?")
# "No. 5", "#5", "Number 5", and Colorado's "No. Re-1J", "No. RJ1", "No. Re 1" and
# "N. 14".
_NUMBER_MARK: Final = re.compile(
    r"#\s*(?=\d)|\b(?:no|nos|num|number)\.?\s*(?=(?:rj|re|r|c|j|d|u)?[-\s]?\d)"
    r"|\bn\.\s*(?=\d+\b)"
)
_TOKEN: Final = re.compile(r"[^\W_]+")
_COMPOSITE: Final = re.compile(r"([a-z]{1,4})(\d+[a-z]?)")
_NUMBER: Final = re.compile(r"(\d+)([a-z]?)")
_ROMAN: Final = re.compile(r"x{0,3}(?:ix|iv|v?i{0,3})")
_ROMAN_VALUES: Final = {"i": 1, "v": 5, "x": 10}
_LONE_ROMAN: Final = frozenset({"i", "v", "x"})
_STEM_MIN_LENGTH: Final = 4
_DIGIT: Final = re.compile(r"\d")
_POSSESSIVE: Final = re.compile(r"(?<=[a-z])'s\b")
_MOUNTAIN_BEFORE_HYPHEN: Final = re.compile(r"(?<=[a-z] )mt\.?(?=-[a-z])")
_CACHE_SIZE: Final = 1 << 19
_PARSED: dict[str, "_Parsed"] = {}
_DISTRICT_FORMS: dict[str, "NameForm"] = {}
_SCHOOL_FORMS: dict[str, "NameForm"] = {}
_LEVEL_LETTERS: Final = {"h": "high", "m": "middle", "e": "elementary"}
"""New Hampshire's level letters: the NCES splits one school into records by level
(``"Great Bay Charter School (H)"``, ``"(M)"``, ``"(E)"``)."""
_LEVEL_LETTER_AFTER: Final = frozenset({"school", "academy", "charter"})
_CONTEXT_WORDS: Final = frozenset(
    {*lexicon.SAINT_FORMS, "el", "h", "j", "hi", "pre", "cs", "co", "jr", "early", "ex", "pk"}
    | {"con", "cnt", "mt", "tech"}
).union(_LEVEL_LETTERS)
# "Ex. Vill." is Ohio's "Exempted Village".
_EX_VILLAGE: Final = frozenset({"vill", "vil", "village", "vlg"})
# Words after which "Pk" is still prekindergarten ("David Ellis Academy PK",
# "Teen Parent Program - PK"), besides levels, designators and school nouns.
_PK_AFTER: Final = frozenset({"program", "programs", "and", "prekindergarten"})
_LEVEL_JOINS: Final = frozenset({"senior", "high", "the"})
_LEADING_FIRST: Final = frozenset(phrase[0] for phrase in lexicon.LEADING_DESIGNATORS)
_WEAK_LAST: Final = frozenset(phrase[-1] for phrase in lexicon.WEAK_DESIGNATORS)
_IS_WORD, _IS_LEVEL, _IS_QUALIFIER = 0, 1, 2
_WORD_CLASSES: dict[str, tuple[int, str]] = {}

# Words that end a name before "St" means Street rather than Saint.
_NOT_A_SAINT: Final = (
    frozenset(lexicon.LEVELS)
    | lexicon.STRONG_DESIGNATORS
    | lexicon.QUALIFIERS
    | lexicon.SCHOOL_NOUNS
    | {"sch", "schl", "schs", "el", "elem", "hs", "ms", "es", "and", "of", "junior", "senior"}
    | {"jr", "sr", "middle", "high", "elementary", "primary", "intermediate", "campus", "annex"}
    | {"charter", "magnet", "stem", "learning", "early", "alternative", "career", "technical"}
    | {"vocational", "juniorhigh", "kindergarten", "prekindergarten", "preparatory"}
    | lexicon.AFFILIATIONS
)
_SCHOOL_WORDS: Final = frozenset({"sch", "schl", "school", "schools", "schs"})


def fold(text: str) -> str:
    """Return ``text`` case-folded, with accents dropped and typography made ASCII."""
    if not text.isascii():
        text = unicodedata.normalize("NFKD", text.translate(_TYPOGRAPHY))
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.casefold()


def roman_value(token: str) -> int | None:
    """Return the value of a Roman numeral from 1 to 39, or ``None``."""
    if not token or token.strip("ivx") or not _ROMAN.fullmatch(token):
        return None
    total = 0
    previous = 0
    for ch in reversed(token):
        value = _ROMAN_VALUES[ch]
        total = total - value if value < previous else total + value
        previous = max(previous, value)
    return total


_DIRECTIONAL: Final = re.compile(
    r"(?P<before>^\s*|[-/(,;:@]\s*|\d\s+|\b(?:of|at|and)\s+)"
    r"(?P<abbr>ne|nw|se|sw|no|so|[nsew])(?:(?P<dot>\.)\s*|\s+)"
    r"(?=(?P<next>[a-z]+)\b)"
)
_DIRECTION_PAIR: Final = re.compile(
    r"(?P<before>^\s*|[-(,;:@]\s*|\d\s+|\b(?:of|at|and)\s+)"
    r"(?P<one>ne|nw|se|sw|[nsew])\.?\s*/\s*(?P<two>ne|nw|se|sw|[nsew])(?:\.\s*|\s+)(?=[a-z]{2})"
)
"""Two directions joined by a slash before a name: ``"E./N. Providence"`` names East
Providence and North Providence together."""
_PART_DIRECTION: Final = re.compile(
    r"(?P<abbr>ne|nw|se|sw|no|so|[nsew])(?:(?P<dot>\.)\s*|\s+)(?=(?P<next>[a-z]+)\b)",
    re.IGNORECASE,
)
_NEXT_MIN: Final = (2, 3)
"""The shortest word after a direction of one letter and of two. A letter before
another letter is an initial (``"E H Gentry"``, ``"W. D. Hall"``), and a two-letter
direction needs a longer word after it: ``"Se Do Mo Cha"`` and ``"No KY"`` are not
directions, ``"SE Polk"``, ``"NW Webster"`` and ``"SE of Saline"`` are."""
_SHORT_PLACE_WORDS: Final = frozenset({"of", *lexicon.SAINT_FORMS, "mt", "ft", "pt"})
"""Short words a town's name begins with after a direction whatever their length:
``"SE of Saline"``, ``"So. St. Paul"``, ``"N. Mt. Vernon"``, ``"W. Ft. Worth"``."""


_KIND_AFTER_LETTER: Final = frozenset(
    {"prep", "preparatory", "academy", "acad", "school", "schools", "sch", "learning"}
    | {"charter", "elementary", "elem", "el", "middle", "mid", "high", "hi", "junior", "jr"}
    | {"senior", "sr", "hs", "ms", "es", "jhs", "primary", "intermediate", "kindergarten"}
)
"""Words that say what kind of school a name is. A letter before one is part of a
name, not a direction: ``"E Prep"`` is a school network, and NCES writes a
direction before a school's kind nowhere but ``"N Campus"``."""


def _spelled(abbr: str, following: str, *, dotted: bool, after: str) -> str | None:
    """The direction ``abbr`` stands for before the word ``following``, or ``None``.

    ``after`` is what comes before it: ``""`` at the start of the text or of a
    part, else the separator, number or word (``"of"``, ``"at"``, ``"and"``).
    """
    word = after.rstrip()
    if (
        following == "and"  # "S & J Sanitation", "T & S Brass": initials
        or (len(abbr) == 1 and following in _KIND_AFTER_LETTER)  # "E Prep"
        or (len(following) < _NEXT_MIN[len(abbr) - 1] and following not in _SHORT_PLACE_WORDS)
        or (abbr == "no" and not dotted)  # "No Limits Academy"
        or (abbr == "so" and not dotted and word[-1:].isalnum())  # "College of So NV"
        or (word == "and" and not dotted)
    ):
        return None
    return lexicon.DIRECTION_ABBREVIATIONS[abbr]


def _direction_pair(match: re.Match[str]) -> str:
    """The replacement of one :data:`_DIRECTION_PAIR` match: both directions spelled out."""
    spelled = lexicon.DIRECTION_ABBREVIATIONS
    return f"{match['before']}{spelled[match['one']]}/{spelled[match['two']]} "


def _direction(match: re.Match[str]) -> str:
    """The replacement of one :data:`_DIRECTIONAL` match: the direction, or the text as it was."""
    before = match["before"]
    spelled = _spelled(match["abbr"], match["next"], dotted=match["dot"] is not None, after=before)
    return match.group(0) if spelled is None else f"{before}{spelled} "


def _part_direction(part: str) -> str:
    """``part`` of a listing with a direction at its start spelled out (``"N Campus"``).

    A listing's parts are joined by spaces into the name it is matched as, so a
    direction that begins a part (``"Lake Zurich Middle - N Campus"``) would
    otherwise read as a middle initial.
    """
    found = _PART_DIRECTION.match(part)
    if found is None:
        return part
    abbr = found["abbr"]
    spelled = _spelled(
        abbr.casefold(), found["next"].casefold(), dotted=found["dot"] is not None, after=""
    )
    if spelled is None:
        return part
    return f"{spelled.capitalize() if abbr[0].isupper() else spelled} {part[found.end() :]}"


def expand_directions(text: str) -> str:
    """Spell out the abbreviated directions in folded ``text`` where a direction stands.

    ``"e. lansing"`` becomes ``"east lansing"``, and so do ``"pontiac-w
    holliday"`` (``"pontiac-west holliday"``), ``"usd 251 n. lyon county"``,
    ``"school of n. bennington"``, NCES's ``"school of no.bennington"``, ``"sw
    livingston"``, ``"so. burlington"``, ``"so. st. paul"`` and ``"n.e. polk"``
    once its dots are closed up (``"ne polk"``). A direction stands at the start
    of the text or of a part of it (after ``-``, ``/``, ``(``, ``,``, ``:``,
    ``;`` or ``@``), after a number, and after ``of``, ``at`` or ``and`` (the
    last only with its dot: ``"Cumberland & N. Yarmouth"``), with a word after
    it. Elsewhere a letter is a middle initial
    (``"harry s. truman"``, ``"joel e. barber"``, Chicago's ``"davis n elem
    school"``), and before another initial or ``and`` it is an initial too
    (``"e h gentry"``, ``"s and j"``). ``No`` is North only with its dot, ``So``
    with its dot or at the start (``"SO SIOUX CITY"``). Two directions joined by
    a slash are both spelled out (``"e./n. providence"`` is ``"east/north
    providence"``): such a listing names two towns, and no record says both.
    """
    if "/" in text:
        text = _DIRECTION_PAIR.sub(_direction_pair, text)
    return _DIRECTIONAL.sub(_direction, text)


_POSSESSIVE_WORD: Final = re.compile(r"([a-z]+)'s\b")
_DOTTED_INITIALS_MAX: Final = 3
_COMPASS_PAIRS: Final = frozenset({"ne", "nw", "se", "sw"})
_SPELLED_OUT_MIN: Final = 3
_NO_INITIALS: Final = frozenset({"us", "usa"})
"""Dotted letters that are no one's initials whatever follows (``"U.S. Naval Academy"``);
nor are three that spell an abbreviation out (``"N.Y.C. Department of Education"``)."""
_NEXT_WORD: Final = re.compile(r"\s*([a-z]{2,})\b")
_LAST_WORD: Final = re.compile(r"([a-z]+)\.?$")
_NAME_STARTS: Final = frozenset("(/-,;:@&")
_TITLES: Final = frozenset(
    {"dr", "doctor", "gen", "general", "gov", "governor", "pres", "president", "sen"}
    | {"senator", "judge", "rev", "reverend", "father", "sister", "capt", "captain", "col"}
    | {"colonel", "lt", "sgt", "adm", "admiral", "mayor", "coach", "chief"}
)
"""Titles a person's name may begin with (``"Dr. Charles Drew"``, ``"Father Ryan"``):
part of the forenames a list leaves out (see :func:`forenames`)."""
_BEFORE_INITIALS: Final = _TITLES | {"at", "the", "and", "to", "by"}
_NOT_A_NAME: Final = _NOT_A_SAINT | _KIND_AFTER_LETTER | {"for", "at", "in", "the", "to"}
"""Words no person's name is: after dotted letters, they keep the letters one word."""


class _Raw(NamedTuple):
    """A text split into letter and digit runs (:func:`_raw_tokens`)."""

    tokens: list[str]
    has_digit: bool
    initials: frozenset[int] = frozenset()
    """The positions of single letters written with a dot (``"J. I. Watson"``,
    ``"R.D. White"``): a person's initials, never a Roman numeral."""
    possessives: frozenset[str] = frozenset()
    """The words written with an apostrophe's ``s`` (``king`` for ``"King's Academy"``)."""


_NO_POSITIONS: Final[frozenset[int]] = frozenset()
_LETTER_DOT: Final = re.compile(r"(?<![^\W_])[^\W\d_]\.")
"""A single letter written with a dot (``"J."``, not the ``"St."`` of a word)."""


def _dotted(match: re.Match[str]) -> str:
    """A dotted group of letters as one word (``"i.s.d."`` to ``isd``), or as initials.

    Two or three letters before a person's name are the person's initials, and
    stay single letters with their dots (``"j.f. kennedy"`` to ``"j. f. kennedy"``,
    ``"dr. w.j. creel"``, ``"robert j.c. rice"``): where a name begins (at the
    start, after a separator, a title or a joining word) or after a forename, and
    before a word that is no school's kind, level or designator. Elsewhere, and
    for a compass pair (``"n.e."``), the country (``"u.s."``) and three letters
    that spell an abbreviation out (``"n.y.c."``), the letters close up:
    ``"Premier H.S. of Tyler"``, ``"Genesee I.S.D."``, ``"A.C.E. Academy"``, ``"U.S.
    Naval Academy"``.
    """
    group = match.group(0)
    letters = group.replace(".", "")
    if (
        len(letters) > _DOTTED_INITIALS_MAX
        or letters in _COMPASS_PAIRS
        or letters in _NO_INITIALS
        or (len(letters) >= _SPELLED_OUT_MIN and letters in lexicon.EXPANSIONS)
    ):
        return letters
    text = match.string
    following = _NEXT_WORD.match(text, match.end())
    if following is None or following.group(1) in _NOT_A_NAME:
        return letters
    before = text[: match.start()].rstrip()
    if before and before[-1] not in _NAME_STARTS and not before[-1].isdigit():
        last = _LAST_WORD.search(before)
        word = "" if last is None else last.group(1)
        if word not in _BEFORE_INITIALS and word not in GIVEN_NAMES:
            return letters
    return " ".join(f"{letter}." for letter in letters) + " "


def _raw_tokens(text: str) -> _Raw:
    """Split folded ``text`` into letter and digit runs; also say whether it has digits."""
    text = fold(text)
    if "&" in text or "+" in text:
        text = _AMPERSAND.sub(" and ", text)
    possessives: frozenset[str] = frozenset()
    if "'" in text:
        possessives = frozenset(_POSSESSIVE_WORD.findall(text))
        text = _POSSESSIVE.sub("", text).replace("'", "")
    if "mt" in text and "-" in text:
        # "EAGLE MT-SAGINAW ISD": a Mt that ends one name of a pair is Mountain.
        text = _MOUNTAIN_BEFORE_HYPHEN.sub("mountain", text)
    dotted = "." in text
    if dotted:
        text = _DOTTED.sub(_dotted, text)
        if " of ed" in text:
            text = _of_education(text)
    elif " of ed" in text:
        text = _of_education(text)
    has_digit = _DIGIT.search(text) is not None
    if has_digit:
        text = _NUMBER_MARK.sub(" ", text)
    text = expand_directions(text)
    if dotted and _LETTER_DOT.search(text) is not None:
        tokens, initials = _dotted_tokens(text)
    else:
        tokens, initials = _TOKEN.findall(text), _NO_POSITIONS
    if not has_digit:
        return _Raw(tokens, False, initials, possessives)
    tokens, initials = _unglued(tokens, initials)
    return _Raw(tokens, True, initials, possessives)


def _dotted_tokens(text: str) -> tuple[list[str], frozenset[int]]:
    """The letter and digit runs of ``text``, and the positions of letters written with a dot."""
    tokens: list[str] = []
    marked: list[int] = []
    for found in _TOKEN.finditer(text):
        token = found.group(0)
        if len(token) == 1 and text[found.end() : found.end() + 1] == ".":
            marked.append(len(tokens))
        tokens.append(token)
    return tokens, frozenset(marked) if marked else _NO_POSITIONS


def _unglued(tokens: list[str], initials: frozenset[int]) -> tuple[list[str], frozenset[int]]:
    """``tokens`` with a prefix glued to its number split off (``"r4"`` to ``r``, ``4``).

    Only the prefixes of :data:`lexicon.COMPOSITE_PREFIXES`; the positions of the
    dotted letters ``initials`` move with them.
    """
    split: list[str] = []
    moved: list[int] = []
    for i, token in enumerate(tokens):
        if i in initials:
            moved.append(len(split))
        if token[0].isalpha() and not token.isalpha():
            glued = _COMPOSITE.fullmatch(token)
            if glued and glued.group(1) in lexicon.COMPOSITE_PREFIXES:
                split.extend(glued.groups())
                continue
        split.append(token)
    return split, frozenset(moved) if moved else _NO_POSITIONS


def _of_education(text: str) -> str:
    """Spell out ``"Bd. of Ed."`` and ``"Dept. of Ed."`` as the bodies they name."""
    text = _BOARD_OF_ED.sub(" board of education ", text)
    return _DEPARTMENT_OF_ED.sub(" department of education ", text)


def _saint_or_street(token: str, following: str | None) -> str:
    """``St`` is Saint before a name (``St Marys``), Street before a school word or at the end.

    The word after it is read through its abbreviation (``St. Intermed.``, ``St
    JHS``), and a single letter is never a saint's name (``Elm St H S``).
    """
    saint, street = lexicon.SAINT_FORMS[token]
    if following is None or len(following) == 1 or not following.isalpha():
        return street
    head = lexicon.EXPANSIONS.get(following, (following,))[0]
    if head in _NOT_A_SAINT or following in _NOT_A_SAINT:
        return street
    return saint


def _number(token: str) -> str:
    """Drop leading zeros from a number token (``"007"`` to ``"7"``, ``"028j"`` to ``"28j"``)."""
    if token.isdigit():
        return str(int(token))
    parts = _NUMBER.fullmatch(token)
    if parts is None:
        return token
    return str(int(parts.group(1))) + parts.group(2)


def _special(  # noqa: PLR0911, PLR0912 - one branch and return per spelling rule
    word: str, out: list[str], following: str | None, after: str | None
) -> int:
    """Apply the context-dependent spelling rules to ``word``; return words consumed."""
    if word in lexicon.SAINT_FORMS:
        out.append(_saint_or_street(word, following))
        return 1
    if word == "el" and out and (following is None or following in _SCHOOL_WORDS):
        out.append("elementary")
        return 1
    if word == "h" and following == "s" and (after is None or after in _SCHOOL_WORDS or out):
        # After a name, "H S" is High School whatever follows ("Premier H S of
        # Tyler", "New Trier Township H S Winnetka"); first, it is a person's
        # initials unless a school word or nothing follows ("H S Thompson").
        out.extend(("high", "school"))
        return 2
    if (
        word == "j"
        and following == "h"
        and (out or after is None or after == "s" or after in _NOT_A_NAME)
    ):
        # First and before a name, "J H" is a person's initials ("J.H. Williams
        # Middle School"), as "H S" is.
        out.extend(("junior", "high"))
        if after == "s":
            out.append("school")
            return 3
        return 2
    if word == "hi" and ((out and out[-1] in {"junior", "senior"}) or following in _SCHOOL_WORDS):
        out.append("high")
        return 1
    if word == "pre" and following in {"k", "kindergarten", "kinder", "school"}:
        out.append("prekindergarten")
        return 2
    if word == "cs" and out and (following is None or following.isalpha()):
        # Pennsylvania's "Penn Hills CS of Entrepreneurship", "Propel CS-Homestead";
        # a number after it is New York's community school ("CS 211").
        out.extend(("charter", "school"))
        return 1
    if word == "co" and following == "op":
        # "Co-op" and "Coop" are one word: New Hampshire's "Oyster River Coop School
        # District", Florida's "Youth Co-op Charter School".
        out.append("cooperative")
        return 2
    if word == "jr" and out and out[-1] == "king":
        # "Martin Luther King Jr High School" is a high school named for King.
        out.append("jr")
        return 1
    if word == "early" and following in lexicon.EARLY_PROGRAMS:
        # "Early Learning Center" and "Early Childhood Center" are prekindergarten.
        out.append("prekindergarten")
        return 1
    if word == "ex" and following in _EX_VILLAGE:
        out.append("exempted")
        return 1
    if word == "pk" and _pk_is_park(out, following):
        out.append("park")
        return 1
    if word in _LEVEL_LETTERS and following is None and out and out[-1] in _LEVEL_LETTER_AFTER:
        # "Great Bay Charter School (H)": the letter that ends a school's name is its level.
        out.append(_LEVEL_LETTERS[word])
        return 1
    read = _in_context(word, out, following)
    if read is None:
        return 0
    out.append(read)
    return 1


_CONSOLIDATED_BEFORE: Final = _SCHOOL_WORDS | {"corp", "corporation", "district", "dist", "sd"}
_CENTER_AFTER: Final = frozenset(
    {"career", "tech", "technical", "technology", "vocational", "learning", "training", "and"}
)
_MOUNTAIN_BEFORE: Final = _NOT_A_SAINT | {
    "independent",
    "unified",
    "consolidated",
    "community",
    "cooperative",
}
"""Words before which a name's ``Mt`` ends it, so is Mountain: a designator, a legal
form, a qualifier, a level, a school noun, an affiliation (``"Blue Mt Christian
School"``, ``"Monument Mt Regional High"``, ``"Eagle Mt ISD"``). Not ``Union``:
``"Winfield-Mt Union"`` is Mount Union."""


def _in_context(word: str, out: list[str], following: str | None) -> str | None:
    """Indiana's ``Con`` and ``Cnt``, and the ``Mt`` that ends a name: how to read them here.

    NCES writes Indiana's districts ``"Bartholomew Con School Corp"``,
    ``"Southwestern-Jefferson Co Con"`` and ``"Brownstown Cnt Com Sch Corp"``:
    ``Con`` after a name and before a school word, or ending it, is
    Consolidated (``"Con Amore School"`` is a name); ``Cnt`` is Central before
    another word, and Center where it ends a name or follows a career or
    technical word (``"Pontotoc Ridge Career & Tech. Cnt."``). ``Mt`` is Mount
    before a name (``"Mt. Pleasant"``, ``"Our Lady of Mt Carmel"``) and Mountain
    after one where the name ends: before a designator, a level, a school noun
    or an affiliation, or at the end (``"Blue Mt Christian School"``, ``"Eagle
    Mt ISD"``); NCES's ``"EAGLE MT-SAGINAW ISD"`` is caught before the hyphen goes
    (:func:`_raw_tokens`). ``Tech`` after ``Voc`` or ``Vocational`` is Technical
    (``"Tri-County Regional Voc Tech"`` for ``"Tri-County Regional Vocational
    Technical"``); elsewhere it may be Technology, and stays as written. Returns
    ``None`` where the plain expansion applies.
    """
    if word == "tech":
        return "technical" if out and out[-1] == "vocational" else None
    if word == "con":
        consolidated = out and (following is None or following in _CONSOLIDATED_BEFORE)
        return "consolidated" if consolidated else None
    if word == "cnt":
        center = following is None or (out and out[-1] in _CENTER_AFTER)
        return "center" if center else "central"
    if word == "mt" and out and _ends_a_name(following):
        return "mountain"
    return None


def _ends_a_name(following: str | None) -> bool:
    """True when a word before ``following`` ends a name (see :data:`_MOUNTAIN_BEFORE`)."""
    if following is None:
        return True
    head = lexicon.EXPANSIONS.get(following, (following,))[0]
    return head in _MOUNTAIN_BEFORE or following in _MOUNTAIN_BEFORE


def _pk_is_park(out: list[str], following: str | None) -> bool:
    """``Pk`` is Park after a name (``"Woodland Pk"``, ``"Washington Pk Campus"``).

    It stays prekindergarten before a grade (``"PK-8"``), at the start, and after
    a level, a designator, a school noun or a program (``"Academy PK"``).
    """
    if not out or (following is not None and following[0].isdigit()):
        return False
    before = out[-1]
    return before.isalpha() and before not in _NOT_A_SAINT and before not in _PK_AFTER


def _spelled_number(raw: Sequence[str], i: int, out: Sequence[str]) -> str | None:
    """The number ``raw[i]`` spells where it is a district's number, else ``None``.

    After ``District``, ``Unit`` or ``Number`` (``"Spartanburg District Seven"``),
    or ending a name after its first word, designators aside (``"Richland One"``,
    ``"Florence One Schools"``): see :data:`lexicon.SPELLED_NUMBERS`.
    """
    value = lexicon.SPELLED_NUMBERS.get(raw[i])
    if value is None or not out:
        return None
    if out[-1] in lexicon.SPELLED_NUMBER_BEFORE:
        return value
    if all(word in lexicon.SPELLED_NUMBER_AFTER for word in raw[i + 1 :]):
        return value
    return None


def _canonical(raw: list[str], initials: frozenset[int] = _NO_POSITIONS) -> tuple[list[str], bool]:
    """Map raw tokens to canonical words, using the neighbours where a word is ambiguous.

    Also says whether a Roman numeral or a spelled number became a number. A
    letter at one of the positions ``initials`` was written with a dot, a
    person's initial: ``"J. I. Watson"`` and ``"C.V. Koogler"`` are men, where
    ``"Ava R-I"`` and ``"Grain Valley R-V"`` are numbered districts.
    """
    out: list[str] = []
    roman = False
    count = len(raw)
    expansions = lexicon.EXPANSIONS
    i = 0
    while i < count:
        token = raw[i]
        if token in _CONTEXT_WORDS:
            used = _special(
                token,
                out,
                raw[i + 1] if i + 1 < count else None,
                raw[i + 2] if i + 2 < count else None,
            )
            if used:
                i += used
                continue
        expanded = expansions.get(token)
        if expanded is not None:
            out.extend(expanded)
        elif token[0].isdigit():
            out.append(_number(token))
        elif (
            i not in initials
            and (value := roman_value(token)) is not None
            and (token not in _LONE_ROMAN or (out and out[-1] in lexicon.NUMBER_CONTEXT))
            # A pope's numeral ("St. John XXIII") is his name's, not a number.
            and not (out and out[-1] in lexicon.POPE_NAMES)
        ):
            out.append(str(value))
            roman = True
        elif (spelled := _spelled_number(raw, i, out)) is not None:
            out.append(spelled)
            roman = True
        else:
            out.append(token)
        i += 1
    if "intermediate" in out:
        _intermediate_district(out)
    if "state" in out:
        _state_school(out)
    if _LEVEL_JOINS.isdisjoint(out):
        return out, roman
    return _join_levels(out), roman


_STATE_SCHOOL: Final = frozenset({"school", "schools"})


def _state_school(words: list[str]) -> None:
    """Drop the ``State`` of a name that ends ``State School``, in place.

    Missouri's state schools for the severely disabled are the lists'
    ``"Maple Valley State School"`` and ``"Lakeview Woods State School"`` and
    NCES's ``"MAPLE VALLEY SCHOOL"`` and ``"LAKEVIEW WOODS SCHOOL"``. A name that
    is only ``"State Schools"`` keeps it; one where ``State`` is not the last word
    before the closing ``School`` (``"Ohio State School for the Blind"``) too.
    """
    if words[-2:-1] == ["state"] and words[-1] in _STATE_SCHOOL and _has_name(words[:-2]):
        del words[-2]


_INTERMEDIATE_DISTRICT: Final = ("intermediate", "school", "district")
_INTERMEDIATE_END: Final = ("intermediate", "district")


def _intermediate_district(words: list[str]) -> None:
    """Read Michigan's intermediate school districts as NCES names them, in place.

    NCES writes ``"Washtenaw ISD"`` and ``"Barry ISD"``; the districts and the
    lists write ``"Washtenaw Intermediate School District"``, ``"Washtenaw Int
    School District"`` or ``"Kent Intermediate District"``. Canonically ``ISD``
    is ``independent school district`` (Texas's), and no Texas district is an
    intermediate one, so after a name the intermediate phrase is read so too,
    not as a school's level. At the start of a name it stays: Minnesota's
    ``"Intermediate School District 287"`` is another kind of body than its
    ``"ISD 287"`` would be.
    """
    count = len(words)
    for i in range(1, count - 1):
        if words[i] != "intermediate":
            continue
        if tuple(words[i : i + 3]) == _INTERMEDIATE_DISTRICT or (
            i + 2 == count and tuple(words[i:]) == _INTERMEDIATE_END
        ):
            words[i] = "independent"
            if words[i + 1] == "district":
                words.insert(i + 1, "school")
            return


def _join_levels(words: list[str]) -> list[str]:
    """Fold ``junior high`` into one level and ``senior high`` into ``high``; drop ``the``."""
    out: list[str] = []
    count = len(words)
    for i, word in enumerate(words):
        following = words[i + 1] if i + 1 < count else None
        if word == "senior" and following == "high":
            continue
        if word == "senior" and following is None and out:
            out.append("high")
        elif word == "high" and out and out[-1] == "junior":
            out[-1] = "juniorhigh"
        elif word != "the":
            out.append(word)
    return out


class _Parsed(NamedTuple):
    """A name after canonical words and numbers, before designators are stripped.

    ``coded`` says the name begins with a district code (``"USD 320 Wamego"``,
    ``"RE-2 Woodland Park"``) or holds a code of a series (``"RSU 13"``): it names
    a district, or a school within one.
    """

    words: tuple[str, ...]
    numbers: frozenset[str]
    leading: tuple[str, ...]
    implied: frozenset[str] = frozenset()
    codes: frozenset[str] = frozenset()
    district_numbers: frozenset[str] = frozenset()
    coded: bool = False
    possessives: frozenset[str] = frozenset()
    """The words written with an apostrophe's ``s`` (:attr:`_Raw.possessives`)."""


def _legal_suffix(words: list[str]) -> tuple[list[str], frozenset[str]]:
    """Drop the legal description Colorado's numbered district names end with.

    The CCD spells them ``"Cherry Creek School District No. 5 in the county of
    Arapah"`` and ``"Aurora Joint District No. 28 of the counties of Adams and
    A"``: the state's legal form, cut at 60 characters. The description goes.
    When nothing else names the district (``"School District No. 1 in the county
    of Denver and State of C"``), the county's name stays in its place and the
    name implies ``County``: a listing may say it or leave it out. ``the`` is
    already gone, so the description starts ``in county`` or ``of counties``.
    """
    for i in range(len(words) - 1):
        word, following = words[i], words[i + 1]
        if (word == "in" and following.startswith("cou")) or (
            word == "of" and following.startswith("count")
        ):
            head = words[:i]
            if _has_name([w for w in head if w not in lexicon.STRONG_DESIGNATORS]):
                return head, frozenset()
            rest = words[i + 2 :]
            if rest[:1] == ["of"]:
                rest = rest[1:]
            place = list(itertools.takewhile(lambda w: w not in {"and", "state"}, rest))
            return [*place, *head], frozenset({"county"})
    return words, frozenset()


_NO_NUMBERS: Final[frozenset[str]] = frozenset()
_SERIES_FIRST: Final = frozenset(phrase[0] for phrase, _series in lexicon.DISTRICT_SERIES)


class DistrictCodes(NamedTuple):
    """What :func:`district_codes` took out of a name's words.

    ``words`` are what is left, numbers included; ``numbers`` are those after a
    district designator at the start (a code's number is in its code); ``coded``
    says the name gives a code or begins with a district's number.
    """

    words: list[str]
    codes: frozenset[str]
    numbers: frozenset[str]
    coded: bool


def _is_number(word: str) -> bool:
    return word[0].isdigit()


def _series_at(words: Sequence[str], i: int) -> tuple[int, str] | None:
    """The length and series of a series designator and number at ``words[i]``."""
    for phrase, series in lexicon.DISTRICT_SERIES:
        end = i + len(phrase)
        if end < len(words) and _is_number(words[end]) and tuple(words[i:end]) == phrase:
            return len(phrase), series
    return None


def _leading_code_at(words: Sequence[str], i: int) -> int | None:
    """The length of a district designator run at ``words[i]`` that a number follows.

    ``"unified school district 320"`` and ``"community unit school district 300"``
    count; the run must end in ``District`` or ``Unit`` right before the number.
    """
    end: int | None = None
    j = i
    while j < len(words) and words[j] in lexicon.DISTRICT_CODE_WORDS:
        if (
            words[j] in lexicon.DISTRICT_CODE_HEADS
            and j + 1 < len(words)
            and _is_number(words[j + 1])
        ):
            end = j + 1
        j += 1
    return None if end is None else end - i


def district_codes(words: list[str]) -> DistrictCodes:
    """Take the district codes out of a name's canonical words; keep their numbers.

    A designator of a series (:data:`lexicon.DISTRICT_SERIES`) and its number
    anywhere become a code (``"regional school unit 13"`` is ``"rsu 13"``); a
    district designator and number at the start (``"unified school district
    320"``, ``"d 3"``, ``"re 2"``) name the district the rest of the words are
    about. The designator words go; the numbers stay in the words for
    :func:`_take_numbers`. A code's number is in the code; the number after a
    designator at the start is returned as a district number.
    """
    kept: list[str] = []
    codes: set[str] = set()
    numbers: set[str] = set()
    coded = False
    at_start = True  # nothing but codes and numbers so far
    i = 0
    count = len(words)
    while i < count:
        word = words[i]
        if word in _SERIES_FIRST and (found := _series_at(words, i)) is not None:
            size, series = found
            codes.add(f"{series} {words[i + size]}")
            coded = True
            i += size
            continue
        if at_start and word in lexicon.DISTRICT_CODE_WORDS:
            size_or_none = _leading_code_at(words, i)
            if size_or_none is not None:
                numbers.add(words[i + size_or_none])
                coded = True
                i += size_or_none
                continue
        if (
            at_start
            and word in lexicon.NUMBER_PREFIXES
            and i + 1 < count
            and _is_number(words[i + 1])
        ):
            coded = True
        elif not _is_number(word):
            at_start = False
        kept.append(word)
        i += 1
    return DistrictCodes(kept, frozenset(codes), frozenset(numbers), coded)


def _take_numbers(words: list[str]) -> tuple[list[str], frozenset[str], frozenset[str]]:
    """Move the numbers out of ``words``, with the letters that only prefix them.

    Also return the numbers that name a district: those after a district prefix
    (``"R-IV"``, ``"RE-1"``, ``"D49"``) or after ``District`` or ``Unit``.
    """
    kept: list[str] = []
    found: set[str] = set()
    district: set[str] = set()
    glue = False
    for i, word in enumerate(words):
        if glue:
            glue = False
            continue
        if word[0].isdigit():
            number = word
            following = words[i + 2 : i + 3]
            if (
                word.isdigit()
                and words[i + 1 : i + 2] == ["j"]
                and not (following and len(following[0]) == 1)
            ):
                # Colorado's joint districts: "28-J" and "28J" are one number; not
                # a person's initials after a number ("Dist #201 (J.S. Morton").
                number, glue = word + "j", True
            found.add(number)
            if kept and kept[-1] in lexicon.NUMBER_PREFIXES:
                kept.pop()
                district.add(number)
            elif kept and kept[-1] in lexicon.DISTRICT_CODE_HEADS:
                district.add(number)
        else:
            kept.append(word)
    return kept, frozenset(found), frozenset(district) if district else _NO_NUMBERS


def _parse(text: str) -> _Parsed:
    parsed = _PARSED.get(text)
    if parsed is not None:
        return parsed
    raw, has_digit, initials, possessives = _raw_tokens(text)
    words, roman = _canonical(raw, initials)
    leading: tuple[str, ...] = ()
    if words and words[0] in _LEADING_FIRST:
        for phrase in lexicon.LEADING_DESIGNATORS:
            size = len(phrase)
            if len(words) > size and tuple(words[:size]) == phrase:
                leading = phrase
                words = words[size:]
                break
    numbers = _NO_NUMBERS
    implied: frozenset[str] = frozenset()
    if words[-3:] == _OF_THE_CITY_OF and _has_name(words[:-3]):
        # Michigan's "Flint School District of the City of": the city's own.
        words = words[:-3]
        implied = _CITY
    if has_digit or roman:
        codes = district_codes(words)
        words, numbers, district = _take_numbers(codes.words)
        if numbers and ("in" in words or "of" in words):
            words, legal = _legal_suffix(words)
            implied |= legal
        parsed = _Parsed(
            tuple(words),
            numbers,
            leading,
            implied,
            codes.codes,
            codes.numbers | district if codes.numbers else district,
            codes.coded,
            possessives,
        )
    else:
        parsed = _Parsed(tuple(words), numbers, leading, implied, possessives=possessives)
    if len(_PARSED) < _CACHE_SIZE:
        _PARSED[text] = parsed
    return parsed


_DEPARTMENT_OF_EDUCATION: Final = ["department", "of", "education"]
_PLACE_AND_KIND: Final = 2
"""A place's name and its kind (``"new york city"``) take more words than this."""
_OF_THE_CITY_OF: Final = ["of", "city", "of"]
"""The legal form Michigan's city districts end with (``"Hamtramck School District of
the City of"``), ``the`` already dropped: the district is the city's, so the name
implies ``City`` and the words before it name it."""
_CITY: Final = frozenset({"city"})


def _has_name(words: list[str]) -> bool:
    """True when ``words`` still hold something that identifies (not just ``of``)."""
    return any(len(word) > 1 and word not in lexicon.WEAK_WORDS for word in words)


def _strip_designators(words: list[str], *, district: bool) -> list[str]:
    """Pop designators off the end of ``words`` in place; return what was popped."""
    popped: list[str] = []
    legal = False
    while words:
        last = words[-1]
        if last in lexicon.STRONG_DESIGNATORS:
            popped.append(words.pop())
            continue
        if last == "education" and words[-3:] == ["board", "of", "education"]:
            del words[-3:]
            popped.append("board of education")
            continue
        if last == "education" and words[-3:] == _DEPARTMENT_OF_EDUCATION:
            # "NYC Department of Education", "Orange County Department of Education".
            del words[-3:]
            popped.append("department of education")
            continue
        if last == "doe" and len(words) > _PLACE_AND_KIND and words[-2] in lexicon.QUALIFIERS:
            # "NYC DOE": a department of education, after a place's name and its
            # kind ("Jane Doe" is a person).
            words.pop()
            popped.append("department of education")
            continue
        if last == "board" and words[-2:] == ["school", "board"]:
            del words[-2:]
            popped.append("school board")
            continue
        if not district:
            break
        weak = _weak_designator(words, first=not legal) if last in _WEAK_LAST else None
        if weak is None:
            # "Mountain Views Unified Union", "Westside Union Elementary".
            weak = _strip_inner_legal(words)
            if weak is None:
                break
        else:
            del words[-len(weak) :]
        legal = True
        popped.append(" ".join(weak))
    return popped


_FIRST_ONLY: Final = frozenset({("central",)})
"""Weak designators that are a legal form only where they end one, and only after a
name that stands alone: ``"Greene Central School District"`` is Greene's, but
``"Washington Central Unified Union School District"`` is Washington Central's, not
Washington's, and ``"West Central Community School District"`` West Central's."""


def _weak_designator(words: list[str], *, first: bool) -> tuple[str, ...] | None:
    """The weak designator ``words`` end with, when a name is left before it.

    ``first``: no legal-form word has gone from the end yet (see :data:`_FIRST_ONLY`).
    """
    for phrase in lexicon.WEAK_DESIGNATORS:
        size = len(phrase)
        if tuple(words[-size:]) != phrase or not _has_name(words[:-size]):
            continue
        if phrase in _FIRST_ONLY and not (first and _names_alone(words[:-size])):
            continue
        return phrase
    return None


_INNER_LEGAL: Final[tuple[tuple[str, ...], ...]] = (
    ("joint", "union"),
    ("union",),
    ("joint",),
    ("consolidated",),
    ("community",),
)
"""Legal-form words a district's name says before the levels and qualifiers it ends
with, longest first: see :func:`_strip_inner_legal`."""
_UNION: Final = frozenset({("union",), ("joint", "union")})
_COMMUNITY_BEFORE: Final = frozenset({"city", "local", "high"})
_KIND_WORDS: Final = frozenset(lexicon.LEVELS) | lexicon.QUALIFIERS | {"exempted"}
"""Words a district's name ends with that say its level or its kind of place:
``"Chesapeake Union Exempted Village"`` is Chesapeake's union district."""
_NO_NAME_ALONE: Final = lexicon.DIRECTIONS | {
    "mount",
    "saint",
    "fort",
    "new",
    "port",
    "lake",
    "la",
    "las",
    "los",
    "le",
    "de",
    "del",
}
"""Words that begin a place's name and are no name alone: ``"Mount Union"`` and
``"North Union"`` are names, ``"Cupertino Union"`` is Cupertino's union district."""


def _strip_inner_legal(words: list[str]) -> tuple[str, ...] | None:
    """Drop the legal-form words of a district's name that its levels or qualifiers follow.

    California, Arizona and Vermont name districts ``"Westside Union
    Elementary"``, ``"Roseville Joint Union High"``, ``"Clay Joint Elementary"``,
    ``"Buckeye Union High School District"`` or ``"Cupertino Union"``; Ohio
    ``"Sycamore Community City"``, ``"Oak Hill Union Local"`` and ``"St Henry
    Consolidated Local"``; Illinois ``"Bremen CHSD 228"``. Closings lists say
    ``"Westside Elementary"``, ``"Sycamore Community Schools"``, ``"Oak Hill
    Schools"``: the union, the consolidation or the community is how the district
    was formed, not which it is. ``Union`` also goes from the end. The words go
    only when a name is left that stands alone (``"Mount Union Area"`` and
    ``"North Union Local"`` keep theirs), and ``Community`` only before
    ``City``, ``Local`` or ``High`` (``"Irvington Community Middle School"`` is
    a charter school's own name). Returns the words dropped, if any.
    """
    end = len(words)
    start = end
    while start and words[start - 1] in _KIND_WORDS:
        start -= 1
    for phrase in _INNER_LEGAL:
        size = len(phrase)
        if start <= size or tuple(words[start - size : start]) != phrase:
            continue
        if phrase == ("community",) and (start == end or words[start] not in _COMMUNITY_BEFORE):
            continue
        if not _names_alone(words[: start - size]):
            continue
        del words[start - size : start]
        return phrase
    return None


def _names_alone(words: Sequence[str]) -> bool:
    """True when ``words`` hold a name that stands alone (``"Cupertino"``, not ``"Mount"``)."""
    return any(
        len(word) > 1
        and word not in lexicon.WEAK_WORDS
        and word not in _NO_NAME_ALONE
        and word not in _KIND_WORDS
        for word in words
    )


def _word_class(word: str) -> tuple[int, str]:
    """Sort a word into level, qualifier or identifying word, stemming the last kind."""
    known = _WORD_CLASSES.get(word)
    if known is not None:
        return known
    if word in lexicon.LEVELS:
        known = (_IS_LEVEL, word)
    elif word in lexicon.QUALIFIERS:
        known = (_IS_QUALIFIER, word)
    elif (
        len(word) >= _STEM_MIN_LENGTH
        and word[-1] == "s"
        and word[-2] != "s"
        and word not in lexicon.WEAK_WORDS
    ):
        # A plural or possessive s goes, so St. Mary's, St Marys and St Mary meet.
        known = (_IS_WORD, word[:-1])
    else:
        known = (_IS_WORD, word)
    if len(_WORD_CLASSES) < _CACHE_SIZE:
        _WORD_CLASSES[word] = known
    return known


def stem(word: str) -> str:
    """The form a canonical ``word`` takes in :attr:`NameForm.tokens` (``campus`` to ``campu``)."""
    return _word_class(word)[1]


def affiliations_of(words: Sequence[str]) -> frozenset[str]:
    """The affiliations ``words`` name.

    One right before ``County`` or ``Parish`` is a place (``"Christian County"``),
    ``Baptist`` after ``John`` is a saint (``"St. John the Baptist"``), and
    ``Friends`` before ``of`` or ``for`` is no Quaker school (``"Friends of the
    Library"``). A child care chain's name is its brand's (:func:`chains_of`).
    """
    found: set[str] = set()
    last = len(words) - 1
    for i, word in enumerate(words):
        if word not in lexicon.AFFILIATIONS:
            continue
        if i < last and words[i + 1] in lexicon.AFFILIATION_PLACES:
            continue
        if i and words[i - 1] in lexicon.AFFILIATION_SAINTS.get(word, ()):
            continue
        if i < last and words[i + 1] in lexicon.AFFILIATION_NOT_BEFORE.get(word, ()):
            continue
        found.add(word)
    return frozenset(found) | chains_of(words) if found else chains_of(words)


_CHAIN_FIRST: Final = frozenset(phrase[0] for phrase in lexicon.CHAINS)


def chains_of(words: Sequence[str]) -> frozenset[str]:
    """The child care chains canonical ``words`` name (``"goddard school"``).

    See :data:`lexicon.CHAINS`: ``"Goddard School of Dallas"`` names the chain,
    ``"Goddard Middle School"`` does not.
    """
    if _CHAIN_FIRST.isdisjoint(words):
        return frozenset()
    found: set[str] = set()
    for i, word in enumerate(words):
        if word not in _CHAIN_FIRST:
            continue
        for phrase, brand in lexicon.CHAINS.items():
            if tuple(words[i : i + len(phrase)]) == phrase:
                found.add(brand)
    return frozenset(found)


class _Kind(NamedTuple):
    """What a listing's words say it is: see :class:`NameForm`."""

    hint: Level
    says_school: bool = False
    system: bool = False


_RECORD_KINDS: Final = {True: _Kind(Level.DISTRICT), False: _Kind(Level.SCHOOL)}


_KIND_DESIGNATORS: Final = frozenset({"school", "schools"})
_PLACE_NOUNS: Final = frozenset({"center", "campus"})
_PUBLIC_SCHOOL: Final = ["school", "public"]
_INDEPENDENT_SCHOOL: Final = ["school", "independent"]
_ONE_SCHOOL: Final = ["school"]
"""What :func:`_strip_designators` pops, last word first, off a name ending ``Public School``."""


_PLACE_AFTER_LEVEL: Final = frozenset({"township", "village", "county", "city", "town", "borough"})
"""Place qualifiers that make a level word before them a place's name: New Jersey's
``"Middle Township"``, New York's ``"Middle Village"``."""


def _place_level(words: Sequence[str]) -> bool:
    """True when ``words`` begin with a level word that names a place (``"Middle Township"``)."""
    return len(words) > 1 and words[0] in lexicon.LEVELS and words[1] in _PLACE_AFTER_LEVEL


_JOINING: Final = (lexicon.WEAK_WORDS - lexicon.AFFILIATIONS) | {"the"}
"""Words that join or rank a name's words (``and``, ``of``, ``Junior``, ``Exempted``)
rather than name anything: see :func:`qualifies`."""
_LINKS: Final = frozenset({"of", "at", "for", "in", "on", "a", "an", "to", "the", "by"})
"""Words that link one part of a name to another: a qualifier right after one names
no place before it (``"Montessori in Town"``)."""
_NAMES_NO_PLACE: Final = _JOINING | lexicon.DIRECTIONS
"""Words that name no place a place kind after them could be: ``"East Village
Elementary"`` and ``"The Village School"`` name no village."""
_STATE_WORDS: Final = frozenset(
    name.casefold() for name in lexicon.STATE_NAMES.values() if " " not in name
)
_ADDS_NOTHING: Final = (
    _JOINING
    | lexicon.GENERIC_WORDS
    | lexicon.STRONG_DESIGNATORS
    | lexicon.DISTRICT_WORDS
    | _STATE_WORDS
)
"""Words after a qualifier that add no name to it, so it still ends the name: a
designator (``"Crawford County Schools-IN"``) or a state's name (``"Kansas City
Kansas Public Schools"``)."""


def qualifies(words: Sequence[str], classes: Sequence[tuple[int, str]], i: int) -> bool:
    """True when the place qualifier ``words[i]`` qualifies the name before it.

    A qualifier is one only after the name it qualifies: ``"Toledo City"``,
    ``"Faketown City Schools"``, ``"Milford Exempted Village"``, ``"Union City
    High School"``, ``"Washington Township Middle"``, ``"Northwest Local"``,
    ``"Ludington Area Catholic School"``, ``"Laclede County R-1 Conway"``. Such
    a word says what kind of place or district the name is, which a list may
    leave out (``"Murfreesboro"`` for ``"Murfreesboro City Schools"``).
    Anywhere else the word is the name's own, and a listing that leaves it out
    names another school: one that begins a name (``"Village Christian
    Academy"`` is not ``"Christian Academy"``, ``"Town & Country Day School"``
    not ``"Country Day School"``, ``"City Academy"`` not ``"Academy"``), a kind
    of place after no place's name (``"East Village Elementary"`` is not ``"East
    Elementary"``) or after a word that links rather than names (``"Montessori
    in Town"``), and a kind of town (:data:`lexicon.TOWN_KINDS`) with more of the
    name after it than levels and words that add no name (:data:`_ADDS_NOTHING`):
    ``"Kid City Academy"`` is not ``"Kids Academy"``. ``classes`` are the words'
    :func:`_word_class`.
    """
    if i and words[i - 1] in _LINKS:
        return False
    if words[i] in lexicon.TOWN_KINDS:
        for word, (word_class, _text) in zip(words[i + 1 :], classes[i + 1 :], strict=True):
            if word_class == _IS_WORD and len(word) > 1 and word not in _ADDS_NOTHING:
                return False
    unnamed = _NAMES_NO_PLACE if words[i] in lexicon.PLACE_KINDS else _JOINING
    return any(
        word_class == _IS_WORD and len(word) > 1 and word not in unnamed
        for word, (word_class, _text) in zip(words[:i], classes[:i], strict=True)
    )


def _classes(words: Sequence[str], *, numbered: bool = False) -> list[tuple[int, str]]:
    """:func:`_word_class` of each of ``words``, a qualifier or level that names read as a name.

    A level before a place qualifier names a place (``"Middle Township"``). A
    place qualifier is one only where it ends a name after the name it
    qualifies (:func:`qualifies`); anywhere else it is a word of the name
    (``"Village Christian Academy"``, ``"Kid City Academy"``, ``"Cooperative
    Middle School"``, ``"Village Elementary"``). A name that is only a
    qualifier and a number keeps its qualifier (``"Township High School District
    214"``): its number names it.
    """
    classes = [_word_class(word) for word in words]
    if _place_level(words):
        classes[0] = (_IS_WORD, words[0])
    if numbered and all(word_class != _IS_WORD for word_class, _text in classes):
        return classes
    said = list(classes)
    for i, (word_class, _text) in enumerate(said):
        if word_class == _IS_QUALIFIER and not qualifies(words, said, i):
            classes[i] = (_IS_WORD, words[i])
    return classes


_GOVERNMENT_KINDS: Final = lexicon.QUALIFIERS & lexicon.MUNICIPAL_BODIES
"""The kinds of place a name may put first, as a government's is written: ``"Township
of Union"``, ``"City of Baker"``, ``"County of Winnebago"``."""
_KIND_OF_NAME: Final = 2
"""How many words ``"Township of"`` takes before the place's name."""
_SCHOOLS_OF: Final = ["schools", "of"]
_KIND_SCHOOLS_OF: Final = 3
"""How many words ``"City Schools of"`` takes before the place's name."""


def name_first(words: Sequence[str]) -> list[str]:
    """``words`` with a leading ``"<kind of place> of"`` put after the place's name.

    ``"Township of Union"`` and ``"Union Township"`` are one name, however NCES
    or a list orders it: New Jersey's ``"Township of Union School District"`` (Union
    County) and ``"Union Township School District"`` (Hunterdon County) are two
    townships of one name, which only where each lies tells apart, never which
    of them a listing's word order happens to repeat. So a name read either way
    has the same words and the same ``Township`` qualifier, and neither begins
    with a qualifier that names rather than qualifies
    (:attr:`NameForm.qualifier_first`). Only a kind of place
    (:data:`_GOVERNMENT_KINDS`) followed by ``of`` and a name, or by ``Schools of``
    and a name: Georgia's ``"City Schools of Decatur"`` is ``"Decatur City
    Schools"``. So is Indiana's ``"School City of Hammond"`` (and ``"School Town
    of Speedway"``), which lists call ``"City of Hammond Public Schools"`` or
    ``"Speedway Schools"``.
    """
    if len(words) > _KIND_OF_NAME and words[0] in _GOVERNMENT_KINDS:
        if words[1] == "of":
            return [*words[_KIND_OF_NAME:], words[0]]
        if len(words) > _KIND_SCHOOLS_OF and words[1:_KIND_SCHOOLS_OF] == _SCHOOLS_OF:
            return [*words[_KIND_SCHOOLS_OF:], words[0]]
    if (
        len(words) > _KIND_SCHOOLS_OF
        and words[0] in _SCHOOL_WORDS
        and words[1] in _GOVERNMENT_KINDS
        and words[2] == "of"
    ):
        return [*words[_KIND_SCHOOLS_OF:], words[1]]
    return list(words)


_POPE_TITLES: Final = frozenset({"saint", "pope"})


def _names_a_pope(words: Sequence[str]) -> bool:
    """True when ``words`` hold a pope's name and his numeral (``"Paul VI"``, ``"St. Pius X"``).

    His school is a Catholic parish's or diocese's, as a saint's is
    (:data:`lexicon.DEVOTIONS`), and may be listed without its faith: ``"Paul VI
    High School"`` for ``"PAUL VI CATHOLIC HIGH SCHOOL"``. A numeral of one letter
    is a pope's only after ``Saint`` or ``Pope``: ``"John V. Lindsay"`` is a man.
    """
    for i in range(len(words) - 1):
        numeral = words[i + 1]
        if (
            words[i] in lexicon.POPE_NAMES
            and roman_value(numeral) is not None
            and (len(numeral) > 1 or (i and words[i - 1] in _POPE_TITLES))
        ):
            return True
    return False


def _epithet(words: Sequence[str], i: int) -> str | None:
    """The token of ``words[i]`` when it is a saint's epithet (:data:`lexicon.SAINT_EPITHETS`).

    ``Baptist`` right after ``John`` (``"St. John the Baptist"``, ``the`` already
    dropped) is the saint's name, not a faith, and weighs as a name's word.
    """
    token = lexicon.SAINT_EPITHETS.get(words[i])
    if token is None or not i or words[i - 1] not in lexicon.AFFILIATION_SAINTS[words[i]]:
        return None
    return token


_FORENAMES_MAX: Final = 4
"""The most words a person's forenames, initials and title take before the surname."""
_NOT_FORENAMES: Final = (
    _NOT_A_NAME
    | lexicon.DIRECTIONS
    | lexicon.WEAK_WORDS
    | lexicon.DEVOTIONS
    | {"saint", "sainte", "mount", "fort", "our", "lady", "holy", "sacred", "blessed"}
)
"""Words that are no person's forename or surname in a school's name: a kind, a
level, a designator, a faith, a direction, a joining word, a saint's or a
devotion's (``"St. John"``, ``"Sacred Heart"``)."""
_SAINT_WORDS: Final = frozenset({"saint", "sainte"})


def _name_like(word: str, word_class: int) -> bool:
    """True when ``word`` of the class ``word_class`` may be a person's forename,
    initial or surname: any letter (the directions a letter stands for are spelled
    out by now, :func:`expand_directions`), or a word that names."""
    return (
        word_class == _IS_WORD and word.isalpha() and (len(word) == 1 or word not in _NOT_FORENAMES)
    )


def forenames(
    words: Sequence[str], classes: Sequence[tuple[int, str]], *, graded: bool = False
) -> int:
    """How many of a school name's first ``words`` may be a person's forenames.

    A person's name begins with an initial (``"J F Kennedy"``, ``"R. D.
    White"``), a given name (:data:`~snowlight.match.forenames.GIVEN_NAMES`:
    ``"Charles White"``, ``"Martin Luther King"``), a title (``"Dr. Charles
    Drew"``) or a word before an initial (``"Lyndon B Johnson"``, ``"Beatriz G
    Garza"``); the forenames run on through the words that name, at most
    :data:`_FORENAMES_MAX`, and leave a surname after them: a word that names,
    not a kind, a level, a faith or a direction (``"Grace Christian Academy"``
    and ``"Plan B Academy"`` are no one's). Which of those words are the
    forenames a list leaves out, it says itself, by the word its name begins
    with: ``"Kennedy Middle"`` for ``"John F Kennedy Middle"``, ``"King
    Elementary"`` for ``"Martin Luther King Jr Elementary"``, ``"Tatem"`` for
    ``"J. Fithian Tatem"`` (see :attr:`NameForm.forenames`). ``classes`` are the
    words' :func:`_word_class`. Two given names joined by ``and`` are one run
    (``"Lloyd & Dolly Bentsen"``), and a name with numbers is ``graded``: its lone
    ``K`` is a grade span's (``"Nettie S Freed K-8 Expeditionary"``), no initial.
    """
    count = min(len(words) - 1, _FORENAMES_MAX)
    if count < 1:
        return 0
    first = words[0]
    if (
        len(first) > 1 and first not in GIVEN_NAMES and first not in _TITLES and len(words[1]) > 1
    ) or not _name_like(first, classes[0][0]):
        # Most names: no forename, no title, no initial.
        return 0
    if first in _TITLES:
        # A title before a forename or an initial ("Dr. Charles Drew"), not alone
        # ("Chief Charlo School" is named for a man, but no forename is left out).
        second = words[1]
        if not (len(second) == 1 or second in GIVEN_NAMES) or not _name_like(second, classes[1][0]):
            return 0
    elif not (
        len(first) == 1
        or first in GIVEN_NAMES
        or (len(words[1]) == 1 and _name_like(words[1], classes[1][0]))
    ):
        return 0
    run = 1
    while run < count and (
        _in_run(words, classes, run, graded=graded) or _joins_forenames(words, classes, run)
    ):
        run += 1
    if words[run - 1] == "o":
        # "Ronald D O Neal": the O of O'Neal, which NCES writes apart, is the surname's.
        run -= 1
    while run and (
        words[run - 1] == _AND
        or not (_name_like(words[run], classes[run][0]) and len(words[run]) > 1)
    ):
        # The surname after them is a name's word: "Plan B Academy" names no one.
        run -= 1
    return run


_AND: Final = "and"
_GRADE_K: Final = "k"


def _in_run(
    words: Sequence[str], classes: Sequence[tuple[int, str]], at: int, *, graded: bool
) -> bool:
    """True when :func:`forenames`' word ``at`` may go on a run: a word that names,
    but the ``K`` of a ``graded`` name's grade span (``"K-8"``)."""
    return _name_like(words[at], classes[at][0]) and not (graded and words[at] == _GRADE_K)


def _joins_forenames(words: Sequence[str], classes: Sequence[tuple[int, str]], at: int) -> bool:
    """True when :func:`forenames`' word ``at`` is an ``and`` between two forenames:
    ``"Lloyd & Dolly Bentsen"``, ``"John and Mary Smith"``."""
    if words[at] != _AND or at + 1 >= len(words):
        return False
    before, after = words[at - 1], words[at + 1]
    return (
        (len(before) == 1 or before in GIVEN_NAMES)
        and (len(after) == 1 or after in GIVEN_NAMES)
        and _name_like(after, classes[at + 1][0])
    )


def _possessives(said: frozenset[str], tokens: Sequence[str]) -> frozenset[str]:
    """:attr:`NameForm.possessives`: the words written with an apostrophe's ``s`` (``said``),
    and a token followed by a lone ``s``, an apostrophe NCES wrote as a space
    (``"TERRY S MONTESSORI SCHOOL"`` for ``"Terry's Montessori School"``)."""
    if not said and "s" not in tokens:
        return _NO_NUMBERS
    apart = [token for token, following in itertools.pairwise(tokens) if following == "s"]
    if not said and not apart:
        return _NO_NUMBERS
    return frozenset(stem(word) for word in said).union(apart)


def _letter_runs(tokens: Sequence[str]) -> tuple[str, ...]:
    """The runs of two or more single letters in ``tokens``, each run together."""
    runs: list[str] = []
    run = ""
    for token in (*tokens, ""):
        if len(token) == 1:
            run += token
            continue
        if len(run) > 1:
            runs.append(run)
        run = ""
    return tuple(runs)


def _plurals(words: Sequence[str], classes: Sequence[tuple[int, str]]) -> frozenset[str]:
    """The tokens of ``words`` written with the ``s`` they drop: :attr:`NameForm.plurals`."""
    found = [
        text
        for i, (word, (word_class, text)) in enumerate(zip(words, classes, strict=True))
        if word_class == _IS_WORD
        and len(text) < len(word)
        and text not in _SAINT_WORDS
        and not (i and words[i - 1] in _SAINT_WORDS)
    ]
    return frozenset(found) if found else _NO_NUMBERS


def _form(parsed: _Parsed, *, district: bool, kind: _Kind) -> NameForm:
    words = list(parsed.words)
    popped = _strip_designators(words, district=district)
    words = name_first(words)
    levels: list[str] = []
    qualifiers: list[str] = []
    tokens: list[str] = []
    devoted = not lexicon.DEVOTIONS.isdisjoint(words) or _names_a_pope(words)
    classes = _classes(words, numbered=bool(parsed.numbers or parsed.codes))
    plural = False
    letters = 0
    for i, (word_class, text) in enumerate(classes):
        if word_class == _IS_WORD:
            epithet = _epithet(words, i)
            tokens.append(epithet or text)
            plural = plural or (epithet is None and len(text) < len(words[i]))
            letters += len(text) == 1
        elif word_class == _IS_LEVEL:
            levels.append(text)
        elif not (devoted and not district and text == lexicon.PARISH):
            # A saint's "Parish School" is its church's school, not a county's.
            qualifiers.append(text)
    return NameForm(
        tokens=tuple(tokens),
        token_set=frozenset(tokens),
        levels=frozenset(levels) if levels else _NO_NUMBERS,
        qualifiers=frozenset(qualifiers) if qualifiers else _NO_NUMBERS,
        numbers=parsed.numbers,
        compact="".join(tokens),
        hint=kind.hint,
        says_school=kind.says_school,
        affiliations=affiliations_of(words) | chains_of(parsed.words),
        system=kind.system,
        implied=parsed.implied,
        school_of=_school_of(parsed.words),
        codes=parsed.codes,
        district_numbers=parsed.district_numbers,
        public_school=popped[:2] == _PUBLIC_SCHOOL,
        names_kind=bool(levels)
        or not _KIND_DESIGNATORS.isdisjoint(popped)
        or not lexicon.SCHOOL_NOUNS.isdisjoint(words),
        directions=_NO_NUMBERS
        if lexicon.DIRECTIONS.isdisjoint(words)
        else lexicon.DIRECTIONS.intersection(words),
        devoted=devoted,
        one_school=popped[:1] == _ONE_SCHOOL and popped[:2] != _PUBLIC_SCHOOL,
        school_named=district and named_as_school(parsed.words),
        qualifier_first=len(words) > 1 and words[0] in lexicon.QUALIFIERS,
        forenames=0
        if district or len(tokens) < _PLACE_AND_KIND
        else forenames(words, classes, graded=bool(parsed.numbers)),
        plurals=_plurals(words, classes) if plural else _NO_NUMBERS,
        letters=_letter_runs(tokens) if letters > 1 else (),
        possessives=_possessives(parsed.possessives, tokens),
    )


_SCHOOL_NAME_NOUNS: Final = lexicon.SCHOOL_NOUNS | {"charter", "school"}


def named_as_school(words: Sequence[str]) -> bool:
    """True when canonical ``words`` name one school, or schools of one level, not a district.

    A school noun (``Academy``, ``Preparatory``, ``Charter``, ``Center``, a
    singular ``School``) or a level said of schools (``"High Schools"``) names
    schools; a district word anywhere (``District``, ``Unified``, ``Independent``,
    ``Corporation``, ``System``, ``Unit``) names a district: ``"Premier High
    Schools"``, ``"Arrow Academy"`` and ``"Orenda Charter School"`` read as one
    school, ``"Township High School District 214"``, ``"Fortuna Elementary"``
    and ``"IDEA Public Schools"`` do not.
    """
    if not lexicon.DISTRICT_WORDS.isdisjoint(words):
        return False
    if not _SCHOOL_NAME_NOUNS.isdisjoint(words):
        return True
    if "schools" not in words:
        return False
    return any(
        word in lexicon.LEVELS and following == "schools"
        for word, following in itertools.pairwise(words)
    )


def _school_of(words: Sequence[str]) -> bool:
    """True when ``School of`` or ``School for`` names one school.

    ``"Valley School of Ligonier"`` is a private school, not a bare name that
    may mean the district ``"Ligonier Valley SD"``.
    """
    if "school" not in words:
        return False
    links = lexicon.ONE_SCHOOL_LINKS
    return any(words[i] == "school" and words[i + 1] in links for i in range(len(words) - 1))


def _hint(parsed: _Parsed, popped: list[str], *, affiliated: bool) -> _Kind:
    """What the words say the name is: a district, one school, or either.

    A name with an affiliation is a district only when a designator says so that
    a private school system cannot also use: ``"Pass Christian School District"``
    is a district, but ``"Grand Rapids Christian Schools"`` is a private school or
    a group of them, never a public district. A district code (``"USD 320
    Wamego"``, ``"RSU 19"``) makes a name a district unless the rest of it names
    a school (``"RSU 13 Oceanside High School"``); ``Center`` or ``Campus`` after
    it is a place (``"USD 262 Valley Center"``). A name that ends ``Public
    School`` and says nothing else of its kind (``"Elba Public School"``) is a
    town's school system or a school of that name: either. ``Independent`` right
    before a closing ``School`` (singular) names a private school (``"The Stone
    Independent School"``), not an ISD, which a list calls ``Independent School
    District`` or ``Independent Schools``.
    """
    said = set(popped)
    if parsed.leading:
        said.update(parsed.leading)
    if popped[:2] == _INDEPENDENT_SCHOOL:
        said.discard("independent")
    district_cues = said & lexicon.DISTRICT_HINTS
    if district_cues:
        return _district_cued(parsed, said, district_cues, affiliated=affiliated)
    nouns = lexicon.SCHOOL_NOUNS.intersection(parsed.words)
    names_one = (
        # After a district code, "Center" and "Campus" are the district's place
        # ("USD 262 Valley Center", "USD 237 Smith Center"), not one school.
        bool(nouns and not (parsed.coded and nouns <= _PLACE_NOUNS))
        or "charter" in parsed.words
        or _school_of(parsed.words)
    )
    words = parsed.words[1:] if _place_level(parsed.words) else parsed.words
    has_level = any(w in lexicon.LEVELS for w in words)
    if not (names_one or has_level or affiliated):
        coded = parsed.coded and not said & lexicon.SCHOOL_DESIGNATORS
        # "Holden R-III School": only a district carries a district's number,
        # and the Kansas City lists call one "School".
        numbered = bool(parsed.district_numbers and said and said <= lexicon.SCHOOL_DESIGNATORS)
        if coded or numbered:
            return _Kind(Level.DISTRICT)
        if popped[:2] == _PUBLIC_SCHOOL:
            return _Kind(Level.UNKNOWN)
    if said & lexicon.SCHOOL_DESIGNATORS or names_one:
        return _Kind(Level.SCHOOL, says_school=True)
    if has_level:
        return _Kind(Level.SCHOOL)
    return _Kind(Level.UNKNOWN)


def _district_cued(parsed: _Parsed, said: set[str], cues: set[str], *, affiliated: bool) -> _Kind:
    """:func:`_hint` for a name whose designators say district (``Schools``, ``ISD``)."""
    if not affiliated or "public" in said or not cues <= lexicon.SYSTEM_DESIGNATORS:
        return _Kind(Level.DISTRICT)
    words = parsed.words[1:] if _place_level(parsed.words) else parsed.words
    if any(w in lexicon.LEVELS for w in words):
        return _Kind(Level.SCHOOL)
    return _Kind(Level.UNKNOWN, system=True)


def clear_caches() -> None:
    """Forget every name normalized so far (for measuring a cold index build)."""
    for cache in (_PARSED, _DISTRICT_FORMS, _SCHOOL_FORMS, _WORD_CLASSES):
        cache.clear()
    listing_forms.cache_clear()
    legal_words.cache_clear()


def record_form(name: str, *, district: bool) -> NameForm:
    """Return the form of a directory name; ``district`` strips legal-form words too."""
    cache = _DISTRICT_FORMS if district else _SCHOOL_FORMS
    form = cache.get(name)
    if form is None:
        form = _form(_parse(name), district=district, kind=_RECORD_KINDS[district])
        if len(cache) < _CACHE_SIZE:
            cache[name] = form
    return form


_TRAILING_BRACKET: Final = re.compile(r"\s*\(([^()]*)\)\s*$")
_ENTITY_ID: Final = re.compile(r"\d+")
_GRADE_SPAN: Final = re.compile(r"(?:p?k|\d{1,2})\s*-\s*(?:k|\d{1,2})", re.IGNORECASE)
_FORMER_NAME: Final = re.compile(
    r"(?:formerly|former|frm|fka|f/k/a|aka|a/k/a|dba|d/b/a|now|also\s+known\s+as)\.?\s+",
    re.IGNORECASE,
)
_COUNTY_KINDS: Final = {"county": "county", "parish": "parish", "co": "county"}
"""Designations that end a county's name, and the place qualifier each gives a name."""
_COUNTY_TAILS: Final = frozenset({"county", "parish", "borough", "city", "region", "municipality"})
"""Words NCES ends a county's name with (``"Clark County"``, ``"Orleans Parish"``,
``"Alexandria city"``, ``"Capitol Planning Region"``): not part of the county's own name."""
_LEGAL_BRACKETS: Final = frozenset({"charter"})
"""Words a district's name says in brackets for its legal form (``"COMANCHE ACADEMY
(CHARTER)"``): a listing may say them or leave them out."""
_LEGAL_INITIALS: Final = frozenset({"sda", "psad"})
"""Michigan's initials in brackets for the kind of academy a district is (``"Clara B.
Ford Academy (SDA)"``, a strict discipline academy; ``"(PSAD)"``): no name, and not
the Seventh-day Adventists a listing's ``SDA`` means."""


@dataclass(frozen=True, slots=True)
class DirectoryName:
    """A directory name read apart from the brackets NCES ends some names with.

    Attributes:
        base: the name without them: what a listing names the record by.
        county: the words of the record's county, when a bracket names it
            (``"Evergreen School District (Clark)"`` in Clark County, ``"Madison
            School District (Lenawee)"``). They tell a district from its namesakes
            in other counties, and a listing may say them or leave them out.
        county_kind: the place qualifier the county's name ends with
            (``county``, ``parish``), which a listing that says the county's words
            may say too.
        legal: legal-form words a bracket says (``charter`` for Oklahoma's
            ``"COMANCHE ACADEMY (CHARTER)"``), which a listing may say or leave out.
        second: the other names a district is known by (``"NORTH ROCKLAND"`` for
            ``"HAVERSTRAW-STONY POINT CSD (NORTH ROCKLAND)"``, ``"Berlin-Milan"``
            for ``"Edison Local (formerly Berlin-Milan)"``).
        entity: a state's entity number in brackets (Arizona's ``"(4192)"``),
            without leading zeros: no part of the name and no district number,
            but a listing that gives it names this record and no other of the
            name (:func:`entity_number`).
    """

    base: str
    county: frozenset[str] = frozenset()
    county_kind: str | None = None
    legal: frozenset[str] = frozenset()
    second: tuple[str, ...] = ()
    entity: str | None = None
    forenames: int = 0
    """How many words of a person's forenames a bracket after the surname gave,
    now before it (``2`` for ``"Kennedy (John F.) Elementary"``, read as ``"John F.
    Kennedy Elementary"``; see :func:`bracketed_forenames`)."""


_BRACKETED_FORENAMES: Final = re.compile(
    r"^\s*(?P<surname>[^()\s]+(?:\s+[^()\s]+)?)\s*\((?P<given>[^()]+)\)\s*(?P<rest>\S.*)$"
)
_FORENAME_WORDS_MAX: Final = 4
_KIND_WORDS_AFTER: Final = (
    _KIND_AFTER_LETTER
    | lexicon.LEVELS
    | lexicon.SCHOOL_NOUNS
    | _SCHOOL_WORDS
    | {"early", "magnet", "community", "continuation", "k", "center", "ctr"}
)


def bracketed_forenames(name: str) -> tuple[str, int] | None:
    """A school's name whose person's forenames NCES put in brackets after the surname.

    California and Delaware write ``"Kennedy (John F.) Elementary"``, ``"Lincoln
    (Abraham) Elementary"``, ``"Chipman (W.T.) Middle School"`` and ``"Morris
    (Evelyn I.) Early Childhood"``: one or two words of surname, the forenames in
    brackets (initials, or a given name first, see
    :data:`~snowlight.match.forenames.GIVEN_NAMES`), then the school's kind or
    level. Returns the name as a list says it, forenames first (``"John F.
    Kennedy Elementary"``), and how many words they are; ``None`` for any other
    name, such as ``"Knowledge Enlightens You (KEY) Academy"`` or ``"William
    (Bill) Roberts ECE-8 School"``.
    """
    found = _BRACKETED_FORENAMES.match(name)
    if found is None:
        return None
    given = _folded_words(found.group("given"))
    rest = _folded_words(found.group("rest"))
    if (
        not given
        or len(given) > _FORENAME_WORDS_MAX
        or not all(word.isalpha() for word in given)
        or not (given[0] in GIVEN_NAMES or any(len(word) == 1 for word in given))
        or not rest
        or rest[0] not in _KIND_WORDS_AFTER
    ):
        return None
    said = f"{found.group('given').strip()} {found.group('surname')} {found.group('rest')}"
    return said, len(given)


def split_brackets(name: str) -> tuple[str, tuple[str, ...]]:
    """``name`` without the bracketed parts it ends with, and those parts, first first.

    A school's NCES name keeps a bracket that says its level
    (``"Great Bay Charter School (H)"``), so one of a single level letter ends the
    peeling. A bracket the CCD cut open at its 60 characters goes too
    (``"Southwest Technical Education District of Yuma (ST (92705)"``). A name
    that is only a bracket is kept whole.
    """
    base = name.rstrip()
    parts: list[str] = []
    while base.endswith(")"):
        found = _TRAILING_BRACKET.search(base)
        if found is None:
            break
        inner = found.group(1).strip()
        if fold(inner) in _LEVEL_LETTERS:
            break
        base = base[: found.start()].rstrip()
        parts.append(inner)
    opened = base.rfind("(")
    if opened > base.rfind(")"):
        base = base[:opened].rstrip()
    base = base.rstrip(" -,;:")
    if not _TOKEN.search(base):
        return name, ()
    return base, tuple(reversed(parts))


def _folded_words(text: str) -> list[str]:
    return _TOKEN.findall(fold(text).replace("'", ""))


def county_words(county: str) -> tuple[list[str], str | None]:
    """The words of a county's own name and the qualifier it ends with.

    ``"Clark County"`` is ``(["clark"], "county")``, ``"Orleans Parish"``
    ``(["orleans"], "parish")``, ``"Alexandria city"`` ``(["alexandria"], None)``.
    """
    words = _folded_words(county)
    if len(words) > 1 and words[-1] in _COUNTY_TAILS:
        return words[:-1], _COUNTY_KINDS.get(words[-1])
    return words, None


def _named_county(inner: str, county: str | None) -> tuple[list[str], str | None] | None:
    """:func:`county_words` of ``county`` when the bracket ``inner`` names it, else ``None``.

    ``"Clark"`` and ``"Clark County"`` name ``"Clark County"``.
    """
    if county is None:
        return None
    said = _folded_words(inner)
    if len(said) > 1 and said[-1] in _COUNTY_KINDS:
        said = said[:-1]
    words = county_words(county)
    return words if said and said == words[0] else None


def _droppable(inner: str) -> bool:
    """True when a bracket says nothing a listing repeats.

    Arizona's entity number (``"Flagstaff Unified District (4192)"``), a school's
    grades (``"Shell Lake Elementary (3-6)"``), ``"(THE)"`` and Michigan's
    :data:`_LEGAL_INITIALS`.
    """
    words = _folded_words(inner)
    return bool(
        _ENTITY_ID.fullmatch(inner)
        or _GRADE_SPAN.fullmatch(inner)
        or words in (["the"], [])
        or (len(words) == 1 and words[0] in _LEGAL_INITIALS)
    )


def directory_name(name: str, *, district: bool, county: str | None = None) -> DirectoryName:
    """Read the brackets a directory name ends with for what each says.

    NCES ends some names with a bracket that is no part of the name a closings
    list uses. ``county`` is the record's county's name (``"Clark County"``).

    * a number (Arizona's entity number, ``"(4192)"``, kept apart as
      :attr:`DirectoryName.entity`), a school's grades (``"(K-6)"``) and
      ``"(THE)"`` go;
    * the record's county (``"(Clark)"``, ``"(Lenawee)"``, ``"(Van Buren)"``)
      only tells namesakes apart: see :attr:`DirectoryName.county`;
    * ``"(CHARTER)"`` is a legal form: see :attr:`DirectoryName.legal`;
    * for a district, any other bracket is a second name it is known by, with
      ``"formerly"``, ``"FRM"`` or ``"dba"`` before it dropped
      (``"(NORTH ROCKLAND)"``, ``"(LAKE SHORE)"``, ``"(KESHEQUA)"``,
      ``"(formerly Berlin-Milan)"``), unless it names a church or faith or
      nothing that identifies; Michigan's ``"(SDA)"`` and ``"(PSAD)"`` go
      (:data:`_LEGAL_INITIALS`);
    * a school keeps any other bracket in its name, where it says the school's
      level, campus or kind (``"(Middle)"``, ``"(North Campus)"``,
      ``"(Continuation)"``, ``"(AMISH)"``);
    * a school's person's forenames in brackets after the surname go before it
      (``"Kennedy (John F.) Elementary"`` is ``"John F. Kennedy Elementary"``,
      :func:`bracketed_forenames`).
    """
    if "(" not in name:
        return DirectoryName(name)
    forenames = 0
    if not district and (moved := bracketed_forenames(name)) is not None:
        name, forenames = moved
        if "(" not in name:
            return DirectoryName(name, forenames=forenames)
    base, parts = split_brackets(name)
    kept: list[str] = []
    entity: str | None = None
    county_said: frozenset[str] = frozenset()
    county_kind: str | None = None
    legal: set[str] = set()
    second: list[str] = []
    for inner in parts:
        if kept:
            # A bracket after one the name keeps is the name's too.
            kept.append(inner)
        elif _droppable(inner):
            entity = entity_number(inner) or entity
        elif (named := _named_county(inner, county)) is not None:
            county_said = record_form(" ".join(named[0]), district=False).token_set
            county_kind = named[1]
        elif set(_folded_words(inner)) <= _LEGAL_BRACKETS:
            legal.update(_folded_words(inner))
        elif district:
            other = _FORMER_NAME.sub("", inner, count=1) if _FORMER_NAME.match(inner) else inner
            form = record_form(other, district=True)
            if _has_name(list(form.tokens)) and not form.affiliations:
                second.append(other)
        else:
            kept.append(inner)
    if kept:
        base = f"{base} " + " ".join(f"({inner})" for inner in kept)
    return DirectoryName(
        base, county_said, county_kind, frozenset(legal), tuple(second), entity, forenames
    )


_ENTITY_DIGITS: Final = 4
"""The fewest digits of an entity number (Arizona's run from four to seven)."""


def entity_number(inner: str) -> str | None:
    """The entity number a bracket gives (``"4192"`` for ``"4192"``, ``"25076"`` for
    ``"025076"``), or ``None``: four digits or more and nothing else."""
    inner = inner.strip()
    if len(inner) < _ENTITY_DIGITS or not inner.isdigit():
        return None
    return str(int(inner))


@dataclass(frozen=True, slots=True)
class ListingForms:
    """A listing read two ways: as a district name and as a school name."""

    district: NameForm
    school: NameForm
    hint: Level
    legal: frozenset[str] = frozenset()
    """The words that say the legal form of the body the listing names (:func:`legal_words`)."""
    spelled: tuple[str, ...] = ()
    """The listing's identifying words as it spells them, read as a district's name
    (:func:`spelled_name`): ``("oak", "hill")`` for ``"Oak Hill Schools"``."""

    @property
    def is_empty(self) -> bool:
        """True when the listing names nothing once designators and noise are gone.

        Nor does one whose only words begin a name and never stand alone
        (``"St."``, ``"Mt."``, ``"Ft."``, see :data:`_NO_NAME_ALONE_WORDS`).
        """
        return (self.district.is_empty and self.school.is_empty) or (
            _only_name_prefixes(self.district) and _only_name_prefixes(self.school)
        )


_NO_NAME_ALONE_WORDS: Final = frozenset({"saint", "sainte", "street", "mount", "fort"})
"""Words (as :func:`stem` gives them) that begin or end a name and are no name alone:
no NCES record is named ``"Saint"``, ``"Street"``, ``"Mount"`` or ``"Fort"`` and
nothing else, so a listing that says only ``"St."`` or ``"Mt."`` names nothing,
not ``"STREET EL"`` or ``"High Mount SD 116"``."""


def _only_name_prefixes(form: NameForm) -> bool:
    """True when ``form`` says nothing but :data:`_NO_NAME_ALONE_WORDS`."""
    return (
        bool(form.token_set)
        and form.token_set <= _NO_NAME_ALONE_WORDS
        and not (form.numbers or form.levels or form.qualifiers or form.codes)
    )


@lru_cache(maxsize=1 << 14)
def legal_words(text: str) -> frozenset[str]:
    """The words of a name that say its legal form rather than which body it is.

    The designators stripped from the end of its district reading and the
    phrase stripped from its start, as :func:`stem` gives them, joining words
    left out: ``public``, ``school``, ``community`` and ``district`` for
    ``"Detroit Public Schools Community District"``, ``community`` and ``school``
    for ``"Detroit Community Schools"``, ``independent``, ``school`` and
    ``district`` for ``"Jackson ISD"``. Two districts of one town whose names
    differ only in these words are told apart by them.
    """
    parsed = _parse(text)
    words = list(parsed.words)
    popped = _strip_designators(words, district=True)
    found = {stem(word) for phrase in (*popped, *parsed.leading) for word in phrase.split()}
    return frozenset(found - lexicon.WEAK_WORDS)


@lru_cache(maxsize=1 << 16)
def listing_forms(text: str, *, district_hint: bool = False) -> ListingForms:
    """Return both readings of a cleaned listing name and what its words say it is.

    ``district_hint`` records that the noise around the name said it is
    district-wide (``"- All Schools"``); it settles a bare name as a district but
    does not overrule a name that says it is one school, and a name with an
    affiliation it makes a group of private schools, not a district.
    """
    parsed = _parse(text)
    popped = _strip_designators(list(parsed.words), district=True)
    affiliated = bool(affiliations_of(parsed.words))
    kind = _hint(parsed, popped, affiliated=affiliated)
    if district_hint and kind.hint is Level.UNKNOWN:
        kind = _Kind(Level.UNKNOWN, system=True) if affiliated else _Kind(Level.DISTRICT)
    return ListingForms(
        district=_form(parsed, district=True, kind=kind),
        school=_form(parsed, district=False, kind=kind),
        hint=kind.hint,
        legal=legal_words(text),
        spelled=spelled_name(text, district=True).words,
    )


_STATUS_BRACKET: Final = re.compile(
    r"[\(\[][^\)\]]*\b(?:closed?|closings?|closure|delay(?:ed|s)?|late|early|dismiss\w*|remote"
    r"|virtual|e-?learning|nti|online|cancel+(?:ed|led)?|open(?:ing|s)?|no\s+school|hours?|hrs?"
    r"|updated?|today|tomorrow)\b[^\)\]]*[\)\]]",
    re.IGNORECASE,
)
_ALL_SCHOOLS: Final = re.compile(
    r"(?:^\s*|\s*[-:,]\s*|\s+)(?:and\s+)?all\s+(?:district\s+)?"
    r"(?:schools|locations|campuses|buildings|sites|facilities)\b\.?",
    re.IGNORECASE,
)
_CLOCK: Final = re.compile(
    r"\b\d{1,2}(?::\d{2})?\s*(?:a\.?\s?m\b\.?|p\.?\s?m\b\.?|noon\b)|\bnoon\b", re.IGNORECASE
)
_SEPARATORS: Final = re.compile(r"\s+[-|/]\s+|\s*[:;,]\s*|[\(\)\[\]]|\s*[-]{2,}\s*")
_WORD: Final = re.compile(r"[a-z0-9]+")

# A segment made only of these words is a status, not a name ("2 Hour Delay",
# "Early Dismissal at 1 PM", "Remote Learning Day"); it must hold at least one of
# _STATUS_MARKERS. "Virtual Academy" and "Early Childhood Center" keep a word
# outside the list, so they stay names.
_STATUS_MARKERS: Final = frozenset(
    {
        "closed",
        "close",
        "closing",
        "closings",
        "closure",
        "delay",
        "delayed",
        "delays",
        "late",
        "early",
        "dismissal",
        "dismissing",
        "dismiss",
        "remote",
        "virtual",
        "elearning",
        "learning",
        "nti",
        "online",
        "cancelled",
        "canceled",
        "cancel",
        "open",
        "opening",
        "opens",
    }
)
_STATUS_VOCABULARY: Final = _STATUS_MARKERS | frozenset(
    {
        "all",
        "and",
        "at",
        "the",
        "of",
        "to",
        "for",
        "due",
        "no",
        "school",
        "schools",
        "system",
        "classes",
        "activities",
        "today",
        "tomorrow",
        "day",
        "days",
        "e",
        "hour",
        "hours",
        "hr",
        "hrs",
        "minute",
        "minutes",
        "min",
        "mins",
        "one",
        "two",
        "three",
        "a",
        "m",
        "p",
        "am",
        "pm",
        "noon",
        "start",
        "starting",
        "instruction",
        "updated",
        "update",
        "snow",
        "weather",
        "ice",
        "cold",
        "roads",
        "road",
        "conditions",
    }
)


_STATUS_WORDS_NOT_MARKERS: Final = _STATUS_VOCABULARY - _STATUS_MARKERS


def _is_status(segment: str) -> bool:
    words = _WORD.findall(fold(segment))
    return (
        bool(words)
        and all(w in _STATUS_VOCABULARY or w.isdigit() for w in words)
        and any(w in _STATUS_MARKERS for w in words)
    )


def _is_noise(segment: str) -> bool:
    words = _WORD.findall(fold(segment))
    return not words or _is_status(segment) or " ".join(words) in _NOISE_PHRASES


_NOISE_PHRASES: Final = frozenset(
    {"all", "schools", "school", "school system", "the", "inc", "llc", "all schools"}
)


@dataclass(frozen=True, slots=True)
class CleanListing:
    """A listing with its noise removed.

    Attributes:
        text: the kept segments joined by spaces, a direction that begins one
            spelled out: what is matched as one name.
        segments: the kept parts between separators, for reading one part as the
            name and another as its city or district.
        all_schools: the listing said ``All Schools`` (or locations, campuses ...),
            so it is district-wide.
        business: the word that names a business form (``llc``, ``inc`` ...),
            which is dropped from the name, or ``None``.
        base: :attr:`text` without the brackets the listing ends with, when it
            ends with any (``"Mason Consolidated Schools"`` for ``"Mason
            Consolidated Schools (Monroe)"``); else ``""``.
        brackets: those brackets, first first (``("Monroe",)``).
        entity: the entity number a bracket gives (``"4192"``), see
            :func:`entity_number`, or ``None``.
    """

    text: str
    segments: tuple[str, ...]
    all_schools: bool
    business: str | None = None
    base: str = ""
    brackets: tuple[str, ...] = ()
    entity: str | None = None


def clean_listing(text: str) -> CleanListing:
    """Remove the status and ``All Schools`` noise a closings list adds around a name.

    The listing is split at separators (`` - ``, ``:``, ``,``, ``|``, brackets); a
    hyphen inside a word (``"Hall-Woodward"``, ``"R-IV"``) does not split, but one
    after the word or the number that ends a name and before a capitalized word
    sets that word apart, as a list joins a town (``"Sacred Heart School-Troy"``,
    ``"Southeast Local SD-Ravenna"``, ``"Central School District 104-O'Fallon"``;
    not ``"Lincoln Elementary-Middle School"``). Parts that are only a status
    (``"(Closed)"``, ``"2 Hour Delay"``) are dropped. A direction that begins a
    part is spelled out in :attr:`CleanListing.text` (``"Lake Zurich Middle - N
    Campus"`` is ``"Lake Zurich Middle North Campus"``), since a letter inside a
    name is an initial. HTML entities a feed
    left in (``"Leverett&#039;s"``) are decoded first. A bracket that says no
    more than a directory's does (an Arizona entity number, grades, ``"(THE)"``,
    ``"(CHARTER)"``: see :func:`directory_name`) goes too, and the brackets the
    listing then ends with are kept apart (:attr:`CleanListing.brackets`), for
    a listing that names a district as NCES writes it (``"Mason Consolidated
    Schools (Monroe)"``).
    """
    text = _CLOCK.sub(" ", plain_text(text))
    text = _STATUS_BRACKET.sub(" ", text)
    entity = next(
        (
            number
            for found in _NOISE_BRACKET.finditer(text)
            if (number := entity_number(found.group(0).strip("() "))) is not None
        ),
        None,
    )
    text = _NOISE_BRACKET.sub(" ", text)
    all_schools = bool(_ALL_SCHOOLS.search(text))
    text = _JOINED_PART.sub(_part_apart, _ALL_SCHOOLS.sub(" ", text))
    kept = _kept_parts(text)
    business = next(
        (w for w in _WORD.findall(fold(_DOTTED_BUSINESS.sub(_close_up, text))) if w in _BUSINESS),
        None,
    )
    joined = " ".join(_part_direction(part) for part in kept)
    base, brackets = _trailing_brackets(text)
    base_text = " ".join(_part_direction(part) for part in _kept_parts(base)) if brackets else ""
    return CleanListing(joined, kept, all_schools, business, base_text, brackets, entity)


_CHARTER_AFTER_TYPE: Final = re.compile(
    r"^(?P<name>.*\b(?:academy|acad\.?|preparatory|prep\.?|institute))\s+charter\s+school\.?$",
    re.IGNORECASE,
)


def without_charter_school(text: str) -> str | None:
    """A listing's name without the ``Charter School`` that follows its type, if it has one.

    Tennessee's charter schools are NCES's ``"Memphis Merit Academy"``, run by the
    county's district, and the lists' ``"Memphis Merit Academy Charter
    School"``: after ``Academy``, ``Preparatory`` or ``Institute``, ``Charter
    School`` says what kind of academy it is. The matcher reads the name without
    it only when the listing as written names nothing: NCES also names schools
    ``"TRELLIS Academy Charter School"`` beside their district ``"TRELLIS
    Academy"``. ``text``: the cleaned listing (:attr:`CleanListing.text`).
    """
    found = _CHARTER_AFTER_TYPE.match(text.strip())
    return None if found is None else found["name"]


_JOINED_PART: Final = re.compile(r"(?<![\w'.-])([A-Za-z0-9#.']+)-(?=([A-Z][A-Za-z.']*[A-Za-z]))")
"""A hyphen with no space between a word and a capitalized one: see :func:`_part_apart`."""
_LEVEL_SHORTS: Final = frozenset(
    short for short, words in lexicon.EXPANSIONS.items() if set(words) & lexicon.LEVELS
)
_NAME_END_WORDS: Final = (
    frozenset({"school", "schools", "sch", "schl", "schs", "district", "dist", "academy"})
    | frozenset({"local", "sd", "isd", "usd", "cusd", "csd", "psd", "ufsd", "cisd"})
    | lexicon.LEVELS
    | _LEVEL_SHORTS
)
"""Words that end a district's or a school's name, after which a list may join a
town with a hyphen (``"Cody Kilgore Unified Schools-Cody"``)."""
_NOT_A_PART: Final = (
    lexicon.K12_WORDS
    | lexicon.SCHOOL_NOUNS
    | lexicon.QUALIFIERS
    | lexicon.DISTRICT_DESIGNATORS
    | _LEVEL_SHORTS
)


def _part_apart(found: re.Match[str]) -> str:
    """``"School-Troy"`` as ``"School - Troy"``; any other hyphen as it was.

    Only after a word that ends a name (:data:`_NAME_END_WORDS`) or a number,
    and before a word that is no level, noun, qualifier or designator, nor a
    word of a status that says no status by itself (``"All"``, ``"School"``).
    """
    before = fold(found.group(1)).strip(".'")
    after = fold(found.group(2)).strip(".'")
    ends = before in _NAME_END_WORDS or before.lstrip("#").isdigit()
    if ends and after not in _NOT_A_PART and after not in _STATUS_WORDS_NOT_MARKERS:
        return f"{found.group(1)} - "
    return found.group(0)


def plain_text(text: str) -> str:
    """``text`` with HTML entities decoded, typographic quotes and dashes made ASCII, one space.

    Feeds that escape twice send ``"Leverett&#039;s Chapel ISD"``, and lists type
    an en dash (U+2013) for a hyphen (``"Knox County - TN"``).
    """
    if "&" in text:
        text = html.unescape(text)
    return " ".join(text.translate(_TYPOGRAPHY).split())


def _kept_parts(text: str) -> tuple[str, ...]:
    """The parts of ``text`` between separators that are not noise (a status, ``Schools``)."""
    parts = (part.strip(" .-") for part in _SEPARATORS.split(text))
    return tuple(part for part in parts if part and not _is_noise(part))


_NOISE_BRACKET: Final = re.compile(
    r"\(\s*(?:\d{4,}|(?:p?k|\d{1,2})\s*-\s*(?:k|\d{1,2})|the|charter|sda|psad)\s*\)",
    re.IGNORECASE,
)
"""A bracket that says no more than a directory name's: an entity number (``"(4192)"``,
four digits or more, kept as :attr:`CleanListing.entity`), grades (``"(K-6)"``),
``"(THE)"``, ``"(CHARTER)"`` and Michigan's :data:`_LEGAL_INITIALS`."""
_LAST_PART: Final = re.compile(r"(?:\s+[-|/]\s+|\s*[:;,]\s*)(?P<part>[^-|/:;,()]*)$")


def _trailing_brackets(text: str) -> tuple[str, tuple[str, ...]]:
    """``text`` without the brackets it ends with, a status after them aside, and them.

    ``"Mason Consolidated Schools (Monroe) - Closed"`` ends with ``(Monroe)``.
    """
    body = text.strip(" .-")
    while (last := _LAST_PART.search(body)) is not None and _is_noise(last["part"]):
        body = body[: last.start()].strip(" .-")
    if not body.endswith(")"):
        return text, ()
    base, parts = split_brackets(body)
    # "(All Schools)" leaves "()" behind; a status in brackets is gone already.
    return base, tuple(part for part in parts if not _is_noise(part))


def bracket_form(inner: str) -> NameForm:
    """What a bracket of a listing says, read as a school's name.

    ``"formerly"`` and the like before a former name go (``"(formerly
    Berlin-Milan)"`` says ``berlin`` and ``milan``), and so do designators at its end.
    """
    other = _FORMER_NAME.sub("", inner, count=1) if _FORMER_NAME.match(inner) else inner
    return record_form(other, district=False)


_BUSINESS: Final = lexicon.BUSINESS_WORDS
_DOTTED_BUSINESS: Final = re.compile(r"\b(?:[A-Za-z]\.){2,}")


def _close_up(match: re.Match[str]) -> str:
    return match.group(0).replace(".", "")


def non_k12(clean: CleanListing) -> str | None:
    """The word that makes a listing name a college, university or seminary, or ``None``.

    ``"Boston College"``, ``"University of Denver"`` and ``"Harrisburg Area
    Community College"`` name no K-12 school, whatever K-12 school shares their
    words (``"Boston College High School"``). A listing that also says it is a
    K-12 school (a level, ``School``, ``Academy``, ``Preparatory``, ``Charter``) is
    one, and so are ``"Early College"``, ``"Middle College"``, ``"Gateway to
    College"`` and a college word before a place word (``"College Park"``,
    ``"University Heights"``). Each part of the listing is read on its own, so
    ``"Boston College - Chestnut Hill"`` still ends in ``College``. ``"A&M"``
    names a university too (``"Texas A&M"``, never ``"TEXAS CITY ISD"``).
    """
    found: str | None = None
    for segment in clean.segments:
        words = _canonical(_raw_tokens(segment)[0])[0]
        if not lexicon.K12_WORDS.isdisjoint(words):
            return None
        if found is None and _names_an_a_and_m(words):
            found = "university"
        count = len(words)
        for i, word in enumerate(words):
            if word not in lexicon.NON_K12 or found is not None:
                continue
            if i and words[i - 1] in lexicon.NON_K12_PROGRAMS:
                continue
            rest = words[i + 1 :]
            if (
                i + 1 == count
                or rest[0] == "of"
                or all(w in lexicon.NON_K12_TRAILERS or w in _STATUS_VOCABULARY for w in rest)
            ):
                found = word
    return found


_A_AND_M: Final = ("a", "and", "m")


def _names_an_a_and_m(words: Sequence[str]) -> bool:
    """True when ``words`` hold ``A&M`` (``"a and m"`` once the ampersand is read)."""
    size = len(_A_AND_M)
    return any(tuple(words[i : i + size]) == _A_AND_M for i in range(len(words) - size + 1))


@dataclass(frozen=True, slots=True)
class CivicBody:
    """What makes a listing name a civic body rather than a school.

    Attributes:
        what: the words that say so, for the unmatched queue (``"city of"``,
            ``"city hall"``, ``"senior center"``, ``"church"``).
        may_be_a_place: the words may be part of a town's name (``"Falls
            Church"``, ``"Shelter Island"``), so a listing that is only a town's
            name is still that town. ``"City of ..."`` never is.
        business: the listing names a business (``"Royston, LLC"``), not a
            government or a community place.
        parish: the listing names a parish and nothing else of the kind: a
            church (``"Christ the King Parish"``), or in Louisiana a county, whose
            district a list may name bare (``"Acadia Parish"``); the matcher
            tells them apart by the directory. A saint's parish in the
            possessive (``"St. Peter's Parish"``) is a church outright.
    """

    what: str
    may_be_a_place: bool
    business: bool = False
    parish: bool = False

    @property
    def kind(self) -> str:
        """``"business"`` or ``"civic body"``, for the unmatched queue."""
        return "business" if self.business else "civic body"

    @property
    def government(self) -> bool:
        """True when the listing is a government's name as it writes one: ``"Township of Union"``.

        New Jersey's ``"Township of Union School District"`` bears the same
        name, so among a list's schools it is the school district's
        (:meth:`~snowlight.match.matcher.Matcher.match`).
        """
        return self.what.endswith(" of")


_CIVIC_PHRASES: Final[dict[str, tuple[tuple[str, ...], ...]]] = {
    first: tuple(p for p in lexicon.CIVIC_PHRASES if p[0] == first)
    for first in {phrase[0] for phrase in lexicon.CIVIC_PHRASES}
}
_GOVERNMENT_OF_MIN_WORDS: Final = 3


def _civic(words: Sequence[str]) -> CivicBody | None:
    """The civic body one part of a listing names, read from its canonical words."""
    if (
        len(words) >= _GOVERNMENT_OF_MIN_WORDS
        and words[0] in lexicon.MUNICIPAL_BODIES
        and words[1] == "of"
    ):
        return CivicBody(f"{words[0]} of", may_be_a_place=False)
    for i, word in enumerate(words):
        following = words[i + 1] if i + 1 < len(words) else None
        if word in lexicon.MUNICIPAL_BODIES and following in lexicon.MUNICIPAL_OFFICES:
            return CivicBody(f"{word} {following}", may_be_a_place=True)
        for phrase in _CIVIC_PHRASES.get(word, ()):
            if tuple(words[i : i + len(phrase)]) == phrase and (
                word not in lexicon.CIVIC_IN_NAMES or _names_the_body(words, i)
            ):
                return CivicBody(" ".join(phrase), may_be_a_place=True)
    return None


def _names_the_body(words: Sequence[str], i: int) -> bool:
    """True when ``words[i]``, a word of :data:`lexicon.CIVIC_IN_NAMES`, names the body.

    It does where it ends the part (a status after it counts as the end:
    ``"Grace Church closed today"``), comes before ``of`` or ``on``, or follows a
    faith; not inside a name (``"Mary Church Terrell"``, ``"Church Point"``).
    """
    rest = words[i + 1 :]
    return (
        all(w in _STATUS_VOCABULARY or w.isdigit() for w in rest)
        or rest[0] in lexicon.CIVIC_IN_NAMES_LINKS
        or (i > 0 and words[i - 1] in lexicon.AFFILIATIONS)
    )


def names_a_school(clean: CleanListing) -> bool:
    """True when a listing's words say it is about a school or a school district.

    A level, ``School``, ``Academy`` or another school's noun (``"Bethlehem
    Lutheran School"``, ``"Archbishop Williams High"``), a district's designator,
    code or number (``"Brandon Valley SD"``, ``"USD 107 Rock Hills"``, ``"Holden
    R-III"``), or ``All Schools`` beside it; not a bare name (``"Bishop
    Fenwick"``, ``"Albemarle County"``, ``"Visitation"``).
    """
    words = _parse(clean.text).words
    if not lexicon.K12_WORDS.isdisjoint(words) or not lexicon.SCHOOL_NOUNS.isdisjoint(words):
        return True
    forms = listing_forms(clean.text, district_hint=clean.all_schools)
    district = forms.district
    return forms.hint is not Level.UNKNOWN or bool(district.codes or district.district_numbers)


def church_name(clean: CleanListing) -> str | None:
    """The words by which a listing may name a church, when it says nothing of a school.

    A parish and its school share a name: ``"St. Peter's"``, ``"Christ the
    King"``, ``"Visitation"``, ``"Our Lady of Unity"`` (:data:`lexicon.PARISH_NAMES`)
    are each a church as much as a school, and so are ``"Trinity Lutheran"`` and
    ``"Grace Baptist"`` (:data:`lexicon.CHURCH_FAITHS`). A listing that also says
    a level, ``School``, ``Academy`` or another school's noun names the school
    (:func:`names_a_school`).
    Returns those words, folded (``"saint"``, ``"christ"``, ``"lutheran"``), or
    ``None``.
    """
    if names_a_school(clean):
        return None
    words = _parse(clean.text).words
    said = [w for w in words if w in lexicon.PARISH_NAMES]
    said.extend(sorted(affiliations_of(words) & lexicon.CHURCH_FAITHS))
    return " ".join(dict.fromkeys(said)) or None


class SpelledName(NamedTuple):
    """A name's words as it spells them: see :func:`spelled_name`."""

    words: tuple[str, ...]
    qualifiers: frozenset[str]
    levels: frozenset[str]


def spelled_name(text: str, *, district: bool = False) -> SpelledName:
    """The words of a name as written: canonical, but nothing stemmed.

    Abbreviations expand as in any name (``"Mt. Lindell"`` is ``"Mount
    Lindell"``, ``"St. Marys"`` is ``"Saint Marys"``), designators go (legal-form
    words too, for a ``district``), and punctuation goes, an apostrophe too
    (``"St. Mary's"`` is ``"St. Marys"``, ``"Coeur d'Alene"`` is ``"Coeur
    dAlene"``). Unlike :attr:`NameForm.tokens`, a plural or possessive ``s``
    stays: ``"Oak Hills"`` is another place than ``"Oak Hill"``, and ``"Scott
    Valley"`` than ``"Scotts Valley"``. The identifying words are in
    :attr:`SpelledName.words`, in order; levels and qualifiers apart.
    """
    folded = fold(text)
    parsed = _parse(folded.replace("'", "") if "'" in folded else folded)
    words = list(parsed.words)
    _strip_designators(words, district=district)
    words = name_first(words)
    kept: list[str] = []
    qualifiers: list[str] = []
    levels: list[str] = []
    numbered = bool(parsed.numbers or parsed.codes)
    for word, (word_class, _text) in zip(words, _classes(words, numbered=numbered), strict=True):
        if word_class == _IS_WORD:
            kept.append(word)
        elif word_class == _IS_LEVEL:
            levels.append(word)
        else:
            qualifiers.append(word)
    return SpelledName(tuple(kept), frozenset(qualifiers), frozenset(levels))


_LETTERS: Final = re.compile(r"[a-z]+")


class Section(StrEnum):
    """What a list's section says of the listings it files (see :func:`listing_section`)."""

    SCHOOLS = "schools"
    """K-12 schools (``"Schools"``, ``"Public Schools"``, ``"Parochial School"``)."""
    OTHER = "other"
    """Anything but K-12 schools (``"Churches"``, ``"Business"``, ``"Gov't."``,
    ``"Pre-Schools/Daycare"``, ``"Gov't."``)."""
    UNKNOWN = "unknown"
    """No section, or one that files schools beside anything else
    (``"School/College"``), or says nothing of either (``"Closings"``, ``"Other"``)."""


def listing_section(category: str | None) -> Section:
    """What the section a list files a listing under says it is, from its words.

    ``category`` is the section's name as the list writes it, or ``None``. A
    section is :attr:`Section.SCHOOLS` when its words all name schools
    (:data:`lexicon.SCHOOL_SECTIONS`), :attr:`Section.OTHER` when they name only
    other things (:data:`lexicon.OTHER_SECTIONS`), and otherwise
    :attr:`Section.UNKNOWN`.
    """
    if not category:
        return Section.UNKNOWN
    text = " ".join(_LETTERS.findall(fold(plain_text(category))))
    for phrase, joined in lexicon.SECTION_PHRASES:
        text = re.sub(rf"\b{phrase}\b", joined, text)
    words = set(text.split())
    schools = not words.isdisjoint(lexicon.SCHOOL_SECTIONS)
    other = not words.isdisjoint(lexicon.OTHER_SECTIONS)
    if schools and not other:
        return Section.SCHOOLS
    if other and not schools:
        return Section.OTHER
    return Section.UNKNOWN


def is_bare_name(text: str) -> bool:
    """True when ``text`` holds no designator and no number: nothing but a name.

    ``"Falls Church"``, ``"Falls Church City"`` and ``"State College"`` are bare;
    ``"Roselle Park District"``, ``"Roselle Parks Department"``, ``"School District
    of Lancaster"`` and ``"Wentzville R-4"`` are not, so they never count as the
    name of a town.
    """
    parsed = _parse(text)
    if parsed.leading or parsed.numbers:
        return False
    return not _strip_designators(list(parsed.words), district=False)


def not_school(clean: CleanListing) -> CivicBody | None:
    """The civic body a listing names instead of a school, or ``None``.

    A closings list carries governments, community places, hospitals and
    churches beside schools, and they share their town's name with its district.
    A listing names one when a part of it begins ``City``, ``Town``, ``Village``,
    ``Borough``, ``Township``, ``County``, ``Parish`` or ``State`` followed by
    ``of`` (``"City of Monessen"``), or a part after the first is only that
    (``"Chester, Town of"``, ``"Springfield, City of"``), names a government's offices (``"Monessen
    City Hall"``, ``"Foley City Council"``), or names a place in
    :data:`lexicon.CIVIC_PHRASES` (``"Sabine Pass Senior Center"``, ``"North
    Fond du Lac Hospital"``, ``"First Baptist Church of Marion"``). A listing
    that also says it is about schools (a level, ``School``, ``Academy``,
    ``Education``, ``ISD`` ...) is not one: ``"City of Chicago SD 299"`` and
    ``"Township of Ocean School District"`` are districts, though a church's
    ``"Sunday School"`` says nothing K-12. The same holds for a business: a
    listing whose name carries ``LLC``, ``Inc.`` or ``Ltd.`` (``"Royston,
    LLC"``) and nothing K-12 names none. A listing that says ``Parish`` and
    nothing K-12 names a church, or a Louisiana parish (:attr:`CivicBody.parish`).
    """
    found: CivicBody | None = None
    parish: CivicBody | None = None
    for position, segment in enumerate(clean.segments):
        words = _canonical(_raw_tokens(segment)[0])[0]
        if not lexicon.CIVIC_EXEMPT.isdisjoint(_without_church_classes(words)):
            return None
        if found is None and position and _government_of(words):
            # "Chester, Town of", "Springfield, City of": a government, written
            # the way a directory sorts it.
            found = CivicBody(" ".join(words), may_be_a_place=False)
        if found is None:
            found = _civic(words)
        if parish is None and lexicon.PARISH in words:
            possessive = _POSSESSIVE_PARISH.search(segment) is not None
            parish = CivicBody(lexicon.PARISH, may_be_a_place=False, parish=not possessive)
    if found is None and clean.business is not None:
        found = CivicBody(clean.business, may_be_a_place=False, business=True)
    return found or parish


_POSSESSIVE_PARISH: Final = re.compile(r"[A-Za-z]'s\s+parish\b", re.IGNORECASE)
_GOVERNMENT_OF: Final = 2


def _government_of(words: Sequence[str]) -> bool:
    """True when ``words`` are only a government's kind and ``of`` (``"town of"``)."""
    return (
        len(words) == _GOVERNMENT_OF and words[0] in lexicon.MUNICIPAL_BODIES and words[1] == "of"
    )


def _without_church_classes(words: Sequence[str]) -> list[str]:
    """``words`` without the ``school`` of a church's classes (``"Sunday School"``)."""
    kept = list(words)
    for phrase in lexicon.CHURCH_CLASSES:
        size = len(phrase)
        for i in range(len(kept) - size, -1, -1):
            if tuple(kept[i : i + size]) == phrase:
                del kept[i + size - 1]
    return kept
