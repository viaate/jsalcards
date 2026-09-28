"""The parts of the measure on SYNTHETIC inputs: evidence, tallies, places, audit, snapshot.

Every record, row and outline here is SYNTHETIC (invented for the test).
"""

import json
from pathlib import Path

import numpy as np
import polars as pl
import pytest
import shapely

from snowlight.cli import main
from snowlight.listed import audit
from snowlight.listed.evidence import ListRow
from snowlight.listed.located import Gazetteer, Place, Verdict, place_key, state_code, stated_places
from snowlight.listed.matching import MatcherSpec, Outcome, Query, match_all
from snowlight.listed.measure import (
    ClosureWeights,
    MeasureError,
    aggregate,
    load_closure_weights,
    school_table,
    school_weights,
    tally,
)
from snowlight.listed.rosters import RosterEntry
from snowlight.listed.scope import Context
from snowlight.listed.snapshot import SnapshotError, take_snapshot
from snowlight.match import Directory, DirectoryRecord, Matcher
from snowlight.weights.schools import PlacedSchool, Placement
from snowlight.weights.zones import County, CountyList

CONTEXT = Context("syn-list", ("MO",), None)


def _row(name: str, at: str, source: str = "syn-list") -> ListRow:
    return ListRow(source, "archive", at, "f" * 64, "syn-variant", name, "Closed", None)


def _outcome(
    direct: tuple[str, ...] = (), via: tuple[str, ...] = (), *, accepted: bool = True
) -> Outcome:
    return Outcome(
        accepted=accepted,
        reason="name" if accepted else "ambiguous",
        level="school",
        confidence=1.0,
        targets=direct or ("D1",),
        direct=direct,
        via_district=via,
        best_id=None,
        best_name=None,
        best_score=None,
        detail="",
    )


def _entry(name: str) -> RosterEntry:
    return RosterEntry(
        "syn-list/roster", "syn-list", name, "S", "1", CONTEXT, "e" * 64, "2026-09-28T00:00:00Z"
    )


def test_evidence_basis_and_dates() -> None:
    evidence = aggregate(
        [
            (_row("A", "2024-01-02T00:00:00Z"), _outcome(direct=("S1",))),
            (_row("B", "2023-05-01T00:00:00Z"), _outcome(via=("S1", "S2"))),
            (_row("C", "2025-01-01T00:00:00Z", "syn-other"), _outcome(via=("S2",))),
            (_row("D", "2026-01-01T00:00:00Z"), _outcome(direct=("S9",), accepted=False)),
        ],
        [
            (_entry("R"), _outcome(via=("S2", "S3"))),
            (_entry("Q"), _outcome(direct=("S4",), accepted=False)),
        ],
    )
    assert set(evidence) == {"S1", "S2", "S3"}
    s1, s2, s3 = evidence["S1"], evidence["S2"], evidence["S3"]
    assert (s1.basis, s1.rows_seen, s1.first_seen, s1.last_seen) == (
        "school", 2, "2023-05-01T00:00:00Z", "2024-01-02T00:00:00Z"
    )  # fmt: skip
    assert (s2.basis, s2.seen, s2.roster) == ("district", True, True)
    assert s2.sources == {"syn-list", "syn-other", "syn-list/roster"}
    assert (s3.basis, s3.seen, s3.roster, s3.rows_seen, s3.first_seen) == (
        "roster",
        False,
        True,
        0,
        None,
    )
    table = school_table([("S1", "MO"), ("S2", "MO"), ("S3", "KS"), ("S5", "KS")], evidence)
    assert table["basis"].to_list() == ["school", "district", "roster", None]
    assert table["rows_seen"].to_list() == [2, 2, 0, 0]
    assert table.schema["first_seen"] == pl.Datetime("us", "UTC")
    with pytest.raises(MeasureError, match="outside the directory"):
        school_table([("S1", "MO")], evidence)


def test_tallies_plain_and_weighted() -> None:
    table = pl.DataFrame(
        {
            "id": ["S1", "S2", "S3", "S4"],
            "state": ["MO", "MO", "KS", "KS"],
            "seen": [True, False, False, False],
            "roster": [True, True, False, False],
        }
    )
    national, states = tally(table, {"S1": 2.0, "S2": 1.0, "S3": 1.0})
    out = national.to_json()
    assert out["schools"] == 4
    assert out["weighted_schools"] == 4.0
    assert out["seen"] == {"count": 1, "share": 0.25, "weighted": 2.0, "weighted_share": 0.5}
    assert out["listed"] == {"count": 2, "share": 0.5, "weighted": 3.0, "weighted_share": 0.75}
    assert states["KS"].to_json()["listed"] == {
        "count": 0, "share": 0.0, "weighted": 0.0, "weighted_share": 0.0
    }  # fmt: skip
    plain, _states = tally(table.head(0), None)
    seen = plain.to_json()["seen"]
    assert isinstance(seen, dict)
    assert seen["share"] == 0.0


def test_closure_weights(tmp_path: Path) -> None:
    path = tmp_path / "closure-weights.json"
    path.write_text(
        json.dumps({"generated_at": "x", "counties": [{"fips": "29095", "weight": 1.5}]})
    )
    weights = load_closure_weights(path)
    assert weights.by_county == {"29095": 1.5}
    placement = Placement(
        schools=[
            PlacedSchool(0, "S1", "MO", "MO", "29095", "29095", "fips"),
            PlacedSchool(1, "S2", "MO", "MO", "29097", "29097", "fips"),
        ]
    )
    assert school_weights(weights, placement) == {"S1": 1.5}
    bad_files: tuple[dict[str, object], ...] = (
        {"counties": []},
        {"counties": [{"fips": "1", "weight": 1}]},
        {"counties": [{"fips": "29095", "weight": 1}, {"fips": "29095", "weight": 2}]},
    )
    for bad in bad_files:
        path.write_text(json.dumps(bad))
        with pytest.raises(MeasureError):
            load_closure_weights(path)
    assert isinstance(weights, ClosureWeights)


def test_places_rows_name() -> None:
    assert stated_places("hearst-rows", {"location": "Jackson, Kansas City, MO"}) == (
        Place("MO", "Kansas City", "Jackson"),
    )
    assert stated_places("hearst-rows", {"location": "ok, okc, OK"}) == (Place("OK"),)
    assert stated_places("hearst-ibsys", {"address": "Elkton / Cecil / MD"}) == (
        Place("MD", "Elkton", "Cecil"),
    )
    assert stated_places("abc-legacy-list", {"county": "LAKE, IN COUNTY"}) == (
        Place("IN", None, "LAKE"),
    )
    assert stated_places("gray-file-sc-xml", {"City": "READING PA 19606"}) == ()
    assert stated_places("heritage-bti-table", {"address": "Coulee Dam, Wa"}) == (
        Place("WA", "Coulee Dam", None),
    )
    assert stated_places(
        "whdh-closings-block", {"address": "Address: 3 Washburn Square Leicester, MA 01524"}
    ) == (Place("MA"),)
    assert stated_places(
        "hearst-next", {"locations": '[{"city":"Manchester","county":"Hillsborough","state":"NH"}]'}
    ) == (Place("NH", "Manchester", "Hillsborough"),)
    assert stated_places("hearst-next", {"locations": "not json"}) == ()
    assert stated_places("nbc-wp-page", {"state": "Connecticut"}) == (Place("CT"),)
    assert stated_places("nbc-wp-page", {"state": None}) == ()
    assert stated_places("gray-s3-json", {"state": "ARKANSAS", "county_name1": "Dent"}) == ()
    assert stated_places("ecc-legacy-page", {"City": "N/A"}) == ()
    assert state_code("New Jersey") == "NJ"
    assert state_code("other") is None
    assert place_key("St. Louis") == place_key("SAINT LOUIS") == "SAINTLOUIS"
    assert place_key("LAGRANGE") == place_key("La Grange")
    assert place_key("O'Fallon") == place_key("O FALLON")
    assert place_key("MILWAUKEE CO", county=True) == "MILWAUKEE"


def _gazetteer() -> Gazetteer:
    schools = pl.DataFrame(
        {
            "id": ["S1", "S2", "S3"],
            "district_id": ["D1", "D1", None],
            "city": ["Quillfeather", "Marrowbrook", "Farhaven"],
            "state": ["MO", "MO", "KS"],
            "lat": [39.0, 39.3, 38.0],
            "lon": [-94.4, -94.4, -97.0],
        }
    )
    districts = pl.DataFrame(
        {
            "district_id": ["D1"],
            "city": ["Quillfeather"],
            "state": ["MO"],
            "lat": [39.0],
            "lon": [-94.4],
        }
    )
    counties = CountyList(
        counties={
            "29095": County(
                "29095",
                "MO",
                "Jackson",
                ("America/Chicago",),
                shapely.box(-94.6, 38.9, -94.2, 39.1),
            )
        },
        state_fips={"MO": "29"},
        records=1,
    )
    return Gazetteer.build(schools, districts, counties)


def test_verdicts() -> None:
    gazetteer = _gazetteer()
    states = ("KS", "MO")
    assert gazetteer.verdict([Place(None, "Quillfeather", None)], ["S1"], states) is Verdict.AGREES
    assert gazetteer.verdict([Place(None, "Farhaven", None)], ["S1"], states) is Verdict.CONFLICT
    assert gazetteer.verdict([Place("KS")], ["S1"], states) is Verdict.CONFLICT
    assert gazetteer.verdict([Place("MO")], ["S1"], states) is Verdict.AGREES
    assert gazetteer.verdict([Place(None, "Nowhere", None)], ["S1"], states) is Verdict.UNKNOWN
    assert gazetteer.verdict([], ["S1"], states) is Verdict.UNKNOWN
    assert gazetteer.verdict([Place(None, None, "Jackson")], ["S1"], states) is Verdict.AGREES
    assert gazetteer.verdict([Place(None, None, "Jackson")], ["S3"], states) is Verdict.CONFLICT
    # A district is where any of its schools is: Marrowbrook's school is 33 km north.
    assert gazetteer.verdict([Place(None, "Marrowbrook", None)], ["D1"], states) is Verdict.AGREES
    # Town and county both count: the town is wrong, the county right.
    assert gazetteer.verdict([Place("MO", "Farhaven", "Jackson")], ["S1"], states) is Verdict.AGREES
    assert gazetteer.verdict([Place(None, "Quillfeather", None)], ["X9"], states) is Verdict.UNKNOWN


def test_allocation_is_proportional_with_one_each() -> None:
    sizes = {("MO", "school"): 90, ("MO", "district"): 8, ("KS", "roster"): 2}
    assert audit.allocate(sizes, 10) == {
        ("MO", "school"): 8,
        ("MO", "district"): 1,
        ("KS", "roster"): 1,
    }
    assert audit.allocate(sizes, 200) == sizes
    assert audit.allocate(sizes, 2) == {
        ("MO", "school"): 1,
        ("MO", "district"): 1,
        ("KS", "roster"): 0,
    }
    with pytest.raises(ValueError, match="positive"):
        audit.allocate(sizes, 0)


def test_the_audit_sample_is_reproducible(tmp_path: Path) -> None:
    lines = [
        {
            "source_id": f"s{i}",
            "name": f"N{i}",
            "section": None,
            "kind": "row",
            "accepted": i % 4 != 0,
            "targets": [
                {
                    "id": str(i),
                    "kind": "school" if i % 2 else "district",
                    "state": "MO" if i < 20 else "KS",
                }
            ],
        }
        for i in range(40)
    ] + [{"source_id": "r", "name": "R", "kind": "roster", "accepted": True, "targets": []}]
    path = tmp_path / "matches.jsonl"
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    found = audit.accepted_matches(path)
    assert len(found) == 31
    assert {m.stratum for m in found} >= {("MO", "school"), ("KS", "district"), ("", "roster")}
    first = audit.draw(found, size=8, seed=3)
    assert [m.key for m in first] == [m.key for m in audit.draw(found, size=8, seed=3)]
    assert len(first) == 8
    audit.write_sample(tmp_path / "sample.json", first, seed=3)
    assert json.loads((tmp_path / "sample.json").read_text())["size"] == 8


def test_snapshot_needs_every_input(tmp_path: Path) -> None:
    registry = tmp_path / "sources"
    registry.mkdir()
    (registry / "syn.yaml").write_text("{}")
    with pytest.raises(SnapshotError, match="not found"):
        take_snapshot(
            {"coverage": tmp_path / "none.json"}, registry, tmp_path / "snap", base=tmp_path
        )
    with pytest.raises(SnapshotError, match="no place"):
        take_snapshot({"other": tmp_path / "x"}, registry, tmp_path / "snap", base=tmp_path)
    (tmp_path / "reads.jsonl").write_text("")
    with pytest.raises(SnapshotError, match="together"):
        take_snapshot(
            {"live_reads": tmp_path / "reads.jsonl"}, registry, tmp_path / "snap", base=tmp_path
        )
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(SnapshotError, match="no registry"):
        take_snapshot(
            {"live_reads": tmp_path / "reads.jsonl", "live_rows": tmp_path / "reads.jsonl"},
            empty,
            tmp_path / "snap",
            base=tmp_path,
        )


def test_snapshot_retakes_a_pair_that_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = tmp_path / "sources"
    registry.mkdir()
    (registry / "syn.yaml").write_text("{}")
    reads, rows = tmp_path / "reads.jsonl", tmp_path / "rows.jsonl"
    reads.write_text("one\n")
    rows.write_text("r\n")
    copied: list[Path] = []
    changes = {"left": 1}

    def copy_while_a_builder_rewrites(source: Path, dest: Path) -> None:
        Path(dest).write_bytes(Path(source).read_bytes())
        copied.append(source)
        if source == rows and changes["left"] > 0:
            changes["left"] -= 1
            reads.write_text(f"recounted {len(copied)}\n")

    monkeypatch.setattr("snowlight.listed.snapshot.shutil.copyfile", copy_while_a_builder_rewrites)
    waits: list[float] = []
    snap = take_snapshot(
        {"live_reads": reads, "live_rows": rows},
        registry,
        tmp_path / "snap",
        base=tmp_path,
        sleep=waits.append,
    )
    assert len(waits) == 1
    assert snap.path("live_reads").read_text() == reads.read_text()
    changes["left"] = 99
    with pytest.raises(SnapshotError, match="kept changing"):
        take_snapshot(
            {"live_reads": reads, "live_rows": rows},
            registry,
            tmp_path / "snap",
            base=tmp_path,
            sleep=waits.append,
        )


def _directory(tmp_path: Path) -> Path:
    folder = tmp_path / "directory"
    folder.mkdir()
    pl.DataFrame(
        {
            "district_id": ["9900001"],
            "name": ["Quillfeather R-7"],
            "state": ["MO"],
            "county_fips": ["29095"],
            "city": ["Quillfeather"],
            "lat": [39.0],
            "lon": [-94.4],
            "county_name": ["Jackson County"],
        }
    ).write_parquet(folder / "districts.parquet")
    names = [f"Synthetic Number {i} Elementary" for i in range(12)]
    pl.DataFrame(
        {
            "id": [f"99000010{i:04d}" for i in range(12)],
            "name": names,
            "district_id": ["9900001"] * 12,
            "state": ["MO"] * 12,
            "county_fips": ["29095"] * 12,
            "city": ["Quillfeather"] * 12,
            "lat": list(np.linspace(39.0, 39.1, 12)),
            "lon": [-94.4] * 12,
            "grade_low": ["KG"] * 12,
            "grade_high": ["05"] * 12,
            "level": ["Elementary"] * 12,
            "county_name": ["Jackson County"] * 12,
        }
    ).write_parquet(folder / "schools.parquet")
    return folder


def test_worker_processes_give_the_same_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _directory(tmp_path)
    aliases = tmp_path / "aliases.yaml"
    aliases.write_text("schema_version: 1\nmarkets: {}\n")
    spec = MatcherSpec(folder, aliases)
    matcher = spec.build()
    queries = [Query(CONTEXT, f"Synthetic Number {i} Elementary", None) for i in range(12)]
    queries += [Query(CONTEXT, "Quillfeather R-7", "Schools"), Query(CONTEXT, "Nothing Here", None)]
    alone = match_all(matcher, queries)
    monkeypatch.setattr("snowlight.listed.matching.CHUNK", 3)
    assert match_all(matcher, queries, workers=2, spec=spec) == alone
    assert alone[queries[0]].direct == ("990000100000",)
    assert len(alone[queries[12]].via_district) == 12
    assert not alone[queries[13]].accepted


def test_a_directory_record_is_a_school_or_district() -> None:
    directory = Directory(
        [
            DirectoryRecord(
                "9900001", "Quillfeather R-7", "district", None, "MO", "29095", "Q", 39.0, -94.4
            )
        ]
    )
    assert len(Matcher(directory).directory) == 1


def test_the_cli_keeps_intact_rosters(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out, cache = tmp_path / "rosters.json", tmp_path / "cache"
    cache.mkdir()
    body = b"<flashnews/>"
    import hashlib  # noqa: PLC0415

    sha = hashlib.sha256(body).hexdigest()
    (cache / f"{sha}.body").write_bytes(body)
    out.write_text(
        json.dumps(
            {
                "user_agent": "x",
                "reads": [
                    {
                        "roster": "a/roster",
                        "station_id": "a",
                        "part": "p",
                        "url": "https://example.invalid",
                        "final_url": "https://example.invalid",
                        "fetched_at": "2026-09-28T00:00:00Z",
                        "sha256": sha,
                        "bytes": len(body),
                        "content_type": None,
                        "robots": [],
                    }
                ],
            }
        )
    )
    assert main(["listed", "rosters", "--out", str(out), "--cache-dir", str(cache)]) == 0
    assert "nothing read" in capsys.readouterr().out
    assert (
        main(["listed", "build", "--reuse-snapshot", "--snapshot-dir", str(tmp_path / "none")]) == 1
    )
    assert "listed build:" in capsys.readouterr().err


def test_the_cli_build_prints_its_numbers(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    from snowlight.listed.build import BuildResult  # noqa: PLC0415
    from snowlight.listed.measure import Tally  # noqa: PLC0415

    national = Tally()
    national.add({"seen": True, "roster": False, "listed": True}, 2.0)
    national.add({"seen": False, "roster": True, "listed": True}, None)
    result = BuildResult(
        paths={"listed": tmp_path / "listed.json"},
        national=national,
        states={},
        unmatched_names=3,
        unmatched_rows=7,
        listed={},
    )
    seen: dict[str, object] = {}

    def fake_build(*_args: object, **kwargs: object) -> BuildResult:
        seen.update(kwargs)
        return result

    monkeypatch.setattr("snowlight.listed.cli.build", fake_build)
    assert main(["listed", "build", "--workers", "2", "--no-rosters"]) == 0
    printed = capsys.readouterr().out
    assert "seen: 1 (50.0%; closure-weighted 100.0%)" in printed
    assert "roster: 1 (50.0%; closure-weighted 0.0%)" in printed
    assert "unmatched K-12-looking names: 3 (7 rows)" in printed
    assert seen["workers"] == 2
    assert seen["require_rosters"] is False


def test_the_cli_reads_the_rosters_again_on_refresh(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    from snowlight.sources.stations.registry import Registry  # noqa: PLC0415

    monkeypatch.setattr("snowlight.listed.cli.load_registry", lambda _folder: Registry({}))
    monkeypatch.setattr("snowlight.listed.cli.rosters.fetch_rosters", lambda *_args, **_kwargs: [])
    out = tmp_path / "rosters.json"
    code = main(
        ["listed", "rosters", "--refresh", "--out", str(out), "--http-store", str(tmp_path / "h")]
    )
    assert code == 0
    assert json.loads(out.read_text())["reads"] == []
    assert "rosters: 0 reads" in capsys.readouterr().out
