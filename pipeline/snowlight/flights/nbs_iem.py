"""IEM's copy of the NBS station guidance (FL-1b.1): the same product, two more winters.

The AWS bucket's bulletins (:mod:`snowlight.flights.nbs`) start in mid 2020. The Iowa
Environmental Mesonet (IEM) keeps the same NBS, run by run, from 2018-11-07 (``mos.py``, model
NBS; 00Z runs until 2020-02-25, 01Z after). Its 00Z runs are read here into the exact rows the
history keeps from the bulletins (:func:`snowlight.flights.live.rows_of`: station, run, valid
and the elements as the bulletin writes them), so :mod:`snowlight.flights.features` reads them
unchanged.

The unit map (IEM's codes into the bulletin's units, element by element), proven on the 00Z runs
both sources hold after the test year (2026-10-01 on) and, for the 2018-2020 NBM version, by
month-by-element ranges against the first AWS months:

* ``TMP`` ``WSP`` ``GST`` ``P06`` ``PZR`` ``PSN`` ``T03`` ``S06`` ``I06``: the same numbers
  (IEM writes some as decimals: rounded);
* ``CIG``: the same hundreds of feet; IEM's 888 (no ceiling) is the bulletin's -88;
* ``VIS``: tenths of a mile, IEM's whole miles before :data:`VIS_MILES_BEFORE` times 10;
* 999 in any element is IEM's no value: none, never a number.

Holes stay holes: a run IEM lacks is never filled with a later run.
"""

from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Final

import polars as pl

from snowlight.flights.nbs import ELEMENTS

IEM_MISSING: Final = 999
IEM_NO_CEILING: Final = 888
NO_CEILING: Final = -88
VIS_TENTHS: Final = 10
VIS_MILES_BEFORE: Final = date(2020, 2, 20)
"""Runs before this day (NBM 3.1) give ``vis`` in whole miles, read as tenths (``x 10``); from
it on (NBM 3.2, then 4.x) IEM keeps the bulletin's own tenths of a mile. Found in IEM's rows:
the median visibility of every 00Z run is 9 to 15 through 2020-02-19, there is no 00Z run on
2020-02-20, and it is 110 from 2020-02-21; on the runs both sources hold from 2026-10-01 IEM's
``vis`` equals the bulletin's ``VIS``."""
VIS_MAX: Final = 100
"""The bulletin caps visibility at 10 miles (100 tenths) from the 2020 NBM version on."""
FIRST_HOUR: Final = 6
LAST_HOUR: Final = 72

ROW_SCHEMA: Final[dict[str, pl.DataType]] = {
    "station": pl.String(),
    "run": pl.Datetime("us", "UTC"),
    "valid": pl.Datetime("us", "UTC"),
    **{name: pl.Int16() for name in ELEMENTS},
}


def _element(name: str, columns: Sequence[str]) -> pl.Expr:
    column = name.lower()
    if column not in columns:
        return pl.lit(None, dtype=pl.Int16).alias(name)
    value = pl.col(column).cast(pl.Float64, strict=False).round(0)
    value = pl.when(value == IEM_MISSING).then(None).otherwise(value)
    if name == "CIG":
        value = pl.when(value == IEM_NO_CEILING).then(NO_CEILING).otherwise(value)
    elif name == "VIS":
        miles = pl.col("runtime").dt.date() < VIS_MILES_BEFORE
        value = pl.min_horizontal(
            pl.when(miles).then(value * VIS_TENTHS).otherwise(value), pl.lit(VIS_MAX)
        )
    return value.cast(pl.Int16, strict=False).alias(name)


def to_rows(frame: pl.DataFrame) -> pl.DataFrame:
    """IEM's NBS rows (as :func:`snowlight.flights.pull.reduce_mos` keeps them: text, 00Z runs,
    ``runtime`` and ``ftime`` as times) in the history's row shape: one row per station, run and
    valid hour from 6 to 72 hours after the run; a duplicated row is kept once."""
    if frame.is_empty() or "runtime" not in frame.columns:
        return pl.DataFrame(schema=ROW_SCHEMA)
    hours = (pl.col("valid") - pl.col("run")).dt.total_hours()
    return (
        frame.select(
            pl.col("station").cast(pl.String),
            pl.col("runtime").alias("run"),
            pl.col("ftime").alias("valid"),
            *[_element(name, frame.columns) for name in ELEMENTS],
        )
        .filter(
            pl.col("run").is_not_null()
            & (pl.col("run").dt.hour() == 0)
            & hours.is_between(FIRST_HOUR, LAST_HOUR)
        )
        .unique(subset=["station", "run", "valid"], keep="first", maintain_order=True)
        .sort("station", "run", "valid")
        .cast(ROW_SCHEMA)  # type: ignore[arg-type]
    )


def convert(source: Path, target: Path) -> int:
    """Each kept IEM table under ``source`` (one per station and winter, from the pull) as rows
    under ``target`` (same file names), skipping those already there; how many were written."""
    target.mkdir(parents=True, exist_ok=True)
    written = 0
    for path in sorted(source.glob("*.parquet")):
        out = target / path.name
        if out.exists():
            continue
        rows = to_rows(pl.read_parquet(path))
        part = out.with_suffix(".part")
        rows.write_parquet(part, compression="zstd")
        part.replace(out)
        written += 1
    return written
