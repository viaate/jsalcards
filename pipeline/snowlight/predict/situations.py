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


class HeadsUp(IntEnum):
    """A heads-up (S7-F, spec-f s. 2): a watch or a cold advisory, kept beside the class and
    never changing it. Ranked in this order, 1 strongest (what each most often becomes)."""

    NONE = 0
    WINTER_STORM_WATCH = 1
    EXTREME_COLD_WATCH = 2
    COLD_WEATHER_ADVISORY = 3
    HURRICANE_WATCH = 4
    TROPICAL_STORM_WATCH = 5

    @property
    def label(self) -> str:
        """Its name in files and reports (``winter_storm_watch``)."""
        return self.name.lower()


HEADS_UP_BY_CODE: Final[dict[str, HeadsUp]] = {
    "WS.A": HeadsUp.WINTER_STORM_WATCH,
    "BZ.A": HeadsUp.WINTER_STORM_WATCH,
    "LE.A": HeadsUp.WINTER_STORM_WATCH,
    "EC.A": HeadsUp.EXTREME_COLD_WATCH,
    "WC.A": HeadsUp.EXTREME_COLD_WATCH,
    "CW.Y": HeadsUp.COLD_WEATHER_ADVISORY,
    "WC.Y": HeadsUp.COLD_WEATHER_ADVISORY,
    "HU.A": HeadsUp.HURRICANE_WATCH,
    "TR.A": HeadsUp.TROPICAL_STORM_WATCH,
}
"""The VTEC codes of each heads-up, retired codes with the code that replaced them (Blizzard
and Lake Effect Snow Watches folded into the Winter Storm Watch in 2017, the Wind Chill Watch
and Advisory became the Extreme Cold Watch and the Cold Weather Advisory in October 2024). There
is no Ice Storm Watch and no Extreme Cold Advisory. Read by no class: F1 downloads them only."""

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
    withdrawn_at: datetime | None = None
    """When a ``CAN`` or ``UPG`` product took the event back (S7-F rule D2, history only:
    the live memory drops a withdrawn event at once); ``None``: never."""

    @property
    def weather(self) -> WeatherClass | None:
        """The class it makes, or ``None`` for a code that makes none."""
        return CLASS_BY_CODE.get(self.code)

    @property
    def heads_up(self) -> HeadsUp:
        """The heads-up it gives (``NONE`` for every other code)."""
        return HEADS_UP_BY_CODE.get(self.code, HeadsUp.NONE)


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


# --- S7-F: the class as issued, heads-ups and the 05:00 record (spec-f s. 2, 3, 5) ------------

WITHDRAWING: Final = frozenset({"CAN", "UPG"})
"""The final VTEC actions that take an event back (rule D2); expiry is a natural end."""
MORNING_RECORD: Final = time(5)
"""S7-F's class snapshot (rule D3): 05:00 local on D, what the district woke up to."""


def issued_counts(event: Event, day: date, zone: str, window: Window, as_of: datetime) -> bool:
    """Whether ``event`` counts at ``as_of`` under S7-F's one withdrawal rule (D2): issued by
    then and not yet taken back (``issued <= as_of < withdrawn_at``), a span that is not empty
    (``start < end``), and a span that overlaps the day's window. Heads-ups count by the same
    rule (:func:`school_state`). The shipped pass keeps :func:`counts` until S7-F F3 moves the
    live path onto this rule."""
    if event.issued > as_of:
        return False
    if event.withdrawn_at is not None and as_of >= event.withdrawn_at:
        return False
    if event.end is not None and event.start >= event.end:
        return False
    start, end = window.span(day, zone)
    return event.start < end and (event.end is None or event.end > start)


def school_state(
    events: Iterable[Event], day: date, zone: str, window: Window, as_of: datetime
) -> tuple[WeatherClass, HeadsUp]:
    """A school's class and heads-up at ``as_of`` under rule D2 (:func:`issued_counts`): the
    strongest class and the strongest heads-up (lowest rank above ``NONE``) that count."""
    weather = WeatherClass.NONE
    heads = HeadsUp.NONE
    for event in events:
        if not issued_counts(event, day, zone, window, as_of):
            continue
        found = event.weather
        if found is not None and found > weather:
            weather = found
        given = event.heads_up
        if given is not HeadsUp.NONE and (heads is HeadsUp.NONE or given < heads):
            heads = given
    return weather, heads


def heads_up_strength(heads: int) -> int:
    """A heads-up index as a strength (0 none, 5 the winter storm watch), so the covered-share
    rule reads it as it reads a class."""
    return 0 if heads <= 0 else len(HeadsUp) - heads


def district_heads_up(heads: Sequence[HeadsUp], share: float) -> HeadsUp:
    """The strongest heads-up that covers, with itself or a stronger one, ``share`` of the
    schools (``heads`` holds one per eligible school; none gives ``NONE``): the class's rule
    (:func:`district_class`) in the heads-up order."""
    if not heads:
        return HeadsUp.NONE
    needed = share * len(heads)
    for given in sorted(HeadsUp):
        if given is HeadsUp.NONE:
            continue
        if sum(1 for found in heads if found is not HeadsUp.NONE and found <= given) >= needed:
            return given
    return HeadsUp.NONE


def local_moment(day: date, zone: str, clock: time, *, evening_before: bool) -> datetime:
    """``clock`` local in ``zone`` on D-1 (``evening_before``) or on D, as an aware time."""
    on = day - timedelta(days=1) if evening_before else day
    return datetime.combine(on, clock, tzinfo=ZoneInfo(zone))


def morning_record(day: date, zone: str) -> datetime:
    """The 05:00 record's moment for ``day`` in ``zone`` (rule D3)."""
    return local_moment(day, zone, MORNING_RECORD, evening_before=False)
