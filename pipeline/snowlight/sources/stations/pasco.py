"""Pasco County Schools (Florida): the emergency banner on the district's homepage.

Pasco's site (``https://www.pasco.k12.fl.us/``) is its own, server-rendered, and
puts its urgent notice in a banner at the top of the homepage, marked in the
page's source by the comment ``<!-- Red emergency banner -->``. On storm days the
banner holds the closure: "All Schools and District Offices will now be closed to
the public, and all events and activities will be cancelled through Friday, October
11, 2024." (captured 2024-10-09, Hurricane Milton); "District Offices and Schools
will be CLOSED on Thursday, September 26, AND FRIDAY, September 27" (2024-09-26,
Helene). The adapter reads the part of the page between that comment and the next
comment (the banner slot).

Variants this adapter reads:

``pasco-emergency-banner``
    The page of 2024 on: the slot holds the banner's stylesheet (classes
    ``pcs_emergency_banner_red`` and ``pcs_emergency_banner_yellow``) and, when the
    district has a notice up, one ``div.pcs_emergency_banner_red`` or
    ``div.pcs_emergency_banner_yellow`` per notice. A slot with the stylesheet and
    no banner is an empty list (the live page on 2026-09-27).

``pasco-red-rectangle``
    The page of 2022 (in archived captures): the slot holds one red
    ``div.pcs_hp_rect`` with the notice ("All Pasco County schools and offices will
    reopen on Monday, October 3rd.", 2022-10-03, after Ian).

Each banner is one row: ``raw_name`` the page's title ("Pasco County Schools"; the
banner names no school, and the station's ``leaids`` say whose it is),
``raw_status`` the banner's text, no ``raw_updated_text``, and ``raw_extra``
``level`` (``red`` or ``yellow``) and ``links`` (the banner's link targets). A banner
with no words is a skipped row. A page without the comment, or whose slot holds
neither the stylesheet nor a banner, raises
:class:`~snowlight.sources.stations.model.ShapeError` (a redesign).
"""

import re

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

BANNER = "pasco-emergency-banner"
RECTANGLE = "pasco-red-rectangle"
MARK = "<!-- Red emergency banner -->"
_NEXT_COMMENT = re.compile(r"<!--")
_LEVELS = ("red", "yellow")


def _slot(text: str) -> str:
    start = text.find(MARK)
    if start < 0:
        raise ShapeError("no emergency banner slot: not Pasco's homepage as known")
    after = start + len(MARK)
    following = _NEXT_COMMENT.search(text, after)
    return text[after : following.start() if following is not None else len(text)]


def _row(name: str, banner: Node, level: str) -> ParsedRow | None:
    words = node_text(banner)
    if not words:
        return None
    links = [
        href for anchor in banner.css("a") if isinstance(href := anchor.attributes.get("href"), str)
    ]
    extra: dict[str, JsonScalar] = {"level": level, "links": " ".join(links) or None}
    return make_row(name, words, None, extra)


def parse(body: bytes) -> Listing:
    """Read Pasco County Schools' homepage: the emergency banners it shows."""
    text = html_text(body)
    slot = _slot(text)
    title = HTMLParser(text).css_first("title")
    name = collapse(title.text()) if title is not None else ""
    if not name:
        raise ShapeError("the page has no title to name the district by")
    fragment = HTMLParser(slot)
    found: list[tuple[Node, str]] = [
        (node, level)
        for level in _LEVELS
        for node in fragment.css(f"div.pcs_emergency_banner_{level}")
    ]
    if found or "pcs_emergency_banner_red" in slot:
        variant = BANNER
    else:
        found = [(node, "red") for node in fragment.css("div.pcs_hp_rect")]
        if not found:
            raise ShapeError("the emergency banner slot holds neither a banner nor its stylesheet")
        variant = RECTANGLE
    rows: list[ParsedRow] = []
    skipped = 0
    for node, level in found:
        row = _row(name, node, level)
        if row is None:
            skipped += 1
        else:
            rows.append(row)
    return make_listing(variant, rows, skipped=skipped)


def slice_body(body: bytes) -> bytes:
    """Keep the page title and the banner slot (the rest is navigation and news).

    The slice is a minimal document that reads exactly as the page does; a page
    without the slot slices to an empty document.
    """
    text = html_text(body)
    start = text.find(MARK)
    if start < 0:
        return document("")
    title = HTMLParser(text).css_first("title")
    head = title.html if title is not None and title.html is not None else ""
    return document(head + MARK + _slot(text) + "<!-- end of slot -->")
