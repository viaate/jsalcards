"""``replays/index.json`` and ``replays/<id>.json``: past storms, frame by frame.

A replay is a run of evenly spaced frames: frame ``k`` shows the moment
``start + k * step_minutes``. Instead of repeating every affected school in every
frame, a replay file lists each spell once, as the first and last frame in which a
school had a status; the reader draws frame ``k`` from the rows whose span holds
``k``. ``tests/schemas`` checks that this and a frame-by-frame listing agree.

The index lists every replay with what the picker shows before the frames load;
:func:`check_summary` ties each summary to its file.
"""

from datetime import datetime, timedelta
from typing import Annotated, Self

from pydantic import Field, StringConstraints, model_validator

from snowlight.schemas.base import PublishedModel
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.scalars import Count, SchemaVersion, SchoolIndex, Usps, UtcInstant
from snowlight.schemas.vocab import Reason, Status

MAX_FRAMES = 4032  # two weeks of five-minute frames
MIN_STEP_MINUTES = 5
MAX_STEP_MINUTES = 1440

type ReplayId = Annotated[
    str,
    StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}(?:-[a-z0-9]{1,16})?$"),
    Field(description="The storm's first local day, with a suffix when two share it."),
]

type FrameIndex = Annotated[
    int, Field(ge=0, lt=MAX_FRAMES, description="A frame's position, from 0.")
]

type FrameCount = Annotated[
    int, Field(ge=1, le=MAX_FRAMES, description="How many frames a replay has.")
]

type StepMinutes = Annotated[
    int,
    Field(
        ge=MIN_STEP_MINUTES,
        le=MAX_STEP_MINUTES,
        description="Minutes between one frame and the next.",
    ),
]

type ReplayRow = Annotated[
    tuple[
        Annotated[SchoolIndex, Field(title="school")],
        Annotated[Status, Field(title="status")],
        Annotated[FrameIndex, Field(title="first")],
        Annotated[FrameIndex, Field(title="last")],
        Annotated[Reason | None, Field(title="reason")],
    ],
    Field(
        description=(
            "[school, status, first, last, reason]: the school had this status in every "
            "frame from first to last, inclusive."
        )
    ),
]


class ReplayFile(PublishedModel):
    """replays/<id>.json: every school's statuses through one storm."""

    schema_version: SchemaVersion
    id: ReplayId
    generated_at: UtcInstant
    directory: DirectoryStamp
    start: UtcInstant = Field(description="The moment frame 0 shows.")
    step_minutes: StepMinutes
    frames: FrameCount
    rows: tuple[ReplayRow, ...] = Field(
        description="Sorted by school, then first frame; a school's spans never overlap."
    )

    @model_validator(mode="after")
    def _check(self) -> Self:
        previous: tuple[int, int] | None = None
        for position, (school, _status, first, last, _reason) in enumerate(self.rows):
            where = f"rows[{position}]"
            if first > last or last >= self.frames:
                raise ValueError(f"{where}: frames {first}..{last} are not within 0..{self.frames}")
            if school >= self.directory.schools:
                raise ValueError(f"{where}: school {school} is not in the directory")
            if previous is not None and (
                school < previous[0] or (school == previous[0] and first <= previous[1])
            ):
                raise ValueError(f"{where}: rows must be sorted and a school's spans apart")
            previous = (school, last)
        return self

    @property
    def end(self) -> datetime:
        """The moment the last frame shows."""
        return self.start + timedelta(minutes=self.step_minutes * (self.frames - 1))

    def frame_counts(self) -> list[int]:
        """Return how many schools have a status in each frame."""
        deltas = [0] * (self.frames + 1)
        for _school, _status, first, last, _reason in self.rows:
            deltas[first] += 1
            deltas[last + 1] -= 1
        counts: list[int] = []
        running = 0
        for delta in deltas[:-1]:
            running += delta
            counts.append(running)
        return counts

    def frame(self, index: int) -> list[tuple[int, Status]]:
        """Return the schools with a status in frame ``index``, and their statuses."""
        if not 0 <= index < self.frames:
            raise IndexError(f"frame {index} is not within 0..{self.frames - 1}")
        return [
            (school, status)
            for school, status, first, last, _reason in self.rows
            if first <= index <= last
        ]


class ReplaySummary(PublishedModel):
    """What the replay picker shows before a replay's frames load."""

    id: ReplayId
    start: UtcInstant
    step_minutes: StepMinutes
    frames: FrameCount
    peak_schools: Count = Field(description="The most schools with a status in one frame.")
    peak_frame: FrameIndex = Field(description="The first frame with peak_schools.")
    schools: Count = Field(description="Distinct schools with a status in any frame.")
    states: tuple[Usps, ...] = Field(description="States with an affected school, sorted.")

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.peak_frame >= self.frames:
            raise ValueError("peak_frame is past the last frame")
        if self.peak_schools > self.schools:
            raise ValueError("peak_schools is more than the distinct schools")
        if list(self.states) != sorted(set(self.states)):
            raise ValueError("states must be sorted and unique")
        return self


class ReplayIndex(PublishedModel):
    """replays/index.json: every replay, oldest first."""

    schema_version: SchemaVersion
    generated_at: UtcInstant
    replays: tuple[ReplaySummary, ...]

    @model_validator(mode="after")
    def _check(self) -> Self:
        keys = [(replay.start, replay.id) for replay in self.replays]
        if keys != sorted(keys):
            raise ValueError("replays must be sorted by start, then id")
        ids = [replay.id for replay in self.replays]
        if len(set(ids)) != len(ids):
            raise ValueError("replay ids must be unique")
        return self


def check_summary(summary: ReplaySummary, replay: ReplayFile) -> None:
    """Raise ValueError unless ``summary`` describes ``replay``.

    ``states`` is not checked here: it needs the directory to map schools to states.
    """
    counts = replay.frame_counts()
    peak = max(counts)
    expected = {
        "id": replay.id,
        "start": replay.start,
        "step_minutes": replay.step_minutes,
        "frames": replay.frames,
        "peak_schools": peak,
        "peak_frame": counts.index(peak),
        "schools": len({row[0] for row in replay.rows}),
    }
    actual = summary.model_dump(include=set(expected))
    wrong = sorted(key for key, value in expected.items() if actual[key] != value)
    if wrong:
        raise ValueError(f"replay {replay.id}: the summary's {', '.join(wrong)} disagree")
