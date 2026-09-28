"""Live reads of registered Nexstar, TEGNA and Scripps stations, end to end.

The servers are synthetic (httpx.MockTransport); the bodies they serve are the real
fixtures in fixtures/groups/. Each read goes through the real registry entry, the
polite client (robots.txt first, the repository's User-Agent) and the adapter.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from snowlight.sources.stations import fetch
from snowlight.sources.stations.http import USER_AGENT, ConditionalStore, PoliteClient, Timing
from snowlight.sources.stations.model import HealthStatus, ListingState
from snowlight.sources.stations.registry import load_registry

FIXTURES = Path(__file__).parent / "fixtures" / "groups"
REGISTRY = load_registry()
NOW = datetime(2026, 9, 26, 23, 0, tzinfo=UTC)
KSN_PAGE = "https://www.ksn.com/wp-json/wp/v2/pages?slug=closings"
SERVED = {
    "https://www.wtnh.com/wp-json/wp/v2/pages/5894": "nexstar/wtnh-page-20260926224825.json",
    KSN_PAGE: "nexstar/ksnw-page-20260926224815.json",
    "https://media.psg.nexstardigital.net/ksnw/weather/ksnwx-closings-nwt.html": (
        "nexstar/ksnw-psg-20260926224342.html"
    ),
    "https://media.psg.nexstardigital.net/WGNR/closings/closings.json": (
        "nexstar/wgn-ecc-20260926224340.json"
    ),
    "https://www.fox61.com/closings": "tegna/wtic-page-20260926223946.html",
    "https://content.kgw.com/station/flashalert/allclosures.html": (
        "tegna/kgw-flashalert-20260926224347.html"
    ),
    "https://www.wtkr.com/weather/school-closings-delays": "scripps/wtkr-page-20260926223948.html",
    "https://www.wtvq.com/content/uploads/weather-images/SnoWatch.html": (
        "scripps/wtvq-snowatch-20260926224349.html"
    ),
}


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
            return httpx.Response(200, content=b"User-agent: *\nDisallow: /wp-admin/\n")
        if url in SERVED:
            headers = (
                {"Last-Modified": "Fri, 20 Mar 2026 12:33:08 GMT"} if "SnoWatch" in url else {}
            )
            return httpx.Response(
                200, headers=headers, content=(FIXTURES / SERVED[url]).read_bytes()
            )
        # What Nexstar's HTML pages answer this User-Agent: a bot challenge.
        return httpx.Response(403, content=b"<html>Access to this page has been denied</html>")


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
        "nexstar-wtnh",
        "nexstar-ksnw",
        "nexstar-wgn",
        "tegna-wtic",
        "tegna-kgw",
        "scripps-wtkr",
        "scripps-wtvq",
    ]
    result = fetch.run(REGISTRY, client, clock=lambda: NOW, only=wanted)
    health = {entry.source_id: entry for entry in result.health}
    assert {sid: (h.status, h.rows, h.variant) for sid, h in health.items()} == {
        "nexstar-wtnh": (HealthStatus.OK, 3, "nexstar-wp-closings"),
        "nexstar-ksnw": (HealthStatus.EMPTY, 0, "nexstar-psg-closings"),
        "nexstar-wgn": (HealthStatus.EMPTY, 0, "nexstar-ecc-json"),
        "tegna-wtic": (HealthStatus.OK, 1, "tegna-closings-module"),
        "tegna-kgw": (HealthStatus.EMPTY, 0, "gray-file-flashalert"),
        "scripps-wtkr": (HealthStatus.OK, 4, "scripps-closings-module"),
        "scripps-wtvq": (HealthStatus.EMPTY, 0, "gray-file-grid"),
    }
    # WTVQ's file was last written in March 2026, within the last winter: not stale.
    assert health["scripps-wtvq"].last_modified == datetime(2026, 3, 20, 12, 33, 8, tzinfo=UTC)
    assert all(verdict.allowed for h in health.values() for verdict in h.robots)
    rows = [(row.source_id, row.raw_name) for row in result.rows]
    assert ("nexstar-wtnh", "Glanbia Nutritionals") in rows
    assert ("tegna-wtic", "MDC All Recreational Facilities") in rows
    assert len(rows) == 8
    # Only robots.txt files and the registered list URLs were requested.
    assert {url for url in server.seen if not url.endswith("/robots.txt")} <= set(SERVED)


def test_a_page_that_frames_its_file_is_followed_to_it(tmp_path: Path) -> None:
    server = Server()
    station = REGISTRY.stations["nexstar-ksnw"].model_copy(
        update={"page_url": KSN_PAGE, "data_url": None, "page_check": None, "list_files": ()}
    )
    result = fetch.read_station(REGISTRY, station, _client(tmp_path, server), NOW)
    (health,) = result.health
    assert (health.status, health.variant, health.via_url) == (
        HealthStatus.EMPTY,
        "nexstar-psg-closings",
        KSN_PAGE,
    )
    (read,) = result.reads
    (page,) = read.via
    assert (page.variant, page.state) == ("nexstar-wp-frame", ListingState.DEFERRED)
    assert page.follows.endswith("ksnwx-closings-nwt.html")


def test_a_bot_challenge_is_an_error_and_is_not_retried(tmp_path: Path) -> None:
    server = Server()
    station = REGISTRY.stations["nexstar-wtnh"].model_copy(
        update={"data_url": None, "page_url": "https://www.wtnh.com/weather/closings/"}
    )
    result = fetch.read_station(REGISTRY, station, _client(tmp_path, server), NOW)
    (health,) = result.health
    assert (health.status, health.http_status) == (HealthStatus.ERROR, 403)
    assert server.seen.count("https://www.wtnh.com/weather/closings/") == 1
    assert result.rows == []
