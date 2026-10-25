"""What each district did on past school days, from the archived closing lists (spec a).

Unit: a district-day ``(d, D)``, ``D`` a school day (:mod:`snowlight.predict.calendar`)
outside the pandemic closures. The lists are matched and read with the landed matcher
and status reader through the replay builder's steps (:func:`match_archive` once, then
:func:`settle_day` per day); the replay day bar and the D+7 control are not used: they
gate display, not labels.

* **Eligible schools** of ``d``: its public schools in the directory, less charters and
  fully virtual schools (the ``points.bin`` kind flags).
* **Lit on D**: :func:`settle_day` gives the school a status dated for D, from any read
  whose window covers D (evening-before lists count).
* **Weather positive**: closed, remote or delayed, for a winter storm, ice, extreme cold,
  a hurricane, flooding or severe storms; or with no reason named on a day the district's
  weather class is not ``none``. Heat, a power outage, any other cause, and a closing
  with no reason on a clear day are unknown: never positive, never open.
* **Audience** of station ``s``: the districts it listed (any school or the district row,
  any status) on at least ``audience_days`` distinct local days; ``s`` carries ``d`` on D
  only from the first day it listed ``d`` (a list never shows a district open before it is
  known to carry it).
* **Read on D**: a station that carries ``d`` on D has a populated or empty
  read fetched in [``read_from``, ``read_until``) local on D, in ``d``'s zone, that can
  show the district. Deferred and count-only reads never count, nor do:

  - a populated read the replay step (:func:`~snowlight.replays.build.settle_day`)
    dropped (``dropped_read``: unreadable, or too few rows matched): nothing in it lit,
    so it shows no one open;
  - a populated read of a station with fewer than ``station_min_captures`` populated
    captures in the archive (``thin_station``: too few lists to tell a whole one from a
    partial one; its empty reads still count, under the rules below);
  - on a day whose class is above ``none``, a populated read with fewer than
    ``capture_min_share`` of the station's median populated rows (``small_capture``: a
    partial list);
  - an empty read while another station of its market holds ``market_rows_void`` or more
    rows in a read of the same window (``voided_empty``: a list cleared early or idle);
  - on a day whose class is above ``none``, empty reads alone, unless another station of
    the market also read in the window (``empty_uncorroborated``).

  A district a list names that day in a row the replay step did not light (a status it
  could not date or read, a conflict, a withdrawn claim, a row it read as naming one school;
  not a row about another day or one that says school is open) is not absent from the list:
  it is never ``open`` or ``delayed`` (``listed_unread``).

  On a day whose class is above ``none``, a district that is open only by being absent
  from the lists while at least ``storm_absence_share`` of the other labeled districts of
  its market had no school is unknown (``absent_in_storm``, :func:`storm_absences`): the
  audit found such districts closed in fact, left off a full list.

  On a :func:`~snowlight.predict.calendar.likely_break` day no district is read
  (``break``): a quiet list then says nothing about the weather.
* **Outcome**, for a district read on D: ``no_school`` when at least ``no_school_share``
  of the eligible schools are lit closed or remote (weather positive); else ``delayed``
  when at least ``delayed_share`` are lit delayed (weather positive); else ``open`` when
  at most ``open_max_share`` are lit with any status; else ``unknown``. A district not
  read on D is unknown and has no row, lit or not: a closing seen only on an evening
  list, with no morning read of the district, is not labeled, because an open day is
  only ever labeled from a morning read, and labeling closings from more captures than
  open days would count closings the archive happened to catch and miss the open days it
  did not (a closing an evening list lights still counts on a day the district is read).
  Unknown rows are dropped from training and scoring, never counted as open.
* **Day after**: the district's previous school day was ``no_school``.
"""

import json
import statistics
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Final
from zoneinfo import ZoneInfo

import polars as pl

from snowlight.predict.calendar import likely_break, previous_school_day, season_of
from snowlight.predict.config import LabelSettings
from snowlight.predict.situations import WeatherClass
from snowlight.schemas.vocab import Reason, Status

WEATHER_REASONS: Final = frozenset(
    {
        Reason.WINTER_STORM,
        Reason.ICE,
        Reason.EXTREME_COLD,
        Reason.HURRICANE,
        Reason.FLOODING,
        Reason.SEVERE_STORMS,
    }
)
"""The reasons a weather closing names; heat and a power outage are not weather here."""
NO_SCHOOL: Final = frozenset({Status.CLOSED, Status.REMOTE})
COUNTED_STATES: Final = frozenset({"populated", "empty"})
"""Read states that can show a district was read (deferred and count-only never do)."""


class Outcome(StrEnum):
    """What a district did on a school day."""

    NO_SCHOOL = "no_school"
    DELAYED = "delayed"
    OPEN = "open"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ReadRecord:
    """One capture of a station's list: when, whether it held rows, and how many."""

    source_id: str
    fetched_at: datetime
    state: str
    rows: int


def parse_reads(lines: Iterable[str]) -> list[ReadRecord]:
    """The reads of a ``reads.jsonl`` file (blank lines skipped).

    Raises:
        ValueError: a line is not a read.
    """
    found: list[ReadRecord] = []
    for line in lines:
        if not line.strip():
            continue
        item = json.loads(line)
        found.append(
            ReadRecord(
                source_id=str(item["source_id"]),
                fetched_at=datetime.fromisoformat(str(item["fetched_at"])).astimezone(UTC),
                state=str(item["state"]),
                rows=int(item.get("rows") or 0),
            )
        )
    return found


@dataclass(frozen=True, slots=True)
class LitStatus:
    """A school's settled status for the day, and the reason named."""

    status: Status
    reason: Reason | None


def weather_positive(lit: LitStatus, weather: WeatherClass) -> bool:
    """Whether a lit status is a weather closing, remote day or delay (see the module
    docstring)."""
    if lit.status not in (*NO_SCHOOL, Status.DELAYED):
        return False
    if lit.reason is None:
        return weather is not WeatherClass.NONE
    return lit.reason in WEATHER_REASONS


@dataclass(frozen=True, slots=True)
class Shares:
    """The shares of a district's eligible schools lit each way."""

    no_school: float
    delayed: float
    any_status: float
    remote: float = 0.0
    """Of ``no_school``, the share lit remote."""


def shares(eligible: Sequence[str], lit: Mapping[str, LitStatus], weather: WeatherClass) -> Shares:
    """How much of ``eligible`` is lit no school, delayed (weather positive) and at all."""
    if not eligible:
        return Shares(0.0, 0.0, 0.0)
    closed = delayed = shown = remote = 0
    for school in eligible:
        found = lit.get(school)
        if found is None:
            continue
        shown += 1
        if weather_positive(found, weather):
            if found.status in NO_SCHOOL:
                closed += 1
                remote += found.status is Status.REMOTE
            else:
                delayed += 1
    total = len(eligible)
    return Shares(closed / total, delayed / total, shown / total, remote / total)


def _unknown_why(outcome: Outcome) -> str | None:
    """Why a row is unknown: read with more than the open share lit but under the closing
    and delay shares (``partly_lit``)."""
    return "partly_lit" if outcome is Outcome.UNKNOWN else None


def did_of(outcome: Outcome, found: Shares) -> str | None:
    """What the district did, for its record: ``closed`` or ``remote`` (whichever more of
    its schools were lit, closed on a tie), ``delayed``, ``open``, or ``None`` (unknown)."""
    if outcome is Outcome.NO_SCHOOL:
        return "remote" if found.remote > found.no_school - found.remote else "closed"
    if outcome is Outcome.DELAYED:
        return "delayed"
    if outcome is Outcome.OPEN:
        return "open"
    return None


def outcome_of(found: Shares, read: bool, settings: LabelSettings) -> Outcome:
    """The district's outcome from its shares and whether it was read on the day."""
    if found.no_school >= settings.no_school_share:
        return Outcome.NO_SCHOOL
    if found.delayed >= settings.delayed_share:
        return Outcome.DELAYED
    if read and found.any_status <= settings.open_max_share:
        return Outcome.OPEN
    return Outcome.UNKNOWN


type Audience = Mapping[str, Mapping[str, date]]
"""Station to each district it carries and the first local day it listed it."""


def audiences(
    listings: Iterable[tuple[str, str, date]], min_days: int
) -> dict[str, dict[str, date]]:
    """Each station's audience: the districts it listed on at least ``min_days`` local days,
    each with the first day it listed it. A station reads a district on a day only from that
    first day on (:func:`carries`): a list never shows a district open before it is known to
    carry it.

    ``listings`` gives (station, district, local day) for every listing of a district or one
    of its schools.
    """
    days: dict[tuple[str, str], set[date]] = defaultdict(set)
    for station, district, day in listings:
        days[(station, district)].add(day)
    found: dict[str, dict[str, date]] = defaultdict(dict)
    for (station, district), seen in sorted(days.items()):
        if len(seen) >= min_days:
            found[station][district] = min(seen)
    return {
        station: dict(sorted(districts.items())) for station, districts in sorted(found.items())
    }


def carries(audience: Audience, station: str, day: date) -> list[str]:
    """The districts ``station`` is known to carry on ``day``: listed on enough days, the
    first of them on or before ``day``."""
    return [district for district, first in audience.get(station, {}).items() if first <= day]


def _in_read_window(moment: datetime, day: date, zone: str, settings: LabelSettings) -> bool:
    tz = ZoneInfo(zone)
    start = datetime.combine(day, settings.read_from, tzinfo=tz)
    end = datetime.combine(day, settings.read_until, tzinfo=tz)
    return start <= moment < end


class Unread(StrEnum):
    """Why a district an audience station read is still unknown (see the module docstring)."""

    LISTED_UNREAD = "listed_unread"
    DROPPED_READ = "dropped_read"
    THIN_STATION = "thin_station"
    SMALL_CAPTURE = "small_capture"
    VOIDED_EMPTY = "voided_empty"
    EMPTY_UNCORROBORATED = "empty_uncorroborated"
    BREAK = "break"
    ABSENT_IN_STORM = "absent_in_storm"


@dataclass(frozen=True, slots=True)
class StationRead:
    """What one station's reads in a window can show: its kept populated reads' rows, and
    whether it has an empty read that counts."""

    populated: tuple[int, ...] = ()
    empty: bool = False
    refused: tuple[Unread, ...] = ()
    """Why each of its other reads in the window does not count."""


def _first(why: Sequence[Unread]) -> Unread | None:
    """The first reason in the enum's order (``dropped_read`` before the rest)."""
    order = list(Unread)
    return min(why, key=order.index) if why else None


type Kept = frozenset[tuple[str, datetime]]
"""The populated reads the replay step kept for the day: (station, fetched at)."""


def window_reads(  # noqa: PLR0913 - the day, its zone, the reads and their gates
    day: date,
    zone: str,
    reads: Sequence[ReadRecord],
    market_of: Mapping[str, str],
    settings: LabelSettings,
    *,
    kept: Kept | None = None,
) -> dict[str, StationRead]:
    """Each station's reads in ``zone``'s read window on ``day``, after the read gates that do
    not depend on the district: a populated read the replay step dropped (not in ``kept``;
    ``None`` keeps every one) and an empty read voided by a busy market peer."""
    window = [
        read
        for read in reads
        if read.state in COUNTED_STATES and _in_read_window(read.fetched_at, day, zone, settings)
    ]
    busy: dict[str, set[str]] = defaultdict(set)
    for read in window:
        if (
            read.state == "populated"
            and read.rows >= settings.market_rows_void
            and (kept is None or (read.source_id, read.fetched_at) in kept)
        ):
            busy[market_of.get(read.source_id, read.source_id)].add(read.source_id)
    populated: dict[str, list[int]] = defaultdict(list)
    empty: dict[str, bool] = defaultdict(bool)
    refused: dict[str, list[Unread]] = defaultdict(list)
    for read in window:
        station = read.source_id
        if read.state == "populated":
            if kept is not None and (station, read.fetched_at) not in kept:
                refused[station].append(Unread.DROPPED_READ)
            else:
                populated[station].append(read.rows)
            continue
        market = market_of.get(station, station)
        if busy.get(market, set()) - {station}:
            refused[station].append(Unread.VOIDED_EMPTY)
        else:
            empty[station] = True
    stations = sorted({read.source_id for read in window})
    return {
        station: StationRead(
            tuple(populated.get(station, ())),
            empty.get(station, False),
            tuple(refused.get(station, ())),
        )
        for station in stations
    }


def read_stations(  # noqa: PLR0913 - the day, its zone, the reads and their gates
    day: date,
    zone: str,
    reads: Sequence[ReadRecord],
    market_of: Mapping[str, str],
    settings: LabelSettings,
    *,
    kept: Kept | None = None,
) -> frozenset[str]:
    """The stations with a read that counts in ``zone``'s window on ``day`` before the
    district's own gates (:func:`window_reads`)."""
    found = window_reads(day, zone, reads, market_of, settings, kept=kept)
    return frozenset(name for name, item in found.items() if item.populated or item.empty)


def station_reads(  # noqa: PLR0913 - one station's reads and the district's gates
    station: str,
    item: StationRead,
    storm: bool,
    *,
    captures: Mapping[str, int] | None,
    median_rows: Mapping[str, float] | None,
    settings: LabelSettings,
) -> tuple[str | None, Unread | None]:
    """What one station's reads show of a district: ``populated``, ``empty`` or ``None``,
    and why not when ``None``. ``storm``: the district's class that day is above ``none``.
    ``None`` maps leave the station gates out."""
    rows = item.populated
    thin = captures is not None and captures.get(station, 0) < settings.station_min_captures
    if thin:
        rows = ()
    elif storm and rows and median_rows is not None:
        least = settings.capture_min_share * median_rows.get(station, 0.0)
        rows = tuple(count for count in rows if count >= least)
    if not rows and not item.empty and item.populated:
        return None, Unread.THIN_STATION if thin else Unread.SMALL_CAPTURE
    if rows:
        return "populated", None
    if item.empty:
        return "empty", None
    return None, item.refused[0] if item.refused else Unread.DROPPED_READ


@dataclass(frozen=True, slots=True)
class LabelInputs:
    """What labeling every day needs, from the archive and the directory."""

    eligible: Mapping[str, tuple[str, ...]]
    """District LEAID to its eligible schools' NCES ids."""
    zone_of: Mapping[str, str]
    """District LEAID to its IANA zone."""
    audience: Audience
    """Station to the districts it carries and since when (:func:`audiences`)."""
    reads: Sequence[ReadRecord]
    market_of: Mapping[str, str]
    """Station to its market."""
    weather: Mapping[tuple[str, date], WeatherClass]
    """(district, day) to the class above ``none`` (absent: ``none``)."""
    district_of: Mapping[str, str]
    """Eligible school NCES id to its district LEAID."""
    captures: Mapping[str, int] | None = None
    """Station to its populated captures in the archive (``None``: no station gate)."""
    median_rows: Mapping[str, float] | None = None
    """Station to the median rows of its populated captures (``None``: no size gate)."""


@dataclass(frozen=True, slots=True)
class DayLit:
    """What the replay step settled for a day: the statuses by NCES school id, the
    populated reads it kept (``None``: every one), and the districts a list named that day
    in a row the step did not light (``listed``: not absent, so never open)."""

    lit: Mapping[str, LitStatus]
    kept: Kept | None = None
    listed: frozenset[str] = frozenset()


type LitFor = Callable[[date], DayLit]
"""What the replay step settled for a day."""


def station_stats(reads: Iterable[ReadRecord]) -> tuple[dict[str, int], dict[str, float]]:
    """Each station's populated captures and their median rows, over the whole archive."""
    rows: dict[str, list[int]] = defaultdict(list)
    for read in reads:
        if read.state == "populated":
            rows[read.source_id].append(read.rows)
    counts = {station: len(found) for station, found in sorted(rows.items())}
    medians = {station: float(statistics.median(found)) for station, found in sorted(rows.items())}
    return counts, medians


def _reads_near(reads: Sequence[ReadRecord], day: date) -> list[ReadRecord]:
    start = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    end = start + timedelta(days=1, hours=12)
    return [read for read in reads if start <= read.fetched_at < end]


def _district_unread(  # noqa: PLR0913, PLR0917 - the district's readers and the day's reads
    stations: Sequence[str],
    window: Mapping[str, StationRead],
    readers_of_market: Mapping[str, set[str]],
    storm: bool,
    inputs: LabelInputs,
    settings: LabelSettings,
) -> tuple[int, Unread | None]:
    """How many of ``stations`` read the district (see the module docstring), and why it is
    unread when none did."""
    return district_readers(
        stations,
        window,
        readers_of_market,
        storm,
        market_of=inputs.market_of,
        captures=inputs.captures,
        median_rows=inputs.median_rows,
        settings=settings,
    )


def district_readers(  # noqa: PLR0913 - the district's readers, the day's reads and the gates
    stations: Sequence[str],
    window: Mapping[str, StationRead],
    readers_of_market: Mapping[str, set[str]],
    storm: bool,
    *,
    market_of: Mapping[str, str],
    captures: Mapping[str, int] | None,
    median_rows: Mapping[str, float] | None,
    settings: LabelSettings,
) -> tuple[int, Unread | None]:
    """How many of ``stations`` (those carrying the district that have reads in ``window``)
    read it, after the station gates (``thin_station``, ``small_capture``) and, on a storm
    day, ``empty_uncorroborated``; and why it is unread when none did. The live labels use
    it too (:mod:`snowlight.predict.live_labels`), so both follow one rule."""
    readers = 0
    why: list[Unread] = []
    for station in stations:
        item = window.get(station)
        if item is None:
            continue
        kind, reason = station_reads(
            station,
            item,
            storm,
            captures=captures,
            median_rows=median_rows,
            settings=settings,
        )
        market = market_of.get(station, station)
        if kind == "empty" and storm and not readers_of_market.get(market, set()) - {station}:
            why.append(Unread.EMPTY_UNCORROBORATED)
        elif kind is not None:
            readers += 1
        elif reason is not None:
            why.append(reason)
    return readers, None if readers else _first(why)


def label_day(
    day: date,
    inputs: LabelInputs,
    lit: Mapping[str, LitStatus] | DayLit,
    settings: LabelSettings,
) -> list[dict[str, object]]:
    """The labeled districts of one day: every district an audience station read that day
    (see the module docstring); one a station read whose reads cannot show it is unknown,
    with why."""
    settled = lit if isinstance(lit, DayLit) else DayLit(lit)
    reads = _reads_near(inputs.reads, day)
    season = season_of(day)
    pause = likely_break(day)
    rows: list[dict[str, object]] = []
    for zone in sorted(set(inputs.zone_of.values())):
        window = window_reads(day, zone, reads, inputs.market_of, settings, kept=settled.kept)
        listened: dict[str, list[str]] = defaultdict(list)
        readers_of_market: dict[str, set[str]] = defaultdict(set)
        for station, item in window.items():
            if item.populated or item.empty:
                readers_of_market[inputs.market_of.get(station, station)].add(station)
            for district in carries(inputs.audience, station, day):
                if inputs.zone_of.get(district) == zone:
                    listened[district].append(station)
        for district in sorted(listened):
            eligible = inputs.eligible.get(district, ())
            if not eligible:
                continue
            weather = inputs.weather.get((district, day), WeatherClass.NONE)
            readers, unread = _district_unread(
                listened[district],
                window,
                readers_of_market,
                weather is not WeatherClass.NONE,
                inputs,
                settings,
            )
            if pause:
                readers, unread = 0, Unread.BREAK
            found = shares(eligible, settled.lit, weather)
            outcome = (
                Outcome.UNKNOWN
                if unread is not None
                else outcome_of(found, read=readers > 0, settings=settings)
            )
            if outcome in (Outcome.OPEN, Outcome.DELAYED) and district in settled.listed:
                outcome, unread = Outcome.UNKNOWN, Unread.LISTED_UNREAD
            rows.append(
                {
                    "district": district,
                    "day": day,
                    "season": season,
                    "outcome": outcome.value,
                    "did": did_of(outcome, found),
                    "unknown_why": unread.value if unread is not None else _unknown_why(outcome),
                    "readers": readers,
                    "no_school_share": round(found.no_school, 4),
                    "delayed_share": round(found.delayed, 4),
                    "lit_share": round(found.any_status, 4),
                    "weather": int(weather),
                }
            )
    rows.sort(key=lambda row: str(row["district"]))
    return rows


LABEL_SCHEMA: Final = {
    "district": pl.String,
    "day": pl.Date,
    "season": pl.Int32,
    "outcome": pl.String,
    "did": pl.String,
    "unknown_why": pl.String,
    "readers": pl.Int32,
    "no_school_share": pl.Float64,
    "delayed_share": pl.Float64,
    "lit_share": pl.Float64,
    "weather": pl.Int8,
}


def with_day_after(labels: pl.DataFrame) -> pl.DataFrame:
    """``labels`` with ``after``: the district's previous school day was ``no_school``."""
    closed = labels.filter(pl.col("outcome") == Outcome.NO_SCHOOL.value).select(
        "district", pl.col("day").alias("closed_day")
    )
    days = labels.select(pl.col("day").unique())
    previous = days.with_columns(
        pl.col("day").map_elements(previous_school_day, return_dtype=pl.Date).alias("closed_day")
    )
    joined = labels.join(previous, on="day", how="left").join(
        closed.with_columns(pl.lit(value=True).alias("after")),
        on=["district", "closed_day"],
        how="left",
    )
    return joined.with_columns(pl.col("after").fill_null(value=False)).drop("closed_day")


def label_days(
    days: Iterable[date], inputs: LabelInputs, lit_for: LitFor, settings: LabelSettings
) -> pl.DataFrame:
    """Every labeled district-day of ``days`` (excluded days skipped), with the day after."""
    rows: list[dict[str, object]] = []
    for day in days:
        if settings.excluded_from <= day <= settings.excluded_until:
            continue
        rows.extend(label_day(day, inputs, lit_for(day), settings))
    frame = pl.DataFrame(rows, schema=LABEL_SCHEMA)
    return with_day_after(frame).sort("district", "day")


def storm_absences(labels: pl.DataFrame, share: float) -> pl.DataFrame:
    """``labels`` (with ``cluster``, the district's market) with every storm-day ``open`` that
    rests on absence alone made unknown where at least ``share`` of the other known districts
    of its market that day had no school (see the module docstring)."""
    known = labels.filter(pl.col("outcome") != Outcome.UNKNOWN.value)
    groups = known.group_by("day", "cluster").agg(
        pl.len().alias("known"),
        (pl.col("outcome") == Outcome.NO_SCHOOL.value).sum().alias("closed"),
    )
    joined = labels.join(groups, on=["day", "cluster"], how="left")
    others = pl.col("known").fill_null(0) - 1
    peer_share = pl.when(others > 0).then(pl.col("closed").fill_null(0) / others).otherwise(0.0)
    absent = (
        (pl.col("outcome") == Outcome.OPEN.value)
        & (pl.col("weather") > 0)
        & (pl.col("lit_share") == 0.0)
        & (peer_share >= share)
    )
    return joined.with_columns(
        pl.when(absent)
        .then(pl.lit(Outcome.UNKNOWN.value))
        .otherwise(pl.col("outcome"))
        .alias("outcome"),
        pl.when(absent).then(None).otherwise(pl.col("did")).alias("did"),
        pl.when(absent)
        .then(pl.lit(Unread.ABSENT_IN_STORM.value))
        .otherwise(pl.col("unknown_why"))
        .alias("unknown_why"),
        pl.when(absent).then(0).otherwise(pl.col("readers")).cast(pl.Int32).alias("readers"),
    ).drop("known", "closed")


def district_markets(
    listings: Iterable[tuple[str, str, date]], market_of: Mapping[str, str]
) -> dict[str, str]:
    """Each listed district's market: the market of the stations that listed it on the most
    days (ties to the smallest name). Storm days cluster by it (spec c.3)."""
    days: dict[str, dict[str, set[date]]] = defaultdict(lambda: defaultdict(set))
    for station, district, day in listings:
        days[district][market_of.get(station, station)].add(day)
    found: dict[str, str] = {}
    for district, markets in days.items():
        top = max(len(seen) for seen in markets.values())
        found[district] = min(market for market, seen in markets.items() if len(seen) == top)
    return found


# --- the label audit (calc-research plan T1) -----------------------------------------------------

KNOWN_OUTCOMES: Final = frozenset(
    {Outcome.NO_SCHOOL.value, Outcome.DELAYED.value, Outcome.OPEN.value}
)
"""The outcomes a fit trains on (an unknown row is dropped)."""
NO_ROW: Final = "no_row"
"""A district-day one build labels and the other has no row for."""


def listings_before(
    listings: Iterable[tuple[str, str, date]], before: date
) -> list[tuple[str, str, date]]:
    """The listings of local days before ``before``: what a station's audience could have been
    built from at the start of a fold whose test season begins on ``before``."""
    return [item for item in listings if item[2] < before]


def reads_before(reads: Iterable[ReadRecord], before: date) -> list[ReadRecord]:
    """The reads fetched before midnight UTC starting ``before`` (a season starts in July, when
    no school day is near the edge)."""
    edge = datetime.combine(before, datetime.min.time(), tzinfo=UTC)
    return [read for read in reads if read.fetched_at < edge]


@dataclass(frozen=True, slots=True)
class LabelChanges:
    """How the known labels of a fold's training seasons change when the station audiences,
    the station gates and the markets are rebuilt from those seasons only (``fold``) instead
    of from the whole archive (``whole``)."""

    training: int
    """Known labels of the training seasons in the whole-archive build."""
    changed: int
    """Of those, the ones the fold's build labels another way or not at all."""
    added: int
    """Known labels the fold's build has that the whole-archive build does not."""
    pairs: Mapping[tuple[str, str], int]
    """(whole, fold) outcome to the rows that moved so (``no_row``: no row)."""

    @property
    def share(self) -> float:
        """The changed and added labels over the training labels (0 with none)."""
        return (self.changed + self.added) / self.training if self.training else 0.0


def label_changes(whole: pl.DataFrame, fold: pl.DataFrame) -> LabelChanges:
    """Compare two label builds of the same days (``district``, ``day``, ``outcome``).

    A row whose outcome is unknown, or that is missing, is not a training label; a known row
    that becomes unknown, missing or another outcome is ``changed``, and an unknown or missing
    row that becomes known is ``added``."""
    left = whole.select("district", "day", pl.col("outcome").alias("whole"))
    right = fold.select("district", "day", pl.col("outcome").alias("fold"))
    joined = left.join(right, on=["district", "day"], how="full", coalesce=True).with_columns(
        pl.col("whole").fill_null(NO_ROW), pl.col("fold").fill_null(NO_ROW)
    )
    known = sorted(KNOWN_OUTCOMES)
    training = int(joined["whole"].is_in(known).sum())
    moved = joined.filter(pl.col("whole") != pl.col("fold"))
    pairs: dict[tuple[str, str], int] = {}
    changed = added = 0
    for was, now, count in moved.group_by("whole", "fold").len().sort("whole", "fold").iter_rows():
        if was not in KNOWN_OUTCOMES and now not in KNOWN_OUTCOMES:
            continue
        pairs[(str(was), str(now))] = int(count)
        if was in KNOWN_OUTCOMES:
            changed += int(count)
        else:
            added += int(count)
    return LabelChanges(training, changed, added, pairs)


def fold_label_days(  # noqa: PLR0913, PLR0917 - the days, the inputs, the listings and the fold
    days: Iterable[date],
    inputs: LabelInputs,
    listings: Sequence[tuple[str, str, date]],
    lit_for: LitFor,
    settings: LabelSettings,
    before: date | None = None,
) -> tuple[pl.DataFrame, dict[str, str]]:
    """Label ``days`` with the station audiences (:func:`audiences` of ``listings``), the
    station gates (:func:`station_stats` of ``inputs.reads``) and the districts' markets
    (:func:`district_markets`) built here, and return the labels and the markets.

    ``before``: the start of a walk-forward fold's test season. Then only the days before it
    are labeled, and the audiences, the gates and the markets are built from the listings
    and reads before it only, so a fold's training labels never depend on a later season
    (calc-research plan T1, the lead's per-fold rule of 2026-10-25). A day's own reads
    (fetched up to noon the day after it) still read it."""
    reads: Sequence[ReadRecord] = inputs.reads
    if before is not None:
        listings = listings_before(listings, before)
        reads = reads_before(reads, before)
        days = [day for day in days if day < before]
    captures, median_rows = station_stats(reads)
    mine = replace(
        inputs,
        audience=audiences(listings, settings.audience_days),
        captures=captures,
        median_rows=median_rows,
    )
    return label_days(days, mine, lit_for, settings), district_markets(listings, inputs.market_of)
