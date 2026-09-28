"""Hubbard Broadcasting TV stations' School Alert lists: a file their pages load.

The six Hubbard TV sites (KSTP, WDIO, WNYT, KAAL, KOB, WHEC) share one WordPress
theme: the closings page loads ``/wp-content/uploads/dynamic-assets/schoolalert.html``
into ``div#listOfClosings`` with jQuery. Variants this adapter reads:

``hubbard-schoolalert``
    The file, written by the stations' "toolbox": ``<p class="lastUpdated">Last
    updated: 2025-04-03 13:36:14</p>``, then one ``div.everyOther`` per
    organization, then ``<!-- Last updated via the toolbox: ... -->``, as KSTP's
    capture of 2025-04-03 18:39 UTC shows::

        <div class="everyOther p-2"><strong>ASHBY PUBLIC SCHOOL DISTRICT</strong><br />
          E Learning Thursday April 3 </div>

    (The same markup in WDIO's capture of 2026-01-23, 67 rows; WNYT's of February
    2025, 106 to 511, whose names carry the county and state; KOB's and KAAL's.)
    The ``strong`` text is the name and the text after it the status; the time
    after "Last updated:" is each row's update text. With nothing listed the file
    holds the sentence "There are currently no reported closings." (live at all six
    sites, 2026-09-26 and 2026-09-27; KSTP's captures of 2023-12-20 and 2026-01-25):
    the empty state. A ``div.everyOther`` without exactly one ``strong`` name, other
    text in the file, or rows beside the no-closings sentence raise
    :class:`~snowlight.sources.stations.model.ShapeError`.

``hubbard-page``
    The closings page: it holds no list and names the file in its script
    (``fileClosingsList = '/wp-content/uploads/dynamic-assets/schoolalert.html';``).
    A :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED` listing that
    follows it.

``hubbard-frame-page``
    The same page in early 2022 (KSTP's captures of 2022-01-26 to 2022-02-25), which
    framed the list instead: ``<iframe src="/wp-content/uploads/wx/schoolalert.html"``.
    ``DEFERRED``, following the frame.

``hubbard-banner``
    WHEC's site alert banner, ``/wp-content/uploads/dynamic-assets/closings.html``
    beside the School Alert file, which the site's pages load to link to the
    closings page: ``<div id="siteAlertBanner-21" ...><a href="/closings-and-delays/"
    ...><strong>9 School Closings: </strong><br />Click for full list of
    closings</a>...</div><!-- 2022-12-24 8:37:16 PM -->`` (the capture of
    2022-12-25 01:37 UTC; 3,725 captures from 2022 to 2026, six read, counting 1
    to 9). A count, not a list:
    :attr:`~snowlight.sources.stations.model.ListingState.COUNT_ONLY` with the
    count, following nothing (the closings page it links to is the station's
    ``page_url``). A banner without a count above zero has not been seen and
    raises.

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`.
"""

import re

from selectolax.parser import HTMLParser, Node

from snowlight.sources.stations.body import decode
from snowlight.sources.stations.model import (
    JsonScalar,
    Listing,
    ListingState,
    ParsedRow,
    ShapeError,
)
from snowlight.sources.stations.regional import (
    collapse,
    deferred,
    document,
    html_text,
    listing,
    node_text,
    row,
)

FILE = "hubbard-schoolalert"
PAGE = "hubbard-page"
FRAME_PAGE = "hubbard-frame-page"
BANNER = "hubbard-banner"
EMPTY_SENTENCE = "There are currently no reported closings."
UPDATED_PREFIX = "Last updated:"
_LOADER = re.compile(r"fileClosingsList\s*=\s*'([^']+)'")
_FRAME = re.compile(
    r"<iframe\b[^>]*?\bsrc=\"(/wp-content/uploads/[a-z0-9/_-]*schoolalert\.html)\"", re.IGNORECASE
)
_STAMP = re.compile(r"<p class=\"lastUpdated\">", re.IGNORECASE)
_ROW = "div.everyOther"
_BANNER = re.compile(r"<div id=\"siteAlertBanner-[0-9]+\"")
_BANNER_COUNT = re.compile(r"<strong>\s*([0-9]+) School Closings:\s*</strong>")


def _classes(node: Node) -> set[str]:
    return set((node.attributes.get("class") or "").split())


def _organization(div: Node, updated: str | None) -> ParsedRow | None:
    names = div.css("strong")
    if len(names) != 1:
        raise ShapeError(f"a School Alert row holds {len(names)} names, not one")
    name = node_text(names[0])
    whole = node_text(div)
    if not whole.startswith(name):
        raise ShapeError(f"a School Alert row does not start with its name: {whole[:60]!r}")
    extra: dict[str, JsonScalar] = {"updated_scope": "page"} if updated else {}
    return row(name, collapse(whole[len(name) :]), updated, extra)


def _file(text: str) -> Listing:
    tree = HTMLParser(text)
    for tag in tree.css("style, script"):
        tag.decompose()
    stamp = tree.css_first("p.lastUpdated")
    updated = node_text(stamp).removeprefix(UPDATED_PREFIX).strip() or None
    rows: list[ParsedRow] = []
    skipped = 0
    for div in tree.css(_ROW):
        found = _organization(div, updated)
        if found is None:
            skipped += 1
        else:
            rows.append(found)
    paragraphs = [node_text(p) for p in tree.css("p") if "lastUpdated" not in _classes(p)]
    others = [text for text in paragraphs if text]
    empty = others == [EMPTY_SENTENCE]
    if others and not empty:
        shown = " | ".join(others)[:80]
        raise ShapeError(f"a School Alert file holds text not seen before: {shown!r}")
    if rows and empty:
        raise ShapeError("a School Alert file lists rows and says there are none")
    if not rows and not empty:
        raise ShapeError("a School Alert file with no rows and no no-closings sentence")
    return listing(FILE, rows, skipped=skipped)


def parse(body: bytes) -> Listing:
    """Read a Hubbard School Alert file or the page that loads or frames it."""
    text = html_text(body)
    if _STAMP.search(text) is not None and "<html" not in text[:500].lower():
        return _file(text)
    loader = _LOADER.search(text)
    if loader is not None:
        return deferred(PAGE, (loader.group(1),))
    frame = _FRAME.search(text)
    if frame is not None:
        return deferred(FRAME_PAGE, (frame.group(1),))
    if _BANNER.match(text.lstrip()) is not None:
        return _banner(text)
    raise ShapeError("not a Hubbard School Alert file or page")


def _banner(text: str) -> Listing:
    counts = _BANNER_COUNT.findall(text)
    if len(counts) != 1 or int(counts[0]) == 0:
        raise ShapeError("a site alert banner without one closings count above zero")
    return Listing(
        variant=BANNER, state=ListingState.COUNT_ONLY, rows=(), declared_count=int(counts[0])
    )


def slice_body(body: bytes) -> bytes:
    """Cut a page to its loader line or frame; the file and the banner stay whole."""
    found = parse(body)
    if found.variant == PAGE:
        return document(f"<script>fileClosingsList = '{found.follows[0]}';</script>")
    if found.variant == FRAME_PAGE:
        return document(f'<iframe src="{found.follows[0]}"></iframe>')
    return decode(body)
