"""The coverage gate: marginal gains, the archive census, verdicts, the report and the plan.

The ``snowlight stations gate`` commands run on the same files at the end, without
weights or storm days (which need the weights build's cached NWS files).

Everything here is synthetic (every URL is under .test): a registry of five
sources, a six-school directory, closure weights, CDX listings, a snapshot
manifest and archive reads written to a temporary folder. The coverage result is
the real measure's (:func:`coverage.measure` and :func:`proof.add_proven`) over
them, so the gate is held to what ``coverage.json`` would say.
"""

import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest
import yaml  # type: ignore[import-untyped, unused-ignore]

from snowlight.cli import main
from snowlight.output import JSONValue
from snowlight.sources.stations import coverage, gate, proof
from snowlight.sources.stations.archive import Capture
from snowlight.sources.stations.model import HealthStatus, SourceHealth
from snowlight.sources.stations.registry import Registry, StationStatus, load_registry
from snowlight.sources.stations.storms import StormDays

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
        "index": [0, 1, 2, 3, 4, 5],
        "state": ["KS", "KS", "MO", "MO", "MO", "MO"],
        "county_fips": ["20091", "20091", "29095", "29095", "29095", "29047"],
        "county_name": ["Johnson", "Johnson", "Jackson", "Jackson", "Jackson", "Clay"],
        "district_id": ["2000001", "2000001", "2900001", "2900001", None, "2900002"],
    }
)
WEIGHTS = coverage.Weights({"20091": 2.0, "29095": 1.0, "29047": 0.5}, {"path": "synthetic"})
SHA = "b" * 64


def _station(sid: str, fips: list[str], **fields: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "id": sid,
        "platform": "synthetic",
        "call_sign": sid.split("-")[1].upper() + "XX",
        "name": sid,
        "market": "Kansas City",
        "dma": None,
        "states": ["KS", "MO"],
        "counties": {"basis": "dma", "source": "synthetic", "fips": fips},
        "page_url": f"https://{sid}.test/closings",
        "data_url": None,
        "archive_urls": [],
        "poll_minutes": None,
        "status": "active",
        "evidence": "synthetic",
    }
    entry.update(fields)
    return entry


def _registry(tmp_path: Path) -> Registry:
    folder = tmp_path / "sources"
    folder.mkdir()
    district = _station(
        "synthetic-d",
        ["29095"],
        counties={"basis": "district", "source": "synthetic", "fips": ["29095"]},
        leaids=["2900001"],
        states=["MO"],
    )
    none = _station("synthetic-e", ["29047"], page_url=None, status="no_endpoint")
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
            _station(
                "synthetic-b",
                ["29095"],
                archive_urls=["https://synthetic-b.test/closings", "https://old-b.test/list.json"],
            ),
            _station("synthetic-c", ["29047"]),
            district,
            none,
        ],
    }
    (folder / "synthetic.yaml").write_text(yaml.safe_dump(content), encoding="utf-8")
    return load_registry(folder)


def _read(sid: str, url: str, when: str, rows: int) -> dict[str, object]:
    return {
        "source_id": sid,
        "mode": "archive",
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


def _lines(path: Path, items: list[dict[str, object]]) -> Path:
    path.write_text("".join(json.dumps(item) + "\n" for item in items), encoding="utf-8")
    return path


def _cdx(folder: Path, name: str, rows: list[list[str]]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    header = ["timestamp", "original", "statuscode", "mimetype", "length", "digest"]
    (folder / name).write_text(json.dumps([header, *rows]), encoding="utf-8")


def _artifacts(tmp_path: Path) -> Path:
    root = tmp_path / "artifacts"
    b = "https://synthetic-b.test/closings"
    _cdx(
        root / "cdx-1",
        "synthetic_b_test_closings___20140101-20260930.json",
        [
            ["20250106120000", b, "200", "text/html", "1000", "EMPTYA"],  # read, empty
            ["20250107120000", b, "200", "text/html", "1000", "EMPTYA"],  # same digest: read
            ["20250110120000", b, "200", "text/html", "5000", "BIGGER"],  # unread, large
            ["20250108120000", b, "200", "text/html", "1100", "STORMY"],  # unread, storm day
            ["20250109120000", b, "-", "warc/revisit", "600", "EMPTYA"],  # a revisit
            ["20250111120000", b, "404", "text/html", "300", "GONE"],  # not replayable
            ["20240106120000", b, "200", "text/html", "1000", "OLDER1"],
            ["20240107120000", b, "200", "text/html", "1000", "OLDER2"],
        ],
    )
    # C's page was listed and the archive holds nothing of it.
    _cdx(root / "cdx-1", "synthetic_c_test_closings___20140101-20260930.json", [])
    # A file under a folder not named cdx* is not a listing.
    _cdx(root / "other", "synthetic_d_test_closings.json", [])
    snapshots = root / "snapshots-1" / "snapshots"
    snapshots.mkdir(parents=True)
    record = {
        "timestamp": "20250106120000",
        "url": b,
        "requested": f"https://web.archive.org/web/20250106120000id_/{b}",
        "final_timestamp": "20250106120000",
        "final_original": b,
        "file": "snapshots/x.body",
        "sha256": SHA,
        "bytes": 10,
    }
    failed = {**record, "timestamp": "20240106120000", "file": None, "error": "URLError: timed out"}
    (snapshots / "manifest.jsonl").write_text(
        json.dumps(record) + "\n" + json.dumps(failed) + "\n", encoding="utf-8"
    )
    return root


def _states(registry: Registry) -> dict[str, coverage.StationState]:
    health = {
        sid: SourceHealth.model_validate(
            {
                "source_id": sid,
                "url": f"https://{sid}.test/closings",
                "checked_at": "2026-09-27T01:00:00Z",
                "status": HealthStatus.EMPTY,
                "rows": 0,
            }
        )
        for sid in registry.stations
        if sid != "synthetic-e"
    }
    return coverage.station_states(registry, health)


def _result(tmp_path: Path, registry: Registry) -> dict[str, JSONValue]:
    states = _states(registry)
    result = coverage.measure(registry, SCHOOLS, states, None, weights=WEIGHTS)
    reads = _lines(
        tmp_path / "archive-reads.jsonl",
        [
            _read("synthetic-a", "https://synthetic-a.test/closings", "2025-01-06T12:00:00Z", 3),
            _read("synthetic-b", "https://synthetic-b.test/closings", "2025-01-06T12:00:00Z", 0),
        ],
    )
    evidence = proof.gather(
        live_reads=None, archive_reads=reads, archive_health=None, fixtures=None
    )
    proof.add_proven(result, registry, SCHOOLS, states, evidence, weights=WEIGHTS)
    return result


def _census(tmp_path: Path) -> gate.Census:
    reads = proof.read_reads(tmp_path / "archive-reads.jsonl")
    failure = SourceHealth.model_validate(
        {
            "source_id": "synthetic-b",
            "url": "https://synthetic-b.test/closings",
            "checked_at": "2024-01-07T12:00:00Z",
            "status": HealthStatus.ERROR,
            "rows": 0,
            "sha256": SHA,
            "reason": "unrecognized shape",
        }
    )
    never = failure.model_copy(update={"checked_at": datetime(2024, 1, 6, 12, tzinfo=UTC)})
    never = never.model_copy(update={"sha256": None})
    return gate.census_from_files(_artifacts(tmp_path), reads, [failure, never])


def _storms(registry: Registry) -> StormDays:
    days = {
        "winter": {"29095": {date(2025, 1, 8): 1.0}},
        "tropical": {"29095": {date(2025, 1, 10): 0.4}},
    }
    return StormDays.build(registry, gate.hazard_days(days, ["winter", "cold"]))


def _report(tmp_path: Path) -> tuple[Registry, dict[str, JSONValue], gate.Census]:
    registry = _registry(tmp_path)
    result = _result(tmp_path, registry)
    census = _census(tmp_path)
    report = gate.build_report(
        registry,
        result,
        gate.school_frame(SCHOOLS, WEIGHTS),
        census,
        _storms(registry),
        coverage_file={"path": "coverage.json", "sha256": SHA, "generated_at": None},
        now=datetime(2026, 9, 29, 3, tzinfo=UTC),
    )
    return registry, report, census


def _dig(value: JSONValue, *keys: str) -> JSONValue:
    for key in keys:
        assert isinstance(value, dict)
        value = value[key]
    return value


def _table(value: JSONValue) -> dict[str, JSONValue]:
    assert isinstance(value, dict)
    return value


def _rows(value: JSONValue) -> list[dict[str, JSONValue]]:
    assert isinstance(value, list)
    return [_table(item) for item in value]


def test_marginal_gains_count_only_schools_no_proven_source_covers(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    frame = gate.school_frame(SCHOOLS, WEIGHTS)
    working = {"synthetic-a", "synthetic-b", "synthetic-c", "synthetic-d"}
    gains = gate.marginal_gains(registry, frame, working, {"synthetic-a"})
    assert (gains["synthetic-b"].schools, gains["synthetic-b"].weighted) == (3, 3.0)
    assert (gains["synthetic-d"].schools, gains["synthetic-d"].weighted) == (2, 2.0)
    assert gains["synthetic-c"].by_state == {"MO": (1, 0.5)}
    assert "synthetic-a" not in gains
    # With B proven, D (whose districts lie in B's county) would add nothing.
    after = gate.marginal_gains(registry, frame, working, {"synthetic-a", "synthetic-b"})
    assert after["synthetic-d"].schools == 0
    assert after["synthetic-d"].as_json() == {"schools": 0, "weighted": 0.0, "by_state": {}}


def test_school_frame_without_weights_or_optional_columns() -> None:
    frame = gate.school_frame(SCHOOLS.select("state", "county_fips"), None)
    assert frame.columns == ["state", "county_fips", "district_id", "weight"]
    assert frame["weight"].sum() == 0.0
    with pytest.raises(gate.GateError, match="lacks"):
        gate.school_frame(SCHOOLS.select("state"), None)


def test_check_totals_holds_the_gate_to_the_coverage_result(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    result = _result(tmp_path, registry)
    frame = gate.school_frame(SCHOOLS, WEIGHTS)
    gate.check_totals(registry, frame, {"synthetic-a"}, result)
    with pytest.raises(gate.GateError, match="proven schools"):
        gate.check_totals(registry, frame, {"synthetic-a", "synthetic-b"}, result)
    national = _dig(result, "proven", "national")
    assert isinstance(national, dict)
    weighted = national["weighted"]
    assert isinstance(weighted, dict)
    weighted["covered"] = 99.0
    with pytest.raises(gate.GateError, match="proven weight"):
        gate.check_totals(registry, frame, {"synthetic-a"}, result)
    with pytest.raises(gate.GateError, match="no proven share"):
        gate.check_totals(registry, frame, set(), {"stations": {}})


def test_the_census_counts_listed_read_and_unread_captures(tmp_path: Path) -> None:
    registry, report, census = _report(tmp_path)
    b = _table(_dig(report, "stations", "synthetic-b"))
    archive = {str(item["key"]): item for item in _rows(b["archive"])}
    page = archive["synthetic-b.test/closings"]
    assert page["listed"] == 7  # the 404 is not replayable; the revisit is
    assert page["winter"] == 7
    assert page["digests"] == 5
    # Read: the empty capture, its twin by digest, the revisit of it, and the failure.
    assert page["read"] == {"empty": 3, "error": 1}
    assert page["read_captures"] == 4
    assert page["unread"] == 3
    assert page["unread_storm"] == 1
    assert page["listing_asked"] is True
    old = archive["old-b.test/list.json"]
    assert (old["listed"], old["listing_asked"], old["read_captures"]) == (0, False, 0)
    assert census.asked("synthetic-c.test/closings")
    assert not census.asked("synthetic-d.test/closings")
    assert gate.station_keys(registry.stations["synthetic-b"]) == [
        "old-b.test/list.json",
        "synthetic-b.test/closings",
    ]


def test_a_listing_covers_its_url_and_the_paths_under_a_prefix() -> None:
    # SYNTHETIC listing file names, in the workflow's formats.
    census = gate.Census(
        listing_names={
            "www_synthetic_e_test_fs_pages_2_page_pops__20170101-20260927__ff8c6197e.json",
            "synthetic_f_test_closings___20140101-20260930.json",
            "www_synthetic_g_test___20190101-20260930__fe40c3ae4.json",
            "files_synthetic_h_test_closings_json_.json",
            "synthetic_i_test_closings__f0123abcd.json",
        }
    )
    # A listing of another path of the host does not cover the homepage.
    assert census.asked("synthetic-e.test/fs/pages/2/page-pops")
    assert not census.asked("synthetic-e.test/")
    # A prefix listing ("closings*") covers the paths it starts.
    assert census.asked("synthetic-f.test/closings")
    assert census.asked("synthetic-f.test/closings-and-delays")
    assert not census.asked("synthetic-f.test/weather")
    # A homepage listing, asked with www.
    assert census.asked("synthetic-g.test/")
    # The older format, with no window in the name.
    assert census.asked("files.synthetic-h.test/closings.json")
    # A filtered listing in the shared window: its filter's hash, and no days.
    assert census.asked("synthetic-i.test/closings")
    assert not census.asked("synthetic-i.test/")
    assert gate.listing_url_part("notes.txt") == "notes.txt"


def test_verdicts(tmp_path: Path) -> None:
    _, report, _ = _report(tmp_path)
    verdicts = {
        sid: _dig(report, "stations", sid, "verdict")
        for sid in ("a", "b", "c", "d", "e")
        for sid in [f"synthetic-{sid}"]
    }
    assert verdicts == {
        "synthetic-a": "proven",
        "synthetic-b": "unread",
        "synthetic-c": "no-capture",
        "synthetic-d": "not-listed",
        "synthetic-e": "no-endpoint",
    }
    keys = [gate.KeyCensus("k", 1, True, 1, 1, {"empty": 1}, 1, 0, 0)]
    assert gate.verdict("working", False, keys, StationStatus.ACTIVE) == "all-read"
    assert gate.verdict("stale", False, keys, StationStatus.ACTIVE) == "not-working"
    refused = [gate.KeyCensus("k", 1, True, 1, 1, {"error": 1}, 1, 0, 0)]
    assert gate.verdict("working", False, refused, StationStatus.ACTIVE) == "unreadable"
    # Unread captures of an address the station no longer reads cannot prove its list.
    older = [*keys, gate.KeyCensus("old", 3, True, 2, 3, {}, 0, 3, 1, current=False)]
    assert gate.verdict("working", False, older, StationStatus.ACTIVE) == "older-unread"
    newer = [gate.KeyCensus("k", 3, True, 2, 3, {}, 0, 3, 1, current=True)]
    assert gate.verdict("working", False, [*older, *newer], StationStatus.ACTIVE) == "unread"
    assert older[1].as_json()["current"] is False


def test_the_report_names_each_states_gap(tmp_path: Path) -> None:
    _, report, _ = _report(tmp_path)
    assert _dig(report, "targets") == {"national": 0.95, "state": 0.9}
    national = _dig(report, "national")
    assert isinstance(national, dict)
    assert national["gap"] == {"schools": 4, "weighted": 3.5}
    # 95% of 6 schools is 5.7: five more to reach it, and 95% of 7.5 weight is 7.125.
    assert national["to_target"] == {"schools": 4, "weighted": 3.1}
    assert national["meets_target"] is False
    kansas = _dig(report, "states", "KS")
    assert isinstance(kansas, dict)
    assert kansas["meets_target"] is True
    assert kansas["to_target"] == {"schools": 0, "weighted": 0.0}
    assert kansas["settled"] is True
    assert kansas["open"] == []
    missouri = _dig(report, "states", "MO")
    assert isinstance(missouri, dict)
    assert missouri["private_schools"] == 1
    # B's storm-day capture is unread and D's page was never listed: both keep it open.
    assert missouri["settled"] is False
    assert missouri["open"] == ["synthetic-b", "synthetic-d"]
    assert national["settled"] is False
    b = _dig(report, "stations", "synthetic-b")
    assert isinstance(b, dict)
    assert b["readable_since"] == "20240107120000"
    assert b["blind_since"] is None
    assert b["closure_days"] == 0
    assert missouri["stations"] == [
        "synthetic-a",
        "synthetic-b",
        "synthetic-c",
        "synthetic-d",
        "synthetic-e",
    ]
    ranking = _rows(_dig(report, "ranking"))
    assert [item["id"] for item in ranking] == [
        "synthetic-b",
        "synthetic-d",
        "synthetic-c",
    ]
    path = gate.write_report(tmp_path, report)
    assert gate.load_result(path)["ranking"] == ranking


def test_the_plan_picks_storm_days_then_large_captures(tmp_path: Path) -> None:
    registry, report, census = _report(tmp_path)
    ranking = _dig(report, "ranking")
    assert isinstance(ranking, list)
    items: list[Mapping[str, JSONValue]] = [item for item in ranking if isinstance(item, dict)]
    done = gate.downloaded_keys(tmp_path / "artifacts")
    assert done == {("20250106120000", "synthetic-b.test/closings")}
    options = gate.PlanOptions(limit=10, per_station=5, min_weighted=0.1, min_score=0.5)
    plan = gate.plan_captures(
        registry, items, census, done, storms=_storms(registry), options=options
    )
    assert [(item.timestamp, item.station) for item in plan] == [
        ("20250108120000", "synthetic-b"),
        ("20250110120000", "synthetic-b"),
    ]
    assert plan[0].why == "storm day 2025-01-08 (market score 1.00)"
    assert plan[1].why.startswith("largest captures of its winter (5000 bytes")
    assert plan[0].as_json()["url"] == "https://synthetic-b.test/closings"
    # A limit of one, a gain threshold above every station's, or a filter leaves room.
    one = gate.PlanOptions(limit=1, per_station=5, min_weighted=0.1, min_score=0.5)
    assert len(gate.plan_captures(registry, items, census, done, storms=None, options=one)) == 1
    high = gate.PlanOptions(min_weighted=100.0)
    assert gate.plan_captures(registry, items, census, done, storms=None, options=high) == []
    only = gate.PlanOptions(min_weighted=0.1, only=frozenset({"synthetic-c"}))
    assert gate.plan_captures(registry, items, census, done, storms=None, options=only) == []
    with pytest.raises(gate.GateError, match="registry lacks"):
        gate.plan_captures(
            registry, [{"id": "synthetic-z", "weighted": 9.0}], census, done, storms=None
        )


def test_hazard_days_merge_groups() -> None:
    days = {"winter": {"1": {date(2025, 1, 1): 0.5}}, "cold": {"1": {date(2025, 1, 1): 0.8}}}
    assert gate.hazard_days(days, ["winter", "cold"]) == {"1": {date(2025, 1, 1): 0.8}}
    assert gate.hazard_days(days, ["tropical"]) == {}


def test_load_result_refuses_what_is_not_a_coverage_result(tmp_path: Path) -> None:
    path = tmp_path / "coverage.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(gate.GateError, match="not a JSON object"):
        gate.load_result(path)
    with pytest.raises(gate.GateError):
        gate.load_result(tmp_path / "missing.json")
    path.write_text('{"generated_at": "x"}', encoding="utf-8")
    record = gate.file_record(path, {"generated_at": "x"})
    assert record["generated_at"] == "x"


def _setup(tmp_path: Path) -> dict[str, Path]:
    registry = _registry(tmp_path)
    states = _states(registry)
    result = coverage.measure(registry, SCHOOLS, states, None)
    reads = _lines(
        tmp_path / "archive-reads.jsonl",
        [_read("synthetic-a", "https://synthetic-a.test/closings", "2025-01-06T12:00:00Z", 3)],
    )
    evidence = proof.gather(
        live_reads=None, archive_reads=reads, archive_health=None, fixtures=None
    )
    proof.add_proven(result, registry, SCHOOLS, states, evidence)
    out = tmp_path / "out"
    out.mkdir()
    result["generated_at"] = "2026-09-29T00:00:00Z"
    (out / "coverage.json").write_text(json.dumps(result), encoding="utf-8")
    directory = tmp_path / "schools.parquet"
    SCHOOLS.write_parquet(directory)
    gaps = tmp_path / "gaps.json"
    other = {"source_id": "KULR", "gap_state": "MT", "verdict": "built"}
    stale = {"source_id": "old", "gap_state": "MO", "gate": {"piece": "s4"}}
    gaps.write_text(json.dumps([other, stale], indent=1) + "\n", encoding="utf-8")
    return {
        "registry": tmp_path / "sources",
        "out": out,
        "directory": directory,
        "reads": reads,
        "artifacts": _artifacts(tmp_path),
        "gaps": gaps,
    }


def test_report_records_and_plan(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    paths = _setup(tmp_path)
    base = ["stations", "--registry", str(paths["registry"]), "gate"]
    # The closure-text check of the same coverage result comes first (the report
    # refuses to run without it, or with one made against another coverage result).
    checked = [
        *base,
        "text-check",
        "--coverage",
        str(paths["out"] / "coverage.json"),
        "--artifacts",
        str(paths["artifacts"]),
        "--archive-reads",
        str(paths["reads"]),
        "--archive-health",
        str(tmp_path / "missing-health.json"),
        "--out-dir",
        str(paths["out"]),
        "--jobs",
        "1",
    ]
    assert main(checked) == 0
    assert "captures checked:" in capsys.readouterr().out
    code = main(
        [
            *base,
            "report",
            "--closure-text",
            str(paths["out"] / "closure-text.jsonl"),
            "--coverage",
            str(paths["out"] / "coverage.json"),
            "--directory",
            str(paths["directory"]),
            "--no-weights",
            "--no-storms",
            "--artifacts",
            str(paths["artifacts"]),
            "--archive-reads",
            str(paths["reads"]),
            "--archive-health",
            str(tmp_path / "missing-health.json"),
            "--out-dir",
            str(paths["out"]),
            "--gaps",
            str(paths["gaps"]),
        ]
    )
    printed = capsys.readouterr().out
    assert code == 0
    assert "states short of the target: 1 (MO)" in printed
    report = gate.load_result(paths["out"] / gate.GATE_FILE)
    assert report["coverage"] is not None
    assert report["calibration"] is None  # measured only with the storm days
    # The gap file's KULR record (no time of check) touches Montana alone.
    assert _dig(report, "states", "MO", "open_records") == []
    markdown = tmp_path / "gaps.md"
    markdown.write_text("# Gaps\n\nIntroduction.\n\n## Round 1\n\nNotes.\n", encoding="utf-8")
    records = [
        *base,
        "records",
        "--report",
        str(paths["out"] / gate.GATE_FILE),
        "--coverage",
        str(paths["out"] / "coverage.json"),
        "--gaps",
        str(paths["gaps"]),
        "--gaps-md",
        str(markdown),
    ]
    code = main(records)
    assert code == 0
    written = markdown.read_text(encoding="utf-8")
    assert written.startswith("# Gaps\n\nIntroduction.\n\n" + gate.GAPS_MD_START)
    assert written.endswith(gate.GAPS_MD_END + "\n\n## Round 1\n\nNotes.\n")
    assert "| MO |" in written
    assert "| KS |" not in written
    assert main(records) == 0  # a second run replaces the section
    assert markdown.read_text(encoding="utf-8") == written
    assert capsys.readouterr().out.count("records for the states short of the target") == 2
    merged = json.loads(paths["gaps"].read_text(encoding="utf-8"))
    assert merged[0] == {"source_id": "KULR", "gap_state": "MT", "verdict": "built"}
    assert "old" not in {item["source_id"] for item in merged}
    ours = [item for item in merged if item.get("gate")]
    assert {item["source_id"] for item in ours} == {
        "synthetic-a",
        "synthetic-b",
        "synthetic-c",
        "synthetic-d",
        "synthetic-e",
    }
    b = next(item for item in ours if item["source_id"] == "synthetic-b")
    assert b["gap_state"] == "MO"
    assert b["gate"]["verdict"] == "unread"
    # Run with --no-storms: no window, so nothing in it was seen.
    assert (b["gate"]["near_days"], b["gate"]["window_seen"]) == (0, 0)
    assert b["verdict"] == "unproven: captures of its list are not read yet"
    assert "proving it would add 3 schools" in b["notes"]
    assert "synthetic-b.test/closings (current): 7 captures listed" in b["notes"]
    e = next(item for item in ours if item["source_id"] == "synthetic-e")
    assert (e["built_as"], e["origin"], e["closings_url"]) == ([], None, None)
    code = main(
        [
            *base,
            "plan",
            "--report",
            str(paths["out"] / gate.GATE_FILE),
            "--artifacts",
            str(paths["artifacts"]),
            "--archive-reads",
            str(paths["reads"]),
            "--archive-health",
            str(tmp_path / "missing-health.json"),
            "--no-storms",
            "--min-weighted",
            "0",
        ]
    )
    planned = json.loads(capsys.readouterr().out)
    assert code == 0
    assert [item["timestamp"] for item in planned["snapshots"]] == ["20250110120000"]


def test_commands_report_bad_inputs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    paths = _setup(tmp_path)
    base = ["stations", "--registry", str(paths["registry"]), "gate"]
    missing = str(tmp_path / "nothing.json")
    assert main([*base, "report", "--coverage", missing, "--no-weights", "--no-storms"]) == 1
    assert main([*base, "plan", "--report", missing, "--no-storms"]) == 1
    bad: JSONValue = {"ranking": "no"}
    (tmp_path / "bad.json").write_text(json.dumps(bad), encoding="utf-8")
    assert main([*base, "plan", "--report", str(tmp_path / "bad.json"), "--no-storms"]) == 1
    paths["gaps"].write_text("{}", encoding="utf-8")
    code = main(
        [
            *base,
            "records",
            "--report",
            str(tmp_path / "bad.json"),
            "--coverage",
            str(paths["out"] / "coverage.json"),
            "--gaps",
            str(paths["gaps"]),
            "--gaps-md",
            str(tmp_path / "gaps.md"),
        ]
    )
    assert code == 1
    assert not (tmp_path / "gaps.md").exists()
    assert "gate" in capsys.readouterr().err


def test_the_gate_section_is_placed_and_replaced() -> None:
    section = gate.GAPS_MD_START + "\nfirst\n" + gate.GAPS_MD_END + "\n"
    assert gate.replace_section("# T\n", section) == "# T\n\n" + section
    placed = gate.replace_section("# T\n\nIntro.\n\n## R\n", section)
    assert placed == "# T\n\nIntro.\n\n" + section + "\n## R\n"
    again = gate.replace_section(placed, section.replace("first", "second"))
    assert again == "# T\n\nIntro.\n\n" + section.replace("first", "second") + "\n## R\n"
    with pytest.raises(gate.GateError):
        gate.gate_section({"national": {}, "states": {}})


def test_merge_keeps_other_pieces_records() -> None:
    existing: list[dict[str, JSONValue]] = [
        {"source_id": "a"},
        {"source_id": "b", "gate": {"piece": "s4"}},
        {"source_id": "c", "gate": {"piece": "other"}},
    ]
    merged = gate.merge_records(existing, [{"source_id": "d"}])
    assert merged == [
        {"source_id": "a"},
        {"source_id": "c", "gate": {"piece": "other"}},
        {"source_id": "d"},
    ]


def test_markets_count_whole_county_and_district_sources() -> None:
    result: dict[str, JSONValue] = {
        "dmas": {
            "Big": {"schools": 10, "working": ["a", "b"]},
            "Small": {"schools": 3, "working": []},
            "Bare": {"schools": 1, "working": []},
            "Odd": "not a table",
        },
        "counties": {
            "1": {"dmas": ["Big"], "districts": ["d1"]},
            "2": {"dmas": ["Small"], "districts": ["d2", "d3"]},
            "3": "not a table",
        },
    }
    report = gate.dma_report(result, working={"a", "b", "d2", "d3"}, proven={"a", "d3"})
    table = _table(report["dmas"])
    assert _table(table["Big"]) == {
        "schools": 10,
        "working": ["a", "b"],
        "proven": ["a"],
        "working_district": [],
        "proven_district": [],
    }
    assert _table(table["Small"])["proven_district"] == ["d3"]
    summary = _table(report["dma_summary"])
    assert (summary["markets"], summary["with_a_working_source"]) == (3, 2)
    assert (summary["with_a_whole_county_source"], summary["with_a_proven_source"]) == (1, 2)
    assert _rows(summary["biggest_by_schools"])[0] == {
        "dma": "Big",
        "schools": 10,
        "working": 2,
        "working_district": 0,
        "proven": 1,
    }
    assert gate.dma_report({}, set(), set())["dmas"] == {}


def test_the_plan_leaves_out_captures_from_before_the_readable_form() -> None:
    # SYNTHETIC census: a homepage the adapter refused in 2021 (an older site) and read
    # from 2023 on; its unread captures of 2020 and 2022 hold the older form.
    key = "district.test/"
    captures = [
        Capture(stamp, "https://district.test/", "200", "text/html", 1000 + n, f"D{n}")
        for n, stamp in enumerate(
            [
                "20200115120000",
                "20210115120000",
                "20220115120000",
                "20230115120000",
                "20240115120000",
            ]
        )
    ]
    census = gate.Census(
        listings={key: captures},
        read={
            ("20210115120000", key): "error",
            ("20230115120000", key): "empty",
        },
    )
    assert gate.readable_since(census, [key]) == "20210115120000"
    # With nothing read, or nothing refused before the first read, nothing is left out.
    assert gate.readable_since(gate.Census(listings={key: captures}), [key]) is None
    later = gate.Census(listings={key: captures}, read={("20240115120000", key): "error"})
    assert gate.readable_since(later, [key]) is None


RECORDS: list[dict[str, JSONValue]] = [
    # Read once, unreachable that day: never settles a state.
    {
        "source_id": "Timed out (MO)",
        "gap_state": "MO",
        "states": ["MO"],
        "verdict": "not read",
        "checked_at": "2026-10-13T12:00:00Z",
        "built_as": [],
    },
    # A glance from before October: today's site is unknown.
    {
        "source_id": "Glanced (MO)",
        "gap_state": "MO",
        "states": ["MO"],
        "verdict": "not built",
        "checked_at": "2026-09-27T15:49:18Z",
        "built_as": [],
    },
    # Checked again in October and found unreadable: it settles.
    {
        "source_id": "Checked (MO)",
        "gap_state": "MO",
        "states": ["MO", "KS"],
        "verdict": "not built: the homepage is a script shell",
        "checked_at": "2026-10-13T12:00:00Z",
        "built_as": [],
    },
    # No time of check at all.
    {"source_id": "Undated", "gap_state": "MO", "verdict": "no list", "checked_at": None},
    # Built as a registry station: the gate judges the station instead.
    {
        "source_id": "Built",
        "gap_state": "MO",
        "verdict": "built",
        "checked_at": "2026-09-01T00:00:00Z",
        "built_as": ["synthetic-a"],
    },
    # A pointer to another part's registry station.
    {
        "source_id": "Pointer",
        "gap_state": "MO",
        "verdict": "other part's station (synthetic-b)",
        "checked_at": "2026-09-01T00:00:00Z",
        "built_as": [],
    },
    # A pointer to a station the registry does not hold is not built.
    {
        "source_id": "Dangling",
        "gap_state": "MO",
        "verdict": "other part's station (gray-none, no endpoint)",
        "checked_at": "2026-09-01T00:00:00Z",
        "built_as": [],
    },
    # Built as a station the registry does not hold: not built either.
    {
        "source_id": "Renamed",
        "gap_state": "MO",
        "verdict": "built",
        "checked_at": "2026-10-13T00:00:00Z",
        "built_as": ["synthetic-gone"],
    },
    # The gate's own records are of registry stations.
    {
        "source_id": "synthetic-c",
        "gap_state": "MO",
        "verdict": "unproven",
        "checked_at": "2026-09-01T00:00:00Z",
        "gate": {"piece": "s4"},
    },
]


def test_records_of_sources_not_built_keep_their_states_open(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    opened = gate.open_records(RECORDS, registry)
    assert sorted(opened) == ["MO"]
    assert [(item.source_id, item.why) for item in opened["MO"]] == [
        ("Timed out (MO)", "not-read"),
        ("Glanced (MO)", "stale"),
        ("Undated", "unchecked"),
        ("Dangling", "stale"),
    ]
    assert opened["MO"][1].as_json() == {
        "source_id": "Glanced (MO)",
        "verdict": "not built",
        "checked_at": "2026-09-27T15:49:18Z",
        "why": "stale",
    }
    renamed = RECORDS[7]
    assert not gate.record_built(renamed, registry)
    assert gate.open_records([renamed], registry) == {}  # checked in October: not open
    later = datetime(2026, 10, 14, tzinfo=UTC)
    assert [
        item.why for item in gate.open_records([renamed], registry, fresh_since=later)["MO"]
    ] == ["stale"]
    bad_time = {**RECORDS[1], "checked_at": "the 27th"}
    assert gate.open_records([bad_time], registry)["MO"][0].why == "unchecked"


def test_a_short_state_settles_only_on_records_checked_this_month(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _registry(tmp_path)
    result = _result(tmp_path, registry)
    census = _census(tmp_path)
    # Every source of Missouri has a terminal verdict here, so only the records decide.
    monkeypatch.setattr(gate, "_open_sources", lambda *_args: [])

    def missouri(records: list[dict[str, JSONValue]] | None) -> dict[str, JSONValue]:
        report = gate.build_report(
            registry,
            result,
            gate.school_frame(SCHOOLS, WEIGHTS),
            census,
            _storms(registry),
            coverage_file={"path": "coverage.json", "sha256": SHA, "generated_at": None},
            now=datetime(2026, 10, 13, 3, tzinfo=UTC),
            records=records,
        )
        kansas = _table(_dig(report, "states", "KS"))
        assert (kansas["settled"], kansas["open_records"]) == (True, [])  # meets the target
        return _table(_dig(report, "states", "MO"))

    assert missouri(None)["settled"] is False  # no gap file read: nothing settles
    assert missouri([])["settled"] is True
    fresh = [RECORDS[2], RECORDS[4], RECORDS[5], RECORDS[8]]
    assert missouri(fresh)["settled"] is True
    held = missouri([*fresh, RECORDS[1]])
    assert held["settled"] is False
    assert held["open"] == []
    assert _rows(held["open_records"]) == [
        {
            "source_id": "Glanced (MO)",
            "verdict": "not built",
            "checked_at": "2026-09-27T15:49:18Z",
            "why": "stale",
        }
    ]
    section = gate.gate_section(
        {
            "generated_at": "2026-10-13T03:00:00Z",
            "coverage": {"generated_at": "2026-10-13T00:00:00Z"},
            "national": {"proven": {"share": 0.5}, "to_target": {"schools": 1, "weighted": 1}},
            "states": {"MO": held},
            "stations": {},
        }
    )
    assert "| 1 records |" in section
    assert "checked before 2026-10-01" in section
