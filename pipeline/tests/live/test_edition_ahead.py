"""Code ahead of the deploy (S8-E ops 11). SYNTHETIC world and host.

``publish.json`` keeps the directory content each upload was made against. On an edition
mismatch:

* the deployed content is the last published one (this run checked out a directory-changing
  head before Preview deployed it): no blank; the pass is refused, the loop checks every 60 s
  and passes at once when the deploy matches;
* the deployed content is new (the deploy moved under a public stamp): blank at once, then
  stop for the successor, as before.
"""

import argparse
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

from live.test_cli import MORNING, Rig, make_rig
from live.test_edition import Source
from live.test_publish import Host
from live.world import World
from snowlight.live import cli as live_cli
from snowlight.live.edition import EditionState, EditionWatch
from snowlight.live.ingest import Ingest, SourceRead
from snowlight.live.publish import CLOSINGS, Exit, LivePublisher, Mode
from snowlight.schemas.directory import DirectoryEdition
from snowlight.schemas.live import ClosingsFile

SHADOW = "v1-shadow"


def _edition(digest: str) -> DirectoryEdition:
    return DirectoryEdition(
        schema_version=1,
        generated_on=date(2026, 10, 14),
        schools=11,
        districts=6,
        content_sha256=digest * 64,
    )


def _ingest(world: World, host: Host, tmp: Path, digest: str, deployed: Source) -> Ingest:
    directory = replace(world.dir, edition=digest * 64)
    publisher = LivePublisher(
        host=host,
        directory=directory,
        state_dir=tmp / "state",
        internal_dir=tmp / "i",
        mode=Mode.SHADOW,
    )
    return Ingest(
        ledger=world.ledger,
        resolver=world.resolver(),
        stations=world.stations,
        publisher=publisher,
        watch=EditionWatch(own=_edition(digest), source=deployed),
        internal_dir=tmp / "i",
    )


def _lit(host: Host) -> int:
    return len(
        ClosingsFile.from_json_bytes((host.root / SHADOW / CLOSINGS).read_bytes()).closings()
    )


def _reads(rig: Rig, at: datetime) -> list[SourceRead]:
    return [replace(read, fetched_at=at) for read in rig.reads]


def _first_run(host: Host, tmp: Path) -> Rig:
    rig = make_rig()  # the synthetic world warmed up, and one read of the storm
    ingest = _ingest(rig.world, host, tmp, "a", Source([_edition("a")]))
    assert ingest.run_pass(rig.reads, MORNING).exit is Exit.OK
    assert _lit(host) > 0
    return rig


def test_code_ahead_of_the_deploy_waits_without_a_blank_then_passes(tmp_path: Path) -> None:
    host = Host(tmp_path / "host")
    rig = _first_run(host, tmp_path)
    world = rig.world
    deployed = Source([_edition("a")])
    successor = _ingest(world, host, tmp_path, "b", deployed)  # new code, the old deploy
    later = MORNING + timedelta(minutes=5)
    report = successor.run_pass(_reads(rig, later), later)
    verdict = successor.last_verdict
    assert verdict is not None
    assert (verdict.state, verdict.ahead, verdict.wants_blank) == (
        EditionState.DIFFERENT,
        True,
        False,
    )
    assert report.exit is Exit.REFUSED
    assert "edition" in report.refusals
    assert _lit(host) > 0  # nothing was blanked: the public file still indexes the deploy
    deployed.answers[:] = [_edition("b")]  # Preview deployed this run's directory
    passed = successor.run_pass(
        _reads(rig, later + timedelta(minutes=1)), later + timedelta(minutes=1)
    )
    assert passed.exit is Exit.OK
    assert passed.edition == "equal"


def test_a_deploy_that_moved_under_the_public_stamp_blanks_at_once(tmp_path: Path) -> None:
    host = Host(tmp_path / "host")
    rig = _first_run(host, tmp_path)
    world = rig.world
    successor = _ingest(world, host, tmp_path, "a", Source([_edition("c")]))
    report = successor.run_pass(
        _reads(rig, MORNING + timedelta(minutes=5)), MORNING + timedelta(minutes=5)
    )
    assert report.blank
    assert _lit(host) == 0
    verdict = successor.last_verdict
    assert verdict is not None
    assert not verdict.ahead


def test_the_loop_waits_while_ahead_and_passes_when_the_deploy_matches(tmp_path: Path) -> None:
    host = Host(tmp_path / "host")
    rig = _first_run(host, tmp_path)
    world = rig.world
    deployed = Source([_edition("a")])
    ingest = _ingest(world, host, tmp_path, "b", deployed)
    config = live_cli.LiveConfig(
        host={"kind": "dir"},
        state={"kind": "local"},
        site="https://s.example",
        site_repository="o/r",
    )
    args = argparse.Namespace(push=False, state=tmp_path / "state", internal=tmp_path / "i")
    runner = live_cli.Runner(
        args, config, {}, live_cli.Parts(ingest, lambda *_: ()), live_cli.Loaders()
    )
    now = MORNING + timedelta(minutes=6)
    runner.state = live_cli._Loop(due=now + timedelta(minutes=4), next_check=now)
    for minute in range(3):
        runner.loop_check(now + timedelta(minutes=minute))
        assert runner.state.stop is None  # never stops for code ahead
        assert runner.state.ahead
    deployed.answers[:] = [_edition("b")]
    moment: datetime = now + timedelta(minutes=3)
    runner.loop_check(moment)
    assert (runner.state.due, runner.state.grid, runner.state.ahead) == (moment, False, False)
    assert _lit(host) > 0
