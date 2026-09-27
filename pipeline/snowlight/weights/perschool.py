"""The per-school weights: counting, and the school, county and state records built from them.

:func:`count_per_school` runs :mod:`snowlight.weights.zonepolys`,
:mod:`snowlight.weights.schoolzones`, :mod:`snowlight.weights.polygons` and
:mod:`snowlight.weights.schoolcount` on the rows the county rule read
(:func:`snowlight.weights.build.count_weather`). The records:

* :func:`school_records`: one per school, keyed by its NCES id;
* :func:`county_summaries`: per county with schools, the school-weighted mean of its
  schools' figures (the county's value is the mean over its schools), with the
  county rule's own figures kept beside them (``county_rule``) and the whole-county
  diagnostic;
* :func:`state_rows`: per state, the school-weighted means, with the county rule's
  weight and rank for comparison.

``weight`` is always ``days_per_year`` divided by the mean of ``days_per_year`` over
every placed school, so the school-weighted national mean weight is 1.
"""

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import polars as pl
import shapely

from snowlight.output import JSONValue
from snowlight.sources.nws.boundaries import BoundaryRelease
from snowlight.weights import archive, polygons, schoolcount, schoolzones, zonepolys
from snowlight.weights.cache import WeightsCache
from snowlight.weights.codes import CODES, SUBSETS
from snowlight.weights.count import CountyDays, Tally
from snowlight.weights.schools import Placement
from snowlight.weights.zones import CountyList


class PerSchoolError(ValueError):
    """The per-school weights cannot be computed."""


@dataclass(slots=True)
class PerSchool:
    """Everything the per-school counting computed."""

    sets: list[zonepolys.ZoneSet]
    book: zonepolys.VersionBook
    zoned: schoolzones.ZonePlacement
    by_year: schoolzones.YearPlacement
    cells: schoolcount.Cells
    tally: schoolcount.SchoolTally
    days: list[schoolcount.SchoolDays]
    polygon_files: list[polygons.PolygonFile]
    mean: float
    """Mean ``days_per_year`` over every placed school (the normalizer)."""
    weights: list[float] = field(default_factory=list)
    """Each school's weight, in the order of the placement."""
    rows_by_source: dict[str, Counter[str]] = field(default_factory=dict)
    """School year to zone rows by where their polygon came from."""
    alternating: list[zonepolys.Alternation] = field(default_factory=list)
    """Zones whose rows return to an outline after rows of another."""


def _round(value: float, places: int = 4) -> float:
    return round(value + 0.0, places)


def count_per_school(  # noqa: PLR0913
    cache: WeightsCache,
    files: Sequence[archive.SchoolYearFile],
    counties: CountyList,
    *,
    frame: pl.DataFrame,
    placement: Placement,
    county_tally: Tally,
    county_left_out: Mapping[str, Sequence[int]],
    zone_releases: Sequence[BoundaryRelease] = zonepolys.ZONE_RELEASES,
) -> PerSchool:
    """Count every school's days (see :mod:`snowlight.weights.schoolcount`).

    Raises:
        PerSchoolError: a zone version has no polygon, a polygon file is still
            provisional, a polygon-code row is outside the polygon codes, or no school
            has a closure-type day.
    """
    sets = zonepolys.load_zone_sets(cache, zone_releases)
    rows = [row for file in files for row in file.rows]
    book = zonepolys.build_book(cache, rows, sets)
    if book.unresolved:
        labels = [version.label for version in book.unresolved]
        raise PerSchoolError(f"zone versions with no polygon: {labels[:20]}")
    polygon_files = polygons.load_polygon_years(cache, [file.year for file in files])
    provisional = [file.label for file in polygon_files if not file.final]
    if provisional:
        raise PerSchoolError(f"storm-polygon files still provisional: {provisional}")
    stray = sorted(
        {
            key.split(".", 1)[1].rsplit(".", 2)[0]
            for file in files
            for key in file.stats.polygon_events
        }
        - polygons.POLYGON_CODES
    )
    if stray:
        raise PerSchoolError(f"polygon rows of codes not read as polygons: {stray}")
    zoned = schoolzones.place_in_zones(frame, placement, book.reference, counties)
    members = schoolzones.memberships(book.polygons, frame, placement, zoned)
    versions = schoolzones.year_versions(
        files, book, {item.year: item.events for item in polygon_files}
    )
    by_year = schoolzones.place_by_year(
        book.polygons,
        versions,
        zoned,
        members,
        coordinates=schoolzones.school_coordinates(frame, placement),
    )
    cells = schoolcount.build_cells(zoned, members, by_year)
    tally = schoolcount.count_schools(
        files,
        {file.year: file for file in polygon_files},
        book,
        cells,
        state_fips=counties.state_fips,
        school_points=schoolcount.school_frame_points(frame, placement),
        zoned=zoned,
        county_tally=county_tally,
        county_left_out=county_left_out,
    )
    days = schoolcount.summarize_schools(tally, SUBSETS)
    if not days:
        raise PerSchoolError("no school was placed")
    mean = sum(item.days_per_year for item in days) / len(days)
    if mean <= 0:
        raise PerSchoolError("no school had a closure-type day")
    result = PerSchool(sets, book, zoned, by_year, cells, tally, days, polygon_files, mean)
    result.weights = [item.days_per_year / mean for item in days]
    result.alternating = zonepolys.alternating_outlines(rows, book)
    for file in files:
        found: Counter[str] = Counter()
        for row in file.rows:
            if row.ugc[2] == "Z" and row.area_km2 is not None:
                found[book.resolved[zonepolys.Version(row.ugc, row.area_km2)].source] += 1
        result.rows_by_source[file.label] = found
    return result


RECOUNT_TOLERANCE = 1e-9


def recount_check(  # noqa: PLR0913
    per: PerSchool,
    files: Sequence[archive.SchoolYearFile],
    frame: pl.DataFrame,
    placement: Placement,
    counties: CountyList,
    *,
    county_tally: Tally,
    county_left_out: Mapping[str, Sequence[int]],
) -> dict[str, JSONValue]:
    """Recount some schools directly (:func:`snowlight.weights.schoolcount.recount`).

    The schools: the first school of each state by NCES id, every school placed
    ``nearest`` and every school with a school year logged by
    :func:`snowlight.weights.schoolzones.place_by_year`. (A school placed ``county``
    takes the county rule, checked elsewhere.) The recount re-applies the school-year
    rule from the rows of each school's own zone; the zone versions it adds, school
    year by school year, must be the ones the placement logged.

    Raises:
        PerSchoolError: a recount differs from the school's counted days, or adds
            other versions than the placement.
    """
    lon, lat = schoolzones.school_coordinates(frame, placement)
    first: dict[str, int] = {}
    for position, school in enumerate(placement.schools):
        known = first.get(school.state)
        if known is None or school.school_id < placement.schools[known].school_id:
            first[school.state] = position
    logged: dict[int, dict[int, frozenset[str]]] = defaultdict(dict)
    for item in per.by_year.outside:
        taken = frozenset(m.key for m in item.missed if m.taken)
        if taken:
            logged[item.position][item.year] = taken
    chosen = sorted(
        set(first.values())
        | {p for p, zone in enumerate(per.zoned.schools) if zone.method == "nearest"}
        | {item.position for item in per.by_year.outside}
    )
    index = schoolcount.recount_index(
        files, {item.year: item for item in per.polygon_files}, per.book, counties.state_fips
    )
    checked: list[JSONValue] = []
    for position in chosen:
        zone = per.zoned.schools[position]
        if zone.method == "county":
            continue
        target = schoolcount.RecountSchool(
            point=shapely.Point(float(lon[position]), float(lat[position])),
            fips=zone.fips,
            time_zones=zone.time_zones,
            own_zone=zone.zone,
        )
        again = schoolcount.recount(
            target,
            index,
            per.book,
            county_tally=county_tally,
            county_left_out=county_left_out.get(zone.fips, ()),
            nearest_km=per.by_year.nearest_km,
        )
        counted = per.days[position].days_per_year
        if abs(again.days_per_year - counted) > RECOUNT_TOLERANCE:
            raise PerSchoolError(
                f"school {zone.school_id}: counted {counted!r} weighted days a year, "
                f"recounted {again.days_per_year!r}"
            )
        if dict(again.by_year_rows) != logged.get(position, {}) or again.county_years != (
            per.by_year.county_years.get(position, frozenset())
        ):
            raise PerSchoolError(
                f"school {zone.school_id}: the recount's school-year versions differ from "
                "the placement's"
            )
        checked.append({"school": zone.school_id, "days_per_year": _round(again.days_per_year, 6)})
    return {
        "schools": len(checked),
        "agree": len(checked),
        "school_year_rule_schools": len({item.position for item in per.by_year.outside}),
        "recounted": checked,
    }


def school_records(per: PerSchool, placement: Placement) -> dict[str, JSONValue]:
    """Return every school's record, keyed by its NCES id."""
    outside: dict[int, dict[str, JSONValue]] = defaultdict(dict)
    for item in per.by_year.outside:
        outside[item.position][archive.school_year_label(item.year)] = item.method
    records: dict[str, JSONValue] = {}
    for position, school in enumerate(placement.schools):
        zone = per.zoned.schools[position]
        days = per.days[position]
        record: dict[str, JSONValue] = {
            "fips": school.nws_fips,
            "state": school.state,
            "zone": zone.zone if zone.method != "county" else None,
            "placed": zone.method,
            "time_zones": list(zone.time_zones),
            "weight": _round(per.weights[position]),
            "days_per_year": _round(days.days_per_year),
            "any_days_per_year": _round(days.any_days_per_year),
            "years_counted": len(days.years_counted),
            "codes": {
                code: _round(days.code_days_per_year(code))
                for code in sorted(days.code_days)
                if days.code_days[code]
            },
        }
        if zone.method != "inside":
            record["distance_km"] = None if zone.zone is None else _round(zone.distance_km, 3)
        if position in outside:
            record["school_years_outside_zone"] = outside[position]
        records[school.school_id] = record
    return records


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def county_summaries(  # noqa: PLR0913
    per: PerSchool,
    placement: Placement,
    counties: CountyList,
    *,
    county_rule: Mapping[str, CountyDays],
    county_rule_records: Mapping[str, dict[str, JSONValue]],
    whole_mean: float,
    county_rule_mean: float,
) -> tuple[dict[str, dict[str, JSONValue]], list[str]]:
    """Return the county summaries (counties with schools) and the counties without schools.

    ``county_rule_records`` are the county rule's records (``county_records`` of the
    build), whose zone and left-out details are kept under ``county_rule``.
    """
    members: dict[str, list[int]] = defaultdict(list)
    for position, school in enumerate(placement.schools):
        members[school.nws_fips].append(position)
    years = per.tally.index.years
    summaries: dict[str, dict[str, JSONValue]] = {}
    empty: list[str] = []
    for fips, county in sorted(counties.counties.items()):
        positions = members.get(fips, [])
        rule = county_rule[fips]
        if not positions:
            empty.append(fips)
            continue
        days = [per.days[p] for p in positions]
        weights = [per.weights[p] for p in positions]
        by_year: dict[str, JSONValue] = {}
        for year in years:
            counted = [d.by_year[year] for d in days if d.by_year[year] is not None]
            values = [item for item in counted if item is not None]
            by_year[archive.school_year_label(year)] = (
                {
                    "weighted": _round(_mean([v[0] for v in values]), 2),
                    "days": _round(_mean([float(v[1]) for v in values]), 2),
                    "schools": len(values),
                }
                if values
                else None
            )
        zones = Counter(
            per.zoned.schools[p].zone for p in positions if per.zoned.schools[p].method != "county"
        )
        placed = Counter(per.zoned.schools[p].method for p in positions)
        old = county_rule_records[fips]
        summaries[fips] = {
            "fips": fips,
            "state": county.state,
            "name": county.name,
            "time_zones": list(county.time_zones),
            "schools": len(positions),
            "weight": _round(_mean(weights)),
            "days_per_year": _round(_mean([d.days_per_year for d in days])),
            "any_days_per_year": _round(_mean([d.any_days_per_year for d in days])),
            "weighted_days_total": _round(
                _mean([sum(v[0] for v in d.by_year.values() if v is not None) for d in days]), 2
            ),
            "years_counted": min(len(d.years_counted) for d in days),
            "schools_with_school_years_left_out": sum(
                len(d.years_counted) < len(years) for d in days
            ),
            "codes": {
                code.code: {
                    "days": _round(_mean([float(d.code_days.get(code.code, 0)) for d in days]), 2),
                    "per_year": _round(_mean([d.code_days_per_year(code.code) for d in days])),
                }
                for code in CODES
            },
            "subsets_days_per_year": {
                name: _round(_mean([d.subset_days_per_year[name] for d in days]))
                for name in sorted(SUBSETS)
            },
            "by_year": by_year,
            "zones": {
                str(k): v for k, v in sorted(zones.items(), key=lambda kv: (-kv[1], str(kv[0])))
            },
            "schools_placed": dict(sorted(placed.items())),
            "whole_county_days_per_year": _round(rule.whole_county_days_per_year),
            "whole_county_weight": _round(rule.whole_county_days_per_year / whole_mean),
            "county_rule": {
                "weight": _round(rule.days_per_year / county_rule_mean),
                "days_per_year": _round(rule.days_per_year),
                "any_days_per_year": _round(rule.any_days_per_year),
                "years_counted": len(rule.years_counted),
                "school_years_left_out": old["school_years_left_out"],
                "by_year": old["by_year"],
                "codes": old["codes"],
                "top_zones": old["top_zones"],
                "left_out_zone_days": old["left_out_zone_days"],
            },
        }
    return summaries, empty


def state_rows(
    per: PerSchool,
    placement: Placement,
    county_rule: Mapping[str, CountyDays],
    whole_mean: float,
    county_rule_mean: float,
) -> list[dict[str, JSONValue]]:
    """Return every state's record for ``state-weights.json``, heaviest first."""
    by_state: dict[str, list[int]] = defaultdict(list)
    for position, school in enumerate(placement.schools):
        by_state[school.state].append(position)
    national = sum(item.days_per_year for item in per.days)
    rows: list[dict[str, JSONValue]] = []
    for state, positions in by_state.items():
        days = [per.days[p] for p in positions]
        value = _mean([d.days_per_year for d in days])
        rule_days = _mean(
            [county_rule[placement.schools[p].nws_fips].days_per_year for p in positions]
        )
        whole = _mean(
            [
                county_rule[placement.schools[p].nws_fips].whole_county_days_per_year
                for p in positions
            ]
        )
        placed = Counter(per.zoned.schools[p].method for p in positions)
        rows.append(
            {
                "state": state,
                "schools": len(positions),
                "schools_with_school_years_left_out": sum(
                    len(d.years_counted) < len(per.tally.index.years) for d in days
                ),
                "schools_placed": dict(sorted(placed.items())),
                "weight": _round(value / per.mean),
                "days_per_year": _round(value),
                "share_of_weighted_closure_days": _round(len(positions) * value / national, 5),
                "any_days_per_year": _round(_mean([d.any_days_per_year for d in days])),
                "subsets_days_per_year": {
                    name: _round(_mean([d.subset_days_per_year[name] for d in days]))
                    for name in sorted(SUBSETS)
                },
                "code_days_per_year": {
                    code.code: _round(_mean([d.code_days_per_year(code.code) for d in days]))
                    for code in sorted(CODES, key=lambda c: c.code)
                },
                "county_rule_weight": _round(rule_days / county_rule_mean),
                "county_rule_days_per_year": _round(rule_days),
                "whole_county_days_per_year": _round(whole),
                "whole_county_weight": _round(whole / whole_mean),
                "partial_day_share": _round(1 - whole / rule_days, 4) if rule_days > 0 else None,
            }
        )
    rows.sort(key=lambda row: (-float(str(row["weight"])), str(row["state"])))
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    rule_order = sorted(
        rows, key=lambda row: (-float(str(row["county_rule_weight"])), str(row["state"]))
    )
    for rank, row in enumerate(rule_order, start=1):
        row["county_rule_rank"] = rank
    return rows


def by_year_json(by_year: schoolzones.YearPlacement) -> dict[str, JSONValue]:
    """Return the school-year log kept in the manifest (every school year logged)."""
    return {
        "nearest_km": by_year.nearest_km,
        "school_years_by_method": dict(sorted(by_year.by_method().items())),
        "schools": len({item.school_id for item in by_year.outside}),
        "schools_with_county_years": len(by_year.county_years),
        "school_years_in_another_zone": sum(by_year.in_other_zone.values()),
        "schools_with_school_years_in_another_zone": by_year.schools_in_other_zone,
        "school_years_in_another_zone_by_own_zone": dict(by_year.in_other_zone.most_common()),
        "logged": [
            {
                "school": item.school_id,
                "fips": item.fips,
                "school_year": archive.school_year_label(item.year),
                "zone": item.zone,
                "placed": item.method,
                "inside_another_version_of_its_zone": item.inside_own_zone,
                "versions": [
                    {
                        "version": missed.key,
                        "distance_km": _round(missed.distance_km, 3),
                        "rows": missed.rows,
                        "taken": missed.taken,
                    }
                    for missed in item.missed
                ],
            }
            for item in by_year.outside
        ],
    }


def placement_json(per: PerSchool) -> dict[str, JSONValue]:
    """Return the placement log kept in the manifest (every school not placed ``inside``,
    and every school year :func:`snowlight.weights.schoolzones.place_by_year` logged)."""
    zoned = per.zoned
    return {
        "reference_release": zoned.reference,
        "nearest_km": schoolzones.NEAREST_KM,
        "placed_by": dict(sorted(zoned.by_method.items())),
        "on_shared_boundary": zoned.on_shared_boundary,
        "time_zone_from_zone": zoned.time_zone_from_zone,
        "time_zone_split_kept": zoned.time_zone_split_kept,
        "nearest": [
            {
                "school": s.school_id,
                "fips": s.fips,
                "zone": s.zone,
                "distance_km": _round(s.distance_km, 3),
            }
            for s in zoned.nearest
        ],
        "county": [
            {
                "school": s.school_id,
                "fips": s.fips,
                "nearest_zone": s.zone,
                "distance_km": None if s.zone is None else _round(s.distance_km, 3),
            }
            for s in zoned.county
        ],
        "by_school_year": by_year_json(per.by_year),
    }


def counting_json(per: PerSchool) -> dict[str, JSONValue]:
    """Return what the per-school counting did (kept in the manifest)."""
    stats = per.tally.stats
    return {
        "cells": len(per.cells.keys),
        "zone_rows": stats.zone_rows,
        "zone_rows_reaching_schools": stats.zone_rows_reaching_schools,
        "county_rows": stats.county_rows,
        "county_rows_reaching_schools": stats.county_rows_reaching_schools,
        "counties_named_by_county_rows_without_schools": dict(
            stats.county_rows_without_schools.most_common()
        ),
        "polygon_code_county_rows_replaced_by_polygons": stats.polygon_county_rows_replaced,
        "polygon_code_events_without_polygons": dict(
            sorted(stats.polygon_events_without_polygons.items())
        ),
        "zone_rows_by_school_year_and_polygon_source": {
            label: dict(sorted(found.items())) for label, found in per.rows_by_source.items()
        },
        "polygon_rows": stats.polygon_rows,
        "polygon_rows_reaching_schools": stats.polygon_rows_reaching_schools,
        "fallback_cells": stats.fallback_cells,
        "zone_rows_reaching_schools_by_the_school_year_rule": stats.zone_rows_reaching_by_year,
        "cells_with_county_school_years": stats.county_year_cells,
    }


def polygon_files_json(
    per: PerSchool, files: Sequence[archive.SchoolYearFile]
) -> dict[str, JSONValue]:
    """Return, per school year, the polygon file and its agreement with the school-year file."""
    by_year = {file.year: file for file in files}
    found: dict[str, JSONValue] = {}
    for item in per.polygon_files:
        csv_events = frozenset(by_year[item.year].stats.polygon_events)
        found[item.label] = {
            "file": item.file.provenance.as_json(),
            "records": item.stats.records,
            "polygon_rows": item.stats.polygon_rows,
            "county_rows": item.stats.county_rows,
            "events": len(item.events),
            "ended_before_start": item.stats.ended_before_start,
            "without_event_times": item.stats.without_event_times,
            "school_year_file_polygon_events": len(csv_events),
            "events_in_both": len(csv_events & item.events),
            "only_in_school_year_file": [str(k) for k in sorted(csv_events - item.events)[:50]],
            "only_in_polygon_file": [str(k) for k in sorted(item.events - csv_events)[:50]],
        }
    return found
