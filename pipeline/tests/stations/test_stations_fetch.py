"""``stations fetch``: the terms gate, robots verdicts, staleness, health, rows and files.

The servers are synthetic (an in-memory httpx transport). The bodies they serve are
real fixtures (fixtures/hearst/), served for a synthetic platform whose terms are
recorded as permitting automated reading, so the full path runs without contacting
any station.
"""

import json
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path

import httpx
import pytest
import yaml  # type: ignore[import-untyped, unused-ignore]

from snowlight.cli import main
from snowlight.sources.stations import cli as stations_cli
from snowlight.sources.stations import fetch
from snowlight.sources.stations.http import USER_AGENT, ConditionalStore, PoliteClient, Timing
from snowlight.sources.stations.model import HealthStatus
from snowlight.sources.stations.registry import load_registry

FIXTURES = Path(__file__).parent / "fixtures" / "hearst"
NOW = datetime(2026, 1, 26, 14, 21, 1, tzinfo=UTC)


def _platform(access: str = "permitted") -> dict[str, object]:
    return {
        "id": "demo",
        "name": "Demo platform (synthetic)",
        "operator": "Nobody",
        "adapter": "hearst",
        "poll_minutes": 10,
        "terms": {
            "automated_access": access,
            "summary": "synthetic terms for tests",
            "evidence": [
                {
                    "url": "https://demo.test/terms",
                    "read_at": "2026-09-25T00:00:00Z",
                    "sha256": None,
                    "excerpt": ["synthetic"],
                }
            ],
        },
        "notes": "synthetic",
    }


def _station(sid: str, url: str | None, status: str = "active") -> dict[str, object]:
    return {
        "id": sid,
        "platform": "demo",
        "call_sign": sid.split("-")[1].upper(),
        "name": sid,
        "market": "Kansas City",
        "dma": None,
        "states": ["MO"],
        "counties": {"basis": "observed", "source": "synthetic", "fips": ["29095"]},
        "page_url": url,
        "data_url": None,
        "archive_urls": [],
        "poll_minutes": None,
        "status": status,
        "evidence": "synthetic",
    }


def _registry(tmp_path: Path, access: str = "permitted") -> Path:
    folder = tmp_path / "sources"
    folder.mkdir()
    stations = [
        _station("demo-rows", "https://demo.test/rows"),
        _station("demo-next", "https://demo.test/next"),
        _station("demo-blocked", "https://demo.test/private/closings"),
        _station("demo-old", "https://demo.test/old"),
        _station("demo-broken", "https://demo.test/broken"),
        _station("demo-down", "https://demo.test/down"),
        _station("demo-none", None, status="no_endpoint"),
    ]
    content = {"platform": _platform(access), "stations": stations}
    (folder / "demo.yaml").write_text(yaml.safe_dump(content), encoding="utf-8")
    return folder


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/robots.txt":
        return httpx.Response(200, content=b"User-agent: *\nDisallow: /private/\n")
    if path in {"/rows", "/private/closings"}:
        return httpx.Response(200, content=(FIXTURES / "kmbc-20240117203333.html").read_bytes())
    if path == "/old":
        # A list file nothing has written to since before the last winter began.
        return httpx.Response(
            200,
            content=(FIXTURES / "kmbc-20240117203333.html").read_bytes(),
            headers={"Last-Modified": "Thu, 10 Feb 2022 16:02:11 GMT"},
        )
    if path == "/next":
        return httpx.Response(200, content=(FIXTURES / "wcvb-20260223150125.html").read_bytes())
    if path == "/broken":
        return httpx.Response(200, content=b"<html><body>We moved!</body></html>")
    return httpx.Response(500)


class Ticker:
    def __init__(self) -> None:
        self.now = NOW
        self.mono = 0.0

    def clock(self) -> datetime:
        return self.now

    def monotonic(self) -> float:
        return self.mono

    def sleep(self, seconds: float) -> None:
        self.mono += seconds
        self.now += timedelta(seconds=seconds)


def _client(tmp_path: Path, ticker: Ticker) -> PoliteClient:
    client = httpx.Client(
        transport=httpx.MockTransport(_handler), headers={"User-Agent": USER_AGENT}
    )
    return PoliteClient(
        client,
        ConditionalStore(tmp_path / "cache"),
        timing=Timing(clock=ticker.clock, monotonic=ticker.monotonic, sleep=ticker.sleep),
    )


def test_run_reads_parses_and_records_health(tmp_path: Path) -> None:
    registry = load_registry(_registry(tmp_path))
    ticker = Ticker()
    result = fetch.run(registry, _client(tmp_path, ticker), clock=ticker.clock)
    health = {entry.source_id: entry for entry in result.health}
    assert health["demo-rows"].status is HealthStatus.OK
    assert health["demo-rows"].rows == 4
    assert health["demo-rows"].variant == "hearst-rows"
    assert health["demo-next"].rows == 492
    # robots.txt disallows /private/: the list is read all the same (the owner's
    # decision of 2026-09-26) and the verdict is recorded with the read.
    blocked = health["demo-blocked"]
    assert (blocked.status, blocked.rows) == (HealthStatus.OK, 4)
    assert [(r.url, r.allowed, r.rule) for r in blocked.robots] == [
        ("https://demo.test/private/closings", False, "Disallow: /private/")
    ]
    assert all(r.allowed for r in health["demo-rows"].robots)
    assert health["demo-rows"].robots[0].state.value == "parsed"
    old = health["demo-old"]
    assert (old.status, old.rows) == (HealthStatus.STALE, 0)
    assert old.last_modified == datetime(2022, 2, 10, 16, 2, 11, tzinfo=UTC)
    assert "last modified 2022-02-10T16:02:11Z" in (old.reason or "")
    assert "2024-11-01T00:00:00Z" in (old.reason or "")  # the 2024-25 winter's start
    assert not [row for row in result.rows if row.source_id == "demo-old"]
    assert health["demo-broken"].status is HealthStatus.ERROR
    assert "unrecognized shape" in (health["demo-broken"].reason or "")
    assert health["demo-down"].status is HealthStatus.ERROR
    assert health["demo-down"].http_status == 500
    assert health["demo-none"].status is HealthStatus.SKIPPED
    assert health["demo-none"].reason == "no known closings endpoint"
    rows = [row for row in result.rows if row.source_id == "demo-rows"]
    assert [row.raw_name for row in rows][:2] == [
        "Bannister Road Baptist Church",
        "Christ United Methodist",
    ]
    assert all(row.fetched_at >= NOW for row in rows)
    assert fetch.totals(result.health) == {
        "ok": 3,
        "empty": 0,
        "error": 2,
        "stale": 1,
        "skipped": 1,
        "rows": 500,
        "sources": 7,
        "robots_disallowed": 1,
    }


def test_forbidden_terms_skip_every_station_without_a_request(tmp_path: Path) -> None:
    registry = load_registry(_registry(tmp_path, access="forbidden"))
    requests: list[str] = []

    def spy(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return _handler(request)

    ticker = Ticker()
    client = PoliteClient(
        httpx.Client(transport=httpx.MockTransport(spy)),
        ConditionalStore(tmp_path / "cache"),
        timing=Timing(clock=ticker.clock, monotonic=ticker.monotonic, sleep=ticker.sleep),
    )
    result = fetch.run(registry, client, clock=ticker.clock)
    assert requests == []
    assert {entry.status for entry in result.health} == {HealthStatus.SKIPPED}
    assert all("terms forbid" in (e.reason or "") for e in result.health if e.url)


def test_only_restricts_the_run_and_rejects_unknown_ids(tmp_path: Path) -> None:
    registry = load_registry(_registry(tmp_path))
    ticker = Ticker()
    result = fetch.run(registry, _client(tmp_path, ticker), clock=ticker.clock, only=["demo-rows"])
    assert [entry.source_id for entry in result.health] == ["demo-rows"]
    with pytest.raises(KeyError, match="unknown"):
        fetch.run(registry, _client(tmp_path, ticker), clock=ticker.clock, only=["demo-x"])


def test_outputs_are_written(tmp_path: Path) -> None:
    registry = load_registry(_registry(tmp_path))
    ticker = Ticker()
    result = fetch.run(registry, _client(tmp_path, ticker), clock=ticker.clock)
    paths = fetch.write_outputs(result, tmp_path / "out", NOW)
    rows = paths["rows"].read_text(encoding="utf-8").splitlines()
    assert len(rows) == 500
    first = json.loads(rows[0])
    assert set(first) == {
        "source_id",
        "fetched_at",
        "raw_name",
        "raw_status",
        "raw_updated_text",
        "raw_extra",
    }
    health = json.loads(paths["health"].read_text(encoding="utf-8"))
    assert health["totals"]["rows"] == 500
    assert health["stale_before"] == "2024-11-01T00:00:00Z"
    by_id = {entry["source_id"]: entry for entry in health["sources"]}
    assert by_id["demo-blocked"]["robots"][0]["allowed"] is False
    assert by_id["demo-old"]["last_modified"] == "2022-02-10T16:02:11Z"
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    assert {snap["source_id"] for snap in manifest["snapshots"]} == {
        "demo-rows",
        "demo-next",
        "demo-blocked",
        "demo-old",
        "demo-broken",
        "demo-down",
    }
    reads = [json.loads(line) for line in paths["reads"].read_text().splitlines()]
    assert [read["variant"] for read in reads] == [
        "hearst-rows",
        "hearst-next",
        "hearst-rows",
        "hearst-rows",
    ]
    assert [read["last_modified"] for read in reads][2] == "2022-02-10T16:02:11Z"


def test_cli_fetch_reads_the_real_registry_politely(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real registry's platforms forbid automated access, but the owner's recorded
    decision lets their stations be read: robots.txt first, then the list, with the
    repository's User-Agent. The servers are synthetic; the bodies are real fixtures."""
    seen: list[tuple[str, str]] = []
    export = Path(__file__).parent / "fixtures" / "gray" / "kctv-export-20240128101402.json"

    def serve(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers.get("User-Agent", "")))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=b"User-agent: *\nDisallow: /api/\n")
        if request.url.host == "s3.amazonaws.com":
            return httpx.Response(200, content=export.read_bytes())
        return httpx.Response(200, content=(FIXTURES / "kmbc-20260122213928.html").read_bytes())

    ticker = Ticker()
    monkeypatch.setattr(
        stations_cli,
        "make_client",
        lambda: httpx.Client(
            transport=httpx.MockTransport(serve), headers={"User-Agent": USER_AGENT}
        ),
    )
    monkeypatch.setattr(
        stations_cli,
        "PoliteClient",
        partial(
            PoliteClient,
            timing=Timing(clock=ticker.clock, monotonic=ticker.monotonic, sleep=ticker.sleep),
        ),
    )
    code = main(
        [
            "stations",
            "fetch",
            "--only",
            "gray-kctv",
            "hearst-kmbc",
            "--out-dir",
            str(tmp_path / "out"),
            "--cache-dir",
            str(tmp_path / "cache"),
        ]
    )
    assert code == 0
    assert (
        "2 sources: 1 ok, 1 empty, 0 stale, 0 error, 0 skipped; 1 rows; 0 read although "
        "robots.txt disallows them (recorded)"
    ) in capsys.readouterr().out
    assert [url for url, _agent in seen] == [
        "https://s3.amazonaws.com/robots.txt",
        "https://s3.amazonaws.com/grayfilestore-kctv/closingsData/closings_KCTV.json",
        "https://www.kmbc.com/robots.txt",
        "https://www.kmbc.com/weather/closings",
    ]
    assert {agent for _url, agent in seen} == {USER_AGENT}
    assert "jsalcards" in USER_AGENT


def test_cli_registry_summary(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["stations", "registry"]) == 0
    out = capsys.readouterr().out
    registry = load_registry()
    for platform in ("gray", "hearst"):
        members = [s for s in registry.stations.values() if s.platform == platform]
        active = sum(s.status.value == "active" for s in members)
        assert f"{platform}: {len(members)} stations ({active} with an endpoint)" in out
    # Every one of the 123 Gray exports the research verified is registered, WBBJ's,
    # which an archived capture shows its Arc site loading, and KATC's, read live.
    gray = [s for s in registry.stations.values() if s.platform == "gray"]
    assert sum(1 for s in gray if s.export_url) == 125
    assert "terms forbidden: polled (project owner's decision of 2026-09-25)" in out


def test_cli_reports_a_bad_registry(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["stations", "--registry", str(tmp_path), "registry"]) == 1
    assert "no registry files" in capsys.readouterr().err


def test_gray_pages_and_count_only_health(tmp_path: Path) -> None:
    folder = tmp_path / "sources"
    folder.mkdir()
    platform = {**_platform(), "id": "graydemo", "adapter": "gray"}
    stations = []
    for sid, path in (("graydemo-kctv", "/kctv"), ("graydemo-wkyt", "/wkyt")):
        station = _station(sid, f"https://gray.test{path}")
        station["platform"] = "graydemo"
        stations.append(station)
    content = {"platform": platform, "stations": stations}
    (folder / "graydemo.yaml").write_text(yaml.safe_dump(content), encoding="utf-8")
    gray_fixtures = FIXTURES.parent / "gray"

    def handler(request: httpx.Request) -> httpx.Response:
        files = {"/kctv": "kctv-20240115205330.html", "/wkyt": "wkyt-20260127004608.html"}
        if request.url.path in files:
            return httpx.Response(
                200, content=(gray_fixtures / files[request.url.path]).read_bytes()
            )
        return httpx.Response(404)

    ticker = Ticker()
    client = PoliteClient(
        httpx.Client(transport=httpx.MockTransport(handler)),
        ConditionalStore(tmp_path / "cache"),
        timing=Timing(clock=ticker.clock, monotonic=ticker.monotonic, sleep=ticker.sleep),
    )
    result = fetch.run(load_registry(folder), client, clock=ticker.clock)
    health = {entry.source_id: entry for entry in result.health}
    assert (health["graydemo-kctv"].status, health["graydemo-kctv"].rows) == (HealthStatus.OK, 21)
    wkyt = health["graydemo-wkyt"]
    assert wkyt.status is HealthStatus.ERROR
    assert wkyt.variant == "gray-fusion-count"
    assert "only a count (318 listed)" in (wkyt.reason or "")
    states = {read.source_id: read.state.value for read in result.reads}
    assert states == {"graydemo-kctv": "populated", "graydemo-wkyt": "count_only"}
