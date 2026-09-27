"""The market readers: the DMA crosswalk, the county Gazetteer and the Connecticut crosswalk.

The real slices are in ``fixtures/`` (``usa-tvdma-county.csv``: 13 markets;
``2025_Gaz_counties_national.zip``: 21 states; ``ct_cou_to_cousub_crosswalk.xlsx``:
the whole file; see ``fixtures/provenance.json``). Files built in ``tmp_path`` for
the error paths are synthetic and named so.
"""

import hashlib
import zipfile
from pathlib import Path

import pytest

from snowlight.weights import markets

FIXTURES = Path(__file__).parent / "fixtures"
GAZETTEER = FIXTURES / "2025_Gaz_counties_national.zip"
CT = FIXTURES / "ct_cou_to_cousub_crosswalk.xlsx"
CROSSWALK = FIXTURES / "usa-tvdma-county.csv"
HEADER = "STATE,STATE_AB,COUNTY,Internal_State_Region,TVDMA\n"


def _gazetteer() -> list[markets.GazetteerCounty]:
    return markets.read_gazetteer(GAZETTEER)


def _crosswalk() -> markets.DmaCounties:
    return markets.read_crosswalk(CROSSWALK, _gazetteer(), markets.read_ct_regions(CT))


def test_normalize_county() -> None:
    assert markets.normalize_county("St. Mary's") == "STMARYS"
    assert markets.normalize_county("SAINT MARYS") == "STMARYS"
    assert markets.normalize_county("Ste. Genevieve") == "STEGENEVIEVE"
    assert markets.normalize_county("DeKalb") == markets.normalize_county("De Kalb")
    assert markets.normalize_county("Doña Ana") == "DONAANA"
    assert markets.normalize_county("Fairfax city") == "FAIRFAXCITY"


def test_read_gazetteer() -> None:
    counties = _gazetteer()
    assert len(counties) == 1163
    assert {county.state for county in counties} >= {"RI", "CT", "MD", "NV", "MS"}
    providence = next(county for county in counties if county.fips == "44007")
    assert providence == markets.GazetteerCounty("RI", "44007", "Providence County")


def test_county_index() -> None:
    index = markets.county_index(_gazetteer())
    assert index[("RI", "PROVIDENCE")] == "44007"
    assert index[("RI", "PROVIDENCECOUNTY")] == "44007"
    # Baltimore city is an independent city; the plain name stays Baltimore County's.
    assert index[("MD", "BALTIMORECITY")] == "24510"
    assert index[("MD", "BALTIMORE")] == "24005"
    assert index[("MD", markets.normalize_county("Saint Mary's"))] == "24037"
    # Carson City, Nevada is indexed like a county, not as an independent city.
    assert index[("NV", "CARSONCITY")] == "32510"
    assert ("NV", "CARSON") not in index
    assert index[("CT", "CAPITOL")] == "09110"


def test_read_ct_regions() -> None:
    regions = markets.read_ct_regions(CT)
    assert regions.old_by_name["HARTFORD"] == "09003"
    assert regions.old_by_name["NEWLONDON"] == "09011"
    assert len(regions.old_by_name) == 8
    assert regions.regions["09003"] == frozenset({"09110", "09140", "09160"})
    assert regions.regions["09007"] == frozenset({"09130"})


def test_read_crosswalk() -> None:
    crosswalk = _crosswalk()
    assert len(crosswalk.by_dma) == 13
    assert crosswalk.unmatched == ()
    assert crosswalk.by_dma["Providence, RI - New Bedford, MA DMA"] == (
        "25005",
        "44001",
        "44003",
        "44005",
        "44007",
        "44009",
    )
    assert crosswalk.by_dma["Bakersfield, CA DMA"] == ("06029",)
    # Old Connecticut counties become every planning region holding one of their towns,
    # so a region straddling two markets belongs to both.
    assert crosswalk.by_dma["Hartford & New Haven, CT DMA"] == (
        "09110",
        "09130",
        "09140",
        "09150",
        "09160",
        "09170",
        "09180",
        "09190",
    )
    assert crosswalk.dma_of("09140") == (
        "Hartford & New Haven, CT DMA",
        "New York, NY - CT - NJ - PA DMA",
    )
    assert crosswalk.dma_of("44007") == ("Providence, RI - New Bedford, MA DMA",)
    assert crosswalk.dma_of("99999") == ()


def test_crosswalk_pin_matches_the_fixture_source() -> None:
    """The fixture slice records the full file's SHA-256: the pinned one."""
    provenance = (FIXTURES / "provenance.json").read_text(encoding="utf-8")
    assert markets.DMA_CROSSWALK_SHA256 in provenance
    sliced = hashlib.sha256(CROSSWALK.read_bytes()).hexdigest()
    assert sliced != markets.DMA_CROSSWALK_SHA256  # a slice, not the pinned file itself


def test_crosswalk_rows_renamed_unmatched_and_out_of_scope(tmp_path: Path) -> None:
    """A synthetic crosswalk exercising every row rule on real Gazetteer names."""
    path = tmp_path / "synthetic-crosswalk.csv"
    path.write_text(
        HEADER
        + 'RHODE ISLAND,RI,PROVIDENCE,x,"Providence, RI - New Bedford, MA DMA"\n'
        + HEADER  # the real file repeats its header between states
        + "\n"
        + 'ALASKA,AK,JUNEAU,x,"Juneau, AK DMA"\n'
        + 'RHODE ISLAND,RI,NOWHERE,x,"Providence, RI - New Bedford, MA DMA"\n'
        + "RHODE ISLAND,RI,KENT,x,\n"
        + 'CONNECTICUT,CT,NOWHERE,x,"Hartford & New Haven, CT DMA"\n'
        + 'CONNECTICUT,CT,TOLLAND,x,"Hartford & New Haven, CT DMA"\n'
        + "SHORT,ROW\n",
        encoding="utf-8",
    )
    found = markets.read_crosswalk(path, _gazetteer(), markets.read_ct_regions(CT))
    assert found.by_dma == {
        "Hartford & New Haven, CT DMA": ("09110", "09150"),
        "Providence, RI - New Bedford, MA DMA": ("44007",),
    }
    assert found.unmatched == (
        ("RI", "NOWHERE", "Providence, RI - New Bedford, MA DMA"),
        ("RI", "KENT", ""),
        ("CT", "NOWHERE", "Hartford & New Haven, CT DMA"),
    )


def test_renamed_counties_resolve() -> None:
    """Each renamed county whose state is in the Gazetteer slice is found there."""
    index = markets.county_index(_gazetteer())
    found = {
        (state, old): index.get((state, markets.normalize_county(new)))
        for (state, old), new in markets.RENAMED.items()
        if state in {"SD", "FL", "MN"}
    }
    assert found == {
        ("SD", "SHANNON"): "46102",
        ("FL", "DADE"): "12086",
        ("MN", "LAKE OF WOODS"): "27077",
    }


def test_crosswalk_errors(tmp_path: Path) -> None:
    bad_header = tmp_path / "synthetic-bad-header.csv"
    bad_header.write_text("A,B,C\n", encoding="utf-8")
    with pytest.raises(markets.MarketsError, match="unexpected header"):
        markets.read_crosswalk(bad_header, [], markets.read_ct_regions(CT))
    empty = tmp_path / "synthetic-empty.csv"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(markets.MarketsError, match="unexpected header"):
        markets.read_crosswalk(empty, [], markets.read_ct_regions(CT))
    latin = tmp_path / "synthetic-latin-1.csv"
    latin.write_bytes(HEADER.encode() + "RI,RI,DOÑA,x,y\n".encode("latin-1"))
    with pytest.raises(markets.MarketsError, match="not UTF-8"):
        markets.read_crosswalk(latin, [], markets.read_ct_regions(CT))


def _zip(path: Path, members: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in members.items():
            archive.writestr(name, text)
    return path


def test_gazetteer_errors(tmp_path: Path) -> None:
    two = _zip(tmp_path / "synthetic-two.zip", {"a.txt": "x", "b.txt": "y"})
    with pytest.raises(markets.MarketsError, match="expected one text member"):
        markets.read_gazetteer(two)
    columns = _zip(tmp_path / "synthetic-columns.zip", {"g.txt": "USPS|NAME\nRI|Kent\n"})
    with pytest.raises(markets.MarketsError, match="missing the USPS, GEOID or NAME"):
        markets.read_gazetteer(columns)
    geoid = _zip(tmp_path / "synthetic-geoid.zip", {"g.txt": "USPS|GEOID|NAME\nRI|4400|Kent\n"})
    with pytest.raises(markets.MarketsError, match="bad GEOID '4400'"):
        markets.read_gazetteer(geoid)
    padded = _zip(
        tmp_path / "synthetic-padded.zip",
        {"g.txt": "﻿USPS|GEOID|NAME   \nRI|44003|Kent County   \n"},
    )
    assert markets.read_gazetteer(padded) == [markets.GazetteerCounty("RI", "44003", "Kent County")]


def test_unreadable_files(tmp_path: Path) -> None:
    not_zip = tmp_path / "synthetic-not-a-zip.zip"
    not_zip.write_bytes(b"plain text")
    with pytest.raises(markets.MarketsError, match="not-a-zip"):
        markets.read_gazetteer(not_zip)
    with pytest.raises(markets.MarketsError, match="not-a-zip"):
        markets.read_ct_regions(not_zip)
    binary = _zip(tmp_path / "synthetic-binary.zip", {})
    with zipfile.ZipFile(binary, "w") as archive:
        archive.writestr("g.txt", b"\xff\xfe\x00")
    with pytest.raises(markets.MarketsError, match="synthetic-binary"):
        markets.read_gazetteer(binary)


def test_ct_region_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Synthetic tables in place of the workbook's first sheet."""
    tables = iter(
        [
            (["STATEFP", "OLD_COUNTYFP"], [["09", "003"]]),
            (
                ["STATEFP\nState", "OLD_COUNTYFP", "OLD_COUNTY_NAMELSAD", "NEW_COUNTYFP"],
                [["44", "007", "Providence County", "007"], ["09", "", "Hartford County", ""]],
            ),
        ]
    )

    def fake_table(path: Path, label: str) -> tuple[list[str], list[list[str]]]:
        assert label == path.name
        return next(tables)

    monkeypatch.setattr(markets, "read_table", fake_table)
    with pytest.raises(markets.MarketsError, match="missing column OLD_COUNTY_NAMELSAD"):
        markets.read_ct_regions(tmp_path / "synthetic.xlsx")
    with pytest.raises(markets.MarketsError, match="no Connecticut rows"):
        markets.read_ct_regions(tmp_path / "synthetic.xlsx")
