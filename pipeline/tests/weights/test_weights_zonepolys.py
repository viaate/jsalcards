"""Zone polygons by version: the served releases, the ``area2d`` fingerprint and IEM's copies.

Every file is a real slice (``fixtures/provenance.json``): the two served zone releases
cut to the fixtures' zones, the school-year slices (with the Salt Lake slice of
2019-20) and IEM's full-resolution answers of the requests the plan picks.
"""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from snowlight.sources.nws.boundaries import BoundaryRelease
from snowlight.sources.nws.http import FetchError
from snowlight.weights import archive, zonepolys
from snowlight.weights.archive import EventRow

if TYPE_CHECKING:
    from weights.conftest import Kit

FIXTURES = Path(__file__).parent / "fixtures"
YEAR_FILES = ("iem-2018-2019.csv", "iem-2021-2022.csv", "iem-2024-2025.csv")


def _rows(*names: str) -> list[EventRow]:
    rows: list[EventRow] = []
    for name in names:
        rows.extend(archive.read_rows((FIXTURES / name).read_text(encoding="utf-8"))[0])
    return rows


def _sets(kit: "Kit") -> list[zonepolys.ZoneSet]:
    return [
        zonepolys.read_zone_set(kit.path(f"{release.url.rsplit('/', 1)[-1]}"), release)
        for release in kit.zone_releases()
    ]


def test_equal_area_reproduces_iem_area2d(kit: "Kit") -> None:
    # IEM's area2d for RIZ002's 2024-25 rows is the equal-area size of z_18mr25's polygon.
    shape = _sets(kit)[0].shapes["RIZ002"]
    rows = [row for row in _rows("iem-2024-2025.csv") if row.ugc == "RIZ002"]
    assert rows
    for row in rows:
        assert row.area_km2 is not None
        assert shape.area_km2 == pytest.approx(row.area_km2, rel=1e-6)
    assert zonepolys.same_area(100.0, 100.00005)
    assert not zonepolys.same_area(100.0, 100.001)


def test_read_zone_set(kit: "Kit") -> None:
    reference, later = _sets(kit)
    assert reference.name == "z_18mr25"
    assert later.name == "z_16ap26"
    assert reference.records == kit.zone_releases()[0].records
    assert {"RIZ001", "RIZ002", "UTZ105", "UTZ111", "FLZ173"} <= set(reference.shapes)
    assert reference.shapes["UTZ105"].time_zones == ("M",)
    wrong = replace(kit.zone_releases()[0], records=1)
    with pytest.raises(zonepolys.ZonePolygonError, match="records, the NWS page lists 1"):
        zonepolys.read_zone_set(kit.path("z_18mr25.zip"), wrong)
    with pytest.raises(zonepolys.ZonePolygonError, match="has no STATE/ZONE"):
        zonepolys.read_zone_set(kit.path("c_16ap26.zip"), replace(wrong, records=None))


def test_load_zone_sets_checks_the_listed_md5(kit: "Kit") -> None:
    sets = zonepolys.load_zone_sets(kit.cache(), kit.zone_releases())
    assert [zone_set.name for zone_set in sets] == ["z_18mr25", "z_16ap26"]
    assert sets[0].file is not None
    # The slices are not the files the NWS page lists: their MD5 does not match.
    with pytest.raises(FetchError):
        zonepolys.load_zone_sets(kit.cache(), zonepolys.ZONE_RELEASES)


def test_versions_and_served_matches(kit: "Kit") -> None:
    sets = _sets(kit)
    rows = _rows(*YEAR_FILES)
    versions = zonepolys.versions_of(rows)
    assert sum(versions.values()) == sum(row.ugc[2] == "Z" for row in rows)
    by_ugc = {version.ugc: version for version in versions}
    riz002 = zonepolys.served_match(by_ugc["RIZ002"], sets)
    assert riz002 is not None
    assert riz002[0].name == "z_18mr25"
    assert riz002[1] < zonepolys.AREA_TOLERANCE
    # Tallahassee's zones were redrawn in March 2025: their 2024-25 version is in neither.
    assert zonepolys.served_match(by_ugc["FLZ014"], sets) is None
    laz037 = zonepolys.served_match(by_ugc["LAZ037"], sets)
    assert laz037 is not None
    assert laz037[0].name == "z_16ap26"
    assert by_ugc["RIZ002"].label.startswith("RIZ002/")
    with pytest.raises(zonepolys.ZonePolygonError, match="no area2d"):
        zonepolys.versions_of([replace(rows[0], area_km2=None)])


def test_plan_requests(kit: "Kit") -> None:
    rows = _rows(*YEAR_FILES)
    book = zonepolys.build_book(kit.cache(), rows, _sets(kit), fetch=False)
    assert len(book.unresolved) == 23
    plan = zonepolys.plan_requests(rows, book.unresolved)
    assert [(key.wfo, key.code, f"{key.begin:%Y%m%dT%H%M}") for key in plan] == [
        ("BOX", "WS.W", "20190304T0000"),
        ("LIX", "TR.W", "20210827T2112"),
        ("LIX", "TR.W", "20210830T0929"),
        ("LIX", "TR.W", "20210830T1528"),
        ("MSO", "BZ.W", "20190203T2100"),
        ("TAE", "EC.W", "20250122T0600"),
    ]
    assert plan[0].url.endswith(
        "?accept=shapefile&sts=2019-03-04T00:00Z&ets=2019-03-04T00:01Z&limitps=1"
        "&phenomena=WS&significance=W&location_group=wfo&wfo=BOX&simple=0"
    )
    assert plan[0].path(Path("cache")) == Path(
        "cache/mesonet.agron.iastate.edu/watchwarn-zones/BOX/WS.W/20190304T0000.zip"
    )
    lonely = zonepolys.Version("RIZ099", 1.0)
    with pytest.raises(zonepolys.ZonePolygonError, match="no row to request"):
        zonepolys.plan_requests(rows, [*book.unresolved, lonely])


def test_a_request_across_the_new_year_spans_it() -> None:
    # Synthetic key: an event numbered in 2019 whose row begins on 2 January 2020.
    key = zonepolys.RequestKey("SLC", "WS.W", datetime(2020, 1, 2, 10, 0, tzinfo=UTC), 2019)
    start, end = key.window()
    assert start == datetime(2019, 12, 31, 23, 59, tzinfo=UTC)
    assert end == datetime(2020, 1, 2, 10, 1, tzinfo=UTC)
    assert key.path(Path("c")).name == "20200102T1000-vtec2019.zip"


def test_read_version_file(kit: "Kit") -> None:
    zones = zonepolys.read_version_file(kit.path("iem-zones-SLC-WS.W-20191127T1100.zip"))
    by_ugc = {zone.ugc: zone for zone in zones}
    assert set(by_ugc) == {"UTZ003", "UTZ008"}
    rows = {row.ugc: row for row in _rows("iem-2019-2020-slc.csv")}
    for ugc, zone in by_ugc.items():
        assert zone.area_km2 == rows[ugc].area_km2
        assert zonepolys.equal_area_km2(zone.geometry) == pytest.approx(zone.area_km2, rel=1e-6)
    with pytest.raises(zonepolys.ZonePolygonError, match="lacks an attribute"):
        zonepolys.read_version_file(kit.path("c_16ap26.zip"))
    with pytest.raises(zonepolys.ZonePolygonError):
        zonepolys.read_version_file(kit.path("iem-2019-2020-slc.csv"))


def test_build_book_gives_every_version_a_polygon(kit: "Kit") -> None:
    rows = _rows(*YEAR_FILES)
    cache = kit.cache()
    book = zonepolys.build_book(cache, rows, _sets(kit))
    assert book.unresolved == []
    assert len(book.resolved) == len(zonepolys.versions_of(rows))
    assert book.reference.name == "z_18mr25"
    sources = {item.source for item in book.resolved.values()}
    assert sources == {"z_18mr25", "z_16ap26", "iem"}
    for item in book.resolved.values():
        assert item.area_difference <= zonepolys.AREA_TOLERANCE
        assert (item.file is None) == (item.source != "iem")
    riz = next(row for row in rows if row.ugc == "RIZ002" and row.begin.year == 2024)
    assert book.key_of(riz) == "z_18mr25/RIZ002"
    summary: Any = book.as_json()
    assert summary["versions"] == len(book.resolved)
    assert summary["unresolved"] == []
    assert len(summary["iem_requests"]) == 6
    assert {entry["ugc"] for entry in summary["iem_versions"]} >= {"MTZ043", "FLZ014"}
    hits = sum(kit.server.hits.values())
    zonepolys.build_book(cache, rows, _sets(kit))
    assert sum(kit.server.hits.values()) == hits  # every answer came from the cache
    with pytest.raises(zonepolys.ZonePolygonError, match="no area2d"):
        book.key_of(replace(riz, area_km2=None))
    with pytest.raises(zonepolys.ZonePolygonError, match="has no polygon"):
        book.key_of(replace(riz, area_km2=1.0))


def test_an_answer_without_the_version_leaves_it_unresolved(kit: "Kit") -> None:
    rows = _rows(*YEAR_FILES)
    plan = zonepolys.plan_requests(
        rows, zonepolys.build_book(kit.cache(), rows, _sets(kit), fetch=False).unresolved
    )
    missoula = next(key for key in plan if key.wfo == "MSO")
    # Serve Salt Lake's answer where Missoula's belongs: MTZ043's version is not in it.
    kit.server.files[missoula.url] = kit.bytes("iem-zones-SLC-WS.W-20191127T1100.zip")
    book = zonepolys.build_book(kit.cache(), rows, _sets(kit))
    assert [version.ugc for version in book.unresolved] == ["MTZ043"]
    assert book.as_json()["unresolved"] == [book.unresolved[0].label]


def test_outlines_a_zone_returns_to(kit: "Kit") -> None:
    rows = _rows("iem-2017-2018-outside.csv")
    book = zonepolys.build_book(kit.cache(), rows, _sets(kit))
    assert book.unresolved == []
    # MDZ008's rows of 2017-18: IEM joined the one of 4 January 2018 to an outline of
    # 910.3665 km2, the others (before and after it) to one of 910.3663 km2.
    (found,) = zonepolys.alternating_outlines(rows, book)
    assert found.ugc == "MDZ008"
    assert [(run.key, run.rows) for run in found.runs] == [
        ("iem/MDZ008/910.3663", 2),
        ("iem/MDZ008/910.3665", 1),
        ("iem/MDZ008/910.3663", 8),
    ]
    assert found.runs[1].first == found.runs[1].last == datetime(2018, 1, 4, 2, tzinfo=UTC)
    assert found.largest_difference == pytest.approx(2.7e-7, rel=0.05)
    assert found.largest_difference < zonepolys.MATERIAL
    record: Any = found.as_json()
    assert record["runs"][1] == {
        "version": "iem/MDZ008/910.3665",
        "first": "2018-01-04T02:00Z",
        "last": "2018-01-04T02:00Z",
        "rows": 1,
    }
    assert record["outlines_km2"] == {
        "iem/MDZ008/910.3663": 910.3663,
        "iem/MDZ008/910.3665": 910.3665,
    }
    # NYZ072's rows of the year are joined to one outline: not listed.
    assert zonepolys.alternating_outlines([row for row in rows if row.ugc == "NYZ072"], book) == []


def test_zone_release_listing_matches_the_page() -> None:
    # The pinned releases are the two the NWS page listed (valid dates, MD5, records).
    assert [r.valid_from.isoformat() for r in zonepolys.ZONE_RELEASES] == [
        "2025-03-18",
        "2026-04-16",
    ]
    assert all(r.records for r in zonepolys.ZONE_RELEASES)
    assert all(isinstance(r, BoundaryRelease) for r in zonepolys.ZONE_RELEASES)
