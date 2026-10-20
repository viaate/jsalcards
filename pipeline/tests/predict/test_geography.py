"""Neighbors within ten miles, nearest first, at most twelve."""

import numpy as np

from snowlight.predict.geography import (
    REGION_OF,
    DistrictPlace,
    majority,
    neighbors,
    state_of_leaid,
)

MILE_LAT = 1 / 69.05  # degrees of latitude in a mile, about


def test_neighbors_are_within_the_distance_nearest_first() -> None:
    # District 0 at the origin; 1 two miles north, 2 six miles north, 3 twenty miles north.
    lat = np.array(
        [40.0, 40.0 + 2 * MILE_LAT, 40.0 + 6 * MILE_LAT, 40.0 + 20 * MILE_LAT], dtype=np.float64
    )
    lon = np.full(4, -100.0)
    district = np.array([0, 1, 2, 3], dtype=np.int64)
    found = neighbors(lon, lat, district, 10)
    assert found[0] == (1, 2)
    assert found[2] == (1, 0)
    assert 3 not in found
    assert found[1] == (0, 2)


def test_at_most_the_limit_and_schools_without_district_left_out() -> None:
    count = 20
    lat = (40.0 + np.arange(count) * 0.2 * MILE_LAT).astype(np.float64)
    lon = np.full(count, -100.0)
    district = np.arange(count, dtype=np.int64)
    district[5] = -1
    found = neighbors(lon, lat, district, 10)
    assert len(found[0]) == 12
    assert all(5 not in near for near in found.values())
    assert found[0][:2] == (1, 2)
    assert neighbors(lon[:0], lat[:0], district[:0], 10) == {}
    assert neighbors(lon[:1], lat[:1], district[:1], 10) == {}


def test_places() -> None:
    assert majority(["a", "b", "b", None]) == "b"
    assert majority(["b", "a"]) == "a"
    assert majority([None]) is None
    assert state_of_leaid("2011820") == "KS"
    assert state_of_leaid("0200001") is None  # Alaska is not in the contiguous states
    assert REGION_OF["MO"] == "ohio_valley"
    assert DistrictPlace("2011820", "KS", "20091", "America/Chicago").region == "south"
    assert DistrictPlace("0000000", None, None, None).region is None
