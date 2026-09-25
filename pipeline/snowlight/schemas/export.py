"""Write the published models as JSON Schema to ``schemas/`` at the repository root.

Run from ``pipeline/``::

    uv run python -m snowlight.schemas            # rewrite schemas/
    uv run python -m snowlight.schemas --check    # exit 1 if schemas/ is stale
    uv run python -m snowlight.schemas --validate out/site-data   # check a built site

Then ``npm run gen:types`` in ``web/`` turns the schemas into TypeScript.

For each entry of :data:`snowlight.schemas.registry.PUBLISHED_FILES` this writes
``<name>.schema.json``: JSON Schema draft 2020-12 in serialization mode (what the
pipeline writes and the site reads), with wire names, keys sorted, two-space
indent and a final newline, so the same models always give the same bytes.
Enum codes carry their member names in ``x-enum-names``, and each root carries the
file's published path in ``x-snowlight-path``.

It also writes ``fingerprint.json``, whose single key is :func:`fingerprint` of the
schema files. The generated TypeScript repeats that key and ``npm run check``
fails when the two differ, so the site cannot build against types older than
the schemas.
"""

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, override

from pydantic.json_schema import GenerateJsonSchema, JsonSchemaValue
from pydantic_core import CoreSchema, core_schema

from snowlight.schemas.registry import PUBLISHED_FILES, PublishedFile
from snowlight.schemas.site import validate_site

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_DIR = REPO_ROOT / "schemas"
SCHEMA_SUFFIX = ".schema.json"
FINGERPRINT_FILE = "fingerprint.json"
DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
GENERATED_NOTE = (
    "Generated from pipeline/snowlight/schemas by `uv run python -m snowlight.schemas`. "
    "Do not edit."
)
FINGERPRINT_NOTE = (
    "sha256 over the *.schema.json files here; web/src/types/generated/fingerprint.ts "
    "must repeat it."
)


class SnowlightJsonSchema(GenerateJsonSchema):
    """Pydantic's generator, with enum member names and without per-field titles.

    Field titles would only repeat the property names. Titles set on purpose (the
    labels of tuple positions) are kept.
    """

    @override
    def field_title_should_be_set(self, schema: CoreSchema) -> bool:
        return False

    @override
    def enum_schema(self, schema: core_schema.EnumSchema) -> JsonSchemaValue:
        value = super().enum_schema(schema)
        value["x-enum-names"] = [member.name.lower() for member in schema["members"]]
        return value


def json_schema(entry: PublishedFile) -> dict[str, Any]:
    """Return the JSON Schema document for one published file."""
    schema = entry.model.model_json_schema(
        by_alias=True, mode="serialization", schema_generator=SnowlightJsonSchema
    )
    return {
        "$schema": DRAFT_2020_12,
        "$comment": GENERATED_NOTE,
        "x-snowlight-path": entry.path,
        **schema,
    }


def render(value: Any) -> bytes:
    """Serialize a schema document the one way this module writes files."""
    text = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return (text + "\n").encode("utf-8")


def fingerprint(files: Mapping[str, bytes]) -> str:
    """Return the sha256 of every ``*.schema.json`` file, by name, in name order.

    ``web/scripts/gen-types.mjs`` computes the same value: for each schema file in
    name order, the name, a newline, the sha256 of its bytes and a newline.
    """
    digest = hashlib.sha256()
    for name in sorted(files):
        if name.endswith(SCHEMA_SUFFIX):
            digest.update(f"{name}\n{hashlib.sha256(files[name]).hexdigest()}\n".encode())
    return digest.hexdigest()


def expected_files() -> dict[str, bytes]:
    """Return every file ``schemas/`` should hold, by name."""
    files = {entry.name + SCHEMA_SUFFIX: render(json_schema(entry)) for entry in PUBLISHED_FILES}
    files[FINGERPRINT_FILE] = render({fingerprint(files): FINGERPRINT_NOTE})
    return files


def _present(directory: Path) -> set[str]:
    if not directory.is_dir():
        return set()
    names = {path.name for path in directory.glob("*" + SCHEMA_SUFFIX)}
    if (directory / FINGERPRINT_FILE).exists():
        names.add(FINGERPRINT_FILE)
    return names


def stale_files(directory: Path = SCHEMA_DIR) -> list[str]:
    """Return the names in ``directory`` that are missing, out of date or left over."""
    expected = expected_files()
    stale = [
        name
        for name, data in expected.items()
        if not (directory / name).is_file() or (directory / name).read_bytes() != data
    ]
    stale.extend(_present(directory) - expected.keys())
    return sorted(stale)


def write(directory: Path = SCHEMA_DIR) -> list[str]:
    """Bring ``directory`` up to date; return the names written or removed."""
    directory.mkdir(parents=True, exist_ok=True)
    changed = stale_files(directory)
    expected = expected_files()
    for name in changed:
        target = directory / name
        if name in expected:
            target.write_bytes(expected[name])
        else:
            target.unlink()
    return changed


def main(argv: Sequence[str] | None = None) -> int:
    """Write or check ``schemas/``; return a process exit code."""
    parser = argparse.ArgumentParser(
        prog="python -m snowlight.schemas",
        description="Write the published file schemas to schemas/ as JSON Schema.",
    )
    parser.add_argument(
        "--check", action="store_true", help="change nothing; exit 1 if schemas/ is stale"
    )
    parser.add_argument("--out", type=Path, default=SCHEMA_DIR, help="default: %(default)s")
    parser.add_argument(
        "--validate",
        type=Path,
        metavar="SITE_DATA",
        help=(
            "instead, check every file under SITE_DATA: published JSON against the models, "
            "other published files by name and content, anything else as a problem"
        ),
    )
    args = parser.parse_args(argv)
    out: Path = args.out
    if args.validate is not None:
        if not args.validate.is_dir():
            sys.stderr.write(f"problem: {args.validate} is not a folder\n")
            return 1
        report = validate_site(args.validate)
        lines = [
            *(f"ok: {name}" for name in report.checked),
            *(f"ok, text scanned: {name}" for name in report.scanned),
            *(f"published, checked by its builder: {name}" for name in report.unchecked),
            *(f"skipped, never published: {name}" for name in report.skipped),
        ]
        sys.stdout.writelines(f"{line}\n" for line in lines)
        for problem in report.problems:
            sys.stderr.write(f"problem: {problem}\n")
        return 1 if report.problems else 0
    if args.check:
        stale = stale_files(out)
        for name in stale:
            sys.stderr.write(f"stale: {out / name}\n")
        if stale:
            sys.stderr.write("run: uv run python -m snowlight.schemas\n")
        return 1 if stale else 0
    for name in write(out):
        sys.stdout.write(f"wrote {out / name}\n")
    return 0
