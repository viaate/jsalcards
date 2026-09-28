"""Match a closings listing to the district or school it names.

:meth:`Matcher.match` takes the listing text as the closings source shows it and
where the source is (its states, optionally its counties and a point near its
market) and returns a :class:`MatchResult`:

1. An alias for the listing's exact text in its market (``config/aliases.yaml``)
   always wins.
2. Otherwise the listing is cleaned (:func:`~snowlight.match.normalize.clean_listing`),
   read as a district name and as a school name, and scored against every
   plausible record in its states and counties (:class:`~snowlight.match.index.NameIndex`).
   NCES's naming habits are read both ways: Tennessee's ``"Murfreesboro"`` is the
   lists' ``"Murfreesboro City Schools"``, Michigan's ``"Washtenaw ISD"`` their
   ``"Washtenaw Intermediate School District"``, Indiana's ``"South Ripley Com
   Sch Corp"`` their ``"South Ripley Community Schools"``, Pennsylvania's
   ``"Bensalem Township SD"`` their ``"Bensalem School District"`` (a municipal
   word one side says costs nothing unless another record in scope bears the
   rest of the name, as ``"Bristol Borough SD"`` does beside ``"Bristol Township
   SD"``; see :mod:`snowlight.match.lexicon` and :meth:`~snowlight.match.index.NameIndex.search`).
   A listing that names a college, university or seminary (``"Boston
   College"``, :func:`~snowlight.match.normalize.non_k12`) is never accepted
   unless it is the name of a candidate's own town (``"State College"``); nor is
   one that names a civic body and nothing K-12 (``"City of Monessen"``,
   ``"Sabine Pass Senior Center"``, :func:`~snowlight.match.normalize.not_school`),
   unless it is only a town's name (``"Falls Church"``); a parish's church
   (``"St. Peter's Parish: No Mass"``) is one such body, but a Louisiana
   parish's district is not (``"Acadia Parish"``). One that names an
   affiliation (``"Omaha Catholic Schools"``) only matches a record that names
   it too, or a saint's private school whose name implies the Catholic faith
   (``"St. Peter's Catholic School"`` for ``"ST PETER'S SCHOOL"``). One that is
   only a place's name (``"Napa"``, ``"Old Bridge"``, ``"Louisville"``) names
   that place's school district, never one school named for the place or in it
   (``"Napa High"``, ``"Village School of Louisville"``);
   only a town of that name within the listing's counties, or near its market,
   says whose district that is (``"Edgewood"`` on a San Antonio list is San
   Antonio's ``"Edgewood ISD"``, not the town of Edgewood's, 440 km away), and a
   district whose name is the listing's, word for word, is always as good a
   reading as the town's own: see :meth:`Matcher._read`.
3. The best candidate's confidence is its name score less a penalty when
   another candidate comes within :attr:`MatchSettings.margin` of it: two
   equally good names (two ``St. Mary's`` in one state) cannot be told apart by
   name. A rival is measured by its plausibility, its score without the
   penalties for details the listing merely leaves out, so ``"St. Mary's
   School"`` finds ``"St. Mary's Middle School"`` a full-strength rival. A
   school whose name leaves out the level a listing says is of the level its
   NCES grades are (:mod:`snowlight.match.grades`), as NCES leaves the word out
   of many names: ``"St. Joseph Elementary"`` names the PK-8 ``"ST JOSEPH
   SCHOOL"`` as surely as ``"ST JOSEPH ELEMENTARY SCHOOL"`` a town away, and
   ``"Lincoln Elementary"`` the K-5 ``"Lincoln"`` as surely as the ``"Lincoln
   Elementary"`` beside it, so each ties and goes to the queue; a school of
   other grades is none of that level, and one that teaches them and far more
   (a K-12 school, a PK-8 one for ``"Preschool"``) is a rival never taken on
   the level alone. A school named for a person may be listed by its surname
   and level (``"Kennedy Middle School"``): the forenames that listing leaves
   out weigh the same whether NCES spells them (``"John F Kennedy Middle"``)
   or gives only their initials (``"J F Kennedy Middle School"``), so two such
   schools of one surname in scope tie and go to the queue, and a school whose
   name is the listing's word for word comes before them; a surname and
   ``School`` alone (``"Pingree School"``) takes none of them, and a school
   whose forenames may be a place's words (``"Charles White"``, ``"Grace
   Hill"``) is only ever a rival (see
   :meth:`~snowlight.match.index.NameIndex._person`). A word written with a
   plural's ``s`` on one side only is another word (``"Park Elementary"`` is
   not ``"PARKS EL"``), though as close a rival. A
   district and its own schools do not compete, and the schools of one
   district that tie by name, every one of them (NCES splits ``"Great Bay
   Charter School"`` into ``"(H)"`` and ``"(M)"``), name that district. A
   listing that is a district's name, word for word, names that district, not
   one of its schools whose name adds a level or a part and so scores higher
   (``"Cumberland Academy"`` is the charter district of five schools, not its
   ``"Cumberland Academy Middle"``); when the district fits the listing's words
   too badly to be taken, neither is, and the listing goes to the queue (see
   :meth:`Matcher._exact_reading`). The other way round, a school whose name is
   the listing's, word for word, is the reading over its district whose name
   is not, the listing saying a word, a level or a legal form the district's
   name lacks (``"Cheatham Co Central"`` is one high school, not the
   ``"Cheatham County"`` district; ``"Selma Independent"`` is not ``"Selma
   Unified"``): see :meth:`Matcher._school_reading`. When ``near`` is given and
   names tie, a candidate much nearer than the rest wins the tie, but only when
   the rest lie outside the market: outside the listing's counties, or, with
   none given, farther than :attr:`MatchSettings.reach_km` from the point. Two
   ``"ST JOHN SCHOOL"`` in a Boston list's counties, 1 km and 17 km from its
   point, are both the market's; its point says nothing of which one the list
   means, and the listing goes to the queue (:meth:`Matcher._break_tie`).
   Otherwise districts of one town whose names differ only in their legal form
   (``"Detroit Public Schools Community District"`` and ``"Detroit Community
   Schools"``) are told apart by the legal-form words the listing says
   (:meth:`Matcher._legal_form_tie`);
   and districts that tie by name go to the one the listing names exactly, in
   its words, its legal form and its spelling (``"Saint Paul"`` is ``"Saint Paul
   Public Schools"``, not ``"St. Paul City School"``; ``"Genesee ISD"`` is not
   ``"Genesee School District"``; ``"Oak Hill Schools"`` is not ``"Oak Hills
   Local"``, see :meth:`Matcher._exact_tie`). Between districts of two counties
   only what the listing says that one name lacks decides (a distinct legal
   form, a spelling), never that it says no more than the other's: New Jersey's
   ``"Union Township School District"`` (Hunterdon County) and ``"Township of
   Union School District"`` (Union County) are two townships of one name, which
   ``"Union Township Public Schools"`` names alike, whatever its word order (see
   :func:`~snowlight.match.normalize.name_first`); only a point much nearer one
   of them, the other outside the market, tells, or the queue. Never across a
   state line: each state writes its NCES names its own way (Missouri's
   ``"KANSAS CITY 33"``, Kansas's ``"Kansas City"``; Tennessee's ``"Bristol"``,
   Virginia's ``"Bristol City Public Schools"``), so wording tells two states'
   namesakes apart no better than a coin. Names that tie across states, and an
   accepted district's namesake across the line however far apart the wording
   scores them, are told apart only by a point much nearer one of them, the
   other outside the market
   (:attr:`MatchSettings.near_ratio`, :attr:`MatchSettings.near_slack_km`,
   :attr:`MatchSettings.reach_km`), or by the state the listing names;
   otherwise the listing goes to the queue with both (:meth:`Matcher._undecided_across`).
4. With counties given, an accepted district is taken whole only when the
   market may speak for all its schools. A charter network named as one school
   (``"Premier High Schools"``, ``"Arrow Academy"``) with campuses outside the
   counties, or one whose schools lie far beyond them (``"IDEA Public
   Schools"``), is read as its campus in the market that the listing fits; two
   such campuses go to the queue, as both are the market's, whichever lies
   nearer its point. A district that straddles the market's edge, its schools
   near one another, stays whole: see :meth:`Matcher._within_market`.
5. When the whole listing is not accepted and it has parts (``"Lincoln
   Elementary - Springfield"``, ``"Springfield Public Schools: Lincoln
   Elementary"``), each part is tried as the name with the others read as its
   city, its county (``"Big Sandy ISD - Upshur County"``), its state or its
   district; a listing that ends with brackets, as NCES writes a name
   (``"Mason Consolidated Schools (Monroe)"``), is read as the name before them
   among the records that answer to them (:meth:`Matcher._with_brackets`); and
   a district code followed by a list of towns (``"MSAD 51 - Cumberland, North
   Yarmouth"``) is tried with each town.

6. A state the listing writes beside its name (``"Salem MA Public"``,
   ``"Knox County, TN Schools"``, ``"Shawnee R-3 MO Chilhowee"``) narrows the
   search to that state, and one outside the market names no record of it
   (:func:`~snowlight.match.states.state_mentions`).
7. A section a list files the listing under (``category``) that names one of
   the market's states (``"RI Public Schools"``, ``"Schools-IN"``) limits the
   search to that state first: WPRI's ``"Scituate Public Schools"`` under
   ``"RI Public Schools"`` is Rhode Island's, not Massachusetts's
   (:func:`~snowlight.match.states.category_states`). Otherwise the section is read last: a
   listing filed among churches, businesses or governments whose words name
   no school is none; and a listing that is only a saint's, a devotion's or a
   church's name (``"St. Peter's"``, ``"Christ the King"``, ``"Visitation"``)
   names its parish's school only when the list files it among schools, as the
   church shares the name (:attr:`Reason.PARISH`).
8. A listing's counties are its market, not a wall: a station's list strays
   into the counties just past them (WMUR, whose counties are the Boston
   market's, lists New Hampshire's Grafton County). A listing accepted in its
   counties is read again with those neighbours too (within
   :attr:`MatchSettings.reach_km`, see
   :meth:`~snowlight.match.index.NameIndex.around`), in the same states; when a
   record there fits it as well, or better (``"Hanover High School"`` of
   Hanover, New Hampshire, beside Massachusetts's ``"Hanover High"`` in the
   counties), the counties cannot say which it names, and it goes to the queue
   with both (:meth:`Matcher._past_counties`). A record there is never
   accepted in place of one in the counties.
9. A listing that names a school system NCES splits into several districts
   names all of them (:mod:`snowlight.match.systems`, :meth:`Matcher._as_system`):
   ``"Billings Public Schools"`` is ``"Billings Elem"`` and ``"Billings H S"``,
   ``"Kalispell"`` is ``"Kalispell Elem"`` and ``"Flathead H S"``, run from one
   office, and ``"NYC DOE"`` the 33 districts of New York City's public schools.
   The result's :attr:`MatchResult.targets` holds every one, and
   :meth:`Matcher.expand` every school of them. A listing that says a level
   (``"Billings Elementary"``) or a number (``"NYC District 75"``) names one
   district, as before; so does one that says a legal-form word only one of
   them says (``"Phoenix Union"``).

10. A listing of nothing but words that say what kind of school it is
    (``"Christian Academy"``, ``"Learning Center"``, ``"Day Care"``) names only a
    school whose name it is, word for word and in order, never one that holds
    those words among others or in another order (:meth:`Matcher._kind_only`).

Only a confidence of at least :attr:`MatchSettings.threshold` is accepted; any
other result carries its best candidates so it can go to the unmatched queue
(:mod:`snowlight.match.queue`). An alias may pin a listing to several records
(:mod:`snowlight.match.aliases`), all of which it names.
"""

import itertools
import math
import re
from collections.abc import Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from snowlight.match import lexicon
from snowlight.match.aliases import Aliases
from snowlight.match.directory import Directory, DirectoryRecord
from snowlight.match.index import (
    COUNTY_LEFT_OUT,
    REACH_KM,
    STRAY_SHARE,
    NameIndex,
    Scope,
    Scored,
    Town,
    city_key,
    haversine_km,
    levels_said,
    place_keys,
)
from snowlight.match.normalize import (
    CleanListing,
    Level,
    ListingForms,
    NameForm,
    Section,
    bracket_form,
    church_name,
    clean_listing,
    county_words,
    is_bare_name,
    listing_forms,
    listing_section,
    names_a_school,
    non_k12,
    not_school,
    record_form,
    spelled_name,
    stem,
    without_charter_school,
)
from snowlight.match.states import StateMention, category_states, spelled_in, state_mentions
from snowlight.match.systems import SchoolSystem, Systems, names_a_system

_STATE: Final = re.compile(r"[A-Z]{2}")
_COUNTY: Final = re.compile(r"\d{5}")
_MAX_LATITUDE: Final = 90.0
_MAX_LONGITUDE: Final = 180.0
MAX_SEGMENTS: Final = 3
MIN_THRESHOLD: Final = 0.1
"""The lowest threshold a matcher accepts: far above the score of a ruled-out record."""
PLACE_SCHOOL: Final = 0.75
"""The share of its name score a candidate keeps that is not the place a listing
that is only a place's name names.

``"Louisville"`` names Louisville's school district, not ``"Village School of
Louisville"``, and ``"Neptune"`` the township's district, not ``"Neptune City School
District"`` next door: such a candidate ranks below every district of the place
that fits the name nearly as well. A school is never accepted for a place's name
(:attr:`Reason.PLACE`); it stays among the candidates, for the unmatched queue. See
:meth:`Matcher._as_place`.
"""
NAMESAKE_FLOOR: Final = 0.6
"""The plausibility a district's namesake across a state line needs to leave a listing
undecided (see :meth:`Matcher._namesakes_across`).

A namesake has the winner's words, levels and kind of place, so only how its state
writes names (a ``County`` a listing leaves out, which Florida's ``"ESCAMBIA"``
implies and Alabama's ``"Escambia County"`` says) keeps its score lower; this far
down, something the listing says rules it out.
"""
_NO_CANDIDATE: Final = "no record in the states and counties searched resembles it"
_NAMES_SHOWN: Final = 3
"""How many districts of a school system a result's detail names."""
_BELOW: Final = 0.001
"""How far under the threshold a listing that ties stays, whatever its name scores."""
_KIND_ONLY: Final = frozenset(stem(word) for word in lexicon.KIND_ONLY_WORDS)
""":data:`~snowlight.match.lexicon.KIND_ONLY_WORDS` as a name's tokens give them."""
_LINKING: Final = frozenset({"and", "of", "at", "for", "in", "on", "to", "the"})
"""Words that link a name's words, which a name said word for word may add or drop."""


class Reason(StrEnum):
    """Why a listing was or was not matched."""

    ALIAS = "alias"
    """Pinned in ``aliases.yaml``."""
    NAME = "name"
    """The name alone is close enough and no other name is as close."""
    NEAREST = "nearest"
    """Equally close names; this one is much nearer the listing's point, the rest outside.

    Outside its market: outside the listing's counties, or, with none given, farther than
    :attr:`MatchSettings.reach_km` from its point: see :meth:`Matcher._break_tie`.
    """
    CONTEXT = "context"
    """Matched once a city, state or district named beside it narrowed the search."""
    AMBIGUOUS = "ambiguous"
    """Close enough by name, but another name is just as close."""
    WEAK = "weak"
    """The best name is not close enough."""
    NO_CANDIDATE = "no_candidate"
    """No name in the listing's states and counties resembles it."""
    ALIAS_UNKNOWN = "alias_unknown"
    """Pinned in ``aliases.yaml`` to an id the directory does not hold."""
    EMPTY = "empty"
    """Nothing is left once the noise is removed (``"Schools"``, ``"(Closed)"``)."""
    NOT_K12 = "not_k12"
    """Names a college, university or seminary (``"Boston College"``), not a K-12 school."""
    NOT_SCHOOL = "not_school"
    """Names a government, a community place, a hospital, a church or a business.

    ``"City of Monessen"``, ``"Monessen City Hall"``, ``"Sabine Pass Senior
    Center"``, ``"First Baptist Church of Marion"``, ``"Royston, LLC"``: see
    :func:`~snowlight.match.normalize.not_school`.
    """
    PLACE = "place"
    """Names only a place, and none of the candidates is that place's district.

    ``"Louisville"``, ``"Raleigh"``, ``"Oswego"``: a town's name on a closings list
    is its school system, never the one school named for the town or in it
    (``"Village School of Louisville"``, ``"Oswego High School"``), and the
    system's own name here says something else (``"Jefferson County"``, ``"CUSD
    308"``). See :meth:`Matcher._read`.
    """
    CAMPUS = "campus"
    """Names a district that runs schools beyond the market; its one school there that fits.

    ``"Premier High School"`` on a list whose counties hold one campus of the
    statewide network ``"Premier High Schools"`` is that campus, never the
    network's schools in other cities. See :meth:`Matcher._within_market`.
    """
    OTHER_STATE = "other_state"
    """Names a state beside its name that the market does not cover.

    ``"Salem MA Public"`` on a New Hampshire list, ``"Harmony (OK) Public
    Schools"`` on a Texas one: the listing is about the other state's record,
    never a namesake in the market. See
    :func:`~snowlight.match.states.state_mentions`.
    """
    NETWORK = "network"
    """Names a district that runs schools beyond the market, none of them there fits.

    The listing cannot be about the district's other cities, and no campus in
    the market answers to it: ``"Halcyon Academy"`` where the network's only
    campus in the counties is its ``"Halcyon College Prep - Belltown"``.
    """
    PARISH = "parish"
    """Names a saint, a devotion or a church's faith, and nothing of a school.

    A parish and its school share a name: ``"St. Peter's"``, ``"Christ the
    King"`` or ``"Visitation"`` on a list that carries churches beside schools
    is the church as surely as the school. The school is the listing's only
    when the listing says a school's word (``"St. Peter's School"``) or the list
    files it among schools (``category``, see :meth:`Matcher.match`); otherwise
    it goes to the unmatched queue with the school first. See
    :func:`~snowlight.match.normalize.church_name`.
    """
    SYSTEM = "system"
    """Names a school system NCES splits into several districts, and names them all.

    ``"Billings Public Schools"`` for ``"Billings Elem"`` and ``"Billings H S"``,
    ``"NYC DOE"`` for New York City's geographic districts: see
    :mod:`snowlight.match.systems` and :meth:`Matcher._as_system`.
    """


ACCEPTED: Final = frozenset(
    {Reason.ALIAS, Reason.NAME, Reason.NEAREST, Reason.CONTEXT, Reason.CAMPUS, Reason.SYSTEM}
)
_NOT_A_SCHOOL: Final = frozenset({Reason.NOT_K12, Reason.NOT_SCHOOL, Reason.EMPTY, Reason.PARISH})
"""Reasons that say what a listing is, which the state it names does not change."""


@dataclass(frozen=True, slots=True)
class MatchSettings:
    """The matcher's decision rules.

    Attributes:
        threshold: the lowest confidence accepted. Chosen on the synthetic
            fixture in ``tests/match`` for at least 99% precision. At least
            :data:`MIN_THRESHOLD`, so a record the listing rules out (by an
            affiliation it does not carry) is never accepted.
        margin: a runner-up within this much of the best score costs confidence.
        margin_slope: confidence lost per unit the runner-up is inside the margin,
            so an exact tie costs ``margin * margin_slope``.
        tie: scores this close count as a tie that ``near`` may break.
        near_ratio, near_slack_km: a tie goes to the nearest candidate only when
            the next is at least ``near_ratio`` times as far plus ``near_slack_km``,
            and every other lies outside the listing's market (see ``reach_km``
            and :meth:`Matcher._break_tie`).
        near_max_km: and only when the nearest is within this distance.
        runners_up: how many runners-up a result keeps.
        reach_km: a district whose schools lie farther than this from the
            listing's counties is not taken whole, and a county with a record
            this near one in them is just past them, where a namesake leaves an
            accepted listing ambiguous (see :data:`~snowlight.match.index.REACH_KM`
            and :meth:`Matcher._past_counties`). A listing read in whole states
            has its market within this distance of its point: a namesake that
            near is the market's as much as the one beside the point, which does
            not break their tie.
        stray_share: the share of its schools that may lie that far and leave
            it whole (see :data:`~snowlight.match.index.STRAY_SHARE`).
    """

    threshold: float = 0.85
    margin: float = 0.10
    margin_slope: float = 2.0
    tie: float = 0.03
    near_ratio: float = 2.0
    near_slack_km: float = 10.0
    near_max_km: float = 160.0
    runners_up: int = 5
    reach_km: float = REACH_KM
    stray_share: float = STRAY_SHARE

    def __post_init__(self) -> None:
        if not MIN_THRESHOLD <= self.threshold <= 1.0:
            raise ValueError(f"threshold must be in [{MIN_THRESHOLD}, 1]")
        if self.margin < 0 or self.margin_slope < 0 or self.tie < 0:
            raise ValueError("margin, margin_slope and tie must not be negative")
        if self.near_ratio < 1.0 or self.near_slack_km < 0 or self.near_max_km <= 0:
            raise ValueError("near_ratio must be at least 1 and the distances positive")
        if self.runners_up < 0:
            raise ValueError("runners_up must not be negative")
        if self.reach_km <= 0 or not 0.0 <= self.stray_share < 1.0:
            raise ValueError("reach_km must be positive and stray_share in [0, 1)")


@dataclass(frozen=True, slots=True)
class Candidate:
    """A directory record considered for a listing.

    Attributes:
        record: the district or school.
        score: its name score, 0-1, after every penalty.
        distance_km: distance from the listing's ``near`` point, when both are known.
    """

    record: DirectoryRecord
    score: float
    distance_km: float | None


@dataclass(frozen=True, slots=True)
class MatchResult:
    """What :meth:`Matcher.match` decided for one listing.

    Attributes:
        listing: the listing text as given.
        market: the market it was looked up in, if any.
        states: the states searched.
        counties: the counties searched, or ``None`` for whole states.
        level: whether the listing's words read as a district, a school or either.
        target: the matched district or school, or ``None`` when not accepted.
            When the listing names several records, the first of :attr:`targets`.
        confidence: 0-1; accepted results are at or above the threshold.
        reason: why, as a :class:`Reason`.
        detail: one line that explains the reason, for the unmatched queue and logs.
        best: the best candidate, accepted or not.
        runners_up: the next best candidates, best first.
        category: the section the list filed the listing under, as given.
        targets: every record the listing names, :attr:`target` first; empty when
            not accepted. More than one for a school system NCES splits into
            several districts (:attr:`Reason.SYSTEM`: ``"Billings Public
            Schools"`` is ``"Billings Elem"`` and ``"Billings H S"``) and for an
            alias pinned to several records. Always begins with :attr:`target`:
            a result whose target is replaced alone names that target alone.
    """

    listing: str
    market: str | None
    states: tuple[str, ...]
    counties: tuple[str, ...] | None
    level: Level
    target: DirectoryRecord | None
    confidence: float
    reason: Reason
    detail: str
    best: Candidate | None
    runners_up: tuple[Candidate, ...]
    category: str | None = None
    targets: tuple[DirectoryRecord, ...] = ()

    def __post_init__(self) -> None:
        target = self.target
        targets = self.targets
        if target is None:
            kept: tuple[DirectoryRecord, ...] = ()
        elif not targets or targets[0].id != target.id:
            kept = (target,)
        else:
            return
        if kept != targets:
            object.__setattr__(self, "targets", kept)

    @property
    def accepted(self) -> bool:
        """True when the listing is matched to :attr:`target` (and the rest of :attr:`targets`)."""
        return self.target is not None


@dataclass(frozen=True, slots=True)
class _Outcome:
    winner: Scored | None
    confidence: float
    reason: Reason
    detail: str
    ranked: tuple[Scored, ...]
    distances: dict[int, float] = field(default_factory=dict)
    joint: tuple[int, ...] = ()
    """The positions of the other districts of the school system the listing names
    with :attr:`winner` (see :meth:`Matcher._as_system`)."""

    @property
    def accepted(self) -> bool:
        return self.winner is not None and self.reason in ACCEPTED


@dataclass(frozen=True, slots=True)
class _Context:
    """What a context part of a listing narrows the search to, and how sure that is.

    ``said``: what the record must answer to besides lying in the scope
    (:meth:`~snowlight.match.index.NameIndex.answers_to`): a county's name is
    the county a district's office lies in, not one a school of it strays into.
    """

    scope: Scope
    confidence: float
    note: str
    said: tuple[NameForm, ...] = ()


@dataclass(frozen=True, slots=True)
class _Place:
    """How a listing that is only a place's name names it.

    Attributes:
        towns: the towns of that name within the listing's reach (see
            :meth:`Matcher._place`), by state and
            :func:`~snowlight.match.index.place_keys`, with the positions of the
            districts whose office or schools lie in each. Empty when the place
            is known only by a district's own name (``"Coffee"``), or every town
            of the name lies outside the listing's counties or far from its
            market (``"Edgewood"`` on a San Antonio list, whose ``"Edgewood
            ISD"`` is named for a neighbourhood; the town of Edgewood lies 440
            km away).
        districts: the districts of all of them.
        town: see below.
    """

    towns: Mapping[tuple[str, str], frozenset[int]]
    districts: frozenset[int]
    town: bool = True
    """The name is a town's in the listing's states, near or far; not only a
    district's own name (``"Coffee"``, ``"Warren County Vocational"``)."""


_NO_TOWNS: Final[Mapping[tuple[str, str], frozenset[int]]] = MappingProxyType({})
_TOWNSHIP: Final = "township"
_EMPTY_INDICES: Final[frozenset[int]] = frozenset()


def _ranked_down(scored: Scored) -> Scored:
    """A candidate that is not the place a listing names: see :data:`PLACE_SCHOOL`."""
    return Scored(scored.index, scored.score * PLACE_SCHOOL, scored.plausibility * PLACE_SCHOOL)


@dataclass(frozen=True, slots=True)
class _Tie:
    """A tie between equally good names that distance, or the names' legal forms, broke."""

    winner: Scored
    tied: frozenset[int]
    note: str
    reason: "Reason"


def _states(states: Collection[str]) -> frozenset[str]:
    if isinstance(states, str):
        raise TypeError("states must be a collection of state codes, not one string")
    codes = frozenset(state.strip().upper() for state in states)
    if not codes:
        raise ValueError("a listing needs at least one state")
    bad = sorted(code for code in codes if not _STATE.fullmatch(code))
    if bad:
        raise ValueError(f"not USPS state codes: {bad}")
    return codes


def _counties(counties: Collection[str] | None) -> frozenset[str] | None:
    if counties is None:
        return None
    if isinstance(counties, str):
        raise TypeError("counties must be a collection of FIPS codes, not one string")
    codes = frozenset(county.strip() for county in counties)
    bad = sorted(code for code in codes if not _COUNTY.fullmatch(code))
    if bad or not codes:
        raise ValueError(f"counties must be 5-digit FIPS codes, got {sorted(counties)}")
    return codes


def _near(near: tuple[float, float] | None) -> tuple[float, float] | None:
    if near is None:
        return None
    lat, lon = near
    if not (abs(lat) <= _MAX_LATITUDE and abs(lon) <= _MAX_LONGITUDE):
        raise ValueError(f"near must be (lat, lon) in degrees, got {near}")
    return (float(lat), float(lon))


class Matcher:
    """Matches listings against one directory.

    Building the index normalizes every name once; after that each
    :meth:`match` call only reads it, so one matcher serves every market.
    """

    def __init__(
        self,
        directory: Directory,
        *,
        aliases: Aliases | None = None,
        settings: MatchSettings | None = None,
    ) -> None:
        self.directory = directory
        self.index = NameIndex(directory)
        self.systems = Systems(self.index)
        self.aliases = aliases if aliases is not None else Aliases()
        self.settings = settings if settings is not None else MatchSettings()

    def expand(self, target: MatchResult | DirectoryRecord | str) -> tuple[DirectoryRecord, ...]:
        """Return every school a match covers.

        For a :class:`MatchResult`, the schools of every one of its
        :attr:`~MatchResult.targets` (none when it was not accepted), each once,
        in the order of the targets; for a district, its schools; for a school,
        the school itself.

        Raises:
            KeyError: if ``target`` is an id that is not in the directory.
        """
        if not isinstance(target, MatchResult):
            return self.directory.expand(target)
        seen: set[str] = set()
        schools: list[DirectoryRecord] = []
        for record in target.targets:
            for school in self.directory.expand(record):
                if school.id not in seen:
                    seen.add(school.id)
                    schools.append(school)
        return tuple(schools)

    def match(  # noqa: PLR0913 - the listing, where it is listed, and how
        self,
        listing_name: str,
        *,
        states: Collection[str],
        counties: Collection[str] | None = None,
        near: tuple[float, float] | None = None,
        market: str | None = None,
        category: str | None = None,
    ) -> MatchResult:
        """Match one listing.

        Args:
            listing_name: the listing text as the closings source shows it.
            states: USPS codes of the states the source covers; only records in
                them are candidates.
            counties: 5-digit FIPS codes; when given, only schools in them and
                districts that touch them are candidates.
            near: ``(lat, lon)`` of the source's market, used to break ties
                between equally good names.
            market: the source's id, for aliases.
            category: the section the source files the listing under, as it
                names it (``"Schools"``, ``"Churches"``, ``"Business"``,
                ``"Gov't."``), when it has sections; a source that lists only
                schools passes ``"Schools"``. In a section of anything but
                schools a listing whose words name no school matches nothing
                (:attr:`Reason.NOT_SCHOOL`); one of schools lets a saint's name be
                its school's (:attr:`Reason.PARISH`), and a government's name
                (``"Township of Union"``) the district's that bears it. See
                :func:`~snowlight.match.normalize.listing_section`. A section
                that names one of ``states`` (``"RI Public Schools"``,
                ``"Schools-IN"``) limits the search to that state
                (:func:`~snowlight.match.states.category_states`).

        Raises:
            ValueError: on an empty or malformed state list, county list or point.
        """
        state_codes = _states(states)
        county_codes = _counties(counties)
        point = _near(near)
        pinned = self.aliases.lookup(market, listing_name)
        if pinned is not None:
            blank = self._blank(listing_name, listing_name, market, state_codes, county_codes)
            return replace(self._alias(blank, pinned, point), category=category)
        filed = category_states(category, state_codes)
        if len(filed) == 1:
            # "Scituate Public Schools" filed under "RI Public Schools" is Rhode Island's.
            state_codes = filed
        section = listing_section(category)
        result = self._by_name(
            listing_name, market, state_codes, county_codes, point, section=section
        )
        if county_codes is not None and result.accepted:
            result = self._past_counties(
                result, listing_name, market, state_codes, county_codes, point, section=section
            )
        return self._in_section(replace(result, category=category), listing_name, category)

    def _past_counties(  # noqa: PLR0913, PLR0917 - the result, and how it was reached
        self,
        result: MatchResult,
        listing_name: str,
        market: str | None,
        states: frozenset[str],
        counties: frozenset[str],
        point: tuple[float, float] | None,
        *,
        section: Section = Section.UNKNOWN,
    ) -> MatchResult:
        """An accepted listing read again with the counties just past its own.

        A station's list names schools past its market's counties: WMUR's
        counties are the Boston market's, and it lists New Hampshire's
        ``"Hanover High School"``, in Grafton County, beside the counties'
        ``"Hanover High"`` of Hanover, Massachusetts. The counties cannot tell
        such namesakes apart. So the listing is read again in the same states
        with the counties around its own
        (:meth:`~snowlight.match.index.NameIndex.around`, within
        :attr:`MatchSettings.reach_km`): when that reading still takes the
        record accepted, it stands (at the lower of the two confidences); when
        it takes a record past the counties, or takes none because one there
        comes within :attr:`MatchSettings.margin` of the record accepted
        (``"Littleton School District"``, New Hampshire's name word for word,
        beside Massachusetts's ``"Littleton"``), the listing goes to the queue
        as ambiguous with both. A record past the counties is never accepted in
        place of the one in them, and a namesake far beyond them (Alabama's
        Henry County on an Atlanta list) is none of the listing's.

        A reading that differs only as the wider counties change it (a network
        that has more campuses in them, a town that lies there) and that no
        record past the counties decides leaves the result as it was.
        """
        ring = self.index.around(counties, states, reach_km=self.settings.reach_km)
        if not ring:
            return result
        wide = self._by_name(
            listing_name, market, states, counties | ring, point, section=section, home=counties
        )
        return self._beside(result, wide, counties)

    def _beside(
        self, result: MatchResult, wide: MatchResult, counties: frozenset[str]
    ) -> MatchResult:
        """``result``, accepted in ``counties``, read against ``wide``, read past them too.

        See :meth:`_past_counties`. When the wider reading takes no record, the
        records past the counties among its candidates are why: they are all it
        adds. They go to the queue beside the record accepted, best first.
        """
        target = result.target
        best = result.best
        if target is None or best is None:  # pragma: no cover - only accepted results come here
            return result
        found = wide.target
        targets = result.targets
        if found is not None and found.id in {record.id for record in targets}:
            confidence = min(result.confidence, wide.confidence)
            if wide.reason is Reason.NEAREST and result.reason is not Reason.NEAREST:
                # A point told the namesake past the counties apart.
                detail = f"{wide.detail}, beside a namesake just past the counties"
                return replace(result, confidence=confidence, reason=wide.reason, detail=detail)
            return replace(result, confidence=confidence)
        strays = [
            candidate
            for candidate in (wide.best, *wide.runners_up)
            if candidate is not None and self._past(candidate.record, targets, counties)
        ]
        if not strays or (found is not None and not self._past(found, targets, counties)):
            # The wider counties changed the reading; no record past them decides it.
            return result
        stray = strays[0]
        where = stray.record.county or stray.record.county_fips or "a county"
        runners: dict[str, Candidate] = {}
        for candidate in (*strays, *result.runners_up):
            runners.setdefault(candidate.record.id, candidate)
        return replace(
            result,
            target=None,
            confidence=self._short_of(result.confidence),
            reason=Reason.AMBIGUOUS,
            detail=(
                f"{target.name!r} in the counties scores {best.score:.3f}, but "
                f"{stray.record.name!r}, in {where}, {stray.record.state}, just past them, "
                f"scores {stray.score:.3f}"
            ),
            runners_up=tuple(runners.values())[: self.settings.runners_up],
        )

    def _past(
        self,
        record: DirectoryRecord,
        targets: Sequence[DirectoryRecord],
        counties: frozenset[str],
    ) -> bool:
        """True when ``record`` lies past ``counties`` and is no part of any of ``targets``.

        A district that touches the counties is in them; a school of the
        district accepted, or the district of the school accepted, is part of it.
        """
        if self.index.in_counties(self.index.index_of(record.id), counties):
            return False
        return all(
            target.id not in {record.id, record.district_id} and target.district_id != record.id
            for target in targets
        )

    def _by_name(  # noqa: PLR0913 - the listing, where it is listed, and how
        self,
        listing_name: str,
        market: str | None,
        states: frozenset[str],
        counties: frozenset[str] | None,
        point: tuple[float, float] | None,
        *,
        section: Section = Section.UNKNOWN,
        home: frozenset[str] | None = None,
    ) -> MatchResult:
        """Match a listing by its name, in the state it names beside it if any.

        ``home``: the listing's own counties when ``counties`` reaches past them
        (:attr:`~snowlight.match.index.Scope.home`).
        """
        plain = self._listing(
            listing_name, listing_name, market, states, counties, point, section=section, home=home
        )
        mentions = state_mentions(listing_name, states)
        if not mentions:
            return plain
        local = [mention for mention in mentions if mention.in_market]
        foreign = [mention for mention in mentions if not mention.in_market]
        if foreign and not any(mention.beside for mention in local):
            return self._in_other_state(plain, foreign)
        return self._in_named_state(
            plain, local, market, counties, point, section=section, home=home
        )

    def _in_section(
        self, result: MatchResult, listing_name: str, category: str | None
    ) -> MatchResult:
        """A result read against the section the list filed its listing under.

        A section of anything but schools (``"Churches"``, ``"Business"``,
        ``"Government"``) says a listing whose words name no school is none
        (``"Visitation"`` among churches, ``"Albemarle County"`` among
        governments): its candidates stay, for the unmatched queue. A listing
        whose words say a school keeps its reading wherever it is filed: lists
        file parish schools among churches and Montessori schools among day
        cares (``"Bethlehem Lutheran School"``, ``"Clay Platte Montessori
        School"``, see :func:`~snowlight.match.normalize.names_a_school`).
        Outside a section of schools, a listing that names a saint, a devotion
        or a church's faith and nothing of a school (``"St. Peter's"``,
        ``"Christ the King"``, ``"Visitation"``) is its church as much as its
        school, and an accepted school goes to the queue (:attr:`Reason.PARISH`).
        """
        section = listing_section(category)
        clean = clean_listing(listing_name)
        if section is Section.OTHER and not names_a_school(clean):
            if result.reason in _NOT_A_SCHOOL:
                return result
            return replace(
                result,
                target=None,
                confidence=0.0,
                reason=Reason.NOT_SCHOOL,
                detail=f"filed under {category!r}, not among schools",
            )
        target = result.target
        if section is Section.SCHOOLS or target is None or target.kind != "school":
            return result
        said = church_name(clean)
        if said is None:
            return result
        return replace(
            result,
            target=None,
            confidence=self._short_of(result.confidence),
            reason=Reason.PARISH,
            detail=(
                f"says {said!r} and nothing of a school: a parish's church as much as "
                f"{target.name!r}"
            ),
        )

    def _in_other_state(self, plain: MatchResult, foreign: Sequence[StateMention]) -> MatchResult:
        """A listing that names only a state the market does not cover: no record of the market.

        Unless the record it names has the state in its own name.
        """
        target = plain.target
        if plain.reason in _NOT_A_SCHOOL or (
            target is not None and any(spelled_in(target.name, mention) for mention in foreign)
        ):
            return plain
        states = ", ".join(sorted({mention.state for mention in foreign}))
        return replace(
            plain,
            target=None,
            confidence=0.0,
            reason=Reason.OTHER_STATE,
            detail=f"names {states}, which the market does not cover",
        )

    def _blank(
        self,
        listing_name: str,
        text: str,
        market: str | None,
        states: frozenset[str],
        counties: frozenset[str] | None,
    ) -> MatchResult:
        """A result for ``listing_name`` read as ``text`` in ``states`` that matches nothing yet."""
        clean = clean_listing(text)
        forms = listing_forms(clean.text, district_hint=clean.all_schools)
        return MatchResult(
            listing=listing_name,
            market=market,
            states=tuple(sorted(states)),
            counties=tuple(sorted(counties)) if counties is not None else None,
            level=forms.hint,
            target=None,
            confidence=0.0,
            reason=Reason.EMPTY,
            detail="nothing names a school or district once the noise is removed",
            best=None,
            runners_up=(),
        )

    def _listing(  # noqa: PLR0913, PLR0917 - the listing, how to read it, and where
        self,
        listing_name: str,
        text: str,
        market: str | None,
        states: frozenset[str],
        counties: frozenset[str] | None,
        point: tuple[float, float] | None,
        *,
        section: Section = Section.UNKNOWN,
        home: frozenset[str] | None = None,
    ) -> MatchResult:
        """Match ``listing_name``, read as ``text``, in ``states`` and ``counties``.

        ``section``: what the list's section says its listings are. Among schools,
        a government's name (``"Township of Union"``) is the school district's
        that bears it; elsewhere, or with no section, it is the government
        (:func:`~snowlight.match.normalize.not_school`).
        """
        result = self._blank(listing_name, text, market, states, counties)
        clean = clean_listing(text)
        forms = listing_forms(clean.text, district_hint=clean.all_schools)
        if forms.is_empty:
            return result
        scope = Scope(states, counties, entity=clean.entity, home=home)
        outcome = self._read(clean.text, forms, scope, point)
        read_as = clean.text
        academy = None if outcome.accepted else without_charter_school(clean.text)
        if academy is not None:
            # "Memphis Merit Academy Charter School" for NCES's "Memphis Merit Academy".
            read = self._read(academy, listing_forms(academy), scope, point)
            if read.accepted:
                outcome, read_as = read, academy
        outcome = self._kind_only(outcome, read_as)
        if clean.business is not None:
            outcome = self._as_company(clean.business, outcome, forms, point, home=scope.market)
        institution = non_k12(clean)
        if institution is not None and not self._names_a_town(clean, outcome.ranked):
            # The candidates stay, for the unmatched queue.
            outcome = replace(
                outcome,
                confidence=0.0,
                reason=Reason.NOT_K12,
                detail=f"names a {institution}, not a K-12 school",
            )
            return self._result(result, outcome, point)
        civic = not_school(clean)
        if civic is not None and not (
            (civic.may_be_a_place and self._names_a_town(clean, outcome.ranked))
            or (civic.business and self._names_its_business(civic.what, outcome))
            or (civic.parish and self._names_a_parish(outcome))
            or (civic.government and section is Section.SCHOOLS)
        ):
            # A city hall or a senior center is not its town's district; the
            # candidates stay, for the unmatched queue.
            outcome = replace(
                outcome,
                confidence=0.0,
                reason=Reason.NOT_SCHOOL,
                detail=f"says {civic.what!r}: a {civic.kind}, not a school",
            )
            return self._result(result, outcome, point)
        if (
            not outcome.accepted
            and len(clean.segments) > 1
            and not self._named_whole(outcome, forms)
        ):
            best_context = max(
                itertools.chain(
                    self._with_brackets(clean, scope, point),
                    self._with_context(clean, scope, point),
                    self._code_with_places(clean, scope, point),
                ),
                key=lambda o: o.confidence,
                default=None,
            )
            if best_context is not None and best_context.accepted:
                outcome = best_context
        return self._result(result, outcome, point)

    def _kind_only(self, outcome: _Outcome, text: str) -> _Outcome:
        """``outcome``, not accepted when ``text`` names only a kind of school that is not its name.

        A listing of nothing but words that say what kind of school or program a
        name is (:data:`~snowlight.match.lexicon.KIND_ONLY_WORDS`: ``"Christian
        Academy"``, ``"Learning Center"``, ``"Day Care"``, ``"Community School"``)
        names only a school whose name it is, word for word and in order, with
        the same levels and numbers: ``"The Christian Academy"`` and ``"The
        Learning Center"``, never ``"The Academy Christian School"``, ``"Center
        for Learning, Inc."``, ``"High School in the Community"`` or
        ``"Montessori Elementary School"``. Any other reading goes to the
        unmatched queue with its candidates.
        """
        winner = outcome.winner
        if winner is None or not outcome.accepted:
            return outcome
        forms = listing_forms(text)
        if not self._names_only_a_kind(forms) or self._named_word_for_word(
            text, forms, winner.index
        ):
            return outcome
        name = self.index.records[winner.index].name
        return replace(
            outcome,
            confidence=min(outcome.confidence, self.settings.threshold - _BELOW),
            reason=Reason.WEAK,
            detail=f"names only a kind of school, and {name!r} is not its name word for word",
            joint=(),
        )

    @staticmethod
    def _names_only_a_kind(forms: ListingForms) -> bool:
        """True when a listing's words say only what kind of school it is (:meth:`_kind_only`)."""
        form = forms.school
        return (
            bool(form.token_set)
            and form.token_set <= _KIND_ONLY
            and not (form.numbers or form.codes or form.qualifiers)
        )

    def _named_word_for_word(self, text: str, forms: ListingForms, index: int) -> bool:
        """True when record ``index``'s name is ``text``'s, word for word and in order.

        Its words as spelled, bar the words that link them (``"The Learning
        Center"`` is ``"Learning Center"``), and its levels
        (:func:`~snowlight.match.index.levels_said`) and numbers.
        """
        district = self.index.is_district[index]
        form = forms.district if district else forms.school
        other = self.index.forms[index]
        if not levels_said(form.levels, other) or form.numbers != other.numbers:
            return False
        said = tuple(w for w in spelled_name(text, district=district).words if w not in _LINKING)
        return said == tuple(w for w in self.index.spelled(index) if w not in _LINKING)

    def _named_whole(self, outcome: _Outcome, forms: ListingForms) -> bool:
        """True when ``outcome``'s best school is named by the whole listing, word for word.

        Such a listing is not read in parts: ``"District 287 - ALC - IS"`` is the
        name of one program of Minnesota's ``"Intermediate School District
        287"``, not the district (``"District 287"``) beside a place called
        ``"ALC"``. When the school is not taken (its name scores low, or a rival
        is as close), the listing goes to the queue. Two schools that both say
        the listing (``"GORDON-RUSHVILLE ELEM-GORDON"`` and ``"GORDON-RUSHVILLE
        ELE-RUSHVILLE"``, whose towns are no name words) are told apart by its
        parts.
        """
        winner = outcome.winner
        if winner is None or self.index.is_district[winner.index]:
            return False
        named = [
            s.index
            for s in outcome.ranked[: self.settings.runners_up + 1]
            if not self.index.is_district[s.index]
            and self.index.says_exactly(forms.school, s.index)
        ]
        return named == [winner.index]

    def _in_named_state(  # noqa: PLR0913 - the reading, the states named, and where
        self,
        plain: MatchResult,
        mentions: Sequence[StateMention],
        market: str | None,
        counties: frozenset[str] | None,
        point: tuple[float, float] | None,
        *,
        section: Section = Section.UNKNOWN,
        home: frozenset[str] | None = None,
    ) -> MatchResult:
        """Read a listing that names a state in that state alone.

        A state beside the name is left out: ``"Salem MA Public"`` on a list for
        Massachusetts and New Hampshire is ``"Salem Public"`` in Massachusetts,
        ``"Knox County, TN Schools"`` is ``"Knox County Schools"`` in Tennessee,
        and ``"Holden R-III School Holden MO"`` is ``"Holden R-III School"``
        beside the town of Holden, in Missouri. A state that is part of the name
        is spelled the other way: ``"Western PA School for the Deaf"`` is
        ``"Western Pennsylvania School for the Deaf"`` in Pennsylvania (see
        :func:`~snowlight.match.states.state_mentions`).

        A listing the whole of which names a record stays so, unless the record
        lies outside every state the listing names firmly beside its name
        (:attr:`~snowlight.match.states.StateMention.firm`): then the listing
        names that state's record, or none.
        """
        target = plain.target
        if target is not None:
            named = {mention.state for mention in mentions if mention.beside}
            firm = [mention for mention in mentions if mention.firm]
            if (
                target.state in named
                or not firm
                or any(spelled_in(target.name, mention) for mention in firm)
            ):
                return plain
        readings: list[MatchResult] = []
        for mention in mentions:
            state = frozenset({mention.state})
            for text in mention.texts:
                reading = self._listing(
                    plain.listing, text, market, state, counties, point, section=section, home=home
                )
                readings.append(reading)
                if reading.accepted:
                    break
        accepted = [reading for reading in readings if reading.accepted]
        if accepted:
            best = max(accepted, key=lambda reading: reading.confidence)
            return replace(
                best,
                reason=Reason.CAMPUS if best.reason is Reason.CAMPUS else Reason.CONTEXT,
                detail=f"{best.detail}; in {best.states[0]}, the state the listing names",
            )
        best = max(readings, key=lambda reading: reading.confidence)
        if plain.target is None and (
            plain.reason in _NOT_A_SCHOOL or plain.confidence >= best.confidence
        ):
            return plain
        states = ", ".join(sorted({reading.states[0] for reading in readings}))
        return replace(best, detail=f"{best.detail}; read in {states}, as the listing names it")

    # -- decisions -------------------------------------------------------------

    def _read(
        self, text: str, forms: ListingForms, scope: Scope, point: tuple[float, float] | None
    ) -> _Outcome:
        """Search ``scope`` for one name and decide, reading a place's name as its district.

        A listing that is only a place's name (:meth:`_place`) names that place's
        school system, never one school. A school of the place it fits stands
        for its own district when that district is a candidate too (``"Napa
        High"`` for ``"Napa Valley Unified"``); any other school ranks lower
        (:meth:`_as_place`) and is never accepted: with no district of the
        place among the candidates, the listing goes to the unmatched queue
        (:attr:`Reason.PLACE`).

        A district that runs schools beyond the market's counties is read as
        its schools in the market (:meth:`_within_market`).
        """
        scored = self.index.search(forms, scope)
        # Beside its city or its district ("Lincoln - Springfield"), a name is
        # what lies there, not the place.
        placed = scope.city is not None or scope.allowed is not None
        place = None if placed else self._place(text, forms, scored, scope, point)
        if place is None:
            decided = self._decide(scored, point, forms, home=scope.market)
            return self._within_market(decided, forms, scope, point)
        if forms.hint is Level.DISTRICT:
            # "Napa - All Schools": the schools named for the town still speak
            # for its district, as they do without the noise.
            forms = listing_forms(text)
            scored = self.index.search(forms, scope)
        placed_scores = self._as_place(scored, place, forms)
        outcome = self._decide(placed_scores, point, forms, home=scope.market)
        winner = outcome.winner
        if winner is None or self.index.is_district[winner.index]:
            return self._within_market(outcome, forms, scope, point)
        name = self.index.records[winner.index].name
        return replace(
            outcome,
            confidence=0.0,
            reason=Reason.PLACE,
            detail=f"names only a place, whose district is no candidate; {name!r} is one school",
        )

    def _place(
        self,
        text: str,
        forms: ListingForms,
        scored: Sequence[Scored],
        scope: Scope,
        point: tuple[float, float] | None,
    ) -> _Place | None:
        """How ``text`` names a place, or ``None`` when it is not only a place's name.

        It holds no designator, number, affiliation or code (``"Napa"``,
        ``"Kansas City"``), and the directory shows the place: a record in one
        of ``scope``'s states lies in a town of that name, spelled as the
        listing spells it (:meth:`NameIndex.towns`; ``"Oak Hills"`` is no town
        ``"Oak Hill"``), or a district among the candidates is named by the
        listing's words and its kind (``"Coffee County"`` for ``"Coffee"``). A
        level or a school noun in a town's own name (``"Byron Center"``,
        ``"High Point"``) still names the town; elsewhere it names a school. A
        bare name that is no place (``"Hollis Frost"``, ``"Gloria Deo"``) may be
        one school's.

        A town anywhere in the states makes the listing a place's name, so no
        one school is taken for it: a source's counties may leave out a town it
        lists (``"Jackson"`` on a list whose counties hold only a ``"Jackson
        School"`` named for someone). But only the towns within the listing's
        reach say whose district it is (:attr:`_Place.towns`, :meth:`_in_reach`):
        ``"Edgewood"`` on a San Antonio list is San Antonio's ``"Edgewood ISD"``,
        not the district of the town of Edgewood 440 km away. A place known only
        by a district's name is one only within reach of the listing's point
        (:meth:`_district_in_reach`).
        """
        form = forms.district
        if (
            form.affiliations
            or form.codes
            or form.system
            or form.public_school
            or form.school_of
            or not is_bare_name(text)
        ):
            return None
        index = self.index
        towns = index.towns(place_keys(text), scope.states)
        if towns:
            local = {
                key: town.districts
                for key, town in towns.items()
                if self._in_reach(town, scope, point)
            }
            districts = frozenset(d for found in local.values() for d in found)
            return _Place(MappingProxyType(local), districts)
        if forms.hint is Level.SCHOOL or form.levels or form.names_kind:
            return None
        # The listing's own words, legal-form words and all: "Del Norte Community"
        # is a school's name, not the district "Del Norte County Unified". A
        # district's second name counts ("North Rockland").
        words = forms.school.token_set
        if any(
            index.is_district[s.index]
            and words in index.word_sets(s.index)
            and self._district_in_reach(s.index, scope, point)
            for s in scored
        ):
            return _Place(_NO_TOWNS, _EMPTY_INDICES, town=False)
        return None

    def _district_in_reach(
        self, index: int, scope: Scope, point: tuple[float, float] | None
    ) -> bool:
        """True when a listing searched in ``scope`` from ``point`` may name district ``index``.

        With only a point, the district's office or one of its schools lies
        within :attr:`MatchSettings.reach_km` of it: ``"Wolf Creek"`` on a
        Kenton list is no place known by the name of the ``"Wolf Creek Local"``
        district 200 km away. With counties, the district is a candidate only
        when it touches them; with neither, anywhere in the states.
        """
        if scope.counties is not None or point is None:
            return True
        records = self.index.records
        places = (records[index].point, *(records[i].point for i in self.index.schools_of(index)))
        reach = self.settings.reach_km
        return any(where is not None and haversine_km(point, where) <= reach for where in places)

    def _in_reach(self, town: Town, scope: Scope, point: tuple[float, float] | None) -> bool:
        """True when a listing searched in ``scope`` from ``point`` may name ``town``.

        With counties given, a town that lies in one of them; with only a
        point, a town within :attr:`MatchSettings.reach_km` of it; with neither,
        any town in the states.
        """
        if scope.counties is not None:
            return not town.counties.isdisjoint(scope.counties)
        if point is not None:
            return town.within(point, self.settings.reach_km)
        return True

    def _as_place(
        self, scored: Sequence[Scored], place: _Place, forms: ListingForms
    ) -> list[Scored]:
        """``scored`` read for a place's name: its schools stand for their districts.

        A school whose district is a candidate leaves the list, and when it lies
        in the town the listing names, that district takes its score if it is
        the higher: ``"Napa High"`` fits ``"Napa"`` better than ``"Napa Valley
        Unified"`` does, and is Napa's high school, so ``"Napa"`` names its
        district. So does a school of the town's one district wherever its
        address is (``"Old Bridge High School"``, in Matawan, for ``"Old Bridge
        Township School District"``, which runs every public school in Old
        Bridge), and any school of a place known only by a district's name
        (``"Coffee Middle School"`` for ``"Coffee County"``). ``"Peoria Regional
        High School"`` in West Peoria does not speak for the regional office in
        Peoria, one of that town's many districts.

        Every other school ranks at :data:`PLACE_SCHOOL` of its score and
        plausibility, save two kinds that stay as close rivals as their names
        make them, though never accepted: a public school in a town of that name
        whose own districts fit the listing no better than it does, since the
        town's district cannot then be told (``"Westside Junior-Senior High
        School"`` in Westside, Iowa, for ``"Westside"`` in a market that also
        holds ``"Westside Community Schools"`` of Omaha), and a school whose name
        is a saint's or a devotion's (``"St. Mary's School"`` is named for the
        saint, not the town of St. Marys).

        A district ranks as low when the town has districts of its own and it
        is none of them (:attr:`_Place.districts`): ``"Neptune"`` is the
        township's district, not ``"Neptune City School District"`` next door,
        and ``"Richmond"`` not a ``"Richmond Elementary"`` district that lies in
        another county. Never one whose name is the listing's, word for word
        (:meth:`_names_exactly`): ``"Kentwood"`` is ``"Kentwood Public
        Schools"``, and ``"Socorro"`` ``"Socorro ISD"``, whatever districts run
        the schools whose addresses say the town. A district of one school
        named as that school ranks as low for a town's name wherever it is:
        ``"Youngstown"`` is ``"Youngstown City"``, never the charter school's
        own ``"Youngstown Community School"`` (but ``"Warren County
        Vocational"``, no town, is the district ``"Warren County Vocational
        School"``, and ``"Mattawan"`` the five schools of ``"Mattawan
        Consolidated School"``). One of
        the town's own named for its township is as close a rival as its name
        would be with ``Township`` said: a town's name may mean its township
        (``"Burlington"`` for ``"Burlington Township School District"`` as well
        as ``"Burlington City"``).
        """
        index = self.index
        districts = {s.index for s in scored if index.is_district[s.index]}
        # A town all of whose public schools one district runs: that district's
        # schools speak for it wherever their addresses are.
        sole = next(iter(place.districts)) if len(place.districts) == 1 else None
        standing: dict[int, Scored] = {}
        others: list[tuple[Scored, bool]] = []
        for s in scored:
            if index.is_district[s.index]:
                continue
            owner = index.owner_of(s.index)
            town = self._town_of(s.index)
            here = town in place.towns
            if owner is not None and owner in districts:
                best = standing.get(owner)
                speaks = here or not place.towns or owner == sole
                if speaks and (best is None or s.score > best.score):
                    standing[owner] = s
                continue
            others.append((s, owner is not None and here))
        read = [
            self._as_town_district(s, standing, place, forms)
            for s in scored
            if s.index in districts
        ]
        # How well a district of each town fits: a public school there of
        # another district is no rival to one that fits as well ("Falls Church
        # High", of the county's district, for "Falls Church City Public
        # Schools"), but is to one that fits worse (a charter school's own
        # district named "Kessel Academy" in Kessel).
        fits: dict[tuple[str, str], float] = {}
        for district in read:
            for town, own in place.towns.items():
                if district.index in own:
                    fits[town] = max(fits.get(town, 0.0), district.score)
        for s, public_here in others:
            town = self._town_of(s.index)
            rival = public_here and fits.get((town[0], town[1] or ""), 0.0) < s.score
            read.append(s if rival or index.forms[s.index].devoted else _ranked_down(s))
        read.sort(key=lambda s: (-s.score, s.index))
        return read

    def _as_town_district(
        self, district: Scored, standing: dict[int, Scored], place: _Place, forms: ListingForms
    ) -> Scored:
        """A district candidate read for a place's name: see :meth:`_as_place`."""
        score, plausibility = district.score, district.plausibility
        local = place.districts
        township = self._named_for_its_township(forms, district.index)
        if township and (district.index in local or place.town):
            # The town's township is the town as much as its city is:
            # "Burlington" may be "Burlington Township" or "Burlington City".
            # And a township is a place of its name wherever its district's
            # office is: "Union" is Hunterdon County's "Union Township School
            # District", in Hampton, as much as Union's own district.
            plausibility = min(1.0, plausibility / COUNTY_LEFT_OUT)
        school = standing.get(district.index)
        if school is not None:
            score = max(score, school.score)
            plausibility = max(plausibility, school.plausibility)
        one_school = place.town and self._one_school(district.index)
        if one_school or (
            local
            and district.index not in local
            and not self._names_exactly(forms, district.index)
            and not township
        ):
            # A charter school's own district ("Youngstown Community School") is
            # one school, which a town's name never names.
            score *= PLACE_SCHOOL
            plausibility *= PLACE_SCHOOL
        return Scored(district.index, score, plausibility)

    def _named_for_its_township(self, forms: ListingForms, index: int) -> bool:
        """True when district ``index`` is named as the listing's place, and ``Township``.

        ``"Union Township School District"`` and ``"Township of Union School
        District"`` for ``"Union"``: the name says the listing's words and levels,
        and of the place's kind only ``Township``, which the listing leaves out.
        """
        said = forms.district.qualifiers
        form = self.index.forms[index]
        return (
            _TOWNSHIP not in said
            and form.qualifiers - said == {_TOWNSHIP}
            and self.index.says_exactly(forms.district, index, forgive=True)
        )

    def _names_exactly(self, forms: ListingForms, index: int) -> bool:
        """True when district ``index``'s name is the listing's, word for word.

        :meth:`~snowlight.match.index.NameIndex.says_exactly`, but a district of
        one school named as it (``"Youngstown Community School"``, whose legal
        form leaves ``Youngstown``) is only the name of a listing that says
        ``School`` too.
        """
        if self._one_school(index) and not forms.district.one_school:
            return False
        return self.index.says_exactly(forms.district, index)

    def _one_school(self, index: int) -> bool:
        """True when district ``index`` runs one school and is named as that school."""
        return self.index.forms[index].one_school and len(self.index.schools_of(index)) <= 1

    def _within_market(
        self,
        outcome: _Outcome,
        forms: ListingForms,
        scope: Scope,
        point: tuple[float, float] | None,
    ) -> _Outcome:
        """An accepted district read for a market that holds only part of it.

        With counties given, a district is taken whole only when the market may
        speak for all its schools (:meth:`~snowlight.match.index.Reach.whole`):
        one that straddles the market's edge, its schools near one another, is.
        One whose name is a single school's and that runs campuses outside the
        counties (``"Premier High Schools"``, ``"Arrow Academy"``), or whose
        schools lie far beyond them (``"IDEA Public Schools"``), is not: the
        listing names its campus in the market. That is the one campus in the
        counties the listing fits (:meth:`~snowlight.match.index.NameIndex.campuses`,
        :attr:`Reason.CAMPUS`); among several, none, however much nearer
        ``point`` one of them lies: they are all the market's, and the listing
        goes to the queue as ambiguous with the campuses first. Only a campus
        past the listing's own counties, read again with those around them
        (:meth:`_past_counties`), may lose to one in them much nearer ``point``
        (:attr:`Reason.NEAREST`, :meth:`_break_tie`). With no campus there that
        fits, it goes as :attr:`Reason.NETWORK`.

        The one campus that fits is the listing's when it is the district's only
        school in the market, or when its name says no more than the listing but
        its town (``"Premier H S of Tyler"`` for ``"Premier High School"``). One
        that says a level or a name more, beside other schools of the district
        in the market (``"Minnesota Transitions Charter Elem"`` beside ``"MTS
        High School"``, for the district's own name), is one of them, no more
        the listing's than the rest: the listing goes to the queue.
        """
        winner = outcome.winner
        counties = scope.counties
        index = self.index
        if (
            counties is None
            or winner is None
            or not outcome.accepted
            or not index.is_district[winner.index]
        ):
            return outcome
        settings = self.settings
        reach = index.reach(winner.index, counties, reach_km=settings.reach_km)
        if reach.whole(settings.stray_share):
            return outcome
        district = index.records[winner.index].name
        how = (
            "is named as one school"
            if reach.school_named and reach.schools > 1
            else f"has {len(reach.beyond)} of its {reach.schools} schools beyond "
            f"{settings.reach_km:.0f} km of the market"
        )
        why = f"{district!r} {how}, {len(reach.inside)} in the counties"
        campuses = index.campuses(forms, reach.inside, scope.states)
        fitting = sorted((s for s, fits in campuses if fits), key=lambda s: (-s.score, s.index))
        others = sorted((s for s, fits in campuses if not fits), key=lambda s: (-s.score, s.index))
        seen = {winner.index, *reach.inside}
        rest = [s for s in outcome.ranked if s.index not in seen]
        distances = {**outcome.distances, **self._distances([s for s, _ in campuses], point)}
        lone = fitting[0] if len(fitting) == 1 else None
        if lone is not None and (
            len(reach.inside) == 1 or not index.says_beyond(forms.school, lone.index)
        ):
            campus = lone
            name = index.records[campus.index].name
            return _Outcome(
                campus,
                outcome.confidence,
                Reason.CAMPUS,
                f"{why}; {name!r} is the one there the listing fits",
                (campus, winner, *others, *rest),
                distances,
            )
        tie = (
            self._break_tie(fitting, distances, home=scope.market, what="campuses the listing fits")
            if point is not None and len(fitting) > 1
            else None
        )
        if tie is not None:
            ranked = (tie.winner, *(s for s in fitting if s is not tie.winner), winner)
            return _Outcome(
                tie.winner,
                outcome.confidence,
                Reason.NEAREST,
                f"{why}; {tie.note}",
                (*ranked, *others, *rest),
                distances,
            )
        if fitting:
            names = ", ".join(repr(index.records[s.index].name) for s in fitting[:3])
            said = (
                f"{names} fits the listing and says more, beside "
                f"{len(reach.inside) - 1} other schools of it there"
                if lone is not None
                else f"{len(fitting)} there fit the listing: {names}"
            )
            return _Outcome(
                fitting[0],
                self._short_of(outcome.confidence),
                Reason.AMBIGUOUS,
                f"{why}; {said}",
                (*fitting, winner, *others, *rest),
                distances,
            )
        return _Outcome(
            winner,
            0.0,
            Reason.NETWORK,
            f"{why}; none there fits the listing",
            (winner, *others, *rest),
            distances,
        )

    def _short_of(self, confidence: float) -> float:
        """The confidence of a name that ties with another: an exact tie's, under the threshold."""
        settings = self.settings
        tied = confidence - settings.margin * settings.margin_slope
        return max(0.0, min(tied, settings.threshold - _BELOW))

    def _town_of(self, index: int) -> tuple[str, str | None]:
        """The state and :meth:`~snowlight.match.index.NameIndex.place_of` of a record."""
        return (self.index.records[index].state, self.index.place_of(index))

    def _alias(
        self, result: MatchResult, pinned: Sequence[str], point: tuple[float, float] | None
    ) -> MatchResult:
        """``result`` pinned in ``aliases.yaml`` to the records ``pinned``, every one of them.

        A pin to an id the directory does not hold (a record NCES dropped) is
        not taken at all, not even for the ids it does hold: the pin was checked
        as a whole.
        """
        records = [self.directory.get(record_id) for record_id in pinned]
        missing = [
            record_id for record_id, record in zip(pinned, records, strict=True) if record is None
        ]
        if missing:
            return replace(
                result,
                reason=Reason.ALIAS_UNKNOWN,
                detail=f"pinned to {', '.join(missing)}, not in the directory",
            )
        found = tuple(record for record in records if record is not None)
        first = found[0]
        how = f" to {len(found)} records" if len(found) > 1 else ""
        return replace(
            result,
            target=first,
            targets=found,
            confidence=1.0,
            reason=Reason.ALIAS,
            detail=f"pinned in aliases.yaml for market {result.market}{how}",
            best=Candidate(first, 1.0, self._distance(first, point)),
        )

    def _names_a_parish(self, outcome: _Outcome) -> bool:
        """True when a listing that says ``Parish`` names a Louisiana parish's district.

        ``"Acadia Parish"`` is the district of that parish, accepted by its name;
        ``"Christ the King Parish"`` finds no district of that name, only the
        parish's school, and is its church.
        """
        winner = outcome.winner
        if winner is None or not outcome.accepted or not self.index.is_district[winner.index]:
            return False
        return lexicon.PARISH in self.index.forms[winner.index].qualifiers

    def _names_a_town(self, clean: CleanListing, ranked: Sequence[Scored]) -> bool:
        """True when the whole listing is the name of a candidate's town.

        ``"State College"`` is a town in Pennsylvania, whose district is ``"State
        College Area SD"``, and ``"Falls Church"`` (or ``"Falls Church City"``) a
        city in Virginia: a college or civic word in the name of a place the
        directory holds names that place, as in ``"College Park"``. The listing
        must be the town's name and nothing more: ``"Roselle Park District"`` is
        a park district, not the town of Roselle Park (:func:`is_bare_name`).
        """
        if not is_bare_name(clean.text):
            return False
        places = place_keys(clean.text)
        return any(
            self.index.place_of(s.index) in places for s in ranked[: self.settings.runners_up + 1]
        )

    def _carries(self, word: str, index: int) -> bool:
        """True when record ``index``'s own NCES name carries the business form ``word``."""
        return clean_listing(self.index.records[index].name).business == word

    def _as_company(
        self,
        word: str,
        outcome: _Outcome,
        forms: ListingForms,
        point: tuple[float, float] | None,
        *,
        home: frozenset[str] | None,
    ) -> _Outcome:
        """An accepted listing that says a business form (``Inc.``) read as the company it names.

        ``"Intelli-School Inc."`` is, word for word, the charter holder
        ``"Intelli-School Inc."``, not another holder's school named
        ``"Intelli-School"``: when a candidate within the margin of the one
        accepted carries the listing's business form in its own name and the
        one accepted does not, the listing is read among those that carry it
        alone, and names one of them or goes to the queue.
        """
        winner = outcome.winner
        if winner is None or not outcome.accepted or self._carries(word, winner.index):
            return outcome
        floor = winner.score - self.settings.margin
        companies = [
            s for s in outcome.ranked if s.plausibility >= floor and self._carries(word, s.index)
        ]
        if not companies:
            return outcome
        read = self._decide(companies, point, forms, home=home)
        if read.winner is None:  # pragma: no cover - companies is never empty here
            return outcome
        return replace(
            read,
            confidence=read.confidence if read.accepted else self._short_of(read.confidence),
            reason=read.reason if read.accepted else Reason.AMBIGUOUS,
            detail=f"the listing says {word!r}, as only these names do; {read.detail}",
            ranked=(*read.ranked, *(s for s in outcome.ranked if s not in read.ranked)),
        )

    def _names_its_business(self, word: str, outcome: _Outcome) -> bool:
        """True when the accepted record's own NCES name carries the business form ``word``.

        Arizona's charter holders are districts named as companies (``"Friendly
        House Inc."``, ``"Ridgeline Academy, Inc."``): a listing that gives that
        name, ``Inc.`` and all, names that district, not a business, or one of
        several holders of that very name (``"Horizon Community Learning Center
        Inc."``), which the name cannot tell apart: the best candidate need not
        be accepted, only close enough by name.
        """
        winner = outcome.winner
        if winner is None or winner.score < self.settings.threshold:
            return False
        return self._carries(word, winner.index)

    def _distance(self, record: DirectoryRecord, point: tuple[float, float] | None) -> float | None:
        if point is None:
            return None
        where = record.point
        if where is None and record.kind == "district":
            schools = [s.point for s in self.directory.schools_of(record.id) if s.point]
            if schools:
                where = (
                    sum(p[0] for p in schools) / len(schools),
                    sum(p[1] for p in schools) / len(schools),
                )
        return None if where is None else haversine_km(point, where)

    def _covered(self, winner: Scored, other: Scored) -> bool:
        """True when ``winner`` and ``other`` are a district and one of its own schools.

        They do not compete. A district covers its schools; and a school is the
        narrower reading of its own district (a charter district that runs one
        school carries the school's name), so taking the school never marks a
        school the listing did not name.
        """
        one = self.index.records[winner.index]
        two = self.index.records[other.index]
        if one.kind == "district":
            return two.district_id == one.id
        return two.kind == "district" and one.district_id == two.id

    def _distances(
        self, candidates: list[Scored], point: tuple[float, float] | None
    ) -> dict[int, float]:
        distances: dict[int, float] = {}
        if point is None:
            return distances
        for s in candidates:
            if s.index not in distances:
                distance = self._distance(self.index.records[s.index], point)
                if distance is not None:
                    distances[s.index] = distance
        return distances

    def _break_tie(
        self,
        tied: list[Scored],
        distances: dict[int, float],
        *,
        home: frozenset[str] | None,
        what: str = "tied names",
        known: bool = False,
    ) -> _Tie | None:
        """The tied candidate much nearer than the rest, when a point may tell them apart.

        A market's point says which of several names a listing means only when
        the rest lie outside the market: with the listing's counties (``home``),
        every other tied candidate lies outside them (a district: touches none
        of them, :meth:`~snowlight.match.index.NameIndex.in_counties`); with
        none, every other lies farther than :attr:`MatchSettings.reach_km` from
        the point, as the directory places it. Two ``"St. John School"`` in a
        Boston list's counties, one 1 km from the station and one 17 km, are
        both the market's: the station's place says nothing of which one the
        list means, and the listing goes to the queue. And the nearest must be
        much nearer than the next (:attr:`MatchSettings.near_ratio`,
        :attr:`MatchSettings.near_slack_km`) and within
        :attr:`MatchSettings.near_max_km`.

        ``known``: every tied candidate's distance must be known; one whose
        place the directory does not give is not taken to be far away. Names
        that tie across states are told apart by distance alone
        (:meth:`_undecided_across`), so a place unknown leaves them tied.
        """
        settings = self.settings
        if known and any(s.index not in distances for s in tied):
            return None
        nearest, *rest = sorted(
            tied, key=lambda s: (distances.get(s.index, math.inf), -s.score, s.index)
        )
        first = distances.get(nearest.index)
        second = distances.get(rest[0].index, math.inf)
        if (
            first is None
            or first > settings.near_max_km
            or second < settings.near_ratio * first + settings.near_slack_km
            or not all(self._outside_market(s, distances, home) for s in rest)
        ):
            return None
        shown = "farther" if math.isinf(second) else f"{second:.0f} km"
        where = (
            "the rest outside the counties"
            if home is not None
            else f"the rest beyond {settings.reach_km:.0f} km"
        )
        return _Tie(
            nearest,
            frozenset(s.index for s in tied),
            f"nearest of {len(tied)} {what} ({first:.0f} km against {shown}, {where})",
            Reason.NEAREST,
        )

    def _outside_market(
        self, candidate: Scored, distances: Mapping[int, float], home: frozenset[str] | None
    ) -> bool:
        """True when ``candidate`` lies outside the listing's market: see :meth:`_break_tie`.

        Outside ``home``, the listing's counties, when it has any; otherwise
        farther than :attr:`MatchSettings.reach_km` from its point, which a
        candidate whose place the directory does not give is not.
        """
        if home is not None:
            return not self.index.in_counties(candidate.index, home)
        distance = distances.get(candidate.index)
        return distance is not None and distance > self.settings.reach_km

    def _namesakes_across(
        self, winner: Scored, scored: Sequence[Scored], forms: ListingForms
    ) -> list[Scored]:
        """The districts in other states than district ``winner``'s that bear its name.

        The same identifying words (or the same words run together), the same
        levels, and both a county's (or a parish's) district or neither, by any
        name each answers to; a number the listing gives, both carry. What else
        tells them apart is how each state writes its NCES names: a municipal
        word (Tennessee's ``"Bristol"``, Virginia's ``"Bristol City Public
        Schools"``), a legal form (Kentucky's ``"Covington Independent"``, Ohio's
        ``"Covington Exempted Village"``), a number the listing does not give
        (Missouri's ``"KANSAS CITY 33"``), a ``County`` one state's names imply
        (Florida's ``"ESCAMBIA"``, Alabama's ``"Escambia County"``). None of it
        says which state a listing means, however far apart it puts their
        scores: see :meth:`_undecided_across`. A county's district and a town's
        are two names (Kentucky's ``"Madison County"``, Indiana's ``"Madison
        Consolidated Schools"``): a list writes ``County`` for the first.

        Only those at least :data:`NAMESAKE_FLOOR` plausible, best first.
        """
        index = self.index
        if not index.is_district[winner.index]:
            return []
        state = index.records[winner.index].state
        numbers = forms.district.numbers
        keys = self._namesake_keys(winner.index)
        found: list[Scored] = []
        for s in scored:
            if (
                s.index == winner.index
                or not index.is_district[s.index]
                or index.records[s.index].state == state
                or s.plausibility < NAMESAKE_FLOOR
                or not numbers <= index.forms[s.index].numbers
                or not numbers <= index.forms[winner.index].numbers
            ):
                continue
            if keys & self._namesake_keys(s.index):
                found.append(s)
        found.sort(key=lambda s: (-s.plausibility, s.index))
        return found

    def _namesake_keys(self, index: int) -> frozenset[tuple[object, ...]]:
        """What district ``index``'s names say once each state's writing habits are set aside.

        See :meth:`_namesakes_across`: for every name the district answers to,
        its identifying words and, when it has one, the same words run
        together, each with its levels and whether it names a county's (or a
        parish's) district, said or implied.
        """
        keys: set[tuple[object, ...]] = set()
        for form in self.index.forms_of(index):
            county = not (form.qualifiers | form.implied).isdisjoint(
                lexicon.COUNTY_LEVEL_QUALIFIERS
            )
            keys.add((self.index.identifying(form.token_set), form.levels, county))
            if form.compact:
                keys.add((form.compact, form.levels, county))
        return frozenset(keys)

    def _nearest_of(
        self,
        winner: Scored,
        namesakes: Sequence[Scored],
        distances: dict[int, float],
        point: tuple[float, float] | None,
        *,
        home: frozenset[str] | None,
    ) -> bool:
        """True when ``winner`` is much nearer ``point`` than every one of its ``namesakes``.

        And they lie outside the listing's market (:meth:`_break_tie`).
        """
        if point is None:
            return False
        candidates = [winner, *namesakes]
        known = {**distances, **self._distances(candidates, point)}
        tie = self._break_tie(candidates, known, home=home, known=True)
        return tie is not None and tie.winner.index == winner.index

    def _across_states(self, candidates: Sequence[Scored]) -> bool:
        """True when ``candidates`` lie in more than one state."""
        records = self.index.records
        return len({records[s.index].state for s in candidates}) > 1

    def _undecided_across(
        self,
        best: Scored,
        tied: Sequence[Scored],
        scored: Sequence[Scored],
        distances: dict[int, float],
        point: tuple[float, float] | None,
    ) -> _Outcome:
        """Names that tie across states and that no point tells apart: the unmatched queue.

        Each state writes its NCES names its own way: Missouri numbers its
        districts (``"KANSAS CITY 33"``), Kansas writes a bare name (``"Kansas
        City"``), Virginia ``"Bristol City Public Schools"`` and Tennessee
        ``"Bristol"``. Between two states, which one's record says a listing's
        words exactly, or its legal form, or its spelling, says how the states
        write names, not which record the listing means: ``"Kansas City Public
        Schools"`` on a list for both states is Missouri's as likely as Kansas's.
        So none of the steps that tell districts of one state apart by their
        wording (:meth:`_legal_form_tie`, :meth:`_exact_tie`) decides between
        states; only a point much nearer one of them does (:meth:`_break_tie`),
        or a state the listing names (:func:`~snowlight.match.states.state_mentions`).
        Otherwise the listing goes to the queue with the tied names first, for
        an alias to pin.
        """
        records = self.index.records
        chosen = records[best.index]
        other = next(s for s in tied if records[s.index].state != chosen.state)
        rival = records[other.index]
        first = [best, other, *(s for s in tied if s.index not in {best.index, other.index})]
        seen = {s.index for s in first}
        ranked = (*first, *(s for s in scored if s.index not in seen))
        states = ", ".join(sorted({records[s.index].state for s in tied}))
        why = (
            "no point near the market tells them apart"
            if point is None
            else "the market's point is not much nearer one of them, the other outside the market"
        )
        return _Outcome(
            best,
            self._short_of(best.score),
            Reason.AMBIGUOUS,
            f"{chosen.name!r} ({chosen.state}) and {rival.name!r} ({rival.state}) tie by name "
            f"across {states}; {why}",
            ranked,
            distances,
        )

    def _rival(
        self, winner: Scored, scored: Sequence[Scored], set_aside: frozenset[int]
    ) -> Scored | None:
        """The most plausible candidate that competes with ``winner``, if any."""
        rival: Scored | None = None
        for s in scored:
            if s.index in set_aside or self._covered(winner, s):
                continue
            if rival is None or s.plausibility > rival.plausibility:
                rival = s
        return rival

    def _whole_district(
        self, winner: Scored, rival: Scored, scored: Sequence[Scored], forms: ListingForms
    ) -> Scored | None:
        """The district whose schools are every name as close as ``winner``, or ``None``.

        NCES splits some schools by level into records of one name (``"Great Bay
        Charter School (H)"`` and ``"Great Bay Charter School (M)"``), the
        schools of a district of that name. A listing that names the school
        without a level names all of them, so they do not compete: the listing
        names their district, when its words fit the district about as well
        and every one of the district's schools is as close as the best. Two
        schools that tie in a district with a school the listing does not name
        as well (``"Lincoln School"`` for Lincoln Elementary and Lincoln Middle
        beside Adams High) stay rivals: their district would mark a school the
        listing never named. So does a school whose name is the listing's, word
        for word, when its district's is not (:meth:`_says_district`):
        ``"Plainview-Elgin-Millville Junior"`` is that school, not its district
        ``"Plainview-Elgin-Millville"``, however close its
        ``"Plainview-Elgin-Millville High"`` comes; ``"Beta Academy"`` is the
        charter district of that name as much as its school.
        """
        records = self.index.records
        school = records[winner.index]
        owner = school.district_id
        if (
            school.kind != "school"
            or owner is None
            or records[rival.index].district_id != owner
            or records[rival.index].kind != "school"
        ):
            return None
        floor = winner.score - self.settings.margin
        position = self.index.index_of(owner)
        district = next((s for s in scored if s.index == position), None)
        if (
            district is None
            or district.score < floor
            or (
                self.index.says_exactly(forms.school, winner.index)
                and not self._says_district(forms, position)
            )
        ):
            return None
        close = {s.index for s in scored if s.plausibility >= floor}
        siblings = {self.index.index_of(s.id) for s in self.directory.schools_of(owner)}
        return district if siblings <= close else None

    def _exact_reading(
        self, winner: Scored, scored: Sequence[Scored], forms: ListingForms
    ) -> Scored | None:
        """The record that says exactly the listing, for a school of its district that says more.

        ``"Cumberland Academy"`` is, word for word, the name of a charter
        district of five schools. Its ``"Cumberland Academy Middle"`` says all of
        the listing's words and a level more, and scores higher, since a listing
        that says ``Academy`` reads as one school; but the listing no more names
        that school than the district's ``"Cumberland Academy Lower El"``: it
        names the district. So ``"University Academy"`` names the district
        ``"UNIVERSITY ACADEMY"``, not its ``"UNIVERSITY ACADEMY-MIDDLE"``, and
        ``"Paul PCS"`` the district, not ``"Paul PCS - MS"``. A school of the
        district whose own name is the listing's is the narrower reading and is
        the one taken (``"Kesselby Academy"``, a charter school named as its own
        district). So is the school of a district of one school, which is all
        the district is: ``"Peacham School"`` is ``"Peacham Elementary School"``,
        the one school of ``"Peacham School District"``.

        Returns that school or the district, or ``None`` when ``winner`` is not a
        school that says more than the listing, or its district is no candidate,
        runs no other school, or its name is not the listing's
        (:meth:`~snowlight.match.index.NameIndex.says_exactly`).
        """
        index = self.index
        if index.is_district[winner.index] or index.says_exactly(forms.school, winner.index):
            return None
        owner = index.owner_of(winner.index)
        district = next((s for s in scored if s.index == owner), None)
        if (
            owner is None
            or district is None
            or len(index.schools_of(owner)) == 1
            or not index.says_exactly(forms.district, owner)
        ):
            return None
        district_id = index.records[owner].id
        return next(
            (
                s
                for s in scored
                if index.records[s.index].district_id == district_id
                and not index.is_district[s.index]
                and index.says_exactly(forms.school, s.index)
            ),
            district,
        )

    def _school_reading(
        self, winner: Scored, scored: Sequence[Scored], forms: ListingForms
    ) -> Scored | None:
        """The school a listing that reads as one school names word for word, over its district.

        ``"Petaluma High"`` is the whole name of Petaluma's high school; the
        district that runs it and the town's other high schools, ``"Petaluma
        Joint Union High"``, reads the same once its legal form is set aside,
        and scores as well. The listing names the school: taking the district
        would mark the district's other schools too. Only a listing whose words
        say one school (:attr:`~snowlight.match.normalize.Level.SCHOOL`), and
        only a school of that district that scores as well. A district whose
        own name the listing says, legal form and all, stays the reading: a
        list names ``"Robla Elementary"`` and ``"Tolleson Union High"`` for the
        districts of those names, not for their ``"Robla Elementary School"``
        and ``"Tolleson Union High School"``.

        Whatever the listing's words say it is, a school of the district whose
        name is the listing's, word for word, is the reading when the district's
        name is not (:meth:`_says_district`): the listing says a word, a level
        or a legal form the district's name does not. ``"Cheatham Co Central"``
        is the county's Central High School, not the ``"Cheatham County"``
        district of 14 schools; ``"Selma Independent"`` the independent study
        school, not ``"Selma Unified"``; ``"Lakota Central"``, ``"Waterford
        Junior"`` and ``"CYPRESS-FAIRBANKS J J A E P"`` one school each. That
        school is taken however it scores: when a word of the listing marks it
        down (``Independent`` reads as a district's legal form), the listing
        goes to the queue, and the district is never taken for it. A district
        of one school is that school already (``"Craftsbury Schools"``).

        Returns that school, or ``None``.
        """
        index = self.index
        if not index.is_district[winner.index]:
            return None
        district_id = index.records[winner.index].id
        floor = -math.inf
        if len(index.schools_of(winner.index)) <= 1 or self._says_district(forms, winner.index):
            distinct = index.legal_words(winner.index) & lexicon.DISTINCT_LEGAL_WORDS
            if forms.hint is not Level.SCHOOL or distinct <= forms.legal:
                return None
            floor = winner.score - self.settings.tie
        return next(
            (
                s
                for s in scored
                if s.score >= floor
                and not index.is_district[s.index]
                and index.records[s.index].district_id == district_id
                and index.says_exactly(forms.school, s.index)
            ),
            None,
        )

    def _says_district(self, forms: ListingForms, index: int) -> bool:
        """True when district ``index``'s name says the listing's words and its legal form.

        Its words, levels, numbers and qualifiers
        (:meth:`~snowlight.match.index.NameIndex.says_exactly`), and every
        legal-form word the listing says but the generic ones
        (:data:`~snowlight.match.lexicon.GENERIC_LEGAL_WORDS`): ``"Cheatham
        County"`` says ``"Cheatham County Schools"`` but not ``"Cheatham Co
        Central"``, and ``"Selma Unified"`` not ``"Selma Independent"``. A list
        may leave out a legal-form word the district's name says (``"Mineral
        Wells Schools"`` for ``"MINERAL WELLS ISD"``).
        """
        said = forms.legal - lexicon.GENERIC_LEGAL_WORDS
        return said <= self.index.legal_words(index) and self.index.says_exactly(
            forms.district, index
        )

    def _bare_reading(
        self, winner: Scored, scored: Sequence[Scored], forms: ListingForms
    ) -> Scored | None:
        """The district a bare name names, for a school of it that adds a level.

        ``"Cicero-North Syracuse"`` is how a list names the district
        ``"NORTH SYRACUSE CENTRAL SCHOOL DISTRICT"``; its ``"CICERO-NORTH
        SYRACUSE HIGH SCHOOL"`` says all of the listing's words and a level
        more, and scores higher. A name that says no level, designator or noun
        is a school system's on a closings list as often as the one school's,
        so the school is not taken: the district is, when its own name fits
        well enough, and otherwise neither is, and the listing goes to the
        queue (see :meth:`_decide`). Only a district of more than one school,
        whose own name shares the listing's words.

        Returns the district, or ``None``.
        """
        index = self.index
        listing = forms.school
        if (
            forms.hint is not Level.UNKNOWN
            or listing.levels
            or listing.names_kind
            or index.is_district[winner.index]
            or not index.forms[winner.index].levels
        ):
            return None
        owner = index.owner_of(winner.index)
        district = next((s for s in scored if s.index == owner), None)
        if (
            owner is None
            or district is None
            or len(index.schools_of(owner)) == 1
            or not any(listing.token_set & words for words in index.word_sets(owner))
        ):
            return None
        return district

    def _legal_form_tie(self, tied: Sequence[Scored], forms: ListingForms) -> _Tie | None:
        """The one of several districts of one town that tie by name that the listing names.

        Names that differ only in their legal form reduce to the same words:
        ``"Detroit Public Schools Community District"`` and the charter district
        ``"Detroit Community Schools"`` are both ``detroit``, as are Michigan's
        ``"Jackson Public Schools"`` and its intermediate district ``"Jackson
        ISD"``. The legal-form words the listing says decide
        (:func:`~snowlight.match.normalize.legal_words`, the generic ones such
        as ``School`` and ``District`` aside): ``"Detroit Public Schools"`` names
        the one district whose name says ``Public``, ``"Detroit Community
        Schools"``, which both names say, the one whose legal form is no more
        than that. ``"Detroit Schools"`` says nothing that tells them apart.

        A listing that names a school system (``"Denver Public Schools"``) and
        whose legal form tells nothing apart names the one of them that runs
        several schools, not a district of one school that bears the town's
        name (``"DENVER 1"``, one program's), when their names say the same
        place qualifiers: ``"Capital City PCS"`` and ``"Capital Village PCS"``
        are two names.

        Only districts whose offices lie in one town of one county: the same
        name in two towns, or in two counties (two townships of one name), is
        two places, which distance, not wording, tells apart. And only names of
        the same words and levels: a town's elementary and high school
        districts (``"Julian Union Elementary"`` and ``"Julian Union High"``,
        ``"Princeton ESD 115"`` and ``"Princeton HSD 500"``) are two bodies that
        a listing of the town's schools may mean together, and ``"Avon Grove
        CS"`` is a charter school beside ``"Avon Grove SD"``, not its legal form.
        """
        index = self.index
        first = index.forms[tied[0].index]

        def place(position: int) -> tuple[str, str | None, str | None]:
            return (*self._town_of(position), index.records[position].county_fips)

        def same_name(position: int) -> bool:
            form = index.forms[position]
            words = form.token_set == first.token_set or (
                bool(form.compact) and form.compact == first.compact
            )
            return words and form.levels == first.levels

        where = place(tied[0].index)
        if None in where or any(
            not index.is_district[s.index] or place(s.index) != where or not same_name(s.index)
            for s in tied
        ):
            return None
        said = forms.legal - lexicon.GENERIC_LEGAL_WORDS
        chosen: list[Scored] = []
        why = ""
        if said:
            chosen = [s for s in tied if said <= index.legal_words(s.index)]
            if len(chosen) > 1:
                chosen = [
                    s
                    for s in chosen
                    if index.legal_words(s.index) - lexicon.GENERIC_LEGAL_WORDS == said
                ]
            why = f"the only one whose legal form says {' '.join(sorted(said))!r}"
        if (
            len(chosen) != 1
            and forms.hint is Level.DISTRICT
            and all(index.forms[s.index].qualifiers == first.qualifiers for s in tied)
        ):
            chosen = [s for s in tied if len(index.schools_of(s.index)) > 1]
            why = "the only one that runs more than one school"
        if len(chosen) != 1:
            return None
        return _Tie(
            chosen[0],
            frozenset(s.index for s in tied),
            f"of {len(tied)} districts of one town that tie by name, {why}",
            Reason.NAME,
        )

    def _exact_tie(self, tied: Sequence[Scored], forms: ListingForms) -> _Tie | None:
        """The one of several districts that tie by name whose name is the listing's.

        Names tie when the words that tell them apart are ones a listing may
        leave out (a town qualifier, a legal form) or fold together (a plural).
        The listing then names the one district it says exactly:

        1. its words and nothing more (:meth:`~snowlight.match.index.NameIndex.says_exactly`):
           ``"Saint Paul"`` is ``"Saint Paul Public Schools"``, not the charter
           district ``"St. Paul City School"``, and ``"Kent ISD"`` is ``"Kent
           ISD"``, not ``"Kent City Community Schools"``;
        2. of several that do, or of several that bear one name
           (:meth:`_one_name`) when none does, the one whose legal form says the
           :data:`~snowlight.match.lexicon.DISTINCT_LEGAL_WORDS` the listing's
           does: ``"Genesee ISD"`` is Michigan's intermediate district
           ``"Genesee ISD"``, not ``"Genesee School District"``, and ``"Wexley
           Union School District"`` is ``"Wexley Union Elementary"``, not
           ``"Wexley Elementary"``; when the listing's says none of them and
           the districts lie in one county, the one whose legal form says none
           (:meth:`_apart`): ``"Genesee School District"`` is the
           township's district, not the county's intermediate district
           ``"Genesee ISD"`` beside it, and ``"Saginaw Public Schools"`` the
           city's, not ``"Saginaw ISD"``;
        3. otherwise, the one that spells the listing's words as it does,
           nothing stemmed, when every other has the same words spelled
           otherwise (:meth:`_spelled_as_listed`): ``"Oak Hill Schools"`` is
           ``"Oak Hill Union Local"``, not ``"Oak Hills Local"``, and ``"Scott
           Valley"`` is ``"Scott Valley Unified"``, not ``"Scotts Valley
           Unified"``.

        Only districts: two schools of one name (``"St. Mary's School"`` and
        ``"St. Mary's Catholic School"``) may be one school however a list writes
        it. Two districts of one name (the two ``"Edgewood ISD"`` of Texas) stay
        tied, for distance to tell apart or for the unmatched queue; so do
        names with other words than the listing's (``"Central CUSD"`` against
        ``"A-C Central CUSD 262"`` and ``"Central City SD 133"``).

        Districts that tie in two counties or more (:meth:`_apart`) are two
        places, and a list names each for the market around it, which never
        needs the words that set it apart from a namesake two counties off. So
        that the listing says one's name and nothing more is no sign it means
        that one: step 1 does not decide, and neither does a legal form the
        listing's leaves out. ``"Union Township Public Schools"`` names Union
        County's ``"Township of Union School District"`` as much as Hunterdon
        County's ``"Union Township School District"`` (the word order is no
        part of the name, see :func:`~snowlight.match.normalize.name_first`),
        and ``"Springfield School District"`` Montgomery County's
        ``"Springfield Township SD"`` as much as Delaware County's
        ``"Springfield SD"``. Only what the listing says that a tied name lacks
        rules that name out: a distinct legal form (step 2, over every tied
        district: ``"Oak Hill Union Local"``) or a spelling (step 3: ``"Oak
        Hill"`` is not ``"Oak Hills"``, ``"Fall River"`` not ``"River Falls"``).
        Otherwise only a point much nearer one of them (:meth:`_break_tie`)
        tells them apart, or the listing goes to the queue.
        """
        index = self.index
        if any(not index.is_district[s.index] for s in tied):
            return None
        apart = self._apart(tied)
        chosen = [] if apart else [s for s in tied if self._names_exactly(forms, s.index)]
        if len(chosen) == 1 and (
            self._beside_its_town_s_system(chosen[0], tied)
            or self._both_leave_out(chosen[0], tied, forms)
        ):
            chosen = []
        why = "whose name is the listing's, word for word"
        said = forms.legal & lexicon.DISTINCT_LEGAL_WORDS
        # Across counties a distinct legal form rules out every tied name that
        # lacks it; in one, only among the names the listing says exactly.
        one_name = not apart and self._one_name(tied)
        pool = list(tied) if apart or (not chosen and one_name) else chosen
        if len(chosen) != 1 and said:
            legal = [s for s in pool if said <= index.legal_words(s.index)]
            if legal:
                chosen = legal
                why = f"whose legal form says {' '.join(sorted(said))!r}"
        elif len(chosen) != 1 and pool and not apart:
            plain = [
                s
                for s in pool
                if index.legal_words(s.index).isdisjoint(lexicon.DISTINCT_LEGAL_WORDS)
            ]
            if len(plain) == 1:
                chosen = plain
                why = "of one county whose legal form says nothing the listing leaves out"
        if len(chosen) != 1:
            chosen = self._spelled_as_listed(chosen or list(tied), forms)
            why = "that spells the listing's words as it does"
        if len(chosen) != 1:
            return None
        return _Tie(
            chosen[0],
            frozenset(s.index for s in tied),
            f"of {len(tied)} districts that tie by name, the only one {why}",
            Reason.NAME,
        )

    def _beside_its_town_s_system(self, chosen: Scored, tied: Sequence[Scored]) -> bool:
        """True when ``chosen`` runs one school and a tied district of its town runs more.

        ``"Glens Falls"`` says ``"GLENS FALLS COMMON SCHOOL DISTRICT"``, a district
        of one school, word for word, but no more surely names it than the town's
        system beside it, ``"GLENS FALLS CITY SCHOOL DISTRICT"``, whose ``City``
        a list may leave out: the name does not tell them apart.
        """
        if len(self.index.schools_of(chosen.index)) > 1:
            return False
        town = self._town_of(chosen.index)
        return any(
            s.index != chosen.index
            and self._town_of(s.index) == town
            and len(self.index.schools_of(s.index)) > 1
            for s in tied
        )

    def _both_leave_out(self, chosen: Scored, tied: Sequence[Scored], forms: ListingForms) -> bool:
        """True when ``chosen`` is the listing's name only once a word of its legal form goes.

        And a tied district is the listing's name once its municipal word goes:
        ``"Manheim School District"`` leaves out the ``Central`` of ``"Manheim
        Central SD"`` as much as the ``Township`` of ``"Manheim Township SD"``,
        two districts of one county. Only a legal-form word that is as often a
        name's (:data:`~snowlight.match.lexicon.NAME_LIKE_LEGAL_WORDS`):
        ``"Central Schools"`` is Iowa's ``"Central Comm School District"``,
        whose ``Community`` any list leaves out, not ``"Central City Comm School
        District"``. A district of one school named as it is no rival
        (:meth:`_names_exactly`).
        """
        index = self.index
        extra = (index.legal_words(chosen.index) & lexicon.NAME_LIKE_LEGAL_WORDS) - forms.legal
        return bool(extra) and any(
            s.index != chosen.index
            and not self._one_school(s.index)
            and index.says_exactly(forms.district, s.index, forgive=True)
            for s in tied
        )

    def _apart(self, candidates: Sequence[Scored]) -> bool:
        """True when the districts ``candidates`` lie in two places or more.

        Two counties, as their offices' counties say; where the directory gives
        no county for one, two towns (:meth:`_town_of`), and a district whose
        town it does not give either is taken to lie apart. Districts of one
        county are one place, whose names NCES keeps apart as their bodies are
        (see :meth:`_exact_tie`).
        """
        records = self.index.records
        counties = {records[s.index].county_fips for s in candidates}
        known = counties - {None}
        if len(known) > 1 or None not in counties:
            return len(known) > 1
        towns = {self._town_of(s.index) for s in candidates}
        return len(towns) > 1 or any(place is None for _state, place in towns)

    def _one_name(self, candidates: Sequence[Scored]) -> bool:
        """True when ``candidates`` bear one name, but for legal form and spelling.

        The same words (or the same words run together), levels, numbers and
        place qualifiers, as :meth:`~snowlight.match.index.NameIndex.says_exactly`
        compares them: ``"Wexley Union Elementary"`` and ``"Wexley Elementary"``.
        """
        forms = self.index.forms
        first = forms[candidates[0].index]
        return all(
            (form.token_set == first.token_set or form.compact == first.compact)
            and form.levels == first.levels
            and form.numbers == first.numbers
            and form.qualifiers == first.qualifiers
            for form in (forms[s.index] for s in candidates[1:])
        )

    def _spelled_as_listed(self, tied: Sequence[Scored], forms: ListingForms) -> list[Scored]:
        """The one of ``tied`` that spells the listing's words, when the rest misspell them.

        Every other candidate must have the listing's words, stemmed, and spell
        them otherwise (``"Oak Hills Local"`` for ``"Oak Hill Schools"``); one
        with other words (``"A-C Central CUSD 262"`` for ``"Central CUSD"``) is a
        rival spelling cannot rule out, and nothing is picked.
        """
        index = self.index
        words = index.identifying(forms.district.token_set)
        spelled: list[Scored] = []
        for s in tied:
            if index.says_as_spelled(forms.spelled, s.index):
                spelled.append(s)
            elif index.identifying(index.token_sets[s.index]) != words:
                return []
        return spelled

    def _as_system(
        self,
        scored: Sequence[Scored],
        point: tuple[float, float] | None,
        forms: ListingForms,
        *,
        home: frozenset[str] | None,
    ) -> _Outcome | None:
        """The school system a listing names, when NCES splits it into several districts.

        See :mod:`snowlight.match.systems`. A listing that says a system's name
        and nothing that picks one of its districts (a level, a code, a number
        one of them has: :func:`~snowlight.match.systems.names_a_system`,
        :meth:`~snowlight.match.systems.Systems.numbered`) names every one of
        them: ``"Billings Public Schools"`` is ``"Billings Elem"`` and
        ``"Billings H S"``, which tie by name, and ``"Kalispell"`` is
        ``"Kalispell Elem"`` and ``"Flathead H S"``, which does not answer to the
        name at all. The system's reading is as good as its best district's
        plausibility (the listing leaves out that district's level or number
        because it names them all; a municipal word none of them says costs none
        of them anything, as ``"Santa Rosa City Schools"`` says of ``"Santa Rosa
        Elementary"`` and ``"Santa Rosa High"``, see
        :meth:`~snowlight.match.index.NameIndex.forgiven`), and must be at least
        as good as any other candidate's; a rival outside the system within
        :attr:`MatchSettings.margin` costs confidence as for any name, and a
        school of the system is none. The best district is the result's
        :attr:`MatchResult.target`, the others :attr:`_Outcome.joint`.

        A listing that says the system's name with a legal-form word only one
        of its districts says (``"Phoenix Union"``, ``"Anaheim Union"``) names
        that district alone, and the others are no rivals.

        Returns ``None`` when the listing names no system among the best candidates.
        """
        form = forms.district
        if not names_a_system(form, school=forms.hint is Level.SCHOOL):
            return None
        index = self.index
        settings = self.settings
        floor = scored[0].score - settings.tie
        words = index.identifying(form.token_set)
        readings: dict[int, tuple[SchoolSystem, list[Scored]]] = {}
        for s in scored:
            system = self.systems.of(s.index) if index.is_district[s.index] else None
            if system is not None:
                readings.setdefault(system.members[0], (system, []))[1].append(s)
        found: list[tuple[SchoolSystem, Scored]] = []
        for system, candidates in readings.values():
            if (form.numbers and self.systems.numbered(system)) or self._school_over_system(
                system, scored, forms
            ):
                continue
            name = system.named_by(form, words, forms.legal)
            if name is not None:
                members = candidates
                if form.qualifiers - name.qualifiers:
                    # "Santa Rosa City Schools": a municipal word no district of
                    # the system says, which tells none of them apart.
                    members = [
                        max(s, index.forgiven(forms, s.index), key=lambda m: m.plausibility)
                        for s in candidates
                    ]
                best = max(members, key=lambda s: (s.plausibility, -s.index))
                if best.plausibility >= floor:
                    found.append((system, best))
            elif any(name.said_by(form, words) for name in system.names):
                saying = self.systems.saying(system, forms.legal)
                if len(saying) == 1:
                    outcome = self._one_of_system(system, saying[0], scored, point, forms)
                    if outcome is not None:
                        return outcome
        if not found:
            return None
        system, member = max(found, key=lambda pair: (pair[1].plausibility, -pair[1].index))
        return self._system_outcome(system, member, scored, point, home=home)

    def _school_over_system(
        self, system: SchoolSystem, scored: Sequence[Scored], forms: ListingForms
    ) -> bool:
        """True when a school is the listing's name, word for word, and ``system``'s is not.

        ``"Salinas Community"`` is the county's community school of that name,
        not Salinas's two districts, whose names say no ``Community``: the
        listing says a legal-form word (bar the generic ones) that no district of
        the system says, and a candidate school says the listing exactly. The
        listing is then read as any other, and the school competes with the
        system's districts by name.
        """
        index = self.index
        said = forms.legal - lexicon.GENERIC_LEGAL_WORDS
        if not said or any(said <= index.legal_words(member) for member in system.members):
            return False
        members = frozenset(system.members)
        return any(
            not index.is_district[s.index]
            and index.owner_of(s.index) not in members
            and index.says_exactly(forms.school, s.index)
            for s in scored
        )

    def _system_outcome(
        self,
        system: SchoolSystem,
        member: Scored,
        scored: Sequence[Scored],
        point: tuple[float, float] | None,
        *,
        home: frozenset[str] | None,
    ) -> _Outcome | None:
        """The outcome of a listing that names ``system``, read through its best district.

        A rival that ties with the system is told apart by distance when
        ``point`` is given, as any tie is (:meth:`_break_tie`): the system much
        nearer the market wins; a rival much nearer, and the listing is read as
        any other (``None``).
        """
        index = self.index
        members = frozenset(system.members)
        winner = Scored(member.index, min(1.0, member.plausibility), member.plausibility)
        others = [
            s for s in scored if s.index not in members and index.owner_of(s.index) not in members
        ]
        note = ""
        tied = [s for s in others if s.plausibility >= winner.score - self.settings.tie]
        distances = self._distances([winner, *tied], point)
        across = self._across_states([winner, *tied])
        tie = (
            self._break_tie([winner, *tied], distances, home=home, known=across)
            if point is not None and tied
            else None
        )
        if tie is None and across:
            return self._undecided_across(winner, [winner, *tied], scored, distances, point)
        if tie is not None:
            if tie.winner.index != winner.index:
                return None
            note = f"; {tie.note}"
            others = [s for s in others if s.index not in tie.tied]
        rival = max(others, key=lambda s: s.plausibility, default=None)
        records = index.records
        shown = system.members[:_NAMES_SHOWN]
        names = ", ".join(repr(records[m].name) for m in shown)
        more = (
            f" and {len(system.members) - len(shown)} more"
            if len(system.members) > len(shown)
            else ""
        )
        return self._judged(
            winner,
            rival,
            scored,
            point,
            reason=Reason.SYSTEM,
            detail=f"names the {len(system.members)} districts of one system ({names}{more}){note}",
            joint=tuple(m for m in system.members if m != member.index),
        )

    def _one_of_system(
        self,
        system: SchoolSystem,
        chosen: int,
        scored: Sequence[Scored],
        point: tuple[float, float] | None,
        forms: ListingForms,
    ) -> _Outcome | None:
        """The one district of ``system`` whose legal form says what the listing's does.

        See :meth:`_as_system`. ``None`` when that district is no candidate as
        good as the best, and the listing is read as any other.
        """
        member = next((s for s in scored if s.index == chosen), None)
        if member is None or member.plausibility < scored[0].score - self.settings.tie:
            return None
        others = frozenset(system.members) - {chosen}
        rest = [s for s in scored if s.index not in others]
        said = " ".join(sorted(forms.legal & lexicon.DISTINCT_LEGAL_WORDS))
        outcome = self._judged(
            member,
            self._rival(member, rest, frozenset({chosen})),
            rest,
            point,
            reason=Reason.NAME,
            detail=(
                f"of the {len(system.members)} districts of one system, the only one "
                f"whose legal form says {said!r}"
            ),
        )
        return replace(outcome, ranked=(*outcome.ranked, *(s for s in scored if s.index in others)))

    def _judged(  # noqa: PLR0913 - the winner, its rival, and how to say it
        self,
        winner: Scored,
        rival: Scored | None,
        scored: Sequence[Scored],
        point: tuple[float, float] | None,
        *,
        reason: Reason,
        detail: str,
        joint: tuple[int, ...] = (),
    ) -> _Outcome:
        """``winner`` over ``rival``: accepted for ``reason`` unless the rival is within the margin.

        A rival within :attr:`MatchSettings.margin` costs confidence as in
        :meth:`_decide`; ``joint`` goes with an accepted winner only.
        """
        settings = self.settings
        runner = rival.plausibility if rival is not None else 0.0
        gap = winner.score - runner
        confidence = winner.score - max(0.0, settings.margin - gap) * settings.margin_slope
        confidence = min(1.0, max(0.0, confidence))
        if confidence >= settings.threshold:
            said = f"{detail}; next {runner:.3f}"
        elif winner.score >= settings.threshold and rival is not None:
            reason = Reason.AMBIGUOUS
            other = self.index.records[rival.index].name
            said = f"{detail}, but {other!r} scores {runner:.3f}"
            joint = ()
        else:
            reason = Reason.WEAK
            said = f"{detail}, scoring {winner.score:.3f}"
            joint = ()
        ranked = (winner, *(s for s in scored if s.index != winner.index))
        distances = self._distances(list(ranked[: settings.runners_up + 1]), point)
        return _Outcome(winner, confidence, reason, said, ranked, distances, joint)

    def _decide(
        self,
        scored: list[Scored],
        point: tuple[float, float] | None,
        forms: ListingForms,
        *,
        home: frozenset[str] | None,
    ) -> _Outcome:
        """Pick the best of ``scored`` for a listing read as ``forms`` and say how sure that is.

        Names that tie go to the one much nearer ``point`` (:meth:`_break_tie`),
        or, among districts of one town, to the one whose legal form the
        listing says (:meth:`_legal_form_tie`), or, among districts, to the one
        whose name the listing says exactly (:meth:`_exact_tie`). A school that says more than the
        listing gives way to its own district when the district's name is the
        listing's, word for word (:meth:`_exact_reading`); when that district
        does not fit the listing's words well enough to be taken (``"Allen
        Village School"`` for ``"ALLEN VILLAGE"`` and its ``"ALLEN VILLAGE HIGH
        SCHOOL"``), neither is, and the listing goes to the queue. A district
        gives way to its own school when a listing that reads as one school is
        that school's name, word for word (:meth:`_school_reading`). A rival
        within the margin costs confidence. Before all of it, a listing that
        names a school system NCES splits into several districts names every one
        of them (:meth:`_as_system`).
        """
        settings = self.settings
        if not scored:
            return _Outcome(None, 0.0, Reason.NO_CANDIDATE, _NO_CANDIDATE, ())
        system = self._as_system(scored, point, forms, home=home)
        if system is not None:
            return system
        best = scored[0]
        tied = [s for s in scored if s.plausibility >= best.score - settings.tie]
        distances = self._distances([*tied, *scored[: settings.runners_up + 1]], point)
        across = self._across_states(tied)
        tie = (
            self._break_tie(tied, distances, home=home, known=across)
            if point is not None and len(tied) > 1
            else None
        )
        if tie is None and across:
            return self._undecided_across(best, tied, scored, distances, point)
        if tie is None and len(tied) > 1:
            tie = self._legal_form_tie(tied, forms) or self._exact_tie(tied, forms)
        elif tie is not None and self._apart(tied):
            tie = self._nearest_forgiven(tie, forms)
        return self._settled(best, tie, scored, distances, point, forms, home=home)

    def _nearest_forgiven(self, tie: _Tie, forms: ListingForms) -> _Tie:
        """A tie that a point broke between districts apart, its winner's municipal word forgiven.

        A municipal word the listing leaves out costs a district whose name says
        it when another in scope bears the rest of the name: ``"Ashfield
        Schools"`` names ``"Ashfield School District"`` before ``"Ashfield
        Township School District"`` of the same county (see
        :meth:`~snowlight.match.index.NameIndex.search`). Two such districts of two
        counties tie, as two places of one name (:meth:`_exact_tie`); once a
        point much nearer one of them has told them apart, the word no longer
        does, and costs the one taken nothing: ``"Springfield Schools"`` near
        Burlington County, New Jersey, is its ``"Springfield Township School
        District"``, not Union County's ``"Springfield Public School District"``;
        and ``"Springfield"`` alone, a place's name, is the township's district
        too (:meth:`_as_town_district`). Not for a listing that says a municipal
        word and nothing of a school system: ``"Ashfield Township"`` names the
        township, as the index reads it (see
        :meth:`~snowlight.match.index.NameIndex.forgiven`).
        """
        winner = tie.winner
        form = forms.district
        municipal = not form.qualifiers.isdisjoint(lexicon.MUNICIPAL_QUALIFIERS)
        if not self.index.is_district[winner.index] or (
            municipal and form.hint is not Level.DISTRICT
        ):
            return tie
        forgiven = self.index.forgiven(forms, winner.index)
        if forgiven.score <= winner.score:
            return tie
        plausibility = max(winner.plausibility, forgiven.plausibility)
        return replace(tie, winner=Scored(winner.index, forgiven.score, plausibility))

    def _settled(  # noqa: PLR0913, PLR0917 - the tie's outcome, and what it was among
        self,
        best: Scored,
        tie: _Tie | None,
        scored: list[Scored],
        distances: dict[int, float],
        point: tuple[float, float] | None,
        forms: ListingForms,
        *,
        home: frozenset[str] | None,
    ) -> _Outcome:
        """The outcome of :meth:`_decide` once ties are broken, or left unbroken (``tie``).

        The exact readings of the winner (:meth:`_exact_reading`,
        :meth:`_school_reading`, :meth:`_bare_reading`), its rival and the whole
        district it may stand for (:meth:`_whole_district`), and its namesakes
        across a state line (:meth:`_namesakes_across`), which leave the listing
        for the queue unless ``point`` is much nearer the winner.
        """
        settings = self.settings
        winner = tie.winner if tie is not None else best
        set_aside = tie.tied if tie is not None else frozenset({best.index})
        exact = (
            self._exact_reading(winner, scored, forms)
            or self._school_reading(winner, scored, forms)
            or self._bare_reading(winner, scored, forms)
        )
        held: Scored | None = None
        if exact is not None and (
            not self.index.is_district[exact.index] or exact.score >= settings.threshold
        ):
            winner = exact
            set_aside |= {exact.index}
        elif exact is not None:
            held = exact
        rival = self._rival(winner, scored, set_aside)
        whole = (
            self._whole_district(winner, rival, scored, forms)
            if rival is not None and tie is None
            else None
        )
        if whole is not None:
            winner = whole
            rival = self._rival(winner, scored, frozenset({whole.index}))
        runner = rival.plausibility if rival is not None else 0.0
        gap = winner.score - runner
        confidence = winner.score - max(0.0, settings.margin - gap) * settings.margin_slope
        confidence = min(1.0, max(0.0, confidence))
        if confidence >= settings.threshold and (held is None or held.index == winner.index):
            namesakes = self._namesakes_across(winner, scored, forms)
            if namesakes and not self._nearest_of(winner, namesakes, distances, point, home=home):
                return self._undecided_across(
                    winner, [winner, *namesakes], scored, distances, point
                )
        ranked = (winner, *(s for s in scored if s.index != winner.index))
        if held is not None and held.index != winner.index:
            name = self.index.records[winner.index].name
            district = self.index.records[held.index].name
            detail = (
                f"{district!r} is the listing's name, word for word, but scores "
                f"{held.score:.3f}; {name!r} says more than the listing"
            )
            ranked = (winner, held, *(s for s in ranked[1:] if s.index != held.index))
            return _Outcome(
                winner, self._short_of(confidence), Reason.AMBIGUOUS, detail, ranked, distances
            )
        reason, detail = self._explained(winner, rival, confidence, tie, exact=exact is not None)
        return _Outcome(winner, confidence, reason, detail, ranked, distances)

    def _explained(
        self,
        winner: Scored,
        rival: Scored | None,
        confidence: float,
        tie: _Tie | None,
        *,
        exact: bool,
    ) -> tuple[Reason, str]:
        """Why :meth:`_settled` takes ``winner``, or leaves it: the reason and how to say it."""
        settings = self.settings
        name = self.index.records[winner.index].name
        runner = rival.plausibility if rival is not None else 0.0
        if confidence >= settings.threshold:
            reason = tie.reason if tie is not None else Reason.NAME
            detail = (
                tie.note
                if tie is not None
                else f"name scores {winner.score:.3f}, next {runner:.3f}"
            )
            if exact:
                detail = f"{detail}; its name is the listing's, word for word"
            return reason, detail
        if winner.score >= settings.threshold and rival is not None:
            other = self.index.records[rival.index].name
            return (
                Reason.AMBIGUOUS,
                f"{name!r} scores {winner.score:.3f} but {other!r} scores {runner:.3f}",
            )
        return Reason.WEAK, f"best name {name!r} scores {winner.score:.3f}"

    # -- listings in parts -----------------------------------------------------

    def _contexts(
        self, part: str, base: Scope, point: tuple[float, float] | None
    ) -> list[_Context]:
        """Read one context part of a listing as a state, a district or a city."""
        code = part.strip().upper()
        if _STATE.fullmatch(code):
            if code not in base.states:
                return []
            return [_Context(replace(base, states=frozenset({code})), 1.0, f"state {code}")]
        contexts: list[_Context] = []
        forms = listing_forms(part)
        if not forms.is_empty:
            scored = self.index.search(forms, replace(base, kinds=("district",)))
            outcome = self._decide(scored, point, forms, home=base.market)
            if outcome.accepted and outcome.winner is not None:
                # A school system's schools are all its districts' ("PS 124 - NYC").
                districts = (outcome.winner.index, *outcome.joint)
                allowed = frozenset(
                    school for district in districts for school in self.index.schools_of(district)
                )
                name = self.index.records[outcome.winner.index].name
                more = f" and {len(districts) - 1} more" if len(districts) > 1 else ""
                contexts.append(
                    _Context(replace(base, allowed=allowed), outcome.confidence, f"in {name}{more}")
                )
        county = self._county_context(part, base)
        if county is not None:
            contexts.append(county)
        city = replace(base, city=city_key(part))
        contexts.append(_Context(city, 1.0, f"in the city {part.strip()!r}"))
        return contexts

    def _county_context(
        self, part: str, base: Scope, *, bracketed: bool = False
    ) -> _Context | None:
        """Read a context part of a listing as a county of its states, or ``None``.

        ``"Clark County"``, ``"Van Buren Co."``, or a county's name alone when no
        town of the states bears it (``"Madison (Lenawee)"``, ``"Evergreen School
        District (Clark)"``, as NCES writes a district's county beside its name),
        or when it is a bracket the listing ends with (``bracketed``, see
        :meth:`_with_brackets`). The county must lie among the listing's
        counties, when it has any.
        """
        words, kind = county_words(part)
        designated = kind is not None or (len(words) > 1 and words[-1] == "co")
        if designated and words[-1] == "co":
            words = words[:-1]
        index = self.index
        counties = index.counties_named(words, base.states)
        if not counties or (
            not designated and not bracketed and index.towns(place_keys(part), base.states)
        ):
            return None
        if base.counties is not None:
            counties &= base.counties
            if not counties:
                return None
        name = " ".join(words).title()
        return _Context(
            replace(base, counties=counties),
            1.0,
            f"in the county {name!r}",
            (record_form(" ".join(words), district=False),),
        )

    def _with_context(
        self, clean: CleanListing, base: Scope, point: tuple[float, float] | None
    ) -> Iterator[_Outcome]:
        parts = clean.segments[:MAX_SEGMENTS]
        for i, name in enumerate(parts):
            forms = listing_forms(name, district_hint=clean.all_schools)
            if forms.is_empty:
                continue
            readings = [self._contexts(p, base, point) for j, p in enumerate(parts) if j != i]
            for combination in itertools.product(*readings):
                context = _merge(combination, base)
                scope = None if context is None else self._answering(forms, context)
                if context is None or scope is None:
                    continue
                outcome = self._read(name, forms, scope, point)
                if outcome.accepted:
                    yield replace(
                        outcome,
                        confidence=min(outcome.confidence, context.confidence),
                        reason=Reason.CONTEXT,
                        detail=f"{outcome.detail}; {context.note}",
                    )

    def _answering(self, forms: ListingForms, context: _Context) -> Scope | None:
        """``context``'s scope, narrowed to the records that answer to what it says.

        ``None`` when none does.
        """
        if not context.said:
            return context.scope
        answering = frozenset(
            s.index
            for s in self.index.search(forms, context.scope)
            if all(self.index.answers_to(s.index, said) for said in context.said)
        )
        if not answering:
            return None
        return replace(context.scope, allowed=answering)

    def _with_brackets(
        self, clean: CleanListing, base: Scope, point: tuple[float, float] | None
    ) -> Iterator[_Outcome]:
        """The listing's name before the brackets it ends with, which must agree with it.

        A listing may give a name as NCES writes it: ``"Mason Consolidated
        Schools (Monroe)"``, ``"BRUNSWICK CENTRAL SCHOOL DISTRICT
        (BRITTONKILL)"``. A bracket that names a county of the states narrows
        the search to it, as NCES's county tells namesakes apart, even where a
        town bears the name too. The name before the brackets is then read
        among the records that answer to every bracket
        (:meth:`~snowlight.match.index.NameIndex.answers_to`: their county,
        second name, town, own words), as beside a city or a district.
        """
        if not clean.brackets or not clean.base:
            return
        forms = listing_forms(clean.base, district_hint=clean.all_schools)
        if forms.is_empty:
            return
        scope = base
        for bracket in clean.brackets:
            county = self._county_context(bracket, scope, bracketed=True)
            if county is not None:
                scope = county.scope
        said = tuple(bracket_form(bracket) for bracket in clean.brackets)
        answering = self._answering(forms, _Context(scope, 1.0, "", said))
        if answering is None:
            return
        outcome = self._read(clean.base, forms, answering, point)
        if outcome.accepted:
            brackets = ", ".join(repr(bracket) for bracket in clean.brackets)
            yield replace(
                outcome,
                reason=Reason.CONTEXT,
                detail=f"{outcome.detail}; among those that answer to {brackets}",
            )

    def _code_with_places(
        self, clean: CleanListing, base: Scope, point: tuple[float, float] | None
    ) -> Iterator[_Outcome]:
        """A district code followed by its towns, each town read with the code.

        ``"MSAD 51 - Cumberland, North Yarmouth"`` names a district by its code
        and lists its towns, not all of which have a school of their own; the
        code with any one town the district answers to (``"MSAD 51
        Cumberland"``) names it. When a part names a school (``"RSU 13 - South
        School, Rockland"``), the listing is about that school, and a town never
        makes it the whole district.
        """
        codes: list[str] = []
        for part in clean.segments:
            code = listing_forms(part).district
            if code.tokens or not (code.codes or code.district_numbers):
                break
            codes.append(part)  # "RSU 17 / MSAD 17" is one district's two codes
        places = clean.segments[len(codes) : len(codes) + MAX_SEGMENTS]
        if not codes or not places:
            return
        head = " ".join(codes)
        one_school = any(listing_forms(place).hint is Level.SCHOOL for place in places)
        for place in places:
            forms = listing_forms(f"{head} {place}", district_hint=clean.all_schools)
            outcome = self._read(f"{head} {place}", forms, base, point)
            if (
                outcome.accepted
                and outcome.winner is not None
                and not (one_school and self.index.is_district[outcome.winner.index])
            ):
                yield replace(
                    outcome,
                    reason=Reason.CONTEXT,
                    detail=f"{outcome.detail}; {head!r} with {place!r}",
                )

    def _result(
        self, result: MatchResult, outcome: _Outcome, point: tuple[float, float] | None
    ) -> MatchResult:
        records = self.index.records

        def candidate(s: Scored) -> Candidate:
            distance = outcome.distances.get(s.index)
            if distance is None and point is not None:
                distance = self._distance(records[s.index], point)
            return Candidate(records[s.index], round(s.score, 4), distance)

        best = candidate(outcome.ranked[0]) if outcome.ranked else None
        runners = tuple(candidate(s) for s in outcome.ranked[1 : 1 + self.settings.runners_up])
        target = best.record if best is not None and outcome.accepted else None
        targets = (target, *(records[j] for j in outcome.joint)) if target is not None else ()
        return replace(
            result,
            target=target,
            targets=targets,
            confidence=round(outcome.confidence, 4),
            reason=outcome.reason,
            detail=outcome.detail,
            best=best,
            runners_up=runners,
        )


def _merge(contexts: tuple[_Context, ...], base: Scope) -> _Context | None:
    """Combine the readings of several context parts; ``None`` when they cannot all hold."""
    scope = base
    for context in contexts:
        part = context.scope
        allowed = scope.allowed
        if part.allowed is not None:
            allowed = part.allowed if allowed is None else allowed & part.allowed
        if part.city is not None and scope.city is not None and part.city != scope.city:
            return None
        counties = scope.counties
        if part.counties is not None:
            counties = part.counties if counties is None else counties & part.counties
        scope = replace(
            scope,
            states=scope.states & part.states,
            counties=counties,
            allowed=allowed,
            city=part.city if part.city is not None else scope.city,
        )
    if not scope.states or scope.counties == frozenset():
        return None
    return _Context(
        scope,
        min((c.confidence for c in contexts), default=1.0),
        ", ".join(c.note for c in contexts),
        tuple(said for c in contexts for said in c.said),
    )
