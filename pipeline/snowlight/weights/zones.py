"""Which counties each NWS zone covered, and the NWS county list.

Zone-county correlation
=======================

Most closure-type products are issued for public forecast zones (``NYZ072``),
not counties. The NWS publishes which counties each zone falls in as the
zone-county correlation file (https://www.weather.gov/gis/ZoneCounty):
``bpDDmmYY.dbx``, pipe-delimited, no header, one record per zone polygon and
county it lies in: ``STATE|ZONE|CWA|NAME|STATE_ZONE|COUNTY|FIPS|TIME_ZONE|
FE_AREA|LAT|LON``. The ``DDmmYY`` in the name is the date the release takes
effect (the page lists "18 March 2025" for ``bp18mr25.dbx``). A zone that lies
in several counties has a record for each, and counts for each of them.

The page links only the current and the next release, but earlier releases are
still served at the same path. :data:`RELEASES` lists every release that
answered there when a request was made for every date from 2013-01-01 to
2026-09-26 (``HEAD /source/gis/Shapefiles/County/bpDDmmYY.dbx``, 2026-09-26;
see the method note). A product's zones are read in the release in effect on
the UTC date its product was issued (:meth:`ZoneCountyCatalog.counties`).

Zones are redrawn and renumbered now and then, so a zone code can be missing
from the release in effect (a product issued on the day of a change, say). Such a
zone is read in the nearest release that has it, and counted as such. Products
issued before the earliest release (2 April 2019) are read in that release; the
build compares each zone's name there with the name IEM's UGC database had for
it during the school year (``/api/1/nws/ugcs.json?valid=``), and a zone whose
names disagree (beyond spelling, a longer form of the same name, or a name
that still names the zone's counties) is left out for that school year
(:meth:`ZoneCountyCatalog.exclude`), since its code may then have meant
another area.

County list
===========

The counties, their states, names and time zones come from the NWS county
shapefile release pinned in :data:`COUNTY_RELEASE` (https://www.weather.gov/gis/
Counties; ``FIPS``, ``STATE``, ``COUNTYNAME``, ``TIME_ZONE``). The NWS still
uses Connecticut's eight counties, so this list has them rather than the
planning regions the school directory uses; schools are placed in a county by
their coordinates where the codes differ (see :mod:`snowlight.weights.schools`).
"""

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

import shapely

from snowlight.sources.nws.boundaries import BoundaryRelease
from snowlight.sources.nws.http import CachedFile
from snowlight.sources.nws.shapefile import Polygonal, ShapefileError, polygonal, read_zip
from snowlight.weather.hazards import CONUS_STATES
from snowlight.weather.timezones import IANA_ZONES
from snowlight.weights.cache import WeightsCache, cache_path

RELEASE_BASE = "https://www.weather.gov/source/gis/Shapefiles/County/"
ZONE_COUNTY_PAGE = "https://www.weather.gov/gis/ZoneCounty"
RELEASES: tuple[str, ...] = (
    "bp02ap19",
    "bp10oc19",
    "bp03mr20",
    "bp10nv20",
    "bp30mr21",
    "bp08se21",
    "bp22mr22",
    "bp13se22",
    "bp08mr23",
    "bp19se23",
    "bp05mr24",
    "bp10se24",
    "bp18mr25",
    "bp16ap26",
)
"""Every zone-county release served at :data:`RELEASE_BASE` (see the module docstring)."""

COUNTY_RELEASE = BoundaryRelease(
    kind="county",
    valid_from=date(2026, 4, 16),
    url="https://www.weather.gov/source/gis/Shapefiles/County/c_16ap26.zip",
    md5="734d75df3791bdc0cbb29fd6ed75a387",
    records=3352,
)
"""The county release in effect when the build was written (MD5 and record count as
https://www.weather.gov/gis/Counties lists them)."""

_MONTHS = {
    "ja": 1,
    "fe": 2,
    "mr": 3,
    "ap": 4,
    "my": 5,
    "jn": 6,
    "jl": 7,
    "au": 8,
    "se": 9,
    "oc": 10,
    "nv": 11,
    "de": 12,
}
_RELEASE_NAME = re.compile(r"^bp(\d{2})([a-z]{2})(\d{2})$")
_FIPS = re.compile(r"^\d{5}$")
_ZONE = re.compile(r"^\d{3}$")
_STATE = re.compile(r"^[A-Z]{2}$")
_UGC = re.compile(r"^[A-Z]{2}[CZ]\d{3}$")
BP_COLUMNS = 11

type Resolution = Literal[
    "county", "in_effect", "before_first", "nearest", "unmapped", "left_out_renamed"
]


class ZoneCountyError(ValueError):
    """A correlation file or county file does not have the documented shape."""


def release_date(name: str) -> date:
    """Return the date a release named ``bpDDmmYY`` takes effect.

    Raises:
        ZoneCountyError: the name does not follow the NWS naming convention.
    """
    match = _RELEASE_NAME.match(name)
    if match is None or match[2] not in _MONTHS:
        raise ZoneCountyError(f"{name!r} is not a bpDDmmYY release name")
    try:
        return date(2000 + int(match[3]), _MONTHS[match[2]], int(match[1]))
    except ValueError as error:
        raise ZoneCountyError(f"{name!r} names no real date") from error


def release_url(name: str) -> str:
    """Return the URL of the release named ``name``."""
    release_date(name)
    return f"{RELEASE_BASE}{name}.dbx"


@dataclass(frozen=True, slots=True)
class ZoneRecord:
    """One record of a correlation file."""

    ugc: str
    name: str
    cwa: str
    county: str
    fips: str
    time_zone: str
    state_zone: str
    """The file's ``STATE_ZONE`` field as written (it should be ``STATE + ZONE``)."""

    @property
    def state_zone_agrees(self) -> bool:
        """Whether ``STATE_ZONE`` repeats ``STATE`` and ``ZONE``."""
        return self.state_zone == self.ugc[:2] + self.ugc[3:]


def read_release(text: str, label: str) -> list[ZoneRecord]:
    """Parse a correlation file's text.

    The zone is ``STATE`` + ``Z`` + ``ZONE``. ``STATE_ZONE`` should repeat them;
    where it does not (``bp10oc19`` has ``WY|198|...|WY098`` for the zone the
    NWS calls WYZ198, "Northeast Big Horn Mountains"), the record is kept under
    ``STATE`` and ``ZONE`` and the disagreement is reported
    (:attr:`ZoneRelease.state_zone_mismatches`).

    Raises:
        ZoneCountyError: a record does not have 11 fields, or a code is malformed.
    """
    records: list[ZoneRecord] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        fields = line.split("|")
        if len(fields) != BP_COLUMNS:
            raise ZoneCountyError(f"{label} line {number}: {len(fields)} fields, not 11")
        state, zone, cwa, name, state_zone, county, fips, time_zone = fields[:8]
        if not _STATE.match(state) or not _ZONE.match(zone):
            raise ZoneCountyError(f"{label} line {number}: zone {state!r} {zone!r}")
        if not _FIPS.match(fips):
            raise ZoneCountyError(f"{label} line {number}: FIPS {fips!r}")
        records.append(
            ZoneRecord(f"{state}Z{zone}", name.strip(), cwa, county, fips, time_zone, state_zone)
        )
    if not records:
        raise ZoneCountyError(f"{label}: no records")
    return records


@dataclass(frozen=True, slots=True)
class ZoneRelease:
    """One correlation release: each zone's counties and name."""

    name: str
    valid_from: date
    counties: Mapping[str, frozenset[str]]
    names: Mapping[str, str]
    records: int
    county_names: Mapping[str, frozenset[str]] = field(default_factory=dict)
    """Zone to the names of the counties its records give (the ``COUNTY`` field)."""
    state_zone_mismatches: tuple[str, ...] = ()
    """Zones whose ``STATE_ZONE`` field disagrees with ``STATE`` and ``ZONE``."""
    file: CachedFile | None = None
    pairs: tuple[tuple[str, str, str], ...] = ()
    """Every distinct (zone, county FIPS, county name as written) of the file."""

    @classmethod
    def from_records(
        cls, name: str, records: Sequence[ZoneRecord], file: CachedFile | None = None
    ) -> "ZoneRelease":
        """Group ``records`` by zone."""
        counties: dict[str, set[str]] = defaultdict(set)
        county_names: dict[str, set[str]] = defaultdict(set)
        names: dict[str, str] = {}
        for record in records:
            counties[record.ugc].add(record.fips)
            county_names[record.ugc].add(record.county)
            names.setdefault(record.ugc, record.name)
        mismatches = sorted({r.ugc for r in records if not r.state_zone_agrees})
        return cls(
            name=name,
            valid_from=release_date(name),
            counties={ugc: frozenset(fips) for ugc, fips in counties.items()},
            names=names,
            records=len(records),
            county_names={ugc: frozenset(found) for ugc, found in county_names.items()},
            state_zone_mismatches=tuple(mismatches),
            file=file,
            pairs=tuple(sorted({(r.ugc, r.fips, r.county) for r in records})),
        )


_GENERIC_WORDS = frozenset(
    {
        "city",
        "county",
        "of",
        "the",
        "in",
        "and",
        "upper",
        "lower",
        "middle",
        "eastern",
        "western",
        "northern",
        "southern",
        "central",
        "north",
        "south",
        "east",
        "west",
        "mainland",
        "inland",
        "coastal",
        "keys",
    }
)


def _name_words(name: str) -> set[str]:
    return set(re.findall(r"[a-z]+", name.lower())) - _GENERIC_WORDS


def county_name_conflicts(
    release: "ZoneRelease", names: Mapping[str, str]
) -> list[tuple[str, str, str, str]]:
    """Return the records whose county name shares no word with the name of their FIPS code.

    ``names`` is FIPS to the county's name in the NWS county list. A record naming
    ``Hood River`` with FIPS 41031 (Jefferson County) conflicts; ``Upper Bucks`` with
    42017 (Bucks) does not. Returns (zone, FIPS, name as written, county list name).
    """
    conflicts = []
    for ugc, fips, written in release.pairs:
        known = names.get(fips)
        if known is not None and not _name_words(written) & _name_words(known):
            conflicts.append((ugc, fips, written, known))
    return conflicts


@dataclass(slots=True)
class MappingStats:
    """How zone and county codes were resolved to counties."""

    by_resolution: Counter[str] = field(default_factory=Counter)
    unmapped: Counter[str] = field(default_factory=Counter)
    nearest: Counter[tuple[str, str]] = field(default_factory=Counter)
    """(zone, release used) for zones read in a release other than the one in effect."""
    before_first: Counter[str] = field(default_factory=Counter)
    left_out: Counter[str] = field(default_factory=Counter)
    """Zones left out on dates their meaning may have differed (see :meth:`exclude`)."""


class ZoneCountyCatalog:
    """Resolves a UGC code on a date to the counties it covered."""

    def __init__(self, releases: Sequence[ZoneRelease], state_fips: Mapping[str, str]) -> None:
        if not releases:
            raise ZoneCountyError("no zone-county release")
        self.releases = sorted(releases, key=lambda release: release.valid_from)
        self.state_fips = dict(state_fips)
        self.stats = MappingStats()
        self._excluded: dict[str, list[tuple[date, date]]] = defaultdict(list)

    def exclude(self, ugc: str, first: date, end: date) -> None:
        """Leave ``ugc`` unmapped for products issued on ``[first, end)``.

        Used for zones read in the first release before it took effect whose name
        there disagrees with the name IEM had for them at the time
        (:func:`snowlight.weights.crosscheck.names_agree`): the code may then have
        meant another area.
        """
        self._excluded[ugc].append((first, end))

    def excluded(self, ugc: str, day: date) -> bool:
        """Whether ``ugc`` is left out on ``day``."""
        return any(first <= day < end for first, end in self._excluded.get(ugc, ()))

    def release_in_effect(self, day: date) -> ZoneRelease | None:
        """Return the release in effect on ``day``, or ``None`` before the first one."""
        chosen: ZoneRelease | None = None
        for release in self.releases:
            if release.valid_from <= day:
                chosen = release
        return chosen

    def zone_release(self, ugc: str, day: date) -> tuple[ZoneRelease | None, Resolution]:
        """Return the release a zone is read in on ``day``, and how it was chosen."""
        current = self.release_in_effect(day)
        if current is not None and ugc in current.counties:
            return current, "in_effect"
        if current is None and ugc in self.releases[0].counties:
            return self.releases[0], "before_first"
        holders = [release for release in self.releases if ugc in release.counties]
        if not holders:
            return None, "unmapped"
        nearest = min(holders, key=lambda release: abs((release.valid_from - day).days))
        return nearest, "nearest"

    def counties(self, ugc: str, day: date) -> frozenset[str]:
        """Return the county FIPS codes ``ugc`` covered on ``day`` (empty when unknown).

        County UGCs (``NYC029``) name their county directly: the state's FIPS code
        plus the three digits. Zone UGCs are read in a correlation release.

        Raises:
            ZoneCountyError: ``ugc`` is not a UGC code.
        """
        if not _UGC.match(ugc):
            raise ZoneCountyError(f"not a UGC code: {ugc!r}")
        if ugc[2] == "C":
            prefix = self.state_fips.get(ugc[:2])
            if prefix is None:
                self.stats.by_resolution["unmapped"] += 1
                self.stats.unmapped[ugc] += 1
                return frozenset()
            self.stats.by_resolution["county"] += 1
            return frozenset({prefix + ugc[3:]})
        if self.excluded(ugc, day):
            self.stats.by_resolution["left_out_renamed"] += 1
            self.stats.left_out[ugc] += 1
            return frozenset()
        release, resolution = self.zone_release(ugc, day)
        self.stats.by_resolution[resolution] += 1
        if release is None:
            self.stats.unmapped[ugc] += 1
            return frozenset()
        if resolution == "nearest":
            self.stats.nearest[(ugc, release.name)] += 1
        elif resolution == "before_first":
            self.stats.before_first[ugc] += 1
        return release.counties[ugc]


def load_releases(cache: WeightsCache, names: Sequence[str] = RELEASES) -> list[ZoneRelease]:
    """Download (or reuse) and read the correlation releases ``names``."""
    releases = []
    for name in names:
        url = release_url(name)
        file = cache.fetch(url, cache_path(cache.root, url))
        text = file.path.read_bytes().decode("latin-1")
        releases.append(ZoneRelease.from_records(name, read_release(text, name), file))
    return releases


@dataclass(frozen=True, slots=True)
class County:
    """One county of the NWS county list."""

    fips: str
    state: str
    name: str
    time_zones: tuple[str, ...]
    """IANA zones (two when the county is split by a time zone line)."""
    geometry: Polygonal


@dataclass(frozen=True, slots=True)
class CountyList:
    """The contiguous states' counties from one NWS county release."""

    counties: Mapping[str, County]
    state_fips: Mapping[str, str]
    """State code to its two-digit FIPS prefix."""
    records: int
    """Records in the whole file (all states and territories)."""
    file: CachedFile | None = None

    def in_state(self, state: str) -> list[County]:
        """Return the counties of ``state``, by FIPS code."""
        return [county for fips, county in sorted(self.counties.items()) if county.state == state]


def _iana(codes: Iterable[str], fips: str) -> tuple[str, ...]:
    letters = sorted({letter for code in codes for letter in code})
    zones = [IANA_ZONES.get(letter) for letter in letters]
    if not zones or None in zones:
        raise ZoneCountyError(f"county {fips}: time zone codes {sorted(set(codes))} are unknown")
    return tuple(sorted({zone for zone in zones if zone is not None}))


def read_counties(path: Path, states: Iterable[str] = CONUS_STATES) -> CountyList:
    """Read the counties of ``states`` from an NWS county shapefile (zip).

    Records sharing a FIPS code (a county split between two forecast offices or
    time zones) are merged.

    Raises:
        ZoneCountyError: a record lacks a documented attribute, or two records of
            one FIPS code disagree on its state.
    """
    wanted = frozenset(states)
    try:
        records = read_zip(path)
    except ShapefileError as error:
        raise ZoneCountyError(f"{path.name}: {error}") from error
    parts: dict[str, list[Polygonal]] = defaultdict(list)
    zone_codes: dict[str, set[str]] = defaultdict(set)
    meta: dict[str, tuple[str, str]] = {}
    prefixes: dict[str, str] = {}
    for record in records:
        attrs = record.attributes
        state, fips = str(attrs.get("STATE") or ""), str(attrs.get("FIPS") or "")
        name, zone = str(attrs.get("COUNTYNAME") or ""), str(attrs.get("TIME_ZONE") or "")
        if not _STATE.match(state) or not _FIPS.match(fips) or not name or not zone:
            raise ZoneCountyError(f"{path.name}: record {record.index} lacks an attribute")
        known = prefixes.setdefault(state, fips[:2])
        if known != fips[:2]:
            raise ZoneCountyError(f"{path.name}: {state} has FIPS prefixes {known} and {fips[:2]}")
        if state not in wanted:
            continue
        if meta.setdefault(fips, (state, name))[0] != state:
            raise ZoneCountyError(f"{path.name}: FIPS {fips} is in two states")
        zone_codes[fips].add(zone)
        if record.geometry is not None:
            parts[fips].append(record.geometry)
    counties: dict[str, County] = {}
    for fips, (state, name) in sorted(meta.items()):
        pieces = parts.get(fips, [])
        merged = pieces[0] if len(pieces) == 1 else polygonal(shapely.union_all(pieces))
        if merged is None:
            raise ZoneCountyError(f"{path.name}: county {fips} has no outline")
        counties[fips] = County(fips, state, name, _iana(zone_codes[fips], fips), merged)
    return CountyList(counties, {s: p for s, p in prefixes.items() if s in wanted}, len(records))


def load_counties(cache: WeightsCache, release: BoundaryRelease = COUNTY_RELEASE) -> CountyList:
    """Download (or reuse) and read the pinned NWS county release.

    Raises:
        ZoneCountyError: the file does not have the documented shape or record count.
    """
    file = cache.fetch(release.url, cache_path(cache.root, release.url), expected_md5=release.md5)
    listing = read_counties(file.path)
    if release.records is not None and listing.records != release.records:
        raise ZoneCountyError(
            f"{release.url}: {listing.records} records, the page lists {release.records}"
        )
    return CountyList(listing.counties, listing.state_fips, listing.records, file)
