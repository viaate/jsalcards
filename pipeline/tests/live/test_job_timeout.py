"""S7 (S8-E follow-up): the worst case fits in live-read.yml's job timeout.

A job past its ``timeout-minutes`` is cancelled: no successor is dispatched (the restarters
start one 5-20 minutes on) and the end push never runs. Before S7 the loop's ``--until +320m``
counted from the loop's own start, so the set-up steps at their bounds (the directory at 10
minutes, the pull at 8) and a slow last pass took the job past 345 minutes with its end steps
still to run. The workflow now hands the loop the job's start, and the loop's last pass starts
by the job's start + 345 minutes less :data:`~snowlight.live.cli.JOB_RESERVE`, whatever the
set-up took. SYNTHETIC world, a loopback stub host, on a fake clock.
"""

from datetime import timedelta
from pathlib import Path

import pytest

from live.test_cli import Clock, Rig, Server, _common, _loaders, _run
from live.test_handoff_gaps import (  # noqa: F401 - fixtures
    STEP,
    _reading,
    _times,
    clock,
    rig,
    server,
)
from live.test_live_workflows import load, step, steps
from snowlight.live import cli as live_cli
from snowlight.live.pool import PASS_CAP_GRACE, PASS_DEADLINE

READS = timedelta(seconds=40)
LAST_PASS = timedelta(seconds=PASS_DEADLINE + PASS_CAP_GRACE + 90)
"""The last pass at worst: its reads cut 30 s after the 240-s deadline, then its resolve and
publish (each request bounded; 90 s allowed)."""
SUCCESSOR = timedelta(seconds=3 * 20 + 10 + 20)
"""The successor step at worst: three dispatches at curl's 20-s bound, the pauses between."""
END_PUSH = live_cli.END_PUSH_FOR + timedelta(seconds=40)
"""The end push at its bound, with the process's start and the record step before it."""
TAIL = timedelta(minutes=4)
"""Left for the closing report, the export, its check and the cache save (about a minute)."""


def test_the_reserve_covers_the_last_pass_and_the_end_steps_at_their_bounds() -> None:
    workflow = load("live-read.yml")
    job = workflow["jobs"]["read"]
    assert timedelta(minutes=job["timeout-minutes"]) == live_cli.JOB_MINUTES
    worst = LAST_PASS + live_cli.PULSE_GRACE + SUCCESSOR + END_PUSH + TAIL
    assert worst <= live_cli.JOB_RESERVE
    # the set-up before the loop is bounded too, so the loop always has most of its time:
    # checkout, uv and its sync at 15 minutes each (a hang ends there; a slow cache or git
    # day, measured at 2-9 s a step, still fits), the directory at 10, the pull at 8
    bounded = {
        str(item.get("id") or item.get("uses") or item.get("run")): int(
            item.get("timeout-minutes") or 0
        )
        for item in steps(workflow, "read")
    }
    setup = [
        minutes
        for key, minutes in bounded.items()
        if key.startswith(("actions/checkout", "astral-sh/setup-uv", "uv sync"))
    ]
    assert setup == [15, 15, 15]
    before_loop = timedelta(minutes=sum(setup) + bounded["directory"] + bounded["pull"])
    assert before_loop < live_cli.JOB_MINUTES - live_cli.JOB_RESERVE - timedelta(hours=4)


def test_the_workflow_hands_the_loop_the_jobs_start() -> None:
    workflow = load("live-read.yml")
    token = step(workflow, "read", "token")
    assert 'echo "LIVE_JOB_STARTED=$(date -u +%s)" >> "$GITHUB_ENV"' in str(token["run"])
    assert steps(workflow, "read")[0]["id"] == "token"  # the job's first step
    loop = str(step(workflow, "read", "loop")["run"])
    assert 'mode+=(--job-started "$LIVE_JOB_STARTED")' in loop
    assert loop.index("--job-started") < loop.index("setsid")


def test_a_late_loop_start_ends_by_the_jobs_limit(  # noqa: PLR0913, PLR0917 - fixtures
    tmp_path: Path,
    server: Server,  # noqa: F811 - the fixture
    clock: Clock,  # noqa: F811 - the fixture
    rig: Rig,  # noqa: F811 - the fixture
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    start = clock.now
    # the job started long enough ago that its limit falls 30 minutes into this run
    end_by = start + timedelta(minutes=30)
    started = end_by - live_cli.JOB_MINUTES + live_cli.JOB_RESERVE
    loaders = _reading(_loaders(rig, clock), clock, lambda: READS)
    assert _loop_with(tmp_path, server, loaders, monkeypatch, "+60m", int(started.timestamp())) == 0
    last = _times(server)[-1] - READS
    assert last < end_by
    assert last >= end_by - STEP
    assert clock.now < end_by + STEP  # it ended right after that pass, not at +60m
    assert "the job's limit ends this run by" in capsys.readouterr().out


def test_a_start_that_does_not_read_keeps_the_until(
    tmp_path: Path,
    server: Server,  # noqa: F811 - the fixture
    clock: Clock,  # noqa: F811 - the fixture
    rig: Rig,  # noqa: F811 - the fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = clock.now
    loaders = _reading(_loaders(rig, clock), clock, lambda: READS)
    assert _loop_with(tmp_path, server, loaders, monkeypatch, "+20m", "soon") == 0
    assert _times(server)[-1] - READS >= start + timedelta(minutes=15)
    assert live_cli.job_end_by(None) is None
    assert live_cli.job_end_by("") is None


def _loop_with(  # noqa: PLR0913, PLR0917 - the loop's parts
    tmp_path: Path,
    stub: Server,
    loaders: live_cli.Loaders,
    monkeypatch: pytest.MonkeyPatch,
    until: str,
    started: int | str,
) -> int:
    argv = ["live", "run", "--until", until, "--job-started", str(started)]
    return _run([*argv, *_common(tmp_path, stub)], loaders, monkeypatch)
