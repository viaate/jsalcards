"""The elevation table's pin: ``pipeline/config/elevation.yaml``.

The file names the terrain tiles a build reads (``source``) and, once a build in Actions has
put a table in the data mirror's release, that table (``table``: its URL, SHA-256 and
counts). The predict pass reads only the pinned table, and only when its bytes have the
pinned SHA-256 (:mod:`snowlight.predict.heights`).
"""

import re
from pathlib import Path
from typing import Final

import yaml  # type: ignore[import-untyped, unused-ignore]
from pydantic import BaseModel, ConfigDict, Field, field_validator

PIPELINE_ROOT: Final = Path(__file__).resolve().parents[2]
DEFAULT_PINS_PATH: Final = PIPELINE_ROOT / "config" / "elevation.yaml"
ASSET_PREFIX: Final = "school-elevations-"
ASSET_SUFFIX: Final = ".json.gz"
_SHA256: Final = re.compile(r"^[0-9a-f]{64}$")
_DIGITS_IN_NAME: Final = 16


class _Pins(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Source(_Pins):
    """The terrain tiles a build reads."""

    url: str = Field(pattern=r"^https://[^ ]+\{z\}/\{x\}/\{y\}\.png$")
    zoom: int = Field(ge=8, le=14)
    attribution: str = Field(min_length=1)


class TablePin(_Pins):
    """A built table in the data mirror's release."""

    url: str = Field(pattern=r"^https://github\.com/[^ ]+/releases/download/[^ ]+$")
    sha256: str
    schools: int = Field(ge=1)
    unknown: int = Field(ge=0)
    directory_sha256: str | None = None
    """The content SHA-256 of the directory the table was built from: a rebuild from the
    same directory must give the same table (the workflow fails when it does not)."""

    @field_validator("sha256", "directory_sha256")
    @classmethod
    def _digest(cls, value: str | None) -> str | None:
        if value is not None and not _SHA256.match(value):
            raise ValueError("a SHA-256 is 64 lowercase hex digits")
        return value

    def check_name(self) -> None:
        """The URL's last segment is the asset name of its digest.

        Raises:
            ValueError: it is not.
        """
        if not self.url.endswith("/" + asset_name(self.sha256)):
            raise ValueError(f"the pinned table's URL does not end in {asset_name(self.sha256)}")


class ElevationPins(_Pins):
    """Everything ``config/elevation.yaml`` pins."""

    source: Source
    table: TablePin | None = None


def asset_name(sha256: str) -> str:
    """The release asset name of a table: it carries the start of the table's digest, so a
    rebuild with other bytes never replaces the pinned one."""
    return f"{ASSET_PREFIX}{sha256[:_DIGITS_IN_NAME]}{ASSET_SUFFIX}"


def load_pins(path: Path = DEFAULT_PINS_PATH) -> ElevationPins:
    """Read ``config/elevation.yaml``.

    Raises:
        OSError: it cannot be read.
        yaml.YAMLError: it is not YAML.
        pydantic.ValidationError, ValueError: a pin is missing or malformed.
    """
    pins = ElevationPins.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    if pins.table is not None:
        pins.table.check_name()
    return pins
