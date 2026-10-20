"""School days, seasons and the days a pass forecasts.

A school day (spec a) is a Monday to Friday from 15 August to 15 June, except
Thanksgiving Thursday and Friday and 24 December to 1 January. Every other day
is published as ``no_threat`` (contract C1): no school, so no chance to give.
"""

from collections.abc import Iterator
from datetime import date, datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

FRIDAY: Final = 4
THURSDAY: Final = 3
NOVEMBER: Final = 11
DECEMBER: Final = 12
JULY: Final = 7
FIRST_DAY: Final = (8, 15)
"""The first school day of a season (month, day)."""
LAST_DAY: Final = (6, 15)
"""The last school day of a season (month, day)."""
_ONE_DAY: Final = timedelta(days=1)


def thanksgiving(year: int) -> date:
    """The fourth Thursday of November."""
    first = date(year, NOVEMBER, 1)
    offset = (THURSDAY - first.weekday()) % 7
    return first + timedelta(days=offset + 21)


def winter_break(day: date) -> bool:
    """Whether ``day`` is in 24 December to 1 January."""
    return (day.month == DECEMBER and day.day >= 24) or (day.month == 1 and day.day == 1)  # noqa: PLR2004


def third_monday(year: int, month: int) -> date:
    """The third Monday of ``month``."""
    first = date(year, month, 1)
    return first + timedelta(days=(-first.weekday()) % 7 + 14)


BREAK_FROM: Final = (12, 18)
BREAK_UNTIL: Final = (1, 3)
"""The span around 24 December to 1 January that many districts also take off."""
FEBRUARY: Final = 2


def likely_break(day: date) -> bool:
    """Whether many districts take ``day`` off though it is a school day here: the Monday to
    Wednesday of Thanksgiving week, 18 December to 3 January, Martin Luther King Jr. Day and
    Presidents' Day. A list that shows nothing then says nothing about the weather, so the
    labels leave these days unknown (the serving pass still gives them a chance)."""
    month_day = (day.month, day.day)
    if month_day >= BREAK_FROM or month_day <= BREAK_UNTIL:
        return True
    feast = thanksgiving(day.year)
    if feast - timedelta(days=3) <= day < feast:
        return True
    return day in (third_monday(day.year, 1), third_monday(day.year, FEBRUARY))


def in_season(day: date) -> bool:
    """Whether ``day`` falls from 15 August to 15 June."""
    month_day = (day.month, day.day)
    return month_day >= FIRST_DAY or month_day <= LAST_DAY


def is_school_day(day: date) -> bool:
    """Whether ``day`` is a school day (see the module docstring)."""
    if day.weekday() > FRIDAY or not in_season(day) or winter_break(day):
        return False
    feast = thanksgiving(day.year)
    return day not in (feast, feast + _ONE_DAY)


def season_of(day: date) -> int:
    """The first calendar year of the July-to-June season ``day`` is in (2024 for 2024-25)."""
    return day.year if day.month >= JULY else day.year - 1


def season_label(season: int) -> str:
    """``2024-25`` for 2024."""
    return f"{season}-{(season + 1) % 100:02d}"


def school_days(first: date, last: date) -> Iterator[date]:
    """Every school day from ``first`` to ``last``, both included."""
    day = first
    while day <= last:
        if is_school_day(day):
            yield day
        day += _ONE_DAY


def previous_school_day(day: date) -> date:
    """The school day before ``day`` (any day: it walks back past breaks)."""
    before = day - _ONE_DAY
    while not is_school_day(before):
        before -= _ONE_DAY
    return before


def forecast_days(now: datetime, zone: str) -> tuple[date, date]:
    """Today in ``zone`` at ``now`` and the day after (spec d: every contiguous district's
    today is one of them).

    Raises:
        ValueError: ``now`` has no time zone.
    """
    if now.tzinfo is None:
        raise ValueError("now must be an aware time")
    today = now.astimezone(ZoneInfo(zone)).date()
    return today, today + _ONE_DAY
