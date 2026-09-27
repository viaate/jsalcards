"""Every adapter fixture: its bytes, its provenance record, and what the adapter reads.

PROVENANCE.json pins each fixture's SHA-256 and the adapter's exact output (variant,
state, row count and every row name); README.md is generated from it.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from snowlight.cli import main
from snowlight.sources.stations import fixtures
from snowlight.sources.stations.adapters import ADAPTERS
from snowlight.sources.stations.http import ConditionalStore, Fetched
from snowlight.sources.stations.model import ListingState, ReadMode

FOLDER = Path(__file__).parent / "fixtures"
ENTRIES = fixtures.load_entries(FOLDER)


# Every variant ``snowlight stations archive parse`` read (as a list or as a page on
# the way to one) over all the captures downloaded by round 2.
VARIANTS_SEEN_IN_THE_ARCHIVE = {
    ("gray", "gray-api-count"),
    ("gray", "gray-api-orgs"),
    ("gray", "gray-blox-script"),
    ("gray", "gray-file-cgs"),
    ("gray", "gray-file-count-json"),
    ("gray", "gray-file-flashalert"),
    ("gray", "gray-file-grid"),
    ("gray", "gray-file-mobile-cells"),
    ("gray", "gray-file-newsticker"),
    ("gray", "gray-file-newsticker-xml"),
    ("gray", "gray-file-sc-para"),
    ("gray", "gray-file-sc-script"),
    ("gray", "gray-file-sc-xml"),
    ("gray", "gray-file-ticker-xml"),
    ("gray", "gray-frame"),
    ("gray", "gray-fusion-count"),
    ("gray", "gray-fusion-frame"),
    ("gray", "gray-fusion-lazy"),
    ("gray", "gray-fusion-orgs"),
    ("gray", "gray-gdm-list"),
    ("gray", "gray-gdm-script"),
    ("gray", "gray-gdm-table"),
    ("gray", "gray-heartland-newsticker"),
    ("gray", "gray-heartland-sc-para"),
    ("gray", "gray-s3-json"),
    ("hearst", "hearst-ibsys"),
    ("hearst", "hearst-next"),
    ("hearst", "hearst-rows"),
}


def test_there_are_fixtures_for_every_adapter_variant_seen() -> None:
    variants = {(entry.adapter, entry.expected.variant) for entry in ENTRIES}
    assert variants >= VARIANTS_SEEN_IN_THE_ARCHIVE
    states = {(entry.expected.variant, entry.expected.state) for entry in ENTRIES}
    assert ("hearst-rows", ListingState.EMPTY) in states
    assert ("gray-fusion-orgs", ListingState.EMPTY) in states
    assert ("gray-fusion-count", ListingState.COUNT_ONLY) in states
    assert ("gray-s3-json", ListingState.EMPTY) in states
    assert ("hearst-next", ListingState.EMPTY) in states
    assert ("gray-gdm-table", ListingState.EMPTY) in states
    assert ("gray-gdm-table", ListingState.POPULATED) in states
    assert ("hearst-ibsys", ListingState.EMPTY) in states
    assert ("hearst-ibsys", ListingState.POPULATED) in states
    for variant in (
        "gray-file-newsticker",
        "gray-file-newsticker-xml",
        "gray-file-sc-xml",
        "gray-file-sc-para",
        "gray-file-grid",
        "gray-file-flashalert",
        "gray-file-ticker-xml",
        "gray-file-mobile-cells",
    ):
        assert (variant, ListingState.POPULATED) in states, variant
        assert (variant, ListingState.EMPTY) in states, variant


@pytest.mark.parametrize("entry", ENTRIES, ids=[entry.file for entry in ENTRIES])
def test_fixture_matches_its_provenance(entry: fixtures.FixtureEntry) -> None:
    body = (FOLDER / entry.file).read_bytes()
    assert hashlib.sha256(body).hexdigest() == entry.sha256
    assert len(body) == entry.bytes
    listing = ADAPTERS[entry.adapter](body)
    assert listing.variant == entry.expected.variant
    assert listing.state is entry.expected.state
    assert len(listing.rows) == entry.expected.rows
    assert tuple(row.name for row in listing.rows) == entry.expected.names
    assert (entry.expected.state is ListingState.POPULATED) == (entry.expected.rows > 0)
    if entry.mode is ReadMode.ARCHIVE:
        assert entry.archive_url is not None
        assert entry.archive_url.endswith("id_/" + entry.url)
        stamp = entry.captured_at.strftime("%Y%m%d%H%M%S")
        assert f"/web/{stamp}id_/" in entry.archive_url


@pytest.mark.parametrize("entry", ENTRIES, ids=[entry.file for entry in ENTRIES])
def test_slicing_a_fixture_again_changes_nothing(entry: fixtures.FixtureEntry) -> None:
    body = (FOLDER / entry.file).read_bytes()
    assert fixtures.slice_body(entry.slice, body) == body


def test_readme_is_generated_from_the_provenance() -> None:
    readme = (FOLDER / fixtures.README_FILE).read_text(encoding="utf-8")
    assert readme == fixtures.render_readme(ENTRIES, FOLDER)
    for name in ("www.kmbc.com.robots.txt", "usa-tvdma-county.slice.csv"):
        assert name in readme


def test_every_fixture_file_is_recorded() -> None:
    recorded = {entry.file for entry in ENTRIES}
    on_disk = {
        path.relative_to(FOLDER).as_posix()
        for path in FOLDER.rglob("*")
        if path.is_file() and path.parent.name in {"hearst", "gray"}
    }
    assert on_disk == recorded


def _live_setup(tmp_path: Path, sha: str) -> tuple[Path, Path, str, bytes]:
    """A fetch's cache and run manifest around a real live fixture body (layout synthetic)."""
    url = "https://www.wcvb.com/weather/closings"
    body = (FOLDER / "hearst" / "wcvb-live-20260926180111.html").read_bytes()
    fetched = Fetched(
        url=url,
        final_url=url,
        status=200,
        body=body,
        sha256=hashlib.sha256(body).hexdigest(),
        fetched_at=datetime(2026, 9, 26, 18, 1, 11, tzinfo=UTC),
        not_modified=False,
        content_type="text/html",
        etag=None,
        last_modified=None,
    )
    ConditionalStore(tmp_path / "cache").save(fetched)
    manifest = tmp_path / "manifest.json"
    snapshot = {
        "source_id": "hearst-wcvb",
        "url": url,
        "fetched_at": "2026-09-26T18:01:11Z",
        "http_status": 200,
        "sha256": sha,
        "bytes": len(body),
        "error": None,
    }
    manifest.write_text(json.dumps({"snapshots": [snapshot]}), encoding="utf-8")
    return tmp_path / "cache", manifest, url, body


def test_add_live_turns_a_fetched_body_into_a_fixture(tmp_path: Path) -> None:
    body = (FOLDER / "hearst" / "wcvb-live-20260926180111.html").read_bytes()
    cache, manifest, url, _ = _live_setup(tmp_path, hashlib.sha256(body).hexdigest())
    out = tmp_path / "fixtures"
    args = ["stations", "fixture", "add-live", "--url", url, "--file", "hearst/x.html"]
    args += ["--slice", "hearst-page-v1", "--manifest", str(manifest), "--cache-dir", str(cache)]
    assert main([*args, "--fixtures", str(out)]) == 0
    (entry,) = fixtures.load_entries(out)
    assert (entry.mode, entry.archive_url, entry.expected.rows) == (ReadMode.LIVE, None, 5)
    assert entry.captured_at == entry.retrieved_at
    assert (out / "hearst" / "x.html").read_bytes() == body


def test_add_live_refuses_a_body_the_run_did_not_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cache, manifest, url, _ = _live_setup(tmp_path, "0" * 64)
    args = ["stations", "fixture", "add-live", "--url", url, "--file", "hearst/x.html"]
    args += ["--manifest", str(manifest), "--cache-dir", str(cache)]
    assert main([*args, "--fixtures", str(tmp_path / "f")]) == 1
    assert "not the one the run read" in capsys.readouterr().err
    other = ["stations", "fixture", "add-live", "--url", "https://x.test/", "--file", "a/b.html"]
    assert main([*other, "--manifest", str(manifest), "--cache-dir", str(cache)]) == 1


def test_a_slice_that_reads_differently_from_its_original_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = (FOLDER / "gray" / "kctv-20181009230234.html").read_bytes()
    other = (FOLDER / "gray" / "kctv-export-20240128101402.json").read_bytes()
    # A synthetic slicing method that returns another real body.
    monkeypatch.setitem(fixtures.SLICERS, "synthetic-wrong", lambda _body: other)
    origin = fixtures.Origin("gray-kctv", "gray", ReadMode.LIVE, "https://x.test/", "", None, "")
    with pytest.raises(ValueError, match="does not read as the original"):
        fixtures.make_entry("gray/x.html", origin, page, "synthetic-wrong")
