"""The usual flights on each route (D11), from the BTS ``sched`` tables.

For each departure airport and posted month: every flight number that flew from it, with its
route, its scheduled times, the weekdays it flew, how many days, and how many of those it was
cancelled or left 45+ minutes late. These are what usually flies, labeled with their month; they
never say a flight is on sale or has seats.

The months published are the newest posted month and the same months a year before the month a
trip is likely in (:func:`months_for`): this month and next month, a year back.
"""

from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path

import polars as pl

from snowlight.flights.airports import current_code
from snowlight.flights.bts import Month, has_month, table_path
from snowlight.schemas.flights import FlightsRouteMonth, FlightsRoutes, FlightsUsualFlight

MIN_DAYS = 2
"""A flight that flew on fewer days of the month is not a usual flight (a one-off)."""


def months_for(newest: Month, today: date) -> list[Month]:
    """The newest posted month, then this month and next month a year back (each once)."""
    this = Month(today.year - 1, today.month)
    wanted = [newest, this, this.next()]
    out: list[Month] = []
    for month in wanted:
        if month not in out and (month.year, month.month) <= (newest.year, newest.month):
            out.append(month)
    return out


def _minutes(hhmm: int) -> int:
    return (hhmm // 100 % 24) * 60 + hhmm % 100


def month_flights(sched: pl.DataFrame) -> pl.DataFrame:
    """One month's usual flights: per carrier, number, route and times, the weekdays flown
    (Monday bit 0) and the days, cancellations and late departures summed."""
    return (
        sched.with_columns(current_code("dep_apt"), current_code("arr_apt"))
        .filter(pl.col("number").is_between(1, 9999))
        .group_by("carrier", "number", "dep_apt", "arr_apt", "dep_time", "arr_time")
        .agg(
            pl.lit(2)
            .pow(pl.col("weekday").cast(pl.Int64) - 1)
            .unique()
            .sum()
            .cast(pl.Int64)
            .alias("weekdays"),
            pl.col("days").sum(),
            pl.col("canc").sum(),
            pl.col("late").sum(),
        )
        # The group's whole key, then its sums: every row has one place, so a build repeats.
        .sort(
            "dep_apt",
            "dep_time",
            "carrier",
            "number",
            "arr_apt",
            "arr_time",
            "weekdays",
            "days",
            "canc",
            "late",
        )
    )


def build(
    root: Path,
    months: Sequence[Month],
    airports: Sequence[str],
    generated_at: datetime,
) -> dict[str, FlightsRoutes]:
    """The routes file of every airport in ``airports``."""
    per: dict[str, list[FlightsRouteMonth]] = {code: [] for code in airports}
    for month in months:
        if not has_month(root, month):
            continue
        flights = month_flights(pl.read_parquet(table_path(root, "sched", month)))
        for (code,), group in flights.group_by("dep_apt", maintain_order=True):
            if code not in per:
                continue
            per[str(code)].append(
                FlightsRouteMonth(
                    month=f"{month.year}-{month.month:02d}",
                    flights=tuple(
                        FlightsUsualFlight(
                            carrier=row["carrier"],
                            number=row["number"],
                            to_airport=row["arr_apt"],
                            leaves=_minutes(row["dep_time"]),
                            lands=_minutes(row["arr_time"]),
                            weekdays=min(127, int(row["weekdays"])),
                            days=row["days"],
                            cancelled=row["canc"],
                            late=row["late"],
                        )
                        for row in group.iter_rows(named=True)
                        if row["weekdays"] > 0 and row["days"] >= MIN_DAYS
                    ),
                )
            )
    return {
        code: FlightsRoutes(
            schema_version=1, generated_at=generated_at, code=code, months=tuple(found)
        )
        for code, found in per.items()
    }
