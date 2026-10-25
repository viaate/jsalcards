"""The committed reasons model: ``pipeline/data/predict/terms.json.gz`` (S7 spec, piece 3).

Derived numbers only: each term's shape (its levels and the band it is 0 on), its steps on the
log-odds scale, the counted days' snow buckets the band was taken from (counts), the penalty,
and each district's usual posting time in minutes (by LEAID; :mod:`snowlight.predict.
announce`). It names the committed pooled model it was fit over (``model_sha256`` of
``model.json.gz``): serving uses it only over that model, as the terms were fit with that
model's bases as offsets. It also records backtest v2's gate as the fit's run judged it
(``gate``: passed or not, the pooled storm Brier gain, and the SHA-256 of the report it wrote):
serving refuses terms whose gate failed, or that record none, unless the config names the
lead's override (``serve.reasons_gate_override``; :func:`snowlight.predict.cli.terms_refused`).
Gzip with no name and no time, key-sorted JSON, so the same fit always writes the same bytes.
"""

import gzip
import io
import json
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from snowlight.output import dumps_json, write_bytes_atomic
from snowlight.predict.artifact import LEAID_PATTERN
from snowlight.predict.config import PIPELINE_ROOT
from snowlight.predict.terms import ADD_ONLY, ADD_ONLY_SNOW, LEVELS, Model, Shape, Term, TermFit

TERMS_PATH: Final = PIPELINE_ROOT / "data" / "predict" / "terms.json.gz"
MAX_BYTES: Final = 1_000_000


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class TermEntry(_Model):
    """One term."""

    levels: int
    low: int
    high: int
    up: tuple[float, ...]
    down: tuple[float, ...]
    counts: tuple[int, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> "TermEntry":
        if not 0 <= self.low <= self.high < self.levels:
            raise ValueError("a term's band must lie inside its levels")
        if len(self.up) != self.levels - 1 - self.high or len(self.down) != self.low:
            raise ValueError("a term has one step per level outside its band")
        if any(step < 0 for step in (*self.up, *self.down)):
            raise ValueError("a step is never below 0 (each term keeps its sign)")
        return self


class GateRecord(_Model):
    """Backtest v2's gate as the run that fit the terms judged it."""

    passed: bool
    """Every gate of piece 3 (:attr:`snowlight.predict.backtest_terms.Judged.passed`)."""
    gain: float
    """The pooled storm Brier's improvement as a share of the base's (6 places)."""
    report_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    """SHA-256 of the ``report.md`` the run wrote (UTF-8)."""


class TermsArtifact(_Model):
    """``terms.json.gz``."""

    schema_version: Literal[1]
    model_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    seasons: tuple[int, ...]
    rows: int
    penalty: float
    terms: dict[str, TermEntry]
    announce: dict[Annotated[str, Field(pattern=LEAID_PATTERN)], int] = Field(default_factory=dict)
    """LEAID to its usual posting time, minutes from the school day's midnight (-360 to 570)."""
    gate: GateRecord | None = None
    """Backtest v2's gate for this fit; ``None`` (a file from before it was recorded) is served
    as a failed gate."""

    @model_validator(mode="after")
    def _check(self) -> "TermsArtifact":
        for key, entry in self.terms.items():
            term = Term(key)
            if entry.levels != LEVELS[term]:
                raise ValueError(f"{key} has {entry.levels} levels, not {LEVELS[term]}")
            if (term in ADD_ONLY or term in ADD_ONLY_SNOW) and (entry.low or entry.down):
                raise ValueError(f"{key} only adds")
        if any(not -360 <= minutes < 570 for minutes in self.announce.values()):  # noqa: PLR2004
            raise ValueError("a posting time is the evening before or the morning of")
        return self

    def model(self) -> Model:
        """The terms as :mod:`snowlight.predict.terms` computes with them."""
        return Model(
            {
                Term(key): TermFit(
                    Term(key),
                    Shape(entry.levels, entry.low, entry.high),
                    up=entry.up,
                    down=entry.down,
                    counts=entry.counts,
                )
                for key, entry in self.terms.items()
            },
            self.penalty,
        )

    def to_bytes(self) -> bytes:
        """Key-sorted JSON in a gzip with no name and no time."""
        raw = dumps_json(json.loads(self.model_dump_json()))
        buffer = io.BytesIO()
        with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0, compresslevel=9) as out:
            out.write(raw)
        return buffer.getvalue()

    @classmethod
    def from_bytes(cls, data: bytes) -> "TermsArtifact":
        """Read a ``terms.json.gz``.

        Raises:
            OSError: it is not gzip.
            pydantic.ValidationError: it is not a terms file.
        """
        return cls.model_validate_json(gzip.decompress(data), strict=False)

    def write(self, path: Path = TERMS_PATH) -> int:
        """Write it; return its size.

        Raises:
            ValueError: it is larger than :data:`MAX_BYTES`.
        """
        data = self.to_bytes()
        if len(data) > MAX_BYTES:
            raise ValueError(f"the terms file is {len(data):,} bytes, over {MAX_BYTES:,}")
        write_bytes_atomic(path, data)
        return len(data)


def entry_of(fit: TermFit) -> TermEntry:
    """A fitted term as the file keeps it (steps rounded to 6 places)."""
    return TermEntry(
        levels=fit.shape.levels,
        low=fit.shape.low,
        high=fit.shape.high,
        up=tuple(round(max(step, 0.0), 6) for step in fit.up),
        down=tuple(round(max(step, 0.0), 6) for step in fit.down),
        counts=fit.counts,
    )


def load(path: Path = TERMS_PATH) -> TermsArtifact | None:
    """The committed terms, or ``None`` when there is no file."""
    if not path.is_file():
        return None
    return TermsArtifact.from_bytes(path.read_bytes())
