"""Contract tests for .github/workflows/social-post.yml: nothing a stranger can start reaches
the secrets, the secrets reach only the post step, actions are pinned by full SHA, and the
log check is the same rule as :mod:`snowlight.social.logscan`."""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped, unused-ignore]

from snowlight.social import logscan

REPO = Path(__file__).resolve().parents[3]
PATH = REPO / ".github" / "workflows" / "social-post.yml"
BRANCH = "claude/keen-faraday-oy7yqw"
ALLOWED = {"actions/checkout", "astral-sh/setup-uv", "actions/setup-python"}
SECRET = re.compile(r"secrets\.([A-Z_]+)")


@pytest.fixture(scope="module")
def workflow() -> dict[Any, Any]:
    loaded = yaml.safe_load(PATH.read_text())
    assert isinstance(loaded, dict)
    return loaded


def test_only_the_schedule_and_pushes_to_the_default_branch_start_it(
    workflow: dict[Any, Any],
) -> None:
    triggers = workflow[True]  # YAML 1.1 reads the key "on" as true
    assert set(triggers) == {"schedule", "push"}
    assert triggers["schedule"] == [{"cron": "37 16 * * *"}, {"cron": "41 20 * * *"}]
    assert triggers["push"] == {
        "branches": [BRANCH],
        "paths": ["social/queue/**", ".github/workflows/social-post.yml"],
    }
    text = PATH.read_text()
    for word in (
        "pull_request",
        "pull_request_target",
        "workflow_dispatch",
        "workflow_run",
        "issue_comment",
    ):
        assert not re.search(rf"^\s*{word}:", text, re.MULTILINE), word


def test_the_post_job_is_guarded_and_alone(workflow: dict[Any, Any]) -> None:
    assert workflow["permissions"] == {}
    job = workflow["jobs"]["post"]
    assert job["environment"] == "x-posting"
    assert job["concurrency"] == {"group": "social-post", "cancel-in-progress": False}
    assert job["permissions"] == {"contents": "read", "actions": "read", "issues": "write"}
    assert job["needs"] == "render"
    for name in ("post", "render"):
        guarded = workflow["jobs"][name]
        assert f"github.ref == 'refs/heads/{BRANCH}'" in guarded["if"]
        first = guarded["steps"][0]
        assert f'"$REF" != "refs/heads/{BRANCH}"' in first["run"]
        assert "exit 1" in first["run"]


def test_secrets_reach_only_the_post_step(workflow: dict[Any, Any]) -> None:
    job = workflow["jobs"]["post"]
    assert "secrets." not in yaml.safe_dump(job.get("env", {}))
    holders = [step for step in job["steps"] if SECRET.search(yaml.safe_dump(step))]
    assert [step.get("name") for step in holders] == ["Post"]
    assert set(SECRET.findall(yaml.safe_dump(holders[0]))) == {
        "X_CLIENT_ID",
        "X_CLIENT_SECRET",
        "X_REFRESH_TOKEN",
        "ANTHROPIC_API_KEY",
        "CLOUDFLARE_API_TOKEN",
        "CLOUDFLARE_ACCOUNT_ID",
    }
    check = workflow["jobs"]["log-check"]
    assert "environment" not in check
    assert check["permissions"] == {"actions": "read"}
    assert "secrets." not in yaml.safe_dump(check)


def test_actions_are_the_allowed_ones_pinned_by_full_sha(workflow: dict[Any, Any]) -> None:
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            if "uses" not in step:
                continue
            name, _, ref = step["uses"].partition("@")
            assert name in ALLOWED, name
            assert re.fullmatch(r"[0-9a-f]{40}", ref), step["uses"]
            assert step.get("with", {}).get("persist-credentials", False) is False
    text = PATH.read_text()
    assert "enable-cache: false" in text
    for word in ("upload-artifact", "actions/cache", "GITHUB_STEP_SUMMARY", "set-output", "tee "):
        assert word not in text, word


def test_the_log_check_is_logscan(workflow: dict[Any, Any]) -> None:
    script = workflow["jobs"]["log-check"]["steps"][0]["run"]
    assert 'run = re.compile(r"[A-Za-z0-9_\\-~+=.]{30,}")' in script
    assert logscan.RUN.pattern == r"[A-Za-z0-9_\-~+=.]{30,}"
    assert str(logscan.PREFIXES).replace("'", '"') in script
    assert "> /dev/null" in script
    assert '.jobs[] | select(.name == "post")' in script


def test_the_browser_runs_in_its_own_job_with_no_secret_and_no_environment(
    workflow: dict[Any, Any],
) -> None:
    render = workflow["jobs"]["render"]
    assert "environment" not in render
    assert render["permissions"] == {"contents": "read"}
    assert "secrets." not in yaml.safe_dump(render)
    assert "github.token" not in yaml.safe_dump(render)
    assert render["outputs"] == {"digest": "${{ steps.relay.outputs.digest }}"}
    steps = render["steps"]
    names = [step.get("name") for step in steps]
    assert names.index("Install the picture's browser") < names.index("Render")
    assert names.index("Render") < names.index("Hand the cards to the post job")
    sync = next(step for step in steps if step.get("run", "").startswith("uv sync"))
    assert sync["run"] == "uv sync --locked --no-dev --group render"
    for name in ("Install the picture's browser", "Render", "Hand the cards to the post job"):
        step = steps[names.index(name)]
        assert step["continue-on-error"] is True, "a failed render falls back, it never stops"
        assert "env" not in step
    browser = steps[names.index("Install the picture's browser")]
    assert "playwright install --with-deps --only-shell chromium" in browser["run"]
    render_step = steps[names.index("Render")]
    assert render_step["run"] == (
        'uv run --no-sync snowlight social render --out "$RUNNER_TEMP/picture"'
    )
    # The post job installs no browser and never runs one: it takes the cards from the log.
    post = workflow["jobs"]["post"]
    text = yaml.safe_dump(post)
    assert "playwright" not in text
    assert "social render" not in text
    post_steps = post["steps"]
    sync = next(step for step in post_steps if step.get("run", "").startswith("uv sync"))
    assert sync["run"] == "uv sync --locked --no-dev"
    names = [step.get("name") for step in post_steps]
    take = post_steps[names.index("Take the cards")]
    assert take["continue-on-error"] is True
    assert "relay-in" in take["run"]
    assert '.jobs[] | select(.name == "render")' in take["run"]
    assert "secrets." not in yaml.safe_dump(take)
    assert names.index("Take the cards") < names.index("Post")
    assert post_steps[names.index("Post")]["timeout-minutes"] == 10
    assert post_steps[names.index("Post")]["run"].endswith('--picture "$RUNNER_TEMP/picture"')
    assert post["if"].startswith("${{ !cancelled()")


def test_uv_is_pinned_to_one_version(workflow: dict[Any, Any]) -> None:
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            if step.get("uses", "").startswith("astral-sh/setup-uv@"):
                assert re.fullmatch(r"\d+\.\d+\.\d+", step["with"]["version"])


def test_the_log_check_also_fails_on_a_command_that_stops_masking(
    workflow: dict[Any, Any],
) -> None:
    script = workflow["jobs"]["log-check"]["steps"][0]["run"]
    assert '"::stop-commands::" in line' in script
