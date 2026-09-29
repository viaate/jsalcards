"""Cowles Montana Media's school closures ticker (KULR-8 and NonStop Local Montana).

Cowles' Montana stations show one list of school closures: KULR-8's page "Montana
School Closures" (``https://www.kulr8.com/schoolclosures/``) and NonStop Local
Montana's page "School Closures Around Montana"
(``https://www.montanarightnow.com/schoolclosures/``, the site of KFBB/KHBB, KTMF
and KWYB) both frame the same file, which the company's ticker system writes to
S3: ``https://company-wide-tickers.s3.us-west-2.amazonaws.com/KULR_School_Results/closings.html``
(read live on 2026-09-27; ``Last-Modified`` 2026-04-16, inside the last winter).
Variants this adapter reads:

``closings-grid``
    The ticker file, a "Closings Last Updated at" grid (the NewsTicker generator's
    grid form): the line "Closings Last Updated at 9:13am on 4/16/2026" over a table
    of three-cell rows, one per organization::

        <tr><td width="33%"><b>Name</b></td><td width="33%">Status</td>
            <td width="33%">Comment</td></tr>

    The bold first cell is the name, the second the status, and the third (often
    blank) goes in ``raw_extra["comment"]`` when it holds text. A row of one bold
    cell is a heading, kept as ``raw_extra["group"]`` on the rows under it. The
    update line's time is each row's ``raw_updated_text`` (``raw_extra["updated_scope"]``
    is ``"page"``: the file gives one time for the whole list). The bold sentence
    "No Closings have been reported at this time" in the first of three otherwise
    blank cells is the empty state (live on 2026-09-27).

``cowles-page``
    Either station page: a TownNews BLOX page whose body frames the ticker
    (``<iframe src="https://company-wide-tickers.s3.us-west-2.amazonaws.com/KULR_School_Results/closings.html"``).
    A :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED` listing that
    follows the file.

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`, and so
does a grid that lists rows and also says none are reported, or a row whose shape
is not one of the above. So do the archived captures of the ``/schoolclosures/``
pages from before they framed the ticker (abcfoxmontana.com 2019-11-20,
montanarightnow.com 2020-11-24 and 2021-03-06): BLOX sections of article cards
(``<body class="... section-schoolclosures">``; the 2021 one held a single story on a
COVID-19 closure), not a list of schools, so they are not read as one.
"""

import re

from selectolax.parser import HTMLParser

from snowlight.sources.stations.body import decode
from snowlight.sources.stations.gap_markup import (
    collapse,
    deferred,
    document,
    html_text,
    make_listing,
    make_row,
    node_text,
)
from snowlight.sources.stations.model import JsonScalar, Listing, ParsedRow, ShapeError

GRID = "closings-grid"
PAGE = "cowles-page"
GRID_EMPTY = "No Closings have been reported at this time"
TICKER_HOST = "company-wide-tickers.s3.us-west-2.amazonaws.com"

_STAMP = re.compile(r"Closings Last Updated at\s*([^<]*?)\s*<", re.IGNORECASE)
_FRAME = re.compile(
    r"<iframe\b[^>]*\bsrc=\"(https?://company-wide-tickers\.s3[.a-z0-9-]*\.amazonaws\.com/"
    r"[A-Za-z0-9_]+/closings\.html)\"",
    re.IGNORECASE,
)
_COLUMNS = 3
_SECTION = re.compile(r"<body\b[^>]*\bclass=\"[^\"]*\bsection-schoolclosures\b", re.IGNORECASE)


def _grid(text: str) -> Listing:
    stamp = _STAMP.search(text)
    updated = collapse(stamp.group(1)) if stamp is not None and stamp.group(1).strip() else None
    tree = HTMLParser(text)
    rows: list[ParsedRow] = []
    group: str | None = None
    empty = False
    skipped = 0
    for tr in tree.css("tr"):
        cells = tr.css("td")
        if not cells or cells[0].css_first("b") is None:
            raise ShapeError("a closings grid row does not start with a bold cell")
        texts = [node_text(td) for td in cells]
        if texts[0] == GRID_EMPTY and not any(texts[1:]):
            empty = True
            continue
        if len(cells) == 1:
            group = texts[0] or None
            continue
        if len(cells) != _COLUMNS:
            raise ShapeError(f"a closings grid row has {len(cells)} cells, not {_COLUMNS}")
        extra: dict[str, JsonScalar] = {"updated_scope": "page"} if updated else {}
        if group is not None:
            extra["group"] = group
        if texts[2]:
            extra["comment"] = texts[2]
        found = make_row(texts[0], texts[1], updated, extra)
        if found is None:
            skipped += 1
        else:
            rows.append(found)
    if rows and empty:
        raise ShapeError("a closings grid lists rows and says none are reported")
    if not rows and not empty:
        raise ShapeError("a closings grid with no rows and no no-closings sentence")
    return make_listing(GRID, rows, skipped=skipped)


def parse(body: bytes) -> Listing:
    """Read Cowles' closures ticker file, or a station page that frames it."""
    text = html_text(body)
    if _STAMP.search(text) is not None:
        return _grid(text)
    frame = _FRAME.search(text)
    if frame is not None:
        return deferred(PAGE, (frame.group(1),))
    if _SECTION.search(text) is not None:
        raise ShapeError(
            "the /schoolclosures/ section as it was before it framed the ticker (archived "
            "2019-2021): cards linking to articles, not a list of schools"
        )
    raise ShapeError("neither Cowles' closures ticker nor a page that frames it")


def slice_body(body: bytes) -> bytes:
    """Cut a station page to its frame; the ticker file is kept whole (decoded)."""
    found = parse(body)
    if found.variant == PAGE:
        return document(f'<iframe src="{found.follows[0]}"></iframe>')
    return decode(body)
