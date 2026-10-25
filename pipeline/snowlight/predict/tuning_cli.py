"""``snowlight predict label-audit`` and the tuning candidates' input builds (internal).

The calc-research plan (T1, T2) asks for checks on today's labels and for new inputs, as known
at 21:00 the evening before, for the candidates the tune lane will test. Every command here
writes only under its ``--out`` folder (gitignored ``out/internal`` by default) or the
gitignored ``.cache``; nothing here changes what the site serves.

* ``label-audit``: rebuild each fold's training labels with the station audiences, the
  station gates and the markets made from the seasons before its test season only, and count
  how many change (:func:`snowlight.predict.train.label_audit`).
* ``alert-streams``: fetch IEM's VTEC event records of the class-making events the label
  dates' snapshots can know of, one a second, into the gitignored cache, keeping the cached
  records within the cap (``--cap``, 100 MB by default; :mod:`snowlight.predict.alert_streams`).
* ``alert-classes``: every district's class on the label dates by the history's rule and by
  the product streams as of 21:00 (the T2 sentinel's count of later products that moved a
  start across 09:00, and the classes of the known labels that change), with the streams'
  parsed alert inputs per district-day (start, end, type flags, elevation band; no text).
* ``morning-obs``: the label dates' 5 AM airport reports at each labeled district's nearest
  ASOS station (:mod:`snowlight.predict.morning_obs`), one request a second, cached.
* ``night-extract``: the label-night forecast extract (:mod:`snowlight.predict.night_extract`),
  run on GitHub's runners by ``.github/workflows/label-night-forecast-extract.yml``.
"""

import argparse
import hashlib
import json
import os
import sys
import time
from collections.abc import Mapping
from datetime import date, timedelta
from pathlib import Path
from typing import Final

import polars as pl

from snowlight.output import JSONValue, write_json
from snowlight.predict import alert_streams, morning_obs, night_extract, train
from snowlight.predict.alerts_history import HistoryRow, read_season
from snowlight.predict.calendar import season_of
from snowlight.predict.config import PIPELINE_ROOT, PredictConfig
from snowlight.predict.labels import KNOWN_OUTCOMES
from snowlight.predict.situations import Window

SEASON_FILES: Final = (
    PIPELINE_ROOT / ".cache" / "weights" / "mesonet.agron.iastate.edu" / "watchwarn-csv"
)
AUDIT_LIMIT: Final = 0.01
"""A fold whose training labels change more than this share is rebuilt per fold (plan T1)."""


def register(actions: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register the commands of this module."""
    audit = actions.add_parser(
        "label-audit", help="training labels rebuilt from each fold's own seasons (internal)"
    )
    paths = train.TrainPaths()
    audit.add_argument("--archive", type=Path, default=paths.archive)
    audit.add_argument("--registry", type=Path, default=paths.registry)
    audit.add_argument("--directory", type=Path, default=paths.directory)
    audit.add_argument("--aliases", type=Path, default=paths.aliases)
    audit.add_argument("--weather-cache", type=Path, default=paths.weather_cache)
    audit.add_argument(
        "--work", type=Path, default=paths.out, help="a labels folder (its weather history)"
    )
    audit.add_argument("--out", type=Path, default=paths.out / "audit")
    audit.add_argument(
        "--folds",
        type=Path,
        default=None,
        help="where the fold label files go (default: the labels folder's folds/)",
    )
    audit.add_argument("--workers", type=int, default=4)
    audit.set_defaults(handler=run_label_audit)

    streams = actions.add_parser(
        "alert-streams", help="the label dates' alert product streams from IEM (internal)"
    )
    streams.add_argument("--work", type=Path, default=paths.out, help="a labels folder")
    streams.add_argument("--seasons", type=Path, default=SEASON_FILES, help="IEM season files")
    streams.add_argument("--cache", type=Path, default=alert_streams.CACHE)
    streams.add_argument("--cap", type=int, default=alert_streams.BYTE_CAP, help="bytes")
    streams.add_argument("--out", type=Path, default=paths.out / "streams")
    streams.add_argument("--fetch", action="store_true", help="fetch what the cache lacks")
    streams.set_defaults(handler=run_alert_streams)

    classes = actions.add_parser(
        "alert-classes", help="label dates' classes from the streams vs the history (internal)"
    )
    classes.add_argument("--work", type=Path, default=paths.out, help="a labels folder")
    classes.add_argument("--directory", type=Path, default=paths.directory)
    classes.add_argument("--weights-cache", type=Path, default=paths.weights_cache)
    classes.add_argument("--cache", type=Path, default=alert_streams.CACHE)
    classes.add_argument("--out", type=Path, default=paths.out / "streams")
    classes.set_defaults(handler=run_alert_classes)

    morning = actions.add_parser("morning-obs", help="label dates' 5 AM airport reports")
    morning.add_argument("--work", type=Path, default=paths.out, help="a labels folder")
    morning.add_argument("--directory", type=Path, default=paths.directory)
    morning.add_argument("--cache", type=Path, default=morning_obs.CACHE)
    morning.add_argument("--out", type=Path, default=paths.out / "morning")
    morning.set_defaults(handler=run_morning_obs)

    extract = actions.add_parser(
        "night-extract", help="the label-night forecast extract (GitHub's runners)"
    )
    extract.add_argument("--nights", type=Path, default=night_extract.NIGHTS_PATH)
    extract.add_argument("--site", default="https://snowlightmap.com")
    extract.add_argument(
        "--repository", default=os.environ.get("GITHUB_REPOSITORY", "viaate/jsalcards")
    )
    extract.add_argument("--site-data", type=Path, default=None, help="meta.json, points.bin")
    extract.add_argument("--model", type=Path, default=None)
    extract.add_argument(
        "--only", type=date.fromisoformat, action="append", help="only these days (a dry run)"
    )
    extract.add_argument("--workers", type=int, default=4)
    extract.add_argument("--out", type=Path, required=True)
    extract.set_defaults(handler=run_night_extract)


def run_label_audit(args: argparse.Namespace) -> int:  # pragma: no cover - the real archive
    """Run ``predict label-audit``."""
    config = PredictConfig.load(args.config)
    paths = train.TrainPaths(
        archive=args.archive,
        registry=args.registry,
        directory=args.directory,
        aliases=args.aliases,
        weather_cache=args.weather_cache,
        out=args.work,
    )
    schools = pl.read_parquet(paths.directory / "schools.parquet")
    table = pl.read_parquet(args.work / "districts.parquet")
    weather = pl.read_parquet(args.work / "weather.parquet")
    private = pl.read_parquet(args.work / "private.parquet")
    zone_of = {
        d: z for d, z in zip(table["district"], table["time_zone"], strict=True) if z is not None
    }
    zone_of_private = {
        s: z for s, z in zip(private["district"], private["time_zone"], strict=True) if z
    }
    run = train.prepare_archive(paths, zone_of, args.workers, zone_of_private)
    whole = train.run_labels(run, schools, table, weather, config)
    kept = pl.read_parquet(args.work / "labels.parquet")
    same = whole.select(kept.columns).sort("district", "day").equals(kept.sort("district", "day"))
    print(f"whole-archive labels: {whole.height:,} rows, same as {args.work}: {same}")  # noqa: T201
    seasons = sorted(set(whole["season"].to_list()))[1:]
    folds = train.fold_labels(run, schools, table, weather, config, seasons)
    private_weather = pl.read_parquet(args.work / "weather-private.parquet")
    private_folds = train.private_fold_labels(run, private, private_weather, folds, config)
    write_fold_labels(args.folds or args.work / train.FOLDS, folds, private_folds)
    found = train.label_audit(whole, folds)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "label-audit.md").write_text(
        train.label_audit_markdown(found, AUDIT_LIMIT), encoding="utf-8"
    )
    write_json(
        args.out / "label-audit.json",
        {
            "same_as_work": same,
            "limit": AUDIT_LIMIT,
            "folds": [
                {
                    "season": item.season,
                    "training": item.changes.training,
                    "changed": item.changes.changed,
                    "added": item.changes.added,
                    "share": round(item.changes.share, 6),
                    "pairs": {f"{a}->{b}": n for (a, b), n in sorted(item.changes.pairs.items())},
                }
                for item in found
            ],
        },
    )
    worst = max((item.changes.share for item in found), default=0.0)
    print(json.dumps({"folds": len(found), "worst_share": round(worst, 6)}))  # noqa: T201
    return 0


def write_fold_labels(
    folder: Path, folds: Mapping[int, pl.DataFrame], private: Mapping[int, pl.DataFrame]
) -> None:  # pragma: no cover - the real archive
    """Write each test season's fold labels (districts and private schools) and a manifest
    of their rows and SHA-256s to ``folder`` (gitignored, like the labels folder)."""
    folder.mkdir(parents=True, exist_ok=True)
    files: dict[str, JSONValue] = {}
    for season in sorted(folds):
        for frame, is_private in ((folds[season], False), (private.get(season), True)):
            if frame is None:
                continue
            path = train.fold_label_path(folder, season, private=is_private)
            frame.write_parquet(path)
            known = int(frame["outcome"].is_in(sorted(KNOWN_OUTCOMES)).sum())
            files[path.name] = {
                "season": season,
                "rows": frame.height,
                "known": known,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
    write_json(folder / "manifest.json", {"files": files})


def label_dates(labels: pl.DataFrame) -> list[date]:
    """The days with a known label."""
    known = labels.filter(pl.col("outcome").is_in(sorted(KNOWN_OUTCOMES)))
    return sorted(set(known["day"].to_list()))


def season_rows(folder: Path, days: list[date]) -> list[HistoryRow]:
    """The class-making zone rows of the season files of ``days``."""
    rows: list[HistoryRow] = []
    for season in sorted({season_of(day) for day in days}):
        path = folder / f"{season}-{season + 1}.csv"
        rows.extend(read_season(path.read_text(encoding="utf-8"), season))
    return rows


def run_alert_streams(args: argparse.Namespace) -> int:  # pragma: no cover - IEM
    """Run ``predict alert-streams``."""
    from snowlight.predict.inputs import client  # noqa: PLC0415

    days = label_dates(pl.read_parquet(args.work / "labels.parquet"))
    keys = alert_streams.event_keys(season_rows(args.seasons, days), days)
    print(f"label dates: {len(days)}, events: {len(keys):,}")  # noqa: T201
    report: alert_streams.FetchReport | None = None
    if args.fetch:
        with client() as http:

            def get(query: Mapping[str, str]) -> bytes:
                response = http.get(alert_streams.EVENT_URL, params=dict(query))
                response.raise_for_status()
                return response.content

            report = alert_streams.fetch_events(keys, args.cache, get, cap=args.cap)
    cached = [key for key in keys if key.path(args.cache).exists()]
    args.out.mkdir(parents=True, exist_ok=True)
    write_json(
        args.out / "fetch.json",
        {
            "label_dates": len(days),
            "events": len(keys),
            "cached": len(cached),
            "fetch": None
            if report is None
            else {
                "requests": report.requested,
                "already_cached": report.cached,
                "bytes_fetched": report.bytes_fetched,
                "bytes_cached": report.bytes_cached,
                "bytes_dropped": report.bytes_dropped,
                "stopped_at_cap": report.stopped_at_cap,
                "missing": len(report.missing),
                "errors": list(report.errors),
            },
        },
    )
    if report is not None and report.stopped_at_cap:
        print(f"stopped at the cap: {len(report.missing):,} records not fetched")  # noqa: T201
        return 3
    return 0


def run_alert_classes(args: argparse.Namespace) -> int:  # pragma: no cover - the cached files
    """Run ``predict alert-classes``."""
    config = PredictConfig.load(args.config)
    weather = config.weather
    window = Window(weather.window_from, weather.window_until, weather.snapshot_hour)
    labels = pl.read_parquet(args.work / "labels.parquet")
    days = label_dates(labels)
    schools = pl.read_parquet(args.directory / "schools.parquet")
    paths = train.TrainPaths(directory=args.directory, weights_cache=args.weights_cache)
    seasons = sorted({season_of(day) for day in days})
    places = train.history_places(paths, schools, seasons)
    district_of_school, _private, zone_by_index = train.school_zones(places, schools)
    rows = [
        row
        for season, path in sorted(places.files.items())
        for row in read_season(path.read_text(encoding="utf-8"), season)
    ]
    keys = set(alert_streams.event_keys(rows, days))
    streams: dict[alert_streams.EventKey, tuple[alert_streams.Product, ...]] = {}
    for key in sorted(keys):
        found = alert_streams.read_cached(key, args.cache)
        if found is not None:
            streams[key] = found
    print(f"events {len(keys):,}, streams cached {len(streams):,}")  # noqa: T201
    frame = alert_streams.school_row_days(
        (row for row in rows if alert_streams.parse_key(row.event_key) in keys),
        places.reach,
        zone_by_index,
        window,
        streams,
        days,
    )
    districts = alert_streams.district_row_days(frame, district_of_school, weather.covered_share)
    args.out.mkdir(parents=True, exist_ok=True)
    districts.write_parquet(args.out / "alert-inputs.parquet")
    report = alert_streams.label_class_report(
        labels, pl.read_parquet(args.work / "weather.parquet"), districts, frame, days
    )
    write_json(args.out / "classes.json", json.loads(json.dumps(report)))
    print(json.dumps(report["summary"]))  # noqa: T201
    return 0


def run_night_extract(args: argparse.Namespace) -> int:  # pragma: no cover - the network
    """Run ``predict night-extract``: every night's files and values, the manifest."""
    from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415

    from snowlight.predict import artifact as artifact_module  # noqa: PLC0415
    from snowlight.predict import forecast_history as history  # noqa: PLC0415
    from snowlight.predict.inputs import client, read_deployed_meta, read_local  # noqa: PLC0415

    config = PredictConfig.load(args.config)
    nights = night_extract.load_nights(args.nights.read_text(encoding="utf-8"))
    if args.only:
        nights = [night for night in nights if night.day in set(args.only)]
    model = artifact_module.load(args.model or artifact_module.ARTIFACT_PATH)
    if args.site_data is not None:
        directory = read_local(args.site_data)
    else:
        token = os.environ.get("GITHUB_TOKEN")
        directory = read_deployed_meta(args.site, args.repository, token)[0]
    schools = history.deciding_schools(directory, model)
    started = time.monotonic()
    values: list[pl.DataFrame] = []
    weather: list[pl.DataFrame] = []
    runs: list[dict[str, object]] = []
    errors: dict[str, list[str]] = {}
    with client() as http:
        fetcher = history.Fetcher(http)
        days = sorted({d for night in nights for d in (night.day - timedelta(days=1), night.day)})
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            listed = dict(
                zip(
                    days,
                    pool.map(lambda d: night_extract.list_extract_day(fetcher.get, d), days),
                    strict=True,
                )
            )

        def one(night: night_extract.Night) -> night_extract.NightValues:
            files = [*listed[night.day - timedelta(days=1)], *listed[night.day]]
            return night_extract.extract_night(
                night, schools, files, fetcher.opener(), config.weather.covered_share
            )

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for night, found in zip(nights, pool.map(one, nights), strict=True):
                runs.extend(found.runs)
                if found.values is not None:
                    values.append(found.values)
                if found.wx is not None:
                    weather.append(found.wx)
                if found.errors:
                    errors[f"{night.day} {night.zone}"] = found.errors
                sys.stdout.write(
                    f"{night.day} {night.zone}: {len(found.runs)} files, "
                    f"{0 if found.values is None else found.values.height} districts, "
                    f"errors {found.errors or 'none'}, MB {fetcher.bytes / 1e6:.0f}\n"
                )
                sys.stdout.flush()
    args.out.mkdir(parents=True, exist_ok=True)
    run_frame = night_extract.runs_frame(runs)
    late = night_extract.check_runs(run_frame)
    paths = [
        night_extract.write_frames(args.out, "values.parquet", values),
        night_extract.write_frames(args.out, "wx.parquet", weather),
        night_extract.write_frames(args.out, "runs.parquet", [run_frame]),
    ]
    value_frame = pl.read_parquet(paths[0])
    manifest = {
        "name": "label-night forecast extract",
        "nights": len(nights),
        "districts_per_night": {
            f"{d} {z}": n
            for d, z, n in value_frame.group_by("day", "zone").len().sort("day", "zone").iter_rows()
        },
        "rows_per_element_and_night": night_extract.row_counts(value_frame),
        "files": {
            path.name: {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size,
                "rows": pl.read_parquet(path).height,
            }
            for path in paths
        },
        "bytes_kept": sum(path.stat().st_size for path in paths),
        "bytes_streamed": fetcher.bytes,
        "requests": fetcher.requests,
        "seconds": round(time.monotonic() - started, 1),
        "errors": errors,
        "late": late,
    }
    write_json(args.out / "manifest.json", json.loads(json.dumps(manifest, default=str)))
    sys.stdout.write(
        json.dumps(
            {
                k: manifest[k]
                for k in ("nights", "bytes_kept", "bytes_streamed", "requests", "seconds")
            }
        )
        + "\n"
    )
    if late:
        sys.stderr.write(f"files that count after their snapshot: {late}\n")
        return 1
    return 0


def run_morning_obs(args: argparse.Namespace) -> int:  # pragma: no cover - IEM
    """Run ``predict morning-obs``."""
    from snowlight.predict.inputs import client  # noqa: PLC0415
    from snowlight.weather.hazards import CONUS_STATES  # noqa: PLC0415

    labels = pl.read_parquet(args.work / "labels.parquet")
    table = pl.read_parquet(args.work / "districts.parquet")
    points = morning_obs.district_points(pl.read_parquet(args.directory / "schools.parquet"))
    requests = 0
    fetched = 0
    first = True

    def pause() -> None:
        nonlocal first
        if not first:
            time.sleep(1.0)
        first = False

    with client() as http:

        def get(url: str) -> bytes:
            nonlocal requests, fetched
            response = http.get(url)
            response.raise_for_status()
            requests += 1
            fetched += len(response.content)
            return response.content

        stations: dict[str, list[morning_obs.Station]] = {}
        for state in sorted(CONUS_STATES):
            url = morning_obs.NETWORK_URL.format(state=state)
            body, _new = morning_obs.cached_get(
                url, args.cache / "networks" / f"{state}.geojson", get, pause
            )
            stations[state] = morning_obs.parse_network(body, state)
        rows = morning_obs.label_rows(labels, table, points, stations)
        reports: list[pl.DataFrame] = []
        for (day,), part in rows.filter(pl.col("station").is_not_null()).group_by("day"):
            query = morning_obs.asos_query(part["station"].to_list(), day)
            body, _new = morning_obs.cached_get(
                f"{morning_obs.ASOS_URL}?{query}", args.cache / "reports" / f"{day}.csv", get, pause
            )
            reports.append(morning_obs.parse_asos(body.decode("utf-8")))
    every = pl.concat(reports) if reports else pl.DataFrame(schema=morning_obs.OBS_SCHEMA)
    found: list[dict[str, object]] = []
    for row in rows.iter_rows(named=True):
        report = None
        if row["station"] is not None:
            report = morning_obs.morning_report(every, row["station"], row["day"], row["time_zone"])
        found.append({**row, **(report or {})})
    frame = pl.DataFrame(found, infer_schema_length=None)
    args.out.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(args.out / "morning-obs.parquet")
    summary = {
        "label_rows": frame.height,
        "with_station": int(frame["station"].is_not_null().sum()),
        "with_report": int(frame["valid"].is_not_null().sum()) if "valid" in frame.columns else 0,
        "stations": int(frame["station"].n_unique()),
        "requests": requests,
        "bytes_fetched": fetched,
    }
    write_json(args.out / "morning-obs.json", json.loads(json.dumps(summary)))
    print(json.dumps(summary))  # noqa: T201
    return 0
