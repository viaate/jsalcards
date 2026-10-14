"""Real schools the NCES files miss, from a reviewed file kept beside the config.

The NCES Private School Survey public file lists only the private schools that
answered that cycle, so real schools, many Catholic ones among them, are missing
from it. ``config/directory-supplement.yaml`` lists such schools, each with the
evidence that it operates now and where it is. :func:`load_supplement` reads and
checks the file; :func:`assemble_supplement` turns it into rows of
:data:`~snowlight.directory.assemble.SCHOOL_SCHEMA`, each with a drop reason, so
the build counts and reconciles them like the NCES rows.

Ids: every supplement id is the configured two-letter prefix and six digits
(``SN000001``). NCES never uses that prefix (PSS ids are a letter and seven
digits, ``AA``/``AB``/``BB``/``XA``/``YA`` and six digits, or eight digits; CCD ids
are twelve digits), and the build stops if an NCES file ever does
(:func:`check_prefix_unused`), so a supplement id can never name an NCES school.
An id is never reused or renumbered: a school's id stays its own. The file
records the highest id it ever issued (``last_id``) and the ids of the entries it
no longer holds (``retired_ids``); :func:`load_supplement` refuses a file in which
any number up to ``last_id`` is neither an entry nor retired, or is both, so an
entry cannot be deleted without retiring its id, and a new one takes the next
number.

A supplement school is dropped as ``listed_by_nces`` when the NCES files the
build reads list it: an NCES private school id the entry records (``nces_ppin``),
or a kept NCES private school in the same state within :data:`SAME_PLACE_METERS`
with the same name (:func:`same_name`: at least half of their distinctive words
shared, initials aside, a word one letter off counting as the same). The NCES
row is then the one on the map, so the same school is never listed twice.

What a name cannot settle stops the build until a reviewer does
(:func:`review_conflicts`): a kept entry with a kept NCES private school within
:data:`NEAR_PRIVATE_METERS`, a kept NCES public school within
:data:`NEAR_PUBLIC_METERS`, or a kept NCES private school at the same street
address, whatever their names, or one within :data:`NEAR_NAME_METERS` whose name
the entry's contains (a campus of it). The reviewer checks each and lists the NCES ids
that are other schools in the entry's ``distinct_from`` (a public "Roland Park
Elementary/Middle" is not the private Roland Park Country School next to it), or
deletes the entry. An entry whose only evidence is a closings row is refused
when an NCES school in another state has its name and town (:func:`same_words`):
the row may name that school.

Two dates keep an entry current. Its evidence that the school operates (a
current page checked on ``checked_on``, or a closings row's ``evidence_seen_on``)
must be from this school year or the last and no older than the configured
``max_evidence_age_days``, or the entry is dropped as ``evidence_stale``: a school
that closed never stays on the map as current. Its street address must have been
matched against a current source (the school's own site, its diocese's list, or a
closings row that gives the street) on or after August 1 of this school year, or
it is dropped as ``address_stale``: a school that moved over the summer is never
shown at its old address. An earlier PSS file never vouches for an address.
"""

import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

import polars as pl
import yaml  # type: ignore[import-untyped, unused-ignore]
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from snowlight.directory import filters
from snowlight.directory.assemble import KIND_PRIVATE, SCHOOL_SCHEMA, coordinate_e6, degrees
from snowlight.directory.config import DirectoryConfig
from snowlight.directory.filters import Reason

SAME_PLACE_METERS = 1_000.0
"""How near an NCES school with the same name must be to count as the same school."""
NEAR_PRIVATE_METERS = 300.0
"""An NCES private school this near an entry, whatever its name, needs a reviewer's ruling."""
NEAR_PUBLIC_METERS = 150.0
"""An NCES public school this near an entry, whatever its name, needs a reviewer's ruling."""
NEAR_NAME_METERS = 5_000.0
"""An NCES private school this near whose name's words all are in the entry's name
(or the other way round) needs a reviewer's ruling: it may be the school the entry
is a campus of ("Monroe Catholic Elementary Schools" and its St. John campus)."""
NEAR_DUPLICATE_METERS = 100.0
"""Two supplement entries with the same name this near each other are one school listed twice."""
_EARTH_RADIUS_M = 6_371_008.8
_SCHOOL_YEAR_STARTS = 8  # August
EXPIRY_WARNING_DAYS = 60
"""An entry whose evidence or address goes stale within this many days of the build
is listed in the build report (and as a warning in Preview's log), so it is checked
again before it drops off the map."""

# State postal code to state FIPS code, for the states the directory can hold.
STATE_FIPS: dict[str, str] = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09",
    "DE": "10", "DC": "11", "FL": "12", "GA": "13", "HI": "15", "ID": "16", "IL": "17",
    "IN": "18", "IA": "19", "KS": "20", "KY": "21", "LA": "22", "ME": "23", "MD": "24",
    "MA": "25", "MI": "26", "MN": "27", "MS": "28", "MO": "29", "MT": "30", "NE": "31",
    "NV": "32", "NH": "33", "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38",
    "OH": "39", "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46",
    "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53", "WV": "54",
    "WI": "55", "WY": "56",
}  # fmt: skip

# Grade labels as the directory writes them (PSS_GRADE_LABELS), lowest first.
GRADE_ORDER: tuple[str, ...] = ("PK", "TK", "KG", "T1", *(f"{g:02d}" for g in range(1, 13)))
_K12 = frozenset(("KG", "T1", *(f"{g:02d}" for g in range(1, 13))))
_HIGH = ["09", "10", "11", "12"]
# PSS LEVEL: secondary when the lowest grade is 7 or above, elementary when the
# highest is 8 or below, combined otherwise (as the NCES private rows are labelled).
_SECONDARY_LOW = ["07", "08", *_HIGH]
# Sources whose grades are current: a school's own site or its diocese's list.
_CURRENT_GRADES: frozenset[str] = frozenset(["diocese-list", "school-site"])

Source = Literal["pss-2021-22", "pss-2019-20", "diocese-list", "school-site", "closings-list"]
AddressFrom = Literal["school-site", "diocese-list", "closings-row"]


class SupplementError(ValueError):
    """The supplement file is malformed or contradicts itself."""


class SupplementSchool(BaseModel):
    """One school the NCES files miss, with where it is and why it is known to operate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str = Field(min_length=3)
    street: str = Field(min_length=3)
    city: str = Field(min_length=2)
    state: str
    zip: str
    county_fips: str
    county_name: str = Field(min_length=3)
    lat: float
    lon: float
    grade_low: str
    grade_high: str
    """Lowest and highest grade, as the school's current pages give them (``grades_url``),
    or, where no current page gives them, as its earlier PSS row does."""
    pss_grade_low: str | None = None
    pss_grade_high: str | None = None
    """The grades of the school's earlier PSS row (``nces_ppin``), recorded so that
    grades that differ from it cannot pass unnoticed."""
    grades_url: str | None = None
    """The school's own current page that gives ``grade_low`` to ``grade_high``:
    required when they differ from its PSS row's grades. A diocese list, or a survey
    from earlier years, can be out of date: Sacred Heart in Sedalia is PK-12 on its
    own site and PK-8 on its diocese's list."""
    source: Source
    """Where the school and its grades come from (its address: ``address_from``)."""
    nces_ppin: str | None = None
    """The school's id in an earlier PSS file: required for ``pss-*`` sources, and
    given for others when known, so the build drops the entry if NCES lists it again."""
    evidence_url: str | None = None
    """A current page that lists the school as operating (its diocese's list or its own site)."""
    evidence_station: str | None = None
    """A closings list (station source id) that named the school ..."""
    evidence_seen_on: date | None = None
    """... on this date."""
    address_from: AddressFrom
    """Where the street address was last matched: the school's own site or its
    diocese's list (``address_url``), or a closings row that gives the street address
    (``evidence_station`` on ``evidence_seen_on``). An earlier PSS file never vouches
    for an address: a school can move over a summer."""
    address_url: str | None = None
    """The page that gives the street address now (``school-site`` or ``diocese-list``)."""
    address_checked_on: date
    """When the street address was matched against that source. An address last
    matched before the school year began (August 1) is dropped as ``address_stale``."""
    geocoded_address: str = Field(min_length=10)
    """The address ``lat`` and ``lon`` are the geocode of, as the geocoder matched it."""
    geocoder: Literal["census", "nces-pss"] = "census"
    """``census``: the Census Bureau geocoder matched the street address. ``nces-pss``:
    it found no exact match, and NCES's own geocode of the same street address in the
    earlier PSS file (``nces_ppin``) is used, once a reviewer has matched that point
    against the school's own map or address page (``location_url``); the county still
    comes from the Census Bureau for those coordinates."""
    location_url: str | None = None
    """For an ``nces-pss`` geocode: the school's own map or address page whose point
    a reviewer matched ``lat`` and ``lon`` against."""
    location_checked_on: date | None = None
    """When that match was made."""
    checked_on: date
    """When the evidence and the address were checked."""
    distinct_from: list[str] = Field(default_factory=list)
    """NCES ids of schools near this one that a reviewer checked are other schools
    (see :func:`review_conflicts`)."""

    @field_validator("state")
    @classmethod
    def _state(cls, value: str) -> str:
        if value not in STATE_FIPS:
            raise ValueError(f"unknown state {value!r}")
        return value

    @field_validator("name", "street", "city")
    @classmethod
    def _as_nces_writes(cls, value: str) -> str:
        # Written as the NCES files write theirs (ASCII capitals), so the site
        # cases every school's name one way (web/src/text/names.ts casedName).
        if not value.isascii() or value != value.upper():
            raise ValueError("name, street and city are in ASCII capitals, as NCES writes them")
        return value

    @field_validator("zip")
    @classmethod
    def _zip(cls, value: str) -> str:
        if not re.fullmatch(r"\d{5}", value):
            raise ValueError("zip must be five digits")
        return value

    @field_validator("county_fips")
    @classmethod
    def _county(cls, value: str) -> str:
        if not re.fullmatch(r"\d{5}", value):
            raise ValueError("county_fips must be five digits")
        return value

    @field_validator("grade_low", "grade_high", "pss_grade_low", "pss_grade_high")
    @classmethod
    def _grade(cls, value: str | None) -> str | None:
        if value is not None and value not in GRADE_ORDER:
            raise ValueError(f"grade must be one of {GRADE_ORDER}")
        return value

    @field_validator("evidence_url", "address_url", "grades_url", "location_url")
    @classmethod
    def _https(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("https://"):
            raise ValueError("evidence_url, address_url, grades_url and location_url must be https")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> "SupplementSchool":
        if STATE_FIPS[self.state] != self.county_fips[:2]:
            raise ValueError(f"county {self.county_fips} is not in {self.state}")
        if round(self.lat, 6) != self.lat or round(self.lon, 6) != self.lon:
            raise ValueError("coordinates have at most six decimals")
        self._check_grades()
        self._check_location()
        if self.source.startswith("pss-") and self.nces_ppin is None:
            raise ValueError("a pss-* source needs its nces_ppin")
        station = (self.evidence_station is None, self.evidence_seen_on is None)
        if station[0] != station[1]:
            raise ValueError("evidence_station and evidence_seen_on go together")
        if self.evidence_url is None and self.evidence_station is None:
            raise ValueError("an entry needs evidence: evidence_url or evidence_station")
        if self.evidence_seen_on is not None:
            if self.evidence_seen_on > self.checked_on:
                raise ValueError("evidence_seen_on is after checked_on")
            if school_year_of(self.evidence_seen_on) not in _this_or_last_year(self.checked_on):
                raise ValueError(
                    "evidence_seen_on is not in the school year of checked_on or the one before"
                )
        self._check_address()
        return self

    def _check_location(self) -> None:
        if self.geocoder == "census":
            if self.location_url is not None or self.location_checked_on is not None:
                raise ValueError("location_url and location_checked_on are for nces-pss geocodes")
            return
        if self.nces_ppin is None:
            raise ValueError("an nces-pss geocode needs its nces_ppin")
        if self.location_url is None or self.location_checked_on is None:
            raise ValueError(
                "an nces-pss geocode needs location_url and location_checked_on: the "
                "school's own map or address page its point was matched against, and when"
            )
        if self.location_checked_on > self.checked_on:
            raise ValueError("location_checked_on is after checked_on")

    def _check_address(self) -> None:
        if self.address_checked_on > self.checked_on:
            raise ValueError("address_checked_on is after checked_on")
        if self.address_from == "closings-row":
            if self.evidence_station is None or self.address_url is not None:
                raise ValueError("a closings-row address needs evidence_station and no address_url")
            if self.address_checked_on != self.evidence_seen_on:
                raise ValueError("a closings-row address is checked on the row's evidence_seen_on")
        elif self.address_url is None:
            raise ValueError(f"a {self.address_from} address needs its address_url")

    @property
    def evidence_on(self) -> date:
        """The date of the latest evidence that the school operates: ``checked_on``
        for a current page (``evidence_url``), else the closings row's date."""
        if self.evidence_url is not None or self.evidence_seen_on is None:
            return self.checked_on
        return self.evidence_seen_on

    def _check_grades(self) -> None:
        low, high = GRADE_ORDER.index(self.grade_low), GRADE_ORDER.index(self.grade_high)
        if low > high:
            raise ValueError("grade_low is above grade_high")
        if not _K12.intersection(GRADE_ORDER[low : high + 1]):
            raise ValueError("the school offers no grade from K to 12")
        # A preschool or child care center with a kindergarten class in an
        # earlier survey may have dropped it: its kindergarten must be current.
        if high <= GRADE_ORDER.index("T1") and self.source not in _CURRENT_GRADES:
            raise ValueError(
                "a school whose highest grade is kindergarten needs its grades from "
                "a current source (diocese-list or school-site)"
            )
        pss = (self.pss_grade_low, self.pss_grade_high)
        recorded = None not in pss
        if (recorded != (self.nces_ppin is not None)) or (not recorded and pss != (None, None)):
            raise ValueError(
                "an entry with an nces_ppin records its PSS row's grades in "
                "pss_grade_low and pss_grade_high, and only such an entry"
            )
        differ = self.nces_ppin is not None and pss != (self.grade_low, self.grade_high)
        if differ and self.grades_url is None:
            raise ValueError(
                f"grades {self.grade_low}-{self.grade_high} differ from its PSS row's "
                f"{pss[0]}-{pss[1]}: grades_url must give the school's own current "
                "page that settles them"
            )


class Supplement(BaseModel):
    """The whole supplement file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    last_id: str | None = None
    """The highest id ever issued; ``None`` only while the file holds no entry."""
    retired_ids: list[str] = Field(default_factory=list)
    """Ids of entries the file no longer holds, never to be issued again."""
    schools: list[SupplementSchool]


def load_supplement(path: Path, prefix: str) -> Supplement:
    """Read and check the supplement file.

    Raises:
        SupplementError: on an id that is not ``prefix`` and six digits, a repeated
            id, an id above ``last_id``, a number up to ``last_id`` that is neither
            an entry's id nor retired (or is both), or the same school listed twice
            (the same distinctive name words within :data:`NEAR_DUPLICATE_METERS`;
            two schools of one campus, such as "Everest Academy" and "Everest
            Collegiate High School", differ).
        pydantic.ValidationError: on a malformed entry.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    supplement = Supplement.model_validate(raw)
    _check_ids(supplement, prefix)
    schools = supplement.schools
    for i, a in enumerate(schools):
        for b in schools[i + 1 :]:
            near = meters_between(a.lat, a.lon, b.lat, b.lon) <= NEAR_DUPLICATE_METERS
            if a.state == b.state and near and name_words(a.name) == name_words(b.name):
                raise SupplementError(f"{a.id} and {b.id} are the same school")
    return supplement


def _check_ids(supplement: Supplement, prefix: str) -> None:
    pattern = re.compile(rf"{re.escape(prefix)}\d{{6}}")
    ids = [school.id for school in supplement.schools]
    for value in [*ids, *supplement.retired_ids]:
        if not pattern.fullmatch(value):
            raise SupplementError(f"{value}: ids are {prefix} and six digits")
    seen: set[str] = set()
    for value in ids:
        if value in seen:
            raise SupplementError(f"{value}: repeated id")
        seen.add(value)
    for value in supplement.retired_ids:
        if value in seen:
            where = "retired and in use" if value in ids else "retired twice"
            raise SupplementError(f"{value}: {where}")
        seen.add(value)
    if supplement.last_id is None:
        if seen:
            raise SupplementError("last_id is missing: the highest id ever issued")
        return
    if not pattern.fullmatch(supplement.last_id):
        raise SupplementError(f"last_id {supplement.last_id}: ids are {prefix} and six digits")
    last = int(supplement.last_id[len(prefix) :])
    numbers = {int(value[len(prefix) :]) for value in seen}
    above = sorted(n for n in numbers if n > last)
    if above:
        raise SupplementError(f"{prefix}{above[0]:06d} is above last_id {supplement.last_id}")
    missing = sorted(set(range(1, last + 1)) - numbers)
    if missing:
        raise SupplementError(
            f"{prefix}{missing[0]:06d} is neither an entry nor retired: "
            "a deleted entry's id goes in retired_ids"
        )


def check_prefix_unused(ids: pl.Series, prefix: str, what: str) -> None:
    """Refuse NCES ids that start with the supplement prefix.

    Raises:
        SupplementError: if any id in ``ids`` starts with ``prefix``.
    """
    taken = ids.drop_nulls().filter(ids.drop_nulls().str.starts_with(prefix))
    if taken.len():
        raise SupplementError(
            f"{what} uses the supplement id prefix {prefix} ({taken[0]!r}); choose another"
        )


_SPELLED = {"ST": "SAINT", "STS": "SAINTS", "MT": "MOUNT", "&": "AND", "SCH": "SCHOOL"}
_GENERIC = frozenset(
    [
        "THE",
        "OF",
        "AND",
        "AT",
        "SCHOOL",
        "SCHOOLS",
        "CATHOLIC",
        "PARISH",
        "ACADEMY",
        "ELEMENTARY",
        "GRADE",
        "HIGH",
        "MIDDLE",
        "JUNIOR",
        "SENIOR",
        "PREPARATORY",
        "PREP",
        "REGIONAL",
        "INC",
        "JR",
        "SR",
    ]
)


def name_words(name: str) -> frozenset[str]:
    """A name's distinctive words: upper case, accents and apostrophes dropped,
    "St" read as "Saint", and generic school words and initials left out (all
    words when every word is generic)."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().upper()
    text = text.replace("'", "")
    words = [_SPELLED.get(word, word) for word in re.findall(r"[A-Z0-9&]+", text)]
    distinctive = frozenset(word for word in words if word not in _GENERIC and len(word) > 1)
    return distinctive or frozenset(words)


_FUZZY_WORD = 5
"""Shortest word a one-letter difference may still match (GERTUDE is GERTRUDE;
ANN is not ANNE)."""


def _one_edit(a: str, b: str) -> bool:
    """Whether ``a`` and ``b`` differ by at most one inserted, deleted or changed letter."""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    if len(a) == len(b):
        return a[i + 1 :] == b[i + 1 :]
    return a[i:] == b[i + 1 :]


def _words_match(a: str, b: str) -> bool:
    if a == b:
        return True
    return min(len(a), len(b)) >= _FUZZY_WORD and _one_edit(a, b)


def _matched(wa: frozenset[str], wb: frozenset[str]) -> int:
    """How many words of ``wa`` pair off with a word of ``wb`` (each used once)."""
    free = sorted(wb)
    matched = 0
    for word in sorted(wa):
        hit = next((other for other in free if _words_match(word, other)), None)
        if hit is not None:
            free.remove(hit)
            matched += 1
    return matched


def same_name(a: str, b: str) -> bool:
    """Whether two names share at least half of their distinctive words, a word one
    letter off (from :data:`_FUZZY_WORD` letters) counting as the same: "Powers
    Catholic High School" is "Luke M Powers Catholic High School", and "St.
    Gertrude School" is NCES's "St Gertude Catholic School"."""
    wa, wb = name_words(a), name_words(b)
    if not wa or not wb:
        return False
    matched = _matched(wa, wb)
    return matched * 2 >= len(wa) + len(wb) - matched


def same_words(a: str, b: str, aside: frozenset[str] = frozenset()) -> bool:
    """Whether two names have the same distinctive words, setting ``aside`` (a
    town's words) apart, a word one letter off counting as the same; never for a
    name with no other word left."""
    wa, wb = name_words(a) - aside, name_words(b) - aside
    if not wa or not wb or len(wa) != len(wb):
        return False
    return _matched(wa, wb) == len(wa)


_STREET_PHRASES = (
    ("STATE ROAD", "HWY"),
    ("STATE RD", "HWY"),
    ("STATE ROUTE", "HWY"),
    ("STATE HIGHWAY", "HWY"),
    ("STATE HWY", "HWY"),
)
_STREET_WORDS = {
    "WEST": "W", "EAST": "E", "NORTH": "N", "SOUTH": "S", "STREET": "ST", "AVENUE": "AVE",
    "AV": "AVE", "ROAD": "RD", "COURT": "CT", "DRIVE": "DR", "LANE": "LN", "BOULEVARD": "BLVD",
    "HIGHWAY": "HWY", "ROUTE": "HWY", "RTE": "HWY", "RT": "HWY", "PLACE": "PL",
    "PARKWAY": "PKWY", "CIRCLE": "CIR", "TERRACE": "TER", "TRAIL": "TRL", "SAINT": "ST",
}  # fmt: skip


def street_key(street: str | None) -> str | None:
    """A street address in one spelling ("1505 West Court St." and "1505 W CT ST"
    are "1505 W CT ST"; "6520 State Road YY" and "6520 HWY YY" are "6520 HWY YY"),
    or ``None`` when it does not start with a house number."""
    if not street:
        return None
    text = unicodedata.normalize("NFKD", street).encode("ascii", "ignore").decode().upper()
    text = " ".join(re.findall(r"[A-Z0-9]+", text))
    for phrase, short in _STREET_PHRASES:
        text = re.sub(rf"\b{phrase}\b", short, text)
    words = [_STREET_WORDS.get(word, word) for word in text.split()]
    if not words or not words[0].isdigit():
        return None
    return " ".join(words)


def meters_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in meters."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(h))


def _within(school: SupplementSchool, frame: pl.DataFrame, meters: float) -> list[dict[str, Any]]:
    """Rows of ``frame`` (``lat``, ``lon``) within ``meters`` of ``school``, nearest first."""
    box = meters / 111_000 * 1.5
    wide = box / max(math.cos(math.radians(school.lat)), 0.1)
    nearby = frame.filter(
        pl.col("lat").is_between(school.lat - box, school.lat + box)
        & pl.col("lon").is_between(school.lon - wide, school.lon + wide)
    )
    rows = []
    for row in nearby.iter_rows(named=True):
        distance = meters_between(school.lat, school.lon, row["lat"], row["lon"])
        if distance <= meters:
            rows.append({**row, "meters": distance})
    return sorted(rows, key=lambda row: (row["meters"], row["id"]))


def listed_by_nces(
    school: SupplementSchool, nces_private_ids: frozenset[str], kept_private: pl.DataFrame
) -> str | None:
    """The NCES id that lists ``school`` (its PSS id, or the same name nearby), or ``None``.

    ``kept_private`` holds the kept NCES private schools with ``id``, ``state``,
    ``name``, ``lat`` and ``lon``.
    """
    if school.nces_ppin is not None and school.nces_ppin in nces_private_ids:
        return school.nces_ppin
    same_state = kept_private.filter(pl.col("state") == school.state)
    for row in _within(school, same_state, SAME_PLACE_METERS):
        if same_name(school.name, row["name"]):
            return str(row["id"])
    return None


def review_conflicts(
    school: SupplementSchool, kept_private: pl.DataFrame, kept_public: pl.DataFrame
) -> list[str]:
    """The kept NCES schools a reviewer must rule on before ``school`` is merged.

    Each is an NCES private school within :data:`NEAR_PRIVATE_METERS`, a public one
    within :data:`NEAR_PUBLIC_METERS`, a private one within :data:`NEAR_NAME_METERS`
    whose name's words all are the entry's (or the other way round), or a private
    one at the same street address
    (:func:`street_key`, the same state and ZIP code or town), not listed in the
    entry's ``distinct_from``. Both frames hold ``id``, ``name``, ``street``,
    ``city``, ``state``, ``zip``, ``lat`` and ``lon``.
    """
    found: dict[str, str] = {}
    for row in _within(school, kept_private, NEAR_PRIVATE_METERS):
        found.setdefault(row["id"], f"private {row['name']!r} {row['meters']:.0f} m away")
    for row in _within(school, kept_public, NEAR_PUBLIC_METERS):
        found.setdefault(row["id"], f"public {row['name']!r} {row['meters']:.0f} m away")
    words = name_words(school.name)
    for row in _within(school, kept_private, NEAR_NAME_METERS):
        other = name_words(row["name"])
        if words <= other or other <= words:
            found.setdefault(
                row["id"], f"private {row['name']!r} {row['meters']:.0f} m away shares its name"
            )
    key = street_key(school.street)
    if key is not None:
        place = (pl.col("zip") == school.zip) | (
            pl.col("city").str.to_uppercase() == school.city.upper()
        )
        for row in kept_private.filter((pl.col("state") == school.state) & place).iter_rows(
            named=True
        ):
            if street_key(row["street"]) == key:
                found.setdefault(row["id"], f"private {row['name']!r} at the same address")
    return [
        f"{school.id} {school.name!r}: NCES {nces_id} {what}"
        for nces_id, what in sorted(found.items())
        if nces_id not in school.distinct_from
    ]


def station_twins(school: SupplementSchool, kept_nces: pl.DataFrame) -> list[str]:
    """For an entry whose only evidence is a closings row: the kept NCES schools in
    another state with its name and town, which the row may have named instead
    (a Cincinnati list's "St Mary/Alexandria" is Alexandria, Kentucky's school,
    not Alexandria, Indiana's). ``kept_nces`` holds ``id``, ``name``, ``city`` and
    ``state``."""
    if school.evidence_url is not None:
        return []
    twins = kept_nces.filter(
        (pl.col("state") != school.state)
        & (pl.col("city").str.to_uppercase() == school.city.upper())
    )
    town = name_words(school.city)
    return [
        f"{school.id} {school.name!r}: its only evidence is a closings row, and NCES "
        f"{row['id']} {row['name']!r} in {row['city']}, {row['state']} has its name and town"
        for row in twins.iter_rows(named=True)
        if same_words(school.name, row["name"], town)
    ]


def school_year_start(day: date) -> date:
    """The first day of the school year ``day`` falls in (August 1)."""
    return date(day.year if day.month >= _SCHOOL_YEAR_STARTS else day.year - 1, 8, 1)


def school_year_of(day: date) -> str:
    """The school year a day falls in, starting August 1 (``2026-10-14`` is 2026-2027)."""
    start = school_year_start(day).year
    return f"{start}-{start + 1}"


def _this_or_last_year(day: date) -> tuple[str, str]:
    start = school_year_start(day).year
    return f"{start}-{start + 1}", f"{start - 1}-{start}"


def evidence_stale(school: "SupplementSchool", today: date, max_age_days: int | None) -> bool:
    """Whether the latest evidence that ``school`` operates is too old to show it as
    current: from before last school year, or older than ``max_age_days``."""
    seen = school.evidence_on
    too_old = max_age_days is not None and (today - seen).days > max_age_days
    return too_old or school_year_of(seen) not in _this_or_last_year(today)


def address_stale(school: "SupplementSchool", today: date) -> bool:
    """Whether ``school``'s street address was last matched against a current source
    before this school year began: a school may have moved over the summer."""
    return school.address_checked_on < school_year_start(today)


def evidence_expires_on(school: "SupplementSchool", max_age_days: int | None) -> date:
    """The first build date on which :func:`evidence_stale` holds for ``school``
    (for builds on or after its evidence date): the evidence's school year ends a year
    ago, or it turns ``max_age_days`` old."""
    seen = school.evidence_on
    year_ends = date(school_year_start(seen).year + 2, _SCHOOL_YEAR_STARTS, 1)
    if max_age_days is None:
        return year_ends
    return min(year_ends, seen + timedelta(days=max_age_days + 1))


def address_expires_on(school: "SupplementSchool") -> date:
    """The first build date on which :func:`address_stale` holds for ``school``: the
    August 1 after its address was last matched."""
    start = school_year_start(school.address_checked_on)
    return date(start.year + 1, _SCHOOL_YEAR_STARTS, 1)


@dataclass(frozen=True)
class Expiring:
    """A kept entry whose evidence or address goes stale soon."""

    id: str
    name: str
    what: Literal["evidence", "address"]
    expires_on: date


def expiring(
    schools: list["SupplementSchool"],
    today: date,
    max_age_days: int | None,
    within_days: int = EXPIRY_WARNING_DAYS,
) -> list[Expiring]:
    """The checks of ``schools`` that go stale after ``today`` but within
    ``within_days`` of it, soonest first."""
    horizon = today + timedelta(days=within_days)
    found = []
    for school in schools:
        checks: tuple[tuple[Literal["evidence", "address"], date], ...] = (
            ("evidence", evidence_expires_on(school, max_age_days)),
            ("address", address_expires_on(school)),
        )
        for what, day in checks:
            if today < day <= horizon:
                found.append(Expiring(school.id, school.name, what, day))
    return sorted(found, key=lambda item: (item.expires_on, item.id, item.what))


@dataclass(frozen=True)
class NcesSchools:
    """What the NCES files hold that the supplement is checked against."""

    private_ids: frozenset[str]
    """Every private school id in the NCES files, kept or not."""
    kept_private: pl.DataFrame
    kept_public: pl.DataFrame
    """The kept NCES schools: ``id``, ``name``, ``street``, ``city``, ``state``,
    ``zip``, ``lat`` and ``lon``."""


@dataclass(frozen=True)
class SupplementRows:
    """The supplement's rows of the school schema, and what the build checked."""

    rows: pl.DataFrame
    """One row per entry, with its drop reason."""
    listed_by: dict[str, str]
    """Entries the NCES files list, each with the NCES id that lists it."""
    cleared: int
    """Nearby NCES schools reviewers ruled are other schools (``distinct_from``)."""
    oldest_evidence_on: date | None
    """The earliest :attr:`SupplementSchool.evidence_on` of the entries."""
    oldest_address_checked_on: date | None
    """The earliest ``address_checked_on`` of the entries."""
    expiring: list[Expiring]
    """Checks of the kept entries that go stale within :data:`EXPIRY_WARNING_DAYS`."""


def assemble_supplement(
    supplement: Supplement,
    config: DirectoryConfig,
    nces: NcesSchools,
    today: date,
) -> SupplementRows:
    """Return one row per supplement entry, with its drop reason.

    Rows carry the audit columns of the NCES rows (``coordinates_long`` and
    ``coordinates_rounded`` false, ``geocoded`` true): supplement coordinates are
    written with at most six decimals. ``today`` is the build's date, against
    which evidence and addresses age (:func:`evidence_stale`, :func:`address_stale`).

    Raises:
        SupplementError: if an entry that would be kept (not listed by NCES, not
            stale) needs a reviewer's ruling (:func:`review_conflicts`,
            :func:`station_twins`).
    """
    rules = config.filters
    max_age = config.supplement.max_evidence_age_days if config.supplement else None
    entries = supplement.schools
    listed_by: dict[str, str] = {}
    problems: list[str] = []
    kept_nces = pl.concat([nces.kept_private, nces.kept_public])
    stale = [evidence_stale(school, today, max_age) for school in entries]
    moved = [address_stale(school, today) for school in entries]
    for school, dropped in zip(entries, map(max, stale, moved), strict=True):
        nces_id = listed_by_nces(school, nces.private_ids, nces.kept_private)
        if nces_id is not None:
            listed_by[school.id] = nces_id
            continue
        if dropped:  # left off the map whatever a reviewer rules
            continue
        problems += review_conflicts(school, nces.kept_private, nces.kept_public)
        problems += station_twins(school, kept_nces)
    if problems:
        raise SupplementError(
            "supplement entries need a reviewer's ruling (list NCES ids that are other "
            "schools in distinct_from, add a current evidence_url, or delete the entry):\n  "
            + "\n  ".join(problems)
        )
    listed = [school.id in listed_by for school in entries]
    frame = pl.DataFrame(
        {
            "id": [s.id for s in entries],
            "name": [s.name for s in entries],
            "street": [s.street for s in entries],
            "city": [s.city for s in entries],
            "state": [s.state for s in entries],
            "zip": [s.zip for s in entries],
            "state_fips": [s.county_fips[:2] for s in entries],
            "county_fips": [s.county_fips for s in entries],
            "county_name": [s.county_name for s in entries],
            "LAT": [repr(s.lat) for s in entries],
            "LON": [repr(s.lon) for s in entries],
            "grade_low": [s.grade_low for s in entries],
            "grade_high": [s.grade_high for s in entries],
            "school_year": [school_year_of(s.evidence_on) for s in entries],
            "listed": listed,
            "stale": stale,
            "moved": moved,
        },
        schema={
            **{c: pl.String() for c in ("id", "name", "street", "city", "state", "zip")},
            **{c: pl.String() for c in ("state_fips", "county_fips", "county_name")},
            **{c: pl.String() for c in ("LAT", "LON", "grade_low", "grade_high", "school_year")},
            "listed": pl.Boolean(),
            "stale": pl.Boolean(),
            "moved": pl.Boolean(),
        },
    )
    frame = frame.with_columns(
        lat_e6=coordinate_e6("LAT", 90.0), lon_e6=coordinate_e6("LON", 180.0)
    ).with_columns(lat=degrees("lat_e6"), lon=degrees("lon_e6"))
    level = (
        pl.when(pl.col("grade_high").is_null())
        .then(pl.lit(None, pl.String))
        .when(pl.col("grade_low").is_in(_SECONDARY_LOW))
        .then(pl.lit(filters.PSS_LEVEL_LABELS["2"]))
        .when(pl.col("grade_high").is_in(_HIGH))
        .then(pl.lit(filters.PSS_LEVEL_LABELS["3"]))
        .otherwise(pl.lit(filters.PSS_LEVEL_LABELS["1"]))
    )
    schools = frame.select(
        "id",
        kind=pl.lit("private"),
        kind_flags=pl.lit(KIND_PRIVATE, pl.UInt8),
        name="name",
        district_id=pl.lit(None, pl.String),
        district_name=pl.lit(None, pl.String),
        street="street",
        city="city",
        state="state",
        zip="zip",
        state_fips="state_fips",
        county_fips="county_fips",
        county_name="county_name",
        locale=pl.lit(None, pl.String),
        lat="lat",
        lon="lon",
        lat_e6="lat_e6",
        lon_e6="lon_e6",
        grade_low="grade_low",
        grade_high="grade_high",
        grades_offered=pl.lit(None, pl.List(pl.String)),
        level=level,
        school_type=pl.lit(None, pl.String),
        charter=pl.lit(None, pl.Boolean),
        virtual=pl.lit(None, pl.String),
        status=pl.lit(None, pl.String),
        enrollment=pl.lit(None, pl.Int32),
        enrollment_flag=pl.lit(None, pl.String),
        phone=pl.lit(None, pl.String),
        website=pl.lit(None, pl.String),
        school_year="school_year",
        drop_reason=filters.first_reason(
            [
                filters.coordinates_check("lat_e6", "lon_e6"),
                filters.state_check("state_fips", rules.state_fips),
                filters.bounds_check("lat_e6", "lon_e6", rules.bounds),
                pl.when(pl.col("listed")).then(pl.lit(Reason.LISTED_BY_NCES.value)),
                pl.when(pl.col("stale")).then(pl.lit(Reason.EVIDENCE_STALE.value)),
                pl.when(pl.col("moved")).then(pl.lit(Reason.ADDRESS_STALE.value)),
            ]
        ),
        coordinates_rounded=pl.lit(value=False),
        coordinates_long=pl.lit(value=False),
        geocoded=pl.lit(value=True),
    )
    audit = ("coordinates_long", "coordinates_rounded", "geocoded")
    rows = schools.select(*SCHOOL_SCHEMA, *audit).cast(SCHOOL_SCHEMA)  # type: ignore[arg-type]
    cleared = sum(
        1
        for school in entries
        if school.id not in listed_by
        for nces_id in school.distinct_from
        if nces_id in set(kept_nces["id"].to_list())
    )
    return SupplementRows(
        rows=rows,
        listed_by=listed_by,
        cleared=cleared,
        oldest_evidence_on=min((school.evidence_on for school in entries), default=None),
        oldest_address_checked_on=min(
            (school.address_checked_on for school in entries), default=None
        ),
        expiring=expiring(
            [s for s, kept in zip(entries, rows["drop_reason"].is_null(), strict=True) if kept],
            today,
            max_age,
        ),
    )
