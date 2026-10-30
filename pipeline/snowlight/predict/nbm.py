"""NOAA's National Blend of Models (NBM) on AWS: the deterministic 1-hour snowfall the night chart
draws (option (iv), docs/predict.md "The night chart"; design spec chart-data r3, 4.8).

The bucket ``noaa-nbm-grib2-pds`` is public (no key, no cost). A cycle runs every hour; its CONUS
core files ``blend.YYYYMMDD/HH/core/blend.tHHz.core.fFFF.co.grib2`` (with an ``.idx``) are hourly
from f001 to f036. File ``fFFF`` holds the hour ending FFF hours after the cycle, and its
deterministic 1-hour snowfall is the one message whose ``.idx`` line is exactly
``ASNOW:surface:{F-1}-{F} hour acc fcst:`` (the percentile, probability and 6-hour lines beside
it never match). Only that message is read, by range (about 0.5 to 0.65 MB), never a whole file
(166 to 202 MB).

The grid is NDFD's own Lambert projection, 2345 x 1597, its first point about 200 columns west
of NDFD's. Each point's cell is the nearest to it from NBM's own first point (:func:`cells`),
never NDFD's cell shifted: the two first points are 200.003 columns and 0.002 rows apart, so a
shifted NDFD cell is a neighbour for about 0.4% of schools (critic r1 S1). Every message read is
held to the grid (:data:`GRID_KEYS`, a :class:`~snowlight.predict.ndfd.GridError` otherwise), to its
parameter (GRIB2 0/1/29, template 4.8, an accumulation of one hour) and to its cycle and hour;
odd rows are reversed, as in NDFD.

Every read of a pass runs inside one time :class:`Budget` (:data:`READ_SECONDS`) through
:class:`NbmHttp`: two tries, short timeouts, the budget checked before every request, every wait
and every chunk of a body, a body never past its cap, and a range read answered with the whole
file refused unread. So a bucket that is slow, hanging or down holds a pass back by at most the
budget and one chunk's timeout, and never makes it download a whole core file (critic r1 B1,
G1 and S2).

A cycle counts at a moment once every file a pass needs, and its ``.idx``, is listed with an S3
``LastModified`` at or before it (a cycle's files post over up to about half an hour, and f036
is often not the last: critic 3's B3). A pass picks one cycle, the newest that counts and is at
most ``max_age`` old (:func:`choose_cycle`), for every night of its file.
"""

import math
import re
import time
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import httpx
import numpy as np

from snowlight.predict import ndfd
from snowlight.predict.ndfd import Cells, Floats, Ranged

BUCKET_ROOT: Final = "https://noaa-nbm-grib2-pds.s3.amazonaws.com"
NX: Final = 2345
NY: Final = 1597
LA1_DEG: Final = 19.229
LO1_DEG: Final = 233.7234
"""NBM's first grid point (south-west corner), as every message states it (:data:`GRID_KEYS`)."""
FIRST_HOUR: Final = 1
LAST_HOUR: Final = 36
"""The core files are hourly from f001 to f036 in every cycle."""
PARAMETER: Final = (0, 1, 29)
"""Total snowfall, metres (the same parameter as NDFD's snow)."""
GRID_KEYS: Final[Mapping[str, float]] = {
    "gridDefinitionTemplateNumber": 30,
    "Nx": NX,
    "Ny": NY,
    "LaDInDegrees": ndfd.LATIN_DEG,
    "LoVInDegrees": ndfd.LOV_DEG,
    "Latin1InDegrees": ndfd.LATIN_DEG,
    "Latin2InDegrees": ndfd.LATIN_DEG,
    "latitudeOfFirstGridPointInDegrees": LA1_DEG,
    "longitudeOfFirstGridPointInDegrees": LO1_DEG,
    "DxInMetres": ndfd.DX_M,
    "DyInMetres": ndfd.DX_M,
    "radius": ndfd.RADIUS_M,
    "scanningMode": ndfd.SCANNING_MODE,
}
"""Every grid key a message must carry, and its value."""
_TOLERANCE: Final = 1e-6
_HOUR: Final = timedelta(hours=1)
_KEYS_PER_HOUR: Final = 12
"""Keys a forecast hour holds in a core listing: six domains, each a file and its ``.idx``."""


class NbmError(ndfd.NdfdError):
    """The blend cannot give the night chart (the code is the pass's withheld code)."""

    code = "nbm_unreadable"


class NbmStaleError(NbmError):
    """No cycle at most ``max_age`` old has every file the pass needs listed."""

    code = "nbm_stale"


class NbmUnreadableError(NbmError):
    """A listing or read failed, or an ``.idx`` holds no one matching line."""

    code = "nbm_unreadable"


class NbmSlowError(NbmError):
    """The pass's time for the blend's reads is up (:class:`Budget`)."""

    code = "nbm_slow"


READ_SECONDS: Final = 60.0
"""A pass's time for every blend read of its night stage (listings, ``.idx`` files and
messages). A cold pass reads about 30 requests and 9 MB; what it read before the time is up is
kept, so the next pass goes on from there."""
READ_TIMEOUT: Final = httpx.Timeout(10.0, connect=5.0)
"""One request's limits (as the outlook's NDFD reads): a hanging host costs at most these."""
READ_ATTEMPTS: Final = 2
"""Tries per request (one retry), as the outlook's NDFD reads."""
MAX_GET_BYTES: Final = 4_000_000
"""A listing page (about 130 KB) or an ``.idx`` (about 11 KB) is never read past this."""


@dataclass
class Budget:
    """A pass's time for the blend's reads: :meth:`start` once per pass, :meth:`check` before
    every request, every wait and every chunk of a body."""

    seconds: float = READ_SECONDS
    clock: Callable[[], float] = time.monotonic
    until: float = math.inf

    def start(self) -> None:
        """Start the pass's time."""
        self.until = self.clock() + self.seconds

    def check(self) -> None:
        """Raises:
        NbmSlowError: the pass's time for blend reads is up.
        """
        if self.clock() >= self.until:
            raise NbmSlowError(f"the night chart's {self.seconds:.0f} s of blend reads are up")


_CONTENT_RANGE: Final = re.compile(r"bytes (\d+)-(\d+)/(\d+|\*)")


class NbmHttp:
    """The blend's GETs and range reads inside a :class:`Budget` (the pipeline's client: its
    User-Agent; :data:`READ_TIMEOUT` and :data:`READ_ATTEMPTS`). A range read must be answered
    with that range (a 206): a host that sends the whole file (a 200) is refused before its
    body is read. ``sleep`` waits between tries (the budget is checked before)."""

    def __init__(
        self,
        client: httpx.Client,
        budget: Budget,
        *,
        attempts: int = READ_ATTEMPTS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self.budget = budget
        self.attempts = attempts
        self.sleep = sleep

    def _wait(self, seconds: float) -> None:
        self.budget.check()
        self.sleep(seconds)

    def _read(self, url: str, headers: Mapping[str, str], most: int) -> httpx.Response:
        """One answer (status, headers and a body of at most ``most`` bytes), tried again on a
        transport error, a 5xx or a 429.

        Raises:
            NbmSlowError: the budget is up.
            NbmUnreadableError: no answer, a body past ``most``, or a whole file for a range.
        """
        error: Exception | None = None
        for attempt in range(max(1, self.attempts)):
            if attempt:
                self._wait(min(8.0, 2.0 ** (attempt - 1)))
            self.budget.check()
            try:
                with self.client.stream("GET", url, headers=dict(headers)) as response:
                    status = response.status_code
                    if status >= 500 or status == 429:  # noqa: PLR2004
                        error = RuntimeError(f"HTTP {status}")
                        continue
                    if "Range" in headers and status == httpx.codes.OK:
                        raise NbmUnreadableError(f"{url}: the whole file for a range read")
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        self.budget.check()
                        body += chunk
                        if len(body) > most:
                            raise NbmUnreadableError(f"{url}: more than {most:,} bytes")
                    return httpx.Response(status, headers=response.headers, content=bytes(body))
            except httpx.HTTPError as failed:
                error = failed
        raise NbmUnreadableError(f"{url}: {error}")

    def get(self, url: str) -> bytes:
        """The body of a 200.

        Raises:
            ndfd.NotFoundError: it answered 404.
            NbmUnreadableError: it never answered 200 (or the body is past its cap).
            NbmSlowError: the budget is up.
        """
        response = self._read(url, {}, MAX_GET_BYTES)
        if response.status_code == httpx.codes.NOT_FOUND:
            raise ndfd.NotFoundError(f"HTTP 404 for {url}")
        if response.status_code != httpx.codes.OK:
            raise NbmUnreadableError(f"HTTP {response.status_code} for {url}")
        return response.content

    def ranged(self, url: str) -> Ranged:
        """Range reads of one file, each checked to hold the bytes the file holds there
        (:func:`snowlight.predict.ndfd.steady_reader`, at most :data:`READ_ATTEMPTS` tries)."""

        def fetch(offset: int, size: int) -> ndfd.RangeAnswer:
            headers = {"Range": f"bytes={offset}-{offset + size - 1}"}
            response = self._read(url, headers, size)
            if response.status_code != httpx.codes.PARTIAL_CONTENT:
                raise NbmUnreadableError(f"HTTP {response.status_code} for a range of {url}")
            said = _CONTENT_RANGE.fullmatch(response.headers.get("content-range", "").strip())
            if said is None:
                return ndfd.RangeAnswer(-1, response.content, None)
            total = None if said[3] == "*" else int(said[3])
            return ndfd.RangeAnswer(int(said[1]), response.content, total)

        return ndfd.steady_reader(fetch, self.attempts, self._wait)


def core_prefix(cycle: datetime) -> str:
    """The key prefix of a cycle's core files, up to the forecast hour."""
    return f"blend.{cycle:%Y%m%d}/{cycle:%H}/core/blend.t{cycle:%H}z.core.f"


def core_key(cycle: datetime, hour: int) -> str:
    """The CONUS core file of a cycle's forecast hour."""
    return f"{core_prefix(cycle)}{hour:03d}.co.grib2"


def core_url(cycle: datetime, hour: int) -> str:
    """Where :func:`core_key` is."""
    return f"{BUCKET_ROOT}/{core_key(cycle, hour)}"


def listing_url(cycle: datetime, first: int, last: int, token: str | None = None) -> str:
    """One S3 listing of a cycle's core keys from forecast hour ``first`` to ``last`` (all six
    domains, in key order)."""
    prefix = core_prefix(cycle)
    url = (
        f"{BUCKET_ROOT}/?list-type=2&prefix={prefix}&start-after={prefix}{first - 1:03d}"
        f"&max-keys={(last - first + 1) * _KEYS_PER_HOUR}"
    )
    return url if token is None else f"{url}&continuation-token={_quote(token)}"


def _quote(text: str) -> str:
    from urllib.parse import quote  # noqa: PLC0415

    return quote(text, safe="")


_BLOCK: Final = re.compile(r"<Contents>(.*?)</Contents>", re.DOTALL)
_KEY: Final = re.compile(r"<Key>([^<]+)</Key>")
_MODIFIED: Final = re.compile(r"<LastModified>([^<]+)</LastModified>")
_SIZE: Final = re.compile(r"<Size>(\d+)</Size>")
_TOKEN: Final = re.compile(r"<NextContinuationToken>([^<]+)</NextContinuationToken>")
_CORE: Final = re.compile(r"core\.f(\d{3})\.co\.grib2(\.idx)?$")


@dataclass(slots=True)
class Posted:
    """What a cycle's listing says of its CONUS core files: each forecast hour's file and
    ``.idx`` post time, and the file's size."""

    grib: dict[int, datetime] = field(default_factory=dict)
    idx: dict[int, datetime] = field(default_factory=dict)
    size: dict[int, int] = field(default_factory=dict)
    last_listed: int = 0
    """The highest forecast hour the listing reached (any domain)."""

    def counts(self, hours: Collection[int], at: datetime) -> bool:
        """Whether every hour's file and ``.idx`` is listed and posted at or before ``at``."""
        return all(
            hour in self.grib
            and hour in self.idx
            and self.grib[hour] <= at
            and self.idx[hour] <= at
            for hour in hours
        )


def parse_listing(xml: bytes, posted: Posted) -> str | None:
    """Add one S3 listing page's CONUS core files to ``posted``; the next page's token, or None.

    Raises:
        NbmUnreadableError: the page is not an S3 listing.
    """
    text = xml.decode("utf-8", errors="replace")
    if "<ListBucketResult" not in text:
        raise NbmUnreadableError("a blend listing is not an S3 listing")
    for block in _BLOCK.findall(text):
        key, modified, size = _KEY.search(block), _MODIFIED.search(block), _SIZE.search(block)
        if key is None or modified is None:
            continue
        found = re.search(r"core\.f(\d{3})\.", key.group(1))
        if found is not None:
            posted.last_listed = max(posted.last_listed, int(found.group(1)))
        core = _CORE.search(key.group(1))
        if core is None:
            continue
        hour = int(core.group(1))
        when = datetime.fromisoformat(modified.group(1).replace("Z", "+00:00")).astimezone(UTC)
        if core.group(2):
            posted.idx[hour] = when
        else:
            posted.grib[hour] = when
            if size is not None:
                posted.size[hour] = int(size.group(1))
    token = _TOKEN.search(text)
    return None if token is None else token.group(1)


def forecast_hour(cycle: datetime, hour: datetime) -> int:
    """The core file that holds the hour from ``hour`` to an hour later: f = hours after the
    cycle + 1."""
    return round((hour - cycle) / _HOUR) + 1


def floor_hour(moment: datetime) -> datetime:
    """The whole hour at or before a moment, in UTC."""
    return moment.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def choose_cycle(
    hours: Collection[datetime],
    at: datetime,
    max_age: timedelta,
    posted: Callable[[datetime, int, int], Posted],
    *,
    frozen: timedelta | None = None,
) -> datetime | None:
    """The newest cycle at most ``max_age`` old (cycle hour to ``at``) whose every needed core
    file and ``.idx`` (the hours ``hours`` start) is posted at or before ``at``; None if none is.
    ``frozen`` (GC4's frozen listing): the listing hides every file posted less than this long
    before ``at``, as if no cycle had posted since.

    Raises (from ``posted``):
        NbmUnreadableError: a listing failed.
    """
    if not hours:
        return None
    seen = at if frozen is None else at - frozen
    cycle = floor_hour(at)
    while at - cycle <= max_age:
        needed = {forecast_hour(cycle, hour) for hour in hours}
        if min(needed) >= FIRST_HOUR and max(needed) <= LAST_HOUR:
            found = posted(cycle, min(needed), max(needed))
            if found.counts(needed, seen):
                return cycle
        cycle -= _HOUR
    return None


def asnow_line(hour: int) -> str:
    """The ``.idx`` line of a core file's deterministic 1-hour snowfall, after its offset and
    reference time."""
    return f"ASNOW:surface:{hour - 1}-{hour} hour acc fcst:"


def pick(idx: bytes, hour: int, size: int | None) -> tuple[int, int]:
    """The offset and length of the 1-hour snowfall message an ``.idx`` lists.

    Raises:
        NbmUnreadableError: the ``.idx`` holds no line, or more than one, equal to
            :func:`asnow_line`, or its offsets do not read.
    """
    want = asnow_line(hour)
    rows = [line.split(":") for line in idx.decode("ascii", errors="replace").splitlines() if line]
    hits = [k for k, row in enumerate(rows) if ":".join(row[3:]) == want]
    if len(hits) != 1:
        raise NbmUnreadableError(f"f{hour:03d}.idx holds {len(hits)} lines of {want!r}")
    k = hits[0]
    try:
        offset = int(rows[k][1])
        end = int(rows[k + 1][1]) if k + 1 < len(rows) else size
    except (IndexError, ValueError) as error:
        raise NbmUnreadableError(f"f{hour:03d}.idx: an offset does not read") from error
    if end is None or end <= offset:
        raise NbmUnreadableError(f"f{hour:03d}.idx: the message has no length")
    return offset, end - offset


def _eccodes() -> Any:  # eccodes ships no types
    import eccodes  # type: ignore[import-untyped]  # noqa: PLC0415

    return eccodes


def decode(raw: bytes, cycle: datetime, hour: int) -> Floats:
    """A 1-hour snowfall message's grid in metres, rows south to north and every row west to
    east, NaN where missing.

    Raises:
        ndfd.GridError: it is not on the NBM grid.
        NbmUnreadableError: it is another parameter, template, accumulation, cycle or hour.
    """
    if raw[:4] != b"GRIB" or raw[-4:] != b"7777":
        raise NbmUnreadableError(f"f{hour:03d}: the range read is not one GRIB message")
    codes = _eccodes()
    handle = codes.codes_new_from_message(raw)
    try:
        get = codes.codes_get
        for key, wanted in GRID_KEYS.items():
            found = get(handle, key)
            if abs(float(found) - float(wanted)) > _TOLERANCE * max(1.0, abs(wanted)):
                raise ndfd.GridError(f"{key} is {found}, not {wanted}")
        if get(handle, "alternativeRowScanning") != 1:
            raise ndfd.GridError("rows do not alternate")
        parameter = (
            int(get(handle, "discipline")),
            int(get(handle, "parameterCategory")),
            int(get(handle, "parameterNumber")),
        )
        if parameter != PARAMETER:
            raise NbmUnreadableError(f"f{hour:03d}: parameter {parameter}, not {PARAMETER}")
        if int(get(handle, "productDefinitionTemplateNumber")) != 8:  # noqa: PLR2004
            raise NbmUnreadableError(f"f{hour:03d}: not a template 4.8 accumulation")
        if int(get(handle, "typeOfStatisticalProcessing")) != 1:
            raise NbmUnreadableError(f"f{hour:03d}: not an accumulation")
        span = timedelta(
            seconds=int(get(handle, "lengthOfTimeRange"))
            * _UNIT_SECONDS.get(int(get(handle, "indicatorOfUnitForTimeRange")), 0)
        )
        if span != _HOUR:
            raise NbmUnreadableError(f"f{hour:03d}: a {span} accumulation, not one hour")
        reference = ndfd._stamp_time(get(handle, "dataDate"), get(handle, "dataTime"))
        valid = ndfd._stamp_time(get(handle, "validityDate"), get(handle, "validityTime"))
        if reference != cycle or valid != cycle + hour * _HOUR:
            raise NbmUnreadableError(
                f"f{hour:03d}: cycle {reference} valid {valid}, not {cycle} f{hour}"
            )
        values = np.array(codes.codes_get_values(handle), dtype=np.float64)
        values[values == float(get(handle, "missingValue"))] = np.nan
    finally:
        codes.codes_release(handle)
    if values.shape[0] != NX * NY:
        raise ndfd.GridError(f"{values.shape[0]} values, not {NX * NY}")
    grid = values.reshape(NY, NX)
    grid[1::2] = grid[1::2, ::-1].copy()
    return grid


_UNIT_SECONDS: Final[Mapping[int, int]] = {0: 60, 1: 3600, 13: 1}
"""GRIB2 code table 4.4, the units an hour's accumulation is stated in."""


def _first_point() -> tuple[float, float]:
    x, y = ndfd._project(np.array([LA1_DEG]), np.array([LO1_DEG]))
    return float(x[0]), float(y[0])


_X0, _Y0 = _first_point()


def cells(lat: Floats, lon: Floats) -> Cells:
    """The NBM cell nearest each point (degrees; longitude east, either sign), counted from
    NBM's own first point on the shared Lambert projection; ``inside`` false off the grid."""
    x, y = ndfd._project(np.asarray(lat, dtype=np.float64), np.asarray(lon, dtype=np.float64))
    col = np.rint((x - _X0) / ndfd.DX_M).astype(np.int64)
    row = np.rint((y - _Y0) / ndfd.DX_M).astype(np.int64)
    inside = (col >= 0) & (col < NX) & (row >= 0) & (row < NY)
    return Cells(np.where(inside, row, 0), np.where(inside, col, 0), inside)


def sample(grid: Floats, where: Cells) -> Floats:
    """The grid's value at each cell in inches, converted from metres and never rounded (so a
    sum of hours is the sum of NBM's own amounts, converted once: critic r1 B1); NaN off the
    grid or where missing."""
    return np.where(where.inside, grid[where.row, where.col] * ndfd.INCHES_PER_METRE, np.nan)


type Get = Callable[[str], bytes]
type Ranges = Callable[[str], Ranged]


Stamp = tuple[datetime, int | None, datetime]
"""A core file as a listing gives it: the file's LastModified and size, and its ``.idx``'s."""


class NbmReader:
    """The blend's 1-hour snowfall at a set of points, read politely: each pass lists the cycles
    it weighs afresh (a listing page or two each), and reads one ``.idx`` and one range per
    (cycle, hour) it has not read as the listing now stamps it, so a later pass on the same
    cycle reads no message again, and a file NOAA posts anew under the same cycle (a new
    LastModified or size) is read anew, never served from the old one's values (critic r2 S2).
    ``get`` and ``ranged`` are the pipeline's fetcher (its User-Agent, retries and range
    checks)."""

    def __init__(self, get: Get, ranged: Ranges) -> None:
        self._get = get
        self._ranged = ranged
        self._posted: dict[datetime, Posted] = {}
        self._values: dict[tuple[datetime, int], tuple[Stamp, Floats]] = {}
        self._where: tuple[bytes, Cells] | None = None
        self.requests = 0
        self.bytes = 0

    def posted(self, cycle: datetime, first: int, last: int) -> Posted:
        """The cycle's listing from hour ``first`` to ``last``, listed now: a listing held from
        an earlier pass could hide a file posted anew since.

        Raises:
            NbmUnreadableError: a listing failed.
        """
        found = Posted()
        token: str | None = None
        for _page in range(8):
            try:
                xml = self._get(listing_url(cycle, first, last, token))
            except NbmError:
                raise
            except (OSError, ndfd.NdfdError) as error:
                raise NbmUnreadableError(f"the {cycle:%Y-%m-%d %HZ} listing: {error}") from error
            self.requests += 1
            self.bytes += len(xml)
            token = parse_listing(xml, found)
            if token is None or found.last_listed > last:
                break
        self._posted[cycle] = found
        return found

    def read(  # noqa: PLR0913 - the points, the hours, the moment, the cap and the hook
        self,
        lat: Floats,
        lon: Floats,
        hours: Collection[datetime],
        at: datetime,
        max_age: timedelta,
        *,
        frozen: timedelta | None = None,
    ) -> tuple[datetime, dict[datetime, Floats]]:
        """The newest counting cycle (:func:`choose_cycle`) and, for each hour, the 1-hour
        snowfall (inches) at each point, NaN off the grid or missing.

        Raises:
            NbmStaleError: no cycle at most ``max_age`` old counts.
            NbmUnreadableError: a listing, ``.idx`` or range read failed.
            ndfd.GridError: a message is off the grid.
        """
        cycle = choose_cycle(hours, at, max_age, self.posted, frozen=frozen)
        if cycle is None:
            raise NbmStaleError(f"no blend cycle within {max_age} of {at:%Y-%m-%d %H:%MZ}")
        where = self._cells(lat, lon)
        listed = self._posted[cycle]
        found: dict[datetime, Floats] = {}
        for hour in sorted(hours):
            f = forecast_hour(cycle, hour)
            key = (cycle, f)
            stamp: Stamp = (listed.grib[f], listed.size.get(f), listed.idx[f])
            held = self._values.get(key)
            if held is None or held[0] != stamp:
                held = (stamp, sample(self._message(cycle, f), where))
                self._values[key] = held
            found[hour] = held[1]
        for old in [k for k in self._values if k[0] < cycle - timedelta(days=2)]:
            del self._values[old]
        for stale in [c for c in self._posted if c < cycle - timedelta(days=2)]:
            del self._posted[stale]
        return cycle, found

    def _cells(self, lat: Floats, lon: Floats) -> Cells:
        key = np.ascontiguousarray(lat).tobytes() + np.ascontiguousarray(lon).tobytes()
        if self._where is None or self._where[0] != key:
            self._where = (key, cells(lat, lon))
            self._values.clear()
        return self._where[1]

    def _message(self, cycle: datetime, hour: int) -> Floats:
        url = core_url(cycle, hour)
        try:
            idx = self._get(f"{url}.idx")
            self.requests += 1
            self.bytes += len(idx)
            offset, size = pick(idx, hour, self._posted.get(cycle, Posted()).size.get(hour))
            raw = self._ranged(url)(offset, size)
        except NbmError:
            raise
        except (OSError, ndfd.NdfdError) as error:
            raise NbmUnreadableError(f"f{hour:03d} of {cycle:%Y-%m-%d %HZ}: {error}") from error
        self.requests += 1
        self.bytes += len(raw)
        if len(raw) != size:
            raise NbmUnreadableError(f"f{hour:03d}: {len(raw)} bytes read of {size}")
        return decode(raw, cycle, hour)
