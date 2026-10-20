"""The reads a pass hands the ledger, from S4's station reader (until S8-B's pool replaces it).

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
id and the error's type only. The concurrent pool and the cadence (S8-B) replace it.
"""

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from typing import Final

from snowlight.live.ingest import SourceRead, station_zone
from snowlight.live.ledger import Outcome, seen_row
from snowlight.live.resolve import LiveDirectory
from snowlight.sources.stations.fetch import RunResult, skip_reason
from snowlight.sources.stations.model import HealthStatus
from snowlight.sources.stations.registry import Registry, Station

LOG: Final = logging.getLogger(__name__)
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
                    station, read_station(registry, station, client, now), directory
                ),
            )
            if read is not None:
                found.append(read)
            tick()
        return found

    return reads
