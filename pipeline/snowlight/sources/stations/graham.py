"""Graham Media Group stations' school closings: the Arc XP ``school-closings`` content source.

WDIV (Detroit) and WSLS (Roanoke) run Arc XP Fusion sites whose closings page
(``/school_closings/``, ``/school-closings/``) renders the content source
``school-closings``, which the site also answers at
``/pf/api/v3/content/fetch/school-closings?_website={site}``. Variants this
adapter reads:

``graham-arc-content``
    The content source's answer: ``{"schools": [...], "timestamp": <epoch s>
    [, "time_from_origin": "Sunday, August 16, 2026 12:17:52 PM EDT"], "_id": ...}``.
    No schools is the empty state (live at both stations on 2026-09-27; the page
    then says "There are currently no active closings or delays."). The
    ``time_from_origin`` text, when present, is the update text of an entry
    without its own.

``graham-arc-page``
    The page, which inlines the same object in ``Fusion.contentCache["school-closings"]``.

A school entry (seen in storm-day captures of WDIV, February 2025, and WSLS,
February 2025 and 2026) always holds ``id``, ``name_one``, ``category``,
``status_name_one``, ``status_two_name_one`` and ``updated``; WDIV's also hold
``name_two`` (a parent body, e.g. "**Archdiocese of Detroit"), ``county``,
``cat_code``, ``homepage``, ``forced_status_name``, ``status_code``,
``status_code_two``, ``expiration`` and ``active_phrase``. The page shows each as
a card: ``name_one`` as its heading, ``status_name_one`` under it, then
``status_two_name_one`` when set (at WDIV a second status such as "See School
Website"; at WSLS a summary line "Schools: <name> - <status>"), then "Last
updated:" and ``updated`` (which the page reads as UTC). A row's name is
``name_one``, its status ``status_name_one``, its update text ``updated`` (with
``raw_extra["updated_zone"]`` "UTC", as the page reads it; the answer's
``time_from_origin`` for an entry without one); every other field is kept in
``raw_extra`` by its own name.

An entry in any other shape raises
:class:`~snowlight.sources.stations.model.ShapeError` naming the fields it holds,
rather than being read by guesswork. Anything else raises it too.
"""

import json
from collections.abc import Mapping

from snowlight.sources.stations.body import decode
from snowlight.sources.stations.model import Listing, ParsedRow, ShapeError
from snowlight.sources.stations.regional import (
    document,
    extra_from,
    fusion_entry,
    html_text,
    json_body,
    listing,
    looks_like_json,
    row,
    text_field,
)

CONTENT = "graham-arc-content"
PAGE = "graham-arc-page"
SOURCE = "school-closings"


REQUIRED = frozenset(
    {"id", "name_one", "category", "status_name_one", "status_two_name_one", "updated"}
)
OPTIONAL = frozenset(
    {
        "name_two",
        "county",
        "cat_code",
        "homepage",
        "forced_status_name",
        "status_code",
        "status_code_two",
        "expiration",
        "active_phrase",
    }
)
_READ = frozenset({"name_one", "status_name_one", "updated"})


def _row(item: object, updated: str | None) -> ParsedRow | None:
    if not isinstance(item, Mapping) or not REQUIRED <= set(item) <= REQUIRED | OPTIONAL:
        keys = sorted(item)[:20] if isinstance(item, Mapping) else type(item).__name__
        raise ShapeError(f"a Graham school entry's fields have not been seen before: {keys}")
    status = text_field(item, "status_name_one") or ""
    own = text_field(item, "updated")
    extra = extra_from(item, _READ)
    if own:
        extra["updated_zone"] = "UTC"
    return row(text_field(item, "name_one") or "", status, own or updated, extra)


def parse_content(data: object, variant: str = CONTENT) -> Listing:
    """Read the ``school-closings`` content source's answer."""
    if not isinstance(data, Mapping) or not isinstance(data.get("schools"), list):
        raise ShapeError("not a Graham school-closings answer")
    if "timestamp" not in data:
        raise ShapeError("a Graham school-closings answer without its timestamp")
    stamp = data.get("time_from_origin")
    updated = stamp if isinstance(stamp, str) and stamp.strip() else None
    items = data["schools"]
    rows = [found for item in items if (found := _row(item, updated)) is not None]
    return listing(variant, rows, skipped=len(items) - len(rows))


def parse(body: bytes) -> Listing:
    """Read a Graham closings page or its content source's answer."""
    if looks_like_json(body):
        return parse_content(json_body(body))
    cached = fusion_entry(html_text(body), SOURCE)
    if cached is None:
        raise ShapeError("not a Graham closings page (no school-closings content cached)")
    return parse_content(cached[0], PAGE)


def slice_body(body: bytes) -> bytes:
    """Cut a page to its content cache's ``school-closings`` entry; an answer stays whole."""
    found = parse(body)
    if found.variant != PAGE:
        return decode(body)
    cached = fusion_entry(html_text(body), SOURCE) or (None, None)
    cache = json.dumps({SOURCE: {"undefined": {"data": cached[0], "lastModified": cached[1]}}})
    return document(f"<script>Fusion.contentCache={cache};</script>")
