"""The coverage gate's fixtures: bytes, provenance, README, and the fixture command.

fixtures/gate/PROVENANCE.json pins each fixture's SHA-256 and the adapter's exact
output; README.md is generated from it and PROVENANCE.errors.json. Every fixture is
a real archived body. The command is exercised against a temporary artifact folder
holding a real fixture body under a SYNTHETIC manifest line (in the workflow's
format), the way part 4's fixture tests do.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from snowlight.sources.stations import gate_fixtures
from snowlight.sources.stations.adapters import adapter_for
from snowlight.sources.stations.fixtures import Origin
from snowlight.sources.stations.http import ConditionalStore, Fetched
from snowlight.sources.stations.model import ReadMode, ShapeError

FOLDER = gate_fixtures.DEFAULT_FOLDER
ENTRIES = gate_fixtures.load_entries(FOLDER)
ERRORS = gate_fixtures.load_errors(FOLDER)
CLARKE = "https://www.clarkecountyschools.org/"


def test_provenance_and_readme_agree_with_the_files() -> None:
    assert ENTRIES
    for entry in ENTRIES:
        body = (FOLDER / entry.file).read_bytes()
        assert hashlib.sha256(body).hexdigest() == entry.sha256, entry.file
        if entry.mode is ReadMode.ARCHIVE:
            assert entry.archive_url is not None
            assert entry.archive_url.endswith(entry.url)
        else:
            assert entry.archive_url is None
        assert entry.slice in gate_fixtures.SLICERS
    for item in ERRORS:
        body = (FOLDER / item.file).read_bytes()
        assert hashlib.sha256(body).hexdigest() == item.sha256
        with pytest.raises(ShapeError):
            adapter_for(item.adapter)(body)
    readme = gate_fixtures.render_readme(ENTRIES, ERRORS)
    assert (FOLDER / gate_fixtures.README_FILE).read_text(encoding="utf-8") == readme
    kept = {gate_fixtures.PROVENANCE_FILE, gate_fixtures.ERRORS_FILE, gate_fixtures.README_FILE}
    listed = {
        path.relative_to(FOLDER).as_posix()
        for path in FOLDER.rglob("*")
        if path.is_file() and path.relative_to(FOLDER).as_posix() not in kept
    }
    assert listed == {entry.file for entry in ENTRIES} | {item.file for item in ERRORS}


def _artifacts(tmp_path: Path, body: bytes, url: str) -> Path:
    run = tmp_path / "artifacts" / "snapshots-1" / "snapshots"
    run.mkdir(parents=True)
    (run / "a.body").write_bytes(body)
    # A SYNTHETIC manifest line in the workflow's format, for a real body.
    record = {
        "timestamp": "20201030120000",
        "url": url,
        "requested": f"https://web.archive.org/web/20201030120000id_/{url}",
        "hops": [],
        "retrieved_at": "2026-09-29T02:00:00Z",
        "final_timestamp": "20201030135632",
        "final_original": url,
        "http_status": 200,
        "file": "snapshots/a.body",
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }
    (run / "manifest.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    return tmp_path / "artifacts"


def test_add_archived_and_add_archived_error(tmp_path: Path) -> None:
    body = (FOLDER / "wcm/clarke-20201030.html").read_bytes()
    artifacts = _artifacts(tmp_path, body, CLARKE)
    folder = tmp_path / "gate"
    base = ["--artifacts", str(artifacts), "--timestamp", "20201030120000", "--url", CLARKE]
    code = gate_fixtures.main(
        [
            "add-archived",
            *base,
            "--file",
            "wcm/clarke.html",
            "--source",
            "finalsite-clarke-al",
            "--slice",
            "wcm-v1",
            "--folder",
            str(folder),
            "--note",
            "a note",
        ]
    )
    assert code == 0
    (entry,) = gate_fixtures.load_entries(folder)
    assert (entry.adapter, entry.expected.rows, entry.note) == ("finalsite", 4, "a note")
    assert entry.captured_at.isoformat() == "2020-10-30T13:56:32+00:00"
    assert "wcm/clarke.html" in (folder / "README.md").read_text(encoding="utf-8")
    # The finalsite adapter reads the page: it is no refused body.
    refused = ["add-archived-error", *base, "--file", "errors/x.html", "--source"]
    assert gate_fixtures.main([*refused, "finalsite-clarke-al", "--reason", "r"]) == 1
    # The Cowles adapter refuses it: kept under errors/ with the reason. (District
    # readers no longer refuse an HTML page: they read one in no known form by its text.)
    code = gate_fixtures.main(
        [*refused, "cowles-x", "--reason", "not a Cowles page", "--folder", str(folder)]
    )
    assert code == 0
    (item,) = gate_fixtures.load_errors(folder)
    assert (item.adapter, item.reason) == ("cowles", "not a Cowles page")
    # A capture the manifest does not hold fails.
    missing = ["add-archived", "--artifacts", str(artifacts), "--timestamp", "20190101000000"]
    missing += ["--url", CLARKE, "--file", "wcm/y.html", "--source", "finalsite-clarke-al"]
    assert gate_fixtures.main([*missing, "--folder", str(folder)]) == 1


def test_add_from_a_capture_log(tmp_path: Path) -> None:
    body = (FOLDER / "wcm/clarke-20201030.html").read_bytes()
    log = tmp_path / "captures.jsonl"
    (tmp_path / "b.body").write_bytes(body)
    # A SYNTHETIC capture-log line (the gap-state part's capture format) for a real body.
    record = {
        "url": CLARKE,
        "final_url": CLARKE,
        "status": 200,
        "fetched_at": "2026-09-29T02:00:00Z",
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
        "file": "b.body",
    }
    log.write_text(json.dumps(record) + "\n", encoding="utf-8")
    folder = tmp_path / "gate"
    code = gate_fixtures.main(
        [
            "add",
            "--log",
            str(log),
            "--url",
            CLARKE,
            "--file",
            "wcm/clarke-live.html",
            "--source",
            "finalsite-clarke-al",
            "--adapter",
            "finalsite",
            "--slice",
            "wcm-v1",
            "--folder",
            str(folder),
        ]
    )
    assert code == 0
    (entry,) = gate_fixtures.load_entries(folder)
    assert entry.mode is ReadMode.LIVE
    assert entry.archive_url is None


def test_a_slice_that_reads_differently_is_refused() -> None:
    body = (FOLDER / "wcm/clarke-20201030.html").read_bytes()
    origin = Origin(
        source_id="finalsite-clarke-al",
        adapter="finalsite",
        mode=ReadMode.ARCHIVE,
        url=CLARKE,
        captured_at="2020-10-30T13:56:32Z",
        archive_url=f"https://web.archive.org/web/20201030135632id_/{CLARKE}",
        retrieved_at="2026-09-29T02:00:00Z",
    )
    # The googlesites slicer empties a WCM page, which the adapter then reads as a page
    # showing nothing (its text), not as the populated announcements of the original.
    with pytest.raises(ValueError, match="does not read as the original does"):
        gate_fixtures.make_entry("wcm/z.html", origin, body, "googlesites-v1")


def test_add_fetched_takes_the_body_the_live_fetch_kept(tmp_path: Path) -> None:
    body = (FOLDER / "sharpschool/lee-alerts-live-20261003.json").read_bytes()
    url = "https://www.leeschools.net/WebServices/UnifiedPublishing/" + (
        "UnifiedPublishingService.asmx/GetActiveAlerts"
    )
    store = ConditionalStore(tmp_path / "store")
    when = datetime(2026, 10, 3, 21, 45, 29, tzinfo=UTC)
    fetched = Fetched(
        url=url,
        final_url=url,
        status=200,
        body=body,
        sha256=hashlib.sha256(body).hexdigest(),
        fetched_at=when,
        not_modified=False,
        content_type="application/json; charset=utf-8",
        etag=None,
        last_modified=None,
        robots=(),
    )
    store.save(fetched)
    # A SYNTHETIC run manifest naming the real body's read.
    manifest = tmp_path / "manifest.json"
    read = {"source_id": "sharpschool-lee-fl", "url": url, "fetched_at": "2026-10-03T21:45:29Z"}
    manifest.write_text(
        json.dumps({"snapshots": [{**read, "sha256": fetched.sha256}]}), encoding="utf-8"
    )
    folder = tmp_path / "gate"
    argv = ["add-fetched", "--manifest", str(manifest), "--cache-dir", str(tmp_path / "store")]
    argv += ["--url", url, "--file", "sharpschool/x.json", "--source", "sharpschool-lee-fl"]
    assert gate_fixtures.main([*argv, "--folder", str(folder)]) == 0
    (entry,) = gate_fixtures.load_entries(folder)
    assert (entry.mode, entry.adapter, entry.expected.variant) == (
        ReadMode.LIVE,
        "sharpschool",
        "sharpschool-alerts",
    )
    assert entry.captured_at == when
    # A store holding another body than the run read is refused.
    manifest.write_text(json.dumps({"snapshots": [{**read, "sha256": "0" * 64}]}), "utf-8")
    assert gate_fixtures.main([*argv, "--folder", str(folder)]) == 1
    # So is a URL the run never read.
    manifest.write_text(json.dumps({"snapshots": []}), encoding="utf-8")
    assert gate_fixtures.main([*argv, "--folder", str(folder)]) == 1
