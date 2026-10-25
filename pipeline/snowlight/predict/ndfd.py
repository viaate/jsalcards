"""The Weather Service's forecast grids (NDFD) for the night-before chance (S7-F, spec-f s. 4, 11).

The National Digital Forecast Database is the forecaster-edited 2.5 km grid behind the
weather.gov point forecasts and the snow totals quoted in warnings. One code path reads it for
the history (the backfill workflow, :mod:`snowlight.predict.forecast_history`) and, later, for
the live pass: the same objects, the same decoder, the same rules.

Objects
=======

``noaa-ndfd-pds`` on AWS (from 2020-04-16; also the live host), key
``wmo/<element>/YYYY/MM/DD/<heading>_KWBN_<YYYYMMDDHHMM>``; NCEI THREDDS
``model-ndfd-file-old/YYYYMM/YYYYMMDD/<heading>_KWBN_<stamp>`` before that (2018-06 to
2020-05). Three elements, CONUS 2.5 km (``U``, ``98``):

* ``snow`` (``YSUZ98``): snow amount, 0/1/29, metres, 6-hour periods ending 00, 06, 12, 18Z;
* ``iceaccum`` (``YZUZ98``): ice accumulation, 0/1/227, mm, the same periods;
* ``apt`` (``YTUZ98``): apparent temperature, 0/0/193, K, hourly to 36 hours.

Each file is WMO-framed (a heading line between GRIB messages); the reader finds each
``GRIB`` and its 8-byte length, so a framed AWS or NCEI file and an unframed one read alike.
Files are read by HTTP range: a 1 KB head per message, then only the messages a window needs.

Runs
====

A run is the three elements' stamps in one half hour; its time is the latest of the three. It
counts from its time plus :data:`RUN_DELAY` (and, on AWS, never before every object of it was
listed: its ``LastModified``), only while it is at most :data:`MAX_AGE` old. No such run: the
forecast is unknown.

Grid
====

Lambert conformal, 2145 x 1377, true at 25 N, LoV 265, first point 20.191999 N 238.445999 E,
2539.703 m, sphere of 6,371,200 m, scanning mode 80 (alternate rows reversed). Every decode
asserts all of it (:class:`GridError`); every odd row is reversed before indexing, after which
the Lambert index of a school (:func:`cells`) is exactly the cell eccodes calls nearest.

Window and values
=================

Snow and ice: the 6-hour periods ending 06Z, 12Z and 18Z on the school day D, less the
periods ended by the time asked (as of). Every amount message holds a whole 6-hour period, the
one ending at its end-of-interval time: the period under way at the run's reference time too,
snow before the run included (measured over 2018-2025 runs, docs/predict.md). The files stamp it
two ways (:class:`PeriodStamp`); both read alike (:func:`period_stamp`). Apparent temperature at
07:00 local on D.
A district's value is the class's 50% rule (:func:`group_half`); its bucket is
:func:`bucket_codes`.
"""

import itertools
import re
import struct
from collections import Counter
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import IntEnum, StrEnum
from typing import Any, Final, Protocol
from urllib.parse import quote
from zoneinfo import ZoneInfo

import numpy as np
import numpy.typing as npt

type Floats = npt.NDArray[np.float64]
type Ints = npt.NDArray[np.int64]


class NdfdError(ValueError):
    """An NDFD file or listing is not what this module reads."""


class GridError(NdfdError):
    """A message is not on the NDFD 2.5 km CONUS grid (spec-f s. 4: assert every read)."""


class PeriodError(NdfdError):
    """A message's time range is not one of the 6-hour periods (or the run's partial one)."""


class NotFoundError(NdfdError):
    """The host has no such file or listing (HTTP 404): NCEI has no folder for some days."""


class ShortReadError(NdfdError):
    """A range read kept returning other bytes than the file holds there (fewer than asked
    before its end, or another range), after :data:`RANGE_ATTEMPTS` tries."""


class HeadError(NdfdError):
    """A GRIB message's head is cut short or malformed: the file ends inside sections 0 to 4
    (an object truncated on its host), or a section overruns the bytes that hold it."""


class LongHeadError(HeadError):
    """Section 4 lies past the bytes read at a message's start (a long section 2): the head is
    read again whole (:func:`head_bytes`)."""


class Element(StrEnum):
    """An NDFD element, by its folder name on AWS. The night-before chance reads the first
    three (:data:`ELEMENTS`); the rest are read only by the label-night forecast extract
    (:mod:`snowlight.predict.night_extract`)."""

    SNOW = "snow"
    ICE = "iceaccum"
    APT = "apt"
    TEMP = "temp"
    POP12 = "pop12"
    QPF = "qpf"
    WX = "wx"

    @property
    def heading(self) -> str:
        """The WMO heading of its CONUS 2.5 km file."""
        return HEADING[self]

    @property
    def parameter(self) -> tuple[int, int, int]:
        """Its GRIB2 discipline, category and number."""
        return PARAMETER[self]


HEADING: Final[Mapping[Element, str]] = {
    Element.SNOW: "YSUZ98",
    Element.ICE: "YZUZ98",
    Element.APT: "YTUZ98",
    Element.TEMP: "YEUZ98",
    Element.POP12: "YDUZ98",
    Element.QPF: "YIUZ98",
    Element.WX: "YJUZ98",
}
PARAMETER: Final[Mapping[Element, tuple[int, int, int]]] = {
    Element.SNOW: (0, 1, 29),
    Element.ICE: (0, 1, 227),
    Element.APT: (0, 0, 193),
    Element.TEMP: (0, 0, 0),
    Element.POP12: (0, 1, 8),
    Element.QPF: (0, 1, 8),
    Element.WX: (0, 1, 192),
}
ELEMENTS: Final = (Element.SNOW, Element.ICE, Element.APT)
"""The elements of a run of the night-before chance (:func:`assemble_runs`)."""


class Host(StrEnum):
    """Where an object was listed."""

    AWS = "aws"
    NCEI = "ncei"
    TGFTP = "tgftp"


AWS_ROOT: Final = "https://noaa-ndfd-pds.s3.amazonaws.com"
NCEI_ROOT: Final = "https://www.ncei.noaa.gov/thredds"
NCEI_DATASET: Final = "model-ndfd-file-old"
TGFTP_ROOT: Final = (
    "https://tgftp.nws.noaa.gov/SL.us008001/ST.opnl/DF.gr2/DC.ndfd/AR.conus/VP.001-003/"
)
TGFTP_FILE: Final[Mapping[Element, str]] = {
    Element.SNOW: "ds.snow.bin",
    Element.ICE: "ds.iceaccum.bin",
    Element.APT: "ds.apt.bin",
}
AWS_FIRST_DAY: Final = date(2020, 4, 17)
"""The first UTC day listed from AWS (the bucket starts on 2020-04-16, part of a day)."""
ARCHIVE_COPY_AFTER: Final = timedelta(days=1)
ARCHIVE_FILL_MIN: Final = 100
"""An archive fill is a UTC day on which AWS wrote at least this many objects more than
:data:`ARCHIVE_COPY_AFTER` after their stamps: the bucket's first weeks (2020-04-17 to 2020-05-29)
were uploaded in bulk on 2020-06-01 to 06-03 (6,139 objects, 1 to 46 days after their stamps).
Such an object is an archive copy: its write time says when the archive was filled, not when the
forecast was public, so it counts as an NCEI file does (stamp + delay) and is flagged. Any other
late object keeps its write time (19 written a day late in 2023 and 2025, and 12 written 3 to 24
hours late): its run is over 3 hours old by then and never counts (spec-f s. 4, leakage)."""

RUN_DELAY: Final = timedelta(minutes=10)
"""A run counts from its time plus this (spec-f s. 4; F1 measures the AWS lateness)."""
MAX_AGE: Final = timedelta(hours=3)
"""A run older than this is not used: the forecast is unknown (or stale, live)."""
HALF_HOUR: Final = timedelta(minutes=30)

# --- the grid -----------------------------------------------------------------------------------

NX: Final = 2145
NY: Final = 1377
LATIN_DEG: Final = 25.0
LOV_DEG: Final = 265.0
LA1_DEG: Final = 20.191999
LO1_DEG: Final = 238.445999
DX_M: Final = 2539.703
RADIUS_M: Final = 6371200.0
SCANNING_MODE: Final = 80
GRID_KEYS: Final[Mapping[str, float]] = {
    "gridDefinitionTemplateNumber": 30,
    "Nx": NX,
    "Ny": NY,
    "LaDInDegrees": LATIN_DEG,
    "LoVInDegrees": LOV_DEG,
    "Latin1InDegrees": LATIN_DEG,
    "Latin2InDegrees": LATIN_DEG,
    "latitudeOfFirstGridPointInDegrees": LA1_DEG,
    "longitudeOfFirstGridPointInDegrees": LO1_DEG,
    "DxInMetres": DX_M,
    "DyInMetres": DX_M,
    "radius": RADIUS_M,
    "scanningMode": SCANNING_MODE,
}
"""Every key a message must carry, and its value (spec-f s. 4, research B s. 3.1)."""
_GRID_TOLERANCE: Final = 1e-6

_N: Final = float(np.sin(np.radians(LATIN_DEG)))
_F: Final = float(
    np.cos(np.radians(LATIN_DEG)) * np.tan(np.pi / 4 + np.radians(LATIN_DEG) / 2) ** _N / _N
)
_RHO0: Final = RADIUS_M * _F / float(np.tan(np.pi / 4 + np.radians(LATIN_DEG) / 2)) ** _N


def _project(lat: Floats, lon: Floats) -> tuple[Floats, Floats]:
    phi = np.radians(lat)
    theta = _N * (np.radians(np.mod(lon, 360.0)) - np.radians(LOV_DEG))
    rho = RADIUS_M * _F / np.tan(np.pi / 4 + phi / 2) ** _N
    return rho * np.sin(theta), _RHO0 - rho * np.cos(theta)


_X0, _Y0 = (float(v[0]) for v in _project(np.array([LA1_DEG]), np.array([LO1_DEG])))


@dataclass(frozen=True, slots=True)
class Cells:
    """The grid cell under each point: ``row`` (south to north) and ``col`` (west to east)
    after the odd rows are reversed; ``inside`` is false for a point off the grid."""

    row: Ints
    col: Ints
    inside: npt.NDArray[np.bool_]


def cells(lat: Floats, lon: Floats) -> Cells:
    """The Lambert index of each point (degrees; longitude east, either sign)."""
    x, y = _project(np.asarray(lat, dtype=np.float64), np.asarray(lon, dtype=np.float64))
    col = np.rint((x - _X0) / DX_M).astype(np.int64)
    row = np.rint((y - _Y0) / DX_M).astype(np.int64)
    inside = (col >= 0) & (col < NX) & (row >= 0) & (row < NY)
    return Cells(np.where(inside, row, 0), np.where(inside, col, 0), inside)


def sample(grid: Floats, where: Cells) -> Floats:
    """The grid's value at each cell; NaN off the grid."""
    found = grid[where.row, where.col]
    return np.where(where.inside, found, np.nan)


# --- listings and runs --------------------------------------------------------------------------

_NAME: Final = re.compile(r"\b(Y[SZTEDIJ]UZ98)_KWBN_(\d{12})\b")
_HEADING_ELEMENT: Final = {heading: element for element, heading in HEADING.items()}


@dataclass(frozen=True, slots=True)
class Listed:
    """One listed object: an element's file of one stamp."""

    element: Element
    stamp: datetime
    url: str
    host: Host
    last_modified: datetime | None = None
    """When the host wrote it (AWS); ``None`` where the host does not say (NCEI keeps its own
    archive time, not the original's)."""

    @property
    def lateness(self) -> timedelta | None:
        """How long after its stamp it was written (AWS)."""
        return None if self.last_modified is None else self.last_modified - self.stamp

    @property
    def over_a_day_late(self) -> bool:
        """Written more than :data:`ARCHIVE_COPY_AFTER` after its stamp."""
        late = self.lateness
        return late is not None and late > ARCHIVE_COPY_AFTER

    def archive_copy(self, fills: Collection[date]) -> bool:
        """Written over a day late on an archive fill day (:func:`archive_fills`)."""
        return (
            self.over_a_day_late
            and self.last_modified is not None
            and self.last_modified.date() in fills
        )

    def published_at(self, fills: Collection[date] = ()) -> datetime | None:
        """When it was written, as far as that says when it was public: ``None`` for an NCEI
        file and an archive copy (they count from their stamp plus the delay)."""
        return None if self.archive_copy(fills) else self.last_modified


def archive_fills(listed: Iterable[Listed]) -> dict[date, int]:
    """The archive fill days (:data:`ARCHIVE_FILL_MIN`) and how many late objects each wrote."""
    days: Counter[date] = Counter(
        item.last_modified.date()
        for item in listed
        if item.over_a_day_late and item.last_modified is not None
    )
    return {day: count for day, count in sorted(days.items()) if count >= ARCHIVE_FILL_MIN}


def stamp_of(text: str) -> datetime:
    """The UTC time of a ``YYYYMMDDHHMM`` stamp.

    Raises:
        NdfdError: it is not one.
    """
    if not re.fullmatch(r"\d{12}", text):
        raise NdfdError(f"not a stamp: {text!r}")
    try:
        return datetime.strptime(text, "%Y%m%d%H%M").replace(tzinfo=UTC)
    except ValueError as error:
        raise NdfdError(f"not a stamp: {text!r}") from error


def aws_listing_url(element: Element, day: date, token: str | None = None) -> str:
    """The S3 listing of one element's CONUS 2.5 km files of one UTC day."""
    prefix = f"wmo/{element.value}/{day:%Y/%m/%d}/{element.heading}"
    url = f"{AWS_ROOT}/?list-type=2&prefix={prefix}"
    if token is not None:
        url += "&continuation-token=" + _quote(token)
    return url


def _quote(text: str) -> str:
    return quote(text, safe="")


_KEY_BLOCK: Final = re.compile(r"<Contents>(.*?)</Contents>", re.DOTALL)
_KEY: Final = re.compile(r"<Key>([^<]+)</Key>")
_MODIFIED: Final = re.compile(r"<LastModified>([^<]+)</LastModified>")
_TOKEN: Final = re.compile(r"<NextContinuationToken>([^<]+)</NextContinuationToken>")
_TRUNCATED: Final = re.compile(r"<IsTruncated>(true|false)</IsTruncated>")


def parse_aws_listing(xml: bytes) -> tuple[list[Listed], str | None]:
    """The objects of one S3 ``ListObjectsV2`` page, and the token of the next page (if any).

    Raises:
        NdfdError: it is not a listing page.
    """
    text = xml.decode("utf-8", errors="replace")
    truncated = _TRUNCATED.search(text)
    if "<ListBucketResult" not in text or truncated is None:
        raise NdfdError("not an S3 listing")
    found: list[Listed] = []
    for block in _KEY_BLOCK.findall(text):
        key, modified = _KEY.search(block), _MODIFIED.search(block)
        if key is None or modified is None:
            raise NdfdError("an S3 listing entry has no key or time")
        name = _NAME.search(key.group(1))
        if name is None or not key.group(1).endswith(name.group(0)):
            continue
        written = datetime.fromisoformat(modified.group(1).replace("Z", "+00:00"))
        found.append(
            Listed(
                _HEADING_ELEMENT[name.group(1)],
                stamp_of(name.group(2)),
                f"{AWS_ROOT}/{key.group(1)}",
                Host.AWS,
                written.astimezone(UTC),
            )
        )
    following = _TOKEN.search(text)
    more = truncated.group(1) == "true"
    if more and following is None:
        raise NdfdError("a truncated S3 listing has no continuation token")
    return found, following.group(1) if more and following is not None else None


def ncei_catalog_url(day: date) -> str:
    """The THREDDS catalog of one UTC day of the NCEI archive."""
    return f"{NCEI_ROOT}/catalog/{NCEI_DATASET}/{day:%Y%m}/{day:%Y%m%d}/catalog.xml"


_DATASET: Final = re.compile(
    r'<dataset\s+name="(Y[SZTEDIJ]UZ98_KWBN_\d{12})"[^>]*urlPath="([^"]+)"'
)


def parse_ncei_catalog(xml: bytes, elements: Collection[Element] = ELEMENTS) -> list[Listed]:
    """The CONUS 2.5 km files of ``elements`` (snow, ice and apparent temperature unless
    told) a THREDDS day catalog lists.

    Raises:
        NdfdError: it is not a THREDDS catalog.
    """
    text = xml.decode("utf-8", errors="replace")
    if "<catalog" not in text:
        raise NdfdError("not a THREDDS catalog")
    found: list[Listed] = []
    for name, path in _DATASET.findall(text):
        heading, stamp = name.split("_KWBN_")
        if _HEADING_ELEMENT[heading] not in elements:
            continue
        found.append(
            Listed(
                _HEADING_ELEMENT[heading],
                stamp_of(stamp),
                f"{NCEI_ROOT}/fileServer/{path}",
                Host.NCEI,
            )
        )
    return found


@dataclass(frozen=True, slots=True)
class Run:
    """One issuance: the three elements' files of one half hour."""

    time: datetime
    """The latest of the three stamps."""
    files: Mapping[Element, Listed]
    available_at: datetime
    """When it counts: its time plus the delay, and never before every file was published
    (:meth:`Listed.published_at`)."""
    archive_copy: bool = False
    """Some file is an archive copy (:meth:`Listed.archive_copy`)."""

    @property
    def host(self) -> Host:
        """Where its files were listed."""
        return self.files[Element.SNOW].host

    def age(self, at: datetime) -> timedelta:
        """How old it is at ``at``."""
        return at - self.time


def half_hour_of(moment: datetime) -> datetime:
    """The start of the half hour ``moment`` is in."""
    return moment.replace(minute=moment.minute - moment.minute % 30, second=0, microsecond=0)


@dataclass(frozen=True, slots=True)
class Assembled:
    """The runs of a listing, and the half hours that had some but not all three elements."""

    runs: tuple[Run, ...]
    incomplete: tuple[datetime, ...]


def assemble_runs(
    listed: Iterable[Listed], delay: timedelta = RUN_DELAY, fills: Collection[date] = ()
) -> Assembled:
    """Group listed files into runs (spec-f s. 4): the three elements in one half hour, the
    latest stamp of each element there; a half hour missing an element makes no run. ``fills``
    are the archive fill days (:func:`archive_fills`)."""
    by_half: dict[datetime, dict[Element, Listed]] = {}
    for item in listed:
        slot = by_half.setdefault(half_hour_of(item.stamp), {})
        known = slot.get(item.element)
        if known is None or item.stamp > known.stamp:
            slot[item.element] = item
    runs: list[Run] = []
    incomplete: list[datetime] = []
    for half in sorted(by_half):
        files = by_half[half]
        if len(files) < len(ELEMENTS):
            incomplete.append(half)
            continue
        run_time = max(item.stamp for item in files.values())
        written = [w for item in files.values() if (w := item.published_at(fills)) is not None]
        available = max([run_time + delay, *written])
        copy = any(item.archive_copy(fills) for item in files.values())
        runs.append(Run(run_time, dict(files), available, copy))
    return Assembled(tuple(runs), tuple(incomplete))


def newest_run(runs: Sequence[Run], at: datetime, max_age: timedelta = MAX_AGE) -> Run | None:
    """The newest run that counts at ``at`` and is at most ``max_age`` old, or ``None``."""
    best: Run | None = None
    for run in runs:
        if (
            run.available_at <= at
            and run.age(at) <= max_age
            and (best is None or run.time > best.time)
        ):
            best = run
    return best


# --- GRIB messages by range ---------------------------------------------------------------------

HEAD_BYTES: Final = 1024
"""Bytes read at a message's start: sections 0 to 4 of an NDFD message take about 200."""


class Ranged(Protocol):
    """Reads ``size`` bytes at ``offset`` of one file; fewer at its end, none past it."""

    def __call__(self, offset: int, size: int) -> bytes: ...


def bytes_reader(data: bytes) -> Ranged:
    """A :class:`Ranged` over bytes in memory (a whole file, or a test's)."""

    def read(offset: int, size: int) -> bytes:
        return data[offset : offset + size]

    return read


RANGE_ATTEMPTS: Final = 4
"""Tries of one range read that returned other bytes than asked (a cut connection, a server
answering short) before :class:`ShortReadError`."""
RANGE_PAUSE: Final = 2.0
"""Seconds before the second try; each later try waits twice as long (at most 30 s)."""


@dataclass(frozen=True, slots=True)
class RangeAnswer:
    """What a host sent for one range read: the bytes, where they start, and the file's size
    (``None`` when the host did not say)."""

    start: int
    data: bytes
    total: int | None
    past_end: bool = False
    """The host said the range starts past the file's end without saying the file's size (an
    S3 416): believed only when no earlier answer gave a size the range is inside."""
    whole: bool = False
    """The host sent the whole file (a 200), so ``total`` is the length of the body it sent:
    this answer is checked against it, but only a size the host said in a header (a 206's
    Content-Range or a 416's ``bytes */N``) holds for the file's later reads."""


def range_expected(offset: int, size: int, total: int) -> int:
    """The bytes a read of ``size`` at ``offset`` must return from a file of ``total`` bytes."""
    return max(0, min(size, total - offset))


def steady_reader(
    fetch: Callable[[int, int], RangeAnswer],
    attempts: int = RANGE_ATTEMPTS,
    pause: Callable[[float], None] | None = None,
) -> Ranged:
    """A :class:`Ranged` that checks every answer of ``fetch`` holds exactly the bytes the file
    holds at that range (all asked, or up to the file's end) and tries again politely when not:
    ``pause`` waits :data:`RANGE_PAUSE` s, then twice as long each time, at most 30 s. The
    file's size, once an answer says it in a header, holds for every later read of the file:
    an answer without one is checked against it, and an end of file said inside it is short. A
    whole-file answer's body length is never learned as the size (a body cut short but
    well-formed would set a wrong size for every later read); it is checked against a size
    already said, and an answer with no said size is checked against its own.

    Raises (from the reader):
        ShortReadError: ``attempts`` answers in a row were short or another range.
    """
    wait = pause if pause is not None else _sleep
    known: list[int] = []  # the file's size, from the first answer that said it in a header

    def read(offset: int, size: int) -> bytes:
        why = ""
        for attempt in range(max(1, attempts)):
            if attempt:
                wait(min(30.0, RANGE_PAUSE * 2.0 ** (attempt - 1)))
            answer = fetch(offset, size)
            if answer.total is not None and not answer.whole and not known:
                known.append(answer.total)
            if answer.start != offset:
                why = f"bytes from {answer.start}, asked from {offset}"
                continue
            if known and answer.total is not None and answer.total != known[0]:
                why = f"a file of {answer.total} bytes, earlier {known[0]}"
                continue
            total = known[0] if known else answer.total
            if answer.past_end and total is None:
                return b""  # no size ever given: the host's end of file is all there is
            want = size if total is None else range_expected(offset, size, total)
            if len(answer.data) == want:
                return answer.data
            why = f"{len(answer.data)} bytes at {offset}, the file holds {want} there"
        raise ShortReadError(f"{why} after {max(1, attempts)} tries")

    return read


def _sleep(seconds: float) -> None:  # pragma: no cover - real time
    import time  # noqa: PLC0415

    time.sleep(seconds)


_UNIT_SECONDS: Final[Mapping[int, int]] = {
    0: 60,
    1: 3600,
    2: 86400,
    10: 3 * 3600,
    11: 6 * 3600,
    12: 12 * 3600,
    13: 1,
}
"""GRIB2 code table 4.4: the unit of a forecast time, in seconds."""
_STATISTICAL: Final = 8
_PROBABILITY: Final = 9
_INSTANT: Final = 0
_RANGE_END: Final = 58
"""Template 4.8 with one time range ends at octet 58 (its length and increment)."""
_PROBABILITY_SHIFT: Final = 13
"""Template 4.9 is template 4.8 with the probability's 13 octets (35 to 47) before the end of
its interval, so each of 4.8's later octets sits 13 further on (GRIB2 code table 4.0)."""


@dataclass(frozen=True, slots=True)
class Head:
    """One GRIB2 message's place in its file and what it holds (sections 0, 1 and 4)."""

    offset: int
    length: int
    parameter: tuple[int, int, int]
    reference: datetime
    start: datetime
    """Reference time plus forecast time: the interval start (statistical), or the valid time."""
    end: datetime
    """The end of the overall interval (statistical), or the valid time (instant)."""
    template: int
    span: timedelta = timedelta(0)
    """The length of the statistical process (template 4.8's time range; zero when instant)."""

    @property
    def period_start(self) -> datetime:
        """The start of the period the message holds: its end less its span."""
        return self.end - self.span


def _need(raw: bytes, end: int, what: str) -> None:
    """Raise :class:`HeadError` unless ``raw`` holds ``end`` bytes (``what`` is cut short)."""
    if len(raw) < end:
        raise HeadError(f"{what} is cut short: {len(raw)} of its {end} bytes")


def _when(raw: bytes, at: int) -> datetime:
    _need(raw, at + 7, "a GRIB time")
    year = struct.unpack(">H", raw[at : at + 2])[0]
    month, day, hour, minute, second = raw[at + 2 : at + 7]
    try:
        return datetime(year, month, day, hour, minute, second, tzinfo=UTC)
    except ValueError as error:
        raise NdfdError(f"bad time {year}-{month}-{day} {hour}:{minute}:{second}") from error


def parse_head(raw: bytes, offset: int) -> Head:
    """Sections 0, 1 and 4 of the message starting at ``raw[0]`` (``offset`` in its file).

    Raises:
        HeadError: the head is cut short (the file ends inside it) or a section overruns it.
        NdfdError: it is not a GRIB2 message this module reads.
    """
    try:
        return _parse_head(raw, offset)
    except (struct.error, IndexError) as error:  # pragma: no cover - a bound the checks missed
        raise HeadError(f"a GRIB head at {offset} does not read: {error}") from error


def _parse_head(raw: bytes, offset: int) -> Head:
    """:func:`parse_head`'s reading.

    Raises:
        HeadError: the head is cut short (the file ends inside it) or a section overruns it.
        NdfdError: it is not a GRIB2 message this module reads.
    """
    if raw[:4] != b"GRIB":
        raise NdfdError("not a GRIB message")
    _need(raw, 16, "a GRIB section 0")
    if raw[7] != 2:  # noqa: PLR2004
        raise NdfdError(f"GRIB edition {raw[7]}, not 2")
    discipline = raw[6]
    length = struct.unpack(">Q", raw[8:16])[0]
    at = 16
    reference: datetime | None = None
    while at + 5 <= len(raw):
        size = struct.unpack(">I", raw[at : at + 4])[0]
        number = raw[at + 4]
        if size < 5:  # noqa: PLR2004
            raise HeadError("a GRIB section shorter than its header")
        if number in {1, 4}:
            _need(raw, at + size, f"GRIB section {number}")
            if at + size > length:
                raise HeadError(f"GRIB section {number} runs past its message's {length} bytes")
        if number == 1:
            reference = _when(raw, at + 12)
        elif number == 4:  # noqa: PLR2004
            return _section4(raw[at : at + size], offset, length, discipline, reference)
        elif number > 4:  # noqa: PLR2004
            break
        at += size
    if len(raw) < min(length, HEAD_BYTES):
        raise HeadError(f"the file ends {len(raw)} bytes into a message, before its section 4")
    if len(raw) < length:
        raise LongHeadError(f"section 4 is not in the message's first {len(raw)} bytes")
    raise HeadError("section 4 is not in the message's first bytes")


def _section4(
    raw: bytes, offset: int, length: int, discipline: int, reference: datetime | None
) -> Head:
    if reference is None:
        raise NdfdError("no section 1 before section 4")
    _need(raw, 22, "a GRIB section 4")
    template = struct.unpack(">H", raw[7:9])[0]
    category, number, unit = raw[9], raw[10], raw[17]
    if unit not in _UNIT_SECONDS:
        raise NdfdError(f"unknown time unit {unit}")
    lead = struct.unpack(">I", raw[18:22])[0] * _UNIT_SECONDS[unit]
    start = reference + timedelta(seconds=lead)
    span = timedelta(0)
    if template in {_STATISTICAL, _PROBABILITY}:
        shift = _PROBABILITY_SHIFT if template == _PROBABILITY else 0
        _need(raw, _RANGE_END + shift, f"a template 4.{template} section")
        if raw[41 + shift] != 1:
            raise NdfdError(f"a template 4.{template} message without exactly one time range")
        end = _when(raw, 34 + shift)
        span_unit = raw[48 + shift]
        if span_unit not in _UNIT_SECONDS:
            raise NdfdError(f"unknown time range unit {span_unit}")
        units = struct.unpack(">I", raw[49 + shift : 53 + shift])[0]
        span = timedelta(seconds=units * _UNIT_SECONDS[span_unit])
    elif template == _INSTANT:
        end = start
    else:
        raise NdfdError(f"product template 4.{template} is not read")
    return Head(
        offset, length, (discipline, category, number), reference, start, end, template, span
    )


LONG_HEAD_MAX: Final = 1 << 20
"""The most a message's sections 0 to 4 may take (a Wx file's weather strings in section 2 take
about 12 KB)."""


def head_bytes(read: Ranged, offset: int) -> bytes:
    """Sections 0 to 4 of the message at ``offset``, found by hopping over its sections (for a
    message whose section 2 is longer than :data:`HEAD_BYTES`).

    Raises:
        HeadError: the file ends inside them, or they are longer than :data:`LONG_HEAD_MAX`.
    """
    indicator = read(offset, 16)
    if len(indicator) < 16 or indicator[:4] != b"GRIB":  # noqa: PLR2004
        raise HeadError(f"no GRIB indicator at {offset}")
    length = min(struct.unpack(">Q", indicator[8:16])[0], LONG_HEAD_MAX)
    at = 16
    while at + 5 <= length:
        header = read(offset + at, 5)
        if len(header) < 5:  # noqa: PLR2004
            raise HeadError(f"the file ends inside the head of the message at {offset}")
        size, number = struct.unpack(">I", header[:4])[0], header[4]
        if size < 5 or number > 4:  # noqa: PLR2004
            break
        at += size
        if number == 4:  # noqa: PLR2004
            return read(offset, at)
    raise HeadError(f"section 4 is not in the head of the message at {offset}")


def walk(read: Ranged, stop: Callable[[Head], bool] | None = None) -> Iterator[Head]:
    """Every message head of a file, in order, by range reads (WMO framing skipped).

    ``stop`` ends the walk after the first head it accepts (that head is yielded).

    A walk that reaches the file's end checks the last message ends there in ``7777``, so a
    file cut inside a message's body is a cut file whether or not that message is ever read.

    Raises:
        HeadError: the file ends inside a frame, a message's head or the last message's body,
            or a head is malformed.
        NdfdError: bytes between messages are not a frame, or a head does not read.
    """
    offset = 0
    last: Head | None = None
    while True:
        raw = read(offset, HEAD_BYTES)
        if not raw and last is not None and read(offset - 4, HEAD_BYTES)[:4] != b"7777":
            raise HeadError(f"the file ends inside the message at {last.offset}")
        if not raw.strip(b"\r\n\x00 "):
            return
        found = raw.find(b"GRIB")
        if found < 0:
            if len(raw) < HEAD_BYTES:
                tail = raw.strip(b"\r\n\x00 ")
                # Any start of a frame line (``*`` to ``****...``) or of ``GRIB`` is a cut file.
                if tail.startswith(b"*") or b"****" in raw or tail.endswith((b"G", b"GR", b"GRI")):
                    raise HeadError(f"the file ends inside a frame or a GRIB start at {offset}")
                return
            raise NdfdError(f"no GRIB message within {HEAD_BYTES} bytes of {offset}")
        if found:
            offset += found
            raw = read(offset, HEAD_BYTES)
        try:
            head = parse_head(raw, offset)
        except LongHeadError:
            head = parse_head(head_bytes(read, offset), offset)
        last = head
        yield head
        if stop is not None and stop(head):
            return
        offset += head.length


def message(read: Ranged, head: Head) -> bytes:
    """The whole message ``head`` names.

    Raises:
        NdfdError: the file ends inside it, or it does not end in ``7777``.
    """
    raw = read(head.offset, head.length)
    if len(raw) != head.length or raw[-4:] != b"7777":
        raise NdfdError(f"message at {head.offset} is cut short")
    return raw


# --- decoding -----------------------------------------------------------------------------------


def _eccodes() -> Any:  # eccodes ships no types
    import eccodes  # type: ignore[import-untyped]  # noqa: PLC0415

    return eccodes


@dataclass(frozen=True, slots=True)
class Decoded:
    """One message's grid, rows south to north and every row west to east; NaN where the
    forecast has no value (a bitmap, or the packing's missing value)."""

    head: Head
    values: Floats


def _stamp_time(day: object, clock: object) -> datetime:
    """A time from eccodes' ``YYYYMMDD`` date and ``HHMM`` time keys."""
    return datetime.strptime(f"{int(str(day)):08d}{int(str(clock)):04d}", "%Y%m%d%H%M").replace(
        tzinfo=UTC
    )


def decode(raw: bytes, head: Head) -> Decoded:
    """Decode a message with eccodes, asserting the grid and the head.

    Raises:
        GridError: it is not on the NDFD grid.
        NdfdError: eccodes reads another parameter or time than its head.
    """
    codes = _eccodes()
    handle = codes.codes_new_from_message(raw)
    try:
        get = codes.codes_get
        for key, wanted in GRID_KEYS.items():
            found = get(handle, key)
            if abs(float(found) - float(wanted)) > _GRID_TOLERANCE * max(1.0, abs(wanted)):
                raise GridError(f"{key} is {found}, not {wanted}")
        if get(handle, "alternativeRowScanning") != 1:
            raise GridError("rows do not alternate")
        parameter = (
            int(get(handle, "discipline")),
            int(get(handle, "parameterCategory")),
            int(get(handle, "parameterNumber")),
        )
        if parameter != head.parameter:
            raise NdfdError(f"eccodes reads parameter {parameter}, the head {head.parameter}")
        reference = _stamp_time(get(handle, "dataDate"), get(handle, "dataTime"))
        valid = _stamp_time(get(handle, "validityDate"), get(handle, "validityTime"))
        if reference != head.reference or valid != head.end:
            raise NdfdError(
                f"eccodes reads {reference} to {valid}, the head {head.reference} to {head.end}"
            )
        values = np.array(codes.codes_get_values(handle), dtype=np.float64)
        # A bitmap and complex packing's missing value management both read as missingValue.
        values[values == float(get(handle, "missingValue"))] = np.nan
    finally:
        codes.codes_release(handle)
    if values.shape[0] != NX * NY:
        raise GridError(f"{values.shape[0]} values, not {NX * NY}")
    grid = values.reshape(NY, NX)
    grid[1::2] = grid[1::2, ::-1].copy()
    return Decoded(head, grid)


def weather_strings(raw: bytes) -> tuple[str, ...]:
    """The weather strings of an NDFD Wx message (``Lkly:S:-:<NoVis>:``), in the order its grid
    values index them. NDFD keeps them in section 2 (local use, version 1): a count of groups,
    then per group the number of characters (4 octets), a reference value (IEEE float), a
    binary scale factor (2 octets), the bits per character and the type of the original values
    (1: integers), and the characters simple packed; the strings end each in a zero.

    Raises:
        NdfdError: the message has no such section 2.
    """
    at = 16
    while at + 5 <= len(raw):
        size, number = struct.unpack(">I", raw[at : at + 4])[0], raw[at + 4]
        if size < 5 or at + size > len(raw):  # noqa: PLR2004
            break
        if number == 2:  # noqa: PLR2004
            return _string_table(raw[at : at + size])
        if number > 2:  # noqa: PLR2004
            break
        at += size
    raise NdfdError("no weather strings in section 2")


_GROUP_HEAD: Final = 12
_CHAR_BITS: Final = 8


def _string_table(section: bytes) -> tuple[str, ...]:
    if len(section) < 8 or section[5] != 1:  # noqa: PLR2004
        raise NdfdError("section 2 is not NDFD's local use version 1")
    groups = struct.unpack(">H", section[6:8])[0]
    at = 8
    codes: list[npt.NDArray[np.int64]] = []
    for _ in range(groups):
        if at + _GROUP_HEAD > len(section):
            raise NdfdError("section 2 ends inside a group's head")
        count = struct.unpack(">I", section[at : at + 4])[0]
        reference = struct.unpack(">f", section[at + 4 : at + 8])[0]
        scale = struct.unpack(">h", section[at + 8 : at + 10])[0]
        bits, kind = section[at + 10], section[at + 11]
        at += _GROUP_HEAD
        size = (count * bits + 7) // 8
        if (
            reference != 0
            or scale != 0
            or kind != 1
            or not 0 < bits <= _CHAR_BITS
            or at + size > len(section)
        ):
            raise NdfdError("section 2's characters are not simple packed integers")
        packed = np.unpackbits(np.frombuffer(section[at : at + size], dtype=np.uint8))
        rows = packed[: count * bits].reshape(count, bits).astype(np.int64)
        codes.append(rows @ (1 << np.arange(bits - 1, -1, -1, dtype=np.int64)))
        at += size
    text = bytes(np.concatenate(codes).astype(np.uint8).tolist()) if codes else b""
    try:
        strings = text.decode("ascii").split("\0")
    except UnicodeDecodeError as error:
        raise NdfdError("section 2's weather strings are not ASCII") from error
    if strings and strings[-1] == "":
        strings.pop()
    return tuple(strings)


# --- the window ---------------------------------------------------------------------------------

WINDOW_END_HOURS: Final = (6, 12, 18)
"""The snow and ice window: the 6-hour periods ending at these UTC hours on D."""
PERIOD: Final = timedelta(hours=6)
BUS_HOUR: Final = time(7, 0)
"""Apparent temperature is read at 07:00 local on D."""
REFERENCE_LEAD: Final = timedelta(hours=1)
"""A file's reference time is at or after its run's time and less than this after it."""


def window_ends(day: date) -> tuple[datetime, ...]:
    """The ends of the window's periods on ``day``."""
    return tuple(datetime.combine(day, time(hour), tzinfo=UTC) for hour in WINDOW_END_HOURS)


def bus_time(day: date, zone: str) -> datetime:
    """07:00 local on ``day`` in ``zone``, in UTC."""
    return datetime.combine(day, BUS_HOUR, tzinfo=ZoneInfo(zone)).astimezone(UTC)


def reference_ok(reference: datetime, run_time: datetime) -> bool:
    """Whether a file's reference time fits its run: at or after the run's time and less than
    :data:`REFERENCE_LEAD` after it. A file whose content was issued at another time (NCEI's
    ``201906030016`` and ``0017`` hold the run of 2019-07-03 00:30) is not that run."""
    return run_time <= reference < run_time + REFERENCE_LEAD


class PeriodStamp(StrEnum):
    """How a file's amount messages stamp their periods (section 4: reference time plus forecast
    time, the end of the interval, and its 6-hour length)."""

    START = "start"
    """From 2018-10-30 13:47Z: each message stamped at its period's start, the first at the
    reference time (inside its period)."""
    END = "end"
    """Until 2018-10-30 13:15Z: each message stamped at its period's end."""


def without_repeats(heads: Sequence[Head]) -> tuple[list[Head], list[Head]]:
    """A file's heads less the ones that repeat an earlier head (same parameter, times, span
    and length), and those repeats. Some NCEI files hold their messages twice (half the runs of
    2019-08-19 and 2019-09-09); a repeat is used only when its bytes equal the first's."""
    seen: set[tuple[object, ...]] = set()
    kept: list[Head] = []
    repeats: list[Head] = []
    for head in heads:
        key = (head.parameter, head.reference, head.start, head.end, head.span, head.length)
        (repeats if key in seen else kept).append(head)
        seen.add(key)
    return kept, repeats


def period_stamp(heads: Sequence[Head]) -> PeriodStamp:
    """Check that a file's amount messages are whole 6-hour periods ending at 00, 06, 12 or 18Z,
    one reference time, ends rising, the first the period under way at the reference time; and
    say how they are stamped. Either stamp reads as the period ending at each message's end.

    Raises:
        PeriodError: the file holds no message, or one that does not fit.
    """
    if not heads:
        raise PeriodError("no amount message")
    first = heads[0]
    for head in heads:
        if head.template != _STATISTICAL or head.span != PERIOD:
            raise PeriodError(f"a {head.span} period to {head.end:%Y-%m-%d %H:%M}Z, not 6 hours")
        if head.end.hour % 6 or head.end.minute or head.end.second:
            raise PeriodError(f"a period ending {head.end:%Y-%m-%d %H:%M}Z, off the hours")
        if head.reference != first.reference:
            raise PeriodError(f"two reference times, {first.reference} and {head.reference}")
    if any(later.end <= earlier.end for earlier, later in itertools.pairwise(heads)):
        raise PeriodError("period ends that do not rise")
    if not first.reference < first.end <= first.reference + PERIOD:
        raise PeriodError(
            f"the first period ends {first.end:%Y-%m-%d %H:%M}Z, not the one under way at "
            f"{first.reference:%Y-%m-%d %H:%M}Z"
        )
    if all(head.start == head.end for head in heads):
        return PeriodStamp.END
    if first.start == first.reference and all(
        head.start == head.period_start for head in heads[1:]
    ):
        return PeriodStamp.START
    raise PeriodError(f"periods stamped neither at their start nor at their end ({first.start})")


def amount_heads(heads: Sequence[Head], day: date) -> dict[datetime, Head]:
    """The run's messages of the window's periods on ``day``, by period end."""
    ends = set(window_ends(day))
    return {head.end: head for head in heads if head.end in ends}


def apt_heads(heads: Sequence[Head], at: Iterable[datetime]) -> dict[datetime, Head]:
    """The run's apparent temperature messages valid at each time of ``at``."""
    wanted = set(at)
    return {head.end: head for head in heads if head.end in wanted}


def window_total(by_end: Mapping[datetime, Floats], day: date, as_of: datetime) -> Floats | None:
    """The sum of the window's periods not ended by ``as_of``; ``None`` when a period the window
    needs is not in the run. All ended: zeros of the right length (or ``None`` with no data)."""
    needed = [end for end in window_ends(day) if end > as_of]
    if any(end not in by_end for end in needed):
        return None
    if not needed:
        first = next(iter(by_end.values()), None)
        return None if first is None else np.zeros_like(first)
    total = np.zeros_like(by_end[needed[0]])
    for end in needed:
        total = total + by_end[end]
    return total


# --- units, districts and buckets ---------------------------------------------------------------

INCHES_PER_METRE: Final = 1 / 0.0254
MM_PER_INCH: Final = 25.4
_ROUND: Final = 6


def snow_inches(metres: Floats) -> Floats:
    """Snow amount in inches (rounded to a millionth, so a bucket bound is exact)."""
    return np.round(metres * INCHES_PER_METRE, _ROUND)


def ice_inches(millimetres: Floats) -> Floats:
    """Ice accumulation in inches."""
    return np.round(millimetres / MM_PER_INCH, _ROUND)


def fahrenheit(kelvin: Floats) -> Floats:
    """Kelvin in Fahrenheit."""
    return np.round((kelvin - 273.15) * 9 / 5 + 32, _ROUND)


@dataclass(frozen=True, slots=True)
class Groups:
    """Points grouped by district: ``order`` sorts the points by group; ``starts`` and
    ``counts`` mark each group's run in that order; ``ids`` the group of each run."""

    order: Ints
    starts: Ints
    counts: Ints
    ids: Ints


def groups_of(group: Ints) -> Groups:
    """The grouping of points by ``group`` (a district index per point)."""
    order = np.argsort(group, kind="stable")
    ids, starts, counts = np.unique(group[order], return_index=True, return_counts=True)
    return Groups(order.astype(np.int64), starts.astype(np.int64), counts.astype(np.int64), ids)


def group_half(values: Floats, groups: Groups, share: float = 0.5, coldest: bool = False) -> Floats:
    """Each group's 50% value (spec-f s. 4): the largest amount at least ``share`` of its points
    reach (``coldest``: the coldest value at least ``share`` reach, as cold or colder). NaN when a
    point of the group has no value."""
    ordered = values[groups.order]
    key = ordered if coldest else -ordered
    group = np.repeat(np.arange(groups.ids.shape[0]), groups.counts)
    missing = np.isnan(ordered)
    within = np.lexsort((np.where(missing, np.inf, key), group))
    needed = np.maximum(np.ceil(share * groups.counts - 1e-9).astype(np.int64), 1)
    found = ordered[within[groups.starts + needed - 1]]
    has_missing = np.add.reduceat(missing.astype(np.int64), groups.starts) > 0
    return np.where(has_missing, np.nan, found)


def group_min_max(values: Floats, groups: Groups) -> tuple[Floats, Floats]:
    """Each group's lowest and highest value; NaN when a point has none."""
    ordered = values[groups.order]
    return np.minimum.reduceat(ordered, groups.starts), np.maximum.reduceat(ordered, groups.starts)


class Bucket(IntEnum):
    """A district's forecast bucket (spec-f s. 4)."""

    QUIET = 0
    SNOW_HALF = 1
    SNOW_2 = 2
    SNOW_4 = 3
    SNOW_6 = 4
    SNOW_9 = 5
    ICE_TRACE = 6
    ICE_TENTH = 7
    ICE_QUARTER = 8
    FEELS_10 = 9
    FEELS_0 = 10
    FEELS_MINUS_10 = 11
    FEELS_MINUS_20 = 12
    UNKNOWN = 13


SNOW_FROM: Final = (0.5, 2.0, 4.0, 6.0, 9.0)
"""Lower bounds (inches, included) of snow buckets 1 to 5."""
ICE_FROM: Final = (0.01, 0.10, 0.25)
"""Lower bounds (inches, included) of ice buckets 6 to 8."""
FEELS_TO: Final = (10.0, 0.0, -10.0, -20.0)
"""Upper bounds (F, included: the warmer end) of feels buckets 9 to 12."""
PRIORITY: Final = (8, 7, 5, 4, 3, 2, 1, 6, 12, 11, 10, 9, 0)
"""Strongest first; unknown (13) comes only from an undecided value."""
_RANK: Final = np.array([PRIORITY.index(code) for code in range(13)], dtype=np.int64)
_NONE: Final = -1
_UNSET: Final = -2


def snow_bucket(inches: Floats) -> Ints:
    """1-5 by :data:`SNOW_FROM`, -1 below the first bound, -2 unknown (NaN)."""
    found = np.searchsorted(np.array(SNOW_FROM), inches, side="right").astype(np.int64)
    return np.where(np.isnan(inches), _UNSET, np.where(found == 0, _NONE, found))


def ice_bucket(inches: Floats) -> Ints:
    """6-8 by :data:`ICE_FROM`, -1 below, -2 unknown."""
    found = np.searchsorted(np.array(ICE_FROM), inches, side="right").astype(np.int64)
    return np.where(np.isnan(inches), _UNSET, np.where(found == 0, _NONE, found + 5))


def feels_bucket(degrees: Floats) -> Ints:
    """9-12 by :data:`FEELS_TO`, -1 warmer than 10 F, -2 unknown."""
    colder = -np.asarray(degrees)
    found = np.searchsorted(-np.array(FEELS_TO), colder, side="right").astype(np.int64)
    return np.where(np.isnan(degrees), _UNSET, np.where(found == 0, _NONE, found + 8))


_BEST: Final = (int(_RANK[8]), int(_RANK[5]), int(_RANK[12]))
"""The strongest rank ice, snow and feels can reach."""


def bucket_codes(snow_in: Floats, ice_in: Floats, feels_f: Floats) -> npt.NDArray[np.int8]:
    """Each district's bucket: the strongest of its three by :data:`PRIORITY`; 0 when none;
    13 when an unknown value could change the answer (it could be stronger than the known)."""
    ranks = []
    unknown = []
    for found in (ice_bucket(ice_in), snow_bucket(snow_in), feels_bucket(feels_f)):
        ranks.append(np.where(found >= 0, _RANK[np.maximum(found, 0)], _RANK[0]))
        unknown.append(found == _UNSET)
    best = np.minimum.reduce(ranks)
    undecided = np.zeros_like(best, dtype=np.bool_)
    for is_unknown, strongest in zip(unknown, _BEST, strict=True):
        undecided |= is_unknown & (best > strongest)
    codes = np.array(PRIORITY, dtype=np.int64)[best]
    return np.where(undecided, int(Bucket.UNKNOWN), codes).astype(np.int8)
