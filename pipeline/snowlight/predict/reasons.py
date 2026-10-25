"""A day's reasons: the terms on top of the base, as lines with whole points (S7 spec c.2,
piece 3).

The base (:mod:`snowlight.predict.why`) keeps its whole points. Each term the day has
(:mod:`snowlight.predict.terms`: the forecast's snow, ice and cold, the districts next door)
moves the chance on the log-odds scale; the chance shown is ``sigmoid(logit(p_base) + sum
f)``, rounded and clamped as every published chance is, and the lines share the points between
it and the base by their exact Shapley values (:mod:`snowlight.predict.shapley`).

The levels a day's terms read are exactly the ones training reads (:func:`levels`): the
forecast's bucket code alone (:func:`snowlight.predict.terms.levels_of`, as
:mod:`snowlight.predict.term_rows` reads the history's codes) and the neighbors' share. Nothing
the history does not keep (the schools' lowest and highest amounts) ever decides whether a
term applies, so the rows the backtest scores are the rows a pass moves. The words follow the
code instead, and state an amount only where it is true of every deciding school
(:func:`snow_words`, :func:`ice_amount`, :func:`chill_amount`): a snow line's range is the
code's bucket cut to the schools' lowest and highest amounts in whole inches, said only where
the schools' amounts as read (never rounded) all lie in the bucket, so the range holds every
deciding school's forecast and lies wholly on the side of the band the term's sign says; no
new snow at all reads "no new snow" (0 to 0). Where a school's forecast leaves the bucket the
line drops the amount and says only the comparison ("less snow by 2 PM than most advisory
days"), which the code alone makes true. "Overnight" is said only where every deciding
school's overnight snow lies in the range (:func:`overnight`); otherwise the range is "by" the
window's end. An ice line says the 50% value in tenths, rounded down, and a wind chill line its
whole degrees, each only where every deciding school reads that same amount (a school with no
feel read gives no degrees); otherwise it says the weather without one. Every line from the forecast
carries the run's time (``at``), as the web words it. Dropping an amount never drops a line:
which terms apply and their points are training's, whatever the words.

Which terms a day has follows its own weather, and a snow term also the days its base counts
(:func:`snowlight.predict.terms.has_term`): a lake effect snow, tropical, ice or cold day that
publishes the winter storm warning days' rates never takes their snow term.

The delay chance keeps the base's share of days with school (``q``): ``round((1 - p) * q,
2)``, so the two still sum to at most 1.
"""

import math
from dataclasses import dataclass
from typing import Final

from snowlight.predict import terms as terms_module
from snowlight.predict.forecast_values import DistrictForecast
from snowlight.predict.nowcast import Posted
from snowlight.predict.shapley import shapley, whole_points
from snowlight.predict.situations import WeatherClass
from snowlight.predict.terms import SNOW_EDGES, Levels, Term, levels_of, neighbor_level
from snowlight.schemas.predictions import (
    IceReason,
    NeighborsReason,
    ReasonPoints,
    SnowTotalReason,
    WindChillReason,
)

_WHOLE: Final = 100


@dataclass(frozen=True, slots=True)
class DayInputs:
    """What a pass read for one unit and day: its forecast and its neighbors' posts."""

    forecast: DistrictForecast | None = None
    posted: Posted | None = None


@dataclass(frozen=True, slots=True)
class Moved:
    """The chance with the reasons, and the lines."""

    p_no_school: float
    p_delay: float
    reasons: tuple[ReasonPoints, ...]


def levels(inputs: DayInputs) -> Levels:
    """The term levels a day's inputs give: the forecast code's, as training reads them, and
    the neighbors' share (unknown with no forecast or no closings read)."""
    snow, ice, cold = levels_of(None if inputs.forecast is None else inputs.forecast.code)
    posted = inputs.posted
    near = terms_module.UNKNOWN
    if posted is not None:
        near = neighbor_level(posted.share)
        if near > 0 and not posted.districts:
            near = terms_module.UNKNOWN  # a share with no district named cannot be (training's)
    return Levels(snow=snow, ice=ice, cold=cold, neighbors=near)


SNOW_START: Final = (0.0, *SNOW_EDGES)
"""Where each snow level starts (inches, included); a level ends where the next starts."""


def _bucket(level: int) -> tuple[float, float]:
    start = SNOW_START[level]
    return start, SNOW_START[level + 1] if level + 1 < len(SNOW_START) else math.inf


def _snow_read(level: int, low: float | None, high: float | None) -> bool:
    """Whether the snow values a snow level needs were read (the reader always gives them with
    a code that reads a snow level, so this never drops a term training applies)."""
    if level < 0 or low is None or high is None:
        return False
    start, end = _bucket(level)
    return max(start, math.floor(low + 1e-9)) <= min(end, math.ceil(high - 1e-9))


def snow_words(level: int, low: float | None, high: float | None) -> tuple[float, float] | None:
    """A snow line's range for a district at snow ``level`` whose deciding schools' window
    totals run from ``low`` to ``high`` (inches as read): the level's bucket cut to that range
    in whole inches (the low rounded down, the high up), so it holds every school's amount and
    lies wholly in the bucket. ``None``, and the line says only its comparison, where a school's
    amount leaves the bucket (the bucket is the district's 50% value's, which a school above or
    below it need not share; an amount at the bucket's end is the next bucket's, as the codes
    read it, so 2.0 inches is never "lighter than" advisory days' 2 to 4) or the values are not
    given."""
    if level < 0 or low is None or high is None:
        return None
    start, end = _bucket(level)
    if low < start or high >= end:  # a bucket's end is the next one's start: not in it
        return None
    return max(start, float(math.floor(low + 1e-9))), min(end, float(math.ceil(high - 1e-9)))


def _tenths_down(value: float) -> float:
    return math.floor(value * 10 + 1e-9) / 10


def ice_words(inches: float | None) -> float | None:
    """An ice line's amount: the 50% value in tenths, rounded down, so it never says more ice
    than the forecast has (``None`` where none was read, which the reader never gives with an
    ice code)."""
    return None if inches is None else _tenths_down(inches)


def ice_amount(inches: float | None, low: float | None, high: float | None) -> float | None:
    """The amount an ice line states: the 50% value in tenths, rounded down, only where every
    deciding school's ice (``low`` to ``high``, as read) reads that same tenth; else ``None``
    and the line says the freezing rain without an amount."""
    said = ice_words(inches)
    if said is None or low is None or high is None:
        return None
    return said if _tenths_down(low) == said == _tenths_down(high) else None


def chill_amount(feels: int | None, low: float | None, high: float | None) -> int | None:
    """The temperature a wind chill line states: the 50% value in whole degrees, only where
    every deciding school's feel (``low`` to ``high``, as read) rounds to it; else ``None`` and
    the line says the wind chill without one."""
    if feels is None or low is None or high is None:
        return None
    return feels if round(low) == feels == round(high) else None


def overnight(
    words: tuple[float, float] | None,
    night: float | None,
    night_low: float | None,
    night_high: float | None,
) -> bool:
    """Whether the line may say "overnight": every deciding school's overnight snow (the
    periods ending 06 and 12 UTC, ``night_low`` to ``night_high`` as read) is in the line's
    range, and the district's (its 50% value ``night``) is some snow, so "9 to 11 inches
    overnight" is true of the snow that falls overnight at each school, not only of the
    window's or of the district's 50% value. Otherwise the line says "by" the window's end,
    which its range makes true. Never for a line with no amount: its comparison is of the
    window's snow."""
    if words is None or night is None or night_low is None or night_high is None:
        return False
    low, high = words
    return high > 0 and night > 0 and low <= night_low and night_high <= high


def _line(term: Term, points: int, inputs: DayInputs, level: Levels) -> ReasonPoints:
    found = inputs.forecast
    if term in terms_module.SNOW_TERMS:
        assert found is not None  # noqa: S101
        words = snow_words(level.snow, found.snow_low, found.snow_high)
        return SnowTotalReason(
            kind="snow_total",
            points=points,
            low=None if words is None else words[0],
            high=None if words is None else words[1],
            overnight=overnight(
                words, found.snow_night, found.snow_night_low, found.snow_night_high
            ),
            against="storms" if term == Term.SNOW_STORM else "advisory",
            at=found.run_time,
        )
    if term == Term.ICE:
        assert found is not None  # noqa: S101
        inches = ice_amount(found.ice, found.ice_low, found.ice_high)
        return IceReason(kind="ice", points=points, inches=inches, at=found.run_time)
    if term == Term.COLD:
        assert found is not None  # noqa: S101
        feels = chill_amount(found.feels, found.feels_low, found.feels_high)
        return WindChillReason(
            kind="wind_chill", points=points, feels_like=feels, at=found.run_time
        )
    posted = inputs.posted
    assert posted is not None  # noqa: S101
    return NeighborsReason(
        kind="neighbors", points=points, districts=posted.districts, status=posted.status
    )


def _said(term: Term, inputs: DayInputs, level: Levels) -> bool:
    """Whether a term with a level was read. The reader always gives the amounts with a code
    that reads their level (tested over random runs), so this never drops a term training
    applies; whether a line states its amount is the words' (:func:`snow_words`), never this."""
    found = inputs.forecast
    if term in terms_module.SNOW_TERMS:
        return found is not None and _snow_read(level.snow, found.snow_low, found.snow_high)
    if term == Term.ICE:
        return found is not None and found.ice is not None
    if term == Term.COLD:
        return found is not None and found.feels is not None
    return True


def moved(  # noqa: PLR0913, PLR0917 - the base's chances, the day's weather, the model and the inputs
    p_base: float,
    p_delay: float,
    own: WeatherClass,
    counted: WeatherClass,
    model: terms_module.Model,
    inputs: DayInputs,
    floor: float,
    ceiling: float,
    *,
    q_rate: float | None = None,
) -> Moved | None:
    """The day's chance and lines on top of a published base ``p_base`` (its delay chance
    ``p_delay``, and ``q_rate`` the delay rate among days with school when known) for a day of
    weather ``own`` whose base counts ``counted``'s days, or ``None`` when no term moves it by a
    whole point."""
    level = levels(inputs)
    values = {
        term: value
        for term, value in model.values(own, counted, level).items()
        if _said(term, inputs, level)
    }
    if not values:
        return None
    z = math.log(min(max(p_base, 1e-6), 1 - 1e-6) / (1 - min(max(p_base, 1e-6), 1 - 1e-6)))
    raw = 1.0 / (1.0 + math.exp(-(z + sum(values.values()))))
    shown = min(max(round(raw, 2), floor), ceiling)
    total = round(shown * _WHOLE) - round(p_base * _WHOLE)
    shares = shapley(p_base, values)
    points = whole_points(shares, total)
    lines = [
        _line(term, value, inputs, level)
        for term, value in sorted(points.items(), key=lambda item: (-abs(item[1]), item[0].value))
        if value
    ]
    if not lines:
        return None
    # The delay rate among days with school: unrounded where the pass has it (a published
    # delay of 0.01 at a 99% base would read as a rate of 1), else from the published chances.
    q = q_rate if q_rate is not None else p_delay / (1 - p_base) if p_base < 1 else 0.0
    delay = min(round((1 - shown) * q, 2), round(1 - shown, 2))
    return Moved(p_no_school=shown, p_delay=delay, reasons=tuple(lines))
