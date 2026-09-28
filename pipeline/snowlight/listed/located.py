"""Where a row says its organization is, and whether the record the matcher chose is there.

Many lists write where each organization is: a state, a county, a city
(Hearst's ``"Jackson, Kansas City, MO"``, ABC's ``{"state": "New Jersey",
"county": "Burlington"}``, the Emergency Closing Center's ``"SCHILLER PARK"``).
The matcher does not read them: it reads a name in its list's registry context.
So when the name has a namesake in the market and the organization itself is not
in the directory, or the list carries organizations beyond its registered
states, an accepted match can name a record elsewhere: ``"DIST #81"`` of
Schiller Park read as Joliet's ``"Union SD 81"``, Connecticut's ``"Canton
Public Schools"`` on NBC Boston's list read as Canton, Massachusetts.

This module is a guard that only ever takes a match away. :func:`stated_places`
reads the places a row names (:data:`PLACE_FIELDS`, per list variant, only the
fields that describe the organization: Gray's location fields, which on many
rows are the feed's defaults and not the organization's (KYTV files Missouri
towns under ``"ARKANSAS"``, KLTV Bullard ISD under Shelby County), Nexstar's
``locality`` (a town on some rows, a county on others, a default on some lists)
and WRAL's roster counties are not read). :class:`Gazetteer` resolves
them against the school directory (a city: the directory records in that town)
and the NWS county outlines (a county), within the row's own state or else its
list's states, and :meth:`Gazetteer.verdict` compares them with the records the
matcher chose:

* ``conflict``: the row names a state none of the records is in, or every city
  and county it names that can be resolved (a place's town and county both
  count) lies out of reach of every record
  (a city: :data:`CITY_REACH_KM` from any directory record of that town; a
  county: :data:`COUNTY_REACH_KM` beyond its outline). For a district, its
  office and every school count as its places.
* ``agrees``: some place the row names is within reach (or the row names only a
  state, and a record is in it).
* ``unknown``: the row names no place that can be resolved.

A listing (one name on one list) is one organization, so a single conflicting
row takes the match away from all of its rows (see :mod:`snowlight.listed.build`).
"""

import json
import math
import re
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

import numpy as np
import numpy.typing as npt
import polars as pl
import shapely
from shapely.affinity import scale

from snowlight.weights.zones import CountyList

CITY_REACH_KM: Final = 20.0
"""How far a record may lie from the nearest directory record of the town a row
names (a mailing town is often the next town over)."""
COUNTY_REACH_KM: Final = 10.0
"""How far a record may lie outside the county a row names (a campus by the line)."""
EARTH_KM: Final = 6371.0088
KM_PER_DEGREE: Final = 111.195

STATE_NAMES: Final[Mapping[str, str]] = {
    "ALABAMA": "AL", "ARIZONA": "AZ", "ARKANSAS": "AR", "CALIFORNIA": "CA", "COLORADO": "CO",
    "CONNECTICUT": "CT", "DELAWARE": "DE", "DISTRICT OF COLUMBIA": "DC", "FLORIDA": "FL",
    "GEORGIA": "GA", "IDAHO": "ID", "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA",
    "KANSAS": "KS", "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD",
    "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS",
    "MISSOURI": "MO", "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV", "NEW HAMPSHIRE": "NH",
    "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY", "NORTH CAROLINA": "NC",
    "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK", "OREGON": "OR", "PENNSYLVANIA": "PA",
    "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC", "SOUTH DAKOTA": "SD", "TENNESSEE": "TN",
    "TEXAS": "TX", "UTAH": "UT", "VERMONT": "VT", "VIRGINIA": "VA", "WASHINGTON": "WA",
    "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WYOMING": "WY",
}  # fmt: skip
"""The 48 contiguous states and DC by name (a row's ``"New Jersey"``)."""
USPS: Final = frozenset(STATE_NAMES.values())


@dataclass(frozen=True, slots=True)
class Place:
    """One place a row names for its organization: a state, and a city or county in it."""

    state: str | None = None
    city: str | None = None
    county: str | None = None


type Places = tuple[Place, ...]


class Verdict(StrEnum):
    """Whether a row's places agree with the records a match names."""

    AGREES = "agrees"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"


# Reading the places a row names ------------------------------------------------------

_ZIP_TAIL: Final = re.compile(r"[\s,]+([A-Za-z]{2})\.?\s*(\d{5}(?:-\d{4})?)?\s*$")
_QUALIFIED: Final = re.compile(r"^(.*?)\s*[,(]\s*([A-Za-z]{2})\s*\)?\s*(?:COUNTY)?\s*$", re.I)
_BLANK: Final = frozenset({"", "NA", "N/A", "NONE", "NULL", "OTHER", "USA", "OK"})


def _text(extra: Mapping[str, object], key: str) -> str | None:
    value = extra.get(key)
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned if cleaned.upper() not in _BLANK else None


def state_code(text: str | None) -> str | None:
    """A USPS code for a state written as its code or its name (``"New Jersey"``)."""
    if not text:
        return None
    key = " ".join(re.sub(r"[^A-Za-z ]", " ", text).upper().split())
    if key in USPS:
        return key
    return STATE_NAMES.get(key)


def _city(text: str | None) -> tuple[str | None, str | None]:
    """A city as a row writes it, and the state it adds (``"READING PA 19606"``)."""
    if text is None:
        return None, None
    match = _ZIP_TAIL.search(text)
    if match is not None and state_code(match.group(1)) is not None:
        head = text[: match.start()].strip(" ,")
        return (head or None), state_code(match.group(1))
    return text, None


def _county(text: str | None) -> tuple[str | None, str | None]:
    """A county as a row writes it, and the state it adds (``"LAKE, IL COUNTY"``)."""
    if text is None:
        return None, None
    match = _QUALIFIED.match(text)
    if match is not None and state_code(match.group(2)) is not None:
        return (match.group(1).strip() or None), state_code(match.group(2))
    return text, None


def _place(state: str | None, city: str | None = None, county: str | None = None) -> Place | None:
    city_name, city_state = _city(city)
    county_name, county_state = _county(county)
    code = state_code(state) or city_state or county_state
    if code is None and city_name is None and county_name is None:
        return None
    return Place(state=code, city=city_name, county=county_name)


def _split(text: str | None, sep: str, parts: int) -> list[str | None] | None:
    if text is None or text.count(sep) != parts - 1:
        return None
    return [piece.strip() or None for piece in text.split(sep)]


def _hearst_rows(extra: Mapping[str, object]) -> list[Place | None]:
    parts = _split(_text(extra, "location"), ",", 3)
    if not parts:
        return []
    if state_code(parts[0]) is not None:
        # "ok, okc, OK": a placeholder, not a county and a town; only the state holds.
        return [_place(parts[2])]
    return [_place(parts[2], city=parts[1], county=parts[0])]


def _hearst_address(extra: Mapping[str, object]) -> list[Place | None]:
    parts = _split(_text(extra, "address"), "/", 3)
    return [_place(parts[2], city=parts[0], county=parts[1])] if parts else []


def _hearst_next(extra: Mapping[str, object]) -> list[Place | None]:
    raw = extra.get("locations")
    try:
        items = json.loads(raw) if isinstance(raw, str) else []
    except ValueError:
        return []
    return [
        _place(item.get("state"), city=item.get("city"), county=item.get("county"))
        for item in items
        if isinstance(item, dict)
    ]


def _fields(
    state: str | None = None, city: str | None = None, county: str | None = None
) -> Callable[[Mapping[str, object]], list[Place | None]]:
    def read(extra: Mapping[str, object]) -> list[Place | None]:
        return [
            _place(
                _text(extra, state) if state else None,
                city=_text(extra, city) if city else None,
                county=_text(extra, county) if county else None,
            )
        ]

    return read


def _address_state(extra: Mapping[str, object]) -> list[Place | None]:
    """``"Address: 3 Washburn Square Leicester, MA 01524"``: only the state is certain."""
    text = _text(extra, "address")
    match = _ZIP_TAIL.search(text) if text else None
    return [_place(match.group(1))] if match is not None else []


PLACE_FIELDS: Final[Mapping[str, Callable[[Mapping[str, object]], list[Place | None]]]] = {
    "abc-legacy-list": _fields(state="state", county="county"),
    "abc-otv-list": _fields(state="state", county="county"),
    "cox-arc-page": _fields(county="county"),
    "ecc-legacy-page": _fields(city="City"),
    "fox-newsticker-county": _fields(county="county"),
    "hearst-ibsys": _hearst_address,
    "hearst-next": _hearst_next,
    "hearst-rows": _hearst_rows,
    "heritage-arc-content": _fields(state="state", city="city", county="county"),
    "heritage-arc-page": _fields(state="state", city="city", county="county"),
    "heritage-bti-table": _fields(city="address"),
    "nbc-wp-json": _fields(state="state"),
    "nbc-wp-page": _fields(state="state"),
    "news12-jsp": _fields(city="city"),
    "newsticker-html": _fields(city="location"),
    "nexstar-app-feed": _fields(city="city", county="county"),
    "nexstar-ecc-json": _fields(state="State", city="City", county="County"),
    "nexstar-newsticker-table": _fields(city="town"),
    "nexstar-wp-closings": _fields(city="locality"),
    "scripps-closings-json": _fields(county="county"),
    "townsquare-closings-table": _fields(city="city", county="group"),
    "weatherthreat-js": _fields(state="org_state", city="org_city", county="county"),
    "whdh-closings-block": _address_state,
    "wtop-page": _fields(state="org_state", city="org_city"),
}
"""For each list variant that writes where an organization is: how to read it."""


def stated_places(variant: str, extra: Mapping[str, object]) -> Places:
    """The places a row names for its organization (none when its variant writes none)."""
    reader = PLACE_FIELDS.get(variant)
    if reader is None:
        return ()
    found = {place for place in reader(extra) if place is not None}
    return tuple(sorted(found, key=lambda p: (p.state or "", p.city or "", p.county or "")))


# Resolving places ---------------------------------------------------------------------

_ABBREVIATIONS: Final[Mapping[str, str]] = {
    "ST": "SAINT", "STE": "SAINTE", "FT": "FORT", "MT": "MOUNT",
    "N": "NORTH", "S": "SOUTH", "E": "EAST", "W": "WEST",
}  # fmt: skip
_COUNTY_WORDS: Final = frozenset({"COUNTY", "CO", "PARISH", "CNTY"})


def place_key(text: str, *, county: bool = False) -> str:
    """A town's or county's name as it is compared: letters only, abbreviations spelled out.

    ``"St. Louis"`` and ``"SAINT LOUIS"`` agree, and so do ``"LAGRANGE"`` and ``"La
    Grange"`` or ``"O'Fallon"`` and ``"O Fallon"`` (spaces do not count); for a county,
    a trailing ``County``/``Co``/``Parish`` is dropped (``"MILWAUKEE CO"`` is
    ``"MILWAUKEE"``).
    """
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    words = re.sub(r"[^A-Za-z0-9]+", " ", folded.replace("&", " AND ").replace("'", "")).upper()
    tokens = words.split()
    if len(tokens) > 1 and tokens[0] in _ABBREVIATIONS:
        tokens[0] = _ABBREVIATIONS[tokens[0]]
    if county:
        while len(tokens) > 1 and tokens[-1] in _COUNTY_WORDS:
            tokens.pop()
    return "".join(tokens)


type Points = npt.NDArray[np.float64]
"""An ``(n, 2)`` array of ``(lat, lon)`` degrees."""


def _km(first: Points, second: Points) -> float:
    """The smallest great-circle distance between two sets of points."""
    lat1, lon1 = np.radians(first[:, 0])[:, None], np.radians(first[:, 1])[:, None]
    lat2, lon2 = np.radians(second[:, 0])[None, :], np.radians(second[:, 1])[None, :]
    half = (
        np.sin((lat2 - lat1) / 2) ** 2
        + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    )
    return float(2 * EARTH_KM * np.arcsin(np.sqrt(np.clip(half, 0.0, 1.0))).min())


@dataclass(frozen=True, slots=True)
class _Outline:
    """A county's outline with longitude scaled so plane distances are near kilometres."""

    geometry: shapely.Geometry
    factor: float


def _outline(geometry: shapely.Geometry) -> _Outline:
    latitude = float(shapely.get_y(shapely.centroid(geometry)))
    factor = math.cos(math.radians(latitude))
    return _Outline(scale(geometry, xfact=factor, yfact=1.0, origin=(0.0, 0.0)), factor)


class Gazetteer:
    """Towns, counties and record locations, to compare a row's places with a match."""

    def __init__(
        self,
        cities: Mapping[tuple[str, str], Points],
        counties: Mapping[tuple[str, str], Sequence[shapely.Geometry]],
        records: Mapping[str, tuple[str, Points]],
    ) -> None:
        self._cities = dict(cities)
        self._counties = {key: [_outline(g) for g in found] for key, found in counties.items()}
        self._records = dict(records)

    @classmethod
    def build(
        cls, schools: pl.DataFrame, districts: pl.DataFrame, county_list: CountyList | None
    ) -> "Gazetteer":
        """From the directory's schools and districts (id, district id, city, state, lat,
        lon) and the NWS county outlines."""
        towns: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
        places: dict[str, list[tuple[float, float]]] = defaultdict(list)
        states: dict[str, str] = {}
        for record_id, city, state, lat, lon in districts.select(
            "district_id", "city", "state", "lat", "lon"
        ).iter_rows():
            if lat is None or lon is None:
                continue
            states[str(record_id)] = str(state)
            places[str(record_id)].append((float(lat), float(lon)))
            if city:
                towns[(str(state), place_key(str(city)))].append((float(lat), float(lon)))
        for record_id, district, city, state, lat, lon in schools.select(
            "id", "district_id", "city", "state", "lat", "lon"
        ).iter_rows():
            if lat is None or lon is None:
                continue
            point = (float(lat), float(lon))
            states[str(record_id)] = str(state)
            places[str(record_id)].append(point)
            if district:
                places[str(district)].append(point)
            if city:
                towns[(str(state), place_key(str(city)))].append(point)
        outlines: dict[tuple[str, str], list[shapely.Geometry]] = defaultdict(list)
        if county_list is not None:
            for county in county_list.counties.values():
                outlines[(county.state, place_key(county.name, county=True))].append(
                    county.geometry
                )
        return cls(
            {key: np.array(points, dtype=np.float64) for key, points in towns.items()},
            outlines,
            {
                key: (states[key], np.array(points, dtype=np.float64))
                for key, points in places.items()
            },
        )

    def _near_city(self, key: tuple[str, str], targets: Points) -> bool | None:
        points = self._cities.get(key)
        if points is None or not len(targets):
            return None
        return _km(points, targets) <= CITY_REACH_KM

    def _near_county(self, key: tuple[str, str], targets: Points) -> bool | None:
        outlines = self._counties.get(key)
        if not outlines or not len(targets):
            return None
        for outline in outlines:
            xs = targets[:, 1] * outline.factor
            dots = shapely.points(xs, targets[:, 0])
            distance = float(np.min(shapely.distance(outline.geometry, dots)))
            if distance * KM_PER_DEGREE <= COUNTY_REACH_KM:
                return True
        return False

    def _place_verdict(
        self, place: Place, targets: Sequence[str], states: Collection[str]
    ) -> Verdict:
        located = [self._records[t] for t in targets if t in self._records]
        if not located:
            return Verdict.UNKNOWN
        if place.state is not None:
            located = [(state, points) for state, points in located if state == place.state]
            if not located:
                return Verdict.CONFLICT
        points = np.vstack([points for _state, points in located])
        where = (place.state,) if place.state is not None else tuple(sorted(states))
        known: list[bool] = []
        if place.city is not None:
            key = place_key(place.city)
            known += [
                near
                for state in where
                if (near := self._near_city((state, key), points)) is not None
            ]
        if place.county is not None:
            key = place_key(place.county, county=True)
            known += [
                near
                for state in where
                if (near := self._near_county((state, key), points)) is not None
            ]
        if known:
            return Verdict.AGREES if any(known) else Verdict.CONFLICT
        return Verdict.AGREES if place.state is not None else Verdict.UNKNOWN

    def verdict(
        self, places: Iterable[Place], targets: Sequence[str], states: Collection[str]
    ) -> Verdict:
        """Whether a row's places agree with the records ``targets`` a match names.

        ``states`` are the row's list's states, where a place without a state is
        looked for.
        """
        found = {self._place_verdict(place, targets, states) for place in places}
        if Verdict.AGREES in found:
            return Verdict.AGREES
        return Verdict.CONFLICT if Verdict.CONFLICT in found else Verdict.UNKNOWN
