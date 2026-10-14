"""Cowles Montana Media's school closures ticker (KULR-8 and NonStop Local Montana).

Cowles' Montana stations show one list of school closures: KULR-8's page "Montana
School Closures" (``https://www.kulr8.com/schoolclosures/``) and NonStop Local
Montana's page "School Closures Around Montana"
(``https://www.montanarightnow.com/schoolclosures/``, the site of KFBB/KHBB, KTMF
and KWYB) both frame the same file, which the company's ticker system writes to
S3: ``https://company-wide-tickers.s3.us-west-2.amazonaws.com/KULR_School_Results/closings.html``
(read live on 2026-09-27; ``Last-Modified`` 2026-04-16, inside the last winter).
Variants this adapter reads:

``closings-grid``
    The ticker file, a "Closings Last Updated at" grid (the NewsTicker generator's
    grid form): the line "Closings Last Updated at 9:13am on 4/16/2026" over a table
    of three-cell rows, one per organization::

        <tr><td width="33%"><b>Name</b></td><td width="33%">Status</td>
            <td width="33%">Comment</td></tr>

    The bold first cell is the name, the second the status, and the third (often
    blank) goes in ``raw_extra["comment"]`` when it holds text. A row of one bold
    cell is a heading, kept as ``raw_extra["group"]`` on the rows under it. The
    update line's time is each row's ``raw_updated_text`` (``raw_extra["updated_scope"]``
    is ``"page"``: the file gives one time for the whole list). The bold sentence
    "No Closings have been reported at this time" in the first of three otherwise
    blank cells is the empty state (live on 2026-09-27).

``cowles-page``
    Either station page: a TownNews BLOX page whose body frames the ticker
    (``<iframe src="https://company-wide-tickers.s3.us-west-2.amazonaws.com/KULR_School_Results/closings.html"``).
    A :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED` listing that
    follows the file.

Before the pages framed the ticker (archived 2019 to 2021), each ``/schoolclosures/``
page was a TownNews BLOX section page (``<body class="... section-schoolclosures">``)
in one of two forms:

``cowles-closures-article``
    KULR-8's section page showing the station's latest closings article in full
    (``<article class="asset ...">`` with its headline, its time and its
    ``itemprop="articleBody"``), the list typed into the article as bulleted lines
    under regional headings: "Statewide school delays and closures for Monday,
    March 4" (published 2019-03-03, captured 2019-07-16 and 2019-08-20: 25 schools,
    "Amsterdam School CANCELED", "Belgrade School District 2-HOUR DELAY", ...) and
    "... for Wednesday, October 9" (published 2019-10-08, captured 2019-10-19 to
    2021-09-17: "Pretty Eagle Catholic Academy - St. Xavier - 2 HOUR DELAY", "Pryor
    Public Schools - CLOSED"). Each bulleted line is one row: ``raw_name`` the line
    up to its status (the first status word: closed, canceled, delay, early, late,
    no buses, remote; a dash before it is dropped), ``raw_status`` the rest
    (``raw_extra["line"]`` keeps the whole line), ``raw_updated_text`` the article's
    published time as its ``<time datetime>`` gives it, and ``raw_extra``
    ``headline`` and ``lead`` (the article's headline and first paragraph, "As winter
    weather and bitterly cold temperatures continue to impact the region, several
    schools are closed or delayed to start the week.") and ``group`` (the bold
    heading above the line, "Western Montana:"). A line with no status word is kept
    whole as its name.
    The article was typed by hand and stayed up long after the day it names (the
    March article in July; the October article until September 2021), so the
    listing is ``typed`` with ``list_updated_at`` the article's time: the live reader
    keeps such rows only while the article is current.

``cowles-section-cards``
    NonStop Local Montana's section pages (abcfoxmontana.com 2019-11-20,
    montanarightnow.com 2020-11-24 and 2021-03-06): BLOX cards of the section's
    stories (``<article class="... card ...">`` in the page's main regions, not its
    right rail), none on the first two, one on the last ("Dodson Public Schools
    closed indefinitely due to positive COVID-19 cases"). A link card
    (``tnt-asset-type-link``: the site's "Check current road conditions" link to the
    state's road report, on the last two) is a link to another site, not a story,
    and is not read. One row per story card: ``raw_name`` its headline (else its
    image's ``alt``), ``raw_status`` its summary, and ``raw_extra`` ``link`` and
    ``card`` (the card's asset type). A section with no story card is an empty list.
    A card is a story, not a list's entry: such a row proves the station's list
    only when it announces a closing for weather or an emergency
    (:func:`snowlight.sources.stations.notices.row_qualifies`).

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`, and so
does a grid that lists rows and also says none are reported, or a row whose shape
is not one of the above.
"""

import re
from datetime import UTC, datetime

from selectolax.parser import HTMLParser, Node

from snowlight.sources.stations.body import decode
from snowlight.sources.stations.gap_markup import (
    collapse,
    deferred,
    document,
    html_text,
    make_listing,
    make_row,
    node_text,
)
from snowlight.sources.stations.model import JsonScalar, Listing, ParsedRow, ShapeError

GRID = "closings-grid"
PAGE = "cowles-page"
ARTICLE = "cowles-closures-article"
CARDS = "cowles-section-cards"
GRID_EMPTY = "No Closings have been reported at this time"
TICKER_HOST = "company-wide-tickers.s3.us-west-2.amazonaws.com"

_STAMP = re.compile(r"Closings Last Updated at\s*([^<]*?)\s*<", re.IGNORECASE)
_FRAME = re.compile(
    r"<iframe\b[^>]*\bsrc=\"(https?://company-wide-tickers\.s3[.a-z0-9-]*\.amazonaws\.com/"
    r"[A-Za-z0-9_]+/closings\.html)\"",
    re.IGNORECASE,
)
_COLUMNS = 3
_SECTION = re.compile(r"<body\b[^>]*\bclass=\"[^\"]*\bsection-schoolclosures\b", re.IGNORECASE)
_STATUS_WORD = re.compile(
    r"(?:\s+-\s*|\s+-(?=\S)|\s+)(?=(?:\d+\s*-?\s*hours?\b|closed\b|clos(?:ing|ure)\b|"
    r"cancel(?:l)?ed\b|cancel(?:l)?ations?\b|delay(?:ed|s)?\b|early\b|late\b|no\s+(?:buses|school)\b|"
    r"remote\b|virtual\b|online\b))",
    re.IGNORECASE,
)
_RAIL = ("right", "rail", "sidebar", "aside")


def _grid(text: str) -> Listing:
    stamp = _STAMP.search(text)
    updated = collapse(stamp.group(1)) if stamp is not None and stamp.group(1).strip() else None
    tree = HTMLParser(text)
    rows: list[ParsedRow] = []
    group: str | None = None
    empty = False
    skipped = 0
    for tr in tree.css("tr"):
        cells = tr.css("td")
        if not cells or cells[0].css_first("b") is None:
            raise ShapeError("a closings grid row does not start with a bold cell")
        texts = [node_text(td) for td in cells]
        if texts[0] == GRID_EMPTY and not any(texts[1:]):
            empty = True
            continue
        if len(cells) == 1:
            group = texts[0] or None
            continue
        if len(cells) != _COLUMNS:
            raise ShapeError(f"a closings grid row has {len(cells)} cells, not {_COLUMNS}")
        extra: dict[str, JsonScalar] = {"updated_scope": "page"} if updated else {}
        if group is not None:
            extra["group"] = group
        if texts[2]:
            extra["comment"] = texts[2]
        found = make_row(texts[0], texts[1], updated, extra)
        if found is None:
            skipped += 1
        else:
            rows.append(found)
    if rows and empty:
        raise ShapeError("a closings grid lists rows and says none are reported")
    if not rows and not empty:
        raise ShapeError("a closings grid with no rows and no no-closings sentence")
    return make_listing(GRID, rows, skipped=skipped)


def _split(line: str) -> tuple[str, str]:
    """A typed line's name and status: the status starts at its first status word."""
    found = _STATUS_WORD.search(line)
    if found is None or found.start() == 0:
        return line, ""
    return line[: found.start()].rstrip(" -"), line[found.end() :].strip()


def _published(article: Node) -> tuple[str | None, datetime | None]:
    stamp = article.css_first("time[datetime]")
    value = stamp.attributes.get("datetime") if stamp is not None else None
    if not isinstance(value, str) or not value.strip():
        return None, None
    try:
        moment = datetime.fromisoformat(value.strip())
    except ValueError as error:
        raise ShapeError(f"a closings article's time is not ISO 8601: {value!r}") from error
    if moment.tzinfo is None:
        raise ShapeError(f"a closings article's time has no zone: {value!r}")
    return value.strip(), moment.astimezone(UTC).replace(microsecond=0)


def _article(article: Node) -> Listing:
    body = article.css_first('[itemprop="articleBody"]')
    if body is None:
        raise ShapeError("a closings article without its articleBody")
    headline = node_text(article.css_first("h1.headline")) or None
    lead = next((node_text(p) for p in body.css("p") if not p.css_first("strong, b")), None)
    updated, moment = _published(article)
    rows: list[ParsedRow] = []
    skipped = 0
    group: str | None = None
    for node in body.traverse():
        if node.tag == "p":
            bold = node.css_first("strong, b")
            if bold is not None and node_text(bold) == node_text(node):
                group = node_text(node) or None
            continue
        if node.tag != "li":
            continue
        line = node_text(node)
        name, status = _split(line)
        extra: dict[str, JsonScalar] = {"headline": headline, "lead": lead, "line": line}
        if group is not None:
            extra["group"] = group
        found = make_row(name, status, updated, extra)
        if found is None:
            skipped += 1
        else:
            rows.append(found)
    if not rows:
        raise ShapeError("a closings article with no bulleted lines: not the typed list")
    listing = make_listing(ARTICLE, rows, skipped=skipped)
    return Listing.model_validate(
        {**listing.model_dump(), "typed": True, "list_updated_at": moment}
    )


def _in_rail(node: Node) -> bool:
    parent = node.parent
    while parent is not None:
        names = f"{parent.attributes.get('class') or ''} {parent.attributes.get('id') or ''}"
        if any(word in names.lower() for word in _RAIL):
            return True
        parent = parent.parent
    return False


def _story_card(card: Node) -> bool:
    """A story card of the section's main regions (not the rail, not a link card)."""
    return not _in_rail(card) and "tnt-asset-type-link" not in (card.attributes.get("class") or "")


def _card(card: Node) -> ParsedRow | None:
    headline = node_text(card.css_first(".tnt-headline, h3, h2"))
    image = card.css_first("img[alt]")
    alt = image.attributes.get("alt") if image is not None else None
    name = headline or (collapse(alt) if isinstance(alt, str) else "")
    summary = node_text(card.css_first(".tnt-summary, p.summary, .card-lead"))
    anchor = card.css_first("a[href]")
    href = anchor.attributes.get("href") if anchor is not None else None
    classes = card.attributes.get("class") or ""
    kind = re.search(r"\btnt-asset-type-([a-z]+)\b", classes)
    extra: dict[str, JsonScalar] = {
        "link": collapse(href) or None if isinstance(href, str) else None,
        "card": kind.group(1) if kind else None,
    }
    return make_row(name, summary, None, extra)


def _section(text: str) -> Listing:
    tree = HTMLParser(text)
    article = tree.css_first("article.asset")
    if article is not None:
        return _article(article)
    rows: list[ParsedRow] = []
    skipped = 0
    for card in tree.css("article.card"):
        if not _story_card(card):
            continue
        found = _card(card)
        if found is None:
            skipped += 1
        else:
            rows.append(found)
    return make_listing(CARDS, rows, skipped=skipped)


def parse(body: bytes) -> Listing:
    """Read Cowles' closures ticker file, a station page that frames it, or an older one."""
    text = html_text(body)
    if _STAMP.search(text) is not None:
        return _grid(text)
    frame = _FRAME.search(text)
    if frame is not None:
        return deferred(PAGE, (frame.group(1),))
    if _SECTION.search(text) is not None:
        return _section(text)
    raise ShapeError("neither Cowles' closures ticker nor a page that frames it")


def slice_body(body: bytes) -> bytes:
    """Cut a station page to its frame; the ticker file is kept whole (decoded)."""
    found = parse(body)
    if found.variant == PAGE:
        return document(f'<iframe src="{found.follows[0]}"></iframe>')
    return decode(body)


def slice_body_v2(body: bytes) -> bytes:
    """Cut a body as :func:`slice_body` does, and an older section page to what it shows.

    A closings-article page keeps the section's ``<body>`` class and the article
    (without scripts, styles or images); a section of story cards keeps the class
    and each card read. Slicing a slice changes nothing, and it reads as the page.
    """
    found = parse(body)
    if found.variant not in {ARTICLE, CARDS}:
        return slice_body(body)
    tree = HTMLParser(html_text(body))
    if found.variant == ARTICLE:
        kept = [tree.css_first("article.asset")]
    else:
        kept = [
            card
            for card in tree.css("article.card")
            if not _in_rail(card)
            and "tnt-asset-type-link" not in (card.attributes.get("class") or "")
        ]
    parts = []
    for node in kept:
        if node is None:
            continue
        for junk in node.css("script, style, img, noscript, svg, form"):
            junk.decompose()
        parts.append(node.html or "")
    inner = "".join(parts)
    return (
        f'<!DOCTYPE html><html><body class="section-schoolclosures">{inner}</body></html>\n'
    ).encode()
