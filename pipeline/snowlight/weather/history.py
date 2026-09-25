"""The weather check for past dates, from the IEM archive of NWS VTEC events.

What is loaded for a window
===========================

:meth:`WarningHistory.load` gathers every archived row that can be in effect
during a UTC window ``[start, end)``, however long before it the event began
(see :mod:`snowlight.sources.nws.iem` for the three kinds of file):

1. The day files for the UTC days from ``D0`` to the day the window ends
   (capped at today), where ``D0`` is the day before ``start - lookback``. A day
   file holds the rows that began that day.
2. Snapshots of the events in effect or pending at ``S0``, midnight UTC after
   ``D0`` (the current minute if that midnight is still to come), and at
   midnight on 1 January of each year that begins after ``S0`` and no later
   than the last day file.
3. For each allowlisted event those snapshots list (in the contiguous states)
   that the day files may not hold whole, a range file with every row of its
   office and code from the month of the day before its first listed begin or
   product time to the end of the last day file's month (one file per office
   and code, from the earliest month its events need). Such an event is
   *carried*: all its rows come from the range file and none from the day
   files. That is:

   * an event listed at ``S0`` whose latest expiry there is not before
     ``start``: it may have rows that began before ``D0`` (a river flood
     warning in effect for weeks);
   * an event numbered in a VTEC year before the year of the snapshot that
     lists it: its rows that began in the later year are missing from their
     day files, which IEM answers from the later year's table.

Why nothing in effect is left out: a row in effect during the window expires
after ``start``. If it began on or after ``D0`` it is in its day file, unless
its event is numbered in an earlier year than the row began. The NWS cannot
add to an event after it ends, so such an event runs, in effect or pending,
from its first product (in the earlier year) until the row's product and the
row runs on into the window: it is listed at 1 January of the row's year when
that midnight is after ``S0`` (a snapshot is taken then), and otherwise at
``S0``, in a later year than its number either way, and is carried. If it
began before ``D0``, its product was
issued before ``S0`` (a begin time can precede its product by minutes, which
the extra day absorbs) and it had not expired at ``S0``, so ``S0`` lists its
event with a latest expiry after ``start``, and the event is carried. A carried
event's rows all began within its range file's months and IEM answers a range
across two calendar years from its table of all years (the range starts in
the event's VTEC year when that is earlier). A carried event missing from its
range file would contradict this; it is counted, and its rows are taken from
the day files. The lookback only decides which rows come from day files and
which from range files; ``check`` and ``schools`` load the same files for a
local date (see :func:`snowlight.weather.build.archive_window`).

What becomes of the rows
========================

Each row becomes an :class:`~snowlight.weather.index.AlertArea`:

* Storm-based warnings (events with ``GTYPE = "P"`` rows) are matched on their
  polygons. Each polygon version counts from ``POLY_BEG`` to ``POLY_END`` but
  only within the event's own ``ISSUED`` to ``EXPIRED`` span, so a river flood
  warning cancelled before its forecast begin time, whose polygons IEM still
  lists, never matches. The event's county rows are kept only for places
  without a point (``point_matching=False``), because the counties a polygon
  touches are wider than the polygon. An event whose polygon versions were
  never in effect is matched on its county and zone rows instead.
* An event none of whose rows has an ``EXPIRED`` after its ``ISSUED`` never
  took effect (a watch upgraded before it began, say) and gives no areas.
* County and zone rows span ``ISSUED`` to ``EXPIRED``. Their boundary is the
  NWS release in effect on the row's start date when that release has the UGC
  (``exact``). Otherwise (dates before the earliest NWS release still served)
  it is the simplified outline IEM keeps for that date: ``approximate``, with
  :data:`~snowlight.sources.nws.iem.SIMPLIFIED_TOLERANCE` as its tolerance and
  the UGC's boundary in the nearest NWS release as its hint, so that a school
  near the outline, or in a part of the zone the outline dropped, is reported
  as ``uncertain`` instead of not covered (see :mod:`snowlight.weather.index`).
  Without any boundary, county rows match on the county FIPS alone. A county
  row always also carries its FIPS code (from the NWS county files: the code is
  part of the county, not of its drawn boundary), and for approximate county
  rows that code, not the outline, decides for schools whose county code the
  NWS county files use (:meth:`WarningHistory.known_counties`).

Rows without a start or end time, rows outside the contiguous states and rows
whose code is not allowlisted are skipped and counted in :attr:`WarningHistory.skipped`.
:attr:`WarningHistory.outlines` counts the distinct approximate outlines used by
whether they are on IEM's 0.01° grid, and the approximate rows by whether an NWS
hint was found.

Typical use, for the schools closed on one local date::

    with HttpCache(make_client()) as cache:
        catalog = BoundaryCatalog(cache, DEFAULT_CACHE_DIR)
        history = WarningHistory(make_archive(cache, DEFAULT_CACHE_DIR), catalog)
        window = LocalWindow(day)
        index = history.index(*archive_window(window))  # one span for every US zone
        matches = index.check_local(
            county_fips="19153", lat=41.59, lon=-93.62, window=window, zone="America/Chicago"
        )

(``make_archive``, ``archive_window`` and ``DEFAULT_CACHE_DIR`` are in
:mod:`snowlight.weather.build`; ``index.check_many`` checks a whole table of
schools at once.)
"""

from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta

import shapely

from snowlight.output import JSONValue
from snowlight.sources.nws.boundaries import BoundaryCatalog, BoundaryKind, BoundarySet, ugc_kind
from snowlight.sources.nws.http import iso_utc
from snowlight.sources.nws.iem import (
    SIMPLIFIED_TOLERANCE,
    ArchiveDay,
    ArchiveRange,
    ArchiveRow,
    ArchiveSnapshot,
    IemArchive,
    SnapshotEvent,
    on_simplified_grid,
)
from snowlight.sources.nws.shapefile import Polygonal
from snowlight.weather.hazards import CONUS_STATES, alert_type_for_code
from snowlight.weather.index import AlertArea, AlertInfo, AlertMatch, WeatherIndex

DEFAULT_LOOKBACK = timedelta(days=21)
RETROACTIVE_MARGIN = timedelta(days=1)
"""The extra day file before ``start - lookback``: a VTEC begin time can precede
the product that sets it (by minutes, in practice)."""

type Located = tuple[ArchiveRow, str]
"""An archive row and the trace naming where it came from."""


def _event_span(rows: Sequence[ArchiveRow]) -> tuple[datetime, datetime] | None:
    """Return when an event was in effect anywhere: the hull of its rows' valid spans."""
    spans = [
        (row.issued, row.expired)
        for row in rows
        if row.issued is not None and row.expired is not None and row.expired > row.issued
    ]
    if not spans:
        return None
    return min(start for start, _ in spans), max(end for _, end in spans)


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time(0), tzinfo=UTC)


def _next_month(day: date) -> date:
    """The first day of the month after ``day``'s."""
    return (day.replace(day=28) + timedelta(days=4)).replace(day=1)


@dataclass(frozen=True, slots=True)
class CarriedEvent:
    """An event whose rows come from a range file (see the module docstring).

    ``first`` and ``last_expire`` merge what the snapshots listed; ``reasons``
    say why the day files may not hold it whole.
    """

    key: str
    wfo: str
    phenomena: str
    significance: str
    vtec_year: int
    first: datetime | None
    last_expire: datetime | None
    listed_at: tuple[datetime, ...]
    reasons: tuple[str, ...]

    def merged(self, other: "CarriedEvent") -> "CarriedEvent":
        """Combine two listings of the same event."""
        firsts = [t for t in (self.first, other.first) if t is not None]
        lasts = [t for t in (self.last_expire, other.last_expire) if t is not None]
        return replace(
            self,
            first=min(firsts) if firsts else None,
            last_expire=max(lasts) if lasts else None,
            listed_at=tuple(sorted({*self.listed_at, *other.listed_at})),
            reasons=tuple(sorted({*self.reasons, *other.reasons})),
        )


@dataclass(frozen=True, slots=True)
class ArchiveLoad:
    """The archive files read for one window, and which file supplies each event's rows.

    ``carried`` maps each carried event to the range file its rows come from;
    ``missing`` lists carried events their range file did not hold (their rows
    are then taken from the day files).
    """

    days: tuple[ArchiveDay, ...]
    snapshots: tuple[ArchiveSnapshot, ...] = ()
    ranges: tuple[ArchiveRange, ...] = ()
    carried: Mapping[str, ArchiveRange] = field(default_factory=dict)
    missing: tuple[str, ...] = ()

    def rows(self) -> Iterator[Located]:
        """Every row to use, each event's from one kind of file only, with its trace."""
        for day in self.days:
            for row in day.rows:
                if row.event_key not in self.carried:
                    yield row, f"archive day {day.day} row {row.index} ({row.product_id})"
        for source in self.ranges:
            for row in source.rows:
                if self.carried.get(row.event_key) is source:
                    yield row, f"archive {source.label} row {row.index} ({row.product_id})"


@dataclass(slots=True)
class WarningHistory:
    """Builds weather-check indexes for past windows from the IEM archive."""

    archive: IemArchive
    catalog: BoundaryCatalog
    lookback: timedelta = DEFAULT_LOOKBACK
    skipped: Counter[str] = field(default_factory=Counter)
    outlines: Counter[str] = field(default_factory=Counter)
    carried: dict[str, CarriedEvent] = field(default_factory=dict)
    missing: set[str] = field(default_factory=set)
    _shared: dict[tuple[str, bytes], Polygonal] = field(default_factory=dict, repr=False)

    def days_for(self, start: datetime, end: datetime) -> list[date]:
        """Return the UTC days whose files are read for ``[start, end)`` (``D0`` on)."""
        if end <= start:
            raise ValueError("the window must end after it starts")
        first = (start - self.lookback - RETROACTIVE_MARGIN).astimezone(UTC).date()
        last = (end - timedelta(microseconds=1)).astimezone(UTC).date()
        today = self.archive.cache.now().date()
        last = min(last, today)
        return [first + timedelta(days=n) for n in range((last - first).days + 1)]

    def snapshot_times(self, start: datetime, end: datetime) -> list[datetime]:
        """Return ``S0`` and the New Year midnights after it, up to the last day file.

        When the first day file is today, ``S0`` would be in the future; the
        current minute stands in for it (a row that began before today and
        runs into the window is in effect now).
        """
        days = self.days_for(start, end)
        if not days:
            return []
        now = self.archive.cache.now().astimezone(UTC).replace(second=0, microsecond=0)
        first = min(_midnight(days[0] + RETROACTIVE_MARGIN), now)
        new_years = [
            _midnight(date(year, 1, 1)) for year in range(first.year + 1, days[-1].year + 1)
        ]
        return [first, *(moment for moment in new_years if first < moment <= now)]

    def _to_carry(
        self, snapshots: Sequence[ArchiveSnapshot], start: datetime
    ) -> list[CarriedEvent]:
        found: dict[str, CarriedEvent] = {}
        for n, snapshot in enumerate(snapshots):
            for event in snapshot.events:
                reasons = self._reasons(event, snapshot, first_snapshot=n == 0, start=start)
                if not reasons:
                    continue
                carried = CarriedEvent(
                    key=event.event_key,
                    wfo=event.wfo,
                    phenomena=event.phenomena,
                    significance=event.significance,
                    vtec_year=event.vtec_year,
                    first=event.first,
                    last_expire=event.last_expire,
                    listed_at=(snapshot.at,),
                    reasons=reasons,
                )
                known = found.get(carried.key)
                found[carried.key] = carried if known is None else known.merged(carried)
        return [found[key] for key in sorted(found)]

    @staticmethod
    def _reasons(
        event: SnapshotEvent, snapshot: ArchiveSnapshot, *, first_snapshot: bool, start: datetime
    ) -> tuple[str, ...]:
        """Why a listed event may be missing rows from the day files (none: it is not)."""
        if alert_type_for_code(event.phenomena, event.significance) is None:
            return ()
        if event.states and not event.states & CONUS_STATES:
            return ()
        reasons: list[str] = []
        if first_snapshot and (event.last_expire is None or event.last_expire >= start):
            reasons.append("in effect before the day files and during the window")
        if event.vtec_year < snapshot.at.year:
            reasons.append(f"numbered in {event.vtec_year}, listed in {snapshot.at.year}")
        return tuple(reasons)

    @staticmethod
    def range_for(event: CarriedEvent, last_day: date) -> tuple[date, date]:
        """The months of the range file that holds every row of ``event`` up to ``last_day``."""
        if event.first is not None:
            anchor = (event.first - RETROACTIVE_MARGIN).date()
        else:
            anchor = date(event.vtec_year - 1, 12, 1)
        first = anchor.replace(day=1)
        if event.vtec_year < first.year:
            # A range inside one later year would be answered from that year's table.
            first = date(event.vtec_year, 12, 1)
        return first, _next_month(last_day)

    def load(self, start: datetime, end: datetime) -> ArchiveLoad:
        """Fetch (or reuse) every file needed for ``[start, end)`` (see the module docstring)."""
        days = tuple(self.archive.day(day) for day in self.days_for(start, end))
        if not days:
            return ArchiveLoad(days=())
        snapshots = tuple(self.archive.snapshot(t) for t in self.snapshot_times(start, end))
        # One range file per office and code, from the earliest month any of its events needs.
        wanted: dict[tuple[str, str, str], tuple[date, date, list[str]]] = {}
        for event in self._to_carry(snapshots, start):
            known = self.carried.get(event.key)
            self.carried[event.key] = event if known is None else known.merged(event)
            first, last = self.range_for(event, days[-1].day)
            code = (event.wfo, event.phenomena, event.significance)
            earlier = wanted.get(code)
            if earlier is not None:
                first = min(first, earlier[0])
            wanted[code] = (first, last, [*(earlier[2] if earlier else []), event.key])
        ranges: list[ArchiveRange] = []
        carried: dict[str, ArchiveRange] = {}
        missing: list[str] = []
        for code in sorted(wanted):
            first, last, keys = wanted[code]
            source = self.archive.range(*code, first, last)
            ranges.append(source)
            present = {row.event_key for row in source.rows}
            for key in keys:
                if key in present:
                    carried[key] = source
                else:
                    missing.append(key)
        if missing:
            self.skipped["carried event not in its range file"] += len(missing)
            self.missing.update(missing)
        return ArchiveLoad(days, snapshots, tuple(ranges), carried, tuple(sorted(missing)))

    def areas(self, sources: ArchiveLoad | Iterable[ArchiveDay]) -> list[AlertArea]:
        """Turn the rows of ``sources`` into alert areas (see the module docstring)."""
        load = sources if isinstance(sources, ArchiveLoad) else ArchiveLoad(days=tuple(sources))
        events: dict[str, list[Located]] = defaultdict(list)
        for located in load.rows():
            events[located[0].event_key].append(located)
        areas: list[AlertArea] = []
        for key in sorted(events):
            areas.extend(self._event_areas(key, events[key]))
        return areas

    def _event_areas(self, key: str, located: Sequence[Located]) -> list[AlertArea]:
        rows = [row for row, _ in located]
        first = rows[0]
        kind = alert_type_for_code(first.phenomena, first.significance)
        if kind is None:
            self.skipped["code not on the allowlist"] += len(rows)
            return []
        info = AlertInfo(
            key=f"vtec:{key}",
            event=kind.event,
            hazard=kind.hazard,
            level=kind.level,
            severity=None,
        )
        span = _event_span(rows)
        if span is None:
            self.skipped["event never in effect"] += len(rows)
            return []
        polygons = [
            area
            for row, where in located
            if row.gtype == "P" and (area := self._polygon(info, row, span, where)) is not None
        ]
        has_polygon = bool(polygons)
        areas: list[AlertArea] = list(polygons)
        for row, where in located:
            if row.gtype == "C":
                area = self._ugc(info, row, where, point_matching=not has_polygon)
                if area is not None:
                    areas.append(area)
        return areas

    def _polygon(
        self, info: AlertInfo, row: ArchiveRow, span: tuple[datetime, datetime], where: str
    ) -> AlertArea | None:
        # A polygon version is in force from POLY_BEG to POLY_END, but only while the
        # event itself is in effect (a warning cancelled before its begin time never was).
        if row.issued is not None and row.expired is not None:
            span = (row.issued, row.expired)
        start = max(row.polygon_begin or span[0], span[0])
        end = min(row.polygon_end or span[1], span[1])
        if row.geometry is None or end <= start:
            self.skipped["polygon version never in effect or without geometry"] += 1
            return None
        return AlertArea(
            alert=info,
            start=start,
            end=end,
            geometry=row.geometry,
            counties=frozenset(),
            basis="polygon",
            precision="exact",
            trace=f"{where} polygon",
        )

    def _ugc(
        self, info: AlertInfo, row: ArchiveRow, where: str, *, point_matching: bool
    ) -> AlertArea | None:
        ugc = row.ugc or ""
        is_county = ugc[2:3] == "C"
        if not point_matching and not is_county:
            return None  # a zone of a storm-based warning: its polygon decides
        if ugc[:2] not in CONUS_STATES or row.issued is None or row.expired is None:
            self.skipped["county/zone row outside the contiguous states or without times"] += 1
            return None
        day = row.issued.date()
        fips = self._fips(ugc, day) if is_county else None
        exact = self.catalog.lookup(ugc, day)[0] if point_matching else None
        outline = self._outline(ugc, row.geometry) if point_matching and exact is None else None
        if exact is None and outline is None and fips is None:
            self.skipped["county/zone row without a boundary or county code"] += 1
            return None
        hint = self._hint(ugc, day) if outline is not None else None
        if outline is not None:
            found = "without" if hint is None else "with"
            self.outlines[f"approximate rows {found} an NWS hint"] += 1
        return AlertArea(
            alert=info,
            start=row.issued,
            end=row.expired,
            geometry=exact if outline is None else outline,
            counties=frozenset() if fips is None else frozenset({fips}),
            basis="county" if is_county else "zone",
            precision="exact" if outline is None else "approximate",
            point_matching=point_matching,
            trace=f"{where} {ugc}",
            tolerance=0.0 if outline is None else SIMPLIFIED_TOLERANCE,
            hint=hint,
        )

    def _outline(self, ugc: str, geometry: Polygonal | None) -> Polygonal | None:
        """Return ``geometry``, shared with earlier rows that have the same outline."""
        if geometry is None:
            return None
        key = (ugc, shapely.to_wkb(geometry))
        shared = self._shared.get(key)
        if shared is None:
            shared = self._shared[key] = geometry
            grid = "on" if on_simplified_grid(geometry) else "off"
            self.outlines[f"distinct outlines {grid} the 0.01 degree grid"] += 1
        return shared

    def _nearest(self, kind: BoundaryKind, day: date) -> BoundarySet | None:
        """The NWS release in effect on ``day``, or the earliest one for earlier days."""
        release = self.catalog.release_for(kind, day)
        if release is None:
            releases = self.catalog.releases(kind)
            release = releases[0] if releases else None
        return None if release is None else self.catalog.load(release)

    def _hint(self, ugc: str, day: date) -> Polygonal | None:
        nearest = self._nearest(ugc_kind(ugc), day)
        return None if nearest is None else nearest.areas.get(ugc)

    def known_counties(self, day: date) -> frozenset[str]:
        """The county FIPS codes the NWS county release nearest to ``day`` uses."""
        nearest = self._nearest("county", day)
        return frozenset() if nearest is None else frozenset(nearest.county_fips.values())

    def _fips(self, ugc: str, day: date) -> str | None:
        in_effect = self.catalog.boundaries_for("county", day)
        if in_effect is not None and ugc in in_effect.county_fips:
            return in_effect.county_fips[ugc]
        for release in reversed(self.catalog.releases("county")):
            fips = self.catalog.load(release).county_fips.get(ugc)
            if fips is not None:
                return fips
        return None

    def provenance(self) -> dict[str, JSONValue]:
        """The archive files and boundary releases read and what was skipped, for manifests."""
        days: list[JSONValue] = [
            {
                "day": day.day.isoformat(),
                "final": day.final,
                "rows": len(day.rows),
                "file": day.file.provenance.as_json(),
            }
            for day in self.archive.loaded()
        ]
        snapshots: list[JSONValue] = [
            {
                "at": iso_utc(snapshot.at),
                "final": snapshot.final,
                "events": len(snapshot.events),
                "file": snapshot.file.provenance.as_json(),
            }
            for snapshot in self.archive.loaded_snapshots()
        ]
        ranges: list[JSONValue] = [
            {
                "office": source.wfo,
                "code": f"{source.phenomena}.{source.significance}",
                "first": source.first.isoformat(),
                "end": source.end.isoformat(),
                "final": source.final,
                "rows": len(source.rows),
                "file": source.file.provenance.as_json(),
            }
            for source in self.archive.loaded_ranges()
        ]
        carried: dict[str, JSONValue] = {
            key: {
                "first": None if event.first is None else iso_utc(event.first),
                "last_expire": None if event.last_expire is None else iso_utc(event.last_expire),
                "listed_at": [iso_utc(moment) for moment in event.listed_at],
                "reasons": list(event.reasons),
                "in_range_file": key not in self.missing,
            }
            for key, event in sorted(self.carried.items())
        }
        return {
            "archive_days": days,
            "snapshots": snapshots,
            "range_files": ranges,
            "carried_events": carried,
            "boundaries": self.catalog.provenance(),
            "skipped_rows": dict(sorted(self.skipped.items())),
            "approximate_outlines": dict(sorted(self.outlines.items())),
            "simplified_tolerance_deg": SIMPLIFIED_TOLERANCE,
        }

    def index(self, start: datetime, end: datetime) -> WeatherIndex:
        """Return an index of every area that can overlap ``[start, end)``."""
        return WeatherIndex(
            self.areas(self.load(start, end)),
            known_counties=self.known_counties(start.astimezone(UTC).date()),
        )

    def check(
        self,
        *,
        county_fips: str | None,
        lat: float | None,
        lon: float | None,
        start: datetime,
        end: datetime,
    ) -> list[AlertMatch]:
        """Return the archived alerts that covered one place during ``[start, end)``."""
        return self.index(start, end).check(
            county_fips=county_fips, lat=lat, lon=lon, start=start, end=end
        )
