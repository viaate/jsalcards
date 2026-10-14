"""Closure seasons: whether a list left unwritten has missed weather that closes schools.

``stations fetch`` (:mod:`snowlight.sources.stations.fetch`, step 4) once called a list
stale whenever nothing had been written to it since before the last winter began: a
station that moved its list elsewhere leaves the old file behind. That reasoning holds
where weather closes schools every winter, not where it seldom does. Savannah's list
file (WTOC) was last written on 2025-01-24, two days after it held 23 closings for the
snow of 22 January 2025 (an archived capture), and no weather of the kind has come to
that market since; Sarasota's (WWSB) on 2024-10-12, after the Hurricane Warning of
8-9 October 2024 (Milton). Such a list is idle, not abandoned: nothing has happened
that it would list.

So a list last written before the last winter began is judged by its market's closure
seasons since then (:meth:`ClosureSeasons.judge`): it is stale only when weather that
closes schools came to its market after it was last written, and it was not written
for it (New Orleans' WVUE file, last written on 2024-01-16, missed the Hurricane
Warning of 11-12 September 2024, Francine, and the Winter Storm Warning of 21 January
2025). Otherwise it is idle: its rows
(any left from its last closure) are old and not kept, the read is ``empty``, and the
station counts as working. A list written since the last winter began is judged as
before (in use), and a station whose market this record does not know keeps the
winter rule.

Closure weather
===============

The official record is the one the closure weights count (:mod:`snowlight.weights`):
the NWS watches, warnings and advisories the Iowa Environmental Mesonet archives, one
file per school year (the weights build's files for 2015-16 to 2025-26, and the
current school year's file so far, fetched again when an hour old), placed in counties
through the NWS zone-county correlation, a school day (Monday to Friday, 15 August to
15 June) counting for a county under the 6 AM rule (:mod:`snowlight.weights.count`).
Only the warnings for weather that closes schools across a market count
(:data:`CLOSURE_CODES`): the Winter Storm, Blizzard, Ice Storm and Lake Effect Snow
Warnings and the Hurricane Warning (the codes the weights count at 1.0, the classic
causes of a snow day or a storm closure), and the Tropical Storm Warning (districts
close under it as a hurricane nears; as Milton crossed Florida on 9-10 October 2024,
the Tropical Storm Warning, not the Hurricane Warning, covered most of the West Palm
Beach market's schools). Advisories, cold warnings
(districts close for cold only past their own thresholds, and a warning that would
close them comes with the storms the list does serve) and flood warnings do not.

A station's *closure day* is a school day on which those codes covered counties
holding at least :data:`MARKET_SHARE` of the schools in its market: the schools of
its county list (for a district-level source, of its districts), counted from the
school directory. Closure days at most :data:`EVENT_GAP` apart (a weekend between)
are one *closure event*. A list last written at ``W`` *missed* an event when the
event's first day is more than :data:`WRITE_LEAD` after ``W``'s day (a list written
the day before a storm's first day was written for it).

Written by ``snowlight stations seasons`` (internal, never published) to
``closure-days.json``::

    {"generated_at", "counted_through", "codes": [...], "market_share",
     "event_gap_days", "write_lead_days",
     "school_years": {label: {"url", "sha256", "bytes", "retrieved_at", "checked_at",
                              "final"}},
     "directory": {"path", "sha256", "schools"},
     "stations": {id: [[first, last, share, "CODE,CODE"], ...]}}

``counted_through`` is the last school day the record covers. A station absent from
``stations`` has no market this record can measure (no county list, no district
schools); one with an empty list has had no closure event since 2015-16.
"""

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from snowlight.output import JSONValue, write_json
from snowlight.sources.stations.http import iso_utc
from snowlight.sources.stations.registry import Registry
from snowlight.weights import archive
from snowlight.weights import count as weights_count
from snowlight.weights.build import count_weather
from snowlight.weights.cache import WeightsCache

CLOSURE_CODES = frozenset({"WS.W", "BZ.W", "IS.W", "LE.W", "HU.W", "TR.W"})
"""The warnings for weather that closes schools across a market (see the module docstring)."""
MARKET_SHARE = 0.5
"""The share of a market's schools those warnings must cover for a school day to count."""
EVENT_GAP = timedelta(days=3)
"""Closure days at most this far apart are one event (Friday and Monday are)."""
WRITE_LEAD = timedelta(days=1)
"""A list written this long before an event's first day (or later) was written for it."""
SEASONS_FILE = "closure-days.json"
_SHARE_DIGITS = 3
_EVENT_FIELDS = 4


class SeasonsError(ValueError):
    """``closure-days.json`` does not have the shape ``stations seasons`` writes."""


@dataclass(frozen=True, slots=True)
class ClosureEvent:
    """A run of a market's closure days (at most :data:`EVENT_GAP` apart)."""

    first: date
    last: date
    share: float
    """The largest share of the market's schools the warnings covered on one of its days."""
    codes: tuple[str, ...]
    """Every closure code that covered one of the market's counties on one of its days."""

    def describe(self) -> str:
        """Say what the event was, e.g. ``2025-01-21 (BZ.W, WS.W over 100% of its schools)``."""
        span = (
            self.first.isoformat()
            if self.first == self.last
            else f"{self.first.isoformat()} to {self.last.isoformat()}"
        )
        return f"{span} ({', '.join(self.codes)} over {self.share:.0%} of its schools)"

    def as_json(self) -> list[JSONValue]:
        """The event as ``closure-days.json`` holds it."""
        return [self.first.isoformat(), self.last.isoformat(), self.share, ",".join(self.codes)]


@dataclass(frozen=True, slots=True)
class SeasonVerdict:
    """What a station's closure seasons say of a list last written at ``written``."""

    written: datetime
    missed: tuple[ClosureEvent, ...]
    """The closure events after the list was last written (none: the list is idle)."""
    before: ClosureEvent | None
    """The last closure event the list was written for (or before it), if any."""
    counted_through: date

    @property
    def stale(self) -> bool:
        """Whether the list missed weather that closes schools: it is not the one in use."""
        return bool(self.missed)

    def explain(self) -> str:
        """Say why, for a health reason."""
        if self.missed:
            more = (
                f", and {len(self.missed) - 1} more since, the last {self.missed[-1].describe()}"
                if len(self.missed) > 1
                else ""
            )
            return (
                f"weather that closes schools came to its market after that, and the list was "
                f"not written for it: {self.missed[0].describe()}{more}"
            )
        last = f"; the last before it: {self.before.describe()}" if self.before else ""
        return (
            f"no weather that closes schools has come to its market since (none of "
            f"{', '.join(sorted(CLOSURE_CODES))} over {MARKET_SHARE:.0%} of its schools on a "
            f"school day, counted through {self.counted_through.isoformat()}{last}): the list "
            "is idle, not abandoned"
        )


@dataclass(frozen=True, slots=True)
class ClosureSeasons:
    """Every station's closure events, and how far the record goes."""

    counted_through: date
    events: Mapping[str, tuple[ClosureEvent, ...]]

    def knows(self, station_id: str) -> bool:
        """Whether the record measures the station's market."""
        return station_id in self.events

    def judge(self, station_id: str, written: datetime) -> SeasonVerdict | None:
        """Judge a list last written at ``written``; ``None`` for a market not measured."""
        if station_id not in self.events:
            return None
        day = written.astimezone(UTC).date()
        events = self.events[station_id]
        missed = tuple(
            event
            for event in events
            if event.first - WRITE_LEAD > day and event.first <= self.counted_through
        )
        before = [event for event in events if event.first - WRITE_LEAD <= day]
        return SeasonVerdict(written, missed, before[-1] if before else None, self.counted_through)

    def as_json(self, generated_at: datetime, extra: Mapping[str, JSONValue]) -> JSONValue:
        """The record as ``closure-days.json`` holds it (``extra``: provenance fields)."""
        codes: list[JSONValue] = [*sorted(CLOSURE_CODES)]
        return {
            "generated_at": iso_utc(generated_at),
            "counted_through": self.counted_through.isoformat(),
            "codes": codes,
            "market_share": MARKET_SHARE,
            "event_gap_days": EVENT_GAP.days,
            "write_lead_days": WRITE_LEAD.days,
            **extra,
            "stations": {
                station_id: [event.as_json() for event in events]
                for station_id, events in sorted(self.events.items())
            },
        }

    @classmethod
    def load(cls, path: Path) -> "ClosureSeasons":
        """Read ``closure-days.json``."""
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            through = date.fromisoformat(document["counted_through"])
            stations = document["stations"]
            events = {
                str(station_id): tuple(_event(item) for item in items)
                for station_id, items in stations.items()
            }
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            raise SeasonsError(f"{path}: {error}") from error
        return cls(through, events)


def _event(item: object) -> ClosureEvent:
    if not isinstance(item, list) or len(item) != _EVENT_FIELDS:
        raise SeasonsError(f"an event is not [first, last, share, codes]: {item!r}")
    first, last, share, codes = item
    return ClosureEvent(
        date.fromisoformat(str(first)),
        date.fromisoformat(str(last)),
        float(share),
        tuple(code for code in str(codes).split(",") if code),
    )


def county_closure_days(tallies: Iterable[weights_count.Tally]) -> dict[str, dict[date, set[str]]]:
    """Each county's school days under a closure code, and the codes that covered each."""
    found: dict[str, dict[date, set[str]]] = defaultdict(lambda: defaultdict(set))
    for tally in tallies:
        for fips, years in tally.counties.items():
            for counts in years.values():
                for code, days in counts.by_code.items():
                    if code not in CLOSURE_CODES:
                        continue
                    for day in days:
                        found[fips][day].add(code)
    return {fips: dict(days) for fips, days in found.items()}


def market_events(
    schools: Mapping[str, int], county_days: Mapping[str, Mapping[date, Iterable[str]]]
) -> tuple[ClosureEvent, ...]:
    """A market's closure events, from its schools per county (see the module docstring)."""
    total = sum(schools.values())
    if total <= 0:
        return ()
    covered: dict[date, int] = defaultdict(int)
    codes: dict[date, set[str]] = defaultdict(set)
    for fips, count in schools.items():
        for day, day_codes in county_days.get(fips, {}).items():
            covered[day] += count
            codes[day].update(day_codes)
    events: list[ClosureEvent] = []
    for day in sorted(covered):
        share = covered[day] / total
        if share < MARKET_SHARE:
            continue
        if events and day - events[-1].last <= EVENT_GAP:
            held = events[-1]
            events[-1] = ClosureEvent(
                held.first,
                day,
                max(held.share, round(share, _SHARE_DIGITS)),
                tuple(sorted({*held.codes, *codes[day]})),
            )
        else:
            events.append(
                ClosureEvent(day, day, round(share, _SHARE_DIGITS), tuple(sorted(codes[day])))
            )
    return tuple(events)


def station_markets(
    registry: Registry,
    county_schools: Mapping[str, int],
    district_schools: Mapping[str, Mapping[str, int]],
) -> dict[str, dict[str, int]]:
    """Each station's market: schools per county (its districts', or its county list's)."""
    markets: dict[str, dict[str, int]] = {}
    for station in sorted(registry.stations.values(), key=lambda s: s.id):
        market: dict[str, int] = defaultdict(int)
        if station.leaids:
            for leaid in station.leaids:
                for fips, count in district_schools.get(leaid, {}).items():
                    market[fips] += count
        elif station.counties is not None:
            for fips in station.counties.fips:
                market[fips] += county_schools.get(fips, 0)
        if sum(market.values()) > 0:
            markets[station.id] = dict(market)
    return markets


def build(
    markets: Mapping[str, Mapping[str, int]],
    county_days: Mapping[str, Mapping[date, Iterable[str]]],
    counted_through: date,
) -> ClosureSeasons:
    """Every measured station's closure events up to ``counted_through``."""
    events = {
        station_id: tuple(
            event for event in market_events(market, county_days) if event.first <= counted_through
        )
        for station_id, market in markets.items()
    }
    return ClosureSeasons(counted_through, events)


@dataclass(frozen=True, slots=True)
class Counted:
    """The closure days counted from the NWS record, and the files they came from."""

    county_days: dict[str, dict[date, set[str]]]
    counted_through: date
    files: tuple[archive.SchoolYearFile, ...]


def current_years(today: date) -> list[int]:
    """The school years after the weights build's that have begun by ``today``."""
    return [
        year
        for year in range(archive.LAST_SCHOOL_YEAR + 1, today.year + 1)
        if archive.request_window(year)[0] <= today
    ]


def count_closure_weather(cache: WeightsCache, today: date) -> Counted:
    """Count the closure days: the weights build's school years and the current one so far.

    The current school year's file is provisional (the archive is fetched again once an
    hour old); its rows are placed with the same zone catalog. ``counted_through`` is
    the last school day the files cover: the day before the current file was fetched,
    or the weights build's last school day when no later year has begun.
    """
    counted = count_weather(cache)
    files = list(counted.files)
    tallies = [counted.tally]
    last_year = archive.LAST_SCHOOL_YEAR
    through = date(last_year + 1, *weights_count.LAST_SCHOOL_DAY)
    later = current_years(today)
    if later:
        current = archive.load_years(cache, later)
        tallies.append(weights_count.count_years(current, counted.catalog, counted.counties))
        files.extend(current)
        fetched = datetime.fromisoformat(
            current[-1].file.provenance.checked_at.replace("Z", "+00:00")
        )
        through = max(through, (fetched - timedelta(days=1)).date())
    return Counted(county_closure_days(tallies), through, tuple(files))


def provenance(files: Sequence[archive.SchoolYearFile]) -> dict[str, JSONValue]:
    """The school-year files' provenance, for ``closure-days.json``."""
    return {file.label: {**file.file.provenance.as_json(), "final": file.final} for file in files}


def write(path: Path, seasons: ClosureSeasons, generated_at: datetime, **extra: JSONValue) -> None:
    """Write ``closure-days.json``."""
    write_json(path, seasons.as_json(generated_at, extra))
