"""Merging live fetch runs: a list seen populated by an earlier fetch stays proven.

Every read and row built here is synthetic (every URL is under .test); the real
runs are merged by ``snowlight stations merge-live``.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from snowlight.cli import main
from snowlight.sources.stations import merge
from snowlight.sources.stations.model import ListingRead, RawRow

SHA = "b" * 64


def _read(source: str, url: str, at: str, rows: int) -> ListingRead:
    return ListingRead.model_validate_json(
        json.dumps(
            {
                "source_id": source,
                "mode": "live",
                "url": url,
                "fetched_at": at,
                "retrieved_at": at,
                "sha256": SHA,
                "bytes": 100,
                "variant": "synthetic",
                "state": "populated" if rows else "empty",
                "rows": rows,
                "declared_count": None,
                "skipped_rows": 0,
            }
        )
    )


def _row(source: str, at: str, name: str) -> RawRow:
    return RawRow.model_validate_json(
        json.dumps(
            {
                "source_id": source,
                "fetched_at": at,
                "raw_name": name,
                "raw_status": "Closed",
                "raw_updated_text": None,
                "raw_extra": {},
            }
        )
    )


def _write(folder: Path, reads: list[ListingRead], rows: list[RawRow]) -> Path:
    folder.mkdir(parents=True)
    path = folder / "reads.jsonl"
    path.write_text("".join(read.model_dump_json() + "\n" for read in reads), encoding="utf-8")
    (folder / "rows.jsonl").write_text(
        "".join(row.model_dump_json() + "\n" for row in rows), encoding="utf-8"
    )
    return path


EARLY = "2026-09-29T10:00:00Z"
LATE = "2026-10-03T20:00:00Z"


def test_an_earlier_populated_read_is_kept_beside_a_newer_empty_one(tmp_path: Path) -> None:
    first = _write(
        tmp_path / "first",
        [
            _read("synthetic-a", "https://a.test/list", EARLY, 2),
            _read("synthetic-b", "https://b.test/list", EARLY, 0),
        ],
        [_row("synthetic-a", EARLY, "Alpha School"), _row("synthetic-a", EARLY, "Beta School")],
    )
    second = _write(
        tmp_path / "second",
        [
            _read("synthetic-a", "https://a.test/list", LATE, 0),
            _read("synthetic-b", "https://b.test/list", LATE, 0),
        ],
        [],
    )
    runs = [merge.load_run(first), merge.load_run(second)]
    merged = merge.merge_runs(runs)
    kept = [
        (read.source_id, read.fetched_at.strftime("%Y-%m-%d"), read.rows) for read in merged.reads
    ]
    assert kept == [
        ("synthetic-a", "2026-09-29", 2),
        ("synthetic-a", "2026-10-03", 0),
        ("synthetic-b", "2026-10-03", 0),
    ]
    assert merged.kept_as_proof == 1
    assert merged.dropped_older == 1  # b's older empty read
    assert [row.raw_name for row in merged.rows] == ["Alpha School", "Beta School"]


def test_a_newer_populated_read_replaces_the_older_one(tmp_path: Path) -> None:
    first = _write(
        tmp_path / "first",
        [_read("synthetic-a", "https://a.test/list", EARLY, 1)],
        [_row("synthetic-a", EARLY, "Old School")],
    )
    second = _write(
        tmp_path / "second",
        [_read("synthetic-a", "https://a.test/list", LATE, 1)],
        [_row("synthetic-a", LATE, "New School")],
    )
    merged = merge.merge_runs([merge.load_run(first), merge.load_run(second)])
    assert [read.rows for read in merged.reads] == [1]
    assert merged.reads[0].fetched_at == datetime(2026, 10, 3, 20, tzinfo=UTC)
    assert [row.raw_name for row in merged.rows] == ["New School"]
    assert merged.kept_as_proof == 0


def test_an_older_populated_read_of_another_body_is_kept_beside_a_newer_populated_one(
    tmp_path: Path,
) -> None:
    # A channel populated twice: a storm notice, then an enrollment notice (another body).
    storm = _read("synthetic-a", "https://a.test/pops", EARLY, 1)
    notice = _read("synthetic-a", "https://a.test/pops", LATE, 1).model_copy(
        update={"sha256": "c" * 64}
    )
    first = _write(tmp_path / "first", [storm], [_row("synthetic-a", EARLY, "Storm notice")])
    second = _write(tmp_path / "second", [notice], [_row("synthetic-a", LATE, "Enrollment")])
    merged = merge.merge_runs([merge.load_run(first), merge.load_run(second)])
    assert [(read.fetched_at.strftime("%Y-%m-%d"), read.sha256[0]) for read in merged.reads] == [
        ("2026-09-29", "b"),
        ("2026-10-03", "c"),
    ]
    assert merged.kept_as_proof == 1
    assert merged.dropped_older == 0
    assert [row.raw_name for row in merged.rows] == ["Storm notice", "Enrollment"]


def test_identical_reads_and_rows_are_kept_once(tmp_path: Path) -> None:
    reads = [_read("synthetic-a", "https://a.test/list", EARLY, 1)]
    rows = [_row("synthetic-a", EARLY, "Alpha School")]
    first = _write(tmp_path / "first", reads, rows)
    second = _write(tmp_path / "second", reads, rows)
    runs = [merge.load_run(first), merge.load_run(second)]
    merged = merge.merge_runs(runs)
    assert len(merged.reads) == 1
    assert merged.duplicate_reads == 1
    assert len(merged.rows) == 1
    assert merged.duplicate_rows == 1
    paths = merge.write_merged(tmp_path / "out", runs, merged, datetime(2026, 10, 3, tzinfo=UTC))
    record = json.loads(paths["merge"].read_text(encoding="utf-8"))
    assert record["reads"] == {"kept": 1, "dropped_older": 0, "duplicates": 1, "kept_as_proof": 0}
    assert record["rows"] == {"kept": 1, "duplicates": 1}
    assert [item["reads"]["count"] for item in record["inputs"]] == [1, 1]
    assert merge.load_run(paths["reads"]).reads == tuple(merged.reads)


def test_a_bad_line_names_its_file_and_line(tmp_path: Path) -> None:
    folder = tmp_path / "bad"
    folder.mkdir()
    path = folder / "reads.jsonl"
    path.write_text('{"source_id": "synthetic-a"}\n', encoding="utf-8")
    with pytest.raises(merge.MergeError, match=r"reads\.jsonl:1"):
        merge.load_run(path)


def test_the_output_may_not_overwrite_an_input(tmp_path: Path) -> None:
    first = _write(tmp_path / "first", [_read("synthetic-a", "https://a.test/l", EARLY, 0)], [])
    runs = [merge.load_run(first)]
    with pytest.raises(merge.MergeError, match="holds an input"):
        merge.write_merged(tmp_path / "first", runs, merge.merge_runs(runs), datetime.now(UTC))


def test_merge_live_command_writes_the_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = _write(
        tmp_path / "first",
        [_read("synthetic-a", "https://a.test/list", EARLY, 1)],
        [_row("synthetic-a", EARLY, "Alpha School")],
    )
    second = _write(tmp_path / "second", [_read("synthetic-a", "https://a.test/list", LATE, 0)], [])
    (tmp_path / "second" / "rows.jsonl").unlink()  # a run may have written no rows file
    out = tmp_path / "merged"
    code = main(["stations", "merge-live", str(first), str(second), "--out-dir", str(out)])
    assert code == 0
    assert "1 older populated reads kept as proof" in capsys.readouterr().out
    assert len(merge.load_run(out / "reads.jsonl").rows) == 1
    record = json.loads((out / merge.MERGE_FILE).read_text(encoding="utf-8"))
    assert record["inputs"][1]["rows"] is None


def test_merge_live_command_reports_a_missing_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        ["stations", "merge-live", str(tmp_path / "nope.jsonl"), "--out-dir", str(tmp_path)]
    )
    assert code == 1
    assert "merge-live:" in capsys.readouterr().err


def _health_file(folder: Path, at: str, entries: list[tuple[str, str]]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "health.json"
    sources = [
        {
            "source_id": source,
            "url": f"https://{source}.test/",
            "checked_at": at,
            "status": status,
            "rows": 2 if status == "ok" else 0,
            "reason": "synthetic failure" if status == "error" else None,
        }
        for source, status in entries
    ]
    data = {
        "generated_at": at,
        "stale_before": "2025-11-01T00:00:00Z",
        "sources": sources,
        "totals": {},
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_health_files_keep_each_sources_last_read(tmp_path: Path) -> None:
    full = _health_file(
        tmp_path / "full", EARLY, [("synthetic-a", "empty"), ("synthetic-b", "error")]
    )
    few = _health_file(tmp_path / "few", LATE, [("synthetic-b", "empty"), ("synthetic-c", "ok")])
    table = merge.merge_health([merge.load_health(full), merge.load_health(few)])
    statuses = {
        item["source_id"]: (item["status"], item["checked_at"])
        for item in table["sources"]  # type: ignore[union-attr]
        if isinstance(item, dict)
    }
    assert statuses == {
        "synthetic-a": ("empty", EARLY),
        "synthetic-b": ("empty", LATE),
        "synthetic-c": ("ok", LATE),
    }
    assert table["generated_at"] == LATE
    totals = table["totals"]
    assert isinstance(totals, dict)
    assert (totals["sources"], totals["empty"], totals["ok"], totals["error"]) == (3, 2, 1, 0)


def test_merge_live_command_merges_named_health_files(tmp_path: Path) -> None:
    reads = _write(tmp_path / "full", [_read("synthetic-a", "https://a.test/list", EARLY, 0)], [])
    health = _health_file(tmp_path / "full", EARLY, [("synthetic-a", "empty")])
    out = tmp_path / "merged"
    argv = ["stations", "merge-live", str(reads), "--out-dir", str(out), "--health", str(health)]
    assert main(argv) == 0
    merged = merge.load_health(out / "health.json")
    assert [entry.source_id for entry in merged.sources] == ["synthetic-a"]
    record = json.loads((out / merge.MERGE_FILE).read_text(encoding="utf-8"))
    assert record["health"]["sources"] == 1
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    with pytest.raises(merge.MergeError, match=r"bad\.json"):
        merge.load_health(bad)
    # A health file may not be overwritten by the merge either.
    with pytest.raises(merge.MergeError, match="holds an input"):
        merge.write_merged(
            tmp_path / "full",
            [merge.load_run(reads)],
            merge.merge_runs([merge.load_run(reads)]),
            datetime(2026, 10, 3, tzinfo=UTC),
            [merge.load_health(health)],
        )
