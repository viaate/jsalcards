"""CBS News and Stations' school closings pages and the files they load.

Eight CBS-owned stations show a closings list (first-hand check of 2026-09-26,
re-read live 2026-09-27). Their pages (``https://www.cbsnews.com/{market}/school-closings/``)
hold no list: seven name a feed in their closings widget, which a script loads,
and CBS Colorado frames a file. The live poller reads each station's file
directly. Variants this adapter reads:

``gray-file-newsticker-xml``, ``gray-file-sc-xml`` and ``gray-file-newsticker``
    The files: the NewsTicker closings system's XML export (WJZ, WBZ, WWJ, WCCO,
    KDKA, KTVT on ``assets1.cbsnewsstatic.com/Integrations/SchoolClosings/PRODUCTION/CBS/...``:
    ``<DATA>`` with ``NUM_CLOSINGS``, ``RUN_DATE`` and one ``RECORD`` per
    organization), the School Closings "File" XML (KYW's ``BTI/KYW-closingsC.xml``:
    ``<File Time="09/26/2026 09:10pm">`` holding one ``Closing`` per organization),
    and NewsTicker's HTML export (KCNC's
    ``static.cbslocal.com/Integrations/SchoolClosings/PRODUCTION/CBS/kcnc/NEWSROOM/closings.html``).
    These are vendor formats Gray stations' pages also loaded; they are read with
    :func:`snowlight.sources.stations.gray_files.parse` under that module's variant
    names (a NewsTicker XML export's ``NUM_CLOSINGS`` must equal its records; its
    ``FORCED_ORGANIZATION_NAME`` is the name and ``FORCED_STATUS_NAME`` the status).
    ``assets1.cbsnewsstatic.com``'s robots.txt disallows every path but three
    image folders; the project owner decided on 2026-09-26 to read closings files
    regardless, and every read records the verdict.

``cbs-newsticker-xml-short``
    WWJ's feed (``wwj/NEWSROOM/closings-active.xml``) as captured on 19 January
    2026: the same ``<DATA>`` export with fewer fields per ``RECORD`` and no
    ``FORCED_ORGANIZATION_NAME``. ``ORGANIZATION_NAME1`` is the name,
    ``FORCED_STATUS_NAME`` the status and ``UPDATED`` the update text; every other
    field goes in ``raw_extra`` under its name in lower case; ``NUM_CLOSINGS`` must
    equal the records read. It is recognized only when no record has a
    ``FORCED_ORGANIZATION_NAME`` and every record has an ``ORGANIZATION_NAME1``
    (a full export, empty or not, is read as ``gray-file-newsticker-xml``).

``cbs-widget-page``
    A station page whose closings widget names its feed::

        <div ... data-school-closings-options='{"provider":"newsroom",
             "feed":"https:\\/\\/assets1.cbsnewsstatic.com\\/Integrations\\/SchoolClosings\\/PRODUCTION\\/CBS\\/wjz\\/NEWSROOM\\/cbs_closings.xml"}'>

    A :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED` listing whose
    ``follows`` is the feed (the ``provider``, "newsroom" or "bti", is the
    feed's generator).

``cbs-frame-page``
    CBS Colorado's page, which frames its file in a lazily loaded
    ``<iframe class="embed__content lazyload" data-src="https://static.cbslocal.com/Integrations/SchoolClosings/...">``:
    ``DEFERRED``, ``follows`` naming the framed closings file.

Archived captures (archive-captures runs 36323195832 and 36330775706) show the
feeds with rows at WBZ (up to 258 records, 23 February 2026), WCCO (157, 26 March
2024), KDKA (24, 16 January 2024), WJZ (32, 11 February 2025) and WWJ (7, 19
January 2026, in the shorter export above), and KCNC's file with one row in
November 2022 and January 2024 (19 in March 2022); runs 36345276947 and later
added KTVT's feed with 10 records (4 February 2023) and KYW's with 14 (2 December
2025).
CBS Pittsburgh's page of April 2022 named its feed on ``static.cbslocal.com``
(registered as an earlier list file), and the Colorado, Pittsburgh, Texas and
Philadelphia pages from 2022 to 2026 are the two page variants above.

Anything else (the CBS Local pages of before 2022 included, until a capture shows
them) raises :class:`~snowlight.sources.stations.model.ShapeError`.
"""

import json
import re
from html import unescape
from xml.etree import ElementTree

from snowlight.sources.stations import gray_files
from snowlight.sources.stations.body import decode
from snowlight.sources.stations.model import (
    JsonScalar,
    Listing,
    ListingState,
    ParsedRow,
    ShapeError,
)
from snowlight.sources.stations.network_markup import collapse, text_of

FILE_VARIANTS = frozenset({"gray-file-newsticker-xml", "gray-file-sc-xml", "gray-file-newsticker"})
_OPTIONS = re.compile(r"data-school-closings-options=(?:'([^']*)'|\"([^\"]*)\")", re.IGNORECASE)
_FRAME = re.compile(
    r"<iframe\b[^>]*?\b(?:data-src|src)\s*=\s*\"(https?://[^\"]*SchoolClosings[^\"]*)\"",
    re.IGNORECASE,
)


_DATA_START = re.compile(
    rb"^\s*(?:<\?xml[^>]*>\s*)?(?:<!DOCTYPE[^>]*(?:\[[^\]]*\])?\s*>\s*)?<DATA>"
)
_SHORT_HEAD = frozenset({"SOURCE", "EXPORT_TYPE", "NUM_CLOSINGS", "RUN_DATE", "RUN_EPOCH"})
_SHORT_READ = frozenset({"ORGANIZATION_NAME1", "FORCED_STATUS_NAME", "UPDATED"})


def _short_export(raw: bytes) -> ElementTree.Element | None:
    """The root of a NewsTicker XML export whose records have no FORCED_ORGANIZATION_NAME."""
    if not _DATA_START.match(raw):
        return None
    try:
        root = ElementTree.fromstring(raw)  # noqa: S314 - see gray_files._xml: no entity expansion
    except ElementTree.ParseError:
        return None
    records = root.findall("RECORD")
    if not records or any(
        record.find("FORCED_ORGANIZATION_NAME") is not None for record in records
    ):
        return None
    return (
        root if all(record.find("ORGANIZATION_NAME1") is not None for record in records) else None
    )


def _text(element: ElementTree.Element, tag: str) -> str | None:
    child = element.find(tag)
    return None if child is None else collapse("".join(child.itertext()))


def _short_newsticker(root: ElementTree.Element) -> Listing:
    """Read the shorter NewsTicker XML export (``cbs-newsticker-xml-short``)."""
    count = _text(root, "NUM_CLOSINGS")
    if count is None or not count.isdigit():
        raise ShapeError("a NewsTicker XML export has no NUM_CLOSINGS count")
    rows: list[ParsedRow] = []
    skipped = 0
    for element in root:
        if element.tag in _SHORT_HEAD:
            continue
        if element.tag != "RECORD":
            raise ShapeError(f"a NewsTicker XML export holds a <{element.tag}>")
        name, status = _text(element, "ORGANIZATION_NAME1"), _text(element, "FORCED_STATUS_NAME")
        if status is None:
            raise ShapeError("a NewsTicker XML record has no FORCED_STATUS_NAME")
        if not name:
            skipped += 1
            continue
        extra: dict[str, JsonScalar] = {
            child.tag.lower(): collapse("".join(child.itertext()))
            for child in element
            if child.tag not in _SHORT_READ
        }
        rows.append(
            ParsedRow(name=name, status=status, updated_text=_text(element, "UPDATED"), extra=extra)
        )
    if len(rows) + skipped != int(count):
        raise ShapeError(f"NUM_CLOSINGS is {count} but the export holds {len(rows) + skipped}")
    if skipped and not rows:
        raise ShapeError("every NewsTicker XML record is missing its name")
    return Listing(
        variant="cbs-newsticker-xml-short",
        state=ListingState.POPULATED if rows else ListingState.EMPTY,
        rows=tuple(rows),
        declared_count=int(count),
        skipped_rows=skipped,
    )


def _feeds(html: str) -> list[str]:
    feeds: list[str] = []
    for match in _OPTIONS.finditer(html):
        raw = unescape(match.group(1) if match.group(1) is not None else match.group(2))
        try:
            options = json.loads(raw)
        except ValueError as error:
            raise ShapeError(f"the closings widget's options are not JSON: {error}") from error
        feed = options.get("feed") if isinstance(options, dict) else None
        if not isinstance(feed, str) or not feed.startswith(("https://", "http://")):
            raise ShapeError("the closings widget names no feed")
        feeds.append(feed)
    return feeds


def parse(body: bytes) -> Listing:
    """Read a CBS closings file or page (see the module docstring)."""
    raw = decode(body)
    short = _short_export(raw)
    if short is not None:
        return _short_newsticker(short)
    if gray_files.is_file(raw):
        listing = gray_files.parse(raw)
        if listing.variant in FILE_VARIANTS:
            return listing
        raise ShapeError(f"a list file in a format CBS files do not use ({listing.variant})")
    html = text_of(raw)
    feeds = _feeds(html)
    if feeds:
        return Listing(
            variant="cbs-widget-page",
            state=ListingState.DEFERRED,
            rows=(),
            follows=tuple(dict.fromkeys(feeds)),
        )
    frames = [unescape(match.group(1)) for match in _FRAME.finditer(html)]
    if frames:
        return Listing(
            variant="cbs-frame-page",
            state=ListingState.DEFERRED,
            rows=(),
            follows=tuple(dict.fromkeys(frames)),
        )
    raise ShapeError("not a CBS closings file or page this adapter knows")
