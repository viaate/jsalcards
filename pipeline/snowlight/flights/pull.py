"""The long history pull (FL-1b.2, LR-H8): twenty more years of forecasts, weather reports and
flights, fetched into RAM one file at a time, reduced, and the raw body dropped.

Two queues, each a detached, re-runnable process that skips whatever it already keeps:

* **IEM** (one university server, so one queue for every request to it, the probes too), in
  this order:

  1. the NBS station guidance: each station's runs from 2026-10-01 on (the unit map's proof
     against the AWS bulletins), then the 00Z runs from 2018-11-07 to 2020-02-25 (``mos.py``,
     model NBS), one station per winter;
  2. GFS MOS (MAV) 00Z runs from 2000-06-01 on, one station-year per request (model AVN until
     2003-12-16, GFS after);
  3. the hourly weather reports for 2000 to 2014 (``asos.py``), one month of 20 stations per
     request, kept as the hourly flags :mod:`snowlight.flights.obs` reads.

  Requests are serial, and each waits at least 2 s (3 s from 13:00 to 01:00 UTC) after the
  last reply ended, whichever process made it (the pause, the backoff and a lock live in
  files). A busy reply ("Too many requests", 429, 5xx, a dropped connection) or a body that is
  not the table asked for backs off hard: 60 s, doubling on each busy reply to 15 minutes, and
  halving only after a run of calm replies (the backoff's end lives in the file too, so a
  restart waits it out). A request that never left this machine (the local agent proxy refused
  the connection) is no reply from IEM: it leaves the pace and the backoff alone, and three in a
  row stop the queue with that reason in the status. Five tasks failing in a row stop the queue.
  While
  the live Flights pass may be reading IEM (its ``latest.json`` is 14.5 to 27 minutes old),
  no request is made (LR-H7). Holes (a station with no runs) are asked once more a day later.
* **BTS** (its own hosts), one month at a time: PREZIP 2000-01 to 2014-12, and the Data Expo
  copy (Harvard Dataverse, CC0) for 1997-10 to 1999-12 plus 2000-01 to 2000-03 kept apart for
  the cross-check with PREZIP. Old years keep ``dep``, ``arr``, ``legs`` and ``places`` only.

A forecast is kept as IEM gives it (its codes as text, 00Z runs only): the unit maps that turn
it into model inputs read these tables later, so a map can change without a new pull.

``python -m snowlight.flights.pull iem|bts|status`` runs a queue or writes the status file.
"""

import argparse
import bz2
import contextlib
import fcntl
import io
import json
import os
import shutil
import sys
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

import httpx
import polars as pl

from snowlight.flights import airports as airports_module
from snowlight.flights import bts, history, obs

HIST: Final = Path("/dev/shm/flights/hist")  # noqa: S108 - RAM for raw downloads, never shared
USER_AGENT: Final = "Snowlight flights history (https://snowlightmap.com)"

MOS_URL: Final = "https://mesonet.agron.iastate.edu/cgi-bin/request/mos.py"
NBS_FIRST: Final = date(2018, 11, 7)
NBS_LAST: Final = date(2020, 2, 25)
"""IEM's NBS runs at 00Z (0, 7, 12 and 19Z) from the first run to this day; 01Z after it."""
NBS_SPLIT: Final = date(2019, 7, 1)
MAV_FIRST: Final = date(2000, 6, 1)
AVN_LAST: Final = date(2003, 12, 16)
"""IEM names the MAV runs AVN before this day and GFS from it."""
ASOS_FIRST: Final = bts.Month(2000, 1)
ASOS_LAST: Final = bts.Month(2014, 12)
BTS_FIRST: Final = bts.Month(2000, 1)
BTS_LAST: Final = bts.Month(2014, 12)
EXPO_FIRST: Final = bts.Month(1997, 10)
EXPO_CHECK: Final = (bts.Month(2000, 1), bts.Month(2000, 2), bts.Month(2000, 3))
OLD_TABLES: Final = ("dep", "arr", "legs", "places")

GAP_SECONDS: Final = 2.0
BUSY_GAP_SECONDS: Final = 3.0
BUSY_HOURS: Final = (13, 1)
"""From 13:00 to 01:00 UTC (the US day) IEM requests are 3 s apart."""
BACKOFF_FIRST: Final = 60.0
BACKOFF_MAX: Final = 900.0
BACKOFF_EASE_AFTER: Final = 50
"""After this many calm replies in a row the shared backoff halves (under 60 s it is gone)."""
TRIES: Final = 8
STOP_AFTER: Final = 5
"""Tasks failing in a row (each after its backoff) that stop the queue: the server is down or
saying something else, and the lead restarts it."""
HOLE_AGAIN_AFTER: Final = timedelta(days=1)
"""A hole is asked once more this long after it was kept (an empty reply under load is not a
gap for good)."""


class PullError(RuntimeError):
    """A request failed after every try (it is asked again on the next run)."""


class LocalProxyError(RuntimeError):
    """The local agent proxy refused :data:`LOCAL_STOP_AFTER` requests in a row: nothing reached
    the host, so this is no task's failure and no busy reply. The queue stops and says so; a
    restart from a shell with the current proxy settings fixes it."""


# --- the tasks -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Task:
    """One request and the file its reduced table is kept in."""

    source: str
    """``nbs``, ``mav`` or ``asos``."""
    key: str
    url: str
    path: Path


def _stamp(moment: date) -> str:
    return f"{moment.isoformat()}T00:00Z"


def mos_url(station: str, model: str, first: date, end: date) -> str:
    """One station's MOS runs of ``model`` from ``first`` up to (not including) ``end``: IEM's
    end time is included, so the request ends at 23:00 the day before."""
    last = f"{(end - timedelta(days=1)).isoformat()}T23:00Z"
    return f"{MOS_URL}?station={station}&model={model}&sts={_stamp(first)}&ets={last}&format=csv"


def nbs_tasks(stations: Sequence[str], root: Path) -> list[Task]:
    """The NBS winters 2018-19 and 2019-20, one request per station and winter."""
    spans = ((NBS_FIRST, NBS_SPLIT), (NBS_SPLIT, NBS_LAST + timedelta(days=1)))
    return [
        Task(
            "nbs",
            f"{station}_{first:%Y%m}",
            mos_url(station, "NBS", first, end),
            root / "nbs" / f"{station}_{first:%Y%m}.parquet",
        )
        for first, end in spans
        for station in stations
    ]


IEM_SOURCES: Final = frozenset({"nbs", "nbsx", "mav", "asos"})

OVERLAP_FIRST: Final = date(2026, 10, 1)
"""The NBS unit map is proven on the 00Z runs both IEM and the AWS bucket hold from this day on
(after the test year: no outcome is read)."""


def overlap_tasks(stations: Sequence[str], root: Path, today: date) -> list[Task]:
    """IEM's NBS from :data:`OVERLAP_FIRST` to ``today``, one request per station (the unit
    map's proof against the AWS bulletins of the same runs)."""
    return [
        Task(
            "nbsx",
            station,
            mos_url(station, "NBS", OVERLAP_FIRST, today),
            root / "nbsx" / f"{station}.parquet",
        )
        for station in stations
    ]


def mav_spans(today: date) -> list[tuple[str, date, date]]:
    """The MAV requests per station: (model, first day, end day), a year at a time."""
    spans: list[tuple[str, date, date]] = []
    for year in range(MAV_FIRST.year, today.year + 1):
        first = max(date(year, 1, 1), MAV_FIRST)
        end = min(date(year + 1, 1, 1), today)
        if first >= end:
            continue
        if first < AVN_LAST < end:
            spans.append(("AVN", first, AVN_LAST))
            spans.append(("GFS", AVN_LAST, end))
        else:
            spans.append(("AVN" if end <= AVN_LAST else "GFS", first, end))
    return spans


def mav_tasks(stations: Sequence[str], root: Path, today: date) -> list[Task]:
    """Every station's MAV from 2000-06-01 to ``today``, year by year (all stations of a year
    before the next year)."""
    return [
        Task(
            "mav",
            f"{station}_{first:%Y%m%d}",
            mos_url(station, model, first, end),
            root / "mav" / str(first.year) / f"{station}_{first:%Y%m%d}.parquet",
        )
        for model, first, end in mav_spans(today)
        for station in stations
    ]


def asos_tasks(stations: Sequence[str], root: Path) -> list[Task]:
    """The hourly reports 2000 to 2014, a month of 20 stations a request."""
    groups = [list(stations[i : i + history.GROUP]) for i in range(0, len(stations), history.GROUP)]
    return [
        Task(
            "asos",
            f"{month.key}_{index:02d}",
            obs.request_url(group, month.year, month.month),
            root / "asos" / month.key / f"{index:02d}.parquet",
        )
        for month in bts.months(ASOS_FIRST, ASOS_LAST)
        for index, group in enumerate(groups)
    ]


def iem_tasks(airports: Sequence[airports_module.Airport], root: Path, today: date) -> list[Task]:
    """The whole IEM queue, in the order LR-H8 sets."""
    icao = sorted({airport.icao for airport in airports})
    wx = sorted({airport.wx for airport in airports})
    return [
        *overlap_tasks(icao, root, today),
        *nbs_tasks(icao, root),
        *mav_tasks(icao, root, today),
        *asos_tasks(wx, root),
    ]


# --- reducing ------------------------------------------------------------------------------------


class NotTableError(ValueError):
    """A body that is not the table asked for (an error text, a cut-off body)."""


def _moment(column: str) -> pl.Expr:
    return (
        pl.col(column)
        .str.slice(0, 16)
        .str.to_datetime("%Y-%m-%d %H:%M", time_zone="UTC", strict=False)
        .dt.cast_time_unit("us")
    )


def reduce_mos(body: bytes, hour: int = 0) -> pl.DataFrame:
    """The runs at ``hour`` UTC of a MOS request's CSV, every column kept as IEM wrote it
    (text), with ``runtime`` and ``ftime`` read as UTC times.

    Raises:
        NotTableError: the body is not the MOS table.
    """
    head = body[:2048].decode("utf-8", "replace").splitlines()
    names = head[0].split(",") if head else []
    if not {"station", "runtime", "ftime"} <= set(names):
        raise NotTableError(f"not the MOS table: {(head[0] if head else '')[:80]!r}")
    try:
        frame = pl.read_csv(io.BytesIO(body), infer_schema=False, truncate_ragged_lines=True)
        return (
            frame.with_columns(_moment("runtime"), _moment("ftime"))
            .filter(pl.col("runtime").dt.hour() == hour)
            .sort("runtime", "ftime")
        )
    except (pl.exceptions.PolarsError, ValueError) as error:
        raise NotTableError(f"the MOS table does not read: {error}") from error


def reduce_task(task: Task, body: bytes) -> pl.DataFrame:
    """A task's body reduced to the table kept.

    Raises:
        NotTableError: the body is not the table asked for.
    """
    if task.source == "asos":
        try:
            return obs.reduce_bytes(body)
        except obs.ReportsError as error:
            raise NotTableError(str(error)) from error
    return reduce_mos(body)


# --- the polite client ---------------------------------------------------------------------------


def gap_at(moment: datetime) -> float:
    """The least pause between two IEM requests at ``moment``."""
    start, end = BUSY_HOURS
    hour = moment.astimezone(UTC).hour
    return BUSY_GAP_SECONDS if hour >= start or hour < end else GAP_SECONDS


def busy(status: int, body: bytes) -> bool:
    """Whether a reply says the server is busy or failing (back off hard)."""
    too_many = b"too many requests" in body[:4096].lower()
    return status == 429 or status >= 500 or too_many  # noqa: PLR2004 - HTTP statuses


SLOW_MAX: Final = 60.0
"""The most a busy server stretches the pause between requests to."""
FASTER_AFTER: Final = 20
"""After this many replies in a row with no busy one, the stretched pause shrinks a little."""


PACER_FIELDS: Final = ("last", "asked", "slow", "calm", "backoff", "eased", "until")


def _nothing() -> None:
    return None


def _ignore(_reason: str) -> None:
    return None


def _no_hold() -> float:
    return 0.0


@dataclass(slots=True)
class Pacer:
    """The pause between requests to one host, kept in a file so every process shares it.

    The pause counts from the end of the last reply (:meth:`done`), not its start. A busy reply
    stretches the pause (by half, plus a second, up to a minute) and it stays stretched; every
    :data:`FASTER_AFTER` calm replies in a row shrink it by 15%, never under the least pause
    ``gap`` gives. The hard backoff (:meth:`busy`) lives in the same file: it doubles on each
    busy reply, whichever task got it, and halves after :data:`BACKOFF_EASE_AFTER` calm ones in
    a row. ``until`` is the hard backoff's end: the caller that got the busy reply sleeps the
    backoff itself, and any other pacer on the same file (a restarted queue) waits it out before
    its first request. ``hold`` says how long no request may go at all (the live pass's window).
    """

    stamp: Path
    gap: Callable[[datetime], float]
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.time
    hold: Callable[[], float] = _no_hold
    mine: float = 0.0
    """The backoff end this pacer set (its caller sleeps that one out itself)."""

    def _state(self) -> dict[str, float]:
        try:
            state = json.loads(self.stamp.read_text())
            return {name: float(state.get(name, 0.0)) for name in PACER_FIELDS}
        except (OSError, ValueError, AttributeError, TypeError):
            return dict.fromkeys(PACER_FIELDS, 0.0)

    def _save(self, state: dict[str, float]) -> None:
        self.stamp.parent.mkdir(parents=True, exist_ok=True)
        part = self.stamp.with_name(f"{self.stamp.name}.{os.getpid()}.part")
        part.write_text(json.dumps(state))
        part.replace(self.stamp)

    def state(self) -> dict[str, float]:
        """The shared state: ``last`` (the last request's end, or start while it runs),
        ``asked`` (its start), ``slow``, ``calm``, ``backoff``, ``eased`` and ``until``."""
        return self._state()

    def pause(self) -> float:
        """The pause between requests now."""
        state = self._state()
        return max(self.gap(datetime.fromtimestamp(self.clock(), UTC)), state["slow"])

    def wait(self) -> None:
        """Sleep until the next request may go (the pause after the last reply ended, the end of
        a hard backoff, and no request while ``hold`` says so), and note it as asked now."""
        while (held := self.hold()) > 0:
            self.sleep(held)
        state = self._state()
        if state["until"] != self.mine and (backoff := state["until"] - self.clock()) > 0:
            self.sleep(backoff)
        now = self.clock()
        pause = state["last"] + self.pause() - now
        if pause > 0:
            self.sleep(pause)
        state = self._state()
        state["last"] = state["asked"] = self.clock()
        self._save(state)

    def done(self) -> None:
        """The reply ended (or the request failed): the next pause counts from now."""
        state = self._state()
        state["last"] = max(state["last"], self.clock())
        self._save(state)

    def slower(self) -> None:
        """A busy reply: stretch the pause."""
        state = self._state()
        state["slow"] = min(max(state["slow"], self.gap(datetime.now(UTC))) * 1.5 + 1, SLOW_MAX)
        state["calm"] = 0.0
        self._save(state)

    def busy(self) -> float:
        """A busy reply (or a body that is not the table): stretch the pause and give the hard
        backoff to wait now, 60 s, then double the last one, to 15 minutes."""
        self.slower()
        state = self._state()
        last = state["backoff"]
        state["backoff"] = BACKOFF_FIRST if last < BACKOFF_FIRST else min(last * 2, BACKOFF_MAX)
        state["eased"] = 0.0
        state["until"] = self.mine = self.clock() + state["backoff"]
        self._save(state)
        return state["backoff"]

    def calm(self) -> None:
        """A calm reply: after enough in a row, shrink the stretched pause and halve the
        backoff (under 60 s it is gone: the next busy reply waits 60 s)."""
        state = self._state()
        state["calm"] += 1
        state["eased"] += 1
        if state["calm"] >= FASTER_AFTER:
            state["calm"] = 0.0
            state["slow"] *= 0.85
        if state["eased"] >= BACKOFF_EASE_AFTER:
            state["eased"] = 0.0
            half = state["backoff"] / 2
            state["backoff"] = half if half >= BACKOFF_FIRST else 0.0
        self._save(state)


LIVE_LATEST: Final = "https://viaate.github.io/snowlight-live/v1/flights/latest.json"
"""The live Flights pass's newest file (public): a pass runs once it is 15 minutes old."""
HOLD_FROM: Final = 14.5 * 60
HOLD_UNTIL: Final = 27.0 * 60
"""While ``latest.json`` is this old (seconds), a live pass may be reading IEM: no request goes
(LR-H7). Older than :data:`HOLD_UNTIL`, the live job is stalled and the pull goes on."""
LIVE_CHECK_EVERY: Final = 60.0


@dataclass(slots=True)
class LiveHold:
    """How long the IEM queue holds for the live pass (a ``hold`` for :class:`Pacer`): the age
    of the live ``latest.json``, read at most once a minute; nothing held when it does not
    read."""

    fetch: Callable[[], bytes | None]
    clock: Callable[[], float] = time.time
    log: Callable[[str], None] = print
    made: float | None = None
    checked: float = float("-inf")
    holding: bool = False

    def _read(self) -> float | None:
        try:
            body = self.fetch()
            if body is None:
                return None
            stamp = str(json.loads(body)["generated_at"]).replace("Z", "+00:00")
            return datetime.fromisoformat(stamp).timestamp()
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return None

    def __call__(self) -> float:
        now = self.clock()
        if now - self.checked >= LIVE_CHECK_EVERY:
            self.made, self.checked = self._read(), now
        age = None if self.made is None else now - self.made
        if age is not None and HOLD_FROM <= age < HOLD_UNTIL:
            if not self.holding:
                self.log(f"pull: holding for the live pass (latest.json {age / 60:.1f} min old)")
            self.holding = True
            return min(LIVE_CHECK_EVERY, HOLD_UNTIL - age)
        self.holding = False
        return 0.0


LOCAL_STOP_AFTER: Final = 3
"""Requests in a row the local proxy refuses that stop the queue (nothing reached the host)."""
LOCAL_WAIT: Final = 10.0
"""The wait after one request the local proxy refused (no backoff: the host never saw it)."""


def local_proxy(env: Mapping[str, str] = os.environ) -> str | None:
    """The proxy every request goes through (``HTTPS_PROXY``) when it runs on this machine, else
    ``None``."""
    for name in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        if value := env.get(name):
            host = urlsplit(value).hostname or ""
            return value if host in {"localhost", "::1"} or host.startswith("127.") else None
    return None


def local_failure(error: httpx.HTTPError, proxy: str | None) -> bool:
    """Whether ``error`` never left this machine: the connection to a local ``proxy`` failed.
    Through a proxy the client connects to the proxy alone; the host's own failures come back
    as a reply, a :class:`httpx.ProxyError` or a dropped connection, and stay the host's."""
    return proxy is not None and isinstance(error, httpx.ConnectError | httpx.ConnectTimeout)


def get_politely(  # noqa: PLR0913 - the request, its pacing, its tries and its log
    request: Callable[[str], tuple[int, bytes]],
    url: str,
    pacer: Pacer,
    log: Callable[[str], None],
    *,
    tries: int = TRIES,
    sleep: Callable[[float], None] = time.sleep,
    proxy: str | None = None,
    failed: Callable[[str], None] = _ignore,
) -> bytes | None:
    """The body at ``url``, ``None`` when it is not there (404); a busy reply or a failed
    connection waits the shared backoff (:meth:`Pacer.busy`: 60 s, doubling to 15 minutes)
    before the next try. A connection the local ``proxy`` refused is no reply from the host: it
    spends no try and leaves the pace and the backoff alone. ``failed`` hears every failed
    try's reason.

    Raises:
        PullError: every try failed.
        LocalProxyError: the local proxy refused :data:`LOCAL_STOP_AFTER` requests in a row.
    """
    last = ""
    tried = local = 0
    while tried < tries:
        pacer.wait()
        try:
            status, body = request(url)
        except httpx.HTTPError as error:
            pacer.done()
            status, body, last = 0, b"", f"{type(error).__name__}: {error}"
            if local_failure(error, proxy):
                local += 1
                failed(f"the local proxy {proxy} refused the request ({last})")
                if local >= LOCAL_STOP_AFTER:
                    raise LocalProxyError(
                        f"the local proxy {proxy} refused {local} requests in a row ({last})"
                    ) from error
                log(f"pull: the local proxy {proxy} failed ({last}); the host's pace is unchanged")
                sleep(LOCAL_WAIT)
                continue
        else:
            pacer.done()
            if status == 404:  # noqa: PLR2004 - not there
                return None
            if status == 200 and not busy(status, body):  # noqa: PLR2004 - the body
                pacer.calm()
                return body
            last = f"HTTP {status}"
        local = 0
        tried += 1
        failed(last)
        if status == 0 or busy(status, body):
            backoff = pacer.busy()
            log(
                f"pull: busy or failed ({last}); waiting {backoff:.0f} s, "
                f"then {pacer.pause():.1f} s between requests"
            )
            sleep(backoff)
        else:
            sleep(BACKOFF_FIRST / 4)
    raise PullError(f"{url}: {last}")


def requester(http: httpx.Client) -> Callable[[str], tuple[int, bytes]]:  # pragma: no cover
    """The status and body of a GET on ``http``."""

    def call(url: str) -> tuple[int, bytes]:
        response = http.get(url)
        return response.status_code, response.content

    return call


def client() -> httpx.Client:  # pragma: no cover - the network
    """An HTTP client with the pull's User-Agent and long timeouts (a station-year is slow)."""
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=httpx.Timeout(300.0, connect=30.0),
        follow_redirects=True,
    )


@contextlib.contextmanager
def only_one(lock: Path) -> Iterator[None]:
    """Hold ``lock`` for the whole run: a second run of the same queue stops at once.

    Raises:
        PullError: another run holds it.
    """
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise PullError(f"{lock} is held by another run") from error
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


# --- the IEM queue -------------------------------------------------------------------------------


def _note(index: Path, record: dict[str, object]) -> None:
    with index.open("a") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def keep(path: Path, frame: pl.DataFrame) -> None:
    """Write a table whole, then rename it into place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".part")
    frame.write_parquet(part, compression="zstd")
    part.replace(path)


def _fetch_table(task: Task, get: Callable[[str], bytes | None]) -> tuple[pl.DataFrame, int]:
    body = get(task.url)
    frame = (
        reduce_task(task, body)
        if body is not None
        else pl.DataFrame(schema={"station": pl.String()})
    )
    return frame, 0 if body is None else len(body)


def run_tasks(  # noqa: PLR0913 - the queue, its client, its index, its clock and its guards
    tasks: Sequence[Task],
    get: Callable[[str], bytes | None],
    index: Path,
    log: Callable[[str], None],
    *,
    after: Callable[[], None] = _nothing,
    clock: Callable[[], float] = time.monotonic,
    rejected: Callable[[str], None] = _ignore,
    stop_after: int = STOP_AFTER,
) -> int:
    """Run every task whose table is not kept yet; how many were kept now. A table with no rows
    is kept too (a hole: the station had no runs then), and noted as such. A body that is not
    the table goes to ``rejected`` (the caller backs off as for a busy reply) and the task is
    asked again on the next run; ``after`` runs after every task, kept or failed.

    Raises:
        PullError: ``stop_after`` tasks failed in a row (the queue stops).
    """
    kept = 0
    in_a_row = 0
    for task in tasks:
        if task.path.exists():
            continue
        start = clock()
        try:
            frame, size = _fetch_table(task, get)
        except (PullError, NotTableError) as error:
            log(f"pull: {task.source} {task.key} failed ({error})")
            _note(index, {"source": task.source, "key": task.key, "failed": str(error)[:200]})
            in_a_row += 1
            if in_a_row >= stop_after:
                after()
                raise PullError(f"{in_a_row} tasks failed in a row; the queue stops") from error
            if isinstance(error, NotTableError):
                rejected(str(error))
            after()
            continue
        in_a_row = 0
        keep(task.path, frame)
        kept += 1
        _note(
            index,
            {
                "source": task.source,
                "key": task.key,
                "rows": frame.height,
                "bytes": size,
                "seconds": round(clock() - start, 2),
                "at": datetime.now(UTC).isoformat(timespec="seconds"),
            },
        )
        after()
    return kept


def _latest(index: Path) -> dict[tuple[str, str], dict[str, object]]:
    """Each task's newest record that is not a failure."""
    out: dict[tuple[str, str], dict[str, object]] = {}
    for record in _records(index):
        if "failed" not in record:
            out[str(record["source"]), str(record["key"])] = record
    return out


def holes_to_confirm(tasks: Sequence[Task], index: Path) -> list[tuple[Task, datetime]]:
    """The holes not yet asked again and confirmed, with when each was last asked."""
    latest = _latest(index)
    out: list[tuple[Task, datetime]] = []
    for task in tasks:
        record = latest.get((task.source, task.key))
        if record is None or int(str(record.get("rows", 0))) > 0 or record.get("confirmed"):
            continue
        with contextlib.suppress(ValueError):
            out.append((task, datetime.fromisoformat(str(record.get("at", "")))))
    return out


def confirm_holes(  # noqa: PLR0913 - the queue, its client, its index, its clock and its sleep
    tasks: Sequence[Task],
    get: Callable[[str], bytes | None],
    index: Path,
    log: Callable[[str], None],
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], None] = time.sleep,
    after: Callable[[], None] = _nothing,
) -> int:
    """Ask every hole once more, :data:`HOLE_AGAIN_AFTER` after it was kept (sleeping until the
    next is due), and note it confirmed, or keep the rows it has now. Each hole is asked at
    most once a run; one that fails stays a hole to confirm on the next run. Out: how many
    were asked."""
    asked: set[tuple[str, str]] = set()
    while True:
        pending = [
            (task, at)
            for task, at in holes_to_confirm(tasks, index)
            if (task.source, task.key) not in asked
        ]
        if not pending:
            return len(asked)
        due = [task for task, at in pending if now() - at >= HOLE_AGAIN_AFTER]
        if not due:
            wait = min(at for _, at in pending) + HOLE_AGAIN_AFTER - now()
            hours = wait / timedelta(hours=1)
            log(f"pull: {len(pending)} holes to ask again; the next in {hours:.1f} h")
            sleep(max(wait.total_seconds(), 60.0))
            continue
        for task in due:
            asked.add((task.source, task.key))
            record: dict[str, object] = {"source": task.source, "key": task.key, "rows": 0}
            try:
                frame, size = _fetch_table(task, get)
            except (PullError, NotTableError) as error:
                log(f"pull: hole {task.source} {task.key} not asked again ({error})")
                after()
                continue
            if frame.height:
                keep(task.path, frame)
                log(f"pull: hole {task.source} {task.key} has {frame.height} rows now")
            record.update(
                rows=frame.height,
                bytes=size,
                confirmed=True,
                at=now().isoformat(timespec="seconds"),
            )
            _note(index, record)
            after()


# --- BTS -----------------------------------------------------------------------------------------

DATAVERSE: Final = "https://dataverse.harvard.edu"
EXPO_DOI: Final = "doi:10.7910/DVN/HG7NV7"
EXPO_COLUMNS: Final = {
    "UniqueCarrier": "Reporting_Airline",
    "FlightNum": "Flight_Number_Reporting_Airline",
    "Origin": "Origin",
    "Dest": "Dest",
    "CRSDepTime": "CRSDepTime",
    "DepDelay": "DepDelay",
    "CRSArrTime": "CRSArrTime",
    "ArrDelay": "ArrDelay",
    "Cancelled": "Cancelled",
    "Diverted": "Diverted",
}
"""The Data Expo copy's columns, named as the PREZIP files name them."""


def has_tables(root: Path, month: bts.Month, tables: Sequence[str] = OLD_TABLES) -> bool:
    """Whether every one of ``tables`` of the month is kept."""
    return all(bts.table_path(root, table, month).is_file() for table in tables)


def write_tables(
    root: Path,
    month: bts.Month,
    frames: dict[str, pl.DataFrame],
    tables: Sequence[str] = OLD_TABLES,
) -> None:
    """Keep the month's ``tables`` (each whole, then renamed)."""
    for table in tables:
        keep(bts.table_path(root, table, month), frames[table])


def expo_rows(csv: Path) -> pl.LazyFrame:
    """A Data Expo year's CSV in the PREZIP columns (no city names), all text."""
    raw = pl.scan_csv(csv, infer_schema=False, encoding="utf8-lossy")
    day = pl.format(
        "{}-{}-{}",
        pl.col("Year"),
        pl.col("Month").str.zfill(2),
        pl.col("DayofMonth").str.zfill(2),
    )
    return raw.select(
        day.alias("FlightDate"),
        *[pl.col(old).alias(new) for old, new in EXPO_COLUMNS.items()],
        pl.lit(None, pl.String).alias("OriginCityName"),
        pl.lit(None, pl.String).alias("OriginState"),
        pl.lit(None, pl.String).alias("DestCityName"),
        pl.lit(None, pl.String).alias("DestState"),
        pl.col("Month").cast(pl.Int32).alias("_month"),
    )


def reduce_expo_month(csv: Path, month: bts.Month) -> dict[str, pl.DataFrame]:
    """One month of a Data Expo year reduced to the compact tables."""
    rows = expo_rows(csv).filter(pl.col("_month") == month.month).drop("_month")
    return bts.reduce_rows(bts.read_rows(rows))


def expo_files(get: Callable[[str], bytes | None]) -> dict[int, int]:  # pragma: no cover
    """The Data Expo file id of each year (from the dataset's listing)."""
    body = get(f"{DATAVERSE}/api/datasets/:persistentId/?persistentId={EXPO_DOI}")
    if body is None:
        raise PullError("the Data Expo listing is not there")
    files = json.loads(body)["data"]["latestVersion"]["files"]
    found: dict[int, int] = {}
    for entry in files:
        label = str(entry.get("label", ""))
        if label.endswith(".csv.bz2") and label[:4].isdigit():
            found[int(label[:4])] = int(entry["dataFile"]["id"])
    return found


def unbzip(body: bytes, target: Path) -> None:
    """Write a bz2 body's text to ``target`` in pieces (never all of it in memory twice)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with bz2.open(io.BytesIO(body)) as source, target.open("wb") as out:
        shutil.copyfileobj(source, out, 16 << 20)


def run_bts(
    root: Path,
    get: Callable[[str], bytes | None],
    log: Callable[[str], None],
    status: Callable[[], None],
) -> None:  # pragma: no cover - the long run
    """The BTS queue: PREZIP 2000-01 to 2014-12, then the Data Expo years 1997 to 2000."""
    run_prezip(root, get, log, status)
    run_expo(root, get, log, status)


def run_prezip(
    root: Path,
    get: Callable[[str], bytes | None],
    log: Callable[[str], None],
    status: Callable[[], None],
) -> None:  # pragma: no cover - the long run
    """PREZIP 2000-01 to 2014-12, a month at a time."""
    scratch = root / "scratch"
    store = root / "bts"
    index = root / "bts-done.jsonl"
    for month in bts.months(BTS_FIRST, BTS_LAST):
        if has_tables(store, month):
            continue
        start = time.monotonic()
        try:
            body = get(month.url())
        except PullError as error:
            log(f"pull: bts {month.key} failed ({error})")
            continue
        if body is None:
            log(f"pull: bts {month.key} not posted")
            _note(index, {"source": "bts", "key": month.key, "failed": "not posted"})
            continue
        scratch.mkdir(parents=True, exist_ok=True)
        archive = scratch / f"{month.key}.zip"
        archive.write_bytes(body)
        del body
        try:
            frames = bts.reduce_zip(archive, scratch)
        except Exception as error:  # a body that does not read is that month's alone
            log(f"pull: bts {month.key} did not read ({type(error).__name__}: {error})")
            _note(index, {"source": "bts", "key": month.key, "failed": type(error).__name__})
            continue
        finally:
            archive.unlink(missing_ok=True)
        write_tables(store, month, frames)
        _note(
            index,
            {
                "source": "bts",
                "key": month.key,
                "rows": frames["legs"].height,
                "seconds": round(time.monotonic() - start, 1),
                "at": datetime.now(UTC).isoformat(timespec="seconds"),
            },
        )
        log(f"pull: bts {month.key} kept ({frames['legs'].height} flights)")
        status()


def run_expo(
    root: Path,
    get: Callable[[str], bytes | None],
    log: Callable[[str], None],
    status: Callable[[], None],
) -> None:  # pragma: no cover - the long run
    """The Data Expo years: 1997-10 to 1999-12 into the BTS store, 2000-01 to 03 apart."""
    scratch = root / "scratch"
    store = root / "bts"
    index = root / "bts-done.jsonl"
    expo = root / "expo"
    wanted: dict[int, list[tuple[Path, bts.Month]]] = {}
    for month in bts.months(EXPO_FIRST, bts.Month(1999, 12)):
        wanted.setdefault(month.year, []).append((store, month))
    for month in EXPO_CHECK:
        wanted.setdefault(month.year, []).append((expo, month))
    todo = {
        year: months
        for year, months in wanted.items()
        if not all(has_tables(place, month) for place, month in months)
    }
    if not todo:
        return
    ids = expo_files(get)
    for year, months in sorted(todo.items()):
        start = time.monotonic()
        try:
            body = get(f"{DATAVERSE}/api/access/datafile/{ids[year]}")
        except (PullError, KeyError) as error:
            log(f"pull: expo {year} failed ({error})")
            continue
        if body is None:
            log(f"pull: expo {year} not there")
            continue
        csv = scratch / f"expo-{year}.csv"
        try:
            unbzip(body, csv)
            del body
            for place, month in months:
                if has_tables(place, month):
                    continue
                frames = reduce_expo_month(csv, month)
                write_tables(place, month, frames)
                _note(
                    index,
                    {
                        "source": "expo",
                        "key": month.key,
                        "rows": frames["legs"].height,
                        "seconds": round(time.monotonic() - start, 1),
                        "at": datetime.now(UTC).isoformat(timespec="seconds"),
                    },
                )
                log(f"pull: expo {month.key} kept ({frames['legs'].height} flights)")
        except Exception as error:  # a year that does not read is that year's alone
            log(f"pull: expo {year} did not read ({type(error).__name__}: {error})")
        finally:
            csv.unlink(missing_ok=True)
        status()


# --- the status file -----------------------------------------------------------------------------


def _records(index: Path) -> list[dict[str, object]]:
    if not index.is_file():
        return []
    out: list[dict[str, object]] = []
    for line in index.read_text().splitlines():
        with contextlib.suppress(ValueError):
            out.append(json.loads(line))
    return out


def held(lock: Path) -> bool:
    """Whether a running queue holds ``lock`` (a lock is per open file, so this reads true in
    the running process too)."""
    if not lock.is_file():
        return False
    with lock.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle, fcntl.LOCK_UN)
    return False


QUEUE_GAPS: Final = {"iem": gap_at, "bts": lambda _moment: 1.0}


def _when(stamp: float) -> str:
    return datetime.fromtimestamp(stamp, UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if stamp else "never"


def _parse_at(text: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _read_json(path: Path) -> dict[str, object]:
    try:
        out = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return out if isinstance(out, dict) else {}


def note_error(root: Path, queue: str, reason: str, now: datetime) -> None:
    """Keep ``queue``'s last failed request (its time and reason) for the status file."""
    path = root / f"{queue}.err"
    part = path.with_name(f"{path.name}.{os.getpid()}.part")
    part.write_text(json.dumps({"at": now.isoformat(timespec="seconds"), "error": reason[:200]}))
    part.replace(path)


def note_stop(root: Path, queue: str, why: str, now: datetime) -> None:
    """Add to ``queue``'s run file why and when it stopped (the status says it)."""
    run = _read_json(root / f"{queue}.run")
    run.update(stopped=now.isoformat(timespec="seconds"), why=why[:300])
    (root / f"{queue}.run").write_text(json.dumps(run))


def queue_line(root: Path, queue: str, *, finished: bool = False, now: float | None = None) -> str:
    """Whether ``queue`` runs now (its lock), its pid and start, its last request, its pause
    and its backoff (and its end, while one is waited out); a queue not running says whether it
    ``finished``, or why it stopped and that it needs a restart."""
    run = _read_json(root / f"{queue}.run")
    try:
        pid, since = int(str(run["pid"])), str(run["since"])
    except (KeyError, ValueError):
        pid, since = 0, "unknown"
    pacer = Pacer(root / f"{queue}.last", QUEUE_GAPS[queue])
    state = pacer.state()
    if not held(root / f"{queue}.lock"):
        if finished:
            return f"{queue} queue: not running (last started {since}, pid {pid}); every task done"
        why = f"stopped {run['stopped']}: {run.get('why', '')}; " if "stopped" in run else ""
        return f"{queue} queue: not running (last started {since}, pid {pid}); {why}restart it"
    clock = time.time() if now is None else now
    until = f" (waiting it out until {_when(state['until'])})" if state["until"] > clock else ""
    return (
        f"{queue} queue: running (pid {pid} since {since}), last request asked "
        f"{_when(state['asked'])}, pause {pacer.pause():.1f} s, "
        f"backoff {state['backoff']:.0f} s{until}"
    )


STALL_AFTER: Final = timedelta(minutes=15)
"""A running queue that kept no table for this long says so in the status, with its last error."""
STUCK_AFTER: Final = timedelta(minutes=30)
"""A running queue that kept no table for this long (since its start too) is stuck: the restart
command (``start-pull.sh``, through ``pull stuck``) replaces it."""


def last_kept(root: Path, queue: str) -> datetime | None:
    """When ``queue`` last kept a table (its index), ``None`` before the first."""
    newest: datetime | None = None
    for record in _records(root / f"{queue}-done.jsonl"):
        if "failed" in record or record.get("confirmed"):
            continue
        moment = _parse_at(str(record.get("at", "")))
        if moment is not None and (newest is None or moment > newest):
            newest = moment
    return newest


def quiet_for(root: Path, queue: str, now: datetime) -> timedelta | None:
    """How long a running ``queue`` has kept no table (counted from its start when it kept none
    since), ``None`` while it is not running."""
    if not held(root / f"{queue}.lock"):
        return None
    since = _parse_at(str(_read_json(root / f"{queue}.run").get("since", "")))
    marks = [m for m in (last_kept(root, queue), since) if m is not None]
    return now - max(marks) if marks else None


def stall_line(root: Path, queue: str, now: datetime) -> str | None:
    """``queue keeps nothing`` with its last error, while a running queue kept no table for
    :data:`STALL_AFTER`."""
    quiet = quiet_for(root, queue, now)
    if quiet is None or quiet < STALL_AFTER:
        return None
    error = _read_json(root / f"{queue}.err")
    at = _parse_at(str(error.get("at", "")))
    kept = last_kept(root, queue)
    if at is None or (kept is not None and at < kept):
        said = "no failed request since the last table kept"
    else:
        said = f"last error {_when(at.timestamp())}: {error.get('error', '')}"
    return f"{queue} queue: no table kept for {quiet / timedelta(minutes=1):.0f} min ({said})"


def stuck(root: Path, queue: str, now: datetime) -> int | None:
    """The pid of a running ``queue`` that kept no table for :data:`STUCK_AFTER`, else ``None``."""
    quiet = quiet_for(root, queue, now)
    if quiet is None or quiet < STUCK_AFTER:
        return None
    try:
        return int(str(_read_json(root / f"{queue}.run")["pid"])) or None
    except (KeyError, ValueError):
        return None


PACE_WINDOW: Final = timedelta(hours=2)
PACE_LEAST: Final = 20


def seconds_each(
    records: Sequence[dict[str, object]], queue: str, now: datetime | None = None
) -> float | None:
    """The seconds per kept task over the :data:`PACE_WINDOW` up to ``now`` (the real pace,
    pauses, backoffs, holds and any stall in), else the mean of the last 50 tasks' own seconds
    (never under the window's time up to ``now`` per task kept in it); ``None`` when nothing
    was kept in the window up to ``now`` (no pace to tell). Without ``now`` the window ends at
    the last record."""
    times: list[datetime] = []
    for record in records:
        if (moment := _parse_at(str(record.get("at", "")))) is not None:
            times.append(moment)
    times.sort()
    end = now if now is not None else (times[-1] if times else None)
    recent = [t for t in times if end is not None and end - PACE_WINDOW <= t <= end]
    if now is not None and not recent:
        return None
    if len(recent) >= PACE_LEAST and end is not None:
        span = (end - recent[0]).total_seconds()
        if span >= 600:  # noqa: PLR2004 - ten minutes
            return span / (len(recent) - 1)
    pause = GAP_SECONDS if queue == "iem" else 0.0
    own = [float(str(r.get("seconds", 0))) + pause for r in records][-50:]
    mean = sum(own) / len(own) if own else 0.0
    if now is None or not recent:
        return mean
    # Too few kept in the window for a pace: never faster than what was kept up to now.
    return max(mean, (now - recent[0]).total_seconds() / len(recent))


def status_lines(root: Path, today: date, now: datetime) -> list[str]:
    """The status: whether each queue runs, done and total per source, rows kept, holes (and
    those confirmed), failures, the last request and the hours left at the recent pace."""
    airports = airports_module.load()
    totals: dict[str, int] = {}
    for task in iem_tasks(airports, root, today):
        totals[task.source] = totals.get(task.source, 0) + 1
    totals["bts"] = len(list(bts.months(BTS_FIRST, BTS_LAST)))
    totals["expo"] = len(list(bts.months(EXPO_FIRST, bts.Month(1999, 12)))) + len(EXPO_CHECK)
    done: dict[str, dict[str, dict[str, object]]] = {}
    failed: dict[str, set[str]] = {}
    last = ""
    pace: dict[str, list[dict[str, object]]] = {}
    for record in [*_records(root / "iem-done.jsonl"), *_records(root / "bts-done.jsonl")]:
        source, key = str(record["source"]), str(record["key"])
        if "failed" in record:
            failed.setdefault(source, set()).add(key)
            continue
        done.setdefault(source, {})[key] = record
        failed.get(source, set()).discard(key)
        last = max(last, str(record.get("at", "")))
        if not record.get("confirmed"):
            pace.setdefault("iem" if source in IEM_SOURCES else "bts", []).append(record)
    finished = {
        queue: all(
            len(done.get(source, {})) >= totals[source]
            for source in totals
            if (source in IEM_SOURCES) == (queue == "iem")
        )
        for queue in ("iem", "bts")
    }
    lines = [
        f"Snowlight FL-1b.2 history pull, status at {now:%Y-%m-%d %H:%MZ}",
        *(
            line
            for queue in ("iem", "bts")
            for line in (
                queue_line(root, queue, finished=finished[queue], now=now.timestamp()),
                stall_line(root, queue, now),
            )
            if line is not None
        ),
    ]
    each = {queue: seconds_each(records, queue, now) for queue, records in pace.items()}
    left_hours: dict[str, float | None] = {}
    for source in ("nbs", "nbsx", "mav", "asos", "bts", "expo"):
        kept = done.get(source, {})
        rows = sum(int(str(r.get("rows", 0))) for r in kept.values())
        holes = sum(1 for r in kept.values() if int(str(r.get("rows", 0))) == 0)
        confirmed = sum(
            1 for r in kept.values() if int(str(r.get("rows", 0))) == 0 and r.get("confirmed")
        )
        fails = len(failed.get(source, set()))
        lines.append(
            f"{source}: {len(kept)} of {totals[source]} done, {rows} rows kept, "
            f"{holes} holes, {fails} failed (asked again on the next run); "
            f"{confirmed} of the holes asked again a day later and still empty"
        )
        queue = "iem" if source in IEM_SOURCES else "bts"
        left = max(totals[source] - len(kept), 0)
        pace_each = each.get(queue, 0.0)
        so_far = left_hours.get(queue, 0.0)
        left_hours[queue] = (
            so_far + left * pace_each
            if so_far is not None and pace_each is not None
            else (None if left else so_far)
        )
    lines.append(f"last request kept: {last or 'none yet'}")

    def hours(queue: str) -> str:
        value = left_hours.get(queue, 0.0)
        return (
            "unknown (no table kept in the last 2 hours)"
            if value is None
            else f"{value / 3600:.1f}"
        )

    lines.append(
        f"est. hours left: IEM {hours('iem')}, BTS {hours('bts')} "
        "(at the pace of the last 2 hours up to now)"
    )
    return lines


def write_status(root: Path, path: Path) -> None:  # pragma: no cover - the clock
    """Write the status file (small; the lead's copy lives on the scratchpad)."""
    now = datetime.now(UTC)
    with contextlib.suppress(OSError):
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(f"{path.name}.{os.getpid()}.part")
        part.write_text("\n".join(status_lines(root, now.date(), now)) + "\n")
        part.replace(path)


# --- the command ---------------------------------------------------------------------------------


def _logger(root: Path) -> Callable[[str], None]:  # pragma: no cover - the log file
    log_file = root / "fetch.log"

    def log(line: str) -> None:
        stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        with log_file.open("a") as handle:
            handle.write(f"{stamp} {line}\n")

    return log


STATUS_EVERY: Final = 60.0
"""The status file is written at least this often while a queue runs: on every log line, after
tasks, and between the pieces of every wait (a backoff, a hold for the live pass, the pause,
the wait for a hole); only one request in flight (its timeout 300 s) can stretch it."""


def napper(
    tick: Callable[[], None],
    sleep: Callable[[float], None] = time.sleep,
    every: float = STATUS_EVERY,
) -> Callable[[float], None]:
    """A sleep in pieces of at most ``every`` seconds, with ``tick`` (the status) after each."""

    def nap(seconds: float) -> None:
        while seconds > 0:
            piece = min(seconds, every)
            sleep(piece)
            seconds -= piece
            tick()

    return nap


def stopped_by_proxy(error: LocalProxyError) -> str:
    """What the status says when the local proxy stopped a queue."""
    return f"local proxy refused ({error}); restart it from a shell with the current proxy"


def _run_iem(  # pragma: no cover - the long run
    root: Path,
    request: Callable[[str], tuple[int, bytes]],
    log: Callable[[str], None],
    status: Callable[[], None],
) -> int:
    """The IEM queue: every task, the failures of this run once more, then the holes."""
    hold = LiveHold(lambda: request(f"{LIVE_LATEST}?t={int(time.time())}")[1], log=log)
    nap = napper(status)
    pacer = Pacer(root / "iem.last", gap_at, sleep=nap, hold=hold)
    tasks = iem_tasks(airports_module.load(), root, datetime.now(UTC).date())
    index = root / "iem-done.jsonl"
    written = [0.0]

    def after() -> None:
        if time.monotonic() - written[0] >= STATUS_EVERY:
            written[0] = time.monotonic()
            status()

    def failed(reason: str) -> None:
        note_error(root, "iem", reason, datetime.now(UTC))

    def get_iem(url: str) -> bytes | None:
        return get_politely(request, url, pacer, log, sleep=nap, proxy=local_proxy(), failed=failed)

    def rejected(reason: str) -> None:
        failed(f"not the table ({reason[:80]})")
        backoff = pacer.busy()
        log(f"pull: not the table ({reason[:80]}); waiting {backoff:.0f} s")
        nap(backoff)

    try:
        kept = run_tasks(tasks, get_iem, index, log, after=after, rejected=rejected)
        kept += run_tasks(tasks, get_iem, index, log, after=after, rejected=rejected)
        log(f"pull: iem tasks done ({kept} kept this run); asking the holes again")
        asked = confirm_holes(tasks, get_iem, index, log, after=after, sleep=nap)
    except LocalProxyError as error:
        note_stop(root, "iem", stopped_by_proxy(error), datetime.now(UTC))
        log(f"pull: iem queue stopped ({stopped_by_proxy(error)}) with start-pull.sh")
        return EXIT_LOCAL_PROXY
    except PullError as error:
        note_stop(root, "iem", str(error), datetime.now(UTC))
        log(f"pull: iem queue stopped ({error}); restart it with start-pull.sh")
        return 1
    log(f"pull: iem queue ends ({kept} kept, {asked} holes asked again this run)")
    return 0


EXIT_LOCAL_PROXY: Final = 3
"""The exit code of a queue the local proxy stopped (not the host: restart it as it is)."""


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - the long run
    """Run one queue (``iem`` or ``bts``) to its end, write the status file (``status``), or
    say whether a queue is stuck (``stuck iem``: its pid and exit 0 when it kept no table for
    :data:`STUCK_AFTER`, for the restart command to replace it; else exit 1)."""
    parser = argparse.ArgumentParser(prog="python -m snowlight.flights.pull")
    parser.add_argument("queue", choices=("iem", "bts", "status", "stuck"))
    parser.add_argument("which", nargs="?", choices=("iem", "bts"), default="iem")
    parser.add_argument("--root", type=Path, default=HIST)
    parser.add_argument("--status", type=Path, default=None, help="the status file")
    args = parser.parse_args(argv)
    root: Path = args.root
    status_file: Path = args.status or root / "fetch-status.txt"

    def status() -> None:
        write_status(root, status_file)

    root.mkdir(parents=True, exist_ok=True)
    if args.queue == "status":
        status()
        return 0
    if args.queue == "stuck":
        pid = stuck(root, args.which, datetime.now(UTC))
        if pid is None:
            return 1
        sys.stdout.write(f"{pid}\n")
        return 0
    to_file = _logger(root)

    def log(line: str) -> None:
        to_file(line)
        status()

    code = 0
    with only_one(root / f"{args.queue}.lock"), client() as http:
        (root / f"{args.queue}.run").write_text(
            json.dumps(
                {"pid": os.getpid(), "since": datetime.now(UTC).isoformat(timespec="seconds")}
            )
        )
        request = requester(http)
        log(f"pull: {args.queue} queue starts (pid {os.getpid()})")
        if args.queue == "iem":
            code = _run_iem(root, request, log, status)
        else:
            nap = napper(status)
            pacer = Pacer(root / "bts.last", lambda _moment: 1.0, sleep=nap)

            def failed(reason: str) -> None:
                note_error(root, "bts", reason, datetime.now(UTC))

            def get_bts(url: str) -> bytes | None:
                return get_politely(
                    request,
                    url,
                    pacer,
                    log,
                    tries=4,
                    sleep=nap,
                    proxy=local_proxy(),
                    failed=failed,
                )

            try:
                run_bts(root, get_bts, log, status)
            except LocalProxyError as error:
                note_stop(root, "bts", stopped_by_proxy(error), datetime.now(UTC))
                log(f"pull: bts queue stopped ({stopped_by_proxy(error)}) with start-pull.sh")
                code = EXIT_LOCAL_PROXY
            else:
                log("pull: bts queue ends")
    status()
    return code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
