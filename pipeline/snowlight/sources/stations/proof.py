"""Proven coverage: stations whose list has been seen populated at least once.

A list that answers but has never been seen holding a row may not be one anyone
uses (Utah counted as covered only through a page that was empty whenever it
was read). The *proven* share counts a working station only when a read of its
list held at least one row: live, in an archived Wayback capture, or in a
committed test fixture (a real live or archived body; its provenance is in the
fixture folder's ``PROVENANCE.json``). The evidence per station is the read with
the most rows among those of its current list, else among all its reads:

* ``current`` is true when the read is of the list the station's registry entry
  reads today: the read's URL (or a page it was reached through) is the station's
  ``page_url`` or ``data_url`` (compared with :func:`~snowlight.sources.stations.archive.url_key`,
  so ``?_renderer=json`` or ``wp-json`` forms of the same page do not count as the
  same address unless registered). Only proofs of the current list make a station
  proven; an older list file seen populated (a Tribune-era frame, say) is kept as
  evidence but does not.
* ``capture_url`` is the Wayback link of an archived read
  (``https://web.archive.org/web/<timestamp>/<url>``); a live read has none.

For each working station without such a proof, ``checked`` says what was looked
at: its live reads, the archived captures read (with their states) and those
that failed (with the reason, such as a capture the archive answered 403 for or
never downloaded), and the fixtures that hold its bodies.

Written into ``coverage.json`` (internal, never published) by
:func:`add_proven`::

    "proven": {"national": Share, "states": {"AL": Share, ...},
               "stations": {"working": n, "proven": n, "unproven": n},
               "evidence": {"archive_reads": {"path", "sha256", "reads"} | null,
                            "archive_health": {...} | null, "live_reads": {...} | null,
                            "fixtures": [{"path", "sha256", "entries"}, ...]}},
    "unproven": [{"id", "checked": {...}}, ...],
    "stations": {id: {..., "proof": null | {"mode", "url", "capture_url", "captured_at",
                                            "rows", "sha256", "variant", "basis",
                                            "current"}}}

(``Share`` as in :mod:`~snowlight.sources.stations.coverage`, with its ``weighted``
part when closure weights are given.)
"""

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import polars as pl
from pydantic import TypeAdapter, ValidationError

from snowlight.output import JSONValue
from snowlight.sources.stations.archive import url_key
from snowlight.sources.stations.coverage import (
    CoverageError,
    StationState,
    Weights,
    measure,
)
from snowlight.sources.stations.fixtures import FixtureEntry
from snowlight.sources.stations.http import iso_utc
from snowlight.sources.stations.model import (
    ListingRead,
    ListingState,
    ReadMode,
    SourceHealth,
)
from snowlight.sources.stations.registry import Registry, Station

WAYBACK = "https://web.archive.org/web/"
PROVENANCE_FILE = "PROVENANCE.json"
CHECKED_LIMIT = 40
"""At most this many reads of each kind are listed in ``checked`` (the counts are complete)."""


class ProofError(ValueError):
    """An evidence file does not have the shape its writer gives it."""


@dataclass(frozen=True, slots=True)
class Proof:
    """One read of a station's list that held rows."""

    source_id: str
    mode: str
    url: str
    captured_at: datetime
    rows: int
    sha256: str
    variant: str
    basis: str
    """Where the read is recorded: ``live reads``, ``archive reads`` or ``fixture <file>``."""
    via: tuple[str, ...] = ()

    @property
    def capture_url(self) -> str | None:
        """The Wayback link of an archived read."""
        if self.mode != ReadMode.ARCHIVE.value:
            return None
        return f"{WAYBACK}{self.captured_at:%Y%m%d%H%M%S}/{self.url}"

    def current(self, station: Station) -> bool:
        """Whether this is a read of the list the station's entry reads today."""
        own = {url_key(url) for url in (station.page_url, station.data_url) if url}
        return any(url_key(url) in own for url in (self.url, *self.via))

    def as_json(self, station: Station) -> dict[str, JSONValue]:
        """The evidence as ``coverage.json`` records it."""
        return {
            "mode": self.mode,
            "url": self.url,
            "capture_url": self.capture_url,
            "captured_at": iso_utc(self.captured_at),
            "rows": self.rows,
            "sha256": self.sha256,
            "variant": self.variant,
            "basis": self.basis,
            "current": self.current(station),
        }


@dataclass(slots=True)
class Evidence:
    """Every populated read, and what else was checked, per station."""

    proofs: dict[str, list[Proof]] = field(default_factory=lambda: defaultdict(list))
    checked: dict[str, dict[str, list[dict[str, JSONValue]]]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(list))
    )
    files: dict[str, JSONValue] = field(default_factory=dict)

    def best(self, station: Station) -> Proof | None:
        """The proof with the most rows, of the current list when there is one."""
        found = self.proofs.get(station.id, [])
        if not found:
            return None
        current = [proof for proof in found if proof.current(station)]
        pool = current or found
        return max(pool, key=lambda proof: (proof.rows, proof.captured_at))


_READS = TypeAdapter(ListingRead)
_ENTRIES = TypeAdapter(list[FixtureEntry])


def _record(path: Path, count: int) -> dict[str, JSONValue]:
    return {
        "path": path.as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "entries": count,
    }


def read_reads(path: Path) -> list[ListingRead]:
    """Read a ``reads.jsonl`` written by ``stations fetch`` or ``stations archive parse``."""
    reads = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            reads.append(_READS.validate_json(line))
        except ValidationError as error:
            raise ProofError(f"{path}:{number}: {error}") from error
    return reads


def read_health(path: Path) -> list[SourceHealth]:
    """Read the sources of a ``health.json``."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [SourceHealth.model_validate_json(json.dumps(item)) for item in data["sources"]]
    except (ValueError, KeyError, TypeError) as error:
        raise ProofError(f"{path}: {error}") from error


def fixture_entries(root: Path) -> list[tuple[Path, list[FixtureEntry]]]:
    """Every fixture provenance file under ``root`` that lists fixture entries."""
    found = []
    for path in sorted(root.rglob(PROVENANCE_FILE)):
        data = json.loads(path.read_text(encoding="utf-8"))
        # Reference files (DMA lists, robots.txt) keep other provenance records.
        if not isinstance(data, list) or not all(
            isinstance(item, dict) and "expected" in item for item in data
        ):
            continue
        try:
            found.append((path, _ENTRIES.validate_json(path.read_bytes())))
        except ValidationError as error:
            raise ProofError(f"{path}: {error}") from error
    return found


def _add_reads(evidence: Evidence, reads: Iterable[ListingRead], basis: str) -> None:
    for read in reads:
        kind = "live" if read.mode is ReadMode.LIVE else "archived"
        if read.state is ListingState.POPULATED and read.rows > 0:
            evidence.proofs[read.source_id].append(
                Proof(
                    source_id=read.source_id,
                    mode=read.mode.value,
                    url=read.url,
                    captured_at=read.fetched_at,
                    rows=read.rows,
                    sha256=read.sha256,
                    variant=read.variant,
                    basis=basis,
                    via=tuple(page.url for page in read.via),
                )
            )
        evidence.checked[read.source_id][kind].append(
            {"captured_at": iso_utc(read.fetched_at), "url": read.url, "state": read.state.value}
        )


def _add_failures(evidence: Evidence, health: Iterable[SourceHealth]) -> None:
    for entry in health:
        if entry.status.value in {"ok", "empty"}:
            continue
        evidence.checked[entry.source_id]["archive_failures"].append(
            {"captured_at": iso_utc(entry.checked_at), "url": entry.url, "reason": entry.reason}
        )


def _add_fixtures(
    evidence: Evidence, root: Path, folders: Sequence[tuple[Path, list[FixtureEntry]]]
) -> None:
    for path, entries in folders:
        for entry in entries:
            evidence.checked[entry.source_id]["fixtures"].append(
                {
                    "file": entry.file,
                    "state": entry.expected.state.value,
                    "rows": entry.expected.rows,
                }
            )
            if entry.expected.state is not ListingState.POPULATED or entry.expected.rows == 0:
                continue
            evidence.proofs[entry.source_id].append(
                Proof(
                    source_id=entry.source_id,
                    mode=entry.mode.value,
                    url=entry.url,
                    captured_at=entry.captured_at,
                    rows=entry.expected.rows,
                    sha256=entry.original_sha256,
                    variant=entry.expected.variant,
                    basis=f"fixture {path.parent.relative_to(root).as_posix() or '.'}/{entry.file}",
                )
            )


def gather(
    *,
    live_reads: Path | None,
    archive_reads: Path | None,
    archive_health: Path | None,
    fixtures: Path | None,
) -> Evidence:
    """Collect the evidence from whichever of the files exist."""
    evidence = Evidence()
    for key, path, basis in (
        ("live_reads", live_reads, "live reads"),
        ("archive_reads", archive_reads, "archive reads"),
    ):
        if path is not None and path.is_file():
            reads = read_reads(path)
            _add_reads(evidence, reads, basis)
            evidence.files[key] = _record(path, len(reads))
        else:
            evidence.files[key] = None
    if archive_health is not None and archive_health.is_file():
        health = read_health(archive_health)
        _add_failures(evidence, health)
        evidence.files["archive_health"] = _record(archive_health, len(health))
    else:
        evidence.files["archive_health"] = None
    folders = fixture_entries(fixtures) if fixtures is not None and fixtures.is_dir() else []
    if fixtures is not None:
        _add_fixtures(evidence, fixtures, folders)
    evidence.files["fixtures"] = [_record(path, len(entries)) for path, entries in folders]
    return evidence


def _checked(evidence: Evidence, station_id: str) -> dict[str, JSONValue]:
    found = evidence.checked.get(station_id, {})
    summary: dict[str, JSONValue] = {}
    for kind in ("live", "archived", "archive_failures", "fixtures"):
        items = found.get(kind, [])
        summary[kind] = {"count": len(items), "items": list(items[:CHECKED_LIMIT])}
    return summary


def add_proven(  # noqa: PLR0913 - the measure's own inputs, and the evidence
    result: dict[str, JSONValue],
    registry: Registry,
    schools: pl.DataFrame,
    states: Mapping[str, StationState],
    evidence: Evidence,
    *,
    weights: Weights | None = None,
) -> None:
    """Add the proven share, each station's evidence and the unproven list to ``result``.

    The proven share is the coverage measure again, counting only the working
    stations with a proof of their current list.
    """
    stations = result.get("stations")
    if not isinstance(stations, dict):
        raise CoverageError("coverage result has no station table")
    proven_states: dict[str, StationState] = {}
    unproven: list[JSONValue] = []
    counts = {"working": 0, "proven": 0, "unproven": 0}
    for station in sorted(registry.stations.values(), key=lambda item: item.id):
        state = states[station.id]
        best = evidence.best(station)
        entry = stations.get(station.id)
        if isinstance(entry, dict):
            entry["proof"] = best.as_json(station) if best is not None else None
        proven_states[station.id] = state
        if state.state != "working":
            continue
        counts["working"] += 1
        if best is not None and best.current(station):
            counts["proven"] += 1
            continue
        counts["unproven"] += 1
        proven_states[station.id] = StationState("unproven", "never seen populated")
        unproven.append({"id": station.id, "checked": _checked(evidence, station.id)})
    shares = measure(registry, schools, proven_states, None, weights=weights)
    result["proven"] = {
        "national": shares["national"],
        "states": shares["states"],
        "stations": dict(counts),
        "evidence": dict(evidence.files),
    }
    result["unproven"] = unproven


def summary_line(result: Mapping[str, JSONValue]) -> str | None:
    """One line on the proven share, for the command's output (None without it)."""
    proven = result.get("proven")
    national = proven.get("national") if isinstance(proven, dict) else None
    if not isinstance(proven, dict) or not isinstance(national, dict):
        return None
    line = f"proven (lists seen with rows): {float(str(national['share'])):.1%}"
    weighted = national.get("weighted")
    if isinstance(weighted, dict):
        line += f", closure-weighted {float(str(weighted['share'])):.1%}"
    counts = proven.get("stations")
    if isinstance(counts, dict):
        line += f"; {counts.get('proven')} of {counts.get('working')} working stations proven"
    return line
