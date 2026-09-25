"""The ``snowlight alerts`` command.

Actions:

* ``live``: fetch the active NWS alerts and write ``live/alerts.json`` plus its
  internal manifest;
* ``backfill``: cache the archive files (day files, snapshots and range files)
  and boundary releases for a range of local dates, so later checks run offline;
* ``check``: print, one JSON object per line, the alerts that covered (or, near
  a simplified archive boundary, may have covered) a place during a local
  window (``--live`` for the active alerts, otherwise the archive);
* ``schools``: run the check for every school in a directory table and write
  the matches to an internal parquet file.

Without ``--date``, the date is today in each place's own time zone (in the
evening, the UTC date is already tomorrow's).
"""

import argparse
import json
import re
import sys
import time as clock
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from snowlight.output import JSONValue, write_json
from snowlight.sources.nws.alerts import AlertFormatError
from snowlight.sources.nws.boundaries import BoundaryCatalog, BoundaryError, BoundarySet
from snowlight.sources.nws.http import FetchError, HttpCache, iso_utc, make_client, sha256_file
from snowlight.sources.nws.iem import ArchiveFormatError
from snowlight.weather.build import (
    DEFAULT_CACHE_DIR,
    DEFAULT_MANIFEST,
    DEFAULT_OUT_DIR,
    PIPELINE_ROOT,
    WeatherBuildError,
    ZoneFootprint,
    archive_window,
    backfill,
    build_live,
    check_places,
    check_schools,
    live_sources,
    make_archive,
)
from snowlight.weather.history import DEFAULT_LOOKBACK, WarningHistory
from snowlight.weather.index import WeatherIndex
from snowlight.weather.publish import DEFAULT_MAX_BYTES, BudgetError, PublishedContentError
from snowlight.weather.timezones import (
    IANA_ZONES,
    LocalWindow,
    TimeZoneLookup,
    TodayWindow,
    Window,
)

_FAILURES = (
    AlertFormatError,
    ArchiveFormatError,
    BoundaryError,
    BudgetError,
    FetchError,
    PublishedContentError,
    WeatherBuildError,
)
DEFAULT_SCHOOLS = PIPELINE_ROOT / "out" / "internal" / "directory" / "schools.parquet"
DEFAULT_MATCHES = PIPELINE_ROOT / "out" / "internal" / "weather" / "matches.parquet"
MATCHES_MANIFEST_SCHEMA = 1


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {value!r}") from error


def _clock(value: str) -> time:
    if not re.fullmatch(r"\d{2}:\d{2}", value):
        raise argparse.ArgumentTypeError(f"expected HH:MM, got {value!r}")
    try:
        return time.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"expected HH:MM, got {value!r}") from error


def _fips(value: str) -> str:
    if not re.fullmatch(r"\d{5}", value):
        raise argparse.ArgumentTypeError(f"expected a five-digit county FIPS code, got {value!r}")
    return value


def _add_cache(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR, help="download cache")


def _add_window(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--live", action="store_true", help="check the active alerts")
    parser.add_argument(
        "--date", type=_date, help="local date (default: today in the place's time zone)"
    )
    parser.add_argument("--from", dest="start", type=_clock, default=time(0), help="local HH:MM")
    parser.add_argument(
        "--to",
        dest="end",
        type=_clock,
        default=time(0),
        help="local HH:MM, exclusive (not after --from means the next day)",
    )


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register ``alerts`` and its actions on ``subparsers``."""
    alerts = subparsers.add_parser(
        "alerts",
        help="weather alerts: live map layer and the weather-reason check",
        description="NWS weather alerts relevant to school closures.",
    )
    actions = alerts.add_subparsers(dest="alerts_action", metavar="ACTION", required=True)

    live = actions.add_parser("live", help="fetch active alerts and write live/alerts.json")
    _add_cache(live)
    live.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="site data root; the file goes to <out-dir>/live/alerts.json",
    )
    live.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST, help="internal manifest")
    live.add_argument(
        "--max-bytes", type=int, default=DEFAULT_MAX_BYTES, help="size budget of alerts.json"
    )
    live.set_defaults(handler=run_live)

    fill = actions.add_parser("backfill", help="cache archive day files for local dates")
    _add_cache(fill)
    fill.add_argument("--start", type=_date, required=True, help="first local date")
    fill.add_argument("--end", type=_date, required=True, help="last local date")
    fill.add_argument(
        "--lookback-days",
        type=int,
        default=DEFAULT_LOOKBACK.days,
        help="days of day files before each date (older events come from snapshots)",
    )
    fill.set_defaults(handler=run_backfill)

    check = actions.add_parser("check", help="alerts covering one place in a local window")
    _add_cache(check)
    check.add_argument("--lat", type=float, help="latitude")
    check.add_argument("--lon", type=float, help="longitude")
    check.add_argument("--county", type=_fips, help="five-digit county FIPS code")
    check.add_argument("--tz", help="IANA time zone (default: from the NWS boundary files)")
    _add_window(check)
    check.set_defaults(handler=run_check)

    schools = actions.add_parser("schools", help="check every school for one local date")
    _add_cache(schools)
    schools.add_argument(
        "--schools", type=Path, default=DEFAULT_SCHOOLS, help="directory schools.parquet"
    )
    schools.add_argument("--out", type=Path, default=DEFAULT_MATCHES, help="matches parquet")
    _add_window(schools)
    schools.set_defaults(handler=run_schools)


def _cache() -> HttpCache:
    return HttpCache(make_client())


def run_live(args: argparse.Namespace) -> int:
    """Run ``snowlight alerts live``."""
    try:
        with _cache() as cache:
            result = build_live(
                cache,
                cache_dir=args.cache_dir,
                out_dir=args.out_dir,
                manifest_path=args.manifest,
                max_bytes=args.max_bytes,
            )
    except _FAILURES as error:
        sys.stderr.write(f"snowlight alerts live: error: {error}\n")
        return 1
    reasons = ", ".join(f"{reason}: {count}" for reason, count in result.dropped.items())
    sys.stdout.write(
        f"feed: {result.features} alerts{' (not modified)' if result.not_modified else ''}\n"
        f"kept {result.kept}; dropped {sum(result.dropped.values())} ({reasons or 'none'})\n"
        f"wrote {result.published} entries, {result.size} bytes "
        f"(tolerance {result.tolerance} deg) to {result.path}\n"
        f"manifest: {result.manifest}\n"
    )
    return 0


def run_backfill(args: argparse.Namespace) -> int:
    """Run ``snowlight alerts backfill``."""
    try:
        with _cache() as cache:
            result = backfill(
                cache,
                args.start,
                args.end,
                cache_dir=args.cache_dir,
                lookback=timedelta(days=args.lookback_days),
            )
    except (*_FAILURES, ValueError) as error:
        sys.stderr.write(f"snowlight alerts backfill: error: {error}\n")
        return 1
    sys.stdout.write(
        f"{result.days} day files ({result.downloaded} downloaded, {result.final} final), "
        f"{result.rows} rows; {result.snapshots} snapshots; {result.ranges} range files for "
        f"{result.carried} events in effect since before their day files\n"
    )
    return 0


def _boundaries(catalog: BoundaryCatalog, day: date) -> tuple[BoundarySet, BoundarySet]:
    # Time zone codes come from the release in effect, or the earliest one served.
    sets = []
    for kind in ("county", "zone"):
        release = catalog.release_for(kind, day) or catalog.releases(kind)[0]
        sets.append(catalog.load(release))
    return sets[0], sets[1]


def _history(cache: HttpCache, cache_dir: Path) -> WarningHistory:
    return WarningHistory(make_archive(cache, cache_dir), BoundaryCatalog(cache, cache_dir))


def _index(
    args: argparse.Namespace, cache: HttpCache, window: Window, history: WarningHistory | None
) -> tuple[WeatherIndex, dict[str, JSONValue]]:
    """The index to check against, and the provenance of what it was built from.

    The archive is read for :func:`~snowlight.weather.build.archive_window`, so
    ``check`` and ``schools`` read the same files for the same window.
    """
    if history is None:
        index, provenance = live_sources(cache, args.cache_dir)
        return index, {"source": "live", **provenance}
    index = history.index(*archive_window(window))
    return index, {"source": "archive", **history.provenance()}


def _notes(history: WarningHistory | None) -> str:
    """One line on the archive rows skipped, the approximate outlines and the carried events."""
    if history is None:
        return ""
    counts = {**history.skipped, **history.outlines}
    counts["events read from range files"] = len(history.carried) - len(history.missing)
    return "archive: " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) + "\n"


def run_check(args: argparse.Namespace) -> int:
    """Run ``snowlight alerts check``."""
    if (args.lat is None) != (args.lon is None) or (args.lat is None and args.county is None):
        sys.stderr.write("snowlight alerts check: error: give --lat and --lon, or --county\n")
        return 2
    place = pl.DataFrame(
        {"county_fips": [args.county], "lat": [args.lat], "lon": [args.lon]},
        schema={"county_fips": pl.String(), "lat": pl.Float64(), "lon": pl.Float64()},
    )
    try:
        with _cache() as cache:
            window, first_day, _last_day, _label = _school_window(args, cache.now())
            counties, zones = _boundaries(BoundaryCatalog(cache, args.cache_dir), first_day)
            options: tuple[str, ...] = (args.tz,) if args.tz else ()
            if not options:
                lookup = TimeZoneLookup(counties, zones)
                options = lookup.zones_for(args.county, args.lat, args.lon)
            if not options:
                sys.stderr.write("snowlight alerts check: error: time zone unknown; pass --tz\n")
                return 1
            spans = [window.utc(zone) for zone in options]
            start, end = min(s for s, _ in spans), max(e for _, e in spans)
            history = None if args.live else _history(cache, args.cache_dir)
            index, _sources = _index(args, cache, window, history)
            stand_ins = ZoneFootprint(zones).stand_ins(
                place["lat"].fill_null(np.nan).to_numpy(), place["lon"].fill_null(np.nan).to_numpy()
            )
            matches = check_places(index, place, [options], window, stand_ins)
    except (*_FAILURES, ValueError) as error:
        sys.stderr.write(f"snowlight alerts check: error: {error}\n")
        return 1
    for row in matches.drop("place").iter_rows(named=True):
        record = {
            **row,
            "start": iso_utc(row["start"]),
            "end": None if row["end"] is None else iso_utc(row["end"]),
        }
        sys.stdout.write(json.dumps(record, sort_keys=True) + "\n")
    uncertain = matches.filter(pl.col("coverage") == "uncertain").height
    local = ", ".join(options)
    sys.stderr.write(
        f"{matches.height - uncertain} alerts covered the place, {uncertain} uncertain; "
        f"window {iso_utc(start)} to {iso_utc(end)} ({local})\n{_notes(history)}"
    )
    if args.lat is None:
        sys.stderr.write(
            "no point given: zone-based alerts are not checked (a zone is not a county), and a "
            "storm-based warning's county list only makes the place uncertain\n"
        )
    return 0


def _school_window(args: argparse.Namespace, now: datetime) -> tuple[Window, date, date, str]:
    """The window for ``schools``, the first and last local dates it can fall on, and a label."""
    if args.date is not None:
        return LocalWindow(args.date, args.start, args.end), args.date, args.date, str(args.date)
    window = TodayWindow(now, args.start, args.end)
    days = sorted({window.day_in(zone) for zone in IANA_ZONES.values()})
    return window, days[0], days[-1], "today in each school's time zone"


def run_schools(args: argparse.Namespace) -> int:
    """Run ``snowlight alerts schools``."""
    try:
        schools = pl.read_parquet(args.schools, columns=["id", "county_fips", "lat", "lon"])
        with _cache() as cache:
            now = cache.now()
            window, first_day, _last_day, label = _school_window(args, now)
            counties, zones = _boundaries(BoundaryCatalog(cache, args.cache_dir), first_day)
            lookup = TimeZoneLookup(counties, zones)
            history = None if args.live else _history(cache, args.cache_dir)
            index, sources = _index(args, cache, window, history)
            began = clock.perf_counter()
            matches, unchecked = check_schools(index, schools, lookup, window, ZoneFootprint(zones))
            elapsed = clock.perf_counter() - began
    except (*_FAILURES, OSError, ValueError, pl.exceptions.PolarsError) as error:
        sys.stderr.write(f"snowlight alerts schools: error: {error}\n")
        return 1
    covered = matches.filter(pl.col("coverage") == "covered")
    uncertain = matches.filter(~pl.col("id").is_in(covered["id"].implode()))
    counts: dict[str, JSONValue] = {
        "schools": schools.height,
        "unchecked": len(unchecked),
        "rows": matches.height,
        "covered_schools": covered["id"].n_unique(),
        "uncertain_only_schools": uncertain["id"].n_unique(),
        "alerts": matches["key"].n_unique(),
    }
    manifest: dict[str, JSONValue] = {
        "schema": MATCHES_MANIFEST_SCHEMA,
        "generated_at": iso_utc(now),
        "output": {"path": str(args.out), "sha256": ""},
        "window": {
            "date": None if args.date is None else args.date.isoformat(),
            "label": label,
            "from": args.start.strftime("%H:%M"),
            "to": args.end.strftime("%H:%M"),
        },
        "counts": counts,
        "unchecked_ids": list(unchecked),
        "sources": sources,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    matches.write_parquet(args.out)
    manifest["output"] = {"path": args.out.name, "sha256": sha256_file(args.out)}
    manifest_path = args.out.with_suffix(".json")
    write_json(manifest_path, manifest)
    sys.stdout.write(
        f"{schools.height} schools checked for {label} in {elapsed:.2f} s against "
        f"{len(index)} areas; {counts['covered_schools']} covered by "
        f"{covered['key'].n_unique()} alerts; {counts['uncertain_only_schools']} more "
        f"uncertain (near a simplified archive boundary, outside every NWS zone or between "
        f"time zones); "
        f"{len(unchecked)} skipped (time zone unknown); wrote {args.out} and {manifest_path.name}"
        f"\n{_notes(history)}"
    )
    return 0
