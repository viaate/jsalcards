"""The spans whose cancellations had nothing to do with weather.

Every Flights figure that stands for behaviour in weather leaves them out: the fit and the test
(:mod:`snowlight.flights.train`), the own records (:mod:`snowlight.flights.records`), the replays,
and the usual flights' cancelled and late counts (:mod:`snowlight.flights.bts`, the ``sched``
table).
"""

from datetime import date
from typing import Final

import polars as pl

NOT_WEATHER: Final = (
    (date(2024, 7, 19), date(2024, 7, 23), "the July 2024 airline computer outage"),
    (date(2025, 11, 7), date(2025, 11, 15), "the FAA's ordered flight cuts in the 2025 shutdown"),
)
"""Spans whose cancellations had nothing to do with weather: left out of fitting and testing
alike (each says why)."""


def weather_days(column: str = "day") -> pl.Expr:
    """Rows whose ``column`` (a date) lies outside every :data:`NOT_WEATHER` span."""
    keep = pl.lit(value=True)
    for first, last, _ in NOT_WEATHER:
        keep = keep & ~pl.col(column).is_between(first, last)
    return keep
