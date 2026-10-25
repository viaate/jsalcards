"""Labels from the days the live pipeline read (S7-L, spec addenda c and d).

A live-read district-day becomes a label by the archive's rules
(:mod:`snowlight.predict.labels`: the same shares and outcomes, the same read gates, the same
``listed_unread``, ``absent_in_storm`` and day-after rules), from three inputs, none of them
raw text:

* **What the map showed**: the live host's public day timeline of the day
  (``live/days/<day>.json``, S8-D), final only (the day is over everywhere), built from the
  directory content the deployed directory has (its school indexes are read against it). A
  status the emergency stop darkened is already left out of the timeline, and a day the stop
  held dark labels nothing. A school whose last change took its status back (a retraction, or
  a status the gate withheld) leaves its district unknown that day (``retracted``). The host
  holding no timeline for a day is read as "no school showed a status" only once the host's
  day index, written after the day was over everywhere, does not list the day.
* **What the lists said that morning**: the live ingest's morning record
  (:mod:`snowlight.live.morning`, read only from its private state) and its change log.

  - A source **carries** a district when it lit a school of it on ``audience_days`` or more
    live days up to D, from the first of them on (the archive's audience rule). A district
    site's rows never light in the live pipeline, so a district's own channel carries nothing
    here: its silence cannot be told from a list the map never shows.
  - A district is **read** on D when a carrying source has a whole read (the ledger took it
    ``ok``, ``not_modified`` or ``empty``; a read that lost half its rows is ``partial`` and
    never recorded) in a 30-minute slot wholly inside the settled window [``read_from``,
    ``read_until``) local on D in the district's zone, where every pass of the slot that read
    was shown on the map under the prefix this step reads, and no pass of the slot withheld
    the district's state whole (a source whose say was unknown). The read then passes the
    archive's gates: a populated read with over a quarter of its rows read as no status, or
    under half its source's median share of rows placed, never counts (``dropped_read``); nor
    does a populated read of a source with fewer than ``station_min_captures`` populated reads
    (``thin_station``), or on a storm day one under ``capture_min_share`` of its source's
    median rows (``small_capture``); an empty read is void while another source of its market
    holds ``market_rows_void`` rows in the window (``voided_empty``), and on a storm day empty
    reads alone count only when another source of the market read too
    (``empty_uncorroborated``). The counts and medians are the record's (it keeps 10 days).
  - A district a present row of any list named for D, or for every day (a withheld,
    undated or dissenting row), from the day before through the end of its window, is never
    ``open`` (``listed_unread``; stricter than the archive, which lets a district any of
    whose schools lit be open). It is ``delayed`` only when every status kind a list named it
    with is one the map showed on one of its schools that day: a district the map lit
    delayed, named only by its own lit delay rows, is delayed; one a row also named closed
    (or remote, or an early dismissal) that the map never showed on it, or that a dissenting,
    unsure or unread row named, is ``listed_unread``. Whatever the live guards kept off the
    map (a conflict, a weak or unworded reading, a tripped breaker, a spike hold, a refused
    or failed publish) was named by such a row, so a district a list named is never read as
    open, or as only delayed, because the map was dark.
  - A day is labeled only once its record reads (a damaged one never does) and reaches past
    the read window of every deployed zone (a state restored from before then labels nothing,
    and the day waits). A zone's reads count only when the day's own record holds a pass
    (shown or not) in the last slot of the zone's window: a record that stops partway
    through the window (an ingest outage, passes that fail before they are recorded) leaves
    every district of the zone ``not_read``, never open on its early reads.
* **The weather class** of the district-day, as the serving pass computed it at the training
  snapshot (21:00 the evening before, local): every pass records each district's class for
  the days it serves until that district's snapshot time (:func:`record_snapshots`). A class
  taken more than ``snapshot_slack_minutes`` before the snapshot (the passes stopped), or not
  taken at all, leaves the district-day unknown.

Every rule here can only make a district-day unknown. As in the archive, a row the matcher
could not place on a school names no district: a district only such a row named is read by
the rest of its list.
"""

import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final, Protocol
from zoneinfo import ZoneInfo

import numpy as np
import numpy.typing as npt
import polars as pl

from snowlight.live.history import BY, BY_HOLD, ChangeLog, Event, is_final
from snowlight.live.morning import (
    EVERY_DAY,
    SLOT_MINUTES,
    MorningDay,
    MorningLog,
    Read,
    Slot,
    slot_start,
)
from snowlight.predict.calendar import is_school_day, likely_break, season_of
from snowlight.predict.config import LabelSettings
from snowlight.predict.geography import state_of_leaid
from snowlight.predict.labels import (
    LABEL_SCHEMA,
    LitStatus,
    Outcome,
    StationRead,
    Unread,
    audiences,
    carries,
    did_of,
    district_readers,
    outcome_of,
    shares,
    storm_absences,
    with_day_after,
)
from snowlight.predict.situations import WeatherClass, Window
from snowlight.replays.gates import UNREADABLE_SHARE, low_match, station_median
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.live import DayIndex, DayTimeline
from snowlight.schemas.vocab import STATUS_BY_KIND

UNKNOWN_CLASS: Final = "-"
"""A district whose class was not taken for the day, in a snapshot's class string."""
NCES_SCHOOL_DIGITS: Final = 12
LEAID_DIGITS: Final = 7
SNAPSHOT_KEEP_DAYS: Final = 10


class LiveWhy:
    """Why a live-read district-day is unknown (beyond the archive's ``partly_lit`` and
    ``absent_in_storm``)."""

    BREAK: Final = "break"
    NOT_READ: Final = "not_read"
    """No source that carries it had a whole read in its window, in a slot shown under this
    prefix with its state not withheld whole, or the day's record holds no pass in the last
    slot of the window."""
    NO_WEATHER: Final = "no_weather"
    RETRACTED: Final = "retracted"


# --- the weather class at the snapshot ---------------------------------------------------------


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def record_snapshots(  # noqa: PLR0913 - the record, the pass's classes and when
    snapshots: Mapping[str, object],
    *,
    content: str,
    zones: Sequence[str],
    classes: npt.NDArray[np.int64],
    days: Sequence[date],
    now: datetime,
    window: Window,
) -> dict[str, object]:
    """The snapshot record with this pass's classes taken in: for each school day of ``days``
    and each zone whose snapshot time (21:00 the evening before) has not passed, every
    district of that zone gets its class now, and the zone its time taken. ``classes`` is
    (districts, days); ``zones`` each deployed district's zone; ``content`` names the
    directory content the district positions belong to (a record of another restarts).
    Days more than :data:`SNAPSHOT_KEEP_DAYS` before ``now`` are dropped."""
    found: dict[str, object] = {}
    oldest = now.astimezone(UTC).date() - timedelta(days=SNAPSHOT_KEEP_DAYS)
    for key, value in snapshots.items():
        try:
            if date.fromisoformat(key) >= oldest and isinstance(value, dict):
                found[key] = value
        except ValueError:
            continue
    size = len(zones)
    by_zone: dict[str, list[int]] = defaultdict(list)
    for index, zone in enumerate(zones):
        by_zone[zone].append(index)
    for d, day in enumerate(days):
        if not is_school_day(day):
            continue
        key = day.isoformat()
        kept = found.get(key)
        entry: dict[str, object] = (
            kept
            if isinstance(kept, dict)
            and kept.get("content") == content
            and len(str(kept.get("classes", ""))) == size
            else {"content": content, "classes": UNKNOWN_CLASS * size, "taken": {}}
        )
        chars = list(str(entry["classes"]))
        before = entry.get("taken")
        taken: dict[str, object] = dict(before) if isinstance(before, dict) else {}
        for zone, members in sorted(by_zone.items()):
            if now > window.snapshot(day, zone):
                continue
            for index in members:
                chars[index] = str(int(classes[index, d]))
            taken[zone] = _iso(now)
        found[key] = {"content": content, "classes": "".join(chars), "taken": taken}
    return dict(sorted(found.items()))


def snapshot_classes(  # noqa: PLR0913 - the record, the day, the districts and the rule
    snapshots: Mapping[str, object],
    day: date,
    *,
    content: str,
    zones: Sequence[str],
    window: Window,
    slack: timedelta,
) -> list[WeatherClass | None]:
    """Each deployed district's class for ``day`` at its snapshot, or ``None``: not taken, taken
    for another directory content, or last taken more than ``slack`` before the snapshot."""
    entry = snapshots.get(day.isoformat())
    if not isinstance(entry, dict) or entry.get("content") != content:
        return [None] * len(zones)
    chars = str(entry.get("classes", ""))
    taken = entry.get("taken")
    if len(chars) != len(zones) or not isinstance(taken, dict):
        return [None] * len(zones)
    found: list[WeatherClass | None] = []
    for index, zone in enumerate(zones):
        when = taken.get(zone)
        char = chars[index]
        if not isinstance(when, str) or char == UNKNOWN_CLASS:
            found.append(None)
            continue
        at = datetime.fromisoformat(when)
        found.append(None if at < window.snapshot(day, zone) - slack else WeatherClass(int(char)))
    return found


# --- what the live pipeline read that morning ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class StationStats:
    """Each source's populated reads over the record: how many, their median rows, and their
    median share of rows the matcher placed (``None`` with too few to tell)."""

    captures: Mapping[str, int]
    median_rows: Mapping[str, float]
    placed: Mapping[str, float | None]


def station_stats(days: Iterable[MorningDay]) -> StationStats:
    """The sources' populated reads over every day the record keeps."""
    rows: dict[str, list[int]] = defaultdict(list)
    shares: dict[str, list[float]] = defaultdict(list)
    for found in days:
        for slot in found.slots.values():
            for source, reads in slot.reads.items():
                for count, placed, _unread in reads:
                    if count:
                        rows[source].append(count)
                        shares[source].append(placed / count)
    return StationStats(
        captures={source: len(found) for source, found in sorted(rows.items())},
        median_rows={s: float(statistics.median(found)) for s, found in sorted(rows.items())},
        placed={source: station_median(found) for source, found in sorted(shares.items())},
    )


@dataclass(frozen=True, slots=True)
class Morning:
    """What the live pipeline read on one day, from its morning record
    (:mod:`snowlight.live.morning`) and change log."""

    day: date
    slots: Mapping[datetime, Slot]
    """The record's slots of the UTC day ``day``, by their UTC start."""
    audience: Mapping[str, Mapping[str, date]]
    """Each source's districts and the first day it lit one of their schools
    (:func:`~snowlight.predict.labels.audiences`)."""
    market_of: Mapping[str, str]
    stats: StationStats
    prefix: str
    """The live prefix this learning step reads (``v1``, ``v1-shadow``): a pass shown under
    another is not what these timelines show."""
    named_before: Mapping[str, frozenset[str]] = field(default_factory=dict)
    """Districts a row named for ``day`` in the record of the UTC day before, with the status
    kinds named."""
    held: bool = False
    """The emergency stop held the map dark that day: nothing is labeled."""


def leaid_of(nces_id: str) -> str | None:
    """The district of a public school's 12-digit NCES id (its first 7 digits)."""
    if len(nces_id) == NCES_SCHOOL_DIGITS and nces_id.isdigit():
        return nces_id[:LEAID_DIGITS]
    return None


def audience_of(changes: ChangeLog, day: date, min_days: int) -> dict[str, dict[str, date]]:
    """Each source's audience up to ``day``: the districts whose schools it lit on at least
    ``min_days`` live days, each from the first of them."""
    listings: list[tuple[str, str, date]] = []
    for logged in changes.days():
        if logged > day:
            break
        for change in changes.changes(logged):
            source = change.fields.get("source_id")
            district = leaid_of(change.nces_id)
            if change.event in (Event.LIT, Event.CHANGED) and source and district:
                listings.append((str(source), district, change.day))
    return audiences(listings, min_days)


def held_on(changes: ChangeLog, day: date) -> bool:
    """Whether the emergency stop darkened the map on ``day``."""
    return any(
        change.shown is None and change.fields.get(BY) == BY_HOLD for change in changes.changes(day)
    )


OUTSIDE_48: Final = {"02": "AK", "15": "HI"}


def district_state(leaid: str) -> str:
    """The postal code of the state a LEAID's first two digits name (``""`` when unknown: then
    any state withheld whole disqualifies the slot)."""
    return state_of_leaid(leaid) or OUTSIDE_48.get(leaid[:2], "")


def window_of(day: date, zone: str, settings: LabelSettings) -> tuple[datetime, datetime]:
    """The settled read window [``read_from``, ``read_until``) local on ``day`` in ``zone``."""
    tz = ZoneInfo(zone)
    return (
        datetime.combine(day, settings.read_from, tzinfo=tz),
        datetime.combine(day, settings.read_until, tzinfo=tz),
    )


def _dropped(source: str, read: Read, stats: StationStats) -> bool:
    """A populated read the archive's replay step would drop: over a quarter of its rows
    read as no status, or under half its source's median share of rows placed."""
    rows, placed, unread = read
    return rows > 0 and (
        unread / rows > UNREADABLE_SHARE or low_match(placed / rows, stats.placed.get(source))
    )


def station_window(
    qualified: Sequence[Slot], every: Sequence[Slot], morning: Morning, settings: LabelSettings
) -> dict[str, StationRead]:
    """Each source's reads in a window (:class:`~snowlight.predict.labels.StationRead`), from
    the ``qualified`` slots: a populated read dropped as unreadable or matched too little
    never counts (``dropped_read``), and an empty one is void while another source of its
    market held ``market_rows_void`` rows in any read of the window (``every`` slot)."""
    busy: dict[str, set[str]] = defaultdict(set)
    for slot in every:
        for source, reads in slot.reads.items():
            if any(
                read[0] >= settings.market_rows_void and not _dropped(source, read, morning.stats)
                for read in reads
            ):
                busy[morning.market_of.get(source, source)].add(source)
    populated: dict[str, list[int]] = defaultdict(list)
    empty: dict[str, bool] = defaultdict(bool)
    refused: dict[str, list[Unread]] = defaultdict(list)
    seen: set[str] = set()
    for slot in qualified:
        for source, reads in slot.reads.items():
            seen.add(source)
            market = morning.market_of.get(source, source)
            for read in sorted(reads):
                if read[0] > 0:
                    if _dropped(source, read, morning.stats):
                        refused[source].append(Unread.DROPPED_READ)
                    else:
                        populated[source].append(read[0])
                elif busy.get(market, set()) - {source}:
                    refused[source].append(Unread.VOIDED_EMPTY)
                else:
                    empty[source] = True
    return {
        source: StationRead(
            tuple(populated.get(source, ())),
            empty.get(source, False),
            tuple(refused.get(source, ())),
        )
        for source in sorted(seen)
    }


def _slots_between(morning: Morning, start: datetime, end: datetime) -> list[Slot]:
    """The slots wholly inside [``start``, ``end``)."""
    return [
        slot
        for at, slot in sorted(morning.slots.items())
        if start <= at and at + timedelta(minutes=SLOT_MINUTES) <= end
    ]


def named_on(morning: Morning, leaid: str, until: datetime) -> frozenset[str]:
    """The status kinds a row named the district with for the day (or for every day) before
    ``until`` (empty: none named it): in the record of the day before for the day itself,
    and in the day's own record."""
    found = set(morning.named_before.get(leaid, ()))
    for at, slot in morning.slots.items():
        if at >= until:
            continue
        days = slot.named.get(leaid, {})
        found.update(days.get(morning.day.isoformat(), ()), days.get(EVERY_DAY, ()))
    return frozenset(found)


KIND_OF: Final = {status: kind for kind, status in STATUS_BY_KIND.items()}


def listed_unread(outcome: Outcome, named: frozenset[str], shown: frozenset[str]) -> bool:
    """Whether what a list named keeps the outcome from being told: any naming for an open
    district, and for a delayed one a status kind the map did not show on the district
    (``shown``: the kinds it lit on its schools that day; :data:`ANY_KIND` is never shown)."""
    if outcome is Outcome.OPEN:
        return bool(named)
    if outcome is Outcome.DELAYED:
        return not named <= shown
    return False


# --- the inputs, as the learning step sees them -------------------------------------------------


class LiveSource(Protocol):
    """Where the live days come from (the live host's public files and the live state)."""

    def index(self) -> DayIndex | None:
        """The host's day index, or ``None`` when it holds none."""
        ...

    def timeline(self, day: date) -> DayTimeline | None:
        """The host's timeline of ``day``, or ``None`` when it holds none."""
        ...

    def morning(self, day: date) -> Morning | str:
        """What was read on ``day``, or why it cannot be told yet (or ever)."""
        ...


NO_RECORD: Final = "no record of the live reads"
DAMAGED: Final = "its record of the live reads does not read"
NOT_SHOWN: Final = "no pass of the day was shown under the prefix learning reads"
"""A day the reader ran only in shadow (``v1-shadow``) or with publishing off: what it read
was never on the map, so it labels nothing (every district would be unknown) and is never
written as labeled; no later run changes that."""
NO_STATE: Final = "no live ingest state reached this run"


@dataclass(slots=True)
class NoLiveSource:
    """No live ingest state reached this run: nothing can be labeled (which is not to say no
    live day was read)."""

    def index(self) -> DayIndex | None:
        return None

    def timeline(self, day: date) -> DayTimeline | None:  # noqa: ARG002 - the protocol
        return None

    def morning(self, day: date) -> Morning | str:  # noqa: ARG002 - the protocol
        return NO_STATE


class Reader(Protocol):
    """Reads one file of the live host's folder (``live/...``), ``None`` when absent."""

    def __call__(self, path: str) -> bytes | None: ...


@dataclass(slots=True)
class StateSource:
    """The live ingest's private state folder (read only) and the live host's day files."""

    folder: Path
    market_of: Mapping[str, str]
    zone_of: Mapping[str, str]
    """Each deployed district's zone: a day is labeled only once the record reaches past
    every one of their read windows."""
    settings: LabelSettings
    prefix: str
    read_file: Reader
    _stats: StationStats | None = field(default=None, init=False)

    def index(self) -> DayIndex | None:
        data = self.read_file("live/days/index.json")
        return None if data is None else DayIndex.from_json_bytes(data)

    def timeline(self, day: date) -> DayTimeline | None:
        data = self.read_file(f"live/days/{day.isoformat()}.json")
        return None if data is None else DayTimeline.from_json_bytes(data)

    def morning(self, day: date) -> Morning | str:
        log = MorningLog(self.folder / "morning")
        record = log.day(day)
        if record is None:
            return NO_RECORD
        if record.damaged:
            return DAMAGED
        if not any(self.prefix in slot.shown for slot in record.slots.values()):
            return NOT_SHOWN
        through = log.through()
        zones = set(self.zone_of.values())
        last = max((window_of(day, zone, self.settings)[1] for zone in zones), default=None)
        if through is None or last is None or through < last:
            return "the live state was saved before its read windows closed"
        if self._stats is None:
            self._stats = station_stats(
                found for when in log.days() if (found := log.day(when)) is not None
            )
        before = log.day(day - timedelta(days=1))
        named_before: dict[str, set[str]] = {}
        for slot in before.slots.values() if before is not None else ():
            for leaid, days in slot.named.items():
                if day.isoformat() in days:
                    named_before.setdefault(leaid, set()).update(days[day.isoformat()])
        changes = ChangeLog(self.folder / "changes")
        return Morning(
            day=day,
            slots={slot_start(day, key): slot for key, slot in record.slots.items()},
            audience=audience_of(changes, day, self.settings.audience_days),
            market_of=self.market_of,
            stats=self._stats,
            prefix=self.prefix,
            named_before={leaid: frozenset(kinds) for leaid, kinds in named_before.items()},
            held=held_on(changes, day),
        )


def markets_of(stations: Iterable[tuple[str, str]]) -> dict[str, str]:
    """Each source's market from (source id, market)."""
    return dict(stations)


# --- one day's labels ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Lit:
    """What the timeline showed: each school's last status, and the schools whose status was
    taken back (the last change shows none)."""

    statuses: Mapping[int, LitStatus]
    retracted: frozenset[int]


def lit_of(timeline: DayTimeline | None) -> Lit:
    """Each school's last shown status on the timeline's day."""
    if timeline is None:
        return Lit({}, frozenset())
    statuses: dict[int, LitStatus] = {}
    retracted: set[int] = set()
    start = 0
    for school, count in zip(timeline.schools(), timeline.counts, strict=True):
        last = start + count - 1
        status = timeline.statuses[last]
        if status is None:
            retracted.add(school)
        else:
            statuses[school] = LitStatus(status, timeline.reasons[last])
        start += count
    return Lit(statuses, frozenset(retracted))


@dataclass(frozen=True, slots=True)
class Directory:
    """The deployed directory as labels need it: LEAIDs, each district's eligible school
    indexes and its zone, and the content its indexes belong to."""

    districts: tuple[str, ...]
    eligible: tuple[npt.NDArray[np.int64], ...]
    zones: tuple[str, ...]
    content: str
    stamp: DirectoryStamp
    digest: str | None = None
    """The directory's content digest, when it names one."""

    def indexes(self, timeline: DayTimeline) -> bool:
        """Whether ``timeline``'s school indexes are this directory's (the serving pass's
        rule: the same stamp and, when both name one, the same content digest)."""
        theirs = timeline.content_sha256
        return timeline.directory == self.stamp and (
            self.digest is None or theirs is None or theirs == self.digest
        )


@dataclass(slots=True)
class _Windows:
    """One day's windows, per zone and per state (the slots a state's reads count in)."""

    morning: Morning
    settings: LabelSettings
    found: dict[tuple[str, str], tuple[dict[str, StationRead], dict[str, set[str]]]] = field(
        default_factory=dict
    )

    def of(self, zone: str, state: str) -> tuple[dict[str, StationRead], dict[str, set[str]]]:
        key = (zone, state)
        if key not in self.found:
            start, end = window_of(self.morning.day, zone, self.settings)
            every = _slots_between(self.morning, start, end)
            last = end - timedelta(minutes=SLOT_MINUTES)
            ran_through = any(last <= at < end for at in self.morning.slots)
            qualified = [
                slot
                for slot in every
                if ran_through
                and slot.shown == {self.morning.prefix}
                and (state not in slot.unknown if state else not slot.unknown)
            ]
            window = station_window(qualified, every, self.morning, self.settings)
            readers: dict[str, set[str]] = defaultdict(set)
            for source, item in window.items():
                if item.populated or item.empty:
                    readers[self.morning.market_of.get(source, source)].add(source)
            self.found[key] = (window, readers)
        return self.found[key]


def label_live_day(  # noqa: PLR0913 - the day, its three inputs and the rules
    day: date,
    *,
    lit: Lit,
    morning: Morning,
    classes: Sequence[WeatherClass | None],
    directory: Directory,
    settings: LabelSettings,
) -> list[dict[str, object]]:
    """The labeled district-days of one live day, as the archive's label rows (with
    ``cluster``, the market of its readers): every deployed district a source carries that
    day, unknown with why unless a carrying source's whole read in its window counts."""
    if morning.held or not is_school_day(day):
        return []
    pause = likely_break(day)
    position = {leaid: i for i, leaid in enumerate(directory.districts)}
    carriers: dict[str, list[str]] = defaultdict(list)
    for source in sorted(morning.audience):
        for district in carries(morning.audience, source, day):
            if district in position:
                carriers[district].append(source)
    windows = _Windows(morning, settings)
    rows: list[dict[str, object]] = []
    for leaid, stations in sorted(carriers.items()):
        index = position[leaid]
        schools = [int(s) for s in directory.eligible[index].tolist()]
        if not schools:
            continue
        zone = directory.zones[index]
        weather = classes[index]
        found = shares(
            [str(s) for s in schools],
            {str(s): lit.statuses[s] for s in schools if s in lit.statuses},
            weather if weather is not None else WeatherClass.NONE,
        )
        window, readers_of_market = windows.of(zone, district_state(leaid))
        readers, unread = district_readers(
            stations,
            window,
            readers_of_market,
            weather is not None and weather is not WeatherClass.NONE,
            market_of=morning.market_of,
            captures=morning.stats.captures,
            median_rows=morning.stats.median_rows,
            settings=settings,
        )
        why: str | None = None
        if not readers:
            why = unread.value if unread is not None else LiveWhy.NOT_READ
        if pause:
            why = LiveWhy.BREAK
        elif weather is None:
            why = LiveWhy.NO_WEATHER
        elif any(s in lit.retracted for s in schools):
            why = LiveWhy.RETRACTED
        outcome = Outcome.UNKNOWN if why else outcome_of(found, read=readers > 0, settings=settings)
        named = named_on(morning, leaid, window_of(day, zone, settings)[1])
        shown = frozenset(KIND_OF[lit.statuses[s].status] for s in schools if s in lit.statuses)
        if listed_unread(outcome, named, shown):
            outcome, why = Outcome.UNKNOWN, Unread.LISTED_UNREAD.value
        if why is None and outcome is Outcome.UNKNOWN:
            why = "partly_lit"
        market = morning.market_of.get(stations[0], stations[0])
        rows.append(
            {
                "district": leaid,
                "day": day,
                "season": season_of(day),
                "outcome": outcome.value,
                "did": did_of(outcome, found),
                "unknown_why": why,
                "readers": readers if outcome is not Outcome.UNKNOWN else 0,
                "no_school_share": round(found.no_school, 4),
                "delayed_share": round(found.delayed, 4),
                "lit_share": round(found.any_status, 4),
                "weather": int(weather) if weather is not None else 0,
                "cluster": market,
            }
        )
    return rows


LIVE_SCHEMA: Final = {**LABEL_SCHEMA, "cluster": pl.String}


def finish_labels(rows: Sequence[Mapping[str, object]], storm_share: float) -> pl.DataFrame:
    """The live label rows as a frame: storm-day absences made unknown by the archive's rule
    (by the reader's market), and the day after a closing marked."""
    frame = pl.DataFrame(list(rows), schema=LIVE_SCHEMA)
    frame = storm_absences(frame, storm_share).drop("cluster")
    return with_day_after(frame).sort("district", "day")


def day_ready(day: date, timeline: DayTimeline | None, index: DayIndex | None) -> str | None:
    """``None`` when what the map showed on ``day`` is known for good (a final timeline, or
    none while the host's index, written after the day was over everywhere, does not list
    the day), else why not."""
    if timeline is not None:
        return None if timeline.final else "its timeline is not final yet"
    if index is None or not is_final(day, index.generated_at):
        return "its timeline is not final yet"
    if any(entry.day == day for entry in index.days):
        return "the live host lists its timeline but holds none that reads"
    return None
