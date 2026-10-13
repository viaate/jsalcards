"""The ``snowlight replays`` command: build one day, or the table of every candidate day.

``snowlight replays build --day D`` matches the archive, builds the day, prints
its bar, and writes the internal report. ``--check`` prepares the run a second
time from the files (a fresh match of the archive with another worker count,
fresh zone lookups, the reader's caches emptied) and builds the day again;
unless the seed and report are byte-identical, A7 fails and the command exits
1. Independence from Python's hash seed is shown by a test that builds in two
processes. ``--write-seed`` writes ``<out>/seeds/<D>.json``, only when the
automatic bar passes, A7 included: it always builds twice.

Each preparation reads the archive's two files once (:func:`snapshot_archive`),
hashes those bytes, and reads its rows, comments and posted times from that
copy, so a seed is built from the archive its ``archive_sha256`` names even
when the archive is rewritten during the build.

``snowlight replays days`` builds every candidate day (:data:`CANDIDATES`) in one
run, writes each report, and prints the table.

The status reader (``snowlight.classify``, f5) is loaded by :func:`load_reader`
behind the :class:`~snowlight.replays.gates.ParseFn` protocol: until the reader is
on this branch the command says so and stops, and a reader whose call or levels
differ from what the gates assume (:func:`check_reader`) is refused the same way.
Nothing here makes a network request except the NWS boundary and county files
the alerts and listed commands already download and cache.
"""

import argparse
import importlib
import inspect
import json
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Final, NamedTuple, cast, get_args

import polars as pl
from pydantic import ValidationError

from snowlight.listed.cli import nws_counties
from snowlight.listed.evidence import EvidenceError, LoadedRows, load_rows
from snowlight.listed.located import Gazetteer
from snowlight.listed.matching import MatcherSpec
from snowlight.output import dumps_json, write_json
from snowlight.replays.build import (
    CONFLICTING,
    BuildError,
    DayBuild,
    DayInputs,
    Directory,
    MatchBook,
    ZoneLookup,
    build_day,
    built_for,
    match_archive,
)
from snowlight.replays.gates import (
    ALLOWED_NOTES,
    DISSENT_NOTES,
    MIN_CONFIDENCE,
    UNREAD_CONFIDENCE,
    ParseFn,
)
from snowlight.replays.report import day_report, report_path
from snowlight.replays.rows import RowExtra, row_extras
from snowlight.replays.seed import (
    archive_sha256,
    counties_sha256,
    matcher_sha256,
    reader_sha256,
    registry_sha256,
    rules_sha256,
    write_seed,
    zones_sha256,
)
from snowlight.schemas.vocab import STATUS_BY_KIND
from snowlight.sources.nws.boundaries import BoundaryCatalog, BoundaryError
from snowlight.sources.nws.http import FetchError, HttpCache, make_client
from snowlight.sources.stations.registry import Registry, RegistryError, load_registry
from snowlight.weather.timezones import TimeZoneLookup
from snowlight.weights.zones import CountyList

PIPELINE_ROOT: Final = Path(__file__).resolve().parents[2]
INTERNAL: Final = PIPELINE_ROOT / "out" / "internal"
DEFAULT_ARCHIVE: Final = INTERNAL / "stations" / "archive"
DEFAULT_REGISTRY: Final = PIPELINE_ROOT / "config" / "sources"
DEFAULT_DIRECTORY: Final = INTERNAL / "directory"
DEFAULT_META: Final = PIPELINE_ROOT / "out" / "site-data" / "schools" / "meta.json"
DEFAULT_ALIASES: Final = PIPELINE_ROOT / "config" / "aliases.yaml"
DEFAULT_OUT: Final = INTERNAL / "replays"
DEFAULT_CACHE: Final = PIPELINE_ROOT / ".cache" / "weather"
READER_MODULE: Final = "snowlight.classify"
CANDIDATES: Final[tuple[date, ...]] = tuple(
    date.fromisoformat(text)
    for text in (
        "2024-01-09",
        "2024-01-10",
        "2024-01-16",
        "2024-01-17",
        "2025-01-06",
        "2025-01-08",
        "2025-01-21",
        "2025-01-22",
        "2025-02-12",
        "2025-02-18",
        "2025-02-19",
        "2026-01-26",
    )
)
"""The fixed candidate days (spec section 3.1); no day is added by hand afterward."""

_FAILURES = (
    BoundaryError,
    BuildError,
    EvidenceError,
    FetchError,
    OSError,
    RegistryError,
    ValidationError,
    ValueError,
)


class ReaderMissingError(RuntimeError):
    """The status reader is not on this branch, or is not the reader the gates assume."""


def _note_literals(model: ModuleType) -> frozenset[str]:
    note = getattr(model, "Note", None)
    value = getattr(note, "__value__", note)
    return frozenset(str(item) for item in get_args(value))


def check_reader(module: ModuleType, model: ModuleType | None) -> ParseFn:
    """``module.parse_status``, once it is the reader the gates are written against.

    It must be called ``parse_status(text, *, posted_at, tz)``; its model's
    judgment and nothing-recognized levels must be :data:`MIN_CONFIDENCE` and
    :data:`UNREAD_CONFIDENCE`; its ``Note`` literals must hold every allowed note
    and every note a vote reads (:data:`~snowlight.replays.gates.DISSENT_NOTES`);
    its conflict level must be :data:`~snowlight.replays.build.CONFLICTING`; and
    its status kinds must be the published ones (``STATUS_BY_KIND``).

    Raises:
        ReaderMissingError: any of these differs.
    """
    parse = getattr(module, "parse_status", None)
    if not callable(parse):
        raise ReaderMissingError(f"{READER_MODULE} has no parse_status")
    params = list(inspect.signature(parse).parameters.values())
    keywords = {p.name for p in params if p.kind is inspect.Parameter.KEYWORD_ONLY}
    positional = [p for p in params if p.kind is not inspect.Parameter.KEYWORD_ONLY]
    if len(positional) != 1 or not {"posted_at", "tz"} <= keywords:
        raise ReaderMissingError(f"{READER_MODULE}.parse_status is not (text, *, posted_at, tz)")
    if model is None:
        raise ReaderMissingError(f"{READER_MODULE} has no model")
    levels = (getattr(model, "JUDGMENT", None), getattr(model, "UNKNOWN", None))
    if levels != (MIN_CONFIDENCE, UNREAD_CONFIDENCE):
        raise ReaderMissingError(f"{READER_MODULE}'s levels are {levels}")
    if not _note_literals(model) >= ALLOWED_NOTES | DISSENT_NOTES:
        raise ReaderMissingError(
            f"{READER_MODULE}'s notes lack {sorted(ALLOWED_NOTES | DISSENT_NOTES)}"
        )
    if getattr(model, "CONFLICTING", None) != CONFLICTING:
        raise ReaderMissingError(f"{READER_MODULE}'s conflict level is not {CONFLICTING}")
    kinds = getattr(model, "STATUS_KINDS", None)
    if not isinstance(kinds, tuple) or set(kinds) != set(STATUS_BY_KIND):
        raise ReaderMissingError(f"{READER_MODULE}'s status kinds are not {sorted(STATUS_BY_KIND)}")
    return cast("ParseFn", parse)


def load_reader() -> tuple[ParseFn, Path]:
    """The status reader's ``parse_status`` and the root its files hash from.

    Raises:
        ReaderMissingError: ``snowlight.classify`` cannot be imported, or
            :func:`check_reader` refuses it.
    """
    try:
        module = importlib.import_module(READER_MODULE)
    except ImportError as error:
        raise ReaderMissingError(
            f"the status reader ({READER_MODULE}) is not on this branch"
        ) from error
    try:
        model: ModuleType | None = importlib.import_module(f"{READER_MODULE}.model")
    except ImportError:
        model = None
    return check_reader(module, model), Path(str(module.__file__)).resolve().parents[2]


class Zones(NamedTuple):
    """A day's zone lookup and the boundary releases it was made from."""

    lookup: ZoneLookup
    releases: tuple[str, ...]
    """Each boundary release as its URL and its file's MD5 (:func:`seed.zones_sha256`)."""


type LookupLoader = Callable[[Path, date], Zones]
type CountyLoader = Callable[[], CountyList | None]


_LOOKUPS: dict[tuple[str, ...], TimeZoneLookup] = {}
"""Zone lookups by the boundary releases they were made from (one per release pair)."""


def nws_lookup(cache_dir: Path, day: date) -> Zones:  # pragma: no cover - reads NWS files
    """Each place's zone from the NWS boundaries in effect on ``day`` (as ``alerts check``)."""
    with HttpCache(make_client()) as cache:
        catalog = BoundaryCatalog(cache, cache_dir)
        releases = [
            catalog.release_for(kind, day) or catalog.releases(kind)[0]
            for kind in ("county", "zone")
        ]
        key = (str(cache_dir), *(release.url for release in releases))
        if key not in _LOOKUPS:
            counties, zones = (catalog.load(release) for release in releases)
            _LOOKUPS[key] = TimeZoneLookup(counties, zones)
    return Zones(_LOOKUPS[key], tuple(f"{release.url} md5:{release.md5}" for release in releases))


def forget_lookups() -> None:
    """Drop the zone lookups made so far, so the next run makes its own."""
    _LOOKUPS.clear()


def forget_reader() -> None:
    """Empty the status reader's caches, so A7's second build reads every text afresh.

    The reader keeps analyses by text across calls; a reading that depended on
    what was read before would then show as two builds that differ. Uses the
    reader's ``cache_clear`` when it has one, else its parse module's
    ``_forget_words``; a reader with neither keeps its caches.
    """
    module = sys.modules.get(READER_MODULE)
    clear = getattr(module, "cache_clear", None)
    if not callable(clear):
        clear = getattr(sys.modules.get(f"{READER_MODULE}.parse"), "_forget_words", None)
    if callable(clear):
        clear()


@dataclass(frozen=True, slots=True)
class Loaders:
    """The parts of a run that read the world; tests replace them."""

    reader: Callable[[], tuple[ParseFn, Path]] = load_reader
    lookup: LookupLoader = nws_lookup
    counties: CountyLoader = nws_counties
    forget: Callable[[], None] = forget_lookups
    forget_reader: Callable[[], None] = forget_reader


LOADERS = Loaders()


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register ``replays`` and its actions on ``subparsers``."""
    replays = subparsers.add_parser(
        "replays",
        help="past storm days built from archived closing lists",
        description="Build replay days from the archived station closing lists.",
    )
    actions = replays.add_subparsers(dest="replays_action", metavar="ACTION", required=True)
    build = actions.add_parser("build", help="build one day, print its bar, write its report")
    build.add_argument("--day", type=date.fromisoformat, required=True, help="YYYY-MM-DD")
    _inputs(build)
    build.add_argument(
        "--write-seed", action="store_true", help="build twice; write the seed if the bar passes"
    )
    build.add_argument("--check", action="store_true", help="build twice and compare bytes (A7)")
    build.set_defaults(handler=run_build)
    days = actions.add_parser("days", help="build every candidate day and print the table")
    _inputs(days)
    days.set_defaults(handler=run_days)


def _inputs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE, help="reads/rows folder")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY, help="sources folder")
    parser.add_argument("--directory", type=Path, default=DEFAULT_DIRECTORY)
    parser.add_argument("--meta", type=Path, default=DEFAULT_META, help="directory meta.json")
    parser.add_argument("--aliases", type=Path, default=DEFAULT_ALIASES)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE, help="NWS boundaries")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="reports and seeds folder")
    parser.add_argument("--workers", type=int, default=1)


@dataclass(frozen=True, slots=True)
class Run:
    """What every day of one run shares."""

    loaded: LoadedRows
    extras: dict[tuple[str, str], tuple[RowExtra, ...]]
    registry: Registry
    book: MatchBook
    directory: Directory
    parse: ParseFn
    pins: dict[str, str]
    """The input hashes and directory date every day's ``built`` block shares."""
    args: argparse.Namespace


def check_meta(meta: dict[str, object], schools: pl.DataFrame) -> str:
    """The directory's ``generated_on``, once ``meta`` is the meta.json of these schools.

    Raises:
        BuildError: meta.json counts or orders other schools than ``schools.parquet``.
    """
    ids = schools.sort("index")["id"].to_list() if "index" in schools.columns else None
    if meta.get("count") != schools.height or meta.get("ids") != ids:
        raise BuildError("--meta does not describe the schools of --directory")
    return str(meta["generated_on"])


ARCHIVE_FILES: Final = ("reads.jsonl", "rows.jsonl")


def snapshot_archive(
    archive: Path, into: Path, read: Callable[[Path], bytes] = Path.read_bytes
) -> str:
    """Copy the archive's two files into ``into`` as read once, and hash that copy.

    ``reads.jsonl`` is read before and after ``rows.jsonl``; when the two reads
    differ, the archive was rewritten in between and the pair may not belong
    together, so the build stops.

    Raises:
        BuildError: ``reads.jsonl`` changed while the archive was read.
    """
    reads, rows = (read(archive / name) for name in ARCHIVE_FILES)
    if read(archive / ARCHIVE_FILES[0]) != reads:
        raise BuildError(f"{archive} changed while it was read: build again")
    into.mkdir(parents=True, exist_ok=True)
    for name, data in zip(ARCHIVE_FILES, (reads, rows), strict=True):
        (into / name).write_bytes(data)
    return archive_sha256(into)


def _prepare(args: argparse.Namespace, loaders: Loaders) -> Run:
    parse, reader_root = loaders.reader()
    with tempfile.TemporaryDirectory(prefix="snowlight-replay-") as temp:
        copy = Path(temp)
        archive_hash = snapshot_archive(args.archive, copy)
        loaded = load_rows(copy / "reads.jsonl", copy / "rows.jsonl")
        extras = row_extras(copy / "rows.jsonl")
    registry = load_registry(args.registry)
    spec = MatcherSpec(args.directory, args.aliases)
    matcher = spec.build()
    schools = pl.read_parquet(args.directory / "schools.parquet")
    districts = pl.read_parquet(args.directory / "districts.parquet")
    generated_on = check_meta(json.loads(args.meta.read_text(encoding="utf-8")), schools)
    counties = loaders.counties()
    gazetteer = Gazetteer.build(schools, districts, counties)
    book = match_archive(
        loaded, registry, matcher, gazetteer=gazetteer, spec=spec, workers=args.workers
    )
    pins = {
        "rules_sha256": rules_sha256(PIPELINE_ROOT),
        "reader_sha256": reader_sha256(reader_root),
        "matcher_sha256": matcher_sha256(PIPELINE_ROOT, args.aliases, counties_sha256(counties)),
        "registry_sha256": registry_sha256(args.registry),
        "archive_sha256": archive_hash,
        "directory_generated_on": generated_on,
    }
    return Run(
        loaded=loaded,
        extras=extras,
        registry=registry,
        book=book,
        directory=Directory.from_frame(schools),
        parse=parse,
        pins=pins,
        args=args,
    )


def _build(run: Run, day: date, loaders: Loaders) -> tuple[DayBuild, bytes]:
    zones = loaders.lookup(run.args.cache_dir, day)
    inputs = DayInputs(
        loaded=run.loaded,
        registry=run.registry,
        book=run.book,
        directory=run.directory,
        lookup=zones.lookup,
        parse=run.parse,
        extras=run.extras,
    )
    built = built_for(**run.pins, zones_sha256=zones_sha256(zones.releases))
    made = build_day(day, inputs, built=built)
    report = day_report(made, run.registry, archive_drops=run.loaded.dropped)
    return made, dumps_json(report)


HEADER: Final = ("day", "lit", "sources", "markets", "corroborated", "conflicts", "control", "bar")


def table_line(made: DayBuild) -> str:
    """One row of the bar table."""
    quality = made.seed.quality
    cells = (
        made.day.isoformat(),
        str(quality.lit),
        str(quality.sources),
        str(quality.markets),
        str(quality.corroborated),
        str(quality.conflicts),
        str(made.control.lit),
        "pass" if made.passed else "FAIL " + "; ".join(made.failures),
    )
    return " | ".join(cells)


def _out(line: str) -> None:
    sys.stdout.write(line + "\n")


def replace_workers(args: argparse.Namespace) -> argparse.Namespace:
    """``args`` with another matcher worker count, for the second preparation of A7."""
    again = argparse.Namespace(**vars(args))
    again.workers = args.workers + 1
    return again


def run_build(args: argparse.Namespace, loaders: Loaders | None = None) -> int:
    """Run ``snowlight replays build``.

    Exits 0 when the day is built (whether or not it passes its bar), 1 when the
    inputs fail, A7 fails, or ``--write-seed`` is refused by the bar, and 2
    without the reader. ``--write-seed`` builds twice, as ``--check`` does.
    """
    use = loaders or LOADERS
    check = args.check or args.write_seed
    try:
        run = _prepare(args, use)
        made, report = _build(run, args.day, use)
        failures = list(made.failures)
        if check:
            use.forget()
            use.forget_reader()
            fresh = _prepare(replace_workers(args), use)
            again, report_again = _build(fresh, args.day, use)
            same_seed = dumps_json(again.seed.as_json()) == dumps_json(made.seed.as_json())
            if report_again != report or not same_seed:
                failures.append("A7: two builds differ")
        path = report_path(args.out, args.day)
        document = json.loads(report)
        document["failures"] = failures
        document["passed"] = not failures
        write_json(path, document)
        _out(" | ".join(HEADER))
        _out(table_line(made))
        differ = "A7: two builds differ" in failures
        if check:
            _out("A7: two builds differ" if differ else "A7: two builds are byte-identical")
        _out(f"report: {path}")
        if args.write_seed:
            if failures:
                _out("seed: not written (the bar fails)")
                return 1
            seed_path = args.out / "seeds" / f"{args.day.isoformat()}.json"
            write_seed(seed_path, made.seed)
            _out(f"seed: {seed_path}")
        if differ:
            return 1
    except ReaderMissingError as error:
        sys.stderr.write(f"snowlight replays build: {error}\n")
        return 2
    except _FAILURES as error:
        sys.stderr.write(f"snowlight replays build: error: {error}\n")
        return 1
    return 0


def run_days(
    args: argparse.Namespace, loaders: Loaders | None = None, days: Sequence[date] = CANDIDATES
) -> int:
    """Run ``snowlight replays days``."""
    use = loaders or LOADERS
    try:
        run = _prepare(args, use)
        _out(" | ".join(HEADER))
        for day in days:
            made, report = _build(run, day, use)
            write_json(report_path(args.out, day), json.loads(report))
            _out(table_line(made))
    except ReaderMissingError as error:
        sys.stderr.write(f"snowlight replays days: {error}\n")
        return 2
    except _FAILURES as error:
        sys.stderr.write(f"snowlight replays days: error: {error}\n")
        return 1
    return 0
