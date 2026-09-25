"""Round-trip and validation tests for points.bin."""

import struct

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from snowlight.directory import points

record = st.tuples(
    st.integers(-180_000_000, 180_000_000),
    st.integers(-90_000_000, 90_000_000),
    st.one_of(st.integers(0, 49), st.just(points.NO_DISTRICT)),
    st.integers(0, 7),
)


@given(st.lists(record, max_size=60))
def test_round_trip(records: list[tuple[int, int, int, int]]) -> None:
    lons = [r[0] for r in records]
    lats = [r[1] for r in records]
    districts = [r[2] for r in records]
    kinds = [r[3] for r in records]
    data = points.encode(lons, lats, districts, kinds, district_count=50)
    assert len(data) == points.HEADER.size + 13 * len(records)
    decoded = points.decode(data)
    assert len(decoded) == len(records)
    assert decoded.lon_e6.tolist() == lons
    assert decoded.lat_e6.tolist() == lats
    assert decoded.district.tolist() == districts
    assert decoded.kind.tolist() == kinds
    assert decoded.district_count == 50


def test_layout_is_little_endian_and_packed() -> None:
    # A real school: Albertville Middle School, district index 0, public.
    data = points.encode([-86_206_200], [34_260_200], [0], [0], district_count=1)
    assert data[:4] == b"SLPT"
    assert struct.unpack_from("<HHII", data, 4) == (points.FORMAT_VERSION, 13, 1, 1)
    assert struct.unpack_from("<iiIB", data, 16) == (-86_206_200, 34_260_200, 0, 0)
    assert len(data) == 29


def test_encode_accepts_numpy_arrays() -> None:
    data = points.encode(
        np.array([1, 2], dtype=np.int32),
        np.array([3, 4], dtype=np.int32),
        np.array([0, points.NO_DISTRICT], dtype=np.uint32),
        np.array([1, 0], dtype=np.uint8),
        district_count=1,
    )
    assert points.decode(data).district.tolist() == [0, points.NO_DISTRICT]


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (([1], [1, 2], [0], [0], 1), "same length"),
        (([180_000_001], [0], [0], [0], 1), "outside"),
        (([0], [90_000_001], [0], [0], 1), "outside"),
        (([0], [0], [1], [0], 1), "district index"),
        (([0], [0], [0], [8], 1), "unknown flag"),
        (([0], [0], [0], [0], -1), "district count"),
    ],
)
def test_encode_refuses_bad_values(
    args: tuple[list[int], list[int], list[int], list[int], int], message: str
) -> None:
    with pytest.raises(points.PointsFormatError, match=message):
        points.encode(*args[:4], district_count=args[4])


def test_decode_refuses_bad_files() -> None:
    good = points.encode([0], [0], [0], [0], district_count=1)
    with pytest.raises(points.PointsFormatError, match="shorter"):
        points.decode(good[:10])
    with pytest.raises(points.PointsFormatError, match="magic"):
        points.decode(b"XXXX" + good[4:])
    with pytest.raises(points.PointsFormatError, match="version"):
        points.decode(good[:4] + struct.pack("<H", 2) + good[6:])
    with pytest.raises(points.PointsFormatError, match="record size"):
        points.decode(good[:6] + struct.pack("<H", 12) + good[8:])
    with pytest.raises(points.PointsFormatError, match="header implies"):
        points.decode(good + b"\x00")
