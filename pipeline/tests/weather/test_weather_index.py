"""Tests for the weather check index.

The areas here are synthetic squares and made-up alert keys: these tests pin the
matching rules, not any real alert (the real-data tests are in test_weather_live
and test_weather_history).
"""

import time as clock
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta

import numpy as np
import pytest
from shapely.geometry import MultiPolygon, Polygon, box

from snowlight.sources.nws.shapefile import Polygonal
from snowlight.weather.index import (
    MATCH_SCHEMA,
    AlertArea,
    AlertInfo,
    AlertMatch,
    Basis,
    WeatherIndex,
)
from snowlight.weather.timezones import LocalWindow

T0 = datetime(2026, 1, 26, 12, tzinfo=UTC)
HOUR = timedelta(hours=1)
TOL = 0.01
WARNING = AlertInfo("synthetic:warning", "Winter Storm Warning", "winter", "warning", "Severe")
WATCH = AlertInfo("synthetic:watch", "Tornado Watch", "severe", "watch", None)
FLOOD = AlertInfo("synthetic:flood", "Flood Warning", "flood", "warning", None)


def _area(alert: AlertInfo, geometry: Polygon | None, basis: Basis = "zone") -> AlertArea:
    """An exact area in effect from T0 for six hours (vary it with ``replace``)."""
    return AlertArea(
        alert=alert,
        start=T0,
        end=T0 + 6 * HOUR,
        geometry=geometry,
        counties=frozenset(),
        basis=basis,
        precision="exact",
    )


def _rough(alert: AlertInfo, outline: Polygon, hint: Polygonal | None = None) -> AlertArea:
    """An approximate zone area: a simplified outline with tolerance ``TOL``."""
    return replace(_area(alert, outline), precision="approximate", tolerance=TOL, hint=hint)


def _at(index: WeatherIndex, lon: float, lat: float, county: str | None = None) -> list[AlertMatch]:
    return index.check(county_fips=county, lat=lat, lon=lon, start=T0, end=T0 + HOUR)


def _answers(matches: list[AlertMatch]) -> list[tuple[str, str]]:
    return [(m.alert.key, m.coverage) for m in matches]


def test_point_inside_an_area_during_the_window_matches() -> None:
    index = WeatherIndex([_area(WARNING, box(0, 0, 1, 1))])
    hits = _at(index, 0.5, 0.5)
    assert [(m.alert, m.coverage, m.basis, m.precision) for m in hits] == [
        (WARNING, "covered", "zone", "exact")
    ]
    assert (hits[0].start, hits[0].end) == (T0, T0 + 6 * HOUR)
    # Boundary points count as covered.
    assert _at(index, 0.5, 1.0)
    assert not _at(index, 0.5, 2.0)


def test_time_windows_must_overlap() -> None:
    index = WeatherIndex([_area(WARNING, box(0, 0, 1, 1))])

    def hit(start: datetime, end: datetime) -> bool:
        return bool(index.check(county_fips=None, lat=0.5, lon=0.5, start=start, end=end))

    assert not hit(T0 - 2 * HOUR, T0)
    assert hit(T0 - 2 * HOUR, T0 + timedelta(minutes=1))
    assert hit(T0 + 5 * HOUR, T0 + 9 * HOUR)
    assert not hit(T0 + 6 * HOUR, T0 + 9 * HOUR)


def test_open_ended_areas_last_until_further_notice() -> None:
    index = WeatherIndex([replace(_area(FLOOD, box(0, 0, 1, 1)), end=None)])
    [match] = index.check(
        county_fips=None, lat=0.5, lon=0.5, start=T0 + 1000 * HOUR, end=T0 + 1001 * HOUR
    )
    assert match.end is None


def test_areas_that_never_took_effect_are_dropped() -> None:
    upgraded = replace(_area(WATCH, box(0, 0, 1, 1)), end=T0 - HOUR)
    zero = replace(_area(WARNING, box(0, 0, 1, 1)), end=T0)
    index = WeatherIndex([upgraded, zero])
    assert len(index) == 0
    assert not index.check(county_fips=None, lat=0.5, lon=0.5, start=T0 - 5 * HOUR, end=T0 + HOUR)


def test_approximate_outlines_answer_in_three_states() -> None:
    index = WeatherIndex([_rough(WARNING, box(0, 0, 1, 1))])
    assert _answers(_at(index, 0.5, 0.5)) == [("synthetic:warning", "covered")]
    [deep] = _at(index, 0.5, 0.5)
    assert (deep.basis, deep.precision) == ("zone", "approximate")
    # Within the tolerance of the outline, on either side: uncertain, never absent.
    assert _answers(_at(index, 0.995, 0.5)) == [("synthetic:warning", "uncertain")]
    assert _answers(_at(index, 1.005, 0.5)) == [("synthetic:warning", "uncertain")]
    assert _answers(_at(index, 1.0, 1.0)) == [("synthetic:warning", "uncertain")]
    # Farther than the tolerance outside: not covered.
    assert not _at(index, 1.02, 0.5)


def test_the_hint_catches_dropped_parts_and_moved_boundaries() -> None:
    # The hint (nearest NWS release) has an island the outline dropped, and ends at x = 0.8.
    hint = MultiPolygon([box(0, 0, 0.8, 1), box(1.5, 0, 1.6, 0.1)])
    index = WeatherIndex([_rough(WARNING, box(0, 0, 1, 1), hint=hint)])
    assert _answers(_at(index, 0.4, 0.5)) == [("synthetic:warning", "covered")]
    # On the dropped island, far from the outline: uncertain.
    assert _answers(_at(index, 1.55, 0.05)) == [("synthetic:warning", "uncertain")]
    # Deep inside the outline but outside the hint: uncertain, not covered.
    assert _answers(_at(index, 0.9, 0.5)) == [("synthetic:warning", "uncertain")]
    # Outside both: nothing.
    assert not _at(index, 1.3, 0.5)


def test_a_shared_edge_between_areas_of_one_alert_is_covered() -> None:
    west = replace(_rough(WARNING, box(0, 0, 1, 1)), trace="west")
    east = replace(_rough(WARNING, box(1, 0, 2, 1)), trace="east")
    index = WeatherIndex([west, east])
    [edge] = _at(index, 1.0, 0.5)
    assert (edge.coverage, edge.traces) == ("covered", ("east", "west"))
    assert _answers(_at(index, 0.996, 0.5)) == [("synthetic:warning", "covered")]
    # Near the union's own outline it stays uncertain, even next to the shared edge.
    assert _answers(_at(index, 1.0, 0.995)) == [("synthetic:warning", "uncertain")]
    assert _answers(_at(index, 1.0, 1.005)) == [("synthetic:warning", "uncertain")]
    # Areas of different alerts do not add up.
    split = WeatherIndex([west, replace(east, alert=WATCH)])
    assert sorted(_answers(_at(split, 1.0, 0.5))) == [
        ("synthetic:warning", "uncertain"),
        ("synthetic:watch", "uncertain"),
    ]
    # Nor do a zone and a county (they tile the land differently).
    mixed = WeatherIndex([west, replace(east, basis="county")])
    assert _answers(_at(mixed, 1.0, 0.5)) == [("synthetic:warning", "uncertain")]


def test_a_shared_edge_respects_the_hints() -> None:
    west = _rough(WARNING, box(0, 0, 1, 1), hint=box(0, 0, 1, 1))
    east = _rough(WARNING, box(1, 0, 2, 1), hint=box(1, 0, 2, 1))
    assert _answers(_at(WeatherIndex([west, east]), 1.0, 0.5)) == [("synthetic:warning", "covered")]
    # The hints say the point is in neither zone (a third zone was carved out).
    carved = [replace(west, hint=box(0, 0, 0.9, 1)), replace(east, hint=box(1.1, 0, 2, 1))]
    assert _answers(_at(WeatherIndex(carved), 1.0, 0.5)) == [("synthetic:warning", "uncertain")]
    # One area with a hint and one without cannot be checked together.
    lopsided = [west, replace(east, hint=None)]
    assert _answers(_at(WeatherIndex(lopsided), 1.0, 0.5)) == [("synthetic:warning", "uncertain")]


def test_county_matching_rules() -> None:
    fallback = replace(_area(WATCH, None, "county"), counties=frozenset({"19153"}))
    county_list = replace(
        _area(FLOOD, None, "county"), counties=frozenset({"19153"}), point_matching=False
    )
    polygon = _area(FLOOD, box(10, 10, 11, 11), "polygon")
    drawn_county = replace(
        _area(WARNING, box(20, 20, 21, 21), "county"), counties=frozenset({"19153"})
    )
    index = WeatherIndex([fallback, county_list, polygon, drawn_county])
    # With a point: a county area without a boundary matches on FIPS; the storm
    # polygon's county list does not; a drawn county matches only by its drawing.
    assert _answers(_at(index, 0.0, 0.0, "19153")) == [("synthetic:watch", "covered")]
    assert sorted(_answers(_at(index, 10.5, 10.5, "19153"))) == [
        ("synthetic:flood", "covered"),
        ("synthetic:watch", "covered"),
    ]
    # Without a point, areas coded as the county cover it; a storm-based
    # warning's county list only makes it uncertain.
    no_point = index.check(county_fips="19153", lat=None, lon=None, start=T0, end=T0 + HOUR)
    assert sorted(_answers(no_point)) == [
        ("synthetic:flood", "uncertain"),
        ("synthetic:warning", "covered"),
        ("synthetic:watch", "covered"),
    ]
    assert not index.check(county_fips=None, lat=None, lon=None, start=T0, end=T0 + HOUR)
    assert not index.check(county_fips="01001", lat=None, lon=None, start=T0, end=T0 + HOUR)


def test_a_known_county_code_decides_for_approximate_county_outlines() -> None:
    county = replace(_rough(WATCH, box(0, 0, 1, 1)), counties=frozenset({"19089"}), basis="county")
    index = WeatherIndex([county], known_counties={"19089", "19019"})
    # The place's county code settles it, wherever the outline puts the point.
    [same] = _at(index, 1.005, 0.5, "19089")
    assert (same.coverage, same.basis, same.precision) == ("covered", "county", "exact")
    assert _answers(_at(index, 5.0, 5.0, "19089")) == [("synthetic:watch", "covered")]
    assert not _at(index, 0.5, 0.5, "19019")
    # A code the NWS files do not use (a Connecticut planning region) leaves it to the outline.
    assert _answers(_at(index, 0.5, 0.5, "09110")) == [("synthetic:watch", "covered")]
    assert _answers(_at(index, 1.005, 0.5, "09110")) == [("synthetic:watch", "uncertain")]
    assert _answers(_at(index, 1.005, 0.5)) == [("synthetic:watch", "uncertain")]
    # Without the list of known codes, the outline decides for everyone.
    assert _answers(_at(WeatherIndex([county]), 1.005, 0.5, "19089")) == [
        ("synthetic:watch", "uncertain")
    ]


def test_matches_are_merged_per_alert() -> None:
    rough = _rough(WARNING, box(0, 0, 1, 1))
    first = replace(rough, start=T0, end=T0 + HOUR)
    later = replace(_area(WARNING, box(0, 0, 2, 2), "polygon"), start=T0 + HOUR, end=T0 + 3 * HOUR)
    index = WeatherIndex([first, later])
    [match] = index.check(county_fips=None, lat=0.5, lon=0.5, start=T0, end=T0 + 5 * HOUR)
    assert (match.start, match.end) == (T0, T0 + 3 * HOUR)
    assert (match.coverage, match.basis, match.precision) == ("covered", "polygon", "exact")
    [coarse] = index.check(county_fips=None, lat=0.5, lon=0.5, start=T0, end=T0 + HOUR)
    assert (coarse.basis, coarse.precision) == ("zone", "approximate")
    # A covered answer is built only from the areas that covered the place.
    near = index.check(county_fips=None, lat=0.5, lon=0.995, start=T0, end=T0 + 5 * HOUR)
    assert [(m.coverage, m.start, m.basis) for m in near] == [("covered", T0 + HOUR, "polygon")]
    [unsure] = index.check(county_fips=None, lat=0.5, lon=0.995, start=T0, end=T0 + HOUR)
    assert (unsure.coverage, unsure.start, unsure.end) == ("uncertain", T0, T0 + HOUR)


def test_areas_must_be_consistent() -> None:
    other = AlertInfo(WARNING.key, "Blizzard Warning", "winter", "warning", None)
    with pytest.raises(ValueError, match="described two ways"):
        WeatherIndex([_area(WARNING, box(0, 0, 1, 1)), _area(other, box(0, 0, 1, 1))])
    rough = _rough(WARNING, box(0, 0, 1, 1))
    with pytest.raises(ValueError, match="needs an outline and a tolerance"):
        replace(rough, tolerance=0.0)
    with pytest.raises(ValueError, match="needs an outline and a tolerance"):
        replace(rough, geometry=None)
    with pytest.raises(ValueError, match="only approximate areas"):
        replace(rough, precision="exact")
    with pytest.raises(ValueError, match="only approximate areas"):
        replace(_area(WARNING, box(0, 0, 1, 1)), hint=box(0, 0, 1, 1))


def test_check_many_takes_per_place_windows() -> None:
    index = WeatherIndex([_area(WARNING, box(0, 0, 1, 1)), _area(WATCH, box(0, 0, 3, 3))])
    lon = np.array([0.5, 2.5, 0.5, np.nan])
    lat = np.array([0.5, 2.5, 0.5, np.nan])
    starts = np.array(
        ["2026-01-26T12:00", "2026-01-26T12:00", "2026-01-27T12:00", "2026-01-26T12:00"],
        dtype="datetime64[ns]",
    )
    ends = (starts + np.timedelta64(1, "h")).astype("datetime64[ns]")
    frame = index.check_many(["19153", None, None, "19153"], lon, lat, start=starts, end=ends)
    assert frame.schema == MATCH_SCHEMA
    # Sorted by place, then start, then event name.
    assert frame.select("row", "key", "coverage").rows() == [
        (0, "synthetic:watch", "covered"),
        (0, "synthetic:warning", "covered"),
        (1, "synthetic:watch", "covered"),
    ]
    row = frame.row(0, named=True)
    assert row["start"] == T0
    assert row["end"] == T0 + 6 * HOUR
    empty = index.check_many([None], np.array([50.0]), np.array([50.0]), start=T0, end=T0 + HOUR)
    assert empty.height == 0
    assert empty.schema == MATCH_SCHEMA
    assert (
        WeatherIndex([]).check_many([None], lon[:1], lat[:1], start=T0, end=T0 + HOUR).height == 0
    )


def test_bad_inputs_are_refused() -> None:
    index = WeatherIndex([_area(WARNING, box(0, 0, 1, 1))])
    naive = datetime(2026, 1, 26, 12)
    with pytest.raises(ValueError, match="naive datetime"):
        index.check(county_fips=None, lat=0.5, lon=0.5, start=naive, end=T0)
    with pytest.raises(ValueError, match="end after it starts"):
        index.check(county_fips=None, lat=0.5, lon=0.5, start=T0, end=T0)
    with pytest.raises(ValueError, match="same length"):
        index.check_many([None, None], np.array([0.5]), np.array([0.5]), start=T0, end=T0 + HOUR)
    with pytest.raises(ValueError, match="has 2 values for 1 places"):
        index.check_many([None], np.array([0.5]), np.array([0.5]), start=[T0, T0], end=T0 + HOUR)
    with pytest.raises(TypeError, match="datetime64"):
        index.check_many([None], np.array([0.5]), np.array([0.5]), start=np.array([1]), end=T0)


def test_many_schools_per_second() -> None:
    # Synthetic load: 2,000 one-degree squares (half approximate, in adjacent pairs
    # under one alert) and 100,000 random points.
    rng = np.random.default_rng(7)
    areas: list[AlertArea] = []
    for i, (x, y) in enumerate(
        zip(rng.uniform(-120, -70, 1000), rng.uniform(25, 48, 1000), strict=True)
    ):
        alert = AlertInfo(f"synthetic:{i}", "Winter Storm Warning", "winter", "warning", None)
        if i % 2:
            areas.append(_area(alert, box(x, y, x + 1, y + 1)))
            areas.append(_area(alert, box(x + 1, y, x + 2, y + 1)))
        else:
            areas.append(_rough(alert, box(x, y, x + 1, y + 1), hint=box(x, y, x + 1, y + 1)))
            areas.append(_rough(alert, box(x + 1, y, x + 2, y + 1)))
    index = WeatherIndex(areas)
    lon = rng.uniform(-125, -66, 100_000)
    lat = rng.uniform(24, 50, 100_000)
    began = clock.perf_counter()
    frame = index.check_many([None] * lon.size, lon, lat, start=T0, end=T0 + HOUR)
    elapsed = clock.perf_counter() - began
    assert set(frame["coverage"]) == {"covered", "uncertain"}
    assert elapsed < 20, f"{lon.size} places took {elapsed:.1f} s"


def test_check_local_converts_the_local_window() -> None:
    index = WeatherIndex([_area(WARNING, box(0, 0, 1, 1))])
    # T0 is 06:00 in Chicago; the area runs 06:00 to 12:00 local.
    morning = LocalWindow(date(2026, 1, 26), time(5), time(7))
    evening = LocalWindow(date(2026, 1, 26), time(18), time(22))
    zone = "America/Chicago"
    assert index.check_local(county_fips=None, lat=0.5, lon=0.5, window=morning, zone=zone)
    assert not index.check_local(county_fips=None, lat=0.5, lon=0.5, window=evening, zone=zone)
