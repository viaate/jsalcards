"""District homepages: the closings a homepage's own text shows, beside its alert channel.

A district's alert channel (:data:`~snowlight.sources.stations.notices.GENERAL_CHANNEL_ADAPTERS`)
is read through the form its homepage has: an Apptegy banner, an Edlio homepage
alert, a SharpSchool slider, a Web Community Manager announcements app. A
district does not always post its closing there. Indian River's SharpSchool
homepage of 2020-11-08 carried "SDIRC Closed Monday Nov. 9 Due to Potential Storm
Impacts From Tropical Storm Eta" as a news item; Robstown ISD's Edlio homepage of
2025-01-21, read with no homepage alert up, led its headlines with "Robstown ISD
Schools Closed Tuesday Due to Inclement Weather"; and the archive holds homepages
in forms no reader here knows (a district's site before its current platform:
WordPress themes, Google Sites, a vendor's own). What the homepage's text shows is
read the way the closure-text check reads it
(:func:`snowlight.sources.stations.closure_text.page_lines` and
:func:`~snowlight.sources.stations.closure_text.closure_lines`: the text a visitor
sees, without scripts or the entries of the site's menus, one line per block, each
line that announces a closing or states the district's weather status for a named
day, a title and the line under it read together when only the two together say it):

* :func:`with_page_text`: a homepage read in a known form (an empty or populated
  list) gets one more row for each closing line its text shows that none of its
  rows holds; a homepage that loads its alerts from a file and shows closing lines
  of its own (Indian River's SharpSchool homepage of the Eta closing, San Benito's
  Finalsite homepage of 2026-01-25, "Delayed start on Monday, January 26th") is read
  as those lines, loading the file beside them;
* :func:`other_form`: a homepage in no known form (its reader raised :class:`NoFormError`)
  is read by its site alert module when it has one (:func:`site_alerts`: a district site
  of 2017 to 2023 in Florida, ``div#alerts .site-alert``, each alert a channel row:
  Calhoun's "School Canceled Tuesday, Wednesday, and Thursday" of 2018-10-08, posted
  before Hurricane Michael), and otherwise as variant
  ``homepage-text``: its closing lines as rows, or, when it shows none, a page that
  holds no list of its own (``deferred``, naming no file): what its alert channel
  held, if it loaded one by script, is not in the page.

A page-text row: ``raw_name`` the line as written (to the row name's limit),
``raw_status`` the line, no ``raw_updated_text``, ``raw_extra`` ``section``
(``"page-text"``: the row is the page's text, not an alert the district posted to
its channel). A page-text row proves its channel only when it announces a closing,
a delay, a remote day or cancelled classes for weather or an emergency, and is not
a teaser or an explainer
(:func:`snowlight.sources.stations.notices.page_text_closing`), or states the
schools' status for a named day and names weather
(:func:`~snowlight.sources.stations.notices.page_text_status`), so a calendar's
"No School on Feb 15th, 2019 and Feb 18th, 2019" never does, nor a closing that
names no reason unless an NWS warning covered the district on the one day it names
(:func:`~snowlight.sources.stations.notices.dated_closing`). A JSON answer (an alert
service's) is never given page-text rows: its alerts are its rows.
"""

import re
from collections.abc import Callable
from html import escape

from selectolax.parser import HTMLParser

from snowlight.sources.stations import closure_text
from snowlight.sources.stations.gap_markup import collapse, html_text, make_row
from snowlight.sources.stations.model import (
    MAX_NAME,
    JsonScalar,
    Listing,
    ListingState,
    ParsedRow,
    ShapeError,
)

PAGE_TEXT = "page-text"
"""``raw_extra["section"]`` of a row read from a homepage's text."""
TEXT_VARIANT = "homepage-text"
"""A homepage in no form a reader knows, read as text."""
SITE_ALERT_VARIANT = "site-alert-module"
"""A homepage's site alert module (:func:`site_alerts`)."""


def is_html(text: str) -> bool:
    """Whether a decoded body is an HTML page (not JSON, not empty)."""
    head = text.lstrip()[:2000].lower()
    return bool(head) and not head.startswith(("{", "[")) and "<" in head


POSTED = re.compile(
    r"^\W*posted(?:\s+on)?\s*:?\s*"
    r"((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})\W*$",
    re.IGNORECASE,
)
"""A news card's posting stamp under its headline ("posted: Oct 07, 2026", Gulf's homepage)."""
POSTED_MARK = " (posted {day})"
"""How a page-text row says the date its card was posted, after the line itself."""


def _posted(lines: list[str], line: str) -> str | None:
    """The posting stamp of the card a line heads, when the next line or the one after is
    one (``Oct 07, 2026``), or None."""
    try:
        index = lines.index(line)
    except ValueError:
        return None
    after = lines[index + 1 : index + 4]
    candidates = [*after[:2], " ".join(after[:2]), " ".join(after[1:3])]
    for following in candidates:
        found = POSTED.match(following)
        if found is not None:
            return collapse(found.group(1))
    return None


def text_rows(text: str) -> list[ParsedRow]:
    """One row for each line of the page's text that announces a closing.

    A line that heads a news card with a posting stamp ("SCHOOL CLOSURES: Hurricane
    Isaias" over "posted: Oct 07, 2026") carries the stamp after it (:data:`POSTED_MARK`),
    so the line is judged by the day it was posted, not as an undated leftover.
    """
    rows: list[ParsedRow] = []
    lines = closure_text.page_lines(text.encode("utf-8"))
    for line in closure_text.closure_lines(lines):
        day = _posted(lines, line)
        status = line + POSTED_MARK.format(day=day) if day is not None else line
        extra: dict[str, JsonScalar] = {"section": PAGE_TEXT}
        if day is not None:
            extra["posted"] = day
        row = make_row(line[:MAX_NAME], status, None, extra)
        if row is not None:
            rows.append(row)
    return rows


def with_page_text(listing: Listing, text: str) -> Listing:
    """Add the page's closing lines that no row of ``listing`` holds, as page-text rows.

    A list read from the page itself (empty or populated) is extended. A page that
    defers to the file it loads its alerts from (a Finalsite homepage's page pops, a
    Web Community Manager homepage's on-screen alert, a SharpSchool homepage's alert
    service) and shows closing lines of its own becomes a list of those page-text
    rows that loads the file beside it (``also_loads``): the archive reader still
    reads the file's capture nearest the page, when it holds one. A page that shows
    none, or a JSON answer, is returned as it is.
    """
    if not is_html(text):
        return listing
    if listing.state is ListingState.DEFERRED and listing.follows:
        rows = text_rows(text)
        if not rows:
            return listing
        return Listing(
            variant=listing.variant,
            state=ListingState.POPULATED,
            rows=tuple(rows),
            also_loads=listing.follows,
        )
    if listing.state not in {ListingState.EMPTY, ListingState.POPULATED}:
        return listing
    held = closure_text.row_texts_of(listing.rows)
    extra = [row for row in text_rows(text) if not closure_text.line_read(row.status, held)]
    if not extra:
        return listing
    return Listing.model_validate(
        {**listing.model_dump(), "state": ListingState.POPULATED, "rows": (*listing.rows, *extra)}
    )


def site_alerts(text: str) -> Listing | None:
    """Read a homepage's site alert module, or None when it has none.

    The module (``<div class="module" id="alerts"><div class="site-alert">``) holds one
    ``div.alert-wrapper`` per alert the district posted, its title in
    ``span.alert-title`` and any text in ``div.alert-content``; the page's script shows
    each one unless the visitor closed it (Hamilton's "School District Announces
    Closure for Thursday and Friday in Preparation for Severe Weather!" of 2022-11-10,
    Calhoun's "School Canceled Tuesday, Wednesday, and Thursday" of 2018-10-08). Each
    alert is a row of the district's alert channel (its title the name, its title and
    text the status); a module with no alert is the empty channel.
    """
    tree = HTMLParser(text)
    module = tree.css_first("div#alerts div.site-alert")
    if module is None:
        return None
    rows: list[ParsedRow] = []
    for wrapper in module.css("div.alert-wrapper"):
        title_node = wrapper.css_first(".alert-title")
        title = collapse(title_node.text(deep=True, separator=" ")) if title_node else ""
        body_node = wrapper.css_first(".alert-content")
        body = collapse(body_node.text(deep=True, separator=" ")) if body_node else ""
        row = make_row(title or body, " ".join(part for part in (title, body) if part), None, {})
        if row is not None:
            rows.append(row)
    state = ListingState.POPULATED if rows else ListingState.EMPTY
    return Listing(variant=SITE_ALERT_VARIANT, state=state, rows=tuple(rows))


def other_form(text: str) -> Listing:
    """Read a homepage in no known form by its site alert module or by its text (see the
    module docstring).

    Raises:
        ShapeError: the body is not an HTML page.
    """
    if not is_html(text):
        raise ShapeError("not an HTML page: no homepage form to read")
    alerts = site_alerts(text)
    if alerts is not None:
        return with_page_text(alerts, text)
    rows = text_rows(text)
    if rows:
        return Listing(variant=TEXT_VARIANT, state=ListingState.POPULATED, rows=tuple(rows))
    return Listing(variant=TEXT_VARIANT, state=ListingState.DEFERRED, rows=())


class NoFormError(ShapeError):
    """The page is in none of a reader's forms (not a malformed page of one of them).

    A reader raises it when no form it knows holds; :func:`read_homepage` then reads
    the page by its text. Any other :class:`ShapeError` (a page in a known form that
    does not read: a Nuxt payload that does not unflatten, a Finalsite page whose
    page ID is not a number) is a failure, as before.
    """


def read_homepage(text: str, read: Callable[[str], Listing]) -> Listing:
    """Read a homepage with ``read``, else as text (:func:`other_form`), and add its page text.

    Only :class:`NoFormError` sends a page to its text; any other refusal is raised.
    """
    try:
        listing = read(text)
    except NoFormError:
        if not is_html(text):
            raise
        return other_form(text)
    return with_page_text(listing, text)


def text_blocks(text: str, *, stamps: bool = False) -> str:
    """The page's closing lines as ``<p>`` elements, for a fixture's slice.

    A slice that keeps them (and what its form's reader reads) reads exactly as the
    page does: :func:`text_rows` finds the same lines in it. With ``stamps`` (the
    ``district-homepage-v2`` slice), a line that heads a news card keeps the card's
    posting stamp after it, as its own paragraph.
    """
    every = closure_text.page_lines(text.encode("utf-8"))
    blocks: list[str] = []
    for line in closure_text.closure_lines(every):
        blocks.append(f"<p>{escape(line, quote=False)}</p>")
        day = _posted(every, line) if stamps else None
        if day is not None:
            blocks.append(f"<p>posted: {escape(day, quote=False)}</p>")
    return "".join(blocks)


def slice_body(body: bytes) -> bytes:
    """Cut a page read by its text (``homepage-text``) to its title and closing lines,
    and its site alert module (:func:`site_alerts`) when it has one, without scripts."""
    text = html_text(body)
    tree = HTMLParser(text)
    title = tree.css_first("title")
    head = f"<title>{escape(collapse(title.text()), quote=False)}</title>" if title else ""
    module = tree.css_first("div#alerts")
    kept = ""
    if module is not None and module.css_first("div.site-alert") is not None:
        for script in module.css("script"):
            script.decompose()
        kept = module.html or ""
    inner = f"<head>{head}</head><body>{kept}{text_blocks(text)}</body>"
    return f"<!DOCTYPE html><html>{inner}</html>\n".encode()
