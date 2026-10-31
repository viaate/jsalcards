"""The blend's reads end at the budget's deadline on a real socket (chart-shadow critic B1).

A socket read's timeout holds for each read, so a host that trickles a byte now and then and
then stalls kept a request open one read timeout (10 s) past the budget. These tests run
:func:`snowlight.predict.nbm.bounded_client` against a local server that does exactly that, or
never answers, or whose name never resolves, and check the read ends with ``nbm_slow`` within
the budget and a little slack (far under the 10 s an unbounded read would take).
"""

import socket
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager

import httpx
import pytest

from snowlight.predict import nbm

READ_S = 2.0
"""The per-read timeout in these tests (10 s live), so they run in seconds."""
BUDGET_S = 2.4
"""More than one read timeout: a request starts with its whole read timeout, as live."""
SLACK_S = 0.9
"""Thread start-up and a loaded machine. An unbounded trickle ends one read timeout after its
last byte: at 3.6 s or later here, against the 3.3 s these tests allow."""

Serve = Callable[[socket.socket, threading.Event], None]


@pytest.fixture(autouse=True)
def _short_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """The live limits scaled down: a 2 s read timeout, connects at most 1 s."""
    monkeypatch.setattr(nbm, "_READ_S", READ_S)
    monkeypatch.setattr(nbm, "READ_TIMEOUT", httpx.Timeout(READ_S, connect=1.0))


@contextmanager
def _server(serve: Serve) -> Iterator[str]:
    """A local HTTP server running ``serve`` for each connection; its base URL."""
    stop = threading.Event()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)
    listener.settimeout(0.1)
    open_sockets: list[socket.socket] = []

    def accept() -> None:
        while not stop.is_set():
            try:
                conn, _addr = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            open_sockets.append(conn)
            threading.Thread(target=serve, args=(conn, stop), daemon=True).start()

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{listener.getsockname()[1]}"
    finally:
        stop.set()
        thread.join(2)
        listener.close()
        for conn in open_sockets:
            conn.close()


def _request(conn: socket.socket) -> None:
    conn.settimeout(5)
    data = b""
    while b"\r\n\r\n" not in data:
        more = conn.recv(4096)
        if not more:
            return
        data += more


def _trickle(times: Iterable[float]) -> Serve:
    """Headers at once, then one body byte at each of ``times`` (seconds after the request),
    then a stall until the test ends."""

    def serve(conn: socket.socket, stop: threading.Event) -> None:
        _request(conn)
        started = time.monotonic()
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n")
        for at in times:
            if stop.wait(max(0.0, started + at - time.monotonic())):
                return
            conn.sendall(b"x")
        stop.wait(30)

    return serve


def _silent(conn: socket.socket, stop: threading.Event) -> None:
    """Reads the request and never answers."""
    _request(conn)
    stop.wait(30)


def _answer(conn: socket.socket, stop: threading.Event) -> None:
    del stop
    _request(conn)
    conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\nConnection: close\r\n\r\nhello")


def _http(budget: nbm.Budget, lookup: nbm.Lookup | None = None) -> nbm.NbmHttp:
    if lookup is None:
        client = nbm.bounded_client(budget, proxy=None)
    else:
        client = nbm.bounded_client(budget, proxy=None, lookup=lookup)
    return nbm.NbmHttp(client, budget)


def _timed(call: Callable[[], object]) -> tuple[float, BaseException | None]:
    started = time.monotonic()
    try:
        call()
    except Exception as error:
        return time.monotonic() - started, error
    return time.monotonic() - started, None


@pytest.mark.parametrize(
    "serve",
    [
        pytest.param(_trickle([1.8, 3.6]), id="trickle-then-stall"),
        pytest.param(_trickle([1.9, 2.3]), id="late-byte-then-stall"),
        pytest.param(_silent, id="no-headers"),
    ],
)
def test_a_trickling_or_silent_host_ends_at_the_budget(serve: Serve) -> None:
    with _server(serve) as base:
        budget = nbm.Budget(seconds=BUDGET_S)
        http = _http(budget)
        budget.start()
        elapsed, error = _timed(lambda: http.get(f"{base}/blend"))
        http.client.close()
    assert isinstance(error, nbm.NbmSlowError), error
    assert error.code == "nbm_slow"
    assert elapsed < BUDGET_S + SLACK_S


def test_a_lookup_that_hangs_ends_at_the_budget() -> None:
    release = threading.Event()

    def hangs(host: str, port: int) -> list[str]:
        del host, port
        release.wait(30)
        return ["127.0.0.1"]

    budget = nbm.Budget(seconds=BUDGET_S)
    http = _http(budget, hangs)
    budget.start()
    elapsed, error = _timed(lambda: http.get("http://blend.test:9/x"))
    release.set()
    http.client.close()
    assert isinstance(error, nbm.NbmSlowError), error
    assert elapsed < BUDGET_S + SLACK_S


def test_a_name_that_never_resolves_is_unreadable_at_once() -> None:
    def missing(host: str, port: int) -> list[str]:
        raise socket.gaierror(f"{host}:{port}: no such name")

    budget = nbm.Budget(seconds=30)
    http = _http(budget, missing)
    budget.start()
    elapsed, error = _timed(lambda: http.get("http://blend.invalid/x"))
    http.client.close()
    assert isinstance(error, nbm.NbmUnreadableError), error
    assert not isinstance(error, nbm.NbmSlowError)
    assert elapsed < 1 + SLACK_S  # the one wait between the two tries


def test_the_bounded_client_reads_an_answer_in_time() -> None:
    with _server(_answer) as base:
        budget = nbm.Budget(seconds=5)
        http = _http(budget)
        budget.start()
        assert http.get(f"{base}/blend") == b"hello"
        http.client.close()


def test_the_bounded_client_never_reads_proxies_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    with _server(_answer) as base:
        budget = nbm.Budget(seconds=5)
        http = _http(budget)
        budget.start()
        assert http.get(f"{base}/blend") == b"hello"
        http.client.close()
    assert nbm.env_proxy("https://noaa-nbm-grib2-pds.s3.amazonaws.com") == "http://127.0.0.1:9"


def test_the_wait_between_tries_never_sleeps_past_the_budget() -> None:
    now = [0.0]
    slept: list[float] = []
    budget = nbm.Budget(seconds=0.4, clock=lambda: now[0])
    budget.start()
    http = nbm.NbmHttp(nbm.bounded_client(budget, proxy=None), budget, sleep=slept.append)
    http._wait(1.0)
    http.client.close()
    assert slept == [pytest.approx(0.4)]
