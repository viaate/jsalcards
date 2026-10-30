"""GC1, the night chart's truth gate (design spec chart-data r3, 6.3): every night of a file is
checked against NOAA's blend itself, freshly listed, read and decoded, by a second
implementation of the rule that shares no code with the one that made it.

It is grown from the design probe ``scripts/probe_nbm.py`` (its reader and its rule), and may
import only NDFD's tested reading primitive :func:`~snowlight.predict.ndfd.cells` (a first guess
of each school's cell, which it then corrects from the message's own coordinates), numpy,
eccodes and the standard library: never ``night_chart``, ``nbm``, ``night_serve`` nor the
contract's ``night_day``, so the rule is never checked with itself (a test runs it in a fresh
interpreter and fails if any of them is loaded, and a ruff ``banned-api`` rule forbids the
imports here). It re-derives the night day from its own arithmetic (the local date of the moment
plus 17 hours), the window from the spec's words, and each district's deciding schools from the
directory's own school kinds (its schools that are not private, charter or virtual, else all).

Every amount is held in whole millimetres, as NBM packs them, and every rounding is integer
arithmetic on them (1 in is 25.4 mm), so no float sum ever decides a step (critic r1 B1).

For the file it holds that:

* ``night_at`` is the newest cycle at most 150 minutes old whose every needed core file and
  ``.idx`` (the hours of every open district's window) its own S3 listing shows posted at or
  before ``generated_at``;
* each message read is the deterministic 1-hour snowfall of that cycle and hour (its reference
  time and its step range, as eccodes states them), on the NBM grid;
* each school's cell is the grid point nearest it by the message's own latitudes and longitudes.

For each open district on a night day that carries nights, against its schools' amounts:

* a night only inside its window: the bar count is the hours from the first whole hour after
  ``generated_at`` (not before 6 PM local the evening before) to 7 AM local on the day, and the
  window is open (before 6 AM);
* each ``least`` value is the floor to a tenth of the least school's running total at its hour;
* ``low`` and ``high`` are the lowest total rounded down and the highest rounded up, in tenths
  when the highest rounds up to under 2 in and in whole inches otherwise, and hold every school;
* ``heavy`` is there exactly when the rule names a span, and is that span;
* both ways: a night exactly when every deciding school was read, the district's 50% value is
  at least 1 in and every number is inside the contract's bounds.

100%, or nothing ships.
"""

import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Final
from urllib.parse import quote
from zoneinfo import ZoneInfo

import numpy as np
import numpy.typing as npt

from snowlight.predict.ndfd import cells

type Floats = npt.NDArray[np.float64]
type Ints = npt.NDArray[np.int64]

BUCKET: Final = "https://noaa-nbm-grib2-pds.s3.amazonaws.com"
NBM_NX: Final = 2345
NBM_NY: Final = 1597
SHIFT: Final = 200
"""NDFD's cell shifted this many columns: only the first guess, corrected by :func:`locate`."""
MAX_AGE: Final = timedelta(minutes=150)
HOUR: Final = timedelta(hours=1)
LAST_HOUR: Final = 36
TOLERANCE: Final = 1e-6
MM_TOLERANCE: Final = 1e-3
"""How far from a whole millimetre a decoded value may be (float packing noise)."""
MAX_LEAST_TENTHS: Final = 999
MAX_HIGH_INCHES: Final = 99
MAX_BARS: Final = 13
EXPECT: Final[Mapping[str, float]] = {
    "Nx": NBM_NX,
    "Ny": NBM_NY,
    "gridDefinitionTemplateNumber": 30,
    "alternativeRowScanning": 1,
    "LoVInDegrees": 265.0,
    "LaDInDegrees": 25.0,
    "discipline": 0,
    "parameterCategory": 1,
    "parameterNumber": 29,
    "productDefinitionTemplateNumber": 8,
    "typeOfStatisticalProcessing": 1,
}
"""The keys the probe asserted on every message, and their values."""
BANNED: Final = (
    "snowlight.predict.night_chart",
    "snowlight.predict.nbm",
    "snowlight.predict.night_serve",
)
"""The modules this check must never load (the fresh-interpreter test reads this)."""
_KEY: Final = re.compile(
    r"<Key>[^<]*core\.f(\d{3})\.co\.grib2(\.idx)?</Key>\s*<LastModified>([^<]+)</LastModified>"
)
_TOKEN: Final = re.compile(r"<NextContinuationToken>([^<]+)</NextContinuationToken>")


def night_day_of(moment: datetime, zone: str) -> date:
    """The local date of the moment plus 17 hours, from this module's own arithmetic."""
    local = moment.astimezone(ZoneInfo(zone))
    return (local.replace(tzinfo=None) + timedelta(hours=17)).date()


def window_of(moment: datetime, zone: str) -> tuple[date, bool, datetime, datetime]:
    """The night day, whether open (before 6 AM local on it), and Start and End in UTC."""
    tz = ZoneInfo(zone)
    day = night_day_of(moment, zone)
    open_ = moment < datetime.combine(day, time(6), tzinfo=tz)
    after = moment.astimezone(UTC).replace(minute=0, second=0, microsecond=0) + HOUR
    evening = datetime.combine(day - timedelta(days=1), time(18), tzinfo=tz).astimezone(UTC)
    end = datetime.combine(day, time(7), tzinfo=tz).astimezone(UTC)
    return day, open_, max(after, evening), end


type Get = Callable[[str, tuple[int, int] | None], bytes]
"""Reads a URL, or a byte range of it (offset, length)."""


def _url(cycle: datetime, f: int) -> str:
    return (
        f"{BUCKET}/blend.{cycle:%Y%m%d}/{cycle:%H}/core/blend.t{cycle:%H}z.core.f{f:03d}.co.grib2"
    )


def posted_hours(get: Get, cycle: datetime, at: datetime) -> set[int]:
    """The forecast hours whose CONUS core file and ``.idx`` the cycle's S3 listing shows posted
    at or before ``at``."""
    prefix = f"blend.{cycle:%Y%m%d}/{cycle:%H}/core/blend.t{cycle:%H}z.core.f0"
    grib: dict[int, datetime] = {}
    idx: dict[int, datetime] = {}
    token: str | None = None
    for _page in range(10):
        url = f"{BUCKET}/?list-type=2&prefix={prefix}&max-keys=1000"
        if token is not None:
            url += f"&continuation-token={quote(token, safe='')}"
        text = get(url, None).decode("utf-8", errors="replace")
        for f, is_idx, modified in _KEY.findall(text):
            when = datetime.fromisoformat(modified.replace("Z", "+00:00"))
            (idx if is_idx else grib)[int(f)] = when
        found = _TOKEN.search(text)
        if found is None:
            break
        token = found.group(1)
    return {f for f, when in grib.items() if when <= at and f in idx and idx[f] <= at}


@dataclass
class Message:
    """One decoded 1-hour snowfall message: its values in metres and, when asked, its points'
    coordinates, both in the file's own order (odd rows not reversed)."""

    metres: Floats
    lat: Floats | None = None
    lon: Floats | None = None


def asnow_hour(get: Get, cycle: datetime, f: int, *, where: bool = False) -> Message:
    """The deterministic 1-hour snowfall of file ``f``, as ``probe_nbm.py`` reads it: the exact
    ``.idx`` line, a range read, eccodes, the grid keys, and the message's own reference time
    and step range; with ``where``, its points' latitudes and longitudes too.

    Raises:
        ValueError: the ``.idx`` holds no one matching line, or the message is not the cycle's
            1-hour snowfall of that hour on the NBM grid.
    """
    import eccodes  # type: ignore[import-untyped]  # noqa: PLC0415

    url = _url(cycle, f)
    lines = get(f"{url}.idx", None).decode().splitlines()
    want = f"ASNOW:surface:{f - 1}-{f} hour acc fcst:"
    rows_ = [line.split(":") for line in lines]
    hits = [i for i, row in enumerate(rows_) if ":".join(row[3:]) == want]
    if len(hits) != 1:
        raise ValueError(f"{url}.idx: {len(hits)} lines of {want}")
    i = hits[0]
    offset = int(rows_[i][1])
    size = int(rows_[i + 1][1]) - offset
    raw = get(url, (offset, size))
    handle = eccodes.codes_new_from_message(raw)
    try:
        g = eccodes.codes_get
        for key, wanted in EXPECT.items():
            found = g(handle, key)
            if abs(float(found) - wanted) > TOLERANCE:
                raise ValueError(f"{url}: {key} is {found}, not {wanted}")
        stamp = f"{int(g(handle, 'dataDate')):08d}{int(g(handle, 'dataTime')):04d}"
        if stamp != f"{cycle:%Y%m%d%H%M}":
            raise ValueError(f"{url}: reference {stamp}, not the {cycle:%Y-%m-%d %HZ} cycle")
        eccodes.codes_set(handle, "stepUnits", "h")
        steps = (int(g(handle, "startStep")), int(g(handle, "endStep")))
        if steps != (f - 1, f):
            raise ValueError(f"{url}: steps {steps}, not {(f - 1, f)}")
        values = np.array(eccodes.codes_get_values(handle), dtype=np.float64)
        values[values == float(g(handle, "missingValue"))] = np.nan
        found_lat = found_lon = None
        if where:
            found_lat = np.array(eccodes.codes_get_array(handle, "latitudes"), dtype=np.float64)
            found_lon = np.array(eccodes.codes_get_array(handle, "longitudes"), dtype=np.float64)
    finally:
        eccodes.codes_release(handle)
    if values.shape[0] != NBM_NX * NBM_NY:
        raise ValueError(f"{url}: {values.shape[0]} values")
    return Message(values, found_lat, found_lon)


def raw_index(row: Ints, col: Ints) -> Ints:
    """A (row, column) cell, rows south to north and columns west to east, as its position in
    the file's own order, whose odd rows run east to west."""
    return np.asarray(row * NBM_NX + np.where(row % 2 == 1, NBM_NX - 1 - col, col), dtype=np.int64)


def _unit(lat: Floats, lon: Floats) -> Floats:
    phi, lam = np.radians(lat), np.radians(lon)
    return np.stack([np.cos(phi) * np.cos(lam), np.cos(phi) * np.sin(lam), np.sin(phi)])


def locate(lat: Floats, lon: Floats, grid_lat: Floats, grid_lon: Floats) -> Ints:
    """Each point's nearest grid point by the message's own coordinates (chord distance on the
    sphere), as the position of its value in the file's order; -1 off the grid. eccodes gives
    the coordinates row by row west to east (it does not apply the alternate row scanning to
    them), and the values with odd rows east to west (:func:`raw_index`). NDFD's cell 200
    columns over is only where the search starts: the nearest is sought two cells around it,
    and a point whose nearest is on the search's edge is taken as off the grid (never a wrong
    cell)."""
    guess = cells(lat, lon)
    row0, col0 = guess.row, guess.col + SHIFT
    inside = guess.inside & (col0 < NBM_NX)
    points = _unit(lat, lon)
    best_row = np.zeros(lat.shape[0], dtype=np.int64)
    best_col = np.zeros(lat.shape[0], dtype=np.int64)
    edge = np.zeros(lat.shape[0], dtype=np.bool_)
    gap = np.full(lat.shape[0], np.inf)
    for dr in range(-2, 3):
        for dc in range(-2, 3):
            row, col = row0 + dr, col0 + dc
            ok = inside & (row >= 0) & (row < NBM_NY) & (col >= 0) & (col < NBM_NX)
            at = np.where(ok, row, 0) * NBM_NX + np.where(ok, col, 0)
            there = _unit(grid_lat[at], grid_lon[at])
            dist = np.where(ok, np.linalg.norm(there - points, axis=0), np.inf)
            nearer = dist < gap
            best_row = np.where(nearer, row, best_row)
            best_col = np.where(nearer, col, best_col)
            gap = np.where(nearer, dist, gap)
            edge = np.where(nearer, max(abs(dr), abs(dc)) == 2, edge)  # noqa: PLR2004
    found = raw_index(best_row, best_col)
    return np.where(inside & ~edge & np.isfinite(gap), found, -1)


@dataclass
class Report:
    """What the check found: nights checked, open districts checked both ways, and every
    failure in words."""

    nights: int = 0
    schools: int = 0
    districts: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """100%, or nothing ships."""
        return self.nights > 0 and not self.failures


def _floor_tenths(mm: int) -> int:
    """Inches in tenths, rounded down, of a whole-millimetre amount (exact: 1 in is 25.4 mm)."""
    return (mm * 100) // 254


def _ceil_tenths(mm: int) -> int:
    return -((-mm * 100) // 254)


@dataclass(frozen=True, slots=True)
class Rule:
    """What the rule of spec 4.8 says of one district's whole millimetres: the bars in tenths,
    the range (tenths in tenths mode, else whole inches), the mode, the span, and whether it
    charts at all."""

    least: list[int]
    low: int
    high: int
    tenths: bool
    heavy: tuple[int, int] | None
    shows: bool


def rule(mm: Ints) -> Rule:
    """The rule of spec 4.8 on whole millimetres ``(hours, schools)``, in integers only."""
    hours, schools = mm.shape
    running = np.cumsum(mm, axis=0)
    least = [_floor_tenths(int(running[h].min())) for h in range(hours)]
    totals = running[-1]
    lowest, highest = int(totals.min()), int(totals.max())
    tenths = _ceil_tenths(highest) < 20  # noqa: PLR2004 - 2.0 in
    if tenths:
        low, high = _floor_tenths(lowest), _ceil_tenths(highest)
    else:
        low, high = (lowest * 10) // 254, -((-highest * 10) // 254)
    ordered = sorted((int(v) for v in totals), reverse=True)
    half = ordered[max((schools + 1) // 2, 1) - 1]
    shows = (
        _floor_tenths(half) >= 10  # noqa: PLR2004 - the 50% value at least 1.0 in
        and max(least) <= MAX_LEAST_TENTHS
        and (high if not tenths else 0) <= MAX_HIGH_INCHES
        and 1 <= hours <= MAX_BARS
    )
    heavy: tuple[int, int] | None = None
    if hours >= 3 and lowest * 20 >= 254:  # noqa: PLR2004 - three hours; every school 0.5 in
        best = []
        for k in range(schools):
            sums = [int(mm[h : h + 3, k].sum()) for h in range(hours - 2)]
            best.append(sums.index(max(sums)))  # the earliest on a tie
        first, last = min(best), max(best) + 3
        if last - first in {3, 4}:
            before = least[first - 1] if first > 0 else 0
            # rise / span >= 1.5 x mean, in tenths: 2 x rise x hours >= 3 x least[-1] x span
            if 2 * (least[last - 1] - before) * hours >= 3 * least[-1] * (last - first):
                heavy = (first, last)
    return Rule(least, low, high, tenths, heavy, shows)


def whole_mm(metres: Floats) -> Ints | None:
    """Metres as whole millimetres, or None when a value is not one (NBM packs whole mm)."""
    scaled = metres * 1000.0
    mm = np.rint(scaled)
    if not np.isfinite(scaled).all() or (np.abs(scaled - mm) > MM_TOLERANCE).any():
        return None
    return mm.astype(np.int64)


def _half_mm(mm: Ints) -> int:
    totals = sorted((int(v) for v in mm.sum(axis=0)), reverse=True)
    return totals[max((len(totals) + 1) // 2, 1) - 1]


def check_night(  # noqa: PLR0913 - one night, its district's schools and its file
    night: Mapping[str, Any] | None,
    day: date,
    zone: str,
    generated: datetime,
    metres: Floats,
    *,
    where: str,
) -> list[str]:
    """One open district's night (or its absence, ``None``) against its deciding schools' blend
    amounts in metres ``(hours, schools)``."""
    found: list[str] = []
    night_day, open_, start, end = window_of(generated, zone)
    hours = round((end - start) / HOUR)
    if night is not None and (night_day != day or not open_):
        found.append(f"{where}: the window is not open for {day} at {generated:%H:%MZ}")
    if metres.shape[0] != hours:
        found.append(f"{where}: {metres.shape[0]} hours read for a {hours}-hour window")
        return found
    if np.isnan(metres).any():
        if night is not None:
            found.append(f"{where}: a school has no blend value")
        return found
    mm = whole_mm(metres)
    if mm is None:
        found.append(f"{where}: a blend value is not a whole millimetre")
        return found
    said = rule(mm)
    if night is None:
        if said.shows:
            found.append(f"{where}: no night, but its 50% value is {_half_mm(mm)} mm (>= 1 in)")
        return found
    if not said.shows:
        found.append(f"{where}: a night, but the rule shows none (50% value or bounds)")
    return found + _against(night, said, mm, hours, where)


def _against(night: Mapping[str, Any], said: Rule, mm: Ints, hours: int, where: str) -> list[str]:
    """A night's numbers against what the rule says of its schools' millimetres."""
    found: list[str] = []
    bars = [round(float(v) * 10) for v in night["least"]]
    if len(bars) != hours:
        found.append(f"{where}: {len(bars)} bars for a {hours}-hour window")
        return found
    for i, (value, want) in enumerate(zip(bars, said.least, strict=True)):
        if value != want:
            found.append(f"{where}: bar {i} is {value / 10}, the least school's floor {want / 10}")
    low, high = float(night["low"]), float(night["high"])
    scale = 10 if said.tenths else 1
    tenths = high < 2.0  # noqa: PLR2004 - the mode the file's numbers say
    if (round(low * scale), round(high * scale)) != (said.low, said.high) or tenths != said.tenths:
        found.append(
            f"{where}: range {low} to {high} is not the rule's "
            f"{said.low / scale} to {said.high / scale}"
        )
    totals = mm.sum(axis=0)
    if int(totals.min()) * 10 < round(low * 254) or int(totals.max()) * 10 > round(high * 254):
        found.append(f"{where}: totals {totals.min()} to {totals.max()} mm not in {low} to {high}")
    given = night.get("heavy")
    span = None if given is None else (int(given[0]), int(given[1]))
    if span != said.heavy:
        found.append(f"{where}: heaviest span {span} is not the rule's {said.heavy}")
    return found


@dataclass(frozen=True, slots=True)
class Directory:
    """The directory's schools: each one's point, its deployed district, and whether it is a
    public school (not private, charter or virtual)."""

    lat: Floats
    lon: Floats
    district: Ints
    public: npt.NDArray[np.bool_]

    def deciding(self) -> dict[int, Ints]:
        """Each district's deciding schools (positions): its public schools, else all."""
        order = np.argsort(self.district, kind="stable")
        ids, starts, counts = np.unique(self.district[order], return_index=True, return_counts=True)
        found: dict[int, Ints] = {}
        for d, s, n in zip(ids.tolist(), starts.tolist(), counts.tolist(), strict=True):
            mine = order[s : s + n]
            public = mine[self.public[mine]]
            found[int(d)] = public if public.shape[0] else mine
        return found


def directory_of(lat: Any, lon: Any, district: Any, public: Any) -> Directory:
    """The directory's schools as the check reads them."""
    return Directory(
        np.asarray(lat, dtype=np.float64),
        np.asarray(lon, dtype=np.float64),
        np.asarray(district, dtype=np.int64),
        np.asarray(public, dtype=np.bool_),
    )


def _hours(start: datetime, end: datetime) -> list[datetime]:
    return [start + k * HOUR for k in range(round((end - start) / HOUR))]


@dataclass(frozen=True, slots=True)
class _Open:
    entry: Mapping[str, Any]
    day: date
    night: Mapping[str, Any] | None
    schools: Ints


def _open_districts(
    value: Mapping[str, Any], generated: datetime, directory: Directory, night_days: set[date]
) -> list[_Open]:
    """The file's districts open at ``generated_at`` on a night day that carries nights, with a
    school day there and every deciding school on the blend's grid (the pass reads no other)."""
    days = [date.fromisoformat(day) for day in value["days"]]
    deciding = directory.deciding()
    guess = cells(directory.lat, directory.lon)
    on_grid = guess.inside & (guess.col + SHIFT < NBM_NX)
    found: list[_Open] = []
    for entry in value["districts"]:
        zone = entry.get("time_zone")
        mine = deciding.get(int(entry["district"]))
        if zone is None or mine is None or not on_grid[mine].all():
            continue
        day, is_open, _start, _end = window_of(generated, zone)
        if not is_open or day not in night_days or day not in days:
            continue
        item = entry["days"][days.index(day)]
        if item.get("state") == "forecast":
            found.append(_Open(entry, day, item.get("night"), mine))
    return found


def check_file(
    data: bytes,
    directory: Directory,
    *,
    get: Get,
    report: Report | None = None,
) -> Report:
    """Every night of a predictions file (its bytes), and every open district without one on a
    night day that carries nights, against the blend: the cycle its own listing says was the
    newest that counted, read at each deciding school's nearest grid point."""
    found = report or Report()
    value = json.loads(data)
    generated = datetime.fromisoformat(value["generated_at"].replace("Z", "+00:00"))
    days = [date.fromisoformat(day) for day in value["days"]]
    nights = [
        (int(entry["district"]), day)
        for entry in value["districts"]
        for day, item in zip(days, entry["days"], strict=True)
        if "night" in item
    ]
    if not nights:
        return found
    cycle = datetime.fromisoformat(value["night_at"].replace("Z", "+00:00"))
    if not timedelta(0) <= generated - cycle <= MAX_AGE:
        found.failures.append(
            f"night_at {cycle:%H:%MZ} is not within 150 min of {generated:%H:%MZ}"
        )
    open_ = _open_districts(value, generated, directory, {day for _d, day in nights})
    opened = {(int(item.entry["district"]), item.day) for item in open_}
    found.failures.extend(
        f"district {d} {day}: a night, but not open on a school day with every school read"
        for d, day in nights
        if (d, day) not in opened
    )
    windows = {
        item.entry["time_zone"]: window_of(generated, item.entry["time_zone"]) for item in open_
    }
    needed = sorted({h for _d, _o, start, end in windows.values() for h in _hours(start, end)})
    _check_cycle(get, cycle, generated, needed, found)
    blend: dict[datetime, Floats] = {}
    position: Ints | None = None
    for hour in needed:
        f = round((hour - cycle) / HOUR) + 1
        try:
            message = asnow_hour(get, cycle, f, where=position is None)
        except Exception as error:
            found.failures.append(f"f{f:03d} of the {cycle:%m-%d %HZ} cycle: {error}")
            return found
        if position is None:
            if message.lat is None or message.lon is None:
                raise AssertionError("asked for the message's coordinates")
            position = locate(directory.lat, directory.lon, message.lat, message.lon)
        blend[hour] = np.where(position >= 0, message.metres[np.maximum(position, 0)], np.nan)
    for item in open_:
        zone = item.entry["time_zone"]
        _day, _open, start, end = windows[zone]
        metres = np.array([blend[h][item.schools] for h in _hours(start, end)], dtype=np.float64)
        where = f"district {item.entry['district']} {item.day}"
        found.failures.extend(
            check_night(item.night, item.day, zone, generated, metres, where=where)
        )
        found.districts += 1
        if item.night is not None:
            found.nights += 1
            found.schools += int(item.schools.shape[0])
    return found


def _check_cycle(
    get: Get, cycle: datetime, generated: datetime, needed: Sequence[datetime], found: Report
) -> None:
    """``night_at`` is the newest cycle at most 150 min old whose every needed file and ``.idx``
    its own listing shows posted by ``generated_at``."""
    newest: datetime | None = None
    at = generated.replace(minute=0, second=0, microsecond=0)
    while needed and generated - at <= MAX_AGE:
        hours = {round((h - at) / HOUR) + 1 for h in needed}
        if (
            min(hours) >= 1
            and max(hours) <= LAST_HOUR
            and hours <= posted_hours(get, at, generated)
        ):
            newest = at
            break
        at -= HOUR
    if newest != cycle:
        said = "none" if newest is None else f"{newest:%m-%d %HZ}"
        found.failures.append(
            f"night_at is the {cycle:%m-%d %HZ} cycle; the newest that counted at "
            f"{generated:%H:%MZ} is {said}"
        )


def http_get() -> Get:  # pragma: no cover - the network
    """GETs and range GETs, politely (the site's User-Agent, one at a time, a few tries); a
    range read must be answered with exactly that range (a 206)."""
    import httpx  # noqa: PLC0415

    client = httpx.Client(
        timeout=60.0,
        headers={"User-Agent": "snowlight-night-check (+https://snowlightmap.com)"},
        follow_redirects=True,
    )

    def get(url: str, span: tuple[int, int] | None) -> bytes:
        headers = {} if span is None else {"Range": f"bytes={span[0]}-{span[0] + span[1] - 1}"}
        status = 0
        for attempt in range(4):
            response = client.get(url, headers=headers)
            status = response.status_code
            if response.status_code in {200, 206}:
                if span is not None and (
                    response.status_code != 206 or len(response.content) != span[1]  # noqa: PLR2004
                ):
                    raise ValueError(f"{url}: {len(response.content)} bytes of {span[1]}")
                return response.content
            if response.status_code < 500 and response.status_code != 429:  # noqa: PLR2004
                break
            import time as clock  # noqa: PLC0415

            clock.sleep(2.0**attempt)
        raise ValueError(f"{url}: HTTP {status}")

    return get


def main(file: str, directory: Directory) -> int:  # pragma: no cover - the network
    """``night-check FILE --site-data DIR``: 0 when every night holds, 1 otherwise."""
    with open(file, "rb") as handle:  # noqa: PTH123
        report = check_file(handle.read(), directory, get=http_get())
    lines = [
        f"night-check: {report.nights} nights, {report.schools} schools, "
        f"{report.districts} open districts checked both ways, "
        f"{len(report.failures)} failures",
        *(f"  {line}" for line in report.failures[:50]),
    ]
    sys.stdout.write("\n".join(lines) + "\n")
    return 0 if report.passed else 1
