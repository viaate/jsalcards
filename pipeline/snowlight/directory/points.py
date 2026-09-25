"""``points.bin``: every school on the map as a compact binary record.

Layout (all integers little-endian)::

    header, 16 bytes
      0  4 bytes  magic b"SLPT"
      4  uint16   format version (FORMAT_VERSION)
      6  uint16   record size in bytes (13)
      8  uint32   school count N
     12  uint32   district count D (the length of meta.json "districts")
    N records, 13 bytes each, packed with no padding, in meta.json order
      0  int32    longitude, millionths of a degree
      4  int32    latitude, millionths of a degree
      8  uint32   district index into meta.json "districts", or 0xFFFFFFFF for none
     12  uint8    kind flags: 0x01 private, 0x02 charter, 0x04 exclusively virtual

The file is ``16 + 13 * N`` bytes. Records are unaligned, so browsers should read
them through a ``DataView`` with ``littleEndian = true``.
"""

import struct
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

MAGIC = b"SLPT"
FORMAT_VERSION = 1
NO_DISTRICT = 0xFFFFFFFF
HEADER = struct.Struct("<4sHHII")
RECORD = np.dtype([("lon", "<i4"), ("lat", "<i4"), ("district", "<u4"), ("kind", "u1")])
RECORD_SIZE = RECORD.itemsize
_KNOWN_FLAGS = 0x07
_MAX_LON = 180_000_000
_MAX_LAT = 90_000_000


class PointsFormatError(ValueError):
    """Bytes that are not a valid ``points.bin``, or values that cannot be encoded."""


@dataclass(frozen=True, slots=True)
class Points:
    """Decoded contents of a ``points.bin`` file."""

    lon_e6: npt.NDArray[np.int32]
    lat_e6: npt.NDArray[np.int32]
    district: npt.NDArray[np.uint32]
    kind: npt.NDArray[np.uint8]
    district_count: int

    def __len__(self) -> int:
        return int(self.lon_e6.shape[0])


def encode(
    lon_e6: Sequence[int] | npt.NDArray[np.int32],
    lat_e6: Sequence[int] | npt.NDArray[np.int32],
    district: Sequence[int] | npt.NDArray[np.uint32],
    kind: Sequence[int] | npt.NDArray[np.uint8],
    district_count: int,
) -> bytes:
    """Encode parallel arrays of school values as ``points.bin`` bytes.

    Raises:
        PointsFormatError: if the arrays differ in length or hold a value that is
            out of range (a coordinate beyond ±180/±90 degrees, a district index
            past ``district_count`` other than NO_DISTRICT, or an unknown flag).
    """
    lons = np.asarray(lon_e6, dtype=np.int64)
    lats = np.asarray(lat_e6, dtype=np.int64)
    districts = np.asarray(district, dtype=np.int64)
    kinds = np.asarray(kind, dtype=np.int64)
    count = lons.shape[0]
    if not lats.shape[0] == districts.shape[0] == kinds.shape[0] == count:
        raise PointsFormatError("lon, lat, district and kind must have the same length")
    if not 0 <= district_count < NO_DISTRICT:
        raise PointsFormatError(f"district count {district_count} is out of range")
    if count and (np.abs(lons).max() > _MAX_LON or np.abs(lats).max() > _MAX_LAT):
        raise PointsFormatError("a coordinate is outside ±180/±90 degrees")
    valid_district = ((districts >= 0) & (districts < district_count)) | (districts == NO_DISTRICT)
    if not valid_district.all():
        raise PointsFormatError("a district index is out of range")
    if count and (kinds.min() < 0 or (kinds & ~_KNOWN_FLAGS).any()):
        raise PointsFormatError("a kind value sets an unknown flag")
    records = np.empty(count, dtype=RECORD)
    records["lon"] = lons
    records["lat"] = lats
    records["district"] = districts
    records["kind"] = kinds
    header = HEADER.pack(MAGIC, FORMAT_VERSION, RECORD_SIZE, count, district_count)
    return header + records.tobytes()


def decode(data: bytes) -> Points:
    """Decode ``points.bin`` bytes, checking the header against the payload.

    Raises:
        PointsFormatError: on a bad magic, unknown version or record size, or a
            length that does not match the declared count.
    """
    if len(data) < HEADER.size:
        raise PointsFormatError("file is shorter than the header")
    magic, version, record_size, count, district_count = HEADER.unpack_from(data)
    if magic != MAGIC:
        raise PointsFormatError(f"bad magic {magic!r}")
    if version != FORMAT_VERSION:
        raise PointsFormatError(f"unsupported format version {version}")
    if record_size != RECORD_SIZE:
        raise PointsFormatError(f"record size {record_size}, expected {RECORD_SIZE}")
    expected = HEADER.size + count * RECORD_SIZE
    if len(data) != expected:
        raise PointsFormatError(f"{len(data)} bytes, header implies {expected}")
    records = np.frombuffer(data, dtype=RECORD, count=count, offset=HEADER.size)
    return Points(
        lon_e6=records["lon"].astype(np.int32),
        lat_e6=records["lat"].astype(np.int32),
        district=records["district"].astype(np.uint32),
        kind=records["kind"].astype(np.uint8),
        district_count=district_count,
    )
