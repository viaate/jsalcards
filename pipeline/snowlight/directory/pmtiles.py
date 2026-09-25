"""Read a PMTiles v3 archive of Mapbox Vector Tiles, independently of tippecanoe.

Used to check every tileset the build writes: the header and metadata, and
every feature of every tile. Only what the checks need is implemented: gzip or
uncompressed directories and tiles, leaf directories, and MVT decoding of
layers, keys, values, feature ids, tags and point geometry.

References: the PMTiles v3 specification (github.com/protomaps/PMTiles, spec/v3)
and the Mapbox Vector Tile specification 2.1.
"""

import gzip
import json
import struct
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

MAGIC = b"PMTiles"
HEADER = struct.Struct("<7sBQQQQQQQQQQQBBBBBBiiiiBii")  # 127 bytes
_SPEC_VERSION = 3
_NO_COMPRESSION = 1
_GZIP = 2
_MVT = 1

type Value = str | float | int | bool


class PMTilesError(ValueError):
    """Bytes that are not a PMTiles v3 archive of vector tiles this reader handles."""


@dataclass(frozen=True, slots=True)
class Header:
    """The PMTiles v3 header fields the checks use."""

    root_offset: int
    root_length: int
    metadata_offset: int
    metadata_length: int
    leaf_offset: int
    tile_data_offset: int
    addressed_tiles: int
    internal_compression: int
    tile_compression: int
    tile_type: int
    min_zoom: int
    max_zoom: int


@dataclass(frozen=True, slots=True)
class Info:
    """Header and parsed JSON metadata."""

    header: Header
    metadata: dict[str, Any]

    @property
    def min_zoom(self) -> int:
        """Lowest zoom level in the archive."""
        return self.header.min_zoom

    @property
    def max_zoom(self) -> int:
        """Highest zoom level in the archive."""
        return self.header.max_zoom


@dataclass(slots=True)
class Feature:
    """One decoded vector tile feature."""

    id: int | None
    geom_type: int
    properties: dict[str, Value]
    points: list[tuple[int, int]] = field(default_factory=list)


@dataclass(slots=True)
class Layer:
    """One decoded vector tile layer."""

    name: str
    extent: int
    features: list[Feature]


def _decompress(data: bytes, compression: int) -> bytes:
    if compression == _GZIP:
        return gzip.decompress(data)
    if compression == _NO_COMPRESSION:
        return data
    raise PMTilesError(f"unsupported compression {compression}")


def read_header(data: bytes) -> Header:
    """Parse the fixed 127-byte header.

    Raises:
        PMTilesError: for a bad magic number or a version other than 3.
    """
    if len(data) < HEADER.size or not data.startswith(MAGIC):
        raise PMTilesError("not a PMTiles archive")
    f = HEADER.unpack_from(data)
    if f[1] != _SPEC_VERSION:
        raise PMTilesError(f"PMTiles version {f[1]}, expected 3")
    return Header(
        root_offset=f[2],
        root_length=f[3],
        metadata_offset=f[4],
        metadata_length=f[5],
        leaf_offset=f[6],
        tile_data_offset=f[8],
        addressed_tiles=f[10],
        internal_compression=f[14],
        tile_compression=f[15],
        tile_type=f[16],
        min_zoom=f[17],
        max_zoom=f[18],
    )


def read_info(data: bytes) -> Info:
    """Parse the header and the JSON metadata."""
    header = read_header(data)
    start, length = header.metadata_offset, header.metadata_length
    raw = _decompress(data[start : start + length], header.internal_compression)
    metadata = json.loads(raw.decode("utf-8")) if raw else {}
    if not isinstance(metadata, dict):
        raise PMTilesError("metadata is not a JSON object")
    return Info(header=header, metadata=metadata)


def _varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


@dataclass(frozen=True, slots=True)
class Entry:
    """A directory entry: a run of tiles, or (run_length 0) a leaf directory."""

    tile_id: int
    offset: int
    length: int
    run_length: int


def decode_directory(raw: bytes) -> list[Entry]:
    """Decode an uncompressed PMTiles v3 directory."""
    count, pos = _varint(raw, 0)
    ids: list[int] = []
    last = 0
    for _ in range(count):
        delta, pos = _varint(raw, pos)
        last += delta
        ids.append(last)
    runs: list[int] = []
    lengths: list[int] = []
    offsets: list[int] = []
    for _ in range(count):
        value, pos = _varint(raw, pos)
        runs.append(value)
    for _ in range(count):
        value, pos = _varint(raw, pos)
        lengths.append(value)
    for i in range(count):
        value, pos = _varint(raw, pos)
        if value == 0 and i > 0:
            offsets.append(offsets[i - 1] + lengths[i - 1])
        else:
            offsets.append(value - 1)
    return [Entry(ids[i], offsets[i], lengths[i], runs[i]) for i in range(count)]


def iter_tiles(data: bytes) -> Iterator[tuple[int, bytes]]:
    """Yield ``(tile_id, decompressed tile bytes)`` for every addressed tile."""
    header = read_header(data)

    def walk(offset: int, length: int) -> Iterator[tuple[int, bytes]]:
        raw = _decompress(data[offset : offset + length], header.internal_compression)
        for entry in decode_directory(raw):
            if entry.run_length == 0:
                yield from walk(header.leaf_offset + entry.offset, entry.length)
                continue
            start = header.tile_data_offset + entry.offset
            tile = _decompress(data[start : start + entry.length], header.tile_compression)
            for step in range(entry.run_length):
                yield entry.tile_id + step, tile

    yield from walk(header.root_offset, header.root_length)


def tile_id_to_zxy(tile_id: int) -> tuple[int, int, int]:
    """Invert the PMTiles Hilbert tile id into ``(z, x, y)``."""
    first = 0
    for z in range(32):
        count = 1 << (2 * z)
        if tile_id < first + count:
            position = tile_id - first
            x = y = 0
            size = 1
            t = position
            while size < (1 << z):
                rx = 1 & (t // 2)
                ry = 1 & (t ^ rx)
                if ry == 0:
                    if rx == 1:
                        x, y = size - 1 - x, size - 1 - y
                    x, y = y, x
                x += size * rx
                y += size * ry
                t //= 4
                size *= 2
            return z, x, y
        first += count
    raise PMTilesError(f"tile id {tile_id} is out of range")


def _fields(buf: bytes) -> Iterator[tuple[int, int, int | bytes]]:
    """Yield ``(field number, wire type, value)`` for a protobuf message."""
    pos = 0
    while pos < len(buf):
        key, pos = _varint(buf, pos)
        number, wire = key >> 3, key & 0x7
        if wire == 0:
            value, pos = _varint(buf, pos)
            yield number, wire, value
        elif wire == 2:  # noqa: PLR2004 - length-delimited
            length, pos = _varint(buf, pos)
            yield number, wire, buf[pos : pos + length]
            pos += length
        elif wire == 5:  # noqa: PLR2004 - 32-bit
            yield number, wire, buf[pos : pos + 4]
            pos += 4
        elif wire == 1:
            yield number, wire, buf[pos : pos + 8]
            pos += 8
        else:
            raise PMTilesError(f"unsupported protobuf wire type {wire}")


def _packed(buf: bytes) -> list[int]:
    values, pos = [], 0
    while pos < len(buf):
        value, pos = _varint(buf, pos)
        values.append(value)
    return values


def _zigzag(value: int) -> int:
    return (value >> 1) ^ -(value & 1)


def _value(buf: bytes) -> Value:
    for number, _wire, raw in _fields(buf):
        if isinstance(raw, bytes):
            if number == 1:
                return raw.decode("utf-8")
            if number == 2:  # noqa: PLR2004 - float
                return float(struct.unpack("<f", raw)[0])
            return float(struct.unpack("<d", raw)[0])
        if number == 6:  # noqa: PLR2004 - sint64
            return _zigzag(raw)
        if number == 7:  # noqa: PLR2004 - bool
            return bool(raw)
        return raw  # int64 or uint64
    raise PMTilesError("empty vector tile value")


def _points(commands: list[int]) -> list[tuple[int, int]]:
    points: list[tuple[int, int]] = []
    x = y = pos = 0
    while pos < len(commands):
        command, count = commands[pos] & 0x7, commands[pos] >> 3
        pos += 1
        if command != 1:
            raise PMTilesError(f"point geometry has command {command}")
        for _ in range(count):
            x += _zigzag(commands[pos])
            y += _zigzag(commands[pos + 1])
            pos += 2
            points.append((x, y))
    return points


def _feature(blob: bytes, keys: list[str], values: list[Value]) -> Feature:
    feature = Feature(id=None, geom_type=0, properties={})
    for number, _wire, item in _fields(blob):
        if number == 1 and isinstance(item, int):
            feature.id = item
        elif number == 2 and isinstance(item, bytes):  # noqa: PLR2004 - tags
            tags = _packed(item)
            for k in range(0, len(tags), 2):
                feature.properties[keys[tags[k]]] = values[tags[k + 1]]
        elif number == 3 and isinstance(item, int):  # noqa: PLR2004 - geometry type
            feature.geom_type = item
        elif number == 4 and isinstance(item, bytes):  # noqa: PLR2004 - geometry
            feature.points = _points(_packed(item))
    return feature


def _layer(raw: bytes) -> Layer:
    name, extent = "", 4096
    keys: list[str] = []
    values: list[Value] = []
    encoded: list[bytes] = []
    for number, _wire, item in _fields(raw):
        if isinstance(item, int):
            if number == 5:  # noqa: PLR2004 - extent
                extent = item
        elif number == 1:
            name = item.decode("utf-8")
        elif number == 2:  # noqa: PLR2004 - features
            encoded.append(item)
        elif number == 3:  # noqa: PLR2004 - keys
            keys.append(item.decode("utf-8"))
        elif number == 4:  # noqa: PLR2004 - values
            values.append(_value(item))
    return Layer(name, extent, [_feature(blob, keys, values) for blob in encoded])


def decode_tile(tile: bytes) -> list[Layer]:
    """Decode a Mapbox Vector Tile (point features only)."""
    return [
        _layer(raw)
        for number, _wire, raw in _fields(tile)
        if number == 3 and isinstance(raw, bytes)  # noqa: PLR2004 - Tile.layers
    ]
