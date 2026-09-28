"""Allen Media Broadcasting stations' closings: BLOX pages that frame a file on ``ftp2``.

Each Allen station's closings page (``https://www.{site}/weather/closings/``, a
TownNews BLOX page) frames a static file its closings system writes on the
station's ``ftp2`` host, and a banner script reads a counter on
``amb-feeds.s3.amazonaws.com``. Variants this adapter reads:

``allen-blox-page``
    The station page: ``<div class="tncms-block"><iframe
    src="https://ftp2.kwwl.com/closings.html" ...>``. A
    :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED` listing whose
    ``follows`` is the framed ``ftp2`` file.

``newsticker-html`` and ``closings-grid``
    The framed file as KWWL, WXOW, WQOW, WAOW, WKOW and WJRT write it (a NewsTicker
    export), read by :mod:`snowlight.sources.stations.newsticker`.

``allen-header-table``
    KIMT's file (``ftp2.kimt.com/closings.html``) since 2025 (captures of
    2025-03-27 to 2026-03-17): a table whose two header cells
    (``<th colspan="2">``) give the time ("September 27, 2026 12:55 am CDT") and,
    when nothing is listed, "THERE ARE CURRENTLY NO CLOSINGS OR CANCELLATIONS" (the
    empty state). With postings (the storm-day capture of 2026-03-16) a blank
    one-cell row comes first and a column heading row ("Location", "Status")
    follows the time; below it, one ``<tr>`` of two cells per organization, the
    name first and the status second. The time is each row's update text. A
    heading row of any other text raises, as it has not been seen.

``cgs-all-active``
    WKTV's file (``ftp2.wktv.com/CGSXML/All%20Active.html``, written by CGS
    Infographics Automation), and KIMT's file from 2020 to 2024 (captures of
    2020-03-27 to 2024-01-14, 61 to 98 entries each), read by
    :mod:`snowlight.sources.stations.cgs`: its empty state (WKTV) and its entries
    (KIMT), one ``table.tableborder`` each.

``allen-counter``
    The banner counter (``amb-feeds.s3.amazonaws.com/{CALL}_closings.json``):
    ``{"title", "station", "closingsURL", "numClosings"}``. A count, not a list:
    ``numClosings`` 0 is the empty state, any other count is
    :attr:`~snowlight.sources.stations.model.ListingState.COUNT_ONLY` (the
    ``closingsURL`` is the station page, which is not followed from here). A
    counter written blank (``"numClosings": ""``) says neither how many nor who:
    :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED`, with nothing
    to follow.

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`.
"""

import re
from collections.abc import Mapping

from selectolax.parser import HTMLParser

from snowlight.sources.stations import cgs, newsticker
from snowlight.sources.stations.body import decode
from snowlight.sources.stations.model import (
    JsonScalar,
    Listing,
    ListingState,
    ParsedRow,
    ShapeError,
)
from snowlight.sources.stations.regional import (
    collapse,
    deferred,
    document,
    html_text,
    json_body,
    listing,
    looks_like_json,
    node_text,
    row,
)

PAGE = "allen-blox-page"
HEADER_TABLE = "allen-header-table"
HEADER_COLUMNS = ("Location", "Status")
COUNTER = "allen-counter"
HEADER_EMPTY = "THERE ARE CURRENTLY NO CLOSINGS OR CANCELLATIONS"

_FTP2_FRAME = re.compile(
    r"<iframe\b[^>]*?\bsrc=\"(https?://ftp2\.[a-z0-9.-]+/[^\"]+)\"", re.IGNORECASE
)
_HEADER_MARK = re.compile(r"<th\b[^>]*\bcolspan=\"2\"[^>]*bgcolor='999999'", re.IGNORECASE)
_COUNTER_KEYS = frozenset({"title", "station", "closingsURL", "numClosings"})
_TWO = 2


def _counter(data: object) -> Listing:
    if not isinstance(data, Mapping) or set(data) != _COUNTER_KEYS:
        raise ShapeError("not an Allen closings counter")
    value = data["numClosings"]
    if value == "":
        # A counter written blank (WTVA's, 2025-01-26): it says neither how many nor who.
        return Listing(variant=COUNTER, state=ListingState.DEFERRED, rows=())
    text = (
        str(value).strip() if isinstance(value, str | int) and not isinstance(value, bool) else ""
    )
    if not text.isdigit():
        raise ShapeError(f"numClosings is not a count: {value!r}")
    count = int(text)
    return Listing(
        variant=COUNTER,
        state=ListingState.COUNT_ONLY if count else ListingState.EMPTY,
        rows=(),
        declared_count=count,
    )


def _header_table(text: str) -> Listing:
    tree = HTMLParser(text)
    headers = [node_text(cell) for cell in tree.css("th")]
    if not headers or not headers[0]:
        raise ShapeError("a closings header table without its time")
    updated = headers[0]
    rows: list[ParsedRow] = []
    empty = HEADER_EMPTY in headers[1:]
    skipped = 0
    for tr in tree.css("tr"):
        heads, cells = tr.css("th"), tr.css("td")
        if heads and not cells:
            labels = [node_text(head) for head in heads]
            if labels not in ([updated], [HEADER_EMPTY], list(HEADER_COLUMNS)):
                raise ShapeError(f"a closings header table heading not seen before: {labels}")
            continue
        if len(cells) == 1 and not node_text(cells[0]):
            continue
        if len(cells) != _TWO:
            raise ShapeError(f"a closings header table row has {len(cells)} cells, not 2")
        extra: dict[str, JsonScalar] = {"updated_scope": "page"}
        found = row(node_text(cells[0]), node_text(cells[1]), updated, extra)
        if found is None:
            skipped += 1
        else:
            rows.append(found)
    if rows and empty:
        raise ShapeError("a closings header table lists rows and says there are none")
    if not rows and not empty:
        raise ShapeError("a closings header table with no rows and no no-closings line")
    return listing(HEADER_TABLE, rows, skipped=skipped)


def read_header_table(text: str) -> Listing | None:
    """Read a header-table closings file (KIMT's, and KATV's earlier one); None for another shape.

    Raises:
        ShapeError: the text has the table's heading mark but does not read cleanly.
    """
    if _HEADER_MARK.search(text) is None:
        return None
    return _header_table(text)


def parse(body: bytes) -> Listing:
    """Read an Allen station page, the file it frames, or the banner counter."""
    if looks_like_json(body):
        return _counter(json_body(body))
    found = newsticker.read_file(body)
    if found is not None:
        return found
    text = html_text(body)
    cgs_page = cgs.read_page(text)
    if cgs_page is not None:
        return cgs_page
    header = read_header_table(text)
    if header is not None:
        return header
    frame = _FTP2_FRAME.search(text)
    if frame is not None:
        return deferred(PAGE, (collapse(frame.group(1)),))
    raise ShapeError("not an Allen closings page, list file or counter")


def slice_body(body: bytes) -> bytes:
    """Cut a body to what the adapter reads: a page keeps its ``ftp2`` frame; files stay whole."""
    found = parse(body)
    if found.variant == PAGE:
        return document(f'<iframe src="{found.follows[0]}"></iframe>')
    return decode(body)
