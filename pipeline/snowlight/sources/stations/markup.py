"""Small text and markup helpers shared by the Nexstar, TEGNA and Scripps adapters.

Nothing here knows a platform: it collapses text the way every adapter keeps it,
flattens JSON values into ``raw_extra`` scalars, finds the end of an element that
may nest, lists the frames a page holds, and wraps kept fragments in a minimal
document for test fixtures.
"""

import json
import re
from collections.abc import Iterable
from html import unescape

from selectolax.parser import HTMLParser, Node

from snowlight.sources.stations.model import JsonScalar, ShapeError

_SPACE = re.compile(r"\s+")
_IFRAME = re.compile(r"<iframe\b[^>]*?\bsrc\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", re.IGNORECASE)
_IFRAME_TAG = re.compile(r"<iframe\b[^>]*>(?:.*?</iframe>)?", re.IGNORECASE | re.DOTALL)
SEPARATOR = " | "
"""How several values of one field (a list of statuses, say) are joined in raw text."""


def collapse(text: str) -> str:
    """Return ``text`` with runs of whitespace (non-breaking spaces too) made one space."""
    return _SPACE.sub(" ", text.replace("\xa0", " ")).strip()


def node_text(node: Node | None) -> str:
    """Return a node's visible text, whitespace collapsed (entities already decoded)."""
    if node is None:
        return ""
    return collapse(node.text(separator=" "))


def flat(value: object) -> JsonScalar:
    """Keep a JSON scalar as it is; write a list or object as compact JSON text."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def element_end(html: str, start: int, tag: str) -> int:
    """Return the offset just past the ``</tag>`` that closes the element opening at ``start``.

    Elements of the same name inside it are counted, so a module ``<article>``
    holding row ``<article>`` elements is cut whole.
    """
    pattern = re.compile(rf"<(/?){tag}\b[^>]*>", re.IGNORECASE)
    depth = 0
    for match in pattern.finditer(html, start):
        depth += -1 if match.group(1) else 1
        if depth == 0:
            return match.end()
    raise ShapeError(f"the <{tag}> element is not closed")


def iframe_sources(html: str) -> list[str]:
    """Return the ``src`` of every ``<iframe>`` in ``html``, entities decoded, in order."""
    return [unescape(m.group(1) or m.group(2) or "").strip() for m in _IFRAME.finditer(html)]


def iframe_tags(html: str) -> list[str]:
    """Return every ``<iframe ...>`` element of ``html`` (with its closing tag), in order."""
    return [match.group(0) for match in _IFRAME_TAG.finditer(html)]


def minimal_document(parts: Iterable[str]) -> bytes:
    """Wrap kept fragments, one per line, in a minimal HTML document (UTF-8)."""
    body = "\n".join(parts)
    return f"<!doctype html>\n<html><body>\n{body}\n</body></html>\n".encode()


def parse_html(html: str) -> HTMLParser:
    """Parse an HTML document or fragment."""
    return HTMLParser(html)


def json_value(text: str) -> object:
    """Parse JSON text, raising :class:`ShapeError` when it is not JSON."""
    try:
        return json.loads(text)
    except ValueError as error:
        raise ShapeError(f"not JSON: {error}") from error


def text_of(body: bytes) -> str:
    """Decode a body as UTF-8 (a BOM dropped), else as Windows-1252."""
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError:
        return body.decode("cp1252", errors="replace")
