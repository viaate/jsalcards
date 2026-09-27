"""Chicago's Emergency Closing Center (``https://wgnr-closings.emergencyclosingcenter.com/``).

The Emergency Closing Center (ECC) is the closings system Chicago's stations share:
CBS 2 (WBBM) and FOX 32 (WFLD) frame its application, NBC 5 Chicago's closings
address redirects to it, and WGN's page frames it too. The application
(``index.html`` and its script ``static/js/main.c73bd0ff.chunk.js``, read
2026-09-26 and 2026-09-27) loads one data file every 120 seconds,
``https://media.psg.nexstardigital.net/WGNR/closings/closings.json?timestamp=<ms>``,
and shows its ``$.Time`` as "Last Updated" and each closing's ``Name1[0]``,
``City[0]`` and ``Status1`` then ``Status2`` texts, filtered into tabs by
``EntityType[0]`` ("No closings to report." when the tab has none). Variants:

``ecc-json``
    The data file: an XML document converted to JSON (every element a list, the
    root's attributes under ``$``)::

        {"$": {"Time": "09/26/2026 12:30:31 PM"}}                 (nothing listed)
        {"$": {"Time": "01/20/2025 10:00:31 PM"}, "Closing": [
          {"Name1": ["DIST #46 (COMMUNITY CONSOLIDATED SCHOOL)"], "Name2": [""],
           "Status1": ["E-Learning"], "Status2": [""], "StatusCode": ["15"],
           "TodayTomorrow": [""], "EntityType": ["01 - Public School"],
           "EntityTypeCode": ["1"], "City": ["GRAYSLAKE"], "County": ["LAKE (IL)"],
           "State": ["IL"], "Group": [""], "Comments": [""],
           "UpdateTime": ["2025-01-20 21:57:13"], "ID": ["13063"]}, ...]}

    Each ``Closing`` is a row: ``Name1[0]`` is the name, the ``Status1`` then
    ``Status2`` texts joined with " | " the status, ``$.Time`` every row's
    ``raw_updated_text`` (``raw_extra["updated_scope"]`` is ``"page"``), and every
    other field goes in ``raw_extra`` under its name (a one-item list as its item,
    a longer one as JSON text), so each row keeps its own ``UpdateTime``, its
    ``EntityType`` (public and private schools, colleges, day care, religious,
    government, business) and its ``County`` and ``State``. No ``Closing`` (or an
    empty one) is the empty state. Archived captures of the file (downloaded by the
    archive-captures workflow, runs 36285593343, 36291380584 and 36293423860) show
    both forms, with the fifteen fields above in every closing of every populated
    capture from January 2024 to August 2026 (75 rows on 15 January 2024, 203 on
    20 January 2025, 144 on 11 February 2025, 102 on 26 January 2026). A file
    with other top-level fields or no ``$.Time``, a closing that is not an
    object, a ``Name1``, ``Status1`` or ``Status2`` that is not a list of text,
    or closings none of which has a name, is an error.

``ecc-app``
    The application's page (``index.html``, a create-react-app shell whose list
    arrives by script): a
    :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED` listing that
    names nothing, so the reader loads the station's registered ``data_url``.

``ecc-legacy-page``
    The closing center's own site before the application, when WGN Radio ran it
    (``www.emergencyclosingcenter.com/complete.html``, "ECC: Status Search";
    archived, 3,274 facilities on 6 January 2014; its home page ``/ecc/home.jsp``,
    "ECC: Home", carried the same table below a search form: 3,210 facilities that
    evening and 2,860 on 30 January 2019)::

        <p class="text">Below is a complete alphabetical listing of the status of
          <b>ALL REPORTED</b> ECC facilities <MARKET_TOKEN> as of 11:50 PM, CST
          (updated every 15 minutes). ...</p>
        <table ...>
          <tr><td>&nbsp;</td><td><p>Facility Name</p></td><td>&nbsp;</td>
              <td><p>City</p></td><td>&nbsp;</td><td><p>Status</p></td></tr>
          <tr bgcolor=#d5d5d5><td>&nbsp;</td><td><p class=text>A CHILDS SPACE</p></td>
              <td>&nbsp;</td><td><p class=text> CHICAGO</p></td><td>&nbsp;</td>
              <td><p class=text>(TODAY) CLOSED</p></td></tr>
          <tr><td>&nbsp;</td><td><p class=text>&nbsp;</p></td><td>&nbsp;</td>
              <td><p class=text>&nbsp;</p></td><td>&nbsp;</td>
              <td><p class=text>(TOMORROW) CLOSED</p></td></tr> ...

    Each table row after the heading row is a facility: the second cell its name,
    the fourth its city (``raw_extra["City"]``) and the sixth its status; the time
    after "as of" is every row's ``raw_updated_text``. A row whose name and city
    cells are blank carries a second status line of the facility above it (the
    page's layout of what the application's file holds as ``Status1`` and
    ``Status2``): it is joined to that facility's status with " | ", as the file's
    two statuses are, and counted in ``raw_extra["status_lines"]``. A heading row
    other than Facility Name, City, Status, a row of other than six cells, a
    status line with no facility above it, or a table with no facility (the page's
    empty form has not been seen) is an error.

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`.
"""

import re
from collections.abc import Mapping
from html import unescape

from snowlight.sources.stations.body import decode
from snowlight.sources.stations.model import (
    JsonScalar,
    Listing,
    ListingState,
    ParsedRow,
    ShapeError,
)
from snowlight.sources.stations.network_markup import (
    SEPARATOR,
    collapse,
    element_end,
    flat,
    json_value,
    minimal_document,
    text_of,
)

APP_SCRIPT_PREFIX = "/static/js/main."
"""The application's script, which the ECC page loads (its list arrives from it)."""
_TOP_FIELDS = frozenset({"$", "Closing"})
_READ = frozenset({"Name1", "Status1", "Status2"})
LEGACY_HEADINGS = ("", "Facility Name", "", "City", "", "Status")
"""The heading row of the legacy page's list table, cell by cell."""
_LEGACY_TITLE = re.compile(r"<title>\s*ECC: (?:Status Search|Home)\s*</title>", re.IGNORECASE)
_LEGACY_AS_OF = re.compile(r"<p\b[^>]*>(?:(?!</p>).)*?\bECC facilities\b.*?</p>", re.I | re.S)
_LEGACY_TIME = re.compile(r"\bas of\s+(.*?)\s*\(updated", re.IGNORECASE | re.DOTALL)
_LEGACY_HEADING = re.compile(r"<p\b[^>]*>\s*Facility Name\s*</p>", re.IGNORECASE)
_TABLE_OPEN = re.compile(r"<table\b[^>]*>", re.IGNORECASE)
_ROW = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_CELL = re.compile(r"<td\b[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]*>")


def _texts(value: object, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ShapeError(f"an ECC closing's {field} is not a list of text")
    return [collapse(item) for item in value if collapse(item)]


def _one(value: object) -> JsonScalar:
    """A one-item list (as the XML-to-JSON conversion writes an element) as its item."""
    if isinstance(value, list) and len(value) == 1:
        return flat(value[0])
    return flat(value)


def _row(closing: object, updated: str) -> ParsedRow | None:
    if not isinstance(closing, Mapping):
        raise ShapeError("an ECC closing is not an object")
    names = _texts(closing.get("Name1"), "Name1")
    status = SEPARATOR.join(
        _texts(closing.get("Status1"), "Status1") + _texts(closing.get("Status2"), "Status2")
    )
    if not names:
        return None
    extra: dict[str, JsonScalar] = {"updated_scope": "page"}
    for key, value in closing.items():
        if key not in _READ:
            extra[str(key)] = _one(value)
    return ParsedRow(name=names[0], status=status, updated_text=updated, extra=extra)


def parse_json(data: object) -> Listing:
    """Read the ECC data file (``ecc-json``)."""
    if not isinstance(data, Mapping):
        raise ShapeError("the ECC file is not a JSON object")
    unknown = set(data) - _TOP_FIELDS
    if unknown:
        raise ShapeError(f"the ECC file has unexpected fields {sorted(unknown)}")
    head = data.get("$")
    time = head.get("Time") if isinstance(head, Mapping) else None
    if not isinstance(time, str) or not time.strip():
        raise ShapeError("the ECC file has no $.Time")
    closings = data.get("Closing") or []
    if not isinstance(closings, list):
        raise ShapeError("the ECC file's Closing is not a list")
    rows: list[ParsedRow] = []
    skipped = 0
    for closing in closings:
        row = _row(closing, collapse(time))
        if row is None:
            skipped += 1
        else:
            rows.append(row)
    if skipped and not rows:
        raise ShapeError("every ECC closing is missing its name")
    return Listing(
        variant="ecc-json",
        state=ListingState.POPULATED if rows else ListingState.EMPTY,
        rows=tuple(rows),
        skipped_rows=skipped,
    )


def _cell_text(cell: str) -> str:
    return collapse(unescape(_TAG.sub(" ", cell)))


def _legacy_table(html: str) -> str:
    """The legacy page's list table (the table whose heading row names the facility)."""
    heading = _LEGACY_HEADING.search(html)
    if heading is None:
        raise ShapeError("the legacy ECC page has no Facility Name heading")
    opens = [match.start() for match in _TABLE_OPEN.finditer(html, 0, heading.start())]
    if not opens:
        raise ShapeError("the legacy ECC page's list is not in a table")
    return html[opens[-1] : element_end(html, opens[-1], "table")]


def _legacy_updated(html: str) -> str | None:
    paragraph = _LEGACY_AS_OF.search(html)
    found = _LEGACY_TIME.search(paragraph.group(0)) if paragraph is not None else None
    return collapse(found.group(1)) if found is not None else None


def parse_legacy(html: str) -> Listing:
    """Read the closing center's pre-application page (``ecc-legacy-page``)."""
    updated = _legacy_updated(html)
    rows = [
        [_cell_text(cell) for cell in _CELL.findall(row)]
        for row in _ROW.findall(_legacy_table(html))
    ]
    if not rows or tuple(rows[0]) != LEGACY_HEADINGS:
        raise ShapeError("the legacy ECC table's heading is not Facility Name, City, Status")
    facilities: list[tuple[str, str, list[str]]] = []
    for cells in rows[1:]:
        if len(cells) != len(LEGACY_HEADINGS) or any(cells[i] for i in (0, 2, 4)):
            raise ShapeError("a legacy ECC row is not a facility, city and status")
        name, city, status = cells[1], cells[3], cells[5]
        if name:
            facilities.append((name, city, [status] if status else []))
        elif city or not facilities:
            raise ShapeError("a legacy ECC status line has no facility above it")
        elif status:
            facilities[-1][2].append(status)
    if not facilities:
        raise ShapeError("the legacy ECC table lists no facility (its empty form is unseen)")
    return Listing(
        variant="ecc-legacy-page",
        state=ListingState.POPULATED,
        rows=tuple(
            ParsedRow(
                name=name,
                status=SEPARATOR.join(statuses),
                updated_text=updated,
                extra={"City": city, "status_lines": len(statuses), "updated_scope": "page"},
            )
            for name, city, statuses in facilities
        ),
    )


def slice_legacy_page(body: bytes) -> bytes:
    """Keep the legacy page's title, its "as of" paragraph and its list table."""
    html = text_of(decode(body))
    title = _LEGACY_TITLE.search(html)
    paragraph = _LEGACY_AS_OF.search(html)
    if title is None or paragraph is None:
        raise ShapeError("not the legacy ECC page")
    return minimal_document([title.group(0), paragraph.group(0), _legacy_table(html)])


def is_app(text: str) -> bool:
    """Whether ``text`` is the ECC application's page (or a copy of it)."""
    return '<div id="root"></div>' in text and APP_SCRIPT_PREFIX in text


def parse(body: bytes) -> Listing:
    """Read an ECC data file or application page (see the module docstring)."""
    text = text_of(decode(body))
    if text.lstrip().startswith("{"):
        return parse_json(json_value(text))
    if is_app(text):
        return Listing(variant="ecc-app", state=ListingState.DEFERRED, rows=())
    if _LEGACY_TITLE.search(text):
        return parse_legacy(text)
    raise ShapeError("not an Emergency Closing Center file or page this adapter knows")
