"""The per-school weights end to end: the build on the fixture slices, recounted by hand.

The recount below reads the same real slices without the build's cells or trees: for
each school, every zone row whose version polygon (the served release's or IEM's copy)
covers the school's point, every county row of its county, and every FF.W polygon
covering the point, under the 6 AM rule in the school's time zones.
"""

import json
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import shapely

from snowlight.sources.nws.shapefile import Polygonal
from snowlight.weights import (
    archive,
    build,
    count,
    notes,
    perschool,
    polygons,
    schoolcount,
    schools,
    zonepolys,
)
from snowlight.weights.codes import BY_CODE

if TYPE_CHECKING:
    from weights.conftest import Kit

FIXTURES = Path(__file__).parent / "fixtures"
YEARS = {2018: "iem-2018-2019.csv", 2021: "iem-2021-2022.csv", 2024: "iem-2024-2025.csv"}


def _scope(kit: "Kit") -> build.Scope:
    import hashlib  # noqa: PLC0415

    return build.Scope(
        years=tuple(YEARS),
        releases=kit.releases,
        county_release=kit.county_release(),
        day_windows=(),
        dma_sha256=hashlib.sha256(kit.bytes("usa-tvdma-county.csv")).hexdigest(),
        zone_releases=kit.zone_releases(),
    )


def _paths(kit: "Kit", out: Path) -> build.Paths:
    return build.Paths(
        cache_dir=kit.cache_dir,
        out_dir=out,
        directory=kit.path("schools.parquet"),
        coverage=kit.path("coverage.json"),
        research=kit.path("research"),
        registry=None,
        siblings=(),
    )


def _build(kit: "Kit", out: Path) -> build.Result:
    return build.build(_paths(kit, out), scope=_scope(kit), clock=kit.clock, cache=kit.http())


def _polygon_of(kit: "Kit") -> dict[zonepolys.Version, Polygonal]:
    """Every zone version's polygon, found by hand from the slices."""
    sets = [
        zonepolys.read_zone_set(kit.path(release.url.rsplit("/", 1)[-1]), release)
        for release in kit.zone_releases()
    ]
    archived = [
        zone
        for path in sorted(FIXTURES.glob("iem-zones-*.zip"))
        for zone in zonepolys.read_version_file(path)
    ]
    found: dict[zonepolys.Version, Polygonal] = {}
    for name in YEARS.values():
        rows, _ = archive.read_rows((FIXTURES / name).read_text(encoding="utf-8"))
        for row in rows:
            if row.ugc[2] != "Z" or row.area_km2 is None:
                continue
            version = zonepolys.Version(row.ugc, row.area_km2)
            for zone_set in sets:
                shape = zone_set.shapes.get(row.ugc)
                if shape and abs(shape.area_km2 / row.area_km2 - 1) <= zonepolys.AREA_TOLERANCE:
                    found.setdefault(version, shape.geometry)
            for zone in archived:
                if zone.ugc == row.ugc and zone.area_km2 == row.area_km2:
                    found.setdefault(version, zone.geometry)
    return found


def _recount(kit: "Kit", school: dict[str, Any], point: shapely.Point) -> float:
    polygon_of = _polygon_of(kit)
    zones_of = tuple(school["time_zones"])
    total = 0.0
    for year, name in YEARS.items():
        rows, _ = archive.read_rows((FIXTURES / name).read_text(encoding="utf-8"))
        storms, _ = polygons.read_polygon_file(kit.path(f"iem-polygons-{year}-{year + 1}.zip"))
        with_polygons = {storm.event_key for storm in storms}
        days = frozenset(count.school_days(year))
        best: dict[date, float] = {}
        spans = []
        for row in rows:
            if row.code == "FF.W" and row.event_key in with_polygons:
                continue
            if row.ugc[2] == "Z":
                assert row.area_km2 is not None
                polygon = polygon_of[zonepolys.Version(row.ugc, row.area_km2)]
                if polygon.intersects(point):
                    spans.append((row.begin, row.end, row.product_issued, row.code))
            elif {"RI": "44", "FL": "12"}.get(row.ugc[:2], "") + row.ugc[3:] == school["fips"]:
                spans.append((row.begin, row.end, row.product_issued, row.code))
        spans += [
            (storm.begin, storm.end, storm.product_issued, storm.code)
            for storm in storms
            if storm.geometry.intersects(point)
        ]
        for begin, end, issued, code in spans:
            for day in count.counted_days(begin, end, issued, zones_of) & days:
                best[day] = max(best.get(day, 0.0), BY_CODE[code].weight)
        total += sum(best.values())
    return total / len(YEARS)


def test_every_school_matches_a_recount_by_hand(kit: "Kit", tmp_path: Path) -> None:
    result = _build(kit, tmp_path / "out")
    closure = json.loads((tmp_path / "out" / "closure-weights.json").read_text("utf-8"))
    frame = schools.read_schools(kit.path("schools.parquet"))
    points = {
        school_id: shapely.Point(lon, lat)
        for school_id, lon, lat in zip(frame["id"], frame["lon"], frame["lat"], strict=True)
    }
    records = closure["schools"]
    assert set(records) == set(points) - {"00230442"}  # Litchfield's county is not in the slice
    mean = closure["normalizer"]["school_weighted_mean_days_per_year"]
    for school_id, record in records.items():
        recount = _recount(kit, record, points[school_id])
        assert record["days_per_year"] == pytest.approx(recount, abs=1e-4), school_id
        assert record["weight"] == pytest.approx(recount / mean, abs=1e-3)
        assert record["placed"] == "inside"
        assert "distance_km" not in record
        assert record["years_counted"] == 3
    assert result.per_school is not None
    assert result.per_school.mean == pytest.approx(mean)
    # Providence's schools: the county summary is the mean of its three schools.
    providence = [r for r in records.values() if r["fips"] == "44007"]
    county = next(c for c in closure["counties"] if c["fips"] == "44007")
    assert county["days_per_year"] == pytest.approx(
        sum(r["days_per_year"] for r in providence) / 3, abs=1e-4
    )


def test_state_rows_and_logs(kit: "Kit", tmp_path: Path) -> None:
    result = _build(kit, tmp_path / "out")
    assert result.per_school is not None
    states = {row["state"]: row for row in result.states}
    assert set(states) == {"RI", "FL", "MT", "CT"}
    for row in result.states:
        assert row["county_rule_rank"] in {1, 2, 3, 4}
        assert row["schools_placed"] == {"inside": row["schools"]}
    assert states["RI"]["schools"] == 5
    placement: Any = perschool.placement_json(result.per_school)
    assert placement["placed_by"] == {"inside": 10}
    assert placement["nearest"] == placement["county"] == []
    # Every school of the build's slices is inside its own zone's outline of every year.
    by_year = placement["by_school_year"]
    assert by_year["logged"] == []
    assert by_year["school_years_by_method"] == {}
    assert by_year["nearest_km"] == 2.0
    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text("utf-8"))
    assert manifest["checks"]["zone_polygons"]["alternating_outlines"] == []
    counting: Any = perschool.counting_json(result.per_school)
    assert counting["zone_rows"] == counting["zone_rows_reaching_schools"] + (
        counting["zone_rows"] - counting["zone_rows_reaching_schools"]
    )
    by_source = counting["zone_rows_by_school_year_and_polygon_source"]
    assert set(by_source) == {"2018-19", "2021-22", "2024-25"}
    method = (tmp_path / "out" / "method.md").read_text(encoding="utf-8")
    for heading in (
        "## Each school in its own forecast zone",
        "### Where each school is",
        "### County-coded products and storm-based polygons",
        "### The places named, under both rules",
        "### Largest changes (counties with at least 20 schools)",
        "## For the station builders: reading per-school weights",
        "## The county rule (kept for comparison and the whole-county diagnostic)",
    ):
        assert heading in method
    assert "| Providence County, RI (44007) | 3 |" in method
    assert "Logged: 0 school years of 0 schools (none)" in method
    assert '`data["schools"]`' in method


def test_per_school_failures_stop_the_build(
    kit: "Kit", tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [
        row
        for name in YEARS.values()
        for row in archive.read_rows((FIXTURES / name).read_text(encoding="utf-8"))[0]
    ]
    sets = zonepolys.load_zone_sets(kit.cache(), kit.zone_releases())
    plan = zonepolys.plan_requests(
        rows, zonepolys.build_book(kit.cache(), rows, sets, fetch=False).unresolved
    )
    missoula = next(key for key in plan if key.wfo == "MSO")
    good = kit.server.files[missoula.url]
    kit.server.files[missoula.url] = kit.bytes("iem-zones-SLC-WS.W-20191127T1100.zip")
    with pytest.raises(build.WeightsBuildError, match="zone versions with no polygon"):
        _build(kit, tmp_path / "one")
    kit.server.files[missoula.url] = good
    kit.cache_dir = tmp_path / "fresh-cache"  # the bad answer is cached as final
    real = archive.read_rows

    def with_a_tornado(text: str, *args: Any) -> Any:
        found, stats = real(text, *args)
        stats.polygon_events["BOX.TO.W.0001.2024"] += 1
        return found, stats

    monkeypatch.setattr(archive, "read_rows", with_a_tornado)
    with pytest.raises(build.WeightsBuildError, match="codes not read as polygons"):
        _build(kit, tmp_path / "two")


def test_provisional_polygon_files_stop_the_build(kit: "Kit", tmp_path: Path) -> None:
    kit.now = kit.now.replace(year=2025, month=6, day=25)
    scope = replace(_scope(kit), years=(2024,), releases=("bp05mr24", "bp10se24"))
    paths = _paths(kit, tmp_path / "out")
    with pytest.raises(build.WeightsBuildError, match="still provisional"):
        build.build(paths, scope=scope, clock=kit.clock, cache=kit.http())


def test_recount_check(kit: "Kit", tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _build(kit, tmp_path / "out")
    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text("utf-8"))
    recount = manifest["checks"]["school_recount"]
    assert recount["schools"] == recount["agree"] == 4  # one school of each of four states
    assert "4 of 4 schools" in (tmp_path / "out" / "method.md").read_text("utf-8")
    real = schoolcount.recount
    wrong = schoolcount.Recounted(99.0, {}, frozenset(), (2018, 2021, 2024))
    monkeypatch.setattr(schoolcount, "recount", lambda *_args, **_kwargs: wrong)
    with pytest.raises(build.WeightsBuildError, match=r"recounted 99\.0"):
        _build(kit, tmp_path / "again")

    def with_a_version(*args: Any, **kwargs: Any) -> schoolcount.Recounted:
        found = real(*args, **kwargs)
        return replace(found, by_year_rows={2018: frozenset({"z_18mr25/RIZ002"})})

    monkeypatch.setattr(schoolcount, "recount", with_a_version)
    with pytest.raises(build.WeightsBuildError, match="school-year versions differ"):
        _build(kit, tmp_path / "third")


def test_school_tables_need_one_weight_per_school() -> None:
    with pytest.raises(build.WeightsBuildError, match="differ in number"):
        build.school_tables(schools.Placement(schools=[]), [1.0], {})


def test_named_counties_are_real_fips_codes() -> None:
    assert all(len(fips) == 5 and fips.isdigit() for fips, _ in notes.NAMED_COUNTIES)
