"""9&10 News (Heritage Broadcasting, northern Michigan): the Arc XP school closings source.

The closings page (``https://www.9and10news.com/weather/school-closings/``) is an
Arc XP Fusion page reading the content source ``weather-school-closings``, which
the site also answers at ``/pf/api/v3/content/fetch/weather-school-closings``.
Variants this adapter reads:

``heritage-arc-content``
    The source's answer: ``{"closing": [...], "lastUpdated": ..., "_id": ...}``, one
    object per organization, as the storm-day capture of 2023-02-07 14:06 UTC shows
    (130 of them)::

        {"name1": "Alanson Public Schools", "name2": "", "status": "Closed",
         "status2": "", "statuscode": "1", "entitytype": "Districts",
         "entitytypecode": "05", "city": "", "county": "Emmet", "state": "",
         "group": "", "comments": "", "updatetime": "02/07/2023 05:19am", "id": "4802"}

    ``name1`` is the name, ``status`` the status and ``updatetime`` the update
    text; every other field (``name2``, ``status2``, ``county``, ``entitytype`` and
    the rest) goes in ``raw_extra`` under its own name. With nothing listed the
    answer holds only the time the list was made and the cache id,
    ``{"lastUpdated": "09/27/2026 02:15am", "_id": ...}`` (live on 2026-09-26 and
    2026-09-27): the empty state, as is an empty ``closing`` list.

``heritage-arc-page``
    The page inlines the same object in
    ``Fusion.contentCache["weather-school-closings"]`` (the storm-day capture of
    2024-12-12 03:09 UTC holds 40 closings there) and is read the same way.

``heritage-bti-table``
    The page before the Arc site (captures of 2021): a server-written
    ``table.bti_closings`` ("School", "Location"), one row per organization, as the
    capture of 2021-02-05 08:07 UTC shows::

        <tr><td class="location"><span class="location_name">Baldwin Community</span>
            <span class="location_type">Districts</span></td>
          <td class="address"> </td>
          <td class="status"><span class="status_desc">Closed - Weather</span>
            <span class="last_updated" title="02/04/2021 07:16pm">Updated 8 hours ago</span>
          </td></tr>

    ``location_name`` is the name, ``status_desc`` the status and the
    ``last_updated`` title the update text; the ``location_type`` (when the row
    has one), a non-blank address and the relative time the page showed go in
    ``raw_extra`` (``location_type``, ``address``, ``updated_label``). The table is
    the schoolclosings.org list of the GTxcel ("RAYOS") WordPress theme, which
    KXLY's page also carried (captures of 2021 and 2022, read by
    :mod:`snowlight.sources.stations.blox` through :func:`read_bti`): there it sits
    in ``div.gtx-school-closings-page``, its rows have no ``location_type``, and
    with nothing listed the block holds only the sentence "No active school
    closings at this time." (KXLY's capture of 2021-02-15), the empty state. A
    table without rows has not been seen, so it raises
    :class:`~snowlight.sources.stations.model.ShapeError`.

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`.
"""

import json
from collections.abc import Mapping

from selectolax.parser import HTMLParser, Node

from snowlight.sources.stations.body import decode
from snowlight.sources.stations.model import JsonScalar, Listing, ParsedRow, ShapeError
from snowlight.sources.stations.regional import (
    document,
    extra_from,
    fusion_entry,
    html_text,
    json_body,
    listing,
    looks_like_json,
    node_text,
    row,
    text_field,
)

CONTENT = "heritage-arc-content"
PAGE = "heritage-arc-page"
TABLE = "heritage-bti-table"
SOURCE = "weather-school-closings"
_ANSWER_KEYS = frozenset({"lastUpdated", "_id", "closing"})
_ROW_KEYS = frozenset({"name1", "status", "updatetime"})
_TABLE = "table.bti_closings"
_BLOCK = "div.gtx-school-closings-page"
BTI_EMPTY = "No active school closings at this time."


def _closing(item: object) -> ParsedRow | None:
    if not isinstance(item, Mapping):
        raise ShapeError("a 9&10 closing is not an object")
    status = text_field(item, "status")
    if status is None:
        raise ShapeError(f"a 9&10 closing has no status (keys {sorted(item)[:12]})")
    return row(
        text_field(item, "name1") or "",
        status,
        text_field(item, "updatetime") or None,
        extra_from(item, _ROW_KEYS),
    )


def parse_content(data: object, variant: str = CONTENT) -> Listing:
    """Read the ``weather-school-closings`` answer."""
    if not isinstance(data, Mapping) or "lastUpdated" not in data:
        raise ShapeError("not a 9&10 school closings answer")
    unknown = sorted(set(data) - _ANSWER_KEYS)
    if unknown:
        raise ShapeError(f"a 9&10 closings answer holds fields not seen before: {unknown[:20]}")
    items = data.get("closing", [])
    if not isinstance(items, list):
        raise ShapeError("the 9&10 closings are not a list")
    rows: list[ParsedRow] = []
    skipped = 0
    for item in items:
        found = _closing(item)
        if found is None:
            skipped += 1
        else:
            rows.append(found)
    return listing(variant, rows, skipped=skipped)


def _one(tr: Node, selector: str) -> Node:
    found = tr.css(selector)
    if len(found) != 1:
        raise ShapeError(f"a 9&10 closings table row holds {len(found)} {selector}")
    return found[0]


def _table(table: Node) -> Listing:
    rows: list[ParsedRow] = []
    skipped = 0
    for tr in table.css("tbody tr"):
        stamp = _one(tr, "span.last_updated")
        updated = (stamp.attributes.get("title") or "").strip() or None
        types = tr.css("span.location_type")
        if len(types) > 1:
            raise ShapeError(f"a closings table row holds {len(types)} span.location_type")
        extra: dict[str, JsonScalar] = {"location_type": node_text(types[0])} if types else {}
        address = node_text(_one(tr, "td.address"))
        if address:
            extra["address"] = address
        if node_text(stamp):
            extra["updated_label"] = node_text(stamp)
        found = row(
            node_text(_one(tr, "span.location_name")),
            node_text(_one(tr, "span.status_desc")),
            updated,
            extra,
        )
        if found is None:
            skipped += 1
        else:
            rows.append(found)
    if not rows and not skipped:
        raise ShapeError("a 9&10 closings table without rows (its empty form has not been seen)")
    return listing(TABLE, rows, skipped=skipped)


def read_bti(text: str) -> Listing | None:
    """Read a page's schoolclosings.org table (or its empty block); None when it has neither.

    Raises:
        ShapeError: the page has the table or its block but it does not read cleanly.
    """
    tree = HTMLParser(text)
    table = tree.css_first(_TABLE)
    if table is not None:
        return _table(table)
    blocks = tree.css(_BLOCK)
    if not blocks:
        return None
    if len(blocks) == 1 and node_text(blocks[0]) == BTI_EMPTY:
        return listing(TABLE, [])
    raise ShapeError("a school closings block with neither its table nor its no-closings line")


def parse(body: bytes) -> Listing:
    """Read the 9&10 closings page or its content source's answer."""
    if looks_like_json(body):
        return parse_content(json_body(body))
    text = html_text(body)
    cached = fusion_entry(text, SOURCE)
    if cached is not None:
        return parse_content(cached[0], PAGE)
    bti = read_bti(text)
    if bti is not None:
        return bti
    raise ShapeError("not a 9&10 closings page (no school closings content cached)")


def slice_body(body: bytes) -> bytes:
    """Cut a page to its content cache's closings entry or its table; an answer stays whole."""
    found = parse(body)
    if found.variant == TABLE:
        return slice_bti(html_text(body))
    if found.variant != PAGE:
        return decode(body)
    cached = fusion_entry(html_text(body), SOURCE) or (None, None)
    cache = json.dumps({SOURCE: {"undefined": {"data": cached[0], "lastModified": cached[1]}}})
    return document(f"<script>Fusion.contentCache={cache};</script>")


def bti_markup(text: str) -> str:
    """Return a page's schoolclosings.org table, or its empty block, as markup."""
    tree = HTMLParser(text)
    table = tree.css_first(_TABLE)
    if table is not None:
        return table.html or ""
    block = tree.css_first(_BLOCK)
    return block.html or "" if block is not None else ""


def slice_bti(text: str) -> bytes:
    """Keep a page's schoolclosings.org table, or its empty block."""
    return document(bti_markup(text))
