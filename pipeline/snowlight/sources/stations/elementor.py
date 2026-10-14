"""District homepages built with WordPress and Elementor: the page's Alert widgets.

Before Alpine School District (Utah) moved its site to Apptegy in 2026, its
homepage was a WordPress page laid out with the Elementor page builder, and the
district posted its weather and closure notices on it as Elementor *Alert* widgets,
rendered into the page as served. The archive's capture of 2023-02-27 02:24 UTC
holds three (the first title's dash is an en dash in the page)::

    <div class="elementor-alert elementor-alert-info" role="alert">
      <span class="elementor-alert-title">ONLINE/DISTANCE LEARNING DAY - WEDNESDAY,
        FEBRUARY 22, 2023</span>
      <span class="elementor-alert-description">...</span>
    </div>

beside "Winter Weather" (the district's weather advisory for the Winter Storm
Warning) and "SCHOOLS OPEN ON REGULAR SCHEDULE FRIDAY, FEBRUARY 24, 2023"; its
captures of 2024 and 2025, the same page (the same Elementor page id, 32409) with
no Alert widget. The Apptegy adapter reads such a capture of its station's
homepage with :func:`parse_text`, after the forms it reads first.

Variant this module reads:

``elementor-alert-widgets``
    A WordPress page built with Elementor (its ``<body>`` has the ``elementor-page``
    class, and a ``generator`` meta names Elementor). Each Alert widget
    (``div.elementor-alert``) is one row; a page with none is an empty list (the
    district had no notice up: the widgets are placed on the page only while one
    is).

Each widget is one row: ``raw_name`` its title (``.elementor-alert-title``, the
notice's own title), ``raw_status`` its description (``.elementor-alert-description``),
no ``raw_updated_text`` (a widget shows no time), and ``raw_extra`` ``kind`` (the
widget's type: info, success, warning or danger). A widget with neither title nor
description is a skipped row. A page that is not an Elementor page raises
:class:`~snowlight.sources.stations.model.ShapeError`.
"""

import re
from html import escape

from selectolax.parser import HTMLParser, Node

from snowlight.sources.stations.gap_markup import (
    html_text,
    make_listing,
    make_row,
    node_text,
)
from snowlight.sources.stations.model import JsonScalar, Listing, ParsedRow, ShapeError

VARIANT = "elementor-alert-widgets"
_BODY_CLASS = re.compile(r"<body\b[^>]*\bclass=\"[^\"]*\belementor-page\b", re.IGNORECASE)
_GENERATOR = re.compile(r"<meta\s+name=\"generator\"\s+content=\"Elementor\b", re.IGNORECASE)
_KINDS = ("info", "success", "warning", "danger")


def holds_alert_widgets(text: str) -> bool:
    """Whether a page is a WordPress page built with Elementor (where Alert widgets go)."""
    return bool(_BODY_CLASS.search(text)) and bool(_GENERATOR.search(text))


def _kind(widget: Node) -> str | None:
    classes = str(widget.attributes.get("class") or "").split()
    for kind in _KINDS:
        if f"elementor-alert-{kind}" in classes:
            return kind
    return None


def _row(widget: Node) -> ParsedRow | None:
    title = node_text(widget.css_first(".elementor-alert-title"))
    description = node_text(widget.css_first(".elementor-alert-description"))
    extra: dict[str, JsonScalar] = {"kind": _kind(widget)}
    return make_row(title or description, description if title else "", None, extra)


def _widgets(tree: HTMLParser) -> list[Node]:
    return [
        node
        for node in tree.css("div.elementor-alert")
        if "elementor-alert" in str(node.attributes.get("class") or "").split()
    ]


def parse_text(text: str) -> Listing:
    """Read an Elementor homepage's Alert widgets (``text`` is the page)."""
    if not holds_alert_widgets(text):
        raise ShapeError("not a WordPress page built with Elementor")
    rows: list[ParsedRow] = []
    skipped = 0
    for widget in _widgets(HTMLParser(text)):
        row = _row(widget)
        if row is None:
            skipped += 1
        else:
            rows.append(row)
    return make_listing(VARIANT, rows, skipped=skipped)


def slice_body(body: bytes) -> bytes:
    """Keep the Elementor generator meta, the ``<body>`` classes and the Alert widgets.

    The slice is a minimal document that reads exactly as the page does; a page
    that is not an Elementor page slices to an empty document.
    """
    text = html_text(body)
    if not holds_alert_widgets(text):
        return b"<!DOCTYPE html><html><body></body></html>\n"
    tree = HTMLParser(text)
    generators = [
        str(node.attributes.get("content") or "")
        for node in tree.css('meta[name="generator"]')
        if str(node.attributes.get("content") or "").startswith("Elementor")
    ]
    body_node = tree.body
    classes = str(body_node.attributes.get("class") or "") if body_node is not None else ""
    widgets = "".join(node.html or "" for node in _widgets(tree))
    head = "".join(f'<meta name="generator" content="{escape(item)}">' for item in generators)
    return (
        f'<!DOCTYPE html><html><head>{head}</head><body class="{escape(classes)}">'
        f"{widgets}</body></html>\n"
    ).encode()
