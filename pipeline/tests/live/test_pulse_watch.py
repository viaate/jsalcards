"""The pulse watcher outside Python (S8-E stuck passes): ``.github/scripts/pulse-watch.sh``
against stub processes, with its timings scaled down to seconds."""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / ".github" / "scripts" / "pulse-watch.sh"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")


def _watch(
    tmp_path: Path, child: str, *, max_age: int = 2, grace: int = 1
) -> tuple[int, float, str]:
    output = tmp_path / "github_output"
    env = {**os.environ, "PULSE_POLL": "0.2", "GITHUB_OUTPUT": str(output)}
    begin = time.monotonic()
    done = subprocess.run(  # noqa: S603 - our own script and interpreter
        [
            str(BASH),
            str(SCRIPT),
            str(tmp_path / "pulse"),
            str(max_age),
            str(grace),
            "--",
            sys.executable,
            "-c",
            child,
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    took = time.monotonic() - begin
    written = output.read_text(encoding="utf-8") if output.exists() else ""
    return done.returncode, took, done.stdout + written


def _beating(pulse: Path, seconds: float, code: int) -> str:
    return (
        "import time, pathlib\n"
        f"p = pathlib.Path({str(pulse)!r})\n"
        f"end = time.monotonic() + {seconds}\n"
        "while time.monotonic() < end:\n"
        "    p.write_text('x')\n"
        "    time.sleep(0.2)\n"
        f"raise SystemExit({code})\n"
    )


def test_a_beating_reader_runs_to_its_end_and_keeps_its_exit(tmp_path: Path) -> None:
    code, took, out = _watch(tmp_path, _beating(tmp_path / "pulse", 3.0, 3))
    assert code == 3
    assert took >= 3.0
    assert "killed" not in out


def test_a_stopped_pulse_ends_the_reader(tmp_path: Path) -> None:
    child = "import time\ntime.sleep(30)\n"  # a hang: no pulse at all
    code, took, out = _watch(tmp_path, child)
    assert code == 124
    assert took < 10
    assert "the reader's pulse is" in out
    assert "killed=true" in out


def test_a_reader_that_ignores_term_is_killed_after_the_grace(tmp_path: Path) -> None:
    child = "import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\ntime.sleep(30)\n"
    code, took, out = _watch(tmp_path, child, max_age=1, grace=2)
    assert code == 124
    assert took < 12
    assert "killing it" in out


def test_a_pulse_that_stops_mid_run_ends_the_reader(tmp_path: Path) -> None:
    pulse = tmp_path / "pulse"
    child = _beating(pulse, 1.5, 0).replace("raise SystemExit(0)", "time.sleep(30)")
    code, took, _ = _watch(tmp_path, child, max_age=2)
    assert code == 124
    assert 3.0 <= took < 12


def test_a_bad_call_is_refused(tmp_path: Path) -> None:
    done = subprocess.run(  # noqa: S603
        [str(BASH), str(SCRIPT), str(tmp_path / "pulse"), "2"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert done.returncode == 2
