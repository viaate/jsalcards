"""A district's forecast values at the class snapshot, as the reasons read them (piece 3).

Read by :mod:`snowlight.predict.forecast_live` from the NDFD runs; kept apart so the serving
pass can name them without importing the reader (which imports the pass).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo

COMMUTE: Final = (time(22, 0), time(9, 0))
"""The hours on the school's clock whose snow is on the roads for the buses: 10 PM the evening
before to 9 AM."""


def commute_share(start: datetime, end: datetime, day: date, zone: str) -> float:
    """The share of ``start`` to ``end`` inside :data:`COMMUTE` for school day ``day`` on
    ``zone``'s clock (0 for an empty span)."""
    length = (end - start).total_seconds()
    if length <= 0:
        return 0.0
    tz = ZoneInfo(zone)
    lo = datetime.combine(day - timedelta(days=1), COMMUTE[0], tzinfo=tz).astimezone(UTC)
    hi = datetime.combine(day, COMMUTE[1], tzinfo=tz).astimezone(UTC)
    return max(0.0, (min(end, hi) - max(start, lo)).total_seconds()) / length


@dataclass(frozen=True, slots=True)
class SnowPart:
    """One window period counted for its part still to come at the snapshot (SF-R5-1): from,
    to, and the district's 50% value of its snow (inches)."""

    start: datetime
    end: datetime
    snow: float


@dataclass(frozen=True, slots=True)
class DistrictForecast:
    """One district's forecast at the snapshot for one school day."""

    code: int
    """The bucket code (0-13), as the history keeps it (``code_filled``): the only thing the
    terms read, as in training."""
    snow_low: float | None = None
    """The deciding schools' lowest window snow (inches, as read: never rounded, so the words
    can check that a range they state holds every school)."""
    snow_high: float | None = None
    """The deciding schools' highest window snow (inches, as read)."""
    snow_night: float | None = None
    """The district's 50% value of the snow in the overnight periods (inches)."""
    snow_night_low: float | None = None
    """The deciding schools' lowest overnight snow (inches, as read), so "overnight" is said
    only where every school's overnight snow is in the line's range."""
    snow_night_high: float | None = None
    """The deciding schools' highest overnight snow (inches, as read)."""
    ice: float | None = None
    """The district's 50% value of the window ice (inches, hundredths)."""
    ice_low: float | None = None
    """The deciding schools' lowest window ice (inches, as read)."""
    ice_high: float | None = None
    """The deciding schools' highest window ice (inches, as read)."""
    feels: int | None = None
    """The district's 50% value of how cold it feels at 7 AM (whole degrees F)."""
    feels_low: float | None = None
    """The coldest a deciding school feels at 7 AM (degrees F, as read; ``None`` when a
    deciding school has no value, so no line states a degree a school was not read at)."""
    feels_high: float | None = None
    """The least cold a deciding school feels at 7 AM (degrees F, as read; ``None`` as for
    ``feels_low``)."""
    run_time: datetime | None = None
    """When the weather service issued the run read."""
    snow: float | None = None
    """The district's 50% value of the window snow still to come (inches, as read): the
    forecast adjustment's amount (:mod:`snowlight.predict.forecast_adjust`)."""
    snow_parts: tuple[SnowPart, ...] = ()
    """Each window period counted, with the district's 50% value of its snow: only to name the
    hours a timing line says (empty where the snow was not read)."""
    snow_commute: float | None = None
    """The district's 50% value, by the same rule as ``snow``, of each deciding school's own
    window snow in the commute hours (:data:`COMMUTE`; a period's snow taken as even through
    it): the adjustment's timing. Never more than ``snow``, and it only grows with any school's
    snow in any period. ``None`` where ``snow`` is."""


@dataclass(frozen=True, slots=True)
class Forecasts:
    """Each deployed district's forecast by day: ``by_day[day][district index]``."""

    by_day: Mapping[date, Mapping[int, DistrictForecast]] = field(default_factory=dict)
    problems: tuple[str, ...] = ()
    """Zones and days that had no usable run, and why (the pass reports them)."""
    unread: Mapping[date, Mapping[str, str]] = field(default_factory=dict)
    """Per day, the zones with no forecast and why: ``stale`` (no run counts: the newest is
    over the maximum age or none is listed) or ``error`` (the listing or a run did not read)."""

    def get(self, day: date, district: int) -> DistrictForecast | None:
        """A district's forecast for ``day``, or ``None`` when none was read."""
        return self.by_day.get(day, {}).get(district)


NO_FORECASTS = Forecasts()
