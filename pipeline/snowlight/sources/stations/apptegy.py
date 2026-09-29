"""Apptegy (Thrillshare CMS) school district sites: the alert banner on the district homepage.

Many districts' websites are Apptegy's Thrillshare CMS (Hillsborough, Duval,
Brevard and 13 more county districts in Florida; Twin Falls, Cassia, Madison,
Fremont, Minidoka and American Falls in Idaho; Fremont #25, Johnson #1 and Converse
#2 in Wyoming). A district announces a
closure, a delay or an early dismissal in the site's alert banner (a strip or a
pop-up "light box" on the homepage): "HURRICANE MILTON UPDATE: All MCSD-operated
schools and offices will be closed Wednesday ..." (Martin County), "School is
closed due to Ice!" (Nassau County), still kept as drafts in the sites' state on
2026-09-27. The homepage is rendered on the server with the site's whole state,
so the banner is in the page as served (and in its archived captures).

Variants this adapter reads:

``apptegy-nuxt-state``
    The Nuxt 3 site (2025 on): a ``<script type="application/json"
    id="__NUXT_DATA__">`` payload in devalue's flat form, holding the Pinia stores.
    One store holds ``alertBannerConfig`` (the older single banner: ``enabled``,
    ``content``) and ``alertBannerSeparate`` (the list of banners, each with
    ``status``: draft, scheduled, published, archived or closed): a store of its own,
    ``alertBanner``, on the live pages of 2026; the ``main`` store in captures of
    2025 (where ``alertBanner`` is only the banner settings). Which the page shows
    follows Apptegy's own code: when the site's feature flag
    ``cms_separate_alert_banner_enabled`` is on, every banner whose ``status`` is
    ``published``; when it is off, the single banner if ``enabled``. (A store
    without the list, or a page without the flag, shows the list if the store has
    one, else the single banner.)

``apptegy-nuxt2-state``
    The Nuxt 2 site (2021 to 2024, in archived captures): the same state written as
    a script, ``window.__NUXT__=(function(a,b,...){...}(...))``, read with
    :mod:`snowlight.sources.stations.nuxt2` (never run). The same
    ``alertBannerConfig``, ``alertBannerSeparate`` and flag, the same choice of what
    is shown: Martin County's capture of 2024-10-09 shows its published banner
    "HURRICANE MILTON UPDATE: All MCSD-operated schools and offices will be closed
    Wednesday, October 9 - Friday, October 11"; its capture of 2022-09-28 (before the
    list existed) its enabled single banner, "Hurricane Ian Update".

``schoolwires-important-announcements``
    A capture of the homepage from before the district moved to Apptegy, when it was
    a Blackboard Web Community Manager site (Manatee, Monroe, Alachua): read by
    :mod:`snowlight.sources.stations.schoolwires`.

``campussuite-alert-banner``
    A capture of the homepage from before the district moved to Apptegy, when it was
    a Campus Suite site with the alert banner widget (Hardin, MT, 2022-12-21: "School
    Closure Wednesday, Dec. 21st 2022"): read by
    :mod:`snowlight.sources.stations.campussuite`.

Each banner shown is one row: ``raw_name`` the site's organization name (the
theme's ``school_name``, "Hillsborough County Public Schools"), ``raw_status`` the
banner's text (its HTML reduced to text), no ``raw_updated_text`` (banners carry
no time), and ``raw_extra`` ``alert_id``, ``style`` (banner or light_box),
``display_location``, ``banner`` (``separate`` or ``single``) and ``host`` (the
site), ``image_alt`` (the banner image's alt text, if any). A page whose state
shows no banner is an empty list: the district has no alert up. A banner shown
with neither text nor an image's alt text (an empty strip) is counted as a skipped
row, not read. Banners not shown (drafts, archived, closed) are never rows.

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`: a page
with no Nuxt state or no alert banner store (a redesign, or a page that is not an
Apptegy site, such as Hillsborough's and Duval's Blackboard homepages of 2024, which
have no announcements region), or a payload that does not unflatten.
"""

import json
import re
from collections.abc import Iterator
from typing import Any

from selectolax.parser import HTMLParser

from snowlight.sources.stations import campussuite, nuxt2, schoolwires
from snowlight.sources.stations.gap_markup import (
    collapse,
    document,
    html_text,
    make_listing,
    make_row,
)
from snowlight.sources.stations.model import JsonScalar, Listing, ParsedRow, ShapeError

NUXT_STATE = "apptegy-nuxt-state"
NUXT2_STATE = "apptegy-nuxt2-state"
_NUXT2 = re.compile(r"window\.__NUXT__\s*=\s*\(function\(")
SEPARATE_FLAG = "cms_separate_alert_banner_enabled"
SHOWN = "published"
_PAYLOAD = re.compile(
    r"<script\b[^>]*\bid=\"__NUXT_DATA__\"[^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE
)
# devalue's markers for values that are not stored in the table.
_UNDEFINED, _HOLE = -1, -2
_SPECIALS = {-3: float("nan"), -4: float("inf"), -5: float("-inf"), -6: -0.0}
_WRAPPERS = frozenset(
    {"Reactive", "ShallowReactive", "Ref", "ShallowRef", "EmptyRef", "EmptyShallowRef"}
)
MAX_DEPTH = 200


class _Flat:
    """devalue's flat form (an array of values that refer to each other by index), unflattened."""

    def __init__(self, table: list[Any]) -> None:
        self.table = table
        self.done: dict[int, Any] = {}

    def value(self, index: int, depth: int = 0) -> Any:
        if index in {_UNDEFINED, _HOLE}:
            return None
        if index in _SPECIALS:
            return _SPECIALS[index]
        if not 0 <= index < len(self.table):
            raise ShapeError(f"the Nuxt payload refers to a missing entry {index}")
        if index in self.done:
            return self.done[index]
        if depth > MAX_DEPTH:
            raise ShapeError("the Nuxt payload nests too deeply")
        raw = self.table[index]
        if isinstance(raw, dict):
            out: dict[str, Any] = {}
            self.done[index] = out
            for key, ref in raw.items():
                out[key] = self._ref(ref, depth)
            return out
        if isinstance(raw, list):
            return self._list(index, raw, depth)
        return raw

    def _ref(self, ref: object, depth: int) -> Any:
        if isinstance(ref, bool) or not isinstance(ref, int):
            raise ShapeError(f"the Nuxt payload holds a reference that is not an index: {ref!r}")
        return self.value(ref, depth + 1)

    def _list(self, index: int, raw: list[Any], depth: int) -> Any:
        if raw and isinstance(raw[0], str):
            kind = raw[0]
            if kind in _WRAPPERS:
                value = self._ref(raw[1], depth) if len(raw) > 1 else None
                self.done[index] = value
                return value
            if kind == "Date":
                return raw[1] if len(raw) > 1 else None
            if kind in {"Set", "Map", "null", "Object", "RegExp", "BigInt"}:
                # Not needed here, and never where the alert banners are.
                self.done[index] = None
                return None
            raise ShapeError(f"the Nuxt payload holds an unknown form {kind!r}")
        items: list[Any] = []
        self.done[index] = items
        items.extend(self._ref(ref, depth) for ref in raw)
        return items


def _walk(node: Any, seen: set[int] | None = None) -> Iterator[dict[str, Any]]:
    """Every mapping under ``node`` (each once)."""
    seen = set() if seen is None else seen
    stack = [node]
    while stack:
        item = stack.pop()
        if isinstance(item, dict | list):
            if id(item) in seen:
                continue
            seen.add(id(item))
        if isinstance(item, dict):
            yield item
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


def _state(text: str) -> dict[str, Any]:
    found = _PAYLOAD.search(text)
    if found is None:
        raise ShapeError("no __NUXT_DATA__ payload: not an Apptegy (Nuxt 3) page")
    try:
        table = json.loads(found.group(1))
    except ValueError as error:
        raise ShapeError(f"the __NUXT_DATA__ payload is not JSON: {error}") from error
    if not isinstance(table, list) or not table:
        raise ShapeError("the __NUXT_DATA__ payload is not devalue's flat form")
    root = _Flat(table).value(0)
    if not isinstance(root, dict):
        raise ShapeError("the Nuxt state is not a mapping")
    return root


def _banner_text(content: object) -> str:
    if content is None:
        return ""
    if not isinstance(content, str):
        raise ShapeError(f"a banner's content is not text: {content!r}"[:200])
    tree = HTMLParser(document(content).decode())
    return collapse(tree.body.text(separator=" ")) if tree.body is not None else ""


def _first(root: dict[str, Any], key: str) -> dict[str, Any] | None:
    for mapping in _walk(root):
        if key in mapping:
            return mapping
    return None


def _shown(store: dict[str, Any], flags: dict[str, Any] | None) -> list[tuple[str, dict[str, Any]]]:
    config = store.get("alertBannerConfig")
    separate = store.get("alertBannerSeparate")
    if config is not None and not isinstance(config, dict):
        raise ShapeError("the single alert banner is not a mapping")
    if separate is not None and not isinstance(separate, list):
        raise ShapeError("the alert banner list is not a list")
    flag = flags.get(SEPARATE_FLAG) if flags is not None else None
    use_list = bool(flag) if isinstance(flag, bool) else separate is not None
    if use_list:
        shown = [item for item in separate or [] if isinstance(item, dict)]
        return [("separate", item) for item in reversed(shown) if item.get("status") == SHOWN]
    if config is not None and config.get("enabled") is True:
        return [("single", config)]
    return []


def _image_alt(image: object) -> str | None:
    alt = image.get("alt_text") if isinstance(image, dict) else None
    return collapse(alt) or None if isinstance(alt, str) else None


def _row(name: str, host: str | None, kind: str, banner: dict[str, Any]) -> ParsedRow | None:
    text = _banner_text(banner.get("content"))
    extra: dict[str, JsonScalar] = {
        "alert_id": banner.get("id") if isinstance(banner.get("id"), int) else None,
        "style": banner.get("style") if isinstance(banner.get("style"), str) else None,
        "display_location": banner.get("display_location")
        if isinstance(banner.get("display_location"), str)
        else None,
        "banner": kind,
        "host": host,
        "image_alt": _image_alt(banner.get("image")),
    }
    if not text and extra["image_alt"] is None:
        return None  # a shown banner with no words (an empty strip): nothing to read
    return make_row(name, text, None, extra)


def _listing(
    variant: str,
    name: str,
    host: str | None,
    store: dict[str, Any],
    flags: dict[str, Any] | None,
) -> Listing:
    rows: list[ParsedRow] = []
    skipped = 0
    for kind, banner in _shown(store, flags):
        row = _row(name, host, kind, banner)
        if row is None:
            skipped += 1
        else:
            rows.append(row)
    return make_listing(variant, rows, skipped=skipped)


def _nuxt3(text: str) -> Listing:
    root = _state(text)
    store = next(
        (m for m in _walk(root) if "alertBannerConfig" in m or "alertBannerSeparate" in m),
        None,
    )
    if store is None:
        raise ShapeError("the Nuxt state has no alert banner store")
    info = next((m for m in _walk(root) if "school_name" in m and "alert_bg_color" in m), None)
    name = info.get("school_name") if info is not None else None
    if not isinstance(name, str) or not name.strip():
        raise ShapeError("the Nuxt state names no organization (theme school_name)")
    pinia = root.get("pinia")
    main = pinia.get("main") if isinstance(pinia, dict) else None
    host = main.get("host") if isinstance(main, dict) else None
    if host is None:
        host = store.get("host")
    host_text = host if isinstance(host, str) else None
    return _listing(NUXT_STATE, name, host_text, store, _first(root, SEPARATE_FLAG))


def _nuxt2(text: str) -> Listing:
    state = nuxt2.read(text)
    store: dict[str, Any] = {}
    for key in ("alertBannerConfig", "alertBannerSeparate"):
        found, value = state.value(key)
        if found:
            store[key] = value
    if not store:
        raise ShapeError("the Nuxt 2 state has no alert banner store")
    found, name = state.value("school_name")
    if not found or not isinstance(name, str) or not name.strip():
        raise ShapeError("the Nuxt 2 state names no organization (theme school_name)")
    found, flag = state.value(SEPARATE_FLAG)
    _, host = state.value("host", after=("state",))
    flags = {SEPARATE_FLAG: flag} if found else None
    host_text = host if isinstance(host, str) else None
    return _listing(NUXT2_STATE, name, host_text, store, flags)


def parse(body: bytes) -> Listing:
    """Read an Apptegy district homepage (or an archived one of its earlier forms)."""
    text = html_text(body)
    if _PAYLOAD.search(text) is not None:
        return _nuxt3(text)
    if _NUXT2.search(text) is not None:
        return _nuxt2(text)
    if schoolwires.holds_announcements(text):
        return schoolwires.parse_text(text)
    if campussuite.holds_alert_banner(text):
        return campussuite.parse_text(text)
    raise ShapeError("no __NUXT_DATA__ payload: not an Apptegy (Nuxt 3) page")


def slice_body(body: bytes) -> bytes:
    """Keep only the Nuxt 3 payload (the rest of the page is markup and styles).

    The payload is kept whole, in a minimal document, so the slice reads exactly
    as the page does.
    """
    text = html_text(body)
    found = _PAYLOAD.search(text)
    if found is None:
        return document("")
    return document(found.group(0))


def slice_body_v2(body: bytes) -> bytes:
    """Keep only the Nuxt payload: the Nuxt 3 data script, or the Nuxt 2 ``window.__NUXT__`` script.

    Like :func:`slice_body` (whose output for a Nuxt 3 page it keeps), and for a
    Nuxt 2 page the whole ``<script>`` element that sets ``window.__NUXT__``.
    """
    text = html_text(body)
    if _PAYLOAD.search(text) is not None:
        return slice_body(body)
    start = _NUXT2.search(text)
    if start is None:
        return document("")
    open_at = text.rfind("<script", 0, start.start())
    close_at = text.find("</script>", start.end())
    if open_at < 0 or close_at < 0:
        return document("")
    return document(text[open_at : close_at + len("</script>")])
