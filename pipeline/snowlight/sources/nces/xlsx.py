"""A small, dependency-free reader for the worksheets of an ``.xlsx`` file (the first by
default).

NCES ships its EDGE geocode tables as Excel workbooks next to pipe-delimited
text. The text files have no header row and the private-school release has no
text file at all, so the workbook is where column names (and, for private
schools, the rows themselves) come from.

Only what those workbooks use is supported: shared strings, inline strings,
plain numbers, booleans and formula string results. Every cell comes back as
the exact text stored in the file (a number keeps the digits Excel wrote, such
as ``"32.469349999999999"``); empty cells come back as ``None``.
"""

import io
import posixpath
import re
import zipfile
from collections.abc import Iterator
from xml.etree import ElementTree as ET

_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_DOC_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_CELL_REF = re.compile(r"^([A-Z]+)(\d+)$")

type Row = list[str | None]


class XlsxFormatError(ValueError):
    """The workbook is not in the shape this reader understands."""


def column_index(letters: str) -> int:
    """Return the zero-based index of a column name such as ``"A"`` or ``"AH"``."""
    index = 0
    for char in letters:
        index = index * 26 + (ord(char) - ord("A") + 1)
    return index - 1


def _text_of(element: ET.Element) -> str:
    """Concatenate the ``<t>`` runs of a string item, skipping phonetic hints."""
    parts: list[str] = []
    for child in element:
        if child.tag == f"{_MAIN}t":
            parts.append(child.text or "")
        elif child.tag == f"{_MAIN}r":
            parts.extend(t.text or "" for t in child.iter(f"{_MAIN}t"))
    return "".join(parts)


def _shared_strings(book: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in book.namelist():
        return []
    root = ET.fromstring(book.read("xl/sharedStrings.xml"))  # noqa: S314 - official NCES file
    return [_text_of(item) for item in root.findall(f"{_MAIN}si")]


def _sheet_paths(book: zipfile.ZipFile) -> list[tuple[str, str]]:
    """Each worksheet's name and part path, in workbook order."""
    workbook = ET.fromstring(book.read("xl/workbook.xml"))  # noqa: S314 - official NCES file
    sheets = workbook.findall(f"{_MAIN}sheets/{_MAIN}sheet")
    if not sheets:
        raise XlsxFormatError("workbook has no sheets")
    rels = ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))  # noqa: S314 - official NCES file
    targets = {
        rel.get("Id"): rel.get("Target", "") for rel in rels.findall(f"{_PKG_REL}Relationship")
    }
    found: list[tuple[str, str]] = []
    for sheet in sheets:
        rel_id = sheet.get(f"{_DOC_REL}id")
        target = targets.get(rel_id)
        if target is None:
            raise XlsxFormatError(f"no relationship for sheet id {rel_id!r}")
        path = (
            target.lstrip("/")
            if target.startswith("/")
            else posixpath.normpath(posixpath.join("xl", target))
        )
        found.append((sheet.get("name", ""), path))
    return found


def sheet_names(workbook: bytes) -> list[str]:
    """The workbook's worksheet names, in order."""
    with zipfile.ZipFile(io.BytesIO(workbook)) as book:
        return [name for name, _path in _sheet_paths(book)]


def _cell_value(cell: ET.Element, strings: list[str]) -> str | None:
    kind = cell.get("t")
    if kind == "inlineStr":
        inline = cell.find(f"{_MAIN}is")
        return None if inline is None else _text_of(inline)
    value = cell.find(f"{_MAIN}v")
    if value is None or value.text is None:
        return None
    if kind == "s":
        return strings[int(value.text)]
    if kind == "e":
        raise XlsxFormatError(f"cell {cell.get('r')} holds an Excel error {value.text!r}")
    return value.text


def iter_rows(workbook: bytes, sheet: int = 0) -> Iterator[Row]:
    """Yield every row of the first worksheet of ``workbook`` (or of worksheet ``sheet``, by
    its position) as a list of cell texts.

    Cells missing from the XML (Excel omits empty ones) are ``None``; each row is
    as long as its right-most non-empty cell. Blank rows are skipped.
    """
    with zipfile.ZipFile(io.BytesIO(workbook)) as book:
        strings = _shared_strings(book)
        paths = _sheet_paths(book)
        if not 0 <= sheet < len(paths):
            raise XlsxFormatError(f"workbook has no sheet {sheet}")
        with book.open(paths[sheet][1]) as part:
            for _event, element in ET.iterparse(part):  # noqa: S314 - official NCES file
                if element.tag != f"{_MAIN}row":
                    continue
                row: Row = []
                for cell in element.findall(f"{_MAIN}c"):
                    ref = cell.get("r")
                    if ref is None:
                        position = len(row)
                    else:
                        match = _CELL_REF.match(ref)
                        if match is None:
                            raise XlsxFormatError(f"bad cell reference {ref!r}")
                        position = column_index(match.group(1))
                    if position < len(row):
                        raise XlsxFormatError(f"cell {ref!r} is out of order")
                    row.extend([None] * (position - len(row)))
                    row.append(_cell_value(cell, strings))
                element.clear()
                if any(value is not None for value in row):
                    yield row


def read_header(workbook: bytes) -> list[str]:
    """Return the first row of the first worksheet as column names.

    Raises:
        XlsxFormatError: if the sheet is empty or a header cell is blank.
    """
    for row in iter_rows(workbook):
        if any(value is None or not value.strip() for value in row):
            raise XlsxFormatError(f"header row has a blank cell: {row!r}")
        return [value.strip() for value in row if value is not None]
    raise XlsxFormatError("worksheet is empty")
