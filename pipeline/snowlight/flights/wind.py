"""Windy days (docs/flights.md, "Windy days"): do the chances as published match what happened on
blocks with strong wind, or are they low?

The held-out test year only, scored with the published model (``model.json.gz``) on the rows the
live pass would have read (the evening-before 00Z run, lead class 1), and the values the files
would have shown: the model's chance where the airport's own gate passed (and the after-storm
gate on a day after a storm), else the usual rate (:meth:`snowlight.flights.model.Model.shows`).

Each block falls in a wind band twice: by the run's own strongest forecast gust in the block
(the forecast path: what the page knew) and by the strongest gust or sustained wind the hourly
reports saw in it (the observed path: what came), so a forecast that missed the wind is told
apart from a model that read the wind and still said too little. The split (:func:`splits`)
says which: the blocks where the reports saw 35 kt or more, by the band the forecast had put them
in, and the blocks forecast at 35 kt or more that the reports saw under 30 kt.

Per band, outcome and group of airports: blocks, days, the expected events against what happened
(their ratio, with a 90% interval from whole days drawn again, since cancels cluster by day: the
lead's rule LR-F5), and the log loss and Brier score per flight of the published values and of
the usual rate. The verdict (:func:`verdict`) says "too low" only when the ratio's whole interval
lies above :data:`TOO_LOW` on the 35 kt band for departures cancelled or late, with at least
:data:`MIN_DAYS` days, at the airports that passed, on the forecast path; an outcome with fewer
days there is "too few days to tell", never "not shown too low". A line with fewer than
:data:`INTERVAL_DAYS` days has no interval: drawing one or two days again cannot give one.
"""

import json
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Final

import numpy as np
import polars as pl

from snowlight.flights import model as fm
from snowlight.flights.airports import Airport
from snowlight.flights.artifact import Artifact
from snowlight.flights.blocks import DAY_START_HOUR, STARTS, Block
from snowlight.flights.spans import weather_days


@dataclass(frozen=True, slots=True)
class Band:
    """Blocks whose strongest gust is at least ``low`` knots and under ``high`` (no top when
    ``None``)."""

    name: str
    low: float
    high: float | None

    def holds(self, gust: pl.Expr) -> pl.Expr:
        """Whether ``gust`` (knots) is in the band; a missing gust is in none."""
        inside = gust >= self.low
        return inside if self.high is None else inside & (gust < self.high)


BANDS: Final = (
    Band("under 30 kt", 0.0, 30.0),
    Band("30-34 kt", 30.0, 35.0),
    Band("35 kt or more", 35.0, None),
    Band("45 kt or more", 45.0, None),
)
"""The wind bands; the last is part of the one before it."""
STRONG: Final = "35 kt or more"
TARGETS: Final = ("dep_canc", "dep_late", "arr_canc", "arr_late")
CHECKED: Final = ("dep_canc", "dep_late")
"""The outcomes the verdict reads."""
NAMED: Final = ("EWR", "JFK", "LGA", "PHL", "BOS", "DCA")
PASSED: Final = "airports that passed"
SIX: Final = "EWR JFK LGA PHL BOS DCA"
PATHS: Final = ("forecast", "observed")
DRAWS: Final = 1000
SEED: Final = 20261127
LEVEL: Final = 0.90
TOO_LOW: Final = 1.15
MIN_DAYS: Final = 30
INTERVAL_DAYS: Final = 5
"""Fewer days than this: no interval (printed ``-``)."""
SPLIT: Final = "split"
SEEN_STRONG: Final = Band("seen 35 kt or more", 35.0, None)
SPLITS: Final = (
    (SEEN_STRONG, Band("forecast under 30 kt", 0.0, 30.0)),
    (SEEN_STRONG, Band("forecast 30-34 kt", 30.0, 35.0)),
    (SEEN_STRONG, Band("forecast 35 kt or more", 35.0, None)),
    (Band("forecast 35 kt or more", 35.0, None), Band("seen under 30 kt", 0.0, 30.0)),
)
"""The split's lines: (the first band, the second), each on its own path: the observed path
first for the blocks the reports saw at 35 kt or more, else the forecast path first."""
EPSILON: Final = 1e-6


def ratio_interval(
    days: np.ndarray,
    events: np.ndarray,
    expected: np.ndarray,
    *,
    draws: int = DRAWS,
    seed: int = SEED,
) -> tuple[float, float]:
    """The 90% interval of happened over expected, from whole days drawn again ``draws`` times
    with a fixed seed (every block of a day goes together); ``nan`` without expected events."""
    if len(days) == 0 or float(expected.sum()) <= 0:
        return float("nan"), float("nan")
    _, index = np.unique(days, return_inverse=True)
    happened = np.bincount(index, weights=events)
    said = np.bincount(index, weights=expected)
    rng = np.random.default_rng(seed)
    picks = rng.integers(0, len(happened), size=(draws, len(happened)))
    top = happened[picks].sum(axis=1)
    bottom = said[picks].sum(axis=1)
    ratios = np.divide(top, bottom, out=np.full(draws, np.nan), where=bottom > 0)
    tail = (1 - LEVEL) / 2
    low, high = np.nanquantile(ratios, [tail, 1 - tail])
    return float(low), float(high)


def _per_flight(p: np.ndarray, events: np.ndarray, trials: np.ndarray) -> tuple[float, float]:
    """Log loss and Brier score per flight."""
    total = float(trials.sum())
    if total <= 0:
        return float("nan"), float("nan")
    q = np.clip(p, EPSILON, 1 - EPSILON)
    misses = trials - events
    loss = -(events * np.log(q) + misses * np.log(1 - q)).sum() / total
    brier = (events * (1 - p) ** 2 + misses * p**2).sum() / total
    return float(loss), float(brier)


@dataclass(frozen=True, slots=True)
class Line:
    """One band, outcome, group and path."""

    path: str
    group: str
    target: str
    band: str
    blocks: int
    days: int
    said: float
    """Expected events over flights: the mean chance said, per flight."""
    happened: float
    """Events over flights."""
    ratio: float
    low: float
    high: float
    log_loss: float
    log_loss_usual: float
    brier: float
    brier_usual: float


def line(rows: pl.DataFrame, path: str, group: str, target: str, band: str) -> Line:
    """The measures of ``rows`` (``day``, ``p``, ``base``, ``events``, ``trials``)."""
    p = rows.get_column("p").to_numpy().astype(np.float64)
    base = rows.get_column("base").to_numpy().astype(np.float64)
    events = rows.get_column("events").to_numpy().astype(np.float64)
    trials = rows.get_column("trials").to_numpy().astype(np.float64)
    expected = p * trials
    flights = float(trials.sum())
    low, high = ratio_interval(rows.get_column("day").to_numpy(), events, expected)
    loss, brier = _per_flight(p, events, trials)
    loss_usual, brier_usual = _per_flight(base, events, trials)
    said = float(expected.sum())
    days = rows.get_column("day").n_unique()
    if days < INTERVAL_DAYS:
        low, high = float("nan"), float("nan")
    return Line(
        path=path,
        group=group,
        target=target,
        band=band,
        blocks=rows.height,
        days=days,
        said=said / flights if flights > 0 else float("nan"),
        happened=float(events.sum()) / flights if flights > 0 else float("nan"),
        ratio=float(events.sum()) / said if said > 0 else float("nan"),
        low=low,
        high=high,
        log_loss=loss,
        log_loss_usual=loss_usual,
        brier=brier,
        brier_usual=brier_usual,
    )


def _groups() -> tuple[tuple[str, pl.Expr], ...]:
    return ((PASSED, pl.col("passed")), (SIX, pl.col("apt").is_in(NAMED)))


def lines(scored: pl.DataFrame) -> list[Line]:
    """Every path, group, outcome and band of the scored rows (``apt``, ``day``, ``target``,
    ``p``, ``base``, ``events``, ``trials``, ``passed``, ``gust_fc``, ``gust_obs``)."""
    out: list[Line] = []
    for path in PATHS:
        gust = pl.col("gust_fc" if path == "forecast" else "gust_obs")
        for group, chosen in _groups():
            for target in TARGETS:
                part = scored.filter((pl.col("target") == target) & chosen)
                for band in BANDS:
                    rows = part.filter(band.holds(gust).fill_null(value=False))
                    out.append(line(rows, path, group, target, band.name))
    return out


def splits(scored: pl.DataFrame) -> list[Line]:
    """The split of :data:`SPLITS` (path :data:`SPLIT`, band ``"<first>, <second>"``) for every
    group and outcome: whether the observed path's excess comes from the forecast missing the
    wind or from the model saying too little on a gust it was given."""
    out: list[Line] = []
    for group, chosen in _groups():
        for target in TARGETS:
            part = scored.filter((pl.col("target") == target) & chosen)
            for first, second in SPLITS:
                seen_first = first.name.startswith("seen")
                gusts = (pl.col("gust_obs"), pl.col("gust_fc"))
                one, two = gusts if seen_first else gusts[::-1]
                rows = part.filter((first.holds(one) & second.holds(two)).fill_null(value=False))
                out.append(line(rows, SPLIT, group, target, f"{first.name}, {second.name}"))
    return out


def _interval(item: Line) -> str:
    """``low-high``, or ``-`` without one."""
    if not (np.isfinite(item.low) and np.isfinite(item.high)):
        return "-"
    return f"{item.low:.2f}-{item.high:.2f}"


def _days(count: int) -> str:
    return f"{count} day" if count == 1 else f"{count} days"


def verdict(found: Sequence[Line]) -> tuple[bool, str]:
    """Whether history says the chances are too low on windy days (decision 4), and why: "too
    low", "not shown too low", or for an outcome with fewer than :data:`MIN_DAYS` days (or none)
    on the checked line, "too few days to tell"."""
    checked = {
        item.target: item
        for item in found
        if item.path == "forecast"
        and item.group == PASSED
        and item.band == STRONG
        and item.target in CHECKED
    }
    enough = [
        checked[target]
        for target in CHECKED
        if target in checked
        and checked[target].days >= MIN_DAYS
        and np.isfinite(checked[target].low)
    ]
    low = [item for item in enough if item.low > TOO_LOW]
    if low:
        names = ", ".join(f"{item.target} {item.ratio:.2f} ({_interval(item)})" for item in low)
        return True, f"too low: {names}"
    parts = []
    if enough:
        parts.append(
            "not shown too low: "
            + "; ".join(
                f"{item.target} {_num(item.ratio)} ({_interval(item)}) on {_days(item.days)}"
                for item in enough
            )
        )
    thin = [target for target in CHECKED if checked.get(target) not in enough]
    if thin:
        parts.append(
            "too few days to tell: "
            + "; ".join(
                f"{target} {_num(checked[target].ratio)} ({_interval(checked[target])}) "
                f"on {_days(checked[target].days)}"
                if target in checked
                else f"{target} on 0 days"
                for target in thin
            )
        )
    return False, "; ".join(parts)


def _pct(value: float) -> str:
    return "-" if not np.isfinite(value) else f"{100 * value:.2f}%"


def _num(value: float, places: int = 2) -> str:
    return "-" if not np.isfinite(value) else f"{value:.{places}f}"


TITLES: Final = {
    "forecast": "Forecast gust",
    "observed": "Observed gust",
    SPLIT: "Seen against forecast",
}


def markdown(found: Sequence[Line]) -> str:
    """The tables, one per path (and the split) and group (a line with no blocks left out)."""
    out: list[str] = []
    for path in (*PATHS, SPLIT):
        for group in (PASSED, SIX):
            if not any(item.path == path and item.group == group for item in found):
                continue
            out += [
                f"**{TITLES[path]}, {group}**",
                "",
                "| outcome | band | blocks | days | said | happened | ratio (90%) "
                "| log loss shown / usual | Brier shown / usual |",
                "| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |",
            ]
            for item in found:
                if item.path != path or item.group != group or item.blocks == 0:
                    continue
                out.append(
                    f"| {item.target} | {item.band} | {item.blocks:,} | {item.days} "
                    f"| {_pct(item.said)} | {_pct(item.happened)} | {_num(item.ratio)} "
                    f"({_interval(item)}) "
                    f"| {_num(item.log_loss, 4)} / {_num(item.log_loss_usual, 4)} "
                    f"| {_num(item.brier, 5)} / {_num(item.brier_usual, 5)} |"
                )
            out.append("")
    return "\n".join(out)


def left_out(model: fm.Model, codes: Sequence[str]) -> dict[str, list[str]]:
    """Per outcome, the airports of ``codes`` (those this backtest has no hourly reports for)
    whose gate passed at lead 1: left out of "airports that passed" by a gap in the data."""
    return {
        target: sorted(code for code in codes if model.is_published(code, target, 1))
        for target in TARGETS
    }


def left_out_note(missing: Sequence[str], passed: dict[str, list[str]]) -> str:
    """The sentence under the verdict naming what the backtest's data could not score."""
    named = "; ".join(f"{target} {' '.join(codes)}" for target, codes in passed.items() if codes)
    return (
        f"No hourly reports in this backtest's data for {len(missing)} airports, left out; "
        f"of them, passed at lead 1: {named or 'none'}."
    )


# --- the rows ----------------------------------------------------------------------------------


def base_frame(artifact: Artifact, table: str, codes: Sequence[str]) -> pl.DataFrame:
    """The usual rates the live pass reads (:meth:`Artifact.usual`) for ``codes``: ``apt``,
    ``block``, ``moy``, ``canc_base``, ``late_base``."""
    rows = [
        {
            "apt": code,
            "block": int(block),
            "moy": month,
            "canc_base": artifact.usual(table, "canc", code, int(block), month),
            "late_base": artifact.usual(table, "late", code, int(block), month),
        }
        for code in codes
        for block in Block
        for month in range(1, 13)
    ]
    return pl.DataFrame(
        rows,
        schema={
            "apt": pl.String,
            "block": pl.Int8,
            "moy": pl.Int8,
            "canc_base": pl.Float64,
            "late_base": pl.Float64,
        },
    )


def scored_rows(
    blocks: dict[str, pl.DataFrame],
    model: fm.Model,
    rows_of: Callable[[pl.DataFrame, str], tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]],
    stormy: Callable[[pl.DataFrame], np.ndarray],
) -> pl.DataFrame:
    """Per outcome, every lead-1 block of ``blocks`` (``dep``, ``arr``: features joined to what
    happened and the usual rates, with ``gust_obs``) with the value the files would have shown:
    ``apt``, ``day``, ``block``, ``target``, ``p``, ``base``, ``events``, ``trials``, ``passed``
    (the airport's gate), ``gust_fc``, ``gust_obs``."""
    parts = []
    for target in TARGETS:
        frame = blocks[target.split("_")[0]].filter(pl.col("lead_class") == 1)
        if frame.is_empty() or (target, 1) not in model.fitted:
            continue
        x, events, trials, base = rows_of(frame, target)
        p = model.chance(target, 1, x)
        codes = frame.get_column("apt").to_list()
        storm = stormy(frame)
        shown = np.asarray(
            [model.shows(c, target, 1, stormy=bool(s)) for c, s in zip(codes, storm, strict=True)],
            dtype=bool,
        )
        passed = np.asarray([model.is_published(c, target, 1) for c in codes], dtype=bool)
        parts.append(
            frame.select(
                "apt",
                "day",
                "block",
                pl.col("gust").cast(pl.Float64).fill_null(0.0).alias("gust_fc"),
                pl.col("gust_obs").cast(pl.Float64),
            ).with_columns(
                pl.lit(target).alias("target"),
                pl.Series("p", np.where(shown, p, base)),
                pl.Series("base", base),
                pl.Series("events", events),
                pl.Series("trials", trials),
                pl.Series("passed", passed),
            )
        )
    if not parts:
        return pl.DataFrame()
    return pl.concat(parts)


def observed_peaks(hourly: pl.LazyFrame, stations: pl.DataFrame) -> pl.DataFrame:
    """The strongest gust or sustained wind (knots) the hourly reports saw in each local block:
    ``apt``, ``day``, ``block``, ``gust_obs``. ``hourly``: ``station``, ``hour`` (UTC),
    ``gust``, ``wind``; ``stations``: ``station``, ``apt``, ``tz``."""
    parts = []
    for tz, group in stations.group_by("tz"):
        local = pl.col("hour").dt.convert_time_zone(str(tz[0]))
        hour = local.dt.hour()
        block = (
            pl.when(hour >= STARTS[Block.NIGHT])
            .then(int(Block.NIGHT))
            .when(hour >= STARTS[Block.EVENING])
            .then(int(Block.EVENING))
            .when(hour >= STARTS[Block.AFTERNOON])
            .then(int(Block.AFTERNOON))
            .when(hour >= STARTS[Block.MORNING])
            .then(int(Block.MORNING))
            .when(hour >= STARTS[Block.EARLY])
            .then(int(Block.EARLY))
            .otherwise(int(Block.NIGHT))
        )
        day = (
            pl.when(hour < DAY_START_HOUR)
            .then(local.dt.date() - pl.duration(days=1))
            .otherwise(local.dt.date())
        )
        parts.append(
            hourly.join(group.lazy().select("station", "apt"), on="station")
            .with_columns(
                day.alias("day"),
                block.cast(pl.Int8).alias("block"),
                pl.max_horizontal(
                    pl.col("gust").cast(pl.Float64), pl.col("wind").cast(pl.Float64)
                ).alias("peak"),
            )
            .group_by("apt", "day", "block")
            .agg(pl.col("peak").max().alias("gust_obs"))
        )
    if not parts:
        return pl.DataFrame(
            schema={"apt": pl.String, "day": pl.Date, "block": pl.Int8, "gust_obs": pl.Float64}
        )
    return pl.concat(parts).collect()


def in_year(first: date, last: date) -> pl.Expr:
    """Rows from ``first`` to ``last`` (both included)."""
    return (pl.col("day") >= first) & (pl.col("day") <= last)


def reported(raw: Path) -> set[str]:  # pragma: no cover - a year of reports on disk
    """The stations this backtest has hourly reports for (``raw/obs``)."""
    flags = pl.scan_parquet(raw / "obs" / "*.parquet")
    return set(flags.select("station").unique().collect().get_column("station").to_list())


def test_blocks(
    raw: Path,
    artifact: Artifact,
    airports: Sequence[Airport],
    peaks: pl.DataFrame | None,
    seen: set[str],
) -> dict[str, pl.DataFrame]:  # pragma: no cover - a year of bulletins and flights on disk
    """The test year's lead-1 blocks at the airports whose station is in ``seen`` (those this
    backtest has hourly reports for), as the live pass would have read them: the run's
    features (``raw/nbs``), the weather observed before the run (``raw/obs``), what happened
    (``raw/bts``) and the published usual rates, with the observed peaks (``gust_obs``; none
    without ``peaks``)."""
    from snowlight.flights import build, train  # noqa: PLC0415 - the history readers

    rows = build.nbs_rows(raw)
    flags = pl.scan_parquet(raw / "obs" / "*.parquet")
    # An airport this backtest's data has no hourly reports for is a gap in the data, not in the
    # live pass (which reads METARs for it): left out here and named by run().
    features = train.forecast_features(rows, airports, flags).filter(
        in_year(artifact.test_first, artifact.test_last)
        & (pl.col("lead_class") == 1)
        & pl.col("apt").is_in([a.code for a in airports if a.wx in seen])
    )
    codes = sorted(features.get_column("apt").unique().to_list())
    out: dict[str, pl.DataFrame] = {}
    for table in ("dep", "arr"):
        frame = (
            features.lazy()
            .join(train.outcomes(raw / "bts", table), on=["apt", "day", "block"])
            .with_columns(pl.col("day").dt.month().cast(pl.Int8).alias("moy"))
            .join(base_frame(artifact, table, codes).lazy(), on=["apt", "block", "moy"])
            .filter(weather_days())
            .collect()
        )
        if peaks is None:
            frame = frame.with_columns(pl.lit(None, pl.Float64).alias("gust_obs"))
        else:
            frame = frame.join(peaks, on=["apt", "day", "block"], how="left")
        out[table] = frame
    return out


def run(
    raw: Path, model_path: Path, out: Path, gusts: Path | None
) -> int:  # pragma: no cover - a year of bulletins and flights on disk
    """``snowlight flights wind``: write ``wind.md`` and ``wind.json`` under ``out``."""
    from snowlight.flights import artifact as artifact_module  # noqa: PLC0415
    from snowlight.flights import train  # noqa: PLC0415
    from snowlight.flights.airports import load  # noqa: PLC0415

    airports = load()
    artifact = artifact_module.read(model_path)
    stations = pl.DataFrame(
        {
            "station": [a.wx for a in airports],
            "apt": [a.code for a in airports],
            "tz": [a.tz for a in airports],
        }
    )
    peaks = (
        observed_peaks(pl.scan_parquet(gusts / "*.parquet"), stations)
        if gusts is not None
        else None
    )
    seen = reported(raw)
    blocks = test_blocks(raw, artifact, airports, peaks, seen)
    scored = scored_rows(blocks, artifact.model, train._rows, train.stormy)
    found = lines(scored)
    split = splits(scored)
    too_low, why = verdict(found)
    missing = sorted(a.code for a in airports if a.wx not in seen)
    passed = left_out(artifact.model, missing)
    out.mkdir(parents=True, exist_ok=True)
    head = (
        f"Test year {artifact.test_first} to {artifact.test_last}, lead 1, as published. "
        f"Verdict: {why}.\n\n{left_out_note(missing, passed)}\n\n"
    )
    (out / "wind.md").write_text(head + markdown([*found, *split]))
    (out / "wind.json").write_text(
        json.dumps(
            {
                "too_low": too_low,
                "verdict": why,
                "lines": [asdict(item) for item in found],
                "split": [asdict(item) for item in split],
                "left_out": missing,
                "left_out_passed": passed,
            },
            indent=1,
        )
    )
    print(f"flights wind: {len(scored)} rows, {why}")  # noqa: T201 - the command's one line
    return 0
