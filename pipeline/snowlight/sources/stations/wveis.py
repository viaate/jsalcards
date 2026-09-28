"""West Virginia's statewide school closings (WVEIS, West Virginia Department of Education).

County board offices post their announcements to
``https://wveis.k12.wv.us/closings/``, whose page says "Running an automated news
service? Use the RSS feed." and links ``/closings/rss.php``. Variant this adapter
reads:

``wveis-rss``
    The RSS feed. The feed's own comment says it carries public schools only,
    "announcements affecting entire counties at once or individual schools in
    counties". Each ``<item>`` is one posting, as the storm-day capture of
    2026-01-29 17:45 UTC shows (55 of them, one per county)::

        <item><title>All schools in Marion County</title>
          <link>https://wveis.k12.wv.us/closings/county.php?id=47</link>
          <description><![CDATA[As of Jan 28, 11:08am: All schools in Marion County will be
            non-traditional learning on Thu. Jan. 29, 2026 due to Weather.]]></description>
          <pubDate>Wed, 28 Jan 2026 11:08:31 -0500</pubDate>
          <guid isPermaLink="false">11677-1769616511</guid></item>

    The title is the name (it says whom the posting is for: a whole county's
    schools, or a school), the description the status (the posting's own sentence,
    kept whole), and the item's ``pubDate`` its update text; the ``link`` (the
    county's page) and ``guid`` go in ``raw_extra``, as does any other child element
    by its tag. With nothing posted the feed holds one item, "No closings to
    report" / "Nothing to report" (live on 2026-09-27, archived 2024-11-21): the
    empty state. An item without a title or description raises
    :class:`~snowlight.sources.stations.model.ShapeError`, as does a feed that
    mixes the no-closings item with postings.

``wveis-page``
    The closings pages themselves, which the server writes: the public schools' list
    (``/closings/``, also ``?text=1``), and the private and public charter schools'
    lists the feed leaves out (``private.php``, ``charter.php``). Each says which day
    it is about ("For today, Monday February 23, 2026 - as of Feb 23, 8:56am") and
    lists its postings in one ``table.closings-table``, one row per county (or per
    school, on the private and charter lists), as the storm-day captures of
    2025-01-05 and 2026-02-23 show::

        <tr><th>County</th><th>Closings</th><th>Delays</th><th>Dismissals</th>
            <th>Non-traditional</th><th>Bus info</th><th>Last update</th></tr>
        <tr><td><a href="county.php?id=4">Berkeley</a></td><td><span class="red">All</span></td>
            <td>None</td><td>None</td><td>None</td><td>None</td><td>Jan 5, 2:23pm</td></tr>

    (private.php's columns: School, Closed, Delayed, Early out, Last update.) The
    first cell is the name; the status is every column between the first and the
    last, each as "heading: cell" in the page's order ("Closings: All; Delays: None;
    ..."), kept whole for the status parser; the last cell ("Last update") is the
    update text. The day line goes in ``raw_extra["day"]`` and the first cell's link
    in ``raw_extra["link"]``. With nothing posted the page says "No announcements to
    report" under its day line and holds no table (live on 2026-09-27, in the page
    template of that date; the storm-day captures use an older template, with the
    list in ``div#wvde-content``): the empty state.

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`.
"""

from xml.etree import ElementTree

from selectolax.parser import HTMLParser, Node

from snowlight.sources.stations.body import decode
from snowlight.sources.stations.model import JsonScalar, Listing, ParsedRow, ShapeError
from snowlight.sources.stations.regional import (
    collapse,
    document,
    html_text,
    listing,
    node_text,
    row,
)

VARIANT = "wveis-rss"
PAGE = "wveis-page"
PAGE_EMPTY = "No announcements to report"
_CONTENT = ("div#page-content", "div#wvde-content")
_FIRST = frozenset({"County", "School"})
_LAST = "Last update"
_DAY = "For "
EMPTY_TITLE = "No closings to report"
EMPTY_DESCRIPTION = "Nothing to report"
_ROW_TAGS = frozenset({"title", "description", "pubDate"})
_MIN_COLUMNS = 3


def _text(item: ElementTree.Element, tag: str) -> str | None:
    found = item.find(tag)
    return None if found is None else collapse("".join(found.itertext()))


def _posting(item: ElementTree.Element) -> ParsedRow | None:
    title, description = _text(item, "title"), _text(item, "description")
    if title is None or description is None:
        raise ShapeError("a WVEIS feed item without a title or description")
    extra: dict[str, JsonScalar] = {}
    for child in item:
        if child.tag in _ROW_TAGS:
            continue
        if len(child):
            raise ShapeError(f"a WVEIS feed item's {child.tag!r} is not plain text")
        extra[child.tag] = collapse(child.text or "")
    return row(title, description, _text(item, "pubDate") or None, extra)


def _page_rows(table: Node, day: str | None) -> list[ParsedRow | None]:
    headers = [node_text(th) for th in table.css("th")]
    if len(headers) < _MIN_COLUMNS or headers[0] not in _FIRST or headers[-1] != _LAST:
        raise ShapeError(f"a WVEIS closings table with the columns {headers}")
    found: list[ParsedRow | None] = []
    for tr in table.css("tr"):
        cells = tr.css("td")
        if not cells:
            continue
        if len(cells) != len(headers):
            raise ShapeError(f"a WVEIS closings row has {len(cells)} cells, not {len(headers)}")
        texts = [node_text(td) for td in cells]
        status = "; ".join(f"{h}: {c}" for h, c in zip(headers[1:-1], texts[1:-1], strict=True))
        extra: dict[str, JsonScalar] = {}
        if day:
            extra["day"] = day
        link = cells[0].css_first("a")
        if link is not None and link.attributes.get("href"):
            extra["link"] = link.attributes.get("href")
        found.append(row(texts[0], status, texts[-1] or None, extra))
    return found


def _page(content: Node) -> Listing:
    tables = content.css("table.closings-table")
    caption = content.css_first("table.closings-table caption")
    lines = [node_text(p) for p in content.css("p")]
    day = (
        node_text(caption)
        if caption is not None
        else next((line for line in lines if line.startswith(_DAY)), None)
    )
    empty = PAGE_EMPTY in lines
    if len(tables) > 1:
        raise ShapeError("a WVEIS closings page with more than one table")
    found = _page_rows(tables[0], day) if tables else []
    rows = [item for item in found if item is not None]
    if rows and empty:
        raise ShapeError("a WVEIS closings page lists postings and says there are none")
    if not found and not empty:
        raise ShapeError("a WVEIS closings page with no postings and no no-announcements line")
    return listing(PAGE, rows, skipped=len(found) - len(rows))


def parse(body: bytes) -> Listing:
    """Read the WVEIS closings RSS feed or one of the closings pages."""
    text = html_text(body)
    if "<rss" not in text[:1000]:
        tree = HTMLParser(text)
        content = next((node for sel in _CONTENT if (node := tree.css_first(sel))), None)
        if content is None:
            raise ShapeError("not the WVEIS closings feed or page")
        return _page(content)
    try:
        root = ElementTree.fromstring(decode(body))  # noqa: S314 - a small state feed
    except ElementTree.ParseError as error:
        raise ShapeError(f"the RSS feed does not parse: {error}") from error
    channel = root.find("channel")
    if root.tag != "rss" or channel is None:
        raise ShapeError("not an RSS feed")
    items = channel.findall("item")
    if not items:
        raise ShapeError("the WVEIS feed holds no item, not even its no-closings item")
    empty = [
        item
        for item in items
        if (_text(item, "title"), _text(item, "description")) == (EMPTY_TITLE, EMPTY_DESCRIPTION)
    ]
    if empty:
        if len(items) != 1:
            raise ShapeError("the WVEIS feed says nothing is posted and also posts items")
        return listing(VARIANT, [])
    rows: list[ParsedRow] = []
    skipped = 0
    for item in items:
        found = _posting(item)
        if found is None:
            skipped += 1
        else:
            rows.append(found)
    return listing(VARIANT, rows, skipped=skipped)


def slice_body(body: bytes) -> bytes:
    """The feed is kept whole (decoded); a page is cut to its content block."""
    found = parse(body)
    if found.variant != PAGE:
        return decode(body)
    tree = HTMLParser(html_text(body))
    content = next((node for sel in _CONTENT if (node := tree.css_first(sel))), None)
    return document((content.html or "") if content is not None else "")
