"""Local time windows, and each place's time zone from the NWS boundary files.

The weather check works in UTC; a school's day is local. :func:`local_window`
turns a local date and clock times into a UTC window, using the IANA database
that ships with the operating system (``zoneinfo``).

Where a caller has no time zone for a school, :class:`TimeZoneLookup` reads it
from the ``TIME_ZONE`` attribute of the NWS county and zone boundary files. The
NWS documents these codes on https://www.weather.gov/gis/Counties; for the
contiguous states they are ``E`` (Eastern), ``C`` (Central), ``M`` (Mountain),
``m`` (Mountain, daylight time not observed) and ``P`` (Pacific), which map to
the IANA zones in :data:`IANA_ZONES`. Two-letter codes mark areas split by a
time zone line; those give no single answer unless the point falls in a zone
with a single code, and :meth:`TimeZoneLookup.zones_for` then lists every zone
the place can be in, so that a check can be run in each.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

import numpy as np
import shapely
from shapely import STRtree

from snowlight.sources.nws.boundaries import BoundarySet

IANA_ZONES: dict[str, str] = {
    "E": "America/New_York",
    "C": "America/Chicago",
    "M": "America/Denver",
    "m": "America/Phoenix",
    "P": "America/Los_Angeles",
}


def local_window(
    day: date, zone: str, start: time = time(0), end: time = time(0)
) -> tuple[datetime, datetime]:
    """Return the UTC window from ``start`` to ``end`` local time on ``day`` in ``zone``.

    When ``end`` is not after ``start`` the window runs to ``end`` on the next
    day, so the defaults give the whole local day.
    """
    tz = ZoneInfo(zone)
    begin = datetime.combine(day, start, tzinfo=tz)
    finish_day = day if end > start else day + timedelta(days=1)
    finish = datetime.combine(finish_day, end, tzinfo=tz)
    return begin.astimezone(UTC), finish.astimezone(UTC)


class Window(Protocol):
    """A clock window that can be placed in UTC for a place in a given time zone."""

    def utc(self, zone: str) -> tuple[datetime, datetime]:
        """Return the window in UTC for a place in ``zone``."""
        ...


@dataclass(frozen=True, slots=True)
class LocalWindow:
    """A local date and clock window, the same for every place (see :func:`local_window`)."""

    day: date
    start: time = time(0)
    end: time = time(0)

    def utc(self, zone: str) -> tuple[datetime, datetime]:
        """Return this window in UTC for a place in ``zone``."""
        return local_window(self.day, zone, self.start, self.end)


@dataclass(frozen=True, slots=True)
class TodayWindow:
    """A clock window on the date it is at ``now`` in each place's own time zone.

    At 03:00 UTC it is still the previous evening in the contiguous states, so
    "today" is that previous date there, not the UTC date.
    """

    now: datetime
    start: time = time(0)
    end: time = time(0)

    def day_in(self, zone: str) -> date:
        """Return the local date at ``now`` in ``zone``."""
        if self.now.tzinfo is None:
            raise ValueError("now must be an aware time")
        return self.now.astimezone(ZoneInfo(zone)).date()

    def utc(self, zone: str) -> tuple[datetime, datetime]:
        """Return this window in UTC for a place in ``zone``."""
        return local_window(self.day_in(zone), zone, self.start, self.end)


def _single(codes: tuple[str, ...] | None) -> str | None:
    if codes is None or len(codes) != 1:
        return None
    return IANA_ZONES.get(codes[0])


def _all(codes: tuple[str, ...] | None) -> tuple[str, ...]:
    """Every IANA zone a set of NWS codes (each one or more letters) can mean."""
    letters = sorted({letter for code in codes or () for letter in code})
    names = [IANA_ZONES.get(letter) for letter in letters]
    if not letters or None in names:
        return ()  # a code outside the contiguous states' set: nothing is known
    return tuple(sorted({name for name in names if name is not None}))


class TimeZoneLookup:
    """Finds a place's IANA time zone from NWS county and zone boundaries."""

    def __init__(self, counties: BoundarySet, zones: BoundarySet) -> None:
        self._by_fips: dict[str, str | None] = {}
        self._fips_options: dict[str, set[str]] = {}
        for ugc, fips in counties.county_fips.items():
            codes = counties.time_zones.get(ugc)
            answer = _single(codes)
            known = self._by_fips.get(fips, answer)
            self._by_fips[fips] = answer if known == answer else None
            self._fips_options.setdefault(fips, set()).update(_all(codes))
        usable = [
            (geometry, _single(codes), _all(codes))
            for ugc, geometry in sorted(zones.areas.items())
            if _all(codes := zones.time_zones.get(ugc))
        ]
        self._zone_names = [name for _geometry, name, _options in usable]
        self._zone_options = [options for _geometry, _name, options in usable]
        geometries = np.array([geometry for geometry, _name, _options in usable], dtype=object)
        shapely.prepare(geometries)
        self._zone_geometries = geometries
        self._tree = STRtree(geometries)

    def _zones_at(self, lat: float, lon: float) -> list[int]:
        candidates = self._tree.query(shapely.points(lon, lat))
        return [
            i
            for i in candidates.tolist()
            if shapely.intersects_xy(self._zone_geometries[i], lon, lat)
        ]

    def zone_for(self, county_fips: str | None, lat: float | None, lon: float | None) -> str | None:
        """Return the IANA zone for a place, or ``None`` when the files do not settle it.

        The county's code is used when it is a single zone; otherwise the public
        forecast zone containing the point, when that zone has a single code.
        """
        if county_fips is not None:
            answer = self._by_fips.get(county_fips)
            if answer is not None:
                return answer
        if lat is None or lon is None:
            return None
        names = {name for i in self._zones_at(lat, lon) if (name := self._zone_names[i])}
        return names.pop() if len(names) == 1 else None

    def zones_for(
        self, county_fips: str | None, lat: float | None, lon: float | None
    ) -> tuple[str, ...]:
        """Return every IANA zone the place can be in (one when :meth:`zone_for` settles it).

        When the files do not settle it, these are the zones the codes of the
        forecast zone containing the point allow, or else those of the county.
        An empty tuple means nothing is known.
        """
        single = self.zone_for(county_fips, lat, lon)
        if single is not None:
            return (single,)
        if lat is not None and lon is not None:
            options = {name for i in self._zones_at(lat, lon) for name in self._zone_options[i]}
            if options:
                return tuple(sorted(options))
        if county_fips is not None:
            return tuple(sorted(self._fips_options.get(county_fips, ())))
        return ()
