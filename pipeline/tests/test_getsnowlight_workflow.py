"""Contract tests for .github/workflows/getsnowlight.yml, the getsnowlight landing's deploy.

It runs when the landing's files change, on the default branch only, reads the repository
and nothing more, fails dark without the Cloudflare secrets, builds the landing to its own
folder (web/dist-get, never the map's web/dist), refuses to deploy a landing without the
site's lock, and deploys to the Pages project getsnowlight with www.getsnowlight.com attached.
Its secrets check and lock check are run here to see what they do.
"""

import fnmatch
import json
import os
import re
import subprocess
from pathlib import Path
from typing import cast

import pytest
import yaml  # type: ignore[import-untyped, unused-ignore]

REPO_ROOT = Path(__file__).resolve().parents[1].parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "getsnowlight.yml"
WEB = REPO_ROOT / "web"
SECRETS = "Are the Cloudflare secrets set"
LOCK = "Check the landing is locked"

type Step = dict[str, object]


@pytest.fixture(scope="module")
def workflow() -> dict[object, object]:
    loaded = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return cast("dict[object, object]", loaded)


def _job(workflow: dict[object, object]) -> dict[str, object]:
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    assert list(jobs) == ["deploy"]
    return cast("dict[str, object]", jobs["deploy"])


def _steps(workflow: dict[object, object]) -> list[Step]:
    return cast("list[Step]", _job(workflow)["steps"])


def _step(workflow: dict[object, object], name: str) -> Step:
    (step,) = [s for s in _steps(workflow) if s.get("name") == name]
    return step


def _bash(script: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - the workflow's own script, in a temp dir
        ["/bin/bash", "-e", "-c", script],
        cwd=cwd,
        env={"PATH": os.environ["PATH"], **env},
        capture_output=True,
        text=True,
        check=False,
    )


def test_it_runs_when_the_landing_changes_on_the_default_branch(
    workflow: dict[object, object],
) -> None:
    # YAML 1.1 reads the key "on" as True.
    on = cast("dict[str, object]", workflow[True])
    assert set(on) == {"push", "workflow_dispatch"}
    paths = cast("dict[str, list[str]]", on["push"])["paths"]
    for wanted in (
        "web/get/**",
        "web/src/copy-get.ts",
        "web/vite.get.config.ts",
        ".github/workflows/getsnowlight.yml",
    ):
        assert wanted in paths
    for pattern in paths:
        assert list(REPO_ROOT.glob(pattern.replace("**", "*"))), f"{pattern!r} matches no file"
    assert workflow["permissions"] == {"contents": "read"}
    assert _job(workflow)["if"] == "github.ref_name == github.event.repository.default_branch"


def _landing_inputs() -> set[str]:
    """Every file the landing's build reads: vite.get.config.ts and the local modules it
    imports, one import after another, the files get/index.html takes from public/, and the
    package files that pin the build's tools."""
    web = REPO_ROOT / "web"
    seen: set[Path] = set()
    todo = [web / "vite.get.config.ts"]
    while todo:
        module = todo.pop()
        if module in seen:
            continue
        seen.add(module)
        for found in re.finditer(r"from '(\.{1,2}/[^']+)'", module.read_text(encoding="utf-8")):
            target = (module.parent / found.group(1)).resolve()
            if target.suffix in {".ts", ".js", ".mjs"} and target.is_file():
                todo.append(target)
    page = (web / "get" / "index.html").read_text(encoding="utf-8")
    for found in re.finditer(r'(?:href|src)="\.\./(public/[^"]+)"', page):
        seen.add(web / found.group(1))
    seen.update({web / "package.json", web / "package-lock.json"})
    return {path.relative_to(REPO_ROOT).as_posix() for path in seen}


def test_it_runs_when_any_file_the_landing_build_reads_changes(
    workflow: dict[object, object],
) -> None:
    on = cast("dict[str, object]", workflow[True])
    paths = cast("dict[str, list[str]]", on["push"])["paths"]
    inputs = _landing_inputs()
    assert "web/tools/get-page.ts" in inputs
    assert "web/public/icons/apple-touch-icon.v2.png" in inputs
    for name in sorted(inputs):
        assert (REPO_ROOT / name).is_file(), name
        assert any(fnmatch.fnmatchcase(name, pattern) for pattern in paths), name


def test_every_step_after_the_secrets_check_waits_for_them(
    workflow: dict[object, object],
) -> None:
    steps = _steps(workflow)
    assert steps[0].get("name") == SECRETS
    for step in steps[1:]:
        assert step.get("if") == "steps.secrets.outputs.enabled == 'true'", step
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    # The secrets are named in env blocks only, never in a script.
    for step in steps:
        assert "secrets." not in str(step.get("run", ""))
    assert text.count("secrets.CLOUDFLARE_API_TOKEN") == 2
    assert text.count("secrets.CLOUDFLARE_ACCOUNT_ID") == 2


@pytest.mark.parametrize(
    ("token", "account", "enabled"),
    [("true", "true", "true"), ("false", "true", "false"), ("true", "false", "false")],
)
def test_it_fails_dark_without_the_secrets(
    workflow: dict[object, object], tmp_path: Path, token: str, account: str, enabled: str
) -> None:
    output = tmp_path / "output"
    result = _bash(
        str(_step(workflow, SECRETS)["run"]),
        tmp_path,
        {"HAVE_TOKEN": token, "HAVE_ACCOUNT": account, "GITHUB_OUTPUT": str(output)},
    )
    assert result.returncode == 0
    assert output.read_text(encoding="utf-8") == f"enabled={enabled}\n"
    assert ("::notice::" in result.stdout) == (enabled == "false")


def test_it_builds_the_landing_alone(workflow: dict[object, object]) -> None:
    assert _job(workflow)["defaults"] == {"run": {"working-directory": "web"}}
    runs = [str(step.get("run", "")) for step in _steps(workflow)]
    assert "npm run build:get" in runs
    scripts = json.loads((WEB / "package.json").read_text(encoding="utf-8"))["scripts"]
    assert scripts["build:get"] == "vite build --config vite.get.config.ts"
    assert (WEB / "vite.get.config.ts").is_file()
    assert not [run for run in runs if "npm run build\n" in f"{run}\n" or " dist " in f" {run} "]


@pytest.mark.parametrize(("count", "ok"), [(3, True), (2, False), (0, False)])
def test_it_never_deploys_a_landing_without_the_lock(
    workflow: dict[object, object], tmp_path: Path, count: int, ok: bool
) -> None:
    dist = tmp_path / "dist-get"
    dist.mkdir()
    (dist / "index.html").write_text("<p>page</p>\n" + "lock-form\n" * count, encoding="utf-8")
    result = _bash(str(_step(workflow, LOCK)["run"]), tmp_path, {})
    assert (result.returncode == 0) == ok
    assert ("::error::" in result.stdout) == (not ok)


def test_it_deploys_to_its_own_project_and_name(workflow: dict[object, object]) -> None:
    deploy = str(_step(workflow, "Deploy the landing")["run"])
    assert "pages deploy dist-get --project-name getsnowlight --branch main" in deploy
    runs = "\n".join(str(step.get("run", "")) for step in _steps(workflow))
    assert "projects/getsnowlight/domains" in runs
    assert '"name":"www.getsnowlight.com"' in runs
    # The map's own Pages, project and name are never touched here.
    assert "snowlight-status" not in runs
    assert "snowlightmap.com" not in runs
    # The same wrangler as the status page deploys with.
    status = json.loads((REPO_ROOT / "status" / "package.json").read_text(encoding="utf-8"))
    pinned = status["devDependencies"]["wrangler"]
    assert runs.count("npx --yes wrangler@") == runs.count(f"npx --yes wrangler@{pinned} ")
    assert runs.count("wrangler") == runs.count(f"wrangler@{pinned} ")
