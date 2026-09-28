"""Search index over the directory: candidate lookup and name scoring.

:class:`NameIndex` normalizes every directory name once (districts with their
legal-form words stripped, see :mod:`snowlight.match.normalize`) and keeps, per
state, a posting list from each word to the records that carry it, a lookup by
compact spelling (``oakridge`` for ``Oak Ridge``), a lookup by number for names
that are only a number (``CUSD 300``), and the state's vocabulary for typo
lookups.

Scoring a candidate against a listing is a weighted Dice coefficient over the
identifying words, times penalties for the parts that must agree:

* word weight: ``1 + ln(N / df)`` over the whole directory, so a rare word
  (``albertville``) counts far more than a common one (``lincoln``); joining
  words, initials, affiliations and a ``School`` inside a name (see
  :data:`~snowlight.match.lexicon.GENERIC_WORDS`) weigh
  :data:`~snowlight.match.lexicon.WEAK_WEIGHT`.
  A listing word the state does not know is looked up in the state's
  vocabulary; a close spelling (``albertvile``) counts with a reduced credit.
* numbers (``R-IV``, ``District 5``): different numbers all but rule a
  candidate out; a number on one side only costs a little.
* school levels: ``elementary`` against ``middle`` all but rules it out. A
  school whose name says no level is of the levels its NCES grades are
  (:func:`~snowlight.match.grades.fit`), since NCES often leaves the word out
  (``"Lincoln"`` of K-5, a parish's ``"ST JOSEPH SCHOOL"`` of PK-8): it scores
  as a name that says the listing's level when its grades are of it, as one
  that says another when they are not, and short of the threshold, though a
  full rival, when they reach well past it (a K-12 school for
  ``"Elementary"``) or are unknown (:func:`_levels_factor`).
* place qualifiers: a listing that says ``county`` needs a candidate that says
  it; a candidate's ``county`` or ``parish`` the listing leaves out costs more
  than a ``city`` or a ``township`` it leaves out, so ``Lancaster`` is not taken
  for ``Lancaster County`` by default. A municipal word (``City``, ``Township``,
  ``Borough``, ``Town``, ``Village``) that only one side says costs nothing
  when no other record in scope shares the rest of the name: NCES's
  ``"Murfreesboro"`` is the lists' ``"Murfreesboro City Schools"``, its
  ``"Bensalem Township SD"`` their ``"Bensalem School District"``, but
  ``"Bristol School District"`` is neither ``"Bristol Township SD"`` nor
  ``"Bristol Borough SD"`` beside it (:meth:`NameIndex.search`). A school's
  ``City``, ``Town``, ``Village`` or ``Borough`` the listing leaves out costs as
  a county does (:data:`PLACE_LEFT_OUT`): ``"Union High School"`` is not
  ``"Union City High School"``. A qualifier is one only where it ends a name
  after the name it qualifies (see :func:`~snowlight.match.normalize.qualifies`);
  elsewhere the word is the name's own (``"Village Christian Academy"``, ``"Kid
  City Academy"``), and a name that does not say it is another's
  (:data:`PLACE_WORD_NOT_SAID`). A name can imply a qualifier through its place:
  ``"Salt Lake District"`` lies in Salt Lake City, so a listing's ``"Salt Lake
  City"`` names it (:meth:`NameIndex._implied`).
* affiliations: a listing that names one (``Catholic``, ``Lutheran``,
  ``Montessori`` ...) rules out every record that does not name exactly the
  same ones: a public district or public school, a school of another or a
  further faith (``"York Christian"`` is not ``"York Adventist Christian"``),
  and a private school whose name leaves it out. ``"Omaha Catholic Schools"`` is
  never the city's public district. A listing may leave out a record's
  affiliation (``"St. Mary's"`` for ``"St. Mary's Catholic School"``).
* directions: a listing that says a compass direction (``"E. Lansing"``,
  ``"West Des Moines"``, ``"S. Portland"``; abbreviations are spelled out, see
  :func:`~snowlight.match.normalize.expand_directions`) rules out every record
  that does not say the same one, and a record that says one is ruled out for a
  listing that does not: ``"East Lansing"`` and ``"Lansing"`` are two towns.
* an affiliation the listing leaves out costs a record whose name is no
  saint's (``"Concord Academy"`` is not ``"Concord Christian Academy"``).
* forenames: a school named for a person may be listed by the surname and
  what follows it (``"Kennedy Middle School"``), leaving out the forenames its
  name begins with (:attr:`~snowlight.match.normalize.NameForm.forenames`), or
  with them written another way. Left out, they weigh nothing, whether the name
  spells them (``"John F Kennedy Middle"``) or gives only the initials (``"J F
  Kennedy Middle"``), and cost the score :data:`FORENAMES_LEFT_OUT`: such
  schools of one surname tie, and the listing goes to the queue, but one whose
  name is the listing's word for word (``"Kennedy Middle"``) comes first. An
  initial stands for a forename that begins
  with it, either way (``"J.F. Kennedy"`` and ``"John F. Kennedy"`` name both
  schools alike), and a listing whose forenames are another person's rules the
  record out (:data:`FORENAMES_DIFFER`). Only forenames that end with an
  initial, or that NCES bracketed after the surname (``"Lincoln (Abraham)
  Elementary"``), are surely a person's: a given name alone may be a place's
  word (``"Grace Hill"``, ``"Glen Park"``), so a record that begins with one is
  as close a rival for a listing of its surname but is never taken on it
  (:meth:`NameIndex._person`).
* plurals: a word the listing and the record write one with a trailing ``s``
  and one without is another word (``"Park Elementary"`` is not ``"Parks
  Elementary"``, ``"Brook"`` not ``"Brooks"``, ``"Oak Hill"`` not ``"Oak
  Hills"``: :data:`PLURAL_DIFFERS`), though as close a rival, as a list may
  misspell either; a saint's possessive (``"St. Marys"``), an
  apostrophe's (``"Kings Academy"`` for ``"King's Academy"``), a devotion's name
  (``"Sacred Hearts"``) and a word that says the school's kind (``"Arts and
  Sciences"``) cost nothing.
* word order: a listing that says ``School of`` or ``School for`` (``"Valley
  School of Carlisle"``) needs a record that says it too, not the same words in
  another order (``"Carlisle Valley School"``), and the other way round.
* kind: a listing whose words say district (``Schools``, ``ISD``) is scored
  down against schools, one that says school (``Elementary``, ``Academy``)
  against districts, unless the district's own name says it too (``"Fortuna
  Elementary"``, ``"Lancaster County Career and Technology Center"``), and a
  bare name leans slightly towards districts; one that names only a place and
  its kind (``"York Township"``) names no one school. A listing that ends ``Public
  School`` (``"Elba Public School"``) is the town's district unless a school
  has that very name (``"Carey Public School"``).
* place: whether a listing is only a town's name, and which districts lie in
  that town, is the matcher's to read (:meth:`NameIndex.towns`, which keys
  towns as they are spelled: ``"Oak Hills"`` is no town ``"Oak Hill"``); a
  school is never what such a listing names.
* legal forms inside a district's name go as those at its end do (``"Westside
  Union Elementary"``, ``"Sycamore Community City"``; see
  :mod:`snowlight.match.normalize`), and the matcher tells districts that tie
  by name apart by the legal form and spelling the listing says
  (:meth:`NameIndex.says_as_spelled`, :meth:`NameIndex.legal_words`).
* type: a listing that says ``Academy``, ``Charter``, ``Preparatory`` or
  ``Institute`` is scored down against a school that says another kind
  (``"St. Johnsbury Academy"`` is not ``"St. Johnsbury School"``).
* district codes (``"RSU 13"``, ``"USD 320"``, ``"D-3"``): a school carries its
  district's codes and number, so ``"RSU 13 Oceanside High School"`` needs a
  school of RSU 13 and rules out one of RSU 5 or of a town district, and a
  code of the other series (``"MSAD 13"``) rules out ``"RSU 13"``. A district a
  listing names by its code or number may be named by its towns and its
  schools' area rather than its own name (``"MSAD 17 - Oxford Hills"`` for
  ``"RSU 17/MSAD 17"``): see :meth:`NameIndex._coverage`.

* brackets NCES ends a name with (see
  :func:`~snowlight.match.normalize.directory_name`) are no name words: a
  district is matched by its name without them (``"Evergreen School District"``
  for ``"Evergreen School District (Clark)"``); the county a bracket names and a
  legal form it says are words a listing may say or leave out
  (:meth:`NameIndex.optional`); a second name (``"(NORTH ROCKLAND)"``) is a
  name the district answers to as well as its own, a little less surely
  (:data:`SECOND_NAME`); an entity number (``"(4192)"``) names only the record
  that carries it, when a listing gives it (:attr:`Scope.entity`).

Scoring says which record a listing names; :meth:`NameIndex.reach` says whether a
district can be named whole from a market that holds only part of it (a charter
network's other cities cannot), and :meth:`NameIndex.campuses` which of its
schools in the market a listing fits.
"""

import gc
import math
import re
from collections import Counter
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Final

from rapidfuzz import fuzz, process

from snowlight.match import lexicon
from snowlight.match.directory import Directory, DirectoryRecord
from snowlight.match.forenames import GIVEN_NAMES
from snowlight.match.grades import Fit, fit
from snowlight.match.normalize import (
    Level,
    ListingForms,
    NameForm,
    county_words,
    directory_name,
    fold,
    legal_words,
    record_form,
    spelled_name,
    stem,
)

# Penalties, as multipliers on the Dice score.
NUMBERS_DIFFER: Final = 0.3
NUMBERS_OVERLAP: Final = 0.7
NUMBER_ONLY_CANDIDATE: Final = 0.92
NUMBER_ONLY_LISTING: Final = 0.8
NUMBER_ONLY_LISTING_DISTRICT: Final = 0.9
"""A listing's district number the district's NCES name leaves out ("Fort Zumwalt R-II")."""
LEVELS_DIFFER: Final = 0.35
LEVELS_OVERLAP: Final = 0.75
LEVEL_ONLY_CANDIDATE: Final = 0.95
LEVEL_ONLY_LISTING: Final = 0.82
"""A listing's level that a record's name leaves out, when its grades do not say it is
of that level: a district's name, or a school's whose grades are unknown or reach well
past the level. Enough to keep an otherwise perfect name under the threshold. A
school keeps its plausibility (see :data:`_GRADES_FACTORS`): ``"St. John Lutheran
Preschool"`` may be the preschool of any PK-8 ``"ST JOHN LUTHERAN SCHOOL"`` in the
market, so it is never taken for the PK-1 one beside them."""
_GRADES_FACTORS: Final[dict[Fit, tuple[float, float]]] = {
    Fit.FITS: (1.0, 1.0),
    Fit.SPANS: (LEVEL_ONLY_LISTING, 1.0),
    Fit.UNKNOWN: (LEVEL_ONLY_LISTING, 1.0),
    Fit.PART: (LEVELS_OVERLAP, LEVELS_OVERLAP),
    Fit.APART: (LEVELS_DIFFER, LEVELS_DIFFER),
}
"""``(score factor, plausibility factor)`` for a listing's levels against a school whose
name says none, by how its grades fit them (:func:`~snowlight.match.grades.fit`)."""
QUALIFIER_NOT_FOUND: Final = 0.75
SOFT_QUALIFIER_NOT_FOUND: Final = 0.95
"""A listing's ``Area`` that the record's name leaves out: Minnesota's districts call
themselves ``"Elk River Area Schools"``, and NCES names them ``"Elk River Public
School District"``. A record that says ``Area`` too still wins by the margin
(``"Millbrook Area SD"`` over ``"Millbrook SD"``); see :data:`lexicon.SOFT_QUALIFIERS`."""
COUNTY_LEFT_OUT: Final = 0.82
COUNTY_LEFT_OUT_NUMBERED: Final = 0.96
"""A district's county qualifier (or ``Township``) a listing leaves out while it gives
the district's number: ``"West Platte R-2"`` for ``"WEST PLATTE CO. R-II"``,
``"Glenbard 87"`` for ``"Glenbard Twp HSD 87"``. No state has two districts whose
names differ only by that qualifier (``"Lancaster"`` and ``"Lancaster County"`` carry
no number), so the number says which it is."""
TOWN_LEFT_OUT: Final = 0.96
PLACE_LEFT_OUT: Final = COUNTY_LEFT_OUT
"""A school's ``City``, ``Town``, ``Village`` or ``Borough`` a listing leaves out.

At the end of a school's name the word finishes its place's name (``"Union City
High School"``, ``"Middle Village Elementary"``), which a list repeats: ``"Union
High School"`` is another school. Only a district's municipal word is how NCES and
the lists each happen to write a name (``"Murfreesboro"`` for ``"Murfreesboro City
Schools"``, see :data:`TOWN_LEFT_OUT`). Enough to keep an otherwise perfect name
under the threshold."""
TOWNSHIP_LEFT_OUT: Final = COUNTY_LEFT_OUT
"""A district's ``Township`` a listing leaves out, when another record in scope bears the
rest of its name (otherwise it costs nothing: see :meth:`NameIndex.search`). A
township's district is often a place of its own beside the borough or city of
one name (``"Bristol Township SD"`` and ``"Bristol Borough SD"``), so it costs
the score as a county does; but a listing may well mean it, so a rival that
leaves out a township competes at full strength."""
AFFILIATION_NOT_SAID: Final = 0.02
"""The listing names affiliations the record does not name exactly: ruled out.

Not zero, so the record still shows as a candidate in the unmatched queue for a
person to pin; :data:`~snowlight.match.matcher.MIN_THRESHOLD` keeps it far below any
threshold a matcher accepts.
"""
PARISH_IMPLIED: Final = 0.94
"""A saint's private school whose name implies the Catholic faith a listing says
(``"St. Paul's School"`` for ``"St. Paul Catholic School"``): the listing's when it
is alone, but short of a school that says the faith (``"ST PAUL CATHOLIC
SCHOOL"``), which wins. See :meth:`NameIndex._implies_the_faith`."""
AFFILIATION_LEFT_OUT: Final = 0.75
"""The record names an affiliation the listing leaves out, and its name is no saint's
or devotion's: ``"Concord Academy"`` is another school than ``"Concord Christian
Academy"``, and ``"Covenant School"`` than ``"Covenant Christian School"`` a state
away. A saint's school may be listed without its church (``"St. Mary's"`` for
``"St. Mary's Catholic School"``, see :data:`~snowlight.match.lexicon.DEVOTIONS`),
and so may a school a listing places in its own town by a name that is more than
the town's (``"Cheverus School - Malden"`` for ``"Cheverus Catholic School"`` in
Malden; see :meth:`NameIndex._placed_by_name`). Enough to keep an otherwise
perfect name under the threshold."""
DIRECTION_NOT_SAID: Final = 0.05
"""The listing and the record do not name the same compass directions: ruled out.

``"E. Lansing Public Schools"`` is East Lansing's district, never Lansing's, and
``"Lansing Public Schools"`` is never East Lansing's; ``"W. Des Moines"``, ``"S.
Portland"``, ``"N. Little Rock"`` likewise. The same words run together
(``"North Wood"``, ``"Northwood"``) are one name. Like
:data:`AFFILIATION_NOT_SAID`, not zero, so the record still shows in the unmatched
queue, and far under :data:`~snowlight.match.matcher.MIN_THRESHOLD`.
"""
PLACE_WORD_NOT_SAID: Final = 0.85
"""A place word one name holds as a word of its own that the other does not say at all.

``Village``, ``City`` or ``Town`` that begins a school's name, or has more of the
name after it, is the name's own word, not a qualifier a list may leave out (see
:func:`~snowlight.match.normalize.qualifies`): ``"Child Development Center"`` is not
``"Village Child Development Center"``, ``"Kids Academy"`` not ``"Kid City
Academy"``, and ``"Village Christian Academy"`` not ``"The Christian Academy"``.
On top of what the word weighs, so a name of common words (``Child``,
``Development``, ``Center``) that leaves it out stays well under the threshold."""
FORENAMES_LEFT_OUT: Final = 0.95
"""A school named for a person, listed by the surname and what follows it: its
forenames left out (``"Kennedy Middle School"`` for ``"John F Kennedy Middle"``
and for ``"J F Kennedy Middle"`` alike, see :meth:`NameIndex._person`). The
listing's when it is alone; a tie with any other such school of the surname, so
that the listing goes to the queue; and short of a school whose name is the
listing's, word for word (``"Kennedy Middle"``), which is the listing's first.
A record whose forenames may be a place's words (``"Charles White"``, ``"Grace
Hill"``, see :meth:`NameIndex._person`) is never taken so, but is as close a
rival."""
FORENAMES_DIFFER: Final = 0.3
"""The listing names another person than the school's name does: its first forename
is not the record's, nor its initial (``"Robert Kennedy"`` for ``"John F Kennedy"``),
or its initials differ (``"J.B. Nelson"`` for ``"V H Nelson"``, whose letters
weigh little else). See :meth:`NameIndex._person`."""
PLURAL_DIFFERS: Final = 0.8
"""A word one name writes with a trailing ``s`` and the other without it.

``"Park Elementary"`` is not ``"Parks Elementary"`` (Rosa Parks), ``"Brook
Elementary"`` not ``"Brooks School"``, ``"Oak Elementary"`` not ``"The Oaks
School"``, ``"Oak Hill"`` not ``"Oak Hills"``: the words are two, though the stem
both share is one (see :attr:`~snowlight.match.normalize.NameForm.plurals`, and
:func:`plural_words` for what is no plural). Enough to keep an otherwise perfect
name under the threshold, so a listing is never taken for the other word's
school. A list may misspell either, so the other word's school stays as close a
rival (its plausibility is not cut): where both spellings are in scope
(``"River Trail School"`` and ``"River Trails Middle School"``) a listing of one
names neither but by the rules that tell districts' spellings apart
(:meth:`~snowlight.match.matcher.Matcher._exact_tie`), and a list's misspelling
of the one name in scope (``"Welsh Hill School"`` for ``"WELSH HILLS SCHOOL"``)
goes to the queue with it."""
RULED_OUT: Final = 0.1
"""A plausibility under this says the listing rules the record out: it names a direction
or an affiliation the record does not (:data:`DIRECTION_NOT_SAID`,
:data:`AFFILIATION_NOT_SAID`)."""
WRONG_KIND: Final = 0.7
LEVEL_NAMED_DISTRICT: Final = 0.9
BARE_NAME_SCHOOL: Final = 0.95
PLACE_NOT_A_SCHOOL: Final = 0.75
"""A school of a level for a listing that names only a place and the kind of place
it is (``"York Township"``, ``"Harwick County"``, ``"Kettleby City"``): a township's
or a county's government, or a district named so, never the one school named for
the place (``"York Twp El Sch"``). A school whose own name is the listing's
(``"Cristo Rey Kansas City"``) is not one of a level. Enough to keep an otherwise
perfect name under the threshold."""
_PLACE_QUALIFIERS: Final = lexicon.QUALIFIERS & lexicon.MUNICIPAL_BODIES
_PLACE_WORDS: Final = lexicon.QUALIFIERS
"""Place qualifiers, which among a name's words are words of its own (see
:func:`~snowlight.match.normalize.qualifies`)."""
_TOWNSHIP: Final = "township"
ONE_OF_A_SYSTEM: Final = 0.85
"""A group of private schools (``"Springfield Catholic Schools"``) against one of a level."""
SCHOOL_OF_NOT_SAID: Final = 0.85
"""The listing says ``School of`` or ``School for`` and the record does not, or the
listing ends ``School`` and the record says ``School of``.

``"Valley School of Carlisle"`` names a school whose name puts the town after
``School of``; ``"Carlisle Valley School"`` has the same words in another order,
and is another school, as ``"The Sablewood School"`` is not ``"Village School of
Sablewood"``. A listing that says no ``School`` at all may leave the words out
(``"Pressley Ridge"``).
"""
TYPE_NOT_SAID: Final = 0.85
"""The listing says ``Academy``, ``Charter``, ``Preparatory`` or ``Institute`` and
the school does not (see :data:`~snowlight.match.lexicon.TYPE_NOUNS`,
:meth:`NameIndex._type_mismatch`)."""
ONE_SCHOOL_DISTRICT: Final = 0.9
"""A district whose name is one school's (``"St. Paul City School"``, a charter
school's own district) for a listing whose words say a school system (``"St. Paul
Public Schools"``): the town's system, when there is one, is what it names."""
TYPE_NOT_SHOWN: Final = 0.95
"""The listing says ``Academy``, ``Preparatory`` or ``Institute`` and the school's
name says nothing of its kind (``"ST MARY"``, ``"Gloria Deo"``): it may have lost
the noun, or be another school of that name. A rare name (``"Tollis Deo Academy"``
for ``"TOLLIS DEO"``) still passes; a common one (``"Saint Mary's Academy"``) does
not take the one kindless ``"ST MARY"`` among a state's many."""
PUBLIC_SCHOOL_DISTRICT: Final = 0.97
"""A district for a listing that ends ``Public School`` (``"Elba Public School"``).

A town's school system fits, a little less well than a school whose own name
ends ``Public School`` (``"Carey Public School"``, one school of a county
district): that one is what the listing names when the directory holds it.
"""
PUBLIC_SCHOOL_OTHER: Final = 0.85
"""A school whose name does not end ``Public School`` for a listing that does:
``"Carrington Public School"`` is the town's system, not ``"Carrington High
School"``, so the district, whose number the listing leaves out (``"Carrington
49"``), still outranks its schools."""
CODES_DIFFER: Final = 0.1
"""The listing's district code is of a series the record's codes are, with another
number: ``"MSAD 13"`` against ``"RSU 13"``, or a school of another unit."""
CODE_NOT_FOUND: Final = 0.3
"""The listing's code is of a series the state's directory names districts by,
and the record (or its district) carries none: not in that unit."""
DISTRICT_NUMBER_DIFFERS: Final = 0.3
"""The listing names a school with its district's number (``"D-3 Widefield High
School"``) and the school's district carries another number."""
NO_DISTRICT: Final = 0.3
"""The listing gives a district's code or number, and the record is a school no
district runs: ``"St. James R-1"`` is Missouri's district ``"ST. JAMES R-I"``, never
the private ``"ST JAMES CATHOLIC SCHOOL"``, which carries no district's number."""
CODE_ONLY: Final = 0.3
"""The least a district scores whose code a listing names, whatever else it says
(``"RSU 13 - Adult Education"``): never accepted, but shown in the unmatched queue."""
SECOND_NAME: Final = 0.95
"""The share of its score a district keeps when a listing names it by its second name.

NCES ends some districts' names with another name they are known by
(``"HAVERSTRAW-STONY POINT CSD (NORTH ROCKLAND)"``, ``"EVANS-BRANT CENTRAL SCHOOL
DISTRICT (LAKE SHORE)"``, see :func:`~snowlight.match.normalize.directory_name`):
``"North Rockland CSD"`` names that district. A district whose own name is the
listing's is still the likelier reading (``"Killeen ISD"``, not the charter
district ``"RICHARD MILBURN ALTER HIGH SCHOOL (KILLEEN)"``), so a second name
scores a little under it, and well over the threshold."""
COVERAGE_CREDIT: Final = 0.95
"""The score of a district a listing names by its code or number when the rest of
the listing names its places or its schools rather than the district's own name
(``"MSAD 17 - Oxford Hills"`` for ``"RSU 17/MSAD 17"``, ``"D-3 Widefield"`` for
``"School District No. 3 in the county of El Paso"``); see
:meth:`NameIndex._coverage`."""

COUNTY_DISTRICT_NAMES: Final[dict[str, re.Pattern[str]]] = {
    "SC": re.compile(r"[A-Za-z']+(?: \d{2})?"),
    "FL": re.compile(r"[A-Z][A-Z.'-]*(?: [A-Z][A-Z.'-]*)?"),
    "NV": re.compile(r"[A-Z][a-z]+"),
}
"""District names that are a county's name, by state; the name implies ``County``.

The CCD names these states' county school districts by the county alone, where
closings lists say ``"Leon County Schools"``: South Carolina's alone or with a
two-digit number (``"Greenville 01"``, ``"Spartanburg 07"``, ``"Barnwell"``),
Florida's in capitals (``"LEON"``, ``"MIAMI-DADE"``, ``"ST. JOHNS"``, ``"PALM
BEACH"``), and Nevada's rural ones in one word (``"Elko"``, ``"Lyon"``). A name
of another kind that fits the pattern (``"FL VIRTUAL"``) is only matched by a
listing that says ``County`` beside its words, which none does.
"""

_OWN_SCHOOL_NOUNS: Final = frozenset(stem(word) for word in (*lexicon.SCHOOL_NOUNS, "charter"))
"""Nouns that make a listing read as one school, as they appear among a name's tokens."""
_TYPE_NOUNS: Final = frozenset(stem(word) for word in lexicon.TYPE_NOUNS)
_CHARTER: Final = "charter"
_WEAK_TOKENS: Final = lexicon.WEAK_WORDS | frozenset(stem(word) for word in lexicon.GENERIC_WORDS)
"""Tokens that weigh :data:`~snowlight.match.lexicon.WEAK_WEIGHT`, as do single letters."""
_KIND_TOKENS: Final = frozenset(
    stem(word) for word in lexicon.STRONG_DESIGNATORS | lexicon.DISTRICT_WORDS
)
"""Designators left among a listing's words (``"Harmony Public Schools Bryan"``): they
say what kind of body it names, not which campus."""
_EMPTY: Final[frozenset[str]] = frozenset()
_CAMPUS_NOUNS: Final = frozenset(stem(word) for word in ("campus", "center"))
_CAMPUS: Final = re.compile(r"\s*[-\u2013]\s*(?:[^-\u2013]*\s)?campus\s*$", re.IGNORECASE)
"""A school's campus at the end of its name, after a dash: ``" - WORNALL CAMPUS"``,
``" -DOHERTY CAMPUS"``, ``" - Campus"``."""
"""Nouns that say a school is one place of several, not which: see :meth:`NameIndex.says_beyond`."""
_SCHOOLS_TO_COVER: Final = 2
"""A word counts as a district's own when this many of its schools carry it (or all
of them, if it has fewer): ``"Oxford Hills"`` is a district's area when its middle
and high schools are both named for it, not when one school is named ``Lincoln``."""
_CITY_SUFFIX: Final = " city"

REACH_KM: Final = 80.0
"""How far from a market a record may lie and still be the listing's.

A school district that straddles a market's edge keeps its schools near one
another, and its closing closes them all. Matching the archived station listings
against the real directory, every accepted public district with schools outside
the station's counties kept them within 47 km of its schools inside
(``"Titusville Area School District"``, ``"Governor Wentworth Regional School
District"``), while the charter networks' campuses in other cities lay 122 km to
1,100 km away (``"Arrow Academy"``, ``"Bay City Academy"``, ``"Premier High
Schools"``): a closing in one market says nothing of them. See
:meth:`NameIndex.reach`.

A station's list strays past its counties as far. Of the archived listings whose
source gives their county, 6 in 100 lie outside the station's counties (18 in
100 of WMUR's: its counties are the Boston market's, and it lists all of New
Hampshire), and 99 in 100 of those lie in a county with a record within 80 km
of one in the station's (WMUR's Coos County: 78 km). So a record of the
listing's states in a county that near is as much the listing's as its
namesake in the counties: see :meth:`NameIndex.around`.
"""
STRAY_SHARE: Final = 0.05
"""The share of a district's schools that may lie beyond :data:`REACH_KM` and leave it
whole: at most one school in twenty is a stray record, a virtual school or a
program registered to a county's district from across the state, not a network."""

ALTERNATE_CREDIT: Final = 0.9
"""The share of its weight a listing's word earns against a record's other spelling of
the same abbreviation (:data:`~snowlight.match.lexicon.ALTERNATE_SPELLINGS`):
``"Eagle Mt. Saginaw ISD"`` reads Mount where NCES's ``"EAGLE MT-SAGINAW ISD"``
reads Mountain, and ``"Mt. View Elementary"`` may be ``"Mountain View
Elementary"``. Short of a full match, so a record spelled as the listing wins."""
FUZZY_CUTOFF: Final = 88.0
FUZZY_MIN_LENGTH: Final = 5
FUZZY_LIMIT: Final = 3
MIN_DICE: Final = 0.6
"""Candidates are only sought among records that could reach this Dice score.

Every penalty is a factor at most 1, so a record below it scores below it; the
decisions only look at scores near the threshold (0.85) less the margin (0.10).
"""
_NOTHING: Final[list[int]] = []
_GIVEN_STEMS: Final = frozenset(stem(name) for name in GIVEN_NAMES)
"""Given names (:data:`~snowlight.match.forenames.GIVEN_NAMES`) as a name's tokens spell
them (``charle`` for ``Charles``)."""
_WHOLE: Final = (1.0, 1.0)
_NONE: Final = (0.0, 0.0)
_WORDS: Final = re.compile(r"[a-z0-9]+")
_EARTH_RADIUS_KM: Final = 6371.0088
_KM_PER_DEGREE: Final = math.pi * _EARTH_RADIUS_KM / 180.0
_POLAR: Final = 89.0
CELL_DEGREES: Final = 0.2
"""The grid a market's neighbours are measured on, in degrees (about 22 km north to
south): see :meth:`NameIndex.around`."""


@dataclass(frozen=True, slots=True)
class Scored:
    """A candidate record and how well its name fits a listing.

    Attributes:
        index: the record's position in :attr:`NameIndex.records`.
        score: 0-1 after every penalty; candidates are ranked by it.
        plausibility: 0-1, the score without the penalties for details the
            listing merely leaves out (a level, a number, a town). A runner-up is
            measured by it: ``"St. Mary's School"`` may well mean ``"St. Mary's
            Middle School"``, so that name competes at full strength.
    """

    index: int
    score: float
    plausibility: float


@dataclass(frozen=True, slots=True)
class Scope:
    """Where to look for a listing's record.

    Attributes:
        states: USPS codes; only records in them are candidates.
        counties: 5-digit FIPS codes; a school must lie in one, a district touch one.
        allowed: record positions the candidate must be among (a district's schools).
        city: a :func:`city_key` the record's city must have.
        kinds: ``"district"``, ``"school"`` or both.
        entity: an entity number the listing gives (``"4192"``): when a record of
            the name carries it, only such records are candidates
            (:meth:`NameIndex.entity_of`).
        home: the listing's own counties when ``counties`` reaches past them (a
            listing read again with the counties around its market's); ``None``
            when ``counties`` are its own. The search never reads it: only a tie
            between names does, which a point may break only when every other
            name lies outside them (see :attr:`market`).
    """

    states: frozenset[str]
    counties: frozenset[str] | None = None
    allowed: frozenset[int] | None = None
    city: str | None = None
    kinds: tuple[str, ...] = ("district", "school")
    entity: str | None = None
    home: frozenset[str] | None = None

    @property
    def market(self) -> frozenset[str] | None:
        """The listing's own counties, :attr:`home` or :attr:`counties`; ``None``: whole states."""
        return self.home if self.home is not None else self.counties


@dataclass(frozen=True, slots=True)
class Reach:
    """Where a district's schools lie against a market's counties: see :meth:`NameIndex.reach`.

    Attributes:
        inside: positions of its schools in the counties.
        outside: how many of its schools lie outside them.
        beyond: positions of the schools outside that lie farther than the reach
            from every school inside (from its office when none inside has a place).
        schools: how many schools it has.
        school_named: its own name reads as one school's (``"Premier High
            Schools"``, ``"Arrow Academy"``, see :attr:`NameForm.school_named`).
    """

    inside: tuple[int, ...]
    outside: int
    beyond: tuple[int, ...]
    schools: int
    school_named: bool

    def whole(self, stray_share: float = STRAY_SHARE) -> bool:
        """True when a listing in the market may name the whole district.

        Not when its name is one school's and it has several, some outside the
        market (a single school's listing names the campus there), nor when
        more than ``stray_share`` of its schools lie beyond the reach (a
        network: one market's closing is not its other cities'). A district
        that straddles the market's edge with its schools near one another is
        whole.
        """
        if not self.outside:
            return True
        if self.school_named and self.schools > 1:
            return False
        return len(self.beyond) <= stray_share * self.schools


@dataclass(frozen=True, slots=True)
class _Variant:
    """A second name a district is known by, read as a district's name, and its weight."""

    form: NameForm
    total: float


@dataclass(frozen=True, slots=True)
class _Query:
    """One reading of a listing, weighted for scoring."""

    form: NameForm
    weights: dict[str, float]
    total: float
    fuzzy: dict[str, tuple[tuple[str, float], ...]]
    affiliations: frozenset[str]
    prefix: tuple[str, ...]
    types: frozenset[str]
    """The :data:`~snowlight.match.lexicon.TYPE_NOUNS` the listing says."""
    known: tuple[str, ...]
    """The listing's words some record in its states carries (or a close spelling of)."""
    said: frozenset[str]
    """The listing's words and the close spellings they are read as (``"montesori"``
    is ``"montessori"``)."""
    joined: tuple[str, ...] = ()
    """The listing's runs of single letters run together (``fc`` for ``"F.C. Boyd"``),
    that a record may write as one word (``"FC BOYD"``); see :meth:`NameIndex._dice`."""


def _prefix(tokens: Sequence[str], weights: Mapping[str, float], total: float) -> list[str]:
    """The heaviest of ``tokens`` (sorted heaviest first) a record must share one of to
    reach :data:`MIN_DICE` against a listing whose words weigh ``total``: see
    :meth:`NameIndex._candidates`."""
    needed = MIN_DICE * total / (2.0 - MIN_DICE)
    remaining = sum(weights[token] for token in tokens)
    prefix: list[str] = []
    for token in tokens:
        if remaining < needed:
            break
        prefix.append(token)
        remaining -= weights[token]
    return prefix


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in kilometres between two ``(lat, lon)`` points."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


def city_key(city: str) -> str:
    """Return a city name folded for comparison (``"St. Louis"`` and ``"SAINT LOUIS"``).

    Every word of the name counts, a level's too: ``"High Point"`` is not ``"Point"``,
    and ``"Oakridge Elementary"`` is no town ``"Oakridge"``. A letter that NCES
    writes apart where a list writes an apostrophe joins the next word: ``"O
    Fallon"`` is ``"O'Fallon"``, and ``"D Iberville"`` ``"D'Iberville"``.
    """
    form = record_form(city, district=False)
    tokens: list[str] = []
    for token in form.tokens:
        if tokens and len(tokens[-1]) == 1 and tokens[-1].isalpha():
            tokens[-1] += token
        else:
            tokens.append(token)
    words = [*tokens, *sorted(form.qualifiers), *sorted(form.levels)]
    return " ".join(words) if words else fold(city).strip()


def place_key(text: str) -> str:
    """The key of the town ``text`` names: its :func:`spelled_name`, written solid.

    ``"Coeur D Alene"`` and ``"COEUR D'ALENE"``, ``"Oak Ridge"`` and ``"Oakridge"``,
    ``"St. Marys"`` and ``"SAINT MARY'S"`` are one town however an address spells
    it. Nothing is stemmed: ``"Oak Hills"`` is not ``"Oak Hill"``, nor ``"Scott
    Valley"`` ``"Scotts Valley"``. Every word counts, as in :func:`city_key`.
    """
    town = spelled_name(text)
    key = "".join((*town.words, *sorted(town.qualifiers), *sorted(town.levels)))
    return key or "".join(fold(text).split())


def place_keys(text: str) -> frozenset[str]:
    """The :func:`place_key` of ``text``, and of it without a ``City`` it adds to a town.

    ``"Falls Church City"`` is how a closings list names Falls Church.
    """
    town = spelled_name(text)
    keys = {place_key(text)}
    if "city" in town.qualifiers and town.words:
        rest = sorted(town.qualifiers - {"city"})
        keys.add("".join((*town.words, *rest, *sorted(town.levels))))
    return frozenset(keys)


@dataclass(frozen=True, slots=True)
class Town:
    """A town records of one state lie in: see :meth:`NameIndex.towns`.

    Attributes:
        districts: the positions of the districts whose office or schools are
            there.
        counties: the counties its records lie in.
        points: where its records are.
    """

    districts: frozenset[int]
    counties: frozenset[str]
    points: tuple[tuple[float, float], ...]

    def within(self, point: tuple[float, float], reach_km: float) -> bool:
        """True when one of the town's records lies within ``reach_km`` of ``point``."""
        return any(haversine_km(point, where) <= reach_km for where in self.points)


type _Cell = tuple[int, int]
"""A cell of the grid a market's neighbours are measured on: row and column."""


def _spans(row: int, reach_km: float) -> tuple[tuple[int, int], ...]:
    """The cells whose centres lie within ``reach_km`` of the centre of a cell in ``row``.

    As ``(rows away, columns either way)``. Measured flat, with a degree of
    longitude as short as it is at whichever of the two rows lies nearer a
    pole: a cell is never left out that lies within reach.
    """
    height = CELL_DEGREES * _KM_PER_DEGREE
    rows = math.floor(reach_km / height)
    spans: list[tuple[int, int]] = []
    for step in range(-rows, rows + 1):
        rise = abs(step) * height
        polar = min(
            _POLAR, max(abs((row + 0.5) * CELL_DEGREES), abs((row + step + 0.5) * CELL_DEGREES))
        )
        width = height * math.cos(math.radians(polar))
        spans.append((step, math.floor(math.sqrt(reach_km**2 - rise**2) / width)))
    return tuple(spans)


class CountyGrid:
    """Which counties lie near a market's: where their records lie on a grid.

    The grid's cells are :data:`CELL_DEGREES` wide; a county lies in every cell
    one of its geocoded records does. Each state's cells are worked out the
    first time a market in it is asked about.
    """

    def __init__(
        self,
        records: Sequence[DirectoryRecord],
        in_state: Mapping[str, Sequence[int]] | None = None,
    ) -> None:
        """Map ``records``, whose positions ``in_state`` lists by state when given."""
        self._records = records
        if in_state is None:
            positions: dict[str, list[int]] = {}
            for i, record in enumerate(records):
                positions.setdefault(record.state, []).append(i)
            in_state = positions
        self._in_state = in_state
        self._grids: dict[str, dict[_Cell, frozenset[str]]] = {}
        self._cells_of: dict[str, frozenset[_Cell]] = {}
        self._spans: dict[tuple[int, float], tuple[tuple[int, int], ...]] = {}
        self._around: dict[tuple[frozenset[str], frozenset[str], float], frozenset[str]] = {}

    def around(
        self, counties: Collection[str], states: Iterable[str], *, reach_km: float = REACH_KM
    ) -> frozenset[str]:
        """The counties of ``states`` just past ``counties``: a market's neighbours.

        Those outside ``counties`` with a record within ``reach_km`` of a record
        in them (:data:`REACH_KM`): WMUR's counties are the Boston market's, and
        its list names schools of New Hampshire's Grafton and Coos counties
        beside them. Measured between the cells the records lie in, centre to
        centre, so a county a little farther may join, one a little nearer may
        not (on the station markets of the real directory, 2 in 100 of the
        counties within 80 km are left out, all beyond 57 km, and 5 in 100 more
        join, from 80 km to 98 km). A county none of whose records has a place
        is never one: only a place the directory gives puts it near.
        """
        market = frozenset(counties)
        wanted = frozenset(states)
        key = (market, wanted, reach_km)
        found = self._around.get(key)
        if found is not None:
            return found
        grids = [self._grid(state) for state in sorted(wanted)]
        if not market <= self._cells_of.keys():
            # A market county of a state the listing is not searched in.
            for state in sorted(self._in_state):
                self._grid(state)
        cells = set[_Cell]().union(*(self._cells_of.get(county, ()) for county in market))
        near: set[str] = set()
        for row, column in cells:
            spans = self._spans.get((row, reach_km))
            if spans is None:
                spans = self._spans[row, reach_km] = _spans(row, reach_km)
            for step, width in spans:
                for across in range(column - width, column + width + 1):
                    for grid in grids:
                        held = grid.get((row + step, across))
                        if held is not None:
                            near |= held
        found = self._around[key] = frozenset(near - market)
        return found

    def _grid(self, state: str) -> dict[_Cell, frozenset[str]]:
        """The counties of ``state`` whose records lie in each cell."""
        grid = self._grids.get(state)
        if grid is not None:
            return grid
        held: dict[_Cell, set[str]] = {}
        cells: dict[str, set[_Cell]] = {}
        for i in self._in_state.get(state, ()):
            record = self._records[i]
            county, lat, lon = record.county_fips, record.lat, record.lon
            if county is None or lat is None or lon is None:
                continue
            cell = (math.floor(lat / CELL_DEGREES), math.floor(lon / CELL_DEGREES))
            held.setdefault(cell, set()).add(county)
            cells.setdefault(county, set()).add(cell)
        grid = self._grids[state] = {cell: frozenset(found) for cell, found in held.items()}
        for county, found in cells.items():
            # A county's code on records of two states (a school across the line).
            self._cells_of[county] = self._cells_of.get(county, frozenset()).union(found)
        return grid


@contextmanager
def _no_cyclic_gc() -> Iterator[None]:
    """Pause the cyclic garbage collector while a bulk build allocates.

    Building the index allocates hundreds of thousands of small containers and
    no reference cycles; left on, the collector rescans them over and over and
    the build takes nearly twice as long. Only the collector's on/off state is
    touched, and it is restored when the build ends, even on an error. After a
    build that succeeds, one full collection runs.
    """
    enabled = gc.isenabled()
    gc.disable()
    try:
        yield
    finally:
        if enabled:
            gc.enable()
    # The collector sweeps every object the build made once, the first time it
    # runs in full; do that now, as part of the build, rather than in the middle
    # of the first thousand matches.
    gc.collect()


def _is_weak(token: str) -> bool:
    return len(token) == 1 or token in _WEAK_TOKENS


def _second_form(second: str, base: str) -> NameForm:
    """A district's second name read as a district's name, with its own name's kind.

    The levels, numbers and place qualifiers of the district's own name are the
    second name's too: ``"Edison Local (formerly Berlin-Milan)"`` is
    ``"Berlin-Milan Local"``.
    """
    form = record_form(second, district=True)
    own = record_form(base, district=True)
    return form._replace(
        levels=form.levels | own.levels,
        qualifiers=form.qualifiers | own.qualifiers,
        numbers=form.numbers | own.numbers,
        implied=form.implied | own.implied,
    )


def _says_exactly(form: NameForm, other: NameForm, *, forgive: bool = False) -> bool:
    """True when the name ``other`` says what ``form`` says, and nothing more: see
    :meth:`NameIndex.says_exactly`."""
    if form.token_set != other.token_set and not (form.compact and form.compact == other.compact):
        return False
    if (form.plurals or other.plurals) and plurals_differ(form, other):
        return False
    said = form.qualifiers
    theirs = other.qualifiers | (form.qualifiers & other.implied)
    if forgive:
        said = said - lexicon.MUNICIPAL_QUALIFIERS
        theirs = theirs - lexicon.MUNICIPAL_QUALIFIERS
    return levels_said(form.levels, other) and form.numbers == other.numbers and said == theirs


def plural_words(form: NameForm, other: NameForm) -> frozenset[str]:
    """The tokens both names share that one writes with a trailing ``s`` and the other not.

    See :data:`PLURAL_DIFFERS`: ``park`` for ``"Parks"`` and ``"Park"``. Not
    ``king`` for ``"Kings"`` and ``"King's"`` (a possessive written without its
    apostrophe), nor a saint's ``"Marys"`` (never in
    :attr:`~snowlight.match.normalize.NameForm.plurals`), nor any word of a saint's
    or a devotion's name, which is written either way (``"Sacred Hearts"``), nor a
    word that says a school's kind (:data:`~snowlight.match.lexicon.LOOSE_PLURALS`:
    ``"Arts and Sciences"``).
    """
    if (not form.plurals and not other.plurals) or form.devoted or other.devoted:
        # A saint's or a devotion's name is written either way ("Sacred Hearts",
        # "Guardian Angel").
        return _EMPTY
    shared = (form.token_set & other.token_set) - lexicon.LOOSE_PLURALS
    return frozenset(
        token
        for token in form.plurals
        if token in shared and token not in other.plurals and token not in other.possessives
    ).union(
        token
        for token in other.plurals
        if token in shared and token not in form.plurals and token not in form.possessives
    )


def plurals_differ(form: NameForm, other: NameForm) -> bool:
    """True when a word both names share is written with a trailing ``s`` in one only."""
    return bool(plural_words(form, other))


def levels_said(levels: frozenset[str], other: NameForm) -> bool:
    """True when the name ``other`` says the school levels ``levels``, and no other.

    A school whose name says no level says the levels its grades are
    (:attr:`~snowlight.match.normalize.NameForm.grades`,
    :data:`~snowlight.match.grades.Fit.FITS`): NCES names Massachusetts's K-5
    ``"Lincoln Elementary School"`` ``"Lincoln"`` and a PK-8 parish school
    ``"ST JOSEPH SCHOOL"``, so ``"Lincoln Elementary"`` and ``"St. Joseph
    Elementary"`` say their names as much as those of the schools whose names
    spell the level. Not a K-12 school, which is more than an elementary school.
    """
    if levels == other.levels:
        return True
    return (
        bool(levels)
        and not other.levels
        and other.grades is not None
        and fit(levels, other.grades) is Fit.FITS
    )


def _levels_factor(
    listing: frozenset[str], candidate: NameForm, *, school: bool
) -> tuple[float, float]:
    """``(score factor, plausibility factor)`` for the school levels named.

    Levels both names say must agree. A level only the record's name says the
    listing may leave out (:data:`LEVEL_ONLY_CANDIDATE`). A level only the
    listing says costs a district (:data:`LEVEL_ONLY_LISTING`); a ``school``
    whose name says none is of the level its grades are
    (:func:`~snowlight.match.grades.fit`, :data:`_GRADES_FACTORS`): NCES often
    leaves the word out, so ``"Devonshire Elementary"`` names the K-5
    ``"Devonshire School"`` as surely as the K-5 ``"Devonshire Elem School"``
    a town away, and a listing of it names neither alone. A school of other
    grades (a 6-8 ``"Devonshire School"``) is ruled out as a school whose name
    says another level is.
    """
    theirs = candidate.levels
    if listing == theirs:
        return (1.0, 1.0)
    if listing and theirs:
        factor = LEVELS_OVERLAP if listing & theirs else LEVELS_DIFFER
        return (factor, factor)
    if theirs:
        return (LEVEL_ONLY_CANDIDATE, 1.0)
    if not school:
        return (LEVEL_ONLY_LISTING, LEVEL_ONLY_LISTING)
    return _GRADES_FACTORS[fit(listing, candidate.grades)]


def _numbers_factor(
    listing: frozenset[str], candidate: frozenset[str], *, district: bool
) -> tuple[float, float]:
    """``(score factor, plausibility factor)`` for the numbers named.

    A district's number is a legal designation its NCES name sometimes leaves
    out (``"FORT ZUMWALT SCHOOL DISTRICT"`` for Fort Zumwalt R-II), so a listing's
    number costs a district less than a school.
    """
    if listing == candidate:
        return (1.0, 1.0)
    if listing and candidate:
        factor = NUMBERS_OVERLAP if listing & candidate else NUMBERS_DIFFER
        return (factor, factor)
    if candidate:
        return (NUMBER_ONLY_CANDIDATE, 1.0)
    factor = NUMBER_ONLY_LISTING_DISTRICT if district else NUMBER_ONLY_LISTING
    return (factor, factor)


def _listing_numbers_factor(
    listing: NameForm, candidate: NameForm, *, district: bool, code_match: bool
) -> tuple[float, float]:
    """:func:`_numbers_factor`, where a district's code or number names the record.

    A code the record carries accounts for the listing's numbers; so does a
    district's number beside a school whose own name has none (``"RSU 13
    Oceanside High School"``, ``"USD 320 Wamego High School"``).
    """
    if code_match:
        return (1.0, 1.0)
    if (
        not district
        and (listing.district_numbers or listing.codes)
        and not candidate.numbers
        and listing.numbers <= listing.context_numbers
    ):
        return (1.0, 1.0)
    return _numbers_factor(listing.numbers, candidate.numbers, district=district)


def _qualifier_factor(  # noqa: PLR0913 - the qualifiers, and how to read them
    listing: frozenset[str],
    candidate: frozenset[str],
    implied: frozenset[str],
    *,
    numbered: bool = False,
    forgive: bool = False,
    school: bool = False,
) -> tuple[float, float]:
    """``(score factor, plausibility factor)`` for the place qualifiers named.

    A qualifier the candidate's name ``implied`` counts as named when the
    listing names it, and as left out by nobody when it does not. ``numbered``:
    the candidate is a district whose number the listing gives, so a county
    qualifier it leaves out costs little (:data:`COUNTY_LEFT_OUT_NUMBERED`).
    A ``Township`` the listing leaves out costs as a county does
    (:data:`TOWNSHIP_LEFT_OUT`), but not its plausibility; a municipal
    qualifier (:data:`~snowlight.match.lexicon.MUNICIPAL_QUALIFIERS`) the
    listing says and the candidate does not costs as any other it does not
    find. With ``forgive``, municipal words are set aside: when only one side
    says one and no other record in scope shares the rest of the name, it costs
    nothing (``"Bensalem School District"`` for ``"Bensalem Township SD"``,
    ``"Murfreesboro City Schools"`` for ``"Murfreesboro"``; see
    :meth:`NameIndex.search`). A ``school``'s kind of place the listing leaves out
    costs as a township's does (:data:`PLACE_LEFT_OUT`).
    """
    if implied:
        candidate |= listing & implied
    if forgive:
        listing = listing - lexicon.MUNICIPAL_QUALIFIERS
        candidate = candidate - lexicon.MUNICIPAL_QUALIFIERS
    if listing == candidate:
        return (1.0, 1.0)
    unfound = listing - candidate
    if not unfound:
        factor = 1.0
    elif unfound <= lexicon.SOFT_QUALIFIERS:
        factor = SOFT_QUALIFIER_NOT_FOUND
    else:
        factor = QUALIFIER_NOT_FOUND
    left_out = candidate - listing
    if left_out & lexicon.COUNTY_LEVEL_QUALIFIERS:
        factor *= COUNTY_LEFT_OUT_NUMBERED if numbered else COUNTY_LEFT_OUT
        return (factor, factor)
    if _TOWNSHIP in left_out:
        return (factor * (COUNTY_LEFT_OUT_NUMBERED if numbered else TOWNSHIP_LEFT_OUT), factor)
    if school and not left_out.isdisjoint(lexicon.PLACE_KINDS):
        return (factor * PLACE_LEFT_OUT, factor)
    if left_out:
        return (factor * TOWN_LEFT_OUT, factor)
    return (factor, factor)


def _place_word_not_said(listing: NameForm, candidate: NameForm) -> bool:
    """True when one name holds a place word as its own word that the other never says.

    See :data:`PLACE_WORD_NOT_SAID`. Said as a qualifier counts as said: ``"Kid
    City"`` says the ``City`` of ``"Kid City Academy"``, whatever else it leaves out.
    """
    ours = listing.token_set & _PLACE_WORDS
    theirs = candidate.token_set & _PLACE_WORDS
    if not (ours or theirs):
        return False
    return not (
        theirs <= listing.token_set | listing.qualifiers
        and ours <= candidate.token_set | candidate.qualifiers | candidate.implied
    )


def municipal_one_sided(listing: frozenset[str], candidate: frozenset[str]) -> bool:
    """True when only one of two names says a municipal qualifier (``City``, ``Township`` ...).

    ``"Murfreesboro City Schools"`` and ``"Murfreesboro"``, ``"Bensalem School
    District"`` and ``"Bensalem Township SD"``; not ``"Union City"`` and ``"Union
    Township"``, which both say one, and differ.
    """
    municipal = lexicon.MUNICIPAL_QUALIFIERS
    return listing.isdisjoint(municipal) != candidate.isdisjoint(municipal)


def kind_factor(listing: NameForm, candidate: NameForm, *, district: bool) -> float:
    """How well a candidate's kind fits what the listing's words say it is.

    A level word does not rule out a district whose own name carries the same
    level: California and Montana name districts ``"Fortuna Elementary"`` and
    ``"Helmville Elem"``. When the listing also says ``School`` such a district
    still fits, a little less well than a school of that name. The same holds
    for a district whose own name carries the noun that makes the listing read
    as one school (``Center``, ``Academy``, ``Charter``): Pennsylvania's career
    and technology centers are districts of several campuses. A group of
    private schools (``"Springfield Catholic Schools"``) is not one school of a
    level (``"Springfield Catholic High School"``), though it may include it.
    A listing that ends ``Public School`` fits a record whose name ends so best,
    then any district (:data:`PUBLIC_SCHOOL_DISTRICT`), then other schools
    (:data:`PUBLIC_SCHOOL_OTHER`). A listing whose words say district fits a
    district named as one school (``"St. Paul City School"``) a little less well
    than a town's system (:data:`ONE_SCHOOL_DISTRICT`).
    """
    hint = listing.hint
    if hint is Level.DISTRICT:
        if not district:
            return WRONG_KIND
        # A charter school's own district is named as the school.
        return ONE_SCHOOL_DISTRICT if candidate.one_school else 1.0
    if hint is Level.SCHOOL:
        return _district_named_as_school(listing, candidate) if district else 1.0
    return _either_kind(listing, candidate, district=district)


def _either_kind(listing: NameForm, candidate: NameForm, *, district: bool) -> float:
    """:func:`kind_factor` for a listing whose words may name a district or a school."""
    if listing.public_school:
        if district:
            return 1.0 if candidate.public_school else PUBLIC_SCHOOL_DISTRICT
        return 1.0 if candidate.public_school else PUBLIC_SCHOOL_OTHER
    if district:
        return 1.0
    if listing.system:
        return ONE_OF_A_SYSTEM if candidate.levels else BARE_NAME_SCHOOL
    if (
        candidate.levels
        and not _PLACE_QUALIFIERS.isdisjoint(listing.qualifiers)
        and not (listing.names_kind or listing.affiliations)
    ):
        return PLACE_NOT_A_SCHOOL
    return BARE_NAME_SCHOOL


def _district_named_as_school(listing: NameForm, candidate: NameForm) -> float:
    """:func:`kind_factor` of a district for a listing whose words say one school.

    A district named as one school fits as well as a district of that level or
    noun when its words are the listing's, whatever they are: ``"Marie H.
    Katzenbach School for the Deaf"`` is a state school's district of two
    schools. Not a district whose name says it is one (``"Oakdale School
    District"`` for ``"Oakdale School"``).
    """
    if candidate.levels and candidate.levels == listing.levels:
        return LEVEL_NAMED_DISTRICT if listing.says_school else 1.0
    if candidate.levels == listing.levels and (
        not _OWN_SCHOOL_NOUNS.isdisjoint(listing.token_set & candidate.token_set)
        or (candidate.school_named and candidate.token_set == listing.token_set)
    ):
        return LEVEL_NAMED_DISTRICT
    return WRONG_KIND


class NameIndex:
    """Normalized names, word weights and per-state lookups for a :class:`Directory`."""

    def __init__(self, directory: Directory) -> None:
        with _no_cyclic_gc():
            self._build(directory)

    def _build(self, directory: Directory) -> None:
        self.directory = directory
        self.records: tuple[DirectoryRecord, ...] = tuple(directory)
        self.is_district: list[bool] = [r.kind == "district" for r in self.records]
        self._read_brackets()
        self.forms: list[NameForm] = [
            record_form(name, district=d)
            for name, d in zip(self.names, self.is_district, strict=True)
        ]
        for i, count in self._bracketed.items():
            form = self.forms[i]
            if count < len(form.tokens):
                self.forms[i] = form._replace(forenames=count, forenames_sure=True)
        for i, record in enumerate(self.records):
            city = record.city
            if (city is not None and city[-5:].lower() == _CITY_SUFFIX) or (
                self.is_district[i] and record.state in COUNTY_DISTRICT_NAMES
            ):
                implied = self._implied(i)
                if implied:
                    form = self.forms[i]
                    self.forms[i] = form._replace(implied=form.implied | implied)
        self._grade_schools()
        self.token_sets: list[frozenset[str]] = [form.token_set for form in self.forms]
        self._index_of = {record.id: i for i, record in enumerate(self.records)}
        self._city_keys: dict[str, str] = {}
        self._place_keys: dict[str, str] = {}
        self._spelled: dict[int, tuple[str, ...]] = {}
        self._vocabularies: dict[int, tuple[frozenset[str], frozenset[str]]] = {}
        self._schools: dict[int, tuple[int, ...]] = {}
        self._county_names: dict[str, dict[tuple[str, ...], frozenset[str]]] = {}
        self._inherit_district_context()
        self._lookups()
        self._weigh()
        self.grid = CountyGrid(self.records, self._in_state)

    def _read_brackets(self) -> None:
        """Each record's name without the brackets NCES ends some names with.

        See :func:`~snowlight.match.normalize.directory_name`: ``self.names`` holds
        the names records are matched by (``"Evergreen School District"`` for
        ``"Evergreen School District (Clark)"``); a county a bracket names and a
        legal form it says (``"(CHARTER)"``) become words a listing may say or
        leave out (:meth:`optional`); a district's second name (``"(NORTH
        ROCKLAND)"``) is kept for :meth:`_weigh` to read as a district's name;
        a school's person's forenames that a bracket gave after the surname
        (``"Kennedy (John F.) Elementary"``) go before it, and are surely a
        person's (:attr:`~snowlight.match.normalize.NameForm.forenames_sure`).

        A school of no district (a private school) whose name ends with its
        campus (:data:`_CAMPUS`: ``"THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS"``)
        answers to its name without it as a second name, as a list names the
        school. Two campuses of one school then tie by that name, and a listing
        of it alone goes to the queue. A district's campuses are read as its
        schools are (a charter network's ``"QUILLON ACADEMY - HARBOR CAMPUS"``,
        see :meth:`campuses`).
        """
        self.names: list[str] = []
        self._optional: dict[int, frozenset[str]] = {}
        self._county: dict[int, tuple[frozenset[str], str | None]] = {}
        self._legal: dict[int, frozenset[str]] = {}
        self._seconds: dict[int, tuple[NameForm, ...]] = {}
        self._second_names: dict[int, tuple[str, ...]] = {}
        self._entities: dict[int, str] = {}
        self._bracketed: dict[int, int] = {}
        for i, (record, district) in enumerate(zip(self.records, self.is_district, strict=True)):
            name = record.name
            campus = None if district or record.district_id else _CAMPUS.search(name)
            if campus is not None and campus.start() > 0:
                # "THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS" is "The Pembroke Hill
                # School" too; its campus, a part of the name a list leaves out.
                base = name[: campus.start()].strip()
                self._second_names[i] = (base,)
                self._seconds[i] = (record_form(base, district=False),)
            if "(" in name:
                read = directory_name(name, district=district, county=record.county)
                name = read.base
                if read.county or read.legal:
                    self._optional[i] = read.county | read.legal
                if read.county:
                    self._county[i] = (read.county, read.county_kind)
                if read.legal:
                    self._legal[i] = read.legal
                if read.entity is not None:
                    self._entities[i] = read.entity
                if read.forenames:
                    self._bracketed[i] = read.forenames
                if read.second:
                    self._second_names[i] = (*self._second_names.get(i, ()), *read.second)
                    self._seconds[i] = (
                        *self._seconds.get(i, ()),
                        *(_second_form(second, name) for second in read.second),
                    )
            self.names.append(name)

    def _grade_schools(self) -> None:
        """Give each school's names that say no level the school's grades.

        See :attr:`~snowlight.match.normalize.NameForm.grades`: NCES's
        ``"Lincoln"``, a K-5 school, is of the level ``"Lincoln Elementary"`` says.
        A name that says a level keeps it (``"LINCOLN MIDDLE SCHOOL"``), and a
        school whose grades are unknown has none. A few hundred spans and the
        names' shared forms (:func:`~snowlight.match.normalize.record_form`) are
        read once each.
        """
        spans: dict[tuple[str | None, str | None, str | None], tuple[int, int] | None] = {}
        graded: dict[tuple[int, tuple[int, int]], NameForm] = {}
        forms = self.forms
        for i, record in enumerate(self.records):
            if self.is_district[i]:
                continue
            key = (record.grade_low, record.grade_high, record.level)
            if key in spans:
                span = spans[key]
            else:
                span = spans[key] = record.span
            if span is None:
                continue
            form = forms[i]
            if not form.levels:
                # Forms are immutable and a name's form is shared: grade it once.
                shared = (id(form), span)
                done = graded.get(shared)
                if done is None:
                    done = graded[shared] = form._replace(grades=span)
                forms[i] = done
            seconds = self._seconds.get(i)
            if seconds is not None:
                self._seconds[i] = tuple(
                    second if second.levels else second._replace(grades=span) for second in seconds
                )

    def optional(self, index: int) -> frozenset[str]:
        """Words a listing may say of record ``index`` or leave out: its county's, its legal form's.

        ``clark`` for ``"Evergreen School District (Clark)"``, ``charter`` for
        ``"COMANCHE ACADEMY (CHARTER)"``.
        """
        return self._optional.get(index, _EMPTY)

    def entity_of(self, index: int) -> str | None:
        """The entity number of record ``index``'s district (itself, for a district), if any."""
        if not self._entities:
            return None
        owner = self.owner_of(index)
        return None if owner is None else self._entities.get(owner)

    def forms_of(self, index: int) -> tuple[NameForm, ...]:
        """Every name record ``index`` answers to: its own, then its second names."""
        seconds = self._seconds.get(index)
        return (self.forms[index],) if seconds is None else (self.forms[index], *seconds)

    def _inherit_district_context(self) -> None:
        """Each record's district codes and numbers: a district's own, a school's district's.

        ``"Oceanside High School"`` in ``"RSU 13"`` carries ``rsu 13`` and ``13``,
        so ``"RSU 13 Oceanside High School"`` names it and ``"RSU 5 Oceanside High
        School"`` does not. Also the series each state's names use.
        """
        codes: list[frozenset[str]] = [form.codes for form in self.forms]
        types: list[frozenset[str]] = [_EMPTY] * len(self.forms)
        numbers: list[frozenset[str]] = [
            form.numbers if district else _EMPTY
            for form, district in zip(self.forms, self.is_district, strict=True)
        ]
        by_id = {record.id: i for i, record in enumerate(self.records) if self.is_district[i]}
        # The directory checked that every school's district is listed.
        owners = [
            None if self.is_district[i] or record.district_id is None else by_id[record.district_id]
            for i, record in enumerate(self.records)
        ]
        sizes = Counter(owners)
        for i, owner in enumerate(owners):
            if owner is None:
                continue
            owner_form = self.forms[owner]
            if owner_form.codes:
                codes[i] = codes[i] | owner_form.codes
            numbers[i] = owner_form.numbers
            form = self.forms[i]
            # "OKLAHOMA YOUTH ACADEMY (CHARTER)" says its schools are charter
            # schools, which a listing may say.
            legal = self._legal.get(owner)
            if legal is not None:
                self._optional[i] = self._optional.get(i, _EMPTY) | legal
            owner_types = (owner_form.token_set | (legal or _EMPTY)) & _TYPE_NOUNS
            if (
                owner_form.token_set
                and owner_form.token_set <= form.token_set
                and sizes[owner] == 1
            ):
                # A district of one school, named for it: a charter school.
                types[i] = owner_types | {"charter"}
            elif owner_types:
                types[i] = owner_types
            if (
                "regional" in form.qualifiers
                and "regional" not in owner_form.qualifiers | owner_form.implied
                and owner_form.token_set
                and owner_form.token_set <= form.token_set
            ):
                # Massachusetts names "Wachusett Regional" "Wachusett", and its
                # high school "Wachusett Regional High": the district is regional.
                self.forms[owner] = owner_form._replace(implied=owner_form.implied | {"regional"})
        self.context_codes = codes
        self.context_numbers = numbers
        self.district_types = types
        """The type nouns a school's district's name gives it (``charter`` for a
        district of one school named for it)."""
        series: dict[str, set[str]] = {}
        for owner in by_id.values():
            for code in self.forms[owner].codes:
                series.setdefault(self.records[owner].state, set()).add(code.split(" ", 1)[0])
        self._series = {state: frozenset(found) for state, found in series.items()}

    def _implied(self, index: int) -> frozenset[str]:
        """Place qualifiers a record's name implies through where it is.

        ``county`` for a South Carolina, Florida or Nevada district named by its
        county alone (:data:`COUNTY_DISTRICT_NAMES`). ``city`` for a record whose name is its
        city's name without ``City``: Utah's ``"Salt Lake District"`` lies in
        Salt Lake City, and closings lists call it ``"Salt Lake City School
        District"``. Only a record whose words are the city's words qualifies,
        so ``"Carson Middle School"`` in Carson City does, ``"Carson Valley
        Middle School"`` does not.
        """
        record = self.records[index]
        form = self.forms[index]
        implied: set[str] = set()
        pattern = COUNTY_DISTRICT_NAMES.get(record.state)
        if self.is_district[index] and pattern is not None and pattern.fullmatch(self.names[index]):
            implied.add("county")
        city = record.city
        if (
            city is not None
            and form.tokens
            and "city" not in form.qualifiers
            and city_key(city) == " ".join((*form.tokens, "city"))
        ):
            implied.add("city")
        return frozenset(implied)

    def _lookups(self) -> None:
        """Per-state posting lists, compact spellings, numbers and records; district counties."""
        self._postings: dict[str, dict[str, list[int]]] = {}
        self._compact: dict[str, dict[str, list[int]]] = {}
        self._numbers: dict[str, dict[str, list[int]]] = {}
        self._in_state: dict[str, list[int]] = {}
        self._towns: dict[str, dict[str, Town]] = {}
        counties: dict[str, set[str]] = {}
        for i, (record, form) in enumerate(zip(self.records, self.forms, strict=True)):
            postings = self._postings.get(record.state)
            if postings is None:
                postings = self._postings[record.state] = {}
                self._compact[record.state] = {}
                self._numbers[record.state] = {}
                self._in_state[record.state] = [i]
            else:
                self._in_state[record.state].append(i)
            for token in self._words(i):
                posting = postings.get(token)
                if posting is None:
                    postings[token] = [i]
                else:
                    posting.append(i)
            if form.compact:
                self._compact[record.state].setdefault(form.compact, []).append(i)
            for second in self._seconds.get(i, ()):
                if second.compact and second.compact != form.compact:
                    self._compact[record.state].setdefault(second.compact, []).append(i)
            for number in form.numbers:
                self._numbers[record.state].setdefault(number, []).append(i)
            owner = record.id if self.is_district[i] else record.district_id
            if owner is not None and record.county_fips is not None:
                counties.setdefault(owner, set()).add(record.county_fips)
        self._district_counties = {key: frozenset(value) for key, value in counties.items()}
        self._vocabulary: dict[str, list[str]] = {
            state: sorted(t for t in postings if len(t) >= FUZZY_MIN_LENGTH - 1 and not _is_weak(t))
            for state, postings in self._postings.items()
        }

    def _words(self, index: int) -> frozenset[str]:
        """Every word record ``index`` answers to: its name's, its second names', its optional."""
        tokens = self.token_sets[index]
        if index not in self._optional and index not in self._seconds:
            return tokens
        more = [form.token_set for form in self._seconds.get(index, ())]
        return tokens.union(self.optional(index), *more)

    def _weigh(self) -> None:
        """Word weights (``1 + ln(N / df)``) and each record's total weight."""
        document_frequency: Counter[str] = Counter()
        for tokens in self.token_sets:
            document_frequency.update(tokens)
        for i in self._optional.keys() | self._seconds.keys():
            document_frequency.update(self._words(i) - self.token_sets[i])
        size = max(len(self.records), 1)
        self.max_weight = 1.0 + math.log(size)
        self.weight: dict[str, float] = {
            token: lexicon.WEAK_WEIGHT if _is_weak(token) else 1.0 + math.log(size / count)
            for token, count in document_frequency.items()
        }
        totals: dict[frozenset[str], float] = {}
        for tokens in self.token_sets:
            if tokens not in totals:
                totals[tokens] = sum(self.weight[t] for t in tokens)
        self.totals: list[float] = [totals[tokens] for tokens in self.token_sets]
        self._variants: dict[int, tuple[_Variant, ...]] = {
            i: tuple(
                _Variant(form, sum(self.weight[t] for t in form.token_set)) for form in seconds
            )
            for i, seconds in self._seconds.items()
        }

    def index_of(self, record_id: str) -> int:
        """Return the position of ``record_id``; raises ``KeyError`` when unknown."""
        return self._index_of[record_id]

    def district_counties(self, district_id: str) -> frozenset[str]:
        """Counties a district touches: its office's and every one of its schools'."""
        return self._district_counties.get(district_id, frozenset())

    def city_of(self, index: int) -> str | None:
        """The comparison key of the record's city, or ``None`` when it has none."""
        city = self.records[index].city
        if city is None:
            return None
        key = self._city_keys.get(city)
        if key is None:
            key = self._city_keys[city] = city_key(city)
        return key

    def in_counties(self, index: int, counties: Collection[str]) -> bool:
        """True when the record lies in (a district: touches) one of ``counties``."""
        record = self.records[index]
        if record.kind == "district":
            return not self.district_counties(record.id).isdisjoint(counties)
        return record.county_fips in counties

    def around(
        self, counties: Collection[str], states: Iterable[str], *, reach_km: float = REACH_KM
    ) -> frozenset[str]:
        """The counties of ``states`` just past ``counties``: see :meth:`CountyGrid.around`."""
        return self.grid.around(counties, states, reach_km=reach_km)

    def schools_of(self, index: int) -> tuple[int, ...]:
        """The positions of district ``index``'s schools, in directory order."""
        found = self._schools.get(index)
        if found is None:
            record = self.records[index]
            found = tuple(self._index_of[s.id] for s in self.directory.schools_of(record.id))
            self._schools[index] = found
        return found

    def reach(self, index: int, counties: Collection[str], *, reach_km: float = REACH_KM) -> Reach:
        """Where district ``index``'s schools lie against ``counties`` (see :class:`Reach`).

        A school outside the counties lies beyond the reach when it is more than
        ``reach_km`` from every one of the district's schools inside them, or
        from the district's office when none inside has a place. A school without
        coordinates, or a district with nothing to measure from, is never beyond
        it: only a distance the directory gives can rule a district out. Nor is
        a virtual school (``"Tennessee Connections Academy Johnson County 4-8"``,
        which NCES places at its operator's office across the state), which a
        county's district runs for pupils who learn from home.
        """
        schools = self.schools_of(index)
        inside: list[int] = []
        outside: list[int] = []
        for position in schools:
            (inside if self.records[position].county_fips in counties else outside).append(position)
        beyond: list[int] = []
        if outside:
            anchors = [p for p in (self.records[i].point for i in inside) if p is not None]
            office = self.records[index].point
            if not anchors and office is not None:
                anchors.append(office)
            for position in outside:
                point = self.records[position].point
                if (
                    point is not None
                    and anchors
                    and not self._is_virtual(position)
                    and all(haversine_km(point, anchor) > reach_km for anchor in anchors)
                ):
                    beyond.append(position)
        return Reach(
            inside=tuple(inside),
            outside=len(outside),
            beyond=tuple(beyond),
            schools=len(schools),
            school_named=self.forms[index].school_named,
        )

    def _is_virtual(self, index: int) -> bool:
        """True when school ``index``'s name says it teaches online (:data:`lexicon.VIRTUAL`)."""
        words = _WORDS.findall(fold(self.names[index]))
        return any(
            tuple(words[i : i + len(phrase)]) == phrase
            for i in range(len(words))
            for phrase in lexicon.VIRTUAL
        )

    def campuses(
        self, forms: ListingForms, positions: Sequence[int], states: Collection[str]
    ) -> list[tuple[Scored, bool]]:
        """Score schools ``positions`` of one district for a listing; say which it fits.

        The listing named the district, and these are its schools in the
        listing's market (:meth:`reach`). One fits when it says, or its town
        does, every word of the listing but its designators (a close spelling
        counts), a level the listing says, and any number the listing says that
        is not its district's: ``"Premier High School"`` fits ``"Premier H S of Tyler"``
        and ``"Premier High School - Longview"``, ``"Premier High School
        Tyler"`` only the first, and ``"IDEA Academy"`` not ``"IDEA College
        Prep"``. Its score is its name's own, which its town's words lower.
        """
        query = self._query(forms.school, states)
        found: list[tuple[Scored, bool]] = []
        for position in positions:
            score, plausibility = self._score(query, position)
            found.append((Scored(position, score, plausibility), self._fits(query, position)))
        return found

    def _fits(self, query: _Query, index: int) -> bool:
        """True when school ``index`` says everything the listing says: see :meth:`campuses`."""
        form = query.form
        if self.levels_apart(form.levels, index):
            return False
        other = self.forms[index]
        if form.numbers - other.numbers - self.context_numbers[index]:
            return False
        town = self.city_of(index)
        words = self.token_sets[index] | frozenset(town.split()) if town else self.token_sets[index]
        return all(
            token in words
            or _is_weak(token)
            or token in _KIND_TOKENS
            or any(word in words for word, _credit in query.fuzzy.get(token, ()))
            for token in form.token_set
        )

    def _towns_of(self, state: str) -> dict[str, Town]:
        """Every town a record in ``state`` lies in (:meth:`place_of`): see :class:`Town`.

        A town's districts are those whose office or schools are there (their
        positions): ``"Neptune"`` is the township's district's town, not
        ``"Neptune City School District"``'s next door. A town the directory
        knows only by private schools' addresses has none. Worked out the first
        time a state is asked about, so the index build pays nothing for it.
        """
        towns = self._towns.get(state)
        if towns is not None:
            return towns
        districts: dict[str, set[int]] = {}
        counties: dict[str, set[str]] = {}
        points: dict[str, list[tuple[float, float]]] = {}
        for i in self._in_state.get(state, _NOTHING):
            key = self.place_of(i)
            if key is None:
                continue
            owners = districts.get(key)
            if owners is None:
                owners = districts[key] = set()
                counties[key] = set()
                points[key] = []
            owner = self.owner_of(i)
            if owner is not None:
                owners.add(owner)
            record = self.records[i]
            if record.county_fips is not None:
                counties[key].add(record.county_fips)
            where = record.point
            if where is not None:
                points[key].append(where)
        towns = self._towns[state] = {
            key: Town(frozenset(owners), frozenset(counties[key]), tuple(points[key]))
            for key, owners in districts.items()
        }
        return towns

    def place_of(self, index: int) -> str | None:
        """The record's city as its :func:`place_key`, or ``None`` when it has none."""
        city = self.records[index].city
        if city is None:
            return None
        key = self._place_keys.get(city)
        if key is None:
            key = self._place_keys[city] = place_key(city)
        return key

    def towns(self, places: frozenset[str], states: Iterable[str]) -> dict[tuple[str, str], Town]:
        """The towns of ``places`` (:func:`place_keys`) records in ``states`` lie in.

        Keyed by state and place key (see :meth:`_towns_of`). ``"Maple Valley"``
        is a town when a school's address is there, whatever the schools named
        for it (``"Maple Valley Elementary"``, whose address is another town's).
        """
        found: dict[tuple[str, str], Town] = {}
        for state in states:
            towns = self._towns_of(state)
            for key in places:
                districts = towns.get(key)
                if districts is not None:
                    found[state, key] = districts
        return found

    def answers_to(self, index: int, said: NameForm) -> bool:
        """True when record ``index`` answers to every identifying word ``said`` says.

        A record answers to its own names' words (:meth:`_words`), its town's, its
        county's, and, for a school, what its district answers to; a district
        also to its schools' towns and the words most of its schools share
        (:meth:`_district_words`). ``"Mason Consolidated Schools (Monroe)"``: the
        district in Monroe County answers to ``monroe``. A level ``said`` says
        must be one the record's name says, when it says any
        (``"St. Margaret School (Elementary)"``), or one its grades teach
        (:meth:`levels_apart`).
        """
        if self.levels_apart(said.levels, index):
            return False
        wanted = self.identifying(said.token_set)
        known = set(self._words(index))
        record = self.records[index]
        town = self.city_of(index)
        if town:
            known.update(town.split())
        if record.county is not None:
            county = " ".join(county_words(record.county)[0])
            known.update(record_form(county, district=False).tokens)
        owner = self.owner_of(index)
        if owner is not None:
            known.update(self._district_words(owner)[0])
        return wanted <= known

    def counties_named(self, words: Sequence[str], states: Iterable[str]) -> frozenset[str]:
        """The FIPS codes of the counties of ``states`` whose own name is ``words``.

        ``words`` are folded, without the ``County`` or ``Parish`` a county's name
        ends with (``("clark",)``, ``("van", "buren")``): see
        :func:`~snowlight.match.normalize.county_words`. Only counties the
        directory names (:attr:`~snowlight.match.directory.DirectoryRecord.county`)
        are known; worked out the first time a state is asked about.
        """
        key = tuple(words)
        found: set[str] = set()
        for state in states:
            names = self._county_names.get(state)
            if names is None:
                names = self._county_names[state] = self._counties_of(state)
            found.update(names.get(key, _EMPTY))
        return frozenset(found)

    def _counties_of(self, state: str) -> dict[tuple[str, ...], frozenset[str]]:
        named: dict[tuple[str, ...], set[str]] = {}
        for i in self._in_state.get(state, _NOTHING):
            record = self.records[i]
            if record.county is not None and record.county_fips is not None:
                words = tuple(county_words(record.county)[0])
                named.setdefault(words, set()).add(record.county_fips)
        return {words: frozenset(codes) for words, codes in named.items()}

    def owner_of(self, index: int) -> int | None:
        """The position of record ``index``'s district (itself for a district), if it has one."""
        if self.is_district[index]:
            return index
        district = self.records[index].district_id
        return None if district is None else self._index_of[district]

    def levels_apart(self, levels: frozenset[str], index: int) -> bool:
        """True when record ``index`` is of none of the school levels ``levels``.

        Its name says levels and none of them (``"Lincoln Middle"`` for
        ``"Lincoln Elementary"``), or says none and it is a school whose grades
        teach none of them (a 6-8 ``"Lincoln"``, see
        :func:`~snowlight.match.grades.fit`). Nothing is apart from a listing
        that says no level, nor a record of unknown grades.
        """
        if not levels:
            return False
        other = self.forms[index]
        if other.levels:
            return levels.isdisjoint(other.levels)
        return other.grades is not None and fit(levels, other.grades) is Fit.APART

    def says_exactly(self, form: NameForm, index: int, *, forgive: bool = False) -> bool:
        """True when a name of record ``index`` says what ``form`` says, and nothing more.

        The same words (or the same words run together, ``"Oak Ridge"`` and
        ``"Oakridge"``), the same levels, numbers and place qualifiers; a
        qualifier the record's name implies counts as said when the listing says
        it. The district ``"CUMBERLAND ACADEMY"`` says exactly what the listing
        ``"Cumberland Academy"`` says; its ``"CUMBERLAND ACADEMY MIDDLE"`` says a
        level more, and ``"Paul PCS - MS"`` more than ``"Paul PCS"``. Compare a
        listing's district reading with a district, its school reading with a
        school. A district's second name counts (``"North Rockland"`` is
        ``"HAVERSTRAW-STONY POINT CSD (NORTH ROCKLAND)"``, see :meth:`forms_of`).
        ``forgive``: a municipal qualifier
        (:data:`~snowlight.match.lexicon.MUNICIPAL_QUALIFIERS`) either says is set
        aside (``"Bensalem Township SD"`` for ``"Bensalem School District"``).
        """
        return any(_says_exactly(form, other, forgive=forgive) for other in self.forms_of(index))

    def word_sets(self, index: int) -> tuple[frozenset[str], ...]:
        """The identifying words of every name record ``index`` answers to (:meth:`forms_of`)."""
        return tuple(form.token_set for form in self.forms_of(index))

    def says_beyond(self, form: NameForm, index: int) -> frozenset[str]:
        """The levels and words school ``index``'s name says beyond ``form``, bar its town's.

        Joining words and ``Campus`` or ``Center`` aside: ``"Premier H S of
        Tyler"`` in Tyler says nothing beyond ``"Premier High School"``, and
        ``"Minnesota Transitions Charter Elem"`` says ``elementary`` beyond
        ``"Minnesota Transitions Charter School"``.
        """
        other = self.forms[index]
        town = self.city_of(index)
        places = frozenset(town.split()) if town else _EMPTY
        words = (
            token
            for token in other.token_set - form.token_set
            if token not in places and token not in _CAMPUS_NOUNS and not _is_weak(token)
        )
        return frozenset(words).union(other.levels - form.levels)

    def spelled(self, index: int) -> tuple[str, ...]:
        """Record ``index``'s identifying words as its name spells them (:func:`spelled_name`)."""
        found = self._spelled.get(index)
        if found is None:
            name = self.names[index]
            found = self._spelled[index] = spelled_name(
                name, district=self.is_district[index]
            ).words
        return found

    @staticmethod
    def identifying(tokens: frozenset[str]) -> frozenset[str]:
        """``tokens`` but joining words, initials and the like (see :data:`_WEAK_TOKENS`)."""
        if not any(_is_weak(token) for token in tokens):
            return tokens
        return frozenset(token for token in tokens if not _is_weak(token))

    def says_as_spelled(self, words: tuple[str, ...], index: int) -> bool:
        """True when record ``index``'s name spells its identifying words as ``words`` do.

        Nothing stemmed: ``"Oak Hill Union Local"`` spells ``("oak", "hill")``, and
        ``"Oak Hills Local"`` does not; the same words run together count
        (``"Oak Ridge"``, ``"Oakridge"``), and joining words and the like
        (:data:`~snowlight.match.lexicon.WEAK_WORDS`: the ``Exempted`` of
        ``"Ashfields Exempted Village"``) do not. A district's second name counts.
        """
        spellings = [self.spelled(index)]
        spellings.extend(
            spelled_name(second, district=self.is_district[index]).words
            for second in self._second_names.get(index, ())
        )
        said = frozenset(w for w in words if not _is_weak(w))
        return any(
            "".join(theirs) == "".join(words)
            or frozenset(w for w in theirs if not _is_weak(w)) == said
            for theirs in spellings
        )

    def legal_words(self, index: int) -> frozenset[str]:
        """The words of record ``index``'s name that say its legal form: see :func:`legal_words`."""
        return legal_words(self.names[index])

    # -- query ---------------------------------------------------------------

    def _fuzzy(self, token: str, states: Iterable[str]) -> tuple[tuple[str, float], ...]:
        """Close spellings of an unknown ``token`` in ``states``, with their credit."""
        if len(token) < FUZZY_MIN_LENGTH or not token.isalpha():
            return ()
        best: dict[str, float] = {}
        for state in states:
            vocabulary = self._vocabulary.get(state)
            if not vocabulary:
                continue
            for word, similarity, _ in process.extract(
                token,
                vocabulary,
                scorer=fuzz.ratio,
                score_cutoff=FUZZY_CUTOFF,
                limit=FUZZY_LIMIT,
            ):
                credit = 1.0 - 2.0 * (1.0 - similarity / 100.0)
                best[word] = max(best.get(word, 0.0), credit)
        return tuple(sorted(best.items(), key=lambda item: (-item[1], item[0])))

    def _alternates(self, token: str, form: NameForm) -> tuple[tuple[str, float], ...]:
        """The other spellings of ``token`` the directory holds, with their credit.

        See :data:`~snowlight.match.lexicon.ALTERNATE_SPELLINGS`; a spelling that
        is itself one of the listing's words is that word's to match.
        """
        spellings = lexicon.ALTERNATE_SPELLINGS.get(token)
        if spellings is None:
            return ()
        return tuple(
            (word, ALTERNATE_CREDIT)
            for word in spellings
            if word in self.weight and word not in form.token_set
        )

    def _query(self, form: NameForm, states: Collection[str]) -> _Query:
        weights: dict[str, float] = {}
        fuzzy: dict[str, tuple[tuple[str, float], ...]] = {}
        known_here: list[str] = []
        for token in set(form.tokens):
            known = self.weight.get(token)
            if known is not None and any(token in self._postings.get(s, {}) for s in states):
                weights[token] = known
                known_here.append(token)
                alternates = self._alternates(token, form)
                if alternates:
                    fuzzy[token] = alternates
                continue
            # A close spelling that is itself one of the listing's words is that
            # word's to match: "Fairport Airport" is not "Fairport" twice.
            close = self._alternates(token, form) or (
                ()
                if _is_weak(token)
                else tuple(c for c in self._fuzzy(token, states) if c[0] not in form.token_set)
            )
            if close:
                fuzzy[token] = close
                weights[token] = self.weight[close[0][0]]
                known_here.append(token)
            elif known is not None:
                weights[token] = known
            else:
                weights[token] = lexicon.WEAK_WEIGHT if _is_weak(token) else self.max_weight
        total = sum(weights.values())
        # A word no record in the states carries can be shared by none, so only
        # the others are looked up; they must still weigh enough between them.
        known_here.sort(key=lambda token: (-weights[token], token))
        prefix = _prefix(known_here, weights, total)
        if form.forenames:
            # A school named for the listing's person may leave its forenames out, or
            # give only their initials (see NameIndex._person): its name need share
            # only the rest.
            forenames = frozenset(form.tokens[: form.forenames])
            rest = [token for token in known_here if token not in forenames]
            left = total - sum(weights[token] for token in forenames)
            prefix.extend(token for token in _prefix(rest, weights, left) if token not in prefix)
        return _Query(
            form=form,
            weights=weights,
            total=total,
            fuzzy=fuzzy,
            affiliations=form.affiliations,
            prefix=tuple(prefix),
            types=form.token_set & _TYPE_NOUNS,
            known=tuple(known_here),
            said=form.token_set.union(word for close in fuzzy.values() for word, _ in close)
            if fuzzy
            else form.token_set,
            joined=tuple(run for run in form.letters if run not in form.token_set),
        )

    def _candidates(self, queries: Sequence[_Query], states: Collection[str]) -> set[int]:
        """Records that could score at least :data:`MIN_DICE` against one of ``queries``.

        Prefix filtering: to reach a Dice coefficient of ``d`` a record must share
        words weighing at least ``d * W / (2 - d)`` of the listing's total ``W``.
        Taking the listing's words heaviest first, once the words not yet taken
        weigh less than that, every such record shares one of the words taken, so
        only their posting lists are read. Records with the same compact
        spelling are added too; for a name that is only a number, the records
        with that number; and for a listing that names a district by its code
        or number (``"RSU 13"``, ``"D-3 Widefield"``), the records with that
        number, since such a district's own name may share no word with it.

        When no record can reach that score, the records that share any of the
        listing's words are returned instead, so the unmatched queue still
        shows what comes closest (``"Chagrin Falls Ex. Vil. SD"`` with a word
        the directory never spells).
        """
        found: set[int] = set()
        for state in states:
            postings = self._postings.get(state)
            if postings is None:
                continue
            compact = self._compact[state]
            numbers = self._numbers[state]
            for query in queries:
                for token in query.prefix:
                    found.update(postings.get(token, _NOTHING))
                    for word, _credit in query.fuzzy.get(token, ()):
                        found.update(postings.get(word, _NOTHING))
                found.update(compact.get(query.form.compact, _NOTHING))
                if not query.prefix or query.form.district_numbers or query.form.codes:
                    for number in query.form.numbers:
                        found.update(numbers.get(number, _NOTHING))
        return found or self._sharing(queries, states)

    def _sharing(self, queries: Sequence[_Query], states: Collection[str]) -> set[int]:
        """Records in ``states`` that share any known word of ``queries``."""
        found: set[int] = set()
        for state in states:
            postings = self._postings.get(state)
            if postings is None:
                continue
            for query in queries:
                for token in query.known:
                    found.update(postings.get(token, _NOTHING))
                    for word, _credit in query.fuzzy.get(token, ()):
                        found.update(postings.get(word, _NOTHING))
        return found

    def _district_context(self, form: NameForm, index: int) -> tuple[float, bool]:
        """How the district a listing names by code or number fits record ``index``.

        Returns the factor and whether a code of the listing is one of the
        record's (its own, or its district's for a school). A code of a series
        the record's codes are of, with another number, all but rules the record
        out; so does a code of a series the state's districts are named by when
        the record carries none (``"RSU 13 Lincoln School"`` is no Lincoln School
        of a town district). A code no district in the state is named by
        (``"AOS 98"``, ``"SAU 16"``) cannot be checked. A school's district
        number (``"D-3 Widefield High School"``) must be its district's when its
        district's name has one. A school no district runs (a private school) is
        named by no district's code or number, unless its own name carries it
        (:data:`NO_DISTRICT`).
        """
        if (
            not self.is_district[index]
            and self.records[index].district_id is None
            and form.context_numbers.isdisjoint(self.forms[index].numbers)
        ):
            return (NO_DISTRICT, False)
        theirs = self.context_codes[index]
        if form.codes:
            if not form.codes.isdisjoint(theirs):
                return (1.0, True)
            if theirs:
                return (CODES_DIFFER, False)
            state_series = self._series.get(self.records[index].state, _EMPTY)
            if any(code.split(" ", 1)[0] in state_series for code in form.codes):
                return (CODE_NOT_FOUND, False)
        named = form.district_numbers
        if named and not self.is_district[index]:
            numbers = self.context_numbers[index]
            # A school whose own name carries the number ("U-32 Middle & High
            # School") is named by it, whatever its district's number.
            own = self.forms[index].numbers
            if numbers and named.isdisjoint(numbers) and named.isdisjoint(own):
                return (DISTRICT_NUMBER_DIFFERS, False)
        return (1.0, False)

    def _type_mismatch(self, types: frozenset[str], index: int) -> bool:
        """True when school ``index`` is not the kind of school the listing's ``types`` say.

        ``"St. Johnsbury Academy"`` is not ``"St. Johnsbury School"``, and
        ``"Robert Frost Charter School"`` is not the ``"Robert Frost"``
        elementary school of a city district. A school whose name says nothing
        of its kind may have lost the noun (``"Gloria Deo"`` for ``"Gloria Deo
        Academy"``), but not ``Charter``: a charter school says it, or its
        district does, or it is a district of its own (``"Naytahwaush Community
        School"``, whose district has that name). A district is never checked:
        a charter school's own district is often named without the word
        (``"Guadalupe Centers Schools"``).
        """
        missing = types - self.token_sets[index]
        if not missing:
            return False
        if self.forms[index].names_kind:
            return bool(missing - self.district_types[index])
        return _CHARTER in missing and _CHARTER not in self.district_types[index]

    def _district_words(self, index: int) -> tuple[frozenset[str], frozenset[str]]:
        """The words and place qualifiers district ``index`` answers to besides its name.

        Its own name's, its office's and its schools' towns', and the words most
        of its schools' names share (:data:`_SCHOOLS_TO_COVER`): ``"RSU 17/MSAD
        17"`` answers to ``"Oxford Hills"`` when its middle and high schools are
        ``"Oxford Hills ..."``, and to the towns its schools are in.
        """
        cached = self._vocabularies.get(index)
        if cached is not None:
            return cached
        record = self.records[index]
        form = self.forms[index]
        words: set[str] = set(self._words(index))
        qualifiers: set[str] = set(form.qualifiers | form.implied)
        towns = {record.city}
        counts: Counter[str] = Counter()
        schools = self.directory.schools_of(record.id)
        for school in schools:
            position = self._index_of[school.id]
            counts.update(self.token_sets[position])
            qualifiers.update(self.forms[position].qualifiers)
            towns.add(school.city)
        needed = min(_SCHOOLS_TO_COVER, len(schools))
        words.update(word for word, count in counts.items() if count >= needed)
        for town in towns:
            if town:
                place = record_form(town, district=False)
                words.update(place.token_set)
                qualifiers.update(place.qualifiers)
        if record.county is not None:
            # "Harrisonville Cass MO R-IX School": its county's name, without "County".
            county = " ".join(county_words(record.county)[0])
            words.update(record_form(county, district=False).token_set)
        found = (frozenset(words), frozenset(qualifiers))
        self._vocabularies[index] = found
        return found

    def _coverage(self, query: _Query, index: int) -> tuple[float, bool]:
        """How much of a listing district ``index``'s :meth:`_district_words` hold.

        The share of the listing's word weight it holds, and whether it holds the
        county or township the listing names. A town qualifier (``Area``,
        ``Regional``) is description, not identity, once a code names the district.
        """
        words, qualifiers = self._district_words(index)
        total = query.total
        held = sum(weight for token, weight in query.weights.items() if token in words)
        share = held / total if total else 1.0
        return share, query.form.qualifiers & lexicon.COUNTY_QUALIFIERS <= qualifiers

    def _directions_differ(
        self, form: NameForm, index: int, other: NameForm, *, covered: bool
    ) -> bool:
        """True when the listing and record ``index``'s name ``other`` name other directions.

        The same words run together are one name (``"North Wood"`` is
        ``"Northwood"``). A district a listing names by its code or number
        (``covered``, see :meth:`_coverage`) answers to the directions of its
        towns too (``"MSAD 60 - N. Berwick"``), but its own name's direction must
        still be said: ``"Harlan-Dixby SD 147"`` is not ``"W Harlan-Dixby PSD
        147"``.
        """
        if not covered:
            return form.directions != other.directions and form.compact != other.compact
        return not (
            other.directions <= form.directions
            and form.directions <= self._district_words(index)[0]
        )

    def _placed_by_name(self, query: _Query, index: int) -> bool:
        """True when the listing names record ``index`` by more than its town's name.

        A listing that also names the record's town (``"Cheverus School -
        Malden"``) and whose own words say more than the town and a kind of
        school (``"Cheverus"``, not ``"Concord Academy"`` in Concord) names
        that town's school of that name, whatever church it belongs to.
        """
        town = self.city_of(index)
        places = frozenset(town.split()) if town else _EMPTY
        return any(
            token not in places and token not in _OWN_SCHOOL_NOUNS and not _is_weak(token)
            for token in query.form.token_set
        )

    def _dice(
        self, query: _Query, index: int, other: NameForm, total: float, *, code_match: bool
    ) -> tuple[float, float]:
        """The weighted Dice coefficient of the listing's words and record ``index``'s.

        ``other`` is the name of the record compared and ``total`` its words'
        weight. A word the listing shares with the record's :meth:`optional`
        words counts on both sides (``"Evergreen Clark"`` is ``"Evergreen School
        District (Clark)"``); left out, it counts on neither.

        Initials one name runs together and the other writes apart (``"FC
        BOYD"``, ``"F.C. Boyd"``) are one word, weighed on each side as it is.

        Returns the coefficient for the score and for the plausibility. A school
        named for a person whose forenames the listing leaves out, or says
        another way, is scored as its name without them (:meth:`_person`),
        however it writes them, less what leaving them out costs; when its
        forenames may be a place's words, that is its plausibility only, and the
        score is the words'.
        """
        form = query.form
        if form.compact and form.compact == other.compact:
            return _WHOLE
        tokens = other.token_set
        optional = self._optional.get(index)
        shared = 0.0
        said = 0.0
        credited: set[str] | None = None
        for token, weight in query.weights.items():
            if token in tokens:
                shared += weight
                continue
            if optional is not None and token in optional:
                shared += weight
                said += weight
                continue
            if token in other.letters:
                # The listing's one word for initials the record writes apart
                # ("FC Boyd" for "F. C. Boyd"): one word, weighed on each side as it is.
                shared += (weight + len(token) * lexicon.WEAK_WEIGHT) / 2.0
                continue
            for word, credit in query.fuzzy.get(token, ()):
                # Each of the record's words is credited once.
                if word in tokens and (credited is None or word not in credited):
                    shared += self.weight[word] * credit
                    credited = credited or set()
                    credited.add(word)
                    break
        for run in query.joined:
            if run in tokens:
                # Initials the listing writes apart and the record as one word.
                shared += (len(run) * lexicon.WEAK_WEIGHT + self.weight[run]) / 2.0
        denominator = query.total + total + said
        if denominator:
            dice = min(1.0, 2.0 * shared / denominator)
            if shared and (other.forenames or query.form.forenames):
                return self._as_person(query, other, shared, denominator)
            return (dice, dice)
        # Neither has words: a name that is only a code or a number. A code of a
        # series ("MSAD 51") names only a record of that series, never one that
        # merely has its number ("Central SD 51").
        if code_match or (not form.codes and form.numbers and form.numbers == other.numbers):
            return _WHOLE
        return _NONE

    def _as_person(
        self, query: _Query, other: NameForm, shared: float, denominator: float
    ) -> tuple[float, float]:
        """:meth:`_dice`'s pair for a school named for a person, the listing's words
        and the record's sharing ``shared`` of ``denominator`` (see :meth:`_person`)."""
        dice = min(1.0, 2.0 * shared / denominator)
        person = self._person(query, other)
        if person is None:
            return (dice, dice)
        cut, factor, sure = person
        if not cut:
            # Another person's forenames.
            return (dice * factor, dice * factor)
        fitted = min(1.0, 2.0 * shared / (denominator - cut))
        if factor < 1.0 and not query.form.levels:
            # Forenames left out, and no level said: the surname alone may be
            # another school's, one no directory holds ("Pingree School").
            sure = False
        if sure:
            return (factor * fitted, factor * fitted)
        return (dice, max(dice, FORENAMES_LEFT_OUT * fitted))

    def _person(self, query: _Query, other: NameForm) -> tuple[float, float, bool] | None:
        """How school name ``other`` fits a listing that names its person another way.

        A school named for a person may be listed without the forenames its name
        begins with, or with them written another way, which is the same
        person's name (:attr:`~snowlight.match.normalize.NameForm.forenames`):

        * left out: the listing's name begins at the surname (``"Kennedy Middle
          School"`` for ``"John F Kennedy Middle"`` and for ``"J F Kennedy
          Middle"`` alike). The forenames then weigh nothing, however the record
          writes them, and the name scores :data:`FORENAMES_LEFT_OUT` less: two
          such schools tie, and one whose name is the listing's word for word
          comes first. The same when a record leaves out initials the listing
          gives (``"Walker School"`` for ``"W.W. Walker"``).
        * said another way: the listing's words before the surname are the
          record's forenames one for one, each as written or as its initial,
          either way (``"J.F. Kennedy"`` for ``"John F Kennedy"``, ``"John F.
          Kennedy"`` and ``"John Kennedy"`` for ``"J F Kennedy"``), and may leave
          out the later ones or add initials of their own. A forename and its
          initial are one word and weigh nothing on either side, and a middle
          initial after a forename both spell alike is no matter (``"Amelia T.
          Carrow"`` for ``"Amelia R. Carrow"``).
        * another person's: a forename or an initial of the listing's is neither
          the record's in its place nor its initial (``"Robert Kennedy"``,
          ``"J.B. Nelson"`` for ``"V H Nelson"``): :data:`FORENAMES_DIFFER`. A word
          of the listing's own that is no forename, before the surname, is only a
          word the record lacks.

        A listing that leaves the forenames out is taken for the school only when
        it says the school's level too (``"Kennedy Middle School"``): a surname and
        ``School`` alone (``"Pingree School"``) may name another school, one the
        directory lacks, though the school stays a rival (:meth:`_as_person`).

        Returns the weight to take off the two names' totals (none for another
        person's), the factor to score the rest at, and whether the forenames
        surely are a person's: they end with an initial (``"John F"``, ``"R.
        D."``) or NCES bracketed them
        (:attr:`~snowlight.match.normalize.NameForm.forenames_sure`). A given name
        alone (``"Charles"``, ``"Grace"``) may be a place's word, so a record
        whose forenames are only that is scored on its words, but is as close a
        rival as a person's school would be. ``None`` when the listing names the
        person as the record does, or no person the record's name begins with.
        """
        if other.forenames:
            found = self._forenames_said(query, other)
            if found is not None:
                return found
        return self._initials_left_out(query, other) if query.form.forenames else None

    def _forenames_said(self, query: _Query, other: NameForm) -> tuple[float, float, bool] | None:
        """:meth:`_person` for the forenames record name ``other`` begins with."""
        tokens = other.tokens
        weights = query.weights
        at = next(
            (
                i
                for i in range(1, other.forenames + 1)
                if len(tokens[i]) > 1 and tokens[i] in weights
            ),
            0,
        )
        if not at:
            return None
        listing = query.form.tokens
        run = frozenset(tokens[:at])
        # The listing's words before the surname, but those the record's name says
        # elsewhere ("Har Zion Temple - Noreen Cook Center").
        said = [
            word
            for word in listing[: listing.index(tokens[at])]
            if word in run or word not in other.token_set
        ]
        spelled = bool(said) and len(said[0]) > 1 and said[0] == tokens[0]
        cut = 0.0
        for i in range(max(at, len(said))):
            mine = said[i] if i < len(said) else None
            theirs = tokens[i] if i < at else None
            if theirs is None:
                if mine is None or len(mine) > 1:
                    return None
                # An initial of the listing's own ("Amelia R. Carrow" for "Amelia Carrow").
                cut += weights[mine]
            elif theirs in weights or tokens.index(theirs) < i:
                # Said alike, or counted once already ("C C Lee").
                continue
            elif mine is None:
                cut += self.weight[theirs]
            elif mine[0] == theirs[0] and (len(mine) == 1 or len(theirs) == 1):
                # A forename and its initial, either way round: one word.
                cut += weights[mine] + self.weight[theirs]
            elif spelled and len(mine) == 1 and len(theirs) == 1:
                # Middle initials after one forename: no matter.
                cut += weights[mine] + self.weight[theirs]
            elif len(mine) == 1 or mine in _GIVEN_STEMS:
                return (0.0, FORENAMES_DIFFER, True)
            else:
                # A word of the listing's own before the surname, no forename.
                return None
        if not cut:
            return None
        factor = FORENAMES_LEFT_OUT if not said else 1.0
        return (cut, factor, other.forenames_sure or len(tokens[at - 1]) == 1)

    def _initials_left_out(
        self, query: _Query, other: NameForm
    ) -> tuple[float, float, bool] | None:
        """:meth:`_person` for initials a listing's name begins with and record ``other``'s lacks.

        ``"W.W. Walker"`` for ``"Walker School"``: the record's name begins at the
        listing's surname, and none of the listing's initials is the record's.
        """
        listing = query.form.tokens
        tokens = other.tokens
        if not tokens or len(tokens[0]) == 1:
            return None
        head = tokens[0]
        for at in range(1, query.form.forenames + 1):
            if listing[at] == head:
                initials = listing[:at]
                if all(len(word) == 1 and word not in other.token_set for word in initials):
                    cut = sum(query.weights[word] for word in set(initials))
                    return (cut, FORENAMES_LEFT_OUT, True)
                return None
        return None

    def _score(
        self, query: _Query, index: int, *, placed: bool = False, forgive: bool = False
    ) -> tuple[float, float]:
        """``(score, plausibility)`` of record ``index`` for one reading of a listing.

        The better of its own name's and, at :data:`SECOND_NAME`, its second names'.
        ``placed``: the listing named the record's town beside its name.
        ``forgive``: a municipal qualifier only one side says costs nothing
        (:meth:`_forgive_municipal`).
        """
        score, plausibility = self._score_name(
            query, index, self.forms[index], self.totals[index], placed=placed, forgive=forgive
        )
        variants = self._variants.get(index)
        if variants is not None:
            for variant in variants:
                other = self._score_name(
                    query, index, variant.form, variant.total, placed=placed, forgive=forgive
                )
                score = max(score, SECOND_NAME * other[0])
                plausibility = max(plausibility, SECOND_NAME * other[1])
        return (score, plausibility)

    def _score_name(  # noqa: PLR0913 - the listing, the name, and how to read them
        self,
        query: _Query,
        index: int,
        other: NameForm,
        total: float,
        *,
        placed: bool,
        forgive: bool = False,
    ) -> tuple[float, float]:
        """:meth:`_score` of one name ``other`` of record ``index``, whose words weigh ``total``."""
        form = query.form
        district = self.is_district[index]
        context, code_match = (
            self._district_context(form, index)
            if form.codes or form.district_numbers
            else (1.0, False)
        )
        dice, plausible = self._dice(query, index, other, total, code_match=code_match)
        county_held: bool | None = None
        if district and (
            code_match or (form.tokens and not form.district_numbers.isdisjoint(other.numbers))
        ):
            # A bare number ("District 5") is too weak to name a district alone;
            # a code of a series ("RSU 13") is not.
            if form.hint is not Level.SCHOOL:
                # Named by its code or number: the rest of the listing may name
                # its places or its schools rather than its own name.
                share, held = self._coverage(query, index)
                if COVERAGE_CREDIT * share > dice:
                    dice = COVERAGE_CREDIT * share
                    county_held = held
            if code_match and dice < CODE_ONLY:
                dice = CODE_ONLY
        if dice == 0.0:
            return (0.0, 0.0)
        plausible = max(plausible, dice)
        numbers = _listing_numbers_factor(form, other, district=district, code_match=code_match)
        levels = _levels_factor(form.levels, other, school=not district)
        if county_held is None:
            qualifiers = _qualifier_factor(
                form.qualifiers,
                other.qualifiers,
                self._implied_by(form, index, other),
                numbered=district and bool(form.numbers) and form.numbers == other.numbers,
                forgive=forgive,
                school=not district,
            )
        else:
            factor = 1.0 if county_held else QUALIFIER_NOT_FOUND
            qualifiers = (factor, factor)
        common = (
            context
            * kind_factor(form, other, district=district)
            * self._identity_factor(
                query, index, other, covered=county_held is not None, placed=placed
            )
        )
        plural = (
            PLURAL_DIFFERS
            if (form.plurals or other.plurals) and plurals_differ(form, other)
            else 1.0
        )
        return (
            dice * common * plural * numbers[0] * levels[0] * qualifiers[0],
            plausible * common * numbers[1] * levels[1] * qualifiers[1],
        )

    def _implied_by(self, form: NameForm, index: int, other: NameForm) -> frozenset[str]:
        """The place qualifiers record ``index``'s name ``other`` implies for the listing ``form``.

        Its own (:attr:`~snowlight.match.normalize.NameForm.implied`), and the
        qualifier of the county a bracket of its name names when the listing
        says that county's words: ``"Evergreen - Clark County"`` says the
        ``County`` of ``"Evergreen School District (Clark)"``, which
        ``"Evergreen County Schools"`` does not.
        """
        county = self._county.get(index)
        if county is None or county[1] is None or not county[0] <= form.token_set:
            return other.implied
        return other.implied | {county[1]}

    def _identity_factor(
        self, query: _Query, index: int, other: NameForm, *, covered: bool, placed: bool = False
    ) -> float:
        """The penalties for what the listing and record ``index``'s name ``other`` say they are.

        Their affiliations, directions, ``School of`` and kind of school; see the
        module's notes. ``covered``: the record is a district the listing names by
        its code or number, and the rest of the listing its towns.
        """
        form = query.form
        factor = 1.0
        theirs = other.affiliations
        if query.affiliations:
            if self._implies_the_faith(query, index, other):
                factor *= PARISH_IMPLIED
            elif query.affiliations != theirs:
                factor *= AFFILIATION_NOT_SAID
        elif (
            theirs - lexicon.CHAIN_BRANDS
            and not other.devoted
            and not theirs <= query.said
            and not (placed and self._placed_by_name(query, index))
        ):
            factor *= AFFILIATION_LEFT_OUT
        if (form.directions or other.directions) and self._directions_differ(
            form, index, other, covered=covered
        ):
            factor *= DIRECTION_NOT_SAID
        if form.school_of != other.school_of and (form.school_of or form.one_school):
            factor *= SCHOOL_OF_NOT_SAID
        if _place_word_not_said(form, other):
            factor *= PLACE_WORD_NOT_SAID
        if query.types and not self.is_district[index]:
            if self._type_mismatch(query.types, index):
                factor *= TYPE_NOT_SAID
            elif not other.names_kind and not query.types <= self.token_sets[index]:
                factor *= TYPE_NOT_SHOWN
        return factor

    def _implies_the_faith(self, query: _Query, index: int, other: NameForm) -> bool:
        """True when the listing's only faith is a parish school's, which the record's name implies.

        A private school named for a saint or a devotion, and no church, is a
        Catholic parish's school: NCES's ``"ST PETER'S SCHOOL"`` is the listing
        ``"St. Peter's Catholic School"``. Another church names itself
        (``"ST PAUL'S LUTHERAN SCHOOL"``), and a public school is none. Such a
        record scores a little under one that says the faith (:data:`PARISH_IMPLIED`).
        """
        record = self.records[index]
        return (
            bool(query.affiliations)
            and query.affiliations != other.affiliations
            and query.affiliations <= lexicon.PARISH_AFFILIATIONS
            and not other.affiliations
            and other.devoted
            and record.kind == "school"
            and record.district_id is None
        )

    def search(self, forms: ListingForms, scope: Scope) -> list[Scored]:
        """Score every plausible record in ``scope`` for a listing, best first.

        A district whose name and the listing differ only in a municipal word
        one of them says is scored again without it when no other record in
        ``scope`` shares the rest of its name (:meth:`_forgive_municipal`).
        """
        states = scope.states
        district_query = self._query(forms.district, states)
        school_query = self._query(forms.school, states)
        found = self._candidates((district_query, school_query), states)
        entity = scope.entity
        if entity is not None and not any(self.entity_of(i) == entity for i in found):
            # No record of the name carries the number: it says nothing here.
            entity = None
        scored: list[Scored] = []
        one_sided: list[int] = []
        placed = scope.city is not None
        for index in found:
            if self.records[index].kind not in scope.kinds:
                continue
            if scope.allowed is not None and index not in scope.allowed:
                continue
            if scope.counties is not None and not self.in_counties(index, scope.counties):
                continue
            if scope.city is not None and self.city_of(index) != scope.city:
                continue
            if entity is not None and self.entity_of(index) != entity:
                continue
            district = self.is_district[index]
            query = district_query if district else school_query
            score, plausibility = self._score(query, index, placed=placed)
            if score > 0.0:
                if district and self._municipal_one_sided(query.form, index):
                    one_sided.append(len(scored))
                scored.append(Scored(index, score, plausibility))
        if one_sided:
            self._forgive_municipal(scored, one_sided, district_query, placed=placed)
        scored.sort(key=lambda s: (-s.score, s.index))
        return scored

    def forgiven(self, forms: ListingForms, index: int) -> Scored:
        """District ``index`` scored for a listing with a municipal word one side says set aside.

        As :meth:`search` scores it when no other record shares the rest of its
        name (:meth:`_forgive_municipal`), whatever else does: a school system's
        districts are one reading of a listing that says a municipal word none
        of them says (``"Santa Rosa City Schools"`` for ``"Santa Rosa
        Elementary"`` and ``"Santa Rosa High"``, see
        :meth:`~snowlight.match.matcher.Matcher._as_system`).
        """
        query = self._query(forms.district, (self.records[index].state,))
        score, plausibility = self._score(query, index, forgive=True)
        return Scored(index, score, plausibility)

    def _municipal_one_sided(self, form: NameForm, index: int) -> bool:
        """True when only the listing ``form`` or district ``index``'s name says a municipal word.

        See :func:`municipal_one_sided`; a qualifier the record's name implies
        counts as said when the listing says it. Only for a listing whose words
        say it names a school system (``"Murfreesboro City Schools"``): one that
        names a place and its kind (``"Dover Borough"``, ``"Flushing
        Township"``) names the municipality, not a district named otherwise.
        And only a word that follows a name: ``"City University Schools"`` is
        no city's.
        """
        other = self.forms[index]
        if (
            form.hint is not Level.DISTRICT
            or not (form.qualifiers or other.qualifiers)
            or form.qualifier_first
            or other.qualifier_first
        ):
            return False
        said = other.qualifiers | (form.qualifiers & self._implied_by(form, index, other))
        return municipal_one_sided(form.qualifiers, said)

    def _forgive_municipal(
        self, scored: list[Scored], positions: Sequence[int], query: _Query, *, placed: bool
    ) -> None:
        """Score again, in place, the districts at ``positions`` with their municipal word forgiven.

        NCES and the closings lists each say or leave out the kind of
        municipality a district's town is (:data:`~snowlight.match.lexicon.MUNICIPAL_QUALIFIERS`):
        Tennessee's ``"Murfreesboro"`` is the lists' ``"Murfreesboro City
        Schools"``, New Jersey's ``"Cherry Hill School District"`` their
        ``"Cherry Hill Township School District"``, Pennsylvania's ``"Bensalem
        Township SD"`` their ``"Bensalem School District"``. Such a word said on
        one side only costs nothing when no other record in scope shares the
        rest of the name (:meth:`_shares_the_rest`); when one does
        (``"Bristol Township SD"`` beside ``"Bristol Borough SD"``), the word is
        what tells them apart, and costs as before.
        """
        for position in positions:
            found = scored[position]
            if self._shares_the_rest(found.index, scored):
                continue
            score, plausibility = self._score(query, found.index, placed=placed, forgive=True)
            if score > found.score:
                scored[position] = Scored(found.index, score, max(plausibility, found.plausibility))

    def _shares_the_rest(self, index: int, scored: Sequence[Scored]) -> bool:
        """True when a district of ``scored`` other than ``index`` bears the rest of its name.

        Its name holds district ``index``'s identifying words (or the same words
        run together), whatever else it says: ``"Bristol Borough SD"`` for
        ``"Bristol Township SD"``, ``"Hampton SD"`` for ``"Hampton Township SD"``,
        ``"Johnson County"`` for ``"Johnson"``, and ``"Passaic County Manchester
        Regional High School District"`` for ``"Manchester Township School
        District"``. Not one the listing rules out (:data:`RULED_OUT`): ``"South
        Hackensack School District"`` is no reading of ``"Hackensack Township
        School District"``.

        Only a district of the same state: a state writes its municipal words
        its own way (Tennessee's ``"Bristol"`` is Virginia's ``"Bristol City
        Public Schools"``), so a namesake across a state line is no reason to
        read one state's habit as a word that tells the two apart. Which state
        such a listing means is for the matcher to settle
        (:meth:`~snowlight.match.matcher.Matcher._undecided_across`).
        """
        form = self.forms[index]
        words = form.token_set
        state = self.records[index].state
        for found in scored:
            other = found.index
            if (
                other == index
                or not self.is_district[other]
                or found.plausibility < RULED_OUT
                or self.records[other].state != state
            ):
                continue
            if (form.compact and self.forms[other].compact == form.compact) or any(
                words <= theirs for theirs in self.word_sets(other)
            ):
                return True
        return False
