"""The state export (S8-E privacy 3): what predict learn reads, and all the Actions cache holds.

The export keeps ``morning/``, ``changes/`` and a schema-only ``ledger.sqlite``: no ``meta``
secret, no ``rows``, no ``derived``, and none of ``unmatched.json``, ``robots.json``,
``cadence.json``, ``publish.json``, ``pacer.json``, ``d1.json`` or ``pulse``. predict learn
labels a day the same from the export as from the whole state.
"""

import io
import sqlite3
import subprocess
import sys
import tarfile
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from live.world import ALPHA_SCHOOL, at, row
from snowlight.live.history import Change, ChangeLog, Event, Shown
from snowlight.live.ledger import Ledger
from snowlight.live.ledger import Outcome as ReadOutcome
from snowlight.live.morning import ANY_KIND, MorningLog
from snowlight.live.state import (
    ALERT_BYTES,
    ARCHIVE,
    BUDGET_BYTES,
    LocalStateStore,
    StateError,
    check_export,
    export,
    pack,
    unpack,
)
from snowlight.schemas.vocab import Reason, Status

PRIVATE = (
    "unmatched.json",
    "robots.json",
    "cadence.json",
    "publish.json",
    "publish.v1-shadow.json",
    "pacer.json",
    "d1.json",
    "pulse",
)


def _full_state(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(folder / "ledger.sqlite")
    ledger.observe("gray-synthetic", ReadOutcome.OK, at("2026-11-17 11:00"), [])
    ledger.observe("gray-synthetic", ReadOutcome.OK, at("2026-11-17 11:05"), [row(ALPHA_SCHOOL)])
    ledger.close()
    for name in PRIVATE:
        (folder / name).write_text('{"SYNTHETIC": "private SYNTHETIC name"}', encoding="utf-8")
    morning(folder)


def morning(folder: Path) -> None:
    """A SYNTHETIC morning record and change log, as predict learn reads them."""
    log = MorningLog(folder / "morning")
    log.record(datetime(2026, 1, 6, 13, tzinfo=UTC), shown="v1", reads={"tv": (10, 10, 0)},
               unknown=(), named={"2900002": {"*": {ANY_KIND}}})  # fmt: skip
    log.record(datetime(2026, 1, 6, 17, tzinfo=UTC), shown="v1", reads={}, unknown=(), named={})
    lit = Shown(int(Status.CLOSED), int(Reason.WINTER_STORM), None, None)
    ChangeLog(folder / "changes").commit(
        [
            Change(
                datetime(2026, 1, day, 12, tzinfo=UTC),
                date(2026, 1, day),
                "290000200003",
                Event.LIT,
                lit,
                {"source_id": "tv"},
            )
            for day in (2, 5)
        ]
    )


def _members(data: bytes) -> dict[str, bytes]:
    found: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar.getmembers():
            handle = tar.extractfile(member)
            assert handle is not None
            found[member.name] = handle.read()
    return found


def test_the_export_holds_only_the_allowlist_and_a_schema_only_ledger(tmp_path: Path) -> None:
    _full_state(tmp_path / "state")
    data = export(tmp_path / "state")
    members = _members(data)
    assert sorted(members) == [
        "changes/2026-01-02.jsonl",
        "changes/2026-01-05.jsonl",
        "ledger.sqlite",
        "morning/2026-01-06.json",
    ]
    assert b"SYNTHETIC name" not in b"".join(members.values())
    ledger = tmp_path / "exported.sqlite"
    ledger.write_bytes(members["ledger.sqlite"])
    connection = sqlite3.connect(ledger)
    tables = [
        name
        for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    ]
    assert {"meta", "rows", "derived", "good_reads", "sources"} <= set(tables)
    for table in tables:
        assert connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0] == 0  # noqa: S608
    connection.close()
    assert check_export(data) == sorted(members)
    # the same state gives the same bytes
    assert export(tmp_path / "state") == data


def test_check_export_refuses_anything_else(tmp_path: Path) -> None:
    _full_state(tmp_path / "state")
    with pytest.raises(StateError, match="must not"):
        check_export(pack(tmp_path / "state"))  # the whole state: a secret, the queue
    sneaked = tmp_path / "sneaked"
    sneaked.mkdir()
    (sneaked / "morning").mkdir()
    (sneaked / "morning" / "2026-01-06.json").write_text("{}", encoding="utf-8")
    full = Ledger(sneaked / "ledger.sqlite")  # a ledger with its secret, under an allowed name
    full.close()
    with pytest.raises(StateError, match="holds rows"):
        check_export(pack(sneaked))
    (sneaked / "ledger.sqlite").unlink()
    with pytest.raises(StateError, match="no ledger"):
        check_export(pack(sneaked))
    with pytest.raises(StateError, match="does not read"):
        check_export(b"not a tar")


def test_never_packed_names_stay_on_the_runner(tmp_path: Path) -> None:
    _full_state(tmp_path / "state")
    names = unpack(pack(tmp_path / "state"), tmp_path / "restored")
    assert "d1.json" not in names
    assert "pulse" not in names
    assert "unmatched.json" in names  # the private store keeps the queue
    LocalStateStore(tmp_path / "box").push(tmp_path / "state")
    assert (tmp_path / "box" / ARCHIVE).is_file()


def test_the_budget_is_16_mb_with_the_alert_at_12() -> None:
    assert BUDGET_BYTES == 16 * 1024 * 1024
    assert ALERT_BYTES == 12 * 1024 * 1024


def test_a_ledger_a_killed_process_left_mid_transaction_packs_its_last_commit(
    tmp_path: Path,
) -> None:
    # the watcher's KILL, a cancel or a timeout inside a ledger transaction leaves a hot
    # rollback journal: the end push and the export still pack the last committed state
    # (SQLite rolls the journal back itself, under its own lock, as any next open would)
    folder = tmp_path / "state"
    folder.mkdir()
    path = folder / "ledger.sqlite"
    made = sqlite3.connect(path)
    made.execute("CREATE TABLE t (x INTEGER)")
    made.executemany("INSERT INTO t VALUES (?)", [(n,) for n in range(20_000)])
    made.commit()
    made.close()
    child = (
        "import os, signal, sqlite3, sys\n"
        "c = sqlite3.connect(sys.argv[1], isolation_level=None)\n"
        "c.execute('PRAGMA cache_size = 10')\n"
        "c.execute('BEGIN')\n"
        "c.execute('UPDATE t SET x = x + 1')\n"
        "c.execute('DELETE FROM t WHERE x % 3 = 0')\n"
        "os.kill(os.getpid(), signal.SIGKILL)\n"
    )
    subprocess.run([sys.executable, "-c", child, str(path)], check=False)  # noqa: S603
    journal = folder / "ledger.sqlite-journal"
    assert journal.is_file()
    assert journal.stat().st_size > 0
    data = pack(folder)
    assert not journal.is_file() or journal.stat().st_size == 0  # rolled back, not copied
    out = tmp_path / "out"
    assert unpack(data, out) == ["ledger.sqlite"]
    for ledger in (out / "ledger.sqlite", path):
        copy = sqlite3.connect(ledger)
        try:
            assert copy.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            assert copy.execute("SELECT count(*), sum(x) FROM t").fetchone() == (
                20_000,
                sum(range(20_000)),
            )
        finally:
            copy.close()
