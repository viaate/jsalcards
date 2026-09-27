"""The archive-captures workflow: its shape, its request file, and its reader script.

The reader script is taken from the workflow file itself and run against a local,
synthetic stand-in for the Wayback Machine (CDX answers, id_ captures, a redirect
to the nearest capture, a 429 with Retry-After, a gzip body and a redirect that
leaves the archive), so what is tested is exactly what the runner executes.
"""

import gzip
import hashlib
import json
import os
import subprocess
import sys
import threading
from collections.abc import Iterator, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml  # type: ignore[import-untyped, unused-ignore]

REPO = Path(__file__).resolve().parents[3]
WORKFLOW = REPO / ".github" / "workflows" / "archive-captures.yml"
REQUEST = REPO / "pipeline" / "config" / "archive-requests.json"
PAGE = b"<html><body>closings</body></html>"


def _steps() -> list[dict[str, Any]]:
    loaded = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = loaded["jobs"]["archive"]["steps"]
    assert isinstance(steps, list)
    return steps


def _script(tmp_path: Path) -> Path:
    (writer,) = [s for s in _steps() if s.get("name") == "Write the archive reader"]
    run = str(writer["run"])
    body = run.split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    path = tmp_path / "archive_reader.py"
    path.write_text(body + "\n", encoding="utf-8")
    return path


def test_workflow_triggers_on_the_request_file_and_uploads_both_artifacts() -> None:
    loaded = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = loaded[True]  # YAML reads the bare key "on" as True
    assert triggers["push"]["paths"] == ["pipeline/config/archive-requests.json"]
    assert "workflow_dispatch" in triggers
    assert loaded["permissions"] == {"contents": "read"}
    names = [s.get("name") or s.get("uses") for s in _steps()]
    assert names.index("Download snapshots") < names.index("List captures")
    uploads = [
        s["with"]["name"]
        for s in _steps()
        if str(s.get("uses", "")).startswith("actions/upload-artifact")
    ]
    assert uploads == ["snapshots-${{ github.run_id }}", "cdx-${{ github.run_id }}"]
    for step in _steps():
        if step.get("name") in {"Download snapshots", "List captures"}:
            env = step["env"]
            assert isinstance(env, dict)
            assert float(env["PAUSE_SECONDS"]) >= 5


def test_committed_request_file_is_valid(tmp_path: Path) -> None:
    env = {**os.environ, "EVENT": "push", "REQUEST_FILE": str(REQUEST), "MODE": "check"}
    done = subprocess.run(  # noqa: S603 - runs the workflow's own script
        [sys.executable, str(_script(tmp_path))],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "request is valid" in done.stdout


class _Archive(BaseHTTPRequestHandler):
    agents: ClassVar[list[str]] = []
    queries: ClassVar[list[dict[str, list[str]]]] = []
    retried: ClassVar[bool] = False

    def log_message(self, *_args: object) -> None:
        return

    def _send(self, status: int, body: bytes = b"", headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        type(self).agents.append(self.headers.get("User-Agent", ""))
        parts = urlsplit(self.path)
        if parts.path == "/cdx":
            query = parse_qs(parts.query)
            type(self).queries.append(query)
            rows = [
                ["timestamp", "original", "statuscode", "mimetype", "length", "digest"],
                ["20240117203333", query["url"][0], "200", "text/html", "100", "D"],
            ]
            self._send(200, json.dumps(rows).encode())
        elif parts.path.startswith("/web/20240108050323id_/"):
            target = parts.path.split("id_/", 1)[1]
            self._send(302, headers={"Location": f"/web/20240117203333id_/{target}"})
        elif parts.path.startswith("/web/20240117203333id_/"):
            if not type(self).retried:
                type(self).retried = True
                self._send(429, headers={"Retry-After": "0"})
                return
            self._send(200, PAGE, {"Content-Type": "text/html", "Memento-Datetime": "x"})
        elif parts.path.startswith("/web/20250101000000id_/"):
            body = gzip.compress(PAGE)
            self._send(200, body, {"Content-Type": "text/html", "Content-Encoding": "gzip"})
        elif parts.path.startswith("/web/20250202000000id_/"):
            self._send(302, headers={"Location": "https://elsewhere.test/page"})
        else:
            self._send(404)


@pytest.fixture
def archive() -> Iterator[str]:
    _Archive.agents = []
    _Archive.queries = []
    _Archive.retried = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Archive)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _run(
    tmp_path: Path,
    origin: str,
    request: Mapping[str, object],
    mode: str,
    extra_env: Mapping[str, str] | None = None,
) -> Path:
    request_file = tmp_path / "request.json"
    request_file.write_text(json.dumps(request), encoding="utf-8")
    out = tmp_path / f"out-{mode}"
    env = {
        **os.environ,
        "EVENT": "push",
        "REQUEST_FILE": str(request_file),
        "MODE": mode,
        "OUT_DIR": str(out),
        "PAUSE_SECONDS": "0",
        "BACKOFF_SECONDS": "0",
        "CDX_ENDPOINT": f"{origin}/cdx",
        "WAYBACK_ORIGIN": origin,
        **(extra_env or {}),
    }
    done = subprocess.run(  # noqa: S603 - runs the workflow's own script
        [sys.executable, str(_script(tmp_path))],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    return out


def test_snapshots_are_downloaded_with_provenance(tmp_path: Path, archive: str) -> None:
    request = {
        "snapshots": [
            {"timestamp": "20240108050323", "url": "https://www.kmbc.com/weather/closings"},
            {"timestamp": "20250101000000", "url": "https://www.wgal.com/weather/closings"},
            {"timestamp": "20250202000000", "url": "https://www.wcvb.com/weather/closings"},
        ],
        "cdx": [{"url": "kmbc.com/weather/closings*", "from": "20140101", "to": "20260930"}],
    }
    out = _run(tmp_path, archive, request, "snapshots")
    records = [
        json.loads(line) for line in (out / "snapshots" / "manifest.jsonl").read_text().splitlines()
    ]
    first, second, third = records
    assert first["final_timestamp"] == "20240117203333"
    assert first["final_original"] == "https://www.kmbc.com/weather/closings"
    assert first["hops"][0]["status"] == 302
    body = (out / first["file"]).read_bytes()
    assert body == PAGE
    assert first["sha256"] == hashlib.sha256(PAGE).hexdigest()
    assert second["content_encoding"] == "gzip"
    assert gzip.decompress((out / second["file"]).read_bytes()) == PAGE
    assert third["error"] == "redirect leaves the archive"
    assert not list(out.glob("*.json"))  # listings wait for their own step
    assert all("github.com/viaate/jsalcards" in agent for agent in _Archive.agents)


def test_listings_are_written_per_window(tmp_path: Path, archive: str) -> None:
    request = {
        "urls": ["www.kmbc.com/weather/closings*"],
        "from": "20231101",
        "to": "20260331",
        "cdx": [{"url": "wgal.com/weather/closings*", "from": "20140101", "to": "20260930"}],
        "snapshots": [{"timestamp": "20240108050323", "url": "https://www.kmbc.com/x"}],
    }
    out = _run(tmp_path, archive, request, "listings")
    names = sorted(path.name for path in out.glob("*.json"))
    assert names == [
        "wgal_com_weather_closings___20140101-20260930.json",
        "www_kmbc_com_weather_closings_.json",
    ]
    assert not (out / "snapshots").exists()


def test_listings_pass_filters_and_collapse_and_name_them_apart(
    tmp_path: Path, archive: str
) -> None:
    window = {"url": "webpubcontent.raycommedia.com/*", "from": "20181101", "to": "20190331"}
    request = {
        "cdx": [
            window,
            {**window, "filter": ["original:.*[Cc]losings.*", "statuscode:200"]},
            {**window, "filter": ["original:.*[Cc]losings.*"], "collapse": "urlkey"},
        ]
    }
    out = _run(tmp_path, archive, request, "listings")
    names = sorted(path.name for path in out.glob("*.json"))
    stem = "webpubcontent_raycommedia_com____20181101-20190331"
    assert len(names) == 3
    assert f"{stem}.json" in names
    assert all(name.startswith(stem) for name in names)
    assert len({name for name in names if "__f" in name}) == 2
    plain, filtered, collapsed = _Archive.queries
    assert "filter" not in plain
    assert "collapse" not in plain
    assert filtered["filter"] == ["original:.*[Cc]losings.*", "statuscode:200"]
    assert collapsed["collapse"] == ["urlkey"]


@pytest.mark.parametrize(
    "request_body",
    [
        {},
        {"cdx": [{"url": "x.test/*", "from": "20240101", "to": "20240102", "filter": "x"}]},
        {"cdx": [{"url": "x.test/*", "from": "20240101", "to": "20240102", "filter": ["a b"]}]},
        {"cdx": [{"url": "x.test/*", "from": "20240101", "to": "20240102", "collapse": "x;"}]},
        {"snapshots": [{"timestamp": "2024", "url": "https://x.test/"}]},
        {"snapshots": [{"timestamp": "20240108050323", "url": "ftp://x.test/"}]},
        {"cdx": [{"url": "x.test/*", "from": "2024", "to": "20240101"}]},
    ],
)
def test_bad_requests_fail(tmp_path: Path, request_body: dict[str, object]) -> None:
    request_file = tmp_path / "request.json"
    request_file.write_text(json.dumps(request_body), encoding="utf-8")
    env = {**os.environ, "EVENT": "push", "REQUEST_FILE": str(request_file), "MODE": "check"}
    done = subprocess.run(  # noqa: S603 - runs the workflow's own script
        [sys.executable, str(_script(tmp_path))],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 1
    assert "::error::" in done.stdout


def test_snapshots_past_the_time_budget_are_recorded_as_not_attempted(
    tmp_path: Path, archive: str
) -> None:
    request = {
        "snapshots": [
            {"timestamp": "20250101000000", "url": "https://www.wgal.com/weather/closings"},
            {"timestamp": "20250101000000", "url": "https://www.wcvb.com/weather/closings"},
        ]
    }
    out = _run(tmp_path, archive, request, "snapshots", {"BUDGET_MINUTES": "0"})
    lines = (out / "snapshots" / "manifest.jsonl").read_text().splitlines()
    records = [json.loads(line) for line in lines]
    assert [record["error"] for record in records] == [
        "not attempted: the run's time budget was spent"
    ] * 2
    assert _Archive.agents == []
