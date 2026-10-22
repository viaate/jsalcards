"""The live reads (pool and cadence wired for the ingest) and the sweep report, on SYNTHETIC
answers served in memory for real registry ids."""

import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest

from live import world
from snowlight.live.cadence import AlertWatch, Cadence
from snowlight.live.ledger import Outcome
from snowlight.live.pool import PassResult, Request, RequestLog, SourceResult
from snowlight.live.reads import LiveReads, alerts_reader, due_sources, live_pool, pool_read
from snowlight.live.sweep import report
from snowlight.sources.nws.alerts import ACTIVE_URL
from snowlight.sources.stations.fetch import RunResult
from snowlight.sources.stations.http import FetchError, PoliteClient
from snowlight.sources.stations.model import HealthStatus, SourceHealth
from snowlight.sources.stations.registry import Registry, Station, load_registry

NOW = datetime(2026, 11, 16, 12, 0, 0, 250, tzinfo=UTC)


def fresh_robots(state: Path, urls: list[str]) -> None:
    """A robots.json read just now for every origin of ``urls`` (no robots request)."""
    origins = {f"{urlsplit(u).scheme}://{urlsplit(u).netloc}".lower() for u in urls}
    value = {"read_at": datetime.now(UTC).isoformat(), "state": "unavailable", "groups": []}
    state.mkdir(parents=True, exist_ok=True)
    body = {"version": 1, "origins": dict.fromkeys(sorted(origins), value)}
    (state / "robots.json").write_text(json.dumps(body), encoding="utf-8")


def fake_reader(
    registry: Registry, station: Station, client: PoliteClient, now: datetime
) -> RunResult:
    """Reads the station's page through the client; any answer is an empty list."""
    del registry
    assert now.microsecond == 0
    result = RunResult()
    assert station.poll_url is not None
    if station.id.endswith("x"):
        raise RuntimeError("SYNTHETIC adapter failure")
    try:
        client.fetch(station.poll_url)
    except FetchError as error:
        status = HealthStatus.ERROR
        result.health.append(health(station, status, error.status, now))
        return result
    result.health.append(health(station, HealthStatus.EMPTY, 200, now))
    return result


def health(
    station: Station, status: HealthStatus, http_status: int | None, now: datetime
) -> SourceHealth:
    return SourceHealth.model_validate(
        {
            "source_id": station.id,
            "url": station.poll_url,
            "checked_at": now,
            "rows": 0,
            "status": status,
            "http_status": http_status,
            "reason": "SYNTHETIC" if status is HealthStatus.ERROR else None,
        }
    )


def test_live_reads_read_the_due_sources_and_keep_the_cadence(tmp_path: Path) -> None:
    registry = load_registry()
    ids = sorted(due_sources(registry))
    hosts: dict[str, str] = {}
    picked: list[str] = []
    for sid in ids:  # three due sources on three different hosts
        host = urlsplit(registry.stations[sid].poll_url or "").hostname or ""
        if host not in hosts and "s3.amazonaws.com" not in host:
            hosts[host] = sid
            picked.append(sid)
        if len(picked) == 3:
            break
    busy = registry.stations[picked[1]].poll_url

    def serve(request: httpx.Request) -> httpx.Response:
        if str(request.url) == busy:
            return httpx.Response(429, headers={"Retry-After": "600"})
        return httpx.Response(200, content=b"SYNTHETIC")

    state = tmp_path / "state"
    fresh_robots(state, [registry.stations[sid].poll_url or "" for sid in picked])
    http = httpx.Client(transport=httpx.MockTransport(serve))
    pool = live_pool(tmp_path / "cache", state, http=http)
    cadence = Cadence(registry.stations, {}, registry.poll_minutes, path=state / "cadence.json")
    cadence.record(NOW - timedelta(minutes=1), [(sid, Outcome.OK, None) for sid in ids])
    for sid in picked:
        del cadence.clocks[sid]
    reads = LiveReads(registry, world.directory(), pool, cadence, reader=fake_reader)
    ticks: list[int] = []

    found = reads(NOW, (), lambda: ticks.append(1))

    outcomes = {read.source_id: read.outcome for read in found}
    assert outcomes == {
        picked[0]: Outcome.EMPTY,
        picked[1]: Outcome.DEFERRED,
        picked[2]: Outcome.EMPTY,
    }
    assert ticks
    deferred = cadence.clocks[picked[1]]
    assert deferred.not_before is not None
    answered = next(item for item in found if item.source_id == picked[1])
    assert deferred.not_before - deferred.last_pass > timedelta(seconds=600)
    assert deferred.not_before - deferred.last_pass < timedelta(seconds=610)
    assert answered.outcome is Outcome.DEFERRED
    assert json.loads((state / "cadence.json").read_text())["sources"][picked[0]]["outcome"] == (
        "empty"
    )

    only = reads(NOW + timedelta(minutes=5), (picked[0], "synthetic-missing"), lambda: None)
    assert [read.source_id for read in only] == [picked[0]]


def test_live_reads_tell_the_ingest_what_was_due(tmp_path: Path) -> None:
    registry = load_registry()
    sid = sorted(due_sources(registry))[0]
    url = registry.stations[sid].poll_url or ""
    state = tmp_path / "state"
    fresh_robots(state, [url])
    pool = live_pool(
        tmp_path / "cache",
        state,
        http=httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(200))),
    )
    cadence = Cadence(registry.stations, {}, registry.poll_minutes)
    reads = LiveReads(registry, world.directory(), pool, cadence, reader=fake_reader)

    class Sink:
        due: frozenset[str] | None = None

    sink = Sink()
    reads.ingest = sink  # type: ignore[assignment]
    reads(NOW, (sid,), lambda: None)
    assert sink.due == due_sources(registry)  # a pass of a few still counts every source due
    assert cadence.recently_due(NOW + timedelta(minutes=16)) == frozenset()


def test_a_read_that_raised_is_an_error_read() -> None:
    station = world.station("gray-synthetic")
    crashed = SourceResult(station.id, Outcome.ERROR, 0.1, 0.1)
    read = pool_read(station, crashed, world.directory(), NOW)
    assert read is not None
    assert (read.outcome, read.fetched_at, read.rows) == (Outcome.ERROR, NOW, ())
    late = SourceResult(station.id, Outcome.LATE, 0.0, 240.0)
    assert pool_read(station, late, world.directory(), NOW).outcome is Outcome.LATE  # type: ignore[union-attr]


def test_alerts_are_read_through_the_pool(tmp_path: Path) -> None:
    body = {
        "type": "FeatureCollection",
        "features": [
            {
                "properties": {
                    "status": "Actual",
                    "messageType": "Alert",
                    "event": "Winter Storm Warning",
                    "expires": "2099-01-01T00:00:00+00:00",
                    "geocode": {"SAME": ["020091"]},
                }
            }
        ],
    }
    seen: list[str] = []

    def serve(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, content=json.dumps(body).encode())

    fresh_robots(tmp_path, [ACTIVE_URL])
    pool = live_pool(
        tmp_path / "cache", tmp_path, http=httpx.Client(transport=httpx.MockTransport(serve))
    )
    watch = AlertWatch(alerts_reader(pool))
    assert watch.counties(datetime.now(UTC)) == frozenset({"20091"})
    assert ACTIVE_URL in seen


def test_sweep_report_counts_requests_floors_and_robots() -> None:
    log = RequestLog()
    log.add(Request("a.example.test", 5.0, 10.0, 10.5, True, "https://a.example.test"))
    log.add(Request("a.example.test", 5.0, 15.0, 15.4, False, "https://a.example.test"))
    log.add(Request("b.example.test", 5.0, 10.0, 10.2))
    sources = (
        SourceResult("synthetic-a", Outcome.OK, 1.0, 5.4),
        SourceResult("synthetic-b", Outcome.ERROR, 0.2, 0.2, None),
        SourceResult("synthetic-c", Outcome.BLOCKED, 0.2, 0.3, 403),
    )
    result = PassResult(NOW, 5.5, sources, 2)
    sent = Counter({"a.example.test": 2, "b.example.test": 1})
    found = report(result, log, sent, label="1")
    assert found["violations"] == 0
    assert found["requests_paced"] == found["requests_sent"] == 3
    assert found["unpaced_keys"] == []
    assert found["robots_requests"] == found["robots_reads"] == 1
    assert found["robots_reads_max_per_origin"] == 1
    assert found["robots_follow_ups"] == {}
    assert found["robots_origins"] == {"https://a.example.test": 1}
    assert found["outcomes"] == {"blocked": 1, "error": 1, "ok": 1}
    assert found["not_good"] == {"blocked": ["synthetic-c:403"], "error": ["synthetic-b:none"]}
    assert found["slowest_keys"][0] == ["a.example.test", 2, 5.4]  # type: ignore[index]
    broken = report(result, log, Counter({"a.example.test": 3}), label="2")
    assert broken["unpaced_keys"] == ["a.example.test", "b.example.test"]


def test_request_log_is_written_relative_to_its_origin(tmp_path: Path) -> None:
    log = RequestLog()
    log.add(Request("k", 5.0, 102.0, 102.5, True, "https://k.example.test"))
    log.add(Request("k", 5.0, 100.0, 100.25))
    path = tmp_path / "log.jsonl"
    log.write(path, origin=100.0, sweep=3)
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert lines == [
        {
            "end": 0.25,
            "floor": 5.0,
            "follow": False,
            "key": "k",
            "origin": "",
            "robots": False,
            "start": 0.0,
            "sweep": 3,
        },
        {
            "end": 2.5,
            "floor": 5.0,
            "follow": False,
            "key": "k",
            "origin": "https://k.example.test",
            "robots": True,
            "start": 2.0,
            "sweep": 3,
        },
    ]


def test_an_alerts_read_that_was_stopped_does_not_stop_the_next(tmp_path: Path) -> None:
    answers = [
        httpx.Response(503, headers={"Retry-After": "3600"}),
        httpx.Response(200, content=b'{"type": "FeatureCollection", "features": []}'),
    ]

    def serve(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)  # pragma: no cover - kept fresh
        return answers.pop(0)

    fresh_robots(tmp_path, [ACTIVE_URL])
    pool = live_pool(
        tmp_path / "cache", tmp_path, http=httpx.Client(transport=httpx.MockTransport(serve))
    )
    read = alerts_reader(pool)
    with pytest.raises(FetchError):
        read()  # deferred: the feed asked for an hour
    assert b"FeatureCollection" in read()
    assert answers == []
