"""Tests for the minimal xlsx reader.

The first tests read the sliced real EDGE workbook fixtures. The rest build tiny
synthetic workbooks in the test to reach cell kinds NCES files do not use.
"""

import io
import zipfile
from pathlib import Path

import pytest

from snowlight.sources.nces import xlsx
from snowlight.sources.nces.readers import read_member

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def synthetic_workbook(
    sheet_xml: str, strings: list[str] | None = None, *, target: str = "", sst: str = ""
) -> bytes:
    """Build a synthetic one-sheet workbook around ``sheet_xml`` (sheetData contents)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as book:
        book.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{MAIN}" xmlns:r="{REL}"><sheets>'
            '<sheet name="S" sheetId="1" r:id="rId7"/></sheets></workbook>',
        )
        book.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId7" Type="t" Target="{target or "worksheets/data.xml"}"/>'
            "</Relationships>",
        )
        book.writestr(
            "xl/worksheets/data.xml",
            f'<worksheet xmlns="{MAIN}"><sheetData>{sheet_xml}</sheetData></worksheet>',
        )
        if strings is not None:
            items = "".join(f"<si><t>{s}</t></si>" for s in strings)
            sst = sst or f'<sst xmlns="{MAIN}">{items}</sst>'
            book.writestr("xl/sharedStrings.xml", sst)
    return buffer.getvalue()


@pytest.mark.parametrize(("letters", "index"), [("A", 0), ("Z", 25), ("AA", 26), ("AH", 33)])
def test_column_index(letters: str, index: int) -> None:
    assert xlsx.column_index(letters) == index


def test_reads_real_private_geocode_rows(fixtures_dir: Path) -> None:
    workbook = read_member(
        fixtures_dir / "EDGE_GEOCODE_PRIVATESCH_2324.zip", "EDGE_GEOCODE_PRIVATESCH_2324.xlsx"
    )
    rows = list(xlsx.iter_rows(workbook))
    assert rows[0][:3] == ["PPIN", "NAME", "STREET"]
    assert len(rows) == 9
    first = dict(zip(rows[0], rows[1], strict=True))
    # Row 57 of the published workbook, copied as stored: LAT/LON are numbers.
    assert first["PPIN"] == "00000033"
    assert first["NAME"] == "ST JAMES CATHOLIC SCHOOL"
    assert first["LAT"] == "34.023810000000005"
    assert first["LON"] == "-85.989151000000007"
    assert first["CNTY"] == "01055"


def test_reads_real_public_header(fixtures_dir: Path) -> None:
    workbook = read_member(
        fixtures_dir / "EDGE_GEOCODE_PUBLICSCH_2425.zip", "EDGE_GEOCODE_PUBLICSCH_2425.xlsx"
    )
    header = xlsx.read_header(workbook)
    assert header[:4] == ["NCESSCH", "LEAID", "NAME", "OPSTFIPS"]
    assert header[-1] == "SCHOOLYEAR"
    assert len(header) == 23


def test_missing_cells_become_none_and_blank_rows_are_skipped() -> None:
    sheet = (
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1" t="inlineStr"><is><t>c</t></is></c></row>'
        '<row r="2"><c r="A2"/></row>'
        '<row r="3"><c r="B3"><v>1.5</v></c><c r="C3" t="b"><v>1</v></c></row>'
    )
    rows = list(xlsx.iter_rows(synthetic_workbook(sheet, ["a"])))
    assert rows == [["a", None, "c"], [None, "1.5", "1"]]


def test_cells_without_references_are_sequential() -> None:
    sheet = '<row><c t="inlineStr"><is><t>x</t></is></c><c><v>2</v></c></row>'
    assert list(xlsx.iter_rows(synthetic_workbook(sheet))) == [["x", "2"]]


def test_rich_text_shared_strings_are_joined() -> None:
    sst = (
        f'<sst xmlns="{MAIN}"><si><r><t>Ab</t></r><r><t>c</t></r>'
        "<rPh><t>ignored</t></rPh></si></sst>"
    )
    workbook = synthetic_workbook('<row r="1"><c r="A1" t="s"><v>0</v></c></row>', [], sst=sst)
    assert list(xlsx.iter_rows(workbook)) == [["Abc"]]


def test_absolute_sheet_target_is_followed() -> None:
    workbook = synthetic_workbook(
        '<row r="1"><c r="A1"><v>7</v></c></row>', target="/xl/worksheets/data.xml"
    )
    assert list(xlsx.iter_rows(workbook)) == [["7"]]


@pytest.mark.parametrize(
    ("sheet", "message"),
    [
        ('<row r="1"><c r="A1" t="e"><v>#N/A</v></c></row>', "Excel error"),
        ('<row r="1"><c r="B1"><v>1</v></c><c r="A1"><v>2</v></c></row>', "out of order"),
        ('<row r="1"><c r="1A"><v>1</v></c></row>', "bad cell reference"),
    ],
)
def test_malformed_cells_raise(sheet: str, message: str) -> None:
    with pytest.raises(xlsx.XlsxFormatError, match=message):
        list(xlsx.iter_rows(synthetic_workbook(sheet)))


def test_header_must_be_complete() -> None:
    blank = synthetic_workbook(
        '<row r="1"><c r="A1" t="inlineStr"><is><t>A</t></is></c><c r="C1"><v>1</v></c></row>'
    )
    with pytest.raises(xlsx.XlsxFormatError, match="blank cell"):
        xlsx.read_header(blank)
    with pytest.raises(xlsx.XlsxFormatError, match="empty"):
        xlsx.read_header(synthetic_workbook(""))


def test_sheet_relationship_must_exist() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as book:
        book.writestr("xl/workbook.xml", f'<workbook xmlns="{MAIN}"><sheets/></workbook>')
    with pytest.raises(xlsx.XlsxFormatError, match="no sheets"):
        list(xlsx.iter_rows(buffer.getvalue()))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as book:
        book.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{MAIN}" xmlns:r="{REL}"><sheets>'
            '<sheet name="S" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        book.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>',
        )
    with pytest.raises(xlsx.XlsxFormatError, match="no relationship"):
        list(xlsx.iter_rows(buffer.getvalue()))
