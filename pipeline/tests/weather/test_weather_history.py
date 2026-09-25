"""Tests for the IEM archive reader and the weather check for past dates, on real rows."""

import json
import struct
import zipfile
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from shapely.geometry import Point

from snowlight.sources.nws.http import NotFoundError
from snowlight.sources.nws.iem import (
    SIMPLIFIED_TOLERANCE,
    WATCHWARN_URL,
    ArchiveFormatError,
    ArchiveRow,
    Freshness,
    IemArchive,
    day_url,
    range_url,
    read_day_file,
)
from snowlight.sources.nws.shapefile import read_dbf
from snowlight.weather.build import archive_codes, archive_window, make_archive
from snowlight.weather.hazards import CONUS_STATES
from snowlight.weather.history import ArchiveLoad, CarriedEvent, WarningHistory
from snowlight.weather.index import AlertMatch, WeatherIndex
from snowlight.weather.timezones import LocalWindow

if TYPE_CHECKING:
    from weather.conftest import Kit

FIXTURES = Path(__file__).parent / "fixtures"
NEW_ORLEANS = (29.9511, -90.0715)  # lat, lon of New Orleans City Hall
TOL = SIMPLIFIED_TOLERANCE


def _history(kit: "Kit", lookback_days: int = 21) -> WarningHistory:
    cache = kit.cache()
    return WarningHistory(
        make_archive(cache, kit.cache_dir), kit.catalog(cache), timedelta(days=lookback_days)
    )


def _polygon_begin(row: ArchiveRow) -> datetime:
    begin = row.polygon_begin or row.issued
    assert begin is not None
    return begin


def _day_window(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    return start, start + timedelta(days=1)


def test_day_url_asks_for_one_day_of_allowlisted_events() -> None:
    url = day_url(date(2025, 1, 21), [("WS", "W"), ("CW", "Y"), ("WS", "W")], ["TX", "DC"])
    assert url.startswith(WATCHWARN_URL + "?accept=shapefile&")
    assert "sts=2025-01-21T00:00Z&ets=2025-01-22T00:00Z" in url
    assert "phenomena=CW,WS&significance=Y,W" in url
    assert "location_group=states&states=DC,TX" in url
    assert url.endswith("&simple=1&addsvs=1")
    with pytest.raises(ValueError, match="at least one"):
        day_url(date(2025, 1, 21), [], ["TX"])


def test_reads_real_archive_rows() -> None:
    rows = read_day_file(FIXTURES / "iem-2024-05-21.zip")
    assert {row.event_key for row in rows} == {"DMX.TO.W.0034.2024", "ARX.TO.A.0277.2024"}
    rows = [row for row in rows if row.event_key == "DMX.TO.W.0034.2024"]
    polygons = sorted((r for r in rows if r.gtype == "P"), key=_polygon_begin)
    assert [(r.status, r.polygon_begin, r.polygon_end) for r in polygons] == [
        (
            "NEW",
            datetime(2024, 5, 21, 12, 24, tzinfo=UTC),
            datetime(2024, 5, 21, 12, 31, tzinfo=UTC),
        ),
        (
            "CON",
            datetime(2024, 5, 21, 12, 31, tzinfo=UTC),
            datetime(2024, 5, 21, 12, 37, tzinfo=UTC),
        ),
        (
            "CON",
            datetime(2024, 5, 21, 12, 37, tzinfo=UTC),
            datetime(2024, 5, 21, 12, 58, tzinfo=UTC),
        ),
        (
            "EXP",
            datetime(2024, 5, 21, 12, 58, tzinfo=UTC),
            datetime(2024, 5, 21, 13, 0, tzinfo=UTC),
        ),
    ]
    counties = sorted(r.ugc or "" for r in rows if r.gtype == "C")
    assert counties == ["IAC001", "IAC029"]
    first = polygons[0]
    assert (first.wfo, first.phenomena, first.significance, first.etn) == ("DMX", "TO", "W", 34)
    assert first.issued == datetime(2024, 5, 21, 12, 24, tzinfo=UTC)
    assert first.expired == datetime(2024, 5, 21, 13, 0, tzinfo=UTC)
    assert first.product_id == "202405211224-KDMX-WFUS53-TORDMX"


def _mutated(tmp_path: Path, field: str, value: bytes) -> Path:
    """A copy of a real day file with one field of its first record overwritten."""
    source = FIXTURES / "iem-2024-05-21.zip"
    with zipfile.ZipFile(source) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    dbf_name = next(name for name in members if name.endswith(".dbf"))
    dbf = bytearray(members[dbf_name])
    fields, _rows = read_dbf(bytes(dbf))
    header_len = struct.unpack_from("<H", dbf, 8)[0]
    offset = header_len + 1
    for item in fields:
        if item.name == field:
            dbf[offset : offset + item.length] = value.ljust(item.length)
            break
        offset += item.length
    members[dbf_name] = bytes(dbf)
    path = tmp_path / f"{field}.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return path


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("GTYPE", b"X", "GTYPE 'X'"),
        ("NWS_UGC", b"IAC001", "GTYPE 'P' with NWS_UGC 'IAC001'"),
        ("ISSUED", b"2024-05-21", "not YYYYMMDDHHMM"),
        ("ETN", b"3.5", "not a whole number"),
    ],
)
def test_malformed_rows_are_errors(tmp_path: Path, field: str, value: bytes, message: str) -> None:
    with pytest.raises(ArchiveFormatError, match=message):
        read_day_file(_mutated(tmp_path, field, value))


def test_unreadable_day_files_are_errors(tmp_path: Path) -> None:
    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"not a zip")
    with pytest.raises(ArchiveFormatError, match="not a zip"):
        read_day_file(broken)


def test_archive_fetches_caches_and_finalises_day_files(kit: "Kit") -> None:
    day = date(2026, 1, 26)
    url = day_url(day, archive_codes(), CONUS_STATES)
    kit.clock.now = datetime(2026, 1, 28, 12, tzinfo=UTC)
    with kit.cache() as cache:
        archive = make_archive(cache, kit.cache_dir)
        first = archive.day(day)
        assert first.final is False
        assert archive.path_for(day) == first.file.path
        assert first.file.path.name == "2026-01-26.zip"
        assert archive.day(day) is first
        archive.evict(date(2026, 1, 27))
        kit.clock.now += timedelta(minutes=30)
        assert archive.day(day).file.downloaded is False
        archive.evict(date(2026, 1, 27))
        kit.clock.now += timedelta(hours=2)
        refreshed = archive.day(day)
        assert refreshed.file.downloaded is True
        assert refreshed.final is False
        archive.evict(date(2026, 1, 27))
        kit.clock.now = datetime(2026, 3, 1, tzinfo=UTC)
        final = archive.day(day)
        assert final.final is True
        archive.evict(date(2026, 1, 27))
        kit.clock.now = datetime(2026, 9, 1, tzinfo=UTC)
        assert archive.day(day).file.downloaded is False
        with pytest.raises(ValueError, match="has not started"):
            archive.day(date(2026, 9, 2))
    assert kit.server.hits[url] == 3
    assert len(final.rows) == len(read_day_file(FIXTURES / "iem-2026-01-26.zip"))


def test_custom_freshness(kit: "Kit") -> None:
    day = date(2026, 1, 26)
    kit.clock.now = datetime(2026, 1, 28, tzinfo=UTC)
    with kit.cache() as cache:
        archive = IemArchive(
            cache, kit.cache_dir, archive_codes(), CONUS_STATES, Freshness(timedelta(days=1))
        )
        assert archive.day(day).final is True


def test_days_for_covers_the_lookback_and_stops_today(kit: "Kit") -> None:
    history = _history(kit, lookback_days=2)
    start, end = _day_window(date(2025, 1, 21))
    # The lookback, and one day more for begin times that precede their product.
    assert history.days_for(start, end) == [
        date(2025, 1, 18),
        date(2025, 1, 19),
        date(2025, 1, 20),
        date(2025, 1, 21),
    ]
    kit.clock.now = datetime(2025, 1, 21, 6, tzinfo=UTC)
    assert history.days_for(start, end + timedelta(days=3))[-1] == date(2025, 1, 21)
    with pytest.raises(ValueError, match="end after it starts"):
        history.days_for(end, start)


def _single_day(kit: "Kit", day: date) -> WarningHistory:
    history = _history(kit)
    history.archive.day(day)  # only this day is served; the lookback days are not needed
    return history


def test_zone_rows_before_the_earliest_release_use_the_archive_outline(kit: "Kit") -> None:
    history = _single_day(kit, date(2025, 1, 21))
    days = [history.archive.day(date(2025, 1, 21))]
    index_areas = history.areas(days)
    keys = {area.alert.key for area in index_areas}
    assert keys == {
        "vtec:CRP.WS.W.0001.2025",
        "vtec:HGX.CW.Y.0004.2025",
        "vtec:HGX.WS.W.0001.2025",
        "vtec:LIX.CW.Y.0005.2025",
        "vtec:LIX.WS.W.0001.2025",
    }
    never = {"LIX.WS.A.0001.2025", "JAX.FL.W.0001.2025"}  # upgraded, cancelled before begin
    expected = sum(1 for row in days[0].rows if row.event_key in never)
    assert expected > 3
    assert history.skipped["event never in effect"] == expected
    zones = [area for area in index_areas if area.basis == "zone"]
    assert {area.precision for area in zones} == {"approximate"}
    assert {area.tolerance for area in zones} == {SIMPLIFIED_TOLERANCE}
    # The hint is the same UGC in the earliest NWS release still served (z_18mr25).
    earliest = history.catalog.load(history.catalog.releases("zone")[0])
    orleans = [area for area in zones if area.trace.endswith(" LAZ077")]
    assert orleans
    assert all(area.hint is earliest.areas["LAZ077"] for area in orleans)
    # Rows of one UGC share one outline object.
    assert len({id(area.geometry) for area in orleans}) == 1
    assert history.outlines["approximate rows with an NWS hint"] > 0
    index = WeatherIndex(index_areas)
    lat, lon = NEW_ORLEANS
    local_day = (datetime(2025, 1, 21, 6, tzinfo=UTC), datetime(2025, 1, 22, 6, tzinfo=UTC))
    hits = index.check(county_fips="22071", lat=lat, lon=lon, start=local_day[0], end=local_day[1])
    assert [(m.alert.event, m.coverage, m.basis, m.precision) for m in hits] == [
        ("Cold Weather Advisory", "covered", "zone", "approximate"),
        ("Winter Storm Warning", "covered", "zone", "approximate"),
    ]
    assert hits[0].traces == (
        "archive day 2025-01-21 row 17 (202501180926-KLIX-WWUS74-NPWLIX) LAZ077",
    )
    storm = hits[1]
    assert (storm.start, storm.end) == (
        datetime(2025, 1, 21, 6, tzinfo=UTC),
        datetime(2025, 1, 22, 0, 33, tzinfo=UTC),
    )


def test_zone_rows_use_the_nws_release_in_effect(kit: "Kit") -> None:
    day = date(2026, 1, 26)
    history = _single_day(kit, day)
    index = WeatherIndex(history.areas([history.archive.day(day)]))
    zones = history.catalog.boundaries_for("zone", day)
    assert zones is not None
    maine = zones.areas["MEZ008"].representative_point()
    start, end = _day_window(day)
    [storm] = index.check(county_fips=None, lat=maine.y, lon=maine.x, start=start, end=end)
    assert (storm.alert.key, storm.basis, storm.precision) == (
        "vtec:GYX.WS.W.0001.2026",
        "zone",
        "exact",
    )
    upgraded = zones.areas["MEZ002"].representative_point()
    assert not index.check(county_fips=None, lat=upgraded.y, lon=upgraded.x, start=start, end=end)


def test_river_flood_polygons_decide_over_their_counties(kit: "Kit") -> None:
    day = date(2026, 1, 26)
    history = _single_day(kit, day)
    areas = history.areas([history.archive.day(day)])
    index = WeatherIndex(areas)
    flood = [a for a in areas if a.alert.key == "vtec:BMX.FL.W.0001.2026"]
    polygons = [a for a in flood if a.basis == "polygon"]
    assert polygons
    assert all(a.point_matching for a in polygons)
    assert {a.basis for a in flood if not a.point_matching} == {"county"}
    inside = polygons[0].geometry
    assert inside is not None
    point = inside.representative_point()
    start = polygons[0].start
    window = {"start": start, "end": start + timedelta(hours=1)}
    [hit] = index.check(county_fips="01063", lat=point.y, lon=point.x, **window)
    assert hit.basis == "polygon"
    # A school in Greene County (ALC063) away from the river: the polygon says no.
    county = history.catalog.lookup("ALC063", day)[0]
    assert county is not None
    outside = county.difference(inside.buffer(0.05)).representative_point()
    assert not index.check(county_fips="01063", lat=outside.y, lon=outside.x, **window)
    # Without a point, the county rows answer.
    assert index.check(county_fips="01063", lat=None, lon=None, **window)


def test_tornado_polygon_versions_follow_the_warning_as_it_shrinks(kit: "Kit") -> None:
    day = date(2024, 5, 21)
    history = _single_day(kit, day)
    areas = history.areas([history.archive.day(day)])
    polygons = sorted((a for a in areas if a.basis == "polygon"), key=lambda a: a.start)
    first, last = polygons[0].geometry, polygons[-1].geometry
    assert first is not None
    assert last is not None
    dropped_part = first.difference(last)
    assert not dropped_part.is_empty
    point = dropped_part.representative_point()
    index = WeatherIndex(areas)
    early = datetime(2024, 5, 21, 12, 25, tzinfo=UTC)
    late = datetime(2024, 5, 21, 12, 59, tzinfo=UTC)
    minute = timedelta(minutes=1)
    assert index.check(
        county_fips="19001", lat=point.y, lon=point.x, start=early, end=early + minute
    )
    assert not index.check(
        county_fips="19001", lat=point.y, lon=point.x, start=late, end=late + minute
    )
    counties = [a for a in areas if a.basis == "county" and a.alert.key.endswith("TO.W.0034.2024")]
    assert sorted(fips for a in counties for fips in a.counties) == ["19001", "19029"]
    assert not any(a.point_matching for a in counties)


def test_check_loads_the_days_it_needs(kit: "Kit") -> None:
    history = _history(kit, lookback_days=0)
    start, end = _day_window(date(2026, 1, 26))
    kit.serve_days_without_rows(date(2026, 1, 25), date(2026, 1, 25))
    kit.serve_days_without_rows(date(2026, 1, 26), date(2026, 1, 26))  # its snapshot
    zones = history.catalog.boundaries_for("zone", date(2026, 1, 26))
    assert zones is not None
    maine = zones.areas["MEZ009"].representative_point()
    # The day after is not served: the fake server answers 404, which is an error.
    with pytest.raises(NotFoundError, match="HTTP 404"):
        history.check(
            county_fips=None, lat=maine.y, lon=maine.x, start=start, end=end + timedelta(hours=1)
        )
    hits = history.check(county_fips=None, lat=maine.y, lon=maine.x, start=start, end=end)
    assert [m.alert.event for m in hits] == ["Winter Storm Warning"]


def test_rows_that_cannot_be_placed_are_skipped_and_counted(kit: "Kit") -> None:
    """Synthetic variants of real rows, one defect each."""
    history = _history(kit)
    day = history.archive.day(date(2024, 5, 21))
    polygon = next(row for row in day.rows if row.gtype == "P")
    county = next(row for row in day.rows if row.gtype == "C")
    marine = replace(polygon, phenomena="MA")
    no_geometry = replace(polygon, geometry=None)
    zone_of_polygon_event = replace(county, ugc="IAZ047")
    no_county_code = replace(county, ugc="IAC999")
    foreign = replace(county, etn=99, ugc="PRC001")
    no_times = replace(county, etn=98, issued=None)
    unknown_zone = replace(county, etn=97, ugc="IAZ999", geometry=None)
    fake = replace(day, rows=(marine, no_geometry, polygon, zone_of_polygon_event, no_county_code))
    others = replace(
        day, rows=(foreign, no_times, unknown_zone, replace(no_times, issued=county.issued))
    )
    areas = history.areas([fake, others])
    assert history.skipped == {
        "code not on the allowlist": 1,
        "polygon version never in effect or without geometry": 1,
        "county/zone row without a boundary or county code": 2,
        "county/zone row outside the contiguous states or without times": 2,
    }
    assert [(a.alert.key, a.basis) for a in areas] == [
        ("vtec:DMX.TO.W.0034.2024", "polygon"),
        ("vtec:DMX.TO.W.0098.2024", "county"),
    ]


# The schools below are real NCES rows (fixtures/nces-schools.json, sliced from the
# EDGE geocode files the directory is built from; see provenance.json).
SCHOOLS = {s["id"]: s for s in json.loads((FIXTURES / "nces-schools.json").read_text())}
LAKE_CASTLE, LEE_HS, IMPACT_HS = "00541083", "482115002117", "482115012492"
EINSTEIN = "220028300858"
RICEVILLE, FAIRBANK = "192415001409", "192976001693"
# 2025-01-21 as a local day in Louisiana and Texas.
CENTRAL_DAY = (datetime(2025, 1, 21, 6, tzinfo=UTC), datetime(2025, 1, 22, 6, tzinfo=UTC))


def _school(school_id: str) -> tuple[str, float, float]:
    school = SCHOOLS[school_id]
    return str(school["county_fips"]), float(school["lat"]), float(school["lon"])


def _check(
    index: WeatherIndex, school_id: str, window: tuple[datetime, datetime]
) -> list[AlertMatch]:
    fips, lat, lon = _school(school_id)
    return index.check(county_fips=fips, lat=lat, lon=lon, start=window[0], end=window[1])


def _winter_index(kit: "Kit") -> tuple[WarningHistory, WeatherIndex]:
    history = _history(kit)
    days = [history.archive.day(date(2025, 1, 21)), history.archive.day(date(2025, 1, 22))]
    known = history.known_counties(date(2025, 1, 21))
    return history, WeatherIndex(history.areas(days), known_counties=known)


def _full_rows(ugc: str) -> list[ArchiveRow]:
    return [row for row in read_day_file(FIXTURES / "iem-full-2025-01-21.zip") if row.ugc == ugc]


@pytest.mark.parametrize(
    ("school_id", "office", "ugc"),
    [(LAKE_CASTLE, "LIX", "LAZ077"), (LEE_HS, "HGX", "TXZ313"), (IMPACT_HS, "HGX", "TXZ313")],
)
def test_schools_just_outside_a_simplified_outline_are_uncertain_not_missed(
    kit: "Kit", school_id: str, office: str, ugc: str
) -> None:
    """Round 1 reported no alert for these three schools on 2025-01-21.

    IEM's point query puts all three under their office's Winter Storm Warning,
    Cold Weather Advisory and Extreme Cold Warning. IEM's simplified outline of
    their zone misses them by 30 to 180 m; the full-resolution boundary and the
    NWS z_18mr25 zone contain them.
    """
    history, index = _winter_index(kit)
    _fips, lat, lon = _school(school_id)
    point = Point(lon, lat)
    outline = next(a.geometry for a in index.areas if a.trace.endswith(f" {ugc}"))
    assert outline is not None
    assert not outline.intersects(point)
    assert outline.distance(point) < SIMPLIFIED_TOLERANCE
    assert all(row.geometry is not None and row.geometry.covers(point) for row in _full_rows(ugc))
    hint = history.catalog.load(history.catalog.releases("zone")[0]).areas[ugc]
    assert hint.covers(point)
    matches = _check(index, school_id, CENTRAL_DAY)
    advisory = {"LIX": "CW.Y.0005", "HGX": "CW.Y.0004"}[office]
    events = [f"vtec:{office}.{code}.2025" for code in (advisory, "EC.W.0001", "WS.W.0001")]
    assert sorted((m.alert.key, m.coverage, m.basis, m.precision) for m in matches) == [
        (key, "uncertain", "zone", "approximate") for key in events
    ]


def test_a_school_on_the_edge_between_two_warned_zones_is_covered(kit: "Kit") -> None:
    """Einstein Charter School sits on the LAZ077/LAZ078 line: near each outline, inside both."""
    index = _winter_index(kit)[1]
    _fips, lat, lon = _school(EINSTEIN)
    point = Point(lon, lat)
    storm = [a for a in index.areas if a.alert.key == "vtec:LIX.WS.W.0001.2025"]
    assert {a.trace.rsplit(" ", 1)[1] for a in storm} == {"LAZ077", "LAZ078"}
    assert all(a.geometry is not None and a.geometry.boundary.distance(point) < TOL for a in storm)
    matches = _check(index, EINSTEIN, CENTRAL_DAY)
    assert [(m.alert.event, m.coverage) for m in matches] == [
        ("Cold Weather Advisory", "covered"),
        ("Winter Storm Warning", "covered"),
        ("Extreme Cold Warning", "covered"),
    ]
    [storm_match] = [m for m in matches if m.alert.key == "vtec:LIX.WS.W.0001.2025"]
    assert [trace.rsplit(" ", 1)[1] for trace in storm_match.traces] == ["LAZ078", "LAZ077"]
    # The full-resolution boundaries agree: the school is in one of the two zones.
    full = [row.geometry for ugc in ("LAZ077", "LAZ078") for row in _full_rows(ugc)]
    assert any(geometry is not None and geometry.covers(point) for geometry in full)


def test_the_hint_catches_a_sliver_the_outline_dropped(kit: "Kit") -> None:
    """IEM's 2025-01-21 outline of TXZ231 drops a sliver at its southern tip.

    A point there is 0.0118 degrees from the outline, beyond the tolerance, yet
    inside the full-resolution boundary; the NWS zone (the hint) has the sliver.
    """
    history, index = _winter_index(kit)
    [row] = _full_rows("TXZ231")
    area = next(a for a in index.areas if a.trace.endswith(" TXZ231"))
    assert row.geometry is not None
    assert area.geometry is not None
    assert area.hint is not None
    dropped = row.geometry.difference(area.geometry.buffer(SIMPLIFIED_TOLERANCE, quad_segs=64))
    point = dropped.intersection(area.hint).representative_point()
    assert area.geometry.distance(point) > SIMPLIFIED_TOLERANCE
    assert row.geometry.covers(point)
    window = (area.start, area.start + timedelta(hours=1))
    matches = index.check(
        county_fips=None, lat=point.y, lon=point.x, start=window[0], end=window[1]
    )
    assert [(m.alert.key, m.coverage) for m in matches] == [
        ("vtec:CRP.WS.W.0001.2025", "uncertain")
    ]
    # Without the hint the band alone would have said "no alert".
    bare = WeatherIndex([replace(a, hint=None) for a in index.areas if a is area])
    assert not bare.check(
        county_fips=None, lat=point.y, lon=point.x, start=window[0], end=window[1]
    )
    assert history.outlines["distinct outlines on the 0.01 degree grid"] > 0


def test_county_codes_decide_for_approximate_county_rows(kit: "Kit") -> None:
    """ARX Tornado Watch 277 (2024-05-21) was issued by county, before any NWS county release.

    Riceville's schools are in Howard County (IAC089) but just outside IEM's
    outline of it; Fairbank Elementary is in Buchanan County, which that watch
    segment did not name, but inside IEM's outline of Fayette County (IAC065).
    """
    history = _single_day(kit, date(2024, 5, 21))
    areas = history.areas([history.archive.day(date(2024, 5, 21))])
    watch = [a for a in areas if a.alert.key == "vtec:ARX.TO.A.0277.2024"]
    assert sorted((a.trace.rsplit(" ", 1)[1], sorted(a.counties)) for a in watch) == [
        ("IAC065", ["19065"]),
        ("IAC089", ["19089"]),
    ]
    assert {a.precision for a in watch} == {"approximate"}
    known = history.known_counties(date(2024, 5, 21))
    assert {"19089", "19065", "19019"} <= known
    window = (watch[0].start, watch[0].start + timedelta(hours=1))
    howard = next(a.geometry for a in watch if "19089" in a.counties)
    fayette = next(a.geometry for a in watch if "19065" in a.counties)
    assert howard is not None
    assert fayette is not None
    _fips, lat, lon = _school(RICEVILLE)
    assert not howard.intersects(Point(lon, lat))
    _fips, lat, lon = _school(FAIRBANK)
    assert fayette.intersects(Point(lon, lat))

    index = WeatherIndex(areas, known_counties=known)
    [riceville] = [
        m for m in _check(index, RICEVILLE, window) if m.alert.key.startswith("vtec:ARX")
    ]
    assert (riceville.coverage, riceville.basis, riceville.precision) == (
        "covered",
        "county",
        "exact",
    )
    assert not [m for m in _check(index, FAIRBANK, window) if m.alert.key.startswith("vtec:ARX")]
    # Without county codes, both schools are near an outline: uncertain.
    outlines_only = WeatherIndex(areas)
    for school_id in (RICEVILLE, FAIRBANK):
        answers = {(m.alert.key, m.coverage) for m in _check(outlines_only, school_id, window)}
        assert ("vtec:ARX.TO.A.0277.2024", "uncertain") in answers


# Events in effect since before the day files (round 3). Round 2 read only day
# files from 21 days back, so these real places got no row on 2024-05-21.
CHAMBERS = ("48071", 29.875, -94.755)  # the point the round 2 review checked
FLETCHER, ST_ANTHONY, CALHOUN_HS = "480967004642", "01323483", "171818002089"
DEWEYVILLE, LAMOILLE_UHS = "481701001472", "500039700171"
HGX_52, LCH_35, LCH_55, LSX_47 = (
    "HGX.FL.W.0052.2024",
    "LCH.FL.W.0035.2024",
    "LCH.FL.W.0055.2024",
    "LSX.FL.W.0047.2024",
)
BTV_10 = "BTV.WS.W.0010.2024"


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def _local_day(kit: "Kit", day: date) -> tuple[WarningHistory, datetime, datetime]:
    """A history and the archive window of local ``day``; unexamined files are served empty."""
    history = _history(kit)
    start, end = archive_window(LocalWindow(day))
    days = history.days_for(start, end)
    kit.serve_days_without_rows(days[0], days[-1])
    return history, start, end


def test_river_flood_warnings_in_effect_for_weeks_are_found(kit: "Kit") -> None:
    """HGX Flood Warning 52 (Trinity River) covered the round 2 point from 02:30 UTC.

    IEM's point-in-time listing at 2024-05-21 12:00 UTC has that warning in
    effect since 2024-04-29 with a polygon over the point from 02:30 to 15:01;
    LCH 55 covered Beaumont's Fletcher El and St Anthony, LSX 47 Calhoun High
    School in Hardin, IL, and LCH 35, 41 days old, Deweyville El.
    """
    history, start, end = _local_day(kit, date(2024, 5, 21))
    load = history.load(start, end)
    assert load.days[0].day == date(2024, 4, 29)
    assert [snapshot.at for snapshot in load.snapshots] == [_utc(2024, 4, 30)]
    assert sorted(load.carried) == [HGX_52, LCH_35, LCH_55, LSX_47]
    assert [source.label for source in load.ranges] == [
        "range HGX.FL.W 2024-04-01..2024-06-01",
        "range LCH.FL.W 2024-04-01..2024-06-01",
        "range LSX.FL.W 2024-04-01..2024-06-01",
    ]
    # Listed but not carried: ended before the day (LCH 63, CYS 21), Alaska, fire weather.
    assert set(history.carried) == {HGX_52, LCH_35, LCH_55, LSX_47}
    sabine = history.carried[LCH_35]
    assert sabine.first == _utc(2024, 4, 10, 14, 14)
    assert (start - sabine.first).days > 30  # beyond IEM's 30-day point-in-time lookup
    assert sabine.reasons == ("in effect before the day files and during the window",)

    index = history.index(start, end)
    places = {"chambers": CHAMBERS} | {
        school: _school(school) for school in (FLETCHER, ST_ANTHONY, CALHOUN_HS, DEWEYVILLE)
    }
    expected = {
        "chambers": (HGX_52, _utc(2024, 5, 21, 2, 30), _utc(2024, 5, 22, 19, 3)),
        FLETCHER: (LCH_55, _utc(2024, 5, 21, 1, 30), _utc(2024, 5, 22, 15, 29)),
        ST_ANTHONY: (LCH_55, _utc(2024, 5, 21, 1, 30), _utc(2024, 5, 22, 15, 29)),
        CALHOUN_HS: (LSX_47, _utc(2024, 5, 21, 0, 55), _utc(2024, 5, 22, 14, 38)),
        DEWEYVILLE: (LCH_35, _utc(2024, 5, 21, 1, 30), _utc(2024, 5, 22, 15, 29)),
    }
    for name, (fips, lat, lon) in places.items():
        [match] = index.check_local(
            county_fips=fips,
            lat=lat,
            lon=lon,
            window=LocalWindow(date(2024, 5, 21)),
            zone="America/Chicago",
        )
        key, begins, ends = expected[name]
        assert (match.alert.key, match.alert.event) == (f"vtec:{key}", "Flood Warning")
        assert (match.coverage, match.basis, match.precision) == ("covered", "polygon", "exact")
        assert (match.start, match.end) == (begins, ends)
        assert all(trace.startswith("archive range ") for trace in match.traces)
    # The version in force at 12:00 UTC is IEM's 02:30-15:01 polygon, over the point.
    noon = _utc(2024, 5, 21, 12)
    [in_force] = [
        area
        for area in index.areas
        if area.alert.key == f"vtec:{HGX_52}"
        and area.basis == "polygon"
        and area.start <= noon
        and (area.end is None or noon < area.end)
    ]
    assert (in_force.start, in_force.end) == (_utc(2024, 5, 21, 2, 30), _utc(2024, 5, 21, 15, 1))
    assert in_force.geometry is not None
    assert in_force.geometry.covers(Point(CHAMBERS[2], CHAMBERS[1]))


def test_a_warning_numbered_in_the_previous_year_is_found(kit: "Kit") -> None:
    """BTV Winter Storm Warning 10 was issued on 2024-12-31 for 2025-01-01.

    IEM files it under 2024 and answers the 2025-01-01 day file from its 2025
    table, so that file has none of its rows (69 rows, none of BTV's): round 2
    reported nothing for Lamoille Union High School that day.
    """
    history, start, end = _local_day(kit, date(2025, 1, 1))
    load = history.load(start, end)
    assert [snapshot.at for snapshot in load.snapshots] == [_utc(2024, 12, 11), _utc(2025, 1, 1)]
    assert list(load.carried) == [BTV_10]
    [source] = load.ranges
    # From December 2024: a range across two years is answered from every year's table.
    assert (source.first, source.end) == (date(2024, 12, 1), date(2025, 2, 1))
    assert history.carried[BTV_10].reasons == ("numbered in 2024, listed in 2025",)
    assert set(history.carried) == {BTV_10}  # not the Alaska advisory nor the marine one
    index = history.index(start, end)
    fips, lat, lon = _school(LAMOILLE_UHS)
    [match] = index.check_local(
        county_fips=fips,
        lat=lat,
        lon=lon,
        window=LocalWindow(date(2025, 1, 1)),
        zone="America/New_York",
    )
    assert (match.alert.key, match.coverage, match.basis, match.precision) == (
        f"vtec:{BTV_10}",
        "covered",
        "zone",
        "approximate",
    )
    assert (match.start, match.end) == (_utc(2025, 1, 1, 6), _utc(2025, 1, 3, 2, 35))
    assert match.traces == (
        "archive range BTV.WS.W 2024-12-01..2025-02-01 row 1 "
        "(202412312031-KBTV-WWUS41-WSWBTV) VTZ006",
    )
    # What the fixture generator checked in the real day file, kept in provenance.json.
    provenance = json.loads((FIXTURES / "provenance.json").read_text())
    absent = provenance["iem-range-BTV-WS.W-2024-12-01_2025-02-01.zip"]["absent_from_day_file"]
    assert (absent["day"], absent["event"], absent["rows"]) == ("2025-01-01", BTV_10, 69)
    assert absent["source_url"] == day_url(date(2025, 1, 1), archive_codes(), CONUS_STATES)


def test_snapshot_times(kit: "Kit") -> None:
    history = _history(kit)
    kit.clock.now = _utc(2025, 3, 1)
    across = archive_window(LocalWindow(date(2024, 12, 31)))
    assert history.days_for(*across)[0] == date(2024, 12, 9)
    assert history.snapshot_times(*across) == [_utc(2024, 12, 10), _utc(2025, 1, 1)]
    january = archive_window(LocalWindow(date(2025, 1, 25)))
    assert history.snapshot_times(*january) == [_utc(2025, 1, 4)]
    # A window after today reads nothing.
    kit.clock.now = _utc(2024, 11, 1)
    assert history.days_for(*across) == []
    assert history.snapshot_times(*across) == []
    assert history.load(*across) == ArchiveLoad(days=())
    # A window whose first day file is today: the current minute stands in for S0.
    kit.clock.now = datetime(2024, 12, 9, 6, 30, 15, tzinfo=UTC)
    assert history.days_for(*across) == [date(2024, 12, 9)]
    assert history.snapshot_times(*across) == [_utc(2024, 12, 9, 6, 30)]


def test_range_files_reach_back_to_the_event_and_its_vtec_year() -> None:
    event = CarriedEvent(
        key="SHV.FL.W.0019.2024",
        wfo="SHV",
        phenomena="FL",
        significance="W",
        vtec_year=2024,
        first=_utc(2024, 1, 24, 19, 35),
        last_expire=_utc(2024, 5, 29, 12),
        listed_at=(_utc(2024, 4, 30),),
        reasons=("in effect before the day files and during the window",),
    )
    assert WarningHistory.range_for(event, date(2024, 5, 22)) == (
        date(2024, 1, 1),
        date(2024, 6, 1),
    )
    # A begin on the first of a month reaches into the month before (retroactive begins).
    first_of_april = replace(event, first=_utc(2024, 4, 1, 3))
    assert WarningHistory.range_for(first_of_april, date(2024, 5, 31))[0] == date(2024, 3, 1)
    # Listed rows from 2025 of an event numbered in 2024: the range starts in December 2024.
    later = replace(event, first=_utc(2025, 1, 20))
    assert WarningHistory.range_for(later, date(2025, 2, 3)) == (
        date(2024, 12, 1),
        date(2025, 3, 1),
    )
    # No time listed at all: from December of the year before its VTEC year.
    unknown = replace(event, first=None)
    assert WarningHistory.range_for(unknown, date(2024, 5, 22))[0] == date(2023, 12, 1)
    merged = event.merged(
        replace(event, first=None, last_expire=None, listed_at=(_utc(2025, 1, 1),))
    )
    assert (merged.first, merged.last_expire) == (event.first, event.last_expire)
    assert merged.listed_at == (_utc(2024, 4, 30), _utc(2025, 1, 1))


def test_day_file_rows_of_carried_events_are_not_used(kit: "Kit") -> None:
    """Each event's rows come from one kind of file, so none is counted twice."""
    history = _history(kit)
    day = history.archive.day(date(2024, 5, 21))
    kit.clock.now = _utc(2024, 6, 10)
    source = history.archive.range("HGX", "FL", "W", date(2024, 4, 1), date(2024, 6, 1))
    load = ArchiveLoad(days=(day,), ranges=(source,), carried={"DMX.TO.W.0034.2024": source})
    keys = {row.event_key for row, _ in load.rows()}
    assert keys == {"ARX.TO.A.0277.2024"}  # not DMX's (carried), nor HGX's (not carried)
    assert {row.event_key for row, _ in ArchiveLoad(days=(day,)).rows()} == {
        "ARX.TO.A.0277.2024",
        "DMX.TO.W.0034.2024",
    }


def test_a_carried_event_missing_from_its_range_file_is_counted(kit: "Kit") -> None:
    """Synthetic: the LSX range slice is served at the HGX range URL."""
    history, start, end = _local_day(kit, date(2024, 5, 21))
    hgx = range_url("HGX", "FL", "W", date(2024, 4, 1), date(2024, 6, 1))
    kit.server.files[hgx] = (FIXTURES / "iem-range-LSX-FL.W-2024-04-01_2024-06-01.zip").read_bytes()
    load = history.load(start, end)
    assert load.missing == (HGX_52,)
    assert HGX_52 not in load.carried
    assert history.skipped["carried event not in its range file"] == 1
    carried = history.provenance()["carried_events"]
    assert isinstance(carried, dict)
    assert carried[HGX_52] == {
        "first": "2024-04-29T07:38:00Z",
        "last_expire": "2024-06-28T19:02:00Z",
        "listed_at": ["2024-04-30T00:00:00Z"],
        "reasons": ["in effect before the day files and during the window"],
        "in_range_file": False,
    }
    # LSX 47's rows are read once, from the LSX file, not again from the mislabelled one.
    lsx = [where for row, where in load.rows() if row.event_key == LSX_47]
    assert lsx
    assert all("range LSX.FL.W" in where for where in lsx)
