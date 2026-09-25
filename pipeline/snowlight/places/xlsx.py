"""A small, strict reader for the first worksheet of an Office Open XML workbook.

NCES publishes its School District Geographic Relationship Files as ``.xlsx`` (and
SAS) only. The pipeline needs nothing more than the cell text of one plain table,
so rather than depend on a spreadsheet library this module streams the sheet XML
with the standard library and returns every cell as the exact text stored in the
file: shared strings, inline strings and the literal ``<v>`` text of numbers, with
no float round-trip and no number formatting applied.

Anything this reader does not understand (formula error cells, rich cells it
cannot place, a workbook without sheets) raises :class:`XlsxError` instead of
being guessed at.

Python's ``xml.etree`` never resolves external entities, and the expat it links
(>= 2.4.1 for every supported CPython 3.12 build) refuses entity-expansion bombs,
so parsing a downloaded workbook is safe without ``defusedxml``.
"""

import posixpath
import re
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import IO
from xml.etree import ElementTree as ET

_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_CELL_REF = re.compile(r"([A-Z]+)(\d+)")


class XlsxError(ValueError):
    """Raised when a workbook is not the simple table this reader expects."""


def _column_index(letters: str) -> int:
    index = 0
    for char in letters:
        index = index * 26 + (ord(char) - ord("A") + 1)
    return index - 1


def _iterparse(handle: IO[bytes]) -> Iterator[tuple[str, ET.Element]]:
    return ET.iterparse(handle, events=("end",))  # noqa: S314 - see the module docstring


def _text_of(element: ET.Element) -> str:
    """Concatenate the ``<t>`` runs of a shared or inline string item."""
    plain = element.find(f"{_MAIN}t")
    if plain is not None:
        return plain.text or ""
    return "".join(t.text or "" for t in element.iter(f"{_MAIN}t"))


def _first_sheet_path(archive: zipfile.ZipFile) -> str:
    with archive.open("xl/workbook.xml") as handle:
        workbook = ET.parse(handle).getroot()  # noqa: S314 - see the module docstring
    sheet = workbook.find(f"{_MAIN}sheets/{_MAIN}sheet")
    if sheet is None:
        raise XlsxError("workbook has no sheets")
    rel_id = sheet.get(f"{_REL}id")
    with archive.open("xl/_rels/workbook.xml.rels") as handle:
        rels = ET.parse(handle).getroot()  # noqa: S314 - see the module docstring
    for rel in rels.iter(f"{_PKG_REL}Relationship"):
        if rel.get("Id") == rel_id:
            target = rel.get("Target", "")
            if target.startswith("/"):
                return target.lstrip("/")
            return posixpath.normpath(posixpath.join("xl", target))
    raise XlsxError(f"sheet relationship {rel_id!r} not found")


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    strings: list[str] = []
    with archive.open("xl/sharedStrings.xml") as handle:
        for _event, element in _iterparse(handle):
            if element.tag == f"{_MAIN}si":
                strings.append(_text_of(element))
                element.clear()
    return strings


def _cell_text(cell: ET.Element, strings: list[str]) -> str:
    kind = cell.get("t", "n")
    if kind == "inlineStr":
        inline = cell.find(f"{_MAIN}is")
        return "" if inline is None else _text_of(inline)
    value = cell.find(f"{_MAIN}v")
    raw = "" if value is None or value.text is None else value.text
    if kind == "s":
        try:
            return strings[int(raw)]
        except (ValueError, IndexError) as exc:
            raise XlsxError(f"cell {cell.get('r')}: bad shared string index {raw!r}") from exc
    if kind in {"n", "str", "b"}:
        return raw
    raise XlsxError(f"cell {cell.get('r')}: unsupported cell type {kind!r}")


def iter_first_sheet_rows(source: Path | IO[bytes]) -> Iterator[list[str]]:
    """Yield each row of the workbook ``source``'s first worksheet as cell texts.

    Missing cells inside a row come back as empty strings, so every row is as
    long as its right-most populated cell. Empty rows are yielded as ``[]``
    only when the sheet XML lists them.
    """
    with zipfile.ZipFile(source) as archive:
        strings = _shared_strings(archive)
        sheet_path = _first_sheet_path(archive)
        with archive.open(sheet_path) as handle:
            for _event, element in _iterparse(handle):
                if element.tag != f"{_MAIN}row":
                    continue
                cells: dict[int, str] = {}
                for position, cell in enumerate(element.iter(f"{_MAIN}c")):
                    ref = cell.get("r")
                    if ref is None:
                        column = position
                    else:
                        match = _CELL_REF.fullmatch(ref)
                        if match is None:
                            raise XlsxError(f"bad cell reference {ref!r}")
                        column = _column_index(match.group(1))
                    cells[column] = _cell_text(cell, strings)
                element.clear()
                width = max(cells, default=-1) + 1
                yield [cells.get(i, "") for i in range(width)]


def read_table(source: Path | IO[bytes], label: str) -> tuple[list[str], list[list[str]]]:
    """Return ``(header, rows)`` of the first worksheet, padding short rows.

    ``label`` names the workbook in error messages.

    Raises:
        XlsxError: if the sheet is empty, or a row is wider than the header.
    """
    rows = iter_first_sheet_rows(source)
    header = next(rows, None)
    if not header:
        raise XlsxError(f"{label}: first worksheet is empty")
    body: list[list[str]] = []
    for number, row in enumerate(rows, start=2):
        if len(row) > len(header):
            raise XlsxError(f"{label}: row {number} is wider than the header")
        body.append(row + [""] * (len(header) - len(row)))
    return header, body
