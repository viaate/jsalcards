"""Placing each school in its own public forecast zone, and its own time zone.

Every school of the directory (its NCES latitude and longitude) is placed in the
reference zone release (:data:`snowlight.weights.zonepolys.ZONE_RELEASES`, first
entry: ``z_18mr25``):

* ``inside``: the zone whose polygon covers the point (boundary included; a point
  on a line two zones share takes the first zone code in sort order, and is
  counted in :attr:`ZonePlacement.on_shared_boundary`);
* ``nearest``: a point outside every zone polygon (a shoreline or a pier, a point
  a few metres across a state line) takes the nearest zone whose polygon is within
  :data:`NEAREST_KM` of it, and the choice is logged (:attr:`ZonePlacement.nearest`);
  that zone's rows reach it school year by school year (below);
* ``county``: a point farther than that from every zone falls back to its county
  (:mod:`snowlight.weights.schools` placed it in one): for zone-coded products it
  takes the county rule of :mod:`snowlight.weights.count` (every zone the
  correlation release lists for the county), and it is logged as well.

Distances are measured on a local equirectangular approximation around the school
(sphere of radius 6,371.0088 km); within 2 km its error is well under 1%.

Which zone rows reach a school
==============================

A zone row reaches the schools inside the polygon of the zone version it was issued
for (:mod:`snowlight.weights.zonepolys`), whatever release that polygon comes from:
:func:`memberships` places every school's point in every such polygon.

A school's point can lie inside its zone as the reference release draws it and
outside every outline that zone had in an earlier school year (Waterside Plaza, on
the East River, is 16 m outside each outline ``NYZ072`` had from 2015-16 to
2022-23). :func:`place_by_year` checks every school year (the versions of each zone
code with rows that school year, :func:`year_versions`) for every school placed
``inside`` or ``nearest``, whose *own zone* is its reference zone:

* if a version of another zone with rows that school year covers the school, the
  school lay in that zone that year (its zone has been redrawn since, or its outline
  changed within the year) and takes the rows of the versions covering it only, as
  :func:`memberships` gives them;
* otherwise every version of its own zone with rows that school year that does not
  cover the school is a *miss*. When no version of its own zone covers the school
  that year (it lay outside every zone version of the year), it takes the rows of
  the missed versions when each lies within :data:`NEAREST_KM`
  (``nearest``), and beyond that it falls back to its county for that school year
  (``county``: the county rule's counts of that year, every code). When another
  version of its own zone covers it that year (the zone's outline changed within
  the school year), each missed version within :data:`NEAREST_KM` is taken
  (``nearest``) and one beyond it is not (``not_taken``);
* a school year in which its own zone has no rows gives the school no zone rows of
  its own zone (a quiet year, or a zone code not yet in use).

Every miss is logged per school and school year (:attr:`YearPlacement.outside`).
A school placed ``county`` takes the county rule in every school year and is not
checked.

Time zones
==========

The 6 AM rule is read in the school's own time zone: the ``TIME_ZONE`` of its
reference zone when that is a single time zone. The NWS marks a zone or a county
that a time zone line crosses with a two-letter code (``CE`` for Gulf County,
Florida, and its zones FLZ014 and FLZ114; ``Mm`` for the Navajo Nation's zones of
Arizona), without drawing the line, so a school in such a zone takes its county's
time zones, and the rule holds when it holds in either (as for the county rule). A
school of a split county whose own zone lies in one time zone (Gulf County's
coastal FLZ115, all Eastern) takes that zone's; a school placed ``county`` takes
its county's.
"""

import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import numpy.typing as npt
import polars as pl
import shapely

from snowlight.sources.nws.shapefile import Polygonal
from snowlight.weather.timezones import IANA_ZONES
from snowlight.weights.archive import SchoolYearFile
from snowlight.weights.schools import Placement
from snowlight.weights.zonepolys import VersionBook, ZonePolygonError, ZoneSet
from snowlight.weights.zones import CountyList

NEAREST_KM = 2.0
EARTH_RADIUS_KM = 6371.0088
_KM_PER_DEGREE = math.pi * EARTH_RADIUS_KM / 180.0
_SEARCH_DEGREES = 0.05
"""Bounding-box margin for the nearest-zone search (more than 2 km at any US latitude)."""

type ZoneMethod = Literal["inside", "nearest", "county"]
type Ints = npt.NDArray[np.int64]


@dataclass(frozen=True, slots=True)
class SchoolZone:
    """One placed school's zone and time zones."""

    school_id: str
    fips: str
    """The NWS county the school is placed in (:mod:`snowlight.weights.schools`)."""
    zone: str | None
    """The reference zone (``inside`` or ``nearest``), else the nearest zone found."""
    method: ZoneMethod
    distance_km: float
    """0 inside a zone; else the distance to :attr:`zone` (``inf`` when none is near)."""
    time_zones: tuple[str, ...]


@dataclass(slots=True)
class ZonePlacement:
    """Every placed school's zone, in the order of :attr:`Placement.schools`."""

    reference: str
    schools: list[SchoolZone]
    by_method: Counter[str] = field(default_factory=Counter)
    on_shared_boundary: int = 0
    time_zone_from_zone: int = 0
    """Schools of counties split by a time zone line whose own zone lies in one time zone."""
    time_zone_split_kept: int = 0
    """Schools of such counties whose zone is split too: they keep both time zones."""

    @property
    def nearest(self) -> list[SchoolZone]:
        """The schools placed in the nearest zone within :data:`NEAREST_KM`."""
        return [school for school in self.schools if school.method == "nearest"]

    @property
    def county(self) -> list[SchoolZone]:
        """The schools that fell back to their county."""
        return [school for school in self.schools if school.method == "county"]

    def per_zone(self) -> Counter[str]:
        """Schools per reference zone (``inside`` and ``nearest``)."""
        return Counter(
            school.zone for school in self.schools if school.method != "county" and school.zone
        )


def school_coordinates(
    frame: pl.DataFrame, placement: Placement
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Return the placed schools' longitudes and latitudes, in the order of the placement."""
    rows = {int(index): position for position, index in enumerate(frame["index"].to_list())}
    lon = frame["lon"].to_numpy().astype(np.float64)
    lat = frame["lat"].to_numpy().astype(np.float64)
    order = np.array([rows[school.index] for school in placement.schools], dtype=np.int64)
    return lon[order], lat[order]


def school_points(frame: pl.DataFrame, placement: Placement) -> npt.NDArray[np.object_]:
    """Return the placed schools' points, in the order of the placement."""
    lon, lat = school_coordinates(frame, placement)
    points = shapely.points(lon, lat)
    if not isinstance(points, np.ndarray):  # pragma: no cover - arrays in, array out
        raise TypeError("shapely.points returned a single point")
    return points


def local_km(geometry: Polygonal, lon: float, lat: float) -> Polygonal:
    """Return ``geometry`` in km on the equirectangular plane centred on (``lon``, ``lat``)."""
    scale = np.array([_KM_PER_DEGREE * math.cos(math.radians(lat)), _KM_PER_DEGREE])
    origin = np.array([lon, lat])
    moved = shapely.transform(geometry, lambda coords: (coords - origin) * scale)
    if not isinstance(moved, shapely.Polygon | shapely.MultiPolygon):  # pragma: no cover
        raise TypeError("a polygon transformed into another geometry type")
    return moved


def distance_km(geometry: Polygonal, lon: float, lat: float) -> float:
    """Return the distance from the point to ``geometry``, in km (see the module docstring)."""
    return float(shapely.distance(shapely.Point(0.0, 0.0), local_km(geometry, lon, lat)))


def zone_time_zones(codes: Sequence[str]) -> tuple[str, ...]:
    """Return the IANA zones of a zone's ``TIME_ZONE`` codes (``("CE",)`` gives two).

    Raises:
        ZonePolygonError: a letter is not one of :data:`IANA_ZONES`.
    """
    letters = {letter for code in codes for letter in code}
    unknown = sorted(letters - set(IANA_ZONES))
    if unknown:
        raise ZonePolygonError(f"time zone codes {sorted(codes)}: unknown letters {unknown}")
    return tuple(sorted({IANA_ZONES[letter] for letter in letters}))


def place_in_zones(
    frame: pl.DataFrame,
    placement: Placement,
    reference: ZoneSet,
    counties: CountyList,
) -> ZonePlacement:
    """Place every school of ``placement`` in the reference release (see the module docstring).

    Raises:
        ZonePolygonError: a zone's ``TIME_ZONE`` holds a letter :data:`IANA_ZONES` lacks.
    """
    lon, lat = school_coordinates(frame, placement)
    points = shapely.points(lon, lat)
    codes = sorted(reference.shapes)
    geometries = [reference.shapes[code].geometry for code in codes]
    tree = shapely.STRtree(geometries)
    school_index, zone_index = tree.query(points, predicate="intersects")
    inside: dict[int, list[str]] = defaultdict(list)
    for school, zone in zip(school_index.tolist(), zone_index.tolist(), strict=True):
        inside[school].append(codes[zone])
    result = ZonePlacement(reference=reference.name, schools=[])
    for position, school in enumerate(placement.schools):
        x, y = float(lon[position]), float(lat[position])
        found = sorted(inside.get(position, []))
        method: ZoneMethod
        if found:
            zone, method, away = found[0], "inside", 0.0
            if len(found) > 1:
                result.on_shared_boundary += 1
        else:
            zone, away = _nearest(tree, codes, geometries, x, y)
            method = "nearest" if zone is not None and away <= NEAREST_KM else "county"
        zones = counties.counties[school.nws_fips].time_zones
        if method != "county" and zone is not None:
            own = zone_time_zones(reference.shapes[zone].time_zones)
            if len(own) == 1:
                if len(zones) > 1:
                    result.time_zone_from_zone += 1
                zones = own
            elif len(zones) > 1:
                result.time_zone_split_kept += 1
        result.by_method[method] += 1
        result.schools.append(
            SchoolZone(school.school_id, school.nws_fips, zone, method, away, zones)
        )
    return result


def _nearest(
    tree: shapely.STRtree, codes: Sequence[str], geometries: Sequence[Polygonal], x: float, y: float
) -> tuple[str | None, float]:
    box = shapely.box(
        x - _SEARCH_DEGREES, y - _SEARCH_DEGREES, x + _SEARCH_DEGREES, y + _SEARCH_DEGREES
    )
    best: tuple[float, str] | None = None
    for index in tree.query(box).tolist():
        away = distance_km(geometries[index], x, y)
        if best is None or (away, codes[index]) < best:
            best = (away, codes[index])
    if best is None:
        return None, math.inf
    return best[1], best[0]


def memberships(
    polygons: Mapping[str, Polygonal],
    frame: pl.DataFrame,
    placement: Placement,
    zoned: ZonePlacement,
) -> dict[str, Ints]:
    """Return, per polygon key, the positions (in :attr:`Placement.schools`) of the schools
    inside it (boundary included; schools placed ``county`` are left out)."""
    points = school_points(frame, placement)
    keys = sorted(polygons)
    tree = shapely.STRtree([polygons[key] for key in keys])
    school_index, polygon_index = tree.query(points, predicate="intersects")
    found: dict[str, set[int]] = defaultdict(set)
    for school, polygon in zip(school_index.tolist(), polygon_index.tolist(), strict=True):
        if zoned.schools[school].method != "county":
            found[keys[polygon]].add(school)
    return {key: np.array(sorted(found.get(key, set())), dtype=np.int64) for key in keys}


# --- school year by school year ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class YearVersions:
    """The zone versions with rows in each school year."""

    by_year: Mapping[int, Mapping[str, frozenset[str]]]
    """School year to zone code to the polygon keys of its versions with rows that year."""
    rows: Mapping[tuple[int, str], int]
    """(school year, polygon key) to the key's rows that school year."""
    code_of: Mapping[str, str]
    """Polygon key to its zone code."""


def year_versions(
    files: Iterable[SchoolYearFile],
    book: VersionBook,
    set_aside: Mapping[int, frozenset[str]] | None = None,
) -> YearVersions:
    """Return the zone versions with rows in each school year of ``files``.

    ``set_aside`` gives, per school year, the events whose rows the counting does not
    use (storm-based events with polygons, :mod:`snowlight.weights.schoolcount`).

    Raises:
        ZonePolygonError: a zone row's version has no polygon.
    """
    skip = set_aside or {}
    by_year: dict[int, dict[str, set[str]]] = {}
    rows: Counter[tuple[int, str]] = Counter()
    code_of: dict[str, str] = {}
    for file in files:
        found = by_year.setdefault(file.year, defaultdict(set))
        aside = skip.get(file.year, frozenset())
        for row in file.rows:
            if row.ugc[2] != "Z" or row.event_key in aside:
                continue
            key = book.key_of(row)
            found[row.ugc].add(key)
            rows[(file.year, key)] += 1
            code_of[key] = row.ugc
    return YearVersions(
        {
            year: {ugc: frozenset(keys) for ugc, keys in sorted(codes.items())}
            for year, codes in sorted(by_year.items())
        },
        dict(rows),
        code_of,
    )


type YearMethod = Literal["nearest", "county", "not_taken"]


@dataclass(frozen=True, slots=True)
class MissedVersion:
    """One version of a school's own zone, with rows that school year, not covering it."""

    key: str
    distance_km: float
    rows: int
    """The version's rows that school year."""
    taken: bool
    """Whether its rows of that school year reach the school."""


@dataclass(frozen=True, slots=True)
class OutsideOwnZone:
    """One school year in which versions of a school's own zone do not cover it."""

    position: int
    school_id: str
    fips: str
    year: int
    zone: str
    missed: tuple[MissedVersion, ...]
    inside_own_zone: bool
    """Whether another version of its own zone, with rows that school year, covers it."""
    method: YearMethod

    @property
    def distance_km(self) -> float:
        """The farthest missed version's distance."""
        return max(item.distance_km for item in self.missed)


@dataclass(slots=True)
class YearPlacement:
    """What :func:`place_by_year` found (see the module docstring)."""

    nearest_km: float
    outside: list[OutsideOwnZone] = field(default_factory=list)
    extra: dict[tuple[str, int], list[int]] = field(default_factory=dict)
    """(polygon key, school year) to the positions it reaches that year besides the
    schools inside it."""
    county_years: dict[int, frozenset[int]] = field(default_factory=dict)
    """Position to the school years it takes its county's counts for."""
    in_other_zone: Counter[str] = field(default_factory=Counter)
    """Reference zone to the school years (summed over its schools) in which a version
    of it missed one of its schools that a version of another zone (with rows that
    year) covered: the school takes the rows of the versions covering it only."""
    schools_in_other_zone: int = 0

    def extras(self) -> dict[int, frozenset[tuple[str, int]]]:
        """Position to the (polygon key, school year) pairs reaching it beyond its polygons."""
        found: dict[int, set[tuple[str, int]]] = defaultdict(set)
        for pair, positions in self.extra.items():
            for position in positions:
                found[position].add(pair)
        return {position: frozenset(pairs) for position, pairs in found.items()}

    def by_method(self) -> Counter[str]:
        """School years logged, by method."""
        return Counter(item.method for item in self.outside)


def place_by_year(  # noqa: PLR0913
    polygons: Mapping[str, Polygonal],
    versions: YearVersions,
    zoned: ZonePlacement,
    members: Mapping[str, Ints],
    *,
    coordinates: tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]],
    nearest_km: float = NEAREST_KM,
) -> YearPlacement:
    """Check every school year for every school placed ``inside`` or ``nearest``
    (see the module docstring).

    ``members`` is :func:`memberships`' answer and ``coordinates`` the schools'
    longitudes and latitudes (:func:`school_coordinates`), both in the order of
    ``zoned.schools``.
    """
    lon, lat = coordinates
    covering: dict[int, set[str]] = defaultdict(set)
    for key, positions in members.items():
        for position in positions.tolist():
            covering[position].add(key)
    result = YearPlacement(nearest_km)
    extra: dict[tuple[str, int], set[int]] = defaultdict(set)
    for position, school in enumerate(zoned.schools):
        if school.method == "county" or school.zone is None:
            continue
        check = _SchoolCheck(
            school,
            position,
            covering.get(position, set()),
            (float(lon[position]), float(lat[position])),
        )
        elsewhere = False
        county: set[int] = set()
        for year, codes in versions.by_year.items():
            found = check.year(year, codes, versions, polygons, nearest_km)
            if found is None:
                continue
            if found == "elsewhere":
                result.in_other_zone[school.zone] += 1
                elsewhere = True
                continue
            result.outside.append(found)
            if found.method == "county":
                county.add(year)
            for item in found.missed:
                if item.taken:
                    extra[(item.key, year)].add(position)
        result.schools_in_other_zone += elsewhere
        if county:
            result.county_years[position] = frozenset(county)
    result.extra = {pair: sorted(positions) for pair, positions in sorted(extra.items())}
    return result


@dataclass(slots=True)
class _SchoolCheck:
    school: SchoolZone
    position: int
    inside: set[str]
    point: tuple[float, float]
    distances: dict[str, float] = field(default_factory=dict)

    def distance(self, key: str, polygons: Mapping[str, Polygonal]) -> float:
        if key not in self.distances:
            self.distances[key] = distance_km(polygons[key], *self.point)
        return self.distances[key]

    def year(
        self,
        year: int,
        codes: Mapping[str, frozenset[str]],
        versions: YearVersions,
        polygons: Mapping[str, Polygonal],
        nearest_km: float,
    ) -> "OutsideOwnZone | Literal['elsewhere'] | None":
        own_zone = self.school.zone or ""
        own = codes.get(own_zone)
        if not own or own <= self.inside:
            return None
        if any(
            versions.code_of[key] != own_zone and (year, key) in versions.rows
            for key in self.inside
            if key in versions.code_of
        ):
            return "elsewhere"
        missed = [(key, self.distance(key, polygons)) for key in sorted(own - self.inside)]
        within = [away <= nearest_km for _, away in missed]
        inside_own = bool(own & self.inside)
        method: YearMethod
        if inside_own:
            taken, method = within, ("nearest" if all(within) else "not_taken")
        elif all(within):
            taken, method = within, "nearest"
        else:
            taken, method = [False] * len(missed), "county"
        return OutsideOwnZone(
            self.position,
            self.school.school_id,
            self.school.fips,
            year,
            own_zone,
            tuple(
                MissedVersion(key, away, versions.rows[(year, key)], take)
                for (key, away), take in zip(missed, taken, strict=True)
            ),
            inside_own,
            method,
        )
