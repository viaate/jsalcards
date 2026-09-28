"""The whole build on a SYNTHETIC world: snapshot, match, guard, measure, outputs, determinism.

Everything here is SYNTHETIC and confined to this test: a directory of invented
districts and schools (``SYN`` names, ``99`` ids), a registry of invented
stations, their reads and rows, coverage and weights files, and square county
outlines. It checks the definitions end to end: a school named on a list is SEEN
by name, every school of a district named is SEEN through it, a church matches
nothing, a row whose list places it in another state takes its match away, a
district website's rows do not count, and the same snapshot gives the same bytes.
"""

import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest
import shapely

from snowlight.cli import main
from snowlight.listed import audit
from snowlight.listed.build import BuildError, BuildPaths, build, county_names, matcher_fingerprint
from snowlight.listed.snapshot import SnapshotError, load_snapshot
from snowlight.weights.zones import County, CountyList

DISTRICT = "9900001"
DISTRICT_SCHOOLS = ("990000100001", "990000100002", "990000100003")
PRIVATE = "S9900001"
OTHER_DISTRICT = "9900002"
OTHER_SCHOOL = "990000200001"
KS_SCHOOL = "990000300001"


def _districts() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "district_id": [DISTRICT, OTHER_DISTRICT, "9900003"],
            "name": ["Quillfeather R-7", "Marrowbrook R-2", "Tansyridge USD 900"],
            "state": ["MO", "MO", "KS"],
            "state_fips": ["29", "29", "20"],
            "county_fips": ["29095", "29095", "20091"],
            "county_name": ["Jackson County", "Jackson County", "Johnson County"],
            "city": ["Quillfeather", "Marrowbrook", "Tansyridge"],
            "lat": [39.00, 39.10, 38.90],
            "lon": [-94.40, -94.50, -94.80],
        }
    )


def _schools() -> pl.DataFrame:
    ids = [*DISTRICT_SCHOOLS, OTHER_SCHOOL, KS_SCHOOL, PRIVATE]
    return pl.DataFrame(
        {
            "index": list(range(len(ids))),
            "id": ids,
            "name": [
                "Quillfeather Elementary",
                "Quillfeather Middle",
                "Quillfeather High",
                "Marrowbrook Elementary",
                "Tansyridge Elementary",
                "Saint Brindlewood Academy",
            ],
            "district_id": [DISTRICT] * 3 + [OTHER_DISTRICT, "9900003", None],
            "state": ["MO", "MO", "MO", "MO", "KS", "MO"],
            "state_fips": ["29", "29", "29", "29", "20", "29"],
            "county_fips": ["29095"] * 4 + ["20091", "29095"],
            "county_name": ["Jackson County"] * 4 + ["Johnson County", "Jackson County"],
            "city": [
                "Quillfeather",
                "Quillfeather",
                "Quillfeather",
                "Marrowbrook",
                "Tansyridge",
                "Quillfeather",
            ],
            "lat": [39.00, 39.01, 39.02, 39.10, 38.90, 39.03],
            "lon": [-94.40, -94.41, -94.42, -94.50, -94.80, -94.43],
            "grade_low": ["KG", "06", "09", "KG", "KG", "PK"],
            "grade_high": ["05", "08", "12", "05", "05", "08"],
            "level": ["Elementary", "Middle", "High", "Elementary", "Elementary", "Elementary"],
        }
    )


def _platform(platform: str, stations: list[dict[str, object]]) -> dict[str, object]:
    return {
        "platform": {
            "id": platform,
            "name": "SYNTHETIC platform",
            "operator": "SYNTHETIC",
            "adapter": platform,
            "poll_minutes": 10,
            "terms": {"automated_access": "unread", "summary": "SYNTHETIC", "evidence": []},
            "notes": "SYNTHETIC",
            "shared_paths": [],
        },
        "stations": stations,
    }


def _station(station_id: str, platform: str) -> dict[str, object]:
    return {
        "id": station_id,
        "platform": platform,
        "call_sign": "SYNT",
        "name": "SYNTHETIC station",
        "market": "SYNTHETIC market",
        "dma": None,
        "states": ["KS", "MO"],
        "counties": {"basis": "dma", "source": "SYNTHETIC", "fips": ["20091", "29095"]},
        "page_url": "https://example.invalid/closings",
        "data_url": None,
        "archive_urls": [],
        "poll_minutes": None,
        "status": "active",
        "evidence": "SYNTHETIC",
    }


def _read(source: str, at: str, rows: int, sha: str) -> dict[str, object]:
    return {
        "source_id": source,
        "mode": "archive",
        "url": "https://example.invalid/closings",
        "fetched_at": at,
        "retrieved_at": "2026-09-01T00:00:00Z",
        "sha256": sha,
        "bytes": 1,
        "variant": "hearst-rows",
        "state": "populated",
        "rows": rows,
    }


def _row(source: str, at: str, name: str, location: str = "") -> dict[str, object]:
    return {
        "source_id": source,
        "fetched_at": at,
        "raw_name": name,
        "raw_status": "Closed",
        "raw_updated_text": None,
        "raw_extra": {"location": location},
    }


def _jsonl(path: Path, items: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(item) + "\n" for item in items), encoding="utf-8")
    return path


def _world(root: Path) -> dict[str, Path]:
    """Write the SYNTHETIC inputs; return them by snapshot name."""
    directory = root / "directory"
    directory.mkdir(parents=True)
    _districts().write_parquet(directory / "districts.parquet")
    _schools().write_parquet(directory / "schools.parquet")
    registry = root / "sources"
    registry.mkdir()
    for platform, stations in (("synth", ["synth-a", "synth-b"]), ("apptegy", ["apptegy-syn"])):
        body = _platform(platform, [_station(s, platform) for s in stations])
        (registry / f"{platform}.yaml").write_text(json.dumps(body), encoding="utf-8")
    early, late = "2024-01-09T12:00:00Z", "2025-02-18T12:00:00Z"
    archive_rows = [
        _row("synth-a", early, "Saint Brindlewood Academy", "Jackson, Quillfeather, MO"),
        _row("synth-a", early, "Quillfeather R-7", "Jackson, Quillfeather, MO"),
        _row("synth-a", early, "First Baptist Church of Quillfeather"),
        _row("synth-a", late, "Saint Brindlewood Academy", "Jackson, Quillfeather, MO"),
        _row("synth-a", late, "Marrowbrook Elementary", "Johnson, Tansyridge, KS"),
        _row("synth-a", late, "Tansyridge Elementary School"),
        _row("apptegy-syn", late, "Quillfeather Middle"),
    ]
    archive_reads = [
        _read("synth-a", early, 3, "1" * 64),
        _read("synth-a", late, 3, "2" * 64),
        _read("apptegy-syn", late, 1, "3" * 64),
    ]
    live_rows = [_row("synth-b", "2026-09-27T10:00:00Z", "QUILLFEATHER HIGH")]
    live_reads = [_read("synth-b", "2026-09-27T10:00:00Z", 1, "4" * 64)]
    station_dir = root / "stations"
    coverage = station_dir / "coverage.json"
    coverage.parent.mkdir(parents=True, exist_ok=True)
    coverage.write_text(
        json.dumps(
            {
                "generated_at": "2026-09-01T00:00:00Z",
                "national": {"share": 1.0, "weighted": {"share": 1.0}},
                "states": {"KS": {"share": 1.0}, "MO": {"share": 0.9, "weighted": {"share": 0.8}}},
                "proven": {"national": {"share": 0.5}, "states": {"MO": {"share": 0.5}}},
            }
        ),
        encoding="utf-8",
    )
    weights = root / "closure-weights.json"
    weights.write_text(
        json.dumps(
            {
                "generated_at": "2026-09-01T00:00:00Z",
                "counties": [{"fips": "29095", "weight": 2.0}, {"fips": "20091", "weight": 0.5}],
            }
        ),
        encoding="utf-8",
    )
    aliases = root / "aliases.yaml"
    aliases.write_text("schema_version: 1\nmarkets: {}\n", encoding="utf-8")
    return {
        "live_reads": _jsonl(station_dir / "reads.jsonl", live_reads),
        "live_rows": _jsonl(station_dir / "rows.jsonl", live_rows),
        "archive_reads": _jsonl(station_dir / "archive" / "reads.jsonl", archive_reads),
        "archive_rows": _jsonl(station_dir / "archive" / "rows.jsonl", archive_rows),
        "coverage": coverage,
        "aliases": aliases,
        "districts": directory / "districts.parquet",
        "schools": directory / "schools.parquet",
        "weights": weights,
    }


def _counties() -> CountyList:
    """Two SYNTHETIC square counties around the synthetic schools."""
    return CountyList(
        counties={
            "29095": County(
                "29095",
                "MO",
                "Jackson",
                ("America/Chicago",),
                shapely.box(-94.7, 38.8, -94.2, 39.3),
            ),
            "20091": County(
                "20091",
                "KS",
                "Johnson",
                ("America/Chicago",),
                shapely.box(-95.1, 38.6, -94.7, 39.1),
            ),
        },
        state_fips={"MO": "29", "KS": "20"},
        records=2,
    )


def _build(
    root: Path, inputs: dict[str, Path], *, reuse: bool = False, workers: int = 1
) -> BuildPaths:
    paths = BuildPaths(
        out_dir=root / "out", snapshot_dir=root / "out" / "snapshot", roster_cache=root / "cache"
    )
    build(
        paths,
        _counties,
        inputs=inputs,
        registry_dir=root / "sources",
        reuse_snapshot=reuse,
        workers=workers,
        require_rosters=False,
    )
    return paths


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Path], BuildPaths]:
    """The SYNTHETIC world, built once."""
    root = tmp_path_factory.mktemp("world")
    inputs = _world(root)
    return root, inputs, _build(root, inputs)


def _json(paths: BuildPaths, name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((paths.out_dir / name).read_text(encoding="utf-8"))
    return data


def test_schools_are_seen_by_name_or_through_their_district(
    world: tuple[Path, dict[str, Path], BuildPaths],
) -> None:
    paths = world[2]
    table = pl.read_parquet(paths.out_dir / "schools.parquet")
    assert table.columns == [
        "id", "state", "seen", "roster", "basis", "source_ids", "first_seen", "last_seen",
        "rows_seen",
    ]  # fmt: skip
    rows = {row["id"]: row for row in table.iter_rows(named=True)}
    private = rows[PRIVATE]
    assert (private["seen"], private["basis"], private["rows_seen"]) == (True, "school", 2)
    assert private["first_seen"].strftime("%Y-%m-%dT%H:%M:%SZ") == "2024-01-09T12:00:00Z"
    assert private["last_seen"].strftime("%Y-%m-%dT%H:%M:%SZ") == "2025-02-18T12:00:00Z"
    assert private["source_ids"] == ["synth-a"]
    for school in DISTRICT_SCHOOLS[:2]:
        assert (rows[school]["seen"], rows[school]["basis"]) == (True, "district")
    high = rows[DISTRICT_SCHOOLS[2]]
    assert high["basis"] == "school"  # named on synth-b, and reached through its district
    assert high["source_ids"] == ["synth-a", "synth-b"]
    other = rows[OTHER_SCHOOL]  # its list places it in Kansas
    assert (other["seen"], other["basis"], other["first_seen"]) == (False, None, None)
    assert (rows[KS_SCHOOL]["seen"], rows[KS_SCHOOL]["roster"]) == (True, False)


def test_listed_json_counts_and_evidence(world: tuple[Path, dict[str, Path], BuildPaths]) -> None:
    listed = _json(world[2], "listed.json")
    national = listed["national"]
    assert national["schools"] == 6
    assert (national["seen"]["count"], national["listed"]["count"]) == (5, 5)
    assert national["roster"]["count"] == 0
    assert national["weighted_schools"] == 5 * 2.0 + 0.5
    assert national["seen"]["weighted_share"] == round((4 * 2.0 + 0.5) / 10.5, 4)
    assert listed["states"]["KS"]["seen"]["share"] == 1.0
    assert list(listed["excluded_sources"]) == ["apptegy-syn"]
    assert listed["excluded_sources"]["apptegy-syn"].startswith("a district's own website")
    assert (listed["rows"]["from_excluded_sources"], listed["rows"]["counted"]) == (1, 7)
    assert listed["row_outcomes"]["place_conflict"] == 1
    assert listed["row_outcomes"]["not_school"] == 1
    assert listed["coverage"]["states"]["MO"]["area"] == {"share": 0.9, "weighted_share": 0.8}
    assert listed["gaps"][0] == {"state": "MO", "area_share": 0.9, "listed_share": 0.8, "gap": 0.1}
    assert listed["generated_at"] == "2026-09-01T00:00:00Z"
    assert listed["matcher"]["sources_sha256"] == matcher_fingerprint()
    assert listed["evidence"]["archive_rows"]["path"] == "archive/rows.jsonl"
    assert set(listed["evidence"]) >= {"live_reads", "registry/synth.yaml", "nws_counties"}


def test_unmatched_and_matches(world: tuple[Path, dict[str, Path], BuildPaths]) -> None:
    paths = world[2]
    unmatched = _json(paths, "unmatched.json")
    queued = unmatched["stations"]["synth-a"]["entries"]
    assert {entry["name"] for entry in queued} == {"Marrowbrook Elementary"}
    assert queued[0]["reason"] == "place_conflict"
    assert "First Baptist Church of Quillfeather" not in json.dumps(unmatched)
    matches = (paths.out_dir / "matches.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(matches) == 6
    drawn = audit.draw(audit.accepted_matches(paths.out_dir / "matches.jsonl"), size=2, seed=1)
    assert len(drawn) == 2
    assert all(match.line["accepted"] is True for match in drawn)


def test_the_same_snapshot_gives_the_same_bytes(
    world: tuple[Path, dict[str, Path], BuildPaths],
) -> None:
    root, inputs, paths = world
    names = ("listed.json", "schools.parquet", "unmatched.json", "matches.jsonl")
    before = {name: (paths.out_dir / name).read_bytes() for name in names}
    _build(root, inputs, reuse=True)
    assert {name: (paths.out_dir / name).read_bytes() for name in names} == before


def test_a_new_snapshot_of_the_same_inputs_gives_the_same_bytes(tmp_path: Path) -> None:
    inputs = _world(tmp_path)
    first = _build(tmp_path, inputs)
    kept = (first.out_dir / "listed.json").read_bytes()
    _build(tmp_path, inputs)
    assert (first.out_dir / "listed.json").read_bytes() == kept
    snapshot = load_snapshot(first.snapshot_dir)
    assert snapshot.has("archive_rows")
    assert not snapshot.has("rosters")
    (first.snapshot_dir / "archive" / "rows.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(SnapshotError, match="altered"):
        load_snapshot(first.snapshot_dir)


def test_rosters_are_required_unless_waived(tmp_path: Path) -> None:
    inputs = _world(tmp_path)
    inputs["rosters"] = tmp_path / "missing-rosters.json"
    paths = BuildPaths(
        out_dir=tmp_path / "out", snapshot_dir=tmp_path / "snap", roster_cache=tmp_path / "c"
    )
    with pytest.raises(SnapshotError, match="rosters"):
        build(paths, _counties, inputs=inputs, registry_dir=tmp_path / "sources")
    del inputs["rosters"]
    with pytest.raises(BuildError, match="rosters"):
        build(paths, _counties, inputs=inputs, registry_dir=tmp_path / "sources")


def test_county_names_resolve_the_directory_counties(tmp_path: Path) -> None:
    inputs = _world(tmp_path)
    assert county_names(inputs["schools"]) == {
        ("MO", "jackson"): "29095",
        ("KS", "johnson"): "20091",
    }


def test_the_cli_audit_and_its_failures(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    inputs = _world(tmp_path)
    paths = _build(tmp_path, inputs)
    out = tmp_path / "sample.json"
    code = main(
        [
            "listed",
            "audit",
            "--matches",
            str(paths.out_dir / "matches.jsonl"),
            "--out",
            str(out),
            "--size",
            "3",
        ]
    )
    assert code == 0
    sample = json.loads(out.read_text(encoding="utf-8"))
    assert sample["size"] == 3
    assert "audit: 3 matches" in capsys.readouterr().out
    assert main(["listed", "audit", "--matches", str(tmp_path / "none.jsonl")]) == 1
    assert "listed audit:" in capsys.readouterr().err
