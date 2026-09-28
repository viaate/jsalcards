"""E.W. Scripps closings pages (``https://www.{site}/weather/school-closings-delays``).

The Scripps station sites serve one page template, rendered on the server.
Variants this adapter reads (the ``variant`` of each listing):

``scripps-closings-module``
    The page's closings module on the Brightspot sites (seen live on 2026-09-26,
    and in archived captures from 2019 on)::

        <article class="module module--closings js-filter">
          <div class="inner">
            <header class="header--light">... search box, filter buttons ...</header>
            <div class="blocks js-filter__targets">
              <div class="js-num"></div> <div class="js-a-f cls"></div> ...
              <article class="closing js-block">
                <p class="text--primary js-sort-value">Poquoson Public Schools</p>
                <p class="text--secondary">Virtual Learning</p>
                <p class="text--secondary">2026-09-27T03:59:59.999999Z</p>
              </article> ...

    In each ``article.closing`` the ``text--primary`` element is the name and the
    first ``text--secondary`` paragraph the status. Where the name element breaks
    into lines (``<br>``), the first line is the name and the next ones go in
    ``raw_extra`` as ``second_line`` (``line3``, ...): WEWS and WXMI print the row's
    county there, "Ashland County" beside the JSON rendering's ``"county":
    "Ashland"`` (and "null County" where the county is missing). The second ``text--secondary``
    paragraph is a time the page does not label; the page's own JSON rendering of
    the same module (``?_renderer=json``, below) gives it as the row's
    ``expiration``, so it is kept in ``raw_extra["expiration"]`` and
    ``raw_updated_text`` is left empty. Further ``text--secondary`` paragraphs go in
    ``raw_extra`` by position (``text3``, ``text4``, ...), and the filter group a
    row sits in (``js-a-f`` and the like), if any, as ``group``. The module's own
    sentence "There are currently no active closings or delays." with no rows is
    the empty state. A page that also types list items or table rows into a
    rich-text module (``div.RichTextModule``) beside the closings module is an
    error, never the module's list alone. No Scripps page has been seen doing that:
    the rich-text modules beside the closings module on the 103 pages read (archived
    and live) hold notes for organizations written as paragraphs (WCPO's "*Leave a
    message on our hotline ...", KMTV's "Contact the Newsroom" and the line after
    it), so paragraphs there are not taken for entries.

``scripps-closings-liferay``
    The same module on the Liferay sites of 2018 (archived captures of KSHB, WKBW,
    WEWS and WTVF from November 2018): the module ``<article>`` carries a numeric
    ``id`` and the classes ``show-desktop show-tablet show-phone``, and a row's name
    is an ``<h1 class="text--primary">``. Read as above, except that the second
    ``text--secondary`` paragraph is the row's comment (the ``setStoryComments`` of
    the ``ClosingsData`` comment the page prints before the module: "No evening
    service" beside "Dismissing Early at 10:15 AM"), kept as
    ``raw_extra["comments"]``. The same sentence is the empty state.

``scripps-closings-json``
    The page as Brightspot renders it to JSON (``?_renderer=json``, archived from
    2020 on): a module whose ``_styledTemplate`` is ``/thirdParty/Closings.hbs``
    holds ``data.resultsArray``, one object per row (``name``, ``status``,
    ``expiration``, ``state``, and at some stations ``county``), and names the
    service it was filled from in ``data.singleValues[].datasource``
    (``https://api.ewscloud.com/prod/closings/v1/{site}/active-closings``, which
    answers 401 without a key: checked 2026-09-27). ``name`` is the name and
    ``status`` the status; every other field goes in ``raw_extra``. An empty
    ``resultsArray`` is the empty state (the HTML page then shows the sentence
    above). A page holding two such modules that differ is an error.

``scripps-frame``
    A closings page with no closings module that frames a list file (WTVQ's
    WordPress page frames ``/content/uploads/weather-images/SnoWatch.html``): a
    :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED` listing whose
    ``follows`` names the framed file. Only frames of files whose name says they
    are closings files are followed (``SnoWatch``, ``closings``); other frames
    (video, advertising) are ignored.

``scripps-typed-page`` (the ``scripps-typed`` platform only)
    A Brightspot closings page typed by hand (KSTU's ``/weather/closings``, the
    Montana stations' ``/weather/closings``): no closings module, a
    ``<h1 class="Page-pageHeading">`` that says it is a closings page ("School
    Closings & Delays", "Closings") and a ``div.left-column`` holding the typed
    text in ``RichTextModule`` blocks::

        <div class="left-column"><div class="RichTextModule">
          <div class="RichTextModule-items"><ul><li><b>Provo City School District</b>
            will operate on a Two Hour Late Start schedule on Tuesday. ...

    These are read only by :func:`parse_typed`, the ``parse`` of the
    ``scripps-typed`` adapter (:mod:`snowlight.sources.stations.scripps_typed`), for
    the stations the registry files under that platform; :func:`parse` never reads
    them. The column is read by :func:`snowlight.sources.stations.typed.read_typed`
    (its rows are the column's list items or paragraph entries, whatever words they
    use; with none, the page must say it holds none, "There are currently no school
    closings"). A ``RichTextModule`` with nothing in it (the typed list cleared,
    KSTU's page on 2023-02-20) is the empty state; a left column with nothing in it
    at all, not even the module (the Montana pages), is an error: nothing on the
    page says it is an empty list. These pages state no time for their text, so the
    live reader keeps their rows only when the text itself names a day near the read
    (KSTU's day headings, "WEDNESDAY, FEB. 22"; see
    :func:`snowlight.sources.stations.typed.names_day_near`).

A framed list file in one of the vendor formats
:mod:`snowlight.sources.stations.gray_files` reads (WTVQ's SnoWatch file is
``gray-file-grid``) is read with it, under that module's variant names.
Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`.
"""

import json
import re
from collections.abc import Iterator, Mapping, Sequence
from html import unescape
from urllib.parse import urlsplit

from selectolax.parser import Node

from snowlight.sources.stations import gray_files, typed
from snowlight.sources.stations.body import decode
from snowlight.sources.stations.markup import (
    collapse,
    element_end,
    flat,
    iframe_sources,
    iframe_tags,
    json_value,
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

EMPTY_SENTENCE = "There are currently no active closings or delays."
CLOSINGS_TEMPLATE = "/thirdParty/Closings.hbs"
_MODULE_V1 = re.compile(
    r"<article\s+class=\"module module--closings(?:\s[^\"]*)?\"\s*>", re.IGNORECASE
)
_MODULE = re.compile(
    r"<article\b(?P<attrs>[^>]*?)\sclass=\"module module--closings(?:\s[^\"]*)?\"[^>]*>",
    re.IGNORECASE,
)
_LIFERAY_ID = re.compile(r"\sid=\"[0-9]+\"")
_FRAME_FILE = re.compile(r"(snowatch|closings)", re.IGNORECASE)
_GROUP = re.compile(r"^js-(?:num|[a-z]-[a-z])$")
_ROW_KEYS = frozenset({"name", "status"})
_HEADING = re.compile(r"<h1\s+class=\"Page-pageHeading\"\s*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_LEFT_COLUMN = re.compile(r"<div\s+class=\"left-column\"\s*>", re.IGNORECASE)


def _is_list_frame(src: str) -> bool:
    return _FRAME_FILE.search(urlsplit(src).path) is not None


def _lines(node: Node) -> list[str]:
    """Return a node's text split where it has ``<br>`` elements, each line collapsed."""
    lines = [""]
    for child in node.iter(include_text=True):
        if child.tag == "br":
            lines.append("")
        else:
            lines[-1] += child.text(deep=True)
    return [collapse(line) for line in lines]


def _row(block: Node, second: str) -> ParsedRow | None:
    primary = block.css_first(".text--primary")
    secondary = block.css("p.text--secondary")
    if primary is None or not secondary:
        raise ShapeError("a closing without its name and status paragraphs")
    name, *more = [line for line in _lines(primary) if line] or [""]
    status = node_text(secondary[0])
    extra: dict[str, JsonScalar] = {}
    for position, line in enumerate(more, start=2):
        extra["second_line" if position == 2 else f"line{position}"] = line  # noqa: PLR2004
    for position, paragraph in enumerate(secondary[1:], start=2):
        extra[second if position == 2 else f"text{position}"] = node_text(paragraph)  # noqa: PLR2004
    parent = block.parent
    classes = (parent.attributes.get("class") or "").split() if parent is not None else []
    groups = [cls for cls in classes if _GROUP.match(cls)]
    if groups:
        extra["group"] = groups[0]
    if not name:
        return None
    return ParsedRow(name=name, status=status, extra=extra)


def parse_module(html: str) -> Listing:
    """Read the ``scripps-closings-module`` (or 2018 ``scripps-closings-liferay``) page."""
    match = _MODULE.search(html)
    if match is None:
        raise ShapeError("no closings module")
    liferay = _LIFERAY_ID.search(match.group("attrs") or "") is not None
    variant = "scripps-closings-liferay" if liferay else "scripps-closings-module"
    module_html = html[match.start() : element_end(html, match.start(), "article")]
    module = parse_html(module_html).css_first("article.module--closings")
    if module is None:  # pragma: no cover - the pattern matched this element
        raise ShapeError("no closings module")
    rows: list[ParsedRow] = []
    skipped = 0
    for block in module.css("article.closing"):
        row = _row(block, "comments" if liferay else "expiration")
        if row is None:
            skipped += 1
        else:
            rows.append(row)
    if rows:
        return Listing(
            variant=variant, state=ListingState.POPULATED, rows=tuple(rows), skipped_rows=skipped
        )
    if skipped:
        raise ShapeError("every closing in the module is missing its name")
    inner = module.css_first("div.inner")
    header = inner.css_first("header") if inner is not None else None
    said = node_text(inner)
    if header is not None:
        said = said.removeprefix(node_text(header)).strip()
    if said == EMPTY_SENTENCE:
        return Listing(variant=variant, state=ListingState.EMPTY, rows=())
    raise ShapeError(f"the closings module has no rows and no empty sentence: {said[:80]!r}")


# The JSON rendering ------------------------------------------------------------------------


def _closings_modules(value: object) -> Iterator[Mapping[str, object]]:
    """Yield every object in ``value`` whose ``_styledTemplate`` is the closings template."""
    if isinstance(value, Mapping):
        if value.get("_styledTemplate") == CLOSINGS_TEMPLATE:
            yield value
        for item in value.values():
            yield from _closings_modules(item)
    elif isinstance(value, list):
        for item in value:
            yield from _closings_modules(item)


def _results(module: Mapping[str, object]) -> Sequence[object]:
    data = module.get("data")
    results = data.get("resultsArray") if isinstance(data, Mapping) else None
    if not isinstance(results, list):
        raise ShapeError("the closings module has no data.resultsArray list")
    return results


def parse_json(data: object) -> Listing:
    """Read the ``scripps-closings-json`` rendering (see the module docstring)."""
    modules = list(_closings_modules(data))
    if not modules:
        raise ShapeError("the JSON rendering holds no closings module")
    results = [_results(module) for module in modules]
    if any(other != results[0] for other in results[1:]):
        raise ShapeError("the JSON rendering holds two closings modules that differ")
    rows: list[ParsedRow] = []
    skipped = 0
    for item in results[0]:
        if not isinstance(item, Mapping) or not set(item) >= _ROW_KEYS:
            raise ShapeError("a resultsArray item is not a closing object")
        name, status = item["name"], item["status"]
        if not isinstance(name, str) or not isinstance(status, str):
            raise ShapeError("a resultsArray item's name or status is not text")
        if not collapse(name):
            skipped += 1
            continue
        extra = {str(k): flat(v) for k, v in item.items() if k not in _ROW_KEYS}
        rows.append(ParsedRow(name=collapse(name), status=collapse(status), extra=extra))
    if skipped and not rows:
        raise ShapeError("every row of the closings module is missing its name")
    return Listing(
        variant="scripps-closings-json",
        state=ListingState.POPULATED if rows else ListingState.EMPTY,
        rows=tuple(rows),
        skipped_rows=skipped,
    )


# Closings typed by hand ------------------------------------------------------------------


def _typed_parts(html: str) -> tuple[str, str] | None:
    """A typed closings page's heading element and left column, byte for byte, or None."""
    heading = _HEADING.search(html)
    title = collapse(unescape(re.sub(r"<[^>]+>", " ", heading.group(1)))) if heading else ""
    if heading is None or not typed.closings_title(title):
        return None
    column = _LEFT_COLUMN.search(html)
    if column is None:
        return None
    block = html[column.start() : element_end(html, column.start(), "div")]
    # A column that frames another site's page (KERO's frames Kern County's AlertLine) holds
    # its list in the frame, not typed on the page.
    return None if iframe_sources(block) else (heading.group(0), block)


def parse_typed_page(html: str) -> Listing:
    """Read a Brightspot closings page typed by hand (``scripps-typed-page``).

    Raises:
        ShapeError: the page has no typed left column; the column is empty with no
            rich-text module in it; or its text holds no row and does not say it holds
            none.
    """
    parts = _typed_parts(html)
    if parts is None:
        raise ShapeError("no closings page typed by hand (no left column under a closings heading)")
    column = parse_html(parts[1]).css_first("div.left-column")
    if column is None:  # pragma: no cover - the pattern matched this element
        raise ShapeError("no closings page typed by hand")
    modified = typed.html_modified(html)
    if not node_text(column):
        if column.css_first("div.RichTextModule") is not None:
            # The rich-text module the station types its closings into, cleared.
            return typed.empty_typed("scripps-typed-page", modified)
        raise ShapeError(
            "a closings page with nothing on it: an empty left column, no closings module "
            "and no rich-text module"
        )
    return typed.read_typed(column, "scripps-typed-page", modified)


def _items_beside_module(html: str) -> tuple[ParsedRow, ...]:
    """The list items and table rows typed in the page's rich-text modules (``RichTextModule``)
    outside its closings module (:func:`snowlight.sources.stations.typed.entries_beside`,
    list items and table rows only)."""
    tree = parse_html(html)
    for module in tree.css("article.module--closings"):
        module.decompose()
    found: list[ParsedRow] = []
    for block in tree.css("div.RichTextModule"):
        found.extend(typed.entries_beside(block, paragraphs=False))
    return tuple(found)


# Dispatch ----------------------------------------------------------------------------------


def parse(body: bytes) -> Listing:
    """Read one Scripps closings body, live or archived, in whichever known variant it is."""
    raw = decode(body)
    text = text_of(raw)
    if text.lstrip().startswith("{"):
        return parse_json(json_value(text.lstrip()))
    if _MODULE.search(text):
        listing = parse_module(text)
        beside = _items_beside_module(text)
        if beside:
            names = "; ".join(row.name for row in beside[:3])
            raise ShapeError(
                f"the page lists {len(beside)} items typed in a rich-text module beside its "
                f"closings module ({names}), which this adapter does not read as the list"
            )
        return listing
    if gray_files.is_file(raw):
        return gray_files.parse(raw)
    frames = [src for src in iframe_sources(text) if _is_list_frame(src)]
    if frames:
        return Listing(
            variant="scripps-frame",
            state=ListingState.DEFERRED,
            rows=(),
            follows=tuple(dict.fromkeys(frames)),
        )
    raise ShapeError("not a Scripps closings body this adapter knows")


def parse_typed(body: bytes) -> Listing:
    """Read one closings body of a station the registry files as typing its closings by hand.

    Every variant :func:`parse` reads is read the same way. A body it refuses is read
    as a Brightspot closings page typed by hand (``scripps-typed-page``) when it is
    one: an HTML page with no closings module, list file or list frame, whose
    ``Page-pageHeading`` says it is a closings page. This is the ``parse`` of the
    ``scripps-typed`` adapter (:mod:`snowlight.sources.stations.scripps_typed`);
    :func:`parse`, every other Scripps station's, never reads a typed page, so a
    missing, blank or script-filled module there is an error.

    Raises:
        ShapeError: :func:`parse` refuses the body and it is no typed closings page, or
            the typed page holds no row and does not say it holds none.
    """
    try:
        return parse(body)
    except ShapeError:
        raw = decode(body)
        text = text_of(raw)
        known = (
            text.lstrip().startswith("{")
            or _MODULE.search(text) is not None
            or gray_files.is_file(raw)
            or _typed_parts(text) is None
        )
        if known:
            raise
        return parse_typed_page(text)


def slice_body(body: bytes) -> bytes:
    """Cut a Scripps body down to what :func:`parse` reads (for test fixtures): ``scripps-v1``.

    A page with the closings module keeps the module, byte for byte; a page that
    frames its list keeps the frame tags of closings files. Each is wrapped in a
    minimal document. A list file is small and kept whole (decoded). (The 2018
    Liferay pages and the JSON rendering are cut by :func:`slice_body_v2`.)
    """
    raw = decode(body)
    text = text_of(raw)
    match = _MODULE_V1.search(text)
    if match is not None:
        return minimal_document([text[match.start() : element_end(text, match.start(), "article")]])
    if gray_files.is_file(raw):
        return raw
    tags = [tag for tag in iframe_tags(text) if any(map(_is_list_frame, iframe_sources(tag)))]
    if tags:
        return minimal_document(tags)
    raise ShapeError("not a Scripps closings body this adapter knows")


def slice_body_v2(body: bytes) -> bytes:
    """``scripps-v2``: :func:`slice_body`, extended to the Liferay pages and the JSON rendering.

    Every body ``scripps-v1`` slices is cut to the same bytes. A 2018 Liferay page
    keeps its closings module (whose opening tag carries attributes ``v1`` does
    not match), byte for byte, in a minimal document. The JSON rendering keeps
    only its closings module objects, as ``{"closings": [module, ...]}`` in
    compact JSON with sorted keys.
    """
    text = text_of(decode(body))
    head = text.lstrip()
    if head.startswith("{"):
        modules = list(_closings_modules(json_value(head)))
        if not modules:
            raise ShapeError("the JSON rendering holds no closings module")
        cut = {"closings": modules}
        return json.dumps(cut, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    if _MODULE_V1.search(text) is None:
        match = _MODULE.search(text)
        if match is not None:
            end = element_end(text, match.start(), "article")
            return minimal_document([text[match.start() : end]])
    return slice_body(body)


def slice_body_v3(body: bytes) -> bytes:
    """``scripps-v3``: :func:`slice_body_v2`, extended to closings typed by hand.

    Every body ``scripps-v2`` cuts is cut to the same bytes. A Brightspot closings
    page typed by hand (``scripps-typed-page``, which ``v2`` refused) keeps its
    ``Page-pageHeading`` heading, the tag that gives its time, if any (see
    :func:`~snowlight.sources.stations.typed.time_tags`), and its left column,
    byte for byte, in a minimal document.
    """
    try:
        return slice_body_v2(body)
    except ShapeError:
        text = text_of(decode(body))
        parts = _typed_parts(text)
        if parts is None:
            raise
        return minimal_document([parts[0], *typed.time_tags(text), parts[1]])
