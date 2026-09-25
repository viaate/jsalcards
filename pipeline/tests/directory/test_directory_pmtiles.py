"""Tests for the independent PMTiles/MVT reader, on synthetic archives built in the tests."""

import gzip
import struct
from typing import TYPE_CHECKING

import pytest

from snowlight.directory import pmtiles

if TYPE_CHECKING:
    from directory.conftest import SyntheticTiles


def test_tile_ids_round_trip(synthetic_tiles: type["SyntheticTiles"]) -> None:
    expected_id = 0
    for z in range(6):
        ids = {}
        for x in range(1 << z):
            for y in range(1 << z):
                tile_id = synthetic_tiles.tile_id(z, x, y)
                ids[tile_id] = (z, x, y)
                assert pmtiles.tile_id_to_zxy(tile_id) == (z, x, y)
        assert sorted(ids) == list(range(expected_id, expected_id + (1 << (2 * z))))
        expected_id += 1 << (2 * z)
    # Values from the PMTiles specification's examples.
    assert pmtiles.tile_id_to_zxy(0) == (0, 0, 0)
    assert pmtiles.tile_id_to_zxy(1) == (1, 0, 0)
    assert pmtiles.tile_id_to_zxy(19078479) == (12, 3423, 1763)


def test_tile_id_out_of_range() -> None:
    with pytest.raises(pmtiles.PMTilesError, match="out of range"):
        pmtiles.tile_id_to_zxy(1 << 64)


def test_decodes_every_value_type(synthetic_tiles: type["SyntheticTiles"]) -> None:
    properties = {"s": "Ñandú", "u": 7, "neg": -3, "d": 1.5, "b": True}
    tile = synthetic_tiles.tile("layer", [(5, properties, 10, -2)], extent=512)
    float_value = synthetic_tiles.varint(2 << 3 | 5) + struct.pack("<f", 0.25)
    int_value = synthetic_tiles.field(4, 9)
    extra = synthetic_tiles.field(
        3,
        synthetic_tiles.field(1, b"more")
        + synthetic_tiles.field(3, b"f")
        + synthetic_tiles.field(3, b"i")
        + synthetic_tiles.field(4, float_value)
        + synthetic_tiles.field(4, int_value)
        + synthetic_tiles.field(
            2,
            synthetic_tiles.field(2, synthetic_tiles.packed([0, 0, 1, 1]))
            + synthetic_tiles.field(4, synthetic_tiles.packed([17, 2, 4, 6, 8])),
        ),
    )
    layers = pmtiles.decode_tile(tile + extra + synthetic_tiles.field(9, 1))
    assert [layer.name for layer in layers] == ["layer", "more"]
    first = layers[0]
    assert first.extent == 512
    (feature,) = first.features
    assert (feature.id, feature.geom_type, feature.points) == (5, 1, [(10, -2)])
    assert feature.properties == properties
    second = layers[1].features[0]
    assert second.id is None
    assert second.properties == {"f": 0.25, "i": 9}
    assert second.points == [(1, 2), (4, 6)]


def test_decode_errors(synthetic_tiles: type["SyntheticTiles"]) -> None:
    line = synthetic_tiles.field(4, synthetic_tiles.packed([10, 0, 0]))  # LineTo
    tile = synthetic_tiles.field(3, synthetic_tiles.field(2, line))
    with pytest.raises(pmtiles.PMTilesError, match="command 2"):
        pmtiles.decode_tile(tile)
    with pytest.raises(pmtiles.PMTilesError, match="wire type"):
        pmtiles.decode_tile(synthetic_tiles.varint(3 << 3 | 3))
    empty_value = synthetic_tiles.field(3, synthetic_tiles.field(4, b""))
    with pytest.raises(pmtiles.PMTilesError, match="empty"):
        pmtiles.decode_tile(empty_value)


def _tiles(synthetic_tiles: type["SyntheticTiles"], count: int) -> dict[int, bytes]:
    return {
        synthetic_tiles.tile_id(4, x, 3): synthetic_tiles.tile("s", [(x, {"n": x}, 1, 1)])
        for x in range(count)
    }


@pytest.mark.parametrize("leaf_size", [0, 2])
def test_reads_header_metadata_and_every_tile(
    synthetic_tiles: type["SyntheticTiles"], leaf_size: int
) -> None:
    tiles = _tiles(synthetic_tiles, 5)
    data = synthetic_tiles.archive(
        tiles, metadata={"name": "s"}, minzoom=4, maxzoom=4, leaf_size=leaf_size
    )
    info = pmtiles.read_info(data)
    assert (info.min_zoom, info.max_zoom) == (4, 4)
    assert info.header.addressed_tiles == 5
    assert info.metadata == {"name": "s"}
    read = dict(pmtiles.iter_tiles(data))
    assert read == tiles


def test_run_lengths_and_uncompressed_directories(synthetic_tiles: type["SyntheticTiles"]) -> None:
    tile = synthetic_tiles.tile("s", [(1, {}, 0, 0)])
    raw = synthetic_tiles.varint(2)  # two entries
    raw += synthetic_tiles.varint(0) + synthetic_tiles.varint(5)  # tile ids 0 and 5
    raw += synthetic_tiles.varint(3) + synthetic_tiles.varint(1)  # run lengths
    raw += synthetic_tiles.varint(len(tile)) * 2  # lengths
    raw += synthetic_tiles.varint(1) + synthetic_tiles.varint(0)  # offsets 0, then contiguous
    assert pmtiles.decode_directory(raw) == [
        pmtiles.Entry(0, 0, len(tile), 3),
        pmtiles.Entry(5, len(tile), len(tile), 1),
    ]
    header = bytearray(synthetic_tiles.archive({}, metadata={}, minzoom=0, maxzoom=0)[:127])
    root_at, data_at = 127, 127 + len(raw)
    struct.pack_into("<QQQQ", header, 8, root_at, len(raw), data_at, 0)
    struct.pack_into("<QQ", header, 56, data_at, 2 * len(tile))
    header[97] = header[98] = 1  # no compression
    archive = bytes(header) + raw + tile + tile
    assert [tile_id for tile_id, _ in pmtiles.iter_tiles(archive)] == [0, 1, 2, 5]
    assert pmtiles.read_info(archive).metadata == {}


def test_header_errors(synthetic_tiles: type["SyntheticTiles"]) -> None:
    with pytest.raises(pmtiles.PMTilesError, match="not a PMTiles"):
        pmtiles.read_header(b"SQLite format 3\x00" + bytes(200))
    old = synthetic_tiles.archive({}, metadata={}, minzoom=0, maxzoom=0, version=2)
    with pytest.raises(pmtiles.PMTilesError, match="version 2"):
        pmtiles.read_header(old)
    data = bytearray(synthetic_tiles.archive({}, metadata={}, minzoom=0, maxzoom=0))
    data[97] = 3  # brotli
    with pytest.raises(pmtiles.PMTilesError, match="compression 3"):
        pmtiles.read_info(bytes(data))
    listing = bytearray(synthetic_tiles.archive({}, metadata={}, minzoom=0, maxzoom=0))
    meta = gzip.compress(b"[1, 2]", mtime=0)
    struct.pack_into("<Q", listing, 32, len(meta))
    offset = struct.unpack_from("<Q", listing, 24)[0]
    listing[offset : offset + len(meta)] = meta
    with pytest.raises(pmtiles.PMTilesError, match="not a JSON object"):
        pmtiles.read_info(bytes(listing))
