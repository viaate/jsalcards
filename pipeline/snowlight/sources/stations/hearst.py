"""Hearst Television closings pages (``https://www.{station}.com/weather/closings``).

Every Hearst station site serves the same page template, which has changed over
the years. Variants this adapter reads (the ``variant`` of each listing):

``hearst-ibsys``
    The ibsys (ibPublish) page (seen in captures from 2014 and 2015): the whole
    list is a JSON argument to a script call, bucketed by first letter::

        ibsys.htvClosings.init({"f": {"count": 3, "institutions": [
            {"updateTimestamp": "2014-01-05T13:27:00.000-06:00",
             "status": "Monday: Closed", "address": "Fort Dodge / Webster / IA",
             "name": "Ft. Dodge Public/Parochial Schools"}, ...]},
          ..., "totalCount": 203});

    Rows are kept in the order the object holds them (bucket by bucket, as the
    page's script receives them). ``updateTimestamp`` is the row's
    ``raw_updated_text``; ``address`` ("City / County / ST"), ``emailListKey`` and
    the bucket key are kept in ``raw_extra``. Each bucket's ``count`` must match
    its institutions and ``totalCount`` their sum, or the page is a shape error.

``hearst-rows``
    Server-rendered rows (seen in captures from 2023 to January 2026)::

        <div class="weather-closings-data">
          <div class="weather-closings-data-noresults hidden">...</div>
          <div class="weather-closings-data-item" data-name="Academie Lafayette" data-count="1">
            <h2 class="weather-closings-data-name">Academie Lafayette</h2>
            <div class="weather-closings-data-location">Jackson, Kansas City, MO<br></div>
            <div class="weather-closings-data-status">
              <ul class="weather-closings-data-status-list">
                <li class="weather-closings-data-status-list-item">Closed</li>
                <li class="weather-closings-data-status-list-item">Updated: 1/7/2025 4:41:31 PM</li>
              </ul>
            </div>
          </div> ...

    The status is either plain text ("Friday Morning: Two Hour Delay") or a list;
    list items are kept in order, joined with " | ", except an item that starts
    "Updated:", which becomes the row's ``raw_updated_text``. The location text
    ("County, City, ST") is kept in ``raw_extra["location"]``; an organization
    with several locations lists them split by ``<br>``, kept in order and joined
    with " | ". A page
    with the container and no rows is empty only when it shows the site's own
    no-closings block; anything else is a shape error.

``hearst-next``
    The Next.js site (seen from February 2026): the list is a JSON object,
    ``"closingsData": {"head": {...}, "closings": [...], "total": n}``, inside the
    page's React Server Component payload (``self.__next_f.push([1, "..."])``
    script chunks). Each closing gives ``name``, ``closure.status``,
    ``closure.update_time`` and more; the rest is kept in ``raw_extra``, nested
    values as JSON text. ``"closings": []`` is the empty state.

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`.
"""

import json
import re
from collections.abc import Mapping
from html import unescape

from selectolax.parser import HTMLParser, Node

from snowlight.sources.stations.body import decode
from snowlight.sources.stations.model import (
    JsonScalar,
    Listing,
    ListingState,
    ParsedRow,
    ShapeError,
)

_IBSYS = "ibsys.htvClosings.init("
_IBSYS_TOTAL = "totalCount"
_PUSH = re.compile(rb"<script>self\.__next_f\.push\((\[.*?\])\)</script>", re.DOTALL)
_KEY = '"closingsData":'
_CONTAINER = re.compile(rb'<div class="weather-closings-data">')
_DIV = re.compile(rb"<(/?)div\b", re.IGNORECASE)
_SPACE = re.compile(r"\s+")
_UPDATED = re.compile(r"^updated\s*:\s*", re.IGNORECASE)
_BREAK = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]*>")
SEPARATOR = " | "


def _text(node: Node | None) -> str:
    if node is None:
        return ""
    return _SPACE.sub(" ", node.text(separator=" ")).strip()


def _locations(node: Node | None) -> str:
    """Return a location block's lines (split at ``<br>``), joined with the separator."""
    if node is None:
        return ""
    lines = []
    for piece in _BREAK.split(node.html or ""):
        text = _SPACE.sub(" ", unescape(_TAG.sub(" ", piece))).strip()
        if text:
            lines.append(text)
    return SEPARATOR.join(lines)


def _row_from_item(item: Node) -> ParsedRow | None:
    name = (
        _text(item.css_first(".weather-closings-data-name"))
        or _SPACE.sub(" ", item.attributes.get("data-name") or "").strip()
    )
    if not name:
        return None
    status_node = item.css_first(".weather-closings-data-status")
    if status_node is None:
        raise ShapeError(f"row {name!r} has no status block")
    entries = [_text(li) for li in status_node.css(".weather-closings-data-status-list-item")]
    updated: str | None = None
    if entries:
        kept = []
        for entry in entries:
            if _UPDATED.match(entry) and updated is None:
                updated = _UPDATED.sub("", entry)
            elif entry:
                kept.append(entry)
        status = SEPARATOR.join(kept)
    else:
        status = _text(status_node)
    extra: dict[str, JsonScalar] = {
        "location": _locations(item.css_first(".weather-closings-data-location")),
    }
    for attribute in ("data-name", "data-count"):
        value = item.attributes.get(attribute)
        if value is not None:
            extra[attribute] = value
    return ParsedRow(name=name, status=status, updated_text=updated, extra=extra)


def parse_rows(html: bytes) -> Listing:
    """Read the server-rendered ``hearst-rows`` page."""
    tree = HTMLParser(html.decode("utf-8", errors="replace"))
    container = tree.css_first("div.weather-closings-data")
    if container is None:
        raise ShapeError("no weather-closings-data container")
    items = container.css("div.weather-closings-data-item")
    rows: list[ParsedRow] = []
    skipped = 0
    for item in items:
        row = _row_from_item(item)
        if row is None:
            skipped += 1
        else:
            rows.append(row)
    if rows:
        return Listing(
            variant="hearst-rows",
            state=ListingState.POPULATED,
            rows=tuple(rows),
            skipped_rows=skipped,
        )
    if skipped:
        raise ShapeError("every row on the page is missing its name")
    notice = tree.css_first(".weather-closings-data-noclosings")
    if notice is not None and "hidden" not in (notice.attributes.get("class") or "").split():
        return Listing(variant="hearst-rows", state=ListingState.EMPTY, rows=())
    raise ShapeError("the closings container has no rows and no visible no-closings notice")


def _payload(html: bytes) -> str:
    parts: list[str] = []
    for match in _PUSH.finditer(html):
        try:
            item = json.loads(match.group(1))
        except ValueError as error:
            raise ShapeError(f"a Next.js payload chunk is not JSON: {error}") from error
        if isinstance(item, list) and len(item) == 2 and item[0] == 1 and isinstance(item[1], str):  # noqa: PLR2004
            parts.append(item[1])
    return "".join(parts)


def _closings_object(payload: str) -> Mapping[str, object]:
    start = payload.find(_KEY)
    if start < 0:
        raise ShapeError("the Next.js payload has no closingsData")
    try:
        data, _end = json.JSONDecoder().raw_decode(payload, start + len(_KEY))
    except ValueError as error:
        raise ShapeError(f"closingsData is not complete JSON: {error}") from error
    if not isinstance(data, Mapping) or not isinstance(data.get("closings"), list):
        raise ShapeError("closingsData has no closings list")
    head = data.get("head")
    if isinstance(head, Mapping) and head.get("success") is False:
        raise ShapeError(f"closingsData reports failure: {head}")
    return data


def _flat(value: object) -> JsonScalar:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _row_from_closing(closing: object) -> ParsedRow | None:
    if not isinstance(closing, Mapping):
        raise ShapeError("a closing is not an object")
    name = closing.get("name")
    closure = closing.get("closure")
    if not isinstance(closure, Mapping):
        raise ShapeError(f"closing {name!r} has no closure object")
    status, updated = closure.get("status"), closure.get("update_time")
    if not isinstance(status, str) or (updated is not None and not isinstance(updated, str)):
        raise ShapeError(f"closing {name!r} has no status text")
    if not isinstance(name, str) or not name.strip():
        return None
    extra: dict[str, JsonScalar] = {
        str(key): _flat(value) for key, value in closing.items() if key not in {"name", "closure"}
    }
    for key, value in closure.items():
        if key not in {"status", "update_time"}:
            extra[f"closure.{key}"] = _flat(value)
    return ParsedRow(
        name=_SPACE.sub(" ", name).strip(),
        status=status.strip(),
        updated_text=updated.strip() if updated is not None else None,
        extra=extra,
    )


def parse_next(html: bytes) -> Listing:
    """Read the Next.js ``hearst-next`` page."""
    data = _closings_object(_payload(html))
    closings = data["closings"]
    if not isinstance(closings, list):  # pragma: no cover - _closings_object checked it
        raise ShapeError("closingsData has no closings list")
    rows: list[ParsedRow] = []
    skipped = 0
    for closing in closings:
        row = _row_from_closing(closing)
        if row is None:
            skipped += 1
        else:
            rows.append(row)
    if skipped and not rows:
        raise ShapeError("every closing is missing its name")
    total = data.get("total")
    declared = (
        total if isinstance(total, int) and not isinstance(total, bool) and total >= 0 else None
    )
    return Listing(
        variant="hearst-next",
        state=ListingState.POPULATED if rows else ListingState.EMPTY,
        rows=tuple(rows),
        declared_count=declared,
        skipped_rows=skipped,
    )


def _ibsys_object(text: str) -> tuple[Mapping[str, object], int, int]:
    """Return the ``htvClosings.init`` argument and its span (call start, argument end)."""
    start = text.find(_IBSYS)
    if start < 0:
        raise ShapeError("no ibsys.htvClosings.init call on the page")
    try:
        data, end = json.JSONDecoder().raw_decode(text, start + len(_IBSYS))
    except ValueError as error:
        raise ShapeError(f"the htvClosings.init argument is not complete JSON: {error}") from error
    if not isinstance(data, Mapping):
        raise ShapeError("the htvClosings.init argument is not an object")
    return data, start, end


def _ibsys_row(bucket: str, institution: object) -> ParsedRow | None:
    if not isinstance(institution, Mapping):
        raise ShapeError(f"an institution in bucket {bucket!r} is not an object")
    name, status = institution.get("name"), institution.get("status")
    updated = institution.get("updateTimestamp")
    if not isinstance(status, str) or (name is not None and not isinstance(name, str)):
        raise ShapeError(f"an institution in bucket {bucket!r} lacks its name or status as text")
    if updated is not None and not isinstance(updated, str):
        raise ShapeError(f"an institution in bucket {bucket!r} has a non-text updateTimestamp")
    if name is None or not name.strip():
        return None
    extra: dict[str, JsonScalar] = {"bucket": bucket}
    for key, value in institution.items():
        if key not in {"name", "status", "updateTimestamp"}:
            extra[str(key)] = _flat(value)
    return ParsedRow(
        name=_SPACE.sub(" ", name).strip(),
        status=status.strip(),
        updated_text=updated.strip() if updated is not None else None,
        extra=extra,
    )


def _whole(value: object, what: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    raise ShapeError(f"{what} is not a count: {value!r}")


def parse_ibsys(html: bytes) -> Listing:
    """Read the ibsys ``hearst-ibsys`` page (the list is a script call's JSON argument)."""
    data, _start, _end = _ibsys_object(html.decode("utf-8", errors="replace"))
    total = _whole(data.get(_IBSYS_TOTAL), _IBSYS_TOTAL)
    rows: list[ParsedRow] = []
    skipped = 0
    held = 0
    for bucket, content in data.items():
        if bucket == _IBSYS_TOTAL:
            continue
        if not isinstance(content, Mapping) or not isinstance(content.get("institutions"), list):
            raise ShapeError(f"bucket {bucket!r} has no institutions list")
        institutions = content["institutions"]
        count = _whole(content.get("count"), f"bucket {bucket!r} count")
        if count != len(institutions):
            raise ShapeError(
                f"bucket {bucket!r} says {count} but holds {len(institutions)} institutions"
            )
        held += count
        for institution in institutions:
            row = _ibsys_row(str(bucket), institution)
            if row is None:
                skipped += 1
            else:
                rows.append(row)
    if held != total:
        raise ShapeError(f"totalCount is {total} but the buckets hold {held} institutions")
    if skipped and not rows:
        raise ShapeError("every institution is missing its name")
    return Listing(
        variant="hearst-ibsys",
        state=ListingState.POPULATED if rows else ListingState.EMPTY,
        rows=tuple(rows),
        declared_count=total,
        skipped_rows=skipped,
    )


def parse(body: bytes) -> Listing:
    """Read one Hearst closings page, live or archived, in whichever known variant it is."""
    html = decode(body)
    if _CONTAINER.search(html):
        return parse_rows(html)
    if _IBSYS.encode() in html:
        return parse_ibsys(html)
    if b"self.__next_f.push" in html and b"closingsData" in html:
        return parse_next(html)
    raise ShapeError("not a Hearst closings page this adapter knows")


def _balanced_div(html: bytes, start: int) -> int:
    """Return the end offset of the ``<div>`` that opens at ``start``."""
    depth = 0
    for match in _DIV.finditer(html, start):
        depth += -1 if match.group(1) else 1
        if depth == 0:
            close = html.find(b">", match.end())
            if close < 0:
                break
            return close + 1
    raise ShapeError("the closings container is not closed")


def slice_page_v2(body: bytes) -> bytes:
    """Cut a Hearst page down to what :func:`parse` reads: ``hearst-page-v2``.

    The same as :func:`slice_page` (``hearst-page-v1``) for the variants that reads,
    plus ``hearst-ibsys``: the ``ibsys.htvClosings.init({...})`` call, byte for byte,
    in a one-statement script in a minimal document.
    """
    html = decode(body)
    if _CONTAINER.search(html) or _IBSYS.encode() not in html:
        return slice_page(body)
    text = html.decode("utf-8")
    _data, start, end = _ibsys_object(text)
    close = text.find(")", end)
    if close < 0 or text[end:close].strip():
        raise ShapeError("the htvClosings.init call is not closed after its argument")
    call = text[start : close + 1].encode("utf-8")
    return b"<!doctype html>\n<html><body>\n<script>" + call + b";</script>\n</body></html>\n"


def slice_page(body: bytes) -> bytes:
    """Cut a Hearst page down to what :func:`parse` reads (for test fixtures): v1.

    ``hearst-rows``: the ``weather-closings-data`` container, byte for byte.
    ``hearst-next``: the payload chunks that hold the closingsData object, byte for
    byte. Each is wrapped in a minimal document and nothing else of the page is kept.
    Any other page (``hearst-ibsys`` included) is refused: see :func:`slice_page_v2`.
    """
    html = decode(body)
    match = _CONTAINER.search(html)
    if match is not None:
        end = _balanced_div(html, match.start())
        kept = html[match.start() : end]
        notice = re.search(rb'<div class="weather-closings-data-noclosings[^"]*">', html)
        if notice is not None and not (match.start() <= notice.start() < end):
            kept = html[notice.start() : _balanced_div(html, notice.start())] + b"\n" + kept
        return b"<!doctype html>\n<html><body>\n" + kept + b"\n</body></html>\n"
    if b"closingsData" in html:
        chunks = list(_PUSH.finditer(html))
        texts: list[str] = []
        for chunk in chunks:
            item = json.loads(chunk.group(1))
            texts.append(item[1] if isinstance(item, list) and item[:1] == [1] else "")
        payload = "".join(texts)
        start = payload.find(_KEY)
        if start < 0:
            raise ShapeError("the Next.js payload has no closingsData")
        _data, end = json.JSONDecoder().raw_decode(payload, start + len(_KEY))
        offset = 0
        kept_chunks: list[bytes] = []
        for chunk, text in zip(chunks, texts, strict=True):
            if offset < end and offset + len(text) > start:
                kept_chunks.append(chunk.group(0))
            offset += len(text)
        return b"<!doctype html>\n<html><body>\n" + b"\n".join(kept_chunks) + b"\n</body></html>\n"
    raise ShapeError("not a Hearst closings page this adapter knows")
