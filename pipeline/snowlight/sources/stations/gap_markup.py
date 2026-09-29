"""Text and markup helpers for the gap-state adapters (part 4 of the station adapters).

The adapters of the sources that reach the counties TV-group lists leave out
(:mod:`~snowlight.sources.stations.cowles` and
:mod:`~snowlight.sources.stations.flathead`) read bodies the same way: text is kept
as the page shows it, with runs of whitespace (non-breaking spaces too) made one
space. Nothing here knows a platform, classifies a status or matches a name.
"""

import re

from selectolax.parser import Node

from snowlight.sources.stations.body import decode
from snowlight.sources.stations.model import (
    MAX_EXTRA_TEXT,
    MAX_NAME,
    JsonScalar,
    Listing,
    ListingState,
    ParsedRow,
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


def html_text(body: bytes) -> str:
    """Decode an HTML body (after any archive content encoding).

    UTF-8 first; a body that is not UTF-8 is read as Windows-1252, the encoding
    older list generators wrote.
    """
    raw = decode(body).removeprefix(b"\xef\xbb\xbf")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def clip(text: str, limit: int = MAX_EXTRA_TEXT) -> str:
    """Return ``text`` cut to ``limit`` characters (with an ellipsis), never dropped."""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def make_row(
    name: str, status: str, updated: str | None, extra: dict[str, JsonScalar]
) -> ParsedRow | None:
    """Build a row, or None when it has no name (the listing counts it as skipped)."""
    name = collapse(name)
    if not name:
        return None
    return ParsedRow(
        name=clip(name, MAX_NAME),
        status=collapse(status),
        updated_text=updated,
        extra={
            key: clip(value) if isinstance(value, str) else value for key, value in extra.items()
        },
    )


def make_listing(variant: str, rows: list[ParsedRow], *, skipped: int = 0) -> Listing:
    """Return a populated listing when there are rows, else an empty one.

    Only call it once the body has shown it is in its variant's shape: a body with
    no rows here is one that said, in its own words or structure, that nothing is listed.
    """
    return Listing(
        variant=variant,
        state=ListingState.POPULATED if rows else ListingState.EMPTY,
        rows=tuple(rows),
        skipped_rows=skipped,
    )


def deferred(variant: str, follows: tuple[str, ...]) -> Listing:
    """Return a page that holds no list and loads it from ``follows`` (as the page names it)."""
    return Listing(variant=variant, state=ListingState.DEFERRED, rows=(), follows=follows)


def document(inner: str) -> bytes:
    """Wrap a kept fragment in a minimal HTML document (for sliced fixtures)."""
    return f"<!DOCTYPE html><html><body>{inner}</body></html>\n".encode()
