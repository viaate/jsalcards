"""The IEM archive of NWS VTEC events, one CSV file per school year.

:mod:`snowlight.sources.nws.iem` reads IEM's ``watchwarn.py`` one UTC day at a
time, as zipped shapefiles with outlines, because the weather check needs
geometry. Counting closure-type days per county needs none, so this module asks
the same service (documented at
https://mesonet.agron.iastate.edu/cgi-bin/request/gis/watchwarn.py?help) for a
whole school year in one request, ``accept=csv``: every county/zone row (and
storm-based polygon row) of the closure-type codes in the contiguous states and
DC whose VTEC begin time (``utc_issue``) falls in the request window. That is
eleven requests for eleven school years instead of about 3,700 day files; the
build cross-checks the two on real days (:mod:`snowlight.weights.crosscheck`).

The window runs from 1 August to 17 June (UTC midnights): two weeks before the
first school day (15 August), so that a row that began earlier and was still in
effect is included (the build checks that no row in any file lasted that long),
and a day past the last school day (15 June) in every contiguous time zone. It
spans two calendar years, so IEM answers it from its table of all years (a
request inside one calendar year reads only that year's table and misses rows
of events numbered in the previous year; see :mod:`snowlight.sources.nws.iem`).

Columns used (the CSV has more): ``wfo``, ``phenomena``, ``significance``,
``eventid``, ``vtec_year``, ``status`` (the row's final VTEC action), ``gtype``
(``C`` county or zone row, ``P`` storm-based polygon), ``ugc``, ``utc_issue`` and
``utc_expire`` (the row's in-effect span as IEM finally recorded it: a
cancellation or an upgrade ends it early), ``utc_prodissue`` (when the product
that created the row was issued), ``product_id`` and ``area2d`` (the area, in
km², of the zone or county outline IEM joined to the row: the outline of that
UGC as it stood when the product was issued, measured in the US National Atlas
Equal Area projection; :mod:`snowlight.weights.zonepolys` uses it to tell which
version of a zone a row was issued for). Times are ``YYYY-MM-DD HH:MM`` in UTC.

Rows ended before they began
============================

A cancellation or an upgrade that comes before a row's begin time leaves IEM a
row whose ``utc_expire`` (the time of the cancelling or upgrading product) is
not after its ``utc_issue``: the event never took effect there. Such a row is
kept, because it may still have been standing at 6 AM on the day it was issued
for, which the 6 AM rule counts (:func:`snowlight.weights.count.row_counts_on`):
a Winter Storm Warning issued at 3 PM for 10 AM the next day and cancelled at
7 AM had been issued for that day by 6 AM. Its ``end`` is then the time it was
withdrawn, and it is reported (``ReadStats.ended_before_start``).

Tropical rows left open
=======================

Tropical Storm and Hurricane Warnings (from the tropical cyclone VTEC products,
TCV) are issued "until further notice": their VTEC end time is unset and the
warning lasts until a product cancels it. IEM stores such a row with a
placeholder expiry (its ``utc_init_expire`` is the product time plus a fixed
span: 6 days in 2016, 21 days in 2021). When no product ever ended a row (its
final ``status`` is not ``CAN``, ``EXP`` or ``UPG``), that placeholder is all
IEM has: Hermine's ``NHC.TR.W.1009.2016`` has five zones recorded until
2016-09-10 06:00 although every other zone of the event was cancelled by
2016-09-06 18:00, and Ida's ``LIX.TR.W.1009.2021`` five zones until 2021-09-20
although the rest ended by 2021-08-30 21:19. :func:`close_open_tropical` ends
such a row when the last explicitly ended row of its event ended, and reports it;
a row whose event has no explicitly ended row keeps its span and is reported.

Files are cached at ``<cache>/mesonet.agron.iastate.edu/watchwarn-csv/<first
year>-<last year>.csv``. A file is provisional until it has been fetched at
least :data:`~snowlight.sources.nws.iem.FINAL_AFTER` after its window ended
(events are still being updated until then) and is fetched again once it is an
hour old; a final copy is never fetched again.
"""

import csv
import io
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time
from pathlib import Path
from urllib.parse import urlencode

from snowlight.sources.nws.http import CachedFile, parse_iso_utc
from snowlight.sources.nws.iem import FINAL_AFTER, PROVISIONAL_MAX_AGE, WATCHWARN_URL
from snowlight.weather.hazards import CONUS_STATES
from snowlight.weights.cache import WeightsCache
from snowlight.weights.codes import BY_CODE, code_pairs

FIRST_SCHOOL_YEAR = 2015
LAST_SCHOOL_YEAR = 2025
"""School years 2015-16 through 2025-26, named by the year they start."""
REQUEST_START = (8, 1)
REQUEST_END = (6, 17)
REQUIRED_COLUMNS = (
    "wfo",
    "utc_issue",
    "utc_expire",
    "utc_prodissue",
    "phenomena",
    "gtype",
    "significance",
    "eventid",
    "status",
    "ugc",
    "product_id",
    "vtec_year",
)
_HOST = "mesonet.agron.iastate.edu"
ENDING_ACTIONS = frozenset({"CAN", "EXP", "UPG"})
"""VTEC actions that end a row: cancelled, expired, upgraded."""
UNTIL_FURTHER_NOTICE_CODES = frozenset({"HU.W", "TR.W"})


class ArchiveCsvError(ValueError):
    """A school-year file does not have the documented columns or values."""


def school_year_label(year: int) -> str:
    """Return ``2015-16`` for the school year starting in 2015."""
    return f"{year}-{(year + 1) % 100:02d}"


def school_years() -> list[int]:
    """Return the school years counted, by starting year."""
    return list(range(FIRST_SCHOOL_YEAR, LAST_SCHOOL_YEAR + 1))


def request_window(year: int) -> tuple[date, date]:
    """Return the UTC dates ``[start, end)`` whose rows the school year's file holds."""
    return date(year, *REQUEST_START), date(year + 1, *REQUEST_END)


def year_url(year: int, states: Iterable[str] = CONUS_STATES) -> str:
    """Return the ``watchwarn.py`` CSV request for one school year of closure-type rows."""
    first, end = request_window(year)
    pairs = code_pairs()
    query = {
        "accept": "csv",
        "sts": f"{first.isoformat()}T00:00Z",
        "ets": f"{end.isoformat()}T00:00Z",
        "limitps": "1",
        "phenomena": ",".join(phenomena for phenomena, _ in pairs),
        "significance": ",".join(significance for _, significance in pairs),
        "location_group": "states",
        "states": ",".join(sorted(set(states))),
    }
    return f"{WATCHWARN_URL}?{urlencode(query, safe=',:')}"


def year_path(root: Path, year: int) -> Path:
    """Return where the school year's file is cached."""
    return root / _HOST / "watchwarn-csv" / f"{year}-{year + 1}.csv"


@dataclass(frozen=True, slots=True)
class EventRow:
    """One county or zone row of one VTEC event."""

    wfo: str
    code: str
    """``PP.S``, e.g. ``WS.W``."""
    etn: int
    vtec_year: int
    status: str
    ugc: str
    begin: datetime
    end: datetime
    product_issued: datetime
    product_id: str
    area_km2: float | None = None
    """IEM's ``area2d``: the area of the UGC outline joined to the row (``None`` when blank)."""

    @property
    def event_key(self) -> str:
        """The VTEC event, e.g. ``BOX.WS.W.0001.2025``."""
        return f"{self.wfo}.{self.code}.{self.etn:04d}.{self.vtec_year}"

    @property
    def state(self) -> str:
        """The two-letter state (or marine area) prefix of the UGC."""
        return self.ugc[:2]


@dataclass(frozen=True, slots=True)
class ClosedRow:
    """A tropical row left open, and the end :func:`close_open_tropical` gave it."""

    event_key: str
    ugc: str
    status: str
    recorded_end: datetime
    end: datetime | None
    """The event's last explicit end, or ``None`` when the row was kept as recorded."""


@dataclass(slots=True)
class ReadStats:
    """What reading a school-year file kept and skipped."""

    rows: int = 0
    kept: int = 0
    polygon_rows: int = 0
    outside_states: Counter[str] = field(default_factory=Counter)
    ended_before_start: int = 0
    """Rows withdrawn (cancelled or upgraded) before they began; kept (see the module docstring)."""
    polygon_events: Counter[str] = field(default_factory=Counter)
    """Storm-based polygon rows (skipped here) by event key (``WFO.PP.S.ETN.YEAR``)."""
    by_code: Counter[str] = field(default_factory=Counter)
    longest_row_days: float = 0.0
    closed_tropical: list[ClosedRow] = field(default_factory=list)


def _time(value: str, column: str, line: int) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
    except ValueError as error:
        raise ArchiveCsvError(f"line {line}: {column} {value!r} is not YYYY-MM-DD HH:MM") from error


def _int(value: str, column: str, line: int) -> int:
    try:
        return int(value)
    except ValueError as error:
        raise ArchiveCsvError(f"line {line}: {column} {value!r} is not a whole number") from error


def _area(value: str | None, line: int) -> float | None:
    if value is None or value == "":
        return None
    try:
        area = float(value)
    except ValueError as error:
        raise ArchiveCsvError(f"line {line}: area2d {value!r} is not a number") from error
    if not area > 0:
        raise ArchiveCsvError(f"line {line}: area2d {value!r} is not positive")
    return area


def read_rows(text: str, states: Iterable[str] = CONUS_STATES) -> tuple[list[EventRow], ReadStats]:
    """Read a school-year CSV into the county/zone rows of the contiguous states.

    Kept: ``gtype`` ``C`` rows of a closure-type code whose UGC is in ``states``,
    including rows withdrawn before they began (counted in
    ``stats.ended_before_start``; see the module docstring). Skipped and
    counted: storm-based polygon rows (their counties come as ``C`` rows of the
    same event) and rows outside ``states`` (marine zones, Alaska, Hawaii,
    Puerto Rico and the like).

    Raises:
        ArchiveCsvError: a documented column is missing or a value is malformed.
    """
    wanted = frozenset(states)
    reader = csv.DictReader(io.StringIO(text))
    missing = [column for column in REQUIRED_COLUMNS if column not in (reader.fieldnames or ())]
    if missing:
        raise ArchiveCsvError(f"missing columns {missing}")
    rows: list[EventRow] = []
    stats = ReadStats()
    for line, record in enumerate(reader, start=2):
        stats.rows += 1
        code = f"{record['phenomena']}.{record['significance']}"
        if code not in BY_CODE:
            raise ArchiveCsvError(f"line {line}: {code} was not asked for")
        gtype = record["gtype"]
        if gtype == "P":
            stats.polygon_rows += 1
            etn = _int(record["eventid"], "eventid", line)
            stats.polygon_events[f"{record['wfo']}.{code}.{etn:04d}.{record['vtec_year']}"] += 1
            continue
        ugc = record["ugc"]
        if gtype != "C" or len(ugc) != 6 or ugc[2] not in {"C", "Z"}:  # noqa: PLR2004
            raise ArchiveCsvError(f"line {line}: gtype {gtype!r} with ugc {ugc!r}")
        if ugc[:2] not in wanted:
            stats.outside_states[ugc[:2]] += 1
            continue
        begin = _time(record["utc_issue"], "utc_issue", line)
        end = _time(record["utc_expire"], "utc_expire", line)
        row = EventRow(
            wfo=record["wfo"],
            code=code,
            etn=_int(record["eventid"], "eventid", line),
            vtec_year=_int(record["vtec_year"], "vtec_year", line),
            status=record["status"],
            ugc=ugc,
            begin=begin,
            end=end,
            product_issued=_time(record["utc_prodissue"], "utc_prodissue", line),
            product_id=record["product_id"],
            area_km2=_area(record.get("area2d"), line),
        )
        rows.append(row)
    rows = close_open_tropical(rows, stats)
    for row in rows:
        stats.kept += 1
        stats.by_code[row.code] += 1
        if row.end <= row.begin:
            stats.ended_before_start += 1
        span = (row.end - row.begin).total_seconds() / 86400
        stats.longest_row_days = max(stats.longest_row_days, span)
    return rows, stats


def close_open_tropical(rows: Sequence[EventRow], stats: ReadStats) -> list[EventRow]:
    """End the tropical rows no product ended (see the module docstring).

    A row of :data:`UNTIL_FURTHER_NOTICE_CODES` whose final status is not an
    ending action and whose recorded end is later than the latest end among the
    explicitly ended rows of its event is ended then (if that is before its
    begin time, it becomes a row withdrawn before it began, which the 6 AM rule
    reads like any other). Every such row is recorded in ``stats.closed_tropical``.
    """
    explicit: dict[str, datetime] = {}
    for row in rows:
        if row.code in UNTIL_FURTHER_NOTICE_CODES and row.status in ENDING_ACTIONS:
            known = explicit.get(row.event_key)
            explicit[row.event_key] = row.end if known is None else max(known, row.end)
    kept: list[EventRow] = []
    for row in rows:
        if row.code not in UNTIL_FURTHER_NOTICE_CODES or row.status in ENDING_ACTIONS:
            kept.append(row)
            continue
        last = explicit.get(row.event_key)
        if last is None:
            stats.closed_tropical.append(
                ClosedRow(row.event_key, row.ugc, row.status, row.end, None)
            )
            kept.append(row)
            continue
        if row.end <= last:
            kept.append(row)
            continue
        stats.closed_tropical.append(ClosedRow(row.event_key, row.ugc, row.status, row.end, last))
        kept.append(replace(row, end=last))
    return kept


@dataclass(frozen=True, slots=True)
class SchoolYearFile:
    """One school year's rows and the cached file they came from."""

    year: int
    rows: tuple[EventRow, ...]
    stats: ReadStats
    file: CachedFile
    final: bool

    @property
    def label(self) -> str:
        """The school year, e.g. ``2024-25``."""
        return school_year_label(self.year)


def _is_final(year: int, file: CachedFile) -> bool:
    end = datetime.combine(request_window(year)[1], time(0), tzinfo=UTC)
    return parse_iso_utc(file.provenance.checked_at) >= end + FINAL_AFTER


def load_year(cache: WeightsCache, year: int) -> SchoolYearFile:
    """Return one school year's rows, fetching the file when it is missing or provisional.

    Raises:
        ValueError: the school year's window has not started yet.
        ArchiveCsvError: the file is malformed.
    """
    start = datetime.combine(request_window(year)[0], time(0), tzinfo=UTC)
    if start > cache.cache.now():
        raise ValueError(f"school year {school_year_label(year)} has not started")
    url, dest = year_url(year), year_path(cache.root, year)
    cached = cache.cache.cached(url, dest)
    final_copy = cached is not None and _is_final(year, cached)
    file = cache.fetch(url, dest, max_age=None if final_copy else PROVISIONAL_MAX_AGE)
    rows, stats = read_rows(file.path.read_text(encoding="utf-8"))
    return SchoolYearFile(year, tuple(rows), stats, file, _is_final(year, file))


def load_years(cache: WeightsCache, years: Sequence[int]) -> list[SchoolYearFile]:
    """Return the files of ``years`` (see :func:`load_year`)."""
    return [load_year(cache, year) for year in years]
