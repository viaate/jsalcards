"""Run the weather piece: publish live alerts, back-fill the archive, check schools.

Paths (relative to ``pipeline/``):

* ``.cache/weather/``: every downloaded file with its ``.provenance.json``
  sidecar (the NWS feed response, boundary pages and shapefiles, IEM day files);
* ``out/site-data/live/alerts.json``: the published live alerts
  (shape in :mod:`snowlight.weather.publish`);
* ``out/manifests/alerts.json``: the internal manifest behind it, never published
  (the file is validated against :class:`snowlight.schemas.live.AlertsFile` first);
* ``out/internal/weather/matches.parquet`` (``alerts schools``): the weather
  check for every school, never published. One row per school and alert that
  covered it or may have: ``id``, ``key`` (``vtec:OFFICE.PP.S.NNNN.YYYY`` for
  the archive, the NWS alert id for live alerts), ``event``, ``hazard``, ``level``,
  ``severity``, ``start`` and ``end`` (UTC; a null end is "until further
  notice"), ``coverage`` (``covered``, or ``uncertain`` near a simplified
  archive boundary, outside every NWS zone, or when the school's time zone is
  not settled), ``basis``
  (``polygon``, ``zone`` or ``county``), ``precision`` (``exact`` or
  ``approximate``), ``traces`` (the source records) and ``zones`` (the time
  zones the school was checked in). A school with no row was checked and not
  covered, unless it is listed as unchecked in
* ``out/internal/weather/matches.json``: the window, the unchecked schools,
  counts, and the provenance of every source file the check read.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import numpy.typing as npt
import polars as pl
import shapely
from pydantic import ValidationError

from snowlight.output import JSONValue, write_bytes_atomic, write_json
from snowlight.schemas.live import AlertsFile
from snowlight.sources.nws.alerts import ACTIVE_URL, fetch_active
from snowlight.sources.nws.boundaries import BoundaryCatalog, BoundarySet
from snowlight.sources.nws.http import HttpCache, iso_utc
from snowlight.sources.nws.iem import IemArchive
from snowlight.weather.hazards import ALERT_TYPES, CONUS_STATES
from snowlight.weather.history import DEFAULT_LOOKBACK, WarningHistory
from snowlight.weather.index import BASES, MATCH_SCHEMA, PRECISIONS, WeatherIndex
from snowlight.weather.live import Selection, select_alerts
from snowlight.weather.publish import DEFAULT_MAX_BYTES, group_alerts, render
from snowlight.weather.timezones import IANA_ZONES, LocalWindow, TimeZoneLookup, Window

PIPELINE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE_DIR = PIPELINE_ROOT / ".cache" / "weather"
DEFAULT_OUT_DIR = PIPELINE_ROOT / "out" / "site-data"
DEFAULT_MANIFEST = PIPELINE_ROOT / "out" / "manifests" / "alerts.json"
MANIFEST_SCHEMA = 1


class WeatherBuildError(RuntimeError):
    """The sources do not allow the requested output."""


def archive_codes() -> list[tuple[str, str]]:
    """Every VTEC code on the allowlist, for the archive request."""
    return sorted({code for kind in ALERT_TYPES for code in kind.codes})


def make_archive(cache: HttpCache, cache_dir: Path) -> IemArchive:
    """Return the IEM archive reader for the allowlisted codes and the contiguous states."""
    return IemArchive(cache, cache_dir, archive_codes(), CONUS_STATES)


def current_boundaries(catalog: BoundaryCatalog, day: date) -> tuple[BoundarySet, BoundarySet]:
    """Return the zone and county releases in effect on ``day``.

    Raises:
        WeatherBuildError: the NWS lists no release in effect on ``day``.
    """
    zones = catalog.boundaries_for("zone", day)
    counties = catalog.boundaries_for("county", day)
    if zones is None or counties is None:
        raise WeatherBuildError(f"no NWS zone/county boundary release is in effect on {day}")
    return zones, counties


@dataclass(frozen=True, slots=True)
class LiveResult:
    """What ``alerts live`` wrote."""

    path: Path
    manifest: Path
    features: int
    kept: int
    published: int
    dropped: dict[str, int]
    tolerance: float
    size: int
    not_modified: bool


def _selection_manifest(selection: Selection) -> dict[str, JSONValue]:
    return {
        "dropped": [
            {"event": item.event, "id": item.id, "reason": item.reason}
            for item in selection.dropped
        ],
        "dropped_by_reason": dict(selection.reasons()),
    }


def build_live(
    cache: HttpCache,
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    out_dir: Path = DEFAULT_OUT_DIR,
    manifest_path: Path = DEFAULT_MANIFEST,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> LiveResult:
    """Fetch the active alerts, keep the relevant ones and publish ``live/alerts.json``."""
    feed, fetched = fetch_active(cache, cache_dir)
    catalog = BoundaryCatalog(cache, cache_dir)
    as_of = feed.updated or cache.now()
    zones, counties = current_boundaries(catalog, as_of.date())
    selection = select_alerts(feed, zones, counties)
    groups = group_alerts(selection.kept)
    generated = cache.now()
    rendered = render(groups, as_of=feed.updated, generated_at=generated, max_bytes=max_bytes)
    try:
        AlertsFile.from_json_bytes(rendered.data)
    except ValidationError as error:
        raise WeatherBuildError(
            f"live/alerts.json does not match the shared schema: {error}"
        ) from error
    path = out_dir / "live" / "alerts.json"
    published: list[JSONValue] = []
    for group in groups:
        members: list[JSONValue] = [
            {
                "basis": item.basis,
                "ends": None if item.end is None else iso_utc(item.end),
                "event": item.alert.event,
                "expires": None if item.alert.expires is None else iso_utc(item.alert.expires),
                "message_type": item.alert.message_type,
                "nws_id": item.alert.id,
                "onset": iso_utc(item.start),
                "sent": iso_utc(item.alert.sent),
                "severity": item.alert.severity,
                "unresolved": list(item.unresolved),
                "vtec": [
                    f"{v.product_class}.{v.action}.{v.office}.{v.phenomena}.{v.significance}."
                    f"{v.etn:04d}"
                    for v in item.alert.vtec
                ],
                "zones": list(item.zones),
            }
            for item in group.members
        ]
        published.append(
            {
                "id": group.id,
                "members": members,
                "too_small_to_draw": group.id in rendered.too_small,
            }
        )
    manifest: dict[str, JSONValue] = {
        "schema": MANIFEST_SCHEMA,
        "generated_at": iso_utc(generated),
        "output": {
            "path": "live/alerts.json",
            "bytes": len(rendered.data),
            "sha256": hashlib.sha256(rendered.data).hexdigest(),
            "max_bytes": max_bytes,
            "alerts": rendered.alerts,
            "simplify_tolerance_deg": rendered.tolerance,
            "validated_against": f"{AlertsFile.__module__}.{AlertsFile.__name__}",
        },
        "feed": {
            "request": ACTIVE_URL,
            "file": fetched.provenance.as_json(),
            "not_modified": fetched.not_modified,
            "updated": None if feed.updated is None else iso_utc(feed.updated),
            "features": len(feed.alerts),
        },
        "boundaries": catalog.provenance(),
        "kept": len(selection.kept),
        **_selection_manifest(selection),
        "published": published,
    }
    # The manifest goes first, so a published file never lacks the record behind it.
    write_json(manifest_path, manifest)
    write_bytes_atomic(path, rendered.data)
    return LiveResult(
        path=path,
        manifest=manifest_path,
        features=len(feed.alerts),
        kept=len(selection.kept),
        published=rendered.alerts,
        dropped=selection.reasons(),
        tolerance=rendered.tolerance,
        size=len(rendered.data),
        not_modified=fetched.not_modified,
    )


def live_sources(
    cache: HttpCache, cache_dir: Path = DEFAULT_CACHE_DIR
) -> tuple[WeatherIndex, dict[str, JSONValue]]:
    """Return the index over the currently active, relevant alerts, and its provenance."""
    feed, fetched = fetch_active(cache, cache_dir)
    catalog = BoundaryCatalog(cache, cache_dir)
    zones, counties = current_boundaries(catalog, (feed.updated or cache.now()).date())
    selection = select_alerts(feed, zones, counties)
    index = WeatherIndex([area for alert in selection.kept for area in alert.areas])
    provenance: dict[str, JSONValue] = {
        "feed": {
            "request": ACTIVE_URL,
            "file": fetched.provenance.as_json(),
            "updated": None if feed.updated is None else iso_utc(feed.updated),
            "features": len(feed.alerts),
            "kept": len(selection.kept),
        },
        "boundaries": catalog.provenance(),
    }
    return index, provenance


def live_index(cache: HttpCache, cache_dir: Path = DEFAULT_CACHE_DIR) -> WeatherIndex:
    """Return the weather-check index over the currently active, relevant alerts."""
    return live_sources(cache, cache_dir)[0]


def archive_window(window: Window) -> tuple[datetime, datetime]:
    """The UTC span of ``window`` over every time zone of the contiguous states.

    The archive is loaded for this span, the same for one place (``alerts
    check``) as for every school (``alerts schools``), so both read the same
    files and give a school the same answer.
    """
    spans = [window.utc(zone) for zone in IANA_ZONES.values()]
    return min(start for start, _ in spans), max(end for _, end in spans)


@dataclass(frozen=True, slots=True)
class BackfillResult:
    """What ``alerts backfill`` cached."""

    days: int
    downloaded: int
    final: int
    rows: int
    snapshots: int
    ranges: int
    carried: int


def backfill(
    cache: HttpCache,
    start: date,
    end: date,
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    lookback: timedelta = DEFAULT_LOOKBACK,
) -> BackfillResult:
    """Cache every archive file and NWS boundary release the local dates ``start..end`` need.

    Each date is loaded as ``alerts check`` and ``alerts schools`` load it (the
    whole local day, :func:`archive_window`), so later checks of those dates
    run offline.
    """
    if end < start:
        raise ValueError("the end date is before the start date")
    catalog = BoundaryCatalog(cache, cache_dir)
    for kind in ("zone", "county"):
        for release in catalog.releases(kind):
            catalog.load(release)
    history = WarningHistory(make_archive(cache, cache_dir), catalog, lookback=lookback)
    days: dict[date, tuple[bool, bool, int]] = {}
    for n in range((end - start).days + 1):
        window_start, window_end = archive_window(LocalWindow(start + timedelta(days=n)))
        load = history.load(window_start, window_end)
        for day in load.days:
            days[day.day] = (day.file.downloaded, day.final, len(day.rows))
        # Later dates need no earlier day files than this one's first.
        history.archive.evict(load.days[0].day if load.days else start)
    return BackfillResult(
        days=len(days),
        downloaded=sum(downloaded for downloaded, _, _ in days.values()),
        final=sum(final for _, final, _ in days.values()),
        rows=sum(rows for _, _, rows in days.values()),
        snapshots=len(history.archive.loaded_snapshots()),
        ranges=len(history.archive.loaded_ranges()),
        carried=len(history.carried),
    )


def local_windows(
    zones: Sequence[str], window: Window
) -> tuple[npt.NDArray[np.datetime64], npt.NDArray[np.datetime64]]:
    """Return the window's UTC bounds (``datetime64[ns]``) for a place in each of ``zones``."""
    begins = np.full(len(zones), np.datetime64("NaT", "ns"), dtype="datetime64[ns]")
    ends = begins.copy()
    by_zone: dict[str, tuple[np.datetime64, np.datetime64]] = {}
    for i, zone in enumerate(zones):
        if zone not in by_zone:
            lo, hi = window.utc(zone)
            by_zone[zone] = (
                np.datetime64(lo.astimezone(UTC).replace(tzinfo=None), "ns"),
                np.datetime64(hi.astimezone(UTC).replace(tzinfo=None), "ns"),
            )
        begins[i], ends[i] = by_zone[zone]
    return begins, ends


PLACE_SCHEMA: dict[str, pl.DataType] = {
    "place": pl.Int64(),
    **{name: dtype for name, dtype in MATCH_SCHEMA.items() if name != "row"},
    "zones": pl.List(pl.String()),
}
"""The rows of :func:`check_places`: ``place`` is the input position, ``zones`` the
time zones the place was checked in (more than one when its zone is not settled)."""


def _rank(column: str, names: tuple[str, ...]) -> pl.Expr:
    return pl.col(column).replace_strict(list(names), list(range(len(names))))


def _name(column: str, names: tuple[str, ...]) -> pl.Expr:
    return pl.col(column).replace_strict(
        list(range(len(names))), list(names), return_dtype=pl.String()
    )


STRAY_DISTANCE = 0.05
"""Degrees: a place farther than this from every NWS public zone gets no stand-in point."""


class ZoneFootprint:
    """The NWS public zones of one release, to notice places outside all of them.

    The NWS zone and county files draw coastlines and state lines generalized,
    so a few schools (on small islands, beaches, piers, or right on a state
    line) fall outside every zone. A zone-based alert then cannot match them by
    point, although they are in the area it names. :meth:`stand_ins` gives such
    a place a point just inside the nearest zone, and :func:`check_places`
    reports what covers that point as ``uncertain``.
    """

    def __init__(self, zones: BoundarySet) -> None:
        geometries = np.array(list(zones.areas.values()), dtype=object)
        shapely.prepare(geometries)
        self._geometries = geometries
        self._tree = shapely.STRtree(geometries)

    def stand_ins(
        self, lat: npt.NDArray[np.float64], lon: npt.NDArray[np.float64]
    ) -> list[tuple[float, float] | None]:
        """For each place outside every zone but near one: ``(lat, lon)`` inside the nearest."""
        answers: list[tuple[float, float] | None] = [None] * lat.size
        located = np.flatnonzero(np.isfinite(lat) & np.isfinite(lon))
        if not located.size or not self._geometries.size:
            return answers
        points: npt.NDArray[np.object_] = np.asarray(
            shapely.points(lon[located], lat[located]), dtype=object
        )
        inside = np.zeros(located.size, dtype=bool)
        inside[self._tree.query(points, predicate="intersects")[0]] = True
        strays = np.flatnonzero(~inside)
        if not strays.size:
            return answers
        (which, nearest), distance = self._tree.query_nearest(
            points[strays], max_distance=STRAY_DISTANCE, return_distance=True, all_matches=False
        )
        for k, zone, gap in zip(which.tolist(), nearest.tolist(), distance.tolist(), strict=True):
            point = points[strays[k]]
            # A point of the zone within the gap (plus a little) of the place.
            reach = shapely.intersection(self._geometries[zone], point.buffer(gap + 0.001))
            spot = shapely.point_on_surface(reach)
            answers[int(located[strays[k]])] = (spot.y, spot.x)
        return answers


def check_places(
    index: WeatherIndex,
    places: pl.DataFrame,
    zones: Sequence[Sequence[str]],
    window: Window,
    stand_ins: Sequence[tuple[float, float] | None] | None = None,
) -> pl.DataFrame:
    """Check places whose time zone may not be settled, or that lie outside every zone.

    ``places`` has ``county_fips``, ``lat`` and ``lon`` (null when unknown);
    ``zones[i]`` lists every IANA zone place ``i`` can be in (see
    :meth:`~snowlight.weather.timezones.TimeZoneLookup.zones_for`); a place with
    none is not checked. The window is placed in each of them, and an alert is
    ``covered`` only if it covered the place in every one; if it covered or may
    have covered the place in some but not all, it is ``uncertain``.
    ``stand_ins[i]``, when given (see :meth:`ZoneFootprint.stand_ins`), is also
    checked, and whatever covers only it is ``uncertain``. Spans are joined (an
    open end stays open), the most specific basis and ``exact`` precision win,
    and the traces are pooled.
    """
    county_fips: list[str | None] = places["county_fips"].to_list()
    lat = places["lat"].cast(pl.Float64).fill_null(np.nan).to_numpy()
    lon = places["lon"].cast(pl.Float64).fill_null(np.nan).to_numpy()
    moved = list(stand_ins) if stand_ins is not None else [None] * places.height
    if len(zones) != places.height or len(moved) != places.height:
        raise ValueError("one list of time zones (and one stand-in) is needed per place")
    # One check per place, time zone and point (the place's own, then any stand-in).
    owner: list[int] = []
    names: list[str] = []
    stand_in: list[bool] = []
    points: list[tuple[float, float]] = []
    for i, options in enumerate(zones):
        spots: list[tuple[float, float]] = [(float(lat[i]), float(lon[i]))]
        extra = moved[i]
        if extra is not None:
            spots.append(extra)
        for name in options:
            for n, spot in enumerate(spots):
                owner.append(i)
                names.append(name)
                stand_in.append(n > 0)
                points.append(spot)
    begins, ends = local_windows(names, window)
    rows = np.array(owner, dtype=np.int64)
    matches = index.check_many(
        [county_fips[i] for i in owner],
        np.array([x for _, x in points], dtype=np.float64),
        np.array([y for y, _ in points], dtype=np.float64),
        start=begins,
        end=ends,
    )
    counts = pl.DataFrame(
        {
            "place": np.arange(len(zones), dtype=np.int64),
            "options": [list(z) for z in zones],
            "simple": [len(z) == 1 and m is None for z, m in zip(zones, moved, strict=True)],
        },
        schema={"place": pl.Int64(), "options": pl.List(pl.String()), "simple": pl.Boolean()},
    )
    check_rows = matches["row"].to_numpy()
    placed = matches.with_columns(
        pl.Series("place", rows[check_rows], pl.Int64()),
        pl.Series("zone", np.array(names, dtype=object)[check_rows], pl.String()),
        pl.Series("stand_in", np.array(stand_in, dtype=bool)[check_rows], pl.Boolean()),
    ).join(counts, on="place", how="left")
    # A place with one zone and no stand-in is answered by its one check as it is.
    single = placed.filter(pl.col("simple")).with_columns(pl.col("options").alias("zones"))
    merged = (
        placed.filter(~pl.col("simple"))
        .group_by("place", "key")
        .agg(
            pl.col("event", "hazard", "level", "severity", "options").first(),
            pl.col("start").min(),
            pl.when(pl.col("end").is_null().any())
            .then(None)
            .otherwise(pl.col("end").max())
            .alias("end"),
            pl.col("zone")
            .filter((pl.col("coverage") == "covered") & ~pl.col("stand_in"))
            .n_unique()
            .alias("covered_in"),
            _rank("basis", BASES).min().alias("basis"),
            _rank("precision", PRECISIONS).min().alias("precision"),
            pl.col("traces").list.explode(keep_nulls=False, empty_as_null=False).unique().sort(),
        )
        .with_columns(
            pl.when(pl.col("covered_in") == pl.col("options").list.len())
            .then(pl.lit("covered"))
            .otherwise(pl.lit("uncertain"))
            .alias("coverage"),
            _name("basis", BASES),
            _name("precision", PRECISIONS),
            pl.col("options").alias("zones"),
        )
    )
    return pl.concat(
        [part.select(list(PLACE_SCHEMA)).cast(pl.Schema(PLACE_SCHEMA)) for part in (single, merged)]
    ).sort("place", "start", "event", "key")


def check_schools(
    index: WeatherIndex,
    schools: pl.DataFrame,
    zones: TimeZoneLookup,
    window: Window,
    footprint: ZoneFootprint | None = None,
) -> tuple[pl.DataFrame, list[str]]:
    """Check every school (``id``, ``county_fips``, ``lat``, ``lon``) for one local window.

    Returns the matches (:func:`check_places` rows with the school ``id`` in
    place of ``place``) and the ids of the schools that were not checked because
    nothing is known of their time zone (they have no rows, but that does not
    mean no alert covered them). With ``footprint``, schools outside every NWS
    zone are also checked at a stand-in point (see :class:`ZoneFootprint`).
    """
    options = [
        zones.zones_for(fips, lat, lon)
        for fips, lat, lon in schools.select("county_fips", "lat", "lon").iter_rows()
    ]
    moved = None
    if footprint is not None:
        lat = schools["lat"].cast(pl.Float64).fill_null(np.nan).to_numpy()
        lon = schools["lon"].cast(pl.Float64).fill_null(np.nan).to_numpy()
        moved = footprint.stand_ins(lat, lon)
        fips: list[str | None] = schools["county_fips"].to_list()
        for i, spot in enumerate(moved):
            if spot is not None and not options[i]:
                # Outside every zone, the stand-in's zone settles the time zone.
                options[i] = zones.zones_for(fips[i], *spot)
    matches = check_places(index, schools, options, window, moved)
    ids = pl.Series("id", schools["id"].to_numpy())
    result = matches.with_columns(ids.gather(matches["place"])).drop("place")
    unchecked = [str(ids[i]) for i, option in enumerate(options) if not option]
    return result.select("id", *[c for c in result.columns if c != "id"]), unchecked
