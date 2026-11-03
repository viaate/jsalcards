"""The forecast adjustment (advisory-sane L5, Addendum A item 3): how the forecast for the school
morning moves a storm-class day's chance within its class.

A storm-class day starts from its class's level for the district (:mod:`snowlight.predict.
anchor`: the capture-corrected level, the district's exposure, the live labels and the
plausibility pull), ``p0``. From the class snapshot on (9 PM the evening before on the school's
clock; never before it, so no earlier run with a longer lead and no day after the next school
day's is read: turn-on items 8 and 10), the forecast read then (:mod:`snowlight.predict.
forecast_live`, the newest run at most 3 hours old) moves it on the log-odds scale by a few
transparent terms, each with a physical reason:

* **Snow against the district's own climate** (two-sided): ``a ln((s + c) / (u + c))``, ``s``
  the district's 50% value of the window's snow still to come (the periods ending 06, 12 and
  18 UTC on the day, never snow already down: SF-R5-1, :func:`snowlight.predict.ndfd.
  window_total`), ``u`` the snow usual for the district on days of the class (below). An inch
  over a usual half inch (Atlanta) moves the chance far more than an inch under a usual 3
  inches (Buffalo): a dusting lowers it, a heavy forecast raises it. Where the district's
  days of the class are often icy, the usual snow counts the ice days, so the same inches
  count for a little less there (PHYS-R3-S1 (i), a documented limit: the round-4 anchor at
  the snow alone is gone, the lead's ruling of Nov 1, since its flat stretch let more snow
  lower the chance where ice is forecast; the snow amount term's floor, registered on, is
  its monotone successor: :func:`floor_lift`).
* **Timing** (two-sided): snow from 10 PM the evening before to 9 AM on the school's clock is
  on the roads for the buses, with little time to plow it; snow earlier in the evening is
  plowed and treated by morning, and snow after 9 AM falls on a school day already under way.
  Each deciding school's own snow inside 10 PM to 9 AM is counted first, and the district
  takes its 50% value by the same rule as ``s`` (``commute``); the snow weighed by its hours,
  against the same snow even through the window, is ``W = (outside s + (1 - outside) commute)
  / even`` (:func:`weighed`), held to a band of ``timing_max`` either way phased in from no
  snow to ``timing_min_snow`` (:func:`timed`): the term is ``a ln((W + c) / (s + c))``. Its
  line names the heaviest snow by the hour where that is on the term's side, else the
  heaviest on its side (``snow_hours``: "snow from 12 AM to 6 AM"), from the periods' own 50%
  values where they stand for the window's snow (:func:`_named`); else its points go with the
  snow's line.
* **Ice** (adds only): freezing rain on the roads, an inch of ice counted as ``ice_snow``
  inches of snow on top of the day's snow, ``a ln((W + k i + c) / (W + c))``.
* **Cold at the bus stop** (adds only): how cold it feels at 7 AM below ``chill_from``,
  ``chill_per_degree`` a degree up to ``chill_max``: snow stays on cold roads and the wait at
  the stop is harsh.

Snow, timing and ice together are one log, ``a ln((W + k i + c) / (u + c))``, so more snow in
any period at any deciding school, more ice or more cold never lowers the chance (PHYS-R2-B1:
each school's hours are weighed before the district's 50% value is taken). The sum is bounded
per class (``bounds_<class>``): an advisory day moves at most 0.7 down, to about half its
level, and about 7 times its odds up (10% to 5% or 45%); a warning day at most 0.4 down, 1.5
up: a 9 PM read cannot see a storm's snow already on the ground (SF-R5-1 counts only the snow
still to come), so no snow ahead lowers a day only so far (PHYS-R3-S2, the lead's ruling of
Nov 1, 2026). An advisory day is never over the same district's winter warning days for the
same forecast (the class order: :func:`order_cap`, the warning class solved first). A cold
day is not moved: the cold is the class itself, and its level is already the cold's; nor is a
blizzard warning day (its wind is the hazard as much as the new snow, and wind is not a term)
or a tropical storm or hurricane warning day, whose hazard is not the snow (:data:`SKIP`).

**Calibration.** ``u`` is solved per district and class level so that, over the forecasts the
district had on its own days of the class (the forecast history's 9 PM codes, 2018-19 on,
joined to the weather history's class days: ``data/predict/forecast-climate.json.gz``), the
adjusted chance averages ``p0``: each code stands for its bucket's middle (a quiet day for
:data:`QUIET` inches), and each snow or ice day's morning is cold as the district's own quiet
and cold mornings are (:func:`cold_mix`), since the live cold term counts a cold snowy morning
too. So each district's days of each class still average its class level, and the
plausibility check (G6) holds on the adjusted chances as published. ``u`` is the district's
usual snow in exactly this sense: the forecast at which its chance is its class level. A
district with few days of a class borrows from its county's (or its region's) days,
``shrink_days`` of them. The climate file says how its codes counted the period under way at 9
PM (``window``: ``whole`` for the history collected before SF-R5-1 was fixed); a ``whole``
climate's amounts are scaled to the fixed window by the zone's share of the window still to
come at 9 PM (:func:`window_scale`), and a file that does not say is refused. The calibration
is exact on those code values; a live quiet day that reads 0.00 or 0.4 inches moves its
district's average a little off its level (docs/predict.md gives the measured bounds), and
each pass logs the mean of the published chance less the class level per class
(:func:`shift_note`).

**The snow amount term** (predict-next SNOW-AMOUNT, registered on by SNOW-AMOUNT-2:
``snow_amount``): each class has its own slope (:meth:`AdjustSettings.for_class`), the total
is never under the snow alone's floor (:func:`floor_lift`), and over the class's upper bound it
bends toward ``snow_amount_high`` instead of stopping there (:func:`saturated`), so big amounts
keep rising; the solve and serving hold the total the same way. A within-date test with a
season held out found it no worse than L5 (docs/predict.md, "The snow amount term"); off, the
terms are L5's exactly.

**The bus hour timing term** (predict-next BUS-TIMING, registered on: ``timing_bus``): the
timing weighs snow down by the bus hour (07:00 on the school's clock,
:func:`snowlight.predict.ndfd.bus_time`) against snow after it, in place of 10 PM to 9 AM.
Each deciding school's own snow before the bus hour is counted first and the district takes
its 50% value by the same rule as ``s`` (``snow_bus``); ``W = (o s + (1 - o) snow_bus) /
even_bus``, ``o`` ``timing_after_bus``, ``even_bus = o + (1 - o) min(f, F)``, ``f`` the
window's before-bus share by the hour and ``F`` ``timing_bus_share_max`` (:func:`window_even`,
:func:`weighed`), in the same band and log as L5's. Even snow weighs exactly as itself wherever
``f <= F`` (every lower-48 zone at 9 PM and every later snapshot), so their even factors are 1;
a line that raises names only a period more than half before the bus hour, one that lowers only
a period more than half after it (:func:`_named`). ``o`` was fit within date with each season
held out over 0.0 to 0.95 (ties to the largest, the weakest timing): 0.95, the grid's top;
docs/predict.md, "The bus hour timing term", says what the record can and cannot show. Off,
the timing is L5's exactly.

No forecast, a forecast that did not read, a code that is unknown, or a stale run (none at
most 3 hours old at the snapshot): no term, the chance is the class level ``p0`` and no
forecast line shows (or, once the snapshot has passed, the same snapshot's lines as the last
file had them: :mod:`snowlight.predict.serve`). Nothing here reads a closure share of any kind;
the climate file holds codes and counts only.
"""

import gzip
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Final, Literal
from zoneinfo import ZoneInfo

import numpy as np
import numpy.typing as npt
import polars as pl

from snowlight.predict import ndfd
from snowlight.predict.config import PIPELINE_ROOT, PredictConfig
from snowlight.predict.forecast_values import DistrictForecast, SnowPart, bus_share, commute_share
from snowlight.predict.geography import REGION_OF
from snowlight.predict.reasons import Moved, chill_amount, ice_amount
from snowlight.predict.shapley import shapley, whole_points
from snowlight.schemas.predictions import (
    Forecast,
    IceReason,
    PredictionsFile,
    ReasonPoints,
    SnowHoursReason,
    SnowTotalReason,
    TimingReason,
    WindChillReason,
)

type Floats = npt.NDArray[np.float64]
type Place = tuple[str | None, str | None, str | None]
"""A place's LEAID, county FIPS and NOAA region."""

CLIMATE_PATH: Final = PIPELINE_ROOT / "data" / "predict" / "forecast-climate.json.gz"
SCHEMA_VERSION: Final = 1
CLASSES: Final = ("advisory", "warning", "cold")
"""The serving classes the climate file keeps (:data:`snowlight.predict.exposure.CLASSES`)."""
CODES: Final = 14
"""The forecast history's bucket codes, 0-13 (:class:`snowlight.predict.ndfd.Bucket`)."""
QUIET: Final = 0.1
"""The window snow (inches) a quiet code (under half an inch) stands for in the climate: most
quiet 9 PM forecasts read 0 to a few tenths (Oct 28, 2026: 0.00 at Winthrop, Twisp and
Stehekin, 0.12 at West Yellowstone, 0.31 at East Glacier). Kept at 0.1 by the lead's ruling of
Nov 1, 2026 (PHYS-R3-S2); measuring it on live advisory nights is a POSTLAND item."""
SNOW_CODE: Final = (
    QUIET, 1.2, 3.0, 5.0, 7.5, 11.0, QUIET, QUIET, QUIET, QUIET, QUIET, QUIET, QUIET,
)  # fmt: skip
"""The window snow (inches) each code stands for in the climate: its bucket's middle (0.5-2
1.2; 2-4 3; 4-6 5; 6-9 7.5; 9 or more 11), :data:`QUIET` for a quiet day; a trace of ice or a
cold code ranks under any snow bucket, so its snow is under half an inch, and a tenth of ice or
more (which ranks over all snow) is taken as quiet too: freezing rain days have little snow.
Code 13 (unknown) is never counted."""
COLD_CODES: Final = (9, 10, 11, 12)
"""The cold codes (feels at 7 AM 10 to 0, 0 to -10, -10 to -20, -20 and colder)."""
COLD_FEELS: Final = (math.inf, 5.0, -5.0, -15.0, -27.0)
"""How cold a morning feels at 7 AM (F) in the climate: not cold (no cold term), then each cold
code's middle."""
ICE_CODE: Final = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.05, 0.15, 0.3, 0.0, 0.0, 0.0, 0.0)
"""The window ice (inches) each code stands for."""
SEASON_DAYS: Final = (
    date(2025, 11, 14), date(2025, 12, 15), date(2026, 1, 14), date(2026, 2, 13), date(2026, 3, 16),
)  # fmt: skip
"""School days through a winter, for each zone's share of the window still to come at 9 PM
(:func:`window_scale`): daylight time in November and March, standard time between."""
WINDOWS: Final = ("whole", "still_to_come")
"""How a climate's codes counted the window period under way at 9 PM: whole (the history before
SF-R5-1 was fixed) or for its part still to come (:func:`snowlight.predict.ndfd.
window_total` since)."""
SOLVED: Final = 1e-6
"""How near its class level a place's adjusted days must average for its usual snow to count."""


class Term(StrEnum):
    """The adjustment's terms, in the order lines are given at equal points."""

    SNOW = "snow"
    TIMING = "timing"
    ICE = "ice"
    COLD = "cold"


@dataclass(frozen=True, slots=True)
class AdjustSettings:
    """``live_score.forecast_adjustment`` (registered; S7 addendum i)."""

    classes: tuple[str, ...]
    snow_per_log: float
    snow_offset: float
    bounds: Mapping[str, tuple[float, float]]
    ice_snow: float
    chill_from: float
    chill_per_degree: float
    chill_max: float
    timing_outside: float
    timing_max: float
    timing_min_snow: float
    timing_even_max: float
    shrink_days: float
    county_min_days: int
    usual_max: float
    snow_amount: bool = False
    """The snow amount term (predict-next SNOW-AMOUNT): the total is never under the snow
    alone's floor (:func:`floor_lift`) and over the class's upper bound it bends toward
    ``snow_amount_high`` (:func:`saturated`) instead of stopping. Off: L5 as registered."""
    snow_amount_high: float = math.inf
    """The upper asymptote of the total (log-odds) with ``snow_amount`` on: over the class's
    upper bound the total bends toward it (:func:`saturated`), never reaching it."""
    snow_amount_floor_ratio: float = math.inf
    """With ``snow_amount`` on, the snow alone's floor is anchored at no less than the usual
    over this (:func:`floor_lift`), so the solve for the usual stays determinate."""
    snow_amount_slopes: Mapping[str, float] = field(default_factory=dict)
    """With ``snow_amount`` on, each class's ``a`` (``snow_amount_slope_<class>``) in place of
    ``snow_per_log``, for the solve and serving alike (:meth:`for_class`)."""
    timing_bus: bool = False
    """The bus hour timing term (predict-next BUS-TIMING): the timing weighs snow before the
    bus hour (07:00 on the school's clock) against snow after it (:func:`bus_weight`,
    :func:`weighed`), in place of L5's 10 PM to 9 AM weighting. Off: L5's timing exactly."""
    timing_after_bus: float = 1.0
    """With ``timing_bus`` on, what snow after the bus hour weighs against snow before it
    (``o``; 1: no timing, the term is 0 everywhere and every even factor 1)."""
    timing_bus_share_max: float = 0.8
    """With ``timing_bus`` on, the window's before-bus share is taken at most this in its even
    weight (``F``, :func:`window_even`): snow at least this share before the bus hour never
    lowers."""

    def for_class(self, klass: str) -> "AdjustSettings":
        """The settings a day of ``klass`` is adjusted (and its usual solved) by: with
        ``snow_amount`` on, the class's own slope as ``snow_per_log``; else these."""
        if not self.snow_amount or klass not in self.snow_amount_slopes:
            return self
        return replace(self, snow_per_log=self.snow_amount_slopes[klass])

    @classmethod
    def of(cls, config: PredictConfig) -> "AdjustSettings":
        """The registered settings.

        Raises:
            KeyError: one is missing.
            ValueError: one is out of range.
        """
        block = config.live_score["forecast_adjustment"]

        def number(key: str) -> float:
            value = block[key]
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValueError(f"forecast_adjustment.{key} is not a number: {value!r}")
            return float(value)

        def numbers(key: str) -> tuple[float, ...]:
            value = block[key]
            if not isinstance(value, list) or not all(
                isinstance(item, int | float) and not isinstance(item, bool) for item in value
            ):
                raise ValueError(f"forecast_adjustment.{key} is not a list of numbers: {value!r}")
            return tuple(float(item) for item in value)

        classes = block["classes"]
        if not isinstance(classes, list) or not all(item in CLASSES for item in classes):
            raise ValueError(f"forecast_adjustment.classes are not serving classes: {classes!r}")
        bounds: dict[str, tuple[float, float]] = {}
        for klass in classes:
            low, high = numbers(f"bounds_{klass}")
            if not low <= 0 <= high:
                raise ValueError(f"forecast_adjustment.bounds_{klass} must hold 0")
            bounds[str(klass)] = (low, high)
        found = cls(
            classes=tuple(str(item) for item in classes),
            snow_per_log=number("snow_per_log"),
            snow_offset=number("snow_offset"),
            bounds=bounds,
            ice_snow=number("ice_snow"),
            chill_from=number("chill_from"),
            chill_per_degree=number("chill_per_degree"),
            chill_max=number("chill_max"),
            timing_outside=number("timing_outside"),
            timing_max=number("timing_max"),
            timing_min_snow=number("timing_min_snow"),
            timing_even_max=number("timing_even_max"),
            shrink_days=number("shrink_days"),
            county_min_days=int(number("county_min_days")),
            usual_max=number("usual_max"),
            snow_amount=_flag(block, "snow_amount"),
            snow_amount_high=number("snow_amount_high"),
            snow_amount_floor_ratio=number("snow_amount_floor_ratio"),
            snow_amount_slopes={
                str(klass): number(f"snow_amount_slope_{klass}")
                for klass in classes
                if klass != "cold"
            },
            timing_bus=_flag(block, "timing_bus"),
            timing_after_bus=number("timing_after_bus"),
            timing_bus_share_max=number("timing_bus_share_max"),
        )
        if not found.snow_amount_high > max(high for _, high in found.bounds.values()):
            raise ValueError(
                "forecast_adjustment: snow_amount_high must be over every class's upper bound"
            )
        if not found.snow_amount_floor_ratio >= 1:
            raise ValueError("forecast_adjustment: snow_amount_floor_ratio must be 1 or more")
        if found.ice_snow < 0 or found.chill_max < 0 or found.chill_per_degree < 0:
            raise ValueError("forecast_adjustment: ice and cold only add")
        if (
            not 0 <= found.timing_outside <= 1
            or not found.timing_outside < found.timing_even_max <= 1
            or found.snow_offset <= 0
        ):
            raise ValueError("forecast_adjustment: timing_outside or snow_offset out of range")
        if not 0 <= found.timing_after_bus <= 1:
            raise ValueError("forecast_adjustment: timing_after_bus must be in [0, 1]")
        if not 0 < found.timing_bus_share_max <= 1:
            raise ValueError("forecast_adjustment: timing_bus_share_max must be in (0, 1]")
        m, c = found.timing_min_snow, found.snow_offset
        for a in (found.snow_per_log, *found.snow_amount_slopes.values()):
            if a <= 0 or found.timing_max < 0 or (m > 0 and (m + c) * found.timing_max > a * m):
                # The timing band's lower edge, (s + c) exp(-timing_max min(1, s / m) / a) - c,
                # only rises with s while (m + c) timing_max <= a m (:func:`timed`), for every
                # class's slope (snow_amount_slope_<class>).
                raise ValueError(
                    "forecast_adjustment: timing_max is too wide for timing_min_snow"
                    " (snow_per_log, snow_amount_slope)"
                )
        return found


def _flag(block: Mapping[str, object], key: str) -> bool:
    value = block[key]
    if not isinstance(value, bool):
        raise ValueError(f"forecast_adjustment.{key} is not true or false: {value!r}")
    return value


# --- the climate --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Climate:
    """The forecast climate file, read: per class, the 9 PM forecast codes of each place's days
    of that class (counts of codes 0-12)."""

    seasons: tuple[str, ...]
    window: str
    """How its codes counted the window period under way at 9 PM (:data:`WINDOWS`)."""
    districts: Mapping[str, Mapping[str, tuple[int, ...]]]
    counties: Mapping[str, Mapping[str, tuple[int, ...]]]
    regions: Mapping[str, Mapping[str, tuple[int, ...]]]

    def scale(self, zone: str) -> float:
        """The factor taking its amounts to the window as read now (SF-R5-1): the zone's
        :func:`window_scale` where its codes counted the period under way whole, else 1."""
        return window_scale(zone) if self.window == "whole" else 1.0

    def counts(self, klass: str, place: Place, settings: AdjustSettings) -> Floats:
        """A place's days of ``klass`` by code (0-12), with ``shrink_days`` days of its
        county's mix (its region's where the county holds fewer than ``county_min_days`` days)
        added in proportion; all zeros where nothing is known: a place with no region of its
        own in the climate (Alaska and Hawaii hold none) never borrows the nation's (S-R2-1),
        so its days keep their class level. ``place``: its LEAID, county FIPS and NOAA region,
        each ``None`` where not known (a private school has no LEAID)."""
        leaid, county, region_name = place
        own = np.zeros(CODES - 1)
        if leaid is not None and klass in self.districts.get(leaid, {}):
            own = np.array(self.districts[leaid][klass], dtype=np.float64)
        pool = np.zeros(CODES - 1)
        if county is not None and klass in self.counties.get(county, {}):
            pool = np.array(self.counties[county][klass], dtype=np.float64)
        region = self.regions.get(region_name or "", {})
        if pool.sum() < settings.county_min_days and klass in region:
            pool = np.array(region[klass], dtype=np.float64)
        if pool.sum() <= 0:
            return own
        return own + settings.shrink_days * pool / pool.sum()


def _codes(value: object) -> tuple[int, ...]:
    if (
        not isinstance(value, list)
        or len(value) != CODES - 1
        or not all(isinstance(item, int) and item >= 0 for item in value)
    ):
        raise ValueError(f"a code count is {CODES - 1} counts, not {value!r}")
    return tuple(value)


def _by_class(value: object) -> dict[str, tuple[int, ...]]:
    if not isinstance(value, dict) or not set(value) <= set(CLASSES):
        raise ValueError(f"code counts are by class, not {value!r}")
    return {str(k): _codes(v) for k, v in value.items()}


def load(path: Path = CLIMATE_PATH) -> Climate:
    """Read the climate file.

    Raises:
        OSError: it cannot be read.
        ValueError: it is not one.
    """
    return parse(json.loads(gzip.decompress(path.read_bytes())), path.name)


def parse(body: object, name: str = "forecast-climate") -> Climate:
    """A climate file's body (:func:`build`), read.

    Raises:
        ValueError: it is not one.
    """
    if not isinstance(body, dict) or body.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"{name}: not a forecast climate file of schema {SCHEMA_VERSION}")
    window = body.get("window")
    if window not in WINDOWS:
        # A file that does not say how its codes counted the period under way could be scaled
        # twice (or not at all): refused, its days keep their class levels.
        raise ValueError(f"{name}: its window is {window!r}, not one of {', '.join(WINDOWS)}")
    try:
        return Climate(
            seasons=tuple(str(item) for item in body["seasons"]),
            window=str(window),
            districts={str(k): _by_class(v) for k, v in body["districts"].items()},
            counties={str(k): _by_class(v) for k, v in body["counties"].items()},
            regions={str(k): _by_class(v) for k, v in body["regions"].items()},
        )
    except KeyError as error:
        raise ValueError(f"{name}: no {error}") from error


SERVING_CLASS: Final[Mapping[int, str]] = {
    1: "advisory", 3: "cold", 4: "warning", 5: "warning", 6: "warning", 7: "warning",
}  # fmt: skip
"""The serving class of each weather history class (as :data:`snowlight.predict.exposure.
CLASS_OF_WEATHER`), less tropical storm and hurricane warning days (2): their hazard is not the
snow, so they are never adjusted (``skip``) and never in a climate."""
SKIP: Final = frozenset({"tropical", "blizzard"})
"""The situations a class keeps at its level: a tropical storm or hurricane warning day (its
hazard is not the snow: :data:`SERVING_CLASS`) and a blizzard warning day (its wind is the
hazard as much as the new snow, and wind is not a term: a ground blizzard with little new snow
is never lowered; and the class's climate does not tell blizzard days apart, so raising them
without ever lowering would put their days about 6 points over their level, 52% for 46%)."""
SAMPLE: Final = 13
"""The forecast history's 9 PM sample, the class snapshot."""


def build(
    codes: pl.DataFrame,
    weather: pl.DataFrame,
    districts: pl.DataFrame,
    seasons: Sequence[str],
    window: str,
) -> dict[str, object]:
    """The climate file's body from the forecast history's codes (``district``, ``night``,
    ``sample``, ``code_filled``), the weather history (``district``, ``day``, ``weather``) and
    the districts (``district``, ``state``, ``county``): per district, county and NOAA region,
    the 9 PM codes of its days of each class (code 13, unknown, left out). ``window``: how the
    codes counted the period under way at 9 PM (:data:`WINDOWS`).

    Raises:
        ValueError: ``window`` is not one.
    """
    if window not in WINDOWS:
        raise ValueError(f"the window is {window!r}, not one of {', '.join(WINDOWS)}")
    nine = codes.filter(pl.col("sample") == SAMPLE).select(
        "district", pl.col("night").alias("day"), pl.col("code_filled").alias("code")
    )
    days = weather.with_columns(
        pl.col("weather").replace_strict(SERVING_CLASS, default=None).alias("class")
    ).filter(pl.col("class").is_not_null())
    joined = (
        days.join(nine, on=["district", "day"], how="inner")
        .filter(pl.col("code") < CODES - 1)
        .join(districts.select("district", "state", "county"), on="district", how="left")
        .with_columns(pl.col("state").replace_strict(dict(REGION_OF), default=None).alias("region"))
    )

    def counted(key: str) -> dict[str, dict[str, list[int]]]:
        found: dict[str, dict[str, list[int]]] = {}
        grouped = joined.filter(pl.col(key).is_not_null()).group_by(key, "class", "code").len()
        for place, klass, code, count in grouped.sort(key, "class", "code").iter_rows():
            row = found.setdefault(str(place), {}).setdefault(str(klass), [0] * (CODES - 1))
            row[int(code)] = int(count)
        return found

    return {
        "schema_version": SCHEMA_VERSION,
        "sample": SAMPLE,
        "seasons": list(seasons),
        "window": window,
        "classes": list(CLASSES),
        "districts": counted("district"),
        "counties": counted("county"),
        "regions": counted("region"),
    }


# --- the terms ----------------------------------------------------------------------------------


def window_scale(zone: str) -> float:
    """The share of a 9 PM read's window snow that the fixed window (SF-R5-1) counts against
    what a history that counted each period not over at 9 PM whole counted: each period's snow
    taken as even through its 6 hours, and the window's as even through its periods, at 9 PM
    the evening before each of :data:`SEASON_DAYS` (daylight time in November and March;
    Hawaii's and Alaska's 9 PM fall in or after the first period), averaged."""
    shares: list[float] = []
    for day in SEASON_DAYS:
        nine = snapshot(day, zone)
        counted = [end for end in ndfd.window_ends(day) if end > nine]
        if not counted:
            shares.append(1.0)
            continue
        shares.append(sum(ndfd.still_to_come(end, nine) for end in counted) / len(counted))
    return sum(shares) / len(shares)


def snapshot(day: date, zone: str) -> datetime:
    """The class snapshot for school day ``day``: 9 PM the evening before on the school's
    clock (the forecast history's sample 13), in UTC."""
    return datetime.combine(day - timedelta(days=1), time(21), tzinfo=ZoneInfo(zone)).astimezone(
        UTC
    )


def chill_value(feels: float, settings: AdjustSettings) -> float:
    """The cold term of feeling like ``feels`` F at 7 AM."""
    return min(
        settings.chill_max, settings.chill_per_degree * max(0.0, settings.chill_from - feels)
    )


def _log(value: Floats | float) -> Floats:
    found: Floats = np.log(np.asarray(value, dtype=np.float64))
    return found


def snow_term(
    s: Floats | float,
    usual: Floats | float,
    settings: AdjustSettings,
) -> Floats:
    """The snow term of ``s`` inches for a place with usual snow ``usual`` (the amount its
    chance is solved against, its class days' ice counted): ``a ln((s + c) / (u + c))``.

    The round-4 anchor at the snow alone (a flat stretch from the snow alone's usual to
    ``usual`` inside the snow term) is gone: its flat stretch let the ice and timing terms make
    more snow lower the chance (the lead's ruling of Nov 1). With ``snow_amount`` on, the snow
    alone's usual is a floor under the whole total instead (:func:`floor_lift`), which keeps
    the total monotone."""
    a, c = settings.snow_per_log, settings.snow_offset
    s_ = np.maximum(np.asarray(s, dtype=np.float64), 0.0)
    u_ = np.asarray(usual, dtype=np.float64)
    found: Floats = a * (_log(s_ + c) - _log(u_ + c))
    return found


def amount_terms(
    s: Floats | float,
    weighted: Floats | float,
    ice: Floats | float,
    usual: Floats | float,
    settings: AdjustSettings,
) -> tuple[Floats, Floats, Floats]:
    """The snow, timing and ice terms of ``s`` inches of window snow still to come, the same
    snow weighed by its hours (``weighted``: ``s`` where it is even through the window, more
    where it falls into the commute) and ``ice`` inches of ice, for a place with ``usual``
    snow. Snow :func:`snow_term`, timing
    ``a ln((weighted + c) / (s + c))`` and ice ``a ln((weighted + k ice + c) / (weighted +
    c))`` (never below 0): together, with one usual, ``a ln((weighted + k ice + c) / (u +
    c))``, one log of the day's snow weighed by its hours with its ice counted as ``ice_snow``
    inches of snow an inch. Every one of them only raises the chance as it grows (the snow
    term rises with ``s`` faster than the timing term falls), and an ice trace adds a little to
    a dusting's term, never more."""
    a, c = settings.snow_per_log, settings.snow_offset
    s_ = np.asarray(s, dtype=np.float64)
    w_ = np.asarray(weighted, dtype=np.float64)
    e_ = settings.ice_snow * np.asarray(ice, dtype=np.float64)
    snow = snow_term(s_, usual, settings)
    timing = a * (_log(w_ + c) - _log(s_ + c))
    iced = a * (_log(w_ + e_ + c) - _log(w_ + c))
    return snow, timing, iced


def saturated(
    total: Floats | float,
    low: float,
    high: float,
    settings: AdjustSettings | None = None,
    most: Floats | float | None = None,
) -> Floats:
    """The day's total held to the class's bounds ``[low, high]``: clipped; with
    ``snow_amount`` on (predict-next SNOW-AMOUNT), the total is as L5's up to ``high`` and over
    it bends toward ``H`` (``snow_amount_high``) instead of stopping, ``high + (H - high)
    tanh((total - high) / (H - high))``: slope 1 at ``high``, so it is continuous, only rises
    and is never flat at a cap. The lower bound stays hard (a 9 PM read cannot see snow already
    down: PHYS-R3-S2). ``most``: the class order's cap (:func:`order_cap`), the most the total
    may be (never under ``low``). Serving (:func:`bounded`) and the solve
    (:func:`climate_terms`) both hold the total here, so the usual is solved on the curve that
    is served."""
    t = np.asarray(total, dtype=np.float64)
    if settings is None or not settings.snow_amount:
        found: Floats = np.clip(t, low, high)
    else:
        room = settings.snow_amount_high - high
        bent = high + room * np.tanh(np.maximum(t - high, 0.0) / room)
        found = np.where(t > high, bent, np.maximum(t, low))
    if most is not None:
        found = np.minimum(found, np.maximum(most, low))
    return found


def floor_lift(
    total: Floats | float,
    weighted: Floats | float,
    usual: Floats | float,
    alone: Floats | float | None,
    settings: AdjustSettings,
) -> Floats:
    """What the snow alone's floor adds to the day's total (log-odds, 0 or more): with
    ``snow_amount`` on, the total is never under ``min(0, a ln((W + c) / (u_a + c)))``,
    ``W`` the snow weighed by its hours and ``u_a`` the place's usual snow alone (its ice days
    as quiet; ``usual`` where it is not known or over it). So snow from what the snow alone
    makes usual up never lowers a day because the place's days of the class are often icy
    (PHYS-R3-S1 (i)), and since the floor only rises with the snow and the total with the snow,
    the ice and the cold, the larger of them only rises: the round-4 anchor's flat stretch,
    which let more snow lower the chance with ice forecast, is not here. The floor is the snow
    alone's, with no cold: the snow alone's usual is solved with the ice days' mornings taken
    as quiet ones, so a floor with the cold on top would leave a place whose few quiet mornings
    are cold with no usual that balances its days. The floor's anchor is never under ``u / R``
    (``snow_amount_floor_ratio``): where the snow alone's usual is about a quiet day's trace, a
    floor at it would hold every day of the class at its level or over whatever the usual, so
    no usual would balance them and the solve would run to ``usual_max`` with the chance flat
    in the snow (SA-R1-B2); anchored with the usual, the floor falls as the usual rises and the
    solve stays determinate. Off, or with no ``alone``: 0."""
    t = np.asarray(total, dtype=np.float64)
    if not settings.snow_amount or alone is None:
        return np.zeros_like(t)
    a, c = settings.snow_per_log, settings.snow_offset
    u_ = np.asarray(usual, dtype=np.float64)
    b_ = np.asarray(alone, dtype=np.float64)
    b_ = np.where(np.isfinite(b_), b_, u_)
    b_ = np.minimum(np.maximum(b_, u_ / settings.snow_amount_floor_ratio), u_)
    w_ = np.maximum(np.asarray(weighted, dtype=np.float64), 0.0)
    floor = np.minimum(0.0, a * (_log(w_ + c) - _log(b_ + c)))
    found: Floats = np.maximum(floor - t, 0.0)
    return found


_LEFT: Final = 1e-9
"""What :func:`bounded`'s guard leaves alone: float rounding of a sum already at its target."""


def bounded(
    values: Sequence[Floats | float],
    low: float,
    high: float,
    settings: AdjustSettings | None = None,
    most: float | None = None,
) -> list[Floats]:
    """The terms scaled down on the side that passes a bound, so their sum is the total held
    to the bounds (:func:`saturated`: clipped, or with ``snow_amount`` on bending toward its
    asymptote over ``high``; ``most`` the class order's cap)."""
    terms = [np.asarray(value, dtype=np.float64) for value in values]
    up = sum((np.maximum(term, 0.0) for term in terms), np.zeros(np.shape(terms[0])))
    down = sum((np.minimum(term, 0.0) for term in terms), np.zeros(np.shape(terms[0])))
    total = up + down
    target = saturated(total, low, high, settings, most)
    over, under = total > target, total < target
    # Over the target the raising terms are scaled down, to none at the most; where that is
    # not enough (the class order's cap under 0 and under the lowering terms' sum: SA-R2-S4)
    # the lowering terms take the rest, so the sum is always the solve's total.
    deep = over & (target < down)
    with np.errstate(divide="ignore", invalid="ignore"):
        up_scale = np.where(
            over & (up > 0),
            np.clip((target - down) / np.where(up > 0, up, 1), 0.0, 1.0),
            1,
        )
        down_scale = np.where(
            (under | deep) & (down < 0),
            (target - np.where(deep, 0.0, up)) / np.where(down < 0, down, -1),
            1,
        )
    found = [np.where(term > 0, term * up_scale, term * down_scale) for term in terms]
    # The runtime guard: whatever is left (no term on the side to scale: a total of 0 under a
    # cap under 0) goes to the first term (the snow's), so serving's sum and the solve's
    # :func:`saturated` total never differ.
    rest = target - sum(found, np.zeros(np.shape(terms[0])))
    found[0] = found[0] + np.where(np.abs(rest) > _LEFT, rest, 0.0)
    return found


def timed(s: Floats | float, weighted: Floats | float, settings: AdjustSettings) -> Floats:
    """The weighed snow (:func:`weighed`) held to the timing band: a timing term
    ``a ln((weighted + c) / (s + c))`` of at most ``timing_max`` either way, phased in from no
    snow to ``timing_min_snow`` (the band is ``timing_max min(1, s / m)`` wide). Both edges of
    the band only rise with ``s`` (:meth:`AdjustSettings.of` holds the settings to it), so the
    result only rises with ``s`` and with ``weighted``: more snow in any period at any school
    never lowers it (PHYS-R2-B1)."""
    a, c = settings.snow_per_log, settings.snow_offset
    s_ = np.maximum(np.asarray(s, dtype=np.float64), 0.0)
    m = settings.timing_min_snow
    phase = np.ones_like(s_) if m <= 0 else np.minimum(1.0, s_ / m)
    width = settings.timing_max * phase / a
    low = (s_ + c) * np.exp(-width) - c
    high = (s_ + c) * np.exp(width) - c
    found: Floats = np.clip(np.asarray(weighted, dtype=np.float64), low, high)
    return found


def climate_terms(  # noqa: PLR0913, PLR0917 - the places, the class and the settings
    usual: Floats,
    scale: Floats,
    klass: str,
    settings: AdjustSettings,
    even: Floats | None = None,
    alone: Floats | None = None,
    most: Floats | None = None,
) -> Floats:
    """The adjustment of each climate code (0-12) for places with ``usual`` snow, their
    history's amounts scaled by ``scale`` (:meth:`Climate.scale`), on each kind of morning
    (:data:`COLD_STATES`: no cold term, and the four cold codes' feels): (places, 13, 5).
    The history keeps the window's total alone, so its snow is taken as even through the
    window: its timing is the zone's even snow's (``even``, :func:`even_factor`; 1 where the
    window's even weight is under the cap, as in the lower 48), so a zone whose even snow has a
    timing term (PHYS-R2-S2) still averages its class level. ``alone``: each place's snow
    alone's usual (:func:`floor_lift`; ``None``: no floor). ``most``: the most each code's and
    morning's terms may add (places, 13, 5; the class order, :func:`order_cap`). With
    ``snow_amount`` on, the class's own slope (:meth:`AdjustSettings.for_class`), as
    :func:`term_parts` serves it."""
    settings = settings.for_class(klass)
    low, high = settings.bounds[klass]
    snow_in = np.array(SNOW_CODE)[None, :] * scale[:, None]
    ice_in = np.array(ICE_CODE)[None, :] * scale[:, None]
    factor = np.ones_like(scale) if even is None else even
    weighted = timed(snow_in, snow_in * factor[:, None], settings)
    snow, timing, iced = amount_terms(snow_in, weighted, ice_in, usual[:, None], settings)
    cold = np.array([chill_value(feels, settings) for feels in COLD_FEELS])  # (5,)
    total = (snow + timing + iced)[:, :, None] + cold[None, None, :]
    if alone is not None:
        total = total + floor_lift(
            total,
            weighted[:, :, None],
            usual[:, None, None],
            alone[:, None, None],
            settings,
        )
    found: Floats = saturated(total, low, high, settings, most)
    return found


def order_cap(p0: Floats, warning: Sequence[Floats]) -> Floats:
    """The most an advisory day's terms may add (log-odds, places by code by morning) so its
    chance is never over the same district's warning day's for the same forecast (PHYS-R3-S1,
    the class order): ``logit(min warning) - logit(p0)``, ``warning`` each warning situation's
    unrounded chance per code and morning (a situation kept at its level: that level)."""
    lowest = np.minimum.reduce([np.asarray(item, dtype=np.float64) for item in warning])
    found: Floats = _logits(lowest) - _logits(p0)[:, None, None]
    return found


def climate_chances(  # noqa: PLR0913, PLR0917 - the levels, the usuals and the settings
    p0: Floats,
    usual: Floats,
    scale: Floats,
    klass: str,
    settings: AdjustSettings,
    even: Floats | None = None,
    alone: Floats | None = None,
) -> Floats:
    """Each place's unrounded chance on each climate code and morning (places, 13, 5): ``p0``
    where it is not adjusted (no usual snow)."""
    has = np.isfinite(usual)
    terms = climate_terms(np.where(has, usual, 0.0), scale, klass, settings, even, alone)
    found: Floats = np.where(
        has[:, None, None],
        1.0 / (1.0 + np.exp(-(_logits(p0)[:, None, None] + terms))),
        p0[:, None, None],
    )
    return found


def cold_mix(counts: Floats) -> Floats:
    """How each code's mornings are cold (places, 13, 5): a cold code's own, a quiet day's none,
    and on a snow or ice day the place's own mix of its quiet and cold mornings (the codes keep a
    morning's feel only where the day has under half an inch of snow and no ice, but a snowy
    morning is as often cold as any other there, and the live cold term counts it)."""
    places = counts.shape[0]
    found = np.zeros((places, CODES - 1, len(COLD_FEELS)))
    found[:, 0, 0] = 1.0
    for state, code in enumerate(COLD_CODES, start=1):
        found[:, code, state] = 1.0
    mornings = counts[:, [0, *COLD_CODES]]
    total = mornings.sum(axis=1, keepdims=True)
    mix = np.where(total > 0, mornings / np.where(total > 0, total, 1.0), 0.0)
    mix[:, 0] = np.where(total[:, 0] > 0, mix[:, 0], 1.0)
    for code in range(1, COLD_CODES[0]):
        found[:, code, :] = mix
    return found


ICE_CODES: Final = (6, 7, 8)
"""The ice codes (a trace, a tenth, a quarter inch or more)."""


def ice_as_quiet(counts: Floats) -> Floats:
    """The code counts with every ice day taken as a quiet one (places by code): the climate of
    the snow alone, for the usual snow a snow line is said against (:func:`_snow_line`)."""
    found = np.array(counts, dtype=np.float64, copy=True)
    found[:, 0] += found[:, list(ICE_CODES)].sum(axis=1)
    found[:, list(ICE_CODES)] = 0.0
    return found


def _shares(counts: Floats) -> tuple[Floats, npt.NDArray[np.bool_]]:
    total = counts.sum(axis=1)
    has = total > 0
    weight = np.where(has[:, None], counts / np.where(has, total, 1.0)[:, None], 0.0)
    return weight[:, :, None] * cold_mix(counts), has


def _logits(p0: Floats) -> Floats:
    q = np.clip(p0, 1e-6, 1 - 1e-6)
    found: Floats = np.log(q / (1 - q))
    return found


def usual_snow(  # noqa: PLR0913 - the levels, the climate and the settings
    p0: Floats,
    counts: Floats,
    scale: Floats,
    klass: str,
    settings: AdjustSettings,
    *,
    even: Floats | None = None,
    alone: Floats | None = None,
    most: Floats | None = None,
) -> Floats:
    """Each place's usual snow ``u`` (inches): the one at which its chance, adjusted over its
    climate's days and mornings (``counts``, places by code, :func:`cold_mix`), averages its
    class level ``p0`` exactly (bisection on ``ln(u + c)`` over ``[0, usual_max]``, from
    ``alone`` up where given: the snow alone's usual, :func:`floor_lift`, which ice days only
    raise). NaN where the place has no climate, or where no ``u`` in the range does (then its
    days keep the class level). ``even``: each place's zone's :func:`even_factor`; ``most``:
    the class order's cap (:func:`order_cap`)."""
    weight, has = _shares(counts)
    z0 = _logits(p0)
    c = settings.snow_offset
    low = np.full(p0.shape, math.log(c))
    if alone is not None:
        low = np.where(np.isfinite(alone), np.log(np.maximum(alone, 0.0) + c), low)
    high = np.full(p0.shape, math.log(settings.usual_max + c))

    def mean(log_u: Floats) -> Floats:
        terms = climate_terms(np.exp(log_u) - c, scale, klass, settings, even, alone, most)
        found: Floats = (weight / (1.0 + np.exp(-(z0[:, None, None] + terms)))).sum(axis=(1, 2))
        return found

    for _ in range(48):  # to 1e-14 of the log range: exact at the published grid
        middle = (low + high) / 2
        above = mean(middle) > p0  # still above the level: more snow is usual
        low = np.where(above, middle, low)
        high = np.where(above, high, middle)
    middle = (low + high) / 2
    usual = np.exp(middle) - c
    # Where no usual snow in the range balances the climate (a place whose days of the class
    # are mostly ice or cold, which only add), nothing can keep its days at its level: no
    # adjustment, its class level alone.
    solved = np.abs(mean(middle) - p0) <= SOLVED
    return np.where(has & solved, np.round(usual, 6), np.nan)


def expected(  # noqa: PLR0913, PLR0917 - the levels, the climate and the published grid
    p0: Floats,
    counts: Floats,
    scale: Floats,
    usual: Floats,
    klass: str,
    settings: AdjustSettings,
    floor: float,
    ceiling: float,
    *,
    even: Floats | None = None,
    alone: Floats | None = None,
    most: Floats | None = None,
) -> Floats:
    """Each place's adjusted chance as published (hundredths, the floor and ceiling), averaged
    over its climate's days and mornings: what its days of the class come to with the
    adjustment, for the plausibility check (G6). ``p0`` where it is not adjusted (no usual
    snow)."""
    weight, has_days = _shares(counts)
    has = has_days & np.isfinite(usual)
    terms = climate_terms(np.where(has, usual, 0.0), scale, klass, settings, even, alone, most)
    shown = np.clip(
        np.round(1.0 / (1.0 + np.exp(-(_logits(p0)[:, None, None] + terms))), 2), floor, ceiling
    )
    found: Floats = np.where(has, (weight * shown).sum(axis=(1, 2)), p0)
    return found


def commute_weight(
    start: datetime, end: datetime, day: date, zone: str, settings: AdjustSettings
) -> float:
    """The weight of snow from ``start`` to ``end`` for school day ``day``: ``outside`` plus the
    rest by its share inside :data:`COMMUTE` (10 PM the evening before to 9 AM on the school's
    clock)."""
    if end <= start:
        return settings.timing_outside
    inside = commute_share(start, end, day, zone)
    return settings.timing_outside + (1 - settings.timing_outside) * inside


def bus_weight(
    start: datetime, end: datetime, day: date, zone: str, settings: AdjustSettings
) -> float:
    """With ``timing_bus`` on, the weight of snow from ``start`` to ``end`` for school day
    ``day``: ``timing_after_bus`` plus the rest by its share before the bus hour (07:00 on the
    school's clock, :func:`~snowlight.predict.forecast_values.bus_share`)."""
    o = settings.timing_after_bus
    return o + (1 - o) * bus_share(start, end, day, zone)


def window_even(
    spans: Sequence[tuple[datetime, datetime]], day: date, zone: str, settings: AdjustSettings
) -> tuple[float, float]:
    """The window's even weight (its periods' :func:`commute_weight` by their hours) and the
    same taken at most ``timing_even_max``: where nearly the whole window is in the commute
    hours (Alaska, Hawaii, the West's 9 PM), snow wholly in them still never lowers. ``(1, 1)``
    with no period.

    With ``timing_bus`` on (BUS-TIMING), the window's before-bus share ``f`` (its periods'
    shares before the bus hour by their hours): ``o + (1 - o) f`` and the same with ``f`` taken
    at most ``timing_bus_share_max`` (``F``), ``o`` ``timing_after_bus``. So snow even through
    the window weighs exactly as itself wherever ``f <= F`` (every lower-48 zone at 9 PM and
    every later snapshot), and snow at least ``F`` before the bus hour never lowers."""
    hours = [(end - start).total_seconds() for start, end in spans]
    if sum(hours) <= 0:
        return 1.0, 1.0
    if settings.timing_bus:
        o, cap = settings.timing_after_bus, settings.timing_bus_share_max
        f = sum(
            bus_share(start, end, day, zone) * h
            for (start, end), h in zip(spans, hours, strict=True)
        ) / sum(hours)
        return o + (1 - o) * f, o + (1 - o) * min(f, cap)
    weights = [commute_weight(start, end, day, zone, settings) for start, end in spans]
    even = sum(w * h for w, h in zip(weights, hours, strict=True)) / sum(hours)
    return even, min(even, settings.timing_even_max)


def even_factor(zone: str, settings: AdjustSettings) -> float:
    """What snow even through the window weighs in ``zone`` against itself: the window's even
    weight over the same taken at the cap (:func:`window_even`), at 9 PM the evening before
    each of :data:`SEASON_DAYS`, averaged. 1 where the window's even weight is under the cap
    (the lower 48's Eastern, Central and Mountain time; with ``timing_bus`` on, every lower-48
    zone); over 1 where the cap holds it (the climate's even snow then has the timing term live
    even snow has: PHYS-R2-S2)."""
    found: list[float] = []
    for day in SEASON_DAYS:
        nine = snapshot(day, zone)
        spans = [(max(end - ndfd.PERIOD, nine), end) for end in ndfd.window_ends(day) if end > nine]
        even, capped = window_even(spans, day, zone, settings)
        found.append(even / capped)
    return sum(found) / len(found)


def weighed(s: float, commute: float, even: float, settings: AdjustSettings) -> float:
    """The window's snow weighed by its hours against the same snow even through the window:
    ``(outside s + (1 - outside) commute) / even``, ``s`` the district's 50% value of the
    schools' window snow and ``commute`` the same of each school's own snow in the commute
    hours (:attr:`~snowlight.predict.forecast_values.DistrictForecast.snow_commute`). Each
    school's snow is weighed before the district's 50% value is taken, so this only rises with
    any school's snow in any period (PHYS-R2-B1); ``s`` where the snow is even through the
    window. With ``timing_bus`` on, ``commute`` is the snow before the bus hour
    (:attr:`~snowlight.predict.forecast_values.DistrictForecast.snow_bus`) and ``outside`` is
    ``timing_after_bus``: ``(o s + (1 - o) snow_bus) / even_bus``."""
    o = settings.timing_after_bus if settings.timing_bus else settings.timing_outside
    return (o * s + (1 - o) * min(max(commute, 0.0), s)) / even


NAMED_SHARE: Final = 0.5
"""A timing line names hours only where the district's 50% values of the window's periods add
up to at least this share of its window snow: where its deciding schools' snow falls at
different hours, no one period stands for them (PHYS-R2-S3)."""
BUS_SIDE: Final = 0.5
"""With ``timing_bus`` on, a timing line that raises names only a period more than this share
before the bus hour, one that lowers only a period more than this share after it (BT-S5)."""


@dataclass(frozen=True, slots=True)
class Terms:
    """A day's terms (log-odds), each only where it applies; the period the timing line names
    and whether it is the heaviest snow's (by the hour)."""

    values: Mapping[Term, float]
    period: SnowPart | None = None
    heaviest: bool = False


def _rate(part: SnowPart) -> float:
    return part.snow / max((part.end - part.start).total_seconds(), 1.0)


def _named(  # noqa: PLR0913, PLR0917 - the periods, the day, the place and the side
    parts: Sequence[SnowPart],
    s: float,
    even: float,
    up: bool,
    day: date,
    zone: str,
    settings: AdjustSettings,
) -> tuple[SnowPart | None, bool]:
    """The period a timing line names, and whether it is the heaviest snow's: the heaviest snow
    by the hour where it is on the term's side of the even weight, else the heaviest on that
    side; ``None`` where no period with snow is on it, or where the periods' 50% values do not
    stand for the window's snow (:data:`NAMED_SHARE`). With ``timing_bus`` on, each period
    weighs :func:`bus_weight`, and a line that raises names only a period more than half before
    the bus hour, one that lowers only a period more than half after it."""
    if sum(part.snow for part in parts) < NAMED_SHARE * s:
        return None, False
    if settings.timing_bus:
        shares = [bus_share(part.start, part.end, day, zone) for part in parts]
        weights = [bus_weight(part.start, part.end, day, zone, settings) for part in parts]
        # A line that raises names a period mostly before the bus hour; one that lowers, after.
        sided = [g > BUS_SIDE if up else g < 1 - BUS_SIDE for g in shares]
    else:
        weights = [commute_weight(part.start, part.end, day, zone, settings) for part in parts]
        sided = [True] * len(parts)
    side = [
        part
        for part, w, ok in zip(parts, weights, sided, strict=True)
        if ok and part.snow > 0 and (w > even if up else w < even)
    ]
    if not side:
        return None, False
    order = {id(part): k for k, part in enumerate(parts)}
    heaviest = max(parts, key=lambda part: (_rate(part), -order[id(part)]))
    named = max(side, key=lambda part: (_rate(part), -order[id(part)]))
    return named, named is heaviest


@dataclass(frozen=True, slots=True)
class TermParts:
    """A day's terms before and after the class's bounds (log-odds, in :class:`Term` order:
    snow, timing, ice, cold), with what they were made of: the window snow still to come, the
    same weighed by its hours, the ice and the bounds used (``high`` already the class order's
    cap where one applies). The frozen record keeps them (:mod:`snowlight.predict.frozen`)."""

    raw: tuple[float, float, float, float]
    bounded: tuple[float, float, float, float]
    snow: float
    weighted: float
    ice: float
    low: float
    high: float
    parts: tuple[SnowPart, ...] = ()
    even: float | None = None


def term_parts(  # noqa: PLR0913, PLR0917 - the forecast, the place, the day and the settings
    forecast: DistrictForecast,
    usual: float,
    klass: str,
    day: date,
    zone: str,
    settings: AdjustSettings,
    alone: float | None = None,
    most: float | None = None,
) -> TermParts | None:
    """The terms :func:`day_terms` adds, before and after the bounds; ``None`` where nothing
    moves the day (as there)."""
    if klass not in settings.classes or not math.isfinite(usual):
        return None
    if forecast.code == ndfd.Bucket.UNKNOWN or forecast.snow is None:
        return None
    # With ``snow_amount`` on, the class's own slope, as the solve has it (:func:`climate_terms`).
    settings = settings.for_class(klass)
    s = max(float(forecast.snow), 0.0)
    parts = tuple(part for part in forecast.snow_parts if part.end > part.start)
    even = None
    weighted = s
    # With ``timing_bus`` on, the snow before the bus hour; else L5's commute snow.
    timing = forecast.snow_bus if settings.timing_bus else forecast.snow_commute
    if parts and timing is not None and s > 0:
        _, even = window_even([(part.start, part.end) for part in parts], day, zone, settings)
        weighted = weighed(s, float(timing), even, settings)
    weighted = float(timed(s, weighted, settings))
    ice = max(float(forecast.ice), 0.0) if forecast.ice is not None else 0.0
    snow_term, timing_term, ice_term = (
        float(term) for term in amount_terms(s, weighted, ice, usual, settings)
    )
    cold = 0.0 if forecast.feels is None else chill_value(float(forecast.feels), settings)
    # With ``snow_amount`` on, the snow alone's floor lifts the snow term (:func:`floor_lift`).
    snow_term += float(
        floor_lift(snow_term + timing_term + ice_term + cold, weighted, usual, alone, settings)
    )
    low, high = settings.bounds[klass]
    raw = (snow_term, timing_term, ice_term, cold)
    # The total held as the solve holds it (:func:`saturated`, :func:`climate_terms`).
    after = tuple(float(term) for term in bounded(list(raw), low, high, settings, most))
    if settings.snow_amount:
        # The upper side bends toward this (:func:`saturated`), never reaching it.
        high = settings.snow_amount_high
    if most is not None:
        high = min(high, max(most, low))
    return TermParts(
        raw=raw,
        bounded=(after[0], after[1], after[2], after[3]),
        snow=s,
        weighted=weighted,
        ice=ice,
        low=low,
        high=high,
        parts=parts,
        even=even,
    )


def day_terms(  # noqa: PLR0913, PLR0917 - the forecast, the place, the day and the settings
    forecast: DistrictForecast,
    usual: float,
    klass: str,
    day: date,
    zone: str,
    settings: AdjustSettings,
    alone: float | None = None,
    most: float | None = None,
    noted: list[TermParts] | None = None,
) -> Terms | None:
    """The terms of a district's forecast on a day of ``klass`` with usual snow ``usual`` (and
    ``alone``, its snow alone's: :func:`floor_lift`; ``most``: the most the terms may add, the
    class order's cap: :func:`order_cap`; ``noted``: where given, the terms before and after
    the bounds are added to it, for the frozen record);
    ``None`` where nothing moves it (no snow read, an unknown code, or not an adjusted
    class). Snow, timing and ice are one log of the day's snow weighed by its hours
    (:func:`weighed`, held to the timing band: :func:`timed`) with its ice
    (:func:`amount_terms`); the cold adds; the sum is bounded per class. So the chance only
    rises with more snow in any period at any deciding school, more ice or more cold. Where no
    period can be named for the timing (:func:`_named`), its part is said with the snow's
    line: the chance is the same."""
    found = term_parts(forecast, usual, klass, day, zone, settings, alone, most)
    if found is None:
        return None
    if noted is not None:
        noted.append(found)
    s, parts, even = found.snow, found.parts, found.even
    snow_term, timing_term, ice_term, cold = found.bounded
    period, heaviest = None, False
    if timing_term != 0 and even is not None:
        period, heaviest = _named(parts, s, even, timing_term > 0, day, zone, settings)
    values: dict[Term, float] = {Term.SNOW: snow_term}
    if period is not None:
        values[Term.TIMING] = timing_term
    else:
        values[Term.SNOW] = snow_term + timing_term
    if ice_term > 0:
        values[Term.ICE] = ice_term
    if cold > 0:
        values[Term.COLD] = cold
    return Terms(values, period, heaviest)


def _logit(p: float) -> float:
    q = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(q / (1 - q))


def snow_range(
    low: float | None, high: float | None, usual: float, more: bool
) -> tuple[float, float] | None:
    """The range a snow line states: the deciding schools' window snow (``low`` to ``high``, as
    read) in whole inches (low down, high up), only where every school's is on the line's side
    of the usual snow (over it for more, under it for less); ``None`` otherwise."""
    if low is None or high is None:
        return None
    if (more and low <= usual) or (not more and high >= usual):
        return None
    return float(math.floor(low + 1e-9)), float(math.ceil(high - 1e-9))


def _overnight(words: tuple[float, float] | None, forecast: DistrictForecast) -> bool:
    if words is None or forecast.snow_night is None:
        return False
    night_low, night_high = forecast.snow_night_low, forecast.snow_night_high
    if night_low is None or night_high is None:
        return False
    low, high = words
    return high > 0 and forecast.snow_night > 0 and low <= night_low and night_high <= high


def _snow_line(
    points: int, forecast: DistrictForecast, usual: float, snow_usual: float
) -> SnowTotalReason:
    """The snow line: its range and how it compares with the usual snow here where every
    deciding school's snow is on the line's side of it, against both ``usual`` (the amount the
    chance is weighed against, its days' ice counted as snow) and ``snow_usual`` (the same with
    their ice days taken as quiet: the snow alone, PHYS-R2-S1), so "less snow than usual" is
    never said where the district's usual includes ice; where the schools' snow lies on both
    sides of either (one school gets more than usual, another less: SF-R4-1), or the snow alone
    has no usual, the range alone, with no comparison (``against: none``), so the line never
    says of the district what one of its deciding schools' forecasts says otherwise."""
    more = points > 0
    bar = (
        (max(usual, snow_usual) if more else min(usual, snow_usual))
        if math.isfinite(snow_usual)
        else math.nan
    )
    words = (
        snow_range(forecast.snow_low, forecast.snow_high, bar, more) if math.isfinite(bar) else None
    )
    against: Literal["here", "none"] = "here"
    if words is None and forecast.snow_low is not None and forecast.snow_high is not None:
        low, high = forecast.snow_low, forecast.snow_high
        words = float(math.floor(low + 1e-9)), float(math.ceil(high - 1e-9))
        against = "none"
    return SnowTotalReason(
        kind="snow_total",
        points=points,
        low=None if words is None else words[0],
        high=None if words is None else words[1],
        overnight=_overnight(words, forecast),
        against=against,
        at=forecast.run_time,
    )


def _line(  # noqa: PLR0913, PLR0917 - the term, its points, the forecast and the usuals
    term: Term,
    points: int,
    forecast: DistrictForecast,
    usual: float,
    snow_usual: float,
    terms: Terms,
) -> ReasonPoints:
    if term == Term.SNOW:
        return _snow_line(points, forecast, usual, snow_usual)
    if term == Term.TIMING:
        assert terms.period is not None  # noqa: S101
        if terms.heaviest:
            return TimingReason(
                kind="timing", points=points, start=terms.period.start, end=terms.period.end
            )
        return SnowHoursReason(
            kind="snow_hours", points=points, start=terms.period.start, end=terms.period.end
        )
    if term == Term.ICE:
        inches = ice_amount(forecast.ice, forecast.ice_low, forecast.ice_high)
        return IceReason(kind="ice", points=points, inches=inches, at=forecast.run_time)
    feels = chill_amount(forecast.feels, forecast.feels_low, forecast.feels_high)
    return WindChillReason(kind="wind_chill", points=points, feels_like=feels, at=forecast.run_time)


_WHOLE: Final = 100


def raw_chance(  # noqa: PLR0913, PLR0917 - the class level, the day and the settings
    p0: float,
    klass: str,
    usual: float,
    forecast: DistrictForecast | None,
    day: date,
    zone: str,
    settings: AdjustSettings,
    alone: float | None = None,
) -> float:
    """A day's chance with the forecast on its class level before it is published (unrounded):
    ``p0`` where no term moves it (for the class order's cap, :func:`order_cap`). ``alone``:
    the usual snow alone (:func:`floor_lift`)."""
    if forecast is None or not math.isfinite(usual):
        return p0
    terms = day_terms(forecast, usual, klass, day, zone, settings, alone)
    if terms is None or not terms.values:
        return p0
    return 1.0 / (1.0 + math.exp(-(_logit(p0) + sum(terms.values.values()))))


def terms_detail(  # noqa: PLR0913, PLR0917 - the class level, the day and the settings
    p0: float,
    klass: str,
    usual: float,
    forecast: DistrictForecast,
    day: date,
    zone: str,
    settings: AdjustSettings,
    cap: float | None = None,
    alone: float | None = None,
) -> tuple[TermParts | None, float | None]:
    """What :func:`adjusted` adds to the class level ``p0``: its terms before and after the
    bounds (:func:`term_parts`), and the chance they give before publishing rounds it
    (``None`` where no term moves it), with the same cap. Read only by the frozen record."""
    most = None if cap is None else _logit(cap) - _logit(p0)
    parts = term_parts(forecast, usual, klass, day, zone, settings, alone, most)
    if parts is None:
        return None, None
    return parts, chance_of(p0, parts)


def chance_of(p0: float, parts: TermParts) -> float:
    """The chance ``parts``' bounded terms give the class level ``p0``, before publishing
    rounds it (as :func:`adjusted`'s)."""
    # :func:`day_terms`'s values add up to the bounded terms, in the same order (the timing
    # term is added to the snow term's either way; an ice or cold term of 0 adds nothing)
    return 1.0 / (1.0 + math.exp(-(_logit(p0) + sum(parts.bounded))))


def adjusted(  # noqa: PLR0913, PLR0917 - the class level, the day and the settings
    p0: float,
    q_rate: float,
    klass: str,
    usual: float,
    forecast: DistrictForecast | None,
    day: date,
    zone: str,
    settings: AdjustSettings,
    floor: float,
    ceiling: float,
    *,
    snow_usual: float | None = None,
    cap: float | None = None,
    noted: list[TermParts] | None = None,
) -> Moved | None:
    """A storm-class day's chance and lines with the forecast on top of its class level ``p0``
    (published; ``q_rate`` the delay rate among days with school), or ``None`` where no term
    moves it by a whole point (then the chance is ``p0``, as with no forecast).
    ``snow_usual``: the district's usual snow alone (its ice days as quiet): the snow line's
    comparison's second bar, and with ``snow_amount`` on the snow alone's floor
    (:func:`floor_lift`), never the round-4 anchor (the lead's ruling of Nov 1,
    :func:`snow_term`'s note); ``usual`` where not given. ``cap``: the chance
    (unrounded) it is never over, the same district's lowest warning chance for the same
    forecast on an advisory day (the class order, :func:`order_cap`). ``noted``: as
    :func:`day_terms`'s."""
    if forecast is None:
        return None
    most = None if cap is None else _logit(cap) - _logit(p0)
    # ``snow_usual`` is the snow line's second bar, and with ``snow_amount`` on the floor of a
    # total that stays monotone (:func:`floor_lift`); never the round-4 anchor (the lead's
    # ruling of Nov 1: the anchor let more snow lower the chance with ice forecast).
    terms = day_terms(forecast, usual, klass, day, zone, settings, snow_usual, most, noted)
    if terms is None or not terms.values:
        return None
    raw = 1.0 / (1.0 + math.exp(-(_logit(p0) + sum(terms.values.values()))))
    shown = min(max(round(raw, 2), floor), ceiling)
    total = round(shown * _WHOLE) - round(p0 * _WHOLE)
    if total == 0:
        return None
    points = whole_points(shapley(p0, terms.values), total)
    order = list(Term)
    lines = [
        _line(term, value, forecast, usual, usual if snow_usual is None else snow_usual, terms)
        for term, value in sorted(points.items(), key=lambda kv: (-abs(kv[1]), order.index(kv[0])))
        if value
    ]
    if not lines:
        return None
    delay = min(round((1 - shown) * q_rate, 2), round(1 - shown, 2))
    return Moved(p_no_school=shown, p_delay=delay, reasons=tuple(lines))


FLOORED: Final[Mapping[str, str]] = {
    "advisory": "advisory",
    "winter_storm_warning": "warning",
    "lake_snow": "warning",
    "ice_storm_warning": "warning",
}
"""The class of each adjusted base's alert (or weather), for the share at its lower bound."""


def at_floor(points: int, shown: float, low: float) -> bool:
    """Whether a day at class level ``points`` shown at ``shown`` sits at the class's lower
    bound ``low`` (log-odds) as published."""
    floor = 1.0 / (1.0 + math.exp(-(_logit(points / _WHOLE) + low)))
    return round(shown * _WHOLE) == round(round(floor, 2) * _WHOLE) and shown < points / _WHOLE


def shift_note(made: PredictionsFile, settings: AdjustSettings | None = None) -> str | None:
    """A pass's note of the adjustment (advisory-sane L5's drift check): per class level's
    alert (or weather), how many district-days the file serves at a class level, how many the
    forecast moved, the mean of the published chance less the class level over them all, so a
    drift of a class off its level shows in every pass's log, and (with ``settings``) the share
    of them at the class's lower bound (PHYS-R3-S2). ``None`` where none is."""
    found: dict[str, list[float]] = {}
    moved: dict[str, int] = {}
    floored: dict[str, int] = {}
    for item in made.districts:
        for forecast in item.days:
            if not isinstance(forecast, Forecast) or forecast.why.base.kind != "class":
                continue
            base = forecast.why.base
            alert = str(base.alert or base.weather or "class")
            found.setdefault(alert, []).append(forecast.p_no_school - base.points / _WHOLE)
            moved[alert] = moved.get(alert, 0) + bool(forecast.why.reasons)
            klass = FLOORED.get(alert)
            if settings is not None and klass is not None and forecast.why.reasons:
                low = settings.bounds.get(klass, (0.0, 0.0))[0]
                hit = at_floor(base.points, forecast.p_no_school, low)
                floored[alert] = floored.get(alert, 0) + hit
    if not found:
        return None

    def said(alert: str, shifts: list[float]) -> str:
        text = (
            f"{alert} {len(shifts):,} days, {moved[alert]:,} moved, "
            f"mean {sum(shifts) / len(shifts):+.4f}"
        )
        if settings is not None and FLOORED.get(alert) in settings.bounds:
            text += f", at the lower bound {floored.get(alert, 0) / len(shifts):.1%}"
        return text

    return "forecast adjustment: " + "; ".join(
        said(alert, shifts) for alert, shifts in sorted(found.items())
    )


def write(body: Mapping[str, object], path: Path = CLIMATE_PATH) -> int:
    """Write the file (gzip, no timestamp, so the same inputs give the same bytes); its size."""
    data = gzip.compress(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode(),
        compresslevel=9,
        mtime=0,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return len(data)
