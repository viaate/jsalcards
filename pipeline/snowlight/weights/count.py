"""Counting the school days each county spent under closure-type events.

School days
===========

For the school year starting in ``Y``: every Monday to Friday from 15 August
``Y`` to 15 June ``Y+1``, both included. Holidays and breaks are not removed (no
official calendar covers every district), so a storm over the winter break
counts; this affects every county alike.

The 6 AM rule
=============

A county's school day ``d`` counts for a code when a row of that code covering
the county (its zone or county UGC; see :mod:`snowlight.weights.zones`) was, in
the county's local time:

* in effect at 06:00 on ``d``: its recorded span ``[begin, end)`` contains
  06:00; or
* issued for that day by then: the product that created the row was issued by
  06:00, the row had not been withdrawn by 06:00 (``end`` is after it), and it
  begins after 06:00 but before the end of the school day, 15:00
  (:data:`SCHOOL_DAY_END`), so districts deciding at dawn knew a warning would
  start during school hours. This holds for a row withdrawn after 06:00 but
  before it began, too (IEM records it with ``end`` at the withdrawal, before
  ``begin``; see :mod:`snowlight.weights.archive`).

The span is the one IEM finally recorded: an event cancelled before 06:00 does
not count, one cancelled later does; a begin time a later product moved is read
where it ended up. A county split by a time zone line counts the day when the
rule holds at 06:00 in either of its zones.

What is counted
===============

For each county, school year and code, the distinct school days the code
covered (unweighted), and which UGCs covered each of them. A day's weighted
value is the largest weight among the codes that covered it
(:mod:`snowlight.weights.codes`), so each day counts once.

Two diagnostics come from the UGCs (they do not change the metric):

* *whole-county* days: days on which the code covered every zone the county has
  in the correlation release in effect that day (or the county's own UGC). A
  zone-based warning that covered only one zone of a county (a mountain zone of
  a county whose schools are in the valley) counts for the whole county in the
  metric, as the correlation rule requires; the share of such partial days shows
  where that rule weighs most.
* *driver* zones: per county, the days each UGC covered it, and the days on
  which it was the only UGC that did.

School years left out of a county's average
===========================================

Some zone rows cannot be counted for the counties they covered: the zone is in
no served correlation release (the releases start in April 2019, and zones
redrawn before then are in none), the zone's code meant another area then, or
the release gives the zone a county code the county list lacks (see
:mod:`snowlight.weights.outlines` for how the build finds the counties such rows
covered). A county's count for such a school year is incomplete, not
zero, so :func:`summarize` averages each county only over the school years
with no such rows for it, and every per-year figure of the county (the metric,
the per-code counts, the subsets, the whole-county diagnostic and the driver
zones) uses those years only. Nothing is filled in for the years left out.
"""

from collections import Counter, defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from functools import cache
from zoneinfo import ZoneInfo

from snowlight.weights.archive import REQUEST_START, EventRow, SchoolYearFile
from snowlight.weights.codes import BY_CODE, CODES
from snowlight.weights.zones import CountyList, ZoneCountyCatalog

FIRST_SCHOOL_DAY = (8, 15)
LAST_SCHOOL_DAY = (6, 15)
DECISION_TIME = time(6, 0)
SCHOOL_DAY_END = time(15, 0)
_WEEKEND = 5


class CountError(ValueError):
    """A county cannot be summarized (every school year of it was left out)."""


def school_year_of(day: date) -> int:
    """Return the school year (by its starting year) whose window holds ``day``.

    Days from 1 August on belong to the year starting then; earlier days to the
    year before.
    """
    return day.year if (day.month, day.day) >= REQUEST_START else day.year - 1


def school_days(year: int) -> list[date]:
    """Return the weekdays from 15 August ``year`` to 15 June ``year + 1``."""
    first, last = date(year, *FIRST_SCHOOL_DAY), date(year + 1, *LAST_SCHOOL_DAY)
    days = []
    day = first
    while day <= last:
        if day.weekday() < _WEEKEND:
            days.append(day)
        day += timedelta(days=1)
    return days


@cache
def _moment(day: date, clock: time, zone: str) -> datetime:
    return datetime.combine(day, clock, tzinfo=ZoneInfo(zone)).astimezone(UTC)


def row_counts_on(
    begin: datetime, end: datetime, product_issued: datetime, day: date, zone: str
) -> bool:
    """Whether a row with this span and product time counts for local ``day`` in ``zone``."""
    decision = _moment(day, DECISION_TIME, zone)
    if begin <= decision < end:
        return True
    closing = _moment(day, SCHOOL_DAY_END, zone)
    return product_issued <= decision < end and decision < begin < closing


@cache
def counted_days(
    begin: datetime, end: datetime, product_issued: datetime, zones: tuple[str, ...]
) -> frozenset[date]:
    """Return the local dates (any weekday) a row counts for in a county with ``zones``."""
    found: set[date] = set()
    first, final = min(begin, end), max(begin, end)
    for zone in zones:
        tz = ZoneInfo(zone)
        day = first.astimezone(tz).date() - timedelta(days=1)
        last = final.astimezone(tz).date() + timedelta(days=1)
        while day <= last:
            if row_counts_on(begin, end, product_issued, day, zone):
                found.add(day)
            day += timedelta(days=1)
    return frozenset(found)


def _all_codes(codes: Iterable[str] | None) -> set[str]:
    return set(BY_CODE) if codes is None else set(codes)


@dataclass(slots=True)
class YearCounts:
    """One county's days in one school year: code to day to the UGCs that covered it."""

    by_code: dict[str, dict[date, set[str]]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(set))
    )

    def days(self, code: str) -> set[date]:
        """Return the days ``code`` covered."""
        return set(self.by_code.get(code, {}))

    def any_days(self, codes: Iterable[str] | None = None) -> set[date]:
        """Return the days covered by any of ``codes`` (all codes when ``None``)."""
        wanted = _all_codes(codes)
        found: set[date] = set()
        for code, days in self.by_code.items():
            if code in wanted:
                found |= set(days)
        return found

    def weighted(
        self, codes: Iterable[str] | None = None, *, whole: Mapping[str, set[date]] | None = None
    ) -> float:
        """Return the sum over covered days of the largest weight that day.

        With ``whole`` (code to its whole-county days), only those days count.
        """
        wanted = _all_codes(codes)
        best: dict[date, float] = {}
        for code, days in self.by_code.items():
            if code not in wanted:
                continue
            weight = BY_CODE[code].weight
            for day in days if whole is None else whole.get(code, set()):
                best[day] = max(best.get(day, 0.0), weight)
        return sum(best.values())


@dataclass(slots=True)
class CountStats:
    """What the counting did with the rows it was given."""

    rows: int = 0
    county_rows: int = 0
    rows_without_county: int = 0
    unknown_counties: Counter[str] = field(default_factory=Counter)
    rows_counted: int = 0


def _nested_year_counts() -> defaultdict[int, YearCounts]:
    return defaultdict(YearCounts)


@dataclass(slots=True)
class Tally:
    """Every county's days, by school year and code."""

    years: list[int]
    counties: dict[str, dict[int, YearCounts]] = field(
        default_factory=lambda: defaultdict(_nested_year_counts)
    )
    stats: CountStats = field(default_factory=CountStats)

    def year(self, fips: str, year: int) -> YearCounts:
        """Return one county's counts for one school year (empty when none)."""
        return self.counties.get(fips, {}).get(year, YearCounts())


def count_rows(
    tally: Tally,
    year: int,
    rows: Iterable[EventRow],
    catalog: ZoneCountyCatalog,
    counties: CountyList,
) -> None:
    """Add one school year's rows to ``tally``."""
    days_in_year = frozenset(school_days(year))
    for row in rows:
        tally.stats.rows += 1
        targets = catalog.counties(row.ugc, row.product_issued.date())
        if not targets:
            tally.stats.rows_without_county += 1
            continue
        counted = False
        for fips in sorted(targets):
            county = counties.counties.get(fips)
            if county is None:
                tally.stats.unknown_counties[fips] += 1
                continue
            tally.stats.county_rows += 1
            found = counted_days(row.begin, row.end, row.product_issued, county.time_zones)
            hits = found & days_in_year
            if hits:
                by_day = tally.counties[fips][year].by_code[row.code]
                for day in hits:
                    by_day[day].add(row.ugc)
                counted = True
        if counted:
            tally.stats.rows_counted += 1


def count_years(
    files: Sequence[SchoolYearFile], catalog: ZoneCountyCatalog, counties: CountyList
) -> Tally:
    """Count every school year's rows."""
    tally = Tally(years=[file.year for file in files])
    for file in files:
        count_rows(tally, file.year, file.rows, catalog, counties)
    return tally


@dataclass(frozen=True, slots=True)
class CountyDays:
    """One county's averages over the school years counted for it."""

    fips: str
    days_per_year: float
    """Weighted distinct school days per school year counted (the metric)."""
    any_days_per_year: float
    """Distinct school days per school year under any closure-type code, unweighted."""
    whole_county_days_per_year: float
    """As ``days_per_year``, counting only whole-county days (a diagnostic)."""
    subset_days_per_year: Mapping[str, float]
    """Named code subset to its weighted days per year (only those codes counted)."""
    code_days: Mapping[str, int]
    """Distinct school days per code over the school years counted (unweighted)."""
    by_year: Mapping[int, tuple[float, int] | None]
    """School year to (weighted days, unweighted days); ``None`` for a year left out."""
    drivers: Mapping[str, tuple[int, int]]
    """UGC to (days it covered the county, days it was the only UGC that did)."""
    years_counted: tuple[int, ...] = ()
    """The school years averaged (every year of the tally but those left out)."""

    @property
    def weighted_days_total(self) -> float:
        """Weighted days summed over the school years counted."""
        return sum(value[0] for value in self.by_year.values() if value is not None)

    @property
    def years_left_out(self) -> tuple[int, ...]:
        """The school years left out of the county's average."""
        return tuple(year for year, value in self.by_year.items() if value is None)

    def code_days_per_year(self, code: str) -> float:
        """Return ``code``'s distinct school days per school year counted."""
        return self.code_days[code] / len(self.years_counted)


def whole_days(counts: YearCounts, zones_on: "ZonesOnDay", fips: str) -> dict[str, set[date]]:
    """Return, per code, the days the code covered all of the county's zones (or its UGC)."""
    whole: dict[str, set[date]] = {}
    for code, days in counts.by_code.items():
        kept: set[date] = set()
        for day, ugcs in days.items():
            if any(ugc[2] == "C" for ugc in ugcs):
                kept.add(day)
                continue
            zones = zones_on(fips, day)
            if zones and zones <= ugcs:
                kept.add(day)
        whole[code] = kept
    return whole


class ZonesOnDay:
    """A county's zones in the correlation release in effect on a day."""

    def __init__(self, catalog: ZoneCountyCatalog) -> None:
        self.catalog = catalog
        self._by_release: dict[str, dict[str, frozenset[str]]] = {}
        for release in catalog.releases:
            inverse: dict[str, set[str]] = defaultdict(set)
            for ugc, fips_codes in release.counties.items():
                for fips in fips_codes:
                    inverse[fips].add(ugc)
            self._by_release[release.name] = {f: frozenset(z) for f, z in inverse.items()}

    def __call__(self, fips: str, day: date) -> frozenset[str]:
        """Return the county's zones on ``day`` (the earliest release before it began)."""
        release = self.catalog.release_in_effect(day) or self.catalog.releases[0]
        return self._by_release[release.name].get(fips, frozenset())


def county_days(
    tally: Tally,
    fips: str,
    zones_on: ZonesOnDay,
    subsets: Mapping[str, frozenset[str]],
    left_out: Collection[int] = (),
) -> CountyDays:
    """Summarize one county over ``tally.years``, leaving out the school years ``left_out``.

    Raises:
        CountError: every school year of the tally is left out.
    """
    years = tuple(year for year in tally.years if year not in left_out)
    if not years:
        raise CountError(f"county {fips}: every school year is left out")
    by_year: dict[int, tuple[float, int] | None] = dict.fromkeys(tally.years)
    code_days: dict[str, int] = {code.code: 0 for code in CODES}
    subset_totals: dict[str, float] = dict.fromkeys(subsets, 0.0)
    whole_total = 0.0
    covered: Counter[str] = Counter()
    only: Counter[str] = Counter()
    for year in years:
        counts = tally.year(fips, year)
        by_year[year] = (counts.weighted(), len(counts.any_days()))
        for name, codes in subsets.items():
            subset_totals[name] += counts.weighted(codes)
        whole_total += counts.weighted(whole=whole_days(counts, zones_on, fips))
        day_ugcs: dict[date, set[str]] = defaultdict(set)
        for code, days in counts.by_code.items():
            code_days[code] += len(days)
            for day, ugcs in days.items():
                day_ugcs[day] |= ugcs
        for ugcs in day_ugcs.values():
            covered.update(ugcs)
            if len(ugcs) == 1:
                only.update(ugcs)
    count = len(years)
    counted = [value for value in by_year.values() if value is not None]
    return CountyDays(
        fips=fips,
        days_per_year=sum(value for value, _ in counted) / count,
        any_days_per_year=sum(days for _, days in counted) / count,
        whole_county_days_per_year=whole_total / count,
        subset_days_per_year={name: total / count for name, total in subset_totals.items()},
        code_days=code_days,
        by_year=by_year,
        drivers={ugc: (covered[ugc], only[ugc]) for ugc in sorted(covered)},
        years_counted=years,
    )


def summarize(
    tally: Tally,
    fips_codes: Iterable[str],
    zones_on: ZonesOnDay,
    subsets: Mapping[str, frozenset[str]],
    left_out: Mapping[str, Collection[int]] | None = None,
) -> dict[str, CountyDays]:
    """Return :func:`county_days` for every county in ``fips_codes``.

    ``left_out`` maps a county to the school years to leave out of its average
    (see the module docstring); a county not in it keeps every year.

    Raises:
        CountError: a county has every school year left out.
    """
    skip = left_out or {}
    return {
        fips: county_days(tally, fips, zones_on, subsets, skip.get(fips, ()))
        for fips in sorted(fips_codes)
    }
