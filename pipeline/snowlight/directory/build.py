"""Build the school directory from official NCES files.

``snowlight directory build`` runs :func:`build`, which downloads (or reuses from
the cache) every file named in ``config/directory.yaml``, keeps the K-12 schools
of the continental US that are operating and geocoded, and writes:

Published, under ``<out>/schools/`` (what the website downloads):

* ``points.bin``: one 13-byte record per school, see :mod:`snowlight.directory.points`.
* ``meta.json``: the school ids and names in ``points.bin`` order and the district
  list that ``points.bin`` indexes::

      {
        "schema_version": 1,
        "generated_on": "2026-09-24",          # see "The date" below
        "count": 118132,                        # schools, = points.bin count
        "ids": ["010000500870", ...],           # NCES id: 12 digits public, 8 chars private
        "names": ["Albertville Middle School", ...],
        "districts": {"ids": ["0100005", ...], "names": ["Albertville City", ...]},
        "school_years": {"public": "2024-2025", "private": "2023-2024"}
      }

  Public schools come first, sorted by id, then private schools sorted by id.
* ``schools.pmtiles``: the same schools as vector tile points, see
  :mod:`snowlight.directory.tiles`. Every tile is decoded after tippecanoe runs
  and each feature checked against its school before the file is kept.
  ``--no-tiles`` skips it (and removes an older one, so it is never staged with
  a directory it was not made from): the live ingest needs no tiles.
* ``edition.json``: the directory named by its content
  (:class:`~snowlight.schemas.directory.DirectoryEdition`)::

      {"content_sha256": "...", "districts": 12938, "generated_on": "2026-09-24",
       "schema_version": 1, "schools": 118132}

  ``content_sha256`` is :func:`~snowlight.schemas.directory.written_digest` of
  ``meta.json`` and ``points.bin``: the digest of ``meta.json`` with an empty
  ``generated_on``, followed by ``points.bin``.

The date in ``meta.json`` (and so in the stamp every live file carries) names the
directory's content; it is an identifier, not the day of the build, and can be
ahead of the calendar. Given ``previous``, the edition of the directory the site
serves now (:mod:`snowlight.directory.deployed` reads it), a build whose digest
equals ``previous``'s keeps its date, so a redeploy of the same directory leaves
every file indexed into it valid. Any change to the schools, their order, names,
districts, kinds or places changes the digest, and the date: to the build's UTC
date, or to the day after ``previous``'s when that is already on or after the build
day (:func:`choose_generated_on`). So the date of a changed directory only moves
forward, and no stamp names two contents as long as ``previous`` is the edition
the site really serves. That holds only while the deploys are read in order, so
the live ingest still blanks its files when the deployed edition's digest is not
its own under the stamp it last published (risk R6 is reduced, not closed).

Internal, never published:

* ``<out>/schools/manifest.internal.json``: each source file's URL, retrieval time,
  SHA-256 and size, plus the checksums of the files written. A publishing step
  must skip ``*.internal.json``.
* ``<internal>/schools.parquet``: every kept school with all fields listed in
  :mod:`snowlight.directory.assemble` plus ``index`` (its position in
  ``points.bin``) and ``district_index``.
* ``<internal>/districts.parquet``: the district list with EDGE LEA location fields.
* ``<internal>/dropped.parquet``: every source row that was not kept, with its
  ``drop_reason``, so each exclusion can be audited.
* ``<internal>/build_report.json`` and ``build_report.md``: counts by state and
  reason, reconciled against the source row counts.
* ``<internal>/school_zones.parquet``, when the build is given a zone lookup: each
  school's time zones, see :mod:`snowlight.directory.zones`, named by the edition
  it indexes into. The lookup is made before anything is written, and an older
  table is removed before the new ``meta.json`` is, so no table ever sits beside
  a directory it was not made with.

Schools the NCES files miss come from the reviewed supplement file the config
names (:mod:`snowlight.directory.supplement`). They are private schools with ids
of the supplement prefix (``SN000001``), sorted among the private schools, and
the report counts them in a section of their own.
"""

import gzip
import json
import sys
import tempfile
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import polars as pl
from pydantic import ValidationError

from snowlight import __version__
from snowlight.directory import pmtiles, points, tiles
from snowlight.directory.assemble import (
    SCHOOL_SCHEMA,
    PrivateSources,
    PublicSources,
    assemble_districts,
    assemble_private,
    assemble_public,
)
from snowlight.directory.config import (
    PIPELINE_ROOT,
    Candidate,
    DirectoryConfig,
    SourceKey,
)
from snowlight.directory.filters import Reason
from snowlight.directory.report import reconcile, render_markdown
from snowlight.directory.supplement import (
    NcesSchools,
    Supplement,
    SupplementRows,
    assemble_supplement,
    check_prefix_unused,
    load_supplement,
)
from snowlight.directory.zones import (
    ZONES_FILE,
    ZoneLookup,
    check_coverage,
    override_for,
    school_zones,
    write_school_zones,
    zone_counts,
)
from snowlight.output import dumps_json, write_bytes_atomic, write_json
from snowlight.schemas.directory import DirectoryEdition, written_digest
from snowlight.sources.mirror import Mirror
from snowlight.sources.nces import readers
from snowlight.sources.nces.fetch import (
    FileCache,
    Retrieved,
    SourceMissingError,
    make_client,
    sha256_file,
    utc_now_iso,
)

SCHEMA_VERSION = 1
DEFAULT_CACHE_DIR = PIPELINE_ROOT / ".cache" / "nces"
DEFAULT_OUT_DIR = PIPELINE_ROOT / "out" / "site-data"
DEFAULT_INTERNAL_DIR = PIPELINE_ROOT / "out" / "internal" / "directory"
PUBLISHED_FILES = ("points.bin", "meta.json", "schools.pmtiles", "edition.json")
TILES_FILE = "schools.pmtiles"
# How far after the build day a deployed edition may be dated before a changed
# directory is refused: each directory change on a day already used moves the
# date on by one, so only a burst of changes or a bad edition gets this far.
MAX_DAYS_AHEAD = timedelta(days=31)
EDITION_FILE = "edition.json"
# Text that must never appear in a published file.
FORBIDDEN_IN_PUBLISHED = (
    "nces.ed.gov",
    "national center for education statistics",
    "common core of data",
    "private school survey",
    "edge_geocode",
    "ccd_sch",
    "pss2324",
    "census.gov",
    "http://",
    "https://",
)

# The filters that apply to each set, in the order they are applied.
_GEOGRAPHY = (
    Reason.NO_COORDINATES,
    Reason.OUTSIDE_CONTINENTAL_US,
    Reason.COORDINATES_OUTSIDE_BOUNDS,
)
PUBLIC_REASONS = (
    *_GEOGRAPHY,
    Reason.STATUS_CLOSED,
    Reason.STATUS_INACTIVE,
    Reason.STATUS_FUTURE,
    Reason.STATUS_NOT_OPERATIONAL,
    Reason.GRADES_NOT_REPORTED,
    Reason.NO_GRADES,
    Reason.PREK_ONLY,
    Reason.ADULT_ONLY,
    Reason.UNGRADED_ONLY,
    Reason.NO_K12_GRADE,
)
PRIVATE_REASONS = (
    *_GEOGRAPHY,
    Reason.PREK_ONLY,
    Reason.UNGRADED_ONLY,
    Reason.GRADES_NOT_REPORTED,
)
DISTRICT_REASONS = (Reason.OUTSIDE_CONTINENTAL_US, Reason.NO_SCHOOL_ON_MAP)
SUPPLEMENT_REASONS = (
    *_GEOGRAPHY,
    Reason.LISTED_BY_NCES,
    Reason.EVIDENCE_STALE,
    Reason.ADDRESS_STALE,
)

Log = Callable[[str], None]
# Given the build's UTC date, a time zone lookup and a record of what it was made from.
ZoneSource = Callable[[date], tuple[ZoneLookup, dict[str, Any]]]


class BuildError(RuntimeError):
    """The sources are inconsistent or an output failed its checks."""


class EditionRefusedError(BuildError):
    """The deployed edition given cannot date this build: trying again cannot help."""


def _stderr(message: str) -> None:
    sys.stderr.write(message + "\n")
    sys.stderr.flush()


@dataclass(frozen=True, slots=True)
class BuildPaths:
    """Where the build reads and writes."""

    cache_dir: Path = DEFAULT_CACHE_DIR
    out_dir: Path = DEFAULT_OUT_DIR
    internal_dir: Path = DEFAULT_INTERNAL_DIR
    work_dir: Path | None = None

    @property
    def site_dir(self) -> Path:
        """The published directory for the school files."""
        return self.out_dir / "schools"


@dataclass(slots=True)
class FetchedSource:
    """A resolved source: the release used, its file, and the releases skipped."""

    key: SourceKey
    title: str
    candidate: Candidate
    file: Retrieved
    skipped: list[dict[str, str]] = field(default_factory=list)
    rows: int | None = None

    def member(self, name: str) -> str:
        """Return the name of a file inside the zip, as configured."""
        return self.candidate.members[name]

    def manifest_entry(self) -> dict[str, Any]:
        """Return this source's provenance record for the internal manifest."""
        return {
            "key": self.key,
            "title": self.title,
            "school_year": self.candidate.school_year,
            **self.file.provenance(),
            "pinned_sha256": self.candidate.sha256,
            "members_read": sorted(set(self.candidate.members.values())),
            "rows_read": self.rows,
            "newer_releases_checked": self.skipped,
        }


def fetch_sources(
    config: DirectoryConfig, cache: FileCache, log: Log = _stderr
) -> dict[SourceKey, FetchedSource]:
    """Fetch every configured source, using the first release that exists.

    Raises:
        BuildError: if no release of a source exists.
    """
    fetched: dict[SourceKey, FetchedSource] = {}
    for key, source in config.sources.items():
        skipped: list[dict[str, str]] = []
        for candidate in source.candidates:
            try:
                file = cache.fetch(candidate.url, candidate.sha256)
            except SourceMissingError as error:
                skipped.append(
                    {"url": candidate.url, "checked_at": utc_now_iso(), "result": str(error)}
                )
                log(f"  {key}: {candidate.url} is not published ({error}); trying older")
                continue
            origin = "cache" if file.from_cache else "downloaded"
            log(f"  {key}: {Path(file.path).name} ({origin}, sha256 {file.sha256[:12]}...)")
            fetched[key] = FetchedSource(key, source.title, candidate, file, skipped)
            break
        else:
            raise BuildError(f"no release of {key} could be fetched: {skipped}")
    return fetched


def _single_value(frame: pl.DataFrame, column: str, expected: str, what: str) -> None:
    values = frame[column].unique().to_list()
    if values != [expected]:
        raise BuildError(f"{what}: {column} is {values}, config says {expected!r}")


@dataclass(frozen=True, slots=True)
class Tables:
    """Every parsed source table."""

    public: PublicSources
    private: PrivateSources
    leas: pl.DataFrame


def read_tables(sources: dict[SourceKey, FetchedSource], config: DirectoryConfig) -> Tables:
    """Parse the fetched files and check each is the school year it claims.

    Raises:
        BuildError: if a file's school year differs from its configured year, or
            the private geocode and PSS files are from different surveys.
    """
    geo = sources["public_school_geocodes"]
    geocodes = readers.read_edge_public_schools(
        geo.file.path, geo.member("table"), geo.member("header")
    )
    lea_src = sources["public_lea_geocodes"]
    leas = readers.read_edge_leas(
        lea_src.file.path, lea_src.member("table"), lea_src.member("header")
    )
    directory_src = sources["ccd_directory"]
    directory = readers.read_ccd_directory(directory_src.file.path, directory_src.member("table"))
    membership_src = sources["ccd_membership"]
    membership = readers.read_ccd_membership_totals(
        membership_src.file.path,
        membership_src.member("table"),
        config.enrollment.ccd_total_indicator,
    )
    characteristics_src = sources["ccd_characteristics"]
    characteristics = readers.read_ccd_characteristics(
        characteristics_src.file.path, characteristics_src.member("table")
    )
    private_src = sources["private_school_geocodes"]
    private = readers.read_edge_private_schools(private_src.file.path, private_src.member("table"))
    pss_src = sources["pss"]
    low = pss_src.candidate.columns["low_grade"]
    high = pss_src.candidate.columns["high_grade"]
    pss = readers.read_pss(pss_src.file.path, pss_src.member("table"), (low, high))

    read: list[tuple[SourceKey, pl.DataFrame]] = [
        ("public_school_geocodes", geocodes),
        ("public_lea_geocodes", leas),
        ("ccd_directory", directory),
        ("ccd_membership", membership),
        ("ccd_characteristics", characteristics),
        ("private_school_geocodes", private),
        ("pss", pss),
    ]
    for key, frame in read:
        sources[key].rows = frame.height
    _single_value(geocodes, "SCHOOLYEAR", geo.candidate.school_year, "EDGE public geocodes")
    _single_value(leas, "SCHOOLYEAR", lea_src.candidate.school_year, "EDGE LEA geocodes")
    _single_value(private, "SCHOOLYEAR", private_src.candidate.school_year, "EDGE private")
    for frame, src in (
        (directory, directory_src),
        (membership, membership_src),
        (characteristics, characteristics_src),
    ):
        _single_value(frame, "SCHOOL_YEAR", src.candidate.school_year, src.title)
    if pss_src.candidate.school_year != private_src.candidate.school_year:
        raise BuildError(
            f"private geocodes are {private_src.candidate.school_year} but PSS is "
            f"{pss_src.candidate.school_year}; add the matching PSS release to the config"
        )
    return Tables(
        public=PublicSources(directory, geocodes, membership, characteristics),
        private=PrivateSources(private, pss, low, high),
        leas=leas,
    )


@contextmanager
def _work_dir(requested: Path | None) -> Iterator[Path]:
    if requested is not None:
        requested.mkdir(parents=True, exist_ok=True)
        yield requested
        return
    with tempfile.TemporaryDirectory(prefix="snowlight-directory-") as name:
        yield Path(name)


def order_schools(kept: pl.DataFrame, districts: pl.DataFrame) -> pl.DataFrame:
    """Order kept schools (public by id, then private by id) and attach indexes.

    Raises:
        BuildError: if two kept schools share an id.
    """
    if kept.height != kept["id"].n_unique():
        raise BuildError("two kept schools share an id")
    ordered = kept.sort(
        pl.when(pl.col("kind") == "public").then(0).otherwise(1), "id"
    ).with_row_index("index")
    lookup = districts.select("district_id", pl.col("index").alias("district_index"))
    joined = ordered.join(lookup, on="district_id", how="left", maintain_order="left")
    return joined.with_columns(
        pl.col("district_index").fill_null(points.NO_DISTRICT).cast(pl.UInt32)
    )


def meta_document(
    schools: pl.DataFrame, districts: pl.DataFrame, generated_on: str, school_years: dict[str, str]
) -> dict[str, Any]:
    """Return the ``meta.json`` document for the ordered schools."""
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_on": generated_on,
        "count": schools.height,
        "ids": schools["id"].to_list(),
        "names": schools["name"].to_list(),
        "districts": {
            "ids": districts["district_id"].to_list(),
            "names": districts["name"].to_list(),
        },
        "school_years": school_years,
    }


def check_published(name: str, data: bytes) -> None:
    """Refuse a published file that names a source or carries a URL.

    Raises:
        BuildError: if ``data`` contains any of :data:`FORBIDDEN_IN_PUBLISHED`.
    """
    lowered = data.lower()
    hits = [term for term in FORBIDDEN_IN_PUBLISHED if term.encode() in lowered]
    if hits:
        raise BuildError(f"{name} contains {hits}; published files must not name sources")


def _display_path(path: Path) -> str:
    """``path`` relative to the pipeline project when it is inside it."""
    resolved = path.resolve()
    if resolved.is_relative_to(PIPELINE_ROOT):
        return str(resolved.relative_to(PIPELINE_ROOT))
    return str(resolved)


def _file_info(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "bytes": len(data),
        "gzip_bytes": len(gzip.compress(data, compresslevel=9, mtime=0)),
        "sha256": sha256_file(path),
    }


def _encode_points(schools: pl.DataFrame, district_count: int) -> bytes:
    data = points.encode(
        schools["lon_e6"].to_numpy(),
        schools["lat_e6"].to_numpy(),
        schools["district_index"].to_numpy(),
        schools["kind_flags"].to_numpy(),
        district_count,
    )
    decoded = points.decode(data)
    if not (
        np.array_equal(decoded.lon_e6, schools["lon_e6"].to_numpy())
        and np.array_equal(decoded.lat_e6, schools["lat_e6"].to_numpy())
        and np.array_equal(decoded.district, schools["district_index"].to_numpy())
        and np.array_equal(decoded.kind, schools["kind_flags"].to_numpy())
    ):
        raise BuildError("points.bin does not decode to the values written")
    return data


@dataclass(frozen=True, slots=True)
class TilesWritten:
    """How ``schools.pmtiles`` was made and what its full decode found."""

    argv: list[str]
    generator: str | None
    check: tiles.TilesetCheck
    separated_pairs: int


def _write_tiles(
    schools: pl.DataFrame, config: DirectoryConfig, work: Path, target: Path
) -> TilesWritten:
    features = [
        tiles.TileFeature(
            index=row["index"],
            school_id=row["id"],
            name=row["name"],
            kind=row["kind_flags"],
            lon_e6=row["lon_e6"],
            lat_e6=row["lat_e6"],
        )
        for row in schools.iter_rows(named=True)
    ]
    settings = tiles.TileSettings(config.tiles.layer, config.tiles.minzoom, config.tiles.maxzoom)
    source = work / "schools.geojsonseq"
    written = tiles.write_tile_input(features, source)
    staged = work / "schools.pmtiles"
    argv = tiles.run_tippecanoe(source, staged, settings)
    data = staged.read_bytes()
    info = pmtiles.read_info(data)
    if (info.min_zoom, info.max_zoom) != (settings.minzoom, settings.maxzoom):
        raise BuildError(f"schools.pmtiles spans z{info.min_zoom}-{info.max_zoom}")
    count = tiles.layer_feature_count(info, settings.layer)
    if count != written:
        raise BuildError(f"schools.pmtiles holds {count} features, {written} were written")
    check_published("schools.pmtiles metadata", json.dumps(info.metadata).encode())
    try:
        check = tiles.verify_tileset(data, features, settings)
    except (tiles.TilesError, pmtiles.PMTilesError) as error:
        raise BuildError(f"schools.pmtiles does not match its input: {error}") from error
    write_bytes_atomic(target, data)
    source.unlink()
    staged.unlink()
    generator = info.metadata.get("generator")
    return TilesWritten(
        argv=argv,
        generator=generator if isinstance(generator, str) else None,
        check=check,
        separated_pairs=len(tiles.colliding_features(features)),
    )


@dataclass(frozen=True, slots=True)
class EditionChoice:
    """The date a build stamps its directory with, and why."""

    generated_on: str
    reason: str


def choose_generated_on(
    digest: str, schools: int, districts: int, build_day: date, previous: DirectoryEdition | None
) -> EditionChoice:
    """Date a directory with content ``digest``, given the edition the site serves now.

    * The same content as ``previous`` keeps its date: the stamp does not change.
    * Other content takes ``build_day``, or the day after ``previous``'s date when
      that is not before ``build_day``. Dates of a changed directory so only ever
      go forward from the deployed one, and while ``previous`` is the edition the
      site serves, a stamp is never reused for other content: a page still holding
      the older ``meta.json`` can never take a live file indexed into the new one
      for its own (with the same counts, the date is all that tells them apart).
    * ``previous`` is ``None`` only when no edition was ever deployed.

    Raises:
        EditionRefusedError: the content changed and ``previous`` is dated more than
            :data:`MAX_DAYS_AHEAD` after ``build_day``. Taking the build date would
            move the stamp backwards, to a date that may already name other content.
    """
    today = build_day.isoformat()
    if previous is None:
        return EditionChoice(today, "no edition was deployed before: the build date")
    if previous.content_sha256 == digest and (previous.schools, previous.districts) == (
        schools,
        districts,
    ):
        return EditionChoice(
            previous.generated_on.isoformat(), "the content is unchanged: its date"
        )
    if previous.generated_on > build_day + MAX_DAYS_AHEAD:
        raise EditionRefusedError(
            f"the deployed directory is dated {previous.generated_on}, more than "
            f"{MAX_DAYS_AHEAD.days} days after {build_day}: a changed directory would "
            "need a later date still, and an earlier one may name other content"
        )
    if previous.generated_on < build_day:
        return EditionChoice(today, "the content changed: the build date")
    later = previous.generated_on + timedelta(days=1)
    return EditionChoice(
        later.isoformat(),
        "the content changed on or before the previous edition's date: the day after it",
    )


def read_edition(path: Path) -> DirectoryEdition:
    """Read the deployed edition at ``path``.

    Raises:
        EditionRefusedError: the file is missing, unreadable or not an edition. The build
            then stops: dated without the deployed edition, a changed directory
            could take a date that already names other content.
    """
    try:
        data = path.read_bytes()
    except OSError as error:
        raise EditionRefusedError(f"previous edition {path}: {error.strerror or error}") from error
    try:
        return DirectoryEdition.from_json_bytes(data)
    except ValidationError as error:
        raise EditionRefusedError(
            f"previous edition {path}: not an edition ({error.error_count()} problem(s))"
        ) from error


def _edition(
    meta: dict[str, Any], meta_bytes: bytes, points_bytes: bytes, digest: str
) -> DirectoryEdition:
    """The edition of ``meta``, after checking the digest against the written bytes.

    The digest is also what a reader gets from the files by emptying the date's
    text in ``meta.json`` and following it with ``points.bin``
    (web/scripts/edition.mjs checks it that way).

    Raises:
        BuildError: if the date's text is not in ``meta_bytes`` exactly once, or
            blanking it does not give ``digest``.
    """
    try:
        written = written_digest(meta_bytes, meta["generated_on"], points_bytes)
    except ValueError as error:
        raise BuildError(f"meta.json: {error}") from error
    if written != digest:
        raise BuildError("meta.json does not have the content digest written for it")
    return DirectoryEdition(
        schema_version=1,
        generated_on=date.fromisoformat(meta["generated_on"]),
        schools=meta["count"],
        districts=len(meta["districts"]["ids"]),
        content_sha256=digest,
    )


@dataclass(frozen=True, slots=True)
class DatedDirectory:
    """``meta.json`` dated, and its edition, ready to write."""

    meta_bytes: bytes
    edition: DirectoryEdition
    edition_bytes: bytes


def _dated_directory(  # noqa: PLR0913 - the directory, its date's inputs, and where to report
    meta: dict[str, Any],
    points_bytes: bytes,
    *,
    build_day: date,
    previous: DirectoryEdition | None,
    report: dict[str, Any],
    log: Log,
) -> DatedDirectory:
    """Date ``meta`` and make its edition.

    The digest is taken of ``meta.json`` written with an empty date, by the same
    definition every reader uses (:func:`written_digest`); :func:`_edition` then
    checks that the dated file gives it too.
    """
    try:
        digest = written_digest(dumps_json({**meta, "generated_on": ""}), "", points_bytes)
    except ValueError as error:
        raise BuildError(f"meta.json: {error}") from error
    choice = choose_generated_on(
        digest, meta["count"], len(meta["districts"]["ids"]), build_day, previous
    )
    meta["generated_on"] = choice.generated_on
    meta_bytes = dumps_json(meta)
    check_published("meta.json", meta_bytes)
    edition = _edition(meta, meta_bytes, points_bytes, digest)
    edition_bytes = edition.to_json_bytes()
    check_published(EDITION_FILE, edition_bytes)
    report["edition"] = {
        "generated_on": choice.generated_on,
        "content_sha256": digest,
        "date_from": choice.reason,
        "previous": None if previous is None else previous.to_json_value(),
    }
    log(f"Directory dated {choice.generated_on}: {choice.reason}")
    return DatedDirectory(meta_bytes, edition, edition_bytes)


def _tiles_step(
    schools: pl.DataFrame,
    config: DirectoryConfig,
    paths: BuildPaths,
    report: dict[str, Any],
    *,
    write: bool,
) -> TilesWritten | None:
    """Write ``schools.pmtiles``, or with ``write=False`` remove an older one."""
    target = paths.site_dir / TILES_FILE
    if not write:
        # An older tileset beside this meta.json would point at other schools.
        target.unlink(missing_ok=True)
        return None
    with _work_dir(paths.work_dir) as work:
        written = _write_tiles(schools, config, work, target)
    report["tileset_check"] = {
        "tiles": written.check.tiles,
        "feature_instances": written.check.feature_instances,
        "schools_per_zoom": {str(z): n for z, n in written.check.schools_per_zoom.items()},
        "string_pool_pairs_separated": written.separated_pairs,
    }
    return written


def _write_directory(
    site: Path, internal: Path, points_bytes: bytes, dated: DatedDirectory
) -> None:
    """Write points.bin, meta.json and edition.json, after removing an older zone table.

    An older table gives the zones of another directory's indexes, so it goes
    before the new directory is written, whatever happens after.
    """
    (internal / ZONES_FILE).unlink(missing_ok=True)
    write_bytes_atomic(site / "points.bin", points_bytes)
    write_bytes_atomic(site / "meta.json", dated.meta_bytes)
    write_bytes_atomic(site / EDITION_FILE, dated.edition_bytes)


def _write_tables(  # noqa: PLR0913 - one table each
    internal: Path,
    schools: pl.DataFrame,
    districts: pl.DataFrame,
    dropped: pl.DataFrame,
    *,
    zone_table: pl.DataFrame | None,
    dated: DatedDirectory,
) -> list[str]:
    """Write the internal tables; return their names."""
    columns = ["index", *(c for c in SCHOOL_SCHEMA if c != "drop_reason"), "district_index"]
    schools.select(columns).write_parquet(internal / "schools.parquet")
    districts.write_parquet(internal / "districts.parquet")
    dropped.select(*SCHOOL_SCHEMA).write_parquet(internal / "dropped.parquet")
    written = ["schools.parquet", "districts.parquet", "dropped.parquet"]
    if zone_table is not None:
        write_school_zones(zone_table, internal / ZONES_FILE, dated.edition)
        written.append(ZONES_FILE)
    return written


@dataclass(frozen=True, slots=True)
class ZonesFound:
    """The lookup a zone source gave, and the record of what it was made from."""

    lookup: ZoneLookup
    made_from: dict[str, Any]


def _zone_table(schools: pl.DataFrame, found: ZonesFound, report: dict[str, Any]) -> pl.DataFrame:
    """Each school's zones, refused below the coverage floor (raises ZoneError)."""
    table = school_zones(schools, found.lookup)
    overridden = Counter(
        entry.place
        for county, lat, lon in schools.select("county_fips", "lat", "lon").iter_rows()
        if (entry := override_for(county, lat, lon)) is not None
    )
    report["zones"] = {
        **zone_counts(table),
        "overridden": dict(sorted(overridden.items())),
        "boundaries": found.made_from,
    }
    check_coverage(table)
    return table


@dataclass(frozen=True, slots=True)
class BuildResult:
    """What a build wrote and the report it produced."""

    report: dict[str, Any]
    site_dir: Path
    internal_dir: Path


def _fetch_all(
    config: DirectoryConfig,
    cache_dir: Path,
    client_factory: Callable[[], httpx.Client],
    log: Log,
    mirror: Mirror | None,
) -> dict[SourceKey, FetchedSource]:
    if mirror is None:
        log("Fetching NCES files")
    else:
        log(f"Fetching NCES files from the cache, else the data mirror {mirror.base_url}")
    with FileCache(cache_dir, client_factory(), mirror=mirror, log=log) as cache:
        return fetch_sources(config, cache, log)


def build(  # noqa: PLR0913 - what to build, where, and how
    config: DirectoryConfig,
    paths: BuildPaths,
    *,
    client_factory: Callable[[], httpx.Client] | None = None,
    log: Log = _stderr,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    previous: DirectoryEdition | None = None,
    zones: ZoneSource | None = None,
    write_tiles: bool = True,
    mirror: Mirror | None = None,
) -> BuildResult:
    """Run the whole directory build; see the module docstring for the outputs.

    ``previous`` is the edition the site serves now; ``None`` only when no edition
    was ever deployed. ``zones`` makes ``school_zones.parquet``.
    ``write_tiles=False`` skips ``schools.pmtiles``. With ``mirror`` (a deploy)
    every file the cache lacks is read from the data mirror, never from NCES.
    """
    started = now()
    found = None
    if zones is not None:
        # First, so a failed lookup stops the build before any file is written.
        log("Reading the NWS boundary files")
        found = ZonesFound(*zones(started.date()))
    sources = _fetch_all(config, paths.cache_dir, client_factory or make_client, log, mirror)
    log("Reading tables")
    tables = read_tables(sources, config)
    log("Filtering schools")
    public = assemble_public(tables.public, config)
    private = assemble_private(tables.private, config)
    supplement, merged = _supplement(config, tables, public, private, started.date())
    kept = pl.concat([public, private, merged.rows]).filter(pl.col("drop_reason").is_null())
    districts, lea_rows = assemble_districts(
        kept.filter(pl.col("kind") == "public"), tables.leas, config
    )
    schools = order_schools(kept, districts)

    report: dict[str, Any] = {
        "generated_at": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "public": reconcile(
            public, tables.public.directory.height, "public schools", PUBLIC_REASONS
        ),
        "private": reconcile(
            private, tables.private.geocodes.height, "private schools", PRIVATE_REASONS
        ),
        "districts": reconcile(lea_rows, tables.leas.height, "districts", DISTRICT_REASONS),
        "supplement": _supplement_report(config, supplement, merged),
    }
    report["public"]["geocode_rows"] = tables.public.geocodes.height
    report["public"]["geocode_rows_without_directory_record"] = tables.public.geocodes.join(
        tables.public.directory, on="NCESSCH", how="anti"
    ).height
    report["public"]["directory_rows_without_geocode"] = public.filter(~pl.col("geocoded")).height
    report["private"]["pss_rows"] = tables.private.pss.height
    report["private"]["geocode_rows_without_pss_record"] = tables.private.geocodes.join(
        tables.private.pss, on="PPIN", how="anti"
    ).height
    report["private"]["pss_rows_without_geocode"] = tables.private.pss.join(
        tables.private.geocodes, on="PPIN", how="anti"
    ).height
    report["districts"]["on_map"] = districts.height
    report["districts"]["on_map_without_lea_record"] = districts.filter(
        ~pl.col("lea_geocoded")
    ).height
    if report["districts"]["kept"] + report["districts"]["on_map_without_lea_record"] != (
        districts.height
    ):
        raise BuildError("district list does not reconcile with the LEA file")
    report["schools_on_map"] = {
        "total": schools.height,
        "public": schools.filter(pl.col("kind") == "public").height,
        "private": schools.filter(pl.col("kind") == "private").height,
        "private_from_supplement": report["supplement"]["kept"],
        "charter": schools.filter(pl.col("charter").fill_null(value=False)).height,
        "exclusively_virtual": schools.filter(pl.col("virtual") == "FULLVIRTUAL").height,
        "with_enrollment": schools.filter(pl.col("enrollment").is_not_null()).height,
        "without_enrollment_by_flag": {
            f"{row['kind']}:{row['enrollment_flag']}": row["n"]
            for row in schools.filter(pl.col("enrollment").is_null())
            .group_by("kind", "enrollment_flag")
            .agg(n=pl.len())
            .sort("kind", "enrollment_flag", nulls_last=True)
            .iter_rows(named=True)
        },
        # Coordinates keep six decimals. Longer published values are counted, and
        # so are those where dropping the extra digits moved the point by more
        # than floating-point noise (below 1e-9 degrees).
        "coordinates_published_with_more_than_6_decimals": schools.filter(
            pl.col("coordinates_long")
        ).height,
        "coordinates_moved_by_rounding_to_6_decimals": schools.filter(
            pl.col("coordinates_rounded")
        ).height,
    }

    zone_table = None if found is None else _zone_table(schools, found, report)
    log("Writing outputs")
    site, internal = paths.site_dir, paths.internal_dir
    site.mkdir(parents=True, exist_ok=True)
    internal.mkdir(parents=True, exist_ok=True)
    school_years = {
        "public": sources["ccd_directory"].candidate.school_year,
        "private": sources["private_school_geocodes"].candidate.school_year,
    }
    points_bytes = _encode_points(schools, districts.height)
    meta = meta_document(schools, districts, "", school_years)
    dated = _dated_directory(
        meta, points_bytes, build_day=started.date(), previous=previous, report=report, log=log
    )
    _write_directory(site, internal, points_bytes, dated)
    tiles_written = _tiles_step(schools, config, paths, report, write=write_tiles)

    dropped = pl.concat([public, private, merged.rows]).filter(pl.col("drop_reason").is_not_null())
    internal_written = _write_tables(
        internal, schools, districts, dropped, zone_table=zone_table, dated=dated
    )

    outputs = {
        name: _file_info(site / name)
        for name in PUBLISHED_FILES
        if write_tiles or name != TILES_FILE
    }
    report["outputs"] = {name: dict(info) for name, info in outputs.items()}
    report["notes"] = [
        f"Public schools: CCD {school_years['public']}; private schools: PSS "
        f"{school_years['private']} (the most recent private geocode release).",
        "Operational CCD statuses kept: "
        + ", ".join(config.filters.operational_status_codes)
        + " (1 Open, 3 New, 4 Added, 5 Changed boundary/agency, 8 Reopened).",
        f"Public enrollment is the CCD membership row '{config.enrollment.ccd_total_indicator}' "
        f"when its flag is {config.enrollment.ccd_accepted_flag} (adult education "
        "students are not counted); private enrollment is PSS P305 when not imputed. "
        "Otherwise enrollment is left empty.",
        "Coordinates are the NCES geocodes at six decimals: "
        f"{report['schools_on_map']['coordinates_published_with_more_than_6_decimals']:,} "
        "kept schools are published with more digits, and dropping them moves "
        f"{report['schools_on_map']['coordinates_moved_by_rounding_to_6_decimals']:,} "
        "by more than floating-point noise (1e-9 degrees).",
        f"Supplement: {report['schools_on_map']['private_from_supplement']:,} private schools "
        "the NCES files miss, each with current evidence that it operates, a street "
        "address matched this school year against its own site, its diocese's list or "
        "a closings row, and a geocode of that address (Census Bureau, or NCES's own for "
        "the same address once matched against the school's own map) "
        f"({len(supplement.schools):,} entries, "
        f"{report['supplement']['dropped'][Reason.LISTED_BY_NCES.value]:,} now listed by NCES, "
        f"{report['supplement']['dropped'][Reason.EVIDENCE_STALE.value]:,} with evidence from "
        "before last school year or older than "
        f"{report['supplement']['max_evidence_age_days']} days, "
        f"{report['supplement']['dropped'][Reason.ADDRESS_STALE.value]:,} with an address "
        "not checked this school year; oldest evidence "
        f"{report['supplement']['oldest_evidence_on']}, oldest address check "
        f"{report['supplement']['oldest_address_checked_on']}).",
        "schools.pmtiles is built with tippecanoe, reading in two threads so that "
        "attribute strings its string pool would confuse (equal low 32 bits of the "
        "FNV-1a hash) never share a pool; every tile is then decoded and checked.",
    ]
    write_json(internal / "build_report.json", report)
    (internal / "build_report.md").write_text(render_markdown(report), encoding="utf-8")

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": report["generated_at"],
        "pipeline_version": __version__,
        "sources": [sources[key].manifest_entry() for key in sorted(sources)],
        "outputs": outputs,
        "internal_outputs": {name: _file_info(internal / name) for name in internal_written},
        "supplement": _supplement_provenance(config, supplement),
        "tippecanoe_argv": None if tiles_written is None else tiles_written.argv,
        "tileset_generator": None if tiles_written is None else tiles_written.generator,
        "report": _display_path(internal / "build_report.json"),
    }
    write_json(site / "manifest.internal.json", manifest)
    return BuildResult(report=report, site_dir=site, internal_dir=internal)


def _supplement(
    config: DirectoryConfig,
    tables: Tables,
    public: pl.DataFrame,
    private: pl.DataFrame,
    today: date,
) -> tuple[Supplement, SupplementRows]:
    """Load the supplement and assemble its rows against the NCES rows.

    Raises:
        SupplementError: if the file does not check out, an NCES id takes its
            prefix, or an entry needs a reviewer's ruling.
    """
    settings = config.supplement
    supplement = Supplement(schools=[])
    if settings is not None:
        prefix = settings.id_prefix
        check_prefix_unused(public["id"], prefix, "CCD directory")
        check_prefix_unused(private["id"], prefix, "EDGE private geocodes")
        check_prefix_unused(tables.private.pss["PPIN"], prefix, "PSS file")
        supplement = load_supplement(settings.resolved(), prefix)
    nces_private_ids = frozenset(private["id"].to_list()) | frozenset(
        tables.private.pss["PPIN"].to_list()
    )
    columns = ("id", "name", "street", "city", "state", "zip", "lat", "lon")
    nces = NcesSchools(
        private_ids=nces_private_ids,
        kept_private=private.filter(pl.col("drop_reason").is_null()).select(columns),
        kept_public=public.filter(pl.col("drop_reason").is_null()).select(columns),
    )
    merged = assemble_supplement(supplement, config, nces, today)
    return supplement, merged


def _supplement_report(
    config: DirectoryConfig, supplement: Supplement, merged: SupplementRows
) -> dict[str, Any]:
    """The supplement's reconciled counts, its kept schools by source, the NCES ids
    that list entries, the nearby schools reviewers cleared, and the oldest check."""
    extra = merged.rows
    section = reconcile(extra, len(supplement.schools), "supplement schools", SUPPLEMENT_REASONS)
    kept = set(extra.filter(pl.col("drop_reason").is_null())["id"].to_list())
    by_source: dict[str, int] = {}
    for entry in supplement.schools:
        if entry.id in kept:
            by_source[entry.source] = by_source.get(entry.source, 0) + 1
    section["kept_by_source"] = dict(sorted(by_source.items()))
    section["listed_by_nces"] = dict(sorted(merged.listed_by.items()))
    section["near_nces_cleared"] = merged.cleared
    for key, day in (
        ("oldest_evidence_on", merged.oldest_evidence_on),
        ("oldest_address_checked_on", merged.oldest_address_checked_on),
    ):
        section[key] = None if day is None else day.isoformat()
    by_address: dict[str, int] = {}
    for entry in supplement.schools:
        if entry.id in kept:
            by_address[entry.address_from] = by_address.get(entry.address_from, 0) + 1
    section["kept_by_address_source"] = dict(sorted(by_address.items()))
    section["max_evidence_age_days"] = (
        None if config.supplement is None else config.supplement.max_evidence_age_days
    )
    section["expiring"] = [
        {"id": e.id, "name": e.name, "what": e.what, "expires_on": e.expires_on.isoformat()}
        for e in merged.expiring
    ]
    return section


def _supplement_provenance(config: DirectoryConfig, supplement: Supplement) -> dict[str, Any]:
    if config.supplement is None:
        return {"path": None, "entries": 0}
    path = config.supplement.resolved()
    return {
        "path": _display_path(path),
        "sha256": sha256_file(path),
        "entries": len(supplement.schools),
        "id_prefix": config.supplement.id_prefix,
    }


def summary_lines(result: BuildResult) -> list[str]:
    """Return a short human-readable summary of a build."""
    report = result.report
    lines = [
        f"public schools: {report['public']['kept']:,} kept of {report['public']['source_rows']:,}",
        f"private schools: {report['private']['kept']:,} kept of "
        f"{report['private']['source_rows']:,}",
        f"supplement schools: {report['supplement']['kept']:,} kept of "
        f"{report['supplement']['source_rows']:,}",
        *(
            f"supplement entry {e['id']} {e['name']}: its {e['what']} goes stale on "
            f"{e['expires_on']}; check it again before then"
            for e in report["supplement"].get("expiring", [])
        ),
        f"districts on map: {report['districts']['on_map']:,} "
        f"(LEA file rows {report['districts']['source_rows']:,})",
    ]
    for name, info in report["outputs"].items():
        lines.append(f"{name}: {info['bytes']:,} bytes, {info['gzip_bytes']:,} gzipped")
    edition = report["edition"]
    lines.append(f"dated {edition['generated_on']}: {edition['date_from']}")
    zones = report.get("zones")
    if zones is not None:
        lines.append(
            f"time zones: {zones['one_zone']:,} schools in one, {zones['several_zones']:,} "
            f"in several, {zones['unknown']:,} unknown"
        )
    lines.append(f"report: {result.internal_dir / 'build_report.md'}")
    return lines
