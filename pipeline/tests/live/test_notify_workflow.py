"""Contract tests for live-ingest.yml's notify job (docs/notify.md): it runs after the publish
job on every run whose check finished, holds no live host token, and its first step counts
the browsers that get notifications, so that with none, no Cloudflare secrets or the tables
not there yet the job says one line and sets nothing up.

The count step's script runs here against a SYNTHETIC stub of the Cloudflare API on a
loopback port (it needs bash, curl and jq, as the runner has).
"""

import json
import os
import shutil
import sqlite3
import subprocess
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped, unused-ignore]

REPO_ROOT = Path(__file__).resolve().parents[3]
LIVE = REPO_ROOT / ".github" / "workflows" / "live-ingest.yml"
PREDICT = REPO_ROOT / ".github" / "workflows" / "predict.yml"
TOOLS = all(shutil.which(tool) for tool in ("bash", "curl", "jq"))
needs_tools = pytest.mark.skipif(not TOOLS, reason="needs bash, curl and jq")
DB = "11111111-2222-3333-4444-555555555555"
LIST = "/cf/accounts/acct/d1/database?name=snowlight-accounts"
QUERY = f"/cf/accounts/acct/d1/database/{DB}/query"
FOUND = (200, json.dumps({"success": True, "result": [{"uuid": DB, "name": "snowlight-accounts"}]}))


def notify_job() -> dict[str, object]:
    found = yaml.safe_load(LIVE.read_text(encoding="utf-8"))["jobs"]["notify"]
    assert isinstance(found, dict)
    return found


def test_runs_after_publish_without_the_live_host_token() -> None:
    job = notify_job()
    assert job["needs"] == ["check", "publish"]
    assert job["if"] == "always() && needs.check.result == 'success'"
    assert job["continue-on-error"] is True, "a notification problem never fails the run"
    assert "environment" not in job
    assert job["permissions"] == {"contents": "read", "actions": "read", "deployments": "read"}
    assert "SNOWLIGHT_LIVE_TOKEN" not in json.dumps(job)
    env = job["env"]
    assert isinstance(env, dict)
    token = "${{ secrets.CLOUDFLARE_API_TOKEN }}"  # noqa: S105 - the secret's name
    assert env["CLOUDFLARE_API_TOKEN"] == token
    assert env["CLOUDFLARE_ACCOUNT_ID"] == "${{ secrets.CLOUDFLARE_ACCOUNT_ID }}"
    steps = job["steps"]
    assert isinstance(steps, list)
    assert steps[0]["id"] == "count"
    for step in steps[1:]:
        assert step["if"] == "steps.count.outputs.send == 'true'"
    assert steps[-1]["run"] == "uv run snowlight notify status"


def test_the_predictions_loop_gets_the_cloudflare_secrets() -> None:
    job = yaml.safe_load(PREDICT.read_text(encoding="utf-8"))["jobs"]["predict"]
    token = "${{ secrets.CLOUDFLARE_API_TOKEN }}"  # noqa: S105 - the secret's name
    # Only the step that runs the loop: never the job, whose other steps run third-party
    # actions and fetches.
    assert "CLOUDFLARE_API_TOKEN" not in json.dumps(job.get("env", {}))
    holders = [step for step in job["steps"] if "CLOUDFLARE_API_TOKEN" in json.dumps(step)]
    assert [step.get("id") for step in holders] == ["run"]
    [step] = holders
    assert step["run"].startswith("uv run snowlight predict run")
    assert step["env"]["CLOUDFLARE_API_TOKEN"] == token
    assert step["env"]["CLOUDFLARE_ACCOUNT_ID"] == "${{ secrets.CLOUDFLARE_ACCOUNT_ID }}"


@dataclass
class Cloudflare:
    answers: dict[str, tuple[int, str]] = field(default_factory=dict)
    posted: list[str] = field(default_factory=list)
    url: str = ""


@pytest.fixture
def cloudflare() -> Iterator[Cloudflare]:
    stub = Cloudflare()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002, ARG002
            return

        def answer(self) -> None:
            assert self.headers.get("authorization") == "Bearer cf-token"
            code, body = stub.answers.get(self.path, (404, '{"success": false}'))
            data = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            self.answer()

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            stub.posted.append(self.rfile.read(length).decode())
            self.answer()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    stub.url = f"http://127.0.0.1:{httpd.server_address[1]}"
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield stub
    httpd.shutdown()
    httpd.server_close()


def run_count(tmp_path: Path, stub: Cloudflare, secrets: bool = True) -> tuple[int, str, str]:
    steps = notify_job()["steps"]
    assert isinstance(steps, list)
    outputs = tmp_path / "outputs"
    outputs.write_text("", encoding="utf-8")
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "NO_PROXY": "*",
        "GITHUB_OUTPUT": str(outputs),
        "CLOUDFLARE_API_URL": f"{stub.url}/cf",
        "CLOUDFLARE_API_TOKEN": "cf-token" if secrets else "",
        "CLOUDFLARE_ACCOUNT_ID": "acct" if secrets else "",
    }
    done = subprocess.run(  # noqa: S603 - the workflow's own script, in a temporary folder
        ["bash", "-e", "-c", str(steps[0]["run"])],  # noqa: S607 - bash from PATH
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return done.returncode, done.stdout + done.stderr, outputs.read_text(encoding="utf-8")


def count(n: int) -> tuple[int, str]:
    return 200, json.dumps({"success": True, "result": [{"results": [{"n": n}]}]})


@needs_tools
def test_no_secrets_one_line(tmp_path: Path, cloudflare: Cloudflare) -> None:
    _code, out, outputs = run_count(tmp_path, cloudflare, secrets=False)
    assert out == "notify: no Cloudflare secrets: nothing to send\n"
    assert outputs == "send=false\n"


@needs_tools
def test_zero_browsers_one_line_and_nothing_set_up(tmp_path: Path, cloudflare: Cloudflare) -> None:
    cloudflare.answers = {LIST: FOUND, QUERY: count(0)}
    _code, out, outputs = run_count(tmp_path, cloudflare)
    assert out == "notify: no browser gets notifications: nothing to send\n"
    assert outputs == "send=false\n"
    [body] = cloudflare.posted
    sql = json.loads(body)["sql"]
    assert sql.startswith("SELECT COUNT(*) AS n FROM push_subscriptions")
    # The same count as the sender's: on the API's own tables, only browsers of accounts
    # that are not disabled whose sign-in lasts.
    db = sqlite3.connect(":memory:")
    for path in sorted((REPO_ROOT / "api" / "migrations").glob("*.sql")):
        db.executescript(path.read_text(encoding="utf-8"))
    for user, disabled, until in (("u1", 0, 10**15), ("u2", 0, 1), ("u3", 1, 10**15)):
        db.execute(
            "INSERT INTO users (id, login, email, name, role, schools, disabled, created_at)"
            " VALUES (?, ?, ?, 'Pat Lee', 'user', '[]', ?, 1)",
            (user, f"{user}@example.com", f"{user}@example.com", disabled),
        )
        db.execute("INSERT INTO sessions VALUES (?, ?, 1, ?, 1)", (f"s-{user}", user, until))
        db.execute(
            "INSERT INTO push_subscriptions (endpoint, user_id, session_hash, p256dh, auth,"
            " created_at) VALUES (?, ?, ?, 'p', 'a', 1)",
            (f"https://fcm.googleapis.com/{user}", user, f"s-{user}"),
        )
    assert db.execute(sql).fetchall() == [(1,)]


@needs_tools
@pytest.mark.parametrize(
    ("answers", "says"),
    [
        ({}, "the accounts database was not found (HTTP 404)"),
        ({LIST: (200, '{"success": true, "result": []}')}, "the accounts database was not found"),
        (
            {
                LIST: FOUND,
                QUERY: (
                    400,
                    json.dumps({"success": False, "errors": [{"message": "no such table: x"}]}),
                ),
            },
            "the notification tables cannot be read yet (HTTP 400",
        ),
    ],
)
def test_dark_until_the_database_and_tables_are_there(
    tmp_path: Path, cloudflare: Cloudflare, answers: dict[str, tuple[int, str]], says: str
) -> None:
    cloudflare.answers = answers
    _code, out, outputs = run_count(tmp_path, cloudflare)
    assert says in out
    assert out.count("\n") == 1
    assert outputs == "send=false\n"


@needs_tools
def test_browsers_to_send_to(tmp_path: Path, cloudflare: Cloudflare) -> None:
    cloudflare.answers = {LIST: FOUND, QUERY: count(3)}
    _code, out, outputs = run_count(tmp_path, cloudflare)
    assert out == "notify: 3 browsers get notifications\n"
    assert outputs == "send=true\n"
