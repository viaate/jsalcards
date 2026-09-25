"""Tests for selecting today's relevant alerts from the real fixture feed."""

import copy
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from snowlight.sources.nws.alerts import ActiveFeed, parse_active, parse_alert
from snowlight.sources.nws.boundaries import BoundarySet
from snowlight.weather.index import WeatherIndex
from snowlight.weather.live import alert_times, select_alerts

if TYPE_CHECKING:
    from weather.conftest import Kit

FIXTURES = Path(__file__).parent / "fixtures"
RAW = json.loads((FIXTURES / "active.geojson").read_text())
FEED = parse_active((FIXTURES / "active.geojson").read_bytes())
TODAY = date(2026, 9, 25)
NOW = datetime(2026, 9, 25, 0, 9, 38, tzinfo=UTC)  # the fixture feed's "updated" time
PREFIX = "urn:oid:2.49.0.1.840.0."
FFW = PREFIX + "107eb2d6ccaadd37298b7ec9a8ecea52cdcc597e.001.1"
FLOOD = PREFIX + "cde4b599c92ad3912dad22ba7ef69b83f83cf451.001.1"
COASTAL_WARNING = PREFIX + "5dadf6e3b9ebfab154c0bb2598d2155371dcf4fb.002.1"
COASTAL_WATCH = PREFIX + "a606da1d3b77e41466dadb0b1d3a63f3b3b6ecb8.005.1"


def _boundaries(kit: "Kit") -> tuple[BoundarySet, BoundarySet]:
    catalog = kit.catalog()
    zones = catalog.boundaries_for("zone", TODAY)
    counties = catalog.boundaries_for("county", TODAY)
    assert zones is not None
    assert counties is not None
    return zones, counties


def _raw(alert_id: str) -> dict[str, Any]:
    feature: dict[str, Any] = copy.deepcopy(
        next(f for f in RAW["features"] if f["properties"]["id"] == alert_id)
    )
    return feature


def test_selection_of_the_real_feed(kit: "Kit") -> None:
    assert FEED.updated == NOW
    zones, counties = _boundaries(kit)
    selection = select_alerts(FEED, zones, counties)
    kept = {alert.alert.event for alert in selection.kept}
    assert kept == {
        "Flash Flood Warning",
        "Flood Warning",
        "Coastal Flood Warning",
        "Coastal Flood Watch",
        "Coastal Flood Advisory",
        "High Wind Watch",
        "Flood Watch",
    }
    assert len(selection.kept) == 7
    assert selection.reasons() == {
        "event not on the allowlist": 3,
        "outside the contiguous states": 2,
    }
    dropped = {(item.event, item.reason) for item in selection.dropped}
    assert ("Red Flag Warning", "event not on the allowlist") in dropped
    assert ("Tropical Storm Watch", "outside the contiguous states") in dropped


def test_storm_based_warning_uses_its_polygon(kit: "Kit") -> None:
    zones, counties = _boundaries(kit)
    selection = select_alerts(FEED, zones, counties)
    ffw = next(alert for alert in selection.kept if alert.alert.id == FFW)
    assert ffw.basis == "polygon"
    assert ffw.start == datetime(2026, 9, 24, 23, 42, tzinfo=UTC)
    assert ffw.end == datetime(2026, 9, 25, 2, 45, tzinfo=UTC)
    assert [(a.basis, a.point_matching, sorted(a.counties)) for a in ffw.areas] == [
        ("polygon", True, []),
        ("county", False, ["35009", "35041"]),
    ]
    assert ffw.zones == ("county NMC009", "county NMC041")
    assert ffw.info.severity == "Severe"
    assert ffw.info.level == "warning"
    index = WeatherIndex(list(ffw.areas))
    inside = ffw.footprint.representative_point()
    window = {"start": ffw.start, "end": ffw.start + timedelta(hours=1)}
    [hit] = index.check(county_fips="35009", lat=inside.y, lon=inside.x, **window)
    assert hit.basis == "polygon"
    assert hit.traces == (f"{FFW} polygon",)
    # Elsewhere in the county the polygon decides; without a point the county list does.
    assert not index.check(county_fips="35009", lat=34.0, lon=-103.9, **window)
    assert index.check(county_fips="35009", lat=None, lon=None, **window)


def test_open_ended_warning_and_unresolved_counties(kit: "Kit") -> None:
    zones, counties = _boundaries(kit)
    selection = select_alerts(FEED, zones, counties)
    flood = next(alert for alert in selection.kept if alert.alert.id == FLOOD)
    assert flood.end is None
    assert [area.basis for area in flood.areas] == ["polygon"]
    # The fixture slice leaves this alert's three counties out (see make_fixtures.py).
    assert [note.split(":")[0] for note in flood.unresolved] == [
        "county FLC017",
        "county FLC075",
        "county FLC083",
    ]


def test_zone_based_alerts_use_the_zone_boundaries(kit: "Kit") -> None:
    zones, counties = _boundaries(kit)
    selection = select_alerts(FEED, zones, counties)
    watch = next(alert for alert in selection.kept if alert.alert.id == COASTAL_WATCH)
    assert watch.start == datetime(2026, 9, 25, 21, tzinfo=UTC)
    assert watch.basis == "zones"
    assert watch.zones == ("forecast NYZ074",)
    assert watch.footprint.equals(zones.areas["NYZ074"])
    index = WeatherIndex([area for alert in selection.kept for area in alert.areas])
    point = zones.areas["NCZ204"].representative_point()
    today = index.check(
        county_fips=None, lat=point.y, lon=point.x, start=NOW, end=NOW + timedelta(hours=12)
    )
    assert [m.alert.key for m in today] == [COASTAL_WARNING]
    montana = zones.areas["MTZ303"].representative_point()
    tomorrow = datetime(2026, 9, 26, 6, tzinfo=UTC)
    later = {"start": tomorrow, "end": tomorrow + timedelta(hours=18)}
    hits = index.check(county_fips=None, lat=montana.y, lon=montana.x, **later)
    assert [m.alert.event for m in hits] == ["High Wind Watch"]
    now = {"start": NOW, "end": NOW + timedelta(hours=1)}
    assert not index.check(county_fips=None, lat=montana.y, lon=montana.x, **now)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"status": "Exercise"}, "status Exercise"),
        ({"messageType": "Cancel"}, "message type Cancel"),
        (
            {"parameters": {"VTEC": ["/O.CAN.KABQ.FF.W.0185.000000T0000Z-260925T0245Z/"]}},
            "cancelled or upgraded (VTEC action)",
        ),
        ({"onset": None, "effective": None}, "no onset or effective time"),
        ({"ends": "2026-09-24T18:00:00-06:00"}, "ended before the feed was generated"),
        (
            {"onset": "2026-09-26T00:00:00Z", "ends": "2026-09-25T12:00:00Z"},
            "ends before it begins",
        ),
        ({"affectedZones": [], "geocode": {"UGC": ["NCZ999"]}}, "no resolvable area"),
    ],
)
def test_synthetic_variants_are_dropped_with_reasons(
    kit: "Kit", changes: dict[str, Any], reason: str
) -> None:
    zones, counties = _boundaries(kit)
    feature = _raw(COASTAL_WARNING if "affectedZones" in changes else FFW)
    feature["properties"].update(changes)
    if "affectedZones" in changes:
        feature["geometry"] = None
    selection = select_alerts(ActiveFeed(NOW, (parse_alert(feature),)), zones, counties)
    assert selection.kept == ()
    assert [item.reason for item in selection.dropped] == [reason]


def test_times_fall_back_to_effective_and_vtec_end() -> None:
    feature = _raw(FFW)
    feature["properties"].update(onset=None, ends=None)
    alert = parse_alert(feature)
    start, end = alert_times(alert)
    assert start == alert.effective
    assert end == datetime(2026, 9, 25, 2, 45, tzinfo=UTC)
    feature["properties"]["parameters"]["VTEC"] = []
    assert alert_times(parse_alert(feature)) == (alert.effective, None)


def test_unsupported_and_foreign_zones_are_noted(kit: "Kit") -> None:
    zones, counties = _boundaries(kit)
    feature = _raw(COASTAL_WARNING)
    base = "https://api.weather.gov/zones/"
    feature["properties"]["affectedZones"] += [
        base + "fire/NCZ204",
        base + "forecast/AKZ101",
        base + "forecast/NCZ999",
        "https://example.org/somewhere",
    ]
    feed = ActiveFeed(NOW, (parse_alert(feature),))
    [kept] = select_alerts(feed, zones, counties).kept
    assert kept.zones == ("forecast NCZ204",)
    assert kept.unresolved == (
        "unparsed zone reference https://example.org/somewhere",
        "fire NCZ204: no boundary file for this zone type",
        "forecast AKZ101: outside the contiguous states",
        "forecast NCZ999: not in the boundary release in effect",
    )
