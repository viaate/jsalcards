"""The weather class of every school and district on past school days (spec b, history path).

Source: the IEM VTEC season files the weights build caches
(``.cache/weights/mesonet.agron.iastate.edu/watchwarn-csv``, one per school year,
:mod:`snowlight.weights.archive`): one row per event and zone. Each row becomes an
:class:`~snowlight.predict.situations.Event`:

* ``issued``: ``utc_prodissue``, when the product that put the zone in the event was
  issued. A row issued after a day's snapshot (21:00 local on D-1) does not count
  for D: no later product leaks into the past.
* the span: ``[utc_issue, utc_init_expire)``, the first product's window, so a later
  extension does not leak. A row cancelled or upgraded early (its final
  ``utc_expire`` before its first end) ends there for a snapshot made after it.
  Tropical warnings run "until further notice" (no end), ended by the product that
  ended them (:func:`snowlight.weights.archive.close_open_tropical`'s rule for a row
  no product ended).

Each zone row reaches the schools in the polygon of the zone version it was issued
for, school year by school year, as the weights build places them
(:func:`snowlight.weights.schoolzones.place_by_year`): the zones as they stood when
the product was issued. Only the codes of
:data:`~snowlight.predict.situations.CLASS_BY_CODE` are read; zone rows only (the only
county rows in the files are flash flood warnings, which no class reads).
"""

import csv
import io
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

import numpy as np
import numpy.typing as npt
import polars as pl

from snowlight.predict.calendar import is_school_day
from snowlight.predict.situations import (
    CLASS_BY_CODE,
    Event,
    WeatherClass,
    Window,
    school_class,
)
from snowlight.weather.hazards import CONUS_STATES

ENDED: Final = frozenset({"CAN", "EXP", "UPG"})
"""Final VTEC actions that ended a row explicitly."""
TROPICAL: Final = frozenset({"HU.W", "TR.W"})
_ONE_DAY: Final = timedelta(days=1)


class HistoryError(ValueError):
    """A season file cannot be read."""


@dataclass(frozen=True, slots=True)
class HistoryRow:
    """One zone row of a class-making code, as a training event."""

    season: int
    event_key: str
    ugc: str
    area_km2: float | None
    code: str
    issued: datetime
    start: datetime
    end: datetime | None
    final_end: datetime
    """IEM's final ``utc_expire``: when the row really ended."""

    def event(self, as_of: datetime) -> Event:
        """The event as it was known at ``as_of``: ended early only once the ending product
        was out."""
        end = self.end
        if self.final_end <= as_of and (end is None or self.final_end < end):
            end = self.final_end
        return Event(self.code, self.issued, self.start, end)


def _utc(text: str, compact: bool = False) -> datetime:
    form = "%Y%m%d%H%M" if compact else "%Y-%m-%d %H:%M"
    return datetime.strptime(text, form).replace(tzinfo=UTC)


def read_season(text: str, season: int) -> list[HistoryRow]:
    """The class-making zone rows of one season file (see the module docstring).

    Raises:
        HistoryError: a needed column is missing or a value is malformed.
    """
    reader = csv.DictReader(io.StringIO(text))
    needed = (
        "wfo", "phenomena", "significance", "eventid", "vtec_year", "status", "gtype", "ugc",
        "utc_issue", "utc_expire", "utc_prodissue", "utc_init_expire", "area2d",
    )  # fmt: skip
    missing = [name for name in needed if name not in (reader.fieldnames or ())]
    if missing:
        raise HistoryError(f"season {season}: missing columns {missing}")
    rows: list[tuple[HistoryRow, str]] = []
    tropical_ends: dict[str, datetime] = {}
    try:
        for record in reader:
            code = f"{record['phenomena']}.{record['significance']}"
            ugc = record["ugc"]
            if code not in CLASS_BY_CODE or record["gtype"] != "C" or len(ugc) != 6:  # noqa: PLR2004
                continue
            if ugc[2] != "Z" or ugc[:2] not in CONUS_STATES:
                continue
            key = f"{record['wfo']}.{code}.{int(record['eventid']):04d}.{record['vtec_year']}"
            final_end = _utc(record["utc_expire"])
            area = record["area2d"]
            row = HistoryRow(
                season=season,
                event_key=key,
                ugc=ugc,
                area_km2=float(area) if area else None,
                code=code,
                issued=_utc(record["utc_prodissue"]),
                start=_utc(record["utc_issue"]),
                end=None if code in TROPICAL else _utc(record["utc_init_expire"], compact=True),
                final_end=final_end,
            )
            if code in TROPICAL and record["status"] in ENDED:
                known = tropical_ends.get(key)
                tropical_ends[key] = final_end if known is None else max(known, final_end)
            rows.append((row, record["status"]))
    except (KeyError, ValueError) as error:
        raise HistoryError(f"season {season}: {error}") from error
    return [_close_tropical(item, tropical_ends) for item in rows]


def _close_tropical(item: tuple[HistoryRow, str], ends: Mapping[str, datetime]) -> HistoryRow:
    """A tropical row no product ended ends when its event's last explicitly ended row did."""
    row, status = item
    if row.code not in TROPICAL or status in ENDED:
        return row
    last = ends.get(row.event_key)
    if last is None or last >= row.final_end:
        return row
    return HistoryRow(
        row.season, row.event_key, row.ugc, row.area_km2, row.code, row.issued, row.start,
        row.end, last,
    )  # fmt: skip


def days_touched(row: HistoryRow, zone: str) -> list[date]:
    """The school days ``row`` can count for in ``zone`` (a superset: :func:`school_class`
    decides)."""
    tz = ZoneInfo(zone)
    last_moment = row.final_end if row.end is None else max(row.end, row.final_end)
    end_local = last_moment.astimezone(tz)
    day = row.start.astimezone(tz).date()
    found: list[date] = []
    while day <= end_local.date() + _ONE_DAY:
        if is_school_day(day):
            found.append(day)
        day += _ONE_DAY
    return found


def row_classes(row: HistoryRow, zone: str, window: Window) -> list[tuple[date, WeatherClass]]:
    """The days ``row`` counts for in ``zone`` at each day's snapshot, with its class."""
    found: list[tuple[date, WeatherClass]] = []
    for day in days_touched(row, zone):
        as_of = window.snapshot(day, zone)
        weather = school_class([row.event(as_of)], day, zone, window, as_of)
        if weather is not WeatherClass.NONE:
            found.append((day, weather))
    return found


@dataclass(slots=True)
class Reach:
    """Which schools each zone version reaches, season by season."""

    members: Mapping[str, npt.NDArray[np.int64]]
    """Polygon key to the directory indexes of the schools inside it."""
    extra: Mapping[tuple[str, int], npt.NDArray[np.int64]]
    """(polygon key, season) to further directory indexes it reaches that season."""
    key_of: Mapping[tuple[str, float], str]
    """(UGC, area2d) to the version's polygon key."""
    unresolved: int = 0
    """Rows whose version has no polygon (left out and counted)."""

    def schools(self, row: HistoryRow) -> npt.NDArray[np.int64] | None:
        """The directory indexes ``row`` reaches, or ``None`` when its version is unknown."""
        if row.area_km2 is None:
            return None
        key = self.key_of.get((row.ugc, row.area_km2))
        if key is None:
            return None
        inside = self.members.get(key)
        more = self.extra.get((key, row.season))
        parts = [part for part in (inside, more) if part is not None and part.size]
        if not parts:
            return np.zeros(0, dtype=np.int64)
        return np.unique(np.concatenate(parts))


@dataclass(slots=True)
class HistoryClasses:
    """Per school and day, the strongest class at the snapshot (only days above ``none``)."""

    frame: pl.DataFrame
    """Columns ``school`` (directory index), ``day``, ``weather`` (class value)."""
    rows: int
    rows_unresolved: int
    by_code: dict[str, int] = field(default_factory=dict)


def school_day_classes(
    rows: Iterable[HistoryRow],
    reach: Reach,
    zone_of_school: Sequence[str | None],
    window: Window,
) -> HistoryClasses:
    """Every (school, day) whose class is above ``none``, at the day's snapshot.

    ``zone_of_school`` gives each directory index its IANA zone (``None``: left out).
    """
    zones = np.array([zone or "" for zone in zone_of_school], dtype=object)
    schools_out: list[npt.NDArray[np.int64]] = []
    days_out: list[npt.NDArray[np.int32]] = []
    class_out: list[npt.NDArray[np.int8]] = []
    counted = 0
    unresolved = 0
    by_code: dict[str, int] = defaultdict(int)
    epoch = date(1970, 1, 1)
    for row in rows:
        counted += 1
        reached = reach.schools(row)
        if reached is None:
            unresolved += 1
            continue
        if not reached.size:
            continue
        by_code[row.code] += 1
        row_zones = zones[reached]
        for zone in sorted(set(row_zones.tolist()) - {""}):
            group = reached[row_zones == zone]
            for day, weather in row_classes(row, zone, window):
                schools_out.append(group)
                days_out.append(np.full(group.size, (day - epoch).days, dtype=np.int32))
                class_out.append(np.full(group.size, int(weather), dtype=np.int8))
    if schools_out:
        frame = (
            pl.DataFrame(
                {
                    "school": np.concatenate(schools_out),
                    "day": np.concatenate(days_out),
                    "weather": np.concatenate(class_out),
                }
            )
            .group_by("school", "day")
            .agg(pl.col("weather").max())
            .with_columns(pl.col("day").cast(pl.Date))
            .sort("school", "day")
        )
    else:
        frame = pl.DataFrame(schema={"school": pl.Int64, "day": pl.Date, "weather": pl.Int8})
    return HistoryClasses(frame, counted, unresolved, dict(sorted(by_code.items())))


def district_day_classes(
    school_classes: pl.DataFrame,
    district_of_school: pl.DataFrame,
    share: float,
) -> pl.DataFrame:
    """Each (district, day)'s class by the covered-share rule, for days above ``none``.

    ``district_of_school`` has ``school`` (directory index) and ``district`` (LEAID) for
    every eligible school; ``school_classes`` is :attr:`HistoryClasses.frame`.
    """
    totals = district_of_school.group_by("district").agg(pl.len().alias("eligible"))
    joined = school_classes.join(district_of_school, on="school", how="inner")
    if joined.is_empty():
        return pl.DataFrame(schema={"district": pl.String, "day": pl.Date, "weather": pl.Int8})
    per = joined.group_by("district", "day", "weather").agg(pl.len().alias("n"))
    found: list[pl.DataFrame] = []
    for weather in sorted(WeatherClass, reverse=True):
        if weather is WeatherClass.NONE:
            break
        at_least = (
            per.filter(pl.col("weather") >= int(weather))
            .group_by("district", "day")
            .agg(pl.col("n").sum())
            .join(totals, on="district")
            .filter(pl.col("n") >= share * pl.col("eligible"))
            .select("district", "day", pl.lit(int(weather), dtype=pl.Int8).alias("weather"))
        )
        found.append(at_least)
    return (
        pl.concat(found)
        .group_by("district", "day")
        .agg(pl.col("weather").max())
        .sort("district", "day")
    )
