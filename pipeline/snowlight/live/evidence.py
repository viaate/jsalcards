"""The evidence store: every finished live morning record kept for good (advisory-sane L0).

The state folder keeps the newest 45 days of the morning record (:mod:`snowlight.live.morning`)
and the change log (:mod:`snowlight.live.history`), which is what ``predict learn`` reads.
What the live reader saw on a morning cannot be read again later, so every finished day is
also copied here, append-only, and kept forever: the reads, the named and withheld sets per
30-minute slot, the change log of what the map lit, and the weather-class snapshots the labels
are counted under (the predict state's, with the district table each one indexes). Codes,
ids, counts and times only, as in the files themselves: nothing personal, no names, no list
text.

**Where.** Two D1 databases of the owner's Cloudflare account, reached with the same
``CLOUDFLARE_API_TOKEN`` and ``CLOUDFLARE_ACCOUNT_ID`` as the state (:mod:`snowlight.live.d1`):
:data:`PRIMARY` and its backup :data:`BACKUP`. No Worker is bound to either, so the public
site cannot serve them and nothing on the internet reaches them. They are not the state
database: resetting the state (or losing it) leaves the evidence as it was. Each push writes
both, and copies across whatever one holds and the other lacks (a database lost or recreated
is filled again from the other). D1's own Time Travel restores either to any minute of its
retention window.

**Tables.** ``items(kind, key, sha256, bytes, packed, parts, codec, kept_at, run_id)``: one row
per version of a file, ``kind`` one of :data:`KINDS` and ``key`` its day (or, for
``districts``, the directory content it names); ``parts(sha256, n, data)``: its bytes, xz
compressed (:data:`CODEC`), 64 KiB a part as base64. Content addressed: a version is its
sha256, so the same bytes are stored once and a file that changed after it was kept is kept
again beside the first version. The store sends only its own fixed statements
(:data:`STATEMENTS`): there is no ``UPDATE``, ``DELETE`` or ``DROP`` among them, so nothing
kept here is ever changed or removed by the pipeline. Parts go first and are read back and
checked against the version's sha256 and size; only then is its item row written. So an item
row means its parts were read back whole, and that is what the live reader asks before a
morning day leaves its state folder (:meth:`EvidenceStore.held`, :mod:`snowlight.live.kept`).

**What is final.** A morning day (UTC) once :data:`MORNING_SETTLE` has passed after it ends;
a change-log day (local) :data:`CHANGES_SETTLE_DAYS` days after it (its statuses leave the
map, and the day file is written for the last time, within the 3 days the fold reads); a
snapshot day once every zone's 21:00 the evening before has passed, :data:`SNAPSHOT_SETTLE`
after the UTC day it serves begins.

**Budget.** A push writes at most :data:`MAX_ROWS` rows to each database, of the account's
100,000 a day (the state's pushes keep to 30,000, :data:`snowlight.live.d1.WRITE_CAP`). A
finished day is a few rows, so a day's pushes write tens of rows; the first push after this
store lands takes in the 45 days the folder holds.
"""

import base64
import hashlib
import logging
import lzma
import math
import re
import tarfile
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final

import httpx

from snowlight.live.d1 import Answer, CloudflareD1, D1Api, D1Error, Secrets, Statement
from snowlight.live.kept import (
    CHANGES_SETTLE_DAYS,
    MORNING_SETTLE,
    SNAPSHOT_SETTLE,
    canonical,
    held_versions,
    table_bytes,
)
from snowlight.output import write_bytes_atomic

LOG: Final = logging.getLogger(__name__)

PRIMARY: Final = "snowlight-evidence"
BACKUP: Final = "snowlight-evidence-backup"
DATABASES: Final = (PRIMARY, BACKUP)
MORNING: Final = "morning"
CHANGES: Final = "changes"
SNAPSHOT: Final = "snapshot"
DISTRICTS: Final = "districts"
LABELS: Final = "labels"
"""``learn.json``, every version (key ``learn``): the labels the model learned from."""
TRIALS: Final = "trials"
AUDIT: Final = "audit"
"""The live labels' co-listing trials and read audit (advisory-sane L1), one version a day."""
KINDS: Final = (MORNING, CHANGES, SNAPSHOT, DISTRICTS, LABELS, TRIALS, AUDIT)
WRITERS: Final[Mapping[str, frozenset[str]]] = {
    "live-read": frozenset({MORNING, CHANGES}),
    "predict": frozenset({SNAPSHOT, DISTRICTS, LABELS, TRIALS, AUDIT}),
}
"""The kinds each workflow (``GITHUB_WORKFLOW``) may write: only the live reader's evidence job
holds the morning record and change log, and only the predict chain the snapshots, district
tables and labels."""
CODEC: Final = "xz"
PART_BYTES: Final = 64 * 1024
"""Compressed bytes per part (87,384 base64 characters, under D1's 100 KB statement)."""
WRITE_BATCH: Final = 8
READ_BATCH: Final = 16
MAX_ROWS: Final = 1_000
"""Rows one push may write to each database."""
WARN_BYTES: Final = 300 * 1024 * 1024
"""Stored bytes past which a push warns: D1's smallest per-database limit is 500 MB (the free
plan's); the projection for 10 winters is about 210 MB, 460 MB at the worst measured
(docs/live.md, The evidence)."""
DAY_FILE: Final = re.compile(r"(\d{4}-\d{2}-\d{2})\.(?:json|jsonl)")
KEY: Final = re.compile(r"[0-9A-Za-z][0-9A-Za-z./:_-]{0,127}")

DDL: Final = (
    "CREATE TABLE IF NOT EXISTS items (kind TEXT NOT NULL, key TEXT NOT NULL,"
    " sha256 TEXT NOT NULL, bytes INTEGER NOT NULL, packed INTEGER NOT NULL,"
    " parts INTEGER NOT NULL, codec TEXT NOT NULL, kept_at TEXT NOT NULL, run_id TEXT,"
    " PRIMARY KEY (kind, key, sha256)) WITHOUT ROWID",
    "CREATE TABLE IF NOT EXISTS parts (sha256 TEXT NOT NULL, n INTEGER NOT NULL,"
    " data TEXT NOT NULL, PRIMARY KEY (sha256, n)) WITHOUT ROWID",
)
_ITEMS: Final = (
    "SELECT kind, key, sha256, bytes, packed, parts, codec, kept_at FROM items"
    " WHERE kind = ? ORDER BY key, kept_at"
)
_PUT_PART: Final = (
    "INSERT INTO parts (sha256, n, data) VALUES (?, ?, ?) ON CONFLICT (sha256, n) DO NOTHING"
)
_PUT_ITEM: Final = (
    "INSERT INTO items (kind, key, sha256, bytes, packed, parts, codec, kept_at, run_id)"
    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (kind, key, sha256) DO NOTHING"
)
_PARTS: Final = "SELECT n, data FROM parts WHERE sha256 = ? AND n >= ? AND n < ? ORDER BY n"
_HELD: Final = "SELECT kind, key, sha256 FROM items WHERE kind = ? AND key >= ? ORDER BY key"
_SIZE: Final = (
    "SELECT kind, COUNT(*) AS items, SUM(bytes) AS bytes, SUM(packed) AS packed FROM items"
    " GROUP BY kind ORDER BY kind"
)
STATEMENTS: Final = frozenset({*DDL, _ITEMS, _PUT_PART, _PUT_ITEM, _PARTS, _SIZE, _HELD})
"""Every statement the store sends; nothing else is ever sent (none changes or removes a row)."""


class EvidenceError(D1Error):
    """The evidence store could not be read or written (codes and HTTP status only)."""


@dataclass(frozen=True, slots=True)
class Item:
    """One kept version of a file."""

    kind: str
    key: str
    sha256: str
    bytes: int
    packed: int
    parts: int
    codec: str = CODEC
    kept_at: str = ""

    @property
    def version(self) -> tuple[str, str, str]:
        return self.kind, self.key, self.sha256


@dataclass(frozen=True, slots=True)
class Offer:
    """A finished file offered to the store: its kind, key and bytes."""

    kind: str
    key: str
    data: bytes = field(repr=False)


def compress(data: bytes) -> bytes:
    """The stored form: xz, the same bytes for the same input."""
    return lzma.compress(data, format=lzma.FORMAT_XZ, preset=6)


def item_of(offer: Offer, kept_at: str) -> tuple[Item, list[str]]:
    """The item row and base64 parts of ``offer`` (compressed here: only for a version some
    database lacks, :meth:`EvidenceStore.push`)."""
    packed = compress(offer.data)
    parts = [
        base64.b64encode(packed[start : start + PART_BYTES]).decode("ascii")
        for start in range(0, len(packed), PART_BYTES)
    ] or [""]
    item = Item(
        kind=offer.kind,
        key=offer.key,
        sha256=hashlib.sha256(offer.data).hexdigest(),
        bytes=len(offer.data),
        packed=len(packed),
        parts=len(parts),
        kept_at=kept_at,
    )
    return item, parts


def unpack(item: Item, parts: Sequence[str]) -> bytes:
    """The file's bytes from its parts, checked against the item.

    Raises:
        EvidenceError: a part is missing, or the bytes do not match the item.
    """
    if len(parts) != item.parts or item.codec != CODEC:
        raise EvidenceError(f"{item.kind} {item.key}: parts missing")
    try:
        packed = b"".join(base64.b64decode(part, validate=True) for part in parts)
        data = lzma.decompress(packed, format=lzma.FORMAT_XZ)
    except (ValueError, lzma.LZMAError) as error:
        raise EvidenceError(f"{item.kind} {item.key}: {type(error).__name__}") from error
    if len(packed) != item.packed or len(data) != item.bytes:
        raise EvidenceError(f"{item.kind} {item.key}: another size")
    if hashlib.sha256(data).hexdigest() != item.sha256:
        raise EvidenceError(f"{item.kind} {item.key}: another sha256")
    return data


# --- what is final --------------------------------------------------------------------------


def _day_files(folder: Path) -> list[tuple[date, Path]]:
    found: list[tuple[date, Path]] = []
    if folder.is_dir():
        for path in folder.iterdir():
            match = DAY_FILE.fullmatch(path.name)
            if match is None or not path.is_file():
                continue
            try:
                found.append((date.fromisoformat(match.group(1)), path))
            except ValueError:
                continue
    return sorted(found)


def finished(kind: str, day: date, now: datetime) -> bool:
    """Whether a morning-record or change-log day is final (see the module)."""
    at = now.astimezone(UTC)
    if kind == MORNING:
        return day < (at - MORNING_SETTLE).date()
    return day < at.date() - timedelta(days=CHANGES_SETTLE_DAYS - 1)


_SUFFIX: Final = {MORNING: ".json", CHANGES: ".jsonl"}
EXPORT_DAY: Final = re.compile(r"(morning|changes)/(\d{4}-\d{2}-\d{2})\.(jsonl?)")


def state_offers(state: Path, now: datetime) -> list[Offer]:
    """The finished morning-record and change-log days of the live state folder."""
    offers: list[Offer] = []
    for kind in (MORNING, CHANGES):
        for day, path in _day_files(state / kind):
            if path.suffix == _SUFFIX[kind] and finished(kind, day, now):
                offers.append(Offer(kind, day.isoformat(), path.read_bytes()))
    return offers


def export_offers(archive: Path, now: datetime) -> list[Offer]:
    """The finished morning-record and change-log days of a live-state export (the archive
    live-read.yml saves to the Actions cache, :func:`snowlight.live.state.export`), read from
    the archive itself: nothing is unpacked, and no other name is read.

    Raises:
        OSError, tarfile.TarError: the archive does not read.
    """
    offers: list[Offer] = []
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            match = EXPORT_DAY.fullmatch(member.name)
            if match is None or not member.isfile():
                continue
            kind, key, ext = match.groups()
            try:
                day = date.fromisoformat(key)
            except ValueError:
                continue
            if f".{ext}" != _SUFFIX[kind] or not finished(kind, day, now):
                continue
            handle = tar.extractfile(member)
            if handle is not None:
                offers.append(Offer(kind, key, handle.read()))
    return sorted(offers, key=lambda offer: (offer.kind, offer.key))


def snapshot_offers(
    snapshots: Mapping[str, object],
    districts: Mapping[str, Sequence[str]],
    now: datetime,
) -> list[Offer]:
    """The finished weather-class snapshots of the predict state (one per school day, as
    key-sorted JSON), and every district table ``districts`` holds (LEAIDs in table order,
    one a line), keyed by its directory content: a content's table is kept while it is
    deployed, before any snapshot indexed under it settles."""
    at = now.astimezone(UTC)
    offers: list[Offer] = []
    for key, entry in sorted(snapshots.items()):
        try:
            day = date.fromisoformat(key)
        except ValueError:
            continue
        begins = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
        if at < begins + SNAPSHOT_SETTLE or not isinstance(entry, dict):
            continue
        offers.append(Offer(SNAPSHOT, key, canonical(entry)))
    for content, table in sorted(districts.items()):
        if KEY.fullmatch(content):
            offers.append(Offer(DISTRICTS, content, table_bytes(table)))
    return offers


# --- the store ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PushReport:
    """What a push did to one database (counts and sizes only)."""

    database: str
    held: int
    """Versions it held before."""
    kept: int
    """Versions written and read back whole."""
    copied: int
    """Of those, versions copied from the other database."""
    rows_written: int
    bytes: int
    """Raw bytes of the versions written."""
    left: int = 0
    """Versions that wait for a later push (the row budget)."""
    stored: int | None = None
    """What the database holds in all, every kind, as stored (base64 text), when it read."""

    @property
    def full(self) -> bool:
        """Whether it holds more than :data:`WARN_BYTES` (time to plan the next database)."""
        return self.stored is not None and self.stored > WARN_BYTES


@dataclass(slots=True)
class EvidenceDatabase:
    """One evidence database (see the module)."""

    api: D1Api
    name: str
    _id: str | None = None
    rows_written: int = 0

    def lookup(self) -> str | None:
        """Its id, found by its exact name; ``None`` when the list answered and names none
        (nothing is created)."""
        if self._id is not None:
            return self._id
        found = [uuid for name, uuid in self.api.databases(self.name) if name == self.name]
        if len(found) > 1:
            raise EvidenceError(f"the account lists {self.name} more than once")
        self._id = found[0] if found else None
        return self._id

    def database(self) -> str:
        """Its id, found by its exact name; created only when the list answered and names
        none."""
        if self._id is not None:
            return self._id
        found = self.lookup()
        self._id = found if found is not None else self.api.create(self.name)
        self.run([(sql, ()) for sql in DDL])
        return self._id

    def run(self, statements: Sequence[Statement]) -> list[Answer]:
        for sql, _ in statements:
            if sql not in STATEMENTS:  # pragma: no cover - a programming error
                raise EvidenceError("refused a statement the store does not own")
        database = self._id if self._id is not None else self.database()
        answers = self.api.run(database, statements)
        if len(answers) != len(statements):
            raise EvidenceError("the answer holds another number of results")
        self.rows_written += sum(answer.rows_written for answer in answers)
        return answers

    def items(self, kinds: Iterable[str]) -> list[Item]:
        """Every kept version of ``kinds``."""
        self.database()
        found: list[Item] = []
        for kind in kinds:
            for row in self.run([(_ITEMS, (kind,))])[0].rows:
                found.append(
                    Item(
                        kind=str(row["kind"]),
                        key=str(row["key"]),
                        sha256=str(row["sha256"]),
                        bytes=int(row["bytes"]),
                        packed=int(row["packed"]),
                        parts=int(row["parts"]),
                        codec=str(row["codec"]),
                        kept_at=str(row["kept_at"]),
                    )
                )
        return found

    def parts(self, item: Item) -> list[str]:
        """The item's parts, in order."""
        self.database()
        found: dict[int, str] = {}
        for start in range(0, item.parts, READ_BATCH):
            stop = min(item.parts, start + READ_BATCH)
            for row in self.run([(_PARTS, (item.sha256, start, stop))])[0].rows:
                found[int(row["n"])] = str(row["data"])
        return [found[n] for n in range(item.parts) if n in found]

    def read(self, item: Item) -> bytes:
        """The item's bytes, checked (:func:`unpack`)."""
        return unpack(item, self.parts(item))

    def held(self, kinds: Iterable[str], since: str = "") -> list[tuple[str, str, str]]:
        """``(kind, key, sha256)`` of every version of ``kinds`` with a key from ``since``,
        read only: a database the account does not list holds nothing (it is not created).
        An item row means its parts were read back whole (:meth:`write_item`)."""
        if self.lookup() is None:
            return []
        found: list[tuple[str, str, str]] = []
        for kind in kinds:
            for row in self.run([(_HELD, (kind, since))])[0].rows:
                found.append((str(row["kind"]), str(row["key"]), str(row["sha256"])))
        return found

    def write_parts(self, item: Item, parts: Sequence[str]) -> None:
        """The parts (``DO NOTHING`` when already there)."""
        self.database()
        rows: list[Statement] = [
            (_PUT_PART, (item.sha256, n, data)) for n, data in enumerate(parts)
        ]
        for start in range(0, len(rows), WRITE_BATCH):
            self.run(rows[start : start + WRITE_BATCH])

    def write_item(self, item: Item, run_id: str | None) -> None:
        """The item row (``DO NOTHING`` when already there): written only once its parts
        read back whole."""
        self.database()
        self.run(
            [
                (
                    _PUT_ITEM,
                    (
                        item.kind,
                        item.key,
                        item.sha256,
                        item.bytes,
                        item.packed,
                        item.parts,
                        item.codec,
                        item.kept_at,
                        run_id,
                    ),
                )
            ]
        )

    def size(self) -> list[dict[str, object]]:
        """Per kind: versions kept, raw bytes and compressed bytes."""
        self.database()
        return [dict(row) for row in self.run([(_SIZE, ())])[0].rows]


def _rows_of(item: Item) -> int:
    return item.parts + 1


@dataclass(slots=True)
class _Tally:
    rows: int = 0
    kept: int = 0
    copied: int = 0
    bytes: int = 0
    left: int = 0


def _stored(database: "EvidenceDatabase") -> int | None:
    """The stored size of every kind in ``database`` (base64 text), ``None`` if it does not
    read."""
    try:
        rows = database.size()
    except D1Error:
        return None
    return sum(math.ceil(int(str(row.get("packed") or 0)) * 4 / 3) for row in rows)


@dataclass(slots=True)
class _Run:
    """One push's progress."""

    run_id: str | None
    stop: float | None
    held: dict[str, dict[tuple[str, str, str], Item]] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    tally: dict[str, _Tally] = field(default_factory=dict)

    def fail(self, database: "EvidenceDatabase", error: Exception) -> None:
        self.errors[database.name] = str(error)
        LOG.warning("evidence: %s: %s", database.name, error)

    def reports(self, databases: Sequence["EvidenceDatabase"]) -> list["PushReport"]:
        """What each database that did not fail did.

        Raises:
            EvidenceError: every database failed.
            PartialPushError: one did.
        """
        found = [
            PushReport(
                database=d.name,
                held=len(self.held[d.name]) - self.tally[d.name].kept,
                kept=self.tally[d.name].kept,
                copied=self.tally[d.name].copied,
                rows_written=self.tally[d.name].rows,
                bytes=self.tally[d.name].bytes,
                left=self.tally[d.name].left,
                stored=_stored(d),
            )
            for d in databases
            if d.name in self.held and d.name not in self.errors
        ]
        message = "; ".join(f"{name}: {why}" for name, why in self.errors.items())
        if not found:
            raise EvidenceError(message or "no evidence database")
        if self.errors:
            raise PartialPushError(found, message)
        return found


@dataclass(slots=True)
class EvidenceStore:
    """Both evidence databases (see the module). One per process."""

    api: D1Api
    env: Mapping[str, str]
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    names: Sequence[str] = DATABASES
    max_rows: int = MAX_ROWS
    seconds: float | None = None
    """How long a push may take in all (``None``: no limit)."""
    monotonic: Callable[[], float] = time.monotonic
    _databases: list[EvidenceDatabase] = field(default_factory=list)

    def databases(self) -> list[EvidenceDatabase]:
        if not self._databases:
            self._databases = [EvidenceDatabase(self.api, name) for name in self.names]
        return self._databases

    def _writable(self, kinds: Iterable[str]) -> None:
        workflow = self.env.get("GITHUB_WORKFLOW", "")
        allowed = WRITERS.get(workflow, frozenset())
        refused = sorted(set(kinds) - allowed)
        if refused:
            raise EvidenceError(f"a {workflow or 'local'} run does not keep {', '.join(refused)}")

    def push(self, offers: Sequence[Offer], kinds: Iterable[str]) -> list[PushReport]:
        """Keep every offer in both databases, and copy across what one holds and the other
        lacks (of ``kinds``), version by version into every database that lacks it, until the
        row budget or :attr:`seconds` runs out (the rest waits for the next push). Versions
        are told apart by their sha256 first: only a version some database lacks is
        compressed, and the time budget starts once both have been listed. A database that
        fails is reported, and the other is still written; a kept version that does not read
        back whole is never copied, and gets no item row.

        Raises:
            EvidenceError: this workflow may not write ``kinds``, or no database was written.
        """
        kinds = tuple(sorted(set(kinds) | {offer.kind for offer in offers}))
        self._writable(kinds)
        kept_at = self.clock().astimezone(UTC).isoformat()
        run = _Run(run_id=self.env.get("GITHUB_RUN_ID") or None, stop=None)
        databases = self.databases()
        for database in databases:
            try:
                run.held[database.name] = {item.version: item for item in database.items(kinds)}
            except D1Error as error:
                run.fail(database, error)
        offered: dict[tuple[str, str, str], Offer] = {}
        for offer in offers:
            version = (offer.kind, offer.key, hashlib.sha256(offer.data).hexdigest())
            offered.setdefault(version, offer)
        run.tally = {name: _Tally() for name in run.held}
        if self.seconds is not None:
            run.stop = self.monotonic() + self.seconds
        # offers first, then each version only another database holds
        for version, offer in sorted(offered.items()):
            if self._lacking(run, databases, version):
                item, parts = item_of(offer, kept_at)
                self._keep(run, databases, item, parts, copied=False)
        for name in sorted(run.held):
            for version, item in sorted(run.held[name].items()):
                if version in offered or not self._lacking(run, databases, version):
                    continue
                if self._late(run):
                    for database in self._lacking(run, databases, version):
                        run.tally[database.name].left += 1
                    continue
                source = next(d for d in databases if d.name == name)
                try:
                    parts = source.parts(item)
                    unpack(item, parts)
                except D1Error as error:
                    LOG.warning("evidence: %s %s in %s: %s", item.kind, item.key, name, error)
                    continue
                self._keep(run, databases, item, parts, copied=True)
        return run.reports(databases)

    def _late(self, run: "_Run") -> bool:
        return run.stop is not None and self.monotonic() >= run.stop

    def _lacking(
        self, run: "_Run", databases: Sequence[EvidenceDatabase], version: tuple[str, str, str]
    ) -> list[EvidenceDatabase]:
        return [
            d
            for d in databases
            if d.name in run.held and d.name not in run.errors and version not in run.held[d.name]
        ]

    def _keep(
        self,
        run: "_Run",
        databases: Sequence[EvidenceDatabase],
        item: Item,
        parts: Sequence[str],
        *,
        copied: bool,
    ) -> None:
        """Write ``item``'s parts into every database that lacks it, read them back, and
        only then its item row; count it."""
        for database in self._lacking(run, databases, item.version):
            count = run.tally[database.name]
            if self._late(run) or count.rows + _rows_of(item) > self.max_rows:
                count.left += 1
                continue
            before = database.rows_written
            try:
                database.write_parts(item, parts)
                database.read(item)  # read back whole before its item row is written
                database.write_item(item, run.run_id)
            except D1Error as error:
                run.fail(database, error)
                continue
            finally:
                count.rows += database.rows_written - before
            run.held[database.name][item.version] = item
            count.kept += 1
            count.copied += copied
            count.bytes += item.bytes

    def held(
        self, kinds: Iterable[str], since: str = "", *, seconds: float | None = None
    ) -> dict[str, dict[tuple[str, str], frozenset[str]]]:
        """Per database that answered, the ``(kind, key)`` versions (sha256s) it holds whole
        (read only; nothing is created). A database that fails is left out (logged).
        ``seconds``: how long the whole question may take, shared between the databases: each
        gets an even share of the time left when it is asked (at least 1 s), so a slow or
        silent first database never starves the second of its answer.

        Raises:
            EvidenceError: no database answered.
        """
        found: dict[str, dict[tuple[str, str], frozenset[str]]] = {}
        errors: list[str] = []
        wanted = tuple(kinds)
        databases = self.databases()
        api: object = self.api
        timed = seconds is not None and hasattr(api, "deadline") and hasattr(api, "monotonic")
        previous = getattr(api, "deadline", None)
        clock: Callable[[], float] = getattr(api, "monotonic", self.monotonic)
        end = clock() + (seconds or 0.0)
        try:
            for index, database in enumerate(databases):
                if timed:
                    share = max(0.0, end - clock()) / (len(databases) - index)
                    setattr(api, "deadline", clock() + max(1.0, share))  # noqa: B010
                try:
                    found[database.name] = held_versions(database.held(wanted, since))
                except D1Error as error:
                    errors.append(f"{database.name}: {error}")
                    LOG.warning("evidence: %s: %s", database.name, error)
        finally:
            if timed:
                setattr(api, "deadline", previous)  # noqa: B010
        if not found:
            raise EvidenceError("; ".join(errors) or "no evidence database")
        return found

    def versions(
        self, kind: str, since: date | None = None
    ) -> dict[str, list[tuple[EvidenceDatabase, Item]]]:
        """Every kept version of every key of ``kind`` (from ``since``), newest first, in
        every database that answered.

        Raises:
            EvidenceError: no database could be read.
        """
        found: dict[str, list[tuple[EvidenceDatabase, Item]]] = {}
        errors: list[str] = []
        for database in self.databases():
            try:
                items = database.items([kind])
            except D1Error as error:
                errors.append(f"{database.name}: {error}")
                continue
            for item in items:
                if since is not None and kind != DISTRICTS and item.key < since.isoformat():
                    continue
                found.setdefault(item.key, []).append((database, item))
        if errors and len(errors) == len(self.databases()):
            raise EvidenceError("; ".join(errors))
        for choices in found.values():
            choices.sort(key=lambda choice: choice[1].kept_at, reverse=True)
        return found

    def pull(self, kind: str, since: date | None = None) -> dict[str, bytes]:
        """The newest kept version of every key of ``kind`` (from ``since``) that reads back
        whole from some database; when none of the newest does, the next older one, with a
        warning naming the version used. A key kept in more than one version is named in a
        warning too (:meth:`pull_all` reads them all).

        Raises:
            EvidenceError: no database could be read.
        """
        found: dict[str, bytes] = {}
        for key, choices in sorted(self.versions(kind, since).items()):
            digests = {item.sha256 for _, item in choices}
            if len(digests) > 1:
                LOG.warning("evidence: %s %s is kept in %d versions", kind, key, len(digests))
            newest = choices[0][1].sha256
            for database, item in choices:
                try:
                    found[key] = database.read(item)
                except D1Error as error:
                    LOG.warning("evidence: %s %s in %s: %s", kind, key, database.name, error)
                    continue
                if item.sha256 != newest:
                    LOG.warning(
                        "evidence: %s %s: the newest version does not read; %s (kept %s) used",
                        kind,
                        key,
                        item.sha256[:12],
                        item.kept_at,
                    )
                break
        return found

    def pull_all(self, kind: str, since: date | None = None) -> dict[tuple[str, str], bytes]:
        """Every kept version of every key of ``kind``, as ``(key, sha256)``, each from the
        first database it reads back whole from.

        Raises:
            EvidenceError: no database could be read.
        """
        found: dict[tuple[str, str], bytes] = {}
        for key, choices in sorted(self.versions(kind, since).items()):
            for database, item in choices:
                if (key, item.sha256) in found:
                    continue
                try:
                    found[key, item.sha256] = database.read(item)
                except D1Error as error:
                    LOG.warning("evidence: %s %s in %s: %s", kind, key, database.name, error)
        return found

    def size(self) -> dict[str, list[dict[str, object]]]:
        """Per database, per kind: versions, raw and stored bytes."""
        return {database.name: database.size() for database in self.databases()}


class PartialPushError(EvidenceError):
    """One database was written and another was not."""

    def __init__(self, reports: Sequence[PushReport], message: str) -> None:
        super().__init__(message)
        self.reports = tuple(reports)


def make_store(env: Mapping[str, str], client: httpx.Client) -> EvidenceStore:
    """Both databases over the Cloudflare API with the environment's secrets.

    Raises:
        D1Error: the secrets are missing.
    """
    return EvidenceStore(CloudflareD1(client, Secrets.from_env(env)), env)


EXTENSIONS: Final[Mapping[str, str]] = {
    MORNING: ".json",
    CHANGES: ".jsonl",
    SNAPSHOT: ".json",
    DISTRICTS: ".txt",
    LABELS: ".json",
    TRIALS: ".jsonl",
    AUDIT: ".json",
}


def write_pulled(
    found: Mapping[str, bytes] | Mapping[tuple[str, str], bytes], kind: str, out: Path
) -> list[Path]:
    """``out/<kind>/<key>.<ext>`` for each pulled file (a private folder); for every version
    (:meth:`EvidenceStore.pull_all`), ``<key>.<sha256 prefix>.<ext>``."""
    ext = EXTENSIONS[kind]
    written: list[Path] = []
    for name, data in sorted(found.items()):
        key, digest = name if isinstance(name, tuple) else (name, "")
        stem = key if kind != DISTRICTS else hashlib.sha256(key.encode()).hexdigest()[:16]
        tail = f".{digest[:12]}" if digest else ""
        path = out / kind / f"{stem}{tail}{ext}"
        write_bytes_atomic(path, data)
        written.append(path)
    return written
