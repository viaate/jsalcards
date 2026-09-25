"""Typed view of ``config/directory.yaml``."""

import re
from pathlib import Path
from typing import Literal

import yaml  # type: ignore[import-untyped, unused-ignore]
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PIPELINE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PIPELINE_ROOT / "config" / "directory.yaml"

SourceKey = Literal[
    "public_school_geocodes",
    "public_lea_geocodes",
    "private_school_geocodes",
    "ccd_directory",
    "ccd_membership",
    "ccd_characteristics",
    "pss",
]
SOURCE_KEYS: tuple[SourceKey, ...] = (
    "public_school_geocodes",
    "public_lea_geocodes",
    "private_school_geocodes",
    "ccd_directory",
    "ccd_membership",
    "ccd_characteristics",
    "pss",
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SCHOOL_YEAR = re.compile(r"^(\d{4})-(\d{4})$")
_FIPS = re.compile(r"^\d{2}$")
_MAX_LON = 180.0
_MAX_LAT = 90.0


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Candidate(_Strict):
    """One downloadable release of a source file."""

    url: str
    school_year: str
    sha256: str | None = None
    members: dict[str, str]
    columns: dict[str, str] = Field(default_factory=dict)

    @field_validator("url")
    @classmethod
    def _https(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("source URLs must be https")
        return value

    @field_validator("sha256")
    @classmethod
    def _hex(cls, value: str | None) -> str | None:
        if value is not None and not _SHA256.match(value):
            raise ValueError("sha256 must be 64 lowercase hex digits")
        return value

    @field_validator("school_year")
    @classmethod
    def _year(cls, value: str) -> str:
        match = _SCHOOL_YEAR.match(value)
        if not match or int(match.group(2)) != int(match.group(1)) + 1:
            raise ValueError("school_year must look like 2024-2025")
        return value

    @field_validator("members")
    @classmethod
    def _has_table(cls, value: dict[str, str]) -> dict[str, str]:
        if "table" not in value:
            raise ValueError("members must name the 'table' file inside the zip")
        return value


class Source(_Strict):
    """A source and its releases, newest first; the first that exists is used."""

    title: str
    candidates: list[Candidate] = Field(min_length=1)


class Bounds(_Strict):
    """A longitude/latitude box in degrees."""

    west: float
    south: float
    east: float
    north: float

    @model_validator(mode="after")
    def _ordered(self) -> "Bounds":
        lon_ok = -_MAX_LON <= self.west < self.east <= _MAX_LON
        lat_ok = -_MAX_LAT <= self.south < self.north <= _MAX_LAT
        if not (lon_ok and lat_ok):
            raise ValueError("bounds must be ordered west < east and south < north")
        return self


class Filters(_Strict):
    """Which source rows become schools on the map."""

    state_fips: list[str] = Field(min_length=1)
    bounds: Bounds
    operational_status_codes: list[str] = Field(min_length=1)
    k12_grade_flags: list[str] = Field(min_length=1)

    @field_validator("state_fips")
    @classmethod
    def _fips(cls, value: list[str]) -> list[str]:
        if any(not _FIPS.match(code) for code in value) or len(set(value)) != len(value):
            raise ValueError("state_fips must be distinct two-digit codes")
        return value


class Enrollment(_Strict):
    """Which published enrollment counts are used."""

    ccd_total_indicator: str
    ccd_accepted_flag: str
    pss_unimputed_flag: str


class Tiles(_Strict):
    """Vector tile settings."""

    layer: str
    minzoom: int = Field(ge=0, le=22)
    maxzoom: int = Field(ge=0, le=22)

    @model_validator(mode="after")
    def _zooms(self) -> "Tiles":
        if self.minzoom > self.maxzoom:
            raise ValueError("minzoom must not exceed maxzoom")
        return self


class DirectoryConfig(_Strict):
    """The whole ``directory.yaml``."""

    sources: dict[SourceKey, Source]
    filters: Filters
    enrollment: Enrollment
    tiles: Tiles

    @field_validator("sources")
    @classmethod
    def _all_sources(cls, value: dict[SourceKey, Source]) -> dict[SourceKey, Source]:
        missing = [key for key in SOURCE_KEYS if key not in value]
        if missing:
            raise ValueError(f"missing sources: {missing}")
        return value


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> DirectoryConfig:
    """Load and validate the directory build configuration."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return DirectoryConfig.model_validate(raw)
