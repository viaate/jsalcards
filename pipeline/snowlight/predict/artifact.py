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
import hashlib
import io
import json
from collections.abc import Mapping
from datetime import date, datetime
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
PRIVATE_PATTERN: Final = r"^[A-Z0-9]{8}$"
"""A private school's NCES id."""
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
    private_level_min_days: int | None = None
    """The private schools' chain's level minimum (``None``: the districts')."""

    def rules(self, *, private: bool = False) -> Rules:
        """The chain's rules (``private``: the private schools' chain)."""
        level = self.private_level_min_days if private else None
        return make_rules(
            own_min_days=self.own_min_days,
            level_min_days=level if level is not None else self.level_min_days,
            nation_min_days=self.nation_min_days,
            almost_share=self.almost_share,
            floor=self.floor,
            ceiling=self.ceiling,
            fallback=self.fallback,
        )


def _check_strengths(strengths: Mapping[str, Mapping[str, Mapping[str, float]]]) -> None:
    for outcome in ("no_school", "delay"):
        levels = strengths.get(outcome)
        if levels is None or set(levels) != set(LEVELS):
            raise ValueError(f"strengths for {outcome} must name every level")
        for groups in levels.values():
            if set(groups) != set(GROUPS) or any(m <= 0 for m in groups.values()):
                raise ValueError("every class group needs a positive strength")


class ModelArtifact(_Model):
    """``model.json.gz``."""

    schema_version: Literal[2]
    situations: tuple[str, ...]
    training: Training
    settings: Settings
    strengths: dict[str, dict[str, dict[str, float]]]
    """Outcome (``no_school``, ``delay``) to level to class group to ``m``."""
    districts: dict[Annotated[str, Field(pattern=LEAID_PATTERN)], DistrictModel]
    private: dict[Annotated[str, Field(pattern=PRIVATE_PATTERN)], DistrictModel] = Field(
        default_factory=dict
    )
    """Every private school of the training directory, by NCES id, as its own unit (contract
    C3): its place and, where it has labeled days, its counts and record, counted over private
    schools only. Empty: private schools take the districts' rates around them."""
    private_strengths: dict[str, dict[str, dict[str, float]]] = Field(default_factory=dict)
    """The private chain's strengths, as :attr:`strengths` (empty with :attr:`private`)."""
    private_labeled_days: int = 0
    """Labeled private school-days the private counts hold."""

    @model_validator(mode="after")
    def _check(self) -> "ModelArtifact":
        if self.situations != SITUATION_KEYS:
            raise ValueError("the model's situations are not this code's")
        _check_strengths(self.strengths)
        if self.private_strengths or self.private:
            _check_strengths(self.private_strengths)
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


# --- what the live days taught (S7-L, :mod:`snowlight.predict.learn`) ---------------------------


class LiveCounts(_Model):
    """One district's live-read days per situation, in :data:`SITUATION_KEYS` order."""

    y: Counts
    n: Counts
    yd: Counts
    nd: Counts

    @model_validator(mode="after")
    def _check(self) -> "LiveCounts":
        for y, n, yd, nd in zip(self.y, self.n, self.yd, self.nd, strict=True):
            if not (0 <= y <= n and 0 <= yd <= nd <= n and nd == n - y):
                raise ValueError("a district's live counts do not add up")
        return self


class Learned(_Model):
    """``predictions/learned.json`` on the live host: what the served model adds to the
    committed one from the days the live pipeline read. Derived counts by LEAID only (no
    names, no source ids, no text), like the committed model.

    A situation in ``anchored`` has ``anchor_min_days`` or more live-read district-days
    nationally: its rates are counted over the live days (the nation's is their record), the
    committed model's archive counts giving each place's relative propensity only, and its
    sentence says "days we read live". Every other situation publishes the committed model's
    archive rates, unchanged.
    """

    schema_version: Literal[1]
    archive_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    """The committed model these counts are added to (its file's SHA-256): a learned file
    made over another committed model is not used."""
    through: date
    """The last live day counted: every later day is held out (checked against, never fit)."""
    labeled_days: int = Field(ge=0)
    """Live-read district-days counted."""
    anchored: tuple[str, ...]
    live: dict[Annotated[str, Field(pattern=LEAID_PATTERN)], LiveCounts]
    records: dict[Annotated[str, Field(pattern=LEAID_PATTERN)], dict[str, tuple[RecordDay, ...]]]
    """Each district's last live days per anchored situation, oldest first (at most 8)."""
    check: dict[str, float | int]
    """The walk-forward check it passed: held-out rows, and Brier and reliability of the
    model it replaced and of itself."""
    made_at: datetime
    days: tuple[date, ...]
    """Every live day counted (sorted, none after ``through``): a day later found misread and
    excluded from learning is caught here, whatever became of the store of labels."""

    @model_validator(mode="after")
    def _check(self) -> "Learned":
        if any(key not in SITUATION_KEYS for key in self.anchored):
            raise ValueError("an anchored situation is not this code's")
        if list(self.anchored) != sorted(set(self.anchored), key=SITUATION_KEYS.index):
            raise ValueError("anchored situations must be unique, in situation order")
        for days in self.records.values():
            for key, found in days.items():
                if key not in self.anchored:
                    raise ValueError(f"a live record of a situation not anchored: {key!r}")
                if not 1 <= len(found) <= 8:  # noqa: PLR2004
                    raise ValueError("a record holds 1 to 8 days")
                if any(later.day <= earlier.day for earlier, later in pairwise(found)):
                    raise ValueError("record days must be sorted and unique")
                if any(item.day > self.through for item in found):
                    raise ValueError("a live record day is after the days counted")
        if any(later <= earlier for earlier, later in pairwise(self.days)):
            raise ValueError("the days counted must be sorted and unique")
        if self.days and self.days[-1] > self.through:
            raise ValueError("a day counted is after through")
        if bool(self.days) != bool(self.labeled_days):
            raise ValueError("the days counted and the district-days counted disagree")
        return self

    def to_bytes(self) -> bytes:
        """Key-sorted JSON."""
        return dumps_json(json.loads(self.model_dump_json()))

    @classmethod
    def from_bytes(cls, data: bytes) -> "Learned":
        """Read a ``learned.json``.

        Raises:
            pydantic.ValidationError: it is not one.
        """
        return cls.model_validate_json(data, strict=False)


def sha256_of(data: bytes) -> str:
    """The SHA-256 of a committed model's bytes, as :attr:`Learned.archive_sha256` names it."""
    return hashlib.sha256(data).hexdigest()
