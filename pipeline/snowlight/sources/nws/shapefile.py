"""Read the zipped polygon shapefiles that the NWS and the Iowa Environmental Mesonet publish.

Only what those files use is supported, and anything else is refused rather than
guessed at:

* ``.shp`` shape types 0 (null), 5 (Polygon), 15 (PolygonZ) and 25 (PolygonM);
  Z and M values are ignored.
* ``.dbf`` (dBASE III) fields of type C, D and L (read as text) and N and F (read
  as floats; blank means ``None``). The text encoding comes from the ``.cpg``
  member when there is one, otherwise ISO-8859-1, which decodes any byte.

Polygon rings follow the shapefile rule: clockwise rings are exteriors and
counter-clockwise rings are holes, each hole belonging to the smallest exterior
that covers it. A hole that no exterior covers is kept as an exterior (the file
wound it the wrong way), so no area in the file is lost. Geometries that are not
valid are repaired with :func:`shapely.make_valid`, keeping polygonal parts only.
"""

import codecs
import itertools
import struct
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
import shapely
from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry

type Polygonal = Polygon | MultiPolygon
type Value = str | float | None

_FILE_CODE = 9994
_SHP_HEADER = 100
_DBF_HEADER = 32
_DBF_DESCRIPTOR = 32
_DBF_TERMINATOR = 0x0D
_DBF_DELETED = 0x2A
_SHAPE_TYPE_BYTES = 4
_MIN_RING = 4  # a closed ring needs three distinct vertices plus the closing one
_POLYGON_TYPES = frozenset({5, 15, 25})
_DEFAULT_ENCODING = "latin-1"


class ShapefileError(ValueError):
    """A shapefile is malformed or uses a feature this reader does not support."""


@dataclass(frozen=True, slots=True)
class DbfField:
    """One attribute column of a ``.dbf`` table."""

    name: str
    kind: str
    length: int
    decimals: int


@dataclass(frozen=True, slots=True)
class ShapeRecord:
    """One feature: its position in the file, its attributes and its polygon(s)."""

    index: int
    attributes: dict[str, Value]
    geometry: Polygonal | None


def polygonal(geometry: BaseGeometry | None) -> Polygonal | None:
    """Return the polygonal part of ``geometry`` (``None`` when it has none)."""
    if geometry is None or geometry.is_empty:
        return None
    if isinstance(geometry, Polygon | MultiPolygon):
        return geometry
    parts = [part for part in shapely.get_parts(geometry) if isinstance(part, Polygon)]
    parts = [part for part in parts if not part.is_empty]
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else MultiPolygon(parts)


def read_dbf(
    data: bytes, encoding: str = _DEFAULT_ENCODING
) -> tuple[list[DbfField], list[dict[str, Value]]]:
    """Parse a dBASE III table into its fields and one attribute dict per record.

    Raises:
        ShapefileError: the header is inconsistent or a record is marked deleted.
    """
    if len(data) < _DBF_HEADER:
        raise ShapefileError("dbf file is shorter than its header")
    count, header_len, record_len = struct.unpack_from("<IHH", data, 4)
    fields: list[DbfField] = []
    offset = _DBF_HEADER
    while offset < header_len and data[offset] != _DBF_TERMINATOR:
        raw = data[offset : offset + _DBF_DESCRIPTOR]
        if len(raw) < _DBF_DESCRIPTOR:
            raise ShapefileError("dbf field descriptors run past the header")
        name = raw[:11].split(b"\x00", 1)[0].decode("ascii").strip()
        fields.append(DbfField(name, chr(raw[11]), raw[16], raw[17]))
        offset += _DBF_DESCRIPTOR
    if sum(field.length for field in fields) + 1 != record_len:
        raise ShapefileError("dbf field widths do not add up to the record length")
    if header_len + count * record_len > len(data):
        raise ShapefileError(f"dbf declares {count} records but the file is too short")
    rows: list[dict[str, Value]] = []
    for index in range(count):
        start = header_len + index * record_len
        record = data[start : start + record_len]
        if record[0] == _DBF_DELETED:
            raise ShapefileError(f"dbf record {index} is marked deleted")
        row: dict[str, Value] = {}
        position = 1
        for field in fields:
            raw_value = record[position : position + field.length]
            position += field.length
            row[field.name] = _value(field, raw_value, encoding)
        rows.append(row)
    return fields, rows


def _value(field: DbfField, raw: bytes, encoding: str) -> Value:
    text = raw.decode(encoding).replace("\x00", " ").strip()
    if field.kind in {"N", "F"}:
        if not text or set(text) == {"*"}:
            return None
        try:
            return float(text)
        except ValueError as error:
            raise ShapefileError(f"dbf field {field.name}: {text!r} is not a number") from error
    if field.kind in {"C", "D", "L"}:
        return text
    raise ShapefileError(f"dbf field {field.name} has unsupported type {field.kind!r}")


def read_shp(data: bytes) -> list[Polygonal | None]:
    """Parse the records of a polygon ``.shp`` file, in file order.

    Raises:
        ShapefileError: the file is not a polygon shapefile or is truncated.
    """
    if len(data) < _SHP_HEADER:
        raise ShapefileError("shp file is shorter than its header")
    (code,) = struct.unpack_from(">i", data, 0)
    if code != _FILE_CODE:
        raise ShapefileError(f"not a shapefile (file code {code})")
    (declared_words,) = struct.unpack_from(">i", data, 24)
    if declared_words * 2 != len(data):
        raise ShapefileError(f"shp declares {declared_words * 2} bytes but has {len(data)}")
    (file_type,) = struct.unpack_from("<i", data, 32)
    if file_type not in _POLYGON_TYPES:
        raise ShapefileError(f"shape type {file_type} is not a polygon type")
    shapes: list[Polygonal | None] = []
    offset = _SHP_HEADER
    while offset < len(data):
        if offset + 8 > len(data):
            raise ShapefileError("shp record header is truncated")
        _number, words = struct.unpack_from(">ii", data, offset)
        content = data[offset + 8 : offset + 8 + 2 * words]
        if len(content) != 2 * words or len(content) < _SHAPE_TYPE_BYTES:
            raise ShapefileError("shp record content is truncated")
        offset += 8 + 2 * words
        shapes.append(_record_geometry(content))
    return shapes


def _record_geometry(content: bytes) -> Polygonal | None:
    (shape_type,) = struct.unpack_from("<i", content, 0)
    if shape_type == 0:
        return None
    if shape_type not in _POLYGON_TYPES:
        raise ShapefileError(f"record shape type {shape_type} is not a polygon type")
    num_parts, num_points = struct.unpack_from("<ii", content, 36)
    points_at = 44 + 4 * num_parts
    if num_parts < 1 or num_points < 1 or points_at + 16 * num_points > len(content):
        raise ShapefileError("shp polygon record is truncated or empty")
    parts = np.frombuffer(content, dtype="<i4", count=num_parts, offset=44)
    points = np.frombuffer(content, dtype="<f8", count=2 * num_points, offset=points_at)
    xy = points.reshape(-1, 2).astype(np.float64)
    bounds = [*parts.tolist(), num_points]
    if bounds[0] != 0 or any(b < a for a, b in itertools.pairwise(bounds)):
        raise ShapefileError("shp polygon part offsets are out of order")
    rings = [xy[a:b] for a, b in itertools.pairwise(bounds)]
    return assemble_rings(rings)


def _signed_area(ring: npt.NDArray[np.float64]) -> float:
    x, y = ring[:, 0], ring[:, 1]
    return float(np.dot(x[:-1], y[1:]) - np.dot(x[1:], y[:-1])) / 2.0


def assemble_rings(rings: Sequence[npt.NDArray[np.float64]]) -> Polygonal | None:
    """Build a polygon from shapefile rings (clockwise exteriors, counter-clockwise holes)."""
    exteriors: list[npt.NDArray[np.float64]] = []
    holes: list[npt.NDArray[np.float64]] = []
    for raw in rings:
        ring = raw if np.array_equal(raw[0], raw[-1]) else np.vstack([raw, raw[:1]])
        if len(ring) < _MIN_RING:
            continue
        # Zero net area means a self-crossing or collinear ring; make_valid sorts it out.
        if _signed_area(ring) > 0:
            holes.append(ring)
        else:
            exteriors.append(ring)
    shells = [Polygon(ring) for ring in exteriors]
    owned: list[list[npt.NDArray[np.float64]]] = [[] for _ in shells]
    for hole in holes:
        vertex = Point(hole[0])
        owners = [i for i, shell in enumerate(shells) if shell.covers(vertex)]
        if owners:
            owned[min(owners, key=lambda i: shells[i].area)].append(hole)
        else:
            shells.append(Polygon(hole))
            owned.append([])
    polygons = [
        Polygon(shell.exterior.coords, [h.tolist() for h in own]) if own else shell
        for shell, own in zip(shells, owned, strict=True)
    ]
    if not polygons:
        return None
    geometry: BaseGeometry = polygons[0] if len(polygons) == 1 else MultiPolygon(polygons)
    if not geometry.is_valid:
        geometry = shapely.make_valid(geometry)
    return polygonal(geometry)


def _member(names: Sequence[str], suffix: str, stem: str | None) -> str | None:
    matches = [
        name
        for name in names
        if name.lower().endswith(suffix) and (stem is None or Path(name).stem == stem)
    ]
    if len(matches) > 1:
        raise ShapefileError(f"more than one {suffix} member: {matches}")
    return matches[0] if matches else None


def read_zip(path: Path, *, stem: str | None = None) -> list[ShapeRecord]:
    """Read the shapefile in the zip at ``path`` (the one named ``stem`` if given).

    Raises:
        ShapefileError: a member is missing or malformed, or the ``.shp`` and
            ``.dbf`` disagree on the number of records.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            shp_name = _member(names, ".shp", stem)
            dbf_name = _member(names, ".dbf", stem)
            if shp_name is None or dbf_name is None:
                raise ShapefileError(f"{path.name} has no .shp/.dbf pair")
            cpg_name = _member(names, ".cpg", Path(shp_name).stem)
            encoding = _DEFAULT_ENCODING
            if cpg_name is not None:
                encoding = _encoding(archive.read(cpg_name))
            _fields, rows = read_dbf(archive.read(dbf_name), encoding)
            shapes = read_shp(archive.read(shp_name))
    except zipfile.BadZipFile as error:
        raise ShapefileError(f"{path.name} is not a zip archive") from error
    if len(rows) != len(shapes):
        raise ShapefileError(f"{path.name}: {len(shapes)} shapes but {len(rows)} dbf records")
    return [
        ShapeRecord(index, row, shape)
        for index, (row, shape) in enumerate(zip(rows, shapes, strict=True))
    ]


def _encoding(raw: bytes) -> str:
    name = raw.decode("ascii", errors="replace").strip()
    try:
        return codecs.lookup(name).name
    except LookupError:
        return _DEFAULT_ENCODING
