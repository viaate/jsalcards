"""NBC Owned Television Stations' school closings (``https://www.{site}/weather/school-closings/``).

The NBC-owned station sites run one WordPress platform. Ten of the eleven
stations serve their list both on the page, rendered on the server, and at a
public WordPress REST route, ``/wp-json/nbc/v1/school-closings`` (both seen live on
2026-09-26 and 2026-09-27; NBC Chicago's page redirects to the Emergency Closing
Center instead, read by :mod:`snowlight.sources.stations.ecc`). Variants:

``nbc-wp-json``
    The REST route, polled live: a JSON array of objects::

        [{"category": "DUTCHESS", "datetime": "", "organization": "Bristol Community College",
          "status": "Closed Saturday", "state": "ma"}, ...]

    ``organization`` is the name and ``status`` the status; ``datetime`` (when not
    empty) is the row's ``raw_updated_text``; every other field goes in
    ``raw_extra`` under its own name. ``[]`` is the empty state. An item without an
    ``organization`` is counted as a nameless row; an array whose items are not
    objects with text fields is an error.

``nbc-wp-page``
    The page's closings block (``div.article-content--wrap.closings``), on the
    WordPress platform (live, and archived from December 2019)::

        <div class="closings--active">
          <div class="closings__updated"> Update 09/26/2026 08:11:32 PM EDT </div>
          <div class="closings__listings">
            <h3 class="listings-heading">B</h3>
            <div class="listing">
              <h4 class="listing__org">Bristol Community College</h4>
              <p class="listing__notice">Closed Saturday</p>
            </div> ...

    ``listing__org`` is the name and ``listing__notice`` the status; the
    "Update ..." text (without the word "Update") is every row's
    ``raw_updated_text`` (``raw_extra["updated_scope"]`` is ``"page"``). A site
    covering several states (NBC Boston) wraps the list in tabs
    (``div.closings__tabs``: an "All" pane, whose names carry the state in
    parentheses, and one pane per state): the rows are read from the state panes,
    each row's state (the pane's tab label) going in ``raw_extra["state"]``, and
    they must be as many as the "All" pane's. ``div.closings--inactive`` with
    "Forecast: School's Open." is the empty state; so is an active block whose only
    listing has neither a name nor a notice (NBC Miami's, 2026-09-27), counted as
    one nameless row.

``nbc-legacy-page``
    The page before the WordPress platform (archived captures from January 2017
    to November 2019 at NBC Boston, Connecticut, New York, Philadelphia,
    Washington and San Diego; with rows at NBC Connecticut, 159 on 8 February
    2017, NBC Philadelphia and NBC Boston)::

        <div id="closingTop"> ... <h1>School Closings</h1>
          <div id="schoolForecast"> ... </div></div>
        <div id="listing">
          <div class="update_anchor"> Last Update 02/20/19 03:12:30 PM EST</div>
          <span class="closing_anchor"><a name="A" id="A">A</a></span>
          <p class="closing_item">ABC Learning Station<br/><span>Closed </span></p> ...
        </div>

    Each ``p.closing_item`` is a row: the text before its ``<br>`` is the name
    and its ``<span>`` the status; the "Last Update ..." text (without the words
    "Last Update") is every row's ``raw_updated_text``. The alerts bar's
    school-closings count (``div.severeWeatherAlertCount`` linking to the closings
    page), when the page shows one, is the listing's ``declared_count`` (47 for 47
    items at NBC Philadelphia on 20 February 2019). With nothing listed there is no
    ``div#listing`` and the forecast block's heading is "Forecast: School's Open."
    (NBC Washington: "Forecast: Schools are open."): the empty state. An item
    holding anything but its name, a ``<br>`` and a ``<span>``, or a listing with no
    named item, is an error.

Archived captures (archive-captures runs 36311251817, 36323195832 and 36330775706)
show the WordPress page with rows at NBC New York, Philadelphia, Washington, Boston,
Connecticut and Dallas-Fort Worth from 2020 to 2026 (up to 853 listings, NBC
Connecticut on 13 February 2024), and the REST route with rows at NBC New York (6
items on 22 February 2026, 27 on 13 March 2020), NBC Philadelphia (22 on 16 March
2020) and NBC Connecticut (430 on 23 February 2026). Every capture of the NBC Los
Angeles, San Diego, Bay Area and Miami pages and routes read (2016 to 2026) was
empty, on closure days too: Los Angeles on all 26 captures of the January 2025
fire closures and the November 2024 Mountain fire, the Bay Area during the October
2017 North Bay fires, Miami on all 11 captures of hurricane days (Eta 2020, Ian and
Nicole 2022, Idalia 2023, Milton and Rafael 2024) (runs 36345276947 and
36348669505).

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`.
"""

import re
from collections.abc import Mapping, Sequence

from selectolax.parser import Node

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
    flat,
    json_value,
    minimal_document,
    node_text,
    parse_html,
    text_of,
)

INACTIVE_HEADING = "Forecast: School's Open."
LEGACY_OPEN_HEADINGS = frozenset({INACTIVE_HEADING, "Forecast: Schools are open."})
"""The headings the pre-2020 page shows when nothing is listed (NBC Washington's is the second)."""
_BLOCK_OPEN = re.compile(
    r"<div\b[^>]*\bclass=\"article-content--wrap closings\"[^>]*>", re.IGNORECASE
)
_UPDATED = re.compile(r"^Update\s+(.*)$")
_LEGACY_UPDATED = re.compile(r"^Last Update\s+(.*)$")
_LEGACY_OPEN = re.compile(r"<div\b[^>]*\bid=\"(closingTop|listing)\"[^>]*>", re.IGNORECASE)
_LEGACY_COUNT_OPEN = re.compile(
    r"<div\b[^>]*\bclass=\"severeWeatherAlertCount\"[^>]*>", re.IGNORECASE
)
_JSON_FIELDS = ("organization", "status", "datetime")


def _json_row(item: object) -> ParsedRow | None:
    if not isinstance(item, Mapping):
        raise ShapeError("a school-closings item is not an object")
    for field in _JSON_FIELDS:
        value = item.get(field)
        if value is not None and not isinstance(value, str):
            raise ShapeError(f"a school-closings item's {field} is not text")
    name = " ".join(str(item.get("organization") or "").split())
    if not name:
        return None
    updated = " ".join(str(item.get("datetime") or "").split()) or None
    extra: dict[str, JsonScalar] = {
        str(key): flat(value) for key, value in item.items() if key not in _JSON_FIELDS
    }
    status = " ".join(str(item.get("status") or "").split())
    return ParsedRow(name=name, status=status, updated_text=updated, extra=extra)


def parse_json(data: object) -> Listing:
    """Read the ``/wp-json/nbc/v1/school-closings`` array (``nbc-wp-json``)."""
    if not isinstance(data, list):
        raise ShapeError("the school-closings route did not answer with an array")
    rows: list[ParsedRow] = []
    skipped = 0
    for item in data:
        row = _json_row(item)
        if row is None:
            skipped += 1
        else:
            rows.append(row)
    return Listing(
        variant="nbc-wp-json",
        state=ListingState.POPULATED if rows else ListingState.EMPTY,
        rows=tuple(rows),
        skipped_rows=skipped,
    )


def _listings(pane: Node, state: str | None, updated: str | None) -> tuple[list[ParsedRow], int]:
    rows: list[ParsedRow] = []
    skipped = 0
    for listing in pane.css("div.listing"):
        name = node_text(listing.css_first("h4.listing__org"))
        notice = node_text(listing.css_first("p.listing__notice"))
        if not name:
            skipped += 1
            continue
        extra: dict[str, JsonScalar] = {"updated_scope": "page"} if updated else {}
        if state is not None:
            extra["state"] = state
        rows.append(ParsedRow(name=name, status=notice, updated_text=updated, extra=extra))
    return rows, skipped


def _tabbed(tabs: Node, updated: str | None) -> tuple[list[ParsedRow], int]:
    labels = {}
    for link in tabs.css("ul.tabs__nav a"):
        href = link.attributes.get("href") or ""
        if href.startswith("#"):
            labels[href[1:]] = node_text(link)
    panes = tabs.css("div.tab-pane")
    if not panes or "all" not in labels:
        raise ShapeError("the closings tabs have no 'All' pane")
    rows: list[ParsedRow] = []
    skipped = 0
    everything: Sequence[ParsedRow] = ()
    for pane in panes:
        pane_id = pane.attributes.get("id") or ""
        if pane_id not in labels:
            raise ShapeError(f"a closings pane {pane_id!r} has no tab")
        found, nameless = _listings(pane, None if pane_id == "all" else labels[pane_id], updated)
        if pane_id == "all":
            everything = found
            continue
        rows.extend(found)
        skipped += nameless
    if len(everything) != len(rows):
        raise ShapeError("the state panes do not hold the 'All' pane's rows")
    return rows, skipped


def _page(block: Node) -> Listing:
    inactive = block.css_first("div.closings--inactive")
    active = block.css_first("div.closings--active")
    tabs = block.css_first("div.closings__tabs")
    if inactive is not None and active is None and tabs is None:
        if node_text(inactive.css_first("h3.closings__heading")) != INACTIVE_HEADING:
            raise ShapeError("an inactive closings block without the 'School's Open' heading")
        return Listing(variant="nbc-wp-page", state=ListingState.EMPTY, rows=())
    container = tabs or active
    if container is None or inactive is not None:
        raise ShapeError("a closings block that is neither active nor inactive")
    stamp = _UPDATED.match(node_text(block.css_first("div.closings__updated")))
    updated = stamp.group(1).strip() if stamp else None
    if tabs is not None:
        rows, skipped = _tabbed(tabs, updated)
    else:
        if not active or not active.css("div.closings__listings"):
            raise ShapeError("an active closings block with no listings")
        rows, skipped = _listings(active, None, updated)
    return Listing(
        variant="nbc-wp-page",
        state=ListingState.POPULATED if rows else ListingState.EMPTY,
        rows=tuple(rows),
        skipped_rows=skipped,
    )


def _legacy_item(item: Node) -> tuple[str, str]:
    """Return a pre-2020 ``p.closing_item``'s name (the text before its ``<br>``) and status."""
    name: list[str] = []
    status = ""
    after_break = False
    for child in item.iter(include_text=True):
        if child.tag == "-text":
            if not after_break:
                name.append(child.text(deep=False))
            elif (child.text(deep=False) or "").strip():
                raise ShapeError("a closing item has text after its status")
        elif child.tag == "br" and not after_break:
            after_break = True
        elif child.tag == "span" and after_break and not status:
            status = node_text(child)
        else:
            raise ShapeError(f"a closing item holds an unexpected <{child.tag}>")
    return " ".join("".join(name).split()), status


def _legacy_count(tree: Node) -> int | None:
    """The school-closings count in the page's alerts bar, when it shows one."""
    for block in tree.css("div.severeWeatherAlertCount"):
        link = block.css_first("a")
        href = (link.attributes.get("href") or "") if link is not None else ""
        text = node_text(link)
        if "school-closings" in href and text.isdigit():
            return int(text)
    return None


def _legacy_page(tree: Node) -> Listing | None:
    """Read the pre-2020 page (``nbc-legacy-page``), or None when the body is not one."""
    top = tree.css_first("div#closingTop")
    if top is None:
        return None
    block = tree.css_first("div#listing")
    if block is None:
        heading = node_text(top.css_first("div#schoolForecast h3"))
        if heading not in LEGACY_OPEN_HEADINGS:
            raise ShapeError("a closings page with neither a listing nor the 'School's Open' line")
        return Listing(variant="nbc-legacy-page", state=ListingState.EMPTY, rows=())
    stamp = _LEGACY_UPDATED.match(node_text(block.css_first("div.update_anchor")))
    updated = stamp.group(1).strip() if stamp else None
    rows: list[ParsedRow] = []
    skipped = 0
    for item in block.css("p.closing_item"):
        name, status = _legacy_item(item)
        if not name:
            skipped += 1
            continue
        extra: dict[str, JsonScalar] = {"updated_scope": "page"} if updated else {}
        rows.append(ParsedRow(name=name, status=status, updated_text=updated, extra=extra))
    if not rows:
        raise ShapeError("a closings listing with no named closing")
    return Listing(
        variant="nbc-legacy-page",
        state=ListingState.POPULATED,
        rows=tuple(rows),
        skipped_rows=skipped,
        declared_count=_legacy_count(tree),
    )


def parse(body: bytes) -> Listing:
    """Read an NBC school closings route or page (see the module docstring)."""
    raw = decode(body)
    text = text_of(raw)
    if text.lstrip().startswith("["):
        return parse_json(json_value(text))
    tree = parse_html(text)
    block = tree.css_first("div.article-content--wrap.closings")
    if block is not None:
        return _page(block)
    legacy = _legacy_page(tree.root) if tree.root is not None else None
    if legacy is None:
        raise ShapeError("not an NBC school closings route or page this adapter knows")
    return legacy


def slice_page(body: bytes) -> bytes:
    """Keep what :func:`parse` reads: the closings block of a page (a route is kept whole)."""
    text = text_of(decode(body))
    if text.lstrip().startswith("["):
        parse(body)
        return decode(body)
    match = _BLOCK_OPEN.search(text)
    if match is not None:
        kept = [text[match.start() : element_end(text, match.start(), "div")]]
    else:
        # The pre-2020 page: its heading block, its listing and the alerts bar's count.
        opens = [*_LEGACY_OPEN.finditer(text), *_LEGACY_COUNT_OPEN.finditer(text)]
        if not opens:
            raise ShapeError("no closings block to keep")
        kept = [text[m.start() : element_end(text, m.start(), "div")] for m in opens]
    sliced = minimal_document(kept)
    parse(sliced)
    return sliced
