"""Merging the live reads of several ``stations fetch`` runs into one evidence folder.

``stations coverage`` reads one live-reads file (``--live-reads``) and the
``rows.jsonl`` beside it (the district-notice gate looks a proof's rows up there).
A station's list seen populated by an earlier fetch stays proven after a later
fetch finds it empty, so the earlier run's reads are merged with the new ones
before coverage is measured:

* identical reads (same source, URL and read time) are kept once;
* for each source and URL the newest read is kept, and also, of the older reads that
  were populated, the newest of each body (SHA-256) not already kept (the evidence
  the proven share cites: a district's alert channel that showed "STISD Weather
  Update: All STISD activities for Saturday, Oct. 3, have been canceled" on
  2026-10-05 and only an enrollment notice on 2026-10-13 was populated both times,
  and only the first read proves it, which the notice gate decides); older reads of
  the URL are dropped;
* the rows kept are those of the kept populated reads (rows are matched to a
  read by source and read time, the way the notice gate matches them), each
  distinct row once.

Health files may be merged too (``--health``): a fetch of a few stations only
(``stations fetch --only``, say for sources added after the full fetch) gives their
health beside the full run's. For each source the entry read last is kept;
``generated_at`` and ``stale_before`` are the latest of the inputs', and the totals
are counted again. Only the health files named are merged, so an earlier run's
health never stands in for a source today's runs did not read.

Written (internal, never published) to the output folder: ``reads.jsonl``,
``rows.jsonl`` (the formats ``stations fetch`` writes), ``health.json`` (with
``--health``) and ``merge.json``::

    {"generated_at", "inputs": [{"reads": {"path", "sha256", "count"},
                                 "rows": {"path", "sha256", "count"} | null}, ...],
     "reads": {"kept", "dropped_older", "duplicates", "kept_as_proof"},
     "rows": {"kept", "duplicates"},
     "health": {"inputs": [{"path", "sha256", "count"}, ...], "sources"} | null}
"""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from snowlight.output import JSONValue, write_bytes_atomic, write_json
from snowlight.sources.stations.fetch import totals
from snowlight.sources.stations.http import iso_utc
from snowlight.sources.stations.model import ListingRead, ListingState, RawRow, SourceHealth

MERGE_FILE = "merge.json"
_READ = TypeAdapter(ListingRead)
_ROW = TypeAdapter(RawRow)


class MergeError(ValueError):
    """A reads or rows file does not have the shape ``stations fetch`` writes."""


@dataclass(frozen=True, slots=True)
class LiveRun:
    """One fetch run's reads and rows, with the files they came from."""

    reads_path: Path
    reads: tuple[ListingRead, ...]
    rows_path: Path | None
    rows: tuple[RawRow, ...]


@dataclass(slots=True)
class Merged:
    """The merged reads and rows, and what the merge kept and dropped."""

    reads: list[ListingRead] = field(default_factory=list)
    rows: list[RawRow] = field(default_factory=list)
    duplicate_reads: int = 0
    dropped_older: int = 0
    kept_as_proof: int = 0
    duplicate_rows: int = 0


def _parse[T](path: Path, adapter: TypeAdapter[T]) -> list[T]:
    items: list[T] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            items.append(adapter.validate_json(line))
        except ValidationError as error:
            raise MergeError(f"{path}:{number}: {error}") from error
    return items


def load_run(reads_path: Path) -> LiveRun:
    """Read one run's ``reads.jsonl`` and the ``rows.jsonl`` beside it (if any)."""
    reads = _parse(reads_path, _READ)
    rows_path = reads_path.with_name("rows.jsonl")
    if not rows_path.is_file():
        return LiveRun(reads_path, tuple(reads), None, ())
    return LiveRun(reads_path, tuple(reads), rows_path, tuple(_parse(rows_path, _ROW)))


def merge_runs(runs: Sequence[LiveRun]) -> Merged:
    """Merge the runs' reads and rows (see the module docstring)."""
    merged = Merged()
    by_key: dict[tuple[str, str, datetime], ListingRead] = {}
    for run in runs:
        for read in run.reads:
            key = (read.source_id, read.url, read.fetched_at)
            if key in by_key:
                merged.duplicate_reads += 1
                continue
            by_key[key] = read
    by_url: dict[tuple[str, str], list[ListingRead]] = {}
    for read in by_key.values():
        by_url.setdefault((read.source_id, read.url), []).append(read)
    kept: list[ListingRead] = []
    for reads in by_url.values():
        reads.sort(key=lambda read: read.fetched_at)
        newest = reads[-1]
        chosen = [newest]
        bodies = {newest.sha256} if newest.state is ListingState.POPULATED else set()
        for read in reversed(reads[:-1]):
            if read.state is ListingState.POPULATED and read.sha256 not in bodies:
                chosen.insert(0, read)
                bodies.add(read.sha256)
                merged.kept_as_proof += 1
        merged.dropped_older += len(reads) - len(chosen)
        kept.extend(chosen)
    kept.sort(key=lambda read: (read.source_id, read.fetched_at, read.url))
    merged.reads = kept
    wanted = {
        (read.source_id, read.fetched_at) for read in kept if read.state is ListingState.POPULATED
    }
    seen: set[str] = set()
    for run in runs:
        for row in run.rows:
            if (row.source_id, row.fetched_at) not in wanted:
                continue
            text = row.model_dump_json()
            if text in seen:
                merged.duplicate_rows += 1
                continue
            seen.add(text)
            merged.rows.append(row)
    merged.rows.sort(key=lambda row: (row.source_id, row.fetched_at))
    return merged


@dataclass(frozen=True, slots=True)
class HealthRun:
    """One fetch run's ``health.json``."""

    path: Path
    generated_at: str
    stale_before: str
    sources: tuple[SourceHealth, ...]


def load_health(path: Path) -> HealthRun:
    """Read one ``health.json`` written by ``stations fetch``."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        sources = [SourceHealth.model_validate_json(json.dumps(item)) for item in data["sources"]]
        return HealthRun(path, str(data["generated_at"]), str(data["stale_before"]), tuple(sources))
    except (ValueError, KeyError, TypeError) as error:
        raise MergeError(f"{path}: {error}") from error


def merge_health(runs: Sequence[HealthRun]) -> dict[str, JSONValue]:
    """Each source's health entry read last across ``runs`` (later files win ties)."""
    latest: dict[str, SourceHealth] = {}
    for run in runs:
        for entry in run.sources:
            kept = latest.get(entry.source_id)
            if kept is None or entry.checked_at >= kept.checked_at:
                latest[entry.source_id] = entry
    sources = [latest[source] for source in sorted(latest)]
    return {
        "generated_at": max(run.generated_at for run in runs),
        "stale_before": max(run.stale_before for run in runs),
        "sources": [entry.model_dump(mode="json") for entry in sources],
        "totals": dict(totals(sources)),
    }


def _file(path: Path, count: int) -> dict[str, JSONValue]:
    return {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "count": count,
    }


def write_merged(
    out_dir: Path,
    runs: Sequence[LiveRun],
    merged: Merged,
    generated_at: datetime,
    health: Sequence[HealthRun] = (),
) -> dict[str, Path]:
    """Write ``reads.jsonl``, ``rows.jsonl``, ``health.json`` (with ``health``) and
    ``merge.json``; return their paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "reads": out_dir / "reads.jsonl",
        "rows": out_dir / "rows.jsonl",
        "merge": out_dir / MERGE_FILE,
    }
    if health:
        paths["health"] = out_dir / "health.json"
    outputs = {path.resolve() for path in paths.values()}
    sources = [path for run in runs for path in (run.reads_path, run.rows_path)]
    for source in [*sources, *(run.path for run in health)]:
        if source is not None and source.resolve() in outputs:
            raise MergeError(f"{source}: the output folder holds an input; pick another")
    write_bytes_atomic(
        paths["reads"],
        b"".join(read.model_dump_json().encode("utf-8") + b"\n" for read in merged.reads),
    )
    write_bytes_atomic(
        paths["rows"],
        b"".join(row.model_dump_json().encode("utf-8") + b"\n" for row in merged.rows),
    )
    inputs: list[JSONValue] = [
        {
            "reads": _file(run.reads_path, len(run.reads)),
            "rows": _file(run.rows_path, len(run.rows)) if run.rows_path is not None else None,
        }
        for run in runs
    ]
    record: dict[str, JSONValue] = {
        "generated_at": iso_utc(generated_at),
        "inputs": inputs,
        "reads": {
            "kept": len(merged.reads),
            "dropped_older": merged.dropped_older,
            "duplicates": merged.duplicate_reads,
            "kept_as_proof": merged.kept_as_proof,
        },
        "rows": {"kept": len(merged.rows), "duplicates": merged.duplicate_rows},
        "health": None,
    }
    if health:
        table = merge_health(health)
        write_json(paths["health"], table)
        record["health"] = {
            "inputs": [_file(run.path, len(run.sources)) for run in health],
            "sources": len(table["sources"]) if isinstance(table["sources"], list) else 0,
        }
    write_json(paths["merge"], record)
    return paths


def summary(merged: Merged) -> str:
    """One line on what the merge kept."""
    return (
        f"{len(merged.reads)} reads kept ({merged.kept_as_proof} older populated reads kept "
        f"as proof beside a newer read of another body; {merged.dropped_older} older reads and "
        f"{merged.duplicate_reads} duplicates dropped); {len(merged.rows)} rows"
    )
