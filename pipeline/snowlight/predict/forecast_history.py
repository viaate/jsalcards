"""The forecast history: an NDFD bucket per district, school night and sample hour (S7-F F1).

The backfill streams the NDFD runs of 2018-19 to 2025-26 on GitHub's runners
(``.github/workflows/predict-forecast-history.yml``), never on a laptop: about 7 MB a run read
by range (:mod:`snowlight.predict.ndfd`), 25 runs a night, decoded and dropped at once. What it
keeps is small and derived: a bucket code per (district, night, sample hour), and the tables
that say how good the feed was (run age per sample, lateness per object, gaps, how each run's
periods were stamped, the runs and elements that did not read).

Samples (spec-f s. 5): every whole local hour from 08:00 D-1 to 04:00 D (21 hours, 3 per
slot), on every school day D from 15 August to 15 June. At each, the newest run that counts by
then (:func:`snowlight.predict.ndfd.newest_run`); none makes the code 13 (unknown).

Three steps, each a command (``snowlight predict forecast-history ACTION``):

* ``prepare``: the schools (the deployed directory's points, each district's deciding schools as
  the serving pass takes them, its time zone from the model); the listing of every day of the
  eight school years from its history host; the AWS lateness of the school days' objects and
  the delay it implies (10 minutes unless more than 2% are later: then their 98th percentile;
  archive copies and objects over 3 hours late are left out, see :func:`delay_from`); and the
  hours with no run at most 3 hours old. It fails before the matrix starts when the delay is
  over 30 minutes, a season's school-day hours are mostly gaps, or days did not list
  (:func:`measure_feed`).
* ``nights --season S --chunk C``: one school year's months (:data:`CHUNKS`), the 80-job matrix.
* ``collect``: one file per school year, a manifest with every file's SHA-256, the report.
"""

import argparse
import json
import math
import os
import re
import sys
import threading
import time as clock
from collections import Counter, defaultdict
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo

import httpx
import numpy as np
import numpy.typing as npt
import polars as pl

from snowlight.output import JSONValue, write_json
from snowlight.predict import ndfd
from snowlight.predict.artifact import ModelArtifact
from snowlight.predict.calendar import is_school_day, season_label
from snowlight.predict.ndfd import Element, Floats, Host, Listed, Run
from snowlight.predict.serve import CHARTER, PRIVATE, VIRTUAL, DeployedDirectory

FIRST_SEASON: Final = 2018
LAST_SEASON: Final = 2025
"""School years 2018-19 to 2025-26, by the year they start (NDFD history: spec-f s. 11)."""
CHUNKS: Final[tuple[tuple[int, ...], ...]] = (
    (8, 9),
    (10,),
    (11,),
    (12,),
    (1,),
    (2,),
    (3,),
    (4,),
    (5,),
    (6,),
)
"""The months of one matrix job (8 school years x 10 = 80 jobs)."""
SAMPLES: Final = 21
"""Sample hours a night: 08:00 D-1 (index 0) to 04:00 D (index 20), local."""
FIRST_SAMPLE_HOUR: Final = 8
SLOT_OF_SAMPLE: Final = tuple(1 + index // 3 for index in range(SAMPLES))
"""Slots S1-S7 (spec-f s. 5): three sample hours each, spread across the slot."""
LATE_SHARE: Final = 0.02
LATE_PERCENTILE: Final = 98.0
SCHOOLS_FILE: Final = "schools.parquet"
DELAY_FILE: Final = "delay.json"
PREPARED_OBJECTS_FILE: Final = "objects-prepare.parquet"
PREPARE_FIRST_DAY: Final = date(FIRST_SEASON, 8, 14)
"""UTC day D-1 of the first night (15 August 2018)."""
PREPARE_LAST_DAY: Final = date(LAST_SEASON + 1, 6, 15)
DELAY_LIMIT: Final = timedelta(minutes=30)
"""Over this the measured delay is not a publication lag but a fault (a bulk upload read as
publication): prepare fails before the matrix starts."""
GAP_SHARE_LIMIT: Final = 0.5
"""A season whose school-day hours are gaps (no run at most 3 hours old) more often than this
would come out mostly unknown: prepare fails before the matrix starts."""
FAILED_DAY_LIMIT: Final = 0.01
"""More days than this share that did not list (after retries) make prepare's measures unsure."""


def nights(season: int, chunk: int) -> list[date]:
    """The school days of one season's chunk of months, in order."""
    found: list[date] = []
    for month in CHUNKS[chunk]:
        year = season if month >= 7 else season + 1  # noqa: PLR2004 - July starts a season
        day = date(year, month, 1)
        while day.month == month:
            if is_school_day(day):
                found.append(day)
            day += timedelta(days=1)
    return found


def sample_time(day: date, zone: str, index: int) -> datetime:
    """Sample ``index`` (0 = 08:00 D-1, 20 = 04:00 D) of night ``day`` in ``zone``, in UTC."""
    hour = FIRST_SAMPLE_HOUR + index
    local_day = day - timedelta(days=1) if hour < 24 else day  # noqa: PLR2004
    return datetime.combine(local_day, time(hour % 24), tzinfo=ZoneInfo(zone)).astimezone(UTC)


# --- the schools --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Schools:
    """Each district's deciding schools: their points, district and zone."""

    lat: Floats
    lon: Floats
    district: npt.NDArray[np.int64]
    """Index into ``districts``."""
    districts: tuple[str, ...]
    """LEAIDs."""
    zone_of_district: tuple[str, ...]

    def frame(self) -> pl.DataFrame:
        """One row per school."""
        return pl.DataFrame(
            {
                "lat": self.lat,
                "lon": self.lon,
                "district": [self.districts[i] for i in self.district],
                "time_zone": [self.zone_of_district[i] for i in self.district],
            }
        )

    @classmethod
    def from_frame(cls, frame: pl.DataFrame) -> "Schools":
        """Rebuild from :meth:`frame`'s rows.

        Raises:
            ValueError: a district has two time zones.
        """
        pairs = frame.select("district", "time_zone").unique().sort("district")
        if pairs.height != pairs["district"].n_unique():
            raise ValueError("a district has two time zones")
        districts = tuple(pairs["district"].to_list())
        index = {leaid: i for i, leaid in enumerate(districts)}
        return cls(
            frame["lat"].to_numpy().astype(np.float64),
            frame["lon"].to_numpy().astype(np.float64),
            np.array([index[d] for d in frame["district"].to_list()], dtype=np.int64),
            districts,
            tuple(pairs["time_zone"].to_list()),
        )


def deciding_schools(directory: DeployedDirectory, artifact: ModelArtifact) -> Schools:
    """The schools whose forecast decides each district's (the serving pass's rule: its schools
    that are not private, charter or virtual, else all of them), for every deployed district
    the model places in a time zone."""
    points = directory.points
    flags = (points.kind & (PRIVATE | CHARTER | VIRTUAL)) == 0
    keep_lat: list[float] = []
    keep_lon: list[float] = []
    keep_district: list[int] = []
    districts: list[str] = []
    zones: list[str] = []
    district_of = points.district.astype(np.int64)
    order = np.argsort(district_of, kind="stable")
    ids, starts, counts = np.unique(district_of[order], return_index=True, return_counts=True)
    for found, start, count in zip(ids.tolist(), starts.tolist(), counts.tolist(), strict=True):
        if found >= len(directory.district_ids):
            continue
        leaid = directory.district_ids[found]
        entry = artifact.districts.get(leaid)
        if entry is None or entry.time_zone is None:
            continue
        mine = order[start : start + count]
        chosen = mine[flags[mine]] if flags[mine].any() else mine
        position = len(districts)
        districts.append(leaid)
        zones.append(entry.time_zone)
        keep_lat.extend((points.lat_e6[chosen] / 1e6).tolist())
        keep_lon.extend((points.lon_e6[chosen] / 1e6).tolist())
        keep_district.extend([position] * int(chosen.shape[0]))
    return Schools(
        np.array(keep_lat, dtype=np.float64),
        np.array(keep_lon, dtype=np.float64),
        np.array(keep_district, dtype=np.int64),
        tuple(districts),
        tuple(zones),
    )


@dataclass(frozen=True, slots=True)
class ZoneGroup:
    """The schools of one time zone's districts, grouped by district."""

    zone: str
    schools: npt.NDArray[np.int64]
    """Positions in :class:`Schools`."""
    groups: ndfd.Groups
    """Grouping of ``schools`` by district (``ids`` are district indexes)."""


def zone_groups(schools: Schools) -> list[ZoneGroup]:
    """One group per time zone, in name order."""
    zone_of_school = np.array(schools.zone_of_district, dtype=object)[schools.district]
    found: list[ZoneGroup] = []
    for zone in sorted(set(schools.zone_of_district)):
        mine = np.flatnonzero(zone_of_school == zone).astype(np.int64)
        found.append(ZoneGroup(zone, mine, ndfd.groups_of(schools.district[mine])))
    return found


# --- one night ----------------------------------------------------------------------------------

type Opener = Callable[[Listed], ndfd.Ranged]


@dataclass(slots=True)
class RunValues:
    """What one run says at every school for one night: snow and ice (inches) by period end,
    apparent temperature (F) by valid time. An element that did not read is empty (its values
    unknown) and named in :attr:`errors`; the others still count."""

    run: Run
    snow: dict[datetime, Floats] = field(default_factory=dict)
    ice: dict[datetime, Floats] = field(default_factory=dict)
    feels: dict[datetime, Floats] = field(default_factory=dict)
    stamps: dict[Element, ndfd.PeriodStamp] = field(default_factory=dict)
    """How the snow and ice files stamp their periods (:class:`ndfd.PeriodStamp`)."""
    errors: dict[Element, str] = field(default_factory=dict)
    """Why an element did not read (a period that does not fit, a file that does not read)."""
    repeated: int = 0
    """Messages its snow and ice files hold twice (:func:`ndfd.without_repeats`)."""
    refused: str | None = None
    """Why the run is not the run its stamps say (a file's reference time outside
    :func:`snowlight.predict.ndfd.reference_ok`): it is not used, and the run before it is."""

    @property
    def error(self) -> str | None:
        """The run's errors in one line (``None`` when every element read)."""
        if self.refused is not None:
            return f"refused: {self.refused}"
        if not self.errors:
            return None
        return "; ".join(f"{element.value}: {why}" for element, why in self.errors.items())

    @property
    def period_stamp(self) -> str | None:
        """The snow and ice files' :class:`snowlight.predict.ndfd.PeriodStamp` (joined by ``+``
        when they differ; ``None`` when neither read)."""
        found = sorted({stamp.value for stamp in self.stamps.values()})
        return "+".join(found) if found else None


AMOUNTS: Final = (
    (Element.SNOW, "snow", ndfd.snow_inches),
    (Element.ICE, "ice", ndfd.ice_inches),
)


@dataclass(frozen=True, slots=True)
class RunHeads:
    """A run's message heads by element, the readers they came from, and what reading them found
    (refusal, period stamps, errors) in :attr:`found`."""

    found: RunValues
    reads: Mapping[Element, ndfd.Ranged]
    heads: Mapping[Element, Sequence[ndfd.Head]]
    repeats: Mapping[Element, Sequence[ndfd.Head]] = field(default_factory=dict)
    """Snow and ice messages that repeat an earlier one (:func:`ndfd.without_repeats`)."""


def run_heads(run: Run, opener: Opener, apt_until: datetime) -> RunHeads:
    """Walk a run's files: snow and ice whole, apparent temperature to ``apt_until``. Refuse the
    run when a file's first reference time does not fit it
    (:func:`snowlight.predict.ndfd.reference_ok`); check the snow and ice periods
    (:func:`snowlight.predict.ndfd.period_stamp`). An element that does not read is dropped with
    its error."""
    found = RunValues(run)
    reads = {element: opener(run.files[element]) for element in ndfd.ELEMENTS}
    heads: dict[Element, list[ndfd.Head]] = {}
    for element, read in reads.items():
        stop = (lambda head: head.end >= apt_until) if element is Element.APT else None
        try:
            heads[element] = list(ndfd.walk(read, stop=stop))
        except ndfd.NdfdError as error:
            found.errors[element] = f"read: {error}"
            continue
        if not heads[element]:
            found.errors[element] = "read: no GRIB message"
            del heads[element]
    for element, listed in heads.items():
        if listed and not ndfd.reference_ok(listed[0].reference, run.time):
            found.refused = (
                f"{element.value} reference {listed[0].reference:%Y-%m-%d %H:%M}Z, "
                f"run {run.time:%Y-%m-%d %H:%M}Z"
            )
            return RunHeads(found, reads, {})
    repeats: dict[Element, list[ndfd.Head]] = {}
    for element, _, _ in AMOUNTS:
        if element in heads:
            heads[element], repeats[element] = ndfd.without_repeats(heads[element])
            found.repeated += len(repeats[element])
            try:
                found.stamps[element] = ndfd.period_stamp(heads[element])
            except ndfd.PeriodError as error:
                found.errors[element] = f"period: {error}"
                del heads[element]
    return RunHeads(found, reads, heads, repeats)


def _amount_message(walked: RunHeads, element: Element, head: ndfd.Head) -> bytes:
    """The message ``head`` names, checked against its element and any repeat of it.

    Raises:
        ndfd.NdfdError: it is another parameter, or a repeat of it holds other bytes.
    """
    if head.parameter != element.parameter:
        raise ndfd.NdfdError(f"{element.value} file holds {head.parameter}")
    read = walked.reads[element]
    raw = ndfd.message(read, head)
    for again in walked.repeats.get(element, ()):
        if again.end == head.end and ndfd.message(read, again) != raw:
            raise ndfd.NdfdError(f"two different messages of the period to {head.end}")
    return raw


def run_values(
    run: Run, day: date, bus_times: Sequence[datetime], where: ndfd.Cells, opener: Opener
) -> RunValues:
    """Read, decode and sample the messages one night needs from one run (:func:`run_heads`
    first: a refused run reads no value). An element whose file, periods or messages do not
    read is left empty with its error, and the others are read.

    Raises:
        ndfd.GridError: a message is not on the NDFD grid (the whole history stops).
    """
    walked = run_heads(run, opener, max(bus_times))
    found = walked.found
    if found.refused is not None:
        return found
    for element, name, convert in AMOUNTS:
        if element not in walked.heads:
            continue
        target: dict[datetime, Floats] = getattr(found, name)
        try:
            for end, head in ndfd.amount_heads(walked.heads[element], day).items():
                grid = ndfd.decode(_amount_message(walked, element, head), head)
                target[end] = convert(ndfd.sample(grid.values, where))
        except ndfd.GridError:
            raise
        except ndfd.NdfdError as error:
            found.errors[element] = f"read: {error}"
            target.clear()
    if Element.APT in walked.heads:
        apt = [h for h in walked.heads[Element.APT] if h.parameter == Element.APT.parameter]
        try:
            for valid, head in ndfd.apt_heads(apt, bus_times).items():
                grid = ndfd.decode(ndfd.message(walked.reads[Element.APT], head), head)
                found.feels[valid] = ndfd.fahrenheit(ndfd.sample(grid.values, where))
        except ndfd.GridError:
            raise
        except ndfd.NdfdError as error:
            found.errors[Element.APT] = f"read: {error}"
            found.feels.clear()
    return found


@dataclass(frozen=True, slots=True)
class Night:
    """One night's codes, its sample table, and the runs it refused."""

    codes: pl.DataFrame
    samples: pl.DataFrame
    refused: tuple[RunValues, ...] = ()
    """Runs whose content is another run's (:attr:`RunValues.refused`)."""


class Reason(StrEnum):
    """Why a sample's code is what it is, in the sample table (``None``: a run was read)."""

    NO_RUN = "no_run"
    """No run at most 3 hours old counted by then."""
    DAY_NOT_IN_ARCHIVE = "day_not_in_archive"
    """No run, and the host has no folder for UTC day D-1 or D (NCEI lacks some days)."""
    LISTING_FAILED = "listing_failed"
    """A day did not list after the retries: the whole night is unknown (``error`` says why)."""
    RUN_ERROR = "run_error"
    """No element of the run read (``error`` says why)."""
    ELEMENT_ERROR = "element_error"
    """Some element of the run did not read (``error`` says which): its values are unknown, the
    others count."""


def night_codes(  # noqa: PLR0913, PLR0917 - one night's inputs
    day: date,
    schools: Schools,
    groups: Sequence[ZoneGroup],
    runs: Sequence[Run],
    opener: Opener,
    share: float,
    workers: int = 1,
    *,
    listing: "Around | None" = None,
) -> Night:
    """The bucket of every district at each sample hour of night ``day``.

    ``listing`` is what the night's days listed: when a day did not list, no run is used (the
    night is unknown: a run of the other day could stand in for a newer one that was not
    seen); when the host has no folder for a day, its samples without a run say so.

    Raises:
        ndfd.GridError: a message is not on the NDFD grid.
    """
    failed = listing is not None and listing.error is not None
    if failed:
        runs = ()
    no_run = (
        Reason.LISTING_FAILED
        if failed
        else Reason.DAY_NOT_IN_ARCHIVE
        if listing is not None and listing.missing
        else Reason.NO_RUN
    )
    where = ndfd.cells(schools.lat, schools.lon)
    bus = {group.zone: ndfd.bus_time(day, group.zone) for group in groups}
    bus_times = sorted(set(bus.values()))
    times = {
        (group.zone, index): sample_time(day, group.zone, index)
        for group in groups
        for index in range(SAMPLES)
    }
    loaded: dict[datetime, RunValues] = {}
    refused: dict[datetime, RunValues] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        while True:  # a refused run gives way to the run before it, which is read in turn
            usable = [run for run in runs if run.time not in refused]
            chosen = {key: (at, ndfd.newest_run(usable, at)) for key, at in times.items()}
            todo = sorted(
                {
                    run.time: run
                    for _, run in chosen.values()
                    if run is not None and run.time not in loaded
                }.values(),
                key=lambda r: r.time,
            )
            if not todo:
                break
            for read in pool.map(lambda r: run_values(r, day, bus_times, where, opener), todo):
                loaded[read.run.time] = read
                if read.refused is not None:
                    refused[read.run.time] = read
    district_col: list[npt.NDArray[np.int64]] = []
    hour_col: list[npt.NDArray[np.int8]] = []
    code_col: list[npt.NDArray[np.int8]] = []
    filled_col: list[npt.NDArray[np.int8]] = []
    missing_col: list[npt.NDArray[np.int8]] = []
    rows: list[dict[str, object]] = []
    for group in groups:
        for index in range(SAMPLES):
            at, run = chosen[group.zone, index]
            values = None if run is None else loaded[run.time]
            passed_over = sum(
                1
                for item in refused.values()
                if item.run.available_at <= at
                and item.run.age(at) <= ndfd.MAX_AGE
                and (run is None or item.run.time > run.time)
            )
            found = _codes(values, group, day, at, bus[group.zone], share)
            codes = found.code
            district_col.append(group.groups.ids)
            hour_col.append(np.full(group.groups.ids.shape[0], index, dtype=np.int8))
            code_col.append(codes)
            filled_col.append(found.filled)
            missing_col.append(found.missing)
            rows.append(
                {
                    "night": day,
                    "time_zone": group.zone,
                    "sample": index,
                    "slot": SLOT_OF_SAMPLE[index],
                    "at": at,
                    "run_time": None if run is None else run.time,
                    "host": None if run is None else run.host.value,
                    "age_minutes": None if run is None else run.age(at).total_seconds() / 60,
                    "archive_copy": None if run is None else run.archive_copy,
                    "period_stamp": None if values is None else values.period_stamp,
                    "error": (listing.error if failed and listing else None)
                    if values is None
                    else values.error,
                    "reason": no_run.value if values is None else _reason(values),
                    "refused_runs": passed_over,
                    "repeated": None if values is None else values.repeated,
                    "districts": int(group.groups.ids.shape[0]),
                    "unknown": int((codes == ndfd.Bucket.UNKNOWN).sum()),
                    "unknown_filled": int((found.filled == ndfd.Bucket.UNKNOWN).sum()),
                }
            )
    districts = np.concatenate(district_col) if district_col else np.zeros(0, dtype=np.int64)
    codes_frame = pl.DataFrame(
        {
            "district": pl.Series([schools.districts[i] for i in districts], dtype=pl.String),
            "night": pl.Series([day] * int(districts.shape[0]), dtype=pl.Date),
            "sample": pl.Series(np.concatenate(hour_col) if hour_col else [], dtype=pl.Int8),
            "code": pl.Series(np.concatenate(code_col) if code_col else [], dtype=pl.Int8),
            "code_filled": pl.Series(
                np.concatenate(filled_col) if filled_col else [], dtype=pl.Int8
            ),
            "missing": pl.Series(np.concatenate(missing_col) if missing_col else [], dtype=pl.Int8),
        }
    )
    return Night(
        codes_frame,
        pl.DataFrame(rows, schema=SAMPLE_SCHEMA),
        tuple(refused[key] for key in sorted(refused)),
    )


def _reason(values: RunValues) -> str | None:
    if not values.errors:
        return None
    if len(values.errors) == len(ndfd.ELEMENTS):
        return Reason.RUN_ERROR.value
    return Reason.ELEMENT_ERROR.value


SAMPLE_SCHEMA: Final[dict[str, pl.DataType | type[pl.DataType]]] = {
    "night": pl.Date,
    "time_zone": pl.String,
    "sample": pl.Int8,
    "slot": pl.Int8,
    "at": pl.Datetime("us", "UTC"),
    "run_time": pl.Datetime("us", "UTC"),
    "host": pl.String,
    "age_minutes": pl.Float64,
    "archive_copy": pl.Boolean,
    "period_stamp": pl.String,
    "error": pl.String,
    "reason": pl.String,
    "refused_runs": pl.Int64,
    "repeated": pl.Int64,
    "districts": pl.Int64,
    "unknown": pl.Int64,
    "unknown_filled": pl.Int64,
}


@dataclass(frozen=True, slots=True)
class SampleCodes:
    """One sample's buckets for a zone's districts, under both readings of a cell with no
    value (an office that issues no grid of an element: ice in much of the West, snow around
    Tampa Bay)."""

    code: npt.NDArray[np.int8]
    """Strict: a deciding school with no value leaves its element unknown (13 if it could
    change the bucket)."""
    filled: npt.NDArray[np.int8]
    """A cell with no value read as nothing forecast of that element (a missing message or no
    run is still 13)."""
    missing: npt.NDArray[np.int8]
    """Bit 1 snow, 2 ice, 4 apparent temperature: a deciding school's cell had no value."""


MISSING_BITS: Final = (1, 2, 4)


def _codes(  # noqa: PLR0913, PLR0917 - one sample of one zone
    values: RunValues | None,
    group: ZoneGroup,
    day: date,
    at: datetime,
    bus: datetime,
    share: float,
) -> SampleCodes:
    count = group.groups.ids.shape[0]
    if values is None or values.refused is not None:
        unknown = np.full(count, int(ndfd.Bucket.UNKNOWN), dtype=np.int8)
        return SampleCodes(unknown, unknown.copy(), np.zeros(count, dtype=np.int8))
    nothing = np.full(group.schools.shape[0], np.nan)
    strict: list[Floats] = []
    filled: list[Floats] = []
    missing = np.zeros(count, dtype=np.int8)
    found = (
        ndfd.window_total(values.snow, day, at),
        ndfd.window_total(values.ice, day, at),
        values.feels.get(bus),
    )
    for position, (school, bit) in enumerate(zip(found, MISSING_BITS, strict=True)):
        coldest = position == 2  # noqa: PLR2004 - apparent temperature
        mine = nothing if school is None else school[group.schools]
        blank = np.isnan(mine)
        if school is not None:
            missing |= np.where(
                np.add.reduceat(blank[group.groups.order].astype(np.int64), group.groups.starts),
                bit,
                0,
            ).astype(np.int8)
        read_as_none = np.where(blank, np.inf if coldest else 0.0, mine)
        strict.append(ndfd.group_half(mine, group.groups, share, coldest=coldest))
        filled.append(
            ndfd.group_half(
                nothing if school is None else read_as_none, group.groups, share, coldest=coldest
            )
        )
    return SampleCodes(
        ndfd.bucket_codes(strict[0], strict[1], strict[2]),
        ndfd.bucket_codes(filled[0], filled[1], filled[2]),
        missing,
    )


# --- listing ------------------------------------------------------------------------------------


class Fetcher:  # pragma: no cover - the network
    """GETs and range reads with retries (NCEI's THREDDS answers 503 at times), counting bytes."""

    def __init__(
        self,
        client: httpx.Client,
        attempts: int = 6,
        range_attempts: int = ndfd.RANGE_ATTEMPTS,
    ) -> None:
        self.client = client
        self.attempts = attempts
        self.range_attempts = range_attempts
        self.bytes = 0
        self.requests = 0
        self._lock = threading.Lock()

    def _get(self, url: str, headers: Mapping[str, str] | None = None) -> httpx.Response:
        error: Exception | None = None
        for attempt in range(self.attempts):
            try:
                response = self.client.get(url, headers=headers)
            except httpx.HTTPError as failed:
                error = failed
            else:
                if response.status_code < 500 and response.status_code != 429:  # noqa: PLR2004
                    with self._lock:
                        self.bytes += len(response.content)
                        self.requests += 1
                    return response
                error = RuntimeError(f"HTTP {response.status_code} for {url}")
            clock.sleep(min(60.0, 2.0**attempt))
        raise ndfd.NdfdError(f"{url}: {error}")

    def get(self, url: str) -> bytes:
        """The body of a 200.

        Raises:
            ndfd.NotFoundError: it answered 404.
            ndfd.NdfdError: it never answered 200.
        """
        response = self._get(url)
        if response.status_code == httpx.codes.NOT_FOUND:
            raise ndfd.NotFoundError(f"HTTP 404 for {url}")
        if response.status_code != httpx.codes.OK:
            raise ndfd.NdfdError(f"HTTP {response.status_code} for {url}")
        return response.content

    def ranged(self, url: str) -> ndfd.Ranged:
        """Range reads of one file, each checked to hold the bytes the file holds there and
        tried again when not (:func:`snowlight.predict.ndfd.steady_reader`)."""

        def fetch(offset: int, size: int) -> ndfd.RangeAnswer:
            response = self._get(url, {"Range": f"bytes={offset}-{offset + size - 1}"})
            return range_answer(
                response.status_code,
                response.headers.get("content-range"),
                response.content,
                offset,
                size,
                url,
            )

        return ndfd.steady_reader(fetch, self.range_attempts, clock.sleep)

    def opener(self) -> Opener:
        """Opens a listed file."""
        return lambda listed: self.ranged(listed.url)


_CONTENT_RANGE: Final = re.compile(r"bytes (\d+)-(\d+)/(\d+|\*)")


def range_answer(  # noqa: PLR0913, PLR0917 - one response's parts
    status: int, content_range: str | None, content: bytes, offset: int, size: int, url: str
) -> ndfd.RangeAnswer:
    """What one answer to a range read holds (:class:`snowlight.predict.ndfd.RangeAnswer`): a
    206 by its Content-Range, a 200 (the host sent the whole file) cut to the range, a 416 as
    nothing past the file's end.

    Raises:
        ndfd.NdfdError: another status (after :class:`Fetcher`'s retries).
    """
    if status == httpx.codes.REQUESTED_RANGE_NOT_SATISFIABLE:
        said = (content_range or "").strip()
        total = int(said[8:]) if said.startswith("bytes */") and said[8:].isdigit() else None
        # Past the file's end: nothing. A 416 inside a file the host says (or said) is longer
        # is short; S3's 416 gives no size, so the reader checks it against an earlier answer.
        return ndfd.RangeAnswer(offset, b"", total, past_end=total is None)
    if status == httpx.codes.OK:
        return ndfd.RangeAnswer(offset, content[offset : offset + size], len(content), whole=True)
    if status != httpx.codes.PARTIAL_CONTENT:
        raise ndfd.NdfdError(f"HTTP {status} for a range of {url}")
    found = _CONTENT_RANGE.fullmatch((content_range or "").strip())
    if found is None:  # no way to know where the bytes are: never taken as the range
        return ndfd.RangeAnswer(-1, content, None)
    total = None if found[3] == "*" else int(found[3])
    return ndfd.RangeAnswer(int(found[1]), content, total)


def host_for(day: date) -> Host:
    """The history host of a UTC day."""
    return Host.AWS if day >= ndfd.AWS_FIRST_DAY else Host.NCEI


def list_day(fetch: Callable[[str], bytes], day: date) -> list[Listed]:
    """Every snow, ice and apparent temperature file of one UTC day, from its history host.

    Raises:
        ndfd.NotFoundError: the host has no folder for the day (NCEI lacks some days).
        ndfd.NdfdError: a listing does not read.
    """
    if host_for(day) is Host.NCEI:
        return ndfd.parse_ncei_catalog(fetch(ndfd.ncei_catalog_url(day)))
    found: list[Listed] = []
    for element in ndfd.ELEMENTS:
        token: str | None = None
        while True:
            page, token = ndfd.parse_aws_listing(fetch(ndfd.aws_listing_url(element, day, token)))
            found.extend(page)
            if token is None:
                break
    return found


@dataclass(frozen=True, slots=True)
class DayListing:
    """One UTC day's listing: its files, or that the host has no folder for it (``missing``:
    a 404, no files that day), or why it did not list (``error``: after the retries)."""

    day: date
    listed: tuple[Listed, ...] = ()
    missing: bool = False
    error: str | None = None


def list_day_safely(fetch: Callable[[str], bytes], day: date) -> DayListing:
    """:func:`list_day`, with a missing day and a listing that does not read kept as such."""
    try:
        return DayListing(day, tuple(list_day(fetch, day)))
    except ndfd.NotFoundError:
        return DayListing(day, missing=True)
    except ndfd.NdfdError as error:
        return DayListing(day, error=str(error))


@dataclass(frozen=True, slots=True)
class Around:
    """The files a night's samples can use (UTC days D-1 and D), the days of the two the host
    has no folder for, and why a day did not list (the night is then unknown)."""

    listed: list[Listed]
    missing: tuple[date, ...] = ()
    error: str | None = None


@dataclass(slots=True)
class Listings:
    """Day listings, each read once (a day that did not list is asked again next time)."""

    fetch: Callable[[str], bytes]
    days: dict[date, DayListing] = field(default_factory=dict)

    def around(self, night: date) -> Around:
        """The files of UTC days D-1 and D (every run a night's samples can use)."""
        found: list[Listed] = []
        missing: list[date] = []
        errors: list[str] = []
        for day in (night - timedelta(days=1), night):
            known = self.days.get(day)
            if known is None or known.error is not None:
                known = self.days[day] = list_day_safely(self.fetch, day)
            if known.error is not None:
                errors.append(f"{day}: {known.error}")
            elif known.missing:
                missing.append(day)
            found.extend(known.listed)
        return Around(found, tuple(missing), "; ".join(errors) or None)

    def listed(self) -> list[Listed]:
        """Every file listed so far."""
        return [item for known in self.days.values() for item in known.listed]


def objects_frame(listed: Iterable[Listed], fills: Collection[date] = ()) -> pl.DataFrame:
    """One row per listed file (the lateness table); ``fills`` are the archive fill days."""
    rows = {(item.element, item.stamp): item for item in listed}
    return pl.DataFrame(
        [
            {
                "element": item.element.value,
                "stamp": item.stamp,
                "host": item.host.value,
                "last_modified": item.last_modified,
                "late_minutes": None
                if item.lateness is None
                else item.lateness.total_seconds() / 60,
                "archive_copy": item.archive_copy(fills),
            }
            for item in sorted(rows.values(), key=lambda i: (i.stamp, i.element.value))
        ],
        schema={
            "element": pl.String,
            "stamp": pl.Datetime("us", "UTC"),
            "host": pl.String,
            "last_modified": pl.Datetime("us", "UTC"),
            "late_minutes": pl.Float64,
            "archive_copy": pl.Boolean,
        },
    )


def delay_from(late_minutes: Sequence[float]) -> tuple[timedelta, dict[str, float]]:
    """The run delay (spec-f s. 4): 10 minutes, unless more than 2% of objects were written more
    than 10 minutes after their stamp; then the 98th percentile of the lateness, whole minutes up.

    Objects written over 3 hours after their stamp are left out of the measure, and counted (over
    a day, :data:`snowlight.predict.ndfd.ARCHIVE_COPY_AFTER`, and the rest): the bulk upload of
    2020-06-01 to 06-03 made 2.4% of the school days' objects 1 to 46 days "late", which would
    set the delay to 8 days. Neither kind is a publication lag the delay could stand for: an
    archive copy counts from its stamp plus the delay, as an NCEI file does, and any other
    object over 3 hours late holds its run until it was written, when the run is too old.
    """
    base = ndfd.RUN_DELAY.total_seconds() / 60
    every = np.array(late_minutes, dtype=np.float64)
    archive = every > ndfd.ARCHIVE_COPY_AFTER.total_seconds() / 60
    over = ~archive & (every > ndfd.MAX_AGE.total_seconds() / 60)
    late = every[~archive & ~over]
    left_out = {"over_a_day": int(archive.sum()), "over_max_age": int(over.sum())}
    if late.size == 0:
        return ndfd.RUN_DELAY, {
            "objects": 0,
            **left_out,
            "late_share": 0.0,
            "p98_minutes": 0.0,
            "delay_minutes": base,
        }
    share = float((late > base).mean())
    p98 = float(np.percentile(late, LATE_PERCENTILE))
    minutes = base if share <= LATE_SHARE else max(base, math.ceil(p98))
    return timedelta(minutes=minutes), {
        "objects": int(late.size),
        **left_out,
        "late_share": share,
        "p98_minutes": p98,
        "max_minutes": float(late.max()),
        "delay_minutes": minutes,
    }


def gap_hours(runs: Sequence[Run], hours: Iterable[datetime]) -> list[datetime]:
    """The hours with no run at most 3 hours old that counts by then (as
    :func:`snowlight.predict.ndfd.newest_run` decides, in one pass over sorted runs)."""
    ordered = sorted(runs, key=lambda run: run.available_at)
    found: list[datetime] = []
    newest: datetime | None = None
    position = 0
    for hour in sorted(hours):
        while position < len(ordered) and ordered[position].available_at <= hour:
            time_of = ordered[position].time
            newest = time_of if newest is None else max(newest, time_of)
            position += 1
        if newest is None or hour - newest > ndfd.MAX_AGE:
            found.append(hour)
    return found


def season_of_hour(hour: datetime) -> int:
    """The school year (by its starting year) a UTC hour is in."""
    return hour.year if hour.month >= 7 else hour.year - 1  # noqa: PLR2004 - July starts a season


@dataclass(frozen=True, slots=True)
class Feed:
    """What prepare measures of the feed: the delay, the report and what stops the matrix."""

    delay: timedelta
    report: dict[str, JSONValue]
    problems: tuple[str, ...]
    fills: tuple[date, ...] = ()
    """The archive fill days (:func:`snowlight.predict.ndfd.archive_fills`)."""


def measure_feed(days: Sequence[DayListing]) -> Feed:
    """The delay from the AWS lateness of the school days' objects (:func:`delay_from`), the
    runs, and by season the school-day hours with no run at most 3 hours old (the first day's
    hours are left out: their runs of the day before were not listed).

    Problems (prepare then fails before the matrix): a delay over :data:`DELAY_LIMIT`; a season
    whose school-day hours are gaps more often than :data:`GAP_SHARE_LIMIT`; more than
    :data:`FAILED_DAY_LIMIT` of the days not listed (missing days are the host's and kept as
    gaps)."""
    ordered = sorted(days, key=lambda found: found.day)
    listed = [item for found in ordered for item in found.listed]
    school_days = {found.day for found in ordered if is_school_day(found.day)}
    delay, stats = delay_from(
        [
            item.lateness.total_seconds() / 60
            for item in listed
            if item.host is Host.AWS
            and item.lateness is not None
            and item.stamp.date() in school_days
        ]
    )
    fills = ndfd.archive_fills(listed)
    assembled = ndfd.assemble_runs(listed, delay, fills)
    first = ordered[0].day if ordered else None
    hours = [
        datetime.combine(found.day, time(hour), tzinfo=UTC)
        for found in ordered
        if found.day != first and found.day in school_days
        for hour in range(24)
    ]
    gaps = gap_hours(assembled.runs, hours)
    hours_by: Counter[int] = Counter(season_of_hour(hour) for hour in hours)
    gaps_by: Counter[int] = Counter(season_of_hour(hour) for hour in gaps)
    winter_by: Counter[int] = Counter(
        season_of_hour(hour) for hour in gaps if hour.month in {12, 1, 2}
    )
    shares = {season: gaps_by[season] / count for season, count in sorted(hours_by.items())}
    missing = [found.day.isoformat() for found in ordered if found.missing]
    failed = {found.day.isoformat(): found.error for found in ordered if found.error is not None}
    problems: list[str] = []
    if delay > DELAY_LIMIT:
        problems.append(f"the delay is {delay}, over {DELAY_LIMIT}")
    problems.extend(
        f"{season_label(season)}: {share:.1%} of school-day hours have no run"
        for season, share in shares.items()
        if share > GAP_SHARE_LIMIT
    )
    if ordered and len(failed) > FAILED_DAY_LIMIT * len(ordered):
        problems.append(f"{len(failed)} of {len(ordered)} days did not list")
    report: dict[str, JSONValue] = {
        "delay_minutes": delay.total_seconds() / 60,
        "days_listed": len(ordered),
        "first_day": None if first is None else first.isoformat(),
        "last_day": ordered[-1].day.isoformat() if ordered else None,
        "objects": len(listed),
        "archive_fill_days": {day.isoformat(): count for day, count in fills.items()},
        "archive_copies": sum(item.archive_copy(fills) for item in listed),
        "late_over_a_day_held": sum(
            item.over_a_day_late and not item.archive_copy(fills) for item in listed
        ),
        "runs": len(assembled.runs),
        "runs_archive_copy": sum(run.archive_copy for run in assembled.runs),
        "incomplete_half_hours": len(assembled.incomplete),
        "lateness_school_days": dict(stats),
        "school_day_hours_by_season": {season_label(k): v for k, v in sorted(hours_by.items())},
        "gap_hours_by_season": {season_label(k): v for k, v in sorted(gaps_by.items())},
        "gap_share_by_season": {season_label(k): round(v, 4) for k, v in shares.items()},
        "gap_hours_dec_feb_by_season": {season_label(k): v for k, v in sorted(winter_by.items())},
        "missing_days": list(missing),
        "failed_days": dict(failed),
        "problems": list(problems),
    }
    return Feed(delay, report, tuple(problems), tuple(fills))


PROBE_HOURS: Final = (time(3), time(12))
"""Prepare probes the run newest at 03:00 UTC (the evening before, in the lower 48), or at
12:00 UTC when no run counts at 03:00 (NCEI has no evening runs on many nights of 2018-19 and
2019-20)."""
PROBE_ERROR_LIMIT: Final = 0.5
"""A month whose probed runs have an element that does not read more often than this would come
out mostly unknown: prepare fails before the matrix starts."""
PROBE_FALLBACKS: Final = 12
"""Refused runs passed over before a probe gives up on its night."""


def probe_nights() -> list[date]:
    """The first night of each week of the history (every season's chunks)."""
    found: dict[tuple[int, int], date] = {}
    for season in range(FIRST_SEASON, LAST_SEASON + 1):
        for chunk in range(len(CHUNKS)):
            for night in nights(season, chunk):
                year, week, _ = night.isocalendar()
                found.setdefault((year, week), night)
    return sorted(found.values())


@dataclass(frozen=True, slots=True)
class Probe:
    """What prepare's probe found: by month, the runs probed, refused and with an element that
    does not read, and how their periods were stamped; and the months that stop the matrix."""

    report: dict[str, JSONValue]
    problems: tuple[str, ...]


def probe_periods(
    runs: Sequence[Run], opener: Opener, days: Iterable[date], workers: int = 1
) -> Probe:
    """Walk the heads of one run a night (the newest at the first of :data:`PROBE_HOURS` with a
    run on each of ``days``; a refused run gives way to the one before it) the way the nights
    do (:func:`run_heads`), without decoding a value. A month whose probed runs mostly have an
    element that does not read is a problem: its nights would come out unknown."""

    def probe(day: date) -> tuple[date, list[RunValues]]:
        refused: set[datetime] = set()
        seen: list[RunValues] = []
        for hour in PROBE_HOURS:
            at = datetime.combine(day, hour, tzinfo=UTC)
            for _ in range(PROBE_FALLBACKS + 1):
                run = ndfd.newest_run([r for r in runs if r.time not in refused], at)
                if run is None:
                    break
                found = run_heads(run, opener, run.time).found
                seen.append(found)
                if found.refused is None:
                    return day, seen
                refused.add(run.time)
        return day, seen

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        probed = list(pool.map(probe, days))
    months: dict[str, Counter[str]] = defaultdict(Counter)
    failures: list[JSONValue] = []
    for day, seen in probed:
        month = months[f"{day:%Y-%m}"]
        month["nights"] += 1
        month["refused"] += sum(found.refused is not None for found in seen)
        used = next((found for found in seen if found.refused is None), None)
        if used is None:
            month["no_run"] += 1
            continue
        month["probed"] += 1
        month[f"stamp_{used.period_stamp}"] += 1
        month["repeated"] += used.repeated > 0
        if used.errors:
            month["errors"] += 1
            failures.append(
                {"night": day.isoformat(), "run": used.run.time.isoformat(), "error": used.error}
            )
    problems = [
        f"{month}: {counts['errors']} of {counts['probed']} probed runs have an element that "
        "does not read"
        for month, counts in sorted(months.items())
        if counts["errors"] > PROBE_ERROR_LIMIT * counts["probed"]
    ]
    report: dict[str, JSONValue] = {
        "probe_nights": sum(counts["nights"] for counts in months.values()),
        "probe_by_month": {month: dict(counts) for month, counts in sorted(months.items())},
        "probe_failures": failures,
        "probe_refused": [
            {"night": day.isoformat(), "run": found.run.time.isoformat(), "why": found.refused}
            for day, seen in probed
            for found in seen
            if found.refused is not None
        ],
        "probe_problems": list(problems),
    }
    return Probe(report, tuple(problems))


ERROR_REASONS: Final = frozenset(
    {Reason.RUN_ERROR.value, Reason.ELEMENT_ERROR.value, Reason.LISTING_FAILED.value}
)
ERROR_MONTH_LIMIT: Final = 0.5
"""Collect fails when a month's samples mostly come from runs or listings that did not read."""


def error_share_by_month(samples: pl.DataFrame) -> dict[str, float]:
    """By month of the night, the share of samples whose run or listing did not read (whole or
    in part: :data:`ERROR_REASONS`)."""
    if samples.height == 0:
        return {}
    shares = (
        samples.with_columns(
            pl.col("night").dt.strftime("%Y-%m").alias("month"),
            pl.col("reason").is_in(sorted(ERROR_REASONS)).fill_null(False).alias("bad"),
        )
        .group_by("month")
        .agg(pl.col("bad").mean().alias("share"))
        .sort("month")
    )
    return {month: round(float(share), 4) for month, share in shares.iter_rows()}


def error_problems(shares: Mapping[str, float]) -> list[str]:
    """The months over :data:`ERROR_MONTH_LIMIT` (:func:`error_share_by_month`)."""
    return [
        f"{month}: {share:.1%} of samples from runs or listings that did not read"
        for month, share in sorted(shares.items())
        if share > ERROR_MONTH_LIMIT
    ]


# --- the commands -------------------------------------------------------------------------------


def register(actions: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register ``predict forecast-history``."""
    parser = actions.add_parser(
        "forecast-history", help="NDFD buckets per district, night and sample hour (runners)"
    )
    steps = parser.add_subparsers(dest="history_action", metavar="STEP", required=True)
    prepare = steps.add_parser("prepare", help="the schools, the AWS lateness and the delay")
    prepare.add_argument("--site", default="https://snowlightmap.com")
    prepare.add_argument(
        "--repository", default=os.environ.get("GITHUB_REPOSITORY", "viaate/jsalcards")
    )
    prepare.add_argument("--site-data", type=Path, default=None, help="meta.json, points.bin")
    prepare.add_argument("--model", type=Path, default=None)
    prepare.add_argument("--first-day", type=date.fromisoformat, default=PREPARE_FIRST_DAY)
    prepare.add_argument("--last-day", type=date.fromisoformat, default=PREPARE_LAST_DAY)
    prepare.add_argument("--workers", type=int, default=16)
    prepare.add_argument("--out", type=Path, required=True)
    prepare.set_defaults(handler=run_prepare)
    night = steps.add_parser("nights", help="one school year's months")
    night.add_argument("--season", type=int, required=True)
    night.add_argument("--chunk", type=int, required=True, choices=range(len(CHUNKS)))
    night.add_argument("--prepared", type=Path, required=True)
    night.add_argument("--limit", type=int, default=None, help="only the first N nights")
    night.add_argument(
        "--only", type=date.fromisoformat, action="append", help="only these nights (a dry run)"
    )
    night.add_argument("--workers", type=int, default=6)
    night.add_argument(
        "--range-attempts",
        type=int,
        default=ndfd.RANGE_ATTEMPTS,
        help="tries of a range read that came back short before its run's element is unreadable",
    )
    night.add_argument("--out", type=Path, required=True)
    night.set_defaults(handler=run_nights)
    collect = steps.add_parser("collect", help="one file per school year, manifest, report")
    collect.add_argument("--parts", type=Path, required=True)
    collect.add_argument("--prepared", type=Path, required=True)
    collect.add_argument("--out", type=Path, required=True)
    collect.set_defaults(handler=run_collect)


def _client() -> httpx.Client:  # pragma: no cover - the network
    from snowlight.predict.inputs import client  # noqa: PLC0415

    return client()


def run_prepare(args: argparse.Namespace) -> int:  # pragma: no cover - the network
    """Run ``forecast-history prepare``."""
    from snowlight.predict import artifact as artifact_module  # noqa: PLC0415
    from snowlight.predict.inputs import read_deployed_meta, read_local  # noqa: PLC0415

    model = artifact_module.load(args.model or artifact_module.ARTIFACT_PATH)
    if args.site_data is not None:
        directory = read_local(args.site_data)
    else:
        directory = read_deployed_meta(args.site, args.repository, os.environ.get("GITHUB_TOKEN"))[
            0
        ]
    schools = deciding_schools(directory, model)
    args.out.mkdir(parents=True, exist_ok=True)
    schools.frame().write_parquet(args.out / SCHOOLS_FILE)
    days = [
        args.first_day + timedelta(days=offset)
        for offset in range((args.last_day - args.first_day).days + 1)
    ]
    with _client() as http:
        fetcher = Fetcher(http)
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            listings = list(pool.map(lambda d: list_day_safely(fetcher.get, d), days))
        feed = measure_feed(listings)
        listed = [item for found in listings for item in found.listed]
        runs = ndfd.assemble_runs(listed, feed.delay, feed.fills).runs
        probe = probe_periods(runs, fetcher.opener(), probe_nights(), args.workers)
    objects_frame(listed, feed.fills).write_parquet(args.out / PREPARED_OBJECTS_FILE)
    problems = [*feed.problems, *probe.problems]
    report: dict[str, JSONValue] = {
        "schools": int(schools.lat.shape[0]),
        "districts": len(schools.districts),
        **feed.report,
        **probe.report,
        "problems": list(problems),
        "bytes": fetcher.bytes,
        "requests": fetcher.requests,
    }
    write_json(args.out / DELAY_FILE, report)
    sys.stdout.write(json.dumps(report, default=str) + "\n")
    for problem in problems:
        sys.stderr.write(f"forecast history: {problem}\n")
    return 1 if problems else 0


def run_nights(args: argparse.Namespace) -> int:  # pragma: no cover - the network
    """Run ``forecast-history nights``."""
    from snowlight.predict.config import CONFIG_PATH, PredictConfig  # noqa: PLC0415

    share = PredictConfig.load(CONFIG_PATH).weather.covered_share
    prepared = json.loads((args.prepared / DELAY_FILE).read_text(encoding="utf-8"))
    if prepared.get("problems"):
        sys.stderr.write(f"prepare found problems: {prepared['problems']}\n")
        return 2
    delay = timedelta(minutes=float(prepared["delay_minutes"]))
    fills = frozenset(date.fromisoformat(day) for day in prepared["archive_fill_days"])
    schools = Schools.from_frame(pl.read_parquet(args.prepared / SCHOOLS_FILE))
    groups = zone_groups(schools)
    days = [d for d in nights(args.season, args.chunk) if not args.only or d in args.only]
    days = days[: args.limit]
    started = clock.monotonic()
    codes: list[pl.DataFrame] = []
    samples: list[pl.DataFrame] = []
    refused: list[RunValues] = []
    with _client() as http:
        fetcher = Fetcher(http, range_attempts=args.range_attempts)
        listings = Listings(fetcher.get)
        for day in days:
            around = listings.around(day)
            assembled = ndfd.assemble_runs(around.listed, delay, fills)
            night = night_codes(
                day,
                schools,
                groups,
                assembled.runs,
                fetcher.opener(),
                share,
                args.workers,
                listing=around,
            )
            codes.append(night.codes)
            samples.append(night.samples)
            refused.extend(night.refused)
            unknown = int(night.samples["unknown"].sum())
            for run_time, reason, error in unreadable_runs(night.samples):
                sys.stdout.write(f"{day} run {run_time:%Y-%m-%d %H:%M}Z {reason}: {error}\n")
            sys.stdout.write(
                f"{day} runs {len(assembled.runs)} unknown {unknown} "
                f"MB {fetcher.bytes / 1e6:.0f} s {clock.monotonic() - started:.0f}\n"
            )
            sys.stdout.flush()
    args.out.mkdir(parents=True, exist_ok=True)
    stem = f"{args.season}-{args.chunk}"
    code_frame = pl.concat(codes) if codes else pl.DataFrame()
    code_frame.sort("district", "night", "sample").write_parquet(
        args.out / f"codes-{stem}.parquet", compression="zstd", compression_level=19
    )
    sample_frame = pl.concat(samples) if samples else pl.DataFrame(schema=SAMPLE_SCHEMA)
    missing_days = sorted(k.day.isoformat() for k in listings.days.values() if k.missing)
    sample_frame.write_parquet(args.out / f"samples-{stem}.parquet")
    objects_frame(listings.listed(), fills).write_parquet(args.out / f"objects-{stem}.parquet")
    write_json(
        args.out / f"summary-{stem}.json",
        {
            "season": season_label(args.season),
            "chunk": args.chunk,
            "nights": len(days),
            "delay_minutes": delay.total_seconds() / 60,
            "bytes": fetcher.bytes,
            "requests": fetcher.requests,
            "seconds": round(clock.monotonic() - started, 1),
            "missing_days": list(missing_days),
            "failed_days": {
                known.day.isoformat(): known.error
                for known in sorted(listings.days.values(), key=lambda k: k.day)
                if known.error is not None
            },
            **summarize(sample_frame, code_frame, refused),
        },
    )
    return 0


def unreadable_runs(samples: pl.DataFrame) -> list[tuple[datetime, str, str]]:
    """Each run of a night's samples whose files did not read, whole or in part (its time,
    :class:`Reason` and error), in run order: logged as the night is read."""
    if samples.height == 0:
        return []
    bad = (
        samples.filter(
            pl.col("run_time").is_not_null()
            & pl.col("reason").is_in([Reason.RUN_ERROR.value, Reason.ELEMENT_ERROR.value])
        )
        .unique(["run_time"])
        .sort("run_time")
    )
    return [
        (row["run_time"], row["reason"], row["error"] or "")
        for row in bad.select("run_time", "reason", "error").to_dicts()
    ]


def summarize(
    samples: pl.DataFrame, codes: pl.DataFrame, refused: Sequence[RunValues] = ()
) -> dict[str, JSONValue]:
    """Unknown samples and run age by slot, the runs' period stamps and errors, the refused runs,
    the error share by month, codes by bucket."""
    refused_rows: list[JSONValue] = [
        {"run": found.run.time.isoformat(), "why": found.refused} for found in refused
    ]
    if samples.height == 0:
        return {"samples": 0, "refused_runs": refused_rows}
    by_slot = (
        samples.group_by("slot")
        .agg(
            pl.len().alias("samples"),
            pl.col("run_time").is_null().sum().alias("no_run"),
            pl.col("age_minutes").median().alias("age_median"),
            pl.col("age_minutes").quantile(0.9).alias("age_p90"),
            pl.col("age_minutes").max().alias("age_max"),
        )
        .sort("slot")
    )
    runs = samples.filter(pl.col("run_time").is_not_null()).unique(["night", "run_time"])
    return {
        "samples": samples.height,
        "no_run": int(samples["run_time"].is_null().sum()),
        "by_slot": json.loads(json.dumps(by_slot.to_dicts(), default=str)),
        "runs": runs.height,
        "period_stamps": _counts(
            runs.with_columns(pl.col("period_stamp").fill_null("none")), "period_stamp"
        ),
        "run_reasons": _counts(runs.filter(pl.col("reason").is_not_null()), "reason"),
        "refused_runs": refused_rows,
        "samples_passing_over_refused_runs": int((samples["refused_runs"] > 0).sum()),
        "runs_with_repeated_messages": int((runs["repeated"].fill_null(0) > 0).sum()),
        "samples_from_archive_copies": int(samples["archive_copy"].fill_null(False).sum()),
        "reasons": _counts(samples.filter(pl.col("reason").is_not_null()), "reason"),
        "error_share_by_month": dict(error_share_by_month(samples)),
        "codes": _counts(codes, "code"),
        "codes_filled": _counts(codes, "code_filled"),
        "missing_bits": _counts(codes, "missing"),
    }


def _counts(codes: pl.DataFrame, column: str) -> JSONValue:
    if codes.height == 0:
        return {}
    found = codes[column].value_counts().sort(column)
    return {str(k): int(v) for k, v in found.iter_rows()}


def _days_of(summaries: Iterable[JSONValue], key: str) -> list[str]:
    """The days the jobs' summaries name under ``key`` (a list, or a mapping by day)."""
    found: set[str] = set()
    for summary in summaries:
        days = summary.get(key) if isinstance(summary, dict) else None
        if isinstance(days, list | dict):
            found.update(day for day in days if isinstance(day, str))
    return sorted(found)


def run_totals(summaries: Iterable[JSONValue]) -> dict[str, int]:
    """Over the jobs' summaries: the run-nights read (a run counts once for each night that
    samples it, so a run two nights share counts twice), and how many of them did not read
    whole (``run_error``) or in part (``element_error``)."""
    totals = {"run_nights": 0, Reason.RUN_ERROR.value: 0, Reason.ELEMENT_ERROR.value: 0}
    for summary in summaries:
        if not isinstance(summary, dict):
            continue
        runs = summary.get("runs")
        totals["run_nights"] += runs if isinstance(runs, int) else 0
        reasons = summary.get("run_reasons")
        if isinstance(reasons, dict):
            for key in (Reason.RUN_ERROR.value, Reason.ELEMENT_ERROR.value):
                count = reasons.get(key)
                totals[key] += count if isinstance(count, int) else 0
    return totals


def run_collect(args: argparse.Namespace) -> int:  # pragma: no cover - the workflow's files
    """Run ``forecast-history collect``: per school year files, the manifest and the report."""
    parts = sorted(args.parts.rglob("*.parquet")) + sorted(args.parts.rglob("summary-*.json"))
    args.out.mkdir(parents=True, exist_ok=True)
    by_kind: dict[tuple[str, str], list[Path]] = defaultdict(list)
    for path in parts:
        kind, season = path.stem.split("-")[0], path.stem.split("-")[1]
        by_kind[kind, season].append(path)
    summaries: list[JSONValue] = [
        json.loads(p.read_text(encoding="utf-8")) for p in parts if p.suffix == ".json"
    ]
    expected = {(s, c) for s in range(FIRST_SEASON, LAST_SEASON + 1) for c in range(len(CHUNKS))}
    present = {
        (int(p.stem.split("-")[1]), int(p.stem.split("-")[2]))
        for p in parts
        if p.stem.startswith("codes-")
    }
    written: list[Path] = []
    shares: dict[str, float] = {}
    for (kind, season), paths in sorted(by_kind.items()):
        if kind not in {"codes", "samples"}:
            continue
        frame = pl.concat([pl.read_parquet(p) for p in sorted(paths)], how="vertical_relaxed")
        if kind == "codes":
            frame = frame.sort("district", "night", "sample")
        else:
            shares.update(error_share_by_month(frame))
        target = args.out / f"{kind}-{season}.parquet"
        frame.write_parquet(target, compression="zstd", compression_level=19)
        written.append(target)
    objects = (
        pl.concat(
            [
                pl.read_parquet(p)
                for (kind, _), paths in by_kind.items()
                if kind == "objects"
                for p in paths
            ],
            how="vertical_relaxed",
        )
        .unique(["element", "stamp"])
        .sort("stamp", "element")
    )
    objects.write_parquet(args.out / "objects.parquet", compression="zstd")
    written.append(args.out / "objects.parquet")
    for name in (DELAY_FILE, PREPARED_OBJECTS_FILE):
        source = args.prepared / name
        target = args.out / name
        target.write_bytes(source.read_bytes())
        written.append(target)
    missing = sorted(f"{s}-{c}" for s, c in expected - present)
    problems = error_problems(shares)
    totals = run_totals(summaries)
    manifest: JSONValue = {
        "parts_expected": len(expected),
        "parts_present": len(present),
        "missing_parts": list(missing),
        "error_share_by_month": dict(sorted(shares.items())),
        "run_totals": dict(totals),
        "problems": list(problems),
        "missing_days": list(_days_of(summaries, "missing_days")),
        "failed_days": list(_days_of(summaries, "failed_days")),
        "files": {
            path.name: {
                "bytes": path.stat().st_size,
                "sha256": sha256(path.read_bytes()).hexdigest(),
            }
            for path in written
        },
        "summaries": summaries,
    }
    write_json(args.out / "manifest.json", manifest)
    sys.stdout.write(f"parts {len(present)} of {len(expected)}, missing {missing}\n")
    sys.stdout.write(
        f"run-nights {totals['run_nights']}, unreadable {totals[Reason.RUN_ERROR.value]}, "
        f"with an unreadable element {totals[Reason.ELEMENT_ERROR.value]}\n"
    )
    for problem in problems:
        sys.stderr.write(f"forecast history: {problem}\n")
    return 0 if not missing and not problems else 1
