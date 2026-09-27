"""Each school in its own zone: inside, the nearest zone within 2 km, or its county.

Real rows: the zone-test schools (a Salt Lake valley school, the county's school in the
Wasatch mountain zone, two schools just outside every zone polygon, two New York schools on
the East River, a Cherokee school in Swain County, NC, and a west Miami-Dade school) with
the county records around them, and the build's schools (Gulf County, Florida, is split by
a time zone line). The zone release is the ``z_18mr25`` slice; the school-year rule reads
the NCZ051 rows of 2016-17 and the NYZ072, FLZ073 and FLZ074 rows of 2017-18 against IEM's
copies of those zones as they stood then.
"""

from typing import TYPE_CHECKING, Any

import numpy as np
import pytest
import shapely

from snowlight.output import JSONValue
from snowlight.weights import archive, notes, perschool, schools, schoolzones, zonepolys, zones

if TYPE_CHECKING:
    from weights.conftest import Kit


def _reference(kit: "Kit") -> zonepolys.ZoneSet:
    return zonepolys.read_zone_set(kit.path("z_18mr25.zip"), kit.zone_releases()[0])


def test_schools_inside_and_near_their_zones(kit: "Kit") -> None:
    frame = schools.read_schools(kit.path("schools-zones.parquet"))
    counties = zones.read_counties(kit.path("c_16ap26-zones.zip"))
    placement = schools.place_schools(frame, counties)
    zoned = schoolzones.place_in_zones(frame, placement, _reference(kit), counties)
    by_id = {school.school_id: school for school in zoned.schools}
    valley, mountain = by_id["01412727"], by_id["490014201380"]
    assert (valley.zone, valley.method, valley.distance_km) == ("UTZ105", "inside", 0.0)
    assert (mountain.zone, mountain.method) == ("UTZ111", "inside")
    assert valley.fips == mountain.fips == "49035"
    assert valley.time_zones == ("America/Denver",)
    aventura, lebanon = by_id["120039004068"], by_id["090171000303"]
    assert (aventura.zone, aventura.method) == ("FLZ173", "nearest")
    assert aventura.distance_km == pytest.approx(0.016, abs=0.001)
    assert (lebanon.zone, lebanon.method) == ("NYZ071", "nearest")
    assert lebanon.distance_km == pytest.approx(0.383, abs=0.001)
    waterside, hunters_point = by_id["A0902269"], by_id["360010206660"]
    assert (waterside.zone, waterside.method, waterside.fips) == ("NYZ072", "inside", "36061")
    assert (hunters_point.zone, hunters_point.method) == ("NYZ072", "inside")
    assert hunters_point.fips == "36081"  # Queens: its point is in the river, in NYZ072 now
    assert zoned.by_method == {"inside": 6, "nearest": 2}
    assert [school.school_id for school in zoned.nearest] == ["090171000303", "120039004068"]
    assert zoned.county == []
    assert zoned.per_zone() == {
        "UTZ105": 1,
        "UTZ111": 1,
        "FLZ173": 1,
        "NYZ071": 1,
        "NYZ072": 2,
        "NCZ051": 1,
        "FLZ074": 1,
    }
    assert zoned.reference == "z_18mr25"


def test_a_school_farther_than_2_km_falls_back_to_its_county(kit: "Kit") -> None:
    frame = schools.read_schools(kit.path("schools-zones.parquet"))
    counties = zones.read_counties(kit.path("c_16ap26-zones.zip"))
    placement = schools.place_schools(frame, counties)
    # Synthetic: the Aventura school's point moved 0.05 degrees east, into the Atlantic,
    # 3.3 km from FLZ173.
    moved = frame.with_columns(
        (frame["lon"] + np.where(frame["id"] == "120039004068", 0.05, 0.0)).alias("lon")
    )
    zoned = schoolzones.place_in_zones(moved, placement, _reference(kit), counties)
    (fallen,) = zoned.county
    assert fallen.school_id == "120039004068"
    assert fallen.zone == "FLZ173"
    assert fallen.distance_km == pytest.approx(3.316, abs=0.01)
    assert fallen.time_zones == counties.counties[fallen.fips].time_zones
    # Farther still than the search box: no zone is found at all.
    far = frame.with_columns(
        (frame["lon"] + np.where(frame["id"] == "120039004068", 1.0, 0.0)).alias("lon")
    )
    (lost,) = schoolzones.place_in_zones(far, placement, _reference(kit), counties).county
    assert lost.zone is None
    assert lost.distance_km == float("inf")


def test_time_zones_come_from_the_school_zone(kit: "Kit") -> None:
    frame = schools.read_schools(kit.path("schools.parquet"))
    counties = zones.read_counties(kit.path("c_16ap26.zip"))
    placement = schools.place_schools(frame, counties)
    zoned = schoolzones.place_in_zones(frame, placement, _reference(kit), counties)
    gulf = [school for school in zoned.schools if school.fips == "12045"]
    # Gulf County and its zone FLZ114 are both marked "CE": the line is not drawn, so
    # its two schools keep both zones.
    assert {school.zone for school in gulf} == {"FLZ114"}
    assert all(school.time_zones == ("America/Chicago", "America/New_York") for school in gulf)
    assert zoned.time_zone_split_kept == 2
    assert zoned.time_zone_from_zone == 0
    assert schoolzones.zone_time_zones(("E",)) == ("America/New_York",)
    assert schoolzones.zone_time_zones(("CE",)) == ("America/Chicago", "America/New_York")
    with pytest.raises(zonepolys.ZonePolygonError, match="unknown letters"):
        schoolzones.zone_time_zones(("Ah",))  # Alaska's codes, outside the contiguous states


def test_memberships_follow_every_version(kit: "Kit") -> None:
    frame = schools.read_schools(kit.path("schools-zones.parquet"))
    counties = zones.read_counties(kit.path("c_16ap26-zones.zip"))
    placement = schools.place_schools(frame, counties)
    reference = _reference(kit)
    zoned = schoolzones.place_in_zones(frame, placement, reference, counties)
    old = zonepolys.read_version_file(kit.path("iem-zones-SLC-WS.W-20191127T1100.zip"))
    polygons = {
        "z_18mr25/UTZ105": reference.shapes["UTZ105"].geometry,
        "z_18mr25/UTZ111": reference.shapes["UTZ111"].geometry,
        "z_18mr25/FLZ173": reference.shapes["FLZ173"].geometry,
        **{f"iem/{zone.ugc}": zone.geometry for zone in old},
    }
    members = schoolzones.memberships(polygons, frame, placement, zoned)
    ids = [school.school_id for school in placement.schools]

    def reached(key: str) -> set[str]:
        return {ids[position] for position in members[key].tolist()}

    # The valley school is in UTZ003's polygon as it stood in 2019 and not in UTZ008's;
    # the mountain school the other way round.
    assert reached("iem/UTZ003") == {"01412727"}
    assert reached("iem/UTZ008") == {"490014201380"}
    assert reached("z_18mr25/UTZ105") == {"01412727"}
    # The Aventura school is outside FLZ173: its rows reach it through the school-year
    # rule (place_by_year), not through the polygon.
    assert reached("z_18mr25/FLZ173") == set()


OUTSIDE_YEARS = (2015, 2016, 2017)
"""The school years of the rule's slices (their zone versions are planned together)."""


def _year_rule(
    kit: "Kit", year: int, nearest_km: float = schoolzones.NEAREST_KM
) -> tuple[schoolzones.YearPlacement, zonepolys.VersionBook, list[str]]:
    """The school-year rule on a real school-year slice and the zone-test schools."""
    cache = kit.cache()
    files = {item: archive.load_year(cache, item) for item in OUTSIDE_YEARS}
    sets = [
        zonepolys.read_zone_set(kit.path(f"{name}.zip"), release)
        for name, release in zip(("z_18mr25", "z_16ap26"), kit.zone_releases(), strict=True)
    ]
    book = zonepolys.build_book(cache, [row for f in files.values() for row in f.rows], sets)
    assert book.unresolved == []
    frame = schools.read_schools(kit.path("schools-zones.parquet"))
    counties = zones.read_counties(kit.path("c_16ap26-zones.zip"))
    placement = schools.place_schools(frame, counties)
    zoned = schoolzones.place_in_zones(frame, placement, book.reference, counties)
    members = schoolzones.memberships(book.polygons, frame, placement, zoned)
    found = schoolzones.place_by_year(
        book.polygons,
        schoolzones.year_versions([files[year]], book),
        zoned,
        members,
        coordinates=schoolzones.school_coordinates(frame, placement),
        nearest_km=nearest_km,
    )
    return found, book, [school.school_id for school in placement.schools]


def test_waterside_plaza_takes_its_zone_outline_of_2017(kit: "Kit") -> None:
    by_year, book, ids = _year_rule(kit, 2017)
    # NYZ072's rows of 2017-18 were issued for IEM's copy of the zone as it stood then,
    # 61.0158 km2 (the full-resolution answer of OKX's WS.W of 4 January 2018, 06:00 UTC).
    version = book.resolved[zonepolys.Version("NYZ072", 61.0157585144043)]
    assert (version.key, version.source, version.rows) == ("iem/NYZ072/61.0158", "iem", 11)
    outline = book.polygons["iem/NYZ072/61.0158"]
    waterside = shapely.Point(-73.972869, 40.736897)  # the directory's point, Waterside Plaza
    assert not outline.intersects(waterside)
    assert schoolzones.distance_km(outline, waterside.x, waterside.y) == pytest.approx(
        0.0157, abs=0.0005
    )
    logged = {item.school_id: item for item in by_year.outside}
    # (The slice holds no FLZ173 row, so the Aventura school has nothing to take.)
    assert set(logged) == {"A0902269", "360010206660"}
    item = logged["A0902269"]
    assert (item.year, item.zone, item.method, item.inside_own_zone) == (
        2017,
        "NYZ072",
        "nearest",
        False,
    )
    (missed,) = item.missed
    assert (missed.key, missed.rows, missed.taken) == ("iem/NYZ072/61.0158", 11, True)
    assert missed.distance_km == pytest.approx(0.0157, abs=0.0005)
    hunters_point = logged["360010206660"]
    assert hunters_point.method == "nearest"
    assert hunters_point.distance_km == pytest.approx(0.901, abs=0.001)
    # Both take the version's rows of 2017-18, in that school year only.
    position = {school_id: p for p, school_id in enumerate(ids)}
    assert by_year.extra == {
        ("iem/NYZ072/61.0158", 2017): sorted([position["A0902269"], position["360010206660"]])
    }
    assert by_year.county_years == {}


def test_a_redrawn_zone_school_lay_in_the_other_zone(kit: "Kit") -> None:
    by_year, book, _ = _year_rule(kit, 2017)
    # West Miami-Dade: in FLZ074 now; in 2017-18 FLZ074's outline (562 km2) did not
    # cover it and FLZ073's (2,968 km2) did, so it takes FLZ073's rows, not FLZ074's.
    point = shapely.Point(-80.388051, 25.76858)
    assert book.polygons["iem/FLZ073/2967.8022"].intersects(point)
    assert not book.polygons["iem/FLZ074/562.1982"].intersects(point)
    assert by_year.in_other_zone == {"FLZ074": 1}
    assert by_year.schools_in_other_zone == 1
    assert "120039003051" not in {item.school_id for item in by_year.outside}


def test_beyond_the_limit_a_school_year_falls_back_to_the_county(kit: "Kit") -> None:
    by_year, _, ids = _year_rule(kit, 2017, nearest_km=0.5)
    logged = {item.school_id: item for item in by_year.outside}
    assert logged["360010206660"].method == "county"
    assert [m.taken for m in logged["360010206660"].missed] == [False]
    assert logged["A0902269"].method == "nearest"
    assert by_year.county_years == {ids.index("360010206660"): frozenset({2017})}
    assert by_year.by_method() == {"nearest": 1, "county": 1}


def test_an_outline_that_changed_within_the_school_year(kit: "Kit") -> None:
    by_year, book, _ = _year_rule(kit, 2016)
    # NCZ051's rows of 2016-17 were joined to two outlines: 531 km2 (nine rows) and
    # 1,400 km2 (one row, April 2017). The Cherokee school is inside the second and
    # 0.73 km outside the first: it takes both.
    assert {item.key for item in book.resolved.values() if item.version.ugc == "NCZ051"} == {
        "iem/NCZ051/531.0424",
        "iem/NCZ051/1400.3182",
    }
    (item,) = [i for i in by_year.outside if i.school_id == "590006600044"]
    assert (item.method, item.inside_own_zone) == ("nearest", True)
    (missed,) = item.missed
    assert (missed.key, missed.rows, missed.taken) == ("iem/NCZ051/531.0424", 9, True)
    assert missed.distance_km == pytest.approx(0.730, abs=0.001)
    # Beyond the limit, a school inside another outline of its zone that year keeps
    # that outline's rows and does not take the far one; it does not fall back.
    far, _, _ = _year_rule(kit, 2016, nearest_km=0.5)
    (item,) = [i for i in far.outside if i.school_id == "590006600044"]
    assert item.method == "not_taken"
    assert [m.taken for m in item.missed] == [False]
    assert far.county_years == {}
    assert far.extra == {}


def test_distance_on_the_local_plane() -> None:
    # Synthetic: a unit square one degree east of the point, at the equator and at 60 N.
    square = shapely.box(1.0, -0.5, 2.0, 0.5)
    assert schoolzones.distance_km(square, 0.0, 0.0) == pytest.approx(111.195, abs=0.01)
    far_north = shapely.box(1.0, 59.5, 2.0, 60.5)
    assert schoolzones.distance_km(far_north, 0.0, 60.0) == pytest.approx(55.6, abs=0.1)


def test_the_log_in_the_manifest_and_the_method_note(kit: "Kit") -> None:
    by_year, _, _ = _year_rule(kit, 2016)
    log: Any = perschool.by_year_json(by_year)
    assert log["school_years_by_method"] == {"nearest": 1}
    assert log["schools"] == 1
    (entry,) = log["logged"]
    assert entry == {
        "school": "590006600044",
        "fips": "37173",
        "school_year": "2016-17",
        "zone": "NCZ051",
        "placed": "nearest",
        "inside_another_version_of_its_zone": True,
        "versions": [
            {"version": "iem/NCZ051/531.0424", "distance_km": 0.73, "rows": 9, "taken": True}
        ],
    }
    lines = notes._by_year_lines(log)
    assert lines[-1] == (
        "| 590006600044 | 37173 | NCZ051 | 2016-17 | iem/NCZ051/531.0424 (0.730) | 9 "
        "| nearest, inside another version that year |"
    )
    far, _, _ = _year_rule(kit, 2017, nearest_km=0.5)
    far_lines = notes._by_year_lines(perschool.by_year_json(far))
    assert (
        "| 360010206660 | 36081 | NYZ072 | 2017-18 | iem/NYZ072/61.0158 (0.901), not taken "
        "| 0 | county |"
    ) in far_lines
    assert notes._by_year_lines({}) == []


def test_ncz051_goes_back_and_forth_between_two_outlines(kit: "Kit") -> None:
    by_year, book, _ = _year_rule(kit, 2016)
    cache = kit.cache()
    rows = [row for year in (2015, 2016) for row in archive.load_year(cache, year).rows]
    (found,) = zonepolys.alternating_outlines(rows, book)
    assert [(run.key, run.rows) for run in found.runs] == [
        ("iem/NCZ051/1400.3182", 14),
        ("iem/NCZ051/531.0424", 9),
        ("iem/NCZ051/1400.3182", 1),
    ]
    assert found.largest_difference == pytest.approx(1 - 531.0424 / 1400.3182, abs=1e-6)
    zone_polygons: dict[str, JSONValue] = {"alternating_outlines": [found.as_json()]}
    lines = notes._alternating_lines(zone_polygons, perschool.by_year_json(by_year))
    assert "and more for 1:" in lines[0]
    assert lines[1].startswith(
        "  - NCZ051: outlines 1400.3182 (1400.3 km²), 531.0424 (531.0 km²); its rows in "
        "order: 1400.3182 2016-01 to 2016-03, 531.0424 2016-12 to 2017-03, 1400.3182 2017-04 "
        "to 2017-04. Schools with a school year logged for it below: 1;"
    )
    assert notes.ALTERNATION_NOTES["NCZ051"] in lines[1]
