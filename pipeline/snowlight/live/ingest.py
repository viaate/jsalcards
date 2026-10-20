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
   minutes was healthy (G12b);
6. queues the listings the matcher did not accept (private) and writes
   ``health.json``: counts, codes and source ids only (a failed write is logged by its
   type and leaves the pass's exit as it was).

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
from snowlight.live.edition import EditionVerdict, EditionWatch
from snowlight.live.guards import Rules, held
from snowlight.live.ledger import GOOD, LONGEST, Ledger, SeenRow
from snowlight.live.ledger import Outcome as ReadOutcome
from snowlight.live.merge import Merged, merge
from snowlight.live.publish import Exit, LivePublisher, PassReport
from snowlight.live.resolve import LiveDirectory, Resolved, Resolver
from snowlight.output import JSONValue, write_json
from snowlight.sources.stations.registry import Station, StationStatus

LOG: Final = logging.getLogger(__name__)
HEALTH_WINDOW: Final = timedelta(minutes=15)
"""G12b counts the sources due in the last 15 minutes."""
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

    def observe(self, reads: Iterable[SourceRead]) -> Counter[str]:
        """Fold reads into the ledger; returns the outcomes as the ledger took them."""
        outcomes: Counter[str] = Counter()
        self.failed = set()
        for read in reads:
            try:
                observed = self.ledger.observe(
                    read.source_id, read.outcome, read.fetched_at, read.rows
                )
            except Exception as error:
                LOG.error("observe %s: %s", read.source_id, type(error).__name__)
                outcomes["error"] += 1
                self.failed.add(read.source_id)
                self.present.pop(read.source_id, None)
                self.recent.append((read.fetched_at, read.source_id, False))
                continue
            outcomes[observed.outcome.value] += 1
            confirmed = read.outcome is ReadOutcome.NOT_MODIFIED and not read.rows
            if observed.outcome in GOOD and not confirmed:
                self.present[read.source_id] = read.rows
            # A "not modified" with no rows confirms the body this process last read; one
            # this process never read leaves the source unheld (dissents only) until a
            # full read (the fetch layer's first read after a start is a full GET).
            self.recent.append((read.fetched_at, read.source_id, observed.outcome in GOOD))
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
        due source not read in that time counts as not healthy)."""
        while self.recent and now - self.recent[0][0] > HEALTH_WINDOW:
            self.recent.popleft()
        latest: dict[str, bool] = {}
        for _, source_id, good in self.recent:
            latest[source_id] = good
        due = self.due_sources()
        return sum(latest.get(source_id, False) for source_id in due) / len(due) if due else 0.0

    def resolve(self) -> list[Resolved]:
        """Every source the ledger knows, resolved against its present rows. A source whose
        resolve raises is left out and named in :attr:`failed` (its id and the error's type
        are logged, never its message)."""
        known = {state.source_id for state in self.ledger.sources()}
        resolved = []
        for source_id in sorted(known):
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
        """The directory handshake against the stamps the public files carry."""
        stamps, complete = self.publisher.public_stamps()
        verdict = self.watch.check(now, published=stamps, complete=complete)
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

    def run_pass(
        self, reads: Sequence[SourceRead], now: datetime, *, started: datetime | None = None
    ) -> PassReport:
        """One pass: observe, resolve, merge, gate, publish, record (see the module). ``now``
        is the clock after the reads; a read stamped later moves it to that read.
        ``started`` is when the pass began, before its reads (the heartbeat's grid)."""
        now = max([now, *(read.fetched_at for read in reads)])
        outcomes = self.observe(reads)
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
        share = self.healthy_share(now)
        edition = self.check_edition(now)
        try:
            report = self.publisher.publish(
                merged,
                now=now,
                healthy_share=share,
                edition=edition,
                alerted=self.alerted,
                started=started,
            )
        except OSError as error:
            LOG.error("publish: %s", type(error).__name__)
            report = PassReport(Exit.ERROR, now, note=f"publish: {type(error).__name__}")
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
        LOG.info(
            "pass: %d reads, healthy share %.2f, %d statuses, exit %d",
            len(reads),
            share,
            len(merged.closings),
            int(report.exit),
        )
        return report


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
