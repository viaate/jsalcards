"""The night-before states of S7-F (spec-f s. 3 and 5): per district, night and moment, the
class issued and the heads-up as rule D2 has them, the 05:00 record, and the outlook's cases.

Rule D2 makes each history row count on one interval of moments per day
(:meth:`~snowlight.predict.alerts_history.HistoryRow.counting`), so one sweep over the rows
gives every moment of a night at once: the 21 sample hours (08:00 D-1 to 04:00 D, three per
slot, :mod:`snowlight.predict.forecast_history`), the late-in-slot scoring times (19:15, 22:15,
01:15, 04:15, and 10:15, 13:15, 16:15 for the daytime slots) and the 05:00 record (rule D3).
A school's class at a moment is the strongest class that counts then, its heads-up the
strongest heads-up; a district's are those that cover, with themselves or stronger ones, at
least ``covered_share`` of its eligible schools (the class's half rule).

A case (spec-f s. 5) is one district at one sample hour of one school night: the class issued
then (``c0``), the heads-up (``h``), the forecast bucket of the newest NDFD run by then (``f``,
F1's ``code_filled``: 13 when no run counted) and the target, the class of the 05:00 record.
The cases are kept as counts by night, state and cell (:func:`season_cases`), from which the
outlook (:mod:`snowlight.predict.outlook`) is fit and its calibration scored.
"""

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo

import numpy as np
import numpy.typing as npt
import polars as pl

from snowlight.predict.alerts_history import HistoryRow, Reach, days_touched
from snowlight.predict.situations import (
    CLASS_BY_CODE,
    HEADS_UP_BY_CODE,
    MORNING_RECORD,
    HeadsUp,
    WeatherClass,
    Window,
    heads_up_strength,
)

type Int8s = npt.NDArray[np.int8]
type Int64s = npt.NDArray[np.int64]

SAMPLE_COUNT: Final = 21
FIRST_SAMPLE_HOUR: Final = 8
_EPOCH: Final = date(1970, 1, 1)
_FOREVER: Final = np.iinfo(np.int64).max


@dataclass(frozen=True, slots=True)
class Moment:
    """A local clock time of a school night, at which a state is taken."""

    label: str
    """``20:00`` (on D-1 unless ``evening_before`` is false)."""
    clock: time
    evening_before: bool
    sample: int
    """The F1 sample hour whose forecast holds at it (the newest run by the whole hour);
    -1 for the 05:00 record, which needs none."""

    @property
    def slot(self) -> int:
        """Its slot S1-S7 (spec-f s. 5); 0 for the 05:00 record (the morning-of pass)."""
        return 0 if self.sample < 0 else slot_of_clock(self.clock, self.evening_before)

    def at(self, day: date, zone: str) -> datetime:
        """The moment of night ``day`` in ``zone``, as an aware time."""
        on = day - timedelta(days=1) if self.evening_before else day
        return datetime.combine(on, self.clock, tzinfo=ZoneInfo(zone))


def slot_of_clock(clock: time, evening_before: bool) -> int:
    """The slot of a local clock time of the night before D (spec-f s. 5): S1 before 10:30 D-1,
    S2 10:30-13:30, S3 13:30-16:30, S4 16:30-19:30, S5 19:30-22:30, S6 22:30-01:30, S7 01:30-05:00;
    0 from 05:00 D (the morning-of pass, where the outlook is the identity)."""
    minutes = clock.hour * 60 + clock.minute
    if not evening_before:
        if minutes >= MORNING_RECORD.hour * 60:
            return 0
        return 6 if minutes < 90 else 7  # noqa: PLR2004 - 01:30
    edges = (630, 810, 990, 1170, 1350)  # 10:30, 13:30, 16:30, 19:30, 22:30
    return 1 + sum(1 for edge in edges if minutes >= edge)


def slot_at(day: date, zone: str, moment: datetime) -> int:
    """The slot of a pass at ``moment`` for school day ``day`` in ``zone``: S1 for any time
    before 10:30 D-1, 0 from 05:00 D on."""
    local = moment.astimezone(ZoneInfo(zone))
    if local.date() >= day:
        if local.date() > day:
            return 0
        return slot_of_clock(local.time(), evening_before=False)
    if local.date() < day - timedelta(days=1):
        return 1
    return slot_of_clock(local.time(), evening_before=True)


def _sample_moment(index: int) -> Moment:
    hour = FIRST_SAMPLE_HOUR + index
    return Moment(f"{hour % 24:02d}:00", time(hour % 24), hour < 24, index)  # noqa: PLR2004


SAMPLES: Final[tuple[Moment, ...]] = tuple(_sample_moment(index) for index in range(SAMPLE_COUNT))
LATE: Final[tuple[Moment, ...]] = (
    Moment("10:15", time(10, 15), True, 2),
    Moment("13:15", time(13, 15), True, 5),
    Moment("16:15", time(16, 15), True, 8),
    Moment("19:15", time(19, 15), True, 11),
    Moment("22:15", time(22, 15), True, 14),
    Moment("01:15", time(1, 15), False, 17),
    Moment("04:15", time(4, 15), False, 20),
)
"""Late in each slot (spec-f GF1, GF4, GF7): the forecast is the whole hour's (the hourly
history holds no later run), the class and heads-up are exactly as issued by the moment."""
RECORD: Final = Moment("05:00", MORNING_RECORD, False, -1)
MOMENTS: Final[tuple[Moment, ...]] = (*SAMPLES, *LATE, RECORD)
RECORD_INDEX: Final = len(MOMENTS) - 1
INDEX_OF: Final[dict[str, int]] = {moment.label: i for i, moment in enumerate(MOMENTS)}


def moment_seconds(day: date, zone: str, moments: Sequence[Moment] = MOMENTS) -> Int64s:
    """Each moment of night ``day`` in ``zone`` as UTC epoch seconds."""
    return np.array([int(moment.at(day, zone).timestamp()) for moment in moments], dtype=np.int64)


def _seconds(moment: datetime | None) -> int:
    return _FOREVER if moment is None else int(moment.timestamp())


# --- the sweep ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SchoolStates:
    """Per (school, day) with any row counting at any moment: the class and the heads-up
    strength (:func:`~snowlight.predict.situations.heads_up_strength`) at each moment."""

    school: Int64s
    day: npt.NDArray[np.int32]
    """Days since 1970-01-01."""
    weather: Int8s
    """Shape (rows, moments)."""
    heads: Int8s
    rows: int = 0
    rows_unresolved: int = 0


def sweep(
    rows: Iterable[HistoryRow],
    reach: Reach,
    zone_of_school: Sequence[str | None],
    window: Window,
    moments: Sequence[Moment] = MOMENTS,
) -> SchoolStates:
    """Every (school, day) state at every moment under rule D2 (see the module docstring):
    class-making rows set the class, heads-up rows the heads-up; any other code is ignored."""
    zones = np.array([zone or "" for zone in zone_of_school], dtype=object)
    times: dict[tuple[str, date], Int64s] = {}
    schools_out: list[Int64s] = []
    days_out: list[npt.NDArray[np.int32]] = []
    values_out: list[Int8s] = []
    kinds_out: list[npt.NDArray[np.bool_]] = []
    counted = unresolved = 0
    width = len(moments)
    for row in rows:
        weather = CLASS_BY_CODE.get(row.code)
        heads = HEADS_UP_BY_CODE.get(row.code)
        if weather is None and heads is None:
            continue
        counted += 1
        reached = reach.schools(row)
        if reached is None:
            unresolved += 1
            continue
        if not reached.size:
            continue
        value = int(weather) if weather is not None else heads_up_strength(int(heads or 0))
        row_zones = zones[reached]
        for zone in sorted(set(row_zones.tolist()) - {""}):
            group = reached[row_zones == zone]
            for day in days_touched(row, zone):
                found = row.counting(day, zone, window)
                if found is None:
                    continue
                at = times.get((zone, day))
                if at is None:
                    at = times[(zone, day)] = moment_seconds(day, zone, moments)
                low, high = _seconds(found[0]), _seconds(found[1])
                active = (at >= low) & (at < high)
                if not active.any():
                    continue
                schools_out.append(group)
                days_out.append(np.full(group.size, (day - _EPOCH).days, dtype=np.int32))
                values_out.append(
                    np.broadcast_to(np.where(active, value, 0).astype(np.int8), (group.size, width))
                )
                kinds_out.append(np.full(group.size, weather is not None, dtype=np.bool_))
    if not schools_out:
        empty = np.zeros((0, width), dtype=np.int8)
        return SchoolStates(
            np.zeros(0, np.int64), np.zeros(0, np.int32), empty, empty.copy(), counted, unresolved
        )
    school = np.concatenate(schools_out)
    day_array = np.concatenate(days_out)
    values = np.concatenate(values_out)
    is_class = np.concatenate(kinds_out)
    key = school.astype(np.int64) * 100_000 + day_array
    order = np.argsort(key, kind="stable")
    key, school, day_array = key[order], school[order], day_array[order]
    values, is_class = values[order], is_class[order]
    starts = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
    weather_values = np.where(is_class[:, None], values, 0).astype(np.int8)
    heads_values = np.where(is_class[:, None], 0, values).astype(np.int8)
    return SchoolStates(
        school[starts],
        day_array[starts],
        np.maximum.reduceat(weather_values, starts, axis=0),
        np.maximum.reduceat(heads_values, starts, axis=0),
        counted,
        unresolved,
    )


@dataclass(frozen=True, slots=True)
class UnitStates:
    """Per (unit, day) with any state above none: the unit's class and heads-up index at each
    moment, by the covered-share rule."""

    unit: Int64s
    """Index into the units' names."""
    day: npt.NDArray[np.int32]
    weather: Int8s
    heads: Int8s
    """Heads-up index (:class:`~snowlight.predict.situations.HeadsUp`), not strength."""


def _covering(values: Int8s, group: Int64s, groups: int, needed: Int64s, top: int) -> Int8s:
    """Per group, the largest value ``v`` held, with ``v`` or more, by ``needed`` members."""
    found = np.zeros(groups, dtype=np.int8)
    counts = np.bincount(group * (top + 1) + values, minlength=groups * (top + 1)).reshape(
        groups, top + 1
    )
    at_least = np.cumsum(counts[:, ::-1], axis=1)[:, ::-1]
    for value in range(1, top + 1):
        found = np.where(at_least[:, value] >= needed, np.int8(value), found)
    return found


def unit_states(
    states: SchoolStates, unit_of_school: Int64s, eligible: Int64s, share: float
) -> UnitStates:
    """Each unit's states (``unit_of_school``: per directory index, the unit or -1;
    ``eligible``: per unit, its eligible schools)."""
    width = states.weather.shape[1]
    known = (states.school < unit_of_school.size) & (states.school >= 0)
    unit = np.full(states.school.size, -1, dtype=np.int64)
    unit[known] = unit_of_school[states.school[known]]
    keep = unit >= 0
    unit, day = unit[keep], states.day[keep]
    weather, heads = states.weather[keep], states.heads[keep]
    if not unit.size:
        empty = np.zeros((0, width), dtype=np.int8)
        return UnitStates(np.zeros(0, np.int64), np.zeros(0, np.int32), empty, empty.copy())
    key = unit * 100_000 + day
    groups_key, group = np.unique(key, return_inverse=True)
    groups = groups_key.size
    group_unit = groups_key // 100_000
    group_day = (groups_key % 100_000).astype(np.int32)
    needed = np.ceil(share * eligible[group_unit] - 1e-9).astype(np.int64)
    needed = np.maximum(needed, 1)
    top_class = max(WeatherClass)
    top_heads = len(HeadsUp) - 1
    out_weather = np.zeros((groups, width), dtype=np.int8)
    out_heads = np.zeros((groups, width), dtype=np.int8)
    for k in range(width):
        out_weather[:, k] = _covering(weather[:, k], group, groups, needed, int(top_class))
        strength = _covering(heads[:, k], group, groups, needed, top_heads)
        out_heads[:, k] = np.where(strength > 0, len(HeadsUp) - strength, 0)
    busy = (out_weather > 0).any(axis=1) | (out_heads > 0).any(axis=1)
    return UnitStates(group_unit[busy], group_day[busy], out_weather[busy], out_heads[busy])


def states_frame(
    found: UnitStates, names: Sequence[str], moments: Sequence[Moment] = MOMENTS
) -> pl.DataFrame:
    """The unit states as a frame: ``district``, ``day``, then ``w<k>`` and ``h<k>`` per
    moment ``k`` (class value, heads-up index)."""
    columns: dict[str, object] = {
        "district": pl.Series([names[i] for i in found.unit.tolist()], dtype=pl.String),
        "day": pl.Series(found.day, dtype=pl.Int32).cast(pl.Date),
    }
    for k in range(len(moments)):
        columns[f"w{k}"] = pl.Series(found.weather[:, k], dtype=pl.Int8)
    for k in range(len(moments)):
        columns[f"h{k}"] = pl.Series(found.heads[:, k], dtype=pl.Int8)
    return pl.DataFrame(columns)


def record_weather(states: pl.DataFrame) -> pl.DataFrame:
    """The 05:00 record's class of each (district, day) above none: the weather history the
    05:00 labels read (``district``, ``day``, ``weather``; rule D3)."""
    column = f"w{RECORD_INDEX}"
    return (
        states.filter(pl.col(column) > 0)
        .select("district", "day", pl.col(column).alias("weather"))
        .sort("district", "day")
    )


# --- the cases ----------------------------------------------------------------------------------

CASE_KEYS: Final = ("night", "state", "moment", "c0", "h", "f", "target")


def season_cases(
    codes: pl.DataFrame,
    states: pl.DataFrame,
    state_of: pl.DataFrame,
    moments: Sequence[Moment] = MOMENTS,
) -> pl.DataFrame:
    """The cases of one season as counts: ``night``, ``state``, ``moment`` (index into
    ``moments``), ``c0``, ``h``, ``f``, ``target`` and ``n``.

    ``codes`` holds F1's ``district``, ``night``, ``sample`` and ``code`` (the bucket); every
    (district, night) it holds is a night of cases, whose states are none at every moment
    unless ``states`` (:func:`states_frame`) holds them. ``state_of`` gives each district its
    state (``district``, ``state``); a district without one is left out.
    """
    parts: list[pl.DataFrame] = []
    record = f"w{RECORD_INDEX}"
    for k, moment in enumerate(moments):
        if moment.sample < 0:
            continue
        wanted = states.select(
            "district",
            pl.col("day").alias("night"),
            pl.col(f"w{k}").alias("c0"),
            pl.col(f"h{k}").alias("h"),
            pl.col(record).alias("target"),
        )
        part = (
            codes.filter(pl.col("sample") == moment.sample)
            .select("district", "night", pl.col("code").alias("f"))
            .join(wanted, on=["district", "night"], how="left")
            .join(state_of, on="district", how="inner")
            .with_columns(
                pl.col("c0").fill_null(0),
                pl.col("h").fill_null(0),
                pl.col("target").fill_null(0),
                pl.lit(k, dtype=pl.Int8).alias("moment"),
            )
            .group_by(*CASE_KEYS)
            .agg(pl.len().cast(pl.Int64).alias("n"))
        )
        parts.append(part)
    if not parts:
        return pl.DataFrame(
            schema={
                "night": pl.Date, "state": pl.String, "moment": pl.Int8, "c0": pl.Int8,
                "h": pl.Int8, "f": pl.Int8, "target": pl.Int8, "n": pl.Int64,
            }
        )  # fmt: skip
    return pl.concat(parts).sort(*CASE_KEYS)


def day_number(day: date) -> int:
    """Days since 1970-01-01."""
    return (day - _EPOCH).days


def utc_seconds(moment: datetime) -> int:
    """An aware time as UTC epoch seconds."""
    return int(moment.astimezone(UTC).timestamp())


def ceil_share(share: float, total: int) -> int:
    """The members a covered share of ``total`` needs."""
    return max(1, math.ceil(share * total - 1e-9))


def unit_index(
    unit_of_school: Mapping[int, str], names: Sequence[str], size: int
) -> tuple[Int64s, Int64s]:
    """Per directory index (``size`` of them), its unit's position in ``names`` or -1; and per
    unit, its school count."""
    position = {name: i for i, name in enumerate(names)}
    found = np.full(size, -1, dtype=np.int64)
    for school, name in unit_of_school.items():
        if name in position and 0 <= school < size:
            found[school] = position[name]
    counts = np.bincount(found[found >= 0], minlength=len(names)).astype(np.int64)
    return found, counts
