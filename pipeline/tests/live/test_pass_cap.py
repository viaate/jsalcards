"""S8-E pass cap, abandoned threads, the keep-alive cut and the pacer kept across processes.

* A pass is cut 30 s (here a fraction of a second) after its deadline whatever its workers
  do: the sources not finished are ``late``, a result that arrives later is dropped, and
  the thread still running counts as abandoned until it ends.
* A long-lived process's live client keeps no idle connection, so a request under a
  deadline is cut even when the server stalls the header phase (a stub server that
  trickles its status line one byte at a time).
* ``pacer.json`` carries each key's last start to the next process, so a floor holds
  across a handoff.
"""

import json
import os
import socketserver
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from live.test_pool import station
from snowlight.live.ledger import Outcome
from snowlight.live.pool import HostPacer, Pool, RobotsStore
from snowlight.live.reads import PACER_FILE, live_pool
from snowlight.sources.stations.fetch import RunResult
from snowlight.sources.stations.http import (
    REQUEST_GRACE,
    ConditionalStore,
    DeadlineError,
    FetchError,
    PoliteClient,
    make_client,
)
from snowlight.sources.stations.model import HealthStatus, SourceHealth
from snowlight.sources.stations.registry import Station

NOW = datetime(2026, 11, 17, 11, 5, tzinfo=UTC)


def _ok(source: Station) -> RunResult:
    return RunResult(
        health=[
            SourceHealth.model_validate(
                {
                    "source_id": source.id,
                    "url": source.poll_url,
                    "checked_at": NOW,
                    "rows": 1,
                    "status": HealthStatus.OK,
                    "http_status": 200,
                    "reason": None,
                }
            )
        ]
    )


def _pool(tmp: Path, **kwargs: object) -> Pool:
    def client() -> PoliteClient:
        return PoliteClient(httpx.Client(trust_env=False), ConditionalStore(tmp / "cache"))

    return Pool(client=client, **kwargs)  # type: ignore[arg-type]


def test_a_stuck_source_is_cut_at_the_cap_and_its_late_result_dropped(tmp_path: Path) -> None:
    release = threading.Event()
    sources = [
        station("synthetic-stuck", "https://stuck.example/list"),
        station("synthetic-fine", "https://fine.example/list"),
        station("synthetic-other", "https://other.example/list"),
    ]

    def read(source: Station, _client: PoliteClient) -> RunResult:
        if source.id == "synthetic-stuck":
            release.wait(10)  # a hang no deadline reaches (pure Python, say)
        return _ok(source)

    pool = _pool(tmp_path, pass_deadline=0.3, cap_grace=0.2, workers=4)
    begin = time.monotonic()
    result = pool.run_pass(sources, read)
    took = time.monotonic() - begin
    assert took < 1.5  # the cap (0.5 s) plus a tick, never the 10 s hang
    outcomes = {item.source_id: item.outcome for item in result.sources}
    assert outcomes == {
        "synthetic-stuck": Outcome.LATE,
        "synthetic-fine": Outcome.OK,
        "synthetic-other": Outcome.OK,
    }
    assert pool.abandoned == 1
    release.set()
    deadline = time.monotonic() + 5
    while pool.abandoned and time.monotonic() < deadline:
        time.sleep(0.02)
    assert pool.abandoned == 0
    # the stuck read finished after the cut: the pass's result never changed
    assert {item.source_id: item.outcome for item in result.sources} == outcomes
    # and the next pass runs on a new executor, with nothing left of the old one
    again = pool.run_pass(sources[1:], read)
    assert {item.outcome for item in again.sources} == {Outcome.OK}


def test_a_pass_that_ends_in_time_abandons_nothing(tmp_path: Path) -> None:
    pool = _pool(tmp_path, pass_deadline=5.0, workers=2)
    result = pool.run_pass(
        [
            station("synthetic-a", "https://a.example/"),
            station("synthetic-b", "https://b.example/"),
        ],
        lambda source, _client: _ok(source),
    )
    assert {item.outcome for item in result.sources} == {Outcome.OK}
    assert pool.abandoned == 0


class _Trickle(socketserver.BaseRequestHandler):
    """The first two requests (robots.txt and a page) answer at once on a keep-alive
    connection; every later one trickles its status line, a byte every 0.25 s."""

    count = 0

    def handle(self) -> None:
        stream = self.request.makefile("rb")
        while True:
            line = stream.readline()
            if not line:
                return
            while stream.readline() not in (b"\r\n", b""):
                pass
            type(self).count += 1
            if type(self).count <= 2:
                self.request.sendall(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
                continue
            head = (
                b"HTTP/1.1 200 OK\r\nX-Synthetic: " + b"a" * 40 + b"\r\nContent-Length: 1\r\n\r\nx"
            )
            try:
                for byte in head:
                    self.request.sendall(bytes([byte]))
                    time.sleep(0.25)
            except OSError:
                return


@pytest.fixture
def trickle() -> object:
    _Trickle.count = 0

    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = True

    server = Server(("127.0.0.1", 0), _Trickle)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_the_live_client_cuts_a_stalled_header_phase_after_an_earlier_request(
    trickle: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy"):
        monkeypatch.delenv(name, raising=False)
    client = PoliteClient(
        make_client(keepalive=False),
        ConditionalStore(tmp_path / "cache"),
        host_interval=0.0,
        attempts=1,
        pacer=HostPacer(),
        robots=RobotsStore(None),
    )
    with pytest.raises(FetchError):
        client.fetch(f"{trickle}/first")  # no deadline: a connection a pool could keep
    begin = time.monotonic()
    client.deadline = begin + 0.3
    with pytest.raises(DeadlineError) as stopped:
        client.fetch(f"{trickle}/second")
    over = time.monotonic() - (begin + 0.3)
    assert stopped.value.kind == "late"
    assert over < REQUEST_GRACE + 1.0  # the grace, never the 10 s of the trickle


def test_the_pacer_is_kept_across_processes(tmp_path: Path) -> None:
    mono = [1000.0]
    first = HostPacer(lambda: mono[0])
    with first.slot("s3.amazonaws.com/synthetic", 5.0):
        pass
    path = tmp_path / PACER_FILE
    first.save(path, NOW)
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert set(stored["starts"]) == {"s3.amazonaws.com/synthetic"}
    # the successor starts 2 s later on another clock: the 5 s floor still holds for 3 s
    later = [50.0]
    second = HostPacer(lambda: later[0])
    second.load(path, NOW + timedelta(seconds=2))
    with pytest.raises(TimeoutError), second.slot("s3.amazonaws.com/synthetic", 5.0, 51.0):
        pass
    later[0] = 53.0
    with second.slot("s3.amazonaws.com/synthetic", 5.0, 54.0):
        pass
    # another key never waits
    with second.slot("other.example", 5.0, 53.5):
        pass


def test_a_damaged_pacer_file_seeds_nothing(tmp_path: Path) -> None:
    path = tmp_path / PACER_FILE
    path.write_text("{not json", encoding="utf-8")
    pacer = HostPacer(lambda: 10.0)
    pacer.load(path, NOW)
    pacer.load(tmp_path / "missing.json", NOW)
    with pacer.slot("any.example", 5.0, 10.5):
        pass


def test_the_live_pool_seeds_and_keeps_the_pacer(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    (state / PACER_FILE).write_text(
        json.dumps({"version": 1, "starts": {"a.example": datetime.now(UTC).isoformat()}}),
        encoding="utf-8",
    )
    pool = live_pool(tmp_path / "cache", state, http=httpx.Client(trust_env=False))
    assert pool.pacer is not None
    assert "a.example" in pool.pacer.starts(datetime.now(UTC))
    pool.run_pass([], lambda source, _client: _ok(source))
    assert "a.example" in json.loads((state / PACER_FILE).read_text(encoding="utf-8"))["starts"]


_STUCK = """
import sys, threading
from pathlib import Path
from live.test_pass_cap import _pool
from live.test_pool import station
from snowlight.live import cli as live_cli

pool = _pool(Path(sys.argv[1]), pass_deadline=0.3, cap_grace=0.2, workers=2)

def read(source, client):
    threading.Event().wait()  # stuck for good: no deadline reaches it

pool.run_pass([station("synthetic-stuck", "https://stuck.example/list")], read)

class Reads:
    pass

reads = Reads()
reads.pool = pool
print("cut", pool.abandoned, flush=True)
if sys.argv[2] == "leave":
    live_cli.leave(1, live_cli.Parts(ingest=None, reads=reads), live_cli.Loaders())
sys.exit(1)
"""


def _stuck(tmp_path: Path, how: str) -> "subprocess.Popen[str]":
    tests = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": f"{tests}{os.pathsep}{os.environ.get('PYTHONPATH', '')}"}
    return subprocess.Popen(  # noqa: S603 - this interpreter and a fixed script
        [sys.executable, "-c", _STUCK, str(tmp_path), how],
        stdout=subprocess.PIPE,
        text=True,
        env=env,
    )


def test_a_process_with_a_thread_stuck_for_good_exits_at_once(tmp_path: Path) -> None:
    """The interpreter's own exit joins every executor thread, so a plain exit waits for a
    stuck reader thread for good (until the pulse watcher kills it, 9 minutes on); the
    reader's ``leave`` ends the process at once with its exit."""
    plain = _stuck(tmp_path, "plain")
    assert plain.stdout is not None
    assert plain.stdout.readline().strip() == "cut 1"
    with pytest.raises(subprocess.TimeoutExpired):
        plain.wait(timeout=3)  # held by the stuck thread
    plain.kill()
    plain.wait()
    plain.stdout.close()
    quick = _stuck(tmp_path, "leave")
    assert quick.stdout is not None
    assert quick.stdout.readline().strip() == "cut 1"
    begin = time.monotonic()
    assert quick.wait(timeout=10) == 1
    assert time.monotonic() - begin < 5
    rest = quick.stdout.read()
    quick.stdout.close()
    assert "1 reader threads still running: the process ends now (exit 1)" in rest
