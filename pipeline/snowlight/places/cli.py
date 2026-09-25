"""The ``snowlight places`` command."""

import argparse
import re
import sys
from pathlib import Path

import snowlight
from snowlight.places.build import Pins, PlacesBuildError, build_places
from snowlight.places.download import DownloadError, SourceCache, make_client
from snowlight.places.grf import GrfFormatError
from snowlight.places.records import SourceMismatchError
from snowlight.places.xlsx import XlsxError
from snowlight.sources.census import CensusFormatError

_FAILURES = (
    CensusFormatError,
    DownloadError,
    GrfFormatError,
    PlacesBuildError,
    SourceMismatchError,
    XlsxError,
)


def pipeline_root() -> Path:
    """Return the ``pipeline/`` project directory, or the working directory if not found.

    The package lives at ``pipeline/snowlight`` in a checkout, so the project
    root is the package's parent when it holds ``pyproject.toml``.
    """
    candidate = Path(snowlight.__file__).resolve().parent.parent
    return candidate if (candidate / "pyproject.toml").is_file() else Path.cwd()


def _series(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d{4})-(\d{4})", value)
    if match is None:
        raise argparse.ArgumentTypeError(f"expected BASE-VINTAGE such as 2020-2025, got {value!r}")
    return int(match.group(1)), int(match.group(2))


def _year(value: str) -> int:
    if not re.fullmatch(r"\d{4}", value):
        raise argparse.ArgumentTypeError(f"expected a four-digit year, got {value!r}")
    return int(value)


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Add the ``places`` command and its ``build`` action to ``subparsers``."""
    places = subparsers.add_parser(
        "places",
        help="city and ZIP code records for search",
        description="City and ZIP code records for the site's search box.",
    )
    actions = places.add_subparsers(dest="places_action", metavar="<action>", required=True)
    build = actions.add_parser(
        "build",
        help="download the sources and write cities.jsonl and zips.jsonl",
        description=(
            "Download (or reuse from the cache) the newest Census Gazetteer, population "
            "estimate, LSAD, ZCTA-county and NCES GRF files, then write the search records "
            "and their internal manifest."
        ),
    )
    build.add_argument("--cache-dir", type=Path, help="download cache (default: .cache/places)")
    build.add_argument(
        "--out-dir", type=Path, help="where to write the records (default: out/site-data/search)"
    )
    build.add_argument(
        "--manifest", type=Path, help="internal manifest path (default: out/manifests/places.json)"
    )
    build.add_argument(
        "--revalidate",
        action="store_true",
        help="confirm cached files with conditional requests and re-download changed ones",
    )
    build.add_argument("--gazetteer-year", type=_year, help="use this Gazetteer release")
    build.add_argument("--grf-year", type=_year, help="use the GRF built from this TIGER year")
    build.add_argument(
        "--popest-series", type=_series, help="use this estimates series, e.g. 2020-2025"
    )
    build.set_defaults(handler=run_build)


def run_build(args: argparse.Namespace) -> int:
    """Run ``snowlight places build`` and return its exit code."""
    root = pipeline_root()
    cache_dir: Path = args.cache_dir or root / ".cache" / "places"
    out_dir: Path = args.out_dir or root / "out" / "site-data" / "search"
    manifest: Path = args.manifest or root / "out" / "manifests" / "places.json"
    pins = Pins(
        gazetteer_year=args.gazetteer_year,
        grf_year=args.grf_year,
        popest_series=args.popest_series,
    )
    try:
        with SourceCache(cache_dir, make_client(), revalidate=args.revalidate) as cache:
            result = build_places(cache, out_dir, manifest, pins)
    except _FAILURES as exc:
        sys.stderr.write(f"places build failed: {exc}\n")
        return 1
    for output in result.outputs:
        sys.stdout.write(f"wrote {output.records} records to {output.path}\n")
    sys.stdout.write(f"manifest: {result.manifest_path}\n")
    return 0
