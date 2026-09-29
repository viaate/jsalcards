"""Miami-Dade County Public Schools: the district's public alerts file.

The district's homepage (``https://www.dadeschools.net/``, an Angular app) shows its
urgent notices from ``https://mainapi.dadeschools.net/api/v1/alerts/`` (the app's
``API_1_ALERTS``), a JSON file of alert items that the page draws only when an item's
``visible`` is true (its template's ``ngIf: 1==e.visible``). On 2026-09-27 the file
held three items, none visible; the Wayback Machine's capture of 2024-10-09 14:41 UTC
holds, visible, "Hurricane Milton: All M-DCPS schools, as well as Region and District
offices will be CLOSED on Wednesday, October 9 and Thursday, October 10."

Variant this adapter reads:

``dadeschools-alerts``
    ``{"items": [{"id", "clients": ["Web", "Mobile"], "type", "visible", "imgSrc",
    "imgAlt", "title", "body", "innerHTML", "link"}, ...]}``.

Each visible item is one row: ``raw_name`` its ``title`` ("Hurricane Milton"; the file
names no school, and the station's ``leaids`` say whose it is), ``raw_status`` its
``body`` (else the text of its ``innerHTML``), no ``raw_updated_text`` (the items carry
no time), and ``raw_extra`` ``alert_id``, ``type``, ``clients`` (comma-joined) and
``link``. Hidden items are never rows (they are kept in the file after their day). A
visible item with neither title nor text is a skipped row. A file with no visible item
is an empty list. Anything else raises
:class:`~snowlight.sources.stations.model.ShapeError`: a body that is not JSON, an
object without the ``items`` list, or an item without a numeric ``id`` or a boolean
``visible``.
"""

import json
from typing import Any

from selectolax.parser import HTMLParser

from snowlight.sources.stations.body import decode
from snowlight.sources.stations.gap_markup import collapse, document, make_listing, make_row
from snowlight.sources.stations.model import JsonScalar, Listing, ParsedRow, ShapeError

VARIANT = "dadeschools-alerts"


def _text(item: dict[str, Any], key: str) -> str:
    value = item.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ShapeError(f"alert field {key!r} is not text: {value!r}"[:200])
    return collapse(value)


def _html_text(item: dict[str, Any]) -> str:
    markup = _text(item, "innerHTML")
    if not markup:
        return ""
    tree = HTMLParser(document(markup).decode())
    return collapse(tree.body.text(separator=" ")) if tree.body is not None else ""


def _row(item: object) -> ParsedRow | None:
    if not isinstance(item, dict):
        raise ShapeError("an alert item is not an object")
    alert_id = item.get("id")
    if isinstance(alert_id, bool) or not isinstance(alert_id, int):
        raise ShapeError(f"an alert item has no numeric id: {alert_id!r}")
    visible = item.get("visible")
    if not isinstance(visible, bool):
        raise ShapeError(f"alert item {alert_id} has no boolean 'visible'")
    if not visible:
        return None
    clients = item.get("clients")
    names = [c for c in clients if isinstance(c, str)] if isinstance(clients, list) else []
    extra: dict[str, JsonScalar] = {
        "alert_id": alert_id,
        "type": _text(item, "type") or None,
        "clients": ",".join(names) or None,
        "link": _text(item, "link") or None,
    }
    title = _text(item, "title")
    text = _text(item, "body") or _html_text(item)
    return make_row(title or text, text if title else "", None, extra)


def parse(body: bytes) -> Listing:
    """Read one answer of the district's alerts file: the items the homepage shows."""
    try:
        data = json.loads(decode(body))
    except (ValueError, UnicodeDecodeError) as error:
        raise ShapeError(f"not a JSON answer: {error}") from error
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ShapeError("the answer has no items list: not the district's alerts file")
    rows: list[ParsedRow] = []
    skipped = 0
    for item in data["items"]:
        shown = isinstance(item, dict) and item.get("visible") is True
        row = _row(item)
        if row is not None:
            rows.append(row)
        elif shown:
            skipped += 1
    return make_listing(VARIANT, rows, skipped=skipped)
