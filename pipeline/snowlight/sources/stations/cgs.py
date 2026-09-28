"""CGS Infographics Automation's "All Active" closings page, as stations' list files.

CGS (Callaway GraphicSoftware) writes a static HTML page of its "All Active" output
that stations frame or link as their closings list: WKTV's
``ftp2.wktv.com/CGSXML/All%20Active.html`` (Allen Media) today, KIMT's
``ftp2.kimt.com/closings.html`` (Allen Media) from 2020 to 2024, and KRCG's
``/resources/ftptransfer/krcg/closings/WebClose.htm`` (Sinclair) in 2018, among the
captures read. Variant this module reads:

``cgs-all-active``
    ``<meta http-equiv="Created by CGS Infographics Automation"/>``, a title and a
    time in ``<div class="msg">`` blocks ("WKTV Closings", "9/24/2026 7:04:25 PM"),
    then ``table.tablenoborder``. With nothing listed the table's one cell is the
    sentence "There are no 'All Active' closings to report." (live at WKTV on
    2026-09-27; all nine of WKTV's captures read, 2022-03-14 to 2026-01-28, the
    largest, 2023-03-18, among them; KRCG's of 2018-01-25): the empty state.

    With closings listed (KIMT's ``ftp2.kimt.com/closings.html`` was such a page
    from 2020 to 2024: captures of 2020-03-27, 2022-12-21, 2023-02-23 and
    2024-01-14, 61 to 98 entries each), a third ``div.msg`` says how the list is
    sorted ("Sorted by Category, Organization"), each category starts with an
    ``<A NAME>`` anchor and a ``table.tablenoborder`` of ``td.links`` (links to the
    categories), and each entry is a ``table.tableborder`` of one row of three
    cells, their classes alternating plain and ``dark``::

        <table class="tableborder"><tr><td class="cat">Schools</td>
          <td class="org">West Hancock</td><td class="sts">Closed</td></tr></table>

    The ``org`` cell is the name, ``sts`` the status, ``cat`` goes in
    ``raw_extra["category"]``, and the page's time (the ``div.msg`` that is a
    time) is each row's update text (``updated_scope`` ``page``). The stylesheet
    also names ``sts2``, ``ctny`` and ``stslong`` cells (the fields of CGS's XML
    export), which no capture has shown: a row with any other cells, a table of
    another kind, or a page with neither entries nor the empty sentence raises
    :class:`~snowlight.sources.stations.model.ShapeError`.

:func:`read_page` returns None for a body that is not such a page.
"""

import re

from selectolax.parser import HTMLParser, Node

from snowlight.sources.stations.model import JsonScalar, Listing, ParsedRow, ShapeError
from snowlight.sources.stations.regional import listing, node_text, row

VARIANT = "cgs-all-active"
MARK = "Created by CGS Infographics Automation"
EMPTY_SENTENCE = "There are no 'All Active' closings to report."
ENTRY_CELLS = ("cat", "org", "sts")
_MARK = re.compile(re.escape(MARK), re.IGNORECASE)
_STAMP = re.compile(r"\d{1,2}/\d{1,2}/\d{4} \d{1,2}:\d{2}(?::\d{2})? [AP]M")


def _classes(cells: list[Node]) -> tuple[str, ...]:
    """The cells' classes, a ``dark`` alternate named as its plain class."""
    return tuple((cell.attributes.get("class") or "").removesuffix("dark") for cell in cells)


def _entries(tree: HTMLParser, stamp: str | None) -> Listing:
    rows: list[ParsedRow] = []
    skipped = 0
    for table in tree.css("table"):
        kind = table.attributes.get("class")
        if kind == "tablenoborder":
            if _classes(table.css("td")) != ("links",):
                raise ShapeError("a CGS navigation table that is not one cell of links")
            continue
        if kind != "tableborder":
            raise ShapeError(f"a CGS closings page with a table of class {kind!r}")
        for line in table.css("tr"):
            cells = line.css("td")
            if _classes(cells) != ENTRY_CELLS:
                raise ShapeError(f"a CGS entry with cells {_classes(cells)}, not {ENTRY_CELLS}")
            category, name, status = (node_text(cell) for cell in cells)
            extra: dict[str, JsonScalar] = {"category": category}
            if stamp:
                extra["updated_scope"] = "page"
            found = row(name, status, stamp, extra)
            if found is None:
                skipped += 1
            else:
                rows.append(found)
    if not rows and not skipped:
        raise ShapeError("a CGS closings page with neither entries nor its empty sentence")
    return listing(VARIANT, rows, skipped=skipped)


def read_page(text: str) -> Listing | None:
    """Read a CGS "All Active" page; None when ``text`` is not one.

    Raises:
        ShapeError: the page has no title or time, or is in neither shape seen.
    """
    if _MARK.search(text) is None:
        return None
    tree = HTMLParser(text)
    messages = [node_text(div) for div in tree.css("div.msg")]
    if not messages:
        raise ShapeError("a CGS closings page with no title or time")
    cells = [node_text(td) for td in tree.css("table td")]
    if cells == [EMPTY_SENTENCE]:
        return listing(VARIANT, [])
    stamp = next((message for message in messages if _STAMP.fullmatch(message)), None)
    return _entries(tree, stamp)
