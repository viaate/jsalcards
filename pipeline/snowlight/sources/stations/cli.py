"""The ``snowlight stations`` command.

Actions:

* ``fetch``: read every live source once (the list each station's page loads
  today; under its platform's terms or the project owner's recorded decision, see
  :class:`~snowlight.sources.stations.registry.Terms`, with robots.txt's verdict on
  every URL recorded, not obeyed, under the owner's decision of 2026-09-26) and
  write raw rows, reads, health and a manifest to ``out/internal/stations/``;
* ``registry``: load and cross-check ``config/sources/*.yaml`` and print a summary;
* ``robots``: read each station's robots.txt and report its verdict on the
  station's URLs (``--update`` records the result in the registry files);
* ``archive plan``: pick storm-day captures from downloaded CDX listings (the NWS
  winter-warning school days of each station's market first, see
  :mod:`snowlight.sources.stations.storms`; ``--by-size`` ranks by size alone);
* ``archive plan-follow``: pick the captures of the files pages load their lists
  from, near the pages (see :func:`snowlight.sources.stations.archive.plan_follow`);
* ``archive parse``: run downloaded Wayback captures through the adapters;
* ``fixture add``: slice a downloaded capture into a test fixture with its provenance;
* ``fixture add-live``: the same for a body the last live fetch read;
* ``pagecheck targets`` / ``pagecheck apply``: set each Gray station's ``data_url``
  to the list file its page loads, from a browser check (``pagecheck.cjs``; see
  :mod:`snowlight.sources.stations.pagecheck`);
* ``coverage``: measure the share of schools covered, plain and closure-weighted,
  and draw the coverage map (and check county lists against the counties archived
  rows name); with the proven share, counting only lists seen populated at least
  once, live, archived or in a fixture (see :mod:`snowlight.sources.stations.proof`).
"""

import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import polars as pl

from snowlight.output import JSONValue
from snowlight.sources.nws.http import SIDECAR_SUFFIX, HttpCache, sha256_file
from snowlight.sources.nws.http import FetchError as ReferenceFetchError
from snowlight.sources.nws.http import make_client as make_reference_client
from snowlight.sources.nws.shapefile import ShapefileError
from snowlight.sources.stations import (
    archive,
    coverage,
    dma,
    fetch,
    fixtures,
    notices,
    observed,
    pagecheck,
    proof,
    storms,
)
from snowlight.sources.stations.adapters import AdapterRegistry
from snowlight.sources.stations.http import (
    ConditionalStore,
    PoliteClient,
    iso_utc,
    make_client,
    system_clock,
)
from snowlight.sources.stations.model import ReadMode, ShapeError
from snowlight.sources.stations.registry import (
    DEFAULT_REGISTRY_DIR,
    PIPELINE_ROOT,
    CountyBasis,
    PlatformFile,
    Registry,
    RegistryError,
    RobotsCheck,
    StationStatus,
    load_registry,
    write_platform_file,
)
from snowlight.weights import schools as weights_schools
from snowlight.weights import zones as weights_zones
from snowlight.weights.archive import ArchiveCsvError
from snowlight.weights.build import WeightsBuildError
from snowlight.weights.cache import WeightsCache
from snowlight.weights.schools import SchoolsError
from snowlight.weights.zones import ZoneCountyError

DEFAULT_REFERENCE_DIR = PIPELINE_ROOT / ".cache" / "stations" / "reference"
DEFAULT_DIRECTORY = PIPELINE_ROOT / "out" / "internal" / "directory" / "schools.parquet"
DEFAULT_WEIGHTS = PIPELINE_ROOT / "out" / "internal" / "weights" / "closure-weights.json"
DEFAULT_FIXTURES = PIPELINE_ROOT / "tests" / "stations" / "fixtures"
COUNTY_SHAPES_URL = "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_county_20m.zip"
_FAILURES = (
    RegistryError,
    archive.ArchiveError,
    coverage.CoverageError,
    dma.DmaError,
    observed.ObservedError,
    ShapeError,
    proof.ProofError,
    ReferenceFetchError,
    ShapefileError,
    WeightsBuildError,
    ArchiveCsvError,
    ZoneCountyError,
    SchoolsError,
    KeyError,
    OSError,
)


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Add the ``stations`` command and its actions to ``subparsers``."""
    stations = subparsers.add_parser(
        "stations",
        help="station closings sources: fetch, registry, robots, archive, coverage",
        description="TV station and other closings sources.",
    )
    stations.add_argument(
        "--registry", type=Path, default=DEFAULT_REGISTRY_DIR, help="registry folder"
    )
    actions = stations.add_subparsers(dest="stations_action", metavar="<action>", required=True)

    fetch_p = actions.add_parser("fetch", help="read every live source once")
    fetch_p.add_argument("--out-dir", type=Path, default=fetch.DEFAULT_OUT_DIR)
    fetch_p.add_argument("--cache-dir", type=Path, default=fetch.DEFAULT_CACHE_DIR)
    fetch_p.add_argument("--only", nargs="+", metavar="ID", help="read only these stations")
    fetch_p.set_defaults(handler=run_fetch)

    registry_p = actions.add_parser("registry", help="check the registry and summarize it")
    registry_p.add_argument(
        "--check-counties",
        action="store_true",
        help="re-derive every DMA-based county list from the pinned crosswalk and compare",
    )
    registry_p.add_argument("--reference-dir", type=Path, default=DEFAULT_REFERENCE_DIR)
    registry_p.set_defaults(handler=run_registry)

    robots_p = actions.add_parser("robots", help="check each station's robots.txt")
    robots_p.add_argument("--update", action="store_true", help="record results in the registry")
    robots_p.add_argument("--only", nargs="+", metavar="ID", help="check only these stations")
    robots_p.set_defaults(handler=run_robots)

    _register_archive(actions)
    _register_fixture(actions)
    _register_pagecheck(actions)

    coverage_p = actions.add_parser("coverage", help="measure coverage and draw the map")
    coverage_p.add_argument("--directory", type=Path, default=DEFAULT_DIRECTORY)
    coverage_p.add_argument("--health", type=Path, default=fetch.DEFAULT_OUT_DIR / "health.json")
    coverage_p.add_argument("--out-dir", type=Path, default=fetch.DEFAULT_OUT_DIR)
    coverage_p.add_argument("--reference-dir", type=Path, default=DEFAULT_REFERENCE_DIR)
    coverage_p.add_argument(
        "--archive-rows",
        type=Path,
        default=fetch.DEFAULT_OUT_DIR / "archive" / "rows.jsonl",
        help="rows read from archived captures, to check county lists against",
    )
    coverage_p.add_argument(
        "--weights",
        type=Path,
        default=DEFAULT_WEIGHTS,
        help="closure weights per county (the weights build's closure-weights.json)",
    )
    coverage_p.add_argument("--no-weights", action="store_true", help="report plain shares only")
    coverage_p.add_argument(
        "--live-reads",
        type=Path,
        default=fetch.DEFAULT_OUT_DIR / "reads.jsonl",
        help="the last live fetch's reads, as evidence of lists seen populated",
    )
    coverage_p.add_argument(
        "--archive-reads",
        type=Path,
        default=fetch.DEFAULT_OUT_DIR / "archive" / "reads.jsonl",
        help="reads of archived captures, as evidence of lists seen populated",
    )
    coverage_p.add_argument(
        "--archive-health",
        type=Path,
        default=fetch.DEFAULT_OUT_DIR / "archive" / "health.json",
        help="the archived captures that could not be read, for the unproven list",
    )
    coverage_p.add_argument(
        "--fixtures",
        type=Path,
        default=DEFAULT_FIXTURES,
        help="test fixtures (real bodies with provenance), as evidence of lists seen populated",
    )
    coverage_p.add_argument("--no-proof", action="store_true", help="leave out the proven share")
    coverage_p.add_argument("--no-png", action="store_true")
    coverage_p.set_defaults(handler=run_coverage)


def _register_archive(actions: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Add ``stations archive plan`` and ``stations archive parse``."""
    archive_p = actions.add_parser("archive", help="Wayback listings and captures")
    archive_actions = archive_p.add_subparsers(
        dest="archive_action", metavar="<archive action>", required=True
    )
    plan_p = archive_actions.add_parser("plan", help="pick storm-day captures from listings")
    plan_p.add_argument("cdx_dir", type=Path, help="folder of downloaded CDX listings")
    plan_p.add_argument("--per-season", type=int, default=1)
    plan_p.add_argument("--since", type=date.fromisoformat, help="ignore captures before this day")
    plan_p.add_argument("--seasons", type=int, nargs="+", help="winter seasons (start years)")
    plan_p.add_argument(
        "--skip-downloaded",
        type=Path,
        metavar="DIR",
        help="leave out seasons already read from the artifacts under DIR",
    )
    plan_p.add_argument(
        "--eras-before", type=int, metavar="YEAR", help="also sample one capture per year before"
    )
    plan_p.add_argument("--only", nargs="+", metavar="ID", help="plan only these stations")
    plan_p.add_argument(
        "--by-size",
        action="store_true",
        help="rank captures by size alone, not by NWS winter-warning school days first",
    )
    plan_p.set_defaults(handler=run_archive_plan)
    follow_p = archive_actions.add_parser(
        "plan-follow", help="pick list-file captures near pages that hold no list"
    )
    follow_p.add_argument("artifact_dir", type=Path, help="downloaded artifacts and listings")
    follow_p.add_argument("--per-season", type=int, default=2)
    follow_p.add_argument("--limit", type=int, help="keep only the first N requests")
    follow_p.add_argument(
        "--by-size",
        action="store_true",
        help="rank captures by size alone, not by NWS winter-warning school days first",
    )
    follow_p.set_defaults(handler=run_archive_plan_follow)
    parse_p = archive_actions.add_parser("parse", help="parse downloaded captures")
    parse_p.add_argument("artifact_dir", type=Path, help="folder holding snapshots/manifest.jsonl")
    parse_p.add_argument("--out-dir", type=Path, default=fetch.DEFAULT_OUT_DIR / "archive")
    parse_p.set_defaults(handler=run_archive_parse)


def _register_pagecheck(actions: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Add ``stations pagecheck targets`` and ``stations pagecheck apply``."""
    check_p = actions.add_parser(
        "pagecheck", help="set each station's data_url from a browser check of its page"
    )
    check_actions = check_p.add_subparsers(
        dest="pagecheck_action", metavar="<pagecheck action>", required=True
    )
    targets_p = check_actions.add_parser("targets", help="print the pages to open (JSON)")
    targets_p.add_argument("--platform", nargs="+", default=["gray"])
    targets_p.set_defaults(handler=run_pagecheck_targets)
    apply_p = check_actions.add_parser("apply", help="read pagecheck.cjs records")
    apply_p.add_argument("check_dir", type=Path, help="the folder pagecheck.cjs wrote")
    apply_p.add_argument("--platform", default="gray")
    apply_p.add_argument("--write", action="store_true", help="update the registry file")
    apply_p.set_defaults(handler=run_pagecheck_apply)


def run_pagecheck_targets(args: argparse.Namespace) -> int:
    """Run ``snowlight stations pagecheck targets``."""
    try:
        registry = load_registry(args.registry)
    except _FAILURES as error:
        return _fail("pagecheck targets", error)
    _print(json.dumps(pagecheck.targets(registry, args.platform), indent=1))
    return 0


def run_pagecheck_apply(args: argparse.Namespace) -> int:
    """Run ``snowlight stations pagecheck apply``."""
    try:
        registry = load_registry(args.registry)
        records = pagecheck.read_pages(args.check_dir)
        decisions = {
            station_id: pagecheck.decide(registry.stations[station_id], pages)
            for station_id, pages in records.items()
            if station_id in registry.stations
        }
        content = registry.files[args.platform]
        updated = pagecheck.apply(content, decisions)
        if args.write:
            write_platform_file(args.registry, updated)
    except (*_FAILURES, pagecheck.PageCheckError, ValueError) as error:
        return _fail("pagecheck apply", error)
    for decision in sorted(decisions.values(), key=lambda d: d.station_id):
        _print(f"{decision.station_id}: {decision.note} {decision.data_url or ''}".rstrip())
    for line in pagecheck.review(registry, decisions):
        _print(line)
    return 0


def _register_fixture(actions: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Add ``stations fixture add``."""
    fixture_p = actions.add_parser("fixture", help="test fixtures from real captures")
    fixture_actions = fixture_p.add_subparsers(
        dest="fixture_action", metavar="<fixture action>", required=True
    )
    add_p = fixture_actions.add_parser("add", help="slice a downloaded capture into a fixture")
    add_p.add_argument("artifact_dir", type=Path)
    add_p.add_argument("--timestamp", required=True, help="the capture timestamp asked for")
    add_p.add_argument("--url", required=True, help="the URL asked for")
    add_p.add_argument("--file", required=True, help="fixture path, e.g. hearst/kmbc-2024.html")
    add_p.add_argument("--slice", default="none", choices=sorted(fixtures.SLICERS))
    add_p.add_argument("--note", default="")
    add_p.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    add_p.set_defaults(handler=run_fixture_add)
    live_p = fixture_actions.add_parser(
        "add-live", help="slice a body the last live fetch read into a fixture"
    )
    live_p.add_argument("--url", required=True, help="the URL the fetch read")
    live_p.add_argument("--file", required=True, help="fixture path, e.g. gray/kptv-live.json")
    live_p.add_argument("--slice", default="none", choices=sorted(fixtures.SLICERS))
    live_p.add_argument("--note", default="")
    live_p.add_argument(
        "--manifest",
        type=Path,
        default=fetch.DEFAULT_OUT_DIR / "manifest.json",
        help="the fetch's run manifest (the read's time and SHA-256)",
    )
    live_p.add_argument("--cache-dir", type=Path, default=fetch.DEFAULT_CACHE_DIR)
    live_p.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    live_p.set_defaults(handler=run_fixture_add_live)


def _print(text: str) -> None:
    sys.stdout.write(text + "\n")


def _fail(action: str, error: Exception) -> int:
    sys.stderr.write(f"stations {action} failed: {error}\n")
    return 1


def run_fetch(args: argparse.Namespace) -> int:
    """Run ``snowlight stations fetch``."""
    try:
        registry = load_registry(args.registry)
        registry.check_adapters(AdapterRegistry(args.registry))
        client = PoliteClient(make_client(), ConditionalStore(args.cache_dir))
        try:
            result = fetch.run(registry, client, clock=system_clock, only=args.only)
        finally:
            client.close()
        paths = fetch.write_outputs(result, args.out_dir, system_clock())
    except _FAILURES as error:
        return _fail("fetch", error)
    counts = fetch.totals(result.health)
    _print(
        f"{counts['sources']} sources: {counts['ok']} ok, {counts['empty']} empty, "
        f"{counts['stale']} stale, {counts['error']} error, {counts['skipped']} skipped; "
        f"{counts['rows']} rows; {counts['robots_disallowed']} read although robots.txt "
        "disallows them (recorded)"
    )
    for name, path in paths.items():
        _print(f"{name}: {path}")
    return 0


def run_registry(args: argparse.Namespace) -> int:
    """Run ``snowlight stations registry``."""
    try:
        registry = load_registry(args.registry)
        registry.check_adapters(AdapterRegistry(args.registry))
        mismatches: list[str] = []
        if args.check_counties:
            with HttpCache(make_reference_client()) as cache:
                references = _references(cache, args.reference_dir)
            gazetteer = dma.read_gazetteer(references["gazetteer"])
            markets = dma.read_crosswalk(
                references["dma"], gazetteer, dma.read_ct_regions(references["ct"])
            )
            filled = _filled(markets, references, gazetteer)
            mismatches = county_mismatches(registry, markets, filled)
    except _FAILURES as error:
        return _fail("registry", error)
    for platform in sorted(registry.platforms.values(), key=lambda p: p.id):
        members = [s for s in registry.stations.values() if s.platform == platform.id]
        active = sum(s.status is StationStatus.ACTIVE for s in members)
        terms = platform.terms
        polled = "polled" if terms.pollable else "not polled"
        if terms.owner_decision is not None:
            polled += f" (project owner's decision of {terms.owner_decision.decided_on})"
        _print(
            f"{platform.id}: {len(members)} stations ({active} with an endpoint); terms "
            f"{platform.terms.automated_access.value}: {polled}"
        )
    for line in mismatches:
        _print(f"county list differs from the crosswalk: {line}")
    if args.check_counties and not mismatches:
        _print("every DMA-based county list matches the pinned crosswalk")
    return 1 if mismatches else 0


def county_mismatches(
    registry: Registry, markets: dma.DmaCounties, filled: dma.DmaCounties | None = None
) -> list[str]:
    """Return the stations whose DMA-based counties differ from the crosswalk's.

    With ``filled`` (the crosswalk with the counties it lacks placed by the second
    list, :func:`snowlight.sources.stations.dma.fill_missing`), a list holding the
    market's counties plus any of those placed counties also matches.
    """
    problems = []
    for station in sorted(registry.stations.values(), key=lambda s: s.id):
        counties = station.counties
        if counties is None or counties.basis is not CountyBasis.DMA:
            continue
        expected = markets.by_dma.get(station.dma or "")
        extra = (
            {fips for fips, label in filled.supplemented if label == station.dma}
            if filled
            else set()
        )
        if expected is None:
            problems.append(f"{station.id}: market {station.dma!r} is not in the crosswalk")
        elif tuple(expected) != counties.fips and not (
            set(expected) <= set(counties.fips) <= set(expected) | extra
        ):
            problems.append(f"{station.id}: {len(counties.fips)} listed, {len(expected)} in market")
    return problems


def run_robots(args: argparse.Namespace) -> int:
    """Run ``snowlight stations robots``."""
    try:
        registry = load_registry(args.registry)
    except _FAILURES as error:
        return _fail("robots", error)
    wanted = set(args.only) if args.only else None
    client = PoliteClient(make_client(), ConditionalStore(fetch.DEFAULT_CACHE_DIR))
    checks: dict[str, tuple[RobotsCheck, ...]] = {}
    try:
        for station in registry.active():
            if wanted is not None and station.id not in wanted:
                continue
            found = []
            # A station polled at its page reads the files its page check saw it load too.
            loads = station.page_check.loads if station.page_check and not station.data_url else ()
            for url in dict.fromkeys(u for u in (station.page_url, station.data_url, *loads) if u):
                robots = client.robots_for(url)
                allowed, rule = robots.decide(url, client.user_agent)
                check = RobotsCheck.model_validate(
                    {
                        "url": url,
                        "checked_at": system_clock(),
                        "state": robots.state,
                        "allowed": allowed,
                        "rule": rule,
                        "crawl_delay": robots.crawl_delay(client.user_agent),
                        "disallowed_agents": robots.disallowed_agents(),
                        "sha256": robots.sha256,
                    }
                )
                found.append(check)
                verdict = "allowed" if allowed else "DISALLOWED"
                _print(f"{station.id} {url}: {verdict} ({rule})")
            checks[station.id] = tuple(found)
    finally:
        client.close()
    if args.update:
        for name, content in registry.files.items():
            if not any(station.id in checks for station in content.stations):
                continue  # a file with no station checked is left exactly as it is
            stations = tuple(
                station.model_copy(update={"robots": checks[station.id]})
                if station.id in checks
                else station
                for station in content.stations
            )
            updated = PlatformFile.model_validate(
                {"platform": content.platform, "stations": stations}
            )
            path = write_platform_file(args.registry, updated)
            _print(f"updated {path} ({name})")
    return 0


def run_archive_plan(args: argparse.Namespace) -> int:
    """Run ``snowlight stations archive plan``: print snapshot requests as JSON."""
    try:
        registry = load_registry(args.registry)
        index = archive.station_index(registry)
        captures: dict[str, list[archive.Capture]] = {}
        for path in sorted(args.cdx_dir.rglob("*.json")):
            for capture in archive.read_cdx(path):
                station = index.get(archive.url_key(capture.original))
                if station is not None:
                    captures.setdefault(station.id, []).append(capture)
        if args.only:
            captures = {sid: caps for sid, caps in captures.items() if sid in set(args.only)}
        skip = archive.downloaded(args.skip_downloaded) if args.skip_downloaded else set()
        options = archive.PlanOptions(
            seasons=frozenset(args.seasons) if args.seasons else None,
            per_season=args.per_season,
            since=args.since,
            skip=frozenset(skip),
            eras_before=args.eras_before,
            storms=None if args.by_size else _storm_days(registry),
        )
        plan = archive.plan_snapshots(captures, options)
    except _FAILURES as error:
        return _fail("archive plan", error)
    _print(json.dumps({"snapshots": plan}, indent=2))
    return 0


def _storm_days(registry: Registry) -> storms.StormDays:
    """Count the NWS winter-warning school days for every station's counties."""
    return storms.StormDays.build(registry, storms.load_county_days())


def run_archive_plan_follow(args: argparse.Namespace) -> int:
    """Run ``snowlight stations archive plan-follow``: print snapshot requests as JSON."""
    try:
        registry = load_registry(args.registry)
        plan = archive.plan_follow(
            registry,
            args.artifact_dir,
            per_season=args.per_season,
            limit=args.limit,
            storms=None if args.by_size else _storm_days(registry),
        )
    except _FAILURES as error:
        return _fail("archive plan-follow", error)
    _print(json.dumps({"snapshots": plan}, indent=2))
    return 0


def run_archive_parse(args: argparse.Namespace) -> int:
    """Run ``snowlight stations archive parse``."""
    try:
        registry = load_registry(args.registry)
        registry.check_adapters(AdapterRegistry(args.registry))
        result = archive.parse_snapshots(registry, args.artifact_dir)
        paths = fetch.write_outputs(result, args.out_dir, system_clock())
    except _FAILURES as error:
        return _fail("archive parse", error)
    counts = fetch.totals(result.health)
    followed = archive.follow_summary(result.reads)
    _print(
        f"{counts['sources']} reads: {counts['ok']} with rows, {counts['empty']} empty, "
        f"{counts['error']} without rows (see health.json); {counts['rows']} rows"
    )
    _print(
        f"{followed['followed']} pages read through the file they load "
        f"({followed['followed_with_rows']} with rows); {followed['counts_matching']} of "
        f"{followed['counts_checked']} page counts match the list read"
    )
    for line in archive.count_differences(result.reads):
        _print(line)
    if result.set_aside:
        _print(
            f"{len(result.set_aside)} captures of shared application files (not lists) set aside"
        )
    causes = archive.unread_summary(result.health)
    if causes:
        _print("without rows: " + ", ".join(f"{count} {label}" for label, count in causes.items()))
    waiting = archive.unattempted_requests(args.artifact_dir)
    if waiting:
        _print(f"{len(waiting)} requested captures were never attempted (a run ran out of time)")
    for name, path in paths.items():
        _print(f"{name}: {path}")
    for failure in result.failures:
        sys.stderr.write(f"archive parse: {failure}\n")
    return 1 if result.failures else 0


def run_fixture_add(args: argparse.Namespace) -> int:
    """Run ``snowlight stations fixture add``."""
    try:
        registry = load_registry(args.registry)
        index = archive.station_index(registry)
        matching = [
            (manifest, record)
            for manifest in archive.find_manifests(args.artifact_dir)
            for record in archive.read_manifest(manifest)
            if record.timestamp == args.timestamp and record.url == args.url
        ]
        if not matching:
            return _fail("fixture add", KeyError(f"no capture {args.timestamp} {args.url}"))
        # A request a later run asked again: use the run that downloaded it.
        manifest, record = min(matching, key=lambda item: item[1].file is None)
        if record.file is None or record.sha256 is None or record.retrieved_at is None:
            raise archive.ArchiveError(f"capture was not downloaded: {record.error}")
        original = (manifest.parent.parent / record.file).read_bytes()
        if hashlib.sha256(original).hexdigest() != record.sha256:
            raise archive.ArchiveError(f"{record.file}: SHA-256 differs from the manifest")
        station = index[archive.url_key(record.final_original or record.url)]
        stamp = record.final_timestamp or record.timestamp
        original_url = record.final_original or record.url
        origin = fixtures.Origin(
            source_id=station.id,
            adapter=registry.platform_of(station).adapter,
            mode=ReadMode.ARCHIVE,
            url=original_url,
            captured_at=iso_utc(archive.capture_time(stamp)),
            archive_url=f"https://web.archive.org/web/{stamp}id_/{original_url}",
            retrieved_at=record.retrieved_at,
        )
        entry, body = fixtures.make_entry(args.file, origin, original, args.slice, args.note)
        fixtures.write_fixtures(args.fixtures, [(entry, body)])
    except _FAILURES as error:
        return _fail("fixture add", error)
    _print(
        f"{entry.file}: {entry.expected.variant}, {entry.expected.state.value}, "
        f"{entry.expected.rows} rows"
    )
    return 0


def run_fixture_add_live(args: argparse.Namespace) -> int:
    """Run ``snowlight stations fixture add-live``.

    The body is the one the fetch kept for the URL (its conditional-request cache);
    the run manifest gives when it was read and its SHA-256, which must match.
    """
    try:
        registry = load_registry(args.registry)
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        reads = [
            snap
            for snap in manifest.get("snapshots", [])
            if snap.get("url") == args.url and snap.get("sha256")
        ]
        if not reads:
            raise KeyError(f"the run manifest has no read of {args.url}")
        read = reads[-1]
        stored = ConditionalStore(args.cache_dir).load(args.url)
        if stored is None or stored[0].sha256 != read["sha256"]:
            raise archive.ArchiveError(f"{args.url}: the cached body is not the one the run read")
        station = registry.stations[read["source_id"]]
        origin = fixtures.Origin(
            source_id=station.id,
            adapter=registry.platform_of(station).adapter,
            mode=ReadMode.LIVE,
            url=args.url,
            captured_at=read["fetched_at"],
            archive_url=None,
            retrieved_at=read["fetched_at"],
        )
        entry, body = fixtures.make_entry(args.file, origin, stored[1], args.slice, args.note)
        fixtures.write_fixtures(args.fixtures, [(entry, body)])
    except (*_FAILURES, KeyError, OSError, ValueError) as error:
        return _fail("fixture add-live", error)
    _print(
        f"{entry.file}: {entry.expected.variant}, {entry.expected.state.value}, "
        f"{entry.expected.rows} rows"
    )
    return 0


def run_coverage(args: argparse.Namespace) -> int:
    """Run ``snowlight stations coverage``."""
    now = system_clock()
    try:
        registry = load_registry(args.registry)
        health_at, health = coverage.load_health(args.health)
        states = coverage.station_states(registry, health)
        wanted = ["index", "state", "county_fips", "county_name", "district_id"]
        present = set(pl.scan_parquet(args.directory).collect_schema().names())
        # district_id (and index, for per-school weights) feed district-level sources.
        schools = pl.read_parquet(
            args.directory, columns=[name for name in wanted if name in present]
        )
        with HttpCache(make_reference_client()) as cache:
            references = _references(cache, args.reference_dir)
            weights = None if args.no_weights else _school_weights(args, cache)
        gazetteer = dma.read_gazetteer(references["gazetteer"])
        connecticut = dma.read_ct_regions(references["ct"])
        dmas = _filled(dma.read_crosswalk(references["dma"], gazetteer, connecticut), references)
        seen = observed.observe(
            observed.read_rows(args.archive_rows),
            gazetteer,
            observed.read_states(references["states"]),
            connecticut,
        )
        result = coverage.measure(registry, schools, states, dmas, seen, weights=weights)
        if not args.no_proof:
            evidence = proof.gather(
                live_reads=args.live_reads,
                archive_reads=args.archive_reads,
                archive_health=args.archive_health,
                fixtures=args.fixtures,
            )
            # A district's alert channel is proven only by a row announcing a closing,
            # a status board only by a status other than open.
            gate = notices.gate_proofs(
                evidence.proofs,
                registry,
                live_rows=[args.live_reads.with_name("rows.jsonl")],
                archive_rows=[args.archive_reads.with_name("rows.jsonl")],
                fixtures=args.fixtures,
            )
            proof.add_proven(result, registry, schools, states, evidence, weights=weights)
            result["district_notice_gate"] = gate
            notices.annotate_unproven(result, gate)
        shapes = None if args.no_png else coverage.county_shapes(references["shapes"])
        meta = coverage.CoverageMeta(now, health_at, args.directory, _provenance(references))
        paths = coverage.write_coverage(args.out_dir, result, meta, shapes)
    except _FAILURES as error:
        return _fail("coverage", error)
    national = result["national"]
    if isinstance(national, dict):
        _print(
            f"national: {national['covered']} of {national['schools']} schools covered by a "
            f"working source ({national['share']:.1%})"
        )
        weighted = national.get("weighted")
        if isinstance(weighted, dict):
            _print(f"national, closure-weighted: {weighted['share']:.1%}")
    line = proof.summary_line(result)
    if line is not None:
        _print(line)
    for name, path in paths.items():
        _print(f"{name}: {path}")
    return 0


def _school_weights(args: argparse.Namespace, cache: HttpCache) -> coverage.Weights:
    """Read the closure weights and give every school its own NWS county's weight.

    Schools are placed in NWS counties the way the weights build places them
    (:func:`snowlight.weights.schools.place_schools`, with the build's cached NWS
    county list), so a Connecticut school, whose directory county is a planning
    region, counts the weight of the county it stands in.
    """
    weights = coverage.load_weights(args.weights)
    nws_counties = weights_zones.load_counties(WeightsCache(cache))
    placement = weights_schools.place_schools(
        weights_schools.read_schools(args.directory), nws_counties
    )
    return weights.placed(placement)


def _filled(
    markets: dma.DmaCounties,
    references: dict[str, Path],
    gazetteer: list[dma.GazetteerCounty] | None = None,
) -> dma.DmaCounties:
    """Place the counties the crosswalk lacks with the second DMA list, when it was read."""
    if "supplement" not in references:
        return markets
    counties = gazetteer if gazetteer is not None else dma.read_gazetteer(references["gazetteer"])
    return dma.fill_missing(markets, dma.read_supplement(references["supplement"]), counties)


def _references(cache: HttpCache, root: Path) -> dict[str, Path]:
    """Download (or reuse) the reference files coverage needs, checksummed."""
    urls = {
        "dma": dma.DMA_CROSSWALK_URL,
        "supplement": dma.DMA_SUPPLEMENT_URL,
        "gazetteer": dma.COUNTY_GAZETTEER_URL,
        "ct": dma.CT_CROSSWALK_URL,
        "shapes": COUNTY_SHAPES_URL,
        "states": observed.STATE_CODES_URL,
    }
    paths: dict[str, Path] = {}
    for key, url in urls.items():
        relative = url.split("://", 1)[1]
        cached = cache.fetch(url, root / relative)
        pinned = {"dma": dma.DMA_CROSSWALK_SHA256, "supplement": dma.DMA_SUPPLEMENT_SHA256}
        if key in pinned and cached.provenance.sha256 != pinned[key]:
            raise dma.DmaError(f"{url}: SHA-256 {cached.provenance.sha256} is not the pinned one")
        paths[key] = cached.path
    return paths


def _provenance(paths: dict[str, Path]) -> dict[str, JSONValue]:
    """Return each reference file's provenance sidecar (URL, SHA-256, retrieval time)."""
    records: dict[str, JSONValue] = {}
    for key, path in paths.items():
        sidecar = path.with_name(path.name + SIDECAR_SUFFIX)
        records[key] = (
            json.loads(sidecar.read_text(encoding="utf-8"))
            if sidecar.is_file()
            else {"path": path.name, "sha256": sha256_file(path)}
        )
    return records
