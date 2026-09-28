"""New Jersey 101.5's statewide closings (Townsquare Media): a by-county file its page frames.

The closings page (``https://nj1015.com/closings/``) frames
``/wp-content/uploads/njclosings/ByCountyclosings.html``, which calls itself the
statewide list. Variants this adapter reads:

``townsquare-closings-table``
    The framed file: "Closings Last Updated at 11:30pm on 12/26/2025" over
    ``table#closings-table``, arranged by county, as the capture of 2025-12-27
    04:31 UTC shows::

        <tr><td colspan="2" class="county" valign="bottom">Middlesex County</td></tr>
        <tr class="business-rows">
          <td class="business-details"><span class="business">Amboy Bank-Old Bridge</span><br>
            <span class="city">Old Bridge</span></td>
          <td class="business-details"><span class="status">All Branches will be closed
            Saturday Dec 27</span><br><span class="message">Due to weather. ...</span></td></tr>

    (The file had the same form on 2015-03-05, with 185 rows across the counties.)
    The ``business`` text is the name and the ``status`` text the status; the
    ``city``, the ``message`` and the county heading in force go in ``raw_extra``
    (``city``, ``message``, ``group``). The update time is each row's
    ``raw_updated_text``. The one bold cell "No Closings have been reported at this
    time" (live on 2026-09-26 and 2026-09-27, archived 2025-10-03) is the empty
    state. Every ``business`` in the table must be read as a row.

``townsquare-page``
    The page: its post body (a JSON string in the page) frames the file
    (``<iframe src=\\"/wp-content/uploads/njclosings/ByCountyclosings.html\\"``). A
    :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED` listing that
    follows it.

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`.
"""

import re

from selectolax.parser import HTMLParser, Node

from snowlight.sources.stations.body import decode
from snowlight.sources.stations.model import JsonScalar, Listing, ParsedRow, ShapeError
from snowlight.sources.stations.regional import (
    collapse,
    deferred,
    document,
    html_text,
    listing,
    node_text,
    row,
)

TABLE = "townsquare-closings-table"
PAGE = "townsquare-page"
EMPTY_SENTENCE = "No Closings have been reported at this time"
_FRAME = re.compile(r"<iframe src=\\*\"(/wp-content/uploads/njclosings/[^\"\\]+\.html?)\\*\"")
_STAMP = re.compile(r"Closings Last Updated at\s*([^<]*?)\s*<", re.IGNORECASE)
_TABLE_ID = re.compile(r"<table\b[^>]*\bid=\"closings-table\"", re.IGNORECASE)


def _one(tr: Node, selector: str, *, required: bool) -> str | None:
    found = tr.css(selector)
    if len(found) > 1 or (required and not found):
        raise ShapeError(f"a closings table row holds {len(found)} {selector}")
    return node_text(found[0]) if found else None


def _business(tr: Node, updated: str | None, county: str | None) -> ParsedRow | None:
    name = _one(tr, "span.business", required=True) or ""
    status = _one(tr, "span.status", required=True) or ""
    extra: dict[str, JsonScalar] = {"updated_scope": "page"} if updated else {}
    for key, selector in (("city", "span.city"), ("message", "span.message")):
        value = _one(tr, selector, required=False)
        if value:
            extra[key] = value
    if county is not None:
        extra["group"] = county
    return row(name, status, updated, extra)


def _table(text: str) -> Listing:
    stamp = _STAMP.search(text)
    updated = collapse(stamp.group(1)) if stamp is not None and stamp.group(1).strip() else None
    table = HTMLParser(text).css_first("table#closings-table")
    if table is None:
        raise ShapeError("NJ 101.5's closings file has no closings table")
    county: str | None = None
    empty = False
    rows: list[ParsedRow] = []
    skipped = 0
    for tr in table.css("tr"):
        cells = tr.css("td")
        if "business-rows" in (tr.attributes.get("class") or "").split():
            found = _business(tr, updated, county)
            if found is None:
                skipped += 1
            else:
                rows.append(found)
        elif len(cells) == 1 and "county" in (cells[0].attributes.get("class") or "").split():
            county = node_text(cells[0]) or None
        elif len(cells) == 1 and node_text(cells[0]) == EMPTY_SENTENCE:
            empty = True
        elif node_text(tr):
            raise ShapeError(f"a closings table row not seen before: {node_text(tr)[:60]!r}")
    if len(table.css("span.business")) != len(rows) + skipped:
        raise ShapeError("the closings table names businesses outside its rows")
    if rows and empty:
        raise ShapeError("the closings table lists rows and says none are reported")
    if not rows and not empty:
        raise ShapeError("the closings table holds no rows and no no-closings line")
    return listing(TABLE, rows, skipped=skipped)


def parse(body: bytes) -> Listing:
    """Read NJ 101.5's by-county closings file or the page that frames it."""
    text = html_text(body)
    if _TABLE_ID.search(text) is not None and _STAMP.search(text) is not None:
        return _table(text)
    frame = _FRAME.search(text)
    if frame is None:
        raise ShapeError("not NJ 101.5's closings file or page")
    return deferred(PAGE, (frame.group(1),))


def slice_body(body: bytes) -> bytes:
    """Cut a page to its frame; the file stays whole."""
    found = parse(body)
    if found.variant == PAGE:
        return document(f'<iframe src="{found.follows[0]}"></iframe>')
    return decode(body)
