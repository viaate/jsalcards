"""The night chart's rule, option (iv): true hourly bars from NOAA's National Blend of Models
(NBM) deterministic 1-hour snowfall, from the next whole hour to 07:00 local on the day
(docs/predict.md, "The night chart"; design spec chart-data r3, section 4.8).

Pure numpy over one district's deciding schools: the window and the day come from the contract
(:func:`snowlight.schemas.predictions.night_window`, never a copy here), and the amounts from
:mod:`snowlight.predict.nbm`. Every number the chart states is a sum of the cycle's own 1-hour
amounts, rounded the way that keeps it true of every school:

* ``least[i]``: the least running total at any school at the end of hour i, in tenths rounded
  down, so each bar is at or below every school's own amount at its instant;
* ``low`` to ``high``: the lowest total rounded down and the highest rounded up (tenths under
  2 in, whole inches from 2 in), so every school's total is inside;
* ``heavy``: shown only when every school gets 0.5 in or more over the window, each school's
  heaviest 3 consecutive hours (the earliest on a tie) lie inside one span of 3 or 4 hours, and
  the bars rise over that span at 1.5 times the window's mean hourly rate or more.

A district gets no chart (``None``) unless every deciding school was read (no missing value),
the district's 50% value of the total is at least :data:`NIGHT_MIN_INCHES`, and every number is
inside the contract's bounds.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Final

import numpy as np
import numpy.typing as npt

from snowlight.schemas.predictions import (
    NIGHT_MAX_BARS,
    NIGHT_MAX_HIGH,
    NIGHT_MAX_LEAST,
    NIGHT_MIN_INCHES,
    NIGHT_SPANS,
    NIGHT_TENTHS_BELOW,
    NightSnow,
)

type Floats = npt.NDArray[np.float64]

SNAP: Final = 1e-5
"""Float noise never adds a rounding step (inches). NBM's amounts are whole millimetres, so a
total sits exactly on a tenth or inch step (127 mm is 5.0 in) or at least 7.9e-4 in from every
step; the converted sums drift by far less than this snap, and far less than that gap (critic
r1 B1)."""
HEAVY_HOURS: Final = 3
"""Each school's heaviest run of this many consecutive hours."""
HEAVY_FLOOR: Final = 0.5
"""Every school gets at least this much over the window, or no heaviest span is named."""
HEAVY_RATE: Final = 1.5
"""The span's rise is at least this many times the window's mean hourly rate."""
_HOUR: Final = timedelta(hours=1)
_DIGITS: Final = 5
"""Whole-millimetre sums in inches differ by at least 0.039 in: they compare equal at 1e-5."""


@dataclass(frozen=True, slots=True)
class NightInputs:
    """One district's night: its day, its window, and the NBM 1-hour snowfall in inches at
    each deciding school for each hour of the window, ``(hours, schools)``, NaN where not read.
    The amounts are NBM's metres converted and never rounded one by one, so a sum of hours is
    the cycle's own total (:func:`snowlight.predict.nbm.sample`)."""

    day: date
    zone: str
    start: datetime
    end: datetime
    snow: Floats

    @property
    def hours(self) -> int:
        """The window's hours."""
        return round((self.end - self.start) / _HOUR)


def floor_tenths(values: Floats) -> Floats:
    """Rounded down to a tenth, after the snap."""
    return np.round(np.floor(values * 10 + SNAP) / 10, 1)


def ceil_tenths(values: Floats) -> Floats:
    """Rounded up to a tenth, after the snap."""
    return np.round(np.ceil(values * 10 - SNAP) / 10, 1)


def outward(low: float, high: float) -> tuple[float, float]:
    """A range rounded outward: tenths when its high end rounds up to under 2 in, else whole
    inches."""
    up = float(ceil_tenths(np.array([high]))[0])
    if up < NIGHT_TENTHS_BELOW:
        return float(floor_tenths(np.array([low]))[0]), up
    return float(np.floor(low + SNAP)), float(np.ceil(high - SNAP))


def half_value(totals: Floats, share: float = 0.5) -> float:
    """The district's 50% value: the largest amount at least ``share`` of its schools reach
    (as :func:`snowlight.predict.ndfd.group_half`)."""
    ordered = np.sort(totals)[::-1]
    needed = max(int(np.ceil(share * ordered.shape[0] - SNAP)), 1)
    return float(ordered[needed - 1])


def heavy_span(snow: Floats, least: Floats) -> tuple[int, int] | None:
    """The heaviest span as (first, last) hours from Start, or None (see the module docstring)."""
    hours = snow.shape[0]
    totals = snow.sum(axis=0)
    if hours < HEAVY_HOURS or float(totals.min()) < HEAVY_FLOOR - SNAP:
        return None
    runs = np.lib.stride_tricks.sliding_window_view(snow, HEAVY_HOURS, axis=0).sum(axis=-1)
    best = np.round(runs, _DIGITS).argmax(axis=0)  # the earliest on a tie
    first, last = int(best.min()), int(best.max()) + HEAVY_HOURS
    if last - first not in NIGHT_SPANS:
        return None
    before = float(least[first - 1]) if first > 0 else 0.0
    rise = (float(least[last - 1]) - before) / (last - first)
    mean = float(least[-1]) / hours
    if rise < HEAVY_RATE * mean - SNAP:
        return None
    return first, last


def night(inputs: NightInputs, min_inches: float = NIGHT_MIN_INCHES) -> NightSnow | None:
    """The district's night chart, or None when the rule shows none (see the module docstring)."""
    snow = np.asarray(inputs.snow, dtype=np.float64)
    hours = inputs.hours
    if snow.ndim != 2 or snow.shape[0] != hours or snow.shape[1] == 0:  # noqa: PLR2004
        return None
    if not 1 <= hours <= NIGHT_MAX_BARS or not np.isfinite(snow).all() or (snow < 0).any():
        return None
    running = np.cumsum(snow, axis=0)
    totals = running[-1]
    if half_value(totals) < min_inches - SNAP:
        return None
    least = floor_tenths(running.min(axis=1))
    low, high = outward(float(totals.min()), float(totals.max()))
    if float(least.max()) > NIGHT_MAX_LEAST or high > NIGHT_MAX_HIGH:
        return None
    return NightSnow(
        least=tuple(float(value) for value in least),
        low=low,
        high=high,
        heavy=heavy_span(snow, least),
    )
