"""The morning record's channel to the predict job (LIVE-READS decision 3), against the
in-memory SQLite stand-in for D1. SYNTHETIC record days only.

* the marks that ship: the day itself from 09:00 to 21:00 UTC, the day before (its final
  file) before 09:00;
* the shipped parts decode to the file's bytes, byte for byte; parts go before the head;
* an older epoch or an earlier ``through`` is refused by the head's guard;
* cleanup keeps each day's current and previous versions and the days D and D-1 only;
* every write is billed to the day's ``budget`` and its own ``<day>/morning`` row;
* only a live-read run ships; an overrides-only run and the box have no shipper; a failing
  shipment is one line and never raises; nothing but the fixed statements is sent.
"""

import argparse
import hashlib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from live.test_d1_store import ENV, Clock, FakeD1, _store
from snowlight.live import cli as live_cli
from snowlight.live import d1
from snowlight.live.d1 import (
    MORNING_READS,
    MorningReader,
    MorningShipper,
    WorkflowError,
    WriteCapError,
    unpack_morning,
)
from snowlight.live.morning import MorningDay, MorningLog

DAY = date(2026, 11, 17)
AT = datetime(2026, 11, 17, 13, 0, 30, tzinfo=UTC)


def _record(folder: Path, at: datetime, reads: int = 3) -> bytes:
    """SYNTHETIC: one shown pass at ``at`` with ``reads`` lists read whole."""
    log = MorningLog(folder / "morning")
    log.record(
        at,
        shown="v1",
        reads={
            hashlib.sha256(f"{at}{n}".encode()).hexdigest()[:20]: (n % 97, n % 89, n % 3)
            for n in range(reads)
        },
        unknown=(),
        named={},
        health=0.95,
    )
    return log.path(at.date()).read_bytes()


def _pulled(api: FakeD1, folder: Path, clock: Clock | None = None) -> d1.D1StateStore:
    store = _store(api, clock)
    store.take(folder)
    return store


def _ship(store: d1.D1StateStore, folder: Path, day: date = DAY) -> d1.Shipped:
    data = MorningLog(folder / "morning").path(day).read_bytes()
    through = MorningDay.from_bytes(data).through
    assert through is not None
    return MorningShipper(store).ship(
        folder, day, data, through, deadline=store.clock() + timedelta(minutes=1)
    )


def _heads(api: FakeD1) -> dict[str, dict[str, Any]]:
    cursor = api.db.execute("SELECT * FROM morning_head")
    names = [column[0] for column in cursor.description]
    return {row[0]: dict(zip(names, row, strict=True)) for row in cursor.fetchall()}


def _versions(api: FakeD1) -> set[str]:
    return {row[0] for row in api.db.execute("SELECT DISTINCT sha256 FROM morning_parts")}


def _read_back(api: FakeD1, day: date = DAY) -> bytes | None:
    reader = MorningReader(api)
    head = reader.heads([day])[day]
    texts = reader.parts(head.sha256, head.parts)
    return None if texts is None else unpack_morning(texts, head.sha256)


def test_the_marks_that_ship() -> None:
    def at(hour: int, minute: int = 0) -> datetime:
        return datetime(2026, 11, 17, hour, minute, tzinfo=UTC)

    yesterday = DAY - timedelta(days=1)
    assert live_cli.ship_days(at(0)) == [yesterday]
    assert live_cli.ship_days(at(8, 30)) == [yesterday]
    assert live_cli.ship_days(at(9)) == [DAY]
    assert live_cli.ship_days(at(21)) == [DAY]
    assert live_cli.ship_days(at(21, 30)) == []
    assert live_cli.ship_days(at(23, 30)) == []


def test_the_parts_are_the_files_bytes_and_go_before_the_head(tmp_path: Path) -> None:
    api = FakeD1()
    store = _pulled(api, tmp_path)
    data = _record(tmp_path, AT, reads=20_000)  # several parts
    found = _ship(store, tmp_path)
    assert found.outcome == "shipped"
    assert found.parts >= 2
    assert found.raw == len(data)
    assert _read_back(api) == data
    head = _heads(api)[DAY.isoformat()]
    assert head["sha256"] == hashlib.sha256(data).hexdigest()
    assert head["epoch"] == 1
    assert head["prev_sha256"] is None
    sent = [sql for sql in api.sent if "morning" in sql]
    parts = [i for i, sql in enumerate(sent) if sql.startswith("INSERT INTO morning_parts")]
    ship = [i for i, sql in enumerate(sent) if sql.startswith("INSERT INTO morning_head")]
    assert len(parts) == found.parts
    assert ship
    assert max(parts) < ship[0]
    # the same bytes again: the head names them, nothing is written
    written = len(api.sent)
    again = _ship(store, tmp_path)
    assert (again.outcome, again.rows) == ("same", 0)
    assert not any(sql.startswith("INSERT") for sql in api.sent[written:])
    assert set(api.sent) <= d1.STATEMENTS


def test_an_older_epoch_or_an_earlier_through_is_refused(tmp_path: Path) -> None:
    api = FakeD1()
    old = _pulled(api, tmp_path / "old")
    new = _pulled(api, tmp_path / "new")
    _record(tmp_path / "new", AT)
    assert _ship(new, tmp_path / "new").outcome == "shipped"
    shipped = _heads(api)[DAY.isoformat()]["sha256"]
    # the cancelled run's end, with a later record: its epoch is older
    _record(tmp_path / "old", AT + timedelta(minutes=30))
    assert _ship(old, tmp_path / "old").outcome == "refused"
    assert _heads(api)[DAY.isoformat()]["sha256"] == shipped
    # a successor pulled a record cut 30 minutes back (a restart): refused until it passes
    later = _pulled(api, tmp_path / "later")
    _record(tmp_path / "later", AT - timedelta(minutes=30))
    assert _ship(later, tmp_path / "later").outcome == "refused"
    _record(tmp_path / "later", AT + timedelta(hours=1))
    assert _ship(later, tmp_path / "later").outcome == "shipped"
    assert _heads(api)[DAY.isoformat()]["epoch"] == 3


def test_cleanup_keeps_the_current_and_previous_versions_of_d_and_d_minus_1(
    tmp_path: Path,
) -> None:
    api = FakeD1()
    clock = Clock(AT)
    store = _pulled(api, tmp_path, clock)
    before = DAY - timedelta(days=2)
    for day in (before, DAY - timedelta(days=1)):
        _record(tmp_path, datetime.combine(day, AT.time(), tzinfo=UTC))
        assert _ship(store, tmp_path, day).outcome == "shipped"
    shas = []
    for step in range(3):
        data = _record(tmp_path, AT + timedelta(minutes=30 * step))
        shas.append(hashlib.sha256(data).hexdigest())
        assert _ship(store, tmp_path).outcome == "shipped"
    heads = _heads(api)
    assert sorted(heads) == [(DAY - timedelta(days=1)).isoformat(), DAY.isoformat()]
    assert heads[DAY.isoformat()]["sha256"] == shas[2]
    assert heads[DAY.isoformat()]["prev_sha256"] == shas[1]
    yesterday = heads[(DAY - timedelta(days=1)).isoformat()]["sha256"]
    assert _versions(api) == {shas[1], shas[2], yesterday}


def test_every_write_is_billed_and_the_allowance_refuses(tmp_path: Path) -> None:
    api = FakeD1()
    store = _pulled(api, tmp_path)
    _record(tmp_path, AT)
    found = _ship(store, tmp_path)
    rows = dict(api.db.execute("SELECT day, rows FROM budget").fetchall())
    morning = rows[f"{DAY.isoformat()}/morning"]
    assert morning == found.rows + 2
    assert rows[DAY.isoformat()] >= morning
    # past its own 1,000 rows a day the shipment is refused, and nothing is written
    api.db.execute("UPDATE budget SET rows = 999 WHERE day = ?", (f"{DAY.isoformat()}/morning",))
    api.db.commit()
    _record(tmp_path, AT + timedelta(minutes=30))
    with pytest.raises(WriteCapError):
        _ship(store, tmp_path)
    assert _versions(api) == {_heads(api)[DAY.isoformat()]["sha256"]}


def test_only_a_live_read_run_ships(tmp_path: Path) -> None:
    api = FakeD1()
    _pulled(api, tmp_path)
    _record(tmp_path, AT)
    with pytest.raises(WorkflowError):
        _ship(_store(api, env={**ENV, "GITHUB_WORKFLOW": "predict"}), tmp_path)
    assert _heads(api) == {}


def _runner(tmp_path: Path, shipper: Any, now: datetime) -> live_cli.Runner:
    runner = live_cli.Runner(
        args=argparse.Namespace(state=tmp_path),
        config=None,  # type: ignore[arg-type]
        env={},
        parts=None,  # type: ignore[arg-type]
        loaders=SimpleNamespace(clock=lambda: now),  # type: ignore[arg-type]
    )
    runner.shipper = shipper
    runner.state = live_cli._Loop(due=now + timedelta(minutes=4), next_check=now)
    runner.state.next_ship = now
    return runner


def test_the_idle_time_ships_once_a_mark_and_a_failure_never_raises(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    api = FakeD1()
    store = _pulled(api, tmp_path)
    _record(tmp_path, AT)
    now = AT + timedelta(seconds=30)
    runner = _runner(tmp_path, MorningShipper(store), now)
    runner.idle(now)
    out = capsys.readouterr().out
    assert f"morning shipped: {DAY.isoformat()} shipped" in out
    assert runner.state.next_ship == datetime(2026, 11, 17, 13, 30, tzinfo=UTC)
    # the next mark: the file did not change, so nothing is asked of the database
    sent = len(api.sent)
    runner.state.next_ship = now
    runner.idle(now)
    assert len(api.sent) == sent
    assert "morning shipped" not in capsys.readouterr().out

    class Broken:
        def ship(self, *_args: object, **_kwargs: object) -> d1.Shipped:
            raise d1.D1Error("query: HTTP 500")

    _record(tmp_path, AT + timedelta(minutes=1))
    broken = _runner(tmp_path, Broken(), now)
    broken.idle(now)  # never raises
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    assert "morning ship: 2026-11-17 failed: D1Error" in out


def test_overrides_only_and_the_box_have_no_shipper(tmp_path: Path) -> None:
    now = AT
    runner = _runner(tmp_path, None, now)
    runner.idle(now)  # no store: nothing
    assert runner.state.next_ship == datetime(2026, 11, 17, 13, 30, tzinfo=UTC)
    source = Path(live_cli.__file__).read_text(encoding="utf-8")
    assert "isinstance(store, D1StateStore) and not args.overrides_only" in source


def test_the_reader_sends_selects_of_the_two_tables_only(tmp_path: Path) -> None:
    api = FakeD1()
    store = _pulled(api, tmp_path)
    _record(tmp_path, AT)
    _ship(store, tmp_path)
    sent = len(api.sent)
    assert _read_back(api) is not None
    reads = set(api.sent[sent:])
    assert reads <= MORNING_READS
    assert all(sql.startswith("SELECT") for sql in MORNING_READS)
    assert all("morning_head" in sql or "morning_parts" in sql for sql in MORNING_READS)
    # the reader never creates the database
    empty = FakeD1()
    assert MorningReader(empty).database() is None
    assert empty.created == 0


def test_the_push_keeps_its_idle_time_and_the_ship_follows_on_a_fresh_clock(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """SYNTHETIC: the push goes first with the whole idle time (a slow shipment can never
    starve it into a false state alert); the shipment then starts on a fresh clock, is
    skipped when the push left it too little, and never follows a failed push."""
    _record(tmp_path, AT)
    start = AT + timedelta(seconds=30)
    clock = {"now": start}
    events: list[tuple[str, float]] = []

    class Store:
        def __init__(self, push_takes: timedelta, fails: bool = False) -> None:
            self.push_takes = push_takes
            self.fails = fails

        def keep(self, _folder: Path, *, deadline: datetime) -> SimpleNamespace:
            events.append(("push", (deadline - clock["now"]).total_seconds()))
            clock["now"] += self.push_takes
            if self.fails:
                raise d1.D1Error("query: HTTP 500")
            return SimpleNamespace(
                bytes=10, parts=1, rows_written=3, day_rows=3, hourly=False, over_plan=False
            )

    class SlowShipper:
        def ship(self, *_args: object, deadline: datetime) -> d1.Shipped:
            events.append(("ship", (deadline - clock["now"]).total_seconds()))
            clock["now"] = deadline - timedelta(seconds=5)  # D1 slow: up to its deadline
            raise d1.D1Error("query: out of time")

    def runner(store: Store) -> live_cli.Runner:
        events.clear()
        clock["now"] = start
        made = live_cli.Runner(
            args=argparse.Namespace(state=tmp_path),
            config=None,  # type: ignore[arg-type]
            env={},
            parts=SimpleNamespace(ingest=SimpleNamespace(state_bytes=0)),  # type: ignore[arg-type]
            loaders=SimpleNamespace(clock=lambda: clock["now"]),  # type: ignore[arg-type]
            store=store,
        )
        made.shipper = SlowShipper()  # type: ignore[assignment]
        made.state = live_cli._Loop(due=start + timedelta(minutes=2), next_check=start)
        made.state.next_ship = start
        made.state.next_push = start
        return made

    whole = (timedelta(minutes=2) - live_cli.PUSH_MARGIN).total_seconds()
    quick = runner(Store(timedelta(seconds=3)))
    quick.idle(start)
    out = capsys.readouterr().out
    assert events == [("push", whole), ("ship", whole - 3)]
    assert "ALERT" not in out
    assert "state pushed" in out
    assert "morning ship: 2026-11-17 failed: D1Error" in out
    assert quick.state.next_ship == datetime(2026, 11, 17, 13, 30, tzinfo=UTC)
    # a push that took the idle time: the shipment is skipped, never the push's alert
    slow = runner(Store(timedelta(seconds=80)))
    slow.idle(start)
    out = capsys.readouterr().out
    assert events == [("push", whole)]
    assert "morning ship: skipped (too close to the next pass)" in out
    assert "ALERT" not in out
    # a failed push: no shipment after it (the shipped record never runs ahead of the saved)
    failed = runner(Store(timedelta(seconds=1), fails=True))
    failed.idle(start)
    out = capsys.readouterr().out
    assert events == [("push", whole)]
    assert "morning ship: skipped (the state push failed)" in out
    assert failed.state.next_ship == datetime(2026, 11, 17, 13, 30, tzinfo=UTC)
