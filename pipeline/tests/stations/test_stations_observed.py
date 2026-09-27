"""Counties named in real archived lists, resolved and compared with county lists.

The rows come from real fixtures (fixtures/hearst/, fixtures/gray/); the reference
files are the real slices in fixtures/reference/ (the Gazetteer slice holds AK, CT,
FL, KS, MO, SD and VA only, so places in other states stay unmatched here).
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from snowlight.sources.stations import dma, gray, hearst, observed
from snowlight.sources.stations.coverage import observed_check
from snowlight.sources.stations.fetch import stamp_rows
from snowlight.sources.stations.registry import DEFAULT_REGISTRY_DIR, load_registry

FIXTURES = Path(__file__).parent / "fixtures"
REFERENCE = FIXTURES / "reference"
WHEN = datetime(2025, 1, 8, 11, 26, 59, tzinfo=UTC)


def _references() -> tuple[list[dma.GazetteerCounty], dict[str, str], dma.CtRegions]:
    return (
        dma.read_gazetteer(REFERENCE / "2025_Gaz_counties_national.slice.zip"),
        observed.read_states(REFERENCE / "state.txt"),
        dma.read_ct_regions(REFERENCE / "ct_cou_to_cousub_crosswalk.xlsx"),
    )


def test_kansas_city_lists_name_counties_on_both_sides_of_the_state_line() -> None:
    gazetteer, states, connecticut = _references()
    kmbc = hearst.parse((FIXTURES / "hearst" / "kmbc-20250108112659.html").read_bytes())
    kctv = gray.parse((FIXTURES / "gray" / "kctv-20240115205330.html").read_bytes())
    rows = stamp_rows("hearst-kmbc", WHEN, kmbc) + stamp_rows("gray-kctv", WHEN, kctv)
    seen = observed.observe(rows, gazetteer, states, connecticut)
    assert seen["hearst-kmbc"].rows == 170
    assert {"29095", "20091", "29047", "20209"} <= seen["hearst-kmbc"].counties
    assert seen["hearst-kmbc"].unmatched == set()
    # KCTV's page names Linn County, Kansas and Jackson County, Missouri, and a county "Na".
    assert seen["gray-kctv"].counties == {"20107", "29095"}
    assert seen["gray-kctv"].unmatched == {"Na, MISSOURI"}


def test_real_kansas_city_rows_fall_inside_the_registered_county_lists() -> None:
    gazetteer, states, connecticut = _references()
    kmbc = hearst.parse((FIXTURES / "hearst" / "kmbc-20250108112659.html").read_bytes())
    seen = observed.observe(stamp_rows("hearst-kmbc", WHEN, kmbc), gazetteer, states, connecticut)
    per_station, summary = observed_check(load_registry(DEFAULT_REGISTRY_DIR), seen)
    entry = per_station["hearst-kmbc"]
    assert isinstance(entry, dict)
    assert entry["archived_rows"] == 170
    assert entry["counties_named"] == len(seen["hearst-kmbc"].counties)
    assert summary["stations"] == 1
    outside = entry["outside_county_list"]
    assert isinstance(outside, list)
    assert entry["in_county_list"] == entry["counties_named"] - len(outside)


def test_next_page_locations_and_connecticut_old_counties() -> None:
    _gazetteer, states, connecticut = _references()
    places = observed.row_places(
        {"locations": '[{"city":"Hartford","county":"Hartford","state":"CT"}]'}
    )
    assert places == [("CT", "Hartford")]
    row = stamp_rows(
        "demo-a",
        WHEN,
        hearst.parse((FIXTURES / "hearst" / "kmbc-20260122213928.html").read_bytes()),
    )[0]
    synthetic = row.model_copy(update={"raw_extra": {"location": "Hartford, Hartford, CT"}})
    seen = observed.observe([synthetic], [], states, connecticut)
    assert seen["demo-a"].counties  # every planning region holding a Hartford County town
    assert all(fips.startswith("09") for fips in seen["demo-a"].counties)


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        ({"county_name1": "Gallia County", "state": "OH"}, [("OH", "Gallia County")]),
        ({"county_name1": "Pamlico", "forced_county_name": "NORTH CAROLINA"},
         [("NORTH CAROLINA", "Pamlico")]),
        ({"county": "Linn", "stateAabbreviation": "KANSAS"}, [("KANSAS", "Linn")]),
        ({"county": "", "state": "KS"}, []),
        ({"location": "Jackson, Kansas City, MO | Clay, Liberty, MO"},
         [("MO", "Jackson"), ("MO", "Clay")]),
        ({"location": "Kansas City"}, []),
        ({"locations": "not json"}, []),
        ({"bucket": "f", "address": "Fort Dodge / Webster / IA"}, [("IA", "Webster")]),
        ({"bucket": "f", "address": "Fort Dodge / IA"}, []),
        ({"address": "Fort Dodge / Webster / IA"}, []),
    ],
)  # fmt: skip
def test_row_places_by_shape(extra: dict[str, str], expected: list[tuple[str, str]]) -> None:
    # Synthetic extras in the shapes the adapters keep.
    assert observed.row_places(extra) == expected


def test_state_file_shape_is_checked(tmp_path: Path) -> None:
    bad = tmp_path / "state.txt"
    bad.write_text("A|B\n1|2\n", encoding="utf-8")
    with pytest.raises(observed.ObservedError):
        observed.read_states(bad)
    assert observed.read_rows(tmp_path / "missing.jsonl") == []
