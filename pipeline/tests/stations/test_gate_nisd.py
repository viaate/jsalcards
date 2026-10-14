"""Northside ISD's homepage notices: the adapter, its fixtures and its registry entry.

The fixtures are real: the district's live homepage of 2026-09-29 (an empty
notices view) and the archive's captures of 2024-01-15 (a holiday), 2025-01-20
(the January 2025 snow: classes cancelled) and 2026-01-25 (the January 2026 cold:
schools closed), provenance in fixtures/gate/PROVENANCE.json. The small documents
built in a few tests are synthetic and say so.
"""

import pytest

from snowlight.sources.stations import gate_fixtures, nisd, notices
from snowlight.sources.stations.gap_markup import document
from snowlight.sources.stations.model import MAX_STATUS, ListingState, ReadMode, ShapeError
from snowlight.sources.stations.registry import load_registry

FOLDER = gate_fixtures.DEFAULT_FOLDER
ENTRIES = {e.file: e for e in gate_fixtures.load_entries(FOLDER) if e.source_id.startswith("nisd")}
DISTRICT = "Northside Independent School District"


def _body(name: str) -> bytes:
    return (FOLDER / name).read_bytes()


def test_the_fixtures_read_as_recorded() -> None:
    assert set(ENTRIES) == {
        "nisd/nisd-20240115.html",
        "nisd/nisd-20250120.html",
        "nisd/nisd-20260125.html",
        "nisd/nisd-live-20260929.html",
    }
    for name, entry in ENTRIES.items():
        listing = nisd.parse(_body(name))
        assert listing.variant == nisd.VARIANT
        assert listing.state is entry.expected.state
        assert len(listing.rows) == entry.expected.rows
        assert nisd.slice_body(_body(name)) == _body(name)
    assert ENTRIES["nisd/nisd-live-20260929.html"].mode is ReadMode.LIVE


def test_the_january_2025_snow_and_the_holiday() -> None:
    listing = nisd.parse(_body("nisd/nisd-20250120.html"))
    snow, holiday = listing.rows
    assert snow.name == DISTRICT
    assert snow.status.endswith("Northside ISD is canceling classes for Tuesday, Jan. 21.")
    assert snow.extra == {
        "level": "alert",
        "icon": "fa-cloud-showers-heavy",
        "link": "/news/weather-watch-update",
    }
    assert (
        holiday.status == "Schools and offices are closed Jan. 20 for Martin Luther King, Jr. Day."
    )
    assert holiday.extra == {"level": "info", "icon": "fa-info", "link": None}
    # The notice gate: the snow closing proves the channel, the holiday does not.
    assert notices.row_qualifies(snow.name, snow.status, listing.variant)
    assert not notices.row_qualifies(holiday.name, holiday.status, listing.variant)


def test_the_january_2026_cold_and_an_ordinary_holiday() -> None:
    (cold,) = nisd.parse(_body("nisd/nisd-20260125.html")).rows
    assert cold.status.startswith("Weather Update - Jan. 24, 2026: In light of the extreme cold")
    assert "all District offices and schools will be closed on Monday, Jan. 26." in cold.status
    assert cold.extra["icon"] == "fa-snowflake"
    assert notices.row_qualifies(cold.name, cold.status, nisd.VARIANT)
    (mlk,) = nisd.parse(_body("nisd/nisd-20240115.html")).rows
    assert not notices.row_qualifies(mlk.name, mlk.status, nisd.VARIANT)


def test_the_live_homepage_holds_an_empty_view() -> None:
    listing = nisd.parse(_body("nisd/nisd-live-20260929.html"))
    assert (listing.state, listing.rows, listing.skipped_rows) == (ListingState.EMPTY, (), 0)


def _synthetic(rows: str, title: str = "Synthetic ISD | Home") -> bytes:
    view = f'<div class="view view-notices"><div class="view-content">{rows}</div></div>'
    return f"<html><head><title>{title}</title></head><body>{view}</body></html>".encode()


def test_synthetic_edge_cases() -> None:
    # A SYNTHETIC notice with no words is skipped; a long one is cut to the status limit.
    blank = (
        '<div class="views-row"><div class="notice--info row"><div role="alert"> </div></div></div>'
    )
    long_words = "x" * (MAX_STATUS + 10)
    long_row = f'<div class="views-row"><div role="alert"><p>{long_words}</p></div></div>'
    listing = nisd.parse(_synthetic(blank + long_row))
    assert listing.skipped_rows == 1
    (row,) = listing.rows
    assert (row.name, len(row.status)) == ("Synthetic ISD", MAX_STATUS)
    assert row.extra == {"level": None, "icon": None, "link": None}
    with pytest.raises(ShapeError, match="no notices view"):
        nisd.parse(b"<html><head><title>T</title></head><body><p>x</p></body></html>")
    with pytest.raises(ShapeError, match="no title"):
        nisd.parse(_synthetic(long_row, title=""))
    assert nisd.slice_body(b"<html><head><title>T</title></head><body></body></html>") == (
        document("<title>T</title>")
    )


def test_the_registry_entry() -> None:
    registry = load_registry()
    station = registry.stations["nisd-northside-tx"]
    assert station.leaids == ("4833120",)
    assert station.counties is not None
    assert station.counties.fips == ("48029",)
    assert station.page_url == "https://www.nisd.net/"
    assert station.robots
    assert all(check.allowed for check in station.robots)
    assert registry.platforms["nisd"].terms.pollable
    assert "nisd" in notices.GENERAL_CHANNEL_ADAPTERS
    assert nisd.VARIANT in notices.ORG_NAMED_VARIANTS
