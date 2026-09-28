"""``snowlight stations fetch``: read every live source once, write raw rows and health.

For each station in the registry (in id order):

1. A station with no endpoint is skipped, and so is one whose platform's terms
   do not permit automated reading unless the operator's written permission or
   the project owner's decision to read it anyway is recorded (see
   :class:`~snowlight.sources.stations.registry.Terms`), and one whose terms
   have not been read; the reason is its health.
2. Otherwise its poll URL (the list its page loads, see the registry) is read
   through :class:`~snowlight.sources.stations.http.PoliteClient` (per-host pacing
   with any ``Crawl-delay`` as a floor, conditional requests, retries). robots.txt's
   verdict on every URL read is recorded in the source's health; a URL it
   disallows is read all the same, under the project owner's decision of
   2026-09-26 to read closings pages and files regardless.
3. The body goes to the platform's adapter. A body in no known shape is an
   error, never an empty list. A page that holds no list but names the file it
   loads (a frame, a script's data file) is followed to that file.
4. A list file whose ``Last-Modified`` is older than the start of the last winter
   (:func:`~snowlight.sources.stations.model.stale_before`) is ``stale``: its rows
   are not kept and the source does not count as working, since nothing has been
   written to it for a whole winter (a station that moved its list elsewhere
   leaves the old file behind).
5. A list typed by hand into a page (``Listing.typed``, see
   :mod:`snowlight.sources.stations.typed`) keeps its rows only when the page says
   it changed within :data:`TYPED_CURRENT` of the read. Typed text stays up long
   after the day it names: rows of a page last changed earlier are old notes, not
   kept (the read is ``empty``: the station's list holds nothing current). A page
   that says no time for itself keeps its rows only when its own words pin down a
   day near the read (:func:`snowlight.sources.stations.typed.names_day_near`);
   otherwise they cannot be told from old notes, so they are not kept either and
   the read is ``stale``.

Outputs, under ``pipeline/out/internal/stations/`` (internal, never published)::

    rows.jsonl       RawRow per line (see snowlight.sources.stations.model)
    reads.jsonl      ListingRead per source read
    health.json      {"generated_at", "stale_before", "sources": [SourceHealth...],
                      "totals": {...}}
    manifest.json    RunManifest: every body read (URL, time, status, SHA-256, size)
"""

from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from snowlight import __version__
from snowlight.output import JSONValue, write_bytes_atomic, write_json
from snowlight.schemas.internal import RunManifest, SourceSnapshot
from snowlight.sources.stations import typed
from snowlight.sources.stations.adapters import adapter_for
from snowlight.sources.stations.http import (
    Fetched,
    FetchError,
    PoliteClient,
    RobotsVerdict,
    iso_utc,
)
from snowlight.sources.stations.model import (
    HealthStatus,
    Listing,
    ListingRead,
    ListingState,
    RawRow,
    ReadMode,
    RobotsRecord,
    ShapeError,
    SourceHealth,
    ViaPage,
    count_only_reason,
    stale_before,
)
from snowlight.sources.stations.registry import (
    PIPELINE_ROOT,
    AccessPolicy,
    Registry,
    Station,
    StationStatus,
)

type Clock = Callable[[], datetime]

DEFAULT_OUT_DIR = PIPELINE_ROOT / "out" / "internal" / "stations"
DEFAULT_CACHE_DIR = PIPELINE_ROOT / ".cache" / "stations" / "live"
MAX_REASON = 500
MAX_FOLLOW_DEPTH = 3
"""How many files deep a page that loads its list from another file is followed."""
TYPED_CURRENT = timedelta(hours=36)
"""How long after a typed list's page last changed its rows are taken as current (step 5)."""
UNREAD_STATES = frozenset({ListingState.COUNT_ONLY, ListingState.DEFERRED})


@dataclass(slots=True)
class RunResult:
    """What one pass over the sources produced."""

    health: list[SourceHealth] = field(default_factory=list)
    reads: list[ListingRead] = field(default_factory=list)
    rows: list[RawRow] = field(default_factory=list)
    snapshots: list[SourceSnapshot] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    """Reads that show an adapter or the registry needs attention (archive parsing)."""
    set_aside: list[str] = field(default_factory=list)
    """Archive captures of a platform's shared paths (not lists): ``timestamp URL``."""


def _clip(text: str) -> str:
    return text if len(text) <= MAX_REASON else text[: MAX_REASON - 1] + "…"


def skip_reason(registry: Registry, station: Station) -> str | None:
    """Return why ``station`` must not be polled live, or ``None`` if it may be."""
    if station.status is StationStatus.NO_ENDPOINT:
        return "no known closings endpoint"
    terms = registry.platform_of(station).terms
    if terms.pollable:
        return None
    if terms.automated_access is AccessPolicy.FORBIDDEN:
        return (
            "terms forbid automated access; neither written permission nor the project "
            "owner's decision to read it is recorded"
        )
    return "terms not yet read; not polled until they are"


def listing_health(listing: Listing) -> tuple[HealthStatus, str | None]:
    """Return the health a parsed listing earns, and the reason when it is not ok or empty.

    A count-only or deferred page parsed cleanly but yields no rows, so it is
    recorded as an error that says so (never as an empty list).
    """
    if listing.state is ListingState.POPULATED:
        return HealthStatus.OK, None
    if listing.state is ListingState.EMPTY:
        return HealthStatus.EMPTY, None
    return HealthStatus.ERROR, count_only_reason(listing)


def typed_not_current(listing: Listing, read_at: datetime) -> bool:
    """Whether a list typed by hand holds rows its page does not show as current (step 5)."""
    if not listing.typed or not listing.rows:
        return False
    said = listing.list_updated_at
    if said is None:
        return not typed.names_day_near(listing, read_at)
    return said < read_at - TYPED_CURRENT


def stamp_rows(source_id: str, fetched_at: datetime, listing: Listing) -> list[RawRow]:
    """Turn an adapter's rows into raw rows for ``source_id`` read at ``fetched_at``."""
    return [
        RawRow.model_validate(
            {
                "source_id": source_id,
                "fetched_at": fetched_at,
                "raw_name": row.name,
                "raw_status": row.status,
                "raw_updated_text": row.updated_text,
                "raw_extra": row.extra,
            }
        )
        for row in listing.rows
    ]


@dataclass(frozen=True, slots=True)
class BodyStamp:
    """When and how one body was read: the source time, the download time, its digest."""

    fetched_at: datetime
    retrieved_at: datetime
    sha256: str
    size: int


def listing_read(
    source_id: str, mode: ReadMode, url: str, stamp: BodyStamp, listing: Listing
) -> ListingRead:
    """Describe one parsed body."""
    return ListingRead.model_validate(
        {
            "source_id": source_id,
            "mode": mode,
            "url": url,
            "fetched_at": stamp.fetched_at,
            "retrieved_at": stamp.retrieved_at,
            "sha256": stamp.sha256,
            "bytes": stamp.size,
            "variant": listing.variant,
            "state": listing.state,
            "rows": len(listing.rows),
            "declared_count": listing.declared_count,
            "skipped_rows": listing.skipped_rows,
        }
    )


def _health(station: Station, url: str | None, when: datetime, **fields: object) -> SourceHealth:
    return SourceHealth.model_validate(
        {"source_id": station.id, "url": url, "checked_at": when, "rows": 0, **fields}
    )


def follow_targets(page_url: str, listing: Listing, station: Station) -> list[str]:
    """Return the absolute URLs a count-only or deferred page loads its list from.

    Those the page names (``Listing.follows``), resolved against its URL; or, when
    it names none, the station's registered export (:attr:`Station.export
    <snowlight.sources.stations.registry.Station.export>`: a Gray Arc page loads
    the station's export without writing its URL in the page). Empty for any
    other listing.
    """
    if listing.state not in UNREAD_STATES:
        return []
    if listing.follows:
        return [urljoin(page_url, reference) for reference in listing.follows]
    export = station.export
    if export and _resource(export) != _resource(page_url):
        return [export]
    return []


def _resource(url: str) -> tuple[str, str]:
    """Return (host without www, path without a trailing slash): one file's identity."""
    parts = urlsplit(url)
    return (parts.hostname or "").lower().removeprefix("www."), parts.path.rstrip("/")


@dataclass(frozen=True, slots=True)
class _LiveRead:
    """One live body and what the adapter read from it."""

    url: str
    fetched: Fetched
    listing: Listing


def _read_live(
    station: Station,
    url: str,
    client: PoliteClient,
    adapter: Callable[[bytes], Listing],
    context: tuple[datetime, str | None, RunResult, tuple[RobotsRecord, ...]],
) -> _LiveRead | None:
    """Fetch and parse one URL; on failure record the health (and snapshot) and return None."""
    now, via_url, result, seen = context
    try:
        fetched = client.fetch(url)
    except FetchError as error:
        verdicts = (*seen, _robots_record(client.robots_verdict(url)))
        result.health.append(
            _health(
                station,
                url,
                now,
                status=HealthStatus.ERROR,
                http_status=error.status,
                reason=_clip(str(error)),
                via_url=via_url,
                robots=verdicts,
            )
        )
        result.snapshots.append(_snapshot(station, url, now, None, error))
        return None
    result.snapshots.append(_snapshot(station, url, fetched.fetched_at, fetched, None))
    try:
        listing = adapter(fetched.body)
    except ShapeError as error:
        result.health.append(
            _health(
                station,
                url,
                fetched.fetched_at,
                status=HealthStatus.ERROR,
                http_status=fetched.status,
                not_modified=fetched.not_modified,
                sha256=fetched.sha256,
                bytes=len(fetched.body),
                reason=_clip(f"unrecognized shape: {error}"),
                via_url=via_url,
                robots=(*seen, *_robots_records(fetched)),
            )
        )
        return None
    return _LiveRead(url, fetched, listing)


def _robots_record(verdict: RobotsVerdict) -> RobotsRecord:
    return RobotsRecord(
        url=verdict.url,
        state=verdict.state,
        allowed=verdict.allowed,
        rule=_clip(verdict.rule),
        crawl_delay=verdict.crawl_delay,
    )


def _robots_records(fetched: Fetched) -> tuple[RobotsRecord, ...]:
    return tuple(_robots_record(verdict) for verdict in fetched.robots)


def last_modified(fetched: Fetched) -> datetime | None:
    """Return the body's ``Last-Modified`` time (whole seconds, UTC), if the server sent one."""
    if not fetched.last_modified:
        return None
    try:
        when = parsedate_to_datetime(fetched.last_modified)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(UTC).replace(microsecond=0)


def via_pages(chain: Sequence[tuple[str, Fetched, Listing, str]], final: Listing) -> list[ViaPage]:
    """Describe the pages followed on the way to ``final``: (url, body, listing, followed URL).

    Each page's gap is the next body's read time minus its own; a page that gave a
    count is checked against the entries (rows and nameless rows) ``final`` holds.
    """
    pages: list[ViaPage] = []
    entries = len(final.rows) + final.skipped_rows
    for number, (url, fetched, listing, target) in enumerate(chain):
        after = chain[number + 1][1] if number + 1 < len(chain) else None
        declared = listing.declared_count
        pages.append(
            ViaPage(
                url=url,
                fetched_at=fetched.fetched_at,
                sha256=fetched.sha256,
                variant=listing.variant,
                state=listing.state,
                declared_count=declared,
                count_at=listing.declared_at,
                follows=target,
                gap_seconds=int((after.fetched_at - fetched.fetched_at).total_seconds())
                if after is not None
                else 0,
                count_matches=None if declared is None else declared == entries,
            )
        )
    return pages


def read_station(
    registry: Registry, station: Station, client: PoliteClient, now: datetime
) -> RunResult:
    """Read one station live (or record why not) and return what came of it.

    A page that holds no list and names the file it loads (or whose station has an
    export it loads, :attr:`Station.export`) is followed to that file, up to
    :data:`MAX_FOLLOW_DEPTH` files deep, through the same polite client
    (robots.txt, pacing, conditional requests); the read describes the list file
    and names the pages in ``via``.
    robots.txt's verdicts on every URL requested go into the health record. A list
    file last modified before the last winter began is ``stale`` (see the module
    docstring): its rows are not kept.
    """
    result = RunResult()
    url = station.poll_url
    reason = skip_reason(registry, station)
    if reason is not None or url is None:
        result.health.append(
            _health(station, url, now, status=HealthStatus.SKIPPED, reason=reason or "no URL")
        )
        return result
    adapter = adapter_for(registry.platform_of(station).adapter)
    read = _read_live(station, url, client, adapter, (now, None, result, ()))
    chain: list[tuple[str, Fetched, Listing, str]] = []
    seen: tuple[RobotsRecord, ...] = ()
    while read is not None:
        seen = (*seen, *_robots_records(read.fetched))
        targets = follow_targets(read.url, read.listing, station)
        if not targets or len(chain) >= MAX_FOLLOW_DEPTH:
            break
        chain.append((read.url, read.fetched, read.listing, targets[0]))
        followed = _read_live(station, targets[0], client, adapter, (now, url, result, seen))
        if followed is None:
            return result
        read = followed
    if read is None:
        return result
    listing, fetched = read.listing, read.fetched
    via = tuple(via_pages(chain, listing))
    modified = last_modified(fetched)
    threshold = stale_before(now)
    said = listing.list_updated_at
    stale = (modified is not None and modified < threshold) or (
        said is not None and said < threshold
    )
    typed_old = typed_not_current(listing, fetched.fetched_at)
    rows = [] if stale or typed_old else stamp_rows(station.id, fetched.fetched_at, listing)
    result.rows.extend(rows)
    described = listing_read(
        station.id,
        ReadMode.LIVE,
        read.url,
        BodyStamp(fetched.fetched_at, fetched.fetched_at, fetched.sha256, len(fetched.body)),
        listing,
    ).model_copy(update={"via": via, "last_modified": modified})
    result.reads.append(described)
    status, why = listing_health(listing)
    if stale and modified is not None and modified < threshold:
        status = HealthStatus.STALE
        why = _clip(
            f"the list file was last modified {iso_utc(modified)}, before the last winter "
            f"began ({iso_utc(threshold)}); nothing has been written to it since, so its "
            f"{len(listing.rows)} rows are not kept ({listing.variant}, {listing.state.value})"
        )
    elif stale and said is not None:
        status = HealthStatus.STALE
        why = _clip(
            f"the list says it was last updated {iso_utc(said)}, before the last winter "
            f"began ({iso_utc(threshold)}); it has not changed since, so its "
            f"{len(listing.rows)} rows are not kept ({listing.variant}, {listing.state.value})"
        )
    elif typed_old and said is None:
        status = HealthStatus.STALE
        why = _clip(
            f"a list typed by hand into the page, which says no time for it and names no day "
            f"near the read: its {len(listing.rows)} rows cannot be told from old notes, so they "
            f"are not kept ({listing.variant})"
        )
    elif typed_old and said is not None:
        status = HealthStatus.EMPTY
        why = _clip(
            f"a list typed by hand into the page, last changed {iso_utc(said)}, more than "
            f"{TYPED_CURRENT.total_seconds() / 3600:.0f} hours before the read: its "
            f"{len(listing.rows)} rows are old notes, not kept ({listing.variant})"
        )
    result.health.append(
        _health(
            station,
            read.url,
            fetched.fetched_at,
            status=status,
            reason=why,
            rows=len(rows),
            http_status=fetched.status,
            not_modified=fetched.not_modified,
            sha256=fetched.sha256,
            bytes=len(fetched.body),
            variant=listing.variant,
            via_url=url if via else None,
            last_modified=modified,
            robots=seen,
        )
    )
    return result


def _snapshot(
    station: Station,
    url: str,
    when: datetime,
    fetched: Fetched | None,
    error: FetchError | None,
) -> SourceSnapshot:
    return SourceSnapshot.model_validate(
        {
            "source_id": station.id,
            "url": url,
            "fetched_at": when,
            "http_status": fetched.status if fetched else (error.status if error else None),
            "sha256": fetched.sha256 if fetched else None,
            "bytes": len(fetched.body) if fetched else None,
            "error": None if fetched else _clip(str(error)),
        }
    )


def run(
    registry: Registry,
    client: PoliteClient,
    *,
    clock: Clock,
    only: Iterable[str] | None = None,
) -> RunResult:
    """Read every station (or only the ids in ``only``) once."""
    wanted = set(only) if only is not None else None
    if wanted is not None:
        unknown = wanted - set(registry.stations)
        if unknown:
            raise KeyError(f"unknown station ids: {sorted(unknown)}")
    total = RunResult()
    for station in sorted(registry.stations.values(), key=lambda s: s.id):
        if wanted is not None and station.id not in wanted:
            continue
        part = read_station(registry, station, client, clock())
        total.health.extend(part.health)
        total.reads.extend(part.reads)
        total.rows.extend(part.rows)
        total.snapshots.extend(part.snapshots)
    return total


def totals(health: Sequence[SourceHealth]) -> dict[str, int]:
    """Count sources by health status, rows, and sources read although robots.txt disallows."""
    counts = Counter(entry.status.value for entry in health)
    out = {status.value: counts.get(status.value, 0) for status in HealthStatus}
    out["rows"] = sum(entry.rows for entry in health)
    out["sources"] = len(health)
    out["robots_disallowed"] = sum(
        any(not verdict.allowed for verdict in entry.robots) for entry in health
    )
    return out


def _jsonl(records: Iterable[RawRow | ListingRead]) -> bytes:
    return b"".join(record.model_dump_json().encode("utf-8") + b"\n" for record in records)


def write_outputs(result: RunResult, out_dir: Path, generated_at: datetime) -> dict[str, Path]:
    """Write rows, reads, health and the run manifest; return the paths written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "rows": out_dir / "rows.jsonl",
        "reads": out_dir / "reads.jsonl",
        "health": out_dir / "health.json",
        "manifest": out_dir / "manifest.json",
    }
    write_bytes_atomic(paths["rows"], _jsonl(result.rows))
    write_bytes_atomic(paths["reads"], _jsonl(result.reads))
    health: JSONValue = {
        "generated_at": iso_utc(generated_at),
        "stale_before": iso_utc(stale_before(generated_at)),
        "sources": [entry.model_dump(mode="json") for entry in result.health],
        "totals": dict(totals(result.health)),
    }
    write_json(paths["health"], health)
    manifest = RunManifest.model_validate(
        {
            "generated_at": generated_at,
            "pipeline_version": __version__,
            "snapshots": tuple(result.snapshots),
            "outputs": (),
        }
    )
    write_bytes_atomic(paths["manifest"], manifest.model_dump_json(indent=2).encode("utf-8"))
    return paths
