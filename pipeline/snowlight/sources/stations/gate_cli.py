"""The ``snowlight stations gate`` action: the coverage gate's report and capture plan.

* ``gate report``: read ``coverage.json`` (with its proven share), the school
  directory, the closure weights, the downloaded archive listings and the
  archive's reads, and write ``gate.json`` (see :mod:`snowlight.sources.stations.gate`);
* ``gate records``: write one record per source touching each state short of the
  target into ``docs/research/firsthand/gaps.json`` (replacing this piece's
  earlier records; see :func:`snowlight.sources.stations.gate.gap_records`), and
  the summary of those states into ``gaps.md``'s coverage gate section
  (:func:`snowlight.sources.stations.gate.gate_section`);
* ``gate text-check``: read every downloaded capture of each working source the
  coverage result leaves unproven as text, and say which show a closing their
  adapter's rows do not hold, or were refused by it (``archive/closure-text.jsonl``,
  see :mod:`snowlight.sources.stations.closure_text`); ``gate report`` reads it
  (and refuses one made against another coverage result), and a source with such a
  capture in its closure window is ``misread``, never settled; it also writes the
  audit (``archive/closure-audit.json``): the lines a wider net catches that the check
  did not count, by source, for review by eye;
* ``gate plan``: from ``gate.json``'s ranking, pick the unread captures most
  likely to prove the stations that would add the most closure weight, and print
  them as an archive request (``{"snapshots": [{"timestamp", "url", "station",
  "why"}, ...]}``; the workflow reads the first two fields, the others are notes).
  With ``--due``, pick instead every capture that keeps a source of a state short
  of the target open (:func:`snowlight.sources.stations.gate.plan_due`): its
  unread captures on its closure days, and the listings of addresses never
  listed (``"cdx"``); ``--pending`` names request files of runs not downloaded
  yet, whose captures are not asked for again.

And ``snowlight stations merge-live``: merge the reads and rows of several live
fetch runs into one folder for ``coverage --live-reads`` (a list seen populated by
an earlier fetch stays proven; see :mod:`snowlight.sources.stations.merge`).
"""

import argparse
import hashlib
import json
import sys
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path

import polars as pl

from snowlight.output import JSONValue
from snowlight.sources.nws.http import FetchError as ReferenceFetchError
from snowlight.sources.nws.http import HttpCache
from snowlight.sources.nws.http import make_client as make_reference_client
from snowlight.sources.stations import (
    closure_text,
    coverage,
    fetch,
    gate,
    merge,
    observed,
    proof,
    seasons,
)
from snowlight.sources.stations.archive import ArchiveError, url_key
from snowlight.sources.stations.http import system_clock
from snowlight.sources.stations.model import ListingRead
from snowlight.sources.stations.registry import (
    PIPELINE_ROOT,
    Registry,
    RegistryError,
    load_registry,
)
from snowlight.sources.stations.storms import StormDays
from snowlight.weights import archive as weights_archive
from snowlight.weights import count as weights_count
from snowlight.weights import schools as weights_schools
from snowlight.weights import zones as weights_zones
from snowlight.weights.archive import ArchiveCsvError
from snowlight.weights.build import WeightsBuildError, count_weather
from snowlight.weights.cache import WeightsCache
from snowlight.weights.schools import SchoolsError
from snowlight.weights.zones import ZoneCountyError

DEFAULT_ARTIFACTS = PIPELINE_ROOT / ".cache" / "stations" / "artifacts"
DEFAULT_DIRECTORY = PIPELINE_ROOT / "out" / "internal" / "directory" / "schools.parquet"
DEFAULT_WEIGHTS = PIPELINE_ROOT / "out" / "internal" / "weights" / "closure-weights.json"
DEFAULT_GROUPS = ("winter", "cold", "tropical")
COVERAGE_FILE = "coverage.json"
DEFAULT_TEXT_CHECK = fetch.DEFAULT_OUT_DIR / "archive" / closure_text.CHECK_FILE
DEFAULT_GAPS = PIPELINE_ROOT.parent / "docs" / "research" / "firsthand" / "gaps.json"
_FAILURES = (
    gate.GateError,
    closure_text.TextCheckError,
    RegistryError,
    ArchiveError,
    coverage.CoverageError,
    proof.ProofError,
    ReferenceFetchError,
    WeightsBuildError,
    ArchiveCsvError,
    ZoneCountyError,
    SchoolsError,
    OSError,
)


def register(actions: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Add ``gate report`` and ``gate plan`` to the ``stations`` actions."""
    gate_p = actions.add_parser("gate", help="the coverage gate: report and capture plan")
    gate_actions = gate_p.add_subparsers(dest="gate_action", metavar="<gate action>", required=True)

    report_p = gate_actions.add_parser("report", help="write gate.json: each state's gap")
    report_p.add_argument("--coverage", type=Path, default=fetch.DEFAULT_OUT_DIR / COVERAGE_FILE)
    report_p.add_argument("--directory", type=Path, default=DEFAULT_DIRECTORY)
    report_p.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS)
    report_p.add_argument("--no-weights", action="store_true", help="plain shares only")
    report_p.add_argument("--no-storms", action="store_true", help="count no storm days")
    report_p.add_argument("--artifacts", type=Path, default=DEFAULT_ARTIFACTS)
    report_p.add_argument(
        "--archive-reads", type=Path, default=fetch.DEFAULT_OUT_DIR / "archive" / "reads.jsonl"
    )
    report_p.add_argument(
        "--archive-health", type=Path, default=fetch.DEFAULT_OUT_DIR / "archive" / "health.json"
    )
    report_p.add_argument("--out-dir", type=Path, default=fetch.DEFAULT_OUT_DIR)
    report_p.add_argument(
        "--gaps",
        type=Path,
        default=DEFAULT_GAPS,
        help="the first-hand gap file, whose records of sources not built can keep a state open",
    )
    report_p.add_argument(
        "--closure-text",
        type=Path,
        default=DEFAULT_TEXT_CHECK,
        help="the closure-text check (gate text-check) of the same coverage result",
    )
    report_p.add_argument(
        "--no-text-check",
        action="store_true",
        help="build without the closure-text check (no source is then found misread)",
    )
    report_p.add_argument(
        "--groups",
        nargs="+",
        default=list(DEFAULT_GROUPS),
        help="hazard groups whose NWS days count as storm days",
    )
    report_p.set_defaults(handler=run_report)

    check_p = gate_actions.add_parser(
        "text-check", help="read the unproven sources' captures as text: what was misread"
    )
    check_p.add_argument("--coverage", type=Path, default=fetch.DEFAULT_OUT_DIR / COVERAGE_FILE)
    check_p.add_argument("--artifacts", type=Path, default=DEFAULT_ARTIFACTS)
    check_p.add_argument(
        "--archive-reads", type=Path, default=fetch.DEFAULT_OUT_DIR / "archive" / "reads.jsonl"
    )
    check_p.add_argument(
        "--archive-health", type=Path, default=fetch.DEFAULT_OUT_DIR / "archive" / "health.json"
    )
    check_p.add_argument("--out-dir", type=Path, default=fetch.DEFAULT_OUT_DIR / "archive")
    check_p.add_argument("--jobs", type=int, default=2, help="processes reading bodies")
    check_p.set_defaults(handler=run_text_check)

    records_p = gate_actions.add_parser(
        "records", help="write each short state's sources into the first-hand gap file"
    )
    records_p.add_argument("--report", type=Path, default=fetch.DEFAULT_OUT_DIR / gate.GATE_FILE)
    records_p.add_argument("--coverage", type=Path, default=fetch.DEFAULT_OUT_DIR / COVERAGE_FILE)
    records_p.add_argument("--gaps", type=Path, default=DEFAULT_GAPS)
    records_p.add_argument(
        "--gaps-md",
        type=Path,
        default=DEFAULT_GAPS.with_suffix(".md"),
        help="the gap file's Markdown, whose coverage gate section is rewritten",
    )
    records_p.set_defaults(handler=run_records)

    plan_p = gate_actions.add_parser("plan", help="pick captures to prove the top stations")
    plan_p.add_argument("--report", type=Path, default=fetch.DEFAULT_OUT_DIR / gate.GATE_FILE)
    plan_p.add_argument("--artifacts", type=Path, default=DEFAULT_ARTIFACTS)
    plan_p.add_argument(
        "--archive-reads", type=Path, default=fetch.DEFAULT_OUT_DIR / "archive" / "reads.jsonl"
    )
    plan_p.add_argument(
        "--archive-health", type=Path, default=fetch.DEFAULT_OUT_DIR / "archive" / "health.json"
    )
    plan_p.add_argument("--limit", type=int, default=250)
    plan_p.add_argument("--per-station", type=int, default=25)
    plan_p.add_argument("--min-weighted", type=float, default=5.0)
    plan_p.add_argument("--min-score", type=float, default=0.05)
    plan_p.add_argument(
        "--only",
        nargs="+",
        metavar="ID",
        help="plan only these sources (with --due, also those that keep no state open)",
    )
    plan_p.add_argument("--groups", nargs="+", default=list(DEFAULT_GROUPS))
    plan_p.add_argument("--no-storms", action="store_true", help="rank by size alone")
    plan_p.add_argument(
        "--due", action="store_true", help="every capture keeping a short state's source open"
    )
    plan_p.add_argument(
        "--coverage",
        type=Path,
        default=fetch.DEFAULT_OUT_DIR / COVERAGE_FILE,
        help="--due: the coverage result the report read (for the proven lists' days)",
    )
    plan_p.add_argument("--first", type=int, default=3, help="--due: captures per source first")
    plan_p.add_argument(
        "--pending",
        type=Path,
        nargs="+",
        default=[],
        help="--due: request files of runs not downloaded yet",
    )
    plan_p.set_defaults(handler=run_plan)


def register_merge(actions: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Add ``merge-live`` to the ``stations`` actions."""
    merge_p = actions.add_parser(
        "merge-live", help="merge several live fetches' reads and rows for coverage"
    )
    merge_p.add_argument(
        "reads", type=Path, nargs="+", help="reads.jsonl files (rows.jsonl beside each)"
    )
    merge_p.add_argument("--out-dir", type=Path, required=True)
    merge_p.add_argument(
        "--health",
        type=Path,
        nargs="+",
        default=[],
        help="health.json files to merge (each source's entry read last is kept)",
    )
    merge_p.set_defaults(handler=run_merge)


def run_merge(args: argparse.Namespace) -> int:
    """Run ``snowlight stations merge-live``."""
    try:
        runs = [merge.load_run(path) for path in args.reads]
        health = [merge.load_health(path) for path in args.health]
        merged = merge.merge_runs(runs)
        paths = merge.write_merged(args.out_dir, runs, merged, system_clock(), health)
    except (merge.MergeError, OSError) as error:
        print(f"merge-live: {error}", file=sys.stderr)  # noqa: T201 - the command's output
        return 1
    print(merge.summary(merged))  # noqa: T201 - the command's output
    for name, path in paths.items():
        print(f"{name}: {path}")  # noqa: T201 - the command's output
    return 0


def county_hazard_days(
    cache: HttpCache, groups: Iterable[str], today: date | None = None
) -> dict[str, dict[date, float]]:
    """Each county's NWS days over ``groups``: the weights build's cached school-year files
    and, as the closure seasons count them, the current school year's file so far
    (:func:`snowlight.sources.stations.seasons.current_years`), so a notice of this
    autumn's storm (Gulf's card of 2026-10-07, before the Hurricane Warning of 8-9
    October) can be corroborated."""
    weights_cache = WeightsCache(cache)
    counted = count_weather(weights_cache)
    tallies = [counted.tally]
    later = seasons.current_years(today or system_clock().date())
    if later:
        current = weights_archive.load_years(weights_cache, later)
        tallies.append(weights_count.count_years(current, counted.catalog, counted.counties))
    merged: dict[str, dict[str, dict[date, float]]] = {}
    for tally in tallies:
        for group, counties in gate.group_days(tally).items():
            into = merged.setdefault(group, {})
            for fips, days in counties.items():
                target = into.setdefault(fips, {})
                for day, weight in days.items():
                    target[day] = max(target.get(day, 0.0), weight)
    return gate.hazard_days(merged, groups)


def _storms(registry_dir: Path, groups: list[str], cache: HttpCache) -> StormDays:
    registry = load_registry(registry_dir)
    return StormDays.build(registry, county_hazard_days(cache, groups))


def _weights(path: Path, directory: Path, cache: HttpCache) -> coverage.Weights:
    weights = coverage.load_weights(path)
    counties = weights_zones.load_counties(WeightsCache(cache))
    placement = weights_schools.place_schools(weights_schools.read_schools(directory), counties)
    return weights.placed(placement)


def _census(
    artifacts: Path,
    reads: list[ListingRead],
    health: Path,
    checks: closure_text.Checked | None = None,
) -> gate.Census:
    return gate.census_from_files(
        artifacts, reads, proof.read_health(health) if health.is_file() else [], checks
    )


def _checks(path: Path, coverage_path: Path) -> closure_text.Checked:
    """The closure-text check, refused when it was made against another coverage result."""
    if not path.is_file():
        raise gate.GateError(
            f"{path}: no closure-text check; run `stations gate text-check` first "
            "(or pass --no-text-check)"
        )
    checks = closure_text.load_checks(path)
    sha = hashlib.sha256(coverage_path.read_bytes()).hexdigest()
    if checks.coverage_sha256 != sha:
        raise gate.GateError(
            f"{path} was made against another coverage result than {coverage_path} "
            "(run `stations gate text-check` again)"
        )
    return checks


def _gap_file(path: Path) -> list[dict[str, JSONValue]]:
    """The first-hand gap file's records (a list of JSON objects)."""
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise gate.GateError(f"{path}: not JSON ({error})") from error
    if not isinstance(existing, list):
        raise gate.GateError(f"{path}: not a list of records")
    return [item for item in existing if isinstance(item, dict)]


def _reads(path: Path) -> list[ListingRead]:
    return proof.read_reads(path) if path.is_file() else []


def _pending(paths: list[Path]) -> frozenset[tuple[str, str]]:
    """(Timestamp, URL key) of every capture the request files ask for."""
    found: set[tuple[str, str]] = set()
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data.get("snapshots") if isinstance(data, dict) else None
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict):
                found.add((str(item.get("timestamp")), url_key(str(item.get("url")))))
    return frozenset(found)


def run_report(args: argparse.Namespace) -> int:
    """Run ``snowlight stations gate report``."""
    try:
        registry = load_registry(args.registry)
        result = gate.load_result(args.coverage)
        wanted = ["index", "state", "county_fips", "district_id"]
        present = set(pl.scan_parquet(args.directory).collect_schema().names())
        schools = pl.read_parquet(args.directory, columns=[c for c in wanted if c in present])
        weights: coverage.Weights | None = None
        storms: StormDays | None = None
        if not (args.no_weights and args.no_storms):
            with HttpCache(make_reference_client()) as cache:
                if not args.no_weights:
                    weights = _weights(args.weights, args.directory, cache)
                if not args.no_storms:
                    storms = _storms(args.registry, list(args.groups), cache)
        reads = _reads(args.archive_reads)
        checks = None if args.no_text_check else _checks(args.closure_text, args.coverage)
        _, proven = gate.proven_and_working(result)
        report = gate.build_report(
            registry,
            result,
            gate.school_frame(schools, weights),
            _census(args.artifacts, reads, args.archive_health, checks),
            storms,
            coverage_file=gate.file_record(args.coverage, result),
            now=system_clock(),
            closure=gate.closure_days(registry, reads, proven),
            reads=reads,
            records=_gap_file(args.gaps),
        )
        path = gate.write_report(args.out_dir, report)
    except _FAILURES as error:
        print(f"gate report: {error}", file=sys.stderr)  # noqa: T201 - the command's output
        return 1
    national = report["national"]
    states = report["states"]
    if not isinstance(national, dict) or not isinstance(states, dict):  # pragma: no cover
        raise TypeError("the report is built with a national and a state table")
    short = [
        state
        for state, entry in sorted(states.items())
        if isinstance(entry, dict) and not entry.get("meets_target")
    ]
    owner = report.get("owner_gate")
    if isinstance(owner, dict):
        dig = owner.get("dig")
        shares = ", ".join(
            f"{line.get('state')} {_share_text(line)}"
            for line in (dig if isinstance(dig, list) else [])
            if isinstance(line, dict)
        )
        verdict = "passes" if owner.get("passes") is True else "does not pass"
        print(f"owner's gate ({owner.get('decided_on')}): {verdict}; {shares}")  # noqa: T201
    print(f"to the national target: {json.dumps(national['to_target'])}")  # noqa: T201
    print(f"states short of the target: {len(short)} ({', '.join(short)})")  # noqa: T201
    print(f"gate: {path}")  # noqa: T201
    return 0


def _share_text(line: dict[str, JSONValue]) -> str:
    """A state's proven shares, plain / weighted, as the command prints them."""
    proven = line.get("proven")
    if not isinstance(proven, dict):
        return "-"
    plain, weighted = proven.get("share"), proven.get("weighted_share")
    if not isinstance(plain, int | float) or not isinstance(weighted, int | float):
        return "-"
    accepted = line.get("accepted")
    note = f" ({accepted.get('note')})" if isinstance(accepted, dict) else ""
    return f"{gate.percent(plain)} / {gate.percent(weighted)}{note}"


def run_text_check(args: argparse.Namespace) -> int:
    """Run ``snowlight stations gate text-check``."""
    try:
        registry = load_registry(args.registry)
        result = gate.load_result(args.coverage)
        working, proven = gate.proven_and_working(result)
        wanted = frozenset(working - proven)
        files = closure_text.body_files(registry, args.artifacts, wanted)
        cache: dict[str, list[closure_text.Line]] = {}
        with ProcessPoolExecutor(max(1, args.jobs)) as pool:
            blocks = pool.map(closure_text.blocks_of_file, files.values(), chunksize=16)
            for sha, found in zip(files, blocks, strict=True):
                cache[sha] = found
        rows = observed.read_rows(args.archive_reads.with_name("rows.jsonl"))
        reads = closure_text.Reads.build(
            _reads(args.archive_reads),
            rows,
            proof.read_health(args.archive_health) if args.archive_health.is_file() else [],
        )
        checks = closure_text.check_captures(registry, args.artifacts, reads, wanted, cache=cache)
        record = gate.file_record(args.coverage, result)
        written = closure_text.write_checks(args.out_dir, checks, record)
        with ProcessPoolExecutor(max(1, args.jobs)) as pool:
            broad = dict(
                zip(
                    files,
                    pool.map(closure_text.broad_lines_of_file, files.values(), chunksize=16),
                    strict=True,
                )
            )
        audited = closure_text.audit(checks, broad, record)
        paths = (*written, closure_text.write_audit(args.out_dir, audited))
    except _FAILURES as error:
        print(f"gate text-check: {error}", file=sys.stderr)  # noqa: T201 - the command's output
        return 1
    totals = closure_text.summary(checks)
    print(f"captures checked: {totals['captures']} {json.dumps(totals['outcomes'])}")  # noqa: T201
    for path in paths:
        print(f"closure-text: {path}")  # noqa: T201 - the command's output
    return 0


def run_records(args: argparse.Namespace) -> int:
    """Run ``snowlight stations gate records``: merge this piece's records into the gap file."""
    try:
        registry = load_registry(args.registry)
        report = gate.load_result(args.report)
        result = gate.load_result(args.coverage)
        records = gate.gap_records(registry, report, result, checked_at=system_clock())
        merged = gate.merge_records(_gap_file(args.gaps), records, gate.rare_lines(report), result)
        args.gaps.write_text(json.dumps(merged, indent=1, ensure_ascii=False) + "\n", "utf-8")
        markdown = args.gaps_md.read_text(encoding="utf-8") if args.gaps_md.is_file() else ""
        args.gaps_md.write_text(
            gate.replace_section(markdown, gate.gate_section(report)), encoding="utf-8"
        )
    except (*_FAILURES, ValueError) as error:
        print(f"gate records: {error}", file=sys.stderr)  # noqa: T201 - the command's output
        return 1
    print(f"{len(records)} records for the states short of the target: {args.gaps}")  # noqa: T201
    return 0


def run_plan(args: argparse.Namespace) -> int:
    """Run ``snowlight stations gate plan``."""
    try:
        registry = load_registry(args.registry)
        report = gate.load_result(args.report)
        ranking = report.get("ranking")
        if not isinstance(ranking, list):
            raise gate.GateError(f"{args.report}: no ranking")
        reads = _reads(args.archive_reads)
        census = _census(args.artifacts, reads, args.archive_health)
        storms: StormDays | None = None
        if not args.no_storms:
            with HttpCache(make_reference_client()) as cache:
                storms = _storms(args.registry, list(args.groups), cache)
        if args.due:
            return _print_due(
                args, registry=registry, report=report, census=census, storms=storms, reads=reads
            )
        options = gate.PlanOptions(
            limit=args.limit,
            per_station=args.per_station,
            min_weighted=args.min_weighted,
            min_score=args.min_score,
            only=frozenset(args.only) if args.only else None,
        )
        plan = gate.plan_captures(
            registry,
            [item for item in ranking if isinstance(item, dict)],
            census,
            gate.downloaded_keys(args.artifacts),
            storms=storms,
            options=options,
        )
    except _FAILURES as error:
        print(f"gate plan: {error}", file=sys.stderr)  # noqa: T201 - the command's output
        return 1
    snapshots: list[JSONValue] = [item.as_json() for item in plan]
    print(json.dumps({"snapshots": snapshots}, indent=1))  # noqa: T201 - the command's output
    return 0


def _print_due(  # noqa: PLR0913 - the plan's inputs, read once by run_plan
    args: argparse.Namespace,
    *,
    registry: Registry,
    report: dict[str, JSONValue],
    census: gate.Census,
    storms: StormDays | None,
    reads: list[ListingRead],
) -> int:
    if storms is None:
        print("gate plan: --due needs the storm days", file=sys.stderr)  # noqa: T201
        return 1
    try:
        result = gate.load_result(args.coverage)
        _, proven = gate.proven_and_working(result)
        plan = gate.plan_due(
            registry,
            report,
            census,
            gate.downloaded_keys(args.artifacts),
            storms=storms,
            closure=gate.closure_days(registry, reads, proven),
            options=gate.DueOptions(
                limit=args.limit,
                first=args.first,
                only=frozenset(args.only) if args.only else None,
                skip=_pending(args.pending),
            ),
        )
    except _FAILURES as error:
        print(f"gate plan: {error}", file=sys.stderr)  # noqa: T201 - the command's output
        return 1
    print(json.dumps(plan.as_json(), indent=1))  # noqa: T201 - the command's output
    return 0
