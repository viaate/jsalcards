"""The night chart in the serving pass (option (iv), docs/predict.md "The night chart"): when it
reads, what it reads, and the guard that keeps a chart failure from ever touching a chance.

The pass builds its nights before its file (:func:`night_stage`), and hands them to
:func:`snowlight.predict.serve.forecast_file` as data, so no chart code runs inside the file's
making. Three layers keep a failure to the chart:

1. the whole stage, reading included, runs under one guard: a coded failure (a stale or
   unreadable blend, a message off the grid) or any other exception gives no nights, and the
   pass goes on;
2. each district's night is built and checked alone (:func:`guarded_nights`), with the same
   check functions the contract's validators call: a night that raises is dropped, and the
   rest stand;
3. a file-level failure with nights rebuilds the file at the same fit with none
   (:func:`snowlight.predict.cli.fitted`).

Each is reported as ``chart: withheld, <code>`` in the pass's lines and its health, with counts.

The fetch gate (:func:`gate_days`): the pass lists and reads nothing for the chart unless the
chart is not off, some district's night day is a school day of the file with its window open,
and some district has a snow-bearing weather class (an advisory, lake effect snow, a winter
storm warning, ice or a blizzard) that day. So a calm night, a Friday night and July cost no
request.
"""

import re
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Final

import numpy as np
import numpy.typing as npt
from pydantic import ValidationError

from snowlight.predict import nbm, ndfd, night_chart
from snowlight.predict.calendar import is_school_day
from snowlight.predict.night_chart import NightInputs
from snowlight.predict.situations import WeatherClass
from snowlight.schemas.predictions import (
    NIGHT_MIN_INCHES,
    NightSnow,
    check_night,
    night_day,
    night_open,
    night_window,
)

SNOW_BEARING: Final = frozenset(
    {
        WeatherClass.ADVISORY,
        WeatherClass.LAKE_SNOW,
        WeatherClass.SNOW_WARNING,
        WeatherClass.ICE,
        WeatherClass.BLIZZARD,
    }
)
"""The weather classes that say snow is forecast (not none, tropical or cold)."""
_HOUR: Final = timedelta(hours=1)
_CHECK: Final = re.compile(r"night: (\w+)")


@dataclass(frozen=True, slots=True)
class Nights:
    """The nights a file carries: by (day, district index), and the one cycle they are from."""

    kept: Mapping[tuple[date, int], NightSnow] = field(default_factory=dict)
    at: datetime | None = None

    def get(self, day: date, index: int) -> NightSnow | None:
        """The district's night on ``day``, or None."""
        return self.kept.get((day, index))

    def __len__(self) -> int:
        return len(self.kept)


NO_NIGHTS: Final = Nights()


@dataclass(frozen=True, slots=True)
class Withheld:
    """Why the chart, or some of its nights, is not in the file: each code with its count
    (``invalid (least_falls)``: 3 districts)."""

    codes: tuple[tuple[str, int], ...] = ()

    @staticmethod
    def of(code: str, count: int = 1) -> "Withheld":
        """One code."""
        return Withheld(((code, count),))

    @staticmethod
    def invalid(check: str, count: int = 1) -> "Withheld":
        """A night or the file failed ``check`` (a check's name or an exception's type)."""
        return Withheld.of(f"invalid ({check})", count)

    @staticmethod
    def invalid_counts(dropped: Mapping[str, int]) -> "Withheld":
        """Each check that dropped nights, with how many."""
        return Withheld(tuple((f"invalid ({check})", n) for check, n in sorted(dropped.items())))

    def __add__(self, other: "Withheld") -> "Withheld":
        return Withheld(self.codes + other.codes)

    def line(self) -> str | None:
        """``chart: withheld, nbm_stale``; with counts past one district (``x3``); None when
        nothing was withheld."""
        if not self.codes:
            return None
        parts = [code if n <= 1 else f"{code} x{n}" for code, n in self.codes]
        return f"chart: withheld, {'; '.join(parts)}"


class ChartWithheld(Exception):  # noqa: N818 - a reason, not an error of the pass
    """The chart stage stops with a code (``nbm_stale``, ``nbm_unreadable``, ``grid``)."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code


def check_name(error: BaseException) -> str:
    """The check a failure names (``least_falls``, from ``night: least_falls``), else its type."""
    text = str(error)
    if isinstance(error, ValidationError | ValueError):
        found = _CHECK.search(text)
        if found is not None:
            return found.group(1)
    return type(error).__name__


@dataclass(frozen=True, slots=True)
class Candidate:
    """A district whose night is open at the pass, on a school day of the file."""

    day: date
    index: int
    inputs: NightInputs


@dataclass(frozen=True, slots=True)
class NightValues:
    """What the stage read: the cycle, and every candidate district's inputs."""

    at: datetime
    candidates: tuple[Candidate, ...]


type Build = Callable[[NightInputs], NightSnow | None]


def guarded_nights(
    values: NightValues,
    generated: datetime,
    *,
    build: Build | None = None,
    min_inches: float = NIGHT_MIN_INCHES,
) -> tuple[Nights, Withheld]:
    """Each candidate's night, built and checked alone: one that raises (a bug, or a failed
    check) is dropped and counted by its check's name, and the rest stand."""
    make = build if build is not None else (lambda i: night_chart.night(i, min_inches))
    kept: dict[tuple[date, int], NightSnow] = {}
    dropped: Counter[str] = Counter()
    for candidate in values.candidates:
        try:
            night = make(candidate.inputs)
            if night is None:
                continue
            night = NightSnow.model_validate(night)
            check_night(night, candidate.day, candidate.inputs.zone, generated)
        except Exception as error:  # this district's chart only, never the file
            dropped[check_name(error)] += 1
            continue
        kept[(candidate.day, candidate.index)] = night
    return Nights(kept, values.at if kept else None), Withheld.invalid_counts(dropped)


def open_districts(
    zones: Sequence[str], days: Sequence[date], now: datetime
) -> Iterator[tuple[int, date]]:
    """Each district whose night is open at ``now`` on a school day of the file, with that day."""
    known = set(days)
    by_zone: dict[str, date | None] = {}
    for zone in set(zones):
        day = night_day(now, zone)
        by_zone[zone] = (
            day if night_open(now, zone) and day in known and is_school_day(day) else None
        )
    for index, zone in enumerate(zones):
        found = by_zone[zone]
        if found is not None:
            yield index, found


def gate_days(
    zones: Sequence[str],
    days: Sequence[date],
    classes: npt.NDArray[np.int64],
    now: datetime,
    charting: npt.NDArray[np.bool_] | None = None,
) -> frozenset[date]:
    """The night days the chart may read for (:func:`open_districts`'s days on which some
    district has a snow-bearing class); empty: the gate is shut and nothing is read. Only the
    districts that can chart count (``charting``: every deciding school on the blend's grid;
    None: all), so an advisory in Alaska alone never opens it."""
    can = np.ones(len(zones), dtype=np.bool_) if charting is None else charting
    opened = {day for index, day in open_districts(zones, days, now) if can[index]}
    snowy = list({int(c) for c in SNOW_BEARING})
    found = set()
    for d, day in enumerate(days):
        if day in opened and np.isin(classes[can, d], snowy).any():
            found.add(day)
    return frozenset(found)


@dataclass(frozen=True, slots=True)
class Points:
    """The deciding schools' points, each with its district's deployed index."""

    lat: npt.NDArray[np.float64]
    lon: npt.NDArray[np.float64]
    district: npt.NDArray[np.int64]


type ReadBlend = Callable[
    [npt.NDArray[np.float64], npt.NDArray[np.float64], set[datetime], datetime, timedelta],
    tuple[datetime, dict[datetime, npt.NDArray[np.float64]]],
]
"""Reads the blend (:meth:`snowlight.predict.nbm.NbmReader.read`)."""


def night_values(  # noqa: PLR0913 - the schools, the zones, the days and the read
    points: Points,
    zones: Sequence[str],
    days: frozenset[date],
    now: datetime,
    *,
    read: ReadBlend,
    max_age: timedelta,
) -> NightValues:
    """Every open district's inputs on the gate's days, from one cycle.

    Raises:
        ChartWithheld: ``nbm_stale``, ``nbm_unreadable`` or ``grid``.
    """
    open_now = [(index, day) for index, day in open_districts(zones, sorted(days), now)]
    open_now = [(index, day) for index, day in open_now if day in days]
    order = np.argsort(points.district, kind="stable")
    found, starts, counts = np.unique(points.district[order], return_index=True, return_counts=True)
    slots = {int(d): (int(s), int(n)) for d, s, n in zip(found, starts, counts, strict=True)}
    windows: dict[str, tuple[datetime, datetime]] = {}
    hours: set[datetime] = set()
    chosen: list[tuple[int, date, npt.NDArray[np.int64]]] = []
    for index, day in open_now:
        slot = slots.get(index)
        if slot is None:
            continue
        zone = zones[index]
        if zone not in windows:
            windows[zone] = night_window(now, zone)
            start, end = windows[zone]
            hour = start
            while hour < end:
                hours.add(hour)
                hour += _HOUR
        chosen.append((index, day, order[slot[0] : slot[0] + slot[1]]))
    if not chosen or not hours:
        raise ChartWithheld("none", "no district's night is open")
    try:
        cycle, by_hour = read(points.lat, points.lon, hours, now, max_age)
    except nbm.NbmError as error:
        raise ChartWithheld(error.code, str(error)) from error
    except ndfd.GridError as error:
        raise ChartWithheld("grid", str(error)) from error
    candidates: list[Candidate] = []
    for index, day, schools in chosen:
        zone = zones[index]
        start, end = windows[zone]
        stack = []
        hour = start
        while hour < end:
            stack.append(by_hour[hour][schools])
            hour += _HOUR
        snow = np.array(stack, dtype=np.float64)
        candidates.append(Candidate(day, index, NightInputs(day, zone, start, end, snow)))
    return NightValues(cycle, tuple(candidates))


type ReadNights = Callable[[frozenset[date]], NightValues]


def night_stage(
    read: ReadNights,
    days: frozenset[date],
    generated: datetime,
    *,
    build: Build | None = None,
    min_inches: float = NIGHT_MIN_INCHES,
) -> tuple[Nights, Withheld]:
    """The pass's nights and what was withheld: layer 1 of the guard, around the reading and
    every night. Never raises for the chart's sake."""
    if not days:
        return NO_NIGHTS, Withheld()
    try:
        values = read(days)
        return guarded_nights(values, generated, build=build, min_inches=min_inches)
    except ChartWithheld as coded:
        if coded.code == "none":
            return NO_NIGHTS, Withheld()
        return NO_NIGHTS, Withheld.of(coded.code)
    except Exception as bug:  # any other failure: no chart, never no file
        return NO_NIGHTS, Withheld.invalid(type(bug).__name__)
