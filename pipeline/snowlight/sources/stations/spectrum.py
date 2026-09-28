"""Spectrum News 1's closings: one JSON file per viewing area.

Each Spectrum News 1 region's closings page
(``https://spectrumlocalnews.com/{state}/{region}/weather/closings``) carries the
region's id on its body (``data-ravenid="54e4ffc9ceafc43649b4dae9"``), and its
script (``/etc/designs/news/clientlibs/js/weather/closings.min.js``) reads
``/services/closings.{ravenid}.json``. Variants this adapter reads:

``spectrum-json``
    The file: a list of organization types, each with its closings::

        [{"orgType": "Schools", "closings": [{"accountName": "...", "status": "..."}]}]

    (the shape the page's script renders, per the first-hand check of 2026-09-26).
    Each closing is a row: ``accountName`` is the name and ``status`` the status;
    the organization type goes in ``raw_extra["orgType"]`` and every other field
    of the closing in ``raw_extra`` under its own name. An empty list (``[ ]``,
    live on 2026-09-27 in all eleven regions) is the empty state (the page then
    says "There are no closings or delays active in this Spectrum News viewing
    area.").

``spectrum-page``
    The region's page: it holds no list. A
    :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED` listing that
    follows ``/services/closings.{ravenid}.json``.

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`.
"""

import re
from collections.abc import Mapping

from snowlight.sources.stations.body import decode
from snowlight.sources.stations.model import Listing, ParsedRow, ShapeError
from snowlight.sources.stations.regional import (
    collapse,
    deferred,
    document,
    extra_from,
    html_text,
    json_body,
    listing,
    looks_like_json,
    row,
    text_field,
)

FILE = "spectrum-json"
PAGE = "spectrum-page"
_RAVEN = re.compile(r"\bdata-ravenid=\"([0-9a-f]{24})\"")
_ROW_KEYS = frozenset({"accountName", "status"})


def parse_file(data: object) -> Listing:
    """Read a region's closings file (``spectrum-json``)."""
    if not isinstance(data, list):
        raise ShapeError("the Spectrum closings file is not a list")
    rows: list[ParsedRow] = []
    skipped = 0
    for group in data:
        if not isinstance(group, Mapping) or not isinstance(group.get("closings"), list):
            raise ShapeError("a Spectrum organization type has no closings list")
        kind = text_field(group, "orgType")
        for item in group["closings"]:
            if not isinstance(item, Mapping):
                raise ShapeError("a Spectrum closing is not an object")
            status = text_field(item, "status")
            if status is None:
                raise ShapeError(f"a Spectrum closing has no status (keys {sorted(item)[:12]})")
            extra = extra_from(item, _ROW_KEYS)
            if kind is not None:
                extra["orgType"] = kind
            found = row(text_field(item, "accountName") or "", status, None, extra)
            if found is None:
                skipped += 1
            else:
                rows.append(found)
    return listing(FILE, rows, skipped=skipped)


def parse(body: bytes) -> Listing:
    """Read a Spectrum News region's closings file or its page."""
    if looks_like_json(body):
        return parse_file(json_body(body))
    text = html_text(body)
    raven = _RAVEN.search(text)
    if raven is None or "closings" not in text:
        raise ShapeError("not a Spectrum News closings file or page")
    return deferred(PAGE, (f"/services/closings.{collapse(raven.group(1))}.json",))


def slice_body(body: bytes) -> bytes:
    """Cut a body to what the adapter reads: the page keeps its region id."""
    found = parse(body)
    if found.variant == PAGE:
        raven = _RAVEN.search(html_text(body))
        mark = raven.group(0) if raven is not None else ""
        return document(f"<div {mark}>closings</div>")
    return decode(body)
