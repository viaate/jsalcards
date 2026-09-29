"""News-Press & Gazette stations' closings: KQ2's page and the NewsTicker file it frames.

KQ2 (KQTV, St. Joseph, Missouri; News-Press & Gazette Co.) is the one station of the
St. Joseph market with a closings list. Its page ``https://www.kq2.com/weather/closings/``
(a WordPress page, "Closings and Delays", with "Click here to submit a closing" linking
the schools' login at schoolclosings.org) frames a static file its closings system
writes on the station's ``ftp2`` host, ``https://ftp2.kq2.com/closings.html``, the way
Allen Media's stations frame theirs (:mod:`snowlight.sources.stations.allen`). The
other News-Press & Gazette stations have no such file (their ``ftp2`` hosts do not
resolve, 2026-09-28) and no closings page. Variants this adapter reads:

``npg-closings-page``
    The station page: an ``<iframe src="https://ftp2.kq2.com/closings.html">``. A
    :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED` listing whose
    ``follows`` is the framed file.

``newsticker-html``
    The framed file with postings: a NewsTicker export, one ``orgname`` and one
    ``status`` per row under the file's ``timestamp`` cell, read by
    :mod:`snowlight.sources.stations.newsticker` (the format Allen's and Sinclair's
    files share).

``npg-no-closings``
    The framed file with nothing posted, as KQ2's system writes it (live on
    2026-09-28, Last-Modified 2026-09-22)::

        <TD CLASS="timestamp" ALIGN=RIGHT>UPDATED TUESDAY, SEP 22 AT 10:10 AM</TD>
        <TD CLASS="status">No currently active closings or delays to report.</TD>

    Its own sentence, not NewsTicker's usual "There are no active records at this
    time.", which :mod:`~snowlight.sources.stations.newsticker` does not know. An
    empty list.

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`, including a
file that holds that sentence beside an ``orgname`` row.
"""

import re
from html import escape

from selectolax.parser import HTMLParser

from snowlight.sources.stations import newsticker
from snowlight.sources.stations.gap_markup import (
    deferred,
    document,
    html_text,
    make_listing,
    node_text,
)
from snowlight.sources.stations.model import Listing, ShapeError

PAGE = "npg-closings-page"
EMPTY = "npg-no-closings"
EMPTY_SENTENCE = "No currently active closings or delays to report."
_FRAME = re.compile(r"^https://ftp2\.[a-z0-9.-]+/closings\.html$")
_ORGNAME = re.compile(r"\bclass=\"?orgname\"?", re.IGNORECASE)


def _frame(tree: HTMLParser) -> str | None:
    for iframe in tree.css("iframe"):
        src = (iframe.attributes.get("src") or "").strip()
        if _FRAME.match(src):
            return src
    return None


def _empty_file(tree: HTMLParser, text: str) -> bool:
    if _ORGNAME.search(text) is not None:
        return False
    stamps = [
        td for td in tree.css("td") if "timestamp" in (td.attributes.get("class") or "").lower()
    ]
    statuses = [
        node_text(td)
        for td in tree.css("td")
        if (td.attributes.get("class") or "").lower() == "status"
    ]
    return bool(stamps) and statuses == [EMPTY_SENTENCE]


def parse(body: bytes) -> Listing:
    """Read KQ2's closings page or the file it frames."""
    text = html_text(body)
    tree = HTMLParser(text)
    if EMPTY_SENTENCE in text:
        if not _empty_file(tree, text):
            raise ShapeError("a closings file that says nothing is posted also lists rows")
        return make_listing(EMPTY, [])
    found = newsticker.read_file(body)
    if found is not None:
        return found
    frame = _frame(tree)
    if frame is not None:
        return deferred(PAGE, (frame,))
    raise ShapeError("neither KQ2's closings page nor a closings file it frames")


def slice_body(body: bytes) -> bytes:
    """Keep a page's closings frame alone; a closings file is kept whole (it is small)."""
    found = parse(body)
    if found.variant != PAGE:
        return html_text(body).encode()
    frame = escape(found.follows[0])
    return document(f'<iframe src="{frame}" height="2000" width="100%"></iframe>')
