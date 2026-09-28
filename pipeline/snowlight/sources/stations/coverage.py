"""Measured coverage: which schools sit in a county a working source covers.

A school is covered when its county (from the school directory) is in the county
list of at least one *working* source. A source is working when it is active and
its latest live read (``health.json``) was ``ok`` or ``empty``: the list its page
loads today was read and parsed, and the file has been written to since the last
winter began. A ``stale`` read (the list file's ``Last-Modified`` is older than
that: nothing has been written to it for a whole winter, see
:func:`~snowlight.sources.stations.model.stale_before`), an error, a skip or no
read at all does not count. A platform's terms and robots.txt do not enter the
measure: they are notes in the registry and in each read's health, and the
project owner decided to read these lists anyway (terms on 2026-09-25, robots.txt
on 2026-09-26; see :class:`~snowlight.sources.stations.registry.Terms`).

District-level sources: a station that names NCES district IDs (``leaids``: a
school district's own alert page, or a state's list of its school systems) covers
exactly the schools of those districts (the directory's ``district_id``), never its
counties whole (:func:`district_cover`). A school is covered when its county is in
a working source's county list, or its district is in a working district-level
source's ``leaids``. Every other source is measured as before.

Closure weights: when the weights build's ``closure-weights.json`` is given (a
weight per county, normalized so the school-weighted national mean is 1), each
share is also reported weighted, every school counting its county's weight; the
national target applies to both shares.

Writes (internal, never published) ``coverage.json``::

    {"generated_at", "health_generated_at", "directory": {"path", "sha256", "schools"},
     "references": {name: {"url", "sha256", "retrieved_at", ...}},
     "targets": {"national": 0.95, "state": 0.90},
     "dma_summary": {"markets", "with_a_working_source", "with_two_or_more_working",
                     "biggest_by_schools": [{"dma", "schools", "working"}, ...]},
     "weights": null | {"path", "sha256", "generated_at", "counties",
                        "unplaced_schools", "schools_without_weight"},
     "national": Share, "states": {"AL": Share, ...},
     "counties": {"01001": {"state", "name", "schools", "weighted_schools", "working": [...],
                            "not_working": [...], "dmas": [...], "districts": [...],
                            "districts_not_working": [...], "covered"}, ...},
     "dmas": {label: {"counties", "schools", "working": [...], "not_working": [...]}, ...},
     "counties_without_dma": [...],
     "districts": {"sources": [...], "working": [...], "schools_added",
                   "weighted_added"},
     "stations": {id: {"state": "working" | "stale" | "skipped" | "error" | "no_endpoint"
                                | "not_read",
                       "reason", "counties", "schools", "weighted_schools", "leaids",
                       "observed": null | {"archived_rows", "counties_named", "in_county_list",
                                           "outside_county_list": [fips...],
                                           "unmatched_places"}}},
     "observed_check": {"stations", "counties_named_in_list", "counties_named_outside_list"}}

``not_working`` lists the active stations that name a county but whose latest
read was not ok or empty (stale, an error, skipped or not read). ``observed``
compares a station's county list with the counties its archived rows name
(:mod:`snowlight.sources.stations.observed`), as a check on the list's basis.
A county's ``districts`` and ``districts_not_working`` are the district-level
sources with schools in it (working, or active and not working); ``covered`` is
how many of its schools are covered (all when a whole-county source works). A
district-level station's ``schools`` are its districts' schools, ``leaids`` its
districts (absent for other stations); ``districts.schools_added`` counts the
schools covered only by district-level sources.

    Share = {"schools", "covered", "share", "meets_target",
             "weighted": {"schools", "covered", "share", "meets_target"}}

(``weighted`` only when weights are given; ``schools`` and ``covered`` there are sums
of county weights, rounded to one decimal. A school in a county the weights do not
list counts in the plain share only, and ``weights.schools_without_weight`` says how
many there are.)

With evidence of which lists have been seen populated,
:func:`snowlight.sources.stations.proof.add_proven` adds the *proven* share (the
same measure counting only stations whose current list has held a row, live or
archived), each station's ``proof`` and the ``unproven`` list; see that module.

and ``coverage.png``: counties a working source covers (bright), counties only a
source that is not working lists (amber: stale, failed or not read), counties with
schools and no source (grey), counties where only a district-level source covers
some schools (dim gold), and counties with no schools (black); the title gives
the plain and the weighted national share, and a panel under the map the legend and
each state's (with the proven shares, national and per state, when the result has
them); nothing is drawn over the map.
"""

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import numpy.typing as npt
import polars as pl
from shapely.geometry.base import BaseGeometry

from snowlight.output import JSONValue, write_bytes_atomic, write_json
from snowlight.sources.nws.shapefile import read_zip
from snowlight.sources.stations.dma import DmaCounties
from snowlight.sources.stations.http import iso_utc
from snowlight.sources.stations.mapimage import Rgb, draw_text, png_bytes, project, render
from snowlight.sources.stations.model import HealthStatus, SourceHealth
from snowlight.sources.stations.observed import Observed
from snowlight.sources.stations.registry import Registry, StationStatus
from snowlight.weights.schools import Placement

FIPS_LENGTH = 5
NATIONAL_TARGET = 0.95
STATE_TARGET = 0.90
WORKING_COLOR: Rgb = (255, 214, 102)
DOWN_COLOR: Rgb = (120, 72, 24)
GAP_COLOR: Rgb = (70, 70, 78)
PART_COLOR: Rgb = (150, 118, 52)
EMPTY_COLOR: Rgb = (12, 12, 14)
BACKGROUND: Rgb = (0, 0, 0)


class CoverageError(ValueError):
    """The inputs to the coverage measure are missing or inconsistent."""


@dataclass(frozen=True, slots=True)
class StationState:
    """Why a station does or does not count toward coverage."""

    state: str
    reason: str | None


def station_states(
    registry: Registry, health: Mapping[str, SourceHealth]
) -> dict[str, StationState]:
    """Classify every station as working, stale, skipped, error, no_endpoint or not_read."""
    states: dict[str, StationState] = {}
    for station in registry.stations.values():
        if station.status is StationStatus.NO_ENDPOINT:
            states[station.id] = StationState("no_endpoint", "no known closings endpoint")
            continue
        entry = health.get(station.id)
        if entry is None:
            states[station.id] = StationState("not_read", "no live read in health.json")
        elif entry.status in {HealthStatus.OK, HealthStatus.EMPTY}:
            states[station.id] = StationState("working", None)
        elif entry.status is HealthStatus.SKIPPED:
            states[station.id] = StationState("skipped", entry.reason)
        elif entry.status is HealthStatus.STALE:
            states[station.id] = StationState("stale", entry.reason)
        else:
            states[station.id] = StationState("error", entry.reason)
    return states


def load_health(path: Path) -> tuple[str | None, dict[str, SourceHealth]]:
    """Read ``health.json`` written by ``stations fetch`` (empty if absent)."""
    if not path.is_file():
        return None, {}
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = [SourceHealth.model_validate_json(json.dumps(item)) for item in data["sources"]]
    return str(data["generated_at"]), {entry.source_id: entry for entry in entries}


def _share(
    schools: int, covered: int, target: float, weighted: tuple[float, float] | None = None
) -> dict[str, JSONValue]:
    share = covered / schools if schools else 0.0
    out: dict[str, JSONValue] = {
        "schools": schools,
        "covered": covered,
        "share": round(share, 4),
        "meets_target": schools > 0 and share >= target,
    }
    if weighted is not None:
        total, part = weighted
        ratio = part / total if total > 0 else 0.0
        out["weighted"] = {
            "schools": round(total, 1),
            "covered": round(part, 1),
            "share": round(ratio, 4),
            "meets_target": total > 0 and ratio >= target,
        }
    return out


@dataclass(frozen=True, slots=True)
class Weights:
    """Closure weights per county (the weights build's ``closure-weights.json``).

    The weights are per NWS county. The weights build places each school of the
    directory in one (:func:`snowlight.weights.schools.place_schools`: by its
    county code, which is an NWS code everywhere but Connecticut, whose schools
    carry planning-region codes, else by its coordinates); :meth:`placed` takes that
    placement, so each school counts its own NWS county's weight and the sums are
    kept per directory county (the unit coverage is measured in). Without a
    placement, a directory county's schools count the weight of the NWS county with
    the same code.
    """

    by_county: Mapping[str, float]
    provenance: dict[str, JSONValue]
    school_sums: Mapping[tuple[str, str], float] | None = None
    """(Directory county, school state) to the summed weights of its weighted schools."""
    school_counts: Mapping[tuple[str, str], int] | None = None
    """(Directory county, school state) to the number of its schools given a weight."""
    by_school: Mapping[int, float] | None = None
    """Each placed school's own weight, by its directory ``index``."""

    def placed(self, placement: Placement) -> "Weights":
        """Return these weights with every school's own county weight, summed by county."""
        sums: dict[tuple[str, str], float] = defaultdict(float)
        counts: dict[tuple[str, str], int] = defaultdict(int)
        by_school: dict[int, float] = {}
        for school in placement.schools:
            weight = self.by_county.get(school.nws_fips)
            if weight is not None:
                by_school[school.index] = weight
                key = (school.directory_fips, school.address_state)
                sums[key] += weight
                counts[key] += 1
        provenance = {**self.provenance, "unplaced_schools": len(placement.unplaced)}
        return Weights(self.by_county, provenance, dict(sums), dict(counts), by_school)

    def school(self, index: int | None, fips: str) -> float | None:
        """Return one school's weight: its own when placed, else its county's (or None)."""
        if self.by_school is not None:
            return self.by_school.get(index) if index is not None else None
        return self.by_county.get(fips)

    def county(self, fips: str, state: str, schools: int) -> tuple[float, int]:
        """Return the summed weight of a directory county's schools in ``state``.

        Also returns how many of those schools have no weight. (A few schools sit
        in a county of a neighbouring state, so a county is counted per state.)
        """
        if self.school_sums is None or self.school_counts is None:
            weight = self.by_county.get(fips)
            return (0.0, schools) if weight is None else (weight * schools, 0)
        weighted = min(self.school_counts.get((fips, state), 0), schools)
        return self.school_sums.get((fips, state), 0.0), schools - weighted


def load_weights(path: Path) -> Weights:
    """Read ``closure-weights.json``: each county's ``weight`` by its five-digit FIPS.

    Raises:
        CoverageError: the file is not a closure-weights file.
    """
    raw = path.read_bytes()
    try:
        data = json.loads(raw)
    except ValueError as error:
        raise CoverageError(f"{path.name}: not JSON: {error}") from error
    counties = data.get("counties") if isinstance(data, dict) else None
    if not isinstance(counties, list) or not counties:
        raise CoverageError(f"{path.name}: no county list")
    by_county: dict[str, float] = {}
    for item in counties:
        fips = item.get("fips") if isinstance(item, dict) else None
        weight = item.get("weight") if isinstance(item, dict) else None
        if (
            not isinstance(fips, str)
            or len(fips) != FIPS_LENGTH
            or isinstance(weight, bool)
            or not isinstance(weight, int | float)
            or weight < 0
        ):
            raise CoverageError(f"{path.name}: a county has no FIPS code or weight: {item!r}")
        if fips in by_county:
            raise CoverageError(f"{path.name}: county {fips} is listed twice")
        by_county[fips] = float(weight)
    provenance: dict[str, JSONValue] = {
        "path": path.name,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "generated_at": str(data.get("generated_at")),
        "counties": len(by_county),
    }
    return Weights(by_county, provenance)


_NOT_WORKING = frozenset({"stale", "skipped", "error", "not_read"})


def _station_counties(
    registry: Registry, states: Mapping[str, StationState]
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Map each county to the working stations, and the active ones not working, that list it."""
    working: dict[str, list[str]] = defaultdict(list)
    down: dict[str, list[str]] = defaultdict(list)
    for station in sorted(registry.stations.values(), key=lambda s: s.id):
        # A district-level source covers its districts' schools, not its counties whole.
        if station.counties is None or station.leaids:
            continue
        state = states[station.id].state
        target = working if state == "working" else down if state in _NOT_WORKING else None
        if target is None:
            continue
        for fips in station.counties.fips:
            target[fips].append(station.id)
    return working, down


@dataclass(frozen=True, slots=True)
class DistrictCover:
    """What the district-level sources cover (see :func:`district_cover`)."""

    covered: Mapping[tuple[str, str], int]
    """(County, school state) to its schools a working district-level source covers."""
    weighted: Mapping[tuple[str, str], float]
    """The same schools' summed closure weights (empty without weights)."""
    working: Mapping[str, list[str]]
    """County to the working district-level sources with schools in it."""
    down: Mapping[str, list[str]]
    """County to the active district-level sources with schools in it that are not working."""
    station_schools: Mapping[str, int]
    """Each district-level source (working or not) to its districts' schools."""
    station_weighted: Mapping[str, float]


def district_cover(
    registry: Registry,
    schools: pl.DataFrame,
    states: Mapping[str, StationState],
    weights: Weights | None = None,
) -> DistrictCover:
    """Return the schools that district-level sources (``Station.leaids``) cover.

    A school is covered by such a source when its ``district_id`` (the NCES LEAID
    of the directory) is one of the source's ``leaids`` and the source is working;
    private schools, which have no district, never are. Nothing is counted when no
    station names LEAIDs or the directory frame has no ``district_id`` column. Its
    weight is its own (``Weights.school``: by the frame's ``index`` when the
    weights are placed).
    """
    owners: dict[str, list[str]] = defaultdict(list)
    for station in sorted(registry.stations.values(), key=lambda s: s.id):
        for leaid in station.leaids:
            owners[leaid].append(station.id)
    covered: dict[tuple[str, str], int] = defaultdict(int)
    weighted: dict[tuple[str, str], float] = defaultdict(float)
    working: dict[str, set[str]] = defaultdict(set)
    down: dict[str, set[str]] = defaultdict(set)
    station_schools: dict[str, int] = defaultdict(int)
    station_weighted: dict[str, float] = defaultdict(float)
    if owners and "district_id" in schools.columns:
        columns = ["district_id", "county_fips", "state"]
        columns += ["index"] if "index" in schools.columns else []
        rows = schools.select(columns).filter(pl.col("district_id").is_in(list(owners)))
        for row in rows.iter_rows(named=True):
            fips, state = str(row["county_fips"]), str(row["state"])
            index = row.get("index")
            place = int(index) if index is not None else None
            weight = weights.school(place, fips) if weights is not None else None
            ids = owners[str(row["district_id"])]
            up = [i for i in ids if states[i].state == "working"]
            for station_id in ids:
                if station_id in up or states[station_id].state in _NOT_WORKING:
                    station_schools[station_id] += 1
                    station_weighted[station_id] += weight or 0.0
                    (working if station_id in up else down)[fips].add(station_id)
            if up:
                covered[(fips, state)] += 1
                weighted[(fips, state)] += weight or 0.0
    return DistrictCover(
        covered=dict(covered),
        weighted=dict(weighted),
        working={fips: sorted(ids) for fips, ids in working.items()},
        down={fips: sorted(ids) for fips, ids in down.items()},
        station_schools=dict(station_schools),
        station_weighted=dict(station_weighted),
    )


def _dma_table(
    registry: Registry,
    states: Mapping[str, StationState],
    dmas: DmaCounties,
    county_schools: Mapping[str, int],
) -> dict[str, JSONValue]:
    stations_by_dma: dict[str, list[str]] = defaultdict(list)
    for station in registry.stations.values():
        # A district-level source speaks for its districts, not for its market.
        if station.dma and not station.leaids:
            stations_by_dma[station.dma].append(station.id)
    table: dict[str, JSONValue] = {}
    for label, fips_list in dmas.by_dma.items():
        ids = sorted(stations_by_dma.get(label, []))
        table[label] = {
            "counties": len(fips_list),
            "schools": sum(county_schools.get(fips, 0) for fips in fips_list),
            "working": [i for i in ids if states[i].state == "working"],
            "not_working": [i for i in ids if states[i].state in _NOT_WORKING],
        }
    return table


BIG_MARKETS = 25


def _dma_summary(table: Mapping[str, JSONValue]) -> dict[str, JSONValue]:
    """Count markets by how many working sources list them."""
    rows = [(label, info) for label, info in table.items() if isinstance(info, dict)]

    def count(info: Mapping[str, JSONValue]) -> int:
        value = info.get("working")
        return len(value) if isinstance(value, list) else 0

    by_schools = sorted(rows, key=lambda item: -int(str(item[1].get("schools", 0))))
    return {
        "markets": len(rows),
        "with_a_working_source": sum(count(info) >= 1 for _, info in rows),
        "with_two_or_more_working": sum(count(info) >= 2 for _, info in rows),  # noqa: PLR2004
        "biggest_by_schools": [
            {"dma": label, "schools": info.get("schools", 0), "working": count(info)}
            for label, info in by_schools[:BIG_MARKETS]
        ],
    }


def observed_check(
    registry: Registry, observed: Mapping[str, Observed]
) -> tuple[dict[str, JSONValue], dict[str, JSONValue]]:
    """Compare each station's county list with the counties its archived rows name.

    Returns the per-station entries and a summary.
    """
    per_station: dict[str, JSONValue] = {}
    inside_total = outside_total = 0
    for station_id, seen in sorted(observed.items()):
        station = registry.stations.get(station_id)
        if station is None:
            continue
        listed = set(station.counties.fips) if station.counties else set()
        outside = sorted(seen.counties - listed)
        inside_total += len(seen.counties & listed)
        outside_total += len(outside)
        per_station[station_id] = {
            "archived_rows": seen.rows,
            "counties_named": len(seen.counties),
            "in_county_list": len(seen.counties & listed),
            "outside_county_list": list(outside),
            "unmatched_places": len(seen.unmatched),
        }
    summary: dict[str, JSONValue] = {
        "stations": len(per_station),
        "counties_named_in_list": inside_total,
        "counties_named_outside_list": outside_total,
    }
    return per_station, summary


def measure(  # noqa: PLR0913 - one pass over the counties fills every table
    registry: Registry,
    schools: pl.DataFrame,
    states: Mapping[str, StationState],
    dmas: DmaCounties | None,
    observed: Mapping[str, Observed] | None = None,
    *,
    weights: Weights | None = None,
) -> dict[str, JSONValue]:
    """Compute national, state, county, DMA and station coverage (JSON-ready).

    With ``weights``, every share is also given closure-weighted.
    """
    needed = {"state", "county_fips", "county_name"}
    if not needed <= set(schools.columns):
        raise CoverageError(f"the school directory lacks {sorted(needed - set(schools.columns))}")
    per_county = (
        schools.group_by("county_fips", "state", "county_name")
        .len()
        .sort("county_fips")
        .rows(named=True)
    )
    working, down = _station_counties(registry, states)
    districts = district_cover(registry, schools, states, weights)
    district_ids: list[JSONValue] = [
        i for i in sorted(registry.stations) if registry.stations[i].leaids
    ]
    county_covered: dict[str, int] = defaultdict(int)
    added = [0, 0.0]
    counties: dict[str, JSONValue] = {}
    county_schools: dict[str, int] = {}
    by_state: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    total = [0, 0]
    weighted_by_state: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    weighted_total = [0.0, 0.0]
    without_weight = 0
    station_schools: dict[str, int] = defaultdict(int)
    station_weighted: dict[str, float] = defaultdict(float)
    weighted_county: dict[str, float] = defaultdict(float)
    # A few schools carry a county of a neighbouring state: each (county, state) row
    # counts in its own state, and the county's entry sums its rows, named after the
    # row with the most schools.
    for row in sorted(per_county, key=lambda item: -int(item["len"])):
        fips, state, count = str(row["county_fips"]), str(row["state"]), int(row["len"])
        county_schools[fips] = county_schools.get(fips, 0) + count
        here = working.get(fips, [])
        part = count if here else min(districts.covered.get((fips, state), 0), count)
        county_covered[fips] += part
        added[0] += 0 if here else part
        for bucket in (by_state[state], total):
            bucket[0] += count
            bucket[1] += part
        summed = 0.0
        if weights is not None:
            summed, missing = weights.county(fips, state, count)
            without_weight += missing
            weighted_county[fips] += summed
            share = summed if here else min(districts.weighted.get((fips, state), 0.0), summed)
            added[1] += 0.0 if here else share
            for fbucket in (weighted_by_state[state], weighted_total):
                fbucket[0] += summed
                fbucket[1] += share
        for station_id in here + down.get(fips, []):
            station_schools[station_id] += count
            station_weighted[station_id] += summed
        entry = counties.get(fips)
        counties[fips] = {
            "state": entry["state"] if isinstance(entry, dict) else state,
            "name": entry["name"] if isinstance(entry, dict) else str(row["county_name"]),
            "schools": county_schools[fips],
            "weighted_schools": round(weighted_county[fips], 2) if weights is not None else None,
            "working": list(here),
            "not_working": list(down.get(fips, [])),
            "dmas": list(dmas.dma_of(fips)) if dmas is not None else [],
            "districts": list(districts.working.get(fips, [])),
            "districts_not_working": list(districts.down.get(fips, [])),
            "covered": county_covered[fips],
        }
    for station_id, number in districts.station_schools.items():
        station_schools[station_id] = number
        station_weighted[station_id] = districts.station_weighted.get(station_id, 0.0)
    counties = dict(sorted(counties.items()))
    without: list[JSONValue] = (
        [fips for fips in counties if not dmas.dma_of(fips)] if dmas is not None else []
    )
    dma_table = _dma_table(registry, states, dmas, county_schools) if dmas is not None else {}
    checked, check_summary = observed_check(registry, observed or {})
    weighted = weights is not None

    def pair(values: list[float]) -> tuple[float, float] | None:
        return (values[0], values[1]) if weighted else None

    return {
        "targets": {"national": NATIONAL_TARGET, "state": STATE_TARGET},
        "weights": None
        if weights is None
        else {**weights.provenance, "schools_without_weight": without_weight},
        "dma_summary": _dma_summary(dma_table),
        "national": _share(total[0], total[1], NATIONAL_TARGET, pair(weighted_total)),
        "states": {
            state: _share(values[0], values[1], STATE_TARGET, pair(weighted_by_state[state]))
            for state, values in sorted(by_state.items())
        },
        "counties": counties,
        "dmas": dma_table,
        "counties_without_dma": without,
        "districts": {
            "sources": district_ids,
            "working": [i for i in district_ids if states[str(i)].state == "working"],
            "schools_added": int(added[0]),
            "weighted_added": round(float(added[1]), 1) if weighted else None,
        },
        "stations": {
            station.id: {
                "state": states[station.id].state,
                "reason": states[station.id].reason,
                "counties": len(station.counties.fips) if station.counties else 0,
                "schools": station_schools.get(station.id, 0),
                "weighted_schools": round(station_weighted.get(station.id, 0.0), 1)
                if weighted
                else None,
                "observed": checked.get(station.id),
                **({"leaids": list(station.leaids)} if station.leaids else {}),
            }
            for station in sorted(registry.stations.values(), key=lambda s: s.id)
        },
        "observed_check": check_summary,
    }


def county_shapes(path: Path) -> dict[str, BaseGeometry]:
    """Read county boundaries, projected, keyed by five-digit FIPS.

    Census cartographic boundary files name the code ``GEOID``; NWS county files
    name it ``FIPS``. Either is read.
    """
    shapes: dict[str, BaseGeometry] = {}
    for record in read_zip(path):
        code = record.attributes.get("GEOID") or record.attributes.get("FIPS")
        if isinstance(code, str) and len(code) == FIPS_LENGTH and record.geometry is not None:
            shapes[code] = project(record.geometry)
    if not shapes:
        raise CoverageError(f"{path.name}: no county shapes")
    return shapes


def render_png(result: Mapping[str, JSONValue], shapes: Mapping[str, BaseGeometry]) -> bytes:
    """Draw covered counties against gaps for the counties in ``result``."""
    counties = result["counties"]
    if not isinstance(counties, dict):
        raise CoverageError("coverage result has no county table")
    colors: dict[str, Rgb] = {}
    tallies = {WORKING_COLOR: 0, DOWN_COLOR: 0, GAP_COLOR: 0}
    for fips, info in counties.items():
        if not isinstance(info, dict):
            continue
        if info.get("working"):
            color = WORKING_COLOR
        elif info.get("districts"):
            color = PART_COLOR
        elif info.get("not_working"):
            color = DOWN_COLOR
        else:
            color = GAP_COLOR
        colors[fips] = color
        tallies[color] = tallies.get(color, 0) + 1
    in_scope = {fips[:2] for fips in counties}
    drawn = {fips: shape for fips, shape in shapes.items() if fips[:2] in in_scope}
    image = render(drawn, colors, background=BACKGROUND, default=EMPTY_COLOR)
    national = result.get("national")
    title = "SCHOOLS IN COUNTIES A WORKING CLOSINGS SOURCE COVERS"
    if isinstance(national, dict):
        title += f": {float(str(national['share'])):.1%}"
        weighted = national.get("weighted")
        if isinstance(weighted, dict):
            title += f" (CLOSURE-WEIGHTED {float(str(weighted['share'])):.1%})"
    # The title and the legend go in bands above and below the map, never over it.
    header = _band(image.shape[1], HEADER_HEIGHT)
    draw_text(header, title, (24, 24), (230, 230, 230))
    labels = {
        PART_COLOR: "SOME SCHOOLS COVERED BY A WORKING DISTRICT SOURCE",
        WORKING_COLOR: "COVERED BY A WORKING SOURCE",
        DOWN_COLOR: "LISTED ONLY BY A SOURCE THAT IS STALE, FAILED OR NOT READ",
        GAP_COLOR: "NO SOURCE",
        EMPTY_COLOR: "NO SCHOOL IN THE DIRECTORY",
    }
    tallies[EMPTY_COLOR] = sum(fips not in colors for fips in drawn)
    legend = _band(image.shape[1], len(tallies) * 24 + 8)
    for offset, (color, count) in enumerate(tallies.items()):
        row = 8 + offset * 24
        legend[row : row + 14, 24:38] = color
        if color == EMPTY_COLOR:
            legend[row, 24:38] = legend[row + 13, 24:38] = GAP_COLOR
            legend[row : row + 14, 24] = legend[row : row + 14, 37] = GAP_COLOR
        draw_text(legend, f"{labels[color]}: {count} COUNTIES", (48, row), (200, 200, 200))
    image = np.vstack([header, image, legend])
    return png_bytes(_with_state_table(image, result.get("states"), result.get("proven")))


STATE_COLUMNS = 7
STATE_COLUMNS_WITH_PROOF = 3
STATE_ROW = 22
HEADER_HEIGHT = 48


def _band(width: int, height: int) -> npt.NDArray[np.uint8]:
    """An empty strip of the image's background, ``height`` pixels tall."""
    band = np.empty((height, width, 3), dtype=np.uint8)
    band[:, :] = BACKGROUND
    return band


def _shares_text(share: Mapping[str, JSONValue], digits: int) -> str:
    """``share`` as a percentage, with its closure-weighted share after a slash when given."""
    text = f"{float(str(share['share'])):.{digits}%}"
    inner = share.get("weighted")
    if isinstance(inner, dict):
        text += f" / {float(str(inner['share'])):.{digits}%}"
    return text


def _with_state_table(
    image: npt.NDArray[np.uint8], states: JSONValue, proven: JSONValue = None
) -> npt.NDArray[np.uint8]:
    """Add a panel under the map: each state's covered share, plain and closure-weighted.

    With ``proven`` (the ``proven`` part of the result, see
    :func:`snowlight.sources.stations.proof.add_proven`), the panel opens with the
    national proven share and gives each state's proven shares after its covered
    ones, in fewer columns; nothing is drawn over the map.
    """
    if not isinstance(states, dict) or not states:
        return image
    national = proven.get("national") if isinstance(proven, dict) else None
    by_state = proven.get("states") if isinstance(proven, dict) else None
    if not isinstance(national, dict) or not isinstance(by_state, dict):
        national = by_state = None
    columns = STATE_COLUMNS if by_state is None else STATE_COLUMNS_WITH_PROOF
    top = 8 if national is None else 40
    rows = -(-len(states) // columns)
    panel = _band(image.shape[1], rows * STATE_ROW + top + 48)
    if national is not None:
        line = "PROVEN (COUNTING ONLY LISTS SEEN WITH ROWS AT LEAST ONCE): "
        draw_text(panel, line + _shares_text(national, 1), (24, 8), (230, 230, 230))
    weighted = any(isinstance(v, dict) and "weighted" in v for v in states.values())
    heading = "BY STATE: SHARE OF SCHOOLS COVERED"
    heading += " / CLOSURE-WEIGHTED SHARE" if weighted else ""
    heading += ", THEN PROVEN SHARES" if by_state is not None else ""
    draw_text(panel, heading + " (TARGET 90%)", (24, top), (230, 230, 230))
    width = (image.shape[1] - 48) // columns
    for number, (state, share) in enumerate(sorted(states.items())):
        if not isinstance(share, dict):
            continue
        text = f"{state} {_shares_text(share, 0)}"
        proven_share = by_state.get(state) if by_state is not None else None
        if isinstance(proven_share, dict):
            text += f", PROVEN {_shares_text(proven_share, 0)}"
        color = (255, 214, 102) if share.get("meets_target") else (170, 170, 176)
        column, row = number % columns, number // columns
        draw_text(panel, text, (24 + column * width, top + 32 + row * STATE_ROW), color)
    return np.vstack([image, panel])


@dataclass(frozen=True, slots=True)
class CoverageMeta:
    """What the measure was computed from."""

    generated_at: datetime
    health_generated_at: str | None
    directory_path: Path
    references: dict[str, JSONValue]
    """Provenance of the reference files (DMA list, Gazetteer, county shapes)."""


def write_coverage(
    out_dir: Path,
    result: dict[str, JSONValue],
    meta: CoverageMeta,
    shapes: Mapping[str, BaseGeometry] | None,
) -> dict[str, Path]:
    """Write ``coverage.json`` (and ``coverage.png`` when shapes are given)."""
    digest = hashlib.sha256(meta.directory_path.read_bytes()).hexdigest()
    national = result["national"]
    schools = national["schools"] if isinstance(national, dict) else 0
    document: dict[str, JSONValue] = {
        "generated_at": iso_utc(meta.generated_at),
        "health_generated_at": meta.health_generated_at,
        "directory": {"path": meta.directory_path.name, "sha256": digest, "schools": schools},
        "references": meta.references,
        **result,
    }
    paths = {"json": out_dir / "coverage.json"}
    write_json(paths["json"], document)
    if shapes is not None:
        paths["png"] = out_dir / "coverage.png"
        write_bytes_atomic(paths["png"], render_png(result, shapes))
    return paths
