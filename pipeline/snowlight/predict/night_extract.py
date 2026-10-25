"""The label-night forecast extract: NOAA's forecast grids as they stood at 21:00 the evening
before each night of a list, for every district of the night's time (calc-research plan, Y1
and T2).

Inputs for the candidates the tune lane tests (7 AM temperature, the chance of precipitation,
liquid amounts, snow and ice per 6-hour period, the hourly weather type) come from the same
NDFD files the forecast history reads (:mod:`snowlight.predict.ndfd`), on GitHub's runners
(``.github/workflows/label-night-forecast-extract.yml``), never on a laptop: about 12 MB a night
read by range and dropped at once. What is kept holds NOAA's values only.

Nights
======

``config/label-nights.yaml`` lists (school day ``D``, time zone) pairs. A night's snapshot is
21:00 local on D-1 in its zone; its districts are every district (the deciding schools of the
deployed directory, as the forecast history takes them) whose own zone reaches 21:00 D-1 at the
same instant (Phoenix shares Denver's in winter). Nothing in the files says which of a night's
districts any other file labels.

Runs, one per element
=====================

* Snow, ice and apparent temperature come from the newest run (the three files of one half
  hour, :func:`snowlight.predict.ndfd.newest_run`) that counts at the snapshot, exactly as the
  forecast history's 21:00 sample and the serving pass take them, so the parity days match.
* Temperature (``temp``), the 12-hour chance of precipitation (``pop12``), liquid amounts
  (``qpf``) and the weather strings (``wx``) each come from that element's own newest file that
  counts at the snapshot: available (its stamp plus :data:`snowlight.predict.ndfd.RUN_DELAY`,
  and never before the host wrote it) at or before 21:00 and at most 3 hours old.
* Every file's stamp, reference time and availability are kept (``runs.parquet``); the extract
  fails if any is after the snapshot. A file whose first reference time does not fit its stamp
  (:func:`snowlight.predict.ndfd.reference_ok`) is not used.

Values (``values.parquet``, one row per night and district; NaN where the run has no value)
================================================================================================

* ``snow_e<H>``, ``ice_e<H>``, ``qpf_e<H>``: inches in the 6-hour period ending ``H`` hours after
  00 UTC on D (H = 0, 6, 12, 18, 24): the district's 50% value (the largest amount at least half
  its deciding schools reach). A period already over at the run's reference time is not in the
  run (NaN); the period under way holds the run's whole period.
* ``snow_window``, ``ice_window``: the forecast history's own value, the 50% value of each
  school's total over the periods ending 06, 12 and 18 UTC on D not over at the snapshot.
* ``pop_e<H>``: the 12-hour chance of precipitation (percent) ending ``H`` hours after 00 UTC on D
  (H = 0, 12, 24), the 50% value.
* ``temp_h<L>``, ``apt_h<L>``: air and apparent temperature (F) at ``L`` o'clock local on D
  (L = 5 to 8), the 50% value counted from the cold side (the coldest value at least half reach).

Weather strings (``wx.parquet``): each district's most common string among its deciding schools
(ties to the string first in that hour's message's own table, the file's order) at every local
hour from 21:00 D-1 (hour -3) to 12:00 D.
"""

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo

import numpy as np
import numpy.typing as npt
import polars as pl
import yaml  # type: ignore[import-untyped, unused-ignore]

from snowlight.predict import ndfd
from snowlight.predict.config import PIPELINE_ROOT
from snowlight.predict.forecast_history import Opener, Schools
from snowlight.predict.ndfd import Element, Floats, Listed

NIGHTS_PATH: Final = PIPELINE_ROOT / "config" / "label-nights.yaml"
SNAPSHOT: Final = time(21, 0)
RUN_ELEMENTS: Final = ndfd.ELEMENTS
"""Read from the night's newest run, as the forecast history's 21:00 sample."""
OWN_ELEMENTS: Final = (Element.TEMP, Element.POP12, Element.QPF, Element.WX)
"""Each read from its own newest file."""
EXTRACT_ELEMENTS: Final = (*RUN_ELEMENTS, *OWN_ELEMENTS)
PERIOD_HOURS: Final = (0, 6, 12, 18, 24)
"""Six-hour period ends, hours after 00 UTC on D."""
POP_HOURS: Final = (0, 12, 24)
"""Twelve-hour period ends, hours after 00 UTC on D."""
LOCAL_HOURS: Final = (5, 6, 7, 8)
"""Local hours on D of the temperature values."""
WX_HOURS: Final = tuple(range(-3, 13))
"""Local hours of the weather strings: 21:00 on D-1 (-3) to noon on D."""
AMOUNTS: Final[Mapping[Element, tuple[str, Callable[[Floats], Floats], tuple[int, ...]]]] = {
    Element.SNOW: ("snow", ndfd.snow_inches, PERIOD_HOURS),
    Element.ICE: ("ice", ndfd.ice_inches, PERIOD_HOURS),
    Element.QPF: ("qpf", ndfd.ice_inches, PERIOD_HOURS),
    Element.POP12: ("pop", lambda values: np.round(values, 6), POP_HOURS),
}
"""Amount elements: their column stem, their unit (snow metres, ice and liquid millimetres to
inches; the chance in percent) and their period ends."""
WINDOW_ELEMENTS: Final = (Element.SNOW, Element.ICE)
"""Amounts also kept as the forecast history keeps them: the 50% value of each school's total
over the window's periods (ending 06, 12 and 18 UTC on D) not over at the snapshot
(``snow_window``, ``ice_window``), so the parity days compare value for value."""
TEMPERATURES: Final[Mapping[Element, str]] = {Element.TEMP: "temp", Element.APT: "apt"}
WX_UNKNOWN: Final = -1


VALUE_COLUMNS: Final = (
    *(f"{stem}_e{hour:02d}" for stem, _convert, hours in AMOUNTS.values() for hour in hours),
    *(f"{AMOUNTS[element][0]}_window" for element in WINDOW_ELEMENTS),
    *(f"{stem}_h{hour:02d}" for stem in TEMPERATURES.values() for hour in LOCAL_HOURS),
)
"""The value columns, in order."""


class ExtractError(ValueError):
    """The nights list or a file does not read as the extract needs."""


@dataclass(frozen=True, slots=True, order=True)
class Night:
    """One (school day, time zone) of the list."""

    day: date
    zone: str

    @property
    def snapshot(self) -> datetime:
        """21:00 local on D-1, in UTC."""
        local = datetime.combine(self.day - timedelta(days=1), SNAPSHOT, tzinfo=ZoneInfo(self.zone))
        return local.astimezone(UTC)


def load_nights(text: str) -> list[Night]:
    """The nights of ``config/label-nights.yaml`` (``nights: [{day, zone}, ...]``), sorted.

    Raises:
        ExtractError: it does not read, a zone is unknown, or a night repeats.
    """
    data = yaml.safe_load(text)
    items = data.get("nights") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise ExtractError("no nights")
    found: list[Night] = []
    for item in items:
        if not isinstance(item, dict) or set(item) != {"day", "zone"}:
            raise ExtractError(f"not a night: {item!r}")
        day = item["day"] if isinstance(item["day"], date) else date.fromisoformat(str(item["day"]))
        zone = str(item["zone"])
        try:
            ZoneInfo(zone)
        except (KeyError, ValueError) as error:
            raise ExtractError(f"unknown zone {zone!r}") from error
        found.append(Night(day, zone))
    if len(set(found)) != len(found):
        raise ExtractError("a night is listed twice")
    return sorted(found)


def night_districts(night: Night, schools: Schools) -> npt.NDArray[np.int64]:
    """The district indexes whose own zone reaches 21:00 D-1 at the night's snapshot."""
    at = night.snapshot
    same = [
        index
        for index, zone in enumerate(schools.zone_of_district)
        if Night(night.day, zone).snapshot == at
    ]
    return np.array(same, dtype=np.int64)


# --- which files ---------------------------------------------------------------------------------


def available_at(item: Listed, delay: timedelta = ndfd.RUN_DELAY) -> datetime:
    """When a file counts: its stamp plus ``delay``, and never before its host wrote it."""
    written = item.last_modified
    return max(item.stamp + delay, written) if written is not None else item.stamp + delay


def own_file(
    listed: Iterable[Listed],
    element: Element,
    at: datetime,
    delay: timedelta = ndfd.RUN_DELAY,
    max_age: timedelta = ndfd.MAX_AGE,
) -> Listed | None:
    """The newest file of ``element`` that counts at ``at`` and is at most ``max_age`` old."""
    best: Listed | None = None
    for item in listed:
        if item.element is not element or available_at(item, delay) > at:
            continue
        if at - item.stamp > max_age:
            continue
        if best is None or item.stamp > best.stamp:
            best = item
    return best


@dataclass(frozen=True, slots=True)
class Chosen:
    """The file an element is read from for a night, and when it counted."""

    element: Element
    listed: Listed
    available: datetime
    run_time: datetime
    """The run's time (snow, ice, apparent temperature) or the file's own stamp."""


def choose_files(
    night: Night, listed: Sequence[Listed], delay: timedelta = ndfd.RUN_DELAY
) -> tuple[dict[Element, Chosen], list[str]]:
    """Each element's file for ``night`` (see the module docstring), and the elements none
    counts for (with why).

    Raises:
        ExtractError: a chosen file counts after the snapshot (never: asserted).
    """
    at = night.snapshot
    chosen: dict[Element, Chosen] = {}
    missing: list[str] = []
    run = ndfd.newest_run(ndfd.assemble_runs(listed, delay).runs, at)
    if run is None:
        missing += [f"{element.value}: no run" for element in RUN_ELEMENTS]
    else:
        for element in RUN_ELEMENTS:
            chosen[element] = Chosen(element, run.files[element], run.available_at, run.time)
    for element in OWN_ELEMENTS:
        item = own_file(listed, element, at, delay)
        if item is None:
            missing.append(f"{element.value}: no file")
            continue
        chosen[element] = Chosen(element, item, available_at(item, delay), item.stamp)
    for picked in chosen.values():
        if picked.available > at:
            raise ExtractError(f"{picked.element.value} counts at {picked.available}, after {at}")
    return chosen, missing


# --- values --------------------------------------------------------------------------------------


def period_ends(day: date, hours: Sequence[int]) -> dict[datetime, int]:
    """Each period end ``hours`` after 00 UTC on ``day``."""
    start = datetime.combine(day, time(0), tzinfo=UTC)
    return {start + timedelta(hours=hour): hour for hour in hours}


def local_times(day: date, zone: str, hours: Sequence[int]) -> dict[datetime, int]:
    """Each local hour of ``hours`` on ``day`` in ``zone`` (negative: on the day before), in UTC."""
    tz = ZoneInfo(zone)
    found: dict[datetime, int] = {}
    for hour in hours:
        local_day = day + timedelta(days=math.floor(hour / 24))
        moment = datetime.combine(local_day, time(hour % 24), tzinfo=tz)
        found[moment.astimezone(UTC)] = hour
    return found


def district_mode(codes: npt.NDArray[np.int64], groups: ndfd.Groups) -> npt.NDArray[np.int64]:
    """Each group's most common code (ties to the smallest; :data:`WX_UNKNOWN` where no point
    has one)."""
    found = np.full(groups.ids.shape[0], WX_UNKNOWN, dtype=np.int64)
    ordered = codes[groups.order]
    for position, (start, count) in enumerate(zip(groups.starts, groups.counts, strict=True)):
        mine = ordered[start : start + count]
        mine = mine[mine >= 0]
        if mine.size:
            values, counts = np.unique(mine, return_counts=True)
            found[position] = int(values[int(np.argmax(counts))])
    return found


@dataclass(slots=True)
class NightValues:
    """One night's files, values and weather strings."""

    runs: list[dict[str, object]] = field(default_factory=list)
    values: pl.DataFrame | None = None
    wx: pl.DataFrame | None = None
    errors: list[str] = field(default_factory=list)


def _heads(read: ndfd.Ranged, element: Element, last: datetime) -> list[ndfd.Head]:
    """The element's message heads up to the first that ends at ``last`` or later.

    Raises:
        ndfd.NdfdError: the file does not read, or holds no message of its parameter.
    """
    heads = [
        head
        for head in ndfd.walk(read, stop=lambda head: head.end >= last)
        if head.parameter == element.parameter
    ]
    if not heads:
        raise ndfd.NdfdError("no message of its parameter")
    return heads


@dataclass(frozen=True, slots=True)
class Place:
    """A night's deciding schools: their cells, their grouping by district, and which groups
    lie in each time zone."""

    where: ndfd.Cells
    groups: ndfd.Groups
    zones: Mapping[str, npt.NDArray[np.bool_]]

    @property
    def count(self) -> int:
        """Districts."""
        return int(self.groups.ids.shape[0])


def place_of(night: Night, schools: Schools) -> Place:
    """The night's districts' deciding schools (:func:`night_districts`)."""
    districts = night_districts(night, schools)
    mine = np.flatnonzero(np.isin(schools.district, districts)).astype(np.int64)
    groups = ndfd.groups_of(schools.district[mine])
    zone_of = [schools.zone_of_district[i] for i in groups.ids.tolist()]
    zones = {zone: np.array([z == zone for z in zone_of], dtype=np.bool_) for zone in set(zone_of)}
    return Place(ndfd.cells(schools.lat[mine], schools.lon[mine]), groups, zones)


def read_amounts(  # noqa: PLR0913, PLR0917 - the file, the night, its schools, columns
    element: Element,
    read: ndfd.Ranged,
    night: Night,
    place: Place,
    share: float,
    columns: dict[str, Floats],
) -> tuple[datetime, int]:
    """Fill an amount element's columns; its first reference time and the messages read."""
    stem, convert, hours = AMOUNTS[element]
    ends = period_ends(night.day, hours)
    heads = _heads(read, element, max(ends))
    used = 0
    by_end: dict[datetime, Floats] = {}
    for head in heads:
        hour = ends.get(head.end)
        if hour is None:
            continue
        grid = ndfd.decode(ndfd.message(read, head), head)
        values = convert(ndfd.sample(grid.values, place.where))
        by_end[head.end] = values
        columns[f"{stem}_e{hour:02d}"] = ndfd.group_half(values, place.groups, share)
        used += 1
    if element in WINDOW_ELEMENTS:
        total = ndfd.window_total(by_end, night.day, night.snapshot)
        if total is not None:
            columns[f"{stem}_window"] = ndfd.group_half(total, place.groups, share)
    return heads[0].reference, used


def read_temperatures(  # noqa: PLR0913, PLR0917 - the file, the night, schools, columns
    element: Element,
    read: ndfd.Ranged,
    night: Night,
    place: Place,
    share: float,
    columns: dict[str, Floats],
) -> tuple[datetime, int]:
    """Fill a temperature element's columns, each district at its own zone's local hours."""
    stem = TEMPERATURES[element]
    wanted = {zone: local_times(night.day, zone, LOCAL_HOURS) for zone in place.zones}
    heads = _heads(read, element, max(t for times in wanted.values() for t in times))
    by_time = {head.end: head for head in heads}
    used = 0
    for zone, times in sorted(wanted.items()):
        inside = place.zones[zone]
        for moment, hour in times.items():
            found = by_time.get(moment)
            if found is None:
                continue
            grid = ndfd.decode(ndfd.message(read, found), found)
            values = ndfd.fahrenheit(ndfd.sample(grid.values, place.where))
            half = ndfd.group_half(values, place.groups, share, coldest=True)
            column = columns[f"{stem}_h{hour:02d}"]
            column[inside] = half[inside]
            used += 1
    return heads[0].reference, used


def read_weather(
    read: ndfd.Ranged, night: Night, place: Place, codes: npt.NDArray[np.int64]
) -> tuple[datetime, int, tuple[str, ...]]:
    """Fill each district's weather string codes by local hour; the reference time, messages
    read and the strings the codes index.

    Raises:
        ndfd.NdfdError: a grid value indexes past its message's strings.
    """
    wanted = {zone: local_times(night.day, zone, WX_HOURS) for zone in place.zones}
    heads = _heads(read, Element.WX, max(t for times in wanted.values() for t in times))
    by_time = {head.end: head for head in heads}
    table: dict[str, int] = {}
    used = 0
    for zone, times in sorted(wanted.items()):
        inside = place.zones[zone]
        for moment, hour in times.items():
            found = by_time.get(moment)
            if found is None:
                continue
            raw = ndfd.message(read, found)
            strings = ndfd.weather_strings(raw)
            sampled = ndfd.sample(ndfd.decode(raw, found).values, place.where)
            index = np.where(np.isnan(sampled), WX_UNKNOWN, sampled).astype(np.int64)
            if index.size and int(index.max()) >= len(strings):
                raise ndfd.NdfdError("a weather index past its string table")
            # The mode is taken on the message's own string indexes, so a tie goes to the
            # string first in the file's table; only then is it mapped to the night's codes.
            modes = district_mode(index, place.groups)
            codes[inside, WX_HOURS.index(hour)] = [
                table.setdefault(strings[i], len(table)) if i >= 0 else WX_UNKNOWN
                for i in modes[inside].tolist()
            ]
            used += 1
    return heads[0].reference, used, tuple(sorted(table, key=table.__getitem__))


def extract_night(  # noqa: PLR0913 - one night's inputs
    night: Night,
    schools: Schools,
    listed: Sequence[Listed],
    opener: Opener,
    share: float,
    *,
    delay: timedelta = ndfd.RUN_DELAY,
) -> NightValues:
    """Read one night's files and every district's values (see the module docstring). An
    element whose file does not count or does not read leaves its columns NaN (and is named
    in :attr:`NightValues.errors`); the others still count.

    Raises:
        ndfd.GridError: a message is not on the NDFD grid (the whole extract stops).
    """
    found = NightValues()
    place = place_of(night, schools)
    count = place.count
    columns = {name: np.full(count, np.nan) for name in VALUE_COLUMNS}
    codes = np.full((count, len(WX_HOURS)), WX_UNKNOWN, dtype=np.int64)
    strings: tuple[str, ...] = ()
    chosen, missing = choose_files(night, listed, delay)
    found.errors += missing
    for element in EXTRACT_ELEMENTS:
        item = chosen.get(element)
        if item is None:
            continue
        row: dict[str, object] = {
            "day": night.day,
            "zone": night.zone,
            "snapshot": night.snapshot,
            "element": element.value,
            "stamp": item.listed.stamp,
            "run_time": item.run_time,
            "host": item.listed.host.value,
            "last_modified": item.listed.last_modified,
            "available_at": item.available,
            "url": item.listed.url,
            "reference": None,
            "messages": 0,
            "error": None,
        }
        found.runs.append(row)
        try:
            read = opener(item.listed)
            if element in AMOUNTS:
                reference, used = read_amounts(element, read, night, place, share, columns)
            elif element in TEMPERATURES:
                reference, used = read_temperatures(element, read, night, place, share, columns)
            else:
                reference, used, strings = read_weather(read, night, place, codes)
            row["reference"], row["messages"] = reference, used
            if not ndfd.reference_ok(reference, item.listed.stamp):
                raise ndfd.NdfdError(f"reference {reference} does not fit its stamp")
        except ndfd.GridError:
            raise
        except ndfd.NdfdError as error:
            row["error"] = str(error)
            found.errors.append(f"{element.value}: {error}")
            _clear(element, columns, codes)
    leaids = [schools.districts[i] for i in place.groups.ids.tolist()]
    found.values = pl.DataFrame(
        {
            "day": [night.day] * count,
            "zone": [night.zone] * count,
            "district": leaids,
            **{name: values.astype(np.float32) for name, values in columns.items()},
        }
    )
    rows = [
        (leaid, hour, strings[code])
        for leaid, mine in zip(leaids, codes.tolist(), strict=True)
        for hour, code in zip(WX_HOURS, mine, strict=True)
        if code >= 0
    ]
    found.wx = pl.DataFrame(
        {
            "day": [night.day] * len(rows),
            "zone": [night.zone] * len(rows),
            "district": [item[0] for item in rows],
            "local_hour": [item[1] for item in rows],
            "wx": [item[2] for item in rows],
        },
        schema=WX_SCHEMA,
    )
    return found


WX_SCHEMA: Final[dict[str, pl.DataType | type[pl.DataType]]] = {
    "day": pl.Date,
    "zone": pl.String,
    "district": pl.String,
    "local_hour": pl.Int8,
    "wx": pl.String,
}


def _clear(element: Element, columns: dict[str, Floats], codes: npt.NDArray[np.int64]) -> None:
    """Leave an element that did not read unknown, every value of it (never part of a run)."""
    if element is Element.WX:
        codes[:] = WX_UNKNOWN
        return
    stem = AMOUNTS[element][0] if element in AMOUNTS else TEMPERATURES[element]
    for name, values in columns.items():
        if name.startswith(f"{stem}_"):
            values[:] = np.nan


# --- listing --------------------------------------------------------------------------------------


def list_extract_day(fetch: Callable[[str], bytes], day: date) -> list[Listed]:
    """Every file of the extract's elements of one UTC day, from its history host.

    Raises:
        ndfd.NotFoundError: the host has no folder for the day.
        ndfd.NdfdError: a listing does not read.
    """
    if day < ndfd.AWS_FIRST_DAY:
        return ndfd.parse_ncei_catalog(fetch(ndfd.ncei_catalog_url(day)), EXTRACT_ELEMENTS)
    found: list[Listed] = []
    for element in EXTRACT_ELEMENTS:
        token: str | None = None
        while True:
            page, token = ndfd.parse_aws_listing(fetch(ndfd.aws_listing_url(element, day, token)))
            found.extend(page)
            if token is None:
                break
    return found


def runs_frame(rows: Iterable[Mapping[str, object]]) -> pl.DataFrame:
    """The files read, one row per night and element."""
    return pl.DataFrame(list(rows), schema=RUNS_SCHEMA)


RUNS_SCHEMA: Final[dict[str, pl.DataType | type[pl.DataType]]] = {
    "day": pl.Date,
    "zone": pl.String,
    "snapshot": pl.Datetime("us", "UTC"),
    "element": pl.String,
    "stamp": pl.Datetime("us", "UTC"),
    "run_time": pl.Datetime("us", "UTC"),
    "host": pl.String,
    "last_modified": pl.Datetime("us", "UTC"),
    "available_at": pl.Datetime("us", "UTC"),
    "url": pl.String,
    "reference": pl.Datetime("us", "UTC"),
    "messages": pl.Int32,
    "error": pl.String,
}


def check_runs(runs: pl.DataFrame) -> list[str]:
    """Every file that counts after its night's snapshot (none may)."""
    late = runs.filter(pl.col("available_at") > pl.col("snapshot"))
    return [
        f"{day} {zone} {element}: available {at}, snapshot {snap}"
        for day, zone, element, at, snap in late.select(
            "day", "zone", "element", "available_at", "snapshot"
        ).iter_rows()
    ]


def row_counts(values: pl.DataFrame) -> dict[str, dict[str, int]]:
    """Per night (``D zone``), the districts with a value of each element."""
    found: dict[str, dict[str, int]] = {}
    stems = {stem for stem, _c, _h in AMOUNTS.values()} | set(TEMPERATURES.values())
    for (day, zone), part in values.group_by("day", "zone", maintain_order=True):
        key = f"{day} {zone}"
        found[key] = {
            stem: int(
                part.select(
                    pl.any_horizontal(
                        [pl.col(c).is_not_nan() for c in part.columns if c.startswith(stem + "_")]
                    )
                )
                .to_series()
                .sum()
            )
            for stem in sorted(stems)
        }
    return found


def write_frames(out: Path, name: str, frames: Sequence[pl.DataFrame]) -> Path:
    """Concatenate ``frames`` into ``out/name`` (zstd), sorted by day, zone and district."""
    frame = pl.concat(frames, how="vertical") if frames else pl.DataFrame()
    keys = [key for key in ("day", "zone", "district", "local_hour") if key in frame.columns]
    path = out / name
    frame.sort(keys).write_parquet(path, compression="zstd", compression_level=19)
    return path
