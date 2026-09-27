"""Storm days: the school days NWS winter warnings covered each station's counties.

The archive planner picks the captures of a closings page most likely to hold a
list: those made on, or on the evening before, a school day on which winter
weather warnings covered the station's market. Page size alone is a poor guide
(a page grows with advertising and markup as well as with closings), and a
station whose list file never changes size would otherwise be sampled at random.

The storm days come from the same official record and the same counting as the
closure weights (:mod:`snowlight.weights`): the NWS watches, warnings and
advisories archived by the Iowa Environmental Mesonet, one file per school year,
placed in counties through the NWS zone-county correlation, a day counting for a
county under the 6 AM rule (:mod:`snowlight.weights.count`). Only the winter and
cold codes count here (Winter Storm, Blizzard, Ice Storm and Lake Effect Snow
Warnings, the Winter Weather Advisory, Extreme Cold and Wind Chill Warnings), each
day at the largest weight among the codes that covered it
(:mod:`snowlight.weights.codes`). Flood and tropical codes are left out: a
closings page on a hurricane day is worth reading, but those days are rare in the
markets whose lists are missing, and the planner wants snow days.

A station's score for a day is the mean, over the counties in its county list, of
that day's weight (0 where no winter code covered the county), so 1.0 means a
Winter Storm Warning or stronger over the whole market. A capture is about the
school day of its UTC time plus :data:`DAY_SHIFT` (8 hours): a capture from
about 4 PM local time on is about the next morning, when closings for it are
posted; one made in the morning is about that day.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from snowlight.sources.nws.http import HttpCache
from snowlight.sources.nws.http import make_client as make_reference_client
from snowlight.sources.stations.registry import Registry
from snowlight.weights.build import count_weather
from snowlight.weights.cache import WeightsCache
from snowlight.weights.codes import BY_CODE
from snowlight.weights.count import Tally

STORM_GROUPS = frozenset({"winter", "cold"})
"""The closure-code groups (see :mod:`snowlight.weights.codes`) that make a storm day."""
DAY_SHIFT = timedelta(hours=8)
"""Added to a capture's UTC time to get the school day its list is about."""


def county_days(tally: Tally) -> dict[str, dict[date, float]]:
    """Return each county's storm days and each day's weight, from a weights tally."""
    found: dict[str, dict[date, float]] = defaultdict(dict)
    for fips, years in tally.counties.items():
        for counts in years.values():
            for code, days in counts.by_code.items():
                closure = BY_CODE.get(code)
                if closure is None or closure.group not in STORM_GROUPS:
                    continue
                for day in days:
                    found[fips][day] = max(found[fips].get(day, 0.0), closure.weight)
    return dict(found)


def load_county_days(cache: HttpCache | None = None) -> dict[str, dict[date, float]]:
    """Count the storm days from the weights build's cached school-year files.

    The files are the weights build's (``pipeline/.cache/weights/``); any that is
    missing is downloaded through the same cache, with its provenance sidecar.
    """
    if cache is None:
        with HttpCache(make_reference_client()) as http:
            return county_days(count_weather(WeightsCache(http)).tally)
    return county_days(count_weather(WeightsCache(cache)).tally)


@dataclass(frozen=True, slots=True)
class StormDays:
    """Each station's storm days: school day to the market's mean warning weight."""

    by_station: Mapping[str, Mapping[date, float]]

    @classmethod
    def build(cls, registry: Registry, counties: Mapping[str, Mapping[date, float]]) -> "StormDays":
        """Score every station with a county list against ``counties``' storm days."""
        by_station: dict[str, dict[date, float]] = {}
        for station in registry.stations.values():
            if station.counties is None:
                continue
            fips = station.counties.fips
            totals: dict[date, float] = defaultdict(float)
            for code in fips:
                for day, weight in counties.get(code, {}).items():
                    totals[day] += weight
            by_station[station.id] = {day: total / len(fips) for day, total in totals.items()}
        return cls(by_station)

    def score(self, station_id: str, moment: datetime) -> float:
        """Return the storm score of the school day a capture made at ``moment`` is about."""
        return self.by_station.get(station_id, {}).get(school_day(moment), 0.0)

    def days(self, station_id: str) -> Iterable[tuple[date, float]]:
        """Return the station's storm days, strongest first."""
        found = self.by_station.get(station_id, {})
        return sorted(found.items(), key=lambda item: (-item[1], item[0]))


def school_day(moment: datetime) -> date:
    """Return the school day a capture made at ``moment`` (UTC) is about."""
    return (moment + DAY_SHIFT).date()
