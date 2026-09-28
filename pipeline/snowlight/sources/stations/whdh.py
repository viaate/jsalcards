"""WHDH 7News (Boston) storm closings and delays: a server-rendered page.

The page (``https://whdh.com/storm-closings-delays/``; the older
``/school-closings/`` redirects here) writes its list in a
``div.wp-block-school-closings`` block. Variant this adapter reads:

``whdh-closings-block``
    With something listed, one ``article.closure-notice`` per organization (seen
    populated by the first-hand check of 2026-09-26)::

        <article class="closure-notice">
          <div class="closure-header">Colleges/Universities - Updated: 2026-09-25 18:00:09</div>
          <h3 class="entry-title">Quincy College</h3>
          <div class="current-status">Closed Today</div>
          <div class="address"><span>...</span></div>
          <div class="status-expiration">2026-09-26 22:00:00</div>
        </article>

    (the dash in the header is an en dash). The title is the name and
    ``current-status`` the status; the header's text after "Updated:" is the
    update text and before it the category (``raw_extra["category"]``); the
    address and the expiration go in ``raw_extra`` (``address``, ``expiration``).
    With nothing listed the block holds "There are currently no school closings
    listed." and ``div.last-updated`` ("Updated: 2026-09-27 05:45:01", live
    2026-09-27): the empty state.

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`.
"""

import re

from selectolax.parser import HTMLParser, Node

from snowlight.sources.stations.model import JsonScalar, Listing, ParsedRow, ShapeError
from snowlight.sources.stations.regional import (
    collapse,
    document,
    html_text,
    listing,
    node_text,
    row,
)

VARIANT = "whdh-closings-block"
EMPTY_SENTENCE = "There are currently no school closings listed."
_UPDATED = re.compile(r"^(?P<category>.*?)\s*[\u2013-]\s*Updated:\s*(?P<when>.+)$")


def _notice(article: Node) -> ParsedRow | None:
    title = article.css_first(".entry-title")
    status = article.css_first(".current-status")
    if title is None or status is None:
        raise ShapeError("a closure notice without its title or status")
    header = node_text(article.css_first(".closure-header"))
    parts = _UPDATED.match(header)
    extra: dict[str, JsonScalar] = {}
    updated = None
    if parts is not None:
        updated = collapse(parts.group("when"))
        if parts.group("category"):
            extra["category"] = collapse(parts.group("category"))
    elif header:
        extra["category"] = header
    address = node_text(article.css_first(".address"))
    if address:
        extra["address"] = address
    expiration = node_text(article.css_first(".status-expiration"))
    if expiration:
        extra["expiration"] = expiration
    return row(node_text(title), node_text(status), updated, extra)


def parse(body: bytes) -> Listing:
    """Read WHDH's storm closings page."""
    tree = HTMLParser(html_text(body))
    block = tree.css_first("div.wp-block-school-closings")
    if block is None:
        raise ShapeError("not WHDH's closings page (no school-closings block)")
    notices = block.css("article.closure-notice")
    rows: list[ParsedRow] = []
    skipped = 0
    for article in notices:
        found = _notice(article)
        if found is None:
            skipped += 1
        else:
            rows.append(found)
    empty = EMPTY_SENTENCE in node_text(block)
    if notices and empty:
        raise ShapeError("WHDH's block lists notices and says none are listed")
    if not notices and not empty:
        raise ShapeError("WHDH's block holds no notice and no no-closings sentence")
    return listing(VARIANT, rows, skipped=skipped)


def slice_body(body: bytes) -> bytes:
    """Cut the page to its closings block."""
    parse(body)
    block = HTMLParser(html_text(body)).css_first("div.wp-block-school-closings")
    return document((block.html or "") if block is not None else "")
