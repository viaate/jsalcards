"""FlashAlert Newswire's regional closings reports (``www.flashalertnewswire.net/IIN/reportsX/``).

FlashAlert (irx, LLC) carries closings for nine regions, each named by a
``RegionID`` on its feed page (https://www.flashalert.net/xml-feeds.html, read
2026-09-27): 1 Portland/Vancouver/Salem, 2 Eugene/Springfield/Roseburg/Albany/
Corvallis, 5 Colorado Springs/Rocky Mountain Area, 7 Spokane/Eastern
Washington/Northern Idaho, 10 Bend/Central Oregon/Eastern Oregon, 12
Seattle/Western Washington, 13 Columbia/Tri Cities/Pendleton/Yakima, 15
Boise/Southern Idaho and 25 Medford/Klamath Falls/Grants Pass. Stations frame or
copy a region's report. Variants:

``gray-file-flashalert``
    The region's HTML report, ``cwc-closures.php?RegionID={id}`` (polled live; the
    same report FlashAlert pushes to stations' own hosts, which
    :mod:`snowlight.sources.stations.gray_files` reads under this name and whose
    archived captures from 2019 to 2024 show its populated form)::

        <div id='cwcReportContainer'>
          <div id='cwcReportHeader'>Portland/Vanc/Salem Emergency Info for Sat. Sep. 26 -
            6:12 pm</div>
          <div id='cwcReportBody'> ...
            <div class='cwcReportCat'>Clackamas Co. Schools</div>
            <div class='cwcReport'><strong>Estacada Sch. Dist.</strong>&nbsp;- Virtual school
              days ...</div>

    Read with :func:`snowlight.sources.stations.gray_files.parse`: the bold name,
    the text after " - " as the status, the category heading and the header's
    time in ``raw_extra`` and ``raw_updated_text``; a single report "No
    information reported." is the empty state. The report carries every kind of
    emergency posting of the region (roads and offices as well as schools).
    Archived captures of FlashAlert's own region reports (archive-captures run
    36293423860) show the populated form for region 13 (11 postings on 14
    February 2019, 2 in March 2020) and the empty one in the markup of 2011 (the
    report's query left in an HTML comment), of December 2024 and of October 2025
    (with an accessibility widget script after the report); all read the same way.

``flashalert-emergency-xml``
    The region's emergency-only XML feed,
    ``flashnews_xml_emergency.php?RegionID={id}`` (ISO-8859-1, with its own DTD;
    the feed page documents its fields)::

        <flashnews updated="2026-09-26 06:12:05">
          <emergency>
            <emergency_category name="Central Co. Schools">
              <emergency_report report_id="26940" effective_date="2012-08-14 15:08:40"
                  updated="0" last_update="2012-08-14 15:08:50" testing="0"
                  schoolrelated="1" orgid="413" custom="0" operating_code="5" transpo_code="20">
                <detail><![CDATA[2 hrs late, Buses on snow rts]]></detail>
                <tomorrow><![CDATA[Effective tomorrow - Wed Aug 15th]]></tomorrow>
                <orgname orgid="413" tier="1" zipcode="x"><![CDATA[Cityville Schools]]></orgname>
              </emergency_report> ...

    Each ``emergency_report`` is a row: ``orgname`` is the name and ``detail``
    the status; ``last_update`` (else the feed's ``updated``) is the row's
    ``raw_updated_text``; the category's ``name`` (``category``), every attribute
    of the report and of ``orgname`` (``orgname_``-prefixed where the report has
    the same attribute), and ``tomorrow`` (when not empty) go in ``raw_extra``.
    ``schoolrelated`` "1" marks a school's report and ``testing`` "1" a test
    posting; both are kept as the feed gives them. An ``emergency`` element with no
    category is the empty state. Only the empty form has been seen live (all nine
    regions, 2026-09-27); the populated form is read as the feed page documents it.

``flashalert-site-page``
    The region's page on FlashAlert's own regional site ("FlashAlertEugene -
    Emergency Reports" at ``https://www.flashalerteugene.net/closures-cats.html``,
    and the same at flashalertportland.net, flashalertmedford.net,
    flashalertbend.net, flashalertboise.net, flashalertseattle.net,
    flashalertspokane.net and flashalertcolumbia.net; read live on 2026-09-27 and
    archived from 2015 to 2026). It shows the region's postings in one of three
    orders: by category (``closures-cats.html``) or by time
    (``closures-time.html``)::

        <div id='cwcReportHeader'>Eugene/Spring/Rose/Alb/Corv Emerg. Reports for
          Thu. Feb. 28 - 1:32 am</div>
        <div id='cwcReportBody'>
          <div class="cwcReportCat ReportToggle" id="Category34"><i ...></i> Lane Co.
            Schools <span class="GroupCount">(16)</div>
          <div class="ReportToggleContents">
            <div class="cwcReport" data-age="13392">&bull; <a href="...">Blachly Sch.
              Dist.</a> - Closed <span class='PostTime'>Posted: Wed. 27th, 09:48
              PM</span></div> ...
            <div class="cwcReport" ...>&bull; Slocum Orthopedics - Office Opening at
              8:30 <span class='PostTime'>...</span></div>

    or by message (``closures-report.html``), each row a name beside its status::

        <div class='cwcReportCat'>2 Hours Late</div>
        <div class="cwcReportLR"><div class="cwcReportLeft">&bull; <a href="...">Junction
          City Sch. Dist.</a></div><div class="cwcReportRight" data-age="610">2 Hours
          Late, AM/PM Buses on snow routes <span class='PostTime'>...</span></div></div>

    Each ``cwcReport`` (or ``cwcReportLR``) is a row: the name is the link text
    when the name is a link (``raw_extra["name_linked"]`` true), else the text
    before the first " - "; the status is the rest (the report's own words, with
    its "More Info" and "UPDATE" marks, as the region report keeps them). The
    heading in force goes in ``raw_extra["category"]`` (a category, or in the
    message order a status group), the "Posted: ..." time in
    ``raw_extra["posted"]``, the heading's own count (``GroupCount``, when it has
    one) in ``raw_extra["category_count"]``, and the header text is every row's
    ``raw_updated_text``. The count is kept as the page gives it, not checked: it
    leaves some postings out (Portland's "Transportation (1)" above two postings on
    12 February 2021). One report "There are no emergency messages to display
    currently." is the empty state. The ids are
    single-quoted before 2022 and double-quoted since; both are read.

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`.
"""

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
from snowlight.sources.stations.network_markup import collapse, element_end

REGIONS: dict[int, str] = {
    1: "Portland/Vancouver/Salem",
    2: "Eugene/Springfield/Roseburg/Albany/Corvallis",
    5: "Colorado Springs/Rocky Mountain Area",
    7: "Spokane/Eastern Washington/Northern Idaho",
    10: "Bend/Central Oregon/Eastern Oregon",
    12: "Seattle/Western Washington",
    13: "Columbia/Tri Cities/Pendleton/Yakima",
    15: "Boise/Southern Idaho",
    25: "Medford/Klamath Falls/Grants Pass",
}
"""FlashAlert's region codes, as its feed page lists them (read 2026-09-27)."""
REPORT_URL = "https://www.flashalertnewswire.net/IIN/reportsX/cwc-closures.php?RegionID={}"
XML_URL = "https://www.flashalertnewswire.net/IIN/reportsX/flashnews_xml_emergency.php?RegionID={}"
_XML_ROOT = b"<flashnews"
SITE_EMPTY = "There are no emergency messages to display currently."
"""The regional site's empty state."""
_SITE_TITLE = re.compile(r"<title>\s*FlashAlert[A-Za-z]+ - Emergency Reports\s*</title>", re.I)
_SITE_HEADER = re.compile(r"<div id=(['\"])cwcReportHeader\1>(.*?)</div>", re.I | re.S)
_SITE_BODY = re.compile(r"<div id=(['\"])cwcReportBody\1>", re.I)
_SITE_TOKEN = re.compile(
    r"<div class=(['\"])(?P<cls>cwcReportCat(?: ReportToggle)?|cwcReport|cwcReportLR)\1[^>]*>", re.I
)
_SITE_LEFT = re.compile(r"<div class=(['\"])cwcReportLeft\1[^>]*>", re.I)
_SITE_RIGHT = re.compile(r"<div class=(['\"])cwcReportRight\1[^>]*>", re.I)
_POSTED = re.compile(r"<span class=(['\"])PostTime\1>(.*?)</span>", re.I | re.S)
_GROUP_COUNT = re.compile(r"<span class=(['\"])GroupCount\1>\s*\((\d+)\)", re.I)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_LOGO = re.compile(r"<a\b[^>]*>\s*<img\b[^>]*\bid=(['\"])Logo2\1[^>]*>\s*</a>", re.I | re.S)
_ICON = re.compile(r"<i\b[^>]*>\s*</i>", re.I)
_LINKED = re.compile(
    r"^\s*(?:&bull;|\u2022)?\s*<a\b[^>]*>(?P<name>.*?)</a>(?P<rest>.*)$", re.I | re.S
)
_TAG = re.compile(r"<[^>]*>")
_BULLET = re.compile(r"^\s*(?:&bull;|\u2022)\s*")


def _is_utf8(body: bytes) -> bool:
    try:
        body.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _is_xml(body: bytes) -> bool:
    head = body.lstrip()[:4000]
    return head.startswith(b"<?xml") and _XML_ROOT in body[:8000]


def _report_row(
    report: ElementTree.Element, category: str | None, updated: str
) -> ParsedRow | None:
    orgname = report.find("orgname")
    name = collapse(orgname.text or "") if orgname is not None else ""
    detail = report.find("detail")
    status = collapse(detail.text or "") if detail is not None else ""
    tomorrow = report.find("tomorrow")
    extra: dict[str, JsonScalar] = {}
    if category is not None:
        extra["category"] = category
    for key, value in sorted(report.attrib.items()):
        extra[key] = value
    if orgname is not None:
        for key, value in sorted(orgname.attrib.items()):
            extra[f"orgname_{key}" if key in report.attrib else key] = value
    if tomorrow is not None and collapse(tomorrow.text or ""):
        extra["tomorrow"] = collapse(tomorrow.text or "")
    unknown = {child.tag for child in report} - {"orgname", "detail", "tomorrow"}
    if unknown:
        raise ShapeError(f"a FlashAlert report has unexpected elements {sorted(unknown)}")
    if not name:
        return None
    when = collapse(report.attrib.get("last_update", "")) or updated
    return ParsedRow(name=name, status=status, updated_text=when or None, extra=extra)


def parse_xml(body: bytes) -> Listing:
    """Read a FlashAlert emergency XML feed (``flashalert-emergency-xml``)."""
    try:
        # The standard parser fetches no external entity, and the expat it uses (2.4
        # and later) refuses entity-expansion attacks.
        root = ElementTree.fromstring(body)  # noqa: S314
    except ElementTree.ParseError as error:
        raise ShapeError(f"the FlashAlert feed is not XML: {error}") from error
    if root.tag != "flashnews":
        raise ShapeError(f"the FlashAlert feed's root is {root.tag!r}, not flashnews")
    updated = collapse(root.attrib.get("updated", ""))
    rows: list[ParsedRow] = []
    skipped = 0
    for emergency in root:
        if emergency.tag != "emergency":
            raise ShapeError(f"the FlashAlert feed holds a {emergency.tag!r} element")
        for category in emergency:
            if category.tag != "emergency_category":
                raise ShapeError(f"a FlashAlert emergency holds a {category.tag!r} element")
            name = collapse(category.attrib.get("name", "")) or None
            for report in category:
                if report.tag != "emergency_report":
                    raise ShapeError(f"a FlashAlert category holds a {report.tag!r} element")
                row = _report_row(report, name, updated)
                if row is None:
                    skipped += 1
                else:
                    rows.append(row)
    if skipped and not rows:
        raise ShapeError("every FlashAlert report is missing its organization name")
    return Listing(
        variant="flashalert-emergency-xml",
        state=ListingState.POPULATED if rows else ListingState.EMPTY,
        rows=tuple(rows),
        skipped_rows=skipped,
    )


def _site_text(fragment: str) -> str:
    return collapse(unescape(_TAG.sub(" ", fragment)))


def _inner(html: str, start: int, tag: str = "div") -> str:
    """The markup inside the element that opens at ``start``."""
    end = element_end(html, start, tag)
    return html[html.index(">", start) + 1 : html.rindex("<", start, end)]


def _site_clean(fragment: str) -> tuple[str, str | None]:
    """A report's markup without its logo, notes and "Posted" time (returned apart)."""
    posted = _POSTED.search(fragment)
    fragment = _POSTED.sub(" ", _COMMENT.sub(" ", _LOGO.sub(" ", fragment)))
    return fragment, _site_text(posted.group(2)) if posted is not None else None


def _site_name(fragment: str) -> tuple[str, str, bool]:
    """Split a report into its name, what follows it and whether the name is a link."""
    linked = _LINKED.match(fragment)
    if linked is not None:
        return _site_text(linked.group("name")), _site_text(linked.group("rest")), True
    text = _site_text(_BULLET.sub("", fragment))
    name, dash, rest = text.partition(" - ")
    if not dash:
        raise ShapeError(f"a FlashAlert site report has no ' - ' after its name: {text[:60]!r}")
    return name.strip(), "- " + rest.strip(), False


type _Report = tuple[str, str, bool, str | None]
"""A site report's name, what follows it, whether the name is a link, and its "Posted" time."""


def _site_report(kind: str, inner: str) -> _Report | None:
    """Read one row element; ``None`` for the empty-state sentence."""
    if kind == "cwcReportLR":
        left, right = _SITE_LEFT.search(inner), _SITE_RIGHT.search(inner)
        if left is None or right is None:
            raise ShapeError("a FlashAlert site row has no name or no status side")
        status_part, posted = _site_clean(_inner(inner, right.start()))
        name, after, linked = _site_name(_inner(inner, left.start()) + " - ")
        if after.strip("- "):
            raise ShapeError("a FlashAlert site row's name side holds more than a name")
        status = _site_text(status_part)
        return name, f"- {status}" if status else "", linked, posted
    cleaned, posted = _site_clean(inner)
    if _site_text(cleaned) == SITE_EMPTY:
        return None
    name, rest, linked = _site_name(cleaned)
    return name, rest, linked, posted


def _site_row(report: _Report, heading: tuple[str | None, int | None], header: str) -> ParsedRow:
    name, rest, linked, posted = report
    category, count = heading
    if not name:
        raise ShapeError("a FlashAlert site report has no name")
    if rest and not rest.startswith("-"):
        raise ShapeError(f"a FlashAlert site report's name is not followed by '- ': {rest[:40]!r}")
    extra: dict[str, JsonScalar] = {"updated_scope": "page", "name_linked": linked}
    if category is not None:
        extra["category"] = category
    if count is not None:
        extra["category_count"] = count
    if posted is not None:
        extra["posted"] = posted
    return ParsedRow(
        name=name, status=rest.removeprefix("-").strip(), updated_text=header, extra=extra
    )


def parse_site(html: str) -> Listing:
    """Read a regional site's emergency reports page (``flashalert-site-page``)."""
    header = _SITE_HEADER.search(html)
    body = _SITE_BODY.search(html)
    if header is None or body is None:
        raise ShapeError("a FlashAlert site page with no report header or body")
    updated = _site_text(header.group(2))
    content = _inner(html, body.start())
    rows: list[ParsedRow] = []
    empty = False
    heading: tuple[str | None, int | None] = (None, None)
    position = 0
    for token in _SITE_TOKEN.finditer(content):
        if token.start() < position:
            continue  # inside an element already read
        position = element_end(content, token.start(), "div")
        inner = _inner(content, token.start())
        if token.group("cls").startswith("cwcReportCat"):
            count = _GROUP_COUNT.search(inner)
            heading = (
                _site_text(_ICON.sub(" ", _GROUP_COUNT.sub(" ", inner))),
                int(count.group(2)) if count is not None else None,
            )
            continue
        report = _site_report(token.group("cls"), inner)
        if report is None:
            empty = True
            continue
        rows.append(_site_row(report, heading, updated))
    if rows and empty:
        raise ShapeError("a FlashAlert site page lists rows and says nothing is reported")
    if rows:
        return Listing(
            variant="flashalert-site-page", state=ListingState.POPULATED, rows=tuple(rows)
        )
    if empty and heading[0] is None:
        return Listing(variant="flashalert-site-page", state=ListingState.EMPTY, rows=())
    raise ShapeError("a FlashAlert site page with no rows and no empty-state sentence")


def parse(body: bytes) -> Listing:
    """Read a FlashAlert region report, regional site page or emergency feed."""
    raw = decode(body)
    if _is_xml(raw):
        return parse_xml(raw)
    head = raw[:6000].decode("latin-1")
    if _SITE_TITLE.search(head):
        return parse_site(raw.decode("utf-8") if _is_utf8(raw) else raw.decode("cp1252", "replace"))
    if gray_files.is_file(raw):
        listing = gray_files.parse(raw)
        if listing.variant == "gray-file-flashalert":
            return listing
    raise ShapeError("not a FlashAlert report or feed this adapter knows")
