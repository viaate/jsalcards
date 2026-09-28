"""Delaware's statewide school closings (Department of Education, schoolclosings.delaware.gov).

The state's page (``https://schoolclosings.delaware.gov/``) fills a jqGrid table
from ``/XML/PortalFeed`` (``jQuery.ajax({url: '/XML/PortalFeed', ...})``), whose
columns the page names: ``colModel`` ``school``, ``action``, ``district``,
``note``, headed "District / School", "Details", "District" and "Date" (in 2022
the last was headed "Additional Information"). Variants this adapter reads:

``delaware-portal-xml``
    jqGrid's XML: ``<rows>`` with ``<records>`` (the count), the time the list was
    made (``<timestamp>`` in 2019, ``<lastModified>``, which the page shows as "Last
    Updated:", later) and one ``<row>`` per entry holding one ``<cell>`` per column
    in the page's column order, as the storm-day capture of 2019-02-20 00:37 UTC
    shows (185 entries)::

        <row id='1'><cell>ALFRED G. WATERS MIDDLE SCHOOL</cell>
          <cell>Feb. 20: ASD Schools/Offices will be closed</cell>
          <cell>APPOQUINIMINK SCHOOL DISTRICT</cell>
          <cell>In advance of Wednesday's wintry mix ...</cell></row>

    Cells are read by position, as the page's grid reads them (jqGrid's
    ``addXmlData`` gives the n-th ``<cell>`` to the n-th column of ``colModel``
    and ignores cells beyond the last column): the first cell (``school``) is the
    name, the second (``action``) the status, and the third and fourth go in
    ``raw_extra`` under their column names (``district``, ``note``; the row's
    ``id`` as ``id``). A cell past the fourth, which the page does not show, is
    kept in ``raw_extra`` as ``cell_5``, ``cell_6``, ...: the populated live feed
    of 2026-09-28 00:27 UTC carries five, the fifth the district's RSS item::

        <timestamp></timestamp><page>1</page><records>1</records><row id='1'>
          <cell>Indian River School District CLosed on Monday</cell>
          <cell>Due to inclement weather, all Indian River School District ...</cell>
          <cell>Indian River School District CLosed on Monday</cell>
          <cell>Sun, 27 Sep 2026 23:22:37 GMT</cell>
          <cell>https://rss.finalsiteconnect.com/197765/DEEDU/79164771.xml</cell></row>

    (the page groups rows by ``district`` and shows "Indian River School District
    CLosed on Monday - 1 Item(s)"). A row with fewer than the two cells a list
    entry is made of (name and details), or holding anything but ``<cell>``, is
    not in the grid's shape.

    The update text: when the ``note`` cell (headed "Date" on the pages archived
    2026-02-23 and read live 2026-09-28) holds an RFC 2822 date, as it does in the
    live feed of 2026-09-28, that is the row's own time
    (``updated_scope`` ``row``; the list's time, if any, goes in ``raw_extra`` as
    ``list_updated``); otherwise the list's time is each row's update text
    (``updated_scope`` ``page``; none when the stamp is blank, as in 2026, where
    the page then shows the browser's clock). ``records`` must equal the rows
    read; ``<rows><records>0</records></rows>`` is the empty state (live on
    2026-09-26 and 2026-09-27, archived 2025-05-23; the page then says "No school
    closing or delay information has been reported at this time.").

``delaware-page``
    The page: it holds no list and names the feed in its grid's script. A
    :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED` listing that
    follows it.

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`.
"""

import re
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

from snowlight.sources.stations.body import decode
from snowlight.sources.stations.model import JsonScalar, Listing, ParsedRow, ShapeError
from snowlight.sources.stations.regional import (
    collapse,
    deferred,
    document,
    fragment_text,
    html_text,
    listing,
    row,
    scalar,
)

VARIANT = "delaware-portal-xml"
PAGE = "delaware-page"
COLUMNS = ("school", "action", "district", "note")
# The cells a list entry is made of: the name (school) and its details (action).
_LISTED = 2
_NOTE = COLUMNS.index("note")
_RFC2822 = re.compile(
    r"(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), )?\d{1,2} [A-Z][a-z]{2} \d{4} \d{2}:\d{2}(?::\d{2})?"
    r" (?:[+-]\d{4}|GMT|UT|[ECMP][SD]T)"
)
_HEAD = frozenset({"page", "total", "records", "lastModified", "timestamp", "userdata"})
_STAMPS = ("lastModified", "timestamp")
_FEED = re.compile(r"url:\s*'(/XML/PortalFeed)'")
_GRID = "jQuery('#list1').jqGrid("


def _cells(element: ElementTree.Element) -> list[str]:
    """Return a row's cells in order, as the grid reads them by position."""
    cells: list[str] = []
    for child in element:
        if child.tag != "cell":
            raise ShapeError(f"a PortalFeed row holds a <{child.tag}>")
        cells.append(fragment_text("".join(child.itertext())))
    if len(cells) < _LISTED:
        raise ShapeError(f"a PortalFeed row has {len(cells)} cells, fewer than {_LISTED}")
    return cells


def _is_date(text: str) -> bool:
    """Whether a cell is exactly an RFC 2822 date (as RSS pubDates are)."""
    if not _RFC2822.fullmatch(text):
        return False
    try:
        parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return False
    return True


def _feed(root: ElementTree.Element) -> Listing:
    records = root.findtext("records")
    if records is None or not records.strip().isdigit():
        raise ShapeError("the PortalFeed has no record count")
    stamp = next((text for tag in _STAMPS if (text := root.findtext(tag))), None)
    updated = collapse(stamp) if stamp and stamp.strip() else None
    rows: list[ParsedRow] = []
    skipped = 0
    for element in root:
        if element.tag in _HEAD:
            continue
        if element.tag != "row":
            raise ShapeError(f"the PortalFeed holds a <{element.tag}>")
        cells = _cells(element)
        extra: dict[str, JsonScalar] = {}
        for position, text in enumerate(cells[_LISTED:], start=_LISTED):
            key = COLUMNS[position] if position < len(COLUMNS) else f"cell_{position + 1}"
            extra[key] = scalar(text)
        if element.get("id") is not None:
            extra["id"] = element.get("id")
        note = cells[_NOTE] if len(cells) > _NOTE else ""
        when = updated
        if _is_date(note):
            when = note
            extra["updated_scope"] = "row"
            if updated:
                extra["list_updated"] = updated
        elif updated:
            extra["updated_scope"] = "page"
        found = row(cells[0], cells[1], when, extra)
        if found is None:
            skipped += 1
        else:
            rows.append(found)
    return listing(VARIANT, rows, skipped=skipped, declared=int(records.strip()))


def parse(body: bytes) -> Listing:
    """Read Delaware's PortalFeed XML or the page whose grid loads it."""
    text = html_text(body)
    if _GRID in text:
        feed = _FEED.search(text)
        if feed is None:
            raise ShapeError("Delaware's closings page names no PortalFeed")
        return deferred(PAGE, (feed.group(1),))
    try:
        root = ElementTree.fromstring(decode(body))  # noqa: S314 - a small state feed
    except ElementTree.ParseError as error:
        raise ShapeError(f"the PortalFeed does not parse: {error}") from error
    if root.tag != "rows":
        raise ShapeError(f"not a jqGrid feed: root <{root.tag}>")
    return _feed(root)


def slice_body(body: bytes) -> bytes:
    """Cut a page to its grid's feed address; the feed is kept whole (decoded)."""
    found = parse(body)
    if found.variant == PAGE:
        return document(f"<script>{_GRID}{{url: '{found.follows[0]}'}});</script>")
    return decode(body)
