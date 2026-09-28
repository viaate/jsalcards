"""The proven share: stations whose list has been seen populated at least once.

The registries, school tables, reads and fixture provenance files built here are
synthetic (every URL is under .test); the real evidence is exercised by
``snowlight stations coverage``.
"""

import hashlib
import json
import struct
import zlib
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import polars as pl
import pytest
import yaml  # type: ignore[import-untyped, unused-ignore]
from shapely.geometry import box

from snowlight.output import JSONValue
from snowlight.sources.stations import coverage, proof
from snowlight.sources.stations.mapimage import project, render
from snowlight.sources.stations.model import HealthStatus, SourceHealth
from snowlight.sources.stations.registry import load_registry

TERMS = {
    "automated_access": "permitted",
    "summary": "synthetic",
    "evidence": [
        {
            "url": "https://x.test/t",
            "read_at": "2026-09-25T00:00:00Z",
            "sha256": None,
            "excerpt": ["ok"],
        }
    ],
}
SCHOOLS = pl.DataFrame(
    {
        "state": ["KS", "KS", "MO", "MO"],
        "county_fips": ["20091", "20091", "29095", "29047"],
        "county_name": ["Johnson County", "Johnson County", "Jackson County", "Clay County"],
    }
)
SHA = "a" * 64


def _station(sid: str, fips: list[str], data_url: str | None = None) -> dict[str, object]:
    return {
        "id": sid,
        "platform": "synthetic",
        "call_sign": sid.split("-")[1].upper() + "XXX",
        "name": sid,
        "market": "Kansas City",
        "dma": None,
        "states": ["KS", "MO"],
        "counties": {"basis": "dma", "source": "synthetic", "fips": fips},
        "page_url": f"https://{sid}.test/closings",
        "data_url": data_url,
        "archive_urls": [f"https://old-{sid}.test/list.html"],
        "poll_minutes": None,
        "status": "active",
        "evidence": "synthetic",
    }


def _registry(tmp_path: Path) -> Path:
    folder = tmp_path / "sources"
    folder.mkdir()
    content = {
        "platform": {
            "id": "synthetic",
            "name": "synthetic",
            "operator": "synthetic",
            "adapter": "gray",
            "poll_minutes": 10,
            "terms": TERMS,
            "notes": "synthetic",
        },
        "stations": [
            _station("synthetic-a", ["20091"]),
            _station("synthetic-b", ["29095"], "https://synthetic-b.test/data.json"),
            _station("synthetic-c", ["29047"]),
        ],
    }
    (folder / "synthetic.yaml").write_text(yaml.safe_dump(content), encoding="utf-8")
    return folder


def _read(sid: str, url: str, when: str, rows: int, mode: str = "archive") -> dict[str, object]:
    return {
        "source_id": sid,
        "mode": mode,
        "url": url,
        "fetched_at": when,
        "retrieved_at": "2026-09-27T01:00:00Z",
        "sha256": SHA,
        "bytes": 10,
        "variant": "synthetic",
        "state": "populated" if rows else "empty",
        "rows": rows,
        "declared_count": None,
        "skipped_rows": 0,
    }


def _write_lines(path: Path, items: list[dict[str, object]]) -> Path:
    path.write_text("".join(json.dumps(item) + "\n" for item in items), encoding="utf-8")
    return path


def _health(sid: str, status: HealthStatus) -> SourceHealth:
    return SourceHealth.model_validate(
        {
            "source_id": sid,
            "url": f"https://{sid}.test/closings",
            "checked_at": "2026-09-27T01:00:00Z",
            "status": status,
            "rows": 0,
            "reason": None if status is HealthStatus.EMPTY else "synthetic failure",
        }
    )


def _dig(value: JSONValue, *keys: str) -> JSONValue:
    for key in keys:
        assert isinstance(value, dict)
        value = value[key]
    return value


def _evidence(tmp_path: Path) -> proof.Evidence:
    archive = _write_lines(
        tmp_path / "archive-reads.jsonl",
        [
            # A's page, archived with rows: proof of its current list.
            _read("synthetic-a", "https://synthetic-a.test/closings", "2025-01-06T12:00:00Z", 4),
            _read("synthetic-a", "https://synthetic-a.test/closings", "2024-01-06T12:00:00Z", 9),
            # C: an older list file with rows (not its current list), and its page empty.
            _read(
                "synthetic-c", "https://old-synthetic-c.test/list.html", "2019-01-06T12:00:00Z", 7
            ),
            _read("synthetic-c", "https://synthetic-c.test/closings", "2025-01-06T12:00:00Z", 0),
        ],
    )
    live = _write_lines(
        tmp_path / "reads.jsonl",
        [
            _read(
                "synthetic-b",
                "https://synthetic-b.test/data.json",
                "2026-09-27T02:00:00Z",
                2,
                "live",
            )
        ],
    )
    health = tmp_path / "archive-health.json"
    failure = {
        "source_id": "synthetic-c",
        "url": "https://synthetic-c.test/closings",
        "checked_at": "2026-01-26T12:00:00Z",
        "status": "error",
        "rows": 0,
        "reason": "the capture was not downloaded: HTTP 403",
    }
    ok = {**failure, "status": "empty", "reason": None}
    health.write_text(json.dumps({"sources": [failure, ok]}), encoding="utf-8")
    fixtures = tmp_path / "fixtures"
    (fixtures / "set").mkdir(parents=True)
    (fixtures / "set" / "PROVENANCE.json").write_text("[]", encoding="utf-8")
    (fixtures / "reference").mkdir()
    (fixtures / "reference" / "PROVENANCE.json").write_text('{"x": {}}', encoding="utf-8")
    return proof.gather(
        live_reads=live, archive_reads=archive, archive_health=health, fixtures=fixtures
    )


def test_gather_keeps_every_populated_read_and_what_was_checked(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    registry = load_registry(_registry(tmp_path))
    a, b, c = (registry.stations[f"synthetic-{x}"] for x in "abc")
    best_a = evidence.best(a)
    assert best_a is not None
    assert (best_a.rows, best_a.captured_at) == (9, datetime(2024, 1, 6, 12, tzinfo=UTC))
    assert (
        best_a.capture_url
        == "https://web.archive.org/web/20240106120000/https://synthetic-a.test/closings"
    )
    assert best_a.current(a)
    best_b = evidence.best(b)
    assert best_b is not None
    assert (best_b.mode, best_b.capture_url, best_b.current(b)) == ("live", None, True)
    best_c = evidence.best(c)
    assert best_c is not None
    assert (best_c.rows, best_c.current(c)) == (7, False)
    # The reference folder's provenance (not fixture entries) is passed over.
    records = evidence.files["fixtures"]
    assert isinstance(records, list)
    (record,) = records
    assert isinstance(record, dict)
    assert (record["entries"], str(record["path"]).endswith("set/PROVENANCE.json")) == (0, True)
    assert record["sha256"] == hashlib.sha256(b"[]").hexdigest()


def test_add_proven_counts_only_current_lists_seen_with_rows(tmp_path: Path) -> None:
    registry = load_registry(_registry(tmp_path))
    health = {sid: _health(sid, HealthStatus.EMPTY) for sid in registry.stations}
    states = coverage.station_states(registry, health)
    result = coverage.measure(registry, SCHOOLS, states, None)
    proof.add_proven(result, registry, SCHOOLS, states, _evidence(tmp_path))
    assert _dig(result, "national", "share") == 1.0
    # A (2 schools) and B (1) are proven; C (1) was seen with rows only in an older file.
    assert _dig(result, "proven", "national") == {
        "schools": 4,
        "covered": 3,
        "share": 0.75,
        "meets_target": False,
    }
    assert _dig(result, "proven", "states", "MO", "covered") == 1
    assert _dig(result, "proven", "stations") == {"working": 3, "proven": 2, "unproven": 1}
    listed = result["unproven"]
    assert isinstance(listed, list)
    (unproven,) = listed
    assert isinstance(unproven, dict)
    assert unproven["id"] == "synthetic-c"
    checked = unproven["checked"]
    assert _dig(checked, "archived", "count") == 2
    assert _dig(checked, "archive_failures", "items") == [
        {
            "captured_at": "2026-01-26T12:00:00Z",
            "url": "https://synthetic-c.test/closings",
            "reason": "the capture was not downloaded: HTTP 403",
        }
    ]
    assert _dig(result, "stations", "synthetic-c", "proof", "current") is False
    assert _dig(result, "stations", "synthetic-a", "proof", "rows") == 9
    line = proof.summary_line(result)
    assert line == "proven (lists seen with rows): 75.0%; 2 of 3 working stations proven"
    assert proof.summary_line({}) is None


def test_stations_not_working_are_not_counted_either_way(tmp_path: Path) -> None:
    registry = load_registry(_registry(tmp_path))
    health = {"synthetic-a": _health("synthetic-a", HealthStatus.ERROR)}
    states = coverage.station_states(registry, health)
    result = coverage.measure(registry, SCHOOLS, states, None)
    proof.add_proven(result, registry, SCHOOLS, states, _evidence(tmp_path))
    assert _dig(result, "proven", "stations") == {"working": 0, "proven": 0, "unproven": 0}
    assert _dig(result, "proven", "national", "covered") == 0
    with pytest.raises(coverage.CoverageError, match="station table"):
        proof.add_proven({}, registry, SCHOOLS, states, proof.Evidence())


def test_fixture_provenance_is_evidence(tmp_path: Path) -> None:
    folder = tmp_path / "fixtures" / "set"
    folder.mkdir(parents=True)
    expected: dict[str, object] = {
        "variant": "synthetic",
        "state": "populated",
        "rows": 2,
        "names": ["A", "B"],
    }
    entry: dict[str, object] = {
        "file": "synthetic/c-page.html",
        "source_id": "synthetic-c",
        "adapter": "gray",
        "mode": "live",
        "url": "https://synthetic-c.test/closings",
        "captured_at": "2026-09-26T22:00:00Z",
        "archive_url": None,
        "retrieved_at": "2026-09-26T22:00:00Z",
        "original_sha256": SHA,
        "original_bytes": 10,
        "slice": "none",
        "sha256": SHA,
        "bytes": 10,
        "expected": expected,
        "note": "",
    }
    empty = {
        **entry,
        "file": "synthetic/c-empty.html",
        "expected": {**expected, "state": "empty", "rows": 0, "names": []},
    }
    (folder / "PROVENANCE.json").write_text(json.dumps([entry, empty]), encoding="utf-8")
    evidence = proof.gather(
        live_reads=None, archive_reads=None, archive_health=None, fixtures=tmp_path / "fixtures"
    )
    registry = load_registry(_registry(tmp_path))
    best = evidence.best(registry.stations["synthetic-c"])
    assert best is not None
    assert (best.basis, best.rows, best.current(registry.stations["synthetic-c"])) == (
        "fixture set/synthetic/c-page.html",
        2,
        True,
    )
    assert len(evidence.checked["synthetic-c"]["fixtures"]) == 2
    assert evidence.files["live_reads"] is None
    # A provenance file of fixture entries that does not validate is an error.
    (folder / "PROVENANCE.json").write_text(json.dumps([{**entry, "mode": "x"}]), encoding="utf-8")
    with pytest.raises(proof.ProofError):
        proof.fixture_entries(tmp_path / "fixtures")


def test_malformed_evidence_files_are_errors(tmp_path: Path) -> None:
    reads = tmp_path / "reads.jsonl"
    reads.write_text('{"source_id": "x"}\n', encoding="utf-8")
    with pytest.raises(proof.ProofError, match=r"reads\.jsonl:1"):
        proof.read_reads(reads)
    health = tmp_path / "health.json"
    health.write_text("[]", encoding="utf-8")
    with pytest.raises(proof.ProofError):
        proof.read_health(health)


def test_the_map_panel_gives_the_proven_shares_off_the_map(tmp_path: Path) -> None:
    registry = load_registry(_registry(tmp_path))
    health = {sid: _health(sid, HealthStatus.EMPTY) for sid in registry.stations}
    states = coverage.station_states(registry, health)
    result = coverage.measure(registry, SCHOOLS, states, None)
    shapes = {
        "20091": project(box(-95.1, 38.7, -94.6, 39.0)),
        "29095": project(box(-94.6, 38.8, -94.1, 39.1)),
        "29047": project(box(-94.6, 39.1, -94.2, 39.4)),
    }
    plain = _decode_png(coverage.render_png(result, shapes))
    proof.add_proven(result, registry, SCHOOLS, states, _evidence(tmp_path))
    with_proof = _decode_png(coverage.render_png(result, shapes))
    # The proven shares go in the panel under the map, which grows by a line and
    # widens each state's entry; nothing is drawn over the map itself.
    assert with_proof.shape[1] == plain.shape[1]
    assert with_proof.shape[0] > plain.shape[0]
    # Two states: one row of the panel, 8 pixels above its heading and 48 around it.
    map_height = plain.shape[0] - (coverage.STATE_ROW + 8 + 48)
    assert (plain[map_height : map_height + 8] == coverage.BACKGROUND).all()
    assert (with_proof[:map_height] == plain[:map_height]).all()
    # The panel opens with the national proven line.
    assert (with_proof[map_height + 8 : map_height + 22] != coverage.BACKGROUND).any()
    # The map itself is drawn untouched, between the title band and the legend.
    counties = result["counties"]
    assert isinstance(counties, dict)
    colors = {
        fips: coverage.WORKING_COLOR
        if isinstance(info, dict) and info["working"]
        else coverage.GAP_COLOR
        for fips, info in counties.items()
    }
    bare = render(shapes, colors, background=coverage.BACKGROUND, default=coverage.EMPTY_COLOR)
    top = coverage.HEADER_HEIGHT
    assert (with_proof[top : top + bare.shape[0]] == bare).all()


def _decode_png(data: bytes) -> "np.ndarray[tuple[int, int, int], np.dtype[np.uint8]]":
    """Decode the unfiltered RGB PNG that ``mapimage.png_bytes`` writes."""
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    width, height = struct.unpack(">II", data[16:24])
    chunks, at = [], 8
    while at < len(data):
        (length,) = struct.unpack(">I", data[at : at + 4])
        if data[at + 4 : at + 8] == b"IDAT":
            chunks.append(data[at + 8 : at + 8 + length])
        at += length + 12
    raw = np.frombuffer(zlib.decompress(b"".join(chunks)), dtype=np.uint8)
    rows = raw.reshape(height, 1 + width * 3)
    assert (rows[:, 0] == 0).all()
    return rows[:, 1:].reshape(height, width, 3)
