"""The D1 state store (S8-E section 2), against an in-memory SQLite stand-in for D1 and, for
the HTTP layer, a stub Cloudflare API. SYNTHETIC state only.

* the epoch is taken at pull, and the newest puller wins;
* two writers interleaved at every statement: the loser never writes a slot ``head`` names,
  and every later pull reads bytes that match ``head``'s sha256;
* a damaged current slot falls back to the previous one; both damaged is a failed pull until
  ``head`` is 2 hours old, then an empty start;
* no ``head`` row only on an HTTP 200 with zero rows; no database is created on an error
  answer; chunks are upserted (no DELETE per push);
* the write cap and the hourly switch; holds kept at once and merged at pull;
* only live-read runs take an epoch or push; no answer body ever reaches an error message.
"""

import json
import random
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from snowlight.live import cli as live_cli
from snowlight.live import d1
from snowlight.live.cadence import Cadence, merge_holds
from snowlight.live.d1 import (
    DATABASE,
    EPOCH_FILE,
    Answer,
    CloudflareD1,
    D1Error,
    D1StateStore,
    LostStateError,
    Secrets,
    Statement,
    UnreadableStateError,
    WorkflowError,
    WriteCapError,
)
from snowlight.live.ledger import Outcome
from snowlight.live.state import pack

NOW = datetime(2026, 11, 17, 11, 5, tzinfo=UTC)
ENV = {"GITHUB_WORKFLOW": "live-read", "GITHUB_RUN_ID": "1001"}


@dataclass
class FakeD1:
    """D1 as SQLite in memory: each statement runs as sent; ``rows_written`` is SQLite's
    change count (times ``upsert_cost`` for an upsert, to try D1 counting it twice)."""

    db: sqlite3.Connection = field(default_factory=lambda: sqlite3.connect(":memory:"))
    names: list[tuple[str, str]] = field(default_factory=list)
    created: int = 0
    sent: list[str] = field(default_factory=list)
    before: Callable[[str], None] | None = None
    list_fails: bool = False
    upsert_cost: int = 1

    def databases(self, name: str) -> list[tuple[str, str]]:
        if self.list_fails:
            raise D1Error("list databases: HTTP 500")
        return [item for item in self.names if name in item[0]]

    def create(self, name: str) -> str:
        self.created += 1
        self.names.append((name, "0000-synthetic"))
        return "0000-synthetic"

    def run(self, database: str, statements: Sequence[Statement]) -> list[Answer]:
        assert database == "0000-synthetic"
        answers = []
        for sql, params in statements:
            if self.before is not None:
                self.before(sql)
            self.sent.append(sql)
            before = self.db.total_changes
            try:
                cursor = self.db.execute(sql, params)
            except sqlite3.Error as error:
                raise D1Error("query: HTTP 400") from error
            names = [column[0] for column in cursor.description or ()]
            rows = tuple(dict(zip(names, row, strict=True)) for row in cursor.fetchall())
            self.db.commit()
            changes = self.db.total_changes - before
            cost = self.upsert_cost if "ON CONFLICT" in sql else 1
            answers.append(Answer(rows=rows, rows_written=changes * cost, changes=changes))
        return answers

    def head(self) -> dict[str, Any]:
        cursor = self.db.execute("SELECT * FROM head")
        names = [column[0] for column in cursor.description]
        return dict(zip(names, cursor.fetchone(), strict=True))


def _state(folder: Path, marker: str, size: int = 200_000) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "publish.json").write_text(json.dumps({"marker": marker}), encoding="utf-8")
    # incompressible, so it takes several chunks
    body = random.Random(marker).randbytes(size)  # noqa: S311 - test bytes, no secret
    (folder / "changes").mkdir(exist_ok=True)
    (folder / "changes" / "2026-11-17.jsonl").write_bytes(body)


def _marker(folder: Path) -> str:
    return str(json.loads((folder / "publish.json").read_text(encoding="utf-8"))["marker"])


@dataclass
class Clock:
    now: datetime = NOW

    def __call__(self) -> datetime:
        return self.now


def _store(
    api: FakeD1, clock: Clock | None = None, env: dict[str, str] | None = None
) -> D1StateStore:
    return D1StateStore(api, ENV if env is None else env, clock or Clock())


def test_a_first_run_creates_the_database_and_takes_epoch_1(tmp_path: Path) -> None:
    api = FakeD1()
    pulled = _store(api).take(tmp_path / "a")
    assert (pulled.epoch, pulled.cold, pulled.names) == (1, True, ())
    assert api.created == 1
    assert json.loads((tmp_path / "a" / EPOCH_FILE).read_text())["epoch"] == 1
    # the next run finds the database by its exact name and creates nothing
    assert _store(api).take(tmp_path / "b").epoch == 2
    assert api.created == 1
    assert set(api.sent) <= d1.STATEMENTS


def test_an_error_answer_never_creates_the_database_or_a_head(tmp_path: Path) -> None:
    api = FakeD1(list_fails=True)
    with pytest.raises(D1Error):
        _store(api).take(tmp_path / "a")
    assert api.created == 0
    # a similar name is not the database
    api = FakeD1(names=[("snowlight-live-state-old", "0000-synthetic")])
    _store(api).take(tmp_path / "b")
    assert api.created == 1


def test_push_then_pull_round_trips_and_upserts_only(tmp_path: Path) -> None:
    api = FakeD1()
    _store(api).take(tmp_path / "a")
    _state(tmp_path / "a", "first")
    result = _store(api).keep(tmp_path / "a")
    assert result.parts >= 2
    assert result.day_rows >= result.parts
    assert not any(sql.startswith("DELETE FROM chunks") for sql in api.sent)
    pulled = _store(api).take(tmp_path / "b")
    assert (pulled.epoch, pulled.cold) == (2, False)
    assert _marker(tmp_path / "b") == "first"
    assert EPOCH_FILE in pulled.names or (tmp_path / "b" / EPOCH_FILE).is_file()
    assert "d1.json" not in pulled.names  # never packed


def test_a_second_good_push_deletes_the_older_epochs_slots(tmp_path: Path) -> None:
    api = FakeD1()
    store = _store(api)
    store.take(tmp_path / "a")
    _state(tmp_path / "a", "a1")
    store.keep(tmp_path / "a")
    successor = _store(api)
    successor.take(tmp_path / "b")
    successor.keep(tmp_path / "b")
    slots = {row[0] for row in api.db.execute("SELECT DISTINCT slot FROM chunks")}
    assert slots == {"e1a", "e2a"}
    successor.keep(tmp_path / "b")
    slots = {row[0] for row in api.db.execute("SELECT DISTINCT slot FROM chunks")}
    assert slots == {"e2a", "e2b"}
    head = api.head()
    assert (head["slot"], head["prev_slot"]) == ("e2b", "e2a")


def test_the_newest_puller_wins_and_the_old_writer_writes_nothing(tmp_path: Path) -> None:
    api = FakeD1()
    old = _store(api)
    old.take(tmp_path / "old")
    _state(tmp_path / "old", "old-1")
    old.keep(tmp_path / "old")
    new = _store(api)
    new.take(tmp_path / "new")
    sent = len(api.sent)
    _state(tmp_path / "old", "old-2")
    with pytest.raises(LostStateError):
        old.keep(tmp_path / "old")
    assert not any("chunks" in sql for sql in api.sent[sent:] if "INSERT" in sql)
    new.keep(tmp_path / "new")
    _store(api).take(tmp_path / "later")
    assert _marker(tmp_path / "later") == "old-1"


def _push_statements(tmp_path: Path) -> int:
    """How many statements one push of the second state sends (after a first push)."""
    api = FakeD1()
    store = _store(api)
    store.take(tmp_path / "count")
    _state(tmp_path / "count", "one")
    store.keep(tmp_path / "count")
    _state(tmp_path / "count", "two")
    sent = len(api.sent)
    store.keep(tmp_path / "count")
    return len(api.sent) - sent


@dataclass
class _Interleave:
    """Runs a successor's whole pull just before the ``step``-th statement of a push."""

    api: FakeD1
    step: int
    folder: Path
    seen: int = 0
    taken: list[str] = field(default_factory=list)

    def __call__(self, _sql: str) -> None:
        if self.seen == self.step and not self.taken:
            self.api.before = None
            pulled = _store(self.api).take(self.folder)
            self.taken.append(_marker(self.folder) if pulled.names else "")
            self.api.before = self
        self.seen += 1


def test_two_writers_interleaved_at_every_step(tmp_path: Path) -> None:
    steps = _push_statements(tmp_path)
    assert steps >= 5
    for step in range(steps + 1):
        api = FakeD1()
        old = _store(api)
        old.take(tmp_path / f"old{step}")
        _state(tmp_path / f"old{step}", "old-1")
        old.keep(tmp_path / f"old{step}")
        _state(tmp_path / f"old{step}", "old-2")
        hook = _Interleave(api, step, tmp_path / f"new{step}")
        api.before = hook
        try:
            old.keep(tmp_path / f"old{step}")
            lost = False
        except LostStateError:
            lost = True
        api.before = None
        taken = hook.taken
        if not taken:  # the push ended before the successor pulled
            _store(api).take(tmp_path / f"new{step}")
            taken.append(_marker(tmp_path / f"new{step}"))
        head = api.head()
        if lost:
            # the loser's slot is never the one head names
            assert head["slot"] == "e1a"
            assert taken == ["old-1"]
        # every later pull reads bytes that match head's sha256
        later = _store(api).take(tmp_path / f"later{step}")
        assert not later.cold
        assert _marker(tmp_path / f"later{step}") in {"old-1", "old-2"}
        assert _marker(tmp_path / f"later{step}") == taken[0] or not lost


def test_a_damaged_slot_falls_back_to_the_previous_one(tmp_path: Path) -> None:
    api = FakeD1()
    store = _store(api)
    store.take(tmp_path / "a")
    _state(tmp_path / "a", "first")
    store.keep(tmp_path / "a")
    _state(tmp_path / "a", "second")
    store.keep(tmp_path / "a")
    api.db.execute("UPDATE chunks SET data = 'AAAA' WHERE slot = 'e1b' AND n = 0")
    api.db.commit()
    _store(api).take(tmp_path / "b")
    assert _marker(tmp_path / "b") == "first"


def test_both_slots_damaged_is_a_failed_pull_until_head_is_2_hours_old(tmp_path: Path) -> None:
    api = FakeD1()
    clock = Clock()
    store = _store(api, clock)
    store.take(tmp_path / "a")
    _state(tmp_path / "a", "first")
    store.keep(tmp_path / "a")
    _state(tmp_path / "a", "second")
    store.keep(tmp_path / "a")
    api.db.execute("UPDATE chunks SET data = 'AAAA' WHERE n = 0")
    api.db.commit()
    epoch = api.head()["epoch"]
    clock.now = NOW + timedelta(hours=1)
    with pytest.raises(UnreadableStateError):
        _store(api, clock).take(tmp_path / "b")
    assert api.head()["epoch"] == epoch  # nothing taken: the readable state is never replaced
    clock.now = NOW + timedelta(hours=2, minutes=1)
    pulled = _store(api, clock).take(tmp_path / "c")
    assert (pulled.cold, pulled.replaced_unreadable) == (True, True)
    assert api.head()["epoch"] == epoch + 1


def test_a_head_that_appears_while_it_is_made_fails_the_pull(tmp_path: Path) -> None:
    api = FakeD1()
    store = _store(api)
    store.database()
    real = api.run

    def racing(database: str, statements: Sequence[Statement]) -> list[Answer]:
        if statements[0][0] == d1._FIRST:
            api.db.execute("INSERT INTO head (id, epoch) VALUES (1, 7)")
        return real(database, statements)

    api.run = racing  # type: ignore[method-assign]
    with pytest.raises(D1Error):
        store.take(tmp_path / "a")
    assert api.head()["epoch"] == 7


def test_the_write_cap_refuses_and_the_hourly_switch_turns_on(tmp_path: Path) -> None:
    api = FakeD1()
    store = _store(api)
    store.take(tmp_path / "a")
    _state(tmp_path / "a", "first")
    assert not store.keep(tmp_path / "a").hourly
    day = NOW.date().isoformat()
    api.db.execute("UPDATE budget SET rows = ? WHERE day = ?", (d1.HOURLY_FROM + 1, day))
    api.db.commit()
    assert store.keep(tmp_path / "a").hourly
    api.db.execute("UPDATE budget SET rows = ? WHERE day = ?", (d1.WRITE_CAP - 2, day))
    api.db.commit()
    epoch_before = api.head()["sha256"]
    with pytest.raises(WriteCapError):
        store.keep(tmp_path / "a")
    assert api.head()["sha256"] == epoch_before


def test_a_first_push_that_writes_more_than_planned_goes_hourly(tmp_path: Path) -> None:
    api = FakeD1(upsert_cost=2)  # D1 counting an upsert as two rows
    store = _store(api)
    store.take(tmp_path / "a")
    _state(tmp_path / "a", "first")
    result = store.keep(tmp_path / "a")
    assert result.over_plan
    assert result.hourly
    assert json.loads((tmp_path / "a" / EPOCH_FILE).read_text())["hourly"] is True


def test_a_push_past_its_deadline_leaves_head_as_it_was(tmp_path: Path) -> None:
    api = FakeD1()
    clock = Clock()
    store = _store(api, clock)
    store.take(tmp_path / "a")
    _state(tmp_path / "a", "first", size=1_200_000)
    sha = api.head()["sha256"]
    with pytest.raises(D1Error, match="ran out of time"):
        store.keep(tmp_path / "a", deadline=NOW)
    assert api.head()["sha256"] == sha


def test_only_a_live_read_run_takes_the_epoch_or_pushes(tmp_path: Path) -> None:
    api = FakeD1()
    with pytest.raises(WorkflowError):
        _store(api, env={"GITHUB_WORKFLOW": "ci"}).take(tmp_path / "a")
    with pytest.raises(WorkflowError):
        _store(api, env={}).keep(tmp_path / "a")
    assert api.created == 0
    _store(api).take(tmp_path / "a")
    with pytest.raises(D1Error, match="no epoch"):
        _store(api).keep(tmp_path / "none")


def test_holds_are_kept_at_once_and_merged_at_pull(tmp_path: Path) -> None:
    api = FakeD1()
    store = _store(api)
    store.take(tmp_path / "a")
    until = NOW + timedelta(hours=20)
    store.put_holds([("synthetic-blocked", until, "blocked")])
    store.put_holds([("synthetic-old", NOW - timedelta(minutes=1), "deferred")])
    pulled = _store(api).take(tmp_path / "b")
    assert pulled.holds == (("synthetic-blocked", until, "blocked"),)
    cadence = tmp_path / "b" / "cadence.json"
    assert merge_holds(cadence, pulled.holds, NOW) == 1
    clocks = Cadence._load(cadence)
    assert clocks["synthetic-blocked"].not_before == until
    assert clocks["synthetic-blocked"].outcome is Outcome.BLOCKED
    # a later wait already known wins
    assert (
        merge_holds(cadence, [("synthetic-blocked", NOW + timedelta(hours=1), "deferred")], NOW)
        == 0
    )


# The HTTP layer -------------------------------------------------------------------------


def _api(handler: Callable[[httpx.Request], httpx.Response]) -> CloudflareD1:
    return CloudflareD1(
        httpx.Client(transport=httpx.MockTransport(handler)),
        Secrets("SYNTHETIC-token", "synthetic-account", "https://cf.example/client/v4"),
        pause=0.0,
    )


def test_the_api_batches_statements_and_falls_back_to_one_per_request() -> None:
    bodies: list[Any] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        assert request.headers["authorization"] == "Bearer SYNTHETIC-token"
        if "batch" in body:
            return httpx.Response(
                400, json={"success": False, "errors": [{"message": "SYNTHETIC secret row text"}]}
            )
        meta = {"rows_written": 1, "changes": 1}
        return httpx.Response(
            200, json={"success": True, "result": [{"success": True, "results": [], "meta": meta}]}
        )

    api = _api(handler)
    answers = api.run("db-id", [("SELECT 1", ()), ("SELECT 2", (3,))])
    assert [answer.rows_written for answer in answers] == [1, 1]
    assert "batch" in bodies[0]
    assert bodies[1] == {"sql": "SELECT 1", "params": []}
    assert not api.batch


def test_api_errors_name_the_status_never_the_body() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403, json={"success": False, "errors": [{"message": "SYNTHETIC private words"}]}
        )

    api = _api(handler)
    with pytest.raises(D1Error) as raised:
        api.databases(DATABASE)
    assert str(raised.value) == "list databases: HTTP 403"
    with pytest.raises(D1Error) as raised:
        api.run("db-id", [("SELECT 1", ())])
    assert "SYNTHETIC" not in str(raised.value)


def test_the_api_lists_and_creates_by_name() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            assert request.url.params["name"] == DATABASE
            result = [{"name": DATABASE, "uuid": "1111"}, {"name": "x", "uuid": 5}]
            return httpx.Response(200, json={"success": True, "result": result})
        assert json.loads(request.content) == {"name": DATABASE}
        return httpx.Response(200, json={"success": True, "result": {"uuid": "2222"}})

    api = _api(handler)
    assert api.databases(DATABASE) == [(DATABASE, "1111")]
    assert api.create(DATABASE) == "2222"


def test_the_secrets_come_from_the_environment() -> None:
    with pytest.raises(D1Error):
        Secrets.from_env({"CLOUDFLARE_API_TOKEN": "SYNTHETIC-token-value"})
    found = Secrets.from_env(
        {"CLOUDFLARE_API_TOKEN": "SYNTHETIC-token-value", "CLOUDFLARE_ACCOUNT_ID": "a"}
    )
    assert "SYNTHETIC-token-value" not in repr(found)


# Answers lost after D1 ran the statement, the write cap on holds, billing, the push's own
# budget, and the overrides-only probe (critic round 1) --------------------------------------


@dataclass
class HttpD1:
    """The Cloudflare API over SQLite (as :class:`FakeD1`), through a MockTransport: the
    answer of the statements named in ``lose`` is dropped once after they ran (a read
    timeout), and ``meta`` may leave out ``rows_written``. ``tick`` seconds pass on the
    store's monotonic clock with every request."""

    db: sqlite3.Connection = field(default_factory=lambda: sqlite3.connect(":memory:"))
    lose: list[str] = field(default_factory=list)
    counted: bool = True
    tick: float = 0.0
    now: float = 0.0
    requests: int = 0
    timeouts: list[float] = field(default_factory=list)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests += 1
        self.now += self.tick
        timeout = request.extensions.get("timeout", {})
        if isinstance(timeout, dict) and isinstance(timeout.get("read"), float):
            self.timeouts.append(timeout["read"])
        if request.method == "GET":
            body = {"success": True, "result": [{"name": DATABASE, "uuid": "u1"}]}
            return httpx.Response(200, json=body)
        sent = json.loads(request.content)
        items = sent.get("batch", [sent])
        results = []
        lost = False
        for item in items:
            before = self.db.total_changes
            try:
                cursor = self.db.execute(item["sql"], item["params"])
            except sqlite3.Error:
                return httpx.Response(400, json={"success": False})
            names = [column[0] for column in cursor.description or ()]
            rows = [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
            self.db.commit()
            changes = self.db.total_changes - before
            meta = {"changes": changes} | ({"rows_written": changes} if self.counted else {})
            results.append({"success": True, "results": rows, "meta": meta})
            for prefix in list(self.lose):
                if item["sql"].startswith(prefix):
                    self.lose.remove(prefix)
                    lost = True
        if lost:
            raise httpx.ReadTimeout("the answer was lost", request=request)
        return httpx.Response(200, json={"success": True, "result": results})

    def store(self, clock: Clock | None = None) -> D1StateStore:
        client = httpx.Client(transport=httpx.MockTransport(self.handler))
        api = CloudflareD1(client, Secrets("t", "a"), pause=0.0, monotonic=lambda: self.now)
        return D1StateStore(api, ENV, clock or Clock())

    def head(self) -> dict[str, Any]:
        cursor = self.db.execute("SELECT * FROM head")
        names = [column[0] for column in cursor.description]
        return dict(zip(names, cursor.fetchone(), strict=True))

    def budget(self) -> int:
        row = self.db.execute("SELECT rows FROM budget WHERE day = ?", (NOW.date().isoformat(),))
        found = row.fetchone()
        return 0 if found is None else int(found[0])


def test_a_swap_whose_answer_was_lost_is_a_good_push(tmp_path: Path) -> None:
    api = HttpD1(lose=["UPDATE head SET prev_slot"])
    store = api.store()
    store.take(tmp_path / "a")
    _state(tmp_path / "a", "first")
    result = store.keep(tmp_path / "a")  # the swap ran, its answer was lost, it was sent again
    head = api.head()
    assert (head["epoch"], head["slot"]) == (1, "e1a")
    assert json.loads((tmp_path / "a" / EPOCH_FILE).read_text())["pushes"] == 1
    assert result.bytes == head["bytes"]
    assert _marker_after_pull(api, tmp_path / "b") == "first"


def _marker_after_pull(api: HttpD1, folder: Path) -> str:
    api.store().take(folder)
    return _marker(folder)


def test_a_take_or_first_insert_whose_answer_was_lost_still_takes_the_epoch(
    tmp_path: Path,
) -> None:
    api = HttpD1(lose=["INSERT INTO head"])
    assert api.store().take(tmp_path / "a").epoch == 1  # the insert ran; its retry failed
    _state(tmp_path / "a", "first")
    api.store().keep(tmp_path / "a")
    api.lose.append("UPDATE head SET epoch")
    pulled = api.store().take(tmp_path / "b")
    assert pulled.epoch == 2
    assert api.head()["epoch"] == 2
    assert _marker(tmp_path / "b") == "first"


def test_a_swap_after_another_run_took_the_epoch_is_still_lost(tmp_path: Path) -> None:
    api = HttpD1(lose=["UPDATE head SET prev_slot"])
    old = api.store()
    old.take(tmp_path / "old")
    _state(tmp_path / "old", "old")
    api.db.execute("UPDATE head SET epoch = epoch + 1, run_id = 'other'")
    api.db.commit()
    with pytest.raises(LostStateError):
        old.keep(tmp_path / "old")


def test_holds_past_the_write_cap_are_refused_and_every_write_is_billed(tmp_path: Path) -> None:
    api = FakeD1()
    store = _store(api)
    store.take(tmp_path / "a")
    day = NOW.date().isoformat()
    pulled = api.db.execute("SELECT rows FROM budget WHERE day = ?", (day,)).fetchone()
    assert pulled is not None
    assert pulled[0] >= 2  # the pull's own insert and holds clean-up, and its bill
    until = NOW + timedelta(hours=3)
    store.put_holds([("synthetic-a", until, "blocked"), ("synthetic-b", until, "deferred")])
    after = api.db.execute("SELECT rows FROM budget WHERE day = ?", (day,)).fetchone()[0]
    assert after == pulled[0] + 3  # two holds and the bill itself
    assert store._unbilled == 0
    # past the pushes' cap, the holds have their own allowance
    api.db.execute("UPDATE budget SET rows = ? WHERE day = ?", (d1.WRITE_CAP - 2, day))
    api.db.commit()
    holds = [(f"synthetic-{n}", until, "deferred") for n in range(5)]
    store.put_holds(holds)
    assert api.db.execute("SELECT COUNT(*) FROM holds").fetchone()[0] == 7
    _state(tmp_path / "a", "capped")
    with pytest.raises(WriteCapError):  # the pushes stay refused
        store.keep(tmp_path / "a")
    # and past the allowance too, a hold is refused (nothing written)
    allowed = d1.WRITE_CAP + d1.HOLD_ALLOWANCE
    api.db.execute("UPDATE budget SET rows = ? WHERE day = ?", (allowed - 2, day))
    api.db.commit()
    with pytest.raises(WriteCapError):
        store.put_holds([(f"synthetic-late-{n}", until, "deferred") for n in range(5)])
    assert api.db.execute("SELECT COUNT(*) FROM holds").fetchone()[0] == 7
    assert d1.HOLD_ALLOWANCE + d1.WRITE_CAP < 100_000


def test_a_block_on_a_capped_day_reaches_the_successor_after_a_handoff(tmp_path: Path) -> None:
    api = FakeD1()
    store = _store(api)
    store.take(tmp_path / "run")
    day = NOW.date().isoformat()
    api.db.execute("UPDATE budget SET rows = ? WHERE day = ?", (d1.WRITE_CAP, day))
    api.db.commit()
    _state(tmp_path / "run", "capped")
    with pytest.raises(WriteCapError):
        store.keep(tmp_path / "run")  # no push today: cadence.json never reaches D1
    until = NOW + timedelta(hours=24)
    sink = live_cli.HoldsSink(store, None, lambda: NOW)
    sink([("synthetic-blocked", until, "blocked")])  # a 403 in the run's next pass
    assert sink.pending == {}
    pulled = _store(api).take(tmp_path / "successor")  # a handoff to a new runner
    assert pulled.holds == (("synthetic-blocked", until, "blocked"),)
    cadence = tmp_path / "successor" / "cadence.json"
    assert merge_holds(cadence, pulled.holds, NOW) == 1
    assert Cadence._load(cadence)["synthetic-blocked"].not_before == until


def test_a_block_whose_write_failed_is_kept_by_the_end_push(tmp_path: Path) -> None:
    api = FakeD1()
    store = _store(api)
    run = tmp_path / "run"
    store.take(run)
    down = [True]

    def refuse(sql: str) -> None:
        if down[0] and sql.startswith("INSERT INTO holds"):
            raise D1Error("query: HTTP 503")

    api.before = refuse
    until = NOW + timedelta(hours=24)
    sink = live_cli.HoldsSink(store, None, lambda: NOW)
    sink([("synthetic-blocked", until, "blocked")])
    assert set(sink.pending) == {"synthetic-blocked"}  # kept for the next try
    sink.retry()
    assert set(sink.pending) == {"synthetic-blocked"}
    # the reads keep the block in cadence.json; D1 answers again by the end push, which
    # writes every hold cadence.json still has before the state itself
    assert merge_holds(run / "cadence.json", [("synthetic-blocked", until, "blocked")], NOW) == 1
    down[0] = False
    live_cli._end_holds(store, run, NOW)
    pulled = _store(api).take(tmp_path / "successor")
    assert pulled.holds == (("synthetic-blocked", until, "blocked"),)
    # and a pending hold goes at the loop's next try once D1 answers
    sink.retry()
    assert sink.pending == {}


def test_answers_without_rows_written_are_billed_per_statement(tmp_path: Path) -> None:
    api = HttpD1(counted=False)
    store = api.store()
    store.take(tmp_path / "a")
    _state(tmp_path / "a", "first")
    result = store.keep(tmp_path / "a")
    assert result.rows_written >= result.parts + 1  # the upserts and the swap, at least
    assert api.budget() >= result.parts + 2


def test_a_hanging_api_cannot_stretch_a_push_past_its_deadline(tmp_path: Path) -> None:
    api = HttpD1()
    clock = Clock()
    store = api.store(clock)
    store.take(tmp_path / "a")
    _state(tmp_path / "a", "first", size=1_200_000)
    sha = api.head()["sha256"]
    api.tick, api.requests, api.timeouts = 25.0, 0, []  # each request now takes 25 s
    with pytest.raises(D1Error, match="out of time"):
        store.keep(tmp_path / "a", deadline=NOW + timedelta(seconds=60))
    assert api.requests <= 3  # 60 s of 25-s requests, never the whole push
    assert all(timeout <= 60.0 for timeout in api.timeouts)
    assert api.timeouts[-1] < 30.0  # each request's timeout is cut to what is left
    assert api.head()["sha256"] == sha
    # the budget was the push's only: a later push without a deadline goes through
    api.tick = 0.0
    store.keep(tmp_path / "a")
    assert api.head()["sha256"] != sha


def test_a_pull_is_bounded_by_its_limit(tmp_path: Path) -> None:
    api = HttpD1()
    store = api.store()
    store.limit(50.0)
    api.tick = 30.0
    with pytest.raises(D1Error, match="out of time"):
        store.take(tmp_path / "a")
    assert api.requests <= 2


def test_pullable_follows_what_a_pull_would_do(tmp_path: Path) -> None:
    api = FakeD1()
    clock = Clock()
    assert _store(api, clock).pullable()  # no head yet: a pull starts epoch 1
    store = _store(api, clock)
    store.take(tmp_path / "a")
    _state(tmp_path / "a", "first")
    store.keep(tmp_path / "a")
    store.keep(tmp_path / "a")
    assert _store(api, clock).pullable()
    api.db.execute("UPDATE chunks SET data = 'AAAA' WHERE n = 0")
    api.db.commit()
    epoch = api.head()["epoch"]
    clock.now = NOW + timedelta(hours=1)
    assert not _store(api, clock).pullable()  # both slots fail and head is recent
    assert api.head()["epoch"] == epoch  # read only: no epoch taken
    clock.now = NOW + timedelta(hours=2, minutes=1)
    assert _store(api, clock).pullable()  # old enough: the pull starts empty
    assert not _store(FakeD1(list_fails=True), clock).pullable()


def _spent(api: FakeD1 | HttpD1, rows: int) -> None:
    day = NOW.date().isoformat()
    api.db.execute("UPDATE budget SET rows = ? WHERE day = ?", (rows, day))
    api.db.commit()


def test_the_cap_counts_each_chunk_as_two_rows_before_a_push(tmp_path: Path) -> None:
    # an upsert may be billed two rows: a push that would pass the cap only then is refused
    api = FakeD1()
    store = _store(api)
    store.take(tmp_path / "a")
    _state(tmp_path / "a", "first")
    parts = d1.plan_parts(len(pack(tmp_path / "a")))
    assert parts > 1
    _spent(api, d1.WRITE_CAP - (parts + 2) - 1)  # room for one row a chunk, not two
    with pytest.raises(WriteCapError):
        store.keep(tmp_path / "a")
    _spent(api, d1.WRITE_CAP - (2 * parts + 2) - 1)
    store.keep(tmp_path / "a")


def test_the_old_slots_clean_up_waits_when_it_would_pass_the_cap(tmp_path: Path) -> None:
    api = FakeD1()
    first = _store(api)
    first.take(tmp_path / "a")
    _state(tmp_path / "a", "a1")
    first.keep(tmp_path / "a")
    old = api.db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    successor = _store(api)
    successor.take(tmp_path / "b")
    successor.keep(tmp_path / "b")
    parts = d1.plan_parts(len(pack(tmp_path / "b")))
    # the second push's own writes fit, the old epoch's delete does not
    assert 2 * old > parts
    _spent(api, d1.WRITE_CAP - (2 * parts + 2))
    successor.keep(tmp_path / "b")
    slots = {row[0] for row in api.db.execute("SELECT DISTINCT slot FROM chunks")}
    assert "e1a" in slots  # kept: nothing reads it, a later push deletes it
    assert json.loads((tmp_path / "b" / EPOCH_FILE).read_text())["cleaned"] is False
    assert not any(sql.startswith("DELETE FROM chunks") for sql in api.sent)
    total = api.db.execute("SELECT rows FROM budget").fetchone()[0]
    assert total <= d1.WRITE_CAP
    _spent(api, 0)
    successor.keep(tmp_path / "b")
    slots = {row[0] for row in api.db.execute("SELECT DISTINCT slot FROM chunks")}
    assert slots == {"e2a", "e2b"}
    assert json.loads((tmp_path / "b" / EPOCH_FILE).read_text())["cleaned"] is True
    sent = len(api.sent)
    successor.keep(tmp_path / "b")  # cleaned: no count, no delete again this epoch
    later = api.sent[sent:]
    assert not any(sql.startswith(("SELECT COUNT", "DELETE FROM chunks")) for sql in later)


def test_a_write_sent_again_after_a_lost_answer_is_billed_for_both_tries(tmp_path: Path) -> None:
    api = HttpD1()
    store = api.store()
    store.take(tmp_path / "a")
    _state(tmp_path / "a", "first")
    store.keep(tmp_path / "a")
    clean = api.budget()
    api.lose.append("INSERT INTO chunks")  # the first upsert batch ran; its answer was lost
    store.keep(tmp_path / "a")
    lost = api.budget() - clean
    second = HttpD1()
    other = second.store()
    other.take(tmp_path / "c")
    _state(tmp_path / "c", "first")
    other.keep(tmp_path / "c")
    before = second.budget()
    other.keep(tmp_path / "c")
    plain = second.budget() - before
    assert lost >= plain + min(d1.WRITE_BATCH, d1.plan_parts(len(pack(tmp_path / "a"))))
