"""Public forecast zone polygons, as each row's zone stood when its product was issued.

The weights place every school in the public forecast zone its own point lies in
(:mod:`snowlight.weights.schoolzones`) and give it the warnings of that zone. A zone
code names an area that the NWS redraws now and then (Salt Lake City's valley and
mountain zones were ``UTZ003`` and ``UTZ008`` until 30 March 2021, then ``UTZ105``
and ``UTZ111``), so a row has to be read against the zone polygon that was in force
when its product was issued. This module finds that polygon for every zone row.

Which version of a zone a row was issued for
============================================

Every row of IEM's school-year files carries ``area2d``: the area, in km², of the
UGC outline IEM joined to the row, which is the outline IEM held for that zone when
the product was issued, from the NWS zone release it had loaded (for a few zones it
held two at once, and their rows go back and forth between them:
:func:`alternating_outlines`). IEM measures it in the
US National Atlas Equal Area projection (EPSG:2163, a Lambert azimuthal equal-area
projection of a sphere of radius 6,370,997 m centred on 45° N 100° W), which
:func:`equal_area_km2` reproduces: on the 1,842 zones of IEM's full-resolution
rows of 2025-01-21 compared with the NWS file ``z_18mr25``, the areas agree to
within a few parts in a million when the polygons are the same. A zone *version*
is a zone code with one ``area2d`` value (:class:`Version`).

Where each version's polygon comes from
=======================================

* **The NWS zone release files still served** (:data:`ZONE_RELEASES`, listed with
  their MD5 sums on https://www.weather.gov/gis/PublicZones): ``z_18mr25`` (in
  force from 18 March 2025) and ``z_16ap26`` (from 16 April 2026). A version whose
  ``area2d`` equals the equal-area size of the zone's polygon in one of them, to
  within :data:`AREA_TOLERANCE` (relative), is that polygon: most zones were not
  redrawn after October 2019, and their rows match this way. The NWS serves no zone
  release older than ``z_18mr25``: of the 155 file names in its zone change log
  (:data:`ZONE_CHANGE_LOG`), only ``z_18mr25.zip`` answers, and a ``z_DDmmYY.zip``
  for every release date of the correlation files answers 404 (HEAD, 2026-09-27).
* **IEM's archived copy of the NWS polygon** for the other versions: IEM's
  ``watchwarn.py`` returns, with ``simple=0``, each row's zone at full resolution
  (the polygon IEM loaded from the NWS release of the time). :func:`plan_requests`
  picks, from the school-year rows, the fewest requests of one office, one code
  and one minute of begin times that together hold a row of every such version
  (greedy set cover, deterministic), and :func:`read_version_file` takes each zone
  polygon whose ``AREA_KM2`` is the version's ``area2d``. The polygon is kept only
  when its own equal-area size agrees with ``area2d`` to within
  :data:`AREA_TOLERANCE`.

A version that neither gives a polygon stops the build (:class:`ZonePolygonError`):
its rows could not be placed, and nothing is substituted for them.

A version's polygon is a key into :attr:`VersionBook.polygons` (``z_18mr25/UTZ105``,
``iem/UTZ003/3563.4971``), so a polygon shared by many versions (the same zone
matched within the tolerance) is placed once.

The reference tiling
====================

``z_18mr25`` is also the reference for where each school is
(:mod:`snowlight.weights.schoolzones`): the zone its point lies in, the nearest
zone within 2 km, or its county. :func:`read_zone_set` keeps every zone of the
contiguous states and DC, with the zone's time zone codes.
"""

import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import numpy as np
import numpy.typing as npt
import shapely

from snowlight.output import JSONValue
from snowlight.sources.nws.boundaries import BoundaryRelease
from snowlight.sources.nws.http import CachedFile
from snowlight.sources.nws.iem import WATCHWARN_URL
from snowlight.sources.nws.shapefile import Polygonal, ShapefileError, polygonal, read_zip
from snowlight.weather.hazards import CONUS_STATES
from snowlight.weights.archive import EventRow
from snowlight.weights.cache import WeightsCache, cache_path

ZONE_RELEASES: tuple[BoundaryRelease, ...] = (
    BoundaryRelease(
        kind="zone",
        valid_from=date(2025, 3, 18),
        url="https://www.weather.gov/source/gis/Shapefiles/WSOM/z_18mr25.zip",
        md5="388062c3036e4518d07c9fb09d68ff6f",
        records=4114,
    ),
    BoundaryRelease(
        kind="zone",
        valid_from=date(2026, 4, 16),
        url="https://www.weather.gov/source/gis/Shapefiles/WSOM/z_16ap26.zip",
        md5="004dc6501dc3d50e7b36652cb9d02bd3",
        records=4157,
    ),
)
"""The public zone releases https://www.weather.gov/gis/PublicZones lists (valid date,
MD5 and record count as the page gives them, read 2026-09-27); the first is the
reference tiling."""
PUBLIC_ZONES_PAGE = "https://www.weather.gov/gis/PublicZones"
ZONE_CHANGE_LOG = "https://www.weather.gov/source/gis/Shapefiles/WSOM/zone_ch_log.txt"
AREA_TOLERANCE = 1e-6
"""Relative difference in equal-area size within which two outlines of a zone are the
same polygon. IEM stores ``area2d`` as a 32-bit float (about 6e-8 of rounding). The
polygons of the NWS releases before October 2019 differ from the later ones by the
NWS's point reduction to 0.0001° (zone change log, ``z_10oc19``): IEM's copies of such
versions differ in size from ``z_18mr25`` by 1e-5 and more, with boundaries 7 to 15 m
apart; at 1e-6 such a version is taken from IEM's copy, never from a later release."""
AREA_MATCH = 1e-9
"""Relative difference within which a file's ``AREA_KM2`` is a row's ``area2d`` (both are
IEM's same stored value)."""
SPHERE_RADIUS_M = 6_370_997.0
"""EPSG:2163's sphere."""
_CENTRE_LAT = math.radians(45.0)
_CENTRE_LON = math.radians(-100.0)
_HOST = "mesonet.agron.iastate.edu"

type Floats = npt.NDArray[np.float64]


class ZonePolygonError(ValueError):
    """A zone file is not the documented shape, or a zone version has no polygon."""


def _laea(coords: Floats) -> Floats:
    lon = np.radians(coords[:, 0])
    lat = np.radians(coords[:, 1])
    cos_delta = np.cos(lon - _CENTRE_LON)
    k = np.sqrt(
        2.0
        / (
            1.0
            + math.sin(_CENTRE_LAT) * np.sin(lat)
            + math.cos(_CENTRE_LAT) * np.cos(lat) * cos_delta
        )
    )
    x = SPHERE_RADIUS_M * k * np.cos(lat) * np.sin(lon - _CENTRE_LON)
    y = (
        SPHERE_RADIUS_M
        * k
        * (math.cos(_CENTRE_LAT) * np.sin(lat) - math.sin(_CENTRE_LAT) * np.cos(lat) * cos_delta)
    )
    return np.column_stack([x, y])


def equal_area_km2(geometry: Polygonal) -> float:
    """Return the area of a lon/lat polygon in the US National Atlas Equal Area projection, km²."""
    return float(shapely.transform(geometry, _laea).area) / 1e6


def same_area(a: float, b: float, tolerance: float = AREA_TOLERANCE) -> bool:
    """Whether two areas agree to within ``tolerance`` (relative to the larger)."""
    return abs(a - b) <= tolerance * max(abs(a), abs(b))


@dataclass(frozen=True, slots=True, order=True)
class Version:
    """One zone code with one outline, named by the ``area2d`` its rows carry."""

    ugc: str
    area_km2: float

    @property
    def label(self) -> str:
        """``UTZ003/3563.4971``."""
        return f"{self.ugc}/{self.area_km2:.4f}"


@dataclass(frozen=True, slots=True)
class ZoneShape:
    """One zone of a release: its merged polygon and its equal-area size."""

    ugc: str
    geometry: Polygonal
    area_km2: float
    time_zones: tuple[str, ...]
    """The release's ``TIME_ZONE`` codes for the zone (``C``, ``M``, ...)."""


@dataclass(frozen=True, slots=True)
class ZoneSet:
    """The contiguous states' zones of one served NWS zone release."""

    release: BoundaryRelease
    shapes: Mapping[str, ZoneShape]
    records: int
    file: CachedFile | None = None

    @property
    def name(self) -> str:
        """``z_18mr25``."""
        return self.release.url.rsplit("/", 1)[-1].removesuffix(".zip")


def read_zone_set(
    path: Path, release: BoundaryRelease, states: Iterable[str] = CONUS_STATES
) -> ZoneSet:
    """Read a zone release (zip) into its zones of ``states``; records of one zone are merged.

    Raises:
        ZonePolygonError: a record lacks ``STATE``/``ZONE``, ``STATE_ZONE`` does not repeat
            them, or the record count differs from the one the NWS page lists.
    """
    wanted = frozenset(states)
    try:
        records = read_zip(path)
    except ShapefileError as error:
        raise ZonePolygonError(f"{path.name}: {error}") from error
    if release.records is not None and len(records) != release.records:
        raise ZonePolygonError(
            f"{path.name}: {len(records)} records, the NWS page lists {release.records}"
        )
    parts: dict[str, list[Polygonal]] = defaultdict(list)
    codes: dict[str, set[str]] = defaultdict(set)
    for record in records:
        attrs = record.attributes
        state, zone = str(attrs.get("STATE") or ""), str(attrs.get("ZONE") or "")
        if len(state) != 2 or len(zone) != 3 or not zone.isdigit():  # noqa: PLR2004
            raise ZonePolygonError(f"{path.name}: record {record.index} has no STATE/ZONE")
        if attrs.get("STATE_ZONE") != f"{state}{zone}":
            raise ZonePolygonError(f"{path.name}: record {record.index} STATE_ZONE mismatch")
        if state not in wanted:
            continue
        ugc = f"{state}Z{zone}"
        if record.geometry is not None:
            parts[ugc].append(record.geometry)
        tz = str(attrs.get("TIME_ZONE") or "")
        if tz:
            codes[ugc].add(tz)
    shapes: dict[str, ZoneShape] = {}
    for ugc, pieces in sorted(parts.items()):
        merged = pieces[0] if len(pieces) == 1 else polygonal(shapely.union_all(pieces))
        if merged is None:
            raise ZonePolygonError(f"{path.name}: zone {ugc} has no outline")
        shapes[ugc] = ZoneShape(ugc, merged, equal_area_km2(merged), tuple(sorted(codes[ugc])))
    return ZoneSet(release, shapes, len(records))


def load_zone_sets(
    cache: WeightsCache, releases: Sequence[BoundaryRelease] = ZONE_RELEASES
) -> list[ZoneSet]:
    """Download (or reuse, checking the listed MD5) and read the served zone releases."""
    sets = []
    for release in releases:
        file = cache.fetch(
            release.url, cache_path(cache.root, release.url), expected_md5=release.md5
        )
        found = read_zone_set(file.path, release)
        sets.append(ZoneSet(found.release, found.shapes, found.records, file))
    return sets


def versions_of(rows: Iterable[EventRow]) -> Counter[Version]:
    """Return every zone version the zone rows of ``rows`` were issued for, with its rows.

    Raises:
        ZonePolygonError: a zone row has no ``area2d``.
    """
    found: Counter[Version] = Counter()
    for row in rows:
        if row.ugc[2] != "Z":
            continue
        if row.area_km2 is None:
            raise ZonePolygonError(f"{row.event_key} {row.ugc}: no area2d")
        found[Version(row.ugc, row.area_km2)] += 1
    return found


def served_match(version: Version, sets: Sequence[ZoneSet]) -> tuple[ZoneSet, float] | None:
    """Return the served release whose polygon of the zone has the version's area, and the
    relative difference (the closest one; the earlier release on a tie)."""
    best: tuple[float, int] | None = None
    for position, zone_set in enumerate(sets):
        shape = zone_set.shapes.get(version.ugc)
        if shape is None or not same_area(shape.area_km2, version.area_km2):
            continue
        difference = abs(shape.area_km2 - version.area_km2) / version.area_km2
        if best is None or difference < best[0]:
            best = (difference, position)
    return None if best is None else (sets[best[1]], best[0])


# --- IEM's full-resolution copies ----------------------------------------------------------


@dataclass(frozen=True, slots=True, order=True)
class RequestKey:
    """One ``watchwarn.py`` request: one office, one code, rows beginning in one minute."""

    wfo: str
    code: str
    begin: datetime
    vtec_year: int

    def window(self) -> tuple[datetime, datetime]:
        """Return ``[sts, ets)``.

        One minute from ``begin``; when the event is numbered in another calendar
        year than it begins in, the window is widened across the new year, since IEM
        answers a window inside one calendar year from that year's table only
        (:mod:`snowlight.sources.nws.iem`).
        """
        start, end = self.begin, self.begin + timedelta(minutes=1)
        if self.begin.year != self.vtec_year:
            first = min(self.begin.year, self.vtec_year)
            start = min(start, datetime(first, 12, 31, 23, 59, tzinfo=UTC))
            end = max(end, datetime(first + 1, 1, 1, 0, 1, tzinfo=UTC))
        return start, end

    @property
    def url(self) -> str:
        """The request, full resolution (``simple=0``), as a zipped shapefile."""
        start, end = self.window()
        phenomena, significance = self.code.split(".")
        query = {
            "accept": "shapefile",
            "sts": f"{start:%Y-%m-%dT%H:%M}Z",
            "ets": f"{end:%Y-%m-%dT%H:%M}Z",
            "limitps": "1",
            "phenomena": phenomena,
            "significance": significance,
            "location_group": "wfo",
            "wfo": self.wfo,
            "simple": "0",
        }
        return f"{WATCHWARN_URL}?{urlencode(query, safe=',:')}"

    def path(self, root: Path) -> Path:
        """Where the answer is cached."""
        suffix = "" if self.begin.year == self.vtec_year else f"-vtec{self.vtec_year}"
        name = f"{self.begin:%Y%m%dT%H%M}{suffix}.zip"
        return root / _HOST / "watchwarn-zones" / self.wfo / self.code / name


def plan_requests(rows: Iterable[EventRow], needed: Iterable[Version]) -> list[RequestKey]:
    """Return the fewest requests (greedy) whose rows hold every version in ``needed``.

    Each candidate is the office, code and begin minute of a row of a needed
    version; the one holding the most versions still missing is taken first (ties:
    a request inside one calendar year, then the earliest key).

    Raises:
        ZonePolygonError: a needed version has no row among ``rows``.
    """
    wanted = set(needed)
    holds: dict[RequestKey, set[Version]] = defaultdict(set)
    for row in rows:
        if row.ugc[2] != "Z" or row.area_km2 is None:
            continue
        version = Version(row.ugc, row.area_km2)
        if version in wanted:
            holds[RequestKey(row.wfo, row.code, row.begin, row.vtec_year)].add(version)
    covered = set().union(*holds.values()) if holds else set()
    if covered != wanted:
        missing = sorted(v.label for v in wanted - covered)
        raise ZonePolygonError(f"zone versions with no row to request: {missing[:10]}")
    left = set(wanted)
    order = sorted(holds)
    chosen: list[RequestKey] = []
    while left:
        best: RequestKey | None = None
        best_score = (0, False)
        for key in order:
            score = (len(holds[key] & left), key.begin.year == key.vtec_year)
            if score > best_score:
                best, best_score = key, score
        if best is None:  # pragma: no cover - every needed version is held (checked above)
            break
        chosen.append(best)
        left -= holds[best]
    return sorted(chosen)


@dataclass(frozen=True, slots=True)
class ArchivedZone:
    """One zone polygon of an IEM answer: its code, IEM's ``AREA_KM2`` and the polygon."""

    ugc: str
    area_km2: float
    geometry: Polygonal


def read_version_file(path: Path) -> list[ArchivedZone]:
    """Read the zone rows (``GTYPE`` ``C``, ``NWS_UGC`` a zone) of a ``watchwarn.py`` answer.

    Raises:
        ZonePolygonError: the file is not a shapefile with ``GTYPE``, ``NWS_UGC`` and
            ``AREA_KM2``.
    """
    try:
        records = read_zip(path)
    except ShapefileError as error:
        raise ZonePolygonError(f"{path.name}: {error}") from error
    found: list[ArchivedZone] = []
    for record in records:
        attrs = record.attributes
        if "GTYPE" not in attrs or "NWS_UGC" not in attrs or "AREA_KM2" not in attrs:
            raise ZonePolygonError(f"{path.name}: record {record.index} lacks an attribute")
        ugc = str(attrs.get("NWS_UGC") or "")
        if attrs.get("GTYPE") != "C" or len(ugc) != 6 or ugc[2] != "Z":  # noqa: PLR2004
            continue
        area = attrs.get("AREA_KM2")
        if not isinstance(area, float) or record.geometry is None:
            raise ZonePolygonError(f"{path.name}: record {record.index} has no area or outline")
        found.append(ArchivedZone(ugc, area, record.geometry))
    return found


# --- the book of versions ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Resolved:
    """Where one version's polygon came from."""

    version: Version
    key: str
    """The polygon's key in :attr:`VersionBook.polygons`."""
    source: str
    """``z_18mr25``, ``z_16ap26`` or ``iem``."""
    area_difference: float
    """Relative difference between the polygon's equal-area size and ``area2d``."""
    rows: int
    file: CachedFile | None = None
    """The IEM answer the polygon came from (``None`` for a served release)."""


@dataclass(slots=True)
class VersionBook:
    """Every zone version's polygon, and the polygons by key."""

    sets: list[ZoneSet]
    resolved: dict[Version, Resolved] = field(default_factory=dict)
    polygons: dict[str, Polygonal] = field(default_factory=dict)
    requests: list[RequestKey] = field(default_factory=list)
    files: dict[RequestKey, CachedFile] = field(default_factory=dict)
    unresolved: list[Version] = field(default_factory=list)

    @property
    def reference(self) -> ZoneSet:
        """The reference tiling (the first served release)."""
        return self.sets[0]

    def key_of(self, row: EventRow) -> str:
        """Return the polygon key of a zone row.

        Raises:
            ZonePolygonError: the row's version has no polygon.
        """
        if row.area_km2 is None:
            raise ZonePolygonError(f"{row.event_key} {row.ugc}: no area2d")
        found = self.resolved.get(Version(row.ugc, row.area_km2))
        if found is None:
            raise ZonePolygonError(f"{row.event_key} {row.ugc}: its zone version has no polygon")
        return found.key

    def as_json(self) -> dict[str, JSONValue]:
        """Return the JSON-ready summary kept in the manifest."""
        by_source: Counter[str] = Counter()
        rows_by_source: Counter[str] = Counter()
        worst: dict[str, float] = {}
        for item in self.resolved.values():
            by_source[item.source] += 1
            rows_by_source[item.source] += item.rows
            worst[item.source] = max(worst.get(item.source, 0.0), item.area_difference)
        archived = sorted(
            (item for item in self.resolved.values() if item.source == "iem"),
            key=lambda item: item.version,
        )
        return {
            "served_releases": {
                zone_set.name: {
                    "release": zone_set.release.as_json(),
                    "file": None if zone_set.file is None else zone_set.file.provenance.as_json(),
                    "zones_in_contiguous_states": len(zone_set.shapes),
                }
                for zone_set in self.sets
            },
            "area_tolerance": AREA_TOLERANCE,
            "versions": len(self.resolved),
            "versions_by_source": dict(sorted(by_source.items())),
            "rows_by_source": dict(sorted(rows_by_source.items())),
            "largest_area_difference_by_source": {k: float(f"{v:.3g}") for k, v in worst.items()},
            "iem_requests": [
                {
                    "office": key.wfo,
                    "code": key.code,
                    "begin": f"{key.begin:%Y-%m-%dT%H:%MZ}",
                    "file": self.files[key].provenance.as_json() if key in self.files else None,
                }
                for key in self.requests
            ],
            "iem_versions": [
                {
                    "ugc": item.version.ugc,
                    "area2d": item.version.area_km2,
                    "rows": item.rows,
                    "area_difference": float(f"{item.area_difference:.3g}"),
                    "file_sha256": None if item.file is None else item.file.provenance.sha256,
                }
                for item in archived
            ],
            "unresolved": [version.label for version in self.unresolved],
        }


def build_book(
    cache: WeightsCache,
    rows: Sequence[EventRow],
    sets: Sequence[ZoneSet],
    *,
    fetch: bool = True,
) -> VersionBook:
    """Give every zone version of ``rows`` its polygon (see the module docstring).

    ``fetch=False`` leaves the versions no served release matches unresolved
    instead of asking IEM (for tests of the matching alone).

    Raises:
        ZonePolygonError: an IEM answer is malformed.
    """
    book = VersionBook(sets=list(sets))
    counts = versions_of(rows)
    needed: list[Version] = []
    for version, n in sorted(counts.items()):
        match = served_match(version, sets)
        if match is None:
            needed.append(version)
            continue
        zone_set, difference = match
        key = f"{zone_set.name}/{version.ugc}"
        book.polygons.setdefault(key, zone_set.shapes[version.ugc].geometry)
        book.resolved[version] = Resolved(version, key, zone_set.name, difference, n)
    if not needed or not fetch:
        book.unresolved = needed
        return book
    book.requests = plan_requests(rows, needed)
    archived: dict[str, list[tuple[ArchivedZone, CachedFile]]] = defaultdict(list)
    for request in book.requests:
        file = cache.fetch(request.url, request.path(cache.root))
        book.files[request] = file
        for zone in read_version_file(file.path):
            archived[zone.ugc].append((zone, file))
    for version in needed:
        chosen: tuple[ArchivedZone, CachedFile, float] | None = None
        for zone, file in archived.get(version.ugc, []):
            if not same_area(zone.area_km2, version.area_km2, AREA_MATCH):
                continue
            size = equal_area_km2(zone.geometry)
            difference = abs(size - version.area_km2) / version.area_km2
            if difference <= AREA_TOLERANCE and (chosen is None or difference < chosen[2]):
                chosen = (zone, file, difference)
        if chosen is None:
            book.unresolved.append(version)
            continue
        zone, file, difference = chosen
        key = f"iem/{version.label}"
        book.polygons[key] = zone.geometry
        book.resolved[version] = Resolved(version, key, "iem", difference, counts[version], file)
    return book


# --- outlines a zone's rows return to -------------------------------------------------------

MATERIAL = 0.01
"""Relative area difference above which two outlines of one zone differ materially."""


@dataclass(frozen=True, slots=True)
class Run:
    """Consecutive rows of one zone (by begin time) joined to one outline."""

    key: str
    first: datetime
    last: datetime
    rows: int


@dataclass(frozen=True, slots=True)
class Alternation:
    """A zone whose rows, in time order, return to an outline after rows of another."""

    ugc: str
    runs: tuple[Run, ...]
    areas: Mapping[str, float]
    """Polygon key to its version's ``area2d`` (the first, when several share a key)."""

    @property
    def largest_difference(self) -> float:
        """Largest relative area difference between an outline the rows return to and an
        outline of the rows in between (a later redrawing the rows do not return from is
        not counted)."""
        largest = 0.0
        for later, run in enumerate(self.runs):
            earlier = [i for i in range(later) if self.runs[i].key == run.key]
            if not earlier:
                continue
            area = self.areas[run.key]
            for between in self.runs[earlier[-1] + 1 : later]:
                other = self.areas[between.key]
                largest = max(largest, abs(area - other) / max(area, other))
        return largest

    def as_json(self) -> dict[str, JSONValue]:
        """Return the JSON-ready record kept in the manifest."""
        return {
            "ugc": self.ugc,
            "outlines_km2": {key: round(area, 4) for key, area in sorted(self.areas.items())},
            "largest_area_difference": float(f"{self.largest_difference:.3g}"),
            "runs": [
                {
                    "version": run.key,
                    "first": f"{run.first:%Y-%m-%dT%H:%MZ}",
                    "last": f"{run.last:%Y-%m-%dT%H:%MZ}",
                    "rows": run.rows,
                }
                for run in self.runs
            ],
        }


def alternating_outlines(rows: Iterable[EventRow], book: VersionBook) -> list[Alternation]:
    """Return the zones whose rows return to an outline after rows of another.

    IEM joins each row to the zone outline it held for the row's time; for some zones
    it held two at once (its archived UGC database lists two outlines of ``NCZ051`` on
    15 January 2018), and their rows go back and forth between them. The weights read
    every row against its own outline (a school takes a missed outline of its own zone
    within 2 km, :mod:`snowlight.weights.schoolzones`); this lists them for the method
    note.

    Raises:
        ZonePolygonError: a zone row's version has no polygon.
    """
    by_ugc: dict[str, list[tuple[datetime, str, float]]] = defaultdict(list)
    for row in rows:
        if row.ugc[2] != "Z" or row.area_km2 is None:
            continue
        by_ugc[row.ugc].append((row.begin, book.key_of(row), row.area_km2))
    found: list[Alternation] = []
    for ugc, items in sorted(by_ugc.items()):
        items.sort()
        runs: list[Run] = []
        areas: dict[str, float] = {}
        for begin, key, area in items:
            areas.setdefault(key, area)
            if runs and runs[-1].key == key:
                last = runs[-1]
                runs[-1] = Run(key, last.first, begin, last.rows + 1)
            else:
                runs.append(Run(key, begin, begin, 1))
        keys = [run.key for run in runs]
        if len(keys) != len(set(keys)):
            found.append(Alternation(ugc, tuple(runs), areas))
    return found
