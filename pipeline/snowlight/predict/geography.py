"""Where districts are: their state, weather region, county, time zone and neighbors.

The pooling chain (spec c.1) borrows from a district's ``nearby`` districts, its
county, its state and its NOAA climate region. The same neighbors are published as
the forecast's ``neighbors``: every other district with a school within
``miles`` of one of the district's schools, nearest first, at most
:data:`~snowlight.schemas.predictions.MAX_NEIGHBORS`.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
import numpy.typing as npt
import polars as pl
from scipy.spatial import cKDTree  # type: ignore[import-untyped]

from snowlight.schemas.predictions import MAX_NEIGHBORS

EARTH_MILES: Final = 3958.7613
"""The mean Earth radius in miles."""

REGIONS: Final[Mapping[str, tuple[str, ...]]] = {
    "northeast": ("CT", "DC", "DE", "MA", "MD", "ME", "NH", "NJ", "NY", "PA", "RI", "VT"),
    "upper_midwest": ("IA", "MI", "MN", "WI"),
    "ohio_valley": ("IL", "IN", "KY", "MO", "OH", "TN", "WV"),
    "southeast": ("AL", "FL", "GA", "NC", "SC", "VA"),
    "northern_rockies": ("MT", "ND", "NE", "SD", "WY"),
    "south": ("AR", "KS", "LA", "MS", "OK", "TX"),
    "southwest": ("AZ", "CO", "NM", "UT"),
    "northwest": ("ID", "OR", "WA"),
    "west": ("CA", "NV"),
}
"""NOAA's nine climate regions of the contiguous states (DC with the Northeast)."""

REGION_OF: Final[Mapping[str, str]] = {
    state: region for region, states in REGIONS.items() for state in states
}

STATE_BY_FIPS: Final[Mapping[str, str]] = {
    "01": "AL", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT", "10": "DE",
    "11": "DC", "12": "FL", "13": "GA", "16": "ID", "17": "IL", "18": "IN", "19": "IA",
    "20": "KS", "21": "KY", "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI",
    "27": "MN", "28": "MS", "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH", "40": "OK",
    "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD", "47": "TN", "48": "TX",
    "49": "UT", "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI", "56": "WY",
}  # fmt: skip
"""Postal codes of the contiguous states and DC by FIPS code (an LEAID's first two digits)."""

_CHUNK: Final = 4096


def state_of_leaid(leaid: str) -> str | None:
    """The state an NCES LEAID's first two digits name, or ``None`` outside the contiguous 48."""
    return STATE_BY_FIPS.get(leaid[:2])


def _unit_vectors(
    lon: npt.NDArray[np.float64], lat: npt.NDArray[np.float64]
) -> npt.NDArray[np.float64]:
    lam, phi = np.radians(lon), np.radians(lat)
    return np.column_stack((np.cos(phi) * np.cos(lam), np.cos(phi) * np.sin(lam), np.sin(phi)))


def _chord(miles: float) -> float:
    return float(2.0 * np.sin(miles / EARTH_MILES / 2.0))


def neighbors(
    lon: npt.NDArray[np.float64],
    lat: npt.NDArray[np.float64],
    district: npt.NDArray[np.int64],
    miles: float,
    limit: int = MAX_NEIGHBORS,
) -> dict[int, tuple[int, ...]]:
    """Each district's neighbors: every other district with a school within ``miles`` of one
    of its schools, nearest first (ties by index), at most ``limit``.

    ``lon``, ``lat`` and ``district`` give one school each; a district below 0 (no district)
    is left out. Districts without a neighbor are absent from the answer.
    """
    keep = district >= 0
    points = _unit_vectors(lon[keep], lat[keep])
    owner = district[keep]
    if owner.size == 0:
        return {}
    tree = cKDTree(points)
    radius = _chord(miles)
    frames: list[pl.DataFrame] = []
    for first in range(0, len(points), _CHUNK):
        block = points[first : first + _CHUNK]
        found = tree.query_ball_point(block, radius)
        lengths = np.fromiter((len(item) for item in found), dtype=np.int64, count=len(found))
        if not lengths.sum():
            continue
        source = np.repeat(np.arange(first, first + len(block)), lengths)
        target = np.concatenate([np.asarray(item, dtype=np.int64) for item in found if item])
        mine, theirs = owner[source], owner[target]
        other = mine != theirs
        if not other.any():
            continue
        chord = np.linalg.norm(points[source[other]] - points[target[other]], axis=1)
        frames.append(
            pl.DataFrame({"d": mine[other], "e": theirs[other], "chord": chord})
            .group_by("d", "e")
            .agg(pl.col("chord").min())
        )
    if not frames:
        return {}
    pairs = (
        pl.concat(frames)
        .group_by("d", "e")
        .agg(pl.col("chord").min())
        .sort("d", "chord", "e")
        .group_by("d", maintain_order=True)
        .agg(pl.col("e").head(limit))
    )
    return {
        int(d): tuple(int(e) for e in es)
        for d, es in zip(pairs["d"].to_list(), pairs["e"].to_list(), strict=True)
    }


def majority(values: Sequence[str | None]) -> str | None:
    """The most common value that is not ``None`` (ties to the smallest), or ``None``."""
    counted = Counter(value for value in values if value is not None)
    if not counted:
        return None
    top = max(counted.values())
    return min(value for value, count in counted.items() if count == top)


@dataclass(frozen=True, slots=True)
class DistrictPlace:
    """One district's place in the pooling chain."""

    leaid: str
    state: str | None
    county: str | None
    """Its schools' most common county FIPS code."""
    time_zone: str | None
    """Its schools' most common IANA zone."""

    @property
    def region(self) -> str | None:
        """Its NOAA climate region."""
        return None if self.state is None else REGION_OF.get(self.state)
