"""The ``snowlight listed`` subcommand: rosters, build, audit."""

import argparse
import os
import sys
from pathlib import Path

from pydantic import ValidationError

from snowlight.listed import audit, rosters
from snowlight.listed.build import (
    DEFAULT_INPUTS,
    DEFAULT_OUT_DIR,
    DEFAULT_REGISTRY_DIR,
    DEFAULT_ROSTER_CACHE,
    DEFAULT_SNAPSHOT_DIR,
    PIPELINE_ROOT,
    BuildError,
    BuildPaths,
    BuildResult,
    build,
)
from snowlight.listed.evidence import EvidenceError
from snowlight.listed.measure import MeasureError
from snowlight.listed.snapshot import SnapshotError
from snowlight.sources.nws.http import HttpCache
from snowlight.sources.nws.http import make_client as make_reference_client
from snowlight.sources.stations.http import (
    USER_AGENT,
    ConditionalStore,
    FetchError,
    PoliteClient,
    make_client,
)
from snowlight.sources.stations.registry import RegistryError, load_registry
from snowlight.weights import zones as weights_zones
from snowlight.weights.cache import WeightsCache
from snowlight.weights.zones import CountyList

DEFAULT_HTTP_STORE = PIPELINE_ROOT / ".cache" / "listed" / "http"
DEFAULT_ROSTERS = DEFAULT_OUT_DIR / "rosters.json"
DEFAULT_WORKERS = max(1, min(3, (os.cpu_count() or 1) - 1))

_FAILURES = (
    BuildError,
    EvidenceError,
    FetchError,
    MeasureError,
    OSError,
    RegistryError,
    rosters.RosterFormatError,
    SnapshotError,
    ValidationError,
)


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register ``listed`` and its actions on ``subparsers``."""
    listed = subparsers.add_parser(
        "listed",
        help="per-school coverage: which schools appear on a real closings list",
        description=(
            "Measure which schools have appeared, by name or through their district, on "
            "a recorded closings list (SEEN), or on a list's published roster (ROSTER)."
        ),
    )
    actions = listed.add_subparsers(dest="listed_action", metavar="ACTION", required=True)

    fetch = actions.add_parser("rosters", help="read the published rosters (network)")
    fetch.add_argument("--out", type=Path, default=DEFAULT_ROSTERS, help="rosters.json to write")
    fetch.add_argument("--cache-dir", type=Path, default=DEFAULT_ROSTER_CACHE)
    fetch.add_argument("--http-store", type=Path, default=DEFAULT_HTTP_STORE)
    fetch.add_argument("--registry-dir", type=Path, default=DEFAULT_REGISTRY_DIR)
    fetch.add_argument(
        "--refresh",
        action="store_true",
        help="read the rosters again even when every kept body is intact",
    )
    fetch.set_defaults(handler=run_rosters)

    run = actions.add_parser("build", help="match every recorded row and roster, and measure")
    run.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    run.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR)
    run.add_argument("--roster-cache", type=Path, default=DEFAULT_ROSTER_CACHE)
    run.add_argument("--registry-dir", type=Path, default=DEFAULT_REGISTRY_DIR)
    run.add_argument(
        "--reuse-snapshot",
        action="store_true",
        help="measure the last snapshot again instead of copying the inputs anew",
    )
    run.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    run.add_argument(
        "--no-rosters", action="store_true", help="measure without rosters (ROSTER is empty)"
    )
    run.set_defaults(handler=run_build)

    sample = actions.add_parser("audit", help="draw the stratified sample of accepted matches")
    sample.add_argument("--matches", type=Path, default=DEFAULT_OUT_DIR / "matches.jsonl")
    sample.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR / "audit-sample.json")
    sample.add_argument("--size", type=int, default=audit.DEFAULT_SIZE)
    sample.add_argument("--seed", type=int, default=audit.DEFAULT_SEED)
    sample.set_defaults(handler=run_audit)


def _print(line: str) -> None:
    sys.stdout.write(line + "\n")


def _fail(step: str, error: Exception) -> int:
    sys.stderr.write(f"listed {step}: {error}\n")
    return 1


def run_rosters(args: argparse.Namespace) -> int:
    """Run ``snowlight listed rosters``."""
    try:
        if not args.refresh and args.out.is_file():
            kept = rosters.load_rosters(args.out)
            if kept and rosters.cached_reads_intact(kept, args.cache_dir):
                _print(f"rosters: {len(kept)} reads kept and intact; nothing read (use --refresh)")
                return 0
        registry = load_registry(args.registry_dir)
        client = PoliteClient(
            make_client(), ConditionalStore(args.http_store), host_interval=rosters.HOST_INTERVAL
        )
        try:
            reads = rosters.fetch_rosters(client, registry, args.cache_dir, progress=_print)
        finally:
            client.close()
        rosters.write_rosters(args.out, reads, USER_AGENT)
    except _FAILURES as error:
        return _fail("rosters", error)
    _print(f"rosters: {len(reads)} reads -> {args.out}")
    return 0


def nws_counties() -> CountyList:
    """The NWS county outlines the weights build uses (cached, checked by MD5)."""
    with HttpCache(make_reference_client()) as cache:
        return weights_zones.load_counties(WeightsCache(cache))


def run_build(args: argparse.Namespace) -> int:
    """Run ``snowlight listed build``."""
    paths = BuildPaths(
        out_dir=args.out_dir, snapshot_dir=args.snapshot_dir, roster_cache=args.roster_cache
    )
    try:
        result = build(
            paths,
            nws_counties,
            inputs=DEFAULT_INPUTS,
            registry_dir=args.registry_dir,
            reuse_snapshot=args.reuse_snapshot,
            workers=args.workers,
            require_rosters=not args.no_rosters,
        )
    except _FAILURES as error:
        return _fail("build", error)
    for line in summary_lines(result):
        _print(line)
    return 0


def summary_lines(result: BuildResult) -> list[str]:
    """The build's headline numbers, one per line."""
    national = result.national
    lines = [f"schools: {national.schools}"]
    for kind in ("seen", "roster", "listed"):
        count = national.counts[kind]
        share = count / national.schools if national.schools else 0.0
        weighted = national.sums[kind] / national.weighted if national.weighted else 0.0
        lines.append(f"{kind}: {count} ({share:.1%}; closure-weighted {weighted:.1%})")
    lines.append(
        f"unmatched K-12-looking names: {result.unmatched_names} ({result.unmatched_rows} rows)"
    )
    lines.extend(f"{name}: {path}" for name, path in result.paths.items())
    return lines


def run_audit(args: argparse.Namespace) -> int:
    """Run ``snowlight listed audit``."""
    try:
        drawn = audit.draw(audit.accepted_matches(args.matches), size=args.size, seed=args.seed)
        audit.write_sample(args.out, drawn, seed=args.seed)
    except (OSError, ValueError) as error:
        return _fail("audit", error)
    _print(f"audit: {len(drawn)} matches -> {args.out}")
    return 0
