"""A fixed copy of every input, taken before the measure starts.

Other builds rewrite the station reads and rows, the registry and the coverage
file while this one runs, so :func:`take_snapshot` copies each input into one
folder with its SHA-256, and the measure reads only that copy. A reads file and
its rows file are written one after the other by their builder; a copy is kept
only when the reads file did not change while its rows file was copied, else it
is taken again. ``snapshot.json`` in the folder lists every file::

    {"files": {name: {"path", "source", "sha256", "bytes"}}}

(``path`` is relative to the snapshot folder, ``source`` to the pipeline folder
when the input lies inside it.) :func:`load_snapshot` reads a snapshot back and
checks every file against its SHA-256, so a measure can be run again on exactly
the same inputs.
"""

import hashlib
import json
import shutil
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from snowlight.output import JSONValue, write_json

MANIFEST: Final = "snapshot.json"
PAIRS: Final = (("live_reads", "live_rows"), ("archive_reads", "archive_rows"))
"""Reads files and the rows files written beside them."""
ATTEMPTS: Final = 5
REGISTRY_PREFIX: Final = "registry/"
LAYOUT: Final[Mapping[str, str]] = {
    "live_reads": "live/reads.jsonl",
    "live_rows": "live/rows.jsonl",
    "archive_reads": "archive/reads.jsonl",
    "archive_rows": "archive/rows.jsonl",
    "coverage": "coverage.json",
    "aliases": "aliases.yaml",
    "districts": "directory/districts.parquet",
    "schools": "directory/schools.parquet",
    "weights": "closure-weights.json",
    "rosters": "rosters.json",
}
"""Where each input goes in the snapshot folder."""


class SnapshotError(ValueError):
    """A snapshot is missing a file, or a file does not match its SHA-256."""


@dataclass(frozen=True, slots=True)
class SnapFile:
    """One input as copied."""

    path: Path
    source: str
    sha256: str
    bytes: int

    def to_json(self, root: Path) -> dict[str, JSONValue]:
        """The entry ``snapshot.json`` keeps for this file."""
        return {
            "path": self.path.relative_to(root).as_posix(),
            "source": self.source,
            "sha256": self.sha256,
            "bytes": self.bytes,
        }


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Every input of one measure, by name."""

    root: Path
    files: Mapping[str, SnapFile]

    def path(self, name: str) -> Path:
        """The copied file ``name``.

        Raises:
            SnapshotError: the snapshot holds no such file.
        """
        item = self.files.get(name)
        if item is None:
            raise SnapshotError(f"the snapshot holds no {name!r}")
        return item.path

    def has(self, name: str) -> bool:
        """True when the snapshot holds ``name``."""
        return name in self.files

    @property
    def registry_dir(self) -> Path:
        """The folder holding the copied registry files."""
        return self.root / "registry"


def sha256_file(path: Path) -> str:
    """The SHA-256 of a file's bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _described(source: Path, base: Path) -> str:
    try:
        return source.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return source.resolve().as_posix()


def _copy(source: Path, dest: Path, base: Path) -> SnapFile:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)
    return SnapFile(dest, _described(source, base), sha256_file(dest), dest.stat().st_size)


def take_snapshot(
    inputs: Mapping[str, Path],
    registry_dir: Path,
    dest: Path,
    *,
    base: Path,
    sleep: Callable[[float], None] = time.sleep,
) -> Snapshot:
    """Copy ``inputs`` (name to file) and the registry's YAML files into ``dest``.

    ``dest`` is replaced as a whole. ``base`` is the folder input paths are
    recorded relative to.

    Raises:
        SnapshotError: an input is missing, or a reads file kept changing while its
            rows file was copied.
    """
    unknown = sorted(set(inputs) - set(LAYOUT))
    if unknown:
        raise SnapshotError(f"no place in the snapshot for {unknown}")
    missing = sorted(name for name, path in inputs.items() if not path.is_file())
    if missing:
        raise SnapshotError(f"inputs not found: {missing}")
    staging = dest.with_name(f".{dest.name}.new")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    files: dict[str, SnapFile] = {}
    paired = {name for pair in PAIRS for name in pair}
    for name, path in sorted(inputs.items()):
        if name not in paired:
            files[name] = _copy(path, staging / LAYOUT[name], base)
    for reads_name, rows_name in PAIRS:
        if reads_name in inputs and rows_name in inputs:
            files.update(
                _copy_pair(
                    (reads_name, inputs[reads_name], staging / LAYOUT[reads_name]),
                    (rows_name, inputs[rows_name], staging / LAYOUT[rows_name]),
                    base,
                    sleep,
                )
            )
        elif reads_name in inputs or rows_name in inputs:
            raise SnapshotError(f"{reads_name} and {rows_name} are copied together")
    for path in sorted(registry_dir.glob("*.yaml")):
        files[f"{REGISTRY_PREFIX}{path.name}"] = _copy(path, staging / "registry" / path.name, base)
    if not any(name.startswith(REGISTRY_PREFIX) for name in files):
        raise SnapshotError(f"no registry files in {registry_dir}")
    manifest: dict[str, JSONValue] = {
        "files": {name: item.to_json(staging) for name, item in sorted(files.items())}
    }
    write_json(staging / MANIFEST, manifest)
    if dest.exists():
        shutil.rmtree(dest)
    staging.rename(dest)
    return load_snapshot(dest)


def _copy_pair(
    reads: tuple[str, Path, Path],
    rows: tuple[str, Path, Path],
    base: Path,
    sleep: Callable[[float], None],
) -> dict[str, SnapFile]:
    """Copy a reads file and its rows file, again while the reads file changes meanwhile."""
    reads_name, reads_source, reads_dest = reads
    rows_name, rows_source, rows_dest = rows
    for _attempt in range(ATTEMPTS):
        before = sha256_file(reads_source)
        copied_rows = _copy(rows_source, rows_dest, base)
        copied_reads = _copy(reads_source, reads_dest, base)
        if copied_reads.sha256 == before == sha256_file(reads_source):
            return {reads_name: copied_reads, rows_name: copied_rows}
        sleep(2.0)
    raise SnapshotError(f"{reads_source} kept changing while {rows_source} was copied")


def load_snapshot(root: Path) -> Snapshot:
    """Read a snapshot folder and check every file against its SHA-256.

    Raises:
        SnapshotError: the manifest is missing, or a file is missing or altered.
    """
    manifest = root / MANIFEST
    if not manifest.is_file():
        raise SnapshotError(f"no {MANIFEST} in {root}")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    entries = data.get("files") if isinstance(data, dict) else None
    if not isinstance(entries, dict):
        raise SnapshotError(f"{manifest}: no files")
    files: dict[str, SnapFile] = {}
    for name, entry in sorted(entries.items()):
        if not isinstance(entry, dict):
            raise SnapshotError(f"{manifest}: {name} is not described")
        path = root / str(entry["path"])
        if not path.is_file() or sha256_file(path) != entry["sha256"]:
            raise SnapshotError(f"{path}: missing or altered since the snapshot")
        files[name] = SnapFile(
            path, str(entry["source"]), str(entry["sha256"]), int(entry["bytes"])
        )
    return Snapshot(root, files)
