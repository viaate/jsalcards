"""News 12's closings: one server-rendered page per region.

News 12 (Altice) serves each region's closings from one page,
``https://itv.news12.com/school_closings/closings.jsp?region={LI,NJ,WC,HV,CT,BX,BK}``.
Variant this adapter reads:

``news12-jsp``
    Two tabs named in ``table#table_header`` ("Today Sun Sep 27, 2026", "Tomorrow
    Mon Sep 28, 2026") over one table, ``table#table-reflow``, whose header is Name,
    City and Status and whose body holds one row per organization and day::

        <tr df="0"><td><div>Suffolk Community College</div></td><td>Selden</td>
            <td>All Day, Evening Classes and Activities Canceled<span></span></td></tr>

    (seen populated live on 2026-09-26 and 2026-09-27). ``df`` names the tab: 0
    today, 1 tomorrow. The first cell is the name, the third the status; the city
    goes in ``raw_extra["city"]``, and the tab's label and date in
    ``raw_extra["day"]`` (``"today"`` or ``"tomorrow"``) and
    ``raw_extra["day_label"]`` (the tab's own text). A table body with no rows is
    the empty state (the page's script then writes "No 'Today' closings/delays
    have been submitted for this region.").

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`.
"""

from selectolax.parser import HTMLParser

from snowlight.sources.stations.model import JsonScalar, Listing, ParsedRow, ShapeError
from snowlight.sources.stations.regional import document, html_text, listing, node_text, row

VARIANT = "news12-jsp"
_DAYS = {"0": "today", "1": "tomorrow"}
_HEADER = ["Name", "City", "Status"]
_CELLS = 3


def parse(body: bytes) -> Listing:
    """Read a News 12 region's closings page."""
    tree = HTMLParser(html_text(body))
    table = tree.css_first("table#table-reflow")
    if table is None:
        raise ShapeError("not a News 12 closings page (no table-reflow)")
    header = [node_text(th) for th in table.css("thead th")]
    if header != _HEADER:
        raise ShapeError(f"the News 12 table's columns are {header!r}")
    tabs = [node_text(td) for td in tree.css("table#table_header td")]
    labels = dict(zip(("0", "1"), tabs, strict=False))
    rows: list[ParsedRow] = []
    skipped = 0
    for tr in table.css("tbody tr"):
        cells = tr.css("td")
        if len(cells) != _CELLS:
            raise ShapeError(f"a News 12 row has {len(cells)} cells")
        day = tr.attributes.get("df") or ""
        if day not in _DAYS:
            raise ShapeError(f"a News 12 row names no known tab: df={day!r}")
        extra: dict[str, JsonScalar] = {"city": node_text(cells[1]), "day": _DAYS[day]}
        if day in labels:
            extra["day_label"] = labels[day]
        found = row(node_text(cells[0]), node_text(cells[2]), None, extra)
        if found is None:
            skipped += 1
        else:
            rows.append(found)
    return listing(VARIANT, rows, skipped=skipped)


def slice_body(body: bytes) -> bytes:
    """Cut the page to its tab header and its closings table."""
    parse(body)
    tree = HTMLParser(html_text(body))
    tabs = tree.css_first("table#table_header")
    table = tree.css_first("table#table-reflow")
    parts = [node.html or "" for node in (tabs, table) if node is not None]
    return document("".join(parts))
