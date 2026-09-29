"""Finalsite school district sites: the page pops (alerts) of the district homepage.

Finalsite's CMS carries most of Montana's largest districts' sites (Billings, Great
Falls, Missoula, Bozeman, Kalispell, East Helena), Pocatello-Chubbuck and Blaine
County in Idaho, Teton County in Wyoming and six Florida county districts (Broward,
Palm Beach, Pinellas, Volusia, Escambia, Collier). A district posts an urgent
notice as a "page pop": a dialog over the homepage ("N page alerts"). Today's
homepage does not hold them: its script reads the page's ``<body data-pageid>``,
asks ``/fs/pages/<data-pageid>/page-pops`` (``Accept: text/html``) and opens the
``article.fsPagePop`` elements the answer holds.

How a station is read. The address alone proves nothing: ``/fs/pages/<id>/page-pops``
answers HTTP 200 with an empty body for the right page ID, for a made-up one
(``999999``) and for one that is not a number (``abc``) alike (Billings and
Chickasaw, 2026-09-28). So a Finalsite station registers no ``data_url``: the live
poller reads its homepage (``page_url``), this adapter reads the homepage's own
``data-pageid`` and the poller follows it to that page's page pops, the address the
homepage's script asks for today. Each station's ``page_check`` records the browser
check that saw its homepage ask for exactly that address
(:mod:`snowlight.sources.stations.finalsite_check`); a live homepage that names
another page ID, or holds no ID, or is not a Finalsite page, is an error until it is
checked again, never an empty list
(:func:`snowlight.sources.stations.fetch.page_check_mismatch`). An empty answer is
thus read only as the page pops of the page that named them.

Variants this adapter reads:

``finalsite-homepage``
    A published Finalsite page, ``<body data-pageid="N" class="fsLiveMode ...">``
    (``fsLiveMode``: the class Finalsite gives a page served to visitors), with no
    page pops in it. A :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED`
    listing whose ``follows`` is ``/fs/pages/N/page-pops``. Every one of the 82
    registered homepages on 2026-09-28.

``finalsite-homepage-pops``
    A published Finalsite page that carries its page pops in the page, the same
    ``<div id="fsPagePopCollection" hidden>`` as the fragment below (an older
    template: Volusia County Schools' homepage captured 2024-10-14, "Hurricane Milton
    Update"). Read in place; a collection with no pop is an empty list.

``finalsite-page-pops``
    The fragment ``<div id="fsPagePopCollection" hidden>`` holding one ``<article
    class="fsPagePop" data-id data-visible-at data-hidden-at data-reset-at
    data-delay-option data-delay-time>`` per pop, each with its title
    (``h2.fsPagePopTitle``) and message (``div.fsPagePopMessage``). Live on
    2026-09-27: Broward's "Notice" (its referendum), Great Falls' "Important Notice
    Regarding Settlement Agreement between MT OPI and C. DuPuis-Pablo".

``finalsite-no-page-pops``
    The answer when the page has no pop to show: HTTP 200 with an empty body (13
    of the 15 district sites on 2026-09-27). Read as an empty list: the page pops
    of the homepage that named the address.

``schoolwires-important-announcements``
    The district's homepage on Finalsite's other CMS, Web Community Manager
    ("Schoolwires", formerly Blackboard's), before the district moved to the
    Finalsite CMS: Palm Beach's homepage captured 2024-10-10, whose footer reads
    "Copyright © 2024 Finalsite - all rights reserved." and links the "Web Community
    Manager Privacy Policy" at finalsite.com. Read by
    :mod:`snowlight.sources.stations.schoolwires` (the "Important Announcement" app).

Each pop is one row: ``raw_name`` its title as written (the fragment names no
school: the registry entry's ``leaids`` say whose it is), ``raw_status`` the
message's text, ``raw_updated_text`` its ``data-visible-at`` (when the district
made it visible), and ``raw_extra`` ``pop_id``, ``visible_at``, ``hidden_at``,
``reset_at``, ``delay_option`` and ``image_alt`` (alt text of the message's
images, when it has no words). A pop with neither title nor text is a skipped
row. Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`:
JSON; a whole page that is not a published Finalsite page (another CMS, a login or
error page); a Finalsite page whose ``data-pageid`` is missing or not a number; a
fragment without the pop collection (the archive's one-character answers); or a
pop without its ``data-id``.
"""

import re
from html import escape

from selectolax.parser import HTMLParser, Node

from snowlight.sources.stations import schoolwires
from snowlight.sources.stations.gap_markup import (
    collapse,
    deferred,
    html_text,
    make_listing,
    make_row,
    node_text,
)
from snowlight.sources.stations.model import JsonScalar, Listing, ParsedRow, ShapeError

HOMEPAGE = "finalsite-homepage"
HOMEPAGE_POPS = "finalsite-homepage-pops"
POPS = "finalsite-page-pops"
NONE = "finalsite-no-page-pops"
LIVE_CLASS = "fsLiveMode"
"""The body class Finalsite gives a published page (the page a visitor is served)."""

_BODY = re.compile(r"<body\b", re.IGNORECASE)
_PAGE_ID = re.compile(r"^[0-9]{1,9}$")


def page_pops_path(page_id: str) -> str:
    """Return the address a page's page-pops script asks for (relative to the page's site)."""
    if not _PAGE_ID.match(page_id):
        raise ShapeError(f"a Finalsite page ID is a number, not {page_id!r}")
    return f"/fs/pages/{page_id}/page-pops"


def _attr(node: Node, name: str) -> str | None:
    value = node.attributes.get(name)
    return collapse(value) or None if isinstance(value, str) else None


def _row(article: Node) -> ParsedRow | None:
    pop_id = _attr(article, "data-id")
    if pop_id is None or not pop_id.isdigit():
        raise ShapeError("a page pop has no data-id")
    title = node_text(article.css_first(".fsPagePopTitle"))
    message = article.css_first(".fsPagePopMessage")
    if message is not None:
        for junk in message.css("style, script"):
            junk.decompose()
    text = node_text(message)
    alts = [
        collapse(str(img.attributes.get("alt") or ""))
        for img in (message.css("img") if message is not None else [])
    ]
    image_alt = "; ".join(alt for alt in alts if alt) or None
    extra: dict[str, JsonScalar] = {
        "pop_id": int(pop_id),
        "visible_at": _attr(article, "data-visible-at"),
        "hidden_at": _attr(article, "data-hidden-at"),
        "reset_at": _attr(article, "data-reset-at"),
        "delay_option": _attr(article, "data-delay-option"),
        "image_alt": image_alt if not text else None,
    }
    name = title or text or (image_alt or "")
    status = text if title or not text else ""
    return make_row(name, status, _attr(article, "data-visible-at"), extra)


def _pops(collection: Node, variant: str) -> Listing:
    rows: list[ParsedRow] = []
    skipped = 0
    for article in collection.css("article.fsPagePop"):
        row = _row(article)
        if row is None:
            skipped += 1
        else:
            rows.append(row)
    return make_listing(variant, rows, skipped=skipped)


def _is_page(text: str) -> bool:
    """Whether ``text`` is a whole HTML page rather than the page-pops fragment."""
    return _BODY.search(text) is not None or text.lstrip()[:15].lower().startswith(
        ("<!doctype", "<html")
    )


def page_id(tree: HTMLParser) -> str | None:
    """Return a published Finalsite page's ``data-pageid``, or None for any other page.

    Raises:
        ShapeError: the page is a Finalsite page (``fsLiveMode``, or a ``data-pageid``)
            whose ID is missing or not a number, or which is not a published page.
    """
    body = tree.body
    if body is None:
        return None
    classes = str(body.attributes.get("class") or "").split()
    has_id = "data-pageid" in body.attributes
    if LIVE_CLASS not in classes and not has_id:
        return None
    if LIVE_CLASS not in classes:
        raise ShapeError(
            f"a page with a data-pageid but no {LIVE_CLASS} class: not a published page"
        )
    value = collapse(str(body.attributes.get("data-pageid") or ""))
    if not value:
        raise ShapeError("a Finalsite page that names no data-pageid")
    if not _PAGE_ID.match(value):
        raise ShapeError(f"a Finalsite page whose data-pageid is not a number: {value!r}")
    return value


def _page(text: str) -> Listing:
    tree = HTMLParser(text)
    found = page_id(tree)
    if found is not None:
        collection = tree.css_first("#fsPagePopCollection")
        if collection is not None:
            return _pops(collection, HOMEPAGE_POPS)
        return deferred(HOMEPAGE, (page_pops_path(found),))
    if schoolwires.holds_announcements(text):
        return schoolwires.parse_text(text)
    raise ShapeError(
        "not a Finalsite page: no <body data-pageid> with the fsLiveMode class, and no "
        "Web Community Manager important announcements"
    )


def parse(body: bytes) -> Listing:
    """Read a Finalsite homepage or one answer of its ``page-pops`` fragment."""
    text = html_text(body)
    if not text.strip():
        return make_listing(NONE, [])
    if text.lstrip()[:1] in ("{", "["):
        raise ShapeError("JSON, not a Finalsite page or its page pops")
    if _is_page(text):
        return _page(text)
    tree = HTMLParser(text)
    collection = tree.css_first("#fsPagePopCollection")
    if collection is None:
        raise ShapeError("no fsPagePopCollection: not a Finalsite page-pops fragment")
    return _pops(collection, POPS)


def slice_body(body: bytes) -> bytes:
    """Keep what the adapter reads of a page; a page-pops answer is kept whole.

    A Finalsite page keeps its title, its ``<body>`` tag with every attribute, and
    its page-pop collection when it holds one (without style and script, which are
    not text); a Web Community Manager page is cut by
    :func:`snowlight.sources.stations.schoolwires.slice_body`. The slice is a
    minimal document that reads exactly as the page does.
    """
    text = html_text(body)
    if not text.strip() or not _is_page(text):
        return text.encode()
    tree = HTMLParser(text)
    if page_id(tree) is None:
        return schoolwires.slice_body(body)
    title = tree.css_first("title")
    head = f"<title>{escape(title.text(), quote=False)}</title>" if title is not None else ""
    node = tree.body
    attributes = "".join(
        f' {name}="{escape(value)}"' if value is not None else f" {name}"
        for name, value in (node.attributes.items() if node is not None else [])
    )
    collection = tree.css_first("#fsPagePopCollection")
    inner = ""
    if collection is not None:
        for junk in collection.css("style, script"):
            junk.decompose()
        inner = collection.html or ""
    return (
        f"<!DOCTYPE html><html><head>{head}</head><body{attributes}>{inner}</body></html>\n"
    ).encode()
