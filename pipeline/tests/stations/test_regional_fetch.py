"""Live reads of part 3b's registered stations, end to end.

The servers are synthetic (httpx.MockTransport); the bodies they serve are the real
fixtures in fixtures/regional/. Each read goes through the real registry entry, the
polite client (robots.txt first, its verdict recorded; the repository's User-Agent)
and the adapter, following a page to the file it frames or loads.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from snowlight.sources.stations import fetch
from snowlight.sources.stations.http import USER_AGENT, ConditionalStore, PoliteClient, Timing
from snowlight.sources.stations.model import HealthStatus
from snowlight.sources.stations.registry import load_registry

FIXTURES = Path(__file__).parent / "fixtures" / "regional"
REGISTRY = load_registry()
NOW = datetime(2026, 9, 27, 7, 30, tzinfo=UTC)
D = "20260927"
SHEET = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vRTTn-nz1kHVAdHbBrAQSgMaLB0FbiNrO7cWaFDIxZxvGzGXnHnF2jv5LiRcui_Tz0JTpGAt2DidUYo"
)
SERVED = {
    "https://wach.com/resources/ftptransfer/wach/closings/closings.html": (
        f"sinclair/wach-live-{D}.html"
    ),
    "https://13wham.com/resources/ftptransfer/wham/closings/closings.html": (
        f"sinclair/wham-live-{D}.html"
    ),
    "https://wjactv.com/resources/ftptransfer/wjac/closings/closings.html": (
        f"sinclair/wjac-live-{D}.html"
    ),
    "https://sbgcg.com/Ticker/Stations/KATV/closings.html": f"sinclair/katv-display-live-{D}.html",
    "https://ftp2.kimt.com/closings.html": f"allen/kimt-live-{D}.html",
    "https://www.wsbtv.com/pf/api/v3/content/fetch/closing?_website=cmg-tv-10010": (
        f"cox/wsb-content-live-{D}.json"
    ),
    "https://kstp.com/wp-content/uploads/dynamic-assets/schoolalert.html": (
        f"hubbard/kstp-live-{D}.html"
    ),
    "https://itv.news12.com/school_closings/closings.jsp?region=LI": f"news12/li-live-{D}.html",
    "https://www.ribroadcasters.com/news_and_events/closings_delays/": (
        f"newsticker/riba-live-{D}.html"
    ),
    "https://www.koamnewsnow.com/weather/closings-and-delays/": f"blox/koam-page-live-{D}.html",
    "https://www.koamnewsnow.com/app/closings/KOAM-closingsC.xml": f"blox/koam-live-{D}.xml",
    "https://cwtreasurevalley.com/resources/ftptransfer/kboi/closings/closings.html": (
        f"errors/kyuu-ld-live-{D}.html"
    ),
    "https://www.northcountrypublicradio.org/storm.php": f"ncpr/storm-live-{D}.html",
    "https://santacruzcoe.org/schoolclosures/": f"santacruzcoe/page-live-{D}.html",
    f"{SHEET}/pubhtml?gid=1755311565&single=true&widget=true&headers=false": (
        f"santacruzcoe/widget-live-{D}.html"
    ),
    f"{SHEET}/pubhtml/sheet?headers=false&gid=1755311565": f"santacruzcoe/sheet-live-{D}.html",
    "https://hcoe.org/news/alerts/feed/": f"hcoe/alerts-feed-live-{D}.xml",
    "https://www.eventdelay.com/new/widget/channel/114/list/": (
        f"eventdelay/wdel-list-live-{D}.html"
    ),
}
LAST_MODIFIED = {
    # The WJAC grid as its server dated it; the KOAM file as its server dated it (in
    # the last winter, so not stale).
    "https://wjactv.com/resources/ftptransfer/wjac/closings/closings.html": (
        "Sun, 27 Sep 2026 05:38:45 GMT"
    ),
    "https://www.koamnewsnow.com/app/closings/KOAM-closingsC.xml": "Tue, 10 Feb 2026 07:02:46 GMT",
}
CHAMELEON = "https://ticker.news.sinclairinc.cloud/chameleon/blade/query/28/CLOSINGS/"


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
    def __init__(self) -> None:
        self.seen: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.seen.append(url)
        assert request.headers["User-Agent"] == USER_AGENT
        if request.url.path == "/robots.txt":
            # As Sinclair's hosts write it: the list files' folder is disallowed.
            return httpx.Response(
                200, content=b"User-agent: *\nDisallow: /resources/ftptransfer/\n"
            )
        if url.startswith(CHAMELEON):
            # The Chameleon ticker as read live on 2026-09-27 (see the fixtures README).
            return httpx.Response(200, content=b'{"generated": "x", "bladeQueryItem": []}')
        if url in SERVED:
            headers = {"Last-Modified": LAST_MODIFIED[url]} if url in LAST_MODIFIED else {}
            return httpx.Response(
                200, headers=headers, content=(FIXTURES / SERVED[url]).read_bytes()
            )
        return httpx.Response(404, content=b"not found")


def _client(tmp_path: Path, server: Server) -> PoliteClient:
    ticker = Ticker()
    return PoliteClient(
        httpx.Client(transport=httpx.MockTransport(server), headers={"User-Agent": USER_AGENT}),
        ConditionalStore(tmp_path / "cache"),
        timing=Timing(clock=ticker.clock, monotonic=ticker.monotonic, sleep=ticker.sleep),
    )


def test_registered_stations_read_through_their_adapters(tmp_path: Path) -> None:
    server = Server()
    client = _client(tmp_path, server)
    wanted = [
        "sinclair-wach",
        "sinclair-wham",
        "sinclair-wjac",
        "sinclair-katv",
        "sinclair-kyuu-ld",
        "allen-kimt",
        "cox-wsb",
        "hubbard-kstp",
        "news12-li",
        "riba-statewide",
        "blox-koam",
        "ncpr-storm",
        "santacruzcoe-closures",
        "hcoe-alerts",
        "eventdelay-wdel",
    ]
    result = fetch.run(REGISTRY, client, clock=lambda: NOW, only=wanted)
    health = {entry.source_id: entry for entry in result.health}
    summary = {sid: (h.status, h.rows, h.variant) for sid, h in health.items()}
    assert summary == {
        "sinclair-wach": (HealthStatus.OK, 1, "newsticker-html"),
        "sinclair-wham": (HealthStatus.EMPTY, 0, "newsticker-html"),
        "sinclair-wjac": (HealthStatus.EMPTY, 0, "closings-grid"),
        "sinclair-katv": (HealthStatus.EMPTY, 0, "chameleon-json"),
        "sinclair-kyuu-ld": (HealthStatus.SKIPPED, 0, None),
        "allen-kimt": (HealthStatus.EMPTY, 0, "allen-header-table"),
        "cox-wsb": (HealthStatus.EMPTY, 0, "cox-arc-content"),
        "hubbard-kstp": (HealthStatus.EMPTY, 0, "hubbard-schoolalert"),
        "news12-li": (HealthStatus.OK, 6, "news12-jsp"),
        "riba-statewide": (HealthStatus.OK, 11, "newsticker-html"),
        "blox-koam": (HealthStatus.EMPTY, 0, "blox-sc-xml"),
        "ncpr-storm": (HealthStatus.EMPTY, 0, "ncpr-storm-page"),
        "santacruzcoe-closures": (HealthStatus.EMPTY, 0, "santacruzcoe-sheet"),
        "hcoe-alerts": (HealthStatus.OK, 5, "hcoe-alerts-feed"),
        "eventdelay-wdel": (HealthStatus.EMPTY, 0, "eventdelay-list"),
    }
    # The robots.txt verdict is recorded, not obeyed: the disallowed file was read.
    wach = health["sinclair-wach"]
    assert [(v.url, v.allowed) for v in wach.robots] == [
        ("https://wach.com/resources/ftptransfer/wach/closings/closings.html", False)
    ]
    assert fetch.totals(result.health)["robots_disallowed"] >= 1
    # KYUU-LD's page frames a file of no bytes: the station has no list to read, so it
    # is registered without an endpoint and not requested (the error fixture shows why).
    assert health["sinclair-kyuu-ld"].reason == "no known closings endpoint"
    assert not any("cwtreasurevalley" in url for url in server.seen)
    # Santa Cruz: the page frames the sheet's widget view, which names the tab page.
    sheet = f"{SHEET}/pubhtml/sheet?headers=false&gid=1755311565"
    assert health["santacruzcoe-closures"].url == sheet
    # KATV's display page was followed to the ticker address it carries.
    katv = health["sinclair-katv"]
    assert katv.via_url == "https://sbgcg.com/Ticker/Stations/KATV/closings.html"
    assert katv.url is not None
    assert katv.url.startswith(CHAMELEON)
    koam = health["blox-koam"]
    assert koam.last_modified == datetime(2026, 2, 10, 7, 2, 46, tzinfo=UTC)
    rows = [(row.source_id, row.raw_name) for row in result.rows]
    assert ("sinclair-wach", "Lexington School District Three") in rows
    assert ("riba-statewide", "Roger Williams Park Zoo") in rows
    assert ("hcoe-alerts", "Klamath-Trinity Schools Closed Wednesday, March 11") in rows
    assert len(rows) == 23


def test_a_list_file_unwritten_since_before_last_winter_is_stale(tmp_path: Path) -> None:
    server = Server()
    LAST_MODIFIED["https://ftp2.kimt.com/closings.html"] = "Tue, 21 Jan 2025 12:00:00 GMT"
    try:
        result = fetch.run(
            REGISTRY, _client(tmp_path, server), clock=lambda: NOW, only=["allen-kimt"]
        )
    finally:
        del LAST_MODIFIED["https://ftp2.kimt.com/closings.html"]
    (health,) = result.health
    assert health.status is HealthStatus.STALE
    assert "2025-01-21" in (health.reason or "")


def test_a_refusal_is_an_error_and_is_not_retried_around(tmp_path: Path) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(403, content=b"<html>blocked</html>")

    ticker = Ticker()
    client = PoliteClient(
        httpx.Client(transport=httpx.MockTransport(refuse), headers={"User-Agent": USER_AGENT}),
        ConditionalStore(tmp_path / "cache"),
        timing=Timing(clock=ticker.clock, monotonic=ticker.monotonic, sleep=ticker.sleep),
    )
    result = fetch.run(REGISTRY, client, clock=lambda: NOW, only=["spectrum-albany"])
    (health,) = result.health
    assert health.status is HealthStatus.ERROR
    assert health.http_status == 403
