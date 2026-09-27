"""Counting closure-type school days for every school, and averaging them.

The metric of :mod:`snowlight.weights.count` (weighted distinct school days per
school year under the 6 AM rule; school days, the rule and the code weights are
the same) is counted here for each school instead of each county:

* a **zone row** reaches the schools inside the polygon of the zone version its
  product was issued for (:mod:`snowlight.weights.zonepolys`,
  :mod:`snowlight.weights.schoolzones`), and the schools
  :func:`snowlight.weights.schoolzones.place_by_year` gives that version in that
  school year (a school outside its own zone's outline of the year, within 2 km);
* a **county row** (a county-coded product) reaches every school placed in that
  county (:mod:`snowlight.weights.schools`);
* a **storm-based polygon** (FF.W; :mod:`snowlight.weights.polygons`) reaches the
  schools inside it, and the county rows of its event are then not used;
* a school placed ``county`` (farther than 2 km from every zone) takes its
  county's county-rule counts (:mod:`snowlight.weights.count`), every code, and
  the county's school years left out; a school that fell back to its county for
  one school year only (its own zone's outline of that year farther than 2 km) takes
  them for that school year.

The 6 AM rule is read in the school's own time zones (:mod:`snowlight.weights.schoolzones`).

Schools that the same rows reach, in the same time zones, have the same counts,
so the rows are counted once per *cell* of such schools (:class:`CellKey`: the NWS
county, the time zones, the polygon keys reaching them, the polygon keys reaching
them in one school year only and the school years they take their county's counts
for); each school then adds its own storm-polygon days. A school's figures are its own:

* ``days_per_year``: weighted distinct school days per school year counted;
* ``any_days_per_year``, per-code distinct days (``code_days``), named code
  subsets (``subset_days_per_year``) and each school year's weighted days
  (``by_year``), as for a county in :mod:`snowlight.weights.count`.

Every school counts every school year (a zone version's polygon is always known,
or the build stops), except a school that fell back to its county, which keeps
its county's years (:attr:`SchoolDays.years_counted`); for a school year it fell
back to its county alone, it keeps or leaves out that year as its county does.
"""

from collections import Counter, defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import NamedTuple

import numpy as np
import numpy.typing as npt
import polars as pl
import shapely

from snowlight.weights.archive import EventRow, SchoolYearFile
from snowlight.weights.codes import BY_CODE
from snowlight.weights.count import Tally, counted_days, school_days, school_year_of
from snowlight.weights.polygons import POLYGON_CODES, PolygonFile, PolygonRow
from snowlight.weights.schools import Placement
from snowlight.weights.schoolzones import (
    NEAREST_KM,
    YearPlacement,
    ZonePlacement,
    distance_km,
    school_points,
)
from snowlight.weights.zonepolys import VersionBook

type Ints = npt.NDArray[np.int64]
type Floats = npt.NDArray[np.float64]


class CellKey(NamedTuple):
    """What makes the rows reaching a group of schools the same."""

    fips: str
    time_zones: tuple[str, ...]
    polygons: frozenset[str]
    """Polygon keys whose rows reach the cell in every school year."""
    polygon_years: frozenset[tuple[str, int]]
    """(polygon key, school year): that key's rows of that school year reach the cell."""
    county_years: frozenset[int]
    """School years the cell takes its county's county-rule counts for."""
    fallback: bool
    """Placed ``county``: the county rule in every school year."""


class SchoolCountError(ValueError):
    """The rows cannot be counted for the schools."""


@dataclass(frozen=True, slots=True)
class DayIndex:
    """Every school day of the school years counted, numbered in order."""

    years: tuple[int, ...]
    days: tuple[date, ...]
    position: Mapping[date, int]
    year_position: Ints
    """For each day, the position of its school year in :attr:`years`."""
    starts: Ints
    """The first day of each school year."""

    @classmethod
    def of(cls, years: Sequence[int]) -> "DayIndex":
        """Number the school days of ``years`` (in the order given, which must be increasing)."""
        if list(years) != sorted(set(years)):
            raise SchoolCountError(f"school years {list(years)} are not increasing")
        days: list[date] = []
        year_position: list[int] = []
        starts: list[int] = []
        for position, year in enumerate(years):
            starts.append(len(days))
            found = school_days(year)
            days.extend(found)
            year_position.extend([position] * len(found))
        return cls(
            tuple(years),
            tuple(days),
            {day: index for index, day in enumerate(days)},
            np.array(year_position, dtype=np.int64),
            np.array(starts, dtype=np.int64),
        )

    def per_year(self, values: Floats) -> Floats:
        """Sum ``values`` (one per day) by school year."""
        return np.add.reduceat(values, self.starts)


@dataclass(slots=True)
class Cells:
    """The schools grouped by the rows that reach them."""

    keys: list[CellKey] = field(default_factory=list)
    of_school: list[int] = field(default_factory=list)
    by_polygon: dict[str, list[int]] = field(default_factory=dict)
    by_polygon_year: dict[tuple[str, int], list[int]] = field(default_factory=dict)
    by_county: dict[str, list[int]] = field(default_factory=dict)
    county_years: dict[int, list[int]] = field(default_factory=dict)
    """School year to the cells that take their county's counts for it."""

    def schools(self) -> Counter[int]:
        """Schools per cell."""
        return Counter(self.of_school)


def build_cells(
    zoned: ZonePlacement, members: Mapping[str, Ints], by_year: YearPlacement | None = None
) -> Cells:
    """Group the schools of ``zoned`` into cells (see the module docstring).

    ``members`` is :func:`snowlight.weights.schoolzones.memberships`' answer and
    ``by_year`` :func:`snowlight.weights.schoolzones.place_by_year`'s.
    """
    reaching: list[set[str]] = [set() for _ in zoned.schools]
    for polygon, positions in members.items():
        for position in positions.tolist():
            reaching[position].add(polygon)
    extras = by_year.extras() if by_year is not None else {}
    county_years = by_year.county_years if by_year is not None else {}
    cells = Cells()
    ids: dict[CellKey, int] = {}
    for position, school in enumerate(zoned.schools):
        fallback = school.method == "county"
        key = CellKey(
            school.fips,
            school.time_zones,
            frozenset() if fallback else frozenset(reaching[position]),
            frozenset() if fallback else extras.get(position, frozenset()),
            frozenset() if fallback else county_years.get(position, frozenset()),
            fallback,
        )
        if key not in ids:
            ids[key] = len(cells.keys)
            cells.keys.append(key)
        cells.of_school.append(ids[key])
    by_polygon: dict[str, list[int]] = defaultdict(list)
    by_polygon_year: dict[tuple[str, int], list[int]] = defaultdict(list)
    by_county: dict[str, list[int]] = defaultdict(list)
    by_county_year: dict[int, list[int]] = defaultdict(list)
    for cell, key in enumerate(cells.keys):
        if key.fallback:
            continue
        by_county[key.fips].append(cell)
        for polygon in key.polygons:
            by_polygon[polygon].append(cell)
        for pair in key.polygon_years:
            by_polygon_year[pair].append(cell)
        for year in key.county_years:
            by_county_year[year].append(cell)
    cells.by_polygon = dict(by_polygon)
    cells.by_polygon_year = dict(by_polygon_year)
    cells.by_county = dict(by_county)
    cells.county_years = dict(by_county_year)
    return cells


@dataclass(slots=True)
class SchoolCountStats:
    """What the counting did with the rows."""

    zone_rows: int = 0
    zone_rows_reaching_schools: int = 0
    county_rows: int = 0
    county_rows_reaching_schools: int = 0
    county_rows_without_schools: Counter[str] = field(default_factory=Counter)
    polygon_county_rows_replaced: int = 0
    """County rows of polygon-code events that have polygon rows (not used)."""
    polygon_events_without_polygons: Counter[str] = field(default_factory=Counter)
    """Polygon-code events with no polygon row in the polygon file (their county rows used)."""
    polygon_rows: int = 0
    polygon_rows_reaching_schools: int = 0
    polygon_school_rows: int = 0
    fallback_cells: int = 0
    zone_rows_reaching_by_year: int = 0
    """Zone rows reaching a school through :attr:`CellKey.polygon_years`."""
    county_year_cells: int = 0
    """Cells taking their county's counts for some school year only."""


@dataclass(slots=True)
class SchoolTally:
    """The counted days: per cell and code, and per school for storm polygons."""

    index: DayIndex
    cells: Cells
    cell_days: list[dict[str, set[int]]]
    polygon_days: dict[int, dict[str, set[int]]] = field(default_factory=dict)
    cell_left_out: dict[int, frozenset[int]] = field(default_factory=dict)
    """Cell to the school years left out (their county's, for the school years they take
    their county's counts for)."""
    stats: SchoolCountStats = field(default_factory=SchoolCountStats)


def _positions(index: DayIndex, days: Iterable[date]) -> set[int]:
    return {index.position[day] for day in days if day in index.position}


def _by_zones(
    cells: Iterable[int], zones_of: Sequence[tuple[str, ...]]
) -> dict[tuple[str, ...], list[int]]:
    grouped: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for cell in cells:
        grouped[zones_of[cell]].append(cell)
    return grouped


def count_schools(  # noqa: PLR0913
    files: Sequence[SchoolYearFile],
    polygon_files: Mapping[int, PolygonFile],
    book: VersionBook,
    cells: Cells,
    *,
    state_fips: Mapping[str, str],
    school_points: shapely.STRtree,
    zoned: ZonePlacement,
    county_tally: Tally,
    county_left_out: Mapping[str, Collection[int]],
) -> SchoolTally:
    """Count every school year's rows for the cells and schools (see the module docstring).

    ``school_points`` is a tree of the schools' points in the order of
    ``zoned.schools``; ``county_tally`` and ``county_left_out`` are the county
    rule's counts and incomplete years, for the schools placed ``county``.

    Raises:
        SchoolCountError: a school year has no polygon file.
        ZonePolygonError: a zone row's version has no polygon.
    """
    index = DayIndex.of([file.year for file in files])
    tally = SchoolTally(index, cells, [defaultdict(set) for _ in cells.keys])
    zones_of = [key.time_zones for key in cells.keys]
    stats = tally.stats
    for file in files:
        polygons = polygon_files.get(file.year)
        if polygons is None:
            raise SchoolCountError(f"no storm-polygon file for {file.label}")
        with_polygons = polygons.events
        year_days = frozenset(school_days(file.year))
        county_year = frozenset(cells.county_years.get(file.year, ()))
        for row in file.rows:
            if row.code in POLYGON_CODES:
                if row.event_key in with_polygons:
                    stats.polygon_county_rows_replaced += 1
                    continue
                stats.polygon_events_without_polygons[row.event_key] += 1
            targets = _row_targets(row, file.year, cells, book, state_fips, stats)
            if county_year:
                targets = [cell for cell in targets if cell not in county_year]
            for zones, group in _by_zones(targets, zones_of).items():
                found = counted_days(row.begin, row.end, row.product_issued, zones) & year_days
                if not found:
                    continue
                hits = _positions(index, found)
                for cell in group:
                    tally.cell_days[cell][row.code] |= hits
        _count_polygons(
            tally, polygons, school_points, zoned, year_days=year_days, county_year=county_year
        )
    _fill_fallback(tally, county_tally, county_left_out)
    return tally


def _row_targets(  # noqa: PLR0913, PLR0917
    row: EventRow,
    year: int,
    cells: Cells,
    book: VersionBook,
    state_fips: Mapping[str, str],
    stats: SchoolCountStats,
) -> list[int]:
    """Return the cells a zone or county row reaches, counting it in ``stats``."""
    if row.ugc[2] == "Z":
        stats.zone_rows += 1
        key = book.key_of(row)
        by_year = cells.by_polygon_year.get((key, year), [])
        targets = cells.by_polygon.get(key, []) + by_year
        stats.zone_rows_reaching_schools += bool(targets)
        stats.zone_rows_reaching_by_year += bool(by_year)
        return targets
    stats.county_rows += 1
    fips = state_fips.get(row.ugc[:2], "??") + row.ugc[3:]
    targets = cells.by_county.get(fips, [])
    if targets:
        stats.county_rows_reaching_schools += 1
    else:
        stats.county_rows_without_schools[fips] += 1
    return targets


def _count_polygons(  # noqa: PLR0913
    tally: SchoolTally,
    polygons: PolygonFile,
    school_points: shapely.STRtree,
    zoned: ZonePlacement,
    *,
    year_days: frozenset[date],
    county_year: frozenset[int],
) -> None:
    stats = tally.stats
    of_school = tally.cells.of_school
    for row in polygons.rows:
        stats.polygon_rows += 1
        reached = [
            position
            for position in school_points.query(row.geometry, predicate="intersects").tolist()
            if zoned.schools[position].method != "county" and of_school[position] not in county_year
        ]
        if not reached:
            continue
        stats.polygon_rows_reaching_schools += 1
        grouped: dict[tuple[str, ...], list[int]] = defaultdict(list)
        for position in reached:
            grouped[zoned.schools[position].time_zones].append(position)
        for zones, group in grouped.items():
            found = counted_days(row.begin, row.end, row.product_issued, zones) & year_days
            if not found:
                continue
            hits = _positions(tally.index, found)
            for position in group:
                stats.polygon_school_rows += 1
                tally.polygon_days.setdefault(position, defaultdict(set))[row.code] |= hits


def _fill_fallback(
    tally: SchoolTally, county_tally: Tally, county_left_out: Mapping[str, Collection[int]]
) -> None:
    for cell, key in enumerate(tally.cells.keys):
        if key.fallback:
            tally.stats.fallback_cells += 1
            years: Collection[int] = tally.index.years
        elif key.county_years:
            tally.stats.county_year_cells += 1
            years = key.county_years
        else:
            continue
        for year in years:
            for code, by_day in county_tally.year(key.fips, year).by_code.items():
                tally.cell_days[cell][code] |= _positions(tally.index, by_day)
        left_out = frozenset(county_left_out.get(key.fips, ())) & frozenset(years)
        if left_out:
            tally.cell_left_out[cell] = left_out


@dataclass(frozen=True, slots=True)
class SchoolDays:
    """One school's averages over the school years counted for it."""

    days_per_year: float
    any_days_per_year: float
    subset_days_per_year: Mapping[str, float]
    code_days: Mapping[str, int]
    """Distinct school days per code over the school years counted (unweighted)."""
    by_year: Mapping[int, tuple[float, int] | None]
    """School year to (weighted days, distinct days); ``None`` for a year left out."""
    years_counted: tuple[int, ...]

    def code_days_per_year(self, code: str) -> float:
        """Return ``code``'s distinct school days per school year counted."""
        return self.code_days.get(code, 0) / len(self.years_counted)


def _best(index: DayIndex, codes: Mapping[str, Ints], wanted: Collection[str] | None) -> Floats:
    best = np.zeros(len(index.days), dtype=np.float64)
    for code, days in codes.items():
        if wanted is not None and code not in wanted:
            continue
        if len(days):
            best[days] = np.maximum(best[days], BY_CODE[code].weight)
    return best


def _summary(
    index: DayIndex,
    codes: Mapping[str, Ints],
    subsets: Mapping[str, frozenset[str]],
    left_out: frozenset[int],
) -> SchoolDays:
    keep = np.array([year not in left_out for year in index.years], dtype=bool)
    counted = int(keep.sum())
    if not counted:
        raise SchoolCountError("a school has every school year left out")
    day_kept = keep[index.year_position]
    best = _best(index, codes, None)
    weighted = index.per_year(best)
    distinct = index.per_year((best > 0).astype(np.float64))
    subset_totals = {
        name: float(index.per_year(_best(index, codes, members))[keep].sum())
        for name, members in subsets.items()
    }
    by_year: dict[int, tuple[float, int] | None] = {}
    for position, year in enumerate(index.years):
        by_year[year] = (
            (float(weighted[position]), int(distinct[position])) if keep[position] else None
        )
    return SchoolDays(
        days_per_year=float(weighted[keep].sum()) / counted,
        any_days_per_year=float(distinct[keep].sum()) / counted,
        subset_days_per_year={name: total / counted for name, total in subset_totals.items()},
        code_days={code: int(day_kept[days].sum()) for code, days in codes.items() if len(days)},
        by_year=by_year,
        years_counted=tuple(year for position, year in enumerate(index.years) if keep[position]),
    )


def summarize_schools(
    tally: SchoolTally, subsets: Mapping[str, frozenset[str]]
) -> list[SchoolDays]:
    """Return every school's :class:`SchoolDays`, in the order of the placement.

    Schools of one cell with the same storm-polygon days share one summary.
    """
    arrays: dict[int, dict[str, Ints]] = {}
    shared: dict[tuple[int, frozenset[tuple[str, frozenset[int]]]], SchoolDays] = {}
    found: list[SchoolDays] = []
    for position, cell in enumerate(tally.cells.of_school):
        extra = tally.polygon_days.get(position, {})
        signature = frozenset((code, frozenset(days)) for code, days in extra.items() if days)
        key = (cell, signature)
        if key not in shared:
            if cell not in arrays:
                arrays[cell] = {
                    code: np.array(sorted(days), dtype=np.int64)
                    for code, days in tally.cell_days[cell].items()
                }
            codes = dict(arrays[cell])
            for code, days in signature:
                merged = set(days)
                if code in codes:
                    merged |= set(codes[code].tolist())
                codes[code] = np.array(sorted(merged), dtype=np.int64)
            shared[key] = _summary(
                tally.index, codes, subsets, tally.cell_left_out.get(cell, frozenset())
            )
        found.append(shared[key])
    return found


def school_frame_points(frame: pl.DataFrame, placement: Placement) -> shapely.STRtree:
    """Return a tree of the placed schools' points, in the order of ``placement.schools``."""
    return shapely.STRtree(school_points(frame, placement))


@dataclass(frozen=True, slots=True)
class RecountSchool:
    """One school for :func:`recount`: where it is and which zone rows it takes."""

    point: shapely.Point
    fips: str
    time_zones: tuple[str, ...]
    own_zone: str | None = None
    """The school's own zone code (placed ``inside`` or ``nearest``), for the school-year
    rule of :func:`snowlight.weights.schoolzones.place_by_year`."""


@dataclass(slots=True)
class RecountIndex:
    """The rows of every school year, grouped once for :func:`recount`."""

    years: tuple[int, ...]
    by_key: dict[str, list[tuple[int, EventRow]]] = field(default_factory=dict)
    by_ugc: dict[str, list[tuple[int, EventRow]]] = field(default_factory=dict)
    by_county: dict[str, list[tuple[int, EventRow]]] = field(default_factory=dict)
    storms: list[tuple[int, PolygonRow]] = field(default_factory=list)
    storm_bounds: Floats = field(default_factory=lambda: np.zeros((0, 4)))
    keys: list[str] = field(default_factory=list)
    key_bounds: Floats = field(default_factory=lambda: np.zeros((0, 4)))


def recount_index(
    files: Sequence[SchoolYearFile],
    polygon_files: Mapping[int, PolygonFile],
    book: VersionBook,
    state_fips: Mapping[str, str],
) -> RecountIndex:
    """Group the rows by polygon key, zone code and county (see :func:`recount`)."""
    index = RecountIndex(years=tuple(file.year for file in files))
    by_key: dict[str, list[tuple[int, EventRow]]] = defaultdict(list)
    by_ugc: dict[str, list[tuple[int, EventRow]]] = defaultdict(list)
    by_county: dict[str, list[tuple[int, EventRow]]] = defaultdict(list)
    for file in files:
        storms = polygon_files[file.year]
        for row in file.rows:
            if row.code in POLYGON_CODES and row.event_key in storms.events:
                continue
            if row.ugc[2] == "Z":
                by_key[book.key_of(row)].append((file.year, row))
                by_ugc[row.ugc].append((file.year, row))
            else:
                by_county[state_fips.get(row.ugc[:2], "??") + row.ugc[3:]].append((file.year, row))
        index.storms.extend((file.year, storm) for storm in storms.rows)
    index.by_key, index.by_ugc, index.by_county = dict(by_key), dict(by_ugc), dict(by_county)
    index.storm_bounds = np.array(
        [storm.geometry.bounds for _, storm in index.storms], dtype=np.float64
    ).reshape(-1, 4)
    index.keys = sorted(book.polygons)
    index.key_bounds = np.array(
        [book.polygons[key].bounds for key in index.keys], dtype=np.float64
    ).reshape(-1, 4)
    return index


def _around(bounds: Floats, x: float, y: float) -> list[int]:
    hits = (bounds[:, 0] <= x) & (x <= bounds[:, 2]) & (bounds[:, 1] <= y) & (y <= bounds[:, 3])
    return [int(i) for i in np.flatnonzero(hits)]


@dataclass(frozen=True, slots=True)
class Recounted:
    """What :func:`recount` found for one school."""

    days_per_year: float
    by_year_rows: Mapping[int, frozenset[str]]
    """School year to the polygon keys whose rows the school-year rule added."""
    county_years: frozenset[int]
    years_counted: tuple[int, ...]


def _by_year_rule(
    school: RecountSchool,
    index: RecountIndex,
    book: VersionBook,
    covering: Collection[str],
    nearest_km: float,
) -> tuple[dict[int, set[str]], set[int]]:
    """Apply the school-year rule directly: the keys it adds per year, and the county years."""
    added: dict[int, set[str]] = defaultdict(set)
    county: set[int] = set()
    if school.own_zone is None:
        return added, county
    own: dict[int, set[str]] = defaultdict(set)
    for year, row in index.by_ugc.get(school.own_zone, []):
        own[year].add(book.key_of(row))
    inside = set(covering)
    for year, keys in sorted(own.items()):
        missed = keys - inside
        if not missed:
            continue
        elsewhere = any(
            row.ugc != school.own_zone and at == year
            for key in inside
            for at, row in index.by_key.get(key, [])
        )
        if elsewhere:
            continue
        away = {
            key: distance_km(book.polygons[key], school.point.x, school.point.y) for key in missed
        }
        if keys & inside:
            added[year] = {key for key in missed if away[key] <= nearest_km}
        elif all(value <= nearest_km for value in away.values()):
            added[year] = missed
        else:
            county.add(year)
    return added, county


def recount(  # noqa: PLR0913
    school: RecountSchool,
    index: RecountIndex,
    book: VersionBook,
    *,
    county_tally: Tally | None = None,
    county_left_out: Collection[int] = (),
    nearest_km: float = NEAREST_KM,
) -> Recounted:
    """Count one school's weighted days per school year directly, as a check of the cells.

    Each row is tested for the school on its own: a zone row counts when its
    version's polygon covers the school's point, or when the school-year rule of
    :func:`snowlight.weights.schoolzones.place_by_year` (re-applied here from the rows
    of the school's own zone) gives the school that version in that school year; a
    county row when it names the school's county; a storm polygon when it covers the
    point (the county rows of events with polygons were set aside when the index was
    built). A school year the rule sends to the county takes ``county_tally``'s days of
    the school's county instead, and is left out when it is in ``county_left_out``. No
    cell, tree or day array of :func:`count_schools` is used.

    Raises:
        SchoolCountError: the rule sends a school year to the county and no county
            tally is given, or every school year is left out.
    """
    x, y = school.point.x, school.point.y
    covering = [
        index.keys[i]
        for i in _around(index.key_bounds, x, y)
        if book.polygons[index.keys[i]].covers(school.point)
    ]
    added, county_years = _by_year_rule(school, index, book, covering, nearest_km)
    reached = [pair for key in covering for pair in index.by_key.get(key, [])]
    for year, keys in added.items():
        reached += [pair for key in keys for pair in index.by_key.get(key, []) if pair[0] == year]
    reached += index.by_county.get(school.fips, [])
    spans = {
        (year, row.begin, row.end, row.product_issued, row.code)
        for year, row in reached
        if year not in county_years
    }
    for i in _around(index.storm_bounds, x, y):
        year, storm = index.storms[i]
        if year not in county_years and storm.geometry.covers(school.point):
            spans.add((year, storm.begin, storm.end, storm.product_issued, storm.code))
    best: dict[date, float] = {}
    for year, begin, end, issued, code in spans:
        for day in counted_days(begin, end, issued, school.time_zones) & frozenset(
            school_days(year)
        ):
            best[day] = max(best.get(day, 0.0), BY_CODE[code].weight)
    if county_years:
        if county_tally is None:
            raise SchoolCountError("a school year falls back to the county and no county tally")
        for year in sorted(county_years):
            for code, by_day in county_tally.year(school.fips, year).by_code.items():
                for day in by_day:
                    best[day] = max(best.get(day, 0.0), BY_CODE[code].weight)
    left_out = county_years & set(county_left_out)
    kept = tuple(year for year in index.years if year not in left_out)
    if not kept:
        raise SchoolCountError("a school has every school year left out")
    total = sum(value for day, value in best.items() if school_year_of(day) in kept)
    return Recounted(
        total / len(kept),
        {year: frozenset(keys) for year, keys in sorted(added.items()) if keys},
        frozenset(county_years),
        kept,
    )
