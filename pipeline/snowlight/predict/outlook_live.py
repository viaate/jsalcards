"""The outlook on the serving loop (S7-F, spec-f s. 7 and 10; piece F3): the switch, the
private record a pass takes, and the forecast a pass reads.

``PREDICT_OUTLOOK`` (spec-f D7): ``off`` (the default) leaves the pass exactly as S7-L's,
byte for byte, and keeps no outlook state; ``shadow`` publishes exactly as off and, after the
pass is done, takes the outlook's record (:mod:`snowlight.predict.outlook_record`) in its
private state, with the outlook's chance as ``on`` would show it; ``on`` publishes the outlook
(v3 rates and ``T``). Nothing the shadow step does can change or darken the pass: it runs
after the file is published and any error it meets is only warned.
"""

import math
import time
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Final

import httpx
import numpy as np
import numpy.typing as npt

from snowlight.predict import forecast_history, forecast_live, ndfd
from snowlight.predict.alerts_live import ProductLog, UgcIndex
from snowlight.predict.calendar import is_school_day
from snowlight.predict.forecast_values import Forecasts
from snowlight.predict.opens import SaidOpen
from snowlight.predict.outlook import UNKNOWN, OutlookMode
from snowlight.predict.outlook_record import (
    NOT_TAKEN8,
    NOT_TAKEN16,
    Record,
    due_chance,
    due_morning,
    due_samples,
    pack,
    sample_moment,
    zone_members,
)
from snowlight.predict.outlook_serve import (
    Chances,
    OutlookServe,
    district_states,
)
from snowlight.predict.serve import FLOOR, ServeModel
from snowlight.predict.situations import Window, morning_record
from snowlight.schemas.predictions import Forecast, PredictionsFile

type ReadForecast = Callable[
    [ServeModel, tuple[date, ...], datetime, Callable[[date, str], datetime] | None,
     Collection[str] | None],
    Forecasts,
]  # fmt: skip
"""Reads the forecast for the days at a pass: ``(model, days, now, moment, zones)``, the
newest run counting at ``moment(day, zone)`` (``None``: at ``now``) for ``zones`` (``None``:
all)."""

STALE_IDENTITY: Final = "identity"
STALE_DARK: Final = "dark"

READ_SECONDS: Final = 90.0
"""The most a pass's outlook spends on forecast reads (:class:`Budget`). The shadow step runs
after the file is published, but the loop's next pass waits for it: an AWS feed that is slow or
down must not hold back a pass that carries a new warning. A healthy pass reads a new run's
values in a few seconds; one that runs out of time reads the rest as not read (the identity
when on, a skipped sample in the record: never imputed)."""
READ_TIMEOUT: Final = httpx.Timeout(10.0, connect=5.0)
"""Each forecast request's limit for the outlook (the history's reader allows 30 seconds)."""
READ_ATTEMPTS: Final = 2
"""Tries per forecast request for the outlook (the history's reader tries 6 times)."""
RUNS_KEPT: Final = timedelta(hours=4)
"""How old a run's values the outlook's reader keeps between passes: no run older than 3 hours
counts at a sample hour, and a sample is taken within 15 minutes after its hour."""


@dataclass(slots=True)
class Budget:
    """A pass's time for the outlook's reads (its forecast and, when its product log must be
    rebuilt, the NWS alert history): :meth:`start` once per pass where the outlook's work
    begins, :meth:`check` before every forecast request (the reader's ``before``) and
    :meth:`left` before every history page."""

    seconds: float = READ_SECONDS
    clock: Callable[[], float] = time.monotonic
    until: float = math.inf

    def start(self) -> None:
        """Start the pass's time."""
        self.until = self.clock() + self.seconds

    def left(self) -> bool:
        """Whether the pass's time is not up yet (the product log's history read asks it
        before every page)."""
        return self.clock() < self.until

    def check(self) -> None:
        """Raises:
        ndfd.NdfdError: the pass's time for forecast reads is up.
        """
        if self.clock() >= self.until:
            raise ndfd.NdfdError(f"the outlook's {self.seconds:.0f} s of forecast reads are up")


def prune_runs(
    cache: dict[tuple[datetime, date], forecast_history.RunValues], now: datetime
) -> None:
    """Drop the runs no read at ``now`` or after can count (:data:`RUNS_KEPT`), so the reader's
    cache holds a few hours of runs over a 320-minute loop, never every run it read."""
    oldest = now - RUNS_KEPT
    for key in [key for key in cache if key[0] < oldest]:
        del cache[key]


def forecast_reader(fetcher: forecast_history.Fetcher, share: float) -> ReadForecast:
    """Reads the NDFD runs for the outlook: the newest run at a moment, each run's values once
    (kept between passes while a read can still use them, :func:`prune_runs`), and the day
    listings once per pass (a day that did not list is not asked again that pass)."""
    cache: dict[tuple[datetime, date], forecast_history.RunValues] = {}
    built: dict[object, tuple[forecast_history.Schools, dict[str, int]]] = {}
    listed: dict[datetime, forecast_history.Listings] = {}

    def read(
        model: ServeModel,
        days: tuple[date, ...],
        now: datetime,
        moment: Callable[[date, str], datetime] | None,
        zones: Collection[str] | None,
    ) -> Forecasts:
        stamp = model.directory.stamp
        if stamp not in built:
            built.clear()
            cache.clear()
            schools = forecast_history.deciding_schools(model.directory, model.artifact)
            index = {leaid: i for i, leaid in enumerate(model.directory.district_ids)}
            built[stamp] = (schools, index)
        schools, index = built[stamp]
        if now not in listed:
            listed.clear()
            listed[now] = forecast_history.Listings(fetcher.get, again=False)
            prune_runs(cache, now)
        listings = listed[now]

        def runs_for(day: date) -> list[ndfd.Run] | None:
            around = listings.around(day)
            if around.error is not None:
                return None
            return list(ndfd.assemble_runs(around.listed).runs)

        reader = forecast_live.run_reader(schools, fetcher.opener(), cache)
        return forecast_live.forecasts(
            schools,
            index,
            days,
            now,
            runs_for,
            reader,
            share,
            moment=moment if moment is not None else (lambda _day, _zone: now),
            zones=zones,
        )

    return read


def outlook_mode_of(value: str | None) -> OutlookMode:
    """``PREDICT_OUTLOOK``: off when unset or empty.

    Raises:
        ValueError: not off, shadow or on.
    """
    text = (value or "").strip().lower() or OutlookMode.OFF.value
    try:
        return OutlookMode(text)
    except ValueError as error:
        raise ValueError(f"PREDICT_OUTLOOK must be off, shadow or on, not {value!r}") from error


@dataclass(slots=True)
class Taken:
    """What one pass took into the record (for its line)."""

    samples: int = 0
    skipped: int = 0
    chances: int = 0
    mornings: int = 0
    notes: list[str] = field(default_factory=list)

    def line(self) -> str | None:
        """The pass's line, or ``None`` when it took nothing."""
        if not (self.samples or self.skipped or self.chances or self.mornings):
            return None
        parts = [f"{self.samples} sample zones"]
        if self.skipped:
            parts.append(f"{self.skipped} skipped")
        if self.chances:
            parts.append(f"{self.chances} 8 PM chance zones")
        if self.mornings:
            parts.append(f"{self.mornings} 5 AM record zones")
        return "outlook record: " + ", ".join(parts)


def percent_values(p: npt.NDArray[np.float64]) -> npt.NDArray[np.int64]:
    """Chances as whole percent (:data:`NOT_TAKEN8` where there is none)."""
    found = np.full(p.shape, NOT_TAKEN8, dtype=np.int64)
    known = np.isfinite(p)
    found[known] = np.round(p[known] * 100).astype(np.int64)
    return found


def published_percent(made: PredictionsFile, districts: int, d: int) -> npt.NDArray[np.int64]:
    """The published chance of each district on day ``d`` of a file, in whole percent."""
    found = np.full(districts, NOT_TAKEN8, dtype=np.int64)
    for entry in made.districts:
        item = entry.days[d]
        if isinstance(item, Forecast) and entry.district < districts:
            found[entry.district] = round(item.p_no_school * 100)
    return found


def as_shown(
    p: npt.NDArray[np.float64], said: SaidOpen, days: Sequence[date]
) -> npt.NDArray[np.float64]:
    """Chances (districts, days) as a district's page shows them: the floor where it said
    school is on that day (:func:`~snowlight.predict.serve.forecast_file` does the same), so
    the record holds what ``on`` would show, never a chance a district's own word overrode."""
    found = np.array(p, dtype=np.float64, copy=True)
    for d, day in enumerate(days):
        rows = [i for i in said.districts.get(day, frozenset()) if 0 <= i < found.shape[0]]
        if rows:
            found[rows, d] = np.where(np.isfinite(found[rows, d]), FLOOR, found[rows, d])
    return found


def as_shown_percent(
    percent: npt.NDArray[np.int64], said: SaidOpen, days: Sequence[date]
) -> npt.NDArray[np.int64]:
    """Whole-percent chances as shown (:func:`as_shown`); 255 (no school day) stays."""
    found = np.array(percent, dtype=np.int64, copy=True)
    floor = round(FLOOR * 100)
    for d, day in enumerate(days):
        rows = [i for i in said.districts.get(day, frozenset()) if 0 <= i < found.shape[0]]
        if rows:
            found[rows, d] = np.where(found[rows, d] == NOT_TAKEN8, NOT_TAKEN8, floor)
    return found


def take_record(  # noqa: PLR0913 - the record, the model, the alerts and the moment
    record: Record,
    *,
    serve: OutlookServe,
    log: ProductLog,
    ugcs: UgcIndex,
    days: Sequence[date],
    now: datetime,
    window: Window,
    share: float,
    read: ReadForecast,
    published: Callable[[int], npt.NDArray[np.int64]] | None,
    chances: Chances | None,
) -> Taken:
    """Take into ``record`` every part due at ``now`` (see
    :mod:`snowlight.predict.outlook_record`): samples as of their hour (whole zones, as the
    history counts them), the 20:00 chances (``published(d)``: the file's percent on day ``d``;
    ``chances``: the outlook's), and the 05:00 record."""
    model = serve.rates
    members = zone_members(model.time_zone)
    taken = Taken()
    for d, day in enumerate(days):
        if not is_school_day(day):
            continue
        due: dict[int, list[str]] = {}
        for zone in members:
            k = due_samples(day, zone, now)
            if k is not None and zone not in record.sample(day, k).taken:
                due.setdefault(k, []).append(zone)
        for k, zones in sorted(due.items()):
            _take_sample(record, serve, log, ugcs, day, k, zones, window, share, read, now, taken)
        if published is not None and chances is not None:
            v2, outlook = record.chance(day)
            for zone, rows in members.items():
                if due_chance(day, zone, now) and zone not in v2.taken:
                    v2.put(zone, rows, published(d)[rows], now)
                    outlook.put(zone, rows, percent_values(chances.p[rows, d]), now)
                    taken.chances += 1
        for zone, rows in members.items():
            if due_morning(day, zone, now) and zone not in record.morning(day).taken:
                at = morning_record(day, zone).astimezone(UTC)
                c0, _heads = district_states(
                    model, log.events_at(at), ugcs, [day], at, window, share
                )
                record.morning(day).put(zone, rows, c0[rows, 0], now)
                taken.mornings += 1
    return taken


def _take_sample(  # noqa: PLR0913, PLR0917 - one sample hour of some zones
    record: Record,
    serve: OutlookServe,
    log: ProductLog,
    ugcs: UgcIndex,
    day: date,
    k: int,
    zones: list[str],
    window: Window,
    share: float,
    read: ReadForecast,
    now: datetime,
    taken: Taken,
) -> None:
    model = serve.rates
    members = zone_members(model.time_zone)
    forecasts = read(
        model,
        (day,),
        now,
        lambda night, zone: sample_moment(night, zone, k),
        frozenset(zones),
    )
    failed = forecasts.unread.get(day, {})
    by_moment: dict[datetime, list[str]] = {}
    for zone in zones:
        if failed.get(zone) == "error":
            taken.skipped += 1
            continue
        by_moment.setdefault(sample_moment(day, zone, k), []).append(zone)
    for at, group in sorted(by_moment.items()):
        c0, heads = district_states(model, log.events_at(at), ugcs, [day], at, window, share)
        for zone in group:
            rows = members[zone]
            codes = np.full(len(rows), NOT_TAKEN16, dtype=np.int64)
            run: datetime | None = None
            for j, i in enumerate(rows):
                given = forecasts.get(day, i)
                bucket = UNKNOWN if given is None else int(given.code)
                if given is not None and given.run_time is not None:
                    run = given.run_time if run is None else max(run, given.run_time)
                codes[j] = pack(int(c0[i, 0]), int(heads[i, 0]), bucket)
            record.sample(day, k).put(zone, rows, codes, now, run)
            taken.samples += 1


def stale_line(chances: Chances) -> str | None:
    """The pass's line on rows the outlook gave the identity, or ``None``."""
    parts = []
    if chances.stale:
        parts.append(f"{chances.stale:,} with no forecast run under 3 hours old (stale)")
    if chances.unknown:
        parts.append(f"{chances.unknown:,} with an unknown forecast")
    if chances.unsaid:
        parts.append(f"{chances.unsaid:,} whose forecast range does not read")
    if chances.no_rate:
        parts.append(f"{chances.no_rate:,} whose class has no rate")
    if chances.fell_back:
        parts.append(f"{chances.fell_back:,} whose outlook weighs a class with no rate")
    if not parts:
        return None
    return "outlook: issued-alerts-only chance (identity) for " + "; ".join(parts)


def finite_share(values: npt.NDArray[np.float64]) -> float:
    """The share of finite values (for reports)."""
    return float(np.isfinite(values).mean()) if values.size else math.nan
