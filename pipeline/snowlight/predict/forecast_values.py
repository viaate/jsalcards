"""A district's forecast values at the class snapshot, as the reasons read them (piece 3).

Read by :mod:`snowlight.predict.forecast_live` from the NDFD runs; kept apart so the serving
pass can name them without importing the reader (which imports the pass).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime


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
