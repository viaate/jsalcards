"""``snowlight listed build``: match every recorded row and roster entry, and measure.

The steps, all on one snapshot of the inputs (:mod:`snowlight.listed.snapshot`):

1. load the registry, the rows of every recorded read (live and archived,
   :mod:`snowlight.listed.evidence`) and the roster entries
   (:mod:`snowlight.listed.rosters`);
2. match each distinct listing once with the committed matcher, in its list's
   registry context (:mod:`snowlight.listed.matching`, :mod:`snowlight.listed.scope`);
3. take away the matches a row's own list places elsewhere (:func:`guard`,
   :mod:`snowlight.listed.located`);
4. gather each school's evidence and count SEEN, ROSTER and LISTED, plain and
   closure-weighted (:mod:`snowlight.listed.measure`);
5. write the outputs described in :mod:`snowlight.listed`.

The same snapshot always gives the same bytes: ``generated_at`` is the newest
retrieval time among the evidence, not the clock, and every file is written
sorted.
"""

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Final

import polars as pl

from snowlight.listed.evidence import ListRow, LoadedRows, load_rows
from snowlight.listed.located import Gazetteer, Places, Verdict
from snowlight.listed.matching import MatcherSpec, Outcome, Query, match_all
from snowlight.listed.measure import (
    Tally,
    aggregate,
    load_closure_weights,
    school_table,
    school_weights,
    tally,
)
from snowlight.listed.rosters import (
    RosterEntry,
    RosterFormatError,
    cached_reads_intact,
    load_rosters,
    read_entries,
)
from snowlight.listed.scope import excluded_reason, station_context
from snowlight.listed.snapshot import Snapshot, load_snapshot, take_snapshot
from snowlight.match import Matcher, MatchSettings
from snowlight.output import JSONValue, dumps_json, write_bytes_atomic, write_json
from snowlight.sources.stations.registry import Registry, load_registry
from snowlight.weights.schools import Placement, place_schools, read_schools
from snowlight.weights.zones import CountyList

PIPELINE_ROOT: Final = Path(__file__).resolve().parents[2]
INTERNAL: Final = PIPELINE_ROOT / "out" / "internal"
DEFAULT_OUT_DIR: Final = INTERNAL / "listed"
DEFAULT_SNAPSHOT_DIR: Final = DEFAULT_OUT_DIR / "snapshot"
DEFAULT_ROSTER_CACHE: Final = PIPELINE_ROOT / ".cache" / "listed" / "rosters"
DEFAULT_REGISTRY_DIR: Final = PIPELINE_ROOT / "config" / "sources"
DEFAULT_INPUTS: Final[Mapping[str, Path]] = {
    "live_reads": INTERNAL / "stations" / "reads.jsonl",
    "live_rows": INTERNAL / "stations" / "rows.jsonl",
    "archive_reads": INTERNAL / "stations" / "archive" / "reads.jsonl",
    "archive_rows": INTERNAL / "stations" / "archive" / "rows.jsonl",
    "coverage": INTERNAL / "stations" / "coverage.json",
    "aliases": PIPELINE_ROOT / "config" / "aliases.yaml",
    "districts": INTERNAL / "directory" / "districts.parquet",
    "schools": INTERNAL / "directory" / "schools.parquet",
    "weights": INTERNAL / "weights" / "closure-weights.json",
    "rosters": DEFAULT_OUT_DIR / "rosters.json",
}
MATCHER_DIR: Final = Path(__file__).resolve().parents[1] / "match"
NOT_A_SCHOOL: Final = frozenset({"not_k12", "not_school", "empty"})
"""Matcher reasons that say a listing names no K-12 school at all."""
SCHOOL_LEVELS: Final = frozenset({"district", "school"})
"""Listing levels that say the words name a school or a district."""
TOP_UNMATCHED: Final = 50
GAP_STATES: Final = 10

type CountyLoader = Callable[[], CountyList]
"""Reads the NWS county outlines (the pinned release the weights build uses)."""
GUARD_REASON: Final = "place_conflict"
"""The reason a match the row's own places contradict is given (see :func:`guard`)."""


class BuildError(ValueError):
    """The inputs do not check out."""


@dataclass(frozen=True, slots=True)
class BuildPaths:
    """Where the build reads and writes."""

    out_dir: Path = DEFAULT_OUT_DIR
    snapshot_dir: Path = DEFAULT_SNAPSHOT_DIR
    roster_cache: Path = DEFAULT_ROSTER_CACHE


@dataclass(frozen=True, slots=True)
class BuildResult:
    """What a build wrote, and its headline numbers."""

    paths: Mapping[str, Path]
    national: Tally
    states: Mapping[str, Tally]
    unmatched_names: int
    unmatched_rows: int
    listed: Mapping[str, JSONValue]


@dataclass(frozen=True, slots=True)
class Loaded:
    """Every input of the measure, read from one snapshot."""

    snapshot: Snapshot
    registry: Registry
    rows: tuple[ListRow, ...]
    row_stats: dict[str, JSONValue]
    excluded: dict[str, str]
    entries: tuple[RosterEntry, ...]
    roster_reads: int
    generated_at: str


def matcher_fingerprint(folder: Path = MATCHER_DIR) -> str:
    """A SHA-256 over the matcher's source files, naming the matcher a build used."""
    digest = hashlib.sha256()
    for path in sorted(folder.glob("*.py")):
        digest.update(path.name.encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii") + b"\n")
    return digest.hexdigest()


def county_names(schools_path: Path) -> dict[tuple[str, str], str]:
    """``(state, county name)`` to county FIPS, from the directory (``"Albany County"`` as
    ``"albany"``), for the names that stand for exactly one county."""
    frame = pl.read_parquet(schools_path, columns=["state", "county_fips", "county_name"]).unique()
    codes: dict[tuple[str, str], set[str]] = defaultdict(set)
    for state, fips, name in frame.iter_rows():
        if state and fips and name:
            key = (str(state), str(name).removesuffix(" County").strip().casefold())
            codes[key].add(str(fips))
    return {key: next(iter(found)) for key, found in codes.items() if len(found) == 1}


def load_inputs(snapshot: Snapshot, roster_cache: Path, *, require_rosters: bool) -> Loaded:
    """Read the registry, rows and roster entries of a snapshot.

    Raises:
        BuildError: the rosters are required but missing or not intact.
    """
    registry = load_registry(snapshot.registry_dir)
    loaded: list[LoadedRows] = [
        load_rows(snapshot.path(f"{mode}_reads"), snapshot.path(f"{mode}_rows"))
        for mode in ("live", "archive")
    ]
    dropped: Counter[str] = Counter()
    attributed = 0
    kept: list[ListRow] = []
    excluded: dict[str, str] = {}
    excluded_rows: Counter[str] = Counter()
    unknown: Counter[str] = Counter()
    for part in loaded:
        dropped.update(part.dropped)
        attributed += len(part.rows)
        for row in part.rows:
            station = registry.stations.get(row.source_id)
            if station is None:
                unknown[row.source_id] += 1
                continue
            reason = excluded_reason(station)
            if reason is not None:
                excluded[station.id] = reason
                excluded_rows[station.id] += 1
                continue
            kept.append(row)
    newest = [read.retrieved_at for part in loaded for read in part.reads]
    entries: list[RosterEntry] = []
    roster_reads = 0
    if snapshot.has("rosters"):
        reads = load_rosters(snapshot.path("rosters"))
        if not cached_reads_intact(reads, roster_cache):
            raise BuildError(f"the bodies {snapshot.path('rosters')} names are not all kept")
        places = county_names(snapshot.path("schools"))
        try:
            entries = read_entries(reads, roster_cache, registry, places)
        except RosterFormatError as error:
            raise BuildError(f"rosters: {error}") from error
        roster_reads = len(reads)
        newest.extend(read.fetched_at for read in reads)
    elif require_rosters:
        raise BuildError("no rosters.json: run `snowlight listed rosters` first")
    stats: dict[str, JSONValue] = {
        "in_files": attributed + sum(dropped.values()),
        "tied_to_a_read": attributed,
        "left_out": dict(sorted(dropped.items())),
        "from_excluded_sources": sum(excluded_rows.values()),
        "from_unregistered_sources": sum(unknown.values()),
        "counted": len(kept),
    }
    return Loaded(
        snapshot=snapshot,
        registry=registry,
        rows=tuple(kept),
        row_stats=stats,
        excluded=dict(sorted(excluded.items())),
        entries=tuple(entries),
        roster_reads=roster_reads,
        generated_at=max(newest) if newest else "",
    )


def row_query(row: ListRow, registry: Registry) -> Query:
    """The listing a row asks the matcher about."""
    return Query(station_context(registry.stations[row.source_id]), row.name, row.section)


def entry_query(entry: RosterEntry) -> Query:
    """The listing a roster entry asks the matcher about."""
    return Query(entry.context, entry.name, entry.category)


def guard(
    gazetteer: Gazetteer,
    pairs: Sequence[tuple[Query, Places]],
    outcomes: Mapping[Query, Outcome],
) -> dict[Query, Outcome]:
    """Take away the matches that a row's own places contradict.

    ``pairs`` are each row's (or roster entry's) listing and the places it names.
    A listing is one organization, so when any of its rows places it where none of
    the matched records is (:meth:`Gazetteer.verdict`), the listing's match is not
    accepted: its outcome becomes :data:`GUARD_REASON`, keeping the records the
    matcher named for the record. Returns the changed outcomes only.
    """
    changed: dict[Query, Outcome] = {}
    for query, places in pairs:
        outcome = outcomes[query]
        if not outcome.accepted or not places or query in changed:
            continue
        verdict = gazetteer.verdict(places, outcome.targets, query.context.states)
        if verdict is Verdict.CONFLICT:
            where = "; ".join(
                ", ".join(p for p in (place.city, place.county, place.state) if p)
                for place in places
            )
            changed[query] = replace(
                outcome,
                accepted=False,
                reason=GUARD_REASON,
                direct=(),
                via_district=(),
                detail=f"{outcome.detail}; the list places it at {where}, not by the record",
            )
    return changed


def build(  # noqa: PLR0913 - where to read and write, and how
    paths: BuildPaths,
    county_loader: CountyLoader,
    *,
    inputs: Mapping[str, Path] | None = None,
    registry_dir: Path = DEFAULT_REGISTRY_DIR,
    reuse_snapshot: bool = False,
    workers: int = 1,
    require_rosters: bool = True,
) -> BuildResult:
    """Snapshot the inputs (or reuse the last snapshot), match, measure and write.

    Raises:
        BuildError: an input does not check out.
        SnapshotError: the snapshot cannot be taken or does not verify.
    """
    if reuse_snapshot:
        snapshot = load_snapshot(paths.snapshot_dir)
    else:
        wanted = dict(DEFAULT_INPUTS if inputs is None else inputs)
        if "rosters" in wanted and not wanted["rosters"].is_file() and not require_rosters:
            del wanted["rosters"]
        snapshot = take_snapshot(wanted, registry_dir, paths.snapshot_dir, base=PIPELINE_ROOT)
    loaded = load_inputs(snapshot, paths.roster_cache, require_rosters=require_rosters)
    spec = MatcherSpec(snapshot.root / "directory", snapshot.path("aliases"))
    matcher = spec.build()
    row_queries = [row_query(row, loaded.registry) for row in loaded.rows]
    entry_queries = [entry_query(entry) for entry in loaded.entries]
    outcomes = match_all(matcher, [*row_queries, *entry_queries], workers=workers, spec=spec)
    county_list = county_loader()
    schools_frame = pl.read_parquet(snapshot.path("schools"))
    gazetteer = Gazetteer.build(
        schools_frame, pl.read_parquet(snapshot.path("districts")), county_list
    )
    stated = [(q, row.places) for q, row in zip(row_queries, loaded.rows, strict=True)]
    stated += [(q, e.places) for q, e in zip(entry_queries, loaded.entries, strict=True)]
    guarded = guard(gazetteer, stated, outcomes)
    outcomes = {**outcomes, **guarded}
    row_pairs = [(row, outcomes[q]) for row, q in zip(loaded.rows, row_queries, strict=True)]
    entry_pairs = [(e, outcomes[q]) for e, q in zip(loaded.entries, entry_queries, strict=True)]
    evidence = aggregate(row_pairs, entry_pairs)
    schools = [(str(i), str(s)) for i, s in schools_frame.select("id", "state").iter_rows()]
    table = school_table(schools, evidence)
    weights = load_closure_weights(snapshot.path("weights"))
    placement = place_schools(read_schools(snapshot.path("schools")), county_list)
    counties_file: dict[str, JSONValue] = {}
    if county_list.file is not None:
        record = county_list.file.provenance
        counties_file = {"url": record.url, "sha256": record.sha256, "bytes": record.size}
    national, states = tally(table, school_weights(weights, placement))
    listed = _listed_json(
        loaded,
        (national, states),
        (row_pairs, entry_pairs),
        matcher,
        (placement, counties_file),
    )
    unmatched = _unmatched_json(loaded, row_pairs, entry_pairs)
    out = paths.out_dir
    written = {
        "listed": out / "listed.json",
        "schools": out / "schools.parquet",
        "unmatched": out / "unmatched.json",
        "matches": out / "matches.jsonl",
    }
    write_json(written["listed"], listed)
    _write_parquet(written["schools"], table)
    write_json(written["unmatched"], unmatched)
    write_bytes_atomic(written["matches"], _matches_jsonl(row_pairs, entry_pairs, matcher))
    national_unmatched = unmatched["national"]
    assert isinstance(national_unmatched, dict)  # noqa: S101 - built just above
    return BuildResult(
        paths=written,
        national=national,
        states=states,
        unmatched_names=int(str(national_unmatched["names"])),
        unmatched_rows=int(str(national_unmatched["rows"])),
        listed=listed,
    )


def _write_parquet(path: Path, table: pl.DataFrame) -> None:
    staging = path.with_name(f".{path.name}.tmp")
    table.write_parquet(staging, compression="zstd", statistics=False)
    write_bytes_atomic(path, staging.read_bytes())
    staging.unlink()


# listed.json ---------------------------------------------------------------------------


def _coverage_share(item: object) -> dict[str, JSONValue] | None:
    if not isinstance(item, dict):
        return None
    weighted = item.get("weighted")
    return {
        "share": item.get("share"),
        "weighted_share": weighted.get("share") if isinstance(weighted, dict) else None,
    }


def _object(value: object) -> dict[str, object]:
    return {str(key): item for key, item in value.items()} if isinstance(value, dict) else {}


def _coverage(snapshot: Snapshot) -> dict[str, JSONValue]:
    """The area and proven shares of ``coverage.json``, for comparison."""
    data = json.loads(snapshot.path("coverage").read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise BuildError("coverage.json is not a JSON object")
    proven = _object(data.get("proven"))
    area_states = _object(data.get("states"))
    proven_states = _object(proven.get("states"))
    return {
        "generated_at": data.get("generated_at"),
        "national": {
            "area": _coverage_share(data.get("national")),
            "proven": _coverage_share(proven.get("national")),
        },
        "states": {
            state: {
                "area": _coverage_share(area_states.get(state)),
                "proven": _coverage_share(proven_states.get(state)),
            }
            for state in sorted(set(area_states) | set(proven_states))
        },
    }


def _gaps(coverage: Mapping[str, JSONValue], states: Mapping[str, Tally]) -> list[JSONValue]:
    """The states whose listed share falls furthest below their area share."""
    by_state = coverage.get("states")
    rows: list[tuple[float, str, float, float]] = []
    for state, counted in states.items():
        entry = by_state.get(state) if isinstance(by_state, dict) else None
        area = entry.get("area") if isinstance(entry, dict) else None
        share = area.get("share") if isinstance(area, dict) else None
        if not isinstance(share, int | float):
            continue
        listed = counted.counts["listed"] / counted.schools if counted.schools else 0.0
        rows.append((round(float(share) - listed, 4), state, float(share), round(listed, 4)))
    rows.sort(key=lambda item: (-item[0], item[1]))
    return [
        {"state": state, "area_share": area, "listed_share": listed, "gap": gap}
        for gap, state, area, listed in rows[:GAP_STATES]
    ]


def _stations(
    rows: Sequence[tuple[ListRow, Outcome]], entries: Sequence[tuple[RosterEntry, Outcome]]
) -> dict[str, JSONValue]:
    counted: dict[str, Counter[str]] = defaultdict(Counter)
    reached: dict[str, set[str]] = defaultdict(set)
    dates: dict[str, list[str]] = defaultdict(list)
    for row, outcome in rows:
        tally_ = counted[row.source_id]
        tally_["rows"] += 1
        tally_["accepted_rows" if outcome.accepted else "other_rows"] += 1
        reached[row.source_id].update(outcome.direct, outcome.via_district)
        dates[row.source_id].append(row.fetched_at)
    for entry, outcome in entries:
        tally_ = counted[entry.roster]
        tally_["entries"] += 1
        tally_["accepted_entries" if outcome.accepted else "other_entries"] += 1
        reached[entry.roster].update(outcome.direct, outcome.via_district)
    out: dict[str, JSONValue] = {}
    for key in sorted(counted):
        item: dict[str, JSONValue] = dict(sorted(counted[key].items()))
        item["schools"] = len(reached[key])
        if dates.get(key):
            item["first_capture"] = min(dates[key])
            item["last_capture"] = max(dates[key])
        out[key] = item
    return out


def _outcome_counts(pairs: Iterable[tuple[object, Outcome]]) -> dict[str, JSONValue]:
    reasons: Counter[str] = Counter(outcome.reason for _item, outcome in pairs)
    return dict(sorted(reasons.items()))


def _listed_json(
    loaded: Loaded,
    counted: tuple[Tally, Mapping[str, Tally]],
    pairs: tuple[Sequence[tuple[ListRow, Outcome]], Sequence[tuple[RosterEntry, Outcome]]],
    matcher: Matcher,
    placed: tuple[Placement, dict[str, JSONValue]],
) -> dict[str, JSONValue]:
    national, states = counted
    rows, entries = pairs
    placement, counties_file = placed
    snapshot = loaded.snapshot
    coverage = _coverage(snapshot)
    settings: MatchSettings = matcher.settings
    evidence: dict[str, JSONValue] = {
        name: item.to_json(snapshot.root) for name, item in sorted(snapshot.files.items())
    }
    evidence["nws_counties"] = counties_file
    return {
        "generated_at": loaded.generated_at,
        "definitions": {
            "seen": (
                "an accepted match of the name matcher ties a row of a recorded read "
                "(live or archived) to the school, or to its district (every school of "
                "the district counts); a match the row's own list places elsewhere "
                "(another state, or a town or county out of reach) does not count"
            ),
            "roster": (
                "an organization on a list's published roster matches the school or its district"
            ),
            "listed": "seen or roster",
        },
        "evidence": evidence,
        "matcher": {
            "sources_sha256": matcher_fingerprint(),
            "threshold": settings.threshold,
            "aliases": len(matcher.aliases),
        },
        "placement": {
            "schools_placed": len(placement.schools),
            "unplaced": len(placement.unplaced),
        },
        "rows": loaded.row_stats,
        "row_outcomes": _outcome_counts(rows),
        "place_guard": {
            "listings": len(
                {(r.source_id, r.name, r.section) for r, o in rows if o.reason == GUARD_REASON}
            ),
            "rows": sum(1 for _r, o in rows if o.reason == GUARD_REASON),
        },
        "roster_reads": loaded.roster_reads,
        "roster_entries": len(entries),
        "roster_outcomes": _outcome_counts(entries),
        "excluded_sources": dict(loaded.excluded),
        "national": national.to_json(),
        "states": {state: counted.to_json() for state, counted in states.items()},
        "coverage": coverage,
        "gaps": _gaps(coverage, states),
        "stations": _stations(rows, entries),
    }


# unmatched.json -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, order=True)
class _Miss:
    source: str
    name: str
    section: str
    reason: str
    level: str
    best_id: str
    best_name: str
    best_score: float


def looks_k12(outcome: Outcome) -> bool:
    """True for a listing not accepted whose words, by the matcher's reading, name a
    school or a district (and that the matcher does not call something else)."""
    return (
        not outcome.accepted
        and outcome.reason not in NOT_A_SCHOOL
        and outcome.level in SCHOOL_LEVELS
    )


def _miss(source: str, name: str, section: str | None, outcome: Outcome) -> _Miss:
    return _Miss(
        source=source,
        name=name,
        section=section or "",
        reason=outcome.reason,
        level=outcome.level,
        best_id=outcome.best_id or "",
        best_name=outcome.best_name or "",
        best_score=outcome.best_score if outcome.best_score is not None else 0.0,
    )


def _miss_json(miss: _Miss, count: int, *, key: str) -> dict[str, JSONValue]:
    return {
        key: miss.source,
        "name": miss.name,
        "section": miss.section or None,
        "reason": miss.reason,
        "kind": "queued" if miss.best_id else "unmatched",
        "level": miss.level,
        "count": count,
        "best": (
            {"id": miss.best_id, "name": miss.best_name, "score": miss.best_score}
            if miss.best_id
            else None
        ),
    }


def _grouped(misses: Counter[_Miss], key: str) -> dict[str, JSONValue]:
    by_source: dict[str, list[tuple[_Miss, int]]] = defaultdict(list)
    for miss, count in misses.items():
        by_source[miss.source].append((miss, count))
    out: dict[str, JSONValue] = {}
    for source in sorted(by_source):
        items = sorted(by_source[source], key=lambda pair: (-pair[1], pair[0]))
        out[source] = {
            "names": len(items),
            "count": sum(count for _miss_item, count in items),
            "entries": [_miss_json(miss, count, key=key) for miss, count in items],
        }
    return out


def _unmatched_json(
    loaded: Loaded,
    rows: Sequence[tuple[ListRow, Outcome]],
    entries: Sequence[tuple[RosterEntry, Outcome]],
) -> dict[str, JSONValue]:
    row_misses: Counter[_Miss] = Counter(
        _miss(row.source_id, row.name, row.section, outcome)
        for row, outcome in rows
        if looks_k12(outcome)
    )
    entry_misses: Counter[_Miss] = Counter(
        _miss(entry.roster, entry.name, entry.category, outcome)
        for entry, outcome in entries
        if looks_k12(outcome)
    )
    ranked = sorted(row_misses.items(), key=lambda pair: (-pair[1], pair[0]))
    queued = [(m, c) for m, c in row_misses.items() if m.best_id]
    return {
        "generated_at": loaded.generated_at,
        "national": {
            "names": len(row_misses),
            "rows": sum(row_misses.values()),
            "queued_names": len(queued),
            "queued_rows": sum(c for _m, c in queued),
            "unmatched_names": len(row_misses) - len(queued),
            "unmatched_rows": sum(row_misses.values()) - sum(c for _m, c in queued),
            "roster_names": len(entry_misses),
        },
        "top": [_miss_json(miss, count, key="source_id") for miss, count in ranked[:TOP_UNMATCHED]],
        "stations": _grouped(row_misses, "source_id"),
        "rosters": _grouped(entry_misses, "roster"),
    }


# matches.jsonl --------------------------------------------------------------------------


@dataclass(slots=True)
class _Listing:
    """One distinct listing's rows (or roster entries), while they are gathered."""

    outcome: Outcome
    kind: str
    status: str
    rows: int = 0
    reads: set[str] = field(default_factory=set)
    first: str = ""
    last: str = ""

    def add(self, fetched_at: str, sha256: str) -> None:
        self.rows += 1
        self.reads.add(sha256)
        self.first = min(self.first, fetched_at) if self.first else fetched_at
        self.last = max(self.last, fetched_at)


def _matches_jsonl(
    rows: Sequence[tuple[ListRow, Outcome]],
    entries: Sequence[tuple[RosterEntry, Outcome]],
    matcher: Matcher,
) -> bytes:
    """Every distinct listing with its outcome, rows and captures: the audit's input."""
    grouped: dict[tuple[str, str, str], _Listing] = {}
    for row, outcome in rows:
        key = (row.source_id, row.name, row.section or "")
        grouped.setdefault(key, _Listing(outcome, "row", row.status)).add(
            row.fetched_at, row.read_sha256
        )
    for entry, outcome in entries:
        key = (entry.roster, entry.name, entry.category or "")
        grouped.setdefault(key, _Listing(outcome, "roster", "")).add(
            entry.fetched_at, entry.read_sha256
        )
    lines: list[bytes] = []
    for (source, name, section), item in sorted(grouped.items()):
        outcome = item.outcome
        targets: list[JSONValue] = []
        for record_id in outcome.targets:
            record = matcher.directory[record_id]
            targets.append(
                {
                    "id": record.id,
                    "name": record.name,
                    "kind": record.kind,
                    "state": record.state,
                    "city": record.city,
                    "county_fips": record.county_fips,
                }
            )
        line: dict[str, JSONValue] = {
            "source_id": source,
            "kind": item.kind,
            "name": name,
            "section": section or None,
            "accepted": outcome.accepted,
            "reason": outcome.reason,
            "level": outcome.level,
            "confidence": outcome.confidence,
            "targets": targets,
            "schools_direct": len(outcome.direct),
            "schools_via_district": len(outcome.via_district),
            "rows": item.rows,
            "first": item.first,
            "last": item.last,
            "reads": list[JSONValue](sorted(item.reads)),
            "status_example": item.status[:200],
            "best": (
                {"id": outcome.best_id, "name": outcome.best_name, "score": outcome.best_score}
                if outcome.best_id is not None
                else None
            ),
            "detail": outcome.detail,
        }
        lines.append(dumps_json(line) + b"\n")
    return b"".join(lines)
