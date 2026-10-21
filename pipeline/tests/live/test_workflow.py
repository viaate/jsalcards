"""Contract tests for .github/workflows/live-ingest.yml (accounts spec C): it fails dark and
quietly, and publishes only through ``snowlight live overrides`` with the live host token.

The check job's script runs here against SYNTHETIC stubs of the API, the Cloudflare API and
GitHub's contents API on a loopback port (it needs bash, curl and jq, as the runner has).
"""

import json
import os
import shutil
import subprocess
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped, unused-ignore]

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "live-ingest.yml"
TOOLS = all(shutil.which(tool) for tool in ("bash", "curl", "jq"))


def load() -> dict[object, object]:
    found = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(found, dict)
    return found


def jobs() -> dict[str, dict[str, object]]:
    found = load()["jobs"]
    assert isinstance(found, dict)
    return found


def test_dispatched_only_one_run_at_a_time_on_the_default_branch() -> None:
    workflow = load()
    assert workflow[True] == {"workflow_dispatch": None}  # YAML reads "on" as true
    assert workflow["concurrency"] == {"group": "live-ingest", "cancel-in-progress": False}
    assert workflow["permissions"] == {"contents": "read"}
    check = jobs()["check"]
    assert "environment" not in check  # a quiet run makes no deployment of `live`
    assert check["if"] == (
        "github.ref == format('refs/heads/{0}', github.event.repository.default_branch)"
    )


def test_only_the_publish_job_holds_the_live_host_token() -> None:
    publish = jobs()["publish"]
    assert publish["environment"] == "live"
    assert publish["needs"] == "check"
    assert publish["if"] == "needs.check.outputs.publish == 'true'"
    env = publish["env"]
    assert isinstance(env, dict)
    secret = "${{ secrets.SNOWLIGHT_LIVE_TOKEN }}"  # noqa: S105 - the secret's name, not a value
    assert env["LIVE_HOST_TOKEN"] == secret
    assert "SNOWLIGHT_LIVE_TOKEN" not in json.dumps(jobs()["check"])
    steps = publish["steps"]
    assert isinstance(steps, list)
    first = steps[0]
    assert first["id"] == "token"
    assert "::notice::" in str(first["run"])
    runs = "\n".join(str(step.get("run", "")) for step in steps)
    assert 'uv run snowlight live overrides --api "$API_ROOT"' in runs
    assert "uv run snowlight live overrides --none" in runs  # the take-down, with no API left
    for step in steps[1:]:
        assert "steps.token.outputs.ready == 'true'" in str(step["if"])
    assert all("upload-artifact" not in str(step.get("uses", "")) for step in steps)


# --- the check job's script ------------------------------------------------------------------


@dataclass
class Stubs:
    """SYNTHETIC answers by path: the API, the Cloudflare API and GitHub's contents API."""

    answers: dict[str, tuple[int, bytes]] = field(default_factory=dict)
    first: dict[str, list[tuple[int, bytes]]] = field(default_factory=dict)
    """Answers given before ``answers``, one per GET, in order."""
    url: str = ""
    seen: list[str] = field(default_factory=list)


@pytest.fixture
def stubs() -> Iterator[Stubs]:
    stub = Stubs()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002, ARG002
            return

        def do_GET(self) -> None:
            stub.seen.append(f"{self.path} {self.headers.get('authorization', '')}")
            queued = stub.first.get(self.path)
            if queued:
                code, data = queued.pop(0)
            else:
                code, data = stub.answers.get(self.path, (404, b'{"message": "Not Found"}'))
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    stub.url = f"http://127.0.0.1:{httpd.server_address[1]}"
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield stub
    httpd.shutdown()
    httpd.server_close()


@dataclass(frozen=True)
class Ran:
    code: int
    out: str
    outputs: dict[str, str]


def run_check(tmp_path: Path, env: dict[str, str], stubs: Stubs) -> Ran:
    steps = jobs()["check"]["steps"]
    assert isinstance(steps, list)
    script = str(steps[0]["run"])
    outputs = tmp_path / "outputs"
    outputs.write_text("", encoding="utf-8")
    base = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "NO_PROXY": "*",
        "GITHUB_OUTPUT": str(outputs),
        "GITHUB_API_URL": f"{stubs.url}/github",
        "CLOUDFLARE_API_URL": f"{stubs.url}/cloudflare",
        "API_ROOT": "",
        "CLOUDFLARE_API_TOKEN": "",
        "CLOUDFLARE_ACCOUNT_ID": "",
        "GH_TOKEN": "synthetic-github-token",
        "LIVE_REPOSITORY": "viaate/snowlight-synthetic",
        "LIVE_PUBLISH": "on",
        "RETRY_PAUSE": "0",
    }
    done = subprocess.run(  # noqa: S603 - the workflow's own script, in a temporary folder
        ["bash", "-e", "-c", script],  # noqa: S607 - bash from PATH, as on the runner
        cwd=tmp_path,
        env={**base, **env},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    found: dict[str, str] = {}
    for line in outputs.read_text(encoding="utf-8").splitlines():
        name, _, value = line.partition("=")
        found[name] = value
    return Ran(done.returncode, done.stdout + done.stderr, found)


needs_tools = pytest.mark.skipif(not TOOLS, reason="needs bash, curl and jq")
PUBLIC = "/github/repos/viaate/snowlight-synthetic/contents/v1/live"
CLOSINGS = f"{PUBLIC}/closings.json"
OPENS = f"{PUBLIC}/opens.json"
SUBDOMAIN = "/cloudflare/accounts/acct/workers/subdomain"
SCRIPTS = "/cloudflare/accounts/acct/workers/scripts"
DEPLOYED = (200, b'{"success": true, "result": [{"id": "other"}, {"id": "snowlight-api"}]}')
HAS_SUBDOMAIN = (200, b'{"success": true, "result": {"subdomain": "synthetic"}}')
CLOUDFLARE = {"CLOUDFLARE_API_TOKEN": "cf-token", "CLOUDFLARE_ACCOUNT_ID": "acct"}
NOTHING_THERE = "http://127.0.0.1:9"  # the discard port: refused
ONE = json.dumps({"overrides": [{"scope": "district", "id": "2900001"}]}).encode()
NONE = b'{"overrides": []}'
SHOWN = b'{"days": [{"day": "2026-11-17"}]}'


def one_line(ran: Ran, kind: str) -> None:
    """Quiet: exactly one line, of that kind."""
    assert ran.out.count(kind) == 1
    assert ran.out.strip().count("\n") == 0, ran.out


@needs_tools
@pytest.mark.parametrize(
    "env",
    [{}, {"CLOUDFLARE_API_TOKEN": "synthetic"}, {"CLOUDFLARE_ACCOUNT_ID": "synthetic"}],
)
def test_without_an_api_root_one_notice_and_success(
    tmp_path: Path, stubs: Stubs, env: dict[str, str]
) -> None:
    ran = run_check(tmp_path, env, stubs)
    assert ran.code == 0
    one_line(ran, "::notice::")
    assert ran.outputs == {"publish": "false"}
    # Only the public files were read (both missing here).
    assert [seen.split()[0] for seen in stubs.seen] == [CLOSINGS, OPENS]


@needs_tools
@pytest.mark.parametrize(
    ("closings", "opens"),
    [((200, SHOWN), None), ((200, b'{"days": []}'), (200, b'{"opens": [{"school": 1}]}'))],
)
def test_without_an_api_statuses_left_on_the_map_are_taken_down(
    tmp_path: Path, stubs: Stubs, closings: tuple[int, bytes], opens: tuple[int, bytes] | None
) -> None:
    stubs.answers[CLOSINGS] = closings
    if opens is not None:
        stubs.answers[OPENS] = opens
    ran = run_check(tmp_path, {}, stubs)
    assert ran.code == 0
    one_line(ran, "::warning::")
    assert "taking them down" in ran.out
    assert ran.outputs == {"publish": "true"}  # no api: the publish job runs --none


@needs_tools
@pytest.mark.parametrize("public", [(200, b"not json"), (502, b"{}"), (200, b'{"days": 1}')])
def test_without_an_api_an_unreadable_public_file_is_never_taken_down_on_a_guess(
    tmp_path: Path, stubs: Stubs, public: tuple[int, bytes]
) -> None:
    stubs.answers[CLOSINGS] = public
    ran = run_check(tmp_path, {}, stubs)
    assert ran.code == 0
    one_line(ran, "::notice::")
    assert ran.outputs == {"publish": "false"}


@needs_tools
def test_the_root_is_found_from_the_cloudflare_account(tmp_path: Path, stubs: Stubs) -> None:
    stubs.answers[SUBDOMAIN] = HAS_SUBDOMAIN
    stubs.answers[SCRIPTS] = DEPLOYED
    closed = {"NO_PROXY": "127.0.0.1", "HTTPS_PROXY": NOTHING_THERE}
    ran = run_check(tmp_path, {**CLOUDFLARE, **closed}, stubs)
    assert f"{SUBDOMAIN} Bearer cf-token" in stubs.seen
    assert f"{SCRIPTS} Bearer cf-token" in stubs.seen
    # The Worker's address is out of this test's reach (a closed proxy): one clear error.
    assert ran.code == 1
    one_line(ran, "::error::")
    assert "https://snowlight-api.synthetic.workers.dev/" in ran.out
    assert "curl" not in ran.out
    assert ran.outputs == {"publish": "false"}


@needs_tools
@pytest.mark.parametrize(
    "answer",
    [
        (403, b'{"success": false, "errors": [{"code": 10000}]}'),
        (404, b'{"success": false, "errors": [{"code": 10007}]}'),
        (200, b"not json"),
        (200, b'{"success": false}'),
        (200, b'{"success": true, "result": {"subdomain": "a b/c"}}'),
        None,  # no answer at all
    ],
)
def test_a_failed_cloudflare_lookup_is_one_notice_and_success(
    tmp_path: Path, stubs: Stubs, answer: tuple[int, bytes] | None
) -> None:
    env = dict(CLOUDFLARE)
    if answer is None:
        env["CLOUDFLARE_API_URL"] = NOTHING_THERE
    else:
        stubs.answers[SUBDOMAIN] = answer
    ran = run_check(tmp_path, env, stubs)
    assert ran.code == 0
    one_line(ran, "::notice::")
    assert "curl" not in ran.out
    assert ran.outputs == {"publish": "false"}


@needs_tools
def test_an_account_without_a_subdomain_has_no_api(tmp_path: Path, stubs: Stubs) -> None:
    stubs.answers[SUBDOMAIN] = (200, b'{"success": true, "result": {"subdomain": null}}')
    stubs.answers[CLOSINGS] = (200, SHOWN)
    ran = run_check(tmp_path, CLOUDFLARE, stubs)
    assert ran.code == 0
    one_line(ran, "::warning::")
    assert ran.outputs == {"publish": "true"}


@needs_tools
@pytest.mark.parametrize(("public", "publish"), [(None, "false"), ((200, SHOWN), "true")])
def test_an_api_not_deployed_is_one_line_and_success(
    tmp_path: Path, stubs: Stubs, public: tuple[int, bytes] | None, publish: str
) -> None:
    if public is not None:
        stubs.answers[CLOSINGS] = public
    ran = run_check(tmp_path, {"API_ROOT": f"{stubs.url}/api"}, stubs)
    assert ran.code == 0
    one_line(ran, "::notice::" if publish == "false" else "::warning::")
    assert ran.outputs == {"publish": publish}  # no api: a take-down runs --none


@needs_tools
def test_an_api_that_does_not_answer_is_one_error(tmp_path: Path, stubs: Stubs) -> None:
    ran = run_check(tmp_path, {"API_ROOT": NOTHING_THERE}, stubs)
    assert ran.code == 1
    one_line(ran, "::error::")
    assert "curl" not in ran.out
    assert ran.outputs == {"publish": "false"}


@needs_tools
def test_no_override_and_no_public_file_stops_quietly(tmp_path: Path, stubs: Stubs) -> None:
    stubs.answers["/api/v1/overrides"] = (200, NONE)
    ran = run_check(tmp_path, {"API_ROOT": f"{stubs.url}/api/"}, stubs)
    assert ran.code == 0
    assert "::" not in ran.out
    assert "nothing to publish" in ran.out
    assert ran.out.strip().count("\n") == 0
    assert ran.outputs == {"publish": "false", "api": f"{stubs.url}/api/"}
    assert f"{CLOSINGS} Bearer synthetic-github-token" in stubs.seen


Answer = tuple[int, bytes] | None


@needs_tools
@pytest.mark.parametrize(
    ("overrides", "public", "publish"),
    [
        (ONE, (None, None), "true"),
        (NONE, ((200, b'{"days": []}'), None), "false"),
        (NONE, ((200, b'{"days": []}'), (200, b'{"opens": []}')), "false"),
        (NONE, ((200, SHOWN), None), "true"),
        (NONE, ((200, b'{"days": []}'), (200, b'{"opens": [{"school": 1}]}')), "true"),
        (NONE, ((200, b"not json"), None), "true"),
        (NONE, ((502, b"{}"), None), "true"),
        (NONE, (None, (502, b"{}")), "true"),
    ],
)
def test_the_publish_job_runs_when_there_is_something_to_publish_or_take_down(
    tmp_path: Path, stubs: Stubs, overrides: bytes, public: tuple[Answer, Answer], publish: str
) -> None:
    stubs.answers["/api/v1/overrides"] = (200, overrides)
    for path, answer in zip((CLOSINGS, OPENS), public, strict=True):
        if answer is not None:
            stubs.answers[path] = answer
    ran = run_check(tmp_path, {"API_ROOT": f"{stubs.url}/api/"}, stubs)
    assert ran.code == 0
    assert ran.outputs == {"publish": publish, "api": f"{stubs.url}/api/"}


@needs_tools
@pytest.mark.parametrize(
    "answer", [(500, b"{}"), (200, b"not json"), (200, b'{"overrides": {}}'), (200, b"[]")]
)
def test_a_bad_api_answer_fails_and_publishes_nothing(
    tmp_path: Path, stubs: Stubs, answer: tuple[int, bytes]
) -> None:
    stubs.answers["/api/v1/overrides"] = answer
    ran = run_check(tmp_path, {"API_ROOT": f"{stubs.url}/api/"}, stubs)
    assert ran.code == 1
    one_line(ran, "::error::")
    assert ran.outputs == {"publish": "false"}


# --- critic round 2: the Worker's presence, a bad root, one bad answer, the publish mode -----


@needs_tools
@pytest.mark.parametrize(("public", "publish"), [(None, "false"), ((200, SHOWN), "true")])
def test_a_worker_the_account_does_not_list_is_no_api(
    tmp_path: Path, stubs: Stubs, public: tuple[int, bytes] | None, publish: str
) -> None:
    stubs.answers[SUBDOMAIN] = HAS_SUBDOMAIN
    stubs.answers[SCRIPTS] = (200, b'{"success": true, "result": [{"id": "other"}]}')
    if public is not None:
        stubs.answers[CLOSINGS] = public
    ran = run_check(tmp_path, CLOUDFLARE, stubs)
    assert ran.code == 0
    one_line(ran, "::notice::" if publish == "false" else "::warning::")
    assert "snowlight-api Worker is not deployed" in ran.out
    assert ran.outputs == {"publish": publish}
    # workers.dev is never asked: whatever it answers for a missing Worker does not matter
    assert not any("v1/overrides" in seen for seen in stubs.seen)


@needs_tools
@pytest.mark.parametrize(
    "answer",
    [
        (403, b'{"success": false, "errors": [{"code": 10000}]}'),
        (200, b'{"success": true, "result": {}}'),
        (200, b"not json"),
        (502, b"<html>bad gateway</html>"),
    ],
)
def test_a_failed_worker_listing_is_one_notice_and_success(
    tmp_path: Path, stubs: Stubs, answer: tuple[int, bytes]
) -> None:
    stubs.answers[SUBDOMAIN] = HAS_SUBDOMAIN
    stubs.answers[SCRIPTS] = answer
    stubs.answers[CLOSINGS] = (200, SHOWN)  # neither republished nor taken down on a guess
    ran = run_check(tmp_path, CLOUDFLARE, stubs)
    assert ran.code == 0
    one_line(ran, "::notice::")
    assert ran.outputs == {"publish": "false"}


@needs_tools
@pytest.mark.parametrize(
    "root",
    [
        "http://api.example.invalid/",
        "https://api.example.invalid/?key=1",
        "https://api.example.invalid/#v1",
        "https://api example.invalid/",
        "ftp://api.example.invalid/",
        "api.example.invalid",
    ],
)
@pytest.mark.parametrize(("public", "publish"), [(None, "false"), ((200, SHOWN), "true")])
def test_a_root_that_is_not_an_https_url_is_one_warning_and_success(
    tmp_path: Path, stubs: Stubs, root: str, public: tuple[int, bytes] | None, publish: str
) -> None:
    if public is not None:
        stubs.answers[CLOSINGS] = public
    ran = run_check(tmp_path, {"API_ROOT": root}, stubs)
    assert ran.code == 0
    one_line(ran, "::warning::")
    assert ran.outputs == {"publish": publish}
    assert not any("v1/overrides" in seen for seen in stubs.seen)


@needs_tools
@pytest.mark.parametrize("bad", [(404, b"{}"), (503, b"{}"), (500, b"{}")])
def test_one_bad_answer_is_asked_again(
    tmp_path: Path, stubs: Stubs, bad: tuple[int, bytes]
) -> None:
    stubs.first["/api/v1/overrides"] = [bad]
    stubs.answers["/api/v1/overrides"] = (200, ONE)
    stubs.answers[CLOSINGS] = (200, SHOWN)
    ran = run_check(tmp_path, {"API_ROOT": f"{stubs.url}/api/"}, stubs)
    assert ran.code == 0
    assert "::" not in ran.out
    assert ran.outputs == {"publish": "true", "api": f"{stubs.url}/api/"}
    assert sum("/api/v1/overrides" in seen for seen in stubs.seen) == 2


@needs_tools
def test_two_404s_in_a_row_take_the_map_down(tmp_path: Path, stubs: Stubs) -> None:
    stubs.answers[CLOSINGS] = (200, SHOWN)
    ran = run_check(tmp_path, {"API_ROOT": f"{stubs.url}/api/"}, stubs)
    assert ran.code == 0
    one_line(ran, "::warning::")
    assert "404 twice" in ran.out
    assert ran.outputs == {"publish": "true"}
    assert sum("/api/v1/overrides" in seen for seen in stubs.seen) == 2


@needs_tools
def test_two_server_errors_in_a_row_are_one_error(tmp_path: Path, stubs: Stubs) -> None:
    stubs.answers["/api/v1/overrides"] = (503, b"{}")
    ran = run_check(tmp_path, {"API_ROOT": f"{stubs.url}/api/"}, stubs)
    assert ran.code == 1
    one_line(ran, "::error::")
    assert sum("/api/v1/overrides" in seen for seen in stubs.seen) == 2


@needs_tools
@pytest.mark.parametrize("mode", ["off", "shadow"])
def test_a_mode_that_does_not_write_v1_warns_while_v1_shows_statuses(
    tmp_path: Path, stubs: Stubs, mode: str
) -> None:
    stubs.answers[CLOSINGS] = (200, SHOWN)
    ran = run_check(tmp_path, {"LIVE_PUBLISH": mode}, stubs)  # and no API root
    assert ran.code == 0
    assert ran.out.count("::warning::") == 1
    assert f"LIVE_OVERRIDES_PUBLISH is {mode}, but v1 still shows 1 manual statuses" in ran.out
    assert ran.out.count("::notice::") == 1  # no take-down: that mode cannot write v1
    assert ran.outputs == {"publish": "false"}
    # nothing on v1: quiet
    del stubs.answers[CLOSINGS]
    ran = run_check(tmp_path, {"LIVE_PUBLISH": mode}, stubs)
    one_line(ran, "::notice::")


def test_the_check_job_reads_the_publish_mode_the_publish_job_uses() -> None:
    check = jobs()["check"]["steps"]
    assert isinstance(check, list)
    publish = jobs()["publish"]["env"]
    assert isinstance(publish, dict)
    assert check[0]["env"]["LIVE_PUBLISH"] == publish["LIVE_PUBLISH"]


def test_the_publishers_state_cache_is_not_the_live_loops_store() -> None:
    from snowlight.live.state import CACHE_KEY_PREFIX  # noqa: PLC0415 - this test only

    steps = jobs()["publish"]["steps"]
    assert isinstance(steps, list)
    caches = [step for step in steps if "actions/cache" in str(step.get("uses", ""))]
    assert len(caches) == 2  # restore and save
    for step in caches:
        with_ = step["with"]
        assert with_["path"] == "pipeline/out/internal/live/state"
        assert not str(with_["key"]).startswith(CACHE_KEY_PREFIX)
        assert not str(with_.get("restore-keys", "-")).startswith(CACHE_KEY_PREFIX)
