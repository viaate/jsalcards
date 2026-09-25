"""End-to-end tests: the whole build on the sliced real files, served offline."""

import hashlib
import json
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl
import pytest
import yaml  # type: ignore[import-untyped, unused-ignore]

from snowlight.cli import main
from snowlight.directory import build as build_module
from snowlight.directory import pmtiles, points, tiles
from snowlight.directory.build import (
    FORBIDDEN_IN_PUBLISHED,
    BuildError,
    BuildPaths,
    BuildResult,
    build,
    check_published,
)
from snowlight.directory.config import DirectoryConfig
from snowlight.sources.nces.fetch import SourceChangedError

if TYPE_CHECKING:
    from directory.conftest import FixtureServer, SyntheticTiles

PRIVATE_2425 = "https://nces.ed.gov/programs/edge/data/EDGE_GEOCODE_PRIVATESCH_2425.zip"
KEPT_PUBLIC = sorted(
    [
        "010000500870",
        "010000500871",
        "010019702432",
        "010000602705",
        "040386003535",
        "010000600986",
        "590002500172",
        "180020202661",
        "280237000462",
        "120008410898",
        "050040801686",
        "010020902504",
        "110003000207",
    ]
)
KEPT_PRIVATE = sorted(["00000033", "00000044", "00073137", "00083393"])


@pytest.fixture(autouse=True)
def tippecanoe_or_stand_in(
    monkeypatch: pytest.MonkeyPatch, synthetic_tiles: type["SyntheticTiles"]
) -> None:
    """Use tippecanoe when installed; otherwise tile the input synthetically."""
    if shutil.which("tippecanoe") is not None:
        return

    def synthetic(source: Path, target: Path, settings: tiles.TileSettings) -> list[str]:
        text = source.read_text(encoding="utf-8")
        target.write_bytes(
            synthetic_tiles.from_geojsonseq(
                text, settings.layer, settings.minzoom, settings.maxzoom
            )
        )
        return ["synthetic-tippecanoe"]

    monkeypatch.setattr(tiles, "run_tippecanoe", synthetic)


def _paths(tmp_path: Path) -> BuildPaths:
    return BuildPaths(
        cache_dir=tmp_path / "cache",
        out_dir=tmp_path / "site-data",
        internal_dir=tmp_path / "internal",
        work_dir=tmp_path / "work",
    )


def _run(config: DirectoryConfig, tmp_path: Path, server: "FixtureServer") -> BuildResult:
    return build(
        config,
        _paths(tmp_path),
        client_factory=server.client,
        log=lambda _message: None,
        now=lambda: datetime(2026, 9, 24, 23, 0, tzinfo=UTC),
    )


@pytest.fixture
def built(fixture_config: DirectoryConfig, tmp_path: Path, server: "FixtureServer") -> BuildResult:
    return _run(fixture_config, tmp_path, server)


def test_meta_lists_kept_schools_in_order(built: BuildResult) -> None:
    meta = json.loads((built.site_dir / "meta.json").read_bytes())
    assert meta["schema_version"] == 1
    assert meta["generated_on"] == "2026-09-24"
    assert meta["ids"] == KEPT_PUBLIC + KEPT_PRIVATE
    assert meta["count"] == len(meta["ids"]) == len(meta["names"]) == 17
    assert meta["names"][0] == "Albertville Middle School"
    assert meta["districts"]["ids"] == sorted(meta["districts"]["ids"])
    assert "Albertville City" in meta["districts"]["names"]
    assert meta["school_years"] == {"public": "2024-2025", "private": "2023-2024"}


def test_points_match_the_internal_table(built: BuildResult) -> None:
    meta = json.loads((built.site_dir / "meta.json").read_bytes())
    decoded = points.decode((built.site_dir / "points.bin").read_bytes())
    table = pl.read_parquet(built.internal_dir / "schools.parquet")
    assert len(decoded) == table.height == meta["count"]
    assert decoded.district_count == len(meta["districts"]["ids"])
    assert table["index"].to_list() == list(range(table.height))
    assert table["id"].to_list() == meta["ids"]
    assert decoded.lon_e6.tolist() == table["lon_e6"].to_list()
    assert decoded.lat_e6.tolist() == table["lat_e6"].to_list()
    assert decoded.kind.tolist() == table["kind_flags"].to_list()
    for row, district in zip(table.iter_rows(named=True), decoded.district.tolist(), strict=True):
        if row["kind"] == "private":
            assert district == points.NO_DISTRICT
        else:
            assert meta["districts"]["ids"][district] == row["district_id"]


def test_manifest_records_every_source(built: BuildResult, fixture_config: DirectoryConfig) -> None:
    manifest = json.loads((built.site_dir / "manifest.internal.json").read_bytes())
    entries = {entry["key"]: entry for entry in manifest["sources"]}
    assert set(entries) == set(fixture_config.sources)
    for key, entry in entries.items():
        candidate = next(c for c in fixture_config.sources[key].candidates if c.sha256)
        assert entry["url"] == candidate.url
        assert entry["sha256"] == entry["pinned_sha256"] == candidate.sha256
        assert entry["retrieved_at"].endswith("Z")
        assert entry["bytes"] > 0
        assert entry["rows_read"] > 0
    skipped = entries["private_school_geocodes"]["newer_releases_checked"]
    assert [s["url"] for s in skipped] == [PRIVATE_2425]
    assert "404" in skipped[0]["result"]
    for name, info in manifest["outputs"].items():
        data = (built.site_dir / name).read_bytes()
        assert info["sha256"] == hashlib.sha256(data).hexdigest()
        assert info["bytes"] == len(data)
        assert info["gzip_bytes"] > 0


def test_report_reconciles_by_state(built: BuildResult) -> None:
    report = json.loads((built.internal_dir / "build_report.json").read_bytes())
    public, private, districts = report["public"], report["private"], report["districts"]
    assert (public["source_rows"], public["kept"]) == (25, 13)
    assert (private["source_rows"], private["kept"]) == (8, 4)
    assert districts["source_rows"] == 24
    assert districts["on_map"] == districts["kept"] == 11
    for section in (public, private, districts):
        assert section["kept"] + sum(section["dropped"].values()) == section["source_rows"]
        states = section["by_state"].values()
        assert sum(s["source_rows"] for s in states) == section["source_rows"]
    assert public["dropped"]["outside_continental_us"] == 3
    assert public["dropped"]["no_coordinates"] == 0  # counted even when nothing is dropped
    assert set(private["dropped"]) == {
        "no_coordinates",
        "outside_continental_us",
        "coordinates_outside_continental_bounds",
        "grades_prek_only",
        "grades_ungraded_only",
        "grades_not_reported",
    }
    assert report["tileset_check"]["schools_per_zoom"] == dict.fromkeys(
        [str(z) for z in range(9, 15)], 17
    )
    assert manifest_report_path(built).endswith("build_report.json")
    assert public["by_state"]["ND"] == {"source_rows": 1, "kept": 1, "dropped": {}}
    assert public["geocode_rows_without_directory_record"] == 0
    assert private["geocode_rows_without_pss_record"] == 0
    assert report["schools_on_map"]["exclusively_virtual"] == 1
    # Every kept private fixture row has float-noise coordinates; none moves.
    assert report["schools_on_map"]["coordinates_published_with_more_than_6_decimals"] == 4
    assert report["schools_on_map"]["coordinates_moved_by_rounding_to_6_decimals"] == 0
    markdown = (built.internal_dir / "build_report.md").read_text()
    assert "| public | `status_closed` | 1 |" in markdown
    dropped = pl.read_parquet(built.internal_dir / "dropped.parquet")
    assert dropped.height == 16
    assert dropped["drop_reason"].null_count() == 0


def manifest_report_path(built: BuildResult) -> str:
    manifest = json.loads((built.site_dir / "manifest.internal.json").read_bytes())
    path = manifest["report"]
    assert isinstance(path, str)
    return path


def test_published_files_name_no_source(built: BuildResult) -> None:
    for name in ("points.bin", "meta.json", "schools.pmtiles"):
        data = (built.site_dir / name).read_bytes().lower()
        for term in FORBIDDEN_IN_PUBLISHED:
            assert term.encode() not in data, (name, term)
        check_published(name, data)
    info = pmtiles.read_info((built.site_dir / "schools.pmtiles").read_bytes())
    assert tiles.layer_feature_count(info, "schools") == 17


def test_check_published_refuses_urls() -> None:
    with pytest.raises(BuildError, match="must not name sources"):
        check_published("meta.json", b'{"x": "See https://nces.ed.gov"}')


def test_second_build_reads_the_cache(
    fixture_config: DirectoryConfig, tmp_path: Path, server: "FixtureServer"
) -> None:
    _run(fixture_config, tmp_path, server)
    assert len(server.requests) == 8
    server.requests.clear()
    _run(fixture_config, tmp_path, server)
    # Only the not-yet-published newer private release is checked again.
    assert server.requests == [PRIVATE_2425]


def test_changed_upstream_file_stops_the_build(
    fixture_config: DirectoryConfig, tmp_path: Path, server: "FixtureServer"
) -> None:
    source = fixture_config.sources["pss"]
    wrong = source.model_copy(
        update={"candidates": [source.candidates[0].model_copy(update={"sha256": "0" * 64})]}
    )
    config = fixture_config.model_copy(update={"sources": {**fixture_config.sources, "pss": wrong}})
    with pytest.raises(SourceChangedError):
        _run(config, tmp_path, server)


def test_school_year_mismatch_stops_the_build(
    fixture_config: DirectoryConfig, tmp_path: Path, server: "FixtureServer"
) -> None:
    source = fixture_config.sources["pss"]
    moved = source.model_copy(
        update={
            "candidates": [source.candidates[0].model_copy(update={"school_year": "2024-2025"})]
        }
    )
    config = fixture_config.model_copy(update={"sources": {**fixture_config.sources, "pss": moved}})
    with pytest.raises(BuildError, match="PSS"):
        _run(config, tmp_path, server)


def test_file_year_must_match_config(
    fixture_config: DirectoryConfig, tmp_path: Path, server: "FixtureServer"
) -> None:
    source = fixture_config.sources["ccd_directory"]
    moved = source.model_copy(
        update={
            "candidates": [source.candidates[0].model_copy(update={"school_year": "2023-2024"})]
        }
    )
    config = fixture_config.model_copy(
        update={"sources": {**fixture_config.sources, "ccd_directory": moved}}
    )
    with pytest.raises(BuildError, match="SCHOOL_YEAR"):
        _run(config, tmp_path, server)


def test_no_release_at_all_stops_the_build(
    fixture_config: DirectoryConfig, tmp_path: Path, server: "FixtureServer"
) -> None:
    source = fixture_config.sources["private_school_geocodes"]
    only_missing = source.model_copy(update={"candidates": source.candidates[:1]})
    config = fixture_config.model_copy(
        update={"sources": {**fixture_config.sources, "private_school_geocodes": only_missing}}
    )
    with pytest.raises(BuildError, match="no release"):
        _run(config, tmp_path, server)


def test_tileset_checks(
    built: BuildResult,
    fixture_config: DirectoryConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    synthetic_tiles: type["SyntheticTiles"],
) -> None:
    schools = pl.read_parquet(built.internal_dir / "schools.parquet")

    def stand_in(
        *,
        minzoom: int | None = None,
        count: int | None = None,
        extra: dict[str, object] | None = None,
        rename: tuple[str, str] | None = None,
    ) -> Callable[..., list[str]]:
        def run(source: Path, target: Path, settings: tiles.TileSettings) -> list[str]:
            text = source.read_text(encoding="utf-8")
            if rename is not None:
                text = text.replace(*rename, 1)
            data = bytearray(
                synthetic_tiles.from_geojsonseq(
                    text,
                    settings.layer,
                    settings.minzoom,
                    settings.maxzoom,
                    count=count,
                    extra=extra,
                )
            )
            if minzoom is not None:
                data[100] = minzoom
            target.write_bytes(bytes(data))
            return ["synthetic"]

        return run

    work = tmp_path / "tiles-work"
    work.mkdir()
    target = tmp_path / "out.pmtiles"
    for runner, message in (
        (stand_in(minzoom=8), "spans"),
        (stand_in(count=1), "features"),
        (stand_in(extra={"description": "https://example.org"}), "must not name sources"),
        (
            stand_in(rename=("Albertville Middle School", "Albertville High School")),
            "does not match its input",
        ),
    ):
        monkeypatch.setattr(tiles, "run_tippecanoe", runner)
        with pytest.raises(BuildError, match=message):
            build_module._write_tiles(schools, fixture_config, work, target)
    assert not target.exists()


def test_duplicate_ids_are_refused() -> None:
    frame = pl.DataFrame(
        {"id": ["a", "a"], "kind": ["public", "private"], "district_id": [None, None]}
    )
    districts = pl.DataFrame(
        {"district_id": [], "index": []}, schema={"district_id": pl.String, "index": pl.UInt32}
    )
    with pytest.raises(BuildError, match="share an id"):
        build_module.order_schools(frame, districts)


def _write_config(config: DirectoryConfig, path: Path) -> Path:
    path.write_text(yaml.safe_dump(config.model_dump(mode="json")), encoding="utf-8")
    return path


def _cli_args(config_path: Path, tmp_path: Path) -> list[str]:
    paths = _paths(tmp_path)
    return [
        "directory",
        "build",
        "--config",
        str(config_path),
        "--cache-dir",
        str(paths.cache_dir),
        "--out-dir",
        str(paths.out_dir),
        "--internal-dir",
        str(paths.internal_dir),
        "--work-dir",
        str(paths.work_dir),
    ]


def test_cli_build(
    fixture_config: DirectoryConfig,
    tmp_path: Path,
    server: "FixtureServer",
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(build_module, "make_client", server.client)
    config_path = _write_config(fixture_config, tmp_path / "directory.yaml")
    assert main(_cli_args(config_path, tmp_path)) == 0
    out = capsys.readouterr()
    assert "public schools: 13 kept of 25" in out.out
    assert "private schools: 4 kept of 8" in out.out
    assert "points.bin:" in out.out
    assert "Fetching NCES files" in out.err


def test_cli_reports_failures(
    fixture_config: DirectoryConfig,
    tmp_path: Path,
    server: "FixtureServer",
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(build_module, "make_client", server.client)
    raw = fixture_config.model_dump(mode="json")
    raw["sources"]["pss"]["candidates"][0]["sha256"] = "0" * 64
    config_path = tmp_path / "bad.yaml"
    config_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    assert main(_cli_args(config_path, tmp_path)) == 1
    assert "changed upstream" in capsys.readouterr().err


def test_cli_requires_an_action(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["directory"])
    assert excinfo.value.code == 2
    assert "ACTION" in capsys.readouterr().err
