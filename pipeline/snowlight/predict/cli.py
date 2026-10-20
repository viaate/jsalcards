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
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import numpy as np
import polars as pl

from snowlight.live.publish import LiveHold
from snowlight.live.publishers import DirPublisher, GitHubPublisher, PublishError
from snowlight.output import write_bytes_atomic, write_json
from snowlight.predict import artifact as artifact_module
from snowlight.predict import backtest, pool, train
from snowlight.predict.alerts_live import (
    LiveEvent,
    Memory,
    UgcIndex,
    alerts_digest,
    live_events,
    withdrawn,
)
from snowlight.predict.calendar import is_school_day, season_of
from snowlight.predict.config import CONFIG_PATH, PIPELINE_ROOT, PredictConfig
from snowlight.predict.labels import Outcome
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
    ServeError,
    ServeModel,
    build_model,
    closed_districts,
    district_classes,
    forecast_file,
    pass_days,
)
from snowlight.predict.situations import CLASS_BY_CODE, Window
from snowlight.schemas.live import DayTimeline
from snowlight.schemas.predictions import PredictionsFile
from snowlight.sources.nws.alerts import NwsAlert

LOG: Final = logging.getLogger("snowlight.predict")
DEFAULT_STATE: Final = PIPELINE_ROOT / "out" / "internal" / "predict" / "state.json"
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
    else:
        seasons = list(range(config.labels.first_season, season_of(date.today())))
        places = train.history_places(paths, schools, seasons)
        table = train.district_table(schools, places.zone_of_school)
        weather, stats = train.weather_history(places, schools, config)
        paths.out.mkdir(parents=True, exist_ok=True)
        table.write_parquet(paths.out / "districts.parquet")
        weather.write_parquet(paths.out / "weather.parquet")
        write_json(paths.out / "weather-stats.json", json.loads(json.dumps(stats, default=str)))
    _out(f"weather: {weather.height:,} district-days above none")
    zone_of = {
        d: z for d, z in zip(table["district"], table["time_zone"], strict=True) if z is not None
    }
    run = train.prepare_archive(paths, zone_of, args.workers)
    labels = train.run_labels(run, schools, table, weather, config)
    labels.write_parquet(paths.out / "labels.parquet")
    write_json(paths.out / "district-markets.json", dict(sorted(run.markets.items())))
    states = dict(zip(table["district"], table["state"], strict=True))
    (paths.out / "labels-report.md").write_text(
        train.labels_report(labels, states), encoding="utf-8"
    )
    write_audit(run, labels, schools, zone_of, config, paths.out)
    _out(f"labels: {labels.height:,} district-days; report and audit in {paths.out}")
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


def run_train(args: argparse.Namespace) -> int:  # pragma: no cover - the real labels
    """Run ``predict train``."""
    config = PredictConfig.load(args.config)
    labels, table, places = _load_training(args.work, args.directory, config)
    generated = json.loads(args.meta.read_text(encoding="utf-8"))["generated_on"]
    model, tuned, tuned_delay = train.fit_artifact(
        labels, table, places, config, date.fromisoformat(generated)
    )
    size = model.write(args.out)
    write_json(
        args.work / "train-trials.json",
        {
            "no_school": [list(item) for item in tuned.trials],
            "delay": [list(item) for item in tuned_delay.trials],
        },
    )
    _out(f"model: {args.out} ({size:,} bytes), {model.training.labeled_days:,} labeled days")
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
    return 0


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


def backtest_report(
    usable: pl.DataFrame,
    places: pool.Places,
    config: PredictConfig,
    *,
    labels: pl.DataFrame | None = None,
    markets: Mapping[str, str] | None = None,
) -> BacktestReport:
    """Run the walk-forward backtest on the usable labels (with a ``cluster`` column).

    ``labels`` (every row, unknown ones with why) and ``markets`` (district to its market)
    word the named cases; without them the usable labels are used."""
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
    cases = backtest.named_cases(known, scored, NAMED_DISTRICTS, NAMED_DAYS, places_of)
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
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    write: Path | None = None
    history: Callable[[datetime, datetime], Sequence[NwsAlert]] | None = None
    """The NWS alert products issued in a span, to rebuild a lost alert memory."""
    _built: tuple[object, ServeModel] | None = None
    _index: tuple[object, UgcIndex] | None = None

    def serve_model(self, directory: DeployedDirectory) -> ServeModel:
        """The rates for this directory (built once per directory)."""
        if self._built is None or self._built[0] != directory.stamp:
            built = build_model(directory, self.model(), self.config, self.zone_fallback)
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
        classes = district_classes(
            model, counted, run.ugc_index(directory), days, now, window, weather.covered_share
        )
        last = _last_file(run)
        made = forecast_file(model, classes, days, now, closed_on=_closed_on(run, model), last=last)
        data = made.to_json_bytes()
        checked(data)
        packed = check_budget(data, config.serve)
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
        f"predict: {len(made.districts):,} districts, {len(days)} days ({lit} school days), "
        f"{winter_count(events)} winter alerts, {len(data):,} bytes ({packed:,} gzip)"
    )
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


def _closed_on(run: Pass, model: ServeModel) -> Callable[[date], frozenset[int] | None]:
    """The districts closed for weather on a day, from the live ingest's day timeline on the
    host (``live/days/<day>.json``, S8-D). ``None`` only when the host holds no timeline for
    the day (none was published: no district had the day off). A timeline that cannot be read
    or does not validate darkens the pass: a chance is never published from fewer inputs."""

    def closed(day: date) -> frozenset[int] | None:
        key = run.mode.key
        if key is None or run.host is None:
            return None
        prefix = key.split("/", 1)[0]
        path = f"{prefix}/live/days/{day.isoformat()}.json"
        try:
            data = run.host.read(path)
        except (OSError, PublishError) as error:
            raise DarkError(Dark.DAY_FILE, f"{path}: {error}") from error
        if data is None:
            return None
        try:
            timeline = DayTimeline.from_json_bytes(data)
        except ValueError as error:
            raise DarkError(Dark.DAY_FILE, f"{path} does not validate") from error
        return closed_districts(timeline, model, run.config.weather.covered_share)

    return closed


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
        model=lambda: artifact_module.load(args.model),
        state=load_state(args.state),
        write=args.write,
        history=history.read,
    )


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
