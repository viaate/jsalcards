"""The third critic round's blocking findings and the cheap should-fix items, each with its
regression test.

Every name, status, school and station here is SYNTHETIC. The CLI tests run against the
stub bucket of ``test_cli`` (a real HTTP server on 127.0.0.1 that checks SigV4).
"""

import argparse
import json
import logging
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import replace
from datetime import date, datetime, timedelta
from itertools import pairwise
from pathlib import Path

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
from live.test_fixes_r1 import Timed, _again, _events, _lit, _timed, _timeline
from snowlight.live import cli as live_cli
from snowlight.live import publish as publish_module
from snowlight.live.history import ChangeLog, content_of
from snowlight.live.ingest import Ingest, SourceRead
from snowlight.live.publish import LivePublisher, Mode, PassReport
from snowlight.live.publishers import Publisher, PublishError, R2Publisher
from snowlight.live.resolve import LiveDirectory
from snowlight.live.state import LocalStateStore
from snowlight.schemas.live import ClosingsFile

DAY = date(2026, 11, 17)
OTHER = OWN.model_copy(update={"content_sha256": "b" * 64})
"""The same stamp over other directory content (risk R6: a second same-day deploy)."""


@pytest.fixture
def clock() -> Clock:
    return Clock(MORNING)


@pytest.fixture
def server(clock: Clock) -> Iterator[Server]:
    yield from serve(clock)


@pytest.fixture
def rig() -> Rig:
    return make_rig()


def _switch_after_first_sleep(
    loaders: live_cli.Loaders, clock: Clock, then: Callable[[], None]
) -> live_cli.Loaders:
    calls = {"n": 0}

    def sleep(seconds: float) -> None:
        clock.sleep(seconds)
        calls["n"] += 1
        if calls["n"] == 1:
            then()

    return replace(loaders, sleep=sleep)


# --- B1 (data): the heartbeat is measured on the pass grid -----------------------------------


def test_unchanged_files_go_up_on_every_grid_pass_whatever_the_reads_take(
    tmp_path: Path, server: Server, clock: Clock, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = _loaders(rig, clock)
    takes = iter([40, 30, 45, 20, 50, 35, 25, 40, 30, 45, 20, 50, 30])
    starts: list[datetime] = []
    stamped: list[datetime] = []

    def parts(
        config: live_cli.LiveConfig, env: live_cli.Env, args: argparse.Namespace
    ) -> live_cli.Parts:
        made = base.parts(config, env, args)

        def reads(
            now: datetime, only: Sequence[str], tick: Callable[[], None]
        ) -> Sequence[SourceRead]:
            if CLOSINGS_PATH in server.objects:
                stamped.append(
                    ClosingsFile.from_json_bytes(server.objects[CLOSINGS_PATH]).generated_at
                )
            starts.append(now)
            found = made.reads(now, only, tick)
            clock.now += timedelta(seconds=next(takes))  # the reads take 20 to 50 s
            return found

        return live_cli.Parts(made.ingest, reads)

    code = _run(
        ["live", "run", "--until", "+60m", *_common(tmp_path, server)],
        replace(base, parts=parts),
        monkeypatch,
    )
    stamped.append(ClosingsFile.from_json_bytes(server.objects[CLOSINGS_PATH]).generated_at)
    uploads = sorted(set(stamped))
    assert code == 0
    assert len(starts) == 12
    assert len(uploads) == len(starts)  # every grid pass uploaded, though nothing changed
    assert max(b - a for a, b in pairwise(uploads)) <= timedelta(minutes=5, seconds=50)


def test_live_once_always_uploads(
    tmp_path: Path, server: Server, clock: Clock, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    # S8-E: ``live once`` (local and tests only) always uploads; the off-grid skip of an
    # unchanged pass under 4 minutes after the last upload is the loop's (test_handoff_gaps).
    loaders = _loaders(rig, clock)
    common = _common(tmp_path, server)
    assert _run(["live", "once", *common], loaders, monkeypatch) == 0
    first = server.objects[CLOSINGS_PATH]
    _again(rig, clock, MORNING + timedelta(minutes=2))  # a pass two minutes on: unchanged
    assert _run(["live", "once", *common], loaders, monkeypatch) == 0
    assert server.objects[CLOSINGS_PATH] != first
    memory = json.loads((tmp_path / "state" / "publish.v1-shadow.json").read_text(encoding="utf-8"))
    assert memory["last_upload_pass"] == (MORNING + timedelta(minutes=2)).isoformat()


# --- B2 (data): a successor continues a day only from a file built on its content ------------


def _permuted(directory: LiveDirectory) -> LiveDirectory:
    swap = {0: 1, 1: 0, 7: 10, 10: 7}
    schools = {
        nces_id: replace(school, index=swap.get(school.index, school.index))
        for nces_id, school in directory.schools.items()
    }
    return LiveDirectory(schools, directory.district_sizes, "synthetic-edition-2")


def _successor(rig: Rig, tmp_path: Path, directory: LiveDirectory) -> LivePublisher:
    return LivePublisher(
        host=rig.ingests[-1].publisher.host,
        directory=directory,
        state_dir=tmp_path / "state-b",
        internal_dir=tmp_path / "internal-b",
        mode=Mode.SHADOW,
    )


def test_a_cold_successor_skips_a_day_file_built_from_other_content(  # noqa: PLR0913, PLR0917
    tmp_path: Path,
    server: Server,
    clock: Clock,
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    loaders = _loaders(rig, clock)
    assert _run(["live", "once", *_common(tmp_path, server)], loaders, monkeypatch) == 0
    made = _timeline(server)
    assert made.content_sha256 == content_of(rig.world.dir)
    stamp = ClosingsFile.from_json_bytes(server.objects[CLOSINGS_PATH]).directory
    later = MORNING + timedelta(minutes=20)

    other = _successor(rig, tmp_path, _permuted(rig.world.dir))  # same stamp, other content
    assert content_of(other.directory) != made.content_sha256
    with caplog.at_level(logging.WARNING, logger="snowlight.live.publish"):
        other._seed(stamp, later)
    assert other.changes.changes(DAY) == []
    assert "built from other directory content" in caplog.text

    same = _successor(rig, tmp_path / "same", rig.world.dir)  # the content it was built on
    same._seed(stamp, later)
    logged = ChangeLog(tmp_path / "state" / "changes").changes(DAY)
    assert {change.nces_id for change in same.changes.changes(DAY)} == {
        change.nces_id for change in logged
    }


def test_content_of_is_the_edition_digest_or_a_digest_of_its_id() -> None:
    directory = make_rig().world.dir
    assert content_of(replace(directory, edition="d" * 64)) == "d" * 64
    found = content_of(directory)
    assert len(found) == 64
    assert found != content_of(replace(directory, edition="synthetic-edition-2"))


# --- B1 (operations): the handshake between passes alerts, records and counts ---------------


def test_a_blank_between_passes_alerts_is_recorded_and_pushed(  # noqa: PLR0913, PLR0917
    tmp_path: Path,
    server: Server,
    clock: Clock,
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    loaders = _switch_after_first_sleep(
        _loaders(rig, clock), clock, lambda: rig.edition.__setitem__(slice(None), [OTHER])
    )
    common = _common(tmp_path, server)
    code = _run(
        ["live", "run", *common, "--push-every", "30", "--until", "+20m"], loaders, monkeypatch
    )
    out = capsys.readouterr().out
    blank = next(line for line in out.splitlines() if "; blank;" in line)
    assert blank.startswith("exit 3: refusals edition")
    assert "ALERT" in blank
    assert code == 3
    assert _lit(server) == set()
    health = json.loads((tmp_path / "internal" / "health.json").read_text(encoding="utf-8"))
    assert health["check"]["edition"] == "different"
    assert health["check"]["alert"] is True
    assert health["check"]["gate"]["blank"] is True
    pulled = tmp_path / "pulled"
    LocalStateStore(tmp_path / "store").pull(pulled)
    stored = [change.event.value for change in ChangeLog(pulled / "changes").changes(DAY)]
    assert stored == _events(tmp_path)  # the dark lines reached the store
    assert stored[-1] == "dark"


def test_an_unverified_deployment_between_passes_alerts_without_a_blank(  # noqa: PLR0913, PLR0917
    tmp_path: Path,
    server: Server,
    clock: Clock,
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from snowlight.live.edition import EditionState, EditionVerdict  # noqa: PLC0415

    loaders = _loaders(rig, clock)
    common = _common(tmp_path, server)
    assert _run(["live", "once", *common], loaders, monkeypatch) == 0
    ingest = rig.ingests[-1]
    expired = EditionVerdict(EditionState.UNREADABLE, MORNING, note="Synthetic: down", alert=True)
    monkeypatch.setattr(Ingest, "check_edition", lambda _self, _now: expired)
    args = argparse.Namespace(push=False, state=tmp_path / "state", internal=tmp_path / "internal")
    config = live_cli.LiveConfig.load(Path(common[1]))
    runner = live_cli.Runner(args, config, {}, live_cli.Parts(ingest, lambda *_: ()), loaders)
    runner.state = live_cli._Loop(due=MORNING + timedelta(minutes=5), next_check=MORNING)
    runner.loop_check(MORNING)
    assert runner.state.stop is None
    assert "ALERT edition: unreadable; Synthetic: down" in capsys.readouterr().out
    health = json.loads((tmp_path / "internal" / "health.json").read_text(encoding="utf-8"))
    assert health["check"]["alert"] is True
    assert health["check"]["gate"] is None
    assert "gate" in health  # the last pass's health is kept beside it


def test_the_run_ending_inside_a_failing_blank_exits_1(  # noqa: PLR0913, PLR0917
    tmp_path: Path,
    server: Server,
    clock: Clock,
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def deploy() -> None:
        rig.edition[:] = [OTHER]
        server.fail_puts = True

    loaders = _switch_after_first_sleep(_loaders(rig, clock), clock, deploy)
    code = _run(["live", "run", *_common(tmp_path, server), "--until", "+6m"], loaders, monkeypatch)
    out = capsys.readouterr().out
    assert code == 1
    assert "ALERT" in out
    assert "the run ended while the blank was failing" in out


def test_a_blank_refused_for_the_clock_is_tried_again(  # noqa: PLR0913, PLR0917
    tmp_path: Path,
    server: Server,
    clock: Clock,
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    timed = Timed(clock, MORNING + timedelta(seconds=90), OWN, OTHER)
    real = publish_module._ahead

    def ahead(generated_at: datetime, host: Publisher, now: datetime) -> bool:
        # the host's clock lags for three minutes after the deploy
        late = timed.switch <= clock.now < timed.switch + timedelta(minutes=3)
        return late or real(generated_at, host, now)

    monkeypatch.setattr(publish_module, "_ahead", ahead)
    code = _run(
        ["live", "run", "--until", "+30m", *_common(tmp_path, server)],
        _timed(rig, clock, timed),
        monkeypatch,
    )
    out = capsys.readouterr().out
    assert "refusals edition,clock_ahead" in out
    assert "trying again at the next check" in out
    assert _lit(server) == set()  # it landed once the clock allowed
    assert code == 3  # S8-E: only a blank that keeps failing is an exit 1


def test_a_failed_push_in_the_loop_is_not_an_exit_1(  # noqa: PLR0913, PLR0917 - pytest fixtures
    tmp_path: Path,
    server: Server,
    clock: Clock,
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # S8-E: a push that fails in the loop is tried again at the next slot; only the end
    # step's push failing is a persistent failure (that process exits 1).
    (tmp_path / "store").write_text("not a folder", encoding="utf-8")  # every push fails
    loaders = _switch_after_first_sleep(
        _loaders(rig, clock), clock, lambda: rig.edition.__setitem__(slice(None), [OTHER])
    )
    code = _run(
        ["live", "run", *_common(tmp_path, server), "--push-every", "30", "--until", "+20m"],
        loaders,
        monkeypatch,
    )
    assert code == 3
    assert "ALERT state push failed" in capsys.readouterr().out


# --- S3 (operations): a hold that cannot be read after an upload counts as set ---------------


def test_an_unreadable_hold_after_the_upload_blanks_and_alerts(  # noqa: PLR0913, PLR0917
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
    real_write, real_read = R2Publisher.write, R2Publisher.read
    seen = {"raced": False, "after": False}

    def write(self: R2Publisher, files: Mapping[str, bytes]) -> None:
        if not seen["raced"] and any(key.endswith("closings.json") for key in files):
            seen["raced"] = True
            publish_module.emergency_blank(self, clock.now)  # live blank lands mid-pass
            real_write(self, files)
            seen["after"] = True
            return
        real_write(self, files)

    def read(self: R2Publisher, key: str) -> bytes | None:
        if seen["after"] and key.endswith("hold.json"):
            raise PublishError(f"read {key}: HTTP 503")
        return real_read(self, key)

    monkeypatch.setattr(R2Publisher, "write", write)
    monkeypatch.setattr(R2Publisher, "read", read)
    _again(rig, clock, MORNING + timedelta(minutes=6))
    capsys.readouterr()
    code = _run(["live", "once", *common], loaders, monkeypatch)
    out = capsys.readouterr().out
    assert code == 1
    assert "ALERT" in out
    assert "the hold could not be read after the upload: published blank" in out
    assert _lit(server) == set()


def test_unknown_hold_blanks_only_its_own_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = make_rig()
    publisher = LivePublisher(
        host=_NoHost(),
        directory=rig.world.dir,
        state_dir=tmp_path / "state",
        internal_dir=tmp_path / "internal",
        mode=Mode.SHADOW,
    )
    asked: list[Sequence[str]] = []

    def blank(_self: LivePublisher, **kwargs: object) -> PassReport:
        asked.append(kwargs.get("prefixes", ("own",)))  # type: ignore[arg-type]
        return PassReport(publish_module.Exit.OK, MORNING, blank=True)

    monkeypatch.setattr(LivePublisher, "blank", blank)
    report = publisher._unknown_hold(MORNING, {})
    assert asked == [("own",)]  # the default: the mode's own prefix only
    assert report.exit is publish_module.Exit.ERROR
    assert report.alert


class _NoHost:
    def read(self, key: str) -> bytes | None:  # pragma: no cover - never read
        raise AssertionError(key)

    def write(self, files: Mapping[str, bytes]) -> None:  # pragma: no cover - never written
        raise AssertionError(files)


# --- S5 (operations): release has the same catch-all as the other commands -----------------


def test_release_reports_any_error_as_a_line(  # noqa: PLR0913, PLR0917
    tmp_path: Path,
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clock: Clock,
    rig: Rig,
) -> None:
    def broken(_host: object, _now: datetime, _prefixes: object) -> PassReport:
        raise PermissionError(13, "Synthetic permission denied", "/synthetic/hold.json")

    monkeypatch.setattr(live_cli, "release", broken)
    code = _run(
        ["live", "release", "--prefix", "every", *_common(tmp_path, server)],
        _loaders(rig, clock),
        monkeypatch,
    )
    err = capsys.readouterr().err
    assert code == 1
    assert "error: release: PermissionError" in err
    assert "Traceback" not in err
