"""Forecast weather by airport block, from NBS rows (:mod:`snowlight.flights.nbs`).

Each 3-hourly column of a run describes the 3 hours ending at its time, and its middle (1.5 hours
before) places it in a local block (:mod:`snowlight.flights.blocks`). The 6-hour amounts and
chances are given every other column; each column takes the 6-hour value that covers it, and an
amount is split evenly between the two columns it covers.

Per block (:data:`BLOCK_COLUMNS`): snow and ice (inches), the highest chance of snow, freezing
rain and thunder, the strongest wind and gust (knots), the lowest visibility (miles), ceiling
(hundreds of feet; 999 for none) and temperature (F), the snow and ice of the two blocks
before, and the run's snow and ice from its first hour to the start of the block's day
(``pre_snow``, ``pre_ice``: a storm the run sees on the days between it and the block, so the
day after a storm knows the storm). A block counts only when the run covers all of it: its start
at least 3 hours after the run and its end at most 72 hours after.

The lead class of a block is how many days before the block's day the run was issued, by the
airport's own calendar (:func:`lead_class`): the 00Z run is issued in the afternoon or evening
before across the US, so class 1 is the run of the evening before, 2 the evening before that,
3 three evenings before. A run issued on the block's own day (class 0) is never used: the
history has no such rows, so no chance from one was ever tested.
"""

from collections.abc import Sequence
from datetime import date, datetime
from typing import Final

import polars as pl

from snowlight.flights.blocks import DAY_START_HOUR, STARTS, Block

NO_CEILING_HUNDREDS: Final = 999
FIRST_HOURS: Final = 3
LAST_HOURS: Final = 72
LEADS: Final = (1, 2, 3)

BLOCK_COLUMNS: Final = (
    "snow",
    "ice",
    "p_snow",
    "p_zr",
    "thunder",
    "wind",
    "gust",
    "vis",
    "cig",
    "tmp",
    "snow_before",
    "ice_before",
    "pre_snow",
    "pre_ice",
)

_BLOCK_HOURS: Final = {
    Block.EARLY: 4,
    Block.MORNING: 3,
    Block.AFTERNOON: 5,
    Block.EVENING: 4,
    Block.NIGHT: 8,
}


def lead_class(block_day: date, run_day: date) -> int:
    """The lead class of a block on ``block_day`` from a run issued on ``run_day`` (the
    airport's own date at the run's time): the days between them."""
    return (block_day - run_day).days


def _columns(rows: pl.LazyFrame) -> pl.LazyFrame:
    """Each 3-hour column's values, with the covering 6-hour values."""
    by = ("station", "run")
    filled = rows.sort("station", "run", "valid").with_columns(
        *[
            pl.col(name).cast(pl.Float64).fill_null(strategy="backward").over(by).alias(name)
            for name in ("P06", "S06", "I06")
        ]
    )
    pop = (pl.col("P06") / 100).fill_null(0.0)
    return filled.select(
        "station",
        "run",
        (pl.col("valid") - pl.duration(minutes=90)).alias("mid"),
        (pl.col("S06").fill_null(0.0).clip(lower_bound=0) / 20).alias("snow"),
        (pl.col("I06").fill_null(0.0).clip(lower_bound=0) / 200).alias("ice"),
        (pl.col("PSN").cast(pl.Float64).fill_null(0.0) / 100 * pop).alias("p_snow"),
        (pl.col("PZR").cast(pl.Float64).fill_null(0.0) / 100 * pop).alias("p_zr"),
        (pl.col("T03").cast(pl.Float64).fill_null(0.0) / 100).alias("thunder"),
        pl.col("WSP").cast(pl.Float64).alias("wind"),
        pl.col("GST").cast(pl.Float64).alias("gust"),
        (pl.col("VIS").cast(pl.Float64) / 10).alias("vis"),
        pl.when(pl.col("CIG") < 0)
        .then(NO_CEILING_HUNDREDS)
        .otherwise(pl.col("CIG"))
        .cast(pl.Float64)
        .alias("cig"),
        pl.col("TMP").cast(pl.Float64).alias("tmp"),
    )


def _block_of(local_hour: pl.Expr) -> pl.Expr:
    from snowlight.flights.bts import _block_expr  # noqa: PLC0415 - one block rule

    return _block_expr(local_hour)


def block_features(rows: pl.LazyFrame, zones: pl.DataFrame) -> pl.LazyFrame:
    """Forecast features per airport, run, block day and block: only blocks the run covers
    whole and of lead class 1 to 3 (:func:`lead_class`), the same rule for the history and the
    live job, so the live job never reads a row of a kind the held-out test did not see.

    ``rows``: NBS rows (``station``, ``run``, ``valid`` and the elements); ``zones``: ``station``
    (the bulletin's id), ``apt`` and ``tz`` per airport. Out: ``apt``, ``run``, ``day``,
    ``block``, ``lead`` (hours from the run to the block's start), ``lead_class``, ``end``,
    :data:`BLOCK_COLUMNS`.
    """
    columns = _columns(rows)
    parts = []
    for (tz,), group in zones.group_by("tz"):
        zone = str(tz)
        local = (
            columns.join(group.lazy().select("station", "apt"), on="station")
            .with_columns(pl.col("mid").dt.convert_time_zone(zone).alias("local"))
            .with_columns(
                pl.col("local").dt.hour().alias("lh"),
                pl.col("local").dt.date().alias("cd"),
            )
            .with_columns(
                _block_of(pl.col("lh")).alias("block"),
                (
                    pl.col("cd") - pl.duration(days=(pl.col("lh") < DAY_START_HOUR).cast(pl.Int32))
                ).alias("day"),
            )
            .with_columns(
                _block_start(zone).alias("start"),
                pl.col("run").dt.convert_time_zone(zone).dt.date().alias("run_day"),
            )
            .drop("local", "lh", "cd")
        )
        parts.append(local)
    if not parts:
        return pl.LazyFrame(schema=_schema())
    hours = pl.col("block").replace_strict(
        {int(block): hours for block, hours in _BLOCK_HOURS.items()}, return_dtype=pl.Int64
    )
    grouped = (
        pl.concat(parts)
        .group_by("apt", "run", "run_day", "day", "block", "start")
        .agg(
            pl.col("snow").sum(),
            pl.col("ice").sum(),
            pl.col("p_snow").max(),
            pl.col("p_zr").max(),
            pl.col("thunder").max(),
            pl.col("wind").max(),
            pl.col("gust").max(),
            pl.col("vis").min(),
            pl.col("cig").min(),
            pl.col("tmp").min(),
        )
        .sort("apt", "run", "day", "block")
    )
    grouped = (
        grouped.join(_pre_day(grouped), on=["apt", "run", "day"], how="left")
        .sort("apt", "run", "day", "block")
        .with_columns(
            (pl.col("snow").shift(1).fill_null(0.0) + pl.col("snow").shift(2).fill_null(0.0))
            .over("apt", "run")
            .alias("snow_before"),
            (pl.col("ice").shift(1).fill_null(0.0) + pl.col("ice").shift(2).fill_null(0.0))
            .over("apt", "run")
            .alias("ice_before"),
        )
        .with_columns(
            ((pl.col("start") - pl.col("run")).dt.total_minutes() / 60).alias("lead"),
            (pl.col("start") + pl.duration(hours=hours)).alias("end"),
            (pl.col("day") - pl.col("run_day")).dt.total_days().cast(pl.Int8).alias("lead_class"),
        )
        .filter(
            (pl.col("start") >= pl.col("run") + pl.duration(hours=FIRST_HOURS))
            & (pl.col("end") <= pl.col("run") + pl.duration(hours=LAST_HOURS))
            & pl.col("lead_class").is_between(LEADS[0], LEADS[-1])
        )
        .with_columns(
            pl.col("block").cast(pl.Int8),
            pl.col("pre_snow").fill_null(0.0),
            pl.col("pre_ice").fill_null(0.0),
            *[
                pl.col(name).fill_null(_FILL[name])
                for name in ("wind", "gust", "vis", "cig", "tmp")
            ],
        )
    )
    return grouped.select("apt", "run", "day", "block", "lead", "lead_class", "end", *BLOCK_COLUMNS)


def _pre_day(blocks: pl.LazyFrame) -> pl.LazyFrame:
    """Per airport, run and block day: the run's snow and ice on the days before that day (every
    block of the run, whole or not, from its first hour)."""
    return (
        blocks.group_by("apt", "run", "day")
        .agg(pl.col("snow").sum().alias("day_total"), pl.col("ice").sum().alias("ice_total"))
        .sort("apt", "run", "day")
        .with_columns(
            (pl.col("day_total").cum_sum() - pl.col("day_total"))
            .over("apt", "run")
            .alias("pre_snow"),
            (pl.col("ice_total").cum_sum() - pl.col("ice_total"))
            .over("apt", "run")
            .alias("pre_ice"),
        )
        .select("apt", "run", "day", "pre_snow", "pre_ice")
    )


_FILL: Final = {
    "wind": 0.0,
    "gust": 0.0,
    "vis": 10.0,
    "cig": float(NO_CEILING_HUNDREDS),
    "tmp": 50.0,
}


def _block_start(zone: str) -> pl.Expr:
    """The UTC start of a row's block, from its block day and block, in ``zone``."""
    start_hour = pl.col("block").replace_strict(
        {int(block): hour for block, hour in STARTS.items()}, return_dtype=pl.Int64
    )
    naive = pl.col("day").cast(pl.Datetime("us")) + pl.duration(hours=start_hour)
    return naive.dt.replace_time_zone(
        zone, ambiguous="earliest", non_existent="null"
    ).dt.convert_time_zone("UTC")


def _schema() -> dict[str, pl.DataType]:
    schema: dict[str, pl.DataType] = {
        "apt": pl.String(),
        "run": pl.Datetime("us", "UTC"),
        "day": pl.Date(),
        "block": pl.Int8(),
        "lead": pl.Float64(),
        "lead_class": pl.Int8(),
        "end": pl.Datetime("us", "UTC"),
    }
    schema.update({name: pl.Float64() for name in BLOCK_COLUMNS})
    return schema


def with_hubs(features: pl.DataFrame, hubs: Sequence[str]) -> pl.DataFrame:
    """Add the big hubs' snow and thunder for the same run, day and block (the knock-on, D6):
    ``hub_snow`` (their mean snow) and ``hub_storm`` (their mean chance of thunder); and the
    airport's whole day from the same run (airlines plan a storm day's cancellations for the
    day): ``day_snow``, ``day_ice`` (sums) and ``day_storm`` (the highest chance of thunder)."""
    features = features.with_columns(
        pl.col("snow").sum().over("apt", "run", "day").alias("day_snow"),
        pl.col("ice").sum().over("apt", "run", "day").alias("day_ice"),
        pl.col("thunder").max().over("apt", "run", "day").alias("day_storm"),
    )
    at_hubs = (
        features.filter(pl.col("apt").is_in(list(hubs)))
        .group_by("run", "day", "block")
        .agg(pl.col("snow").mean().alias("hub_snow"), pl.col("thunder").mean().alias("hub_storm"))
    )
    return features.join(at_hubs, on=["run", "day", "block"], how="left").with_columns(
        pl.col("hub_snow").fill_null(0.0), pl.col("hub_storm").fill_null(0.0)
    )


def newest_run(rows: pl.DataFrame) -> datetime | None:
    """The newest run in a frame of NBS rows."""
    if rows.is_empty():
        return None
    value = rows.select(pl.col("run").max()).item()
    return value if isinstance(value, datetime) else None
