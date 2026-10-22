"""Contract tests for .github/workflows/data-mirror.yml, the data mirror's seeding.

It runs on pushes that change the pins or itself, never by hand, writes only the
repository's releases, and uploads only what the release lacks. Its seeding step
is run with stand-in ``uv`` and ``gh`` to check what it does.
"""

import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import cast

import pytest
import yaml  # type: ignore[import-untyped, unused-ignore]

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "data-mirror.yml"
TAG = "data-mirror-0123456789ab"

type Step = dict[str, object]


@pytest.fixture(scope="module")
def workflow() -> dict[object, object]:
    loaded = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return cast("dict[object, object]", loaded)


def _steps(workflow: dict[object, object]) -> list[Step]:
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    return cast("list[Step]", jobs["seed"]["steps"])


def _script(workflow: dict[object, object], name: str) -> str:
    (step,) = [s for s in _steps(workflow) if s.get("name") == name]
    return str(step["run"])


def test_it_runs_on_pin_changes_only(workflow: dict[object, object]) -> None:
    # YAML 1.1 reads the key "on" as True.
    assert workflow[True] == {
        "push": {
            "paths": [
                "pipeline/config/directory.yaml",
                "pipeline/config/places.yaml",
                ".github/workflows/data-mirror.yml",
            ]
        }
    }
    assert workflow["permissions"] == {"contents": "write"}
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    assert jobs["seed"]["if"] == "github.ref_name == github.event.repository.default_branch"
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "workflow_dispatch" not in text
    assert "secrets." not in text


def test_the_proof_compares_the_staged_files_with_the_release(
    workflow: dict[object, object],
) -> None:
    (step,) = [s for s in _steps(workflow) if str(s.get("name", "")).startswith("Builds from")]
    assert step["if"] == "steps.seed.outputs.staged == 'true'"
    script = str(step["run"])
    # Both sides read only pinned files (an unpinned NCES candidate is not published), and
    # the release side is dated by the first build's edition, so midnight UTC cannot split them.
    assert script.count('--mirror "$MIRROR_ROOT"') == 2
    assert "--pinned" not in script
    assert '--mirror ""' not in script
    assert 'dated=(--previous-edition "${out}/seeded/site/schools/edition.json")' in script
    assert '"${dated[@]}"' in script
    assert "diff -r --exclude='*.internal.json'" in script
    assert 'diff -r "${out}/seeded/search" "${out}/mirror/search"' in script


def test_the_seed_checks_digests_and_reads_earlier_releases(
    workflow: dict[object, object],
) -> None:
    script = _script(workflow, "Upload the pinned files the release lacks")
    assert '[.name, (.digest // "")] | @tsv' in script
    assert 'startswith("data-mirror-")' in script
    assert '--mirror "$MIRROR_ROOT" --earlier "${RUNNER_TEMP}/earlier.txt"' in script
    assert "--clobber" in script


@pytest.fixture
def stand_ins(tmp_path: Path) -> Path:
    """``uv`` and ``gh`` that log their arguments; ``gh api`` answers as RELEASE says."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "uv").write_text(
        "#!/bin/sh\n"
        'echo "uv $*" >> "$LOG"\n'
        'case "$*" in\n'
        f'  *"mirror tag"*) echo {TAG} ;;\n'
        '  *"mirror seed"*) mkdir -p "$RUNNER_TEMP/upload"\n'
        '    for name in $STAGE; do echo x > "$RUNNER_TEMP/upload/$name"; done ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    (bin_dir / "gh").write_text(
        "#!/bin/sh\n"
        'echo "gh $*" >> "$LOG"\n'
        'if [ "$1" = api ] && [ "$2" = --paginate ]; then\n'
        "  echo data-mirror-0000000000aa\n"
        'elif [ "$1" = api ]; then\n'
        '  case "$RELEASE" in\n'
        '    missing) echo "gh: Not Found (HTTP 404)" >&2; exit 1 ;;\n'
        '    broken) echo "gh: Server Error (HTTP 502)" >&2; exit 1 ;;\n'
        "    *) for name in $RELEASE; do printf '%s\\tsha256:00\\n' \"$name\"; done ;;\n"
        "  esac\n"
        "fi\n",
        encoding="utf-8",
    )
    for path in bin_dir.iterdir():
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return bin_dir


def _seed(
    workflow: dict[object, object], tmp_path: Path, bin_dir: Path, release: str, stage: str
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    script = _script(workflow, "Upload the pinned files the release lacks")
    bash = shutil.which("bash")
    assert bash is not None
    log = tmp_path / "log.txt"
    log.unlink(missing_ok=True)
    runner_temp = tmp_path / "runner"
    shutil.rmtree(runner_temp, ignore_errors=True)
    runner_temp.mkdir()
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "LOG": str(log),
        "RELEASE": release,
        "STAGE": stage,
        "RUNNER_TEMP": str(runner_temp),
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_SHA": "abc123",
        "GITHUB_OUTPUT": str(runner_temp / "output.txt"),
    }
    result = subprocess.run(  # noqa: S603 - the workflow's own script, in a temp dir
        [bash, "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return result, lines


def test_a_new_release_is_created_and_filled(
    workflow: dict[object, object], tmp_path: Path, stand_ins: Path
) -> None:
    result, log = _seed(workflow, tmp_path, stand_ins, "missing", "a.zip b.zip")
    assert result.returncode == 0, result.stderr
    (create,) = [line for line in log if line.startswith("gh release create")]
    assert f"gh release create {TAG} --repo owner/repo --target abc123" in create
    assert "--latest=false" in create
    (upload,) = [line for line in log if line.startswith("gh release upload")]
    assert upload.startswith(f"gh release upload {TAG} ")
    assert upload.endswith(
        "/upload/a.zip " + str(tmp_path / "runner") + "/upload/b.zip --repo owner/repo --clobber"
    )
    output = (tmp_path / "runner" / "output.txt").read_text(encoding="utf-8")
    assert output == "staged=true\n"
    earlier = (tmp_path / "runner" / "earlier.txt").read_text(encoding="utf-8")
    assert earlier == "data-mirror-0000000000aa\n"


def test_a_full_release_is_left_alone(
    workflow: dict[object, object], tmp_path: Path, stand_ins: Path
) -> None:
    result, log = _seed(workflow, tmp_path, stand_ins, "a.zip b.zip", "")
    assert result.returncode == 0, result.stderr
    assert not [line for line in log if line.startswith("gh release")]
    (seed,) = [line for line in log if "mirror seed" in line]
    assert "--have" in seed
    have = (tmp_path / "runner" / "have.txt").read_text(encoding="utf-8")
    assert have == "a.zip\tsha256:00\nb.zip\tsha256:00\n"
    assert f"the release {TAG} holds every pinned file" in result.stdout
    output = (tmp_path / "runner" / "output.txt").read_text(encoding="utf-8")
    assert output == "staged=false\n"


def test_a_release_that_cannot_be_read_stops_the_job(
    workflow: dict[object, object], tmp_path: Path, stand_ins: Path
) -> None:
    result, log = _seed(workflow, tmp_path, stand_ins, "broken", "a.zip")
    assert result.returncode == 1
    assert not [line for line in log if "mirror seed" in line or "gh release" in line]
    assert f"::error::could not read the release {TAG}" in result.stdout


CHECK_PATH = REPO_ROOT / ".github" / "workflows" / "nces-check.yml"


def test_the_release_check_runs_weekly_and_only_files_an_issue() -> None:
    loaded = yaml.safe_load(CHECK_PATH.read_text(encoding="utf-8"))
    triggers = loaded[True]
    assert set(triggers) == {"schedule", "push"}
    (schedule,) = triggers["schedule"]
    minute, hour, day, month, weekday = schedule["cron"].split()
    assert (day, month) == ("*", "*")
    assert weekday.isdigit()
    assert minute.isdigit()
    assert hour.isdigit()
    assert triggers["push"] == {"paths": [".github/workflows/nces-check.yml"]}
    assert loaded["permissions"] == {"contents": "read", "issues": "write"}
    (step,) = [s for s in loaded["jobs"]["check"]["steps"] if "run" in s]
    assert step["run"].strip().endswith("uv run snowlight nces check --issue")
    text = CHECK_PATH.read_text(encoding="utf-8")
    assert "workflow_dispatch" not in text
    assert "secrets." not in text
