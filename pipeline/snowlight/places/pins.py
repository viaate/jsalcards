"""Typed view of ``config/places.yaml``: the releases a deploy's places build reads.

Without pins the places build finds the newest Census and NCES releases on their
listing pages. A deploy reads the data mirror instead, which serves pinned files
only, so the releases and every file they imply are pinned here, each with its
SHA-256 (the LSAD code list by its code table; see :mod:`snowlight.sources.mirror`).
"""

import re
from pathlib import Path

import yaml  # type: ignore[import-untyped, unused-ignore]
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from snowlight.places.grf import grf_release
from snowlight.sources.census import gazetteer, popest
from snowlight.sources.census.lsad import LSAD_URL
from snowlight.sources.census.zcta_county import ZCTA_COUNTY_URL
from snowlight.sources.mirror import Form, Pin

PIPELINE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PLACES_PINS_PATH = PIPELINE_ROOT / "config" / "places.yaml"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SERIES = re.compile(r"^(\d{4})-(\d{4})$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FilePin(_Strict):
    """The checksum of one file."""

    sha256: str
    form: Form = Form.FILE

    @field_validator("sha256")
    @classmethod
    def _hex(cls, value: str) -> str:
        if not _SHA256.match(value):
            raise ValueError("sha256 must be 64 lowercase hex digits")
        return value


class PlacesPins(_Strict):
    """The whole ``places.yaml``."""

    gazetteer_year: int
    grf_year: int
    popest_series: str
    files: dict[str, FilePin]

    @field_validator("popest_series")
    @classmethod
    def _series(cls, value: str) -> str:
        if not _SERIES.match(value):
            raise ValueError("popest_series must look like 2020-2025")
        return value

    @property
    def series(self) -> tuple[int, int]:
        """``popest_series`` as ``(base, vintage)``."""
        base, vintage = self.popest_series.split("-")
        return int(base), int(vintage)

    def urls(self) -> list[str]:
        """Every file the places build reads for these releases, in build order."""
        base, vintage = self.series
        grf = grf_release(self.grf_year)
        urls = [
            gazetteer.national_file_url(self.gazetteer_year, "place"),
            gazetteer.national_file_url(self.gazetteer_year, "zcta"),
            gazetteer.national_file_url(grf.tiger_year, "zcta"),
            grf.url,
            popest.totals_dir_url(base, vintage) + popest.totals_file_name(vintage),
            LSAD_URL,
            ZCTA_COUNTY_URL,
        ]
        return list(dict.fromkeys(urls))

    @model_validator(mode="after")
    def _pins_every_file(self) -> "PlacesPins":
        wanted, pinned = self.urls(), set(self.files)
        missing = [url for url in wanted if url not in pinned]
        extra = sorted(pinned - set(wanted))
        if missing or extra:
            raise ValueError(
                f"files must pin exactly the build's files: missing {missing}, extra {extra}"
            )
        for url, pin in self.files.items():
            if (pin.form is Form.LSAD_TABLE) != (url == LSAD_URL):
                raise ValueError(f"{url}: only the LSAD code list is pinned as lsad-table")
        return self

    def pins(self) -> list[Pin]:
        """The pins, in build order."""
        return [Pin(url, self.files[url].sha256, self.files[url].form) for url in self.urls()]


def load_places_pins(path: Path = DEFAULT_PLACES_PINS_PATH) -> PlacesPins:
    """Load and validate the places pins."""
    return PlacesPins.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
