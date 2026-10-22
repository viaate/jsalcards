"""The ``snowlight mirror`` command: the data mirror's release tag, and seeding it.

``snowlight mirror tag`` prints the release tag of the current pins.
``snowlight mirror seed`` stages for upload, under its asset name, every pinned
file the release lacks or holds with other bytes (an asset counts as held only
when its SHA-256 is the pin's). A file an earlier mirror release holds (one the
pin bump left unchanged) is copied from that release, checked against its pin, so
only new files are read from their origins; those go through the same checked
downloads a build uses (a web page served with HTTP 200 is not the file, and the
bytes must match the pin). The release notes list every pin.
``.github/workflows/data-mirror.yml`` runs both; nothing else contacts the origins.
"""

import argparse
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx

from snowlight.directory.config import DEFAULT_CONFIG_PATH, load_config
from snowlight.mirror.pins import directory_pins
from snowlight.places.pins import DEFAULT_PLACES_PINS_PATH, load_places_pins
from snowlight.sources.mirror import (
    SIDECAR_SUFFIX,
    Form,
    Mirror,
    MirrorError,
    MirrorMissingError,
    Pin,
    check_pin_set,
    fetch_pinned,
    lsad_table_page,
    pin_set_tag,
    pinned_digest,
)
from snowlight.sources.nces.fetch import (
    DownloadError,
    FileCache,
    SourceChangedError,
    cache_path,
    make_client,
)

PIPELINE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_NCES_CACHE = PIPELINE_ROOT / ".cache" / "nces"
DEFAULT_PLACES_CACHE = PIPELINE_ROOT / ".cache" / "places"

# How many earlier releases a seed looks in for an unchanged file, newest first.
MAX_EARLIER = 5

type Log = Callable[[str], object]


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register ``mirror`` and its ``tag`` and ``seed`` actions."""
    mirror = subparsers.add_parser(
        "mirror",
        help="the data mirror the deploys read NCES and Census files from",
        description="The release of this repository that holds every pinned source file.",
    )
    mirror.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="directory.yaml")
    mirror.add_argument(
        "--places-pins", type=Path, default=DEFAULT_PLACES_PINS_PATH, help="places.yaml"
    )
    actions = mirror.add_subparsers(dest="mirror_action", metavar="ACTION", required=True)
    tag = actions.add_parser("tag", help="print the release tag of the current pins")
    tag.set_defaults(handler=run_tag)
    seed = actions.add_parser(
        "seed", help="download the pinned files the release lacks from their origins"
    )
    seed.add_argument(
        "--have",
        type=Path,
        default=None,
        metavar="FILE",
        help=(
            "the assets the release holds, one per line: the name, a tab, and the digest "
            "the releases API reports (sha256:<hex>, or empty when it reports none)"
        ),
    )
    seed.add_argument(
        "--mirror",
        metavar="ROOT",
        default=None,
        help=(
            "the releases download root: checks a held asset the API gives no digest for, "
            "and copies unchanged files from the --earlier releases"
        ),
    )
    seed.add_argument(
        "--earlier",
        type=Path,
        default=None,
        metavar="FILE",
        help="earlier data mirror release tags, newest first, one per line",
    )
    seed.add_argument("--dest", type=Path, required=True, help="where to stage the uploads")
    seed.add_argument("--notes", type=Path, required=True, help="where to write the release notes")
    seed.add_argument("--nces-cache-dir", type=Path, default=DEFAULT_NCES_CACHE)
    seed.add_argument("--places-cache-dir", type=Path, default=DEFAULT_PLACES_CACHE)
    seed.set_defaults(handler=run_seed)


def _pins(args: argparse.Namespace) -> tuple[list[Pin], list[Pin]]:
    return directory_pins(load_config(args.config)), load_places_pins(args.places_pins).pins()


def run_tag(args: argparse.Namespace) -> int:
    """Print the release tag of the pins."""
    directory, places = _pins(args)
    sys.stdout.write(pin_set_tag(check_pin_set([*directory, *places])) + "\n")
    return 0


def release_notes(tag: str, pins: Sequence[Pin]) -> str:
    """The release notes: what the release is and every asset with its pin."""
    lines = [
        f"Data mirror {tag}: the NCES and Census files the Preview deploy reads, so it never",
        "contacts nces.ed.gov or census.gov. Seeded by .github/workflows/data-mirror.yml from",
        "pipeline/config/directory.yaml and pipeline/config/places.yaml. Public data.",
        "",
        "| Asset | SHA-256 | Origin |",
        "| --- | --- | --- |",
    ]
    for pin in pins:
        digest = pin.sha256 if pin.form is Form.FILE else f"{pin.sha256} (code table)"
        lines.append(f"| {pin.asset} | {digest} | {pin.url} |")
    lines.append("")
    lines.append(
        "The LSAD code list's page changes on every load, so the asset is its code table, "
        "written as a plain page (snowlight.sources.mirror.lsad_table_page), and its pin "
        "is that page's SHA-256."
    )
    return "\n".join(lines) + "\n"


def _stage(source: Path, target: Path) -> None:
    target.unlink(missing_ok=True)
    try:
        os.link(source, target)
    except OSError:
        shutil.copyfile(source, target)


def _lsad_page(pin: Pin, cache: FileCache) -> bytes:
    """The pinned code table page, from the origin page whose table matches the pin."""
    fetched = cache.fetch(pin.url)
    if pinned_digest(fetched.path, pin.form) != pin.sha256 and fetched.from_cache:
        # An older cached copy of the page: read the page as it is now.
        fetched.path.unlink()
        fetched = cache.fetch(pin.url)
    if pinned_digest(fetched.path, pin.form) != pin.sha256:
        raise SourceChangedError(
            f"{pin.url}: its code table changed upstream (the pin is {pin.sha256}). Review it, "
            "then update the pin in config/places.yaml."
        )
    return lsad_table_page(fetched.path.read_text(encoding="utf-8"))


@dataclass(frozen=True, slots=True)
class Releases:
    """The mirror's releases, read to check held assets and to copy unchanged files."""

    client: httpx.Client
    root: str
    tag: str
    earlier: tuple[str, ...] = ()
    scratch: Path | None = None
    sleep: Callable[[float], None] = time.sleep

    def holds(self, pin: Pin) -> bool:
        """Whether the current release's asset is ``pin``'s file (read and checked)."""
        scratch = self.scratch or Path(tempfile.mkdtemp(prefix="mirror-check-"))
        dest = scratch / "check" / pin.asset
        try:
            mirror = Mirror(self.root, (pin,), release=self.tag)
            fetch_pinned(self.client, mirror, pin, dest, sleep=self.sleep)
        except MirrorError:
            return False
        finally:
            dest.unlink(missing_ok=True)
            dest.with_name(dest.name + SIDECAR_SUFFIX).unlink(missing_ok=True)
        return True

    def copy_earlier(self, pin: Pin, dest: Path, log: Log) -> str | None:
        """Copy ``pin``'s file from the newest earlier release that holds it intact.

        Returns that release's tag, or ``None`` when none holds it.
        """
        for tag in self.earlier[:MAX_EARLIER]:
            try:
                mirror = Mirror(self.root, (pin,), release=tag)
                fetch_pinned(self.client, mirror, pin, dest, sleep=self.sleep)
            except MirrorMissingError:
                continue
            except MirrorError as error:
                log(f"  {pin.asset}: not copied from {tag} ({error})")
                continue
            return tag
        return None


def read_have(path: Path | None) -> dict[str, str | None]:
    """The ``--have`` file: each held asset name and its reported digest (``None``: none)."""
    if path is None or not path.exists():
        return {}
    held: dict[str, str | None] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        name, _tab, digest = line.strip().partition("\t")
        if name:
            held[name] = digest.strip() or None
    return held


def _is_held(pin: Pin, have: Mapping[str, str | None], releases: Releases | None) -> bool:
    if pin.asset not in have:
        return False
    digest = have[pin.asset]
    if digest is not None:
        return digest == f"sha256:{pin.sha256}"
    return releases is not None and releases.holds(pin)


def seed(
    jobs: Sequence[tuple[Pin, FileCache]],
    have: Mapping[str, str | None],
    dest: Path,
    log: Log,
    releases: Releases | None = None,
) -> list[Path]:
    """Stage in ``dest`` every pinned file the release does not hold intact.

    An asset is held when its reported digest is the pin's, or, with no digest, when
    ``releases`` reads it back as the pin's file; any other asset is staged again
    (and replaced on upload). A staged file is copied from an earlier release when
    one holds it, else read from its origin.

    Raises:
        DownloadError: when a file cannot be read from its origin or does not match its pin.
    """
    dest.mkdir(parents=True, exist_ok=True)
    staged: list[Path] = []
    for pin, cache in jobs:
        if _is_held(pin, have, releases):
            log(f"  {pin.asset}: in the release")
            continue
        if pin.asset in have:
            log(f"  {pin.asset}: in the release, but not as pinned; staged again")
        target = dest / pin.asset
        earlier = None
        if releases is not None:
            earlier = releases.copy_earlier(pin, cache_path(cache.root, pin.url), log)
        if earlier is not None:
            _stage(cache_path(cache.root, pin.url), target)
            log(f"  {pin.asset}: staged from {earlier} ({target.stat().st_size} bytes)")
        elif pin.form is Form.LSAD_TABLE:
            target.write_bytes(_lsad_page(pin, cache))
            log(f"  {pin.asset}: staged from its origin ({target.stat().st_size} bytes)")
        else:
            _stage(cache.fetch(pin.url, pin.sha256).path, target)
            log(f"  {pin.asset}: staged from its origin ({target.stat().st_size} bytes)")
        staged.append(target)
    return staged


def _stderr(line: str) -> None:
    sys.stderr.write(line + "\n")


def run_seed(args: argparse.Namespace) -> int:
    """Stage the pinned files the release lacks, and write its notes."""
    directory, places = _pins(args)
    pins = check_pin_set([*directory, *places])
    tag = pin_set_tag(pins)
    have = read_have(args.have)
    earlier: tuple[str, ...] = ()
    if args.earlier is not None and args.earlier.exists():
        lines = args.earlier.read_text(encoding="utf-8").splitlines()
        earlier = tuple(t for t in (line.strip() for line in lines) if t and t != tag)
    args.notes.parent.mkdir(parents=True, exist_ok=True)
    args.notes.write_text(release_notes(tag, pins), encoding="utf-8")
    listed = len(have.keys() & {p.asset for p in pins})
    _stderr(f"data mirror {tag}: {len(pins)} pinned files, {listed} listed in the release")
    places_urls = {pin.url for pin in places}
    with (
        FileCache(args.nces_cache_dir, make_client()) as nces,
        FileCache(args.places_cache_dir, make_client()) as census,
        make_client() as client,
        tempfile.TemporaryDirectory(prefix="mirror-seed-") as scratch,
    ):
        releases = None
        if args.mirror:
            releases = Releases(client, args.mirror, tag, earlier, Path(scratch))
        jobs = [(pin, census if pin.url in places_urls else nces) for pin in pins]
        try:
            staged = seed(jobs, have, args.dest, _stderr, releases)
        except (DownloadError, ValueError) as error:
            _stderr(f"snowlight mirror seed: {error}")
            return 1
    _stderr(f"staged {len(staged)} files for upload")
    return 0
