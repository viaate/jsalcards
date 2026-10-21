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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import numpy as np
import numpy.typing as npt
import polars as pl

from snowlight.live.publish import LiveHold
from snowlight.live.publishers import DirPublisher, GitHubPublisher, PublishError
from snowlight.output import write_bytes_atomic, write_json
from snowlight.predict import artifact as artifact_module
from snowlight.predict import backtest, learn, pool, train
from snowlight.predict.alerts_live import (
    LiveEvent,
    Memory,
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
)
from snowlight.predict.labels import Outcome
from snowlight.predict.live_labels import record_snapshots
from snowlight.predict.opens import NOTHING_SAID, OpensError, SaidOpen, said_open
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
    forecast_file,
    pass_days,
    unit_classes,
)
from snowlight.predict.situations import CLASS_BY_CODE, Window
from snowlight.schemas.live import ClosingsFile, DayTimeline, OpensFile
from snowlight.schemas.predictions import PredictionsFile
from snowlight.sources.nws.alerts import NwsAlert

LOG: Final = logging.getLogger("snowlight.predict")
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
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--weather-cache", type=Path, default=PIPELINE_ROOT / ".cache" / "weather")
    parser.add_argument("--host", choices=("github", "dir"), default="github")
    parser.add_argument("--host-dir", type=Path, default=None, help="the folder of --host dir")
    parser.add_argument("--write", type=Path, default=None, help="also write each file here")


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


def run_backtest(args: argparse.Namespace) -> int:  # pragma: no cover - the real labels
    """Run ``predict backtest``."""
    config = PredictConfig.load(args.config)
    labels, _table, places = _load_training(args.work, args.directory, config)
    usable = pool.usable_labels(labels, places)
    markets_path = args.work / "district-markets.json"
    markets = json.loads(markets_path.read_text(encoding="utf-8")) if markets_path.is_file() else {}
    report = backtest_report(usable, places, config, labels=labels, markets=markets)
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
        found = backtest_report(
            usable_private,
            private_places,
            config.model_copy(update={"model": config.model.private()}),
            labels=private_labels,
            markets=markets,
            names=NAMED_PRIVATE,
            days=PEMBROKE_DAYS,
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
                    oracle_table(private_labels, weather, private_places, config.model.private())
                )
                + "\n"
            )
        _out("private: " + found.markdown.splitlines()[2])
    return 0


def oracle_table(
    labels: pl.DataFrame,
    weather: pl.DataFrame,
    places: pool.Places,
    settings: ModelSettings,
) -> list[str]:  # pragma: no cover - the real labels
    """Each named private school on each named day, predicted walk-forward (fit on the
    seasons before its own only) from its weather class that day, labeled or not."""
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
    for unit in NAMED_PRIVATE:
        for day in PEMBROKE_DAYS:
            weather_class = classes.get((unit, day), 0)
            after = (unit, previous_school_day(day)) in closed
            key = pool.situation_of(weather_class, after).key
            cells.append((unit, pool.SITUATION_INDEX[key], season_of(day)))
            shown.append((unit, day, weather_class, after))
    chances = backtest.chances_on(rows, delay_rows, places, cells, settings)
    lines = [
        "",
        "## Named private schools, every named day, predicted",
        "",
        "Walk-forward: each day's chance from its weather class that day (alerts issued by "
        "21:00 the evening before), fit on the seasons before its own only, labeled or not.",
        "",
        "| school | day | weather class | day after | chance | label |",
        "|---|---|---|---|---|---|",
    ]
    for (unit, day, weather_class, after), chance in zip(shown, chances, strict=True):
        row = outcome.get((unit, day))
        label = "no morning read" if row is None else str(row["outcome"])
        lines.append(
            f"| {NAMED_PRIVATE[unit]} ({unit}) | {day} | {_class_label(str(weather_class))} | "
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
) -> BacktestReport:
    """Run the walk-forward backtest on the usable labels (with a ``cluster`` column).

    ``labels`` (every row, unknown ones with why) and ``markets`` (district to its market)
    word the named cases (``names`` on ``days``); without them the usable labels are used."""
    rows = pool.rows_from_labels(usable, places, "no_school")
    delay_rows = pool.rows_from_labels(usable, places, "delay")
    folds = backtest.walk_forward(
        rows, delay_rows, places, config.backtest.test_seasons, config.model
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
    report_metrics = {**metrics, "reliability_by_region": by_region}
    markdown = backtest.report_markdown(report_metrics, bins, judged, cases)
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
    _built: tuple[object, ServeModel] | None = None
    _index: tuple[object, UgcIndex] | None = None

    def serve_model(self, directory: DeployedDirectory) -> ServeModel:
        """The rates for this directory (built once per directory)."""
        if self._built is None or self._built[0] != directory.stamp:
            built, why = learn.serving_model(
                directory, self.model(), self.learned, self.config, self.zone_fallback
            )
            if why is not None:
                _warn(why)
            self._built = (directory.stamp, built)
        return self._built[1]

    def ugc_index(self, directory: DeployedDirectory) -> UgcIndex:
        """The schools of each UGC (built once per directory)."""
        if self._index is None or self._index[0] != directory.stamp:
            self._index = (directory.stamp, self.ugcs(directory))
        return self._index[1]


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
    gap = timedelta(minutes=config.serve.memory_gap_minutes)
    if state.observed_at is None or now - state.observed_at > gap:
        state.memory_since = None
    if state.memory_since is None or state.memory_since > reach:
        if run.history is None:
            raise DarkError(Dark.MEMORY, "the alert memory has a gap and no history to fill it")
        lead = timedelta(hours=config.serve.history_lead_hours)
        memory.rebuild(run.history(reach - lead, now), now)
        state.memory_since = reach
    counted = memory.update(events, now, withdrawn(feed.alerts))
    state.memory = memory.as_json()
    state.observed_at = now
    return counted


def one_pass(run: Pass, *, grid: bool = True) -> int:
    """One serving pass: 0 published or unchanged, 3 dark. ``grid``: a pass on the grid (the
    heartbeat uploads an unchanged file only then, see :func:`~snowlight.predict.publish.due`).

    The alerts it was made from count as handled (``state.alerts_digest``) only when it
    published or found nothing to change: a dark pass leaves them, so the loop tries again.
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
        counted = remember(run, feed, events, now, memory_reach(days, model.time_zone, window))
        classes, private_classes = unit_classes(
            model, counted, run.ugc_index(directory), days, now, window, weather.covered_share
        )
        run.state.snapshots = record_snapshots(
            run.state.snapshots,
            content=learn.content_key(directory),
            zones=model.time_zone,
            classes=classes,
            days=days,
            now=now,
            window=window,
        )
        made, data, packed = _pass_file(run, model, days, now, classes, private_classes)
        checked(data)
    except DarkError as error:
        _err(f"predict: dark ({error})")
        return EXIT_DARK
    except ServeError as error:
        _err(f"predict: dark ({type(error).__name__}: {error})")
        return EXIT_DARK
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
    key = run.mode.key
    handled = alerts_digest(events)
    if key is None or run.host is None:
        _out("predict: publishing is off")
        run.state.alerts_digest = handled
        return 0
    if not due(run.state, digest, now, config.serve, grid=grid):
        _out("predict: unchanged, heartbeat not due")
        run.state.alerts_digest = handled
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
    return 0


def _pass_file(  # noqa: PLR0913, PLR0917 - the pass, its model, days and classes
    run: Pass,
    model: ServeModel,
    days: tuple[date, date],
    now: datetime,
    classes: npt.NDArray[np.int64],
    private_classes: npt.NDArray[np.int64] | None,
) -> tuple[PredictionsFile, bytes, int]:
    """The pass's file within the size budget (:func:`fitted`), its bytes and gzip size; the
    host's files it reads (the last file, the day timelines, the opens) are read once."""
    last = _last_file(run)
    timelines: dict[date, DayTimeline | None] = {}
    closed_on = _closed_on(run, model, timelines)
    closed_schools = _closed_on(run, model, timelines, private=True)
    said = _said_open(run, model, now)
    return fitted(
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
        ),
        run.config.serve,
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
    host = make_host(args, env) if mode is not Mode.OFF else None
    model_bytes = Path(args.model).read_bytes()
    committed = artifact_module.ModelArtifact.from_bytes(model_bytes)
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

    def directory() -> DeployedDirectory:
        if args.site_data is not None:
            return read_local(args.site_data)
        return read_deployed(args.site, args.repository, env.get("GITHUB_TOKEN"))

    def ugcs(found: DeployedDirectory) -> UgcIndex:
        points = found.points
        return UgcIndex.build(
            points.lon_e6.astype(np.float64) * 1e-6, points.lat_e6.astype(np.float64) * 1e-6, areas
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
    )


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
    return learn.EXIT_KEPT if decision.kind == "keep" else 0


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
        directory = run.directory()
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
    except (ConfigError, ValueError, OSError, ServeError, PublishError, StateError) as error:
        _err(f"predict learn: error: {type(error).__name__}: the served model is as it was")
        return 1
    return learn_once(
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
        )
    )
