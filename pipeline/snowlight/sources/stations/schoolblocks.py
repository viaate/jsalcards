"""SchoolBlocks school district sites: the organization's alerts, in the homepage's own payload.

SchoolBlocks (a Next.js site builder for districts) carries district sites in the gap
states: Browning (MT), Uinta #1 and Sublette #1 (WY), Salmon, North Gem and Grace (ID),
and Alice, Industrial and Skidmore-Tynan (TX). The homepage is rendered on the server
and carries the district's organization record in its React Server Components payload,
the strings the page passes to ``self.__next_f.push([1, "..."])``. That record has an
``alerts`` list, which the site's notification component shows over the page (as an
``overlay``) or across it (as a ``banner``). Because the payload is in the page as
served, archived captures of the homepage hold the alerts too.

Variant this adapter reads:

``schoolblocks-org-alerts``
    The decoded payload's ``"alerts": [...]``, a JSON array of::

        {"id": 28295,
         "message": "<p>Grace School District will be closed from September 11-October 4
                     for potato harvest break. ...</p>",
         "type": "overlay"}

    Seen live on 2026-09-28: Grace School District #148's harvest-break closure; the
    other eight district sites' lists were ``[]`` (an empty list).

Each alert is one row: ``raw_name`` the site's name (the page title after "Home - ",
"Grace School District #148"; the alert names no school, and the registry entry's
``leaids`` say whose it is), ``raw_status`` the message's text (its HTML read as text),
no ``raw_updated_text`` (the record gives no time), and ``raw_extra`` ``alert_id`` and
``alert_type``. An alert whose message has no words is a skipped row. A body without
the payload or without an ``alerts`` list (another CMS, a bot challenge), an ``alerts``
value that is not a list, or an alert without an ``id`` raises
:class:`~snowlight.sources.stations.model.ShapeError`.
"""

import json
import re
from html import escape

from selectolax.parser import HTMLParser

from snowlight.sources.stations.gap_markup import collapse, html_text, make_listing, make_row
from snowlight.sources.stations.model import JsonScalar, Listing, ParsedRow, ShapeError

VARIANT = "schoolblocks-org-alerts"
_PUSH = re.compile(r"self\.__next_f\.push\((\[.*?\])\)\s*;?\s*</script>", re.S)
_KEY = '"alerts":'
_ALERTS = re.compile(r'"alerts"\s*:\s*')


def _payload(text: str) -> str:
    """Return the page's React Server Components payload, its string chunks joined."""
    chunks: list[str] = []
    for raw in _PUSH.findall(text):
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(item, list) and len(item) > 1 and isinstance(item[1], str):
            chunks.append(item[1])
    return "".join(chunks)


def _alert_lists(payload: str) -> list[tuple[int, int, object]]:
    """Return each ``"alerts":`` value in the payload, with where its JSON starts and ends."""
    found: list[tuple[int, int, object]] = []
    decoder = json.JSONDecoder()
    match = _ALERTS.search(payload)
    while match is not None:
        at = match.end()
        try:
            value, end = decoder.raw_decode(payload, at)
        except json.JSONDecodeError as error:
            raise ShapeError(f"the alerts value does not parse: {error}") from error
        found.append((at, end, value))
        match = _ALERTS.search(payload, end)
    return found


def _site_name(tree: HTMLParser) -> str:
    title = tree.css_first("title")
    text = collapse(title.text()) if title is not None else ""
    name = text.split(" - ", 1)[1] if text.startswith("Home - ") else text
    if not name:
        raise ShapeError("the SchoolBlocks page has no title to name the district by")
    return name


def _row(name: str, alert: object) -> ParsedRow | None:
    if not isinstance(alert, dict) or alert.get("id") is None:
        raise ShapeError("an alert is not an object with an id")
    message = alert.get("message")
    words = ""
    if isinstance(message, str) and message.strip():
        fragment = HTMLParser(message)
        for junk in fragment.css("style, script"):
            junk.decompose()
        body = fragment.body
        words = collapse(body.text(deep=True, separator=" ")) if body is not None else ""
    if not words:
        return None
    kind = alert.get("type")
    extra: dict[str, JsonScalar] = {
        "alert_id": str(alert["id"]),
        "alert_type": kind if isinstance(kind, str) else None,
    }
    return make_row(name, words, None, extra)


def parse(body: bytes) -> Listing:
    """Read a SchoolBlocks district homepage's alerts (see the module docstring)."""
    text = html_text(body)
    payload = _payload(text)
    if not payload:
        raise ShapeError("no self.__next_f payload: not a SchoolBlocks page")
    lists = _alert_lists(payload)
    if not lists:
        raise ShapeError("the payload has no alerts list: not a SchoolBlocks organization page")
    name = _site_name(HTMLParser(text))
    rows: list[ParsedRow] = []
    skipped = 0
    seen: set[str] = set()
    for _, _, value in lists:
        if not isinstance(value, list):
            raise ShapeError("the alerts value is not a list")
        for alert in value:
            row = _row(name, alert)
            if row is None:
                skipped += 1
                continue
            key = str(row.extra["alert_id"])
            if key not in seen:
                seen.add(key)
                rows.append(row)
    return make_listing(VARIANT, rows, skipped=skipped)


def slice_body(body: bytes) -> bytes:
    """Keep the page title and each ``"alerts":`` value of the payload (for fixtures).

    The slice is a minimal document whose one payload chunk holds the alerts lists as
    the page wrote them; it reads exactly as the page does, and slicing it again changes
    nothing. A page without the payload slices to its title alone.
    """
    text = html_text(body)
    tree = HTMLParser(text)
    title = tree.css_first("title")
    head = ""
    if title is not None:
        head = f"<title>{escape(collapse(title.text()), quote=False)}</title>"
    payload = _payload(text)
    spans = _alert_lists(payload) if payload else []
    kept = ",".join(_KEY + payload[at:end] for at, end, _ in spans)
    script = ""
    if kept:
        script = f"<script>self.__next_f.push({json.dumps([1, '{' + kept + '}'])})</script>"
    return f"<!DOCTYPE html><html><head>{head}</head><body>{script}</body></html>\n".encode()
