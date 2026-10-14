"""Statuses the text calls off: "2 hour delay cancelled", "Cancel delay", "Closure lifted".

A word that calls something off (see :attr:`Mention.revokes
<snowlight.classify.mentions.Mention.revokes>`) switches off the status it is
attached to, so an open school never reads as delayed. It is attached when
only filler words, dates and light punctuation stand between the two, in
either order:

* after the status: "2 hour delay cancelled", "Delay: cancelled", "2 hour delay
  (cancelled)", "Early dismissal has been called off", "Delay for all schools
  has been lifted";
* before it, as a verb and its object: "Cancel delay", "We have cancelled
  tomorrow's 2 hour delay", "Rescinded: 2 hour delay".

Statuses joined by "and" or "or" go off together ("Delay and early dismissal
cancelled"). A status called off still dates what replaces it ("Tomorrow's
delay cancelled. Closed." closes tomorrow), so it is kept, marked ``revoked``.

"Cancelled" can also mean the school is off ("School cancelled", "Cancelled:
all classes"). So a "cancelled" that has a noun of its own before or after it
belongs to that noun, and one that could mean either is ambiguous: the status
beside it is dropped as ``ambiguous`` rather than read either way. That is the
case for a closure noun behind a mark ("Snow day: cancelled", where the word
can restate the closure or call it off), for "closed" itself ("Closed -
cancelled"), for a bare "cancelled" before a status ("Cancelled - NTI day")
and for one in a sentence of its own ("2 hour delay. Cancelled."). Words that
only call something off ("lifted", "rescinded") have no such second reading.

A negation keeps the status ("2 hour delay has not been cancelled"); a hedge or
a condition makes it uncertain ("Delay may be lifted", "Delay will be lifted if
roads clear"). A calling-off word attached to nothing is left out.
"""

import re
from collections.abc import Sequence
from typing import Literal, NamedTuple, Protocol

from snowlight.classify.dates import (
    GROUP_START,
    DateGroup,
)
from snowlight.classify.lexicon import (
    CONDITIONALS,
    HEDGES,
    HEDGES_AFTER,
    MODIFIERS,
    NEGATIONS,
    SCOPES,
    Scope,
)
from snowlight.classify.mentions import Mention
from snowlight.classify.model import JUDGMENT
from snowlight.classify.text import DASH_RUN, at_word_start, one_of, words

type Outcome = Literal["revoked", "ambiguous", "hedged", "kept"]
type Category = Literal["status", "closure", "closed"]
"""What a status mention is: a delay, remote day or early dismissal; a closure named by a
noun ("closure", "snow day"); or "closed" itself (an adjective, "no school")."""


class Span(Protocol):
    """Where a clause starts and ends."""

    @property
    def start(self) -> int: ...  # pragma: no cover - a protocol member
    @property
    def end(self) -> int: ...  # pragma: no cover - a protocol member


# Marks between two mentions: a sentence mark (strong), or a comma, colon, slash, spaced
# dash, "but" or "however" (weak). Brackets are commas once the text is normalized.
# (Each branch opens with a character of its own: see text.one_of. _STRONG is
# "[;!?|]|\.(?=\s|$)", _WEAK "[,:/]|(?:^|\s)-+(?=\s|$)|\b(?:but|however)\b", and _MARKS
# "[;!?|,:/]|\.(?=\s|$)|(?:^|\s)-+(?=\s|$)".)
_STRONG = re.compile(one_of(";!?|") + r"|\.(?=\s|$)", re.ASCII)
_WEAK = re.compile(
    one_of(",:/") + f"|{DASH_RUN}|{at_word_start('but')}\\b|{at_word_start('however')}\\b",
    re.ASCII,
)
_MARKS = re.compile(one_of(";!?|,:/") + rf"|\.(?=\s|$)|{DASH_RUN}", re.ASCII)
_NO_MARK, _WEAK_MARK, _STRONG_MARK = 0, 1, 2

# Words that may stand between a status and a calling-off word after it: "2 hour delay for
# Tuesday has officially been cancelled", "The delay announced earlier is lifted".
_AFTER_GLUE = frozenset(
    {
        "has", "have", "had", "been", "is", "are", "was", "were", "be", "being", "will",
        "shall", "now", "hereby", "officially", "formally", "also", "all", "the", "that",
        "which", "it", "this", "just", "already", "previously", "earlier", "originally",
        "announced", "scheduled", "planned", "posted", "reported", "decision",
        "announcement", "notice", "order", "we", "get", "got", "gets", "as", "of",
        "effective", "immediately", "again", "districtwide", "district-wide", "but",
        "however", "update", "updated", "to",
    }
)  # fmt: skip
# Prepositions after which a school noun describes the status: "delay for all schools".
_PREPOSITIONS = frozenset({"for", "on", "at", "in", "across", "throughout"})
# Words that may stand between a calling-off verb and the status it takes as its object:
# "cancelled the previously announced delay", "cancelling tomorrow's delay".
_BEFORE_GLUE = frozenset(
    {
        "the", "our", "its", "their", "this", "that", "a", "an", "all", "any", "previously",
        "earlier", "originally", "announced", "scheduled", "planned", "of", "for", "on",
        "district's", "school's", "schools'", "s",
    }
)  # fmt: skip
# Words that may come before a bare "cancelled" in its clause without being its subject:
# "Update: cancelled - NTI day" has no noun for "cancelled" to be about.
_NO_SUBJECT = frozenset(
    {
        "update", "updated", "correction", "status", "now", "also", "officially", "hereby",
        "we", "have", "has", "been", "is", "are", "was", "will", "be", "it",
        # "This has been cancelled", "The above is cancelled": the post before, no subject of
        # the sentence's own.
        "this", "that", "the", "above",
    }
)  # fmt: skip
# Words that may follow a bare "cancelled" to the end of its sentence ("2 hour delay.
# Cancelled as of 6 am" has a time; "Cancelled." has nothing).
_TRAILING = _AFTER_GLUE | _PREPOSITIONS
# Words joining statuses that go off together: "Delay and early dismissal cancelled".
_JOINERS = frozenset({"and", "or", "nor", "plus"})
# Words that open the object of a calling-off verb: "cancelled all activities".
_DETERMINERS = frozenset({"all", "the", "our", "any", "its", "their"})
_OBJECT_PREPOSITIONS = frozenset({"for", "to"})
# The last word of a closure named by a noun: "closure", "closing", "snow day", "shutdown".
_CLOSURE_NOUNS = frozenset(
    {"closure", "closures", "closing", "closings", "shutdown", "day", "days", "schedule", "plan"}
)
# Who calls a status off, as the subject of an active verb: "District cancels delay". Any
# other noun before "cancelled" is what is cancelled: "Classes cancelled 2 hour delay for staff".
_AGENTS = frozenset(
    {"district", "districts", "superintendent", "board", "administration", "officials", "we"}
)
_UNSURE = (HEDGES | HEDGES_AFTER | CONDITIONALS) - _AFTER_GLUE
# A word that makes its clause a condition: "Delay will be lifted if roads clear".
_CONDITIONAL = re.compile(r"\b(?:" + "|".join(sorted(CONDITIONALS)) + r")\b", re.ASCII)
_SCHOOL_NOUNS = frozenset(word for word, scope in SCOPES.items() if scope == "school")
_SCOPE_WORDS = frozenset(SCOPES)
# Words that end or fill a school's name: "Lincoln Elementary", "Maple Grove Middle School".
_INSTITUTIONS = frozenset(
    {
        "elementary", "middle", "high", "junior", "senior", "intermediate", "primary",
        "secondary", "academy", "center", "centre", "county", "community", "public", "charter",
        "christian", "catholic", "prep", "preparatory", "montessori", "isd", "usd", "cusd",
    }
)  # fmt: skip
_CAUSE_WORDS = frozenset({"due", "because", "owing"})
# Words with a role of their own, which a name after a preposition cannot hold.
_KNOWN = (
    _AFTER_GLUE | _PREPOSITIONS | _JOINERS | _DETERMINERS | NEGATIONS | _UNSURE
    | frozenset(MODIFIERS) | _CAUSE_WORDS | {"but", "however", "until", "through"}
)  # fmt: skip
# The statuses a calling-off verb can take as its object ("cancel the closure", not "closed").
_OBJECTS = frozenset({"status", "closure"})
_GRADE = re.compile(r"(?:k|pk|tk|\d{1,2}(?:st|nd|rd|th)?)(?:-(?:k|\d{1,2}(?:st|nd|rd|th)?))?")


class _Found(NamedTuple):
    """A status a calling-off word is attached to, and how it is attached."""

    target: int
    rule: Literal["object", "after", "sentence", "label"]
    mark: int
    gap: tuple[str, ...]
    split: bool = False  # the status and the word each name a day: "delay today, cancelled Friday"


class Pairing(NamedTuple):
    """What pairing did: the mentions kept, and each switched-off status's calling-off word.

    ``revoked_by`` maps the index of a status (among ``mentions``) to the index
    of the word that calls it off, whose dates the status shares.
    """

    mentions: list[Mention]
    revoked_by: dict[int, int]


def pair_revocations(
    text: str, clauses: Sequence[Span], mentions: list[Mention], groups: tuple[DateGroup, ...]
) -> Pairing:
    """Attach each calling-off word in ``text`` to the status it calls off, in place.

    ``text`` is the normalized text with its date groups blanked out; ``clauses``
    are its clauses, in order. A status called off gets ``revoked``; one that
    could equally be called off or restated gets ``dropped = "ambiguous"``, and
    one called off only maybe gets ``dropped = "hedged"``. The calling-off word
    becomes kind ``revoke``. Words that call off nothing are left out of the
    returned mentions when they can mean nothing else ("advisory lifted").
    """
    homes = _homes(clauses, mentions)
    used: set[int] = set()
    consumed: dict[int, list[int]] = {}
    for index, mention in enumerate(mentions):
        if mention.revokes is None or mention.kind not in {"ambiguous", "revoke"}:
            continue
        found = _attach(text, clauses, mentions, homes, index, groups, used)
        if found is None:
            continue
        before = found.rule in {"after", "sentence"}
        chain = _chain(text, mentions, found.target, before=before, groups=groups, used=used)
        clause = clauses[homes[index]]
        for target in chain:
            used.add(target)
            _apply(mentions[target], _outcome(text, mention, mentions[target], found, clause))
        mention.kind = "revoke"
        mention.note = None
        consumed[index] = chain
    kept = [
        index
        for index, mention in enumerate(mentions)
        if mention.kind != "revoke" or index in consumed
    ]
    if len(kept) == len(mentions) and not consumed:
        return Pairing(mentions, {})
    position = {old: new for new, old in enumerate(kept)}
    revoked_by = {
        position[target]: position[word]
        for word, chain in consumed.items()
        for target in chain
        if mentions[target].revoked
    }
    return Pairing([mentions[index] for index in kept], revoked_by)


_CAN_REVOKE = frozenset({"ambiguous", "revoke"})
_STATUS_KINDS = frozenset({"delayed", "remote", "early_dismissal"})
_CLOSURE_KINDS = frozenset({"closed", "ambiguous"})


def _may_be_status(mention: Mention) -> bool:
    """Whether :func:`_category` can find a status in ``mention`` (a quick look)."""
    return mention.dropped is None and (
        mention.kind in _STATUS_KINDS
        or (mention.kind in _CLOSURE_KINDS and mention.revokes is None)
    )


def may_revoke(mentions: list[Mention]) -> bool:
    """Whether :func:`pair_revocations` can change anything (a quick look).

    It can when a word that only calls something off stands in the text (it is
    left out when it calls off nothing), or when a calling-off word has a
    mention beside it that can be a status: a word is only ever attached to the
    status right before it or right after it (see :func:`_attach`).
    """
    last = len(mentions) - 1
    for index, mention in enumerate(mentions):
        if mention.revokes is None or mention.kind not in _CAN_REVOKE:
            continue
        if mention.kind == "revoke":
            return True
        if (index and _may_be_status(mentions[index - 1])) or (
            index < last and _may_be_status(mentions[index + 1])
        ):
            return True
    return False


def _homes(clauses: Sequence[Span], mentions: list[Mention]) -> list[int]:
    homes: list[int] = []
    index = 0
    for mention in mentions:
        while index + 1 < len(clauses) and clauses[index + 1].start <= mention.start:
            index += 1
        homes.append(index)
    return homes


def _mark(text: str, start: int, end: int) -> int:
    stretch = text[start:end]
    if _STRONG.search(stretch) is not None:
        return _STRONG_MARK
    if _WEAK.search(stretch) is not None:
        return _WEAK_MARK
    return _NO_MARK


def _category(text: str, mention: Mention) -> Category | None:
    """What a mention calls off would be, or ``None`` for one that is not a status."""
    if mention.dropped is not None:
        return None  # negated by its own words: "no school closures"
    if mention.kind in {"delayed", "remote", "early_dismissal"}:
        return "status"
    if mention.kind not in {"closed", "ambiguous"} or mention.revokes is not None:
        return None
    last = words(text, mention.start, mention.end)[-1:]
    if last and last[0] in _CLOSURE_NOUNS:
        return "closure"
    return "closed" if mention.kind == "closed" else None


def _after_gap(text: str, start: int, end: int) -> tuple[str, ...] | None:
    """The words that bear on calling off, in the gap after a status; ``None`` if it has others.

    The gap may hold filler, a hedge or a negation. Right after a preposition,
    in the same phrase, a school noun or a school's name is filler too ("delay
    for all schools cancelled", "delay at Lincoln Elementary has been lifted"),
    and so is a cause ("2 hour delay due to possible flooding has been
    cancelled"): neither is returned. Anywhere else a noun is what the word
    calls off ("2 hour delay for students, classes cancelled").
    """
    kept: list[str] = []
    for segment in _MARKS.split(text[start:end]):
        preposition = cause = False
        for token in words(segment):
            if token in _CAUSE_WORDS:
                cause = True
            elif token in _PREPOSITIONS:
                preposition = True
            elif token in _DETERMINERS or (
                cause and (token in {"to", "of"} or token not in _AFTER_GLUE)
            ):
                continue  # "due to the icy roads"
            elif token in _AFTER_GLUE or token in NEGATIONS or token in _UNSURE:
                preposition = cause = False
                kept.append(token)
            elif not (preposition and _in_name(token)):
                return None
    return tuple(kept)


def _in_name(token: str) -> bool:
    """Whether ``token`` can be part of a school's name: a school noun, or a word no list holds."""
    return (
        token in _SCHOOL_NOUNS
        or token in _INSTITUTIONS
        or (token.isalpha() and token not in _KNOWN and token not in SCOPES)
    )


def _before_ok(gap: tuple[str, ...], *, school_nouns: bool) -> bool:
    """Whether a gap between a calling-off verb and a status holds only its object's filler."""
    return all(token in _BEFORE_GLUE or (school_nouns and token in _SCHOOL_NOUNS) for token in gap)


def _dated(groups: tuple[DateGroup, ...], start: int, end: int) -> bool:
    return any(start <= group[GROUP_START] < end for group in groups)


def _object_after(text: str, start: int, end: int) -> tuple[Scope | None, bool]:
    """The noun a calling-off verb takes after it, and whether a preposition comes first.

    "Cancelled all activities" and "Cancelled: all classes" have an object;
    "cancelled for students" names who the calling off is for.
    """
    tokens = words(text, start, end)[:5]
    preposition = False
    for position, token in enumerate(tokens):
        if token in _OBJECT_PREPOSITIONS:
            preposition = True
            continue
        if token in _DETERMINERS or token in MODIFIERS or _GRADE.fullmatch(token):
            continue
        pair = " ".join(tokens[position : position + 2])
        scope = SCOPES.get(pair) or SCOPES.get(token)
        return scope, preposition
    return None, preposition


def _attach(  # noqa: PLR0913, PLR0917 - the text's parts, and where each sits
    text: str,
    clauses: Sequence[Span],
    mentions: list[Mention],
    homes: list[int],
    index: int,
    groups: tuple[DateGroup, ...],
    used: set[int],
) -> _Found | None:
    """Find the status the calling-off word at ``index`` is attached to, if any.

    The status is the mention right after the word or right before it, and only
    one of a kind a word can call off (see :func:`_category`): with none beside
    it, the word is attached to nothing, and nothing else is read.
    """
    word = mentions[index]
    following = index + 1
    after = mentions[following] if following < len(mentions) and following not in used else None
    after_category = None if after is None else _category(text, after)
    preceding = index - 1
    status = mentions[preceding] if preceding >= 0 and preceding not in used else None
    status_category = None if status is None else _category(text, status)
    if after_category is None and status_category is None:
        return None
    clause = clauses[homes[index]]
    same = index > 0 and homes[index - 1] == homes[index]
    base = mentions[index - 1].end if same else clause.start
    # The words before the word in its phrase, after any heading: "Oak Academy: rescinded".
    lead = (
        words(text, max(base, text.rfind(":", base, word.start) + 1), word.start)
        if base < word.start
        else []
    )
    replaced = (
        after
        if after is not None
        and after_category in _OBJECTS
        and status is not None
        and status_category is not None
        and _traded(text, status, word, after)
        else None
    )
    if after is not None and after_category in _OBJECTS and replaced is None:
        gap = tuple(words(text, word.end, after.start))
        if (
            _mark(text, word.end, after.start) == _NO_MARK
            # (With a subject of its own before the word, "for" gives the reason: "Zero hour
            # cancelled for the 2 hour delay" calls off the zero hour, not the delay.)
            and not (lead and gap[:1] == ("for",))
            and _before_ok(gap, school_nouns=True)
            and (not _SCOPE_WORDS.intersection(lead) or not _AGENTS.isdisjoint(lead))
        ):
            return _Found(following, "object", _NO_MARK, gap)
    found: _Found | None = None
    if status is not None and status_category is not None:
        mark = _mark(text, status.end, word.start)
        # Across a sentence mark only a word with no subject of its own, alone to the end of
        # its sentence, can call the status off: the gap is read only when it can matter.
        sentence = mark == _STRONG_MARK and (
            set(lead) <= _NO_SUBJECT
            and not _dated(groups, clause.start, clause.end)
            and all(token in _TRAILING for token in words(text, word.end, clause.end))
        )
        between = (
            _after_gap(text, status.end, word.start) if mark < _STRONG_MARK or sentence else None
        )
        if between is not None:
            if mark < _STRONG_MARK:
                home = clauses[homes[preceding]]
                split = _dated(groups, word.end, clause.end) and _dated(
                    groups, home.start, word.start
                )
                found = _Found(preceding, "after", mark, between, split)
            else:
                found = _Found(preceding, "sentence", mark, between)
    if found is None and after is not None and after_category is not None:
        gap = tuple(words(text, word.end, after.start))
        if (
            _mark(text, word.end, after.start) == _WEAK_MARK
            and _before_ok(gap, school_nouns=False)
            and set(lead) <= _NO_SUBJECT
        ):
            found = _Found(following, "label", _WEAK_MARK, gap)
    if found is None:
        return None
    # A noun of its own after the word takes it from the status before it and the label
    # after it: "cancelled all activities", "cancelled for kindergarten".
    scope, preposition = _object_after(text, word.end, clause.end)
    if scope is not None and (not preposition or scope != "school"):
        return None
    if replaced is not None and status is not None and found.target == preceding:
        _replace(status, replaced)
    return found


def _traded(text: str, status: Mention, word: Mention, after: Mention) -> bool:
    """Whether a calling-off word right after ``status`` is followed by "for" or "in favor of",
    an article at most, and the status ``after`` it: "Closure cancelled for a 2 hour delay"
    (not "Learning canceled for SMCS school on Friday. 3 hour early dismissal")."""
    gap = words(text, word.end, after.start)
    if gap and gap[-1] in _ARTICLES:
        gap = gap[:-1]
    return (
        tuple(gap) in _TRADE_LINKS
        and not words(text, status.end, word.start)
        and _mark(text, status.end, word.start) == _NO_MARK
        and _mark(text, word.end, after.start) == _NO_MARK
    )


# The words that trade a status called off for the one after them (see _traded).
_TRADE_LINKS = frozenset({("for",), ("in", "favor", "of"), ("in", "favour", "of")})
_ARTICLES = frozenset({"a", "an", "the"})


def _replace(status: Mention, replaced: Mention) -> None:
    """Make ``replaced`` what replaces ``status``, called off (see :func:`_traded`): a judgment
    call, as a change's new status is. One of the same kind ("2 hour delay cancelled for a 2
    hour delay") says nothing sure."""
    if replaced.kind == status.kind:
        replaced.dropped = "ambiguous"
    else:
        replaced.superseding = True
        replaced.strength = min(replaced.strength, JUDGMENT)


def _chain(  # noqa: PLR0913 - the text's parts, and which way to look
    text: str,
    mentions: list[Mention],
    target: int,
    *,
    before: bool,
    groups: tuple[DateGroup, ...],
    used: set[int],
) -> list[int]:
    """The target and the statuses joined to it by "and" or "or", away from the word."""
    chain = [target]
    step = -1 if before else 1
    current = target
    while 0 <= current + step < len(mentions):
        other = current + step
        low, high = sorted((current, other))
        start, end = mentions[low].end, mentions[high].start
        gap = words(text, start, end)
        if (
            other in used
            or _category(text, mentions[other]) is None
            or not gap
            or not _JOINERS.issuperset(gap)
            or _mark(text, start, end) == _STRONG_MARK
            or _dated(groups, start, end)
        ):
            break
        chain.append(other)
        current = other
    return chain


def _outcome(text: str, word: Mention, status: Mention, found: _Found, clause: Span) -> Outcome:
    """What calling ``status`` off by ``word`` (in ``clause``) comes to."""
    # A negation between the two, or just before a verb that comes first: "2 hour delay has
    # not been cancelled", "We are not cancelling the delay".
    near = (
        found.gap
        if found.rule in {"after", "sentence"}
        else (
            *words(text, clause.start, word.start)[-2:],
            *found.gap,
        )
    )
    if not NEGATIONS.isdisjoint(near):
        return "kept"
    if (
        not _UNSURE.isdisjoint(near)
        or _CONDITIONAL.search(text, clause.start, clause.end) is not None
        or text.startswith("?", clause.end)
    ):
        return "hedged"  # "Delay may be lifted", "Delay will be lifted if roads clear"
    category = _category(text, status)
    ambiguous = (
        found.rule in {"sentence", "label"}  # "2 hour delay. Cancelled.", "Cancelled - NTI day"
        or category == "closed"  # "Closed - cancelled"
        or (category == "closure" and found.mark != _NO_MARK)  # "Snow day: cancelled"
        or found.split  # "2 hour delay today, cancelled tomorrow"
    )
    if ambiguous and word.revokes == "cancel" and found.rule != "object":
        return "ambiguous"
    return "revoked"


def _apply(status: Mention, outcome: Outcome) -> None:
    if outcome == "revoked":
        status.revoked = True
    elif outcome == "ambiguous":
        status.dropped = "ambiguous"
    elif outcome == "hedged":
        status.dropped = "hedged"
