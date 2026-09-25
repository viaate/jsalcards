"""The Iowa Environmental Mesonet (IEM) archive of NWS VTEC watches, warnings and advisories.

IEM keeps every VTEC event the NWS has issued. This module reads it through
three requests, each cached with its provenance:

Day files
=========

https://mesonet.agron.iastate.edu/cgi-bin/request/gis/watchwarn.py (documented
at the same URL with ``?help``) asked for one UTC day: the rows whose VTEC begin
time (``ISSUED``) falls in ``[day, day + 1)``, limited to the allowlisted
phenomena/significance pairs and to the contiguous states and DC, as a zipped
shapefile with:

* ``simple=1``: county and zone rows carry IEM's simplified outline of the UGC
  (of the boundary IEM had on record for that date; exact NWS boundaries come
  from :mod:`snowlight.sources.nws.boundaries` where a release covers the
  date). See :data:`SIMPLIFIED_TOLERANCE` for how far an outline can be from
  the boundary it was made from;
* ``addsvs=1``: storm-based warnings carry one polygon row per polygon version,
  each valid from ``POLY_BEG`` to ``POLY_END``, so a warning that the forecaster
  shrank over time is matched against the polygon that was in force. Every
  version carries its event's begin time as ``ISSUED``, so all of them come
  with the day the event began.

Each row is either ``GTYPE = "P"`` (a storm-based polygon) or ``GTYPE = "C"``
(one county or zone, ``NWS_UGC``, of a county/zone-based event). ``ISSUED`` and
``EXPIRED`` are that row's in-effect span as IEM finally recorded it (a
cancellation or an upgrade ends it early; a row whose ``EXPIRED`` is not after
``ISSUED`` never took effect). Times are ``YYYYMMDDHHMM`` in UTC.

A day file cannot hold every row that began that day. IEM keeps its tables by
VTEC year and answers a request whose ``sts`` and ``ets`` fall in one calendar
year from that year's table alone (``watchwarn.py`` source, 2026), so a row that
begins in January of an event numbered in the previous year (a warning issued
on 31 December for New Year's Day, say) is missing from its day file: on
2025-01-01 the day file has 69 rows, while a request from 2024-12-31 to
2025-01-02 holds 274 rows that began on 2025-01-01. The 31 December file spans
two years and is complete. :mod:`snowlight.weather.history` fetches those
events through range files (below).

Snapshots
=========

https://mesonet.agron.iastate.edu/api/1/vtec/events_status.json?valid=<time>
lists, from IEM's table of all years, every event with a county or zone row
whose product was issued by that time and whose ``expire`` is not before it:
the events in effect, or announced and pending, at that moment, however long
ago they began (``watchwarn.py``'s own point-in-time option only looks back 30
days and reads one year's table). One row per event and VTEC status, with the
earliest begin time, the latest expiry and the first product id of the listed
rows, and the names of their counties and zones with their state in brackets.
:class:`SnapshotEvent` merges an event's rows.

Range files
===========

``watchwarn.py`` again, for one forecast office (``location_group=wfo``) and one
phenomena/significance pair over whole months, otherwise asked like a day file.
They hold every row of the events a snapshot names (see
:mod:`snowlight.weather.history`); a range that spans two calendar years is
answered from the table of all years.

Caching
=======

Files are cached under ``<cache>/mesonet.agron.iastate.edu/``: day files at
``watchwarn/<YYYY>/<date>.zip``, snapshots at
``events_status/<YYYY>/<YYYY-MM-DD>T<HHMM>Z.json`` and range files at
``watchwarn-wfo/<WFO>/<PP>.<S>/<first>_<end>.zip``. Events keep changing while
they are in effect, so a file is *provisional* until it has been fetched at
least :data:`FINAL_AFTER` after the time it covers ended (the day, the snapshot
time, the range); a provisional copy is fetched again once it is older than an
hour. A final copy is never fetched again.
"""

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import urlencode

import numpy as np
import shapely

from snowlight.sources.nws.http import CachedFile, HttpCache, parse_iso_utc
from snowlight.sources.nws.shapefile import Polygonal, ShapefileError, read_zip

_STAMP = re.compile(r"\d{12}")
_PRODUCT_TIME = re.compile(r"(\d{12})-")
_STATE_IN_LOCATION = re.compile(r"\[([A-Z]{2})\]")
_OFFICE = re.compile(r"[A-Z]{3}")
_HOST = "mesonet.agron.iastate.edu"
WATCHWARN_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/gis/watchwarn.py"
EVENTS_STATUS_URL = "https://mesonet.agron.iastate.edu/api/1/vtec/events_status.json"
FINAL_AFTER = timedelta(days=21)
PROVISIONAL_MAX_AGE = timedelta(hours=1)

SIMPLIFIED_GRID = 0.01
"""The grid (degrees) that IEM's simplified outlines put their vertices on."""
_GRID_NOISE = 1e-6  # in grid units: decimal coordinates stored as binary floats

SIMPLIFIED_TOLERANCE = 0.0075
"""How far (degrees) the boundary a simplified outline was made from can be from it.

IEM does not document its simplification, so it was measured, and
``tests/weather/test_nws_iem_outlines.py`` keeps the evidence on real rows:

* 99% of the UGC outlines in 119 day files from 2024 to 2026 have their
  vertices on the 0.01° grid (:data:`SIMPLIFIED_GRID`), apart from the points
  where a repaired ring crossed itself. Moving each vertex to the nearest grid
  point moves it at most half a grid diagonal (0.00707°), and no point of an
  edge moves farther than its ends, so every point of the outline is within
  0.00707° of the true boundary, and a point farther than that from the outline
  is on the same side of the true boundary, except inside parts and holes
  narrower than the grid, which the repair drops altogether (thin slivers,
  small islands, narrow holes). Against IEM's full-resolution rows for 2025-01-21 (1,847 UGCs),
  every outline was within 0.00705° of its boundary.
* The other 1% (new or redrawn zones) are not on the grid; those compared with
  IEM's full-resolution rows were within 0.003° of them.

0.0075° adds a margin to the 0.00707° bound. Dropped parts and holes are left to
the nearest NWS release (the "hint" in :mod:`snowlight.weather.index`), which
settles them wherever that release has the zone as it was. Where the zone was
redrawn in between by less than the grid (IEM's 2025-01-21 TXZ313 leaves out a
strip that z_18mr25 includes), neither can see the change.
"""


class ArchiveFormatError(ValueError):
    """A day file, range file or snapshot does not have the documented columns or values."""


@dataclass(frozen=True, slots=True)
class ArchiveRow:
    """One row of a day file: a polygon version or a county/zone of one VTEC event."""

    index: int
    wfo: str
    phenomena: str
    significance: str
    etn: int
    vtec_year: int
    status: str
    gtype: str
    ugc: str | None
    issued: datetime | None
    expired: datetime | None
    polygon_begin: datetime | None
    polygon_end: datetime | None
    product_id: str
    geometry: Polygonal | None

    @property
    def event_key(self) -> str:
        """The VTEC event this row belongs to, e.g. ``DMX.TO.W.0034.2024``."""
        return f"{self.wfo}.{self.phenomena}.{self.significance}.{self.etn:04d}.{self.vtec_year}"


@dataclass(frozen=True, slots=True)
class ArchiveDay:
    """The rows IEM returned for one UTC day, and the file they came from."""

    day: date
    rows: tuple[ArchiveRow, ...]
    file: CachedFile
    final: bool


@dataclass(frozen=True, slots=True)
class ArchiveRange:
    """The rows IEM returned for one office and VTEC code over ``[first, end)``."""

    wfo: str
    phenomena: str
    significance: str
    first: date
    end: date
    rows: tuple[ArchiveRow, ...]
    file: CachedFile
    final: bool

    @property
    def label(self) -> str:
        """How traces name this file, e.g. ``range HGX.FL.W 2024-04-01..2024-06-01``."""
        code = f"{self.wfo}.{self.phenomena}.{self.significance}"
        return f"range {code} {self.first.isoformat()}..{self.end.isoformat()}"


@dataclass(frozen=True, slots=True)
class SnapshotEvent:
    """One event a snapshot lists, its rows there merged.

    ``first`` is the earliest begin time or product issuance time among the
    listed rows (``None`` when IEM gave neither), ``last_expire`` the latest
    expiry, and ``states`` the state codes of the listed counties and zones
    (empty when none was given, as for offshore marine zones).
    """

    wfo: str
    phenomena: str
    significance: str
    etn: int
    vtec_year: int
    first: datetime | None
    last_expire: datetime | None
    states: frozenset[str]

    @property
    def event_key(self) -> str:
        """The VTEC event, keyed as :attr:`ArchiveRow.event_key`."""
        return f"{self.wfo}.{self.phenomena}.{self.significance}.{self.etn:04d}.{self.vtec_year}"


@dataclass(frozen=True, slots=True)
class ArchiveSnapshot:
    """The events IEM lists as in effect or pending at ``at``, and the file they came from."""

    at: datetime
    events: tuple[SnapshotEvent, ...]
    file: CachedFile
    final: bool


def day_url(day: date, codes: Iterable[tuple[str, str]], states: Iterable[str]) -> str:
    """Return the watchwarn.py request for events that began on UTC ``day``."""
    pairs = sorted(set(codes))
    if not pairs:
        raise ValueError("at least one phenomena/significance pair is required")
    query = {
        "accept": "shapefile",
        "sts": f"{day.isoformat()}T00:00Z",
        "ets": f"{(day + timedelta(days=1)).isoformat()}T00:00Z",
        "limitps": "1",
        "phenomena": ",".join(phenomena for phenomena, _ in pairs),
        "significance": ",".join(significance for _, significance in pairs),
        "location_group": "states",
        "states": ",".join(sorted(set(states))),
        "simple": "1",
        "addsvs": "1",
    }
    return f"{WATCHWARN_URL}?{urlencode(query, safe=',:')}"


def snapshot_url(at: datetime) -> str:
    """Return the request for the events in effect or pending at ``at`` (to the minute)."""
    moment = at.astimezone(UTC)
    return f"{EVENTS_STATUS_URL}?valid={moment:%Y-%m-%dT%H:%M}Z"


def range_url(wfo: str, phenomena: str, significance: str, first: date, end: date) -> str:
    """Return the watchwarn.py request for one office and code, rows beginning in ``[first, end)``.

    Raises:
        ValueError: ``wfo`` is not a three-letter office id, or the range is empty.
    """
    if not _OFFICE.fullmatch(wfo):
        raise ValueError(f"{wfo!r} is not a three-letter forecast office id")
    if end <= first:
        raise ValueError("the range must end after it starts")
    query = {
        "accept": "shapefile",
        "sts": f"{first.isoformat()}T00:00Z",
        "ets": f"{end.isoformat()}T00:00Z",
        "limitps": "1",
        "phenomena": phenomena,
        "significance": significance,
        "location_group": "wfo",
        "wfo": wfo,
        "simple": "1",
        "addsvs": "1",
    }
    return f"{WATCHWARN_URL}?{urlencode(query, safe=',:')}"


def _time(value: object, field: str, index: int) -> datetime | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not _STAMP.fullmatch(value):
        raise ArchiveFormatError(f"row {index}: {field} {value!r} is not YYYYMMDDHHMM")
    try:
        return datetime.strptime(value, "%Y%m%d%H%M").replace(tzinfo=UTC)
    except ValueError as error:
        raise ArchiveFormatError(f"row {index}: {field} {value!r} is not a time") from error


def _text(attrs: dict[str, str | float | None], field: str, index: int) -> str:
    value = attrs.get(field)
    if not isinstance(value, str):
        raise ArchiveFormatError(f"row {index}: column {field} is missing")
    return value


def _int(attrs: dict[str, str | float | None], field: str, index: int) -> int:
    value = attrs.get(field)
    if not isinstance(value, float) or not value.is_integer():
        raise ArchiveFormatError(f"row {index}: column {field} is not a whole number")
    return int(value)


def on_simplified_grid(geometry: Polygonal, share: float = 0.95) -> bool:
    """Whether at least ``share`` of the outline's vertices lie on :data:`SIMPLIFIED_GRID`."""
    scaled = shapely.get_coordinates(geometry) / SIMPLIFIED_GRID
    off = np.abs(scaled - np.round(scaled)) > _GRID_NOISE
    return bool(np.mean(~off.any(axis=1)) >= share) if scaled.size else False


def read_day_file(path: Path) -> list[ArchiveRow]:
    """Read the rows of a cached day file.

    Raises:
        ArchiveFormatError: the shapefile is malformed or lacks a documented column.
    """
    try:
        records = read_zip(path)
    except ShapefileError as error:
        raise ArchiveFormatError(f"{path.name}: {error}") from error
    rows: list[ArchiveRow] = []
    for record in records:
        attrs, index = record.attributes, record.index
        gtype = _text(attrs, "GTYPE", index)
        ugc = _text(attrs, "NWS_UGC", index) or None
        if gtype not in {"P", "C"} or (gtype == "C") != (ugc is not None):
            raise ArchiveFormatError(f"row {index}: GTYPE {gtype!r} with NWS_UGC {ugc!r}")
        rows.append(
            ArchiveRow(
                index=index,
                wfo=_text(attrs, "WFO", index),
                phenomena=_text(attrs, "PHENOM", index),
                significance=_text(attrs, "SIG", index),
                etn=_int(attrs, "ETN", index),
                vtec_year=_int(attrs, "VTEC_YR", index),
                status=_text(attrs, "STATUS", index),
                gtype=gtype,
                ugc=ugc,
                issued=_time(attrs.get("ISSUED"), "ISSUED", index),
                expired=_time(attrs.get("EXPIRED"), "EXPIRED", index),
                polygon_begin=_time(attrs.get("POLY_BEG"), "POLY_BEG", index),
                polygon_end=_time(attrs.get("POLY_END"), "POLY_END", index),
                product_id=_text(attrs, "PROD_ID", index),
                geometry=record.geometry,
            )
        )
    return rows


def _snapshot_time(value: object, field: str, index: int) -> datetime | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ArchiveFormatError(f"snapshot row {index}: {field} {value!r} is not a timestamp")
    try:
        return parse_iso_utc(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ArchiveFormatError(f"snapshot row {index}: {field} {value!r}: {error}") from error


def _snapshot_int(row: dict[str, object], field: str, index: int) -> int:
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ArchiveFormatError(f"snapshot row {index}: {field} {value!r} is not a whole number")
    return value


def _snapshot_text(row: dict[str, object], field: str, index: int) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value:
        raise ArchiveFormatError(f"snapshot row {index}: {field} is missing")
    return value


def _product_time(product_id: object) -> datetime | None:
    """The issuance time IEM puts at the head of its product ids (``YYYYMMDDHHMM-CCCC-...``)."""
    if not isinstance(product_id, str):
        return None
    found = _PRODUCT_TIME.match(product_id)
    return None if found is None else _time(found.group(1), "product id", -1)


def _earliest(*moments: datetime | None) -> datetime | None:
    known = [moment for moment in moments if moment is not None]
    return min(known) if known else None


def _latest(*moments: datetime | None) -> datetime | None:
    known = [moment for moment in moments if moment is not None]
    return max(known) if known else None


def read_snapshot(path: Path) -> list[SnapshotEvent]:
    """Read a cached snapshot, one :class:`SnapshotEvent` per event (sorted by key).

    Raises:
        ArchiveFormatError: the file is not the documented JSON table.
    """
    try:
        document = json.loads(path.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ArchiveFormatError(f"{path.name}: not JSON: {error}") from error
    rows = document.get("data") if isinstance(document, dict) else None
    if not isinstance(rows, list):
        raise ArchiveFormatError(f"{path.name}: no data table")
    events: dict[str, SnapshotEvent] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ArchiveFormatError(f"snapshot row {index} is not an object")
        locations = row.get("locations")
        event = SnapshotEvent(
            wfo=_snapshot_text(row, "wfo", index),
            phenomena=_snapshot_text(row, "phenomena", index),
            significance=_snapshot_text(row, "significance", index),
            etn=_snapshot_int(row, "eventid", index),
            vtec_year=_snapshot_int(row, "year", index),
            first=_earliest(
                _snapshot_time(row.get("issue"), "issue", index),
                _product_time(row.get("issue_product_id")),
            ),
            last_expire=_snapshot_time(row.get("expire"), "expire", index),
            states=frozenset(
                _STATE_IN_LOCATION.findall(locations) if isinstance(locations, str) else ()
            ),
        )
        known = events.get(event.event_key)
        if known is not None:
            event = SnapshotEvent(
                wfo=event.wfo,
                phenomena=event.phenomena,
                significance=event.significance,
                etn=event.etn,
                vtec_year=event.vtec_year,
                first=_earliest(known.first, event.first),
                last_expire=_latest(known.last_expire, event.last_expire),
                states=known.states | event.states,
            )
        events[event.event_key] = event
    return [events[key] for key in sorted(events)]


@dataclass(frozen=True, slots=True)
class Freshness:
    """When a cached archive file is final, and how long a provisional one is trusted."""

    final_after: timedelta = FINAL_AFTER
    provisional_max_age: timedelta = PROVISIONAL_MAX_AGE


class IemArchive:
    """Fetches, caches and reads IEM files for a fixed set of VTEC codes and states."""

    def __init__(
        self,
        cache: HttpCache,
        cache_dir: Path,
        codes: Sequence[tuple[str, str]],
        states: Iterable[str],
        freshness: Freshness | None = None,
    ) -> None:
        self.cache = cache
        self.cache_dir = cache_dir
        self.codes = tuple(sorted(set(codes)))
        self.states = tuple(sorted(set(states)))
        self.freshness = freshness or Freshness()
        self._days: dict[date, ArchiveDay] = {}
        self._snapshots: dict[datetime, ArchiveSnapshot] = {}
        self._ranges: dict[tuple[str, str, str, date, date], ArchiveRange] = {}

    def path_for(self, day: date) -> Path:
        """Return where the file for ``day`` is cached."""
        return self.cache_dir / _HOST / "watchwarn" / f"{day:%Y}" / f"{day.isoformat()}.zip"

    def snapshot_path(self, at: datetime) -> Path:
        """Return where the snapshot at ``at`` is cached."""
        moment = at.astimezone(UTC)
        return (
            self.cache_dir
            / _HOST
            / "events_status"
            / f"{moment:%Y}"
            / f"{moment:%Y-%m-%dT%H%M}Z.json"
        )

    def range_path(
        self, wfo: str, phenomena: str, significance: str, first: date, end: date
    ) -> Path:
        """Return where a range file is cached."""
        folder = self.cache_dir / _HOST / "watchwarn-wfo" / wfo / f"{phenomena}.{significance}"
        return folder / f"{first.isoformat()}_{end.isoformat()}.zip"

    def _final_after(self, covered_until: datetime, file: CachedFile) -> bool:
        checked = parse_iso_utc(file.provenance.checked_at)
        return checked >= covered_until + self.freshness.final_after

    def _is_final(self, day: date, file: CachedFile) -> bool:
        return self._final_after(
            datetime.combine(day + timedelta(days=1), time(0), tzinfo=UTC), file
        )

    def _fetch(self, url: str, dest: Path, covered_until: datetime) -> CachedFile:
        """Fetch ``url`` into ``dest``, trusting a final cached copy forever."""
        cached = self.cache.cached(url, dest)
        final_copy = cached is not None and self._final_after(covered_until, cached)
        return self.cache.fetch(
            url, dest, max_age=None if final_copy else self.freshness.provisional_max_age
        )

    def day(self, day: date) -> ArchiveDay:
        """Return the rows for UTC ``day``, fetching the day file when needed.

        Raises:
            ValueError: ``day`` has not started yet.
        """
        loaded = self._days.get(day)
        if loaded is not None:
            return loaded
        if datetime.combine(day, time(0), tzinfo=UTC) > self.cache.now():
            raise ValueError(f"{day} has not started yet")
        day_end = datetime.combine(day + timedelta(days=1), time(0), tzinfo=UTC)
        file = self._fetch(day_url(day, self.codes, self.states), self.path_for(day), day_end)
        loaded = ArchiveDay(
            day=day,
            rows=tuple(read_day_file(file.path)),
            file=file,
            final=self._is_final(day, file),
        )
        self._days[day] = loaded
        return loaded

    def snapshot(self, at: datetime) -> ArchiveSnapshot:
        """Return the events in effect or pending at ``at`` (to the minute), fetching when needed.

        Raises:
            ValueError: ``at`` is naive or later than now.
        """
        if at.tzinfo is None:
            raise ValueError("a snapshot time must be aware")
        moment = at.astimezone(UTC).replace(second=0, microsecond=0)
        loaded = self._snapshots.get(moment)
        if loaded is not None:
            return loaded
        if moment > self.cache.now():
            raise ValueError(f"{moment.isoformat()} is in the future")
        file = self._fetch(snapshot_url(moment), self.snapshot_path(moment), moment)
        loaded = ArchiveSnapshot(
            at=moment,
            events=tuple(read_snapshot(file.path)),
            file=file,
            final=self._final_after(moment, file),
        )
        self._snapshots[moment] = loaded
        return loaded

    def range(
        self, wfo: str, phenomena: str, significance: str, first: date, end: date
    ) -> ArchiveRange:
        """Return the rows of one office and code beginning in ``[first, end)``.

        Raises:
            ValueError: the code is not one this archive asks for, the office id
                is malformed, the range is empty, or it starts after today.
        """
        if (phenomena, significance) not in self.codes:
            raise ValueError(f"{phenomena}.{significance} is not an archived code")
        key = (wfo, phenomena, significance, first, end)
        loaded = self._ranges.get(key)
        if loaded is not None:
            return loaded
        url = range_url(wfo, phenomena, significance, first, end)
        if datetime.combine(first, time(0), tzinfo=UTC) > self.cache.now():
            raise ValueError(f"{first} has not started yet")
        dest = self.range_path(wfo, phenomena, significance, first, end)
        covered_until = datetime.combine(end, time(0), tzinfo=UTC)
        file = self._fetch(url, dest, covered_until)
        loaded = ArchiveRange(
            wfo=wfo,
            phenomena=phenomena,
            significance=significance,
            first=first,
            end=end,
            rows=tuple(read_day_file(file.path)),
            file=file,
            final=self._final_after(covered_until, file),
        )
        self._ranges[key] = loaded
        return loaded

    def loaded(self) -> list[ArchiveDay]:
        """The day files read so far (and not evicted), oldest first."""
        return [self._days[day] for day in sorted(self._days)]

    def loaded_snapshots(self) -> list[ArchiveSnapshot]:
        """The snapshots read so far, oldest first."""
        return [self._snapshots[at] for at in sorted(self._snapshots)]

    def loaded_ranges(self) -> list[ArchiveRange]:
        """The range files read so far, by office, code and range."""
        return [self._ranges[key] for key in sorted(self._ranges)]

    def evict(self, before: date) -> None:
        """Forget the rows of days before ``before`` (the files stay cached on disk)."""
        for day in [day for day in self._days if day < before]:
            del self._days[day]
