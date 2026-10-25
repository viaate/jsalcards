"""The state is packed only through SQLite's own locks (S8-E round 4, B1): a ledger that
another process keeps writing (a reader a cancel left running) packs into a consistent copy
every time, a damaged ledger is never packed, and a pulled slot whose ledger is damaged is
read as a slot that fails its sha256 (the previous slot is taken). SYNTHETIC data only."""

import hashlib
import io
import sqlite3
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import pytest

from snowlight.live.state import StateError, check_packed, pack, sound, unpack

WRITER = """
import os, random, sqlite3, sys
db = sqlite3.connect(sys.argv[1], isolation_level=None)
db.execute("PRAGMA cache_size = 50")  # spill early: database pages written mid-transaction
db.execute("CREATE TABLE IF NOT EXISTS t (k INTEGER PRIMARY KEY, v BLOB)")
db.execute("BEGIN")
for i in range(4000):
    db.execute("INSERT OR REPLACE INTO t VALUES (?, ?)", (i, os.urandom(500)))
db.execute("COMMIT")
open(sys.argv[1] + ".ready", "w").close()
while True:
    db.execute("BEGIN")
    for _ in range(40):
        db.execute(
            "UPDATE t SET v = ? WHERE k = ?",
            (os.urandom(random.randint(100, 900)), random.randrange(4000)),
        )
    db.execute("DELETE FROM t WHERE k = ?", (random.randrange(4000),))
    db.execute("INSERT OR REPLACE INTO t VALUES (?, ?)", (random.randrange(4000), os.urandom(700)))
    db.execute("COMMIT")
"""


def test_a_ledger_another_process_keeps_writing_packs_consistent_every_time(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "state"
    folder.mkdir()
    ledger = folder / "ledger.sqlite"
    writer = subprocess.Popen([sys.executable, "-c", WRITER, str(ledger)])  # noqa: S603
    try:
        ready = Path(f"{ledger}.ready")
        deadline = time.monotonic() + 30
        while not ready.is_file():
            assert time.monotonic() < deadline, "the writer never started"
            time.sleep(0.05)
        ready.unlink()
        packed, journal_seen = 0, 0
        end = time.monotonic() + 8
        while time.monotonic() < end or packed < 60:
            journal_seen += (folder / "ledger.sqlite-journal").is_file()
            data = pack(folder)  # never raises: no journal vanishes under a hand copy
            out = tmp_path / f"out{packed % 2}"
            assert unpack(data, out) == ["ledger.sqlite"]
            assert sound(out / "ledger.sqlite")
            connection = sqlite3.connect(out / "ledger.sqlite")
            try:
                assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
                count = connection.execute("SELECT count(*) FROM t").fetchone()[0]
                assert 0 < count <= 4000
            finally:
                connection.close()
            packed += 1
        assert writer.poll() is None  # the writer ran (and wrote) the whole time
        assert journal_seen > 0  # and its journal was there for some of the packs
    finally:
        writer.kill()
        writer.wait()


def _archive(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, body in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
    return buffer.getvalue()


def _ledger(path: Path) -> bytes:
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE t (k INTEGER PRIMARY KEY, v TEXT)")
    connection.executemany("INSERT INTO t VALUES (?, ?)", [(n, "x" * 200) for n in range(2000)])
    connection.execute("CREATE INDEX t_v ON t (v)")
    connection.commit()
    connection.close()
    return path.read_bytes()


def _damaged(good: bytes) -> bytes:
    """``good`` with one page of the table's b-tree overwritten (still a SQLite header)."""
    body = bytearray(good)
    page = 4096
    body[page * 3 : page * 3 + 512] = b"\xff" * 512
    return bytes(body)


def test_a_damaged_ledger_is_never_packed_and_a_damaged_pull_is_refused(tmp_path: Path) -> None:
    good = _ledger(tmp_path / "good.sqlite")
    bad = _damaged(good)
    (tmp_path / "bad.sqlite").write_bytes(bad)
    assert sound(tmp_path / "good.sqlite")
    assert not sound(tmp_path / "bad.sqlite")
    folder = tmp_path / "state"
    folder.mkdir()
    (folder / "ledger.sqlite").write_bytes(bad)
    with pytest.raises(StateError, match="integrity"):
        pack(folder)
    check_packed(_archive({"ledger.sqlite": good, "cadence.json": b"{}"}))
    with pytest.raises(StateError, match="integrity"):
        check_packed(_archive({"ledger.sqlite": bad, "cadence.json": b"{}"}))
    assert hashlib.sha256(bad).hexdigest()  # a damaged ledger has a perfectly good sha256
