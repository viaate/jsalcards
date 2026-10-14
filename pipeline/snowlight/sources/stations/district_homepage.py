"""District homepages read whole: districts without a vendor alert channel.

Five Utah districts (Granite, Jordan, Canyons, Washington County and Provo; 277 of
the state's 1,203 schools) run their own WordPress sites, with none of the vendor
alert channels the other district adapters read. Each was read first-hand on
2026-10-05 with the project's User-Agent (``district-homepage.yaml`` keeps each
check). Two load their alerts after the page loads, from a file of their own;
one renders an alerts section into the page; two show whatever they post in the
page itself. Variants this adapter reads:

``wp-rest-notices``
    Granite School District's emergency notifications: its homepage's script
    (the ``gsd-webmaster-district-tools`` plugin's
    ``...-emergency-notifications-public.js``) asks
    ``/wp-json/wp/v2/en?notification_type=district`` (WordPress's REST list of the
    site's ``en`` posts) and writes each as "Emergency notification: <title>"
    into ``div#emergency-notifications``. The answer is a JSON array of posts
    (``[]`` on 2026-10-05: an empty list, variant ``district-alerts-empty``, since an
    empty array does not say which of the two files it is). One row per post: ``raw_name`` its
    ``title.rendered`` reduced to text, ``raw_status`` its ``excerpt.rendered``
    (else its ``content.rendered``) reduced to text, else the title again,
    ``raw_updated_text`` its ``modified_gmt`` (else ``date_gmt``, else ``date``),
    and ``raw_extra`` ``post_id``, ``link`` and ``date``.

``wcsd-alerts``
    Washington County School District's alerts: its pages load
    ``//alert.washk12.org/alert.js`` ("WCSD Alerts"), which asks
    ``https://alert.washk12.org/endpoint.php`` and shows every alert of the JSON
    array it answers as a banner (one on 2026-10-05: "NEW STUDENT REGISTRATION",
    type ``information``). One row per alert: ``raw_name`` its ``title``,
    ``raw_status`` its ``message`` reduced to text, no ``raw_updated_text`` (the
    answer gives no time), and ``raw_extra`` ``alert_id``, ``type``, ``active``
    (``isActive``), ``link`` and ``updates`` (``numUpdates``). ``[]`` is an empty list.
    The answers of 2022 to 2025 the archive holds write the numbers as strings
    (``"id":"96"``, ``"isActive":"1"``, ``"numUpdates":"0"``): a string of digits is
    read as the number it writes; any other id is an error.

``district-homepage-alert-loader``
    A homepage that loads one of those two files (the plugin's container, or the
    WCSD Alerts script): a deferred page that names the file. The live poller reads
    the file itself (each station's ``data_url``); the archive reader follows a
    homepage capture to the file's capture nearest it, when the archive holds one. A
    loader page that shows closing lines of its own (Granite's homepage of 2023-02-22,
    "Distance Learning Day for Granite School District - Wednesday, February 22,
    2023") is read as those lines, still loading the file
    (:func:`snowlight.sources.stations.homepage.with_page_text`).

``district-homepage-alerts``
    Provo City School District's homepage, whose theme renders an alerts section
    into the page, ``<section class="alerts hidden">`` when there is none (live on
    2026-10-05). One row per element in the section (a heading's text as the name,
    when the element has one, else its text; its text as the status), or one row
    for the section's text when it holds text but no element; an empty section is
    an empty list.

``district-homepage-text``
    Any other HTML page: the district's homepage read as text, the way the
    closure-text check reads it (:mod:`snowlight.sources.stations.homepage`): one
    page-text row per line announcing a closing, an empty list when there is none.
    Jordan's (a WordPress theme with no alert plugin) and Canyons' (Elementor) pages
    render what the district posts on the server, so their text is what a visitor
    reads; a closing in an image alone would not be read. Such a page is typed by
    hand and states no time for itself, and a district's homepage keeps its news
    items long after the day (Greenville's "GPSD closed on January 16, 2024 (Due to
    inclement weather)" was still on its homepage on 2026-10-13), so the list is ``typed``
    (:attr:`~snowlight.sources.stations.model.Listing.typed`): the live reader keeps a
    line only while it names a day near the read or is new since an earlier read of
    the page (:mod:`snowlight.sources.stations.typed_history`; every read of this
    adapter's pages is an observation, ``fetch.TYPED_PAGE_ADAPTERS``). A line that heads a
    news card with a posting stamp carries the stamp (Gulf's "SCHOOL CLOSURES: Hurricane
    Isaias" over "posted: Oct 07, 2026", the closing for the hurricane of 8-10 October
    2026: :func:`snowlight.sources.stations.homepage.text_rows`), and names that day.

Every list read from a page itself (alerts or text) also gets a page-text row for
each closing line its text shows that no row holds
(:func:`snowlight.sources.stations.homepage.with_page_text`). These are district
channels (:data:`snowlight.sources.stations.notices.GENERAL_CHANNEL_ADAPTERS`): a
read proves its station only with a row that announces a closing (a page-text row by
the stricter rule of :func:`snowlight.sources.stations.notices.page_text_closing`).
A body that is neither JSON in one of the two answers' shapes nor an HTML page
raises :class:`~snowlight.sources.stations.model.ShapeError`.
"""

import json
import re
from html import escape, unescape
from typing import Any

from selectolax.parser import HTMLParser, Node

from snowlight.sources.stations import homepage
from snowlight.sources.stations.gap_markup import (
    collapse,
    deferred,
    document,
    html_text,
    make_listing,
    make_row,
    node_text,
)
from snowlight.sources.stations.model import (
    JsonScalar,
    Listing,
    ListingState,
    ParsedRow,
    ShapeError,
)

WP_REST = "wp-rest-notices"
WCSD = "wcsd-alerts"
LOADER = "district-homepage-alert-loader"
ALERTS = "district-homepage-alerts"
TEXT = "district-homepage-text"
GRANITE_FILE = "/wp-json/wp/v2/en?notification_type=district"
"""The file Granite's homepage script asks for its emergency notifications."""
WCSD_FILE = "https://alert.washk12.org/endpoint.php"
"""The file the WCSD Alerts script asks for."""
_GRANITE = re.compile(r"emergency-notifications-public\.js|id=\"emergency-notifications\"")
_WCSD = re.compile(r"//alert\.washk12\.org/alert\.js")
_ALERTS_SECTION = "section.alerts"


def _plain(fragment: object) -> str:
    if not isinstance(fragment, str):
        return ""
    if "<" not in fragment:
        return collapse(unescape(fragment))
    tree = HTMLParser(f"<div>{fragment}</div>")
    node = tree.css_first("div")
    return node_text(node) if node is not None else collapse(fragment)


def _rendered(post: dict[str, Any], key: str) -> str:
    value = post.get(key)
    return _plain(value.get("rendered") if isinstance(value, dict) else value)


def _post(post: object) -> ParsedRow | None:
    if not isinstance(post, dict) or not isinstance(post.get("id"), int):
        raise ShapeError("a WordPress REST post without a numeric id")
    if not isinstance(post.get("title"), dict):
        raise ShapeError("a WordPress REST post without its title object")
    title = _rendered(post, "title")
    words = _rendered(post, "excerpt") or _rendered(post, "content")
    stamps = [post[key] for key in ("modified_gmt", "date_gmt", "date") if key in post]
    stamp = next((value for value in stamps if isinstance(value, str)), None)
    extra: dict[str, JsonScalar] = {
        "post_id": post["id"],
        "link": post["link"] if isinstance(post.get("link"), str) else None,
        "date": post["date"] if isinstance(post.get("date"), str) else None,
    }
    return make_row(title or words, words or title, stamp, extra)


def _number(value: object) -> int | None:
    """An integer, or a string of digits read as one (the WCSD answers of 2022 to 2025)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return int(value)
    return None


def _alert(alert: object) -> ParsedRow | None:
    if not isinstance(alert, dict) or "title" not in alert or "message" not in alert:
        raise ShapeError("a WCSD alert without its title and message")
    alert_id = _number(alert.get("id"))
    if alert_id is None:
        raise ShapeError(f"a WCSD alert without a numeric id: {alert.get('id')!r}")
    title, message = _plain(alert.get("title")), _plain(alert.get("message"))
    active = alert.get("isActive")
    active = _number(active) if isinstance(active, str) else active
    extra: dict[str, JsonScalar] = {
        "alert_id": alert_id,
        "type": alert["type"] if isinstance(alert.get("type"), str) else None,
        "active": active if isinstance(active, int | bool) else None,
        "link": collapse(alert["link"]) or None if isinstance(alert.get("link"), str) else None,
        "updates": str(alert["numUpdates"]) if alert.get("numUpdates") is not None else None,
    }
    return make_row(title or message, message if title else "", None, extra)


def _answer(data: object) -> Listing:
    if not isinstance(data, list):
        raise ShapeError("neither a WordPress REST list nor a WCSD alerts answer")
    wcsd = all(isinstance(item, dict) and "message" in item for item in data)
    read = _alert if wcsd else _post
    rows: list[ParsedRow] = []
    skipped = 0
    for item in data:
        row = read(item)
        if row is None:
            skipped += 1
        else:
            rows.append(row)
    return make_listing(WCSD if wcsd else WP_REST, rows, skipped=skipped)


def _section(section: Node) -> Listing:
    rows: list[ParsedRow] = []
    skipped = 0
    children = list(section.iter())
    for child in children:
        heading = child.css_first("h1, h2, h3, h4, strong, b")
        words = node_text(child)
        found = make_row(node_text(heading) or words, words, None, {})
        if found is None:
            skipped += 1
        else:
            rows.append(found)
    if not children and node_text(section):
        found = make_row(node_text(section), node_text(section), None, {})
        if found is not None:
            rows.append(found)
    return make_listing(ALERTS, rows, skipped=skipped)


def _page(text: str) -> Listing:
    if _GRANITE.search(text):
        return homepage.with_page_text(deferred(LOADER, (GRANITE_FILE,)), text)
    if _WCSD.search(text):
        return homepage.with_page_text(deferred(LOADER, (WCSD_FILE,)), text)
    tree = HTMLParser(text)
    section = tree.css_first(_ALERTS_SECTION)
    if section is not None:
        return homepage.with_page_text(_section(section), text)
    rows = homepage.text_rows(text)
    return Listing(
        variant=TEXT,
        state=ListingState.POPULATED if rows else ListingState.EMPTY,
        rows=tuple(rows),
        typed=True,
    )


def parse(body: bytes) -> Listing:
    """Read a Utah district's alert file or homepage (see the module docstring)."""
    text = html_text(body)
    stripped = text.lstrip()
    if stripped.startswith("["):
        try:
            data = json.loads(stripped)
        except ValueError as error:
            raise ShapeError(f"an answer that is not JSON: {error}") from error
        if data == []:
            return Listing(variant=ANSWER_EMPTY, state=ListingState.EMPTY, rows=())
        return _answer(data)
    if stripped.startswith("{"):
        raise ShapeError("a JSON object, not a list of posts or alerts")
    if not homepage.is_html(text):
        raise ShapeError("neither a JSON answer nor an HTML page")
    return _page(text)


ANSWER_EMPTY = "district-alerts-empty"
"""An empty JSON array: no post or alert up (the variant cannot tell the two files apart)."""


def slice_body(body: bytes) -> bytes:
    """The ``district-homepage-v1`` slice (see :func:`slice_body_v2`)."""
    return _slice(body, stamps=False)


def slice_body_v2(body: bytes) -> bytes:
    """The ``district-homepage-v2`` slice: as ``v1``, and a closing line that heads a news
    card keeps the card's posting stamp (:data:`snowlight.sources.stations.homepage.POSTED`)."""
    return _slice(body, stamps=True)


def _slice(body: bytes, *, stamps: bool) -> bytes:
    """Keep what the adapter reads of a page (for fixtures); an answer is kept whole.

    The page title; an alert loader's marker (the WCSD Alerts script, or Granite's
    container); Provo's alerts section; and each closing line of the page's text as
    a paragraph (:func:`snowlight.sources.stations.homepage.text_blocks`). Slicing a
    slice changes nothing, and it reads as the page.
    """
    text = html_text(body)
    if text.lstrip().startswith(("[", "{")):
        return body
    tree = HTMLParser(text)
    title = tree.css_first("title")
    parts = [f"<title>{escape(collapse(title.text()), quote=False)}</title>" if title else ""]
    if _GRANITE.search(text):
        parts.append('<div id="emergency-notifications"></div>')
    elif _WCSD.search(text):
        parts.append('<script src="//alert.washk12.org/alert.js"></script>')
    else:
        section = tree.css_first(_ALERTS_SECTION)
        if section is not None:
            parts.append(section.html or "")
    parts.append(homepage.text_blocks(text, stamps=stamps))
    return document("".join(parts))
