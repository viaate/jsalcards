"""The loop's grid rules and the publish gap at each kind of boundary, on a fake clock (S8-E
pass timing, E3, E7). SYNTHETIC world, a loopback stub host.

* every grid pass uploads, changed or not; the run's first pass is off the grid and skips an
  unchanged upload only when it starts under 4 minutes after the last uploading pass;
* the next due mark is the first grid mark after the pass's start, so a pass that overran
  runs the missed mark at once and no grid slot is lost;
* a run ends right after its last grid pass that starts before ``--until``;
* each boundary type, timed the way Actions runs it (the job's end steps, the queue and cold
  start, the first pass's reads before its upload): a successor handoff is about 5 minutes;
  a mode change (the run cancelled mid-pass, its end steps, the successor in the new mode),
  a broken chain (no successor: the reader job's next tick restarts it), a restart after the
  watcher killed a hang at the start of a grid pass, and an edition stop each stay under 15
  (the kill and the mode change with a minute to spare when the next run's first pass reads
  a full 2.5-minute sweep);
* the pulse is never older than the watcher's limit in a healthy loop, long reads, slow
  pushes (request by request), slow handshakes and a slow live host (a publish longer than
  the limit) included, so the watcher never ends a healthy reader.
"""

import argparse
import signal
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from itertools import pairwise
from pathlib import Path

import httpx
import pytest

from live.test_cli import (
    CLOSINGS_PATH,
    MORNING,
    OWN,
    Clock,
    Rig,
    Server,
    _common,
    _loaders,
    _run,
    make_rig,
    serve,
)
from live.test_edition import Source
from live.world import at
from snowlight.directory.deployed import DeployedEdition
from snowlight.live import cli as live_cli
from snowlight.live.d1 import PushResult
from snowlight.live.edition import EditionWatch
from snowlight.live.ingest import SourceRead
from snowlight.schemas.live import ClosingsFile

STEP = timedelta(minutes=5)
HANDOFF = timedelta(minutes=2, seconds=18) + timedelta(minutes=1, seconds=36)
"""Job end to the successor's first read: job end at G+2.3, first read at about G+3.9."""
READS = timedelta(seconds=90)
"""A pass's reads before its upload (the addendum's 1.5 minutes)."""
SWEEP = timedelta(seconds=150)
"""A new run's first pass in a busy window, reading every due source (E2's 2.5-minute p95
for that sweep)."""
COLD = timedelta(seconds=90)
"""Dispatch to a new run's first read: queue, set-up, directory, imports (the addendum's
cold-start table, its upper end)."""
END_STEPS = timedelta(seconds=60)
"""A job's steps after the loop: the record, the successor's dispatch, the end push, the
closing report, the export, its check and the cache save (about a minute)."""
END_STEPS_SLOW = timedelta(seconds=10) + live_cli.END_PUSH_FOR + timedelta(seconds=30)
"""The same with the end push at its bound (a D1 that hangs too)."""
WATCH_POLL = timedelta(seconds=10)
"""The watcher's look at the pulse (``PULSE_POLL``)."""
DISPATCH_FAILING = timedelta(seconds=3 * 20 + 10 + 20)
"""Three dispatch tries that time out, with the pauses between them."""
TIMER = timedelta(minutes=5)
"""At worst a whole timer interval until the reader job's next tick."""
READER_JOB = timedelta(seconds=15)
"""The reader job's queue and its jobs-API check before it dispatches."""
BAR = timedelta(minutes=15)


class Hang(BaseException):
    """A hang the process never returns from (the watcher's kill, or a cancel): it is not an
    ``Exception``, so nothing in the loop catches it."""


class TimedPuts(list[str]):
    """The stub host's PUT log, with the fake time of every closings upload (``times``: the
    shadow prefix's; ``every``: each prefix's)."""

    def __init__(self, clock: Clock) -> None:
        super().__init__()
        self.clock = clock
        self.times: list[datetime] = []
        self.every: list[tuple[datetime, str]] = []

    def append(self, path: str) -> None:
        super().append(path)
        if path == CLOSINGS_PATH:
            self.times.append(self.clock.now)
        if path.endswith("/live/closings.json"):
            self.every.append((self.clock.now, path.split("/")[2]))


@pytest.fixture
def server(clock: Clock) -> Iterator[Server]:
    for stub in serve(clock):
        stub.puts = TimedPuts(clock)
        yield stub


@pytest.fixture
def clock() -> Clock:
    return Clock(MORNING)


@pytest.fixture
def rig() -> Rig:
    return make_rig()


def _puts(server: Server) -> TimedPuts:
    puts = server.puts
    assert isinstance(puts, TimedPuts)
    return puts


def _times(server: Server) -> list[datetime]:
    return _puts(server).times


def _pulse(tmp_path: Path) -> datetime:
    """The fake time of the loop's last pulse (the file holds it)."""
    return datetime.fromisoformat((tmp_path / "state" / live_cli.PULSE).read_text().strip())


def _reading(
    loaders: live_cli.Loaders, clock: Clock, took: Callable[[], timedelta]
) -> live_cli.Loaders:
    """``loaders`` whose reads take ``took()`` on the fake clock."""
    base = loaders.parts

    def parts(
        config: live_cli.LiveConfig, env: live_cli.Env, args: argparse.Namespace
    ) -> live_cli.Parts:
        made = base(config, env, args)

        def reads(
            _now: datetime, only: Sequence[str], tick: Callable[[], None]
        ) -> Sequence[SourceRead]:
            clock.sleep(took().total_seconds())
            return made.reads(clock.now, only, tick)

        return live_cli.Parts(made.ingest, reads)

    return replace(loaders, parts=parts)


def _loop(
    tmp_path: Path,
    server: Server,
    loaders: live_cli.Loaders,
    monkeypatch: pytest.MonkeyPatch,
    until: str,
) -> int:
    return _run(["live", "run", "--until", until, *_common(tmp_path, server)], loaders, monkeypatch)


def test_grid_passes_always_upload_and_the_run_ends_after_its_last_grid_pass(
    tmp_path: Path, server: Server, clock: Clock, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock.now = at("2026-11-17 11:05") + timedelta(seconds=30)  # an off-grid start
    loaders = _reading(_loaders(rig, clock), clock, lambda: timedelta(seconds=40))
    assert _loop(tmp_path, server, loaders, monkeypatch, "+30m") == 0
    starts = [moment - timedelta(seconds=40) for moment in _times(server)]
    assert starts[0] == at("2026-11-17 11:05") + timedelta(seconds=30)
    assert starts[1:] == [at("2026-11-17 11:10") + STEP * index for index in range(6)]
    # it ends right after the 11:35 pass (the last before 11:35:30), not idling to the limit
    assert clock.now < at("2026-11-17 11:36")


def test_a_pass_that_overran_runs_the_missed_mark_at_once(
    tmp_path: Path, server: Server, clock: Clock, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    lags = iter([timedelta(seconds=30), timedelta(minutes=6), *[timedelta(seconds=30)] * 20])
    loaders = _reading(_loaders(rig, clock), clock, lambda: next(lags))
    assert _loop(tmp_path, server, loaders, monkeypatch, "+25m") == 0
    uploads = _times(server)
    # 11:05 (0:30), 11:10 runs 6 minutes to 11:16, the 11:15 mark runs at once (11:16:30),
    # then 11:20, 11:25: no grid slot is lost
    assert uploads[:4] == [
        at("2026-11-17 11:05") + timedelta(seconds=30),
        at("2026-11-17 11:16"),
        at("2026-11-17 11:16") + timedelta(seconds=30),
        at("2026-11-17 11:20") + timedelta(seconds=30),
    ]


def test_a_successor_skips_its_unchanged_first_pass_and_the_gap_is_about_5_minutes(
    tmp_path: Path, server: Server, clock: Clock, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    loaders = _reading(_loaders(rig, clock), clock, lambda: timedelta(seconds=50))
    assert _loop(tmp_path, server, loaders, monkeypatch, "+60m") == 0
    first = list(_times(server))
    last_pass = first[-1] - timedelta(seconds=50)
    assert last_pass == at("2026-11-17 12:00")
    clock.now = last_pass + HANDOFF  # the successor's first read, about G+3.9
    successor = _reading(_loaders(rig, clock), clock, lambda: timedelta(seconds=50))
    assert _loop(tmp_path, server, successor, monkeypatch, "+20m") == 0
    second = _times(server)[len(first) :]
    assert second[0] == at("2026-11-17 12:05") + timedelta(seconds=50)  # the G+5 grid pass
    gaps = [b - a for a, b in pairwise(_times(server))]
    assert max(gaps) <= STEP + timedelta(seconds=1)
    assert first[-1] < second[0]


def _hanging(
    loaders: live_cli.Loaders, clock: Clock, start: datetime, after: timedelta = timedelta(0)
) -> live_cli.Loaders:
    """``loaders`` whose first pass that starts at ``start`` or later never returns: ``after``
    into its reads the process is gone (:class:`Hang`), with no tick in between."""
    base = loaders.parts

    def parts(
        config: live_cli.LiveConfig, env: live_cli.Env, args: argparse.Namespace
    ) -> live_cli.Parts:
        made = base(config, env, args)

        def reads(
            now: datetime, only: Sequence[str], tick: Callable[[], None]
        ) -> Sequence[SourceRead]:
            if clock.now >= start:
                clock.sleep(after.total_seconds())
                raise Hang
            return made.reads(now, only, tick)

        return live_cli.Parts(made.ingest, reads)

    return replace(loaders, parts=parts)


def _in_mode(loaders: live_cli.Loaders, mode: str) -> live_cli.Loaders:
    base = loaders.env
    return replace(loaders, env=lambda: {**base(), "LIVE_PUBLISH": mode})


@pytest.mark.parametrize("first_reads", [READS, SWEEP], ids=["reads", "sweep"])
@pytest.mark.parametrize("end_steps", [END_STEPS, END_STEPS_SLOW], ids=["end", "slow-end-push"])
def test_a_restart_after_the_watcher_kills_a_hang_at_a_grid_pass_start_stays_under_15(  # noqa: PLR0913, PLR0917 - fixtures
    tmp_path: Path,
    server: Server,
    clock: Clock,
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
    end_steps: timedelta,
    first_reads: timedelta,
) -> None:
    # the worst case: the grid pass at G hangs at its start (holding the interpreter: no tick,
    # no pulse); the pass before it uploaded at G-3.5 and the last pulse is its last 60-s check
    grid = at("2026-11-17 11:30")
    loaders = _hanging(_reading(_loaders(rig, clock), clock, lambda: READS), clock, grid)
    with pytest.raises(Hang):
        _loop(tmp_path, server, loaders, monkeypatch, "+60m")
    last = _times(server)[-1]
    assert last == grid - STEP + READS
    pulse = _pulse(tmp_path)
    assert grid - timedelta(minutes=1) <= pulse < grid
    # the watcher sees the pulse at its limit at its next look, TERM, KILL a grace later; the
    # job's end steps run, then the successor's queue and cold start, and its first pass reads
    killed = pulse + live_cli.PULSE_MAX_AGE + WATCH_POLL + live_cli.PULSE_GRACE
    clock.now = killed + end_steps + COLD
    count = len(_times(server))
    restarted = _reading(_loaders(rig, clock), clock, lambda: first_reads)
    assert _loop(tmp_path, server, restarted, monkeypatch, "+20m") == 0
    first = _times(server)[count]
    assert first == killed + end_steps + COLD + first_reads
    assert first - last <= BAR - timedelta(minutes=1)  # a minute to spare, a sweep included
    assert max(b - a for a, b in pairwise(_times(server))) <= BAR


@pytest.mark.parametrize("first_reads", [READS, SWEEP], ids=["reads", "sweep"])
def test_a_mode_change_cancels_mid_pass_and_the_new_mode_publishes_within_15_minutes(  # noqa: PLR0913, PLR0917 - fixtures
    tmp_path: Path,
    server: Server,
    clock: Clock,
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
    first_reads: timedelta,
) -> None:
    # the reader job cancels the shadow run just before its grid pass would upload (the worst
    # moment), and dispatches the run in the new mode at the same tick: that run waits for
    # this job's end steps (the end push included), then starts cold
    grid = at("2026-11-17 11:30")
    cancelled = grid + READS - timedelta(seconds=6)
    shadow = _hanging(
        _reading(_loaders(rig, clock), clock, lambda: READS), clock, grid, cancelled - grid
    )
    with pytest.raises(Hang):
        _loop(tmp_path, server, shadow, monkeypatch, "+60m")
    assert clock.now == cancelled
    last = _times(server)[-1]
    assert last == grid - STEP + READS
    clock.now = cancelled + timedelta(seconds=10)  # SIGINT, the watcher's TERM to the reader
    pushed = ["live", "state", "push", *_common(tmp_path, server)]
    assert _run(pushed, _loaders(rig, clock), monkeypatch) == 0
    clock.now = cancelled + timedelta(seconds=10) + END_STEPS + COLD
    on = _in_mode(_reading(_loaders(rig, clock), clock, lambda: first_reads), "on")
    assert _loop(tmp_path, server, on, monkeypatch, "+20m") == 0
    every = _puts(server).every
    first_on = next(moment for moment, prefix in every if prefix == "v1")
    assert first_on - last <= BAR
    # the shadow run wrote nothing under v1, and the run in on nothing under v1-shadow
    assert all(prefix == "v1-shadow" for moment, prefix in every if moment <= cancelled)
    assert all(prefix == "v1" for moment, prefix in every if moment > cancelled)


def test_a_broken_chain_is_restarted_by_the_reader_job_within_15_minutes(
    tmp_path: Path, server: Server, clock: Clock, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the run ends after its last grid pass and its successor's dispatch fails three times;
    # the next timer tick (at worst a whole interval later) finds no live-read job running,
    # and the reader job dispatches one
    loaders = _reading(_loaders(rig, clock), clock, lambda: READS)
    assert _loop(tmp_path, server, loaders, monkeypatch, "+30m") == 0
    last = _times(server)[-1]
    ended = clock.now
    assert ended == last
    clock.now = ended + DISPATCH_FAILING + END_STEPS + TIMER + READER_JOB + COLD
    count = len(_times(server))
    assert _loop(tmp_path, server, loaders, monkeypatch, "+20m") == 0
    first = _times(server)[count]
    assert first - last <= BAR


def test_an_edition_stop_blanks_and_its_successor_publishes_within_15_minutes(
    tmp_path: Path, server: Server, clock: Clock, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the deployed directory changes: the run blanks and stops; its successor on the new
    # directory publishes at its first pass
    loaders = _reading(_loaders(rig, clock), clock, lambda: READS)
    assert _loop(tmp_path, server, loaders, monkeypatch, "+10m") == 0
    rig.edition[:] = [OWN, OWN.model_copy(update={"content_sha256": "c" * 64})]
    start = clock.now
    assert _loop(tmp_path, server, loaders, monkeypatch, "+20m") == 3
    blanked = ClosingsFile.from_json_bytes(server.objects[CLOSINGS_PATH])
    assert blanked.days == ()
    assert clock.now - start < timedelta(minutes=10)
    last = _times(server)[-1]  # the blank
    rig.edition[:] = [OWN]  # the successor builds the new directory
    clock.now = clock.now + END_STEPS + COLD
    count = len(_times(server))
    assert _loop(tmp_path, server, loaders, monkeypatch, "+10m") == 0
    assert _times(server)[count] - last <= BAR


@dataclass
class Watched(Clock):
    """A fake clock that looks at the pulse every 5 s of fake time, as the watcher does."""

    pulse: Path = Path()
    oldest: timedelta = timedelta(0)

    def sleep(self, seconds: float) -> None:
        left = seconds
        while left > 0:
            step = min(5.0, left)
            self.now += timedelta(seconds=step)
            left -= step
            if self.pulse.is_file():
                made = datetime.fromisoformat(self.pulse.read_text(encoding="utf-8").strip())
                self.oldest = max(self.oldest, self.now - made)


@dataclass
class SlowKeep:
    """A state store whose every push takes all the time it is given, one request every
    25 s (D1's REST calls, each through a client :func:`live_cli.beating` hooks, as
    ``make_store`` gives the real store) to the loopback stub."""

    clock: Clock
    url: str = ""
    pushes: int = 0
    requests: int = 0

    def keep(self, folder: Path, *, deadline: datetime | None = None) -> PushResult:
        del folder
        assert deadline is not None
        with live_cli.beating(httpx.Client()) as client:
            while self.clock.now < deadline:
                self.clock.sleep(min(25.0, (deadline - self.clock.now).total_seconds()))
                client.get(f"{self.url}/d1-synthetic")
                self.requests += 1
        self.pushes += 1
        return PushResult(bytes=1, parts=1, rows_written=3, day_rows=3, hourly=False)


class SlowPuts(TimedPuts):
    """The stub host's PUT log, each PUT taking ``each`` seconds of fake time (a slow host
    API: the client waits for its answer)."""

    def __init__(self, clock: Clock, each: float) -> None:
        super().__init__(clock)
        self.each = each

    def append(self, path: str) -> None:
        self.clock.sleep(self.each)
        super().append(path)


@dataclass
class SlowSource(Source):
    """A deployed-edition reader that takes 45 s (a slow handshake)."""

    clock: Clock | None = None

    def read(self) -> DeployedEdition:
        assert self.clock is not None
        self.clock.sleep(45)
        return super().read()


@pytest.mark.parametrize("put_seconds", [0.0, 55.0], ids=["host", "slow-host"])
def test_a_healthy_loop_never_lets_its_pulse_reach_the_watchers_limit(
    tmp_path: Path, rig: Rig, monkeypatch: pytest.MonkeyPatch, put_seconds: float
) -> None:
    # every push taking all its time, up to 30 s before the next grid mark, reads ticking
    # every 5 s as the pool's wait does, slow handshakes (45 s, once a minute: in the reads'
    # ticks too), and (slow-host) every upload to the live host taking 55 s (its 20-s
    # timeout, a try again and a read-back), so one pass's publish takes longer than the
    # watcher's limit: the pulse comes from each request, never only from the pass's end
    clock = Watched(at("2026-11-17 11:05"), pulse=tmp_path / "state" / live_cli.PULSE)
    keeper = SlowKeep(clock)
    monkeypatch.setattr(live_cli, "make_store", lambda _c, _e, _h: keeper)
    stubs = serve(clock)
    server = next(stubs)
    keeper.url = server.url
    puts = SlowPuts(clock, put_seconds)
    server.puts = puts
    try:
        base = _loaders(rig, clock)

        def parts(
            config: live_cli.LiveConfig, env: live_cli.Env, args: argparse.Namespace
        ) -> live_cli.Parts:
            made = base.parts(config, env, args)
            made.ingest.watch = EditionWatch(own=OWN, source=SlowSource([OWN], clock=clock))

            def reads(
                _now: datetime, only: Sequence[str], tick: Callable[[], None]
            ) -> Sequence[SourceRead]:
                begin = clock.now
                while clock.now - begin < timedelta(seconds=60):
                    clock.sleep(5)
                    tick()
                return made.reads(clock.now, only, tick)

            return live_cli.Parts(made.ingest, reads)

        loaders = replace(base, parts=parts)
        argv = ["live", "run", "--until", "+120m", "--push-every", "30", *_common(tmp_path, server)]
        assert _run(argv, loaders, monkeypatch) in {0, 3}
    finally:
        next(stubs, None)  # the stub host shuts down
    if not put_seconds:  # (a pass that slow leaves no idle time for a push)
        assert keeper.pushes >= 3
        assert keeper.requests > keeper.pushes  # each ran to its deadline, request by request
    assert clock.oldest <= timedelta(seconds=75)  # the 45-s handshake, then a 25-s request
    assert clock.oldest < live_cli.PULSE_MAX_AGE - timedelta(minutes=2)
    if put_seconds:
        per_pass = len(puts) / max(1, len(puts.times))  # PUTs per closings upload
        assert per_pass * put_seconds > live_cli.PULSE_MAX_AGE.total_seconds()


def test_a_pass_that_reads_to_its_cap_keeps_the_pulse_fresh_at_every_tick(
    tmp_path: Path, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    # reads to the pass cap (240 s and the 30-s grace), ticking every 5 s: the pulse never
    # waits for the pass to end, so only a hang (no tick at all) lets it age
    clock = Watched(at("2026-11-17 11:05"), pulse=tmp_path / "state" / live_cli.PULSE)
    stubs = serve(clock)
    server = next(stubs)
    try:
        base = _loaders(rig, clock)

        def parts(
            config: live_cli.LiveConfig, env: live_cli.Env, args: argparse.Namespace
        ) -> live_cli.Parts:
            made = base.parts(config, env, args)

            def reads(
                _now: datetime, only: Sequence[str], tick: Callable[[], None]
            ) -> Sequence[SourceRead]:
                for _ in range(54):
                    clock.sleep(5)
                    tick()
                return made.reads(clock.now, only, tick)

            return live_cli.Parts(made.ingest, reads)

        loaders = replace(base, parts=parts)
        argv = ["live", "run", "--until", "+30m", *_common(tmp_path, server)]
        assert _run(argv, loaders, monkeypatch) == 0
    finally:
        next(stubs, None)  # the stub host shuts down
    assert clock.oldest <= timedelta(seconds=65)


def test_the_reader_installs_no_term_handler_so_the_watchers_term_ends_it_at_once() -> None:
    live_cli.configure_logging()
    assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL


READER_END_STEPS = ("successor", "record", "push", "finish", "export", "check", "cache/save")
"""What :data:`END_STEPS` counts, in the reader job's order after the loop and its reap."""


def test_the_end_steps_the_gaps_count_are_the_reader_jobs_and_the_evidence_never_holds_it() -> None:
    # The gaps above count END_STEPS (END_STEPS_SLOW) between a run's last pass and its
    # successor's start. The successor waits for the reader job only (the `live-read` group),
    # so its steps after the loop must be exactly those; the evidence push (up to its 8-minute
    # step limit) runs in a job of its own, outside the group, and adds nothing to any gap.
    import yaml  # type: ignore[import-untyped, unused-ignore]  # noqa: PLC0415

    root = Path(__file__).resolve().parents[3]
    workflow = yaml.safe_load((root / ".github" / "workflows" / "live-read.yml").read_text())
    read = workflow["jobs"]["read"]
    names = [str(item.get("id") or item.get("uses")) for item in read["steps"]]
    after = names[names.index("reap") + 1 :]
    assert [next(key for key in READER_END_STEPS if key in name) for name in after] == list(
        READER_END_STEPS
    )
    assert read["concurrency"] == {"group": "live-read", "cancel-in-progress": False}
    assert not any("evidence" in str(item.get("run", "")) for item in read["steps"])
    evidence = workflow["jobs"]["evidence"]
    assert "concurrency" not in evidence
    assert "concurrency" not in workflow  # no workflow-level group holds the successor either
    assert evidence["needs"] == "read"
