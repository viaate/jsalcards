"""S8-B should-fix items (live reader politeness and alert windows) on SYNTHETIC hosts.

Time is scaled as in ``test_pool``: the 5 s floor is 50 ms and a Crawl-delay of 10 s is
100 ms here.
"""

import json
import socket
import threading
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import pairwise
from pathlib import Path

import httpx
import pytest

from snowlight.live.cadence import Cadence, alert_counties
from snowlight.live.ledger import Outcome
from snowlight.live.pool import (
    LIVE_ATTEMPTS,
    HostPacer,
    Pool,
    RequestLog,
    RobotsStore,
    _robots_json,
    pace_key,
    violations,
)
from snowlight.live.reads import due_sources, keep_pass
from snowlight.live.sweep import sweep_plan
from snowlight.sources.nws.vtec import ENDING_ACTIONS
from snowlight.sources.stations.fetch import RunResult
from snowlight.sources.stations.http import (
    REQUEST_GRACE,
    ConditionalStore,
    DeadlineError,
    FetchError,
    PoliteClient,
    Timing,
    _Cutoff,
)
from snowlight.sources.stations.model import HealthStatus, SourceHealth
from snowlight.sources.stations.registry import Station, load_registry
from snowlight.sources.stations.robots import Robots, RobotsState
from snowlight.weather import live as weather_live

SCALE = 0.01
FLOOR = 5 * SCALE
DELAY = 10 * SCALE
NOW = datetime(2026, 11, 16, 11, tzinfo=UTC)
HOST = "https://hearst.example.test"
DELAYED = b"User-agent: *\nCrawl-delay: 0.1\nDisallow: /private/\n"


class Ticker:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def clock(self) -> datetime:
        return self.now


def station(source_id: str, url: str) -> Station:
    """A SYNTHETIC station polled at ``url``."""
    body = {
        "id": source_id,
        "platform": "synthetic",
        "call_sign": "SYNT",
        "name": "SYNTHETIC station",
        "market": "SYNTHETIC market",
        "dma": None,
        "states": ["KS"],
        "counties": {"basis": "dma", "source": "SYNTHETIC", "fips": ["20091"]},
        "page_url": url,
        "data_url": None,
        "archive_urls": [],
        "poll_minutes": None,
        "status": "active",
        "evidence": "SYNTHETIC",
    }
    return Station.model_validate_json(json.dumps(body))


def read(source: Station, client: PoliteClient) -> RunResult:
    """The SYNTHETIC source read: one page through the polite client."""
    result = RunResult()
    assert source.poll_url is not None
    try:
        fetched = client.fetch(source.poll_url)
    except FetchError as error:
        status: HealthStatus = HealthStatus.ERROR
        code = error.status
    else:
        status, code = HealthStatus.EMPTY, fetched.status
    result.health.append(
        SourceHealth.model_validate(
            {
                "source_id": source.id,
                "url": source.poll_url,
                "checked_at": NOW,
                "rows": 0,
                "status": status,
                "http_status": code,
                "reason": "SYNTHETIC" if status is HealthStatus.ERROR else None,
            }
        )
    )
    return result


def pool_on(  # noqa: PLR0913 - the parts a test sets
    tmp_path: Path,
    serve: Callable[[httpx.Request], httpx.Response],
    store: RobotsStore,
    ticker: Ticker,
    log: RequestLog,
    *,
    source_deadline: float = 10.0,
) -> Pool:
    http = httpx.Client(transport=httpx.MockTransport(serve))
    cache = ConditionalStore(tmp_path / "cache")
    pacer = HostPacer(log=log)

    def client() -> PoliteClient:
        return PoliteClient(
            http,
            cache,
            host_interval=FLOOR,
            attempts=LIVE_ATTEMPTS,
            timing=Timing(clock=ticker.clock, sleep=lambda _seconds: None),
            pacer=pacer,
            robots=store,
            pace_key=pace_key,
        )

    return Pool(
        client=client,
        robots=store,
        pass_deadline=60.0,
        source_deadline=source_deadline,
        clock=ticker.clock,
    )


def kept_file(path: Path, read_at: datetime, body: bytes = DELAYED) -> None:
    document = {
        "version": 1,
        "origins": {HOST: _robots_json(read_at, Robots.from_bytes(body))},
        "held": {},
    }
    path.write_text(json.dumps(document), encoding="utf-8")


# S2: a failed daily robots.txt refresh keeps the last file read ---------------------------


def test_a_failed_robots_refresh_keeps_the_known_crawl_delay_for_every_page(
    tmp_path: Path,
) -> None:
    path = tmp_path / "robots.json"
    kept_file(path, NOW - timedelta(hours=25))  # a day old: refreshed this pass
    hits: list[str] = []

    def serve(request: httpx.Request) -> httpx.Response:
        hits.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(503)  # down for the refresh, both attempts
        return httpx.Response(200, content=b"SYNTHETIC list")

    log = RequestLog()
    pool = pool_on(tmp_path, serve, RobotsStore(path), Ticker(NOW), log)
    sources = [station(f"synthetic-{name}", f"{HOST}/{name}") for name in "abc"]
    assert pool.run_pass(sources, read).counts() == {"empty": 3}

    assert hits.count("/robots.txt") == LIVE_ATTEMPTS  # one read, its retry
    pages = sorted((e for e in log.entries if not e.robots), key=lambda e: e.start)
    assert [e.floor for e in pages] == [DELAY] * 3  # not the 5 s floor
    assert all(b.start - a.start >= DELAY - 1e-6 for a, b in pairwise(pages))
    assert violations(log.entries) == []

    origin = json.loads(path.read_text(encoding="utf-8"))["origins"][HOST]
    assert origin["state"] == RobotsState.PARSED.value
    assert origin["groups"][0]["crawl_delay"] == 0.1
    assert origin["read_at"] == NOW.isoformat()  # asked today: not asked again for a day
    assert origin["content_read_at"] == (NOW - timedelta(hours=25)).isoformat()
    again = RobotsStore(path)  # the next process
    assert again.fresh(HOST, NOW)
    known = again.known(HOST)
    assert known is not None
    assert known.crawl_delay("snowlight-pipeline") == 0.1
    assert known.decide(f"{HOST}/private/x", "snowlight-pipeline")[0] is False  # its rules


def test_a_failed_refresh_stands_in_for_30_days_after_the_file_was_read(tmp_path: Path) -> None:
    path = tmp_path / "robots.json"
    read_at = NOW - timedelta(days=28)
    kept_file(path, read_at)
    down = Robots.for_status(503)
    store = RobotsStore(path)
    assert store.get(HOST, NOW, lambda: down).state is RobotsState.PARSED
    store.flush()
    store = RobotsStore(path)  # kept across processes, from the file's own read time
    later = NOW + timedelta(days=1)
    assert store.get(HOST, later, lambda: down).state is RobotsState.PARSED
    store.flush()
    assert json.loads(path.read_text())["origins"][HOST]["content_read_at"] == read_at.isoformat()

    past = read_at + timedelta(days=31)  # older than 30 days: unreachable stands
    assert RobotsStore(path).get(HOST, past, lambda: down).state is RobotsState.UNREACHABLE

    fresh = RobotsStore(path)  # a file read again replaces it and its date
    store.get(HOST, past, lambda: Robots.from_bytes(b"User-agent: *\n"))
    store.flush()
    assert "content_read_at" not in json.loads(path.read_text())["origins"][HOST]
    assert fresh.known(HOST) is not None


def test_a_404_refresh_replaces_the_known_file(tmp_path: Path) -> None:
    """A file the site took down (4xx) is an answer, not a failure: unrestricted."""
    path = tmp_path / "robots.json"
    kept_file(path, NOW - timedelta(hours=25))
    store = RobotsStore(path)
    assert store.get(HOST, NOW, lambda: Robots.for_status(404)).state is RobotsState.UNAVAILABLE


def test_a_robots_429_stopped_by_the_deadline_keeps_the_known_file(tmp_path: Path) -> None:
    path = tmp_path / "robots.json"
    kept_file(path, NOW - timedelta(hours=25))

    def serve(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "3600"})

    store = RobotsStore(path)
    client = PoliteClient(
        httpx.Client(transport=httpx.MockTransport(serve)),
        ConditionalStore(tmp_path / "cache"),
        host_interval=FLOOR,
        attempts=LIVE_ATTEMPTS,
        timing=Timing(clock=Ticker(NOW).clock),
        pacer=HostPacer(),
        robots=store,
    )
    client.deadline = time.monotonic() + 0.5
    robots = client.robots_for(f"{HOST}/a")
    assert client.stopped is not None
    assert client.stopped.kind == "deferred"
    assert robots.state is RobotsState.PARSED
    assert robots.crawl_delay("snowlight-pipeline") == 0.1
    assert store.held(HOST, NOW) is not None


# S4: the alert boost follows VTEC CAN, EXP and UPG as the map does -------------------------


def alerts_feed(*alerts: Mapping[str, object]) -> bytes:
    """A SYNTHETIC /alerts/active body."""
    features = []
    for alert in alerts:
        props = {
            "status": "Actual",
            "messageType": "Update",
            "event": "Winter Storm Warning",
            "expires": "2026-11-17T18:00:00+00:00",
            "ends": None,
            "geocode": {"SAME": ["020091"]},
            **alert,
        }
        features.append({"type": "Feature", "properties": props})
    return json.dumps({"type": "FeatureCollection", "features": features}).encode()


def vtec(action: str, kind: str = "WS.W") -> dict[str, object]:
    return {"parameters": {"VTEC": [f"/O.{action}.KTOP.{kind}.0004.000000T0000Z-261117T1800Z/"]}}


def test_cancelled_and_upgraded_alerts_end_the_boost() -> None:
    for action in ("CAN", "UPG"):
        assert alert_counties(alerts_feed(vtec(action)), NOW) == frozenset(), action
    for action in ("NEW", "CON", "EXT", "EXA", "EXB", "COR", "EXP"):
        assert alert_counties(alerts_feed(vtec(action)), NOW) == {"20091"}, action
    assert alert_counties(alerts_feed({}), NOW) == {"20091"}  # no VTEC: by its times


def test_an_expiring_alert_keeps_the_boost_until_its_end_time() -> None:
    # SYNTHETIC: NOW is 2026-11-16T11:00Z.
    running = vtec("EXP")  # VTEC end 2026-11-17T18:00Z: 31 hours to run
    assert alert_counties(alerts_feed(running), NOW) == {"20091"}
    assert alert_counties(alerts_feed(running), NOW + timedelta(hours=31)) == frozenset()
    over = {"parameters": {"VTEC": ["/O.EXP.KTOP.WS.W.0004.000000T0000Z-261116T1000Z/"]}}
    assert alert_counties(alerts_feed(over), NOW) == frozenset()  # by its VTEC end
    ends_later = {"ends": "2026-11-16T12:00:00+00:00", **over}
    assert alert_counties(alerts_feed(ends_later), NOW) == {"20091"}  # ends wins
    assert alert_counties(alerts_feed(ends_later), NOW + timedelta(hours=1)) == frozenset()


def test_cadence_ends_alerts_on_the_actions_the_map_drops() -> None:
    assert weather_live._ENDING_ACTIONS == ENDING_ACTIONS == {"CAN", "UPG"}


def test_an_upgrade_moves_the_boost_to_the_upgraded_alerts_counties() -> None:
    watch = {
        "event": "Winter Storm Watch",
        "geocode": {"SAME": ["020091", "020045"]},
        **vtec("UPG", "WS.A"),
    }
    warning = {"messageType": "Alert", "geocode": {"SAME": ["020045"]}, **vtec("NEW")}
    assert alert_counties(alerts_feed(watch, warning), NOW) == {"20045"}
    mixed = {  # one segment: the advisory expires as the warning starts
        "parameters": {
            "VTEC": [
                "/O.EXP.KTOP.WW.Y.0010.000000T0000Z-261116T1200Z/",
                "/O.NEW.KTOP.WS.W.0005.261116T1200Z-261117T1800Z/",
            ]
        }
    }
    assert alert_counties(alerts_feed(mixed), NOW) == {"20091"}


def test_an_alert_a_later_one_replaced_no_longer_counts() -> None:
    first = {"id": "urn:oid:synthetic.1", "geocode": {"SAME": ["020091", "020045"]}}
    cancel = {
        "id": "urn:oid:synthetic.2",
        "geocode": {"SAME": ["020091"]},
        "references": [{"identifier": "urn:oid:synthetic.1"}],
        **vtec("CAN"),
    }
    keep = {
        "id": "urn:oid:synthetic.3",
        "geocode": {"SAME": ["020045"]},
        "references": [{"identifier": "urn:oid:synthetic.1"}],
        **vtec("CON"),
    }
    assert alert_counties(alerts_feed(first, cancel, keep), NOW) == {"20045"}
    test_only = {**cancel, "status": "Test"}  # a test message replaces nothing
    assert alert_counties(alerts_feed(first, test_only), NOW) == {"20091", "20045"}


# S3: a slow body ends at the deadline, not a read timeout later ---------------------------


class Trickle(BaseHTTPRequestHandler):
    """A SYNTHETIC page that sends one byte every 1.2 s: each read is inside the read
    timeout, so only the deadline can end it."""

    def do_GET(self) -> None:
        if self.path == "/robots.txt":
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", "10")
        self.end_headers()
        try:
            for _ in range(10):
                self.wfile.write(b"x")
                self.wfile.flush()
                time.sleep(1.2)
        except OSError:
            pass  # the client hung up

    def log_message(self, *_args: object) -> None:
        return


def test_a_trickling_body_is_cut_at_its_deadline(tmp_path: Path) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Trickle)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = PoliteClient(
            httpx.Client(trust_env=False),
            ConditionalStore(tmp_path / "cache"),
            host_interval=0.0,
            attempts=LIVE_ATTEMPTS,
            pacer=HostPacer(),
            robots=RobotsStore(None),
        )
        url = f"http://127.0.0.1:{server.server_address[1]}/closings"
        began = time.monotonic()
        client.deadline = began + 0.3
        with pytest.raises(DeadlineError) as stopped:
            client.fetch(url)
        took = time.monotonic() - began
    finally:
        server.shutdown()
        server.server_close()
    assert stopped.value.kind == "late"
    assert client.stopped is stopped.value
    # The deadline and its grace (1.3 s), not the next byte after them (2.4 s).
    assert took < 0.3 + REQUEST_GRACE + 0.5


class TrickleHead(BaseHTTPRequestHandler):
    """A SYNTHETIC server that keeps its connections open (HTTP/1.1) and sends a page's
    status line and headers one byte every 0.25 s: only the deadline can end the wait."""

    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        if self.path == "/robots.txt":
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        head = b"HTTP/1.1 200 OK\r\nX-Synthetic: " + b"a" * 40 + b"\r\nContent-Length: 1\r\n\r\nx"
        try:
            for byte in head:
                self.wfile.write(bytes([byte]))
                self.wfile.flush()
                time.sleep(0.25)
        except OSError:
            pass  # the client hung up
        self.close_connection = True

    def log_message(self, *_args: object) -> None:
        return


def test_trickling_headers_are_cut_at_the_deadline(tmp_path: Path) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), TrickleHead)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = PoliteClient(
            httpx.Client(trust_env=False),
            ConditionalStore(tmp_path / "cache"),
            host_interval=0.0,
            attempts=LIVE_ATTEMPTS,
            pacer=HostPacer(),
            robots=RobotsStore(None),
        )
        url = f"http://127.0.0.1:{server.server_address[1]}/closings"
        began = time.monotonic()
        client.deadline = began + 0.3  # robots.txt is read first, on a kept-alive server
        with pytest.raises(DeadlineError) as stopped:
            client.fetch(url)
        took = time.monotonic() - began
    finally:
        server.shutdown()
        server.server_close()
    assert stopped.value.kind == "late"
    # The deadline and its grace (1.3 s), not the whole header (about 18 s).
    assert took < 0.3 + REQUEST_GRACE + 0.5


def test_a_finished_request_is_never_cut() -> None:
    near, far = socket.socketpair()

    class Stream:
        def get_extra_info(self, name: str) -> object:
            return near if name == "socket" else None

    try:
        cut = _Cutoff(60.0)
        cut.trace("connection.connect_tcp.complete", {"return_value": Stream()})
        cut.finish()
        cut._fire()  # the timer firing just after the last chunk
        assert not cut.fired
        far.sendall(b"x")
        assert near.recv(1) == b"x"  # the connection is still open
        cut = _Cutoff(0.0)
        cut.trace("connection.connect_tcp.complete", {"return_value": Stream()})
        time.sleep(0.2)
        assert cut.fired
        assert near.recv(1) == b""  # shut when the time was up
        cut.finish()
    finally:
        near.close()
        far.close()


# S5: sources that share one file read it once a pass -----------------------------------------

TICKER = "https://company-wide-tickers.example.test/KULR_School_Results/closings.html"


def test_sources_sharing_one_file_read_it_once_a_pass(tmp_path: Path) -> None:
    hits: list[str] = []

    def serve(request: httpx.Request) -> httpx.Response:
        hits.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, content=b"SYNTHETIC list")

    log = RequestLog()
    pool = pool_on(tmp_path, serve, RobotsStore(None), Ticker(NOW), log)
    sources = [station(f"synthetic-cowles-{n}", TICKER) for n in range(5)]
    sources.append(station("synthetic-other", "https://company-wide-tickers.example.test/b"))
    for _ in range(2):
        assert pool.run_pass(sources, read).counts() == {"empty": 6}
    pages = [url for url in hits if not url.endswith("/robots.txt")]
    assert pages.count(TICKER) == 2  # once in each pass, for all five
    assert violations(log.entries) == []
    assert len(log.entries) == len(hits)  # every request paced


def test_a_shared_file_that_failed_is_not_asked_again_in_the_pass(tmp_path: Path) -> None:
    hits: list[str] = []

    def serve(request: httpx.Request) -> httpx.Response:
        hits.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(503)

    pool = pool_on(tmp_path, serve, RobotsStore(None), Ticker(NOW), RequestLog())
    sources = [station(f"synthetic-cowles-{n}", TICKER) for n in range(5)]
    result = pool.run_pass(sources, read)
    assert [(i.outcome, i.http_status) for i in result.sources] == [(Outcome.ERROR, 503)] * 5
    assert hits.count("/KULR_School_Results/closings.html") == LIVE_ATTEMPTS


def test_a_shared_file_that_asked_for_a_wait_is_not_asked_again_in_the_pass(
    tmp_path: Path,
) -> None:
    hits: list[str] = []

    def serve(request: httpx.Request) -> httpx.Response:
        hits.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(503, headers={"Retry-After": "290"})

    ticker = Ticker(NOW)
    pool = pool_on(tmp_path, serve, RobotsStore(None), ticker, RequestLog(), source_deadline=2.0)
    sources = [station(f"synthetic-cowles-{n}", TICKER) for n in range(5)]
    result = pool.run_pass(sources, read)
    assert hits.count("/KULR_School_Results/closings.html") == 1
    assert [(i.outcome, i.retry_after) for i in result.sources] == [(Outcome.DEFERRED, 290)] * 5
    cadence = Cadence({s.id: s for s in sources}, {}, lambda _: 30, path=tmp_path / "cadence.json")
    keep_pass(cadence, result)
    for source in sources:
        until = cadence.held_until(source.id, NOW)
        assert until is not None
        assert until >= NOW + timedelta(seconds=290)


def test_a_shared_file_still_arriving_at_the_deadline_is_not_asked_again(
    tmp_path: Path,
) -> None:
    hits: list[str] = []

    def serve(request: httpx.Request) -> httpx.Response:
        hits.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        time.sleep(REQUEST_GRACE + 0.4)  # past the deadline and its grace
        return httpx.Response(200, content=b"SYNTHETIC list")

    pool = pool_on(
        tmp_path, serve, RobotsStore(None), Ticker(NOW), RequestLog(), source_deadline=0.2
    )
    sources = [station(f"synthetic-cowles-{n}", TICKER) for n in range(5)]
    result = pool.run_pass(sources, read)
    assert hits.count("/KULR_School_Results/closings.html") == 1
    assert result.counts() == {"late": 5}


# S1: a later sweep keeps the saved waits ----------------------------------------------------


def test_a_later_sweep_never_asks_a_source_before_its_retry_after_ends(tmp_path: Path) -> None:
    registry = load_registry()
    waiting, other = "cowles-kulr", sorted(due_sources(registry) - {"cowles-kulr"})[0]
    busy = registry.stations[waiting].poll_url or ""
    hits: list[str] = []

    def serve(request: httpx.Request) -> httpx.Response:
        hits.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if str(request.url) == busy:
            return httpx.Response(503, headers={"Retry-After": "290"})
        return httpx.Response(200, content=b"SYNTHETIC list")

    state = tmp_path / "state"
    state.mkdir()
    ticker = Ticker(NOW)

    def sweep() -> dict[str, datetime]:
        cadence, due, held = sweep_plan(registry, [waiting, other], state, ticker.now)
        log = RequestLog()  # each sweep is its own process: its own pool and log
        pool = pool_on(
            tmp_path, serve, RobotsStore(state / "robots.json"), ticker, log, source_deadline=0.6
        )
        keep_pass(cadence, pool.run_pass(due, read))
        return held

    assert sweep() == {}
    assert hits.count(busy) == 1  # asked once, told to wait 290 s: deferred
    ticker.now += timedelta(seconds=60)
    held = sweep()
    assert list(held) == [waiting]
    assert NOW + timedelta(seconds=290) <= held[waiting] <= NOW + timedelta(seconds=300)
    assert hits.count(busy) == 1  # not asked by the later sweep
    ticker.now = held[waiting]
    assert sweep() == {}
    assert hits.count(busy) == 2  # asked again once the wait is over
