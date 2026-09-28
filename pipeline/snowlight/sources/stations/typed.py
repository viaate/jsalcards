"""Closings lists typed by hand into a station's page or article (Nexstar and Scripps).

Some stations keep no closings system: in a storm a producer types the closings
into a page (WHNT's ``/weather-closings/``, WDHN's
``/severe-weather-closings-and-delays/``, WRBL's ``/weather/closings-and-delays/``,
KSTU's ``/weather/closings``) or into an article the closings page redirected to
(WNTZ's page led to a 2017 article with a typed table). Only the stations the
registry files under a typed platform are read this way (``nexstar-typed`` and
``scripps-typed``, see :mod:`snowlight.sources.stations.nexstar_typed` and
:mod:`snowlight.sources.stations.scripps_typed`): on any other station's page a
missing, blank or script-filled list is an error, never an empty list typed by hand.

The words are the station's own, but the page has a structure, and the rows are
read from it, whatever words they use. WHNT's page archived on 2021-02-15::

    <div class="article-content rich-text">
      <p>The following information is pertaining to Monday, February 15, 2021, ...</p>
      <p><strong>School Closings</strong> <strong>and Delays</strong></p>
      <ul><li>Athens State University &#8211; Closed Monday</li>
          <li>Cullman County Schools &#8211; Virtual Learning Day/ Campuses Closed Monday</li> ...

and KSTU's on 2023-02-22 (Brightspot's rich-text module, under day headings)::

    <div class="RichTextModule-items"><p><b><u>WEDNESDAY, FEB. 22</u></b></p>
      <ul><li>Granite School District to hold distance learning day on Wednesday.<br>
        <ul><li>Full details on district's website.</li></ul></li></ul> ...

:func:`read_typed` reads such a block (widgets the site injects into it are passed
over: ``section``, ``aside``, ``form``, ``figure``, scripts, video players and
``nlp-ignore-block`` promotions). Which parts are rows depends on how the block is
typed, never on the words in them:

* A block typed as a list (it holds list items, ``<li>``, or a table's data rows):
  every list item that is not inside another item, and every table row (``<tr>``
  with two cells or more that is not the header row: the first cell the name, the
  others the status) is a row. An empty item is none, nor is an item that is the
  sentence saying the list is empty ("There are no closings at this time"), and
  an item typed as a heading (text ending in a colon with nothing nested under it,
  "Pike County:") is the heading of the items after it. Paragraphs are headings
  and notes.
* A block typed as paragraphs (no list item and no table): a paragraph is split
  into lines at ``<br>`` and into entries at blank lines. An entry whose first line
  is a name alone (bold, or ending in a colon: "&#8211; Phenix City Schools:") is
  one row, its status the lines after it (WRBL's page), unless every line after it
  opens with a bullet: then it is their heading and each of them a row. Any other
  line is a row when it is written as an entry: it opens with a bullet ("&#8211;",
  "-", "&#8226;"), or with bold text followed by more text ("**Madison County
  Schools** will operate on a two-hour delay"), or it
  splits at a dash or a colon into a name and a status ("Harris County Schools
  &#8212; 2-hour delay"; not a label such as "NOTE:", nor a news story's dateline
  such as "AUSTIN (KXAN)").
* A block typed as paragraphs with no entry written that way: every plain
  paragraph after a heading is a row (KSTU's page of 2022-12-13, "ALL Uintah School
  District schools will delay opening by two hours ..." under "TUESDAY, DECEMBER
  13" and "DELAYS"). A paragraph wholly in bold or italics is a note, not a row.

How a row's text is split into name and status (``raw_extra["split"]`` says which):
``bold`` when it opens with bold text followed by more text (the bold text is the
name, without a closing colon or dash); ``dash`` or ``colon`` at the first such
separator; ``verb`` before the first word that starts a statement ("Dothan City
Schools | are closed on Tuesday and Wednesday", :data:`_VERB`); ``none`` when
nothing splits it (the whole text is the name and the status is empty);
``name-line`` for a paragraph entry whose first line is its name; ``table`` for a
table row (its cells joined with " | " are the line). A list item with nothing
after its name ("Troy University:") takes the items nested under it as its status.
The whole line is kept in ``raw_extra["line"]``; items nested under an item in
``raw_extra["details"]`` (joined with " | "); the heading in force in
``raw_extra["section"]``; and the last paragraph before the row that is not a row
and names a weekday or a month (the note saying which day the list is for) in
``raw_extra["note"]``.

A block with no row is the empty state only when the page says so: a sentence that
there are no closings ("There are currently no school closings", "There are no
current delays or closings at this time", :data:`NO_CLOSINGS`), or the page's
standing note of what it is for and nothing else ("This page will update you on
closings and delays ...", "List will be updated as closings are announced",
:data:`STANDING_NOTE`). A block with no row and neither (blank, a script's mount
point, a leftover sentence such as "Test Block per Support") raises
:class:`~snowlight.sources.stations.model.ShapeError`. (An empty Brightspot
rich-text module, the typed list cleared, is the empty state too; the Scripps
adapter decides that, since it knows the module.)

A typed list states no time for its rows unless its page does: when the body
carries the page's own modification time (the WordPress REST object's
``modified_gmt``, an HTML page's ``article:modified_time`` or ``dateModified``),
it is every row's ``raw_updated_text`` (``raw_extra["updated_scope"]`` is
``"page"``) and the listing's ``list_updated_at``, and the listing is marked
``typed``. Text typed by hand stays up long after the day it names (WHNT's
page still showed its entry for June 8, 2026 in late September), so the live
reader keeps a typed list's rows only while the page's time says it changed
within :data:`~snowlight.sources.stations.fetch.TYPED_CURRENT` of the read (see
:mod:`snowlight.sources.stations.fetch`). A page that states no time for itself
(Brightspot's) is current only when its own words date it: when a heading, a note or
a line names a day near the read (:func:`names_day_near`), as KSTU's headings did on
22 February 2023 ("WEDNESDAY, FEB. 22"). Only a date the text pins down counts: a
month and day with the year, or with the weekday that falls on it (the year is the
one, within a year of the read, whose calendar puts that weekday there); "on
Tuesday" alone dates nothing.

Whether a body is a typed closings page at all (and not an article that merely
names a closing) is the caller's decision: each typed adapter reads a typed block
only from a page whose title says it is a closings page (:func:`closings_title`).

Closings are also typed beside a closings system's list, into the same page, while
that list stays empty (KIAH's page for the storm of January 2025: eight districts in
a list below its empty Nexstar closings article). :func:`entries_beside` finds such
entries in the page's content outside the list, and :func:`read_beside` reads them as
a typed listing. There the page's list items and table rows are entries, and its
paragraphs only when written as entries with no link in them: the notes such a page
keeps beside its list on quiet days (a station's blurb, "Administrators: To submit a
closing, click here.", a link to a story) are never entries, and no plain paragraph
is. The Nexstar adapter raises an error for a page with such entries unless the
registry files its station as typing closings there.
"""

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from selectolax.parser import Node

from snowlight.sources.stations.markup import SEPARATOR, collapse, node_text
from snowlight.sources.stations.model import (
    MAX_EXTRA_TEXT,
    MAX_NAME,
    MAX_STATUS,
    JsonScalar,
    Listing,
    ListingState,
    ParsedRow,
    ShapeError,
)

NO_CLOSINGS = re.compile(
    r"\bno\s+(?:current\s+|active\s+|reported\s+)?(?:school\s+)?"
    r"(?:closings?|delays?|closures?|cancell?ations?)\b",
    re.IGNORECASE,
)
"""A sentence saying the typed list holds nothing ("There are currently no school closings")."""
_EMPTY_SENTENCE = re.compile(
    r"^\W*(?:there\s+(?:are|is)\s+(?:currently\s+|presently\s+)?)?no\s+"
    r"(?:current\s+|active\s+|reported\s+)?(?:school\s+)?"
    r"(?:closings?|delays?|closures?|cancell?ations?)\b",
    re.IGNORECASE,
)
"""An item or line that is the sentence saying the list is empty, not an entry of it."""
STANDING_NOTE = re.compile(
    r"\bthis\s+page\s+(?:will\s+update|is\s+used\s+for)\b|\blist\s+will\s+be\s+updated\b",
    re.IGNORECASE,
)
"""A typed page's standing note of what it is for ("This page will update you on closings")."""
_MARKER_LENGTH = 300
"""The longest paragraph read as a sentence saying the list is empty (longer ones are prose)."""

_TITLE = re.compile(
    r"\b(?:closings?|closures?|delays?|cancell?ations?|dismissals?)\b(?!\s+arguments?)",
    re.IGNORECASE,
)
_SEPARATORS = re.compile("\\s*(?:\u2013|\u2014|\\s-\\s)\\s*|:\\s+")
_DASH = re.compile("\u2013|\u2014|\\s-\\s")
_VERB = re.compile(
    r"\s(?=(?:is|are|will|has|have|was|were|remains?|closed|closing|closes|delayed|delays"
    r"|dismiss\w*|operat\w*|going|to\s+close|to\s+operate|to\s+hold|to\s+have|on\s+a"
    r"|announc\w*|says|said|moves?|moving|switch\w*|advis\w*|cancel\w*)\b)",
    re.IGNORECASE,
)
_DATED = re.compile(
    r"\b(?:mon|tues|wednes|thurs|fri|satur|sun)day\b|\b(?:january|february|march|april|may|june"
    r"|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sept?|oct"
    r"|nov|dec)\.?\s+[0-9]{1,2}\b",
    re.IGNORECASE,
)
_LABEL = re.compile(
    r"^(?:note|notes|update|updated|editor'?s note|attention|important|please note|reminder)$",
    re.IGNORECASE,
)
_BULLET = " \u2013\u2014-\u2022*\u00b7"
"""Characters a typed line may open with as a bullet ("- Phenix City Schools:")."""
_BULLETED = re.compile("^\\s*[\u2013\u2014\u2022*\u00b7-]")
_WORDY = re.compile(r"[^\W_]", re.UNICODE)
_NOT_A_NAME = re.compile(
    r"^(?:there|it|this|that|these|those|they|we|he|she|all|some|many|most|several)$",
    re.IGNORECASE,
)
"""A word before a verb that is not an organization ("There | is a lightning delay ...")."""
_DATELINE = re.compile(r"^[A-Z][A-Z .,'-]*\([A-Z0-9 -]+\)$")
"""A news story's dateline ("AUSTIN (KXAN)"), which a dash follows but no status does."""
_WRITTEN_SPLITS = frozenset({"bold", "dash", "colon"})
"""Splits the line's own markup or punctuation makes (a name, then its status)."""
_CELLS = frozenset({"li", "td", "th"})
_HEADER_CELL = re.compile(r"^(?:entity|name|school|schools|organization|district)$", re.IGNORECASE)
"""A typed table's header row names its first column ("ENTITY" | "STATUS")."""
_HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_BOLD = frozenset({"b", "strong"})
_LISTS = frozenset({"ul", "ol"})
_LINK = frozenset({"a"})
_SKIPPED = frozenset(
    {
        "script", "style", "form", "aside", "section", "figure", "noscript", "iframe",
        "video", "template", "button", "svg",
    }
)  # fmt: skip
"""Elements a site injects into a typed block (widgets, players, forms): never read."""
_SKIPPED_CLASS = re.compile(r"(?:^|\s)(?:nlp-ignore-block|nxs-player|nexstar-video|video-float)")
_TRIM = " :\u2013\u2014-"
_MAX_HEADING = 120
_MAX_NOTE = 400
_META_TIME = re.compile(
    r"<meta\b[^>]*\bproperty=\"article:modified_time\"[^>]*\bcontent=\"([^\"]+)\"", re.IGNORECASE
)
_LD_TIME = re.compile(r"\"dateModified\"\s*:\s*\"([^\"]+)\"")

type Context = tuple[str | None, str | None]
"""The heading in force and the dated note before a row."""
type Line = tuple[str, str | None]
"""A paragraph line and the bold text it opens with, if any."""


def closings_title(title: str) -> bool:
    """Whether a page's title says it is a closings page ("Weather Closings, Delays ...")."""
    return _TITLE.search(title) is not None


def parse_time(text: str) -> datetime | None:
    """Read an ISO 8601 time as a page states it; a time without an offset is UTC.

    None when ``text`` is not such a time. Fractions of a second are dropped.
    """
    try:
        moment = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).replace(microsecond=0)


def html_modified(html: str) -> datetime | None:
    """The time a page says it was changed: ``article:modified_time``, else ``dateModified``."""
    for pattern in (_META_TIME, _LD_TIME):
        match = pattern.search(html)
        if match is not None:
            moment = parse_time(match.group(1))
            if moment is not None:
                return moment
    return None


def time_tags(html: str) -> list[str]:
    """The markup :func:`html_modified` reads a page's time from, for a fixture slice to keep.

    The ``article:modified_time`` meta tag as the page writes it, or the page's
    ``"dateModified": "..."`` pair wrapped in a JSON-LD script element; empty when
    the page states no time.
    """
    match = _META_TIME.search(html)
    if match is not None and parse_time(match.group(1)) is not None:
        end = html.index(">", match.start()) + 1
        return [html[match.start() : end]]
    match = _LD_TIME.search(html)
    if match is not None and parse_time(match.group(1)) is not None:
        return ['<script type="application/ld+json">{' + match.group(0) + "}</script>"]
    return []


def _inside(node: Node, block: Node, tags: frozenset[str]) -> bool:
    """Whether ``node`` has an ancestor with one of ``tags`` below ``block``."""
    parent = node.parent
    while parent is not None and parent.mem_id != block.mem_id:
        if parent.tag in tags:
            return True
        parent = parent.parent
    return False


def _skipped(node: Node) -> bool:
    """Whether ``node`` is a widget the site injects into a typed block (see :data:`_SKIPPED`)."""
    return node.tag in _SKIPPED or bool(_SKIPPED_CLASS.search(node.attributes.get("class") or ""))


def _in_skipped(node: Node, block: Node) -> bool:
    current: Node | None = node
    while current is not None and current.mem_id != block.mem_id:
        if _skipped(current):
            return True
        current = current.parent
    return False


def _own_text(item: Node) -> str:
    """An item's text without the lists nested in it."""
    parts: list[str] = []
    for child in item.iter(include_text=True):
        if child.tag in _LISTS or _skipped(child):
            continue
        parts.append(child.text(deep=True, separator=" ") if child.tag != "-text" else child.text())
    return collapse(" ".join(parts))


def _details(item: Node) -> list[str]:
    found: list[str] = []
    for child in item.iter(include_text=False):
        if child.tag in _LISTS:
            found.extend(node_text(sub) for sub in child.css("li") if node_text(sub))
    return found


def _leading_bold(node: Node) -> str | None:
    """The text of the bold element an item opens with, if it opens with one."""
    for child in node.iter(include_text=True):
        if child.tag == "-text":
            if collapse(child.text()):
                return None
            continue
        if child.tag in _BOLD:
            return node_text(child) or None
        return None
    return None


def _is_heading(node: Node) -> bool:
    """A heading element, or a short paragraph wholly in bold ("Houston County:")."""
    if node.tag in _HEADINGS:
        return bool(node_text(node))
    if node.tag != "p":
        return False
    text = node_text(node)
    if not text or len(text) > _MAX_HEADING:
        return False
    outer = [b for b in node.css("strong, b") if not _inside(b, node, _BOLD)]
    bold = collapse(" ".join(node_text(b) for b in outer))
    return bool(bold) and bold.replace(" ", "").strip(_TRIM) == text.replace(" ", "").strip(_TRIM)


def _emphasized(node: Node) -> bool:
    """Whether a paragraph's text is wholly inside bold or italic elements (a note, not a row)."""
    for child in _descendants(node):
        if child.tag == "-text" and collapse(child.text()):
            parent = child.parent
            inline: set[str] = set()
            while parent is not None and parent.mem_id != node.mem_id:
                inline.add(parent.tag)
                parent = parent.parent
            if not inline & {"b", "strong", "em", "i"}:
                return False
    return True


def _split(line: str, bold: str | None) -> tuple[str, str, str]:
    """Split a row line into (name, status, how)."""
    if bold is not None and line.startswith(bold) and len(line) > len(bold):
        name = bold.strip(_TRIM)
        status = line[len(bold) :].strip(_TRIM + " ")
        if name and _WORDY.search(status):
            return name, status, "bold"
    match = _SEPARATORS.search(line)
    if match is not None and match.start() > 0:
        name, status = line[: match.start()].strip(_TRIM), line[match.end() :].strip()
        if name and status:
            return name, status, "dash" if _DASH.search(match.group(0)) else "colon"
    match = _VERB.search(line)
    if match is not None and match.start() > 0:
        name, status = line[: match.start()].strip(_TRIM), line[match.end() :].strip()
        if name and status and not _NOT_A_NAME.match(name):
            return name, status, "verb"
    return line.strip(_TRIM), "", "none"


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _extra(line: str, how: str, context: Context) -> dict[str, JsonScalar]:
    extra: dict[str, JsonScalar] = {"line": _clip(line, MAX_EXTRA_TEXT), "split": how}
    section, note = context
    if section is not None:
        extra["section"] = section
    if note is not None:
        extra["note"] = note
    return extra


def _row(line: str, bold: str | None, details: list[str], context: Context) -> ParsedRow | None:
    """One row from its text; a name with nothing after it takes the details as its status."""
    name, status, how = _split(line, bold)
    if not name:
        return None
    extra = _extra(line, how, context)
    if details:
        extra["details"] = _clip(SEPARATOR.join(details), MAX_EXTRA_TEXT)
        status = status or SEPARATOR.join(details)
    return ParsedRow(name=_clip(name, MAX_NAME), status=_clip(status, MAX_STATUS), extra=extra)


def _descendants(node: Node) -> Iterator[Node]:
    """Every node below ``node`` (text nodes too), in document order, and nothing after it."""
    child = node.child
    while child is not None:
        yield child
        yield from _descendants(child)
        child = child.next


def _paragraph_lines(node: Node) -> list[Line]:
    """A paragraph's lines, split at every ``<br>`` in it (inside bold text too).

    Each line comes with the bold text it opens with (after any bullet), and a
    blank line (two ``<br>`` in a row) is kept as ``("", None)``: it ends an entry.
    """
    lines: list[Line] = []
    parts: list[str] = []
    bold: list[str] = []
    leading = True
    for child in _descendants(node):
        if child.tag == "br":
            lines.append((collapse(" ".join(parts)), collapse(" ".join(bold)) or None))
            parts, bold, leading = [], [], True
        elif child.tag == "-text":
            text = child.text()
            parts.append(text)
            if leading and _inside(child, node, _BOLD):
                bold.append(text)
            elif leading and collapse(text).strip(_BULLET):
                leading = False
    lines.append((collapse(" ".join(parts)), collapse(" ".join(bold)) or None))
    return [(text, (b or "").lstrip(_BULLET) or None) for text, b in lines]


def _entries(lines: list[Line]) -> list[list[Line]]:
    """Group a paragraph's lines into entries, split at blank lines."""
    groups: list[list[Line]] = [[]]
    for line in lines:
        if line[0]:
            groups[-1].append(line)
        elif groups[-1]:
            groups.append([])
    return [group for group in groups if group]


def _is_name_line(text: str, bold: str | None) -> bool:
    """Whether a line is a name alone ("Phenix City Schools:"), its status on the next lines."""
    plain = text.lstrip(_BULLET)
    if len(plain) > _MAX_HEADING or not _WORDY.search(plain):
        return False
    whole_bold = bold is not None and bold.strip(_TRIM) == plain.strip(_TRIM)
    return whole_bold or plain.rstrip().endswith(":")


def _written(text: str, bold: str | None) -> tuple[str, str | None] | None:
    """A paragraph line written as an entry, as (its text without the bullet, its bold lead).

    None when the line is not one: it opens with no bullet and neither bold text
    with more text after it nor a name and a status split at a dash or a colon.
    """
    plain = text.lstrip(_BULLET)
    if not _WORDY.search(plain) or _EMPTY_SENTENCE.match(plain):
        return None
    if _BULLETED.match(text):
        return plain, bold
    name, _status, how = _split(plain, bold)
    if how not in _WRITTEN_SPLITS or _LABEL.match(name) or _DATELINE.match(name):
        return None
    return plain, bold


def _entry_rows(entry: list[Line], context: Context) -> list[ParsedRow]:
    """The rows of one paragraph entry (see the module docstring).

    An entry whose first line is a name alone is one row, its status the lines
    after it, unless every line after it opens with a bullet: then the first line
    is their heading and each of them a row. Any other entry's lines are rows each,
    when written as entries.
    """
    (first, bold), rest = entry[0], entry[1:]
    if rest and _is_name_line(first, bold):
        name = first.lstrip(_BULLET).strip(_TRIM)
        if all(_BULLETED.match(text) for text, _bold in rest):
            heading = (name, context[1])
            found = [_row(text.lstrip(_BULLET), line_bold, [], heading) for text, line_bold in rest]
            return [row for row in found if row is not None]
        status = collapse(" ".join(text for text, _bold in rest))
        if name and not _LABEL.match(name):
            extra = _extra(f"{first} {status}", "name-line", context)
            status = _clip(status, MAX_STATUS)
            return [ParsedRow(name=_clip(name, MAX_NAME), status=status, extra=extra)]
    rows: list[ParsedRow] = []
    for text, line_bold in entry:
        line = _written(text, line_bold)
        row = _row(line[0], line[1], [], context) if line is not None else None
        if row is not None:
            rows.append(row)
    return rows


def _cells(row: Node) -> list[str]:
    cells: list[str] = []
    child = row.child
    while child is not None:
        if child.tag in {"td", "th"}:
            cells.append(node_text(child))
        child = child.next
    return cells


def _table_row(node: Node, context: Context) -> ParsedRow | None:
    """A typed table's row: the first cell the name, the others the status (" | " between)."""
    cells = _cells(node)
    if len(cells) < 2 or not cells[0] or any(child.tag == "th" for child in node.iter()):  # noqa: PLR2004
        return None
    name, status = cells[0].strip(_TRIM), SEPARATOR.join(cell for cell in cells[1:] if cell)
    if not name or _HEADER_CELL.match(name):
        return None  # a table's rows are its entries, with or without a status typed beside them
    extra = _extra(SEPARATOR.join(cells), "table", context)
    return ParsedRow(name=_clip(name, MAX_NAME), status=_clip(status, MAX_STATUS), extra=extra)


@dataclass
class _Paragraph:
    """A paragraph of a block typed as paragraphs, with what was in force before it."""

    node: Node
    context: Context
    after_heading: bool


@dataclass
class _Reader:
    """What :func:`read_typed` has found so far, as it walks the block."""

    block: Node
    listed: bool = False
    items: list[ParsedRow] = field(default_factory=list)
    paragraphs: list[_Paragraph] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    section: str | None = None
    note: str | None = None
    headed: bool = False

    @property
    def context(self) -> Context:
        return self.section, self.note

    def heading(self, text: str) -> None:
        self.section = text.strip(_TRIM) or self.section
        self.headed = True
        self.texts.append(text)

    def item(self, node: Node) -> None:
        self.listed = True
        line, details = _own_text(node), _details(node)
        if not line:
            # An empty bullet is no entry; an item holding only a list, each item of it one.
            found = [_row(detail, None, [], self.context) for detail in details]
            self.texts.extend(details)
            self.items.extend(row for row in found if row is not None)
            return
        self.texts.append(line)
        if line.endswith(":") and not details:
            self.heading(line)  # a heading typed as an item ("Pike County:")
            return
        if _EMPTY_SENTENCE.match(line) and not details:
            return  # "There are no closings at this time", typed as an item
        row = _row(line, _leading_bold(node), details, self.context)
        if row is not None:
            self.items.append(row)

    def table_row(self, node: Node) -> None:
        cells = _cells(node)
        if len(cells) >= 2:  # noqa: PLR2004
            self.listed = True
        row = _table_row(node, self.context)
        if row is not None:
            self.items.append(row)

    def paragraph(self, node: Node) -> None:
        text = node_text(node)
        if not text:
            return
        self.texts.append(text)
        self.paragraphs.append(_Paragraph(node, self.context, self.headed))
        if _DATED.search(text) and not any(_written(t, b) for t, b in _paragraph_lines(node)):
            self.note = _clip(text, _MAX_NOTE)

    def visit(self, node: Node) -> None:
        block = self.block
        if _in_skipped(node, block) or _inside(node, block, _CELLS):
            return
        if _is_heading(node) and not _inside(node, block, _HEADINGS | {"p"}):
            self.heading(node_text(node))
        elif node.tag == "tr":
            self.table_row(node)
        elif node.tag == "li":
            self.item(node)
        elif node.tag == "p" and not _inside(node, block, _LISTS | {"p"}):
            self.paragraph(node)

    def paragraph_rows(self) -> list[ParsedRow]:
        """The rows of a block typed as paragraphs (see the module docstring)."""
        rows: list[ParsedRow] = []
        for paragraph in self.paragraphs:
            for entry in _entries(_paragraph_lines(paragraph.node)):
                rows.extend(_entry_rows(entry, paragraph.context))
        if rows:
            return rows
        for paragraph in self.paragraphs:
            node, text = paragraph.node, node_text(paragraph.node)
            if not paragraph.after_heading or _emphasized(node) or _says_empty(text):
                continue
            row = _row(text, _leading_bold(node), [], paragraph.context)
            if row is not None and _WORDY.search(row.name):
                rows.append(row)
        return rows


def _says_empty(text: str) -> bool:
    """Whether a short text says the typed list holds nothing, or is the page's standing note."""
    if len(text) > _MARKER_LENGTH:
        return bool(STANDING_NOTE.search(text))
    return bool(NO_CLOSINGS.search(text) or STANDING_NOTE.search(text))


def read_typed(block: Node, variant: str, modified: datetime | None) -> Listing:
    """Read a block of closings typed by hand (see the module docstring).

    Raises:
        ShapeError: the block holds no row and does not say it holds none.
    """
    reader = _Reader(block)
    # css("*") is the block itself, then its descendants in document order.
    for node in block.css("*")[1:]:
        reader.visit(node)
    rows = reader.items if reader.listed else reader.paragraph_rows()
    if not rows and not any(_says_empty(text) for text in reader.texts):
        seen = collapse(" ".join(reader.texts))
        raise ShapeError(
            "a typed closings block with no entry and no sentence saying it holds none: "
            f"{seen[:120]!r}"
        )
    return _typed_listing(rows, variant, modified)


def _typed_listing(rows: Sequence[ParsedRow], variant: str, modified: datetime | None) -> Listing:
    """A typed list's listing: every row stamped with the page's time, when it states one."""
    if modified is not None:
        stamp = modified.strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = [
            row.model_copy(
                update={"updated_text": stamp, "extra": {**row.extra, "updated_scope": "page"}}
            )
            for row in rows
        ]
    return Listing(
        variant=variant,
        state=ListingState.POPULATED if rows else ListingState.EMPTY,
        rows=tuple(rows),
        list_updated_at=modified,
        typed=True,
    )


type Segment = tuple[str, bool]
"""A text node of a paragraph line, and whether it is inside a link."""


def _paragraph_segments(node: Node) -> list[list[Segment]]:
    """A paragraph's lines as their text nodes, split as :func:`_paragraph_lines` splits them."""
    lines: list[list[Segment]] = []
    parts: list[Segment] = []
    for child in _descendants(node):
        if child.tag == "br":
            lines.append(parts)
            parts = []
        elif child.tag == "-text":
            parts.append((child.text(), _inside(child, node, _LINK)))
    lines.append(parts)
    return lines


def _linked_starts(segments: list[Segment]) -> list[int] | None:
    """Where the line's linked words start in its text; None when every word is linked."""
    starts: list[int] = []
    unlinked = False
    for number, (text, linked) in enumerate(segments):
        if not _WORDY.search(text):
            continue
        if not linked:
            unlinked = True
            continue
        before = collapse(" ".join(part for part, _ in segments[:number]))
        starts.append(len(before) + (1 if before else 0))
    return starts if unlinked else None


def _points_elsewhere(line: Line, segments: list[Segment], *, name_line: bool = False) -> bool:
    """Whether a paragraph line is a note pointing elsewhere rather than an entry.

    A line wholly inside a link is one ("LIST: Additional Northeast Oklahoma
    closings", a link to a story), as is one whose text after its name holds a
    link ("Administrators: To submit a closing, click here."); a name linked to
    the organization's site, its status in plain text, is not. For a name line
    (``name_line``, its status on the lines after it) only the whole line counts.
    """
    starts = _linked_starts(segments)
    if starts is None:
        return True
    if name_line or not starts:
        return False
    text, bold = line
    plain = text.lstrip(_BULLET)
    name = _split(plain, bold)[0]
    found = plain.find(name)
    name_end = len(text) - len(plain) + max(found, 0) + len(name)
    return any(start >= name_end for start in starts)


def _beside_entries(node: Node, context: Context) -> list[ParsedRow]:
    """The entries of a paragraph beside a closings system's list (see :func:`entries_beside`)."""
    groups: list[list[tuple[Line, list[Segment]]]] = [[]]
    for line, segments in zip(_paragraph_lines(node), _paragraph_segments(node), strict=True):
        if line[0]:
            groups[-1].append((line, segments))
        elif groups[-1]:
            groups.append([])
    rows: list[ParsedRow] = []
    for group in (group for group in groups if group):
        (first, first_segments), rest = group[0], group[1:]
        entry = [line for line, _ in group]
        if rest and _is_name_line(*first) and not all(_BULLETED.match(t) for (t, _), _ in rest):
            # One entry: a name line and its status on the lines after it.
            linked = _points_elsewhere(first, first_segments, name_line=True) or any(
                _linked_starts(segments) != [] for _, segments in rest
            )
            rows.extend([] if linked else _entry_rows(entry, context))
            continue
        heading = bool(rest) and _is_name_line(*first)
        for line, segments in group[1:] if heading else group:
            if not _points_elsewhere(line, segments):
                sub = (first[0].lstrip(_BULLET).strip(_TRIM), context[1]) if heading else context
                rows.extend(_entry_rows([line], sub))
    return rows


def entries_beside(block: Node, *, paragraphs: bool = True) -> tuple[ParsedRow, ...]:
    """The entries typed into a page's content beside a closings system's list.

    ``block`` is the page's content with the system's list taken out of it (see
    :func:`read_beside`). Its list items and table rows are entries, read as
    :func:`read_typed` reads a block typed as a list (widgets passed over, an empty
    item or one saying the list is empty none, an item ending in a colon a heading).
    When it has none, its paragraph entries are: a line written as an entry (a bullet,
    bold text followed by more text, a name and a status split at a dash or a colon)
    or a name line with its status lines after it, as :func:`read_typed` reads a
    block typed as paragraphs, except a note pointing elsewhere: a line wholly
    inside a link ("LIST: Additional Northeast Oklahoma closings", a link to a
    story), or one whose text after its name holds a link ("Administrators: To
    submit a closing, click here."), as every paragraph line with a link on the
    typed pages read so far was (a name line whose status lines hold a link, a
    contact's name over a mailto link, too). A name linked to the organization's own
    site with its status in plain text is an entry. Plain paragraphs (a
    station's blurb, instructions for organizations, a sign-up widget's text) are
    never entries here: they stand beside the list on quiet days and storm days
    alike. ``paragraphs`` false leaves paragraph entries out altogether (for pages
    whose notes beside the list are written like entries, see
    :mod:`snowlight.sources.stations.scripps`).
    """
    reader = _Reader(block)
    # css("*") is the block itself, then its descendants in document order.
    for node in block.css("*")[1:]:
        reader.visit(node)
    if reader.items or not paragraphs:
        return tuple(reader.items)
    rows: list[ParsedRow] = []
    for paragraph in reader.paragraphs:
        rows.extend(_beside_entries(paragraph.node, paragraph.context))
    return tuple(rows)


def read_beside(block: Node, variant: str, modified: datetime | None) -> Listing | None:
    """Read the entries typed beside a closings system's list, or None when there are none.

    Some stations type closings into the page that holds their closings system's
    list, beside the list, while the list itself stays empty: KIAH (CW39 Houston)
    listed eight districts under its empty closings list for the storm of
    22 January 2025 (archived 2025-01-25), and WIVB typed a school's closing above
    its list on 2026-09-04. The entries are those of :func:`entries_beside`; like
    any typed list, the listing carries the page's time (``modified``) and is marked
    ``typed``. Whether a station's entries beside its list are read at all is the
    caller's decision (only the stations the registry files as typing closings
    there; on any other station's page such entries are an error).
    """
    rows = entries_beside(block)
    return _typed_listing(rows, variant, modified) if rows else None


def empty_typed(variant: str, modified: datetime | None) -> Listing:
    """The empty state of a typed list whose container the page holds with nothing in it."""
    return Listing(
        variant=variant, state=ListingState.EMPTY, rows=(), list_updated_at=modified, typed=True
    )


def rest_modified(page: object) -> datetime | None:
    """A WordPress REST page object's ``modified_gmt`` (UTC), when it has one."""
    if not isinstance(page, dict):
        return None
    value = page.get("modified_gmt")
    return parse_time(value) if isinstance(value, str) else None


def rest_title(page: object) -> str:
    """A WordPress REST page object's rendered title, as text."""
    if not isinstance(page, dict):
        return ""
    title = page.get("title")
    rendered = title.get("rendered") if isinstance(title, dict) else title
    return collapse(re.sub(r"<[^>]+>", " ", rendered)) if isinstance(rendered, str) else ""


_MONTHS = (
    "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
)  # fmt: skip
_WEEKDAYS = ("mon", "tues", "wednes", "thurs", "fri", "satur", "sun")
_NAMED_DAY = re.compile(
    r"\b(?:(mon|tues|wednes|thurs|fri|satur|sun)day,?\s+)?"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+([0-9]{1,2})(?:st|nd|rd|th)?\b"
    r"(?:,?\s+([0-9]{4})\b)?",
    re.IGNORECASE,
)
NEAR_BEFORE = timedelta(days=1)
NEAR_AFTER = timedelta(days=3)
"""How far a day a typed page names may lie before or after the read's day to date it."""


def _day(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def named_days(text: str, read_on: date) -> list[date]:
    """The calendar days ``text`` pins down (see the module docstring), as of ``read_on``."""
    found: list[date] = []
    for match in _NAMED_DAY.finditer(text):
        weekday, month_name, day_text, year_text = match.groups()
        month = _MONTHS.index(month_name.lower()) + 1
        day = int(day_text)
        wanted = _WEEKDAYS.index(weekday.lower()) if weekday else None
        if year_text is not None:
            candidates = [_day(int(year_text), month, day)]
        elif wanted is not None:
            candidates = [_day(read_on.year + delta, month, day) for delta in (-1, 0, 1)]
        else:
            continue  # a month and day alone could be any year's
        days = [
            d for d in candidates if d is not None and (wanted is None or d.weekday() == wanted)
        ]
        if days:
            found.append(min(days, key=lambda d: abs((d - read_on).days)))
    return found


def names_day_near(listing: Listing, read_at: datetime) -> bool:
    """Whether a typed list's headings, notes or lines pin down a day near ``read_at``."""
    read_on = read_at.astimezone(UTC).date()
    for row in listing.rows:
        texts = [row.name, row.status]
        texts += [str(row.extra[key]) for key in ("section", "note", "line") if row.extra.get(key)]
        for day in named_days(" | ".join(texts), read_on):
            if read_on - NEAR_BEFORE <= day <= read_on + NEAR_AFTER:
                return True
    return False
