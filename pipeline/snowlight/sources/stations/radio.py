"""Independent radio stations' closings pages: KXXO Mixx 96.1 (Olympia, WA).

KXXO's "School Closings" page (``https://www.kxxo.com/list-school-closings/``,
a WordPress page) frames its main list, a file on its own server,
``//www.kxxo.com/kxxo-sftp/school_closures.html``: FlashAlert Newswire's
Seattle/Western Washington report, which FlashAlert writes there ("Info provided
by FlashAlert Newswire", with a link to FlashAlert's participants of region 12).
Variants this adapter reads, as the archived captures of 2020 to 2026 show
(archive-captures runs 36354877675 and 36357297115; the site does not answer from
the build environment):

``kxxo-page``
    The WordPress page: its ``article`` frames the report
    (``<iframe ... src="//www.kxxo.com/kxxo-sftp/school_closures.html">``, every
    capture from 2020-11-27 to 2026-03-06). A
    :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED` listing that
    follows the frame (as the page names it). Below the frame the station keeps
    free-text notes under "Additional Closings, etc." ("Northwest Christian
    Schools of Lacey UPDATE: Closed", 2022-01-04); they are edited by hand and
    stay up long after the day they name (a note of Friday 2/12/21 is still on
    the page on 2021-12-04), so they are not read as rows.

``flashalert-copy``
    The framed report. ``div#cwcReportHeader`` names the region and the time of
    the report ("Seattle/Western Wash. Emergency Info for Tue. Jan. 4 - 8:30 am");
    ``div#cwcReportBody`` holds, after its sub-header, one ``div.cwcReportCat``
    per category ("King Co. School Districts") and one ``div.cwcReport`` per
    organization under it, as the capture of 2022-01-04 16:36 UTC shows::

        <div class='cwcReport'><strong>Auburn SD</strong>&nbsp;- 2 Hours Late, No preschool,
          ... <strong>UPDATE</strong></div>

    The first ``strong`` is the name and the text after its " - " the status (a
    trailing ``<strong>UPDATE</strong>`` marker is left out of it and kept as
    ``raw_extra["marked_update"]``); the category goes in
    ``raw_extra["category"]`` and the header's time ("Tue. Jan. 4 - 8:30 am") is
    each row's update text (``raw_extra["updated_scope"]`` is ``"page"``, and the
    region is ``raw_extra["region"]``). A body whose only entry is "No
    information reported." (captures of 2021 to 2026) is the empty state.

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`.
"""

import re

from selectolax.parser import HTMLParser, Node

from snowlight.sources.stations.model import MAX_STATUS, JsonScalar, Listing, ParsedRow, ShapeError
from snowlight.sources.stations.regional import (
    collapse,
    deferred,
    document,
    html_text,
    listing,
    node_text,
    row,
)

PAGE = "kxxo-page"
COPY = "flashalert-copy"
EMPTY_SENTENCE = "No information reported."
UPDATE_MARK = "UPDATE"
_FRAME = re.compile(
    r"<iframe\b[^>]*?\bsrc=\"((?:https?:)?//www\.kxxo\.com/kxxo-sftp/[^\"]+\.html?)\"",
    re.IGNORECASE,
)
_HEADER = re.compile(r"^(?P<region>.+?) Emergency Info for (?P<when>.+)$")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def _classes(node: Node) -> set[str]:
    return set((node.attributes.get("class") or "").split())


def _children(node: Node) -> list[Node]:
    found: list[Node] = []
    child = node.child
    while child is not None:
        if child.tag not in {"-text", "_comment"}:
            found.append(child)
        child = child.next
    return found


def _entry(entry: Node, category: str | None, region: str, when: str) -> ParsedRow | None:
    marks = entry.css("strong")
    if not marks:
        raise ShapeError(f"a FlashAlert report entry names no organization: {node_text(entry)!r}")
    name = node_text(marks[0])
    text = node_text(entry)
    if not text.startswith(name):
        raise ShapeError(f"a FlashAlert report entry does not start with its name: {text[:60]!r}")
    status = text.removeprefix(name).strip()
    if not status.startswith("-"):
        raise ShapeError(f"a FlashAlert report entry has no ' - ' after its name: {text[:60]!r}")
    status = status.removeprefix("-").strip()
    extra: dict[str, JsonScalar] = {"region": region, "updated_scope": "page"}
    if len(marks) > 1:
        if len(marks) != 2 or node_text(marks[1]) != UPDATE_MARK:  # noqa: PLR2004
            raise ShapeError("a FlashAlert report entry holds marks this adapter has not seen")
        status = status.removesuffix(UPDATE_MARK).strip()
        extra["marked_update"] = True
    if category:
        extra["category"] = category
    if len(status) > MAX_STATUS:
        status = status[: MAX_STATUS - 1] + "…"
    return row(name, status, when, extra)


def _copy(tree: HTMLParser) -> Listing:
    header = tree.css_first("div#cwcReportHeader")
    body = tree.css_first("div#cwcReportBody")
    if header is None or body is None:
        raise ShapeError("not a FlashAlert report (no header or body)")
    heading = _HEADER.match(node_text(header))
    if heading is None:
        raise ShapeError(f"a FlashAlert report header of another form: {node_text(header)!r}")
    region, when = heading.group("region"), heading.group("when")
    rows: list[ParsedRow] = []
    skipped = 0
    empty = False
    category: str | None = None
    for child in _children(body):
        classes = _classes(child)
        if child.attributes.get("id") == "cwcReportSubHeader":
            continue
        if "cwcReportCat" in classes:
            category = node_text(child)
        elif "cwcReport" in classes:
            if node_text(child) == EMPTY_SENTENCE:
                empty = True
                continue
            found = _entry(child, category, region, when)
            if found is None:
                skipped += 1
            else:
                rows.append(found)
        else:
            raise ShapeError(f"a FlashAlert report body holds a <{child.tag}>")
    if empty and (rows or skipped):
        raise ShapeError("a FlashAlert report lists entries and says nothing is reported")
    if not empty and not rows and not skipped:
        raise ShapeError("a FlashAlert report with no entry and no empty line")
    return listing(COPY, rows, skipped=skipped)


def parse(body: bytes) -> Listing:
    """Read KXXO's closings page (it frames the report) or the FlashAlert report it frames."""
    text = html_text(body)
    tree = HTMLParser(text)
    if tree.css_first("div#cwcReportContainer") is not None:
        return _copy(tree)
    frames = _FRAME.findall(_COMMENT.sub("", text))
    if frames:
        return deferred(PAGE, tuple(dict.fromkeys(frames)))
    raise ShapeError("not KXXO's closings page or the FlashAlert report it frames")


def slice_body(body: bytes) -> bytes:
    """Keep the page's frame, or the report's header and body."""
    found = parse(body)
    if found.variant == PAGE:
        return document("".join(f'<iframe src="{url}"></iframe>' for url in found.follows))
    tree = HTMLParser(html_text(body))
    header = tree.css_first("div#cwcReportHeader")
    report = tree.css_first("div#cwcReportBody")
    inner = (header.html or "") + (report.html or "") if header and report else ""
    return document(f"<div id='cwcReportContainer'>{collapse(inner)}</div>")
