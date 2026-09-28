"""Published rosters: the organizations registered with a closings list, closed or not.

Three closings systems publish who is registered to report to them, even on a day
nothing is closed (checked first-hand on 2026-09-27; see the package docstring):

``flashalert``
    FlashAlert Newswire's regional feed, ``flashnews_xml2.php?RegionID=N``, holds a
    ``<participants>`` section: ``<participant_category name=...>`` elements, each
    with ``<org><orgname orgid=... zipcode=...>NAME</orgname>`` entries. One read
    per region the registry lists (its ``flashalert-*`` stations' ``data_url``
    names the RegionID). Only the school categories are kept
    (:func:`flashalert_school_category`).
``wral``
    WRAL's organizations API, ``api.wral.com/closings/v1/organizations``: JSON pages
    (``?pageSize=500&page=N``) of ``{orgCode, name, displayName, category,
    county}``. Only categories ``S`` (Public Schools) and ``P`` (Private Schools)
    are kept.
``cbs6``
    CBS6 Albany's SchoolWatch (WRGB): an index page linking one page per county
    (``Default.asp?County=AlbanyNY``); on a day with nothing closed each county page
    lists "the following participating schools and businesses in <County>": one
    alphabetical list, with no type, so every name is kept and the matcher decides
    which are schools. A page that shows active closings instead is not a roster
    and is refused (:class:`RosterFormatError`).

Every request goes through :class:`~snowlight.sources.stations.http.PoliteClient`
(an honest User-Agent, robots.txt read first and its verdict kept with each read,
per-host pacing, conditional requests). Each body is kept content-addressed in
the cache (``pipeline/.cache/listed/rosters/<sha256>.body``) and described in
``rosters.json`` (internal, never published)::

    {"user_agent": ..., "reads": [RosterRead, ...]}
    RosterRead = {"roster", "station_id", "part", "url", "final_url", "fetched_at",
                  "sha256", "bytes", "content_type",
                  "robots": [{"url", "state", "allowed", "rule", "crawl_delay"}]}

:func:`read_entries` parses the kept bodies back into :class:`RosterEntry` rows,
each carrying the matcher context of the station whose roster it is.
"""

import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Final
from urllib.parse import parse_qs, urlsplit

from snowlight.listed.located import Places
from snowlight.listed.scope import Context, station_context
from snowlight.output import JSONValue, write_bytes_atomic, write_json
from snowlight.sources.stations.http import Fetched, PoliteClient, iso_utc
from snowlight.sources.stations.registry import Registry

FLASHALERT_FEED: Final = "https://www.flashalertnewswire.net/IIN/reportsX/flashnews_xml2.php"
WRAL_ORGANIZATIONS: Final = "https://api.wral.com/closings/v1/organizations"
WRAL_PAGE_SIZE: Final = 500
WRAL_SCHOOL_CODES: Final = frozenset({"S", "P"})
"""WRAL's category codes for Public Schools and Private Schools (``/v1/categories``)."""
WRAL_STATION: Final = "wral-wral"
CBS6_INDEX: Final = "https://closings.cbs6albany.com/community/schoolwatch/Default.asp"
CBS6_STATION: Final = "sinclair-wrgb"
HOST_INTERVAL: Final = 3.0
"""Seconds between two requests to one host (at least; a robots Crawl-delay is longer)."""
MAX_WRAL_PAGES: Final = 100

type Fetcher = Callable[[str], Fetched]


class RosterFormatError(ValueError):
    """A roster body does not have the shape its reader expects."""


@dataclass(frozen=True, slots=True)
class RosterRead:
    """One roster body as it was read."""

    roster: str
    station_id: str
    part: str
    url: str
    final_url: str
    fetched_at: str
    sha256: str
    bytes: int
    content_type: str | None
    robots: tuple[dict[str, JSONValue], ...]

    def to_json(self) -> dict[str, JSONValue]:
        """The read as ``rosters.json`` keeps it."""
        return {
            "roster": self.roster,
            "station_id": self.station_id,
            "part": self.part,
            "url": self.url,
            "final_url": self.final_url,
            "fetched_at": self.fetched_at,
            "sha256": self.sha256,
            "bytes": self.bytes,
            "content_type": self.content_type,
            "robots": list(self.robots),
        }

    @classmethod
    def from_json(cls, item: Mapping[str, JSONValue]) -> "RosterRead":
        """Read one entry of ``rosters.json``."""
        robots = item.get("robots")
        content_type = item.get("content_type")
        size = item.get("bytes")
        if not isinstance(robots, list) or not isinstance(size, int):
            raise RosterFormatError(f"a roster read lacks its robots or size: {item!r}")
        return cls(
            roster=_text(item, "roster"),
            station_id=_text(item, "station_id"),
            part=_text(item, "part"),
            url=_text(item, "url"),
            final_url=_text(item, "final_url"),
            fetched_at=_text(item, "fetched_at"),
            sha256=_text(item, "sha256"),
            bytes=size,
            content_type=content_type if isinstance(content_type, str) else None,
            robots=tuple(dict(v) for v in robots if isinstance(v, dict)),
        )


def _text(item: Mapping[str, JSONValue], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value:
        raise RosterFormatError(f"a roster read lacks {key!r}: {item!r}")
    return value


@dataclass(frozen=True, slots=True)
class RosterEntry:
    """One organization a roster lists, with the context to match it in."""

    roster: str
    station_id: str
    name: str
    category: str | None
    org_id: str | None
    context: Context
    read_sha256: str
    fetched_at: str
    places: Places = ()
    """Where the roster says the organization is, for the guard (none is read today:
    WRAL's counties are the station's defaults on some entries)."""


# FlashAlert --------------------------------------------------------------------------

_DOCTYPE: Final = re.compile(rb"<!DOCTYPE\s[^\[>]*(\[.*?\])?\s*>", re.DOTALL)
_SCHOOL_WORDS: Final = re.compile(r"\b(schools?|privates?|charters?)\b", re.IGNORECASE)
_NOT_K12_WORDS: Final = re.compile(
    r"\b(colleges?|universit(y|ies)|head start|early childhood|preschools?)\b", re.IGNORECASE
)


def flashalert_school_category(name: str) -> bool:
    """True when a FlashAlert participants category files K-12 schools.

    ``"Multnomah Co. Schools"``, ``"King Co. School Districts"``, ``"Private &
    Charter Schools - Portland area"`` and ``"Seattle-area Privates, Charters,
    Childcares"`` do; ``"Colleges & Universities"``, ``"Head Start/Early
    Childhood"``, ``"Churches/Synagogues"`` and ``"Businesses"`` do not. A category
    that mixes schools with child care is kept: the matcher decides each name.
    """
    return bool(_SCHOOL_WORDS.search(name)) and not _NOT_K12_WORDS.search(name)


def flashalert_regions(registry: Registry) -> dict[str, int]:
    """Each FlashAlert station's RegionID, from its ``data_url`` (``...?RegionID=N``)."""
    regions: dict[str, int] = {}
    for station in sorted(registry.stations.values(), key=lambda s: s.id):
        if station.platform != "flashalert" or station.data_url is None:
            continue
        values = parse_qs(urlsplit(station.data_url).query).get("RegionID", [])
        if len(values) == 1 and values[0].isdigit():
            regions[station.id] = int(values[0])
    return regions


def flashalert_url(region: int) -> str:
    """The participants feed of one FlashAlert region."""
    return f"{FLASHALERT_FEED}?RegionID={region}"


def parse_flashalert(body: bytes) -> list[tuple[str, str, str | None]]:
    """Return ``(category, name, orgid)`` for every participant in a FlashAlert feed.

    Raises:
        RosterFormatError: the body is not a FlashAlert feed with a participants list.
    """
    cleaned = _DOCTYPE.sub(b"", body, count=1)
    if b"<!ENTITY" in cleaned:
        raise RosterFormatError("the feed declares entities, which are not read")
    try:
        root = ET.fromstring(cleaned)  # noqa: S314 - no DTD and no entities remain
    except ET.ParseError as error:
        raise RosterFormatError(f"not XML: {error}") from error
    if root.tag != "flashnews":
        raise RosterFormatError(f"root element is {root.tag!r}, not 'flashnews'")
    participants = root.find("participants")
    if participants is None:
        raise RosterFormatError("the feed has no participants section")
    found: list[tuple[str, str, str | None]] = []
    for category in participants.findall("participant_category"):
        label = " ".join((category.get("name") or "").split())
        for org in category.findall("org"):
            node = org.find("orgname")
            if node is None:
                continue
            name = " ".join("".join(node.itertext()).split())
            if name:
                found.append((label, name, node.get("orgid")))
    return found


# WRAL --------------------------------------------------------------------------------


def wral_url(page: int) -> str:
    """One page of WRAL's organizations list."""
    return f"{WRAL_ORGANIZATIONS}?pageSize={WRAL_PAGE_SIZE}&page={page}"


@dataclass(frozen=True, slots=True)
class WralPage:
    """One page of WRAL's organizations."""

    total: int
    page: int
    page_size: int
    organizations: tuple[tuple[str, str, str, str | None], ...]
    """``(orgCode, name, category, county)`` in page order."""


def parse_wral(body: bytes) -> WralPage:
    """Read one page of WRAL's organizations API.

    Raises:
        RosterFormatError: the body is not a page of organizations.
    """
    try:
        data = json.loads(body)
    except ValueError as error:
        raise RosterFormatError(f"not JSON: {error}") from error
    if not isinstance(data, dict):
        raise RosterFormatError("the page is not a JSON object")
    total, page, size, items = (
        data.get("total"),
        data.get("page"),
        data.get("pageSize"),
        data.get("organizations"),
    )
    if not (isinstance(total, int) and isinstance(page, int) and isinstance(size, int)):
        raise RosterFormatError("the page lacks total, page or pageSize")
    if not isinstance(items, list):
        raise RosterFormatError("the page has no organizations list")
    orgs: list[tuple[str, str, str, str | None]] = []
    for item in items:
        if not isinstance(item, dict):
            raise RosterFormatError(f"an organization is not an object: {item!r}")
        code, name, category = item.get("orgCode"), item.get("name"), item.get("category")
        county = item.get("county")
        if not (isinstance(code, str) and isinstance(category, str)):
            raise RosterFormatError(f"an organization lacks orgCode or category: {item!r}")
        if name is not None and not isinstance(name, str):
            raise RosterFormatError(f"an organization's name is not text: {item!r}")
        # A few organizations have no name (null): kept as "" and never matched.
        orgs.append(
            (
                code,
                " ".join((name or "").split()),
                category,
                county.strip() or None if isinstance(county, str) else None,
            )
        )
    return WralPage(total, page, size, tuple(orgs))


# CBS6 SchoolWatch ---------------------------------------------------------------------

_CBS6_LINK: Final = re.compile(
    r'Default\.asp\?County=([A-Za-z]+)([A-Z]{2})"[^>]*>\s*<img[^>]*\balt="([^"]+)"',
    re.IGNORECASE,
)
_CBS6_ALT: Final = re.compile(r"^(.+?) County, ([A-Z]{2})$")
_CBS6_HEADER: Final = re.compile(
    r"participating schools and businesses in ([^:<]+?) County:", re.IGNORECASE
)
_CBS6_END: Final = "End School data"
_CBS6_NAME: Final = re.compile(
    r'<td[^>]*bgcolor="#(?:cccccc|ffffff)"[^>]*>\s*<font size=2[^>]*>(.*?)</font>\s*</td>',
    re.IGNORECASE | re.DOTALL,
)
_TAG: Final = re.compile(r"<[^>]+>")


@dataclass(frozen=True, slots=True, order=True)
class Cbs6County:
    """One county the SchoolWatch index links: its page key and the county it names."""

    key: str
    county: str
    state: str

    @property
    def url(self) -> str:
        """The county's roster page."""
        return f"{CBS6_INDEX}?County={self.key}"


def _latin(body: bytes) -> str:
    return body.decode("windows-1252", errors="replace")


def parse_cbs6_index(body: bytes) -> list[Cbs6County]:
    """The counties SchoolWatch's index links, each once, sorted by page key.

    Raises:
        RosterFormatError: the index links no county.
    """
    found: dict[str, Cbs6County] = {}
    for match in _CBS6_LINK.finditer(_latin(body)):
        stem, state, alt = match.group(1), match.group(2).upper(), unescape(match.group(3))
        named = _CBS6_ALT.match(alt.strip())
        if named is None or named.group(2) != state:
            raise RosterFormatError(f"county link {stem}{state} is labelled {alt!r}")
        key = f"{stem}{state}"
        county = Cbs6County(key, named.group(1).strip(), state)
        if found.setdefault(key, county) != county:
            raise RosterFormatError(f"county {key} is labelled two ways")
    if not found:
        raise RosterFormatError("the SchoolWatch index links no county")
    return sorted(found.values())


def parse_cbs6_county(body: bytes, county: Cbs6County) -> list[str]:
    """The names a SchoolWatch county page lists as participating, in page order.

    The list may be empty: a county can have no participant.

    Raises:
        RosterFormatError: the page does not hold the participating list of ``county``
            (on a day with active closings the page lists those instead).
    """
    text = _latin(body)
    header = _CBS6_HEADER.search(text)
    if header is None:
        raise RosterFormatError(f"{county.key}: no participating list on the page")
    if " ".join(header.group(1).split()).casefold() != county.county.casefold():
        raise RosterFormatError(f"{county.key}: the list is of {header.group(1)!r} County")
    end = text.find(_CBS6_END, header.end())
    if end < 0:
        raise RosterFormatError(f"{county.key}: the list has no end marker")
    names = [
        " ".join(unescape(_TAG.sub("", match.group(1))).split())
        for match in _CBS6_NAME.finditer(text, header.end(), end)
    ]
    # A county with no participant has an empty list (Fairfield County, CT, on 2026-09-27).
    return [name for name in names if name]


def cbs6_contexts(
    counties: Sequence[Cbs6County], county_fips: Mapping[tuple[str, str], str]
) -> dict[str, Context]:
    """The matcher context of each state's SchoolWatch pages.

    WRGB's registry entry has no list and names New York alone, while SchoolWatch
    links counties of four states; each page is matched in its own state, among the
    counties the index links in that state (``county_fips`` maps ``(state, county
    name)`` to its FIPS code, from the school directory). When a linked county of a
    state cannot be placed (Connecticut's directory counties are planning regions),
    that state's pages are matched in the whole state.
    """
    by_state: dict[str, list[str | None]] = {}
    for county in counties:
        by_state.setdefault(county.state, []).append(
            county_fips.get((county.state, county.county.casefold()))
        )
    contexts: dict[str, Context] = {}
    for state, codes in sorted(by_state.items()):
        placed = sorted({code for code in codes if code is not None})
        whole = any(code is None for code in codes)
        contexts[state] = Context(
            market=CBS6_STATION,
            states=(state,),
            counties=None if whole else tuple(placed),
        )
    return contexts


# Fetching ------------------------------------------------------------------------------


def body_path(cache_dir: Path, sha256: str) -> Path:
    """Where a roster body with this SHA-256 is kept."""
    return cache_dir / f"{sha256}.body"


def _record(
    fetched: Fetched, cache_dir: Path, *, roster: str, station_id: str, part: str
) -> RosterRead:
    path = body_path(cache_dir, fetched.sha256)
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != fetched.sha256:
        write_bytes_atomic(path, fetched.body)
    return RosterRead(
        roster=roster,
        station_id=station_id,
        part=part,
        url=fetched.url,
        final_url=fetched.final_url,
        fetched_at=iso_utc(fetched.fetched_at),
        sha256=fetched.sha256,
        bytes=len(fetched.body),
        content_type=fetched.content_type,
        robots=tuple(
            {
                "url": verdict.url,
                "state": verdict.state.value,
                "allowed": verdict.allowed,
                "rule": verdict.rule,
                "crawl_delay": verdict.crawl_delay,
            }
            for verdict in fetched.robots
        ),
    )


def roster_id(station_id: str) -> str:
    """The id a station's roster goes by in the outputs."""
    return f"{station_id}/roster"


def fetch_rosters(
    client: PoliteClient,
    registry: Registry,
    cache_dir: Path,
    *,
    progress: Callable[[str], None] | None = None,
) -> list[RosterRead]:
    """Read every roster once, keep each body in ``cache_dir`` and describe the reads.

    Raises:
        FetchError: a roster could not be read.
        RosterFormatError: a roster's body does not have its expected shape.
    """

    def get(url: str) -> Fetched:
        if progress is not None:
            progress(url)
        return client.fetch(url, interval=HOST_INTERVAL)

    reads: list[RosterRead] = []
    for station_id, region in sorted(flashalert_regions(registry).items()):
        fetched = get(flashalert_url(region))
        parse_flashalert(fetched.body)
        reads.append(
            _record(
                fetched,
                cache_dir,
                roster=roster_id(station_id),
                station_id=station_id,
                part=f"RegionID={region}",
            )
        )
    reads.extend(_fetch_wral(get, cache_dir))
    index = get(CBS6_INDEX)
    counties = parse_cbs6_index(index.body)
    reads.append(
        _record(
            index, cache_dir, roster=roster_id(CBS6_STATION), station_id=CBS6_STATION, part="index"
        )
    )
    for county in counties:
        fetched = get(county.url)
        parse_cbs6_county(fetched.body, county)
        reads.append(
            _record(
                fetched,
                cache_dir,
                roster=roster_id(CBS6_STATION),
                station_id=CBS6_STATION,
                part=county.key,
            )
        )
    return reads


def _fetch_wral(get: Fetcher, cache_dir: Path) -> list[RosterRead]:
    first = get(wral_url(1))
    page = parse_wral(first.body)
    if page.page_size <= 0:
        raise RosterFormatError("WRAL's page size is not positive")
    pages = math.ceil(page.total / page.page_size)
    if pages > MAX_WRAL_PAGES:
        raise RosterFormatError(f"WRAL lists {page.total} organizations, more than expected")
    reads = [_wral_read(first, cache_dir, 1)]
    for number in range(2, pages + 1):
        fetched = get(wral_url(number))
        parse_wral(fetched.body)
        reads.append(_wral_read(fetched, cache_dir, number))
    return reads


def _wral_read(fetched: Fetched, cache_dir: Path, number: int) -> RosterRead:
    return _record(
        fetched,
        cache_dir,
        roster=roster_id(WRAL_STATION),
        station_id=WRAL_STATION,
        part=f"page={number}",
    )


def write_rosters(path: Path, reads: Sequence[RosterRead], user_agent: str) -> None:
    """Write ``rosters.json``."""
    write_json(path, {"user_agent": user_agent, "reads": [read.to_json() for read in reads]})


def load_rosters(path: Path) -> list[RosterRead]:
    """Read ``rosters.json``.

    Raises:
        RosterFormatError: the file does not have the shape :func:`write_rosters` gives it.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    reads = data.get("reads") if isinstance(data, dict) else None
    if not isinstance(reads, list):
        raise RosterFormatError(f"{path.name}: no reads list")
    return [RosterRead.from_json(item) for item in reads if isinstance(item, dict)]


def cached_reads_intact(reads: Iterable[RosterRead], cache_dir: Path) -> bool:
    """True when every read's body is in ``cache_dir`` with its recorded SHA-256."""
    for read in reads:
        path = body_path(cache_dir, read.sha256)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != read.sha256:
            return False
    return True


# Entries -------------------------------------------------------------------------------


def read_entries(
    reads: Sequence[RosterRead],
    cache_dir: Path,
    registry: Registry,
    county_fips: Mapping[tuple[str, str], str],
) -> list[RosterEntry]:
    """Parse the kept roster bodies into the entries to match (school categories only).

    Raises:
        RosterFormatError: a body is missing, altered, or not of its roster's shape,
            or WRAL's pages do not add up to the total it gives.
    """
    bodies: dict[str, bytes] = {}
    for read in reads:
        data = body_path(cache_dir, read.sha256).read_bytes()
        if hashlib.sha256(data).hexdigest() != read.sha256:
            raise RosterFormatError(f"{read.url}: the kept body does not match its SHA-256")
        bodies[read.sha256] = data
    entries: list[RosterEntry] = []
    for read in reads:
        if read.station_id.startswith("flashalert-"):
            context = station_context(registry.stations[read.station_id])
            entries.extend(
                RosterEntry(
                    read.roster,
                    read.station_id,
                    name,
                    category,
                    org,
                    context,
                    read.sha256,
                    read.fetched_at,
                )
                for category, name, org in parse_flashalert(bodies[read.sha256])
                if flashalert_school_category(category)
            )
    entries.extend(
        _wral_entries([r for r in reads if r.station_id == WRAL_STATION], bodies, registry)
    )
    entries.extend(
        _cbs6_entries([r for r in reads if r.station_id == CBS6_STATION], bodies, county_fips)
    )
    return entries


def _wral_entries(
    reads: Sequence[RosterRead], bodies: Mapping[str, bytes], registry: Registry
) -> list[RosterEntry]:
    if not reads:
        return []
    context = station_context(registry.stations[WRAL_STATION])
    codes: set[str] = set()
    totals: set[int] = set()
    entries: list[RosterEntry] = []
    for read in reads:
        page = parse_wral(bodies[read.sha256])
        totals.add(page.total)
        for code, name, category, _county in page.organizations:
            if code in codes:
                raise RosterFormatError(f"WRAL organization {code} appears on two pages")
            codes.add(code)
            if category in WRAL_SCHOOL_CODES and name:
                entries.append(
                    RosterEntry(
                        read.roster,
                        read.station_id,
                        name,
                        category,
                        code,
                        context,
                        read.sha256,
                        read.fetched_at,
                    )
                )
    if len(totals) != 1 or len(codes) != totals.pop():
        raise RosterFormatError(f"WRAL's pages hold {len(codes)} organizations, not its total")
    return entries


def _cbs6_entries(
    reads: Sequence[RosterRead],
    bodies: Mapping[str, bytes],
    county_fips: Mapping[tuple[str, str], str],
) -> list[RosterEntry]:
    index = [read for read in reads if read.part == "index"]
    if not index:
        return []
    if len(index) != 1:
        raise RosterFormatError("SchoolWatch's index was read more than once")
    counties = {county.key: county for county in parse_cbs6_index(bodies[index[0].sha256])}
    contexts = cbs6_contexts(sorted(counties.values()), county_fips)
    pages = {read.part: read for read in reads if read.part != "index"}
    if set(pages) != set(counties):
        raise RosterFormatError("SchoolWatch's county pages are not the index's counties")
    entries: list[RosterEntry] = []
    for key in sorted(pages):
        read, county = pages[key], counties[key]
        entries.extend(
            RosterEntry(
                read.roster,
                read.station_id,
                name,
                None,
                None,
                contexts[county.state],
                read.sha256,
                read.fetched_at,
            )
            for name in parse_cbs6_county(bodies[read.sha256], county)
        )
    return entries
