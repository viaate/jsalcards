"""Gray station closings pages from before Gray's Arc XP sites (read from Wayback captures).

:mod:`snowlight.sources.stations.gray` reads the current formats and hands pages it
does not recognize to :func:`parse`, which knows the older ones. Every variant here
was seen on archived captures of a registered station's closings page:

``gray-gdm-table``
    The Gray Digital Media page (seen at WBKO, WDBJ, KCRG, KKTV, KWCH and WVLT from
    2015 to 2018, and in its empty state at WBKO in 2014): the list
    is server-rendered as one table per organization type::

        <h2>School and Organization Closings and Delays</h2>
        <section>
          <p class="pull-right"><em>Last Updated: 01/08/2017 06:32 PM</em></p>
          <h3 ...>Type: Schools <small>...</small></h3>
          <table class='table table-condensed table-striped'>
            <tr><th>Organization</th><th>Status</th>[<th>State</th>]</tr>
            <tr><td><b>Name</b></td><td>Closed Monday<small>: comment</small></td>
                [<td><b>VA</b></td>]</tr> ...

    From 2014 to 2015 the same content sits in ``<div id="ClosingsModule1">``
    under an ``<h2>`` heading of its own ("School Closings"). Each row's name is the first
    cell; its status is the second cell's own text (without the ``<small>``
    comment). The comment (its leading ": " dropped), the organization type from
    the table's heading, and any further column (by its header, e.g. ``state``)
    go in ``raw_extra``; runs of whitespace in cell text are collapsed to one
    space. The page states one update time for the whole list
    ("Last Updated: ..."); it is each row's ``raw_updated_text``, and
    ``raw_extra["updated_scope"]`` is ``"page"`` to say so. The page's own
    sentence "Currently no closings or delays have been reported" with no table
    is the empty state.

``gray-gdm-list``
    The ``ClosingsModule1`` block as served in 2014 at KKTV: the same headings,
    but each row is a line, not a table row::

        <h3 ...>Type: Schools</h3>
        <div ...><span style='font-weight:bold' >D-11 Col Springs</span>
          - Status: As Scheduled</div>

    The name is the bold span; the status is the text after "- Status:"; the type
    heading goes in ``raw_extra`` as for tables.

``gray-gdm-script``
    The same page as served in 2019: the section holds a script that downloads
    the station's S3 GSync export (``grayfilestore-{call}/closingsData/...``) and
    draws the list in the browser, so the page itself holds neither the list nor
    a count: a :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED`
    listing whose ``follows`` is the export URL the script names
    (``var url = 'https://s3.amazonaws.com/grayfilestore-wbko/...json?c=n&r=...'``).

``gray-frame``
    The page shows its list in an ``<iframe>`` whose ``src`` names a closings file
    on another host, so the page holds neither the list nor a count
    (``DEFERRED``; ``follows`` is the frame's ``src``). Seen at WDBJ before Gray
    owned it (2014 to 2016, an ibPublish site framing
    ``wdbj7ftp.us/sch_closings/...``), at KCRG in 2015 and 2016 (a Gray Digital
    Media page framing ``gray.ftp.clickability.com/kcrgwebftp/closings.html``) and
    at the former Raycom stations from 2018 to 2020 (framing
    ``webpubcontent.raycommedia.com/{site}/closings.html``).

    From late 2019 to 2021 the former Raycom stations framed Raycom's GSync Web
    Embeds application instead (``//webpubcontent.raycommedia.com/raycom/gsync/
    #/embed/closings/{site}``), a script application that holds no list: it reads
    the station's S3 GSync export. Its own script (``static/js/main.*.chunk.js``,
    captured 2020-03-11, 2020-12-09 and 2021-11-19) builds that export's address
    from the frame's ``{site}``: ``https://s3.amazonaws.com/grayfilestore-{s}/
    closingsData/closings_{S}.json``, where ``s`` and ``S`` are the site in lower
    and upper case after the script's renames (``kfvs12`` is ``kfvs``, ``wmctv``
    is ``wmc``, ``wistv`` is ``wis``, ``full-court-press`` is ``fcp``). For such
    a frame, ``follows`` is that export (the application's shell names no file
    itself; see :func:`gsync_export`).

    The Allen Media stations Gray bought in 2025 (their TownNews BLOX sites,
    2021 to 2026) frame an HTML file on the station's ``ftp2.`` host (WJRT
    ``ftp2.wjrt.com/school_closings/wjrtclosings.html``, WLFI
    ``ftp2.wlfi.com/SC/WLFI_schools.HTM``, WTHI ``ftp2.wthitv.com/NWT/closings.html``,
    WTVA ``ftp2.wtva.com/All_Active.html``); such a frame counts even without
    "closing" in its path, and wins over a banner script on the same page. So does
    a frame of a CGS "All Active" page on another host (WTVA's 2018 page,
    ``http://cgs.wtva.com/wtva/All_Active.html``).
    ``follows`` holds the frame's ``src`` as the page writes it.

``gray-blox-script``
    A TownNews BLOX page (its tags carry ``tncms-`` names) served at the station's
    address before it moved to Gray's Arc site: the Meredith stations from 2018 to
    2020 (a script loads ``lmgcorporate.com/closings/.../*.xml``) and the Allen
    Media stations Gray bought, until 2025 (a script loads an
    ``amb-feeds.s3.amazonaws.com/{CALL}_closings.json`` counter, or at KAKE
    ``/app/closings/closings.xml``). The page holds neither the list nor a count
    (``DEFERRED``); ``follows`` holds the file the script names. (An
    ``amb-feeds`` file is only a banner's counter; a page that also frames its
    list is read as ``gray-frame``.)

``gray-heartland-newsticker``, ``gray-heartland-sc-para``
    A Heartland Media page (WLFI and WTHI before Allen Media's BLOX sites, 2019
    to 2021) writes its closings file into the page itself, right after the
    list's "Refresh Data" button::

        <div><a class="btn btn-secondary float-right" href="...">Refresh Data</a></div>
        Last Updated at 2:13am on 2/17/2021
        <P><B><h2>---- Schools</h2></B><br>
        <P><b>Attica Consolidated School Corp.</b><br>Closed - Tomorrow E-Learning Day ...

    The text from the button's ``</div>`` to the ``</div>`` that closes the list's
    container is the file, byte for byte: at WTHI a NewsTicker HTML export (read
    as ``gray-file-newsticker`` is), at WLFI the SC paragraph file (read as
    ``gray-file-sc-para`` is). The variant names the page and the format. (WTVA's
    Heartland page framed its file instead: ``gray-frame``.)

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`.
"""

import re
from collections.abc import Callable

from selectolax.parser import HTMLParser, Node

from snowlight.sources.stations import gray_files
from snowlight.sources.stations.model import (
    JsonScalar,
    Listing,
    ListingState,
    ParsedRow,
    ShapeError,
)

_SECTION_HEADING = re.compile(
    rb"<h2>\s*School and Organization Closings and Delays\s*</h2>\s*(?=<section\b)"
)
_MODULE = re.compile(rb'<div id="ClosingsModule1"[^>]*>')
_FRAME = re.compile(
    rb"<iframe\b[^>]*\bsrc=([\"'])[^\"'?>]*closing[^\"'>]*\1[^>]*>(?:\s*</iframe>)?", re.IGNORECASE
)
_FRAME_FTP2 = re.compile(
    rb"<iframe\b[^>]*\bsrc=([\"'])(?:https?:)?//ftp2\.[A-Za-z0-9.-]+/[^\"'?>]*\.html?\1[^>]*>"
    rb"(?:\s*</iframe>)?",
    re.IGNORECASE,
)
_FRAME_CGS = re.compile(
    rb"<iframe\b[^>]*\bsrc=([\"'])(?:https?:)?//[A-Za-z0-9.-]+/[^\"'?>]*All_Active\.html?\1[^>]*>"
    rb"(?:\s*</iframe>)?",
    re.IGNORECASE,
)
_BLOX_MARK = re.compile(rb"<[a-z]+\b[^>]*\btncms-[^>]*>")
_BLOX_SOURCE = re.compile(
    rb"lmgcorporate\.com/closings/[A-Za-z0-9_./-]+"
    rb"|amb-feeds\.s3\.amazonaws\.com/[A-Za-z0-9]+_closings\.json"
    rb"|/app/closings/[A-Za-z0-9_./-]*\.xml"
)
_BLOX_REFERENCE = re.compile(
    rb"[\"']((?:https?:)?//[^\"'\s]*?(?:lmgcorporate\.com/closings/|amb-feeds\.s3\.amazonaws\.com/)"
    rb"[^\"'\s]*|(?:(?:https?:)?//[^\"'\s/]+)?/app/closings/[^\"'\s]*\.xml)[\"']"
)
_SCRIPT_EXPORT = re.compile(rb"grayfilestore-[a-z0-9]+/closingsData/closings_[A-Za-z0-9]+\.json")
_SCRIPT_URL = re.compile(
    rb"\burl\s*=\s*([\"'])(https://s3\.amazonaws\.com/grayfilestore-[a-z0-9]+/closingsData/"
    rb"closings_[A-Za-z0-9]+\.json[^\"'\s]*)\1"
)
_FRAME_SOURCE = re.compile(rb"\bsrc=([\"'])([^\"']+)\1", re.IGNORECASE)
_GSYNC_EMBED = re.compile(
    r"^(?:https?:)?//webpubcontent\.raycommedia\.com/raycom/gsync/?"
    r"#/embed/closings/(?P<site>[A-Za-z0-9-]+)/?$"
)
_GSYNC_RENAMES = {"kfvs12": "kfvs", "wmctv": "wmc", "wistv": "wis", "full-court-press": "fcp"}
"""The GSync embed script's own renames of a frame's site (its ``R`` function)."""
_HEARTLAND_BUTTON = re.compile(
    rb'<div><a class="btn btn-secondary float-right" href="[^"<>]*">Refresh Data</a></div>'
)
_DIV_TAG = re.compile(rb"<(/?)div\b[^>]*>", re.IGNORECASE)
_HEARTLAND_FORMATS = {
    "gray-file-newsticker": "gray-heartland-newsticker",
    "gray-file-sc-para": "gray-heartland-sc-para",
}
_NO_CLOSINGS = "Currently no closings or delays have been reported"
_LAST_UPDATED = re.compile(r"Last Updated:\s*([^<]*?)\s*<")
_TYPE = re.compile(r"^\s*Type:\s*", re.IGNORECASE)
_LIST_STATUS = re.compile(r"^-\s*Status:\s*(.*)$", re.DOTALL)
_SPACE = re.compile(r"\s+")
_NAME_HEADER, _STATUS_HEADER = "organization", "status"


def _tag_span(html: bytes, start: int, tag: bytes) -> int:
    """Return the end offset of the ``<tag>`` element that opens at ``start``."""
    pattern = re.compile(rb"<(/?)" + tag + rb"\b", re.IGNORECASE)
    depth = 0
    for match in pattern.finditer(html, start):
        depth += -1 if match.group(1) else 1
        if depth == 0:
            close = html.find(b">", match.end())
            if close < 0:
                break
            return close + 1
    raise ShapeError(f"the closings <{tag.decode()}> is not closed")


def container(html: bytes) -> bytes | None:
    """Return the closings block of a Gray Digital Media page, byte for byte, if any.

    That is the ``School and Organization Closings and Delays`` heading with the
    ``<section>`` after it, or the ``ClosingsModule1`` block of the older layout.
    """
    heading = _SECTION_HEADING.search(html)
    if heading is not None:
        return html[heading.start() : _tag_span(html, heading.end(), b"section")]
    module = _MODULE.search(html)
    if module is not None:
        return html[module.start() : _tag_span(html, module.start(), b"div")]
    return None


def heartland_parts(html: bytes) -> tuple[bytes, bytes] | None:
    """Return a Heartland page's "Refresh Data" button and the list file after it, if any.

    The file runs from the button's ``</div>`` to the first ``</div>`` it does not
    open itself (the one that closes the list's container).
    """
    button = _HEARTLAND_BUTTON.search(html)
    if button is None:
        return None
    depth = 0
    for tag in _DIV_TAG.finditer(html, button.end()):
        depth += -1 if tag.group(1) else 1
        if depth < 0:
            return button.group(0), html[button.end() : tag.start()]
    raise ShapeError("the Heartland closings list is not closed")


def heartland(html: bytes) -> Listing | None:
    """Read a Heartland page's inline list (``gray-heartland-*``), or None if not one."""
    parts = heartland_parts(html)
    if parts is None:
        return None
    listing = gray_files.parse(parts[1])
    variant = _HEARTLAND_FORMATS.get(listing.variant)
    if variant is None:
        raise ShapeError(f"a Heartland page holds a {listing.variant} list, not a known one")
    return listing.model_copy(update={"variant": variant})


def slice_heartland(html: bytes) -> bytes | None:
    """Cut a Heartland page to its button and inline list, byte for byte (or None)."""
    parts = heartland_parts(html)
    if parts is None:
        return None
    sliced = b"<!doctype html>\n<html><body>\n<div>" + b"".join(parts) + b"</div>\n</body></html>\n"
    if heartland(sliced) != heartland(html):
        raise ShapeError("the sliced Heartland page does not read as the page does")
    return sliced


def frame(html: bytes) -> bytes | None:
    """Return the iframe element that shows a page's closings list, if any.

    That is the first ``<iframe>`` whose ``src`` has "closing" in its path or
    fragment (a query string does not count, so a tag manager frame whose query
    names the page is not one), or else the first that frames an HTML file on an
    ``ftp2.`` host (Allen Media's closings files, e.g.
    ``https://ftp2.wlfi.com/SC/WLFI_schools.HTM``), or else the first that frames
    a CGS "All Active" closings page (WTVA's 2018 page frames
    ``http://cgs.wtva.com/wtva/All_Active.html``).
    """
    match = _FRAME.search(html) or _FRAME_FTP2.search(html) or _FRAME_CGS.search(html)
    return match.group(0) if match is not None else None


def _frame_v2(html: bytes) -> bytes | None:
    """The frame rule ``gray-page-v2`` slices by (before ``ftp2.`` frames were known)."""
    match = _FRAME.search(html)
    return match.group(0) if match is not None else None


def frame_source(element: bytes) -> str:
    """Return the ``src`` of a closings ``<iframe>`` element as the page writes it."""
    match = _FRAME_SOURCE.search(element)
    if match is None:
        raise ShapeError("the closings frame has no src")
    return match.group(2).decode("utf-8", errors="replace").strip()


def gsync_export(source: str) -> str | None:
    """Return the S3 export a GSync Web Embeds closings frame loads, or None if not one.

    ``source`` is the frame's ``src`` as the page writes it. The rule is the
    embed script's own: the site after ``#/embed/closings/``, renamed as the
    script renames it, in lower case for the bucket and upper case for the file.
    """
    match = _GSYNC_EMBED.match(source)
    if match is None:
        return None
    site = _GSYNC_RENAMES.get(match.group("site"), match.group("site"))
    return (
        f"https://s3.amazonaws.com/grayfilestore-{site.lower()}/closingsData/"
        f"closings_{site.upper()}.json"
    )


def frame_listing(element: bytes, variant: str) -> Listing:
    """Return the deferred listing of a page whose closings frame is ``element``."""
    source = frame_source(element)
    return Listing(
        variant=variant,
        state=ListingState.DEFERRED,
        rows=(),
        follows=(gsync_export(source) or source,),
    )


def blox_parts(html: bytes) -> tuple[bytes, bytes] | None:
    """Return a TownNews BLOX page's first ``tncms-`` tag and the script naming its list.

    ``None`` unless the page is a BLOX page (a tag carrying a ``tncms-`` name) and a
    ``<script>`` in it names a closings file it loads (see ``gray-blox-script``).
    """
    mark = _BLOX_MARK.search(html)
    source = _BLOX_SOURCE.search(html)
    if mark is None or source is None:
        return None
    start = html.rfind(b"<script", 0, source.start())
    end = html.find(b"</script>", source.end())
    if start < 0 or end < 0 or html.find(b"</script>", start, source.start()) >= 0:
        return None
    return mark.group(0), html[start : end + len(b"</script>")]


def _clean(text: str) -> str:
    return _SPACE.sub(" ", text).strip()


def _headers(row: Node) -> list[str] | None:
    cells = row.css("th")
    if not cells:
        return None
    headers = [_clean(cell.text()).lower() for cell in cells]
    if headers[:2] != [_NAME_HEADER, _STATUS_HEADER]:
        raise ShapeError(f"a closings table's columns are {headers}, not Organization, Status")
    return headers


def _row(
    cells: list[Node], headers: list[str], kind: str | None, updated: str | None
) -> ParsedRow | None:
    if len(cells) != len(headers):
        raise ShapeError(f"a closings row has {len(cells)} cells for {len(headers)} columns")
    name = _clean(cells[0].text())
    if not name:
        return None
    status_cell = cells[1]
    comment_node = status_cell.css_first("small")
    extra: dict[str, JsonScalar] = {}
    if updated is not None:
        extra["updated_scope"] = "page"
    if kind is not None:
        extra["type"] = kind
    if comment_node is not None:
        extra["comment"] = _clean(comment_node.text()).removeprefix(":").strip()
    for header, cell in zip(headers[2:], cells[2:], strict=True):
        extra[header] = _clean(cell.text())
    return ParsedRow(
        name=name,
        status=_clean(status_cell.text(deep=False)),
        updated_text=updated,
        extra=extra,
    )


def _list_row(div: Node, kind: str | None, updated: str | None) -> ParsedRow | None:
    """Read a ``<div><span style="font-weight:bold">Name</span> - Status: ...</div>`` row."""
    children = list(div.iter(include_text=False))
    if not children or children[0].tag != "span":
        return None
    if "bold" not in (children[0].attributes.get("style") or ""):
        return None
    match = _LIST_STATUS.match(_clean(div.text(deep=False)))
    if match is None:
        return None
    name = _clean(children[0].text())
    if not name:
        raise ShapeError("a closings list row has no name")
    extra: dict[str, JsonScalar] = {}
    if updated is not None:
        extra["updated_scope"] = "page"
    if kind is not None:
        extra["type"] = kind
    return ParsedRow(name=name, status=match.group(1), updated_text=updated, extra=extra)


def _table_rows(table: Node, kind: str | None, updated: str | None) -> tuple[list[ParsedRow], int]:
    """Read one closings table: its rows, and how many rows had no name."""
    rows: list[ParsedRow] = []
    skipped = 0
    headers: list[str] | None = None
    for tr in table.css("tr"):
        found = _headers(tr)
        if found is not None:
            headers = found
            continue
        if headers is None:
            raise ShapeError("a closings table has a row before its header")
        row = _row(tr.css("td"), headers, kind, updated)
        if row is None:
            skipped += 1
        else:
            rows.append(row)
    return rows, skipped


def _blox_reference(script: bytes) -> str:
    match = _BLOX_REFERENCE.search(script)
    if match is None:
        raise ShapeError("the BLOX closings script names no file it loads")
    return match.group(1).decode("utf-8")


def parse_container(block: bytes) -> Listing:
    """Read a Gray Digital Media closings block (``gray-gdm-table``, ``-list`` or ``-script``)."""
    if b"<script" in block and _SCRIPT_EXPORT.search(block):
        loads = _SCRIPT_URL.search(block)
        if loads is None:
            raise ShapeError("the closings script names no export URL it loads")
        return Listing(
            variant="gray-gdm-script",
            state=ListingState.DEFERRED,
            rows=(),
            follows=(loads.group(2).decode("utf-8"),),
        )
    text = block.decode("utf-8", errors="replace")
    stamp = _LAST_UPDATED.search(text)
    updated = stamp.group(1) if stamp is not None and stamp.group(1) else None
    tree = HTMLParser(text)
    rows: list[ParsedRow] = []
    listed: list[ParsedRow] = []
    skipped = tables = 0
    kind: str | None = None
    for node in tree.root.traverse() if tree.root is not None else ():
        if node.tag == "div":
            item = _list_row(node, kind, updated)
            listed += [item] if item is not None else []
        elif node.tag == "h3":
            heading = _clean(node.text(deep=False))
            kind = _TYPE.sub("", heading) if _TYPE.match(heading) else None
        elif node.tag == "table":
            tables += 1
            found, nameless = _table_rows(node, kind, updated)
            rows += found
            skipped += nameless
    if rows and listed:
        raise ShapeError("the closings block mixes tables and list rows")
    if listed:
        return Listing(variant="gray-gdm-list", state=ListingState.POPULATED, rows=tuple(listed))
    if rows:
        return Listing(
            variant="gray-gdm-table",
            state=ListingState.POPULATED,
            rows=tuple(rows),
            skipped_rows=skipped,
        )
    if skipped:
        raise ShapeError("every row in the closings tables is missing its name")
    if not tables and _NO_CLOSINGS in text:
        return Listing(variant="gray-gdm-table", state=ListingState.EMPTY, rows=())
    raise ShapeError("the closings block has no rows and no no-closings sentence")


def parse(html: bytes) -> Listing:
    """Read an older Gray station page (``gray-gdm-*``, ``gray-frame``, ``gray-blox-script``,
    ``gray-heartland-*``)."""
    inline = heartland(html)
    if inline is not None:
        return inline
    block = container(html)
    if block is not None:
        return parse_container(block)
    element = frame(html)
    if element is not None:
        return frame_listing(element, "gray-frame")
    parts = blox_parts(html)
    if parts is not None:
        return Listing(
            variant="gray-blox-script",
            state=ListingState.DEFERRED,
            rows=(),
            follows=(_blox_reference(parts[1]),),
        )
    raise ShapeError("not a Gray closings body this adapter knows")


def slice_page(html: bytes) -> bytes:
    """Cut a pre-Arc page down to its closings parts (``gray-page-v2``), each byte for byte.

    A Gray Digital Media page keeps its closings block (the heading and its
    ``<section>``, or the ``ClosingsModule1`` block); a ``gray-frame`` page keeps its
    closings iframe element; a ``gray-blox-script`` page keeps its first ``tncms-``
    tag and the script that names its closings file. The parts are wrapped in a
    minimal document. This method's output is frozen: it knows only frames with
    "closing" in their path (see :func:`slice_page_v3`).
    """
    return _slice(html, _frame_v2)


def slice_page_v3(html: bytes) -> bytes:
    """As :func:`slice_page`, with every frame :func:`frame` knows (``gray-page-v3``).

    The slice must read exactly as the whole page does.
    """
    sliced = _slice(html, frame)
    if parse(sliced) != parse(html):
        raise ShapeError("the sliced page does not read as the page does")
    return sliced


def _slice(html: bytes, find_frame: Callable[[bytes], bytes | None]) -> bytes:
    kept = container(html)
    if kept is None:
        kept = find_frame(html)
    if kept is None:
        parts = blox_parts(html)
        kept = b"\n".join(parts) if parts is not None else None
    if kept is None:
        raise ShapeError("not a Gray closings body this adapter knows")
    parse(kept)
    return b"<!doctype html>\n<html><body>\n" + kept + b"\n</body></html>\n"
