"""The first critic round's findings, each as a class of fault with its regression test.

Every name, status, school and station here is SYNTHETIC. The CLI tests run against the
stub bucket of ``test_cli`` (a real HTTP server on 127.0.0.1 that checks SigV4).
"""

import argparse
import json
import logging
import shutil
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import httpx
import pytest

from live.test_cli import (
    CLOSINGS_PATH,
    MORNING,
    OWN,
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
from live.test_publish import SHADOW, STAMP, Host, equal, storm
from live.world import ALPHA_SCHOOL, PACIFIC, World, at, row, station
from snowlight.directory.deployed import DeployedEdition, DeployedEditionError, LiveDeployment
from snowlight.live import cli as live_cli
from snowlight.live.edition import EditionState, EditionVerdict, EditionWatch, PagesDeployed
from snowlight.live.history import ChangeLog, Event
from snowlight.live.ingest import Ingest, SourceRead
from snowlight.live.ledger import Outcome as ReadOutcome
from snowlight.live.merge import OpenSignal
from snowlight.live.publish import (
    CLOSINGS,
    DAYS,
    HOLD,
    Exit,
    LivePublisher,
    Memory,
    Mode,
    PassReport,
    day_path,
    emergency_blank,
    opens_file,
)
from snowlight.live.publishers import PublishError
from snowlight.live.reads import read_safely
from snowlight.schemas.directory import DirectoryEdition, DirectoryStamp
from snowlight.schemas.live import ClosingsFile, DayIndex, DayTimeline
from snowlight.schemas.vocab import Status

PREFIX = "/snowlight-live/v1-shadow/live"
PUBLIC = "/snowlight-live/v1/live"
DAY = "2026-11-17"
WORDS = ("synthetic alpha", "synthetic pacific", "due to snow", "hour delay", "closed due")


@pytest.fixture
def clock() -> Clock:
    return Clock(MORNING)


@pytest.fixture
def server(clock: Clock) -> Iterator[Server]:
    yield from serve(clock)


@pytest.fixture
def rig() -> Rig:
    return make_rig()


def _lit(server: Server, path: str = CLOSINGS_PATH) -> set[tuple[int, str]]:
    found = ClosingsFile.from_json_bytes(server.objects[path])
    return {(item.school, item.status.name) for item in found.closings()}


def _events(tmp_path: Path, day: str = DAY) -> list[str]:
    log = ChangeLog(tmp_path / "state" / "changes")
    return [change.event.value for change in log.changes(date.fromisoformat(day))]


def _timeline(server: Server, prefix: str = PREFIX, day: str = DAY) -> DayTimeline:
    return DayTimeline.from_json_bytes(server.objects[f"{prefix}/days/{day}.json"])


def _env(loaders: live_cli.Loaders, **extra: str) -> live_cli.Loaders:
    env = {**loaders.env(), **extra}
    return replace(loaders, env=lambda: env)


def _again(rig: Rig, clock: Clock, when: datetime) -> None:
    """The same rows read again at ``when`` (a later pass sees the storm still listed)."""
    clock.now = when
    rig.world.ledger.observe("gray-synthetic", ReadOutcome.OK, when - timedelta(minutes=1), STORM)


# --- B1 (data): the pass clock is read after the reads -------------------------------------


def test_reads_finishing_after_the_pass_start_are_held_and_lit(
    tmp_path: Path, server: Server, clock: Clock, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig.lag = timedelta(seconds=20)  # every read finishes 20 s after the pass began
    base = _loaders(rig, clock)

    def parts(
        config: live_cli.LiveConfig, env: live_cli.Env, args: argparse.Namespace
    ) -> live_cli.Parts:
        made = base.parts(config, env, args)

        def reads(
            now: datetime, only: Sequence[str], tick: Callable[[], None]
        ) -> Sequence[SourceRead]:
            found = made.reads(now, only, tick)
            clock.now += rig.lag  # the clock moved while the reads ran
            return found

        return live_cli.Parts(made.ingest, reads)

    code = _run(
        ["live", "once", *_common(tmp_path, server)], replace(base, parts=parts), monkeypatch
    )
    assert code == 0
    assert _lit(server) == {(0, "CLOSED"), (7, "DELAYED")}
    published = ClosingsFile.from_json_bytes(server.objects[CLOSINGS_PATH])
    assert published.generated_at >= MORNING + rig.lag  # never older than the data it carries
    health = json.loads((tmp_path / "internal" / "health.json").read_text())
    assert "stale_source" not in health["withheld"]


def test_an_open_statement_dated_after_the_file_is_refused_not_hidden() -> None:
    later = at("2026-11-17 11:10")
    signal = OpenSignal(
        school=0,
        nces_id="200000100001",
        day=date(2026, 11, 17),
        at=later,
        source_id="gray-synthetic",
        source_type=None,
        confidence=None,
    )
    with pytest.raises(ValueError, match="dated after"):
        opens_file([signal], [], generated_at=at("2026-11-17 11:05"), stamp=STAMP)


# --- B2, B3 (data): blank on a same-stamp content change, from the host's stamp ------------


def test_a_same_stamp_content_change_blanks_even_after_the_state_is_lost(
    tmp_path: Path, server: Server, clock: Clock, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    loaders = _loaders(rig, clock)
    common = _common(tmp_path, server)
    assert _run(["live", "once", *common], loaders, monkeypatch) == 0
    assert _timeline(server).gaps  # the day file names schools
    shutil.rmtree(tmp_path / "state")  # a successor whose state pull failed
    rig.edition = [OWN.model_copy(update={"content_sha256": "c" * 64})]
    _again(rig, clock, MORNING + timedelta(minutes=5))
    assert _run(["live", "once", *common], loaders, monkeypatch) == 3
    blank = ClosingsFile.from_json_bytes(server.objects[CLOSINGS_PATH])
    assert (blank.days, blank.directory) == ((), OWN.stamp())
    # no public day file under that stamp names a school, and the index lists no day
    day = _timeline(server)
    assert (day.gaps, day.directory) == ((), OWN.stamp())
    assert DayIndex.from_json_bytes(server.objects[f"{PREFIX}/days/index.json"]).days == ()


def test_the_edition_blank_publishes_no_timeline_from_the_old_directory(
    tmp_path: Path, server: Server, clock: Clock, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    loaders = _loaders(rig, clock)
    common = _common(tmp_path, server)
    assert _run(["live", "once", *common], loaders, monkeypatch) == 0
    rig.edition = [OWN.model_copy(update={"content_sha256": "c" * 64})]
    _again(rig, clock, MORNING + timedelta(minutes=5))
    assert _run(["live", "once", *common], loaders, monkeypatch) == 3
    for key, body in server.objects.items():
        if "/days/" in key and not key.endswith("index.json"):
            assert DayTimeline.from_json_bytes(body).gaps == (), key
    # the change log says the map went dark (it is what the map showed)
    assert _events(tmp_path)[-2:] == ["dark", "dark"]


def test_a_new_deployment_that_cannot_be_read_keeps_no_verdict() -> None:
    @dataclass
    class Reader:
        newest: LiveDeployment
        fail: bool = False

        def newest_deployment(self) -> LiveDeployment:
            return self.newest

        def read(self) -> DeployedEdition:
            if self.fail:
                raise DeployedEditionError("artifact download: HTTP 502")
            return DeployedEdition(OWN.to_json_bytes(), "artifact")

    reader = Reader(LiveDeployment("success", MORNING, 1, "a" * 40))
    watch = EditionWatch(own=OWN, source=PagesDeployed(reader))  # type: ignore[arg-type]
    first = watch.check(MORNING, published=())
    assert first.state is EditionState.EQUAL
    # the same deployment, read again only from the cache: still equal
    reader.fail = True
    assert watch.check(MORNING + timedelta(minutes=1), published=()).state is EditionState.EQUAL
    # a settled new deployment whose edition cannot be read: no grace, blank every public
    # file under its own stamp (round 2, S5), and alert (round 2, S6)
    reader.newest = LiveDeployment("success", MORNING + timedelta(minutes=10), 2, "b" * 40)
    verdict = watch.check(MORNING + timedelta(minutes=20), published=(OWN.stamp(),))
    assert (verdict.state, verdict.ok, verdict.blank_every, verdict.alert) == (
        EditionState.UNREADABLE,
        False,
        True,
        True,
    )


# --- B4 (data) and B1 (operations): the emergency blank is a latch ------------------------


def test_blank_holds_every_later_pass_dark_until_release(
    tmp_path: Path, server: Server, clock: Clock, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    loaders = _loaders(rig, clock)
    common = _common(tmp_path, server)
    assert _run(["live", "once", *common], loaders, monkeypatch) == 0
    loop = rig.ingests[-1]  # a loop process that keeps running
    clock.now = MORNING + timedelta(minutes=1)
    assert _run(["live", "blank", *common], loaders, monkeypatch) == 0
    assert _lit(server) == set()
    held = json.loads(server.objects[f"{PREFIX}/hold.json"])
    assert held["held"] is True
    # the running loop's next pass: refused, and nothing lights again
    _again(rig, clock, MORNING + timedelta(minutes=5))
    report = loop.run_pass(
        [SourceRead("gray-synthetic", ReadOutcome.OK, clock.now, STORM)], clock.now
    )
    assert (report.exit, report.refusals) == (Exit.REFUSED, ("held",))
    assert _lit(server) == set()
    # a new process, and a loop of passes: all refused, all dark
    assert _run(["live", "once", *common], loaders, monkeypatch) == 3
    assert _run(["live", "run", "--until", "+11m", *common], loaders, monkeypatch) == 3
    assert _lit(server) == set()
    # the change log and the timeline agree with the file: lit, then dark at the hold
    assert _events(tmp_path) == ["lit", "lit", "dark", "dark"]
    day = _timeline(server)
    assert day.gaps == ()  # emptied by the blank: nothing public says lit
    # released: the next pass lights the map again from rows the source still lists; the
    # timeline leaves out what the hold darkened and shows the statuses from the release on
    # (round 2, B1)
    assert _run(["live", "release", "--prefix", "every", *common], loaders, monkeypatch) == 0
    _again(rig, clock, clock.now + timedelta(minutes=5))
    assert _run(["live", "once", *common], loaders, monkeypatch) == 0
    assert _lit(server) == {(0, "CLOSED"), (7, "DELAYED")}
    assert _events(tmp_path)[-2:] == ["lit", "lit"]
    day = _timeline(server)
    assert day.statuses == (Status.CLOSED, Status.DELAYED)
    released = (clock.now - at("2026-11-17 06:00")).total_seconds() // 60
    assert day.minutes[0] >= released - 1


def test_blank_darkens_every_prefix_whatever_the_publishing_switch(
    tmp_path: Path, server: Server, clock: Clock, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    loaders = _loaders(rig, clock)
    common = _common(tmp_path, server)
    on = _env(loaders, LIVE_PUBLISH="on")
    assert _run(["live", "once", *common], on, monkeypatch) == 0
    _again(rig, clock, MORNING + timedelta(minutes=5))
    assert _run(["live", "once", *common], loaders, monkeypatch) == 0  # shadow
    assert _lit(server, f"{PUBLIC}/closings.json") == _lit(server) != set()
    clock.now += timedelta(minutes=1)
    off = _env(loaders, LIVE_PUBLISH="off")
    assert _run(["live", "blank", *common], off, monkeypatch) == 0
    assert _lit(server, f"{PUBLIC}/closings.json") == _lit(server) == set()
    for prefix in (PUBLIC, PREFIX):
        assert json.loads(server.objects[f"{prefix}/hold.json"])["held"] is True


def test_a_host_error_in_blank_exits_1(
    tmp_path: Path, server: Server, clock: Clock, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    loaders = _loaders(rig, clock)
    common = _common(tmp_path, server)
    assert _run(["live", "once", *common], loaders, monkeypatch) == 0
    server.fail_puts = True
    assert _run(["live", "blank", *common], loaders, monkeypatch) == 1
    assert _run(["live", "release", "--prefix", "every", *common], loaders, monkeypatch) == 1


def test_a_hold_logs_a_western_school_dark_not_expired(tmp_path: Path) -> None:
    world = World()
    host = Host(tmp_path / "host")
    publisher = LivePublisher(
        host=host, directory=world.dir, state_dir=tmp_path / "state", internal_dir=tmp_path / "i"
    )
    morning = at("2026-11-17 15:00")  # 07:00 in Los Angeles
    world.read(morning - timedelta(days=1), [])
    world.read(morning - timedelta(minutes=5), [])
    world.read(morning, [row("SYNTHETIC Pacific School", "Closed due to snow")])
    merged = world.publish(morning)
    assert publisher.publish(
        merged, now=morning, healthy_share=1.0, edition=equal(morning)
    ).exit is (Exit.OK)
    late = at("2026-11-18 06:30")  # 22:30 in Los Angeles, the next day in New York
    assert emergency_blank(host, late).exit is Exit.OK
    later = late + timedelta(minutes=5)
    report = publisher.publish(
        world.publish(later), now=later, healthy_share=1.0, edition=equal(later)
    )
    assert report.refusals == ("held",)
    changes = ChangeLog(tmp_path / "state" / "changes").changes(date(2026, 11, 17))
    assert [(change.nces_id, change.event, change.at) for change in changes][-1] == (
        PACIFIC,
        Event.DARK,
        late,
    )


def test_a_hold_file_that_does_not_read_counts_as_a_hold(tmp_path: Path) -> None:
    world = World()
    host = Host(tmp_path / "host")
    publisher = LivePublisher(
        host=host, directory=world.dir, state_dir=tmp_path / "state", internal_dir=tmp_path / "i"
    )
    host.write({f"{SHADOW}/{HOLD}": b'{"held": "no"}'})
    report = publisher.publish(storm(world), now=MORNING, healthy_share=1.0, edition=equal(MORNING))
    assert report.refusals == ("held",)


# --- S3, S2 (data/operations): day files follow the stamp and the prefix -------------------


def test_a_final_day_is_published_again_under_a_new_stamp(
    tmp_path: Path, server: Server, clock: Clock, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    loaders = _loaders(rig, clock)
    common = _common(tmp_path, server)
    assert _run(["live", "once", *common], loaders, monkeypatch) == 0
    _again(rig, clock, MORNING + timedelta(days=2))
    assert _run(["live", "once", *common], loaders, monkeypatch) == 0
    assert _timeline(server).final
    restamped = OWN.model_copy(update={"generated_on": date(2026, 11, 19)})
    rig.edition = [restamped]
    _again(rig, clock, clock.now + timedelta(minutes=5))
    assert _run(["live", "once", *common], loaders, monkeypatch) == 0
    day = _timeline(server)
    assert (day.final, day.directory, len(day.gaps)) == (True, restamped.stamp(), 2)
    index = DayIndex.from_json_bytes(server.objects[f"{PREFIX}/days/index.json"])
    assert DAY in [entry.day.isoformat() for entry in index.days]


def test_switching_shadow_to_on_lists_only_days_published_under_v1(tmp_path: Path) -> None:
    world = World()
    host = Host(tmp_path / "host")
    state, internal = tmp_path / "state", tmp_path / "internal"
    shadow = LivePublisher(host=host, directory=world.dir, state_dir=state, internal_dir=internal)
    now = at("2026-11-17 11:05")
    shadow.publish(storm(world), now=now, healthy_share=1.0, edition=equal(now))
    late = at("2026-11-18 20:00")
    world.read(late, [])
    shadow.publish(world.publish(late), now=late, healthy_share=1.0, edition=equal(late))
    on = LivePublisher(
        host=host, directory=world.dir, state_dir=state, internal_dir=internal, mode=Mode.ON
    )
    later = late + timedelta(days=1, hours=1)
    world.read(later, [row(ALPHA_SCHOOL, "Closed due to snow")])
    report = on.publish(world.publish(later), now=later, healthy_share=1.0, edition=equal(later))
    assert report.exit is Exit.OK
    index = DayIndex.from_json_bytes((host.root / "v1" / DAYS).read_bytes())
    assert index.days
    for entry in index.days:
        assert (host.root / "v1" / day_path(entry.day)).is_file()


# --- S8/S7 (data/operations): write order and a partial write ------------------------------


@dataclass
class Partial(Host):
    """Writes file by file and fails at the first day file (a host without one commit)."""

    fail_at: str = "/live/days/"
    keys: list[str] = field(default_factory=list)

    def write(self, files: Mapping[str, bytes]) -> None:
        written: list[str] = []
        for key, body in files.items():
            self.keys.append(key)
            if self.fail_at and self.fail_at in key:
                raise PublishError(f"put {key}: HTTP 503", written=tuple(written))
            Host.write(self, {key: body})
            written.append(key)


def test_the_live_file_goes_first_and_a_partial_write_keeps_the_log(tmp_path: Path) -> None:
    world = World()
    host = Partial(tmp_path / "host")
    publisher = LivePublisher(
        host=host, directory=world.dir, state_dir=tmp_path / "state", internal_dir=tmp_path / "i"
    )
    merged = storm(world)
    report = publisher.publish(merged, now=MORNING, healthy_share=1.0, edition=equal(MORNING))
    assert report.exit is Exit.ERROR
    assert host.keys[:3] == [
        f"{SHADOW}/live/closings.json",
        f"{SHADOW}/live/opens.json",
        f"{SHADOW}/{day_path(date(2026, 11, 17))}",
    ]
    # the map changed: the change log and the memory say so; the next pass uploads it all
    log = ChangeLog(tmp_path / "state" / "changes").changes(date(2026, 11, 17))
    assert [change.event for change in log] == [Event.LIT, Event.LIT]
    assert publisher.memory.lit
    assert publisher.memory.last_content is None
    host.fail_at = ""
    host.keys.clear()
    later = MORNING + timedelta(minutes=1)
    again = publisher.publish(merged, now=later, healthy_share=1.0, edition=equal(later))
    assert again.exit is Exit.OK
    assert host.keys[-1] == f"{SHADOW}/{DAYS}"
    assert len(ChangeLog(tmp_path / "state" / "changes").changes(date(2026, 11, 17))) == 2


# --- B2 (operations): a torn change log never stops a start or the blank -------------------


def test_a_torn_change_log_line_is_skipped_and_dropped(  # noqa: PLR0913, PLR0917 - pytest fixtures
    tmp_path: Path,
    server: Server,
    clock: Clock,
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    loaders = _loaders(rig, clock)
    common = _common(tmp_path, server)
    assert _run(["live", "once", *common], loaders, monkeypatch) == 0
    log = tmp_path / "state" / "changes" / f"{DAY}.jsonl"
    data = log.read_bytes()
    log.write_bytes(data + data.splitlines()[0][:40])  # a killed append
    clock.now = MORNING + timedelta(minutes=2)
    assert _run(["live", "blank", *common], loaders, monkeypatch) == 0
    assert _run(["live", "release", "--prefix", "every", *common], loaders, monkeypatch) == 0
    _again(rig, clock, MORNING + timedelta(minutes=5))
    with caplog.at_level(logging.WARNING):
        assert _run(["live", "once", *common], loaders, monkeypatch) == 0
    assert any("do not read" in record.getMessage() for record in caplog.records)
    for line in log.read_bytes().splitlines():
        json.loads(line)  # the torn tail was dropped by the atomic rewrite
    # the hold was cleared before any pass saw it: the dark minutes are still recorded
    assert _events(tmp_path) == ["lit", "lit", "dark", "dark", "lit", "lit"]


def test_history_is_pruned_only_once_a_durable_copy_holds_it(tmp_path: Path) -> None:
    root = tmp_path / "changes"
    root.mkdir()
    old, recent = date(2026, 10, 1), date(2026, 11, 16)
    for day in (old, recent):
        (root / f"{day.isoformat()}.jsonl").write_text("", encoding="utf-8")
    log = ChangeLog(root)
    assert log.prune(date(2026, 11, 17)) == []
    (root / "durable.json").write_text('{"through": "2026-10-10"}', encoding="utf-8")
    assert log.prune(date(2026, 11, 17)) == [old]
    assert log.days() == [recent]


def test_a_change_log_day_leaves_the_state_only_once_an_evidence_database_holds_it(
    tmp_path: Path,
) -> None:
    import hashlib  # noqa: PLC0415

    from snowlight.live import kept  # noqa: PLC0415

    root = tmp_path / "changes"
    root.mkdir()
    today = date(2026, 12, 11)
    days = [today - timedelta(days=back) for back in (47, 46, 45, 1)]
    for day in days:
        (root / f"{day.isoformat()}.jsonl").write_text('{"SYNTHETIC": 1}\n', encoding="utf-8")
    log = ChangeLog(root)
    assert log.prune(today) == []  # nothing known held: nothing goes, however old
    digest = hashlib.sha256(b'{"SYNTHETIC": 1}\n').hexdigest()
    held = {
        name: {(kept.CHANGES, day.isoformat()): frozenset({digest}) for day in days}
        for name in kept.DATABASES
    }
    kept.record_answer(tmp_path, held, datetime.combine(today, time(12), tzinfo=UTC))
    # day 47 changed after it was kept: its new bytes are not held, and it stays
    (root / f"{days[0].isoformat()}.jsonl").write_text('{"SYNTHETIC": 2}\n', encoding="utf-8")
    assert log.prune(today) == [days[1]]  # day 46 goes; day 45 is still within 45 days
    assert log.days() == [days[0], days[2], days[3]]


# --- B3 (operations): isolation and redaction ----------------------------------------------


def test_one_failed_pass_never_ends_the_loop(  # noqa: PLR0913, PLR0917 - pytest fixtures
    tmp_path: Path,
    server: Server,
    clock: Clock,
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    loaders = _loaders(rig, clock)
    calls = {"n": 0}

    def parts(
        config: live_cli.LiveConfig, env: live_cli.Env, args: argparse.Namespace
    ) -> live_cli.Parts:
        made = loaders.parts(config, env, args)

        def reads(
            now: datetime, only: Sequence[str], tick: Callable[[], None]
        ) -> Sequence[SourceRead]:
            calls["n"] += 1
            if calls["n"] == 2:
                raise ValueError("SYNTHETIC Alpha Elementary closed due to snow")
            return made.reads(now, only, tick)

        return live_cli.Parts(made.ingest, reads)

    code = _run(
        ["live", "run", "--until", "+16m", *_common(tmp_path, server)],
        replace(loaders, parts=parts),
        monkeypatch,
    )
    assert code == 3  # S8-E: one failed pass is not a persistent failure (3 in a row are)
    assert calls["n"] == 4  # 11:05, 11:10 (failed), 11:15, 11:20
    out = capsys.readouterr()
    assert "ValueError" in out.err
    text = (out.out + out.err).casefold()
    for words in WORDS:
        assert words not in text


def test_a_failed_resolve_withholds_its_states_and_logs_its_type_only(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    world = World()
    world.stations["gray-other"] = station("gray-other", states=("KS",))
    world.read(MORNING - timedelta(days=1), [])
    world.read(MORNING - timedelta(minutes=5), [])
    world.read(MORNING - timedelta(minutes=5), [], source="gray-other")
    resolver = world.resolver()
    real = resolver.resolve

    class Broken:
        directory = resolver.directory
        pollable = resolver.pollable

        def resolve(self, found: object, present: object) -> object:
            if getattr(found, "id", "") == "gray-other":
                raise ValueError("SYNTHETIC Alpha Elementary closed due to snow")
            return real(found, present)  # type: ignore[arg-type]

    ingest = Ingest(
        ledger=world.ledger,
        resolver=Broken(),  # type: ignore[arg-type]
        stations=world.stations,
        publisher=LivePublisher(
            host=Host(tmp_path / "host"),
            directory=world.dir,
            state_dir=tmp_path / "state",
            internal_dir=tmp_path / "i",
        ),
        watch=EditionWatch(own=OWN_SMALL, source=Source([OWN_SMALL])),
        internal_dir=tmp_path / "i",
        due=frozenset({"gray-synthetic"}),
    )
    with caplog.at_level(logging.INFO):
        report = ingest.run_pass(
            [SourceRead("gray-synthetic", ReadOutcome.OK, MORNING, STORM)], MORNING
        )
    assert report.exit is Exit.OK
    assert ingest.failed == {"gray-other"}
    published = ClosingsFile.from_json_bytes((tmp_path / "host" / SHADOW / CLOSINGS).read_bytes())
    assert {(item.school, item.status.name) for item in published.closings()} == {(7, "DELAYED")}
    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "resolve gray-other: ValueError" in text
    assert "synthetic alpha" not in text.casefold()


OWN_SMALL = DirectoryEdition.model_validate(
    {**OWN.model_dump(mode="json"), "schools": 11, "districts": 6}
)


def test_a_station_read_that_raises_is_an_error_read() -> None:
    def boom() -> SourceRead | None:
        raise RuntimeError("SYNTHETIC page text")

    read = read_safely("gray-synthetic", boom)
    assert read is not None
    assert (read.source_id, read.outcome, read.rows) == ("gray-synthetic", ReadOutcome.ERROR, ())


def test_t15a_the_log_formatter_prints_an_errors_type_only() -> None:
    formatter = live_cli.RedactingFormatter()
    try:
        raise ValueError("input_value='SYNTHETIC Alpha Elementary closed due to snow'")
    except ValueError as error:
        record = logging.LogRecord(
            "snowlight.live",
            logging.ERROR,
            __file__,
            1,
            "pass failed: %s",
            ("ValueError",),
            (type(error), error, error.__traceback__),
        )
    text = formatter.format(record)
    assert text.endswith("pass failed: ValueError [ValueError]")
    assert "synthetic" not in text.casefold()
    assert "Traceback" not in text
    assert live_cli.describe(ValueError("SYNTHETIC words")) == "ValueError"
    assert "needs X" in live_cli.describe(live_cli.ConfigError("needs X"))


# --- B4 (operations), S4, S5 (data): the loop and the handshake -----------------------------


def test_a_failed_edition_read_at_start_does_not_end_the_loop(
    tmp_path: Path, server: Server, clock: Clock, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig.edition = [
        DeployedEditionError("synthetic API 502"),
        DeployedEditionError("synthetic API 502"),
        OWN,
    ]
    loaders = _loaders(rig, clock)
    start = clock.now
    code = _run(
        ["live", "run", "--until", "+60m", *_common(tmp_path, server)], loaders, monkeypatch
    )
    assert code == 3  # the first pass was refused (round 2: the worst pass's exit)
    # S8-E: the run went on to its last grid pass before the limit (12:00), then ended
    assert clock.now - start >= timedelta(minutes=55)
    assert _lit(server) == {(0, "CLOSED"), (7, "DELAYED")}


@dataclass
class Timed:
    """The deployed edition by the clock: ``before`` until ``switch``, then ``after``."""

    clock: Clock
    switch: datetime
    before: DirectoryEdition
    after: DirectoryEdition

    def read(self) -> DeployedEdition:
        found = self.before if self.clock.now < self.switch else self.after
        return DeployedEdition(data=found.to_json_bytes(), source="synthetic")


def _timed(
    rig: Rig, clock: Clock, timed: Timed, *, pass_takes: timedelta = timedelta(0)
) -> live_cli.Loaders:
    base = _loaders(rig, clock)

    def parts(
        config: live_cli.LiveConfig, env: live_cli.Env, args: argparse.Namespace
    ) -> live_cli.Parts:
        made = base.parts(config, env, args)
        made.ingest.watch = EditionWatch(own=OWN, source=timed)

        def reads(
            now: datetime, only: Sequence[str], tick: Callable[[], None]
        ) -> Sequence[SourceRead]:
            found = made.reads(now, only, lambda: None)
            for _ in range(int(pass_takes.total_seconds() // 30)):
                clock.now += timedelta(seconds=30)
                tick()
                rig.seen.append(server_lit(rig))
            return found

        return live_cli.Parts(made.ingest, reads)

    return replace(base, parts=parts)


def server_lit(rig: Rig) -> int:
    return len(rig.ingests[-1].publisher.read_back().closings())  # type: ignore[union-attr]


def test_a_restamp_between_passes_publishes_the_new_stamp_at_once(
    tmp_path: Path, server: Server, clock: Clock, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    restamped = OWN.model_copy(update={"generated_on": date(2026, 11, 17)})
    timed = Timed(clock, MORNING + timedelta(seconds=90), OWN, restamped)
    loaders = _timed(rig, clock, timed)
    # S8-E: a run ends after its last grid pass before the limit, so it runs to 11:10
    code = _run(["live", "run", "--until", "+6m", *_common(tmp_path, server)], loaders, monkeypatch)
    assert code == 0
    found = ClosingsFile.from_json_bytes(server.objects[CLOSINGS_PATH])
    assert found.directory == restamped.stamp()
    # 11:05, the restamp pass at once (11:06:30, not at the 11:10 pass), then 11:10
    assert [path for path in server.puts if path == CLOSINGS_PATH] == [CLOSINGS_PATH] * 3


def test_the_handshake_runs_while_a_long_pass_reads(
    tmp_path: Path, server: Server, clock: Clock, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    common = _common(tmp_path, server)
    assert _run(["live", "once", *common], _loaders(rig, clock), monkeypatch) == 0
    changed = OWN.model_copy(update={"content_sha256": "c" * 64})
    start = MORNING + timedelta(minutes=5)
    timed = Timed(clock, start + timedelta(seconds=45), OWN, changed)
    rig.seen = []
    _again(rig, clock, start)
    loaders = _timed(rig, clock, timed, pass_takes=timedelta(minutes=4))
    assert _run(["live", "once", *common], loaders, monkeypatch) == 3
    # blanked within about a minute of the deploy, long before the pass ended
    assert rig.seen[:1] == [2]
    assert 0 in rig.seen[:3]


def test_a_failed_blank_between_passes_exits_1(
    tmp_path: Path, server: Server, clock: Clock, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    changed = OWN.model_copy(update={"content_sha256": "c" * 64})
    timed = Timed(clock, MORNING + timedelta(seconds=90), OWN, changed)
    loaders = _timed(rig, clock, timed)
    common = _common(tmp_path, server)
    original = loaders.sleep

    def sleep(seconds: float) -> None:
        original(seconds)
        server.fail_puts = clock.now >= timed.switch

    assert (
        _run(
            ["live", "run", "--until", "+30m", *common], replace(loaders, sleep=sleep), monkeypatch
        )
        == 1
    )
    assert _lit(server) != set()  # the blank did not land, and the loop says so


def test_the_edition_blank_note_says_when_it_failed(tmp_path: Path) -> None:
    world = World()
    host = Host(tmp_path / "host")
    publisher = LivePublisher(
        host=host, directory=world.dir, state_dir=tmp_path / "state", internal_dir=tmp_path / "i"
    )
    publisher.publish(storm(world), now=MORNING, healthy_share=1.0, edition=equal(MORNING))
    host.fail_write = True
    later = MORNING + timedelta(minutes=1)
    changed = EditionVerdict(EditionState.DIFFERENT, later, blank=STAMP, deployed=STAMP)
    report = publisher.publish(storm(world, later), now=later, healthy_share=1.0, edition=changed)
    assert (report.exit, report.blank) == (Exit.ERROR, False)
    assert "the blank failed" in report.note


# --- S2/S4 (data/operations): the watchdog -------------------------------------------------


def _check(loaders: live_cli.Loaders, body: bytes | None) -> live_cli.Loaders:
    def answer(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404) if body is None else httpx.Response(200, content=body)

    return replace(loaders, client=lambda: httpx.Client(transport=httpx.MockTransport(answer)))


def test_the_watchdog_flags_a_future_file_another_stamp_and_a_missing_file(  # noqa: PLR0913, PLR0917 - pytest fixtures
    tmp_path: Path,
    server: Server,
    clock: Clock,
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    loaders = _loaders(rig, clock)
    common = _common(tmp_path, server)
    assert _run(["live", "once", *common], loaders, monkeypatch) == 0
    body = server.objects[CLOSINGS_PATH]
    check = ["live", "check", "--url", "https://synthetic.example/x.json", "--config", common[1]]
    assert _run(check, _check(loaders, body), monkeypatch) == 0
    capsys.readouterr()
    clock.now = MORNING - timedelta(hours=3)  # the file is three hours ahead of the clock
    assert _run(check, _check(loaders, body), monkeypatch) == 3
    assert "AHEAD" in capsys.readouterr().out
    clock.now = MORNING + timedelta(minutes=1)
    rig.edition[:] = [OWN.model_copy(update={"generated_on": date(2026, 11, 17)})]
    assert _run(check, _check(loaders, body), monkeypatch) == 3
    assert "STAMP" in capsys.readouterr().out
    rig.edition[:] = [DeployedEditionError("synthetic API 502")]
    assert _run(check, _check(loaders, body), monkeypatch) == 1
    assert _run([*check, "--no-edition"], _check(loaders, body), monkeypatch) == 0
    assert _run(check, _check(loaders, None), monkeypatch) == 3
    assert "MISSING" in capsys.readouterr().out


# --- S6 (operations): a failed state push is loud ------------------------------------------


def test_a_failed_state_push_alerts_and_exits_1(  # noqa: PLR0913, PLR0917 - pytest fixtures
    tmp_path: Path,
    server: Server,
    clock: Clock,
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "store").write_text("not a folder", encoding="utf-8")
    loaders = _loaders(rig, clock)
    assert _run(["live", "once", "--push", *_common(tmp_path, server)], loaders, monkeypatch) == 1
    assert "ALERT state push failed" in capsys.readouterr().out


def test_memory_from_before_the_day_records_still_loads(tmp_path: Path) -> None:
    path = tmp_path / "publish.json"
    memory = Memory().to_json()
    del memory["days"]
    path.write_text(json.dumps(memory), encoding="utf-8")
    assert Memory.load(path).days == {}  # every day file is published again


def test_a_blank_over_a_stamp_others_carry_needs_no_state(tmp_path: Path) -> None:
    host = Host(tmp_path / "host")
    assert emergency_blank(host, MORNING).note.endswith("none (nothing published)")
    stamp = DirectoryStamp(generated_on=date(2026, 10, 14), schools=11, districts=6)
    host.write(
        {
            f"v1/{CLOSINGS}": ClosingsFile.encode(
                (), generated_at=MORNING, directory=stamp
            ).to_json_bytes()
        }
    )
    host.server_time = MORNING - timedelta(minutes=5)
    report = emergency_blank(host, MORNING)
    assert (report.exit, report.refusals) == (Exit.REFUSED, ("clock_ahead",))


def test_a_failed_once_exits_1_and_prints_the_type_only(  # noqa: PLR0913, PLR0917 - pytest fixtures
    tmp_path: Path,
    server: Server,
    clock: Clock,
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    base = _loaders(rig, clock)

    def parts(
        config: live_cli.LiveConfig, env: live_cli.Env, args: argparse.Namespace
    ) -> live_cli.Parts:
        made = base.parts(config, env, args)

        def reads(
            _now: datetime, _only: Sequence[str], _tick: Callable[[], None]
        ) -> Sequence[SourceRead]:
            raise ValueError("SYNTHETIC Alpha Elementary closed due to snow")

        return live_cli.Parts(made.ingest, reads)

    loaders = replace(base, parts=parts)
    assert _run(["live", "once", *_common(tmp_path, server)], loaders, monkeypatch) == 1
    out = capsys.readouterr()
    assert "the pass failed: ValueError" in out.err
    assert "synthetic alpha" not in (out.out + out.err).casefold()


def test_a_failed_edition_check_is_logged_and_the_loop_goes_on(
    tmp_path: Path, server: Server, clock: Clock, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    checks = {"n": 0}

    def guard(_self: Ingest, _now: datetime) -> tuple[EditionVerdict, PassReport | None]:
        checks["n"] += 1
        raise RuntimeError("SYNTHETIC")

    monkeypatch.setattr(Ingest, "guard", guard)
    loaders = _loaders(rig, clock)
    common = _common(tmp_path, server)
    assert _run(["live", "run", "--until", "+7m", *common], loaders, monkeypatch) == 0
    assert checks["n"] >= 3  # in the first pass's reads, and between passes
    assert _lit(server) == {(0, "CLOSED"), (7, "DELAYED")}


def test_the_watchdog_reports_a_file_it_cannot_read(
    clock: Clock, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    loaders = _loaders(rig, clock)
    check = ["live", "check", "--url", "https://synthetic.example/x.json", "--no-edition"]

    def answer(status: int, body: bytes = b"") -> live_cli.Loaders:
        def respond(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, content=body)

        return replace(loaders, client=lambda: httpx.Client(transport=httpx.MockTransport(respond)))

    assert _run(check, answer(500), monkeypatch) == 1
    assert _run(check, answer(200, b"{}"), monkeypatch) == 1

    def down(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("SYNTHETIC")

    unreachable = replace(loaders, client=lambda: httpx.Client(transport=httpx.MockTransport(down)))
    assert _run(check, unreachable, monkeypatch) == 1


def test_errors_print_their_own_words_or_their_type() -> None:
    assert live_cli.describe(FileNotFoundError(2, "No such file or directory")) == (
        "FileNotFoundError: No such file or directory"
    )
    assert live_cli.describe(PublishError("put v1/live/closings.json: HTTP 503")).endswith("503")
    assert live_cli.describe(RuntimeError("SYNTHETIC page words")) == "RuntimeError"
