"""Storm-based warning polygons: the Flash Flood Warning applies to the schools inside it.

Of the closure-type codes (:mod:`snowlight.weights.codes`), only the Flash Flood
Warning (FF.W) is storm-based: the NWS draws a polygon for it, and the counties
its product names are only those the polygon touches. The school-year files
(:mod:`snowlight.weights.archive`) give its county rows but not the polygon, so
this module reads the polygons from the same IEM service as a zipped shapefile,
one file per school year (the same window as the school-year file):
``watchwarn.py`` with ``accept=shapefile``, FF.W only, the contiguous states and
DC, ``simple=1`` (the county rows, not used here, come with IEM's simplified
outline) and ``addsvs=1`` (one polygon row per polygon *version*: a forecaster
who narrows the warning in a follow-up statement issues a new polygon, and each
version is valid from ``POLY_BEG`` to ``POLY_END``).

A school counts a school day for FF.W when a polygon version covering its point
(boundary included) passes the 6 AM rule of :mod:`snowlight.weights.count` with
the version's span: ``begin`` the later of ``POLY_BEG`` and the event's
``ISSUED``, ``end`` the earlier of ``POLY_END`` and the event's ``EXPIRED``, and
the product time the head of ``PROD_ID`` (``YYYYMMDDHHMM-``), else ``POLY_BEG``.
A few rows (seven in 2016-17) have a blank ``ISSUED`` or ``EXPIRED``; the
polygon's own span stands in for the blank one, and they are counted.

The county rows of an event that has polygon rows are not used for the schools
(the polygon replaces them); an event of a polygon code with county rows and no
polygon row in the file keeps its county rows, applied to every school of the
county, and is listed (:attr:`PolygonFile.events`).

Files are cached at ``<cache>/mesonet.agron.iastate.edu/watchwarn-polygons/<first
year>-<last year>.zip``, provisional and final like the school-year files.
"""

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, time
from pathlib import Path
from urllib.parse import urlencode

from snowlight.sources.nws.http import CachedFile, parse_iso_utc
from snowlight.sources.nws.iem import FINAL_AFTER, PROVISIONAL_MAX_AGE, WATCHWARN_URL
from snowlight.sources.nws.shapefile import Polygonal, ShapefileError, read_zip
from snowlight.weather.hazards import CONUS_STATES
from snowlight.weights.archive import request_window, school_year_label
from snowlight.weights.cache import WeightsCache

POLYGON_CODES: frozenset[str] = frozenset({"FF.W"})
"""The closure-type codes the NWS issues as storm-based polygons."""
_HOST = "mesonet.agron.iastate.edu"
_STAMP = re.compile(r"^\d{12}$")
_PRODUCT_TIME = re.compile(r"^(\d{12})-")


class PolygonFileError(ValueError):
    """A polygon file does not have the documented attributes."""


def polygon_url(year: int, codes: Iterable[str] = POLYGON_CODES) -> str:
    """Return the request for one school year of storm-based polygons of ``codes``."""
    first, end = request_window(year)
    pairs = sorted(tuple(code.split(".")) for code in codes)
    query = {
        "accept": "shapefile",
        "sts": f"{first.isoformat()}T00:00Z",
        "ets": f"{end.isoformat()}T00:00Z",
        "limitps": "1",
        "phenomena": ",".join(phenomena for phenomena, _ in pairs),
        "significance": ",".join(significance for _, significance in pairs),
        "location_group": "states",
        "states": ",".join(sorted(CONUS_STATES)),
        "simple": "1",
        "addsvs": "1",
    }
    return f"{WATCHWARN_URL}?{urlencode(query, safe=',:')}"


def polygon_path(root: Path, year: int) -> Path:
    """Return where the school year's polygon file is cached."""
    return root / _HOST / "watchwarn-polygons" / f"{year}-{year + 1}.zip"


@dataclass(frozen=True, slots=True)
class PolygonRow:
    """One version of one storm-based warning's polygon."""

    event_key: str
    """``WFO.PP.S.ETN.YEAR``, as :attr:`snowlight.weights.archive.EventRow.event_key`."""
    code: str
    begin: datetime
    end: datetime
    product_issued: datetime
    product_id: str
    geometry: Polygonal


@dataclass(slots=True)
class PolygonStats:
    """What reading a polygon file kept and skipped."""

    records: int = 0
    polygon_rows: int = 0
    county_rows: int = 0
    outside_states: int = 0
    ended_before_start: int = 0
    without_event_times: int = 0
    """Polygon rows whose event ``ISSUED`` is blank (the polygon's own span is used)."""
    events: Counter[str] = field(default_factory=Counter)
    """Polygon versions per event."""


def _time(value: object, name: str, index: int) -> datetime:
    if not isinstance(value, str) or not _STAMP.match(value):
        raise PolygonFileError(f"record {index}: {name} {value!r} is not YYYYMMDDHHMM")
    return datetime.strptime(value, "%Y%m%d%H%M").replace(tzinfo=UTC)


def _whole(value: object, name: str, index: int) -> int:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise PolygonFileError(f"record {index}: {name} {value!r} is not a whole number")


def read_polygon_file(
    path: Path, codes: Iterable[str] = POLYGON_CODES
) -> tuple[list[PolygonRow], PolygonStats]:
    """Read the polygon rows (``GTYPE`` ``P``) of ``codes`` from a ``watchwarn.py`` shapefile.

    A polygon's state is its office's: rows are kept when the county rows of the
    same event name a UGC of the contiguous states or DC (every office that issues
    polygons there does), which the file's ``states`` filter already ensures; the
    count of other records is kept in the stats.

    Raises:
        PolygonFileError: a record lacks a documented attribute or has a malformed time.
    """
    wanted = frozenset(codes)
    try:
        records = read_zip(path)
    except ShapefileError as error:
        raise PolygonFileError(f"{path.name}: {error}") from error
    stats = PolygonStats(records=len(records))
    rows: list[PolygonRow] = []
    for record in records:
        attrs = record.attributes
        gtype = attrs.get("GTYPE")
        code = f"{attrs.get('PHENOM')}.{attrs.get('SIG')}"
        if gtype == "C":
            stats.county_rows += 1
            ugc = str(attrs.get("NWS_UGC") or "")
            if ugc[:2] not in CONUS_STATES:
                stats.outside_states += 1
            continue
        if gtype != "P":
            raise PolygonFileError(f"{path.name}: record {record.index} GTYPE {gtype!r}")
        if code not in wanted:
            raise PolygonFileError(f"{path.name}: record {record.index} {code} was not asked for")
        if record.geometry is None:
            raise PolygonFileError(f"{path.name}: record {record.index} has no polygon")
        index = record.index
        poly_begin = _time(attrs.get("POLY_BEG"), "POLY_BEG", index)
        poly_end = _time(attrs.get("POLY_END"), "POLY_END", index)
        issued = poly_begin
        if attrs.get("ISSUED"):
            issued = _time(attrs.get("ISSUED"), "ISSUED", index)
        else:
            stats.without_event_times += 1
        expired = (
            _time(attrs.get("EXPIRED"), "EXPIRED", index) if attrs.get("EXPIRED") else poly_end
        )
        product_id = str(attrs.get("PROD_ID") or "")
        head = _PRODUCT_TIME.match(product_id)
        product = (
            datetime.strptime(head[1], "%Y%m%d%H%M").replace(tzinfo=UTC) if head else poly_begin
        )
        etn = _whole(attrs.get("ETN"), "ETN", index)
        year = _whole(attrs.get("VTEC_YR"), "VTEC_YR", index)
        key = f"{attrs.get('WFO')}.{code}.{etn:04d}.{year}"
        begin, end = max(poly_begin, issued), min(poly_end, expired)
        stats.polygon_rows += 1
        stats.events[key] += 1
        if end <= begin:
            stats.ended_before_start += 1
        rows.append(PolygonRow(key, code, begin, end, product, product_id, record.geometry))
    return rows, stats


@dataclass(frozen=True, slots=True)
class PolygonFile:
    """One school year's polygon rows and the cached file they came from."""

    year: int
    rows: tuple[PolygonRow, ...]
    stats: PolygonStats
    file: CachedFile
    final: bool

    @property
    def label(self) -> str:
        """The school year, e.g. ``2024-25``."""
        return school_year_label(self.year)

    @property
    def events(self) -> frozenset[str]:
        """The events with at least one polygon row."""
        return frozenset(self.stats.events)


def _is_final(year: int, file: CachedFile) -> bool:
    end = datetime.combine(request_window(year)[1], time(0), tzinfo=UTC)
    return parse_iso_utc(file.provenance.checked_at) >= end + FINAL_AFTER


def load_polygons(cache: WeightsCache, year: int) -> PolygonFile:
    """Return one school year's polygon rows, fetching the file when missing or provisional."""
    url, dest = polygon_url(year), polygon_path(cache.root, year)
    cached = cache.cache.cached(url, dest)
    final_copy = cached is not None and _is_final(year, cached)
    file = cache.fetch(url, dest, max_age=None if final_copy else PROVISIONAL_MAX_AGE)
    rows, stats = read_polygon_file(file.path)
    return PolygonFile(year, tuple(rows), stats, file, _is_final(year, file))


def load_polygon_years(cache: WeightsCache, years: Sequence[int]) -> list[PolygonFile]:
    """Return the polygon files of ``years``."""
    return [load_polygons(cache, year) for year in years]
