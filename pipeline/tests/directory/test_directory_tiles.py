"""Tests for the tileset step, including the tippecanoe string-pool workaround."""

import json
import re
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from snowlight.directory import pmtiles, tiles

if TYPE_CHECKING:
    from directory.conftest import SyntheticTiles

SETTINGS = tiles.TileSettings(layer="schools", minzoom=9, maxzoom=14)
# Real schools as they go into the tileset (CCD 2024-25 names and ids, EDGE
# 2024-25 geocodes). The last two are the pair whose strings tippecanoe 2.49
# confuses: their 64-bit FNV-1a hashes share the low 32 bits.
ALBERTVILLE = tiles.TileFeature(
    0, "010000500870", "Albertville Middle School", 0, -86_206_200, 34_260_200
)
ST_JAMES = tiles.TileFeature(1, "00000033", "ST JAMES CATHOLIC SCHOOL", 1, -85_989_151, 34_023_810)
ROOSEVELT = tiles.TileFeature(
    65071, "390437800500", "Franklin D. Roosevelt", 0, -81_610_400, 41_535_200
)
GANADO = tiles.TileFeature(82206, "482031012317", "GANADO JH", 0, -96_515_817, 29_037_454)


def test_geojsonseq_lines(tmp_path: Path) -> None:
    path = tmp_path / "s.geojsonseq"
    assert tiles.write_geojsonseq([ALBERTVILLE, ST_JAMES], path) == 2
    first, second = (json.loads(line) for line in path.read_text().splitlines())
    assert first == {
        "type": "Feature",
        "id": 0,
        "geometry": {"type": "Point", "coordinates": [-86.2062, 34.2602]},
        "properties": {"id": "010000500870", "name": "Albertville Middle School", "kind": 0},
    }
    assert second["geometry"]["coordinates"] == [-85.989151, 34.02381]


def test_pool_hash_reproduces_the_real_collision() -> None:
    a = tiles.pool_hash("GANADO JH", 0)
    b = tiles.pool_hash("Franklin D. Roosevelt", 0)
    assert a != b
    assert a & 0xFFFFFFFF == b & 0xFFFFFFFF
    assert tiles.colliding_features([ALBERTVILLE, ROOSEVELT, ST_JAMES, GANADO]) == [(1, 3)]


def test_input_separates_colliding_pairs(tmp_path: Path) -> None:
    features = [GANADO, ROOSEVELT, ALBERTVILLE, ST_JAMES]
    path = tmp_path / "in.geojsonseq"
    assert tiles.write_tile_input(features, path) == 4
    data = path.read_bytes()
    order = [json.loads(line)["id"] for line in data.splitlines()]
    assert order == [82206, 0, 1, 65071]
    segments = tiles.tippecanoe_segments(data, tiles.READ_THREADS)
    assert segments[0] != segments[-1]


def test_tippecanoe_segments_follow_newlines() -> None:
    data = b"aaaa\nbb\nc\n"
    # Length 10: the cut at 5 moves forward to the newline at 7.
    assert tiles.tippecanoe_segments(data, 2) == [0, 0, 1]
    assert tiles.tippecanoe_segments(data, 1) == [0, 0, 0]


def _fake_hash(collide: set[str]) -> Any:
    """A stand-in hash under which the strings in ``collide`` share their low 32 bits."""

    def fake(text: str, value_type: int) -> int:
        if text in collide:
            return 42 + (len(text) + 1) * (1 << 32)
        return hash((text, value_type)) & ((1 << 64) - 1)

    return fake


def test_unseparable_collisions_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    features = [ALBERTVILLE, ST_JAMES, GANADO]
    monkeypatch.setattr(tiles, "pool_hash", _fake_hash({"name", "GANADO JH"}))
    with pytest.raises(tiles.TilesError, match="property key"):
        tiles.colliding_features(features)
    monkeypatch.setattr(tiles, "pool_hash", _fake_hash({"GANADO JH", "482031012317"}))
    with pytest.raises(tiles.TilesError, match="one feature"):
        tiles.colliding_features(features)
    trio = {"Albertville Middle School", "ST JAMES CATHOLIC SCHOOL", "GANADO JH"}
    monkeypatch.setattr(tiles, "pool_hash", _fake_hash(trio))
    with pytest.raises(tiles.TilesError, match="cannot be split"):
        tiles.write_tile_input(features, Path("unused"))


def test_input_refused_when_threads_would_mix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tiles, "tippecanoe_segments", lambda data, _t: [0] * data.count(b"\n"))
    with pytest.raises(tiles.TilesError, match="share a tippecanoe reading thread"):
        tiles.write_tile_input([ROOSEVELT, GANADO], tmp_path / "in.geojsonseq")


def test_command_keeps_every_point(tmp_path: Path) -> None:
    argv = tiles.tippecanoe_command("tippecanoe", tmp_path / "in", tmp_path / "out", SETTINGS)
    assert argv[argv.index("--minimum-zoom") + 1] == "9"
    assert argv[argv.index("--maximum-zoom") + 1] == "14"
    assert argv[argv.index("--drop-rate") + 1] == "1"
    assert "--no-feature-limit" in argv
    assert "--no-tile-size-limit" in argv
    assert "--read-parallel" in argv


def test_missing_tippecanoe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(tiles.TilesError, match="not installed"):
        tiles.run_tippecanoe(tmp_path / "in", tmp_path / "out", SETTINGS)


def test_failing_tippecanoe_gets_two_threads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen.update(kwargs, argv=argv)
        return subprocess.CompletedProcess(argv, 1, "", "boom")

    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/tippecanoe")
    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(tiles.TilesError, match="boom"):
        tiles.run_tippecanoe(tmp_path / "in", tmp_path / "out.pmtiles", SETTINGS)
    assert seen["env"]["TIPPECANOE_MAX_THREADS"] == "2"
    assert seen["cwd"] == tmp_path
    assert seen["executable"] == "/usr/bin/tippecanoe"
    assert seen["argv"][seen["argv"].index("--output") + 1] == "out.pmtiles"
    with pytest.raises(tiles.TilesError, match="boom"):
        tiles.run_tippecanoe(tmp_path / "in", Path("/elsewhere/out.pmtiles"), SETTINGS)
    assert seen["argv"][seen["argv"].index("--output") + 1] == "/elsewhere/out.pmtiles"


def test_layer_feature_count_variants() -> None:
    def info(metadata: Mapping[str, object]) -> pmtiles.Info:
        header = pmtiles.Header(0, 0, 0, 0, 0, 0, 0, 2, 2, 1, 9, 14)
        return pmtiles.Info(header=header, metadata=dict(metadata))

    as_text = {"tilestats": json.dumps({"layers": [{"layer": "s", "count": 3}]})}
    assert tiles.layer_feature_count(info(as_text), "s") == 3
    assert tiles.layer_feature_count(info(as_text), "t") is None
    assert tiles.layer_feature_count(info({}), "s") is None
    assert tiles.layer_feature_count(info({"tilestats": {"layers": [{"layer": "s"}]}}), "s") is None


def _synthetic(
    synthetic_tiles: type["SyntheticTiles"],
    features: list[tiles.TileFeature],
    **changes: Mapping[str, object],
) -> bytes:
    """Tile ``features`` synthetically, applying per-feature property ``changes``."""
    lines = []
    for feature in features:
        record = json.loads(tiles._record(feature))
        record["properties"].update(changes.get(str(feature.index), {}))
        lines.append(json.dumps(record))
    return synthetic_tiles.from_geojsonseq("\n".join(lines), "schools", 9, 14)


def test_verify_accepts_a_faithful_tileset(synthetic_tiles: type["SyntheticTiles"]) -> None:
    features = [ALBERTVILLE, ST_JAMES, ROOSEVELT, GANADO]
    check = tiles.verify_tileset(_synthetic(synthetic_tiles, features), features, SETTINGS)
    assert check.schools_per_zoom == dict.fromkeys(range(9, 15), 4)
    assert check.feature_instances == 24


def test_verify_catches_a_swapped_name(synthetic_tiles: type["SyntheticTiles"]) -> None:
    features = [ROOSEVELT, GANADO]
    data = _synthetic(synthetic_tiles, features, **{"65071": {"name": "GANADO JH"}})
    with pytest.raises(tiles.TilesError, match="reads"):
        tiles.verify_tileset(data, features, SETTINGS)


def test_verify_catches_missing_and_unknown_features(
    synthetic_tiles: type["SyntheticTiles"],
) -> None:
    data = _synthetic(synthetic_tiles, [ALBERTVILLE])
    with pytest.raises(tiles.TilesError, match="holds 1 of 2"):
        tiles.verify_tileset(data, [ALBERTVILLE, ST_JAMES], SETTINGS)
    with pytest.raises(tiles.TilesError, match="never written"):
        tiles.verify_tileset(data, [ST_JAMES], SETTINGS)


def test_verify_catches_a_misplaced_point(synthetic_tiles: type["SyntheticTiles"]) -> None:
    moved = tiles.TileFeature(
        0, "010000500870", "Albertville Middle School", 0, -86_206_000, 34_260_200
    )
    data = _synthetic(synthetic_tiles, [moved])
    with pytest.raises(tiles.TilesError, match="misplaced"):
        tiles.verify_tileset(data, [ALBERTVILLE], SETTINGS)


def test_verify_catches_wrong_layer_and_zoom(synthetic_tiles: type["SyntheticTiles"]) -> None:
    tile = synthetic_tiles.tile("other", [(0, {"id": "x"}, 1, 1)])
    data = synthetic_tiles.archive(
        {synthetic_tiles.tile_id(9, 0, 0): tile}, metadata={}, minzoom=9, maxzoom=9
    )
    with pytest.raises(tiles.TilesError, match="unexpected layer"):
        tiles.verify_tileset(data, [ALBERTVILLE], SETTINGS)
    data = synthetic_tiles.archive(
        {synthetic_tiles.tile_id(3, 0, 0): tile}, metadata={}, minzoom=3, maxzoom=3
    )
    with pytest.raises(tiles.TilesError, match="outside z9-14"):
        tiles.verify_tileset(data, [ALBERTVILLE], SETTINGS)


def _tippecanoe_version() -> tuple[int, ...] | None:
    path = shutil.which("tippecanoe")
    if path is None:
        return None
    result = subprocess.run(  # noqa: S603 - fixed argv
        [path, "--version"], capture_output=True, text=True, check=False
    )
    match = re.search(r"v(\d+)\.(\d+)\.(\d+)", result.stdout + result.stderr)
    return tuple(int(part) for part in match.groups()) if match else None


@pytest.mark.skipif(_tippecanoe_version() is None, reason="tippecanoe is not installed")
def test_real_tippecanoe_with_the_workaround(tmp_path: Path) -> None:
    features = [ALBERTVILLE, ROOSEVELT, ST_JAMES, GANADO]
    source = tmp_path / "s.geojsonseq"
    tiles.write_tile_input(features, source)
    target = tmp_path / "s.pmtiles"
    argv = tiles.run_tippecanoe(source, target, SETTINGS)
    assert argv[0] == "tippecanoe"
    assert argv[argv.index("--output") + 1] == "s.pmtiles"
    data = target.read_bytes()
    info = pmtiles.read_info(data)
    assert (info.min_zoom, info.max_zoom) == (9, 14)
    assert tiles.layer_feature_count(info, "schools") == 4
    check = tiles.verify_tileset(data, features, SETTINGS)
    assert check.schools_per_zoom == dict.fromkeys(range(9, 15), 4)


@pytest.mark.skipif(_tippecanoe_version() is None, reason="tippecanoe is not installed")
def test_real_tippecanoe_without_the_workaround_is_caught(tmp_path: Path) -> None:
    """Both colliding strings in one reading thread: 2.49 swaps a name; the check sees it."""
    features = [ROOSEVELT, GANADO]
    source = tmp_path / "s.geojsonseq"
    tiles.write_geojsonseq(features, source)
    target = tmp_path / "s.pmtiles"
    tippecanoe = shutil.which("tippecanoe")
    assert tippecanoe is not None
    argv = tiles.tippecanoe_command(tippecanoe, source, target, SETTINGS)
    argv.remove("--read-parallel")
    subprocess.run(argv, check=True, capture_output=True)  # noqa: S603 - fixed argv
    version = _tippecanoe_version()
    assert version is not None
    if version <= (2, 49, 0):
        with pytest.raises(tiles.TilesError, match="reads"):
            tiles.verify_tileset(target.read_bytes(), features, SETTINGS)
    else:
        tiles.verify_tileset(target.read_bytes(), features, SETTINGS)
