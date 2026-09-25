"""Find, download and combine the sources behind the city and ZIP search records.

:func:`build_places` is what ``snowlight places build`` runs:

1. Find the newest releases, unless pinned: the newest Gazetteer year that has
   both national place and ZCTA files, the newest NCES GRF zip, and the newest
   Population Estimates vintage with a city and town totals file.
2. Download (or reuse from the cache, checksum-verified) the places and ZCTA
   Gazetteer files of that year, the ZCTA Gazetteer file of the GRF's TIGER
   year, the GRF zip, the ``sub-est`` file, the LSAD code list and the 2020
   ZCTA-to-county relationship file.
3. Build and validate the records (:mod:`snowlight.places.records`), write
   ``cities.jsonl`` and ``zips.jsonl`` atomically and deterministically, and
   write the internal manifest with every source's URL, retrieval time and
   SHA-256, the releases used, per-step counts and each output's SHA-256.
"""

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from snowlight import __version__
from snowlight.output import dumps_json, write_bytes_atomic
from snowlight.places.download import FetchedFile, SourceCache, SourceMissingError, utc_now_iso
from snowlight.places.grf import (
    GRF_PAGE_URL,
    GrfRelease,
    grf_release,
    grf_releases,
    read_lea_zcta,
)
from snowlight.places.records import build_cities, build_zips, state_codes
from snowlight.sources.census import gazetteer, popest
from snowlight.sources.census.lsad import LSAD_URL, name_suffixes, parse_lsad_codes
from snowlight.sources.census.zcta_county import ZCTA_COUNTY_URL, read_zcta_state_land

CITIES_FILE = "cities.jsonl"
ZIPS_FILE = "zips.jsonl"

METHOD = {
    "cities": (
        "One record per place in the latest national places Gazetteer whose USPS code is "
        "one of the 48 contiguous states or DC. name is the Gazetteer NAME minus the "
        "suffix that the Census LSAD code list gives for the row's LSAD code (kept whole "
        "when the code has no suffix); lat/lon are INTPTLAT/INTPTLONG as published."
    ),
    "population": (
        "POPESTIMATE<vintage> of the SUMLEV 162 row of the latest Population Estimates "
        "city and town totals with the same GEOID, used only when the Gazetteer place is "
        "not a statistical entity (FUNCSTAT S, i.e. a CDP) and both names match once "
        "their LSAD suffixes are removed; otherwise null."
    ),
    "zcta_districts": (
        "NCES EDGE School District Geographic Relationship File (LEA-ZCTA table) from the "
        "newest GRF release. NCES publishes this relationship directly, built from the "
        "same TIGER/Line school district and 2020 ZCTA boundaries, so no spatial "
        "intersection was needed."
    ),
    "share": (
        "GRF LANDAREA (square miles) x 2,589,988 / ALAND (square meters) of the ZCTA in "
        "the Gazetteer of the GRF's TIGER year, rounded to 4 significant digits. District "
        "pieces with zero land are dropped. Elementary, secondary and unified districts "
        "overlap in some states, so a ZCTA's shares can sum above 1; land in no district "
        "leaves them below 1. The build fails if any unrounded share exceeds 1 + 1e-9."
    ),
    "zip_scope": (
        "ZCTAs from the latest ZCTA Gazetteer (codes and INTPTLAT/INTPTLONG) with land in a "
        "contiguous state or DC per the 2020 ZCTA-to-county relationship file; states are "
        "listed most land first, mapped from FIPS to USPS as the places Gazetteer pairs them."
    ),
}


class PlacesBuildError(RuntimeError):
    """Raised when a source release cannot be found."""


@dataclass(frozen=True, slots=True)
class Pins:
    """Releases to use instead of discovering the newest ones."""

    gazetteer_year: int | None = None
    grf_year: int | None = None
    popest_series: tuple[int, int] | None = None


@dataclass(frozen=True, slots=True)
class OutputFile:
    """One file the build wrote for the site."""

    path: Path
    records: int
    sha256: str
    size: int

    @classmethod
    def write(cls, path: Path, records: Sequence[BaseModel]) -> "OutputFile":
        """Serialize ``records`` as JSON Lines, write them atomically and describe the file."""
        data = b"".join(dumps_json(r.model_dump(mode="json")) + b"\n" for r in records)
        write_bytes_atomic(path, data)
        return cls(path, len(records), hashlib.sha256(data).hexdigest(), len(data))

    def as_json(self) -> dict[str, object]:
        """Return the JSON-ready manifest entry."""
        return {
            "bytes": self.size,
            "file": self.path.name,
            "records": self.records,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class BuildResult:
    """What the build wrote and the manifest it recorded."""

    outputs: tuple[OutputFile, ...]
    manifest_path: Path
    manifest: dict[str, object]


def latest_gazetteer_year(cache: SourceCache) -> int:
    """Return the newest Gazetteer year with national place and ZCTA files."""
    for year in gazetteer.release_years(cache.get_text(gazetteer.INDEX_URL)):
        listing = cache.get_text(gazetteer.release_dir_url(year))
        if gazetteer.release_has(listing, year, ("place", "zcta")):
            return year
    raise PlacesBuildError("no Gazetteer release has national place and ZCTA files")


def latest_grf(cache: SourceCache) -> GrfRelease:
    """Return the newest GRF release linked from the NCES page."""
    releases = grf_releases(cache.get_text(GRF_PAGE_URL))
    if not releases:
        raise PlacesBuildError("the NCES GRF page links no GRF zip")
    return releases[0]


def latest_popest_series(cache: SourceCache) -> tuple[int, int]:
    """Return ``(base, vintage)`` of the newest series with a city and town totals file.

    A series whose totals directory does not exist (HTTP 404) is skipped; any
    other failure stops the build rather than silently falling back to an
    older vintage.
    """
    for base, vintage in popest.estimate_series(cache.get_text(popest.DATASETS_URL)):
        try:
            listing = cache.get_text(popest.totals_dir_url(base, vintage))
        except SourceMissingError:
            continue
        if popest.totals_listed(listing, base, vintage):
            return base, vintage
    raise PlacesBuildError("no Population Estimates series has a city and town totals file")


def _source(role: str, fetched: FetchedFile, member: str | None = None) -> dict[str, object]:
    entry: dict[str, object] = {"role": role, **fetched.provenance()}
    if member is not None:
        entry["member"] = member
    return entry


def build_places(
    cache: SourceCache,
    out_dir: Path,
    manifest_path: Path,
    pins: Pins | None = None,
    now: Callable[[], str] = utc_now_iso,
) -> BuildResult:
    """Run the whole places build and return what it wrote."""
    pins = pins or Pins()
    started = now()
    gaz_year = pins.gazetteer_year or latest_gazetteer_year(cache)
    grf = grf_release(pins.grf_year) if pins.grf_year else latest_grf(cache)
    base, vintage = pins.popest_series or latest_popest_series(cache)

    place_file = cache.fetch(gazetteer.national_file_url(gaz_year, "place"))
    zcta_file = cache.fetch(gazetteer.national_file_url(gaz_year, "zcta"))
    zcta_area_file = cache.fetch(gazetteer.national_file_url(grf.tiger_year, "zcta"))
    grf_file = cache.fetch(grf.url)
    pep_file = cache.fetch(popest.totals_dir_url(base, vintage) + popest.totals_file_name(vintage))
    lsad_file = cache.fetch(LSAD_URL)
    rel_file = cache.fetch(ZCTA_COUNTY_URL)

    place_member, places = gazetteer.read_places(place_file.path)
    zcta_member, zctas = gazetteer.read_zctas(zcta_file.path)
    area_member, area_zctas = gazetteer.read_zctas(zcta_area_file.path)
    lea_zcta = read_lea_zcta(grf_file.path, grf.tiger_year)
    estimates = popest.read_place_estimates(pep_file.path, vintage)
    suffixes = name_suffixes(parse_lsad_codes(lsad_file.path.read_text(encoding="utf-8")))
    zcta_states = read_zcta_state_land(rel_file.path)

    cities, city_counts = build_cities(places, suffixes, estimates)
    zips, zip_counts = build_zips(
        zctas,
        {z.geoid: z.aland for z in area_zctas},
        zcta_states,
        state_codes(places),
        lea_zcta.parts,
    )

    outputs = (
        OutputFile.write(out_dir / CITIES_FILE, cities),
        OutputFile.write(out_dir / ZIPS_FILE, zips),
    )

    manifest: dict[str, object] = {
        "counts": {"cities": city_counts.as_json(), "zips": zip_counts.as_json()},
        "finished_at": now(),
        "method": METHOD,
        "outputs": [output.as_json() for output in outputs],
        "piece": "places",
        "pipeline_version": __version__,
        "releases": {
            "gazetteer_year": gaz_year,
            "grf_tiger_year": grf.tiger_year,
            "grf_zcta_vintage": lea_zcta.zcta_vintage,
            "popest_column": estimates.column,
            "popest_encoding": estimates.encoding,
            "popest_series": f"{base}-{vintage}",
            "zcta_area_gazetteer_year": grf.tiger_year,
        },
        "sources": [
            _source("places_gazetteer", place_file, place_member),
            _source("zcta_gazetteer", zcta_file, zcta_member),
            _source("zcta_area_gazetteer", zcta_area_file, area_member),
            _source("lea_zcta_relationship", grf_file, lea_zcta.member),
            _source("place_population_estimates", pep_file),
            _source("lsad_codes", lsad_file),
            _source("zcta_county_relationship", rel_file),
        ],
        "started_at": started,
        "pages_consulted": [page.as_json() for page in cache.pages_consulted],
    }
    text = json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
    write_bytes_atomic(manifest_path, (text + "\n").encode("utf-8"))
    return BuildResult(outputs, manifest_path, manifest)
