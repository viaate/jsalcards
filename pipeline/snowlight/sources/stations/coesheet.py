"""County offices of education that publish a school closure sheet (Shasta and Trinity, California).

Two northern California county offices keep a "School Closure Information" page
that frames a Google Sheet their schools update, listing every school with its
status (so a sheet always holds rows: "OPEN" or "Open" for most):

* Shasta County Office of Education
  (``https://www.shastacoe.org/office-of-education/school-closures``): "entered and
  updated by district superintendents and charter school leaders" ("School
  Closures 2026-27"; live on 2026-09-27 two Black Butte schools read "Closing at
  12:45", updated "9/10 9:45");
* Trinity County Office of Education
  (``https://www.tcoek12.org/school-districts/school-closure-information``):
  "updated by the individual school administrative offices" (live on 2026-09-27
  every school "Open", updated "01/05/2026 8:47 AM").

A browser loads a sheet in up to three steps, and this adapter reads each:

``coesheet-page``
    The county office's page frames the published sheet
    (``<iframe src="https://docs.google.com/spreadsheets/d/e/{key}/pubhtml?gid={gid}&single=true&widget=...">``;
    Trinity's page uses an ``<embed>`` element with the same ``src``).
    A :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED` listing that
    follows the frame.

``coesheet-widget``
    With ``widget=true`` (Shasta) the framed view draws the sheet in script: it
    names each tab's page in a script string (``items.push({name: "School
    Closure", pageUrl: "https:\\/\\/docs.google.com\\/spreadsheets\\/d\\/e\\/{key}\\/...``,
    escaped ``/pubhtml/sheet?headers=false&gid={gid}``). A deferred listing that
    follows the first tab's page.

``coesheet-table``
    A view the server writes with the sheet in it: the tab page
    (``/pubhtml/sheet?headers=false&gid={gid}``, Shasta) or the framed view itself
    with ``widget=false`` (Trinity). Its ``table.waffle`` rows, with merged cells
    expanded to the columns they span, are the sheet's rows.

``coesheet-csv``
    The same publication's CSV output (``/pub?gid={gid}&single=true&output=csv``),
    read live on 2026-09-27 as a check on Shasta's tab page (the same rows).

A sheet, in any form: title lines (the county's name, the school year such as
"2026-2027 SCHOOL YEAR"), then a header row naming four columns: ``DISTRICT NAME``,
``SCHOOL NAME`` (Shasta: ``SCHOOL NAME (**CHARTER SCHOOL)``), ``DATE/TIME UPDATED``
(Shasta merges it over four columns) and ``OPEN / CLOSED INFO`` (Trinity:
``OPEN/CLOSED INFO``). Below it, a row with only a district name starts that
district's schools (``raw_extra["district"]``), and a row with a school name is one
school: the name (a trailing ``**``, Shasta's charter mark, is removed and kept as
``raw_extra["charter"]``), the text of the date/time cells as ``raw_updated_text``
(``raw_extra["updated_scope"]`` is ``"row"``), and the status column as the status.
The school year goes in ``raw_extra["school_year"]``. Rows above the header (a
"Today's Date" line at Trinity) are not schools.

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`,
including a sheet without that header row, a cell outside the header's columns,
a school row before any district, and a sheet that lists no school.
"""

import csv
import io
import re
from dataclasses import dataclass
from html import escape, unescape

from selectolax.parser import HTMLParser, Node

from snowlight.sources.stations.body import decode
from snowlight.sources.stations.gap_markup import (
    collapse,
    deferred,
    document,
    html_text,
    make_listing,
    make_row,
    node_text,
)
from snowlight.sources.stations.model import JsonScalar, Listing, ParsedRow, ShapeError

TABLE = "coesheet-table"
CSV = "coesheet-csv"
PAGE = "coesheet-page"
WIDGET = "coesheet-widget"
DISTRICT_LABEL = "DISTRICT NAME"
SCHOOL_LABEL = re.compile(r"^SCHOOL NAME(?: \(\*\*CHARTER SCHOOL\))?$")
UPDATED_LABEL = "DATE/TIME UPDATED"
STATUS_LABEL = re.compile(r"^OPEN ?/ ?CLOSED INFO$")
CHARTER_MARK = "**"
_YEAR = re.compile(r"^\d{4}-\d{4} SCHOOL YEAR$")
_FRAME = re.compile(
    r"<(?:iframe|embed)\b[^>]*\bsrc=\"(https://docs\.google\.com/spreadsheets/d/e/[A-Za-z0-9_-]+/pubhtml"
    r"\?[^\"]*)\"",
    re.IGNORECASE,
)
_TAB = re.compile(r"items\.push\(\{name:\s*\"[^\"]*\",\s*pageUrl:\s*\"([^\"]+)\"")
_TAB_URL = re.compile(r"^https://docs\.google\.com/spreadsheets/d/e/[A-Za-z0-9_-]+/pubhtml/sheet\?")


@dataclass(frozen=True, slots=True)
class _Columns:
    """Where a sheet's header row puts its four columns."""

    district: int
    school: int
    updated: int
    status: int

    @classmethod
    def find(cls, row: list[str]) -> "_Columns | None":
        """Read a header row, or None when ``row`` is not one."""
        try:
            district = row.index(DISTRICT_LABEL)
            updated = row.index(UPDATED_LABEL)
        except ValueError:
            return None
        school = next((i for i, cell in enumerate(row) if SCHOOL_LABEL.match(cell)), None)
        status = next((i for i, cell in enumerate(row) if STATUS_LABEL.match(cell)), None)
        if school is None or status is None or not district < school < updated < status:
            return None
        return cls(district, school, updated, status)


def _script_string(text: str) -> str:
    """Undo the escapes a script string literal uses for ``/`` and ``=``."""
    return text.replace("\\/", "/").replace("\\x3d", "=").replace("\\u003d", "=")


def _cell(row: list[str], column: int) -> str:
    return row[column] if column < len(row) else ""


def _school(row: list[str], columns: _Columns, district: str, year: str | None) -> ParsedRow | None:
    name = row[columns.school]
    extra: dict[str, JsonScalar] = {"district": district}
    if name.endswith(CHARTER_MARK):
        name = name.removesuffix(CHARTER_MARK).strip()
        extra["charter"] = True
    updated = " ".join(cell for cell in row[columns.updated : columns.status] if cell) or None
    if updated:
        extra["updated_scope"] = "row"
    if year:
        extra["school_year"] = year
    return make_row(name, _cell(row, columns.status), updated, extra)


def _grid_rows(rows: list[list[str]], variant: str) -> Listing:
    found_header = next(
        ((number, cols) for number, row in enumerate(rows) if (cols := _Columns.find(row))), None
    )
    if found_header is None:
        raise ShapeError("no closure-sheet header row (DISTRICT NAME, SCHOOL NAME, ...)")
    start, columns = found_header
    year = next((cell for row in rows[:start] for cell in row if _YEAR.match(cell)), None)
    district: str | None = None
    found: list[ParsedRow] = []
    for row in rows[start + 1 :]:
        if not any(row):
            continue
        if any(row[: columns.district]) or any(row[columns.status + 1 :]):
            raise ShapeError(f"a closure-sheet row is outside the sheet's columns: {row}")
        named = _cell(row, columns.district)
        if named and not any(row[columns.district + 1 :]):
            district = named
            continue
        if named or not _cell(row, columns.school):
            raise ShapeError(f"a closure-sheet row is neither a district nor a school: {row}")
        if district is None:
            raise ShapeError("a closure-sheet school row comes before any district")
        parsed = _school(row, columns, district, year)
        if parsed is not None:
            found.append(parsed)
    if not found:
        raise ShapeError("the closure sheet lists no school")
    return make_listing(variant, found)


def _expanded(tr: Node) -> list[str]:
    """A waffle row's cells, each repeated over the columns it spans (text in the first)."""
    cells: list[str] = []
    for td in tr.css("td"):
        span = td.attributes.get("colspan") or "1"
        if not span.isdigit() or int(span) < 1:
            raise ShapeError(f"a sheet cell spans {span!r} columns")
        cells.append(node_text(td))
        cells.extend([""] * (int(span) - 1))
    return cells


def _table(tree: HTMLParser) -> Listing:
    table = tree.css_first("table.waffle")
    if table is None:
        raise ShapeError("no sheet table")
    rows = [_expanded(tr) for tr in table.css("tr") if tr.css_first("td.freezebar-cell") is None]
    return _grid_rows(rows, TABLE)


def _csv(text: str) -> Listing:
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or len({len(row) for row in rows}) != 1:
        raise ShapeError("a closure sheet's CSV rows are not all the same width")
    return _grid_rows([[collapse(cell) for cell in row] for row in rows], CSV)


def parse(body: bytes) -> Listing:
    """Read a county office's closure sheet (any form), or a page on the way to it."""
    text = html_text(body)
    head = text[:4000].lower()
    if "<html" not in head and "<!doctype" not in head:
        if UPDATED_LABEL in text:
            return _csv(text)
        raise ShapeError("neither a closure sheet nor a page that frames one")
    tree = HTMLParser(text)
    if tree.css_first("table.waffle") is not None:
        return _table(tree)
    tab = _TAB.search(text)
    if tab is not None:
        url = _script_string(tab.group(1))
        if not _TAB_URL.match(url):
            raise ShapeError(f"the sheet widget names an unexpected tab page: {url}")
        return deferred(WIDGET, (url,))
    frame = _FRAME.search(text)
    if frame is not None:
        return deferred(PAGE, (unescape(frame.group(1)),))
    raise ShapeError("neither a closure sheet nor a page that frames one")


def slice_body(body: bytes) -> bytes:
    """Cut a page or widget to the address it follows; a table view keeps only its table.

    The CSV output is kept whole (decoded). A table view keeps its ``table.waffle``
    with only each cell's text and span (styles, scripts and page chrome dropped).
    """
    found = parse(body)
    if found.variant == PAGE:
        return document(f'<iframe src="{escape(found.follows[0])}"></iframe>')
    if found.variant == WIDGET:
        escaped = found.follows[0].replace("/", "\\/").replace("=", "\\x3d", 1)
        return document(f'<script>items.push({{name: "tab", pageUrl: "{escaped}"}});</script>')
    if found.variant == TABLE:
        return document(_minimal_table(HTMLParser(html_text(body))))
    return decode(body)


def _minimal_table(tree: HTMLParser) -> str:
    """The sheet's table with only each cell's text and span (styles and headers dropped)."""
    lines = []
    table = tree.css_first("table.waffle")
    for tr in table.css("tr") if table is not None else ():
        if tr.css_first("td.freezebar-cell") is not None:
            continue
        cells = []
        for td in tr.css("td"):
            span = td.attributes.get("colspan") or "1"
            attribute = f' colspan="{span}"' if span != "1" else ""
            cells.append(f"<td{attribute}>{escape(node_text(td))}</td>")
        lines.append(f"<tr>{''.join(cells)}</tr>")
    return '<table class="waffle">' + "\n".join(lines) + "</table>"
