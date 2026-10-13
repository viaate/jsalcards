"""The internal report of one replay day: what came in, what was dropped and why, and samples.

The report goes to ``out/internal/replays/<D>.report.internal.json``. It names
stations and holds raw list rows (in the audit samples), so it is internal only:
``out/`` is never committed and ``*.internal.json`` is never staged for the site.

The audit sample is drawn with a fixed seed, stratified by status, dated or
undated, direct or district, single or corroborated, and spread over markets,
with at least :data:`UNREAD_MIN` rows the reader noted ``unread_words`` (when the
day has that many). The dropped sample spreads over drop reasons.

Besides the drops by reason, the report counts what could hide a stale or
wrong state without being a drop of its own: conflicts within one list beside
those across stations (A3 counts only the latter), claims withdrawn because
another station's list withdrew the school, populated reads in the window whose
rows did not tie (each one voids what it may have dropped) and the archive-wide
rows ``load_rows`` could not tie, corroborations that rest on one listing name
(two stations, one matcher decision), and whether the storm falls after the
directory's school year (schools closed since then still have rows, and light
through their district's row: the report counts the schools lit through districts
only, the ones that risk names), and the alternative and special education schools
lit through districts only (the stratum facility programs fall in). It also names the
classes of wording and records the builder is known to read wrongly (:data:`KNOWN_LIMITS`).
"""

import random
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Final

from snowlight.listed.evidence import ListRow
from snowlight.output import JSONValue
from snowlight.replays.build import DayBuild, Lit, Reading, market_of
from snowlight.replays.gates import Drop, school_year_of
from snowlight.schemas.vocab import Status
from snowlight.sources.stations.registry import Registry

AUDIT_SIZE: Final = 60
UNREAD_MIN: Final = 10
DROPPED_SIZE: Final = 20
TOP_MARKETS: Final = 15
AUDIT_SEED: Final = 20240116


def report_path(out_dir: Path, day: date) -> Path:
    """Where a day's report is written."""
    return out_dir / f"{day.isoformat()}.report.internal.json"


def _raw(row: ListRow) -> dict[str, JSONValue]:
    return {"name": row.name, "status": row.status, "section": row.section}


def _sample_item(item: Lit, reading: Reading, registry: Registry) -> dict[str, JSONValue]:
    row = reading.row
    claim = reading.claim
    return {
        "nces_id": item.school,
        "status": item.status.name.lower(),
        "reason": None if item.reason is None else item.reason.name.lower(),
        "source_id": row.source_id,
        "fetched_at": row.fetched_at,
        "read_sha256": row.read_sha256,
        "raw": _raw(row),
        "dated": bool(claim and claim.dated),
        "level": reading.level,
        "corroborated": item.corroborated,
        "matched_apart": item.matched_apart,
        "stations": list(item.stations),
        "market": market_of(registry.stations[row.source_id]),
        "notes": list(claim.notes) if claim else [],
    }


def _spread[T](items: Sequence[T], key: Callable[[T], str], rng: random.Random) -> list[T]:
    """``items`` shuffled, then interleaved by ``key`` so no group comes all at once."""
    groups: dict[str, list[T]] = defaultdict(list)
    for item in items:
        groups[key(item)].append(item)
    order = sorted(groups)
    rng.shuffle(order)
    for name in order:
        rng.shuffle(groups[name])
    out: list[T] = []
    while any(groups[name] for name in order):
        for name in order:
            if groups[name]:
                out.append(groups[name].pop())
    return out


def _round_robin[T](strata: Mapping[tuple[str, ...], list[T]], size: int, taken: list[T]) -> None:
    keys = sorted(strata)
    while len(taken) < size and any(strata[key] for key in keys):
        for key in keys:
            if strata[key] and len(taken) < size:
                taken.append(strata[key].pop(0))


def audit_sample(
    lit: Mapping[str, Lit], registry: Registry, *, day: date, seed: int = AUDIT_SEED
) -> list[JSONValue]:
    """The stratified audit sample of :data:`AUDIT_SIZE` school-days (fewer when fewer lit)."""
    rng = random.Random(f"{day.isoformat()}:{seed}")  # noqa: S311 - a sample, not a secret
    pairs = [
        (item, min(item.evidence, key=lambda r: (r.row.source_id, r.row.fetched_at, r.row.name)))
        for _sid, item in sorted(lit.items())
    ]

    def market(pair: tuple[Lit, Reading]) -> str:
        return market_of(registry.stations[pair[1].row.source_id])

    unread = [pair for pair in pairs if pair[1].claim and "unread_words" in pair[1].claim.notes]
    taken: list[tuple[Lit, Reading]] = _spread(unread, market, rng)[:UNREAD_MIN]
    chosen = {pair[0].school for pair in taken}
    strata: dict[tuple[str, ...], list[tuple[Lit, Reading]]] = defaultdict(list)
    for pair in pairs:
        if pair[0].school in chosen:
            continue
        item, reading = pair
        key = (
            item.status.name,
            "dated" if reading.claim and reading.claim.dated else "undated",
            reading.level,
            "corroborated" if item.corroborated else "single",
        )
        strata[key].append(pair)
    spread = {key: _spread(items, market, rng) for key, items in strata.items()}
    _round_robin(spread, AUDIT_SIZE, taken)
    return [_sample_item(item, reading, registry) for item, reading in taken]


def dropped_sample(
    dropped: Iterable[tuple[ListRow, Drop]], *, day: date, seed: int = AUDIT_SEED
) -> list[JSONValue]:
    """:data:`DROPPED_SIZE` dropped rows spread over the drop reasons."""
    rng = random.Random(f"dropped:{day.isoformat()}:{seed}")  # noqa: S311 - a sample
    by_reason: dict[tuple[str, ...], list[tuple[ListRow, Drop]]] = defaultdict(list)
    for row, reason in dropped:
        by_reason[(reason.value,)].append((row, reason))
    for items in by_reason.values():
        rng.shuffle(items)
    taken: list[tuple[ListRow, Drop]] = []
    _round_robin(by_reason, DROPPED_SIZE, taken)
    return [
        {
            "drop": reason.value,
            "source_id": row.source_id,
            "fetched_at": row.fetched_at,
            "read_sha256": row.read_sha256,
            "raw": _raw(row),
        }
        for row, reason in taken
    ]


SPECIAL_TYPES: Final = frozenset({"Alternative School", "Special Education School"})
"""Directory school types the audit checks when they light only through a district's row: the
facility programs (:data:`snowlight.replays.build.FACILITY_NAME`) are among them."""
AFTER_DIRECTORY_RISK: Final = (
    "the storm is after the directory's school year: a school that closed since then still "
    "lights through its district's row; the audit checks the schools lit through districts only"
)


KNOWN_LIMITS: Final = (
    "retraction read as about another day when its day word is the time it was announced "
    "('Closing rescinded Monday evening', 'Closure cancelled per superintendent 1/15'): the "
    "reading casts no vote, so another list's claim for the day still lights",
    "retraction followed by a comma list of days sees only the first day "
    "('Closings cancelled for Jan 15, 16 and 17'): no vote, as above",
    "learning word in a clause that names another day for another reason "
    "('Closed - Snow packet day, buses resume Wednesday') is skipped, so the row lights closed",
    "weekday followed by bare day numbers ('Snow packet days Monday, 15th & 16th') is judged by "
    "the weekday alone",
    "learning words the gates do not know yet ('Self-directed learning day', 'Blended Learning "
    "Day', 'Home Instruction Day', 'Canvas Day', 'Chromebook Day', 'Schoology', 'Zoom', 'Google "
    "Meet') light closed when the reader reads them so",
    "district row narrowed by a school or level word the part words miss ('Closed - Westwood "
    "Intermediate', 'Closed - Hilltop and Valley schools', 'Closed - bus routes 4, 7 and 12 "
    "only') lights every school of the district",
    "non-weather words are read over the whole text, not the clause of the day ('Closed "
    "Tuesday. Planning day moved from Friday' drops; costs light only)",
    "a program typed Regular whose name and grades do not say so (a partial grade span with no "
    "students, an alternative or residential campus with a plain name) lights through its "
    "district's row; the audit checks the schools lit through districts only",
    "a public school matched by its state alone, or as the only school of a charter district, "
    "counts as anchored; the audit checks single-station matches",
)
"""Classes of wording and records the day builder is known to read wrongly, named so the audit
and the live reader can learn from them. None is lit on the candidate days measured when this list
was written (the facility programs are the exception the audit stratum covers)."""


def day_report(
    build: DayBuild,
    registry: Registry,
    *,
    seed: int = AUDIT_SEED,
    archive_drops: Mapping[str, int] | None = None,
) -> dict[str, JSONValue]:
    """The day's internal report (see the module docstring)."""
    settled = build.settled
    lit = settled.lit
    stations = sorted({station for item in lit.values() for station in item.stations})
    markets: Counter[str] = Counter()
    for item in lit.values():
        for name in sorted({market_of(registry.stations[s]) for s in item.stations}):
            markets[name] += 1
    by_status = Counter(item.status.name.lower() for item in lit.values())
    sources: list[JSONValue] = list(stations)
    market_names: list[JSONValue] = [*sorted({market_of(registry.stations[s]) for s in stations})]
    top = sorted(markets.items(), key=lambda pair: (-pair[1], pair[0]))[:TOP_MARKETS]
    after = school_year_of(build.day) > build.public_year
    district_only = sorted(
        sid
        for sid, item in lit.items()
        if all(reading.level == "district" for reading in item.evidence)
    )
    special: list[JSONValue] = [
        sid for sid in district_only if lit[sid].school_type in SPECIAL_TYPES
    ]
    return {
        "day": build.day.isoformat(),
        "passed": build.passed,
        "failures": list(build.failures),
        "seed": build.seed.as_json(),
        "rows_in": settled.rows_in,
        "drops": {
            "rows": dict(settled.row_drops),
            "targets": dict(settled.target_drops),
            "schools": dict(settled.school_drops),
            "notes": dict(settled.note_drops),
        },
        "sources": sources,
        "markets": market_names,
        "lit": {
            "total": len(lit),
            "by_status": {status.name.lower(): by_status[status.name.lower()] for status in Status},
        },
        "corroborated": sum(1 for item in lit.values() if item.corroborated),
        "corroborated_matched_apart": sum(1 for item in lit.values() if item.matched_apart),
        "conflicts": len(settled.conflicts),
        "conflicts_in_list": settled.school_drops.get(Drop.CONFLICT_IN_LIST.value, 0),
        "withdrawn": settled.school_drops.get(Drop.WITHDRAWN.value, 0),
        "untied": {
            "reads": len(settled.untied),
            "rows": sum(rows for _source, _at, rows in settled.untied),
            "voids": settled.untied_voids,
            "archive_rows_by_reason": dict(sorted((archive_drops or {}).items())),
        },
        "school_year": {
            "storm": school_year_of(build.day),
            "directory_public": build.public_year,
            "after_directory": after,
            "lit_through_districts_only": len(district_only),
            "risk": AFTER_DIRECTORY_RISK if after else None,
        },
        "special_through_districts_only": special,
        "known_limits": list(KNOWN_LIMITS),
        "control": {
            "target": build.control.target.isoformat(),
            "lit": build.control.lit,
            "entries": build.control.entries,
            "passed": build.control.passed,
        },
        "reads": [
            {
                "source_id": check.source_id,
                "fetched_at": check.fetched_at,
                "variant": check.variant,
                "sha256": check.sha256,
                "rows": check.rows,
                "unread_share": check.unread_share,
                "match_share": check.match_share,
                "station_median": check.station_median,
                "drop": None if check.drop is None else check.drop.value,
            }
            for check in settled.reads
        ],
        "top_markets": [{"market": name, "schools": count} for name, count in top],
        "audit": audit_sample(lit, registry, day=build.day, seed=seed),
        "dropped_sample": dropped_sample(settled.dropped, day=build.day, seed=seed),
    }
