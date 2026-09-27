"""The ``python -m snowlight.weights`` command.

Actions:

* ``build``: count closure-type school days for every school in its own forecast
  zone (and, for comparison, per county by the county rule) from the IEM archive,
  write the closure weights, the state weights, the station priority, the method
  note and the map into ``pipeline/out/internal/weights/`` (see
  :mod:`snowlight.weights.build`). Cached files are reused; once everything is
  cached the command runs offline.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from snowlight.sources.nws.http import FetchError
from snowlight.weights.archive import ArchiveCsvError
from snowlight.weights.build import (
    DEFAULT_COVERAGE,
    DEFAULT_DIRECTORY,
    DEFAULT_OUT_DIR,
    DEFAULT_RESEARCH,
    Paths,
    WeightsBuildError,
    build,
)
from snowlight.weights.cache import DEFAULT_CACHE_DIR
from snowlight.weights.markets import MarketsError
from snowlight.weights.priority import PriorityError
from snowlight.weights.registered import DEFAULT_REGISTRY_DIR
from snowlight.weights.schools import SchoolsError
from snowlight.weights.zones import ZoneCountyError

_FAILURES = (
    ArchiveCsvError,
    FetchError,
    MarketsError,
    PriorityError,
    SchoolsError,
    WeightsBuildError,
    ZoneCountyError,
    OSError,
)


def parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    top = argparse.ArgumentParser(
        prog="python -m snowlight.weights",
        description="Closure weights: favor the places whose weather closes schools.",
    )
    actions = top.add_subparsers(dest="action", metavar="ACTION", required=True)
    run = actions.add_parser("build", help="count, weigh and rank; write the internal outputs")
    run.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR, help="download cache")
    run.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="output folder")
    run.add_argument("--directory", type=Path, default=DEFAULT_DIRECTORY, help="schools.parquet")
    run.add_argument("--coverage", type=Path, default=DEFAULT_COVERAGE, help="coverage.json")
    run.add_argument("--research", type=Path, default=DEFAULT_RESEARCH, help="docs/research folder")
    run.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_REGISTRY_DIR,
        help="station registry folder, read for two optional checks",
    )
    run.add_argument(
        "--skip-registry", action="store_true", help="do not read the station registry"
    )
    run.add_argument(
        "--skip-day-files",
        action="store_true",
        help="skip the cross-check against the day-file client",
    )
    return top


def _print(line: str) -> None:
    sys.stdout.write(line + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command; return the exit status."""
    args = parser().parse_args(argv)
    paths = Paths(
        cache_dir=args.cache_dir,
        out_dir=args.out_dir,
        directory=args.directory,
        coverage=args.coverage,
        research=args.research,
        registry=None if args.skip_registry else args.registry,
    )
    try:
        result = build(paths, day_files=not args.skip_day_files)
    except _FAILURES as error:
        sys.stderr.write(f"weights build failed: {error}\n")
        return 1
    _print(
        f"{result.schools} schools in {len(result.counties)} counties; mean "
        f"{result.mean_days:.3f} weighted closure days per school year per school "
        f"(county rule: {result.county_rule_mean:.3f})"
    )
    short = sum(
        int(str(record.get("schools_with_school_years_left_out") or 0))
        for record in result.counties.values()
    )
    _print(f"schools averaged over fewer school years: {short}")
    for row in result.states[:10]:
        _print(
            f"  {row['rank']:>2} {row['state']} weight {row['weight']} "
            f"(county rule {row.get('county_rule_weight')}, rank {row.get('county_rule_rank')})"
        )
    for key in ("listed_winter", "winter"):
        check = result.sanity[key]
        if isinstance(check, dict):
            verdict = "passes" if check.get("passes") else "FAILS"
            _print(f"sanity ({key}): {verdict}")
    for name, path in result.paths.items():
        _print(f"{name}: {path}")
    return 0
