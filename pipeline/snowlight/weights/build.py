"""Build the closure weights and the station priority from the cache (downloading what is missing).

``python -m snowlight.weights build`` runs :func:`build`, which counts the rows
twice: by the county rule (:func:`count_weather`, :func:`summarize_counties`; kept
for comparison, the whole-county diagnostic and the station storm days) and for
each school in its own forecast zone (:mod:`snowlight.weights.perschool`, the
metric), and writes into ``pipeline/out/internal/weights/`` (internal, never
published):

* ``closure-weights.json``, ``state-weights.json``, ``station-priority.json``
  (shapes in :mod:`snowlight.weights`);
* ``method.md`` (the method note, with the checks' results),
  ``station-priority.md`` and ``closure-weights.png``;
* ``manifest.json``: every source file read (URL, retrieval time, SHA-256), the
  local inputs' checksums, and the checks' full results.

Every download goes through the checksummed cache (:mod:`snowlight.weights.cache`);
once the files are cached, and final, the build runs without the network.
"""

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path

from snowlight.output import JSONValue, write_bytes_atomic, write_json
from snowlight.sources.nws.boundaries import BoundaryRelease
from snowlight.sources.nws.http import (
    CachedFile,
    Clock,
    HttpCache,
    iso_utc,
    make_client,
    system_clock,
)
from snowlight.weather.hazards import CONUS_STATES
from snowlight.weights import (
    archive,
    count,
    crosscheck,
    markets,
    notes,
    outlines,
    perschool,
    polygons,
    priority,
    registered,
    render,
    schoolcount,
    schools,
    zonepolys,
    zones,
)
from snowlight.weights.cache import (
    DEFAULT_CACHE_DIR,
    PIPELINE_ROOT,
    SIBLING_CACHE_DIRS,
    WeightsCache,
    cache_path,
)
from snowlight.weights.codes import BY_CODE, CODES, SUBSETS

REPO_ROOT = PIPELINE_ROOT.parent
DEFAULT_OUT_DIR = PIPELINE_ROOT / "out" / "internal" / "weights"
DEFAULT_DIRECTORY = PIPELINE_ROOT / "out" / "internal" / "directory" / "schools.parquet"
DEFAULT_COVERAGE = PIPELINE_ROOT / "out" / "internal" / "stations" / "coverage.json"
DEFAULT_RESEARCH = REPO_ROOT / "docs" / "research"
SCHEMA = 3
SNOWY = ("RI", "MA", "NY", "MI", "MN", "PA")
MILD = ("MS", "LA", "FL")
WELL_ABOVE = 2.0
"""The sanity check's bar: each snowy state's winter days at least this multiple of
every mild state's."""
TOP = 10
RANK_MOVE = 10
"""A state whose rank moved by this many places from the county rule's is flagged."""
LEAD_MARGIN = timedelta(days=30)
"""How long before its window a school year's first product can have been issued."""
ALERT_TYPES_URL = "https://api.weather.gov/alerts/types"
"""The event names the NWS issues today (``eventTypes``), read to confirm the code changes."""
RETIRED_CODES: Mapping[str, tuple[str, str]] = {
    "WC.W": ("Wind Chill Warning", "Extreme Cold Warning"),
    "ZR.Y": ("Freezing Rain Advisory", "Winter Weather Advisory"),
    "LE.Y": ("Lake Effect Snow Advisory", "Winter Weather Advisory"),
}
"""Code to (its event name, the event that replaced it)."""


class WeightsBuildError(RuntimeError):
    """The build cannot produce trustworthy outputs."""


@dataclass(frozen=True, slots=True)
class Paths:
    """Where the build reads and writes."""

    cache_dir: Path = DEFAULT_CACHE_DIR
    out_dir: Path = DEFAULT_OUT_DIR
    directory: Path = DEFAULT_DIRECTORY
    coverage: Path = DEFAULT_COVERAGE
    research: Path = DEFAULT_RESEARCH
    registry: Path | None = registered.DEFAULT_REGISTRY_DIR
    """The station registry, read for two checks (``None``: skip them; see
    :mod:`snowlight.weights.registered`)."""
    siblings: tuple[Path, ...] = SIBLING_CACHE_DIRS
    """Other builds' caches whose verified copies are reused (read only)."""


@dataclass(slots=True)
class Result:
    """What the build computed, for the notes and the command's summary."""

    counties: dict[str, dict[str, JSONValue]]
    """The county summaries (counties with schools), by FIPS code."""
    states: list[dict[str, JSONValue]]
    mean_days: float
    """The per-school normalizer: mean weighted days per school year over every school."""
    whole_mean_days: float
    schools: int
    sanity: dict[str, JSONValue]
    flags: list[dict[str, JSONValue]]
    checks: dict[str, JSONValue]
    priority: dict[str, JSONValue]
    generated_at: str = ""
    references: dict[str, JSONValue] = field(default_factory=dict)
    adopted: list[str] = field(default_factory=list)
    """URLs whose cached copy came from another build's cache."""
    paths: dict[str, Path] = field(default_factory=dict)
    county_rule_mean: float = 0.0
    """The county rule's normalizer (its school-weighted mean days per school year)."""
    school_records: dict[str, JSONValue] = field(default_factory=dict)
    counties_without_schools: list[str] = field(default_factory=list)
    county_rule_records: dict[str, dict[str, JSONValue]] = field(default_factory=dict)
    """Every county's record under the county rule (:func:`county_records`)."""
    per_school: perschool.PerSchool | None = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _local(path: Path) -> dict[str, JSONValue]:
    """Record a local input: its path (relative to the repository when inside it) and hash."""
    resolved = path.resolve()
    shown = resolved.relative_to(REPO_ROOT) if resolved.is_relative_to(REPO_ROOT) else resolved
    return {"path": str(shown), "sha256": _sha256(path)}


def _provenance(file: CachedFile | None) -> JSONValue:
    return None if file is None else file.provenance.as_json()


def _strings(values: Sequence[str]) -> list[JSONValue]:
    return [str(value) for value in sorted(values)]


def _round(value: float, places: int = 4) -> float:
    return round(value + 0.0, places)


# --- counting ------------------------------------------------------------------------------


@dataclass(slots=True)
class Counted:
    """The weather side of the build.

    :func:`count_weather` fills everything but ``summary`` and ``outline_report``,
    which :func:`summarize_counties` adds.
    """

    counties: zones.CountyList
    releases: list[zones.ZoneRelease]
    files: list[archive.SchoolYearFile]
    catalog: zones.ZoneCountyCatalog
    tally: count.Tally
    names: list[crosscheck.NameCheck]
    outline_book: outlines.OutlineBook | None = None
    summary: dict[str, count.CountyDays] = field(default_factory=dict)
    """Every county's averages over the school years counted for it."""
    outline_report: outlines.OutlineReport | None = None
    """The outline checks, with the county-years left out as incomplete."""


@dataclass(frozen=True, slots=True)
class Scope:
    """Which source files the build reads (the defaults are the real build's)."""

    years: tuple[int, ...] = tuple(archive.school_years())
    releases: tuple[str, ...] = zones.RELEASES
    county_release: BoundaryRelease = zones.COUNTY_RELEASE
    day_windows: tuple[tuple[date, date], ...] = crosscheck.WINDOWS
    dma_sha256: str = markets.DMA_CROSSWALK_SHA256
    """The DMA crosswalk's pinned SHA-256 (the registry's)."""
    zone_releases: tuple[BoundaryRelease, ...] = zonepolys.ZONE_RELEASES
    """The served NWS zone releases (:mod:`snowlight.weights.zonepolys`)."""
    outline_check: bool = True
    """Whether to check the zone mapping against IEM's archived outlines (without them, a
    build whose rows include left-out zone rows stops: it cannot tell which county-years
    those rows leave incomplete)."""


def lead_days() -> int:
    """Days between the start of a school-year file's window and the first school day."""
    start = date(2000, *archive.REQUEST_START)
    return (date(2000, *count.FIRST_SCHOOL_DAY) - start).days


def count_weather(cache: WeightsCache, scope: Scope = Scope()) -> Counted:  # noqa: B008
    """Load the county list, the correlation releases and the school years, and count.

    The counties are not summarized yet (:func:`summarize_counties` does it); the
    tally holds every row that could be mapped.

    Raises:
        WeightsBuildError: a school-year file is still provisional, or a row lasted
            longer than the window's lead (a row that began before the window could
            then have reached the first school day).
    """
    counties = zones.load_counties(cache, scope.county_release)
    releases = zones.load_releases(cache, scope.releases)
    files = archive.load_years(cache, scope.years)
    provisional = [file.label for file in files if not file.final]
    if provisional:
        raise WeightsBuildError(f"school-year files still provisional: {provisional}")
    lead = lead_days()
    longest = max(file.stats.longest_row_days for file in files)
    if longest >= lead:
        raise WeightsBuildError(
            f"a row lasted {longest:.1f} days, longer than the {lead}-day lead of the "
            "request window: rows beginning before it could reach the first school day"
        )
    catalog = zones.ZoneCountyCatalog(releases, counties.state_fips)
    book = outlines.OutlineBook(cache, counties) if scope.outline_check else None
    names = check_zone_names(cache, files, catalog, book)
    tally = count.count_years(files, catalog, counties)
    return Counted(counties, releases, files, catalog, tally, names, book)


def summarize_counties(counted: Counted) -> Counted:
    """Find the incomplete county-years and summarize every county without them.

    A county-year is incomplete when zone rows covering the county could not be
    counted for it (:mod:`snowlight.weights.outlines`); each county is averaged
    over its other school years (:func:`snowlight.weights.count.summarize`).

    Raises:
        WeightsBuildError: zone rows were left out and the outline check, which
            finds the counties they covered, is off or has no outline of a zone;
            or a county has no school year left.
    """
    report: outlines.OutlineReport | None = None
    left_out: dict[str, frozenset[int]] = {}
    if counted.outline_book is not None:
        try:
            report = outlines.check_outlines(
                counted.outline_book,
                counted.files,
                counted.catalog,
                counted.counties,
                counted.tally,
            )
        except outlines.OutlineError as error:
            raise WeightsBuildError(str(error)) from error
        left_out = report.left_out_years()
    else:
        resolved = counted.catalog.stats.by_resolution
        dropped = resolved.get("unmapped", 0) + resolved.get("left_out_renamed", 0)
        if dropped:
            raise WeightsBuildError(
                f"{dropped} zone rows were left out and the outline check is off: the "
                "county-years they leave incomplete cannot be found"
            )
    zones_on = count.ZonesOnDay(counted.catalog)
    try:
        summary = count.summarize(
            counted.tally, counted.counties.counties, zones_on, SUBSETS, left_out
        )
    except count.CountError as error:
        raise WeightsBuildError(str(error)) from error
    return replace(counted, summary=summary, outline_report=report)


def check_zone_names(
    cache: WeightsCache,
    files: Sequence[archive.SchoolYearFile],
    catalog: zones.ZoneCountyCatalog,
    book: outlines.OutlineBook | None = None,
) -> list[crosscheck.NameCheck]:
    """Compare the names of the zones read in the first release before it took effect.

    Zones whose names disagree are left out of ``catalog`` for their school year
    (see :mod:`snowlight.weights.crosscheck`), unless ``book`` shows that the
    zone's outline at the time covered the counties the release lists.
    """
    first = catalog.releases[0]
    zones_by_year: dict[int, set[str]] = defaultdict(set)
    for file in files:
        for row in file.rows:
            issued = row.product_issued.date()
            if row.ugc[2] == "Z" and issued < first.valid_from and row.ugc in first.counties:
                zones_by_year[file.year].add(row.ugc)
    checks = crosscheck.compare_zone_names(cache, zones_by_year, first)
    for check in checks:
        if book is not None:
            for entry in list(check.left_out):
                ugc = entry.split(":", 1)[0]
                shares = book.shares(check.year, ugc)
                if shares is not None and outlines.agrees(first.counties[ugc], shares):
                    check.left_out.remove(entry)
                    covered = ", ".join(
                        f"{fips} {share:.0%}"
                        for fips, share in sorted(shares.items())
                        if share >= outlines.TOUCH
                    )
                    check.kept_by_outline.append(f"{entry}; outline then: {covered}")
        start, end = archive.request_window(check.year)
        for ugc in check.left_out_zones:
            catalog.exclude(ugc, start - LEAD_MARGIN, min(end, first.valid_from))
    return checks


# --- assembling ----------------------------------------------------------------------------


def school_mean(values: Mapping[str, float], per_county: Mapping[str, int]) -> float:
    """Return the mean over schools of their county's value."""
    total = sum(per_county.values())
    if total <= 0:
        raise WeightsBuildError("no school was placed in a county")
    mean = sum(values[fips] * n for fips, n in per_county.items()) / total
    if mean <= 0:
        raise WeightsBuildError("no school's county had a closure-type day")
    return mean


def _zone_names(releases: Sequence[zones.ZoneRelease]) -> dict[str, str]:
    names: dict[str, str] = {}
    for release in releases:
        names.update(release.names)
    return names


def county_records(
    counted: Counted,
    per_county: Mapping[str, int],
    mean: float,
    whole_mean: float,
) -> dict[str, dict[str, JSONValue]]:
    """Return every county's record for ``closure-weights.json``.

    Every per-year figure is over the school years counted for the county
    (``years_counted``); a school year left out as incomplete has ``null`` in
    ``by_year`` and its zones in ``school_years_left_out``. ``left_out_zone_days``
    (school year to weighted days) are the days the left-out zone rows would add
    (:mod:`snowlight.weights.outlines`): a diagnostic, never in the metric.
    """
    report = counted.outline_report
    gains = report.gains if report is not None else {}
    incomplete = report.incomplete if report is not None else {}
    names = _zone_names(counted.releases)
    years = counted.tally.years
    records: dict[str, dict[str, JSONValue]] = {}
    for fips, county in sorted(counted.counties.counties.items()):
        days = counted.summary[fips]
        drivers = sorted(days.drivers.items(), key=lambda item: (-item[1][0], item[0]))
        by_year: dict[str, JSONValue] = {}
        for year in years:
            value = days.by_year[year]
            by_year[archive.school_year_label(year)] = (
                None if value is None else {"weighted": _round(value[0], 2), "days": value[1]}
            )
        records[fips] = {
            "fips": fips,
            "state": county.state,
            "name": county.name,
            "time_zones": list(county.time_zones),
            "schools": per_county.get(fips, 0),
            "years_counted": len(days.years_counted),
            "school_years_left_out": {
                archive.school_year_label(year): _strings(sorted(ugcs))
                for year, ugcs in sorted(incomplete.get(fips, {}).items())
            },
            "weighted_days_total": _round(days.weighted_days_total, 2),
            "days_per_year": _round(days.days_per_year),
            "weight": _round(days.days_per_year / mean),
            "any_days_per_year": _round(days.any_days_per_year),
            "whole_county_days_per_year": _round(days.whole_county_days_per_year),
            "whole_county_weight": _round(days.whole_county_days_per_year / whole_mean),
            "subsets_days_per_year": {
                name: _round(value) for name, value in sorted(days.subset_days_per_year.items())
            },
            "codes": {
                code.code: {
                    "days": days.code_days[code.code],
                    "per_year": _round(days.code_days_per_year(code.code)),
                }
                for code in CODES
            },
            "by_year": by_year,
            "top_zones": [
                {"ugc": ugc, "name": names.get(ugc), "days": covered, "only": only}
                for ugc, (covered, only) in drivers[:3]
            ],
            "left_out_zone_days": {
                label: _round(value, 2) for label, value in gains.get(fips, {}).items()
            },
        }
    return records


def _state_value(row: Mapping[str, JSONValue], key: str) -> float:
    subsets = row["subsets_days_per_year"]
    if isinstance(subsets, dict) and key in subsets:
        return float(str(subsets[key]))
    return float(str(row[key]))


def sanity_check(rows: Sequence[Mapping[str, JSONValue]]) -> dict[str, JSONValue]:
    """Compare the snowy states' winter days with the mild states' (the owner's check).

    The check passes for a code subset when every snowy state's days are at least
    :data:`WELL_ABOVE` times every mild state's and above zero. A state missing
    from ``rows`` fails it (and is listed).
    """
    by_state = {str(row["state"]): row for row in rows}
    missing = [state for state in (*SNOWY, *MILD) if state not in by_state]
    result: dict[str, JSONValue] = {
        "snowy": list(SNOWY),
        "mild": list(MILD),
        "missing_states": list(missing),
    }
    for key in ("listed_winter", "winter"):
        high = {s: _state_value(by_state[s], key) for s in SNOWY if s in by_state}
        low = {s: _state_value(by_state[s], key) for s in MILD if s in by_state}
        lowest = min(high.values(), default=0.0)
        highest = max(low.values(), default=0.0)
        ratio = lowest / highest if highest > 0 else None
        result[key] = {
            "snowy_days_per_year": {k: _round(v) for k, v in high.items()},
            "mild_days_per_year": {k: _round(v) for k, v in low.items()},
            "lowest_snowy_over_highest_mild": None if ratio is None else _round(ratio, 2),
            "passes": not missing and lowest > 0 and lowest >= WELL_ABOVE * highest,
        }
    weights = {s: _state_value(by_state[s], "weight") for s in (*SNOWY, *MILD) if s in by_state}
    result["weights"] = {k: _round(v) for k, v in weights.items()}
    result["bar"] = f"every snowy state's winter days at least {WELL_ABOVE:g}x every mild state's"
    return result


def _code_text(row: Mapping[str, JSONValue]) -> str:
    return ", ".join(
        f"{code} {value:.2f}" for code, value in _nonzero(row["code_days_per_year"]).items()
    )


def surprises(
    rows: Sequence[Mapping[str, JSONValue]],
    records: Mapping[str, Mapping[str, JSONValue]],
) -> list[dict[str, JSONValue]]:
    """Flag results that may surprise, each with the data behind it (nothing is changed).

    Flagged: every top-ten state that is not one of the owner's snowy examples,
    every snowy example whose weight is below the national mean, and every state
    whose rank moved by :data:`RANK_MOVE` places or more from the county rule's. Each
    flag gives the state's code days per year and its biggest counties by schools,
    with their per-school and county-rule weights and the zones their schools are in.
    """
    flags: list[dict[str, JSONValue]] = []
    by_state: dict[str, list[str]] = defaultdict(list)
    for fips, record in records.items():
        by_state[str(record["state"])].append(fips)
    snowy_max = max(
        (float(str(row["weight"])) for row in rows if row["state"] in SNOWY), default=0.0
    )

    def biggest(state: str) -> list[JSONValue]:
        codes = sorted(by_state[state], key=lambda f: (-int(str(records[f]["schools"])), f))[:3]
        return [_county_brief(records[fips]) for fips in codes]

    for position, row in enumerate(rows):
        state = str(row["state"])
        weight = float(str(row["weight"]))
        rule_rank = int(str(row["county_rule_rank"]))
        moved = rule_rank - int(str(row["rank"]))
        reasons: list[str] = []
        if position < TOP and state not in SNOWY:
            reasons.append("in the top ten and not one of the owner's snowy examples")
        if state in SNOWY and weight < 1.0:
            reasons.append("one of the owner's snowy examples, below the national mean")
        if abs(moved) >= RANK_MOVE:
            reasons.append(
                f"{'up' if moved > 0 else 'down'} {abs(moved)} places from the county rule"
            )
        if not reasons:
            continue
        finding = (
            f"ranks {row['rank']} with weight {weight:.2f} ({float(str(row['days_per_year'])):.2f} "
            f"weighted days a year); by the county rule it ranked {rule_rank} with "
            f"{float(str(row['county_rule_weight'])):.2f}"
        )
        if weight > snowy_max:
            finding += f"; above every one of {', '.join(SNOWY)}"
        reason = (
            "; ".join(reasons).capitalize()
            + f". Its code days per school year: {_code_text(row)}. Its biggest counties:"
        )
        flags.append(
            {"state": state, "finding": finding, "reason": reason, "counties": biggest(state)}
        )
    return flags


def _nonzero(value: JSONValue) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    return {k: float(str(v)) for k, v in value.items() if float(str(v)) >= 0.05}  # noqa: PLR2004


def _county_brief(record: Mapping[str, JSONValue]) -> dict[str, JSONValue]:
    rule = record["county_rule"]
    zones_held = record["zones"]
    return {
        "fips": record["fips"],
        "name": record["name"],
        "schools": record["schools"],
        "weight": record["weight"],
        "days_per_year": record["days_per_year"],
        "county_rule_weight": rule["weight"] if isinstance(rule, dict) else None,
        "whole_county_days_per_year": record["whole_county_days_per_year"],
        "zones": dict(list(zones_held.items())[:4]) if isinstance(zones_held, dict) else {},
    }


# --- checks --------------------------------------------------------------------------------


def _yearly_means(
    counted: Counted, per_county: Mapping[str, int], members: Sequence[str]
) -> dict[int, float] | None:
    """Return the school-weighted mean weighted days of ``members`` in each school year."""
    schools_n = sum(per_county.get(fips, 0) for fips in members)
    if not schools_n:
        return None
    means: dict[int, float] = {}
    for year in counted.tally.years:
        total = 0.0
        for fips in members:
            value = counted.summary[fips].by_year[year]
            total += per_county.get(fips, 0) * (value[0] if value is not None else 0.0)
        means[year] = total / schools_n
    return means


def _ratio(means: Mapping[int, float] | None, kept: Sequence[int]) -> JSONValue:
    if means is None:
        return None
    overall = sum(means.values()) / len(means)
    if overall <= 0:
        return None
    return _round(sum(means[year] for year in kept) / len(kept) / overall, 3)


def period_effects(counted: Counted, per_county: Mapping[str, int]) -> list[JSONValue]:
    """Show how the school years a county keeps compare with all of them (nothing changes).

    A county with school years left out is averaged over the others. For each
    state and set of school years counted (other than all of them): the counties
    and schools averaged over it, and the ratio of the school-weighted mean over
    those years to the mean over all years, among the counties that keep every
    year, nationally and in the same state. A ratio far from 1 means those years
    were stormier or milder than the period as a whole, and the counties averaged
    over them are lifted or lowered by about as much.
    """
    years = counted.tally.years
    complete = [fips for fips, days in counted.summary.items() if not days.years_left_out]
    states = {fips: county.state for fips, county in counted.counties.counties.items()}
    national = _yearly_means(counted, per_county, complete)
    by_state: dict[str, list[str]] = defaultdict(list)
    for fips in complete:
        by_state[states[fips]].append(fips)
    groups: dict[tuple[str, tuple[int, ...]], list[str]] = defaultdict(list)
    for fips, days in counted.summary.items():
        if days.years_left_out:
            groups[(states[fips], days.years_counted)].append(fips)
    found: list[JSONValue] = []
    for (state, kept), members in sorted(groups.items()):
        state_means = _yearly_means(counted, per_county, by_state.get(state, []))
        found.append(
            {
                "state": state,
                "school_years_counted": [archive.school_year_label(year) for year in kept],
                "school_years_left_out": [
                    archive.school_year_label(year) for year in years if year not in kept
                ],
                "counties": _strings(members),
                "schools": sum(per_county.get(fips, 0) for fips in members),
                "national_ratio": _ratio(national, kept),
                "state_ratio": _ratio(state_means, kept),
            }
        )
    return found


def code_changes(
    cache: WeightsCache, files: Sequence[archive.SchoolYearFile]
) -> tuple[dict[str, JSONValue], CachedFile]:
    """Show, from the rows and today's NWS event list, which codes were replaced and when.

    For each code in :data:`RETIRED_CODES` and each code that replaced one: its
    rows per school year and the last school year with any; and whether today's
    event list (:data:`ALERT_TYPES_URL`, cached once) still names the event.

    Raises:
        WeightsBuildError: the event list is not the documented JSON.
    """
    file = cache.fetch(ALERT_TYPES_URL, cache_path(cache.root, ALERT_TYPES_URL, suffix=".json"))
    document = json.loads(file.path.read_text(encoding="utf-8"))
    names = document.get("eventTypes") if isinstance(document, dict) else None
    if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
        raise WeightsBuildError(f"{ALERT_TYPES_URL}: no eventTypes list")
    events = {BY_CODE[code].name for code in RETIRED_CODES} | {
        after for _, after in RETIRED_CODES.values()
    }
    watched = sorted({*RETIRED_CODES, "EC.W", "WW.Y"})
    rows: dict[str, JSONValue] = {}
    last: dict[str, JSONValue] = {}
    for code in watched:
        per_year = {file.label: file.stats.by_code.get(code, 0) for file in files}
        rows[code] = dict(per_year)
        years_with_rows = [label for label, n in per_year.items() if n]
        last[code] = years_with_rows[-1] if years_with_rows else None
    changes: dict[str, JSONValue] = {
        "replaced": {
            code: {"event": before, "replaced_by": after}
            for code, (before, after) in RETIRED_CODES.items()
        },
        "named_in_todays_event_list": {name: name in names for name in sorted(events)},
        "rows_by_school_year": rows,
        "last_school_year_with_rows": last,
    }
    return changes, file


def county_name_conflicts(counted: Counted) -> list[JSONValue]:
    """List the correlation records whose county name contradicts their FIPS code.

    Each is kept as published (the FIPS code decides the county); the list gives
    the releases that carry it.
    """
    names = {fips: county.name for fips, county in counted.counties.counties.items()}
    found: dict[tuple[str, str, str, str], list[str]] = defaultdict(list)
    for release in counted.releases:
        for conflict in zones.county_name_conflicts(release, names):
            found[conflict].append(release.name)
    return [
        {
            "ugc": ugc,
            "fips": fips,
            "county_as_written": written,
            "county_of_fips": known,
            "releases": list(releases),
        }
        for (ugc, fips, written, known), releases in sorted(found.items())
    ]


def run_checks(
    cache: WeightsCache, counted: Counted, windows: Sequence[tuple[date, date]]
) -> dict[str, JSONValue]:
    """Run the cross-checks (day files, zone names) and collect the data checks."""
    checks: dict[str, JSONValue] = {}
    mapping = counted.catalog.stats
    checks["zone_mapping"] = {
        "rows_by_resolution": dict(sorted(mapping.by_resolution.items())),
        "unmapped_ugcs": dict(mapping.unmapped.most_common()),
        "left_out_renamed": dict(mapping.left_out.most_common()),
        "nearest_release": {
            f"{ugc} in {release}": n for (ugc, release), n in sorted(mapping.nearest.items())
        },
        "counties_not_in_county_list": dict(counted.tally.stats.unknown_counties.most_common()),
        "state_zone_mismatches": {
            release.name: list(release.state_zone_mismatches)
            for release in counted.releases
            if release.state_zone_mismatches
        },
        "county_name_conflicts": county_name_conflicts(counted),
    }
    checks["rows"] = {
        "school_years": {
            file.label: {
                "rows": file.stats.rows,
                "kept": file.stats.kept,
                "polygon_rows": file.stats.polygon_rows,
                "outside_states": dict(sorted(file.stats.outside_states.items())),
                "ended_before_start": file.stats.ended_before_start,
                "by_code": dict(sorted(file.stats.by_code.items())),
                "longest_row_days": _round(file.stats.longest_row_days, 2),
                "tropical_rows_ended": [
                    {
                        "event": row.event_key,
                        "ugc": row.ugc,
                        "status": row.status,
                        "recorded_end": iso_utc(row.recorded_end),
                        "end": None if row.end is None else iso_utc(row.end),
                    }
                    for row in file.stats.closed_tropical
                ],
            }
            for file in counted.files
        },
        "counted_rows": counted.tally.stats.rows_counted,
        "rows_without_county": counted.tally.stats.rows_without_county,
    }
    if windows:
        fresh = zones.ZoneCountyCatalog(counted.releases, counted.counties.state_fips)
        compared = crosscheck.compare_days(
            crosscheck.make_day_archive(cache),
            counted.files,
            crosscheck.CountyMapper(fresh, counted.counties),
            windows,
        )
        checks["day_files"] = [window.as_json() for window in compared]
    checks["zone_names_before_first_release"] = [check.as_json() for check in counted.names]
    return checks


# --- station priority ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Markets:
    """The DMA crosswalk and the county lists it is read with."""

    crosswalk: markets.DmaCounties
    county_ids: dict[tuple[str, str], str]
    state_counties: dict[str, frozenset[str]]
    files: dict[str, CachedFile]


def load_markets(cache: WeightsCache, dma_sha256: str = markets.DMA_CROSSWALK_SHA256) -> Markets:
    """Download (or reuse) and read the DMA crosswalk, the Gazetteer and the CT crosswalk.

    Raises:
        WeightsBuildError: the crosswalk is not the pinned file.
    """
    urls = {
        "dma": markets.DMA_CROSSWALK_URL,
        "gazetteer": markets.COUNTY_GAZETTEER_URL,
        "ct": markets.CT_CROSSWALK_URL,
    }
    files = {key: cache.fetch(url, cache_path(cache.root, url)) for key, url in urls.items()}
    if files["dma"].provenance.sha256 != dma_sha256:
        raise WeightsBuildError("the DMA crosswalk's SHA-256 is not the pinned one")
    gazetteer = markets.read_gazetteer(files["gazetteer"].path)
    connecticut = markets.read_ct_regions(files["ct"].path)
    crosswalk = markets.read_crosswalk(files["dma"].path, gazetteer, connecticut)
    state_sets: dict[str, set[str]] = defaultdict(set)
    for county in gazetteer:
        if county.state in CONUS_STATES:
            state_sets[county.state].add(county.fips)
    return Markets(
        crosswalk=crosswalk,
        county_ids=markets.county_index(gazetteer),
        state_counties={state: frozenset(codes) for state, codes in state_sets.items()},
        files=files,
    )


@dataclass(frozen=True, slots=True)
class Tables:
    """Schools per directory county, under each weighting the ranking reports."""

    weighted: priority.SchoolWeights
    whole: priority.SchoolWeights
    plain: priority.SchoolWeights


def school_tables(
    placement: schools.Placement,
    weights: Sequence[float],
    whole_weights: Mapping[str, float],
) -> Tables:
    """Sum schools and their weights per directory county.

    ``weights`` are the schools' own weights, in the order of ``placement.schools``;
    ``whole_weights`` are the whole-county diagnostic's, per NWS county.
    """
    if len(weights) != len(placement.schools):
        raise WeightsBuildError("school weights and placed schools differ in number")
    counts: Counter[str] = Counter()
    weighted: dict[str, float] = defaultdict(float)
    whole: dict[str, float] = defaultdict(float)
    for school, weight in zip(placement.schools, weights, strict=True):
        counts[school.directory_fips] += 1
        weighted[school.directory_fips] += weight
        whole[school.directory_fips] += whole_weights[school.nws_fips]
    plain = {fips: float(n) for fips, n in counts.items()}
    return Tables(
        priority.SchoolWeights(dict(counts), dict(weighted)),
        priority.SchoolWeights(dict(counts), dict(whole)),
        priority.SchoolWeights(dict(counts), plain),
    )


def _family_record(
    step: priority.Step,
    items: Sequence[priority.Resolved],
    baselines: tuple[frozenset[str], frozenset[str]],
    table: priority.SchoolWeights,
) -> dict[str, JSONValue]:
    working, every = baselines
    counties = frozenset().union(*(item.counties for item in items))
    alone_schools, alone_weighted = table.totals(counties - working)
    beyond_schools, beyond_weighted = table.totals(counties - every)
    fresh = frozenset().union(*(item.counties for item in items if item.source.stale_since is None))
    fresh_schools, fresh_weighted = table.totals(fresh - working)
    market_schools, market_weighted = table.totals(counties)
    total_schools, total_weighted = table.totals(table.schools)
    return {
        "rank": step.rank,
        "id": step.family,
        "name": priority.FAMILY_NAMES[step.family],
        "sources": len(items),
        "sources_robots_blocked": sum(item.source.robots_blocked for item in items),
        "market_counties": len(counties),
        "market_schools": market_schools,
        "market_weighted_schools": _round(market_weighted, 1),
        "standalone": {
            "new_counties": len(counties - working),
            "new_schools": alone_schools,
            "new_weighted_schools": _round(alone_weighted, 1),
        },
        "standalone_beyond_every_working_source": {
            "new_counties": len(counties - every),
            "new_schools": beyond_schools,
            "new_weighted_schools": _round(beyond_weighted, 1),
        },
        "standalone_without_stale_members": {
            "stale_members": sum(item.source.stale_since is not None for item in items),
            "new_schools": fresh_schools,
            "new_weighted_schools": _round(fresh_weighted, 1),
        },
        "in_order": {
            "new_counties": step.new_counties,
            "new_schools": step.new_schools,
            "new_weighted_schools": _round(step.new_weighted, 1),
            "cumulative_schools": step.cumulative_schools,
            "cumulative_share": _round(step.cumulative_schools / total_schools, 4),
            "cumulative_weighted_share": _round(step.cumulative_weighted / total_weighted, 4),
        },
        "members": [priority.member_json(item) for item in items],
    }


def rank_families(
    classified: priority.Classification,
    working: frozenset[str],
    listed: frozenset[str],
    tables: Tables,
    every: frozenset[str] | None = None,
) -> list[JSONValue]:
    """Return every family's record, in the order to build them (see :mod:`...priority`).

    ``working`` and ``listed`` are the Gray and Hearst baseline; ``every`` (default:
    ``working``) is every working source's counties, for the alternative ranking.
    """
    every = working if every is None else every
    members = priority.family_members(classified)
    family_counties = {
        family: frozenset().union(*(item.counties for item in items))
        for family, items in members.items()
    }

    def ranks(baseline: frozenset[str], table: priority.SchoolWeights) -> dict[str, int]:
        steps = priority.greedy_order(family_counties, baseline, table)
        return {step.family: step.rank for step in steps}

    fresh_counties = {
        family: frozenset().union(
            *(item.counties for item in items if item.source.stale_since is None)
        )
        for family, items in members.items()
    }
    fresh_steps = priority.greedy_order(fresh_counties, working, tables.weighted)
    alternatives = {
        "rank_without_stale_members": {step.family: step.rank for step in fresh_steps},
        "rank_if_every_listed_gray_hearst_county_counted": ranks(listed, tables.weighted),
        "rank_with_whole_county_weights": ranks(working, tables.whole),
        "rank_by_schools_unweighted": ranks(working, tables.plain),
        "rank_beyond_every_working_source": ranks(every, tables.weighted),
    }
    records: list[JSONValue] = []
    for step in priority.greedy_order(family_counties, working, tables.weighted):
        record = _family_record(step, members[step.family], (working, every), tables.weighted)
        for key, table in alternatives.items():
            record[key] = table[step.family]
        records.append(record)
    return records


def registry_checks(
    folder: Path | None,
    classified: priority.Classification,
    crosswalk: markets.DmaCounties,
) -> tuple[JSONValue, JSONValue]:
    """Run the two optional registry checks (see :mod:`snowlight.weights.registered`).

    Returns the Gray check and the market check, or for both the reason they were
    not run: ``"not read"`` (no folder given) or the error reading the registry.
    """
    if folder is None:
        return "not read", "not read"
    try:
        stations = registered.read_registry(folder)
    except registered.RegistryReadError as error:
        reason = f"the registry could not be read: {error}"
        return reason, reason
    gray = priority.gray_cover(classified.left_out, registered.by_call_sign(stations))
    return gray, registered.market_agreement(stations, crosswalk)


def station_priority(
    cache: WeightsCache,
    paths: Paths,
    tables: Tables,
    scope: Scope = Scope(),  # noqa: B008
) -> tuple[dict[str, JSONValue], dict[str, JSONValue]]:
    """Rank the scraper families; return the document and the reference provenance.

    Raises:
        WeightsBuildError: a counted record's market cannot be found.
    """
    market_files = load_markets(cache, scope.dma_sha256)
    sources = priority.read_firsthand(paths.research / "firsthand")
    anchors = priority.read_anchors(paths.research / "sources.json")
    resolver = priority.MarketResolver(market_files.crosswalk.by_dma, anchors)
    classified = priority.classify(
        sources,
        resolver,
        market_files.crosswalk,
        market_files.county_ids,
        market_files.state_counties,
    )
    if classified.unresolved:
        names = [source.name for source in classified.unresolved]
        raise WeightsBuildError(f"records whose market could not be found: {names}")
    coverage = json.loads(paths.coverage.read_text(encoding="utf-8"))
    working, listed = priority.baseline_counties(coverage)
    every, _ = priority.baseline_counties(coverage, groups=None)
    table = tables.weighted
    total_schools, total_weighted = table.totals(table.schools)
    base_schools, base_weighted = table.totals(working)
    every_schools, every_weighted = table.totals(every)
    left_out: dict[str, list[str]] = defaultdict(list)
    for source, reason in classified.left_out:
        left_out[reason].append(source.name)
    gray_check, market_check = registry_checks(paths.registry, classified, market_files.crosswalk)
    document: dict[str, JSONValue] = {
        "schema": SCHEMA,
        "baseline": {
            "what": "counties a working Gray or Hearst source lists (coverage.json)",
            "counties": len(working),
            "schools": base_schools,
            "weighted_schools": _round(base_weighted, 1),
            "share": _round(base_schools / total_schools, 4),
            "weighted_share": _round(base_weighted / total_weighted, 4),
            "counties_any_gray_hearst_station_lists": len(listed),
            "working_stations_by_group": dict(priority.working_stations(coverage)),
            "every_working_source": {
                "counties": len(every),
                "schools": every_schools,
                "weighted_schools": _round(every_weighted, 1),
                "share": _round(every_schools / total_schools, 4),
                "weighted_share": _round(every_weighted / total_weighted, 4),
            },
        },
        "schools": total_schools,
        "weighted_schools": _round(total_weighted, 1),
        "families": rank_families(classified, working, listed, tables, every),
        "records": {
            "counted": len(classified.resolved),
            "left_out": len(classified.left_out),
            "left_out_by_reason": {k: _strings(v) for k, v in sorted(left_out.items())},
            "left_out_as_gray_checked_in_registry": gray_check,
        },
        "market_counties_checked_in_registry": market_check,
    }
    references: dict[str, JSONValue] = {
        key: _provenance(file) for key, file in market_files.files.items()
    }
    references["firsthand"] = [
        _local(paths.research / "firsthand" / name) for name in priority.FIRSTHAND_FILES
    ]
    references["sources_json"] = _local(paths.research / "sources.json")
    references["coverage"] = {
        **_local(paths.coverage),
        "generated_at": coverage.get("generated_at"),
    }
    return document, references


# --- the build -----------------------------------------------------------------------------


def build(
    paths: Paths = Paths(),  # noqa: B008
    *,
    scope: Scope = Scope(),  # noqa: B008
    clock: Clock = system_clock,
    day_files: bool = True,
    cache: HttpCache | None = None,
) -> Result:
    """Build every output (see the module docstring) and return what was computed.

    ``day_files=False`` skips the cross-check against the day-file client; ``cache``
    lets tests serve the files.
    """
    own = cache is None
    http = cache if cache is not None else HttpCache(make_client(), clock=clock)
    if not day_files:
        scope = replace(scope, day_windows=())
    try:
        return _build(paths, WeightsCache(http, paths.cache_dir, paths.siblings), scope, clock)
    finally:
        if own:
            http.client.close()


def _build(paths: Paths, cache: WeightsCache, scope: Scope, clock: Clock) -> Result:
    started = clock()
    counted = summarize_counties(count_weather(cache, scope))
    frame = schools.read_schools(paths.directory)
    placement = schools.place_schools(frame, counted.counties)
    per_county = placement.per_county()
    rule_mean = school_mean({f: d.days_per_year for f, d in counted.summary.items()}, per_county)
    whole_mean = school_mean(
        {f: d.whole_county_days_per_year for f, d in counted.summary.items()}, per_county
    )
    rule_records = county_records(counted, per_county, rule_mean, whole_mean)
    try:
        per = perschool.count_per_school(
            cache,
            counted.files,
            counted.counties,
            frame=frame,
            placement=placement,
            county_tally=counted.tally,
            county_left_out={f: d.years_left_out for f, d in counted.summary.items()},
            zone_releases=scope.zone_releases,
        )
    except (
        perschool.PerSchoolError,
        polygons.PolygonFileError,
        schoolcount.SchoolCountError,
        zonepolys.ZonePolygonError,
    ) as error:
        raise WeightsBuildError(str(error)) from error
    records, empty = perschool.county_summaries(
        per,
        placement,
        counted.counties,
        county_rule=counted.summary,
        county_rule_records=rule_records,
        whole_mean=whole_mean,
        county_rule_mean=rule_mean,
    )
    states = perschool.state_rows(per, placement, counted.summary, whole_mean, rule_mean)
    sanity = sanity_check(states)
    flags = surprises(states, records)
    checks = run_checks(cache, counted, scope.day_windows)
    changes, alert_types = code_changes(cache, counted.files)
    checks["code_changes"] = changes
    if counted.outline_report is not None:
        checks["zone_outlines"] = counted.outline_report.as_json()
    checks["years_counted"] = period_effects(counted, per_county)
    checks["schools"] = {
        "placed_by": dict(sorted(placement.by_method.items())),
        "unplaced": _strings(placement.unplaced),
        "fips_point_disagreements": placement.fips_point_disagreements,
        "address_state_elsewhere": [
            {"school": school, "address_state": address, "state": state}
            for school, address, state in placement.address_elsewhere
        ],
    }
    checks["zone_polygons"] = {
        **per.book.as_json(),
        "alternating_outlines": [item.as_json() for item in per.alternating],
    }
    checks["school_zones"] = perschool.placement_json(per)
    checks["school_counting"] = perschool.counting_json(per)
    checks["storm_polygons"] = perschool.polygon_files_json(per, counted.files)
    try:
        checks["school_recount"] = perschool.recount_check(
            per,
            counted.files,
            frame,
            placement,
            counted.counties,
            county_tally=counted.tally,
            county_left_out={f: d.years_left_out for f, d in counted.summary.items()},
        )
    except perschool.PerSchoolError as error:
        raise WeightsBuildError(str(error)) from error
    whole_weights = {
        fips: days.whole_county_days_per_year / whole_mean for fips, days in counted.summary.items()
    }
    tables = school_tables(placement, per.weights, whole_weights)
    priority_doc, references = station_priority(cache, paths, tables, scope)
    references["alert_types"] = _provenance(alert_types)
    result = Result(
        counties=records,
        states=states,
        mean_days=per.mean,
        whole_mean_days=whole_mean,
        schools=len(placement.schools),
        sanity=sanity,
        flags=flags,
        checks=checks,
        priority=priority_doc,
        generated_at=iso_utc(started),
        references=references,
        adopted=sorted(set(cache.adopted)),
        county_rule_mean=rule_mean,
        school_records=perschool.school_records(per, placement),
        counties_without_schools=empty,
        county_rule_records=rule_records,
        per_school=per,
    )
    result.paths = write_outputs(paths, result, counted)
    return result


def _zone_release_sources(result: Result) -> dict[str, JSONValue]:
    """The served zone releases and IEM's full-resolution answers read (provenance only)."""
    per = result.per_school
    if per is None:
        return {}
    return {
        "served": {zone_set.name: _provenance(zone_set.file) for zone_set in per.book.sets},
        "iem_full_resolution": [_provenance(file) for _, file in sorted(per.book.files.items())],
    }


def write_outputs(paths: Paths, result: Result, counted: Counted) -> dict[str, Path]:
    """Write every output file; return their paths by name."""
    out = paths.out_dir
    stamp = result.generated_at
    header: dict[str, JSONValue] = {
        "schema": SCHEMA,
        "generated_at": stamp,
        "school_years": [archive.school_year_label(year) for year in counted.tally.years],
    }
    closure: dict[str, JSONValue] = {
        **header,
        "codes": {
            code.code: {"name": code.name, "group": code.group, "weight": code.weight}
            for code in CODES
        },
        "normalizer": {
            "school_weighted_mean_days_per_year": result.mean_days,
            "schools": result.schools,
            "county_rule_school_weighted_mean_days_per_year": result.county_rule_mean,
            "whole_county_school_weighted_mean_days_per_year": result.whole_mean_days,
        },
        "counties": list(result.counties.values()),
        "counties_without_schools": _strings(result.counties_without_schools),
        "schools": dict(result.school_records),
    }
    state_doc: dict[str, JSONValue] = {
        **header,
        "normalizer": closure["normalizer"],
        "states": list(result.states),
        "sanity": result.sanity,
        "flags": list(result.flags),
    }
    priority_doc = {**header, **result.priority}
    manifest: dict[str, JSONValue] = {
        **header,
        "sources": {
            "school_years": {file.label: file.file.provenance.as_json() for file in counted.files},
            "zone_county_releases": {
                release.name: _provenance(release.file) for release in counted.releases
            },
            "county_release": _provenance(counted.counties.file),
            "zone_releases": _zone_release_sources(result),
            "storm_polygons": {
                item.label: item.file.provenance.as_json()
                for item in (result.per_school.polygon_files if result.per_school else [])
            },
            "adopted_from_other_caches": _strings(result.adopted),
            "references": dict(result.references),
            "directory": _local(paths.directory),
        },
        "checks": result.checks,
    }
    files = {
        "closure_weights": out / "closure-weights.json",
        "state_weights": out / "state-weights.json",
        "station_priority": out / "station-priority.json",
        "manifest": out / "manifest.json",
        "method": out / "method.md",
        "station_priority_md": out / "station-priority.md",
        "png": out / "closure-weights.png",
    }
    write_json(files["closure_weights"], closure)
    write_json(files["state_weights"], state_doc)
    write_json(files["station_priority"], priority_doc)
    write_json(files["manifest"], manifest)
    write_bytes_atomic(files["method"], notes.method_note(result, counted, stamp).encode("utf-8"))
    write_bytes_atomic(
        files["station_priority_md"], notes.priority_note(priority_doc).encode("utf-8")
    )
    weights = {fips: float(str(record["weight"])) for fips, record in result.counties.items()}
    title = "CLOSURE WEIGHT BY COUNTY (MEAN OF ITS SCHOOLS), 2015-16 TO 2025-26"
    write_bytes_atomic(files["png"], render.render_weights(counted.counties, weights, title))
    return files
