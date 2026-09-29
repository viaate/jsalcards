"""Edlio school district sites: the homepage alert (a news story shown over the homepage).

Edlio's CMS carries district sites in the gap states: Natrona County (Casper),
Sublette #9, Hot Springs #1 and Weston #1 in Wyoming, Soda Springs in Idaho,
Livingston in Montana, and Edinburg, Mission, Los Fresnos and eight smaller South
Texas districts. A district marks a news story (or a page) as its *homepage alert*,
and the homepage then carries it, rendered on the server, as a dialog the page's
script opens on load (Magnific Popup), with a "Don't show again" link. When no alert
is up, the homepage has no such element. Because the alert is in the page as served,
archived captures of the homepage hold it too.

Variant this adapter reads:

``edlio-homepage-alert``
    An Edlio homepage (``<meta name="generator" content="Edlio CMS">``). The alert,
    when there is one, is::

        <article id="homepage_news_alert_modal" class="mfp-hide cf" itemscope
                 itemtype="http://schema.org/Article">
          <div id="image-content" class="image-content"><img alt="..."></div>
          <div id="article-content" class="article-content">
            <header class="cf">
              <h2 class="title" itemprop="name headline">Weather Advisory</h2>
            </header>
            <div class="summary cf">
              <p>No School - Jan 21, 2025<br>Delayed Start - Jan 22, 2025</p>
            </div>
            <div class="buttons cf"><div class="read-more">
              <a href="/apps/news/article/2020301" class="button-text button">Read full story</a>
            </div></div>
          </div>
          <a id="dont-show-again" href="">Don't show again</a>
        </article>

    and the script that opens it keys the "Don't show again" choice by the story's id
    and the alert's expiry (``'doNotShowAlert' + '_' + '2020301_' + '2025/01/23
    01:00:00'``, ``var alertExpirationDate = new Date('2025/01/23 01:00:00')``).
    Seen: Mission CISD's homepage archived on 2025-01-21 11:10 UTC ("Weather
    Advisory": "No School - Jan 21, 2025 / Delayed Start - Jan 22, 2025"), and Sublette
    #9's live on 2026-09-28 ("School Picture Days", with a picture, linking to a page).
    A homepage without the element is an empty list (the other fifteen district sites
    on 2026-09-28, and every other archived capture read so far).

Each alert is one row: ``raw_name`` its headline as written (the element names no
school: the registry entry's ``leaids`` say whose it is), ``raw_status`` its summary's
text, no ``raw_updated_text`` (the page shows no time), and ``raw_extra``
``article_id`` (from the script's key), ``expires_text`` (the expiry as the script
writes it, local time without a zone), ``link`` (the "read more" target) and
``image_alt`` (the picture's alt text, only when the alert has no words). An alert
with a summary and no headline takes the summary as its name; one with neither
headline, summary nor picture text is a skipped row. A body that is not an Edlio page
(a bot challenge, another CMS, a redirect's error page) raises
:class:`~snowlight.sources.stations.model.ShapeError`.
"""

import re
from html import escape

from selectolax.parser import HTMLParser, Node

from snowlight.sources.stations.gap_markup import (
    collapse,
    html_text,
    make_listing,
    make_row,
    node_text,
)
from snowlight.sources.stations.model import JsonScalar, Listing, ParsedRow, ShapeError

VARIANT = "edlio-homepage-alert"
MODAL = "homepage_news_alert_modal"
GENERATOR = "Edlio CMS"
_KEY = re.compile(r"alertKeyStartConstant\s*\+\s*'_'\s*\+\s*'(\d+)_'")
_EXPIRY = re.compile(r"alertExpirationDate\s*=\s*new Date\('([^']*)'\)")


def _is_edlio(tree: HTMLParser) -> bool:
    for meta in tree.css('meta[name="generator"]'):
        content = meta.attributes.get("content")
        if isinstance(content, str) and content.strip().startswith("Edlio"):
            return True
    return False


def _alert_script(tree: HTMLParser) -> str:
    """Return the text of the script that opens the alert (empty when there is none)."""
    for script in tree.css("script"):
        text = script.text(deep=True)
        if "alertKeyStartConstant" in text:
            return text
    return ""


def _row(article: Node, script: str) -> ParsedRow | None:
    headline = node_text(article.css_first("h2.title"))
    summary_node = article.css_first("div.summary")
    if summary_node is not None:
        for junk in summary_node.css("style, script"):
            junk.decompose()
    summary = node_text(summary_node)
    pictures = article.css_first("#image-content") or article.css_first(".image-content")
    alts = [
        collapse(alt)
        for img in (pictures.css("img") if pictures is not None else [])
        if isinstance(alt := img.attributes.get("alt"), str) and collapse(alt)
    ]
    image_alt = "; ".join(alts) or None
    anchor = article.css_first(".read-more a")
    href = anchor.attributes.get("href") if anchor is not None else None
    key = _KEY.search(script)
    expiry = _EXPIRY.search(script)
    extra: dict[str, JsonScalar] = {
        "article_id": key.group(1) if key else None,
        "expires_text": collapse(expiry.group(1)) or None if expiry else None,
        "link": collapse(href) or None if isinstance(href, str) else None,
        "image_alt": image_alt if not (headline or summary) else None,
    }
    name = headline or summary or (image_alt or "")
    status = summary if headline else ""
    return make_row(name, status, None, extra)


def parse(body: bytes) -> Listing:
    """Read an Edlio district homepage's alert (see the module docstring)."""
    tree = HTMLParser(html_text(body))
    articles = tree.css(f"article#{MODAL}")
    if not articles and not _is_edlio(tree):
        raise ShapeError("no Edlio generator and no homepage alert: not an Edlio homepage")
    script = _alert_script(tree)
    rows: list[ParsedRow] = []
    skipped = 0
    for article in articles:
        row = _row(article, script)
        if row is None:
            skipped += 1
        else:
            rows.append(row)
    return make_listing(VARIANT, rows, skipped=skipped)


def slice_body(body: bytes) -> bytes:
    """Keep the page title, the generator, the alert's script and the alert (for fixtures).

    The slice is a minimal document that reads exactly as the page does (an Edlio
    page without an alert slices to its title and generator); slicing a slice
    changes nothing.
    """
    tree = HTMLParser(html_text(body))
    title = tree.css_first("title")
    head = ""
    if title is not None:
        head = f"<title>{escape(collapse(title.text()), quote=False)}</title>"
    if _is_edlio(tree):
        head += f'<meta name="generator" content="{GENERATOR}">'
    script = _alert_script(tree)
    parts = [f"<script>{script}</script>"] if script else []
    for article in tree.css(f"article#{MODAL}"):
        for junk in article.css("style, script"):
            junk.decompose()
        if article.html is not None:
            parts.append(article.html)
    inner = "".join(parts)
    return f"<!DOCTYPE html><html><head>{head}</head><body>{inner}</body></html>\n".encode()
