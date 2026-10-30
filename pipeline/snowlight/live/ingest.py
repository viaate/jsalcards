"""One live pass, wired: reads into the ledger, every source resolved, merged, gated, published.

:meth:`Ingest.run_pass` takes the reads the fetch layer made this pass
(:class:`SourceRead`: an outcome, a time and the rows, in memory only) and:

1. folds each read into the ledger (:meth:`~snowlight.live.ledger.Ledger.observe`); a
   good read's rows become that source's present rows for this process;
2. resolves **every** source the ledger knows, not only those read this pass, so a
   retraction or an open statement keeps darkening. A source no longer in the
   registry is resolved as a station that is not active: it lights nothing, and what
   its rows last said still darkens (``TERMS``);
3. holds a source's statuses (G13) only while its last good read is recent **and** it
   was read in this process: a source not yet read since a start has no present rows,
   so it gives only its dissents;
4. withholds every status and open statement in the states of a source whose say is
   unknown this pass (``source_unknown``): one whose read could not be taken in or
   whose resolve failed (its dissents are missing), or one due for reading holding a
   row first seen in the last 36 hours that was never derived (a pass cut off between
   reading and resolving: it may be a retraction, and it reads only when the source is
   read again). A source not due (no longer listed, not active, or not pollable) is
   never read again; its never-derived rows are left out and expire. Two passes in a
   row with such a source raise the alert;
5. merges, checks the directory handshake against the stamps the public files carry
   (read back from the host), and publishes through the gate
   (:class:`~snowlight.live.publish.LivePublisher`), with the share of the sources
   due (the registry's active, pollable stations) whose latest read in the last 15
   minutes was healthy (G12b; both windows counted from the passes' starts);
6. queues the listings the matcher did not accept (private) and writes
   ``health.json``: counts, codes and source ids only (a failed write is logged by its
   type and leaves the pass's exit as it was);
7. adds the pass to the morning record (:mod:`snowlight.live.morning`, for the automatic
   learning): whether the map showed it, its whole reads, the states it withheld and the
   districts its rows name. A failed write is logged by its type and changes nothing else.

The pass's time is the caller's clock **after** the reads (and never earlier than any
read's ``fetched_at``): ``generated_at`` is never older than the data it carries, and
a source read this pass is held. An error in one source's resolve is counted and logged
with the source id and the error's type only, and the pass goes on.

The fetch layer (S8-B's pool and cadence) makes the reads; :class:`SourceRead` is the
whole of what it hands over.
"""

import json
import logging
from collections import Counter, deque
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

from snowlight.listed.matching import Query
from snowlight.live.edition import EditionState, EditionVerdict, EditionWatch
from snowlight.live.guards import Refusal, Rules, held
from snowlight.live.ledger import GOOD, LONGEST, Ledger, SeenRow
from snowlight.live.ledger import Outcome as ReadOutcome
from snowlight.live.merge import AdminStatus, Merged, merge, with_overrides
from snowlight.live.morning import MorningLog, named_of, pass_reads
from snowlight.live.publish import AdminPart, Exit, LivePublisher, PassReport, PassSummary
from snowlight.live.resolve import LiveDirectory, Resolved, Resolver
from snowlight.output import JSONValue, write_json
from snowlight.sources.stations.registry import Station, StationStatus

LOG: Final = logging.getLogger(__name__)
HEALTH_WINDOW: Final = timedelta(minutes=15)
"""G12b counts the sources due in the last 15 minutes."""
OWN_READS_MIN: Final = 10
"""A pass that read at least this many sources also counts its own reads alone in G12b
(:meth:`Ingest.gate_share`): an outage that starts at a pass is refused at that pass, while
the window still holds the reads of the passes before it. (Each of the 1261 uploaded passes
of Oct 25-29 with 10 reads or more had 84% or more of them good.) A broad degradation that
keeps a pass's own reads under 60% so refuses every pass, not only the passes whose window
holds no good sweep (docs/live.md, Health share)."""
FALLBACK_ZONE: Final = "America/Chicago"
EDITION_EVERY: Final = timedelta(seconds=60)
"""How often the directory handshake runs, between passes and while the reads run."""
UNKNOWN: Final = "source_unknown"
"""Withheld: a source whose say is unknown this pass covers the school's state."""
UNKNOWN_TO_ALERT: Final = 2
"""Passes in a row with a source whose say is unknown before the alert."""


@dataclass(frozen=True, slots=True)
class SourceRead:
    """One read of one source, as the fetch layer hands it over (rows in memory only)."""

    source_id: str
    outcome: ReadOutcome
    fetched_at: datetime
    rows: tuple[SeenRow, ...] = field(default=(), repr=False)


def orphan_station(source_id: str) -> Station:
    """A source the ledger knows and the registry no longer lists: not active, so it lights
    nothing and keeps only the darkening part of what its rows last said."""
    platform = source_id.rsplit("-", 1)[0] if "-" in source_id else source_id
    body: dict[str, object] = {
        "id": source_id,
        "platform": platform,
        "call_sign": "GONE",
        "name": "removed source",
        "market": "removed",
        "dma": None,
        "states": ["DC"],
        "counties": None,
        "page_url": None,
        "data_url": None,
        "archive_urls": [],
        "poll_minutes": None,
        "status": "no_endpoint",
        "evidence": "removed from the registry",
    }
    return Station.model_validate_json(json.dumps(body))


def station_zone(station: Station, directory: LiveDirectory) -> str:
    """The zone most of the station's counties' schools are in (for a row stamp with none)."""
    fips = set(station.counties.fips) if station.counties is not None else set()
    found = Counter(
        school.zones[0]
        for school in directory.schools.values()
        if school.zones and school.record.county_fips in fips
    )
    ranked = sorted(found.items(), key=lambda item: (-item[1], item[0]))
    return ranked[0][0] if ranked else FALLBACK_ZONE


def _never(_school: int) -> bool:
    return False


def _boosted(_station: Station, _now: datetime) -> bool:
    return True


def _always(_school: int) -> bool:
    return True


EMPTY_MERGED: Final = Merged(
    closings=(), opens=(), provenance=(), withheld={}, breakers=(), fast_vanishes=()
)
"""No list statuses (an overrides-only pass)."""


def withhold_states(
    merged: Merged, states: Collection[str], directory: LiveDirectory
) -> tuple[Merged, int]:
    """``merged`` without any status or open statement of a school in ``states``; returns it
    and how many statuses went."""
    if not states:
        return merged, 0

    def covered(nces_id: object) -> bool:
        school = directory.schools.get(str(nces_id))
        return school is None or school.record.state in states

    kept = [
        (closing, line)
        for closing, line in zip(merged.closings, merged.provenance, strict=True)
        if not covered(line.get("nces_id"))
    ]
    gone = len(merged.closings) - len(kept)
    withheld = dict(merged.withheld)
    if gone:
        withheld[UNKNOWN] = withheld.get(UNKNOWN, 0) + gone
    return (
        replace(
            merged,
            closings=tuple(closing for closing, _ in kept),
            provenance=tuple(line for _, line in kept),
            opens=tuple(signal for signal in merged.opens if not covered(signal.nces_id)),
            withheld=withheld,
        ),
        gone,
    )


@dataclass(slots=True)
class Ingest:
    """The live pass (see the module). One per process: the ledger and resolver load once."""

    ledger: Ledger
    resolver: Resolver
    stations: Mapping[str, Station]
    publisher: LivePublisher
    watch: EditionWatch
    internal_dir: Path
    rules: Rules = field(default_factory=Rules)
    boosted: Callable[[Station, datetime], bool] = _boosted
    """Whether a station is in a reading window or an alert (S8-B's cadence); the hold is
    then the shorter one. Until the cadence is wired every station counts as boosted."""
    alerted: Callable[[int], bool] = _never
    """Whether a school's county has an active alert (the spike hold, G12e)."""
    queue: Callable[[Sequence[Query], datetime], None] | None = None
    """Keeps the listings the matcher did not accept (the private queue)."""
    due: frozenset[str] | None = None
    """The sources due each pass (G12b counts over them); ``None``: the active stations.
    S8-B's cadence replaces it."""
    present: dict[str, tuple[SeenRow, ...]] = field(default_factory=dict)
    recent: deque[tuple[datetime, str, bool]] = field(default_factory=deque)
    failed: set[str] = field(default_factory=set)
    """Sources whose read could not be taken in, or whose resolve failed, this pass."""
    unknown_streak: int = 0
    """Passes in a row with a source whose say was unknown."""
    checked_at: datetime | None = None
    """When the directory handshake last ran."""
    last_verdict: EditionVerdict | None = None
    morning: MorningLog | None = None
    """The morning record (:mod:`snowlight.live.morning`); ``None`` keeps none."""
    taken: set[str] = field(default_factory=set)
    """Sources the ledger took a whole read of this pass (ok, not_modified or empty)."""
    overrides: Callable[[datetime], Sequence[AdminStatus]] | None = None
    """The admin's statuses at a moment (the API read each pass, S8-E); an error refuses
    the pass. ``None``: none are applied (tests, ``off``)."""
    run_id: str = "-"
    """This run's id, for the upload's commit message."""
    state_bytes: int = 0
    """The packed state's size at the last push, for the commit message."""
    last_outcomes: dict[str, tuple[bool, bool]] = field(default_factory=dict)
    """Each source read in the last pass: whether it erred, and whether it was in a reading
    window or an alert (the ``source`` alert's digest)."""
    beat: Callable[[], None] = field(default=lambda: None)
    """Called per read folded into the ledger and per source resolved (the loop's pulse, so
    a pass's resolve shows progress to the watcher; a hang inside one stops it)."""

    def observe(self, reads: Iterable[SourceRead], at: datetime | None = None) -> Counter[str]:
        """Fold reads into the ledger; returns the outcomes as the ledger took them. ``at`` is
        the pass's start: G12b keeps each read under it (else under the read's own time), the
        moment the cadence counts the source due at, so the two windows are one."""
        outcomes: Counter[str] = Counter()
        self.failed = set()
        self.taken = set()
        for read in reads:
            self.beat()
            try:
                observed = self.ledger.observe(
                    read.source_id, read.outcome, read.fetched_at, read.rows
                )
            except Exception as error:
                LOG.error("observe %s: %s", read.source_id, type(error).__name__)
                outcomes["error"] += 1
                self.failed.add(read.source_id)
                self.present.pop(read.source_id, None)
                self.recent.append((at or read.fetched_at, read.source_id, False))
                continue
            outcomes[observed.outcome.value] += 1
            if observed.outcome in GOOD:
                self.taken.add(read.source_id)
            confirmed = read.outcome is ReadOutcome.NOT_MODIFIED and not read.rows
            if observed.outcome in GOOD and not confirmed:
                self.present[read.source_id] = read.rows
            # A "not modified" with no rows confirms the body this process last read; one
            # this process never read leaves the source unheld (dissents only) until a
            # full read (the fetch layer's first read after a start is a full GET).
            self.recent.append((at or read.fetched_at, read.source_id, observed.outcome in GOOD))
        return outcomes

    def due_sources(self) -> frozenset[str]:
        if self.due is not None:
            return self.due
        return frozenset(
            source_id
            for source_id, station in self.stations.items()
            if station.status is StationStatus.ACTIVE
        )

    def healthy_share(self, now: datetime) -> float:
        """The share of the sources due whose latest read in the last 15 minutes was good (a
        due source not read in that time counts as not healthy).

        ``now`` is the pass's start in the loop: the reads are kept under their pass's start
        (:meth:`observe`) and the cadence counts a source due from the start of the pass that
        picked it, so a source due in the window always has its read of that pass in it. (Its
        read's own time against the clock after the reads, as before S3, dropped the
        half-hour sweep's reads 15 minutes on while their sources still counted due: every
        :10 and :40 pass dipped under 60% and was refused.)"""
        while self.recent and now - self.recent[0][0] > HEALTH_WINDOW:
            self.recent.popleft()
        latest: dict[str, bool] = {}
        for _, source_id, good in self.recent:
            latest[source_id] = good
        due = self.due_sources()
        return sum(latest.get(source_id, False) for source_id in due) / len(due) if due else 0.0

    def gate_share(self, reads: Sequence[SourceRead], now: datetime) -> float:
        """The share G12b gates on: :meth:`healthy_share` at ``now`` (the pass's start), and
        no more than the share of this pass's own reads that were good when it read at
        least :data:`OWN_READS_MIN` sources. A pass whose every read fails is so refused at
        once, not only once the window holds nothing but failing reads (up to two passes
        later after the half-hourly sweep)."""
        share = self.healthy_share(now)
        if len(reads) >= OWN_READS_MIN:
            share = min(share, sum(read.outcome in GOOD for read in reads) / len(reads))
        return share

    def holding(self) -> frozenset[str]:
        """The sources whose last good read held rows: their statuses stand only once this
        process has read them again (:meth:`held`), so a new run reads them first."""
        return frozenset(
            state.source_id
            for state in self.ledger.sources()
            if state.rows_last > 0 and state.last_good_at is not None
        )

    def resolve(self) -> list[Resolved]:
        """Every source the ledger knows, resolved against its present rows. A source whose
        resolve raises is left out and named in :attr:`failed` (its id and the error's type
        are logged, never its message)."""
        known = {state.source_id for state in self.ledger.sources()}
        resolved = []
        for source_id in sorted(known):
            self.beat()
            station = self.stations.get(source_id) or orphan_station(source_id)
            try:
                resolved.append(self.resolver.resolve(station, self.present.get(source_id, ())))
            except Exception as error:
                LOG.error("resolve %s: %s", source_id, type(error).__name__)
                self.failed.add(source_id)
        return resolved

    def undecided(self, now: datetime) -> dict[str, int]:
        """Per source due for reading and not read in this process, its present rows never
        derived and first seen in the last 36 hours: what they say cannot be known until the
        source is read again. A source not due (no longer listed, not active, not pollable)
        is never read again: left out."""
        found: dict[str, int] = {}
        for state in self.ledger.sources():
            station = self.stations.get(state.source_id)
            if (
                state.source_id in self.present
                or station is None
                or station.status is not StationStatus.ACTIVE
                or not self.resolver.pollable.get(station.platform, False)
            ):
                continue
            count = sum(
                1
                for entry in self.ledger.rows(state.source_id, include_gone=False)
                if entry.absent_since is None
                and now - entry.hi <= LONGEST
                and self.ledger.last_derived(entry.key) is None
            )
            if count:
                found[state.source_id] = count
        return found

    def unknown_states(self, now: datetime) -> frozenset[str]:
        """The states of the sources whose say is unknown this pass (failed or undecided)."""
        sources = self.failed | set(self.undecided(now))
        return frozenset(
            state
            for source_id in sources
            if (station := self.stations.get(source_id)) is not None
            for state in station.states
        )

    def check_edition(self, now: datetime) -> EditionVerdict:
        """The directory handshake against the stamps the public files carry. Other content
        deployed that is the content of the last upload is this run's code ahead of the
        deploy: no blank (the run waits for the deploy)."""
        stamps, complete = self.publisher.public_stamps()
        verdict = self.watch.check(now, published=stamps, complete=complete)
        if verdict.state is EditionState.DIFFERENT and self.publisher.ahead_of(verdict):
            verdict = replace(
                verdict,
                blank=None,
                blank_every=False,
                ahead=True,
                alert=False,
                note="this run's directory is ahead of the deploy",
            )
        self.checked_at, self.last_verdict = now, verdict
        return verdict

    def guard(self, now: datetime) -> tuple[EditionVerdict, PassReport | None]:
        """The directory handshake; a verdict that names a blank publishes it at once (its
        report is returned: refused, or an error when the host failed, with the alert)."""
        verdict = self.check_edition(now)
        if not verdict.wants_blank:
            return verdict, None
        report = self.publisher.edition_blank(verdict, now=now)
        LOG.warning(
            "edition %s: blank %s",
            verdict.state.value,
            "published" if report.blank else f"failed (exit {int(report.exit)})",
        )
        return verdict, report

    def record_check(
        self, now: datetime, verdict: EditionVerdict, report: PassReport | None
    ) -> None:
        """Record a handshake made between passes that raised the alert or published a
        blank in ``health.json`` (``check``: its time, verdict, alert and the blank's
        report), keeping the last pass's health beside it. A failed write is logged by its
        type."""
        path = self.internal_dir / "health.json"
        try:
            found = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except (OSError, ValueError) as error:
            LOG.warning("health.json: %s", type(error).__name__)
            found = {}
        doc: dict[str, JSONValue] = found if isinstance(found, dict) else {}
        doc["check"] = {
            "at": now.astimezone(UTC).isoformat(),
            "edition": verdict.state.value,
            "alert": verdict.alert or (report is not None and report.alert),
            "note": verdict.note,
            "gate": None if report is None else report.to_json(),
        }
        try:
            write_json(path, doc)
        except OSError as error:
            LOG.error("health.json: %s", type(error).__name__)

    def tick(self, now: datetime) -> None:
        """While the reads run: the handshake once a minute (a deploy is caught mid-pass). An
        error is logged by its type and the reads go on: the pass checks again before it
        publishes."""
        if self.checked_at is None or now - self.checked_at >= EDITION_EVERY:
            try:
                verdict, report = self.guard(now)
                if report is not None or verdict.alert:
                    self.record_check(now, verdict, report)
            except Exception as error:
                LOG.error("edition check failed: %s", type(error).__name__)
                self.checked_at = now

    def held(self, now: datetime) -> dict[str, bool]:
        """G13 per source, and only for sources read in this process."""
        found: dict[str, bool] = {}
        for state in self.ledger.sources():
            station = self.stations.get(state.source_id)
            found[state.source_id] = (
                station is not None
                and state.source_id in self.present
                and held(
                    state.last_good_at, now, boosted=self.boosted(station, now), rules=self.rules
                )
            )
        return found

    def record_morning(
        self,
        now: datetime,
        resolved: Sequence[Resolved],
        unknown: Collection[str],
        report: PassReport,
    ) -> None:
        """Add this pass to the morning record (a failed write is logged by its type)."""
        if self.morning is None:
            return
        prefix = self.publisher.prefix
        try:
            self.morning.record(
                now,
                shown=prefix if prefix is not None and shown(report) else None,
                reads=pass_reads(self.taken - self.failed, resolved),
                unknown=unknown,
                named=named_of(resolved),
            )
        except (OSError, ValueError) as error:
            LOG.error("morning record: %s", type(error).__name__)

    def _publish(  # noqa: PLR0913 - one pass's parts
        self,
        merged: Merged,
        now: datetime,
        share: float,
        edition: EditionVerdict,
        *,
        started: datetime | None,
        always: bool,
    ) -> PassReport:
        """The admin's statuses on top (an API error refuses the pass), then the gate."""
        admin = None
        if self.overrides is not None:
            try:
                statuses = self.overrides(now)
                merged = with_overrides(
                    merged, statuses, now.astimezone(UTC).replace(microsecond=0)
                )
            except Exception as error:
                LOG.error("overrides: %s", type(error).__name__)
                return self.publisher.refuse_pass((Refusal.OVERRIDES.value,), now)
            admin = _admin_part(statuses)
        try:
            return self.publisher.publish(
                merged,
                now=now,
                healthy_share=share,
                edition=edition,
                alerted=self.alerted,
                started=started,
                always=always,
                admin=admin,
            )
        except OSError as error:
            LOG.error("publish: %s", type(error).__name__)
            return PassReport(Exit.ERROR, now, note=f"publish: {type(error).__name__}")

    def source_outcomes(
        self, reads: Sequence[SourceRead], now: datetime
    ) -> dict[str, tuple[bool, bool]]:
        """Each source read: whether it erred, and whether it was in a window or an alert."""
        found: dict[str, tuple[bool, bool]] = {}
        for read in reads:
            station = self.stations.get(read.source_id)
            boosted = station is not None and self.boosted(station, now)
            found[read.source_id] = (read.outcome is ReadOutcome.ERROR, boosted)
        return found

    def overrides_pass(self, now: datetime, *, always: bool = False) -> PassReport:
        """A pass of an overrides-only run (the state could not be pulled): no list is read,
        and the admin's statuses are published alone, as a blank skips health and the spike
        hold (the list rows go dark, never wrong). An API error refuses it."""
        edition = self.check_edition(now)
        statuses: Sequence[AdminStatus] = ()
        if self.overrides is not None:
            try:
                statuses = self.overrides(now)
            except Exception as error:
                LOG.error("overrides: %s", type(error).__name__)
                return self.publisher.refuse_pass((Refusal.OVERRIDES.value,), now)
        whole = now.astimezone(UTC).replace(microsecond=0)
        merged = with_overrides(EMPTY_MERGED, statuses, whole)
        self.publisher.summary = PassSummary(
            start=now, run_id=self.run_id, sweep_seconds=0.0, due=0, good=0, state_bytes=0
        )
        try:
            return self.publisher.publish(
                merged,
                now=now,
                healthy_share=1.0,
                edition=edition,
                alerted=_always,
                started=now,
                always=always,
            )
        except OSError as error:
            LOG.error("publish: %s", type(error).__name__)
            return PassReport(Exit.ERROR, now, note=f"publish: {type(error).__name__}")

    def run_pass(
        self,
        reads: Sequence[SourceRead],
        now: datetime,
        *,
        started: datetime | None = None,
        always: bool = False,
    ) -> PassReport:
        """One pass: observe, resolve, merge, gate, publish, record (see the module). ``now``
        is the clock after the reads; a read stamped later moves it to that read.
        ``started`` is when the pass began, before its reads (the heartbeat's grid);
        ``always``: upload even when nothing changed (a grid pass, ``live once``)."""
        now = max([now, *(read.fetched_at for read in reads)])
        outcomes = self.observe(reads, at=started)
        self.last_outcomes = self.source_outcomes(reads, now)
        resolved = self.resolve()
        directory = self.resolver.directory
        merged = merge(
            resolved,
            held=self.held(now),
            directory=directory,
            generated_at=now,
            rules=self.rules,
        )
        unknown = self.unknown_states(now)
        merged, _ = withhold_states(merged, unknown, directory)
        unmatched = [query for source in resolved for query in source.unmatched]
        if self.queue is not None and unmatched:
            self.queue(unmatched, now)
        share = self.gate_share(reads, now if started is None else started)
        edition = self.check_edition(now)
        began = now if started is None else started
        self.publisher.summary = PassSummary(
            start=began,
            run_id=self.run_id,
            sweep_seconds=max(0.0, (now - began).total_seconds()),
            due=len(reads),
            good=sum(1 for read in reads if read.outcome in GOOD),
            state_bytes=self.state_bytes,
        )
        report = self._publish(merged, now, share, edition, started=started, always=always)
        self.unknown_streak = self.unknown_streak + 1 if unknown or self.failed else 0
        report = replace(
            report,
            edition=edition.state.value,
            alert=report.alert or self.unknown_streak >= UNKNOWN_TO_ALERT,
            counts={**report.counts, "failed": len(self.failed), "unknown_states": len(unknown)},
        )
        try:
            write_json(
                self.internal_dir / "health.json",
                health(
                    now=now,
                    outcomes=outcomes,
                    share=share,
                    resolved=resolved,
                    merged=merged,
                    report=report,
                    edition=edition.state.value,
                ),
            )
        except OSError as error:
            LOG.error("health.json: %s", type(error).__name__)
        self.record_morning(now, resolved, unknown, report)
        LOG.info(
            "pass: %d reads, healthy share %.2f, %d statuses, exit %d",
            len(reads),
            share,
            len(merged.closings),
            int(report.exit),
        )
        return report


def _admin_part(statuses: Sequence[AdminStatus]) -> AdminPart:
    return AdminPart(tuple(statuses))


def shown(report: PassReport) -> bool:
    """Whether the map shows this pass's merge: it uploaded, or found it unchanged inside the
    heartbeat (never a refused, held, blanked or failed pass, nor publishing off)."""
    return (
        report.exit is Exit.OK
        and not report.refusals
        and not report.blank
        and (bool(report.uploaded) or report.note == "unchanged")
    )


def health(  # noqa: PLR0913 - one pass's parts
    *,
    now: datetime,
    outcomes: Mapping[str, int],
    share: float,
    resolved: Sequence[Resolved],
    merged: Merged,
    report: PassReport,
    edition: str,
) -> dict[str, JSONValue]:
    """The pass's health (spec 11): counts, codes and source ids only."""
    resolve_counts: Counter[str] = Counter()
    for source in resolved:
        resolve_counts.update(source.counts)
    by_status: Counter[str] = Counter(
        f"{closing.day.isoformat()}:{closing.status.name.lower()}" for closing in merged.closings
    )
    return {
        "at": now.astimezone(UTC).isoformat(),
        "reads": dict(sorted(outcomes.items())),
        "healthy_share": round(share, 4),
        "sources": len(resolved),
        "resolve": dict(sorted(resolve_counts.items())),
        "withheld": dict(merged.withheld),
        "merge": dict(merged.counts),
        "published": dict(sorted(by_status.items())),
        "opens": len(merged.opens),
        "breakers": list[JSONValue](merged.breakers),
        "fast_vanishes": len(merged.fast_vanishes),
        "held_vanishes": len(merged.held_vanishes),
        "edition": edition,
        "gate": report.to_json(),
    }
