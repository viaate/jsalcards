"""School systems NCES splits into several districts.

A closings list names a school system the way its town does: ``"Billings Public
Schools"``, ``"Kalispell"``, ``"NYC DOE"``. NCES splits some systems into several
districts, and a listing that names such a system names every one of them, so
that no school of it is left without the listing's status. The directory shows
three kinds, each read from NCES's own records (:func:`find_systems`):

* **One name, one district per level.** A town's districts that bear one name and
  differ only in the level each runs, in one county and one town: Montana's
  ``"Billings Elem"`` and ``"Billings H S"`` (some 80 towns), California's ``"Julian
  Union Elementary"`` and ``"Julian Union High"``, Illinois's ``"Streator ESD
  44"`` and ``"Streator Twp HSD 40"``, Arizona's ``"Phoenix Elementary District"``
  and ``"Phoenix Union High School District"``. The name they share is the
  town's school system's.
* **One office.** An elementary district named for its town and a high school
  district of another name that NCES places at the very same office, the only
  two districts there: Montana's ``"Kalispell Elem"`` and ``"Flathead H S"``,
  which Kalispell calls ``"Kalispell Public Schools"``, and ``"Miles City Elem"``
  with ``"Custer County H S"``. The system goes by the elementary district's
  name, its town's. A high school district with an office of its own
  (``"Jefferson H S"``, beside ``"Boulder Elem"``) is run apart from the town's
  elementary district, and is no part of its system. Districts of one name at
  one office (``"Petaluma City Elementary"`` and ``"Petaluma Joint Union
  High"``) answer to each one's full name as well as the one they share, so
  ``"Petaluma City Schools"`` names both.
* **One city's numbered districts.** A city whose system NCES splits into
  geographic districts (``"NEW YORK CITY GEOGRAPHIC DISTRICT # 1"`` to ``"#32"``),
  with the numbered districts of more than one school whose names begin with
  the city's in the same counties (``"NYC SPECIAL SCHOOLS - DISTRICT 75"``).
  The system goes by the city's name. Charter schools are districts of their
  own, and none of it.

A listing names a system when it says the system's name and no level, number,
district code, affiliation or school word (:meth:`SchoolSystem.named_by`). The
legal-form words that tell districts of one name apart must be every member's:
``"Phoenix Union"`` says ``Union``, which only ``"Phoenix Union High School
District"`` says, and names that district alone.
"""

from collections import defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from snowlight.match import lexicon
from snowlight.match.directory import DirectoryRecord
from snowlight.match.index import city_key
from snowlight.match.normalize import NameForm

if TYPE_CHECKING:  # pragma: no cover - only for the type checker
    from snowlight.match.index import NameIndex

SYSTEM_LEVELS: Final = frozenset({"elementary", "middle", "juniorhigh", "high"})
"""The levels a district of a system may run, one each."""
ELEMENTARY: Final = frozenset({"elementary"})
HIGH: Final = frozenset({"high"})
GEOGRAPHIC: Final = "geographic"
"""The legal-form word NCES gives a city's numbered districts (``"GEOGRAPHIC
DISTRICT # 1"``), stripped from their names (:data:`~snowlight.match.lexicon.WEAK_DESIGNATORS`)."""
SYSTEM_SIZE: Final = 2
"""The fewest districts a system has; one of one office has exactly as many."""
LEAVABLE: Final = lexicon.TOWN_QUALIFIERS | lexicon.MUNICIPAL_QUALIFIERS
"""Qualifiers of a system's name a listing may leave out: ``"New York Public
Schools"`` for New York City's."""

LEVELS: Final = "levels"
OFFICE: Final = "office"
CITY: Final = "city"


@dataclass(frozen=True, slots=True)
class SystemName:
    """A name a system answers to.

    Attributes:
        words: its identifying words, as :attr:`~snowlight.match.normalize.NameForm.token_set`.
        compact: the same words run together.
        qualifiers: the place qualifiers it says (``city`` for Miles City's).
        leavable: those of :attr:`qualifiers` a listing may leave out, as a
            town's name drops its ``City``: none for a city's numbered
            districts, since ``"New York"`` is a state's name as well as the city's.
        sayable: municipal qualifiers a listing may say that the name does not,
            since no district of the system says them (``"Santa Rosa City
            Schools"`` for ``"Santa Rosa Elementary"`` and ``"Santa Rosa High"``,
            as :data:`~snowlight.match.lexicon.MUNICIPAL_QUALIFIERS` has it). One
            that only some of them say picks those (``"Salinas City Schools"`` is
            ``"Salinas City Elementary"``, not ``"Salinas Union High"`` too).
    """

    words: frozenset[str]
    compact: str
    qualifiers: frozenset[str]
    leavable: frozenset[str] = LEAVABLE
    sayable: frozenset[str] = frozenset()

    def said_by(self, form: NameForm, words: frozenset[str]) -> bool:
        """True when a listing whose district reading is ``form`` says this name.

        ``words`` are the listing's identifying words. The same words (or run
        together), every qualifier it says among the name's or its
        :attr:`sayable` ones, and none of the name's left out but a
        :attr:`leavable` one.
        """
        if words != self.words and (not form.compact or form.compact != self.compact):
            return False
        qualifiers = form.qualifiers
        return (
            qualifiers - self.qualifiers <= self.sayable
            and self.qualifiers - qualifiers <= self.leavable
        )


@dataclass(frozen=True, slots=True)
class SchoolSystem:
    """Districts NCES keeps apart that a listing of their system names together.

    Attributes:
        members: the districts' positions in the index, in directory order.
        names: the names the system answers to.
        legal: the legal-form words that tell namesakes apart
            (:data:`~snowlight.match.lexicon.DISTINCT_LEGAL_WORDS`) that every
            member's name says: ``union`` for ``"Julian Union Elementary"`` and
            ``"Julian Union High"``.
        kind: how the directory shows it: :data:`LEVELS`, :data:`OFFICE` or :data:`CITY`.
    """

    members: tuple[int, ...]
    names: tuple[SystemName, ...]
    legal: frozenset[str]
    kind: str

    def named_by(
        self, form: NameForm, words: frozenset[str], legal: frozenset[str]
    ) -> SystemName | None:
        """The name of this system a listing says (see :class:`SystemName`), or ``None``.

        ``form`` is the listing's district reading, ``words`` its identifying
        words, ``legal`` its legal-form words (:func:`~snowlight.match.normalize.legal_words`):
        those that tell namesakes apart must be every member's.
        """
        if legal & lexicon.DISTINCT_LEGAL_WORDS - self.legal:
            return None
        return next((name for name in self.names if name.said_by(form, words)), None)


def names_a_system(form: NameForm, *, school: bool) -> bool:
    """True when a listing's district reading ``form`` may be a school system's name.

    It says no level, district code, affiliation or ``School`` of one school,
    and its words do not read as one school (``school``). A number it says must
    be one no district of the system has in its name (see
    :meth:`Systems.numbered`).
    """
    return not (
        school
        or form.levels
        or form.codes
        or form.affiliations
        or form.one_school
        or form.school_of
        or form.says_school
        or form.system
        or not form.token_set
    )


class Systems:
    """The school systems of a directory, by member (see :func:`find_systems`)."""

    def __init__(self, index: "NameIndex") -> None:
        self._index = index
        self._systems = tuple(find_systems(index))
        self._of = {member: system for system in self._systems for member in system.members}

    def __len__(self) -> int:
        return len(self._systems)

    def __iter__(self) -> Iterator[SchoolSystem]:
        return iter(self._systems)

    def of(self, position: int) -> SchoolSystem | None:
        """The system district ``position`` belongs to, or ``None``."""
        return self._of.get(position)

    def numbered(self, system: SchoolSystem) -> bool:
        """True when a district of ``system`` has a number in its name.

        A listing's number then says which district it names (``"Streator ESD
        44"``, ``"NYC District 5"``); otherwise NCES gives the system's districts
        no number to tell them apart by, and a listing that numbers its town's
        school system (``"Billings School District 2"``, which NCES calls
        ``"Billings Elem"`` and ``"Billings H S"``) still names all of them.
        """
        forms = self._index.forms
        return any(forms[member].numbers for member in system.members)

    def saying(self, system: SchoolSystem, legal: frozenset[str]) -> tuple[int, ...]:
        """The members whose names say each word of ``legal`` that tells namesakes apart.

        ``"Phoenix Union"`` says ``union``: of ``"Phoenix Elementary District"`` and
        ``"Phoenix Union High School District"``, only the second.
        """
        wanted = legal & lexicon.DISTINCT_LEGAL_WORDS
        index = self._index
        return tuple(m for m in system.members if wanted <= index.legal_words(m))


def _qualifiers(form: NameForm) -> frozenset[str]:
    return form.qualifiers | form.implied


def _sayable(forms: Sequence[NameForm]) -> frozenset[str]:
    """The municipal qualifiers none of ``forms`` says: see :attr:`SystemName.sayable`."""
    said = frozenset().union(*(_qualifiers(form) for form in forms))
    return lexicon.MUNICIPAL_QUALIFIERS - said


def _name(form: NameForm, sayable: frozenset[str]) -> SystemName:
    return SystemName(form.token_set, form.compact, _qualifiers(form), sayable=sayable)


def _distinct(index: "NameIndex", positions: Sequence[int]) -> frozenset[str]:
    """The distinct legal-form words every one of ``positions``' names says."""
    common: frozenset[str] | None = None
    for position in positions:
        words = index.legal_words(position) & lexicon.DISTINCT_LEGAL_WORDS
        common = words if common is None else common & words
    return common or frozenset()


def office_of(record: DirectoryRecord) -> tuple[str, float, float] | None:
    """Where NCES places a district's office: its state and point, or ``None`` when unknown.

    Two districts at one office are run from it; NCES geocodes each district by
    its own office's address, so two that share a building share a point.
    """
    point = record.point
    return None if point is None else (record.state, *point)


def _one_office(index: "NameIndex", positions: Sequence[int]) -> bool:
    """True when NCES places every one of ``positions`` at the same office."""
    offices = {office_of(index.records[p]) for p in positions}
    return len(offices) == 1 and None not in offices


def _by_levels(index: "NameIndex", districts: Sequence[int]) -> list[SchoolSystem]:
    """Systems of one name, one district per level: see the module docstring."""
    forms = index.forms
    records = index.records
    groups: dict[tuple[str, frozenset[str]], list[int]] = defaultdict(list)
    for position in districts:
        form = forms[position]
        if form.token_set:
            groups[records[position].state, form.token_set].append(position)
    found: list[SchoolSystem] = []
    for positions in groups.values():
        if len(positions) < SYSTEM_SIZE:
            continue
        levels = [forms[p].levels for p in positions]
        if any(len(level) != 1 or not level <= SYSTEM_LEVELS for level in levels):
            continue
        if len(set(levels)) != len(levels):
            continue
        counties = {records[p].county_fips for p in positions}
        towns = {index.place_of(p) for p in positions}
        if len(counties) != 1 or None in counties or len(towns) != 1 or None in towns:
            continue
        own = [forms[p] for p in positions]
        common = frozenset.intersection(*(_qualifiers(form) for form in own))
        sayable = _sayable(own)
        first = own[0]
        names = [SystemName(first.token_set, first.compact, common, sayable=sayable)]
        if _one_office(index, positions):
            # "Petaluma City Schools" is "Petaluma City Elementary" and "Petaluma
            # Joint Union High", run from one office.
            for form in own:
                name = _name(form, sayable)
                if name not in names:
                    names.append(name)
        found.append(
            SchoolSystem(tuple(positions), tuple(names), _distinct(index, positions), LEVELS)
        )
    return found


def _named_for_its_town(index: "NameIndex", position: int) -> bool:
    """True when district ``position``'s name, its level aside, is its town's."""
    city = index.records[position].city
    if city is None:
        return False
    form = index.forms[position]
    key = city_key(city)
    return key in {" ".join(form.tokens), " ".join((*form.tokens, *sorted(form.qualifiers)))}


def _by_office(index: "NameIndex", districts: Sequence[int], taken: set[int]) -> list[SchoolSystem]:
    """Systems of an elementary and a high school district at one office: see the module."""
    forms = index.forms
    records = index.records
    offices: dict[tuple[str, float, float], list[int]] = defaultdict(list)
    for position in districts:
        office = office_of(records[position])
        if office is not None:
            offices[office].append(position)
    found: list[SchoolSystem] = []
    for positions in offices.values():
        if len(positions) != SYSTEM_SIZE or taken.intersection(positions):
            continue
        elementary = [p for p in positions if forms[p].levels == ELEMENTARY]
        high = [p for p in positions if forms[p].levels == HIGH]
        if len(elementary) != 1 or len(high) != 1:
            continue
        town = elementary[0]
        if records[town].county_fips != records[high[0]].county_fips or not _named_for_its_town(
            index, town
        ):
            continue
        members = tuple(sorted(positions))
        name = _name(forms[town], _sayable([forms[p] for p in members]))
        found.append(SchoolSystem(members, (name,), _distinct(index, members), OFFICE))
    return found


def _begins_with(form: NameForm, tokens: tuple[str, ...], qualifiers: frozenset[str]) -> bool:
    """True when the name ``form`` begins with a city's: its ``tokens``, then its ``qualifiers``.

    The city's ``City`` is a qualifier where it ends the name of the city's
    numbered districts (``"NEW YORK CITY GEOGRAPHIC DISTRICT # 2"``) and a word of
    the name where more of it follows (``"NYC SPECIAL SCHOOLS - DISTRICT 75"``, see
    :func:`~snowlight.match.normalize.qualifies`): either way the name begins
    ``"New York City"``.
    """
    if form.tokens[: len(tokens)] != tokens:
        return False
    after = form.tokens[len(tokens) : len(tokens) + len(qualifiers)]
    return qualifiers <= form.qualifiers.union(after)


def _by_city(index: "NameIndex", districts: Sequence[int]) -> list[SchoolSystem]:
    """A city's numbered districts: see the module docstring."""
    forms = index.forms
    records = index.records
    groups: dict[tuple[str, tuple[str, ...], frozenset[str]], list[int]] = defaultdict(list)
    for position in districts:
        form = forms[position]
        if (
            form.district_numbers
            and GEOGRAPHIC in index.names[position].casefold()
            and GEOGRAPHIC in index.legal_words(position)
        ):
            groups[records[position].state, form.tokens, form.qualifiers].append(position)
    found: list[SchoolSystem] = []
    for (state, tokens, qualifiers), positions in groups.items():
        if len(positions) < SYSTEM_SIZE or not tokens:
            continue
        counties = {records[p].county_fips for p in positions} - {None}
        extra = [
            p
            for p in districts
            if p not in positions
            and records[p].state == state
            and records[p].county_fips in counties
            and forms[p].district_numbers
            and _begins_with(forms[p], tokens, qualifiers)
            and len(index.schools_of(p)) > 1
        ]
        members = tuple(sorted((*positions, *extra)))
        first = forms[positions[0]]
        name = SystemName(first.token_set, first.compact, qualifiers | first.implied, frozenset())
        found.append(SchoolSystem(members, (name,), _distinct(index, positions), CITY))
    return found


def find_systems(index: "NameIndex") -> list[SchoolSystem]:
    """Every school system of the index's directory: see the module docstring.

    A district belongs to one system at most: one of one name and levels first,
    then one of a city's numbered districts, then one of one office.
    """
    districts = [p for p, district in enumerate(index.is_district) if district]
    systems = _by_levels(index, districts)
    systems.extend(_by_city(index, districts))
    taken = {member for system in systems for member in system.members}
    systems.extend(_by_office(index, districts, taken))
    return systems
