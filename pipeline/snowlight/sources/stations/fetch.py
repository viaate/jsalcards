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
   loads (a frame, a script's data file) is followed to that file. A station
   polled at its page whose browser check (``page_check``) recorded the files the
   page loads must be led to one of them; a page that names another file, or
   none, is an error (:func:`page_check_mismatch`).
4. A list last written before the last winter began (its file's ``Last-Modified``,
   or the time the list itself says it was updated, is older than
   :func:`~snowlight.sources.stations.model.stale_before`) is judged by its market's
   closure seasons since (:mod:`snowlight.sources.stations.seasons`, from
   ``closure-days.json``): when weather that closes schools came to the market after
   that and the list was not written for it, the read is ``stale``: its rows are not
   kept and the source does not count as working (a station that moved its list
   elsewhere leaves the old file behind). When no such weather has come since, the
   list is idle: its rows are old, not kept, and the read is ``empty`` (the source
   counts as working). Without that record for the station's market, any such list is
   ``stale``.
5. A list typed by hand into a page (``Listing.typed``, see
   :mod:`snowlight.sources.stations.typed`) keeps its rows only while they are
   current. When the page says when it last changed, that time must be within
   :data:`TYPED_CURRENT` of the read; rows of a page last changed earlier are old
   notes, not kept (the read is ``empty``: the station's list holds nothing current).
   A page that says no time for itself is judged row by row
   (:func:`snowlight.sources.stations.typed_history.judge`): a row whose heading,
   note or line names a day near the read is kept, and so is one an earlier read of
   the page (live, or an archived capture) made within :data:`TYPED_CURRENT` did not
   hold; a row the page has held unchanged since a read made earlier than that is an
   old note. When no row is kept, the read is ``empty`` if every row is an old note,
   and ``stale`` if any cannot be told from one (no earlier read dates it). The
   earlier reads are ``typed-history.json`` (each live read of a typed page is added
   to it) and the archive parse's reads of the station's captures. The lines of a
   page's own text that a channel's list carries beside its notices (``section``
   page-text) are judged the same way, row by row (:func:`judge_page_text`): a
   homepage's "closed today" left up for months is an old note, not today's closing.
6. A feed of dated posts (``Listing.dated_rows``: an Apptegy district's live feed, a
   station's closings articles) keeps a post only while it was published within
   :data:`TYPED_CURRENT` of the read (:func:`posted_recently`): a feed keeps its old posts,
   and only a new one says anything about today. A feed with posts but none that recent
   reads ``empty``. Its newest post's time is the list's own (``list_updated_at``), judged
   by step 4 like any list's.

Outputs, under ``pipeline/out/internal/stations/`` (internal, never published)::

    rows.jsonl       RawRow per line (see snowlight.sources.stations.model)
    reads.jsonl      ListingRead per source read
    health.json      {"generated_at", "stale_before", "sources": [SourceHealth...],
                      "totals": {...}}
    typed-history.json  every read of a typed page so far (``--typed-history``; see
                     :mod:`snowlight.sources.stations.typed_history`)
    manifest.json    RunManifest: every body read (URL, time, status, SHA-256, size)
"""

from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from snowlight import __version__
from snowlight.output import JSONValue, write_bytes_atomic, write_json
from snowlight.schemas.internal import RunManifest, SourceSnapshot
from snowlight.sources.stations import typed_history
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
    ParsedRow,
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
from snowlight.sources.stations.seasons import ClosureSeasons, SeasonVerdict
from snowlight.sources.stations.typed_history import Judgement, Seen, TypedHistory

type Clock = Callable[[], datetime]

DEFAULT_OUT_DIR = PIPELINE_ROOT / "out" / "internal" / "stations"
DEFAULT_CACHE_DIR = PIPELINE_ROOT / ".cache" / "stations" / "live"
MAX_REASON = 500
MAX_FOLLOW_DEPTH = 3
"""How many files deep a page that loads its list from another file is followed."""
TYPED_CURRENT = typed_history.TYPED_CURRENT
"""How long a typed list's rows are taken as current (step 5)."""
TYPED_PAGE_ADAPTERS = frozenset({"district-homepage", "nexstar-typed", "scripps-typed"})
"""The adapters of stations that type their closings into a page: every read of their page
is an observation in the typed history, whatever variant it was read as."""
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
    typed_seen: list[tuple[str, Seen]] = field(default_factory=list)
    """Each read of a typed page: (source id, observation), for the typed history."""


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


def typed_not_current(listing: Listing, read_at: datetime, earlier: Sequence[Seen] = ()) -> bool:
    """Whether a list typed by hand keeps none of its rows as current (step 5)."""
    if not listing.typed or not listing.rows:
        return False
    said = listing.list_updated_at
    if said is None:
        return not typed_history.judge(listing.rows, read_at, earlier).kept
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


def page_check_mismatch(
    station: Station, targets: Sequence[str], beside: Sequence[str] = ()
) -> str | None:
    """Why a live read of a station's checked page does not lead to its checked list, or None.

    Applies to a station polled at its page (it registers no ``data_url``) whose
    ``page_check`` records the files that page loads (``loads``): the page read
    first must name one of those files, and is followed to it (``targets`` are the
    URLs it names, :func:`follow_targets`). A page that holds a list of its own,
    names no file, or names another one (a page ID that changed, a list moved
    elsewhere) is an error until the page is checked again, never read as the
    station's list: a file address can answer for anything (a Finalsite page-pops
    address answers an empty 200 for any page ID). The one exception is a page that
    holds a list of its own and names the checked file beside it (``beside``, its
    ``also_loads`` resolved: a homepage whose own text shows closing lines, read as
    such by :mod:`snowlight.sources.stations.homepage`): the page is still the one
    checked, and its own list is read (the file beside it is not, live). Stations
    polled at a data file, and stations without such a check, are not affected.
    """
    check = station.page_check
    if station.data_url is not None or check is None or not check.loads:
        return None
    checked = {_resource(url) for url in check.loads}
    if targets and _resource(targets[0]) in checked:
        return None
    if not targets and beside and _resource(beside[0]) in checked:
        return None
    seen = ", ".join(check.loads)
    when = iso_utc(check.checked_at)
    if not targets:
        return (
            f"the page names no list file to follow; its browser check of {when} saw it load "
            f"{seen}. Not read until the page is checked again"
        )
    return (
        f"the page now loads {targets[0]}, not {seen} (its browser check of {when}). "
        "Not read until the page is checked again"
    )


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
    post = station.data_post if url == station.data_url else None
    try:
        fetched = client.fetch(url, post=post.encode("utf-8") if post is not None else None)
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


@dataclass(frozen=True, slots=True)
class Judges:
    """What judges a list's age: closure seasons (step 4) and the typed history (step 5)."""

    seasons: ClosureSeasons | None = None
    history: TypedHistory | None = None


NO_JUDGES = Judges()


def read_station(
    registry: Registry,
    station: Station,
    client: PoliteClient,
    now: datetime,
    judges: Judges = NO_JUDGES,
) -> RunResult:
    """Read one station live (or record why not) and return what came of it.

    A page that holds no list and names the file it loads (or whose station has an
    export it loads, :attr:`Station.export`) is followed to that file, up to
    :data:`MAX_FOLLOW_DEPTH` files deep, through the same polite client
    (robots.txt, pacing, conditional requests); the read describes the list file
    and names the pages in ``via``. A station polled at a page its ``page_check``
    records must be led by that page to a file the check saw it load
    (:func:`page_check_mismatch`); otherwise the read is an error.
    robots.txt's verdicts on every URL requested go into the health record. A list
    last written before the last winter began is judged by ``seasons`` (step 4 of the
    module docstring; without them it is ``stale``) and an undated typed list by the
    typed history (step 5), both in ``judges``: rows not current are not kept.
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
        beside = [urljoin(read.url, reference) for reference in read.listing.also_loads]
        mismatch = None if chain else page_check_mismatch(station, targets, beside)
        if mismatch is not None:
            result.health.append(
                _health(
                    station,
                    read.url,
                    read.fetched.fetched_at,
                    status=HealthStatus.ERROR,
                    http_status=read.fetched.status,
                    not_modified=read.fetched.not_modified,
                    sha256=read.fetched.sha256,
                    bytes=len(read.fetched.body),
                    reason=_clip(
                        f"{mismatch} ({read.listing.variant}, {read.listing.state.value})"
                    ),
                    robots=seen,
                )
            )
            return result
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
    if (
        registry.platform_of(station).adapter in TYPED_PAGE_ADAPTERS
        or listing.typed
        or _page_text_rows(listing)
    ):
        result.typed_seen.append(
            (
                station.id,
                typed_history.observation(
                    fetched.fetched_at, read.url, fetched.sha256, listing.rows
                ),
            )
        )
    via = tuple(via_pages(chain, listing))
    modified = last_modified(fetched)
    written = old_write(modified, listing.list_updated_at, stale_before(now))
    season = (
        judges.seasons.judge(station.id, written)
        if written is not None and judges.seasons is not None
        else None
    )
    judgement = judge_typed(station, read.url, listing, fetched.fetched_at, judges.history)
    keep = current_rows(listing, fetched.fetched_at, written, judgement)
    text_judgement = judge_page_text(station, read.url, listing, fetched.fetched_at, judges.history)
    keep = page_text_kept(keep, text_judgement)
    rows = stamp_rows(station.id, fetched.fetched_at, listing.model_copy(update={"rows": keep}))
    result.rows.extend(rows)
    described = listing_read(
        station.id,
        ReadMode.LIVE,
        read.url,
        BodyStamp(fetched.fetched_at, fetched.fetched_at, fetched.sha256, len(fetched.body)),
        listing,
    ).model_copy(update={"via": via, "last_modified": modified})
    result.reads.append(described)
    status, why = read_health(
        listing, fetched.fetched_at, (modified, written), (season, judgement), len(rows)
    )
    if text_judgement is not None and not rows and status is HealthStatus.OK:
        status, why = (
            HealthStatus.EMPTY,
            _clip(
                f"its rows are lines of the page's own text ({len(text_judgement.rows)}), each an "
                f"old note or not yet dated by an earlier read ({text_judgement.summary()}): not "
                f"kept ({listing.variant})"
            ),
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


def old_write(
    modified: datetime | None, said: datetime | None, threshold: datetime
) -> datetime | None:
    """When a list last written before the last winter began was written (step 4), or None.

    The time is the latest of those older than ``threshold``: the list file's
    ``Last-Modified`` and the time the list says it was updated.
    """
    old = [moment for moment in (modified, said) if moment is not None and moment < threshold]
    return max(old) if old else None


def judge_typed(
    station: Station,
    url: str,
    listing: Listing,
    read_at: datetime,
    history: TypedHistory | None,
) -> Judgement | None:
    """Judge an undated typed list's rows against the page's earlier reads (step 5), or None."""
    if not listing.typed or not listing.rows or listing.list_updated_at is not None:
        return None
    earlier = history.earlier(station.id, url, read_at) if history is not None else []
    return typed_history.judge(listing.rows, read_at, earlier)


PAGE_TEXT = "page-text"
"""``raw_extra["section"]`` of a row read from a page's own text
(:data:`snowlight.sources.stations.homepage.PAGE_TEXT`)."""


def _page_text_rows(listing: Listing) -> tuple[ParsedRow, ...]:
    return tuple(row for row in listing.rows if row.extra.get("section") == PAGE_TEXT)


def page_text_kept(
    keep: tuple[ParsedRow, ...], judgement: Judgement | None
) -> tuple[ParsedRow, ...]:
    """The rows a read keeps once its page-text lines are judged (:func:`judge_page_text`):
    the channel's own rows as kept, and only the lines the judgement keeps."""
    if judgement is None:
        return keep
    return (
        *(row for row in keep if row.extra.get("section") != PAGE_TEXT),
        *(row for row in judgement.kept if row in keep),
    )


def judge_page_text(
    station: Station,
    url: str,
    listing: Listing,
    read_at: datetime,
    history: TypedHistory | None,
) -> Judgement | None:
    """Judge the lines of a page's own text beside a channel's list (step 5), or None.

    A channel's page (a SchoolBlocks or Finalsite homepage) also shows lines of its own
    text that announce a closing (:func:`snowlight.sources.stations.homepage.with_page_text`);
    such a line states no time and a homepage keeps it long after the day (North Gem's
    "all North Gem schools are closed today", up from 2026-02-18 to October). Like a typed
    page's rows, each is kept only when it names a day near the read or is new since an
    earlier read of the page (:func:`snowlight.sources.stations.typed_history.judge`);
    the channel's own rows are judged as before. A typed page's rows are judged whole
    (:func:`judge_typed`), so this is None for it, and for a list with no such line.
    """
    lines = _page_text_rows(listing)
    if listing.typed or not lines:
        return None
    earlier = history.earlier(station.id, url, read_at) if history is not None else []
    return typed_history.judge(lines, read_at, earlier)


def current_rows(
    listing: Listing,
    read_at: datetime,
    written: datetime | None,
    judgement: Judgement | None,
) -> tuple[ParsedRow, ...]:
    """The rows a read keeps (steps 4 and 5): none of a list last written before the last
    winter, of a typed page last changed outside the window, or the undated typed rows not
    kept by their judgement."""
    if written is not None:
        return ()
    said = listing.list_updated_at
    if listing.typed and said is not None and said < read_at - TYPED_CURRENT:
        return ()
    if judgement is not None:
        return judgement.kept
    if listing.dated_rows:
        return tuple(row for row in listing.rows if posted_recently(row, read_at))
    return listing.rows


def posted_recently(row: ParsedRow, read_at: datetime) -> bool:
    """Whether a feed's post was published within :data:`TYPED_CURRENT` of the read (step 6).

    The post's time is its ``updated_text`` (an ISO 8601 instant the server wrote); a post
    without one, or published after the read, is not current.
    """
    if row.updated_text is None:
        return False
    try:
        posted = datetime.fromisoformat(row.updated_text)
    except ValueError:
        return False
    posted = posted.astimezone(UTC) if posted.tzinfo is not None else posted.replace(tzinfo=UTC)
    return read_at - TYPED_CURRENT <= posted <= read_at


def read_health(
    listing: Listing,
    read_at: datetime,
    times: tuple[datetime | None, datetime | None],
    verdicts: tuple[SeasonVerdict | None, Judgement | None],
    kept: int,
) -> tuple[HealthStatus, str | None]:
    """The health of a parsed read, and why when it is not plainly ok or empty.

    ``times`` are the list file's ``Last-Modified`` and the old write (:func:`old_write`);
    ``verdicts`` the closure-season verdict on that write and the typed judgement;
    ``kept`` how many rows the read keeps.
    """
    modified, written = times
    season, judgement = verdicts
    said = listing.list_updated_at
    if written is not None:
        return _season_health(listing, read_at, written == modified, written, season)
    if listing.typed and said is not None and said < read_at - TYPED_CURRENT and listing.rows:
        return HealthStatus.EMPTY, _clip(
            f"a list typed by hand into the page, last changed {iso_utc(said)}, more than "
            f"{TYPED_CURRENT.total_seconds() / 3600:.0f} hours before the read: its "
            f"{len(listing.rows)} rows are old notes, not kept ({listing.variant})"
        )
    if listing.dated_rows and listing.rows and not kept:
        return HealthStatus.EMPTY, _clip(
            f"a feed of {len(listing.rows)} dated posts, none published within "
            f"{TYPED_CURRENT.total_seconds() / 3600:.0f} hours before the read (the newest "
            f"{iso_utc(said) if said is not None else 'undated'}): old posts, not kept "
            f"({listing.variant})"
        )
    if judgement is None:
        return listing_health(listing)
    return _typed_health(judgement, listing.variant, kept)


def _season_health(
    listing: Listing,
    read_at: datetime,
    file_time: bool,
    written: datetime,
    season: SeasonVerdict | None,
) -> tuple[HealthStatus, str | None]:
    """The health of a list last written before the last winter began (step 4)."""
    what = (
        f"the list file was last modified {iso_utc(written)}"
        if file_time
        else f"the list says it was last updated {iso_utc(written)}"
    )
    threshold = f"before the last winter began ({iso_utc(stale_before(read_at))})"
    found = f"{len(listing.rows)} rows"
    shape = f"({listing.variant}, {listing.state.value})"
    if season is None:
        return HealthStatus.STALE, _clip(
            f"{what}, {threshold}, and no closure-season record measures its market: nothing "
            f"has been written to it for a whole winter, so its {found} are not kept {shape}"
        )
    if season.stale:
        return HealthStatus.STALE, _clip(
            f"{what}, {threshold}; {season.explain()}. Its {found} are not kept {shape}"
        )
    if listing.state in (ListingState.POPULATED, ListingState.EMPTY):
        return HealthStatus.EMPTY, _clip(
            f"{what}, {threshold}; {season.explain()}. Its {found} are old, not kept {shape}"
        )
    return listing_health(listing)


def _typed_health(judgement: Judgement, variant: str, kept: int) -> tuple[HealthStatus, str]:
    """The health of an undated typed read judged row by row (step 5)."""
    hours = f"{TYPED_CURRENT.total_seconds() / 3600:.0f} hours"
    rows = len(judgement.rows)
    basis = f"{judgement.earlier} earlier reads of the page on record"
    oldest = judgement.oldest()
    since = ""
    if oldest is not None and oldest.since is not None:
        lacking = (
            f", and {oldest.lacking.describe()} did not hold it"
            if oldest.lacking is not None
            else ""
        )
        since = (
            f"; the page has held {oldest.row.name!r} unchanged since {oldest.since.describe()}"
            f"{lacking}"
        )
    if kept:
        dropped = rows - kept
        note = f"; {dropped} not kept ({judgement.summary()})" if dropped else ""
        return HealthStatus.OK, _clip(
            f"a list typed by hand into a page that says no time for it: {kept} of its {rows} "
            f"rows are dated near the read or new since a read within {hours}{note} "
            f"({basis}{since}; {variant})"
        )
    if judgement.all_old:
        return HealthStatus.EMPTY, _clip(
            f"a list typed by hand into a page that says no time for it: its {rows} rows have "
            f"stood unchanged for more than {hours} ({basis}{since}), so they are old notes, "
            f"not kept, and the list holds nothing current ({variant})"
        )
    return HealthStatus.STALE, _clip(
        f"a list typed by hand into the page, which says no time for it and names no day near "
        f"the read: its {rows} rows ({judgement.summary()}) cannot be told from old notes "
        f"({basis}{since}), so they are not kept ({variant})"
    )


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
    judges: Judges = NO_JUDGES,
) -> RunResult:
    """Read every station (or only the ids in ``only``) once.

    ``judges`` judge lists last written long ago and undated typed lists (steps 4 and
    5); each typed read is added to the typed history as it is made.
    """
    wanted = set(only) if only is not None else None
    if wanted is not None:
        unknown = wanted - set(registry.stations)
        if unknown:
            raise KeyError(f"unknown station ids: {sorted(unknown)}")
    total = RunResult()
    for station in sorted(registry.stations.values(), key=lambda s: s.id):
        if wanted is not None and station.id not in wanted:
            continue
        part = read_station(registry, station, client, clock(), judges)
        if judges.history is not None:
            for source_id, observed in part.typed_seen:
                judges.history.add(source_id, observed)
        total.typed_seen.extend(part.typed_seen)
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
