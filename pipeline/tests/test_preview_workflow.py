"""Contract tests for the Pages preview's directory edition, .github/workflows/preview.yml.

The preview dates the directory from the edition the site serves now. These
tests pin what keeps that safe: the edition is read only by ``snowlight
directory deployed-edition`` (which reads the live deploy exactly or fails), a
failed read stops the job, the build is given the edition the reader wrote and
nothing else, and the built site must carry its own edition. The two shell
steps are run with a stand-in ``uv`` to check what they do.
"""

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path
from typing import cast

import pytest
import yaml  # type: ignore[import-untyped, unused-ignore]

from snowlight.directory.cli import REFUSED

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "preview.yml"
READER = "uv run snowlight directory deployed-edition"

type Step = dict[str, object]


@pytest.fixture(scope="module")
def workflow() -> dict[str, object]:
    loaded = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


@pytest.fixture(scope="module")
def build_steps(workflow: dict[str, object]) -> list[Step]:
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    steps = jobs["build"]["steps"]
    assert isinstance(steps, list)
    return steps


def _run(step: Step) -> str:
    run = step.get("run")
    return run if isinstance(run, str) else ""


def _index(steps: list[Step], text: str) -> int:
    (index,) = [i for i, step in enumerate(steps) if text in _run(step)]
    return index


def test_the_token_can_read_deploys_and_artifacts_only(workflow: dict[str, object]) -> None:
    assert workflow["permissions"] == {
        "contents": "read",
        "pages": "write",
        "id-token": "write",
        "actions": "read",
        "deployments": "read",
    }


def test_the_edition_is_read_by_the_reader_before_the_directory_build(
    build_steps: list[Step],
) -> None:
    reader = _index(build_steps, READER)
    builder = _index(build_steps, 'build directory "${previous[@]}"')
    assert reader < builder
    step = build_steps[reader]
    # A failed read fails the job: nothing swallows it.
    assert "continue-on-error" not in step
    assert "||" not in _run(step)
    assert "--out .cache/edition.json" in _run(step)
    env = step["env"]
    assert isinstance(env, dict)
    assert env["GITHUB_TOKEN"] == "${{ github.token }}"  # noqa: S105 - the job's own token
    # The token goes to the reader's step alone.
    others = [s for i, s in enumerate(build_steps) if i != reader]
    assert not any("GITHUB_TOKEN" in str(s.get("env", "")) for s in others)


def test_the_steps_run_reader_then_directory_then_replays_then_staging(
    build_steps: list[Step],
) -> None:
    """Replays publish against the directory just built, dated from the deployed edition,
    and staging reads both."""
    reader = _index(build_steps, READER)
    builder = _index(build_steps, 'build directory "${previous[@]}"')
    replays = _index(build_steps, "snowlight replays publish")
    stage = _index(build_steps, "npm run stage")
    assert reader < builder < replays < stage
    assert build_steps[replays].get("working-directory") == "pipeline"


def test_no_plain_read_of_the_deployed_edition() -> None:
    """Pages' CDN ignores queries and no-cache headers: a GET can be an older deploy's file."""
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "edition.json?" not in text
    for line in text.splitlines():
        assert not ("curl" in line and "edition" in line), line


def test_the_published_site_carries_its_edition(build_steps: list[Step]) -> None:
    check = build_steps[_index(build_steps, "test -f dist/data/schools/edition.json")]
    assert check.get("working-directory") == "web"
    upload = _index_uses(build_steps, "actions/upload-pages-artifact")
    assert build_steps.index(check) < upload


def _index_uses(steps: list[Step], action: str) -> int:
    (index,) = [
        i for i, step in enumerate(steps) if str(step.get("uses", "")).startswith(action + "@")
    ]
    return index


@pytest.fixture
def fake_uv(tmp_path: Path) -> Path:
    """A ``uv`` that logs its arguments and fails when told to."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "uv"
    script.write_text(
        '#!/bin/sh\necho "$*" >> "$UV_LOG"\n'
        'case "$*" in *"$UV_FAIL"*) [ -n "$UV_FAIL" ] && exit "$UV_EXIT";; esac\nexit 0\n',
        encoding="utf-8",
    )
    # sleep, curl and jq log instead: the retry pauses, the network probe and the
    # supplement warnings read from the build report.
    for name in ("sleep", "curl", "jq"):
        stand_in = bin_dir / name
        stand_in.write_text(f'#!/bin/sh\necho "{name} $*" >> "$UV_LOG"\n', encoding="utf-8")
        stand_in.chmod(stand_in.stat().st_mode | stat.S_IXUSR)
    for path in bin_dir.iterdir():
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return bin_dir


def _shell(
    script: str, cwd: Path, bin_dir: Path, fail: str = "", code: int = 1
) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    assert bash is not None
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "UV_LOG": str(cwd / "uv.log"),
        "UV_FAIL": fail,
        "UV_EXIT": str(code),
        "SITE_URL": "https://snowlight.example",
    }
    # How Actions runs a step's script.
    return subprocess.run(  # noqa: S603 - the workflow's own script, in a temp dir
        [bash, "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_failed_read_stops_the_step(
    build_steps: list[Step], tmp_path: Path, fake_uv: Path
) -> None:
    script = _run(build_steps[_index(build_steps, READER)])
    assert _shell(script, tmp_path, fake_uv).returncode == 0
    failed = _shell(script, tmp_path, fake_uv, fail="deployed-edition")
    assert failed.returncode != 0


def test_the_build_gets_the_edition_the_reader_wrote(
    build_steps: list[Step], tmp_path: Path, fake_uv: Path
) -> None:
    script = _run(build_steps[_index(build_steps, 'build directory "${previous[@]}"')])
    (tmp_path / ".cache").mkdir()
    result = _shell(script, tmp_path, fake_uv)
    assert result.returncode == 0, result.stderr
    assert "no schools/edition.json is deployed" in result.stdout
    log = _commands(tmp_path)
    assert log == ["run snowlight directory build", "run snowlight places build"]
    (tmp_path / "uv.log").unlink()
    (tmp_path / ".cache" / "edition.json").write_text("{}", encoding="utf-8")
    result = _shell(script, tmp_path, fake_uv)
    assert result.returncode == 0, result.stderr
    log = _commands(tmp_path)
    assert log == [
        "run snowlight directory build --previous-edition .cache/edition.json",
        "run snowlight places build",
    ]


def _commands(cwd: Path) -> list[str]:
    """What the step ran, but its zero-second pauses and its read of the build report."""
    log = (cwd / "uv.log").read_text(encoding="utf-8").splitlines()
    return [line for line in log if line != "sleep 0" and not line.startswith("jq ")]


def test_a_refused_build_is_not_retried(
    build_steps: list[Step], tmp_path: Path, fake_uv: Path
) -> None:
    """A refusal the inputs decide (REFUSED): one try, and no blame on nces.ed.gov."""
    script = _run(build_steps[_index(build_steps, 'build directory "${previous[@]}"')])
    assert f'"$status" -eq {REFUSED} ]' in script
    (tmp_path / ".cache").mkdir()
    (tmp_path / ".cache" / "edition.json").write_text("{}", encoding="utf-8")
    result = _shell(script, tmp_path, fake_uv, fail="directory build", code=REFUSED)
    assert result.returncode == REFUSED
    assert _commands(tmp_path) == [
        "run snowlight directory build --previous-edition .cache/edition.json"
    ]
    assert "::error::snowlight directory build refused its inputs" in result.stdout
    assert "probing" not in result.stdout


def test_a_usage_error_or_a_uv_failure_is_not_retried(
    build_steps: list[Step], tmp_path: Path, fake_uv: Path
) -> None:
    """argparse exits 2 on a flag the command does not take, and uv on its own errors: the
    step or its tools are wrong, and the message says it may be either."""
    assert REFUSED != 2
    script = _run(build_steps[_index(build_steps, 'build directory "${previous[@]}"')])
    (tmp_path / ".cache").mkdir()
    result = _shell(script, tmp_path, fake_uv, fail="directory build", code=2)
    assert result.returncode == 2
    assert _commands(tmp_path) == ["run snowlight directory build"]
    assert (
        "::error::snowlight directory build exited 2: a usage error or a uv failure "
        "(see the log above)" in result.stdout
    )
    assert "refused its inputs" not in result.stdout
    assert "probing" not in result.stdout


def test_runs_wait_their_turn_and_are_never_cancelled(workflow: dict[str, object]) -> None:
    """One run at a time, at the run's level, and no run cancels another.

    A cancelled run can be cut off mid-deploy and still go live after the next run
    read the deployed edition; waiting instead means each reader reads a deploy that
    has ended. The default branch keeps the group "pages" the preview has always
    used, so at landing the first run waits for one of the older file still in
    flight. A push to another branch builds nothing and has a group of its own, so
    it never holds up the default branch's run.
    """
    concurrency = workflow["concurrency"]
    assert concurrency == {
        "group": (
            "${{ github.ref_name == github.event.repository.default_branch && 'pages' "
            "|| format('pages-{0}', github.ref) }}"
        ),
        "cancel-in-progress": False,
    }
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    assert all("concurrency" not in job for job in jobs.values())


def test_the_recovery_input_reaches_the_reader_on_a_run_by_hand_only(
    workflow: dict[str, object],
    build_steps: list[Step],
    tmp_path: Path,
    fake_uv: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """docs/deployed-edition.md's recovery: --date-past-mismatch, only when asked for."""
    # YAML 1.1 reads the key "on" as True.
    triggers = cast("dict[object, object]", workflow)[True]
    assert isinstance(triggers, dict)
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert inputs["date_past_mismatch"]["type"] == "boolean"
    assert inputs["date_past_mismatch"]["default"] is False
    step = build_steps[_index(build_steps, READER)]
    env = step["env"]
    assert isinstance(env, dict)
    assert env["DATE_PAST_MISMATCH"] == (
        "${{ github.event_name == 'workflow_dispatch' && inputs.date_past_mismatch == true }}"
    )
    script = _run(step)
    for value, flag in (("false", False), ("", False), ("true", True)):
        log = tmp_path / "uv.log"
        log.unlink(missing_ok=True)
        monkeypatch.setenv("DATE_PAST_MISMATCH", value)
        result = _shell(script, tmp_path, fake_uv)
        assert result.returncode == 0, result.stderr
        (read,) = [line for line in _commands(tmp_path) if "deployed-edition" in line]
        assert read.endswith("--out .cache/edition.json --date-past-mismatch") is flag
        assert read.startswith("run snowlight directory deployed-edition --site ")
        assert ("::warning::recovery run" in result.stdout) is flag


def test_a_failed_build_is_tried_three_times(
    build_steps: list[Step], tmp_path: Path, fake_uv: Path
) -> None:
    """Exit 1 may be a passing network fault: two more tries, each after a pause and a probe."""
    script = _run(build_steps[_index(build_steps, 'build directory "${previous[@]}"')])
    (tmp_path / ".cache").mkdir()
    result = _shell(script, tmp_path, fake_uv, fail="directory build", code=1)
    assert result.returncode == 1
    log = _commands(tmp_path)
    assert log.count("run snowlight directory build") == 3
    assert [line for line in log if line.startswith("sleep")] == ["sleep 60", "sleep 180"]
    # No probe of the origins: the build reads the cache and the data mirror only.
    assert not [line for line in log if line.startswith("curl")]
    assert result.stdout.count("::warning::snowlight directory build failed") == 3
    assert result.stdout.count("the data mirror release") == 3
    assert "run snowlight places build" not in log


ORIGIN_HOSTS = ("nces.ed.gov", "census.gov")
# The jobs that contact the origins: seeding the mirror, and the weekly release check.
ORIGIN_READERS = frozenset({"data-mirror.yml", "nces-check.yml"})


def test_no_deploy_contacts_nces_or_census() -> None:
    """Deploys read the cache and the data mirror only; a step that names an origin fails this."""
    workflows = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
    assert WORKFLOW_PATH in workflows
    for path in workflows:
        if path.name in ORIGIN_READERS:
            continue
        text = path.read_text(encoding="utf-8").lower()
        for host in ORIGIN_HOSTS:
            assert host not in text, (path.name, host)


MIRROR_ROOT = "https://github.com/${{ github.repository }}/releases/download"
# Any directory or places build, however it is spelled: `snowlight directory build`,
# or the Preview's `snowlight "$name" build` through its build() helper.
SNOWLIGHT_BUILD = re.compile(r"\bsnowlight\s+(?:directory|places|\"?\$\{?\w+\}?\"?)\s+build\b")


def _deploy_builds() -> list[tuple[str, Step, dict[str, object]]]:
    """Every step outside the origin readers that runs a directory or places build."""
    found: list[tuple[str, Step, dict[str, object]]] = []
    for path in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")):
        if path.name in ORIGIN_READERS:
            continue
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job in loaded["jobs"].values():
            for step in job.get("steps", []):
                if SNOWLIGHT_BUILD.search(_run(step)):
                    env = {**loaded.get("env", {}), **job.get("env", {}), **step.get("env", {})}
                    found.append((path.name, step, env))
    return found


def test_the_build_pattern_matches_every_spelling() -> None:
    for script in (
        "uv run snowlight directory build --no-tiles",
        "uv run snowlight places build",
        'if uv run snowlight "$name" build "$@"; then',
        "uv run snowlight ${name} build",
    ):
        assert SNOWLIGHT_BUILD.search(script), script
    assert not SNOWLIGHT_BUILD.search("uv run snowlight replays publish")


def test_every_build_in_a_deploy_reads_the_mirror_and_requires_it() -> None:
    """A deploy's directory and places builds read the mirror, and fail closed without it."""
    builds = _deploy_builds()
    assert "preview.yml" in {name for name, _step, _env in builds}
    for name, step, env in builds:
        assert env.get("SNOWLIGHT_MIRROR") == MIRROR_ROOT, name
        assert env.get("SNOWLIGHT_REQUIRE_MIRROR") == "1", name
        assert "--mirror" not in _run(step), name


def test_the_preview_build_step_reads_the_mirror(build_steps: list[Step]) -> None:
    step = build_steps[_index(build_steps, 'build directory "${previous[@]}"')]
    script = _run(step)
    assert "build places" in script
    assert SNOWLIGHT_BUILD.search(script)
    env = step["env"]
    assert isinstance(env, dict)
    assert env["SNOWLIGHT_MIRROR"] == MIRROR_ROOT
    assert env["SNOWLIGHT_REQUIRE_MIRROR"] == "1"


def test_the_preview_waits_for_a_mirror_being_seeded_within_its_timeout(
    workflow: dict[str, object], build_steps: list[Step]
) -> None:
    """Three tries of the mirror wait, with their pauses, leave 15 minutes of the job."""
    step = build_steps[_index(build_steps, 'build directory "${previous[@]}"')]
    env = step["env"]
    assert isinstance(env, dict)
    wait = int(env["SNOWLIGHT_MIRROR_WAIT"])
    assert wait >= 300
    pauses = re.search(r"for pause in ([\d ]+); do", _run(step))
    assert pauses is not None
    tries = [int(p) for p in pauses.group(1).split()]
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    timeout = int(jobs["build"]["timeout-minutes"]) * 60
    assert len(tries) * wait + sum(tries) + 15 * 60 <= timeout


def test_the_download_cache_follows_both_pin_files(build_steps: list[Step]) -> None:
    (cache,) = [s for s in build_steps if str(s.get("uses", "")).startswith("actions/cache@")]
    settings = cache["with"]
    assert isinstance(settings, dict)
    assert "pipeline/config/directory.yaml" in settings["key"]
    assert "pipeline/config/places.yaml" in settings["key"]
