"""Tests for the workbook reader and the NCES GRF reader."""

import io
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from snowlight.places.grf import (
    GrfFormatError,
    GrfRelease,
    LeaZctaPart,
    grf_release,
    grf_releases,
    parse_lea_zcta,
    read_lea_zcta,
)
from snowlight.places.xlsx import XlsxError, iter_first_sheet_rows, read_table

if TYPE_CHECKING:
    from conftest import FixtureKit

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


def workbook(
    kit: "FixtureKit",
    sheet_data: str,
    *,
    shared: str | None = None,
    sheets: str = f'<sheet name="S" sheetId="1" r:id="rId1" xmlns:r="{REL}"/>',
    target: str = "worksheets/sheet1.xml",
) -> io.BytesIO:
    """Build a synthetic workbook around ``sheet_data`` to exercise one reader rule."""
    members = {
        "xl/workbook.xml": (
            f'<workbook xmlns="{MAIN}"><sheets>{sheets}</sheets></workbook>'
        ).encode(),
        "xl/_rels/workbook.xml.rels": (
            f'<Relationships xmlns="{PKG}">'
            f'<Relationship Id="rId1" Target="{target}" Type="worksheet"/></Relationships>'
        ).encode(),
        "xl/worksheets/sheet1.xml": (
            f'<worksheet xmlns="{MAIN}"><sheetData>{sheet_data}</sheetData></worksheet>'
        ).encode(),
    }
    if shared is not None:
        members["xl/sharedStrings.xml"] = f'<sst xmlns="{MAIN}">{shared}</sst>'.encode()
    return io.BytesIO(kit.zip_of(members))


# --- workbook reader --------------------------------------------------------------


def test_real_grf_rows_round_trip_through_shared_strings(kit: "FixtureKit") -> None:
    rows = kit.grf_rows()
    header, body = read_table(io.BytesIO(kit.xlsx_of(rows)), "grf")
    assert [header, *body] == rows


def test_real_grf_rows_round_trip_through_inline_strings(kit: "FixtureKit") -> None:
    rows = kit.grf_rows()
    assert list(iter_first_sheet_rows(io.BytesIO(kit.xlsx_of(rows, inline=True)))) == rows


def test_cell_kinds_gaps_and_rich_text(kit: "FixtureKit") -> None:
    sheet = (
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1" t="s"><v>1</v></c></row>'
        '<row r="2"><c r="A2"><v>38.76843715106015</v></c><c r="B2" t="b"><v>1</v></c>'
        '<c r="C2" t="str"><v>formula text</v></c></row>'
        "<row><c><v>7</v></c><c/></row>"
    )
    shared = "<si><t>LEAID</t></si><si><r><t>NAME_</t></r><r><t>LEA25</t></r></si>"
    header, body = read_table(workbook(kit, sheet, shared=shared), "w")
    assert header == ["LEAID", "", "NAME_LEA25"]
    assert body == [["38.76843715106015", "1", "formula text"], ["7", "", ""]]


def test_workbook_without_shared_strings_and_absolute_target(kit: "FixtureKit") -> None:
    sheet = '<row r="1"><c r="A1" t="inlineStr"><is><t>only</t></is></c></row>'
    rows = list(iter_first_sheet_rows(workbook(kit, sheet, target="/xl/worksheets/sheet1.xml")))
    assert rows == [["only"]]


@pytest.mark.parametrize(
    ("sheet", "shared", "message"),
    [
        ('<row r="1"><c r="A1" t="e"><v>#N/A</v></c></row>', None, "unsupported cell type"),
        ('<row r="1"><c r="A1" t="s"><v>9</v></c></row>', "<si><t>x</t></si>", "shared string"),
        ('<row r="1"><c r="1A"><v>1</v></c></row>', None, "bad cell reference"),
    ],
)
def test_unreadable_cells_are_refused(
    kit: "FixtureKit", sheet: str, shared: str | None, message: str
) -> None:
    with pytest.raises(XlsxError, match=message):
        list(iter_first_sheet_rows(workbook(kit, sheet, shared=shared)))


def test_workbooks_without_a_usable_sheet_are_refused(kit: "FixtureKit") -> None:
    with pytest.raises(XlsxError, match="no sheets"):
        list(iter_first_sheet_rows(workbook(kit, "", sheets="")))
    wrong_rel = f'<sheet name="S" sheetId="1" r:id="rId9" xmlns:r="{REL}"/>'
    with pytest.raises(XlsxError, match="relationship 'rId9' not found"):
        list(iter_first_sheet_rows(workbook(kit, "", sheets=wrong_rel)))
    with pytest.raises(XlsxError, match="first worksheet is empty"):
        read_table(workbook(kit, ""), "w")
    wide = '<row r="1"><c r="A1"><v>1</v></c></row><row r="2"><c r="B2"><v>2</v></c></row>'
    with pytest.raises(XlsxError, match="row 2 is wider"):
        read_table(workbook(kit, wide), "w")


# --- GRF ---------------------------------------------------------------------------


def test_grf_releases_from_real_page(kit: "FixtureKit") -> None:
    releases = grf_releases(kit.text_of("nces-relationship-files.lines-222-414.html"))
    assert releases[0] == GrfRelease(2025, "https://nces.ed.gov/programs/edge/data/GRF25.zip")
    assert [r.tiger_year for r in releases] == list(range(2025, 2012, -1))
    assert grf_release(2025) == releases[0]
    assert grf_releases("<p>no links</p>") == []


def test_read_lea_zcta_from_real_rows(kit: "FixtureKit", tmp_path: Path) -> None:
    path = tmp_path / "GRF25.zip"
    path.write_bytes(kit.grf_zip())
    table = read_lea_zcta(path, 2025)
    assert table.member == "GRF25/grf25_lea_zcta5ce20.xlsx"
    assert table.zcta_vintage == 2020
    assert len(table.parts) == len(kit.grf_rows()) - 1
    assert table.parts[0] == LeaZctaPart(
        leaid="0100001",
        name="Fort Rucker School District",
        zcta="00000",
        land_sqmi=38.76843715106015,
        water_sqmi=1.038161180669563,
    )
    orange_beach = next(p for p in table.parts if p.leaid == "0103581")
    assert (orange_beach.zcta, orange_beach.land_sqmi) == ("36542", 0.0)


def test_read_lea_zcta_checks_the_release(kit: "FixtureKit", tmp_path: Path) -> None:
    path = tmp_path / "GRF25.zip"
    path.write_bytes(kit.grf_zip())
    with pytest.raises(GrfFormatError, match="not the 2024 release"):
        read_lea_zcta(path, 2024)
    empty = tmp_path / "empty.zip"
    empty.write_bytes(kit.zip_of({"GRF25/grf25_lea_county.xlsx": b""}))
    with pytest.raises(GrfFormatError, match="expected one LEA-ZCTA workbook"):
        read_lea_zcta(empty, 2025)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ((0, "01001"), "bad LEAID"),
        ((2, "0213"), "bad LEAID/ZCTA"),
        ((1, " "), "bad LEAID/ZCTA/name"),
        ((4, "-1"), "not a non-negative area"),
        ((5, "wet"), "not a number"),
    ],
)
def test_parse_lea_zcta_refuses_bad_cells(
    kit: "FixtureKit", change: tuple[int, str], message: str
) -> None:
    header, row = kit.grf_rows()[0], list(kit.grf_rows()[1])
    row[change[0]] = change[1]
    with pytest.raises(GrfFormatError, match=message):
        parse_lea_zcta(header, [row], "m")


def test_parse_lea_zcta_refuses_repeats_missing_columns_and_empty(kit: "FixtureKit") -> None:
    header, row = kit.grf_rows()[0], kit.grf_rows()[1]
    with pytest.raises(GrfFormatError, match="repeats"):
        parse_lea_zcta(header, [row, row], "m")
    with pytest.raises(GrfFormatError, match="no rows"):
        parse_lea_zcta(header, [], "m")
    with pytest.raises(GrfFormatError, match="no LANDAREA column"):
        parse_lea_zcta([c if c != "LANDAREA" else "LAND" for c in header], [row], "m")
    with pytest.raises(GrfFormatError, match="no ZCTA5CE<yy> column"):
        parse_lea_zcta([c if c != "ZCTA5CE20" else "ZCTA5CE" for c in header], [row], "m")
