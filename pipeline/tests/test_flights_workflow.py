"""Contract tests for the Flights workflows: .github/workflows/flights-live.yml (the live pass on
the live-ingest tick) and flights-monthly.yml (the daily check, scoring and refit).

Both stay dark without the live host token, publish only through the flights commands, keep
their own concurrency groups (the monthly job never holds the live one), and never start
another workflow or run (no rerun, no dispatch)."""

from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped, unused-ignore]

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
LIVE = WORKFLOWS / "flights-live.yml"
MONTHLY = WORKFLOWS / "flights-monthly.yml"


def _load(path: Path) -> dict[str, object]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    # yaml reads the key `on` as true: name it back.
    return {("on" if key is True else str(key)): value for key, value in loaded.items()}


@pytest.fixture(scope="module")
def live() -> dict[str, object]:
    return _load(LIVE)


@pytest.fixture(scope="module")
def monthly() -> dict[str, object]:
    return _load(MONTHLY)


def _job(workflow: dict[str, object]) -> dict[str, object]:
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    assert len(jobs) == 1
    job = next(iter(jobs.values()))
    assert isinstance(job, dict)
    return job


def _steps(job: dict[str, object]) -> list[dict[str, object]]:
    steps = job["steps"]
    assert isinstance(steps, list)
    return steps


def test_the_old_single_workflow_is_gone() -> None:
    assert not (WORKFLOWS / "flights.yml").exists()


def test_the_live_pass_hangs_off_the_live_ingest_tick(live: dict[str, object]) -> None:
    triggers = live["on"]
    assert isinstance(triggers, dict)
    assert triggers["workflow_run"] == {"workflows": ["live-ingest"], "types": ["requested"]}
    # The hourly cron is only a backstop; there is no dispatch.
    assert [entry["cron"] for entry in triggers["schedule"]] == ["7 * * * *"]
    assert "workflow_dispatch" not in triggers
    assert live["concurrency"] == {"group": "flights-live", "cancel-in-progress": False}
    job = _job(live)
    assert "default_branch" in str(job["if"])


def test_the_live_pass_runs_only_when_the_served_file_is_old(live: dict[str, object]) -> None:
    steps = _steps(_job(live))
    due = next(step for step in steps if step.get("id") == "due")
    assert "v1/flights/latest.json" in str(due["run"])
    assert "-ge 900" in str(due["run"])
    assert "--max-time 15" in str(due["run"])
    # Read past the Pages cache: the host repository first, a query no cache holds after.
    assert "api.github.com/repos/viaate/snowlight-live/contents/" in str(due["run"])
    assert "latest.json?t=" in str(due["run"])
    later = steps[steps.index(due) + 1 :]
    assert later
    for step in later:
        assert "steps.due.outputs.due == 'true'" in str(step["if"])


def test_the_monthly_job_has_its_own_group(monthly: dict[str, object]) -> None:
    triggers = monthly["on"]
    assert isinstance(triggers, dict)
    # Started from the live-ingest tick (the schedule here fires late), the cron a backstop.
    assert triggers["workflow_run"] == {"workflows": ["live-ingest"], "types": ["requested"]}
    assert [entry["cron"] for entry in triggers["schedule"]] == ["41 9 * * *"]
    assert "workflow_dispatch" in triggers
    assert monthly["concurrency"] == {"group": "flights-monthly", "cancel-in-progress": False}
    assert "default_branch" in str(_job(monthly)["if"])


def test_the_monthly_job_goes_on_once_a_day(monthly: dict[str, object]) -> None:
    steps = _steps(_job(monthly))
    day = next(step for step in steps if step.get("id") == "day")
    seen = next(step for step in steps if step.get("id") == "seen")
    assert "date -u +%F" in str(day["run"])
    assert str(seen["uses"]).startswith("actions/cache/restore")
    assert seen["with"] == {
        "path": ".flights-day",
        "key": "${{ steps.day.outputs.key }}",
        "lookup-only": True,
    }
    after = steps[steps.index(seen) + 1 :]
    # The marker is kept before any work, so a run that later fails is not started again that
    # day by every tick; every later step waits on the marker's absence.
    assert str(after[0]["uses"]).startswith("actions/cache/save")
    assert after[0]["with"] == {"path": ".flights-day", "key": "${{ steps.day.outputs.key }}"}
    for step in after:
        assert "steps.seen.outputs.cache-hit != 'true'" in str(step["if"])


def test_the_history_cache_is_saved_only_when_something_new_was_kept(
    monthly: dict[str, object],
) -> None:
    steps = _steps(_job(monthly))
    save = next(
        step
        for step in steps
        if str(step.get("uses", "")).startswith("actions/cache/save")
        and "pipeline/.flights-raw" in str(step.get("with"))
    )
    assert "steps.room.outputs.save == 'true'" in str(save["if"])
    saved = save["with"]
    assert isinstance(saved, dict)
    assert saved["key"] == "${{ steps.room.outputs.key }}"


def test_the_flights_caches_stay_one_history_under_2_gb(monthly: dict[str, object]) -> None:
    # LR-F7 and R6-S1: saved only when something new was kept, each save under a new key, under
    # 1 GB so the old and the new entry together stay under 2 GB, and the older flights-history
    # entries and day markers deleted only after the new save succeeded and is listed, so a
    # failed save never leaves the job with no history.
    job = _job(monthly)
    assert job["permissions"] == {"contents": "read", "actions": "write"}
    steps = _steps(job)
    room = next(step for step in steps if step.get("id") == "room")
    assert "steps.month.outputs.fetched == 'true'" in str(room["if"])
    script = str(room["run"])
    assert "1000000000" in script
    assert "save=false" in script
    assert "gh cache delete" not in script
    assert (
        "key=flights-history-$(date -u +%Y-%m-%d)-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}" in script
    )
    save = next(step for step in steps if step.get("id") == "save")
    prune = steps[steps.index(save) + 1]
    assert steps.index(room) < steps.index(save)
    assert "steps.save.outcome == 'success'" in str(prune["if"])
    pruned = str(prune["run"])
    assert pruned.index('grep -qx "$SAVED_KEY"') < pruned.index("gh cache delete")
    assert "flights-history-*|flights-monthly-day-*)" in pruned
    assert '"$TODAY_KEY"|"$SAVED_KEY") ;;' in pruned
    assert not any(
        "gh cache delete" in str(step.get("run", "")) for step in steps[: steps.index(save)]
    )
    restore = next(
        step
        for step in steps
        if str(step.get("uses", "")).startswith("actions/cache/restore")
        and "pipeline/.flights-raw" in str(step.get("with"))
    )
    restored = restore["with"]
    assert isinstance(restored, dict)
    assert restored["restore-keys"] == "flights-history-"


@pytest.mark.parametrize("path", [LIVE, MONTHLY])
def test_each_job_stays_dark_without_the_token(path: Path) -> None:
    workflow = _load(path)
    assert workflow["permissions"] == {"contents": "read"}
    job = _job(workflow)
    assert job["environment"] == "live"
    steps = _steps(job)
    assert steps[0]["id"] == "token"
    assert "SNOWLIGHT_LIVE_TOKEN" in str(steps[0]["run"])
    for step in steps[1:]:
        assert str(step.get("if", "")).startswith("steps.token.outputs.ready == 'true'")


def test_the_jobs_run_the_flights_commands_only(
    live: dict[str, object], monthly: dict[str, object]
) -> None:
    runs = [str(step.get("run", "")) for step in _steps(_job(live))]
    assert "uv run snowlight flights live --host github" in runs
    runs = [str(step.get("run", "")) for step in _steps(_job(monthly))]
    assert any("snowlight flights monthly" in run for run in runs)
    for path in (LIVE, MONTHLY):
        text = path.read_text(encoding="utf-8")
        for forbidden in ("gh workflow run", "rerun", "--no-verify", "gh api"):
            assert forbidden not in text


def test_the_live_job_is_short(live: dict[str, object]) -> None:
    job = _job(live)
    assert isinstance(job["timeout-minutes"], int)
    assert job["timeout-minutes"] <= 15
    passes = next(s for s in _steps(job) if s.get("name") == "One live pass")
    assert passes["timeout-minutes"] == 8


def _due(live: dict[str, object], tmp_path: Path, answers: dict[str, str]) -> str:
    """Run the due step with a stand-in curl that answers by host; its ``due=`` output."""
    import os  # noqa: PLC0415
    import shutil  # noqa: PLC0415
    import subprocess  # noqa: PLC0415

    if shutil.which("jq") is None or shutil.which("bash") is None:
        pytest.skip("jq and bash are needed to run the step")
    due = next(step for step in _steps(_job(live)) if step.get("id") == "due")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    curl = bin_dir / "curl"
    lines = ["#!/bin/bash", 'case "$*" in']
    lines += [f"  *{host}*) printf '%s' '{body}' ;;" for host, body in answers.items()]
    lines += ["  *) exit 7 ;;", "esac"]
    curl.write_text("\n".join(lines) + "\n")
    curl.chmod(0o755)
    output = tmp_path / "out"
    output.write_text("")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GITHUB_OUTPUT": str(output),
        "LIVE_HOST_TOKEN": "x",
    }
    subprocess.run(["bash", "-c", str(due["run"])], env=env, check=True, capture_output=True)  # noqa: S603, S607
    return output.read_text().strip()


def _stamp(minutes_ago: int) -> str:
    from datetime import UTC, datetime, timedelta  # noqa: PLC0415

    made = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    return '{"generated_at": "' + made.strftime("%Y-%m-%dT%H:%M:%SZ") + '"}'


def test_the_due_gate_reads_the_host_before_the_cache(
    live: dict[str, object], tmp_path: Path
) -> None:
    # The host repository says fresh, the Pages copy (cached) says old: no pass.
    fresh = {"api.github.com": _stamp(3), "github.io": _stamp(40)}
    assert _due(live, tmp_path / "a", fresh) == "due=false"
    assert _due(live, tmp_path / "b", {"api.github.com": _stamp(20)}) == "due=true"
    # The host read fails: the Pages copy, read past its cache, decides.
    assert _due(live, tmp_path / "c", {"github.io": _stamp(5)}) == "due=false"
    # Nothing reads: a pass runs.
    assert _due(live, tmp_path / "d", {}) == "due=true"
