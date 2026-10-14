"""District homepages built with Google Sites: the site's announcement banner.

Before Clay County District Schools moved its site to Apptegy, its homepage was a
Google Sites page, and Google Sites' announcement banner (a site-wide banner the
site's editors switch on, with a message and an optional button) stood at the top
of the page, rendered into the page as served. The archive's capture of the
homepage of 2022-09-28 (Hurricane Ian) holds it::

    <header id="atIdViewHeader"><div jscontroller="...">
      <div jsname="..." class="..." role="region" aria-labelledby="i1" ...>
        <p ... id="i1" ...>All Clay County Schools and the district offices will
        officially be closed Wednesday-Friday.</p>
        <div ...><div ... title="Click Here."><a href="http://www.google.com/url?q=...">

and its captures of 2024 (Hurricanes Helene and Milton) a header with no banner.
The Apptegy adapter reads such a capture of its station's homepage with
:func:`parse_text`, after the forms it reads first.

Variant this module reads:

``googlesites-banner``
    A Google Sites page (its view header, ``header#atIdViewHeader``). The banner is the header's
    region (``div[role=region]``) whose ``aria-labelledby`` names the paragraph
    holding its message. A page with the header and no such region is an empty
    list (no banner switched on).

The banner is one row: ``raw_name`` the site's name (its ``itemprop="name"``, else
its title: "Clay County District Schools, Florida"; the banner names no school,
and the station's ``leaids`` say whose it is), ``raw_status`` the message, no
``raw_updated_text`` (a banner shows no time), and ``raw_extra`` ``button`` (the
button's title, if any) and ``link`` (its target, unwrapped from Google's
redirect when it is one). A page that is not a Google Sites page raises
:class:`~snowlight.sources.stations.model.ShapeError`, and so does a banner whose
labelling paragraph is missing.
"""

from html import escape
from urllib.parse import parse_qs, urlsplit

from selectolax.parser import HTMLParser, Node

from snowlight.sources.stations.gap_markup import (
    collapse,
    document,
    html_text,
    make_listing,
    make_row,
    node_text,
)
from snowlight.sources.stations.model import JsonScalar, Listing, ShapeError

VARIANT = "googlesites-banner"
HEADER = "header#atIdViewHeader"
MARKER = 'id="atIdViewHeader"'


def holds_site_header(text: str) -> bool:
    """Whether a page is a Google Sites page (it has the Google Sites view header)."""
    return MARKER in text


def _site_name(tree: HTMLParser) -> str:
    named = tree.css_first('meta[itemprop="name"]')
    content = named.attributes.get("content") if named is not None else None
    if isinstance(content, str) and collapse(content):
        return collapse(content)
    title = tree.css_first("title")
    name = collapse(title.text()) if title is not None else ""
    if not name:
        raise ShapeError("the Google Sites page has no name or title to name the district by")
    return name


def _banner(header: Node) -> Node | None:
    for region in header.css('div[role="region"]'):
        if region.attributes.get("aria-labelledby"):
            return region
    return None


def _unwrap(href: str) -> str:
    parts = urlsplit(href)
    if parts.netloc.endswith("google.com") and parts.path == "/url":
        target = parse_qs(parts.query).get("q")
        if target:
            return target[0]
    return href


def parse_text(text: str) -> Listing:
    """Read a Google Sites homepage's announcement banner (``text`` is the page)."""
    if not holds_site_header(text):
        raise ShapeError("no Google Sites view header: not a Google Sites page")
    tree = HTMLParser(text)
    header = tree.css_first(HEADER)
    if header is None:
        raise ShapeError("no Google Sites view header: not a Google Sites page")
    name = _site_name(tree)
    region = _banner(header)
    if region is None:
        return make_listing(VARIANT, [])
    label = str(region.attributes.get("aria-labelledby"))
    message = region.css_first(f'[id="{label}"]')
    if message is None:
        raise ShapeError("the banner's labelling paragraph is missing")
    button = region.css_first("[title]")
    anchor = region.css_first("a[href]")
    href = anchor.attributes.get("href") if anchor is not None else None
    extra: dict[str, JsonScalar] = {
        "button": collapse(str(button.attributes.get("title"))) if button is not None else None,
        "link": _unwrap(href) if isinstance(href, str) and href else None,
    }
    words = node_text(message)
    row = make_row(name, words, None, extra) if words else None
    return make_listing(VARIANT, [row] if row is not None else [], skipped=0 if row else 1)


def slice_body(body: bytes) -> bytes:
    """Keep the site's name and the view header with its banner.

    The slice is a minimal document that reads exactly as the page does (the
    header keeps only its banner region, the navigation dropped); a page that is
    not a Google Sites page slices to an empty document.
    """
    text = html_text(body)
    if not holds_site_header(text):
        return document("")
    tree = HTMLParser(text)
    header = tree.css_first(HEADER)
    if header is None:
        return document("")
    name = escape(_site_name(tree))
    region = _banner(header)
    banner = region.html if region is not None and region.html is not None else ""
    return document(
        f'<meta itemprop="name" content="{name}"><header id="atIdViewHeader">{banner}</header>'
    )
