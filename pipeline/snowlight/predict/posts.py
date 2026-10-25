"""When districts posted, from the archive: the neighbors term's snapshots and the usual
announcement time (S7 spec, piece 3).

For every unit (a district, or a private school as its own unit) and labeled school day ``D``
the archive's settled day (the replay step, :mod:`snowlight.replays.build`) says which of its
schools were lit, and each lit status carries the rows that showed it. From them:

* ``first_any``: the capture time of the first row that showed any status of one of the
  unit's eligible schools for ``D`` (closed, remote, delayed, early dismissal);
* ``first_no_school``: when the unit first showed **no school** by the label's rule
  (:func:`no_school_at`): at least ``no_school_share`` (half) of its eligible schools shown
  closed or remote, each with a weather reason or none named. One building closed for a water
  main break is not its district canceling;
* ``posted_at``: the earliest time a list's own posted or updated stamp gives for one of those
  rows (:func:`snowlight.replays.rows.posted_stamp`; a page's stamp, or a stamp that names a
  date and no time, says nothing of when the row was posted and is left out).

And for every labeled district-day, its **snapshot**, the pass a morning run makes at
:data:`PASS_AT` (6 AM local) on ``D`` whatever the day's outcome (:func:`snapshot_time`): a
district that had shown any status by then has no snapshot (a pass treats a district that
posted as unknown); else the snapshot is the last capture, from 18:00 the evening before up to
the pass, of a list that carries the district (:func:`snapshot_time`;
:func:`snowlight.predict.labels.carries`). The neighbors term is trained on what the districts
next door had posted by then (:func:`neighbor_share`). The pass time is the same for a day the
district closed and a day it opened, so which rows have a snapshot, and when, does not depend
on the outcome (it did when an open day's snapshot ran to the end of the read window and a
closed day's stopped at its first post). A day with no such capture has no snapshot, and the
term is not judged on it.

Only times and ids: no list text, no names, no source ids leave this module's tables.
"""

import bisect
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo

import polars as pl

from snowlight.predict.labels import (
    COUNTED_STATES,
    NO_SCHOOL,
    WEATHER_REASONS,
    ReadRecord,
    carries,
)
from snowlight.schemas.vocab import Reason, Status

STAMP: Final = "%Y-%m-%dT%H:%M:%SZ"
SNAPSHOT_FROM: Final = time(18)
"""A snapshot is a capture from 18:00 the evening before (the class window's start)."""
PASS_AT: Final = time(6)
"""The morning pass a snapshot stands for, local on the school day: before most districts
decide, and the same for every day whatever it turned out to be."""


def counts_as_no_school(status: Status, reason: Reason | None) -> bool:
    """Whether a school's status counts toward its district canceling: closed or remote, for
    a weather reason or none named."""
    return status in NO_SCHOOL and (reason is None or reason in WEATHER_REASONS)


def no_school_at(times: Sequence[datetime], eligible: int, share: float) -> datetime | None:
    """When a unit with ``eligible`` schools first showed no school: the time the
    ``ceil(share * eligible)``-th of its schools was shown closed or remote (``times``: each
    such school's first, any order), or ``None`` when too few were."""
    if eligible <= 0:
        return None
    need = max(1, math.ceil(share * eligible - 1e-9))
    if len(times) < need:
        return None
    return sorted(times)[need - 1]


POSTS_SCHEMA: Final[dict[str, pl.DataType | type[pl.DataType]]] = {
    "unit": pl.String,
    "day": pl.Date,
    "first_any": pl.Datetime("us", "UTC"),
    "first_no_school": pl.Datetime("us", "UTC"),
    "posted_at": pl.Datetime("us", "UTC"),
}
SNAPSHOT_SCHEMA: Final[dict[str, pl.DataType | type[pl.DataType]]] = {
    "district": pl.String,
    "day": pl.Date,
    "snapshot_at": pl.Datetime("us", "UTC"),
}


@dataclass(frozen=True, slots=True)
class Post:
    """When one unit's status for one day first showed, and when its list says it posted."""

    unit: str
    day: date
    first_any: datetime | None
    first_no_school: datetime | None
    posted_at: datetime | None


def snapshot_window(day: date, zone: str, until: time) -> tuple[datetime, datetime]:
    """[18:00 the evening before, the pass on ``day``), local, as UTC instants: the pass is
    :data:`PASS_AT`, or ``until`` (the end of the read window) if earlier."""
    tz = ZoneInfo(zone)
    start = datetime.combine(day - timedelta(days=1), SNAPSHOT_FROM, tzinfo=tz)
    end = datetime.combine(day, min(until, PASS_AT), tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)


def snapshot_time(
    captures: Sequence[datetime], window: tuple[datetime, datetime], posted: datetime | None
) -> datetime | None:
    """The pass's snapshot: ``None`` when the unit had shown a status (``posted``, its first;
    ``None``: never) by the pass (the window's end), else the last capture in ``window``
    before the pass, or ``None`` when there is none. ``captures`` are sorted."""
    start, end = window
    if posted is not None and posted <= end:
        return None
    at = bisect.bisect_left(captures, end) - 1
    if at < 0 or captures[at] < start:
        return None
    return captures[at]


def neighbor_share(
    neighbors: Sequence[str],
    no_school_at: Mapping[str, datetime],
    at: datetime,
) -> tuple[float, tuple[str, ...]]:
    """The share of ``neighbors`` that had shown closed or remote by ``at`` (a capture at
    ``at`` itself counts), and which, nearest first. No neighbors: 0."""
    posted = tuple(e for e in neighbors if (seen := no_school_at.get(e)) is not None and seen <= at)
    if not neighbors:
        return 0.0, ()
    return len(posted) / len(neighbors), posted


def posts_frame(posts: Iterable[Post]) -> pl.DataFrame:
    """The posts table, sorted by unit and day."""
    rows = [
        {
            "unit": item.unit,
            "day": item.day,
            "first_any": item.first_any,
            "first_no_school": item.first_no_school,
            "posted_at": item.posted_at,
        }
        for item in posts
    ]
    return pl.DataFrame(rows, schema=POSTS_SCHEMA).sort(["unit", "day"])


def snapshots(  # noqa: PLR0913, PLR0917 - the labeled days, the reads and when each unit posted
    labeled: Iterable[tuple[str, date]],
    zone_of: Mapping[str, str],
    audience: Mapping[str, Mapping[str, date]],
    reads: Sequence[ReadRecord],
    kept: Mapping[date, frozenset[tuple[str, datetime]] | None],
    first_any: Mapping[tuple[str, date], datetime],
    until: time,
) -> pl.DataFrame:
    """Each labeled district-day's snapshot (:func:`snapshot_time`): captures are the counted
    reads (populated or empty) of the lists that carry the district that day; a populated
    read counts only when the replay step kept it (``kept[day]``; ``None``: every one)."""
    ordered = sorted(reads, key=lambda read: read.fetched_at)
    times = [read.fetched_at for read in ordered]
    by_day: dict[date, list[str]] = defaultdict(list)
    for district, day in labeled:
        by_day[day].append(district)
    rows: list[dict[str, object]] = []
    for day in sorted(by_day):
        low = bisect.bisect_left(times, datetime.combine(day - timedelta(days=2), time(), UTC))
        high = bisect.bisect_left(times, datetime.combine(day + timedelta(days=2), time(), UTC))
        keep = kept.get(day)
        per_station: dict[str, list[datetime]] = defaultdict(list)
        for read in ordered[low:high]:
            if read.state not in COUNTED_STATES:
                continue
            dropped = keep is not None and (read.source_id, read.fetched_at) not in keep
            if read.state == "populated" and dropped:
                continue
            per_station[read.source_id].append(read.fetched_at)
        carried: dict[str, list[datetime]] = defaultdict(list)
        for station, seen in per_station.items():
            for district in carries(audience, station, day):
                carried[district].extend(seen)
        for district in sorted(set(by_day[day])):
            zone = zone_of.get(district)
            at = None
            if zone is not None:
                captures = sorted(carried.get(district, ()))
                window = snapshot_window(day, zone, until)
                at = snapshot_time(captures, window, first_any.get((district, day)))
            rows.append({"district": district, "day": day, "snapshot_at": at})
    return pl.DataFrame(rows, schema=SNAPSHOT_SCHEMA).sort(["district", "day"])


def archive_posts(  # noqa: PLR0912 - one settled day's rows, walked once
    run: object,
    days: Iterable[date],
    unit_zone: Mapping[str, str],
    share: float,
) -> list[Post]:  # pragma: no cover - the real archive, settled by the replay step
    """Every unit's :class:`Post` on ``days`` from the archive run (``train.ArchiveRun``, its
    eligible and private sets already set by labeling); ``share``: the label's no-school
    share (:func:`no_school_at`)."""
    from dataclasses import replace  # noqa: PLC0415

    from snowlight.listed.evidence import LoadedRows  # noqa: PLC0415
    from snowlight.predict.train import ArchiveRun  # noqa: PLC0415
    from snowlight.replays.build import DayInputs, settle_day  # noqa: PLC0415
    from snowlight.replays.rows import (  # noqa: PLC0415
        NO_EXTRA,
        day_rows,
        instant,
        posted_stamp,
        rows_by_read,
    )

    assert isinstance(run, ArchiveRun)  # noqa: S101
    inputs = run.inputs
    assert isinstance(inputs, DayInputs)  # noqa: S101
    schools_of: dict[str, int] = defaultdict(int)
    for school, known in inputs.directory.schools.items():
        owner = run.unit_of(school, known.district_id)
        if owner is not None:
            schools_of[owner] += 1
    found: list[Post] = []
    for day in sorted(set(days)):
        rows_at, reads_at = run.index.near(day)
        loaded = inputs.loaded
        subset = LoadedRows(rows=loaded.rows[rows_at], reads=loaded.reads[reads_at], dropped={})
        day_inputs = replace(inputs, loaded=subset)
        settled = settle_day(day_inputs, day)
        extra_of: dict[int, object] = {}
        for key, read_rows in rows_by_read(day_rows(subset, day)).items():
            extras = inputs.extras.get(key)
            if extras is None or len(extras) != len(read_rows):
                continue
            for row, item in zip(read_rows, extras, strict=True):
                extra_of[id(row)] = item
        first_any: dict[str, datetime] = {}
        closed_times: dict[str, list[datetime]] = defaultdict(list)
        posted: dict[str, datetime] = {}
        directory = inputs.directory
        for school, lit in settled.lit.items():
            entry = directory.schools.get(school)
            if entry is None:
                continue
            unit = run.unit_of(school, entry.district_id)
            zone = unit_zone.get(unit) if unit is not None else None
            if unit is None or zone is None or not lit.evidence:
                continue
            seen = min(instant(reading.row.fetched_at) for reading in lit.evidence)
            if unit not in first_any or seen < first_any[unit]:
                first_any[unit] = seen
            if counts_as_no_school(lit.status, lit.reason):
                closed_times[unit].append(seen)
            for reading in lit.evidence:
                extra: object = extra_of.get(id(reading.row), NO_EXTRA)
                text = getattr(extra, "posted", None)
                if not text or getattr(extra, "page_stamp", False):
                    continue
                stamp = posted_stamp(
                    text, instant(reading.row.fetched_at), zone, getattr(extra, "posted_zone", None)
                )
                if stamp is None or stamp.date_only:
                    continue
                if unit not in posted or stamp.at < posted[unit]:
                    posted[unit] = stamp.at
        found.extend(
            Post(
                unit=unit,
                day=day,
                first_any=first_any[unit],
                first_no_school=no_school_at(closed_times[unit], schools_of[unit], share),
                posted_at=posted.get(unit),
            )
            for unit in sorted(first_any)
        )
    return found


def write_posts(  # noqa: PLR0913, PLR0917 - the run, its labels and where the units are
    run: object,
    labels: pl.DataFrame,
    table: pl.DataFrame,
    private: pl.DataFrame,
    audience_days: int,
    until: time,
    out: Path,
    share: float,
) -> tuple[int, int]:  # pragma: no cover - the real archive
    """``posts.parquet`` and ``snapshots.parquet`` beside the labels (internal: times and ids
    only); (unit-days posted, labeled district-days with a snapshot)."""
    from snowlight.predict.labels import audiences  # noqa: PLC0415
    from snowlight.predict.train import ArchiveRun  # noqa: PLC0415

    assert isinstance(run, ArchiveRun)  # noqa: S101
    known = labels.filter(pl.col("outcome") != "unknown")
    zone = {d: z for d, z in zip(table["district"], table["time_zone"], strict=True) if z}
    zone |= {s: z for s, z in zip(private["district"], private["time_zone"], strict=True) if z}
    days = sorted(set(known["day"].to_list()))
    frame = posts_frame(archive_posts(run, days, zone, share))
    frame.write_parquet(out / "posts.parquet")
    kept = {day: lit.kept if (lit := run.settled_days.get(day)) else None for day in days}
    first_any = {
        (unit, day): at
        for unit, day, at in frame.select("unit", "day", "first_any").iter_rows()
        if at is not None
    }
    snaps = snapshots(
        zip(known["district"].to_list(), known["day"].to_list(), strict=True),
        zone,
        audiences(run.listings, audience_days),
        run.reads,
        kept,
        first_any,
        until,
    )
    snaps.write_parquet(out / "snapshots.parquet")
    return frame.height, int(snaps["snapshot_at"].is_not_null().sum())
