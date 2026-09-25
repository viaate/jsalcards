"""The models agree with the code that writes the files and names the codes.

Each test runs the real producer and validates what it writes. Producers that are
not in this checkout are skipped with a reason, never stood in for.
"""

import importlib
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, get_args

import polars as pl
import pytest

from snowlight.directory.build import meta_document
from snowlight.output import dumps_json
from snowlight.schemas.directory import SchoolDirectoryMeta
from snowlight.schemas.live import AlertsFile
from snowlight.schemas.vocab import (
    REASON_BY_LABEL,
    STATUS_BY_KIND,
    AlertLevel,
    Hazard,
    Reason,
    Status,
)

WEATHER_FEED = Path(__file__).resolve().parents[1] / "weather" / "fixtures" / "active.geojson"


def _optional(name: str) -> ModuleType:
    """Import a producer module, or skip when it is not in this checkout."""
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as error:
        if error.name is not None and name.startswith(error.name):
            pytest.skip(f"{name} is not in this checkout")
        raise


def _literals(alias: Any) -> set[str]:
    literal = get_args(alias.__value__)[0]
    return set(get_args(literal))


def test_directory_build_writes_a_valid_meta_json() -> None:
    schools = pl.DataFrame(
        {
            "id": ["000000000001", "000000000002", "0000000A"],
            "name": ["Synthetic School A", "Synthetic School B", "Synthetic Private School C"],
        }
    )
    districts = pl.DataFrame(
        {"district_id": ["0000001", "0000002"], "name": ["Synthetic One", "Synthetic Two"]}
    )
    document = meta_document(
        schools, districts, "2026-09-24", {"public": "2024-2025", "private": "2023-2024"}
    )
    meta = SchoolDirectoryMeta.from_json_bytes(dumps_json(document))
    assert meta.to_json_value() == document
    assert meta.to_json_bytes() == dumps_json(document)
    assert (meta.stamp().schools, meta.stamp().districts) == (3, 2)


def test_weather_publisher_writes_a_valid_alerts_json() -> None:
    """Storm-based alerts from the recorded feed, through the real grouping and render."""
    publish = _optional("snowlight.weather.publish")
    live = _optional("snowlight.weather.live")
    hazards = _optional("snowlight.weather.hazards")
    alerts = _optional("snowlight.sources.nws.alerts")
    if not WEATHER_FEED.is_file():
        pytest.skip(f"{WEATHER_FEED} is not in this checkout")
    feed = alerts.parse_active(WEATHER_FEED.read_bytes())
    kept = []
    for alert in feed.alerts:
        kind = hazards.alert_type_for_event(alert.event)
        if alert.geometry is None or kind is None:
            continue
        kept.append(
            live.LiveAlert(
                alert=alert,
                kind=kind,
                start=alert.onset or alert.effective,
                end=alert.ends,
                footprint=alert.geometry,
                areas=(),
                basis="polygon",
                zones=(),
                unresolved=(),
            )
        )
    assert kept, "the recorded feed has storm-based alerts"
    generated = datetime(2026, 9, 25, 0, 10, tzinfo=UTC)
    rendered = publish.render(
        publish.group_alerts(kept), as_of=feed.updated, generated_at=generated
    )
    document = AlertsFile.from_json_bytes(rendered.data)
    assert len(document.alerts) == rendered.alerts > 0
    assert document.to_json_bytes() == rendered.data
    empty = publish.render([], as_of=None, generated_at=generated)
    assert AlertsFile.from_json_bytes(empty.data).alerts == ()


def test_alert_vocabularies_cover_the_allowlist() -> None:
    hazards = _optional("snowlight.weather.hazards")
    template = {
        "id": "a1b2c3d4e5f6",
        "severity": "Severe",
        "onset": "2027-01-12T06:00:00Z",
        "ends": None,
        "bbox": [0.0, 0.0, 1.0, 1.0],
        "polygons": [[[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]]]],
    }
    for kind in hazards.ALERT_TYPES:
        assert kind.hazard in _literals(Hazard), kind
        assert kind.level in _literals(AlertLevel), kind
        entry = template | {"event": kind.event, "hazard": kind.hazard, "level": kind.level}
        document = {"schema": 1, "asOf": None, "generatedAt": "2027-01-12T13:04:10Z"}
        AlertsFile.from_json_bytes(dumps_json(document | {"alerts": [entry]}))


def test_status_and_reason_codes_cover_the_listing_parser() -> None:
    classify = _optional("snowlight.classify")
    assert set(REASON_BY_LABEL) == set(classify.REASONS)
    assert set(STATUS_BY_KIND) == set(classify.STATUS_KINDS)
    assert set(REASON_BY_LABEL.values()) == set(Reason)
    assert set(STATUS_BY_KIND.values()) == set(Status)
