"""Text, JSON and markup helpers shared by the adapters of the regional and group platforms.

The Sinclair, Allen, Cox, Graham, Hubbard, Spectrum, News 12, Townsquare, state
and independent adapters (:mod:`~snowlight.sources.stations.sinclair` and the
others named in :mod:`~snowlight.sources.stations.newsticker`) read bodies the
same way: text is kept as the page shows it with runs of whitespace (non-breaking
spaces too) made one space, JSON is decoded strictly, and a value kept in
``raw_extra`` is a JSON scalar. Nothing here knows a platform.
"""

import json
import re
from collections.abc import Mapping
from html import unescape

from selectolax.parser import HTMLParser, Node

from snowlight.sources.stations.body import decode
from snowlight.sources.stations.model import (
    MAX_EXTRA_TEXT,
    MAX_NAME,
    MAX_STATUS,
    JsonScalar,
    Listing,
    ListingState,
    ParsedRow,
    ShapeError,
)

_SPACE = re.compile(r"\s+")


def collapse(text: str) -> str:
    """Return ``text`` with runs of whitespace (non-breaking spaces too) made one space."""
    return _SPACE.sub(" ", text.replace("\xa0", " ")).strip()


def node_text(node: Node | None) -> str:
    """Return a node's visible text, collapsed (empty for no node)."""
    if node is None:
        return ""
    return collapse(node.text(deep=True, separator=" "))


def fragment_text(fragment: str) -> str:
    """Return the visible text of an HTML fragment, collapsed, entities decoded."""
    tree = HTMLParser(f"<div>{fragment}</div>")
    return node_text(tree.css_first("div"))


def html_text(body: bytes) -> str:
    """Decode an HTML or text body (after any archive content encoding).

    UTF-8 first; the older list files were written in Windows-1252, so a body that
    is not UTF-8 is read as that.
    """
    raw = decode(body).removeprefix(b"\xef\xbb\xbf")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def json_body(body: bytes) -> object:
    """Decode a JSON body strictly (after any archive content encoding).

    Raises:
        ShapeError: the body is not UTF-8 JSON.
    """
    raw = decode(body)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ShapeError(f"body is not UTF-8: {error}") from error
    try:
        return json.loads(text)
    except ValueError as error:
        raise ShapeError(f"body is not JSON: {error}") from error


def looks_like_json(body: bytes) -> bool:
    """Whether a (decoded) body starts like a JSON object or array."""
    head = decode(body).removeprefix(b"\xef\xbb\xbf").lstrip()[:1]
    return head in {b"{", b"["}


def scalar(value: object) -> JsonScalar:
    """Return a JSON value as ``raw_extra`` keeps it: scalars as they are, others as JSON text.

    Text longer than ``raw_extra`` allows is cut to fit (with an ellipsis), never dropped.
    """
    if value is None or isinstance(value, bool | int | float):
        return value
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    return text if len(text) <= MAX_EXTRA_TEXT else text[: MAX_EXTRA_TEXT - 1] + "…"


def extra_from(item: Mapping[str, object], skip: frozenset[str]) -> dict[str, JsonScalar]:
    """Keep every field of a JSON row outside ``skip`` in ``raw_extra``, by its own name."""
    return {key: scalar(value) for key, value in item.items() if key not in skip}


def text_field(item: Mapping[str, object], key: str) -> str | None:
    """Return a row's text field, collapsed; None when absent or null.

    Raises:
        ShapeError: the field is present but not text.
    """
    value = item.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ShapeError(f"the field {key!r} is not text: {value!r}")
    return collapse(unescape(value))


def row(
    name: str, status: str, updated: str | None, extra: dict[str, JsonScalar]
) -> ParsedRow | None:
    """Build a row, or None when it has no name (the listing counts it as skipped).

    A name or status longer than a row's may be is cut to fit (with an ellipsis);
    a list's details cell can hold a district's whole message.
    """
    name = collapse(name)
    if not name:
        return None
    if len(name) > MAX_NAME:
        name = name[: MAX_NAME - 1] + "…"
    status = collapse(status)
    if len(status) > MAX_STATUS:
        status = status[: MAX_STATUS - 1] + "…"
    return ParsedRow(name=name, status=status, updated_text=updated, extra=extra)


def listing(
    variant: str,
    rows: list[ParsedRow],
    *,
    skipped: int = 0,
    declared: int | None = None,
) -> Listing:
    """Return a populated listing when there are rows, else an empty one.

    Only call it once the body has shown it is in its variant's shape: a body with
    no rows here is one that said, in its own structure, that nothing is listed.

    Raises:
        ShapeError: ``declared`` (the body's own count) differs from the entries read.
    """
    if declared is not None and declared != len(rows) + skipped:
        raise ShapeError(f"the body counts {declared} but holds {len(rows) + skipped} entries")
    return Listing(
        variant=variant,
        state=ListingState.POPULATED if rows else ListingState.EMPTY,
        rows=tuple(rows),
        skipped_rows=skipped,
        declared_count=declared,
    )


def deferred(variant: str, follows: tuple[str, ...]) -> Listing:
    """Return a page that holds no list and loads it from ``follows`` (as the page names it)."""
    return Listing(variant=variant, state=ListingState.DEFERRED, rows=(), follows=follows)


def document(inner: str) -> bytes:
    """Wrap kept fragments of a page in a minimal HTML document (for sliced fixtures)."""
    return f"<!DOCTYPE html><html><body>{inner}</body></html>\n".encode()


_FUSION_CACHE = "Fusion.contentCache="


def fusion_entry(text: str, source: str) -> tuple[object, int | None] | None:
    """Return an Arc XP page's cached content for ``source``, and when it was fetched.

    Arc Fusion pages inline the content their components read as
    ``Fusion.contentCache={"<source>": {"<key>": {"data": ..., "lastModified": ms}}}``.
    Returns the ``data`` of the source's one entry and its ``lastModified``
    (milliseconds since 1970, or None), or None when the page caches nothing for
    ``source``.

    Raises:
        ShapeError: the cache is not JSON, or holds the source in another shape.
    """
    start = text.find(_FUSION_CACHE)
    if start < 0:
        return None
    try:
        cache, _end = json.JSONDecoder().raw_decode(text, start + len(_FUSION_CACHE))
    except ValueError as error:
        raise ShapeError(f"the page's content cache is not JSON: {error}") from error
    if not isinstance(cache, Mapping):
        raise ShapeError("the page's content cache is not an object")
    entries = cache.get(source)
    if entries is None:
        return None
    if not isinstance(entries, Mapping) or len(entries) != 1:
        raise ShapeError(f"the content cache holds {source!r} in an unknown shape")
    entry = next(iter(entries.values()))
    if not isinstance(entry, Mapping) or "data" not in entry:
        raise ShapeError(f"the content cache entry for {source!r} has no data")
    modified = entry.get("lastModified")
    stamp = modified if isinstance(modified, int) and not isinstance(modified, bool) else None
    return entry["data"], stamp
