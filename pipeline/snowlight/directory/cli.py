"""The ``snowlight directory`` subcommand."""

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from snowlight.directory.build import (
    DEFAULT_CACHE_DIR,
    DEFAULT_INTERNAL_DIR,
    DEFAULT_OUT_DIR,
    BuildError,
    BuildPaths,
    build,
    summary_lines,
)
from snowlight.directory.config import DEFAULT_CONFIG_PATH, load_config
from snowlight.directory.points import PointsFormatError
from snowlight.directory.report import ReconciliationError
from snowlight.directory.tiles import TilesError
from snowlight.sources.nces.fetch import DownloadError
from snowlight.sources.nces.readers import SourceFormatError
from snowlight.sources.nces.xlsx import XlsxFormatError


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register ``directory`` and its ``build`` action on ``subparsers``."""
    directory = subparsers.add_parser(
        "directory",
        help="build the school directory from NCES files",
        description="Build the school directory (points.bin, meta.json, schools.pmtiles).",
    )
    actions = directory.add_subparsers(dest="directory_action", metavar="ACTION", required=True)
    run = actions.add_parser("build", help="download, filter and write the directory files")
    run.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="directory.yaml")
    run.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR, help="download cache")
    run.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="site data root; files go to <out-dir>/schools/",
    )
    run.add_argument(
        "--internal-dir",
        type=Path,
        default=DEFAULT_INTERNAL_DIR,
        help="where the parquet tables and build report go (never published)",
    )
    run.add_argument(
        "--work-dir", type=Path, default=None, help="scratch space (default: a temp dir)"
    )
    run.set_defaults(handler=run_build)


# Failures that mean "the sources or outputs did not check out", reported as a
# one-line error instead of a traceback.
_FAILURES = (
    BuildError,
    DownloadError,
    PointsFormatError,
    ReconciliationError,
    SourceFormatError,
    TilesError,
    ValidationError,
    XlsxFormatError,
)


def run_build(args: argparse.Namespace) -> int:
    """Run ``snowlight directory build``; return 1 with a message if a check fails."""
    paths = BuildPaths(
        cache_dir=args.cache_dir,
        out_dir=args.out_dir,
        internal_dir=args.internal_dir,
        work_dir=args.work_dir,
    )
    try:
        result = build(load_config(args.config), paths)
    except _FAILURES as error:
        sys.stderr.write(f"snowlight directory build: error: {error}\n")
        return 1
    sys.stdout.write("\n".join(summary_lines(result)) + "\n")
    return 0
