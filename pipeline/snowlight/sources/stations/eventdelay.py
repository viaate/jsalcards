"""EventDelay closings widgets (Envisionwise): WDEL's SnoWatch channel.

WDEL's SnoWatch page (``https://www.wdel.com/features/wdel-stormwatch/``) frames
EventDelay's widget for its channel 114 ("Wilmington"), which the server writes
whole. The widget has two display modes on one list: ``.../channel/114/list/``
(``<body class="widget widget-channel mode-list">``), which the page framed from
2024 to December 2025 (captures of 2025-01-08 and 2025-01-18), and
``.../channel/114/page`` (``mode-page``), which it frames since (captures of
2026-01-24 and the live page of 2026-09-27). Both still answer (live 2026-09-27)
and show the same days. Variants this adapter reads:

``eventdelay-list`` and ``eventdelay-widget``
    The widget in list mode and in page mode. One section per day for the coming
    days, each an ``h3.date-label`` ("Wednesday, January 8th"). A day with nothing
    listed shows "There are no closings to display at this time." (list mode:
    ``p.notice``; page mode: ``p.no-closings``). A day with closings holds a
    ``dl.closing_list`` in which each ``dt.org_type`` names a category
    ("Schools", "College / Adult Ed.", "Community") and each ``dd.closing`` after
    it is one organization, as the list-mode captures of the storm days
    2025-01-08 (8 of them) and 2025-01-18 (1) show::

        <dd class="closing"><h3 >Capital School District</h3>
          <p class="status"><label>Status: </label><strong>Asynchronous learning </strong></p>
          <p class="status"><strong>01-08-2025</strong> through <strong>01-08-2025</strong></p>
          <p class="details"><!--<label>Additional Details: </label>--></p>
          <p class="last_updated"><label>Posted </label>Tue, 01-7-25, 3:58pm</p></dd>

    Each ``dd.closing`` is a row: the ``h3`` is the name, the first
    ``p.status`` without its "Status:" label the status, and the
    ``p.last_updated`` text without its "Posted" label the update text
    (``raw_extra["updated_scope"]`` is ``"row"``); the day label (``day``), the
    category (``category``), the date range (``dates``, "01-08-2025 through
    01-08-2025"), the details (``details``, when any) and the widget's time zone
    (``timezone``, its ``p.timezone-label``, "America/New_York") go in
    ``raw_extra``. Commented-out markup (the template keeps a
    ``<dd class="notice">`` for empty categories in a comment) is not read. Every
    day showing its empty line is the empty state. A list-mode day that holds
    anything but its empty line or this ``dl.closing_list`` markup raises
    :class:`~snowlight.sources.stations.model.ShapeError`. Page mode has only been
    seen with every day empty, and its template closes a table (``</tbody>
    </table>``, with a tablesorter script) after each day, so it writes rows in a
    table never seen: a page-mode day holding anything but its empty line raises
    too. The live poller reads list mode (see the registry entry).

``eventdelay-page``
    WDEL's SnoWatch page itself (a TownNews BLOX page), which holds no list and
    frames the one it shows: the EventDelay widget
    (``<iframe ... src="https://www.eventdelay.com/new/widget/channel/114/list/">``
    in January 2025, ``src="https://eventdelay.com/new/widget/channel/114/page"``
    since) or, before EventDelay, the SnoWatch list
    (``<iframe src="https://foreverdigitalmedia.com/wdel/snowatch.php" ...>``; on
    ``delmarvabroadcasting.com`` in the capture of 2018-01-04, on
    ``foreverdigitalmedia.com`` in that of 2021-02-01). Since 2025 the page keeps
    the SnoWatch frame inside an HTML comment; frames in comments are not
    followed. A :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED`
    listing whose ``follows`` are the framed lists, the EventDelay widget first.
    This adapter reads ``snowatch.php`` itself with
    :mod:`snowlight.sources.stations.snowatch` (variants ``snowatch-index`` and
    ``snowatch-category``, from its captures of 2018 to 2021).

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`.
"""

import re

from selectolax.parser import HTMLParser, Node

from snowlight.sources.stations import snowatch
from snowlight.sources.stations.model import JsonScalar, Listing, ParsedRow, ShapeError
from snowlight.sources.stations.regional import (
    collapse,
    deferred,
    document,
    html_text,
    listing,
    node_text,
    row,
)

VARIANT = "eventdelay-widget"
LIST = "eventdelay-list"
PAGE = "eventdelay-page"
EMPTY_SENTENCE = "There are no closings to display at this time."
STATUS_LABEL = "Status:"
POSTED_LABEL = "Posted"
STATUS_LINES = 2
"""A closing's ``p.status`` lines: the status, then (usually) its date range."""
_MODES = {"mode-page": (VARIANT, "no-closings"), "mode-list": (LIST, "notice")}
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_WIDGET_FRAME = re.compile(
    r"<iframe\b[^>]*?\bsrc=\"(https://(?:www\.)?eventdelay\.com/new/widget/channel/[0-9]+/"
    r"(?:page|list/?))\"",
    re.IGNORECASE,
)
_SNOWATCH_FRAME = re.compile(
    r"<iframe\b[^>]*?\bsrc=\"(https?://(?:www\.)?(?:delmarvabroadcasting|foreverdigitalmedia)"
    r"\.com/wdel/snowatch\.php)\"",
    re.IGNORECASE,
)


def _frames(text: str) -> tuple[str, ...]:
    """The lists a SnoWatch page frames outside comments: EventDelay widgets first."""
    live = _COMMENT.sub("", text)
    found = [collapse(m.group(1)) for m in _WIDGET_FRAME.finditer(live)]
    found += [collapse(m.group(1)) for m in _SNOWATCH_FRAME.finditer(live)]
    return tuple(dict.fromkeys(found))


def _children(node: Node) -> list[Node]:
    """The element children of ``node``, in order (text and comments left out)."""
    found: list[Node] = []
    child = node.child
    while child is not None:
        if child.tag not in {"-text", "_comment"}:
            found.append(child)
        child = child.next
    return found


def _labelled(paragraph: Node, label: str) -> str:
    """A paragraph's text without its leading ``<label>`` (which must read ``label``)."""
    found = paragraph.css_first("label")
    if found is None or node_text(found) != label:
        raise ShapeError(
            f"an EventDelay closing's {paragraph.attributes.get('class')} line "
            f"is not labelled {label!r}"
        )
    text = node_text(paragraph)
    return text.removeprefix(label).strip()


def _closing(entry: Node, day: str, category: str | None, zone: str | None) -> ParsedRow | None:
    names = entry.css("h3")
    statuses = entry.css("p.status")
    posted = entry.css("p.last_updated")
    details = entry.css("p.details")
    known = len(names) + len(statuses) + len(posted) + len(details)
    if (
        len(names) != 1
        or not 1 <= len(statuses) <= STATUS_LINES
        or len(posted) != 1
        or len(details) > 1
    ):
        raise ShapeError("an EventDelay closing without one name, status and posting time")
    if known != len(_children(entry)):
        raise ShapeError("an EventDelay closing holds markup this adapter has not seen")
    extra: dict[str, JsonScalar] = {"day": day}
    if category:
        extra["category"] = category
    if len(statuses) == STATUS_LINES:
        extra["dates"] = node_text(statuses[1])
    if details and node_text(details[0]):
        extra["details"] = node_text(details[0])
    updated = _labelled(posted[0], POSTED_LABEL) or None
    if updated:
        extra["updated_scope"] = "row"
    if zone:
        extra["timezone"] = zone
    return row(node_text(names[0]), _labelled(statuses[0], STATUS_LABEL), updated, extra)


def _closing_list(block: Node, day: str, zone: str | None) -> tuple[list[ParsedRow], int]:
    rows: list[ParsedRow] = []
    skipped = 0
    category: str | None = None
    for child in _children(block):
        if child.tag == "dt" and "org_type" in (child.attributes.get("class") or ""):
            category = node_text(child)
        elif child.tag == "dd" and "closing" in (child.attributes.get("class") or "").split():
            found = _closing(child, day, category, zone)
            if found is None:
                skipped += 1
            else:
                rows.append(found)
        else:
            raise ShapeError(f"an EventDelay closing list holds a <{child.tag}>")
    if not rows and not skipped:
        raise ShapeError("an EventDelay closing list with no closing in it")
    return rows, skipped


def _day_nodes(label: Node) -> list[Node]:
    """The element siblings after a day label, up to the next day label or the time zone."""
    found: list[Node] = []
    node = label.next
    while node is not None:
        classes = (node.attributes.get("class") or "").split() if node.tag != "-text" else []
        if node.tag == "h3" and "date-label" in classes:
            break
        if node.tag in {"div", "center"} and node.css_first("p.timezone-label") is not None:
            break  # the time zone line closes the last day (list mode: div; page mode: center)
        if node.tag not in {"-text", "_comment"}:
            found.append(node)
        node = node.next
    return found


def _classes(node: Node) -> set[str]:
    return set((node.attributes.get("class") or "").split())


def _empty_lines(nodes: list[Node], line_class: str) -> list[str]:
    """The empty-day lines among a day's nodes (the line itself, or inside a wrapper)."""
    found: list[str] = []
    for node in nodes:
        if node.tag == "p" and line_class in _classes(node):
            found.append(node_text(node))
        elif node.tag == "div":
            found += [node_text(p) for p in node.css(f"p.{line_class}")]
    return found


def _widget(tree: HTMLParser, mode: str) -> Listing:
    variant, line_class = _MODES[mode]
    zone_node = tree.css_first("p.timezone-label")
    zone = (node_text(zone_node) or None) if zone_node is not None else None
    rows: list[ParsedRow] = []
    skipped = 0
    for label in tree.css("h3.date-label"):
        day = node_text(label)
        nodes = _day_nodes(label)
        lists = [node for node in nodes if node.tag == "dl"]
        if lists and mode == "mode-list":
            spacers = [node for node in nodes if node.tag != "dl"]
            if any(node.tag not in {"p", "hr"} or node_text(node) for node in spacers):
                raise ShapeError(f"an EventDelay day ({day}) holds a list and something else")
            for block in lists:
                if "closing_list" not in _classes(block):
                    raise ShapeError(f"an EventDelay day ({day}) holds another kind of list")
                found, dropped = _closing_list(block, day, zone)
                rows += found
                skipped += dropped
            continue
        empties = _empty_lines(nodes, line_class)
        if empties != [EMPTY_SENTENCE] or len(nodes) != 1:
            raise ShapeError(
                f"an EventDelay day ({day}) shows something other than its empty line; "
                "only the list mode's closing lists have been seen with rows"
            )
    return listing(variant, rows, skipped=skipped)


def _mode(tree: HTMLParser) -> str | None:
    body = tree.css_first("body")
    classes = set((body.attributes.get("class") or "").split()) if body is not None else set()
    if not {"widget", "widget-channel"} <= classes:
        return None
    modes = classes & set(_MODES)
    if len(modes) != 1:
        raise ShapeError(f"an EventDelay widget in display mode {sorted(modes)}")
    return modes.pop()


def parse(body: bytes) -> Listing:
    """Read an EventDelay widget, the SnoWatch page that frames it, or the older SnoWatch list."""
    text = html_text(body)
    if snowatch.is_snowatch(text):
        return snowatch.parse(text)
    tree = HTMLParser(text)
    mode = _mode(tree)
    if mode is not None and tree.css("h3.date-label"):
        return _widget(tree, mode)
    frames = _frames(text)
    if frames:
        return deferred(PAGE, frames)
    raise ShapeError("not an EventDelay channel widget (no day sections) or a page framing one")


def slice_body_v1(body: bytes) -> bytes:
    """The first slicing method: a page's frames, or a page-mode widget's empty days.

    Kept unchanged for the fixtures that use it (every day of those widgets is empty).
    """
    found = parse(body)
    if found.variant in {snowatch.INDEX, snowatch.CATEGORY}:
        return snowatch.slice_text(html_text(body))
    if found.variant == PAGE:
        return document("".join(f'<iframe src="{url}"></iframe>' for url in found.follows))
    if found.variant != VARIANT or found.rows:
        raise ValueError("the eventdelay-v1 slice keeps only pages and page-mode widgets, empty")
    tree = HTMLParser(html_text(body))
    parts = []
    for label in tree.css("h3.date-label"):
        parts.append(f'<h3 class="date-label">{node_text(label)}</h3>')
        parts.append(f'<p class="no-closings"><em>{EMPTY_SENTENCE}</em></p>')
    return (
        '<!DOCTYPE html><html><body class="widget widget-channel mode-page">'
        f'<div id="body">{"".join(parts)}</div></body></html>\n'
    ).encode()


def slice_body(body: bytes) -> bytes:
    """Keep a page's live frames, or a widget's days as it shows them (the eventdelay-v2 slice).

    A widget keeps its mode, each day label with its empty line or closing list
    (comments dropped) and its time zone line.
    """
    found = parse(body)
    text = html_text(body)
    if found.variant in {snowatch.INDEX, snowatch.CATEGORY}:
        return snowatch.slice_text(text)
    if found.variant == PAGE:
        return document("".join(f'<iframe src="{url}"></iframe>' for url in found.follows))
    tree = HTMLParser(_COMMENT.sub("", text))
    mode = _mode(tree) or ""
    parts: list[str] = []
    for label in tree.css("h3.date-label"):
        parts.append(label.html or "")
        parts.extend(node.html or "" for node in _day_nodes(label))
    zone = tree.css_first("p.timezone-label")
    if zone is not None:
        parts.append(f"<div>{zone.html or ''}</div>")
    return (
        f'<!DOCTYPE html><html><body class="widget widget-channel {mode}">'
        f'<div id="body">{"".join(parts)}</div></body></html>\n'
    ).encode()
