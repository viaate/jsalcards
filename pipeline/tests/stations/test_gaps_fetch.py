"""Live reads of part 4's registered stations (Cowles' Montana ticker, Flathead County), end to end.

The servers are synthetic (httpx.MockTransport); the bodies they serve are the real
fixtures in fixtures/gaps/. Each read goes through the real registry entry, the
polite client (robots.txt first, its verdict recorded; the repository's
User-Agent; conditional requests) and the adapter.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from snowlight.sources.stations import fetch
from snowlight.sources.stations.http import USER_AGENT, ConditionalStore, PoliteClient, Timing
from snowlight.sources.stations.model import HealthStatus
from snowlight.sources.stations.registry import load_registry

FIXTURES = Path(__file__).parent / "fixtures" / "gaps"
REGISTRY = load_registry()
NOW = datetime(2026, 9, 27, 11, 30, tzinfo=UTC)
TICKER = "https://company-wide-tickers.s3.us-west-2.amazonaws.com/KULR_School_Results/closings.html"
FLATHEAD = "https://flatheadcounty.gov/department-directory/schools/emergency-school-closures"
SHASTA = "https://www.shastacoe.org/office-of-education/school-closures"
SHEET = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vRt_q35uHlnknDJQ9VW3PzAu5a8qJdFvqA6gBrKOcLHp1Wx0toWwCFmDDqBh6ak38JSB0nC_Om6VOA_"
)
WIDGET = f"{SHEET}/pubhtml?gid=541890420&single=true&widget=true&headers=false"
TAB = f"{SHEET}/pubhtml/sheet?headers=false&gid=541890420"
TRINITY = "https://www.tcoek12.org/school-districts/school-closure-information"
TRINITY_SHEET = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vRzrIeQ579iJDJCzp_oD9jDkAFAsjdNUHS-qY1Xe-_-kRRHyLaUS0av9-eoKHphpMPKr4HUVpEMTUiX"
    "/pubhtml?gid=0&single=true&widget=false&headers=false"
)
SERVED = {
    TICKER: "cowles/ticker-live-20260927.html",
    FLATHEAD: "flathead/closures-live-20260927.html",
    SHASTA: "coesheet/shasta-page-live-20260927.html",
    WIDGET: "coesheet/shasta-widget-live-20260927.html",
    TAB: "coesheet/shasta-tab-live-20260927.html",
    TRINITY: "coesheet/trinity-page-live-20260927.html",
    TRINITY_SHEET: "coesheet/trinity-sheet-live-20260927.html",
}
# As the ticker's server dated it on 2026-09-27 (inside the last winter, so not stale).
TICKER_MODIFIED = "Thu, 16 Apr 2026 15:18:17 GMT"
ETAG = '"c46c204abfd63132b00fb871fe9b1ab2"'
COWLES = ["cowles-kfbb", "cowles-khbb", "cowles-ktmf", "cowles-kulr", "cowles-kwyb"]


class Ticker:
    def __init__(self) -> None:
        self.now = NOW
        self.mono = 0.0

    def clock(self) -> datetime:
        return self.now

    def monotonic(self) -> float:
        return self.mono

    def sleep(self, seconds: float) -> None:
        self.mono += seconds
        self.now += timedelta(seconds=seconds)


class Server:
    def __init__(self, modified: str = TICKER_MODIFIED) -> None:
        self.seen: list[str] = []
        self.conditional: list[str] = []
        self.modified = modified

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.seen.append(url)
        assert request.headers["User-Agent"] == USER_AGENT
        if request.url.path == "/robots.txt":
            return _robots(request.url.host)
        if url == TICKER:
            return self._ticker(request)
        if url in SERVED:
            return httpx.Response(200, content=(FIXTURES / SERVED[url]).read_bytes())
        return httpx.Response(404, content=b"not found")

    def _ticker(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("If-None-Match") == ETAG:
            self.conditional.append(str(request.url))
            return httpx.Response(304)
        return httpx.Response(
            200,
            headers={"Last-Modified": self.modified, "ETag": ETAG},
            content=(FIXTURES / SERVED[TICKER]).read_bytes(),
        )


def _robots(host: str) -> httpx.Response:
    # S3 answers robots.txt with 403 AccessDenied (read 2026-09-27): unavailable.
    if host.endswith("amazonaws.com"):
        return httpx.Response(403, content=b"<Error><Code>AccessDenied</Code></Error>")
    if host == "docs.google.com":
        # As docs.google.com writes it (read 2026-09-27), in part.
        return httpx.Response(
            200, content=b"User-agent: *\nCrawl-delay: 1\nAllow: /spreadsheet\nDisallow: /\n"
        )
    return httpx.Response(200, content=b"User-agent: *\nDisallow: /application/config\n")


def _client(tmp_path: Path, server: Server) -> PoliteClient:
    ticker = Ticker()
    return PoliteClient(
        httpx.Client(transport=httpx.MockTransport(server), headers={"User-Agent": USER_AGENT}),
        ConditionalStore(tmp_path / "cache"),
        timing=Timing(clock=ticker.clock, monotonic=ticker.monotonic, sleep=ticker.sleep),
    )


def test_every_station_of_the_part_reads_through_its_adapter(tmp_path: Path) -> None:
    server = Server()
    result = fetch.run(
        REGISTRY,
        _client(tmp_path, server),
        clock=lambda: NOW,
        only=[*COWLES, "flathead-county", "coesheet-shasta", "coesheet-trinity"],
    )
    health = {entry.source_id: entry for entry in result.health}
    summary = {sid: (h.status, h.rows, h.variant) for sid, h in health.items()}
    assert summary == {
        **dict.fromkeys(COWLES, (HealthStatus.EMPTY, 0, "closings-grid")),
        "flathead-county": (HealthStatus.OK, 35, "flathead-closure-tables"),
        "coesheet-shasta": (HealthStatus.OK, 95, "coesheet-table"),
        "coesheet-trinity": (HealthStatus.OK, 17, "coesheet-table"),
    }
    kulr = health["cowles-kulr"]
    assert kulr.url == TICKER
    assert kulr.last_modified == datetime(2026, 4, 16, 15, 18, 17, tzinfo=UTC)
    assert [(v.url, v.state.value, v.allowed) for v in kulr.robots] == [
        (TICKER, "unavailable", True)
    ]
    # The file is read once and then asked for conditionally.
    assert server.seen.count(TICKER) == len(COWLES)
    assert server.conditional == [TICKER] * (len(COWLES) - 1)
    # Shasta: the county office's page, then the widget it frames, then the tab page.
    shasta = health["coesheet-shasta"]
    assert (shasta.url, shasta.via_url) == (TAB, SHASTA)
    assert [(v.url, v.allowed) for v in shasta.robots] == [
        (SHASTA, True),
        (WIDGET, True),
        (TAB, True),
    ]
    (read,) = [r for r in result.reads if r.source_id == "coesheet-shasta"]
    assert [(page.url, page.variant) for page in read.via] == [
        (SHASTA, "coesheet-page"),
        (WIDGET, "coesheet-widget"),
    ]
    rows = [(row.source_id, row.raw_name, row.raw_status) for row in result.rows]
    assert ("flathead-county", "West Valley", "Closed") in rows
    assert ("coesheet-shasta", "Black Butte Elementary", "Closing at 12:45") in rows
    assert health["coesheet-trinity"].via_url == TRINITY
    assert len(rows) == 35 + 95 + 17


def test_a_ticker_unwritten_since_before_last_winter_is_stale(tmp_path: Path) -> None:
    server = Server(modified="Fri, 14 Mar 2025 12:00:00 GMT")
    result = fetch.run(REGISTRY, _client(tmp_path, server), clock=lambda: NOW, only=["cowles-kulr"])
    (health,) = result.health
    assert health.status is HealthStatus.STALE
    assert "2025-03-14" in (health.reason or "")


def test_a_refusal_is_an_error_and_is_not_retried_around(tmp_path: Path) -> None:
    seen: list[str] = []

    def refuse(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(403, content=b"<html>Access Denied</html>")

    ticker = Ticker()
    client = PoliteClient(
        httpx.Client(transport=httpx.MockTransport(refuse), headers={"User-Agent": USER_AGENT}),
        ConditionalStore(tmp_path / "cache"),
        timing=Timing(clock=ticker.clock, monotonic=ticker.monotonic, sleep=ticker.sleep),
    )
    result = fetch.run(REGISTRY, client, clock=lambda: NOW, only=["flathead-county"])
    (health,) = result.health
    assert health.status is HealthStatus.ERROR
    assert health.http_status == 403
    assert seen.count(FLATHEAD) == 1


def test_a_redesigned_page_is_an_error_not_an_empty_day(tmp_path: Path) -> None:
    def redesigned(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        # SYNTHETIC: a page without the closures tables.
        return httpx.Response(200, content=b"<html><body><h1>School Closures</h1></body></html>")

    ticker = Ticker()
    client = PoliteClient(
        httpx.Client(transport=httpx.MockTransport(redesigned), headers={"User-Agent": USER_AGENT}),
        ConditionalStore(tmp_path / "cache"),
        timing=Timing(clock=ticker.clock, monotonic=ticker.monotonic, sleep=ticker.sleep),
    )
    result = fetch.run(REGISTRY, client, clock=lambda: NOW, only=["flathead-county"])
    (health,) = result.health
    assert health.status is HealthStatus.ERROR
    assert "unrecognized shape" in (health.reason or "")
