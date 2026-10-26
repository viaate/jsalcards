"""The forecast amounts a pass gives the reasons: each district's NDFD values at the class
snapshot (S7 spec, piece 3; addendum 2026-10-24 g).

The terms were fit on the forecast as it stood at 21:00 local the evening before each school
day (the history's sample 13, :mod:`snowlight.predict.forecast_history`), the class snapshot
the base was counted at. A pass reads, for school day ``D`` and each time zone, the newest run
that counts at ``min(now, 21:00 D-1 local)`` (:func:`snapshot_at`), with the history's own
reader and rules (:func:`~snowlight.predict.forecast_history.run_values`, the district's 50%
value and its bucket code). So every pass from 9 PM on, the morning's too, reads the one of
9 PM: the forecast the base and the terms were counted on. A pass before 9 PM reads an earlier
run than the terms were fit or backtested on (same window, school cell and 50% value, a longer
lead): docs/predict.md lists it for the lead before turn-on. The chance does not change at any
hour after 9 PM for the forecast's sake alone (a pass that dropped the forecast after 9 PM
would move the chance back to its base with nothing in the weather changed, and show that as a
change). The lines carry the run's time (``at``), and the web words them with it ("The 8:16 PM
forecast has"): the time, not the day, so a morning panel names last night's run without
saying it is last night's (also on the turn-on list).

For the words it also keeps, over the district's deciding schools, the lowest and highest
window snow, overnight snow (the periods ending 06 and 12 UTC on ``D``: 6 PM to 6 AM Central),
window ice and 7 AM feel as read (never rounded, so the words can check that what they state
holds every deciding school; a feel is ``None`` when a deciding school has none), the
district's 50% value of the overnight snow, and its 50% values of ice
(hundredths of an inch) and of how cold it feels at 7 AM (whole degrees). A line states an
amount only where every deciding school's forecast is in it, and otherwise only its comparison
(:mod:`snowlight.predict.reasons`).

A run that does not list or read leaves the zone's districts with no forecast: their terms add
nothing (the chance is the base's, and no forecast line shows), as a night with no run is
unknown in training. Nothing here is ever a guess.
"""

import math
from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import date, datetime, timedelta

import numpy as np

from snowlight.predict import forecast_history as history
from snowlight.predict import ndfd
from snowlight.predict.forecast_values import NO_FORECASTS, DistrictForecast, Forecasts
from snowlight.predict.ndfd import Floats, Run

__all__ = [
    "NO_FORECASTS",
    "DistrictForecast",
    "Forecasts",
    "forecasts",
    "run_reader",
    "snapshot_at",
]

SNAPSHOT_SAMPLE = 13
"""The history's sample at 21:00 local the evening before (08:00 + 13 hours)."""
OVERNIGHT_ENDS = (6, 12)
"""Period ends (UTC hours on the school day) counted as overnight snow."""


def snapshot_at(day: date, zone: str, now: datetime) -> datetime:
    """When a pass at ``now`` reads the forecast for ``day`` in ``zone``: 21:00 the evening
    before, or now if earlier."""
    return min(now, history.sample_time(day, zone, SNAPSHOT_SAMPLE))


def _read(values: Floats | None, k: int) -> float | None:
    if values is None:
        return None
    found = float(values[k])
    return found if math.isfinite(found) else None


def zone_forecasts(
    values: history.RunValues,
    group: history.ZoneGroup,
    day: date,
    at: datetime,
    share: float,
) -> dict[int, DistrictForecast]:
    """Every district of ``group`` from one run's values (district index of :class:`Schools`
    to its forecast)."""
    bus = ndfd.bus_time(day, group.zone)
    codes = history._codes(values, group, day, at, bus, share)
    snow = ndfd.window_total(values.snow, day, at)
    ice = ndfd.window_total(values.ice, day, at)
    feels = values.feels.get(bus)
    count = group.groups.ids.shape[0]
    mine = group.schools
    snow_low = snow_high = night_half = night_low = night_high = None
    if snow is not None:
        school = np.where(np.isnan(snow[mine]), 0.0, snow[mine])
        snow_low, snow_high = ndfd.group_min_max(school, group.groups)
        ends = ndfd.window_ends(day)
        night = np.zeros_like(school)
        for end in ends:
            if end.hour in OVERNIGHT_ENDS and end > at and end in values.snow:
                part = values.snow[end][mine]
                night = night + np.where(np.isnan(part), 0.0, part)
        # A school whose window total reads as none has none overnight either, so the
        # overnight part is never more than the total it is part of.
        night = np.where(np.isnan(snow[mine]), 0.0, np.minimum(night, school))
        night_half = ndfd.group_half(night, group.groups, share)
        night_low, night_high = ndfd.group_min_max(night, group.groups)
    ice_half = ice_low = ice_high = None
    if ice is not None:
        school_ice = np.where(np.isnan(ice[mine]), 0.0, ice[mine])
        ice_half = ndfd.group_half(school_ice, group.groups, share)
        ice_low, ice_high = ndfd.group_min_max(school_ice, group.groups)
    feels_half = feels_low = feels_high = None
    if feels is not None:
        feels_half = ndfd.group_half(
            np.where(np.isnan(feels[mine]), np.inf, feels[mine]), group.groups, share, coldest=True
        )
        # NaN where a deciding school has no value: no degree is said of a school not read.
        feels_low, feels_high = ndfd.group_min_max(feels[mine], group.groups)
    found: dict[int, DistrictForecast] = {}
    for k in range(count):
        district = int(group.groups.ids[k])
        overnight = None
        if night_half is not None:
            overnight = round(float(night_half[k]), 2)
        feel = None
        if feels_half is not None and math.isfinite(float(feels_half[k])):
            feel = round(float(feels_half[k]))
        found[district] = DistrictForecast(
            code=int(codes.filled[k]),
            snow_low=_read(snow_low, k),
            snow_high=_read(snow_high, k),
            snow_night=overnight,
            snow_night_low=_read(night_low, k),
            snow_night_high=_read(night_high, k),
            ice=None if ice_half is None else round(float(ice_half[k]), 2),
            ice_low=_read(ice_low, k),
            ice_high=_read(ice_high, k),
            feels=feel,
            feels_low=_read(feels_low, k),
            feels_high=_read(feels_high, k),
            run_time=values.run.time,
        )
    return found


type ReadRun = Callable[[Run, date], history.RunValues]
"""Reads one run's values for one school day (cached by the caller across passes)."""


def forecasts(  # noqa: PLR0913, PLR0917 - the schools, the days, the runs and the reader
    schools: history.Schools,
    index_of: Mapping[str, int],
    days: Sequence[date],
    now: datetime,
    runs_for: Callable[[date], Sequence[Run] | None],
    read: ReadRun,
    share: float,
    *,
    moment: Callable[[date, str], datetime] | None = None,
    zones: Collection[str] | None = None,
) -> Forecasts:
    """Every deciding district's forecast on ``days`` (``index_of``: LEAID to its deployed
    index). ``runs_for(day)`` lists the runs a night can use (``None``: the listing did not
    read). A refused run gives way to the one before it, as in the history.

    ``moment(day, zone)``: when each zone's forecast is read (the newest run that counts then,
    at most 3 hours old); by default the class snapshot (:func:`snapshot_at`). The outlook
    (S7-F) reads the newest run at the pass, and a sample hour's at that hour. ``zones``: only
    these zones' districts (all by default)."""
    groups = [
        group for group in history.zone_groups(schools) if zones is None or group.zone in zones
    ]
    by_day: dict[date, dict[int, DistrictForecast]] = {}
    problems: list[str] = []
    unread: dict[date, dict[str, str]] = {}
    for day in days:
        mine: dict[int, DistrictForecast] = {}
        by_day[day] = mine
        if not groups:
            continue
        runs = runs_for(day)
        if runs is None:
            problems.append(f"{day}: the forecast runs did not list")
            unread[day] = {group.zone: "error" for group in groups}
            continue
        for group in groups:
            at = snapshot_at(day, group.zone, now) if moment is None else moment(day, group.zone)
            usable = list(runs)
            values = None
            failed = False
            while True:
                run = ndfd.newest_run(usable, at)
                if run is None:
                    break
                try:
                    values = read(run, day)
                except ndfd.NdfdError as error:
                    problems.append(f"{day} {group.zone}: run {run.time:%H:%MZ}: {error}")
                    values = None
                    failed = True
                    break
                if values.refused is None:
                    break
                usable = [item for item in usable if item.time != run.time]
                values = None
            if values is None:
                problems.append(f"{day} {group.zone}: no run counts at {at:%Y-%m-%d %H:%MZ}")
                unread.setdefault(day, {})[group.zone] = "error" if failed else "stale"
                continue
            for k, found in zone_forecasts(values, group, day, at, share).items():
                index = index_of.get(schools.districts[k])
                if index is not None:
                    mine[index] = found
    return Forecasts(by_day, tuple(problems), unread)


def bus_times(day: date, zones: Sequence[str]) -> list[datetime]:
    """Every zone's 7 AM on ``day``, as the history reads apparent temperature."""
    return sorted({ndfd.bus_time(day, zone) for zone in zones})


def run_reader(
    schools: history.Schools,
    opener: history.Opener,
    cache: dict[tuple[datetime, date], history.RunValues],
) -> ReadRun:
    """Reads a run's values for a day once, kept in ``cache`` (pass to pass)."""
    where = ndfd.cells(schools.lat, schools.lon)
    zones = sorted(set(schools.zone_of_district))

    def read(run: Run, day: date) -> history.RunValues:
        key = (run.time, day)
        known = cache.get(key)
        if known is None:
            known = cache[key] = history.run_values(run, day, bus_times(day, zones), where, opener)
            for old in [k for k in cache if k[1] < day - timedelta(days=2)]:
                del cache[old]
        return known

    return read
