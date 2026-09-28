"""Tying rows to their recorded reads, sections, and which sources count."""

import json
from pathlib import Path

import pytest

from snowlight.listed.evidence import (
    DROP_REASONS,
    EvidenceError,
    load_rows,
    read_reads,
    section_of,
    utc_text,
)
from snowlight.listed.located import Place
from snowlight.listed.scope import EXCLUDED_PLATFORMS, excluded_reason, station_context
from snowlight.sources.stations.registry import PlatformFile

FIXTURES = Path(__file__).parent / "fixtures"
KMBC_READ = FIXTURES / "kmbc-20240117"


def test_a_real_read_ties_all_its_rows() -> None:
    loaded = load_rows(KMBC_READ / "reads.jsonl", KMBC_READ / "rows.jsonl")
    assert dict(loaded.dropped) == dict.fromkeys(DROP_REASONS, 0)
    assert [row.name for row in loaded.rows] == [
        "Bannister Road Baptist Church",
        "Christ United Methodist",
        "Full Gospel Assembly-Independence",
        "Southside First Baptist",
    ]
    read = json.loads((KMBC_READ / "reads.jsonl").read_text(encoding="utf-8"))
    assert {row.read_sha256 for row in loaded.rows} == {read["sha256"]}
    assert {row.fetched_at for row in loaded.rows} == {"2024-01-17T20:33:33Z"}
    assert {row.mode for row in loaded.rows} == {"archive"}
    first = loaded.rows[0]
    assert first.variant == "hearst-rows"
    assert first.section is None
    assert first.places == (Place(state="MO", city="kansas city", county="Jackson"),)


def _write(path: Path, items: list[dict[str, object]]) -> Path:
    path.write_text("".join(json.dumps(item) + "\n" for item in items), encoding="utf-8")
    return path


def _read(source: str, at: str, rows: int, sha: str = "a" * 64) -> dict[str, object]:
    """A SYNTHETIC read line."""
    return {
        "source_id": source,
        "mode": "archive",
        "url": "https://example.invalid/list",
        "fetched_at": at,
        "retrieved_at": "2026-09-27T00:00:00Z",
        "sha256": sha,
        "bytes": 10,
        "variant": "hearst-rows",
        "state": "populated" if rows else "empty",
        "rows": rows,
    }


def _row(source: str, at: str, name: str) -> dict[str, object]:
    """A SYNTHETIC row line."""
    return {
        "source_id": source,
        "fetched_at": at,
        "raw_name": name,
        "raw_status": "Closed",
        "raw_updated_text": None,
        "raw_extra": {},
    }


def test_rows_without_a_single_matching_read_are_left_out(tmp_path: Path) -> None:
    reads = _write(
        tmp_path / "reads.jsonl",
        [
            _read("syn-a", "2024-01-01T00:00:00Z", 1),
            _read("syn-b", "2024-01-01T00:00:00Z", 1, "b" * 64),
            _read("syn-b", "2024-01-01T00:00:00+00:00", 1, "c" * 64),
            _read("syn-c", "2024-01-01T00:00:00Z", 3),
            _read("syn-e", "2024-01-01T00:00:00Z", 0),
        ],
    )
    rows = _write(
        tmp_path / "rows.jsonl",
        [
            _row("syn-a", "2024-01-01T00:00:00Z", "Kept"),
            _row("syn-b", "2024-01-01T00:00:00Z", "Two reads"),
            _row("syn-c", "2024-01-01T00:00:00Z", "Short one"),
            _row("syn-d", "2024-01-01T00:00:00Z", "No read"),
            _row("syn-e", "2024-01-01T00:00:00Z", "Empty read"),
        ],
    )
    loaded = load_rows(reads, rows)
    assert [row.name for row in loaded.rows] == ["Kept"]
    assert dict(loaded.dropped) == {"no_read": 2, "several_reads": 1, "count_mismatch": 1}
    assert len(loaded.reads) == 5


def test_bad_lines_are_refused(tmp_path: Path) -> None:
    bad = _read("syn-a", "2024-01-01T00:00:00Z", 1)
    bad["rows"] = -1
    with pytest.raises(EvidenceError, match="row count"):
        read_reads(_write(tmp_path / "reads.jsonl", [bad]))
    with pytest.raises(EvidenceError, match="source_id"):
        read_reads(_write(tmp_path / "reads.jsonl", [{"rows": 1}]))
    (tmp_path / "list.jsonl").write_text("[1]\n", encoding="utf-8")
    with pytest.raises(EvidenceError, match="not a JSON object"):
        read_reads(tmp_path / "list.jsonl")
    with pytest.raises(EvidenceError, match="without a time zone"):
        utc_text("2024-01-01T00:00:00")
    with pytest.raises(EvidenceError, match="not an ISO instant"):
        utc_text("yesterday")
    assert utc_text("2024-01-01T01:00:00+01:00") == "2024-01-01T00:00:00Z"


def test_sections_come_from_the_variant_fields() -> None:
    assert section_of("nexstar-page", {"category": " Schools ", "locality": "Kansas City"}) == (
        "Schools"
    )
    assert section_of("gray-file-newsticker-xml", {"forced_category_name": ""}) is None
    assert (
        section_of(
            "gray-file-newsticker-xml",
            {"forced_category_name": "", "category_name1": "Private School"},
        )
        == "Private School"
    )
    assert section_of("hearst-ibsys", {"bucket": "s"}) is None
    assert section_of("nbc-wp-json", {"category": "DUTCHESS"}) is None


def _platform(name: str) -> PlatformFile:
    import yaml  # type: ignore[import-untyped, unused-ignore]  # noqa: PLC0415

    path = Path(__file__).resolve().parents[2] / "config" / "sources" / f"{name}.yaml"
    return PlatformFile.model_validate_json(
        json.dumps(yaml.safe_load(path.read_text(encoding="utf-8")), default=str)
    )


def test_a_station_is_matched_in_its_registry_context() -> None:
    wral = _platform("wral").stations[0]
    context = station_context(wral)
    assert context.market == "wral-wral"
    assert context.states == ("NC", "VA")
    assert context.counties is not None
    assert "37183" in context.counties
    assert excluded_reason(wral) is None


def test_district_alert_channels_are_not_lists() -> None:
    assert set(EXCLUDED_PLATFORMS) == {
        "apptegy",
        "dadeschools",
        "finalsite",
        "hcoe",
        "pasco",
        "smartsites",
    }
