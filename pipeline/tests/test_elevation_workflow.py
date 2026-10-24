"""Contract tests for .github/workflows/elevation.yml, the school elevation table's build.

It runs on pushes that change the directory or elevation pins or itself, never by hand, on
the default branch only, writes only the repository's releases, and uploads the table under
its content-addressed name unless the release holds it. Its upload step is run with stand-in
``uv`` and ``gh`` to check what it does.
"""

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import cast

import pytest
import yaml  # type: ignore[import-untyped, unused-ignore]

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "elevation.yml"
TAG = "data-mirror-0123456789ab"
SHA = "ab" * 32
ASSET = f"school-elevations-{SHA[:16]}.json.gz"
UPLOAD = "Put the table in the data mirror release"

type Step = dict[str, object]


@pytest.fixture(scope="module")
def workflow() -> dict[object, object]:
    loaded = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return cast("dict[object, object]", loaded)


def _steps(workflow: dict[object, object]) -> list[Step]:
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    return cast("list[Step]", jobs["build"]["steps"])


def _script(workflow: dict[object, object], name: str) -> str:
    (step,) = [s for s in _steps(workflow) if s.get("name") == name]
    return str(step["run"])


def test_it_runs_on_pin_changes_only(workflow: dict[object, object]) -> None:
    # YAML 1.1 reads the key "on" as True.
    assert workflow[True] == {
        "push": {
            "paths": [
                "pipeline/config/directory.yaml",
                "pipeline/config/elevation.yaml",
                ".github/workflows/elevation.yml",
            ]
        }
    }
    assert workflow["permissions"] == {"contents": "write"}
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    assert jobs["build"]["if"] == "github.ref_name == github.event.repository.default_branch"
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "workflow_dispatch" not in text
    assert "secrets." not in text


def test_the_directory_comes_from_the_mirror_only(workflow: dict[object, object]) -> None:
    (step,) = [
        s for s in _steps(workflow) if s.get("name") == "Build the directory from the data mirror"
    ]
    env = cast("dict[str, str]", step["env"])
    assert (
        env["SNOWLIGHT_MIRROR"] == "https://github.com/${{ github.repository }}/releases/download"
    )
    assert env["SNOWLIGHT_REQUIRE_MIRROR"] == "1"
    assert int(env["SNOWLIGHT_MIRROR_WAIT"]) > 0
    script = str(step["run"])
    assert "directory build --no-tiles" in script
    assert "--mirror" not in script
    build = _script(workflow, "Read every school's height from the terrain tiles")
    assert '--directory "${RUNNER_TEMP}/site/schools"' in build


@pytest.fixture
def stand_ins(tmp_path: Path) -> Path:
    """``uv`` and ``gh`` that log their arguments; ``gh api`` answers HELD, and ``uv run
    snowlight elevation pinned`` exits PINNED."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "uv").write_text(
        "#!/bin/sh\n"
        'echo "uv $*" >> "$LOG"\n'
        'case "$*" in\n'
        f'  *"mirror tag"*) echo {TAG} ;;\n'
        '  *"elevation pinned"*) exit "$PINNED" ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    (bin_dir / "gh").write_text(
        '#!/bin/sh\necho "gh $*" >> "$LOG"\nif [ "$1" = api ]; then echo "$HELD"; fi\n',
        encoding="utf-8",
    )
    for path in bin_dir.iterdir():
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return bin_dir


def _upload(
    workflow: dict[object, object], tmp_path: Path, bin_dir: Path, held: str, pinned: int
) -> tuple[subprocess.CompletedProcess[str], list[str], str]:
    script = _script(workflow, UPLOAD)
    bash = shutil.which("bash")
    assert bash is not None
    if shutil.which("jq") is None:
        pytest.skip("jq is not installed")
    log = tmp_path / "log.txt"
    log.unlink(missing_ok=True)
    runner_temp = tmp_path / "runner"
    shutil.rmtree(runner_temp, ignore_errors=True)
    runner_temp.mkdir()
    (runner_temp / "table.json.gz").write_bytes(b"table")
    report = {"asset": ASSET, "sha256": SHA, "schools": 118211, "unknown": 3,
              "directory_sha256": "cd" * 32}  # fmt: skip
    (runner_temp / "report.json").write_text(json.dumps(report))
    summary = runner_temp / "summary.md"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "LOG": str(log),
        "HELD": held,
        "PINNED": str(pinned),
        "RUNNER_TEMP": str(runner_temp),
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_STEP_SUMMARY": str(summary),
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
    return result, lines, summary.read_text(encoding="utf-8") if summary.exists() else ""


def test_a_new_table_is_uploaded_under_its_own_name_and_its_pin_is_given(
    workflow: dict[object, object], tmp_path: Path, stand_ins: Path
) -> None:
    result, log, summary = _upload(workflow, tmp_path, stand_ins, "", 1)
    assert result.returncode == 0, result.stderr
    (upload,) = [line for line in log if line.startswith("gh release upload")]
    assert upload == (
        f"gh release upload {TAG} {tmp_path / 'runner' / ASSET} --repo owner/repo --clobber"
    )
    assert (tmp_path / "runner" / ASSET).read_bytes() == b"table"
    url = f"https://github.com/owner/repo/releases/download/{TAG}/{ASSET}"
    assert f'  url: "{url}"' in summary
    assert f'  sha256: "{SHA}"' in summary
    assert "  schools: 118211" in summary
    assert "  unknown: 3" in summary
    assert f'  directory_sha256: "{"cd" * 32}"' in summary
    assert "::warning::the table built is not the pinned one" in result.stdout
    (pinned,) = [line for line in log if "elevation pinned" in line]
    assert pinned.endswith(f"--directory {tmp_path / 'runner'}/site/schools")


def test_a_table_the_release_holds_is_not_uploaded_again(
    workflow: dict[object, object], tmp_path: Path, stand_ins: Path
) -> None:
    result, log, _summary = _upload(workflow, tmp_path, stand_ins, f"sha256:{SHA}", 0)
    assert result.returncode == 0, result.stderr
    assert not [line for line in log if line.startswith("gh release upload")]
    assert f"the release {TAG} holds {ASSET} already" in result.stdout
    assert "::notice::the table built is the pinned one" in result.stdout
    (api,) = [line for line in log if line.startswith("gh api")]
    assert f"releases/tags/{TAG}" in api


def test_an_asset_with_other_bytes_is_replaced(
    workflow: dict[object, object], tmp_path: Path, stand_ins: Path
) -> None:
    result, log, _summary = _upload(workflow, tmp_path, stand_ins, "sha256:" + "0" * 64, 0)
    assert result.returncode == 0, result.stderr
    assert [line for line in log if line.startswith("gh release upload")]


@pytest.mark.parametrize("status", [2, 3])
def test_a_table_that_does_not_rebuild_the_same_fails_before_any_upload(
    workflow: dict[object, object], tmp_path: Path, stand_ins: Path, status: int
) -> None:
    """Built from the pinned table's directory but not the pinned table (3), or unreadable
    (2): the run fails, and nothing is uploaded or offered to pin."""
    result, log, summary = _upload(workflow, tmp_path, stand_ins, "", status)
    assert result.returncode != 0
    assert "does not rebuild the same" in result.stdout
    assert not [line for line in log if line.startswith("gh ")]
    assert summary == ""
