"""The committed model: ``pipeline/data/predict/model.json.gz``.

It holds derived numbers only, keyed by LEAID (the owner-approved derived dataset): for
every district of the training directory its state, most common county and IANA zone,
and, where it has labeled days, its counts per situation (closings ``y`` of days ``n``;
delays ``yd`` of days with school ``nd``) and its record (the last labeled days of each
situation, with what it did). Then the tuned strengths. No names, no source ids, no
list text. The serving pass rebuilds the pooled chain from these counts
(:mod:`snowlight.predict.pool`), with the nearby districts of the deployed directory.

The file is gzip with no name and no time in its header, and key-sorted JSON inside,
so the same model always writes the same bytes.
"""

import gzip
import io
import json
from collections.abc import Mapping
from datetime import date
from itertools import pairwise
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from snowlight.output import dumps_json, write_bytes_atomic
from snowlight.predict.config import PIPELINE_ROOT
from snowlight.predict.pool import LEVELS, Rules, make_rules
from snowlight.predict.situations import GROUPS, SITUATIONS

ARTIFACT_PATH: Final = PIPELINE_ROOT / "data" / "predict" / "model.json.gz"
MAX_BYTES: Final = 5_000_000
SITUATION_KEYS: Final = tuple(item.key for item in SITUATIONS)
LEAID_PATTERN: Final = r"^\d{7}$"
COUNTY_PATTERN: Final = r"^\d{5}$"

type DayStatus = Literal["closed", "remote", "delayed", "open"]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


type Counts = Annotated[tuple[int, ...], Field(min_length=10, max_length=10)]


class RecordDay(_Model):
    """One labeled day of a district's record: the day and what the district did."""

    day: date
    did: DayStatus


class DistrictModel(_Model):
    """One district's place and, where it has labeled days, its counts and record."""

    state: Annotated[str, Field(pattern=r"^[A-Z]{2}$")] | None
    county: Annotated[str, Field(pattern=COUNTY_PATTERN)] | None
    time_zone: str | None
    y: Counts | None = None
    """Closings (no school) per situation, in :data:`SITUATION_KEYS` order."""
    n: Counts | None = None
    """Labeled days per situation."""
    yd: Counts | None = None
    """Delays per situation, among days with school."""
    nd: Counts | None = None
    """Labeled days with school per situation."""
    record: dict[str, tuple[RecordDay, ...]] = Field(default_factory=dict)
    """Situation key to its last labeled days, oldest first (at most 8)."""

    @model_validator(mode="after")
    def _check(self) -> "DistrictModel":
        counts = (self.y, self.n, self.yd, self.nd)
        if any(item is None for item in counts) and any(item is not None for item in counts):
            raise ValueError("a district's counts come all together or not at all")
        if (
            self.y is not None
            and self.n is not None
            and self.yd is not None
            and self.nd is not None
        ):
            for y, n, yd, nd in zip(self.y, self.n, self.yd, self.nd, strict=True):
                if not (0 <= y <= n and 0 <= yd <= nd <= n and nd == n - y):
                    raise ValueError("a district's counts do not add up")
        for key, days in self.record.items():
            if key not in SITUATION_KEYS:
                raise ValueError(f"record of an unknown situation {key!r}")
            if not 1 <= len(days) <= 8:  # noqa: PLR2004
                raise ValueError("a record holds 1 to 8 days")
            if any(later.day <= earlier.day for earlier, later in pairwise(days)):
                raise ValueError("record days must be sorted and unique")
        return self


class Training(_Model):
    """What the model was fit on."""

    seasons: tuple[int, ...]
    labeled_days: int
    directory_generated_on: date


class Settings(_Model):
    """The model settings serving must use with these counts."""

    own_min_days: int
    level_min_days: int
    nation_min_days: int
    almost_share: float
    fallback: dict[str, str]
    """A situation not modeled (too few labeled days nationally) to the one it takes."""
    floor: float
    ceiling: float

    def rules(self) -> Rules:
        """The chain's rules."""
        return make_rules(
            own_min_days=self.own_min_days,
            level_min_days=self.level_min_days,
            nation_min_days=self.nation_min_days,
            almost_share=self.almost_share,
            floor=self.floor,
            ceiling=self.ceiling,
            fallback=self.fallback,
        )


class ModelArtifact(_Model):
    """``model.json.gz``."""

    schema_version: Literal[2]
    situations: tuple[str, ...]
    training: Training
    settings: Settings
    strengths: dict[str, dict[str, dict[str, float]]]
    """Outcome (``no_school``, ``delay``) to level to class group to ``m``."""
    districts: dict[Annotated[str, Field(pattern=LEAID_PATTERN)], DistrictModel]

    @model_validator(mode="after")
    def _check(self) -> "ModelArtifact":
        if self.situations != SITUATION_KEYS:
            raise ValueError("the model's situations are not this code's")
        for outcome in ("no_school", "delay"):
            levels = self.strengths.get(outcome)
            if levels is None or set(levels) != set(LEVELS):
                raise ValueError(f"strengths for {outcome} must name every level")
            for groups in levels.values():
                if set(groups) != set(GROUPS) or any(m <= 0 for m in groups.values()):
                    raise ValueError("every class group needs a positive strength")
        return self

    def to_bytes(self) -> bytes:
        """Key-sorted JSON in a gzip with no name and no time."""
        raw = dumps_json(json.loads(self.model_dump_json()))
        buffer = io.BytesIO()
        with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0, compresslevel=9) as out:
            out.write(raw)
        return buffer.getvalue()

    @classmethod
    def from_bytes(cls, data: bytes) -> "ModelArtifact":
        """Read a ``model.json.gz``.

        Raises:
            OSError: it is not gzip.
            pydantic.ValidationError: it is not a model.
        """
        return cls.model_validate_json(gzip.decompress(data), strict=False)

    def write(self, path: Path = ARTIFACT_PATH) -> int:
        """Write the artifact; return its size.

        Raises:
            ValueError: it is larger than :data:`MAX_BYTES`.
        """
        data = self.to_bytes()
        if len(data) > MAX_BYTES:
            raise ValueError(f"the model is {len(data):,} bytes, over {MAX_BYTES:,}")
        write_bytes_atomic(path, data)
        return len(data)


def load(path: Path = ARTIFACT_PATH) -> ModelArtifact:
    """Read the committed model.

    Raises:
        OSError: it cannot be read.
        pydantic.ValidationError: it is not a model.
    """
    return ModelArtifact.from_bytes(path.read_bytes())


def strengths_json(m: Mapping[str, Mapping[str, float]]) -> dict[str, dict[str, float]]:
    """Level to group to ``m``, sorted."""
    return {level: dict(sorted(groups.items())) for level, groups in sorted(m.items())}
