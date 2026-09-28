"""TEGNA closings pages (``https://www.{site}/closings``).

Every TEGNA station site serves the same page template, rendered on the server.
Variants this adapter reads (the ``variant`` of each listing):

``tegna-closings-module``
    The page's closings module (seen live on 2026-09-26, and in every archived
    capture from late 2020 on)::

        <div data-module="closings" class="closings">
          <div class="closings__sponsor">...</div>
          <a class="closings__weather-link" href="/weather/alerts">View Weather Alerts (15)</a>
          <div class="closings__search">...</div>
          <ul class="closings__list">
            <li class="closings__item">
              <span class="closings__title">MDC All Recreational Facilities</span>
              <span class="closings__body">Closed Sat</span>
            </li> ...
          </ul>
          <p class="closings__no-results">No results found containing "".</p>
        </div>

    ``closings__title`` is the name and ``closings__body`` the status; any other
    ``closings__*`` element of an item goes in ``raw_extra`` under its name. The
    module's own ``<p class="closings__error">No delays or closings.</p>`` with no
    list is the empty state. The page's "All Alerts" box repeats the count
    ("Closures/Delays (1)"); when the page has it, it is the listing's declared
    count (a page whose count differs from its list is read all the same: the box
    and the module may be cached apart). A page that repeats the module (WHAS on
    2021-02-11 held it twice, 149 rows each) is read from the first.

``tegna-closings-grid``
    The same module in the template of 2018 to 2020 (archived captures of WUSA,
    WCSH, WFMY, WHAS, KREM, KING and WVEC), inside a grid cell that carries the
    ``data-module`` attribute::

        <div class="grid__module ..." data-module="closings" ...>
          <div class="grid__module-inner ..."><div class="closings">
            <div class="closings__section-heading">... Closings ...</div>
            <div class="closings__search">...</div> <div class="closings__ad">...</div>
            <div class="closings__heading">DELAYS/CLOSINGS</div>
            <ul class="closings__list closings__list-left">
              <li class="closings__item">
                <p class="closings__title">Berkeley Co Schools</p>
                <p class="closings__body">Closed Today</p>
              </li> ...
            </ul>
            <ul class="closings__list closings__list-right"> ... </ul>

    Items are read as in the module, both columns in page order; the
    ``closings__heading`` in force goes in ``raw_extra["heading"]``. The same
    ``closings__error`` sentence is the empty state. This template has no "All
    Alerts" count.

``tegna-closings-legacy``
    The Closings Alert List of the template TEGNA inherited from Gannett (archived
    captures of 2017 and 2018: KTHV 2017-01-06 with 159 rows, KPNX 2017-01-20,
    KVUE 2018-01-16 and KXTV 2018-01-25 empty)::

        <div class="closings-wrapper mod-wrapper"> ...
          <div class="slides">
            <div id="tab-mod-closings-...-0" class="closings-content slide-all active">
              <div class="closing-container 5353 ">
                <div class="closing-name">ABUNDANT LIFE SCHOOL</div>
                <div class="closing-status">Closed- Cyber Day 1</div>
                <div class="hidden closing-id">5353</div>
              </div> ...
            </div>
            <div id="tab-mod-closings-...-1" class="closings-content slide-a-e hidden"> ...

    The "ALL" tab (``slide-all``) holds every row; the letter tabs (A-E, F-K, ...)
    repeat them and are not read. ``closing-name`` is the name, ``closing-status``
    the status, ``closing-id`` goes in ``raw_extra["id"]`` and any other
    ``closing-*`` child under its name. The tab's
    ``<div class="closings-empty">There are no closings in this category.</div>``
    with no rows is the empty state.

``tegna-frame``
    A closings page with no closings module whose raw-HTML module frames a list
    file (KGW frames ``content.kgw.com/station/flashalert/allclosures.html``): a
    :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED` listing whose
    ``follows`` names the framed file.

A framed list file in one of the vendor formats
:mod:`snowlight.sources.stations.gray_files` reads (KGW's FlashAlert report is
``gray-file-flashalert``) is read with it, under that module's variant names.
Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`
(including the Frankly pages some of these stations had before TEGNA's template,
whose lists a script loaded from an address the page does not name).
"""

import re

from selectolax.parser import Node

from snowlight.sources.stations import gray_files
from snowlight.sources.stations.body import decode
from snowlight.sources.stations.markup import (
    element_end,
    iframe_sources,
    iframe_tags,
    minimal_document,
    node_text,
    parse_html,
    text_of,
)
from snowlight.sources.stations.model import (
    JsonScalar,
    Listing,
    ListingState,
    ParsedRow,
    ShapeError,
)

EMPTY_SENTENCE = "No delays or closings."
LEGACY_EMPTY_SENTENCE = "There are no closings in this category."
_LEGACY = re.compile(r"<div\s+class=\"closings-wrapper\s+mod-wrapper\"\s*>", re.IGNORECASE)
_MODULE = re.compile(r"<div\s+data-module=\"closings\"\s+class=\"closings\"\s*>", re.IGNORECASE)
_GRID = re.compile(
    r"<div\s+class=\"grid__module\b[^\"]*\"[^>]*\sdata-module=\"closings\"[^>]*>", re.IGNORECASE
)
_RAW_HTML = re.compile(r"<div\s+class=\"raw-html\"\s*>", re.IGNORECASE)
_COUNT = re.compile(
    r"<a\s+class=\"all-alerts__link\"\s+href=\"/closings\"[^>]*>\s*Closures/Delays\s*\((\d+)\)\s*</a>",
    re.IGNORECASE,
)
_COUNT_ITEM = re.compile(
    r"<li\s+class=\"all-alerts__item\"\s*>\s*<a\s+class=\"all-alerts__link\"\s+href=\"/closings\""
    r"\s*>\s*Closures/Delays\s*\(\d+\)\s*</a>\s*</li>",
    re.IGNORECASE,
)
_COUNT_ITEM_V2 = re.compile(
    r"<li\s+class=\"all-alerts__item\"\s*>\s*<a\s+class=\"all-alerts__link\"\s+href=\"/closings\""
    r"[^>]*>\s*Closures/Delays\s*\(\d+\)\s*</a>\s*</li>",
    re.IGNORECASE,
)
"""The count item as ``tegna-v2`` keeps it: archived pages add tracking attributes to the link."""
_KNOWN = frozenset({"title", "body", "item"})


def _classes(node: Node) -> list[str]:
    return (node.attributes.get("class") or "").split()


def _item_row(item: Node, heading: str | None) -> ParsedRow | None:
    name = ""
    status: str | None = None
    extra: dict[str, JsonScalar] = {}
    # css("*") is the item itself, then its descendants in document order.
    for node in item.css("*")[1:]:
        for cls in _classes(node):
            if not cls.startswith("closings__"):
                continue
            part = cls.removeprefix("closings__")
            if part == "title":
                name = node_text(node)
            elif part == "body":
                status = node_text(node)
            elif part not in _KNOWN:
                extra[part] = node_text(node)
    if status is None:
        raise ShapeError(f"closing {name!r} has no closings__body status")
    if heading is not None:
        extra["heading"] = heading
    if not name:
        return None
    return ParsedRow(name=name, status=status, extra=extra)


def _read_module(module: Node, variant: str, declared: int | None) -> Listing:
    """Read a ``div.closings`` module: its items in page order under their headings."""
    rows: list[ParsedRow] = []
    skipped = 0
    heading: str | None = None
    # css("*") is the module itself, then its descendants in document order.
    for node in module.css("*")[1:]:
        classes = _classes(node)
        if "closings__heading" in classes:
            heading = node_text(node)
        elif node.tag == "li" and "closings__item" in classes:
            parent = node.parent
            if parent is None or "closings__list" not in _classes(parent):
                raise ShapeError("a closings item outside a closings list")
            row = _item_row(node, heading)
            if row is None:
                skipped += 1
            else:
                rows.append(row)
    error = module.css_first("p.closings__error")
    if rows:
        if error is not None:
            raise ShapeError("the closings module lists rows and says there are none")
        return Listing(
            variant=variant,
            state=ListingState.POPULATED,
            rows=tuple(rows),
            skipped_rows=skipped,
            declared_count=declared,
        )
    if skipped:
        raise ShapeError("every closing in the module is missing its name")
    if error is not None and node_text(error) == EMPTY_SENTENCE:
        return Listing(variant=variant, state=ListingState.EMPTY, rows=(), declared_count=declared)
    raise ShapeError("the closings module has no rows and no no-closings sentence")


def parse_module(html: str) -> Listing:
    """Read the ``tegna-closings-module`` page (the first module when it repeats)."""
    match = _MODULE.search(html)
    if match is None:
        raise ShapeError("no closings module")
    module_html = html[match.start() : element_end(html, match.start(), "div")]
    module = parse_html(module_html).css_first("div.closings")
    if module is None:  # pragma: no cover - the pattern matched this element
        raise ShapeError("no closings module")
    count = _COUNT.search(html)
    declared = int(count.group(1)) if count is not None else None
    return _read_module(module, "tegna-closings-module", declared)


def parse_grid(html: str) -> Listing:
    """Read the ``tegna-closings-grid`` page (the 2018-2020 template)."""
    match = _GRID.search(html)
    if match is None:
        raise ShapeError("no closings grid module")
    cell_html = html[match.start() : element_end(html, match.start(), "div")]
    modules = [
        node for node in parse_html(cell_html).css("div.closings") if _classes(node) == ["closings"]
    ]
    if len(modules) != 1:
        raise ShapeError(f"the closings grid cell holds {len(modules)} closings modules")
    return _read_module(modules[0], "tegna-closings-grid", None)


def _legacy_row(container: Node) -> ParsedRow | None:
    name: str | None = None
    status: str | None = None
    extra: dict[str, JsonScalar] = {}
    for node in container.css("*")[1:]:
        for cls in _classes(node):
            if not cls.startswith("closing-"):
                continue
            part = cls.removeprefix("closing-")
            if part == "name":
                name = node_text(node)
            elif part == "status":
                status = node_text(node)
            else:
                extra[part] = node_text(node)
    if name is None or status is None:
        raise ShapeError("a legacy closing without its closing-name and closing-status")
    if not name:
        return None
    return ParsedRow(name=name, status=status, extra=extra)


def parse_legacy(html: str) -> Listing:
    """Read the ``tegna-closings-legacy`` page (the Gannett-era Closings Alert List)."""
    match = _LEGACY.search(html)
    if match is None:
        raise ShapeError("no legacy closings list")
    wrapper_html = html[match.start() : element_end(html, match.start(), "div")]
    tabs = [
        node
        for node in parse_html(wrapper_html).css("div.closings-content")
        if "slide-all" in _classes(node)
    ]
    if len(tabs) != 1:
        raise ShapeError(f"the legacy closings list has {len(tabs)} ALL tabs")
    rows: list[ParsedRow] = []
    skipped = 0
    for container in tabs[0].css("div.closing-container"):
        row = _legacy_row(container)
        if row is None:
            skipped += 1
        else:
            rows.append(row)
    empty = tabs[0].css_first("div.closings-empty")
    if rows:
        if empty is not None:
            raise ShapeError("the legacy ALL tab lists rows and says there are none")
        return Listing(
            variant="tegna-closings-legacy",
            state=ListingState.POPULATED,
            rows=tuple(rows),
            skipped_rows=skipped,
        )
    if skipped:
        raise ShapeError("every closing in the legacy ALL tab is missing its name")
    if empty is not None and node_text(empty) == LEGACY_EMPTY_SENTENCE:
        return Listing(variant="tegna-closings-legacy", state=ListingState.EMPTY, rows=())
    raise ShapeError("the legacy ALL tab has no rows and no no-closings sentence")


def _frames(html: str) -> list[str]:
    """The files framed by the page's raw-HTML modules, in order."""
    found: list[str] = []
    for match in _RAW_HTML.finditer(html):
        block = html[match.start() : element_end(html, match.start(), "div")]
        found.extend(src for src in iframe_sources(block) if src)
    return list(dict.fromkeys(found))


def parse(body: bytes) -> Listing:
    """Read one TEGNA closings body, live or archived, in whichever known variant it is."""
    raw = decode(body)
    text = text_of(raw)
    if _MODULE.search(text):
        return parse_module(text)
    if _GRID.search(text):
        return parse_grid(text)
    if _LEGACY.search(text):
        return parse_legacy(text)
    if gray_files.is_file(raw):
        return gray_files.parse(raw)
    frames = _frames(text)
    if frames:
        return Listing(
            variant="tegna-frame", state=ListingState.DEFERRED, rows=(), follows=tuple(frames)
        )
    raise ShapeError("not a TEGNA closings body this adapter knows")


def _slice_frames(text: str) -> bytes:
    blocks = []
    for found in _RAW_HTML.finditer(text):
        block = text[found.start() : element_end(text, found.start(), "div")]
        tags = iframe_tags(block)
        if tags:
            blocks.append('<div class="raw-html">' + "".join(tags) + "</div>")
    return minimal_document(blocks)


def slice_body(body: bytes) -> bytes:
    """Cut a TEGNA body down to what :func:`parse` reads (for test fixtures): ``tegna-v1``.

    A page with the closings module keeps the module, byte for byte, and the "All
    Alerts" item that gives its count; a page that frames its list keeps each
    raw-HTML module's frame tags. Each is wrapped in a minimal document. A list
    file is small and kept whole (decoded). (Pages in the 2018-2020 grid template
    are cut by :func:`slice_body_v2`.)
    """
    raw = decode(body)
    text = text_of(raw)
    match = _MODULE.search(text)
    if match is not None:
        kept = [text[match.start() : element_end(text, match.start(), "div")]]
        item = _COUNT_ITEM.search(text)
        if item is not None:
            kept.append(item.group(0))
        return minimal_document(kept)
    if gray_files.is_file(raw):
        return raw
    if _frames(text):
        return _slice_frames(text)
    raise ShapeError("not a TEGNA closings body this adapter knows")


def slice_body_v2(body: bytes) -> bytes:
    """``tegna-v2``: :func:`slice_body`, extended to archived pages.

    Every body ``tegna-v1`` slices is cut to the same bytes, except that the "All
    Alerts" count item is also kept when its link carries further attributes (as
    archived pages' links do). A page in the 2018-2020 grid template (no module
    of the later kind) keeps the grid cell that holds its closings module, byte
    for byte, in a minimal document; a page with the Gannett-era Closings Alert List
    (neither) keeps that list's wrapper, byte for byte, the same way. (Both kinds
    of page were refused by ``tegna-v1``, so no ``tegna-v1`` slice changes.)
    """
    text = text_of(decode(body))
    match = _MODULE.search(text)
    if match is not None:
        kept = [text[match.start() : element_end(text, match.start(), "div")]]
        item = _COUNT_ITEM_V2.search(text)
        if item is not None:
            kept.append(item.group(0))
        return minimal_document(kept)
    grid = _GRID.search(text)
    if grid is not None:
        return minimal_document([text[grid.start() : element_end(text, grid.start(), "div")]])
    legacy = _LEGACY.search(text)
    if legacy is not None:
        return minimal_document([text[legacy.start() : element_end(text, legacy.start(), "div")]])
    return slice_body(body)
