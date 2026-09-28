"""Humboldt County Office of Education: alerts, posted as news items.

The county office posts school closures as news items in its "Alerts" category
(``https://hcoe.org/news/alerts/``): "Klamath-Trinity Schools Closed Wednesday,
March 11", "Trinidad School Closed Monday Due to Water Issue" (both live on
2026-09-27). The category page is a WordPress theme page that names the
category's RSS feed, and the feed holds the same posts. Variants this adapter
reads:

``hcoe-alerts-feed``
    The category's RSS 2.0 feed (``https://hcoe.org/news/alerts/feed/``): a
    ``<channel>`` titled "Alerts | Humboldt County Office of Education", one
    ``<item>`` per post, newest first. Each post is a row: its ``<title>`` is the
    name (a post names the school or district in its title; the feed has no other
    name), the text of its ``<content:encoded>`` (the post's paragraphs, which
    carry its updates, such as "UPDATE Tuesday, Jan. 6: Trinidad School is OPEN
    today.") the status (else its ``<description>`` without the "Continue
    Reading" link), and its ``<pubDate>`` the update text
    (``raw_extra["updated_scope"]`` is ``"row"``). The link, the ``guid``, the
    categories (joined with ``"; "``) and the excerpt go in ``raw_extra``
    (``link``, ``guid``, ``categories``, ``excerpt``). Posts that are not
    closures (the category also holds notices such as "Local Schools' 2026-2027
    Enrollment Has Begun") are rows too: this adapter does not classify. A
    channel with no ``<item>`` is the empty state.

``hcoe-alerts-posts``
    The category page (``https://hcoe.org/news/alerts/``), whose "All Alerts"
    module (``div.posts-blog-feed-module.news-alerts``, the Extra theme's blog
    feed) lists the category's newest posts, one ``<article>`` each, as the
    captures of 2019-09-18 (5 posts), 2023-03-30 and 2026-02-17 and the live page
    of 2026-09-27 (10 each) show::

        <article id="post-24509" class="post ... category-alerts ...">
          <h2 class="post-title entry-title"><a href="https://hcoe.org/2023/03/
            march-8-2023-weather-related-closures/">March 8, 2023 &#8211; Weather
            Related Closures</a></h2>
          <div class="post-meta vcard"><p><span class="updated">Mar 8, 2023</span>
            | <a href="https://hcoe.org/news/alerts/" rel="tag">Alerts</a></p></div>
          <div class="excerpt entry-summary"><p>The following schools/districts are
            closed for weather related reasons on Wednesday, March 8,...</p>
            <a class="read-more-button" href="...">Read More</a></div></article>

    Each post is a row, as in the feed: its title the name, its excerpt (without
    the "Continue Reading" and "Read More" links) the status, and its date
    (``span.updated``, as the page shows it) the update text
    (``updated_scope`` ``row``); the link, the article's ``id`` and the categories
    (joined with ``"; "``) go in ``raw_extra`` (``link``, ``post_id``,
    ``categories``). The live poller reads the feed; the page's list is what its
    archived captures hold (the feed was archived only in 2020). A module without
    a post has not been seen and is refused.

``hcoe-alerts-page``
    A category page without that module that names the category's feed in its
    head (``<link rel="alternate" type="application/rss+xml" title="... Alerts
    Category Feed" href="https://hcoe.org/news/alerts/feed/">``). A
    :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED` listing that
    follows the feed.

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`.
"""

import re
from xml.etree import ElementTree

from selectolax.parser import HTMLParser, Node

from snowlight.sources.stations.body import decode
from snowlight.sources.stations.model import (
    MAX_STATUS,
    JsonScalar,
    Listing,
    ParsedRow,
    ShapeError,
)
from snowlight.sources.stations.regional import (
    collapse,
    deferred,
    document,
    fragment_text,
    html_text,
    listing,
    row,
    scalar,
)

FEED = "hcoe-alerts-feed"
POSTS = "hcoe-alerts-posts"
PAGE = "hcoe-alerts-page"
_MODULE = "div.posts-blog-feed-module.news-alerts"
CHANNEL_TITLE = "Alerts | Humboldt County Office of Education"
_CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"
_CONTINUE = re.compile(r"<a\b[^>]*\bclass=\"continue\"[^>]*>.*?</a>", re.IGNORECASE | re.DOTALL)
_FEED_LINK = re.compile(
    r"<link\b(?=[^>]*\brel=\"alternate\")(?=[^>]*\btype=\"application/rss\+xml\")"
    r"(?=[^>]*\btitle=\"[^\"]*Alerts Category Feed\")[^>]*\bhref=\"(https://hcoe\.org/[^\"]+/feed/)\"",
    re.IGNORECASE,
)
_ITEM_FIELDS = frozenset({"title", "link", "pubDate", "guid", "category", "description", _CONTENT})


def _text(element: ElementTree.Element, tag: str) -> str:
    found = element.find(tag)
    return "" if found is None else collapse("".join(found.itertext()))


def _post_text(fragment: str) -> str:
    """A post's text as the page shows it: each top-level block read whole, joined by a space.

    Inline markup (a link, a bold "UPDATE:") joins its text without a space, as a
    browser shows it; paragraphs and other blocks are separated by one.
    """
    wrapper = HTMLParser(f"<div>{fragment}</div>").css_first("div")
    parts: list[str] = []
    child = wrapper.child if wrapper is not None else None
    while child is not None:
        if child.tag != "_comment":
            parts.append(child.text(deep=True, separator=""))
        child = child.next
    return collapse(" ".join(parts))


def _status(content: str, excerpt: str) -> str:
    text = content or excerpt
    return text if len(text) <= MAX_STATUS else text[: MAX_STATUS - 1] + "…"


def _item(item: ElementTree.Element) -> ParsedRow | None:
    unknown = {child.tag for child in item} - _ITEM_FIELDS
    if not unknown <= {"{http://purl.org/dc/elements/1.1/}creator"}:
        raise ShapeError(f"an alerts feed item holds {sorted(unknown)}")
    content_node = item.find(_CONTENT)
    content = _post_text(content_node.text or "") if content_node is not None else ""
    description = item.find("description")
    raw_excerpt = (description.text or "") if description is not None else ""
    excerpt = _post_text(_CONTINUE.sub("", raw_excerpt))
    if not content and not excerpt:
        raise ShapeError("an alerts feed item has neither content nor a description")
    published = _text(item, "pubDate") or None
    extra: dict[str, JsonScalar] = {}
    for key, value in (
        ("link", _text(item, "link")),
        ("guid", _text(item, "guid")),
        ("categories", "; ".join(_text(c, ".") for c in item.findall("category"))),
        ("excerpt", excerpt),
    ):
        if value:
            extra[key] = scalar(value)
    if published:
        extra["updated_scope"] = "row"
    return row(fragment_text(_text(item, "title")), _status(content, excerpt), published, extra)


def _feed(root: ElementTree.Element) -> Listing:
    channel = root.find("channel")
    if root.tag != "rss" or channel is None:
        raise ShapeError("not an RSS 2.0 feed")
    title = fragment_text(_text(channel, "title"))
    if title != CHANNEL_TITLE:
        raise ShapeError(f"an RSS feed titled {title!r}, not the Humboldt COE alerts feed")
    found: list[ParsedRow] = []
    skipped = 0
    for item in channel.findall("item"):
        parsed = _item(item)
        if parsed is None:
            skipped += 1
        else:
            found.append(parsed)
    return listing(FEED, found, skipped=skipped)


def _node_text(node: Node) -> str:
    return collapse(node.text(deep=True, separator=""))


def _post(article: Node) -> ParsedRow | None:
    title = article.css_first("h2.post-title")
    excerpt = article.css_first("div.excerpt")
    if title is None or excerpt is None:
        raise ShapeError("an alerts post on the page has no title or no excerpt")
    for link in excerpt.css("a.continue, a.read-more-button"):
        link.decompose()
    paragraphs = [_node_text(part) for part in excerpt.css("p")]
    status = collapse(" ".join(paragraphs)) if paragraphs else _node_text(excerpt)
    date = article.css_first(".post-meta span.updated")
    published = _node_text(date) if date is not None else ""
    anchor = title.css_first("a")
    extra: dict[str, JsonScalar] = {}
    for key, value in (
        ("link", (anchor.attributes.get("href") or "") if anchor is not None else ""),
        ("post_id", article.attributes.get("id") or ""),
        ("categories", "; ".join(_node_text(tag) for tag in article.css(".post-meta a[rel=tag]"))),
    ):
        if value:
            extra[key] = scalar(value)
    if published:
        extra["updated_scope"] = "row"
    return row(_node_text(title), status, published or None, extra)


def _posts(module: Node) -> Listing:
    articles = module.css("article")
    if not articles:
        raise ShapeError("the alerts page's post list holds no post (not seen empty)")
    found: list[ParsedRow] = []
    skipped = 0
    for article in articles:
        parsed = _post(article)
        if parsed is None:
            skipped += 1
        else:
            found.append(parsed)
    return listing(POSTS, found, skipped=skipped)


def parse(body: bytes) -> Listing:
    """Read the alerts category's RSS feed, or the category page's posts (or its feed link)."""
    raw = decode(body).removeprefix(b"\xef\xbb\xbf").lstrip()
    if raw.startswith((b"<?xml", b"<rss")):
        try:
            root = ElementTree.fromstring(raw)  # noqa: S314 - one small feed, no entities fetched
        except ElementTree.ParseError as error:
            raise ShapeError(f"the alerts feed does not parse: {error}") from error
        return _feed(root)
    text = html_text(body)
    module = HTMLParser(text).css_first(_MODULE)
    if module is not None:
        return _posts(module)
    links = _FEED_LINK.findall(text)
    if links:
        return deferred(PAGE, tuple(dict.fromkeys(links)))
    raise ShapeError("not the Humboldt COE alerts feed or the category page naming it")


def slice_body(body: bytes) -> bytes:
    """Keep a feed whole; keep a page's post list, or its feed link."""
    found = parse(body)
    if found.variant == FEED:
        return decode(body)
    if found.variant == POSTS:
        module = HTMLParser(html_text(body)).css_first(_MODULE)
        return document(module.html or "" if module is not None else "")
    title = "Humboldt County Office of Education &raquo; Alerts Category Feed"
    links = "".join(
        f'<link rel="alternate" type="application/rss+xml" title="{title}" href="{url}" />'
        for url in found.follows
    )
    return document(links)
