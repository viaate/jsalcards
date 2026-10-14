"""Northside Independent School District (San Antonio): the homepage's notices block.

Northside ISD, San Antonio's largest district (127 schools in Bexar County), runs its
own Drupal site. At the top of its homepage, above the navigation, stands a Drupal
view named ``notices`` (``div.view-notices``), rendered on the server: empty on a
quiet day (read 2026-09-29), and holding one row per notice when the district posts
one. The archive's captures of the homepage show what it posts there: the closures
of the January 2025 snow ("Northside ISD is canceling classes for Tuesday, Jan. 21",
captured 2025-01-20 23:46 UTC) and of the January 2026 cold ("all District offices
and schools will be closed on Monday, Jan. 26", captured 2026-01-25 23:10 UTC), as
well as holidays ("Schools and offices are closed for Martin Luther King, Jr. Day").

Variant this adapter reads:

``nisd-notices``
    The homepage's ``div.view-notices`` with its ``.views-row`` rows, each a
    ``div.notice--<level>`` (``alert`` or ``info``) whose ``[role=alert]`` column
    holds the notice. A view with no row (no ``.view-content``) is an empty list.

Each notice is one row: ``raw_name`` the district's name (the page title before
" | "; a notice names no school, and the station's ``leaids`` say whose it is),
``raw_status`` the notice's words (cut at the status limit), no ``raw_updated_text``
(a notice shows a date only when the district typed one), and ``raw_extra``
``level`` (from the ``notice--`` class), ``icon`` (its Font Awesome icon, such as
``fa-snowflake``) and ``link`` (the notice's first link). A notice with no words is
a skipped row. A page with no notices view, or with no title to name the district
by, raises :class:`~snowlight.sources.stations.model.ShapeError`.
"""

from html import escape

from selectolax.parser import HTMLParser, Node

from snowlight.sources.stations.gap_markup import (
    clip,
    collapse,
    document,
    html_text,
    make_listing,
    make_row,
    node_text,
)
from snowlight.sources.stations.model import MAX_STATUS, JsonScalar, Listing, ParsedRow, ShapeError

VARIANT = "nisd-notices"
VIEW = "div.view-notices"


def _district(tree: HTMLParser) -> str:
    title = tree.css_first("title")
    name = collapse(title.text()).split(" | ")[0] if title is not None else ""
    if not name:
        raise ShapeError("the homepage has no title to name the district by")
    return name


def _classes(node: Node, prefix: str) -> list[str]:
    return [c for c in str(node.attributes.get("class") or "").split() if c.startswith(prefix)]


def _row(item: Node, district: str) -> ParsedRow | None:
    notice = item.css_first('[class*="notice--"]')
    body = item.css_first('[role="alert"]') or item
    words = node_text(body)
    if not words:
        return None
    levels = _classes(notice, "notice--") if notice is not None else []
    icon = item.css_first("i")
    icons = [c for c in _classes(icon, "fa-") if c not in {"fa-2x", "fa-pull-left"}] if icon else []
    anchor = body.css_first("a[href]")
    href = anchor.attributes.get("href") if anchor is not None else None
    extra: dict[str, JsonScalar] = {
        "level": levels[0].removeprefix("notice--") if levels else None,
        "icon": icons[0] if icons else None,
        "link": collapse(href) or None if isinstance(href, str) else None,
    }
    return make_row(district, clip(words, MAX_STATUS), None, extra)


def parse(body: bytes) -> Listing:
    """Read Northside ISD's homepage: the notices block's rows."""
    tree = HTMLParser(html_text(body))
    view = tree.css_first(VIEW)
    if view is None:
        raise ShapeError("no notices view (div.view-notices): not Northside ISD's homepage")
    district = _district(tree)
    rows: list[ParsedRow] = []
    skipped = 0
    for item in view.css(".views-row"):
        row = _row(item, district)
        if row is None:
            skipped += 1
        else:
            rows.append(row)
    return make_listing(VARIANT, rows, skipped=skipped)


def slice_body(body: bytes) -> bytes:
    """Keep the page title and the notices view (for fixtures).

    The slice is a minimal document that reads exactly as the page does; a page
    without the view slices to its title alone (which the adapter refuses).
    """
    tree = HTMLParser(html_text(body))
    title = tree.css_first("title")
    head = f"<title>{escape(collapse(title.text()), quote=False)}</title>" if title else ""
    view = tree.css_first(VIEW)
    if view is None:
        return document(head)
    for junk in view.css("script, style"):
        junk.decompose()
    return document(head + (view.html or ""))
