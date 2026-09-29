"""District-level coverage (``Station.leaids``): a source covers its districts' schools only.

The framework change of piece s4d: an optional ``leaids`` field on a station (NCES
district IDs, with the ``district`` county basis) and
:func:`snowlight.sources.stations.coverage.district_cover`, which the coverage
measure uses to count exactly those districts' schools, never their counties
whole. Every registry, school table and weight here is synthetic.
"""

import json
from typing import Any

import numpy as np
import polars as pl
import pytest
from pydantic import ValidationError
from shapely.geometry import box

from snowlight.output import JSONValue
from snowlight.sources.stations import coverage
from snowlight.sources.stations.coverage import StationState
from snowlight.sources.stations.mapimage import project
from snowlight.sources.stations.registry import (
    PlatformFile,
    Registry,
    Station,
    dump_platform_file,
    load_registry,
)
from snowlight.weights.schools import PlacedSchool, Placement

TERMS = {
    "automated_access": "permitted",
    "summary": "synthetic",
    "evidence": [
        {
            "url": "https://x.test/t",
            "read_at": "2026-09-27T00:00:00Z",
            "sha256": None,
            "excerpt": ["ok"],
        }
    ],
}


def _station(sid: str, fips: list[str], leaids: list[str] | None = None) -> dict[str, Any]:
    district = leaids is not None
    return {
        "id": sid,
        "platform": sid.split("-", 1)[0],
        "call_sign": "SYN" + sid.split("-", 1)[1].upper(),
        "name": "synthetic",
        "market": "synthetic",
        "dma": None if district else "Kansas City, MO - KS DMA",
        "states": ["KS"],
        "counties": {
            "basis": "district" if district else "dma",
            "source": f"synthetic list for {sid}",
            "fips": fips,
        },
        "page_url": f"https://{sid}.test/",
        "data_url": None,
        "archive_urls": [],
        "poll_minutes": None,
        "status": "active",
        "evidence": "synthetic",
        **({"leaids": leaids} if district else {}),
    }


def _registry(*stations: dict[str, Any]) -> Registry:
    files: dict[str, PlatformFile] = {}
    by_platform: dict[str, list[dict[str, Any]]] = {}
    for item in stations:
        by_platform.setdefault(item["platform"], []).append(item)
    for pid, items in by_platform.items():
        files[pid] = PlatformFile.model_validate_json(
            json.dumps(
                {
                    "platform": {
                        "id": pid,
                        "name": "synthetic",
                        "operator": "synthetic",
                        "adapter": "gray",
                        "poll_minutes": 10,
                        "terms": TERMS,
                        "notes": "synthetic",
                    },
                    "stations": items,
                }
            )
        )
    return Registry(files)


def _schools() -> pl.DataFrame:
    """14 schools: county 20091 (6), 20093 (6), 20095 (2); private schools have no district."""
    rows = [
        *[("20091", "2000001")] * 3,
        *[("20091", "2000002")] * 2,
        ("20091", None),
        *[("20093", "2000001")] * 2,
        *[("20093", "2000003")] * 3,
        ("20093", None),
        *[("20095", "2000009")] * 2,
    ]
    return pl.DataFrame(
        {
            "index": list(range(len(rows))),
            "state": ["KS"] * len(rows),
            "county_fips": [fips for fips, _ in rows],
            "county_name": [f"County {fips}" for fips, _ in rows],
            "district_id": [leaid for _, leaid in rows],
        },
        schema={
            "index": pl.UInt32,
            "state": pl.String,
            "county_fips": pl.String,
            "county_name": pl.String,
            "district_id": pl.String,
        },
    )


REGISTRY = _registry(
    _station("open-a", ["20091"]),
    _station("dist-x", ["20091", "20093"], ["2000001"]),
    _station("dist-y", ["20093"], ["2000003"]),
)
STATES = {
    "open-a": StationState("working", None),
    "dist-x": StationState("working", None),
    "dist-y": StationState("error", "HTTP 500"),
}


def _county(result: dict[str, JSONValue], fips: str) -> dict[str, JSONValue]:
    counties = result["counties"]
    assert isinstance(counties, dict)
    entry = counties[fips]
    assert isinstance(entry, dict)
    return entry


def test_district_source_covers_only_its_districts_schools() -> None:
    result = coverage.measure(REGISTRY, _schools(), STATES, None)
    assert result["national"] == {
        "schools": 14,
        "covered": 8,  # 20091 whole (6) and dist-x's 2 schools in 20093
        "share": round(8 / 14, 4),
        "meets_target": False,
    }
    whole, part, none = (_county(result, f) for f in ("20091", "20093", "20095"))
    assert whole["working"] == ["open-a"]
    assert whole["covered"] == 6
    assert whole["districts"] == ["dist-x"]
    assert part["working"] == []
    assert part["districts"] == ["dist-x"]
    assert part["districts_not_working"] == ["dist-y"]
    assert part["covered"] == 2
    assert none["covered"] == 0
    assert none["districts"] == []
    assert result["districts"] == {
        "sources": ["dist-x", "dist-y"],
        "working": ["dist-x"],
        "schools_added": 2,
        "weighted_added": None,
    }


def test_district_stations_count_their_districts_schools() -> None:
    result = coverage.measure(REGISTRY, _schools(), STATES, None)
    stations = result["stations"]
    assert isinstance(stations, dict)
    x, y, a = stations["dist-x"], stations["dist-y"], stations["open-a"]
    assert isinstance(x, dict)
    assert isinstance(y, dict)
    assert isinstance(a, dict)
    assert x["schools"] == 5  # its district's 3 + 2 schools, not its two counties' 12
    assert x["leaids"] == ["2000001"]
    assert y["schools"] == 3
    assert y["state"] == "error"
    assert a["schools"] == 6
    assert "leaids" not in a


def test_a_district_source_is_never_a_whole_county_or_a_market() -> None:
    working, down = coverage._station_counties(REGISTRY, STATES)
    assert working == {"20091": ["open-a"]}
    assert down == {}
    only_districts = _registry(_station("dist-x", ["20091"], ["2000001"]))
    result = coverage.measure(
        only_districts, _schools(), {"dist-x": StationState("working", None)}, None
    )
    national = result["national"]
    assert isinstance(national, dict)
    assert national["covered"] == 5
    assert result["dma_summary"] == {
        "markets": 0,
        "with_a_working_source": 0,
        "with_two_or_more_working": 0,
        "biggest_by_schools": [],
    }


def test_no_district_column_counts_no_district_school() -> None:
    frame = _schools().drop("district_id")
    result = coverage.measure(REGISTRY, frame, STATES, None)
    national = result["national"]
    assert isinstance(national, dict)
    assert national["covered"] == 6
    assert _county(result, "20093")["districts"] == []


def test_district_sources_not_working_cover_nothing() -> None:
    states = {**STATES, "dist-x": StationState("stale", "old")}
    cover = coverage.district_cover(REGISTRY, _schools(), states)
    assert cover.covered == {}
    assert cover.working == {}
    assert cover.down == {"20091": ["dist-x"], "20093": ["dist-x", "dist-y"]}
    assert cover.station_schools == {"dist-x": 5, "dist-y": 3}


def test_weighted_district_share_uses_county_weights() -> None:
    weights = coverage.Weights({"20091": 1.0, "20093": 2.0, "20095": 0.5}, {"path": "w.json"})
    result = coverage.measure(REGISTRY, _schools(), STATES, None, weights=weights)
    national = result["national"]
    assert isinstance(national, dict)
    assert national["weighted"] == {
        "schools": 19.0,  # 6 x 1 + 6 x 2 + 2 x 0.5
        "covered": 10.0,  # 6 x 1 + dist-x's 2 x 2
        "share": round(10 / 19, 4),
        "meets_target": False,
    }
    districts = result["districts"]
    assert isinstance(districts, dict)
    assert districts["weighted_added"] == 4.0


def test_weighted_district_share_uses_each_schools_own_weight() -> None:
    # Placed in NWS counties, dist-x's two schools in 20093 stand in NWS counties
    # of weight 3 and 5 (a Connecticut-style directory county), the rest in 20093's.
    by_county = {"20091": 1.0, "20093": 2.0, "20095": 0.5, "90001": 3.0, "90002": 5.0}
    schools = _schools()
    placed = []
    for row in schools.iter_rows(named=True):
        nws = {6: "90001", 7: "90002"}.get(int(row["index"]), str(row["county_fips"]))
        placed.append(
            PlacedSchool(
                index=int(row["index"]),
                school_id=str(row["index"]),
                state="KS",
                address_state="KS",
                directory_fips=str(row["county_fips"]),
                nws_fips=nws,
                method="fips",
            )
        )
    weights = coverage.Weights(by_county, {"path": "w.json"}).placed(Placement(placed))
    assert weights.school(6, "20093") == 3.0
    assert weights.school(None, "20093") is None
    result = coverage.measure(REGISTRY, schools, STATES, None, weights=weights)
    part = coverage.district_cover(REGISTRY, schools, STATES, weights)
    assert part.weighted == {("20091", "KS"): 3.0, ("20093", "KS"): 8.0}
    national = result["national"]
    assert isinstance(national, dict)
    weighted = national["weighted"]
    assert isinstance(weighted, dict)
    assert weighted["covered"] == 14.0  # 6 x 1 + 3 + 5
    assert weighted["schools"] == 6.0 + 3.0 + 5.0 + 4 * 2.0 + 2 * 0.5


def test_partly_covered_county_has_its_own_colour(monkeypatch: pytest.MonkeyPatch) -> None:
    result = coverage.measure(REGISTRY, _schools(), STATES, None)
    shapes = {
        "20091": box(-95.0, 38.0, -94.5, 38.5),
        "20093": box(-94.5, 38.0, -94.0, 38.5),
        "20095": box(-94.0, 38.0, -93.5, 38.5),
    }
    drawn: list[np.ndarray[Any, Any]] = []

    def keep(image: np.ndarray[Any, Any]) -> bytes:
        drawn.append(image)
        return b""

    monkeypatch.setattr(coverage, "png_bytes", keep)
    coverage.render_png(result, {fips: project(s) for fips, s in shapes.items()})
    colours = {tuple(int(v) for v in pixel) for pixel in drawn[0].reshape(-1, 3)}
    assert coverage.PART_COLOR in colours
    assert coverage.WORKING_COLOR in colours
    assert coverage.GAP_COLOR in colours


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"leaids": ["2000002", "2000001"]}, "LEAIDs are listed once each"),
        ({"leaids": ["2000001", "2000001"]}, "LEAIDs are listed once each"),
        ({"leaids": ["200001"]}, "String should match pattern"),
        ({"leaids": []}, "a district-level source names its LEAIDs"),
    ],
)
def test_leaids_are_checked(change: dict[str, Any], message: str) -> None:
    item = {**_station("dist-x", ["20091"], ["2000001"]), **change}
    with pytest.raises(ValidationError, match=message):
        Station.model_validate_json(json.dumps(item))


def test_leaids_need_the_district_basis_and_it_needs_leaids() -> None:
    county = _station("open-a", ["20091"])
    with pytest.raises(ValidationError, match="a district-level source names its LEAIDs"):
        Station.model_validate_json(json.dumps({**county, "leaids": ["2000001"]}))
    district = _station("dist-x", ["20091"], ["2000001"])
    del district["leaids"]
    with pytest.raises(ValidationError, match="a district-level source names its LEAIDs"):
        Station.model_validate_json(json.dumps(district))


def test_registered_district_sources_are_well_formed() -> None:
    registry = load_registry()
    districts = [s for s in registry.stations.values() if s.leaids]
    assert districts, "at least one district-level source is registered"
    for station in districts:
        assert station.counties is not None
        assert station.counties.basis.value == "district"
        assert station.dma is None, station.id
        assert station.id in station.counties.source


# Statewide lists that name school systems: a system on one may also have its own site.
STATEWIDE_LISTS = {"alsde-statewide", "gohsep-parish-schools"}


def test_no_district_is_claimed_by_two_of_its_own_sites() -> None:
    """A district's own site is one source; only a statewide list may name it again.

    The coverage measure counts each school once however many sources name its district
    (coverage.district_covered), so the overlap never counts a school twice.
    """
    registry = load_registry()
    owners: dict[str, list[str]] = {}
    for station in registry.stations.values():
        if station.id in STATEWIDE_LISTS:
            continue
        for leaid in station.leaids:
            owners.setdefault(leaid, []).append(station.id)
    assert {leaid: ids for leaid, ids in owners.items() if len(ids) > 1} == {}
    for list_id in STATEWIDE_LISTS:
        # each statewide list names its own state's districts, each once
        station = registry.stations[list_id]
        assert len(set(station.leaids)) == len(station.leaids)
        assert {leaid[:2] for leaid in station.leaids} == {
            {"AL": "01", "LA": "22"}[state] for state in station.states
        }


def test_a_district_sites_basis_names_its_districts() -> None:
    """Each district site's county list says which LEAIDs it counts and how they were found."""
    platforms = {"apptegy", "finalsite", "smartsites"}
    for station in load_registry().stations.values():
        if station.platform not in platforms:
            continue
        assert station.counties is not None
        for leaid in station.leaids:
            assert leaid in station.counties.source, station.id


def test_only_district_sources_write_leaids_to_their_yaml() -> None:
    registry = _registry(_station("open-a", ["20091"]), _station("dist-x", ["20091"], ["2000001"]))
    county = dump_platform_file(registry.files["open"]).decode()
    district = dump_platform_file(registry.files["dist"]).decode()
    assert "leaids" not in county
    assert "leaids: ['2000001']" in district
