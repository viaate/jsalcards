"""DMA county lists (real slices of the published files) and the coverage measure.

fixtures/reference/ holds verbatim slices of the pinned DMA crosswalk and the
Census 2025 county Gazetteer, and the whole Census Connecticut crosswalk; see
fixtures/reference/PROVENANCE.json. The school tables and station registries built
here are synthetic.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import polars as pl
import pytest
import yaml  # type: ignore[import-untyped, unused-ignore]
from shapely.geometry import box

from snowlight.output import JSONValue
from snowlight.sources.stations import coverage, dma
from snowlight.sources.stations.cli import county_mismatches
from snowlight.sources.stations.mapimage import albers, png_bytes, project, render
from snowlight.sources.stations.model import HealthStatus, SourceHealth
from snowlight.sources.stations.registry import load_registry
from snowlight.weights.schools import PlacedSchool, Placement

REFERENCE = Path(__file__).parent / "fixtures" / "reference"


def _checked(name: str) -> Path:
    provenance = json.loads((REFERENCE / "PROVENANCE.json").read_text(encoding="utf-8"))
    path = REFERENCE / name
    assert hashlib.sha256(path.read_bytes()).hexdigest() == provenance[name]["sha256"]
    return path


@pytest.fixture(scope="module")
def markets() -> dma.DmaCounties:
    return dma.read_crosswalk(
        _checked("usa-tvdma-county.slice.csv"),
        dma.read_gazetteer(_checked("2025_Gaz_counties_national.slice.zip")),
        dma.read_ct_regions(_checked("ct_cou_to_cousub_crosswalk.xlsx")),
    )


def test_kansas_city_market_resolves_to_fips(markets: dma.DmaCounties) -> None:
    kansas_city = markets.by_dma["Kansas City, MO - KS DMA"]
    assert len(kansas_city) == 29
    assert "20091" in kansas_city  # Johnson County, Kansas
    assert "29095" in kansas_city  # Jackson County, Missouri
    assert all(fips[:2] in {"20", "29"} for fips in kansas_city)


def test_connecticut_counties_become_planning_regions(markets: dma.DmaCounties) -> None:
    hartford = set(markets.by_dma["Hartford & New Haven, CT DMA"])
    new_york = set(markets.by_dma["New York, NY - CT - NJ - PA DMA"])
    assert all(fips.startswith("091") for fips in hartford | new_york)
    # Fairfield County's towns sit in three planning regions; two of them also
    # hold towns of counties in the Hartford market.
    assert new_york == {"09120", "09140", "09190"}
    assert markets.dma_of("09190") == (
        "Hartford & New Haven, CT DMA",
        "New York, NY - CT - NJ - PA DMA",
    )


def test_renamed_and_independent_city_counties(markets: dma.DmaCounties) -> None:
    placed = {fips for counties in markets.by_dma.values() for fips in counties}
    assert "46102" in placed  # Oglala Lakota, written SHANNON in the list
    assert "12086" in placed  # Miami-Dade, written DADE
    assert {"51059", "51600"} <= placed  # Fairfax County and Fairfax city
    assert {"29189", "29510"} <= placed  # St. Louis County and St. Louis city
    unmatched = {(state, county) for state, county, _dma in markets.unmatched}
    assert ("VA", "BEDFORD CITY") in unmatched
    assert not any(state == "AK" for state, _county in unmatched)


def test_normalize_county() -> None:
    assert dma.normalize_county("St. Louis") == dma.normalize_county("SAINT LOUIS")
    assert dma.normalize_county("DeKalb") == dma.normalize_county("DE KALB")
    assert dma.normalize_county("Doña Ana") == "DONAANA"


def test_bad_crosswalk_header(tmp_path: Path) -> None:
    path = tmp_path / "x.csv"
    path.write_text("A,B,C\n", encoding="utf-8")
    with pytest.raises(dma.DmaError):
        dma.read_crosswalk(path, [], dma.CtRegions({}, {}))


def _registry(tmp_path: Path) -> Path:
    folder = tmp_path / "sources"
    folder.mkdir()
    terms = {
        "automated_access": "permitted",
        "summary": "synthetic",
        "evidence": [
            {
                "url": "https://x.test/t",
                "read_at": "2026-09-25T00:00:00Z",
                "sha256": None,
                "excerpt": ["ok"],
            }
        ],
    }
    forbidding = {**terms, "automated_access": "forbidden"}
    for pid, platform_terms, stations in (
        ("open", terms, [("open-a", ["20091", "29095"], "Kansas City, MO - KS DMA")]),
        ("barred", forbidding, [("barred-b", ["29047", "29095"], "Kansas City, MO - KS DMA")]),
    ):
        content = {
            "platform": {
                "id": pid,
                "name": "synthetic",
                "operator": "synthetic",
                "adapter": "gray",
                "poll_minutes": 10,
                "terms": platform_terms,
                "notes": "synthetic",
            },
            "stations": [
                {
                    "id": sid,
                    "platform": pid,
                    "call_sign": sid.split("-")[1].upper() + "XXX",
                    "name": sid,
                    "market": "Kansas City",
                    "dma": label,
                    "states": ["KS", "MO"],
                    "counties": {"basis": "dma", "source": "synthetic", "fips": fips},
                    "page_url": f"https://{sid}.test/closings",
                    "data_url": None,
                    "archive_urls": [],
                    "poll_minutes": None,
                    "status": "active",
                    "evidence": "synthetic",
                }
                for sid, fips, label in stations
            ],
        }
        (folder / f"{pid}.yaml").write_text(yaml.safe_dump(content), encoding="utf-8")
    return folder


def _dig(value: JSONValue, *keys: str) -> JSONValue:
    for key in keys:
        assert isinstance(value, dict)
        value = value[key]
    return value


SCHOOLS = pl.DataFrame(
    {
        "state": ["KS", "KS", "MO", "MO", "MO", "NE"],
        "county_fips": ["20091", "20091", "29095", "29047", "29047", "31055"],
        "county_name": ["Johnson County"] * 2
        + ["Jackson County"]
        + ["Clay County"] * 2
        + ["Douglas County"],
    }
)


def _health(
    status: HealthStatus, reason: str | None = None, source_id: str = "open-a"
) -> SourceHealth:
    return SourceHealth.model_validate(
        {
            "source_id": source_id,
            "url": f"https://{source_id}.test/closings",
            "checked_at": "2026-01-26T12:00:00Z",
            "status": status,
            "rows": 3 if status is HealthStatus.OK else 0,
            "reason": reason,
        }
    )


def test_measure_counts_working_sources_only(tmp_path: Path, markets: dma.DmaCounties) -> None:
    registry = load_registry(_registry(tmp_path))
    skipped = _health(
        HealthStatus.SKIPPED, "robots.txt disallows this URL for our User-Agent", "barred-b"
    )
    states = coverage.station_states(
        registry, {"open-a": _health(HealthStatus.OK), "barred-b": skipped}
    )
    assert states["open-a"].state == "working"
    assert states["barred-b"] == coverage.StationState("skipped", skipped.reason)
    result = coverage.measure(registry, SCHOOLS, states, markets)
    national = result["national"]
    assert isinstance(national, dict)
    assert national == {"schools": 6, "covered": 3, "share": 0.5, "meets_target": False}
    states_out = result["states"]
    assert isinstance(states_out, dict)
    assert states_out["KS"] == {"schools": 2, "covered": 2, "share": 1.0, "meets_target": True}
    assert _dig(result, "counties", "29095", "working") == ["open-a"]
    assert _dig(result, "counties", "29095", "not_working") == ["barred-b"]
    assert _dig(result, "counties", "29047", "working") == []
    assert result["counties_without_dma"] == ["31055"]
    assert _dig(result, "dmas", "Kansas City, MO - KS DMA", "working") == ["open-a"]
    assert _dig(result, "dmas", "Kansas City, MO - KS DMA", "not_working") == ["barred-b"]
    summary = result["dma_summary"]
    assert isinstance(summary, dict)
    assert summary["with_a_working_source"] == 1
    assert summary["with_two_or_more_working"] == 0


def test_terms_do_not_reduce_coverage(tmp_path: Path, markets: dma.DmaCounties) -> None:
    """A station whose platform's terms forbid automated access counts once it reads cleanly."""
    registry = load_registry(_registry(tmp_path))
    assert registry.platforms["barred"].terms.automated_access.value == "forbidden"
    health = {
        "open-a": _health(HealthStatus.OK),
        "barred-b": _health(HealthStatus.EMPTY, source_id="barred-b"),
    }
    states = coverage.station_states(registry, health)
    assert states["barred-b"].state == "working"
    result = coverage.measure(registry, SCHOOLS, states, markets)
    assert _dig(result, "national", "covered") == 5  # plus Clay (2)
    summary = result["dma_summary"]
    assert isinstance(summary, dict)
    assert summary["with_two_or_more_working"] == 1


def test_failed_or_missing_reads_do_not_count(tmp_path: Path) -> None:
    registry = load_registry(_registry(tmp_path))
    failed = coverage.station_states(registry, {"open-a": _health(HealthStatus.ERROR, "HTTP 500")})
    assert failed["open-a"].state == "error"
    missing = coverage.station_states(registry, {})
    assert missing["open-a"].state == "not_read"
    result = coverage.measure(registry, SCHOOLS, missing, None)
    national = result["national"]
    assert isinstance(national, dict)
    assert national["covered"] == 0


def test_directory_without_counties_is_an_error(tmp_path: Path) -> None:
    registry = load_registry(_registry(tmp_path))
    with pytest.raises(coverage.CoverageError):
        coverage.measure(registry, pl.DataFrame({"state": ["KS"]}), {}, None)


def test_write_coverage_and_png(tmp_path: Path) -> None:
    registry = load_registry(_registry(tmp_path))
    states = coverage.station_states(registry, {"open-a": _health(HealthStatus.EMPTY)})
    result = coverage.measure(registry, SCHOOLS, states, None)
    directory = tmp_path / "schools.parquet"
    SCHOOLS.write_parquet(directory)
    shapes = {
        "20091": box(-95.1, 38.7, -94.6, 39.0),
        "29095": box(-94.6, 38.8, -94.1, 39.1),
        "29047": box(-94.6, 39.1, -94.2, 39.4),
    }
    projected = {key: project(shape) for key, shape in shapes.items()}
    references: dict[str, JSONValue] = {"dma": {"url": "https://example.test/dma.csv"}}
    meta = coverage.CoverageMeta(
        datetime(2026, 9, 25, tzinfo=UTC), "2026-09-24T23:00:00Z", directory, references
    )
    paths = coverage.write_coverage(tmp_path / "out", result, meta, projected)
    document = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert document["directory"]["schools"] == 6
    assert document["references"] == references
    png = paths["png"].read_bytes()
    assert png.startswith(b"\x89PNG\r\n\x1a\n")


def test_albers_origin_and_png_encoding() -> None:
    x, y = albers(np.array([-96.0]), np.array([37.5]))
    assert abs(float(x[0])) < 1e-12
    assert abs(float(y[0])) < 1e-12
    image = render({"a": box(0, 0, 1, 1)}, {"a": (255, 0, 0)}, width=60)
    assert image.shape[1] == 60
    assert (image == np.array([255, 0, 0], dtype=np.uint8)).all(axis=2).any()
    assert png_bytes(image)[:8] == b"\x89PNG\r\n\x1a\n"
    with pytest.raises(ValueError, match="RGB"):
        png_bytes(image[:, :, 0])


def test_county_mismatches(tmp_path: Path, markets: dma.DmaCounties) -> None:
    registry = load_registry(_registry(tmp_path))
    problems = county_mismatches(registry, markets)
    # Both synthetic stations list two of the market's 29 counties.
    assert problems == [
        "barred-b: 2 listed, 29 in market",
        "open-a: 2 listed, 29 in market",
    ]


def test_stale_reads_do_not_count(tmp_path: Path, markets: dma.DmaCounties) -> None:
    """A list file nothing has written to since the last winter began is not working."""
    registry = load_registry(_registry(tmp_path))
    stale = _health(HealthStatus.STALE, "the list file was last modified 2022-02-10T16:02:11Z")
    states = coverage.station_states(registry, {"open-a": stale})
    assert states["open-a"] == coverage.StationState("stale", stale.reason)
    result = coverage.measure(registry, SCHOOLS, states, markets)
    assert _dig(result, "national", "covered") == 0
    assert _dig(result, "counties", "29095", "not_working") == ["barred-b", "open-a"]
    assert _dig(result, "stations", "open-a", "state") == "stale"


def _weights(tmp_path: Path, weights: dict[str, float]) -> Path:
    # Synthetic weights in the shape of the weights build's closure-weights.json.
    path = tmp_path / "closure-weights.json"
    counties = [{"fips": fips, "weight": weight} for fips, weight in weights.items()]
    path.write_text(json.dumps({"generated_at": "2026-09-26T22:31:13Z", "counties": counties}))
    return path


def test_weighted_shares(tmp_path: Path, markets: dma.DmaCounties) -> None:
    registry = load_registry(_registry(tmp_path))
    weights = coverage.load_weights(
        _weights(tmp_path, {"20091": 2.0, "29095": 1.0, "29047": 0.25, "31055": 0.5})
    )
    assert weights.provenance["counties"] == 4
    states = coverage.station_states(registry, {"open-a": _health(HealthStatus.OK)})
    result = coverage.measure(registry, SCHOOLS, states, markets, weights=weights)
    # Covered: Johnson (2 schools x 2.0) and Jackson (1 x 1.0) of 4 + 1 + 0.5 + 0.5 = 6.0.
    assert _dig(result, "national", "weighted") == {
        "schools": 6.0,
        "covered": 5.0,
        "share": 0.8333,
        "meets_target": False,
    }
    assert _dig(result, "national", "share") == 0.5
    assert _dig(result, "states", "MO", "weighted") == {
        "schools": 1.5,
        "covered": 1.0,
        "share": 0.6667,
        "meets_target": False,
    }
    assert _dig(result, "counties", "20091", "weighted_schools") == 4.0
    assert _dig(result, "stations", "open-a", "weighted_schools") == 5.0
    assert _dig(result, "weights", "schools_without_weight") == 0


def test_schools_in_counties_without_a_weight_count_only_plainly(
    tmp_path: Path, markets: dma.DmaCounties
) -> None:
    registry = load_registry(_registry(tmp_path))
    weights = coverage.load_weights(_weights(tmp_path, {"20091": 1.0}))
    states = coverage.station_states(registry, {"open-a": _health(HealthStatus.OK)})
    result = coverage.measure(registry, SCHOOLS, states, markets, weights=weights)
    assert _dig(result, "weights", "schools_without_weight") == 4
    assert _dig(result, "national", "weighted", "schools") == 2.0
    assert _dig(result, "national", "schools") == 6


def test_bad_weights_are_an_error(tmp_path: Path) -> None:
    path = tmp_path / "w.json"
    path.write_text(json.dumps({"counties": [{"fips": "2009", "weight": 1.0}]}))
    with pytest.raises(coverage.CoverageError, match="FIPS"):
        coverage.load_weights(path)
    path.write_text(json.dumps({"counties": []}))
    with pytest.raises(coverage.CoverageError, match="no county list"):
        coverage.load_weights(path)


def test_each_school_counts_its_own_nws_countys_weight(
    tmp_path: Path, markets: dma.DmaCounties
) -> None:
    """A Connecticut school's directory county is a planning region; the weights build
    places it in the NWS county it stands in, and it counts that county's weight."""
    registry = load_registry(_registry(tmp_path))
    weights = coverage.load_weights(_weights(tmp_path, {"20091": 2.0, "29095": 1.0, "09003": 0.5}))
    placement = Placement(
        schools=[
            PlacedSchool(0, "a", "KS", "KS", "20091", "20091", "fips"),
            PlacedSchool(1, "b", "CT", "KS", "20091", "09003", "point"),  # synthetic placement
            PlacedSchool(2, "c", "MO", "MO", "29095", "29095", "fips"),
        ],
        unplaced=["d"],
    )
    placed = weights.placed(placement)
    states = coverage.station_states(registry, {"open-a": _health(HealthStatus.OK)})
    result = coverage.measure(registry, SCHOOLS, states, markets, weights=placed)
    assert _dig(result, "counties", "20091", "weighted_schools") == 2.5
    assert _dig(result, "national", "weighted", "covered") == 3.5
    # Clay's two schools and Douglas's one were not placed with a weight.
    assert _dig(result, "weights", "schools_without_weight") == 3
    assert _dig(result, "weights", "unplaced_schools") == 1
