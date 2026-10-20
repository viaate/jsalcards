"""The weather class of a school day, and the situations the rates are kept for (spec b, c.1).

One function decides the class for both paths, history and live
(:func:`school_class`), from :class:`Event` values: an alert's VTEC code, when its
product was issued, and the span it is in effect. History builds them from the IEM
season files (:mod:`snowlight.predict.alerts_history`), the live pass from the NWS
feed (:mod:`snowlight.predict.alerts_live`).

An event counts for a school on day ``D`` when its area covers the school, its
product was issued at or before the snapshot, and its span overlaps
[``window_from`` on D-1, ``window_until`` on D) in the school's time zone.

Classes, strongest first: ``blizzard`` (BZ.W), ``ice`` (IS.W), ``snow_warning``
(WS.W), ``lake_snow`` (LE.W), ``cold`` (EC.W, WC.W), ``tropical`` (HU.W, TR.W),
``advisory`` (WW.Y, ZR.Y, LE.Y), ``none``. A district's class is the strongest
class ``c`` that covers, with ``c`` or a stronger class, at least ``covered_share``
of its eligible schools (:func:`district_class`).

A situation is a class, with the day after a closing told apart for ``none`` and
``advisory`` only (no warning still in force): ten situations.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import IntEnum
from typing import Final, Literal
from zoneinfo import ZoneInfo


class WeatherClass(IntEnum):
    """A day's weather class; a higher value is stronger."""

    NONE = 0
    ADVISORY = 1
    TROPICAL = 2
    COLD = 3
    LAKE_SNOW = 4
    SNOW_WARNING = 5
    ICE = 6
    BLIZZARD = 7

    @property
    def label(self) -> str:
        """The class's name in files and reports (``snow_warning``)."""
        return self.name.lower()


CLASS_BY_CODE: Final[dict[str, WeatherClass]] = {
    "BZ.W": WeatherClass.BLIZZARD,
    "IS.W": WeatherClass.ICE,
    "WS.W": WeatherClass.SNOW_WARNING,
    "LE.W": WeatherClass.LAKE_SNOW,
    "EC.W": WeatherClass.COLD,
    "WC.W": WeatherClass.COLD,
    "HU.W": WeatherClass.TROPICAL,
    "TR.W": WeatherClass.TROPICAL,
    "WW.Y": WeatherClass.ADVISORY,
    "ZR.Y": WeatherClass.ADVISORY,
    "LE.Y": WeatherClass.ADVISORY,
}
"""The VTEC codes that make a class; every other code (FF.W, watches, CW.Y, WC.Y) is ignored."""

type Group = Literal["none", "advisory", "snow", "severe", "cold", "tropical"]

GROUP_OF: Final[dict[WeatherClass, Group]] = {
    WeatherClass.NONE: "none",
    WeatherClass.ADVISORY: "advisory",
    WeatherClass.SNOW_WARNING: "snow",
    WeatherClass.LAKE_SNOW: "snow",
    WeatherClass.BLIZZARD: "severe",
    WeatherClass.ICE: "severe",
    WeatherClass.COLD: "cold",
    WeatherClass.TROPICAL: "tropical",
}
"""Each class's group, for the shrinkage strengths (spec c.1)."""

GROUPS: Final[tuple[Group, ...]] = ("none", "advisory", "snow", "severe", "cold", "tropical")

AFTER_CLASSES: Final = frozenset({WeatherClass.NONE, WeatherClass.ADVISORY})
"""The classes whose day after a closing is a situation of its own."""


@dataclass(frozen=True, slots=True, order=True)
class Situation:
    """A class, and whether the day before was a closing (for ``none`` and ``advisory``)."""

    weather: WeatherClass
    after: bool = False

    @property
    def key(self) -> str:
        """``snow_warning`` or ``none_after``: the key in the model artifact."""
        return f"{self.weather.label}_after" if self.after else self.weather.label

    @property
    def group(self) -> Group:
        """The class group, for the shrinkage strengths."""
        return GROUP_OF[self.weather]

    @classmethod
    def of(cls, weather: WeatherClass, after: bool) -> "Situation":
        """The situation of a day: ``after`` counts only for ``none`` and ``advisory``."""
        return cls(weather, after and weather in AFTER_CLASSES)

    @classmethod
    def from_key(cls, key: str) -> "Situation":
        """The situation a key names.

        Raises:
            ValueError: the key names none.
        """
        label, after = (key[: -len("_after")], True) if key.endswith("_after") else (key, False)
        try:
            weather = WeatherClass[label.upper()]
        except KeyError as error:
            raise ValueError(f"not a situation: {key!r}") from error
        if after and weather not in AFTER_CLASSES:
            raise ValueError(f"not a situation: {key!r}")
        return cls(weather, after)


SITUATIONS: Final[tuple[Situation, ...]] = tuple(
    sorted(
        [Situation(weather) for weather in WeatherClass]
        + [Situation(weather, after=True) for weather in sorted(AFTER_CLASSES)]
    )
)


@dataclass(frozen=True, slots=True)
class Event:
    """One alert's product for one area: its code, when it was issued, its span in effect."""

    code: str
    issued: datetime
    start: datetime
    end: datetime | None
    """``None``: until further notice."""

    @property
    def weather(self) -> WeatherClass | None:
        """The class it makes, or ``None`` for a code that makes none."""
        return CLASS_BY_CODE.get(self.code)


@dataclass(frozen=True, slots=True)
class Window:
    """The local clock times of a day's weather window and its snapshot (spec b)."""

    window_from: time
    window_until: time
    snapshot_hour: int

    def span(self, day: date, zone: str) -> tuple[datetime, datetime]:
        """[``window_from`` on D-1, ``window_until`` on D) in ``zone``, as aware times."""
        tz = ZoneInfo(zone)
        start = datetime.combine(day - timedelta(days=1), self.window_from, tzinfo=tz)
        end = datetime.combine(day, self.window_until, tzinfo=tz)
        return start, end

    def snapshot(self, day: date, zone: str) -> datetime:
        """The training snapshot: ``snapshot_hour`` on D-1 in ``zone``."""
        return datetime.combine(
            day - timedelta(days=1), time(self.snapshot_hour), tzinfo=ZoneInfo(zone)
        )


def counts(event: Event, day: date, zone: str, window: Window, as_of: datetime) -> bool:
    """Whether ``event`` counts for a school in ``zone`` on ``day``, known at ``as_of``."""
    if event.weather is None or event.issued > as_of:
        return False
    start, end = window.span(day, zone)
    return event.start < end and (event.end is None or event.end > start)


def school_class(
    events: Iterable[Event], day: date, zone: str, window: Window, as_of: datetime
) -> WeatherClass:
    """The strongest class among the events that count (:func:`counts`), or ``NONE``."""
    found = WeatherClass.NONE
    for event in events:
        weather = event.weather
        if weather is not None and weather > found and counts(event, day, zone, window, as_of):
            found = weather
    return found


def district_class(classes: Sequence[WeatherClass], share: float) -> WeatherClass:
    """The strongest class that covers, with itself or a stronger one, ``share`` of the schools.

    ``classes`` holds one class per eligible school; none gives ``NONE``.
    """
    if not classes:
        return WeatherClass.NONE
    needed = share * len(classes)
    for weather in sorted(WeatherClass, reverse=True):
        if weather is WeatherClass.NONE:
            break
        if sum(1 for found in classes if found >= weather) >= needed:
            return weather
    return WeatherClass.NONE


def district_class_from_counts(covered: Sequence[int], total: int, share: float) -> WeatherClass:
    """:func:`district_class` from per-class counts: ``covered[c]`` schools whose own class is
    exactly ``c`` (indexed by :class:`WeatherClass` value), of ``total`` eligible schools."""
    if total <= 0:
        return WeatherClass.NONE
    needed = share * total
    running = 0
    for weather in sorted(WeatherClass, reverse=True):
        if weather is WeatherClass.NONE:
            break
        running += covered[weather] if weather < len(covered) else 0
        if running >= needed:
            return weather
    return WeatherClass.NONE
