"""Live and archived reads of the network-owned, ECC and FlashAlert stations, end to end.

The servers are synthetic (httpx.MockTransport) and so is the snapshot manifest
of the archive test; the bodies they serve are the real fixtures in
fixtures/networks/. Each read goes through the real registry entry, the polite
client (robots.txt first, the repository's User-Agent) and the adapter.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from snowlight.sources.stations import archive, fetch, network_fixtures
from snowlight.sources.stations.fixtures import Origin
from snowlight.sources.stations.http import USER_AGENT, ConditionalStore, PoliteClient, Timing
from snowlight.sources.stations.model import HealthStatus, ListingState, ReadMode
from snowlight.sources.stations.registry import load_registry

FIXTURES = Path(__file__).parent / "fixtures" / "networks"
REGISTRY = load_registry()
NOW = datetime(2026, 9, 27, 2, 0, tzinfo=UTC)
A1 = "https://assets1.cbsnewsstatic.com/Integrations/SchoolClosings/PRODUCTION/CBS/"
SERVED = {
    "https://abc7ny.com/community/schoolclosings/": "abc-owned/wabc-page-live-20260927013716.html",
    "https://abc7.com/community/schoolclosings/": "abc-owned/kabc-page-live-20260927013721.html",
    "https://abc7chicago.com/community/schoolclosings/": (
        "abc-owned/wls-page-live-20260927013726.html"
    ),
    "https://www.nbcboston.com/wp-json/nbc/v1/school-closings": (
        "nbc-owned/wbts-route-live-20260927013737.json"
    ),
    "https://media.foxtv.com/wttg/closings/closings.html": (
        "fox-owned/wttg-file-live-20260927013824.html"
    ),
    "https://media.foxtv.com/waga/closings/closings.htm": (
        "fox-owned/waga-file-live-20260927013819.htm"
    ),
    A1 + "wbz/NEWSROOM/chyron/closings.xml": "cbs-owned/wbz-feed-live-20260927013850.xml",
    "https://media.psg.nexstardigital.net/WGNR/closings/closings.json": (
        "ecc/chicago-json-live-20260927013921.json"
    ),
    "https://www.flashalertnewswire.net/IIN/reportsX/cwc-closures.php?RegionID=1": (
        "flashalert/portland-report-live-20260927013931.html"
    ),
}
LAST_MODIFIED = {
    "https://media.foxtv.com/waga/closings/closings.htm": "Thu, 28 May 2026 13:08:45 GMT"
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
            if request.url.host == "assets1.cbsnewsstatic.com":
                return httpx.Response(200, content=b"User-agent: *\nDisallow: /\nAllow: /i/\n")
            if request.url.host in {"media.foxtv.com", "www.flashalertnewswire.net"}:
                return httpx.Response(404)
            return httpx.Response(200, content=b"User-agent: *\nDisallow: /wp-admin/\n")
        if url in SERVED:
            headers = {"Last-Modified": LAST_MODIFIED[url]} if url in LAST_MODIFIED else {}
            return httpx.Response(
                200, headers=headers, content=(FIXTURES / SERVED[url]).read_bytes()
            )
        # WLS's framed copy of the ECC application: AccessDenied, as on 2026-09-26.
        return httpx.Response(403, content=b"<Error><Code>AccessDenied</Code></Error>")


def _client(tmp_path: Path, server: Server) -> PoliteClient:
    ticker = Ticker()
    return PoliteClient(
        httpx.Client(transport=httpx.MockTransport(server), headers={"User-Agent": USER_AGENT}),
        ConditionalStore(tmp_path / "cache"),
        timing=Timing(clock=ticker.clock, monotonic=ticker.monotonic, sleep=ticker.sleep),
    )


def test_registered_stations_read_through_their_adapters(tmp_path: Path) -> None:
    server = Server()
    wanted = [
        "abc-owned-wabc",
        "abc-owned-kabc",
        "abc-owned-wls",
        "nbc-owned-wbts",
        "fox-owned-wttg",
        "fox-owned-waga",
        "cbs-owned-wbz",
        "ecc-chicago",
        "flashalert-portland",
        "fox-owned-ksaz",
    ]
    result = fetch.run(REGISTRY, _client(tmp_path, server), clock=lambda: NOW, only=wanted)
    health = {entry.source_id: entry for entry in result.health}
    assert {sid: (h.status, h.rows, h.variant) for sid, h in health.items()} == {
        "abc-owned-wabc": (HealthStatus.EMPTY, 0, "abc-otv-list"),
        "abc-owned-kabc": (HealthStatus.STALE, 0, "abc-otv-list"),
        "abc-owned-wls": (HealthStatus.ERROR, 0, None),
        "nbc-owned-wbts": (HealthStatus.OK, 5, "nbc-wp-json"),
        "fox-owned-wttg": (HealthStatus.EMPTY, 0, "fox-closings-table"),
        "fox-owned-waga": (HealthStatus.EMPTY, 0, "gray-file-sc-para"),
        "cbs-owned-wbz": (HealthStatus.OK, 2, "gray-file-newsticker-xml"),
        "ecc-chicago": (HealthStatus.EMPTY, 0, "ecc-json"),
        "flashalert-portland": (HealthStatus.EMPTY, 0, "gray-file-flashalert"),
        "fox-owned-ksaz": (HealthStatus.SKIPPED, 0, None),
    }
    # A list that says it last changed in 2019 is stale, and says so.
    assert "2019-02-12T20:39:39Z" in (health["abc-owned-kabc"].reason or "")
    # WLS's frame answered 403: an error, not retried, and no row kept.
    assert (health["abc-owned-wls"].http_status, health["abc-owned-wls"].via_url) == (
        403,
        "https://abc7chicago.com/community/schoolclosings/",
    )
    assert server.seen.count("https://wgnr-closings.s3.amazonaws.com/index.html") == 1
    # WAGA's file was written in May 2026, within the last winter: not stale.
    assert health["fox-owned-waga"].last_modified == datetime(2026, 5, 28, 13, 8, 45, tzinfo=UTC)
    # robots.txt disallows CBS's feed: the verdict is recorded and the file read anyway.
    (verdict,) = health["cbs-owned-wbz"].robots
    assert (verdict.allowed, verdict.rule) == (False, "Disallow: /")
    assert all(v.allowed for sid, h in health.items() if sid != "cbs-owned-wbz" for v in h.robots)
    rows = [(row.source_id, row.raw_name) for row in result.rows]
    assert ("nbc-owned-wbts", "Bristol Community College") in rows
    assert ("cbs-owned-wbz", "Worcester Public Schools") in rows
    assert len(rows) == 7
    # Only robots.txt files, the registered lists and WLS's frame were requested.
    requested = {url for url in server.seen if not url.endswith("/robots.txt")}
    assert requested == set(SERVED) | {"https://wgnr-closings.s3.amazonaws.com/index.html"}


def test_archived_region_report_is_read_as_its_region(tmp_path: Path) -> None:
    """A synthetic manifest over a real body: the capture belongs to the region its URL names."""
    body = (FIXTURES / "flashalert/seattle-report-live-20260927013941.html").read_bytes()
    snapshots = tmp_path / "run" / "snapshots"
    snapshots.mkdir(parents=True)
    (snapshots / "region12.body").write_bytes(body)
    url = "https://www.flashalertnewswire.net/IIN/reportsX/cwc-closures.php?RegionID=12"
    record = {
        "timestamp": "20260927013941",
        "url": url,
        "requested": f"https://web.archive.org/web/20260927013941id_/{url}",
        "hops": [],
        "retrieved_at": "2026-09-27T02:00:00Z",
        "final_url": f"https://web.archive.org/web/20260927013941id_/{url}",
        "final_timestamp": "20260927013941",
        "final_original": url,
        "http_status": 200,
        "file": "snapshots/region12.body",
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }
    (snapshots / "manifest.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    result = archive.parse_snapshots(REGISTRY, tmp_path)
    (read,) = result.reads
    assert (read.source_id, read.mode, read.variant, read.state) == (
        "flashalert-seattle",
        ReadMode.ARCHIVE,
        "gray-file-flashalert",
        ListingState.EMPTY,
    )


def test_fixture_tool_captures_and_slices_a_live_body(tmp_path: Path) -> None:
    server = Server()
    url = "https://abc7ny.com/community/schoolclosings/"
    (record,) = network_fixtures.capture(_client(tmp_path, server), [url], tmp_path / "log")
    assert record["status"] == 200
    logged, body = network_fixtures.logged_body(tmp_path / "log" / network_fixtures.LOG_FILE, url)
    origin = Origin(
        source_id="abc-owned-wabc",
        adapter="abc-owned",
        mode=ReadMode.LIVE,
        url=url,
        captured_at=str(logged["fetched_at"]),
        archive_url=None,
        retrieved_at=str(logged["fetched_at"]),
    )
    entry, sliced = network_fixtures.make_entry("abc-owned/x.html", origin, body, "abc-otv-v1")
    assert sliced == body  # the served body is itself a slice: slicing it changes nothing
    assert (entry.expected.variant, entry.expected.state) == ("abc-otv-list", ListingState.EMPTY)
    folder = tmp_path / "fixtures"
    network_fixtures.write_fixtures(folder, [(entry, sliced)])
    assert network_fixtures.load_entries(folder) == [entry]
    assert "abc-owned/x.html" in (folder / network_fixtures.README_FILE).read_text()


def test_archived_storm_day_pages_are_read_as_their_stations(tmp_path: Path) -> None:
    """A synthetic manifest over real storm-day captures: each is its station's populated list."""
    captures = {
        "https://abc7ny.com/community/schoolclosings/": (
            "20260223174946",
            "abc-owned/wabc-page-20260223174946.html",
        ),
        "http://6abc.com/community/schoolclosings/": (
            "20190219235902",
            "abc-owned/wpvi-page-20190219235902.html",
        ),
        "https://www.flashalertnewswire.net/IIN/reportsX/cwc-closures.php?RegionID=13": (
            "20190215030813",
            "flashalert/columbia-report-20190215030813.html",
        ),
    }
    snapshots = tmp_path / "run" / "snapshots"
    snapshots.mkdir(parents=True)
    lines = []
    for number, (url, (stamp, name)) in enumerate(captures.items()):
        body = (FIXTURES / name).read_bytes()
        (snapshots / f"{number}.body").write_bytes(body)
        wayback = f"https://web.archive.org/web/{stamp}id_/{url}"
        lines.append(
            json.dumps(
                {
                    "timestamp": stamp,
                    "url": url,
                    "requested": wayback,
                    "hops": [],
                    "retrieved_at": "2026-09-27T06:00:00Z",
                    "final_url": wayback,
                    "final_timestamp": stamp,
                    "final_original": url,
                    "http_status": 200,
                    "file": f"snapshots/{number}.body",
                    "bytes": len(body),
                    "sha256": hashlib.sha256(body).hexdigest(),
                }
            )
        )
    (snapshots / "manifest.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = archive.parse_snapshots(REGISTRY, tmp_path)
    assert {(read.source_id, read.variant, read.state, read.rows) for read in result.reads} == {
        ("abc-owned-wabc", "abc-otv-list", ListingState.POPULATED, 14),
        ("abc-owned-wpvi", "abc-legacy-list", ListingState.POPULATED, 187),
        ("flashalert-columbia", "gray-file-flashalert", ListingState.POPULATED, 11),
    }
    assert all(read.mode is ReadMode.ARCHIVE for read in result.reads)
    names = {row.raw_name for row in result.rows if row.source_id == "abc-owned-wabc"}
    assert {"Baldwin UFSD", "Secaucus SD"} <= names
