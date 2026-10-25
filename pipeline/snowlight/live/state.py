"""The live ingest's private state, and where it is kept between runs (spec 7.7, 9; S8-E).

The state folder holds what the ingest must not lose:

* ``ledger.sqlite``: the row ledger (keys, times, codes; no raw text; its ``meta`` row holds
  the secret the keys are made with, so it stays private);
* ``publish.json`` (one per prefix): the publisher's memory (the last stamp published, the
  gate's);
* ``changes/<day>.jsonl``: the change log of the live days (codes and times);
* ``morning/<day>.json``: the morning record for the automatic learning
  (:mod:`snowlight.live.morning`: reads, withheld states and named districts as counts, ids
  and codes);
* ``robots.json``: robots.txt verdicts (the fetch layer's); ``cadence.json``: each source's
  last pass and wait; ``pacer.json``: each pace key's last request start;
* ``unmatched.json``: the queue of listings the matcher did not accept. It holds the
  listings' names as the sources print them, so it is kept only in a private store.

Never packed (:data:`NEVER_PACKED`): ``d1.json`` (this run's D1 epoch) and ``pulse`` (the
loop's heartbeat for the watcher). Request bodies and validators, ``health.json`` and
``provenance.jsonl`` live elsewhere and never leave the runner.

A store packs the folder into one gzipped tar (:func:`pack`): files in a fixed order with
fixed times, so the same state is the same bytes, and the ledger copied through SQLite's
backup API under SQLite's own locks (:func:`_snapshot`) and checked with ``PRAGMA
quick_check``, so a store pushed while the ingest runs holds a consistent ledger;
:func:`check_packed` checks a pulled state the same way. :func:`unpack` extracts regular
files only, inside the folder. The packed state is at most :data:`BUDGET_BYTES` (16 MB);
over :data:`ALERT_BYTES` (12 MB) the ``state`` alert is raised.

* :class:`LocalStateStore`: a folder (the paid box, tests; ``out/internal/live/box``).
* :class:`~snowlight.live.d1.D1StateStore`: the private D1 database (the Actions loop).
* :class:`BucketStateStore`: a private bucket (Cloudflare R2), through the same SigV4
  client as the publisher, under ``state/`` keys only.

**The export** (:func:`export`): what ``predict learn`` reads, and the only part of the state
the Actions cache ever holds (the cache is readable by any pull-request run, so it counts as
public): ``morning/``, ``changes/`` and a schema-only ``ledger.sqlite`` (no ``meta`` row, no
``rows``, no ``derived``). :func:`check_export` refuses any other name. That is codes,
LEAIDs, NCES ids, registry ids, times and keyed row HMACs (not reversible without the
ledger's secret, which the export leaves out): no name, listing text or URL, but more than
the public day files show (docs/live.md, The state).
"""

import gzip
import io
import re
import sqlite3
import tarfile
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final, Protocol

import httpx

from snowlight.live.ledger import empty_ledger
from snowlight.live.publishers import Credentials, PublishError, R2Publisher
from snowlight.output import write_bytes_atomic

ARCHIVE: Final = "live-state.tar.gz"
CACHE_KEY_PREFIX: Final = "live-state-"
"""The Actions cache key prefix of the export's folder: live-read.yml saves
``out/internal/live/store`` (holding only :func:`export`'s archive) under
``live-state-<run id>``, and the predict workflow's learning step restores the newest such
key, read only (docs/live.md)."""
STATE_KEY: Final = f"state/{ARCHIVE}"
NEVER_PACKED: Final = frozenset({"d1.json", "pulse"})
"""Names that never leave the runner's state folder: this run's D1 epoch and the pulse."""
BUDGET_BYTES: Final = 16 * 1024 * 1024
"""The packed state is at most 16 MB (S8-E addendum, replacing spec 13's 50 MB)."""
ALERT_BYTES: Final = 12 * 1024 * 1024
"""Packed state over this raises the ``state`` alert."""
LEDGER: Final = "ledger.sqlite"
EXPORT_NAME: Final = re.compile(
    r"(?:ledger\.sqlite|morning/\d{4}-\d{2}-\d{2}\.json|changes/(?:\d{4}-\d{2}-\d{2}\.jsonl|durable\.json))"
)
"""The only names the export holds."""
_SQLITE: Final = ".sqlite"


class StateError(RuntimeError):
    """The state could not be pulled or pushed."""


def _include_all(_name: str) -> bool:
    return True


def _packable(name: str) -> bool:
    return PurePosixPath(name).name not in NEVER_PACKED


BUSY_SECONDS: Final = 30.0
"""How long a snapshot waits for a writer's lock (SQLite's busy timeout)."""


def _journal(path: Path) -> bool:
    journal = path.with_name(path.name + "-journal")
    return journal.is_file() and journal.stat().st_size > 0


def _backup(source: sqlite3.Connection, copy: Path) -> None:
    target = sqlite3.connect(copy)
    try:
        source.backup(target)  # all pages in one step, under the source's shared lock
    finally:
        source.close()
        target.close()


def sound(path: Path) -> bool:
    """Whether the SQLite file at ``path`` opens and passes ``PRAGMA quick_check``."""
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            rows = connection.execute("PRAGMA quick_check").fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return False
    return rows == [("ok",)]


def _snapshot(path: Path) -> bytes:
    """A consistent copy of a SQLite file, always through SQLite's own locks: a read-only
    connection's backup (consistent while another process writes the file), and, only when
    that fails beside a journal (a hot one a killed writer left mid-transaction: a read-only
    connection cannot roll it back), a read-write connection to the file itself, which rolls
    the journal back under SQLite's exclusive lock before the backup reads the last commit.
    The file and its journal are never copied by hand, so a live writer's pair is never
    caught half-written.

    Raises:
        StateError: the copy fails ``PRAGMA quick_check`` (nothing damaged is ever packed).
        sqlite3.Error: the file cannot be read (a lock held past :data:`BUSY_SECONDS`).
    """
    with tempfile.TemporaryDirectory() as scratch:
        copy = Path(scratch) / "copy.sqlite"
        try:
            _backup(sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=BUSY_SECONDS), copy)
        except sqlite3.Error:
            if not _journal(path):
                raise
            copy.unlink(missing_ok=True)
            _backup(sqlite3.connect(path, timeout=BUSY_SECONDS), copy)
        if not sound(copy):
            raise StateError(f"the copy of {path.name} fails its integrity check")
        return copy.read_bytes()


def check_packed(data: bytes) -> None:
    """Check a packed state before it is unpacked into the state folder: it reads as an
    archive of plain files and every SQLite file in it passes ``PRAGMA quick_check``.

    Raises:
        StateError: it does not, so the pull takes it as a slot that fails its sha256.
    """
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)
        for name in unpack(data, root):
            if name.endswith(_SQLITE) and not sound(root / name):
                raise StateError(f"the packed {name} fails its integrity check")


def pack(folder: Path, include: Callable[[str], bool] = _include_all) -> bytes:
    """The state folder as one gzipped tar, the same bytes for the same state."""
    buffer = io.BytesIO()
    with (
        gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as zipped,
        tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as tar,
    ):
        for path in sorted(folder.rglob("*")):
            name = path.relative_to(folder).as_posix()
            if (
                not path.is_file()
                or not include(name)
                or not _packable(name)
                or name.endswith((".tmp", "-journal"))
            ):
                continue
            data = _snapshot(path) if path.suffix == _SQLITE else path.read_bytes()
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode = len(data), 0, 0o600
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def unpack(data: bytes, folder: Path, include: Callable[[str], bool] = _include_all) -> list[str]:
    """Extract a packed state into ``folder``; returns the names written.

    Raises:
        StateError: the archive is damaged or holds anything but plain files inside
            the folder.
    """
    written: list[str] = []
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            members = tar.getmembers()
            for member in members:
                name = PurePosixPath(member.name)
                if (
                    not member.isfile()
                    or name.is_absolute()
                    or ".." in name.parts
                    or not member.name
                ):
                    raise StateError("the state archive holds something other than its files")
            for member in members:
                if not include(member.name):
                    continue
                handle = tar.extractfile(member)
                if handle is None:
                    raise StateError("the state archive holds an unreadable file")
                write_bytes_atomic(folder / member.name, handle.read())
                written.append(member.name)
    except (tarfile.TarError, OSError, EOFError) as error:
        raise StateError(f"the state archive does not read ({type(error).__name__})") from error
    return written


class StateStore(Protocol):
    """Where the state folder is kept between runs."""

    def pull(self, folder: Path) -> list[str]:
        """Restore the kept state into ``folder``; returns the names (none on a first run)."""
        ...

    def push(self, folder: Path) -> int:
        """Keep ``folder``'s state; returns the archive's size in bytes."""
        ...


@dataclass(frozen=True, slots=True)
class LocalStateStore:
    """Keeps the state as one archive in a folder."""

    root: Path
    include: Callable[[str], bool] = _include_all

    def pull(self, folder: Path) -> list[str]:
        path = self.root / ARCHIVE
        if not path.is_file():
            return []
        return unpack(path.read_bytes(), folder, self.include)

    def push(self, folder: Path) -> int:
        data = pack(folder, self.include)
        write_bytes_atomic(self.root / ARCHIVE, data)
        return len(data)


def _exported(name: str) -> bool:
    return EXPORT_NAME.fullmatch(name) is not None and name != LEDGER


def export(folder: Path) -> bytes:
    """The export of the state folder (see the module): ``morning/`` and ``changes/`` as they
    are, and a schema-only ``ledger.sqlite``, packed like :func:`pack`.

    Raises:
        OSError: the folder cannot be read.
    """
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)
        for path in sorted(folder.rglob("*")):
            name = path.relative_to(folder).as_posix()
            if path.is_file() and _exported(name):
                write_bytes_atomic(root / name, path.read_bytes())
        empty_ledger(root / LEDGER)
        data = pack(root)
    check_export(data)
    return data


def check_export(data: bytes) -> list[str]:
    """The names an export holds.

    Raises:
        StateError: it holds any other name, or a ledger with a secret, rows or derived
            payloads.
    """
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            members = tar.getmembers()
            names = [member.name for member in members]
            for member in members:
                if not member.isfile() or EXPORT_NAME.fullmatch(member.name) is None:
                    raise StateError("the export holds a file it must not")
            ledger = next((member for member in members if member.name == LEDGER), None)
            handle = None if ledger is None else tar.extractfile(ledger)
            if handle is None:
                raise StateError("the export holds no ledger")
            body = handle.read()
    except (tarfile.TarError, OSError, EOFError) as error:
        raise StateError(f"the export does not read ({type(error).__name__})") from error
    with tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / LEDGER
        path.write_bytes(body)
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            tables = [
                str(row[0])
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            ]
            filled = [
                table
                for table in tables
                if connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]  # noqa: S608
            ]
        finally:
            connection.close()
    if filled:
        raise StateError("the export's ledger holds rows")
    return names


def check_state_key(key: str) -> str:
    """Only ``state/`` keys are written to the private bucket."""
    if key != STATE_KEY:
        raise PublishError(f"refused state key {key!r}")
    return key


@dataclass(slots=True)
class BucketStateStore:
    """Keeps the state in a private bucket, signed as the publisher signs (never public).

    ``client`` is an :class:`~snowlight.live.publishers.R2Publisher` for the private
    bucket, made by :func:`bucket_store`.
    """

    client: R2Publisher

    def pull(self, folder: Path) -> list[str]:
        try:
            data = self.client.read(STATE_KEY)
        except PublishError as error:
            raise StateError(f"pull: {error}") from error
        return [] if data is None else unpack(data, folder)

    def push(self, folder: Path) -> int:
        data = pack(folder)
        try:
            self.client.write({STATE_KEY: data})
        except PublishError as error:
            raise StateError(f"push: {error}") from error
        return len(data)


def bucket_store(
    endpoint: str, bucket: str, credentials: Credentials, client: httpx.Client
) -> BucketStateStore:
    """The private bucket's store: ``state/`` keys only, never cached."""
    return BucketStateStore(
        R2Publisher(
            endpoint=endpoint,
            bucket=bucket,
            credentials=credentials,
            client=client,
            cache_control="no-store",
            content_type="application/gzip",
            keys=check_state_key,
        )
    )
