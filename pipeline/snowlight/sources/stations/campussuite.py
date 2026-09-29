"""Campus Suite district homepages: the alert banner (a district's site before its present CMS).

Before some districts moved their sites to Apptegy or Smart Sites, their homepages
were Campus Suite sites (``window.CAMPUSSUITE``, assets on campussuite.com), and the
district's urgent notice stood at the top of every page in the site's alert banner
widget. Archived captures of those homepages hold it as served, for example Hardin
(MT) on 2022-12-21: "School Closure Wednesday, Dec. 21st 2022" ("Due to the potential
of extreme cold temperatures, snowfall and frigid wind chills that could easily exceed
-30 degrees below zero ..."). The Apptegy and Smart Sites adapters read such a capture
of their station's homepage with :func:`parse_text`.

Variant this module reads:

``campussuite-alert-banner``
    The widget ``<div data-cms-widget="widgets/AlertBanner/AlertBanner">``. With an
    alert up it holds ``div.cs-alert-banner`` with one ``div.cs-alert-banner__item``
    per alert (its class names the level, ``cs-alert-banner__item--urgent``), whose
    ``p.cs-alert-banner__msg`` link (``/alert/<id>/<slug>``) carries the headline,
    and ``div.cs-alert-banner__modals`` with one ``div.cs-alert-modal`` per alert
    (``data-popup="<id>-<time>"``) holding the headline (``h1.modal-title``) and the
    message's opening words (``<p>``). With none up the widget is empty (Hardin's
    homepage of 2023-03-27, Hernando's of 2023 and 2024): an empty list.

Each alert is one row: ``raw_name`` the site's name (the page title before " | ",
"Hardin School District 17H&1"; the alert names no school, and the station's
``leaids`` say whose it is), ``raw_status`` the headline and, when the alert's dialog
is in the page, the message's words after it, no ``raw_updated_text`` (the widget shows
no time), and ``raw_extra`` ``alert_id``, ``level`` and ``link``. An alert with no
words is a skipped row. A page without the widget raises
:class:`~snowlight.sources.stations.model.ShapeError` (it is not this format).
"""

import re
from html import escape

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

VARIANT = "campussuite-alert-banner"
MARKER = 'data-cms-widget="widgets/AlertBanner/AlertBanner"'
_ALERT_ID = re.compile(r"/alert/(\d+)(?:/|$)")
_LEVEL = re.compile(r"\bcs-alert-banner__item--([a-z-]+)\b")


def holds_alert_banner(text: str) -> bool:
    """Whether a page has Campus Suite's alert banner widget."""
    return MARKER in text


def _widget(tree: HTMLParser) -> Node:
    widget = tree.css_first('div[data-cms-widget="widgets/AlertBanner/AlertBanner"]')
    if widget is None:
        raise ShapeError("no alert banner widget: not a Campus Suite page")
    return widget


def _site_name(tree: HTMLParser) -> str:
    title = tree.css_first("title")
    name = collapse(title.text()).split(" | ")[0] if title is not None else ""
    if not name:
        raise ShapeError("the Campus Suite page has no title to name the district by")
    return name


def _messages(widget: Node) -> dict[str, str]:
    """Each alert's dialog words (after its headline), by alert id."""
    found: dict[str, str] = {}
    for modal in widget.css("div.cs-alert-modal"):
        popup = modal.attributes.get("data-popup")
        if not isinstance(popup, str) or not popup.split("-")[0].isdigit():
            continue
        words = " ".join(node_text(p) for p in modal.css("div.modal-body p"))
        found[popup.split("-")[0]] = collapse(words)
    return found


def parse_text(text: str) -> Listing:
    """Read a Campus Suite homepage's alert banner (``text`` is the page)."""
    tree = HTMLParser(text)
    widget = _widget(tree)
    name = _site_name(tree)
    messages = _messages(widget)
    rows: list[ParsedRow] = []
    skipped = 0
    for item in widget.css("div.cs-alert-banner__item"):
        anchor = item.css_first("p.cs-alert-banner__msg a")
        href = anchor.attributes.get("href") if anchor is not None else None
        link = href if isinstance(href, str) and href else None
        found = _ALERT_ID.search(link or "")
        alert_id = found.group(1) if found else None
        headline = node_text(item.css_first("p.cs-alert-banner__msg"))
        message = messages.get(alert_id or "", "")
        status = f"{headline}: {message}" if headline and message else headline or message
        if not status:
            skipped += 1
            continue
        classes = item.attributes.get("class")
        level = _LEVEL.search(classes) if isinstance(classes, str) else None
        extra: dict[str, JsonScalar] = {
            "alert_id": alert_id,
            "level": level.group(1) if level else None,
            "link": link,
        }
        row = make_row(name, status, None, extra)
        if row is None:  # pragma: no cover - the name was checked above
            skipped += 1
        else:
            rows.append(row)
    return make_listing(VARIANT, rows, skipped=skipped)


def slice_body(body: bytes) -> bytes:
    """Keep the page title and the alert banner widget (for fixtures).

    The slice is a minimal document that reads exactly as the page does; slicing it
    again changes nothing. A page without the widget slices to an empty document.
    """
    tree = HTMLParser(html_text(body))
    widget = tree.css_first('div[data-cms-widget="widgets/AlertBanner/AlertBanner"]')
    if widget is None:
        return document("")
    for junk in widget.css("style, script"):
        junk.decompose()
    title = tree.css_first("title")
    head = ""
    if title is not None:
        head = f"<title>{escape(collapse(title.text()), quote=False)}</title>"
    return document(head + (widget.html or ""))
