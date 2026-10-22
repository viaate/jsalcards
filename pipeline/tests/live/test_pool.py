"""The live pool (spec 7.1, T18 and T19) on SYNTHETIC hosts served in memory.

Time is scaled: 1 s of real pacing is :data:`SCALE` s here (the 5 s floor is 50 ms, a
Crawl-delay of 10 s is 100 ms, a 290 s ``Retry-After`` is 2.9 s), so the pool runs its real
threads, pacer and clients in a fraction of a second.
"""

import json
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest

from snowlight.live.ledger import Outcome
from snowlight.live.pool import (
    LIVE_ATTEMPTS,
    HostPacer,
    Pool,
    Request,
    RequestLog,
    RobotsStore,
    classify,
    lanes_of,
    pace_key,
    percentile,
    robots_reads,
    robots_requests,
    violations,
)
from snowlight.sources.stations.fetch import RunResult
from snowlight.sources.stations.http import (
    REQUEST_GRACE,
    ConditionalStore,
    DeadlineError,
    FetchError,
    PoliteClient,
    Timing,
)
from snowlight.sources.stations.model import HealthStatus, SourceHealth
from snowlight.sources.stations.registry import Station
from snowlight.sources.stations.robots import Robots, RobotsState

SCALE = 0.01
FLOOR = 5 * SCALE
HEARST_DELAY = 10 * SCALE
LATENCY = 0.002


def station(source_id: str, url: str, fips: tuple[str, ...] = ("20091",)) -> Station:
    """A SYNTHETIC station polled at ``url``."""
    body = {
        "id": source_id,
        "platform": "synthetic",
        "call_sign": "SYNT",
        "name": "SYNTHETIC station",
        "market": "SYNTHETIC market",
        "dma": None,
        "states": ["KS"],
        "counties": {"basis": "dma", "source": "SYNTHETIC", "fips": list(fips)},
        "page_url": url,
        "data_url": None,
        "archive_urls": [],
        "poll_minutes": None,
        "status": "active",
        "evidence": "SYNTHETIC",
    }
    return Station.model_validate_json(json.dumps(body))


class Server:
    """SYNTHETIC hosts: records every request as the server saw it (its pace key, when it
    started and ended) and any two requests in flight together on one key."""

    def __init__(
        self,
        *,
        robots: dict[str, bytes] | None = None,
        stall: dict[str, float] | None = None,
        answer: dict[str, httpx.Response] | None = None,
    ) -> None:
        self.robots = robots or {}
        self.stall = stall or {}
        self.answer = answer or {}
        self.lock = threading.Lock()
        self.inflight: Counter[str] = Counter()
        self.overlaps: list[str] = []
        self.hits: list[tuple[str, str, float, float]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        key = pace_key(url)
        with self.lock:
            if self.inflight[key]:
                self.overlaps.append(key)
            self.inflight[key] += 1
        start = time.monotonic()
        try:
            time.sleep(self.stall.get(url, LATENCY))
            if urlsplit(url).path == "/robots.txt":
                origin = f"{request.url.scheme}://{request.url.host}"
                body = self.robots.get(origin)
                return httpx.Response(200, content=body) if body else httpx.Response(404)
            if url in self.answer:
                return self.answer[url]
            return httpx.Response(200, content=b"SYNTHETIC list")
        finally:
            end = time.monotonic()
            with self.lock:
                self.inflight[key] -= 1
                self.hits.append((key, url, start, end))

    def pages(self) -> list[str]:
        return [url for _, url, _, _ in self.hits if urlsplit(url).path != "/robots.txt"]

    def robots_reads(self) -> Counter[str]:
        return Counter(
            f"{urlsplit(url).scheme}://{urlsplit(url).netloc}"
            for _, url, _, _ in self.hits
            if urlsplit(url).path == "/robots.txt"
        )


def make_pool(  # noqa: PLR0913 - the parts a test sets
    tmp_path: Path,
    server: Server,
    *,
    log: RequestLog | None = None,
    robots: RobotsStore | None = None,
    pass_deadline: float = 60.0,
    source_deadline: float = 10.0,
) -> Pool:
    http = httpx.Client(transport=httpx.MockTransport(server))
    store = ConditionalStore(tmp_path / "cache")
    shared = robots if robots is not None else RobotsStore(None)
    pacer = HostPacer(log=log)

    def client() -> PoliteClient:
        return PoliteClient(
            http,
            store,
            host_interval=FLOOR,
            attempts=LIVE_ATTEMPTS,
            pacer=pacer,
            robots=shared,
            pace_key=pace_key,
        )

    return Pool(
        client=client,
        robots=shared,
        pass_deadline=pass_deadline,
        source_deadline=source_deadline,
    )


def health(source: Station, status: HealthStatus, http_status: int | None) -> SourceHealth:
    return SourceHealth.model_validate(
        {
            "source_id": source.id,
            "url": source.poll_url,
            "checked_at": datetime(2026, 11, 16, 11, tzinfo=UTC),
            "rows": 1 if status is HealthStatus.OK else 0,
            "status": status,
            "http_status": http_status,
            "reason": "SYNTHETIC" if status is HealthStatus.ERROR else None,
        }
    )


def read(source: Station, client: PoliteClient) -> RunResult:
    """The SYNTHETIC source read: one page through the polite client."""
    result = RunResult()
    assert source.poll_url is not None
    try:
        fetched = client.fetch(source.poll_url)
    except FetchError as error:
        result.health.append(health(source, HealthStatus.ERROR, error.status))
        return result
    result.health.append(health(source, HealthStatus.EMPTY, fetched.status))
    return result


def world() -> tuple[list[Station], dict[str, bytes], set[str]]:
    """900 SYNTHETIC URLs over 640 pace keys: one host with 11 pages, 20 Hearst-like hosts
    with 3 pages each and ``Crawl-delay: 10``, 111 Gray buckets path-style on
    s3.amazonaws.com, 210 hosts with 2 pages and 298 with 1."""
    stations: list[Station] = []
    robots: dict[str, bytes] = {}
    hearst: set[str] = set()

    def add(host: str, count: int) -> None:
        for page in range(count):
            stations.append(station(f"synthetic-{len(stations):04d}", f"https://{host}/c/{page}"))

    add("big.example.test", 11)
    for index in range(20):
        host = f"hearst{index:02d}.example.test"
        hearst.add(host)
        robots[f"https://{host}"] = b"User-agent: *\nCrawl-delay: 0.1\n"
        add(host, 3)
    for index in range(111):
        url = f"https://s3.amazonaws.com/grayfilestore-s{index:03d}/closings.json"
        stations.append(station(f"synthetic-{len(stations):04d}", url))
    for index in range(210):
        add(f"two{index:03d}.example.test", 2)
    for index in range(298):
        add(f"one{index:03d}.example.test", 1)
    return stations, robots, hearst


def test_pace_key_splits_s3_path_style_buckets_only() -> None:
    assert pace_key("https://s3.amazonaws.com/grayfilestore-kwch/x.json") == (
        "s3.amazonaws.com/grayfilestore-kwch"
    )
    assert pace_key("https://s3.amazonaws.com/robots.txt") == "s3.amazonaws.com"
    assert pace_key("https://WWW.Example.TEST/a") == "www.example.test"
    assert pace_key("https://company-wide-tickers.s3.us-west-2.amazonaws.com/a/b") == (
        "company-wide-tickers.s3.us-west-2.amazonaws.com"
    )


def test_t18_pool_keeps_every_key_paced_and_single_flight(tmp_path: Path) -> None:
    stations, robots, hearst = world()
    assert len(stations) == 900
    assert len({pace_key(s.poll_url or "") for s in stations}) == 640
    server = Server(robots=robots)
    log = RequestLog()
    pool = make_pool(tmp_path, server, log=log)
    result = pool.run_pass(stations, read)

    assert result.counts() == {"empty": 900}
    assert sorted(server.pages()) == sorted(s.poll_url or "" for s in stations)
    assert server.overlaps == []  # never two in flight on one key, as the server saw it
    assert len(server.hits) == len(log.entries)  # every request went through the pacer
    assert violations(log.entries) == []
    assert min(entry.floor for entry in log.entries) >= FLOOR
    for host in hearst:
        starts = sorted(e.start for e in log.entries if e.key == host)
        assert len(starts) == 4  # robots.txt, then three pages
        assert all(b - a >= HEARST_DELAY for a, b in pairwise(starts[1:]))
    assert set(server.robots_reads().values()) == {1}
    assert sum(server.robots_reads().values()) == 640 - 111 + 1


def test_t18_a_stalled_host_delays_no_other_host(tmp_path: Path) -> None:
    stations = [
        station(f"synthetic-{i:03d}", f"https://h{i:03d}.example.test/c") for i in range(80)
    ]
    stalled = "https://h000.example.test/c"
    server = Server(stall={stalled: 1.2})  # 120 s, scaled
    pool = make_pool(tmp_path, server)
    began = time.monotonic()
    result = pool.run_pass(stations, read)

    stall_end = next(end for _, url, _, end in server.hits if url == stalled)
    others = [end for _, url, _, end in server.hits if url != stalled]
    assert stall_end - began >= 1.2
    assert max(others) < stall_end  # every other host finished while the one stalled
    assert result.counts() == {"empty": 80}


def test_t18_retry_after_defers_only_that_source(tmp_path: Path) -> None:
    slow = "https://shared.example.test/busy"
    answer = {slow: httpx.Response(429, headers={"Retry-After": "2.9"})}  # 290 s, scaled
    stations = [
        station("synthetic-busy", slow),
        station("synthetic-beside", "https://shared.example.test/calm"),
        station("synthetic-other", "https://other.example.test/calm"),
    ]
    pool = make_pool(tmp_path, Server(answer=answer), source_deadline=0.6)
    began = time.monotonic()
    result = pool.run_pass(stations, read)

    by_id = {item.source_id: item for item in result.sources}
    assert by_id["synthetic-busy"].outcome is Outcome.DEFERRED
    assert by_id["synthetic-busy"].retry_after == pytest.approx(2.9)
    assert by_id["synthetic-busy"].http_status == 429
    assert by_id["synthetic-beside"].outcome is Outcome.EMPTY
    assert by_id["synthetic-other"].outcome is Outcome.EMPTY
    assert time.monotonic() - began < 2.0  # nobody slept through the wait


def test_a_retry_within_the_deadline_is_waited_for(tmp_path: Path) -> None:
    url = "https://flaky.example.test/c"
    calls: list[str] = []

    def serve(request: httpx.Request) -> httpx.Response:
        if urlsplit(str(request.url)).path == "/robots.txt":
            return httpx.Response(404)
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(503, headers={"Retry-After": "0.1"})
        return httpx.Response(200, content=b"SYNTHETIC list")

    pool = make_pool(tmp_path, Server())
    pool.client = _client_factory(tmp_path, serve)
    result = pool.run_pass([station("synthetic-flaky", url)], read)
    assert [item.outcome for item in result.sources] == [Outcome.EMPTY]
    assert len(calls) == LIVE_ATTEMPTS


def _client_factory(
    tmp_path: Path, serve: Callable[[httpx.Request], httpx.Response]
) -> Callable[[], PoliteClient]:
    http = httpx.Client(transport=httpx.MockTransport(serve))
    store = ConditionalStore(tmp_path / "cache2")
    robots = RobotsStore(None)
    pacer = HostPacer()

    def client() -> PoliteClient:
        return PoliteClient(
            http, store, host_interval=FLOOR, attempts=LIVE_ATTEMPTS, pacer=pacer, robots=robots
        )

    return client


def test_the_pass_deadline_leaves_the_rest_late_and_starts_nothing_after(
    tmp_path: Path,
) -> None:
    stations = [
        station(f"synthetic-{i:02d}", f"https://long.example.test/c/{i}") for i in range(30)
    ]
    server = Server()
    pool = make_pool(tmp_path, server, pass_deadline=0.4)
    began = time.monotonic()
    result = pool.run_pass(stations, read)

    counts = result.counts()
    assert counts.get("late", 0) >= 20
    assert counts.get("empty", 0) >= 3
    assert all(start - began <= 0.4 + 0.05 for _, _, start, _ in server.hits)


def test_a_403_blocks_the_source(tmp_path: Path) -> None:
    url = "https://refusing.example.test/c"
    pool = make_pool(tmp_path, Server(answer={url: httpx.Response(403)}))
    result = pool.run_pass([station("synthetic-refused", url)], read)
    assert [(i.outcome, i.http_status) for i in result.sources] == [(Outcome.BLOCKED, 403)]


def test_lanes_go_longest_first_and_alerted_sources_first_in_a_lane() -> None:
    a = [station(f"synthetic-a{i}", f"https://a.example.test/{i}") for i in range(3)]
    b = [station(f"synthetic-b{i}", f"https://b.example.test/{i}") for i in range(2)]
    lanes = lanes_of([*b, *a], alerted=lambda s: s.id == "synthetic-a2")
    assert [[s.id for s in lane] for lane in lanes] == [
        ["synthetic-a2", "synthetic-a0", "synthetic-a1"],
        ["synthetic-b0", "synthetic-b1"],
    ]


def test_pacer_refuses_a_turn_after_the_deadline() -> None:
    pacer = HostPacer()
    with (
        pacer.slot("k", 0.0),
        pytest.raises(TimeoutError),
        pacer.slot("k", 0.0, deadline=time.monotonic() + 0.05),
    ):
        pass  # pragma: no cover - never reached
    with pytest.raises(TimeoutError), pacer.slot("k", 10.0, deadline=time.monotonic() + 1):
        pass  # pragma: no cover


def test_violations_name_overlaps_and_short_gaps() -> None:
    entries = [
        Request("k", 5.0, 0.0, 1.0),
        Request("k", 5.0, 0.5, 2.0),
        Request("j", 5.0, 0.0, 0.1),
        Request("j", 5.0, 5.0, 5.1),
    ]
    found = violations(entries)
    assert len(found) == 2
    assert all(line.startswith("k:") for line in found)


def test_classify_and_percentile() -> None:
    source = station("synthetic-x", "https://x.example.test/c")
    assert classify(RunResult(), source.id) == (Outcome.ERROR, None)
    result = RunResult(health=[health(source, HealthStatus.OK, 200)])
    assert classify(result, source.id) == (Outcome.OK, 200)
    result = RunResult(health=[health(source, HealthStatus.ERROR, 401)])
    assert classify(result, source.id) == (Outcome.BLOCKED, 401)
    result = RunResult(health=[health(source, HealthStatus.ERROR, 500)])
    assert classify(result, source.id) == (Outcome.ERROR, 500)
    assert percentile([], 0.95) == 0.0
    assert percentile([float(i) for i in range(1, 101)], 0.95) == 95.0
    assert percentile([3.0, 1.0, 2.0], 0.5) == 2.0


# T19: robots.txt -------------------------------------------------------------------------


class Ticker:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def clock(self) -> datetime:
        return self.now


@pytest.fixture
def robots_server() -> Server:
    return Server(robots={"https://site.example.test": b"User-agent: *\nCrawl-delay: 0.02\n"})


def test_t19_twenty_threads_read_robots_once(tmp_path: Path, robots_server: Server) -> None:
    store = RobotsStore(tmp_path / "robots.json")
    pool = make_pool(tmp_path, robots_server, robots=store)
    barrier = threading.Barrier(20)
    delays: list[float | None] = []

    def ask() -> None:
        client = pool.client()
        barrier.wait()
        delays.append(client.robots_for("https://site.example.test/a").crawl_delay("x"))

    threads = [threading.Thread(target=ask) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert robots_server.robots_reads() == Counter({"https://site.example.test": 1})
    assert delays == [0.02] * 20
    assert store.reads == Counter({"https://site.example.test": 1})


def test_t19_a_second_process_within_a_day_reads_no_robots(
    tmp_path: Path, robots_server: Server
) -> None:
    path = tmp_path / "state" / "robots.json"
    first = RobotsStore(path)
    pool = make_pool(tmp_path, robots_server, robots=first)
    sources = [station("synthetic-site", "https://site.example.test/c")]
    pool.run_pass(sources, read)
    assert sum(robots_server.robots_reads().values()) == 1
    assert path.exists()

    again = Server(robots=robots_server.robots)
    second = RobotsStore(path)
    assert second.fresh("https://site.example.test", datetime.now(UTC))
    make_pool(tmp_path, again, robots=second).run_pass(sources, read)
    assert again.robots_reads() == Counter()
    kept = second.get("https://site.example.test", datetime.now(UTC), _never)
    assert kept.crawl_delay("snowlight-pipeline") == 0.02
    assert kept.state is RobotsState.PARSED

    later = datetime.now(UTC) + timedelta(hours=24, minutes=1)
    assert not RobotsStore(path).fresh("https://site.example.test", later)


def _never() -> Robots:  # pragma: no cover - a kept verdict is never read again
    raise AssertionError("read again")


def test_t19_an_unreachable_robots_is_kept_a_day_and_written(tmp_path: Path) -> None:
    path = tmp_path / "robots.json"
    store = RobotsStore(path)
    ticker = Ticker(datetime(2026, 11, 16, 11, tzinfo=UTC))
    calls: list[str] = []

    def serve(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(503)

    client = PoliteClient(
        httpx.Client(transport=httpx.MockTransport(serve)),
        ConditionalStore(tmp_path / "cache"),
        host_interval=0.0,
        attempts=1,
        timing=Timing(clock=ticker.clock),
        robots=store,
        pacer=HostPacer(),
    )
    assert client.robots_for("https://down.example.test/a").state is RobotsState.UNREACHABLE
    assert client.robots_for("https://down.example.test/b").state is RobotsState.UNREACHABLE
    assert len(calls) == 1
    store.flush()
    assert RobotsStore(path).fresh("https://down.example.test", ticker.now)
    ticker.now += timedelta(hours=23)
    client.robots_for("https://down.example.test/c")
    assert len(calls) == 1
    ticker.now += timedelta(hours=1)
    client.robots_for("https://down.example.test/d")
    assert len(calls) == 2


def test_robots_store_survives_a_damaged_file(tmp_path: Path) -> None:
    path = tmp_path / "robots.json"
    path.write_text("{not json", encoding="utf-8")
    assert not RobotsStore(path).fresh("https://a.example.test", datetime.now(UTC))
    path.write_text(json.dumps({"version": 99, "origins": {}}), encoding="utf-8")
    assert not RobotsStore(path).fresh("https://a.example.test", datetime.now(UTC))
    path.write_text(
        json.dumps({"version": 1, "origins": {"https://a.example.test": {"state": "parsed"}}}),
        encoding="utf-8",
    )
    assert not RobotsStore(path).fresh("https://a.example.test", datetime.now(UTC))


def test_a_refusal_is_shared_by_every_client(tmp_path: Path) -> None:
    store = RobotsStore(None)
    pool = make_pool(
        tmp_path, Server(answer={"https://no.example.test/a": httpx.Response(403)}), robots=store
    )
    pool.run_pass([station("synthetic-no", "https://no.example.test/a")], read)
    other = pool.client()
    assert other.refused("https://no.example.test/b") == "https://no.example.test/a"


def test_a_read_that_raises_is_an_error_or_its_deadline(tmp_path: Path) -> None:
    busy = "https://busy.example.test/c"
    pool = make_pool(
        tmp_path,
        Server(answer={busy: httpx.Response(503, headers={"Retry-After": "2.9"})}),
        source_deadline=0.6,
    )

    def raising(source: Station, client: PoliteClient) -> RunResult:
        if source.id == "synthetic-broken":
            raise RuntimeError("SYNTHETIC adapter failure")
        client.fetch(source.poll_url or "")  # raises DeadlineError out of the read
        return RunResult()  # pragma: no cover

    result = pool.run_pass(
        [station("synthetic-broken", "https://x.example.test/c"), station("synthetic-busy", busy)],
        raising,
    )
    outcomes = {item.source_id: (item.outcome, item.retry_after) for item in result.sources}
    assert outcomes == {
        "synthetic-broken": (Outcome.ERROR, None),
        "synthetic-busy": (Outcome.DEFERRED, pytest.approx(2.9)),
    }


# A robots.txt that asks to wait (B1 of the S8-B review) -------------------------------

WAIT_ORIGIN = "https://waiting.example.test"
WAIT_PAGE = f"{WAIT_ORIGIN}/closings"


def read_like_s4(source: Station, client: PoliteClient) -> RunResult:
    """The SYNTHETIC read the way S4's ``_read_live`` reads: on a failed fetch it asks for
    the robots verdict again to record it."""
    result = RunResult()
    assert source.poll_url is not None
    try:
        fetched = client.fetch(source.poll_url)
    except FetchError as error:
        client.robots_verdict(source.poll_url)
        result.health.append(health(source, HealthStatus.ERROR, error.status))
        return result
    result.health.append(health(source, HealthStatus.EMPTY, fetched.status))
    return result


class Waiting:
    """A SYNTHETIC origin whose robots.txt answers 503 with ``Retry-After: 3600`` (36 s
    scaled), as one real station's did; its page answers 200."""

    def __init__(self) -> None:
        self.hits: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.hits.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(503, headers={"Retry-After": "36"})
        return httpx.Response(200, content=b"SYNTHETIC list")


def waiting_pool(server: Waiting, store: RobotsStore, ticker: Ticker, log: RequestLog) -> Pool:
    http = httpx.Client(transport=httpx.MockTransport(server))
    pacer = HostPacer(log=log)
    cache = ConditionalStore(Path(str(store.path)).parent / "cache")

    def client() -> PoliteClient:
        return PoliteClient(
            http,
            cache,
            host_interval=FLOOR,
            attempts=LIVE_ATTEMPTS,
            timing=Timing(clock=ticker.clock),
            pacer=pacer,
            robots=store,
            pace_key=pace_key,
        )

    return Pool(
        client=client, robots=store, pass_deadline=5.0, source_deadline=0.6, clock=ticker.clock
    )


def test_t19_a_robots_retry_after_is_kept_and_held_across_passes_and_processes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state" / "robots.json"
    ticker = Ticker(datetime(2026, 11, 16, 11, tzinfo=UTC))
    server = Waiting()
    log = RequestLog()
    sources = [station("synthetic-waiting", WAIT_PAGE)]

    store = RobotsStore(path)
    first = waiting_pool(server, store, ticker, log)
    for left in (36, 26):  # two passes of one process, 10 s apart
        result = first.run_pass(sources, read_like_s4)
        assert [(i.outcome, i.http_status) for i in result.sources] == [(Outcome.DEFERRED, 503)]
        assert result.sources[0].retry_after == pytest.approx(left, abs=1)
        ticker.now += timedelta(seconds=10)
    assert server.hits == ["/robots.txt"]  # one request, and no page while the wait lasts

    kept = json.loads(path.read_text(encoding="utf-8"))
    assert kept["origins"][WAIT_ORIGIN]["state"] == RobotsState.UNREACHABLE.value
    assert kept["held"][WAIT_ORIGIN] == "2026-11-16T11:00:36+00:00"

    later = RequestLog()  # a second process: its own pacer and log
    second = waiting_pool(server, RobotsStore(path), ticker, later)
    assert second.run_pass(sources, read_like_s4).counts() == {"deferred": 1}
    assert server.hits == ["/robots.txt"]

    ticker.now += timedelta(seconds=20)  # the wait is over; the verdict is kept a day
    assert second.run_pass(sources, read_like_s4).counts() == {"empty": 1}
    assert server.hits == ["/robots.txt", "/closings"]
    assert robots_requests([*log.entries, *later.entries]) == Counter({WAIT_ORIGIN: 1})
    assert violations(log.entries) == violations(later.entries) == []


def test_a_robots_retry_after_inside_a_source_stops_it_without_more_requests(
    tmp_path: Path,
) -> None:
    server = Waiting()
    store = RobotsStore(tmp_path / "robots.json")
    log = RequestLog()
    client = waiting_pool(server, store, Ticker(datetime.now(UTC)), log).client()
    client.deadline = time.monotonic() + 0.6
    with pytest.raises(DeadlineError) as stopped:
        client.fetch(WAIT_PAGE)
    assert stopped.value.kind == "deferred"
    with pytest.raises(DeadlineError):
        client.robots_verdict(WAIT_PAGE)  # S4 asks again after a failed fetch: held
    with pytest.raises(DeadlineError):
        client.fetch("https://elsewhere.example.test/c")  # stopped: nothing more starts
    assert server.hits == ["/robots.txt"]
    assert store.known(WAIT_ORIGIN) is not None
    assert store.reads == Counter({WAIT_ORIGIN: 1})


def test_a_robots_read_stopped_after_its_request_is_kept_unreachable(tmp_path: Path) -> None:
    """A robots.txt 503 without Retry-After whose backoff passes the deadline was asked:
    it is kept a day as unreachable, not asked again next pass."""
    hits: list[str] = []

    def serve(request: httpx.Request) -> httpx.Response:
        hits.append(request.url.path)
        return httpx.Response(503)

    store = RobotsStore(None)
    client = PoliteClient(
        httpx.Client(transport=httpx.MockTransport(serve)),
        ConditionalStore(tmp_path / "cache"),
        host_interval=FLOOR,
        attempts=LIVE_ATTEMPTS,
        pacer=HostPacer(),
        robots=store,
    )
    client.deadline = time.monotonic() + 0.5  # the 2 s backoff would pass it
    assert client.robots_for("https://down.example.test/a").state is RobotsState.UNREACHABLE
    assert client.stopped is not None
    assert client.stopped.kind == "late"
    with pytest.raises(DeadlineError):
        client.fetch("https://down.example.test/a")  # the source stays stopped
    assert hits == ["/robots.txt"]
    client.stopped = None
    client.deadline = time.monotonic() + 0.5
    assert client.robots_for("https://down.example.test/b").state is RobotsState.UNREACHABLE
    assert hits == ["/robots.txt"]


def test_a_robots_refresh_keeps_the_known_crawl_delay(tmp_path: Path) -> None:
    ticker = Ticker(datetime(2026, 11, 16, 11, tzinfo=UTC))
    log = RequestLog()
    server = Server(robots={"https://slow.example.test": b"User-agent: *\nCrawl-delay: 0.1\n"})
    client = PoliteClient(
        httpx.Client(transport=httpx.MockTransport(server)),
        ConditionalStore(tmp_path / "cache"),
        host_interval=FLOOR,
        attempts=LIVE_ATTEMPTS,
        timing=Timing(clock=ticker.clock),
        pacer=HostPacer(log=log),
        robots=RobotsStore(None),
    )
    client.fetch("https://slow.example.test/a")
    ticker.now += timedelta(hours=25)
    client.robots_for("https://slow.example.test/b")  # the day is over: read again
    assert [(e.robots, e.floor) for e in log.entries] == [
        (True, FLOOR),  # nothing known yet
        (False, HEARST_DELAY),
        (True, HEARST_DELAY),
    ]
    assert violations(log.entries) == []


def test_violations_hold_every_request_to_the_keys_highest_floor() -> None:
    entries = [
        Request("k", 10.0, 0.0, 0.1),
        Request("k", 5.0, 6.0, 6.1, robots=True),  # a refresh 6 s after a 10 s page
    ]
    assert violations(entries) == ["k: starts 6.000 s apart under a 10.0 s floor"]


def test_an_answer_still_coming_at_the_deadline_is_cut_off(tmp_path: Path) -> None:
    def trickle() -> Iterator[bytes]:
        for _ in range(100):
            time.sleep(0.05)
            yield b"SYNTHETIC "

    def serve(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, content=trickle())

    client = PoliteClient(
        httpx.Client(transport=httpx.MockTransport(serve)),
        ConditionalStore(tmp_path / "cache"),
        host_interval=0.0,
        attempts=LIVE_ATTEMPTS,
        pacer=HostPacer(),
        robots=RobotsStore(None),
    )
    began = time.monotonic()
    client.deadline = began + 0.2
    with pytest.raises(DeadlineError) as stopped:
        client.fetch("https://trickle.example.test/c")
    assert stopped.value.kind == "late"
    assert time.monotonic() - began < 0.2 + REQUEST_GRACE + 0.3  # not the 5 s it would take


def test_a_robots_read_counts_once_with_its_retry_and_redirect_hop(tmp_path: Path) -> None:
    calls: list[str] = []

    def serve(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/robots.txt":
            if calls.count("/robots.txt") == 1:
                return httpx.Response(503, headers={"Retry-After": "0"})
            return httpx.Response(301, headers={"Location": "/real-robots.txt"})
        return httpx.Response(200, content=b"User-agent: *\nAllow: /\n")

    log = RequestLog()
    client = PoliteClient(
        httpx.Client(transport=httpx.MockTransport(serve)),
        ConditionalStore(tmp_path / "cache"),
        host_interval=0.0,
        attempts=LIVE_ATTEMPTS,
        pacer=HostPacer(log=log),
        robots=RobotsStore(None),
    )
    assert client.robots_for("https://hops.example.test/a").state is RobotsState.PARSED
    assert calls == ["/robots.txt", "/robots.txt", "/real-robots.txt"]
    assert [(e.robots, e.follow) for e in log.entries] == [
        (True, False),
        (True, True),
        (True, True),
    ]
    assert robots_reads(log.entries) == Counter({"https://hops.example.test": 1})
    assert robots_requests(log.entries) == Counter({"https://hops.example.test": 3})


def test_a_stopped_robots_read_leaves_the_worker_free_for_the_next_origin(
    tmp_path: Path,
) -> None:
    """One worker's robots.txt read that its server deferred must not skip the next
    origin's read up front (a stale stop made a real cold sweep read robots.txt inside
    every lane and take 200 s instead of about 80 s)."""
    hits: list[str] = []
    other = "https://zeta.example.test"

    def serve(request: httpx.Request) -> httpx.Response:
        hits.append(f"{request.url.host}{request.url.path}")
        if request.url.host == "waiting.example.test":
            return httpx.Response(503, headers={"Retry-After": "36"})
        return httpx.Response(200, content=b"User-agent: *\nAllow: /\n")

    store = RobotsStore(tmp_path / "robots.json")
    ticker = Ticker(datetime(2026, 11, 16, 11, tzinfo=UTC))
    http = httpx.Client(transport=httpx.MockTransport(serve))
    cache = ConditionalStore(tmp_path / "cache")
    pacer = HostPacer(log=RequestLog())

    def client() -> PoliteClient:
        return PoliteClient(
            http,
            cache,
            host_interval=FLOOR,
            attempts=LIVE_ATTEMPTS,
            timing=Timing(clock=ticker.clock),
            pacer=pacer,
            robots=store,
            pace_key=pace_key,
        )

    pool = Pool(client=client, robots=store, workers=1, clock=ticker.clock)
    end = time.monotonic() + 5.0
    pool._robots_first(WAIT_PAGE, end)
    pool._robots_first(f"{other}/closings", end)
    assert hits == ["waiting.example.test/robots.txt", "zeta.example.test/robots.txt"]
    assert store.fresh(other, ticker.clock())
    assert pool._worker_client().stopped is None

    sources = [station("synthetic-waiting", WAIT_PAGE), station("synthetic-z", f"{other}/c")]
    result = pool.run_pass(sources, read_like_s4)
    assert sorted((i.source_id, i.outcome) for i in result.sources) == [
        ("synthetic-waiting", Outcome.DEFERRED),
        ("synthetic-z", Outcome.EMPTY),
    ]
    assert pool._worker_client().stopped is None
    assert hits[2:] == ["zeta.example.test/c"]  # nothing more asked of the waiting origin
