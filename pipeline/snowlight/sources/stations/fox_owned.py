"""FOX Television Stations' closings pages and the list files they frame.

Nine FOX-owned stations show a closings list (first-hand check of 2026-09-26,
re-read live 2026-09-27): each station page (``https://www.{site}/closings`` or
``/school-closings``) frames a static file on ``media.foxtv.com``, which the live
poller reads directly. Archived captures (archive-captures runs 36323195832,
36345276947 and 36348669505, 2016 to 2026) show every file format below with rows
(WJBK's export with 640 rows on 26 February 2020 and 471 on 15 January 2026), the
earlier paths of the same files (``kdfw/closings.html``, ``wnyw/closings/closing.htm``,
``witi/closings/index.html``, read the same way), and the older
pages framing files on other hosts (``media2.fox5ny.com``, ``www.fox5dc.org``,
``media.fox9.com``, ``media.fox29.com``, ``media2.fox2detroit.com``,
``wagaradio2.com``; registered as each station's earlier list files, and read in
run 36355124151 in the same formats: WJBK's with 819 rows on 30 January 2019,
WTTG's with 135 on 29 January 2014, WAGA's with 165 in March 2020). Variants
this adapter reads:

``gray-file-newsticker`` and ``gray-file-sc-para``
    The NewsTicker closings system's HTML export (WJBK, WNYW, WTXF, and KDFW when
    empty: ``media.foxtv.com/{call}/closings/closings.html``; empty: one
    ``<TD CLASS="status">There are no active records at this time.</TD>`` under the
    ``TD.timestamp`` "UPDATED SATURDAY, SEP 26 AT 9:05 PM"; rows are
    ``<FONT CLASS="orgname">`` then ``<FONT CLASS="status">`` in one cell, WNYW's
    names prefixed with their state, "NJ: ...") and the SC paragraph file (WAGA:
    ``media.foxtv.com/waga/closings/closings.htm``, empty "Last Updated at 9:08am on
    5/28/2026 <P>No Closings Reported</P>", 58 rows on 9 January 2025). Both are
    vendor formats Gray stations' pages also framed; they are read with
    :func:`snowlight.sources.stations.gray_files.parse` under that module's variant
    names (WNYW 34 rows on 23 February 2026, WTXF 104 on 6 January 2025).

``fox-newsticker-cell``
    The NewsTicker export KDFW and KCPQ write, whose every row is one cell holding
    a category (the city), the name and the status::

        <TR><TD CLASS="timestamp" ...>UPDATED THURSDAY, JAN  9 AT  1:57 PM</TD></TR>
        <TR><TD BGCOLOR="#EEEEEE"><FONT CLASS="category">&nbsp; &nbsp; Aledo </FONT><br>
          <FONT CLASS="orgname">Aledo ISD</FONT>&nbsp; | &nbsp;<FONT CLASS="status">Closed
          Tomorrow</FONT></TD></TR> ...

    The category (when not blank) goes in ``raw_extra["category"]``, a name's
    "[WEB]" link is dropped from the name and kept as ``raw_extra["homepage"]``, and
    the timestamp is every row's ``raw_updated_text`` (KDFW 348 rows on 9 January
    2025, KCPQ one row on 14 March 2026). KCPQ's file from December 2022 to December
    2024 held only its timestamp cell when nothing was listed: the empty state. A
    cell holding anything but a category, a name and a status, or a second
    timestamp, is an error.

``fox-newsticker-county``
    The NewsTicker export with a county menu (KMSP and WITI)::

        <form name="form"><select name="site" ...><option value="">Select a county...<br>
          </select></form>
        <TABLE ...><TD colspan="2" CLASS="timestamp" ALIGN=RIGHT>UPDATED SATURDAY, SEP 26 AT
          8:05 PM</TD></TR>
        <TR><TD colspan="2" CLASS="none"><CENTER>There are no closings or cancellations at
          this time.</CENTER></TD></TR>
        <TR><TD colspan="2" ...><a href="#top"><FONT CLASS="timestamp"><CENTER>Return to top
          </CENTER></a></TD></TR></TABLE>

    The ``none`` sentence is the empty state. With rows (KMSP 17 on 24 March 2024,
    WITI 15 on 19 January 2026), each ``orgname`` element is followed by its
    ``status`` element and each ``county`` element before them (blank in the
    captures seen) is the row's ``raw_extra["county"]``; a name's "[WEB]" link is
    kept as ``raw_extra["homepage"]``; the ``timestamp`` (not the "Return to top"
    link) is every row's ``raw_updated_text``. A file with anything else (an
    ``orgname`` with no ``status``, a ``status`` with no ``orgname``, rows beside
    the ``none`` sentence, neither) is an error.

``fox-closings-table``
    WTTG's file (``media.foxtv.com/wttg/closings/closings.html``): a table whose
    first header cell (``<th colspan="2">``) gives the time ("September 26, 2026
    9:05 pm EDT"). When nothing is listed, a second header says "THERE ARE CURRENTLY
    NO CLOSINGS OR CANCELLATIONS" (the empty state); with rows, a "Location" |
    "Status" header row is followed by one row of two cells per closing (62 rows on
    15 December 2022). A blank opening cell is passed over; a row of any other
    shape, or rows beside the empty header, is an error.

``fox-page-frame``
    A FOX station's closings page, which frames its list file
    (``<iframe ... src="https://media.foxtv.com/wjbk/closings/closings.html">``): a
    :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED` listing whose
    ``follows`` names the framed closings file.

``fox-page-protected-frame``
    FOX 6's page in 2016 (then at ``fox6now.com/weather/closings/``), a WordPress.com
    site whose "protected embed" carries the frame base64-encoded in a form field
    (``<input type="hidden" name="_data" value="PGlmcmFtZSBzcmM9...,<signature>">``,
    decoding to ``<iframe src="http://s3.amazonaws.com/witiclosings/witi.html">``):
    ``DEFERRED``, ``follows`` naming the decoded frame.

``fox-tab-shell``
    The file FOX 6's page framed from 2016 to 2021,
    ``s3.amazonaws.com/witiclosings/witi.html`` (archived 2019 and 2020): a tabbed
    shell (``<div id="horizontalTab">``, tabs Schools, Businesses, Adult/Child
    Care, Churches, Government, Community Org, Hospitals) whose script loads each
    tab's list from a file beside it (``$( "#school_list" ).load(
    "witi_schools.html", ...)``): ``DEFERRED``, ``follows`` naming those files in
    the order the script first loads them, the schools file first (the reader
    follows the first).

``fox-tab-list``
    One tab's list file beside that shell (``witi_schools.html``, archived 17
    April 2020 with 42 rows)::

        <h4>School Closings Last Updated: Fri Apr 17 01:30:02 CDT 2020</h4>
        <ul id="schools" class="closings">
          <li class="ln-a"><span class="place">Atlas Prep Academy | <span
            class="pstatus">Closed</span></li> ...

    Each ``li`` is a row: the ``place`` text before " | " is the name and the
    ``pstatus`` text the status; the heading's words before "Last Updated" go in
    ``raw_extra["category"]`` and the time after it is every row's
    ``raw_updated_text``. An item of any other shape, or a list with no item (the
    file's empty form has not been seen), is an error.

``fox-page-no-closings``
    FOX 6's page in July 2020, which had no frame and said so in its closings
    section (``<div class="wrap single-closings"> ... <h2><strong>There are
    currently no closings</strong></h2>``): the empty state.

A page with no closings frame and neither of those (KRIV's page without a list,
for instance) is an error, and so is anything else:
:class:`~snowlight.sources.stations.model.ShapeError`.
"""

import base64
import binascii
import re
from dataclasses import dataclass, field
from html import unescape

from selectolax.parser import Node

from snowlight.sources.stations import gray_files
from snowlight.sources.stations.body import decode
from snowlight.sources.stations.model import (
    JsonScalar,
    Listing,
    ListingState,
    ParsedRow,
    ShapeError,
)
from snowlight.sources.stations.network_markup import (
    collapse,
    element_end,
    iframe_sources,
    node_text,
    parse_html,
    text_of,
)

COUNTY_MENU = "Select a county..."
COUNTY_EMPTY = "There are no closings or cancellations at this time."
TABLE_EMPTY = "THERE ARE CURRENTLY NO CLOSINGS OR CANCELLATIONS"
RETURN_TO_TOP = "Return to top"
NO_RECORDS = "There are no active records at this time."
PAGE_NO_CLOSINGS = "There are currently no closings"
TAB_SHELL_MARK = '<div id="horizontalTab">'
_TAB_LIST_HEAD = re.compile(
    r"^\s*<h4>(?P<what>[^<]*?)\s*Last Updated:\s*(?P<when>[^<]*)</h4>\s*<ul\b", re.I
)
_TAB_LIST_OPEN = re.compile(r"<ul\b[^>]*\bclass=\"closings\"[^>]*>", re.I)
_TAB_ITEM = re.compile(r"<li\b[^>]*>(.*?)</li>", re.I | re.S)
_TAB_PLACE = re.compile(
    r"^\s*<span class=\"place\">(?P<name>[^<]*?)\s*\|\s*"
    r"<span class=\"pstatus\">(?P<status>[^<]*)</span>(?:\s*</span>)?\s*$",
    re.I,
)
_TAB_LOAD = re.compile(
    r"\$\(\s*[\"']#[a-z]+_list[\"']\s*\)\.load\(\s*[\"']([^\"'/]+\.html?)[\"']", re.I
)
"""What FOX 6's closings page said in place of a frame when nothing was listed (July 2020)."""
_COUNTY_MARK = re.compile(r"<select\b[^>]*\bname=\"site\"", re.IGNORECASE)
_TABLE_MARK = re.compile(r"<th\b[^>]*\bcolspan=\"2\"[^>]*\bbgcolor='999999'", re.IGNORECASE)
_CLOSINGS_FRAME = re.compile(r"^https?://[^/]+/[^?#]*closings?[^?#]*\.html?(?:[?#].*)?$", re.I)
_CLASSES = ("timestamp", "county", "orgname", "status", "none")
_TIMESTAMP_CELL = re.compile(r"<TD\b[^>]*\bCLASS=\"timestamp\"", re.IGNORECASE)
_CELL_FONTS = ["category", "orgname", "status"]
_CATEGORY_CELL = re.compile(
    r"<FONT\b[^>]*\bCLASS=\"category\"[^>]*>[^<]*</FONT>\s*<br>\s*<FONT\b[^>]*\bCLASS=\"orgname\"",
    re.IGNORECASE,
)
_WEB_LINK = re.compile(r"\[\s*<a\b[^>]*\bhref=\"([^\"]*)\"[^>]*>\s*WEB\s*</a>\s*\]", re.IGNORECASE)
_TABLE_HEADER = ["location", "status"]
_PROTECTED_DATA = re.compile(
    r"<input\b[^>]*\bname=\"_data\"[^>]*\bvalue=\"([A-Za-z0-9+/]+=*),[0-9a-f]+\"", re.IGNORECASE
)


def _classed(node: Node) -> str | None:
    names = (node.attributes.get("class") or "").lower().split()
    found = [name for name in _CLASSES if name in names]
    return found[0] if found else None


@dataclass(slots=True)
class _CountyReader:
    """Walks a county-menu file's classed elements in document order."""

    updated: str | None = None
    county: str | None = None
    pending: str | None = None
    homepage: str | None = None
    empty: bool = False
    skipped: int = 0
    rows: list[ParsedRow] = field(default_factory=list)

    def take(self, kind: str, text: str) -> None:
        if kind == "timestamp":
            if text != RETURN_TO_TOP and self.updated is None:
                self.updated = text or None
        elif kind == "none":
            self.empty = self.empty or text == COUNTY_EMPTY
        elif self.pending is not None and kind != "status":
            raise ShapeError(f"a {kind} element follows a name with no status")
        elif kind == "county":
            self.county = text or None
        elif kind == "orgname":
            self.pending = text
        else:
            self._status(text)

    def _status(self, text: str) -> None:
        if self.pending is None:
            raise ShapeError("a status with no name before it")
        extra: dict[str, JsonScalar] = {"updated_scope": "page"} if self.updated else {}
        if self.county is not None:
            extra["county"] = self.county
        if self.homepage is not None:
            extra["homepage"] = self.homepage
        if self.pending:
            self.rows.append(
                ParsedRow(name=self.pending, status=text, updated_text=self.updated, extra=extra)
            )
        else:
            self.skipped += 1
        self.pending = None
        self.homepage = None


def _county_file(html: str) -> Listing:
    tree = parse_html(html)
    if COUNTY_MENU not in node_text(tree.css_first("select[name=site]")):
        raise ShapeError("a county-menu closings file without its county menu")
    reader = _CountyReader()
    for node in tree.css("[class]"):
        kind = _classed(node)
        if kind == "orgname":
            name, homepage = _name_and_link(node)
            reader.take(kind, name)
            reader.homepage = homepage
        elif kind is not None:
            reader.take(kind, node_text(node))
    if reader.pending is not None:
        raise ShapeError("the last name has no status")
    if reader.updated is None:
        raise ShapeError("a county-menu closings file with no update time")
    if reader.rows and reader.empty:
        raise ShapeError("a county-menu file lists rows and says nothing is listed")
    if reader.rows:
        return Listing(
            variant="fox-newsticker-county",
            state=ListingState.POPULATED,
            rows=tuple(reader.rows),
            skipped_rows=reader.skipped,
        )
    if reader.empty and not reader.skipped:
        return Listing(variant="fox-newsticker-county", state=ListingState.EMPTY, rows=())
    raise ShapeError("a county-menu closings file with no rows and no no-closings sentence")


def _is_cell_file(html: str) -> bool:
    """Whether ``html`` is a NewsTicker export whose rows are single cells (KDFW, KCPQ)."""
    if not _TIMESTAMP_CELL.search(html):
        return False
    if _CATEGORY_CELL.search(html):
        return True
    cells = parse_html(html).css("td")
    return len(cells) == 1 and _classed(cells[0]) == "timestamp"


def _name_and_link(node: Node) -> tuple[str, str | None]:
    """A NewsTicker name without its ``[WEB]`` link, and that link's address."""
    html = node.html or ""
    link = _WEB_LINK.search(html)
    name = node_text(parse_html(_WEB_LINK.sub("", html)).body)
    return name, (link.group(1).strip() if link is not None else None)


def _cell_row(cell: Node, updated: str | None) -> ParsedRow | None:
    fonts = cell.css("font")
    kinds = [(font.attributes.get("class") or "").lower() for font in fonts]
    if kinds != _CELL_FONTS:
        raise ShapeError(f"a closings cell holds {kinds!r}, not a category, name and status")
    category, status = node_text(fonts[0]), node_text(fonts[2])
    name, homepage = _name_and_link(fonts[1])
    if not name:
        return None
    extra: dict[str, JsonScalar] = {"updated_scope": "page"} if updated else {}
    if category:
        extra["category"] = category
    if homepage is not None:
        extra["homepage"] = homepage
    return ParsedRow(name=name, status=status, updated_text=updated, extra=extra)


def _cell_file(html: str) -> Listing:
    """Read a NewsTicker export whose rows are single cells (``fox-newsticker-cell``)."""
    cells = parse_html(html).css("td")
    stamps = [node_text(cell) for cell in cells if _classed(cell) == "timestamp"]
    if len(stamps) != 1 or not stamps[0]:
        raise ShapeError("a closings cell file without exactly one update time")
    updated = stamps[0]
    rows: list[ParsedRow] = []
    skipped = 0
    for cell in cells:
        kind = _classed(cell)
        if kind == "timestamp":
            continue
        if kind is not None or cell.attributes.get("class"):
            raise ShapeError(f"a closings cell file holds a {kind or 'classed'} cell")
        row = _cell_row(cell, updated)
        if row is None:
            skipped += 1
        else:
            rows.append(row)
    if skipped and not rows:
        raise ShapeError("every closing in the cell file is missing its name")
    return Listing(
        variant="fox-newsticker-cell",
        state=ListingState.POPULATED if rows else ListingState.EMPTY,
        rows=tuple(rows),
        skipped_rows=skipped,
    )


@dataclass(slots=True)
class _TableReader:
    """Walks WTTG's closings table row by row."""

    time: str | None = None
    header: bool = False
    empty: bool = False
    skipped: int = 0
    rows: list[ParsedRow] = field(default_factory=list)

    def heading(self, texts: list[str]) -> None:
        if self.time is None and len(texts) == 1 and texts[0]:
            self.time = texts[0]
        elif texts == [TABLE_EMPTY] and not self.empty:
            self.empty = True
        elif [text.lower() for text in texts] == _TABLE_HEADER and not self.header:
            self.header = True
        else:
            raise ShapeError(f"a closings table header {texts!r} out of place")

    def cells(self, texts: list[str]) -> None:
        if texts == [""]:
            return  # the blank row the table opens with
        if len(texts) != 2 or not self.header:  # noqa: PLR2004 - a name and a status
            raise ShapeError(f"a closings table row {texts!r} outside the Location/Status columns")
        name, status = texts
        if not name:
            self.skipped += 1
            return
        extra: dict[str, JsonScalar] = {"updated_scope": "page"} if self.time else {}
        self.rows.append(ParsedRow(name=name, status=status, updated_text=self.time, extra=extra))


def _table_file(html: str) -> Listing:
    reader = _TableReader()
    for row in parse_html(html).css("tr"):
        heads, cells = row.css("th"), row.css("td")
        if heads and cells:
            raise ShapeError("a closings table row mixes header and data cells")
        if heads:
            reader.heading([node_text(cell) for cell in heads])
        elif cells:
            reader.cells([node_text(cell) for cell in cells])
    if reader.time is None:
        raise ShapeError("a closings table without its time header")
    if reader.rows and reader.empty:
        raise ShapeError("a closings table lists rows and says nothing is listed")
    if reader.rows:
        return Listing(
            variant="fox-closings-table",
            state=ListingState.POPULATED,
            rows=tuple(reader.rows),
            skipped_rows=reader.skipped,
        )
    if reader.empty and not reader.header and not reader.skipped:
        return Listing(variant="fox-closings-table", state=ListingState.EMPTY, rows=())
    raise ShapeError("a closings table with no rows and no no-closings line")


def _protected_frames(html: str) -> list[str]:
    """The frames a WordPress.com protected embed holds (base64 in its ``_data`` field)."""
    found: list[str] = []
    for match in _PROTECTED_DATA.finditer(html):
        try:
            embed = base64.b64decode(match.group(1), validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as error:
            raise ShapeError(f"a protected embed that does not decode: {error}") from error
        found.extend(src for src in iframe_sources(embed) if _CLOSINGS_FRAME.match(src))
    return found


def _tab_list(html: str, head: re.Match[str]) -> Listing:
    """Read one tab's list file of WITI's tabbed shell (``fox-tab-list``)."""
    opening = _TAB_LIST_OPEN.search(html)
    if opening is None:
        raise ShapeError("a tab list with no closings list")
    items = _TAB_ITEM.findall(html[opening.end() : element_end(html, opening.start(), "ul")])
    rows = []
    for item in items:
        match = _TAB_PLACE.match(item)
        if match is None:
            raise ShapeError(f"a tab list item is not a place and its status: {item[:60]!r}")
        rows.append(
            ParsedRow(
                name=collapse(unescape(match.group("name"))),
                status=collapse(unescape(match.group("status"))),
                updated_text=collapse(head.group("when")) or None,
                extra={"category": collapse(head.group("what")), "updated_scope": "page"},
            )
        )
    if not rows:
        raise ShapeError("a tab list with no item (its empty form is unseen)")
    return Listing(variant="fox-tab-list", state=ListingState.POPULATED, rows=tuple(rows))


def _page(html: str) -> Listing:
    frames = [src for src in iframe_sources(html) if _CLOSINGS_FRAME.match(src)]
    if frames:
        return Listing(
            variant="fox-page-frame",
            state=ListingState.DEFERRED,
            rows=(),
            follows=tuple(dict.fromkeys(frames)),
        )
    tabs = _TAB_LOAD.findall(html) if TAB_SHELL_MARK in html else []
    if tabs:
        return Listing(
            variant="fox-tab-shell",
            state=ListingState.DEFERRED,
            rows=(),
            follows=tuple(dict.fromkeys(tabs)),
        )
    protected = _protected_frames(html)
    if protected:
        return Listing(
            variant="fox-page-protected-frame",
            state=ListingState.DEFERRED,
            rows=(),
            follows=tuple(dict.fromkeys(protected)),
        )
    section = parse_html(html).css_first("div.single-closings")
    if (
        section is not None
        and not section.css("iframe")
        and [node_text(node) for node in section.css("h2")] == [PAGE_NO_CLOSINGS]
    ):
        return Listing(variant="fox-page-no-closings", state=ListingState.EMPTY, rows=())
    raise ShapeError("a FOX page with no closings frame")


def parse(body: bytes) -> Listing:
    """Read a FOX closings file or page (see the module docstring)."""
    raw = decode(body)
    html = text_of(raw)
    if _COUNTY_MARK.search(html) and COUNTY_MENU in html:
        return _county_file(html)
    if _TABLE_MARK.search(html) and "<html" not in html[:2000].lower():
        return _table_file(html)
    if _is_cell_file(html):
        return _cell_file(html)
    tab_head = _TAB_LIST_HEAD.match(html)
    if tab_head is not None:
        return _tab_list(html, tab_head)
    if gray_files.is_file(raw):
        listing = gray_files.parse(raw)
        if listing.variant in {"gray-file-newsticker", "gray-file-sc-para"}:
            return listing
        raise ShapeError(f"a list file in a format FOX files do not use ({listing.variant})")
    if "<html" in html[:5000].lower() or "<!doctype" in html[:200].lower():
        return _page(html)
    raise ShapeError("not a FOX closings file or page this adapter knows")
