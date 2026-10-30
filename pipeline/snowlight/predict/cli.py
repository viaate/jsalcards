"""``snowlight predict``: the snow-day chance model's commands (docs/predict.md).

* ``predict labels``: the weather history and the labels from the archive (internal).
* ``predict train``: fit the model on every labeled season; write ``model.json.gz``.
* ``predict backtest``: the walk-forward backtest and its gates (internal report).
* ``predict once``: one serving pass; publishes as ``PREDICT_PUBLISH`` says.
* ``predict run --until +330m``: passes on the grid (the heartbeat) and whenever the
  alerts change (checked every ``check_minutes``, at most one extra pass per
  ``min_gap_minutes``), until then.
* ``predict blank``: set the hold and upload a valid file with no districts at once (an
  immediate dark that stays dark: every pass's upload is refused while the hold is set).
* ``predict release``: clear the hold.
* ``predict check --url URL --max-age 45m``: the watchdog.
* ``predict learn``: label the new live-read days and swap in a refit only when the
  walk-forward check finds it no worse (:mod:`snowlight.predict.learn`); exit 4 when it kept
  the model served because the refit was worse.

Exit codes: 0 published (or nothing to change), 3 dark (the gate refused: nothing
uploaded), 1 an error. Secrets come from the environment only: ``LIVE_HOST_TOKEN`` (a
token that may write the live host's repository), ``GITHUB_TOKEN`` (reads the site's
deployments), ``PREDICT_PUBLISH`` (``on``, ``shadow`` or ``off``, the default).
"""

import argparse
import json
import logging
import math
import os
import re
import sqlite3
import sys
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import httpx
import numpy as np
import numpy.typing as npt
import polars as pl

from snowlight.elevation.pins import DEFAULT_PINS_PATH, load_pins
from snowlight.live.kept import (
    PredictKept,
    contents_of,
    fold_predict,
    predict_verdict,
    snapshot_finished,
)
from snowlight.live.publish import LiveHold
from snowlight.live.publishers import DirPublisher, GitHubPublisher, PublishError
from snowlight.output import write_bytes_atomic, write_json
from snowlight.predict import artifact as artifact_module
from snowlight.predict import (
    backtest,
    candidates_cli,
    forecast_history,
    inputs,
    learn,
    ndfd,
    outlook_cli,
    pool,
    terms_cli,
    terms_file,
    train,
    tuning_cli,
)
from snowlight.predict import outlook_learn as ol
from snowlight.predict.alerts_live import (
    LiveEvent,
    Memory,
    ProductLog,
    UgcIndex,
    alerts_digest,
    live_events,
    withdrawn,
)
from snowlight.predict.calendar import is_school_day, previous_school_day, season_of
from snowlight.predict.config import (
    CONFIG_PATH,
    PIPELINE_ROOT,
    ModelSettings,
    PredictConfig,
    ServeSettings,
    live_score_sha256,
)
from snowlight.predict.forecast_values import NO_FORECASTS, Forecasts
from snowlight.predict.heights import (
    Loaded,
    PinnedTable,
    heights_said,
    load_pinned,
    school_heights,
)
from snowlight.predict.labels import Outcome
from snowlight.predict.live_labels import pending_tables, record_snapshots
from snowlight.predict.nowcast import UNREAD, Neighbors, neighbors_posted
from snowlight.predict.opens import NOTHING_SAID, OpensError, SaidOpen, said_open
from snowlight.predict.outlook import Outlook, OutlookMode
from snowlight.predict.outlook_live import (
    READ_ATTEMPTS,
    READ_TIMEOUT,
    Budget,
    ReadForecast,
    Taken,
    as_shown,
    as_shown_percent,
    forecast_reader,
    outlook_mode_of,
    published_percent,
    stale_line,
    take_record,
)
from snowlight.predict.outlook_record import RECORD_PATH, STATE_DAYS, Record, carried, merged
from snowlight.predict.outlook_serve import (
    Chances,
    OutlookServe,
    after_rows,
    district_states,
    inputs_of,
    outlook_chances,
)
from snowlight.predict.outlook_states import slot_at
from snowlight.predict.publish import (
    Dark,
    DarkError,
    Host,
    Mode,
    State,
    blank_file,
    check_alert_age,
    check_budget,
    check_collapse,
    check_coverage,
    checked,
    content_digest,
    due,
    hold_file,
    hold_key,
    mode_of,
    upload,
)
from snowlight.predict.serve import (
    DeployedDirectory,
    Fit,
    ServeError,
    ServeModel,
    TableError,
    build_model,
    closed_districts,
    closed_private,
    district_classes,
    forecast_file,
    pass_days,
    unit_classes,
    with_terms,
)
from snowlight.predict.situations import CLASS_BY_CODE, Window
from snowlight.schemas.live import ClosingsFile, DayTimeline, OpensFile
from snowlight.schemas.predictions import PredictionsFile
from snowlight.sources.nws.alerts import NwsAlert

LOG: Final = logging.getLogger("snowlight.predict")
HEIGHTS_RETRY_MINUTES: Final = 15
"""How long after a failed read of the pinned elevation table the loop reads it again."""
DEFAULT_STATE: Final = PIPELINE_ROOT / "out" / "internal" / "predict" / "state.json"
LIVE_INTERNAL: Final = PIPELINE_ROOT / "out" / "internal" / "live"
"""The live ingest's private folders (``state``, and ``store`` its state store keeps)."""
LEDGER: Final = "ledger.sqlite"
DEFAULT_SITE: Final = "https://snowlightmap.com"
DEFAULT_REPOSITORY: Final = "viaate/jsalcards"
LIVE_REPOSITORY: Final = "viaate/snowlight-live"
LIVE_ROOT: Final = "https://viaate.github.io/snowlight-live/"
EXIT_DARK: Final = 3
NAMED_DISTRICTS: Final = {
    "2011640": "Shawnee Mission",
    "2916400": "Kansas City 33",
    "2012000": "Blue Valley",
    "2010140": "Olathe",
    "2922800": "North Kansas City",
    "2918300": "Lee's Summit",
}
"""The KC districts of the named cases (spec c.3), by LEAID."""
NAMED_PRIVATE: Final = {
    "A1902690": "Pembroke Hill",
    "00753542": "Visitation Catholic (Kansas City)",
}
"""The private schools of the named cases (spec piece 2: Pembroke Hill's oracle days), by NCES
id. The oracle itself (what the school did) stays out of the repository: the report lists each
day's label and chance, and the lead compares them by eye."""
PEMBROKE_DAYS: Final = tuple(
    date.fromisoformat(day)
    for day in (
        "2024-01-09", "2024-01-10", "2024-01-16", "2025-01-06", "2025-01-07", "2025-01-08",
        "2025-01-09", "2025-01-10", "2025-02-05", "2025-02-18", "2025-12-01", "2025-12-02",
        "2026-01-26",
    )
)  # fmt: skip
NAMED_DAYS: Final = tuple(
    date.fromisoformat(day)
    for day in (
        "2024-01-09", "2025-01-06", "2025-01-07", "2025-01-08", "2025-01-09", "2025-01-10",
        "2025-02-18",
    )
)  # fmt: skip


def _out(line: str) -> None:
    sys.stdout.write(line + "\n")


def _err(line: str) -> None:
    sys.stderr.write(line + "\n")


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register ``predict`` and its actions."""
    parser = subparsers.add_parser(
        "predict", help="the chance of no school", description="The snow-day chance model."
    )
    parser.add_argument("--config", type=Path, default=CONFIG_PATH, help="predict.yaml")
    actions = parser.add_subparsers(dest="predict_action", metavar="ACTION", required=True)

    labels = actions.add_parser("labels", help="weather history and labels from the archive")
    _train_inputs(labels)
    labels.add_argument("--workers", type=int, default=4)
    labels.add_argument(
        "--reuse-weather",
        action="store_true",
        help="keep the weather history of an earlier run in --out (it reads no archive)",
    )
    labels.set_defaults(handler=run_labels)

    fit = actions.add_parser("train", help="fit the model and write model.json.gz")
    fit.add_argument("--work", type=Path, default=train.DEFAULT_OUT, help="labels folder")
    fit.add_argument("--directory", type=Path, default=train.TrainPaths().directory)
    fit.add_argument("--meta", type=Path, default=train.TrainPaths().meta)
    fit.add_argument("--out", type=Path, default=artifact_module.ARTIFACT_PATH)
    fit.set_defaults(handler=run_train)

    check = actions.add_parser("backtest", help="walk-forward backtest (internal report)")
    check.add_argument("--work", type=Path, default=train.DEFAULT_OUT, help="labels folder")
    check.add_argument("--directory", type=Path, default=train.TrainPaths().directory)
    labels_rule_options(check)
    check.set_defaults(handler=run_backtest)

    once = actions.add_parser("once", help="one serving pass")
    _serve_inputs(once)
    once.set_defaults(handler=run_once)

    loop = actions.add_parser("run", help="passes until a time, on the grid and on changes")
    _serve_inputs(loop)
    loop.add_argument("--until", required=True, help="+330m, or an ISO 8601 moment")
    loop.set_defaults(handler=run_loop)

    blank = actions.add_parser("blank", help="hold every chance dark at once")
    _serve_inputs(blank)
    blank.set_defaults(handler=run_blank)

    free = actions.add_parser("release", help="clear the hold predict blank set")
    _serve_inputs(free)
    free.set_defaults(handler=run_release)

    watch = actions.add_parser("check", help="is the public file fresh?")
    watch.add_argument("--url", default=f"{LIVE_ROOT}v1/predictions/latest.json")
    watch.add_argument("--max-age", default="45m", help="45m, 2h")
    watch.set_defaults(handler=run_check)

    taught = actions.add_parser("learn", help="learn from the live-read days (nightly)")
    _serve_inputs(taught)
    taught.add_argument(
        "--live-state",
        type=Path,
        default=LIVE_INTERNAL / "state",
        help="the live ingest's state folder (read only)",
    )
    taught.add_argument(
        "--live-store",
        type=Path,
        default=LIVE_INTERNAL / "store",
        help="the live state store's folder (its packed state, unpacked to a scratch folder)",
    )
    taught.add_argument(
        "--registry", type=Path, default=train.TrainPaths().registry, help="station registry"
    )
    taught.set_defaults(handler=run_learn)

    heads = actions.add_parser("headsup", help="download the heads-up season files (watches)")
    heads.add_argument("--first", type=int, default=inputs.FIRST_HEADS_UP_SEASON)
    heads.add_argument("--last", type=int, default=None, help="default: this school year")
    heads.add_argument("--cache", type=Path, default=inputs.HEADS_UP_CACHE)
    heads.add_argument(
        "--out", type=Path, default=PIPELINE_ROOT / "out" / "internal" / "predict" / "headsup.json"
    )
    heads.set_defaults(handler=run_headsup)
    for register_more in (
        _register_evidence,
        *(
            m.register
            for m in (forecast_history, terms_cli, tuning_cli, outlook_cli, candidates_cli)
        ),
    ):
        register_more(actions)


def _register_evidence(actions: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    kept = actions.add_parser(
        "evidence", help="keep the finished weather-class snapshots for good (docs/predict.md)"
    )
    kept.add_argument("--state", type=Path, default=DEFAULT_STATE)
    kept.add_argument("--site", default=DEFAULT_SITE, help="the site whose directory to read")
    kept.add_argument(
        "--repository", default=os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPOSITORY)
    )
    kept.add_argument(
        "--site-data", type=Path, default=None, help="read meta.json and points.bin here instead"
    )
    kept.add_argument(
        "--evidence-dir",
        type=Path,
        default=EVIDENCE_DIR,
        help="the district tables and labels predict learn left",
    )
    kept.add_argument(
        "--check",
        action="store_true",
        help="only say whether every finished snapshot is in both databases (no network)",
    )
    kept.set_defaults(handler=run_evidence)


def _train_inputs(parser: argparse.ArgumentParser) -> None:
    paths = train.TrainPaths()
    parser.add_argument("--archive", type=Path, default=paths.archive)
    parser.add_argument("--registry", type=Path, default=paths.registry)
    parser.add_argument("--directory", type=Path, default=paths.directory)
    parser.add_argument("--meta", type=Path, default=paths.meta)
    parser.add_argument("--aliases", type=Path, default=paths.aliases)
    parser.add_argument("--weather-cache", type=Path, default=paths.weather_cache)
    parser.add_argument("--weights-cache", type=Path, default=paths.weights_cache)
    parser.add_argument("--out", type=Path, default=paths.out)


def _serve_inputs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--site", default=DEFAULT_SITE, help="the site whose directory to read")
    parser.add_argument(
        "--repository", default=os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPOSITORY)
    )
    parser.add_argument(
        "--site-data", type=Path, default=None, help="read meta.json and points.bin here instead"
    )
    parser.add_argument("--model", type=Path, default=artifact_module.ARTIFACT_PATH)
    parser.add_argument("--terms", type=Path, default=terms_file.TERMS_PATH)
    parser.add_argument(
        "--outlook-model",
        type=Path,
        default=PIPELINE_ROOT / "data" / "predict" / "model-f.json.gz",
        help="the outlook's v3 rates and T (read with PREDICT_OUTLOOK shadow or on)",
    )
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--weather-cache", type=Path, default=PIPELINE_ROOT / ".cache" / "weather")
    parser.add_argument("--host", choices=("github", "dir"), default="github")
    parser.add_argument("--host-dir", type=Path, default=None, help="the folder of --host dir")
    parser.add_argument("--write", type=Path, default=None, help="also write each file here")
    parser.add_argument(
        "--elevation-pins", type=Path, default=DEFAULT_PINS_PATH, help="config/elevation.yaml"
    )
    parser.add_argument(
        "--elevation-cache",
        type=Path,
        default=PIPELINE_ROOT / ".cache" / "elevation",
        help="where the pinned elevation table is kept once read",
    )


# --- the heads-up history -----------------------------------------------------------------------


def run_headsup(args: argparse.Namespace) -> int:  # pragma: no cover - IEM
    """Run ``predict headsup``: each season's file (cached with its SHA-256), its rows by code,
    and the codes found in a season they cannot be in (exit 1 when there are any)."""
    from snowlight.sources.nws.http import HttpCache  # noqa: PLC0415

    last = args.last if args.last is not None else season_of(date.today())
    seasons: list[inputs.HeadsUpSeason] = []
    with HttpCache(inputs.client()) as http:
        for year in range(args.first, last + 1):
            found = inputs.load_headsup(year, http, args.cache)
            seasons.append(found)
            _out(
                f"{year}-{(year + 1) % 100:02d} rows {found.rows:,} {dict(found.by_code)}"
                f" tropical rows ended with their event {found.closed_tropical}"
            )
    problems = inputs.code_problems({found.year: found.by_code for found in seasons})
    write_json(
        args.out,
        {
            "seasons": [
                {
                    "season": found.year,
                    "rows": found.rows,
                    "by_code": dict(found.by_code),
                    "closed_tropical": found.closed_tropical,
                    "sha256": found.sha256,
                    "bytes": found.bytes,
                    "final": found.final,
                    "url": found.url,
                }
                for found in seasons
            ],
            "code_problems": list(problems),
        },
    )
    for problem in problems:
        _err(f"code out of its seasons: {problem}")
    return 1 if problems else 0


# --- training -----------------------------------------------------------------------------------


def run_labels(args: argparse.Namespace) -> int:  # pragma: no cover - the real archive
    """Run ``predict labels``."""
    config = PredictConfig.load(args.config)
    paths = train.TrainPaths(
        archive=args.archive,
        registry=args.registry,
        directory=args.directory,
        meta=args.meta,
        aliases=args.aliases,
        weather_cache=args.weather_cache,
        weights_cache=args.weights_cache,
        out=args.out,
    )
    schools = pl.read_parquet(paths.directory / "schools.parquet")
    if args.reuse_weather:
        table = pl.read_parquet(paths.out / "districts.parquet")
        weather = pl.read_parquet(paths.out / "weather.parquet")
        private = pl.read_parquet(paths.out / "private.parquet")
        private_weather = pl.read_parquet(paths.out / "weather-private.parquet")
    else:
        seasons = list(range(config.labels.first_season, season_of(date.today())))
        places = train.history_places(paths, schools, seasons)
        table = train.district_table(schools, places.zone_of_school)
        private = train.private_table(schools, places.zone_of_school)
        weather, private_weather, stats = train.weather_history(places, schools, config)
        paths.out.mkdir(parents=True, exist_ok=True)
        table.write_parquet(paths.out / "districts.parquet")
        weather.write_parquet(paths.out / "weather.parquet")
        private.write_parquet(paths.out / "private.parquet")
        private_weather.write_parquet(paths.out / "weather-private.parquet")
        write_json(paths.out / "weather-stats.json", json.loads(json.dumps(stats, default=str)))
    _out(f"weather: {weather.height:,} district-days, {private_weather.height:,} private days")
    zone_of = {
        d: z for d, z in zip(table["district"], table["time_zone"], strict=True) if z is not None
    }
    zone_of_private = {
        s: z for s, z in zip(private["district"], private["time_zone"], strict=True) if z
    }
    run = train.prepare_archive(paths, zone_of, args.workers, zone_of_private)
    labels = train.run_labels(run, schools, table, weather, config)
    labels.write_parquet(paths.out / "labels.parquet")
    private_labels = train.run_private_labels(run, private, private_weather, labels, config)
    private_labels.write_parquet(paths.out / "labels-private.parquet")
    write_json(paths.out / "district-markets.json", dict(sorted(run.markets.items())))
    states = dict(zip(table["district"], table["state"], strict=True))
    (paths.out / "labels-report.md").write_text(
        train.labels_report(labels, states), encoding="utf-8"
    )
    private_states = dict(zip(private["district"], private["state"], strict=True))
    (paths.out / "labels-private-report.md").write_text(
        train.labels_report(private_labels, private_states), encoding="utf-8"
    )
    write_audit(run, labels, schools, zone_of, config, paths.out)
    from snowlight.predict.posts import write_posts  # noqa: PLC0415

    posted, snapped = write_posts(
        run, labels, table, private, config.labels.audience_days, config.labels.read_until,
        paths.out, config.labels.no_school_share,
    )  # fmt: skip
    _out(f"posts: {posted:,} unit-days posted, {snapped:,} labeled days with a snapshot")
    _out(
        f"labels: {labels.height:,} district-days, {private_labels.height:,} private "
        f"school-days; report and audit in {paths.out}"
    )
    return 0


def write_audit(  # noqa: PLR0913, PLR0917 - the run and the labels it made
    run: train.ArchiveRun,
    labels: pl.DataFrame,
    schools: pl.DataFrame,
    zone_of: Mapping[str, str],
    config: PredictConfig,
    out: Path,
) -> None:  # pragma: no cover - the real archive
    """The 100-label audit sample (50 open, 50 no school) with each label's evidence, for the
    audit by eye (internal: ``labels-audit.jsonl`` and ``labels-audit.md`` hold list rows)."""
    from snowlight.predict.labels import audiences  # noqa: PLC0415

    audit = pl.concat(
        [
            train.sample_rows(labels, Outcome.OPEN, 50),
            train.sample_rows(labels, Outcome.NO_SCHOOL, 50),
        ]
    )
    audit.write_csv(out / "labels-audit.csv")
    eligible = train.eligible_schools(schools)
    by_district: dict[str, list[str]] = {}
    for district, school in zip(
        eligible["district_id"].to_list(), eligible["id"].to_list(), strict=True
    ):
        by_district.setdefault(district, []).append(school)
    audience = audiences(run.listings, config.labels.audience_days)
    items = []
    for row in audit.iter_rows(named=True):
        district, day = str(row["district"]), row["day"]
        found = run.audit(
            district, day, zone_of[district], by_district.get(district, []), audience, config.labels
        )
        found.update(
            {
                key: row[key]
                for key in ("outcome", "did", "readers", "lit_share", "no_school_share", "weather")
            }
        )
        items.append(found)
    train.write_json_lines(out / "labels-audit.jsonl", iter(items))
    (out / "labels-audit.md").write_text(train.audit_markdown(items), encoding="utf-8")


def _load_training(
    work: Path, directory: Path, config: PredictConfig
) -> tuple[pl.DataFrame, pl.DataFrame, pool.Places]:
    labels = pl.read_parquet(work / "labels.parquet")
    table = pl.read_parquet(work / "districts.parquet")
    schools = pl.read_parquet(directory / "schools.parquet")
    places = train.training_places(table, schools, config.serve.neighbor_miles)
    return labels, table, places


def _load_private(
    work: Path, directory: Path, config: PredictConfig
) -> tuple[pl.DataFrame, pl.DataFrame, pool.Places] | None:  # pragma: no cover - real labels
    """The private schools' labels, table and places, when ``predict labels`` made them."""
    if not (work / "labels-private.parquet").is_file():
        return None
    labels = pl.read_parquet(work / "labels-private.parquet")
    table = pl.read_parquet(work / "private.parquet")
    schools = pl.read_parquet(directory / "schools.parquet")
    places = train.private_places(table, schools, config.serve.neighbor_miles)
    return labels, table, places


def run_train(args: argparse.Namespace) -> int:  # pragma: no cover - the real labels
    """Run ``predict train``."""
    config = PredictConfig.load(args.config)
    labels, table, places = _load_training(args.work, args.directory, config)
    generated = json.loads(args.meta.read_text(encoding="utf-8"))["generated_on"]
    model, tuned, tuned_delay = train.fit_artifact(
        labels,
        table,
        places,
        config,
        date.fromisoformat(generated),
        private=_load_private(args.work, args.directory, config),
    )
    size = model.write(args.out)
    write_json(
        args.work / "train-trials.json",
        {
            "no_school": [list(item) for item in tuned.trials],
            "delay": [list(item) for item in tuned_delay.trials],
        },
    )
    _out(
        f"model: {args.out} ({size:,} bytes), {model.training.labeled_days:,} labeled days, "
        f"{len(model.private):,} private schools with {model.private_labeled_days:,} labeled days"
    )
    _out("strengths: " + json.dumps(model.strengths, sort_keys=True))
    return 0


def labels_rule_options(parser: argparse.ArgumentParser) -> None:
    """The walk-forward's training labels: per fold (the rule) or the whole archive's."""
    parser.add_argument(
        "--labels-rule",
        choices=("fold", "whole"),
        default="fold",
        help="fold: each fold trains on its fold label files (the rule); whole: the whole "
        "archive's labels (the rule before 2026-10-25, for comparison)",
    )
    parser.add_argument(
        "--folds", type=Path, default=None, help="fold label files (default: WORK/folds)"
    )


def fold_set(
    args: argparse.Namespace, seasons: Sequence[int], places: pool.Places, *, private: bool = False
) -> "train.FoldSet | None":  # pragma: no cover - the real labels
    """The fold label files ``--labels-rule fold`` reads, or ``None`` for ``whole``."""
    if args.labels_rule == "whole":
        return None
    return train.read_fold_set(
        args.folds or args.work / train.FOLDS, seasons, places, private=private
    )


def run_backtest(args: argparse.Namespace) -> int:  # pragma: no cover - the real labels
    """Run ``predict backtest``."""
    config = PredictConfig.load(args.config)
    labels, _table, places = _load_training(args.work, args.directory, config)
    usable = pool.usable_labels(labels, places)
    markets_path = args.work / "district-markets.json"
    markets = json.loads(markets_path.read_text(encoding="utf-8")) if markets_path.is_file() else {}
    seasons = config.backtest.test_seasons
    folds = fold_set(args, seasons, places)
    report = backtest_report(
        usable,
        places,
        config,
        labels=labels,
        markets=markets,
        training=None if folds is None else folds.training,
    )
    out = args.work / "backtest"
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "metrics.json", json_safe(report.metrics))
    (out / "report.md").write_text(report.markdown, encoding="utf-8")
    (out / "reliability.svg").write_text(report.svg, encoding="utf-8")
    _out(report.markdown.splitlines()[2])
    private = _load_private(args.work, args.directory, config)
    if private is not None:
        private_labels, _private_table, private_places = private
        usable_private = pool.usable_labels(private_labels, private_places)
        private_folds = fold_set(args, seasons, private_places, private=True)
        found = backtest_report(
            usable_private,
            private_places,
            config.model_copy(update={"model": config.model.private()}),
            labels=private_labels,
            markets=markets,
            names=NAMED_PRIVATE,
            days=PEMBROKE_DAYS,
            training=None if private_folds is None else private_folds.training,
        )
        folder = out / "private"
        folder.mkdir(parents=True, exist_ok=True)
        write_json(folder / "metrics.json", json_safe(found.metrics))
        (folder / "report.md").write_text(
            "Private schools (each its own unit, counted over private schools only; contract "
            "C3). The same gates against B0 over the private rows.\n\n" + found.markdown,
            encoding="utf-8",
        )
        (folder / "reliability.svg").write_text(found.svg, encoding="utf-8")
        weather = pl.read_parquet(args.work / "weather-private.parquet")
        with (folder / "report.md").open("a", encoding="utf-8") as handle:
            handle.write(
                "\n".join(
                    oracle_table(
                        private_labels,
                        weather,
                        private_places,
                        config.model.private(),
                        training=None if private_folds is None else private_folds.training,
                    )
                )
                + "\n"
            )
        _out("private: " + found.markdown.splitlines()[2])
    return 0


def oracle_table(  # noqa: PLR0913 - the labels, the weather, the places, the settings, the cases
    labels: pl.DataFrame,
    weather: pl.DataFrame,
    places: pool.Places,
    settings: ModelSettings,
    *,
    training: backtest.FoldTraining | None = None,
    names: Mapping[str, str] = NAMED_PRIVATE,
    days: Sequence[date] = PEMBROKE_DAYS,
) -> list[str]:
    """Each named private school on each named day, predicted walk-forward (fit on the
    seasons before its own only) from its weather class that day, labeled or not.

    ``labels`` give the days after a closing and the label column; the fit trains on their
    usable rows (the whole archive's labels), or on ``training``'s fold labels of each day's
    season under the per-fold rule (:func:`backtest.chances_on`)."""
    usable = pool.usable_labels(labels, places)
    rows = pool.rows_from_labels(usable, places, "no_school")
    delay_rows = pool.rows_from_labels(usable, places, "delay")
    classes = {(unit, day): int(value) for unit, day, value in weather.iter_rows()}
    closed = {
        (row["district"], row["day"])
        for row in labels.filter(pl.col("outcome") == "no_school").iter_rows(named=True)
    }
    outcome = {(row["district"], row["day"]): row for row in labels.iter_rows(named=True)}
    cells: list[tuple[str, int, int]] = []
    shown: list[tuple[str, date, int, bool]] = []
    for unit in names:
        for day in days:
            weather_class = classes.get((unit, day), 0)
            after = (unit, previous_school_day(day)) in closed
            key = pool.situation_of(weather_class, after).key
            cells.append((unit, pool.SITUATION_INDEX[key], season_of(day)))
            shown.append((unit, day, weather_class, after))
    chances = backtest.chances_on(rows, delay_rows, places, cells, settings, training=training)
    lines = [
        "",
        "## Named private schools, every named day, predicted",
        "",
        "Walk-forward: each day's chance from its weather class that day (alerts issued by "
        "21:00 the evening before), fit on the seasons before its own only, labeled or not.",
        "",
        backtest.WHOLE_NOTE if training is None else backtest.PER_FOLD_NOTE,
        "",
        "| school | day | weather class | day after | chance | label |",
        "|---|---|---|---|---|---|",
    ]
    for (unit, day, weather_class, after), chance in zip(shown, chances, strict=True):
        row = outcome.get((unit, day))
        label = "no morning read" if row is None else str(row["outcome"])
        lines.append(
            f"| {names[unit]} ({unit}) | {day} | {_class_label(str(weather_class))} | "
            f"{'yes' if after else 'no'} | {'-' if chance is None else f'{chance:.2f}'} | "
            f"{label} |"
        )
    return lines


def json_safe(value: Any) -> Any:
    """``value`` with every NaN as null (a metric over no rows), for JSON."""
    if isinstance(value, float):
        return None if math.isnan(value) else value
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class BacktestReport:
    """The backtest's outputs."""

    metrics: dict[str, Any]
    markdown: str
    svg: str
    gates: backtest.Gates


def backtest_report(  # noqa: PLR0913 - the labels, the places, the settings and the cases
    usable: pl.DataFrame,
    places: pool.Places,
    config: PredictConfig,
    *,
    labels: pl.DataFrame | None = None,
    markets: Mapping[str, str] | None = None,
    names: Mapping[str, str] = NAMED_DISTRICTS,
    days: Sequence[date] = NAMED_DAYS,
    training: backtest.FoldTraining | None = None,
) -> BacktestReport:
    """Run the walk-forward backtest on the usable labels (with a ``cluster`` column).

    ``labels`` (every row, unknown ones with why) and ``markets`` (district to its market)
    word the named cases (``names`` on ``days``); without them the usable labels are used.
    ``training``: each test season's fold labels (the per-fold rule); without it every fold
    trains on the earlier seasons of ``usable``."""
    rows = pool.rows_from_labels(usable, places, "no_school")
    delay_rows = pool.rows_from_labels(usable, places, "delay")
    folds = backtest.walk_forward(
        rows, delay_rows, places, config.backtest.test_seasons, config.model, training=training
    )
    scored = backtest.scored_frame(folds, rows, places, usable)
    if scored.is_empty():
        raise ValueError("no test season has labeled rows")
    y = scored["y"].to_numpy().astype(np.float64)
    bins = backtest.reliability(
        scored["p_raw"].to_numpy().astype(np.float64),
        y,
        list(zip(scored["day"].to_list(), scored["cluster"].to_list(), strict=True)),
        config.backtest.reliability_bins,
    )
    judged = backtest.gates(
        scored,
        bins,
        config.backtest.apart,
        config.backtest.reliability_min_rows,
        g1_min_storm_rows=config.backtest.g1_min_storm_rows,
        g1_tolerance=config.backtest.g1_tolerance,
    )
    delays = scored.filter(pl.col("outcome") != "no_school")
    delay_recall, delay_precision = backtest.caught(
        delays["q"].to_numpy().astype(np.float64),
        (delays["outcome"] == "delayed").to_numpy().astype(np.float64),
    )
    clusters = list(zip(scored["day"].to_list(), scored["cluster"].to_list(), strict=True))
    by_region: dict[str, list[backtest.Bin]] = {}
    for region in sorted(set(scored["region"].to_list())):
        mask = (scored["region"] == region).to_numpy()
        by_region[str(region)] = backtest.reliability(
            scored["p_raw"].to_numpy().astype(np.float64)[mask],
            y[mask],
            [item for item, keep in zip(clusters, mask.tolist(), strict=True) if keep],
            config.backtest.reliability_bins,
        )
    storm_days = backtest.storm_day_briers(
        scored.filter(pl.col("weather") > 0), config.backtest.storm_day_market_closings
    )
    metrics: dict[str, Any] = {
        "all": backtest.summarize(scored).as_json(),
        "storm": backtest.summarize(scored.filter(pl.col("weather") > 0)).as_json(),
        "by_season": backtest.by_key(scored, "season"),
        "by_class": backtest.by_key(scored, "weather"),
        "by_region": backtest.by_key(scored, "region"),
        "ece": round(backtest.ece(bins), 5),
        "unmodeled_rows": backtest.unmodeled_rows(folds),
        "reliability": [_bin_json(item) for item in bins],
        "reliability_by_region": {
            region: [_bin_json(item) for item in found] for region, found in by_region.items()
        },
        "delay": {"caught_50": delay_recall, "precision_50": delay_precision},
        "storm_day_brier": {
            "days": len(storm_days),
            "quantiles": [round(float(np.quantile(storm_days, q)), 5) for q in (0.1, 0.5, 0.9)]
            if storm_days
            else [],
        },
        "gates": {
            "g1_pooled": judged.g1_pooled,
            "g1_pooled_without_2020_21": judged.g1_pooled_without_apart,
            "g1_seasons": judged.g1_seasons,
            "g1_counted": judged.g1_counted,
            "g1": judged.g1,
            "g1_by_season": {
                str(item.season): {
                    "storm_rows": item.storm_rows,
                    "brier": round(item.brier, 5),
                    "brier_b0": round(item.brier_b0, 5),
                    "excess": round(item.excess, 5),
                    "gated": item.gated,
                    "ok": item.ok,
                }
                for item in judged.g1_by_season
            },
            "g2": judged.g2,
            "g2_failing": list(judged.g2_failing),
            "g3": judged.g3,
            "passed_here": judged.passed,
            "gated_here": ["g1_pooled", "g1_pooled_without_2020_21"],
            "g4": "the leakage tests in tests/predict, run by pytest with every gate; not here",
            "reported": ["g1_by_season", "g2", "g3"],
        },
        "strengths": {
            str(fold.season): {
                "no_school": fold.strengths.as_json(),
                "delay": fold.strengths_delay.as_json(),
            }
            for fold in folds
        },
    }
    metrics["by_class"] = {_class_label(key): value for key, value in metrics["by_class"].items()}
    known = usable if labels is None else labels
    places_of = dict(markets or {})
    for district, cluster in zip(known["district"], known["cluster"], strict=True):
        places_of.setdefault(district, cluster)
    cases = backtest.named_cases(known, scored, names, days, places_of)
    comparison = None
    if training is not None:
        whole = backtest.walk_forward(
            rows, delay_rows, places, config.backtest.test_seasons, config.model
        )
        comparison = backtest.compare_rules(folds, whole, rows, config.backtest.test_seasons)
        metrics["per_fold_beside_whole"] = comparison.as_json()
    report_metrics = {**metrics, "reliability_by_region": by_region}
    metrics["labels_rule"] = "whole" if training is None else "fold"
    markdown = backtest.report_markdown(
        report_metrics, bins, judged, cases, per_fold=training is not None, comparison=comparison
    )
    return BacktestReport(metrics, markdown, backtest.reliability_svg(bins), judged)


def _bin_json(item: "backtest.Bin") -> dict[str, float | int]:
    return {
        "low": item.low,
        "high": item.high,
        "rows": item.rows,
        "clusters": item.clusters,
        "mean_p": round(item.mean_p, 5),
        "observed": round(item.observed, 5),
        "gap": round(item.gap, 5),
        "se": round(item.se, 5),
    }


def _class_label(key: str) -> str:
    from snowlight.predict.situations import WeatherClass  # noqa: PLC0415

    return WeatherClass(int(key)).label


# --- serving ------------------------------------------------------------------------------------


class ConfigError(RuntimeError):
    """The environment or the options are not usable."""


def make_host(args: argparse.Namespace, env: Mapping[str, str]) -> Host:  # pragma: no cover
    """The live host: the live ingest's GitHub publisher (``--host github``), or a folder."""
    if args.host == "dir":
        if args.host_dir is None:
            raise ConfigError("--host dir needs --host-dir")
        return DirPublisher(args.host_dir)
    token = env.get("LIVE_HOST_TOKEN", "")
    if not token:
        raise ConfigError("needs LIVE_HOST_TOKEN in the environment")
    from snowlight.predict.inputs import client  # noqa: PLC0415

    return GitHubPublisher(repository=LIVE_REPOSITORY, token=token, client=client(), branch="main")


def load_state(path: Path) -> State:
    """The private state, empty when there is none or it does not read."""
    try:
        return State.from_json(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return State()


def save_state(path: Path, state: State) -> None:
    """Keep the private state."""
    write_bytes_atomic(path, json.dumps(state.as_json(), sort_keys=True).encode())


@dataclass(slots=True)
class Pass:
    """Everything a pass needs from the world, as callables (tests replace them)."""

    config: PredictConfig
    mode: Mode
    host: Host | None
    directory: Callable[[], DeployedDirectory]
    alerts: Callable[[], tuple[Any, bool]]
    """The feed (``ActiveFeed``) and whether it changed."""
    ugcs: Callable[[DeployedDirectory], UgcIndex]
    zone_fallback: Callable[[float, float], str | None]
    model: Callable[[], artifact_module.ModelArtifact]
    state: State
    learned: artifact_module.Learned | None = None
    """What the live days taught (``predictions/learned.json``), used with the committed
    model; ``None``: the committed model alone."""
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    write: Path | None = None
    history: Callable[[datetime, datetime], Sequence[NwsAlert]] | None = None
    """The NWS alert products issued in a span, to rebuild a lost alert memory."""
    notify: Callable[[PredictionsFile, DeployedDirectory, datetime], str] | None = None
    """The chance notifier (:class:`snowlight.notify.cli.ChanceNotifier`), run after a pass
    whose file is the public one; ``None``: no notifications (no Cloudflare secrets)."""
    heights: Callable[[DeployedDirectory], npt.NDArray[np.float64] | None] | None = None
    """Feet per school position of a directory, NaN where not known
    (:mod:`snowlight.predict.heights`); ``None``, or ``None`` back: no height is known, so an
    alert that names heights reaches its whole zones."""
    terms: terms_file.TermsArtifact | None = None
    """The reasons' terms (``data/predict/terms.json.gz``), used only over the committed model
    they were fit on (``model_sha256``) and only with ``serve.reasons`` on."""
    model_sha256: str | None = None
    """The committed model's SHA-256 (the terms name the model they were fit over)."""
    forecast: Callable[[ServeModel, tuple[date, ...], datetime], Forecasts] | None = None
    """The NDFD forecast at the class snapshot (:mod:`snowlight.predict.forecast_live`)."""
    outlook_mode: OutlookMode = OutlookMode.OFF
    """``PREDICT_OUTLOOK`` (S7-F, :mod:`snowlight.predict.outlook_live`): off leaves the pass
    exactly as S7-L's."""
    outlook_model: Callable[[], tuple[artifact_module.ModelArtifact, Outlook]] | None = None
    """The v3 rates and ``T`` (``data/predict/model-f.json.gz``), read when the outlook is
    shadow or on."""
    outlook_forecast: ReadForecast | None = None
    """The NDFD forecast the outlook reads (the newest run at a moment)."""
    outlook_learned: artifact_module.Learned | None = None
    """What the live days taught the v3 rates (``predictions/outlook/learned-rates.json``),
    used with them; ``None``: the committed v3 rates alone."""
    outlook_newest: Callable[[datetime], datetime | None] | None = None
    """The newest complete NDFD run that counts at a moment (the loop's check for a new run
    with the outlook on); ``None``, or ``None`` back: not known."""
    outlook_budget: Budget | None = None
    """The time limit on the outlook's reads, started once per pass where the outlook's work
    begins (on: before its product log, in the pass; shadow: at the record step); its forecast
    reader checks it before every request and :attr:`product_history` before every page;
    ``None``: no limit (tests' readers)."""
    product_history: Callable[[datetime, datetime], Sequence[NwsAlert]] | None = None
    """The NWS alert history the outlook's product log rebuilds from: the classes' products and
    the heads-ups' (:data:`~snowlight.predict.inputs.PRODUCT_EVENTS`), read apart from the alert
    memory's (:attr:`history`, whose events and bound stay as they are) and within
    :attr:`outlook_budget`; ``None``: :meth:`alert_history` (tests' histories hold both)."""
    _products_retry: datetime | None = None
    """After the record step's product log rebuild failed: no new try before this time."""
    _built: tuple[object, ServeModel] | None = None
    _outlook: tuple[object, OutlookServe] | None = None
    _record_names: Record | None = None
    """The directory content and LEAIDs the last pass's outlook record was of (a new content
    in the same run carries the record over by LEAID)."""
    _history: tuple[tuple[datetime, datetime], Sequence[NwsAlert]] | None = None

    def alert_history(self, start: datetime, end: datetime) -> Sequence[NwsAlert]:
        """The NWS alert products issued in a span (:attr:`history`), asked once per span: the
        alert memory, and the outlook's product log when there is no :attr:`product_history`
        (tests), rebuild from one read.

        Raises:
            DarkError: there is no history to read.
        """
        if self.history is None:
            raise DarkError(Dark.MEMORY, "no alert history to rebuild from")
        if self._history is None or self._history[0] != (start, end):
            self._history = ((start, end), self.history(start, end))
        return self._history[1]

    _index: tuple[object, UgcIndex] | None = None
    _heights: tuple[object, npt.NDArray[np.float64] | None] | None = None

    def serve_model(self, directory: DeployedDirectory) -> ServeModel:
        """The rates for this directory (built once per directory), with the reasons' terms
        when they were fit over this committed model."""
        if self._built is None or self._built[0] != directory.stamp:
            built, why = learn.serving_model(
                directory, self.model(), self.learned, self.config, self.zone_fallback
            )
            if why is not None:
                _warn(why)
            if self.terms is not None and self.config.serve.reasons:
                override = self.config.serve.reasons_gate_override
                refused = terms_refused(
                    self.terms.model_sha256,
                    self.model_sha256,
                    self.learned is not None and why is None,
                    gate=self.terms.gate,
                    override=override,
                )
                if refused is None:
                    with_terms(built, self.terms.model(), self.terms.announce)
                    if self.terms.gate is None or not self.terms.gate.passed:
                        _warn(f"serving terms that failed backtest v2's gate: {override}")
                else:
                    _warn(refused)
            self._built = (directory.stamp, built)
        return self._built[1]

    def outlook_serve(self, directory: DeployedDirectory) -> OutlookServe:
        """The outlook's v3 rates and ``T`` on this directory (built once per directory).

        Raises:
            ServeError: no outlook model is given, or its rates do not build.
        """
        if self._outlook is None or self._outlook[0] != directory.stamp:
            if self.outlook_model is None:
                raise ServeError("the outlook is on but no outlook model is given")
            rates, found = self.outlook_model()
            built, why = learn.serving_model(
                directory, rates, self.outlook_learned, self.config, self.zone_fallback
            )
            if why is not None:
                _warn(f"outlook: v3 rates: {why}")
            self._outlook = (directory.stamp, OutlookServe.of(built, found))
        return self._outlook[1]

    def ugc_index(self, directory: DeployedDirectory) -> UgcIndex:
        """The schools of each UGC (built once per directory)."""
        if self._index is None or self._index[0] != directory.stamp:
            self._index = (directory.stamp, self.ugcs(directory))
        return self._index[1]

    def school_heights(self, directory: DeployedDirectory) -> npt.NDArray[np.float64] | None:
        """The schools' heights (read once per directory; asked again while there are none,
        as the table may read on a later pass)."""
        if self.heights is None:
            return None
        key = (directory.stamp, directory.content_sha256)
        if self._heights is None or self._heights[0] != key or self._heights[1] is None:
            self._heights = (key, self.heights(directory))
        return self._heights[1]


def terms_refused(
    terms_sha256: str,
    model_sha256: str | None,
    learned: bool,
    *,
    gate: terms_file.GateRecord | None,
    override: str = "",
) -> str | None:
    """Why a pass serves the base alone though the reasons are on, or ``None`` when it may
    use the terms: they were fit as offsets on the committed model's archive rates, so they
    apply only over that model (``terms_sha256``, the one they name) with no learned file
    serving (``learned``), which re-anchors rates they were not fit on. A learned file that
    re-anchors a base asks for the terms to be refit over it first (spec addendum b.3). The
    reasons publish only when backtest v2's gate passed (spec c.2): terms whose recorded
    ``gate`` failed, or that record none, serve only under the lead's named ``override``
    (``serve.reasons_gate_override``)."""
    if terms_sha256 != model_sha256:
        return "the reasons' terms were fit over another committed model; base only"
    if learned:
        return "the reasons' terms were fit over the archive rates, not the learned ones; base only"
    if override.strip():
        return None
    if gate is None:
        return (
            "the reasons' terms record no backtest v2 gate and no lead override is set; base only"
        )
    if not gate.passed:
        return (
            f"the reasons' terms failed backtest v2's gate (gain {gate.gain:+.1%}) and no lead "
            "override is set; base only"
        )
    return None


def winter_count(events: list[LiveEvent]) -> int:
    """The class-making alerts (distinct VTEC events) in the feed."""
    return len({event.key for event in events if event.event.code in CLASS_BY_CODE})


def memory_reach(days: tuple[date, ...], zones: Sequence[str], window: Window) -> datetime:
    """How far back the alert memory must reach for ``days``: the earliest start of the first
    day's alert window (``window_from`` the evening before) in any district's zone."""
    return min(window.span(days[0], zone)[0].astimezone(UTC) for zone in set(zones))


def remember(
    run: Pass,
    feed: Any,
    events: list[LiveEvent],
    now: datetime,
    reach: datetime,
) -> list[LiveEvent]:
    """Take the feed into the alert memory and return the events to count.

    The memory is whole since ``state.memory_since`` while the feed was read at least every
    ``memory_gap_minutes``. When it does not reach back to ``reach`` (a lost, stale or first
    state), it is rebuilt from the NWS alert history first.

    Raises:
        DarkError: it must be rebuilt and cannot be (``alert_memory``).
    """
    config = run.config
    state = run.state
    memory = Memory.from_json(config.weather.memory_hours, state.memory)
    if memory.unread_heights:
        _warn(
            f"predict: {memory.unread_heights} remembered alerts' heights do not read: they "
            "reach their whole zones"
        )
    gap = timedelta(minutes=config.serve.memory_gap_minutes)
    if state.observed_at is None or now - state.observed_at > gap:
        state.memory_since = None
    if state.memory_since is None or state.memory_since > reach:
        if run.history is None:
            raise DarkError(Dark.MEMORY, "the alert memory has a gap and no history to fill it")
        lead = timedelta(hours=config.serve.history_lead_hours)
        memory.rebuild(run.alert_history(reach - lead, now), now)
        state.memory_since = reach
    counted = memory.update(events, now, withdrawn(feed.alerts))
    state.memory = memory.as_json()
    state.observed_at = now
    return counted


PRODUCTS_RETRY: Final = timedelta(minutes=30)
"""After the record step's product log rebuild fails, how long before it tries again (the
passes between record nothing; the next sample hour's grace is 15 minutes)."""


def remember_products(
    run: Pass, feed: Any, now: datetime, reach: datetime, *, back_off: bool = False
) -> ProductLog:
    """Take the feed into the outlook's product log (S7-F) and return it. As :func:`remember`:
    the log is whole since ``state.products_since`` while the feed was read at least every
    ``memory_gap_minutes``, and rebuilt from the NWS alert history when it does not reach back
    to ``reach``: the classes' products and the heads-ups' (:attr:`Pass.product_history`), so
    a watch whose current product came after a sample hour still stood at it.

    ``back_off`` (the record step): a rebuild that fails is not tried again for
    :data:`PRODUCTS_RETRY`, so a history that is down cannot hold back pass after pass.

    Raises:
        DarkError: it must be rebuilt and cannot be (``alert_memory``), or a failed rebuild is
            backing off.
    """
    config = run.config
    state = run.state
    log = ProductLog.from_json(config.weather.memory_hours, state.products)
    gap = timedelta(minutes=config.serve.memory_gap_minutes)
    if state.products_observed is None or now - state.products_observed > gap:
        state.products_since = None
    if state.products_since is None or state.products_since > reach:
        if run.history is None and run.product_history is None:
            raise DarkError(Dark.MEMORY, "the product log has a gap and no history to fill it")
        retry = run._products_retry
        if back_off and retry is not None and now < retry:
            raise DarkError(
                Dark.MEMORY,
                f"the product log's history read failed; no new try before {retry:%H:%MZ}",
            )
        lead = timedelta(hours=config.serve.history_lead_hours)
        try:
            products = (
                run.product_history(reach - lead, now)
                if run.product_history is not None
                else run.alert_history(reach - lead, now)
            )
        except DarkError:
            if back_off:
                run._products_retry = now + PRODUCTS_RETRY
            raise
        run._products_retry = None
        log.take(products, now)
        state.products_since = reach
    log.take(feed.alerts, now)
    state.products = log.as_json()
    state.products_observed = now
    return log


@dataclass(slots=True)
class _Made:
    """A pass's file and what the outlook's record reads of it."""

    made: PredictionsFile
    data: bytes
    packed: int
    after: dict[date, frozenset[int]]
    log: ProductLog | None = None
    chances: Chances | None = None
    said: SaidOpen = NOTHING_SAID
    """The units that said school is on at the pass (their chance shows the floor)."""


def one_pass(run: Pass, *, grid: bool = True) -> int:
    """One serving pass: 0 published or unchanged, 3 dark. ``grid``: a pass on the grid (the
    heartbeat uploads an unchanged file only then, see :func:`~snowlight.predict.publish.due`).

    The alerts it was made from count as handled (``state.alerts_digest``) only when it
    published or found nothing to change: a dark pass leaves them, so the loop tries again.

    With ``PREDICT_OUTLOOK`` on, the file is the outlook's (:func:`_outlook_file`); shadow or
    on, a pass that published (or found nothing to change) then takes the outlook's private
    record (:func:`_outlook_after`), which can never change the file or darken the pass.
    """
    config = run.config
    now = run.now()
    weather = config.weather
    window = Window(weather.window_from, weather.window_until, weather.snapshot_hour)
    try:
        feed, _changed = run.alerts()
        check_alert_age(feed.updated, now, config.serve)
        directory = run.directory()
        model = run.serve_model(directory)
        check_coverage(model.coverage, config.serve)
        events = live_events(feed)
        check_collapse(winter_count(events), run.state, config.serve)
        days = pass_days(now, config)
        reach = memory_reach(days, model.time_zone, window)
        counted = remember(run, feed, events, now, reach)
        classes, private_classes, whole_zones, said_heights = _classes(
            run, model, directory, counted, days, now, window
        )
        known = PredictKept.of(run.state.evidence)
        content = learn.content_key(directory)
        run.state.snapshots = record_snapshots(
            run.state.snapshots,
            content=content,
            zones=model.time_zone,
            classes=whole_zones,
            days=days,
            now=now,
            window=window,
            kept=known,
        )
        run.state.tables = pending_tables(
            run.state.tables,
            run.state.snapshots,
            content=content,
            district_ids=directory.district_ids,
            kept=known,
        )
        if run.outlook_mode is OutlookMode.ON:
            if run.outlook_budget is not None:
                run.outlook_budget.start()  # once per pass: the record step goes on with it
            log = remember_products(run, feed, now, reach)
            built = _outlook_file(run, directory, counted, days, now, window, log)
        else:
            built = _pass_file(run, model, days, now, classes, private_classes)
        checked(built.data)
    except DarkError as error:
        _err(f"predict: dark ({error})")
        return EXIT_DARK
    except ServeError as error:
        _err(f"predict: dark ({type(error).__name__}: {error})")
        return EXIT_DARK
    code = _publish_pass(
        run, built, model, directory, events, days, now, grid=grid, said_heights=said_heights
    )
    if code == 0 and run.outlook_mode is not OutlookMode.OFF:
        _outlook_after(run, model, directory, classes, days, now, window, feed, built)
    return code


def _publish_pass(  # noqa: PLR0913, PLR0917 - the pass, its file and what its lines say
    run: Pass,
    built: _Made,
    model: ServeModel,
    directory: DeployedDirectory,
    events: list[LiveEvent],
    days: tuple[date, date],
    now: datetime,
    *,
    grid: bool,
    said_heights: str | None,
) -> int:
    """Upload the pass's file when due (see :func:`one_pass`): 0 published or unchanged, 3
    dark."""
    config = run.config
    made, data, packed = built.made, built.data, built.packed
    if run.write is not None:
        write_bytes_atomic(run.write, data)
    digest = content_digest(data)
    lit = sum(1 for d in range(len(days)) if is_school_day(days[d]))
    _out(
        f"predict: {len(made.districts):,} districts, {len(made.schools):,} private schools, "
        f"{len(days)} days ({lit} school days), {winter_count(events)} winter alerts, "
        f"{len(data):,} bytes ({packed:,} gzip)"
    )
    _say_left_out(model)
    if said_heights is not None:
        _out(said_heights)
    key = run.mode.key
    handled = alerts_digest(events)
    if key is None or run.host is None:
        _out("predict: publishing is off")
        run.state.alerts_digest = handled
        return 0
    if not due(run.state, digest, now, config.serve, grid=grid):
        _out("predict: unchanged, heartbeat not due")
        run.state.alerts_digest = handled
        _after_publish(run, made, directory, now)
        return 0
    try:
        upload(run.host, key, data)
    except (DarkError, PublishError) as error:
        _err(f"predict: dark ({error})")
        return EXIT_DARK
    run.state.digest = digest
    run.state.uploaded_at = now
    run.state.alerts_digest = handled
    _out(f"predict: uploaded {key}")
    _after_publish(run, made, directory, now)
    return 0


def _outlook_forecasts(
    run: Pass, model: ServeModel, days: tuple[date, ...], now: datetime
) -> Forecasts:
    """The newest forecast run at the pass for the outlook; when it cannot be read, none (every
    district then gets the issued-alerts-only chance, and the pass says so)."""
    if run.outlook_forecast is None:
        return Forecasts(unread={day: dict.fromkeys(set(model.time_zone), "error") for day in days})
    # Only the days still before 5 AM somewhere: from then on the outlook is the identity.
    zones = sorted(set(model.time_zone))
    wanted = tuple(day for day in days if any(slot_at(day, zone, now) > 0 for zone in zones))
    if not wanted:
        return Forecasts()
    try:
        found = run.outlook_forecast(model, wanted, now, None, None)
    except (OSError, ValueError, ndfd.NdfdError) as error:
        _warn(f"outlook: forecast {type(error).__name__}: the issued-alerts-only chance this pass")
        return Forecasts(unread={day: dict.fromkeys(set(model.time_zone), "error") for day in days})
    for problem in found.problems[:3]:
        _warn(f"outlook: forecast: {problem}")
    return found


def _outlook_chances(  # noqa: PLR0913, PLR0917 - the pass, the outlook, the days, the day-after
    run: Pass,
    serve: OutlookServe,
    directory: DeployedDirectory,
    log: ProductLog,
    days: tuple[date, ...],
    now: datetime,
    window: Window,
    after: dict[date, frozenset[int]],
) -> tuple[Chances, datetime | None]:
    """The outlook's chances at the pass (:func:`~snowlight.predict.outlook_serve.
    outlook_chances`) and the forecast run its lines read (``forecast_at``): a line whose
    district read another run gives way to the identity, so every line is of that run."""
    config = run.config
    model = serve.rates
    c0, heads = district_states(
        model,
        log.events_at(now),
        run.ugc_index(directory),
        days,
        now,
        window,
        config.weather.covered_share,
        run.school_heights(directory),
        config.serve.elevation_margin_feet,
    )
    forecasts = _outlook_forecasts(run, model, days, now)
    inputs = inputs_of(
        model, c0, heads, after_rows(after, days, len(model.time_zone)), days, forecasts, now
    )
    settings = model.artifact.settings
    chances = outlook_chances(serve, inputs, floor=settings.floor, ceiling=settings.ceiling)
    runs = {
        found.run_time
        for (i, d) in chances.lines
        if (found := forecasts.get(days[d], i)) is not None and found.run_time is not None
    }
    at = max(runs) if runs else None
    for i, d in list(chances.lines):
        found = forecasts.get(days[d], i)
        if found is None or found.run_time != at:
            del chances.lines[(i, d)]
            chances.p[i, d], chances.delay[i, d] = chances.base[i, d], chances.base_delay[i, d]
            chances.applied[i, d] = False
    return chances, at if chances.lines else None


def _outlook_file(  # noqa: PLR0913, PLR0917 - the pass, the directory, the alerts and the days
    run: Pass,
    directory: DeployedDirectory,
    counted: list[LiveEvent],
    days: tuple[date, date],
    now: datetime,
    window: Window,
    log: ProductLog,
) -> _Made:
    """The file of a pass with the outlook on: every chance from the v3 rates, the class as
    issued under rule D2, and the outlook's line where it moves the chance (spec-f s. 7);
    private schools keep their base alone. The reasons' terms of piece 3 are not used (they
    were fit over the v2 rates). Its reads use the time :func:`one_pass` started."""
    serve = run.outlook_serve(directory)
    model = serve.rates
    config = run.config
    share = config.weather.covered_share
    classes, _heads = district_states(
        model,
        log.events_at(now),
        run.ugc_index(directory),
        days,
        now,
        window,
        share,
        run.school_heights(directory),
        config.serve.elevation_margin_feet,
    )
    _found, private_classes = unit_classes(
        model,
        counted,
        run.ugc_index(directory),
        days,
        now,
        window,
        share,
        run.school_heights(directory),
        config.serve.elevation_margin_feet,
    )
    holder: dict[str, Chances] = {}

    def outlook(after: dict[date, frozenset[int]]) -> tuple[Chances, datetime | None]:
        chances, at = _outlook_chances(run, serve, directory, log, days, now, window, after)
        holder["chances"] = chances
        if chances.stale and config.serve.forecast_stale == "dark":
            raise DarkError(
                Dark.FORECAST, f"{chances.stale:,} district-days have no forecast run under 3 hours"
            )
        line = stale_line(chances)
        if line is not None:
            _out(f"predict: {line}")
        return chances, at

    built = _pass_file(run, model, days, now, classes, private_classes, outlook=outlook)
    built.log = log
    built.chances = holder.get("chances")
    return built


def _outlook_after(  # noqa: PLR0913, PLR0917 - the pass, its models, alerts, days and file
    run: Pass,
    model: ServeModel,
    directory: DeployedDirectory,
    classes: npt.NDArray[np.int64],
    days: tuple[date, date],
    now: datetime,
    window: Window,
    feed: Any,
    built: _Made,
) -> None:
    """Take the outlook's private record after a pass (:mod:`snowlight.predict.outlook_record`):
    with the outlook shadow, the chance it would show beside the file's; on, the file's beside
    the v2 rates' (``classes``: the v2 path's). Any error is warned and records nothing: the
    pass and its file stand as they are."""
    mode = run.outlook_mode.value
    if run.outlook_budget is not None and run.outlook_mode is OutlookMode.SHADOW:
        run.outlook_budget.start()  # on started it in the pass, before its product log
    try:
        serve = run.outlook_serve(directory)
        log = built.log
        if log is None:
            reach = memory_reach(days, model.time_zone, window)
            log = remember_products(run, feed, now, reach, back_off=True)
        count = len(directory.district_ids)
        chances = built.chances
        if chances is None:
            chances, _at = _outlook_chances(
                run, serve, directory, log, days, now, window, built.after
            )
        # Both chances as a district's page shows them: the floor where it said school is on.
        chances = replace(chances, p=as_shown(chances.p, built.said, days))
        if run.outlook_mode is OutlookMode.ON:
            v2 = as_shown_percent(_v2_percent(model, classes, built.after, days), built.said, days)

            def published(d: int) -> npt.NDArray[np.int64]:
                return v2[:, d]

        else:

            def published(d: int) -> npt.NDArray[np.int64]:
                return published_percent(built.made, count, d)

        if run.outlook_forecast is None:
            raise ServeError("no forecast reader for the outlook's samples")
        leaids = tuple(directory.district_ids)
        record, moved = carried(
            run.state.outlook, learn.content_key(directory), leaids, run._record_names
        )
        if moved is not None:
            _out(f"predict ({mode}): {moved}")
        run._record_names = Record(record.content, count, leaids=leaids)
        taken = take_record(
            record,
            serve=serve,
            log=log,
            ugcs=run.ugc_index(directory),
            days=days,
            now=now,
            window=window,
            share=run.config.weather.covered_share,
            read=run.outlook_forecast,
            published=published,
            chances=chances,
        )
        oldest = now.astimezone(UTC).date() - timedelta(days=STATE_DAYS)
        kept = record.kept(oldest)
        kept.leaids = None  # the host's record keeps them; the pass state stays small
        run.state.outlook = kept.as_json()
        run.state.outlook_health = _health(now, chances, built, taken)
        for line in (stale_line(chances) if run.outlook_mode is OutlookMode.SHADOW else None,
                     taken.line()):  # fmt: skip
            if line is not None:
                _out(f"predict ({mode}): {line}")
    except Exception as error:  # the record never touches the pass
        detail = f" ({error})" if isinstance(error, DarkError) else ""  # our own words only
        _warn(f"outlook {mode}: {type(error).__name__}: nothing recorded this pass{detail}")


def _health(now: datetime, chances: Chances, built: _Made, taken: Taken) -> dict[str, object]:
    """The state's note of the last outlook pass (``state.outlook_health``)."""
    return {
        "at": now.astimezone(UTC).isoformat(),
        "stale": chances.stale,
        "unknown": chances.unknown,
        "unsaid": chances.unsaid,
        "no_rate": chances.no_rate,
        "lines": len(chances.lines),
        "samples": taken.samples,
        "skipped": taken.skipped,
        "forecast_at": None
        if built.made.forecast_at is None
        else built.made.forecast_at.isoformat(),
        "forecast_run": None if chances.run_time is None else chances.run_time.isoformat(),
    }


def _v2_percent(
    model: ServeModel,
    classes: npt.NDArray[np.int64],
    after: dict[date, frozenset[int]],
    days: tuple[date, ...],
) -> npt.NDArray[np.int64]:
    """The v2 rates' chance of each district (the base alone), in whole percent, (districts,
    days); 255 on a day that is not a school day."""
    from snowlight.predict.serve import SITUATION_POSITION  # noqa: PLC0415
    from snowlight.predict.situations import Situation, WeatherClass  # noqa: PLC0415

    found = np.full(classes.shape, 255, dtype=np.int64)
    for d, day in enumerate(days):
        if not is_school_day(day):
            continue
        for i in range(classes.shape[0]):
            situation = Situation.of(WeatherClass(int(classes[i, d])), i in after.get(day, ()))
            found[i, d] = round(float(model.p[i, SITUATION_POSITION[situation.key]]) * 100)
    return found


def _classes(  # noqa: PLR0913, PLR0917 - the pass, its model and directory, alerts and days
    run: Pass,
    model: ServeModel,
    directory: DeployedDirectory,
    counted: list[LiveEvent],
    days: tuple[date, date],
    now: datetime,
    window: Window,
) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.int64], npt.NDArray[np.int64], str | None]:
    """Each unit's weather class per day (an alert that names heights reaching only the
    schools within them); the districts' classes with every alert reaching its whole zones,
    for the learning step's snapshots (the history labels count a zone whole, and training
    stays as it is: addendum e, E1 is serve only); and the pass's line on the alerts that
    name heights (``None``: there are none)."""
    ugcs = run.ugc_index(directory)
    heights = run.school_heights(directory)
    margin = run.config.serve.elevation_margin_feet
    share = run.config.weather.covered_share
    classes, private_classes = unit_classes(
        model, counted, ugcs, days, now, window, share, heights, margin
    )
    whole_zones = classes
    if heights is not None and any(event.elevation is not None for event in counted):
        whole_zones = district_classes(model, counted, ugcs, days, now, window, share)
    return (
        classes,
        private_classes,
        whole_zones,
        heights_said(counted, ugcs, heights, margin).line(),
    )


def _after_publish(
    run: Pass, made: PredictionsFile, directory: DeployedDirectory, now: datetime
) -> None:
    """The chance notifications, from the file the site now shows (published, or unchanged
    from the one it shows). Only on the live root; a failure only warns, and never touches
    the pass or its file."""
    if run.notify is None or run.mode is not Mode.ON:
        return
    try:
        _out(run.notify(made, directory, now))
    except Exception as error:
        # The sender's own errors name an HTTP status at most; anything else only its type.
        said = str(error) if type(error).__module__.startswith("snowlight.notify") else ""
        _warn(f"notify: {type(error).__name__} {said}".rstrip() + ": nothing sent this pass")


def _pass_file(  # noqa: PLR0913, PLR0917 - the pass, its model, days and classes
    run: Pass,
    model: ServeModel,
    days: tuple[date, date],
    now: datetime,
    classes: npt.NDArray[np.int64],
    private_classes: npt.NDArray[np.int64] | None,
    *,
    outlook: Callable[[dict[date, frozenset[int]]], tuple[Chances, datetime | None]] | None = None,
) -> _Made:
    """The pass's file within the size budget (:func:`fitted`), its bytes and gzip size, and
    the day-after sets it was made with; the host's files it reads (the last file, the day
    timelines, the opens) are read once. ``outlook``: the outlook's chances and its forecast's
    time from the day-after sets (the outlook on: the file carries its lines, and the reasons'
    terms are not used)."""
    last = _last_file(run)
    timelines: dict[date, DayTimeline | None] = {}
    closed_on = _closed_on(run, model, timelines)
    closed_schools = _closed_on(run, model, timelines, private=True)
    said = _said_open(run, model, now)
    serve = run.config.serve
    forecasts: Forecasts = NO_FORECASTS
    posted: Neighbors = UNREAD
    after = {
        day: (closed_on(previous_school_day(day)) or frozenset())
        if is_school_day(day)
        else frozenset()
        for day in days
    }
    chances: Chances | None = None
    forecast_at: datetime | None = None
    reasons = serve.reasons and outlook is None
    if outlook is not None:
        chances, forecast_at = outlook(after)
    elif serve.reasons and model.terms.fits:
        forecasts = _forecasts(run, model, days, now)
        posted = _neighbors(run, model, days, now)
    made, data, packed = fitted(
        lambda fit: forecast_file(
            model,
            classes,
            days,
            now,
            closed_on=closed_on,
            last=last,
            private_classes=private_classes,
            closed_schools=closed_schools,
            said=said,
            fit=fit,
            forecasts=forecasts,
            posted=posted,
            reasons=reasons,
            announces=serve.announces,
            outlook=chances,
            forecast_at=forecast_at,
        ),
        run.config.serve,
    )
    return _Made(made, data, packed, after, chances=chances, said=said)


def _forecasts(run: Pass, model: ServeModel, days: tuple[date, ...], now: datetime) -> Forecasts:
    """The NDFD forecast at the class snapshot for the reasons; when it cannot be read, none
    (the forecast's terms add nothing, the pass says why, and the base and neighbors stand)."""
    if run.forecast is None:
        return NO_FORECASTS
    try:
        found = run.forecast(model, days, now)
    except (OSError, ValueError, ndfd.NdfdError) as error:
        _warn(f"forecast: {type(error).__name__}: no forecast reasons this pass")
        return NO_FORECASTS
    for problem in found.problems[:5]:
        _warn(f"forecast: {problem}")
    return found


def _neighbors(run: Pass, model: ServeModel, days: tuple[date, ...], now: datetime) -> Neighbors:
    """The districts next door that posted (:mod:`snowlight.predict.nowcast`), from
    ``live/closings.json`` on the host; unreadable or invalid: unknown (no neighbors line)."""
    key = run.mode.key
    if key is None or run.host is None:
        return UNREAD
    path = f"{key.split('/', 1)[0]}/live/closings.json"
    try:
        data = run.host.read(path)
        closings = ClosingsFile.from_json_bytes(data) if data else None
    except (OSError, PublishError, ValueError) as error:
        _warn(f"{path}: {type(error).__name__}: no neighbors reasons this pass")
        return UNREAD
    return neighbors_posted(
        closings,
        stamp=model.directory.stamp,
        eligible=model.eligible,
        neighbors=model.neighbors,
        days=days,
        now=now,
        max_age=timedelta(minutes=run.config.serve.neighbors_max_age_minutes),
        share=run.config.labels.no_school_share,
    )


def fitted(
    make: Callable[[Fit], PredictionsFile], settings: ServeSettings
) -> tuple[PredictionsFile, bytes, int]:
    """The pass's file made with the first :class:`~snowlight.predict.serve.Fit` within the
    size budget and the private schools' shared tables, its bytes and its gzip size; a file
    that left anything out says what and why.

    Raises:
        DarkError: over the budget even with the least it may hold (``size``).
        TableError: the districts' file alone named too many outlooks (it names none).
    """
    why: list[str] = []
    last = list(Fit)[-1]
    for fit in Fit:
        try:
            made = make(fit)
        except TableError as error:
            if fit is last:
                raise
            if str(error) not in why:
                why.append(str(error))
            continue
        data = made.to_json_bytes()
        try:
            packed = check_budget(data, settings)
        except DarkError:
            if fit is last:
                raise
            if not any("size budget" in item for item in why):
                which = "whole file" if fit is Fit.WHOLE else f"file with no {fit.left_out}"
                why.append(f"the {which} is over the size budget ({len(data):,} bytes raw)")
            continue
        if fit is not Fit.WHOLE:
            _err(f"predict: warning: {'; '.join(why)}; published it with no {fit.left_out}")
        return made, data, packed
    raise AssertionError("Fit has a last member")


def _say_left_out(model: ServeModel) -> None:
    """Every school gets a chance every school day: a private school with no time zone cannot
    (its today is unknown), so every pass says how many, rather than drop them quietly."""
    left_out = model.private.left_out if model.private is not None else 0
    if left_out:
        _err(
            f"predict: warning: {left_out:,} private schools of the contiguous states have no "
            "time zone and get no chance"
        )


def _closed_on(
    run: Pass,
    model: ServeModel,
    timelines: dict[date, DayTimeline | None] | None = None,
    *,
    private: bool = False,
) -> Callable[[date], frozenset[int] | None]:
    """The districts (or, ``private``, the private schools by directory position) closed for
    weather on a day, from the live ingest's day timeline on the host
    (``live/days/<day>.json``, S8-D). ``None`` only when the host holds no timeline for the
    day (none was published: no unit had the day off). A timeline that cannot be read or does
    not validate darkens the pass: a chance is never published from fewer inputs.
    ``timelines`` keeps the days read, so the districts and the schools read each day once."""
    read = timelines if timelines is not None else {}

    def timeline_of(day: date) -> DayTimeline | None:
        if day in read:
            return read[day]
        key = run.mode.key
        if key is None or run.host is None:
            return None
        prefix = key.split("/", 1)[0]
        path = f"{prefix}/live/days/{day.isoformat()}.json"
        try:
            data = run.host.read(path)
        except (OSError, PublishError) as error:
            raise DarkError(Dark.DAY_FILE, f"{path}: {error}") from error
        found: DayTimeline | None = None
        if data is not None:
            try:
                found = DayTimeline.from_json_bytes(data)
            except ValueError as error:
                raise DarkError(Dark.DAY_FILE, f"{path} does not validate") from error
        read[day] = found
        return found

    def closed(day: date) -> frozenset[int] | None:
        timeline = timeline_of(day)
        if timeline is None:
            return None
        share = run.config.weather.covered_share
        if private:
            return closed_private(timeline, model)
        return closed_districts(timeline, model, share)

    return closed


def _said_open(run: Pass, model: ServeModel, now: datetime) -> SaidOpen:
    """Who said school is on (:mod:`snowlight.predict.opens`), from ``live/opens.json`` and
    ``live/closings.json`` on the host. Neither published: nothing is said. A file that cannot
    be read or does not validate darkens the pass, as a day timeline does."""
    key = run.mode.key
    if key is None or run.host is None:
        return NOTHING_SAID
    prefix = key.split("/", 1)[0]
    found: dict[str, bytes | None] = {}
    for name in ("opens", "closings"):
        path = f"{prefix}/live/{name}.json"
        try:
            found[name] = run.host.read(path)
        except (OSError, PublishError) as error:
            raise DarkError(Dark.OPENS, f"{path}: {error}") from error
    opens_data, closings_data = found["opens"], found["closings"]
    if opens_data is None:
        return NOTHING_SAID
    try:
        opens = OpensFile.from_json_bytes(opens_data)
        closings = ClosingsFile.from_json_bytes(closings_data) if closings_data else None
    except ValueError as error:
        raise DarkError(Dark.OPENS, f"{prefix}/live: {type(error).__name__}") from error
    serve = run.config.serve
    private = model.private.positions if model.private is not None else np.zeros(0, np.int64)
    try:
        return said_open(
            opens,
            closings,
            stamp=model.directory.stamp,
            eligible=model.eligible,
            private=private,
            now=now,
            max_age=timedelta(minutes=serve.opens_max_age_minutes),
        )
    except OpensError as error:
        raise DarkError(Dark.OPENS, str(error)) from error


def _last_file(run: Pass) -> PredictionsFile | None:
    """The file the host holds now, for ``previous`` (none when it does not read)."""
    key = run.mode.key
    if key is None or run.host is None:
        return None
    try:
        data = run.host.read(key)
        return None if data is None else PredictionsFile.from_json_bytes(data)
    except (ValueError, PublishError):
        return None


def make_pass(args: argparse.Namespace, env: Mapping[str, str]) -> Pass:  # pragma: no cover
    """A pass against the real world."""
    from snowlight.predict.inputs import (  # noqa: PLC0415
        AlertsHistory,
        AlertsReader,
        client,
        read_deployed,
        read_local,
    )
    from snowlight.sources.nws.boundaries import BoundaryCatalog  # noqa: PLC0415
    from snowlight.sources.nws.http import HttpCache  # noqa: PLC0415
    from snowlight.weather.timezones import TimeZoneLookup  # noqa: PLC0415

    config = PredictConfig.load(args.config)
    mode = mode_of(env.get("PREDICT_PUBLISH"))
    try:
        outlook_mode = outlook_mode_of(env.get("PREDICT_OUTLOOK"))
    except ValueError as error:
        _warn(f"{error}: the outlook is off")
        outlook_mode = OutlookMode.OFF
    host = make_host(args, env) if mode is not Mode.OFF else None
    model_bytes = Path(args.model).read_bytes()
    committed = artifact_module.ModelArtifact.from_bytes(model_bytes)
    terms = terms_file.load(Path(args.terms)) if config.serve.reasons else None
    learned = served_learned(host, mode, artifact_module.sha256_of(model_bytes))
    alerts = AlertsReader(client({"Accept": "application/geo+json"}))
    history = AlertsHistory(client({"Accept": "application/geo+json"}))
    catalog = BoundaryCatalog(HttpCache(client()), args.weather_cache)
    today = datetime.now(UTC).date()
    zones = catalog.boundaries_for("zone", today)
    counties = catalog.boundaries_for("county", today)
    if zones is None or counties is None:
        raise ConfigError("no NWS boundary release is in effect")
    lookup = TimeZoneLookup(counties, zones)
    areas = {**zones.areas, **counties.areas}
    elevation = PinnedTable(
        read=lambda: _load_heights(args),
        retry=timedelta(minutes=HEIGHTS_RETRY_MINUTES),
        clock=lambda: datetime.now(UTC),
    )

    def directory() -> DeployedDirectory:
        if args.site_data is not None:
            return read_local(args.site_data)
        return read_deployed(args.site, args.repository, env.get("GITHUB_TOKEN"))

    def ugcs(found: DeployedDirectory) -> UgcIndex:
        points = found.points
        return UgcIndex.build(
            points.lon_e6.astype(np.float64) * 1e-6, points.lat_e6.astype(np.float64) * 1e-6, areas
        )

    outlook = _outlook_parts(
        config, Path(args.outlook_model), host, mode, outlook_mode, history.read
    )
    return Pass(
        config=config,
        mode=mode,
        host=host,
        directory=directory,
        alerts=alerts.read,
        ugcs=ugcs,
        zone_fallback=lambda lon, lat: lookup.zone_for(None, lat, lon),
        model=lambda: committed,
        learned=learned,
        state=load_state(args.state),
        write=args.write,
        history=history.read,
        notify=_make_notifier(env, host, mode),
        heights=lambda found: school_heights(elevation.current(), found.school_ids, found.points),
        terms=terms,
        model_sha256=artifact_module.sha256_of(model_bytes),
        forecast=_live_forecast(config) if config.serve.reasons else None,
        **outlook,
    )


def _outlook_parts(  # noqa: PLR0913, PLR0917  # pragma: no cover - the files, the host and AWS
    config: PredictConfig,
    path: Path,
    host: Host | None,
    mode: Mode,
    outlook_mode: OutlookMode,
    read_history: Callable[..., list[NwsAlert]],
) -> dict[str, Any]:
    """The outlook's parts of a pass (:func:`outlook_parts`, over the real readers)."""
    from snowlight.predict.inputs import PRODUCT_EVENTS  # noqa: PLC0415

    def parts() -> dict[str, Any]:
        budget = Budget()

        def product_history(start: datetime, end: datetime) -> Sequence[NwsAlert]:
            return read_history(start, end, events=PRODUCT_EVENTS, before=budget.left)

        read = _outlook_model(path, host, mode)
        read()  # read now: a file that does not read turns the outlook off, never a pass dark
        return {
            "outlook_model": read,
            "outlook_forecast": _outlook_reader(config, budget),
            "outlook_newest": _outlook_newest() if outlook_mode is OutlookMode.ON else None,
            "outlook_learned": _outlook_learned(path, host, mode),
            "outlook_budget": budget,
            "product_history": product_history,
        }

    return outlook_parts(outlook_mode, parts)


def outlook_parts(outlook_mode: OutlookMode, parts: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """The outlook's parts of a pass: none with it off; with it shadow or on, ``parts()``, or,
    when any of them fails to build (a missing ``model-f.json.gz``, a host that does not read,
    anything), a warning and the outlook off. Only the outlook's own inputs are built here, so
    nothing of the outlook can stop a run before its first pass."""
    if outlook_mode is OutlookMode.OFF:
        return {"outlook_mode": OutlookMode.OFF}
    try:
        found = parts()
    except Exception as error:  # any failure of the outlook's inputs
        _warn(f"outlook {outlook_mode.value}: {type(error).__name__}: {error}: the outlook is off")
        return {"outlook_mode": OutlookMode.OFF}
    return {"outlook_mode": outlook_mode, **found}


def _load_heights(args: argparse.Namespace) -> Loaded:  # pragma: no cover - the release
    """The pinned elevation table (:mod:`snowlight.predict.heights`), or none, said why."""
    from snowlight.predict.inputs import client  # noqa: PLC0415

    def get(url: str) -> bytes:
        try:
            with client() as http:
                response = http.get(url)
        except httpx.HTTPError as error:
            raise OSError(type(error).__name__) from error
        if response.status_code != httpx.codes.OK:
            raise OSError(f"HTTP {response.status_code}")
        return response.content

    loaded = load_pinned(load_pins(args.elevation_pins), args.elevation_cache, get)
    if loaded.table is None:
        _warn(f"predict: {loaded.problem}: no school's height is known")
    else:
        _out(
            f"predict: elevation table of {len(loaded.table.rows):,} schools "
            f"({loaded.table.unknown:,} with no height)"
        )
    return loaded


def _live_forecast(
    config: PredictConfig,
) -> Callable[[ServeModel, tuple[date, ...], datetime], Forecasts]:  # pragma: no cover - AWS
    """Reads the NDFD runs from AWS for each pass, each run's values once (kept between
    passes), with the history's reader (:mod:`snowlight.predict.forecast_live`)."""
    from snowlight.predict import forecast_live  # noqa: PLC0415

    http = forecast_history._client()
    fetcher = forecast_history.Fetcher(http)
    cache: dict[tuple[datetime, date], forecast_history.RunValues] = {}
    built: dict[object, tuple[forecast_history.Schools, dict[str, int]]] = {}

    def read(model: ServeModel, days: tuple[date, ...], now: datetime) -> Forecasts:
        stamp = model.directory.stamp
        if stamp not in built:
            built.clear()
            cache.clear()
            schools = forecast_history.deciding_schools(model.directory, model.artifact)
            index = {leaid: i for i, leaid in enumerate(model.directory.district_ids)}
            built[stamp] = (schools, index)
        schools, index = built[stamp]
        listings = forecast_history.Listings(fetcher.get)

        def runs_for(day: date) -> list[ndfd.Run] | None:
            around = listings.around(day)
            if around.error is not None:
                return None
            return list(ndfd.assemble_runs(around.listed).runs)

        reader = forecast_live.run_reader(schools, fetcher.opener(), cache)
        return forecast_live.forecasts(
            schools,
            index,
            days,
            now,
            runs_for,
            reader,
            config.weather.covered_share,
        )

    return read


def _outlook_model(
    path: Path, host: Host | None, mode: Mode
) -> Callable[[], tuple[artifact_module.ModelArtifact, Outlook]]:  # pragma: no cover - the file
    """Reads the v3 rates and ``T`` (``data/predict/model-f.json.gz``) once, with the live cases
    S7-L swapped in (``predictions/outlook/learned.json`` on the host, when it was made over
    this artifact and reads)."""
    from snowlight.predict import outlook as outlook_module  # noqa: PLC0415

    found: list[tuple[artifact_module.ModelArtifact, Outlook]] = []

    def read() -> tuple[artifact_module.ModelArtifact, Outlook]:
        if not found:
            data = path.read_bytes()
            rates = outlook_module.read_rates(path)
            _rates, table = outlook_module.read_artifact(path)
            learned = None
            if host is not None and mode.key is not None:
                key = f"{mode.key.split('/', 1)[0]}/{ol.LEARNED_PATH}"
                try:
                    learned = host.read(key)
                except PublishError as error:
                    _warn(f"{key} unreadable ({error}); the committed outlook serves")
            table, why = ol.served_outlook(table, learned, artifact_module.sha256_of(data))
            if why is not None:
                _warn(f"outlook: {why}")
            found.append((rates, table))
        return found[0]

    return read


def _outlook_learned(
    path: Path, host: Host | None, mode: Mode
) -> artifact_module.Learned | None:  # pragma: no cover - the live host
    """The v3 rates' learned file on the host, when it was made over this ``model-f.json.gz``
    and reads (else ``None`` and why)."""
    key = mode.key
    if host is None or key is None:
        return None
    where = f"{key.split('/', 1)[0]}/{ol.RATES_LEARNED_PATH}"
    try:
        data = host.read(where)
    except PublishError as error:
        _warn(f"{where} unreadable ({error}); the committed v3 rates")
        return None
    found, why = learn.read_learned(data, artifact_module.sha256_of(path.read_bytes()))
    if why is not None:
        _warn(f"outlook: {why}; the committed v3 rates")
    return found


def _outlook_reader(config: PredictConfig, budget: Budget) -> ReadForecast:  # pragma: no cover
    """Reads the NDFD runs from AWS for the outlook (:func:`~snowlight.predict.outlook_live.
    forecast_reader`): short request limits, few tries, and every request inside ``budget``."""
    http = forecast_history._client()
    http.timeout = READ_TIMEOUT
    fetcher = forecast_history.Fetcher(http, attempts=READ_ATTEMPTS, before=budget.check)
    return forecast_reader(fetcher, config.weather.covered_share)


def _outlook_newest() -> Callable[[datetime], datetime | None]:  # pragma: no cover - AWS
    """The newest complete NDFD run that counts at a moment, from the AWS day listings (the
    previous UTC day's too, for the first hours after 00Z); ``None`` when they do not list."""
    http = forecast_history._client()
    http.timeout = READ_TIMEOUT
    fetcher = forecast_history.Fetcher(http, attempts=READ_ATTEMPTS)

    def newest(now: datetime) -> datetime | None:
        around = forecast_history.Listings(fetcher.get).around(now.astimezone(UTC).date())
        if around.error is not None:
            return None
        run = ndfd.newest_run(list(ndfd.assemble_runs(around.listed).runs), now)
        return None if run is None else run.time

    return newest


def _make_notifier(  # pragma: no cover - the real world
    env: Mapping[str, str], host: Host | None, mode: Mode
) -> Callable[[PredictionsFile, DeployedDirectory, datetime], str] | None:
    """The chance notifier (docs/notify.md), or ``None`` without the Cloudflare secrets or
    off the live root."""
    from snowlight.notify.cli import chance_notifier  # noqa: PLC0415
    from snowlight.notify.cli import make_client as notify_client  # noqa: PLC0415

    key = mode.key
    if host is None or key is None or mode is not Mode.ON:
        return None
    closings_key = f"{key.split('/', 1)[0]}/live/closings.json"
    notifier = chance_notifier(env, notify_client(), closings=lambda: host.read(closings_key))
    if notifier is None:
        _out("predict: no Cloudflare secrets: no notification is sent")
    return notifier


def served_learned(
    host: Host | None, mode: Mode, archive_sha256: str
) -> artifact_module.Learned | None:
    """The learned file on the host the serving pass uses with the committed model, or
    ``None`` (none there, unreadable, or made over another committed model: the committed
    model alone serves, and the reason is warned)."""
    key = mode.key
    if host is None or key is None:
        return None
    path = f"{key.split('/', 1)[0]}/{learn.LEARNED_PATH}"
    try:
        data = host.read(path)
    except PublishError as error:
        _warn(f"{path} unreadable ({error}); serving the committed model")
        return None
    found, why = learn.read_learned(data, archive_sha256)
    if why is not None:
        _warn(f"{why}; serving the committed model")
    return found


def run_once(
    args: argparse.Namespace, env: Mapping[str, str] | None = None
) -> int:  # pragma: no cover
    """Run ``predict once``."""
    environment = dict(os.environ) if env is None else env
    try:
        run = make_pass(args, environment)
    except (ConfigError, ValueError, OSError) as error:
        _err(f"predict once: error: {error}")
        return 1
    code = safe_pass(run, grid=True)
    save_state(args.state, run.state)
    return code


def parse_until(text: str, now: datetime) -> datetime:
    """``+330m`` / ``+5h`` from now, or an ISO 8601 moment with its offset.

    Raises:
        ValueError: neither.
    """
    match = re.fullmatch(r"\+(\d+)([mh])", text)
    if match:
        amount = int(match[1])
        return now + (timedelta(minutes=amount) if match[2] == "m" else timedelta(hours=amount))
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        raise ValueError(f"no UTC offset in {text!r}")
    return moment


def next_grid(now: datetime, minutes: tuple[int, ...]) -> datetime:
    """The next moment after ``now`` whose minute is on the grid."""
    base = now.replace(second=0, microsecond=0)
    for step in range(1, 61 * 2):
        moment = base + timedelta(minutes=step)
        if moment.minute in minutes:
            return moment
    raise ValueError("an empty grid")


@dataclass(slots=True)
class Loop:
    """The loop's clock and sleep (tests replace them)."""

    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    sleep: Callable[[float], None] = time.sleep


def safe_pass(run: Pass, *, grid: bool) -> int:
    """:func:`one_pass`, with any error it did not foresee counted as a dark pass (the loop
    goes on; the old file ages out on its own)."""
    try:
        return one_pass(run, grid=grid)
    except Exception as error:
        _err(f"predict: dark (unexpected {type(error).__name__}: {error})")
        return EXIT_DARK


def loop(run: Pass, until: datetime, clock: Loop, save: Callable[[State], None]) -> int:
    """Passes on the grid and when the alerts change, until ``until``.

    * A pass on every grid minute (:07 and :37): the loop sleeps until the next check or the
      next grid minute, whichever comes first, so grid passes do not drift.
    * Between them, every ``check_minutes``: a pass when the alerts differ from the ones the
      last good pass was made from, or when the last pass went dark (try again), at most
      one per ``min_gap_minutes``.
    * The state is saved after every pass.

    Returns the number of dark passes (each printed as it happens); the watchdog
    (``predict check``) judges whether the public file stayed fresh.
    """
    serve = run.config.serve
    dark = 0
    retry = False
    last_pass: datetime | None = None
    grid_at = clock.now()
    while clock.now() < until:
        now = clock.now()
        on_grid = now >= grid_at
        changed = False
        if not on_grid:
            try:
                feed, _fresh = run.alerts()
                changed = alerts_digest(live_events(feed)) != run.state.alerts_digest
            except Exception:
                changed = False
        if not on_grid and not changed:
            changed = outlook_changed(run, last_pass, now)
        gap_ok = last_pass is None or now - last_pass >= timedelta(minutes=serve.min_gap_minutes)
        if on_grid or ((changed or retry) and gap_ok):
            code = safe_pass(run, grid=on_grid)
            retry = code == EXIT_DARK
            if retry:
                dark += 1
                _warn("a pass stayed dark; the next check tries again")
            try:
                save(run.state)
            except OSError as error:
                _warn(f"the state did not save: {error}")
            last_pass = now
            if on_grid:
                grid_at = next_grid(clock.now(), serve.grid_minutes)
        wake = min(clock.now() + timedelta(minutes=serve.check_minutes), grid_at, until)
        clock.sleep(max(1.0, (wake - clock.now()).total_seconds()))
    return dark


PERIOD_HOURS: Final = 6
"""The forecast's snow and ice periods end every 6 hours (00, 06, 12, 18 UTC)."""


def outlook_changed(run: Pass, last: datetime | None, now: datetime) -> bool:
    """With the outlook on, whether a pass is due for it between grid passes (spec-f s. 7): a
    slot boundary or 05:00 passed in a district's zone since the last pass, a forecast period
    ended, or a newer forecast run counts than the last pass read. Never with the outlook off
    or shadow (their passes stay S7-L's), and never on an error (the grid passes stand)."""
    if run.outlook_mode is not OutlookMode.ON or last is None:
        return False
    try:
        if int(now.timestamp()) // (PERIOD_HOURS * 3600) != int(last.timestamp()) // (
            PERIOD_HOURS * 3600
        ):
            return True
        built = run._built
        zones = sorted(set(built[1].time_zone)) if built is not None else []
        days = pass_days(now, run.config)
        for zone in zones:
            for day in days:
                if slot_at(day, zone, last) != slot_at(day, zone, now):
                    return True
        if run.outlook_newest is not None:
            newest = run.outlook_newest(now)
            read = run.state.outlook_health.get("forecast_run")
            if newest is not None and newest.isoformat() != read:
                return True
    except Exception:
        return False
    return False


def _warn(text: str) -> None:
    prefix = "::warning::" if os.environ.get("GITHUB_ACTIONS") == "true" else "warning: "
    _err(prefix + text)


def run_loop(args: argparse.Namespace) -> int:  # pragma: no cover - the real world
    """Run ``predict run``."""
    env = dict(os.environ)
    try:
        until = parse_until(args.until, datetime.now(UTC))
        run = make_pass(args, env)
    except (ConfigError, ValueError, OSError) as error:
        _err(f"predict run: error: {error}")
        return 1
    dark = loop(run, until, Loop(), lambda state: save_state(args.state, state))
    _out(f"predict run: done, {dark} dark passes")
    return 0


def run_blank(args: argparse.Namespace) -> int:  # pragma: no cover - the real host
    """Run ``predict blank``: set the hold, then put a file with no districts in ``v1/`` and
    ``v1-shadow/``. Every later upload is refused until ``predict release``."""
    env = dict(os.environ)
    try:
        run = make_pass(args, env)
        directory = run.directory()
        host = make_host(args, env)
    except (ConfigError, DarkError, ValueError, OSError) as error:
        _err(f"predict blank: error: {error}")
        return 1
    try:
        return blank(host, directory.stamp, run.config, datetime.now(UTC))
    except PublishError as error:
        _err(f"predict blank: error: {error}")
        return 1


def blank(host: Host, stamp: Any, config: PredictConfig, now: datetime) -> int:
    """Set the hold in both folders (a write of its own, first), then write the empty files.

    Raises:
        PublishError: the host failed (the hold may already be set).
    """
    keys = [key for mode in (Mode.ON, Mode.SHADOW) if (key := mode.key) is not None]
    host.write({hold_key(key): hold_file(now, set_hold=True, began=None) for key in keys})
    _out("predict blank: hold set")
    data = blank_file(stamp, pass_days(now, config), now)
    host.write(dict.fromkeys(keys, data))
    for key in keys:
        if host.read(key) != data:
            raise PublishError(f"read back {key}")
        _out(f"predict blank: {key}")
    return 0


def release(host: Host, now: datetime) -> int:
    """Clear the hold in both folders: the next pass publishes.

    Raises:
        PublishError: the host failed.
    """
    files: dict[str, bytes] = {}
    for mode in (Mode.ON, Mode.SHADOW):
        key = mode.key
        if key is None:
            continue
        before = host.read(hold_key(key))
        began = None
        if before is not None:
            try:
                began = LiveHold.from_bytes(before).held_at
            except (KeyError, TypeError, ValueError):
                began = None
        files[hold_key(key)] = hold_file(now, set_hold=False, began=began)
    host.write(files)
    _out("predict release: hold cleared")
    return 0


def run_release(args: argparse.Namespace) -> int:  # pragma: no cover - the real host
    """Run ``predict release``."""
    try:
        host = make_host(args, dict(os.environ))
        return release(host, datetime.now(UTC))
    except (ConfigError, PublishError, OSError) as error:
        _err(f"predict release: error: {error}")
        return 1


def parse_age(text: str) -> timedelta:
    """``45m`` or ``2h``.

    Raises:
        ValueError: neither.
    """
    match = re.fullmatch(r"(\d+)([mh])", text)
    if not match:
        raise ValueError(f"not an age: {text!r}")
    amount = int(match[1])
    return timedelta(minutes=amount) if match[2] == "m" else timedelta(hours=amount)


def check_file(data: bytes | None, now: datetime, max_age: timedelta) -> str | None:
    """Why the public file is not healthy, or ``None``."""
    if data is None:
        return "missing"
    try:
        found = PredictionsFile.from_json_bytes(data)
    except ValueError:
        return "invalid"
    if found.generated_at > now + timedelta(minutes=15):
        return "ahead"
    if now - found.generated_at > max_age:
        return f"stale ({found.generated_at.isoformat()})"
    if not found.districts:
        return "blank"
    return None


def run_check(args: argparse.Namespace) -> int:  # pragma: no cover - the live host
    """Run ``predict check``: 0 fresh, 3 stale, missing, invalid or blank."""
    from snowlight.predict.inputs import client  # noqa: PLC0415

    with client() as http:
        try:
            response = http.get(args.url, headers={"Cache-Control": "no-cache"})
            data = response.content if response.status_code == 200 else None  # noqa: PLR2004
        except Exception as error:
            _err(f"predict check: {type(error).__name__}")
            return EXIT_DARK
    problem = check_file(data, datetime.now(UTC), parse_age(args.max_age))
    if problem is not None:
        _err(f"predict check: {problem}")
        return EXIT_DARK
    _out("predict check: fresh")
    return 0


# --- learning -----------------------------------------------------------------------------------


@dataclass(slots=True)
class LearnRun:
    """Everything ``predict learn`` needs, as values and callables (tests replace them)."""

    config: PredictConfig
    host: Host
    prefix: str
    """``v1``, ``v1-shadow``, or the local folder's ``v1`` when publishing is off."""
    source: Any
    """The live days (:class:`snowlight.predict.live_labels.LiveSource`)."""
    model: ServeModel
    """The committed model alone, on the deployed directory (its districts, schools, zones)."""
    archive_sha256: str
    snapshots: Mapping[str, object]
    build: Callable[[artifact_module.Learned | None], ServeModel]
    now: datetime
    outlook_mode: OutlookMode = OutlookMode.OFF
    """``PREDICT_OUTLOOK``: shadow or on, the step also learns the outlook
    (:mod:`snowlight.predict.outlook_learn`)."""
    outlook_state: Mapping[str, object] = field(default_factory=dict)
    """The passes' outlook record (their private state)."""
    outlook: Callable[[], tuple[OutlookServe, str]] | None = None
    """The v3 rates on the deployed directory with the committed ``T``, and the artifact's
    SHA-256."""
    outlook_build: Callable[[artifact_module.Learned | None], ServeModel] | None = None
    """Builds the v3 rates' serving model with a learned file (or none): the v3 rates learn
    from the 05:00 record's labels under their own no-worse swap (spec-f s. 10)."""


def learn_once(run: LearnRun) -> int:
    """One learning run (:mod:`snowlight.predict.learn`): 0 swapped or nothing to change,
    :data:`~snowlight.predict.learn.EXIT_KEPT` kept because the refit was worse, 1 an error
    (nothing written)."""
    store_key = f"{run.prefix}/{learn.LEARN_PATH}"
    learned_key = f"{run.prefix}/{learn.LEARNED_PATH}"
    try:
        stored = run.host.read(store_key)
        store = learn.LearnStore.empty() if stored is None else learn.LearnStore.from_bytes(stored)
    except (PublishError, ValueError) as error:
        _err(f"predict learn: error: {store_key} cannot be read ({type(error).__name__}): "
             "nothing is changed")  # fmt: skip
        return 1
    try:
        current, why = learn.read_learned(run.host.read(learned_key), run.archive_sha256)
    except PublishError as error:
        _err(f"predict learn: error: {learned_key} cannot be read ({error}): nothing is changed")
        return 1
    if why is not None:
        _out(f"predict learn: {why}; the served model is the committed one")
    try:
        labeling = learn.label_new_days(
            store, run.source, learn.directory_of(run.model), run.snapshots, run.config, run.now
        )
    except (PublishError, sqlite3.Error, ValueError, OSError) as error:
        _err(f"predict learn: error: the live days cannot be read ({type(error).__name__}): "
             "nothing is changed")  # fmt: skip
        return 1
    for reason, count in sorted(labeling.skipped.items()):
        _out(f"predict learn: {count} school days not labeled: {reason}")
    if labeling.added:
        days = ", ".join(day.isoformat() for day in labeling.added)
        _out(f"predict learn: labeled the live days {days}")
    decision = learn.decide(
        labeling.store, current, run.build, run.archive_sha256, run.config, run.now
    )
    files: dict[str, bytes] = {}
    if labeling.added:
        files[store_key] = labeling.store.to_bytes()
    if decision.kind in ("swap", "reset") and decision.learned is not None:
        files[learned_key] = decision.learned.to_bytes()
    if files:
        try:
            run.host.write(files)
            if any(run.host.read(key) != data for key, data in files.items()):
                raise PublishError("the files read back are not the ones written")
        except PublishError as error:
            _err(f"predict learn: error: {error}: the served model is as it was")
            return 1
    _out(f"predict learn: {decision.why}")
    if run.outlook_mode is not OutlookMode.OFF:
        _learn_outlook(run, labeling.store)
    return learn.EXIT_KEPT if decision.kind == "keep" else 0


def _learn_outlook(run: LearnRun, store: learn.LearnStore) -> None:
    """The outlook's learning step (:mod:`snowlight.predict.outlook_learn`): it never changes
    the step's own outcome; an error is warned and writes nothing."""
    try:
        if run.outlook is None:
            raise ServeError("no outlook model is given")
        serve, sha = run.outlook()
        step = outlook_step(run, store, serve, sha)
        if step.files:
            run.host.write(step.files)
            if any(run.host.read(key) != data for key, data in step.files.items()):
                raise PublishError("the files read back are not the ones written")
        for line in step.lines:
            _out(f"predict learn: {line}")
    except Exception as error:  # the outlook never touches the step's own outcome
        _warn(f"predict learn: outlook: {type(error).__name__}: nothing written")


def _learn_v3_rates(
    run: LearnRun, record: Record, sha: str, step: ol.Step
) -> learn.LearnStore | None:
    """The v3 rates' S7-L (spec-f s. 10, (1)): the live days labeled under the 05:00 record's
    class (``predictions/outlook/learn.json``) and the refit swapped in under S7-L's own
    no-worse check (``predictions/outlook/learned-rates.json``, over ``model-f.json.gz``).
    Returns the store, or ``None`` when its file does not read (then nothing of it is
    written)."""
    if run.outlook_build is None:
        return None
    store_key = f"{run.prefix}/{ol.RATES_STORE_PATH}"
    learned_key = f"{run.prefix}/{ol.RATES_LEARNED_PATH}"
    try:
        stored = run.host.read(store_key)
        store = learn.LearnStore.empty() if stored is None else learn.LearnStore.from_bytes(stored)
    except ValueError:
        step.lines.append("outlook: the v3 rates' labels do not read: nothing of them changes")
        return None
    current, why = learn.read_learned(run.host.read(learned_key), sha)
    if why is not None:
        step.lines.append(f"outlook: v3 rates: {why}; the committed v3 rates")
    model = run.outlook_build(None)
    labeling = learn.label_new_days(
        store,
        run.source,
        learn.directory_of(model),
        ol.morning_snapshots(record),
        run.config,
        run.now,
    )
    if labeling.added:
        step.files[store_key] = labeling.store.to_bytes()
        step.lines.append(
            "outlook: v3 rates labeled " + ", ".join(day.isoformat() for day in labeling.added)
        )
    decision = learn.decide(labeling.store, current, run.outlook_build, sha, run.config, run.now)
    step.lines.append(f"outlook: v3 rates: {decision.why}")
    if decision.kind in ("swap", "reset") and decision.learned is not None:
        step.files[learned_key] = decision.learned.to_bytes()
    return labeling.store


def _host_record(run: LearnRun, model: ServeModel, step: ol.Step) -> Record:
    """The host's record with the passes' days taken in (written when it changed). A record of
    another directory content is carried over by LEAID (:func:`~snowlight.predict.
    outlook_record.carried`), so a new directory loses none of the days not yet counted."""
    content = learn.content_key(model.directory)
    record_key = f"{run.prefix}/{RECORD_PATH}"
    stored = run.host.read(record_key)
    try:
        kept = json.loads(stored) if stored else None
    except ValueError:
        kept = None
        step.lines.append("outlook: the host's record does not read: it starts again")
    leaids = tuple(model.directory.district_ids)
    host_record, moved = carried(kept, content, leaids)
    state_record, state_moved = carried(run.outlook_state, content, leaids, Record.read_any(kept))
    step.lines.extend(line for line in (moved, state_moved) if line is not None)
    record = merged(host_record, state_record, model.time_zone)
    record.leaids = leaids
    data = json.dumps(record.as_json(), sort_keys=True, separators=(",", ":")).encode()
    if data != stored:
        step.files[record_key] = data
    return record


def outlook_step(run: LearnRun, store: learn.LearnStore, serve: OutlookServe, sha: str) -> ol.Step:
    """What the outlook's learning step writes (see :mod:`snowlight.predict.outlook_learn`)."""
    step = ol.Step()
    model = serve.rates
    cases_key = f"{run.prefix}/{ol.CASES_PATH}"
    learned_key = f"{run.prefix}/{ol.LEARNED_PATH}"
    record = _host_record(run, model, step)
    found = run.host.read(cases_key)
    cases = ol.LiveCases.empty() if found is None else ol.LiveCases.from_bytes(found)
    cases, added = ol.count_days(cases, record, model.time_zone, serve.state_index, run.now)
    if added:
        step.files[cases_key] = cases.to_bytes()
        step.lines.append(
            "outlook: counted the live cases of " + ", ".join(d.isoformat() for d in added)
        )
    current: ol.LearnedOutlook | None = None
    held = run.host.read(learned_key)
    if held is not None:
        try:
            current = ol.LearnedOutlook.from_bytes(held)
        except ValueError:
            step.lines.append(
                "outlook: the learned T does not validate: judged against the committed T"
            )
        if current is not None and current.artifact_sha256 != sha:
            current = None
    rates_store = _learn_v3_rates(run, record, sha, step)
    rows = store.rows()
    if rates_store is not None and rates_store.days:
        rows = pl.concat([rows, rates_store.rows()]).unique(["district", "day"], keep="first")
    labels = ol.labels_of(rows, model.directory.district_ids)
    decision = ol.decide(
        serve.outlook, current, cases, sha, run.now, ol.e20_score(serve, record, labels)
    )
    step.lines.append(decision.why)
    if decision.kind == "swap" and decision.learned is not None:
        step.files[learned_key] = decision.learned.to_bytes()
        current = decision.learned
    served = ol.with_live(serve.outlook, current.days if current is not None else [])
    made = ol.report(serve, served, record, labels, run.now, run.model)
    report_key = f"{run.prefix}/{ol.REPORT_PATH}"
    if ol.report_changed(run.host.read(report_key), made):
        step.files[report_key] = json.dumps(made, sort_keys=True).encode()
    step.lines.append(ol.summary_line(made))
    return step


NO_STATE_WHERE: Final = (
    "no ledger in out/internal/live/state and no packed state in out/internal/live/store "
    "(the live loop's Actions cache, keys live-state-*)"
)


def live_state_folder(state: Path, store: Path, scratch: Path) -> Path | None:
    """The live ingest's state folder to read: ``state`` when it holds the row ledger (the
    box), else the packed state in ``store`` (the Actions cache) unpacked into ``scratch``,
    else ``None`` (no live day was read here).

    Raises:
        snowlight.live.state.StateError: the packed state is damaged.
    """
    from snowlight.live.state import ARCHIVE, unpack  # noqa: PLC0415

    if (state / LEDGER).is_file():
        return state
    packed = store / ARCHIVE
    if not packed.is_file():
        return None
    unpack(packed.read_bytes(), scratch)
    return scratch if (scratch / LEDGER).is_file() else None


EVIDENCE_SECONDS: Final = 30.0
"""Seconds ``predict evidence`` starts new writes for (the rest waits for the next run)."""
EVIDENCE_FOR: Final = 45.0
"""Seconds its push gives the Cloudflare API in all."""
EVIDENCE_ASK_FOR: Final = 15.0
"""Seconds it then gives the question of what both databases hold (the step's own limit is
2 minutes)."""


def _state_json(state: Path) -> dict[str, Any] | None:
    """The pass state at ``state`` as JSON; ``None`` when there is none or it does not read."""
    try:
        found = json.loads(state.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return found if isinstance(found, dict) else None


def snapshots_of(state: Path) -> dict[str, object]:
    """The weather-class snapshots of the pass state at ``state`` (none when it does not read)."""
    found = (_state_json(state) or {}).get("snapshots")
    return dict(found) if isinstance(found, dict) else {}


def tables_of(state: Path) -> dict[str, tuple[str, ...]]:
    """The district tables the pass state keeps until a database holds them."""
    found = (_state_json(state) or {}).get("tables")
    if not isinstance(found, dict):
        return {}
    return {
        str(key): tuple(str(leaid) for leaid in table)
        for key, table in found.items()
        if isinstance(table, list)
    }


def kept_of(state: Path) -> PredictKept:
    """What the pass state knows the evidence databases hold."""
    return PredictKept.of((_state_json(state) or {}).get("evidence"))


def note_kept(state: Path, known: PredictKept) -> bool:
    """Write ``known`` as the pass state's ``evidence`` entry, nothing else changed (the next
    pass reads it: :func:`snowlight.predict.live_labels.record_snapshots`). False, and nothing
    written, when the state does not read."""
    found = _state_json(state)
    if found is None:
        return False
    found["evidence"] = known.as_json()
    write_bytes_atomic(state, json.dumps(found, sort_keys=True).encode())
    return True


def ask_kept(  # noqa: PLR0913, PLR0917 - the store, what to ask of, what was known and when
    store: Any,
    snapshots: Mapping[str, object],
    contents: Iterable[str],
    known: PredictKept,
    now: datetime,
    seconds: float | None = None,
) -> PredictKept:
    """``known`` with the databases' answer of which snapshots and district tables they hold
    (a database that does not answer keeps what was known of it; none answering changes
    nothing). The grace of the ``evidence`` check counts from the first such question. It
    never raises."""
    from snowlight.live import evidence  # noqa: PLC0415

    if known.watch_from is None:
        known = PredictKept(now, known.snapshots, known.tables)
    try:
        held = store.held((evidence.SNAPSHOT, evidence.DISTRICTS), seconds=seconds)
    except Exception as error:
        _err(f"predict evidence: what the databases hold: {type(error).__name__}; it stays")
        return known
    return fold_predict(known, held, snapshots, set(contents) | contents_of(snapshots))


EVIDENCE_DIR: Final = PIPELINE_ROOT / "out" / "internal" / "predict" / "evidence"
"""What ``predict learn`` leaves for ``predict evidence`` in the same run (a private folder):
the district table of the directory it read (``districts.json``: its content key to its
LEAIDs in table order) and the labels it published (``learn.json``), so the evidence step
reads neither the deployed site nor the live host again."""
LABELS_FILE: Final = "learn.json"
TABLES_FILE: Final = "districts.json"


def leave_for_evidence(
    folder: Path, *, directory: DeployedDirectory | None = None, labels: bytes | None = None
) -> None:
    """Write the directory's district table and the labels into ``folder``. It never raises
    (the evidence step then reads the deployed directory itself, and keeps no labels)."""
    try:
        if directory is not None:
            key = learn.content_key(directory)
            if evidence_key(key):
                table = {key: list(directory.district_ids)}
                write_bytes_atomic(folder / TABLES_FILE, json.dumps(table).encode())
        if labels is not None:
            write_bytes_atomic(folder / LABELS_FILE, labels)
    except OSError as error:
        _err(f"predict learn: the evidence files: {type(error).__name__}")


def evidence_key(key: str) -> bool:
    from snowlight.live import evidence  # noqa: PLC0415

    return evidence.KEY.fullmatch(key) is not None


def left_for_evidence(folder: Path) -> tuple[dict[str, tuple[str, ...]], bytes | None]:
    """The district tables and labels :func:`leave_for_evidence` wrote (none when absent)."""
    tables: dict[str, tuple[str, ...]] = {}
    try:
        found = json.loads((folder / TABLES_FILE).read_bytes())
        if isinstance(found, dict):
            tables = {
                str(key): tuple(str(leaid) for leaid in table)
                for key, table in found.items()
                if isinstance(table, list)
            }
    except (OSError, ValueError):
        tables = {}
    try:
        labels = (folder / LABELS_FILE).read_bytes()
    except OSError:
        labels = None
    return tables, labels


def keep_evidence(
    store: Any,
    snapshots: Mapping[str, object],
    tables: Mapping[str, Sequence[str]],
    now: datetime,
    labels: bytes | None = None,
) -> int:
    """Keep the finished snapshots, every district table given (the directory content this
    run read: kept as soon as it is deployed, before any snapshot indexes it) and the labels
    (``learn.json``, every version) in the evidence store (:mod:`snowlight.live.evidence`);
    print one line a database, and a warning for a finished snapshot whose content has no
    table kept anywhere (its indexes could not be read back). 0 when every database kept
    them, 1 otherwise."""
    from snowlight.live import evidence  # noqa: PLC0415
    from snowlight.live.d1 import D1Error  # noqa: PLC0415

    offers = evidence.snapshot_offers(snapshots, tables, now)
    if labels is not None:
        offers.append(evidence.Offer(evidence.LABELS, "learn", labels))
    kinds = (evidence.SNAPSHOT, evidence.DISTRICTS, evidence.LABELS)
    try:
        reports = store.push(offers, kinds)
        failed = ""
    except evidence.PartialPushError as error:
        reports, failed = list(error.reports), str(error)
    except D1Error as error:
        _err(f"::error::predict evidence: {error}")
        return 1
    for report in reports:
        wait = f", {report.left} wait for the next run" if report.left else ""
        held = "" if report.stored is None else f"; it holds {report.stored} B in all"
        _out(
            f"predict evidence {report.database}: {len(offers)} finished files offered,"
            f" {report.held} held before, {report.kept} kept and read back ({report.copied}"
            f" copied from the other database), {report.bytes} B,"
            f" {report.rows_written} rows written{wait}{held}"
        )
    _warn_untabled(store, snapshots, tables, now)
    if failed:
        _err(f"::error::predict evidence: {failed}")
        return 1
    return 0


def _warn_untabled(
    store: Any, snapshots: Mapping[str, object], tables: Mapping[str, Sequence[str]], now: datetime
) -> None:
    from snowlight.live import evidence  # noqa: PLC0415

    contents = {
        str(entry["content"])
        for offer in evidence.snapshot_offers(snapshots, {}, now)
        if isinstance(entry := snapshots.get(offer.key), dict) and "content" in entry
    } - set(tables)
    if not contents:
        return
    try:
        held = store.held((evidence.DISTRICTS,))
    except Exception as error:
        _err(f"predict evidence: the district tables kept: {type(error).__name__}")
        return
    kept = {key for versions in held.values() for _kind, key in versions}
    for content in sorted(contents - kept):
        _out(
            f"::warning::predict evidence: no district table is kept for the directory content"
            f" {content[:12]} a finished snapshot indexes (docs/predict.md, The evidence)."
        )


def check_kept(state: Path, now: datetime) -> int:
    """``predict evidence --check`` (no network): one line saying how many finished snapshots
    both databases hold, with their district tables; 1 and an ``::error::`` line when one has
    waited more than 2 days for that (:func:`snowlight.live.kept.predict_verdict`), which
    opens the workflow's issue. The first check starts the grace."""
    if _state_json(state) is None:
        _out("predict evidence check: no pass state")
        return 0
    known, snapshots = kept_of(state), snapshots_of(state)
    if known.watch_from is None:
        known = PredictKept(now, known.snapshots, known.tables)
        note_kept(state, known)
    verdict = predict_verdict(known, snapshots, now)
    finished = [
        (key, entry)
        for key, entry in snapshots.items()
        if _finished_snapshot(key, now) and isinstance(entry, dict)
    ]
    whole = sum(
        1
        for key, entry in finished
        if known.snapshot_held(key, entry, every=True)
        and known.table_held(str(entry.get("content", "")), every=True)
    )
    late = f"; {verdict.count} waited over 2 days" if verdict.active else ""
    _out(
        f"predict evidence check: {whole} of {len(finished)} finished snapshots in both"
        f" databases with their district tables{late}"
    )
    if not verdict.active:
        return 0
    _out(
        f"::error::predict evidence: {verdict.count} finished weather-class snapshots (or their"
        " district tables) are not in both evidence databases after 2 days (docs/predict.md,"
        " The evidence)."
    )
    return 1


def _finished_snapshot(key: str, now: datetime) -> bool:
    try:
        return snapshot_finished(date.fromisoformat(key), now) is not None
    except ValueError:
        return False


def run_evidence(args: argparse.Namespace) -> int:  # pragma: no cover - the real world
    """Run ``predict evidence``: the predict workflow's step after the passes (with
    ``--check``, the check after it)."""
    from snowlight.live import evidence  # noqa: PLC0415
    from snowlight.live.cli import make_client  # noqa: PLC0415
    from snowlight.live.d1 import CloudflareD1  # noqa: PLC0415
    from snowlight.predict.inputs import read_deployed, read_local  # noqa: PLC0415

    if args.check:
        return check_kept(args.state, datetime.now(UTC))
    env = dict(os.environ)
    try:
        snapshots = snapshots_of(args.state)
        left, labels = left_for_evidence(args.evidence_dir)
        tables = {**tables_of(args.state), **left}
        if not tables:
            directory = (
                read_local(args.site_data)
                if args.site_data is not None
                else read_deployed(args.site, args.repository, env.get("GITHUB_TOKEN"))
            )
            tables = {learn.content_key(directory): tuple(directory.district_ids)}
        with make_client() as client:
            store = evidence.make_store(env, client)
            store.seconds = EVIDENCE_SECONDS
            if isinstance(store.api, CloudflareD1):
                store.api.deadline = time.monotonic() + EVIDENCE_FOR
            now = datetime.now(UTC)
            code = keep_evidence(store, snapshots, tables, now, labels)
            if isinstance(store.api, CloudflareD1):
                store.api.deadline = None
            known = ask_kept(store, snapshots, tables, kept_of(args.state), now, EVIDENCE_ASK_FOR)
            if not note_kept(args.state, known):
                _out("predict evidence: no pass state to note what is kept in")
            return code
    except Exception as error:
        _err(f"::error::predict evidence: {type(error).__name__}")
        return 1


def run_learn(args: argparse.Namespace) -> int:  # pragma: no cover - the real world
    """Run ``predict learn``."""
    with tempfile.TemporaryDirectory() as scratch:
        return _run_learn(args, Path(scratch))


def _run_learn(args: argparse.Namespace, scratch: Path) -> int:  # pragma: no cover
    from snowlight.live.state import StateError  # noqa: PLC0415
    from snowlight.predict.live_labels import (  # noqa: PLC0415
        NO_STATE,
        NoLiveSource,
        StateSource,
        markets_of,
    )
    from snowlight.sources.stations.registry import load_registry  # noqa: PLC0415

    env = dict(os.environ)
    try:
        run = make_pass(args, env)
        # the pre-registered live scoring rules, timestamped by every run's public log
        _out(f"predict learn: live_score sha256 {live_score_sha256(run.config)}")
        directory = run.directory()
        leave_for_evidence(EVIDENCE_DIR, directory=directory)
        committed = run.model()
        model = build_model(directory, committed, run.config, run.zone_fallback)
        mode = run.mode
        host: Host
        if run.host is not None and mode.key is not None:
            host, prefix = run.host, mode.key.split("/", 1)[0]
        else:
            host, prefix = (
                DirPublisher(PIPELINE_ROOT / "out" / "internal" / "predict" / "learn"),
                "v1",
            )
            _out("predict learn: publishing is off: the files stay in out/internal/predict/learn")
        source: Any = NoLiveSource()
        folder = live_state_folder(args.live_state, args.live_store, scratch)
        if folder is not None:
            from snowlight.live.cli import morning_line  # noqa: PLC0415

            _out(f"predict learn: {morning_line(folder / 'morning')}")
            stations = load_registry(args.registry).stations.values()
            source = StateSource(
                folder=folder,
                market_of=markets_of((s.id, s.market) for s in stations),
                zone_of=dict(zip(directory.district_ids, model.time_zone, strict=True)),
                settings=run.config.labels,
                prefix=prefix,
                read_file=lambda path: host.read(f"{prefix}/{path}"),
            )
        else:
            _out(f"predict learn: {NO_STATE}: {NO_STATE_WHERE}")
        sha = artifact_module.sha256_of(Path(args.model).read_bytes())
        outlook_path = Path(args.outlook_model)

        outlook_built: dict[str, Any] = {}

        def outlook_rates() -> artifact_module.ModelArtifact:
            from snowlight.predict import outlook as outlook_module  # noqa: PLC0415

            if "rates" not in outlook_built:
                outlook_built["rates"] = outlook_module.read_rates(outlook_path)
            found: artifact_module.ModelArtifact = outlook_built["rates"]
            return found

        def outlook_build(learned: artifact_module.Learned | None) -> ServeModel:
            # The committed v3 rates' model is built once (the outlook and the v3 rates' own
            # learning both start from it); a learned one each time it is asked for.
            if learned is not None:
                return build_model(
                    directory, outlook_rates(), run.config, run.zone_fallback, learned
                )
            if "model" not in outlook_built:
                outlook_built["model"] = build_model(
                    directory, outlook_rates(), run.config, run.zone_fallback
                )
            found: ServeModel = outlook_built["model"]
            return found

        def outlook_of() -> tuple[OutlookServe, str]:
            from snowlight.predict import outlook as outlook_module  # noqa: PLC0415

            _rates, table = outlook_module.read_artifact(outlook_path)
            sha_f = artifact_module.sha256_of(outlook_path.read_bytes())
            return OutlookServe.of(outlook_build(None), table), sha_f

    except (ConfigError, ValueError, OSError, ServeError, PublishError, StateError) as error:
        _err(f"predict learn: error: {type(error).__name__}: the served model is as it was")
        return 1
    code = learn_once(
        LearnRun(
            config=run.config,
            host=host,
            prefix=prefix,
            source=source,
            model=model,
            archive_sha256=sha,
            snapshots=run.state.snapshots,
            build=lambda learned: build_model(
                directory, committed, run.config, run.zone_fallback, learned
            ),
            now=datetime.now(UTC),
            outlook_mode=run.outlook_mode,
            outlook_state=run.state.outlook,
            outlook=outlook_of,
            outlook_build=outlook_build,
        )
    )
    _leave_labels(host, prefix)
    return code


def _leave_labels(host: Host, prefix: str) -> None:  # pragma: no cover - the live host
    """The labels as published (``learn.json``), for the evidence step. It never raises."""
    try:
        labels = host.read(f"{prefix}/{learn.LEARN_PATH}")
    except Exception as error:
        _err(f"predict learn: the labels for the evidence: {type(error).__name__}")
        return
    leave_for_evidence(EVIDENCE_DIR, labels=labels)
