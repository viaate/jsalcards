"""Placing the directory's schools in NWS counties, and averaging over schools.

The school directory (``pipeline/out/internal/directory/schools.parquet``, built
from the NCES files by :mod:`snowlight.directory`) gives every school a county
FIPS code and coordinates. The weights are per NWS county, so each school is
placed in one:

* ``fips``: the directory's county code is an NWS county code (every state but
  Connecticut, whose schools carry planning-region codes the NWS does not use);
* ``point``: otherwise, the NWS county whose outline contains the school's
  coordinates;
* ``nearest``: a school just outside every outline (a shoreline point), the
  nearest NWS county of the school's own state within :data:`NEAREST_LIMIT`
  degrees.

A school that none of these places is left out of every average and listed. The
build also counts the ``fips`` schools whose point falls in another county, as
a check on both files.

A school counts in the state of the NWS county it is placed in: where it is, as
its county code and coordinates say. The directory's ``state`` is the school's
address, which for a few schools is across a state line (a mailing address in
the next town over, or a company's office); those are listed
(:attr:`Placement.address_elsewhere`). The ``nearest`` search looks in the state
of the directory's ``state_fips`` (the location's) when it names one.
"""

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import numpy as np
import polars as pl
import shapely

from snowlight.weights.zones import CountyList

NEAREST_LIMIT = 0.05
SCHOOL_COLUMNS = ("index", "id", "state", "state_fips", "county_fips", "lat", "lon")

type Method = Literal["fips", "point", "nearest"]


class SchoolsError(ValueError):
    """The school directory does not have the expected columns."""


@dataclass(frozen=True, slots=True)
class PlacedSchool:
    """One school and the NWS county it was placed in."""

    index: int
    school_id: str
    state: str
    """The state of the NWS county the school is placed in."""
    address_state: str
    """The directory's ``state`` (the school's address)."""
    directory_fips: str
    nws_fips: str
    method: Method


@dataclass(slots=True)
class Placement:
    """Every school's NWS county, and what could not be placed."""

    schools: list[PlacedSchool]
    unplaced: list[str] = field(default_factory=list)
    by_method: Counter[str] = field(default_factory=Counter)
    fips_point_disagreements: int = 0

    @property
    def address_elsewhere(self) -> list[tuple[str, str, str]]:
        """(school id, address state, state placed in) where the two differ."""
        return [
            (school.school_id, school.address_state, school.state)
            for school in self.schools
            if school.address_state != school.state
        ]

    def per_county(self) -> Counter[str]:
        """Return the number of placed schools per NWS county."""
        return Counter(school.nws_fips for school in self.schools)


def read_schools(path: Path) -> pl.DataFrame:
    """Read the columns this module needs from the school directory.

    Raises:
        SchoolsError: a column is missing.
    """
    frame = pl.read_parquet(path)
    missing = [column for column in SCHOOL_COLUMNS if column not in frame.columns]
    if missing:
        raise SchoolsError(f"{path.name}: missing columns {missing}")
    return frame.select(SCHOOL_COLUMNS)


def place_schools(frame: pl.DataFrame, counties: CountyList) -> Placement:
    """Place every school in ``frame`` (see the module docstring)."""
    fips_codes = sorted(counties.counties)
    geometries = [counties.counties[fips].geometry for fips in fips_codes]
    tree = shapely.STRtree(geometries)
    lon = frame["lon"].to_numpy().astype(np.float64)
    lat = frame["lat"].to_numpy().astype(np.float64)
    points = shapely.points(lon, lat)
    point_index, tree_index = tree.query(points, predicate="within")
    containing: dict[int, list[str]] = {}
    for school, county in zip(point_index.tolist(), tree_index.tolist(), strict=True):
        containing.setdefault(school, []).append(fips_codes[county])
    postal = {prefix: state for state, prefix in counties.state_fips.items()}
    placement = Placement(schools=[])
    rows = frame.iter_rows(named=True)
    for position, row in enumerate(rows):
        fips, address = str(row["county_fips"] or ""), str(row["state"] or "")
        state = postal.get(str(row["state_fips"] or ""), address)
        inside = containing.get(position, [])
        method: Method
        chosen: str | None
        if fips in counties.counties:
            chosen, method = fips, "fips"
            if inside and fips not in inside:
                placement.fips_point_disagreements += 1
        elif len(inside) == 1:
            chosen, method = inside[0], "point"
        else:
            point = shapely.Point(float(lon[position]), float(lat[position]))
            chosen = _nearest(point, counties, state, inside)
            method = "nearest"
        if chosen is None:
            placement.unplaced.append(str(row["id"]))
            continue
        placement.by_method[method] += 1
        placement.schools.append(
            PlacedSchool(
                index=int(row["index"]),
                school_id=str(row["id"]),
                state=counties.counties[chosen].state,
                address_state=address,
                directory_fips=fips,
                nws_fips=chosen,
                method=method,
            )
        )
    return placement


def _nearest(
    point: shapely.Point, counties: CountyList, state: str, inside: list[str]
) -> str | None:
    candidates = [fips for fips in inside if counties.counties[fips].state == state]
    if len(candidates) == 1:
        return candidates[0]
    best: tuple[float, str] | None = None
    for county in counties.in_state(state):
        distance = float(shapely.distance(point, county.geometry))
        if distance <= NEAREST_LIMIT and (best is None or distance < best[0]):
            best = (distance, county.fips)
    return None if best is None else best[1]
