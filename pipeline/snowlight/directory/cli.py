"""The ``snowlight directory`` subcommand."""

import argparse
import os
import ssl
import sys
from datetime import timedelta
from functools import partial
from pathlib import Path

import httpx
from pydantic import ValidationError

from snowlight.directory.build import (
    DEFAULT_CACHE_DIR,
    DEFAULT_INTERNAL_DIR,
    DEFAULT_OUT_DIR,
    BuildError,
    BuildPaths,
    EditionRefusedError,
    ZoneSource,
    build,
    read_edition,
    summary_lines,
)
from snowlight.directory.config import DEFAULT_CONFIG_PATH, load_config
from snowlight.directory.deployed import (
    MAX_WAIT,
    DeployedEditionError,
    EditionMismatchError,
    Reader,
)
from snowlight.directory.points import PointsFormatError
from snowlight.directory.report import ReconciliationError
from snowlight.directory.supplement import SupplementError
from snowlight.directory.tiles import TilesError
from snowlight.directory.zones import ZoneCoverageError, ZoneError, nws_zone_lookup
from snowlight.output import write_bytes_atomic
from snowlight.sources.nces.fetch import USER_AGENT, DownloadError
from snowlight.sources.nces.readers import SourceFormatError
from snowlight.sources.nces.xlsx import XlsxFormatError
from snowlight.weather.build import DEFAULT_CACHE_DIR as WEATHER_CACHE_DIR


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register ``directory`` and its ``build`` and ``deployed-edition`` actions."""
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
    run.add_argument(
        "--previous-edition",
        type=Path,
        default=None,
        metavar="FILE",
        help=(
            "schools/edition.json of the directory the site serves now (snowlight directory "
            "deployed-edition writes it): its date is kept when the content is unchanged; "
            "a missing or invalid file stops the build. Leave it out only when no edition "
            "was ever deployed"
        ),
    )
    run.add_argument(
        "--zones",
        action="store_true",
        help="also write each school's time zones (school_zones.parquet), from NWS files",
    )
    run.add_argument(
        "--zones-cache-dir",
        type=Path,
        default=WEATHER_CACHE_DIR,
        help="download cache for the NWS boundary files (default: the weather build's)",
    )
    run.add_argument(
        "--no-tiles",
        dest="tiles",
        action="store_false",
        help="skip schools.pmtiles, which the live ingest does not need",
    )
    run.set_defaults(handler=run_build)

    deployed = actions.add_parser(
        "deployed-edition",
        help="read the schools/edition.json the deployed site serves, exactly or not at all",
        description=(
            "Read schools/edition.json from the live GitHub Pages deploy (made from its "
            "artifact's directory, or a CDN copy younger than the last deploy) and write it "
            "to --out; with none deployed (only before editions shipped), remove --out. Exit "
            "1 when it cannot be known for certain (docs/deployed-edition.md). Needs "
            "GITHUB_TOKEN (actions: read, deployments: read, contents: read)."
        ),
    )
    deployed.add_argument("--site", required=True, help="the site's https URL")
    deployed.add_argument("--out", type=Path, required=True, help="where to write the edition")
    deployed.add_argument(
        "--repository",
        default=os.environ.get("GITHUB_REPOSITORY"),
        help="owner/repo whose Pages deploys serve the site (default: $GITHUB_REPOSITORY)",
    )
    deployed.add_argument(
        "--api-url",
        default=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
        help="the GitHub API (default: $GITHUB_API_URL or https://api.github.com)",
    )
    deployed.add_argument(
        "--max-wait",
        type=_positive_seconds,
        default=MAX_WAIT.total_seconds(),
        metavar="SECONDS",
        help=(
            "how long to wait for the CDN to fetch a copy younger than the last deploy, "
            f"then fail (default: {MAX_WAIT.total_seconds():.0f}); a caller with a start-up "
            "budget gives less and tries again later"
        ),
    )
    deployed.add_argument(
        "--date-past-mismatch",
        action="store_true",
        help=(
            "recovery, given by hand only (docs/deployed-edition.md): when the live deploy's "
            "edition.json names another directory than the one beside it, write to --out an "
            "edition dated the later of the two that no directory matches, so the build "
            "dates the directory past both; every other failure still fails"
        ),
    )
    deployed.set_defaults(handler=run_deployed_edition)


# The longest --max-wait: a day, far past any job's timeout.
MAX_WAIT_SECONDS = 86_400


def _positive_seconds(text: str) -> float:
    """``--max-wait``: a number of seconds above zero, up to :data:`MAX_WAIT_SECONDS`."""
    try:
        seconds = float(text)
    except ValueError:
        seconds = 0.0
    if not 0 < seconds <= MAX_WAIT_SECONDS:
        raise argparse.ArgumentTypeError(
            f"not a number of seconds above zero and at most {MAX_WAIT_SECONDS}: {text!r}"
        )
    return seconds


# Failures that mean "the sources or outputs did not check out", reported as a
# one-line error instead of a traceback.
_FAILURES = (
    BuildError,
    DownloadError,
    PointsFormatError,
    ReconciliationError,
    SourceFormatError,
    SupplementError,
    TilesError,
    ValidationError,
    XlsxFormatError,
    ZoneError,
)


# Refusals the inputs decide: the same inputs give the same refusal, so a caller
# must not try again (exit REFUSED), unlike after a failed download (exit 1).
# argparse exits 2 on a usage error (as uv does on its own errors), and the live
# publisher's gate will exit 3 (spec §7.7), so this refusal takes a code neither
# uses.
_REFUSALS = (EditionRefusedError, ZoneCoverageError)
REFUSED = 4


def run_build(args: argparse.Namespace) -> int:
    """Run ``snowlight directory build``.

    Returns 1 with a message if a check fails, and :data:`REFUSED` if the inputs
    themselves refuse the build (the deployed edition given, or too few known
    time zones), which no retry can change.
    """
    paths = BuildPaths(
        cache_dir=args.cache_dir,
        out_dir=args.out_dir,
        internal_dir=args.internal_dir,
        work_dir=args.work_dir,
    )
    zones: ZoneSource | None = (
        partial(nws_zone_lookup, args.zones_cache_dir) if args.zones else None
    )
    try:
        previous = None if args.previous_edition is None else read_edition(args.previous_edition)
        result = build(
            load_config(args.config),
            paths,
            previous=previous,
            zones=zones,
            write_tiles=args.tiles,
        )
    except _REFUSALS as error:
        sys.stderr.write(f"snowlight directory build: refused: {error}\n")
        return REFUSED
    except _FAILURES as error:
        sys.stderr.write(f"snowlight directory build: error: {error}\n")
        return 1
    sys.stdout.write("\n".join(summary_lines(result)) + "\n")
    return 0


def run_deployed_edition(args: argparse.Namespace) -> int:
    """Run ``snowlight directory deployed-edition``; return 1 when the edition is unknown."""
    # Whatever happens, no file from an earlier read is left to be taken for this one.
    args.out.unlink(missing_ok=True)
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token or not args.repository:
        sys.stderr.write(
            "snowlight directory deployed-edition: error: needs GITHUB_TOKEN and --repository\n"
        )
        return 1
    # httpx no longer reads SSL_CERT_FILE itself: a proxy's CA bundle is given here.
    bundle = os.environ.get("SSL_CERT_FILE")
    try:
        verify: ssl.SSLContext | bool = (
            ssl.create_default_context(cafile=bundle) if bundle else True
        )
    except (OSError, ssl.SSLError) as error:
        sys.stderr.write(
            f"snowlight directory deployed-edition: error: SSL_CERT_FILE {bundle}: {error}\n"
        )
        return 1
    timeout = httpx.Timeout(60.0, connect=30.0)
    api_headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    with (
        httpx.Client(
            base_url=args.api_url,
            headers=api_headers,
            follow_redirects=True,
            timeout=timeout,
            verify=verify,
        ) as api,
        httpx.Client(
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            max_redirects=5,
            timeout=timeout,
            verify=verify,
        ) as cdn,
    ):
        reader = Reader(
            site_url=args.site,
            repository=args.repository,
            api=api,
            cdn=cdn,
            max_wait=timedelta(seconds=args.max_wait),
        )
        try:
            found = reader.read()
        except EditionMismatchError as error:
            if not args.date_past_mismatch:
                return _unknown(reader, error)
            past = error.past_both()
            write_bytes_atomic(args.out, past.to_json_bytes())
            sys.stdout.write(
                f"Recovery (--date-past-mismatch): {error}\nThe build is given an edition "
                f"dated {past.generated_on} that no directory matches, so it dates the "
                "directory after that day, or on the build date when later\n"
            )
            return 0
        except DeployedEditionError as error:
            return _unknown(reader, error)
    for note in found.notes:
        sys.stdout.write(f"  {note}\n")
    if args.date_past_mismatch:
        sys.stdout.write(
            "--date-past-mismatch: nothing to date past, no edition is deployed\n"
            if found.data is None
            else "--date-past-mismatch: the deployed edition names its directory\n"
        )
    if found.data is None:
        sys.stdout.write(f"No schools/edition.json is deployed (read from {found.source})\n")
    else:
        write_bytes_atomic(args.out, found.data)
        sys.stdout.write(f"Deployed edition from {found.source}: {found.data.decode()}\n")
    return 0


def _unknown(reader: Reader, error: DeployedEditionError) -> int:
    """Report a read that could not know the deployed edition, with the reader's notes."""
    for note in reader.notes:
        sys.stderr.write(f"  {note}\n")
    sys.stderr.write(f"snowlight directory deployed-edition: error: {error}\n")
    return 1
