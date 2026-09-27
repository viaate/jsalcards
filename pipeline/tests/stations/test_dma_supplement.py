"""The second DMA list: placing the counties the first list has no row for.

``fixtures/dma-supplement/dma_county_zip_data_set.slice.csv`` holds real rows of the
pinned ``BritCrit/dma_county_zip`` file (see that folder's PROVENANCE.json). The
markets built here use the first list's real market names and real county codes,
but hold only a few of each market's counties: they are synthetic and named so, and
so are the one-station registries the county-list check is run on.
"""

from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped, unused-ignore]

from snowlight.sources.stations import dma
from snowlight.sources.stations.cli import county_mismatches
from snowlight.sources.stations.registry import Registry, load_registry

SLICE = Path(__file__).parent / "fixtures" / "dma-supplement" / "dma_county_zip_data_set.slice.csv"
WASHINGTON = "Washington, DC - MD - PA - VA - WV DMA"
DENVER = "Denver, CO - NE - NV - WY DMA"
MINOT = "Minot - Bismarck - Dickinson, ND - MT - SD DMA"
COUNTIES = [
    dma.GazetteerCounty("AK", "02013", "Aleutians East Borough"),
    dma.GazetteerCounty("CO", "08001", "Adams County"),
    dma.GazetteerCounty("CO", "08014", "Broomfield County"),
    dma.GazetteerCounty("CO", "08031", "Denver County"),
    dma.GazetteerCounty("DC", "11001", "District of Columbia"),
    dma.GazetteerCounty("MD", "24031", "Montgomery County"),
    dma.GazetteerCounty("ND", "38101", "Ward County"),
    dma.GazetteerCounty("ND", "38105", "Williams County"),
    dma.GazetteerCounty("VA", "51013", "Arlington County"),
    dma.GazetteerCounty("VA", "51059", "Fairfax County"),
]


def synthetic_markets() -> dma.DmaCounties:
    """The first list's markets for these counties, with its three gaps (synthetic)."""
    return dma.DmaCounties(
        by_dma={
            DENVER: ("08001", "08031"),
            MINOT: ("38101",),
            WASHINGTON: ("24031", "51013", "51059"),
        },
        unmatched=(),
    )


def test_read_supplement_keeps_markets_and_leaves_out_non_dma_counties() -> None:
    codes = dma.read_supplement(SLICE)
    assert codes["11001"] == "511"
    assert codes["08014"] == "751"
    assert codes["38105"] == "687"
    assert "02013" not in codes  # "(NON-DMA COUNTIES)", code 0
    assert len(codes) == 9


def test_fill_missing_places_only_what_the_first_list_lacks() -> None:
    filled = dma.fill_missing(synthetic_markets(), dma.read_supplement(SLICE), COUNTIES)
    # DC joins the market holding 3 of the 4 counties the slice gives code 511, and
    # Broomfield the one holding 2 of the 3 given code 751. Williams stays unplaced:
    # the market holds only 1 of the 2 counties given code 687, not more than half.
    assert filled.supplemented == (("08014", DENVER), ("11001", WASHINGTON))
    assert filled.by_dma[WASHINGTON] == ("11001", "24031", "51013", "51059")
    assert filled.by_dma[DENVER] == ("08001", "08014", "08031")
    assert filled.by_dma[MINOT] == ("38101",)
    assert filled.dma_of("11001") == (WASHINGTON,)
    # Alaska is out of scope; nothing already placed moves.
    assert filled.dma_of("02013") == ()


def test_the_second_list_overrides_nothing() -> None:
    markets = dma.DmaCounties(by_dma={MINOT: ("38101", "51059")}, unmatched=())
    filled = dma.fill_missing(markets, dma.read_supplement(SLICE), COUNTIES)
    # Fairfax stays where the first list put it, although the second list disagrees.
    assert filled.by_dma[MINOT][-1] == "51059"
    assert "51059" not in {fips for fips, _label in filled.supplemented}


@pytest.mark.parametrize(
    ("synthetic", "message"),
    [
        (b'"fips","county"\n"1","A"\n', "missing fips or dma_code"),
        (b'"fips","dma_code"\n"x","511"\n', "bad row"),
        (b'"fips","dma_code"\n"11001","511"\n"11001","512"\n', "two markets"),
        (b'"fips","dma_code"\n', "no rows"),
    ],
)
def test_synthetic_supplements_that_are_errors(
    tmp_path: Path, synthetic: bytes, message: str
) -> None:
    path = tmp_path / "synthetic.csv"
    path.write_bytes(synthetic)
    with pytest.raises(dma.DmaError, match=message):
        dma.read_supplement(path)


def _synthetic_registry(folder: Path, fips: list[str]) -> Registry:
    """A one-station registry in the Washington market holding ``fips`` (synthetic)."""
    platform = {
        "id": "demo",
        "name": "Demo platform (synthetic)",
        "operator": "Nobody",
        "adapter": "gray",
        "poll_minutes": 10,
        "terms": {"automated_access": "unread", "summary": "not read", "evidence": []},
        "notes": "synthetic test platform",
    }
    station = {
        "id": "demo-wxyz",
        "platform": "demo",
        "call_sign": "WXYZ",
        "name": "Synthetic",
        "market": "Washington, DC",
        "dma": WASHINGTON,
        "states": ["DC", "MD", "VA"],
        "counties": {"basis": "dma", "source": "synthetic", "fips": fips},
        "page_url": "https://example.test/closings",
        "data_url": None,
        "archive_urls": [],
        "poll_minutes": None,
        "status": "active",
        "evidence": "synthetic",
    }
    text = yaml.safe_dump({"platform": platform, "stations": [station]}, sort_keys=False)
    (folder / "demo.yaml").write_text(text, encoding="utf-8")
    return load_registry(folder)


def test_county_lists_with_the_placed_counties_match(tmp_path: Path) -> None:
    market = ("24031", "51013", "51059")
    first = dma.DmaCounties(by_dma={WASHINGTON: market}, unmatched=())
    filled = dma.fill_missing(first, dma.read_supplement(SLICE), COUNTIES)
    assert filled.supplemented == (("11001", WASHINGTON),)
    registry = _synthetic_registry(tmp_path, ["11001", *market])
    # The first list alone: the station's list differs from its market by the District.
    assert county_mismatches(registry, first) == ["demo-wxyz: 4 listed, 3 in market"]
    # With the county the second list placed allowed, it matches.
    assert county_mismatches(registry, first, filled) == []


def test_placed_counties_do_not_excuse_missing_or_foreign_ones(tmp_path: Path) -> None:
    first = dma.DmaCounties(
        by_dma={DENVER: ("08001", "08031"), WASHINGTON: ("24031", "51013", "51059")},
        unmatched=(),
    )
    filled = dma.fill_missing(first, dma.read_supplement(SLICE), COUNTIES)
    assert filled.supplemented == (("08014", DENVER), ("11001", WASHINGTON))
    # A market county left out is still a difference, with the District placed or not.
    short = _synthetic_registry(tmp_path, ["11001", "24031", "51013"])
    assert county_mismatches(short, first, filled) == ["demo-wxyz: 3 listed, 3 in market"]
    # So is a county the second list placed in another market (Broomfield: Denver).
    foreign = _synthetic_registry(tmp_path, ["08014", "11001", "24031", "51013", "51059"])
    assert county_mismatches(foreign, first, filled) == ["demo-wxyz: 5 listed, 3 in market"]
