"""Gray Media closings (GSync): the per-station S3 export and the station pages.

Variants this adapter reads (the ``variant`` field of each listing):

``gray-s3-json``
    ``https://s3.amazonaws.com/grayfilestore-{call}/closingsData/closings_{CALL}.json``,
    a JSON array holding one object::

        [{"record": [item, ...], "locations": ["Ohio"], "num_closings": 3,
          "export_type": "L1", "source": "GSync", "run_date": ""}]

    The empty export has no ``record`` key and ``num_closings`` 0. Each item is a
    flat object: ``forced_organization_name`` (the raw name),
    ``forced_status_name`` (the raw status, weekday included, e.g. "Closed
    Friday"), ``updated`` (a date), and the rest (``comments_line1..3``,
    ``county_name1``, ``state``, ``zipcode``, ``expiration`` with no time zone,
    ``rec_id`` and so on), which are kept verbatim in ``raw_extra``. Text is kept
    as the export has it, including HTML escapes such as ``&amp;``, except that
    spaces around the name, the status and the update date are trimmed (the raw
    row keeps names without outer whitespace; the export has names such as
    "Rankin County School District " with a trailing space). Station pages
    fetch it with a cache-busting query (``?rnd=...&arc-site=...``), which is how
    the Wayback Machine holds it.

``gray-fusion-orgs``
    A station's ``/weather/closings/`` page on Gray's Arc XP (Fusion) sites, as
    served from 2023 to early 2025: the list is server-side data in the page's
    ``Fusion.contentCache`` script object, under ``"gsync-closings"``::

        Fusion.contentCache={..., "gsync-closings": {"{}": {"data": {
            "organizations": [org, ...], "totalResults": 277,
            "lastUpdated": "2024-01-14T13:04:08.194Z", "countiesList": [...], ...}}}}

    Each ``org`` gives ``name``, ``status`` and ``updatedDate`` (trimmed of outer
    spaces, as for the export); the rest
    (``county``, ``category``, ``comments``, ``address`` and so on) is kept in
    ``raw_extra``: a nested object as dotted keys (``address.zipcode``), a list
    as JSON text. ``"organizations": []`` with ``totalResults`` 0 is the empty state.

``gray-api-orgs``, ``gray-api-count``
    The same data object served alone as JSON by the station site's Arc content
    API (``https://www.{site}/pf/api/v3/content/fetch/gsync-closings``), read the
    same way.

``gray-fusion-lazy``
    The same page as served by 2026 at some stations: the closings component is
    loaded lazily, so the page's ``Fusion.contentCache`` has no ``"gsync-closings"``
    entry at all (only the component's ``gsync-closings-detailed`` markup shows it
    is the closings page). This is a
    :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED` listing: no
    list and no count.

``gray-fusion-count``
    The same page as served from 2025 on: ``"gsync-closings"`` holds only
    ``totalResults``, and the browser loads the list from the S3 export. A zero
    count is the empty state; a positive count is a
    :attr:`~snowlight.sources.stations.model.ListingState.COUNT_ONLY` listing
    (the page says how many, not who).

    Fusion stamps the cache entry with ``lastModified`` (milliseconds since
    1970): when the server fetched the data, typically one to three minutes
    before the page was served. It is the listing's ``declared_at`` (rounded down
    to the second), for this variant and ``gray-fusion-orgs``, so a page's count
    can be compared with an export captured at a known distance from it.

    Neither a lazy nor a count-only page names the export it loads (the site's
    script builds the URL), so its listing's ``follows`` is empty; the archive
    reader follows it to the station's registered ``data_url``, the export.

``gray-fusion-frame``
    An Arc page whose closings area is an HTML box framing a closings file on
    another host (``<iframe class='embed_frame' src='https://webpubcontent.gray.tv/
    {site}/.../closings.html'>``), with no ``gsync-closings-detailed`` component:
    seen at KPTV (2024), WFSB, WGGB (2024), WEEK (2022) and WLIO (2026), stations
    whose lists never moved to GSync. The page's content cache may still hold a
    ``"gsync-closings"`` entry, but the page does not show it, so that entry says
    nothing about the station's list: the listing is ``DEFERRED`` and ``follows``
    the frame's ``src``.

Older pages at a station's closings address (Gray Digital Media's ``gray-gdm-table``,
``gray-gdm-list`` and ``gray-gdm-script``, pages that frame their list, ``gray-frame``,
TownNews BLOX pages from before a station moved to Gray's Arc site,
``gray-blox-script``, and Heartland Media pages that write their list file in,
``gray-heartland-*``) are read by :mod:`snowlight.sources.stations.gray_legacy`,
and the list files such pages framed or loaded (``gray-file-*``: NewsTicker HTML
and XML exports, the Meredith ticker and SC XML files, FlashAlert reports, Allen
Media's counter and the like) by :mod:`snowlight.sources.stations.gray_files`.

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`.
"""

import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from snowlight.sources.stations import gray_files, gray_legacy
from snowlight.sources.stations.body import decode
from snowlight.sources.stations.model import (
    JsonScalar,
    Listing,
    ListingState,
    ParsedRow,
    ShapeError,
)

NAME_KEY = "forced_organization_name"
STATUS_KEY = "forced_status_name"
UPDATED_KEY = "updated"
_EXPORT_KEYS = frozenset({"num_closings", "locations"})
_FUSION = "Fusion.contentCache="
_GSYNC = "gsync-closings"
_LAZY_COMPONENT = 'class="gsync-closings-detailed'
_LAZY_TAG = re.compile(r'<div class="gsync-closings-detailed[^"]*">')
_GSYNC_KEY = re.compile(rf'"{_GSYNC}"\s*:\s*')
_ORG_NAME, _ORG_STATUS, _ORG_UPDATED = "name", "status", "updatedDate"


def _decode_json(body: bytes) -> object:
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ShapeError(f"body is not UTF-8: {error}") from error
    try:
        return json.loads(text)
    except ValueError as error:
        raise ShapeError(f"body is not JSON: {error}") from error


def _count(value: object, what: str = "num_closings") -> int:
    if isinstance(value, bool):
        raise ShapeError(f"{what} is not a count")
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    raise ShapeError(f"{what} is not a count: {value!r}")


def _scalar(key: str, value: object) -> JsonScalar:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise ShapeError(f"item field {key!r} is not a plain value")


def _row(item: object) -> ParsedRow | None:
    if not isinstance(item, Mapping):
        raise ShapeError("a record item is not an object")
    name, status = item.get(NAME_KEY), item.get(STATUS_KEY)
    if not isinstance(status, str) or (name is not None and not isinstance(name, str)):
        raise ShapeError(f"a record item lacks {NAME_KEY!r} or {STATUS_KEY!r} as text")
    if name is None or not name.strip():
        return None
    updated = item.get(UPDATED_KEY)
    if updated is not None and not isinstance(updated, str):
        raise ShapeError(f"{UPDATED_KEY!r} is not text")
    extra = {
        str(key): _scalar(str(key), value)
        for key, value in item.items()
        if key not in {NAME_KEY, STATUS_KEY, UPDATED_KEY}
    }
    return ParsedRow(
        name=name.strip(),
        status=status.strip(),
        updated_text=updated.strip() if updated is not None else None,
        extra=extra,
    )


def parse_export(data: object) -> Listing:
    """Read a decoded S3 GSync export (the ``gray-s3-json`` variant)."""
    exports: Sequence[object] = data if isinstance(data, list) else [data]
    if not exports:
        raise ShapeError("the export array is empty")
    rows: list[ParsedRow] = []
    declared = 0
    skipped = 0
    for export in exports:
        if not isinstance(export, Mapping) or not set(export) >= _EXPORT_KEYS:
            raise ShapeError("not a GSync export object")
        count = _count(export["num_closings"])
        declared += count
        records = export.get("record")
        if records is None:
            if count:
                raise ShapeError(f"num_closings is {count} but there is no record list")
            continue
        if not isinstance(records, list):
            raise ShapeError("record is not a list")
        for item in records:
            row = _row(item)
            if row is None:
                skipped += 1
            else:
                rows.append(row)
    if skipped and not rows:
        raise ShapeError("every record item is missing its name")
    return Listing(
        variant="gray-s3-json",
        state=ListingState.POPULATED if rows else ListingState.EMPTY,
        rows=tuple(rows),
        declared_count=declared,
        skipped_rows=skipped,
    )


# Station pages (Arc XP Fusion) -----------------------------------------------------


def _content_cache(text: str) -> tuple[Mapping[str, object], int, int]:
    """Return the page's ``Fusion.contentCache`` object and its span in ``text``."""
    start = text.find(_FUSION)
    if start < 0:
        raise ShapeError("no Fusion.contentCache on the page")
    begin = start + len(_FUSION)
    try:
        cache, end = json.JSONDecoder().raw_decode(text, begin)
    except ValueError as error:
        raise ShapeError(f"Fusion.contentCache is not complete JSON: {error}") from error
    if not isinstance(cache, Mapping):
        raise ShapeError("Fusion.contentCache is not an object")
    return cache, begin, end


def _gsync_entry(cache: Mapping[str, object]) -> tuple[Mapping[str, object], datetime | None]:
    """Return the ``gsync-closings`` data object and when the cache entry was made.

    Fusion stamps each content cache entry with ``lastModified`` (milliseconds
    since 1970, UTC): the moment the server fetched the data, which can be minutes
    before the page was served. It is returned rounded down to whole seconds.
    """
    entries = cache.get(_GSYNC)
    if not isinstance(entries, Mapping):
        raise ShapeError("the page's content cache has no gsync-closings entry")
    if len(entries) != 1:
        raise ShapeError(f"gsync-closings holds {len(entries)} queries, not one")
    (entry,) = entries.values()
    data = entry.get("data") if isinstance(entry, Mapping) else None
    if not isinstance(data, Mapping) or not isinstance(entry, Mapping):
        raise ShapeError("gsync-closings has no data object")
    stamp = entry.get("lastModified")
    if stamp is None:
        return data, None
    if isinstance(stamp, bool) or not isinstance(stamp, int) or stamp <= 0:
        raise ShapeError(f"gsync-closings lastModified is not a time: {stamp!r}")
    return data, datetime.fromtimestamp(stamp // 1000, tz=UTC)


def _flatten(key: str, value: object, into: dict[str, JsonScalar]) -> None:
    if value is None or isinstance(value, str | int | float | bool):
        into[key] = value
    elif isinstance(value, Mapping):
        for inner, item in value.items():
            _flatten(f"{key}.{inner}", item, into)
    else:
        into[key] = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _org_row(org: object) -> ParsedRow | None:
    if not isinstance(org, Mapping):
        raise ShapeError("an organization is not an object")
    name, status, updated = org.get(_ORG_NAME), org.get(_ORG_STATUS), org.get(_ORG_UPDATED)
    if not isinstance(status, str) or (name is not None and not isinstance(name, str)):
        raise ShapeError("an organization lacks its name or status as text")
    if updated is not None and not isinstance(updated, str):
        raise ShapeError(f"{_ORG_UPDATED!r} is not text")
    if name is None or not name.strip():
        return None
    extra: dict[str, JsonScalar] = {}
    for key, value in org.items():
        if key not in {_ORG_NAME, _ORG_STATUS, _ORG_UPDATED}:
            _flatten(str(key), value, extra)
    return ParsedRow(
        name=name.strip(),
        status=status.strip(),
        updated_text=updated.strip() if updated is not None else None,
        extra=extra,
    )


def _page_frame(body: bytes) -> bytes | None:
    """Return the closings iframe of an Arc page that shows no GSync component, if any."""
    if _LAZY_COMPONENT.encode() in body:
        return None
    return gray_legacy.frame(body)


def parse_page(body: bytes) -> Listing:
    """Read a station closings page (``gray-fusion-orgs``, ``-count``, ``-lazy`` or ``-frame``)."""
    text = body.decode("utf-8", errors="replace")
    cache, _begin, _end = _content_cache(text)
    element = _page_frame(body)
    if element is not None:
        return gray_legacy.frame_listing(element, "gray-fusion-frame")
    if _GSYNC not in cache and _LAZY_COMPONENT in text:
        return Listing(variant="gray-fusion-lazy", state=ListingState.DEFERRED, rows=())
    data, computed_at = _gsync_entry(cache)
    return parse_gsync_data(data, "gray-fusion", computed_at)


def parse_gsync_data(
    data: Mapping[str, object], prefix: str, computed_at: datetime | None = None
) -> Listing:
    """Read a gsync-closings data object; variants are ``{prefix}-orgs`` and ``-count``.

    ``computed_at`` is when the data was fetched (the page's cache entry says), if known.
    """
    total = _count(data.get("totalResults"), "totalResults")
    organizations = data.get("organizations")
    if organizations is None:
        if set(data) - {"totalResults", "_id"}:
            raise ShapeError(f"gsync-closings data has no organizations: {sorted(data)}")
        state = ListingState.COUNT_ONLY if total else ListingState.EMPTY
        return Listing(
            variant=f"{prefix}-count",
            state=state,
            rows=(),
            declared_count=total,
            declared_at=computed_at,
        )
    if not isinstance(organizations, list):
        raise ShapeError("organizations is not a list")
    rows: list[ParsedRow] = []
    skipped = 0
    for org in organizations:
        row = _org_row(org)
        if row is None:
            skipped += 1
        else:
            rows.append(row)
    if skipped and not rows:
        raise ShapeError("every organization is missing its name")
    if not rows and total:
        raise ShapeError(f"totalResults is {total} but the organizations list is empty")
    return Listing(
        variant=f"{prefix}-orgs",
        state=ListingState.POPULATED if rows else ListingState.EMPTY,
        rows=tuple(rows),
        declared_count=total,
        skipped_rows=skipped,
        declared_at=computed_at,
    )


def parse(body: bytes) -> Listing:
    """Read one Gray body, live or archived, in whichever known variant it is."""
    body = decode(body)
    stripped = body.removeprefix(b"\xef\xbb\xbf").lstrip()
    if stripped[:1] in {b"[", b"{"}:
        data = _decode_json(body)
        if isinstance(data, Mapping) and "totalResults" in data and "num_closings" not in data:
            return parse_gsync_data(data, "gray-api")
        if isinstance(data, Mapping) and "numClosings" in data:
            return gray_files.parse(body)
        return parse_export(data)
    if _FUSION.encode() in body:
        return parse_page(body)
    # A Heartland page holds a list file's markers too, so it goes to gray_legacy.
    if gray_files.is_file(body) and gray_legacy.heartland_parts(body) is None:
        return gray_files.parse(body)
    return gray_legacy.parse(body)


def _document(inner: str) -> bytes:
    return f"<!doctype html>\n<html><body>\n{inner}\n</body></html>\n".encode()


def slice_page_v2(body: bytes) -> bytes:
    """Cut a Gray body down to what :func:`parse` reads: ``gray-page-v2``.

    The same as :func:`slice_page` (``gray-page-v1``) for an export or an Arc page;
    a pre-Arc page is cut with :func:`snowlight.sources.stations.gray_legacy.slice_page`.
    """
    body = decode(body)
    stripped = body.removeprefix(b"\xef\xbb\xbf").lstrip()
    if stripped[:1] in {b"[", b"{"} or _FUSION.encode() in body:
        return slice_page(body)
    return gray_legacy.slice_page(body)


def slice_page_v3(body: bytes) -> bytes:
    """Cut a Gray body down to what :func:`parse` reads: ``gray-page-v3``.

    The same as :func:`slice_page_v2` for every body it slices. An Arc page that
    frames its list (``gray-fusion-frame``, which v1 and v2 refuse) keeps its
    closings ``<iframe>`` element byte for byte, and its ``"gsync-closings"``
    member (byte for byte, as v1 keeps it) in a one-member cache, or an empty
    cache when it has none. A list file a page loads is cut with
    :func:`snowlight.sources.stations.gray_files.slice_file`.
    """
    body = decode(body)
    if _FUSION.encode() in body and _page_frame(body) is not None:
        element = _page_frame(body)
        text = body.decode("utf-8", errors="strict")
        cache, begin, end = _content_cache(text)
        member = "{}"
        for match in _GSYNC_KEY.finditer(text, begin, end):
            try:
                value, value_end = json.JSONDecoder().raw_decode(text, match.end())
            except ValueError:
                continue
            if value == cache.get(_GSYNC) and value is not None:
                member = "{" + text[match.start() : value_end] + "}"
                break
        assert element is not None  # noqa: S101 - checked above
        frame_text = element.decode("utf-8")
        sliced = _document(f"{frame_text}\n<script>{_FUSION}{member};</script>")
        if parse(sliced) != parse(body):
            raise ShapeError("the sliced page does not read as the page does")
        return sliced
    return gray_files.slice_file(body) if gray_files.is_file(body) else slice_page_v2(body)


def slice_page_v4(body: bytes) -> bytes:
    """Cut a Gray body down to what :func:`parse` reads: ``gray-page-v4``.

    Exports and Arc pages are cut as :func:`slice_page_v3` cuts them, and list
    files are kept whole. A Heartland page (``gray-heartland-*``, which v3 kept
    whole) keeps the list's "Refresh Data" button and the file after it (see
    :func:`snowlight.sources.stations.gray_legacy.slice_heartland`), and any other
    older page is cut with every closings frame :func:`gray_legacy.frame
    <snowlight.sources.stations.gray_legacy.frame>` knows
    (:func:`~snowlight.sources.stations.gray_legacy.slice_page_v3`: v2 knew only
    frames with "closing" in their path, so a page framing an ``ftp2.`` file and
    also carrying a counter script was cut to the script). Every slice reads
    exactly as the whole body does, or this raises
    :class:`~snowlight.sources.stations.model.ShapeError`.
    """
    body = decode(body)
    stripped = body.removeprefix(b"\xef\xbb\xbf").lstrip()
    if stripped[:1] in {b"[", b"{"} or _FUSION.encode() in body:
        sliced = slice_page_v3(body)
    elif (inline := gray_legacy.slice_heartland(body)) is not None:
        sliced = inline
    elif gray_files.is_file(body):
        sliced = gray_files.slice_file(body)
    else:
        sliced = gray_legacy.slice_page_v3(body)
    if parse(sliced) != parse(body):
        raise ShapeError("the sliced body does not read as the body does")
    return sliced


def slice_page(body: bytes) -> bytes:
    """Cut a Gray body down to what :func:`parse` reads (for test fixtures): v1.

    An S3 export is kept whole (decoded if the archive replayed it compressed). A
    station page keeps only the ``"gsync-closings": {...}`` member of its
    ``Fusion.contentCache`` object, byte for byte, wrapped in a one-member
    ``Fusion.contentCache={...};`` script in a minimal document; a lazy page (no
    such member) keeps the closings component's opening tag and the whole cache.
    """
    body = decode(body)
    if _FUSION.encode() not in body:
        if body.removeprefix(b"\xef\xbb\xbf").lstrip()[:1] not in {b"[", b"{"}:
            raise ShapeError("not an export or an Arc page: see slice_page_v2")
        parse(body)  # an export, or a ShapeError for anything unknown
        return body
    if _page_frame(body) is not None:
        raise ShapeError("an Arc page that frames its list: see slice_page_v3")
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ShapeError(f"page is not UTF-8: {error}") from error
    cache, begin, end = _content_cache(text)
    expected = cache.get(_GSYNC)
    lazy = _LAZY_TAG.search(text)
    if expected is None and lazy is not None:
        # A lazy page: keep the component's opening tag and the whole cache (which
        # shows the list is absent), each byte for byte.
        script = f"<script>{text[begin - len(_FUSION) : end]};</script>"
        return _document(f"{lazy.group(0)}</div>\n{script}")
    for match in _GSYNC_KEY.finditer(text, begin, end):
        try:
            value, value_end = json.JSONDecoder().raw_decode(text, match.end())
        except ValueError:
            continue
        if value == expected and value is not None:
            member = text[match.start() : value_end]
            return _document(f"<script>{_FUSION}{{{member}}};</script>")
    raise ShapeError("the page's content cache has no gsync-closings entry")
