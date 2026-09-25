"""Tests for VTEC parsing, the allowlist, and the active-alerts feed parser."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from shapely.geometry import Polygon

from snowlight.sources.nws.alerts import (
    ACTIVE_URL,
    AlertFormatError,
    fetch_active,
    parse_active,
    parse_alert,
)
from snowlight.sources.nws.vtec import VtecError, parse_vtec
from snowlight.weather.hazards import (
    ALERT_TYPES,
    BY_CODE,
    CONUS_STATES,
    alert_type_for_code,
    alert_type_for_event,
)

if TYPE_CHECKING:
    from weather.conftest import Kit

FIXTURES = Path(__file__).parent / "fixtures"
FEED = json.loads((FIXTURES / "active.geojson").read_text())
FFW_ID = "urn:oid:2.49.0.1.840.0.107eb2d6ccaadd37298b7ec9a8ecea52cdcc597e.001.1"


def _feature(alert_id: str) -> dict[str, object]:
    feature: dict[str, object] = next(
        f for f in FEED["features"] if f["properties"]["id"] == alert_id
    )
    return feature


def test_parse_vtec() -> None:
    vtec = parse_vtec("/O.NEW.KABQ.FF.W.0185.260924T2342Z-260925T0245Z/")
    assert vtec.code == ("FF", "W")
    assert (vtec.product_class, vtec.action, vtec.office, vtec.etn) == ("O", "NEW", "KABQ", 185)
    assert vtec.begin == datetime(2026, 9, 24, 23, 42, tzinfo=UTC)
    assert vtec.end == datetime(2026, 9, 25, 2, 45, tzinfo=UTC)
    open_ended = parse_vtec("/O.EXT.KTBW.FL.W.0012.000000T0000Z-000000T0000Z/")
    assert (open_ended.begin, open_ended.end) == (None, None)
    with pytest.raises(VtecError, match="not a P-VTEC"):
        parse_vtec("/00000.N.ER.000000T0000Z.000000T0000Z.000000T0000Z.OO/")
    with pytest.raises(VtecError, match="bad time"):
        parse_vtec("/O.NEW.KABQ.FF.W.0185.261324T2342Z-260925T0245Z/")


def test_allowlist_matches_the_nws_event_names() -> None:
    current = set(json.loads((FIXTURES / "alert-types.json").read_text())["eventTypes"])
    for kind in ALERT_TYPES:
        assert (kind.event in current) is not kind.retired, kind.event
    assert len({kind.event for kind in ALERT_TYPES}) == len(ALERT_TYPES)
    assert sum(len(kind.codes) for kind in ALERT_TYPES) == len(BY_CODE)
    for dropped in (
        "Air Quality Alert",
        "Child Abduction Emergency",
        "Civil Danger Warning",
        "Red Flag Warning",
        "Special Weather Statement",
        "Flood Statement",
        "Wind Advisory",
        "Frost Advisory",
    ):
        assert alert_type_for_event(dropped) is None
    flood = alert_type_for_code("FL", "W")
    assert flood is not None
    assert (flood.event, flood.hazard, flood.level) == ("Flood Warning", "flood", "warning")
    heat = alert_type_for_event("Heat Advisory")
    assert heat is not None
    assert heat.level == "advisory"
    assert alert_type_for_code("SV", "A") == alert_type_for_event("Severe Thunderstorm Watch")
    assert alert_type_for_code("MA", "W") is None
    assert len(CONUS_STATES) == 49
    assert {"DC", "TX", "ME", "WA"} <= CONUS_STATES
    assert not {"AK", "HI", "PR", "GU"} & CONUS_STATES


def test_parses_the_real_feed() -> None:
    feed = parse_active((FIXTURES / "active.geojson").read_bytes())
    assert feed.updated == datetime(2026, 9, 25, 0, 9, 38, tzinfo=UTC)
    assert len(feed.alerts) == len(FEED["features"]) == 12
    ffw = next(alert for alert in feed.alerts if alert.id == FFW_ID)
    assert ffw.event == "Flash Flood Warning"
    assert (ffw.status, ffw.message_type, ffw.severity) == ("Actual", "Alert", "Severe")
    assert ffw.onset == datetime(2026, 9, 24, 23, 42, tzinfo=UTC)
    assert ffw.ends == datetime(2026, 9, 25, 2, 45, tzinfo=UTC)
    assert isinstance(ffw.geometry, Polygon)
    assert ffw.ugc == ("NMC009", "NMC041")
    assert [(zone.kind, zone.ugc) for zone in ffw.zones] == [
        ("county", "NMC009"),
        ("county", "NMC041"),
    ]
    assert ffw.vtec[0].code == ("FF", "W")
    red_flag = next(alert for alert in feed.alerts if alert.event == "Red Flag Warning")
    assert {zone.kind for zone in red_flag.zones} == {"fire"}
    no_vtec = next(alert for alert in feed.alerts if alert.event == "Air Quality Alert")
    assert no_vtec.vtec == ()


def test_malformed_features_are_errors() -> None:
    good = _feature(FFW_ID)
    props = dict(good["properties"])  # type: ignore[call-overload]

    def with_props(**changes: object) -> dict[str, object]:
        return {**good, "properties": {**props, **changes}}

    with pytest.raises(AlertFormatError, match="not an object"):
        parse_alert([1])
    with pytest.raises(AlertFormatError, match="no properties"):
        parse_alert({"type": "Feature"})
    with pytest.raises(AlertFormatError, match="'event' is missing"):
        parse_alert(with_props(event=None))
    with pytest.raises(AlertFormatError, match="no sent time"):
        parse_alert(with_props(sent=None))
    with pytest.raises(AlertFormatError, match="onset is not a string"):
        parse_alert(with_props(onset=5))
    with pytest.raises(AlertFormatError, match="not an ISO 8601"):
        parse_alert(with_props(onset="tomorrow"))
    with pytest.raises(AlertFormatError, match="no UTC offset"):
        parse_alert(with_props(onset="2026-09-24T17:42:00"))
    with pytest.raises(AlertFormatError, match="affectedZones is not a list"):
        parse_alert(with_props(affectedZones="NMC009"))
    with pytest.raises(AlertFormatError, match="P-VTEC"):
        parse_alert(with_props(parameters={"VTEC": ["/bad/"]}))
    with pytest.raises(AlertFormatError, match="not a GeoJSON object"):
        parse_alert({**with_props(), "geometry": "POLYGON"})
    with pytest.raises(AlertFormatError, match="cannot be read"):
        parse_alert({**with_props(), "geometry": {"type": "Polygon"}})
    odd = parse_alert(with_props(affectedZones=["https://example.org/zones/NMC009"]))
    assert odd.zones == ()
    assert odd.unparsed_zones == ("https://example.org/zones/NMC009",)
    bowtie = {"type": "Polygon", "coordinates": [[[0, 0], [2, 2], [2, 0], [0, 2], [0, 0]]]}
    repaired = parse_alert({**with_props(), "geometry": bowtie}).geometry
    assert repaired is not None
    assert repaired.is_valid


def test_malformed_collections_are_errors() -> None:
    with pytest.raises(AlertFormatError, match="not JSON"):
        parse_active(b"<html>")
    with pytest.raises(AlertFormatError, match="FeatureCollection"):
        parse_active(b'{"type": "Feature"}')
    with pytest.raises(AlertFormatError, match="no features list"):
        parse_active(b'{"type": "FeatureCollection"}')


def test_fetch_active_caches_the_response(kit: "Kit") -> None:
    with kit.cache() as cache:
        feed, fetched = fetch_active(cache, kit.cache_dir)
        again, confirmed = fetch_active(cache, kit.cache_dir)
    assert fetched.path == kit.cache_dir / "api.weather.gov" / "alerts" / "active.geojson"
    assert fetched.provenance.url == ACTIVE_URL
    assert confirmed.not_modified is True
    assert again == feed
    assert kit.server.requests[0].headers["Accept"] == "application/geo+json"
