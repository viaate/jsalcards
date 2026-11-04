"""The live proof in each serving pass (predict-next LIVE-READS: shadow, nothing served).

CALL-TIME-2's decline may lower a chance only while every required list of the district was
read healthily (:func:`snowlight.predict.call_time.proof`). The predict job holds the live
reader's record only as the state export, written at the end of each live-read run, so a
serving pass would see a record up to 640 minutes old. This module gives each pass the
record as it stood minutes before:

* **The channel.** The live reader ships each changed morning day file in the idle time of
  every :00 and :30 UTC mark (:class:`snowlight.live.d1.MorningShipper`) to two tables of the
  private state database; this module reads them with SELECTs only
  (:class:`snowlight.live.d1.MorningReader`, :data:`snowlight.live.d1.MORNING_READS`).
* **The context** (:func:`build_context`), once a run per class morning D (a district of D
  advisory, warning or cold at its snapshot), in memory: read-labels' own proof inputs
  (:func:`snowlight.predict.read_cli.proof_inputs`) from the export, the coverage, the
  registry, the directory and the run's snapshots, and the population (each district of a
  term's class whose R is not empty, :func:`snowlight.predict.call_time.cases_of`). The
  export, the registry and the coverage are read only then (:class:`Setup`'s ``load``, once a
  run). Bounded: the build runs on a worker thread joined after :data:`CONTEXT_SECONDS`
  (:func:`bounded`), with its own :class:`Bound` checked between phases and before each
  host read; past it, on any error, or when the export gives no context (no live state, an
  empty population: :class:`NoContextError`), there is no context that run (``none``), and
  the build is not tried again. Only the quick no before anything is read (no class at D's
  snapshot) is asked again at the next mark. At the run's end a build still running is told
  to stop, waited for :data:`CLOSE_SECONDS`, and otherwise removes the unpacked folder
  itself when it ends.
* **The view** (:meth:`LiveReads.step`), once a pass: s is the latest :00 or :30 UTC mark at
  or before now less :data:`LAG`. One request reads D's and D-1's heads; a new version brings
  its parts, checked (count, sha256, gzip, the day file). D-1's record is the newer by
  ``through`` of the shipped head and the export's (the shipped one on a tie), and proves
  only when a record known final stands behind it (the head's own version shipped after
  00:00 UTC of D, or an export that records a pass of D). Then every district's proof is
  made from scratch by :func:`snowlight.predict.call_time.proofs_for` (the one
  implementation the counts line uses, so parity holds by construction), and each district
  takes the proof at its latest local slot end at or before s (10:00 held).
* **No proof is the safe side** (:class:`Code`): ``none`` (no class morning, or no context),
  ``missing`` (no head of D, or no D-1 record shipped or exported), ``stale`` (``through``
  before s, the slot before s absent, or D-1's record not known final), ``unreadable``
  (parts missing or failing their checks, after the previous version's; a D-1 head newer
  than the export's included), ``mismatched`` (another day, schema or directory, or
  ``through`` past now plus 2 minutes), ``d1`` (the database did not answer; 5 s a request)
  and ``late`` (past 10 s a pass). One line a run per code; never a raise.
* **Shadow only.** The view reaches no served value and no frozen key: one counts line per
  new (version, s), and digests (:func:`snowlight.predict.call_time.digest_at`) at 06:30,
  07:30, 08:30 and 09:30 local once s has passed them everywhere, with the context digest,
  to compare with read-labels' digest line.

Every line holds codes, counts, times and 12-hex digests: no ids, no names, no list text.
"""

import json
import logging
import threading
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Any, Final, Protocol
from zoneinfo import ZoneInfo

from snowlight.live.d1 import D1Error, MorningHead, unpack_morning
from snowlight.live.morning import READ_BAND, SCHEMA_VERSION, MorningDay, slot_of
from snowlight.live.morning import slot_start as record_slot_start
from snowlight.predict import call_time
from snowlight.predict.live_labels import (
    Directory,
    Morning,
    StationStats,
    named_every_day,
    named_for,
)
from snowlight.predict.live_read import Coverage, ReadRule

LOG: Final = logging.getLogger(__name__)

MARK: Final = timedelta(minutes=30)
LAG: Final = timedelta(minutes=15)
"""s is the latest :00 or :30 UTC mark at or before now less this: the version the live
reader shipped in that mark's idle time holds the slot before s."""
AHEAD: Final = timedelta(minutes=2)
"""A version whose ``through`` is past now by more than this is ``mismatched``."""
REQUEST_SECONDS: Final = 5.0
PASS_SECONDS: Final = 10.0
CONTEXT_SECONDS: Final = 90.0
CLOSE_SECONDS: Final = 5.0
"""How long the run's end waits for a context build still running past its bound (told to
stop at its next check); past it, the last build to end removes what the contexts left."""
VERSIONS_KEPT: Final = 4
LINE: Final = "live reads (off)"


class Code(StrEnum):
    """Why a pass holds no proof (the safe side: never a lowered chance)."""

    NONE = "none"
    MISSING = "missing"
    STALE = "stale"
    UNREADABLE = "unreadable"
    MISMATCHED = "mismatched"
    D1 = "d1"
    LATE = "late"


class Channel(Protocol):
    """The two morning tables, read only (:class:`snowlight.live.d1.MorningReader`)."""

    deadline: float | None

    def heads(self, days: Sequence[date]) -> dict[date, MorningHead]: ...

    def parts(self, sha: str, count: int | None) -> list[str] | None: ...


def midnight_of(day: date) -> datetime:
    """00:00 UTC of ``day``: D-1's record is final once a pass after it is recorded."""
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


EARLIEST: Final = datetime.min.replace(tzinfo=UTC)


def through_of(record: MorningDay | None) -> datetime:
    """A record's last pass (:data:`EARLIEST` for none)."""
    return EARLIEST if record is None or record.through is None else record.through


def mark_of(now: datetime) -> datetime:
    """s: the latest :00 or :30 UTC mark at or before ``now`` less :data:`LAG`."""
    at = (now - LAG).astimezone(UTC)
    return at.replace(minute=at.minute // 30 * 30, second=0, microsecond=0)


@dataclass(frozen=True, slots=True)
class Context:
    """What one class morning's proofs are made from besides D's record (once a run)."""

    day: date
    content: str
    """The directory content the population and classes are of."""
    settings: call_time.CallSettings
    rule: ReadRule
    coverage: Coverage
    inputs: Any
    """read-labels' :class:`~snowlight.predict.read_cli.ProofInputs` from the export."""
    cases: tuple[call_time.Case, ...]
    audience: Mapping[str, Mapping[str, date]]
    market_of: Mapping[str, str]
    station_stats: StationStats
    prefix: str
    before: MorningDay | None = None
    """D-1's record in the export (used when no newer D-1 was shipped)."""
    before_final: bool = False
    """The export's D-1 is final: the export records a pass after D-1 ended (its live-read
    run went past 00:00 UTC of D), so it holds every pass of D-1."""


class _NoProofError(Exception):
    def __init__(self, code: Code, note: str = "") -> None:
        super().__init__(code.value)
        self.code = code
        self.note = note


class NoContextError(Exception):
    """A context build that read the export and found no context to build: no live state
    reached this run, or an empty population (a class morning whose districts have no
    covered list). A final no for D that run (coded ``none``), never asked again."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class WorkerExitError(RuntimeError):
    """A context build ended by a ``BaseException`` that is not an ``Exception`` (a
    ``SystemExit`` on its worker thread): handed to the pass as an ``Exception`` so the view
    codes it ``none`` and the serving loop goes on (its line names the original type)."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


def named_before_of(before: MorningDay | None, day: date) -> dict[str, frozenset[str]]:
    """The districts D-1's record named for D, with the kinds
    (:func:`snowlight.predict.live_labels.named_for`, the one implementation the learning
    step's source and read-labels use)."""
    return named_for(before, day)


def every_before_of(before: MorningDay | None) -> frozenset[str]:
    """The districts a row of D-1's record named for every day
    (:func:`snowlight.predict.live_labels.named_every_day`, as read-labels reads them)."""
    return named_every_day(before.slots.values() if before is not None else ())


def morning_of(context: Context, record: MorningDay, before: MorningDay | None) -> Morning:
    """D's :class:`~snowlight.predict.live_labels.Morning` from a shipped version, as the
    learning step's source builds it from the state folder."""
    day = context.day
    return Morning(
        day=day,
        slots={record_slot_start(day, key): slot for key, slot in record.slots.items()},
        audience=context.audience,
        market_of=context.market_of,
        stats=context.station_stats,
        prefix=context.prefix,
        named_before=named_before_of(before, day),
    )


def view_proofs(
    context: Context,
    record: MorningDay,
    before: MorningDay | None,
    *,
    late: Callable[[], bool] | None = None,
) -> dict[str, list[call_time.SlotProof]]:
    """Every case's proof at every slot end on one version (``before``: D-1's record).

    Raises:
        TimeoutError: ``late()`` turned true between districts.
    """
    morning = morning_of(context, record, before)
    inputs = context.inputs
    cuts = call_time.Cuts(
        morning, context.rule, inputs.stats, context.coverage.district_sites, context.settings
    )
    return call_time.proofs_for(
        cuts, context.cases, recent=inputs.recent, every_before=every_before_of(before), late=late
    )


def end_at(day: date, end: int, zone: str) -> datetime:
    """The local slot end ``end`` (minutes) of ``day`` in ``zone``, in UTC."""
    local = datetime(day.year, day.month, day.day, end // 60, end % 60, tzinfo=ZoneInfo(zone))
    return local.astimezone(UTC)


def at_mark(
    steps: Sequence[call_time.SlotProof], day: date, zone: str, s: datetime
) -> call_time.SlotProof | None:
    """The proof at the district's latest local slot end at or before s (the held 10:00 row
    once s passes it); ``None`` before its first slot end."""
    found = None
    for item in steps:
        if end_at(day, item.end, zone) <= s:
            found = item
    return found


def _decoded(texts: list[str] | None, sha: str, day: date) -> MorningDay:
    """A version's day file from its parts.

    Raises:
        _NoProofError: ``unreadable`` (missing parts, a failed check) or ``mismatched``
            (another schema or day).
    """
    data = None if texts is None else unpack_morning(texts, sha)
    if data is None:
        raise _NoProofError(Code.UNREADABLE)
    try:
        schema = json.loads(data).get("schema_version")
    except (ValueError, AttributeError) as error:
        raise _NoProofError(Code.UNREADABLE) from error
    if schema != SCHEMA_VERSION:
        raise _NoProofError(Code.MISMATCHED)
    try:
        record = MorningDay.from_bytes(data)
    except ValueError as error:
        raise _NoProofError(Code.UNREADABLE) from error
    if record.day != day or record.damaged:
        raise _NoProofError(Code.MISMATCHED if record.day != day else Code.UNREADABLE)
    return record


@dataclass(slots=True)
class LiveReads:
    """The serving pass's live view (see the module); one per process."""

    channel: Channel | None
    """``None``: no channel (the Cloudflare secrets are missing): every pass is ``d1``."""
    context: Callable[[date], Context | None]
    """D's context, built once a run on a worker thread joined after
    :attr:`context_seconds` (``None``: not a class morning yet, asked again at the next
    mark; a raise or the bound: none this run)."""
    say: Callable[[str], None]
    monotonic: Callable[[], float] = time.monotonic
    context_seconds: float = CONTEXT_SECONDS
    cleanup: list[Callable[[], None]] = field(default_factory=list)
    """Run by :meth:`close` at the run's end (the unpacked export's folder), or by the last
    context build to end when one was still running then."""
    stop: threading.Event = field(default_factory=threading.Event)
    """Set by :meth:`close`: from then on every build's bound check raises (the same event
    as :attr:`Setup.stop`)."""
    _guard: threading.Condition = field(default_factory=threading.Condition)
    _live: int = 0
    """Context builds whose worker thread has not ended."""
    _deferred: bool = False
    """:meth:`close` left the cleanup to the last build to end."""
    _contexts: dict[date, Context | None] = field(default_factory=dict)
    _asked: dict[date, datetime] = field(default_factory=dict)
    _failed: dict[date, bool] = field(default_factory=dict)
    _versions: dict[str, MorningDay] = field(default_factory=dict)
    _proofs: dict[tuple[str, str], dict[str, list[call_time.SlotProof]]] = field(
        default_factory=dict
    )
    _printed: set[tuple[str, datetime]] = field(default_factory=set)
    _shown: tuple[date, datetime, dict[str, list[call_time.SlotProof]]] | None = None
    """The day, s and proofs of the last line printed (what ``history changed`` compares)."""
    codes: Counter[str] = field(default_factory=Counter)
    """The no-proof codes of this run's passes (each one's line printed once)."""
    seconds: list[float] = field(default_factory=list)
    """Each view's wall time (a context build's included)."""
    context_times: list[float] = field(default_factory=list)
    """Each context build's wall time (one that built a context, failed or ran past its
    bound)."""
    history_changed: int = 0
    """Districts whose proof at a slot end an earlier line had already reached changed with
    a later version (a slot rewritten after shipping: a clock that went back, a restart's
    successor, D-1's record changing)."""

    def step(self, now: datetime, content: str | None) -> dict[str, call_time.SlotProof] | None:
        """One pass's view at ``now`` for the directory ``content`` (``None``: unknown):
        each population district's proof at s, or ``None`` (no proof, coded and counted).
        It never raises."""
        began = self.monotonic()
        s = mark_of(now)
        if not READ_BAND[0] <= s.time() <= READ_BAND[1]:
            return None
        try:
            return self._step(now, s, content)
        except _NoProofError as error:
            self._code(error.code, s, error.note)
        except NoContextError as error:
            self._code(Code.NONE, s, f" ({error.reason})")
        except WorkerExitError as error:
            self._code(Code.NONE, s, f" ({error.name})")
        except Exception as error:  # the view never touches a pass
            self._code(Code.NONE, s, f" ({type(error).__name__})")
        finally:
            self.seconds.append(self.monotonic() - began)
        return None

    def close(self, wait: float = CLOSE_SECONDS) -> None:
        """The run's end: tell any build still running to stop, wait for it up to ``wait``
        seconds, then remove what the contexts left; a build still running past that removes
        it itself when it ends (so nothing it writes outlives the run). It never raises."""
        self.stop.set()
        with self._guard:
            self._guard.wait_for(lambda: self._live == 0, timeout=wait)
            if self._live:
                self._deferred = True
                LOG.warning("live reads: cleanup left to %d running build(s)", self._live)
                return
        self._clean()

    def _clean(self) -> None:
        while self.cleanup:
            try:
                self.cleanup.pop()()
            except Exception as error:  # a cleanup never changes the run's end
                LOG.warning("live reads: cleanup: %s", type(error).__name__)

    def _ended(self) -> None:
        """A build's worker thread ends (on that thread)."""
        with self._guard:
            self._live -= 1
            self._guard.notify_all()
            last = self._deferred and self._live == 0
            if last:
                self._deferred = False
        if last:
            self._clean()

    def _code(self, code: Code, s: datetime, note: str = "") -> None:
        self.codes[code.value] += 1
        if self.codes[code.value] == 1:
            self.say(f"{LINE} {s.date().isoformat()} {s:%H:%M}Z: no proof: {code.value}{note}")

    def _context(self, day: date, s: datetime) -> Context | None:
        """D's context: built once a run, bounded by :attr:`context_seconds`. ``None`` (not a
        class morning yet: the build's quick no before it reads anything) is asked again at
        the next mark; a build that read the export and found no context
        (:class:`NoContextError`), failed or ran past its bound is a final no that run, and
        each of those is counted in :attr:`context_times`."""
        found = self._contexts.get(day)
        if found is not None or (day in self._contexts and self._failed.get(day)):
            return found
        if self._asked.get(day) == s:
            return None
        self._asked[day] = s
        began = self.monotonic()
        with self._guard:
            self._live += 1
        try:
            self._contexts[day] = bounded(
                lambda: self.context(day), self.context_seconds, ended=self._ended
            )
        except Exception:
            self._contexts[day] = None
            self._failed[day] = True
            self.context_times.append(self.monotonic() - began)
            raise  # coded none by the step, with the reason or the error's type
        if self._contexts[day] is not None:  # a quiet day's quick no is not a build
            self.context_times.append(self.monotonic() - began)
        return self._contexts[day]

    def _step(
        self, now: datetime, s: datetime, content: str | None
    ) -> dict[str, call_time.SlotProof]:
        day = s.date()
        context = self._context(day, s)
        if context is None:
            raise _NoProofError(Code.NONE)
        if content is not None and content != context.content:
            raise _NoProofError(Code.MISMATCHED)
        if self.channel is None:
            raise _NoProofError(Code.D1)
        # the pass's own 10 s start after its context (built once a run, bounded apart)
        deadline = self.monotonic() + PASS_SECONDS
        self.channel.deadline = deadline

        def late() -> bool:
            return self.monotonic() > deadline

        version, record, before, before_key = self._read(context, now, s, late)
        if late():
            raise _NoProofError(Code.LATE)
        key = (version, before_key)
        if key not in self._proofs:
            try:
                self._proofs = {key: view_proofs(context, record, before, late=late)}
            except TimeoutError as error:
                raise _NoProofError(Code.LATE) from error
        proofs = self._proofs[key]
        zones = {case.leaid: case.zone for case in context.cases}
        found_at: dict[str, call_time.SlotProof] = {}
        for leaid, steps in proofs.items():
            item = at_mark(steps, day, zones[leaid], s)
            if item is not None:
                found_at[leaid] = item
        if (version, s) not in self._printed:
            self._printed.add((version, s))
            changed = self._changed(context, proofs)
            self.history_changed += changed
            self._shown = (day, s, proofs)
            self.say(self._line(context, version, record, s, proofs, found_at, before, changed))
        return found_at

    def _changed(
        self, context: Context, proofs: Mapping[str, Sequence[call_time.SlotProof]]
    ) -> int:
        """The districts whose proof at a slot end the last line had reached differs here."""
        if self._shown is None or self._shown[0] != context.day:
            return 0
        _day, shown_at, shown = self._shown
        zones = {case.leaid: case.zone for case in context.cases}

        def reached(leaid: str, steps: Sequence[call_time.SlotProof]) -> list[call_time.SlotProof]:
            return [i for i in steps if end_at(context.day, i.end, zones[leaid]) <= shown_at]

        return sum(
            reached(leaid, steps) != reached(leaid, proofs.get(leaid, ()))
            for leaid, steps in shown.items()
            if leaid in zones
        )

    def _read(
        self, context: Context, now: datetime, s: datetime, late: Callable[[], bool]
    ) -> tuple[str, MorningDay, MorningDay, str]:
        """The sha256 of D's version read (the head's, or the version before it when the
        head's parts are gone), that version, D-1's record (shipped, else the export's) and
        its key.

        Raises:
            _NoProofError: any no-proof code but ``none``.
        """
        channel = self.channel
        if channel is None:  # pragma: no cover - checked before
            raise _NoProofError(Code.D1)
        day = context.day
        yesterday = day - timedelta(days=1)
        try:
            heads = channel.heads([day, yesterday])
        except D1Error as error:
            raise _NoProofError(Code.LATE if late() else Code.D1) from error
        head = heads.get(day)
        if head is None:
            raise _NoProofError(Code.MISSING)
        if head.day != day or head.through > now + AHEAD:
            raise _NoProofError(Code.MISMATCHED)
        version, record = self._version(head, day, late)
        before_key, before = self._before(context, heads.get(yesterday), late)
        if record.through is None or record.through < s or slot_of(s - MARK) not in record.slots:
            raise _NoProofError(Code.STALE)
        return version, record, before, before_key

    def _before(
        self, context: Context, found: MorningHead | None, late: Callable[[], bool]
    ) -> tuple[str, MorningDay]:
        """D-1's record, chosen by its ``through`` (the newer of the shipped head and the
        export's, the shipped one on a tie), with its key (its sha256, or ``export``). A
        shipped head at least as new as the export's that does not read gives its own code,
        never the older export; the version before a head (a racing delete) is used only
        while it is at least as new as the export's.

        Raises:
            _NoProofError: ``missing`` (neither), ``stale`` (no candidate is known final:
                neither the head's own version shipped after D-1 ended nor an export that
                records a pass after it, so D-1's evening namings may be missing), or the
                head's ``unreadable``, ``mismatched``, ``d1`` or ``late``.
        """
        export = context.before
        candidates: list[tuple[datetime, bool, str, MorningDay]] = []
        if found is not None and (export is None or found.through >= through_of(export)):
            key, record = self._version(found, context.day - timedelta(days=1), late)
            shipped = found.shipped_at  # the head's own version, shipped after D-1 ended
            ended = shipped is not None and shipped >= midnight_of(context.day)
            final = key == found.sha256 and ended
            candidates.append((through_of(record), final, key, record))
        if export is not None:
            candidates.append((through_of(export), context.before_final, "export", export))
        if not candidates:
            raise _NoProofError(Code.MISSING)
        newest = max(candidates, key=lambda item: item[0])  # the first (shipped) on a tie
        if not any(item[1] for item in candidates):
            raise _NoProofError(Code.STALE, " (d-1 not final)")
        return newest[2], newest[3]

    def _version(
        self, head: MorningHead, day: date, late: Callable[[], bool]
    ) -> tuple[str, MorningDay]:
        """The version a head points at, as (its sha256, its record): the head's own when its
        parts read, else the version before it (a reader racing the shipper's delete), each
        decoded once and kept under its OWN sha256, so a later pass reads the head's parts
        again and a line names the version its proofs come from.

        Raises:
            _NoProofError: ``unreadable``, ``mismatched``, ``d1`` or ``late``.
        """
        if head.sha256 in self._versions:
            return head.sha256, self._versions[head.sha256]
        channel = self.channel
        if channel is None:  # pragma: no cover - checked before
            raise _NoProofError(Code.D1)
        try:
            texts = channel.parts(head.sha256, head.parts)
            sha = head.sha256
            if texts is None and head.prev_sha256 is not None:
                sha = head.prev_sha256
                texts = None if sha in self._versions else channel.parts(sha, None)
        except D1Error as error:
            raise _NoProofError(Code.LATE if late() else Code.D1) from error
        if sha in self._versions:
            return sha, self._versions[sha]
        record = _decoded(texts, sha, day)
        self._versions[sha] = record
        while len(self._versions) > VERSIONS_KEPT:
            self._versions.pop(next(iter(self._versions)))
        return sha, record

    def _line(  # noqa: PLR0913, PLR0917 - the pass's view and what it was made from
        self,
        context: Context,
        version: str,
        record: MorningDay,
        s: datetime,
        proofs: Mapping[str, Sequence[call_time.SlotProof]],
        found_at: Mapping[str, call_time.SlotProof],
        before: MorningDay | None,
        changed: int,
    ) -> str:
        counts: Counter[str] = Counter(dict.fromkeys(("proven", "unproven", "named", "void"), 0))
        for item in found_at.values():
            if item.ended is not None:
                counts[item.ended] += 1
            else:
                counts["proven" if item.p_star is not None else "unproven"] += 1
        counts["before first slot"] = len(proofs) - len(found_at)
        counts["history changed"] = changed
        inputs = context.inputs
        digest = call_time.context_digest(
            context.cases, recent=inputs.recent, every_before=every_before_of(before),
            stats=inputs.stats, station_stats=context.station_stats,
            named_before=named_before_of(before, context.day),
        )  # fmt: skip
        reached = [
            f"{end // 60:02d}:{end % 60:02d} {call_time.digest_at(proofs, end)}"
            for end in call_time.DIGEST_AT
            if all(end_at(context.day, end, case.zone) <= s for case in context.cases)
        ]
        body = ", ".join(f"{key} {value}" for key, value in counts.items())
        through = "--:--" if record.through is None else f"{record.through.astimezone(UTC):%H:%M}"
        return (
            f"{LINE} {context.day.isoformat()} {s:%H:%M}Z: version {version[:12]} "
            f"(through {through}Z), {len(proofs)} districts: {body}; context {digest}"
            + "".join(f", {item}" for item in reached)
        )

    def summary(self) -> str:
        """The run's counts: views, codes, history changed, the slowest view and each
        context build (seconds)."""
        codes = ", ".join(f"{code} {count}" for code, count in sorted(self.codes.items()))
        slowest = max(self.seconds, default=0.0)
        built = ", ".join(f"{taken:.2f}" for taken in self.context_times) or "none"
        return (
            f"{LINE}: {len(self.seconds)} views, {len(self._printed)} lines"
            f"{'; no proof ' + codes if codes else ''}; history changed "
            f"{self.history_changed}; slowest {slowest:.2f} s; context {built} s"
        )


def bounded[T](
    call: Callable[[], T], seconds: float, *, ended: Callable[[], None] | None = None
) -> T:
    """``call()`` on a worker thread joined after ``seconds`` (a daemon: a build past its
    bound is left to end at its next check, and the pass goes on); ``ended()`` runs on the
    worker as it ends, whenever that is (or here, when the worker never started).

    Raises:
        TimeoutError: past ``seconds``.
        WorkerExitError: ``call`` raised a ``BaseException`` that is not an ``Exception``.
        Exception: whatever ``call`` raised.
    """
    box: dict[str, Any] = {}

    def work() -> None:
        try:
            box["value"] = call()
        except Exception as error:  # handed to the caller
            box["error"] = error
        except BaseException as error:  # never past the caller's Exception handlers
            box["error"] = WorkerExitError(type(error).__name__)
        finally:
            if ended is not None:
                ended()

    worker = threading.Thread(target=work, name="live-reads-context", daemon=True)
    try:
        worker.start()
    except BaseException:
        if ended is not None:
            ended()
        raise
    worker.join(seconds)
    if worker.is_alive():
        raise TimeoutError(f"past {seconds:.0f} s")
    if "error" in box:
        raise box["error"]
    return box["value"]  # type: ignore[no-any-return]


# --- the context ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Loaded:
    """The export and L1's coverage, read when a run's first class-morning context is built
    (never before the run's first serving pass, never on a quiet day)."""

    source: Any
    """The export's :class:`~snowlight.predict.live_read.StateReadSource` (``None``: no live
    state reached this run: no context)."""
    coverage: Coverage


@dataclass(slots=True)
class Once[T]:
    """``make()`` once: its value, or the error it raised, every later call."""

    make: Callable[[], T]
    _value: T | None = None
    _error: Exception | None = None
    _done: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __call__(self) -> T:
        with self._lock:
            if not self._done:
                try:
                    self._value = self.make()
                except Exception as error:
                    self._error = error
                self._done = True
            if self._error is not None:
                raise self._error
            return self._value  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class Bound:
    """One context build's own deadline on the monotonic clock (a later build never moves
    it), asked between the build's phases and before each of its host reads (the Pages
    copy's day timelines, :func:`check_bound`): a read never starts past it, nor after the
    run's end."""

    monotonic: Callable[[], float] = time.monotonic
    until: float | None = None
    stop: threading.Event | None = None
    """The run's end (:attr:`LiveReads.stop`)."""

    def check(self) -> None:
        """Raises:
        TimeoutError: past the deadline, or the run has ended."""
        if self.stop is not None and self.stop.is_set():
            raise TimeoutError("the run has ended")
        if self.until is not None and self.monotonic() > self.until:
            raise TimeoutError("past the context's bound")


_CURRENT: Final = threading.local()
"""The bound of the build running on this thread (each build has its own thread)."""


def check_bound() -> None:
    """The bound check of the context build running on this thread (nothing outside one).

    Raises:
        TimeoutError: past that build's deadline, or the run has ended.
    """
    found: Bound | None = getattr(_CURRENT, "bound", None)
    if found is not None:
        found.check()


@dataclass(frozen=True, slots=True)
class Setup:
    """What a run's contexts are built from."""

    config: Any
    """The run's :class:`~snowlight.predict.config.PredictConfig`."""
    load: Callable[[], Loaded]
    """The export and the coverage (:class:`Once`: read at the first class morning; a raise:
    no context, coded ``none``)."""
    directory: Callable[[], Directory | None]
    """The pass's directory as the labels need it (``None``: no model built yet)."""
    snapshots: Callable[[], Mapping[str, object]]
    """The run's class snapshots, as they stand (the pass records them)."""
    stop: threading.Event | None = None
    """The run's end (:attr:`LiveReads.stop`): a build still running stops at its next
    check."""


def build_context(
    setup: Setup, day: date, *, monotonic: Callable[[], float] = time.monotonic
) -> Context | None:
    """D's context (see the module), or ``None`` (not a class morning yet: no directory, or
    no district of a term's class at D's snapshot; nothing is read, and the view asks again
    at the next mark).

    Raises:
        NoContextError: the export was read and gives no context (no live state, an empty
            population): a final no for D that run.
        TimeoutError: past :data:`CONTEXT_SECONDS` (the build's own :class:`Bound`, checked
            between phases and before each host read; the view also joins the build's
            thread after that long), or the run ended.
        Exception: whatever the export's reading raises (the caller codes it ``none``).
    """
    bound = Bound(monotonic, monotonic() + CONTEXT_SECONDS, setup.stop)
    _CURRENT.bound = bound
    try:
        return _build(setup, day, bound)
    finally:
        _CURRENT.bound = None


def _build(setup: Setup, day: date, bound: Bound) -> Context | None:
    from snowlight.live.morning import MorningLog  # noqa: PLC0415
    from snowlight.predict import live_read, read_cli  # noqa: PLC0415
    from snowlight.predict.live_labels import station_stats  # noqa: PLC0415
    from snowlight.predict.situations import Window  # noqa: PLC0415

    directory = setup.directory()
    if directory is None:
        return None
    config = setup.config
    settings = call_time.CallSettings.of(config)
    snapshots = setup.snapshots()
    classes = read_cli.classes_on(config, snapshots, directory, day)
    if not any(call_time.serves(klass, settings) for klass in classes):
        return None  # a quiet day: nothing is unpacked or read
    bound.check()
    loaded = setup.load()
    source = loaded.source
    if source is None:
        raise NoContextError("no live state")
    bound.check()
    rule = ReadRule.of(config)
    weather = config.weather
    closing = live_read.closing_of(
        rule, loaded.coverage, snapshots, directory,
        window=Window(weather.window_from, weather.window_until, weather.snapshot_hour),
        slack=timedelta(minutes=config.learn.snapshot_slack_minutes), timeline=source.timeline,
    )  # fmt: skip
    state = source.state
    prefix = state.prefix
    inputs = read_cli.proof_inputs(
        source, day, config=config, directory=directory, coverage=loaded.coverage,
        snapshots=snapshots, closing=closing, prefix=prefix,
    )  # fmt: skip
    bound.check()
    audience = live_read.audience_before(source._log(), day, config.labels.audience_days)
    log = MorningLog(state.folder / "morning")
    stats = station_stats(found for when in log.days() if (found := log.day(when)) is not None)
    cases = call_time.cases_of(
        day, directory, inputs.classes, record=inputs.record, coverage=loaded.coverage,
        stats=inputs.stats, audience=audience, registry=state.market_of, settings=settings,
    )  # fmt: skip
    if not cases:
        raise NoContextError("no population")
    bound.check()
    return Context(
        day=day,
        content=directory.content,
        settings=settings,
        rule=rule,
        coverage=loaded.coverage,
        inputs=inputs,
        cases=tuple(cases),
        audience=audience,
        market_of=state.market_of,
        station_stats=stats,
        prefix=prefix,
        before=log.day(day - timedelta(days=1)),
        before_final=(through := log.through()) is not None and through >= midnight_of(day),
    )


__all__ = [
    "Bound",
    "Channel",
    "Code",
    "Context",
    "LiveReads",
    "Loaded",
    "NoContextError",
    "Once",
    "Setup",
    "WorkerExitError",
    "at_mark",
    "bounded",
    "build_context",
    "check_bound",
    "mark_of",
    "view_proofs",
]
