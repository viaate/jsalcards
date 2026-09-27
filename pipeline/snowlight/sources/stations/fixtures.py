"""Test fixtures for the station adapters: real bodies, sliced, with their provenance.

Every fixture under ``pipeline/tests/stations/fixtures/`` is a real response body:
a live response, or a Wayback ``id_`` capture (the bytes the station served when
the archive read the page). A page is stored *sliced*: :func:`slice_body` keeps
the parts of the page the adapter reads (the closings data and the markers that
identify the page format) and drops the rest (articles, navigation, scripts,
advertising), so the repository keeps as little of the station's page as the
tests need. Slicing is deterministic, so anyone can check a fixture: download
the original from the URL in ``PROVENANCE.json``, confirm its SHA-256, slice it
with the recorded method, and compare bytes.

``PROVENANCE.json`` holds one :class:`FixtureEntry` per file, and ``README.md``
is rendered from it (:func:`render_readme`). Each entry also records what the
adapter reads from the fixture (variant, state, row count and every row name), so
the tests pin exact results.
"""

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from pydantic import StringConstraints, TypeAdapter

from snowlight.output import write_bytes_atomic
from snowlight.schemas.base import InternalModel
from snowlight.schemas.internal import Sha256, SourceId
from snowlight.schemas.scalars import Count, UtcInstant
from snowlight.sources.stations import gray, hearst
from snowlight.sources.stations.adapters import ADAPTERS
from snowlight.sources.stations.model import ListingState, ReadMode

PROVENANCE_FILE = "PROVENANCE.json"
README_FILE = "README.md"

type Slicer = Callable[[bytes], bytes]

SLICERS: Mapping[str, Slicer] = {
    "none": lambda body: body,
    "gray-page-v1": gray.slice_page,
    "gray-page-v2": gray.slice_page_v2,
    "gray-page-v3": gray.slice_page_v3,
    "gray-page-v4": gray.slice_page_v4,
    "hearst-page-v1": hearst.slice_page,
    "hearst-page-v2": hearst.slice_page_v2,
}
"""Slicing methods by name. A method's output never changes once fixtures use it.

A ``-v2`` method gives the same bytes as its ``-v1`` for every page ``-v1`` slices,
and also slices the older page formats ``-v1`` refuses; ``gray-page-v3`` likewise
extends ``gray-page-v2`` to Arc pages that frame their list and to the list files
pages framed or loaded (kept whole), and ``gray-page-v4`` cuts the Heartland pages
v3 kept whole to their inline list."""


class Expected(InternalModel):
    """What the adapter reads from a fixture."""

    variant: str
    state: ListingState
    rows: Count
    names: tuple[str, ...]


class FixtureEntry(InternalModel):
    """One fixture file and where its bytes came from."""

    file: Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]+/[a-z0-9._-]+$")]
    source_id: SourceId
    adapter: str
    mode: ReadMode
    url: Annotated[str, StringConstraints(pattern=r"^https?://")]
    captured_at: UtcInstant
    archive_url: Annotated[str, StringConstraints(pattern=r"^https://web\.archive\.org/")] | None
    retrieved_at: UtcInstant
    original_sha256: Sha256
    original_bytes: Count
    slice: str
    sha256: Sha256
    bytes: Count
    expected: Expected
    note: str = ""


_ENTRIES = TypeAdapter(list[FixtureEntry])


def slice_body(method: str, body: bytes) -> bytes:
    """Return ``body`` cut down with the named method."""
    return SLICERS[method](body)


def load_entries(folder: Path) -> list[FixtureEntry]:
    """Read ``PROVENANCE.json`` from a fixtures folder (empty when there is none)."""
    path = folder / PROVENANCE_FILE
    if not path.is_file():
        return []
    return _ENTRIES.validate_json(path.read_bytes())


def expected_from(adapter: str, body: bytes) -> Expected:
    """Run ``adapter`` over ``body`` and describe what it read."""
    listing = ADAPTERS[adapter](body)
    return Expected(
        variant=listing.variant,
        state=listing.state,
        rows=len(listing.rows),
        names=tuple(row.name for row in listing.rows),
    )


@dataclass(frozen=True, slots=True)
class Origin:
    """Where a fixture's original bytes came from."""

    source_id: str
    adapter: str
    mode: ReadMode
    url: str
    captured_at: str
    archive_url: str | None
    retrieved_at: str


def make_entry(
    file: str, origin: Origin, original: bytes, method: str, note: str = ""
) -> tuple[FixtureEntry, bytes]:
    """Slice ``original`` and describe the fixture it becomes.

    Raises :class:`ValueError` when the slice does not read as the original does
    (same variant, state and row names), so a fixture never pins a result the
    real page would not give.
    """
    sliced = slice_body(method, original)
    expected = expected_from(origin.adapter, sliced)
    if expected_from(origin.adapter, original) != expected:
        raise ValueError(f"{file}: the {method} slice does not read as the original does")
    entry = FixtureEntry.model_validate(
        {
            "file": file,
            "source_id": origin.source_id,
            "adapter": origin.adapter,
            "mode": origin.mode,
            "url": origin.url,
            "captured_at": origin.captured_at,
            "archive_url": origin.archive_url,
            "retrieved_at": origin.retrieved_at,
            "original_sha256": hashlib.sha256(original).hexdigest(),
            "original_bytes": len(original),
            "slice": method,
            "sha256": hashlib.sha256(sliced).hexdigest(),
            "bytes": len(sliced),
            "expected": expected,
            "note": note,
        }
    )
    return entry, sliced


def write_fixtures(folder: Path, entries: Sequence[tuple[FixtureEntry, bytes]]) -> None:
    """Add or replace fixtures, then rewrite ``PROVENANCE.json`` and ``README.md``."""
    current = {entry.file: entry for entry in load_entries(folder)}
    for entry, body in entries:
        write_bytes_atomic(folder / entry.file, body)
        current[entry.file] = entry
    ordered = [current[name] for name in sorted(current)]
    data = [entry.model_dump(mode="json") for entry in ordered]
    text = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    write_bytes_atomic(folder / PROVENANCE_FILE, text.encode("utf-8"))
    write_bytes_atomic(folder / README_FILE, render_readme(ordered, folder).encode("utf-8"))


def _other_sections(folder: Path | None) -> list[str]:
    """Tables for the robots.txt and reference-file fixtures, from their own provenance."""
    if folder is None:
        return []
    lines: list[str] = []
    robots = folder / "robots" / "PROVENANCE.robots.json"
    if robots.is_file():
        lines += [
            "",
            "## robots.txt files (`robots/`)",
            "",
            "Verbatim bodies, read live (robots.txt is always allowed to be read).",
            "",
            "| File | URL | Retrieved (UTC) | HTTP | SHA-256 |",
            "|---|---|---|---:|---|",
        ]
        for name, entry in sorted(json.loads(robots.read_text(encoding="utf-8")).items()):
            lines.append(
                f"| `robots/{name}` | {entry['url']} | {entry['retrieved_at']}"
                f" | {entry['http_status']} | `{entry['sha256'][:16]}…` |"
            )
    reference = folder / "reference" / "PROVENANCE.json"
    if reference.is_file():
        lines += [
            "",
            "## Reference files (`reference/`)",
            "",
            "| File | URL | Retrieved (UTC) | Original SHA-256 | Slice |",
            "|---|---|---|---|---|",
        ]
        for name, entry in sorted(json.loads(reference.read_text(encoding="utf-8")).items()):
            lines.append(
                f"| `reference/{name}` | {entry['url']} | {entry['retrieved_at']}"
                f" | `{entry['original_sha256'][:16]}…` | {entry['slice']} |"
            )
    return lines


def render_readme(entries: Sequence[FixtureEntry], folder: Path | None = None) -> str:
    """Render the fixtures README from the provenance records in ``folder``."""
    lines = [
        "# Station adapter fixtures",
        "",
        "Every file here is real. Archived pages are Wayback Machine `id_` captures (the",
        "bytes the station served when the archive read the page), downloaded on GitHub's",
        "runners by `.github/workflows/archive-captures.yml`. The original SHA-256 is of",
        "the bytes as the archive sent them (a page the station served gzip-encoded is",
        "still gzip). Pages are sliced to the parts the adapter reads with the method",
        "named below (`snowlight.sources.stations.fixtures.slice_body`); to check a",
        "fixture, download the capture URL without decoding it, confirm the original",
        "SHA-256, slice it, and compare the bytes. Full SHA-256 values and the exact",
        "names the adapter reads are in `PROVENANCE.json`.",
        "",
        "Live fixtures (marked live) are bodies `snowlight stations fetch` read from the",
        "station's server with the project's User-Agent (the list file the station's page",
        "loads, as a browser check of the page recorded in the registry's `page_check`),",
        "and were cut with `snowlight stations fixture add-live`. Gray's and Hearst's terms",
        "forbid reading their sites with software; the terms are recorded in",
        "`pipeline/config/sources/` with the project owner's decisions to read the closings",
        "lists anyway (terms: 2026-09-25; robots.txt, whose verdict on each URL is recorded",
        "in the registry and in every read's health: 2026-09-26). A live body cannot be",
        "downloaded again as it was: its SHA-256 is the one the fetch's run manifest recorded.",
        "",
        "This file is generated from the provenance files; edit those, not this.",
        "",
        "## Adapter fixtures",
        "",
        "| File | Source | URL | Captured (UTC) | Retrieved (UTC) | Original SHA-256 | Slice"
        " | Variant | State | Rows |",
        "|---|---|---|---|---|---|---|---|---|---:|",
    ]
    for entry in entries:
        archive = f" ([capture]({entry.archive_url}))" if entry.archive_url else ""
        lines.append(
            f"| `{entry.file}` | {entry.source_id} ({entry.mode.value}) | {entry.url}{archive}"
            f" | {entry.captured_at:%Y-%m-%d %H:%M:%S} | {entry.retrieved_at:%Y-%m-%d %H:%M:%S}"
            f" | `{entry.original_sha256[:16]}…` ({entry.original_bytes} bytes) | {entry.slice}"
            f" | {entry.expected.variant} | {entry.expected.state.value}"
            f" | {entry.expected.rows} |"
        )
    notes = [entry for entry in entries if entry.note]
    if notes:
        lines += ["", "Notes:", ""]
        lines += [f"- `{entry.file}`: {entry.note}" for entry in notes]
    lines += _other_sections(folder)
    return "\n".join(lines) + "\n"
