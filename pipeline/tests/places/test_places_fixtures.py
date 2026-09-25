"""Checks that every fixture is a documented, verbatim slice of a real source file.

``fixtures/provenance.json`` names each fixture's source URL, retrieval time and
the SHA-256 of the full source file. When that full file is in the local
download cache (``pipeline/.cache/places``) with the same checksum, the tests
below also prove the slice is verbatim; in a clean checkout they are skipped.
"""

import io
import json
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from snowlight.places.download import cache_path_for, sha256_file
from snowlight.places.xlsx import read_table

if TYPE_CHECKING:
    from conftest import FixtureKit

CACHE = Path(__file__).resolve().parents[2] / ".cache" / "places"


def _provenance(kit: "FixtureKit") -> dict[str, dict[str, Any]]:
    data: dict[str, dict[str, Any]] = json.loads(kit.text_of("provenance.json"))
    return data


def _cached_source(entry: dict[str, Any]) -> Path:
    path = cache_path_for(CACHE, entry["source_url"])
    if not path.is_file() or sha256_file(path) != entry.get("source_sha256"):
        pytest.skip(f"full source not cached: {entry['source_url']}")
    return path


def test_every_fixture_is_documented(kit: "FixtureKit") -> None:
    provenance = _provenance(kit)
    files = {p.name for p in kit.fixtures.iterdir() if p.name != "provenance.json"}
    assert files == set(provenance)
    for entry in provenance.values():
        assert entry["source_url"].startswith("https://")
        assert entry["retrieved_at"].endswith("Z")
        assert entry["selection"]
        assert len(entry.get("source_sha256") or entry["page_sha256"]) == 64


@pytest.mark.parametrize(
    "name",
    [
        "2026_Gaz_place_national.txt",
        "2026_Gaz_zcta_national.txt",
        "2025_Gaz_zcta_national.txt",
        "sub-est2025.csv",
        "tab20_zcta520_county20_natl.txt",
    ],
)
def test_text_slices_are_verbatim_lines(kit: "FixtureKit", name: str) -> None:
    entry = _provenance(kit)[name]
    source = _cached_source(entry)
    if "source_member" in entry:
        with zipfile.ZipFile(source) as archive:
            full = archive.read(entry["source_member"])
    else:
        full = source.read_bytes()
    lines = set(full.split(b"\n"))
    for line in kit.bytes_of(name).split(b"\n")[:-1]:
        assert line in lines, line
    assert kit.bytes_of(name).split(b"\n")[0] == full.split(b"\n")[0]


def test_lsad_table_is_verbatim(kit: "FixtureKit") -> None:
    entry = _provenance(kit)["legal-status-codes.table.html"]
    page = _cached_source(entry).read_text(encoding="utf-8")
    assert kit.text_of("legal-status-codes.table.html") in page


def test_grf_rows_are_verbatim(kit: "FixtureKit") -> None:
    entry = _provenance(kit)["grf25_lea_zcta5ce20.tsv"]
    with zipfile.ZipFile(_cached_source(entry)) as archive:
        workbook = archive.read(entry["source_member"])
    header, rows = read_table(io.BytesIO(workbook), "grf")
    fixture = kit.grf_rows()
    assert fixture[0] == header
    all_rows = {tuple(row) for row in rows}
    for row in fixture[1:]:
        assert tuple(row) in all_rows
