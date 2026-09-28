"""WDEL SnoWatch (Delmarva Broadcasting, later Forever Digital Media): the list before EventDelay.

WDEL's SnoWatch page (``https://www.wdel.com/features/wdel-stormwatch/``) framed
``/wdel/snowatch.php`` on ``delmarvabroadcasting.com`` (capture of 2018-01-04),
later on ``foreverdigitalmedia.com`` (2021-02-01); since 2025 the page keeps that
frame inside an HTML comment beside the EventDelay widget it shows (captures of
2025 and 2026, live 2026-09-27; the host did not answer from the build environment
that day, and the archive's last capture of it is of 2022-10-25). The list is
named SnoWatch in winter, StormWatch in summer and
"COVID-19 Closings" in spring 2020. Read by
:mod:`snowlight.sources.stations.eventdelay` (the WDEL station's adapter).
Variants, as the captures of 2019-06-13 to 2021-04-13 show (archive-captures run
36345392102):

``snowatch-index``
    ``snowatch.php``: either the sentence "There are no active SnoWatch listings at
    this time." (or "StormWatch listings", "COVID-19 Closings listings"), the empty
    state, or "The following categories currently have active ... listings" over
    one link per category, ``<li><a href="snowatch.php?type=7">Community/Non-Profit</a>``
    (captures of March to May 2020). The rows are on the category pages, so a
    populated index is :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED`,
    following each category page in the order listed.

``snowatch-category``
    ``snowatch.php?type=N``: after "You are now viewing an alphabetical listing of
    all StormWatch listings for <b>Community/Non-Profit</b>:", one colour-coded
    ``div.snowatch`` per organization (the capture of 2020-09-25)::

        <div class=snowatch style="background-color: #AA0000; border-color: #AA0000;">
          <div class=org>North Elk Coffee House</div>
          <div class=status>Closed</div><div class=clear></div>
          <div class=moreinfo>The September, October, and November concerts ...</div></div>

    ``div.org`` is the name and ``div.status`` the status; the category
    (``group``), the note (``moreinfo``) and the colour (``color``: the page's
    legend reads #AA0000 "CLOSED", #AAAA00 "2 HOURS LATE", #00AA00 "1 HOUR LATE",
    #0000AA "OTHER INFO") go in ``raw_extra``. The legend's own ``div.snowatch``
    boxes come before the listing sentence and are not rows. Every box after it
    must hold one name and one status; a category page with no box has not been
    seen and raises :class:`~snowlight.sources.stations.model.ShapeError`.

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`.
"""

import re

from selectolax.parser import HTMLParser

from snowlight.sources.stations.model import JsonScalar, Listing, ParsedRow, ShapeError
from snowlight.sources.stations.regional import (
    collapse,
    deferred,
    document,
    fragment_text,
    listing,
    node_text,
    row,
)

INDEX = "snowatch-index"
CATEGORY = "snowatch-category"
_NAMES = r"(?:SnoWatch|StormWatch|COVID-19 Closings)"
_EMPTY = re.compile(rf"There are no active {_NAMES} listings at this time\.")
_ACTIVE = re.compile(rf"The following categories currently have active {_NAMES} listings")
_CATEGORY_LINK = re.compile(
    r"<li>\s*<a href=\"(snowatch\.php\?type=[0-9]+)\">([^<]+)</a>", re.IGNORECASE
)
_VIEWING = re.compile(
    rf"You are now viewing an alphabetical listing of all {_NAMES} listings for\s*<b>([^<]+)</b>"
)
_MARK = "snowatch-request.php"
_COLOR = re.compile(r"background-color:\s*(#[0-9A-Fa-f]{6})")


def is_snowatch(text: str) -> bool:
    """Whether an HTML text is a SnoWatch page (its registration link and one of its forms)."""
    return _MARK in text and bool(
        _EMPTY.search(text) or _ACTIVE.search(text) or _VIEWING.search(text)
    )


def _category(text: str, viewing: re.Match[str]) -> Listing:
    group = collapse(fragment_text(viewing.group(1)))
    tree = HTMLParser(text[viewing.end() :])
    rows: list[ParsedRow] = []
    skipped = 0
    for box in tree.css("div.snowatch"):
        orgs, statuses = box.css("div.org"), box.css("div.status")
        if len(orgs) != 1 or len(statuses) != 1:
            raise ShapeError(f"a SnoWatch box holds {len(orgs)} names and {len(statuses)} statuses")
        extra: dict[str, JsonScalar] = {"group": group}
        info = box.css_first("div.moreinfo")
        if info is not None and node_text(info):
            extra["moreinfo"] = node_text(info)
        color = _COLOR.search(box.attributes.get("style") or "")
        if color is not None:
            extra["color"] = color.group(1).upper()
        found = row(node_text(orgs[0]), node_text(statuses[0]), None, extra)
        if found is None:
            skipped += 1
        else:
            rows.append(found)
    if not rows and not skipped:
        raise ShapeError(
            "a SnoWatch category page with no listing (its empty form has not been seen)"
        )
    return listing(CATEGORY, rows, skipped=skipped)


def parse(text: str) -> Listing:
    """Read a SnoWatch index or category page (``text``: the decoded HTML)."""
    if not is_snowatch(text):
        raise ShapeError("not a SnoWatch page")
    viewing = _VIEWING.search(text)
    if viewing is not None:
        return _category(text, viewing)
    links = tuple(dict.fromkeys(m.group(1) for m in _CATEGORY_LINK.finditer(text)))
    active = _ACTIVE.search(text) is not None
    empty = _EMPTY.search(text) is not None
    if active and links and not empty:
        return deferred(INDEX, links)
    if empty and not active and not links:
        return listing(INDEX, [])
    raise ShapeError("a SnoWatch index that neither lists categories nor says none are active")


def slice_text(text: str) -> bytes:
    """Keep what :func:`parse` reads: the registration link, the sentences and the list."""
    found = parse(text)
    viewing = _VIEWING.search(text)
    kept = [f'<a href="{_MARK}">register</a>']
    if found.variant == CATEGORY and viewing is not None:
        kept.append(viewing.group(0) + ":")
        tree = HTMLParser(text[viewing.end() :])
        kept.extend(box.html or "" for box in tree.css("div.snowatch"))
    else:
        for pattern in (_EMPTY, _ACTIVE):
            match = pattern.search(text)
            if match is not None:
                kept.append(f"<p>{match.group(0)}</p>")
        kept.extend(
            f'<li><a href="{m.group(1)}">{m.group(2)}</a></li>'
            for m in _CATEGORY_LINK.finditer(text)
        )
    return document("".join(kept))
