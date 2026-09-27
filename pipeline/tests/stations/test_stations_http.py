"""PoliteClient: robots.txt verdicts, pacing, conditional requests, retries and redirects.

robots.txt is read for every URL and its verdict returned with the body, but a
disallowed URL is read all the same: the project owner decided on 2026-09-26 to
read closings pages and list files even where robots.txt disallows them.

Every server here is synthetic (an in-memory httpx transport); no station is contacted.
"""

import gzip
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from snowlight.sources.stations.http import (
    MAX_BODY,
    USER_AGENT,
    ConditionalStore,
    FetchError,
    PoliteClient,
    Timing,
)

type Handler = Callable[[httpx.Request], httpx.Response]


class Clock:
    """A fake wall clock and monotonic clock that only move when slept."""

    def __init__(self) -> None:
        self.now = datetime(2026, 1, 21, 12, 0, tzinfo=UTC)
        self.mono = 1000.0
        self.slept: list[float] = []

    def wall(self) -> datetime:
        return self.now

    def monotonic(self) -> float:
        return self.mono

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.mono += seconds
        self.now += timedelta(seconds=seconds)


def make(
    tmp_path: Path, handler: Handler, clock: Clock, *, host_interval: float = 5.0
) -> PoliteClient:
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, headers={"User-Agent": USER_AGENT})
    return PoliteClient(
        client,
        ConditionalStore(tmp_path / "store"),
        timing=Timing(clock=clock.wall, monotonic=clock.monotonic, sleep=clock.sleep),
        host_interval=host_interval,
    )


def robots_ok(body: bytes = b"User-agent: *\nDisallow: /private\n") -> httpx.Response:
    return httpx.Response(200, content=body)


def test_disallowed_url_is_read_and_its_verdict_recorded(tmp_path: Path) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/robots.txt":
            return robots_ok()
        return httpx.Response(200, text="list")

    client = make(tmp_path, handler, Clock())
    fetched = client.fetch("https://station.test/private/closings")
    assert fetched.body == b"list"
    assert seen == ["/robots.txt", "/private/closings"]
    (verdict,) = fetched.robots
    assert verdict.url == "https://station.test/private/closings"
    assert verdict.state.value == "parsed"
    assert not verdict.allowed
    assert "Disallow: /private" in verdict.rule
    allowed = client.fetch("https://station.test/closings").robots[0]
    assert allowed.allowed


def test_user_agent_names_the_repository(tmp_path: Path) -> None:
    agents: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        agents.append(request.headers["User-Agent"])
        return robots_ok() if request.url.path == "/robots.txt" else httpx.Response(200, text="x")

    make(tmp_path, handler, Clock()).fetch("https://station.test/closings")
    assert agents == [USER_AGENT, USER_AGENT]
    assert "github.com/viaate/jsalcards" in USER_AGENT


def test_conditional_request_reuses_the_stored_body(tmp_path: Path) -> None:
    conditions: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return robots_ok()
        conditions.append(request.headers.get("If-None-Match"))
        if request.headers.get("If-None-Match") == '"v1"':
            return httpx.Response(304, headers={"ETag": '"v1"'})
        return httpx.Response(
            200,
            content=b"[1]",
            headers={"ETag": '"v1"', "Last-Modified": "Wed, 21 Jan 2026 11:00:00 GMT"},
        )

    client = make(tmp_path, handler, Clock())
    first = client.fetch("https://station.test/closings.json")
    second = client.fetch("https://station.test/closings.json")
    assert conditions == [None, '"v1"']
    assert not first.not_modified
    assert second.not_modified
    assert second.body == b"[1]"
    assert second.sha256 == first.sha256


def test_corrupt_stored_body_is_not_used(tmp_path: Path) -> None:
    conditions: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return robots_ok()
        conditions.append(request.headers.get("If-None-Match"))
        return httpx.Response(200, content=b"[2]", headers={"ETag": '"v2"'})

    client = make(tmp_path, handler, Clock())
    client.fetch("https://station.test/c.json")
    for body in (tmp_path / "store" / "station.test").glob("*.body"):
        body.write_bytes(b"tampered")
    client.fetch("https://station.test/c.json")
    assert conditions == [None, None]


def test_retries_with_backoff_then_succeeds(tmp_path: Path) -> None:
    answers = [503, 502, 200]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return robots_ok()
        return httpx.Response(answers.pop(0), content=b"ok")

    clock = Clock()
    fetched = make(tmp_path, handler, clock, host_interval=0.0).fetch("https://s.test/c")
    assert fetched.body == b"ok"
    assert clock.slept == [2.0, 4.0]


def test_retry_after_is_honoured(tmp_path: Path) -> None:
    answers = [httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, text="y")]

    def handler(request: httpx.Request) -> httpx.Response:
        return robots_ok() if request.url.path == "/robots.txt" else answers.pop(0)

    clock = Clock()
    make(tmp_path, handler, clock, host_interval=0.0).fetch("https://s.test/c")
    assert clock.slept == [7.0]


def test_long_retry_after_gives_up(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return robots_ok()
        return httpx.Response(503, headers={"Retry-After": "3600"})

    with pytest.raises(FetchError, match="asked to wait") as info:
        make(tmp_path, handler, Clock()).fetch("https://s.test/c")
    assert info.value.status == 503


def test_transport_errors_exhaust_attempts(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return robots_ok()
        raise httpx.ConnectTimeout("slow", request=request)

    with pytest.raises(FetchError, match="after 4 attempts"):
        make(tmp_path, handler, Clock(), host_interval=0.0).fetch("https://s.test/c")


def test_not_found_is_an_error_with_its_status(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return robots_ok() if request.url.path == "/robots.txt" else httpx.Response(404)

    with pytest.raises(FetchError) as info:
        make(tmp_path, handler, Clock()).fetch("https://s.test/c")
    assert info.value.status == 404


def test_requests_to_one_host_are_paced_by_crawl_delay(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return robots_ok(b"User-agent: *\nCrawl-delay: 10\nDisallow:\n")
        return httpx.Response(200, text="z")

    clock = Clock()
    client = make(tmp_path, handler, clock, host_interval=5.0)
    client.fetch("https://s.test/a")
    client.fetch("https://s.test/b")
    # robots.txt, then /a and /b each 10 s (the Crawl-delay, above our 5 s) after the last.
    assert clock.slept == [10.0, 10.0]


def test_robots_is_read_once_per_day(tmp_path: Path) -> None:
    reads: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            reads.append("robots")
            return robots_ok()
        return httpx.Response(200, text="z")

    clock = Clock()
    client = make(tmp_path, handler, clock, host_interval=0.0)
    client.fetch("https://s.test/a")
    client.fetch("https://s.test/b")
    clock.now += timedelta(hours=25)
    client.fetch("https://s.test/c")
    assert reads == ["robots", "robots"]


@pytest.mark.parametrize(
    ("status", "allowed", "rule"),
    [(404, True, "unavailable"), (500, False, "unreachable")],
)
def test_robots_status_decides_the_verdict_not_the_read(
    tmp_path: Path, status: int, allowed: bool, rule: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(status)
        return httpx.Response(200, text="ok")

    client = make(tmp_path, handler, Clock(), host_interval=0.0)
    fetched = client.fetch("https://s.test/c")
    assert fetched.body == b"ok"
    assert fetched.robots[0].allowed is allowed
    assert rule in fetched.robots[0].rule


def test_redirects_are_checked_against_robots(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return robots_ok()
        if request.url.path == "/old":
            return httpx.Response(301, headers={"Location": "/private/new"})
        return httpx.Response(200, text="n")

    fetched = make(tmp_path, handler, Clock(), host_interval=0.0).fetch("https://s.test/old")
    assert fetched.final_url == "https://s.test/private/new"
    assert [(v.url, v.allowed) for v in fetched.robots] == [
        ("https://s.test/old", True),
        ("https://s.test/private/new", False),
    ]


def test_redirect_is_followed_and_recorded(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return robots_ok()
        if request.url.path == "/old":
            return httpx.Response(302, headers={"Location": "https://s.test/new"})
        return httpx.Response(200, text="n")

    fetched = make(tmp_path, handler, Clock(), host_interval=0.0).fetch("https://s.test/old")
    assert fetched.final_url == "https://s.test/new"
    assert fetched.url == "https://s.test/old"


def test_https_to_http_redirect_is_refused(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return robots_ok()
        return httpx.Response(301, headers={"Location": "http://s.test/plain"})

    with pytest.raises(FetchError, match="refused redirect"):
        make(tmp_path, handler, Clock(), host_interval=0.0).fetch("https://s.test/c")


def test_too_many_redirects(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return robots_ok()
        return httpx.Response(302, headers={"Location": "/loop"})

    with pytest.raises(FetchError, match="redirects"):
        make(tmp_path, handler, Clock(), host_interval=0.0).fetch("https://s.test/loop")


def test_oversized_body_is_refused(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return robots_ok()
        return httpx.Response(200, content=b"x" * (MAX_BODY + 1))

    with pytest.raises(FetchError, match="larger than"):
        make(tmp_path, handler, Clock(), host_interval=0.0).fetch("https://s.test/c")


def test_gzip_encoded_answers_are_decoded_once(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = gzip.compress(b"User-agent: *\nDisallow: /private\n")
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=body, headers={"Content-Encoding": "gzip"})
        return httpx.Response(
            200, content=gzip.compress(b"[]"), headers={"Content-Encoding": "gzip"}
        )

    client = make(tmp_path, handler, Clock(), host_interval=0.0)
    assert client.fetch("https://s.test/c").body == b"[]"
    assert not client.check_robots("https://s.test/private/x")[0]
