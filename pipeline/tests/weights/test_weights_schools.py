"""Placing directory schools in NWS counties.

``fixtures/schools.parquet`` holds eleven real rows of the school directory,
``fixtures/c_16ap26.zip`` twelve real records of the NWS county file (see
``fixtures/provenance.json``).
"""

from typing import TYPE_CHECKING

import polars as pl
import pytest

from snowlight.weights import schools, zones

if TYPE_CHECKING:
    from pathlib import Path

    from weights.conftest import Kit


def _placement(kit: "Kit") -> schools.Placement:
    frame = schools.read_schools(kit.path("schools.parquet"))
    return schools.place_schools(frame, zones.read_counties(kit.path("c_16ap26.zip")))


def test_read_schools_keeps_the_needed_columns(kit: "Kit") -> None:
    frame = schools.read_schools(kit.path("schools.parquet"))
    assert tuple(frame.columns) == schools.SCHOOL_COLUMNS
    assert frame.height == 11


def test_read_schools_rejects_a_frame_without_coordinates(kit: "Kit", tmp_path: "Path") -> None:
    path = tmp_path / "schools.parquet"
    pl.read_parquet(kit.path("schools.parquet")).drop("lat").write_parquet(path)
    with pytest.raises(schools.SchoolsError, match="lat"):
        schools.read_schools(path)


def test_place_schools(kit: "Kit") -> None:
    placement = _placement(kit)
    by_id = {school.school_id: school for school in placement.schools}
    # Rhode Island, Florida and Montana schools carry NWS county codes.
    assert by_id["01256947"].nws_fips == "44007"
    assert by_id["01256947"].method == "fips"
    assert by_id["120069000867"].nws_fips == "12045"
    assert by_id["00791679"].nws_fips == "30063"
    # Connecticut schools carry planning-region codes (09110, Capitol): their points
    # fall in Hartford County (09003), which the NWS still uses.
    assert by_id["00230045"].directory_fips == "09110"
    assert by_id["00230045"].nws_fips == "09003"
    assert by_id["00230045"].method == "point"
    # The Litchfield County school (planning region 09160) is outside every county of
    # the slice and farther than the limit from Hartford County: left out, and listed.
    assert placement.unplaced == ["00230442"]
    assert placement.by_method == {"fips": 8, "point": 2}
    assert sum(placement.per_county().values()) == 10
    assert placement.per_county()["44007"] == 3
    assert placement.fips_point_disagreements == 0


def test_nearest_county_of_the_state(kit: "Kit") -> None:
    """A real Providence school moved 0.02 degrees out to sea, with no county code (synthetic)."""
    frame = schools.read_schools(kit.path("schools.parquet")).filter(pl.col("id") == "01257033")
    frame = frame.with_columns(pl.lit("").alias("county_fips"), pl.lit(-71.2).alias("lon"))
    frame = frame.with_columns(pl.lit(41.45).alias("lat"))
    counties = zones.read_counties(kit.path("c_16ap26.zip"))
    placement = schools.place_schools(frame, counties)
    assert [(s.nws_fips, s.method) for s in placement.schools] == [("44005", "nearest")]


def test_schools_count_in_the_state_they_are_in(kit: "Kit") -> None:
    """Real rows whose address state is changed to a neighbour's (synthetic): the school
    still counts in the state of its county, and is listed; the nearest search follows
    ``state_fips``, not the address."""
    frame = schools.read_schools(kit.path("schools.parquet"))
    moved = frame.with_columns(
        pl.when(pl.col("id") == "01256947")
        .then(pl.lit("MA"))
        .otherwise(pl.col("state"))
        .alias("state")
    )
    counties = zones.read_counties(kit.path("c_16ap26.zip"))
    placement = schools.place_schools(moved, counties)
    by_id = {school.school_id: school for school in placement.schools}
    assert by_id["01256947"].state == "RI"
    assert by_id["01256947"].address_state == "MA"
    assert placement.address_elsewhere == [("01256947", "MA", "RI")]
    assert schools.place_schools(frame, counties).address_elsewhere == []
    at_sea = frame.filter(pl.col("id") == "01257033").with_columns(
        pl.lit("").alias("county_fips"),
        pl.lit(-71.2).alias("lon"),
        pl.lit(41.45).alias("lat"),
        pl.lit("MA").alias("state"),
    )
    placed = schools.place_schools(at_sea, counties)
    assert [(s.nws_fips, s.state, s.method) for s in placed.schools] == [("44005", "RI", "nearest")]
