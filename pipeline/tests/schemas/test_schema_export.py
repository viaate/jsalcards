"""schemas/ and the generated TypeScript are deterministic and never stale.

``test_schema_files_are_current`` fails when a model changes and schemas/ was not
re-exported; ``test_typescript_types_are_current`` fails when schemas/ changes
and ``npm run gen:types`` was not run. The second needs Node (any version from 18)
but none of the web dependencies.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from snowlight.schemas.export import (
    FINGERPRINT_FILE,
    REPO_ROOT,
    SCHEMA_DIR,
    SCHEMA_SUFFIX,
    expected_files,
    fingerprint,
    json_schema,
    main,
    stale_files,
    write,
)
from snowlight.schemas.registry import PUBLISHED_FILES, PublishedFile

GENERATOR = REPO_ROOT / "web" / "scripts" / "gen-types.mjs"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")


def test_schema_files_are_current() -> None:
    assert stale_files(SCHEMA_DIR) == [], "run: uv run python -m snowlight.schemas"


def test_module_entry_point_checks_the_repository() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "snowlight.schemas", "--check"],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr


def test_export_is_deterministic(tmp_path: Path) -> None:
    first = expected_files()
    second = expected_files()
    assert first == second
    assert sorted(first) == sorted(
        [entry.name + SCHEMA_SUFFIX for entry in PUBLISHED_FILES] + [FINGERPRINT_FILE]
    )
    write(tmp_path / "a")
    write(tmp_path / "b")
    for name in first:
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_check_mode_reports_and_write_repairs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "schemas"
    assert main(["--out", str(out), "--check"]) == 1
    assert main(["--out", str(out)]) == 0
    assert main(["--out", str(out), "--check"]) == 0
    (out / "closings.schema.json").write_text("{}\n", encoding="utf-8")
    (out / "retired.schema.json").write_text("{}\n", encoding="utf-8")
    assert main(["--out", str(out), "--check"]) == 1
    assert "closings.schema.json" in capsys.readouterr().err
    assert write(out) == ["closings.schema.json", "retired.schema.json"]
    assert not (out / "retired.schema.json").exists()
    assert stale_files(out) == []


def test_fingerprint_covers_every_schema_byte() -> None:
    files = {name: data for name, data in expected_files().items() if name != FINGERPRINT_FILE}
    recorded = json.loads(expected_files()[FINGERPRINT_FILE])
    assert list(recorded) == [fingerprint(files)]
    for name, data in files.items():
        changed = dict(files) | {name: data + b" "}
        assert fingerprint(changed) != fingerprint(files)
    assert fingerprint(files | {FINGERPRINT_FILE: b"{}", "README.md": b"x"}) == fingerprint(files)


def test_validation_and_serialization_schemas_agree(entry: PublishedFile) -> None:
    """What the pipeline writes and what it accepts are the same shape."""
    reading = entry.model.model_json_schema(by_alias=True, mode="validation")
    writing = entry.model.model_json_schema(by_alias=True, mode="serialization")
    assert reading == writing


def _walk(schema: Any) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    if isinstance(schema, dict):
        nodes.append(schema)
        for value in schema.values():
            nodes.extend(_walk(value))
    elif isinstance(schema, list):
        for item in schema:
            nodes.extend(_walk(item))
    return nodes


def test_schemas_describe_codes_tuples_and_paths(entry: PublishedFile) -> None:
    schema = json_schema(entry)
    assert schema["x-snowlight-path"] == entry.path
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    for node in _walk(schema):
        if node.get("type") == "integer" and "enum" in node:
            assert len(node["x-enum-names"]) == len(node["enum"])
        if "prefixItems" in node:
            assert node["minItems"] == node["maxItems"] == len(node["prefixItems"])
            assert all("title" in item for item in node["prefixItems"])
        if node.get("type") == "object":
            assert set(node["required"]) == set(node["properties"])


def _copy_tree(tmp_path: Path) -> Path:
    """A copy of the generator and schemas/ laid out as in the repository."""
    root = tmp_path / "repo"
    (root / "web" / "scripts").mkdir(parents=True)
    shutil.copy(GENERATOR, root / "web" / "scripts" / GENERATOR.name)
    shutil.copytree(SCHEMA_DIR, root / "schemas")
    return root


def _generate(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    assert NODE is not None
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        [NODE, str(root / "web" / "scripts" / GENERATOR.name), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=root / "web",
        timeout=60,
    )


@needs_node
def test_typescript_types_are_current() -> None:
    result = _generate(REPO_ROOT, "--check")
    assert result.returncode == 0, result.stderr + "\nrun: npm run gen:types (in web/)"


@needs_node
def test_typescript_generation_is_deterministic_and_checked(tmp_path: Path) -> None:
    root = _copy_tree(tmp_path)
    generated = root / "web" / "src" / "types" / "generated"
    assert _generate(root, "--check").returncode == 1
    assert _generate(root).returncode == 0
    first = {path.name: path.read_bytes() for path in generated.iterdir()}
    assert sorted(first) == ["fingerprint.ts", "index.ts"]
    assert _generate(root, "--check").returncode == 0
    assert _generate(root).stdout == ""
    real = REPO_ROOT / "web" / "src" / "types" / "generated"
    for name, data in first.items():
        assert (real / name).read_bytes() == data

    # A schema that changes without a new fingerprint is refused outright.
    closings = root / "schemas" / "closings.schema.json"
    closings.write_bytes(closings.read_bytes().replace(b'"gaps"', b'"skips"'))
    refused = _generate(root, "--check")
    assert refused.returncode == 1
    assert "fingerprint.json does not match" in refused.stderr

    # Re-exported (schema and fingerprint together), the types are stale until regenerated.
    files = {path.name: path.read_bytes() for path in (root / "schemas").glob("*" + SCHEMA_SUFFIX)}
    (root / "schemas" / FINGERPRINT_FILE).write_text(
        json.dumps({fingerprint(files): "test"}), encoding="utf-8"
    )
    stale = _generate(root, "--check")
    assert stale.returncode == 1
    assert "index.ts" in stale.stderr
    assert "fingerprint.ts" in stale.stderr
    assert _generate(root).returncode == 0
    assert "readonly skips: readonly SchoolGap[];" in (generated / "index.ts").read_text(
        encoding="utf-8"
    )


@needs_node
def test_typescript_generator_removes_its_own_leftovers_only(tmp_path: Path) -> None:
    root = _copy_tree(tmp_path)
    generated = root / "web" / "src" / "types" / "generated"
    assert _generate(root).returncode == 0
    banner = (generated / "index.ts").read_text(encoding="utf-8").split("\n", 2)
    (generated / "old.ts").write_text("\n".join(banner[:2]) + "\nexport {};\n", encoding="utf-8")
    (generated / "consumer.check.ts").write_text("export {};\n", encoding="utf-8")
    assert _generate(root, "--check").returncode == 1
    assert _generate(root).returncode == 0
    assert not (generated / "old.ts").exists()
    assert (generated / "consumer.check.ts").exists()


@needs_node
def test_typescript_generator_refuses_what_it_cannot_translate(tmp_path: Path) -> None:
    root = _copy_tree(tmp_path)
    closings = root / "schemas" / "closings.schema.json"
    schema = json.loads(closings.read_text(encoding="utf-8"))
    schema["properties"]["days"]["contains"] = {"type": "object"}
    closings.write_text(json.dumps(schema), encoding="utf-8")
    files = {path.name: path.read_bytes() for path in (root / "schemas").glob("*" + SCHEMA_SUFFIX)}
    (root / "schemas" / FINGERPRINT_FILE).write_text(
        json.dumps({fingerprint(files): "test"}), encoding="utf-8"
    )
    result = _generate(root)
    assert result.returncode == 1
    assert "unsupported keyword contains" in result.stderr
