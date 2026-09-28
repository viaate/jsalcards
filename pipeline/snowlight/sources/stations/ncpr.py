"""North Country Public Radio's storm list (Canton, NY): closings reported to the station.

NCPR's page ``https://www.northcountrypublicradio.org/storm.php`` ("Closings and
delays reported to NCPR") renders its list on the server into ``div#closings``;
the page says "This data automatically updates every 60s." Variant this adapter
reads:

``ncpr-storm-page``
    ``div#closings`` holds ``h3#updatedon`` ("This data automatically updates every
    60s. Last updated Monday, December 16th, 2024 at 9:31 am"), then, for each kind
    of posting, an ``h4`` heading and a ``div`` of entries, one ``div`` per
    organization, as the storm-day capture of 2024-12-16 14:33 UTC shows::

        <h4 ...>2 Hour Delay (Monday)</h4>
        <div><div><span class="closingsOrg">Corinth Central School District, Corinth, NY</span>
          - <blockquote>No morning BOCES. No breakfast.</blockquote></div></div>

    (The capture of 2025-02-06 19:01 UTC lists 54 organizations under eight
    headings, "Closed", "Early Dismissal", "2 Hour Delay (Thursday)" and others.)
    The ``closingsOrg`` text is the name (with the town and state the page writes
    after it), the heading above it the status, and the ``blockquote`` (when there
    is one) goes in ``raw_extra["details"]``. The update line, without its "This
    data automatically updates every 60s." preamble, is each row's update text. The
    heading "No closings, delays or cancellations listed at this time." followed by
    an empty ``div`` (live on 2026-09-27, archived 2026-01-19) is the empty state.
    Every ``closingsOrg`` in the block must be read as a row.

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`.
"""

from selectolax.parser import HTMLParser, Node

from snowlight.sources.stations.model import JsonScalar, Listing, ParsedRow, ShapeError
from snowlight.sources.stations.regional import document, html_text, listing, node_text, row

VARIANT = "ncpr-storm-page"
EMPTY_SENTENCE = "No closings, delays or cancellations listed at this time."
UPDATED_PREFIX = "This data automatically updates every 60s."
_ORG = "span.closingsOrg"


def _children(node: Node) -> list[Node]:
    """The element children of ``node``, in order (text and comments left out)."""
    found: list[Node] = []
    child = node.child
    while child is not None:
        if child.tag not in {"-text", "_comment"}:
            found.append(child)
        child = child.next
    return found


def _entry(entry: Node, status: str, updated: str | None) -> ParsedRow | None:
    orgs = entry.css(_ORG)
    if len(orgs) != 1:
        raise ShapeError(f"an NCPR entry holds {len(orgs)} organizations, not one")
    extra: dict[str, JsonScalar] = {"updated_scope": "page"} if updated else {}
    details = entry.css_first("blockquote")
    if details is not None and node_text(details):
        extra["details"] = node_text(details)
    return row(node_text(orgs[0]), status, updated, extra)


def _read(block: Node) -> Listing:
    stamp = block.css_first("h3#updatedon")
    if stamp is None or not node_text(stamp).startswith(UPDATED_PREFIX):
        raise ShapeError("NCPR's closings block has no update line")
    updated = node_text(stamp).removeprefix(UPDATED_PREFIX).strip() or None
    heading: str | None = None
    empty = False
    rows: list[ParsedRow] = []
    skipped = 0
    for child in _children(block):
        if child.tag == "h3":
            continue
        if child.tag == "h4":
            heading = node_text(child)
            empty = empty or heading == EMPTY_SENTENCE
            continue
        if child.tag != "div":
            raise ShapeError(f"NCPR's closings block holds a <{child.tag}>")
        entries = _children(child)
        if entries and (heading is None or heading == EMPTY_SENTENCE):
            raise ShapeError("NCPR's closings block lists entries under no posting heading")
        for entry in entries:
            found = _entry(entry, heading or "", updated)
            if found is None:
                skipped += 1
            else:
                rows.append(found)
    if len(block.css(_ORG)) != len(rows) + skipped:
        raise ShapeError("NCPR's closings block names organizations outside its entries")
    if rows and empty:
        raise ShapeError("NCPR's closings block lists entries and says nothing is listed")
    if not rows and not empty:
        raise ShapeError("NCPR's closings block holds no entries and no no-closings line")
    return listing(VARIANT, rows, skipped=skipped)


def parse(body: bytes) -> Listing:
    """Read NCPR's storm page."""
    block = HTMLParser(html_text(body)).css_first("div#closings")
    if block is None:
        raise ShapeError("not NCPR's storm page (no div#closings)")
    return _read(block)


def slice_body(body: bytes) -> bytes:
    """Cut the page to its closings block."""
    parse(body)
    block = HTMLParser(html_text(body)).css_first("div#closings")
    if block is None:
        raise ShapeError("not NCPR's storm page (no div#closings)")
    return document(block.html or "")
