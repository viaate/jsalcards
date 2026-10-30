"""The evidence store (advisory-sane L0): every finished morning record kept for good, in two D1
databases, against an in-memory SQLite stand-in for D1 and, end to end, a stub Cloudflare API.
SYNTHETIC records only.

* finished days only (a morning day 2 hours after it ends, a change-log day 4 days after);
* append-only: no statement changes or removes a row, a pushed day is never written again, and
  a file that changed is kept again beside its first version;
* both databases written; one lost or recreated is filled again from the other, days the
  state folder no longer holds included;
* every part read back is checked against its sha256 and size; a damaged copy is not copied;
* only the live reader keeps morning records and change logs, only the predict chain snapshots;
* a push writes at most its row budget, and the next push goes on.
"""

import dataclasses
import io
import json
import re
import sqlite3
import tarfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from live.test_state_export import morning as synthetic_morning
from snowlight.live import cli as live_cli
from snowlight.live import evidence, kept
from snowlight.live.d1 import Answer, D1Error, Statement
from snowlight.live.evidence import (
    BACKUP,
    CHANGES,
    DISTRICTS,
    MORNING,
    PRIMARY,
    SNAPSHOT,
    STATEMENTS,
    EvidenceError,
    EvidenceStore,
    Offer,
    PartialPushError,
    export_offers,
    item_of,
    snapshot_offers,
    state_offers,
    unpack,
)
from snowlight.live.morning import MorningLog

NOW = datetime(2026, 1, 9, 12, tzinfo=UTC)
LIVE = {"GITHUB_WORKFLOW": "live-read", "GITHUB_RUN_ID": "77"}
PREDICT = {"GITHUB_WORKFLOW": "predict", "GITHUB_RUN_ID": "78"}


@dataclass
class FakeD1:
    """D1 as one in-memory SQLite database per D1 database; ``broken`` names fail every call."""

    dbs: dict[str, sqlite3.Connection] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)
    broken: set[str] = field(default_factory=set)
    sent: list[str] = field(default_factory=list)
    made: int = 0

    def databases(self, name: str) -> list[tuple[str, str]]:
        return [(n, uuid) for n, uuid in self.names.items() if name in n]

    def create(self, name: str) -> str:
        self.made += 1
        uuid = f"uuid-{self.made}"
        self.names[name] = uuid
        self.dbs[uuid] = sqlite3.connect(":memory:")
        return uuid

    def run(self, database: str, statements: Sequence[Statement]) -> list[Answer]:
        name = next(n for n, uuid in self.names.items() if uuid == database)
        if name in self.broken:
            raise D1Error("query: HTTP 500")
        db = self.dbs[database]
        answers = []
        for sql, params in statements:
            self.sent.append(sql)
            before = db.total_changes
            cursor = db.execute(sql, params)
            names = [column[0] for column in cursor.description or ()]
            rows = tuple(dict(zip(names, row, strict=True)) for row in cursor.fetchall())
            db.commit()
            changes = db.total_changes - before
            answers.append(Answer(rows=rows, rows_written=changes, changes=changes))
        return answers

    def drop(self, name: str) -> None:
        """The database is deleted (by hand): the next push creates it again."""
        uuid = self.names.pop(name)
        self.dbs.pop(uuid).close()

    def count(self, name: str, table: str) -> int:
        db = self.dbs[self.names[name]]
        return int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # noqa: S608


def _state(folder: Path) -> Path:
    """A SYNTHETIC state folder: morning days Jan 6 and today (Jan 9), change-log days Jan 2,
    Jan 5 and today."""
    synthetic_morning(folder)
    log = MorningLog(folder / "morning")
    log.record(NOW, shown="v1", reads={"tv": (3, 3, 0)}, unknown=(), named={})
    (folder / "changes" / "2026-01-09.jsonl").write_text('{"SYNTHETIC": 1}\n', encoding="utf-8")
    return folder


def _store(api: FakeD1, env: dict[str, str] = LIVE, **kwargs: Any) -> EvidenceStore:
    return EvidenceStore(api, env, lambda: NOW, **kwargs)


def test_only_finished_days_are_offered(tmp_path: Path) -> None:
    state = _state(tmp_path / "state")
    offers = state_offers(state, NOW)
    assert [(o.kind, o.key) for o in offers] == [
        (MORNING, "2026-01-06"),
        (CHANGES, "2026-01-02"),
        (CHANGES, "2026-01-05"),
    ]
    # Jan 9's morning is final from 02:00 on Jan 10; Jan 5's change log is not yet at 4 days on
    # Jan 8, Jan 9's on Jan 13.
    assert MORNING in {o.kind for o in state_offers(state, datetime(2026, 1, 10, 2, tzinfo=UTC))}
    late = [(o.kind, o.key) for o in state_offers(state, datetime(2026, 1, 10, 1, tzinfo=UTC))]
    assert (MORNING, "2026-01-09") not in late
    early = {o.key for o in state_offers(state, datetime(2026, 1, 8, 12, tzinfo=UTC))}
    assert "2026-01-05" not in early


def test_a_push_keeps_both_databases_and_pulls_back_the_same_bytes(tmp_path: Path) -> None:
    state = _state(tmp_path / "state")
    api = FakeD1()
    store = _store(api)
    reports = store.push(state_offers(state, NOW), (MORNING, CHANGES))
    assert [(r.database, r.held, r.kept, r.copied) for r in reports] == [
        (PRIMARY, 0, 3, 0),
        (BACKUP, 0, 3, 0),
    ]
    for name in (PRIMARY, BACKUP):
        assert api.count(name, "items") == 3
    pulled = _store(api).pull(MORNING)
    assert pulled == {"2026-01-06": (state / "morning" / "2026-01-06.json").read_bytes()}
    changes = _store(api).pull(CHANGES, since=date(2026, 1, 3))
    assert changes == {"2026-01-05": (state / "changes" / "2026-01-05.jsonl").read_bytes()}
    # pushed again: nothing is written
    again = _store(api).push(state_offers(state, NOW), (MORNING, CHANGES))
    assert [(r.held, r.kept, r.rows_written) for r in again] == [(3, 0, 0), (3, 0, 0)]


def test_no_statement_changes_or_removes_a_row() -> None:
    for sql in STATEMENTS:
        assert not re.search(
            r"\b(UPDATE|DELETE|DROP|REPLACE|ALTER)\b", sql.replace("DO NOTHING", "")
        )
        if sql.startswith("INSERT"):
            assert sql.endswith("DO NOTHING")


def test_a_file_that_changed_is_kept_again_beside_its_first_version(tmp_path: Path) -> None:
    state = _state(tmp_path / "state")
    api = FakeD1()
    _store(api).push(state_offers(state, NOW), (MORNING, CHANGES))
    path = state / "changes" / "2026-01-05.jsonl"
    first = path.read_bytes()
    path.write_bytes(first + b'{"SYNTHETIC": "late line"}\n')
    later = EvidenceStore(api, LIVE, lambda: NOW + timedelta(hours=6))
    reports = later.push(state_offers(state, NOW + timedelta(hours=6)), (MORNING, CHANGES))
    assert [r.kept for r in reports] == [1, 1]
    assert api.count(PRIMARY, "items") == 4
    assert later.pull(CHANGES)["2026-01-05"] == path.read_bytes()
    kept = {
        row[0]
        for row in api.dbs[api.names[PRIMARY]].execute(
            "SELECT bytes FROM items WHERE kind = 'changes' AND key = '2026-01-05'"
        )
    }
    assert kept == {len(first), len(path.read_bytes())}


def test_a_lost_database_is_filled_again_from_the_other(tmp_path: Path) -> None:
    state = _state(tmp_path / "state")
    api = FakeD1()
    _store(api).push(state_offers(state, NOW), (MORNING, CHANGES))
    # The backup is deleted by hand, and the state folder no longer holds Jan 2 (pruned).
    api.drop(BACKUP)
    (state / "changes" / "2026-01-02.jsonl").unlink()
    reports = _store(api).push(state_offers(state, NOW), (MORNING, CHANGES))
    assert [(r.database, r.kept, r.copied) for r in reports] == [(PRIMARY, 0, 0), (BACKUP, 3, 1)]
    api.drop(PRIMARY)
    reports = _store(api).push([], (MORNING, CHANGES))
    assert [(r.database, r.kept, r.copied) for r in reports] == [(PRIMARY, 3, 3), (BACKUP, 0, 0)]
    assert set(_store(api).pull(CHANGES)) == {"2026-01-02", "2026-01-05"}


def test_one_database_failing_still_writes_the_other(tmp_path: Path) -> None:
    state = _state(tmp_path / "state")
    api = FakeD1()
    _store(api).push([], (MORNING,))  # both exist
    api.broken.add(PRIMARY)
    with pytest.raises(PartialPushError) as caught:
        _store(api).push(state_offers(state, NOW), (MORNING, CHANGES))
    assert [(r.database, r.kept) for r in caught.value.reports] == [(BACKUP, 3)]
    api.broken = {PRIMARY, BACKUP}
    with pytest.raises(EvidenceError):
        _store(api).push(state_offers(state, NOW), (MORNING, CHANGES))
    api.broken = {PRIMARY}
    assert set(_store(api).pull(MORNING)) == {"2026-01-06"}  # read from the backup


def test_every_part_is_checked_and_a_damaged_copy_is_not_copied() -> None:
    offer = Offer(MORNING, "2026-01-06", b'{"SYNTHETIC": true}' * 1000)
    item, parts = item_of(offer, "2026-01-09T12:00:00+00:00")
    assert unpack(item, parts) == offer.data
    with pytest.raises(EvidenceError):
        unpack(item, [])
    with pytest.raises(EvidenceError):
        unpack(item, ["AAAA" + parts[0][4:]])
    api = FakeD1()
    _store(api).push([offer], (MORNING,))
    api.dbs[api.names[PRIMARY]].execute("UPDATE parts SET data = 'AAAA' || substr(data, 5)")
    api.dbs[api.names[PRIMARY]].commit()
    api.drop(BACKUP)
    reports = _store(api).push([], (MORNING,))
    assert [(r.database, r.kept) for r in reports] == [(PRIMARY, 0), (BACKUP, 0)]
    assert api.count(BACKUP, "items") == 0
    assert _store(api).pull(MORNING) == {}


def test_only_the_live_reader_keeps_mornings_and_only_predict_snapshots(tmp_path: Path) -> None:
    offers = state_offers(_state(tmp_path / "state"), NOW)
    api = FakeD1()
    for env in ({}, PREDICT, {"GITHUB_WORKFLOW": "ci"}):
        with pytest.raises(EvidenceError, match="does not keep"):
            _store(api, env).push(offers, (MORNING, CHANGES))
    with pytest.raises(EvidenceError, match="does not keep"):
        _store(api, LIVE).push([], (SNAPSHOT,))
    assert api.names == {}
    assert _store(api, PREDICT).push([], (SNAPSHOT, DISTRICTS))


def test_a_push_keeps_to_its_row_budget_and_the_next_goes_on(tmp_path: Path) -> None:
    offers = state_offers(_state(tmp_path / "state"), NOW)
    api = FakeD1()
    first = _store(api, max_rows=4).push(offers, (MORNING, CHANGES))
    assert [(r.kept, r.left) for r in first] == [(2, 1), (2, 1)]
    assert all(r.rows_written <= 4 for r in first)
    second = _store(api, max_rows=4).push(offers, (MORNING, CHANGES))
    assert [(r.kept, r.left) for r in second] == [(1, 0), (1, 0)]


def test_a_push_keeps_to_its_time_and_the_next_goes_on(tmp_path: Path) -> None:
    offers = state_offers(_state(tmp_path / "state"), NOW)
    api = FakeD1()
    ticks = iter(range(100))
    late = _store(api, seconds=1.5, monotonic=lambda: float(next(ticks)))
    reports = late.push(offers, (MORNING, CHANGES))
    # the clock reads 0 at the start, then once per database per version
    assert [(r.kept, r.left) for r in reports] == [(1, 2), (0, 3)]
    reports = _store(api).push(offers, (MORNING, CHANGES))
    assert [(r.held, r.kept) for r in reports] == [(1, 2), (0, 3)]


def test_snapshots_are_offered_once_their_day_has_begun_with_their_district_table() -> None:
    snapshots: dict[str, object] = {
        "2026-01-08": {"content": "c" * 64, "classes": "01-", "taken": {"America/Chicago": "x"}},
        "2026-01-10": {"content": "c" * 64, "classes": "000", "taken": {}},
        "bad": {},
    }
    offers = snapshot_offers(snapshots, {"c" * 64: ["2900001", "2900002", "2900003"]}, NOW)
    assert [(o.kind, o.key) for o in offers] == [(SNAPSHOT, "2026-01-08"), (DISTRICTS, "c" * 64)]
    assert json.loads(offers[0].data)["classes"] == "01-"
    assert offers[1].data == b"2900001\n2900002\n2900003\n"
    assert snapshot_offers(snapshots, {}, NOW)[1:] == []


# --- end to end, over a stub Cloudflare API -------------------------------------------------


@dataclass
class HttpD1:
    """The Cloudflare D1 API in front of :class:`FakeD1`."""

    fake: FakeD1 = field(default_factory=FakeD1)

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path.endswith("/d1/database"):
            name = request.url.params.get("name", "")
            found = [{"name": n, "uuid": u} for n, u in self.fake.databases(name)]
            return httpx.Response(200, json={"success": True, "result": found})
        if request.method == "POST" and path.endswith("/d1/database"):
            uuid = self.fake.create(json.loads(request.content)["name"])
            return httpx.Response(200, json={"success": True, "result": {"uuid": uuid}})
        uuid = path.split("/")[-2]
        body = json.loads(request.content)
        items = body.get("batch", [body])
        answers = self.fake.run(uuid, [(i["sql"], tuple(i["params"])) for i in items])
        result = [
            {"success": True, "results": list(a.rows), "meta": {"rows_written": a.rows_written}}
            for a in answers
        ]
        return httpx.Response(200, json={"success": True, "result": result})


def test_live_evidence_push_pull_and_size_end_to_end(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state = _state(tmp_path / "state")
    api = HttpD1()
    env = {**LIVE, "CLOUDFLARE_API_TOKEN": "t", "CLOUDFLARE_ACCOUNT_ID": "a"}
    loaders = live_cli.Loaders(
        client=lambda: httpx.Client(transport=httpx.MockTransport(api.handler)),
        env=lambda: env,
        clock=lambda: NOW,
    )
    args = _args("push", state=state)
    assert live_cli.run_evidence(args, loaders) == 0
    out = capsys.readouterr().out
    assert re.search(r"morning record: 2 days, \d+ B \(2026-01-06 to 2026-01-09\)\n", out)
    assert f"evidence {PRIMARY}: 3 finished files offered, 0 held before, 3 kept" in out
    assert f"evidence {BACKUP}: 3 finished files offered" in out
    pulled = tmp_path / "pulled"
    assert live_cli.run_evidence(_args("pull", state=state, out=pulled), loaders) == 0
    assert (pulled / "morning" / "2026-01-06.json").read_bytes() == (
        state / "morning" / "2026-01-06.json"
    ).read_bytes()
    assert live_cli.run_evidence(_args("size", state=state), loaders) == 0
    assert f"evidence {BACKUP}: morning 1 versions" in capsys.readouterr().out
    # without the secrets: an error line, exit 1, nothing else
    bare = dataclasses.replace(loaders, env=lambda: LIVE)
    assert live_cli.run_evidence(_args("push", state=state), bare) == 1


def _args(action: str, *, state: Path, out: Path | None = None) -> Any:
    import argparse  # noqa: PLC0415

    return argparse.Namespace(
        evidence_action=action, state=state, kind=MORNING, since=None, out=out or state / "x"
    )


def test_the_evidence_command_is_registered() -> None:
    from snowlight import cli  # noqa: PLC0415

    found = cli.build_parser().parse_args(["live", "evidence", "push"])
    assert found.handler is live_cli.run_evidence
    assert evidence.WRITERS["live-read"] == {MORNING, CHANGES}


def test_a_push_says_what_each_database_holds_and_warns_near_the_limit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state(tmp_path / "state")
    api = HttpD1()
    env = {**LIVE, "CLOUDFLARE_API_TOKEN": "t", "CLOUDFLARE_ACCOUNT_ID": "a"}
    loaders = live_cli.Loaders(
        client=lambda: httpx.Client(transport=httpx.MockTransport(api.handler)),
        env=lambda: env,
        clock=lambda: NOW,
    )
    assert live_cli.run_evidence(_args("push", state=state), loaders) == 0
    out = capsys.readouterr().out
    assert re.search(rf"evidence {PRIMARY}: .*; it holds \d+ B in all\n", out)
    assert "::warning::" not in out
    monkeypatch.setattr(evidence, "WARN_BYTES", 10)
    assert live_cli.run_evidence(_args("push", state=state), loaders) == 0
    out = capsys.readouterr().out
    assert f"::warning::The evidence database {PRIMARY} holds" in out


# --- round 2: an item row only after a whole read-back, the reader's check, the export ------


def test_an_item_row_is_written_only_after_its_parts_read_back_whole() -> None:
    offer = Offer(MORNING, "2026-01-06", b'{"SYNTHETIC": true}' * 100)
    api = FakeD1()
    real = api.run

    def damaging(database: str, statements: Sequence[Statement]) -> list[Answer]:
        answers = real(database, statements)
        if statements and statements[0][0].startswith("SELECT n, data FROM parts"):
            return [Answer(rows=(), rows_written=0, changes=0)]  # the read-back finds nothing
        return answers

    api.run = damaging  # type: ignore[method-assign]
    with pytest.raises(EvidenceError):
        _store(api).push([offer], (MORNING,))
    for name in (PRIMARY, BACKUP):
        assert api.count(name, "parts") == 1
        assert api.count(name, "items") == 0  # no item row: the day is not held
    api.run = real  # type: ignore[method-assign]
    assert _store(api).held((MORNING,)) == {PRIMARY: {}, BACKUP: {}}
    _store(api).push([offer], (MORNING,))
    digest = item_of(offer, "")[0].sha256
    assert _store(api).held((MORNING,)) == {
        name: {(MORNING, "2026-01-06"): frozenset({digest})} for name in (PRIMARY, BACKUP)
    }


def test_the_readers_question_never_creates_or_writes_a_database(tmp_path: Path) -> None:
    api = FakeD1()
    assert _store(api, {}).held((MORNING, CHANGES)) == {PRIMARY: {}, BACKUP: {}}
    assert api.names == {}
    assert api.sent == []
    state = _state(tmp_path / "state")
    _store(api).push(state_offers(state, NOW), (MORNING, CHANGES))
    api.sent.clear()
    found = _store(api, {}).held((MORNING, CHANGES), "2026-01-05")
    # from the day asked on
    assert set(found[PRIMARY]) == {(CHANGES, "2026-01-05"), (MORNING, "2026-01-06")}
    assert all(sql.startswith("SELECT kind, key, sha256 FROM items") for sql in api.sent)
    api.broken.add(PRIMARY)
    assert set(_store(api, {}).held((MORNING,))) == {BACKUP}
    api.broken.add(BACKUP)
    with pytest.raises(EvidenceError):
        _store(api, {}).held((MORNING,))


def test_only_versions_a_database_lacks_are_compressed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    offers = state_offers(_state(tmp_path / "state"), NOW)
    api = FakeD1()
    calls: list[int] = []
    real = evidence.compress

    def counted(data: bytes) -> bytes:
        calls.append(len(data))
        return real(data)

    monkeypatch.setattr(evidence, "compress", counted)
    _store(api).push(offers, (MORNING, CHANGES))
    assert len(calls) == 3  # once a version, for both databases
    calls.clear()
    # a later push, everything held: nothing compressed, and no time spent before the budget
    ticks = iter(range(100))
    again = _store(api, seconds=0.5, monotonic=lambda: float(next(ticks)))
    reports = again.push(offers, (MORNING, CHANGES))
    assert calls == []
    assert [(r.held, r.kept, r.left) for r in reports] == [(3, 0, 0), (3, 0, 0)]


def test_the_evidence_job_reads_the_export_archive_and_nothing_else(tmp_path: Path) -> None:
    state = _state(tmp_path / "state")
    archive = tmp_path / "live-state.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for path in sorted(state.rglob("*")):
            if path.is_file():
                tar.add(path, arcname=path.relative_to(state).as_posix())
        for name, data in (("../escape/2026-01-01.json", b"x"), ("ledger.sqlite", b"y")):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    offers = export_offers(archive, NOW)
    assert [(o.kind, o.key, o.data) for o in offers] == [
        (o.kind, o.key, o.data) for o in sorted(state_offers(state, NOW), key=_order)
    ]


def _order(offer: Offer) -> tuple[str, str]:
    return offer.kind, offer.key


def test_pull_falls_back_to_an_older_version_and_pulls_every_version(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    api = FakeD1()
    first = Offer(CHANGES, "2026-01-05", b'{"SYNTHETIC": 1}\n')
    second = Offer(CHANGES, "2026-01-05", b'{"SYNTHETIC": 1}\n{"SYNTHETIC": 2}\n')
    _store(api).push([first], (CHANGES,))
    EvidenceStore(api, LIVE, lambda: NOW + timedelta(hours=1)).push([second], (CHANGES,))
    assert _store(api).pull(CHANGES) == {"2026-01-05": second.data}
    assert "kept in 2 versions" in caplog.text
    every = _store(api).pull_all(CHANGES)
    assert sorted(every.values()) == sorted([first.data, second.data])
    written = evidence.write_pulled(every, CHANGES, tmp_path / "out")
    assert len(written) == 2
    assert all(re.fullmatch(r"2026-01-05\.[0-9a-f]{12}\.jsonl", path.name) for path in written)
    # the newest version is damaged in both databases: the older one is used, and named
    newest = item_of(second, "")[0].sha256
    for name in (PRIMARY, BACKUP):
        db = api.dbs[api.names[name]]
        db.execute("UPDATE parts SET data = 'AAAA' WHERE sha256 = ?", (newest,))
        db.commit()
    caplog.clear()
    assert _store(api).pull(CHANGES) == {"2026-01-05": first.data}
    assert "the newest version does not read" in caplog.text


def test_the_loops_check_writes_what_both_databases_hold(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state = _state(tmp_path / "state")
    api = FakeD1()
    _store(api).push(state_offers(state, NOW), (MORNING, CHANGES))
    found = live_cli.check_evidence(_store(api, {}), state, NOW, seconds=5)
    assert found == kept.Verdict(False)
    assert "evidence check: 1 of 2 morning days in both databases (2 answered)" in (
        capsys.readouterr().out
    )
    record = kept.read_kept(state)
    assert record.checked == NOW
    assert record.copies[kept.MORNING]["2026-01-06"].databases == kept.DATABASES
    assert record.copies[kept.MORNING]["2026-01-09"].databases == ()  # not finished yet
    log = MorningLog(state / "morning")
    assert log.prune(date(2026, 2, 25)) == [date(2026, 1, 6)]  # kept, 50 days on: it goes


def test_a_day_left_unkept_opens_the_alert_after_2_days_and_a_failed_check_keeps_what_it_knew(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state = _state(tmp_path / "state")
    api = FakeD1()
    store = _store(api, {})
    # The first check: nothing is kept yet; the grace runs from it.
    assert live_cli.check_evidence(store, state, NOW, seconds=5) == kept.Verdict(False)
    day_later = NOW + timedelta(days=1)
    assert not live_cli.check_evidence(store, state, day_later, seconds=5).active
    late = NOW + timedelta(days=2, minutes=1)
    found = live_cli.check_evidence(store, state, late, seconds=5)
    # Jan 6's morning, and the change-log days of Jan 2 and Jan 5: none in either database
    assert found == kept.Verdict(True, "unkept", 3)
    assert "; 3 unkept" in capsys.readouterr().out
    # The push keeps them, but the next check fails: what it knew stays, the alert with it.
    _store(api).push(state_offers(state, late), (MORNING, CHANGES))
    api.broken = {PRIMARY, BACKUP}
    found = live_cli.check_evidence(store, state, late + timedelta(hours=1), seconds=5)
    assert found == kept.Verdict(True, "unkept", 3)
    assert "what it knew stays" in capsys.readouterr().out
    # Both answer again: the alert closes.
    api.broken = set()
    assert live_cli.check_evidence(store, state, late + timedelta(hours=2), seconds=5) == (
        kept.Verdict(False)
    )
    # One database not answering an hourly check changes nothing known of it: no false alarm.
    api.broken = {BACKUP}
    found = live_cli.check_evidence(store, state, late + timedelta(hours=3), seconds=5)
    assert found == kept.Verdict(False)
    assert "(1 answered)" in capsys.readouterr().out
    assert kept.read_kept(state).checked == late + timedelta(hours=2)  # not every one answered
    api.broken = set()
    assert not live_cli.check_evidence(store, state, late + timedelta(hours=4), seconds=5).active
    # Only one database holding a day keeps the alert open (the backup is the point): the
    # backup is lost, and answers that it holds nothing.
    api.drop(BACKUP)
    found = live_cli.check_evidence(_store(api, {}), state, late + timedelta(hours=5), seconds=5)
    assert found == kept.Verdict(True, "unkept", 3)
    # A check that cannot even write kept.json says so and never raises.
    (state / kept.KEPT).unlink()
    (state / kept.KEPT).mkdir()
    assert live_cli.check_evidence(store, state, late, seconds=5) is None


def test_the_runner_asks_in_its_idle_time_and_raises_the_evidence_alert(tmp_path: Path) -> None:
    from types import SimpleNamespace  # noqa: PLC0415

    from snowlight.live.alerts import AlertBook, Kind  # noqa: PLC0415

    state = _state(tmp_path / "state")
    opened: list[str] = []
    sink = SimpleNamespace(
        opened=lambda alert, _book: opened.append(alert.kind),
        updated=lambda _alert, _book: None,
        closed=lambda alert, _at, _book: opened.append(f"closed {alert.kind}"),
    )
    book = AlertBook(sink, "v1")
    clock = {"now": NOW + timedelta(days=3)}
    runner = live_cli.Runner(
        args=SimpleNamespace(state=state),  # type: ignore[arg-type]
        config=None,  # type: ignore[arg-type]
        env={},
        parts=None,  # type: ignore[arg-type]
        loaders=SimpleNamespace(clock=lambda: clock["now"]),  # type: ignore[arg-type]
        alerts=SimpleNamespace(book=book),  # type: ignore[arg-type]
    )
    api = FakeD1()
    runner.evidence = _store(api, {})
    write_kept = kept.write_kept
    write_kept(state, kept.Kept(watch_from=NOW))
    now = clock["now"]
    runner.state = live_cli._Loop(due=now + timedelta(minutes=4), next_check=now)
    runner.state.next_evidence = now
    # too close to the next grid mark: it waits for a later idle time
    runner.check_evidence(now + timedelta(minutes=3, seconds=20))
    assert runner.state.next_evidence == now
    runner.idle(now)
    assert runner.state.next_evidence == now + live_cli.EVIDENCE_EVERY
    assert opened == [Kind.EVIDENCE.value]
    # Jan 12: the mornings of Jan 6 and Jan 9, the change logs of Jan 2 and Jan 5
    assert book.open[Kind.EVIDENCE.value].detail == {"why": "unkept", "count": 4}
    _store(api).push(state_offers(state, now), (MORNING, CHANGES))
    later = now + live_cli.EVIDENCE_EVERY
    runner.state = live_cli._Loop(due=later + timedelta(minutes=4), next_check=later)
    runner.state.next_evidence = later
    clock["now"] = later
    runner.idle(later)
    assert opened == [Kind.EVIDENCE.value, f"closed {Kind.EVIDENCE.value}"]


def test_the_loop_asks_the_evidence_store_only_for_a_d1_state() -> None:
    config = SimpleConfig({"kind": "local", "folder": "x"})
    assert live_cli.make_evidence_reader(config, LIVE, httpx.Client()) is None  # type: ignore[arg-type]
    d1 = SimpleConfig({"kind": "d1"})
    assert live_cli.make_evidence_reader(d1, LIVE, httpx.Client()) is None  # type: ignore[arg-type]
    env = {**LIVE, "CLOUDFLARE_API_TOKEN": "t", "CLOUDFLARE_ACCOUNT_ID": "a"}
    found = live_cli.make_evidence_reader(d1, env, httpx.Client())  # type: ignore[arg-type]
    assert isinstance(found, EvidenceStore)


@dataclass
class SimpleConfig:
    state: dict[str, str]


def test_live_evidence_push_from_the_export_end_to_end(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from snowlight.live.state import export  # noqa: PLC0415

    state = _state(tmp_path / "state")
    kept.write_kept(state, kept.Kept(watch_from=NOW))  # packed with the state, never exported
    archive = tmp_path / "store" / "live-state.tar.gz"
    archive.parent.mkdir()
    archive.write_bytes(export(state))
    api = HttpD1()
    env = {**LIVE, "CLOUDFLARE_API_TOKEN": "t", "CLOUDFLARE_ACCOUNT_ID": "a"}
    loaders = live_cli.Loaders(
        client=lambda: httpx.Client(transport=httpx.MockTransport(api.handler)),
        env=lambda: env,
        clock=lambda: NOW,
    )
    args = _args("push", state=tmp_path / "nowhere")
    args.export = archive
    assert live_cli.run_evidence(args, loaders) == 0
    out = capsys.readouterr().out
    assert "morning record: 1 finished days in the export (2026-01-06 to 2026-01-06)" in out
    assert f"evidence {PRIMARY}: 3 finished files offered, 0 held before, 3 kept" in out
    # a failure says so in one ::error:: line, and the step's exit is 1
    api.fake.broken = {PRIMARY, BACKUP}
    assert live_cli.run_evidence(args, loaders) == 1
    assert "::error::The evidence store was not fully written" in capsys.readouterr().out


def test_the_morning_line_never_raises_and_counts_day_files_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state(tmp_path / "state")
    kept.write_kept(state, kept.Kept(watch_from=NOW))
    (state / "morning" / "notes.json").write_text("{}", encoding="utf-8")
    line = live_cli.morning_line(state / "morning")
    assert re.fullmatch(r"morning record: 2 days, \d+ B \(2026-01-06 to 2026-01-09\)", line)
    assert live_cli.morning_line(tmp_path / "none") == "morning record: 0 days, 0 B"

    def broken(_self: Path, _pattern: str) -> list[Path]:
        raise PermissionError

    monkeypatch.setattr(Path, "glob", broken)
    assert live_cli.morning_line(state / "morning") == (
        "morning record: unreadable (PermissionError)"
    )


def test_a_database_that_did_not_answer_keeps_what_was_known_of_it() -> None:
    before = {MORNING: {"2026-01-06": kept.Copy("a" * 64, kept.DATABASES)}}
    digests = {MORNING: {"2026-01-06": "a" * 64, "2026-01-07": "b" * 64}}
    only_primary = {PRIMARY: {(MORNING, "2026-01-07"): frozenset({"b" * 64})}}
    after = kept.merge_answer(before, only_primary, digests)
    # the primary answered: it holds Jan 7 but no longer Jan 6; the silent backup keeps Jan 6
    assert after[MORNING]["2026-01-06"].databases == (BACKUP,)
    assert after[MORNING]["2026-01-07"].databases == (PRIMARY,)
    # a file that changed is not held by a database that stayed silent
    changed = {MORNING: {"2026-01-06": "c" * 64}}
    assert kept.merge_answer(before, {PRIMARY: {}}, changed)[MORNING]["2026-01-06"].databases == ()
    # a day the folder no longer holds is forgotten
    assert kept.merge_answer(before, only_primary, {}) == {}


@dataclass
class SlowD1(FakeD1):
    """A FakeD1 with a deadline and a clock: the primary takes ``slow`` seconds (or never
    answers, past its deadline), and every deadline set is seen."""

    deadline: float | None = None
    now: float = 0.0
    slow: float = 0.0
    deadlines: list[tuple[str, float]] = field(default_factory=list)

    def monotonic(self) -> float:
        return self.now

    def databases(self, name: str) -> list[tuple[str, str]]:
        if self.deadline is None:  # the push that fills it
            return super().databases(name)
        self.deadlines.append((name, self.deadline - self.now))
        if name == PRIMARY:
            self.now = min(self.now + self.slow, self.deadline)
            if self.now >= self.deadline:
                raise D1Error("list databases: out of time")
        return super().databases(name)


def test_each_database_gets_its_own_share_of_the_checks_time(tmp_path: Path) -> None:
    state = _state(tmp_path / "state")
    api = SlowD1(slow=1_000.0)  # the primary never answers
    _store(api).push(state_offers(state, NOW), (MORNING, CHANGES))
    api.deadlines.clear()
    api.deadline = None
    found = _store(api, {}).held((MORNING, CHANGES), seconds=20)
    # the primary gets half; the backup the half left after it ran out, and answers
    assert api.deadlines == [(PRIMARY, 10.0), (BACKUP, 10.0)]
    assert set(found) == {BACKUP}
    assert api.deadline is None  # the client's own deadline is as it was
    # a fast primary leaves its unused time to the backup
    api.slow, api.now = 2.0, 0.0
    api.deadlines.clear()
    _store(api, {}).held((MORNING,), seconds=20)
    assert api.deadlines == [(PRIMARY, 10.0), (BACKUP, 18.0)]


def test_with_no_store_to_ask_a_dropped_day_still_opens_the_evidence_alert(
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace  # noqa: PLC0415

    from snowlight.live.alerts import AlertBook, Kind  # noqa: PLC0415

    state = _state(tmp_path / "state")
    opened: list[str] = []
    sink = SimpleNamespace(
        opened=lambda alert, _book: opened.append(alert.kind),
        updated=lambda _alert, _book: None,
        closed=lambda alert, _at, _book: opened.append(f"closed {alert.kind}"),
    )
    book = AlertBook(sink, "v1")
    clock = {"now": NOW}
    runner = live_cli.Runner(
        args=SimpleNamespace(state=state),  # type: ignore[arg-type]
        config=None,  # type: ignore[arg-type]
        env={},
        parts=None,  # type: ignore[arg-type]
        loaders=SimpleNamespace(clock=lambda: clock["now"]),  # type: ignore[arg-type]
        alerts=SimpleNamespace(book=book),  # type: ignore[arg-type]
    )
    assert runner.evidence is None
    runner.state = live_cli._Loop(due=NOW + timedelta(minutes=4), next_check=NOW)
    runner.state.next_evidence = NOW
    runner.idle(NOW)
    assert opened == []  # nothing dropped: nothing to say
    kept.note_dropped(state, [date(2026, 1, 2)], NOW)
    clock["now"] = NOW + live_cli.EVIDENCE_EVERY
    runner.idle(clock["now"])
    assert opened == [Kind.EVIDENCE.value]
    assert book.open[Kind.EVIDENCE.value].detail == {"why": "dropped", "count": 1}
    # a week on, the alert closes (the ::error:: line and the record said it)
    clock["now"] = NOW + kept.DROPPED_FOR + live_cli.EVIDENCE_EVERY
    runner.idle(clock["now"])
    assert opened == [Kind.EVIDENCE.value, f"closed {Kind.EVIDENCE.value}"]
