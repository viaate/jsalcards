"""WRAL's closings (Raleigh-Durham): the closings API its page application reads.

WRAL's closings page (``https://www.wral.com/weather/closings/``) is a script
application that names its API in ``<meta name="closings-api"
content="https://api.wral.com/closings">`` and reads the active closings from
``{api}/v1/``. Variants this adapter reads:

``wral-api``
    The API's answer: ``{"count": N, "closings": [...]}``. The page's own renderer
    (``closings/v0.1.13/assets/index-*.js``, read 2026-09-27) shows each closing as
    ``orgDisplayName`` (else ``orgName``), ``statusText``, ``county`` and
    ``comment``, so those are the row's name and status; every other field
    (``county``, ``category``, ``comment``, ``statusCode`` and the rest) goes in
    ``raw_extra`` under its own name. ``count`` is the declared count and must
    equal the closings read. No closings is the empty state (live since the
    application's release: ``{"count":0,"closings":[]}``).

``wral-app-page``
    The application page itself: it holds no list and names its API in the
    ``closings-api`` meta tag. A
    :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED` listing that
    follows ``{api}/v1/``.

``wral-page-table``
    The page before the application (captures of 2021 to 2025, also served as
    ``?v3_show_only_content=1``): the server wrote the list into one
    ``table.responsive-table`` ("Organization", "Status(es)"), one row per
    organization, as the storm-day capture of 2022-01-21 15:26 UTC shows (485 of
    them)::

        <tr><td data-title="Organization">1st Bapt Academy/Raeford</td>
            <td data-title="Status">Closed</td></tr>

    The ``Organization`` cell is the name and the ``Status`` cell the status. Every
    row must hold exactly those two cells. A table without rows has not been seen,
    so it raises :class:`~snowlight.sources.stations.model.ShapeError`.

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`.
"""

import re
from collections.abc import Mapping

from selectolax.parser import HTMLParser, Node

from snowlight.sources.stations.body import decode
from snowlight.sources.stations.model import Listing, ParsedRow, ShapeError
from snowlight.sources.stations.regional import (
    deferred,
    document,
    extra_from,
    html_text,
    json_body,
    listing,
    looks_like_json,
    node_text,
    row,
    text_field,
)

API = "wral-api"
PAGE = "wral-app-page"
TABLE = "wral-page-table"
_TABLE = "table.responsive-table"
_CELLS = ("Organization", "Status")
_META = re.compile(r"<meta\s+name=\"closings-api\"\s+content=\"(https://[^\"]+)\"", re.IGNORECASE)
_ROW_KEYS = frozenset({"orgDisplayName", "orgName", "statusText"})


def _row(item: object) -> ParsedRow | None:
    if not isinstance(item, Mapping):
        raise ShapeError("a WRAL closing is not an object")
    status = text_field(item, "statusText")
    if status is None:
        raise ShapeError(f"a WRAL closing has no statusText (keys {sorted(item)[:12]})")
    name = text_field(item, "orgDisplayName") or text_field(item, "orgName") or ""
    extra = extra_from(item, _ROW_KEYS)
    if text_field(item, "orgDisplayName") and item.get("orgName") is not None:
        extra["orgName"] = text_field(item, "orgName")
    return row(name, status, None, extra)


def parse_api(data: object) -> Listing:
    """Read the API's answer (``wral-api``)."""
    if not isinstance(data, Mapping) or "closings" not in data:
        raise ShapeError("not a WRAL closings answer")
    items, count = data["closings"], data.get("count")
    if not isinstance(items, list):
        raise ShapeError("the WRAL closings are not a list")
    if count is not None and (isinstance(count, bool) or not isinstance(count, int)):
        raise ShapeError(f"the WRAL count is not a number: {count!r}")
    rows: list[ParsedRow] = []
    skipped = 0
    for item in items:
        found = _row(item)
        if found is None:
            skipped += 1
        else:
            rows.append(found)
    return listing(API, rows, skipped=skipped, declared=count)


def _table(table: Node) -> Listing:
    rows: list[ParsedRow] = []
    skipped = 0
    for tr in table.css("tbody tr"):
        cells = tr.css("td")
        titles = tuple(td.attributes.get("data-title") for td in cells)
        if titles != _CELLS:
            raise ShapeError(f"a WRAL closings table row holds the cells {titles}")
        found = row(node_text(cells[0]), node_text(cells[1]), None, {})
        if found is None:
            skipped += 1
        else:
            rows.append(found)
    if not rows and not skipped:
        raise ShapeError("a WRAL closings table without rows (its empty form has not been seen)")
    return listing(TABLE, rows, skipped=skipped)


def parse(body: bytes) -> Listing:
    """Read WRAL's closings API answer, its application page, or the older page's table."""
    if looks_like_json(body):
        return parse_api(json_body(body))
    text = html_text(body)
    meta = _META.search(text)
    if meta is not None:
        return deferred(PAGE, (meta.group(1).rstrip("/") + "/v1/",))
    tables = HTMLParser(text).css(_TABLE)
    if len(tables) == 1:
        return _table(tables[0])
    raise ShapeError("not a WRAL closings answer or application page")


def slice_body(body: bytes) -> bytes:
    """Cut a body to what the adapter reads: the page keeps its API meta tag."""
    found = parse(body)
    if found.variant == PAGE:
        meta = _META.search(html_text(body))
        return document(meta.group(0) if meta is not None else "")
    if found.variant == TABLE:
        table = HTMLParser(html_text(body)).css_first(_TABLE)
        return document((table.html or "") if table is not None else "")
    return decode(body)
