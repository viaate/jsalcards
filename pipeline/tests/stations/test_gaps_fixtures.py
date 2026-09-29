"""Part 4's fixtures: bytes, provenance, and the fixture commands.

fixtures/gaps/PROVENANCE.json pins each fixture's SHA-256 and the adapter's exact
output (variant, state, row count and every row name); README.md is generated from
it and PROVENANCE.errors.json. Every fixture is a real body (live or archived); the
capture and add commands are exercised against a synthetic server that serves real
fixture bodies, and against a synthetic artifact folder holding one.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from snowlight.sources.stations import gap_fixtures
from snowlight.sources.stations.adapters import adapter_for
from snowlight.sources.stations.fixtures import FixtureEntry
from snowlight.sources.stations.http import USER_AGENT, ConditionalStore, PoliteClient, Timing
from snowlight.sources.stations.model import ListingState, ReadMode, ShapeError
from snowlight.sources.stations.registry import load_registry

FOLDER = gap_fixtures.DEFAULT_FOLDER
ENTRIES = gap_fixtures.load_entries(FOLDER)
ERRORS = gap_fixtures.load_errors(FOLDER)
REGISTRY = load_registry()
TICKER = "https://company-wide-tickers.s3.us-west-2.amazonaws.com/KULR_School_Results/closings.html"

VARIANTS = {
    ("coesheet", "coesheet-page", ListingState.DEFERRED),
    ("coesheet", "coesheet-widget", ListingState.DEFERRED),
    ("coesheet", "coesheet-table", ListingState.POPULATED),
    ("coesheet", "coesheet-csv", ListingState.POPULATED),
    ("cowles", "closings-grid", ListingState.EMPTY),
    ("cowles", "cowles-page", ListingState.DEFERRED),
    ("flathead", "flathead-closure-tables", ListingState.POPULATED),
    ("gohsep", "gohsep-feature-query", ListingState.POPULATED),
    ("apptegy", "apptegy-nuxt-state", ListingState.POPULATED),
    ("apptegy", "apptegy-nuxt-state", ListingState.EMPTY),
    ("smartsites", "smartsites-popup-alerts", ListingState.POPULATED),
    ("smartsites", "smartsites-popup-alerts", ListingState.EMPTY),
    ("finalsite", "finalsite-page-pops", ListingState.POPULATED),
    ("finalsite", "finalsite-no-page-pops", ListingState.EMPTY),
    ("finalsite", "finalsite-homepage", ListingState.DEFERRED),
    ("pasco", "pasco-emergency-banner", ListingState.EMPTY),
    ("dadeschools", "dadeschools-alerts", ListingState.EMPTY),
}


# Variants seen in archived captures (archive-captures runs 36317448357 and 36341776194).
ARCHIVED_VARIANTS = {
    ("flathead", "flathead-card-tables", ListingState.POPULATED),
    ("flathead", "flathead-closure-tables", ListingState.POPULATED),
    ("coesheet", "coesheet-page", ListingState.DEFERRED),
    ("coesheet", "coesheet-widget", ListingState.DEFERRED),
    # archive-captures run 36341776194: the district homepages' older forms
    ("apptegy", "apptegy-nuxt2-state", ListingState.POPULATED),
    ("apptegy", "apptegy-nuxt2-state", ListingState.EMPTY),
    ("apptegy", "apptegy-nuxt-state", ListingState.EMPTY),
    ("apptegy", "schoolwires-important-announcements", ListingState.POPULATED),
    ("smartsites", "schoolwires-important-announcements", ListingState.POPULATED),
    ("smartsites", "schoolwires-important-announcements", ListingState.EMPTY),
    ("smartsites", "smartsites-popup-alerts", ListingState.POPULATED),
    ("pasco", "pasco-emergency-banner", ListingState.POPULATED),
    ("pasco", "pasco-red-rectangle", ListingState.POPULATED),
    ("dadeschools", "dadeschools-alerts", ListingState.POPULATED),
    # archive-captures runs 36341776194 and 36445058527: Finalsite homepages of other
    # years (a changed page ID, pops held in the page) and Web Community Manager
    ("finalsite", "finalsite-homepage", ListingState.DEFERRED),
    ("finalsite", "finalsite-homepage-pops", ListingState.POPULATED),
    ("finalsite", "schoolwires-important-announcements", ListingState.POPULATED),
}


def test_every_variant_seen_live_or_archived_has_a_fixture() -> None:
    seen = {(e.adapter, e.expected.variant, e.expected.state) for e in ENTRIES}
    assert seen >= VARIANTS
    archived = {
        (e.adapter, e.expected.variant, e.expected.state)
        for e in ENTRIES
        if e.mode is ReadMode.ARCHIVE
    }
    assert archived >= ARCHIVED_VARIANTS


@pytest.mark.parametrize("entry", ENTRIES, ids=[entry.file for entry in ENTRIES])
def test_fixture_matches_its_provenance(entry: FixtureEntry) -> None:
    body = (FOLDER / entry.file).read_bytes()
    assert hashlib.sha256(body).hexdigest() == entry.sha256
    assert len(body) == entry.bytes
    listing = adapter_for(entry.adapter)(body)
    assert listing.variant == entry.expected.variant
    assert listing.state is entry.expected.state
    assert tuple(row.name for row in listing.rows) == entry.expected.names
    assert len(listing.rows) == entry.expected.rows
    assert gap_fixtures.SLICERS[entry.slice](body) == body
    station = REGISTRY.stations[entry.source_id]
    assert REGISTRY.platform_of(station).adapter == entry.adapter
    assert entry.file.split("/", 1)[0] == entry.adapter
    assert entry.url in {station.page_url, station.data_url, *station.archive_urls}
    if entry.mode is ReadMode.LIVE:
        assert entry.archive_url is None
        assert entry.captured_at == entry.retrieved_at
    else:
        assert entry.archive_url == (
            f"https://web.archive.org/web/{entry.captured_at:%Y%m%d%H%M%S}id_/{entry.url}"
        )
        assert entry.retrieved_at > entry.captured_at


def test_readme_is_generated_from_the_provenance() -> None:
    readme = (FOLDER / "README.md").read_text(encoding="utf-8")
    assert readme == gap_fixtures.render_readme(ENTRIES, ERRORS, FOLDER)


def test_refused_bodies_are_refused() -> None:
    for item in ERRORS:
        body = (FOLDER / item.file).read_bytes()
        assert hashlib.sha256(body).hexdigest() == item.sha256
        with pytest.raises(ShapeError):
            adapter_for(item.adapter)(body)


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 27, 11, 25, tzinfo=UTC)
        self.mono = 0.0

    def clock(self) -> datetime:
        return self.now

    def monotonic(self) -> float:
        return self.mono

    def sleep(self, seconds: float) -> None:
        self.mono += seconds
        self.now += timedelta(seconds=seconds)


def _server(request: httpx.Request) -> httpx.Response:
    assert request.headers["User-Agent"] == USER_AGENT
    if request.url.path == "/robots.txt":
        return httpx.Response(403)
    if str(request.url) == TICKER:
        return httpx.Response(
            200,
            headers={"Last-Modified": "Thu, 16 Apr 2026 15:18:17 GMT"},
            content=(FOLDER / "cowles/ticker-live-20260927.html").read_bytes(),
        )
    return httpx.Response(403, content=b"<html>Access Denied</html>")


def test_capture_then_add_makes_a_live_fixture(tmp_path: Path) -> None:
    clock = _Clock()
    client = PoliteClient(
        httpx.Client(transport=httpx.MockTransport(_server), headers={"User-Agent": USER_AGENT}),
        ConditionalStore(tmp_path / "cache"),
        timing=Timing(clock=clock.clock, monotonic=clock.monotonic, sleep=clock.sleep),
    )
    blocked = "https://blocked.example.org/closings"
    out = tmp_path / "log"
    assert gap_fixtures.main(["capture", "--out", str(out), TICKER, blocked], client=client) == 0
    lines = [json.loads(line) for line in (out / "captures.jsonl").read_text().splitlines()]
    assert [(line["url"], line["status"]) for line in lines] == [(TICKER, 200), (blocked, 403)]
    folder = tmp_path / "fixtures"
    argv = ["add", "--log", str(out / "captures.jsonl"), "--url", TICKER]
    argv += ["--file", "cowles/t.html", "--source", "cowles-kulr", "--slice", "cowles-v1"]
    assert gap_fixtures.main([*argv, "--folder", str(folder)]) == 0
    (entry,) = gap_fixtures.load_entries(folder)
    assert (entry.expected.variant, entry.expected.state) == ("closings-grid", ListingState.EMPTY)
    assert entry.mode is ReadMode.LIVE
    # The blocked URL has no body to make a fixture of.
    log = str(out / "captures.jsonl")
    argv = ["add", "--log", log, "--url", blocked, "--file", "cowles/b.html"]
    assert gap_fixtures.main([*argv, "--source", "cowles-kulr", "--folder", str(folder)]) == 1
    # A body the adapter reads is not a refused body.
    argv = ["add-error", "--log", str(out / "captures.jsonl"), "--url", TICKER]
    argv += ["--file", "errors/t.html", "--source", "cowles-kulr", "--reason", "x"]
    assert gap_fixtures.main([*argv, "--folder", str(folder)]) == 1


def test_add_archived_reads_the_manifest_and_checks_the_bytes(tmp_path: Path) -> None:
    body = (FOLDER / "cowles/ticker-live-20260927.html").read_bytes()
    run = tmp_path / "snapshots-1" / "snapshots"
    run.mkdir(parents=True)
    (run / "a.body").write_bytes(body)
    # A SYNTHETIC manifest line in the workflow's format, for a real body.
    record = {
        "timestamp": "20260101120000",
        "url": TICKER,
        "requested": f"https://web.archive.org/web/20260101120000id_/{TICKER}",
        "hops": [],
        "retrieved_at": "2026-09-27T12:00:00Z",
        "final_timestamp": "20260101115959",
        "final_original": TICKER,
        "http_status": 200,
        "file": "snapshots/a.body",
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }
    (run / "manifest.jsonl").write_text(json.dumps(record) + "\n")
    origin, read = gap_fixtures.archived_body(tmp_path, "20260101120000", TICKER)
    assert read == body
    assert origin.archive_url == f"https://web.archive.org/web/20260101115959id_/{TICKER}"
    assert origin.captured_at == "2026-01-01T11:59:59Z"
    (run / "a.body").write_bytes(body + b" ")
    with pytest.raises(gap_fixtures.CaptureError):
        gap_fixtures.archived_body(tmp_path, "20260101120000", TICKER)
    with pytest.raises(gap_fixtures.CaptureError):
        gap_fixtures.archived_body(tmp_path, "20250101120000", TICKER)


def test_add_error_keeps_a_real_body_an_adapter_refuses(tmp_path: Path) -> None:
    # A real body (Shasta's sheet, CSV output) served back, and kept as one the Cowles
    # adapter must refuse; written to a temporary folder only.
    body = (FOLDER / "coesheet/shasta-sheet-live-20260927.csv").read_bytes()

    def serve(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, content=body)

    clock = _Clock()
    client = PoliteClient(
        httpx.Client(transport=httpx.MockTransport(serve), headers={"User-Agent": USER_AGENT}),
        ConditionalStore(tmp_path / "cache"),
        timing=Timing(clock=clock.clock, monotonic=clock.monotonic, sleep=clock.sleep),
    )
    url = "https://sheet.example.org/closures.csv"
    out = tmp_path / "log"
    assert gap_fixtures.main(["capture", "--out", str(out), url], client=client) == 0
    folder = tmp_path / "fixtures"
    argv = ["add-error", "--log", str(out / "captures.jsonl"), "--url", url]
    argv += ["--file", "errors/sheet.csv", "--source", "cowles-kulr", "--reason", "not a grid"]
    assert gap_fixtures.main([*argv, "--folder", str(folder)]) == 0
    (item,) = gap_fixtures.load_errors(folder)
    assert (item.adapter, item.reason, item.bytes) == ("cowles", "not a grid", len(body))
    readme = (folder / "README.md").read_text(encoding="utf-8")
    assert "## Bodies the adapters refuse (`errors/`)" in readme
    assert "| `errors/sheet.csv` | cowles-kulr |" in readme
