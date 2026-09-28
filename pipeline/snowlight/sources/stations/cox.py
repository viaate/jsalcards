"""Cox Media Group stations' school closings: the Arc XP ``closing`` content source.

The six Cox stations with a closings page (WSB, WFXT, WSOC, WHIO, WPXI, KIRO)
run Arc XP Fusion sites. The page (``/weather/school-closings/``) renders a table
from the content source ``closing``, which the site also answers at
``/pf/api/v3/content/fetch/closing?_website=cmg-tv-100x0``. Variants this adapter
reads:

``cox-arc-content``
    The content source's answer: ``{"totalClosings": N, "closings": [...], "_id": ...}``.
    ``totalClosings`` is the declared count; no closings is the empty state (live
    at all six stations on 2026-09-27).

``cox-arc-page``
    The page, which inlines the same object in ``Fusion.contentCache["closing"]``;
    read the same way, with the cache entry's ``lastModified`` as the listing's
    ``declared_at``.

Each closing is ``{"response": {"name", "county", "status_code",
"status_code_display", "status", "comments", "start_date", "end_date"}}`` (seen in
the storm-day captures of WSB, WSOC, WHIO, WPXI and KIRO, 2025 and 2026). The page
shows it as a table row: Name (``name``), County, Date (``end_date``), Status
(``status_code_display``, a coarse code label: "Closed", "Open" or "Other") and
Description (``status``, the posting's own words, e.g. "Closed Through Monday").
A row's name is ``name`` and its status is ``status`` (``status_code_display``
when a posting has no words of its own); every other field is kept in
``raw_extra`` by its own name. A posting has no time of its own, so no row has
update text; the page's cache time is the listing's ``declared_at``.

A closing in any other shape raises
:class:`~snowlight.sources.stations.model.ShapeError` naming the fields it holds,
rather than being read by guesswork. Anything else raises it too.
"""

import json
from collections.abc import Mapping
from datetime import UTC, datetime

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

CONTENT = "cox-arc-content"
PAGE = "cox-arc-page"
SOURCE = "closing"


FIELDS = frozenset(
    {
        "name",
        "county",
        "status_code",
        "status_code_display",
        "status",
        "comments",
        "start_date",
        "end_date",
    }
)
_READ = frozenset({"name", "status"})


def _row(item: object) -> ParsedRow | None:
    posting = item.get("response") if isinstance(item, Mapping) and len(item) == 1 else None
    if not isinstance(posting, Mapping) or not _READ <= set(posting) <= FIELDS:
        keys = sorted(item)[:20] if isinstance(item, Mapping) else type(item).__name__
        inner = sorted(posting)[:20] if isinstance(posting, Mapping) else None
        raise ShapeError(f"a Cox closing's fields have not been seen before: {keys} {inner}")
    status = text_field(posting, "status") or text_field(posting, "status_code_display") or ""
    return row(text_field(posting, "name") or "", status, None, extra_from(posting, _READ))


def parse_content(data: object, variant: str = CONTENT) -> Listing:
    """Read the ``closing`` content source's answer."""
    if not isinstance(data, Mapping) or "closings" not in data or "totalClosings" not in data:
        raise ShapeError("not a Cox closing content answer")
    items, total = data["closings"], data["totalClosings"]
    if not isinstance(items, list) or isinstance(total, bool) or not isinstance(total, int):
        raise ShapeError("the Cox closings are not a list with a count")
    rows = [found for item in items if (found := _row(item)) is not None]
    return listing(variant, rows, skipped=len(items) - len(rows), declared=total)


def parse(body: bytes) -> Listing:
    """Read a Cox closings page or its content source's answer."""
    if looks_like_json(body):
        return parse_content(json_body(body))
    cached = fusion_entry(html_text(body), SOURCE)
    if cached is None:
        raise ShapeError("not a Cox closings page (no closing content cached)")
    data, modified = cached
    found = parse_content(data, PAGE)
    if modified is None:
        return found
    when = datetime.fromtimestamp(modified // 1000, tz=UTC)
    return Listing.model_validate({**found.model_dump(), "declared_at": when})


def slice_body(body: bytes) -> bytes:
    """Cut a page to its content cache's ``closing`` entry; an answer stays whole."""
    found = parse(body)
    if found.variant != PAGE:
        return decode(body)
    cached = fusion_entry(html_text(body), SOURCE) or (None, None)
    entry = {"data": cached[0], "lastModified": cached[1]}
    cache = json.dumps({SOURCE: {"undefined": entry}})
    return document(f"<script>Fusion.contentCache={cache};</script>")
