"""Apptegy (Thrillshare) district live feeds: the posts a district sends to every channel at once.

An Apptegy district writes one post in its Thrillshare dashboard and sends it to its
website's live feed, its app's push notifications, text messages and Facebook at once
(each post's ``to_live_feed``, ``to_push_notifications``, ``to_sms``, ``to_facebook``).
On a snow day that is where the district says it: Fremont County Joint School District
#215 (Idaho) posted "SCHOOL CLOSURE. Due to hazardous conditions with blowing and drifting
snow, ALL schools in Fremont School District will be closed today (Tuesday, February 14)."
at 05:38 MST on 2023-02-14; American Falls, "School is canceled Monday, March 4, 2024, for
all American Falls schools due to current and forecasted conditions for hazardous roads";
Johnson County #1 (Wyoming), "Due to road conditions and inclement weather all Buffalo
School are on a One Hour Delay today Tuesday, February 27, 2024." The district's homepage
loads the feed from Thrillshare's content service by script
(``https://thrillshare-cmsv2.services.thrillshare.com/api/v4/o/<organization>/cms/live_feeds``,
named in the homepage's own state; no robots.txt on the host: 404, unrestricted), and the
same address answers the newest 20 posts as JSON, older pages by ``?page_no=``.

Variant this adapter reads:

``apptegy-live-feed``
    ``{"live_feeds": [post, ...], "meta": {...}}``. One row per approved post: ``raw_name``
    "Live feed" (the feed's own name; the post's ``author_name``, often the staff member
    who posted it, is a person's name and is neither read nor kept; the name is never read
    for proof: :data:`snowlight.sources.stations.notices.ORG_NAMED_VARIANTS`),
    ``raw_status`` the post's text reduced to plain text, ``raw_updated_text`` the time the
    server stamped it with (``time``, ISO 8601 with its offset), and ``raw_extra`` its
    ``post_id``, ``source`` and the channels it went to. ``{"live_feeds": []}`` is an empty
    feed. A post not approved (``approved`` false) is not shown on the feed, so it is skipped.

The feed keeps its old posts, so the rows are dated (``Listing.dated_rows``): the live
reader keeps a post only while it was published within ``fetch.TYPED_CURRENT`` of the
read, and the newest post's time is the list's own (``list_updated_at``): a feed nobody
has posted to since before the last winter is judged like any list last written then.
A district channel (:data:`snowlight.sources.stations.notices.GENERAL_CHANNEL_ADAPTERS`):
most posts are not closings, so a post proves the feed only when it announces one
(:mod:`snowlight.sources.stations.notices`); the feed's older posts are its dated history
(:mod:`snowlight.sources.stations.history`). Anything else raises
:class:`~snowlight.sources.stations.model.ShapeError`.
"""

import json
from datetime import UTC, datetime
from html import unescape
from typing import Any

from selectolax.parser import HTMLParser

from snowlight.sources.stations.gap_markup import collapse, html_text, make_row
from snowlight.sources.stations.model import (
    JsonScalar,
    Listing,
    ListingState,
    ParsedRow,
    ShapeError,
)
from snowlight.sources.stations.notices import weather_closing

VARIANT = "apptegy-live-feed"
CHANNELS = ("to_live_feed", "to_push_notifications", "to_sms", "to_facebook", "to_email")
"""The channels a post records it was sent to (kept with its row)."""


def plain(fragment: object) -> str:
    """A post's HTML text as plain text (line breaks and paragraphs become spaces)."""
    if not isinstance(fragment, str):
        return ""
    if "<" not in fragment:
        return collapse(unescape(fragment))
    tree = HTMLParser(f"<div>{fragment}</div>")
    node = tree.css_first("div")
    return collapse(node.text(deep=True, separator=" ")) if node is not None else ""


def post_time(post: dict[str, Any]) -> datetime:
    """The time the server stamped a post with (UTC, whole seconds)."""
    stamp = post.get("time")
    if not isinstance(stamp, str):
        raise ShapeError("a live feed post without its time")
    try:
        moment = datetime.fromisoformat(stamp)
    except ValueError as error:
        raise ShapeError(f"a live feed post whose time is not ISO 8601: {stamp!r}") from error
    if moment.tzinfo is None:
        raise ShapeError(f"a live feed post whose time names no offset: {stamp!r}")
    return moment.astimezone(UTC).replace(microsecond=0)


FEED_NAME = "Live feed"
"""Every post's row name: the feed's, never the posting staff member's."""


def _row(post: object) -> ParsedRow | None:
    if not isinstance(post, dict) or not isinstance(post.get("id"), int):
        raise ShapeError("a live feed post without a numeric id")
    if "status" not in post:
        raise ShapeError("a live feed post without its text")
    post_time(post)
    if post.get("approved") is False:
        return None
    name = FEED_NAME
    extra: dict[str, JsonScalar] = {
        "post_id": post["id"],
        "source": post["source"] if isinstance(post.get("source"), str) else None,
        "channels": ",".join(key.removeprefix("to_") for key in CHANNELS if post.get(key) is True),
    }
    return make_row(name, plain(post["status"]), str(post["time"]), extra)


def parse(body: bytes) -> Listing:
    """Read a district's Thrillshare live feed (see the module docstring)."""
    try:
        data = json.loads(html_text(body))
    except ValueError as error:
        raise ShapeError(f"a live feed answer that is not JSON: {error}") from error
    if not isinstance(data, dict) or not isinstance(data.get("live_feeds"), list):
        raise ShapeError("not a Thrillshare live feed answer (no live_feeds list)")
    posts = data["live_feeds"]
    rows: list[ParsedRow] = []
    skipped = 0
    for post in posts:
        row = _row(post)
        if row is None:
            skipped += 1
        else:
            rows.append(row)
    newest = max((post_time(post) for post in posts), default=None)
    return Listing(
        variant=VARIANT,
        state=ListingState.POPULATED if rows else ListingState.EMPTY,
        rows=tuple(rows),
        skipped_rows=skipped,
        list_updated_at=newest,
        dated_rows=True,
    )


def slice_body(body: bytes) -> bytes:
    """Keep the first post of a page that announces a closing or a delay for weather or an emergency
    (fixtures;
    the ``apptegy-feed-closings-v2`` slice: as ``v1``, without the post's ``author_name``).

    A feed lists its newest posts first, so this is the page's newest such post (by the
    rule a feed's dated history proves with,
    :func:`snowlight.sources.stations.notices.weather_closing`); the page's other posts and
    every field the adapter does not read are dropped, and what is kept is written back as
    compact JSON, so the slice is deterministic. One post: its time is the fixture's.
    """
    data = json.loads(html_text(body))
    for post in data.get("live_feeds", []):
        if isinstance(post, dict) and weather_closing(plain(post.get("status"))):
            kept = {
                key: post[key]
                for key in ("id", "status", "time", "approved", "source", *CHANNELS)
                if key in post
            }
            return json.dumps(
                {"live_feeds": [kept]}, ensure_ascii=False, separators=(",", ":")
            ).encode()
    return json.dumps({"live_feeds": []}, separators=(",", ":")).encode()
