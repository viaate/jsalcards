"""The derived seed of one replay day: NCES ids and status codes, and how they were made.

A seed holds no station ids, names, list text or capture times: each status is
``[nces_id, status, reason, "station_list"]`` (codes from
:mod:`snowlight.schemas.vocab`), sorted by id. ``built`` names the rules and
pins the inputs by SHA-256, so a seed made by other replay rules, another
reader, matcher (with its aliases and place guard), registry, archive, time
zone boundaries or directory is told apart (:func:`files_sha256`)::

    {"schema_version": 1, "id": "2024-01-16", "day": "2024-01-16",
     "built": {"rules": "replay-1", "rules_sha256": "...", "min_confidence": 0.8,
               "allowed_notes": ["undated", "unread_words"],
               "reader_sha256": "...", "matcher_sha256": "...",
               "registry_sha256": "...", "archive_sha256": "...",
               "zones_sha256": "...", "directory_generated_on": "2026-09-24"},
     "quality": {"lit": 0, "sources": 0, "markets": 0, "corroborated": 0, "conflicts": 0},
     "statuses": [["990000100001", 0, 0, "station_list"]]}

Seeds are written with :func:`snowlight.output.write_json`: key-sorted and
byte-identical for the same build.
"""

import hashlib
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Annotated, Final, Literal, Self

import shapely
from pydantic import Field, StringConstraints, model_validator

from snowlight.output import JSONValue, write_json
from snowlight.schemas.base import InternalModel
from snowlight.schemas.internal import Sha256
from snowlight.schemas.scalars import LOCAL_DATE_PATTERN
from snowlight.weights.zones import CountyList

SCHEMA_VERSION: Final = 1
RULES: Final = "replay-1"
SOURCE_TYPE: Final = "station_list"
SCHOOL_ID: Final = r"\d{12}|[A-Z]\d{7}|[A-Z]{2}\d{6}|0[0-2]\d{6}|99\d{6}"
"""An NCES id: 12 digits (CCD), or a PSS id of 8, in the shapes the directory holds: a letter and
7 digits, two letters and 6, or 8 digits from ``00`` to ``02`` (and one ``99``). A date or a count
of 8 digits (``20240116``) is none of these."""
SCHOOL_ID_PATTERN: Final = rf"^(?:{SCHOOL_ID})$"
MATCHER_FILES: Final = (
    "snowlight/match/*.py",
    "snowlight/listed/matching.py",
    "snowlight/listed/scope.py",
    "snowlight/listed/build.py",
    "snowlight/listed/evidence.py",
    "snowlight/listed/located.py",
)
"""The code that decides which school a listing names, relative to the pipeline root."""
ALIASES_NAME: Final = "config/aliases.yaml"
"""The name the aliases file is hashed under, wherever it is read from."""
RULES_FILES: Final = (
    "snowlight/replays/*.py",
    "snowlight/schemas/vocab.py",
    "snowlight/weights/zones.py",
    "snowlight/weather/timezones.py",
    "snowlight/sources/nws/boundaries.py",
    "snowlight/sources/nws/shapefile.py",
    "snowlight/sources/stations/registry.py",
)
"""The code that decides a replay's statuses beside the reader and the matcher, relative to the
pipeline root: the replay rules (gates, windows, settling, words), the status and reason codes,
the county and time zone readers, and how the registry's states and markets are read."""
READER_FILES: Final = ("snowlight/classify/*.py",)
"""The status reader's files, relative to the root it is read from."""

type Day = Annotated[str, StringConstraints(pattern=LOCAL_DATE_PATTERN)]
type SchoolId = Annotated[str, StringConstraints(pattern=SCHOOL_ID_PATTERN)]
type StatusCode = Annotated[int, Field(ge=0, le=3)]
type ReasonCode = Annotated[int, Field(ge=0, le=7)]
type Count = Annotated[int, Field(ge=0)]
type SeedStatus = tuple[SchoolId, StatusCode, ReasonCode | None, Literal["station_list"]]


class Built(InternalModel):
    """The rules a seed was made under and the inputs it was made from."""

    rules: Literal["replay-1"]
    rules_sha256: Sha256
    min_confidence: float
    allowed_notes: tuple[str, ...]
    reader_sha256: Sha256
    matcher_sha256: Sha256
    registry_sha256: Sha256
    archive_sha256: Sha256
    zones_sha256: Sha256
    """The time zone boundary releases the day's zones came from."""
    directory_generated_on: Day


class Quality(InternalModel):
    """The day's headline numbers."""

    lit: Count
    sources: Count
    markets: Count
    corroborated: Count
    conflicts: Count


class ReplaySeed(InternalModel):
    """One replay day, keyed by NCES id (see the module docstring)."""

    schema_version: Literal[1]
    id: Day
    day: Day
    built: Built
    quality: Quality
    statuses: tuple[SeedStatus, ...]

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.id != self.day:
            raise ValueError("a one-day replay's id is its day")
        ids = [status[0] for status in self.statuses]
        if ids != sorted(set(ids)):
            raise ValueError("statuses are sorted by NCES id, each id once")
        if len(ids) != self.quality.lit:
            raise ValueError("quality.lit counts the statuses")
        return self

    def as_json(self) -> JSONValue:
        """The seed as JSON values (lists for tuples)."""
        value: JSONValue = self.model_dump(mode="json")
        return value


def write_seed(path: Path, seed: ReplaySeed) -> None:
    """Write ``seed`` to ``path``, key-sorted and atomically."""
    write_json(path, seed.as_json())


def read_seed(path: Path) -> ReplaySeed:
    """Read and validate a seed file.

    Raises:
        pydantic.ValidationError: the file is not a valid seed.
    """
    return ReplaySeed.model_validate_json(path.read_bytes())


def files_sha256(
    root: Path,
    patterns: Iterable[str],
    named: Mapping[str, Path] | None = None,
    digests: Mapping[str, str] | None = None,
) -> str:
    """A SHA-256 over the files ``patterns`` name under ``root``, in sorted path order.

    Each file adds its path relative to ``root`` and the SHA-256 of its bytes, so
    the same files give the same hash wherever the tree is. ``named`` adds files
    read from anywhere under a fixed name; ``digests`` adds the SHA-256 of
    something that is not a file (the counties a run read) under a fixed name.

    Raises:
        FileNotFoundError: a pattern names no file.
    """
    found: dict[str, Path] = dict(named or {})
    for pattern in patterns:
        matches = sorted(root.glob(pattern))
        if not matches:
            raise FileNotFoundError(f"no file {pattern} under {root}")
        for path in matches:
            found[path.relative_to(root).as_posix()] = path
    sums = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in found.items()}
    sums.update(digests or {})
    digest = hashlib.sha256()
    for name in sorted(sums):
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(sums[name].encode("ascii") + b"\n")
    return digest.hexdigest()


def reader_sha256(root: Path) -> str:
    """The status reader's hash: ``snowlight/classify/*.py`` under ``root``."""
    return files_sha256(root, READER_FILES)


COUNTIES_NAME: Final = "counties"
"""The name the counties a run read (for the place guard) are hashed under."""


def counties_sha256(counties: CountyList | None) -> str:
    """A SHA-256 over the counties the place guard reads: each one's code, state, name, zones
    and outline (WKB), in code order. ``None`` (no counties) has a hash of its own."""
    digest = hashlib.sha256()
    if counties is None:
        digest.update(b"no counties")
        return digest.hexdigest()
    for fips, county in sorted(counties.counties.items()):
        head = "\0".join((fips, county.state, county.name, *county.time_zones))
        digest.update(head.encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(shapely.to_wkb(county.geometry)).hexdigest().encode() + b"\n")
    for state, prefix in sorted(counties.state_fips.items()):
        digest.update(f"{state}={prefix}\n".encode())
    return digest.hexdigest()


def matcher_sha256(pipeline_root: Path, aliases: Path, counties: str | None = None) -> str:
    """The matcher's hash: :data:`MATCHER_FILES` under the pipeline root, the aliases used and
    (when given) the :func:`counties_sha256` of the counties its place guard read."""
    digests = {} if counties is None else {COUNTIES_NAME: counties}
    return files_sha256(pipeline_root, MATCHER_FILES, {ALIASES_NAME: aliases}, digests)


def rules_sha256(pipeline_root: Path) -> str:
    """The replay rules' hash: :data:`RULES_FILES` under the pipeline root."""
    return files_sha256(pipeline_root, RULES_FILES)


def zones_sha256(releases: Iterable[str]) -> str:
    """A SHA-256 over the boundary releases a day's zones came from.

    Each release is named by its URL and the MD5 the NWS lists for its file (the
    cache checks every file it reads against that MD5), so the hash pins the
    files' content as well as their names.
    """
    return hashlib.sha256("\n".join(sorted(releases)).encode("utf-8")).hexdigest()


def registry_sha256(registry_dir: Path) -> str:
    """The registry's hash: every ``*.yaml`` in its folder."""
    return files_sha256(registry_dir, ("*.yaml",))


def archive_sha256(archive_dir: Path) -> str:
    """The archive's hash: its ``reads.jsonl`` and ``rows.jsonl``."""
    return files_sha256(archive_dir, ("reads.jsonl", "rows.jsonl"))


SAFE_STRINGS: Final = re.compile(
    rf"{SCHOOL_ID}|\d{{4}}-\d{{2}}-\d{{2}}|[0-9a-f]{{64}}|{RULES}|{SOURCE_TYPE}|undated|unread_words"
)
"""Every string a seed may hold, whole: an id, a date, a hash or one of its own words."""


def unsafe_strings(value: JSONValue) -> list[str]:
    """Every string in a seed's JSON that is not an id, date, hash or known word.

    A backstop against list text reaching a seed: anything returned here is a bug.
    """
    found: list[str] = []
    if isinstance(value, str):
        if not SAFE_STRINGS.fullmatch(value):
            found.append(value)
    elif isinstance(value, list):
        for item in value:
            found.extend(unsafe_strings(item))
    elif isinstance(value, dict):
        for item in value.values():
            found.extend(unsafe_strings(item))
    return found
