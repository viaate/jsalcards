"""Archived closings pages: Wayback listings, snapshot plans, and parsing downloaded captures.

The Wayback Machine is read only from GitHub's runners (see
``.github/workflows/archive-captures.yml``); this module works on what that
workflow uploads:

* CDX listings: JSON arrays whose first row names the fields
  ``timestamp, original, statuscode, mimetype, length, digest``.
* Snapshots: ``snapshots/manifest.jsonl`` (one :class:`SnapshotRecord` per
  capture asked for) beside the raw bodies it names. A body fetched with the
  ``id_`` flag is the bytes the station sent when the archive captured the page.

:func:`plan_snapshots` picks captures to download from listings (storm days
first, when the planner is given them: see :mod:`snowlight.sources.stations.storms`),
and :func:`parse_snapshots` runs each downloaded body through its station's adapter.
An archived row's ``fetched_at`` is the capture time (when the station served
the page), and ``retrieved_at`` on its read is when the runner downloaded it.

Following pages to their lists: a page that holds no list (a count-only or
deferred listing) names the file it loads (``Listing.follows``) or, when it names
none, loads its station's registered export (``Station.export``: the
``export_url``, else the ``data_url``). Such a page is read through the
downloaded capture of that file nearest in time, if one was captured within
:data:`FOLLOW_WINDOW` of the page; the file may itself be such a page (a frame
that loads a data file), up to :data:`MAX_FOLLOW_DEPTH` files deep. The read then
carries the list file's own URL, capture time, digest and rows, and names the
pages on the way in ``via`` (with the time between each page and the file it
loaded, and, for a page that gave a count, whether the count matches the list).
Each capture is read once: a file capture used as one page's list is not read
again on its own, and pages and files pair one to one, closest in time first.
A page with no such capture stays an error that names the file and the nearest
capture of it, and a file capture no page pairs with is read on its own.
"""

import hashlib
import json
import re
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Annotated
from urllib.parse import parse_qsl, urlsplit

from pydantic import Field, StringConstraints, ValidationError

from snowlight.schemas.base import InternalModel
from snowlight.schemas.internal import Sha256, SourceSnapshot
from snowlight.sources.stations.adapters import adapter_for
from snowlight.sources.stations.fetch import (
    MAX_FOLLOW_DEPTH,
    UNREAD_STATES,
    BodyStamp,
    RunResult,
    follow_targets,
    listing_health,
    listing_read,
    stamp_rows,
)
from snowlight.sources.stations.http import iso_utc
from snowlight.sources.stations.model import (
    HealthStatus,
    Listing,
    ListingRead,
    ListingState,
    ReadMode,
    ShapeError,
    SourceHealth,
    ViaPage,
    count_only_reason,
)
from snowlight.sources.stations.registry import Registry, Station
from snowlight.sources.stations.storms import StormDays, school_day

WAYBACK_STAMP = re.compile(r"^[0-9]{14}$")
CDX_FIELDS = ("timestamp", "original", "statuscode", "mimetype", "length", "digest")
WINTER_MONTHS = frozenset({11, 12, 1, 2, 3})
FOLLOW_WINDOW = timedelta(hours=6)
"""How far apart a page's capture and a capture of the file it loads may be."""
COUNT_CHECK_WINDOW = timedelta(minutes=2)
"""A count that differs from a list captured this close to when the count was made is a failure.

The count's time is the one the page gives for it (``Listing.declared_at``, a Gray
Arc page's cache entry time, often a minute or two before the page was served),
else the page's capture time. A list captured further from the count may
legitimately differ (on a storm morning closings arrive by the minute): the
difference is recorded (``ViaPage.count_matches``, ``count_at``) but not failed.
"""


class ArchiveError(ValueError):
    """An artifact file does not have the shape the workflow writes."""


def capture_time(stamp: str) -> datetime:
    """Return the UTC instant of a 14-digit Wayback timestamp."""
    if not WAYBACK_STAMP.match(stamp):
        raise ArchiveError(f"not a 14-digit Wayback timestamp: {stamp!r}")
    return datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=UTC)


KEY_QUERY = frozenset({"regionid", "region", "media_id"})
"""Query parameters that name a different list at one address, kept in :func:`url_key`.

FlashAlert serves every region's report from one script, told apart only by its
``RegionID`` (``cwc-closures.php?RegionID=1``); News 12 serves each region's list
from one page, told apart by ``region`` (``closings.jsp?region=LI``); WeatherThreat
serves each outlet's list from one script, told apart by ``media_id``
(``viewClosings.php?media_id=ntv``). Every other query (cache-busting counters,
``arc-site``, WeatherThreat's ``t`` and ``server``) is dropped.
"""


def url_key(url: str) -> str:
    """Return a key two spellings of one page share: host without www, path, no query.

    The one exception is a parameter in :data:`KEY_QUERY`, which names the list itself:
    it is kept, lower-cased by name (``?regionid=1``).
    """
    parts = urlsplit(url if "://" in url else f"https://{url}")
    host = (parts.hostname or "").lower().removeprefix("www.")
    path = parts.path.rstrip("/") or "/"
    kept = sorted(
        (name.lower(), value)
        for name, value in parse_qsl(parts.query, keep_blank_values=True)
        if name.lower() in KEY_QUERY
    )
    query = "&".join(f"{name}={value}" for name, value in kept)
    return f"{host}{path}?{query}" if query else f"{host}{path}"


class SnapshotRecord(InternalModel):
    """One line of ``snapshots/manifest.jsonl``."""

    timestamp: Annotated[str, StringConstraints(pattern=r"^[0-9]{14}$")]
    url: str
    requested: str
    hops: tuple[dict[str, str | int], ...] = ()
    retrieved_at: str | None = None
    final_url: str | None = None
    final_timestamp: str | None = None
    final_original: str | None = None
    http_status: int | None = None
    content_type: str | None = None
    content_encoding: str | None = None
    memento_datetime: str | None = None
    file: str | None = None
    bytes: Annotated[int, Field(ge=0)] | None = None
    sha256: Sha256 | None = None
    error: str | None = None


def read_manifest(path: Path) -> list[SnapshotRecord]:
    """Read a snapshot manifest (JSON Lines)."""
    records = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(SnapshotRecord.model_validate_json(line))
        except ValidationError as error:
            raise ArchiveError(f"{path}:{number}: {error}") from error
    return records


def find_manifests(root: Path) -> list[Path]:
    """Return every ``snapshots/manifest.jsonl`` under ``root``."""
    return sorted(root.rglob("snapshots/manifest.jsonl"))


@dataclass(frozen=True, slots=True)
class Capture:
    """One row of a CDX listing."""

    timestamp: str
    original: str
    status: str
    mimetype: str
    length: int | None
    digest: str

    @property
    def when(self) -> datetime:
        """The capture instant."""
        return capture_time(self.timestamp)


def read_cdx(path: Path) -> list[Capture]:
    """Read one CDX listing file written by the workflow."""
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "[]")
    except ValueError as error:
        raise ArchiveError(f"{path.name}: not JSON: {error}") from error
    if not isinstance(data, list):
        raise ArchiveError(f"{path.name}: not a JSON list")
    if not data:
        return []
    header = data[0]
    if not isinstance(header, list) or tuple(header) != CDX_FIELDS:
        raise ArchiveError(f"{path.name}: unexpected CDX header {header!r}")
    captures = []
    for row in data[1:]:
        if not isinstance(row, list) or len(row) != len(CDX_FIELDS):
            raise ArchiveError(f"{path.name}: malformed CDX row {row!r}")
        text = [str(cell) for cell in row]
        length = int(text[4]) if text[4].isdigit() else None
        captures.append(Capture(text[0], text[1], text[2], text[3], length, text[5]))
    return captures


def shared_keys(registry: Registry) -> tuple[str, ...]:
    """Return the URL keys of every platform's shared paths (see ``SharedPath``)."""
    return tuple(
        sorted({url_key(item.url) for p in registry.platforms.values() for item in p.shared_paths})
    )


def is_shared(url: str, keys: Sequence[str]) -> bool:
    """Whether ``url`` lies under one of the shared paths ``keys``."""
    key = url_key(url)
    return any(key == shared or key.startswith(shared.rstrip("/") + "/") for shared in keys)


def station_index(registry: Registry) -> dict[str, Station]:
    """Map the URL key of every URL a station uses to that station.

    A station's own addresses (its page and archive URLs) come first: a page may
    load another station's file as its ``data_url`` (KJCT's page loads KKCO's
    export), and that file's captures belong to the station it is kept for.
    """
    index: dict[str, Station] = {}
    stations = list(registry.stations.values())
    for station in stations:
        for url in (station.page_url, *station.archive_urls):
            if url:
                index.setdefault(url_key(url), station)
    for station in stations:
        if station.data_url:
            index.setdefault(url_key(station.data_url), station)
    return index


def winter_season(moment: datetime) -> int | None:
    """Return the year a winter season starts in (Nov 2024 to Mar 2025 is 2024)."""
    if moment.month not in WINTER_MONTHS:
        return None
    return moment.year if moment.month >= 11 else moment.year - 1  # noqa: PLR2004


def downloaded(root: Path) -> set[tuple[str, str]]:
    """Return (capture timestamp, URL key) for every capture already downloaded under ``root``."""
    done: set[tuple[str, str]] = set()
    for manifest in find_manifests(root):
        for record in read_manifest(manifest):
            if record.file is not None:
                original = record.final_original or record.url
                done.add((record.final_timestamp or record.timestamp, url_key(original)))
    return done


@dataclass(frozen=True, slots=True)
class PlanOptions:
    """What :func:`plan_snapshots` picks."""

    seasons: frozenset[int] | None = None
    """Winter seasons to plan (start years); all when ``None``."""
    per_season: int = 1
    since: date | None = None
    skip: frozenset[tuple[str, str]] = frozenset()
    """``(timestamp, url_key)`` of captures already downloaded (see :func:`downloaded`)."""
    eras_before: int | None = None
    storms: StormDays | None = None
    """Each station's storm days; when given, captures on storm days are picked first."""


def _rank(station_id: str, storms: StormDays | None) -> Callable[[Capture], tuple[float, int, str]]:
    """Sort key: the stormiest school day first, then the largest capture, then the earliest."""

    def key(capture: Capture) -> tuple[float, int, str]:
        score = storms.score(station_id, capture.when) if storms is not None else 0.0
        return (-score, -_length(capture), capture.timestamp)

    return key


def _stormy(station_id: str, storms: StormDays | None, capture: Capture) -> bool:
    return storms is not None and storms.score(station_id, capture.when) > 0


def plan_snapshots(
    captures_by_station: Mapping[str, Sequence[Capture]], options: PlanOptions | None = None
) -> list[dict[str, str]]:
    """Pick storm-day captures to download, ``per_season`` per station and winter.

    With ``options.storms``, the captures about the school days on which winter
    warnings covered most of the station's market come first (see
    :mod:`snowlight.sources.stations.storms`), the larger capture first on a tie.
    Without storm days, or in a winter none of whose captures falls on a storm
    day, a closings page's size stands in for its list: the largest successful
    captures larger than the season's median are chosen (at least one per
    season, so each era's page format is sampled even in a quiet winter).
    A season from which a capture was already downloaded (``options.skip``) is
    left out. With ``options.eras_before``, the largest winter capture (or the
    largest capture) of each calendar year before that year is added, to sample
    older page formats.
    """
    options = options or PlanOptions()
    wanted, per_season, since = options.seasons, options.per_season, options.since
    done, eras_before = options.skip, options.eras_before
    plan: list[dict[str, str]] = []
    for station_id in sorted(captures_by_station):
        by_season: dict[int, list[Capture]] = defaultdict(list)
        by_year: dict[int, list[Capture]] = defaultdict(list)
        read_seasons = {
            winter_season(c.when)
            for c in captures_by_station[station_id]
            if (c.timestamp, url_key(c.original)) in done
        }
        for capture in captures_by_station[station_id]:
            if capture.status != "200" or capture.length is None:
                continue
            if eras_before is not None and capture.when.year < eras_before:
                by_year[capture.when.year].append(capture)
            if since is not None and capture.when.date() < since:
                continue
            season = winter_season(capture.when)
            if season is None or (wanted is not None and season not in wanted):
                continue
            if season in read_seasons:
                continue
            by_season[season].append(capture)
        rank = _rank(station_id, options.storms)
        for season in sorted(by_season):
            captures = by_season[season]
            stormy = sorted(
                (c for c in captures if _stormy(station_id, options.storms, c)), key=rank
            )
            middle = median(c.length or 0 for c in captures)
            big = sorted(
                (c for c in captures if (c.length or 0) > middle),
                key=lambda c: (-(c.length or 0), c.timestamp),
            )
            chosen = (
                stormy[:per_season]
                or big[:per_season]
                or sorted(captures, key=lambda c: -(c.length or 0))[:1]
            )
            plan.extend({"timestamp": c.timestamp, "url": c.original} for c in chosen)
        for year in sorted(by_year):
            group = by_year[year]
            winter = [c for c in group if winter_season(c.when) is not None] or group
            best = max(winter, key=lambda c: (c.length or 0, c.timestamp))
            item = {"timestamp": best.timestamp, "url": best.original}
            if (best.timestamp, url_key(best.original)) not in done and item not in plan:
                plan.append(item)
    return plan


def _health(station_id: str, url: str | None, when: datetime, **fields: object) -> SourceHealth:
    return SourceHealth.model_validate(
        {"source_id": station_id, "url": url, "checked_at": when, "rows": 0, **fields}
    )


def _snapshot(source_id: str, record: SnapshotRecord, when: datetime) -> SourceSnapshot:
    """Record the archive download of one capture for the run manifest."""
    complete = record.sha256 is not None and record.bytes is not None
    return SourceSnapshot.model_validate(
        {
            "source_id": source_id,
            "url": record.final_url or record.requested,
            "fetched_at": record.retrieved_at or iso_utc(when),
            "http_status": record.http_status,
            "sha256": record.sha256 if complete else None,
            "bytes": record.bytes if complete else None,
            "error": None if complete else (record.error or "no body recorded")[:500],
        }
    )


@dataclass(frozen=True, slots=True)
class _Parsed:
    """What a station's adapter read from one downloaded capture."""

    station: Station
    listing: Listing
    sha256: str
    size: int


@dataclass(slots=True)
class _Capture:
    """One downloaded (or failed) capture and what its station's adapter read from it."""

    record: SnapshotRecord
    station: Station | None
    original: str
    when: datetime
    retrieved: datetime
    parsed: _Parsed | None = None
    health: SourceHealth | None = None
    """Set when the capture could not be parsed (its final health, an error)."""
    failure: str | None = None


def _load_capture(
    registry: Registry, index: dict[str, Station], base: Path, record: SnapshotRecord
) -> tuple[_Capture, SourceSnapshot | None]:
    """Parse one manifest record's body, or record why it could not be read."""
    original = record.final_original or record.url
    stamp = record.final_timestamp or record.timestamp
    when = capture_time(stamp if WAYBACK_STAMP.match(stamp) else record.timestamp)
    retrieved = (
        datetime.strptime(record.retrieved_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        if record.retrieved_at
        else when
    )
    station = index.get(url_key(original)) or index.get(url_key(record.url))
    capture = _Capture(record, station, original, when, retrieved)
    if station is None:
        reason = f"no station uses {original}"
        if record.file is None:
            reason += f"; capture not downloaded: {record.error or 'no body'}"
        capture.health = _health(
            "unregistered", None, when, status=HealthStatus.ERROR, reason=reason[:500]
        )
        return capture, None
    snapshot = _snapshot(station.id, record, when)
    common: dict[str, object] = {"http_status": record.http_status}
    if record.file is None or record.sha256 is None:
        reason = f"capture not downloaded: {record.error or 'no body'}"
        capture.health = _health(
            station.id, original, when, status=HealthStatus.ERROR, reason=reason[:500], **common
        )
        return capture, snapshot
    body = (base / record.file).read_bytes()
    if hashlib.sha256(body).hexdigest() != record.sha256:
        reason = f"{record.file}: the body's SHA-256 differs from the manifest's"
        capture.failure = reason
        capture.health = _health(
            station.id, original, when, status=HealthStatus.ERROR, reason=reason[:500], **common
        )
        return capture, snapshot
    common.update(sha256=record.sha256, bytes=len(body))
    try:
        listing = adapter_for(registry.platform_of(station).adapter)(body)
        capture.parsed = _Parsed(station, listing, record.sha256, len(body))
    except ShapeError as error:
        reason = f"unrecognized shape: {error}"
        capture.failure = f"{station.id} {stamp} {original}: {reason}"
        capture.health = _health(
            station.id, original, when, status=HealthStatus.ERROR, reason=reason[:500], **common
        )
    return capture, snapshot


@dataclass(slots=True)
class _Pairing:
    """Which capture each page capture is read through, closest in time first."""

    next_of: dict[int, tuple[int, str]] = field(default_factory=dict)
    """Page capture index to (file capture index, the absolute URL followed)."""
    used: set[int] = field(default_factory=set)
    """File captures read as some page's list."""


def _pair(captures: Sequence[_Capture]) -> _Pairing:
    """Pair each count-only or deferred page with the nearest capture of the file it loads."""
    by_key: dict[str, list[int]] = defaultdict(list)
    for number, capture in enumerate(captures):
        if capture.parsed is not None:
            by_key[url_key(capture.original)].append(number)
    edges: list[tuple[timedelta, datetime, int, int, str]] = []
    for number, capture in enumerate(captures):
        parsed = capture.parsed
        if parsed is None:
            continue
        for target in follow_targets(capture.original, parsed.listing, parsed.station):
            for other in by_key.get(url_key(target), []):
                candidate = captures[other].parsed
                if other == number or candidate is None or candidate.station is not parsed.station:
                    continue
                gap = abs(captures[other].when - capture.when)
                if gap <= FOLLOW_WINDOW:
                    edges.append((gap, capture.when, number, other, target))
    pairing = _Pairing()
    for _gap, _when, page, other, target in sorted(edges):
        if page in pairing.next_of or other in pairing.used or other == page:
            continue
        pairing.next_of[page] = (other, target)
        pairing.used.add(other)
    return pairing


def _listings(root: Path, wanted: Callable[[str], bool]) -> dict[str, list[Capture]]:
    """Return the replayable captures the CDX listings under ``root`` hold, by URL key.

    Listings are the ``*.json`` files in the workflow's ``cdx-*`` artifacts. Only
    captures the archive can replay count: HTTP 200 answers and revisits (``-``,
    an unchanged copy of an earlier 200). Only URL keys ``wanted`` accepts are kept.
    """
    found: dict[str, dict[tuple[str, str], Capture]] = defaultdict(dict)
    for path in sorted(root.rglob("*.json")):
        folders = path.relative_to(root).parts[:-1]
        if not any(part.startswith("cdx") for part in folders):
            continue
        for capture in read_cdx(path):
            if capture.status not in {"200", "-"}:
                continue
            key = url_key(capture.original)
            if wanted(key):
                found[key][(capture.timestamp, capture.original)] = capture
    return {key: sorted(caps.values(), key=lambda c: c.timestamp) for key, caps in found.items()}


def listed_captures(root: Path, keys: set[str]) -> dict[str, list[datetime]]:
    """Return, for each URL key in ``keys``, the capture times the CDX listings under ``root`` hold.

    See :func:`_listings` for which captures count.
    """
    if not keys:
        return {}
    found = _listings(root, keys.__contains__)
    return {key: sorted({c.when for c in caps}) for key, caps in found.items()}


def _hours(delta: timedelta) -> str:
    return f"{delta.total_seconds() / 3600:+.1f} h"


def _nearest(
    captures: Sequence[_Capture],
    capture: _Capture,
    parsed: _Parsed,
    listed: Mapping[str, Sequence[datetime]],
) -> str:
    """Say why an unpaired page was not read through its list file.

    Names the nearest downloaded capture of the file, and what the archive's CDX
    listings (when the artifacts hold any for the file) show near the page: either
    that no capture of the file lies within :data:`FOLLOW_WINDOW` of it (the list
    the page showed is not in the archive), or the capture that does and has not
    been downloaded yet.
    """
    targets = follow_targets(capture.original, parsed.listing, parsed.station)
    if not targets:
        return "; it names no file to follow and its station has no export"
    keys = {url_key(target) for target in targets}
    near = [
        other for other in captures if other.parsed is not None and url_key(other.original) in keys
    ]
    window = f"{FOLLOW_WINDOW.total_seconds() / 3600:.0f} h"
    if near:
        best = min(near, key=lambda other: abs(other.when - capture.when))
        text = (
            f"; the nearest downloaded capture of {targets[0]} is "
            f"{_hours(best.when - capture.when)} away ({iso_utc(best.when)})"
        )
    else:
        text = f"; no capture of {targets[0]} was downloaded"
    times = sorted(when for key in keys for when in listed.get(key, ()))
    if not times:
        return text + "; no CDX listing in the artifacts names a capture of it"
    closest = min(times, key=lambda when: abs(when - capture.when))
    if abs(closest - capture.when) <= FOLLOW_WINDOW:
        return (
            f"{text}; the archive lists a capture of it {_hours(closest - capture.when)} "
            f"away ({iso_utc(closest)}), within {window}, not yet downloaded"
        )
    return (
        f"{text}; the archive lists {len(times)} captures of it, none within {window} of "
        f"this page (nearest {_hours(closest - capture.when)}, {iso_utc(closest)})"
    )


def _entries(listing: Listing) -> int:
    return len(listing.rows) + listing.skipped_rows


def _chain(pairing: _Pairing, start: int) -> tuple[list[tuple[int, str]], int]:
    """Return the (page, followed URL) hops from ``start`` and the capture finally read."""
    hops: list[tuple[int, str]] = []
    current = start
    while current in pairing.next_of and len(hops) < MAX_FOLLOW_DEPTH:
        following, target = pairing.next_of[current]
        hops.append((current, target))
        current = following
    return hops, current


def _followed(
    captures: Sequence[_Capture], pairing: _Pairing, start: int, result: RunResult
) -> None:
    """Emit the read of a page followed to its list (rows, read with ``via``, health)."""
    hops, last = _chain(pairing, start)
    final = captures[last]
    done = final.parsed
    if done is None:  # pairing only joins parsed captures
        raise ArchiveError(f"{final.original}: a followed capture was not parsed")
    via: list[ViaPage] = []
    for page_number, target in hops:
        page, after = captures[page_number], captures[pairing.next_of[page_number][0]]
        if page.parsed is None:
            raise ArchiveError(f"{page.original}: a followed capture was not parsed")
        declared = page.parsed.listing.declared_count
        count_at = page.parsed.listing.declared_at
        matches = None if declared is None else declared == _entries(done.listing)
        via.append(
            ViaPage(
                url=page.original,
                fetched_at=page.when,
                sha256=page.parsed.sha256,
                variant=page.parsed.listing.variant,
                state=page.parsed.listing.state,
                declared_count=declared,
                count_at=count_at,
                follows=target,
                gap_seconds=int((after.when - page.when).total_seconds()),
                count_matches=matches,
            )
        )
        counted = count_at or page.when
        if matches is False and abs(final.when - counted) <= COUNT_CHECK_WINDOW:
            result.failures.append(
                f"{done.station.id} {iso_utc(page.when)} {page.original}: the page counts "
                f"{declared} (as of {iso_utc(counted)}) but {target} captured "
                f"{iso_utc(final.when)} lists {_entries(done.listing)}"
            )
    _emit(final, done, result, _Route(tuple(via), captures[start].original))


@dataclass(frozen=True, slots=True)
class _Route:
    """How a capture was reached: the pages on the way, or why it stands alone unread."""

    via: tuple[ViaPage, ...] = ()
    via_url: str | None = None
    reason: str | None = None


def _emit(capture: _Capture, parsed: _Parsed, result: RunResult, route: _Route) -> None:
    """Add one parsed capture's rows, read and health to ``result``."""
    via, via_url, reason = route.via, route.via_url, route.reason
    listing, station = parsed.listing, parsed.station
    result.rows.extend(stamp_rows(station.id, capture.when, listing))
    read = listing_read(
        station.id,
        ReadMode.ARCHIVE,
        capture.original,
        BodyStamp(capture.when, capture.retrieved, parsed.sha256, parsed.size),
        listing,
    )
    result.reads.append(read.model_copy(update={"via": via}) if via else read)
    status, why = listing_health(listing)
    if reason is not None:
        why = reason
    elif why is not None and via_url is not None:
        why = f"{why}; reached from {via_url}"
    result.health.append(
        _health(
            station.id,
            capture.original,
            capture.when,
            status=status,
            reason=why[:500] if why else None,
            rows=len(listing.rows),
            variant=listing.variant,
            http_status=capture.record.http_status,
            sha256=parsed.sha256,
            bytes=parsed.size,
            via_url=via_url,
        )
    )


def _alone(
    captures: Sequence[_Capture],
    number: int,
    result: RunResult,
    listed: Mapping[str, Sequence[datetime]],
) -> None:
    """Emit the read of a capture not followed from (or to) any other."""
    capture = captures[number]
    if capture.parsed is None:
        if capture.health is not None:
            result.health.append(capture.health)
        if capture.failure is not None:
            result.failures.append(capture.failure)
        return
    listing = capture.parsed.listing
    reason = None
    if listing.state in UNREAD_STATES:
        reason = count_only_reason(listing) + _nearest(captures, capture, capture.parsed, listed)
    _emit(capture, capture.parsed, result, _Route(reason=reason))


def _loaded_keys(station: Station) -> set[str]:
    """URL keys of the files a station's pages load: its list files and its export."""
    keys = {url_key(item.url) for item in station.list_files}
    for url in (station.data_url, station.export_url):
        if url:
            keys.add(url_key(url))
    return keys


def _page_keys(station: Station) -> set[str]:
    """URL keys of a station's closings pages: its page and archive URLs, less the files."""
    urls = [station.page_url, *station.archive_urls]
    keys = {url_key(url) for url in urls if url and "amazonaws.com" not in url}
    return keys - _loaded_keys(station)


@dataclass(frozen=True, slots=True)
class _Timeline:
    """Captures in time order, searchable by instant."""

    captures: tuple[Capture, ...]
    times: tuple[datetime, ...]

    @classmethod
    def of(cls, captures: Iterable[Capture]) -> "_Timeline":
        ordered = tuple(sorted(captures, key=lambda c: (c.timestamp, c.original)))
        return cls(ordered, tuple(c.when for c in ordered))

    def closest(self, when: datetime, window: timedelta) -> Capture | None:
        """Return the capture nearest ``when`` within ``window`` (the earlier on a tie)."""
        middle = bisect_left(self.times, when)
        best: Capture | None = None
        for number in (middle - 1, middle):
            if 0 <= number < len(self.captures):
                gap = abs(self.times[number] - when)
                if gap <= window and (best is None or gap < abs(best.when - when)):
                    best = self.captures[number]
        return best


def _length(capture: Capture) -> int:
    return capture.length or 0


OLDER_ERAS_BEFORE = 2022
"""Export pairs from before this year are the GSync-embed and script eras (see plan_follow)."""
UNREAD_FILE_PICKS = 3
"""How many winter list-file captures to ask for a station with no populated read."""
UNREAD_STORM_PICKS = 8
"""With storm days: how many storm-day captures (list files and pages) to ask for such a station."""
_TRANSIENT = re.compile(r"URLError|TimeoutError|ConnectionError|OSError|HTTP (?:429|5[0-9]{2})")


def _populated(captures: Sequence[_Capture]) -> set[str]:
    """Stations with a downloaded capture that lists at least one organization."""
    return {
        c.parsed.station.id
        for c in captures
        if c.parsed is not None and c.parsed.listing.state is ListingState.POPULATED
    }


def _followed_files(captures: Sequence[_Capture], pairing: _Pairing) -> set[tuple[str, str]]:
    """(station, file URL key) of every populated file a page was read through."""
    return {
        (c.parsed.station.id, url_key(c.original))
        for number, c in enumerate(captures)
        if number in pairing.used
        and c.parsed is not None
        and c.parsed.listing.state is ListingState.POPULATED
    }


def retry_requests(root: Path) -> list[tuple[str, str]]:
    """Return (timestamp, URL) of each request that failed transiently and was never served.

    Transient: a network or TLS error, a timeout, or an HTTP 429 or 5xx answer
    after the workflow's own retries.
    """
    served: set[tuple[str, str]] = set()
    failed: dict[tuple[str, str], None] = {}
    for path in find_manifests(root):
        for record in read_manifest(path):
            request = (record.timestamp, record.url)
            if record.sha256 is not None:
                served.add(request)
            elif record.error and _TRANSIENT.search(record.error):
                failed[request] = None
    return [request for request in failed if request not in served]


@dataclass(slots=True)
class _Plan:
    """Requests in priority order, each at most once, none already downloaded."""

    done: set[tuple[str, str]]
    items: list[dict[str, str]] = field(default_factory=list)

    def add(self, timestamp: str, url: str) -> None:
        item = {"timestamp": timestamp, "url": url}
        if (timestamp, url_key(url)) not in self.done and item not in self.items:
            self.items.append(item)

    def capture(self, capture: Capture) -> None:
        self.add(capture.timestamp, capture.original)


def _winter_pairs(
    files: Iterable[Capture], pages: _Timeline, windows: Sequence[timedelta]
) -> dict[int, list[tuple[Capture, Capture]]]:
    """Winter file captures with the page capture nearest each (tightest window first)."""
    by_season: dict[int, list[tuple[Capture, Capture]]] = defaultdict(list)
    for file_capture in files:
        season = winter_season(file_capture.when)
        if season is None:
            continue
        page = next(
            (found for w in windows if (found := pages.closest(file_capture.when, w))), None
        )
        if page is not None:
            by_season[season].append((file_capture, page))
    return by_season


def plan_follow(
    registry: Registry,
    root: Path,
    *,
    per_season: int = 2,
    limit: int | None = None,
    storms: StormDays | None = None,
) -> list[dict[str, str]]:
    """Pick captures that let pages be read through the files holding their lists.

    From the CDX listings and downloads under ``root``, most useful first:

    1. requests that failed transiently and were never served (see :func:`retry_requests`);
    2. for each downloaded page that holds no list and is not yet read through a
       file, the listed capture of the file it loads nearest to it within
       :data:`FOLLOW_WINDOW`;
    3. for each station and each of its list files (not its export) that no page
       has yet been read through to a populated list: in each winter season, the
       ``per_season`` largest listed captures with a page capture within
       :data:`FOLLOW_WINDOW`, each with that page capture;
    4. for each station with no populated read yet: the :data:`UNREAD_FILE_PICKS`
       largest winter captures of its list files and export (a list file read on
       its own is a storm-day list too); with ``storms``, instead the
       :data:`UNREAD_STORM_PICKS` captures of its list files, export and pages
       about its stormiest school days (see
       :mod:`snowlight.sources.stations.storms`);
    5. for each station's export: in each winter season, the ``per_season``
       largest captures with a page capture within :data:`COUNT_CHECK_WINDOW` (so a
       page's count can be checked), else within :data:`FOLLOW_WINDOW`, each with
       that page capture; for a station that already has a populated read, only
       pairs from before :data:`OLDER_ERAS_BEFORE` (the GSync-embed and
       script-loaded eras, whose pages hold no list of their own);
    6. requests earlier runs had no time for (:func:`unattempted_requests`),
       stations with no populated read first.

    With ``storms``, steps 3 and 5 rank each season's pairs by the storm score of
    the file capture's school day before size.

    Only replayable captures (see :func:`_listings`) are picked, with the exact
    timestamp and URL the listing gives, so the archive serves each without a
    redirect. Captures already downloaded under ``root`` are left out; ``limit``
    keeps the first so many requests.
    """
    index = station_index(registry)
    shared = shared_keys(registry)
    captures = [
        _load_capture(registry, index, base, record)[0]
        for base, record in _records_to_read(root)
        if not is_shared(record.final_original or record.url, shared)
    ]
    pairing = _pair(captures)
    populated = _populated(captures)
    stations = sorted(registry.active(), key=lambda s: s.id)
    wanted = (
        set().union(*(_loaded_keys(s) | _page_keys(s) for s in stations)) if stations else set()
    )
    listed = _listings(root, wanted.__contains__)
    plan = _Plan(downloaded(root))
    for timestamp, url in retry_requests(root):
        plan.add(timestamp, url)
    _plan_near_pages(plan, captures, pairing, listed)
    followed = _followed_files(captures, pairing)
    exports: list[tuple[Capture, Capture]] = []
    for station in stations:
        _plan_list_files(plan, station, listed, followed, (per_season, storms))
        exports += _export_pairs(
            station, listed, (per_season, storms), populated=station.id in populated
        )
    for station in stations:
        if station.id not in populated:
            _plan_unread_station(plan, station, listed, storms)
    for file_capture, page in exports:
        plan.capture(file_capture)
        plan.capture(page)

    def claimed(url: str) -> bool:
        station = index.get(url_key(url))
        return station is not None and station.id in populated

    for timestamp, url in sorted(unattempted_requests(root), key=lambda item: claimed(item[1])):
        plan.add(timestamp, url)
    return plan.items if limit is None else plan.items[:limit]


def _plan_near_pages(
    plan: _Plan,
    captures: Sequence[_Capture],
    pairing: _Pairing,
    listed: Mapping[str, Sequence[Capture]],
) -> None:
    """Step 2 of :func:`plan_follow`: the file nearest each page not yet read through one."""
    for number, capture in enumerate(captures):
        parsed = capture.parsed
        if parsed is None or number in pairing.next_of or number in pairing.used:
            continue
        targets = follow_targets(capture.original, parsed.listing, parsed.station)
        files = _Timeline.of(c for target in targets for c in listed.get(url_key(target), []))
        best = files.closest(capture.when, FOLLOW_WINDOW)
        if best is not None:
            plan.capture(best)


def _pages(station: Station, listed: Mapping[str, Sequence[Capture]]) -> _Timeline:
    return _Timeline.of(c for key in _page_keys(station) for c in listed.get(key, []))


type _Picks = tuple[int, StormDays | None]
"""How many pairs to pick per season, and the storm days that rank them."""


def _largest_per_season(
    seasons: Mapping[int, list[tuple[Capture, Capture]]], station_id: str, picks: _Picks
) -> list[list[tuple[Capture, Capture]]]:
    """Each season's best pairs: stormiest school day first (with storm days), then largest."""
    per_season, storms = picks
    rank = _rank(station_id, storms)
    return [
        sorted(seasons[season], key=lambda fp: rank(fp[0]))[:per_season]
        for season in sorted(seasons)
    ]


def _plan_list_files(
    plan: _Plan,
    station: Station,
    listed: Mapping[str, Sequence[Capture]],
    followed: set[tuple[str, str]],
    picks: _Picks,
) -> None:
    """Step 3 of :func:`plan_follow`: winter list-file and page pairs not yet followed."""
    export = url_key(station.export) if station.export else None
    pages = _pages(station, listed)
    for key in sorted(_loaded_keys(station) - {export}):
        if (station.id, key) in followed:
            continue
        seasons = _winter_pairs(listed.get(key, []), pages, (FOLLOW_WINDOW,))
        for pairs in _largest_per_season(seasons, station.id, picks):
            for file_capture, page in pairs:
                plan.capture(file_capture)
                plan.capture(page)


def _export_pairs(
    station: Station,
    listed: Mapping[str, Sequence[Capture]],
    picks: _Picks,
    *,
    populated: bool,
) -> list[tuple[Capture, Capture]]:
    """Step 5 of :func:`plan_follow`: winter export and page pairs."""
    if not station.export:
        return []
    seasons = _winter_pairs(
        listed.get(url_key(station.export), []),
        _pages(station, listed),
        (COUNT_CHECK_WINDOW, FOLLOW_WINDOW),
    )
    chosen: list[tuple[Capture, Capture]] = []
    for pairs in _largest_per_season(
        {
            season: [fp for fp in found if not populated or fp[1].when.year < OLDER_ERAS_BEFORE]
            for season, found in seasons.items()
        },
        station.id,
        picks,
    ):
        chosen += pairs
    return chosen


def _plan_unread_station(
    plan: _Plan,
    station: Station,
    listed: Mapping[str, Sequence[Capture]],
    storms: StormDays | None,
) -> None:
    """Step 4 of :func:`plan_follow`: storm-day (or the largest) winter lists of an unread station.

    With storm days: the captures of its list files, export and pages about its
    stormiest school days, at most one per URL and school day, so the picks spread
    over several storms; without them, the largest winter list-file captures.
    """
    files = [
        c
        for key in sorted(_loaded_keys(station))
        for c in listed.get(key, [])
        if winter_season(c.when) is not None
    ]
    if storms is None:
        ranked = sorted(files, key=lambda c: (-_length(c), c.timestamp))
        for file_capture in ranked[:UNREAD_FILE_PICKS]:
            plan.capture(file_capture)
        return
    pages = [
        c
        for key in sorted(_page_keys(station))
        for c in listed.get(key, [])
        if winter_season(c.when) is not None
    ]
    rank = _rank(station.id, storms)
    seen: set[tuple[str, date]] = set()
    picked = 0
    for capture in sorted((c for c in files + pages if _stormy(station.id, storms, c)), key=rank):
        day = (url_key(capture.original), school_day(capture.when))
        if day in seen:
            continue
        seen.add(day)
        plan.capture(capture)
        picked += 1
        if picked >= UNREAD_STORM_PICKS:
            break


NOT_ATTEMPTED = "not attempted"
"""How the workflow's manifest marks a request it had no time left to make."""


def _attempted(record: SnapshotRecord) -> bool:
    return not (record.error or "").startswith(NOT_ATTEMPTED)


def unattempted_requests(root: Path) -> list[tuple[str, str]]:
    """Return (timestamp, URL) of each request no run under ``root`` has made yet.

    The workflow records a request it had no time for as not attempted; such a
    request is not a capture, so :func:`parse_snapshots` leaves it out, and a later
    run can ask for it again.
    """
    made: set[tuple[str, str]] = set()
    waiting: dict[tuple[str, str], None] = {}
    for path in find_manifests(root):
        for record in read_manifest(path):
            request = (record.timestamp, record.url)
            if _attempted(record):
                made.add(request)
            else:
                waiting[request] = None
    return [request for request in waiting if request not in made]


def _records_to_read(root: Path) -> list[tuple[Path, SnapshotRecord]]:
    """Return each capture once: duplicates across artifacts and re-asked requests dropped.

    Requests a run never made (see :func:`unattempted_requests`) are left out.
    """
    manifests = [
        (path, [record for record in read_manifest(path) if _attempted(record)])
        for path in find_manifests(root)
    ]
    served = {
        (record.timestamp, record.url)
        for _path, records in manifests
        for record in records
        if record.sha256 is not None
    }
    seen: set[tuple[str, str, str]] = set()
    unserved: set[tuple[str, str]] = set()
    chosen: list[tuple[Path, SnapshotRecord]] = []
    for manifest, records in manifests:
        for record in records:
            if record.sha256 is not None:
                original = record.final_original or record.url
                key = (url_key(original), record.final_timestamp or record.timestamp, record.sha256)
                if key in seen:
                    continue
                seen.add(key)
            else:
                request = (record.timestamp, record.url)
                if request in served or request in unserved:
                    continue
                unserved.add(request)
            chosen.append((manifest.parent.parent, record))
    return chosen


def parse_snapshots(registry: Registry, root: Path) -> RunResult:
    """Parse every downloaded capture under ``root`` with its station's adapter.

    Each capture gets a health entry (its ``checked_at`` is the capture time), so
    a capture whose shape no adapter knows is an error in the output, not a
    silent gap. Captures of URLs no station uses are errors too. A capture the
    archive could not serve, a page that gives only a count or no list and could
    not be followed to its list, or a capture no station claims (a request for a
    page outside the registry) is an error entry but not a failure; an unknown
    shape on a station's page or a checksum mismatch is also listed in
    ``failures``, since it means an adapter or a download needs attention, and so
    is a page whose count differs from the list captured with it (within
    :data:`COUNT_CHECK_WINDOW`).

    A page followed to its list (see the module docstring) yields one read and
    one health entry, for the list file, naming the page in ``via`` / ``via_url``.

    Captures under a platform's shared paths (an application several stations'
    pages loaded, not a list) are set aside: listed in ``set_aside``, with no read
    or health entry.

    ``root`` may hold several artifacts; a capture downloaded more than once (the
    same page, capture time and SHA-256) is read once, and a capture asked for but
    not served is reported once per request, and not at all when another artifact
    holds the download of the same request (a later run asked again).
    """
    index = station_index(registry)
    shared = shared_keys(registry)
    result = RunResult()
    captures: list[_Capture] = []
    for base, record in _records_to_read(root):
        original = record.final_original or record.url
        if is_shared(original, shared) and index.get(url_key(original)) is None:
            stamp = record.final_timestamp or record.timestamp
            result.set_aside.append(f"{stamp} {original}")
            continue
        capture, snapshot = _load_capture(registry, index, base, record)
        captures.append(capture)
        if snapshot is not None:
            result.snapshots.append(snapshot)
    pairing = _pair(captures)
    keys: set[str] = set()
    for number, capture in enumerate(captures):
        parsed = capture.parsed
        if parsed is None or number in pairing.next_of or number in pairing.used:
            continue
        for target in follow_targets(capture.original, parsed.listing, parsed.station):
            keys.add(url_key(target))
    listed = listed_captures(root, keys)
    for number in range(len(captures)):
        if number in pairing.used:
            continue
        if number in pairing.next_of:
            _followed(captures, pairing, number, result)
        else:
            _alone(captures, number, result, listed)
    return result


UNREAD_CAUSES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("not downloaded", ("capture not downloaded",)),
    ("no station uses the URL", ("no station uses",)),
    ("unknown shape", ("unrecognized shape",)),
    ("checksum mismatch", ("SHA-256 differs",)),
    (
        "count only, list file listed near it but not downloaded",
        ("the page gives only a count", "not yet downloaded"),
    ),
    (
        "count only, list file not in the archive near it",
        ("the page gives only a count", "none within"),
    ),
    ("count only, list file not captured near it", ("the page gives only a count",)),
    ("no list, no file named", ("the page holds no list", "names no file")),
    (
        "no list, list file listed near it but not downloaded",
        ("the page holds no list", "not yet downloaded"),
    ),
    ("no list, list file not in the archive near it", ("the page holds no list", "none within")),
    ("no list, list file not captured near it", ("the page holds no list",)),
)
"""Why an archived read has no rows: a label, and the texts its health reason holds."""


def unread_summary(health: Sequence[SourceHealth]) -> dict[str, int]:
    """Count the reads that yielded no rows (error health) by cause (see UNREAD_CAUSES)."""
    counts = {label: 0 for label, _texts in UNREAD_CAUSES}
    counts["other"] = 0
    for entry in health:
        if entry.status is not HealthStatus.ERROR:
            continue
        reason = entry.reason or ""
        label = next(
            (label for label, texts in UNREAD_CAUSES if all(text in reason for text in texts)),
            "other",
        )
        counts[label] += 1
    return {label: count for label, count in counts.items() if count}


def follow_summary(reads: Sequence[ListingRead]) -> dict[str, int]:
    """Count the reads made by following pages, and the page counts checked on the way."""
    hops = [hop for read in reads for hop in read.via]
    checked = [hop for hop in hops if hop.count_matches is not None]
    return {
        "followed": sum(1 for read in reads if read.via),
        "followed_with_rows": sum(1 for read in reads if read.via and read.rows),
        "counts_checked": len(checked),
        "counts_matching": sum(1 for hop in checked if hop.count_matches),
    }


def count_differences(reads: Sequence[ListingRead]) -> list[str]:
    """Describe each page whose count differs from the list it was read through.

    Each line names the page, its count and when the count was made (see
    :data:`COUNT_CHECK_WINDOW`), and how long after that the list was captured.
    """
    lines = []
    for read in reads:
        for hop in read.via:
            if hop.count_matches is not False:
                continue
            counted = hop.count_at or hop.fetched_at
            age = int((read.fetched_at - counted).total_seconds())
            lines.append(
                f"{read.source_id} {iso_utc(hop.fetched_at)}: the page counts "
                f"{hop.declared_count} as of {iso_utc(counted)}; the list captured {age} s "
                f"later ({iso_utc(read.fetched_at)}) holds {read.rows + read.skipped_rows}"
            )
    return lines
