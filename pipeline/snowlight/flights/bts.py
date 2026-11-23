"""The BTS On-Time Reporting history: one month's file reduced to compact tables.

Source (public domain, no key): ``https://transtats.bts.gov/PREZIP/`` +
``On_Time_Reporting_Carrier_On_Time_Performance_1987_present_<Y>_<M>.zip``, one row per
scheduled domestic flight of the reporting carriers. The raw file (about 260 MB unzipped) stays in
RAM (``/dev/shm/flights``) and is deleted once reduced; only these tables are kept:

* ``dep``: by departure airport, block day, block and carrier: flights scheduled, cancelled, and
  of those that left, how many left 45+ minutes late;
* ``arr``: the same by arrival airport and scheduled arrival block (arrivals 45+ minutes late);
* ``sched``: each flight number's scheduled route and times by weekday, with how many days it
  flew and how many of those it was cancelled or left 45+ minutes late (the usual flights, D11),
  the days of a non-weather span left out;
* ``places``: each airport's city and state as BTS names them;
* ``legs``: every flight's carrier, airports, block days and blocks, and whether it was
  cancelled or left (arrived) 45+ minutes late, for the held-out test of a flight's chance.

Times are the airports' own local clocks, as BTS writes them. A scheduled arrival clock earlier
than its departure clock is taken to land the next calendar day.
"""

import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

import polars as pl

from snowlight.flights.blocks import DAY_START_HOUR, STARTS, Block
from snowlight.flights.spans import weather_rows

LATE_MINUTES: Final = 45
"""A departure (or arrival) this many minutes after its scheduled time is late (D6)."""

BTS_URL: Final = (
    "https://transtats.bts.gov/PREZIP/"
    "On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{year}_{month}.zip"
)

COLUMNS: Final = (
    "FlightDate",
    "Reporting_Airline",
    "Flight_Number_Reporting_Airline",
    "Origin",
    "OriginCityName",
    "OriginState",
    "Dest",
    "DestCityName",
    "DestState",
    "CRSDepTime",
    "DepDelay",
    "CRSArrTime",
    "ArrDelay",
    "Cancelled",
    "Diverted",
)

TABLES: Final = ("dep", "arr", "sched", "places", "legs")


@dataclass(frozen=True, slots=True)
class Month:
    """A BTS month."""

    year: int
    month: int

    @property
    def key(self) -> str:
        """``2026_9``: the month as BTS names its file."""
        return f"{self.year}_{self.month}"

    @property
    def first(self) -> date:
        """The month's first day."""
        return date(self.year, self.month, 1)

    def next(self) -> "Month":
        """The month after."""
        return Month(self.year + self.month // 12, self.month % 12 + 1)

    def back(self, months: int) -> "Month":
        """The month ``months`` before."""
        index = self.year * 12 + self.month - 1 - months
        return Month(index // 12, index % 12 + 1)

    @classmethod
    def parse(cls, text: str) -> "Month":
        """Read ``2026-09`` or ``2026_9``."""
        year, month = text.replace("_", "-").split("-")
        value = cls(int(year), int(month))
        if not 1 <= value.month <= 12:  # noqa: PLR2004 - months of a year
            raise ValueError(f"not a month: {text}")
        return value

    def url(self) -> str:
        """The month's file on the BTS server."""
        return BTS_URL.format(year=self.year, month=self.month)


def months(first: Month, last: Month) -> Iterator[Month]:
    """Every month from ``first`` to ``last``, both included."""
    month = first
    while (month.year, month.month) <= (last.year, last.month):
        yield month
        month = month.next()


def _block_expr(hour: pl.Expr) -> pl.Expr:
    """The block (an int) of a local hour."""
    return (
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
        .cast(pl.Int8)
    )


def read_rows(source: pl.LazyFrame) -> pl.LazyFrame:
    """The flights of a raw month (all text columns), typed, with block days and blocks."""
    flights = (
        source.select(COLUMNS)
        .with_columns(
            pl.col("FlightDate").str.to_date(),
            pl.col("CRSDepTime").cast(pl.Int32, strict=False),
            pl.col("CRSArrTime").cast(pl.Int32, strict=False),
            pl.col("DepDelay").cast(pl.Float32, strict=False),
            pl.col("ArrDelay").cast(pl.Float32, strict=False),
            (pl.col("Cancelled").cast(pl.Float32) > 0).alias("cancelled"),
            (pl.col("Diverted").cast(pl.Float32) > 0).alias("diverted"),
            pl.col("Flight_Number_Reporting_Airline").cast(pl.Int32, strict=False).alias("number"),
        )
        .filter(pl.col("CRSDepTime").is_not_null() & pl.col("CRSArrTime").is_not_null())
    )
    dep_hour = (pl.col("CRSDepTime") // 100) % 24
    arr_hour = (pl.col("CRSArrTime") // 100) % 24
    arr_calendar = pl.col("FlightDate") + pl.duration(
        days=(pl.col("CRSArrTime") < pl.col("CRSDepTime")).cast(pl.Int32)
    )
    return flights.with_columns(
        _block_expr(dep_hour).alias("dep_block"),
        (pl.col("FlightDate") - pl.duration(days=(dep_hour < DAY_START_HOUR).cast(pl.Int32))).alias(
            "dep_day"
        ),
        _block_expr(arr_hour).alias("arr_block"),
        (arr_calendar - pl.duration(days=(arr_hour < DAY_START_HOUR).cast(pl.Int32))).alias(
            "arr_day"
        ),
        (~pl.col("cancelled") & (pl.col("DepDelay") >= LATE_MINUTES)).alias("dep_late"),
        (~pl.col("cancelled") & (pl.col("diverted") | (pl.col("ArrDelay") >= LATE_MINUTES))).alias(
            "arr_late"
        ),
        pl.col("FlightDate").dt.weekday().cast(pl.Int8).alias("weekday"),
    )


def _counts(late: str) -> list[pl.Expr]:
    return [
        pl.len().cast(pl.Int32).alias("n"),
        pl.col("cancelled").sum().cast(pl.Int32).alias("canc"),
        pl.col(late).sum().cast(pl.Int32).alias("late"),
    ]


def reduce_rows(rows: pl.LazyFrame) -> dict[str, pl.DataFrame]:
    """The compact tables of one month's typed rows (:func:`read_rows`)."""
    dep = (
        rows.group_by(
            pl.col("Origin").alias("apt"),
            pl.col("dep_day").alias("day"),
            pl.col("dep_block").alias("block"),
            pl.col("Reporting_Airline").alias("carrier"),
        )
        .agg(_counts("dep_late"))
        .sort("apt", "day", "block", "carrier")
    )
    arr = (
        rows.group_by(
            pl.col("Dest").alias("apt"),
            pl.col("arr_day").alias("day"),
            pl.col("arr_block").alias("block"),
            pl.col("Reporting_Airline").alias("carrier"),
        )
        .agg(_counts("arr_late"))
        .sort("apt", "day", "block", "carrier")
    )
    sched = (
        # The usual flights' counts stand for weather days only (D11): a non-weather span's
        # days (:data:`snowlight.flights.spans.NOT_WEATHER`, and an airline's own in
        # :data:`snowlight.flights.spans.CARRIER_NOT_WEATHER`) are left out of them.
        rows.filter(
            pl.col("number").is_not_null() & weather_rows("FlightDate", "Reporting_Airline")
        )
        .group_by(
            pl.col("Reporting_Airline").alias("carrier"),
            "number",
            pl.col("Origin").alias("dep_apt"),
            pl.col("Dest").alias("arr_apt"),
            pl.col("CRSDepTime").alias("dep_time"),
            pl.col("CRSArrTime").alias("arr_time"),
            "weekday",
        )
        .agg(_counts("dep_late"))
        .rename({"n": "days"})
        .sort("carrier", "number", "dep_apt", "dep_time", "weekday")
    )
    places = (
        pl.concat(
            [
                rows.select(
                    pl.col("Origin").alias("apt"),
                    pl.col("OriginCityName").alias("city"),
                    pl.col("OriginState").alias("state"),
                ),
                rows.select(
                    pl.col("Dest").alias("apt"),
                    pl.col("DestCityName").alias("city"),
                    pl.col("DestState").alias("state"),
                ),
            ]
        )
        .group_by("apt", "city", "state")
        .agg(pl.len().cast(pl.Int32).alias("n"))
        .sort("apt", "n", descending=[False, True])
    )
    legs = rows.select(
        pl.col("Reporting_Airline").alias("carrier"),
        pl.col("Origin").alias("dep_apt"),
        pl.col("Dest").alias("arr_apt"),
        "dep_day",
        "dep_block",
        "arr_day",
        "arr_block",
        "cancelled",
        "dep_late",
        "arr_late",
    )
    frames = pl.collect_all([dep, arr, sched, places, legs])
    return dict(zip(TABLES, frames, strict=True))


def reduce_csv(csv: Path) -> dict[str, pl.DataFrame]:
    """The compact tables of a raw month's CSV."""
    return reduce_rows(read_rows(pl.scan_csv(csv, infer_schema=False, encoding="utf8-lossy")))


def reduce_zip(archive: Path, scratch: Path) -> dict[str, pl.DataFrame]:
    """The compact tables of a downloaded month's zip; the CSV is unzipped to ``scratch`` and
    deleted after."""
    with zipfile.ZipFile(archive) as bundle:
        names = [name for name in bundle.namelist() if name.endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"{archive.name}: expected one CSV, found {len(names)}")
        csv = Path(bundle.extract(names[0], scratch))
    try:
        return reduce_csv(csv)
    finally:
        csv.unlink(missing_ok=True)


def table_path(root: Path, table: str, month: Month) -> Path:
    """Where a month's compact table is kept."""
    return root / table / f"{month.key}.parquet"


def has_month(root: Path, month: Month) -> bool:
    """Whether every compact table of the month is kept."""
    return all(table_path(root, table, month).is_file() for table in TABLES)


def write_month(root: Path, month: Month, tables: dict[str, pl.DataFrame]) -> None:
    """Keep a month's compact tables (each written whole, then renamed)."""
    for table in TABLES:
        path = table_path(root, table, month)
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_suffix(".part")
        tables[table].write_parquet(part, compression="zstd")
        part.replace(path)


def scan(root: Path, table: str) -> pl.LazyFrame:
    """Every kept month of one compact table."""
    return pl.scan_parquet(root / table / "*.parquet")


def kept_months(root: Path) -> list[Month]:
    """The months whose compact tables are all kept, oldest first."""
    found = sorted(
        (Month.parse(path.stem) for path in (root / "dep").glob("*.parquet")),
        key=lambda m: (m.year, m.month),
    )
    return [month for month in found if has_month(root, month)]
