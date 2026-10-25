"""Past alerts as known at 21:00 the evening before, from each event's product stream.

The history path (:mod:`snowlight.predict.alerts_history`) reads IEM's season files, one row
per event and zone. Their times are not as of the snapshot: ``utc_issue`` (the start) is the
zone's start as IEM last recorded it, which a later product can move with no trace;
``utc_init_expire`` is the zone's first product's end; ``utc_expire`` the final end; and the
text a ``product_id`` names is the first product's alone (calc-research plan T2).

IEM's VTEC event record (``json/vtec_event.py``) holds the event's first product (``report``)
and every follow-up (``svs``), each with its issue time (``valid``) and its text. This module
reads those records and rebuilds, for a zone at a moment ``as_of``, the event as the latest
product issued by then states it (:func:`zone_state`):

* only products issued at or before ``as_of`` count; a product's segment counts for a zone
  when its UGC line names the zone and one of its P-VTEC lines names the event;
* the start is the segment's VTEC begin, or the product's issue time when the begin is not
  given (an event already in effect), as the live path takes ``onset or effective``
  (:mod:`snowlight.predict.alerts_live`); ``began`` keeps the earliest begin any kept product
  stated, for timing;
* the end is the segment's VTEC end (``None``: until further notice);
* rule D2 (S7-F): a zone a ``CAN`` or ``UPG`` segment takes back no longer counts from that
  product's issue time; an ``EXP`` segment ends it at its stated end;
* the type words (:class:`Words`) and the elevation lines
  (:func:`snowlight.sources.nws.elevation.parse_alert_text`) come from the latest counting
  segment's headline and description. Only the parsed flags and numbers are kept, never the
  text (spec addendum e, E1).

Fetching (:func:`fetch_events`) asks one record a second with the site's User-Agent
(:data:`snowlight.predict.inputs.USER_AGENT`), caches each record under the gitignored
``.cache/predict/vtec-events`` and keeps the cached records of its events within a cap (100 MB,
spec addendum 2026-10-20 item 4): it asks for no more once the room left under the cap is less
than the largest record seen, and a record that would still take the cache past the cap is
dropped, never cached (its bytes are counted as downloaded).
"""

import json
import re
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import UTC, date, datetime, timedelta
from datetime import time as time_of_day
from pathlib import Path
from typing import Final

import polars as pl

from snowlight.predict.alerts_history import HistoryRow, Reach, district_day_classes
from snowlight.predict.config import PIPELINE_ROOT
from snowlight.predict.situations import CLASS_BY_CODE, Event, WeatherClass, Window, school_class
from snowlight.sources.nws.elevation import ElevationLimit, parse_alert_text
from snowlight.sources.nws.vtec import Vtec, VtecError, parse_vtec

EVENT_URL: Final = "https://mesonet.agron.iastate.edu/json/vtec_event.py"
CACHE: Final = PIPELINE_ROOT / ".cache" / "predict" / "vtec-events"
BYTE_CAP: Final = 100_000_000
"""The most the cached records of a fetch's events may hold, those fetched before included
(100 MB, spec addendum 2026-10-20 item 4)."""
PAUSE_SECONDS: Final = 1.0
"""One request a second."""
WITHDRAWN: Final = frozenset({"CAN", "UPG"})
EXPIRED: Final = "EXP"

_UGC_END: Final = re.compile(r"\d{6}-\s*$")
_UGC_CHARS: Final = re.compile(r"^[A-Z0-9>-]+$")
"""A UGC line holds codes, ranges and dashes only; a text line that starts like one does not."""
_UGC_START: Final = re.compile(r"^[A-Z]{2}[CZ](?:\d{3}|ALL)")
_UGC_TOKEN: Final = re.compile(
    r"^(?:(?P<state>[A-Z]{2})(?P<kind>[CZ]))?(?P<first>\d{3}|ALL)(?:>(?P<last>\d{3}))?$"
)
_PVTEC_LINE: Final = re.compile(
    r"/[OTEX]\.[A-Z]{3}\.[A-Z0-9]{4}\.[A-Z0-9]{2}\.[A-Z]\.\d{4}\.\d{6}T\d{4}Z-\d{6}T\d{4}Z/"
)
_HEADLINE: Final = re.compile(r"^\s*\.\.\.(.+?)\.\.\.\s*$", re.MULTILINE | re.DOTALL)
_BODY_END: Final = re.compile(r"PRECAUTIONARY/PREPAREDNESS ACTIONS|^&&", re.MULTILINE)


class StreamError(ValueError):
    """An event record does not read as documented."""


@dataclass(frozen=True, slots=True, order=True)
class EventKey:
    """One VTEC event: its office (three letters), code, number and VTEC year."""

    wfo: str
    phenomena: str
    significance: str
    etn: int
    year: int

    @property
    def code(self) -> str:
        """``WW.Y``."""
        return f"{self.phenomena}.{self.significance}"

    @property
    def query(self) -> dict[str, str]:
        """The record's request parameters."""
        return {
            "wfo": self.wfo,
            "year": str(self.year),
            "phenomena": self.phenomena,
            "significance": self.significance,
            "etn": str(self.etn),
        }

    def path(self, cache: Path) -> Path:
        """Where the record is cached."""
        return cache / str(self.year) / f"{self.wfo}.{self.code}.{self.etn:04d}.json"

    def matches(self, vtec: Vtec) -> bool:
        """Whether a P-VTEC string names this event (its office as K + three letters, or the
        four-letter office of Alaska, Hawaii and Puerto Rico ending in the three)."""
        return (
            vtec.phenomena == self.phenomena
            and vtec.significance == self.significance
            and vtec.etn == self.etn
            and vtec.office[1:] == self.wfo
        )


@dataclass(frozen=True, slots=True)
class Words:
    """The weather type a segment's headline and description name (flags only)."""

    snow: bool = False
    sleet: bool = False
    freezing_rain: bool = False
    freezing_drizzle: bool = False
    rain: bool = False
    mix: bool = False
    """"Mixed precipitation", "wintry mix", "rain and snow" or "rain changing to snow"."""
    ice: bool = False

    def as_json(self) -> dict[str, bool]:
        """The flags as a JSON object."""
        return {item.name: bool(getattr(self, item.name)) for item in fields(self)}


_SNOW: Final = re.compile(r"\bsnow", re.I)
_SLEET: Final = re.compile(r"\bsleet\b", re.I)
_FREEZING_RAIN: Final = re.compile(r"\bfreezing rain\b", re.I)
_FREEZING_DRIZZLE: Final = re.compile(r"\bfreezing drizzle\b", re.I)
_RAIN: Final = re.compile(r"(?<!freezing )\brain\b", re.I)
_MIX: Final = re.compile(
    r"\bmixed precipitation\b|\bwintry mix\b|\brain and snow\b|\bsnow and rain\b"
    r"|\brain(?: will)? (?:changing|change|transition|mixing) (?:over )?(?:to|with) snow\b"
    r"|\bsnow(?: will)? (?:changing|change|transition|mixing) (?:over )?(?:to|with) rain\b",
    re.I,
)
_ICE: Final = re.compile(r"\bice\b|\bicing\b|\bice accumulations?\b", re.I)


def words_of(text: str) -> Words:
    """The type flags of a segment's headline and description."""
    plain = " ".join(text.split())
    return Words(
        snow=bool(_SNOW.search(plain)),
        sleet=bool(_SLEET.search(plain)),
        freezing_rain=bool(_FREEZING_RAIN.search(plain)),
        freezing_drizzle=bool(_FREEZING_DRIZZLE.search(plain)),
        rain=bool(_RAIN.search(plain)),
        mix=bool(_MIX.search(plain)),
        ice=bool(_ICE.search(plain)),
    )


@dataclass(frozen=True, slots=True)
class Segment:
    """One segment of a product: the zones it names, its P-VTEC strings, its headlines and
    its description (kept only while a record is read, never written out)."""

    ugcs: frozenset[str]
    vtecs: tuple[Vtec, ...]
    headlines: tuple[str, ...]
    description: str


@dataclass(frozen=True, slots=True)
class Product:
    """One product of an event: when it was issued, its id, and its segments."""

    issued: datetime
    product_id: str
    segments: tuple[Segment, ...]


def expand_ugcs(line: str) -> frozenset[str]:
    """The zone and county codes of a UGC line (``CTZ005>008-NJZ002-004-281015-``).

    Raises:
        StreamError: a token does not read.
    """
    text = "".join(line.split())
    tokens = [token for token in text.split("-") if token]
    if tokens and re.fullmatch(r"\d{6}", tokens[-1]):
        tokens = tokens[:-1]
    found: set[str] = set()
    prefix: str | None = None
    for token in tokens:
        match = _UGC_TOKEN.match(token)
        if match is None:
            raise StreamError(f"not a UGC token: {token!r}")
        if match["state"]:
            prefix = f"{match['state']}{match['kind']}"
        if prefix is None:
            raise StreamError(f"UGC token without a state: {token!r}")
        if match["first"] == "ALL":
            found.add(f"{prefix}ALL")
            continue
        first = int(match["first"])
        last = int(match["last"]) if match["last"] else first
        found.update(f"{prefix}{number:03d}" for number in range(first, last + 1))
    return frozenset(found)


def _segment(chunk: str) -> Segment | None:
    """One ``$$``-delimited chunk as a segment, or ``None`` when it has no UGC line."""
    lines = chunk.replace("\r", "").split("\n")
    for start, line in enumerate(lines):
        if not _UGC_START.match(line.strip()):
            continue
        ugc_text = ""
        end = start
        while end < len(lines) and _UGC_CHARS.match(lines[end].strip()):
            ugc_text += lines[end].strip()
            end += 1
            if _UGC_END.search(ugc_text):
                break
        if not _UGC_END.search(ugc_text):
            continue
        try:
            ugcs = expand_ugcs(ugc_text)
        except StreamError:
            continue
        return _body(ugcs, "\n".join(lines[end:]))
    return None


def _body(ugcs: frozenset[str], rest: str) -> Segment:
    """The segment of ``ugcs`` whose text after its UGC line is ``rest``."""
    vtecs: list[Vtec] = []
    for match in _PVTEC_LINE.finditer(rest):
        try:
            vtecs.append(parse_vtec(match.group(0)))
        except VtecError:
            continue
    headlines = tuple(" ".join(match.group(1).split()) for match in _HEADLINE.finditer(rest))
    star = rest.find("\n*")
    body = rest[star + 1 :] if star >= 0 else rest
    cut = _BODY_END.search(body)
    description = body[: cut.start()] if cut else body
    return Segment(ugcs, tuple(vtecs), headlines, description.strip())


def segments(text: str) -> tuple[Segment, ...]:
    """The segments of one product's text."""
    found = [_segment(chunk) for chunk in text.split("$$")]
    return tuple(item for item in found if item is not None)


def _issued(value: object) -> datetime:
    if not isinstance(value, str):
        raise StreamError(f"no issue time: {value!r}")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        try:
            return datetime.strptime(value, "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC)
        except ValueError as error:
            raise StreamError(f"bad issue time: {value!r}") from error


def parse_record(record: Mapping[str, object]) -> tuple[Product, ...]:
    """The products of one event record, in issue order (the first product and every
    follow-up; a product IEM lists twice is kept once).

    Raises:
        StreamError: the record does not read.
    """
    if record.get("event_exists") is False:
        return ()
    first = record.get("report")
    follow = record.get("svs") or []
    if not isinstance(follow, list):
        raise StreamError("svs is not a list")
    items = ([first] if isinstance(first, dict) else []) + list(follow)
    found: dict[str, Product] = {}
    for item in items:
        if not isinstance(item, dict):
            raise StreamError("a product is not an object")
        text = item.get("text")
        if not isinstance(text, str):
            raise StreamError("a product has no text")
        issued = _issued(item.get("valid"))
        product_id = str(item.get("product_id") or issued.isoformat())
        found[product_id] = Product(issued, product_id, segments(text))
    return tuple(sorted(found.values(), key=lambda product: (product.issued, product.product_id)))


@dataclass(frozen=True, slots=True)
class ZoneState:
    """One zone of one event as the products issued by ``as_of`` state it (parsed values
    only: the times, the action, the type flags and the elevation bands)."""

    ugc: str
    code: str
    first_issued: datetime
    """The first product that named the zone."""
    updated: datetime
    """The latest product that named the zone."""
    action: str
    start: datetime
    began: datetime | None
    """The earliest VTEC begin a kept product stated (``None``: none stated one)."""
    end: datetime | None
    withdrawn: bool
    words: Words
    elevation: ElevationLimit | None

    def event(self) -> Event | None:
        """The event the class rule reads (``None``: withdrawn, rule D2)."""
        if self.withdrawn:
            return None
        return Event(self.code, self.first_issued, self.start, self.end)


def zone_state(
    key: EventKey, products: Sequence[Product], ugc: str, as_of: datetime
) -> ZoneState | None:
    """``ugc`` in event ``key`` as the products issued by ``as_of`` state it (see the module
    docstring), or ``None`` when no such product names it."""
    first: datetime | None = None
    began: datetime | None = None
    kept: tuple[Product, Segment, Vtec] | None = None
    ended: tuple[Product, Vtec] | None = None
    for product in products:
        if product.issued > as_of:
            break
        for segment in product.segments:
            if ugc not in segment.ugcs:
                continue
            vtec = next((v for v in segment.vtecs if key.matches(v)), None)
            if vtec is None:
                continue
            first = first or product.issued
            if vtec.begin is not None:
                began = vtec.begin if began is None else min(began, vtec.begin)
            if vtec.action in WITHDRAWN or vtec.action == EXPIRED:
                ended = (product, vtec)
            else:
                kept = (product, segment, vtec)
                ended = None
    if first is None:
        return None
    if kept is None:
        assert ended is not None  # noqa: S101 - a zone named only by an ending product
        product, vtec = ended
        return ZoneState(
            ugc, key.code, first, product.issued, vtec.action, vtec.begin or product.issued,
            began, vtec.end, vtec.action in WITHDRAWN, Words(), None,
        )  # fmt: skip
    product, segment, vtec = kept
    end = vtec.end
    action = vtec.action
    updated = product.issued
    withdrawn = False
    if ended is not None:
        last, ending = ended
        action, updated = ending.action, last.issued
        withdrawn = ending.action in WITHDRAWN
        if ending.action == EXPIRED and ending.end is not None:
            end = ending.end if end is None else min(end, ending.end)
    text = "\n".join([*segment.headlines, segment.description])
    return ZoneState(
        ugc=ugc,
        code=key.code,
        first_issued=first,
        updated=updated,
        action=action,
        start=vtec.begin or product.issued,
        began=began,
        end=end,
        withdrawn=withdrawn,
        words=words_of(text),
        elevation=parse_alert_text(segment.headlines, None, segment.description or None),
    )


def zones_named(key: EventKey, products: Iterable[Product]) -> frozenset[str]:
    """Every zone some product of the event names for it."""
    found: set[str] = set()
    for product in products:
        for segment in product.segments:
            if any(key.matches(vtec) for vtec in segment.vtecs):
                found |= segment.ugcs
    return frozenset(found)


def key_of_row(wfo: str, phenomena: str, significance: str, etn: int, year: int) -> EventKey | None:
    """The event of a season-file row, when its code makes a class."""
    key = EventKey(wfo, phenomena, significance, int(etn), int(year))
    return key if key.code in CLASS_BY_CODE else None


# --- fetching -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FetchReport:
    """What a fetch did."""

    requested: int
    """Requests sent."""
    cached: int
    """Records already in the cache (no request)."""
    bytes_fetched: int
    """Bytes downloaded by this fetch."""
    bytes_cached: int
    """Bytes of every record of ``keys`` in the cache afterwards."""
    stopped_at_cap: bool
    missing: tuple[EventKey, ...]
    """Records not fetched or not kept (the cap, or an error)."""
    errors: tuple[str, ...]
    bytes_dropped: int = 0
    """Bytes of a record downloaded and dropped because keeping it would pass the cap (part of
    ``bytes_fetched``)."""


type Get = Callable[[Mapping[str, str]], bytes]
"""Fetch one record's bytes for its request parameters."""


def fetch_events(  # noqa: PLR0913 - the keys, the cache, the fetcher and its limits
    keys: Sequence[EventKey],
    cache: Path,
    get: Get,
    *,
    cap: int = BYTE_CAP,
    pause: float = PAUSE_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> FetchReport:
    """Fetch every record of ``keys`` not yet cached, in their order, one request each ``pause``
    seconds, keeping the records of ``keys`` in the cache (those an earlier fetch kept
    included) within ``cap`` bytes: nothing more is asked once the room left is less than the
    largest record seen (cached or fetched), and a record that would still pass the cap is
    dropped, not cached, and ends the fetch."""
    requested = cached = fetched = dropped = 0
    stopped = False
    missing: list[EventKey] = []
    errors: list[str] = []
    wanted = list(dict.fromkeys(keys))
    sizes = [key.path(cache).stat().st_size for key in wanted if key.path(cache).exists()]
    held, largest = sum(sizes), max(sizes, default=0)
    for key in wanted:
        path = key.path(cache)
        if path.exists():
            cached += 1
            continue
        if stopped or cap - held < max(largest, 1):
            stopped = True
            missing.append(key)
            continue
        if requested:
            sleep(pause)
        requested += 1
        try:
            body = get(key.query)
            json.loads(body)
        except (OSError, ValueError) as error:
            errors.append(f"{key.wfo}.{key.code}.{key.etn:04d}.{key.year}: {type(error).__name__}")
            missing.append(key)
            continue
        fetched += len(body)
        largest = max(largest, len(body))
        if held + len(body) > cap:
            dropped += len(body)
            stopped = True
            missing.append(key)
            continue
        held += len(body)
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_suffix(".part")
        part.write_bytes(body)
        part.replace(path)
    on_disk = sum(key.path(cache).stat().st_size for key in set(keys) if key.path(cache).exists())
    return FetchReport(
        requested, cached, fetched, on_disk, stopped, tuple(missing), tuple(errors), dropped
    )


def read_cached(key: EventKey, cache: Path) -> tuple[Product, ...] | None:
    """The cached record's products, or ``None`` when it is not cached.

    Raises:
        StreamError: the record does not read.
    """
    path = key.path(cache)
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_bytes())
    except ValueError as error:
        raise StreamError(f"{path.name}: {error}") from error
    if not isinstance(record, dict):
        raise StreamError(f"{path.name}: not an object")
    return parse_record(record)


# --- which events --------------------------------------------------------------------------------

_SNAPSHOT_LATEST: Final = time_of_day(6, 0)
"""21:00 local on D-1 is at or before 06:00 UTC on D in every contiguous zone (PST)."""
_WINDOW_EARLIEST: Final = time_of_day(22, 0)
"""18:00 local on D-1 is at or after 22:00 UTC on D-1 (EDT)."""


_WINDOW_LATEST: Final = time_of_day(17, 0)
"""09:00 local on D is at or before 17:00 UTC on D (PST)."""


def event_keys(rows: Iterable[HistoryRow], days: Iterable[date]) -> list[EventKey]:
    """The class-making events a snapshot of ``days`` can know of: a zone row of the event was
    issued by 06:00 UTC on D, ends after 22:00 UTC on D-1 (its first or its final end), and
    starts before D+2 (a superset: a later product may have moved the start the season file
    records). Events with a row whose recorded start is before 17:00 UTC on D (so its span can
    meet the window) come first, so a fetch the cap stops misses only the others."""
    wanted = sorted(set(days))
    found: dict[EventKey, bool] = {}
    for row in rows:
        last = row.final_end if row.end is None else max(row.end, row.final_end)
        for day in wanted:
            snapshot = datetime.combine(day, _SNAPSHOT_LATEST, tzinfo=UTC)
            early = datetime.combine(day - timedelta(days=1), _WINDOW_EARLIEST, tzinfo=UTC)
            late = datetime.combine(day + timedelta(days=2), time_of_day(0, 0), tzinfo=UTC)
            if row.issued <= snapshot and last > early and row.start < late:
                key = parse_key(row.event_key)
                window = row.start < datetime.combine(day, _WINDOW_LATEST, tzinfo=UTC)
                found[key] = found.get(key, False) or window
    return sorted(found, key=lambda key: (not found[key], key))


def parse_key(text: str) -> EventKey:
    """The event of a history row's ``event_key`` (``OKX.WW.Y.0002.2023``).

    Raises:
        StreamError: it does not read.
    """
    parts = text.split(".")
    if len(parts) != 5:  # noqa: PLR2004
        raise StreamError(f"not an event key: {text!r}")
    wfo, phenomena, significance, etn, year = parts
    return EventKey(wfo, phenomena, significance, int(etn), int(year))


# --- classes as of the snapshot -----------------------------------------------------------------

type Streams = Mapping[EventKey, Sequence[Product]]
"""Each fetched event's products (an event missing here keeps the season file's row)."""


@dataclass(frozen=True, slots=True)
class RowDay:
    """One season-file row on one day in one time zone: the class the history gives it, the
    class its product stream gives it at the snapshot, and the stream's state then."""

    day: date
    history: WeatherClass
    stream: WeatherClass
    state: ZoneState | None
    start_move: str | None
    """``later``: at the snapshot the stream's start was before the window's end and the season
    file's start (moved by a later product) is not; ``earlier``: the other way round."""
    streamed: bool = True
    """``False``: the event has no stream (not fetched): both sides are the history's."""


def row_days(
    row: HistoryRow,
    zone: str,
    window: Window,
    streams: Streams,
    days: Iterable[date],
) -> list[RowDay]:
    """``row`` on each of ``days`` it touches in ``zone``, by the history's rule and by its
    product stream's state at the day's snapshot (rule D2; :func:`zone_state`). An event with
    no stream keeps the history's class on both sides."""
    key = parse_key(row.event_key)
    products = streams.get(key)
    found: list[RowDay] = []
    last = row.final_end if row.end is None else max(row.end, row.final_end)
    for day in days:
        as_of = window.snapshot(day, zone)
        early, late = window.span(day, zone)
        if row.issued > as_of + timedelta(days=2) or last < early - timedelta(days=2):
            continue
        history = school_class([row.event(as_of)], day, zone, window, as_of)
        if products is None:
            if history is not WeatherClass.NONE:
                found.append(RowDay(day, history, history, None, None, streamed=False))
            continue
        state = zone_state(key, products, row.ugc, as_of)
        event = state.event() if state is not None else None
        stream = (
            WeatherClass.NONE if event is None else school_class([event], day, zone, window, as_of)
        )
        move: str | None = None
        if state is not None and not state.withdrawn and row.issued <= as_of:
            if state.start < late <= row.start:
                move = "later"
            elif row.start < late <= state.start:
                move = "earlier"
        if history is not WeatherClass.NONE or stream is not WeatherClass.NONE or move:
            found.append(RowDay(day, history, stream, state, move))
    return found


def school_row_days(  # noqa: PLR0913, PLR0917 - the rows, their reach, zones and streams
    rows: Iterable[HistoryRow],
    reach: Reach,
    zone_of_school: Sequence[str | None],
    window: Window,
    streams: Streams,
    days: Sequence[date],
) -> pl.DataFrame:
    """Every (school, day, row) of ``days`` where the history or the stream gives a class, or a
    later product moved the start across the window's end: the school's directory index, the
    day, both classes, the event and the stream's parsed state (times, action, type flags and
    the first elevation band; never text)."""
    zones = [zone or "" for zone in zone_of_school]
    out: dict[str, list[object]] = {name: [] for name in ROW_DAY_SCHEMA}
    for row in rows:
        reached = reach.schools(row)
        if reached is None or not reached.size:
            continue
        by_zone: dict[str, list[int]] = {}
        for index in reached.tolist():
            if 0 <= index < len(zones) and zones[index]:
                by_zone.setdefault(zones[index], []).append(index)
        for zone, group in sorted(by_zone.items()):
            for item in row_days(row, zone, window, streams, days):
                state = item.state
                words = state.words if state is not None else Words()
                band = state.elevation.bands[0] if state and state.elevation else None
                for school in group:
                    out["school"].append(school)
                    out["day"].append(item.day)
                    out["event"].append(row.event_key)
                    out["ugc"].append(row.ugc)
                    out["history"].append(int(item.history))
                    out["stream"].append(int(item.stream))
                    out["start_move"].append(item.start_move)
                    out["streamed"].append(item.streamed)
                    out["action"].append(state.action if state else None)
                    out["start"].append(state.start if state else None)
                    out["began"].append(state.began if state else None)
                    out["end"].append(state.end if state else None)
                    out["withdrawn"].append(state.withdrawn if state else None)
                    for name, value in words.as_json().items():
                        out[f"w_{name}"].append(value if state else None)
                    out["above_feet"].append(band.low if band else None)
                    out["below_feet"].append(band.high if band else None)
    return pl.DataFrame(out, schema=ROW_DAY_SCHEMA)


ROW_DAY_SCHEMA: Final[dict[str, pl.DataType | type[pl.DataType]]] = {
    "school": pl.Int64,
    "day": pl.Date,
    "event": pl.String,
    "ugc": pl.String,
    "history": pl.Int8,
    "stream": pl.Int8,
    "start_move": pl.String,
    "streamed": pl.Boolean,
    "action": pl.String,
    "start": pl.Datetime("us", "UTC"),
    "began": pl.Datetime("us", "UTC"),
    "end": pl.Datetime("us", "UTC"),
    "withdrawn": pl.Boolean,
    **{f"w_{name}": pl.Boolean for name in Words().as_json()},
    "above_feet": pl.Int32,
    "below_feet": pl.Int32,
}
"""The columns of :func:`school_row_days` (parsed values only)."""


STATE_COLUMNS: Final = (
    "event", "ugc", "action", "start", "began", "end",
    *(f"w_{name}" for name in Words().as_json()), "above_feet", "below_feet",
)  # fmt: skip
"""The parsed state a district-day keeps from the event that reaches most of its schools."""


def district_row_days(
    frame: pl.DataFrame, district_of_school: pl.DataFrame, share: float
) -> pl.DataFrame:
    """Each (district, day) of :func:`school_row_days`: its class by the history and by the
    streams (the covered-share rule, :func:`district_day_classes`),
    the eligible schools a later product moved a start across the window's end for
    (``moved_later``, ``moved_earlier``), and the parsed state of the stream event of the
    district's stream class that reaches most of its schools (ties: the earliest start)."""
    classes = []
    for side in ("history", "stream"):
        per_school = frame.group_by("school", "day").agg(pl.col(side).max().alias("weather"))
        found = district_day_classes(per_school, district_of_school, share)
        classes.append(found.rename({"weather": side}))
    both = (
        classes[0]
        .join(classes[1], on=["district", "day"], how="full", coalesce=True)
        .with_columns(pl.col("history").fill_null(0), pl.col("stream").fill_null(0))
    )
    joined = frame.join(district_of_school, on="school", how="inner")
    moves = joined.group_by("district", "day").agg(
        pl.col("school").filter(pl.col("start_move") == "later").n_unique().alias("moved_later"),
        pl.col("school")
        .filter(pl.col("start_move") == "earlier")
        .n_unique()
        .alias("moved_earlier"),
        pl.col("school").filter(~pl.col("streamed")).n_unique().alias("unstreamed"),
    )
    top = (
        joined.join(both.select("district", "day", "stream"), on=["district", "day"])
        .filter((pl.col("stream") > 0) & (pl.col("stream") == pl.col("stream_right")))
        .group_by("district", "day", *STATE_COLUMNS)
        .agg(pl.col("school").n_unique().alias("schools"))
        .sort(["district", "day", "schools", "start"], descending=[False, False, True, False])
        .group_by("district", "day", maintain_order=True)
        .first()
    )
    return (
        both.join(moves, on=["district", "day"], how="full", coalesce=True)
        .join(top, on=["district", "day"], how="left")
        .with_columns(
            pl.col("history").fill_null(0).cast(pl.Int8),
            pl.col("stream").fill_null(0).cast(pl.Int8),
            pl.col("moved_later").fill_null(0).cast(pl.Int64),
            pl.col("moved_earlier").fill_null(0).cast(pl.Int64),
            pl.col("unstreamed").fill_null(0).cast(pl.Int64),
        )
        .sort("district", "day")
    )


def label_class_report(
    labels: pl.DataFrame,
    weather: pl.DataFrame,
    districts: pl.DataFrame,
    frame: pl.DataFrame,
    days: Sequence[date],
) -> dict[str, object]:
    """How the known labels' classes change when the alerts are read from the streams as of
    21:00 (rule D2) instead of the season files (plan T2), with two checks: the history side
    rebuilt here must equal the labels' own class (``weather``) and the weather history's
    (``weather.parquet``), else the comparison is void."""
    known = labels.filter(pl.col("outcome").is_in(["no_school", "delayed", "open"])).select(
        "district", "day", "season", "outcome", pl.col("weather").alias("labeled")
    )
    rows = (
        known.join(districts.select("district", "day", "history", "stream", "moved_later",
                                    "moved_earlier", "unstreamed"), on=["district", "day"],
                   how="left")
        .join(weather.rename({"weather": "kept"}), on=["district", "day"], how="left")
        .with_columns(
            pl.col("history").fill_null(0),
            pl.col("stream").fill_null(0),
            pl.col("kept").fill_null(0),
            pl.col("moved_later").fill_null(0),
            pl.col("moved_earlier").fill_null(0),
            pl.col("unstreamed").fill_null(0),
        )
    )  # fmt: skip
    parity_labels = int((rows["history"] != rows["labeled"]).sum())
    parity_history = int((rows["history"] != rows["kept"]).sum())
    changed = rows.filter(pl.col("history") != pl.col("stream"))
    pairs = {
        f"{WeatherClass(int(a)).label}->{WeatherClass(int(b)).label}": int(n)
        for a, b, n in changed.group_by("history", "stream")
        .len()
        .sort("history", "stream")
        .iter_rows()
    }
    by_season = {
        str(season): {"labels": int(total), "changed": int(moved)}
        for season, total, moved in rows.group_by("season")
        .agg(pl.len(), (pl.col("history") != pl.col("stream")).sum())
        .sort("season")
        .iter_rows()
    }
    by_outcome = {
        str(outcome): int(n)
        for outcome, n in changed.group_by("outcome").len().sort("outcome").iter_rows()
    }
    zone_moves = (
        frame.filter(pl.col("start_move").is_not_null())
        .select("event", "ugc", "day", "start_move")
        .unique()
    )
    all_days = districts.filter(pl.col("day").is_in(list(days)))
    summary = {
        "label_rows": rows.height,
        "label_dates": len(set(days)),
        "history_vs_label_class_mismatch": parity_labels,
        "history_vs_weather_history_mismatch": parity_history,
        "labels_changed": changed.height,
        "labels_changed_share": round(changed.height / rows.height, 6) if rows.height else 0.0,
        "zone_days_start_moved_later": int((zone_moves["start_move"] == "later").sum()),
        "zone_days_start_moved_earlier": int((zone_moves["start_move"] == "earlier").sum()),
        "labels_with_a_later_move": int((rows["moved_later"] > 0).sum()),
        "labels_with_an_earlier_move": int((rows["moved_earlier"] > 0).sum()),
        "labels_with_an_event_not_fetched": int((rows["unstreamed"] > 0).sum()),
        "district_days_changed_all": int((all_days["history"] != all_days["stream"]).sum()),
        "district_days_all": all_days.height,
    }
    return {
        "summary": summary,
        "pairs": pairs,
        "by_season": by_season,
        "changed_by_outcome": by_outcome,
    }
