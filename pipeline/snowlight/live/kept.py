"""What the evidence store is known to hold: ``kept.json`` in the live state folder.

The evidence store (:mod:`snowlight.live.evidence`) keeps every finished morning-record and
change-log day for good, written by a job of its own after each reader job. The reader never
writes it, but it must know what it holds: a morning day leaves the state folder (after
:data:`snowlight.live.morning.KEEP_DAYS` days, or past the record's size valve) only once a
database holds that day's file whole, byte for byte. So the loop asks both databases, in its
idle time, which versions they hold (:meth:`EvidenceStore.held`) and writes the answer here:
per kind and day, the sha256 of the state folder's file and the databases that hold exactly
it. The file travels with the state (it is packed and pushed, never exported).

A finished day that no answer has shown kept in every database for :data:`GRACE` (from the
day's end, or from the first check, whichever is later) opens the ``evidence`` alert, and so
does a day the size valve had to drop before any database held it (:func:`note_dropped`,
an ``::error::`` line too). Codes, days, digests and database names only.
"""

import hashlib
import json
import logging
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final

from snowlight.output import JSONValue, dumps_json, write_bytes_atomic

LOG: Final = logging.getLogger(__name__)
KEPT: Final = "kept.json"
SCHEMA_VERSION: Final = 1
MORNING: Final = "morning"
CHANGES: Final = "changes"
KINDS: Final = (MORNING, CHANGES)
SUFFIX: Final[Mapping[str, str]] = {MORNING: ".json", CHANGES: ".jsonl"}
DATABASES: Final = ("snowlight-evidence", "snowlight-evidence-backup")
"""The evidence databases (:data:`snowlight.live.evidence.DATABASES`)."""
MORNING_SETTLE: Final = timedelta(hours=2)
"""A morning day (UTC) is final this long after it ends (the evidence store's rule)."""
CHANGES_SETTLE_DAYS: Final = 4
"""A change-log day (local) is final this many days after it."""
GRACE: Final = timedelta(days=2)
"""How long a finished day may wait for a copy in every database before the alert opens."""
DROPPED_FOR: Final = timedelta(days=7)
"""How long the alert stays open after the valve dropped a day no database held."""


def sha256_of(path: Path) -> str | None:
    """The file's sha256, ``None`` when it does not read."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


@dataclass(frozen=True, slots=True)
class Copy:
    """What the last answer said of one day's file."""

    sha256: str
    databases: tuple[str, ...]


@dataclass(slots=True)
class Kept:
    """``kept.json`` (see the module)."""

    watch_from: datetime | None = None
    """The first check this state folder had: the grace counts from it."""
    checked: datetime | None = None
    """The last check every database answered (``None``: none yet)."""
    copies: dict[str, dict[str, Copy]] = field(default_factory=dict)
    """Kind to day (ISO) to the copy."""
    dropped: dict[str, datetime] = field(default_factory=dict)
    """Morning days the size valve dropped with no copy anywhere, and when."""

    def holds(self, kind: str, day: date, path: Path) -> bool:
        """Whether some database holds exactly the bytes of ``path`` (the day's file now)."""
        copy = self.copies.get(kind, {}).get(day.isoformat())
        return copy is not None and bool(copy.databases) and sha256_of(path) == copy.sha256

    def to_bytes(self) -> bytes:
        copies: dict[str, JSONValue] = {
            kind: {
                day: {
                    "sha256": copy.sha256,
                    "databases": list[JSONValue](copy.databases),
                }
                for day, copy in sorted(days.items())
            }
            for kind, days in sorted(self.copies.items())
        }
        return dumps_json(
            {
                "schema_version": SCHEMA_VERSION,
                "watch_from": _iso(self.watch_from),
                "checked": _iso(self.checked),
                "copies": copies,
                "dropped": {day: _iso(at) for day, at in sorted(self.dropped.items())},
            }
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> "Kept":
        """Raises:
        ValueError: ``data`` is not a ``kept.json``."""
        try:
            body = json.loads(data)
            if body["schema_version"] != SCHEMA_VERSION:
                raise ValueError("another schema")
            copies = {
                str(kind): {
                    str(day): Copy(
                        str(copy["sha256"]), tuple(str(name) for name in copy["databases"])
                    )
                    for day, copy in dict(days).items()
                }
                for kind, days in dict(body["copies"]).items()
            }
            dropped = {
                str(day): datetime.fromisoformat(str(at))
                for day, at in dict(body["dropped"]).items()
            }
            return cls(
                watch_from=_when(body["watch_from"]),
                checked=_when(body["checked"]),
                copies=copies,
                dropped=dropped,
            )
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError(type(error).__name__) from error


def _iso(moment: datetime | None) -> str | None:
    return None if moment is None else moment.astimezone(UTC).isoformat()


def _when(value: object) -> datetime | None:
    return None if value is None else datetime.fromisoformat(str(value))


def read_kept(state: Path) -> Kept:
    """The state folder's ``kept.json``; an empty one when it is missing or does not read
    (then nothing is known kept, and nothing is pruned)."""
    try:
        return Kept.from_bytes((state / KEPT).read_bytes())
    except (OSError, ValueError):
        return Kept()


def write_kept(state: Path, kept: Kept) -> None:
    state.mkdir(parents=True, exist_ok=True)
    write_bytes_atomic(state / KEPT, kept.to_bytes())


def day_files(state: Path, kind: str) -> dict[date, Path]:
    """The day files of ``kind`` in the state folder."""
    folder = state / kind
    found: dict[date, Path] = {}
    if folder.is_dir():
        for path in folder.glob(f"*{SUFFIX[kind]}"):
            try:
                found[date.fromisoformat(path.name.removesuffix(SUFFIX[kind]))] = path
            except ValueError:
                continue
    return found


def finished_at(kind: str, day: date) -> datetime:
    """When a day of ``kind`` is final (the evidence store offers it from then on)."""
    start = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    if kind == MORNING:
        return start + timedelta(days=1) + MORNING_SETTLE
    return start + timedelta(days=CHANGES_SETTLE_DAYS)


def merge_answer(
    before: Mapping[str, Mapping[str, Copy]],
    held: Mapping[str, Mapping[tuple[str, str], frozenset[str]]],
    digests: Mapping[str, Mapping[str, str]],
    databases: Sequence[str] = DATABASES,
) -> dict[str, dict[str, Copy]]:
    """The copies after one answer, for the files ``digests`` names (kind to key to the
    sha256 of the file now; a key no longer there is forgotten). A database that answered
    (it is in ``held``) holds a file when it holds that exact sha256; one that did not answer
    keeps what was known of it, as long as the file's sha256 is the one it was known to
    hold."""
    copies: dict[str, dict[str, Copy]] = {}
    for kind, keys in sorted(digests.items()):
        for key, digest in sorted(keys.items()):
            earlier = before.get(kind, {}).get(key)
            known = earlier.databases if earlier is not None and earlier.sha256 == digest else ()
            names = tuple(
                name
                for name in databases
                if (digest in held[name].get((kind, key), ()) if name in held else name in known)
            )
            copies.setdefault(kind, {})[key] = Copy(digest, names)
    return copies


def record_answer(
    state: Path,
    held: Mapping[str, Mapping[tuple[str, str], frozenset[str]]] | None,
    now: datetime,
) -> Kept:
    """Fold one check into ``kept.json`` and return it. ``held``: per database that answered,
    the ``(kind, day)`` versions (sha256s) it holds; ``None`` when no database answered (the
    copies stay as they were). A database missing from ``held`` (it did not answer) changes
    nothing known of it (:func:`merge_answer`): a check that fails changes nothing it knew."""
    kept = read_kept(state)
    if kept.watch_from is None:
        kept.watch_from = now
    if held is not None:
        digests: dict[str, dict[str, str]] = {}
        for kind in KINDS:
            for day, path in sorted(day_files(state, kind).items()):
                digest = sha256_of(path)
                if digest is not None:
                    digests.setdefault(kind, {})[day.isoformat()] = digest
        kept.copies = merge_answer(kept.copies, held, digests)
        if set(held) >= set(DATABASES):
            kept.checked = now
    kept.dropped = {day: at for day, at in kept.dropped.items() if now - at < DROPPED_FOR}
    write_kept(state, kept)
    return kept


@dataclass(frozen=True, slots=True)
class Verdict:
    """The ``evidence`` alert's state after a check."""

    active: bool
    why: str = ""
    count: int = 0


def verdict(state: Path, kept: Kept, now: datetime) -> Verdict:
    """Open while the valve dropped a day no database held (in the last
    :data:`DROPPED_FOR`), or while a finished day of the state folder has waited more than
    :data:`GRACE` for a copy in every database."""
    if kept.dropped:
        return Verdict(True, "dropped", len(kept.dropped))
    start = kept.watch_from or now
    late = 0
    for kind in KINDS:
        for day, path in day_files(state, kind).items():
            if now < max(finished_at(kind, day), start) + GRACE:
                continue
            copy = kept.copies.get(kind, {}).get(day.isoformat())
            whole = copy is not None and set(copy.databases) == set(DATABASES)
            if not whole or copy is None or sha256_of(path) != copy.sha256:
                late += 1
    return Verdict(late > 0, "unkept" if late else "", late)


def note_dropped(state: Path, days: Iterable[date], now: datetime) -> None:
    """Record days the size valve dropped with no copy in any database (they are gone for
    good), with one ``::error::`` line each."""
    found = list(days)
    if not found:
        return
    kept = read_kept(state)
    for day in found:
        kept.dropped[day.isoformat()] = now
        LOG.error("morning record: %s dropped with no copy in the evidence store", day)
        sys.stdout.write(
            f"::error::The morning record of {day.isoformat()} was dropped from the state"
            " folder before the evidence store held it (docs/live.md, The evidence).\n"
        )
    sys.stdout.flush()
    try:
        write_kept(state, kept)
    except OSError as error:
        LOG.error("kept.json: %s", type(error).__name__)


def held_versions(
    rows: Sequence[tuple[str, str, str]],
) -> dict[tuple[str, str], frozenset[str]]:
    """``(kind, key, sha256)`` rows as ``(kind, key)`` to the sha256s held."""
    found: dict[tuple[str, str], set[str]] = {}
    for kind, key, digest in rows:
        found.setdefault((kind, key), set()).add(digest)
    return {key: frozenset(digests) for key, digests in found.items()}


# --- the predict state's record of its snapshots and district tables ---------------------------

SNAPSHOT: Final = "snapshot"
DISTRICTS: Final = "districts"
SNAPSHOT_SETTLE: Final = timedelta(hours=12)
"""A snapshot day is final this long after the UTC day it serves begins: 21:00 the evening
before in every US zone (Hawaii's is 07:00 UTC) has passed by then."""
PREDICT_KEEP_DAYS: Final = 45
"""Days the predict state keeps a snapshot whatever the evidence store holds (past what
``predict learn`` reads back, 44); an older one leaves it only once a database holds it."""


def canonical(value: object) -> bytes:
    """A snapshot as the evidence store keeps it: key-sorted, compact JSON."""
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def snapshot_sha256(entry: object) -> str:
    """The sha256 of a snapshot as kept (:func:`canonical`)."""
    return hashlib.sha256(canonical(entry)).hexdigest()


def table_bytes(table: Sequence[str]) -> bytes:
    """A district table as kept: its LEAIDs in table order, one a line."""
    return "".join(f"{leaid}\n" for leaid in table).encode()


def snapshot_finished(day: date, now: datetime) -> datetime | None:
    """When a snapshot day is final (``None``: not yet at ``now``)."""
    at = datetime.combine(day, datetime.min.time(), tzinfo=UTC) + SNAPSHOT_SETTLE
    return at if now >= at else None


@dataclass(slots=True)
class PredictKept:
    """The ``evidence`` entry of the predict state: what the evidence databases are known to
    hold of its weather-class snapshots (per day: the sha256 of the snapshot as kept, and the
    databases that hold exactly it) and of the district tables they index (per directory
    content: the databases that hold its table; a content's table is one set of bytes).
    Written by ``predict evidence`` after each push; read by the passes, which let a snapshot
    older than :data:`PREDICT_KEEP_DAYS` go only once a database holds it and its table."""

    watch_from: datetime | None = None
    """The first check: the grace of a day finished before it counts from it."""
    snapshots: dict[str, Copy] = field(default_factory=dict)
    tables: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def snapshot_held(self, day: str, entry: object, every: bool = False) -> bool:
        """Whether a database (``every``: each one) holds exactly this snapshot."""
        copy = self.snapshots.get(day)
        if copy is None or copy.sha256 != snapshot_sha256(entry):
            return False
        return set(copy.databases) >= set(DATABASES) if every else bool(copy.databases)

    def table_held(self, content: str, every: bool = False) -> bool:
        """Whether a database (``every``: each one) holds the district table of ``content``."""
        names = self.tables.get(content, ())
        return set(names) >= set(DATABASES) if every else bool(names)

    def as_json(self) -> dict[str, object]:
        return {
            "watch_from": _iso(self.watch_from),
            "snapshots": {
                day: {"sha256": copy.sha256, "databases": list(copy.databases)}
                for day, copy in sorted(self.snapshots.items())
            },
            "tables": {content: list(names) for content, names in sorted(self.tables.items())},
        }

    @classmethod
    def of(cls, value: object) -> "PredictKept":
        """The entry as kept; an empty one when it is missing or does not read (then nothing
        is known held, and no old snapshot leaves the state)."""
        try:
            body = dict(value)  # type: ignore[call-overload]
            snapshots = {
                str(day): Copy(str(copy["sha256"]), tuple(str(n) for n in copy["databases"]))
                for day, copy in dict(body.get("snapshots") or {}).items()
            }
            tables = {
                str(content): tuple(str(n) for n in names)
                for content, names in dict(body.get("tables") or {}).items()
            }
            return cls(_when(body.get("watch_from")), snapshots, tables)
        except (KeyError, TypeError, ValueError, AttributeError):
            return cls()


def fold_predict(
    before: PredictKept,
    held: Mapping[str, Mapping[tuple[str, str], frozenset[str]]],
    snapshots: Mapping[str, object],
    contents: Iterable[str],
) -> PredictKept:
    """``before`` with one answer of the databases (as :func:`record_answer`: a database
    missing from ``held`` keeps what was known of it, while the snapshot is the same) for the
    snapshots the state holds now and the district tables of ``contents``; days and contents
    no longer there are forgotten."""
    digests = {SNAPSHOT: {day: snapshot_sha256(entry) for day, entry in snapshots.items()}}
    copies = merge_answer({SNAPSHOT: before.snapshots}, held, digests).get(SNAPSHOT, {})
    tables: dict[str, tuple[str, ...]] = {}
    for content in sorted(set(contents)):
        tables[content] = tuple(
            name
            for name in DATABASES
            if (
                any(key == (DISTRICTS, content) for key in held[name])
                if name in held
                else name in before.tables.get(content, ())
            )
        )
    return PredictKept(before.watch_from, copies, tables)


def contents_of(snapshots: Mapping[str, object]) -> set[str]:
    """The directory contents the snapshots index."""
    return {
        str(entry["content"])
        for entry in snapshots.values()
        if isinstance(entry, dict) and "content" in entry
    }


def predict_verdict(known: PredictKept, snapshots: Mapping[str, object], now: datetime) -> Verdict:
    """Open while a finished snapshot of the state (or the district table it indexes) has
    waited more than :data:`GRACE` (from its settling, or from the first check, whichever is
    later) for a copy in every database."""
    start = known.watch_from or now
    late = 0
    for key, entry in snapshots.items():
        try:
            finished = snapshot_finished(date.fromisoformat(key), now)
        except ValueError:
            continue
        if finished is None or now < max(finished, start) + GRACE:
            continue
        content = str(entry.get("content", "")) if isinstance(entry, dict) else ""
        if not known.snapshot_held(key, entry, every=True) or not known.table_held(
            content, every=True
        ):
            late += 1
    return Verdict(late > 0, "unkept" if late else "", late)
