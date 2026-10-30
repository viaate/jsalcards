"""G12b's window (S3): the share counts each due source by the read of the pass that picked it.

The 48-hour soak refused a pass at every :10 and :40 with a share near 0.45: the :25 (and
:55) pass reads every half-hourly source, the cadence counts those sources due for the 15
minutes from that pass's start, but the share kept their reads under their own fetch times
and measured them against the clock after the :40 pass's reads, so the sweep's earlier reads
had left the window while their sources still counted due. Here the same passes run on a
real :class:`~snowlight.live.cadence.Cadence` (SYNTHETIC stations), as
:class:`~snowlight.live.reads.LiveReads` and :meth:`~snowlight.live.ingest.Ingest.run_pass`
drive it: the :40 pass is healthy, and a real outage is still refused within a pass.
"""

import random
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from live.test_cadence import cadence, station
from live.world import at
from snowlight.live.cadence import Cadence
from snowlight.live.guards import MIN_HEALTHY_SHARE, GateInput, Refusal, gate_refusals
from snowlight.live.ingest import Ingest, SourceRead
from snowlight.live.ledger import Outcome

WINDOW = tuple(station(f"synthetic-ny-{n}", fips=("36061",)) for n in range(4))
"""In New York's morning window from 10:25Z (05:25 EST): read every pass."""
CALM = tuple(station(f"synthetic-la-{n}", fips=("06037",), poll=30) for n in range(12))
"""In Los Angeles from 02:25 PST: read every 30 minutes."""
SWEEP_READS = timedelta(seconds=56)
"""The soak's :25 sweep: 864 reads over about 56 seconds."""
PASS_READS = timedelta(seconds=43)


@dataclass(frozen=True, slots=True)
class Taken:
    outcome: Outcome


class Ledger:
    """The ledger's part G12b needs: every read taken as it came."""

    def observe(
        self, _source_id: str, outcome: Outcome, _fetched_at: datetime, _rows: object
    ) -> Taken:
        return Taken(outcome)


class Health:
    """A share-only ingest fed the way the loop feeds it (the real :meth:`Ingest.observe` and
    :meth:`Ingest.healthy_share`), with the soak's way of measuring kept beside it."""

    def __init__(self) -> None:
        self.ingest = Ingest.__new__(Ingest)
        self.ingest.ledger = Ledger()  # type: ignore[assignment]
        self.ingest.recent = deque()
        self.ingest.present = {}
        self.ingest.failed = set()
        self.ingest.taken = set()
        self.ingest.due = frozenset()
        self.ingest.beat = lambda: None
        self.fetched: list[tuple[datetime, str, bool]] = []

    def old_share(self, reads: Sequence[SourceRead], after: datetime) -> float:
        """As the soak's code took it: each read under its own fetch time, measured from the
        clock after the pass's reads."""
        self.fetched.extend(
            (read.fetched_at, read.source_id, read.outcome is Outcome.OK) for read in reads
        )
        old = Ingest.__new__(Ingest)
        old.recent = deque(sorted(self.fetched))
        old.due = self.ingest.due
        return old.healthy_share(after)


def reads_of(
    picked: Sequence[str], started: datetime, took: timedelta, outcome: Outcome = Outcome.OK
) -> list[SourceRead]:
    """One read per source picked, spread over the pass's reads."""
    step = took / max(1, len(picked))
    return [
        SourceRead(source_id, outcome, started + step * (index + 1))
        for index, source_id in enumerate(picked)
    ]


def run(
    clock: Cadence, health: Health, started: datetime, outcome: Outcome = Outcome.OK
) -> tuple[float, float]:
    """One pass: the cadence picks, the reads come back, G12b's share now and as the soak's
    code measured it."""
    due = clock.due(started, [*clock.stations])
    took = SWEEP_READS if len(due) > len(WINDOW) else PASS_READS
    reads = reads_of([item.id for item in due], started, took, outcome)
    clock.record(started, [(read.source_id, read.outcome, None) for read in reads])
    health.ingest.due = clock.recently_due(started)
    health.ingest.observe(reads, at=started)
    return health.ingest.healthy_share(started), health.old_share(reads, started + took)


def stations_clock() -> Cadence:
    return cadence(*WINDOW, *CALM)


def test_the_pass_after_the_half_hour_sweep_is_healthy() -> None:
    clock, health = stations_clock(), Health()
    shares = {}
    for minute in (25, 30, 35, 40, 45, 50, 55, 60, 65, 70):
        started = at("2026-11-17 10:00") + timedelta(minutes=minute, seconds=1)
        shares[minute] = run(clock, health, started)
    # the soak's dip, reproduced: the :40 pass measured the old way falls under 60%
    assert shares[40][1] < MIN_HEALTHY_SHARE
    assert shares[70][1] < MIN_HEALTHY_SHARE  # and again at :10, after the :55 sweep
    # counted by the passes' starts, every pass is whole
    assert all(share == 1.0 for share, _ in shares.values())


def test_a_pass_starting_a_moment_later_keeps_the_two_windows_one() -> None:
    """The sweep's sources leave the due set and the share together: jitter in the passes'
    starts never counts a source due without its read."""
    clock, health = stations_clock(), Health()
    run(clock, health, at("2026-11-17 10:25") + timedelta(seconds=0.2))
    for minute, late in ((30, 1), (35, 1), (40, 1.4)):
        started = at("2026-11-17 10:00") + timedelta(minutes=minute, seconds=late)
        share, _ = run(clock, health, started)
        assert share == 1.0


def refuses(share: float, previous: float | None) -> bool:
    return Refusal.HEALTH in gate_refusals(
        GateInput(
            edition_ok=True,
            healthy_share=share,
            previous_healthy_share=previous,
            generated_at=at("2026-11-17 10:46"),
            last_published=None,
            now=at("2026-11-17 10:46"),
            gzip_bytes=1,
        )
    )


def test_a_real_outage_is_refused_at_its_first_pass() -> None:
    """The window alone still counted the sweep's good reads at 10:40 (12 of 16, published);
    the pass's own reads, every one failed, refuse it there."""
    clock, health = stations_clock(), Health()
    for minute in (25, 30, 35):
        run(clock, health, at("2026-11-17 10:00") + timedelta(minutes=minute, seconds=1))
    # the network goes at 10:40: every read of every pass from then fails
    window, gated = [], []
    for minute in (40, 45, 50):
        started = at("2026-11-17 10:00") + timedelta(minutes=minute, seconds=1)
        due = clock.due(started, [*clock.stations])
        reads = reads_of(
            [item.id for item in due] + [f"synthetic-more-{n}" for n in range(6)],
            started,
            PASS_READS,
            Outcome.ERROR,
        )
        clock.record(started, [(read.source_id, read.outcome, None) for read in reads])
        health.ingest.due = clock.recently_due(started)
        health.ingest.observe(reads, at=started)
        window.append(health.ingest.healthy_share(started))
        gated.append(health.ingest.gate_share(reads, started))
    # 10:40: the window's sources failed, the sweep's 15 minutes old still stand in it
    assert window[0] == len(CALM) / (len(CALM) + len(WINDOW))
    assert not refuses(window[0], 1.0)
    # but the pass's own reads all failed: refused at once
    assert gated[0] == 0.0
    assert refuses(gated[0], 1.0)
    # and the window alone refuses from 10:45 on, as before
    assert window[1] == 0.0
    assert all(refuses(share, None) for share in gated)


def test_a_pass_counts_its_own_reads_only_from_ten_reads_on() -> None:
    health = Health()
    started = at("2026-11-17 10:40")
    # a small pass (a successor's first reads, an edition's pass): the window decides
    few = reads_of(["synthetic-a", "synthetic-b"], started, PASS_READS, Outcome.ERROR)
    health.ingest.due = frozenset({"synthetic-a", "synthetic-b", "synthetic-c"})
    health.ingest.recent.extend((started, sid, True) for sid in ("synthetic-c",))
    health.ingest.observe(few, at=started)
    assert health.ingest.gate_share(few, started) == health.ingest.healthy_share(started)
    # ten reads, nine good: the pass's own 90% is the bar only when the window is higher
    ten = [
        *reads_of([f"synthetic-g{n}" for n in range(9)], started, PASS_READS),
        *reads_of(["synthetic-bad"], started, PASS_READS, Outcome.ERROR),
    ]
    health = Health()
    health.ingest.due = frozenset(read.source_id for read in ten)
    health.ingest.observe(ten, at=started)
    assert health.ingest.healthy_share(started) == 0.9
    assert health.ingest.gate_share(ten, started) == 0.9
    late = [
        *ten[:5],
        *reads_of([f"synthetic-l{n}" for n in range(5)], started, PASS_READS, Outcome.LATE),
    ]
    assert health.ingest.gate_share(late, started) == 0.5


def test_a_whole_sweep_that_fails_is_refused_at_once() -> None:
    clock, health = stations_clock(), Health()
    share, _ = run(clock, health, at("2026-11-17 10:25") + timedelta(seconds=1), Outcome.ERROR)
    assert share == 0.0


def test_no_pass_counts_lower_than_the_soaks_way_whatever_the_starts_and_outcomes() -> None:
    """The new window share (:meth:`Ingest.healthy_share`) is never under the old one for the
    same passes: a due source's latest read is its picking pass's, which the new window
    always holds and the old one held or had dropped. This covers the window share only. The
    gate takes the lower of it and a pass's own reads from 10 reads on
    (:meth:`Ingest.gate_share`), which can be under the old share; that floor refused none of
    the 1261 uploaded passes of Oct 25-29 with 10 reads or more. 400 SYNTHETIC passes with
    jittered and off-grid starts, reads in any fetch order and random outcomes, the old way
    kept exactly as it ran (each read under its fetch time, in the order taken, dropped from
    the front against the clock after the reads)."""
    rng = random.Random(20261030)  # noqa: S311 - a seeded test schedule, not a secret
    clock, health = stations_clock(), Health()
    old: deque[tuple[datetime, str, bool]] = deque()
    started = at("2026-11-17 10:00")
    lower = 0
    for _ in range(400):
        started += timedelta(minutes=5) if rng.random() < 0.85 else timedelta(minutes=2.5)
        started += timedelta(seconds=rng.uniform(0, 2))
        due = clock.due(started, [*clock.stations])
        took = timedelta(seconds=rng.uniform(5, 270))
        reads = [
            SourceRead(
                item.id,
                rng.choice((Outcome.OK, Outcome.OK, Outcome.OK, Outcome.ERROR, Outcome.LATE)),
                started + took * rng.random(),
            )
            for item in due
        ]
        clock.record(started, [(read.source_id, read.outcome, None) for read in reads])
        health.ingest.due = clock.recently_due(started)
        health.ingest.observe(reads, at=started)
        new = health.ingest.healthy_share(started)
        old.extend((read.fetched_at, read.source_id, read.outcome is Outcome.OK) for read in reads)
        after = started + took
        while old and after - old[0][0] > timedelta(minutes=15):
            old.popleft()
        latest = {sid: ok for _, sid, ok in old}
        due_now = health.ingest.due
        was = sum(latest.get(sid, False) for sid in due_now) / len(due_now) if due_now else 0.0
        assert new >= was - 1e-12
        lower += new > was
        started = after
    assert lower > 0  # the old way did drop reads the new one keeps
