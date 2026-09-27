"""ABC Owned Television Stations' school closings pages (``https://{site}/community/schoolclosings/``).

The eight ABC-owned stations (WABC, WPVI, WLS, KABC, KGO, KFSN, WTVD, KTRK) share
one site platform (Disney's "abcotv" React application, rendered on the server).
The page's list comes from the application's own state, which the server writes
into the page twice: as the rendered list and as the page state's
``"schoolclosings": {"time": <epoch seconds>, "states": [...]}`` entry. The page
script (``community.schoolclosings-*.js``, read 2026-09-26) builds that entry from
the closings data as ``{"time": timestamp, "states": [{"name", "abbrev",
"schools": [{"name", "county", "text"}]}]}`` (``text`` is the data's
``closingText``) and renders it as below. Variants this adapter reads:

``abc-otv-list``
    The rendered list (seen live on 2026-09-26 at all seven stations that show it)::

        <section class="school-list inner">
          <div class="meta">Last updated: <!-- -->09/26/2026 01:05am</div>
          <a class="state-anchor" href="#schools-NY">New York</a> ...
          <a name="schools-NY" class="anchor"></a><div class="section-header">New York</div>
          <ul class="school-closings-list">
            <li class="school-closing">
              <span class="school-closing-name">Name</span>
              <span class="school-closing-county"> (County)</span>
              <span class="school-closing-text"> - Closing text.</span>
            </li> ...
          </ul> ...
        </section>

    Each ``li.school-closing`` is a row: ``school-closing-name`` is the name, the
    closing text (the renderer's " - " before it and "." after it removed) is the
    status, and the state heading and the county (the renderer's parentheses
    removed) go in ``raw_extra`` as ``state`` and ``county``. The page's "Last
    updated" text is every row's ``raw_updated_text`` (``raw_extra["updated_scope"]``
    is ``"page"``). With no state listed, the page renders one
    ``li.school-closing`` whose name is the renderer's default "No Closings at this
    time." and nothing else: the empty state. The page state's ``time`` is the
    listing's :attr:`~snowlight.sources.stations.model.Listing.list_updated_at` (the
    page's "Last updated" is that instant formatted in UTC: the three California
    pages and WLS all say 02/12/2019 08:39pm for ``time`` 1550003979), so a list
    last changed before the last winter began is read as stale; the state's
    schools must be exactly the rendered rows, in order, or the page is an error.
    A state the data leaves unnamed (``"name": null``; WPVI on 19 January 2024)
    renders an empty heading, and its rows carry no ``state``; a school with no
    county renders no county span, and its row carries no ``county``.

``abc-legacy-list``
    The design the pages had before the abcotv application (server-rendered
    without the page state; archived captures from February 2017 to February 2019
    show it)::

        <section class="school-list inner">
          <div class="meta">Last updated: 02/19/2019 06:53pm</div>        (not always there)
          <a href="#schools-PA" class="state-anchor">Pennsylvania</a> ...
          <ul class="school-closings-list"></ul>                           (before each state)
          <a name="schools-PA" class="anchor"></a><div class="section-header">Pennsylvania</div>
          <ul class="school-closings-list"><li class="school-closing">...</li> ...</ul> ...
        </section>

    Rows are the same ``li.school-closing`` elements, read the same way; a page
    without state headings (KTRK and WLS in January and February 2018) lists every
    row in one unheaded list and has no "Last updated" line either (the rows then
    have no ``state`` and no ``raw_updated_text``). The empty lists the renderer
    writes before each state's anchor hold nothing and are passed over. The empty
    state is one unheaded list holding only the "No Closings at this time." line
    (WTVD's page of January 2018 added, under the heading "More Closings &
    Delays", a list of one link to a government, business and church closings
    page: links, not closings, so it is passed over, and a list under that heading
    holding anything but links is an error). The "Last updated" time here is the
    station's local time, and there is no page state, so
    :attr:`~snowlight.sources.stations.model.Listing.list_updated_at` is None.
    The design's earliest capture read (KTRK, 16 December 2015) says nothing when
    nothing is listed: its list section holds one empty list and nothing else,
    which is the empty state too.

``abc-otv-frame``
    WLS (Chicago) renders no list: its page frames another file in the list's
    place (``<div class="main main-left"><iframe src="https://wgnr-closings.s3.amazonaws.com/index.html">``,
    a copy of the Emergency Closing Center application; every archived WLS page
    from January 2021 to January 2026 frames it, and it answered 403 on
    2026-09-26). A
    :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED` listing whose
    ``follows`` names the framed file.

``abc-framed-ecc-app``
    The framed file itself, as the archive holds it (March 2020 and February
    2021): the closing center's application shell
    (:func:`snowlight.sources.stations.ecc.is_app`), whose list arrives by script
    from the closing center's data file (read for Chicago as ``ecc-chicago``). A
    :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED` listing that
    names nothing.

Archived storm-day captures (downloaded by the archive-captures workflow, runs
36293423860 and later) show every variant above with rows: WABC in February 2017
(legacy, 4 rows), May and December 2019, February 2021 and February 2026; WPVI
in February 2019 (legacy, 187 rows), January 2021, January 2024 (316 rows) and
February 2026; WTVD in February 2020, January 2022, January 2025 and January
2026; KTRK in August 2017 (legacy, Hurricane Harvey, 121 rows), January 2018
(legacy, unheaded) and January 2026; WLS in January 2015 (legacy, 962 rows) and
February 2018 (legacy, unheaded, 1,062 rows). The KABC, KGO and KFSN pages were never
seen with a row: every capture from May 2019 to June 2025 carries the page state
time of 2019-02-12 20:39:39 UTC.

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`.
"""

import json
import re
from datetime import UTC, datetime

from selectolax.parser import Node

from snowlight.sources.stations import ecc
from snowlight.sources.stations.body import decode
from snowlight.sources.stations.model import (
    JsonScalar,
    Listing,
    ListingState,
    ParsedRow,
    ShapeError,
)
from snowlight.sources.stations.network_markup import (
    element_end,
    iframe_sources,
    minimal_document,
    node_text,
    parse_html,
    text_of,
)

EMPTY_NAME = "No Closings at this time."
"""The name the page's row component renders when it is given no school."""
_SECTION_OPEN = re.compile(r"<section\b[^>]*\bclass=\"school-list\b[^\"]*\"[^>]*>", re.IGNORECASE)
_MAIN_OPEN = re.compile(r"<div\b[^>]*\bclass=\"main main-left\"[^>]*>", re.IGNORECASE)
_STATE_KEY = re.compile(r"\"schoolclosings\":(?=\{\"time\")")
_UPDATED = re.compile(r"^Last updated:\s*(.*)$")
MORE_HEADING = "More Closings & Delays"
"""The heading of the legacy page's list of links to other closings (not schools)."""
_COUNTY = re.compile(r"^\((.*)\)$")


def _state(html: str) -> tuple[int, list[tuple[str, str | None, str | None, str | None]]] | None:
    """Return the page state's time and its schools as (name, county, text, state), or None."""
    match = _STATE_KEY.search(html)
    if match is None:
        return None
    try:
        value, _end = json.JSONDecoder().raw_decode(html, match.end())
    except ValueError as error:
        raise ShapeError(f"the page's schoolclosings state is not JSON: {error}") from error
    if not isinstance(value, dict) or set(value) != {"time", "states"}:
        raise ShapeError("the page's schoolclosings state is not {time, states}")
    time, states = value["time"], value["states"]
    if not isinstance(time, int) or isinstance(time, bool) or not isinstance(states, list):
        raise ShapeError("the page's schoolclosings time or states has an unexpected type")
    schools: list[tuple[str, str | None, str | None, str | None]] = []
    for state in states:
        if not isinstance(state, dict) or not isinstance(state.get("schools"), list):
            raise ShapeError("a schoolclosings state has no schools list")
        name = state.get("name")
        for school in state["schools"]:
            if not isinstance(school, dict):
                raise ShapeError("a schoolclosings school is not an object")
            fields = [school.get(key) for key in ("name", "county", "text")]
            if not all(item is None or isinstance(item, str) for item in fields):
                raise ShapeError("a schoolclosings school field is not text")
            schools.append(
                (
                    fields[0] or "",
                    fields[1],
                    fields[2],
                    name if isinstance(name, str) else None,
                )
            )
    return time, schools


def _strip_affixes(text: str, prefix: str, suffix: str) -> str:
    if text.startswith(prefix):
        text = text[len(prefix) :]
    if text.endswith(suffix):
        text = text[: -len(suffix)]
    return text.strip()


def _row(item: Node, state: str | None, updated: str | None) -> ParsedRow | None:
    name = node_text(item.css_first("span.school-closing-name"))
    county_node = item.css_first("span.school-closing-county")
    text_node = item.css_first("span.school-closing-text")
    county = node_text(county_node)
    county_match = _COUNTY.match(county)
    text = _strip_affixes(node_text(text_node), "- ", ".") if text_node is not None else ""
    if not name:
        return None
    extra: dict[str, JsonScalar] = {"updated_scope": "page"} if updated else {}
    if state is not None:
        extra["state"] = state
    if county_node is not None:
        extra["county"] = county_match.group(1).strip() if county_match else county
    return ParsedRow(name=name, status=text, updated_text=updated, extra=extra)


def _heading(block: Node) -> str | None:
    """Return the heading (``div.section-header``) just before a list, or None when none is."""
    header = block.prev
    while header is not None and header.tag == "-text":
        header = header.prev
    if header is None or "section-header" not in (header.attributes.get("class") or ""):
        return None
    return node_text(header)


def _is_empty_line(items: list[Node]) -> bool:
    """Whether ``items`` is only the renderer's default "No Closings" line."""
    if len(items) != 1:
        return False
    only = items[0]
    return (
        node_text(only.css_first("span.school-closing-name")) == EMPTY_NAME
        and only.css_first("span.school-closing-county") is None
        and only.css_first("span.school-closing-text") is None
    )


def _is_link_list(items: list[Node]) -> bool:
    """Whether every item is a bare link (the legacy "More Closings & Delays" list)."""
    return bool(items) and all(
        item.css_first("span.school-closing-name") is None and item.css_first("a[href]") is not None
        for item in items
    )


def _updated(section: Node, *, required: bool) -> str | None:
    meta_node = section.css_first("div.meta")
    if meta_node is None and not required:
        return None
    meta = _UPDATED.match(node_text(meta_node))
    if meta is None:
        raise ShapeError("the school list has no 'Last updated' line")
    return meta.group(1).strip() or None


def _rows(
    blocks: list[tuple[str | None, list[Node]]], updated: str | None
) -> tuple[list[ParsedRow], int]:
    rows: list[ParsedRow] = []
    skipped = 0
    for heading, items in blocks:
        for item in items:
            row = _row(item, heading or None, updated)
            if row is None:
                skipped += 1
            else:
                rows.append(row)
    return rows, skipped


def _list(html: str, section: Node) -> Listing:
    """Read the current (abcotv application) list: every list under a state heading."""
    updated = _updated(section, required=True)
    lists = section.css("ul.school-closings-list")
    blocks: list[tuple[str | None, list[Node]]] = []
    for block in lists:
        heading = _heading(block)
        if heading is None:
            raise ShapeError("a list of closings has no state heading before it")
        blocks.append((heading, block.css("li.school-closing")))
    rows, skipped = _rows(blocks, updated)
    listed = sum(len(items) for _heading_text, items in blocks)
    page_state = _state(html)
    list_time = datetime.fromtimestamp(page_state[0], UTC) if page_state is not None else None
    if not lists:
        if not _is_empty_line(section.css("li.school-closing")):
            raise ShapeError("the school list has neither closings nor the no-closings line")
        if page_state is not None and page_state[1]:
            raise ShapeError("the page state lists schools the page does not render")
        return Listing(
            variant="abc-otv-list", state=ListingState.EMPTY, rows=(), list_updated_at=list_time
        )
    if len(section.css("li.school-closing")) != listed:
        raise ShapeError("a closing is rendered outside every state's list")
    if page_state is not None:
        expected = [" ".join(name.split()) for name, *_rest in page_state[1] if name.strip()]
        if expected != [row.name for row in rows]:
            raise ShapeError("the page state's schools differ from the rendered rows")
    if not rows:
        raise ShapeError("every rendered closing is missing its name")
    return Listing(
        variant="abc-otv-list",
        state=ListingState.POPULATED,
        rows=tuple(rows),
        skipped_rows=skipped,
        list_updated_at=list_time,
    )


def _is_bare_empty_list(section: Node) -> bool:
    """Whether the list section holds one empty list and nothing else (KTRK, December 2015)."""
    children = list(section.iter(include_text=False))
    return (
        len(children) == 1
        and children[0].tag == "ul"
        and "school-closings-list" in (children[0].attributes.get("class") or "").split()
        and not list(children[0].iter(include_text=False))
        and not node_text(section)
    )


def _legacy_list(section: Node) -> Listing:
    """Read the older server-rendered list (``abc-legacy-list``, see the module docstring)."""
    updated = _updated(section, required=False)
    blocks: list[tuple[str | None, list[Node]]] = []
    empty_line = False
    for block in section.css("ul.school-closings-list"):
        heading = _heading(block)
        items = block.css("li.school-closing")
        if heading == MORE_HEADING:
            if not _is_link_list(items):
                raise ShapeError(f"the '{MORE_HEADING}' list holds something other than links")
            continue
        if heading is None and not items:
            continue  # the empty list the renderer writes before each state's anchor
        if heading is None and _is_empty_line(items):
            empty_line = True
            continue
        blocks.append((heading, items))
    listed = sum(len(items) for _heading_text, items in blocks)
    if empty_line and listed:
        raise ShapeError("the school list has both closings and the no-closings line")
    if any(
        item.parent is None or item.parent.tag != "ul" for item in section.css("li.school-closing")
    ):
        raise ShapeError("a closing is rendered outside every list")
    if empty_line or (not listed and _is_bare_empty_list(section)):
        return Listing(variant="abc-legacy-list", state=ListingState.EMPTY, rows=())
    if not listed:
        raise ShapeError("the school list has neither closings nor the no-closings line")
    if len({heading is None for heading, _items in blocks}) > 1:
        raise ShapeError("the school list mixes lists with and without a state heading")
    rows, skipped = _rows(blocks, updated)
    if not rows:
        raise ShapeError("every rendered closing is missing its name")
    return Listing(
        variant="abc-legacy-list",
        state=ListingState.POPULATED,
        rows=tuple(rows),
        skipped_rows=skipped,
    )


def _frame(html: str) -> Listing | None:
    match = _MAIN_OPEN.search(html)
    if match is None:
        return None
    block = html[match.start() : element_end(html, match.start(), "div")]
    sources = [src for src in iframe_sources(block) if src]
    if len(sources) != 1:
        return None
    return Listing(
        variant="abc-otv-frame", state=ListingState.DEFERRED, rows=(), follows=(sources[0],)
    )


def parse(body: bytes) -> Listing:
    """Read an ABC OTV school closings page (see the module docstring)."""
    html = text_of(decode(body))
    tree = parse_html(html)
    section = tree.css_first("section.school-list")
    if section is not None:
        if _STATE_KEY.search(html) is None:
            return _legacy_list(section)
        return _list(html, section)
    framed = _frame(html)
    if framed is not None:
        return framed
    if ecc.is_app(html):
        # The file WLS's page frames: a copy of the closing center's application.
        return Listing(variant="abc-framed-ecc-app", state=ListingState.DEFERRED, rows=())
    raise ShapeError("not an ABC OTV school closings page this adapter knows")


def slice_page(body: bytes) -> bytes:
    """Keep what :func:`parse` reads: the list section or the main frame, and the page state.

    The page state's ``"schoolclosings": {...}`` entry is kept verbatim inside a
    ``<script>`` of its own. A body that is not such a page is refused.
    """
    html = text_of(decode(body))
    parts: list[str] = []
    section = _SECTION_OPEN.search(html)
    if section is not None:
        parts.append(html[section.start() : element_end(html, section.start(), "section")])
    else:
        main = _MAIN_OPEN.search(html)
        if main is None:
            raise ShapeError("no school list and no main frame to keep")
        parts.append(html[main.start() : element_end(html, main.start(), "div")])
    key = _STATE_KEY.search(html)
    if key is not None:
        _value, end = json.JSONDecoder().raw_decode(html, key.end())
        parts.append(f"<script>{{{html[key.start() : end]}}}</script>")
    sliced = minimal_document(parts)
    parse(sliced)
    return sliced
