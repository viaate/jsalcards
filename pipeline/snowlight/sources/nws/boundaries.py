"""NWS public forecast zone and county boundary releases, keyed by UGC code.

The NWS publishes each boundary set as a versioned zipped shapefile on a page
that lists, for every release it still serves, the date the release takes
effect, the file and its MD5 sum:

* public forecast zones: https://www.weather.gov/gis/PublicZones (``z_DDmmYY.zip``)
* counties: https://www.weather.gov/gis/Counties (``c_DDmmYY.zip``)

:func:`parse_releases` reads that table. :class:`BoundaryCatalog` downloads a
release on first use (checking the listed MD5), reads it, and answers "which
geometry did UGC ``XXZ123`` have on this date": the release whose validity covers
the date (from its valid date to the next release's). A date before the earliest
release still served has no NWS geometry here, and the catalog says so rather
than substituting a later boundary.

UGC codes are built from the attributes the NWS documents on those pages:

* zone: ``STATE + "Z" + ZONE`` (e.g. ``NY`` + ``072`` gives ``NYZ072``);
* county: ``STATE + "C" + FIPS[2:]`` (e.g. ``NM`` + ``35009`` gives ``NMC009``).

Several records can share one UGC (a zone or county split between two warning
areas); their polygons are merged.
"""

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urljoin, urlsplit

import shapely
from selectolax.parser import HTMLParser

from snowlight.output import JSONValue
from snowlight.sources.nws.http import CachedFile, HttpCache
from snowlight.sources.nws.shapefile import Polygonal, ShapefileError, polygonal, read_zip

type BoundaryKind = Literal["zone", "county"]

PAGES: dict[BoundaryKind, str] = {
    "zone": "https://www.weather.gov/gis/PublicZones",
    "county": "https://www.weather.gov/gis/Counties",
}
_FILE_PATTERNS: dict[BoundaryKind, re.Pattern[str]] = {
    "zone": re.compile(r"^/source/gis/Shapefiles/WSOM/z_\d{2}[a-z]{2}\d{2}\.zip$"),
    "county": re.compile(r"^/source/gis/Shapefiles/County/c_\d{2}[a-z]{2}\d{2}\.zip$"),
}
_DATE = re.compile(r"\b(\d{1,2}) ([A-Z][a-z]+) (\d{4})\b")
_MD5 = re.compile(r"\b[0-9a-f]{32}\b")
_UGC = re.compile(r"^[A-Z]{2}[CZ]\d{3}$")
PAGE_MAX_AGE = timedelta(hours=12)


class BoundaryError(RuntimeError):
    """A boundary release page or file is not what this module expects."""


@dataclass(frozen=True, slots=True)
class BoundaryRelease:
    """One release listed on an NWS boundary page."""

    kind: BoundaryKind
    valid_from: date
    url: str
    md5: str
    records: int | None

    def as_json(self) -> dict[str, JSONValue]:
        """Return the JSON-ready record kept in internal manifests."""
        return {
            "kind": self.kind,
            "md5": self.md5,
            "records": self.records,
            "url": self.url,
            "valid_from": self.valid_from.isoformat(),
        }


def parse_releases(html: str, kind: BoundaryKind, page_url: str) -> list[BoundaryRelease]:
    """Return the releases a boundary page lists, oldest first.

    Every table row that links a release file must also show its valid date and
    MD5 sum; a row that does not is an error, not something to skip.

    Raises:
        BoundaryError: no release is listed, or a listed row is incomplete.
    """
    releases: list[BoundaryRelease] = []
    for row in HTMLParser(html).css("tr"):
        links = [
            str(anchor.attributes.get("href") or "")
            for anchor in row.css("a")
            if _FILE_PATTERNS[kind].match(str(anchor.attributes.get("href") or ""))
        ]
        if not links:
            continue
        if len(set(links)) != 1:
            raise BoundaryError(f"{page_url}: a row links several release files: {links}")
        cells = [cell.text(separator=" ", strip=True) for cell in row.css("td")]
        text = " ".join(cells)
        when = _DATE.search(text)
        md5 = _MD5.search(text)
        if when is None or md5 is None:
            raise BoundaryError(f"{page_url}: the row for {links[0]} lacks a valid date or MD5")
        valid = datetime.strptime(" ".join(when.groups()), "%d %B %Y").date()
        counts = [int(cell) for cell in cells if cell.isdigit()]
        releases.append(
            BoundaryRelease(
                kind=kind,
                valid_from=valid,
                url=urljoin(page_url, links[0]),
                md5=md5.group(0),
                records=counts[0] if len(counts) == 1 else None,
            )
        )
    if not releases:
        raise BoundaryError(f"{page_url}: no {kind} release is listed")
    releases.sort(key=lambda release: release.valid_from)
    dates = [release.valid_from for release in releases]
    if len(set(dates)) != len(dates):
        raise BoundaryError(f"{page_url}: two releases share a valid date")
    return releases


@dataclass(frozen=True, slots=True)
class BoundarySet:
    """The geometries of one release, by UGC code."""

    release: BoundaryRelease
    file: CachedFile
    areas: dict[str, Polygonal]
    time_zones: dict[str, tuple[str, ...]]
    county_fips: dict[str, str]


def ugc_kind(ugc: str) -> BoundaryKind:
    """Return whether ``ugc`` names a zone (``XXZnnn``) or a county (``XXCnnn``)."""
    if not _UGC.match(ugc):
        raise ValueError(f"not a UGC code: {ugc!r}")
    return "zone" if ugc[2] == "Z" else "county"


def read_boundary_set(release: BoundaryRelease, file: CachedFile) -> BoundarySet:
    """Read a downloaded release into a :class:`BoundarySet`.

    Raises:
        BoundaryError: the file does not have the documented attributes, or its
            record count differs from the one the page lists.
    """
    try:
        records = read_zip(file.path)
    except ShapefileError as error:
        raise BoundaryError(f"{release.url}: {error}") from error
    if release.records is not None and len(records) != release.records:
        raise BoundaryError(
            f"{release.url}: {len(records)} records, the page lists {release.records}"
        )
    parts: dict[str, list[Polygonal]] = defaultdict(list)
    zones: dict[str, set[str]] = defaultdict(set)
    fips: dict[str, str] = {}
    for record in records:
        attrs = record.attributes
        state = str(attrs.get("STATE") or "")
        if release.kind == "zone":
            number = str(attrs.get("ZONE") or "")
            ugc = f"{state}Z{number}"
            if attrs.get("STATE_ZONE") != f"{state}{number}":
                raise BoundaryError(f"{release.url}: record {record.index} STATE_ZONE mismatch")
        else:
            code = str(attrs.get("FIPS") or "")
            if not re.fullmatch(r"\d{5}", code):
                raise BoundaryError(f"{release.url}: record {record.index} FIPS {code!r}")
            ugc = f"{state}C{code[2:]}"
            fips[ugc] = code
        if not _UGC.match(ugc):
            raise BoundaryError(f"{release.url}: record {record.index} gives UGC {ugc!r}")
        if record.geometry is not None:
            parts[ugc].append(record.geometry)
        zone_code = str(attrs.get("TIME_ZONE") or "")
        if zone_code:
            zones[ugc].add(zone_code)
    areas: dict[str, Polygonal] = {}
    for ugc, pieces in parts.items():
        merged = pieces[0] if len(pieces) == 1 else polygonal(shapely.union_all(pieces))
        if merged is not None:
            areas[ugc] = merged
    return BoundarySet(
        release=release,
        file=file,
        areas=areas,
        time_zones={ugc: tuple(sorted(codes)) for ugc, codes in zones.items()},
        county_fips=fips,
    )


class BoundaryCatalog:
    """The NWS boundary releases, downloaded and read on first use."""

    def __init__(
        self,
        cache: HttpCache,
        cache_dir: Path,
        releases: dict[BoundaryKind, list[BoundaryRelease]] | None = None,
    ) -> None:
        """Read release lists from the NWS pages, or use ``releases`` when given."""
        self.cache = cache
        self.cache_dir = cache_dir
        self._releases: dict[BoundaryKind, list[BoundaryRelease]] = {
            kind: sorted(items, key=lambda release: release.valid_from)
            for kind, items in (releases or {}).items()
        }
        self._pages: dict[BoundaryKind, CachedFile] = {}
        self._sets: dict[str, BoundarySet] = {}

    def _path(self, url: str) -> Path:
        parts = urlsplit(url)
        segments = [segment for segment in parts.path.split("/") if segment]
        if not parts.hostname or any(segment in {".", ".."} for segment in segments):
            raise BoundaryError(f"unexpected URL {url!r}")
        return self.cache_dir.joinpath(parts.hostname, *segments)

    def releases(self, kind: BoundaryKind) -> list[BoundaryRelease]:
        """Return the releases the NWS page lists for ``kind`` (page cached for 12 hours)."""
        if kind not in self._releases:
            page_url = PAGES[kind]
            page = self.cache.fetch(page_url, self._path(page_url + ".html"), max_age=PAGE_MAX_AGE)
            html = page.path.read_text(encoding="utf-8", errors="replace")
            self._releases[kind] = parse_releases(html, kind, page_url)
            self._pages[kind] = page
        return self._releases[kind]

    def release_for(self, kind: BoundaryKind, day: date) -> BoundaryRelease | None:
        """Return the release in effect on ``day``, or ``None`` before the earliest one."""
        chosen: BoundaryRelease | None = None
        for release in self.releases(kind):
            if release.valid_from <= day:
                chosen = release
        return chosen

    def load(self, release: BoundaryRelease) -> BoundarySet:
        """Download (or reuse) and read ``release``."""
        loaded = self._sets.get(release.url)
        if loaded is None:
            file = self.cache.fetch(release.url, self._path(release.url), expected_md5=release.md5)
            loaded = read_boundary_set(release, file)
            self._sets[release.url] = loaded
        return loaded

    def boundaries_for(self, kind: BoundaryKind, day: date) -> BoundarySet | None:
        """Return the boundary set in effect on ``day``, or ``None`` if none is served."""
        release = self.release_for(kind, day)
        return None if release is None else self.load(release)

    def lookup(self, ugc: str, day: date) -> tuple[Polygonal | None, BoundarySet | None]:
        """Return the geometry ``ugc`` had on ``day`` and the set it came from.

        The geometry is ``None`` when no release covers ``day`` or the release in
        effect has no such UGC.
        """
        boundaries = self.boundaries_for(ugc_kind(ugc), day)
        if boundaries is None:
            return None, None
        return boundaries.areas.get(ugc), boundaries

    def provenance(self) -> dict[str, JSONValue]:
        """Return the pages consulted and the files read, for internal manifests."""
        return {
            "pages": {
                kind: page.provenance.as_json() for kind, page in sorted(self._pages.items())
            },
            "files": [
                {"release": item.release.as_json(), "file": item.file.provenance.as_json()}
                for _url, item in sorted(self._sets.items())
            ],
        }
