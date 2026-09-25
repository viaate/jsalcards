"""``schools.pmtiles``: every school as a point feature in a vector tileset.

Built with tippecanoe from a newline-delimited GeoJSON file. Each feature has
the school's position in ``meta.json`` as its numeric feature id (so the map
can set feature state by the same index ``points.bin`` uses) and three
properties:

* ``id``: the NCES school id (string)
* ``name``: the school name (string)
* ``kind``: the kind flags from ``points.bin`` (integer)

One layer, ``schools``, at zooms 9..14. No feature is dropped or coalesced at
any zoom. The tileset metadata carries no source names or URLs.

A tippecanoe string-pool bug, and how the build avoids it
----------------------------------------------------------
tippecanoe 2.49 (and earlier) deduplicates attribute strings in a search tree
ordered by a 64-bit FNV-1a hash, but its comparator returns
``(int)(hash_a - hash_b)``: two different strings whose hashes share the low 32
bits compare equal, and the second silently takes the first one's value. With
the 2024-25 directory this turns "Franklin D. Roosevelt" into "GANADO JH" and
gives five more schools another school's id or name. (Later tippecanoe releases
compare the full 64 bits.) The pool is per input-reading thread, so the build:

1. computes tippecanoe's hash for every attribute string and finds the pairs
   that would collide (:func:`colliding_features`);
2. writes the input so that each such pair falls in different halves of the
   file, and runs tippecanoe with ``--read-parallel`` and exactly two reading
   threads (``TIPPECANOE_MAX_THREADS=2``), so the halves use separate pools;
3. decodes every tile of the result and checks every feature's id, name, kind
   and position against the input (:func:`verify_tileset`), so any tippecanoe
   version that still mixes values up fails the build instead of shipping.
"""

import json
import math
import os
import shutil
import subprocess
from collections import defaultdict, deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from snowlight.directory import pmtiles


class TilesError(RuntimeError):
    """tippecanoe failed or produced a tileset that does not check out."""


@dataclass(frozen=True, slots=True)
class TileFeature:
    """One school as it goes into the tileset."""

    index: int
    school_id: str
    name: str
    kind: int
    lon_e6: int
    lat_e6: int


@dataclass(frozen=True, slots=True)
class TileSettings:
    """Layer name and zoom range of the tileset."""

    layer: str
    minzoom: int
    maxzoom: int


PROPERTY_KEYS = ("id", "name", "kind")
READ_THREADS = 2
# tippecanoe's value types in its string pool (mvt_value_type).
_MVT_STRING = 0
_MVT_DOUBLE = 2
_LOW_32 = 0xFFFFFFFF
_U64 = (1 << 64) - 1
_FNV_OFFSET = 14695981039346656037
_FNV_PRIME = 1099511628211


def _degrees(value_e6: int) -> float:
    return round(value_e6 / 1_000_000, 6)


def pool_hash(text: str, value_type: int) -> int:
    """tippecanoe's ``fnv1a(s, type)``: 64-bit FNV-1a of the UTF-8 bytes, then the type."""
    value = _FNV_OFFSET
    for byte in text.encode("utf-8"):
        value = ((value ^ byte) * _FNV_PRIME) & _U64
    return ((value ^ value_type) * _FNV_PRIME) & _U64


def _pool_strings(feature: TileFeature) -> list[tuple[str, int]]:
    return [
        (feature.school_id, _MVT_STRING),
        (feature.name, _MVT_STRING),
        (str(feature.kind), _MVT_DOUBLE),
    ]


def colliding_features(features: Sequence[TileFeature]) -> list[tuple[int, int]]:
    """Return pairs of positions in ``features`` whose strings tippecanoe 2.49 confuses.

    Raises:
        TilesError: if a property key collides with a value, or one feature's own
            strings collide, since no input order can separate those.
    """
    buckets: dict[int, set[tuple[str, int]]] = defaultdict(set)
    holders: dict[tuple[str, int], list[int]] = defaultdict(list)
    for key in PROPERTY_KEYS:
        buckets[pool_hash(key, _MVT_STRING) & _LOW_32].add((key, _MVT_STRING))
    for position, feature in enumerate(features):
        for item in _pool_strings(feature):
            buckets[pool_hash(*item) & _LOW_32].add(item)
            holders[item].append(position)
    pairs: set[tuple[int, int]] = set()
    for group in buckets.values():
        if len(group) < 2:  # noqa: PLR2004
            continue
        if any(item[0] in PROPERTY_KEYS and item[1] == _MVT_STRING for item in group):
            raise TilesError(f"a property key collides in tippecanoe's string pool: {group}")
        members = sorted(group)
        for i, first in enumerate(members):
            for second in members[i + 1 :]:
                for a in holders[first]:
                    for b in holders[second]:
                        if a == b:
                            raise TilesError(f"one feature holds colliding strings: {group}")
                        pairs.add((min(a, b), max(a, b)))
    return sorted(pairs)


def _two_colouring(pairs: Sequence[tuple[int, int]]) -> dict[int, int]:
    neighbours: dict[int, list[int]] = defaultdict(list)
    for a, b in pairs:
        neighbours[a].append(b)
        neighbours[b].append(a)
    colour: dict[int, int] = {}
    for start in sorted(neighbours):
        if start in colour:
            continue
        colour[start] = 0
        queue = deque([start])
        while queue:
            node = queue.popleft()
            for other in neighbours[node]:
                if other not in colour:
                    colour[other] = 1 - colour[node]
                    queue.append(other)
                elif colour[other] == colour[node]:
                    raise TilesError("colliding strings cannot be split across two pools")
    return colour


def tippecanoe_segments(data: bytes, threads: int) -> list[int]:
    """Return, per line of ``data``, the reading thread tippecanoe's -P assigns it.

    Mirrors ``do_read_parallel``: thread ``i`` starts at ``len * i / threads``,
    moved forward to the next newline.
    """
    starts = [0]
    for i in range(1, threads):
        cut = len(data) * i // threads
        while cut < len(data) and data[cut : cut + 1] != b"\n":
            cut += 1
        starts.append(cut)
    segments: list[int] = []
    offset = 0
    for line in data.splitlines(keepends=True):
        segments.append(max(i for i, start in enumerate(starts) if start <= offset))
        offset += len(line)
    return segments


def _record(feature: TileFeature) -> str:
    record = {
        "type": "Feature",
        "id": feature.index,
        "geometry": {
            "type": "Point",
            "coordinates": [_degrees(feature.lon_e6), _degrees(feature.lat_e6)],
        },
        "properties": {"id": feature.school_id, "name": feature.name, "kind": feature.kind},
    }
    return json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"


def write_geojsonseq(features: Iterable[TileFeature], path: Path) -> int:
    """Write ``features``, in the given order, as newline-delimited GeoJSON."""
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for feature in features:
            handle.write(_record(feature))
            count += 1
    return count


def write_tile_input(features: Sequence[TileFeature], path: Path) -> int:
    """Write the tippecanoe input so no colliding strings share a reading thread.

    Features in a colliding pair go first (one side) or last (the other side);
    the rest keep their order in between. Returns the number of features.

    Raises:
        TilesError: if the collisions cannot be separated.
    """
    pairs = colliding_features(features)
    colour = _two_colouring(pairs)
    head = [features[i] for i in sorted(colour) if colour[i] == 0]
    tail = [features[i] for i in sorted(colour) if colour[i] == 1]
    middle = [feature for i, feature in enumerate(features) if i not in colour]
    ordered = head + middle + tail
    data = "".join(_record(feature) for feature in ordered).encode("utf-8")
    segments = tippecanoe_segments(data, READ_THREADS)
    line_of = {feature.index: line for line, feature in enumerate(ordered)}
    for a, b in pairs:
        if segments[line_of[features[a].index]] == segments[line_of[features[b].index]]:
            raise TilesError("colliding strings would share a tippecanoe reading thread")
    path.write_bytes(data)
    return len(ordered)


def tippecanoe_command(
    tippecanoe: str, source: Path, target: Path, settings: TileSettings
) -> list[str]:
    """Return the tippecanoe argv that tiles ``source`` into ``target``."""
    return [
        tippecanoe,
        "--output",
        str(target),
        "--force",
        "--quiet",
        "--layer",
        settings.layer,
        "--name",
        settings.layer,
        "--description",
        settings.layer,
        "--minimum-zoom",
        str(settings.minzoom),
        "--maximum-zoom",
        str(settings.maxzoom),
        # Keep every point at every zoom: no rate-based dropping, no per-tile
        # feature or size limits that would thin dense cities.
        "--drop-rate",
        "1",
        "--no-feature-limit",
        "--no-tile-size-limit",
        # Two reading threads, each with its own string pool (see module doc).
        "--read-parallel",
        str(source),
    ]


def run_tippecanoe(source: Path, target: Path, settings: TileSettings) -> list[str]:
    """Run tippecanoe; return the argv it ran with.

    Raises:
        TilesError: if tippecanoe is not installed or exits with an error.
    """
    tippecanoe = shutil.which("tippecanoe")
    if tippecanoe is None:
        raise TilesError("tippecanoe is not installed (it builds schools.pmtiles)")
    # Run beside the input with relative names, so the command line tippecanoe
    # records in the tileset metadata is the same on every machine.
    work = source.parent
    output = target.relative_to(work) if target.is_relative_to(work) else target
    argv = tippecanoe_command("tippecanoe", Path(source.name), output, settings)
    env = {**os.environ, "TIPPECANOE_MAX_THREADS": str(READ_THREADS)}
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        argv,
        executable=tippecanoe,
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise TilesError(f"tippecanoe exited {result.returncode}: {result.stderr.strip()}")
    return argv


def layer_feature_count(info: pmtiles.Info, layer: str) -> int | None:
    """Return the feature count tippecanoe recorded for ``layer`` in its tilestats."""
    stats = info.metadata.get("tilestats")
    if isinstance(stats, str):
        stats = json.loads(stats)
    if not isinstance(stats, dict):
        return None
    for entry in stats.get("layers", []):
        if isinstance(entry, dict) and entry.get("layer") == layer:
            count = entry.get("count")
            return count if isinstance(count, int) else None
    return None


def tile_position(feature: TileFeature, z: int, x: int, y: int, extent: int) -> tuple[float, float]:
    """Where ``feature`` falls in tile ``z/x/y``, in tile units (Web Mercator)."""
    lon, lat = feature.lon_e6 / 1_000_000, feature.lat_e6 / 1_000_000
    scale = extent * (1 << z)
    world_x = (lon + 180.0) / 360.0 * scale
    sin = math.sin(math.radians(lat))
    world_y = (0.5 - math.log((1 + sin) / (1 - sin)) / (4 * math.pi)) * scale
    return world_x - x * extent, world_y - y * extent


@dataclass(frozen=True, slots=True)
class TilesetCheck:
    """What :func:`verify_tileset` found."""

    tiles: int
    feature_instances: int
    schools_per_zoom: dict[int, int]


def verify_tileset(
    data: bytes,
    features: Sequence[TileFeature],
    settings: TileSettings,
    *,
    tolerance: float = 2.0,
) -> TilesetCheck:
    """Decode every tile and check it against the input features.

    Every feature must carry exactly the id, name and kind it was given, lie
    within ``tolerance`` tile units of its true position, and every school must
    appear at every zoom from ``minzoom`` to ``maxzoom``.

    Raises:
        TilesError: on the first discrepancy.
    """
    by_index = {feature.index: feature for feature in features}
    zooms = range(settings.minzoom, settings.maxzoom + 1)
    seen: dict[int, set[int]] = {z: set() for z in zooms}
    tiles = instances = 0
    for tile_id, tile in pmtiles.iter_tiles(data):
        z, x, y = pmtiles.tile_id_to_zxy(tile_id)
        if z not in seen:
            raise TilesError(f"tile {z}/{x}/{y} is outside z{settings.minzoom}-{settings.maxzoom}")
        tiles += 1
        for layer in pmtiles.decode_tile(tile):
            if layer.name != settings.layer:
                raise TilesError(f"unexpected layer {layer.name!r} in {z}/{x}/{y}")
            for decoded in layer.features:
                instances += 1
                source = by_index.get(decoded.id) if decoded.id is not None else None
                if source is None:
                    raise TilesError(f"feature id {decoded.id} in {z}/{x}/{y} was never written")
                expected = {"id": source.school_id, "name": source.name, "kind": source.kind}
                if decoded.properties != expected:
                    raise TilesError(
                        f"feature {decoded.id} in {z}/{x}/{y} reads {decoded.properties}, "
                        f"expected {expected}"
                    )
                want = tile_position(source, z, x, y, layer.extent)
                if len(decoded.points) != 1 or any(
                    abs(got - wanted) > tolerance
                    for got, wanted in zip(decoded.points[0], want, strict=True)
                ):
                    raise TilesError(f"feature {decoded.id} is misplaced in {z}/{x}/{y}")
                seen[z].add(source.index)
    for z, indexes in seen.items():
        if len(indexes) != len(by_index):
            raise TilesError(f"zoom {z} holds {len(indexes)} of {len(by_index)} schools")
    return TilesetCheck(
        tiles=tiles,
        feature_instances=instances,
        schools_per_zoom={z: len(v) for z, v in seen.items()},
    )
