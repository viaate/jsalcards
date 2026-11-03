"""Each district's usual call time, and a chance that declines past it (predict-next CALL-TIME).

The owner asked (Nov 2) for "average call time, with the chance declining once it passes", and
only while the district's sources were read healthily (audit piece 19). This module holds the
pieces, registered in ``predict.yaml`` ``live_score.call_time``, with the term **off**
(CALL-TIME-1): nothing served reads it, and only :mod:`snowlight.predict.read_cli` imports it,
for one counts-only log line per day labeled (:func:`day_counts`).

**Samples are map times** (:func:`called_minutes`): a district's call on school day D is the
first local minute of D's final day timeline at which the map showed it no school for the
weather by the label rule's shares (:func:`~snowlight.predict.live_read.lit_no_school`'s), on
an advisory, warning or cold day. Before 18:00 the evening before it is ``ahead`` (no
sample); from 18:00 to midnight ``evening`` (kept apart, never in u); from midnight to 09:30
``morning``; later ``late``. A day with any school of the district taken back (relit or
not), a likely break or another directory's timeline gives none.

**The usual call time u** (:func:`usual_calls`): the median of the district's own morning
calls (weight 1 each) and 3 pseudo-samples at its pool's median. The pool is its market on D
(:func:`market_on`) when the market's districts hold 10 morning calls from 3 districts, else
its state on that minimum, else none (no term, never national). Three own calls: grace 15
minutes; else 30. A call needs its day's weather class, which the counts line takes from the
predict state's class snapshots; those leave the state after ``SNAPSHOT_KEEP_DAYS`` (45) days
(the evidence store keeps them, and the predict job never reads it), so for now u reaches back
about 45 days, not to every final timeline the host keeps for good: keeping each final day's
class for good (codes only) is left to CALL-TIME-2.

**Proof** (:func:`proof`): every tier-A list of the district in the live registry is required
(:func:`required`; a dark one, with no whole read in the 45 days, is required too and blocks,
by the lead's ruling). At slot end s, L1's checks 1 to 3 run on the rule copy's window
[05:00, s) and D's record cut at s, and condition 4 for the district; each required list's
mark is the end of its latest qualifying slot whose read holds no unplaced row, and P(s) is
their minimum (none while any has none). P* is P's running maximum: a failed, refused,
deferred, partial or unhealthy read adds no slot, so P* holds. A required list's mark that
falls (a peer check of the longer window fails its latest slot and no later slot qualifies)
voids D's proof: Delta 0, a rise. A row naming the district for D or every day, in D-1's
record or a slot before s, ends it the same way.

**The decline** (:func:`decline`): x = 0 before proof; at each slot end x_k = max(x_{k-1},
min(P*_k - (u + g), x_{k-1} + 30)), held after 09:30; Delta = ln(m + (1 - m) exp(-x / tau)),
(m, tau) only from the registered domain F (:func:`in_domain`). It would be added to the
model's own chance's log-odds after L5, the class order cap and the G6 pull
(:func:`with_decline`), the published delay held.

Everything here is codes, ids, minutes and counts: no names, no list text.
"""

import math
from collections import Counter, defaultdict
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Final
from zoneinfo import ZoneInfo

from snowlight.live.merge import day_start
from snowlight.live.morning import EVERY_DAY, SLOT_MINUTES, Slot
from snowlight.predict.calendar import likely_break
from snowlight.predict.calendar import season_of as season_of_day
from snowlight.predict.config import PredictConfig
from snowlight.predict.labels import LitStatus, Outcome, outcome_of, shares
from snowlight.predict.live_labels import Directory, Morning, district_state
from snowlight.predict.live_read import (
    WARNING_CLASSES,
    Coverage,
    ListStats,
    ReadRule,
    Tier,
    _Windows,
)
from snowlight.predict.serve import ADJUST_KINDS
from snowlight.predict.situations import WeatherClass
from snowlight.schemas.live import DayTimeline

STEP: Final = 30
"""Minutes between slot ends (the record's slot)."""
EPSILON: Final = 1e-9


class CallKind(StrEnum):
    """When a call fell against its day (local minutes from D's midnight)."""

    AHEAD = "ahead"
    """Before 18:00 the evening before: a closing posted days ahead, no sample."""
    EVENING = "evening"
    """18:00 to midnight the evening before: kept apart, never in u."""
    MORNING = "morning"
    """Midnight to 09:30 on D: the samples of u."""
    LATE = "late"
    """After 09:30 on D: never in u."""


class PoolKind(StrEnum):
    MARKET = "market"
    STATE = "state"


def _hm(value: object) -> int:
    """``HH:MM`` as minutes from midnight."""
    hours, minutes = (int(part) for part in str(value).split(":"))
    return hours * 60 + minutes


def _num(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError("a number")
    return float(value)


def _grid(value: object) -> tuple[float, ...]:
    """``[first, last, step]`` as its points."""
    if not isinstance(value, list) or len(value) != 3:  # noqa: PLR2004 - first, last, step
        raise TypeError("a grid is [first, last, step]")
    first, last, step = (_num(v) for v in value)
    count = round((last - first) / step)
    return tuple(round(first + n * step, 6) for n in range(count + 1))


def delta(x: float, m: float, tau: float) -> float:
    """Delta(x) = ln(m + (1 - m) exp(-x / tau)): 0 at x 0, falling to ln m."""
    return math.log(m + (1.0 - m) * math.exp(-max(x, 0.0) / tau))


@dataclass(frozen=True, slots=True)
class CallSettings:
    """``live_score.call_time`` as this module reads it, at one point (m, tau) of F."""

    serve: str
    m: float
    tau: float
    classes: frozenset[str]
    evening_from: int
    """Local minutes from D's midnight (negative: the evening before)."""
    morning_until: int
    proof_from: time
    slot_from: int
    slot_until: int
    held_row: int
    step: int
    own_min_calls: int
    own_grace: int
    pool_grace: int
    shrink: int
    pool_min_calls: int
    pool_min_districts: int
    lead_days: int
    required_days: int
    m_grid: tuple[float, ...]
    tau_grid: tuple[float, ...]
    first_slot_max: float
    default: tuple[float, float]

    @classmethod
    def of(
        cls, config: PredictConfig, m: float | None = None, tau: float | None = None
    ) -> "CallSettings":
        """The block as registered, at (``m``, ``tau``) (the default when not given).

        Raises:
            ValueError: the block lacks a setting, holds the wrong kind, serves other than
                off, or (m, tau) is outside the registered domain F (never clamped).
        """
        block = config.live_score.get("call_time")
        if block is None:
            raise ValueError("live_score.call_time is not registered")
        try:
            default = block["default"]
            classes = block["classes"]
            if not isinstance(default, list) or not isinstance(classes, list):
                raise TypeError("default and classes are lists")
            found = cls(
                serve=str(block["serve"]),
                m=_num(default[0]) if m is None else m,
                tau=_num(default[1]) if tau is None else tau,
                classes=frozenset(str(c) for c in classes),
                evening_from=_hm(block["evening_from"]) - 24 * 60,
                morning_until=_hm(block["morning_until"]),
                proof_from=time.fromisoformat(str(block["proof_from"])),
                slot_from=_hm(_pair(block["slots"])[0]),
                slot_until=_hm(_pair(block["slots"])[1]),
                held_row=_hm(block["held_row"]),
                step=int(_num(block["step_minutes"])),
                own_min_calls=int(_num(block["own_min_calls"])),
                own_grace=int(_num(block["own_grace"])),
                pool_grace=int(_num(block["pool_grace"])),
                shrink=int(_num(block["shrink"])),
                pool_min_calls=int(_num(block["pool_min_calls"])),
                pool_min_districts=int(_num(block["pool_min_districts"])),
                lead_days=int(_num(block["lead_days"])),
                required_days=int(_num(block["required_days"])),
                m_grid=_grid(block["m_grid"]),
                tau_grid=_grid(block["tau_grid"]),
                first_slot_max=_num(block["first_slot_max"]),
                default=(_num(default[0]), _num(default[1])),
            )
        except (KeyError, IndexError, TypeError) as error:
            raise ValueError(f"live_score.call_time: {type(error).__name__}") from error
        if found.serve != "off":
            raise ValueError(f"live_score.call_time.serve is off only, not {found.serve!r}")
        found.check()
        return found

    def in_domain(self, m: float, tau: float) -> bool:
        """Whether (m, tau) is a point of F: on the grids, and Delta(30) at least
        -``first_slot_max``."""
        if not (math.isfinite(m) and math.isfinite(tau)):
            return False
        on_m = any(abs(m - point) < EPSILON for point in self.m_grid)
        on_tau = any(abs(tau - point) < EPSILON for point in self.tau_grid)
        return on_m and on_tau and delta(self.step, m, tau) >= -self.first_slot_max - EPSILON

    def check(self) -> None:
        """Refuse a settings object whose (m, tau) is outside F, however it was made
        (:meth:`of`, ``dataclasses.replace`` or direct construction): what serves is what
        was tested, never clamped.

        Raises:
            ValueError: (m, tau) is not a point of F.
        """
        if not self.in_domain(self.m, self.tau):
            raise ValueError(f"(m, tau) = ({self.m}, {self.tau}) is outside the registered F")

    def domain(self) -> list[tuple[float, float]]:
        """Every point of F, in grid order."""
        return [(m, t) for m in self.m_grid for t in self.tau_grid if self.in_domain(m, t)]

    def ends(self) -> tuple[int, ...]:
        """The slot ends scored (local minutes), then the held row."""
        found = tuple(range(self.slot_from, self.slot_until + 1, self.step))
        return (*found, self.held_row)


def _pair(value: object) -> tuple[object, object]:
    if not isinstance(value, list) or len(value) != 2:  # noqa: PLR2004 - from, until
        raise TypeError("a pair")
    return value[0], value[1]


# --- samples ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Call:
    """One district's call on one day: its local minute from D's midnight and its kind."""

    leaid: str
    day: date
    minute: int
    kind: CallKind


def local_minute(at: datetime, day: date, zone: str) -> int:
    """``at`` as whole local minutes from ``day``'s midnight in ``zone`` (negative: the
    evening before)."""
    local = at.astimezone(ZoneInfo(zone))
    return (local.date() - day).days * 24 * 60 + local.hour * 60 + local.minute


def kind_of(minute: int, settings: CallSettings) -> CallKind:
    """A call's kind by its local minute."""
    if minute < settings.evening_from:
        return CallKind.AHEAD
    if minute < 0:
        return CallKind.EVENING
    if minute <= settings.morning_until:
        return CallKind.MORNING
    return CallKind.LATE


def _runs(timeline: DayTimeline) -> dict[int, list[tuple[int, LitStatus | None]]]:
    """Each school's changes: (timeline minute, status shown from then; ``None``: taken back)."""
    found: dict[int, list[tuple[int, LitStatus | None]]] = {}
    start = 0
    for school, count in zip(timeline.schools(), timeline.counts, strict=True):
        run: list[tuple[int, LitStatus | None]] = []
        for at in range(start, start + count):
            status = timeline.statuses[at]
            lit = None if status is None else LitStatus(status, timeline.reasons[at])
            run.append((timeline.minutes[at], lit))
        found[school] = run
        start += count
    return found


def called_minutes(
    timeline: DayTimeline | None,
    directory: Directory,
    classes: Sequence[WeatherClass | None],
    settings: CallSettings,
    rule: ReadRule,
) -> dict[str, Call]:
    """Each district's call on the timeline's day (see the module docstring): the first
    minute the map showed it no school for the weather on a day of a registered class, as a
    local minute of the day with its kind. None from a likely break, another directory's
    timeline, or a district with any school taken back that day."""
    if timeline is None or likely_break(timeline.day) or not directory.indexes(timeline):
        return {}
    day = timeline.day
    runs = _runs(timeline)
    owner: dict[int, int] = {}
    for index, eligible in enumerate(directory.eligible):
        for school in eligible.tolist():
            owner[int(school)] = index
    touched: dict[int, list[int]] = defaultdict(list)
    for school in runs:
        if school in owner:
            touched[owner[school]].append(school)
    found: dict[str, Call] = {}
    for index in sorted(touched):
        klass = classes[index]
        if klass is None or not serves(klass, settings):
            continue
        schools = [int(s) for s in directory.eligible[index].tolist()]
        mine = {s: runs[s] for s in schools if s in runs}
        if any(status is None for run in mine.values() for _m, status in run):
            continue
        minute = _first_no_school(mine, schools, klass, rule)
        if minute is None:
            continue
        zone = directory.zones[index]
        at = day_start(day, (zone,)) + timedelta(minutes=minute)
        local = local_minute(at, day, zone)
        leaid = directory.districts[index]
        found[leaid] = Call(leaid, day, local, kind_of(local, settings))
    return found


def _serving(klass: WeatherClass) -> str:
    if klass is WeatherClass.ADVISORY:
        return "advisory"
    if klass is WeatherClass.COLD:
        return "cold"
    return "warning"


def serves(klass: WeatherClass | None, settings: CallSettings) -> bool:
    """Whether a district-day of ``klass`` is one of the term's classes (advisory, warning or
    cold): the only days that give a call or are counted."""
    return (
        klass is not None and klass is not WeatherClass.NONE and _serving(klass) in settings.classes
    )


def _first_no_school(
    runs: Mapping[int, Sequence[tuple[int, LitStatus | None]]],
    schools: Sequence[int],
    klass: WeatherClass,
    rule: ReadRule,
) -> int | None:
    """The first timeline minute at which the district's lit shares made it no school."""
    moments = sorted({minute for run in runs.values() for minute, _ in run})
    eligible = [str(s) for s in schools]
    for moment in moments:
        statuses: dict[str, LitStatus] = {}
        for school, run in runs.items():
            shown = [status for minute, status in run if minute <= moment]
            if shown and shown[-1] is not None:
                statuses[str(school)] = shown[-1]
        found = shares(eligible, statuses, klass)
        if outcome_of(found, read=True, settings=rule.labels) is Outcome.NO_SCHOOL:
            return moment
    return None


# --- the usual call time ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UsualCall:
    """A district's usual call time: the local minute, its own morning calls, and the pool
    its pseudo-samples came from."""

    minute: int
    own: int
    pool: PoolKind

    def grace(self, settings: CallSettings) -> int:
        """Minutes past u before the decline starts: 15 with an own u, else 30."""
        return settings.own_grace if self.own >= settings.own_min_calls else settings.pool_grace


def _median(values: Sequence[int]) -> int:
    """The lower median (a minute that is one of the values)."""
    ordered = sorted(values)
    return ordered[(len(ordered) - 1) // 2]


def usual_calls(  # noqa: PLR0913 - the calls, the pools and which calls count
    calls: Iterable[Call],
    market_of: Callable[[str], str | None],
    state_of: Callable[[str], str],
    settings: CallSettings,
    *,
    before: date,
    outside: int | None = None,
    districts: Iterable[str] | None = None,
) -> dict[str, UsualCall]:
    """Each district's usual call time on ``before`` (see the module docstring), from the
    morning calls strictly before it, leaving out every call of the season ``outside`` (the
    fold rule: no call of a held-out season enters a training value, pools included).
    ``market_of`` is each district's market on ``before`` (:func:`market_on`); a district
    whose pools hold too few calls has none. ``districts``: those asked for (by default every
    district with a call or a qualifying pool among the calls' districts)."""
    own: dict[str, list[int]] = defaultdict(list)
    for call in calls:
        if call.kind is not CallKind.MORNING or call.day >= before:
            continue
        if outside is not None and season_of_day(call.day) == outside:
            continue
        own[call.leaid].append(call.minute)
    pools: dict[tuple[PoolKind, str], list[int]] = defaultdict(list)
    members: dict[tuple[PoolKind, str], set[str]] = defaultdict(set)
    for leaid, minutes in own.items():
        market = market_of(leaid)
        keys = [(PoolKind.STATE, state_of(leaid))]
        if market is not None:
            keys.insert(0, (PoolKind.MARKET, market))
        for key in keys:
            pools[key].extend(minutes)
            members[key].add(leaid)

    def pool_of(leaid: str) -> tuple[PoolKind, int] | None:
        market = market_of(leaid)
        for key in (
            *([(PoolKind.MARKET, market)] if market is not None else []),
            (PoolKind.STATE, state_of(leaid)),
        ):
            if (
                len(pools.get(key, ())) >= settings.pool_min_calls
                and len(members.get(key, ())) >= settings.pool_min_districts
            ):
                return key[0], _median(pools[key])
        return None

    found: dict[str, UsualCall] = {}
    for leaid in sorted(own) if districts is None else sorted(set(districts)):
        pool = pool_of(leaid)
        if pool is None:
            continue
        kind, middle = pool
        mine = own.get(leaid, [])
        found[leaid] = UsualCall(_median([*mine, *([middle] * settings.shrink)]), len(mine), kind)
    return found


type WholeReads = Mapping[date, AbstractSet[str]]
"""Each UTC day of the morning record: the sources with a whole read in a slot shown under the
prefix read."""


def whole_reads(
    days: Mapping[date, Mapping[datetime, Slot]], prefix: str
) -> dict[date, frozenset[str]]:
    """:data:`WholeReads` from the record's days (slots by UTC start)."""
    return {
        day: frozenset(
            source for slot in slots.values() if prefix in slot.shown for source in slot.reads
        )
        for day, slots in sorted(days.items())
    }


def _days_read(source: str, whole: WholeReads, first: date, last: date) -> int:
    return sum(1 for day, found in whole.items() if first <= day < last and source in found)


def tier_a(
    leaid: str,
    day: date,
    coverage: Coverage,
    stats: ListStats,
    audience: Mapping[str, Mapping[str, date]],
) -> list[str]:
    """The district's tier-A sources on ``day`` (never a district site)."""
    found = coverage.candidates(leaid, day, audience, stats.closing)
    return sorted(s for s, tier in found.items() if tier is Tier.A)


def market_on(  # noqa: PLR0913 - the district, its day and the record
    leaid: str,
    day: date,
    record: WholeReads,
    coverage: Coverage,
    stats: ListStats,
    *,
    audience: Mapping[str, Mapping[str, date]],
    market_of: Mapping[str, str],
    settings: CallSettings,
) -> str | None:
    """The district's market on ``day``: the registry market of its tier-A source with the
    most days of a whole read in the record's ``lead_days`` days before ``day`` (ties: more
    captures, then the lowest id), so a dead lowest-id carrier never picks it; ``None`` when
    none was read whole in those days."""
    first = day - timedelta(days=settings.lead_days)
    ranked = sorted(
        (-_days_read(source, record, first, day), -stats.captures.get(source, 0), source)
        for source in tier_a(leaid, day, coverage, stats, audience)
    )
    for days, _captures, source in ranked:
        if days < 0:
            return market_of.get(source, source)
    return None


# --- required lists and proof -------------------------------------------------------------------


class DarkCause(StrEnum):
    """Why a required list had no whole read in the 45 days (the ledger's last outcome), in
    the order a district's causes are joined."""

    REFUSED = "refused"
    FAILED = "failed"
    DEFERRED = "deferred"
    NEVER_WHOLE = "never_whole"
    """The ledger names no refusal, failure or deferral of it (or holds no row of it)."""
    NOT_HERE = "(cause not on this host)"
    """The host holds no ledger outcomes: the predict job reads the state export, whose
    ledger is schema only, so a cause is never guessed there."""


def dark_cause(last_outcome: str | None, *, known: bool = True) -> DarkCause:
    """A dark list's cause from the ledger's last outcome of it (``None``: no ledger row);
    ``known`` false: the host holds no ledger outcomes at all (:attr:`DarkCause.NOT_HERE`)."""
    if not known:
        return DarkCause.NOT_HERE
    return {
        "blocked": DarkCause.REFUSED,
        "error": DarkCause.FAILED,
        "deferred": DarkCause.DEFERRED,
    }.get(last_outcome or "", DarkCause.NEVER_WHOLE)


@dataclass(frozen=True, slots=True)
class Required:
    """R(d, D): every tier-A list of the district in the live registry, in id order; of them
    the dark ones (no whole read in the record's ``required_days`` days before D nor on D),
    which prove nothing and block; and the archive-only carriers, never required."""

    sources: tuple[str, ...]
    dark: tuple[str, ...] = ()
    archive_only: tuple[str, ...] = ()


def required(  # noqa: PLR0913 - the district, its day and the record
    leaid: str,
    day: date,
    record: WholeReads,
    coverage: Coverage,
    stats: ListStats,
    *,
    audience: Mapping[str, Mapping[str, date]],
    registry: Collection[str],
    settings: CallSettings,
) -> Required:
    """R(d, D) (see :class:`Required`; the lead's ruling: a dark carrier the reader attempts
    is required, so a reading failure can never lower a chance). Tier B never proves."""
    carriers = tier_a(leaid, day, coverage, stats, audience)
    first = day - timedelta(days=settings.required_days)
    live = tuple(s for s in carriers if s in registry)
    dark = tuple(s for s in live if not _days_read(s, record, first, day + timedelta(days=1)))
    return Required(live, dark, tuple(s for s in carriers if s not in registry))


@dataclass(frozen=True, slots=True)
class Proof:
    """What D's record cut at one slot end proves for one district."""

    p: int | None
    """P(s): the earliest of the required lists' marks, as a local minute of D; ``None``:
    no proof at s (some required list has no mark, or condition 4 fails)."""
    marks: Mapping[str, datetime | None]
    """Each required list's mark: the end (UTC) of its latest qualifying slot whose read
    holds no unplaced row."""
    void: bool = False
    """A required list's mark fell (or went) against the slot end before: D's proof ends."""
    reached: bool = True
    """The record reached the slot before s; else nothing is told and every mark holds."""


@dataclass(slots=True)
class Cuts:
    """D's record cut at each slot end, with its rule copy, shared by every district of the
    day (one :class:`~snowlight.predict.live_read._Windows` per slot end and zone)."""

    morning: Morning
    rule: ReadRule
    stats: ListStats
    district_sites: AbstractSet[str]
    settings: CallSettings
    _found: dict[tuple[int, str], tuple[_Windows, Morning] | None] = field(default_factory=dict)

    def at(self, end: int, zone: str) -> tuple[_Windows, Morning] | None:
        """The windows of D's record cut at the local slot end ``end`` in ``zone`` (``None``
        when the record does not reach the slot before it)."""
        key = (end, zone)
        if key not in self._found:
            day = self.morning.day
            # the wall clock's minute, also on a day the clocks change
            until = time(end // 60, end % 60)
            cut_at = datetime.combine(day, until, tzinfo=ZoneInfo(zone)).astimezone(UTC)
            last = cut_at - timedelta(minutes=SLOT_MINUTES)
            slots = {
                at: slot
                for at, slot in self.morning.slots.items()
                if at + timedelta(minutes=SLOT_MINUTES) <= cut_at
            }
            if last not in slots:
                self._found[key] = None
            else:
                cut = replace(self.morning, slots=slots)
                labels = self.rule.labels.model_copy(
                    update={"read_from": self.settings.proof_from, "read_until": until}
                )
                rule = replace(self.rule, labels=labels)
                self._found[key] = (_Windows(cut, rule, self.stats, self.district_sites), cut)
        return self._found[key]


def proof(  # noqa: PLR0913 - the record, the slot end, the lists and the district's window
    cuts: Cuts,
    end: int,
    needed: Required,
    *,
    zone: str,
    state: str,
    storm: bool,
    warning: bool,
    recent: Mapping[str, int],
    before: Mapping[str, datetime | None] | None = None,
) -> Proof:
    """P at the local slot end ``end`` for a district whose required lists are ``needed``
    (see the module docstring); ``before``: the marks at the slot end before (a fall voids)."""
    held = dict(before or {})
    if not needed.sources:
        return Proof(None, {}, reached=True)
    found = cuts.at(end, zone)
    if found is None:
        return Proof(None, held, reached=False)
    windows, cut = found
    qualified = windows.of(zone, state, storm, warning)
    marks: dict[str, datetime | None] = {}
    for source in needed.sources:
        item = qualified.get(source)
        clean = [
            at
            for at in (item.slots if item is not None else ())
            if not any(rows > placed for rows, placed, _ in cut.slots[at].reads.get(source, ()))
        ]
        marks[source] = max(clean) + timedelta(minutes=SLOT_MINUTES) if clean else None
    void = any(_fell(was, marks[source]) for source, was in held.items() if source in marks)
    marked = [s for s in needed.sources if marks[s] is not None]
    markets = Counter(cut.market_of.get(s, s) for s in marked)
    fresh = any(recent.get(s, 0) >= 1 or markets[cut.market_of.get(s, s)] >= 2 for s in marked)  # noqa: PLR2004
    if len(marked) < len(needed.sources) or not fresh:
        return Proof(None, marks, void=void)
    earliest = min(m for m in marks.values() if m is not None)
    return Proof(local_minute(earliest, cut.day, zone), marks, void=void)


def _fell(was: datetime | None, now: datetime | None) -> bool:
    """Whether a list's mark fell against the slot end before (or went)."""
    return was is not None and (now is None or now < was)


def named_by(morning: Morning, leaid: str, until: datetime, every_before: AbstractSet[str]) -> bool:
    """Whether a row named the district for D or for every day before ``until``: in D-1's
    record (for D, or ``*``: ``every_before``) or in D's record."""
    if morning.named_before.get(leaid) or leaid in every_before:
        return True
    day = morning.day.isoformat()
    return any(
        at < until and (day in (days := slot.named.get(leaid, {})) or EVERY_DAY in days)
        for at, slot in morning.slots.items()
    )


@dataclass(frozen=True, slots=True)
class SlotProof:
    """One slot end's proof state for a district."""

    end: int
    """The slot end, local minutes."""
    p_star: int | None
    """P*: P's running maximum (``None``: never proven yet)."""
    ended: str | None = None
    """``named`` or ``void`` once D's proof ended (Delta 0 from then on)."""


def proven(  # noqa: PLR0913 - the record, the district and its lists
    cuts: Cuts,
    leaid: str,
    needed: Required,
    *,
    zone: str,
    storm: bool,
    warning: bool,
    recent: Mapping[str, int],
    every_before: AbstractSet[str],
) -> list[SlotProof]:
    """The district's proof at each slot end of the settings (``ends``), in order."""
    found: list[SlotProof] = []
    marks: dict[str, datetime | None] = {}
    best: int | None = None
    ended: str | None = None
    state = district_state(leaid)
    for end in cuts.settings.ends():
        local = datetime.combine(cuts.morning.day, time(end // 60, end % 60), ZoneInfo(zone))
        if ended is None and named_by(cuts.morning, leaid, local.astimezone(UTC), every_before):
            ended = "named"
        if ended is None:
            here = proof(
                cuts, end, needed, zone=zone, state=state, storm=storm, warning=warning,
                recent=recent, before=marks,
            )  # fmt: skip
            if here.void:
                ended = "void"
            elif here.reached:
                marks = dict(here.marks)
                if here.p is not None:
                    best = here.p if best is None else max(best, here.p)
        found.append(SlotProof(end, best, ended))
    return found


@dataclass(frozen=True, slots=True)
class Decline:
    """One slot end's decline: x (minutes past u + g, grown at most a step a slot) and
    Delta (log odds, 0 or below)."""

    end: int
    x: float
    delta: float


def decline(
    proofs: Sequence[SlotProof], usual: UsualCall | None, settings: CallSettings
) -> list[Decline]:
    """x and Delta at each slot end (see the module docstring): 0 before proof and without a
    usual call time; once proof ends (a naming or a void), 0 for the rest of D; after the last
    scored slot end, held.

    Raises:
        ValueError: ``settings`` is outside F (:meth:`CallSettings.check`).
    """
    settings.check()
    found: list[Decline] = []
    x = 0.0
    for item in proofs:
        if item.ended is not None:
            found.append(Decline(item.end, 0.0, 0.0))
            continue
        if usual is not None and item.p_star is not None and item.end <= settings.slot_until:
            past = item.p_star - (usual.minute + usual.grace(settings))
            x = max(x, min(float(past), x + settings.step))
        found.append(Decline(item.end, x, delta(x, settings.m, settings.tau)))
    return found


def applies(kinds: Collection[str], raw_known: bool) -> bool:
    """Whether a pass's chance is the model's own, so the decline may move it: no reason
    kinds, or kinds within :data:`~snowlight.predict.serve.ADJUST_KINDS` with the raw chance
    known (the frozen record's ``_unrounded`` model branch); never ``said_open``, a lit status,
    an override or the outlook."""
    if "said_open" in kinds or not raw_known:
        return False
    return set(kinds) <= ADJUST_KINDS


def with_decline(  # noqa: PLR0913 - the chance, the delay, Delta, the bounds and F's point
    p_raw: float,
    q_published: float,
    delta_: float,
    floor: float,
    ceiling: float,
    *,
    settings: CallSettings,
) -> tuple[float, float]:
    """The chance of no school with Delta added to its log-odds, then the publish floor and
    ceiling; the published delay held at its value without the term.

    Raises:
        ValueError: ``settings`` is outside F; Delta is not a number from 0 down to
            ln(``settings.m``) (the most F's point can lower); or the chance is not one.
    """
    settings.check()
    if not math.isfinite(delta_) or delta_ > 0 or delta_ < math.log(settings.m) - EPSILON:
        raise ValueError("the decline is a number from 0 down to ln m")
    if not (math.isfinite(p_raw) and 0.0 <= p_raw <= 1.0):
        raise ValueError("a chance is a number from 0 to 1")
    p = min(max(p_raw, EPSILON), 1.0 - EPSILON)
    moved = 1.0 / (1.0 + math.exp(-(math.log(p / (1.0 - p)) + delta_)))
    return min(max(moved, floor), ceiling), q_published


# --- the decision rule's rows -------------------------------------------------------------------


class Risk(StrEnum):
    """Whether a district-time is at risk (scored), and why not."""

    AT_RISK = "at_risk"
    NOT_READ = "not_read"
    NOT_SERVED = "not_served"
    LIT = "lit"
    NAMED = "named"


def at_risk(t: int, *, read: bool, served: bool, called: int | None, named: int | None) -> Risk:
    """A district-time at local minute ``t``: in L1's read set, with a served frozen row
    (``s`` 1, ``pr`` known, no ``sa``), not lit no school by ``t`` (``called``: its call's
    minute), and no row naming it for D or every day by ``t`` (``named``: the first such
    minute; D-1's record counts as before every ``t``)."""
    if not read:
        return Risk.NOT_READ
    if not served:
        return Risk.NOT_SERVED
    if called is not None and called <= t:
        return Risk.LIT
    if named is not None and named <= t:
        return Risk.NAMED
    return Risk.AT_RISK


def first_named(
    morning: Morning, leaid: str, zone: str, every_before: AbstractSet[str]
) -> int | None:
    """The first local minute of D at which a row had named the district for D or every day
    (a slot's end; D-1's record: before every minute of D)."""
    if morning.named_before.get(leaid) or leaid in every_before:
        return -24 * 60
    day = morning.day.isoformat()
    starts = sorted(
        at
        for at, slot in morning.slots.items()
        if day in (days := slot.named.get(leaid, {})) or EVERY_DAY in days
    )
    if not starts:
        return None
    return local_minute(starts[0] + timedelta(minutes=SLOT_MINUTES), morning.day, zone)


# --- the counts line ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DayInputs:
    """One labeled day as the counts line reads it (codes only)."""

    day: date
    morning: Morning
    directory: Directory
    coverage: Coverage
    stats: ListStats
    classes: Sequence[WeatherClass | None]
    read: AbstractSet[str]
    """The districts in L1's read set that day (before any outcome)."""
    unknown: AbstractSet[str]
    """Read districts whose day label is unknown (dropped from scoring)."""
    calls: Sequence[Call]
    """Every call of the final timelines before D and of D."""
    record: WholeReads
    recent: Mapping[str, int]
    every_before: AbstractSet[str]
    """Districts a row of D-1's record named for every day."""
    served: AbstractSet[str]
    """Districts with a served frozen row the decline applies to (``s`` 1, ``pr``, no ``sa``)."""
    outcomes: Mapping[str, str] | None = None
    """Each source's last outcome in the live ledger (a dark list's cause); ``None``: the host
    holds none (the predict job's state export ships a schema-only ledger), and a dark
    district counts as ``dark (cause not on this host)``, never as one cause guessed."""
    gapped: AbstractSet[str] = frozenset()
    """Districts whose call on D was lit by a list after a reader gap."""


SEEDED: Final = (
    *(f"call {kind.value}" for kind in CallKind),
    "call lit after a gap",
    *(f"u {kind}" for kind in ("own", "market", "state", "none")),
    "standing *",
    "standing * read",
    "07:30 at_risk",
    "07:30 named",
    "07:30 at_risk dropped later",
    *(f"proven by {at}" for at in ("06:30", "07:30", "08:30", "09:30")),
    "voided",
)
"""The counts the line always shows, 0 or not."""
PROVEN_BY: Final = (390, 450, 510, 570)
"""06:30, 07:30, 08:30 and 09:30: the counts line's proven-by times."""
RISK_AT: Final = 450
"""07:30: the counts line's at-risk time."""


def day_counts(
    inputs: DayInputs,
    settings: CallSettings,
    rule: ReadRule,
    *,
    late: Callable[[], bool] | None = None,
) -> dict[str, int]:
    """One day's counts (no ids): calls by kind and lit after a gap; read-set districts of a
    class day by u kind; standing ``*`` districts and of them read; at risk at 07:30 (from
    the ``d0_0630`` rows ``served`` holds), named by then, dropped later; proven by 06:30,
    07:30, 08:30 and 09:30; voided; unproven by cause.

    Raises:
        TimeoutError: ``late()`` turned true between districts (the caller's limit).
    """
    found: Counter[str] = Counter(dict.fromkeys(SEEDED, 0))
    day = inputs.day
    directory = inputs.directory
    for call in inputs.calls:
        if call.day == day:
            found[f"call {call.kind.value}"] += 1
            found["call lit after a gap"] += call.leaid in inputs.gapped
    record = inputs.record
    market_of = inputs.morning.market_of
    audience = inputs.morning.audience
    positions = [
        i
        for i, leaid in enumerate(directory.districts)
        if leaid in inputs.read and serves(inputs.classes[i], settings)
    ]
    markets: dict[str, str | None] = {}

    def market(leaid: str) -> str | None:
        if leaid not in markets:
            markets[leaid] = market_on(
                leaid, day, record, inputs.coverage, inputs.stats,
                audience=audience, market_of=market_of, settings=settings,
            )  # fmt: skip
        return markets[leaid]

    usual = usual_calls(
        inputs.calls, market, district_state, settings, before=day,
        districts=[directory.districts[i] for i in positions],
    )  # fmt: skip
    for i in positions:
        leaid = directory.districts[i]
        u = usual.get(leaid)
        kind = "none" if u is None else "own" if u.own >= settings.own_min_calls else u.pool.value
        found[f"u {kind}"] += 1
    standing = {
        leaid
        for slot in inputs.morning.slots.values()
        for leaid, days in slot.named.items()
        if EVERY_DAY in days
    } | set(inputs.every_before)
    found["standing *"] = len(standing)
    found["standing * read"] = len(standing & set(inputs.read))
    called = {c.leaid: c.minute for c in inputs.calls if c.day == day}
    cuts = Cuts(inputs.morning, rule, inputs.stats, inputs.coverage.district_sites, settings)
    for i in positions:
        if late is not None and late():
            raise TimeoutError("past the counts line's limit")
        leaid = directory.districts[i]
        zone = directory.zones[i]
        named = first_named(inputs.morning, leaid, zone, inputs.every_before)
        risk = at_risk(
            RISK_AT, read=True, served=leaid in inputs.served, called=called.get(leaid),
            named=named,
        )  # fmt: skip
        found[f"07:30 {risk.value}"] += 1
        found["07:30 at_risk dropped later"] += risk is Risk.AT_RISK and leaid in inputs.unknown
        needed = required(
            leaid, day, record, inputs.coverage, inputs.stats, audience=audience,
            registry=market_of, settings=settings,
        )  # fmt: skip
        steps = proven(
            cuts, leaid, needed, zone=zone, storm=True,
            warning=inputs.classes[i] in WARNING_CLASSES, recent=inputs.recent,
            every_before=inputs.every_before,
        )  # fmt: skip
        by_end = {item.end: item for item in steps}
        for end in PROVEN_BY:
            item = by_end.get(end)
            if item is not None and item.ended is None and item.p_star is not None:
                found[f"proven by {end // 60:02d}:{end % 60:02d}"] += 1
        last = by_end.get(settings.slot_until)
        if last is None:
            continue
        if last.ended == "void":
            found["voided"] += 1
        elif last.ended == "named":
            found["unproven named"] += 1
        elif last.p_star is None:
            found[f"unproven {_cause(needed, inputs.outcomes)}"] += 1
    return dict(found)


def _cause(needed: Required, outcomes: Mapping[str, str] | None) -> str:
    """Why a district stayed unproven: no required list, its dark lists (every cause they
    show, joined by ``+`` in :class:`DarkCause` order, so each district counts once and no
    cause is lost), or a required list with no qualifying slot."""
    if not needed.sources:
        return "no list"
    if needed.dark:
        found = {
            dark_cause(None if outcomes is None else outcomes.get(s), known=outcomes is not None)
            for s in needed.dark
        }
        return "dark " + "+".join(cause.value for cause in DarkCause if cause in found)
    return "no qualifying slot"


def counts_line(day: date, counts: Mapping[str, int]) -> str:
    """The counts as one log line."""
    body = ", ".join(f"{key} {value}" for key, value in counts.items()) or "nothing to count"
    return f"call time (off) {day.isoformat()}: {body}"


__all__ = [
    "Call",
    "CallKind",
    "CallSettings",
    "Cuts",
    "DarkCause",
    "DayInputs",
    "Decline",
    "PoolKind",
    "Proof",
    "Required",
    "Risk",
    "SlotProof",
    "UsualCall",
    "applies",
    "at_risk",
    "called_minutes",
    "counts_line",
    "dark_cause",
    "day_counts",
    "decline",
    "delta",
    "market_on",
    "proof",
    "proven",
    "required",
    "serves",
    "usual_calls",
    "whole_reads",
    "with_decline",
]
