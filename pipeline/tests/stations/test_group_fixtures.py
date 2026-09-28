"""The Nexstar, TEGNA and Scripps fixtures: bytes, provenance, and what the adapters read.

fixtures/groups/PROVENANCE.json pins each fixture's SHA-256 and the adapter's exact
output (variant, state, row count and every row name); README.md is generated from it
and PROVENANCE.errors.json. The capture and add commands are exercised against a
synthetic server that serves real fixture bodies.
"""

import gzip
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from snowlight.sources.stations import group_fixtures
from snowlight.sources.stations.adapters import ADAPTERS
from snowlight.sources.stations.fixtures import FixtureEntry, Origin
from snowlight.sources.stations.http import USER_AGENT, ConditionalStore, PoliteClient, Timing
from snowlight.sources.stations.model import ListingState, ReadMode, ShapeError

FOLDER = group_fixtures.DEFAULT_FOLDER
ENTRIES = group_fixtures.load_entries(FOLDER)
ERRORS = group_fixtures.load_errors(FOLDER)

VARIANTS = {
    ("nexstar", "nexstar-wp-closings", ListingState.POPULATED),
    ("nexstar", "nexstar-wp-closings", ListingState.EMPTY),
    ("nexstar", "nexstar-app-feed", ListingState.POPULATED),
    ("nexstar", "nexstar-wp-frame", ListingState.DEFERRED),
    ("nexstar", "nexstar-psg-closings", ListingState.EMPTY),
    ("nexstar", "schoolclosingsnet-table", ListingState.EMPTY),
    ("nexstar", "nexstar-ecc-json", ListingState.EMPTY),
    ("nexstar-typed", "nexstar-wp-typed", ListingState.POPULATED),
    ("nexstar-typed", "nexstar-wp-typed-beside", ListingState.POPULATED),
    ("nexstar-typed", "nexstar-typed-page", ListingState.POPULATED),
    ("nexstar-typed", "nexstar-typed-page", ListingState.EMPTY),
    ("tegna", "tegna-closings-module", ListingState.POPULATED),
    ("tegna", "tegna-closings-module", ListingState.EMPTY),
    ("tegna", "tegna-frame", ListingState.DEFERRED),
    ("tegna", "gray-file-flashalert", ListingState.EMPTY),
    ("scripps", "scripps-closings-module", ListingState.POPULATED),
    ("scripps", "scripps-closings-module", ListingState.EMPTY),
    ("scripps", "scripps-frame", ListingState.DEFERRED),
    ("scripps", "gray-file-grid", ListingState.EMPTY),
    ("scripps-typed", "scripps-typed-page", ListingState.POPULATED),
    ("scripps-typed", "scripps-typed-page", ListingState.EMPTY),
}


def test_every_variant_seen_live_has_a_fixture() -> None:
    seen = {(e.adapter, e.expected.variant, e.expected.state) for e in ENTRIES}
    assert seen >= VARIANTS


@pytest.mark.parametrize("entry", ENTRIES, ids=[entry.file for entry in ENTRIES])
def test_fixture_matches_its_provenance(entry: FixtureEntry) -> None:
    body = (FOLDER / entry.file).read_bytes()
    assert hashlib.sha256(body).hexdigest() == entry.sha256
    assert len(body) == entry.bytes
    listing = ADAPTERS[entry.adapter](body)
    assert listing.variant == entry.expected.variant
    assert listing.state is entry.expected.state
    assert tuple(row.name for row in listing.rows) == entry.expected.names
    assert len(listing.rows) == entry.expected.rows
    assert group_fixtures.slice_body(entry.slice, body) == body
    if entry.mode is ReadMode.LIVE:
        assert entry.archive_url is None
        assert entry.captured_at == entry.retrieved_at
    else:
        # The id_ capture the archive served: its own time and original URL.
        assert entry.mode is ReadMode.ARCHIVE
        assert entry.archive_url == (
            f"https://web.archive.org/web/{entry.captured_at:%Y%m%d%H%M%S}id_/{entry.url}"
        )
        assert entry.retrieved_at > entry.captured_at
    # The adapter the registry reads the source with (a typed platform's for its stations).
    assert group_fixtures.adapter_of(entry.source_id) == entry.adapter
    assert entry.file.split("/", 1)[0] == entry.adapter


@pytest.mark.parametrize("item", ERRORS, ids=[item.file for item in ERRORS])
def test_refused_bodies_are_refused(item: group_fixtures.ErrorFixture) -> None:
    body = (FOLDER / item.file).read_bytes()
    assert hashlib.sha256(body).hexdigest() == item.sha256
    with pytest.raises(ShapeError):
        ADAPTERS[item.adapter](body)


def test_every_file_is_recorded_and_the_readme_is_generated() -> None:
    recorded = {entry.file for entry in ENTRIES} | {item.file for item in ERRORS}
    on_disk = {
        path.relative_to(FOLDER).as_posix()
        for path in FOLDER.rglob("*")
        if path.is_file() and path.parent != FOLDER
    }
    assert on_disk == recorded
    readme = (FOLDER / group_fixtures.README_FILE).read_text(encoding="utf-8")
    assert readme == group_fixtures.render_readme(ENTRIES, ERRORS)
    for entry in ENTRIES:
        assert entry.url in readme


# The command line, against a synthetic server serving real fixture bodies ----------------

PAGE = FOLDER / "tegna" / "wtic-page-20260926223946.html"
URL = "https://www.fox61.com/closings"


class Ticker:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 26, 22, 39, 46, tzinfo=UTC)
        self.mono = 0.0

    def clock(self) -> datetime:
        return self.now

    def monotonic(self) -> float:
        return self.mono

    def sleep(self, seconds: float) -> None:
        self.mono += seconds
        self.now += timedelta(seconds=seconds)


def _serve(request: httpx.Request) -> httpx.Response:
    assert request.headers["User-Agent"] == USER_AGENT
    if request.url.path == "/robots.txt":
        return httpx.Response(200, content=b"User-agent: *\nDisallow: /search\n")
    if request.url.path == "/closings":
        return httpx.Response(200, content=PAGE.read_bytes())
    return httpx.Response(403, content=b"denied")


def _client(tmp_path: Path) -> PoliteClient:
    ticker = Ticker()
    return PoliteClient(
        httpx.Client(transport=httpx.MockTransport(_serve), headers={"User-Agent": USER_AGENT}),
        ConditionalStore(tmp_path / "cache"),
        timing=Timing(clock=ticker.clock, monotonic=ticker.monotonic, sleep=ticker.sleep),
    )


def test_capture_then_add_makes_a_fixture(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "log"
    blocked = "https://www.fox61.com/elsewhere"
    code = group_fixtures.main(["capture", "--out", str(out), URL, blocked], _client(tmp_path))
    assert code == 0
    lines = [json.loads(line) for line in (out / "captures.jsonl").read_text().splitlines()]
    assert lines[0]["robots"][0][2] is True
    assert lines[0]["fetched_at"].startswith("2026-09-26T22:39:")
    assert lines[1]["status"] == 403
    assert "file" not in lines[1]
    folder = tmp_path / "fixtures"
    args = ["add", "--log", str(out / "captures.jsonl"), "--url", URL, "--file", "tegna/x.html"]
    args += ["--source", "tegna-wtic", "--slice", "tegna-v1", "--folder", str(folder)]
    assert group_fixtures.main(args) == 0
    (entry,) = group_fixtures.load_entries(folder)
    assert entry.expected.names == ("MDC All Recreational Facilities",)
    assert entry.original_sha256 == hashlib.sha256(PAGE.read_bytes()).hexdigest()
    assert "tegna/x.html: tegna-closings-module, populated, 1 rows" in capsys.readouterr().out
    # A body the adapter reads is not kept as a refused one.
    refused = ["add-error", "--log", str(out / "captures.jsonl"), "--url", URL, "--file"]
    refused += ["errors/x.html", "--source", "tegna-wtic", "--reason", "r", "--folder", str(folder)]
    assert group_fixtures.main(refused) == 1
    assert "not a refused body" in capsys.readouterr().err


def test_add_refuses_a_body_that_is_not_the_logged_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "log"
    assert group_fixtures.main(["capture", "--out", str(out), URL], _client(tmp_path)) == 0
    (line,) = [json.loads(text) for text in (out / "captures.jsonl").read_text().splitlines()]
    (out / line["file"]).write_bytes(b"changed")
    args = ["add", "--log", str(out / "captures.jsonl"), "--url", URL, "--file", "tegna/x.html"]
    args += ["--source", "tegna-wtic", "--folder", str(tmp_path / "f")]
    assert group_fixtures.main(args) == 1
    assert "SHA-256 differs" in capsys.readouterr().err
    other = ["add", "--log", str(out / "captures.jsonl"), "--url", "https://x.test/"]
    other += ["--file", "tegna/y.html", "--source", "tegna-wtic", "--folder", str(tmp_path / "f")]
    assert group_fixtures.main(other) == 1
    assert "no body for" in capsys.readouterr().err


def test_add_error_keeps_a_refused_body(tmp_path: Path) -> None:
    koin = FOLDER / "errors" / "koin-feed-20260926223959.json"
    log = tmp_path / "captures.jsonl"
    (tmp_path / "koin.body").write_bytes(koin.read_bytes())
    record = {
        "url": "https://www.koin.com/wp-json/nxd_app/v1/closings_alerts",
        "fetched_at": "2026-09-26T22:39:59Z",
        "sha256": hashlib.sha256(koin.read_bytes()).hexdigest(),
        "file": "koin.body",
    }
    log.write_text(json.dumps(record) + "\n")
    args = ["add-error", "--log", str(log), "--url", record["url"], "--file", "errors/k.json"]
    args += ["--source", "nexstar-koin", "--reason", "nameless", "--folder", str(tmp_path / "f")]
    assert group_fixtures.main(args) == 0
    (item,) = group_fixtures.load_errors(tmp_path / "f")
    assert (item.adapter, item.reason) == ("nexstar", "nameless")


def test_a_slice_that_reads_differently_from_its_original_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = PAGE.read_bytes()
    other = (FOLDER / "tegna" / "wusa-page-20260926224806.html").read_bytes()
    # A synthetic slicing method that returns another real body.
    monkeypatch.setitem(group_fixtures.SLICERS, "synthetic-wrong", lambda _body: other)
    origin = Origin("tegna-wtic", "tegna", ReadMode.LIVE, URL, "", None, "")
    with pytest.raises(ValueError, match="does not read as the original"):
        group_fixtures.make_entry("tegna/x.html", origin, page, "synthetic-wrong")
    # A synthetic method whose output changes when applied again.
    monkeypatch.setitem(group_fixtures.SLICERS, "synthetic-growing", lambda body: body + b" ")
    with pytest.raises(ValueError, match="changes it"):
        group_fixtures.make_entry("tegna/x.html", origin, page, "synthetic-growing")


def _artifact(tmp_path: Path, body: bytes, **record: object) -> Path:
    """A synthetic snapshot artifact holding one real body under a synthetic manifest line."""
    root = tmp_path / "snapshots-1"
    (root / "snapshots").mkdir(parents=True)
    (root / "snapshots" / "a.body").write_bytes(body)
    line = {
        "timestamp": "20240116060000",
        "url": URL,
        "requested": f"https://web.archive.org/web/20240116060000id_/{URL}",
        "retrieved_at": "2026-09-27T01:00:00Z",
        "final_timestamp": "20240116060700",
        "final_original": URL,
        "http_status": 200,
        "file": "snapshots/a.body",
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    } | record
    (root / "snapshots" / "manifest.jsonl").write_text(json.dumps(line) + "\n")
    return root


def test_add_archived_records_the_capture_the_archive_served(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    page = PAGE.read_bytes()
    root = _artifact(tmp_path, gzip_bytes(page))
    folder = tmp_path / "fixtures"
    args = ["add-archived", "--artifacts", str(tmp_path), "--timestamp", "20240116060000"]
    args += ["--url", URL, "--file", "tegna/a.html", "--source", "tegna-wtic"]
    args += ["--slice", "tegna-v1", "--folder", str(folder)]
    assert group_fixtures.main(args) == 0
    (entry,) = group_fixtures.load_entries(folder)
    assert entry.mode is ReadMode.ARCHIVE
    assert entry.captured_at == datetime(2024, 1, 16, 6, 7, tzinfo=UTC)
    assert entry.archive_url == f"https://web.archive.org/web/20240116060700id_/{URL}"
    assert entry.retrieved_at == datetime(2026, 9, 27, 1, 0, tzinfo=UTC)
    assert entry.original_sha256 == hashlib.sha256(gzip_bytes(page)).hexdigest()
    assert entry.expected.names == ("MDC All Recreational Facilities",)
    assert "captured 2024-01-16T06:07:00Z" in capsys.readouterr().out
    # The body on disk must be the one the manifest recorded.
    (root / "snapshots" / "a.body").write_bytes(page)
    assert group_fixtures.main([*args[:-1], str(tmp_path / "other")]) == 1
    assert "SHA-256 differs" in capsys.readouterr().err


def test_add_archived_refuses_a_capture_not_downloaded_or_not_asked_for(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _artifact(tmp_path, b"x", file=None, sha256=None, error="HTTP 404")
    args = ["add-archived", "--artifacts", str(tmp_path), "--timestamp", "20240116060000"]
    args += ["--url", URL, "--file", "tegna/a.html", "--source", "tegna-wtic"]
    args += ["--folder", str(tmp_path / "f")]
    assert group_fixtures.main(args) == 1
    assert "was not downloaded: HTTP 404" in capsys.readouterr().err
    args[4] = "20240116060001"
    assert group_fixtures.main(args) == 1
    assert "holds the capture 20240116060001" in capsys.readouterr().err


def gzip_bytes(body: bytes) -> bytes:
    """Gzip ``body`` reproducibly (a fixed modification time)."""
    return gzip.compress(body, mtime=0)


def test_add_error_keeps_a_refused_archived_body(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    parked = (FOLDER / "errors" / "wdaf-cgs-20201107163159.html").read_bytes()
    _artifact(tmp_path, parked)
    folder = tmp_path / "f"
    args = ["add-error", "--artifacts", str(tmp_path), "--url", URL, "--file", "errors/p.html"]
    args += ["--source", "nexstar-wdaf", "--reason", "parked", "--folder", str(folder)]
    assert group_fixtures.main(args) == 1
    assert "--artifacts needs --timestamp" in capsys.readouterr().err
    assert group_fixtures.main([*args, "--timestamp", "20240116060000"]) == 0
    (item,) = group_fixtures.load_errors(folder)
    assert item.archive_url == f"https://web.archive.org/web/20240116060700id_/{URL}"
    assert item.captured_at == datetime(2024, 1, 16, 6, 7, tzinfo=UTC)
    assert "([capture](https://web.archive.org/web/" in (folder / "README.md").read_text()
