"""A cancel reaches the reader (S8-E round 4, B1): live-read.yml's loop step run as the
Actions runner runs it (``bash --noprofile --norc -eo pipefail``) with a stub reader, and the
runner's cancel as its source sends it (ProcessInvoker: SIGINT to the step's own shell, then
SIGTERM 7.5 s later, to that one process only). The reader is gone before the runner's
SIGTERM, a reader that ignores TERM is KILLed by then, and the reap step finds no reader
left (or KILLs one a cancel left) before the end steps pack the state."""

import contextlib
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from live.test_live_workflows import load, step

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / ".github" / "scripts"
BASH = shutil.which("bash")
TOOLS = all(shutil.which(tool) for tool in ("bash", "setsid", "ps", "awk"))

pytestmark = pytest.mark.skipif(not TOOLS, reason="needs bash, setsid, ps and awk")

READER = """#!{python}
import os, pathlib, signal, sys, time
here = pathlib.Path(__file__).resolve().parents[3]
if os.environ.get("IGNORE_TERM"):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
(here / "reader.pid").write_text(str(os.getpid()))
pulse = here / "out" / "internal" / "live" / "state" / "pulse"
pulse.parent.mkdir(parents=True, exist_ok=True)
end = time.monotonic() + float(os.environ.get("READ_FOR", "120"))
n = 0
while time.monotonic() < end:
    n += 1
    (here / "alive").write_text(str(n))
    pulse.write_text("x")
    time.sleep(0.1)
raise SystemExit(int(os.environ.get("READER_EXIT", "0")))
"""


def _gone(pid: int) -> bool:
    """No such process, or a zombie (it runs no more code)."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return True
    return stat.rsplit(")", 1)[1].split()[0] == "Z"


def _rig(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    """A checkout's shape: ``pipeline/`` (the step's folder) with a stub ``.venv/bin/snowlight``
    and ``.github/scripts`` beside it."""
    pipeline = tmp_path / "pipeline"
    venv = pipeline / ".venv" / "bin"
    venv.mkdir(parents=True)
    reader = venv / "snowlight"
    reader.write_text(READER.format(python=sys.executable), encoding="utf-8")
    reader.chmod(0o755)
    shutil.copytree(SCRIPTS, tmp_path / ".github" / "scripts")
    script = tmp_path / "loop.sh"
    script.write_text(str(step(load("live-read.yml"), "read", "loop")["run"]), encoding="utf-8")
    temp = tmp_path / "runner-temp"
    temp.mkdir()
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "GITHUB_OUTPUT": str(tmp_path / "outputs"),
        "RUNNER_TEMP": str(temp),
        "PULLED": "success",
        "PULSE_POLL": "0.2",
    }
    (tmp_path / "outputs").touch()
    return pipeline, script, env


@pytest.fixture(autouse=True)
def _no_leftovers(tmp_path: Path) -> Iterator[None]:
    """Whatever a failed test left running is KILLed (the watcher's group, by its file)."""
    yield
    group = tmp_path / "runner-temp" / "live-reader.pgid"
    text = group.read_text(encoding="utf-8").strip() if group.is_file() else ""
    if text.isdigit() and int(text) > 1:
        with contextlib.suppress(OSError):
            os.killpg(int(text), signal.SIGKILL)


def _start(tmp_path: Path, extra: dict[str, str]) -> tuple[subprocess.Popen[bytes], int]:
    pipeline, script, env = _rig(tmp_path)
    root = subprocess.Popen(  # noqa: S603 - the workflow's own step, as the runner starts it
        [str(BASH), "--noprofile", "--norc", "-eo", "pipefail", str(script)],
        cwd=pipeline,
        env={**env, **extra},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 20
    pid_file = tmp_path / "reader.pid"
    while not pid_file.is_file() or not pid_file.read_text(encoding="utf-8"):
        assert time.monotonic() < deadline, "the stub reader never started"
        time.sleep(0.05)
    return root, int(pid_file.read_text(encoding="utf-8"))


def _cancel(root: subprocess.Popen[bytes], reader: int) -> float:
    """The runner's cancel: SIGINT to the step's shell, SIGTERM 7.5 s later (if it still
    runs). Returns the seconds until the reader was gone."""
    begin = time.monotonic()
    root.send_signal(signal.SIGINT)
    gone_at = None
    while time.monotonic() - begin < 7.5:
        if gone_at is None and _gone(reader):
            gone_at = time.monotonic() - begin
        if root.poll() is not None and gone_at is not None:
            break
        time.sleep(0.05)
    if root.poll() is None:
        root.send_signal(signal.SIGTERM)
    root.wait(timeout=10)
    assert gone_at is not None, "the reader outlived the runner's SIGINT"
    return gone_at


def _reap(tmp_path: Path) -> str:
    outputs = tmp_path / "reap-outputs"
    outputs.touch()
    done = subprocess.run(  # noqa: S603 - the workflow's own script
        [
            str(BASH),
            str(SCRIPTS / "reap-reader.sh"),
            str(tmp_path / "runner-temp" / "live-reader.pgid"),
        ],
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "GITHUB_OUTPUT": str(outputs)},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert done.returncode == 0
    return done.stdout + outputs.read_text(encoding="utf-8")


def test_a_cancel_ends_the_reader_before_the_runners_sigterm(tmp_path: Path) -> None:
    root, reader = _start(tmp_path, {})
    took = _cancel(root, reader)
    assert took < 2
    ticks = (tmp_path / "alive").read_text(encoding="utf-8")
    time.sleep(0.5)
    assert (tmp_path / "alive").read_text(encoding="utf-8") == ticks  # it reads no more
    outputs = (tmp_path / "outputs").read_text(encoding="utf-8")
    assert "cancelled=true" in outputs
    assert "exit=" not in outputs  # a cancelled run records no exit
    assert "clear=true" in _reap(tmp_path)


def test_a_reader_that_ignores_term_is_killed_inside_the_runners_wait(tmp_path: Path) -> None:
    root, reader = _start(tmp_path, {"IGNORE_TERM": "1"})
    took = _cancel(root, reader)
    assert 4 < took < 7
    assert "clear=true" in _reap(tmp_path)


def test_a_runner_sigterm_alone_also_reaches_the_reader(tmp_path: Path) -> None:
    root, reader = _start(tmp_path, {})
    root.send_signal(signal.SIGTERM)
    root.wait(timeout=10)
    deadline = time.monotonic() + 2
    while not _gone(reader):
        assert time.monotonic() < deadline, "the reader outlived the step's SIGTERM"
        time.sleep(0.05)


@pytest.mark.parametrize(("code", "step_exit"), [(0, 0), (3, 0), (1, 1), (124, 124)])
def test_the_loop_step_keeps_the_readers_exit_and_a_refused_pass_never_fails_it(
    tmp_path: Path, code: int, step_exit: int
) -> None:
    root, _reader = _start(tmp_path, {"READ_FOR": "0.5", "READER_EXIT": str(code)})
    assert root.wait(timeout=30) == step_exit
    outputs = (tmp_path / "outputs").read_text(encoding="utf-8")
    assert f"exit={code}" in outputs
    assert "cancelled" not in outputs
    assert "clear=true" in _reap(tmp_path)


def test_the_watcher_leads_a_process_group_of_its_own(tmp_path: Path) -> None:
    root, reader = _start(tmp_path, {})
    try:
        group = int((tmp_path / "runner-temp" / "live-reader.pgid").read_text(encoding="utf-8"))
        assert os.getpgid(reader) == group  # the reader is in the watcher's group
        assert os.getpgid(root.pid) != group  # and the step's shell is not
    finally:
        _cancel(root, reader)


def test_the_reap_step_kills_a_reader_a_cancel_left(tmp_path: Path) -> None:
    # a reader left running in its group (as one a runner's KILL of the step's shell would
    # orphan): the reap step KILLs the whole group and only then says clear
    temp = tmp_path / "runner-temp"
    temp.mkdir()
    left = subprocess.Popen(
        ["setsid", sys.executable, "-c", "import time\nwhile True: time.sleep(0.1)"],  # noqa: S607
    )
    try:
        time.sleep(0.3)
        assert os.getpgid(left.pid) == left.pid
        (temp / "live-reader.pgid").write_text(str(left.pid), encoding="utf-8")
        said = _reap(tmp_path)
        assert "still running: killing it" in said
        assert "clear=true" in said
        assert left.wait(timeout=5) == -signal.SIGKILL
    finally:
        if left.poll() is None:
            left.kill()


def test_the_reap_step_is_clear_when_no_reader_started_and_refuses_a_bad_group(
    tmp_path: Path,
) -> None:
    assert "clear=true" in _reap(tmp_path)  # no group file: the loop never started a reader
    temp = tmp_path / "runner-temp"
    temp.mkdir()
    for bad in ("", "1", "x9", "0"):
        (temp / "live-reader.pgid").write_text(bad, encoding="utf-8")
        (tmp_path / "reap-outputs").unlink(missing_ok=True)
        said = _reap(tmp_path)
        assert "clear=true" not in said
        assert "not packed" in said
