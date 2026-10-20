"""How a chance adds up, piece 1: the base alone, exact by construction (spec c.2).

``why = {base, reasons: []}`` with ``base.points = round(100 * p_no_school)``, so the base
is the whole chance shown. The base names where the rate comes from:

* the district's own record: ``alert`` with the class's alert kind where the class is
  one VTEC code (``snow_warning`` counts winter storm warnings, ``blizzard`` and ``ice``
  their warnings); ``similar_days`` for the classes that mix codes or have no published
  kind (``none``, ``advisory`` with its freezing rain and lake effect advisories, ``cold``
  with the wind chill warnings before 2024, ``lake_snow``, ``tropical``), so the sentence
  is true of every day it counts; ``day_after`` for the day after a closing;
* the districts around it: ``pooled`` with the level named (up to the whole nation) and
  the same alert kind (or none).

The situation is the one whose rates were published: a situation the nation has too few
labeled days of takes its fallback's rates (:mod:`snowlight.predict.pool`). Its base is
``borrowed``: the sentence says which recorded days the chance is counted over (the
fallback's alert, or the days like this that did not follow a recorded snow day: the day
before is not labeled a closing, which is all the labels say of it), so it is true of
the rate shown and never passes off another weather's days as the day's own.

Every share a base says is true of the recorded days of the place it names: the chain names
a place only when it is (:func:`snowlight.predict.share.says_true`).

The record (own base only) is the district's last labeled days in the same situation
before the day forecast, oldest first, under the base. The forecast's top-level reasons
name the weather of the class: snow, lake snow, blizzard and advisory a winter storm, ice
ice, cold extreme cold, tropical a hurricane, none nothing.
"""

from collections.abc import Sequence
from datetime import date
from typing import Final

from snowlight.predict.artifact import RecordDay
from snowlight.predict.pool import SCOPES, Scope
from snowlight.predict.situations import Situation, WeatherClass
from snowlight.schemas.predictions import (
    MAX_RECORD_DAYS,
    AlertBase,
    AlertKind,
    Base,
    DayAfterBase,
    PastDay,
    PastRecord,
    PooledBase,
    SimilarDaysBase,
    Why,
)
from snowlight.schemas.vocab import Reason, Status

ALERT_KIND: Final[dict[WeatherClass, AlertKind]] = {
    WeatherClass.SNOW_WARNING: "winter_storm_warning",
    WeatherClass.BLIZZARD: "blizzard_warning",
    WeatherClass.ICE: "ice_storm_warning",
}
"""The alert a class's base is counted over, for the classes of one VTEC code. ``advisory``
(winter weather, freezing rain and lake effect snow advisories) and ``cold`` (extreme cold and,
before 2024, wind chill warnings) mix codes, so their sentence says "days like this"; ``none``,
``lake_snow`` and ``tropical`` have no published kind."""

REASONS: Final[dict[WeatherClass, tuple[Reason, ...]]] = {
    WeatherClass.NONE: (),
    WeatherClass.ADVISORY: (Reason.WINTER_STORM,),
    WeatherClass.TROPICAL: (Reason.HURRICANE,),
    WeatherClass.COLD: (Reason.EXTREME_COLD,),
    WeatherClass.LAKE_SNOW: (Reason.WINTER_STORM,),
    WeatherClass.SNOW_WARNING: (Reason.WINTER_STORM,),
    WeatherClass.ICE: (Reason.ICE,),
    WeatherClass.BLIZZARD: (Reason.WINTER_STORM,),
}
"""The forecast weather each class names, most important first."""

STATUS_OF: Final[dict[str, Status | None]] = {
    "closed": Status.CLOSED,
    "remote": Status.REMOTE,
    "delayed": Status.DELAYED,
    "open": None,
}

_WHOLE: Final = 100


def percent(p_no_school: float) -> int:
    """The chance in whole percent."""
    return round(p_no_school * _WHOLE)


def sayable(day: Situation, counted: Situation) -> bool:
    """Whether a base counted over ``counted`` days can say so truly on a ``day`` day: the
    same situation, a fallback with an alert to name, or the same weather without the day
    after a snow day (said as "days like this that did not follow a recorded snow day")."""
    if counted == day:
        return True
    if counted.after:
        return False
    if counted.weather in ALERT_KIND:
        return True
    return counted.weather == day.weather and day.after


def base_for(  # noqa: PLR0913 - the counted days, the chance, where it comes from
    situation: Situation,
    p_no_school: float,
    own: bool,
    scope: Scope,
    day: Situation | None = None,
    *,
    live: bool = False,
) -> Base:
    """The base of a forecast whose whole chance is ``p_no_school``, counted over
    ``situation`` days, on a day of situation ``day`` (default the same).

    ``live``: the counted days are days the live pipeline read, not the archive's recorded
    days (the situation is re-anchored on them, :mod:`snowlight.predict.learn`).

    Raises:
        ValueError: ``scope`` is not a pooled scope, or the counted days cannot be said
            truly on that day (:func:`sayable`).
    """
    points = percent(p_no_school)
    asked = situation if day is None else day
    if not sayable(asked, situation):
        raise ValueError(f"a {asked.key} day cannot be counted over {situation.key} days")
    borrowed = asked != situation
    alert = ALERT_KIND.get(situation.weather)
    if not own:
        if scope not in SCOPES:
            raise ValueError(f"not a pooled scope: {scope!r}")
        return PooledBase(
            kind="pooled", scope=scope, points=points, alert=alert, borrowed=borrowed, live=live
        )
    if situation.after:
        return DayAfterBase(kind="day_after", points=points, live=live)
    if alert is not None:
        return AlertBase(kind="alert", points=points, alert=alert, borrowed=borrowed, live=live)
    return SimilarDaysBase(kind="similar_days", points=points, borrowed=borrowed, live=live)


def why_for(  # noqa: PLR0913 - as base_for
    situation: Situation,
    p_no_school: float,
    own: bool,
    scope: Scope,
    day: Situation | None = None,
    *,
    live: bool = False,
) -> Why:
    """The base alone: it adds up to the chance exactly."""
    return Why(base=base_for(situation, p_no_school, own, scope, day, live=live), reasons=())


def record_for(days: Sequence[RecordDay], before: date) -> PastRecord | None:
    """The district's record under its own base: its last labeled days before ``before``,
    oldest first (at most :data:`MAX_RECORD_DAYS`), or ``None`` without one."""
    earlier = sorted((item for item in days if item.day < before), key=lambda item: item.day)
    kept = earlier[-MAX_RECORD_DAYS:]
    if not kept:
        return None
    return PastRecord(
        proves="base",
        inches=None,
        days=tuple(PastDay(day=item.day, inches=None, status=STATUS_OF[item.did]) for item in kept),
    )


def reasons_for(weather: WeatherClass) -> tuple[Reason, ...]:
    """The forecast weather of a class."""
    return REASONS[weather]
