"""The weather check: which alerts covered a school during a time window.

An alert is stored as one or more :class:`AlertArea` records, each with its own
in-effect span (a zone can be cancelled before the rest of a warning, a
storm-based polygon is replaced when the forecaster redraws it) and its own
footprint:

* ``geometry``: a polygon (a storm-based warning) or the boundary of one NWS
  zone or county, in longitude/latitude;
* ``counties``: the five-digit county FIPS codes the area names, for areas the
  NWS issued by county.

Exact and approximate footprints
================================

A footprint is ``exact`` when it is the NWS's own polygon or boundary. It is
``approximate`` when only a simplified outline of the boundary is known (the
archive's outlines, for dates before the earliest NWS boundary release still
served). An approximate area says how far the true boundary can be from its
outline (``tolerance``, in degrees) and can carry a ``hint``: the same zone or
county in the nearest NWS release. The hint only ever makes an answer less
certain (it catches parts a simplified outline dropped, and boundaries that
moved between releases); it never reports coverage on its own.

Coverage
========

Every match is ``covered`` or ``uncertain``; a place with no row for an alert
was not covered by it (as far as the sources show). For a place with a point:

* an exact area covers the point when its geometry covers it (boundary
  included);
* an approximate county area is decided by the place's county FIPS when that
  code is one the NWS county files use (``known_counties``): the same code
  covers the place and any other code does not. The match is reported as
  ``exact``, since no boundary was needed;
* any other approximate area covers the point when the point is inside the
  outline, farther than ``tolerance`` from it, and inside the hint when there is
  one. It is ``uncertain`` when the point is within ``tolerance`` of the
  outline, or inside the hint. Otherwise it does not match;
* a point near a boundary *shared* by approximate areas of the same alert (two
  adjacent zones under one warning) is uncertain for each area alone but
  covered by the alert: when the point is farther than ``tolerance`` from the
  outline of the union of those areas (one basis at a time, and inside one of
  their hints if they have hints), the alert covers it. NWS zones tile the land
  without gaps, as do counties, so a point that deep inside the union is inside
  one of the true boundaries;
* a county-coded area with no boundary covers the point on the county FIPS;
* areas marked ``point_matching=False`` (the county list of a storm-based
  warning, which is wider than its polygon) are skipped.

For a place without a point, an area that is drawn or coded as the place's
county covers it, and the county list of a storm-based warning makes it
``uncertain`` (the polygon may cover only part of the county). Zone areas cannot
be checked without a point (a zone is not a county) and are not reported.

In every case the area's span must overlap the query window: it starts before
the window ends and ends after the window starts (an open end means "until
further notice"). Areas whose end is not after their start never took effect
and are dropped when the index is built.

Matches are merged per alert: one row per place and alert. A ``covered`` row is
built from the areas that covered the place, an ``uncertain`` row from the areas
that might have; either way it has the earliest start and latest end among them,
the most specific basis (``polygon`` before ``zone`` before ``county``) and
``exact`` precision if any of them was exact.

Lookups use an STR-tree over the area bounding boxes (widened by their
tolerance and hint) and prepared geometries, so checking a hundred thousand
schools takes a second or two.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import numpy as np
import numpy.typing as npt
import polars as pl
import shapely
from shapely import STRtree

from snowlight.sources.nws.shapefile import Polygonal
from snowlight.weather.hazards import Hazard, Level
from snowlight.weather.timezones import LocalWindow

type Basis = Literal["polygon", "zone", "county"]
type Precision = Literal["exact", "approximate"]
type Coverage = Literal["covered", "uncertain"]
type Moment = datetime | Sequence[datetime] | npt.NDArray[np.datetime64]

BASES: tuple[Basis, ...] = ("polygon", "zone", "county")
PRECISIONS: tuple[Precision, ...] = ("exact", "approximate")
COVERAGES: tuple[Coverage, ...] = ("covered", "uncertain")
_BASIS_BY_NAME: dict[str, Basis] = {name: name for name in BASES}
_PRECISION_BY_NAME: dict[str, Precision] = {name: name for name in PRECISIONS}
_COVERAGE_BY_NAME: dict[str, Coverage] = {name: name for name in COVERAGES}
_EXACT = PRECISIONS.index("exact")
_COVERED = COVERAGES.index("covered")
_UNCERTAIN = COVERAGES.index("uncertain")
_NO_MATCH = -1
_SHARED_EDGE_AREAS = 2  # a shared edge needs two outlines
_OPEN_END = np.iinfo(np.int64).max
_NS = 1_000_000_000

MATCH_SCHEMA: dict[str, pl.DataType] = {
    "row": pl.Int64(),
    "key": pl.String(),
    "event": pl.String(),
    "hazard": pl.String(),
    "level": pl.String(),
    "severity": pl.String(),
    "start": pl.Datetime("us", "UTC"),
    "end": pl.Datetime("us", "UTC"),
    "coverage": pl.String(),
    "basis": pl.String(),
    "precision": pl.String(),
    "traces": pl.List(pl.String()),
}


@dataclass(frozen=True, slots=True)
class AlertInfo:
    """What an alert is: a stable key, its NWS event name, grouping and severity."""

    key: str
    event: str
    hazard: Hazard
    level: Level
    severity: str | None


@dataclass(frozen=True, slots=True)
class AlertArea:
    """Where and when one alert (or one part of it) was in effect.

    ``tolerance`` (degrees) is how far the true boundary can be from an
    approximate ``geometry``; it is zero for exact areas. ``hint`` is the same
    zone or county in the nearest NWS release, for approximate areas only.
    """

    alert: AlertInfo
    start: datetime
    end: datetime | None
    geometry: Polygonal | None
    counties: frozenset[str]
    basis: Basis
    precision: Precision
    point_matching: bool = True
    trace: str = ""
    tolerance: float = 0.0
    hint: Polygonal | None = None

    def __post_init__(self) -> None:
        if self.precision == "approximate":
            if self.geometry is None or not self.tolerance > 0:
                raise ValueError(
                    f"{self.trace}: an approximate area needs an outline and a tolerance"
                )
        elif self.tolerance != 0 or self.hint is not None:
            raise ValueError(f"{self.trace}: only approximate areas take a tolerance or a hint")


@dataclass(frozen=True, slots=True)
class AlertMatch:
    """One alert that covered (or may have covered) the queried place in the window.

    ``traces`` name the source records behind the match (the NWS alert id and
    zone, or the archive day file, row and NWS product id).
    """

    alert: AlertInfo
    start: datetime
    end: datetime | None
    coverage: Coverage
    basis: Basis
    precision: Precision
    traces: tuple[str, ...] = ()


def _ns(moment: datetime) -> int:
    if moment.tzinfo is None:
        raise ValueError(f"naive datetime {moment!r}: pass an aware time")
    delta = moment.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86_400 + delta.seconds) * _NS + delta.microseconds * 1000


def _ns_array(values: Moment, count: int, name: str) -> npt.NDArray[np.int64]:
    if isinstance(values, datetime):
        return np.full(count, _ns(values), dtype=np.int64)
    if isinstance(values, np.ndarray):
        if not np.issubdtype(values.dtype, np.datetime64):
            raise TypeError(f"{name} must be datetime64 values")
        result = values.astype("datetime64[ns]").astype(np.int64)
    else:
        result = np.array([_ns(value) for value in values], dtype=np.int64)
    if result.shape != (count,):
        raise ValueError(f"{name} has {result.shape[0]} values for {count} places")
    return result


def _envelopes(
    geometries: npt.NDArray[np.object_],
    tolerance: npt.NDArray[np.float64],
    hints: npt.NDArray[np.object_],
) -> npt.NDArray[np.object_]:
    """Bounding boxes of each geometry widened by its tolerance, joined with its hint's."""
    bounds = shapely.bounds(geometries)
    bounds[:, :2] -= tolerance[:, None]
    bounds[:, 2:] += tolerance[:, None]
    extra = shapely.bounds(hints)
    has = ~np.isnan(extra[:, 0])
    bounds[has, :2] = np.minimum(bounds[has, :2], extra[has, :2])
    bounds[has, 2:] = np.maximum(bounds[has, 2:], extra[has, 2:])
    boxes: npt.NDArray[np.object_] = shapely.box(
        bounds[:, 0], bounds[:, 1], bounds[:, 2], bounds[:, 3]
    )
    return boxes


@dataclass(frozen=True, slots=True)
class _Places:
    """The queried places: points, whether their county code is known, UTC windows (ns)."""

    lon: npt.NDArray[np.float64]
    lat: npt.NDArray[np.float64]
    has_point: npt.NDArray[np.bool_]
    known: npt.NDArray[np.bool_]
    start: npt.NDArray[np.int64]
    end: npt.NDArray[np.int64]


@dataclass(frozen=True, slots=True)
class _Pairs:
    """Candidate (place, area) pairs and how each area answered for its place."""

    rows: npt.NDArray[np.int64]
    areas: npt.NDArray[np.int64]
    coverage: npt.NDArray[np.int8]
    precision: npt.NDArray[np.int8]

    @staticmethod
    def join(parts: Sequence["_Pairs"]) -> "_Pairs":
        """Concatenate ``parts`` (no parts gives no pairs)."""

        def cat(arrays: list[npt.NDArray[np.generic]], dtype: type[np.generic]) -> npt.NDArray[Any]:
            return np.concatenate(arrays).astype(dtype) if arrays else np.array([], dtype=dtype)

        return _Pairs(
            rows=cat([p.rows for p in parts], np.int64),
            areas=cat([p.areas for p in parts], np.int64),
            coverage=cat([p.coverage for p in parts], np.int8),
            precision=cat([p.precision for p in parts], np.int8),
        )

    def where(self, mask: npt.NDArray[np.bool_]) -> "_Pairs":
        """Return the pairs selected by ``mask``."""
        return _Pairs(self.rows[mask], self.areas[mask], self.coverage[mask], self.precision[mask])


class WeatherIndex:
    """A spatial and temporal index over :class:`AlertArea` records.

    ``known_counties`` are the county FIPS codes the NWS county files use; a
    place whose code is one of them is matched to approximate county areas by
    that code (see the module docstring). Leave it out to decide every
    approximate area by its outline.
    """

    def __init__(
        self, areas: Sequence[AlertArea], *, known_counties: Iterable[str] | None = None
    ) -> None:
        kept = [area for area in areas if area.end is None or area.end > area.start]
        self.areas: tuple[AlertArea, ...] = tuple(kept)
        self.known_counties: frozenset[str] = frozenset(known_counties or ())
        alerts: dict[str, AlertInfo] = {}
        for area in kept:
            known = alerts.setdefault(area.alert.key, area.alert)
            if known != area.alert:
                raise ValueError(f"alert {area.alert.key} is described two ways")
        self._alerts = alerts
        alert_number = {key: n for n, key in enumerate(alerts)}
        self._alert = np.array([alert_number[a.alert.key] for a in kept], dtype=np.int64)
        self._start = np.array([_ns(area.start) for area in kept], dtype=np.int64)
        self._end = np.array(
            [_OPEN_END if area.end is None else _ns(area.end) for area in kept], dtype=np.int64
        )
        self._basis = np.array([BASES.index(area.basis) for area in kept], dtype=np.int8)
        self._precision = np.array(
            [PRECISIONS.index(area.precision) for area in kept], dtype=np.int8
        )
        self._build_spatial(kept)
        self._build_codes(kept)

    def _build_spatial(self, kept: Sequence[AlertArea]) -> None:
        drawn = [
            (i, area, geometry)
            for i, area in enumerate(kept)
            if area.point_matching and (geometry := area.geometry) is not None
        ]
        self._spatial_ids = np.array([i for i, _, _ in drawn], dtype=np.int64)
        geometries = np.array([geometry for _, _, geometry in drawn], dtype=object)
        tolerance = np.array([area.tolerance for _, area, _ in drawn], dtype=np.float64)
        hints = np.array([area.hint for _, area, _ in drawn], dtype=object)
        # The outlines of approximate areas, for distance tests.
        edges = np.array(
            [geometry if area.tolerance > 0 else None for _, area, geometry in drawn], dtype=object
        )
        edges = shapely.boundary(edges) if edges.size else edges
        for array in (geometries, edges, hints):
            shapely.prepare(array)
        self._geometries = geometries
        self._edges = edges
        self._hints = hints
        self._has_hint = np.array([area.hint is not None for _, area, _ in drawn], dtype=bool)
        self._tolerance = tolerance
        # Approximate county areas: their county code decides for places with a known code.
        self._by_code = np.array(
            [area.tolerance > 0 and bool(area.counties) for _, area, _ in drawn], dtype=bool
        )
        # Distinct outlines (the archive rows of one zone share one outline object).
        number_of: dict[int, int] = {}
        self._shape_geometry: list[Polygonal] = []
        self._shape_tolerance: list[float] = []
        shapes: list[int] = []
        for _, area, geometry in drawn:
            number = number_of.setdefault(id(geometry), len(self._shape_geometry))
            if number == len(self._shape_geometry):
                self._shape_geometry.append(geometry)
                self._shape_tolerance.append(area.tolerance)
            self._shape_tolerance[number] = max(self._shape_tolerance[number], area.tolerance)
            shapes.append(number)
        self._shape = np.array(shapes, dtype=np.int64)
        self._tree = STRtree(
            _envelopes(geometries, tolerance, hints) if drawn else np.array([], dtype=object)
        )

    def _build_codes(self, kept: Sequence[AlertArea]) -> None:
        # With a point: county areas without a boundary, and approximate county
        # areas when the place's code is known, match on the code.
        self._code_fallback: dict[str, list[int]] = defaultdict(list)
        self._code_decides: dict[str, list[int]] = defaultdict(list)
        # Without a point: (area, coverage) for every area naming the county.
        self._code_any: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for i, area in enumerate(kept):
            for fips in area.counties:
                self._code_any[fips].append((i, _COVERED if area.point_matching else _UNCERTAIN))
                if not area.point_matching:
                    continue
                if area.geometry is None:
                    self._code_fallback[fips].append(i)
                elif area.tolerance > 0:
                    self._code_decides[fips].append(i)

    def __len__(self) -> int:
        return len(self.areas)

    def check(
        self,
        *,
        county_fips: str | None,
        lat: float | None,
        lon: float | None,
        start: datetime,
        end: datetime,
    ) -> list[AlertMatch]:
        """Return the alerts that covered (or may have covered) one place in ``[start, end)``."""
        frame = self.check_many(
            [county_fips],
            np.array([np.nan if lon is None else lon], dtype=np.float64),
            np.array([np.nan if lat is None else lat], dtype=np.float64),
            start=start,
            end=end,
        )
        return [
            AlertMatch(
                alert=self._alerts[row["key"]],
                start=row["start"],
                end=row["end"],
                coverage=_COVERAGE_BY_NAME[row["coverage"]],
                basis=_BASIS_BY_NAME[row["basis"]],
                precision=_PRECISION_BY_NAME[row["precision"]],
                traces=tuple(row["traces"]),
            )
            for row in frame.iter_rows(named=True)
        ]

    def check_local(
        self,
        *,
        county_fips: str | None,
        lat: float | None,
        lon: float | None,
        window: LocalWindow,
        zone: str,
    ) -> list[AlertMatch]:
        """Return the alerts that covered (or may have covered) one place in a local window.

        ``zone`` is the place's IANA time zone (see
        :class:`~snowlight.weather.timezones.TimeZoneLookup` when it is not known).
        """
        start, end = window.utc(zone)
        return self.check(county_fips=county_fips, lat=lat, lon=lon, start=start, end=end)

    def check_many(
        self,
        county_fips: Sequence[str | None],
        lon: npt.NDArray[np.float64],
        lat: npt.NDArray[np.float64],
        *,
        start: Moment,
        end: Moment,
    ) -> pl.DataFrame:
        """Check many places at once.

        Args:
            county_fips: each place's five-digit county FIPS code, or ``None``.
            lon: each place's longitude (``NaN`` when unknown).
            lat: each place's latitude (``NaN`` when unknown).
            start: the window start, one aware time for all places or one per place.
            end: the window end (exclusive), likewise.

        Returns:
            One row per place and matching alert (see :data:`MATCH_SCHEMA`); ``row``
            is the place's position in the inputs. Places with no match have no row.
        """
        count = len(county_fips)
        lon = np.asarray(lon, dtype=np.float64)
        lat = np.asarray(lat, dtype=np.float64)
        if lon.shape != (count,) or lat.shape != (count,):
            raise ValueError("county_fips, lon and lat must have the same length")
        q_start = _ns_array(start, count, "start")
        q_end = _ns_array(end, count, "end")
        if np.any(q_end <= q_start):
            raise ValueError("every window must end after it starts")
        places = _Places(
            lon=lon,
            lat=lat,
            has_point=np.isfinite(lon) & np.isfinite(lat),
            known=np.array(
                [f is not None and f in self.known_counties for f in county_fips], dtype=bool
            ),
            start=q_start,
            end=q_end,
        )
        coded = self._code_pairs(county_fips, places)
        return self._merge(
            _Pairs.join([self._spatial_pairs(places), coded.where(self._live(coded, places))])
        )

    def _live(self, pairs: _Pairs, places: _Places) -> npt.NDArray[np.bool_]:
        """Which pairs have an area in effect during their place's window."""
        live: npt.NDArray[np.bool_] = (self._start[pairs.areas] < places.end[pairs.rows]) & (
            self._end[pairs.areas] > places.start[pairs.rows]
        )
        return live

    def _spatial_pairs(self, places: _Places) -> _Pairs:
        located = np.flatnonzero(places.has_point)
        if not located.size or not self._spatial_ids.size:
            return _Pairs.join([])
        lon, lat = places.lon, places.lat
        query_idx, tree_idx = self._tree.query(shapely.points(lon[located], lat[located]))
        rows = located[query_idx].astype(np.int64)
        slot = tree_idx.astype(np.int64)
        areas = self._spatial_ids[slot]
        # Areas live in the place's window, and not decided by the place's county code.
        keep = (self._start[areas] < places.end[rows]) & (self._end[areas] > places.start[rows])
        keep &= ~(self._by_code[slot] & places.known[rows])
        rows, slot, areas = rows[keep], slot[keep], areas[keep]
        x, y = lon[rows], lat[rows]
        inside = shapely.intersects_xy(self._geometries[slot], x, y)
        coverage = np.full(rows.size, _NO_MATCH, dtype=np.int8)
        approximate = self._tolerance[slot] > 0
        coverage[inside & ~approximate] = _COVERED
        near_hint = np.zeros(rows.size, dtype=bool)
        todo = np.flatnonzero(approximate)
        if todo.size:
            s = slot[todo]
            points = shapely.points(x[todo], y[todo])
            near_edge = shapely.dwithin(self._edges[s], points, self._tolerance[s])
            in_hint = shapely.intersects_xy(self._hints[s], x[todo], y[todo])
            core = inside[todo] & ~near_edge & (in_hint | ~self._has_hint[s])
            maybe = inside[todo] | near_edge | in_hint
            coverage[todo] = np.where(core, _COVERED, np.where(maybe, _UNCERTAIN, _NO_MATCH))
            near_hint[todo] = in_hint
        hit = coverage != _NO_MATCH
        pairs = _Pairs(rows[hit], areas[hit], coverage[hit], self._precision[areas[hit]])
        self._settle_shared_edges(pairs, slot[hit], near_hint[hit], lon, lat)
        return pairs

    def _settle_shared_edges(
        self,
        pairs: _Pairs,
        slot: npt.NDArray[np.int64],
        in_hint: npt.NDArray[np.bool_],
        lon: npt.NDArray[np.float64],
        lat: npt.NDArray[np.float64],
    ) -> None:
        """Mark covered, in place, the uncertain places deep inside the union of an alert's areas.

        Only the areas whose outline is near the place matter (the others are
        farther than their tolerance from it), so the union is taken over the
        uncertain pairs of one place, alert and basis, clipped to the places
        that share the same set of outlines.
        """
        uncertain = np.flatnonzero(pairs.coverage == _UNCERTAIN)
        if uncertain.size < _SHARED_EDGE_AREAS:
            return
        is_covered = pairs.coverage == _COVERED
        frame = pl.DataFrame(
            {
                "pair": uncertain,
                "row": pairs.rows[uncertain],
                "alert": self._alert[pairs.areas[uncertain]],
                "basis": self._basis[pairs.areas[uncertain]],
                "shape": self._shape[slot[uncertain]],
                "has_hint": self._has_hint[slot[uncertain]],
                "in_hint": in_hint[uncertain],
            }
        )
        covered = pl.DataFrame(
            {"row": pairs.rows[is_covered], "alert": self._alert[pairs.areas[is_covered]]},
            schema={"row": pl.Int64(), "alert": pl.Int64()},
        ).unique()
        groups = (
            frame.join(covered, on=["row", "alert"], how="anti")
            .group_by("row", "alert", "basis")
            .agg(
                pl.col("pair"),
                pl.col("shape").unique().sort(),
                pl.col("has_hint").all().alias("all_hints"),
                pl.col("has_hint").any().alias("any_hints"),
                pl.col("in_hint").any(),
            )
            .filter(
                (pl.col("shape").list.len() >= _SHARED_EDGE_AREAS)
                & ((pl.col("all_hints") & pl.col("in_hint")) | ~pl.col("any_hints"))
            )
            .with_columns(pl.col("shape").cast(pl.List(pl.String())).list.join(",").alias("set"))
        )
        for (shape_set,), group in groups.group_by("set"):
            shapes = [int(s) for s in str(shape_set).split(",")]
            rows = group["row"].to_numpy()
            x, y = lon[rows], lat[rows]
            tolerance = max(self._shape_tolerance[s] for s in shapes)
            margin = 2 * tolerance
            clip = (x.min() - margin, y.min() - margin, x.max() + margin, y.max() + margin)
            union = shapely.union_all(
                [shapely.clip_by_rect(self._shape_geometry[s], *clip) for s in shapes]
            )
            edge = shapely.boundary(union)
            shapely.prepare(union)
            shapely.prepare(edge)
            deep = shapely.intersects_xy(union, x, y) & ~shapely.dwithin(
                edge, shapely.points(x, y), tolerance
            )
            for pair_list in group.filter(pl.Series(deep))["pair"].to_list():
                pairs.coverage[np.asarray(pair_list, dtype=np.int64)] = _COVERED

    def _code_pairs(self, county_fips: Sequence[str | None], places: _Places) -> _Pairs:
        rows: list[int] = []
        areas: list[int] = []
        coverage: list[int] = []
        decided: list[bool] = []
        for row, fips in enumerate(county_fips):
            if fips is None:
                continue
            if places.has_point[row]:
                for area in self._code_fallback.get(fips, ()):
                    rows.append(row)
                    areas.append(area)
                    coverage.append(_COVERED)
                    decided.append(False)
                if places.known[row]:
                    for area in self._code_decides.get(fips, ()):
                        rows.append(row)
                        areas.append(area)
                        coverage.append(_COVERED)
                        decided.append(True)
            else:
                for area, answer in self._code_any.get(fips, ()):
                    rows.append(row)
                    areas.append(area)
                    coverage.append(answer)
                    decided.append(answer == _COVERED)
        area_ids = np.array(areas, dtype=np.int64)
        precision = self._precision[area_ids].copy()
        # A county code decides without any boundary, so nothing about it is approximate.
        precision[np.array(decided, dtype=bool)] = _EXACT
        return _Pairs(
            np.array(rows, dtype=np.int64),
            area_ids,
            np.array(coverage, dtype=np.int8),
            precision.astype(np.int8),
        )

    def _merge(self, pairs: _Pairs) -> pl.DataFrame:
        if pairs.rows.size == 0:
            return pl.DataFrame(schema=MATCH_SCHEMA)
        area_ids = pairs.areas.tolist()
        frame = pl.DataFrame(
            {
                "row": pairs.rows,
                "key": [self.areas[i].alert.key for i in area_ids],
                "coverage_rank": pairs.coverage,
                "start_ns": self._start[pairs.areas],
                "end_ns": self._end[pairs.areas],
                "basis_rank": self._basis[pairs.areas],
                "precision_rank": pairs.precision,
                "trace": [self.areas[i].trace for i in area_ids],
            }
        )
        # Keep, per place and alert, only the areas that gave the best answer.
        best = frame.filter(
            pl.col("coverage_rank") == pl.col("coverage_rank").min().over("row", "key")
        )
        merged = best.group_by("row", "key").agg(
            pl.col("coverage_rank").first(),
            pl.col("start_ns").min(),
            pl.col("end_ns").max(),
            pl.col("basis_rank").min(),
            pl.col("precision_rank").min(),
            pl.col("trace").unique().sort().alias("traces"),
        )
        info = pl.DataFrame(
            {
                "key": list(self._alerts),
                "event": [alert.event for alert in self._alerts.values()],
                "hazard": [alert.hazard for alert in self._alerts.values()],
                "level": [alert.level for alert in self._alerts.values()],
                "severity": [alert.severity for alert in self._alerts.values()],
            },
            schema={name: pl.String() for name in ("key", "event", "hazard", "level", "severity")},
        )
        to_time = pl.from_epoch(pl.col("start_ns") // 1000, time_unit="us").dt.replace_time_zone(
            "UTC"
        )
        end_time = (
            pl.when(pl.col("end_ns") == _OPEN_END)
            .then(None)
            .otherwise(pl.from_epoch(pl.col("end_ns") // 1000, time_unit="us"))
            .dt.replace_time_zone("UTC")
        )

        def names(column: str, values: tuple[str, ...]) -> pl.Expr:
            return pl.col(column).replace_strict(
                list(range(len(values))), list(values), return_dtype=pl.String()
            )

        return (
            merged.join(info, on="key", how="left")
            .with_columns(
                to_time.alias("start"),
                end_time.alias("end"),
                names("coverage_rank", COVERAGES).alias("coverage"),
                names("basis_rank", BASES).alias("basis"),
                names("precision_rank", PRECISIONS).alias("precision"),
            )
            .select(list(MATCH_SCHEMA))
            .cast(pl.Schema(MATCH_SCHEMA))
            .sort("row", "start", "event", "key")
        )
