"""Flathead County (Montana) Superintendent of Schools: the county's school closures page.

The county superintendent's office keeps one page for every public and private
school in Flathead County (``https://flatheadcounty.gov/department-directory/schools/emergency-school-closures``;
the county's 23 districts report their decisions to it, and it relays them to the
local radio stations). Every school is listed with its status, so the page always
holds rows: "Open" for most, and "Closed", a delay or an early out with the reason
in the Comments column when a school changes (live on 2026-09-27: 35 schools, one
of them "Closed" with the comment "No running water"; in the archived capture of
2026-01-19, the list "UPDATED INFORMATION FOR Wednesday, December 17th, 2025": five
schools "Closed" and Deer Park "2 hour delayed start due to power"). Variants this
adapter reads:

``flathead-closure-tables``
    The page as the county's site has served it since August 2026 (first archived
    2026-08-15): a "Last Updated" line (``Last Updated September 25, 26 8:11 AM``:
    month, day, two-digit year, time), a notice card ("Checking for a Closure?",
    where the page says the reason for a closure is also posted), and one
    ``table.closure-table`` per group, each labelled by its heading ("Public
    Schools", "Private Schools") with the columns School, Status and Comments.

``flathead-card-tables``
    The page before that, on ``flatheadcounty.gov`` (archived from 2025-04-27 to
    2026-04-12) and on the county's old domain ``flathead.mt.gov`` (archived from
    2022-10-02 to 2025-08-15): a line "SCHOOL CLOSURE INFORMATION FOR 2025-26" (in
    January 2023, "... FOR 2023"), a line "UPDATED INFORMATION FOR Wednesday,
    December 17th, 2025" (in January 2023 the date stood on the next line: "UPDATED
    INFORMATION FOR", "MONDAY, JANUARY 9, 2023"), and one card per group, each an
    ``h3`` heading ("Public Schools", "Private Schools") over a plain table with the
    same three columns (names in capitals; statuses "Open" or, until 2023, "OPEN").

In both, each body row is one school: the School cell is the name, the Status cell
the status (it may be blank), and the Comments cell (when it holds text)
``raw_extra["comment"]``; the table's heading is ``raw_extra["table"]``, and the
page's update line ("Last Updated ..." or "UPDATED INFORMATION FOR ...", without
those words) each row's ``raw_updated_text`` (``raw_extra["updated_scope"]`` is
``"page"``). The newer page's notice card text is ``raw_extra["notice"]``; the older
page's school year ("2025-26") is ``raw_extra["school_year"]``.

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`,
including a closures table whose columns are not School, Status and Comments, a
row of any other width, and a page whose tables hold no school at all.
"""

import re
from html import escape

from selectolax.parser import HTMLParser, Node

from snowlight.sources.stations.gap_markup import (
    document,
    html_text,
    make_listing,
    make_row,
    node_text,
)
from snowlight.sources.stations.model import JsonScalar, Listing, ParsedRow, ShapeError

TABLES = "flathead-closure-tables"
CARDS = "flathead-card-tables"
COLUMNS = ("School", "Status", "Comments")
_UPDATED = re.compile(r"^Last Updated\s*(.*)$", re.IGNORECASE)
_CARD_UPDATED = re.compile(r"^UPDATED INFORMATION FOR\s*(.*)$", re.IGNORECASE)
_CARD_YEAR = re.compile(r"^SCHOOL CLOSURE INFORMATION FOR\s+(\d{4}(?:-\d{2})?)$", re.IGNORECASE)


def _updated(tree: HTMLParser) -> str | None:
    for node in tree.css("p.ccm-block-page-attribute-display-wrapper"):
        found = _UPDATED.match(node_text(node))
        if found is not None:
            return found.group(1) or None
    return None


def _notice(tree: HTMLParser) -> str | None:
    card = tree.css_first("aside.alert-seasonal .alert-message")
    text = node_text(card)
    return text or None


def _heading(tree: HTMLParser, table: Node) -> str:
    label = table.attributes.get("aria-labelledby")
    heading = tree.css_first(f"#{label}") if label else None
    text = node_text(heading)
    if not text:
        raise ShapeError("a closures table has no heading")
    return text


def _header(table: Node) -> tuple[str, ...]:
    return tuple(node_text(th) for th in table.css("thead th"))


def _table_rows(
    table: Node, extra: dict[str, JsonScalar], updated: str | None
) -> tuple[list[ParsedRow], int]:
    header = _header(table)
    if header != COLUMNS:
        raise ShapeError(f"a closures table's columns are {header}, not {COLUMNS}")
    rows: list[ParsedRow] = []
    skipped = 0
    for tr in table.css("tbody tr"):
        cells = [node_text(td) for td in tr.css("td")]
        if len(cells) != len(COLUMNS):
            raise ShapeError(f"a closures row has {len(cells)} cells, not {len(COLUMNS)}")
        fields = dict(extra)
        if updated:
            fields["updated_scope"] = "page"
        if cells[2]:
            fields["comment"] = cells[2]
        found = make_row(cells[0], cells[1], updated, fields)
        if found is None:
            skipped += 1
        else:
            rows.append(found)
    return rows, skipped


def _closure_tables(tree: HTMLParser, tables: list[Node]) -> Listing:
    updated = _updated(tree)
    notice = _notice(tree)
    rows: list[ParsedRow] = []
    skipped = 0
    for table in tables:
        extra: dict[str, JsonScalar] = {"table": _heading(tree, table)}
        if notice:
            extra["notice"] = notice
        found, nameless = _table_rows(table, extra, updated)
        rows.extend(found)
        skipped += nameless
    if not rows:
        raise ShapeError("the Flathead County closures tables list no school")
    return make_listing(TABLES, rows, skipped=skipped)


def _card_heading(table: Node) -> str:
    card = table.parent
    heading = card.css_first("h3") if card is not None else None
    text = node_text(heading)
    if not text:
        raise ShapeError("a closures card has no heading")
    return text


def _card_line(tree: HTMLParser, pattern: re.Pattern[str]) -> str | None:
    """The text after a line's label; when the label stands alone, the next line's text."""
    lines = [node_text(node) for node in tree.css("main p.h4, main h4")]
    for number, line in enumerate(lines):
        found = pattern.match(line)
        if found is None:
            continue
        if found.group(1):
            return found.group(1)
        return lines[number + 1] or None if number + 1 < len(lines) else None
    return None


def _card_tables(tree: HTMLParser, tables: list[Node]) -> Listing:
    updated = _card_line(tree, _CARD_UPDATED)
    year = _card_line(tree, _CARD_YEAR)
    rows: list[ParsedRow] = []
    skipped = 0
    for table in tables:
        extra: dict[str, JsonScalar] = {"table": _card_heading(table)}
        if year:
            extra["school_year"] = year
        found, nameless = _table_rows(table, extra, updated)
        rows.extend(found)
        skipped += nameless
    if not rows:
        raise ShapeError("the Flathead County closures cards list no school")
    return make_listing(CARDS, rows, skipped=skipped)


def _card_tables_of(tree: HTMLParser) -> list[Node]:
    main = tree.css_first("main")
    if main is None:
        return []
    return [table for table in main.css("div.card table") if _header(table) == COLUMNS]


def parse(body: bytes) -> Listing:
    """Read the Flathead County superintendent's school closures page."""
    tree = HTMLParser(html_text(body))
    tables = tree.css("table.closure-table")
    if tables:
        return _closure_tables(tree, tables)
    cards = _card_tables_of(tree)
    if cards and _card_line(tree, _CARD_UPDATED) is not None:
        return _card_tables(tree, cards)
    raise ShapeError("not the Flathead County closures page (no closure table)")


def slice_body(body: bytes) -> bytes:
    """Keep the update line, the notice card or school year, and each table with its heading."""
    found = parse(body)
    tree = HTMLParser(html_text(body))
    parts: list[str] = []
    if found.variant == CARDS:
        parts.append("<main>")
        nodes = tree.css("main p.h4, main h4")
        for number, node in enumerate(nodes):
            text = node_text(node)
            if _CARD_YEAR.match(text) or _CARD_UPDATED.match(text):
                parts.append(node.html or "")
            alone = _CARD_UPDATED.match(text)
            if alone is not None and not alone.group(1) and number + 1 < len(nodes):
                parts.append(nodes[number + 1].html or "")
        for table in _card_tables_of(tree):
            title = escape(_card_heading(table))
            parts.append(f'<div class="card"><h3>{title}</h3>{table.html or ""}</div>')
        parts.append("</main>")
        return document("\n".join(parts))
    for node in tree.css("p.ccm-block-page-attribute-display-wrapper"):
        if _UPDATED.match(node_text(node)):
            parts.append(node.html or "")
    card = tree.css_first("aside.alert-seasonal")
    if card is not None:
        parts.append(card.html or "")
    for table in tree.css("table.closure-table"):
        label = table.attributes.get("aria-labelledby") or ""
        heading = tree.css_first(f"#{label}")
        parts.append(heading.html or "" if heading is not None else "")
        parts.append(table.html or "")
    return document("\n".join(parts))
