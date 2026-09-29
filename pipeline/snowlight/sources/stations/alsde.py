"""Alabama State Department of Education: the statewide school closures and delays list.

The ALSDE keeps one public list of the closings, delays and early dismissals that
Alabama's public school systems report to it, "School Closures/Delays"
(``https://schoolnotification.alsde.edu/SchoolClosuresPublic.aspx``). Its
"Weather Closure List" page (``https://www.alabamaachieves.org/weather-closure-list/``)
frames that page in an ``iframe`` and links it ("Click Here"). The list is an
ASP.NET page whose DevExpress grid (``ClosuresGrid``) is rendered on the server, so
the page as served holds every row the grid shows, and so do archived captures of it.

Variant this adapter reads:

``alsde-closures-grid``
    The grid's header row (``td[id^=ClosuresGrid_col]``, captions "Date", "System",
    "School(s)", "Type of Closure", "Opening or Closing Time", "Reason",
    "Extracurricular / After School Activities Cancelled", "Superintendent Comments",
    "Modified") over its data table ``table#ClosuresGrid_DXMainTable``, one
    ``tr.dxgvDataRow`` per report. Seen live on 2026-09-28: four reports, newest
    first: Pike County's early dismissal of 2026-09-25 at 1:00 PM (Pike County
    Elementary School and Pike County High School, a water main break), Perry County's
    closings of 2026-09-16 and 2026-08-24 and Tallapoosa County's of 2026-09-14. The
    grid shows the school year's reports, not only the day's: each row carries its own
    date. Archived captures read the same way (archive-captures run 36445058527): the
    capture of 2025-01-21 17:26 UTC, in the Gulf Coast snowstorm, holds 118 reports of
    54 systems (180 rows: "Closed", "Delayed", "Early Dismissal", "After School
    Activities Cancelled", with the reason "Snow/Ice" and the superintendents'
    comments); those of 2022-06-05, 2023-08-30 and 2026-05-17 hold a school year's
    reports each (176, 20 and 147 rows, among them "COVID-19" as a type of closure).

Each school a report names (the School(s) cell, one name per line) is one row:
``raw_name`` the school's name as written, ``raw_status`` the Type of Closure
("Closed", "Early Dismissal", ...), ``raw_updated_text`` the Modified cell (when the
system last changed the report, e.g. ``9/25/2026 11:32:39 AM``), and ``raw_extra``
``system`` (the reporting school system, e.g. "Pike County"), ``date`` (the day the
report is for), ``time`` (the Opening or Closing Time, when given), ``reason``,
``comments`` (the superintendent's), ``activities_cancelled`` (the Extracurricular
check box, true or false) and ``schools`` (how many schools the report names). A
report for a whole system names "All Schools" (as most do on storm days): its row is
named for the system, with ``raw_extra["all_schools"]`` true; so is a report whose
School(s) cell is empty. Nothing here decides whether a report is for today: the date
is kept for the status reader.

A grid with its header but no data row (DevExpress writes a ``tr.dxgvEmptyDataRow``
then) is an empty list. Anything else raises
:class:`~snowlight.sources.stations.model.ShapeError`: a page without the grid, a
grid without the System or Type of Closure column, or a data row whose cells do not
line up with the header.
"""

import re
from html import escape

from selectolax.parser import HTMLParser, Node

from snowlight.sources.stations.gap_markup import (
    collapse,
    document,
    html_text,
    make_listing,
    make_row,
    node_text,
)
from snowlight.sources.stations.model import JsonScalar, Listing, ParsedRow, ShapeError

VARIANT = "alsde-closures-grid"
DATE = "Date"
SYSTEM = "System"
SCHOOLS = "School(s)"
TYPE = "Type of Closure"
TIME = "Opening or Closing Time"
REASON = "Reason"
ACTIVITIES = "Extracurricular / After School Activities Cancelled"
COMMENTS = "Superintendent Comments"
MODIFIED = "Modified"
REQUIRED = (SYSTEM, TYPE)
_EXTRA = {DATE: "date", TIME: "time", REASON: "reason", COMMENTS: "comments"}
ALL_SCHOOLS = "all schools"
_STATE = re.compile(r"'(pageIndex|pageCount|pageRowCount)':(-?\d+)")
_CHECKED = "dxWeb_edtCheckBoxChecked"
_UNCHECKED = "dxWeb_edtCheckBoxUnchecked"


def _captions(tree: HTMLParser) -> list[str]:
    """The grid's column captions in order, without the leading command column."""
    captions = [node_text(node) for node in tree.css('td[id^="ClosuresGrid_col"]')]
    while captions and not captions[0]:
        captions.pop(0)
    return captions


def _data_cells(row: Node) -> list[Node]:
    """A data row's cells under the captions (not the command column or the filler)."""
    cells: list[Node] = []
    for cell in row.css("td"):
        classes = (cell.attributes.get("class") or "").split()
        if "dxgv" in classes and "dxgvCommandColumn" not in classes:
            cells.append(cell)
    return cells


def _lines(cell: Node) -> list[str]:
    """A cell's lines (its ``<br>``-separated names), each collapsed, empty ones dropped."""
    parts = (cell.html or "").replace("<br/>", "\n").replace("<br>", "\n").split("\n")
    return [text for text in (collapse(HTMLParser(part).text(deep=True)) for part in parts) if text]


def _checked(cell: Node) -> bool | None:
    classes = " ".join((span.attributes.get("class") or "") for span in cell.css("span"))
    if _CHECKED in classes:
        return True
    if _UNCHECKED in classes:
        return False
    return None


def _report(captions: list[str], cells: list[Node]) -> tuple[list[ParsedRow], int]:
    if len(cells) != len(captions):
        raise ShapeError(f"a closures row has {len(cells)} cells, not {len(captions)}")
    by_caption = dict(zip(captions, cells, strict=True))
    system = node_text(by_caption[SYSTEM])
    status = node_text(by_caption[TYPE])
    modified = node_text(by_caption[MODIFIED]) if MODIFIED in by_caption else ""
    extra: dict[str, JsonScalar] = {"system": system}
    for caption, key in _EXTRA.items():
        text = node_text(by_caption[caption]) if caption in by_caption else ""
        if text:
            extra[key] = text
    if ACTIVITIES in by_caption:
        checked = _checked(by_caption[ACTIVITIES])
        if checked is not None:
            extra["activities_cancelled"] = checked
    schools = _lines(by_caption[SCHOOLS]) if SCHOOLS in by_caption else []
    extra["schools"] = len(schools)
    rows: list[ParsedRow] = []
    skipped = 0
    for school in schools or [system]:
        fields = dict(extra)
        whole = school.casefold() == ALL_SCHOOLS  # the report is for the whole system
        if whole:
            fields["all_schools"] = True
        found = make_row(system if whole else school, status, modified or None, fields)
        if found is None:
            skipped += 1
        else:
            rows.append(found)
    return rows, skipped


def parse(body: bytes) -> Listing:
    """Read the ALSDE School Closures/Delays page."""
    tree = HTMLParser(html_text(body))
    table = tree.css_first("table#ClosuresGrid_DXMainTable")
    if table is None:
        raise ShapeError("not the ALSDE School Closures/Delays page (no ClosuresGrid table)")
    captions = _captions(tree)
    missing = [caption for caption in REQUIRED if caption not in captions]
    if missing:
        raise ShapeError(f"the closures grid has no {', '.join(missing)} column")
    reports = table.css("tr.dxgvDataRow")
    _check_all_shown(tree, len(reports))
    rows: list[ParsedRow] = []
    skipped = 0
    for tr in reports:
        found, nameless = _report(captions, _data_cells(tr))
        rows.extend(found)
        skipped += nameless
    return make_listing(VARIANT, rows, skipped=skipped)


def _check_all_shown(tree: HTMLParser, shown: int) -> None:
    """Refuse a grid that shows one page of several, or fewer reports than it says it holds.

    The grid's client state (its ``ASPxClientGridView`` script, present in the page as
    served, not in a sliced fixture) gives ``pageIndex`` (-1 when every row is shown
    on one page, as in every capture read), ``pageCount`` and ``pageRowCount``.
    """
    script = next(
        (node.text() for node in tree.css("script") if "ASPxClientGridView" in node.text()), ""
    )
    state = {key: int(value) for key, value in _STATE.findall(script)}
    if state.get("pageIndex", -1) != -1 and state.get("pageCount", 1) > 1:
        raise ShapeError("the closures grid shows one page of several")
    if "pageRowCount" in state and state["pageRowCount"] != shown:
        raise ShapeError(
            f"the closures grid says it holds {state['pageRowCount']} reports but shows {shown}"
        )


def slice_body(body: bytes) -> bytes:
    """Keep the grid's captions and data table (rows as served), nothing else."""
    parse(body)
    tree = HTMLParser(html_text(body))
    captions = "".join(
        f'<td id="{escape(node.attributes.get("id") or "")}">{escape(node_text(node))}</td>'
        for node in tree.css('td[id^="ClosuresGrid_col"]')
    )
    table = tree.css_first("table#ClosuresGrid_DXMainTable")
    rows = table.html if table is not None else ""  # parse() found it
    return document(f"<table><tr>{captions}</tr></table>{rows or ''}")
