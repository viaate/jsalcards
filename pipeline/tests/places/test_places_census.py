"""Tests for the Census source readers, run on real slices of the published files."""

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from snowlight.sources.census import CensusFormatError, gazetteer, popest
from snowlight.sources.census.listing import child_names, page_links
from snowlight.sources.census.lsad import (
    base_name,
    name_suffixes,
    parse_lsad_codes,
)
from snowlight.sources.census.table import read_single_member, split_table
from snowlight.sources.census.zcta_county import read_zcta_state_land, zcta_state_land

if TYPE_CHECKING:
    from conftest import FixtureKit


# --- directory listings -------------------------------------------------------


def test_gazetteer_release_years_newest_first(kit: "FixtureKit") -> None:
    years = gazetteer.release_years(kit.text_of("gazetteer-index.table.html"))
    assert years[:3] == [2026, 2025, 2024]
    assert years[-1] == 2012
    assert years == sorted(years, reverse=True)


def test_gazetteer_2026_release_has_place_and_zcta_files(kit: "FixtureKit") -> None:
    listing = kit.text_of("gazetteer-2026.table.html")
    assert gazetteer.release_has(listing, 2026, ("place", "zcta"))
    assert not gazetteer.release_has(listing, 2026, ("place", "no_such_layer"))
    assert not gazetteer.release_has(listing, 2025, ("place",))


def test_gazetteer_urls() -> None:
    assert gazetteer.national_file_url(2026, "zcta") == (
        "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
        "2026_Gazetteer/2026_Gaz_zcta_national.zip"
    )


def test_child_names_keeps_only_direct_children() -> None:
    # Synthetic page: one direct child, a sort link, a parent link, a grandchild
    # and an external link.
    html = (
        '<a href="a.zip">a</a><a href="?C=M;O=A">sort</a><a href="/x/">up</a>'
        '<a href="d/e.txt">deep</a><a href="https://elsewhere.example/b.zip">b</a>'
        '<a href="a.zip#top">again</a><a>no href</a><b href="c.zip">not a link</b>'
    )
    assert child_names(html, "https://h.example/x/y/") == ["a.zip"]
    assert page_links('<a href="z">z</a>', "https://h.example/x/") == ["https://h.example/x/z"]
    with pytest.raises(ValueError, match="must end with '/'"):
        child_names(html, "https://h.example/x/y")


def test_popest_series_and_totals_listing(kit: "FixtureKit") -> None:
    series = popest.estimate_series(kit.text_of("popest-datasets.table.html"))
    assert series[0] == (2020, 2025)
    assert (2010, 2020) in series
    listing = kit.text_of("popest-2020-2025-cities-totals.table.html")
    assert popest.totals_listed(listing, 2020, 2025)
    assert not popest.totals_listed(listing, 2020, 2024)


# --- delimited tables -----------------------------------------------------------


def test_split_table_accepts_tabs_and_padded_headers() -> None:
    # Synthetic layout check: older Gazetteer releases were tab-delimited with
    # space-padded header cells.
    header, rows = split_table("GEOID\tINTPTLONG     \n01001\t-72.6\n\n", "t")
    assert header == ["GEOID", "INTPTLONG"]
    assert rows == [{"GEOID": "01001", "INTPTLONG": "-72.6"}]


@pytest.mark.parametrize(
    ("text", "message"),
    [("", "empty table"), ("A|A\n1|2\n", "repeated column"), ("A|B\n1\n", "has 1 cells")],
)
def test_split_table_refuses_malformed_tables(text: str, message: str) -> None:
    with pytest.raises(CensusFormatError, match=message):
        split_table(text, "t")


def test_read_single_member_requires_exactly_one(kit: "FixtureKit", tmp_path: Path) -> None:
    two = tmp_path / "two.zip"
    two.write_bytes(kit.zip_of({"a.txt": b"x", "b.txt": b"y"}))
    with pytest.raises(CensusFormatError, match=r"expected one \.txt file"):
        read_single_member(two)


def test_decode_refuses_non_utf8(kit: "FixtureKit", tmp_path: Path) -> None:
    archive = tmp_path / "places.zip"
    archive.write_bytes(kit.zip_of({"p.txt": kit.bytes_of("sub-est2025.csv")}))
    with pytest.raises(CensusFormatError, match="not UTF-8"):
        gazetteer.read_places(archive)


# --- Gazetteer ---------------------------------------------------------------------


def test_read_places_keeps_published_values(kit: "FixtureKit", tmp_path: Path) -> None:
    archive = tmp_path / "2026_Gaz_place_national.zip"
    archive.write_bytes(
        kit.zip_of({"2026_Gaz_place_national.txt": kit.bytes_of("2026_Gaz_place_national.txt")})
    )
    member, places = gazetteer.read_places(archive)
    assert member == "2026_Gaz_place_national.txt"
    assert len(places) == 28
    by_geoid = {p.geoid: p for p in places}
    assert by_geoid["0100124"] == gazetteer.GazetteerPlace(
        usps="AL",
        geoid="0100124",
        name="Abbeville city",
        lsad="25",
        funcstat="A",
        aland=40255357,
        awater=107642,
        lat=31.565164,
        lon=-85.259165,
    )
    # Published with a combining dot above (U+0307), and kept exactly so.
    assert by_geoid["0281920"].name == "Utqiag\u0307vik city"
    assert by_geoid["0811810"].name == "Cañon City city"


def test_parse_zctas(kit: "FixtureKit") -> None:
    zctas = gazetteer.parse_zctas(kit.text_of("2026_Gaz_zcta_national.txt"), "z")
    assert [z.geoid for z in zctas][:3] == ["00601", "01002", "02139"]
    cambridge = next(z for z in zctas if z.geoid == "02139")
    assert (cambridge.lat, cambridge.lon) == (42.362391, -71.102336)


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("AL|010012|G|0|Abanda CDP|57|S|1|1|0|0|33.1|-85.5", "bad place GEOID"),
        ("AL|0100100|G|0||57|S|1|1|0|0|33.1|-85.5", "has no NAME"),
        ("AL|0100100|G|0|Abanda CDP|57|S|1.5|1|0|0|33.1|-85.5", "not a whole number"),
        ("AL|0100100|G|0|Abanda CDP|57|S|1|1|0|0|north|-85.5", "not a number"),
        ("AL|0100100|G|0|Abanda CDP|57|S|1|1|0|0|93.1|-85.5", "out of range"),
    ],
)
def test_parse_places_refuses_malformed_rows(kit: "FixtureKit", line: str, message: str) -> None:
    # Synthetic corruptions of the real header's layout.
    header = kit.text_of("2026_Gaz_place_national.txt").splitlines()[0]
    with pytest.raises(CensusFormatError, match=message):
        gazetteer.parse_places(f"{header}\n{line}\n", "p")


def test_parse_rejects_repeated_geoids_and_bad_zctas(kit: "FixtureKit") -> None:
    lines = kit.text_of("2026_Gaz_zcta_national.txt").splitlines()
    with pytest.raises(CensusFormatError, match="repeated GEOID"):
        gazetteer.parse_zctas("\n".join([lines[0], lines[1], lines[1]]), "z")
    with pytest.raises(CensusFormatError, match="bad ZCTA GEOID"):
        gazetteer.parse_zctas("\n".join([lines[0], "0060|" + lines[1].split("|", 1)[1]]), "z")
    with pytest.raises(CensusFormatError, match="missing columns"):
        gazetteer.parse_zctas("GEOID|ALAND\n00601|1\n", "z")


# --- Population estimates -----------------------------------------------------------


def test_place_estimates_from_real_slice(kit: "FixtureKit", tmp_path: Path) -> None:
    path = tmp_path / "sub-est2025.csv"
    path.write_bytes(kit.bytes_of("sub-est2025.csv"))
    estimates = popest.read_place_estimates(path, 2025)
    assert estimates.encoding == "iso-8859-1"
    assert estimates.column == "POPESTIMATE2025"
    assert estimates.by_geoid["0100124"] == popest.PlaceEstimate(
        geoid="0100124", name="Abbeville city", funcstat="A", population=2378
    )
    assert estimates.by_geoid["0811810"].name == "Cañon City city"
    assert estimates.by_geoid["0812030"].population == 0
    # Only SUMLEV 162 rows are kept: not the state, county-part or consolidated-city rows.
    assert "0100000" not in estimates.by_geoid
    assert "0900000" not in estimates.by_geoid
    assert all(len(geoid) == 7 for geoid in estimates.by_geoid)


def test_place_estimates_accepts_utf8(kit: "FixtureKit") -> None:
    data = kit.bytes_of("sub-est2025.csv").decode("iso-8859-1").encode("utf-8")
    estimates = popest.parse_place_estimates(b"\xef\xbb\xbf" + data, 2025, "utf8")
    assert estimates.encoding == "utf-8"
    assert estimates.by_geoid["0811810"].name == "Cañon City city"


def test_place_estimates_refuses_wrong_vintage_and_bad_rows(kit: "FixtureKit") -> None:
    data = kit.bytes_of("sub-est2025.csv")
    with pytest.raises(CensusFormatError, match="newest estimate column is not 2024"):
        popest.parse_place_estimates(data, 2024, "p")
    header, *rows = data.split(b"\n")
    abbeville = next(r for r in rows if b"Abbeville" in r and r.startswith(b"162"))
    with pytest.raises(CensusFormatError, match="repeats"):
        popest.parse_place_estimates(b"\n".join([header, abbeville, abbeville]), 2025, "p")
    with pytest.raises(CensusFormatError, match="bad place row"):
        popest.parse_place_estimates(
            b"\n".join([header, abbeville.replace(b",2378", b",n/a")]), 2025, "p"
        )
    with pytest.raises(CensusFormatError, match="ragged row"):
        popest.parse_place_estimates(b"\n".join([header, abbeville + b",9"]), 2025, "p")
    with pytest.raises(CensusFormatError, match="no SUMLEV 162 rows"):
        popest.parse_place_estimates(header, 2025, "p")
    with pytest.raises(CensusFormatError, match="missing columns"):
        popest.parse_place_estimates(b"SUMLEV,STATE\n162,01\n", 2025, "p")


# --- LSAD codes --------------------------------------------------------------------


def test_lsad_suffixes_from_real_table(kit: "FixtureKit") -> None:
    codes = parse_lsad_codes(kit.text_of("legal-status-codes.table.html"))
    first = codes[0]
    assert (first.code, first.description) == ("00", "")
    assert "Incorporated Place" in first.entities
    suffixes = name_suffixes(codes)
    assert suffixes["00"] == ""
    assert suffixes["21"] == "borough"
    assert suffixes["25"] == "city"
    assert suffixes["53"] == "city and borough"
    assert suffixes["57"] == "CDP"
    assert suffixes["CG"] == "consolidated government"
    assert suffixes["UG"] == "unified government"
    assert "06" not in suffixes  # listed twice with different descriptions
    assert "28" not in suffixes  # a prefix
    assert "BL" not in suffixes  # "(balance)" is not marked as a suffix


def test_lsad_page_without_table_is_refused() -> None:
    with pytest.raises(CensusFormatError, match="expected header"):
        parse_lsad_codes("<html><table><tr><td>x</td></tr></table></html>")
    header = "<tr><th>LSAD</th><th>LSAD Description</th><th>Associated Geographic Entity</th></tr>"
    with pytest.raises(CensusFormatError, match="empty"):
        parse_lsad_codes(f"<table>{header}<tr><td>only one cell</td></tr></table>")


@pytest.mark.parametrize(
    ("full", "suffix", "expected"),
    [
        ("Abbeville city", "city", "Abbeville"),
        ("Jersey City city", "city", "Jersey City"),
        ("Carson City", "city", None),
        ("city", "city", None),
        ("Princeton", "", "Princeton"),
    ],
)
def test_base_name(full: str, suffix: str, expected: str | None) -> None:
    assert base_name(full, suffix) == expected


# --- ZCTA to county ---------------------------------------------------------------


def test_zcta_state_land_from_real_slice(kit: "FixtureKit", tmp_path: Path) -> None:
    path = tmp_path / "rel.txt"
    path.write_bytes(kit.bytes_of("tab20_zcta520_county20_natl.txt"))
    land = read_zcta_state_land(path)
    assert land["02861"] == {"44": 9207555, "25": 42976}
    assert land["02139"] == {"25": 4019199}
    assert "" not in land
    assert len(land) == 11


def test_zcta_state_land_refuses_bad_rows(kit: "FixtureKit") -> None:
    header = kit.text_of("tab20_zcta520_county20_natl.txt").splitlines()[0]
    cells = ["x"] * len(header.split("|"))
    names = header.lstrip("﻿").split("|")
    cells[names.index("GEOID_ZCTA5_20")] = "02139"
    cells[names.index("GEOID_COUNTY_20")] = "25017"
    cells[names.index("AREALAND_PART")] = "-1"
    with pytest.raises(CensusFormatError, match="bad row"):
        zcta_state_land(header.lstrip("﻿") + "\n" + "|".join(cells) + "\n", "rel")
