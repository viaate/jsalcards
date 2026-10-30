"""A successor's first reads (S8-E follow-up): a new process holds a source's statuses only
once it has read the source itself, so every source whose last good read held rows is read
as soon as the politeness floor allows, whatever its cadence, and a run whose predecessor
read such a source in this grid slot waits for the next mark for its first pass.

The handoffs of Oct 25-29 showed why: a successor at G+2 read nothing (its predecessor had
read every due source in slot G), and a half-hourly source's statuses stayed dark until its
next calm read, up to 25 minutes (run 40716034708, 15:30Z Oct 28: 4 statuses to 0, back at
15:55). SYNTHETIC answers in memory for real registry ids; the cadence and the pool are the
real ones.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from live import world
from live.test_cadence import feed
from live.test_live_reads import fake_reader, fresh_robots
from snowlight.live.cadence import AlertWatch, Cadence
from snowlight.live.ingest import Ingest
from snowlight.live.ledger import Outcome
from snowlight.live.pool import PassResult, SourceResult
from snowlight.live.reads import LiveReads, due_sources, live_pool
from snowlight.sources.stations.registry import Registry, Station, load_registry

G = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
"""The predecessor's last grid pass."""
CALM_ZONE = "Pacific/Honolulu"
"""02:00 there: every source is on its calm 30-minute cadence."""


class Holding:
    """The ingest's part the reads ask: which sources' last good read held rows."""

    def __init__(self, ids: frozenset[str]) -> None:
        self.ids = ids
        self.due: frozenset[str] | None = None

    def holding(self) -> frozenset[str]:
        return self.ids


def three(registry: Registry) -> list[str]:
    """Three polled sources with counties on three hosts (none of Gray's shared bucket)."""
    hosts: set[str] = set()
    picked: list[str] = []
    for sid in sorted(due_sources(registry)):
        station = registry.stations[sid]
        host = urlsplit(station.poll_url or "").hostname or ""
        known = station.counties is not None and bool(station.counties.fips)  # a calm zone
        if known and host not in hosts and "s3.amazonaws.com" not in host:
            hosts.add(host)
            picked.append(sid)
        if len(picked) == 3:
            return picked
    raise AssertionError("the registry has fewer than three hosts")


def rig(
    tmp_path: Path, last: dict[str, datetime], holding: frozenset[str], rest: datetime = G
) -> LiveReads:
    """Reads over the real registry where only the sources in ``last`` are polled now (each
    read last by the predecessor's pass at that time), the rest read by its pass at
    ``rest``."""
    registry = load_registry()

    def serve(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"SYNTHETIC")

    state = tmp_path / "state"
    ids = sorted(due_sources(registry))
    fresh_robots(state, [registry.stations[sid].poll_url or "" for sid in last])
    pool = live_pool(
        tmp_path / "cache", state, http=httpx.Client(transport=httpx.MockTransport(serve))
    )
    zones = {
        fips: CALM_ZONE
        for station in registry.stations.values()
        if station.counties is not None
        for fips in station.counties.fips
    }
    cadence = Cadence(registry.stations, zones, registry.poll_minutes)
    cadence.record(rest, [(sid, Outcome.OK, None) for sid in ids if sid not in last])
    for sid, when in last.items():
        cadence.record(when, [(sid, Outcome.OK, None)])
    reads = LiveReads(registry, world.directory(), pool, cadence, reader=fake_reader)
    reads.ingest = Holding(holding)  # type: ignore[assignment]
    return reads


def read_ids(reads: LiveReads, now: datetime) -> set[str]:
    reads.pool.clock = lambda: now  # the pass starts at ``now`` (the pool keeps its start)
    return {read.source_id for read in reads(now, (), lambda: None)}


def test_a_source_the_predecessor_read_this_slot_is_read_at_the_next_mark(tmp_path: Path) -> None:
    registry = load_registry()
    lit, calm, other = three(registry)
    last = {lit: G, calm: G - timedelta(minutes=15), other: G - timedelta(minutes=15)}
    reads = rig(tmp_path, last, frozenset({lit, calm}))
    start = G + timedelta(minutes=2)
    # ``lit`` was read in this slot: asking it again now would break the floor, so the
    # first pass waits for the next mark
    assert reads.waits(start)
    first = read_ids(reads, G + timedelta(minutes=5))
    # both holding sources are read at G+5, whatever their 30-minute cadence; ``other``
    # (no rows) keeps its cadence
    assert first == {lit, calm}
    assert reads.unread == set()
    assert reads.pending() == []
    # from then on each keeps its own cadence: nothing at G+10
    assert read_ids(reads, G + timedelta(minutes=10)) == set()
    # ``other`` comes due on its cadence (30 minutes after G-15)
    assert read_ids(reads, G + timedelta(minutes=15)) == {other}


def test_without_a_source_read_this_slot_the_first_pass_reads_it_at_once(tmp_path: Path) -> None:
    registry = load_registry()
    lit, calm, other = three(registry)
    last = {lit: G - timedelta(minutes=10), calm: G - timedelta(minutes=15), other: G}
    reads = rig(tmp_path, last, frozenset({lit, calm}))
    start = G + timedelta(minutes=2)
    assert not reads.waits(start)  # ``other`` was read this slot but holds nothing
    assert read_ids(reads, start) == {lit, calm}


def test_the_old_cadence_alone_left_a_half_hourly_source_dark(tmp_path: Path) -> None:
    """The control: with nothing to read first, the 30-minute source holding rows is not read
    until its calm interval has run (G+15), so a new process shows none of its statuses."""
    registry = load_registry()
    lit, calm, other = three(registry)
    last = {lit: G, calm: G - timedelta(minutes=15), other: G - timedelta(minutes=15)}
    reads = rig(tmp_path, last, frozenset())
    assert read_ids(reads, G + timedelta(minutes=5)) == set()
    assert read_ids(reads, G + timedelta(minutes=10)) == set()
    assert read_ids(reads, G + timedelta(minutes=15)) == {calm, other}


def test_a_source_a_server_holds_back_is_not_waited_for(tmp_path: Path) -> None:
    registry = load_registry()
    lit, calm, other = three(registry)
    last = {lit: G - timedelta(minutes=15), calm: G - timedelta(minutes=15), other: G}
    reads = rig(tmp_path, last, frozenset({lit, calm}))
    # the predecessor's last read of ``calm`` asked for a 20-minute wait
    reads.cadence.record(G, [(calm, Outcome.DEFERRED, 20 * 60.0)])
    start = G + timedelta(minutes=2)
    assert not reads.waits(start)
    assert read_ids(reads, start) == {lit}  # ``calm`` waits for its server, as it would anyway
    assert reads.unread == {calm}
    assert read_ids(reads, G + timedelta(minutes=20, seconds=30)) == {calm}
    assert reads.unread == set()


def test_a_quiet_handoff_waits_for_the_next_mark(tmp_path: Path) -> None:
    """No source holds statuses (most of the off-season): a successor ready in the slot its
    predecessor passed in would find nothing due, count a share of 0 and be refused, so its
    first pass is the next mark; one ready in a later slot passes at once."""
    registry = load_registry()
    lit, calm, other = three(registry)
    last = {lit: G, calm: G - timedelta(minutes=15), other: G - timedelta(minutes=15)}
    reads = rig(tmp_path, last, frozenset())
    assert reads.pending() == []
    assert reads.waits(G + timedelta(minutes=2))
    assert reads.waits(G + timedelta(minutes=4, seconds=50))
    assert not reads.waits(G + timedelta(minutes=5))  # a new slot: a grid pass at once
    late = rig(tmp_path / "late", last, frozenset(), rest=G - timedelta(minutes=5))
    late.cadence.record(G - timedelta(minutes=5), [(lit, Outcome.OK, None)])
    assert not late.waits(G + timedelta(minutes=2))  # the run before ended a slot ago


def test_a_cold_start_never_waits(tmp_path: Path) -> None:
    reads = rig(tmp_path, {}, frozenset())
    reads.cadence.clocks.clear()
    assert not reads.waits(G + timedelta(minutes=2))


def test_a_holding_source_whose_last_read_failed_keeps_its_cadence(tmp_path: Path) -> None:
    """A 429 or 5xx without Retry-After: the successor does not ask the host early."""
    registry = load_registry()
    lit, calm, other = three(registry)
    last = {lit: G - timedelta(minutes=15), calm: G - timedelta(minutes=15), other: G}
    reads = rig(tmp_path, last, frozenset({lit, calm}))
    reads.cadence.record(G - timedelta(minutes=15), [(calm, Outcome.ERROR, None)])
    start = G + timedelta(minutes=2)
    assert not reads.waits(start)  # ``lit`` can be read now; ``calm`` is not waited for
    assert read_ids(reads, start) == {lit}
    assert read_ids(reads, G + timedelta(minutes=5)) == set()
    assert read_ids(reads, G + timedelta(minutes=10)) == set()
    # 30 minutes after its failed read, as its cadence says
    assert read_ids(reads, G + timedelta(minutes=15)) == {calm}
    assert reads.unread == set()


def test_a_failed_read_is_never_waited_for_alone(tmp_path: Path) -> None:
    registry = load_registry()
    _, calm, other = three(registry)
    last = {calm: G - timedelta(minutes=15), other: G - timedelta(minutes=15)}
    reads = rig(tmp_path, last, frozenset({calm}), rest=G - timedelta(minutes=5))
    reads.cadence.record(G - timedelta(minutes=15), [(calm, Outcome.PARTIAL, None)])
    # the run before ended a slot ago: nothing to wait for, ``calm`` is not due till G+15
    assert not reads.waits(G + timedelta(minutes=2))
    assert read_ids(reads, G + timedelta(minutes=2)) == set()


def test_a_successor_judges_a_failed_source_in_an_alert_county_on_the_alert_interval(
    tmp_path: Path,
) -> None:
    """The first-pass check reads the alert set before it asks a source's interval: the
    cadence's set is empty until a pass's ``due``, and a failed source in an alert county
    would be judged on its calm 30 minutes and not waited for."""
    registry = load_registry()
    lit, calm, other = three(registry)
    last = {lit: G - timedelta(minutes=15), calm: G, other: G - timedelta(minutes=15)}
    fips = registry.stations[calm].counties
    assert fips is not None
    warned = feed({"geocode": {"SAME": [f"0{fips.fips[0]}"], "UGC": []}})
    start = G + timedelta(minutes=2)
    for alerted in (False, True):
        reads = rig(tmp_path / str(alerted), last, frozenset({lit, calm}))
        reads.cadence.record(G, [(calm, Outcome.ERROR, None)])  # failed in this slot
        body = warned if alerted else feed()
        reads.cadence.alerts = AlertWatch(partial(bytes, body))
        assert reads.cadence.alerted == frozenset()
        # in an alert ``calm`` is due again at the next mark (5 minutes): the first pass
        # waits for it there; calm, it keeps 30 minutes and ``lit`` is read at once
        assert reads.waits(start) is alerted
        if alerted:
            first = read_ids(reads, G + timedelta(minutes=5))
            assert {lit, calm} <= first
            # the rest are the alert county's other sources, due on its 5-minute interval
            assert all(
                reads.cadence.in_alert(registry.stations[sid]) for sid in first - {lit, calm}
            )
        else:
            assert read_ids(reads, start) == {lit}
            assert read_ids(reads, G + timedelta(minutes=5)) == set()


class Scripted:
    """A pool that ends each source as told (else ``ok``) at the pass's start (SYNTHETIC)."""

    def __init__(self, ends: dict[str, Outcome]) -> None:
        self.ends = ends
        self.asked: list[set[str]] = []

    def run_pass(
        self,
        due: Sequence[Station],
        _read: object,
        *,
        alerted: Callable[[Station], bool] = lambda _station: False,
        tick: Callable[[], None] = lambda: None,
    ) -> PassResult:
        del alerted, tick  # the real pool's knobs: nothing to pace here
        self.asked.append({station.id for station in due})
        started = self.clock()
        return PassResult(
            started,
            1.0,
            tuple(
                SourceResult(station.id, self.ends.pop(station.id, Outcome.OK), 0.0, 1.0)
                for station in due
            ),
            1,
        )

    def clock(self) -> datetime:
        raise AssertionError("set by read_ids")  # pragma: no cover


def test_a_late_first_read_is_read_again_at_the_next_pass(tmp_path: Path) -> None:
    """The pass ran out of time before the holding source: it stays a source to read first,
    and the next pass reads it (its statuses dark for one pass more)."""
    registry = load_registry()
    lit, calm, other = three(registry)
    last = {lit: G - timedelta(minutes=15), calm: G - timedelta(minutes=15), other: G}
    reads = rig(tmp_path, last, frozenset({calm}))
    reads.pool = Scripted({calm: Outcome.LATE})  # type: ignore[assignment]
    found = read_ids(reads, G + timedelta(minutes=2))
    assert found == {calm}  # read as ``late``: the ledger takes it, nothing held
    assert reads.unread == {calm}
    assert read_ids(reads, G + timedelta(minutes=5)) == {calm}
    assert reads.unread == set()


def test_a_failed_first_read_leaves_the_source_dark_until_its_cadence(tmp_path: Path) -> None:
    """A holding source whose first read in the successor fails is no longer read first: like
    any failed read it keeps its cadence, so its statuses stay dark in the new process
    (never shown stale) until its next good read: at most its calm 30 minutes, 5 in a window
    or an alert."""
    registry = load_registry()
    lit, calm, other = three(registry)
    last = {lit: G - timedelta(minutes=15), calm: G - timedelta(minutes=15), other: G}
    reads = rig(tmp_path, last, frozenset({calm}))
    pool = Scripted({calm: Outcome.ERROR})
    reads.pool = pool  # type: ignore[assignment]
    start = G + timedelta(minutes=2)
    assert read_ids(reads, start) == {calm}
    assert reads.unread == set()
    for minute in (5, 10, 15, 20, 25, 30):
        assert calm not in read_ids(reads, G + timedelta(minutes=minute))
    assert calm in read_ids(reads, G + timedelta(minutes=35))  # 30 minutes after G+2's slot


def test_the_ingest_names_the_sources_whose_last_good_read_held_rows() -> None:
    lights = world.World()
    holder = Ingest.__new__(Ingest)
    holder.ledger = lights.ledger
    lights.read(world.at("2026-11-17 10:00"), [])
    assert holder.holding() == frozenset()  # read, and nothing listed
    lights.read(world.at("2026-11-17 10:30"), [world.row(world.ALPHA_SCHOOL)])
    assert holder.holding() == frozenset({"gray-synthetic"})
    lights.read(world.at("2026-11-17 11:00"), [], outcome=Outcome.ERROR)
    assert holder.holding() == frozenset({"gray-synthetic"})  # a failed read changes nothing
    lights.read(world.at("2026-11-17 11:30"), [])
    lights.read(world.at("2026-11-17 12:00"), [])  # the list really emptied
    assert holder.holding() == frozenset()
