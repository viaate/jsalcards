"""The second critic round's findings, each as a class of fault with its regression test.

Every name, status, school and station here is SYNTHETIC. The CLI tests run against the
stub bucket of ``test_cli`` (a real HTTP server on 127.0.0.1 that checks SigV4).
"""

import argparse
import json
import shutil
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from itertools import pairwise
from pathlib import Path

import httpx
import pytest

from live.test_cli import (
    ACCESS,
    CLOSINGS_PATH,
    MORNING,
    OWN,
    SECRET,
    STORM,
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
from live.test_fixes_r1 import (
    DAY,
    PREFIX,
    PUBLIC,
    Timed,
    _again,
    _events,
    _lit,
    _timed,
    _timeline,
)
from live.test_publish import SHADOW, STAMP, Host, equal, storm
from live.test_publish import Rig as PublishRig
from live.test_publishers import Repo, _github
from live.world import World, at, row, station
from snowlight.directory.deployed import (
    DeployedEdition,
    DeployedEditionError,
    DeployInProgressError,
    LiveDeployment,
)
from snowlight.live import cli as live_cli
from snowlight.live import publish as publish_module
from snowlight.live.edition import EditionState, EditionVerdict, EditionWatch, PagesDeployed
from snowlight.live.history import (
    BY,
    BY_HOLD,
    BY_SEED,
    Change,
    ChangeLog,
    Event,
    Shown,
    seed_changes,
    timeline,
)
from snowlight.live.ingest import Ingest, SourceRead
from snowlight.live.ledger import Outcome as ReadOutcome
from snowlight.live.publish import (
    CLOSINGS,
    HOLD,
    REDACTED,
    Exit,
    LiveHold,
    LivePublisher,
    Memory,
    Mode,
    emergency_blank,
    holds,
    release,
)
from snowlight.live.publishers import (
    Credentials,
    GuardRefusedError,
    PublishError,
    R2Publisher,
    WriteGuard,
    guarded_write,
)
from snowlight.schemas.directory import DirectoryEdition, DirectoryStamp
from snowlight.schemas.live import ClosingsFile, DayIndex
from snowlight.schemas.vocab import Reason, Status
from snowlight.sources.stations.registry import Station

ALPHA = "200000100001"
"""The NCES id of SYNTHETIC Alpha Elementary (school 0)."""


@pytest.fixture
def clock() -> Clock:
    return Clock(MORNING)


@pytest.fixture
def server(clock: Clock) -> Iterator[Server]:
    yield from serve(clock)


@pytest.fixture
def rig() -> Rig:
    return make_rig()


@pytest.fixture
def pub(tmp_path: Path) -> PublishRig:
    world = World()
    host = Host(tmp_path / "host")
    state, internal = tmp_path / "state", tmp_path / "internal"
    publisher = LivePublisher(
        host=host, directory=world.dir, state_dir=state, internal_dir=internal
    )
    return PublishRig(world, host, publisher, state, internal)


def _index(server: Server, prefix: str = PREFIX) -> tuple[date, ...]:
    found = DayIndex.from_json_bytes(server.objects[f"{prefix}/days/index.json"])
    return tuple(entry.day for entry in found.days)


def _bucket(server: Server) -> R2Publisher:
    return R2Publisher(
        endpoint=server.url,
        bucket="snowlight-live",
        credentials=Credentials(ACCESS, SECRET, "auto", "s3"),
        client=httpx.Client(),
    )


def _health(tmp_path: Path) -> dict[str, object]:
    found = json.loads((tmp_path / "internal" / "health.json").read_text())
    assert isinstance(found, dict)
    return found


# --- B1 (data): what the emergency stop darkened never comes back as history -----------------


def test_a_hold_drops_the_run_it_darkened_from_the_timeline() -> None:
    world = World()

    def change(minute: int, event: Event, status: Status | None, **fields: str) -> Change:
        moment = at("2026-11-17 06:00") + timedelta(minutes=minute)  # school 0's midnight
        shown = None if status is None else Shown(int(status), None, None, None)
        return Change(moment, date(2026, 11, 17), ALPHA, event, shown, fields)

    changes = [
        change(420, Event.LIT, Status.CLOSED),
        change(480, Event.DARK, None),  # taken back by the source: history
        change(540, Event.LIT, Status.DELAYED),
        change(560, Event.CHANGED, Status.CLOSED),
        change(600, Event.DARK, None, **{BY: BY_HOLD}),  # the emergency stop
        change(660, Event.LIT, Status.CLOSED),  # shown again after the release
    ]
    made = timeline(
        date(2026, 11, 17),
        changes,
        directory=world.dir,
        stamp=STAMP,
        generated_at=at("2026-11-17 18:00"),
        final=False,
    )
    assert made is not None
    assert made.statuses == (Status.CLOSED, None, Status.CLOSED)
    assert made.minutes == (420, 480, 660)
    # a hold that darkened the only run leaves the school out
    only = [change(420, Event.LIT, Status.CLOSED), change(600, Event.DARK, None, by="hold")]
    assert (
        timeline(
            date(2026, 11, 17),
            only,
            directory=world.dir,
            stamp=STAMP,
            generated_at=at("2026-11-17 18:00"),
            final=False,
        )
        is None
    )


def test_release_never_brings_back_a_blanked_status_whose_row_is_gone(
    tmp_path: Path, server: Server, clock: Clock, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    common = _common(tmp_path, server)
    loaders = _loaders(rig, clock)
    assert _run(["live", "once", *common], loaders, monkeypatch) == 0
    clock.now = MORNING + timedelta(minutes=20)
    assert _run(["live", "blank", *common], loaders, monkeypatch) == 0
    assert _run(["live", "release", *common], loaders, monkeypatch) == 0
    # the cause is fixed at the source: it no longer lists the rows (merge keeps a gone row
    # through its day, so only the hold's record keeps them dark)
    rig.reads = [SourceRead("gray-synthetic", ReadOutcome.EMPTY, MORNING)]
    clock.now = MORNING + timedelta(minutes=30)
    rig.world.ledger.observe(
        "gray-synthetic", ReadOutcome.EMPTY, clock.now - timedelta(minutes=1), ()
    )
    assert _run(["live", "once", *common], loaders, monkeypatch) == 0
    assert _lit(server) == set()
    gate = _health(tmp_path)["gate"]
    assert isinstance(gate, dict)
    assert gate["counts"][REDACTED] == 2
    # no public day file shows the blanked statuses, and the index lists no day
    assert _timeline(server).gaps == ()
    assert _index(server) == ()
    memory = Memory.load(tmp_path / "state" / "publish.json")
    assert {nces_id for nces_id, _ in memory.redacted} == {ALPHA, "060000000001"}


def test_a_hold_read_late_still_darkens_by_the_hold(pub: PublishRig) -> None:
    """A pass that published after the hold began (it read the hold as clear) records it
    at its next pass, after its own change, so the timeline leaves the run out."""
    publisher = pub.publisher
    now = MORNING
    first = publisher.publish(storm(pub.world), now=now, healthy_share=1.0, edition=equal(now))
    assert first.exit is Exit.OK
    began = now - timedelta(minutes=1)  # set before this pass's publish
    pub.host.write(
        {
            f"{SHADOW}/{HOLD}": LiveHold(
                schema_version=1, held=True, at=began, held_at=began
            ).to_json_bytes()
        }
    )
    later = now + timedelta(minutes=5)
    report = publisher.publish(
        storm(pub.world, later), now=later, healthy_share=1.0, edition=equal(later)
    )
    assert (report.exit, report.refusals) == (Exit.REFUSED, ("held",))
    log = ChangeLog(pub.state / "changes")
    darks = [c for c in log.changes(date(2026, 11, 17)) if c.event is Event.DARK]
    assert darks
    assert all(c.fields.get(BY) == BY_HOLD and c.at >= now for c in darks)


# --- B2 (data): a restamp starts one extra pass, never a run of them -------------------------


def test_a_restamp_under_the_hold_adds_one_pass_then_the_grid(
    tmp_path: Path, server: Server, clock: Clock, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    common = _common(tmp_path, server)
    assert _run(["live", "once", *common], _loaders(rig, clock), monkeypatch) == 0
    clock.now = MORNING + timedelta(minutes=1)
    assert _run(["live", "blank", *common], _loaders(rig, clock), monkeypatch) == 0
    restamped = OWN.model_copy(update={"generated_on": date(2026, 11, 17)})
    loaders = _timed(rig, clock, Timed(clock, MORNING + timedelta(minutes=2), OWN, restamped))
    passes: list[datetime] = []
    base = loaders.parts

    def parts(
        config: live_cli.LiveConfig, env: live_cli.Env, args: argparse.Namespace
    ) -> live_cli.Parts:
        made = base(config, env, args)

        def reads(
            now: datetime, only: Sequence[str], tick: Callable[[], None]
        ) -> Sequence[SourceRead]:
            passes.append(now)
            clock.now += timedelta(seconds=30)  # each pass reads for 30 s
            return made.reads(now, only, tick)

        return live_cli.Parts(made.ingest, reads)

    code = _run(
        ["live", "run", "--until", "+20m", *common], replace(loaders, parts=parts), monkeypatch
    )
    assert code == 3  # held: every pass refused
    # 11:06 at the start, then the grid 11:10, 11:15, 11:20, 11:25: no immediate passes,
    # since the hold is set
    assert len(passes) == 5
    assert all(b - a >= timedelta(minutes=3) for a, b in pairwise(passes))


def test_a_restamp_the_gate_refuses_adds_one_pass_only(
    tmp_path: Path, server: Server, clock: Clock, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    common = _common(tmp_path, server)
    assert _run(["live", "once", *common], _loaders(rig, clock), monkeypatch) == 0
    restamped = OWN.model_copy(update={"generated_on": date(2026, 11, 17)})
    loaders = _timed(rig, clock, Timed(clock, MORNING + timedelta(minutes=2), OWN, restamped))
    passes: list[datetime] = []
    base = loaders.parts

    def parts(
        config: live_cli.LiveConfig, env: live_cli.Env, args: argparse.Namespace
    ) -> live_cli.Parts:
        made = base(config, env, args)

        def reads(
            now: datetime, only: Sequence[str], tick: Callable[[], None]
        ) -> Sequence[SourceRead]:
            passes.append(now)
            clock.now += timedelta(seconds=30)
            return [  # every source errors: the health check refuses each pass
                SourceRead(read.source_id, ReadOutcome.ERROR, read.fetched_at)
                for read in made.reads(now, only, tick)
            ]

        return live_cli.Parts(made.ingest, reads)

    clock.now = MORNING + timedelta(seconds=30)
    code = _run(
        ["live", "run", "--until", "+20m", *common], replace(loaders, parts=parts), monkeypatch
    )
    assert code == 3
    # 11:05:30 at the start, one pass for the new stamp, then the grid 11:10 to 11:25
    off_grid = [moment for moment in passes[1:] if moment.minute % 5 or moment.second]
    assert len(off_grid) == 1
    assert len(passes) == 6


# --- B3 (operations): a routine redeploy keeps the map lit -----------------------------------


@dataclass
class Deploys:
    """A SYNTHETIC Pages reader by the clock: deployment 2 (same content) is in progress
    from ``begins`` until ``settles``."""

    clock: Clock
    begins: datetime
    settles: datetime
    content: DirectoryEdition = OWN

    def newest_deployment(self) -> LiveDeployment:
        now = self.clock.now
        if now < self.begins:
            return LiveDeployment("success", MORNING - timedelta(hours=1), 1, "a" * 40)
        state = "in_progress" if now < self.settles else "success"
        return LiveDeployment(state, self.begins, 2, "b" * 40)

    def read(self) -> DeployedEdition:
        if self.begins <= self.clock.now < self.settles:
            raise DeployInProgressError(
                "a deploy is in progress (its state is 'in_progress'); run again after it"
            )
        return DeployedEdition(self.content.to_json_bytes(), "artifact")


def _deploying(rig: Rig, clock: Clock, deploys: Deploys) -> live_cli.Loaders:
    base = _loaders(rig, clock)
    watch = EditionWatch(own=OWN, source=PagesDeployed(deploys))  # type: ignore[arg-type]

    def parts(
        config: live_cli.LiveConfig, env: live_cli.Env, args: argparse.Namespace
    ) -> live_cli.Parts:
        made = base.parts(config, env, args)
        made.ingest.watch = watch  # one loop process: the reader is kept across passes
        return made

    return replace(base, parts=parts)


def test_a_same_content_redeploy_in_progress_keeps_the_map_lit(  # noqa: PLR0913, PLR0917
    tmp_path: Path,
    server: Server,
    clock: Clock,
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # in progress for two handshakes between passes and for the 11:10 pass itself
    deploys = Deploys(
        clock, MORNING + timedelta(minutes=3), MORNING + timedelta(minutes=6, seconds=30)
    )
    loaders = _deploying(rig, clock, deploys)
    seen: list[set[tuple[int, str]]] = []
    original = loaders.sleep

    def sleep(seconds: float) -> None:
        original(seconds)
        if CLOSINGS_PATH in server.objects:
            seen.append(_lit(server))

    code = _run(
        ["live", "run", "--until", "+12m", *_common(tmp_path, server)],
        replace(loaders, sleep=sleep),
        monkeypatch,
    )
    assert code == 0
    assert seen
    assert all(found == {(0, "CLOSED"), (7, "DELAYED")} for found in seen)
    assert _events(tmp_path) == ["lit", "lit"]  # no dark-then-lit flap in the history
    assert _timeline(server).statuses == (Status.CLOSED, Status.DELAYED)
    out = capsys.readouterr().out
    assert "ALERT" not in out
    assert "blank" not in out


def test_a_settled_new_deployment_that_cannot_be_read_blanks_every_stamp(tmp_path: Path) -> None:
    world = World()
    host = Host(tmp_path / "host")
    other = DirectoryStamp(generated_on=date(2026, 10, 15), schools=11, districts=6)
    for mode, stamp in ((Mode.ON, STAMP), (Mode.SHADOW, other)):
        LivePublisher(
            host=host,
            directory=world.dir,
            state_dir=tmp_path / f"state-{mode.value}",
            internal_dir=tmp_path / "i",
            mode=mode,
        ).publish(storm(world), now=MORNING, healthy_share=1.0, edition=equal(MORNING, stamp))
    publisher = LivePublisher(
        host=host,
        directory=world.dir,
        state_dir=tmp_path / "state-shadow",
        internal_dir=tmp_path / "i",
    )
    later = MORNING + timedelta(minutes=5)
    unread = EditionVerdict(EditionState.UNREADABLE, later, blank_every=True, alert=True)
    report = publisher.publish(storm(world, later), now=later, healthy_share=1.0, edition=unread)
    assert (report.exit, report.alert, report.blank) == (Exit.REFUSED, True, True)
    for prefix, stamp in (("v1", STAMP), (SHADOW, other)):
        found = ClosingsFile.from_json_bytes((tmp_path / "host" / prefix / CLOSINGS).read_bytes())
        assert (found.days, found.directory) == ((), stamp)


def test_an_in_progress_deployment_keeps_the_verdict_and_a_settled_one_does_not() -> None:
    clock = Clock(MORNING)
    deploys = Deploys(clock, MORNING + timedelta(minutes=1), MORNING + timedelta(minutes=40))
    watch = EditionWatch(own=OWN, source=PagesDeployed(deploys))  # type: ignore[arg-type]
    assert watch.check(MORNING, published=(OWN.stamp(),)).state is EditionState.EQUAL
    clock.now = MORNING + timedelta(minutes=2)
    kept = watch.check(clock.now, published=(OWN.stamp(),))
    assert (kept.state, kept.wants_blank, kept.alert) == (EditionState.KEPT, False, False)
    # in progress past the grace: refused and alerted, never blanked
    clock.now = MORNING + timedelta(minutes=31)
    late = watch.check(clock.now, published=(OWN.stamp(),))
    assert (late.state, late.wants_blank, late.alert) == (EditionState.UNREADABLE, False, True)


# --- S1 (data, operations): a blank racing a pass is never undone ---------------------------


def test_a_blank_landing_during_a_passs_upload_is_kept(
    tmp_path: Path, server: Server, clock: Clock, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    common = _common(tmp_path, server)
    assert _run(["live", "once", *common], _loaders(rig, clock), monkeypatch) == 0
    loop = rig.ingests[-1]
    original = R2Publisher.write
    fired: list[int] = []

    def write(self: R2Publisher, files: Mapping[str, bytes]) -> None:
        if not fired and any(key.endswith("closings.json") for key in files):
            fired.append(-1)  # the blank's own writes pass straight through
            fired[0] = int(emergency_blank(_bucket(server), clock.now).exit)
        original(self, files)

    monkeypatch.setattr(R2Publisher, "write", write)
    _again(rig, clock, MORNING + timedelta(minutes=5, seconds=1))
    loop.publisher.memory.last_content = None  # the pass uploads
    report = loop.run_pass(
        [SourceRead("gray-synthetic", ReadOutcome.OK, clock.now, STORM)], clock.now
    )
    assert fired == [0]
    assert (report.exit, report.refusals) == (Exit.REFUSED, ("held",))
    assert _lit(server) == set()
    assert _timeline(server).gaps == ()
    # the history leaves out what the hold darkened
    log = ChangeLog(tmp_path / "state" / "changes")
    assert [c.fields.get(BY) for c in log.changes(date(2026, 11, 17)) if c.event is Event.DARK]
    rebuilt = timeline(
        date(2026, 11, 17),
        log.changes(date(2026, 11, 17)),
        directory=rig.world.dir,
        stamp=OWN.stamp(),
        generated_at=clock.now,
        final=False,
    )
    assert rebuilt is None


def test_a_hold_set_before_the_upload_refuses_it(pub: PublishRig) -> None:
    publisher = pub.publisher
    host = pub.host
    original = host.read
    hold = LiveHold(schema_version=1, held=True, at=MORNING, held_at=MORNING).to_json_bytes()
    reads = {"n": 0}

    def read(key: str) -> bytes | None:
        if key.endswith(HOLD):
            reads["n"] += 1
            return hold if reads["n"] > 1 else None  # clear at the pass's start, then set
        found: bytes | None = original(key)
        return found

    host.read = read  # type: ignore[method-assign]
    report = publisher.publish(
        storm(pub.world), now=MORNING, healthy_share=1.0, edition=equal(MORNING)
    )
    assert (report.exit, report.refusals) == (Exit.REFUSED, ("held",))
    assert not (pub.host.root / SHADOW / CLOSINGS).exists()


def test_the_github_guard_reads_the_hold_in_the_commit_it_builds_on() -> None:
    repo = Repo()
    publisher = _github(repo)
    guard = WriteGuard(f"v1/{HOLD}", holds)
    guarded_write(publisher, {"v1/live/closings.json": b'{"a":1}'}, guard)
    assert repo.tree()["v1/live/closings.json"] == b'{"a":1}'
    held = LiveHold(schema_version=1, held=True, at=MORNING, held_at=MORNING).to_json_bytes()
    publisher.write({f"v1/{HOLD}": held})
    head = repo.head
    with pytest.raises(GuardRefusedError):
        guarded_write(publisher, {"v1/live/closings.json": b'{"a":2}'}, guard)
    assert repo.head == head
    # a hold that does not read holds; a cleared one lets the write through
    assert holds(b"not json") is True
    assert holds(None) is False
    cleared = LiveHold(schema_version=1, held=False, at=MORNING, held_at=MORNING)
    publisher.write({f"v1/{HOLD}": cleared.to_json_bytes()})
    guarded_write(publisher, {"v1/live/closings.json": b'{"a":3}'}, guard)
    assert repo.tree()["v1/live/closings.json"] == b'{"a":3}'


def test_the_folder_guard_reads_before_it_writes(tmp_path: Path) -> None:
    host = Host(tmp_path)
    held = LiveHold(schema_version=1, held=True, at=MORNING, held_at=MORNING).to_json_bytes()
    host.write({f"v1/{HOLD}": held})
    with pytest.raises(GuardRefusedError):
        guarded_write(host, {"v1/live/closings.json": b"{}"}, WriteGuard(f"v1/{HOLD}", holds))
    assert not (tmp_path / "v1" / "live" / "closings.json").exists()


# --- S2 (data, operations): the hold is written whatever the clock says ----------------------


def test_a_blank_refused_for_the_clock_still_sets_the_hold(
    tmp_path: Path, server: Server, clock: Clock, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    common = _common(tmp_path, server)
    loaders = _loaders(rig, clock)
    assert _run(["live", "once", *common], loaders, monkeypatch) == 0
    loop = rig.ingests[-1]
    clock.now = MORNING - timedelta(minutes=3)  # the clock runs behind the published file
    assert _run(["live", "blank", *common], loaders, monkeypatch) == 3
    for prefix in (PREFIX, PUBLIC):
        assert json.loads(server.objects[f"{prefix}/hold.json"])["held"] is True
    assert _lit(server) != set()  # not yet: it would be stamped ahead
    # the running loop is held from its next pass, and blanks once the clock allows
    _again(rig, clock, MORNING + timedelta(minutes=5))
    report = loop.run_pass(
        [SourceRead("gray-synthetic", ReadOutcome.OK, clock.now, STORM)], clock.now
    )
    assert (report.exit, report.refusals) == (Exit.REFUSED, ("held",))
    assert _lit(server) == set()


def test_the_hold_write_failing_is_an_error_before_any_blank(tmp_path: Path) -> None:
    host = Host(tmp_path, fail_write=True)
    report = emergency_blank(host, MORNING)
    assert report.exit is Exit.ERROR
    assert report.note.startswith("hold:")
    host.fail_write = False
    assert release(host, MORNING).exit is Exit.OK


# --- S3 (data): a successor that lost its state continues the day ----------------------------


def test_a_cold_successor_keeps_the_days_history(
    tmp_path: Path, server: Server, clock: Clock, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    common = _common(tmp_path, server)
    loaders = _loaders(rig, clock)
    assert _run(["live", "once", *common], loaders, monkeypatch) == 0
    before = _timeline(server)
    shutil.rmtree(tmp_path / "state")  # the successor's state pull failed
    _again(rig, clock, MORNING + timedelta(minutes=40))
    assert _run(["live", "once", *common], loaders, monkeypatch) == 0
    after = _timeline(server)
    assert (after.minutes, after.statuses) == (before.minutes, before.statuses)
    assert _index(server) == (date.fromisoformat(DAY),)
    # the log took the day from the public file, and the publish added nothing to it
    assert _events(tmp_path) == ["lit", "lit"]


def test_the_index_is_written_even_when_it_lists_no_day(pub: PublishRig) -> None:
    publisher = pub.publisher
    world = pub.world
    world.read(MORNING - timedelta(days=1), [])
    world.read(MORNING - timedelta(minutes=5), [])
    world.read(MORNING, [row("SYNTHETIC Eastern School", "Schools are open")])
    stale = DayIndex.model_validate(
        {
            "schema_version": 1,
            "generated_at": MORNING - timedelta(days=1),
            "days": ({"day": date(2026, 11, 16), "schools": 3, "final": True},),
        }
    ).to_json_bytes()
    pub.host.write({f"{SHADOW}/live/days/index.json": stale})
    report = publisher.publish(
        world.publish(MORNING), now=MORNING, healthy_share=1.0, edition=equal(MORNING)
    )
    assert report.exit is Exit.OK
    index = DayIndex.from_json_bytes(pub.host.file("live/days/index.json"))
    assert index.days == ()


# --- S4 (data): a failed edition blank is tried again before the loop stops ------------------


def test_a_failed_edition_blank_is_retried_until_it_lands(
    tmp_path: Path, server: Server, clock: Clock, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    changed = OWN.model_copy(update={"content_sha256": "c" * 64})
    timed = Timed(clock, MORNING + timedelta(seconds=90), OWN, changed)
    loaders = _timed(rig, clock, timed)
    original = loaders.sleep

    def sleep(seconds: float) -> None:
        original(seconds)  # the host refuses writes for three minutes after the deploy
        server.fail_puts = timed.switch <= clock.now < timed.switch + timedelta(minutes=3)

    code = _run(
        ["live", "run", "--until", "+30m", *_common(tmp_path, server)],
        replace(loaders, sleep=sleep),
        monkeypatch,
    )
    assert code == 1  # the blank landed, but it failed first: the run reports the error
    assert _lit(server) == set()
    assert clock.now < MORNING + timedelta(minutes=10)  # stopped once the blank landed


def test_other_content_blanks_under_the_deployed_stamp_when_a_read_back_failed(
    tmp_path: Path, server: Server, clock: Clock, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    common = _common(tmp_path, server)
    loaders = _loaders(rig, clock)
    assert _run(["live", "once", *common], loaders, monkeypatch) == 0
    shutil.rmtree(tmp_path / "state")  # nothing remembered
    rig.edition = [OWN.model_copy(update={"content_sha256": "c" * 64})]
    _again(rig, clock, MORNING + timedelta(minutes=5))
    real = publish_module._read_closings
    calls = {"n": 0}

    def flaky(host: object, prefix: str) -> ClosingsFile | None:
        calls["n"] += 1
        if calls["n"] <= 2:  # both read-backs of the handshake fail (a passing 5xx)
            raise PublishError("read: HTTP 503")
        return real(host, prefix)  # type: ignore[arg-type]

    monkeypatch.setattr(publish_module, "_read_closings", flaky)
    assert _run(["live", "once", *common], loaders, monkeypatch) == 3
    assert _lit(server) == set()


# --- S6 (data): every edition mismatch raises the alert --------------------------------------


def test_other_content_under_a_new_stamp_alerts_at_once(pub: PublishRig) -> None:
    publisher = pub.publisher
    publisher.publish(storm(pub.world), now=MORNING, healthy_share=1.0, edition=equal(MORNING))
    later = MORNING + timedelta(minutes=5)
    other = DirectoryStamp(generated_on=date(2026, 10, 15), schools=11, districts=6)
    verdict = EditionVerdict(EditionState.DIFFERENT, later, deployed=other, alert=True)
    report = publisher.publish(
        storm(pub.world, later), now=later, healthy_share=1.0, edition=verdict
    )
    assert (report.exit, report.alert, report.blank) == (Exit.REFUSED, True, False)


def test_the_watch_alerts_on_other_content_and_never_on_a_kept_verdict() -> None:
    other = OWN.model_copy(update={"content_sha256": "d" * 64, "generated_on": date(2026, 10, 15)})
    watch = EditionWatch(own=OWN, source=Source([other]))
    assert watch.check(MORNING, published=(OWN.stamp(),)).alert
    watch = EditionWatch(own=OWN, source=Source([OWN, DeployedEditionError("HTTP 502")]))
    assert not watch.check(MORNING, published=()).alert
    assert not watch.check(MORNING + timedelta(minutes=5), published=()).alert
    assert watch.check(MORNING + timedelta(minutes=31), published=()).alert


# --- operations S3: a state goes dark only for a source due, and alerts ----------------------


def _ingest(world: World, tmp_path: Path) -> Ingest:
    return Ingest(
        ledger=world.ledger,
        resolver=world.resolver(),
        stations=world.stations,
        publisher=LivePublisher(
            host=Host(tmp_path / "host"),
            directory=world.dir,
            state_dir=tmp_path / "state",
            internal_dir=tmp_path / "internal",
        ),
        watch=EditionWatch(own=OWN, source=Source([OWN])),
        internal_dir=tmp_path / "internal",
        due=frozenset({"gray-synthetic"}),
    )


def test_a_source_not_due_never_darkens_its_states(tmp_path: Path) -> None:
    world = World()
    body = station("gray-gone", states=("KS",)).model_dump(mode="json")
    world.stations["gray-gone"] = Station.model_validate_json(
        json.dumps({**body, "status": "no_endpoint", "page_url": None})
    )
    world.read(MORNING - timedelta(days=1), [])
    world.read(MORNING - timedelta(minutes=5), [])
    # a row of a source with no endpoint, never derived (it is never read again)
    world.ledger.observe(
        "gray-gone",
        ReadOutcome.OK,
        MORNING - timedelta(minutes=5),
        (row("SYNTHETIC Alpha Elementary", "Open"),),
    )
    ingest = _ingest(world, tmp_path)
    assert ingest.undecided(MORNING) == {}
    report = ingest.run_pass(
        [SourceRead("gray-synthetic", ReadOutcome.OK, MORNING, STORM)], MORNING
    )
    assert report.exit is Exit.OK
    assert report.counts["unknown_states"] == 0


def test_a_source_whose_say_stays_unknown_alerts_on_the_second_pass(tmp_path: Path) -> None:
    world = World()
    world.stations["gray-other"] = station("gray-other", states=("KS",))
    world.read(MORNING - timedelta(days=1), [])
    world.read(MORNING - timedelta(minutes=5), [])
    ingest = _ingest(world, tmp_path)
    real = ingest.ledger.observe

    def observe(source_id: str, *args: object, **kwargs: object) -> object:
        if source_id == "gray-other":
            raise ValueError("SYNTHETIC Alpha Elementary closed due to snow")
        return real(source_id, *args, **kwargs)  # type: ignore[arg-type]

    ingest.ledger.observe = observe  # type: ignore[method-assign, assignment]
    reads = [
        SourceRead("gray-synthetic", ReadOutcome.OK, MORNING, STORM),
        SourceRead("gray-other", ReadOutcome.OK, MORNING, ()),
    ]
    first = ingest.run_pass(reads, MORNING)
    assert (first.exit, first.alert) == (Exit.OK, False)
    assert ingest.failed == {"gray-other"}
    assert first.counts["unknown_states"] == 1
    later = MORNING + timedelta(minutes=5)
    second = ingest.run_pass([replace(read, fetched_at=later) for read in reads], later)
    assert second.alert
    healthy = ingest.run_pass(
        [replace(reads[0], fetched_at=later + timedelta(minutes=5))], later + timedelta(minutes=5)
    )
    assert not healthy.alert


# --- operations S4, S5: exit codes and isolated writes ---------------------------------------


def test_a_failed_push_after_a_refused_pass_exits_1(
    tmp_path: Path, server: Server, clock: Clock, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig.edition = [None]  # nothing deployed: the pass is refused
    loaders = _loaders(rig, clock)
    store = tmp_path / "store"
    store.write_text("a file where the store's folder should be", encoding="utf-8")
    code = _run(["live", "once", "--push", *_common(tmp_path, server)], loaders, monkeypatch)
    assert code == 1


def test_the_worst_exit_wins() -> None:
    assert live_cli.worst(Exit.OK, Exit.REFUSED) is Exit.REFUSED
    assert live_cli.worst(Exit.ERROR, Exit.REFUSED, Exit.OK) is Exit.ERROR
    assert live_cli.worst(Exit.OK) is Exit.OK


def test_a_failed_health_write_keeps_the_passs_exit(tmp_path: Path) -> None:
    world = World()
    world.read(MORNING - timedelta(days=1), [])
    world.read(MORNING - timedelta(minutes=5), [])
    ingest = _ingest(world, tmp_path)
    (tmp_path / "internal").mkdir(parents=True)
    (tmp_path / "internal" / "health.json").mkdir()  # a folder where the file goes
    report = ingest.run_pass(
        [SourceRead("gray-synthetic", ReadOutcome.OK, MORNING, STORM)], MORNING
    )
    assert report.exit is Exit.OK
    found = ClosingsFile.from_json_bytes((tmp_path / "host" / SHADOW / CLOSINGS).read_bytes())
    assert len(found.closings()) == 2


def test_a_day_timeline_seeds_the_change_log_it_was_built_from() -> None:
    world = World()
    day = date(2026, 11, 17)
    base = at("2026-11-17 06:00")
    ids = sorted(world.dir.schools, key=lambda nces_id: world.dir.schools[nces_id].index)
    changes = []
    for n, nces_id in enumerate(ids[:4]):
        delayed = Shown(int(Status.DELAYED), int(Reason.WINTER_STORM), 120, 600)
        closed = Shown(int(Status.CLOSED), None, None, None)
        changes.append(
            Change(base + timedelta(minutes=300 + n), day, nces_id, Event.LIT, delayed, {})
        )
        changes.append(
            Change(base + timedelta(minutes=400 + n), day, nces_id, Event.CHANGED, closed, {})
        )
        if n % 2:
            changes.append(
                Change(base + timedelta(minutes=500), day, nces_id, Event.DARK, None, {})
            )
    later = base + timedelta(hours=12)
    made = timeline(day, changes, directory=world.dir, stamp=STAMP, generated_at=later, final=False)
    assert made is not None
    seeded = seed_changes(made, world.dir)
    assert all(change.fields == {BY: BY_SEED} for change in seeded)
    again = timeline(day, seeded, directory=world.dir, stamp=STAMP, generated_at=later, final=False)
    assert again == made
