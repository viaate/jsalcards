"""Contract tests for the Flights workflows: .github/workflows/flights-live.yml (the self-chained
live loop) and flights-monthly.yml (the daily check, scoring and refit).

Both stay dark without the live host token, publish only through the flights commands and keep
their own concurrency groups (the monthly job never holds the live one). Neither starts another
workflow; the live loop dispatches only its own successor."""

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


def _job(workflow: dict[str, object], name: str | None = None) -> dict[str, object]:
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    if name is None:
        assert len(jobs) == 1
        job = next(iter(jobs.values()))
    else:
        job = jobs[name]
    assert isinstance(job, dict)
    return job


def _loop(live: dict[str, object]) -> dict[str, object]:
    return _job(live, "live")


def _steps(job: dict[str, object]) -> list[dict[str, object]]:
    steps = job["steps"]
    assert isinstance(steps, list)
    return steps


def test_the_old_single_workflow_is_gone() -> None:
    assert not (WORKFLOWS / "flights.yml").exists()


def test_the_loop_starts_itself_and_from_every_backstop(live: dict[str, object]) -> None:
    triggers = live["on"]
    assert isinstance(triggers, dict)
    assert triggers["workflow_run"] == {"workflows": ["live-ingest"], "types": ["requested"]}
    assert [entry["cron"] for entry in triggers["schedule"]] == ["*/20 * * * *"]
    assert triggers["push"] == {"paths": [".github/workflows/flights-live.yml"]}
    dispatch = triggers["workflow_dispatch"]
    assert isinstance(dispatch, dict)
    assert set(dispatch["inputs"]) == {"after"}
    # One loop job at a time, never cancelled, and no group of live-ingest or live-read held.
    assert "concurrency" not in live
    job = _loop(live)
    assert job["concurrency"] == {"group": "flights-live", "cancel-in-progress": False}
    assert job["needs"] == "check"
    assert job["if"] == (
        "${{ !cancelled() && needs.check.result != 'skipped'"
        " && needs.check.outputs.start != 'false' }}"
    )
    assert "per_page=100" in str(_steps(_job(live, "check"))[0]["run"])
    check = _job(live, "check")
    assert "concurrency" not in check
    assert "default_branch" in str(check["if"])
    assert "workflow_run.head_branch" in str(check["if"])
    assert check["permissions"] == {"actions": "read"}
    assert check["timeout-minutes"] == 2
    text = LIVE.read_text(encoding="utf-8")
    assert "group: live-read" not in text
    assert "group: live-ingest" not in text


def test_the_loop_runs_its_passes_under_hard_limits(live: dict[str, object]) -> None:
    from snowlight.flights import loop  # noqa: PLC0415

    job = _loop(live)
    steps = _steps(job)
    run = next(step for step in steps if step.get("id") == "loop")
    assert run["run"] == "uv run snowlight flights loop --until +300m"
    assert loop.PASS_SECONDS <= 9 * 60
    assert loop.ALERTS_SECONDS <= 4 * 60
    # Every step is bounded, and the job outlasts the set-up, the loop and the successor.
    bounded = [step for step in steps[1:] if step.get("id") != "successor"]
    assert all(isinstance(step.get("timeout-minutes"), int) for step in bounded)
    total = sum(int(str(step["timeout-minutes"])) for step in bounded)
    assert int(str(run["timeout-minutes"])) >= 300 + 9 + 4 + 2
    assert isinstance(job["timeout-minutes"], int)
    assert total + 2 <= job["timeout-minutes"] <= 355
    env = run["env"]
    assert isinstance(env, dict)
    assert set(env) == {
        "LIVE_HOST_TOKEN",
        "CLOUDFLARE_API_TOKEN",
        "CLOUDFLARE_ACCOUNT_ID",
        "GITHUB_TOKEN",
        "SNOWLIGHT_API_ROOT",
    }
    # The live host token reaches only the token check and the loop.
    for step in steps:
        if step.get("id") not in {"token", "loop"}:
            assert "SNOWLIGHT_LIVE_TOKEN" not in str(step)


def test_the_successor_is_dispatched_unless_cancelled(live: dict[str, object]) -> None:
    job = _loop(live)
    assert job["permissions"] == {"contents": "read", "actions": "write"}
    steps = _steps(job)
    successor = steps[-1]
    assert successor["id"] == "successor"
    condition = str(successor["if"])
    assert "(success() || failure())" in condition
    assert "always()" not in condition
    assert "steps.loop.outcome != 'skipped'" in condition
    script = str(successor["run"])
    assert "actions/workflows/flights-live.yml/dispatches" in script
    assert '--arg after "$GITHUB_RUN_ID"' in script
    assert "::warning::" in script
    assert script.rstrip().endswith("exit 0")


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
    job = _loop(workflow) if path == LIVE else _job(workflow)
    assert job["environment"] == "live"
    steps = _steps(job)
    assert steps[0]["id"] == "token"
    assert "SNOWLIGHT_LIVE_TOKEN" in str(steps[0]["run"])
    for step in steps[1:]:
        assert str(step.get("if", "")).startswith("steps.token.outputs.ready == 'true'")


def test_the_jobs_run_the_flights_commands_only(
    live: dict[str, object], monthly: dict[str, object]
) -> None:
    runs = [str(step.get("run", "")) for step in _steps(_loop(live))]
    assert "uv run snowlight flights loop --until +300m" in runs
    runs = [str(step.get("run", "")) for step in _steps(_job(monthly))]
    assert any("snowlight flights monthly" in run for run in runs)
    for path in (LIVE, MONTHLY):
        text = path.read_text(encoding="utf-8")
        for forbidden in ("gh workflow run", "rerun", "re-run", "--no-verify", "gh api", "/cancel"):
            assert forbidden not in text
    # The only dispatch is the loop's own successor.
    assert MONTHLY.read_text(encoding="utf-8").count("dispatches") == 0
    assert LIVE.read_text(encoding="utf-8").count("/dispatches") == 1


def _check(
    live: dict[str, object],
    tmp_path: Path,
    answers: dict[str, str],
    env: dict[str, str] | None = None,
) -> str:
    """Run the check step with a stand-in curl that answers by URL; its ``start=`` output."""
    import os  # noqa: PLC0415
    import shutil  # noqa: PLC0415
    import subprocess  # noqa: PLC0415

    if shutil.which("jq") is None or shutil.which("bash") is None:
        pytest.skip("jq and bash are needed to run the step")
    step = next(s for s in _steps(_job(live, "check")) if s.get("id") == "loop")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    for name, body in answers.items():
        (tmp_path / name).write_text(body)
    lines = [
        "#!/bin/bash",
        'out=""; url=""',
        'while [ $# -gt 0 ]; do case "$1" in -o) out="$2"; shift 2 ;; -w|-H|--max-time) shift 2 ;;'
        ' -*) shift ;; *) url="$1"; shift ;; esac; done',
        'case "$url" in',
        f"  */workflows/flights-live.yml/runs*) src={tmp_path}/runs ;;",
        f"  */runs/*/jobs) id=${{url%/jobs}}; id=${{id##*/}}; src={tmp_path}/jobs-$id ;;",
        "  *) exit 7 ;;",
        "esac",
        '[ -f "$src" ] || { printf 404; exit 0; }',
        'cp "$src" "$out"; printf 200',
    ]
    curl = bin_dir / "curl"
    curl.write_text("\n".join(lines) + "\n")
    curl.chmod(0o755)
    output = tmp_path / "out"
    output.write_text("")
    work = tmp_path / "work"
    work.mkdir()
    full = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GITHUB_OUTPUT": str(output),
        "GITHUB_REPOSITORY": "o/r",
        "GITHUB_RUN_ID": "9",
        "GH_TOKEN": "x",
        "AFTER": "",
        "EVENT": "schedule",
        **(env or {}),
    }
    subprocess.run(  # noqa: S603
        ["bash", "-c", str(step["run"])],  # noqa: S607
        env=full,
        cwd=work,
        check=True,
        capture_output=True,
    )
    return output.read_text().strip()


def _runs(*ids: int) -> str:
    import json  # noqa: PLC0415

    return json.dumps({"workflow_runs": [{"id": i, "status": "in_progress"} for i in ids]})


def _jobs(*jobs: tuple[str, str]) -> str:
    import json  # noqa: PLC0415

    return json.dumps({"jobs": [{"name": n, "status": s} for n, s in jobs]})


def test_a_run_ends_quietly_while_a_loop_runs(live: dict[str, object], tmp_path: Path) -> None:
    running = {
        "runs": _runs(9, 7),
        "jobs-7": _jobs(("check", "completed"), ("live", "in_progress")),
    }
    assert _check(live, tmp_path / "a", running) == "start=false"
    # A loop waiting in the group counts too.
    waiting = {"runs": _runs(7), "jobs-7": _jobs(("live", "queued"))}
    assert _check(live, tmp_path / "b", waiting) == "start=false"
    # Its own run, and the predecessor that dispatched it, never count.
    assert _check(live, tmp_path / "c", running, {"AFTER": "7"}) == "start=true"
    assert _check(
        live, tmp_path / "d", {"runs": _runs(9), "jobs-9": _jobs(("live", "queued"))}
    ) == ("start=true")
    # A run whose loop is over, or that only checked, holds nothing.
    over = {
        "runs": _runs(7, 8),
        "jobs-7": _jobs(("live", "completed")),
        "jobs-8": _jobs(("check", "in_progress")),
    }
    assert _check(live, tmp_path / "e", over) == "start=true"


def test_a_list_that_fails_leaves_the_group_to_keep_one_loop(
    live: dict[str, object], tmp_path: Path
) -> None:
    assert _check(live, tmp_path / "a", {}) == "start=true"
    assert _check(live, tmp_path / "b", {"runs": _runs(7)}) == "start=true"
    # A push of this file always starts one (the group serialises it behind any other).
    running = {"runs": _runs(7), "jobs-7": _jobs(("live", "in_progress"))}
    assert _check(live, tmp_path / "c", running, {"EVENT": "push"}) == "start=true"
