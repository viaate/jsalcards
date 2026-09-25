"""Shared fixtures for the directory tests.

The fixture zips under ``fixtures/`` are slices of the real NCES files (see
``fixtures/README.md``). Tests that fetch go through an ``httpx.MockTransport``
that serves those zips at the real NCES URLs, so no test touches the network.
"""

import gzip
import hashlib
import json
import math
import struct
from pathlib import Path

import httpx
import pytest

from snowlight.directory.config import DirectoryConfig, load_config

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PROVENANCE = json.loads((FIXTURES / "PROVENANCE.json").read_text(encoding="utf-8"))


def fixture_path(url: str) -> Path:
    """Return the fixture zip standing in for the file at ``url``."""
    return FIXTURES / url.rsplit("/", 1)[1]


@pytest.fixture(scope="session")
def fixture_config() -> DirectoryConfig:
    """The real directory.yaml with each pinned SHA-256 swapped for its fixture's."""
    config = load_config()
    sources = {}
    for key, source in config.sources.items():
        candidates = []
        for candidate in source.candidates:
            path = fixture_path(candidate.url)
            pin = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
            candidates.append(candidate.model_copy(update={"sha256": pin}))
        sources[key] = source.model_copy(update={"candidates": candidates})
    return config.model_copy(update={"sources": sources})


class FixtureServer:
    """An httpx transport handler that serves fixture zips at their real URLs."""

    def __init__(self) -> None:
        self.requests: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        path = fixture_path(url)
        if not path.exists():
            return httpx.Response(404, text="Not Found")
        data = path.read_bytes()
        return httpx.Response(
            200,
            content=data,
            headers={"Content-Length": str(len(data)), "Last-Modified": "synthetic"},
        )

    def client(self) -> httpx.Client:
        """Return a client whose requests this server answers."""
        return httpx.Client(transport=httpx.MockTransport(self))


@pytest.fixture
def server() -> FixtureServer:
    """A fresh fixture server that records the URLs requested."""
    return FixtureServer()


class SyntheticTiles:
    """Writes synthetic PMTiles v3 archives of point vector tiles, for tests only.

    Stands in for tippecanoe where it is not installed, and lets tests build
    tilesets with deliberate faults to prove the checks catch them.
    """

    @staticmethod
    def varint(value: int) -> bytes:
        out = bytearray()
        while True:
            byte = value & 0x7F
            value >>= 7
            if value:
                out.append(byte | 0x80)
            else:
                out.append(byte)
                return bytes(out)

    @classmethod
    def field(cls, number: int, payload: bytes | int) -> bytes:
        if isinstance(payload, int):
            return cls.varint(number << 3) + cls.varint(payload)
        return cls.varint(number << 3 | 2) + cls.varint(len(payload)) + payload

    @classmethod
    def packed(cls, values: list[int]) -> bytes:
        return b"".join(cls.varint(v) for v in values)

    @classmethod
    def value(cls, value: object) -> bytes:
        if isinstance(value, bool):
            return cls.field(7, int(value))
        if isinstance(value, str):
            return cls.field(1, value.encode("utf-8"))
        if isinstance(value, int):
            if value < 0:
                return cls.field(6, (value << 1) ^ (value >> 63))
            return cls.field(5, value)
        assert isinstance(value, float)
        return cls.varint(3 << 3 | 1) + struct.pack("<d", value)

    @classmethod
    def tile(
        cls, layer: str, features: list[tuple[int, dict[str, object], int, int]], extent: int = 4096
    ) -> bytes:
        """Encode one layer of point features ``(id, properties, x, y)``."""
        keys: list[str] = []
        values: list[bytes] = []
        blobs = b""
        for feature_id, properties, x, y in features:
            tags: list[int] = []
            for key, value in properties.items():
                if key not in keys:
                    keys.append(key)
                encoded = cls.value(value)
                if encoded not in values:
                    values.append(encoded)
                tags += [keys.index(key), values.index(encoded)]
            geometry = [9, (x << 1) ^ (x >> 63), (y << 1) ^ (y >> 63)]
            blob = (
                cls.field(1, feature_id)
                + cls.field(2, cls.packed(tags))
                + cls.field(3, 1)
                + cls.field(4, cls.packed(geometry))
            )
            blobs += cls.field(2, blob)
        body = (
            cls.field(15, 2)
            + cls.field(1, layer.encode())
            + blobs
            + b"".join(cls.field(3, k.encode()) for k in keys)
            + b"".join(cls.field(4, v) for v in values)
            + cls.field(5, extent)
        )
        return cls.field(3, body)

    @staticmethod
    def tile_id(z: int, x: int, y: int) -> int:
        """PMTiles Hilbert tile id of ``z/x/y``."""
        first = sum(1 << (2 * i) for i in range(z))
        n = 1 << z
        position = 0
        s = n // 2
        while s > 0:
            rx = 1 if (x & s) > 0 else 0
            ry = 1 if (y & s) > 0 else 0
            position += s * s * ((3 * rx) ^ ry)
            if ry == 0:
                if rx == 1:
                    x, y = n - 1 - x, n - 1 - y
                x, y = y, x
            s //= 2
        return first + position

    @classmethod
    def directory(cls, entries: list[tuple[int, int, int, int]]) -> bytes:
        """Encode ``(tile_id, offset, length, run_length)`` entries, gzipped."""
        out = cls.varint(len(entries))
        last = 0
        for tile_id, *_ in entries:
            out += cls.varint(tile_id - last)
            last = tile_id
        out += b"".join(cls.varint(e[3]) for e in entries)
        out += b"".join(cls.varint(e[2]) for e in entries)
        for i, (_t, offset, _length, _run) in enumerate(entries):
            contiguous = i > 0 and offset == entries[i - 1][1] + entries[i - 1][2]
            out += cls.varint(0 if contiguous else offset + 1)
        return gzip.compress(out, mtime=0)

    @classmethod
    def archive(  # noqa: PLR0913 - test helper with keyword-only options
        cls,
        tiles: dict[int, bytes],
        *,
        metadata: dict[str, object],
        minzoom: int,
        maxzoom: int,
        leaf_size: int = 0,
        version: int = 3,
    ) -> bytes:
        """Assemble a PMTiles v3 archive (gzip everywhere); ``leaf_size`` > 0 adds leaves."""
        data = b""
        entries: list[tuple[int, int, int, int]] = []
        for tile_id in sorted(tiles):
            blob = gzip.compress(tiles[tile_id], mtime=0)
            entries.append((tile_id, len(data), len(blob), 1))
            data += blob
        leaves = b""
        if leaf_size:
            root_entries = []
            for i in range(0, len(entries), leaf_size):
                chunk = cls.directory(entries[i : i + leaf_size])
                root_entries.append((entries[i][0], len(leaves), len(chunk), 0))
                leaves += chunk
            root = cls.directory(root_entries)
        else:
            root = cls.directory(entries)
        meta = gzip.compress(json.dumps(metadata).encode(), mtime=0)
        root_at = 127
        meta_at = root_at + len(root)
        leaves_at = meta_at + len(meta)
        data_at = leaves_at + len(leaves)
        header = struct.pack(
            "<7sBQQQQQQQQQQQBBBBBBiiiiBii",
            b"PMTiles",
            version,
            root_at,
            len(root),
            meta_at,
            len(meta),
            leaves_at,
            len(leaves),
            data_at,
            len(data),
            len(tiles),
            len(entries),
            len(entries),
            1,
            2,
            2,
            1,
            minzoom,
            maxzoom,
            0,
            0,
            0,
            0,
            minzoom,
            0,
            0,
        )
        return header + root + meta + leaves + data

    @classmethod
    def from_geojsonseq(  # noqa: PLR0913 - test helper with keyword-only options
        cls,
        text: str,
        layer: str,
        minzoom: int,
        maxzoom: int,
        *,
        count: int | None = None,
        extra: dict[str, object] | None = None,
    ) -> bytes:
        """Tile newline-delimited GeoJSON points the way tippecanoe would (no buffer)."""
        features = [json.loads(line) for line in text.splitlines()]
        tiles: dict[int, list[tuple[int, dict[str, object], int, int]]] = {}
        for z in range(minzoom, maxzoom + 1):
            scale = 4096 * (1 << z)
            for f in features:
                lon, lat = f["geometry"]["coordinates"]
                sin = math.sin(math.radians(lat))
                wx = (lon + 180.0) / 360.0 * scale
                wy = (0.5 - math.log((1 + sin) / (1 - sin)) / (4 * math.pi)) * scale
                x, y = int(wx // 4096), int(wy // 4096)
                local = (round(wx - x * 4096), round(wy - y * 4096))
                key = cls.tile_id(z, x, y)
                tiles.setdefault(key, []).append((f["id"], f["properties"], *local))
        stats_count = len(features) if count is None else count
        metadata = {
            "name": layer,
            "tilestats": {"layers": [{"layer": layer, "count": stats_count}]},
            **(extra or {}),
        }
        encoded = {key: cls.tile(layer, items) for key, items in tiles.items()}
        return cls.archive(encoded, metadata=metadata, minzoom=minzoom, maxzoom=maxzoom)


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """The directory holding the sliced NCES fixture zips."""
    return FIXTURES


@pytest.fixture(scope="session")
def provenance() -> dict[str, object]:
    """The parsed ``fixtures/PROVENANCE.json``."""
    return dict(PROVENANCE)


@pytest.fixture(scope="session")
def synthetic_tiles() -> type[SyntheticTiles]:
    """The synthetic PMTiles writer."""
    return SyntheticTiles
