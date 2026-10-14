"""Each school's time zones, for the live ingest: ``school_zones.parquet``.

A school's day is local, so the ingest reads a status in the school's own time
zone, and in every zone it could be in where the NWS boundary files do not settle
one (:meth:`snowlight.weather.timezones.TimeZoneLookup.zones_for`). The directory
build writes the answer once per school, in published index order, so the ingest
never loads the boundary files itself:

* ``index``: the school's index (its position in ``points.bin`` and ``meta.json``);
* ``zones``: the IANA zones it can be in, sorted; empty when nothing is known, and
  then the ingest publishes nothing for the school.

A few places keep a time other than the one the NWS files give their county:
:data:`ZONE_OVERRIDES` lists the ones found so far, and their schools take its
zones instead. A place on another zone by law takes that zone; a place on another
by local custom takes both, so the ingest withholds any read the two would date
differently. The places checked are the Nevada towns that keep Mountain time and
the Alabama towns beside Columbus and West Point, Georgia, that keep Eastern;
Kenton, Oklahoma, and Hyder, Alaska, have no school in the directory. The split
counties the NWS files themselves give two zones (the Navajo Nation and Hopi
lands, Idaho County, Malheur, Gulf and Cherry counties, North Dakota's split
counties) already come out right.

The file is internal: it sits beside ``schools.parquet`` and is never published.
Its indexes mean something only in the directory it was made with, so its
Parquet key-value metadata names that directory: the ``content_sha256``,
``generated_on``, ``schools`` and ``districts`` of its ``schools/edition.json``
(:data:`EDITION_KEYS`). A reader must refuse a table whose edition is not the one
it checked against the deployed site (:func:`read_zones_edition` gives the whole
edition, or raises). The build also refuses a table where fewer than
:data:`MIN_KNOWN_SHARE` of the schools have a known zone, rather than write one
that would leave most of the map dark.
"""

import io
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Protocol

import polars as pl

from snowlight.output import write_bytes_atomic
from snowlight.schemas.directory import DirectoryEdition
from snowlight.sources.nws.boundaries import BoundaryCatalog, BoundaryError
from snowlight.sources.nws.http import FetchError, HttpCache, make_client
from snowlight.weather.timezones import TimeZoneLookup

ZONES_FILE = "school_zones.parquet"
ZONES_SCHEMA: dict[str, pl.DataType] = {"index": pl.UInt32(), "zones": pl.List(pl.String())}
# The least share of schools with a known zone a build accepts (measured on the
# 2024-25 directory: 0.999992, one school unknown).
MIN_KNOWN_SHARE = 0.999
# The key-value metadata naming the directory a table indexes into: every field
# of its edition but the schema version, under these keys, as the edition's
# JSON writes them.
EDITION_KEYS = {
    "content_sha256": "snowlight.directory.content_sha256",
    "generated_on": "snowlight.directory.generated_on",
    "schools": "snowlight.directory.schools",
    "districts": "snowlight.directory.districts",
}


class ZoneError(RuntimeError):
    """The NWS boundary files needed for the time zones could not be read."""


class ZoneCoverageError(ZoneError):
    """Too few schools have a known zone: the same inputs give the same refusal."""


class ZoneTableError(ValueError):
    """A ``school_zones.parquet`` does not name the directory it indexes into."""


@dataclass(frozen=True, slots=True)
class ZoneOverride:
    """A place whose legal or observed time differs from its county's NWS time zone code.

    It covers the schools in county ``county_fips`` inside its box (degrees).
    """

    place: str
    county_fips: str
    south: float
    west: float
    north: float
    east: float
    zones: tuple[str, ...]
    why: str

    def covers(self, county_fips: str | None, lat: float | None, lon: float | None) -> bool:
        """Whether a school at ``lat``, ``lon`` in ``county_fips`` is in this place."""
        return (
            county_fips == self.county_fips
            and lat is not None
            and lon is not None
            and self.south <= lat <= self.north
            and self.west <= lon <= self.east
        )


CENTRAL = "America/Chicago"
EASTERN = "America/New_York"
MOUNTAIN = "America/Denver"
PACIFIC = "America/Los_Angeles"
# NWS codes Elko County (32007) and Humboldt County (32013), Nevada, Pacific ("P").
ZONE_OVERRIDES: tuple[ZoneOverride, ...] = (
    ZoneOverride(
        place="West Wendover, NV",
        county_fips="32007",
        south=40.65,
        west=-114.20,
        north=40.80,
        east=-114.03,
        zones=(MOUNTAIN,),
        why="moved to Mountain time by federal rule in 1999",
    ),
    ZoneOverride(
        place="Jackpot, NV",
        county_fips="32007",
        south=41.90,
        west=-114.80,
        north=42.01,
        east=-114.55,
        zones=(MOUNTAIN, PACIFIC),
        why="keeps Mountain time by local custom, with Idaho",
    ),
    ZoneOverride(
        place="Owyhee, NV",
        county_fips="32007",
        south=41.85,
        west=-116.25,
        north=42.01,
        east=-115.95,
        zones=(MOUNTAIN, PACIFIC),
        why="keeps Mountain time by local custom, with the Duck Valley reservation in Idaho",
    ),
    ZoneOverride(
        place="McDermitt, NV",
        county_fips="32013",
        south=41.93,
        west=-117.80,
        north=42.01,
        east=-117.62,
        zones=(MOUNTAIN, PACIFIC),
        why="keeps Mountain time by local custom, with McDermitt, Oregon",
    ),
    # NWS codes Russell (01113), Lee (01081) and Chambers (01017) counties,
    # Alabama, Central ("C"). The towns across the Chattahoochee from Columbus and
    # West Point, Georgia, keep Eastern time by custom; the box takes in the
    # places beside them too, since both zones only ever withhold a read.
    ZoneOverride(
        place="Russell County, AL: Phenix City, Ladonia, Fort Mitchell, Seale",
        county_fips="01113",
        south=32.10,
        west=-85.45,
        north=32.60,
        east=-84.90,
        zones=(CENTRAL, EASTERN),
        why="keeps Eastern time by local custom, with Columbus, Georgia",
    ),
    ZoneOverride(
        place="Lee County, AL, east of Opelika: Smiths Station, Phenix City, Salem, Beulah",
        county_fips="01081",
        south=32.40,
        west=-85.30,
        north=32.80,
        east=-84.90,
        zones=(CENTRAL, EASTERN),
        why="keeps Eastern time by local custom, with Columbus and West Point, Georgia",
    ),
    ZoneOverride(
        place="Chambers County, AL, by the river: Valley, Lanett",
        county_fips="01017",
        south=32.70,
        west=-85.30,
        north=33.00,
        east=-85.10,
        zones=(CENTRAL, EASTERN),
        why="keeps Eastern time by local custom, with West Point, Georgia",
    ),
)


def override_for(
    county_fips: str | None, lat: float | None, lon: float | None
) -> ZoneOverride | None:
    """The entry of :data:`ZONE_OVERRIDES` that covers a school there, if any."""
    return next((entry for entry in ZONE_OVERRIDES if entry.covers(county_fips, lat, lon)), None)


class ZoneLookup(Protocol):
    """What :func:`school_zones` asks of a time zone lookup."""

    def zones_for(
        self, county_fips: str | None, lat: float | None, lon: float | None
    ) -> tuple[str, ...]:
        """Return every IANA zone the place can be in; empty when nothing is known."""
        ...


def school_zones(schools: pl.DataFrame, lookup: ZoneLookup) -> pl.DataFrame:
    """Return ``index`` and ``zones`` for each school, in the order given.

    ``schools`` needs ``index``, ``county_fips``, ``lat`` and ``lon``. A school in
    a place of :data:`ZONE_OVERRIDES` takes that place's zones.
    """
    zones = [
        list(
            entry.zones
            if (entry := override_for(county, lat, lon)) is not None
            else lookup.zones_for(county, lat, lon)
        )
        for county, lat, lon in zip(
            schools["county_fips"].to_list(),
            schools["lat"].to_list(),
            schools["lon"].to_list(),
            strict=True,
        )
    ]
    return pl.DataFrame({"index": schools["index"], "zones": zones}, schema=ZONES_SCHEMA)


def zone_counts(frame: pl.DataFrame) -> dict[str, Any]:
    """Count the schools by how many zones they can be in, for the build report."""
    sizes = frame["zones"].list.len()
    total = frame.height
    known = int((sizes > 0).sum())
    return {
        "schools": total,
        "one_zone": int((sizes == 1).sum()),
        "several_zones": int((sizes > 1).sum()),
        "unknown": total - known,
        "known_share": round(known / total, 6) if total else 0.0,
    }


def check_coverage(frame: pl.DataFrame, floor: float = MIN_KNOWN_SHARE) -> None:
    """Refuse a table where fewer than ``floor`` of the schools have a known zone.

    Raises:
        ZoneCoverageError: the share of schools with a known zone is below ``floor``.
    """
    counts = zone_counts(frame)
    known = frame.height - counts["unknown"]
    if known < floor * frame.height:
        raise ZoneCoverageError(
            f"time zones are known for {known:,} of {frame.height:,} schools, "
            f"below the {floor:.1%} a build needs"
        )


def write_school_zones(frame: pl.DataFrame, target: Path, edition: DirectoryEdition) -> None:
    """Write ``frame`` to ``target`` atomically, named by the directory's ``edition``."""
    if frame.height != edition.schools:
        raise ValueError(f"{frame.height} rows for a directory of {edition.schools} schools")
    named = edition.model_dump(mode="json")
    metadata = {key: str(named[field]) for field, key in EDITION_KEYS.items()}
    buffer = io.BytesIO()
    frame.write_parquet(buffer, metadata=metadata)
    write_bytes_atomic(target, buffer.getvalue())


def read_zones_edition(path: Path) -> DirectoryEdition:
    """Return the edition of the directory a ``school_zones.parquet`` was made with.

    Raises:
        ZoneTableError: the file does not name every field of an edition, or names
            one that is not valid; such a table must not be used.
    """
    metadata = pl.read_parquet_metadata(path)
    missing = sorted(key for key in EDITION_KEYS.values() if key not in metadata)
    if missing:
        raise ZoneTableError(f"{path} does not name its directory: no {', '.join(missing)}")
    named: dict[str, Any] = {field: metadata[key] for field, key in EDITION_KEYS.items()}
    try:
        named["schools"] = int(named["schools"])
        named["districts"] = int(named["districts"])
        return DirectoryEdition.from_json_bytes(json.dumps({"schema_version": 1, **named}).encode())
    except ValueError as error:  # pydantic's ValidationError is a ValueError too
        raise ZoneTableError(f"{path} does not name a valid directory edition") from error


def nws_zone_lookup(cache_dir: Path, day: date) -> tuple[TimeZoneLookup, dict[str, Any]]:
    """Return a lookup built from the NWS county and zone files in effect on ``day``.

    The files are downloaded into ``cache_dir`` on first use (the weather build's
    cache, so a machine that has built the weather files has them). Also returns
    the releases read, for the build report.

    Raises:
        ZoneError: no release is in effect on ``day``, or a file could not be read.
    """
    with HttpCache(make_client()) as cache:
        catalog = BoundaryCatalog(cache, cache_dir)
        try:
            counties = catalog.boundaries_for("county", day)
            zones = catalog.boundaries_for("zone", day)
        except (BoundaryError, FetchError) as error:
            raise ZoneError(f"NWS boundary files: {error}") from error
        if counties is None or zones is None:
            raise ZoneError(f"no NWS county and zone boundary release is in effect on {day}")
        releases = {
            "county": counties.release.as_json(),
            "zone": zones.release.as_json(),
        }
        return TimeZoneLookup(counties, zones), releases
