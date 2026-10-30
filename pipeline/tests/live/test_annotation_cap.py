"""S5 (S8-E follow-up): a whole 320-minute run stays under Actions' annotation caps (10 of
each level a step), its alerts flapping all along, and the soak report's notices (``ready``,
``first pass``, ``end``) are always among the annotations the API keeps.

The loop step prints at most 8 alert warnings (:data:`~snowlight.live.alerts.ANNOTATIONS`;
later ones are plain lines) beside the step's own overrides-only warning, and 3 notices. A
note past a cap is dropped by Actions, so the soak report would lose a run's end. SYNTHETIC
world and a loopback stub host, on a fake clock.
"""

import argparse
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from live.test_cli import Clock, Rig, Server, _loaders
from live.test_handoff_gaps import _loop, _times, clock, rig, server  # noqa: F401 - fixtures
from snowlight.live import cli as live_cli
from snowlight.live.alerts import ANNOTATIONS
from snowlight.live.ingest import SourceRead

STEP_CAP = 10
"""Actions keeps 10 annotations of each level (error, warning, notice) a step."""
WORKFLOW_WARNINGS = 1
"""The loop step's own warning (the state could not be pulled: overrides-only)."""
BAD = 8
"""Passes in a row that read nothing (every due source unread: refused for health once the
last good read is 15 minutes old, so `gate` and `health` open)."""


def _flapping(loaders: live_cli.Loaders, fake: Clock) -> live_cli.Loaders:
    """Reads that read nothing for :data:`BAD` passes in every 2 x :data:`BAD`, so ``gate``
    and ``health`` open and clear again and again over the run."""
    base = loaders.parts
    passes = [0]

    def parts(
        config: live_cli.LiveConfig, env: live_cli.Env, args: argparse.Namespace
    ) -> live_cli.Parts:
        made = base(config, env, args)

        def reads(
            _now: datetime, only: Sequence[str], tick: Callable[[], None]
        ) -> Sequence[SourceRead]:
            fake.sleep(40)
            index = passes[0]
            passes[0] += 1
            found = made.reads(fake.now, only, tick)
            return [] if (index // BAD) % 2 == 1 else found

        return live_cli.Parts(made.ingest, reads)

    return replace(loaders, parts=parts)


def test_a_whole_run_of_flapping_alerts_stays_under_the_step_caps(  # noqa: PLR0913, PLR0917 - fixtures
    tmp_path: Path,
    server: Server,  # noqa: F811 - the fixture
    clock: Clock,  # noqa: F811 - the fixture
    rig: Rig,  # noqa: F811 - the fixture
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    loaders = _flapping(_loaders(rig, clock), clock)
    capsys.readouterr()
    assert _loop(tmp_path, server, loaders, monkeypatch, "+320m") == 3  # refused passes
    lines = capsys.readouterr().out.splitlines()
    passes = len(_times(server))
    assert passes >= 40  # most of a 320-minute run uploads
    levels = Counter(line[2:].split("::", 1)[0] for line in lines if line.startswith("::"))
    alerts = [line for line in lines if line.removeprefix("::warning::").startswith("live alert ")]
    assert len(alerts) > ANNOTATIONS + 4  # flapping all run long
    assert levels["warning"] == ANNOTATIONS
    assert levels["warning"] + WORKFLOW_WARNINGS <= STEP_CAP
    assert levels["notice"] <= STEP_CAP
    assert levels["error"] == 0
    notices = [line for line in lines if line.startswith("::notice::")]
    assert [line.split()[1] for line in notices] == ["ready", "first", "end"]
