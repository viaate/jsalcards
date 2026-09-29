"""Blackboard Web Community Manager (Schoolwires) district homepages: the important announcements.

Before several Florida county districts moved their sites to Apptegy or ParentSquare
Smart Sites, their homepages were Blackboard Web Community Manager ("Schoolwires")
sites, and the district's urgent notice stood at the top of the homepage in the
"Important Announcement" app. Archived captures of those homepages hold it as
served, for example Manatee's on 2024-10-09 (Hurricane Milton): "All SDMC schools
are closed to students through Friday 10/9/24. All school activities, including
athletics, are canceled." The Apptegy, Smart Sites and Finalsite adapters read such a
capture of their station's homepage with :func:`parse_text` (Web Community Manager is a
Finalsite product: Palm Beach's page of 2024-10-10 reads "Copyright © 2024 Finalsite").

Variant this module reads:

``schoolwires-important-announcements``
    ``<div class="cs-important-announcements-outer" data-pmi-id data-mi-id>`` holding
    ``ul.cs-important-announcements-list`` with one ``li.cs-important-announcement
    [data-flex-id]`` per announcement shown, its words in
    ``div.cs-important-announcement-text``. A list with no item is an empty list (the
    district had no announcement up).

Each announcement is one row: ``raw_name`` the site's name (the page title before
" / ", "School District of Manatee County"; the announcement names no school, and
the station's ``leaids`` say whose it is), ``raw_status`` the announcement's text,
no ``raw_updated_text`` (the app shows no time), and ``raw_extra`` ``flex_id``,
``module_id`` (``data-pmi-id``) and ``links`` (the announcement's link targets). An
announcement with no words is a skipped row. A page without the region raises
:class:`~snowlight.sources.stations.model.ShapeError` (it is not this format, or the
district did not use the app), and so does a region whose items lack
``data-flex-id``.
"""

from html import escape

from selectolax.parser import HTMLParser

from snowlight.sources.stations.gap_markup import (
    collapse,
    document,
    html_text,
    make_listing,
    make_row,
    node_text,
)
from snowlight.sources.stations.model import JsonScalar, Listing, ParsedRow, ShapeError

VARIANT = "schoolwires-important-announcements"
MARKER = "cs-important-announcements-outer"


def holds_announcements(text: str) -> bool:
    """Whether a page has the Important Announcement app's region."""
    return MARKER in text


def _site_name(tree: HTMLParser) -> str:
    title = tree.css_first("title")
    name = collapse(title.text()).split(" / ")[0] if title is not None else ""
    if not name:
        raise ShapeError("the Schoolwires page has no title to name the district by")
    return name


def parse_text(text: str) -> Listing:
    """Read a Schoolwires homepage's important announcements (``text`` is the page)."""
    tree = HTMLParser(text)
    outer = tree.css_first(f"div.{MARKER}")
    if outer is None:
        raise ShapeError("no important-announcements region: not a Schoolwires homepage")
    listing = outer.css_first("ul.cs-important-announcements-list")
    if listing is None:
        raise ShapeError("the important-announcements region has no list")
    name = _site_name(tree)
    module = outer.attributes.get("data-pmi-id")
    rows: list[ParsedRow] = []
    skipped = 0
    for item in listing.css("li.cs-important-announcement"):
        flex = item.attributes.get("data-flex-id")
        if not isinstance(flex, str) or not flex.strip():
            raise ShapeError("an important announcement has no data-flex-id")
        body = item.css_first("div.cs-important-announcement-text")
        words = node_text(body) if body is not None else ""
        if not words:
            skipped += 1
            continue
        links = [
            href
            for anchor in (body.css("a") if body is not None else [])
            if isinstance(href := anchor.attributes.get("href"), str) and href
        ]
        extra: dict[str, JsonScalar] = {
            "flex_id": collapse(flex),
            "module_id": collapse(module) if isinstance(module, str) else None,
            "links": " ".join(links) or None,
        }
        row = make_row(name, words, None, extra)
        if row is None:  # pragma: no cover - the name was checked above
            skipped += 1
        else:
            rows.append(row)
    return make_listing(VARIANT, rows, skipped=skipped)


def slice_body(body: bytes) -> bytes:
    """Keep the page title and the announcements region (the rest is markup and scripts).

    The slice is a minimal document that reads exactly as the page does; a page
    without the region slices to an empty document.
    """
    tree = HTMLParser(html_text(body))
    outer = tree.css_first(f"div.{MARKER}")
    title = tree.css_first("title")
    if outer is None:
        return document("")
    for junk in outer.css("style, script"):
        junk.decompose()
    head = f"<title>{escape(title.text(), quote=False)}</title>" if title is not None else ""
    return document(head + outer.html if outer.html is not None else head)
