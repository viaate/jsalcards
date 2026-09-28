"""Sinclair stations' closings: the NewsTicker files their pages frame, and the Chameleon ticker.

A Sinclair station's closings page (``https://{site}/weather/closings``) holds no
list. Since 2023 it is a Next.js page whose server payload carries a
``NewsCustomPage_htmlEmbed`` block with an ``<iframe>``; the frame shows the list.
Variants this adapter reads:

``sinclair-next-page``
    The Next.js page. The embed's ``html`` (a JSON string inside the page's
    script payload) frames either the station's NewsTicker export on its own host
    (``/resources/ftptransfer/{call}/closings/closings.html`` and similar names,
    41 stations), WBFF's copy on ``ftptransfer.sinclairstoryline.com``, or a
    Chameleon display page (``sbgcg.com/Ticker/Stations/KATV/closings.html``). A
    :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED` listing whose
    ``follows`` is the frame's ``src`` as the page writes it (a list file's frame
    first when the embed has several; frames inside HTML comments are not shown,
    so not read). The ``html`` is either inline or, on pages captured in 2026
    (WCTI, WLOS, WWMT), a reference ``"$14"`` to a text chunk of the page's
    React Server Components stream (``14:T<hex byte length>,<html>``, pushed by
    ``self.__next_f.push([1, "..."])``), read from there. A page whose embed
    frames nothing raises :class:`~snowlight.sources.stations.model.ShapeError`
    (WWHO's and KFDM's pages, which show no list).

``sinclair-facade-page``
    The page shell some stations served in 2025 (``sinclairDigital.siteSlug = "..."``;
    captures of WSTM, KMPH, WEYI, WPBN, WJAC, WSBT and KYUU-LD, August to December
    2025). It renders its sections by script from ``sinclairDigital.facade``, where
    the closings page's iframe presentation carries its markup base64-encoded
    (``"data":{"injectedMarkup":"PGI+PGgzPjxw..."}``); decoded, that markup frames
    the station's list file
    (``<iframe ... src="/resources/ftptransfer/wstm/closings/closings.htm">``).
    ``DEFERRED``, following the frame as the markup writes it (a list file's frame
    first, as for the Next.js page). The shells of 2022 (captures of WHAM, WSYX,
    KMPH, KOMO and the partner stations) write the same markup as a plain JSON
    string (``"injectedMarkup":"<iframe src=\\"\\/resources\\/ftptransfer\\/wham..."``),
    read the same way. A shell whose markups frame nothing raises
    :class:`~snowlight.sources.stations.model.ShapeError`.

``sinclair-frame-page``
    An older station page (before the Next.js sites) that frames the same file
    in its HTML: ``<iframe src=".../resources/ftptransfer/..."`` or a Chameleon
    page. ``DEFERRED``, following the frame.

``newsticker-html`` and ``closings-grid``
    The framed files themselves, read by :mod:`snowlight.sources.stations.newsticker`
    (most stations' files are NewsTicker exports; WJAC's, WSBT's, WTOV's, WCYB's and
    KRCG's are "Closings Last Updated at" grids).

``closings-paragraphs``
    WBFF's earlier list file (``foxbaltimore.com/resources/ftptransfer/wbff/closings/closings.htm``,
    2016 to 2023), read by :mod:`snowlight.sources.stations.newsticker`.

``allen-header-table``
    KATV's earlier list file (``katv.com/resources/ftptransfer/katv/closings/closings.html``,
    captures of 2016 to 2025; the station's page framed it on 2023-02-02): the header
    table Allen's KIMT file also has, read by
    :func:`snowlight.sources.stations.allen.read_header_table` (the time in the
    first heading, then "Location" and "Status" headings and one row per
    organization; "THERE ARE CURRENTLY NO CLOSINGS OR CANCELLATIONS" when empty).

``cgs-all-active``
    KRCG's list file in 2018 (``WebClose.htm``, captured 2018-01-25), a CGS
    Infographics page, read by :mod:`snowlight.sources.stations.cgs`.

``sinclair-chameleon-page``
    The "Closings Display" page Sinclair's Chameleon ticker renders into (KATV's
    ``sbgcg.com`` page, WZTV's ``/resources/ftptransfer/wztv/closings/report.html``):
    a script application whose data address is written base64-encoded
    (``const jsonUrl = atob('...')``). ``DEFERRED``, following the decoded address
    (the Chameleon query, which carries the page's own public key).

``chameleon-json``
    The Chameleon query's answer: ``{"generated": ..., "bladeQueryItem": [...]}``
    or ``{"closingGroup": {"closingList": [...]}}`` (the display page reads
    either). Each item is a row: ``institution_name`` (else ``name``) is the name,
    ``statusName`` the status and ``lastModified`` the update text, as the display
    page shows them; every other field goes in ``raw_extra`` under its own name.
    An empty list is the empty state (the display page then says "NO CLOSINGS AT
    THIS TIME.").

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`.
"""

import base64
import binascii
import json
import re
from collections.abc import Mapping

from snowlight.sources.stations import allen, cgs, newsticker
from snowlight.sources.stations.body import decode
from snowlight.sources.stations.model import Listing, ParsedRow, ShapeError
from snowlight.sources.stations.regional import (
    deferred,
    document,
    extra_from,
    html_text,
    json_body,
    listing,
    looks_like_json,
    row,
    text_field,
)

NEXT_PAGE = "sinclair-next-page"
FACADE_PAGE = "sinclair-facade-page"
FRAME_PAGE = "sinclair-frame-page"
CHAMELEON_PAGE = "sinclair-chameleon-page"
CHAMELEON_JSON = "chameleon-json"

_EMBED = "NewsCustomPage_htmlEmbed"
_EMBED_HTML = re.compile(r'NewsCustomPage_htmlEmbed[^"\\]*\\*"\s*,\s*\\*"html\\*"\s*:\s*\\*"')
_IFRAME_SRC = re.compile(r"<iframe\b[^>]*?\bsrc\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
_LIST_FRAME = re.compile(
    r"/resources/ftptransfer/|ftptransfer\.sinclairstoryline\.com/|sbgcg\.com/Ticker/",
    re.IGNORECASE,
)
_ATOB = re.compile(r"const\s+jsonUrl\s*=\s*atob\(\s*'([A-Za-z0-9+/=]+)'\s*\)")
_CHAMELEON_TITLE = "<title>Closings Display</title>"
_ESCAPES = {"u003c": "<", "u003e": ">", "u0026": "&", "u0027": "'"}
_WINDOW = 4000
_EMBED_END = "presentationKey"
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_EMBED_REF = re.compile(r"\$([0-9a-f]+)\\*\"")
_PUSH = re.compile(r'self\.__next_f\.push\(\[1,\s*"((?:[^"\\]|\\.)*)"\]\)')
_SHELL = "sinclairDigital.siteSlug"
_SHELL_SLUG = re.compile(r"sinclairDigital\.siteSlug\s*=\s*\"([^\"]*)\"")
_INJECTED_KEY = re.compile(r'"injectedMarkup"\s*:\s*(?=")')
_BASE64 = re.compile(r"[A-Za-z0-9+/]+={0,2}")
_NAME_KEYS = ("institution_name", "name")
_ROW_KEYS = frozenset({"institution_name", "statusName", "lastModified"})


def _unescape_payload(fragment: str) -> str:
    """Undo the script payload's string escaping around an embed (backslashes, \\u00XX)."""
    text = fragment.replace("\\", "")
    for escaped, character in _ESCAPES.items():
        text = text.replace(escaped, character)
    return text


def _frame_in(html: str) -> str | None:
    """Return the frame an embed shows: a list file's first, else its first frame."""
    sources = [found.group(1) for found in _IFRAME_SRC.finditer(_COMMENT.sub("", html))]
    listed = [source for source in sources if _LIST_FRAME.search(source)]
    return (listed or sources or [None])[0]


def _rsc_stream(text: str) -> str:
    """Return the page's React Server Components stream: its pushed strings, in order."""
    try:
        return "".join(json.loads(f'"{push.group(1)}"') for push in _PUSH.finditer(text))
    except ValueError as error:
        raise ShapeError(f"the page's script payload is not JSON text: {error}") from error


def _rsc_text(stream: str, reference: str) -> str:
    """Return the stream's text chunk ``{reference}:T{hex byte length},{text}``."""
    found = re.search(rf"(?:^|\n){reference}:T([0-9a-f]+),", stream)
    if found is None:
        raise ShapeError(f"the page's closings embed refers to ${reference}, which it lacks")
    length = int(found.group(1), 16)
    raw = stream[found.end() :].encode()
    if len(raw) < length:
        raise ShapeError(f"the page's text chunk ${reference} is cut short")
    return raw[:length].decode(errors="replace")


def _embed_html(text: str, start: int) -> tuple[str, str | None]:
    """Return the embed's ``html`` beginning at ``start``, and its stream reference if any."""
    reference = _EMBED_REF.match(text, start)
    if reference is not None:
        return _rsc_text(_rsc_stream(text), reference.group(1)), reference.group(1)
    end = text.find(_EMBED_END, start, start + _WINDOW)
    return _unescape_payload(text[start : end if end > 0 else start + _WINDOW]), None


def _next_page(text: str) -> Listing:
    for match in _EMBED_HTML.finditer(text):
        frame = _frame_in(_embed_html(text, match.end())[0])
        if frame is not None:
            return deferred(NEXT_PAGE, (frame,))
    raise ShapeError("the page's closings embed frames no list file")


def _frame_page(text: str) -> Listing | None:
    for frame in _IFRAME_SRC.finditer(text):
        if _LIST_FRAME.search(frame.group(1)):
            return deferred(FRAME_PAGE, (frame.group(1),))
    return None


def _injected(text: str) -> list[tuple[str, str]]:
    """Return each ``injectedMarkup`` of a page shell's facade: (as written, the markup).

    The 2025 shells write the markup base64-encoded; the 2022 ones as a JSON string.
    """
    found: list[tuple[str, str]] = []
    for match in _INJECTED_KEY.finditer(text):
        try:
            value, _end = json.JSONDecoder().raw_decode(text, match.end())
        except ValueError as error:
            raise ShapeError(
                f"a page shell's injected markup is not a JSON string: {error}"
            ) from error
        if not isinstance(value, str):
            continue
        if _BASE64.fullmatch(value):
            try:
                markup = base64.b64decode(value, validate=True).decode("utf-8")
            except (binascii.Error, UnicodeDecodeError) as error:
                raise ShapeError(
                    f"a page shell's injected markup does not decode: {error}"
                ) from error
        else:
            markup = value
        found.append((value, markup))
    return found


def _facade_frame(text: str) -> tuple[str, str] | None:
    """Return the frame a page shell's markups show (a list file's first) and its markup."""
    framed = [(frame, raw) for raw, markup in _injected(text) if (frame := _frame_in(markup))]
    listed = [pair for pair in framed if _LIST_FRAME.search(pair[0])]
    return next(iter(listed or framed), None)


def _facade_page(text: str) -> Listing:
    found = _facade_frame(text)
    if found is None:
        raise ShapeError("a Sinclair page shell whose injected markup frames no list file")
    return deferred(FACADE_PAGE, (found[0],))


def _chameleon_page(text: str) -> Listing:
    match = _ATOB.search(text)
    if match is None:
        raise ShapeError("the Chameleon display page names no data address")
    try:
        url = base64.b64decode(match.group(1), validate=True).decode("ascii")
    except (binascii.Error, UnicodeDecodeError) as error:
        raise ShapeError(f"the Chameleon data address does not decode: {error}") from error
    if not url.startswith("https://"):
        raise ShapeError(f"the Chameleon data address is not an https URL: {url[:60]!r}")
    return deferred(CHAMELEON_PAGE, (url,))


def _chameleon_row(item: object) -> ParsedRow | None:
    if not isinstance(item, Mapping):
        raise ShapeError("a Chameleon closing is not an object")
    status = text_field(item, "statusName")
    if status is None:
        raise ShapeError("a Chameleon closing has no statusName")
    name = next((found for key in _NAME_KEYS if (found := text_field(item, key))), "")
    skip = _ROW_KEYS | ({"name"} if not text_field(item, "institution_name") else set())
    return row(name, status, text_field(item, "lastModified"), extra_from(item, skip))


def parse_chameleon(data: object) -> Listing:
    """Read a Chameleon query's answer (``chameleon-json``)."""
    if not isinstance(data, Mapping):
        raise ShapeError("the Chameleon answer is not an object")
    group = data.get("closingGroup")
    if isinstance(group, Mapping) and "closingList" in group:
        items = group["closingList"]
    elif "bladeQueryItem" in data:
        items = data["bladeQueryItem"]
    else:
        raise ShapeError("the Chameleon answer holds neither bladeQueryItem nor closingList")
    if not isinstance(items, list):
        raise ShapeError("the Chameleon closing list is not a list")
    rows: list[ParsedRow] = []
    skipped = 0
    for item in items:
        found = _chameleon_row(item)
        if found is None:
            skipped += 1
        else:
            rows.append(found)
    return listing(CHAMELEON_JSON, rows, skipped=skipped)


def read_page(text: str) -> Listing | None:
    """Read a Sinclair station page that frames its list (Next.js, page shell or older).

    Returns the :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED`
    listing following the framed file, or None when ``text`` is none of those pages.
    Other adapters use it for archived captures of pages Sinclair once ran.

    Raises:
        ShapeError: the page is one of them but frames no list file.
    """
    if _EMBED in text:
        return _next_page(text)
    framed = _frame_page(text)
    if framed is not None:
        return framed
    if _SHELL in text:
        return _facade_page(text)
    return None


def parse(body: bytes) -> Listing:
    """Read a Sinclair closings page, the file it frames, or the Chameleon ticker."""
    if looks_like_json(body):
        return parse_chameleon(json_body(body))
    found = newsticker.read_file(body)
    if found is not None:
        return found
    text = html_text(body)
    cgs_page = cgs.read_page(text)
    if cgs_page is not None:
        return cgs_page
    header = allen.read_header_table(text)
    if header is not None:
        return header
    if _CHAMELEON_TITLE in text:
        return _chameleon_page(text)
    page = read_page(text)
    if page is not None:
        return page
    raise ShapeError("not a Sinclair closings page, NewsTicker file or Chameleon answer")


def slice_body(body: bytes) -> bytes:
    """Cut a body to what the adapter reads, for a test fixture.

    A list file or a Chameleon answer is kept whole; a Next.js page keeps its
    closings embed (the payload string from the embed's name to the end of its
    ``html``), and a Chameleon display page its data address line.
    """
    listing_read = parse(body)
    text = html_text(body)
    if listing_read.variant == NEXT_PAGE:
        match = next(
            m for m in _EMBED_HTML.finditer(text) if _frame_in(_embed_html(text, m.end())[0])
        )
        html, reference = _embed_html(text, match.end())
        if reference is not None:
            head = json.dumps(f'"className":"{_EMBED}","html":"${reference}"')
            chunk = f"\n{reference}:T{len(html.encode()):x},{html}"
            pushes = [
                f"self.__next_f.push([1,{head}])",
                f"self.__next_f.push([1,{json.dumps(chunk)}])",
            ]
            return document("".join(f"<script>{push}</script>" for push in pushes))
        end = text.find(_EMBED_END, match.end())
        stop = end + len(_EMBED_END) if end > 0 else match.end() + _WINDOW
        piece = text[match.start() : stop]
        return document(f"<script>{piece}</script>")
    if listing_read.variant == FACADE_PAGE:
        slug = _SHELL_SLUG.search(text)
        framed = _facade_frame(text)
        injected = framed[1] if framed is not None else ""
        shell = f'{_SHELL} = "{slug.group(1) if slug is not None else ""}";'
        facade = f'sinclairDigital.facade = {{"data":{{"injectedMarkup":{json.dumps(injected)}}}}};'
        return document(f"<script>{shell}\n{facade}</script>")
    if listing_read.variant == CHAMELEON_PAGE:
        found = _ATOB.search(text)
        line = found.group(0) if found is not None else ""
        return document(f"{_CHAMELEON_TITLE}<script>{line};</script>")
    if listing_read.variant == FRAME_PAGE:
        frame = next(m for m in _IFRAME_SRC.finditer(text) if _LIST_FRAME.search(m.group(1)))
        return document(f'<iframe src="{frame.group(1)}"></iframe>')
    return decode(body)
