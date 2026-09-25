"""Tests for the zipped-shapefile reader, on real record slices and on synthetic rings."""

import json
import struct
import zipfile
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Point, Polygon

from snowlight.sources.nws.shapefile import (
    ShapefileError,
    assemble_rings,
    polygonal,
    read_dbf,
    read_shp,
    read_zip,
)

FIXTURES = Path(__file__).parent / "fixtures"
PROVENANCE = json.loads((FIXTURES / "provenance.json").read_text())
ZONES_18MR25 = len(PROVENANCE["z_18mr25.zip"]["records_kept"])


def _members(name: str) -> dict[str, bytes]:
    with zipfile.ZipFile(FIXTURES / name) as archive:
        return {member: archive.read(member) for member in archive.namelist()}


def _zip(tmp_path: Path, members: dict[str, bytes], name: str = "test.zip") -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as archive:
        for member, data in members.items():
            archive.writestr(member, data)
    return path


def _suffix(members: dict[str, bytes], suffix: str) -> str:
    return next(name for name in members if name.endswith(suffix))


def test_reads_real_zone_records() -> None:
    provenance = json.loads((FIXTURES / "provenance.json").read_text())
    kept = provenance["z_16ap26.zip"]["records_kept"]
    records = read_zip(FIXTURES / "z_16ap26.zip")
    assert len(records) == len(kept)
    ugcs = [f"{r.attributes['STATE']}Z{r.attributes['ZONE']}" for r in records]
    assert ugcs == [kept[index] for index in sorted(kept, key=int)]
    first = records[0].attributes
    assert isinstance(first["LAT"], float)
    assert isinstance(first["NAME"], str)
    for record in records:
        assert record.geometry is not None
        assert record.geometry.is_valid
        lon, lat = record.geometry.representative_point().coords[0]
        assert -125 < lon < -66
        assert 24 < lat < 50


def test_reads_real_archive_rows_with_their_encoding() -> None:
    records = read_zip(FIXTURES / "iem-2024-05-21.zip")
    assert {r.attributes["WFO"] for r in records} == {"DMX", "ARX"}
    assert {r.attributes["GTYPE"] for r in records} == {"P", "C"}
    assert all(isinstance(r.attributes["ETN"], float) for r in records)
    assert all(isinstance(r.geometry, Polygon | MultiPolygon) for r in records)


def test_dbf_rejects_deleted_records_and_bad_headers() -> None:
    members = _members("c_18mr25.zip")
    dbf = bytearray(members[_suffix(members, ".dbf")])
    header_len = struct.unpack_from("<H", dbf, 8)[0]
    fields, rows = read_dbf(bytes(dbf))
    assert [field.name for field in fields][:4] == ["STATE", "CWA", "COUNTYNAME", "FIPS"]
    kentucky = next(row for row in rows if row["FIPS"] == "21013")
    assert (kentucky["STATE"], kentucky["COUNTYNAME"]) == ("KY", "Bell")
    deleted = bytearray(dbf)
    deleted[header_len] = 0x2A
    with pytest.raises(ShapefileError, match="marked deleted"):
        read_dbf(bytes(deleted))
    with pytest.raises(ShapefileError, match="shorter than its header"):
        read_dbf(bytes(dbf[:20]))
    too_many = bytearray(dbf)
    struct.pack_into("<I", too_many, 4, 10_000)
    with pytest.raises(ShapefileError, match="too short"):
        read_dbf(bytes(too_many))
    widths = bytearray(dbf)
    struct.pack_into("<H", widths, 10, 7)
    with pytest.raises(ShapefileError, match="do not add up"):
        read_dbf(bytes(widths))


def _dbf(field_type: bytes, value: bytes) -> bytes:
    """A one-field, one-record dBASE table (synthetic, for value decoding)."""
    header = bytearray(32)
    header[0] = 3
    struct.pack_into("<IHH", header, 4, 1, 32 + 32 + 1, 1 + len(value))
    descriptor = bytearray(32)
    descriptor[:5] = b"VALUE"
    descriptor[11:12] = field_type
    descriptor[16] = len(value)
    return bytes(header) + bytes(descriptor) + b"\x0d" + b" " + value


def test_dbf_value_decoding() -> None:
    assert read_dbf(_dbf(b"N", b"  12.50"))[1] == [{"VALUE": 12.5}]
    assert read_dbf(_dbf(b"N", b"       "))[1] == [{"VALUE": None}]
    assert read_dbf(_dbf(b"F", b"*******"))[1] == [{"VALUE": None}]
    assert read_dbf(_dbf(b"D", b"20260924"))[1] == [{"VALUE": "20260924"}]
    assert read_dbf(_dbf(b"C", b"ab\x00\x00"))[1] == [{"VALUE": "ab"}]
    with pytest.raises(ShapefileError, match="not a number"):
        read_dbf(_dbf(b"N", b"12a"))
    with pytest.raises(ShapefileError, match="unsupported type"):
        read_dbf(_dbf(b"M", b"0000000001"))


def test_shp_rejects_malformed_files() -> None:
    members = _members("z_18mr25.zip")
    shp = members[_suffix(members, ".shp")]
    assert len(read_shp(shp)) == ZONES_18MR25
    with pytest.raises(ShapefileError, match="shorter than its header"):
        read_shp(shp[:50])
    wrong_code = bytearray(shp)
    struct.pack_into(">i", wrong_code, 0, 1234)
    with pytest.raises(ShapefileError, match="not a shapefile"):
        read_shp(bytes(wrong_code))
    with pytest.raises(ShapefileError, match="declares"):
        read_shp(shp[:-8])
    points = bytearray(shp)
    struct.pack_into("<i", points, 32, 1)
    with pytest.raises(ShapefileError, match="not a polygon type"):
        read_shp(bytes(points))
    record_type = bytearray(shp)
    struct.pack_into("<i", record_type, 108, 3)
    with pytest.raises(ShapefileError, match="record shape type 3"):
        read_shp(bytes(record_type))
    parts = bytearray(shp)
    struct.pack_into("<i", parts, 108 + 44, 5)
    with pytest.raises(ShapefileError, match="out of order"):
        read_shp(bytes(parts))
    empty = bytearray(shp)
    struct.pack_into("<ii", empty, 108 + 36, 0, 0)
    with pytest.raises(ShapefileError, match="truncated or empty"):
        read_shp(bytes(empty))


def _shp(records: list[bytes]) -> bytes:
    """A polygon .shp around the given record contents (synthetic)."""
    body = b"".join(
        struct.pack(">ii", i + 1, len(content) // 2) + content for i, content in enumerate(records)
    )
    header = bytearray(100)
    struct.pack_into(">i", header, 0, 9994)
    struct.pack_into(">i", header, 24, (100 + len(body)) // 2)
    struct.pack_into("<ii", header, 28, 1000, 5)
    return bytes(header) + body


def test_shp_null_shapes_and_truncated_records() -> None:
    assert read_shp(_shp([struct.pack("<i", 0)])) == [None]
    data = bytearray(_shp([struct.pack("<i", 0)]))
    data += struct.pack(">i", 2)
    struct.pack_into(">i", data, 24, len(data) // 2)
    with pytest.raises(ShapefileError, match="record header is truncated"):
        read_shp(bytes(data))
    short = bytearray(_shp([struct.pack("<i", 0)]))
    struct.pack_into(">i", short, 104, 40)
    with pytest.raises(ShapefileError, match="content is truncated"):
        read_shp(bytes(short))


def _ring(*points: tuple[float, float]) -> np.ndarray:
    return np.array(points, dtype=np.float64)


# Synthetic rings: shapefile exteriors run clockwise, holes counter-clockwise.
SQUARE_CW = _ring((0, 0), (0, 10), (10, 10), (10, 0), (0, 0))
HOLE_CCW = _ring((2, 2), (4, 2), (4, 4), (2, 4), (2, 2))
ISLAND_CW = _ring((2.5, 2.5), (2.5, 3.5), (3.5, 3.5), (3.5, 2.5), (2.5, 2.5))
FAR_CCW = _ring((20, 20), (22, 20), (22, 22), (20, 22), (20, 20))


def test_rings_follow_the_shapefile_winding_rule() -> None:
    geometry = assemble_rings([SQUARE_CW, HOLE_CCW])
    assert isinstance(geometry, Polygon)
    assert geometry.area == pytest.approx(96)
    assert not geometry.contains(Point(3, 3))
    with_island = assemble_rings([SQUARE_CW, HOLE_CCW, ISLAND_CW])
    assert isinstance(with_island, MultiPolygon)
    assert with_island.area == pytest.approx(97)
    assert with_island.contains(Point(3, 3))


def test_orphan_holes_are_kept_as_exteriors() -> None:
    geometry = assemble_rings([SQUARE_CW, FAR_CCW])
    assert isinstance(geometry, MultiPolygon)
    assert geometry.area == pytest.approx(104)
    only_ccw = assemble_rings([FAR_CCW])
    assert isinstance(only_ccw, Polygon)
    assert only_ccw.area == pytest.approx(4)


def test_degenerate_unclosed_and_invalid_rings() -> None:
    assert assemble_rings([_ring((0, 0), (1, 1), (0, 0))]) is None
    assert assemble_rings([_ring((0, 0), (1, 1), (2, 2), (0, 0))]) is None
    unclosed = assemble_rings([SQUARE_CW[:-1]])
    assert unclosed is not None
    assert unclosed.area == pytest.approx(100)
    bowtie = assemble_rings([_ring((0, 0), (10, 10), (10, 0), (0, 10), (0, 0))])
    assert bowtie is not None
    assert bowtie.is_valid
    assert bowtie.area == pytest.approx(50)


def test_polygonal_keeps_only_polygons() -> None:
    square = Polygon([(0, 0), (1, 0), (1, 1)])
    assert polygonal(None) is None
    assert polygonal(Polygon()) is None
    assert polygonal(LineString([(0, 0), (1, 1)])) is None
    mixed = GeometryCollection([square, LineString([(0, 0), (5, 5)])])
    assert polygonal(mixed) == square
    two = GeometryCollection([square, Polygon([(5, 5), (6, 5), (6, 6)])])
    assert isinstance(polygonal(two), MultiPolygon)


def test_read_zip_checks_members(tmp_path: Path) -> None:
    members = _members("z_18mr25.zip")
    shp = _suffix(members, ".shp")
    not_zip = tmp_path / "not.zip"
    not_zip.write_bytes(b"plain text")
    with pytest.raises(ShapefileError, match="not a zip"):
        read_zip(not_zip)
    with pytest.raises(ShapefileError, match=r"no \.shp/\.dbf pair"):
        read_zip(_zip(tmp_path, {shp: members[shp]}))
    doubled = {**members, "copy/" + shp: members[shp]}
    with pytest.raises(ShapefileError, match=r"more than one \.shp"):
        read_zip(_zip(tmp_path, doubled))
    mismatched = dict(members)
    mismatched[shp] = _shp([struct.pack("<i", 0)])
    with pytest.raises(ShapefileError, match=rf"1 shapes but {ZONES_18MR25} dbf records"):
        read_zip(_zip(tmp_path, mismatched))
    odd_cpg = {**members, Path(shp).stem + ".cpg": b"NOT-A-CODEC"}
    assert len(read_zip(_zip(tmp_path, odd_cpg))) == ZONES_18MR25
    utf8 = {**members, Path(shp).stem + ".cpg": b"UTF-8\n"}
    assert len(read_zip(_zip(tmp_path, utf8))) == ZONES_18MR25
