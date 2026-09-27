"""Counting school days per school: zone rows by polygon, county rows, storm polygons.

Real rows: the Salt Lake slice of 2019-20 (three SLC Winter Storm Warnings for the valley
zone UTZ003 and the Wasatch mountain zone UTZ008, read against IEM's copies of those
zones as they stood then), the NYZ072, FLZ073 and FLZ074 rows of 2017-18 (the school-year
rule), the build's 2024-25 slice (Rhode Island and Gulf County, Florida, with their FF.W
polygons) and the schools around them.
"""

from dataclasses import replace
from datetime import date
from typing import TYPE_CHECKING

import numpy as np
import pytest
import shapely

from snowlight.weights import (
    archive,
    count,
    polygons,
    schoolcount,
    schools,
    schoolzones,
    zonepolys,
    zones,
)
from snowlight.weights.codes import BY_CODE, SUBSETS

if TYPE_CHECKING:
    import polars as pl

    from weights.conftest import Kit


def _sets(kit: "Kit") -> list[zonepolys.ZoneSet]:
    return [
        zonepolys.read_zone_set(kit.path(f"{release.url.rsplit('/', 1)[-1]}"), release)
        for release in kit.zone_releases()
    ]


def _run(  # noqa: PLR0913
    kit: "Kit",
    year: int,
    school_file: str,
    county_file: str,
    *,
    frame: "pl.DataFrame | None" = None,
    county_tally: count.Tally | None = None,
    county_left_out: dict[str, list[int]] | None = None,
    nearest_km: float = schoolzones.NEAREST_KM,
) -> tuple[schoolcount.SchoolTally, schools.Placement, archive.SchoolYearFile]:
    cache = kit.cache()
    file = archive.load_year(cache, year)
    book = zonepolys.build_book(cache, file.rows, _sets(kit))
    directory = schools.read_schools(kit.path(school_file))
    frame = directory if frame is None else frame
    counties = zones.read_counties(kit.path(county_file))
    placement = schools.place_schools(directory, counties)
    zoned = schoolzones.place_in_zones(frame, placement, book.reference, counties)
    members = schoolzones.memberships(book.polygons, frame, placement, zoned)
    storms = polygons.load_polygons(cache, year)
    by_year = schoolzones.place_by_year(
        book.polygons,
        schoolzones.year_versions([file], book, {year: storms.events}),
        zoned,
        members,
        coordinates=schoolzones.school_coordinates(frame, placement),
        nearest_km=nearest_km,
    )
    cells = schoolcount.build_cells(zoned, members, by_year)
    tally = schoolcount.count_schools(
        [file],
        {year: storms},
        book,
        cells,
        state_fips=counties.state_fips,
        school_points=schoolcount.school_frame_points(frame, placement),
        zoned=zoned,
        county_tally=county_tally or count.Tally(years=[year]),
        county_left_out=county_left_out or {},
    )
    return tally, placement, file


def _expected(file: archive.SchoolYearFile, ugc: str, zones_of: tuple[str, ...]) -> set[date]:
    days = frozenset(count.school_days(file.year))
    found: set[date] = set()
    for row in file.rows:
        if row.ugc == ugc:
            found |= count.counted_days(row.begin, row.end, row.product_issued, zones_of) & days
    return found


def test_day_index() -> None:
    index = schoolcount.DayIndex.of([2019, 2020])
    assert len(index.days) == len(count.school_days(2019)) + len(count.school_days(2020))
    assert index.starts.tolist() == [0, len(count.school_days(2019))]
    assert index.per_year(np.ones(len(index.days))).tolist() == [
        len(count.school_days(2019)),
        len(count.school_days(2020)),
    ]
    assert index.days[index.position[date(2019, 8, 15)]] == date(2019, 8, 15)
    with pytest.raises(schoolcount.SchoolCountError, match="not increasing"):
        schoolcount.DayIndex.of([2020, 2019])


def test_valley_and_mountain_schools_take_their_own_zones(kit: "Kit") -> None:
    tally, placement, file = _run(kit, 2019, "schools-zones.parquet", "c_16ap26-zones.zip")
    days = schoolcount.summarize_schools(tally, SUBSETS)
    by_id = {school.school_id: days[p] for p, school in enumerate(placement.schools)}
    denver = ("America/Denver",)
    valley = _expected(file, "UTZ003", denver)
    mountain = _expected(file, "UTZ008", denver)
    # SLC.WS.W.0012 of 2019 was for the mountains only: the valley school does not get it.
    assert valley < mountain
    assert by_id["01412727"].code_days == {"WS.W": len(valley)}
    assert by_id["490014201380"].code_days == {"WS.W": len(mountain)}
    assert by_id["01412727"].days_per_year == len(valley) * BY_CODE["WS.W"].weight
    assert by_id["490014201380"].by_year == {2019: (float(len(mountain)), len(mountain))}
    assert by_id["490014201380"].subset_days_per_year["winter"] == len(mountain)
    assert by_id["490014201380"].subset_days_per_year["flood"] == 0
    # The Miami and Connecticut schools had none of these rows.
    assert by_id["120039004068"].days_per_year == 0
    assert by_id["01412727"].years_counted == (2019,)
    assert tally.stats.zone_rows == len(file.rows)
    assert tally.stats.polygon_rows == 2  # SLC's FF.W 17 of 2019, far from these schools
    assert tally.stats.polygon_rows_reaching_schools == 0


def test_flash_flood_polygons_replace_county_rows(kit: "Kit") -> None:
    tally, placement, file = _run(kit, 2024, "schools.parquet", "c_16ap26.zip")
    ffw_county_rows = [row for row in file.rows if row.code == "FF.W"]
    assert tally.stats.polygon_county_rows_replaced == len(ffw_county_rows)
    assert tally.stats.polygon_events_without_polygons == {}
    assert tally.stats.county_rows == 0
    loaded = polygons.load_polygons(kit.cache(), 2024)
    days = frozenset(count.school_days(2024))
    frame = schools.read_schools(kit.path("schools.parquet"))
    points = dict(
        zip(frame["id"].to_list(), zip(frame["lon"], frame["lat"], strict=True), strict=True)
    )
    import shapely  # noqa: PLC0415

    for position, school in enumerate(placement.schools):
        point = shapely.Point(*points[school.school_id])
        zones_of = ("America/New_York",) if school.state == "RI" else None
        if zones_of is None:
            continue
        expected: set[date] = set()
        for row in loaded.rows:
            if row.geometry.intersects(point):
                expected |= (
                    count.counted_days(row.begin, row.end, row.product_issued, zones_of) & days
                )
        found = tally.polygon_days.get(position, {}).get("FF.W", set())
        assert {tally.index.days[i] for i in found} == expected


def test_a_school_far_from_every_zone_takes_its_county_rule(kit: "Kit") -> None:
    cache = kit.cache()
    counties = zones.load_counties(cache, kit.county_release())
    releases = zones.load_releases(cache, kit.releases)
    catalog = zones.ZoneCountyCatalog(releases, counties.state_fips)
    file = archive.load_year(cache, 2024)
    county_tally = count.count_years([file], catalog, counties)
    directory = schools.read_schools(kit.path("schools.parquet"))
    # Synthetic: Kingston Hill Academy's point moved 0.2 degrees south, into the Atlantic.
    moved = directory.with_columns(
        (directory["lat"] - np.where(directory["id"] == "440003300225", 0.2, 0.0)).alias("lat")
    )
    tally, placement, _ = _run(
        kit,
        2024,
        "schools.parquet",
        "c_16ap26.zip",
        frame=moved,
        county_tally=county_tally,
        county_left_out={"44009": []},
    )
    assert tally.stats.fallback_cells == 1
    days = schoolcount.summarize_schools(tally, SUBSETS)
    position = next(
        p for p, school in enumerate(placement.schools) if school.school_id == "440003300225"
    )
    rule = count.summarize(
        county_tally, ["44009"], count.ZonesOnDay(catalog), SUBSETS, {"44009": ()}
    )["44009"]
    assert days[position].days_per_year == pytest.approx(rule.days_per_year)
    assert days[position].code_days == {k: v for k, v in rule.code_days.items() if v}


def test_schools_outside_their_zone_outline_of_the_year_take_its_rows(kit: "Kit") -> None:
    tally, placement, file = _run(kit, 2017, "schools-zones.parquet", "c_16ap26-zones.zip")
    days = schoolcount.summarize_schools(tally, SUBSETS)
    by_id = {school.school_id: days[p] for p, school in enumerate(placement.schools)}
    eastern = ("America/New_York",)
    nyz072 = _expected(file, "NYZ072", eastern)
    assert nyz072
    # Waterside Plaza (16 m outside NYZ072's outline of 2017-18) and Hunters Point
    # (901 m outside it) take every NYZ072 row of the year, like a school inside it.
    for school_id in ("A0902269", "360010206660"):
        found = by_id[school_id]
        assert found.any_days_per_year == len(nyz072)
    assert tally.stats.zone_rows_reaching_by_year == 11
    # The west Miami-Dade school lay in FLZ073 in 2017-18: it takes FLZ073's rows (Irma).
    irma = _expected(file, "FLZ073", eastern)
    assert by_id["120039003051"].any_days_per_year == len(irma)
    # A direct recount agrees, and adds the same version in the same school year.
    cache = kit.cache()
    storms = polygons.load_polygons(cache, 2017)
    book = zonepolys.build_book(cache, file.rows, _sets(kit))
    counties = zones.read_counties(kit.path("c_16ap26-zones.zip"))
    index = schoolcount.recount_index([file], {2017: storms}, book, counties.state_fips)
    again = schoolcount.recount(
        schoolcount.RecountSchool(
            point=shapely.Point(-73.972869, 40.736897),
            fips="36061",
            time_zones=eastern,
            own_zone="NYZ072",
        ),
        index,
        book,
    )
    assert again.days_per_year == pytest.approx(by_id["A0902269"].days_per_year)
    assert again.by_year_rows == {2017: frozenset({"iem/NYZ072/61.0158"})}
    assert again.county_years == frozenset()


def test_a_school_year_beyond_the_limit_takes_the_county_rule(kit: "Kit") -> None:
    cache = kit.cache()
    counties = zones.load_counties(cache, kit.county_release())
    releases = zones.load_releases(cache, kit.releases)
    catalog = zones.ZoneCountyCatalog(releases, counties.state_fips)
    file = archive.load_year(cache, 2024)
    county_tally = count.count_years([file], catalog, counties)
    directory = schools.read_schools(kit.path("schools.parquet"))
    # Synthetic: Kingston Hill Academy's point moved 0.13 degrees south, 0.63 km off the
    # shore of RIZ006: placed "nearest" (within 2 km), then checked against a 0.5 km limit.
    moved = directory.with_columns(
        (directory["lat"] - np.where(directory["id"] == "440003300225", 0.13, 0.0)).alias("lat")
    )
    tally, placement, _ = _run(
        kit,
        2024,
        "schools.parquet",
        "c_16ap26.zip",
        frame=moved,
        county_tally=county_tally,
        county_left_out={"44009": []},
        nearest_km=0.5,
    )
    assert tally.stats.fallback_cells == 0
    assert tally.stats.county_year_cells == 1
    days = schoolcount.summarize_schools(tally, SUBSETS)
    position = next(
        p for p, school in enumerate(placement.schools) if school.school_id == "440003300225"
    )
    rule = count.summarize(
        county_tally, ["44009"], count.ZonesOnDay(catalog), SUBSETS, {"44009": ()}
    )["44009"]
    assert days[position].days_per_year == pytest.approx(rule.days_per_year)
    assert days[position].code_days == {k: v for k, v in rule.code_days.items() if v}
    # The recount takes the county's days for that school year too; left out with it.
    storms = polygons.load_polygons(cache, 2024)
    book = zonepolys.build_book(cache, file.rows, _sets(kit))
    index = schoolcount.recount_index([file], {2024: storms}, book, counties.state_fips)
    point = moved.filter(moved["id"] == "440003300225")
    school = schoolcount.RecountSchool(
        point=shapely.Point(point["lon"][0], point["lat"][0]),
        fips="44009",
        time_zones=("America/New_York",),
        own_zone="RIZ006",
    )
    again = schoolcount.recount(school, index, book, county_tally=county_tally, nearest_km=0.5)
    assert again.days_per_year == pytest.approx(rule.days_per_year)
    assert again.county_years == frozenset({2024})
    with pytest.raises(schoolcount.SchoolCountError, match="no county tally"):
        schoolcount.recount(school, index, book, nearest_km=0.5)
    with pytest.raises(schoolcount.SchoolCountError, match="every school year left out"):
        schoolcount.recount(
            school, index, book, county_tally=county_tally, county_left_out=(2024,), nearest_km=0.5
        )
    cell = tally.cells.keys[tally.cells.of_school[position]]
    assert cell.county_years == frozenset({2024})
    assert cell.polygon_years == frozenset()


def test_summaries_leave_out_years_and_refuse_none_left(kit: "Kit") -> None:
    tally, _, _ = _run(kit, 2024, "schools.parquet", "c_16ap26.zip")
    cell = tally.cells.of_school[0]
    tally.cell_left_out[cell] = frozenset({2024})
    with pytest.raises(schoolcount.SchoolCountError, match="every school year left out"):
        schoolcount.summarize_schools(tally, SUBSETS)
    two = replace(tally, index=schoolcount.DayIndex.of([2023, 2024]))
    two.cell_left_out[cell] = frozenset({2023})
    summary = schoolcount.summarize_schools(two, SUBSETS)[0]
    assert summary.by_year[2023] is None
    assert summary.years_counted == (2024,)
    assert summary.code_days_per_year("WS.W") == summary.code_days.get("WS.W", 0)


def test_a_year_without_its_polygon_file_is_an_error(kit: "Kit") -> None:
    cache = kit.cache()
    file = archive.load_year(cache, 2024)
    book = zonepolys.build_book(cache, file.rows, _sets(kit))
    with pytest.raises(schoolcount.SchoolCountError, match="no storm-polygon file"):
        schoolcount.count_schools(
            [file],
            {},
            book,
            schoolcount.Cells(),
            state_fips={},
            school_points=schoolcount.school_frame_points(
                schools.read_schools(kit.path("schools.parquet")), schools.Placement(schools=[])
            ),
            zoned=schoolzones.ZonePlacement(reference="z_18mr25", schools=[]),
            county_tally=count.Tally(years=[2024]),
            county_left_out={},
        )
