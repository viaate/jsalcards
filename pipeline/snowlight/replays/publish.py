"""Publish the replay seeds as the site's ``replays/index.json`` and ``replays/<D>.json``.

A seed (:mod:`snowlight.replays.seed`) names its schools by NCES id, so it
outlives any one directory build. The site's files index schools by their
position in ``schools/meta.json``, which every directory build renumbers, so
each deploy publishes the seeds again against the directory it has just
built (``snowlight replays publish``):

* each NCES id becomes its index through ``schools.parquet`` (``index``, ``id``,
  ``state``), and the file is stamped with the :class:`DirectoryStamp` of the
  ``meta.json`` beside it, once that ``meta.json`` is shown to list the same
  schools in the same order;
* each file is one school day (:func:`follows_day_convention`): one frame,
  ``step_minutes`` 1440, ``start`` at ``<D>T12:00:00Z`` and the id ``<D>``;
  each row is ``[index, status, 0, 0, reason]``, sorted by index;
* the index lists every file published, sorted by (start, id), and each entry
  is checked against its file (:func:`~snowlight.schemas.replays.check_summary`);
  its ``states`` are those of the schools the file lights.

A seed is left out, with a warning and no file, when it is not a valid seed
named ``<D>.json``, when its day is less than two days before ``generated_at``
(nothing recent or current is ever shown as a replay), when more than 2% of
its ids are not in this directory, when it lights no school here, or when its
file would break a size budget (:data:`MAX_DAY_BYTES`, :data:`MAX_DAY_GZIP_BYTES`,
:data:`MAX_TOTAL_BYTES`, :data:`MAX_INDEX_BYTES`). A skipped seed never stops
a deploy: only an inconsistent directory or an unreadable input does.

``replays/index.json`` is written only when at least one replay is published.
Every replay file of an earlier run that this run does not write is removed,
so the folder never holds a stale index or day; with no seed it is removed
whole, and nothing under ``replays/`` is staged.

Nothing here reads the network or the clock: the same seeds, directory and
``generated_at`` give the same bytes.
"""

import gzip
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Final

import polars as pl
from pydantic import ValidationError

from snowlight.output import write_bytes_atomic
from snowlight.replays.seed import ReplaySeed, read_seed
from snowlight.schemas.directory import DirectoryStamp, SchoolDirectoryMeta
from snowlight.schemas.replays import ReplayFile, ReplayIndex, ReplaySummary, check_summary
from snowlight.schemas.vocab import Reason, Status

SCHEMA_VERSION: Final = 1
STEP_MINUTES: Final = 1440
"""One frame a day."""
FRAMES: Final = 1
NOON_UTC: Final = time(12, 0, tzinfo=UTC)
"""A day's frame shows ``<D>T12:00:00Z``: D's morning in every US zone."""
MIN_AGE_DAYS: Final = 2
"""A day is published only when it is at least this many days before ``generated_at``."""
MAX_MISSING_SHARE: Final = 0.02
"""The share of a seed's ids this directory may lack; a seed missing more is skipped."""
MAX_DAY_BYTES: Final = 400_000
MAX_DAY_GZIP_BYTES: Final = 100_000
MAX_INDEX_BYTES: Final = 8_000
MAX_TOTAL_BYTES: Final = 3_000_000
"""All replay files together, the index included."""
INDEX_NAME: Final = "index.json"
DAY_NAME: Final = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")
"""A seed's file name and a published day file's name: ``<D>.json``."""
STALE_NAME: Final = re.compile(r"^(?:index|\d{4}-\d{2}-\d{2}(?:-[a-z0-9]{1,16})?)\.json$")
"""Every name a replay file of any run may have had."""


class PublishError(Exception):
    """The directory or a folder cannot be read as one consistent build."""


@dataclass(frozen=True, slots=True)
class Skipped:
    """A seed left out, and why."""

    seed: str
    """The seed's file name."""
    reason: str


@dataclass(frozen=True, slots=True)
class PublishResult:
    """What one run published and left out."""

    published: tuple[str, ...]
    """The ids of the day files written, oldest first."""
    skipped: tuple[Skipped, ...]
    index_written: bool
    total_bytes: int
    """The bytes of every replay file written, the index included."""
    removed: tuple[str, ...]
    """Files of an earlier run that this run removed, by name."""


@dataclass(frozen=True, slots=True)
class Schools:
    """The directory as publishing needs it: each NCES id's index and state, and the stamp."""

    index: Mapping[str, int]
    state: Sequence[str]
    stamp: DirectoryStamp


def read_schools(directory_dir: Path, meta_path: Path) -> Schools:
    """Read ``schools.parquet`` and the ``meta.json`` of the same build.

    Raises:
        PublishError: a file is missing or unreadable, or ``meta.json`` does not
            list the parquet's schools in index order.
    """
    parquet = directory_dir / "schools.parquet"
    try:
        frame = pl.read_parquet(parquet, columns=["index", "id", "state"]).sort("index")
        meta = SchoolDirectoryMeta.from_json_bytes(meta_path.read_bytes())
    except (OSError, pl.exceptions.PolarsError, ValidationError) as error:
        raise PublishError(f"cannot read the directory: {error}") from error
    ids: list[str] = frame["id"].to_list()
    if frame["index"].to_list() != list(range(frame.height)):
        raise PublishError(f"{parquet}: index is not 0..{frame.height - 1}")
    if meta.count != frame.height or list(meta.ids) != ids:
        raise PublishError(f"{meta_path} does not list the schools of {parquet} in index order")
    return Schools(
        index={sid: position for position, sid in enumerate(ids)},
        state=frame["state"].to_list(),
        stamp=meta.stamp(),
    )


def day_start(day: str) -> datetime:
    """The moment a one-day replay's frame shows: ``<day>T12:00:00Z``."""
    return datetime.combine(datetime.fromisoformat(day).date(), NOON_UTC)


def follows_day_convention(replay: ReplayFile) -> bool:
    """Whether ``replay`` is one school day, as the site shows replays in v1."""
    start = replay.start.astimezone(UTC)
    return (
        replay.frames == FRAMES
        and replay.step_minutes == STEP_MINUTES
        and start.time() == NOON_UTC.replace(tzinfo=None)
        and replay.id == start.date().isoformat()
    )


class SkipSeedError(Exception):
    """A seed is left out of this run; the message says why."""


def replay_for(
    seed: ReplaySeed, schools: Schools, generated_at: datetime
) -> tuple[ReplayFile, ReplaySummary]:
    """The day file and index entry of ``seed`` in this directory.

    Raises:
        SkipSeedError: the day is too recent, too many of its ids are missing, it
            lights nothing here, or its file does not validate.
    """
    start = day_start(seed.day)
    if start.date() > generated_at.astimezone(UTC).date() - timedelta(days=MIN_AGE_DAYS):
        raise SkipSeedError(
            f"its day is less than {MIN_AGE_DAYS} days before {generated_at:%Y-%m-%d}"
        )
    found = [(schools.index.get(sid), status, reason) for sid, status, reason, _ in seed.statuses]
    rows = sorted(
        (index, Status(status), 0, 0, None if reason is None else Reason(reason))
        for index, status, reason in found
        if index is not None
    )
    missing = len(found) - len(rows)
    if missing > MAX_MISSING_SHARE * len(found):
        raise SkipSeedError(f"{missing} of its {len(found)} schools are not in this directory")
    if not rows:
        raise SkipSeedError("it lights no school in this directory")
    try:
        replay = ReplayFile(
            schema_version=SCHEMA_VERSION,
            id=seed.id,
            generated_at=generated_at,
            directory=schools.stamp,
            start=start,
            step_minutes=STEP_MINUTES,
            frames=FRAMES,
            rows=tuple(rows),
        )
        summary = ReplaySummary(
            id=replay.id,
            start=replay.start,
            step_minutes=replay.step_minutes,
            frames=replay.frames,
            peak_schools=len(rows),
            peak_frame=0,
            schools=len(rows),
            states=tuple(sorted({schools.state[row[0]] for row in rows})),
        )
        check_summary(summary, replay)
    except ValueError as error:  # pydantic's ValidationError is a ValueError
        raise SkipSeedError(f"its file does not validate: {error}") from error
    if not follows_day_convention(replay):
        raise SkipSeedError("its file is not one school day")
    return replay, summary


def _seed_paths(seeds_dir: Path) -> list[Path]:
    if not seeds_dir.is_dir():
        return []
    return sorted(path for path in seeds_dir.glob("*.json") if path.is_file())


def _clear_stale(out_dir: Path, keep: set[str]) -> list[str]:
    removed: list[str] = []
    if not out_dir.is_dir():
        return removed
    for path in sorted(out_dir.iterdir()):
        if path.is_file() and STALE_NAME.match(path.name) and path.name not in keep:
            path.unlink()
            removed.append(path.name)
    if not any(out_dir.iterdir()):
        out_dir.rmdir()
    return removed


def _encoded(model: ReplayFile | ReplayIndex) -> bytes:
    try:
        return model.to_json_bytes()
    except ValueError as error:  # PublishedContentError is a ValueError
        raise SkipSeedError(f"its file cannot be published: {error}") from error


def _check_budget(data: bytes) -> None:
    if len(data) > MAX_DAY_BYTES:
        raise SkipSeedError(f"its file is {len(data):,} bytes, over {MAX_DAY_BYTES:,}")
    packed = len(gzip.compress(data, compresslevel=6, mtime=0))
    if packed > MAX_DAY_GZIP_BYTES:
        raise SkipSeedError(f"its file is {packed:,} bytes gzipped, over {MAX_DAY_GZIP_BYTES:,}")


def _index(summaries: Sequence[ReplaySummary], generated_at: datetime) -> ReplayIndex:
    ordered = sorted(summaries, key=lambda summary: (summary.start, summary.id))
    return ReplayIndex(
        schema_version=SCHEMA_VERSION, generated_at=generated_at, replays=tuple(ordered)
    )


def day_file(
    path: Path, schools: Schools, generated_at: datetime
) -> tuple[ReplayFile, ReplaySummary, bytes]:
    """The day file of the seed at ``path``, its index entry and its bytes.

    Raises:
        SkipSeedError: the seed is left out (see the module docstring).
    """
    named = DAY_NAME.match(path.name)
    if named is None:
        raise SkipSeedError("its name is not <YYYY-MM-DD>.json")
    try:
        seed = read_seed(path)
    except (OSError, ValueError) as error:
        raise SkipSeedError(f"it is not a valid seed: {str(error).splitlines()[0]}") from error
    if seed.id != named.group(1):
        raise SkipSeedError(f"it holds day {seed.id}")
    replay, summary = replay_for(seed, schools, generated_at)
    data = _encoded(replay)
    _check_budget(data)
    return replay, summary, data


@dataclass(slots=True)
class _Run:
    generated_at: datetime
    days: list[tuple[ReplayFile, ReplaySummary, bytes]] = field(default_factory=list)
    index: bytes = b""
    day_bytes: int = 0

    def add(self, replay: ReplayFile, summary: ReplaySummary, data: bytes) -> None:
        """Take a day file, unless the index or all the files together would be over budget."""
        index = _encoded(_index([*(day[1] for day in self.days), summary], self.generated_at))
        if len(index) > MAX_INDEX_BYTES:
            size = f"{len(index):,} bytes, over {MAX_INDEX_BYTES:,}"
            raise SkipSeedError(f"the index would be {size}")
        if self.day_bytes + len(data) + len(index) > MAX_TOTAL_BYTES:
            raise SkipSeedError(f"the replays would be over {MAX_TOTAL_BYTES:,} bytes together")
        self.days.append((replay, summary, data))
        self.day_bytes += len(data)
        self.index = index


def publish(
    seeds_dir: Path,
    directory_dir: Path,
    meta_path: Path,
    out_dir: Path,
    *,
    generated_at: datetime,
) -> PublishResult:
    """Publish every seed in ``seeds_dir`` that passes, against this directory, to ``out_dir``.

    Seeds are taken in day order, oldest first; ``generated_at`` is the publishing
    moment (UTC, whole seconds). With no seed the directory is not read and
    ``out_dir`` is emptied of replay files.

    Raises:
        PublishError: there are seeds and the directory cannot be read as one build.
    """
    run = _Run(generated_at.astimezone(UTC).replace(microsecond=0))
    paths = _seed_paths(seeds_dir)
    skipped: list[Skipped] = []
    if paths:
        schools = read_schools(directory_dir, meta_path)
        for path in paths:
            try:
                run.add(*day_file(path, schools, run.generated_at))
            except SkipSeedError as skip:
                skipped.append(Skipped(path.name, str(skip)))
    written = {f"{replay.id}.json" for replay, _, _ in run.days}
    if run.days:
        written.add(INDEX_NAME)
    removed = _clear_stale(out_dir, written)
    for replay, _, data in run.days:
        write_bytes_atomic(out_dir / f"{replay.id}.json", data)
    if run.days:
        write_bytes_atomic(out_dir / INDEX_NAME, run.index)
    return PublishResult(
        published=tuple(replay.id for replay, _, _ in run.days),
        skipped=tuple(skipped),
        index_written=bool(run.days),
        total_bytes=run.day_bytes + len(run.index),
        removed=tuple(removed),
    )
