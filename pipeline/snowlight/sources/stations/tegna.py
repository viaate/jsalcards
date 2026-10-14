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

``tegna-closings-link``
    A closings page with no closings module whose raw-HTML module holds only a
    link to the list, kept elsewhere on the station's site (every capture of
    KENS' ``/closings`` from January 2022 to September 2023, linking to the
    article it kept its closings in)::

        <div class="raw-html">
            <p><a href="https://www.kens5.com/article/weather/closings/...">For a list
            of closings in our area please click this link.</a></p>
        </div>

    A :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED` listing
    whose ``follows`` names the linked page. Only a link whose words say it leads
    to the list of closings (:data:`_LINK_TEXT`) is one.

``tegna-liferay-page``
    A page of the Liferay template TEGNA's sites had in 2017-2018 (KBMT's
    ``12newsnow.com/closings``, 110 captures from June 2017 to January 2018), whose
    site settings say ``closings:{path:"",type:"None",organizationListPath:"",...}``:
    the site named no closings system, and the page holds no list. A
    :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED` listing that
    names no file (no list can be read from it).

``tegna-subindex-page``
    A ``subindex`` page of the 2019-2020 template (KFMB's ``cbs8.com/closings``,
    ``data-model-closings="true"``, ``"contentType": "subindex"``) whose markup holds
    no closings module, grid, list or frame: what it showed was drawn by its script
    from an address the page does not name. A deferred listing that names no file.

``tegna-closings-article``
    The article such a link leads to, a list typed by hand into the article's
    body (KENS' "FULL LIST: San Antonio and South Texas school closings and
    delays" of 2022-2023, and "School closings due to winter weather in San
    Antonio, Texas" of January 2022), one text section per element::

        <div class="article__body">
          <div class="article__section article__section_type_text utility__text">
            <h2><strong><u>SCHOOL CLOSINGS FOR THURSDAY, FEBRUARY 3, 2022</u></strong></h2></div>
          <div class="article__section ..._type_text ..."><h3>Boerne ISD</h3></div>
          <div class="article__section ..._type_text ..."><p>"Boerne ISD classes are
            canceled and all offices will be closed on Thursday, February 3. ..."</p></div>
          <div class="article__section ..._type_text ..."><p><a href="...">District
            website</a> | <a href="...">Facebook</a> | <a ...>Twitter</a></p></div>
          <div class="article__section article__section_type_ad">...</div> ...

    Each heading followed by a paragraph is a row: the heading is the name and the
    first paragraph after it that is not a line of links alone (the district's
    website and social links) the status; the next such paragraphs before the
    next heading go in ``raw_extra["more"]`` (joined with " | "). A heading
    followed by another heading, and every ``h2``, is the heading of the rows
    after it (``raw_extra["heading"]``). Paragraphs before the first row are the
    article's introduction, not rows. A row whose status is the article's own
    "No report." or "No current report." says the organization reported nothing
    and is not kept (as an empty list leaves it out); an article whose rows all
    say so is the empty state. The article's "Updated:" line ("2:03 PM CST
    February 2, 2022") is every row's ``raw_updated_text`` and, read as UTC, the
    listing's ``list_updated_at``; the listing is ``typed``. Only an article
    whose title says it is a closings page
    (:func:`~snowlight.sources.stations.typed.closings_title`) is read this way;
    one with no row and no "No report." entry raises
    :class:`~snowlight.sources.stations.model.ShapeError`.

A framed list file in one of the vendor formats
:mod:`snowlight.sources.stations.gray_files` reads (KGW's FlashAlert report is
``gray-file-flashalert``) is read with it, under that module's variant names.
Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`
(including the Frankly pages some of these stations had before TEGNA's template,
whose lists a script loaded from an address the page does not name).
"""

import re
from datetime import UTC, datetime, timedelta

from selectolax.parser import Node

from snowlight.sources.stations import gray_files, typed
from snowlight.sources.stations.body import decode
from snowlight.sources.stations.markup import (
    collapse,
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
_LINK_TEXT = re.compile(r"\blist\s+of\s+(?:school\s+)?closings\b", re.IGNORECASE)
"""The words of a raw-HTML module's link that leads to the list kept elsewhere."""
_ARTICLE_BODY = re.compile(r"<div\s+class=\"article__body\"[^>]*>", re.IGNORECASE)
_TITLE = re.compile(r"<title\b[^>]*>.*?</title>", re.IGNORECASE | re.DOTALL)
_UPDATED = re.compile(
    r"<div\s+class=\"article__updated\"\s*>\s*<span\s+class=\"article__meta-label\"\s*>"
    r"\s*Updated:\s*</span>(.*?)</div>",
    re.IGNORECASE | re.DOTALL,
)
_UPDATED_TIME = re.compile(
    r"(\d{1,2}:\d\d\s+[AP]M)\s+(C[SD]T|E[SD]T|M[SD]T|P[SD]T)\s+([A-Z][a-z]+\s+\d{1,2},\s+\d{4})",
    re.IGNORECASE,
)
_ZONE_HOURS = {"EST": 5, "EDT": 4, "CST": 6, "CDT": 5, "MST": 7, "MDT": 6, "PST": 8, "PDT": 7}
"""Hours to add to a US zone's local time for UTC."""
_HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_NO_REPORT = re.compile(r"no\s+(?:current\s+)?report\.?", re.IGNORECASE)
"""An article entry's own words for an organization that reported nothing."""
_LINK_LINE_REST = re.compile(r"[\s|\u2022\u00b7,/-]+")
"""What a line of links holds besides its links: separators and spaces."""


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


def _list_links(html: str) -> list[str]:
    """The pages the raw-HTML modules link to as the list of closings, in order.

    A module counts only when it frames nothing and every link in it says it
    leads to the list (:data:`_LINK_TEXT`).
    """
    found: list[str] = []
    for match in _RAW_HTML.finditer(html):
        block = html[match.start() : element_end(html, match.start(), "div")]
        if iframe_sources(block):
            continue
        anchors = parse_html(block).css("a")
        if anchors and all(_LINK_TEXT.search(node_text(a)) for a in anchors):
            found.extend(a.attributes.get("href") or "" for a in anchors)
    return list(dict.fromkeys(href for href in found if href))


def _link_line(node: Node) -> bool:
    """Whether a paragraph is a line of links alone (its other text only separators)."""
    text = node_text(node)
    for anchor in node.css("a"):
        text = text.replace(node_text(anchor), " ", 1)
    return bool(node.css("a")) and not _LINK_LINE_REST.sub("", text)


def _article_elements(block: Node) -> list[tuple[str, str, bool]]:
    """The article body's text sections' elements in order: (tag, text, a line of links)."""
    found: list[tuple[str, str, bool]] = []
    for section in block.css("div.article__section_type_text"):
        child = section.child
        while child is not None:
            if child.tag[:1] not in {"-", "_"}:
                text = node_text(child)
                if text:
                    found.append((child.tag, text, child.tag == "p" and _link_line(child)))
            child = child.next
    return found


def _updated(html: str) -> tuple[str | None, datetime | None]:
    """The article's "Updated:" line as written, and that time in UTC when it can be read."""
    match = _UPDATED.search(html)
    if match is None:
        return None, None
    written = collapse(match.group(1))
    found = _UPDATED_TIME.fullmatch(written)
    if found is None:
        return written, None
    clock, zone, day = found.group(1), found.group(2).upper(), found.group(3)
    try:
        local = datetime.strptime(f"{clock} {day}", "%I:%M %p %B %d, %Y")
    except ValueError:
        return written, None
    return written, (local + timedelta(hours=_ZONE_HOURS[zone])).replace(tzinfo=UTC)


def parse_article(html: str) -> Listing:
    """Read a ``tegna-closings-article`` page: the closings typed into an article's body.

    Raises:
        ShapeError: the page is not an article whose title names closings, or its
            body holds no entry.
    """
    title = parse_html(html).css_first("title")
    if title is None or not typed.closings_title(node_text(title)):
        raise ShapeError("an article whose title does not say it is a closings page")
    match = _ARTICLE_BODY.search(html)
    if match is None:
        raise ShapeError("no article body")
    block = parse_html(html[match.start() : element_end(html, match.start(), "div")]).css_first(
        "div.article__body"
    )
    if block is None:  # pragma: no cover - the pattern matched this element
        raise ShapeError("no article body")
    elements = [item for item in _article_elements(block) if not item[2]]
    written, updated = _updated(html)
    rows: list[ParsedRow] = []
    entries = 0
    heading: str | None = None
    for number, (tag, text, _links) in enumerate(elements):
        if tag not in _HEADINGS:
            continue
        following = elements[number + 1 :]
        if tag == "h2" or not following or following[0][0] in _HEADINGS:
            heading = text
            continue
        paragraphs = []
        for other_tag, other_text, _ in following:
            if other_tag in _HEADINGS:
                break
            paragraphs.append(other_text)
        entries += 1
        if _NO_REPORT.fullmatch(paragraphs[0]):
            continue
        extra: dict[str, JsonScalar] = {}
        if heading is not None:
            extra["heading"] = heading
        if paragraphs[1:]:
            extra["more"] = " | ".join(paragraphs[1:])
        rows.append(ParsedRow(name=text, status=paragraphs[0], updated_text=written, extra=extra))
    if not entries:
        raise ShapeError("a closings article with no entry")
    return Listing(
        variant="tegna-closings-article",
        state=ListingState.POPULATED if rows else ListingState.EMPTY,
        rows=tuple(rows),
        list_updated_at=updated,
        typed=True,
    )


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
    return _list_elsewhere(text)


def _list_elsewhere(text: str) -> Listing:
    """Read a page whose list is kept elsewhere on the site: the link to it, or the article."""
    links = _list_links(text)
    if links:
        return Listing(
            variant="tegna-closings-link",
            state=ListingState.DEFERRED,
            rows=(),
            follows=tuple(links),
        )
    if _ARTICLE_BODY.search(text):
        return parse_article(text)
    if _LIFERAY_NONE.search(text):
        return Listing(variant=LIFERAY_PAGE, state=ListingState.DEFERRED, rows=())
    if _SUBINDEX.search(text) and _CLOSINGS_MODEL.search(text):
        return Listing(variant=SUBINDEX_PAGE, state=ListingState.DEFERRED, rows=())
    raise ShapeError("not a TEGNA closings body this adapter knows")


LIFERAY_PAGE = "tegna-liferay-page"
"""A Liferay-era page (2017-2018) whose site settings name no closings system."""
SUBINDEX_PAGE = "tegna-subindex-page"
"""A 2019-2020 subindex page that holds no closings module of its own."""
_LIFERAY_NONE = re.compile(
    r"closings:\{path:\"\",type:\"None\",organizationListPath:\"\",url:\"[^\"]*\"\}"
)
_SUBINDEX = re.compile(
    r"&quot;contentType&quot;:\s*&quot;subindex&quot;|\"contentType\":\s*\"subindex\""
)
_CLOSINGS_MODEL = re.compile(r"\bdata-model-closings=\"true\"")


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


def slice_body_v3(body: bytes) -> bytes:
    """``tegna-v3``: :func:`slice_body_v2`, extended to the link and article variants.

    Every body ``tegna-v2`` slices is cut to the same bytes. A closings page that
    links to its list elsewhere (``tegna-closings-link``) keeps each raw-HTML module
    that holds such a link, byte for byte; an article read as
    ``tegna-closings-article`` keeps its ``<title>``, its "Updated:" line and its
    article body, byte for byte. Each is wrapped in a minimal document. (Both kinds of
    page were refused by ``tegna-v2``, so no ``tegna-v2`` slice changes.)
    """
    text = text_of(decode(body))
    if (
        _MODULE.search(text)
        or _GRID.search(text)
        or _LEGACY.search(text)
        or gray_files.is_file(decode(body))
        or _frames(text)
    ):
        return slice_body_v2(body)
    blocks = []
    for match in _RAW_HTML.finditer(text):
        block = text[match.start() : element_end(text, match.start(), "div")]
        if _list_links(block):
            blocks.append(block)
    if blocks:
        return minimal_document(blocks)
    article = _ARTICLE_BODY.search(text)
    title = _TITLE.search(text)
    if article is not None and title is not None:
        updated = _UPDATED.search(text)
        kept = [title.group(0), *([updated.group(0)] if updated is not None else [])]
        kept.append(text[article.start() : element_end(text, article.start(), "div")])
        return minimal_document(kept)
    raise ShapeError("not a TEGNA closings body this adapter knows")
