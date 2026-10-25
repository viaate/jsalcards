"""Amounts in NWS winter alert text: snow low to high, ice, wind chill (S7 spec, piece 3).

The same words appear in the IEM product text of past alerts and in a live alert's
``description``: "Total snow accumulations of 6 to 10 inches", "between 4 and 8 inches",
"up to 3 inches", "around a tenth of an inch of ice", "a quarter inch of ice", "wind chills
as low as 25 below zero". :func:`amounts` reads them; only the numbers are kept, never the
text.

These are the fallback for a forecast the grids do not give (addendum 2026-10-24 g): a text
amount is a storm total over the alert's whole span, not the school-day window the grids are
read over, so it makes a level only where it cannot be read two ways: a snow range whose low
and high fall in one bucket (:func:`snow_level`), an ice amount, a wind chill. Anything else
reads as unknown, and an unknown level adds nothing.
"""

import re
from dataclasses import dataclass
from typing import Final

from snowlight.predict import ndfd

_NUMBER: Final = (
    r"(\d+(?:\.\d+)?|one half|one quarter|one tenth|a half|a tenth|a quarter|half|one|two|three|"
    r"four|five|six|seven|eight|nine|ten)"
)
_WORDS: Final = {
    "one": 1.0,
    "two": 2.0,
    "three": 3.0,
    "four": 4.0,
    "five": 5.0,
    "six": 6.0,
    "seven": 7.0,
    "eight": 8.0,
    "nine": 9.0,
    "ten": 10.0,
    "a half": 0.5,
    "half": 0.5,
    "a tenth": 0.1,
    "a quarter": 0.25,
    "one half": 0.5,
    "one quarter": 0.25,
    "one tenth": 0.1,
}
_SNOW_RANGE: Final = re.compile(
    rf"(?:snow|accumulations?)[^.]*?(?:of|between)\s+{_NUMBER}\s+(?:to|and|-)\s+{_NUMBER}\s+inch",
    re.IGNORECASE,
)
_SNOW_UP_TO: Final = re.compile(
    rf"(?:snow|accumulations?)[^.]*?(?:up to|of up to|less than)\s+{_NUMBER}\s+inch", re.IGNORECASE
)
_SNOW_ONE: Final = re.compile(
    rf"(?:snow|accumulations?)[^.]*?(?:of|around|near)\s+{_NUMBER}\s+inch", re.IGNORECASE
)
_ICE: Final = re.compile(
    rf"(?:around|of|near|up to)?\s*{_NUMBER}\s+(?:of an\s+)?inch(?:es)?\s+(?:of\s+)?ice",
    re.IGNORECASE,
)
_ICE_RANGE: Final = re.compile(
    rf"ice accumulations?[^.]*?(?:of|between)\s+{_NUMBER}\s+(?:to|and|-)\s+{_NUMBER}"
    r"\s+(?:of an\s+)?inch",
    re.IGNORECASE,
)
_CHILL: Final = re.compile(
    r"wind chills?[^.]*?(?:as low as|to|of|near|around)\s+(minus\s+)?(\d+)\s*(below|above)?"
    r"(?:\s+zero)?",
    re.IGNORECASE,
)


def _value(text: str) -> float:
    lowered = text.lower()
    return _WORDS[lowered] if lowered in _WORDS else float(lowered)


@dataclass(frozen=True, slots=True)
class Amounts:
    """What an alert's text says (``None`` where it says nothing)."""

    snow_low: float | None = None
    snow_high: float | None = None
    ice: float | None = None
    """Inches of ice, the most it names."""
    wind_chill: int | None = None
    """Degrees F, the coldest it names."""


def amounts(text: str) -> Amounts:
    """The snow range, ice and wind chill an alert's text names."""
    flat = " ".join(text.split())
    snow_low = snow_high = None
    found = _SNOW_RANGE.search(flat)
    if found is not None:
        snow_low, snow_high = sorted((_value(found[1]), _value(found[2])))
    elif (up := _SNOW_UP_TO.search(flat)) is not None:
        snow_low, snow_high = 0.0, _value(up[1])
    elif (one := _SNOW_ONE.search(flat)) is not None:
        snow_low = snow_high = _value(one[1])
    ice = None
    ranged = _ICE_RANGE.search(flat)
    if ranged is not None:
        ice = max(_value(ranged[1]), _value(ranged[2]))
    elif (single := _ICE.search(flat)) is not None:
        ice = _value(single[1])
    chill = None
    for match in _CHILL.finditer(flat):
        degrees = int(match[2])
        below = match[1] is not None or (match[3] or "").lower() == "below"
        value = -degrees if below else degrees
        chill = value if chill is None else min(chill, value)
    return Amounts(snow_low, snow_high, ice, chill)


def snow_level(found: Amounts) -> int:
    """The snow bucket a text range makes a level of: its low's, when its high falls in the
    same bucket; else unknown (-1)."""
    if found.snow_low is None or found.snow_high is None:
        return -1
    low = _bucket(found.snow_low)
    high = _bucket(found.snow_high - 1e-9) if found.snow_high > found.snow_low else low
    return low if low == high else -1


def _bucket(inches: float) -> int:
    level = 0
    for k, start in enumerate(ndfd.SNOW_FROM, start=1):
        if inches >= start:
            level = k
    return level
