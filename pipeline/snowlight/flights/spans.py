"""The spans whose cancellations had nothing to do with weather.

Every Flights figure that stands for behaviour in weather leaves them out: the fit and the test
(:mod:`snowlight.flights.train`), the own records (:mod:`snowlight.flights.records`), the replays,
and the usual flights' cancelled and late counts (:mod:`snowlight.flights.bts`, the ``sched``
table).

Two kinds (each found in the data first and given its reason):

* :data:`NOT_WEATHER`: days left out at every airport and for every airline;
* :data:`CARRIER_NOT_WEATHER`: one airline's days, left out of the airline-level tables (each
  airline's flights) before they are summed to airports, so the other airlines' flights on
  those days still count.
"""

from datetime import date, timedelta
from typing import Final

import polars as pl

NOT_WEATHER: Final = (
    (
        date(2020, 3, 10),
        date(2020, 6, 7),
        "the COVID-19 collapse in flying in 2020 (cancelled for no passengers, not weather)",
    ),
    (date(2024, 7, 19), date(2024, 7, 23), "the July 2024 airline computer outage"),
    (date(2025, 11, 7), date(2025, 11, 15), "the FAA's ordered flight cuts in the 2025 shutdown"),
)
"""Spans whose cancellations had nothing to do with weather: left out of fitting and testing
alike (each says why).

COVID-19 (found in the BTS departures, every airline summed by day): the national cancelled share
was 0.1 to 0.5% on each day of early March 2020, 0.9% on March 10 and 1.3% on March 11, over 5%
from March 17 and up to 53% at the end of March, and stayed above 2% to May 31; June 1 to 7 were
back to 0.4 to 1.2% while the schedules were still cut, and are left out too as the margin the
lead set."""

CARRIER_NOT_WEATHER: Final = (
    (
        "WN",
        date(2022, 12, 24),
        date(2022, 12, 31),
        "the Southwest Airlines meltdown of December 2022",
    ),
)
"""One airline's days whose cancellations were that airline's own failure, not weather: left out
of that airline's flights only (each says why).

The Southwest meltdown (found in the BTS departures): during the December 2022 storm Southwest
cancelled 26 to 37% on December 22 and 23 against 10 to 25% for the other airlines together (the
storm, kept); then 44% on December 24 against 16%, and 52 to 78% from December 25 to 29 while
the other airlines were back to 1 to 11%. December 30 and 31 were back to about 1% and are left
out too as the margin the lead set."""


def weather_days(column: str = "day") -> pl.Expr:
    """Rows whose ``column`` (a date) lies outside every :data:`NOT_WEATHER` span."""
    keep = pl.lit(value=True)
    for first, last, _ in NOT_WEATHER:
        keep = keep & ~pl.col(column).is_between(first, last)
    return keep


def carrier_weather(day: str = "day", carrier: str = "carrier") -> pl.Expr:
    """Airline-level rows outside every :data:`CARRIER_NOT_WEATHER` span (an airline's rows on
    its span's days are left out; every other row is kept)."""
    keep = pl.lit(value=True)
    for code, first, last, _ in CARRIER_NOT_WEATHER:
        keep = keep & ~((pl.col(carrier) == code) & pl.col(day).is_between(first, last))
    return keep


def weather_rows(day: str = "day", carrier: str = "carrier") -> pl.Expr:
    """Airline-level rows outside every non-weather span of both kinds."""
    return weather_days(day) & carrier_weather(day, carrier)


def not_weather_days(first: date, last: date) -> int:
    """How many days from ``first`` to ``last`` (both in) lie in a :data:`NOT_WEATHER` span."""
    days = 0
    for start, end, _ in NOT_WEATHER:
        low, high = max(first, start), min(last, end)
        if low <= high:
            days += (high - low) // timedelta(days=1) + 1
    return days
