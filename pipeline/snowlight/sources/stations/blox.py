"""TownNews BLOX sites' closings: the closings application's files and the pages that show them.

Several independently owned stations run their sites on TownNews BLOX and show
closings with BLOX's own tools. Variants this adapter reads:

``blox-sc-xml``
    The closings application's XML (KOAM: ``/app/closings/KOAM-closingsC.xml``):
    ``<File Time="02/10/2026 01:02am">`` holding one ``<Closing>`` per
    organization. The page's script (read 2026-09-27) shows ``Name1``,
    ``EntityType``, ``Status`` and ``UpdateTime``: ``Name1`` is the name,
    ``Status`` the status and ``UpdateTime`` the update text (else the file's
    ``Time``); every other child element's text goes in ``raw_extra`` under its
    tag (KXLY's page shows ``Status2`` under ``Status``: it is kept there, as
    ``raw_extra["Status2"]``). A ``File`` with no ``Closing`` is the empty state.
    (No capture of KOAM's or KXLY's file with rows exists; the same generator's
    files that Gray stations framed, in part 1's fixtures, hold rows (WNEM's and
    WSMV's) and this adapter reads them to the same names.)

``blox-newsticker-xml``
    NewsTicker's XML export at ``/app/closings/closings.xml``, the other form a BLOX
    site's closings application serves (Gray's KAKE served it there; part 1's
    fixtures hold KAKE's and WGGB's with 251 and 228 rows, which this adapter reads
    to the same names): ``<DATA>`` with ``NUM_CLOSINGS`` and one ``RECORD`` per
    organization; ``FORCED_ORGANIZATION_NAME`` is the name, ``FORCED_STATUS_NAME``
    the status, ``UPDATED`` the update text, and every other field goes in
    ``raw_extra`` in lower case. ``NUM_CLOSINGS`` must equal the records read.
    (KXLY's page reads ``/app/closings/closings.xml``; its one capture, of
    2023-05-23, is the ``File`` form above, empty.)

``blox-cgs-xml``
    The XML export of CGS Mercury Publisher (Callaway GraphicSoftware), which KOAM
    served at ``/app/closings/closings.xml`` in 2023 and 2024:
    ``<WEBCLOSE_XML>`` with ``RecordCount`` and ``pubDate``, then one
    ``<Organization>`` per posting, as the capture of 2023-02-01 18:18 UTC shows
    (24 of them)::

        <Organization><Category>BUSINESS</Category><Org>BEARSKIN HEALTH CLINIC</Org>
          <Org_ID>5720</Org_ID><Status>Closed Monday</Status><Status2 />
          <Composite>BUSINESS: BEARSKIN HEALTH CLINIC - Closed Monday</Composite>
          <Entered_ON>1/30/2023 7:24:21 AM</Entered_ON></Organization>

    ``Org`` is the name, ``Status`` the status and ``Entered_ON`` the update text
    (else the file's ``pubDate``); every other field goes in ``raw_extra`` under its
    tag. ``RecordCount`` must equal the postings read.

``newsticker-html``
    The HTML export at ``/app/closings/closings.html`` (WRCB), read by
    :mod:`snowlight.sources.stations.newsticker`.

``blox-script-page`` and ``blox-frame-page``
    A station page whose script requests the closings XML
    (``xmlhttp.open("GET", "/app/closings/KOAM-closingsC.xml", true)``) or which
    frames the HTML export (``<iframe src=".../app/closings/closings.html">``): a
    :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED` listing that
    follows the file.

``blox-closings-cards``
    Coast TV's page (``/closings/``), where each closing is a BLOX article card in
    the closings block (``div.tncms-block.closings``)::

        <article class="... card summary ... tnt-section-closings">
          <h3 class="tnt-headline"><a href="/closings/atlantic-umc-ocean-city/article_....html">
            ATLANTIC UMC OCEAN CITY</a></h3>
          <p class="tnt-summary">Closed Today and Tomorrow</p></article>

    (seen populated live, 2026-09-26 and 2026-09-27). The headline is the name,
    the summary the status, and the link ``raw_extra["link"]`` (the block's
    ``<template>`` for cards added in the browser is not a card). A closings block
    with no card is the empty state.

``blox-weather-closings``
    The weather closings tables of the Sinclair partner stations' BLOX pages
    (WRSP, WICS, KHQA): the server writes rows into hidden
    ``table.weather-closings`` tables and a script copies them into
    ``#weatherClosingsCopy``, writing "There are no closings at this time" when
    there are none. Every table with an empty body is the empty state. The
    stations' pages took this form in February 2026. The archive holds no capture
    of it with rows: every capture of winter 2026 was read (WRSP's of 2026-02-06 and
    the two largest, of 2026-03-13; WICS's and KHQA's of 2026-02-26), and each
    table's body is empty; the rest are of May to August. The tables' head names no
    column (one ``th`` spanning five), so a table with rows raises
    :class:`~snowlight.sources.stations.model.ShapeError` rather than being read by
    guesswork at its columns.

``heritage-bti-table``
    KXLY's page before BLOX (captures of 2021 and 2022, on TownNews's GTxcel
    "RAYOS" WordPress theme): the schoolclosings.org table the 9&10 page also
    carried, written into the page, or its "No active school closings at this
    time." line, read by :func:`snowlight.sources.stations.heritage.read_bti`
    (3 rows on 2022-01-06 and 2022-11-30).

``sinclair-next-page``, ``sinclair-frame-page`` and ``sinclair-facade-page``
    The same pages' earlier form, while Sinclair ran them (captures of January 2025
    to January 2026): a Sinclair page framing a NewsTicker file under
    ``/resources/ftptransfer/`` (``wics/closings/closings.html`` for WRSP and WICS,
    ``khqa/closings/closings01.htm`` for KHQA), read by
    :func:`snowlight.sources.stations.sinclair.read_page`.
    :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED`, following the file.

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`.
"""

import re
from xml.etree import ElementTree

from selectolax.parser import HTMLParser, Node

from snowlight.sources.stations import heritage, newsticker, sinclair
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

SC_XML = "blox-sc-xml"
NT_XML = "blox-newsticker-xml"
CGS_XML = "blox-cgs-xml"
SCRIPT_PAGE = "blox-script-page"
FRAME_PAGE = "blox-frame-page"
CARDS = "blox-closings-cards"
WEATHER_TABLES = "blox-weather-closings"

_SCRIPT_FILE = re.compile(
    r"xmlhttp\.open\(\s*\"GET\"\s*,\s*\"(/app/closings/[^\"?]+\.xml)", re.IGNORECASE
)
_NAME1 = re.compile(r"[\".]Name1\b")
_SCRIPT_BLOCK = re.compile(r"<script\b[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL)
_FRAME_FILE = re.compile(
    r"<iframe\b[^>]*?\bsrc=\"((?:https?:)?(?://[^/\"]+)?/app/closings/[^\"]+\.html?)\"",
    re.IGNORECASE,
)
_NT_HEAD = frozenset({"SOURCE", "EXPORT_TYPE", "NUM_CLOSINGS", "RUN_DATE", "RUN_EPOCH"})
_NT_ROW = frozenset({"FORCED_ORGANIZATION_NAME", "FORCED_STATUS_NAME", "UPDATED"})
_CGS_HEAD = frozenset(
    {
        "Source",
        "Title",
        "Data",
        "URL",
        "Copyright",
        "Company",
        "Version",
        "Output",
        "RecordCount",
        "pubDate",
    }
)
_CGS_ROW = frozenset({"Org", "Status", "Entered_ON"})


def _xml(body: bytes) -> ElementTree.Element:
    """Parse a small XML list file (no external entities are fetched by this parser)."""
    try:
        return ElementTree.fromstring(decode(body))  # noqa: S314 - small files, see docstring
    except ElementTree.ParseError as error:
        raise ShapeError(f"the closings XML does not parse: {error}") from error


def _child(element: ElementTree.Element, tag: str) -> str | None:
    found = element.find(tag)
    return None if found is None else collapse("".join(found.itertext()))


def _fields(
    element: ElementTree.Element, skip: frozenset[str], lower: bool
) -> dict[str, JsonScalar]:
    extra: dict[str, JsonScalar] = {}
    for child in element:
        if child.tag in skip:
            continue
        if len(child):
            raise ShapeError(f"a closings XML field {child.tag!r} is not plain text")
        extra[child.tag.lower() if lower else child.tag] = collapse(child.text or "")
    return extra


def _sc(root: ElementTree.Element) -> Listing:
    stamp = root.get("Time")
    rows: list[ParsedRow] = []
    skipped = 0
    for closing in root:
        if closing.tag != "Closing":
            raise ShapeError(f"a closings file holds a <{closing.tag}>, not a <Closing>")
        status = _child(closing, "Status")
        if status is None:
            raise ShapeError("a <Closing> has no Status")
        updated = _child(closing, "UpdateTime") or stamp
        extra = _fields(closing, frozenset({"Name1", "Status", "UpdateTime"}), lower=False)
        if not _child(closing, "UpdateTime") and stamp:
            extra["updated_scope"] = "page"
        found = row(_child(closing, "Name1") or "", status, updated, extra)
        if found is None:
            skipped += 1
        else:
            rows.append(found)
    if not rows and not skipped and "".join(root.itertext()).strip():
        raise ShapeError("a closings file with no <Closing> holds text")
    return listing(SC_XML, rows, skipped=skipped)


def _newsticker_xml(root: ElementTree.Element) -> Listing:
    count = _child(root, "NUM_CLOSINGS")
    if count is None or not count.isdigit():
        raise ShapeError("a NewsTicker XML export has no NUM_CLOSINGS")
    rows: list[ParsedRow] = []
    skipped = 0
    for record in root:
        if record.tag in _NT_HEAD:
            continue
        if record.tag != "RECORD":
            raise ShapeError(f"a NewsTicker XML export holds a <{record.tag}>")
        status = _child(record, "FORCED_STATUS_NAME")
        if status is None:
            raise ShapeError("a NewsTicker XML record has no FORCED_STATUS_NAME")
        found = row(
            _child(record, "FORCED_ORGANIZATION_NAME") or "",
            status,
            _child(record, "UPDATED"),
            _fields(record, _NT_ROW, lower=True),
        )
        if found is None:
            skipped += 1
        else:
            rows.append(found)
    return listing(NT_XML, rows, skipped=skipped, declared=int(count))


def _cgs_xml(root: ElementTree.Element) -> Listing:
    count = _child(root, "RecordCount")
    if count is None or not count.isdigit():
        raise ShapeError("a CGS Mercury export has no RecordCount")
    published = _child(root, "pubDate") or None
    rows: list[ParsedRow] = []
    skipped = 0
    for element in root:
        if element.tag in _CGS_HEAD:
            continue
        if element.tag != "Organization":
            raise ShapeError(f"a CGS Mercury export holds a <{element.tag}>")
        status = _child(element, "Status")
        if status is None:
            raise ShapeError("a CGS Mercury posting has no Status")
        entered = _child(element, "Entered_ON") or None
        extra = _fields(element, _CGS_ROW, lower=False)
        if entered is None and published:
            extra["updated_scope"] = "page"
        found = row(_child(element, "Org") or "", status, entered or published, extra)
        if found is None:
            skipped += 1
        else:
            rows.append(found)
    return listing(CGS_XML, rows, skipped=skipped, declared=int(count))


def _list_script(text: str) -> str | None:
    """Return the XML file the page's closings list script requests, if it has one.

    A BLOX page may request two files: its list block's script reads each
    ``<Closing>``'s ``Name1`` into the table, while an alert banner's script only
    counts another file's closings. The list is the file the ``Name1`` script reads.
    """
    for script in _SCRIPT_BLOCK.finditer(text):
        found = _SCRIPT_FILE.search(script.group(1))
        if found is not None and _NAME1.search(script.group(1)):
            return found.group(1)
    return None


def _in_template(node: Node) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.tag == "template":
            return True
        parent = parent.parent
    return False


def _cards(block: Node) -> Listing:
    rows: list[ParsedRow] = []
    skipped = 0
    for card in block.css("article.card"):
        if _in_template(card):
            continue  # the block's client-side template for cards it adds later
        link = card.css_first("h3.tnt-headline a") or card.css_first(".tnt-headline a")
        if link is None:
            raise ShapeError("a closings card has no headline link")
        summary = card.css_first("p.tnt-summary")
        extra: dict[str, JsonScalar] = {}
        href = link.attributes.get("href")
        if href:
            extra["link"] = href
        found = row(node_text(link), node_text(summary), None, extra)
        if found is None:
            skipped += 1
        else:
            rows.append(found)
    return listing(CARDS, rows, skipped=skipped)


def _weather_tables(tables: list[Node]) -> Listing:
    if any(table.css("tbody tr") for table in tables):
        raise ShapeError(
            "a BLOX weather closings table holds rows; their columns have not been seen, "
            "so they are not read"
        )
    return listing(WEATHER_TABLES, [])


def _xml_file(body: bytes) -> Listing | None:
    """Read a closings XML file, or None when the body is not XML."""
    head = decode(body).removeprefix(b"\xef\xbb\xbf").lstrip()
    if not head.startswith((b"<?xml", b"<File")):
        return None
    root = _xml(body)
    if root.tag == "File":
        return _sc(root)
    if root.tag == "DATA":
        return _newsticker_xml(root)
    if root.tag == "WEBCLOSE_XML":
        return _cgs_xml(root)
    raise ShapeError(f"a closings XML file whose root is <{root.tag}>")


def _page(text: str) -> Listing:
    """Read a BLOX page: follow the file it loads or frames, or read its own list."""
    script = _list_script(text)
    if script is not None:
        return deferred(SCRIPT_PAGE, (script,))
    frame = _FRAME_FILE.search(text)
    if frame is not None:
        return deferred(FRAME_PAGE, (frame.group(1),))
    tree = HTMLParser(text)
    block = tree.css_first("div.tncms-block.closings")
    if block is not None:
        return _cards(block)
    tables = tree.css("table.weather-closings")
    if tables:
        return _weather_tables(tables)
    earlier = sinclair.read_page(text)
    if earlier is not None:
        return earlier
    before_blox = heritage.read_bti(text)
    if before_blox is not None:
        return before_blox
    raise ShapeError("not a BLOX closings page or file")


def parse(body: bytes) -> Listing:
    """Read a BLOX closings file or a BLOX page that shows or loads one."""
    found = _xml_file(body) or newsticker.read_file(body)
    return found if found is not None else _page(html_text(body))


def _kept_markup(found: Listing, text: str) -> str | None:
    """The markup a page's slice keeps, or None for a file (kept whole)."""
    if found.variant == heritage.TABLE:
        return heritage.bti_markup(text)
    if found.variant == SCRIPT_PAGE:
        line = f'xmlhttp.open("GET", "{found.follows[0]}", true); getNodeValue(x[i], "Name1");'
        return f"<script>{line}</script>"
    if found.variant == FRAME_PAGE:
        return f'<iframe src="{found.follows[0]}"></iframe>'
    tree = HTMLParser(text)
    if found.variant == CARDS:
        block = tree.css_first("div.tncms-block.closings")
        return (block.html or "") if block is not None else ""
    if found.variant == WEATHER_TABLES:
        return "".join(table.html or "" for table in tree.css("table.weather-closings"))
    return None


def slice_body(body: bytes) -> bytes:
    """Cut a body to what the adapter reads; files stay whole."""
    found = parse(body)
    if found.variant.startswith("sinclair-"):
        return sinclair.slice_body(body)
    kept = _kept_markup(found, html_text(body))
    return decode(body) if kept is None else document(kept)
