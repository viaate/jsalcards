"""A station's closings articles: the closings a newsroom posts as dated articles.

KIFI Local News 8 (Idaho Falls; News-Press & Gazette) keeps no closings page
(``/weather/closings/`` answers 404). On a morning schools close for weather, its newsroom
posts an article titled for the day and types the list into it, updating it as districts
call: "School closures and delays for Wednesday, March 6" (2024-03-06, 19 entries from
Bonneville School District 93 to "Teton County School District 1 - 2 hour late start"),
"UPDATE: School Closures and Delays for Tuesday, Jan 16th" (2024), "School closures for
Feb. 28, 2023", "School Closures - Tuesday February 25, 2025". A single school's or
district's closing gets a story of its own: "Taylorview Middle School closed Thursday due to
down heat pumps" (2025-12-18), "Classes Canceled: Rising illnesses and absences force
multi-day closure for Ririe School District" (2026-01-28), "Teton County Schools Closed
Tomorrow due to Jackson Boil Order" (2026-09-25), "School canceled for Chief Tahgee
Elementary Academy" (2026-10-07). The site is WordPress; its REST list of posts
(``/wp-json/wp/v2/posts``, robots.txt: no rule matches) answers a search for the word
"school", the wire's and the networks' categories left out and the newest first, with
each post's title, text and the times WordPress stamped it with (``date_gmt``,
``modified_gmt``). The live poller reads that answer.

Variant this adapter reads:

``wp-closings-articles``
    A JSON array of WordPress REST posts. A post is a closings article when it is the
    station's own (:func:`own_article`: its link is not a wire or network story's path, and
    its dateline credits no other outlet: "LONDON (AP) -" and "(CNN) -" are the wire's,
    "BOISE, Idaho (KIVI) -" another station's, "IDAHO FALLS, Idaho (KIFI) -" or no credit
    at all the station's own) and its title says it announces closings
    (:func:`closings_article`). A *list article* (a title such as "School closures ...",
    "School Closures and Delays for ...", "Schools announcing closures ...", "Updated list
    of Monday school cancelations") is read as a typed list
    (:func:`snowlight.sources.stations.typed.read_typed`: list items, or lines and entries
    of paragraphs); a *story* of one closing ("... Middle School closed Thursday ...",
    "Classes Canceled: ...", "... cancels school ...") is one row, its title, with its text
    as the status (and so is a list article in which the typed reader finds no entry).
    Titles about closings that are not one ("School board votes to close Washington
    Elementary", "... rally ahead of possible school closure", "School bus delays expected
    as ... intersection closes") are not closings articles. Every row carries the
    article's ``post_id``, ``link`` and ``title`` and is stamped with the time the article
    last changed (``modified_gmt``), or, for an article changed more than
    :data:`EDIT_LAG` after it was published, with its publication: a later edit of an old
    article is not that day's news. An answer with no closings article is an empty list;
    ``[]`` too.

The rows are dated (``Listing.dated_rows``): the live reader keeps an article's rows only
while it was stamped within ``fetch.TYPED_CURRENT`` of the read. The newest closings
article's publication is the list's own time (``list_updated_at``), judged by the
closure-season rule like any list's (``fetch``, step 4): a newsroom whose newest closings
article predates the last winter, when weather that closes schools came to its market
since, reads ``stale``. KIFI wrote list articles for the storms of each winter from
2022-23 to 2024-25 (the last on 2025-02-25); in 2025-26 it wrote stories of single
closings (December 2025 to October 2026) but no weather list: the market's one closure
event of that winter, 2025-12-05, was a Winter Storm Warning for the mountain zones
(KIFI's forecast that day: "mountain winter storm warnings posted"), and no district's
page on record closed for it; North Gem School District 149 (Caribou County) closed for
weather on 2026-02-18 under a warning for its own zone, and KIFI wrote nothing of it
(its stories that week: highway closures and snowdrifts in Rexburg). A TV station's list:
any row of a closings article is a closing. Older articles are the list's dated history
(:mod:`snowlight.sources.stations.history`). Anything else raises
:class:`~snowlight.sources.stations.model.ShapeError`.
"""

import html
import json
import re
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from selectolax.parser import HTMLParser

from snowlight.sources.stations.gap_markup import collapse, html_text, make_row
from snowlight.sources.stations.model import (
    JsonScalar,
    Listing,
    ListingState,
    ParsedRow,
    ShapeError,
)
from snowlight.sources.stations.typed import parse_time, read_typed, rest_modified, rest_title

VARIANT = "wp-closings-articles"
EDIT_LAG = timedelta(hours=36)
"""An article changed later than this after it was published is stamped with its publication."""
_LIST_TITLE = re.compile(
    r"^\W*(?:updated?\s*:\s*)?school\s+(?:closures?|closings?|delays?|cancell?ations?)\b"
    r"|\bcauses?\s+school\s+(?:closures?|closings?|delays?)\b"
    r"|^\W*schools?\s+closed\b"
    r"|\bschools?\b(?:\W+[\w'-]+){0,4}?\W+announc\w*\W+closures?\b"
    r"|\blist\s+of\b.{0,40}\bschool\s+(?:closures?|closings?|cancell?ations?)\b",
    re.IGNORECASE,
)
"""Titles of a storm day's list article."""
_STORY_TITLE = re.compile(
    r"\b(?:schools?|classes|class)\b(?:\W+[\w'-]+){0,5}?\W+(?:closed|cancell?ed)\b"
    r"|\b(?:cancell?ed|cancels|cancel|cancell?ing|closes)\W+(?:[\w'-]+\W+){0,2}?"
    r"(?:schools?|classes|class)\b"
    r"|\bschools?\b(?:\W+[\w'-]+){0,4}?\W+closures?\b",
    re.IGNORECASE,
)
"""Titles of a story of one school's or district's closing."""
_NOT_A_CLOSING = re.compile(
    r"\b(?:possible|votes?|rally|bus|events?|homecoming|is\s+not|isn't|how|why|what|when"
    r"|consider(?:s|ing)?|plans?|budget)\b",
    re.IGNORECASE,
)
"""Words of a title about closings that does not announce one (a vote, a plan, a feature)."""
_SYNDICATED = re.compile(r"/(?:cnn[-/]|[a-z-]*cnn-|ap-|stacker-|national-world/)", re.IGNORECASE)
"""Paths of the wire and network stories a station's site carries (CNN's, the AP's,
Stacker's), whose titles can name school closings elsewhere."""
_CREDIT = re.compile(r"^\W*(?:[A-Z][^()\n]{0,80}?)?\(([^()\n]{2,30})\)\s*[-\u2014\u2013]")
"""A story's dateline credit: "LONDON (AP) -", "IDAHO FALLS, Idaho (KIFI) -", "(CNN) -"."""
OWN_CREDITS: dict[str, frozenset[str]] = {"localnews8.com": frozenset({"KIFI", "LOCAL NEWS 8"})}
"""The credits a station's own stories carry, by its site's host."""


def own_article(post: dict[str, Any]) -> bool:
    """Whether a REST post is the station's own story: not a wire or network one.

    Its link must not be a syndicated story's path, and its dateline must credit no
    outlet but the station (a story without a credit is the station's own).
    """
    link = post.get("link")
    if not isinstance(link, str) or _SYNDICATED.search(link):
        return False
    content = post.get("content")
    rendered = content.get("rendered") if isinstance(content, dict) else None
    if not isinstance(rendered, str):
        return False
    opening = collapse(html.unescape(re.sub(r"<[^>]+>", " ", rendered[:2000])))
    credit = _CREDIT.match(opening)
    if credit is None:
        return True
    host = (urlsplit(link).hostname or "").lower().removeprefix("www.")
    return collapse(credit.group(1)).upper() in OWN_CREDITS.get(host, frozenset())


def list_article(post: dict[str, Any]) -> bool:
    """Whether a REST post's title is a storm day's list article's."""
    title = html.unescape(rest_title(post))
    return _LIST_TITLE.search(title) is not None and _NOT_A_CLOSING.search(title) is None


def closings_article(post: dict[str, Any]) -> bool:
    """Whether a REST post is one of the station's own closings articles (list or story)."""
    if not own_article(post):
        return False
    title = html.unescape(rest_title(post))
    if _NOT_A_CLOSING.search(title) is not None:
        return False
    return _LIST_TITLE.search(title) is not None or _STORY_TITLE.search(title) is not None


def published(post: dict[str, Any]) -> datetime | None:
    """A REST post's ``date_gmt`` (UTC), when it has one."""
    value = post.get("date_gmt")
    return parse_time(value) if isinstance(value, str) else None


def _stamp(post: dict[str, Any]) -> datetime:
    modified = rest_modified(post)
    if modified is None:
        raise ShapeError("a closings article without its modified_gmt time")
    first = published(post)
    if first is not None and modified - first > EDIT_LAG:
        return first
    return modified


def _rows(post: dict[str, Any]) -> list[ParsedRow]:
    moment = _stamp(post)
    stamp = moment.strftime("%Y-%m-%dT%H:%M:%SZ")
    content = post.get("content")
    rendered = content.get("rendered") if isinstance(content, dict) else None
    if not isinstance(rendered, str):
        raise ShapeError("a closings article without its rendered text")
    title = html.unescape(rest_title(post))
    extra: dict[str, JsonScalar] = {
        "post_id": post.get("id") if isinstance(post.get("id"), int) else None,
        "link": post["link"] if isinstance(post.get("link"), str) else None,
        "title": title,
    }
    block = HTMLParser(f"<div>{rendered}</div>").css_first("div")
    if block is None:
        raise ShapeError("a closings article whose text is not HTML")
    text = collapse(block.text(deep=True, separator=" "))
    if not list_article(post):
        found = make_row(title, text, stamp, extra)
        return [found] if found is not None else []
    try:
        listing = read_typed(block, VARIANT, moment)
    except ShapeError:
        found = make_row(title, text, stamp, extra)
        return [found] if found is not None else []
    return [
        row.model_copy(update={"updated_text": stamp, "extra": {**row.extra, **extra}})
        for row in listing.rows
    ]


def parse(body: bytes) -> Listing:
    """Read a station's REST answer of closings articles (see the module docstring)."""
    try:
        data = json.loads(html_text(body))
    except ValueError as error:
        raise ShapeError(f"a REST answer that is not JSON: {error}") from error
    if not isinstance(data, list) or not all(isinstance(post, dict) for post in data):
        raise ShapeError("not a WordPress REST list of posts")
    if any("title" not in post or "link" not in post for post in data):
        raise ShapeError("a WordPress REST post without its title or link")
    rows: list[ParsedRow] = []
    times: list[datetime] = []
    for post in data:
        if closings_article(post):
            rows.extend(_rows(post))
            first = published(post)
            if first is not None:
                times.append(first)
    return Listing(
        variant=VARIANT,
        state=ListingState.POPULATED if rows else ListingState.EMPTY,
        rows=tuple(rows),
        dated_rows=True,
        list_updated_at=max(times) if times else None,
    )


def slice_body(body: bytes) -> bytes:
    """Keep only the station's closings articles, and only the fields the adapter reads
    (the ``wp-closings-articles-v2`` slice of :mod:`snowlight.sources.stations.history`)."""
    data = json.loads(html_text(body))
    kept = [
        {key: post[key] for key in ("id", "date_gmt", "modified_gmt", "link", "title", "content")}
        for post in data
        if isinstance(post, dict) and closings_article(post)
    ]
    return json.dumps(kept, ensure_ascii=False, separators=(",", ":")).encode()
