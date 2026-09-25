"""Tests for the published live/alerts.json."""

import json
import re
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import shapely
from shapely.geometry import LinearRing, MultiPolygon, Polygon, box, shape

from snowlight.sources.nws.alerts import parse_active
from snowlight.weather.live import LiveAlert, select_alerts
from snowlight.weather.publish import (
    FORBIDDEN_IN_PUBLISHED,
    TOLERANCES,
    BudgetError,
    PublishedContentError,
    build_document,
    check_published,
    group_alerts,
    render,
)

if TYPE_CHECKING:
    from weather.conftest import Kit

FIXTURES = Path(__file__).parent / "fixtures"
FEED = parse_active((FIXTURES / "active.geojson").read_bytes())
NOW = datetime(2026, 9, 25, 0, 9, 38, tzinfo=UTC)
GENERATED = datetime(2026, 9, 25, 0, 10, 0, tzinfo=UTC)


def _kept(kit: "Kit") -> tuple[LiveAlert, ...]:
    catalog = kit.catalog()
    zones = catalog.boundaries_for("zone", date(2026, 9, 25))
    counties = catalog.boundaries_for("county", date(2026, 9, 25))
    assert zones is not None
    assert counties is not None
    return select_alerts(FEED, zones, counties).kept


def test_published_file_shape(kit: "Kit") -> None:
    kept = _kept(kit)
    rendered = render(group_alerts(kept), as_of=NOW, generated_at=GENERATED)
    document = json.loads(rendered.data)
    assert set(document) == {"schema", "asOf", "generatedAt", "alerts"}
    assert (document["schema"], document["asOf"], document["generatedAt"]) == (
        1,
        "2026-09-25T00:09:38Z",
        "2026-09-25T00:10:00Z",
    )
    assert rendered.alerts == len(document["alerts"]) == 7
    assert rendered.tolerance == TOLERANCES[0]
    assert rendered.too_small == ()
    levels = [entry["level"] for entry in document["alerts"]]
    assert levels == sorted(levels, key=["warning", "watch", "advisory"].index)
    for entry in document["alerts"]:
        assert set(entry) == {
            "id", "event", "hazard", "level", "severity", "onset", "ends", "bbox", "polygons",
        }  # fmt: skip
        assert re.fullmatch(r"[0-9a-f]{12}", entry["id"])
        assert entry["onset"].endswith("Z")
        geometry = shape({"type": "MultiPolygon", "coordinates": entry["polygons"]})
        assert geometry.is_valid
        west, south, east, north = entry["bbox"]
        assert geometry.bounds == pytest.approx((west, south, east, north))
        for polygon in entry["polygons"]:
            assert LinearRing(polygon[0]).is_ccw
            for hole in polygon[1:]:
                assert not LinearRing(hole).is_ccw
            for ring in polygon:
                for lon, lat in ring:
                    assert round(lon, 3) == lon
                    assert round(lat, 3) == lat
    flood = next(e for e in document["alerts"] if e["event"] == "Flood Warning")
    assert flood["ends"] is None
    text = rendered.data.decode().lower()
    assert not any(needle in text for needle in FORBIDDEN_IN_PUBLISHED)
    assert "description" not in text


def test_published_polygons_follow_the_real_footprints(kit: "Kit") -> None:
    kept = _kept(kit)
    groups = group_alerts(kept)
    document = json.loads(render(groups, as_of=NOW, generated_at=GENERATED).data)
    for group, entry in zip(groups, document["alerts"], strict=True):
        drawn = shape({"type": "MultiPolygon", "coordinates": entry["polygons"]})
        # Simplification moves edges by at most the tolerance (plus the grid).
        assert shapely.hausdorff_distance(drawn, group.footprint) < 0.05
        assert drawn.intersection(group.footprint).area > 0.8 * group.footprint.area


def test_identical_alerts_are_merged(kit: "Kit") -> None:
    kept = _kept(kit)
    warning = next(alert for alert in kept if alert.alert.event == "Coastal Flood Warning")
    # Synthetic twin: the same alert under another id, shifted one degree east.
    twin = replace(
        warning,
        alert=replace(warning.alert, id=warning.alert.id + ".twin"),
        footprint=shapely.affinity.translate(warning.footprint, xoff=1.0),
    )
    groups = group_alerts([twin, warning])
    assert len(groups) == 1
    assert [m.alert.id for m in groups[0].members] == [warning.alert.id, twin.alert.id]
    assert groups[0].footprint.area == pytest.approx(2 * warning.footprint.area)
    assert group_alerts([warning])[0].id != groups[0].id


def test_size_budget(kit: "Kit") -> None:
    groups = group_alerts(_kept(kit))
    full = render(groups, as_of=NOW, generated_at=GENERATED)
    smaller = render(groups, as_of=NOW, generated_at=GENERATED, max_bytes=len(full.data) - 1)
    assert smaller.tolerance > full.tolerance
    assert len(smaller.data) < len(full.data)
    with pytest.raises(BudgetError, match="over the 1000-byte budget"):
        render(groups, as_of=NOW, generated_at=GENERATED, max_bytes=1000)


def test_tiny_areas_use_a_finer_grid_or_are_reported(kit: "Kit") -> None:
    warning = next(a for a in _kept(kit) if a.alert.event == "Coastal Flood Warning")
    small = replace(warning, footprint=box(-75.0, 35.0, -74.9996, 35.0004))
    speck = replace(
        warning,
        alert=replace(warning.alert, id="speck", severity="Minor"),
        footprint=box(-75.0, 35.0, -74.9999999, 35.0000001),
    )
    groups = group_alerts([small, speck])
    document, too_small = build_document(
        groups, as_of=None, generated_at=GENERATED, tolerance=TOLERANCES[0]
    )
    assert document["asOf"] is None
    entries = document["alerts"]
    assert isinstance(entries, list)
    assert len(entries) == 1
    assert too_small == [g.id for g in groups if g.members[0].alert.id == "speck"]


def test_specks_are_left_out_but_the_largest_part_stays(kit: "Kit") -> None:
    warning = next(a for a in _kept(kit) if a.alert.event == "Coastal Flood Warning")
    islands = MultiPolygon([box(-76, 35, -75, 36), box(-74, 35, -73.9999, 35.0001)])
    groups = group_alerts([replace(warning, footprint=islands)])
    document, _ = build_document(groups, as_of=NOW, generated_at=GENERATED, tolerance=0.002)
    entries = document["alerts"]
    assert isinstance(entries, list)
    [entry] = entries
    assert isinstance(entry, dict)
    polygons = entry["polygons"]
    assert isinstance(polygons, list)
    assert len(polygons) == 1
    lone = replace(warning, footprint=Polygon([(-74, 35), (-73.9999, 35), (-74, 35.0001)]))
    document, _ = build_document(
        group_alerts([lone]), as_of=NOW, generated_at=GENERATED, tolerance=0.002
    )
    assert document["alerts"]


def test_check_published_refuses_sources_and_links() -> None:
    check_published(b'{"event":"Winter Storm Warning"}')
    for bad in (b'{"x":"https://api.weather.gov"}', b'{"x":"NWS"}', b'{"x":"urn:oid:2.49"}'):
        with pytest.raises(PublishedContentError):
            check_published(bad)
