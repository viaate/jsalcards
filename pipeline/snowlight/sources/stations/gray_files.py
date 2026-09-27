"""Closings list files that Gray station pages framed or loaded (read from Wayback captures).

Before Gray's Arc sites (and at a few stations after), a closings page often held
no list: it framed an HTML file on another host or loaded a data file by script
(``gray-frame``, ``gray-fusion-frame``, ``gray-blox-script``,
``gray-gdm-script``; see :mod:`snowlight.sources.stations.gray_legacy`). The
archive reader follows such a page to the capture of that file nearest in time
and reads it with this module. Every variant here was seen in Wayback ``id_``
captures of a file a registered station's page named:

``gray-file-newsticker``
    The NewsTicker closings system's HTML export (the Raycom stations'
    ``webpubcontent.raycommedia.com/{site}/.../closings.html``, 2018 to 2020;
    ``webpubcontent.gray.tv/{site}/.../*.html`` at KPTV's, WEEK's, WFSB's, WGGB's
    and WLIO's pages, 2022 to 2026; KCRG's
    ``gray.ftp.clickability.com/kcrgwebftp/closings.html``, 2015 to 2016; WTHI's
    ``ftp2.wthitv.com/NWT/closings.html``, 2024). One update time for the whole
    file (``<TD CLASS="timestamp">UPDATED FRIDAY, MAR 22 AT 10:50 AM</TD>``, or a
    ``<div CLASS="timestamp">``), then one line per organization::

        <FONT CLASS="orgname">Name</FONT>: <FONT CLASS="status">Status</FONT>

    or, at WAFB, ``<TD class="school">Name</TD><TD class="details">Status</TD>``.
    Rows may sit under group headings (``<CENTER><A NAME=...></A><FONT
    CLASS="orgname">CHURCHES</CENTER>``: a category or a county) and, at WAVE,
    under ``<div class="statename">`` and ``<div class="categoryname">`` headings;
    each heading in force goes in ``raw_extra`` (``group``, ``state``,
    ``category``). A name may be a link (its text is the name) or carry a
    ``[WEB]`` link after it (dropped from the name; its address is
    ``raw_extra["homepage"]``). The file's update time is each row's
    ``raw_updated_text`` (``raw_extra["updated_scope"]`` is ``"page"``). The file's
    own sentence "There are no active records at this time." is the empty state.

``gray-file-newsticker-xml``
    NewsTicker's XML export (``www.kake.com/app/closings/closings.xml``, 2025):
    ``<DATA>`` with ``SOURCE``, ``EXPORT_TYPE``, ``NUM_CLOSINGS``, ``RUN_DATE``,
    ``RUN_EPOCH`` and one ``RECORD`` per organization, whose fields (declared in
    the file's own DTD) are the S3 export's in capitals:
    ``FORCED_ORGANIZATION_NAME`` is the name, ``FORCED_STATUS_NAME`` the status,
    ``UPDATED`` the update text, and every other field goes in ``raw_extra`` under
    its name in lower case. ``NUM_CLOSINGS`` is the declared count and must equal
    the records read; zero records with ``NUM_CLOSINGS`` 0 is the empty state.

``gray-file-ticker-xml``
    The Meredith stations' closings ticker
    (``lmgcorporate.com/closings/kctv/closings.xml``, 2018 to 2020)::

        <ticker lastupdate="01/21/2020 05:39:18 PM">
        <closing id="052980"><type>Schools</type><name>...</name><state>MO</state>
          <status>Closed </status><updatetime>01/21/2020 05:09:53 PM</updatetime></closing>

    Each ``closing`` is a row: ``name``, ``status`` and ``updatetime`` (outer
    spaces trimmed), with ``id``, ``type`` and ``state`` in ``raw_extra``. The
    ticker's own text "There are no closings at this time." with no ``closing``
    is the empty state.

``gray-file-sc-xml``
    The closings XML the Meredith and WDBJ pages loaded (``KMOV-SC45C.xml``,
    ``WSMV-SC4C.xml``, ``WDBJ-SC4C.xml``, WNEM's ``schools.xml``): ``<File
    Time="...">`` holding one ``<Closing>`` per organization, with or without an
    ``<?xml ...?>`` declaration first (WNEM's file has none). ``Name1`` is the name
    and ``Status`` the status (WDBJ's own script shows ``Status`` and
    ``Status2``); every other child element's text goes in ``raw_extra`` under its
    tag. A ``File`` with no ``Closing`` is the empty state; its ``Time`` is each
    row's update text.

``gray-file-count-json``
    Allen Media's banner counter
    (``amb-feeds.s3.amazonaws.com/{CALL}_closings.json``)::

        {"title": "School and Business Closings", "station": "WLFI",
         "closingsURL": "https://www.wlfi.com/weather/closings/", "numClosings": "0"}

    A count, not a list: ``numClosings`` 0 is the empty state, any other count is
    :attr:`~snowlight.sources.stations.model.ListingState.COUNT_ONLY`. The
    ``closingsURL`` is the station page, not a list file, so nothing is followed.
    A counter written with a blank count (``"numClosings": ""``, WTVA's on
    2025-01-26) says neither how many nor who: ``DEFERRED``, with nothing to follow.

``gray-file-grid``
    The closings table WJRT (``ftp2.wjrt.com/school_closings/wjrtclosings.html``,
    2022 to 2025) and WHNS (``lmgcorporate.com/whns/closings/all.htm``, 2020 to
    2021) framed: "Closings Last Updated at 10:52pm on 2/02/2022" over a
    three-column table, one row per organization::

        <tr><td width="33%"><b>Alma Schools&nbsp;</b></td><td width="33%">Closed&nbsp;</td>
            <td width="33%">No after school activities&nbsp;</td></tr>

    The bold first cell is the name, the second cell the status, and the third
    (a comment, often blank) goes in ``raw_extra["comment"]`` when it holds text;
    ``&nbsp;`` and runs of whitespace become one space and the ends are trimmed.
    The file's update time is each row's ``raw_updated_text``
    (``raw_extra["updated_scope"]`` is ``"page"``). The single row "No Closings
    have been reported at this time" with blank cells is the empty state.

``gray-file-sc-para``
    The closings file WLFI framed (``ftp2.wlfi.com/SC/WLFI_schools.HTM``, 2022 to
    2025) and, before that, wrote into its own page (see ``gray-heartland-*`` in
    :mod:`snowlight.sources.stations.gray_legacy`): one line "Last Updated at 11:42am
    on 2/01/2022", then group headings and one paragraph per organization::

        <P><B><h2>---- Small Business</h2></B><br>
        <P><b>Leggett & Platt</b><br>Closed Wendesday - Friday C Shift Resumes ...
        </P></P>

    The bold text is the name and the text after its ``<br>`` (up to the next
    tag) the status; the heading in force, without its leading dashes, goes in
    ``raw_extra["group"]``. The time after "Last Updated at" is each row's
    ``raw_updated_text`` (``raw_extra["updated_scope"]`` is ``"page"``). The single
    paragraph "No Closings Reported" is the empty state.

``gray-file-cgs``
    The "All Active" closings page of CGS Infographics Automation that WTVA framed
    (``ftp2.wtva.com/All_Active.html``, 2019 to 2024): a ``<div class="msg">`` time
    stamp and a table. Every capture of it downloaded so far is in its empty state,
    the sentence "There are no 'All Active' closings to report." in a ``msg``
    cell; the populated form has not been seen in any capture, so a file that
    holds anything else raises :class:`~snowlight.sources.stations.model.ShapeError`
    rather than being read by guesswork.

``gray-file-mobile-cells``
    WDBJ's mobile closings page (``wdbj7ftp.us/sch_closings/mobile_closings_site.php``,
    2015 to 2016), written by the server in two tabs, "School Closings" and "Other
    Closings" (the tab links name them), one list item per organization::

        <li id='closing_cell' class='radius'> <div id='closing_name' ...>Amherst County
          Schools</div> <div id='closing_desc' ...> Closed Wednesday</div><div
          id='closing_desc2' ...> Employee Code 1</div></li>

    ``closing_name`` is the name and ``closing_desc`` the status (it may be blank
    when only the second line says something); a non-blank ``closing_desc2`` goes in
    ``raw_extra["status2"]`` (the second status line of WDBJ's SC files) and the tab
    in ``raw_extra["tab"]``. A tab whose only item is "There are no SCHOOL closings"
    (or OTHER) with a blank status is empty; both tabs empty is the empty state.

``gray-file-flashalert``
    The FlashAlert Newswire report KPTV framed
    (``lmgcorporate.com/closings/kptv/schoolclosures.html``, 2019 to 2021, and
    ``webpubcontent.gray.tv/kptv/closings/schoolclosures.html``, 2024): a
    ``cwcReportHeader`` ("Portland/Vanc/Salem School Closures for Tue. Mar. 17 -
    7:40 pm") over category headings and one report per organization::

        <div class='cwcReportCat'>Clackamas Co. Schools</div>
        <div class='cwcReport'><strong>Estacada Sch. Dist.</strong>&nbsp;- Virtual
          school days March 16-20. ... <span ...>(For Tue. Mar 17th)</span></div>

    The first ``<strong>`` is the name; the report's remaining text after the
    "- " that follows the name is the status, kept whole (a day it applies to,
    "(For Tue. Mar 17th)", or an "UPDATE" mark included), whitespace collapsed.
    The category heading in force goes in ``raw_extra["category"]``. The header
    text is each row's ``raw_updated_text`` (``raw_extra["updated_scope"]`` is
    ``"page"``). A single report "No information reported." is the empty state.

``gray-file-sc-script``
    WDBJ's framed closings page (``wdbj7ftp.us/sch_closings/
    site_closings_noscroll.html``, 2013 to 2016) holds no list: its script
    requests an SC XML file (``xmlhttp.open("GET","../WDBJ-SC4C.xml?random=" +
    ...)``) and writes the list in the browser. A
    :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED` listing whose
    ``follows`` is that file, as the script names it (its random query dropped).

``gray-file-gsync-embed``
    Raycom's "GSync Web Embeds" application
    (``webpubcontent.raycommedia.com/raycom/gsync/``, 2019 to 2021), which the
    station pages framed as ``.../raycom/gsync/#/embed/closings/{site}``: a
    script application shell whose list the browser loads afterwards; the shell
    names no list file. ``DEFERRED`` with nothing to follow. A page framing it is
    followed straight to the station's S3 export instead (see
    :func:`snowlight.sources.stations.gray_legacy.gsync_export`), and archived
    captures of the application are set aside as the Gray platform's shared path.

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`.
"""

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from xml.etree import ElementTree

from selectolax.parser import HTMLParser

from snowlight.sources.stations.body import decode
from snowlight.sources.stations.model import (
    JsonScalar,
    Listing,
    ListingState,
    ParsedRow,
    ShapeError,
)

_FLAGS = re.IGNORECASE | re.DOTALL
_SPACE = re.compile(r"\s+")

# NewsTicker HTML ---------------------------------------------------------------------

_NT_TIMESTAMP = re.compile(r"<(td|div)\b[^>]*\bclass=\"?timestamp\"?[^>]*>(.*?)</\1>", _FLAGS)
_NT_EMPTY = "There are no active records at this time."
_NT_TOKEN = re.compile(
    r"(?P<row><font\s+class=\"?orgname\"?\s*>(?P<name>.*?)</font>\s*:\s*"
    r"<font\s+class=\"?status\"?\s*>(?P<status>.*?)</font>)"
    r"|(?P<heading><center>\s*(?:<a\s+name=[^>]*>\s*(?:</a>)?\s*)?"
    r"<font\s+class=\"?orgname\"?\s*>(?P<group>.*?)</center>)"
    r"|(?P<school><td\s+class=\"?school\"?\s*>(?P<sname>.*?)</td>\s*"
    r"<td\s+class=\"?details\"?\s*>(?P<sstatus>.*?)</td>)"
    r"|(?P<div><div\s+class=\"?(?P<kind>statename|categoryname)\"?\s*>(?P<label>.*?)</div>)",
    _FLAGS,
)
_NT_ORGNAME = re.compile(r"class=\"?orgname\"?", re.IGNORECASE)
_NT_MARK = re.compile(r"class=\"?(?:orgname|school)\"?", re.IGNORECASE)
_WEB_LINK = re.compile(r"\[\s*<a\b[^>]*\bhref=\"([^\"]*)\"[^>]*>\s*WEB\s*</a>\s*\]", _FLAGS)

# Other formats -----------------------------------------------------------------------

_GRID_STAMP = re.compile(r"Closings Last Updated at\s*([^<]*?)\s*<", re.IGNORECASE)
_GRID_EMPTY = "No Closings have been reported at this time"
_GRID_ROW = re.compile(r"<tr\b[^>]*>(.*?)</tr>", _FLAGS)
_GRID_CELL = re.compile(r"<td\b[^>]*>(.*?)</td>", _FLAGS)
_GRID_COLUMNS = 3
_BOLD = re.compile(r"^\s*<b>(.*?)</b>\s*$", _FLAGS)
_FLASH_CONTAINER = "id='cwcReportContainer'"
_FLASH_HEADER = re.compile(r"<div id='cwcReportHeader'>(.*?)</div>", _FLAGS)
_FLASH_TOKEN = re.compile(
    r"<div class='cwcReportCat'>(?P<category>.*?)</div>"
    r"|<div class='cwcReport'>(?P<report>.*?)</div>",
    _FLAGS,
)
_FLASH_NAME = re.compile(r"^\s*<strong>(?P<name>.*?)</strong>(?P<rest>.*)$", _FLAGS)
_FLASH_EMPTY = "No information reported."
_PARA_STAMP = re.compile(r"^\s*Last Updated at\s+([^<\r\n]*?)\s*$", re.MULTILINE)
_PARA_EMPTY = "No Closings Reported"
_PARA_TOKEN = re.compile(
    r"(?P<heading><b>\s*<h2>(?P<group>.*?)</h2>\s*</b>)"
    r"|(?P<row><b>(?P<name>.*?)</b>\s*<br>(?P<status>[^<]*))",
    _FLAGS,
)
_BOLD_OPEN = re.compile(r"<b>", re.IGNORECASE)
_CGS_MARK = "Created by CGS Infographics Automation"
_CGS_STAMP = re.compile(r"<div class=\"msg\">([^<]*)</div>", re.IGNORECASE)
_CGS_EMPTY = re.compile(
    r"<table class=\"tablenoborder\">\s*<tr>\s*<td class=\"msg\">"
    r"There are no 'All Active' closings to report\.</td>\s*</tr>\s*</table>",
    re.IGNORECASE,
)
_CELLS_MARK = "id='closing_cell'"
_CELLS_TAB = re.compile(r"<a href=\"#\" rel=\"(country[0-9]+)\"[^>]*>([^<]*)</a>")
_CELLS_PANE = re.compile(r"<div id=\"(country[0-9]+)\" class=\"tabcontent\">(.*?)</ul>", re.DOTALL)
_CELLS_ITEM = re.compile(r"<li id='closing_cell'[^>]*>(.*?)</li>", re.DOTALL)
_CELLS_FIELD = re.compile(r"<div id='closing_(name|desc|desc2)'[^>]*>(.*?)</div>", re.DOTALL)
_CELLS_NONE = re.compile(r"^There are no [A-Z]+ closings$")
_SC_SCRIPT_MARK = 'id="wx_closings_container"'
_SC_SCRIPT_OPEN = re.compile(r"^[ \t]*xmlhttp\.open\(\"GET\",\"([^\"?]+)", re.MULTILINE)
_GSYNC_EMBED_TITLE = "<title>GSync Web Embeds</title>"
_TICKER_EMPTY = "There are no closings at this time."
_COUNTER_KEYS = frozenset({"title", "station", "closingsURL", "numClosings"})


def _text(fragment: str) -> str:
    """Return the visible text of an HTML fragment, runs of whitespace collapsed."""
    tree = HTMLParser(f"<div>{fragment}</div>")
    node = tree.css_first("div")
    text = node.text() if node is not None else ""
    return _SPACE.sub(" ", text).strip()


def _html(body: bytes) -> str:
    """Decode an HTML list file (UTF-8, else Windows-1252 as these servers sent)."""
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return body.decode("cp1252", errors="replace")


# Sniffing ----------------------------------------------------------------------------


_SC_NO_PROLOG = re.compile(rb"^<File\s+Time=\"[^\"<>]*\"\s*>")


def _xml_root(body: bytes) -> bytes | None:
    """Return the first element tag name of an XML document, or None if not XML.

    A document is XML when it opens with an XML declaration, or (an SC file
    without one) with ``<File Time="...">``.
    """
    head = body.removeprefix(b"\xef\xbb\xbf").lstrip()
    if _SC_NO_PROLOG.match(head):
        return b"File"
    if not head.startswith(b"<?xml"):
        return None
    match = re.search(rb"<([A-Za-z][A-Za-z0-9_]*)[\s>/]", re.sub(rb"<!DOCTYPE.*?\]>", b"", head))
    return match.group(1) if match else None


def _counter(body: bytes) -> Mapping[str, object] | None:
    head = body.removeprefix(b"\xef\xbb\xbf").lstrip()
    if not head.startswith(b"{") or b'"numClosings"' not in head:
        return None
    try:
        data = json.loads(head.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) and set(data) == _COUNTER_KEYS else None


_XML_KINDS: Mapping[bytes, str] = {b"ticker": "ticker", b"File": "sc", b"DATA": "nt-xml"}


def _html_kind(body: bytes) -> str | None:
    """Name the HTML list-file format ``body`` is in, or None."""
    text = _html(body)
    marks = (
        ("gsync", _GSYNC_EMBED_TITLE in text),
        ("sc-script", _SC_SCRIPT_MARK in text and _SC_SCRIPT_OPEN.search(text) is not None),
        ("flash", _FLASH_CONTAINER in text),
        ("grid", _GRID_STAMP.search(text) is not None),
        ("cgs", _CGS_MARK in text),
        ("cells", _CELLS_MARK in text and _CELLS_TAB.search(text) is not None),
        (
            "para",
            text.lstrip().startswith("Last Updated at")
            and _PARA_STAMP.search(text) is not None
            and (_PARA_TOKEN.search(text) is not None or _PARA_EMPTY in text),
        ),
        (
            "newsticker",
            _NT_TIMESTAMP.search(text) is not None
            and (_NT_MARK.search(text) is not None or _NT_EMPTY in text),
        ),
    )
    return next((kind for kind, found in marks if found), None)


def _kind(body: bytes) -> str | None:
    """Name the list-file format ``body`` is in, or None."""
    root = _xml_root(body)
    if root is not None:
        return _XML_KINDS.get(root)
    if _counter(body) is not None:
        return "counter"
    return _html_kind(body)


def is_file(body: bytes) -> bool:
    """Whether ``body`` is a list file this module reads (see the module docstring)."""
    return _kind(decode(body)) is not None


# NewsTicker HTML ---------------------------------------------------------------------


@dataclass(slots=True)
class _Headings:
    state: str | None = None
    category: str | None = None
    group: str | None = None

    def extra(self) -> dict[str, JsonScalar]:
        found = {"state": self.state, "category": self.category, "group": self.group}
        return {key: value for key, value in found.items() if value is not None}


def _nt_name(fragment: str) -> tuple[str, str | None]:
    """Return a NewsTicker name without its ``[WEB]`` link, and that link's address."""
    link = _WEB_LINK.search(fragment)
    if link is None:
        return _text(fragment), None
    return _text(fragment[: link.start()] + fragment[link.end() :]), link.group(1).strip()


def _nt_row(token: re.Match[str], updated: str | None, headings: _Headings) -> ParsedRow:
    """Read one NewsTicker row token (``orgname``/``status`` fonts or ``school``/``details``)."""
    if token.group("row") is not None:
        name, homepage = _nt_name(token.group("name"))
        status = _text(token.group("status"))
    else:
        name, homepage = _text(token.group("sname")), None
        status = _text(token.group("sstatus"))
    if not name:
        raise ShapeError("a NewsTicker row has no name")
    extra: dict[str, JsonScalar] = {"updated_scope": "page"} if updated else {}
    extra.update(headings.extra())
    if homepage is not None:
        extra["homepage"] = homepage
    return ParsedRow(name=name, status=status, updated_text=updated, extra=extra)


def _newsticker(body: bytes) -> Listing:
    text = _html(body)
    stamp = _NT_TIMESTAMP.search(text)
    updated = _text(stamp.group(2)) if stamp is not None else None
    headings = _Headings()
    rows: list[ParsedRow] = []
    names = 0
    for token in _NT_TOKEN.finditer(text):
        if token.group("div") is not None:
            label = _text(token.group("label"))
            if label != _NT_EMPTY and token.group("kind").lower() == "statename":
                headings = _Headings(state=label)
            elif label != _NT_EMPTY:
                headings = _Headings(state=headings.state, category=label)
        elif token.group("heading") is not None:
            names += 1
            headings.group = _text(token.group("group"))
        else:
            names += token.group("row") is not None
            rows.append(_nt_row(token, updated, headings))
    if names != len(_NT_ORGNAME.findall(text)):
        raise ShapeError("a NewsTicker orgname is neither a row nor a heading")
    if rows:
        return Listing(
            variant="gray-file-newsticker", state=ListingState.POPULATED, rows=tuple(rows)
        )
    if _NT_EMPTY in text:
        return Listing(variant="gray-file-newsticker", state=ListingState.EMPTY, rows=())
    raise ShapeError("a NewsTicker file with no rows and no no-records sentence")


# XML ---------------------------------------------------------------------------------


def _xml(body: bytes) -> ElementTree.Element:
    """Parse an archived XML list file.

    The files are small archived captures; the standard parser fetches no
    external entity, and the expat it uses (2.4 and later) refuses entity
    expansion attacks.
    """
    try:
        return ElementTree.fromstring(body)  # noqa: S314 - see the docstring
    except ElementTree.ParseError as error:
        raise ShapeError(f"the XML list file does not parse: {error}") from error


def _child_text(element: ElementTree.Element, tag: str) -> str | None:
    child = element.find(tag)
    if child is None:
        return None
    return "".join(child.itertext()).strip()


def _fields(element: ElementTree.Element, skip: set[str], lower: bool) -> dict[str, JsonScalar]:
    extra: dict[str, JsonScalar] = {}
    for child in element:
        if child.tag in skip:
            continue
        if len(child):
            raise ShapeError(f"a list file field {child.tag!r} is not plain text")
        key = child.tag.lower() if lower else child.tag
        if key in extra:
            raise ShapeError(f"a list file row repeats the field {child.tag!r}")
        extra[key] = (child.text or "").strip()
    return extra


def _ticker(body: bytes) -> Listing:
    root = _xml(body)
    rows: list[ParsedRow] = []
    for closing in root:
        if closing.tag != "closing":
            raise ShapeError(f"a ticker holds a <{closing.tag}>, not a <closing>")
        name = _child_text(closing, "name")
        status = _child_text(closing, "status")
        if not name or status is None:
            raise ShapeError("a ticker closing lacks its name or status")
        extra = _fields(closing, {"name", "status", "updatetime"}, lower=False)
        if closing.get("id") is not None:
            extra["id"] = closing.get("id")
        rows.append(
            ParsedRow(
                name=name,
                status=status,
                updated_text=_child_text(closing, "updatetime"),
                extra=extra,
            )
        )
    if rows:
        return Listing(
            variant="gray-file-ticker-xml", state=ListingState.POPULATED, rows=tuple(rows)
        )
    if _TICKER_EMPTY in "".join(root.itertext()):
        return Listing(variant="gray-file-ticker-xml", state=ListingState.EMPTY, rows=())
    raise ShapeError("a ticker with no closings and no no-closings sentence")


def _sc(body: bytes) -> Listing:
    root = _xml(body)
    updated = root.get("Time")
    rows: list[ParsedRow] = []
    skipped = 0
    for closing in root:
        if closing.tag != "Closing":
            raise ShapeError(f"an SC file holds a <{closing.tag}>, not a <Closing>")
        name = _child_text(closing, "Name1")
        status = _child_text(closing, "Status")
        if status is None:
            raise ShapeError("an SC closing has no Status")
        if not name:
            skipped += 1
            continue
        extra = _fields(closing, {"Name1", "Status"}, lower=False)
        if updated is not None:
            extra["updated_scope"] = "page"
        rows.append(ParsedRow(name=name, status=status, updated_text=updated, extra=extra))
    if skipped and not rows:
        raise ShapeError("every SC closing is missing its name")
    if not rows and "".join(root.itertext()).strip():
        raise ShapeError("an SC file with no closings holds text")
    return Listing(
        variant="gray-file-sc-xml",
        state=ListingState.POPULATED if rows else ListingState.EMPTY,
        rows=tuple(rows),
        skipped_rows=skipped,
    )


_NT_XML_HEAD = ("SOURCE", "EXPORT_TYPE", "NUM_CLOSINGS", "RUN_DATE", "RUN_EPOCH")


def _newsticker_xml(body: bytes) -> Listing:
    root = _xml(body)
    count_text = _child_text(root, "NUM_CLOSINGS")
    if count_text is None or not count_text.isdigit():
        raise ShapeError("a NewsTicker XML export has no NUM_CLOSINGS count")
    declared = int(count_text)
    rows: list[ParsedRow] = []
    skipped = 0
    for element in root:
        if element.tag in _NT_XML_HEAD:
            continue
        if element.tag != "RECORD":
            raise ShapeError(f"a NewsTicker XML export holds a <{element.tag}>")
        name = _child_text(element, "FORCED_ORGANIZATION_NAME")
        status = _child_text(element, "FORCED_STATUS_NAME")
        if status is None:
            raise ShapeError("a NewsTicker XML record has no FORCED_STATUS_NAME")
        if not name:
            skipped += 1
            continue
        skip = {"FORCED_ORGANIZATION_NAME", "FORCED_STATUS_NAME", "UPDATED"}
        rows.append(
            ParsedRow(
                name=name,
                status=status,
                updated_text=_child_text(element, "UPDATED"),
                extra=_fields(element, skip, lower=True),
            )
        )
    if len(rows) + skipped != declared:
        raise ShapeError(f"NUM_CLOSINGS is {declared} but the export holds {len(rows) + skipped}")
    if skipped and not rows:
        raise ShapeError("every NewsTicker XML record is missing its name")
    return Listing(
        variant="gray-file-newsticker-xml",
        state=ListingState.POPULATED if rows else ListingState.EMPTY,
        rows=tuple(rows),
        declared_count=declared,
        skipped_rows=skipped,
    )


# Counts, frames and application shells -----------------------------------------------


def _count_json(body: bytes) -> Listing:
    data = _counter(body)
    if data is None:  # _kind checked it
        raise ShapeError("not a closings counter")
    value = data["numClosings"]
    if value == "":
        # The counter was written blank (WTVA's, 2025-01-26): it says nothing.
        return Listing(variant="gray-file-count-json", state=ListingState.DEFERRED, rows=())
    if not isinstance(value, str | int) or isinstance(value, bool) or not str(value).isdigit():
        raise ShapeError(f"numClosings is not a count: {value!r}")
    count = int(value)
    return Listing(
        variant="gray-file-count-json",
        state=ListingState.COUNT_ONLY if count else ListingState.EMPTY,
        rows=(),
        declared_count=count,
    )


def _grid(body: bytes) -> Listing:
    text = _html(body)
    stamp = _GRID_STAMP.search(text)
    updated = stamp.group(1) if stamp is not None and stamp.group(1) else None
    rows: list[ParsedRow] = []
    empty = False
    for row in _GRID_ROW.finditer(text):
        cells = _GRID_CELL.findall(row.group(1))
        if len(cells) != _GRID_COLUMNS:
            raise ShapeError(f"a closings grid row has {len(cells)} cells, not {_GRID_COLUMNS}")
        bold = _BOLD.match(cells[0])
        if bold is None:
            raise ShapeError("a closings grid row's first cell is not a bold name")
        name, status, comment = _text(bold.group(1)), _text(cells[1]), _text(cells[2])
        if name == _GRID_EMPTY and not status and not comment:
            empty = True
            continue
        if not name:
            raise ShapeError("a closings grid row has no name")
        extra: dict[str, JsonScalar] = {"updated_scope": "page"} if updated else {}
        if comment:
            extra["comment"] = comment
        rows.append(ParsedRow(name=name, status=status, updated_text=updated, extra=extra))
    if rows and empty:
        raise ShapeError("a closings grid lists rows and says none are reported")
    if rows:
        return Listing(variant="gray-file-grid", state=ListingState.POPULATED, rows=tuple(rows))
    if empty:
        return Listing(variant="gray-file-grid", state=ListingState.EMPTY, rows=())
    raise ShapeError("a closings grid with no rows and no no-closings sentence")


def _flash_row(report: str, category: str | None, updated: str | None) -> ParsedRow:
    """Read one ``cwcReport``: ``<strong>Name</strong>&nbsp;- status text``."""
    match = _FLASH_NAME.match(report)
    if match is None:
        raise ShapeError("a FlashAlert report does not start with a bold name")
    name, rest = _text(match.group("name")), _text(match.group("rest"))
    if not name:
        raise ShapeError("a FlashAlert report has no name")
    if not rest.startswith("-"):
        raise ShapeError(f"a FlashAlert report's name is not followed by '- ': {rest[:40]!r}")
    extra: dict[str, JsonScalar] = {"updated_scope": "page"} if updated else {}
    if category is not None:
        extra["category"] = category
    return ParsedRow(
        name=name, status=rest.removeprefix("-").strip(), updated_text=updated, extra=extra
    )


def _flash(body: bytes) -> Listing:
    text = _html(body)
    header = _FLASH_HEADER.search(text)
    if header is None:
        raise ShapeError("a FlashAlert report with no header")
    updated = _text(header.group(1)) or None
    rows: list[ParsedRow] = []
    empty = False
    category: str | None = None
    for token in _FLASH_TOKEN.finditer(text):
        if token.group("category") is not None:
            category = _text(token.group("category"))
        elif _text(token.group("report")) == _FLASH_EMPTY:
            empty = True
        else:
            rows.append(_flash_row(token.group("report"), category, updated))
    if rows and empty:
        raise ShapeError("a FlashAlert report lists rows and says nothing is reported")
    if rows:
        return Listing(
            variant="gray-file-flashalert", state=ListingState.POPULATED, rows=tuple(rows)
        )
    if empty and category is None:
        return Listing(variant="gray-file-flashalert", state=ListingState.EMPTY, rows=())
    raise ShapeError("a FlashAlert report with no rows and no no-information sentence")


def parse_para(text: str) -> Listing:
    """Read SC paragraph text (``gray-file-sc-para``), as a file or as a page holds it."""
    stamp = _PARA_STAMP.search(text)
    if stamp is None:
        raise ShapeError("an SC paragraph list with no 'Last Updated at' line")
    updated = stamp.group(1) or None
    rows: list[ParsedRow] = []
    headings = 0
    group: str | None = None
    for token in _PARA_TOKEN.finditer(text, stamp.end()):
        if token.group("heading") is not None:
            headings += 1
            group = _text(token.group("group")).lstrip("-").strip() or None
            continue
        name = _text(token.group("name"))
        if not name:
            raise ShapeError("an SC paragraph row has no name")
        extra: dict[str, JsonScalar] = {"updated_scope": "page"} if updated else {}
        if group is not None:
            extra["group"] = group
        rows.append(
            ParsedRow(
                name=name, status=_text(token.group("status")), updated_text=updated, extra=extra
            )
        )
    if headings + len(rows) != len(_BOLD_OPEN.findall(text)):
        raise ShapeError("a bold SC paragraph is neither a heading nor a row")
    empty = _PARA_EMPTY in text
    if rows and empty:
        raise ShapeError("an SC paragraph list has rows and says none are reported")
    if rows:
        return Listing(variant="gray-file-sc-para", state=ListingState.POPULATED, rows=tuple(rows))
    if empty and not headings:
        return Listing(variant="gray-file-sc-para", state=ListingState.EMPTY, rows=())
    raise ShapeError("an SC paragraph list with no rows and no no-closings sentence")


def _para(body: bytes) -> Listing:
    return parse_para(_html(body))


def _cgs(body: bytes) -> Listing:
    text = _html(body)
    if _CGS_STAMP.search(text) is None:
        raise ShapeError("a CGS closings page with no time stamp")
    if _CGS_EMPTY.search(text) is None:
        raise ShapeError(
            "a CGS closings page that is not in its empty state (no populated capture "
            "of this format has been seen, so its rows are not read)"
        )
    return Listing(variant="gray-file-cgs", state=ListingState.EMPTY, rows=())


def _cell(item: str, tab: str) -> ParsedRow | None:
    """Read one ``closing_cell`` item; None for a tab's "There are no ... closings"."""
    fields: dict[str, str] = {}
    for match in _CELLS_FIELD.finditer(item):
        if match.group(1) in fields:
            raise ShapeError(f"a closings cell repeats closing_{match.group(1)}")
        fields[match.group(1)] = _text(match.group(2))
    if "name" not in fields or "desc" not in fields:
        raise ShapeError("a closings cell lacks its name or its status")
    name, status, second = fields["name"], fields["desc"], fields.get("desc2", "")
    if _CELLS_NONE.match(name) and not status and not second:
        return None
    if not name:
        raise ShapeError("a closings cell has no name")
    extra: dict[str, JsonScalar] = {"tab": tab}
    if second:
        extra["status2"] = second
    return ParsedRow(name=name, status=status, extra=extra)


def _cells(body: bytes) -> Listing:
    text = _html(body)
    tabs = dict(_CELLS_TAB.findall(text))
    rows: list[ParsedRow] = []
    items = panes = 0
    for pane in _CELLS_PANE.finditer(text):
        panes += 1
        tab = tabs.get(pane.group(1))
        if tab is None:
            raise ShapeError(f"the closings tab {pane.group(1)} has no name")
        found = [_cell(item.group(1), tab.strip()) for item in _CELLS_ITEM.finditer(pane.group(2))]
        if not found:
            raise ShapeError(f"the closings tab {tab!r} has no items")
        if None in found and len(found) > 1:
            raise ShapeError(f"the closings tab {tab!r} lists rows and says there are none")
        items += len(found)
        rows += [row for row in found if row is not None]
    if not panes or panes != len(tabs):
        raise ShapeError(f"the closings page has {panes} tab panes for {len(tabs)} tabs")
    if items != text.count(_CELLS_MARK):
        raise ShapeError("a closings cell lies outside the tabs")
    return Listing(
        variant="gray-file-mobile-cells",
        state=ListingState.POPULATED if rows else ListingState.EMPTY,
        rows=tuple(rows),
    )


def _sc_script(body: bytes) -> Listing:
    match = _SC_SCRIPT_OPEN.search(_html(body))
    if match is None:  # _kind checked it
        raise ShapeError("the closings script requests no file")
    return Listing(
        variant="gray-file-sc-script",
        state=ListingState.DEFERRED,
        rows=(),
        follows=(match.group(1),),
    )


def _gsync(_body: bytes) -> Listing:
    return Listing(variant="gray-file-gsync-embed", state=ListingState.DEFERRED, rows=())


_PARSERS: Mapping[str, Callable[[bytes], Listing]] = {
    "newsticker": _newsticker,
    "nt-xml": _newsticker_xml,
    "ticker": _ticker,
    "sc": _sc,
    "counter": _count_json,
    "grid": _grid,
    "para": _para,
    "cgs": _cgs,
    "cells": _cells,
    "flash": _flash,
    "sc-script": _sc_script,
    "gsync": _gsync,
}


def parse(body: bytes) -> Listing:
    """Read a list file in whichever variant (see the module docstring) it is."""
    body = decode(body)
    kind = _kind(body)
    if kind is None:
        raise ShapeError("not a closings list file this adapter knows")
    return _PARSERS[kind](body)


def slice_file(body: bytes) -> bytes:
    """Return a list file as a test fixture keeps it: whole (decoded), once it parses.

    List files are small (a few kilobytes) and every part of one is either its
    list or its format's markers, so nothing is cut.
    """
    body = decode(body)
    parse(body)
    return body
