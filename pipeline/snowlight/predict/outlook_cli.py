"""``snowlight predict outlook ACTION``: S7-F F2's states, outlook fit and backtest (internal).

* ``states``: the weather history as states at every moment of every school night under rule
  D2 (class rows and heads-up rows, :mod:`snowlight.predict.outlook_states`), one file per
  season, the 05:00 record's weather in the form ``predict labels --reuse-weather`` reads (so
  the 05:00 labels are made by the shipped label code), and the outlook's cases joined with
  F1's forecast codes. Nothing here is committed: it all goes to ``--out``.
* ``fit``: the outlook on every season's cases and the 05:00 rates, as ``model-f.json.gz``.
* ``backtest``: the walk-forward backtest and the GF report
  (:mod:`snowlight.predict.outlook_backtest`).
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Final

import polars as pl

from snowlight.output import write_json
from snowlight.predict import train
from snowlight.predict.calendar import season_of
from snowlight.predict.config import PIPELINE_ROOT, PredictConfig
from snowlight.predict.situations import HEADS_UP_BY_CODE, Window

# The outlook's modules load inside the handlers only: nothing that serves imports them.

NDFD_DISTRICTS: Final = PIPELINE_ROOT / ".cache" / "predict" / "ndfd-districts"
DEFAULT_WORK: Final = train.INTERNAL / "predict-outlook"


def _out(line: str) -> None:
    sys.stdout.write(line + "\n")


def register(actions: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register ``predict outlook``."""
    parser = actions.add_parser("outlook", help="S7-F: the night-before outlook (internal)")
    steps = parser.add_subparsers(dest="outlook_action", metavar="STEP", required=True)
    paths = train.TrainPaths()
    states = steps.add_parser("states", help="states at every moment, 05:00 weather, cases")
    states.add_argument("--directory", type=Path, default=paths.directory)
    states.add_argument("--weights-cache", type=Path, default=paths.weights_cache)
    states.add_argument("--weather-cache", type=Path, default=paths.weather_cache)
    states.add_argument("--headsup-cache", type=Path, default=None, help="default: inputs'")
    states.add_argument("--codes", type=Path, default=NDFD_DISTRICTS)
    states.add_argument("--out", type=Path, default=DEFAULT_WORK)
    states.add_argument(
        "--labels-out", type=Path, default=None, help="default: OUT/labels-0500 (weather only)"
    )
    states.add_argument("--first", type=int, default=None, help="first season (default config)")
    states.set_defaults(handler=run_states)
    named = steps.add_parser("reasons", help="the named weather reason of each closed label")
    named.add_argument("--archive", type=Path, default=paths.archive)
    named.add_argument("--registry", type=Path, default=paths.registry)
    named.add_argument("--directory", type=Path, default=paths.directory)
    named.add_argument("--aliases", type=Path, default=paths.aliases)
    named.add_argument("--weather-cache", type=Path, default=paths.weather_cache)
    named.add_argument("--labels", type=Path, required=True, help="a labels folder")
    named.add_argument("--workers", type=int, default=4)
    named.set_defaults(handler=run_reasons)
    fitting = steps.add_parser("fit", help="fit the outlook and the 05:00 rates (model-f)")
    fitting.add_argument("--work", type=Path, default=DEFAULT_WORK)
    fitting.add_argument("--labels", type=Path, required=True, help="the 05:00 labels folder")
    fitting.add_argument("--directory", type=Path, default=paths.directory)
    fitting.add_argument("--meta", type=Path, default=paths.meta)
    fitting.add_argument("--out", type=Path, default=None, help="default: model-f.json.gz")
    fitting.set_defaults(handler=run_fit)
    check = steps.add_parser("backtest", help="walk-forward backtest and the GF report")
    check.add_argument("--work", type=Path, default=DEFAULT_WORK)
    check.add_argument("--labels", type=Path, required=True, help="the 05:00 labels folder")
    check.add_argument("--shipped", type=Path, required=True, help="the 21:00 labels folder")
    check.add_argument("--directory", type=Path, default=paths.directory)
    check.add_argument("--report", type=Path, default=None, help="default: WORK/backtest")
    check.add_argument("--draws", type=int, default=2000)
    check.add_argument(
        "--fold-labels", type=Path, default=None, help="per-fold training labels (plan T1)"
    )
    check.set_defaults(handler=run_backtest)


def unit_maps(
    schools: pl.DataFrame, places: "train.HistoryPlaces", table: pl.DataFrame
) -> tuple[list[str | None], dict[int, str], dict[int, str]]:
    """Each directory index's zone (a district school's: its district's zone, as the weather
    history has it), and the eligible and private schools' units."""
    zone_of_district = dict(zip(table["district"], table["time_zone"], strict=True))
    eligible = train.eligible_schools(schools)
    district_of = dict(
        zip(
            eligible["index"].cast(pl.Int64).to_list(),
            eligible["district_id"].to_list(),
            strict=True,
        )
    )
    private = train.private_schools(schools)
    private_of = dict(
        zip(private["index"].cast(pl.Int64).to_list(), private["id"].to_list(), strict=True)
    )
    size = schools.height and int(schools["index"].to_numpy().max()) + 1
    zones: list[str | None] = [None] * size
    for index, district in district_of.items():
        zones[index] = zone_of_district.get(district)
    for index in private_of:
        zones[index] = places.zone_of_school.get(index)
    return zones, district_of, private_of


def run_states(args: argparse.Namespace) -> int:  # pragma: no cover - the cached NWS/IEM files
    """Run ``predict outlook states``."""
    from snowlight.predict import inputs, outlook_states  # noqa: PLC0415
    from snowlight.predict.alerts_history import read_season  # noqa: PLC0415

    config = PredictConfig.load(args.config)
    weather = config.weather
    window = Window(weather.window_from, weather.window_until, weather.snapshot_hour)
    first = args.first if args.first is not None else config.labels.first_season
    seasons = list(range(first, season_of(date.today())))
    cache = args.headsup_cache or inputs.HEADS_UP_CACHE
    headsup = {
        season: path for season in seasons if (path := inputs.headsup_path(cache, season)).is_file()
    }
    missing = sorted(set(seasons) - set(headsup))
    if missing:
        _out(f"heads-up files missing for seasons {missing}: run 'predict headsup' first")
        return 1
    paths = train.TrainPaths(
        directory=args.directory, weights_cache=args.weights_cache, weather_cache=args.weather_cache
    )
    schools = pl.read_parquet(paths.directory / "schools.parquet")
    places = train.history_places(paths, schools, seasons, headsup=headsup)
    table = train.district_table(schools, places.zone_of_school)
    private = train.private_table(schools, places.zone_of_school)
    zones, district_of, private_of = unit_maps(schools, places, table)
    names = table["district"].to_list()
    private_names = private["district"].to_list()
    district_index, district_counts = outlook_states.unit_index(district_of, names, len(zones))
    private_index, private_counts = outlook_states.unit_index(private_of, private_names, len(zones))
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    record_parts: list[pl.DataFrame] = []
    private_parts: list[pl.DataFrame] = []
    stats: dict[str, object] = {}
    state_of = table.select("district", "state").filter(pl.col("state").is_not_null())
    for season in seasons:
        rows = read_season(places.files[season].read_text(encoding="utf-8"), season)
        heads = read_season(
            headsup[season].read_text(encoding="utf-8"), season, codes=HEADS_UP_BY_CODE.keys()
        )
        swept = outlook_states.sweep([*rows, *heads], places.reach, zones, window)
        found = outlook_states.unit_states(
            swept, district_index, district_counts, weather.covered_share
        )
        frame = outlook_states.states_frame(found, names)
        frame.write_parquet(out / f"states-{season}.parquet")
        record_parts.append(outlook_states.record_weather(frame))
        privately = outlook_states.unit_states(
            swept, private_index, private_counts, weather.covered_share
        )
        private_parts.append(
            outlook_states.record_weather(outlook_states.states_frame(privately, private_names))
        )
        stats[str(season)] = {
            "rows": swept.rows,
            "rows_unresolved": swept.rows_unresolved,
            "class_rows": len(rows),
            "heads_up_rows": len(heads),
            "school_days": int(swept.school.size),
            "district_days": frame.height,
        }
        codes_path = args.codes / f"codes-{season}.parquet"
        if codes_path.is_file():
            codes = pl.read_parquet(
                codes_path, columns=["district", "night", "sample", "code_filled"]
            )
            codes = codes.rename({"code_filled": "code"})
            cases = outlook_states.season_cases(codes, frame, state_of)
            cases.write_parquet(out / f"cases-{season}.parquet")
            stats[str(season)]["cases"] = int(cases["n"].sum())  # type: ignore[index]
            del codes, cases
        _out(f"{season}: {json.dumps(stats[str(season)])}")
    write_record(
        args.labels_out or out / "labels-0500", table, private, record_parts, private_parts
    )
    write_json(out / "states-stats.json", json.loads(json.dumps(stats)))
    return 0


def write_record(
    folder: Path,
    table: pl.DataFrame,
    private: pl.DataFrame,
    record: list[pl.DataFrame],
    private_record: list[pl.DataFrame],
) -> None:
    """The 05:00 record's weather history in the files ``predict labels --reuse-weather``
    reads, so the 05:00 labels come from the shipped label code."""
    folder.mkdir(parents=True, exist_ok=True)
    table.write_parquet(folder / "districts.parquet")
    private.write_parquet(folder / "private.parquet")
    pl.concat(record).sort("district", "day").write_parquet(folder / "weather.parquet")
    pl.concat(private_record).sort("district", "day").write_parquet(
        folder / "weather-private.parquet"
    )


def run_reasons(args: argparse.Namespace) -> int:  # pragma: no cover - the real archive
    """Run ``predict outlook reasons``: ``reasons.parquet`` beside the labels, the share of
    each closed or delayed label's eligible schools lit with a weather reason named."""
    paths = train.TrainPaths(
        archive=args.archive,
        registry=args.registry,
        directory=args.directory,
        aliases=args.aliases,
        weather_cache=args.weather_cache,
    )
    schools = pl.read_parquet(paths.directory / "schools.parquet")
    table = pl.read_parquet(args.labels / "districts.parquet")
    labels = pl.read_parquet(args.labels / "labels.parquet")
    zone_of = {
        d: z for d, z in zip(table["district"], table["time_zone"], strict=True) if z is not None
    }
    run = train.prepare_archive(paths, zone_of, args.workers)
    found = train.named_shares(run, labels, schools)
    found.write_parquet(args.labels / "reasons.parquet")
    _out(f"reasons: {found.height:,} closed or delayed labels, {args.labels / 'reasons.parquet'}")
    return 0


def season_cases_frame(work: Path, seasons: list[int] | None = None) -> pl.DataFrame:
    """Every season's cases with ``season``, as
    :func:`snowlight.predict.outlook.training_cases` reads them."""
    parts = []
    for path in sorted(work.glob("cases-*.parquet")):
        season = int(path.stem.split("-")[1])
        if seasons is not None and season not in seasons:
            continue
        parts.append(pl.read_parquet(path).with_columns(pl.lit(season).alias("season")))
    return pl.concat(parts)


def run_fit(args: argparse.Namespace) -> int:  # pragma: no cover - the real labels and cases
    """Run ``predict outlook fit``: the outlook on every season's cases, the 05:00 rates on
    every 05:00 label, as ``model-f.json.gz``."""
    from snowlight.predict import outlook  # noqa: PLC0415

    config = PredictConfig.load(args.config)
    target: Path = args.out or outlook.ARTIFACT_PATH
    cases = outlook.training_cases(season_cases_frame(args.work))
    seasons = sorted(set(cases["season"].to_list()))
    found = outlook.fit(cases, seasons)
    labels = pl.read_parquet(args.labels / "labels.parquet")
    table = pl.read_parquet(args.labels / "districts.parquet")
    schools = pl.read_parquet(args.directory / "schools.parquet")
    places = train.training_places(table, schools, config.serve.neighbor_miles)
    generated = json.loads(args.meta.read_text(encoding="utf-8"))["generated_on"]
    model, _tuned, _tuned_delay = train.fit_artifact(
        labels, table, places, config, date.fromisoformat(generated)
    )
    rates = json.loads(model.model_dump_json())
    size = outlook.write_artifact(target, rates, found)
    _out(
        f"model-f: {target} ({size:,} bytes), outlook seasons {seasons}, "
        f"m_region {found.m_region:g}, m_state {found.m_state:g}"
    )
    return 0


def run_backtest(args: argparse.Namespace) -> int:  # pragma: no cover - the real labels
    """Run ``predict outlook backtest``."""
    from snowlight.predict import outlook_backtest  # noqa: PLC0415

    config = PredictConfig.load(args.config)
    report = args.report or args.work / "backtest"
    return outlook_backtest.run(
        work=args.work,
        labels_dir=args.labels,
        shipped_dir=args.shipped,
        directory=args.directory,
        out=report,
        config=config,
        draws=args.draws,
        fold_labels=args.fold_labels,
    )
