"""Read the state a listing names beside its name.

A closings list that covers several states tells namesakes apart by writing the
state beside the name: ``"Salem MA Public"``, ``"Knox County, TN Schools"``,
``"Collinsville (TX) ISD"``, ``"WASHINGTON COUNTY SCHOOLS-KY"``, ``"Tonganoxie KS
Schools - USD 464"``, ``"Holden R-III School Holden MO"``, ``"Salem, Ark."``,
``"Escambia County, Florida schools"``. :func:`state_mentions` finds such a state
among the listing's market states, wherever it sits, and gives the listing
without it, for the matcher to read in that state alone
(:meth:`~snowlight.match.matcher.Matcher.match`).

A state is read only where it stands beside a name, not inside one:

* never first (``"NH School of Mechanical Trades"``, ``"PA House of
  Representatives"``), nor after a region word or a link (``"Southern NH
  Montessori Academy"``, ``"Railroad Museum of PA"``, ``"MID-MI Leadership
  Academy"``), nor before another word of a name (``"GST MI Works"``, ``"Johnson
  County KS Meals on Wheels"``, ``"Winston-Salem VA Outpatient Clinic"``): only
  before the end of the listing or of a part of it, a bracket's end, or a
  designator, a level or a district code (``"Salem MA Public"``,
  ``"Harrisonville Cass MO R-IX School"``, ``"Derry NH Elementary"``);
* a code that is also a word or an abbreviation (``MS`` for Middle School, ``SD``
  for School District, ``CO`` for County, ``IN``, ``OR``: see
  :data:`~snowlight.match.lexicon.LOOSE_STATE_CODES`), a code in title case
  (``"Ky"``), and a state's name (``"Kansas"``, which begins ``"Kansas City"``)
  count only where a state stands alone: in brackets (``"(TX)"``), or right
  after a comma or a hyphen (``"Holly Springs, MS"``, ``"MADISON SCHOOLS-IN"``,
  ``"Kansas City, Kansas Public Schools"``); a state's name also between a
  name's word and a district's designator, or the name's qualifier and a
  designator (``"Kansas City Kansas Public Schools"``, ``"Bristol Virginia Public
  Schools"``, ``"Bristol Tennessee City Schools"``, each how that city's schools
  call themselves), though not firmly: a listing the whole of which names a
  record keeps it; a state's name before a district's designator only, never
  before a level (``"Tacoma - Washington Elementary"`` is a school named for
  Washington);
* a hyphen with no space around it joins the words of a name
  (``"Westfield-Washington Schools"``, ``"Put-In-Bay"``, ``"COMMUNITY ACTION
  SCHOOL-MS 258"``): a state after one counts only where it ends the listing
  (``"WASHINGTON COUNTY SCHOOLS-KY"``), and a slash never sets a state apart
  (``"PS/MS 498"``, ``"Freeland El/MS"``);
* a listing never widens the search beyond its market: a state outside it is
  read only where it stands firmly beside the name
  (:attr:`StateMention.firm`), and says the listing names no record of the
  market (``"Salem MA Public"`` on a New Hampshire list).

When the state closes the listing after a town (``"Ballard R-II School Butler
MO"``, as the Kansas City lists write a district), or a code in capitals comes
between the name's last word and a town that closes it (``"Shawnee R-3 MO
Chilhowee"``), the town is set apart as a part of its own, to be read as the
record's city; when it repeats the name's own town (``"Holden R-III School
Holden MO"``), the name without it is read too. A code may also come before the
name's qualifier (``"Norton, VA City Schools"``), and a code that is also a word
counts after ``County`` or ``Co.`` when a district's designator follows it
(``"Randolph Co. AL Schools"``, not ``"Harrison County MS"``).

A state that is part of a name is spelled the other way instead, since a list
and the directory may each write it either way (``"Western PA School for the
Deaf"`` is NCES's ``"WESTERN PENNSYLVANIA SCHOOL FOR THE DEAF"``, ``"MID-MI
Leadership Academy"`` its ``"Mid-Michigan Leadership Academy"``): a code that
begins the listing or follows a region word or a link becomes the state's name,
and a state's name after a region word or a link becomes its code. Such a
reading is only another way to read the same name (:attr:`StateMention.beside`
is false).
"""

import re
from dataclasses import dataclass
from enum import Enum, auto
from functools import lru_cache
from typing import Final, NamedTuple

from snowlight.match import lexicon
from snowlight.match.normalize import clean_listing, fold, plain_text


@dataclass(frozen=True, slots=True)
class StateMention:
    """A state a listing names, and how to read the listing in that state.

    Attributes:
        state: its USPS code, one of the listing's market states.
        texts: the listing without it, in the order to read them: with a town
            that comes right before a closing state set apart as a part of its
            own (``"Ballard R-II School - Butler"``), and then, when that town
            repeats the name's own, without it (``"Holden R-III School"``). For
            a state that is part of a name, the listing with the state spelled
            the other way (``"Western Pennsylvania School for the Deaf"``).
        beside: the state stands beside the name, which it tells apart from its
            namesakes in other states; false when it is part of the name.
        firm: it stands beside the name so plainly that the listing names no
            record outside the state: a code in capitals or a newspaper
            abbreviation, or any spelling after a comma or alone in brackets
            (``"Holly Springs, MS"``, ``"Collinsville (TX) ISD"``). Not a code
            that also shortens a word after a hyphen (``"Capital City PCS -
            MS"`` may be a middle school), nor a state's name after one.
        in_market: the state is one of the market's. A state outside it is
            mentioned only when it stands firmly beside the name, and has no
            :attr:`texts`: the listing is not read there.
        said: the state as the listing spells it (``"MA"``, ``"Ark."``), after
            the word before it, folded (``"school ar"`` in ``"Evergreen
            Montessori School - AR"``), for :func:`spelled_in`.
    """

    state: str
    texts: tuple[str, ...]
    beside: bool = True
    firm: bool = False
    in_market: bool = True
    said: str = ""


class _Spelling(Enum):
    """How a listing spells a state."""

    FIRM = auto()
    """A code in capitals or a newspaper abbreviation that shortens no other word."""
    LOOSE = auto()
    """A code or abbreviation that also shortens a word (``MS``, ``"Ind."``), or a
    code in title case (``"Ky"``)."""
    NAME = auto()
    """The state's name (``"Kansas"``, ``"North Carolina"``)."""


class _Side(Enum):
    """What stands on one side of a state in a listing."""

    START = auto()
    """Nothing: the listing begins with the state."""
    INSIDE = auto()
    """A region word or a link: the state is part of a name."""
    WORD = auto()
    """A word of the name before the state."""
    SEPARATOR = auto()
    """A comma, a semicolon, a colon, a bar or a hyphen."""
    BRACKET = auto()
    END = auto()
    """Nothing but noise (``"(Closed)"``, ``"- All Schools"``) after the state."""
    DESIGNATOR = auto()
    """A designator, a level or a district code after the state."""


class _Left(NamedTuple):
    side: _Side
    cut: int
    """Where the text to remove with the state begins."""
    mark: str = ""
    """The separator: ``","``, ``" -"`` (a hyphen with a space before it), ``"-"`` ..."""


_BOUNDARY_BEFORE: Final = r"(?<![A-Za-z0-9'&.])"
_BOUNDARY_AFTER: Final = r"(?![A-Za-z0-9'&])"
_CODE: Final = re.compile(r"[A-Z]{2}")
_MARKS: Final = ",;:|"
_JOINED: Final = "-"
_SPACED: Final = " -"
_PART_BREAK: Final = re.compile(r"\s+[-|/]\s+|[,;:()|/]")
_WORD_BEFORE: Final = re.compile(r"([A-Za-z0-9#'.]+)\W*$")
_FIRST_WORD: Final = re.compile(r"[A-Za-z0-9#][A-Za-z0-9#.'-]*")
_TOWN_WORD: Final = re.compile(r"[A-Za-z][A-Za-z.'-]*")
_MAX_TOWN_WORDS: Final = 3
_DISTRICT_CODE: Final = re.compile(
    r"(?:r|re|rj|c|d|j|u)-?(?:[ivxl]+|\d+)"
    r"|#?\d+[a-z]?"
    r"|(?:usd|isd|sd|cusd|csd|psd|rsu|msad|sad|sau|aos)-?#?\d+"
)
"""A district's number as a list writes it: ``"R-III"``, ``"C-6"``, ``"42"``, ``"USD500"``."""

_DISTRICT_WORDS: Final = frozenset(
    {
        "schools",
        "district",
        "districts",
        "system",
        "systems",
        "public",
        "unified",
        "independent",
        "consolidated",
        "corporation",
    }
)
"""Words that say a name is a district's: a state before one of them stands beside
the name (``"Kansas City, Kansas Public Schools"``, ``"Escambia County, Florida
schools"``). A state's name before any other word begins a town's (``"Kansas
City"``, ``"Iowa Falls"``) or a school's (``"Washington Elementary"``)."""
_KIND_WORDS: Final = (
    _DISTRICT_WORDS
    | lexicon.LEVELS
    | {"school", "junior", "senior", "community", "central", "unit", "joint", "union", "common"}
    | {"board", "area", "local", "regional"}
)
"""Words that say what kind of district or school a name is: a code before one of
them stands beside the name (``"Salem MA Public"``, ``"Derry NH Elementary"``,
``"Atchison Co. KS Comm Schools"``)."""


def _abbreviations(words: frozenset[str]) -> frozenset[str]:
    """``words``, and the abbreviations a list writes for them (``"comm"``, ``"sch"``)."""
    return words | {
        short for short, spelled in lexicon.EXPANSIONS.items() if words.intersection(spelled)
    }


_NAME_FOLLOWERS: Final = _abbreviations(_DISTRICT_WORDS)
_CODE_FOLLOWERS: Final = _abbreviations(_KIND_WORDS)
_NAME_ENDS: Final = _abbreviations(
    frozenset({"school", "schools", "district", "academy"}) | lexicon.LEVELS
)
"""Words that end a district's or a school's name, after which a list writes the
town and the state (``"Holden R-III School Holden MO"``, ``"Emerson Elementary
Larkstead WI"``)."""
_NOT_A_TOWN: Final = _CODE_FOLLOWERS | _NAME_ENDS | lexicon.STATE_NAME_LINKS
_QUALIFIED: Final = _abbreviations(lexicon.QUALIFIERS)
"""Place qualifiers a list may write after a name's state, before its designator
(``"Norton, VA City Schools"``)."""
_COUNTY_WORDS: Final = _abbreviations(frozenset({"county", "parish"}))
"""Words after which a loose code in capitals is a state when a district's
designator follows it (``"Randolph Co. AL Schools"``)."""
_LOOSE_ABBREVIATIONS: Final = frozenset(
    short.replace(" ", "") for short in lexicon.LOOSE_STATE_ABBREVIATIONS
)


def _key(spelling: str) -> str:
    return " ".join(spelling.casefold().split())


@lru_cache(maxsize=1)
def _spellings() -> tuple[re.Pattern[str], dict[str, str]]:
    """A pattern that finds any spelling of any state, and the state of each spelling.

    Spellings are keyed by :func:`_key`, a code by itself (``"KS"``, ``"Ks"``).
    """
    patterns: list[str] = []
    owners: dict[str, str] = {}
    for code, name in sorted(lexicon.STATE_NAMES.items()):
        patterns.append(r"(?i:" + r"\s+".join(map(re.escape, name.split())) + ")")
        owners[_key(name)] = code
        for short, owner in lexicon.STATE_ABBREVIATIONS.items():
            if owner == code:
                patterns.append(r"\s?".join(map(re.escape, short.split())))
                owners[_key(short)] = code
                owners[_key(short.replace(" ", ""))] = code
        patterns.extend((code, code[0] + code[1].lower()))
        owners[_key(code)] = code
    patterns.sort(key=len, reverse=True)
    pattern = re.compile(_BOUNDARY_BEFORE + "(?:" + "|".join(patterns) + ")" + _BOUNDARY_AFTER)
    return pattern, owners


def _spelling(found: str) -> _Spelling:
    if len(found) == 2:  # noqa: PLR2004 - a USPS code
        firm = _CODE.fullmatch(found) is not None and found not in lexicon.LOOSE_STATE_CODES
        return _Spelling.FIRM if firm else _Spelling.LOOSE
    if found.endswith("."):
        loose = found.replace(" ", "") in _LOOSE_ABBREVIATIONS
        return _Spelling.LOOSE if loose else _Spelling.FIRM
    return _Spelling.NAME


_INITIALS: Final = re.compile(r"(?:[a-z]\.)+[a-z]")


def _word(text: str) -> str:
    """``text`` folded, without the periods and hyphens around it or between initials.

    ``"I.S.D."`` is ``"isd"``, as ``"ISD"`` is.
    """
    word = fold(text).strip(".-'")
    return word.replace(".", "") if _INITIALS.fullmatch(word) else word


def _begins_a_part(text: str) -> bool:
    """True when a word that follows ``text`` begins the listing or a part of it.

    Nothing, a separator or a bracket comes before it, or a link or a region
    word (``"School of Central"``, ``"North Central"``).
    """
    stripped = text.rstrip()
    if not stripped or stripped[-1] in _MARKS + "-(/":
        return True
    word = _WORD_BEFORE.search(stripped)
    previous = _word(word.group(1)) if word is not None else ""
    return previous in lexicon.STATE_NAME_LINKS or previous in lexicon.REGION_WORDS


def _before(text: str) -> _Left:
    """What stands before a state that begins at ``len(text)``.

    :attr:`_Side.START` when the listing begins with it, and :attr:`_Side.INSIDE`
    when a region word or a link comes right before it: it is part of a name.
    """
    stripped = text.rstrip()
    if not stripped:
        return _Left(_Side.START, 0)
    last = stripped[-1]
    if last == "(":
        return _Left(_Side.BRACKET, len(stripped) - 1)
    marked = last in _MARKS or last == "-"
    before_mark = stripped[:-1] if marked else stripped
    word = _WORD_BEFORE.search(before_mark)
    previous = _word(word.group(1)) if word is not None else ""
    if previous in lexicon.REGION_WORDS and (
        word is None or _begins_a_part(before_mark[: word.start(1)])
    ):
        # "Southern NH Montessori", "School of Central VA": a region of the
        # state. After a name's word a region word ends the name instead
        # ("Mill Ave Middle KY", "Lincoln Central PA Schools").
        return _Left(_Side.INSIDE, len(text))
    if marked:
        cut = len(before_mark.rstrip())
        spaced = last == "-" and cut < len(before_mark)
        return _Left(_Side.SEPARATOR, cut, _SPACED if spaced else last)
    if previous in lexicon.STATE_NAME_LINKS:
        return _Left(_Side.INSIDE, len(text))
    return _Left(_Side.WORD, len(stripped))


def _follows(word: str, spelling: _Spelling) -> bool:
    """True when ``word`` after a state says what kind of district or school the name is."""
    followers = _NAME_FOLLOWERS if spelling is _Spelling.NAME else _CODE_FOLLOWERS
    return any(
        candidate in followers
        or (spelling is not _Spelling.NAME and _DISTRICT_CODE.fullmatch(candidate) is not None)
        for candidate in {word, word.split("-", 1)[0]}
    )


def _after(text: str, spelling: _Spelling, *, after_word: bool = False) -> tuple[_Side, int] | None:
    """What stands after a state followed by ``text``, and how much of ``text`` goes with it.

    ``None`` when another word of a name follows. A closing bracket goes with
    the state (``"(TX)"``); noise after it stays, for the matcher to read
    (``"- All Schools"`` says the listing is district-wide). A designator is
    one, though a listing of the designator alone would be noise
    (``"Westfield-Washington Schools"`` does not end with its state).
    ``after_word``: a word of the name comes right before the state.
    """
    rest = text.lstrip()
    if rest.startswith(")"):
        return _Side.BRACKET, len(text) - len(rest) + 1
    first = _FIRST_WORD.match(rest)
    if first is not None and (
        _follows(_word(first.group(0)), spelling)
        or _qualified(rest, first, spelling, after_word=after_word)
    ):
        return _Side.DESIGNATOR, 0
    if not clean_listing(text).segments:
        return _Side.END, 0
    if rest[0] in _MARKS or (rest.startswith("-") and len(rest) < len(text)):
        return _Side.SEPARATOR, 0  # "Knox County, TN Schools", "Tonganoxie KS - USD 464"
    # A hyphen with no space joins a name ("Put-In-Bay"), unless what it joins
    # says the kind of district ("Kansas City KS-USD 500").
    joined = _FIRST_WORD.match(rest[1:]) if rest.startswith("-") else None
    if joined is not None and _follows(_word(joined.group(0)), spelling):
        return _Side.DESIGNATOR, 0
    return None


def _qualified(
    rest: str, first: re.Match[str], spelling: _Spelling, *, after_word: bool = False
) -> bool:
    """True when ``first``, the word after a state, is the name's qualifier before its designator.

    ``"Norton, VA City Schools"``. After a state's name only when a word of the
    name comes before it (``"Bristol Tennessee City Schools"``): a state's name
    that begins a part begins a town's (``"Missouri City"``, ``"Kansas City"``).
    """
    if (spelling is _Spelling.NAME and not after_word) or _word(first.group(0)) not in _QUALIFIED:
        return False
    second = _FIRST_WORD.match(rest[first.end() :].lstrip())
    return second is not None and _follows(_word(second.group(0)), spelling)


def _town_apart(head: str, tail: str) -> tuple[str, ...]:
    """The readings of ``head``, which a state closes, with any town it ends with set apart.

    ``"Ballard R-II School Butler"`` is ``"Ballard R-II School - Butler"``, and
    ``"Holden R-III School Holden"`` is that and ``"Holden R-III School"``: a
    town after the word or the number that ends a name. ``tail`` is what
    follows the state (noise).
    """
    breaks = list(_PART_BREAK.finditer(head))
    start = breaks[-1].end() if breaks else 0
    words = head[start:].split()
    ends = [i for i, word in enumerate(words) if _ends_a_name(_word(word))]
    if not ends:
        return (head + tail,)
    last = ends[-1]
    town = words[last + 1 :]
    if (
        not 0 < len(town) <= _MAX_TOWN_WORDS
        or not all(_TOWN_WORD.fullmatch(word) and _word(word) not in _NOT_A_TOWN for word in town)
        or (len(town) == 1 and _word(town[0]) in lexicon.REGION_WORDS)
    ):
        # "Lincoln Elementary East MO": a region word alone is the name's, not a town.
        return (head + tail,)
    name = (head[:start] + " ".join(words[: last + 1])).rstrip()
    apart = f"{name} - {' '.join(town)}{tail}"
    if {_word(word) for word in town} <= {_word(word) for word in name.split()}:
        return (apart, name + tail)
    return (apart,)


def _ends_a_name(word: str) -> bool:
    return word in _NAME_ENDS or _DISTRICT_CODE.fullmatch(word) is not None


def _after_a_county(before: str, found: str, rest: str) -> bool:
    """True when a loose code in capitals follows a county word and comes before a designator.

    ``"Randolph Co. AL Schools"``, ``"Harrison County MS Schools"``: a county's
    district, in that state. Not ``"Harrison County MS"`` (a middle school) nor
    ``"Douglas Co SD"`` (its school district), whose code ends the listing.
    """
    word = _WORD_BEFORE.search(before)
    if word is None or not _CODE.fullmatch(found) or _word(word.group(1)) not in _COUNTY_WORDS:
        return False
    following = _FIRST_WORD.match(rest.lstrip())
    return following is not None and _word(following.group(0)) in _NAME_FOLLOWERS


def _town_after(before: str, rest: str, spelling: _Spelling, left: _Left) -> tuple[str, ...] | None:
    """The readings of a listing whose state comes between a name and its town, or ``None``.

    ``"Shawnee R-3 MO Chilhowee"`` is ``"Shawnee R-3 - Chilhowee"``: a code in
    capitals right after the word or the number that ends a name, followed by
    a town of up to three words and nothing more but noise. When the town
    repeats the name's own, the name alone is read too.
    """
    words = before.split()
    if (
        spelling is not _Spelling.FIRM
        or left.side is not _Side.WORD
        or not words
        or not _ends_a_name(_word(words[-1]))
    ):
        return None
    cut = _PART_BREAK.search(rest)
    town_text, tail = (rest[: cut.start()], rest[cut.start() :]) if cut else (rest, "")
    town = town_text.split()
    if (
        not 0 < len(town) <= _MAX_TOWN_WORDS
        or not all(_TOWN_WORD.fullmatch(w) and _word(w) not in _NOT_A_TOWN for w in town)
        or (tail and clean_listing(tail).segments)
    ):
        return None
    name = before.rstrip()
    apart = f"{name} - {' '.join(town)}{tail}"
    if {_word(w) for w in town} <= {_word(w) for w in name.split()}:
        return (apart, name + tail)
    return (apart,)


def _other_spelling(found: str, spelling: _Spelling, state: str, left: _Side) -> str | None:
    """How the directory may spell a state that is part of a name, or ``None``.

    A code becomes the state's name (``"PA"``, ``"Pa"``, ``"Pa."`` for
    ``"Pennsylvania"``) unless it also shortens a word (``"MS"``, ``"Ind."``); a
    state's name after a region word or a link becomes its code. A name that
    begins the listing begins a town's (``"Iowa City"``) as often as it names
    the state, and stays.
    """
    if spelling is _Spelling.NAME:
        return state if left is _Side.INSIDE else None
    if found.upper() in lexicon.LOOSE_STATE_CODES:
        return None
    if spelling is _Spelling.LOOSE and found.endswith("."):
        return None
    return lexicon.STATE_NAMES[state]


def _tidy(text: str) -> str:
    """``text`` with one space between words and no space inside brackets or before a comma.

    A hyphen the state was joined to sets the rest apart (``"Kansas City KS-USD
    500"`` reads ``"Kansas City - USD 500"``).
    """
    text = _DANGLING_HYPHEN.sub("- ", " ".join(text.split()))
    text = _SPACE_IN_BRACKETS.sub(lambda found: found.group(0).replace(" ", ""), text)
    return _SPACE_BEFORE_COMMA.sub(",", _EMPTY_BRACKETS.sub(" ", text)).strip()


_DANGLING_HYPHEN: Final = re.compile(r"(?<= )-(?=[^\s-])")
_SPACE_IN_BRACKETS: Final = re.compile(r"\(\s+|\s+\)")
_EMPTY_BRACKETS: Final = re.compile(r"\(\s*\)")
_SPACE_BEFORE_COMMA: Final = re.compile(r"\s+,")


_WORDS: Final = re.compile(r"[a-z0-9]+")


def spelled_in(name: str, mention: StateMention) -> bool:
    """True when ``name`` spells the state as the listing does, after the same word.

    ``"EVERGREEN MONTESSORI SCHOOL - AR"`` is a school's whole name, and a
    listing that copies it names that school, not one in Arkansas; ``"KANSAS
    CITY 33"`` does not spell the ``"Kansas"`` of ``"Kansas City, Kansas Public
    Schools"``.
    """
    words = _WORDS.findall(fold(name))
    said = mention.said.split()
    size = len(said)
    return any(words[i : i + size] == said for i in range(len(words) - size + 1))


def state_mentions(text: str, states: frozenset[str]) -> tuple[StateMention, ...]:
    """The states ``text`` names, and how to read the listing in each of ``states``.

    See the module's docstring for where a state counts. The
    :attr:`StateMention.texts` of a state beside the name are the listing
    without it (and the punctuation that set it apart): ``"Knox County, TN
    Schools"`` reads ``"Knox County Schools"``, ``"Collinsville (TX) ISD"`` reads
    ``"Collinsville ISD"``. A state outside ``states`` is mentioned only where it
    stands firmly beside the name.
    """
    text = plain_text(text)
    pattern, owners = _spellings()
    mentions: list[StateMention] = []
    for found in pattern.finditer(text):
        spelling = _spelling(found.group(0))
        state = owners[_key(found.group(0))]
        said = " ".join(
            _WORDS.findall(fold(text[: found.end()]))[-1 - len(found.group(0).split()) :]
        )
        in_market = state in states
        left = _before(text[: found.start()])
        if left.side in {_Side.START, _Side.INSIDE}:
            other = (
                _other_spelling(found.group(0), spelling, state, left.side) if in_market else None
            )
            if other is not None:
                spelled = text[: found.start()] + other + text[found.end() :]
                mentions.append(StateMention(state, (_tidy(spelled),), beside=False, said=said))
            continue
        rest = text[found.end() :]
        after = _after(rest, spelling, after_word=left.side is _Side.WORD)
        if after is None:
            town = _town_after(text[: found.start()], rest, spelling, left)
            if town is not None and in_market:
                texts = tuple(_tidy(reading) for reading in town)
                mentions.append(StateMention(state, texts, firm=True, said=said))
            continue
        right, taken = after
        alone = left.side is _Side.BRACKET and right is _Side.BRACKET
        if not alone and (
            (
                left.side is _Side.WORD
                and spelling is not _Spelling.FIRM
                and not _after_a_county(text[: found.start()], found.group(0), rest)
                and not (spelling is _Spelling.NAME and right is _Side.DESIGNATOR)
            )
            or (left.mark == _JOINED and right not in {_Side.END, _Side.BRACKET})
        ):
            continue
        head, tail = text[: left.cut], text[found.end() + taken :]
        if left.side is _Side.BRACKET and not alone:
            # "(KS, Leavenworth)": the bracket stays, without the state and its comma.
            rest = tail.lstrip()
            tail = "(" + (rest[1:] if rest[:1] in _MARKS else rest)
        elif right is _Side.BRACKET and not alone:
            tail = ")" + tail  # "(Leavenworth, KS)"
        if left.side is _Side.WORD and right is _Side.END:
            readings = _town_apart(head.rstrip(), tail)
        else:
            readings = (f"{head} {tail}",)
        firm = spelling is _Spelling.FIRM or alone or left.mark == ","
        if not in_market:
            if firm:
                mentions.append(StateMention(state, (), firm=True, in_market=False, said=said))
            continue
        texts = tuple(_tidy(reading) for reading in readings)
        mentions.append(StateMention(state, texts, firm=firm, said=said))
    return tuple(dict.fromkeys(mentions))


_SECTION_CODE: Final = re.compile(r"(?<![A-Za-z])[A-Z]{2}(?![A-Za-z])")
_SECTION_WORD: Final = re.compile(r"[a-z]+")
_SECTION_APART: Final = frozenset("-/()")
_SECTION_PLACES: Final = frozenset({"co", "county", "city", "parish", "twp", "township"})
"""Words after a state's name that make it a county's or a town's (``"Washington Co.
Schools"``), not the state's."""


def _apart(text: str, start: int, end: int) -> bool:
    """True when ``text[start:end]`` is at an end, or beside a hyphen, a slash or a bracket."""
    before = text[:start].rstrip()
    after = text[end:].lstrip()
    return not before or not after or before[-1] in _SECTION_APART or after[0] in _SECTION_APART


def category_states(category: str | None, states: frozenset[str]) -> frozenset[str]:
    """The states among ``states`` a list's section names (``category``).

    A list that covers several states often files its listings by state: WPRI's
    ``"RI Public Schools"`` and ``"MA Public Schools"``, Gray's ``"Schools-IN"``,
    ``"OH Private"``, ``"KY"`` and ``"Business-KY"``, ``"Cowlitz Co. & Lower
    Columbia (WA) Schools"``, ``"Kansas"``. A code counts in capitals, as a word;
    one that is also a word or an abbreviation (``IN``, ``OH``, ``OR``, ``ME``,
    see :data:`~snowlight.match.lexicon.LOOSE_STATE_CODES`) only where it stands
    apart, at an end or beside a hyphen, a slash or a bracket (``"SCHOOLS IN
    OHIO"`` names Ohio only). A state's name counts unless a county's or a
    town's word follows it (``"Washington Co. Schools"``) or it ends another
    state's name (``"West Virginia"`` is not Virginia).
    """
    if not category:
        return frozenset()
    found: set[str] = set()
    for code in _SECTION_CODE.finditer(category):
        state = code.group(0)
        if state in states and (
            state not in lexicon.LOOSE_STATE_CODES or _apart(category, code.start(), code.end())
        ):
            found.add(state)
    words = _SECTION_WORD.findall(fold(category))
    for state in states:
        name = lexicon.STATE_NAMES.get(state)
        if name is None:
            continue
        said = fold(name).split()
        size = len(said)
        for i in range(len(words) - size + 1):
            if words[i : i + size] != said:
                continue
            after = words[i + size] if i + size < len(words) else None
            if after in _SECTION_PLACES or (i and " ".join(words[i - 1 : i + size]) in _NAMES):
                continue
            found.add(state)
    return frozenset(found)


_NAMES: Final = frozenset(fold(name) for name in lexicon.STATE_NAMES.values())
