"""Internal records: what the pipeline keeps about where each fact came from.

These models name sources, keep their URLs and record when each was read. They
are never published, and :class:`~snowlight.schemas.base.PublishedModel` refuses
to hold one. The only way from an observation to a published file is a projection
that drops the provenance: :meth:`ClosingObservation.closing`, :func:`closings_file`
and :func:`covered_file`.
"""

from collections.abc import Iterable
from dataclasses import replace
from datetime import date, datetime
from typing import Annotated, Self

from pydantic import Field, HttpUrl, StringConstraints, model_validator

from snowlight.schemas.base import InternalModel
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.live import Closing, ClosingsFile, CoveredFile, ranges_from_indices
from snowlight.schemas.scalars import (
    Count,
    LocalDate,
    MinuteOfDay,
    SchoolId,
    SchoolIndex,
    ShiftMinutes,
    UtcInstant,
)
from snowlight.schemas.vocab import SHIFTED, Reason, Status

type SourceId = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z0-9]+(?:[-_.][a-z0-9]+)*$", max_length=80),
    Field(description="A source's stable id in the pipeline's source list."),
]

type Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

HTTP_STATUS_MIN = 100
HTTP_STATUS_MAX = 599
MAX_LISTING_TEXT = 4000


class SourceSnapshot(InternalModel):
    """One fetch of one source: what was asked for, when, and what came back."""

    source_id: SourceId
    url: HttpUrl
    fetched_at: UtcInstant
    http_status: Annotated[int, Field(ge=HTTP_STATUS_MIN, le=HTTP_STATUS_MAX)] | None
    sha256: Sha256 | None
    bytes: Count | None
    error: Annotated[str, StringConstraints(max_length=500)] | None

    @model_validator(mode="after")
    def _check(self) -> Self:
        if (self.sha256 is None) != (self.bytes is None):
            raise ValueError("sha256 and bytes are both set when a body was read")
        if self.error is None and self.sha256 is None:
            raise ValueError("a snapshot without a body must say what went wrong")
        return self


class ClosingObservation(InternalModel):
    """One school's status for one local day, as one source listed it."""

    school_index: SchoolIndex
    school_id: SchoolId
    status: Status
    day: LocalDate
    announced_at: UtcInstant | None
    reason: Reason | None
    shift_minutes: ShiftMinutes | None
    clock_minute: MinuteOfDay | None
    source_id: SourceId
    source_url: HttpUrl
    snapshot_at: UtcInstant
    listing_text: Annotated[str, StringConstraints(min_length=1, max_length=MAX_LISTING_TEXT)]

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.status not in SHIFTED and (
            self.shift_minutes is not None or self.clock_minute is not None
        ):
            raise ValueError("only delays and early dismissals have times")
        if self.announced_at is not None and self.announced_at > self.snapshot_at:
            raise ValueError("announced after the snapshot that listed it")
        return self

    def closing(self) -> Closing:
        """Return the published row: the status without where it came from."""
        return Closing(
            school=self.school_index,
            day=self.day,
            status=self.status,
            announced_at=self.announced_at,
            reason=self.reason,
            shift_minutes=self.shift_minutes,
            clock_minute=self.clock_minute,
        )


class CoverageObservation(InternalModel):
    """One source read live: which schools its listing speaks for."""

    source_id: SourceId
    source_url: HttpUrl
    snapshot_at: UtcInstant
    complete: bool = Field(
        description="True when the listing was read in full and covers every school listed."
    )
    school_indices: tuple[SchoolIndex, ...]


class OutputDigest(InternalModel):
    """A file the run wrote."""

    path: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_./-]*$")]
    bytes: Count
    gzip_bytes: Count
    sha256: Sha256


class RunManifest(InternalModel):
    """Everything one pipeline run read and wrote. Never published.

    It is written outside the site-data folder, or inside it only under a name
    ending in ``.internal.json``, which the site check and the publishing step skip
    (:data:`snowlight.schemas.registry.INTERNAL_SUFFIX`).
    """

    generated_at: UtcInstant
    pipeline_version: Annotated[str, StringConstraints(min_length=1, max_length=40)]
    snapshots: tuple[SourceSnapshot, ...]
    outputs: tuple[OutputDigest, ...]


class ConflictError(ValueError):
    """Two observations give one school two different statuses for one day."""


def closings_file(
    observations: Iterable[ClosingObservation],
    *,
    generated_at: datetime,
    directory: DirectoryStamp,
) -> ClosingsFile:
    """Project observations onto ``live/closings.json``.

    Observations that agree are merged: the row keeps the earliest ``announced_at``
    any of them gives. Resolving disagreements, and keeping only each school's
    local today and tomorrow, are the caller's job.

    Raises:
        ConflictError: two observations for one school and day disagree on anything
            but ``announced_at``.
        ValueError: the rows break a rule of the file (see :meth:`ClosingsFile.encode`).
    """
    rows: dict[tuple[int, date], Closing] = {}
    for observation in observations:
        row = observation.closing()
        key = (row.school, row.day)
        kept = rows.get(key)
        if kept is None:
            rows[key] = row
            continue
        if replace(kept, announced_at=None) != replace(row, announced_at=None):
            raise ConflictError(f"school {row.school} on {row.day}: {kept} vs {row}")
        times = [time for time in (kept.announced_at, row.announced_at) if time is not None]
        rows[key] = replace(kept, announced_at=min(times) if times else None)
    return ClosingsFile.encode(rows.values(), generated_at=generated_at, directory=directory)


def covered_file(
    observations: Iterable[CoverageObservation],
    *,
    generated_at: datetime,
    directory: DirectoryStamp,
) -> CoveredFile:
    """Project the complete live listings onto ``live/covered.json``.

    Only observations marked ``complete`` count: a partial read proves nothing
    about the schools it did not reach.
    """
    covered: set[int] = set()
    for observation in observations:
        if observation.complete:
            covered.update(observation.school_indices)
    return CoveredFile.model_validate(
        {
            "schema_version": 1,
            "generated_at": generated_at,
            "directory": directory,
            "ranges": ranges_from_indices(covered),
        }
    )
