"""Contract tests for the repository's CI workflow, .github/workflows/ci.yml.

Some workflow mistakes never fail a run. A setup-uv cache glob that matches no
file only logs a warning, and the cache is then never invalidated when the
dependencies change. These tests resolve paths the way each action does and
fail locally instead.
"""

import json
import re
import shlex
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"

# owner/repo[/path]@vN (a floating major tag) or @<full commit SHA>.
PINNED_USES = re.compile(r"^[\w.-]+/[\w.-]+(?:/[\w./-]+)?@(?:v\d+|[0-9a-f]{40})$")

type Mapping = dict[str, object]


def _mapping(value: object, where: str) -> Mapping:
    assert isinstance(value, dict), f"{where} must be a mapping"
    assert all(isinstance(key, str) for key in value), f"{where} must have string keys"
    return value


def _steps(job: Mapping, job_name: str) -> list[Mapping]:
    steps = job.get("steps")
    assert isinstance(steps, list), f"job {job_name!r} must have a list of steps"
    return [_mapping(step, f"a step of job {job_name!r}") for step in steps]


def _inputs(step: Mapping) -> Mapping:
    return _mapping(step.get("with", {}), f"the inputs of {step.get('uses')!r}")


def _run_directory(job: Mapping) -> str:
    defaults = _mapping(job.get("defaults", {}), "job defaults")
    run = _mapping(defaults.get("run", {}), "job run defaults")
    directory = run.get("working-directory", ".")
    assert isinstance(directory, str)
    return directory


def _commands(job: Mapping, job_name: str) -> list[str]:
    return [step["run"] for step in _steps(job, job_name) if isinstance(step.get("run"), str)]


@pytest.fixture(scope="module")
def workflow() -> dict[object, object]:
    assert WORKFLOW_PATH.is_file(), f"{WORKFLOW_PATH} is missing"
    loaded = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), "ci.yml must be a mapping"
    return loaded


@pytest.fixture(scope="module")
def jobs(workflow: dict[object, object]) -> dict[str, Mapping]:
    raw = _mapping(workflow.get("jobs"), "jobs")
    return {name: _mapping(job, f"job {name!r}") for name, job in raw.items()}


def _steps_using(jobs: dict[str, Mapping], action: str) -> Iterator[tuple[str, Mapping, Mapping]]:
    for name, job in jobs.items():
        for step in _steps(job, name):
            uses = step.get("uses")
            if isinstance(uses, str) and uses.split("@", 1)[0] == action:
                yield name, job, step


def test_runs_on_push_and_pull_request(workflow: dict[object, object]) -> None:
    # YAML 1.1 reads a bare `on` key as the boolean true.
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict)
    assert {"push", "pull_request"} <= set(triggers)


def test_web_job_runs_every_required_check(jobs: dict[str, Mapping]) -> None:
    web = jobs["web"]
    assert _run_directory(web) == "web"
    assert _commands(web, "web") == [
        "npm ci",
        "npm run check",
        "npm run lint",
        "npm run format:check",
        "npm run test",
        "npm run build",
    ]
    setup_node = [step for job, _, step in _steps_using(jobs, "actions/setup-node") if job == "web"]
    assert len(setup_node) == 1
    assert str(_inputs(setup_node[0]).get("node-version")) == "22"


def test_pipeline_job_runs_every_required_check(jobs: dict[str, Mapping]) -> None:
    pipeline = jobs["pipeline"]
    assert _run_directory(pipeline) == "pipeline"
    assert _commands(pipeline, "pipeline") == [
        "uv sync --locked",
        "uv run ruff check",
        "uv run ruff format --check",
        "uv run mypy --strict snowlight",
        "uv run pytest",
    ]
    assert any(name == "pipeline" for name, _, _ in _steps_using(jobs, "astral-sh/setup-uv"))


def test_every_action_is_pinned(jobs: dict[str, Mapping]) -> None:
    for name, job in jobs.items():
        for step in _steps(job, name):
            uses = step.get("uses")
            if uses is not None:
                assert isinstance(uses, str)
                assert PINNED_USES.fullmatch(uses), f"{uses!r} in job {name!r} is not pinned"


def test_run_directories_exist(jobs: dict[str, Mapping]) -> None:
    for job in jobs.values():
        assert (REPO_ROOT / _run_directory(job)).is_dir()


def test_npm_run_commands_name_existing_scripts(jobs: dict[str, Mapping]) -> None:
    for name, job in jobs.items():
        package_json = REPO_ROOT / _run_directory(job) / "package.json"
        for command in _commands(job, name):
            argv = shlex.split(command)
            if argv[:2] != ["npm", "run"]:
                continue
            scripts = json.loads(package_json.read_text(encoding="utf-8"))["scripts"]
            assert argv[2] in scripts, f"job {name!r} runs a missing npm script: {command!r}"


def test_setup_node_cache_key_uses_the_lockfile(jobs: dict[str, Mapping]) -> None:
    steps = list(_steps_using(jobs, "actions/setup-node"))
    assert steps
    for name, job, step in steps:
        inputs = _inputs(step)
        assert inputs.get("cache") == "npm"
        # setup-node resolves this against the workspace root; run defaults do not apply.
        dependency_path = inputs.get("cache-dependency-path")
        assert isinstance(dependency_path, str)
        assert (REPO_ROOT / dependency_path).is_file(), f"job {name!r}: {dependency_path}"
        assert (REPO_ROOT / dependency_path).parent == REPO_ROOT / _run_directory(job)


def test_setup_uv_cache_key_uses_the_lockfile(jobs: dict[str, Mapping]) -> None:
    steps = list(_steps_using(jobs, "astral-sh/setup-uv"))
    assert steps
    for name, _, step in steps:
        inputs = _inputs(step)
        working_directory = REPO_ROOT / str(inputs.get("working-directory", "."))
        lockfile = working_directory / "uv.lock"
        assert lockfile.is_file(), f"job {name!r}: {lockfile} is missing"
        assert inputs.get("enable-cache") is True

        # setup-uv resolves every glob line against working-directory
        # (getCacheDependencyGlob in src/utils/inputs.ts).
        globs = inputs.get("cache-dependency-glob")
        assert isinstance(globs, str)
        matched: set[Path] = set()
        for line in globs.splitlines():
            pattern = line.strip()
            if not pattern or pattern.startswith("!"):
                continue
            hits = {path.resolve() for path in working_directory.glob(pattern) if path.is_file()}
            assert hits, f"job {name!r}: cache-dependency-glob {pattern!r} matches no file"
            matched |= hits
        assert lockfile.resolve() in matched, f"job {name!r}: the uv cache ignores {lockfile}"


def test_setup_uv_python_matches_the_project(jobs: dict[str, Mapping]) -> None:
    for name, _, step in _steps_using(jobs, "astral-sh/setup-uv"):
        inputs = _inputs(step)
        pinned = REPO_ROOT / str(inputs.get("working-directory", ".")) / ".python-version"
        expected = pinned.read_text(encoding="utf-8").strip()
        assert inputs.get("python-version") == expected, f"job {name!r}"
