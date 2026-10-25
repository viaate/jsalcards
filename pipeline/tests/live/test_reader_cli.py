"""The reader's command-line pieces (S8-E): the log redaction paths, ``live finish`` and the
``chain`` alert, ``live state export``, a D1 pull retried with its holds merged, and the
overrides-only run. SYNTHETIC world, host and state."""

import argparse
import gc
import json
import logging
import sys
import threading
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from live.test_cli import (
    MORNING,
    Clock,
    Rig,
    Server,
    _common,
    _loaders,
    _run,
    make_rig,
    serve,
)
from live.test_d1_store import FakeD1
from snowlight import cli
from snowlight.live import cli as live_cli
from snowlight.live.cadence import Cadence
from snowlight.live.d1 import D1Error, D1StateStore
from snowlight.live.history import seed_changes
from snowlight.live.merge import AdminStatus
from snowlight.live.pool import MAX_ABANDONED
from snowlight.live.publish import day_path
from snowlight.live.state import ARCHIVE, check_export
from snowlight.schemas.live import ClosingsFile, DayTimeline
from snowlight.schemas.vocab import Status

WORDS = "SYNTHETIC Alpha School closed due to snow"


@pytest.fixture
def clock() -> Clock:
    return Clock(MORNING)


@pytest.fixture
def rig() -> Rig:
    return make_rig()


@pytest.fixture
def server(clock: Clock) -> Iterator[Server]:
    yield from serve(clock)


def test_no_library_warning_or_uncaught_exception_prints_page_words(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    live_cli.configure_logging()
    logging.getLogger("py.warnings").warning("parse.py:12: UserWarning: %s", WORDS)
    logging.getLogger("bs4").error("markup: %s", WORDS)
    logging.getLogger("httpx").warning("HTTP Request: GET https://synthetic.example/%s", WORDS)
    logging.getLogger("snowlight.live.test").error("our own line, codes only")
    try:
        raise ValueError(WORDS)
    except ValueError as error:
        sys.excepthook(type(error), error, error.__traceback__)
    err = capsys.readouterr().err
    assert "a warning (UserWarning)" in err
    assert "a library message" in err
    assert "our own line, codes only" in err
    assert "snowlight live: error: ValueError" in err
    assert "SYNTHETIC" not in err
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING


def _dir_config(tmp_path: Path) -> Path:
    path = tmp_path / "live.yaml"
    path.write_text(
        f"""host:
  kind: dir
  folder: {tmp_path / "host"}
state:
  kind: local
  folder: {tmp_path / "box"}
site: https://synthetic.example
site_repository: viaate/synthetic
""",
        encoding="utf-8",
    )
    return path


def _finish(
    tmp_path: Path, code: str, *extra: str, state: Path | None = None, run: str = ""
) -> int:
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "live",
            "finish",
            "--exit",
            code,
            *extra,
            "--config",
            str(_dir_config(tmp_path)),
            "--state",
            str(state or tmp_path / "state"),
        ]
    )
    env = {"LIVE_PUBLISH": "", "GITHUB_RUN_ID": run}
    loaders = replace(live_cli.Loaders(), env=lambda: env, notice=lambda _env: None)
    return int(args.handler(args, loaders))


def _codes(state: Path) -> list[int]:
    return [code for _, code in live_cli._exits(state / live_cli.EXITS)]


def _state(tmp_path: Path, action: str, state: Path) -> int:
    parser = cli.build_parser()
    argv = ["live", "state", action, "--config", str(_dir_config(tmp_path)), "--state", str(state)]
    args = parser.parse_args(argv)
    return int(args.handler(args, replace(live_cli.Loaders(), env=dict)))


def test_the_chain_alert_counts_exits_across_runs_through_the_state_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # each run has its own folder, as each runner does: the exit goes into the state before
    # the end push (live finish --record), so the next run pulls it and its closing step sees
    # two failures in a row
    first, second, third = (tmp_path / name for name in ("run-1", "run-2", "run-3"))
    assert _state(tmp_path, "pull", first) == 0
    assert _finish(tmp_path, "1", "--record", state=first, run="101") == 0
    assert _state(tmp_path, "push", first) == 0
    assert _finish(tmp_path, "1", state=first, run="101") == 0
    assert not (tmp_path / "host" / "v1-shadow" / "live" / "alerts.json").exists()
    assert _state(tmp_path, "pull", second) == 0
    assert _codes(second) == [1]
    assert _finish(tmp_path, "none", "--killed", "--record", state=second, run="102") == 0
    assert _state(tmp_path, "push", second) == 0
    assert _finish(tmp_path, "none", "--killed", state=second, run="102") == 0
    assert _open(tmp_path) == ["chain"]
    assert "live-read exit 124 recorded in the state" in capsys.readouterr().out
    # the closing step replaces the recorded exit with its own (a failed end push is exit
    # 1), never counting one run twice; a run that exits 0 closes the chain
    assert _state(tmp_path, "pull", third) == 0
    assert _finish(tmp_path, "0", "--record", state=third, run="103") == 0
    assert _finish(tmp_path, "0", "--push", "failure", state=third, run="103") == 0
    assert _codes(third) == [1, 124, 1]
    assert _finish(tmp_path, "0", state=third, run="103") == 0
    assert _codes(third) == [1, 124, 0]
    assert _alerts(tmp_path)["open"] == []


def _open(tmp_path: Path) -> list[str]:
    return [str(entry["kind"]) for entry in _alerts(tmp_path)["open"]]


def _alerts(tmp_path: Path) -> dict[str, list[dict[str, object]]]:
    found = json.loads(
        (tmp_path / "host" / "v1-shadow" / "live" / "alerts.json").read_text(encoding="utf-8")
    )
    assert isinstance(found, dict)
    return found


def test_finish_reports_the_exit_and_raises_chain_after_two_failures(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "d1.json").write_text(
        '{"epoch": 3, "bytes": 4000000, "pushes": 7, "day_rows": 900}'
    )
    assert _finish(tmp_path, "1") == 0
    out = capsys.readouterr().out
    assert "::error::live-read exit 1: a persistent failure" in out
    assert (
        "::notice::live-read summary: exit 1; state bytes 4000000; d1 pushes 7; d1 rows today 900"
        in out
    )
    assert not (
        tmp_path / "host" / "v1-shadow" / "live" / "alerts.json"
    ).exists()  # one is not a chain
    assert _finish(tmp_path, "none", "--killed") == 0
    assert _open(tmp_path) == ["chain"]
    assert _finish(tmp_path, "0") == 0
    assert _alerts(tmp_path)["open"] == []
    assert _codes(tmp_path / "state") == [1, 124, 0]
    assert _finish(tmp_path, "3", "--dispatch-failed") == 0
    assert _open(tmp_path) == ["chain"]


def test_a_routine_exit_3_closes_an_open_chain_and_a_cancel_leaves_it(tmp_path: Path) -> None:
    # exit 3 (a refused pass, routine in a 320-minute run) is a healthy run: it closes the
    # chain as exit 0 does; a cancelled run (no exit) changes nothing
    assert _finish(tmp_path, "1") == 0
    assert _finish(tmp_path, "1") == 0
    assert _open(tmp_path) == ["chain"]
    assert _finish(tmp_path, "none") == 0
    assert _open(tmp_path) == ["chain"]
    assert _finish(tmp_path, "3") == 0
    assert _alerts(tmp_path)["open"] == []
    assert _codes(tmp_path / "state") == [1, 1, 3]
    for failed in ("1", "124"):
        assert _finish(tmp_path, failed) == 0
    assert _open(tmp_path) == ["chain"]
    assert _finish(tmp_path, "3", "--push", "failure") == 0  # a failed end push is exit 1
    assert _open(tmp_path) == ["chain"]


def test_state_export_writes_the_allowlist_archive(tmp_path: Path) -> None:
    state = tmp_path / "state"
    (state / "morning").mkdir(parents=True)
    (state / "morning" / "2026-11-17.json").write_text("{}", encoding="utf-8")
    (state / "unmatched.json").write_text('{"SYNTHETIC": "name"}', encoding="utf-8")
    parser = cli.build_parser()
    args = parser.parse_args(
        ["live", "state", "export", "--state", str(state), "--out", str(tmp_path / "store")]
    )
    assert args.handler(args) == 0
    names = check_export((tmp_path / "store" / ARCHIVE).read_bytes())
    assert names == ["ledger.sqlite", "morning/2026-11-17.json"]


def test_a_d1_pull_is_retried_and_its_holds_merged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: Clock
) -> None:
    api = FakeD1()
    env = {"GITHUB_WORKFLOW": "live-read", "GITHUB_RUN_ID": "77"}
    seeded = D1StateStore(api, env, clock)
    seeded.take(tmp_path / "seed")
    seeded.put_holds([("gray-synthetic", MORNING + timedelta(hours=10), "blocked")])
    failures = [2]
    real = api.databases

    def flaky(name: str) -> list[tuple[str, str]]:
        if failures[0]:
            failures[0] -= 1
            raise D1Error("list databases: HTTP 503")
        return real(name)

    api.databases = flaky  # type: ignore[method-assign]
    monkeypatch.setattr(live_cli, "make_store", lambda _c, _e, _h: D1StateStore(api, env, clock))
    slept: list[float] = []
    loaders = replace(live_cli.Loaders(), clock=clock, sleep=slept.append, env=lambda: env)
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "live",
            "state",
            "pull",
            "--retry",
            "--config",
            str(_dir_config(tmp_path)),
            "--state",
            str(tmp_path / "state"),
        ]
    )
    assert args.handler(args, loaders) == 0
    assert slept == [10.0, 10.0]
    clocks = Cadence._load(tmp_path / "state" / "cadence.json")
    assert clocks["gray-synthetic"].not_before == MORNING + timedelta(hours=10)
    # without --retry one failure fails the step (the loop then runs overrides-only)
    failures[0] = 1
    args = parser.parse_args(
        [
            "live",
            "state",
            "pull",
            "--config",
            str(_dir_config(tmp_path)),
            "--state",
            str(tmp_path / "s2"),
        ]
    )
    assert args.handler(args, loaders) == 1


def test_overrides_only_publishes_the_admin_alone_and_ends_when_the_database_answers(  # noqa: PLR0913, PLR0917 - fixtures
    tmp_path: Path,
    server: Server,
    clock: Clock,
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    base = _loaders(rig, clock)
    nces = next(nces for nces, school in rig.world.dir.schools.items() if school.index == 3)
    admin = AdminStatus(
        school=3, nces_id=nces, day=MORNING.date(), status=Status.CLOSED, shift_minutes=None,
        clock_minute=None, set_at=MORNING - timedelta(minutes=30), level="school", key="synthetic",
    )  # fmt: skip

    def parts(
        config: live_cli.LiveConfig, env: live_cli.Env, args: argparse.Namespace
    ) -> live_cli.Parts:
        made = base.parts(config, env, args)
        made.ingest.overrides = lambda _now: [admin]

        def reads(
            _now: datetime, _only: Sequence[str], _tick: Callable[[], None]
        ) -> Sequence[object]:
            raise AssertionError("an overrides-only run reads no source")

        return live_cli.Parts(made.ingest, reads)  # type: ignore[arg-type]

    answers = iter([False, False, True])
    loaders = replace(base, parts=parts, reachable=lambda _c, _e: next(answers))
    code = _run(
        ["live", "run", "--until", "+60m", "--overrides-only", *_common(tmp_path, server)],
        loaders,
        monkeypatch,
    )
    assert code == 0
    assert clock.now < MORNING + timedelta(minutes=16)  # it ended once the database answered
    shown = ClosingsFile.from_json_bytes(
        server.objects["/snowlight-live/v1-shadow/live/closings.json"]
    )
    assert [(row.school, row.status, row.manual) for row in shown.closings()] == [
        (3, Status.CLOSED, True)
    ]
    out = capsys.readouterr().out
    # the loop's notices for the soak report: its first pass's start and why it ended
    assert f"::notice::live-read first pass {MORNING.isoformat()}" in out
    assert "::notice::live-read end overrides" in out


def test_thread_and_unraisable_exceptions_print_their_type_only(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    monkeypatch.setattr(sys, "unraisablehook", sys.unraisablehook)
    live_cli.configure_logging()

    def fails() -> None:
        raise RuntimeError(WORDS)

    thread = threading.Thread(target=fails)
    thread.start()
    thread.join()

    class Leaky:
        def __del__(self) -> None:
            raise RuntimeError(WORDS)

    Leaky()
    gc.collect()
    err = capsys.readouterr().err
    assert "snowlight live: error in a thread: RuntimeError" in err
    assert "snowlight live: error that could not be raised: RuntimeError" in err
    assert "SYNTHETIC" not in err


def test_finish_counts_a_failed_end_push_and_a_directory_that_was_not_built(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _finish(tmp_path, "3", "--push", "failure") == 0
    out = capsys.readouterr().out
    assert "::error::live-read exit 1: end push: the state could not be kept" in out
    assert "::notice::live-read summary: exit 1;" in out
    assert not (tmp_path / "host" / "v1-shadow" / "live" / "alerts.json").exists()
    assert _finish(tmp_path, "", "--directory", "failure") == 0
    assert "::error::live-read exit 1: the directory could not be built" in capsys.readouterr().out
    assert _codes(tmp_path / "state") == [1, 1]
    assert _open(tmp_path) == ["chain"]  # no successor was started: the chain is broken
    alone = tmp_path / "alone"
    alone.mkdir()
    assert _finish(alone, "", "--directory", "failure") == 0
    assert _open(alone) == ["chain"]  # one such run is enough: it started no successor
    # a cancelled run (a mode change) records nothing
    assert _finish(tmp_path, "", "--directory", "success") == 0
    assert "live-read exit none" in capsys.readouterr().out
    assert _codes(tmp_path / "state") == [1, 1]


def test_finish_adds_the_host_size_and_the_token_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    parser = cli.build_parser()
    args = parser.parse_args(
        ["live", "finish", "--exit", "0", "--config", str(_dir_config(tmp_path)),
         "--state", str(tmp_path / "state")]
    )  # fmt: skip
    line = live_cli.limits_line(
        {"x-ratelimit-used": "212", "x-ratelimit-limit": "1000", "x-ratelimit-reset": "1793"},
        42504,
    )
    assert line == "live host size 42504 KB; github token used 212 of 1000 reset 1793"
    assert live_cli.limits_line({}, None) is None
    loaders = replace(live_cli.Loaders(), env=dict, notice=lambda _env: line)
    assert args.handler(args, loaders) == 0
    out = capsys.readouterr().out
    assert f"d1 rows today -; {line}" in out


def test_a_failed_end_push_raises_the_state_alert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Failing:
        def keep(self, _folder: Path, **_kwargs: object) -> None:
            raise D1Error("query: HTTP 503")

    monkeypatch.setattr(live_cli, "make_store", lambda _c, _e, _h: Failing())
    parser = cli.build_parser()
    args = parser.parse_args(
        ["live", "state", "push", "--config", str(_dir_config(tmp_path)),
         "--state", str(tmp_path / "state")]
    )  # fmt: skip
    loaders = replace(live_cli.Loaders(), env=lambda: {"LIVE_PUBLISH": ""})
    assert args.handler(args, loaders) == 1
    assert "D1Error: query: HTTP 503" in capsys.readouterr().err
    found = _alerts(tmp_path)["open"]
    assert [(entry["kind"], entry.get("why")) for entry in found] == [("state", "end_push")]


def test_a_pull_that_keeps_failing_gives_up_inside_its_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: Clock
) -> None:
    class Down:
        limited: float | None = None

        def limit(self, seconds: float) -> None:
            self.limited = seconds

        def take(self, _folder: Path) -> None:
            clock.now += timedelta(seconds=65)  # a hanging API: two 30-s tries and a pause
            raise D1Error("list databases: the Cloudflare API did not answer")

    down = Down()
    monkeypatch.setattr(live_cli, "make_store", lambda _c, _e, _h: down)

    def sleep(seconds: float) -> None:
        clock.now += timedelta(seconds=seconds)

    begin = clock.now
    loaders = replace(live_cli.Loaders(), clock=clock, sleep=sleep, env=dict)
    parser = cli.build_parser()
    args = parser.parse_args(
        ["live", "state", "pull", "--retry", "--config", str(_dir_config(tmp_path)),
         "--state", str(tmp_path / "state")]
    )  # fmt: skip
    assert args.handler(args, loaders) == 1
    assert down.limited == live_cli.PULL_FOR.total_seconds()
    assert clock.now - begin <= live_cli.PULL_FOR


@dataclass
class _Pool:
    abandoned: int


@dataclass
class _Reads:
    pool: _Pool


def _runner(left: int, store: object = None) -> live_cli.Runner:
    parts = live_cli.Parts(ingest=None, reads=_Reads(_Pool(left)))  # type: ignore[arg-type]
    config = live_cli.LiveConfig(host={}, state={}, site="", site_repository="")
    runner = live_cli.Runner(argparse.Namespace(), config, {}, parts, live_cli.Loaders(), store)
    runner.state = live_cli._Loop(due=MORNING, next_check=MORNING)
    return runner


def test_more_than_8_abandoned_threads_stop_the_run_with_exit_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = _runner(MAX_ABANDONED)
    runner.check_abandoned()
    assert runner.state.stop is None  # 8 still alive: the run goes on
    runner = _runner(MAX_ABANDONED + 1)
    runner.check_abandoned()
    assert runner.finish() == 1
    out = capsys.readouterr().out
    assert "9 abandoned reader threads; stopping for the successor" in out
    assert "exit 1: threads" in out
    assert "::notice::live-read end threads" in out


def test_a_run_with_threads_still_running_ends_the_process_at_once(
    capsys: pytest.CaptureFixture[str],
) -> None:
    ended: list[int] = []
    loaders = replace(live_cli.Loaders(), hard_exit=ended.append)
    parts = live_cli.Parts(ingest=None, reads=_Reads(_Pool(1)))  # type: ignore[arg-type]
    assert live_cli.leave(3, parts, loaders) == 3
    assert ended == [3]
    assert "1 reader threads still running: the process ends now (exit 3)" in (
        capsys.readouterr().out
    )
    calm = live_cli.Parts(ingest=None, reads=_Reads(_Pool(0)))  # type: ignore[arg-type]
    assert live_cli.leave(0, calm, loaders) == 0
    assert ended == [3]


def test_a_push_after_a_blank_too_close_to_the_grid_mark_waits(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class Store:
        kept = 0

        def keep(self, _folder: Path, **_kwargs: object) -> None:
            self.kept += 1

    store = Store()
    runner = _runner(0, store)
    runner.state.due = MORNING + timedelta(seconds=40)  # 10 s left before the push margin
    runner.push(MORNING, reason="blank")
    assert store.kept == 0
    assert runner.state.next_push == MORNING  # the idle time after the next pass pushes it
    assert "ALERT" not in capsys.readouterr().out


def _timeline(server: Server, nces: str, rig: Rig) -> list[tuple[str, int | None]]:
    """The public shadow day timeline's changes for one school: (event, status)."""
    made = DayTimeline.from_json_bytes(
        server.objects[f"/snowlight-live/v1-shadow/{day_path(MORNING.date())}"]
    )
    return [
        (change.event.value, None if change.shown is None else change.shown.status)
        for change in seed_changes(made, rig.world.dir)
        if change.nces_id == nces
    ]


def test_an_overrides_only_stretch_stays_dark_in_the_day_timeline_after_its_successor(
    tmp_path: Path,
    server: Server,
    clock: Clock,
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # run A publishes the lists and pushes; D1 is down for run B (overrides-only, cold, no
    # push: the list rows go dark on the map); run C pulls A's state. C's change log does
    # not hold B's dark stretch, so it takes it from the public day file before it publishes:
    # the history never shows the statuses as served while they were not
    common = _common(tmp_path, server)
    first = ["live", "once", "--push", *common[:2], "--state", str(tmp_path / "a"), *common[4:]]
    assert _run(first, _loaders(rig, clock), monkeypatch) == 0
    alpha = next(nces for nces, school in rig.world.dir.schools.items() if school.index == 0)
    lit = _timeline(server, alpha, rig)
    assert [event for event, _ in lit] == ["lit"]
    base = _loaders(rig, clock)

    def parts(
        config: live_cli.LiveConfig, env: live_cli.Env, args: argparse.Namespace
    ) -> live_cli.Parts:
        made = base.parts(config, env, args)
        nces = next(nces for nces, school in rig.world.dir.schools.items() if school.index == 3)
        admin = AdminStatus(
            school=3, nces_id=nces, day=MORNING.date(), status=Status.CLOSED, shift_minutes=None,
            clock_minute=None, set_at=MORNING, level="school", key="synthetic",
        )  # fmt: skip
        made.ingest.overrides = lambda _now: [admin]
        return made

    clock.now = MORNING + timedelta(minutes=20)
    answers = iter([False, True])
    dark = replace(base, parts=parts, reachable=lambda _c, _e: next(answers))
    argv = ["live", "run", "--until", "+30m", "--overrides-only", *common[:2]]
    argv += ["--state", str(tmp_path / "b"), *common[4:]]
    assert _run(argv, dark, monkeypatch) == 0
    assert [event for event, _ in _timeline(server, alpha, rig)] == ["lit", "dark"]
    clock.now = MORNING + timedelta(minutes=40)
    third = tmp_path / "c"
    pull = ["live", "state", "pull", *common[:2], "--state", str(third), *common[4:]]
    assert _run(pull, _loaders(rig, clock), monkeypatch) == 0
    again = ["live", "once", *common[:2], "--state", str(third), *common[4:]]
    assert _run(again, _loaders(rig, clock), monkeypatch) == 0
    assert [event for event, _ in _timeline(server, alpha, rig)] == ["lit", "dark", "lit"]
