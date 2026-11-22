"""The airports table: its builder on made-up inputs, and the committed table itself."""

import json
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from snowlight.flights import airports

HEADER = (
    "id,ident,type,name,latitude_deg,longitude_deg,elevation_ft,continent,iso_country,"
    "iso_region,municipality,scheduled_service,icao_code,iata_code,gps_code,local_code,"
    "home_link,wikipedia_link,keywords"
)
ROWS = (
    "1,KAAA,large_airport,Synthetic Field One,39.1,-94.1,1000,NA,US,US-MO,Synthetic City,"
    "yes,KAAA,AAA,KAAA,AAA,,,",
    "2,KNEW,large_airport,Synthetic Field Renamed,26.6,-80.1,19,NA,US,US-FL,Synthetic Beach,"
    "yes,KNEW,NEW,KNEW,NEW,,,",
    "3,XX-1,small_airport,Elsewhere Strip,1.0,1.0,1,AF,XX,XX-1,Far,no,,AAA,,,,,",
)
OURAIRPORTS = "\n".join((HEADER, *ROWS)) + "\n"


def _stations(tmp_path: Path) -> list[Path]:
    features = [
        {
            "id": "AAA",
            "properties": {
                "sname": "SYNTHETIC ONE",
                "tzname": "America/Chicago",
                "wfo": "XXX",
                "ugc_zone": "MOZ001",
                "ugc_county": "MOC001",
            },
            "geometry": {"coordinates": [-94.0, 39.0]},
        },
        {
            "id": "NEW",
            "properties": {
                "sname": "SYNTHETIC NEW",
                "tzname": "America/New_York",
                "wfo": None,
                "ugc_zone": None,
                "ugc_county": None,
            },
            "geometry": {"coordinates": [-80.0, 26.0]},
        },
        {
            "id": "PZZZ",
            "properties": {"sname": "SYNTHETIC FAR", "tzname": "Pacific/Guam"},
            "geometry": {"coordinates": [144.0, 13.0]},
        },
    ]
    path = tmp_path / "XX_ASOS.geojson"
    path.write_text(json.dumps({"features": features}))
    return [path]


def test_the_builder_joins_flights_names_and_stations(tmp_path: Path) -> None:
    named_path = tmp_path / "airports.csv"
    named_path.write_text(OURAIRPORTS)
    named = airports.read_ourairports(named_path)
    stations = airports.read_stations(_stations(tmp_path))
    day = [date(2026, 9, 1), date(2026, 9, 2)]
    dep = pl.DataFrame(
        {
            "apt": ["AAA", "AAA", "OLD", "ZZZ", "PZZ"],
            "day": day + day + day[:1],
            "n": [100, 100, 40, 5, 5],
        }
    )
    places = pl.DataFrame(
        {
            "apt": ["AAA", "OLD", "ZZZ", "PZZ"],
            "city": ["Synthetic City, MO", "Synthetic Beach, FL", "Nowhere, ZZ", "Far, GU"],
            "state": ["MO", "FL", "ZZ", "GU"],
            "n": [1, 1, 1, 1],
        }
    )
    original = dict(airports.RENAMED)
    airports.RENAMED.clear()
    airports.RENAMED["OLD"] = "NEW"
    try:
        built, left = airports.build(dep, places, named, stations, frozenset({"KAAA", "KOLD"}))
    finally:
        airports.RENAMED.clear()
        airports.RENAMED.update(original)
    codes = [a.code for a in built]
    assert codes == ["AAA", "NEW"]
    assert sorted(left) == ["PZZ: no weather station", "ZZZ: no weather station"]
    aaa, new = built
    assert (aaa.name, aaa.city, aaa.tz, aaa.zone, aaa.per_day) == (
        "Synthetic Field One",
        "Synthetic City",
        "America/Chicago",
        "MOZ001",
        100.0,
    )
    assert new.icao == "KOLD"  # the bulletin still uses the old code
    assert new.wfo == ""
    path = tmp_path / "out.json"
    airports.dump(built, path)
    assert airports.load(path) == tuple(built)


def test_the_committed_table() -> None:
    table = airports.load()
    codes = [a.code for a in table]
    assert len(codes) == len(set(codes)) >= 300
    assert all(len(a.icao) == 4 and len(a.code) == 3 for a in table)
    for a in table:
        ZoneInfo(a.tz)
        assert -180 <= a.lon <= 180
        assert -90 <= a.lat <= 90
    assert "PBI" not in codes
    assert "DJT" in codes
    assert [a.per_day for a in table] == sorted((a.per_day for a in table), reverse=True)
