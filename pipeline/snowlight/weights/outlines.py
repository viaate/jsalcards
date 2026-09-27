"""Checks of the zone mapping against IEM's archived zone outlines (diagnostics only).

The weights map zones to counties only through the NWS correlation files
(:mod:`snowlight.weights.zones`). No release before 2 April 2019 is served, so
products issued earlier are read in that first release, and zones that no
served release holds are left out. IEM keeps an archive of the NWS UGC database
since 2007, with (simplified) outlines:
``https://mesonet.agron.iastate.edu/api/1/nws/ugcs.geojson?valid=<time>``
(documented in IEM's API: "this service takes an optional timestamp flag to
provide an archived version of this database ... For GeoJSON, this service
returns simplified geometries"). This module reads it, for the middle of each
school year concerned (15 January, 12:00 UTC, the time the zone-name check uses),
and measures what share of each zone's outline lies in each NWS county.

It is used three ways; the first two decide something, the third changes
nothing and is reported in ``manifest.json``, the method note and the county
records.

* The zone-name check (:mod:`snowlight.weights.crosscheck`) leaves out, for a
  school year, a zone read in the first release before it took effect whose name
  then differed. The build keeps such a zone when its outline at the time agrees
  with the counties the release lists (:func:`agrees`): the name changed, the
  area did not (``MTZ007`` was "Butte/Blackfoot Region" in 2016 and
  "Butte/Pintlar Region" in the release, over the same four counties).

* Which county-years are incomplete (:attr:`OutlineReport.incomplete`); each is
  left out of its county's average (:mod:`snowlight.weights.count`):

  - a zone's rows are left out (the zone is in no served release, or the name
    check left it out), or reach only some of their counties because the
    release gives a county code the county list lacks (``bp08mr23`` and
    ``bp19se23`` list PAZ077 "Indiana" with 42603 for Indiana County's 42063):
    every county holding at least :data:`MAJOR` of the zone's outline that
    school year, and not reached, misses them. Such a zone with no outline, or
    a county UGC naming a county the list lacks, stops the build, since the
    counties it leaves incomplete would be unknown.
  - a zone was read in a release for products issued before that release took
    effect (``before_first`` and ``nearest``), and the counties the release lists
    disagree with its outline then (:func:`disagreeing`: a county holding at
    least :data:`MAJOR` of the outline that the release does not list, or a
    listed county holding less than :data:`TOUCH`). When the zone's outline in
    the first school year wholly under the served releases
    (:func:`standing_year`, 2019-20) shows the same disagreement, the listing is
    the release's standing reading of that zone, applied alike in every school
    year, and nothing is left out. When it does not (the zone was redrawn), the
    counties it disagreed on then have that school year left out.

* For every zone row left out: how many weighted school days the counties
  holding at least :data:`MAJOR` of its outline (and not reached) would gain if
  the rows counted there (the rule of :mod:`snowlight.weights.count`, applied to the outline's
  counties). This is the size of what leaving them out removes; the weights do
  not include it.

The files are cached at ``<cache>/mesonet.agron.iastate.edu/api-ugcs-geojson/
<date>.geojson`` and never fetched again (the archive of a past date is final).
"""

import json
from collections import Counter, defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import shapely
from shapely.geometry import shape

from snowlight.output import JSONValue
from snowlight.sources.nws.http import CachedFile
from snowlight.sources.nws.shapefile import Polygonal, polygonal
from snowlight.weights.archive import EventRow, SchoolYearFile, school_year_label
from snowlight.weights.cache import WeightsCache
from snowlight.weights.count import Tally, YearCounts, counted_days, school_days, school_year_of
from snowlight.weights.zones import CountyList, ZoneCountyCatalog

OUTLINES_URL = "https://mesonet.agron.iastate.edu/api/1/nws/ugcs.geojson"
MAJOR = 0.05
"""Share of a zone's outline a county must hold to count as covered by it."""
TOUCH = 0.001
"""Share of a zone's outline a listed county must hold for the listing to agree."""


class OutlineError(ValueError):
    """An outline file is not the documented GeoJSON."""


def outline_valid(year: int) -> datetime:
    """Return the archive time read for the school year starting in ``year``."""
    return datetime(year + 1, 1, 15, 12, tzinfo=UTC)


def outlines_url(valid: datetime) -> str:
    """Return the request for the UGC outlines valid at ``valid``."""
    return f"{OUTLINES_URL}?valid={valid.astimezone(UTC):%Y-%m-%dT%H:%M}Z"


@dataclass(frozen=True, slots=True)
class Outline:
    """One UGC's archived outline and name."""

    ugc: str
    name: str
    geometry: Polygonal


class Outlines:
    """One ``ugcs.geojson`` answer: each zone's name, and its outline built when asked for."""

    def __init__(self, features: Mapping[str, tuple[str, dict[str, Any]]]) -> None:
        self._features = dict(features)
        self._built: dict[str, Outline | None] = {}

    def __contains__(self, ugc: object) -> bool:
        return ugc in self._features

    def __len__(self) -> int:
        return len(self._features)

    def get(self, ugc: str) -> Outline | None:
        """Return the zone's outline (``None`` when absent or without area)."""
        if ugc not in self._built:
            found = self._features.get(ugc)
            outline: Outline | None = None
            if found is not None:
                name, raw = found
                geometry = polygonal(shape(raw))
                if geometry is not None and geometry.area > 0:
                    outline = Outline(ugc, name, geometry)
            self._built[ugc] = outline
        return self._built[ugc]


def read_outlines(text: str) -> Outlines:
    """Read a ``ugcs.geojson`` answer: its zone features (county features are skipped).

    Raises:
        OutlineError: the answer is not a feature collection of UGC features.
    """
    document = json.loads(text)
    features = document.get("features") if isinstance(document, dict) else None
    if not isinstance(features, list):
        raise OutlineError("ugcs.geojson: no feature list")
    found: dict[str, tuple[str, dict[str, Any]]] = {}
    for feature in features:
        properties = feature.get("properties") if isinstance(feature, dict) else None
        if not isinstance(properties, dict) or not isinstance(properties.get("ugc"), str):
            raise OutlineError("ugcs.geojson: a feature has no ugc")
        ugc = str(properties["ugc"])
        geometry = feature.get("geometry")
        if ugc[2:3] != "Z" or not isinstance(geometry, dict):
            continue
        found[ugc] = (str(properties.get("name") or ""), geometry)
    return Outlines(found)


def load_outlines(cache: WeightsCache, year: int) -> tuple[Outlines, CachedFile]:
    """Download (or reuse) and read the outlines for one school year."""
    valid = outline_valid(year)
    folder = cache.root / "mesonet.agron.iastate.edu" / "api-ugcs-geojson"
    dest = folder / f"{valid:%Y-%m-%d}.geojson"
    file = cache.fetch(outlines_url(valid), dest)
    return read_outlines(file.path.read_text(encoding="utf-8")), file


class CountyShares:
    """Shares of an outline's area in each NWS county."""

    def __init__(self, counties: CountyList) -> None:
        self.fips = sorted(counties.counties)
        self.geometries = [counties.counties[code].geometry for code in self.fips]
        self.tree = shapely.STRtree(self.geometries)

    def __call__(self, geometry: Polygonal) -> dict[str, float]:
        """Return county FIPS to the share of ``geometry``'s area inside it."""
        area = geometry.area
        shares: dict[str, float] = {}
        for index in self.tree.query(geometry, predicate="intersects").tolist():
            share = geometry.intersection(self.geometries[index]).area / area
            if share > 0:
                shares[self.fips[index]] = share
        return shares


class OutlineBook:
    """IEM's archived outlines, each school year's file loaded when first needed."""

    def __init__(self, cache: WeightsCache, counties: CountyList) -> None:
        self.cache = cache
        self.shares_of = CountyShares(counties)
        self.files: dict[int, CachedFile] = {}
        self._outlines: dict[int, Outlines] = {}
        self._shares: dict[tuple[int, str], dict[str, float]] = {}

    def outline(self, year: int, ugc: str) -> Outline | None:
        """Return a zone's outline in the middle of the school year starting in ``year``."""
        if year not in self._outlines:
            self._outlines[year], self.files[year] = load_outlines(self.cache, year)
        return self._outlines[year].get(ugc)

    def shares(self, year: int, ugc: str) -> dict[str, float] | None:
        """Return county FIPS to the share of the zone's outline in it (``None``: no outline)."""
        key = (year, ugc)
        if key not in self._shares:
            outline = self.outline(year, ugc)
            if outline is None:
                return None
            self._shares[key] = self.shares_of(outline.geometry)
        return self._shares[key]


def disagreeing(listed: Iterable[str], shares: Mapping[str, float]) -> frozenset[str]:
    """Return the counties on which a release's listing of a zone and its outline disagree.

    They are the counties holding at least :data:`MAJOR` of the outline that the
    release does not list, and the listed counties holding less than :data:`TOUCH`.
    """
    listed_set = frozenset(listed)
    unlisted = {fips for fips, share in shares.items() if share >= MAJOR} - listed_set
    uncovered = {fips for fips in listed_set if shares.get(fips, 0.0) < TOUCH}
    return frozenset(unlisted | uncovered)


def agrees(listed: Iterable[str], shares: Mapping[str, float]) -> bool:
    """Whether a release's counties for a zone agree with its outline's shares."""
    return not disagreeing(listed, shares)


def standing_year(catalog: ZoneCountyCatalog) -> int:
    """Return the first school year wholly under the served releases (2019-20)."""
    return school_year_of(catalog.releases[0].valid_from) + 1


@dataclass(slots=True)
class ZoneUse:
    """One zone's rows in one school year that need an outline check."""

    ugc: str
    year: int
    rows: list[EventRow] = field(default_factory=list)
    listed: frozenset[str] = frozenset()
    """The counties of the county list the rows reached (empty when left out)."""
    how: str = ""
    missing: frozenset[str] = frozenset()
    """County codes the rows were given that the county list lacks (the rows never
    reached them)."""

    @property
    def dropped(self) -> bool:
        """Whether the rows reached none of their counties, or not all of them."""
        return not self.listed or bool(self.missing)


@dataclass(slots=True)
class OutlineReport:
    """What the outline checks found."""

    files: dict[int, CachedFile] = field(default_factory=dict)
    compared: Counter[int] = field(default_factory=Counter)
    agreed: Counter[int] = field(default_factory=Counter)
    disagreements: list[dict[str, JSONValue]] = field(default_factory=list)
    left_out: list[dict[str, JSONValue]] = field(default_factory=list)
    missing_outline: list[str] = field(default_factory=list)
    gains: dict[str, dict[str, float]] = field(default_factory=dict)
    """County FIPS to school year to the weighted days its left-out rows would add."""
    incomplete: dict[str, dict[int, set[str]]] = field(default_factory=dict)
    """County FIPS to school year to the zones whose rows could not be counted for it."""
    standing: int | None = None
    """The school year whose outlines tell a standing disagreement from a redrawn zone."""
    touching: list[tuple[str, int, str, float]] = field(default_factory=list)
    """(county, school year, zone, share) for each county holding at least :data:`TOUCH`
    but less than :data:`MAJOR` of a left-out zone's outline."""

    def touching_kept(self) -> list[tuple[str, int, str, float]]:
        """Return :attr:`touching` for the county-years not left out anyway, largest first."""
        kept = [item for item in self.touching if item[1] not in self.incomplete.get(item[0], {})]
        return sorted(kept, key=lambda item: (-item[3], item[0], item[1], item[2]))

    def left_out_years(self) -> dict[str, frozenset[int]]:
        """Return county FIPS to the school years to leave out of its average."""
        return {fips: frozenset(years) for fips, years in sorted(self.incomplete.items())}

    def as_json(self) -> dict[str, JSONValue]:
        """Return the JSON-ready record kept in the internal report."""
        county_years = sum(len(years) for years in self.incomplete.values())
        touching = self.touching_kept()
        return {
            "outline_files": {
                school_year_label(year): file.provenance.as_json()
                for year, file in sorted(self.files.items())
            },
            "major_share": MAJOR,
            "touch_share": TOUCH,
            "standing_school_year": (
                None if self.standing is None else school_year_label(self.standing)
            ),
            "zones_compared": {school_year_label(y): n for y, n in sorted(self.compared.items())},
            "zones_agreeing": {school_year_label(y): n for y, n in sorted(self.agreed.items())},
            "disagreements": list(self.disagreements),
            "left_out_zones": list(self.left_out),
            "zones_without_outline": list(self.missing_outline),
            "counties_with_school_years_left_out": len(self.incomplete),
            "county_school_years_left_out": county_years,
            "below_major_share_kept": {
                "county_school_years": len({(fips, year) for fips, year, _, _ in touching}),
                "largest": [
                    {
                        "fips": fips,
                        "school_year": school_year_label(year),
                        "ugc": ugc,
                        "share": round(share, 4),
                    }
                    for fips, year, ugc, share in touching[:5]
                ],
            },
            "school_years_left_out": {
                fips: {
                    school_year_label(year): [*sorted(ugcs)] for year, ugcs in sorted(years.items())
                }
                for fips, years in sorted(self.incomplete.items())
            },
        }

    def mark(self, fips: str, year: int, ugc: str) -> None:
        """Record that ``ugc``'s rows could not be counted for ``fips`` in ``year``."""
        self.incomplete.setdefault(fips, {}).setdefault(year, set()).add(ugc)


def zone_uses(
    files: Sequence[SchoolYearFile],
    catalog: ZoneCountyCatalog,
    known: Collection[str] | None = None,
) -> dict[tuple[int, str, bool], ZoneUse]:
    """Collect the rows to check, by school year, UGC and whether rows were dropped.

    Zone rows read in a release before it took effect, zone rows left out, and
    (with ``known``, the county list's codes) rows given a county code the county
    list lacks: a county UGC naming such a county, or a zone the release lists
    with one (``bp08mr23`` lists PAZ077 "Indiana" with 42603, not Indiana
    County's 42063).
    """
    first = catalog.releases[0].valid_from
    uses: dict[tuple[int, str, bool], ZoneUse] = {}
    for file in files:
        for row in file.rows:
            day = row.product_issued.date()
            listed: frozenset[str]
            how: str
            if row.ugc[2] == "C":
                prefix = catalog.state_fips.get(row.ugc[:2])
                listed = frozenset() if prefix is None else frozenset({prefix + row.ugc[3:]})
                how = "county"
            elif catalog.excluded(row.ugc, day):
                listed, how = frozenset(), "left_out_renamed"
            else:
                release, how = catalog.zone_release(row.ugc, day)
                listed = release.counties[row.ugc] if release is not None else frozenset()
            missing = frozenset() if known is None else frozenset(listed - set(known))
            checked = how not in {"county", "in_effect"} and not (how == "nearest" and day >= first)
            if not missing and not checked:
                continue
            key = (file.year, row.ugc, bool(missing))
            use = uses.setdefault(key, ZoneUse(row.ugc, file.year))
            use.rows.append(row)
            use.listed, use.how, use.missing = listed - missing, how, missing
    return uses


def _gain(
    year: int, fips: str, rows: Sequence[EventRow], counties: CountyList, tally: Tally
) -> float:
    """Return the weighted days ``rows`` would add to one county's school year."""
    county = counties.counties[fips]
    before = tally.year(fips, year)
    after = YearCounts()
    for code, by_day in before.by_code.items():
        for day, ugcs in by_day.items():
            after.by_code[code][day] = set(ugcs)
    days = frozenset(school_days(year))
    for row in rows:
        hits = counted_days(row.begin, row.end, row.product_issued, county.time_zones)
        for day in hits & days:
            after.by_code[row.code][day].add(row.ugc)
    return after.weighted() - before.weighted()


def check_outlines(
    book: OutlineBook,
    files: Sequence[SchoolYearFile],
    catalog: ZoneCountyCatalog,
    counties: CountyList,
    tally: Tally,
) -> OutlineReport:
    """Run the checks and find the incomplete county-years (see the module docstring).

    Raises:
        OutlineError: rows of a zone were left out and IEM has no outline of it then.
    """
    standing = standing_year(catalog)
    report = OutlineReport(standing=standing)
    uses = zone_uses(files, catalog, counties.counties)
    by_year: dict[int, list[ZoneUse]] = defaultdict(list)
    for use in uses.values():
        by_year[use.year].append(use)
    pending: dict[tuple[int, str], list[EventRow]] = defaultdict(list)
    for year in sorted(by_year):
        for use in sorted(by_year[year], key=lambda item: (item.ugc, item.dropped)):
            label = school_year_label(year)
            if use.ugc[2] == "C":
                raise OutlineError(
                    f"{use.ugc} {label}: {len(use.rows)} rows name county "
                    f"{', '.join(sorted(use.missing))}, which the county list lacks, so the "
                    "county-years they leave incomplete are unknown"
                )
            outline = book.outline(year, use.ugc)
            shares = book.shares(year, use.ugc)
            if outline is None or shares is None:
                if use.dropped:
                    raise OutlineError(
                        f"{use.ugc} {label}: {len(use.rows)} rows left out and IEM has no "
                        "outline of the zone then, so the counties they leave incomplete are "
                        "unknown"
                    )
                report.missing_outline.append(f"{use.ugc} {label}")
                continue
            if not use.dropped:
                report.compared[year] += 1
                if agrees(use.listed, shares):
                    report.agreed[year] += 1
                    continue
                report.disagreements.append(_disagreement(book, report, use, standing))
                continue
            targets = sorted(
                f for f, share in shares.items() if share >= MAJOR and f not in use.listed
            )
            report.touching.extend(
                (fips, year, use.ugc, share)
                for fips, share in sorted(shares.items())
                if TOUCH <= share < MAJOR and fips not in use.listed
            )
            added = {fips: _gain(year, fips, use.rows, counties, tally) for fips in targets}
            for fips in targets:
                pending[(year, fips)].extend(use.rows)
                report.mark(fips, year, use.ugc)
            report.left_out.append(
                {
                    "ugc": use.ugc,
                    "school_year": label,
                    "iem_name": outline.name,
                    "rows": len(use.rows),
                    "why": "county_not_in_county_list" if use.missing else use.how,
                    "counties_reached": [*sorted(use.listed)],
                    "counties_not_in_county_list": [*sorted(use.missing)],
                    "outline_counties": _rounded(shares),
                    "weighted_days_it_would_add": {k: round(v, 2) for k, v in added.items()},
                }
            )
    gains: dict[str, dict[str, float]] = defaultdict(dict)
    for (year, fips), rows in sorted(pending.items()):
        value = _gain(year, fips, rows, counties, tally)
        if value > 0:
            gains[fips][school_year_label(year)] = value
    report.gains = dict(gains)
    report.files = dict(sorted(book.files.items()))
    return report


def _rounded(shares: Mapping[str, float]) -> dict[str, JSONValue]:
    return {k: round(v, 3) for k, v in sorted(shares.items()) if v >= TOUCH}


def _disagreement(
    book: OutlineBook, report: OutlineReport, use: ZoneUse, standing: int
) -> dict[str, JSONValue]:
    """Record one disagreeing zone and leave out the county-years it makes incomplete.

    ``standing`` is the school year whose outline shows whether the disagreement
    is the release's standing reading of the zone (see the module docstring).
    """
    outline = book.outline(use.year, use.ugc)
    shares = book.shares(use.year, use.ugc) or {}
    then = disagreeing(use.listed, shares)
    later = book.shares(standing, use.ugc)
    later_rounded: JSONValue = None if later is None else _rounded(later)
    same = later is not None and disagreeing(use.listed, later) == then
    left_out = [] if same else sorted(then)
    for fips in left_out:
        report.mark(fips, use.year, use.ugc)
    return {
        "ugc": use.ugc,
        "school_year": school_year_label(use.year),
        "iem_name": None if outline is None else outline.name,
        "rows": len(use.rows),
        "read_as": use.how,
        "listed": [*sorted(use.listed)],
        "outline_shares": _rounded(shares),
        "disagreeing_counties": [*sorted(then)],
        "standing_outline_shares": later_rounded,
        "same_in_standing_school_year": same,
        "counties_left_out_for_the_year": [*left_out],
    }
