"""WeatherThreat's closings lists (Hollman Media): a script that writes one outlet's list.

Outlets that license WeatherThreat embed its list script,
``https://wt{1-3}.weatherthreat.com/wt_list/viewClosings.php?media_id={id}&...``
(NTV Nebraska: ``ntv``, KNEB: ``kneb``). The answer is JavaScript, not data: it
defines the list's functions, then fills ``var closings = new Array();`` with one
line per posting::

    closings[0] = new closing('clos~~k12schoo~~...~~ORG NAME~~CITY~~NE~~County~~Closed~~...');

The script's own ``closing()`` function names the ``~~``-separated fields (read
2026-09-27): 0 ``closing_type_id``, 1 ``org_type_id``, 2 ``user_id``, 3
``closing_short_details``, 4 ``closing_long_details``, 5 ``org_name``, 6
``org_city``, 7 ``org_state``, 8 ``county``, 9 ``closing_description``, 10
``org_type_description``, 11 ``closing_start_date``, 12 ``closing_end_date``, 13
``closing_effective_day``, 14 ``closing_entered_date``, 15 ``org_id``, 16
``closing_id``, 23 ``flagged``, 24 ``other``. Variant this adapter reads:

``weatherthreat-js``
    Each posting the page shows is a row, as its ``writeClosings()`` shows it: the
    name is ``org_name``; the status is ``closing_description``, the effective day
    (``closing_effective_day`` 1-7 as Sunday to Saturday) and, after " - ",
    ``closing_long_details``. City, state, county, organization type, the type
    codes, the start, end and entry times and the ids go in ``raw_extra`` under
    the script's field names. The page's "(updated 09/27 01:17 Central)" is each
    row's ``raw_updated_text``. Postings the page does not show are left out as
    it leaves them out: those flagged by readers (``flagged`` of 2 or more) and
    unconfirmed ones (type ``unco``). National Weather Service alerts the script
    also carries (type ``weat``) have no organization name: they are counted as
    skipped rows, not read as closings. A script whose array holds nothing the
    page shows is the empty state (the page then writes "No closings were found
    that match the selected criteria.").

``weatherthreat-page``
    An outlet's closings page with WeatherThreat's "Alerts Page Plugin" (KNEB's,
    captures of 2015 and 2023): a script that loads the list script from a server
    it picks at random among those it names (``servers[0] = "wt1"; ...``), with
    ``'media_id=' + 'kneb'`` and its ``version``, into ``div#wt_closings_list``.
    :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED`, following
    the list script on the first server named, as the plugin builds its address
    (``.../wt_list/viewClosings.php?media_id=kneb&plugin=1&server=wt1&version=2.0.2&directory=``,
    without the cache-busting ``t``).

``weatherthreat-banner``
    The same page when the site's alert bar (the "breaking news" plugin's
    "CLOSINGS & CANCELLATIONS" box, ``ul.cc_wt_list``) lists postings, as KNEB's
    capture of 2023-01-18 12:33 UTC shows (22 of them)::

        <li class="cc_wt_title_wrapper bn_title_wrapper"><a class="cc_wt_title bn_title" ...>
          <span style="text-transform:uppercase"> CITY OF GERING (Gering): </span>
          <span>Notice - SNOW EMERGENCY 8p 1/17 until lifted (Details...)</span></a></li>

    Each entry is a row: the first span, before its "(Town):", is the name and the
    town goes in ``raw_extra["location"]``; the second span, without its
    "(Details...)", is the status. The bar is the site's own summary of the
    WeatherThreat list; the list script's answer at the same time was not captured,
    so whether the bar held every posting is not known. The page's list script is
    not followed when the bar lists postings.

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`.
"""

import re

from selectolax.parser import HTMLParser

from snowlight.sources.stations.body import decode
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

VARIANT = "weatherthreat-js"
PAGE = "weatherthreat-page"
BANNER = "weatherthreat-banner"
_PLUGIN = "WeatherThreat Alerts Page Plugin"
_MEDIA = re.compile(r"'media_id=' \+ '([a-z0-9]+)'")
_VERSION = re.compile(r"&version=([0-9.]+)&directory=")
_FIRST_SERVER = re.compile(r"servers\[0\] = \"(wt[0-9]+)\"")
_SCHEME = re.compile(r"wt_loadScript_list\(\\'(https?)://")
_BANNER_ENTRY = "ul.cc_wt_list li.cc_wt_title_wrapper"
_NAME_TOWN = re.compile(r"^(.*?)\s*\(([^()]*)\):$")
_DETAILS = " (Details...)"
_SPANS = 2
FIELDS = {
    0: "closing_type_id",
    1: "org_type_id",
    2: "user_id",
    3: "closing_short_details",
    4: "closing_long_details",
    5: "org_name",
    6: "org_city",
    7: "org_state",
    8: "county",
    9: "closing_description",
    10: "org_type_description",
    11: "closing_start_date",
    12: "closing_end_date",
    13: "closing_effective_day",
    14: "closing_entered_date",
    15: "org_id",
    16: "closing_id",
    23: "flagged",
    24: "other",
}
DAYS = {
    "1": "Sunday",
    "2": "Monday",
    "3": "Tuesday",
    "4": "Wednesday",
    "5": "Thursday",
    "6": "Friday",
    "7": "Saturday",
}
FLAG_THRESHOLD = 2
_MARK = "var closings = new Array();"
_CONSTRUCTOR = "function closing(theData)"
_POSTING = re.compile(r"^closings\[(\d+)\]\s*=\s*new closing\('((?:[^'\\]|\\.)*)'\);\s*$", re.M)
_UPDATED = re.compile(r"<span class=\"closing_text\"> \((updated [^)<]*)\)</span>")
_ESCAPE = re.compile(r"\\(.)")
_MIN_FIELDS = 25
_KEPT = (
    "org_city",
    "org_state",
    "county",
    "org_type_description",
    "org_type_id",
    "closing_type_id",
    "closing_short_details",
    "closing_start_date",
    "closing_end_date",
    "closing_effective_day",
    "closing_entered_date",
    "org_id",
    "closing_id",
)


def _posting(values: list[str], updated: str | None) -> ParsedRow | None:
    fields = {name: values[index] for index, name in FIELDS.items()}
    long_details = collapse(fields["closing_long_details"])
    day = DAYS.get(fields["closing_effective_day"].strip(), "")
    status = collapse(f"{fields['closing_description']} {day}")
    if long_details:
        status = f"{status} - {long_details}"
    extra: dict[str, JsonScalar] = {
        key: collapse(fields[key]) for key in _KEPT if collapse(fields[key])
    }
    if updated:
        extra["updated_scope"] = "page"
    return row(fields["org_name"], status, updated, extra)


def _banner(text: str) -> Listing | None:
    """Read the site alert bar's postings; None when the bar lists none."""
    entries = HTMLParser(text).css(_BANNER_ENTRY)
    if not entries:
        return None
    rows: list[ParsedRow] = []
    skipped = 0
    for entry in entries:
        spans = entry.css("a span")
        if len(spans) != _SPANS:
            raise ShapeError(f"an alert bar entry holds {len(spans)} spans, not {_SPANS}")
        head = _NAME_TOWN.match(node_text(spans[0]))
        if head is None:
            raise ShapeError(f"an alert bar entry names no town: {node_text(spans[0])[:60]!r}")
        status = node_text(spans[1]).removesuffix(_DETAILS)
        extra: dict[str, JsonScalar] = {"location": head.group(2)} if head.group(2) else {}
        found = row(head.group(1), status, None, extra)
        if found is None:
            skipped += 1
        else:
            rows.append(found)
    return listing(BANNER, rows, skipped=skipped)


def _page(text: str) -> Listing:
    """Read an outlet's page: the alert bar's postings, else the list script it loads."""
    banner = _banner(text)
    if banner is not None:
        return banner
    media, version = _MEDIA.search(text), _VERSION.search(text)
    server, scheme = _FIRST_SERVER.search(text), _SCHEME.search(text)
    if media is None or version is None or server is None or scheme is None:
        raise ShapeError("a WeatherThreat plugin page whose list script address is incomplete")
    first = server.group(1)
    address = (
        f"{scheme.group(1)}://{first}.weatherthreat.com/wt_list/viewClosings.php"
        f"?media_id={media.group(1)}&plugin=1&server={first}&version={version.group(1)}&directory="
    )
    return deferred(PAGE, (address,))


def parse(body: bytes) -> Listing:
    """Read a WeatherThreat list script, or an outlet's page that loads it."""
    text = html_text(body)
    if _PLUGIN in text and _MARK not in text:
        return _page(text)
    if _MARK not in text or _CONSTRUCTOR not in text:
        raise ShapeError("not a WeatherThreat closings script")
    stamp = _UPDATED.search(text)
    updated = collapse(stamp.group(1)) if stamp is not None else None
    rows: list[ParsedRow] = []
    skipped = 0
    postings = _POSTING.findall(text)
    if len(postings) != text.count("new closing('"):
        raise ShapeError("a WeatherThreat posting is not on a line of its own")
    for _index, data in postings:
        values = _ESCAPE.sub(r"\1", data).split("~~")
        if len(values) < _MIN_FIELDS:
            raise ShapeError(f"a WeatherThreat posting has {len(values)} fields")
        flagged = values[23].strip()
        if values[0] == "unco" or (flagged.isdigit() and int(flagged) >= FLAG_THRESHOLD):
            continue
        found = _posting(values, updated)
        if found is None:
            skipped += 1
        else:
            rows.append(found)
    return listing(VARIANT, rows, skipped=skipped)


def slice_body(body: bytes) -> bytes:
    """Keep the script's markers, its update line and its postings (in order).

    A page keeps its alert bar's list, or the plugin's lines that name the list
    script's address.
    """
    found = parse(body)
    text = html_text(body)
    if found.variant == BANNER:
        bar = HTMLParser(text).css_first("ul.cc_wt_list")
        return document(f"<!-- {_PLUGIN} -->" + ((bar.html or "") if bar is not None else ""))
    if found.variant == PAGE:
        kept = [f"<!-- {_PLUGIN} -->"]
        for pattern in (_MEDIA, _VERSION, _FIRST_SERVER, _SCHEME):
            match = pattern.search(text)
            if match is not None:
                kept.append(match.group(0))
        return document("<script>" + " ".join(kept[1:]) + "</script>" + kept[0])
    stamp = _UPDATED.search(text)
    lines = [_CONSTRUCTOR + " {}", _MARK]
    lines += [match.group(0).strip() for match in _POSTING.finditer(text)]
    if stamp is not None:
        lines.append(f"toWrite += '{stamp.group(0)}';")
    return ("\n".join(lines) + "\n").encode()


def raw(body: bytes) -> bytes:
    """Return the body without an archive content encoding (for fixtures kept whole)."""
    return decode(body)
