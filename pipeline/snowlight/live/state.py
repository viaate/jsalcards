"""The live ingest's private state, and where it is kept between runs (spec 7.7, 9).

The state folder holds what the ingest must not lose:

* ``ledger.sqlite``: the row ledger (keys, times, codes; no raw text);
* ``publish.json``: the publisher's memory (the last stamp published, the gate's);
* ``changes/<day>.jsonl``: the change log of the live days (codes and times);
* ``morning/<day>.json``: the morning record for the automatic learning
  (:mod:`snowlight.live.morning`: reads, withheld states and named districts as counts, ids
  and codes);
* ``robots.json``: robots.txt verdicts (the fetch layer's);
* ``unmatched.json``: the queue of listings the matcher did not accept. It holds the
  listings' names as the sources print them, so it is kept only in a private store.

A store packs the folder into one gzipped tar (:func:`pack`): files in a fixed order
with fixed times, so the same state is the same bytes, and the ledger copied through
SQLite's backup API, so a store pushed while the ingest runs holds a consistent
ledger. :func:`unpack` extracts regular files only, inside the folder.

* :class:`LocalStateStore`: a folder (the paid box, tests).
* :class:`BucketStateStore`: a private bucket (Cloudflare R2), through the same SigV4
  client as the publisher, under ``state/`` keys only.
* :class:`CacheStateStore`: the Pages path's Actions cache folder. That cache is
  readable from the public repository's workflows, so it never gets the unmatched
  queue: names stay in a private store.
"""

import gzip
import io
import sqlite3
import tarfile
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final, Protocol

import httpx

from snowlight.live.publishers import Credentials, PublishError, R2Publisher
from snowlight.output import write_bytes_atomic

ARCHIVE: Final = "live-state.tar.gz"
CACHE_KEY_PREFIX: Final = "live-state-"
"""The Actions cache key prefix of the cache store's folder: a workflow that runs the live loop
with state kind ``cache`` saves the folder under ``live-state-<run id>``, and the predict
workflow's learning step restores the newest such key, read only (docs/live.md)."""
STATE_KEY: Final = f"state/{ARCHIVE}"
PRIVATE_ONLY: Final = frozenset({"unmatched.json"})
"""Files that hold raw names: only a private store keeps them."""
BUDGET_BYTES: Final = 50 * 1024 * 1024
"""Spec 13: the state is at most 50 MB compressed."""
_SQLITE: Final = ".sqlite"


class StateError(RuntimeError):
    """The state could not be pulled or pushed."""


def _include_all(_name: str) -> bool:
    return True


def _snapshot(path: Path) -> bytes:
    """A consistent copy of a SQLite file, even while another connection writes it."""
    with tempfile.TemporaryDirectory() as scratch:
        copy = Path(scratch) / "copy.sqlite"
        source = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        target = sqlite3.connect(copy)
        try:
            source.backup(target)
        finally:
            source.close()
            target.close()
        return copy.read_bytes()


def pack(folder: Path, include: Callable[[str], bool] = _include_all) -> bytes:
    """The state folder as one gzipped tar, the same bytes for the same state."""
    buffer = io.BytesIO()
    with (
        gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as zipped,
        tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as tar,
    ):
        for path in sorted(folder.rglob("*")):
            name = path.relative_to(folder).as_posix()
            if not path.is_file() or not include(name) or name.endswith((".tmp", "-journal")):
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


def _public_safe(name: str) -> bool:
    return PurePosixPath(name).name not in PRIVATE_ONLY


def cache_store(root: Path) -> LocalStateStore:
    """:class:`CacheStateStore`: the Actions cache folder, without the unmatched queue."""
    return LocalStateStore(root, include=_public_safe)


CacheStateStore: Final = cache_store
"""The Pages path's store (spec 7.7): hashes and codes only, never the queue."""


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
