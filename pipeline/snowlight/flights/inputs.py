"""The live inputs other than the forecast: FAA programs, NWS alerts and the weather now.

Each reader takes the bytes as downloaded and returns what it found, or raises
:class:`InputError` when the bytes cannot be read (the live job then publishes that part as not
read, never as "none in effect"; D7).

* FAA airport status (``https://nasstatus.faa.gov/api/airport-status-information``, XML): ground
  stops, ground delay programs, general departure and arrival delays, airport closures and
  deicing, with the time the FAA wrote it. A closure counts only when it closes the airport to
  airline flights: closures to non-scheduled or general aviation traffic are left out.
* NWS active alerts (``https://api.weather.gov/alerts/active``, GeoJSON): the alerts of
  :class:`~snowlight.schemas.flights.FlightsAlert` in effect at an airport's forecast zone or
  county.
* The latest weather reports (``https://aviationweather.gov/data/cache/metars.cache.csv.gz``).
* The weather that came before the runs (the observed-before inputs of the chances): the IEM
  archive's routine reports over the 49 hours before them, the same request and reduction as
  the history's (:mod:`snowlight.flights.obs`).
"""

import csv
import gzip
import io
import json
import math
import re
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

import polars as pl

from snowlight.flights.obs import OBSERVED_HOURS, ReportsError, reduce_bytes
from snowlight.schemas.flights import FlightsAlert, FlightsKind, FlightsProgram, FlightsProgramWhy

FAA_URL: Final = "https://nasstatus.faa.gov/api/airport-status-information"
ALERTS_URL: Final = "https://api.weather.gov/alerts/active?status=actual"
METARS_URL: Final = "https://aviationweather.gov/data/cache/metars.cache.csv.gz"

WHY_LENGTH: Final = 80


class InputError(ValueError):
    """Bytes that cannot be read as the input they should be."""


@dataclass(frozen=True, slots=True)
class Program:
    """One FAA program at an airport."""

    code: str
    program: FlightsProgram
    minutes: int | None
    until: datetime | None
    why: str
    """The FAA's reason as it wrote it (screened): for the archive only."""

    @property
    def kind(self) -> FlightsProgramWhy:
        """The kind of the reason, what the live file publishes."""
        return why_kind(self.why)


_DURATION = re.compile(r"(?:(\d+)\s*hours?)?(?:\s*and\s*)?(?:(\d+)\s*minutes?)?")
_NOT_AIRLINES = re.compile(r"NON SKED|TRANSIENT|\bGA\b|PPR|EXC SKED", re.IGNORECASE)


MINUTES_MAX: Final = 1440
"""The longest delay published (a day); a longer one is not believed and not read."""
VISIBILITY_MAX: Final = 100.0
"""Miles: a report's visibility beyond this (or below 0) is not believed and not read."""
GUST_MAX: Final = 200
"""Knots: a gust or wind beyond this (or below 0) is not believed and not read."""

CEILING_MAX: Final = 100_000.0
"""Feet: a cloud base beyond this (or below 0) is not read."""
_CEILINGS: Final = ("BKN", "OVC", "OVX", "VV")


CLOCK_BEHIND: Final = timedelta(days=7)
CLOCK_AHEAD: Final = timedelta(minutes=10)
"""A source's time is read only from :data:`CLOCK_BEHIND` before the pass's clock to this
after it (:func:`on_clock`): a time after the pass is no report yet, and would show as current
what is not."""

_DROPPED: ContextVar["Counter[str] | None"] = ContextVar("dropped", default=None)


@contextmanager
def counting() -> Iterator["Counter[str]"]:
    """Count, while inside, the values read as none for being out of range (``values``) and the
    times dropped for being off the pass's clock (``times``): the source's warning line."""
    counts: Counter[str] = Counter()
    token = _DROPPED.set(counts)
    try:
        yield counts
    finally:
        _DROPPED.reset(token)


def _dropped(what: str, count: int = 1) -> None:
    counts = _DROPPED.get()
    if counts is not None and count:
        counts[what] += count


def within(value: float | None, high: float) -> float | None:
    """``value`` when it lies in 0 to ``high``, else ``None`` (and counted, :func:`counting`): a
    number out of the published range is read as no number, never as a wrong one, and never
    stops the pass."""
    if value is None:
        return None
    if 0 <= value <= high:
        return value
    _dropped("values")
    return None


def on_clock(at: datetime | None, now: datetime) -> datetime | None:
    """``at`` when it lies from :data:`CLOCK_BEHIND` before ``now`` to :data:`CLOCK_AHEAD`
    after it, else ``None`` (and counted, :func:`counting`)."""
    if at is None:
        return None
    if now - CLOCK_BEHIND <= at <= now + CLOCK_AHEAD:
        return at
    _dropped("times")
    return None


def minutes_of(text: str | None) -> int | None:
    """``1 hour and 16 minutes`` as 76; ``None`` when there is no duration or it is longer than
    :data:`MINUTES_MAX`."""
    if not text:
        return None
    match = _DURATION.search(text.strip())
    if match is None or not any(match.groups()):
        return None
    hours, minutes = match.groups()
    total = int(hours or 0) * 60 + int(minutes or 0)
    return int(value) if (value := within(total, MINUTES_MAX)) is not None else None


def _plain(reason: str | None) -> str:
    text = re.sub(r"\s+", " ", reason or "").strip()
    text = re.sub(r"[^A-Za-z0-9 /:().,-]", "", text)
    return text[:WHY_LENGTH]


_WHY_WORDS: Final = (
    (
        FlightsProgramWhy.WEATHER,
        re.compile(
            r"\bWX\b|WEATHER|SNOW|ICE|ICING|THUNDER|\bTSTM|\bTS\b|WIND|FOG|CEILING|\bCIG|VISIB|"
            r"\bLOW\b|RAIN|STORM|HURRICANE|DEICING",
            re.IGNORECASE,
        ),
    ),
    (FlightsProgramWhy.RUNWAY, re.compile(r"RUNWAY|\bRWY|CONSTRUCTION|\bCONST\b", re.I)),
    (FlightsProgramWhy.EQUIPMENT, re.compile(r"EQUIPMENT|\bEQUIP|OUTAGE|\bEQ\b", re.I)),
    (FlightsProgramWhy.VOLUME, re.compile(r"VOLUME|\bVOL\b|DEMAND|\bTM INITIATIVES", re.I)),
)


def why_kind(reason: str | None) -> FlightsProgramWhy:
    """The kind of an FAA reason (``WX:Snow/Ice``, ``Volume:Volume``, ``TM Initiatives:MIT:WX``):
    the first kind whose words it names, weather first; ``OTHER`` for none (the raw text is kept
    in the archive only, never published)."""
    text = reason or ""
    for kind, words in _WHY_WORDS:
        if words.search(text):
            return kind
    return FlightsProgramWhy.OTHER


_ZONE_HOURS: Final = {
    "EST": -5,
    "EDT": -4,
    "CST": -6,
    "CDT": -5,
    "MST": -7,
    "MDT": -6,
    "PST": -8,
    "PDT": -7,
    "AKST": -9,
    "AKDT": -8,
    "HST": -10,
    "AST": -4,
    "UTC": 0,
    "GMT": 0,
    "Z": 0,
}
_LOCAL_CLOCK = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([AaPp])\.?\s*[Mm]\.?\s*([A-Z]{1,4})\b")
_UTC_CLOCK = re.compile(r"\b(\d{1,2}):?(\d{2})\s*(UTC|GMT|Z)\b")


def _next_at(now: datetime, hour: int, minute: int, offset: int) -> datetime:
    """The moment nearest ``now`` (within 12 hours either way) whose clock at UTC ``offset``
    hours reads ``hour:minute``: a program's end is hours away at most, and one just past is
    kept as written, never moved to the next day."""
    local = now.astimezone(UTC) + timedelta(hours=offset)
    moment = local.replace(hour=hour, minute=minute, second=0, microsecond=0) - timedelta(
        hours=offset
    )
    half = timedelta(hours=12)
    while moment - now > half:
        moment -= timedelta(days=1)
    while now - moment > half:
        moment += timedelta(days=1)
    return moment


def _when(text: str | None, now: datetime) -> datetime | None:
    """An FAA end time as an instant: ``8:00 pm EST`` (a 12-hour clock in a US zone, as the FAA
    writes it), ``2230 UTC`` or ``Nov 21 at 22:30 UTC.``: the clock time nearest ``now``
    (:func:`_next_at`). ``None`` for any other form: a time that cannot be read is never
    guessed."""
    if not text:
        return None
    local = _LOCAL_CLOCK.search(text)
    if local is not None:
        hour, minute = int(local.group(1)), int(local.group(2) or 0)
        zone = _ZONE_HOURS.get(local.group(4).upper())
        if zone is None or not 1 <= hour <= 12 or minute > 59:  # noqa: PLR2004 - a 12-hour clock
            return None
        hour = hour % 12 + (12 if local.group(3).lower() == "p" else 0)
        return _next_at(now, hour, minute, zone)
    clock = _UTC_CLOCK.search(text)
    if clock is None:
        return None
    hour, minute = int(clock.group(1)), int(clock.group(2))
    if hour > 23 or minute > 59:  # noqa: PLR2004 - a clock
        return None
    return _next_at(now, hour, minute, 0)


def read_faa(data: bytes, now: datetime) -> tuple[datetime, list[Program]]:  # noqa: PLR0912
    """The FAA status: when the FAA wrote it, and its programs at airports.

    Raises:
        InputError: the bytes are not the status XML.
    """
    try:
        root = ET.fromstring(data)  # noqa: S314 - see the import
    except ET.ParseError as error:
        raise InputError(f"FAA status: {error}") from error
    if root.tag != "AIRPORT_STATUS_INFORMATION":
        raise InputError(f"FAA status: unexpected root {root.tag}")
    written = root.findtext("Update_Time")
    try:
        at = datetime.strptime(written or "", "%a %b %d %H:%M:%S %Y GMT").replace(tzinfo=UTC)
    except ValueError as error:
        raise InputError(f"FAA status: no update time ({written!r})") from error
    if on_clock(at, now) is None:
        raise InputError(f"FAA status: its update time {at:%Y-%m-%dT%H:%M:%SZ} is off the clock")
    programs: list[Program] = []
    for kind in root.findall("Delay_type"):
        name = (kind.findtext("Name") or "").lower()
        for item in (element for group in kind if group.tag != "Name" for element in group):
            code = (item.findtext("ARPT") or "").strip().upper()
            if not re.fullmatch(r"[A-Z0-9]{3}", code):
                continue
            reason = item.findtext("Reason")
            if "ground stop" in name:
                programs.append(
                    Program(
                        code,
                        FlightsProgram.GROUND_STOP,
                        None,
                        _when(item.findtext("End_Time"), now),
                        _plain(reason),
                    )
                )
            elif "ground delay" in name:
                programs.append(
                    Program(
                        code,
                        FlightsProgram.GROUND_DELAY,
                        minutes_of(item.findtext("Avg")),
                        None,
                        _plain(reason),
                    )
                )
            elif "arrival/departure" in name:
                for leg in item.findall("Arrival_Departure"):
                    program = (
                        FlightsProgram.ARRIVAL_DELAY
                        if leg.get("Type", "").lower().startswith("arr")
                        else FlightsProgram.DEPARTURE_DELAY
                    )
                    programs.append(
                        Program(
                            code, program, minutes_of(leg.findtext("Max")), None, _plain(reason)
                        )
                    )
            elif "closure" in name:
                if reason is None or _NOT_AIRLINES.search(reason) or "CLSD" not in reason.upper():
                    continue
                programs.append(Program(code, FlightsProgram.CLOSED, None, None, ""))
            elif "deicing" in name:
                programs.append(Program(code, FlightsProgram.DEICING, None, None, _plain(reason)))
    return at, programs


ALERT_EVENTS: Final[dict[str, FlightsAlert]] = {
    "Winter Storm Warning": FlightsAlert.WINTER_STORM,
    "Blizzard Warning": FlightsAlert.BLIZZARD,
    "Ice Storm Warning": FlightsAlert.ICE_STORM,
    "Winter Weather Advisory": FlightsAlert.WINTER_WEATHER,
    "Severe Thunderstorm Warning": FlightsAlert.SEVERE_THUNDERSTORM,
    "Tornado Warning": FlightsAlert.TORNADO,
    "High Wind Warning": FlightsAlert.HIGH_WIND,
    "Dense Fog Advisory": FlightsAlert.DENSE_FOG,
    "Hurricane Warning": FlightsAlert.HURRICANE,
    "Tropical Storm Warning": FlightsAlert.TROPICAL_STORM,
    "Extreme Cold Warning": FlightsAlert.EXTREME_COLD,
}


def _instant(text: object) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        return datetime.fromisoformat(text).astimezone(UTC)
    except ValueError:
        return None


def read_alerts(
    data: bytes, places: Mapping[str, Iterable[str]], now: datetime
) -> tuple[datetime, dict[str, list[FlightsAlert]]]:
    """The alerts in effect now at each airport (``places``: airport code to its zone and county
    codes), and the time the list was updated.

    Raises:
        InputError: the bytes are not the alerts list.
    """
    try:
        document = json.loads(data)
        features = document["features"]
        updated = _instant(document.get("updated"))
    except (ValueError, KeyError, TypeError) as error:
        raise InputError(f"NWS alerts: {error}") from error
    if updated is None or not isinstance(features, list):
        raise InputError("NWS alerts: no update time")
    if on_clock(updated, now) is None:
        raise InputError(
            f"NWS alerts: their update time {updated:%Y-%m-%dT%H:%M:%SZ} is off the clock"
        )
    by_code: dict[str, set[str]] = {}
    for code, ugcs in places.items():
        for ugc in ugcs:
            if ugc:
                by_code.setdefault(ugc, set()).add(code)
    found: dict[str, set[FlightsAlert]] = {}
    for feature in features:
        props = feature.get("properties", {}) if isinstance(feature, dict) else {}
        alert = ALERT_EVENTS.get(str(props.get("event", "")))
        if alert is None or props.get("status") != "Actual":
            continue
        onset = _instant(props.get("onset")) or _instant(props.get("effective"))
        ends = _instant(props.get("ends")) or _instant(props.get("expires"))
        if (onset is not None and onset > now) or (ends is not None and ends <= now):
            continue
        for ugc in (props.get("geocode") or {}).get("UGC", []):
            for code in by_code.get(str(ugc), ()):
                found.setdefault(code, set()).add(alert)
    return updated, {code: sorted(alerts) for code, alerts in found.items()}


@dataclass(frozen=True, slots=True)
class Report:
    """An airport's latest weather report."""

    at: datetime
    kinds: tuple[FlightsKind, ...]
    visibility: float | None
    gust: int | None


def _kinds(
    wx: str, visibility: float | None, ceiling: int | None, wind: int | None, gust: int | None
) -> tuple[FlightsKind, ...]:
    kinds: list[FlightsKind] = []
    if re.search(r"FZRA|FZDZ|(^|\s)[-+]?PL", wx):
        kinds.append(FlightsKind.FREEZING_RAIN)
    if re.search(r"(^|\s)[-+]?(?:SH|TS)?(?:RA|DZ)?SN", wx):
        kinds.append(FlightsKind.SNOW)
    if "TS" in wx:
        kinds.append(FlightsKind.THUNDER)
    if (visibility is not None and visibility < 1) or (ceiling is not None and ceiling < 500):  # noqa: PLR2004
        kinds.append(FlightsKind.FOG)
    if (wind is not None and wind >= 30) or (gust is not None and gust >= 40):  # noqa: PLR2004
        kinds.append(FlightsKind.WIND)
    return tuple(kinds)


def _number(text: str | None) -> float | None:
    """A report's number; ``None`` when empty, not a number, or not finite (``nan``, ``inf``)."""
    if not text:
        return None
    try:
        value = float(text.rstrip("+"))
    except ValueError:
        return None
    if math.isfinite(value):
        return value
    _dropped("values")
    return None


def _whole(text: str | None) -> int | None:
    value = _number(text)
    return None if value is None else int(value)


def read_metars(data: bytes, stations: Mapping[str, str], now: datetime) -> dict[str, Report]:
    """The latest report of each airport (``stations``: report id, such as ``KMCI``, to code),
    of the reports on the pass's clock (:func:`on_clock`): one dated after the pass never hides
    the real newest one.

    Raises:
        InputError: the bytes are not the gzipped report table.
    """
    try:
        text = gzip.decompress(data).decode("utf-8", "replace")
    except (OSError, EOFError) as error:
        raise InputError(f"weather reports: {error}") from error
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if header is None or "station_id" not in header:
        raise InputError("weather reports: no header")
    index = {name: header.index(name) for name in dict.fromkeys(header)}
    covers = [i for i, name in enumerate(header) if name == "sky_cover"]
    bases = [i for i, name in enumerate(header) if name == "cloud_base_ft_agl"]
    out: dict[str, Report] = {}
    for row in reader:
        if len(row) < len(header):
            continue
        code = stations.get(row[index["station_id"]])
        if code is None:
            continue
        at = on_clock(_instant(row[index["observation_time"]].replace(".000Z", "+00:00")), now)
        if at is None or (code in out and out[code].at >= at):
            continue
        ceiling = None
        for cover, base in zip(covers, bases, strict=False):
            base_ft = within(_number(row[base]), CEILING_MAX)
            value = int(base_ft) if base_ft is not None and row[cover] in _CEILINGS else None
            if value is not None:
                ceiling = value if ceiling is None else min(ceiling, value)
        visibility = within(_number(row[index["visibility_statute_mi"]]), VISIBILITY_MAX)
        wind = within(_number(row[index["wind_speed_kt"]]), GUST_MAX)
        gust = within(_number(row[index["wind_gust_kt"]]), GUST_MAX)
        out[code] = Report(
            at=at,
            kinds=_kinds(
                row[index["wx_string"]],
                visibility,
                ceiling,
                None if wind is None else int(wind),
                None if gust is None else int(gust),
            ),
            visibility=visibility,
            gust=None if gust is None else int(gust),
        )
    return out


OBSERVED_LAG_HOURS: Final = 3
"""The reports read for the observed-before inputs must reach this close to the newest run, or
they are not read (a late archive would count a storm's last hours as none)."""


def observed_window(runs: Sequence[datetime]) -> tuple[datetime, datetime]:
    """The span of reports the observed-before inputs of ``runs`` need: from 49 hours before the
    oldest (an hour counts for the hour after its report, so the hour before the 48 counts its
    last report) to the newest."""
    return min(runs) - timedelta(hours=OBSERVED_HOURS + 1), max(runs)


def read_observed(data: bytes, newest_run: datetime) -> pl.DataFrame:
    """The hourly report flags of a window request (:func:`snowlight.flights.obs.window_url`),
    read as the history's are, of the hours from :data:`CLOCK_BEHIND` before the newest run to
    the run: an hour after it was not known when the run was issued, and would mark a lagging
    station fresh (the others are counted, :func:`counting`).

    Raises:
        InputError: not the table of reports, or the reports end too long before the run.
    """
    try:
        every = reduce_bytes(data)
    except ReportsError as error:
        raise InputError(f"observed reports: {error}") from error
    flags = every.filter(pl.col("hour").is_between(newest_run - CLOCK_BEHIND, newest_run))
    _dropped("times", len(every) - len(flags))
    newest = flags.get_column("hour").max() if len(flags) else None
    if not isinstance(newest, datetime):
        raise InputError("observed reports: none")
    if newest < newest_run - timedelta(hours=OBSERVED_LAG_HOURS):
        raise InputError(f"observed reports: they end at {newest:%Y-%m-%dT%HZ}, too early")
    return flags


def fresh_stations(flags: pl.DataFrame, newest_run: datetime) -> frozenset[str]:
    """The stations whose own reports reach within :data:`OBSERVED_LAG_HOURS` of the newest
    run: a station missing or behind counts as not read (its airport shows the usual rate)."""
    if flags.is_empty():
        return frozenset()
    newest = flags.group_by("station").agg(pl.col("hour").max())
    cutoff = newest_run - timedelta(hours=OBSERVED_LAG_HOURS)
    return frozenset(newest.filter(pl.col("hour") >= cutoff).get_column("station").to_list())


TAFS_URL: Final = "https://aviationweather.gov/data/cache/tafs.cache.xml.gz"


def read_tafs(data: bytes, stations: Mapping[str, str]) -> dict[str, str]:
    """Each airport's newest TAF text (``stations``: TAF id to code), for the archive only.

    Raises:
        InputError: the bytes are not the gzipped TAF list.
    """
    try:
        root = ET.fromstring(gzip.decompress(data))  # noqa: S314 - see the import
    except (OSError, EOFError, ET.ParseError) as error:
        raise InputError(f"TAFs: {error}") from error
    out: dict[str, tuple[str, str]] = {}
    for taf in root.iter("TAF"):
        code = stations.get(taf.findtext("station_id") or "")
        text = (taf.findtext("raw_text") or "").strip()
        issued = taf.findtext("issue_time") or ""
        if code is None or not text:
            continue
        if code not in out or out[code][0] < issued:
            out[code] = (issued, text[:2000])
    return {code: text for code, (_, text) in out.items()}
