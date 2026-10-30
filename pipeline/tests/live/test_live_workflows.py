"""E1 (T15c): the live workflows' contract, and their scripts against SYNTHETIC stubs.

live-read.yml, live-blank.yml and live-drill.yml as the S8-E addendum pins them; live-ingest.yml
with its `reader` and `watch` jobs, the publish job's mode clause, and check and notify
unchanged since 71d6ed9. The reader, watch, successor and export-check scripts run here
against a stub GitHub API and a stub live host on a loopback port (bash, curl and jq, as the
runner has).
"""

import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped, unused-ignore]

from snowlight.live import cli as live_cli

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
TOOLS = all(shutil.which(tool) for tool in ("bash", "curl", "jq", "tar"))
needs_tools = pytest.mark.skipif(not TOOLS, reason="needs bash, curl, jq and tar")
DEFAULT_BRANCH_IF = "github.ref == format('refs/heads/{0}', github.event.repository.default_branch)"
CLOUDFLARE = ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID")
UNCHANGED = {
    # sha256 of each job's canonical JSON at 71d6ed9 (check and notify stay byte-identical)
    "check": "1753fef393791ee636e8a3dde0d09520e6b2c4c20061a32002066c6b8a50bab3",
    "notify": "97d3a933af06f41fa761aa09380bc59983129fb504a686d402d64d05025edefd",
}


def load(name: str) -> dict[Any, Any]:
    found = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    assert isinstance(found, dict)
    return found


def steps(workflow: dict[Any, Any], job: str) -> list[dict[str, Any]]:
    found = workflow["jobs"][job]["steps"]
    assert isinstance(found, list)
    return found


def step(workflow: dict[Any, Any], job: str, name: str) -> dict[str, Any]:
    return next(
        item for item in steps(workflow, job) if item.get("name") == name or item.get("id") == name
    )


# --- live-read.yml ---------------------------------------------------------------------------


def test_live_read_triggers_and_job() -> None:
    workflow = load("live-read.yml")
    assert set(workflow[True]) == {"workflow_dispatch", "schedule", "push"}
    assert set(workflow[True]["workflow_dispatch"]["inputs"]) == {"mode"}
    assert workflow[True]["schedule"] == [{"cron": "*/20 * * * *"}]
    assert workflow[True]["push"] == {"paths": [".github/workflows/live-read.yml"]}
    assert "pull_request" not in workflow[True]
    assert workflow["permissions"] == {
        "contents": "read",
        "actions": "write",
        "deployments": "read",
        "issues": "write",
    }
    job = workflow["jobs"]["read"]
    assert job["if"] == f"github.event_name == 'schedule' || {DEFAULT_BRANCH_IF}"
    assert job["concurrency"] == {"group": "live-read", "cancel-in-progress": False}
    assert "concurrency" not in workflow  # at the job level only
    assert job["environment"] == "live"
    assert job["timeout-minutes"] == 345
    assert job["continue-on-error"] == "${{ (inputs.mode || vars.LIVE_PUBLISH) != 'on' }}"
    assert job["env"]["LIVE_PUBLISH"] == "${{ inputs.mode || vars.LIVE_PUBLISH }}"
    assert workflow["run-name"] == "live-read ${{ inputs.mode || vars.LIVE_PUBLISH || 'shadow' }}"
    checkout = next(item for item in steps(workflow, "read") if "checkout" in str(item.get("uses")))
    assert checkout["with"] == {"persist-credentials": False}


def test_live_read_loop_limits_and_secrets() -> None:
    workflow = load("live-read.yml")
    loop = step(workflow, "read", "loop")
    run = str(loop["run"])
    assert "--until +320m" in run
    minutes = [int(part.split("+")[1].rstrip("m")) for part in run.split() if part.startswith("+")]
    assert minutes == [320]
    limit, grace = (
        int(value.total_seconds()) for value in (live_cli.PULSE_MAX_AGE, live_cli.PULSE_GRACE)
    )
    watcher = f"pulse-watch.sh out/internal/live/state/pulse {limit} {grace}"
    assert watcher in run
    assert "--push-every 30" in run
    # the Cloudflare secrets reach only the pull, loop and end-push steps, never the job
    assert not any(
        name in json.dumps(workflow["jobs"]["read"].get("env", {})) for name in CLOUDFLARE
    )
    holders = {
        str(item.get("id"))
        for item in steps(workflow, "read")
        if any(name in json.dumps(item.get("env", {})) for name in CLOUDFLARE)
    }
    assert holders == {"pull", "loop", "push"}


def test_live_read_keeps_the_evidence_in_a_job_of_its_own_that_never_holds_the_reader() -> None:
    workflow = load("live-read.yml")
    # the reader job ends with its cache save: nothing after it holds the `live-read` group
    assert "cache/save" in str(steps(workflow, "read")[-1].get("uses"))
    assert not any("evidence" in str(item.get("run", "")) for item in steps(workflow, "read"))
    job = workflow["jobs"]["evidence"]
    assert job["needs"] == "read"
    # only after a reader job that ran: never for a run whose reader was cancelled
    assert job["if"] == (
        "always() && (needs.read.result == 'success' || needs.read.result == 'failure')"
    )
    assert job["permissions"] == {"contents": "read"}
    assert "concurrency" not in job
    # nothing is set up before this run's export is found
    names = [str(item.get("id") or item.get("uses")) for item in steps(workflow, "evidence")]
    assert names.index("export") < next(i for i, n in enumerate(names) if "setup-uv" in n)
    for item in steps(workflow, "evidence")[names.index("export") + 1 :]:
        assert "steps.export.outputs.cache-hit == 'true'" in str(item.get("if"))
    assert "concurrency" not in workflow
    assert job["timeout-minutes"] <= 15
    # this run's export only, by its exact key (no restore-keys: never another run's)
    restore = step(workflow, "evidence", "export")
    assert "cache/restore" in str(restore["uses"])
    assert restore["with"] == {
        "path": "pipeline/out/internal/live/store",
        "key": "live-state-${{ github.run_id }}",
    }
    push = step(workflow, "evidence", "push")
    assert push["if"] == "steps.export.outputs.cache-hit == 'true'"
    assert push["continue-on-error"] is True
    assert push["timeout-minutes"] <= 8
    assert timedelta(minutes=push["timeout-minutes"]) > timedelta(seconds=live_cli.EVIDENCE_FOR)
    assert push["run"] == (
        "uv run snowlight live evidence push --export out/internal/live/store/live-state.tar.gz"
    )
    assert set(push["env"]) == set(CLOUDFLARE)
    # the Cloudflare secrets reach the push alone, and no other secret or token reaches the job
    job_text = json.dumps(job)
    assert job_text.count("secrets.") == 2
    assert "github.token" not in job_text
    assert "SNOWLIGHT_LIVE_TOKEN" not in job_text


def test_live_read_end_steps_and_the_successor() -> None:
    workflow = load("live-read.yml")
    names = [
        str(item.get("id") or item.get("name") or item.get("uses"))
        for item in steps(workflow, "read")
    ]
    gated = "always() && steps.pull.outcome == 'success' && steps.reap.outputs.clear == 'true'"
    for key in ("push", "export", "check"):
        assert step(workflow, "read", key)["if"] == gated
    # no reader is left alive before anything packs the state (a cancel included)
    reap = step(workflow, "read", "reap")
    assert reap["if"] == "always() && steps.token.outputs.ready == 'true'"
    assert "reap-reader.sh" in str(reap["run"])
    assert names.index("loop") < names.index("reap") < names.index("record")
    assert names.index("reap") < min(names.index(key) for key in ("push", "export", "check"))
    save = next(item for item in steps(workflow, "read") if "cache/save" in str(item.get("uses")))
    assert str(save["if"]).startswith(gated)
    assert "steps.check.outcome == 'success'" in str(save["if"])
    assert names.index("check") < names.index(str(save["uses"]))  # the check before the save
    assert save["with"] == {
        "path": "pipeline/out/internal/live/store",
        "key": "live-state-${{ github.run_id }}",
    }
    successor = step(workflow, "read", "successor")
    assert str(successor["if"]).startswith("(success() || failure())")
    assert names.index("successor") < names.index("push")
    pull = step(workflow, "read", "pull")
    assert pull["continue-on-error"] is True
    # a stalled download or pull ends its step, never holding the job to its 345 minutes
    # (the pull's own bound, PULL_FOR, is under its step's)
    assert pull["timeout-minutes"] == 8
    assert timedelta(minutes=8) > live_cli.PULL_FOR
    assert step(workflow, "read", "directory")["timeout-minutes"] == 10
    assert "--retry" in str(pull["run"])
    assert "--overrides-only" in str(step(workflow, "read", "loop")["run"])


def _live_files() -> list[str]:
    return sorted(path.name for path in WORKFLOWS.glob("live-*.yml"))


def test_live_workflows_upload_no_artifact_and_cache_only_the_export() -> None:
    assert _live_files() == ["live-blank.yml", "live-drill.yml", "live-ingest.yml", "live-read.yml"]
    for name in _live_files():
        workflow = load(name)
        for job_name, job in workflow["jobs"].items():
            for item in job.get("steps", []):
                uses = str(item.get("uses", ""))
                assert "upload-artifact" not in uses
                if "cache" not in uses:
                    continue
                path = str(item.get("with", {}).get("path", ""))
                assert ".cache/stations" not in path
                if name == "live-ingest.yml":
                    # the overrides job's own memory, as at 71d6ed9 (codes and times only)
                    assert job_name == "publish"
                    assert item["with"]["key"] == "live-overrides-state-${{ github.run_id }}"
                    continue
                if "cache/save" in uses:
                    assert (name, path) == ("live-read.yml", "pipeline/out/internal/live/store")
                elif job_name == "evidence":
                    # the evidence job restores this run's export, by its exact key only
                    assert (name, path) == ("live-read.yml", "pipeline/out/internal/live/store")
                    assert "restore-keys" not in item["with"]
                else:
                    assert "out/internal/live" not in path


def test_live_blank_is_the_owners_button() -> None:
    workflow = load("live-blank.yml")
    assert set(workflow[True]) == {"workflow_dispatch"}
    inputs = workflow[True]["workflow_dispatch"]["inputs"]
    assert inputs["action"]["options"] == ["blank", "release"]
    assert inputs["prefix"]["options"] == ["every", "v1", "v1-shadow"]
    assert inputs["prefix"]["default"] == "every"
    assert workflow["concurrency"] == {"group": "live-blank", "cancel-in-progress": False}
    job = workflow["jobs"]["blank"]
    assert job["environment"] == "live"
    assert job["timeout-minutes"] == 5
    text = (WORKFLOWS / "live-blank.yml").read_text(encoding="utf-8")
    assert "CLOUDFLARE" not in text
    assert "actions/cache" not in text
    assert 'uv run snowlight live "$ACTION" --prefix "$PREFIX"' in text


def test_live_drill_runs_only_from_a_push_of_itself() -> None:
    workflow = load("live-drill.yml")
    assert workflow[True] == {"push": {"paths": [".github/workflows/live-drill.yml"]}}
    # it lands as none: the push that adds the file starts no drill
    assert workflow["env"]["DRILL"] in {"none", "stall", "gate", "switch"}
    job = workflow["jobs"]["drill"]
    assert job["timeout-minutes"] >= 35 + 5 + 10 + 1  # the stall, the tick wait, the poll
    assert job["if"] == DEFAULT_BRANCH_IF
    assert job["env"]["SHADOW_PREFIX"] == "v1-shadow"
    assert job["env"]["REHEARSE_PREFIX"] == "v1-rehearse"
    text = (WORKFLOWS / "live-drill.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" not in text.split("jobs:")[0]
    assert '"prefix": "v1"' not in text
    assert "prefix: v1\n" not in text
    guard = str(step(workflow, "drill", "guard")["run"])
    assert "LIVE_PUBLISH is on" in guard
    assert "v1/live/hold.json" in guard


# --- live-ingest.yml -------------------------------------------------------------------------


def test_live_ingest_keeps_check_and_notify_and_gains_reader_and_watch() -> None:
    workflow = load("live-ingest.yml")
    jobs = workflow["jobs"]
    for name, digest in UNCHANGED.items():
        canonical = json.dumps(jobs[name], sort_keys=True).encode()
        assert hashlib.sha256(canonical).hexdigest() == digest, name
    assert (
        jobs["publish"]["if"]
        == "needs.check.outputs.publish == 'true' && vars.LIVE_PUBLISH != 'on'"
    )
    for name, minutes in (("reader", 2), ("watch", 3)):
        job = jobs[name]
        assert job["continue-on-error"] is True
        assert job["timeout-minutes"] == minutes
        assert job["if"] == DEFAULT_BRANCH_IF
        assert "needs" not in job
        text = json.dumps(job)
        assert "secrets." not in text  # GITHUB_TOKEN only
        assert "actions/checkout" not in text
    assert jobs["reader"]["permissions"] == {"actions": "write"}
    assert jobs["watch"]["permissions"] == {"contents": "read", "issues": "write"}


# --- the scripts against stubs ---------------------------------------------------------------


@dataclass
class Stub:
    """SYNTHETIC answers by method and path; every request is recorded."""

    answers: dict[tuple[str, str], tuple[int, bytes]] = field(default_factory=dict)
    seen: list[tuple[str, str, bytes]] = field(default_factory=list)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    """Sent with every answer."""

    def answer(self, method: str, path: str, code: int, body: object = b"") -> None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.answers[(method, path)] = (code, data)

    def calls(self, method: str) -> list[tuple[str, bytes]]:
        return [(path, body) for verb, path, body in self.seen if verb == method]


@pytest.fixture
def stub() -> Iterator[Stub]:
    found = Stub()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002, ARG002
            return

        def _any(self) -> None:
            length = int(self.headers.get("content-length") or 0)
            body = self.rfile.read(length) if length else b""
            path = self.path.split("?", 1)[0]
            found.seen.append((self.command, self.path, body))
            code, data = found.answers.get((self.command, path), (404, b'{"message": "Not Found"}'))
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            for name, value in found.headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = do_PATCH = do_PUT = _any  # noqa: N815

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    found.url = f"http://127.0.0.1:{httpd.server_address[1]}"
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield found
    httpd.shutdown()
    httpd.server_close()


@dataclass(frozen=True)
class Ran:
    code: int
    out: str


def run_script(script: str, tmp_path: Path, stub: Stub, env: dict[str, str]) -> Ran:
    outputs = tmp_path / "outputs"
    outputs.touch()
    base = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "NO_PROXY": "*",
        "GITHUB_API_URL": f"{stub.url}/api",
        "GITHUB_REPOSITORY": "viaate/synthetic",
        "GITHUB_REF_NAME": "synthetic-main",
        "GITHUB_OUTPUT": str(outputs),
        "GH_TOKEN": "synthetic-token",
        "LIVE_PUBLISH": "",
    }
    done = subprocess.run(  # noqa: S603 - the workflow's own script, in a temporary folder
        ["bash", "-c", script],  # noqa: S607 - bash from PATH, as on the runner
        cwd=tmp_path,
        env={**base, **env},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return Ran(done.returncode, done.stdout + done.stderr)


RUNS = "/api/repos/viaate/synthetic/actions/workflows/live-read.yml/runs"
DISPATCH = "/api/repos/viaate/synthetic/actions/workflows/live-read.yml/dispatches"


def _run(id_: int, title: str, created: datetime, status: str = "in_progress") -> dict[str, object]:
    return {
        "id": id_,
        "status": status,
        "display_title": title,
        "created_at": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _reader(tmp_path: Path, stub: Stub, live_publish: str = "") -> Ran:
    script = str(steps(load("live-ingest.yml"), "reader")[0]["run"])
    return run_script(script, tmp_path, stub, {"LIVE_PUBLISH": live_publish})


@needs_tools
def test_the_reader_job_starts_one_when_none_runs(tmp_path: Path, stub: Stub) -> None:
    stub.answer("GET", RUNS, 200, {"workflow_runs": []})
    stub.answer("POST", DISPATCH, 204)
    ran = _reader(tmp_path, stub)
    assert ran.code == 0
    assert json.loads(stub.calls("POST")[0][1]) == {
        "ref": "synthetic-main",
        "inputs": {"mode": "shadow"},
    }
    assert "::" not in ran.out


@needs_tools
def test_the_reader_job_counts_runs_by_their_jobs(tmp_path: Path, stub: Stub) -> None:
    now = datetime.now(UTC)
    runs = [
        _run(1, "live-read shadow", now - timedelta(hours=2)),  # listed, its job over
        _run(2, "live-read shadow", now - timedelta(seconds=30), "queued"),  # just made
    ]
    stub.answer("GET", RUNS, 200, {"workflow_runs": runs})
    stub.answer(
        "GET",
        "/api/repos/viaate/synthetic/actions/runs/1/jobs",
        200,
        {"jobs": [{"status": "completed"}]},
    )
    stub.answer("GET", "/api/repos/viaate/synthetic/actions/runs/2/jobs", 200, {"jobs": []})
    ran = _reader(tmp_path, stub)
    assert ran.code == 0
    assert stub.calls("POST") == []  # the new one counts as running
    stub.answer("GET", RUNS, 200, {"workflow_runs": runs[:1]})
    stub.answer("POST", DISPATCH, 204)
    assert _reader(tmp_path, stub).code == 0
    assert [path for path, _ in stub.calls("POST")] == [DISPATCH]  # a listed run whose job ended
    # a run whose reader job ended while its evidence job still pushes: no reader runs, so
    # one is started (the evidence job never holds a reader back)
    stub.seen.clear()
    stub.answer(
        "GET",
        "/api/repos/viaate/synthetic/actions/runs/1/jobs",
        200,
        {
            "jobs": [
                {"name": "read", "status": "completed"},
                {"name": "evidence", "status": "in_progress"},
            ]
        },
    )
    assert _reader(tmp_path, stub).code == 0
    assert [path for path, _ in stub.calls("POST")] == [DISPATCH]
    # its reader job still running: it counts as running, whatever the evidence job does
    stub.seen.clear()
    stub.answer(
        "GET",
        "/api/repos/viaate/synthetic/actions/runs/1/jobs",
        200,
        {"jobs": [{"name": "read", "status": "in_progress"}]},
    )
    assert _reader(tmp_path, stub).code == 0
    assert stub.calls("POST") == []


@needs_tools
def test_the_reader_job_switches_the_mode(tmp_path: Path, stub: Stub) -> None:
    now = datetime.now(UTC)
    stub.answer(
        "GET", RUNS, 200, {"workflow_runs": [_run(7, "live-read shadow", now - timedelta(hours=1))]}
    )
    stub.answer(
        "GET",
        "/api/repos/viaate/synthetic/actions/runs/7/jobs",
        200,
        {"jobs": [{"status": "in_progress"}]},
    )
    stub.answer("POST", "/api/repos/viaate/synthetic/actions/runs/7/cancel", 202)
    stub.answer("POST", DISPATCH, 204)
    ran = _reader(tmp_path, stub, "ON")  # Actions compares ignoring case
    assert ran.code == 0
    posts = stub.calls("POST")
    assert posts[0][0].endswith("/runs/7/cancel")
    assert json.loads(posts[1][1])["inputs"] == {"mode": "on"}
    # the same mode: nothing to do
    stub.seen.clear()
    assert _reader(tmp_path, stub, "shadow").code == 0
    assert stub.calls("POST") == []


@needs_tools
@pytest.mark.parametrize("failing", [("GET", RUNS, 500), ("POST", DISPATCH, 403)])
def test_the_reader_job_never_fails(
    tmp_path: Path, stub: Stub, failing: tuple[str, str, int]
) -> None:
    stub.answer("GET", RUNS, 200, {"workflow_runs": []})
    method, path, code = failing
    stub.answer(method, path, code)
    ran = _reader(tmp_path, stub, "loud")
    assert ran.code == 0
    assert "::notice::" in ran.out
    assert "::warning::LIVE_PUBLISH is not on, shadow or off" in ran.out


def _served(stub: Stub, prefix: str, age: timedelta | None) -> None:
    path = f"/live/{prefix}/live/closings.json"
    if age is None:
        stub.answer("GET", path, 404)
        return
    stamp = (datetime.now(UTC) - age).strftime("%Y-%m-%dT%H:%M:%SZ")
    stub.answer("GET", path, 200, {"generated_at": stamp, "days": []})


def _watch(tmp_path: Path, stub: Stub, live_publish: str) -> Ran:
    script = str(steps(load("live-ingest.yml"), "watch")[0]["run"])
    return run_script(
        script, tmp_path, stub, {"LIVE_PUBLISH": live_publish, "LIVE_ROOT": f"{stub.url}/live/"}
    )


@needs_tools
def test_the_watch_job_in_shadow_annotates_and_opens_no_issue(tmp_path: Path, stub: Stub) -> None:
    _served(stub, "v1-shadow", timedelta(minutes=20))
    ran = _watch(tmp_path, stub, "")
    assert ran.code == 0
    assert "::warning::live watch: the served v1-shadow file is stale" in ran.out
    assert not any("/issues" in path for _, path, _ in stub.seen)
    _served(stub, "v1-shadow", None)
    assert "is missing" in _watch(tmp_path, stub, "").out
    _served(stub, "v1-shadow", timedelta(minutes=-5))
    assert "is ahead" in _watch(tmp_path, stub, "").out
    _served(stub, "v1-shadow", timedelta(minutes=2))
    fresh = _watch(tmp_path, stub, "")
    assert "::warning::" not in fresh.out
    assert "is fresh" in fresh.out
    stub.seen.clear()
    assert _watch(tmp_path, stub, "off").code == 0
    assert stub.seen == []  # nothing is watched in off


@needs_tools
def test_the_watch_job_in_on_opens_and_closes_one_issue(tmp_path: Path, stub: Stub) -> None:
    issues = "/api/repos/viaate/synthetic/issues"
    _served(stub, "v1", timedelta(minutes=20))
    stub.answer("GET", issues, 200, [])
    stub.answer("POST", issues, 201, {"number": 5})
    assert _watch(tmp_path, stub, "on").code == 0
    created = next(json.loads(body) for path, body in stub.calls("POST") if path == issues)
    assert "<!-- live-alert:stale:v1 -->" in created["body"]
    assert created["labels"] == ["live-alert"]
    # open already: no second issue; a fresh file closes it
    stub.seen.clear()
    open_issue = [
        {"number": 5, "body": created["body"], "updated_at": datetime.now(UTC).isoformat()}
    ]
    stub.answer("GET", issues, 200, open_issue)
    assert _watch(tmp_path, stub, "on").code == 0
    assert not any(path == issues for path, _ in stub.calls("POST"))
    _served(stub, "v1", timedelta(minutes=1))
    stub.seen.clear()
    assert _watch(tmp_path, stub, "on").code == 0
    assert any(path.endswith("/issues/5/comments") for path, _ in stub.calls("POST"))
    assert json.loads(stub.calls("PATCH")[0][1]) == {"state": "closed", "state_reason": "completed"}


@needs_tools
def test_the_successor_step_tries_three_times_and_never_fails(tmp_path: Path, stub: Stub) -> None:
    script = str(step(load("live-read.yml"), "read", "successor")["run"]).replace(
        "sleep $((try * 10))", "true"
    )
    stub.answer("POST", DISPATCH, 204)
    ran = run_script(script, tmp_path, stub, {"LIVE_PUBLISH": "Shadow"})
    assert ran.code == 0
    assert json.loads(stub.calls("POST")[0][1])["inputs"] == {"mode": "shadow"}
    stub.seen.clear()
    stub.answer("POST", DISPATCH, 500)
    ran = run_script(script, tmp_path, stub, {})
    assert ran.code == 0
    assert len(stub.calls("POST")) == 3
    assert "::warning::The successor could not be dispatched" in ran.out
    assert "dispatch_failed=true" in (tmp_path / "outputs").read_text(encoding="utf-8")


def _tar(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


@needs_tools
@pytest.mark.parametrize(
    ("members", "extra", "ok"),
    [
        (
            {
                "ledger.sqlite": b"",
                "morning/2026-11-17.json": b"{}",
                "changes/2026-11-17.jsonl": b"",
            },
            False,
            True,
        ),
        ({"ledger.sqlite": b"", "unmatched.json": b"{}"}, False, False),
        ({"ledger.sqlite": b"", "robots.json": b"{}"}, False, False),
        ({"ledger.sqlite": b""}, True, False),
        (None, False, False),  # the export failed and left no archive
        ({}, False, False),  # not an archive at all (below)
    ],
)
def test_the_export_check_refuses_any_other_name(
    tmp_path: Path, stub: Stub, members: dict[str, bytes] | None, extra: bool, ok: bool
) -> None:
    store = tmp_path / "out" / "internal" / "live" / "store"
    store.mkdir(parents=True)
    if members is not None:
        data = _tar(members) if members else b"SYNTHETIC: not a gzip archive"
        (store / "live-state.tar.gz").write_bytes(data)
    if extra:
        (store / "d1.json").write_text("{}", encoding="utf-8")
    script = str(step(load("live-read.yml"), "read", "check")["run"])
    ran = run_script(script, tmp_path, stub, {})
    assert (ran.code == 0) is ok, ran.out


# --- critic round 1: token scope, step order, exits, drills ----------------------------------


def _env_holders(workflow: dict[Any, Any], job: str, name: str) -> set[str]:
    return {
        str(item.get("id") or item.get("name"))
        for item in steps(workflow, job)
        if name in json.dumps(item.get("env", {}))
    }


def test_live_read_gives_each_token_only_to_the_steps_that_use_it() -> None:
    workflow = load("live-read.yml")
    job_env = json.dumps(workflow["jobs"]["read"].get("env", {}))
    assert "secrets." not in job_env
    assert "github.token" not in job_env
    assert _env_holders(workflow, "read", "SNOWLIGHT_LIVE_TOKEN") == {
        "token",
        "loop",
        "push",
        "finish",
    }
    assert _env_holders(workflow, "read", "github.token") == {
        "directory",
        "loop",
        "successor",
        "push",
        "finish",
    }


def test_live_read_reports_after_the_end_push_and_starts_no_successor_without_a_loop() -> None:
    workflow = load("live-read.yml")
    names = [str(item.get("id") or item.get("name")) for item in steps(workflow, "read")]
    assert names.index("successor") < names.index("push") < names.index("finish")
    # the exit is in the state before the end push carries it to D1 (the chain alert of the
    # next run counts it); no token reaches that step
    record = step(workflow, "read", "record")
    assert names.index("loop") < names.index("record") < names.index("push")
    assert record["if"] == (
        "always() && steps.pull.outcome == 'success' && steps.loop.outcome != 'skipped'"
        " && steps.reap.outputs.clear == 'true'"
    )
    assert set(record["env"]) == {"EXIT", "KILLED"}
    assert "live finish --record" in str(record["run"])
    assert "steps.loop.outcome != 'skipped'" in str(step(workflow, "read", "successor")["if"])
    finish = step(workflow, "read", "finish")
    assert finish["env"]["PUSHED"] == "${{ steps.push.outcome }}"
    assert finish["env"]["DIRECTORY"] == "${{ steps.directory.outcome }}"
    assert '--directory "$DIRECTORY" --push "$PUSHED"' in str(finish["run"])
    save = next(item for item in steps(workflow, "read") if "cache/save" in str(item.get("uses")))
    assert "steps.export.outcome == 'success'" in str(save["if"])
    counts = step(workflow, "read", "Count the restored caches")
    assert "::notice::live-read caches restored $total bytes" in str(counts["run"])


@needs_tools
def test_the_reader_job_notes_the_token_count(tmp_path: Path, stub: Stub) -> None:
    stub.answer("GET", RUNS, 200, {"workflow_runs": []})
    stub.answer("POST", DISPATCH, 204)
    stub.headers = {
        "X-RateLimit-Used": "212",
        "X-RateLimit-Limit": "1000",
        "X-RateLimit-Reset": "1793",
    }
    ran = _reader(tmp_path, stub)
    assert ran.code == 0
    assert "::notice::github token used 212 of 1000 reset 1793" in ran.out


def test_the_drills_never_turn_red_and_the_switch_holds_no_d1_secret() -> None:
    workflow = load("live-drill.yml")
    job = workflow["jobs"]["drill"]
    assert job["continue-on-error"] is True
    text = (WORKFLOWS / "live-drill.yml").read_text(encoding="utf-8")
    assert "CLOUDFLARE" not in text  # no step can reach the D1 state
    switch = step(workflow, "drill", "switch")
    assert switch["if"] == "env.DRILL == 'switch'"
    assert "uv run snowlight live rehearse" in str(switch["run"])
    # no live host token either: the rehearsal writes a folder on the runner only
    assert set(switch["env"]) == {"GITHUB_TOKEN", "PYTHONWARNINGS"}
    assert "SNOWLIGHT_LIVE_TOKEN" not in text
    assert "environment" not in job
    for item in steps(workflow, "drill"):
        run = str(item.get("run", ""))
        # the guard reads v1's hold; nothing else names v1/
        if item.get("id") != "guard":
            assert "v1/" not in run.replace("v1-shadow/", "").replace("v1-rehearse/", "")


def _gate(tmp_path: Path, stub: Stub, committed: datetime, served: str) -> Ran:
    """The gate drill's step against a stub API and CDN, with sleep a no-op."""
    script = str(
        step(load("live-drill.yml"), "drill", "Block the gate with live-blank, then release it")[
            "run"
        ]
    )
    shim = tmp_path / "bin"
    shim.mkdir()
    (shim / "sleep").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (shim / "sleep").chmod(0o755)
    blank = {
        "sha": "b" * 40,
        "commit": {
            "message": "live-blank v1-shadow blank 2026-10-31T12:00:05Z",
            "committer": {"date": committed.strftime("%Y-%m-%dT%H:%M:%SZ")},
        },
    }
    reader = {
        "sha": "c" * 40,
        "commit": {
            "message": "live v1-shadow pass x",
            "committer": {"date": "2026-10-31T12:00:00Z"},
        },
    }
    stub.answer(
        "POST", "/api/repos/viaate/synthetic/actions/workflows/live-blank.yml/dispatches", 204
    )
    stub.answer("GET", "/api/repos/viaate/snowlight-live/commits", 200, [blank, reader])
    stub.answer(
        "GET",
        "/api/repos/viaate/snowlight-live/contents/v1-shadow/live/closings.json",
        200,
        {"generated_at": "2026-10-31T12:00:05Z", "days": []},
    )
    stub.answer(
        "GET", "/cdn/v1-shadow/live/closings.json", 200, {"generated_at": served, "days": []}
    )
    env = {
        "PATH": f"{shim}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "LIVE_ROOT": f"{stub.url}/cdn/",
        "LIVE_REPOSITORY": "viaate/snowlight-live",
        "SHADOW_PREFIX": "v1-shadow",
    }
    return run_script(script, tmp_path, stub, env)


@needs_tools
def test_the_gate_drill_waits_for_the_blanks_own_stamp(tmp_path: Path, stub: Stub) -> None:
    # an ordinary empty upload (days [] under another stamp) is never taken for the blank
    ran = _gate(tmp_path, stub, datetime.now(UTC), "2026-10-31T12:04:40Z")
    assert ran.code == 0, ran.out
    assert "::warning::drill gate: the blank (generated_at 2026-10-31T12:00:05Z" in ran.out
    assert "was not served within 8 minutes" in ran.out


@needs_tools
@pytest.mark.parametrize(("ago", "verdict"), [(10, "within"), (300, "over")])
def test_the_gate_drill_logs_the_blanks_commit_served_and_delay(
    tmp_path: Path, stub: Stub, ago: int, verdict: str
) -> None:
    committed = datetime.now(UTC) - timedelta(seconds=ago)
    ran = _gate(tmp_path, stub, committed, "2026-10-31T12:00:05Z")
    assert ran.code == 0, ran.out
    level = "notice" if verdict == "within" else "warning"
    assert (
        f"::{level}::drill gate: the blank (generated_at 2026-10-31T12:00:05Z) committed at"
        in ran.out
    )
    assert f"{verdict} the 60-s bar" in ran.out
    assert "::notice::live-drill gate release " in ran.out
    assert "::notice::live-drill gate blank " in ran.out


@needs_tools
def test_the_stall_drill_enables_75_s_before_a_timer_tick_and_logs_the_restart(
    tmp_path: Path, stub: Stub
) -> None:
    script = str(step(load("live-drill.yml"), "drill", "Stall the reader for 35 minutes")["run"])
    shim = tmp_path / "bin"
    shim.mkdir()
    slept = tmp_path / "slept"
    (shim / "sleep").write_text(f'#!/bin/sh\necho "$1" >> {slept}\nexit 0\n', encoding="utf-8")
    (shim / "sleep").chmod(0o755)
    later = (datetime.now(UTC) + timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    actions = "/api/repos/viaate/synthetic/actions"
    stub.answer(
        "GET",
        f"{actions}/workflows/live-read.yml/runs",
        200,
        {"workflow_runs": [{"id": 7, "status": "in_progress", "run_started_at": later}]},
    )
    stub.answer("PUT", f"{actions}/workflows/live-read.yml/disable", 204)
    stub.answer("PUT", f"{actions}/workflows/live-read.yml/enable", 204)
    stub.answer("POST", f"{actions}/runs/7/cancel", 202)
    before = int(datetime.now(UTC).timestamp())
    env = {"PATH": f"{shim}:{os.environ.get('PATH', '/usr/bin:/bin')}"}
    ran = run_script(script, tmp_path, stub, env)
    assert ran.code == 0, ran.out
    waits = [int(line) for line in slept.read_text(encoding="utf-8").split()]
    assert waits[0] == 2100
    # the enable lands 75 s before :x0:40 or :x5:40 (265 s into a 5-minute window)
    assert (before + waits[1]) % 300 in {264, 265, 266}
    assert 0 <= waits[1] < 300
    assert "::notice::live-drill stall disabled " in ran.out
    assert "::notice::live-drill stall enabled " in ran.out
    assert f"::notice::live-drill stall reader started {later}" in ran.out
    assert [path for path, _ in stub.calls("POST")] == [f"{actions}/runs/7/cancel"]


@needs_tools
def test_the_drill_landing_value_none_runs_no_drill(tmp_path: Path, stub: Stub) -> None:
    script = str(step(load("live-drill.yml"), "drill", "guard")["run"])
    ran = run_script(script, tmp_path, stub, {"DRILL": "none", "LIVE_PUBLISH": "on"})
    assert ran.code == 0
    assert "::notice::live-drill none: no drill runs" in ran.out
    assert not stub.seen
    ran = run_script(script, tmp_path, stub, {"DRILL": "fire"})
    assert ran.code == 1
