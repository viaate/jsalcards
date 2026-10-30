"""The reads a pass hands the ledger, from S4's station reader through the live pool.

:func:`source_read` turns one :func:`~snowlight.sources.stations.fetch.read_station`
result into a :class:`~snowlight.live.ingest.SourceRead`:

* a read that parsed rows is ``ok``, or ``not_modified`` when the body was the stored
  one (a 304); one that said nothing is listed is ``empty``;
* a 403 or a challenge is ``blocked`` (never worked around); any other failure, or a
  list judged not current (``stale``), is ``error``: it holds nothing;
* a station the registry keeps from being polled gives no read at all.

Rows become :class:`~snowlight.live.ledger.SeenRow` in memory only, with the station's
zone for a row stamp that names none (:func:`~snowlight.live.ingest.station_zone`).
:func:`sequential_reads` reads the stations one after another through one polite
client, calling ``tick`` between stations (the directory handshake runs once a minute
while a pass reads); a station whose read raises is an ``error`` read, logged with its
id and the error's type only (a local run's fallback).

:class:`LiveReads` is the ingest's reader: each pass reads the sources the cadence
(:mod:`snowlight.live.cadence`) says are due through the concurrent pool
(:mod:`snowlight.live.pool`, :func:`live_pool`); a source the pool stopped is ``late``
or ``deferred`` (:func:`pool_read`).
"""

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from typing import Final

import httpx

from snowlight.live.cadence import AlertWatch, Cadence, county_zones, next_mark
from snowlight.live.ingest import Ingest, SourceRead, station_zone
from snowlight.live.ledger import Outcome, seen_row
from snowlight.live.pool import (
    LIVE_ATTEMPTS,
    WORKERS,
    HostPacer,
    PassResult,
    Pool,
    RequestLog,
    RobotsStore,
    SourceResult,
    pace_key,
)
from snowlight.live.resolve import LiveDirectory
from snowlight.sources.stations.fetch import RunResult, read_station, skip_reason
from snowlight.sources.stations.http import ConditionalStore, PoliteClient, make_client
from snowlight.sources.stations.model import HealthStatus
from snowlight.sources.stations.registry import Registry, Station

LOG: Final = logging.getLogger(__name__)
PACER_FILE: Final = "pacer.json"
_BLOCKED: Final = frozenset({HTTPStatus.FORBIDDEN, HTTPStatus.UNAUTHORIZED})

type Tick = Callable[[], None]
type ReadsFn = Callable[[datetime, Sequence[str], Tick], Sequence[SourceRead]]


def no_tick() -> None:
    """A ``tick`` that does nothing."""


def due_sources(registry: Registry) -> frozenset[str]:
    """The sources each pass reads: the stations S4's reader does not skip (active, with a
    URL, on a platform whose terms permit polling). G12b's share counts over them."""
    return frozenset(
        station.id
        for station in registry.stations.values()
        if skip_reason(registry, station) is None and station.poll_url is not None
    )


def read_safely(source_id: str, read: Callable[[], SourceRead | None]) -> SourceRead | None:
    """``read()``, or an ``error`` read of ``source_id`` when it raises (logged with the id and
    the error's type only: an adapter's message may quote the page)."""
    try:
        return read()
    except Exception as error:
        LOG.error("read %s: %s", source_id, type(error).__name__)
        return SourceRead(source_id, Outcome.ERROR, datetime.now(UTC))


def source_read(station: Station, result: RunResult, directory: LiveDirectory) -> SourceRead | None:
    """One station's read as the ledger takes it, or ``None`` when it was not read."""
    health = [entry for entry in result.health if entry.source_id == station.id]
    if not health or health[-1].status is HealthStatus.SKIPPED:
        return None
    last = health[-1]
    rows = [raw for raw in result.rows if raw.source_id == station.id]
    fetched_at = max((raw.fetched_at for raw in rows), default=last.checked_at)
    if last.status is HealthStatus.OK:
        outcome = Outcome.NOT_MODIFIED if last.not_modified else Outcome.OK
    elif last.status is HealthStatus.EMPTY:
        return SourceRead(station.id, Outcome.EMPTY, last.checked_at)
    elif last.http_status in _BLOCKED:
        return SourceRead(station.id, Outcome.BLOCKED, last.checked_at)
    else:
        return SourceRead(station.id, Outcome.ERROR, last.checked_at)
    zone = station_zone(station, directory)
    variant = last.variant or ""
    seen = tuple(
        seen_row(raw, variant=variant, platform=station.platform, zone=zone) for raw in rows
    )
    return SourceRead(station.id, outcome, fetched_at, seen)


def sequential_reads(  # pragma: no cover - reads the stations over the network
    registry: Registry, directory: LiveDirectory, cache_dir: Path
) -> ReadsFn:
    """Read every active station (or only the ids given) once, one after another."""
    from snowlight.sources.stations.fetch import read_station  # noqa: PLC0415
    from snowlight.sources.stations.http import (  # noqa: PLC0415
        ConditionalStore,
        PoliteClient,
        make_client,
    )

    client = PoliteClient(make_client(), ConditionalStore(cache_dir))

    def reads(now: datetime, only: Sequence[str], tick: Tick) -> Sequence[SourceRead]:
        found: list[SourceRead] = []
        for station in sorted(registry.stations.values(), key=lambda item: item.id):
            if only and station.id not in only:
                continue
            read = read_safely(
                station.id,
                lambda station=station: source_read(  # type: ignore[misc]
                    station,
                    read_station(registry, station, client, now.replace(microsecond=0)),
                    directory,
                ),
            )
            if read is not None:
                found.append(read)
            tick()
        return found

    return reads


def pool_read(
    station: Station, read: SourceResult, directory: LiveDirectory, at: datetime
) -> SourceRead | None:
    """One source's pool read as the ledger takes it: ``late`` and ``deferred`` kept as such,
    and a read that raised as ``error``, at ``at`` (the pass's start)."""
    if read.outcome in {Outcome.LATE, Outcome.DEFERRED} or not read.result.health:
        return SourceRead(station.id, read.outcome, at)
    return source_read(station, read.result, directory)


def live_pool(
    cache_dir: Path,
    state_dir: Path,
    *,
    workers: int = WORKERS,
    log: RequestLog | None = None,
    http: httpx.Client | None = None,
) -> Pool:
    """The pool of one process: one HTTP connection pool (keeping no idle connection, so
    every request's deadline can cut it), pacer (seeded from and kept in
    ``state_dir/pacer.json``), robots store (kept in ``state_dir/robots.json``) and
    conditional store shared by every worker's client."""
    shared = http or make_client(keepalive=False)
    store = ConditionalStore(cache_dir)
    robots = RobotsStore(state_dir / "robots.json")
    pacer = HostPacer(log=log)
    pacer.load(state_dir / PACER_FILE, datetime.now(UTC))

    def client() -> PoliteClient:
        return PoliteClient(
            shared, store, attempts=LIVE_ATTEMPTS, pacer=pacer, robots=robots, pace_key=pace_key
        )

    return Pool(
        client=client,
        robots=robots,
        workers=workers,
        pacer=pacer,
        pacer_path=state_dir / PACER_FILE,
    )


@dataclass(slots=True)
class LiveReads:
    """The live reads (a :data:`ReadsFn`): each pass reads the sources the cadence says are
    due (or the ids given) through the pool, keeps the cadence, and tells the ingest which
    sources G12b counts (:meth:`~snowlight.live.cadence.Cadence.recently_due`)."""

    registry: Registry
    directory: LiveDirectory
    pool: Pool
    cadence: Cadence
    ingest: Ingest | None = None
    reader: Callable[[Registry, Station, PoliteClient, datetime], RunResult] = read_station
    """Reads one station (S4's reader; tests replace it)."""
    on_holds: Callable[[Sequence[tuple[str, datetime, str]]], None] | None = None
    """Told at once of each source a pass newly blocked or deferred ``(id, until, why)``, so
    the state database keeps it even if this process dies before its next push."""
    unread: set[str] | None = None
    """The sources whose last good read held rows and that this process has not read yet
    (``None`` until the first pass asks the ledger): each is read as soon as the cadence's
    politeness floor allows, whatever its cadence, so a successor never shows a status of
    it dark while its calm interval runs (the ingest holds a source's statuses only once
    this process has read it)."""

    def pending(self) -> list[Station]:
        """The sources still to be read first by this process (see :attr:`unread`)."""
        if self.unread is None:
            polled = due_sources(self.registry)
            holding = self.ingest.holding() if self.ingest is not None else frozenset()
            self.unread = set(holding & polled)
        return [self.registry.stations[sid] for sid in sorted(self.unread)]

    def waits(self, now: datetime) -> bool:
        """Whether a run starting at ``now`` should hold its first pass for the next grid
        mark: a source to read first was read too recently to ask again yet (its
        predecessor read it in this grid slot, or under 4 minutes ago) but may be asked at
        the mark; or there is no source to read first that may be asked now and the run
        before passed in this grid slot, so a pass now would find almost nothing due, count
        a share near 0 and be refused (the next mark reads what is due as any grid pass). A
        source a server's wait or block holds past the mark, or one whose last read failed
        and is not due by then, is not waited for. The alert set is brought to ``now``
        first, as a pass's :meth:`~snowlight.live.cadence.Cadence.due` does, so a source in
        an alert county is judged on its 5-minute interval."""
        self.cadence.refresh_alerts(now)
        pending = self.pending()
        mark = next_mark(now)
        if any(
            not self.cadence.may_read(station, now) and self.cadence.may_read(station, mark)
            for station in pending
        ):
            return True
        if any(self.cadence.may_read(station, now) for station in pending):
            return False
        return self.cadence.passed_in_slot(now)

    def __call__(self, now: datetime, only: Sequence[str], tick: Tick) -> Sequence[SourceRead]:
        if only:
            due = [
                self.registry.stations[sid]
                for sid in sorted(set(only))
                if sid in self.registry.stations
            ]
            # Every source the ingest polls stays due, so G12b refuses a pass that read only
            # some of them: ``--only`` is for looking, not for publishing.
            self.cadence.note(now, due_sources(self.registry))
        else:
            due = self.cadence.due(now, due_sources(self.registry))
            picked = {station.id for station in due}
            first = [
                station
                for station in self.pending()
                if station.id not in picked and self.cadence.may_read(station, now)
            ]
            if first:
                self.cadence.note(now, (station.id for station in first))
                due = sorted([*due, *first], key=lambda station: station.id)
        registry, reader = self.registry, self.reader
        whole = now.replace(microsecond=0)  # the stations' records keep whole seconds

        def read(station: Station, client: PoliteClient) -> RunResult:
            return reader(registry, station, client, whole)

        result = self.pool.run_pass(due, read, alerted=self.cadence.in_alert, tick=tick)
        before = {sid: clock.not_before for sid, clock in self.cadence.clocks.items()}
        keep_pass(self.cadence, result)
        if self.unread is not None:
            # asked (a late or deferred source is not: it is due again anyway)
            self.unread -= {
                item.source_id
                for item in result.sources
                if item.outcome not in {Outcome.LATE, Outcome.DEFERRED}
            }
        self._tell_holds(before)
        if self.ingest is not None:
            self.ingest.due = self.cadence.recently_due(now)
        found = []
        for item in result.sources:
            station = self.registry.stations[item.source_id]
            read_one = read_safely(
                item.source_id,
                lambda s=station, i=item: pool_read(s, i, self.directory, result.started),  # type: ignore[misc]
            )
            if read_one is not None:
                found.append(read_one)
        return found

    def _tell_holds(self, before: Mapping[str, datetime | None]) -> None:
        if self.on_holds is None:
            return
        found = [
            (sid, clock.not_before, clock.outcome.value)
            for sid, clock in sorted(self.cadence.clocks.items())
            if clock.not_before is not None
            and clock.outcome in {Outcome.BLOCKED, Outcome.DEFERRED}
            and before.get(sid) != clock.not_before
        ]
        if found:
            self.on_holds(found)


ALERTS_DEADLINE: Final = 30.0
"""Seconds one read of the NWS alerts feed may take."""


def alerts_reader(pool: Pool) -> Callable[[], bytes]:
    """Reads the NWS active alerts through the pool's pacer and robots store."""
    from snowlight.sources.nws.alerts import ACTIVE_URL  # noqa: PLC0415

    client = pool.client()

    def read() -> bytes:
        client.deadline = pool.monotonic() + ALERTS_DEADLINE
        client.stopped = None  # each read starts afresh, like a pool's source
        try:
            return client.fetch(ACTIVE_URL).body
        finally:
            client.deadline = None

    return read


def live_reads(  # pragma: no cover - builds the network pool for the real ingest
    registry: Registry, directory: LiveDirectory, cache_dir: Path, state_dir: Path
) -> LiveReads:
    """The real reader: the pool, and the cadence over the deployed directory's zones with
    the NWS alerts read every 5 minutes."""
    pool = live_pool(cache_dir, state_dir)
    zones = county_zones(
        (school.record.county_fips, school.zones[0] if school.zones else None)
        for school in directory.schools.values()
    )
    cadence = Cadence(
        registry.stations,
        zones,
        registry.poll_minutes,
        path=state_dir / "cadence.json",
        alerts=AlertWatch(alerts_reader(pool)),
    )
    return LiveReads(registry, directory, pool, cadence)


def keep_pass(cadence: Cadence, result: PassResult) -> None:
    """Keep each source's outcome of the pass in the cadence, and save it."""
    cadence.record(
        result.started, [(item.source_id, item.outcome, _wait(item)) for item in result.sources]
    )
    try:
        cadence.save()
    except OSError as error:
        LOG.error("cadence save: %s", type(error).__name__)


def _wait(read: SourceResult) -> float | None:
    """Seconds from the pass's start to the end of the wait a deferred source was asked for:
    when it answered plus its ``Retry-After``."""
    return read.finished + read.retry_after if read.retry_after is not None else None
