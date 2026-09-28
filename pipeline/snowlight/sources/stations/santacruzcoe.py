"""Santa Cruz County Office of Education: school closures, a published Google Sheet.

The county office's page ``https://santacruzcoe.org/schoolclosures/`` ("School
closures - yesterday, today, and in the future") lists "school closures across
Santa Cruz County due to emergencies and/or events that school districts share
with the County Office of Education"; it frames a published Google Sheet, "School
Closure (Responses)", tab ``CLOSURES``. A browser loads the list in three steps,
and this adapter reads each:

``santacruzcoe-page``
    The county office's page frames the sheet's widget view
    (``<iframe ... src="https://docs.google.com/spreadsheets/d/e/{key}/pubhtml?gid=1755311565&amp;single=true&amp;widget=true&amp;headers=false">``,
    live 2026-09-26 and 2026-09-27). A
    :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED` listing that
    follows the frame (entities decoded).

``santacruzcoe-widget``
    The widget view draws the sheet in script: it names the tab's page in a script
    string, escaped (``items.push({name: "CLOSURES", pageUrl: "https:\\/\\/docs.google.com\\/...``,
    ``/pubhtml/sheet?headers=false&gid=1755311565`` once unescaped).
    A deferred listing that follows the named tab's page.

``santacruzcoe-sheet``
    The tab's page, which the server writes with the sheet in a ``table.waffle``
    (live 2026-09-27): a header row naming the columns ``CLOSURE DATE``,
    ``DISTRICT``, ``SCHOOLS CLOSED``, ``REASON`` and ``CONTACT`` (``CONTACT``
    merged over two columns), then one row per closure the districts reported.
    Cells are expanded over the columns they span. Each row with any text is a
    row: its ``SCHOOLS CLOSED`` cell is the name, and the other columns go in
    ``raw_extra`` (``closure_date``, ``district``, ``reason``, ``contact``). The
    sheet has no status column: it lists closures only, under the heading
    ``SCHOOLS CLOSED``, so that heading is each row's status
    (``raw_extra["status_from"]`` is ``"column heading"``). A row whose
    ``SCHOOLS CLOSED`` cell is empty is counted as skipped. A header row followed
    only by empty rows (live on 2026-09-27: ten empty rows) is the empty state.

The columns are read by their headings, so a sheet whose header row does not name
exactly these columns, in this order, raises
:class:`~snowlight.sources.stations.model.ShapeError`, as does anything else.
"""

import re
from html import unescape

from selectolax.parser import HTMLParser, Node

from snowlight.sources.stations.model import JsonScalar, Listing, ParsedRow, ShapeError
from snowlight.sources.stations.regional import (
    deferred,
    document,
    html_text,
    listing,
    node_text,
    row,
)

PAGE = "santacruzcoe-page"
WIDGET = "santacruzcoe-widget"
SHEET = "santacruzcoe-sheet"
HEADER = ("CLOSURE DATE", "DISTRICT", "SCHOOLS CLOSED", "REASON", "CONTACT")
NAME_COLUMN = "SCHOOLS CLOSED"
_EXTRA_KEYS = {
    "CLOSURE DATE": "closure_date",
    "DISTRICT": "district",
    "REASON": "reason",
    "CONTACT": "contact",
}
_SHEET_KEY = r"https://docs\.google\.com/spreadsheets/d/e/[A-Za-z0-9_-]+"
_FRAME = re.compile(
    r"<iframe\b[^>]*?\bsrc=\"(" + _SHEET_KEY + r"/pubhtml\?[^\"]*)\"", re.IGNORECASE
)
_TAB = re.compile(r"items\.push\(\{name:\s*\"([^\"]*)\",\s*pageUrl:\s*\"([^\"]+)\"")
_TAB_URL = re.compile(r"^" + _SHEET_KEY + r"/pubhtml/sheet\?")


def _script_string(text: str) -> str:
    """Undo the escapes a script string literal uses for ``/`` and ``=``."""
    return text.replace("\\/", "/").replace("\\x3d", "=").replace("\\u003d", "=")


def _expanded(tr: Node) -> list[str]:
    """A sheet row's cells, each repeated over the columns it spans (text in the first)."""
    cells: list[str] = []
    for td in tr.css("td"):
        span = td.attributes.get("colspan") or "1"
        if not span.isdigit() or int(span) < 1:
            raise ShapeError(f"a sheet cell spans {span!r} columns")
        cells.append(node_text(td))
        cells.extend([""] * (int(span) - 1))
    return cells


def _closure(cells: list[str], width: int) -> ParsedRow | None:
    by_heading = dict(zip(HEADER, cells[: len(HEADER)], strict=True))
    extra: dict[str, JsonScalar] = {"status_from": "column heading"}
    for heading, key in _EXTRA_KEYS.items():
        text = by_heading[heading]
        if heading == "CONTACT":
            text = " ".join(cell for cell in cells[len(HEADER) - 1 : width] if cell)
        if text:
            extra[key] = text
    return row(by_heading[NAME_COLUMN], NAME_COLUMN, None, extra)


def _sheet(table: Node) -> Listing:
    rows = [_expanded(tr) for tr in table.css("tbody tr")]
    if not rows:
        raise ShapeError("the closures sheet has no rows")
    header, *entries = rows
    width = len(header)
    named = [cell for cell in header if cell]
    if tuple(named) != HEADER or tuple(header[: len(HEADER)]) != HEADER:
        raise ShapeError(f"the closures sheet's header row is {header}, not {list(HEADER)}")
    found: list[ParsedRow] = []
    skipped = 0
    for cells in entries:
        if len(cells) != width:
            raise ShapeError(f"a closures sheet row has {len(cells)} cells, not {width}")
        if not any(cells):
            continue
        parsed = _closure(cells, width)
        if parsed is None:
            skipped += 1
        else:
            found.append(parsed)
    return listing(SHEET, found, skipped=skipped)


def parse(body: bytes) -> Listing:
    """Read the county office's page, the sheet's widget view or its tab page."""
    text = html_text(body)
    table = HTMLParser(text).css_first("table.waffle")
    if table is not None:
        return _sheet(table)
    tabs = [(name, _script_string(url)) for name, url in _TAB.findall(text)]
    if tabs:
        if len(tabs) != 1 or not _TAB_URL.match(tabs[0][1]):
            raise ShapeError(f"the sheet's widget view names {len(tabs)} tabs or an unknown page")
        return deferred(WIDGET, (tabs[0][1],))
    frames = [unescape(url) for url in _FRAME.findall(text)]
    if frames:
        return deferred(PAGE, tuple(dict.fromkeys(frames)))
    raise ShapeError("not the Santa Cruz COE closures page, its sheet's widget view or tab page")


def slice_body(body: bytes) -> bytes:
    """Keep the page's frame, the widget's tab line, or the sheet's table."""
    found = parse(body)
    text = html_text(body)
    if found.variant == PAGE:
        frames = "".join(
            f'<iframe src="{url.replace("&", "&amp;")}"></iframe>' for url in found.follows
        )
        return document(frames)
    if found.variant == WIDGET:
        name, url = _TAB.findall(text)[0]
        return document(f'<script>items.push({{name: "{name}", pageUrl: "{url}"}});</script>')
    table = HTMLParser(text).css_first("table.waffle")
    inner = "".join(tr.html or "" for tr in table.css("tbody tr")) if table is not None else ""
    return document(f'<table class="waffle"><tbody>{inner}</tbody></table>')
