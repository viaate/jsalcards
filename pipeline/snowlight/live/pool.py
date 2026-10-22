"""Concurrent, polite reads of the live closings sources (spec 7.1, decision D5).

A pass reads the sources due (:mod:`snowlight.live.cadence`) on many threads at once
while staying exactly as polite as one careful reader:

* **One request in flight per key, starts spaced by the floor.** :class:`HostPacer` is
  shared by every worker: a request waits until no other request is in flight on its
  key and the key's last start is at least ``max(5 s, Crawl-delay)`` ago, and holds the
  key until its answer has been read. The key is the host (:func:`pace_key`), except
  that each of Gray's list files, path-style on ``s3.amazonaws.com``, is paced under
  its own bucket: the same as reading the bucket's documented virtual-host address
  (owner decision Q3, 2026-10-13), with no URL or robots.txt changed.
* **robots.txt once per origin per day.** :class:`RobotsStore` keeps every client's
  verdicts: one read per origin at a time (single flight), kept for 24 hours in
  ``robots.json`` across runs. A verdict is still a record and never a gate (the
  owner's decision of 2026-09-26). An unreachable one (a 5xx or a failed connection) is
  kept the same 24 hours, so an origin that resets connections is not asked again each
  pass; so is one whose answer asked for a ``Retry-After`` the deadline would not wait
  for, and that wait holds the whole origin (every source on it is ``deferred`` until it
  ends; kept in ``robots.json`` too). A robots.txt refresh keeps the host's known
  Crawl-delay. The run's refused hosts are shared by every client.
* **Each worker thread has its own** :class:`~snowlight.sources.stations.http.PoliteClient`
  (its pacing and robots dicts are not thread-safe); all share one HTTP connection
  pool, the pacer, the robots store and the conditional store. Each task (a robots.txt
  read up front or a source) starts and ends with the client unstopped, so one source's
  stop never makes the worker skip the next task's requests.
* **Lanes.** The sources are grouped by the pace key of their address, and a worker
  reads one lane's sources in turn, longest lane first; within a lane, sources in an
  alert area go first. Before the lanes, each origin whose robots.txt is not kept is
  read once (so a first pass does not wait 5 s between each robots.txt and its page).
* **Deadlines.** A source gets 60 s (all attempts and follows), and nothing starts
  after the pass's 240 s: a source not finished is ``late``. Live reads make two
  attempts. A ``Retry-After`` longer than the source's time left ends that source as
  ``deferred`` (due again only after it), and no other source waits for it.
* **A 403 (or a 401) blocks the source for 24 hours.** It is never worked around.

Outcomes: ``ok | not_modified | empty | error | blocked | deferred | late``; the ledger
turns a read that lost half its rows into ``partial``. Every request is logged
(:class:`RequestLog`: its key, its floor, whether it asked for robots.txt and when it
held the key; no page text) so a sweep can prove the pacing (:func:`violations`) and
count every robots.txt request, retries and redirect hops included (:func:`robots_requests`),
and every robots.txt read (:func:`robots_reads`).
"""

import json
import logging
import threading
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from itertools import pairwise
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

from snowlight.live.ledger import Outcome
from snowlight.output import write_bytes_atomic
from snowlight.sources.stations.fetch import RunResult
from snowlight.sources.stations.http import ROBOTS_TTL, DeadlineError, PoliteClient
from snowlight.sources.stations.model import HealthStatus
from snowlight.sources.stations.registry import Station
from snowlight.sources.stations.robots import Group, Robots, RobotsState, Rule

LOG: Final = logging.getLogger(__name__)

WORKERS: Final = 24
PASS_DEADLINE: Final = 240.0
"""Seconds after a pass starts when no source starts and no request starts."""
SOURCE_DEADLINE: Final = 60.0
"""Seconds one source may take, all attempts and follows included."""
LIVE_ATTEMPTS: Final = 2
BLOCKED_FOR: Final = timedelta(hours=24)
S3_PATH_HOST: Final = "s3.amazonaws.com"
TICK_EVERY: Final = 5.0
"""Seconds between the caller's ticks while a pass's workers run."""
ROBOTS_VERSION: Final = 1
_BLOCKED: Final = frozenset({HTTPStatus.FORBIDDEN, HTTPStatus.UNAUTHORIZED})

type Monotonic = Callable[[], float]
type Clock = Callable[[], datetime]
type ReadOne = Callable[[Station, PoliteClient], RunResult]


def pace_key(url: str) -> str:
    """The key ``url`` is paced under: its host, or ``s3.amazonaws.com/<bucket>`` for a
    path-style Amazon S3 address (each Gray list file's own bucket, owner Q3)."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host == S3_PATH_HOST:
        bucket = parts.path.lstrip("/").split("/", 1)[0]
        if bucket and bucket != "robots.txt":
            return f"{host}/{bucket}"
    return host


# Request log ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Request:
    """One request as the pacer saw it: its key, the floor it waited for, and the
    ``monotonic`` times it took and gave back the key."""

    key: str
    floor: float
    start: float
    end: float
    robots: bool = False
    origin: str = ""
    """The scheme and host the request went to (the robots.txt origin)."""
    follow: bool = False
    """A retry, or a redirect hop of a robots.txt read already started."""


class RequestLog:
    """Every request a pass made (thread-safe); kept in memory, written as JSON lines."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.entries: list[Request] = []

    def add(self, entry: Request) -> None:
        with self._lock:
            self.entries.append(entry)

    def write(self, path: Path, *, origin: float, sweep: int) -> None:
        """Append the entries to ``path``, their times in seconds since ``origin``."""
        lines = [
            json.dumps(
                {
                    "sweep": sweep,
                    "key": entry.key,
                    "floor": entry.floor,
                    "start": round(entry.start - origin, 4),
                    "end": round(entry.end - origin, 4),
                    "robots": entry.robots,
                    "origin": entry.origin,
                    "follow": entry.follow,
                },
                sort_keys=True,
            )
            for entry in sorted(self.entries, key=lambda item: item.start)
        ]
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.writelines(line + "\n" for line in lines)


def violations(entries: Iterable[Request], *, tolerance: float = 1e-6) -> list[str]:
    """Each place the log breaks the pacing: two requests in flight on one key, or two
    starts on a key closer than the highest floor any request on that key waited for
    (its known ``max(5 s, Crawl-delay)``), robots.txt requests included."""
    by_key: dict[str, list[Request]] = defaultdict(list)
    for entry in entries:
        by_key[entry.key].append(entry)
    found: list[str] = []
    for key, requests in sorted(by_key.items()):
        requests.sort(key=lambda item: item.start)
        floor = max(item.floor for item in requests)
        for before, after in pairwise(requests):
            if after.start < before.end - tolerance:
                found.append(f"{key}: in flight together at {after.start:.3f}")
            if after.start - before.start < floor - tolerance:
                gap = after.start - before.start
                found.append(f"{key}: starts {gap:.3f} s apart under a {floor} s floor")
    return found


def robots_requests(entries: Iterable[Request]) -> Counter[str]:
    """How many robots.txt requests (retries and redirect hops included) went to each
    origin."""
    return Counter(entry.origin for entry in entries if entry.robots)


def robots_reads(entries: Iterable[Request]) -> Counter[str]:
    """How many robots.txt reads started at each origin (a read's retries and redirect
    hops are part of it)."""
    return Counter(entry.origin for entry in entries if entry.robots and not entry.follow)


# Pacer ---------------------------------------------------------------------------------


class HostPacer:
    """One request in flight per key, starts spaced by each request's floor (thread-safe)."""

    def __init__(self, monotonic: Monotonic = time.monotonic, log: RequestLog | None = None):
        self._monotonic = monotonic
        self._cond = threading.Condition()
        self._busy: set[str] = set()
        self._last: dict[str, float] = {}
        self.log = log

    @contextmanager
    def slot(  # noqa: PLR0913 - the key, its floor and deadline, and three log marks
        self,
        key: str,
        wait_for: float,
        deadline: float | None = None,
        *,
        robots: bool = False,
        origin: str = "",
        follow: bool = False,
    ) -> Iterator[None]:
        """Hold ``key`` for one request (see the module); :class:`TimeoutError` when the
        key's turn comes after ``deadline``. ``robots``, ``origin`` and ``follow`` go to the
        log."""
        with self._cond:
            while True:
                now = self._monotonic()
                last = self._last.get(key)
                ready = now if last is None else max(now, last + wait_for)
                busy = key in self._busy
                if not busy and ready <= now:
                    break
                if deadline is not None and (now >= deadline or (not busy and ready > deadline)):
                    raise TimeoutError(key)
                timeout = None if busy else ready - now
                if deadline is not None:
                    timeout = deadline - now if timeout is None else min(timeout, deadline - now)
                self._cond.wait(timeout)
            self._busy.add(key)
            self._last[key] = now
        start = now
        try:
            yield
        finally:
            end = self._monotonic()
            with self._cond:
                self._busy.discard(key)
                self._cond.notify_all()
            if self.log is not None:
                self.log.add(Request(key, wait_for, start, end, robots, origin, follow))


# robots.txt ----------------------------------------------------------------------------


def _robots_json(read_at: datetime, robots: Robots) -> dict[str, object]:
    return {
        "read_at": read_at.astimezone(UTC).isoformat(),
        "state": robots.state.value,
        "sha256": robots.sha256,
        "groups": [
            {
                "agents": list(group.agents),
                "rules": [[rule.allow, rule.pattern] for rule in group.rules],
                "crawl_delay": group.crawl_delay,
            }
            for group in robots.groups
        ],
    }


def _robots_from(value: Mapping[str, object]) -> tuple[datetime, Robots]:
    groups = value.get("groups")
    if not isinstance(groups, list):
        raise TypeError("groups")
    built = []
    for group in groups:
        rules = [Rule(bool(allow), str(pattern)) for allow, pattern in group["rules"]]
        delay = group.get("crawl_delay")
        built.append(
            Group(
                agents=[str(agent) for agent in group["agents"]],
                rules=rules,
                crawl_delay=float(delay) if delay is not None else None,
            )
        )
    sha = value.get("sha256")
    robots = Robots(
        RobotsState(str(value["state"])),
        tuple(built),
        sha if isinstance(sha, str) else None,
    )
    return datetime.fromisoformat(str(value["read_at"])), robots


class RobotsStore:
    """robots.txt verdicts shared by every client of a process and kept across runs.

    :meth:`get` reads an origin's file at most once at a time (single flight) and keeps it
    for :data:`~snowlight.sources.stations.http.ROBOTS_TTL`, an unreachable one too.
    :meth:`flush` writes the kept verdicts to
    ``path`` (the parsed rules, read times and digests; atomically).
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.refused: dict[str, str] = {}
        self.reads: Counter[str] = Counter()
        self._lock = threading.Lock()
        self._origin_locks: dict[str, threading.Lock] = {}
        self._kept: dict[str, tuple[datetime, Robots]] = {}
        self._held: dict[str, datetime] = {}
        self._dirty = False
        if path is not None:
            self._load(path)

    def _load(self, path: Path) -> None:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as error:
            LOG.warning("robots store unreadable, starting empty: %s", type(error).__name__)
            return
        if not isinstance(document, dict) or document.get("version") != ROBOTS_VERSION:
            return
        origins = document.get("origins")
        if not isinstance(origins, dict):
            return
        for origin, value in origins.items():
            try:
                self._kept[str(origin)] = _robots_from(value)
            except (KeyError, TypeError, ValueError):
                continue
        held = document.get("held")
        for origin, until in (held if isinstance(held, dict) else {}).items():
            try:
                self._held[str(origin)] = datetime.fromisoformat(str(until))
            except ValueError:
                continue

    def _origin_lock(self, origin: str) -> threading.Lock:
        with self._lock:
            return self._origin_locks.setdefault(origin, threading.Lock())

    def fresh(self, origin: str, now: datetime) -> bool:
        """Whether a verdict younger than its time to live is kept for ``origin``."""
        with self._lock:
            kept = self._kept.get(origin)
        return kept is not None and now - kept[0] < ROBOTS_TTL

    def known(self, origin: str) -> Robots | None:
        """The origin's last kept robots.txt, however old."""
        with self._lock:
            kept = self._kept.get(origin)
        return kept[1] if kept is not None else None

    def hold(self, origin: str, until: datetime) -> None:
        """Ask nothing of ``origin`` before ``until`` (kept in ``robots.json``)."""
        with self._lock:
            self._held[origin] = max(until, self._held.get(origin, until))
            self._dirty = True

    def held(self, origin: str, now: datetime) -> float | None:
        """Seconds until ``origin``'s hold ends, or None when it is not held."""
        with self._lock:
            until = self._held.get(origin)
        if until is None or now >= until:
            return None
        return (until - now).total_seconds()

    def get(self, origin: str, now: datetime, read: Callable[[], Robots]) -> Robots:
        """The origin's robots.txt, read through ``read`` only when none is kept fresh."""
        with self._origin_lock(origin):
            with self._lock:
                kept = self._kept.get(origin)
            if kept is not None and now - kept[0] < ROBOTS_TTL:
                return kept[1]
            robots = read()
            with self._lock:
                self.reads[origin] += 1
                self._kept[origin] = (now, robots)
                self._dirty = True
            return robots

    def flush(self) -> None:
        """Write the kept verdicts when any changed."""
        if self.path is None:
            return
        with self._lock:
            if not self._dirty:
                return
            origins = {
                origin: _robots_json(read_at, robots)
                for origin, (read_at, robots) in sorted(self._kept.items())
            }
            held = {
                origin: until.astimezone(UTC).isoformat()
                for origin, until in sorted(self._held.items())
            }
            self._dirty = False
        document = {"version": ROBOTS_VERSION, "origins": origins, "held": held}
        text = json.dumps(document, sort_keys=True)
        write_bytes_atomic(self.path, (text + "\n").encode("utf-8"))


# The pass ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceResult:
    """How one source's read went this pass."""

    source_id: str
    outcome: Outcome
    seconds: float
    """From the source's start to its end (0 for a source never started)."""
    finished: float
    """Seconds from the pass's start to the source's end."""
    http_status: int | None = None
    retry_after: float | None = None
    result: RunResult = field(default_factory=RunResult, repr=False)


@dataclass(frozen=True, slots=True)
class PassResult:
    """One pass of the pool."""

    started: datetime
    seconds: float
    sources: tuple[SourceResult, ...]
    lanes: int

    def counts(self) -> dict[str, int]:
        """How many sources ended each way."""
        return dict(sorted(Counter(item.outcome.value for item in self.sources).items()))


def lanes_of(
    due: Iterable[Station], alerted: Callable[[Station], bool] = lambda _station: False
) -> list[list[Station]]:
    """The due sources grouped by the pace key of their address: longest lane first (then
    by key), and within a lane the sources in an alert area first (then by id)."""
    grouped: dict[str, list[Station]] = defaultdict(list)
    for station in due:
        if station.poll_url is not None:
            grouped[pace_key(station.poll_url)].append(station)
    for stations in grouped.values():
        stations.sort(key=lambda item: (not alerted(item), item.id))
    return [grouped[key] for key in sorted(grouped, key=lambda key: (-len(grouped[key]), key))]


def classify(result: RunResult, source_id: str) -> tuple[Outcome, int | None]:
    """A finished read's outcome (from its last health record) and HTTP status."""
    health = [entry for entry in result.health if entry.source_id == source_id]
    if not health:
        return Outcome.ERROR, None
    last = health[-1]
    if last.status is HealthStatus.OK:
        return (Outcome.NOT_MODIFIED if last.not_modified else Outcome.OK), last.http_status
    if last.status is HealthStatus.EMPTY:
        return Outcome.EMPTY, last.http_status
    if last.http_status in _BLOCKED:
        return Outcome.BLOCKED, last.http_status
    return Outcome.ERROR, last.http_status


@dataclass(slots=True)
class Pool:
    """The workers' shared parts (see the module); one per process."""

    client: Callable[[], PoliteClient]
    """A new client for one worker thread, sharing the pacer, robots and stores."""
    workers: int = WORKERS
    pass_deadline: float = PASS_DEADLINE
    source_deadline: float = SOURCE_DEADLINE
    monotonic: Monotonic = time.monotonic
    clock: Clock = field(default=lambda: datetime.now(UTC))
    robots: RobotsStore | None = None
    _local: threading.local = field(default_factory=threading.local)

    def _worker_client(self) -> PoliteClient:
        client: PoliteClient | None = getattr(self._local, "client", None)
        if client is None:
            client = self.client()
            self._local.client = client
        return client

    def run_pass(
        self,
        due: Sequence[Station],
        read: ReadOne,
        *,
        alerted: Callable[[Station], bool] = lambda _station: False,
        tick: Callable[[], None] = lambda: None,
    ) -> PassResult:
        """Read every source in ``due`` once (see the module), calling ``tick`` every few
        seconds from this thread while the workers run."""
        started = self.clock()
        origin = self.monotonic()
        end = origin + self.pass_deadline
        lanes = lanes_of(due, alerted)
        found: list[SourceResult] = []
        lock = threading.Lock()

        def run_lane(lane: list[Station]) -> None:
            for station in lane:
                result = self._read_one(station, read, origin, end)
                with lock:
                    found.append(result)

        with ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="live-pool") as pool:
            pending: set[Future[None]] = {
                pool.submit(self._robots_first, url, end)
                for url in self._unread_origins(due, started)
            }
            pending |= {pool.submit(run_lane, lane) for lane in lanes}
            while pending:
                done, pending = wait(pending, timeout=TICK_EVERY, return_when=FIRST_COMPLETED)
                for future in done:
                    future.result()
                tick()
        if self.robots is not None:
            self.robots.flush()
        return PassResult(started, self.monotonic() - origin, tuple(found), len(lanes))

    def _unread_origins(self, due: Sequence[Station], now: datetime) -> list[str]:
        """One address per origin whose robots.txt is not kept fresh (none without a store)."""
        if self.robots is None:
            return []
        seen: dict[str, str] = {}
        for station in due:
            url = station.poll_url
            if url is None:
                continue
            parts = urlsplit(url)
            origin = f"{parts.scheme}://{parts.netloc}".lower()
            if origin not in seen and not self.robots.fresh(origin, now):
                seen[origin] = url
        return [seen[origin] for origin in sorted(seen)]

    def _robots_first(self, url: str, end: float) -> None:
        client = self._worker_client()
        client.deadline = end
        client.stopped = None  # a task never inherits the stop of the one before it
        try:
            client.robots_for(url)
        except Exception as error:  # a page read reads it again, or records why not
            LOG.info("robots first %s: %s", urlsplit(url).hostname, type(error).__name__)
        finally:
            client.deadline = None
            client.stopped = None

    def _read_one(self, station: Station, read: ReadOne, origin: float, end: float) -> SourceResult:
        begin = self.monotonic()
        if begin >= end:
            return SourceResult(station.id, Outcome.LATE, 0.0, begin - origin)
        client = self._worker_client()
        client.deadline = min(begin + self.source_deadline, end)
        client.stopped = None
        result: RunResult | None = None
        try:
            result = read(station, client)
        except Exception as error:
            if client.stopped is None:
                LOG.error("read %s: %s", station.id, type(error).__name__)
        finally:
            client.deadline = None
        finish = self.monotonic()
        stopped: DeadlineError | None = client.stopped
        client.stopped = None  # the worker's next task starts unstopped
        if stopped is not None:
            outcome = Outcome.DEFERRED if stopped.kind == "deferred" else Outcome.LATE
            return SourceResult(
                station.id,
                outcome,
                finish - begin,
                finish - origin,
                stopped.status,
                stopped.retry_after,
                result or RunResult(),
            )
        if result is None:
            return SourceResult(station.id, Outcome.ERROR, finish - begin, finish - origin)
        outcome, status = classify(result, station.id)
        return SourceResult(
            station.id, outcome, finish - begin, finish - origin, status, None, result
        )


def percentile(values: Sequence[float], share: float) -> float:
    """The nearest-rank percentile of ``values`` (0 when there are none)."""
    if not values:
        return 0.0
    ranked = sorted(values)
    index = max(0, min(len(ranked) - 1, -(-int(share * 100) * len(ranked) // 100) - 1))
    return ranked[index]
