"""Regenerate the test fixtures: small slices of the real NCES files.

Run from ``pipeline/`` after a full ``snowlight directory build`` has filled the
download cache::

    uv run python tests/directory/make_fixtures.py

For every source zip named in ``config/directory.yaml`` this writes a zip of the
same name under ``tests/directory/fixtures/`` holding only the rows of the
schools and districts listed below, and records in ``PROVENANCE.json`` the
source URL, the SHA-256 of the source zip, and the line (or worksheet row)
number of every row kept. Rows are copied byte for byte:

* text members (``.TXT``, ``.csv``): the selected lines, unchanged, after the
  original header line when the file has one;
* workbooks (``.xlsx``): a new minimal workbook whose worksheet holds the
  original header row and the selected ``<row>`` elements with their original
  row numbers and cell values; only shared-string indexes are renumbered to
  point into a shared-string table cut down to the strings those rows use.
"""

import csv
import io
import json
import re
import sys
import zipfile
from collections.abc import Iterable
from pathlib import Path
from xml.etree import ElementTree as ET

from snowlight.directory.config import load_config
from snowlight.sources.nces.fetch import cache_path
from snowlight.sources.nces.readers import open_member_stream

PIPELINE = Path(__file__).resolve().parents[2]
CACHE = PIPELINE / ".cache" / "nces"
OUT = Path(__file__).resolve().parent / "fixtures"
MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

# Each id is here for a reason noted beside it; tests rely on these outcomes.
PUBLIC_IDS = {
    "010000500870": "kept: regular middle school",
    "010000500871": "kept: regular high school, same district",
    "010019702432": "kept: charter school",
    "010000602705": "kept: exclusively virtual school",
    "040386003535": "kept: enrollment Suppressed",
    "010000600986": "kept: enrollment Missing",
    "590002500172": "kept: Bureau of Indian Education school, located in ND",
    "180020202661": "kept: EDGE name contains a quoted pipe",
    "280237000462": "kept: EDGE street contains doubled quotes",
    "120008410898": "kept: status 4 Added",
    "050040801686": "kept: status 5 Changed Boundary/Agency",
    "010020902504": "kept: status 8 Reopened",
    "110003000207": "kept: in DC; enrollment leaves out its adult education students",
    "010000600876": "dropped: prekindergarten only",
    "010000902231": "dropped: grades not reported",
    "010020402727": "dropped: status Future",
    "010210000806": "dropped: status Closed",
    "040000101203": "dropped: status Inactive",
    "050042005157": "dropped: adult education only",
    "250000102401": "dropped: PK and UG, no K-12 grade",
    "100023000378": "dropped: ungraded only",
    "230264000057": "dropped: no grades offered",
    "020000100206": "dropped: Alaska",
    "150003000001": "dropped: Hawaii",
    "720003000004": "dropped: Puerto Rico",
}
EXTRA_LEA_IDS = {
    "5000021": "Vermont district whose schools are not in the fixture",
    "0200001": "Alaska district (outside the continental US)",
    "3400033": "New Jersey district whose schools are not in the fixture",
}
PRIVATE_IDS = {
    "00000033": "kept: PK-8",
    "00000044": "kept: PK-12",
    "00073137": "kept: lowest grade transitional kindergarten",
    "00083393": "kept: enrollment imputed by NCES (F_P305 = 4), so left empty",
    "00089781": "dropped: all ungraded",
    "00538514": "dropped: highest grade prekindergarten",
    "00023629": "dropped: Alaska",
    "00326554": "dropped: Hawaii",
}


def _field(line: bytes, index: int, delimiter: str) -> str:
    row = next(csv.reader([line.decode("utf-8").rstrip("\r\n")], delimiter=delimiter))
    return row[index]


def slice_lines(
    data: bytes, ids: set[str], index: int, delimiter: str, *, header: bool
) -> tuple[bytes, list[int]]:
    """Keep the header (if any) and the lines whose field ``index`` is in ``ids``."""
    lines = data.splitlines(keepends=True)
    kept: list[bytes] = [lines[0]] if header else []
    numbers: list[int] = []
    for number, line in enumerate(lines[1:] if header else lines, start=2 if header else 1):
        if _field(line, index, delimiter) in ids:
            kept.append(line)
            numbers.append(number)
    return b"".join(kept), numbers


def slice_membership(zip_path: Path, member: str, ids: set[str]) -> tuple[bytes, list[int]]:
    """Keep each school's two total rows and its first two detail rows."""
    pattern = re.compile(b"|".join(re.escape(i.encode()) for i in sorted(ids)))
    kept: list[bytes] = []
    numbers: list[int] = []
    detail_seen: dict[str, int] = {}
    with open_member_stream(zip_path, member) as handle:
        header = handle.readline()
        number = 1
        for line in handle:
            number += 1
            if not pattern.search(line):
                continue
            school = _field(line, 10, ",")
            if school not in ids:
                continue
            indicator = _field(line, 16, ",")
            if indicator.startswith("Category Set A"):
                if detail_seen.get(school, 0) >= 2:
                    continue
                detail_seen[school] = detail_seen.get(school, 0) + 1
            elif "Education Unit Total" not in indicator:
                continue
            kept.append(line)
            numbers.append(number)
    return header + b"".join(kept), numbers


def _xlsx_parts(workbook: bytes) -> tuple[list[ET.Element], ET.Element]:
    with zipfile.ZipFile(io.BytesIO(workbook)) as book:
        strings = ET.fromstring(book.read("xl/sharedStrings.xml"))  # noqa: S314
        sheet = ET.fromstring(book.read("xl/worksheets/sheet1.xml"))  # noqa: S314
    return list(strings.findall(f"{{{MAIN}}}si")), sheet


def slice_xlsx(workbook: bytes, ids: set[str] | None) -> tuple[bytes, list[int]]:
    """Keep the header row and rows whose column A is in ``ids`` (all rows if None)."""
    strings, sheet = _xlsx_parts(workbook)
    rows = sheet.findall(f"{{{MAIN}}}sheetData/{{{MAIN}}}row")

    def first_cell(row: ET.Element) -> str | None:
        cell = row.find(f"{{{MAIN}}}c")
        value = None if cell is None else cell.find(f"{{{MAIN}}}v")
        if cell is None or value is None or value.text is None:
            return None
        if cell.get("t") == "s":
            return "".join(t.text or "" for t in strings[int(value.text)].iter(f"{{{MAIN}}}t"))
        return value.text

    selected = [rows[0]] + [r for r in rows[1:] if ids is None or first_cell(r) in ids]
    remap: dict[int, int] = {}
    table: list[ET.Element] = []
    for row in selected:
        for cell in row.findall(f"{{{MAIN}}}c"):
            value = cell.find(f"{{{MAIN}}}v")
            if cell.get("t") == "s" and value is not None and value.text is not None:
                old = int(value.text)
                if old not in remap:
                    remap[old] = len(table)
                    table.append(strings[old])
                value.text = str(remap[old])
    numbers = [int(row.get("r", "0")) for row in selected[1:]]
    return build_xlsx(selected, table), numbers


def build_xlsx(rows: Iterable[ET.Element], strings: list[ET.Element]) -> bytes:
    """Write a one-sheet workbook holding ``rows`` and shared ``strings``."""
    ET.register_namespace("", MAIN)
    ET.register_namespace("r", REL)
    sheet = ET.Element(f"{{{MAIN}}}worksheet")
    data = ET.SubElement(sheet, f"{{{MAIN}}}sheetData")
    data.extend(rows)
    sst = ET.Element(f"{{{MAIN}}}sst", {"count": str(len(strings))})
    sst.extend(strings)
    workbook = (
        f'<workbook xmlns="{MAIN}" xmlns:r="{REL}"><sheets>'
        '<sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    rels = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'
    )
    buffer = io.BytesIO()
    _write_members(
        buffer,
        {
            "xl/workbook.xml": workbook.encode("utf-8"),
            "xl/_rels/workbook.xml.rels": rels.encode("utf-8"),
            "xl/worksheets/sheet1.xml": ET.tostring(sheet, xml_declaration=True),
            "xl/sharedStrings.xml": ET.tostring(sst, xml_declaration=True),
        },
    )
    return buffer.getvalue()


def _write_members(target: Path | io.BytesIO, members: dict[str, bytes]) -> None:
    """Write a deflated zip with a fixed timestamp so reruns are byte-identical."""
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)


def write_zip(path: Path, members: dict[str, bytes]) -> None:
    """Write a fixture zip; it and any workbook inside it are byte-identical on reruns."""
    _write_members(path, members)


def main() -> int:
    """Write every fixture zip and PROVENANCE.json."""
    config = load_config()
    OUT.mkdir(exist_ok=True)
    provenance: dict[str, dict[str, object]] = {}
    public = set(PUBLIC_IDS)
    lea_ids = {school[:7] for school in public} | set(EXTRA_LEA_IDS)
    private = set(PRIVATE_IDS)
    for key, source in config.sources.items():
        candidate = next(c for c in source.candidates if c.sha256)
        zip_path = cache_path(CACHE, candidate.url)
        name = zip_path.name
        table = candidate.members["table"]
        rows: list[int]
        with zipfile.ZipFile(zip_path) as archive:
            names = archive.namelist()
            read = archive.read
            if key in {"public_school_geocodes", "public_lea_geocodes"}:
                ids = public if key == "public_school_geocodes" else lea_ids
                text, rows = slice_lines(read(table), ids, 0, "|", header=False)
                header, _ = slice_xlsx(read(candidate.members["header"]), set())
                members = {table: text, candidate.members["header"]: header}
            elif key == "private_school_geocodes":
                workbook, rows = slice_xlsx(read(table), private)
                members = {table: workbook}
            elif key == "ccd_membership":
                text, rows = slice_membership(zip_path, table, public)
                members = {table: text}
            else:
                ids = private if key == "pss" else public
                data = read(table)
                columns = next(csv.reader([data.split(b"\n", 1)[0].decode().rstrip("\r")]))
                column = "PPIN" if key == "pss" else "NCESSCH"
                text, rows = slice_lines(data, ids, columns.index(column), ",", header=True)
                members = {table: text}
        write_zip(OUT / name, members)
        provenance[name] = {
            "source_key": key,
            "source_url": candidate.url,
            "source_sha256": candidate.sha256,
            "source_members": sorted(names),
            "members_written": sorted(members),
            "rows_kept": {"member": table, "line_or_row_numbers": rows},
        }
    manifest = {
        "public_school_ids": PUBLIC_IDS,
        "extra_lea_ids": EXTRA_LEA_IDS,
        "private_school_ids": PRIVATE_IDS,
        "files": provenance,
    }
    (OUT / "PROVENANCE.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(f"wrote {len(provenance)} fixture zips to {OUT}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
