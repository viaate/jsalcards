"""Contract tests for .github/workflows/predict.yml and the live root the preview names."""

from pathlib import Path

import yaml  # type: ignore[import-untyped, unused-ignore]

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "predict.yml"
PREVIEW = REPO_ROOT / ".github" / "workflows" / "preview.yml"
LIVE_ROOT = "https://viaate.github.io/snowlight-live/v1/"


def load() -> dict[object, object]:
    found = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(found, dict)
    return found


def job() -> dict[str, object]:
    jobs = load()["jobs"]
    assert isinstance(jobs, dict)
    found = jobs["predict"]
    assert isinstance(found, dict)
    return found


def steps() -> list[dict[str, object]]:
    found = job()["steps"]
    assert isinstance(found, list)
    return found


def test_one_chain_at_a_time_on_the_default_branch_in_the_live_environment() -> None:
    workflow = load()
    assert workflow["concurrency"] == {"group": "predict", "cancel-in-progress": False}
    triggers = workflow[True]  # YAML reads the key "on" as true
    assert isinstance(triggers, dict)
    assert triggers["schedule"] == [{"cron": "*/20 * * * *"}]
    assert "workflow_dispatch" in triggers
    found = job()
    assert found["environment"] == "live"
    # A scheduled run's payload names no repository: it is let through on its own (schedules
    # run on the default branch); a dispatch must name the default branch.
    condition = str(found["if"])
    assert "github.event_name == 'schedule'" in condition
    assert (
        "github.ref == format('refs/heads/{0}', github.event.repository.default_branch)"
        in condition
    )
    env = found["env"]
    assert isinstance(env, dict)
    secret = "${{ secrets.SNOWLIGHT_LIVE_TOKEN }}"  # noqa: S105 - the secret's name, not a value
    assert env["LIVE_HOST_TOKEN"] == secret


def test_without_the_token_nothing_runs_and_nothing_fails() -> None:
    first, *rest = steps()
    assert first["id"] == "token"
    script = str(first["run"])
    assert "::notice::" in script
    assert "exit 1" not in script
    for step in rest:
        assert "steps.token.outputs.ready == 'true'" in str(step.get("if", "")) or (
            "steps.check.outcome" in str(step.get("if", ""))
        )


def test_the_loop_runs_then_starts_its_successor_and_the_watchdog_checks() -> None:
    commands = [str(step.get("run", "")) for step in steps()]
    assert "uv run snowlight predict run --until +320m" in commands
    successor = next(
        step for step in steps() if "gh workflow run predict.yml" in str(step.get("run"))
    )
    # A cancelled run starts no successor: cancelling stops the chain.
    assert str(successor["if"]).startswith("(success() || failure())")
    assert "always()" not in str(successor["if"])
    assert "uv run snowlight predict check --max-age 45m" in commands
    permissions = load()["permissions"]
    assert isinstance(permissions, dict)
    assert permissions["actions"] == "write"
    assert permissions["contents"] == "read"


def test_the_preview_defaults_the_live_root_to_the_owners_pages_host() -> None:
    text = PREVIEW.read_text(encoding="utf-8")
    assert f"VITE_SNOWLIGHT_LIVE_ROOT: ${{{{ vars.SNOWLIGHT_LIVE_ROOT || '{LIVE_ROOT}' }}}}" in text


def test_the_watchdog_runs_after_a_failed_pass_and_keeps_one_issue_open() -> None:
    check = next(step for step in steps() if step.get("id") == "check")
    assert str(check["if"]).startswith("always()")
    issue = next(step for step in steps() if "gh issue create" in str(step.get("run")))
    assert issue["if"] == "always() && steps.check.outcome == 'failure'"
    script = str(issue["run"])
    assert script.index("gh issue list") < script.index("gh issue create")
    assert '[ "$open" = "0" ]' in script


def test_the_boundaries_cache_has_one_key_and_the_state_is_kept_apart() -> None:
    caches = [step for step in steps() if str(step.get("uses", "")).startswith("actions/cache")]
    keys = {str(step["with"]["key"]) for step in caches}  # type: ignore[index]
    assert "predict-boundaries-v1" in keys
    assert "predict-state-${{ github.run_id }}" in keys
    for step in caches:
        paths = str(step["with"]["path"])  # type: ignore[index]
        # Never the boundaries under a per-run key (that fills the repository's cache).
        assert not ("weather" in paths and "run_id" in str(step["with"]["key"]))  # type: ignore[index]
    saves = [step for step in caches if "save" in str(step["uses"])]
    boundary_save = next(step for step in saves if "weather" in str(step["with"]["path"]))  # type: ignore[index]
    assert "cache-hit != 'true'" in str(boundary_save["if"])


def test_the_model_learns_before_the_passes_and_a_failed_step_never_stops_them() -> None:
    found = steps()
    ids = [step.get("id") for step in found]
    learn = found[ids.index("learn")]
    assert ids.index("learn") < ids.index("run")
    assert learn["run"] == "uv run snowlight predict learn"
    assert learn["continue-on-error"] is True
    # S6: the step runs before the chain's first pass, so it is capped at a few minutes.
    assert int(str(learn["timeout-minutes"])) <= 5
    # The live state is restored for reading, never saved from here.
    live = [step for step in found if "live-state" in str(step.get("with", {}))]
    assert [str(step["uses"]) for step in live] == ["actions/cache/restore@v4"]
    assert found.index(live[0]) < ids.index("learn")
    issue = next(step for step in found if "steps.learn.outcome" in str(step.get("if", "")))
    assert issue["if"] == (
        "always() && steps.token.outputs.ready == 'true' && steps.learn.outcome == 'failure'"
    )
    script = str(issue["run"])
    assert script.index("gh issue list") < script.index("gh issue create")
    assert '[ "$open" = "0" ]' in script
    assert load()["permissions"]["issues"] == "write"  # type: ignore[index]


def test_the_learning_step_restores_the_live_loops_cache_key_and_folder() -> None:
    # S4: the handoff is pinned: the restore names the cache store's folder in config/live.yaml
    # and the key prefix a live loop with the cache store saves under (CACHE_KEY_PREFIX), and
    # any workflow that saves that folder saves it under that prefix.
    from snowlight.live.state import ARCHIVE, CACHE_KEY_PREFIX  # noqa: PLC0415

    live = yaml.safe_load((REPO_ROOT / "pipeline" / "config" / "live.yaml").read_text())
    folder = f"pipeline/{live['state']['folder']}"
    restore = next(step for step in steps() if CACHE_KEY_PREFIX in str(step.get("with", {})))
    found = restore["with"]
    assert isinstance(found, dict)
    assert found["path"] == folder
    assert found["key"] == CACHE_KEY_PREFIX + "${{ github.run_id }}"
    assert found["restore-keys"] == CACHE_KEY_PREFIX
    assert ARCHIVE == "live-state.tar.gz"
    for path in (REPO_ROOT / ".github" / "workflows").glob("*.yml"):
        for item in yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"].values():
            for step in item.get("steps", []):
                uses, given = str(step.get("uses", "")), step.get("with", {})
                saves = "actions/cache" in uses and "restore" not in uses
                if saves and given.get("path") == folder:
                    assert str(given["key"]).startswith(CACHE_KEY_PREFIX), path.name
