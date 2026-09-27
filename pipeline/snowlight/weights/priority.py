"""Which scraper family to build next: schools and closure-weighted schools each would add.

Inputs (all read, none changed):

* the first-hand station checks, ``docs/research/firsthand/*.json`` (one record
  per station website or system, checked 2026-09-26), and the market anchors in
  ``docs/research/sources.json`` for the records linked to it;
* the school directory and each school's own closure weight (the weight of the
  school in its own forecast zone, :mod:`snowlight.weights.perschool`), summed per
  directory county;
* current coverage, ``pipeline/out/internal/stations/coverage.json``: a county
  is covered when a *working* Gray or Hearst source lists it (station ids
  ``gray-*`` and ``hearst-*``; other groups' working sources, added as their
  scrapers are built, are reported beside it and give an alternative ranking);
* the DMA county crosswalk the station registry uses, read by
  :mod:`snowlight.weights.markets` (the pinned Nielsen-derived list, the 2025
  Census county Gazetteer and the Connecticut crosswalk; when the registry is
  present, the build checks that its DMA-based county lists agree).

Which records count
===================

Every record whose check found a closings list counts, including those whose
list file robots.txt disallows (the owner decided on 2026-09-26 to read those
too) and hand-typed lists. A record counts when its ``variant`` is one of
:data:`LIST_VARIANTS`, or when it is one of :data:`LISTS_NOT_READ`: records
whose list is known (by its address, a frame that loads it, or the lead that
found it) but was not read because robots.txt disallows it, robots.txt could not
be read, or the host could not be reached. Every other variant is left out with
the reason in :data:`NOT_LISTS` (no page found, a page without a list, only a
count, blocked before any list was seen, or a station now on Gray's platform,
which the Gray adapter covers), as are the records in :data:`NAME_EXCLUSIONS`,
whose own check shows the list cannot load.

Families
========

Each counted record belongs to exactly one family (:func:`family_of`), tried
in this order: the shared vendors (Emergency Closing Center, FlashAlert, NJ 101.5,
the state systems, which also take WJAR's frame of the Rhode Island list); then the
platform or owner families (Nexstar wp-json, TEGNA module, Scripps module,
NBC-owned, ABC-owned, FOX files, CBS feeds, Sinclair ftptransfer, Cox, Graham,
Allen, Hubbard, Spectrum, News 12); then the NewsTicker family (NewsTicker-format
files no owner family above claims); then the rest (one-off pages).

Markets
=======

A record's counties are its market's counties in the DMA crosswalk. The market
is read from the record's own market text (``Harrisburg-Lancaster-Lebanon-York``,
``Charleston SC``, ``Boise and Twin Falls``), matched to the crosswalk's labels
by city and state, or from its ``sources.json`` anchors (``Harrisburg|PA``)
when the text does not settle it; :data:`MARKET_OVERRIDES` names the market for
the records whose text names a region rather than a market, each with its
reason. Regional and statewide systems, whose lists cover part of a market,
keep only the market's counties in the record's own states (``dma-in-states``);
a statewide system takes every county of its state through the crosswalk; a
county office takes its county (by name in the Gazetteer).

What is estimated
=================

For each family: the schools in counties it would list that no working Gray or
Hearst source lists (``standalone``), and the same weighted by each school's
closure weight (``weighted``: the sum of the schools' weights; the national
mean weight per school is 1, so a weighted school is a school with an average
closure climate). The ranking is greedy: each step takes the family that adds
the most weighted schools not yet covered by Gray, Hearst or the families
already taken. Market counties are an upper bound on what a list covers (a
station rarely lists every county of its market), so every figure is an upper
bound.
"""

import json
import re
from collections import Counter, defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from snowlight.output import JSONValue
from snowlight.weights.markets import DmaCounties, normalize_county
from snowlight.weights.registered import GRAY_PLATFORM, RegistryStation

FIRSTHAND_FILES = ("nexstar-tegna-scripps.json", "others.json")

type Basis = Literal["dma", "dma-in-states", "statewide", "county"]

LIST_VARIANTS: frozenset[str] = frozenset(
    {
        "nexstar-wp-closings",
        "nexstar-manual-page",
        "nexstar-psg-frame",
        "ecc-psg-json",
        "schoolclosingsnet-frame",
        "tegna-closings-module",
        "tegna-flashalert-frame",
        "scripps-closings-module",
        "scripps-manual-text",
        "wtvq-snowatch-frame",
        "sinclair-next-ftptransfer",
        "sinclair-next-external-newsticker",
        "sinclair-next-external-iframe",
        "sinclair-chameleon-json",
        "blox-weather-closings-table",
        "blox-closings-xml",
        "blox-app-closings",
        "blox-closings-assets",
        "riba-newsticker",
        "newsticker-export",
        "newsticker-county-select",
        "closings-table-currently-no",
        "fox-bti-plain",
        "cbs-widget-feed",
        "nbc-wp-closings",
        "abc-otv-school-list",
        "ecc-react",
        "cox-arc-closing",
        "graham-arc-school-closings",
        "arc-fusion-schoolclosings",
        "allen-blox-ftp2-frame",
        "hubbard-schoolalert-asset",
        "wtop-stormdesk",
        "whdh-closure-notice",
        "wral-closings-api",
        "gsync-style-json",
        "weatherthreat-js",
        "flashalert-cwc-closures",
        "flashalert-emergency-xml",
        "spectrum-raven-json",
        "news12-jsp",
        "townsquare-njclosings",
        "eventdelay-widget",
        "delaware-jqgrid-xml",
        "county-office-page",
        "google-sheet-pubhtml",
    }
)
"""Variants whose check found a closings list (or the page's frame of one)."""

NOT_LISTS: Mapping[str, str] = {
    "none-found": "no closings page found",
    "moved-to-gray": "now a Gray station, covered by the Gray adapter",
    "gray-fusion-count": "a Gray-platform page, covered by the Gray adapter",
    "scripps-empty-page": "a page with an empty body, no list",
    "page-without-list": "a page with no list",
    "sinclair-next-empty-embed": "a page whose list embed is empty",
    "amb-count-json": "a count of closings, not a list",
    "intake-only": "an intake form, no public list",
    "opm-json": "federal office status, not schools",
    "article-feed": "closures posted as news items, not a list",
    "dead": "the site is gone",
    "blocked-429": "answered 429 before any list was seen",
    "blocked-403": "answered 403 before any list was seen",
    "blocked-js-challenge": "a script challenge before any list was seen",
    "unreachable": "the host could not be reached",
    "robots-unreachable": "robots.txt could not be read, so nothing was fetched",
    "tls-failure": "TLS verification failed, nothing was read",
    "vendor-frame": "frames a host that could not be reached",
    "nexstar-media-frame": "frames a host whose robots.txt could not be read",
    "robots-blocked": "robots.txt blocks the whole site and no list address is known",
}
"""Variants left out, and why."""

_KERN = "the Kern County AlertLine (alertline.kern.org), whose TLS chain could not be verified"
LISTS_NOT_READ: Mapping[str, tuple[str, str]] = {
    "WVEIS": (
        "state-systems",
        "robots.txt disallows the site; the check names its list address (rss.php)",
    ),
    "WFRD": (
        "rest",
        "robots.txt disallows the site; its lead (sources.json wfrd) names the closings page "
        "and the list endpoint",
    ),
    "North Country Public Radio storm list": (
        "rest",
        "robots.txt disallows the site; the list is known by its title and address (storm.php)",
    ),
    "KXXO Mixx 96.1 school closings": (
        "rest",
        "robots.txt could not be read (treated as disallowed); the list is known by its title "
        "and address (list-school-closings)",
    ),
    "WVNS": (
        "rest",
        "its closings page frames the list file (closings_page.html), whose host's robots.txt "
        "could not be read",
    ),
    "KERO": ("rest", f"its closings page frames {_KERN}"),
    "KBAK": ("rest", f"its closings page frames {_KERN}"),
    "Kern County AlertLine": ("rest", f"the county's own list: {_KERN}"),
}
"""Records whose list is known but was not read, their family and why they count."""

NAME_EXCLUSIONS: Mapping[str, str] = {
    "KFXL": "its list embed is broken (the check found pasted text in place of the script)",
}
"""Records of a list variant whose own check says the list cannot load."""


@dataclass(frozen=True, slots=True)
class Family:
    """One scraper family."""

    id: str
    name: str


FAMILIES: tuple[Family, ...] = (
    Family("nexstar-wp", "Nexstar wp-json"),
    Family("tegna-module", "TEGNA module"),
    Family("scripps-module", "Scripps module"),
    Family("nbc-owned", "NBC-owned"),
    Family("abc-owned", "ABC-owned"),
    Family("fox-files", "FOX files"),
    Family("cbs-feeds", "CBS feeds"),
    Family("sinclair-ftptransfer", "Sinclair ftptransfer"),
    Family("cox", "Cox"),
    Family("graham", "Graham"),
    Family("allen", "Allen"),
    Family("hubbard", "Hubbard"),
    Family("spectrum", "Spectrum"),
    Family("news12", "News 12"),
    Family("flashalert", "FlashAlert"),
    Family("ecc", "Emergency Closing Center"),
    Family("nj1015", "NJ 101.5"),
    Family("state-systems", "State systems"),
    Family("newsticker", "NewsTicker family"),
    Family("rest", "The rest (one-off pages)"),
)
FAMILY_NAMES: dict[str, str] = {family.id: family.name for family in FAMILIES}

_VENDOR_FAMILIES: dict[str, str] = {
    "ecc-react": "ecc",
    "ecc-psg-json": "ecc",
    "flashalert-cwc-closures": "flashalert",
    "flashalert-emergency-xml": "flashalert",
    "tegna-flashalert-frame": "flashalert",
    "townsquare-njclosings": "nj1015",
    "riba-newsticker": "state-systems",
    "delaware-jqgrid-xml": "state-systems",
}
_VARIANT_FAMILIES: dict[str, str] = {
    "nexstar-wp-closings": "nexstar-wp",
    "tegna-closings-module": "tegna-module",
    "scripps-closings-module": "scripps-module",
    "nbc-wp-closings": "nbc-owned",
    "abc-otv-school-list": "abc-owned",
    "sinclair-next-ftptransfer": "sinclair-ftptransfer",
    "cox-arc-closing": "cox",
    "graham-arc-school-closings": "graham",
    "allen-blox-ftp2-frame": "allen",
    "hubbard-schoolalert-asset": "hubbard",
    "spectrum-raven-json": "spectrum",
    "news12-jsp": "news12",
}
_GROUP_FAMILIES: dict[str, str] = {
    "FOX Television Stations": "fox-files",
    "CBS News and Stations": "cbs-feeds",
}
_NEWSTICKER_VARIANTS = frozenset(
    {
        "newsticker-export",
        "newsticker-county-select",
        "closings-table-currently-no",
        "sinclair-next-external-newsticker",
    }
)


@dataclass(frozen=True, slots=True)
class Override:
    """The market of a record whose market text names a region, not a market."""

    basis: Basis
    values: tuple[str, ...]
    """DMA labels (``dma``/``dma-in-states``), states (``statewide``) or
    ``ST|County name`` (``county``)."""
    reason: str


_NYC = "New York, NY - CT - NJ - PA DMA"
_FLASHALERT_DMAS = (
    "Portland, OR - WA DMA",
    "Eugene, OR DMA",
    "Colorado Springs - Pueblo, CO DMA",
    "Spokane, WA - ID - MT - OR DMA",
    "Bend, OR DMA",
    "Seattle - Tacoma, WA DMA",
    "Yakima - Pasco - Richland - Kennewick, WA - OR DMA",
    "Boise, ID - OR DMA",
    "Medford - Klamath Falls, OR - CA DMA",
)
_NEWS12 = "a News 12 region inside the New York market"
MARKET_OVERRIDES: Mapping[str, Override] = {
    "News 12 LI": Override("dma-in-states", (_NYC,), _NEWS12),
    "News 12 NJ": Override("dma-in-states", (_NYC,), _NEWS12),
    "News 12 WC": Override("dma-in-states", (_NYC,), _NEWS12),
    "News 12 HV": Override("dma-in-states", (_NYC,), _NEWS12),
    "News 12 CT": Override("dma-in-states", (_NYC,), _NEWS12),
    "News 12 BX": Override("dma-in-states", (_NYC,), _NEWS12),
    "News 12 BK": Override("dma-in-states", (_NYC,), _NEWS12),
    "Spectrum News 1 Hudson Valley": Override(
        "dma-in-states", (_NYC,), "the Hudson Valley counties are in the New York market"
    ),
    "Spectrum News 1 Coastal NC": Override(
        "dma-in-states",
        ("Wilmington, NC DMA", "Greenville - New Bern - Washington, NC DMA"),
        "coastal North Carolina's markets (Wilmington; Greenville-New Bern)",
    ),
    "FlashAlert cwc-closures": Override(
        "dma-in-states",
        _FLASHALERT_DMAS,
        "the nine regions the check lists: Portland, Eugene, Colorado Springs, Spokane, "
        "Bend, Seattle, Tri-Cities, Boise, Medford",
    ),
    "FlashAlert emergency XML": Override(
        "dma-in-states", _FLASHALERT_DMAS, "the same regions as FlashAlert's closures page"
    ),
    "ECC": Override("dma", ("Chicago, IL - IN DMA",), "the Chicago aggregator"),
    "WeatherThreat": Override(
        "dma-in-states",
        (
            "Cheyenne - Scottsbluff - Sterling, WY - NE DMA",
            "Lincoln & Hastings - Kearney Plus, NE - KS DMA",
        ),
        "the markets of its known media ids: KNEB (Scottsbluff) and KHGI/KFXL (Kearney)",
    ),
    "WDEL SnoWatch": Override(
        "dma-in-states", ("Philadelphia, PA - DE - NJ DMA",), "Wilmington DE radio"
    ),
    "EventDelay": Override(
        "dma-in-states", ("Philadelphia, PA - DE - NJ DMA",), "WDEL's channel, Wilmington DE"
    ),
    "NJ 101.5": Override("statewide", ("NJ",), "New Jersey statewide, by county"),
    "Delaware DNS": Override("statewide", ("DE",), "Delaware statewide"),
    "WVEIS": Override("statewide", ("WV",), "West Virginia statewide"),
    "RIBA": Override(
        "dma-in-states",
        ("Providence, RI - New Bedford, MA DMA",),
        "Rhode Island statewide plus nearby Massachusetts",
    ),
    "WJAR": Override(
        "dma-in-states",
        ("Providence, RI - New Bedford, MA DMA",),
        "frames the Rhode Island Broadcasters' list",
    ),
    "WFRD": Override(
        "dma-in-states",
        ("Burlington, VT - Plattsburgh, NY DMA",),
        "Hanover-Lebanon NH (Grafton County) and White River Junction VT (Windsor County): "
        "the crosswalk puts both counties in the Burlington - Plattsburgh market",
    ),
    "North Country Public Radio storm list": Override(
        "dma-in-states",
        ("Watertown, NY DMA", "Burlington, VT - Plattsburgh, NY DMA"),
        "the markets of Watertown and Plattsburgh, which the record names (with Canton)",
    ),
    "KXXO Mixx 96.1 school closings": Override(
        "dma-in-states",
        ("Seattle - Tacoma, WA DMA",),
        "Olympia WA radio: the crosswalk's metro column gives Thurston County as the Olympia "
        "PMSA, in the Seattle - Tacoma market",
    ),
    "Kern County AlertLine": Override("county", ("CA|Kern",), "a county system"),
    "Sonoma COE school closures": Override("county", ("CA|Sonoma",), "a county office"),
    "Santa Cruz COE school closures": Override("county", ("CA|Santa Cruz",), "a county office"),
}


class PriorityError(ValueError):
    """A research file or reference does not have the expected shape."""


@dataclass(frozen=True, slots=True)
class Source:
    """One first-hand record."""

    name: str
    file: str
    group: str
    variant: str
    market: str
    states: tuple[str, ...]
    link: str | None
    robots_page: str
    robots_data: str
    closings_url: str | None
    data_url: str | None
    notes: str = ""

    @property
    def stale_since(self) -> str | None:
        """The page's own last-updated date when it is before :data:`STALE_BEFORE`."""
        stamp = last_updated(self.notes)
        return stamp if stamp is not None and int(stamp[:4]) < STALE_BEFORE else None

    @property
    def robots_blocked(self) -> bool:
        """Whether robots.txt disallows the page or the list file (not merely unreadable)."""
        return self.robots_page.startswith("disallowed") or self.robots_data.startswith(
            "disallowed"
        )


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def read_firsthand(folder: Path) -> list[Source]:
    """Read every record of the first-hand check files in ``folder``.

    Raises:
        PriorityError: a file is not a list of records with the documented fields.
    """
    sources: list[Source] = []
    for name in FIRSTHAND_FILES:
        records = json.loads((folder / name).read_text(encoding="utf-8"))
        if not isinstance(records, list):
            raise PriorityError(f"{name}: not a list of records")
        for record in records:
            if not isinstance(record, dict):
                raise PriorityError(f"{name}: a record is not an object")
            ident = record.get("call_sign") or record.get("source_id")
            variant, group = record.get("variant"), record.get("group")
            market = record.get("market") or record.get("market_or_region")
            states = record.get("states")
            if not all(isinstance(v, str) for v in (ident, variant, group, market)):
                raise PriorityError(f"{name}: record {ident!r} lacks a documented field")
            if not isinstance(states, list):
                raise PriorityError(f"{name}: record {ident!r} has no state list")
            found = record.get("robots")
            robots: dict[str, object] = found if isinstance(found, dict) else {}
            endpoint = record.get("data_endpoint")
            link = record.get("sources_json_id") or record.get("lead_id")
            sources.append(
                Source(
                    name=str(ident),
                    file=name,
                    group=str(group),
                    variant=str(variant),
                    market=str(market),
                    states=tuple(str(state) for state in states),
                    link=str(link) if isinstance(link, str) else None,
                    robots_page=_text(robots.get("page")),
                    robots_data=_text(robots.get("data")),
                    closings_url=record.get("closings_url") or None,
                    data_url=_text(endpoint.get("url")) if isinstance(endpoint, dict) else None,
                    notes=_text(record.get("notes")),
                )
            )
    names = Counter(source.name for source in sources)
    doubled = sorted(name for name, count in names.items() if count > 1)
    if doubled:
        raise PriorityError(f"records share a name: {doubled}")
    return sources


def read_anchors(path: Path) -> dict[str, list[tuple[str, str]]]:
    """Return ``sources.json`` station id to its market anchors, as (city, state)."""
    document = json.loads(path.read_text(encoding="utf-8"))
    stations = document.get("stations") if isinstance(document, dict) else None
    if not isinstance(stations, list):
        raise PriorityError(f"{path.name}: no station list")
    anchors: dict[str, list[tuple[str, str]]] = {}
    for station in stations:
        if not isinstance(station, dict) or not isinstance(station.get("id"), str):
            continue
        pairs = []
        for anchor in station.get("market_anchors") or []:
            if isinstance(anchor, str) and "|" in anchor:
                city, state = anchor.split("|", 1)
                pairs.append((city, state))
        anchors[str(station["id"])] = pairs
    return anchors


def _counted_family(source: Source) -> tuple[str, str]:
    variant = source.variant
    blocked = " (robots.txt disallows the list)" if source.robots_blocked else ""
    rules: tuple[tuple[str | None, str], ...] = (
        (_VENDOR_FAMILIES.get(variant), f"shared list: {variant}{blocked}"),
        (_VARIANT_FAMILIES.get(variant), f"{variant}{blocked}"),
        (_GROUP_FAMILIES.get(source.group), f"{source.group}: {variant}{blocked}"),
        (
            "newsticker" if variant in _NEWSTICKER_VARIANTS else None,
            f"NewsTicker-format file: {variant}{blocked}",
        ),
    )
    for family, reason in rules:
        if family is not None:
            return family, reason
    return "rest", f"one-off: {variant}{blocked}"


def family_of(source: Source) -> tuple[str | None, str]:
    """Return the family a record belongs to (``None`` when it does not count) and why."""
    variant = source.variant
    if source.name in NAME_EXCLUSIONS:
        return None, NAME_EXCLUSIONS[source.name]
    if source.name in LISTS_NOT_READ:
        return LISTS_NOT_READ[source.name]
    if variant in LIST_VARIANTS:
        return _counted_family(source)
    reason = NOT_LISTS.get(variant)
    if reason is None:
        raise PriorityError(f"{source.name}: variant {variant!r} is not classified")
    return None, reason


# --- markets ---------------------------------------------------------------------------------

_STATE_TOKEN = re.compile(r"^[A-Z]{2}$")
_TRAILING_STATE = re.compile(r"^(.*\S)\s+([A-Z]{2})$")


def _city(text: str) -> str:
    value = text.upper().replace(".", " ").replace("'", "")
    value = re.sub(r"\bFT\b", "FORT", value)
    value = re.sub(r"\bST\b", "SAINT", value)
    value = re.sub(r"\bMT\b", "MOUNT", value)
    return re.sub(r"[^A-Z]", "", value)


def parse_label(label: str) -> tuple[list[str], list[str]]:
    """Return a DMA label's cities (normalized, in order) and states."""
    body = label.rstrip("*").strip()
    body = body.removesuffix(" DMA").strip()
    extra = re.findall(r"\(([^)]*)\)", body)
    body = re.sub(r"\([^)]*\)", " ", body)
    cities: list[str] = []
    states: list[str] = []
    for raw in re.split(r"[-,&/]", body):
        token = raw.strip()
        if not token:
            continue
        if _STATE_TOKEN.match(token):
            states.append(token)
        else:
            cities.append(_city(token))
    cities.extend(_city(text) for text in extra)
    return cities, states


@dataclass(frozen=True, slots=True)
class MarketMatch:
    """How a record's market was found."""

    dmas: tuple[str, ...]
    basis: Basis
    how: str
    note: str = ""


class MarketResolver:
    """Finds a record's DMA labels in the crosswalk."""

    def __init__(self, labels: Iterable[str], anchors: Mapping[str, list[tuple[str, str]]]):
        self.labels = sorted(labels)
        self.parsed = {label: parse_label(label) for label in self.labels}
        self.anchors = anchors

    def _match_part(self, tokens: list[str], states: Sequence[str]) -> list[str]:
        if not tokens:
            return []
        first = tokens[0]
        hits = [
            label
            for label, (cities, label_states) in self.parsed.items()
            if first in cities and (not states or set(states) & set(label_states))
        ]
        if len(hits) <= 1:
            return hits
        scores = {label: sum(token in self.parsed[label][0] for token in tokens) for label in hits}
        best = max(scores.values())
        hits = [label for label in hits if scores[label] == best]
        if len(hits) > 1:
            leading = [label for label in hits if self.parsed[label][0][0] == first]
            if len(leading) == 1:
                return leading
        return hits

    def from_text(self, market: str, states: Sequence[str]) -> list[str]:
        """Return the DMA labels a market text names (empty when unsure)."""
        text = re.sub(r"\([^)]*\)", " ", market)
        inside = re.findall(r"\(([^)]*)\)", market)
        found: list[str] = []
        for raw in re.split(r"\s+and\s+", text):
            part = raw.strip()
            if not part:
                continue
            part_states = list(states)
            trailing = _TRAILING_STATE.match(part)
            if trailing:
                part, part_states = trailing[1], [trailing[2]]
            tokens = [
                _city(token)
                for token in re.split(r"[-,/]", part)
                if token.strip() and not _STATE_TOKEN.match(token.strip())
            ]
            hits = self._match_part([token for token in tokens if token], part_states)
            if len(hits) != 1:
                for name in inside:
                    hits = self._match_part([_city(name)], states)
                    if len(hits) == 1:
                        break
            if len(hits) != 1:
                return []
            found.extend(hits)
        return sorted(set(found))

    def from_anchors(self, link: str | None) -> list[str]:
        """Return the DMA labels of a ``sources.json`` record's anchors (empty when unsure)."""
        found: list[str] = []
        for city, state in self.anchors.get(link or "", []):
            hits = self._match_part([_city(city)], [state])
            if len(hits) != 1:
                return []
            found.extend(hits)
        return sorted(set(found))

    def resolve(self, source: Source) -> MarketMatch | None:
        """Return the record's market, or ``None`` when neither text nor anchors settle it."""
        override = MARKET_OVERRIDES.get(source.name)
        if override is not None:
            return MarketMatch(override.values, override.basis, "override", override.reason)
        basis: Basis = "dma" if source.file == FIRSTHAND_FILES[0] else _basis_for(source)
        text = self.from_text(source.market, source.states)
        if text:
            return MarketMatch(tuple(text), basis, "market text")
        anchored = self.from_anchors(source.link)
        if anchored:
            return MarketMatch(tuple(anchored), basis, "sources.json anchors")
        return None


def _basis_for(source: Source) -> Basis:
    regional = ("Regional system", "Statewide system", "Vendor", "Vendor/aggregator", "Aggregator")
    if source.group in regional or source.group.startswith("Independent (Spectrum"):
        return "dma-in-states"
    return "dma"


@dataclass(frozen=True, slots=True)
class Resolved:
    """A counted record, its family and its counties."""

    source: Source
    family: str
    reason: str
    market: MarketMatch
    counties: frozenset[str]


def market_counties(
    market: MarketMatch,
    source: Source,
    dmas: DmaCounties,
    county_ids: Mapping[tuple[str, str], str],
    state_counties: Mapping[str, frozenset[str]],
) -> frozenset[str]:
    """Return the directory county codes of a record's market (see the module docstring).

    Raises:
        PriorityError: a label, state or county the market names is not known.
    """
    if market.basis == "statewide":
        found: set[str] = set()
        for state in market.dmas:
            if state not in state_counties:
                raise PriorityError(f"{source.name}: no counties for state {state}")
            found |= state_counties[state]
        return frozenset(found)
    if market.basis == "county":
        found = set()
        for value in market.dmas:
            state, name = value.split("|", 1)
            fips = county_ids.get((state, normalize_county(name)))
            if fips is None:
                raise PriorityError(f"{source.name}: county {value!r} is not in the Gazetteer")
            found.add(fips)
        return frozenset(found)
    found = set()
    for label in market.dmas:
        if label not in dmas.by_dma:
            raise PriorityError(f"{source.name}: market {label!r} is not in the crosswalk")
        found.update(dmas.by_dma[label])
    if market.basis == "dma-in-states":
        wanted = set(source.states)
        found = {fips for fips in found if _state_of(fips, state_counties) in wanted}
    return frozenset(found)


def _state_of(fips: str, state_counties: Mapping[str, frozenset[str]]) -> str | None:
    for state, codes in state_counties.items():
        if fips in codes:
            return state
    return None


@dataclass(slots=True)
class Classification:
    """Every record, sorted into families or left out."""

    resolved: list[Resolved] = field(default_factory=list)
    left_out: list[tuple[Source, str]] = field(default_factory=list)
    unresolved: list[Source] = field(default_factory=list)


def classify(
    sources: Sequence[Source],
    resolver: MarketResolver,
    dmas: DmaCounties,
    county_ids: Mapping[tuple[str, str], str],
    state_counties: Mapping[str, frozenset[str]],
) -> Classification:
    """Sort every record into a family with its counties, or leave it out."""
    result = Classification()
    for source in sources:
        family, reason = family_of(source)
        if family is None:
            result.left_out.append((source, reason))
            continue
        market = resolver.resolve(source)
        if market is None:
            result.unresolved.append(source)
            continue
        counties = market_counties(market, source, dmas, county_ids, state_counties)
        result.resolved.append(Resolved(source, family, reason, market, counties))
    return result


# --- gains -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SchoolWeights:
    """Schools per directory county, and the sum of their closure weights."""

    schools: Mapping[str, int]
    weighted: Mapping[str, float]

    def totals(self, counties: Iterable[str]) -> tuple[int, float]:
        """Return (schools, weighted schools) in ``counties``."""
        codes = set(counties)
        return (
            sum(self.schools.get(fips, 0) for fips in codes),
            sum(self.weighted.get(fips, 0.0) for fips in codes),
        )


@dataclass(frozen=True, slots=True)
class Step:
    """One family's place in the ranking."""

    rank: int
    family: str
    new_counties: int
    new_schools: int
    new_weighted: float
    cumulative_schools: int
    cumulative_weighted: float


def greedy_order(
    family_counties: Mapping[str, frozenset[str]],
    baseline: frozenset[str],
    weights: SchoolWeights,
) -> list[Step]:
    """Rank families by the weighted schools each adds beyond everything taken before it.

    Ties (families adding nothing new, most often) are broken by the family's gain
    over the baseline alone, then by its id.
    """
    covered = set(baseline)
    cumulative_schools, cumulative_weighted = weights.totals(covered)
    alone = {
        family: weights.totals(counties - covered) for family, counties in family_counties.items()
    }
    remaining = dict(family_counties)
    steps: list[Step] = []
    while remaining:
        gains = {
            family: (*weights.totals(counties - covered), family)
            for family, counties in remaining.items()
        }
        family = max(
            sorted(remaining),
            key=lambda name: (
                round(gains[name][1], 6),
                gains[name][0],
                round(alone[name][1], 6),
                alone[name][0],
                name,
            ),
        )
        new = remaining.pop(family) - covered
        schools, weighted = weights.totals(new)
        covered |= new
        cumulative_schools += schools
        cumulative_weighted += weighted
        steps.append(
            Step(
                rank=len(steps) + 1,
                family=family,
                new_counties=len(new),
                new_schools=schools,
                new_weighted=weighted,
                cumulative_schools=cumulative_schools,
                cumulative_weighted=cumulative_weighted,
            )
        )
    return steps


_LAST_UPDATED = re.compile(r"Last updated: (\d{2})/(\d{2})/(\d{4})")
STALE_BEFORE = 2024
"""A list whose page says it was last updated before this year is marked stale."""


def last_updated(notes: str) -> str | None:
    """Return the ``Last updated: MM/DD/YYYY`` date a record's notes quote, as ISO, if any."""
    found = _LAST_UPDATED.search(notes)
    if found is None:
        return None
    month, day, year = found.groups()
    return f"{year}-{month}-{day}"


BASELINE_GROUPS: frozenset[str] = frozenset({"gray", "hearst"})
"""The station groups whose working lists are the baseline (station ids ``<group>-<call>``)."""


def station_group(station_id: str) -> str:
    """Return the group of a coverage station id (``gray-wsfa`` is Gray's)."""
    return station_id.split("-", 1)[0]


def _station_ids(value: object, groups: Collection[str] | None) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        item
        for item in value
        if isinstance(item, str) and (groups is None or station_group(item) in groups)
    ]


def baseline_counties(
    coverage: Mapping[str, object], groups: Collection[str] | None = BASELINE_GROUPS
) -> tuple[frozenset[str], frozenset[str]]:
    """Return the counties a working source of ``groups`` lists, and those any of them lists.

    ``groups`` are station groups (:data:`BASELINE_GROUPS`, Gray and Hearst, by
    default); ``None`` takes every group's sources.

    Raises:
        PriorityError: ``coverage.json`` has no county table.
    """
    counties = coverage.get("counties")
    if not isinstance(counties, dict):
        raise PriorityError("coverage.json has no county table")
    working: set[str] = set()
    listed: set[str] = set()
    for fips, info in counties.items():
        if not isinstance(info, dict):
            continue
        if _station_ids(info.get("working"), groups):
            working.add(fips)
            listed.add(fips)
        if _station_ids(info.get("not_working"), groups):
            listed.add(fips)
    return frozenset(working), frozenset(listed)


def working_stations(coverage: Mapping[str, object]) -> dict[str, int]:
    """Return the number of coverage stations whose state is ``working``, by group."""
    stations = coverage.get("stations")
    found: Counter[str] = Counter()
    if isinstance(stations, dict):
        for station_id, info in stations.items():
            if isinstance(info, dict) and info.get("state") == "working":
                found[station_group(str(station_id))] += 1
    return dict(sorted(found.items()))


GRAY_COVERED_VARIANTS = frozenset({"moved-to-gray", "gray-fusion-count"})
"""Variants left out because the Gray adapter covers the list."""
_GRAY_FILE = re.compile(r"grayfilestore-([a-z0-9]+)")


def gray_cover(
    left_out: Sequence[tuple[Source, str]], stations: Mapping[str, Sequence[RegistryStation]]
) -> list[JSONValue]:
    """Check the records left out as covered by Gray against the registry.

    ``stations`` is keyed by call sign, each call sign's entries with Gray's first
    (:func:`snowlight.weights.registered.by_call_sign`). A record is looked up by
    its call sign (the first of a shared name) and by the Gray file its check names
    (``grayfilestore-<call>``): the first of those with a Gray entry is reported,
    else the first with any entry (so a record the registry files under another
    platform shows as such in ``registry_platform``).
    """
    checked: list[JSONValue] = []
    for source, reason in left_out:
        if source.variant not in GRAY_COVERED_VARIANTS:
            continue
        own = source.name.split("/")[0]
        via_file = [call.upper() for call in _GRAY_FILE.findall(source.data_url or "")]
        candidates = [(own, "call sign"), *((c, "its Gray data file") for c in via_file)]
        found: RegistryStation | None = None
        via: str | None = None
        for gray_only in (True, False):
            for call, how in candidates:
                entries = [
                    entry
                    for entry in stations.get(call, ())
                    if entry.platform == GRAY_PLATFORM or not gray_only
                ]
                if entries:
                    found, via = entries[0], how
                    break
            if found is not None:
                break
        checked.append(
            {
                "name": source.name,
                "variant": source.variant,
                "reason": reason,
                "registry_station": None if found is None else found.id,
                "registry_platform": None if found is None else found.platform,
                "registry_status": None if found is None else found.status,
                "registry_counties": None if found is None else len(found.fips),
                "found_by": via,
            }
        )
    return checked


def family_members(classification: Classification) -> dict[str, list[Resolved]]:
    """Group the counted records by family."""
    members: dict[str, list[Resolved]] = defaultdict(list)
    for item in classification.resolved:
        members[item.family].append(item)
    return {family: sorted(items, key=lambda r: r.source.name) for family, items in members.items()}


def member_json(item: Resolved) -> dict[str, JSONValue]:
    """Return one counted record as kept in ``station-priority.json``."""
    return {
        "name": item.source.name,
        "group": item.source.group,
        "variant": item.source.variant,
        "market": item.source.market,
        "states": list(item.source.states),
        "markets": list(item.market.dmas),
        "basis": item.market.basis,
        "found_by": item.market.how,
        "note": item.market.note or None,
        "robots_blocked": item.source.robots_blocked,
        "stale_since": item.source.stale_since,
        "counted_because": item.reason,
        "counties": len(item.counties),
        "research_file": item.source.file,
    }
