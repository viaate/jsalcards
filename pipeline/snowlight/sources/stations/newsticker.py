"""NewsTicker-family closings files: static HTML lists several station groups frame.

Many stations' closings pages hold no list of their own: they frame a static HTML
file that the station's closings system writes every few minutes. Two such
generators are read here, in every form seen in live reads (2026-09-26/27) and in
Wayback ``id_`` captures of the files:

``newsticker-html``
    The NewsTicker export: Sinclair's ``/resources/ftptransfer/{call}/closings/*.html``
    files (WHAM, WJLA, KOMO, WGME, WACH, WCTI, WTVC, WWMT and the rest), WBFF's
    ``ftptransfer.sinclairstoryline.com`` file, Allen Media's
    ``ftp2.{station}.com/closings.html`` files, the Rhode Island Broadcasters
    Association's page and WRCB's ``/app/closings/closings.html``. One update time
    for the whole file (``<TD CLASS="timestamp">UPDATED SUNDAY, SEP 27 AT 1:40
    AM</TD>``), then one table row per organization, in one of three layouts::

        <TD><FONT CLASS="orgname">Name</FONT>: <FONT CLASS="status">Status</FONT></TD>
        <TD><FONT CLASS="orgname">Name</FONT></TD><TD><FONT CLASS="status">Status</FONT></TD>
        <TD><FONT CLASS="status">Town</FONT></TD>
            <TD><FONT CLASS="orgname">Name</FONT>: <FONT CLASS="status">Status</FONT></TD>

    (the first everywhere, the second at WTVC, the third, with the organization's
    town first, at RIBA; Raycom's WAFB export, read the same way, wrote
    ``<TD class="school">Name</TD><TD class="details">Status</TD>``). The
    ``orgname`` text is the name (a ``[WEB]`` link after it is dropped, its
    address kept as ``raw_extra["homepage"]``), the ``status`` text after it the
    status, and a ``status`` cell before it the town
    (``raw_extra["location"]``). Rows may sit under group headings: a row holding
    only an ``orgname`` (a cell of class ``orgname``, or an ``orgname`` font with no
    status, as at RIBA: "COMMUNITY GROUPS"), or only bold text (WRCB: "TN: TN
    Schools"); the heading in force goes in ``raw_extra["group"]``. The
    WorldNow-styled exports (WHAM's and KOMO's files) write each row in a
    ``canname`` cell under a ``racename`` heading cell ("County", in WHAM's
    storm-day captures of 2024-02-29 and 2025-02-17), kept the same way. Raycom's WAVE
    export put rows under ``<div class="statename">`` and ``<div
    class="categoryname">`` headings instead, kept as ``raw_extra["state"]`` and
    ``raw_extra["category"]``. The file's
    update time is each row's ``raw_updated_text`` (``raw_extra["updated_scope"]``
    is ``"page"``). The file's own sentence "There are no active records at this
    time." (in a ``status`` or ``prereporting`` cell) is the empty state.

``closings-grid``
    The "Closings Last Updated at" table (Sinclair's WJAC, WSBT, WTOV, WCYB and
    KRCG files, and NJ 101.5's by-county file): "Closings Last Updated at 1:37am on
    9/27/2026" over a three-column table, one row per organization::

        <tr><td width="33%"><b>Alma Schools&nbsp;</b></td><td width="33%">Closed&nbsp;</td>
            <td width="33%">No after school activities&nbsp;</td></tr>

    The bold first cell is the name, the second the status, and the third (a
    comment, often blank) goes in ``raw_extra["comment"]`` when it holds text. A row
    of one bold cell spanning the table is a heading (a county, in NJ 101.5's
    file), kept as ``raw_extra["group"]``. The update time is each row's
    ``raw_updated_text``. The bold sentence "No Closings have been reported at this
    time" (in one cell, or the first of three blank ones) is the empty state.

``closings-paragraphs``
    The same "Last Updated at" generator's paragraph list, WBFF's earlier file
    (``foxbaltimore.com/resources/ftptransfer/wbff/closings/closings.htm``, captures
    of 2016 to 2023): ``<P>Last Updated at 8:39am on 1/07/2022</P>`` and then, in
    one paragraph, each organization as a bold name, a line break, its status and
    two line breaks, as the capture of 2022-01-07 14:42 UTC shows (58 of them)::

        <P><b>Annapolis City Government</b><br>Opening 2 hours late Liberal leave<br><br>
        <b>Anne Arundel Co Circuit Court</b><br>Opening at 9:00 AM <br><br>...</P>

    The bold text is the name and the text after it the status; the update time is
    each row's ``raw_updated_text``. The paragraph "No Closings reported as of
    11:13am on 5/17/2022" (capture of 2022-05-21) is the empty state. Any other
    text in the list paragraph raises.

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`; so does
a file that lists rows and also says nothing is listed. :func:`parse` reads either
generator's file; the platform adapters call :func:`read_file`, which returns
None for a body in neither shape.
"""

import re

from selectolax.parser import HTMLParser, Node

from snowlight.sources.stations.body import decode
from snowlight.sources.stations.model import JsonScalar, Listing, ParsedRow, ShapeError
from snowlight.sources.stations.regional import (
    collapse,
    fragment_text,
    html_text,
    listing,
    node_text,
    row,
)

NEWSTICKER = "newsticker-html"
GRID = "closings-grid"
PARAGRAPHS = "closings-paragraphs"
EMPTY_SENTENCE = "There are no active records at this time."
GRID_EMPTY = "No Closings have been reported at this time"

_FLAGS = re.IGNORECASE | re.DOTALL
_TIMESTAMP = re.compile(r"<(td|div)\b[^>]*\bclass=\"?timestamp\"?[^>]*>", re.IGNORECASE)
_ORGNAME = re.compile(r"\bclass=\"?orgname\"?", re.IGNORECASE)
_MARK = re.compile(r"\bclass=\"?(?:orgname|school)\"?", re.IGNORECASE)
_WEB_LINK = re.compile(r"\[\s*<a\b[^>]*\bhref=\"([^\"]*)\"[^>]*>\s*WEB\s*</a>\s*\]", _FLAGS)
_GRID_STAMP = re.compile(r"Closings Last Updated at\s*([^<]*?)\s*<", re.IGNORECASE)
_GRID_COLUMNS = 3
_PARA_STAMP = re.compile(r"^\s*<p>\s*Last Updated at\s*([^<]*?)\s*</p>", re.IGNORECASE)
_PARA_EMPTY = re.compile(r"^\s*<p>\s*No Closings reported as of [^<]*</p>\s*$", re.IGNORECASE)
_PARA_LIST = re.compile(r"^\s*<p>(.*)</p>\s*$", _FLAGS)
_PARA_ENTRY = re.compile(r"\s*<b>(.*?)</b>\s*<br>(.*?)<br>\s*<br>", _FLAGS)
_OUTER_TAG = re.compile(r"^<[^>]*>(.*)</[^>]*>$", re.DOTALL)


def _classes(node: Node) -> set[str]:
    value = node.attributes.get("class") or ""
    return {part.lower() for part in value.split()}


def _cell_of(node: Node) -> Node | None:
    current: Node | None = node
    while current is not None and current.tag != "td":
        current = current.parent
    return current


def _name_and_link(font: Node) -> tuple[str, str | None]:
    """Return a NewsTicker name without its ``[WEB]`` link, and that link's address."""
    outer = _OUTER_TAG.match(font.html or "")
    inner = outer.group(1) if outer is not None else ""
    link = _WEB_LINK.search(inner)
    if link is None:
        return fragment_text(inner), None
    return fragment_text(inner[: link.start()] + inner[link.end() :]), link.group(1).strip()


class _Reader:
    """Reads a NewsTicker export row by row."""

    def __init__(self) -> None:
        self.updated: str | None = None
        self.group: str | None = None
        self.state: str | None = None
        self.category: str | None = None
        self.rows: list[ParsedRow] = []
        self.skipped = 0
        self.empty = False
        self.headings = 0
        self.marks = 0  # rows read from the school/details layout (no orgname mark)

    def extra(self) -> dict[str, JsonScalar]:
        found: dict[str, JsonScalar] = {"updated_scope": "page"} if self.updated else {}
        for key, value in (("state", self.state), ("category", self.category)):
            if value is not None:
                found[key] = value
        if self.group is not None:
            found["group"] = self.group
        return found

    def heading(self, div: Node) -> None:
        """Read a ``statename``, ``categoryname`` or ``timestamp`` block (WAVE's layout)."""
        label = node_text(div)
        if "timestamp" in _classes(div):
            self.updated = label or None
            return
        if not label or label == EMPTY_SENTENCE:
            return
        if "statename" in _classes(div):
            self.state, self.category = label, None
        else:
            self.category = label

    def organization(self, tr: Node, font: Node) -> None:
        cell = _cell_of(font)
        if cell is None:
            raise ShapeError("a NewsTicker orgname sits outside a table cell")
        cells = tr.css("td")
        position = next((n for n, td in enumerate(cells) if td.mem_id == cell.mem_id), None)
        if position is None:
            raise ShapeError("a NewsTicker orgname's cell is not in its row")
        inside = [f for f in cell.css("font") if "status" in _classes(f)]
        after = [
            f for td in cells[position + 1 :] for f in td.css("font") if "status" in _classes(f)
        ]
        before = [f for td in cells[:position] for f in td.css("font") if "status" in _classes(f)]
        statuses = inside or after
        if not statuses and not before:
            # An orgname with no status anywhere in its row: a group heading.
            self.headings += 1
            self.group = node_text(font) or None
            return
        if len(statuses) != 1 or len(before) > 1:
            raise ShapeError("a NewsTicker row does not hold one name and one status")
        name, homepage = _name_and_link(font)
        extra = self.extra()
        if before:
            extra["location"] = node_text(before[0])
        if homepage is not None:
            extra["homepage"] = homepage
        found = row(name, node_text(statuses[0]), self.updated, extra)
        if found is None:
            self.skipped += 1
        else:
            self.rows.append(found)

    def school(self, tr: Node, schools: list[Node]) -> None:
        """Read the ``school``/``details`` layout (one name cell, one status cell)."""
        details = [td for td in tr.css("td") if "details" in _classes(td)]
        if len(schools) != 1 or len(details) != 1:
            raise ShapeError(
                "a NewsTicker school row does not hold one school and one details cell"
            )
        self.marks += 1
        found = row(node_text(schools[0]), node_text(details[0]), self.updated, self.extra())
        if found is None:
            self.skipped += 1
        else:
            self.rows.append(found)

    def line(self, tr: Node) -> None:
        stamps = [n for n in tr.css("td, div") if "timestamp" in _classes(n)]
        if stamps:
            self.updated = node_text(stamps[0]) or None
            return
        fonts = [f for f in tr.css("font") if "orgname" in _classes(f)]
        if len(fonts) > 1:
            raise ShapeError("a NewsTicker row holds more than one orgname")
        if fonts:
            self.organization(tr, fonts[0])
            return
        schools = [td for td in tr.css("td") if "school" in _classes(td)]
        if schools:
            self.school(tr, schools)
            return
        text = node_text(tr)
        cells = tr.css("td")
        heads = [td for td in cells if "orgname" in _classes(td)]
        bold = tr.css_first("b")
        if heads:
            self.headings += 1
            self.group = node_text(heads[0]) or None
        elif len(cells) == 1 and "racename" in _classes(cells[0]):
            # WorldNow's layout: a heading cell of its own class, no orgname mark.
            self.group = text or None
        elif text == EMPTY_SENTENCE:
            self.empty = True
        elif not text:
            return
        elif bold is not None and node_text(bold) == text:
            self.group = text
        else:
            raise ShapeError(f"a NewsTicker row is neither a heading nor a listing: {text[:60]!r}")


def _newsticker(text: str) -> Listing:
    tree = HTMLParser(text)
    reader = _Reader()
    root = tree.body or tree.root
    for node in root.traverse() if root is not None else ():
        if node.tag == "tr":
            reader.line(node)
        elif node.tag == "div" and _classes(node) & {"statename", "categoryname", "timestamp"}:
            reader.heading(node)
    marks = len(_ORGNAME.findall(text)) + reader.marks
    read = len(reader.rows) + reader.skipped + reader.headings
    if marks != read:
        raise ShapeError(
            f"the file names {marks} orgnames but {read} were read as rows or headings"
        )
    if reader.rows and reader.empty:
        raise ShapeError("a NewsTicker file lists rows and says there are no records")
    if not reader.rows and not reader.empty:
        raise ShapeError("a NewsTicker file with no rows and no no-records sentence")
    return listing(NEWSTICKER, reader.rows, skipped=reader.skipped)


def _grid(text: str) -> Listing:
    stamp = _GRID_STAMP.search(text)
    updated = collapse(stamp.group(1)) if stamp is not None and stamp.group(1).strip() else None
    tree = HTMLParser(text)
    rows: list[ParsedRow] = []
    group: str | None = None
    empty = False
    skipped = 0
    for tr in tree.css("tr"):
        cells = tr.css("td")
        texts = [node_text(td) for td in cells]
        bold = cells[0].css_first("b") if cells else None
        if bold is None:
            raise ShapeError("a closings grid row does not start with a bold cell")
        if texts[0] == GRID_EMPTY and not any(texts[1:]):
            empty = True
            continue
        if len(cells) == 1:
            group = texts[0] or None
            continue
        if len(cells) != _GRID_COLUMNS:
            raise ShapeError(f"a closings grid row has {len(cells)} cells, not {_GRID_COLUMNS}")
        extra: dict[str, JsonScalar] = {"updated_scope": "page"} if updated else {}
        if group is not None:
            extra["group"] = group
        if texts[2]:
            extra["comment"] = texts[2]
        found = row(texts[0], texts[1], updated, extra)
        if found is None:
            skipped += 1
        else:
            rows.append(found)
    if rows and empty:
        raise ShapeError("a closings grid lists rows and says none are reported")
    if not rows and not empty:
        raise ShapeError("a closings grid with no rows and no no-closings sentence")
    return listing(GRID, rows, skipped=skipped)


def _paragraphs(text: str, stamp: re.Match[str]) -> Listing:
    updated = collapse(stamp.group(1)) or None
    rest = text[stamp.end() :]
    if _PARA_EMPTY.match(rest) is not None:
        return listing(PARAGRAPHS, [])
    block = _PARA_LIST.match(rest)
    if block is None:
        raise ShapeError("a closings paragraph list without its list paragraph")
    inner = block.group(1)
    rows: list[ParsedRow] = []
    skipped = 0
    end = 0
    for entry in _PARA_ENTRY.finditer(inner):
        if inner[end : entry.start()].strip():
            raise ShapeError(f"a closings paragraph list holds {inner[end : entry.start()][:40]!r}")
        end = entry.end()
        extra: dict[str, JsonScalar] = {"updated_scope": "page"} if updated else {}
        found = row(fragment_text(entry.group(1)), fragment_text(entry.group(2)), updated, extra)
        if found is None:
            skipped += 1
        else:
            rows.append(found)
    if inner[end:].strip():
        raise ShapeError(f"a closings paragraph list ends with {inner[end:][:40]!r}")
    if not rows and not skipped:
        raise ShapeError("a closings paragraph list with no entries and no no-closings line")
    return listing(PARAGRAPHS, rows, skipped=skipped)


def read_file(body: bytes) -> Listing | None:
    """Read a NewsTicker export or a closings grid; None when the body is in neither shape.

    Raises:
        ShapeError: the body is one of them but does not read cleanly.
    """
    text = html_text(body)
    if _GRID_STAMP.search(text) is not None:
        return _grid(text)
    stamp = _PARA_STAMP.match(text)
    if stamp is not None:
        return _paragraphs(text, stamp)
    if _TIMESTAMP.search(text) is not None and (
        _MARK.search(text) is not None or EMPTY_SENTENCE in text
    ):
        return _newsticker(text)
    return None


def parse(body: bytes) -> Listing:
    """Read a NewsTicker export or a closings grid (see the module docstring)."""
    found = read_file(body)
    if found is None:
        raise ShapeError("neither a NewsTicker export nor a closings grid")
    return found


def slice_body(body: bytes) -> bytes:
    """A list file (or RIBA's page, which is one) is kept whole, decoded."""
    parse(body)
    return decode(body)
