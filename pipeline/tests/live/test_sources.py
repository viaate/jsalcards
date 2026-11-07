"""The lit statuses' sources for the admin page (ADMIN-SOURCES), against the in-memory SQLite
stand-in for D1 with the accounts database's own migration. SYNTHETIC provenance lines only.

* the shipped parts decode to each day's summary: ids, types, links and times, no row key;
* an unchanged file asks nothing; the same content only updates the heads' times;
* days before yesterday are deleted, yesterday is kept as last shipped;
* the day's row cap ships nothing past it; a day too big keeps its last version;
* only a live-read run ships, the accounts database is never created, and nothing but the
  fixed statements on the shipper's own tables is sent;
* in the loop, a failure is one line and never raises; the log line holds counts only;
* each head carries the publisher's mode (shadow is labelled; off ships nothing) and, after a
  blank publish that left the file as it was, when the map was published again;
* rows a shipment wrote are billed even when it ran out of time or an answer was lost;
* the links come from real registry stations, and the loop's shipper gets them.
"""

import argparse
import base64
import gzip
import hashlib
import json
import os
import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from live.test_d1_store import ENV, FakeD1
from live.world import station
from snowlight.live import cli as live_cli
from snowlight.live import sources
from snowlight.live.d1 import D1Error, D1StateStore
from snowlight.live.publish import Memory, Mode
from snowlight.live.sources import STATEMENTS, SourcesError, SourcesShipper
from snowlight.schemas.live import local_days

AT = datetime(2026, 11, 17, 18, 0, 5, tzinfo=UTC)
MIGRATION = Path(__file__).parents[3] / "api" / "migrations" / "0005_lit_sources.sql"
LINKS = {
    "synthetic-station-a": "https://example.test/closings",
    "synthetic-list-b": "https://b.test/",
}


def _line(nces: str, day: date, source: str = "synthetic-station-a") -> dict[str, Any]:
    """SYNTHETIC: one provenance line as merge.py writes it."""
    key = hashlib.sha256(f"{nces}{source}".encode()).hexdigest()[:32]
    other = hashlib.sha256(f"{nces}b".encode()).hexdigest()[:32]
    return {
        "nces_id": nces,
        "school": 7,
        "day": day.isoformat(),
        "status": 1,
        "reason": 2,
        "source_type": "broadcaster_list",
        "source_id": source,
        "row_key": key,
        "lo": "2026-11-17T10:00:00+00:00",
        "hi": "2026-11-17T17:55:00+00:00",
        "row_stamp": "2026-11-17T10:00:00+00:00",
        "f5_confidence": 0.9,
        "f5_notes": [],
        "match_reason": "name",
        "match_level": "district",
        "target_level": "district",
        "match_confidence": 0.95,
        "derived_version": "f5-1",
        "generated_at": "2026-11-17T18:00:00+00:00",
        "present": True,
        "contributing": [
            [source, "broadcaster_list", key],
            ["synthetic-list-b", "aggregator_list", other],
        ],
        "announced_by": other,
        "sources": 2,
    }


def _write(
    path: Path, lines: list[dict[str, Any]], at: datetime = AT, *, generated: datetime | None = None
) -> None:
    """The file as the publisher writes it: its lines stamped ``generated`` (the publish's
    ``generated_at``; the file's own time ``at`` by default)."""
    stamp = (at if generated is None else generated).isoformat()
    lines = [{**line, "generated_at": stamp} for line in lines]
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    os.utime(path, (at.timestamp(), at.timestamp()))


def _api() -> FakeD1:
    api = FakeD1(names=[("snowlight-accounts", "0000-synthetic"), ("other", "1111")])
    api.db.executescript(MIGRATION.read_text(encoding="utf-8"))
    return api


def _on() -> tuple[str, datetime | None]:
    return "on", None


def _shipper(
    api: FakeD1,
    env: dict[str, str] | None = None,
    publish: Callable[[], tuple[str, datetime | None]] = _on,
) -> SourcesShipper:
    return SourcesShipper(api, ENV if env is None else env, LINKS, publish, clock=lambda: AT)


def _ship(shipper: SourcesShipper, path: Path) -> sources.SourcesShipped:
    return shipper.ship(path, deadline=AT + timedelta(minutes=1))


def _decoded(api: FakeD1, day: date) -> tuple[dict[str, Any], dict[str, Any]]:
    head = api.db.execute(
        "SELECT sha256, parts, closings, published_at, mode, latest_at FROM lit_sources_head"
        " WHERE day = ?",
        (day.isoformat(),),
    ).fetchone()
    texts = [
        row[0]
        for row in api.db.execute(
            "SELECT data FROM lit_sources WHERE day = ? ORDER BY n", (day.isoformat(),)
        )
    ]
    data = gzip.decompress(b"".join(base64.b64decode(text) for text in texts))
    assert hashlib.sha256(data).hexdigest() == head[0]
    assert len(texts) == head[1]
    meta = {"closings": head[2], "published_at": head[3], "mode": head[4], "latest_at": head[5]}
    return json.loads(data), meta


def test_the_parts_decode_to_ids_types_links_and_times_only(tmp_path: Path) -> None:
    first, last = local_days(AT)
    path = tmp_path / "provenance.jsonl"
    lines = [_line("SYN0000001", first), _line("SYN0000002", first), _line("SYN0000003", last)]
    _write(path, lines)
    api = _api()
    found = _ship(_shipper(api), path)
    assert found.outcome == "shipped"
    assert (found.changed, found.closings) == ((last - first).days + 1, 3)
    body, meta = _decoded(api, first)
    assert meta == {
        "closings": 2,
        "published_at": AT.replace(microsecond=0).isoformat(),
        "mode": "on",
        "latest_at": None,
    }
    assert body["links"] == LINKS
    one = body["closings"][0]
    assert one == {
        "nces": "SYN0000001",
        "status": 1,
        "reason": 2,
        "level": "district",
        "source": "synthetic-station-a",
        "type": "broadcaster_list",
        "lo": "2026-11-17T10:00:00+00:00",
        "hi": "2026-11-17T17:55:00+00:00",
        "row_stamp": "2026-11-17T10:00:00+00:00",
        "present": True,
        "posted_by": "synthetic-list-b",
        "contributing": [
            ["synthetic-station-a", "broadcaster_list"],
            ["synthetic-list-b", "aggregator_list"],
        ],
    }
    # no row key, no announced_by key, no matcher internals reach the admin's copy
    text = json.dumps(body)
    for line in lines:
        assert line["row_key"] not in text
        assert line["announced_by"] not in text
    assert "f5_" not in text
    assert "match_" not in text


def test_an_unchanged_file_asks_nothing_and_the_same_content_touches_the_heads(
    tmp_path: Path,
) -> None:
    first, _ = local_days(AT)
    path = tmp_path / "provenance.jsonl"
    _write(path, [_line("SYN0000001", first)])
    api = _api()
    shipper = _shipper(api)
    _ship(shipper, path)
    sent = len(api.sent)
    assert _ship(shipper, path).outcome == "same"
    assert len(api.sent) == sent  # the file did not change: nothing asked
    later = AT + timedelta(minutes=5)
    _write(path, [_line("SYN0000001", first)], at=later)
    again = _ship(shipper, path)
    assert (again.outcome, again.changed, again.parts) == ("same", 0, 0)
    new = api.sent[sent:]
    assert sources._PART not in new
    assert sources._TOUCH in new
    _, meta = _decoded(api, first)
    assert meta["published_at"] == later.isoformat()


def test_days_before_yesterday_go_and_yesterday_stays_as_last_shipped(tmp_path: Path) -> None:
    first, _ = local_days(AT)
    path = tmp_path / "provenance.jsonl"
    api = _api()
    for back in (2, 1):
        old = AT - timedelta(days=back)
        _write(path, [_line(f"SYN000000{back}", local_days(old)[0])], at=old)
        _ship(_shipper(api), path)
    _write(path, [_line("SYN0000009", first)])
    _ship(_shipper(api), path)
    days = {row[0] for row in api.db.execute("SELECT day FROM lit_sources_head")}
    parts = {row[0] for row in api.db.execute("SELECT DISTINCT day FROM lit_sources")}
    yesterday = first - timedelta(days=1)
    assert min(days) == yesterday.isoformat()
    assert min(parts) == yesterday.isoformat()
    body, _ = _decoded(api, yesterday)
    assert [c["nces"] for c in body["closings"]] == ["SYN0000001"]


def test_a_day_with_nothing_lit_any_more_is_shipped_empty(tmp_path: Path) -> None:
    first, _ = local_days(AT)
    path = tmp_path / "provenance.jsonl"
    api = _api()
    _write(path, [_line("SYN0000001", first)])
    _ship(_shipper(api), path)
    _write(path, [], at=AT + timedelta(minutes=5))
    _ship(_shipper(api), path)
    body, meta = _decoded(api, first)
    assert body["closings"] == []
    assert meta["closings"] == 0


def test_the_day_cap_ships_nothing_and_a_day_too_big_keeps_its_last_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, _ = local_days(AT)
    path = tmp_path / "provenance.jsonl"
    _write(path, [_line("SYN0000001", first)])
    api = _api()
    api.db.execute(
        "INSERT INTO lit_sources_budget (day, rows) VALUES (?, ?)",
        (AT.date().isoformat(), sources.SOURCES_ROWS - 3),
    )
    found = _ship(_shipper(api), path)
    assert (found.outcome, found.rows) == ("capped", 0)
    assert api.db.execute("SELECT COUNT(*) FROM lit_sources_head").fetchone()[0] == 0
    api.db.execute("DELETE FROM lit_sources_budget")
    _ship(_shipper(api), path)
    spent = api.db.execute("SELECT rows FROM lit_sources_budget").fetchone()[0]
    assert 0 < spent < 30  # a small day writes a few rows (billed with the bill itself)
    monkeypatch.setattr(sources, "MAX_PARTS", 0)
    later = AT + timedelta(minutes=5)
    _write(path, [_line("SYN0000002", first)], at=later)
    big = _ship(_shipper(api), path)
    assert big.too_big >= 1
    body, meta = _decoded(api, first)
    assert [c["nces"] for c in body["closings"]] == ["SYN0000001"]
    # S1: the day says the map was published again (its last shipped version, its own time)
    assert (meta["published_at"], meta["latest_at"]) == (AT.isoformat(), later.isoformat())
    sent = len(api.sent)
    assert _ship(_shipper(api), path).too_big >= 1  # asked again: nothing more to write
    assert sources._PART not in api.sent[sent:]
    assert _decoded(api, first)[1]["latest_at"] == later.isoformat()


def test_only_a_live_read_ships_and_the_accounts_database_is_never_made(tmp_path: Path) -> None:
    path = tmp_path / "provenance.jsonl"
    _write(path, [_line("SYN0000001", local_days(AT)[0])])
    api = _api()
    with pytest.raises(SourcesError):
        _ship(_shipper(api, env={**ENV, "GITHUB_WORKFLOW": "predict"}), path)
    assert api.sent == []
    empty = FakeD1()
    with pytest.raises(SourcesError):
        _ship(_shipper(empty), path)
    assert empty.created == 0
    assert _ship(_shipper(api), tmp_path / "missing.jsonl").outcome == "none"
    _ship(_shipper(api), path)
    assert set(api.sent) <= STATEMENTS
    tables = {"lit_sources", "lit_sources_head", "lit_sources_budget"}
    for sql in STATEMENTS:
        named = set(re.findall(r"(?:FROM|INTO|^UPDATE)\s+(\w+)", sql))
        assert named, sql
        assert named <= tables, sql


def _runner(tmp_path: Path, shipper: Any, now: datetime) -> live_cli.Runner:
    runner = live_cli.Runner(
        args=argparse.Namespace(state=tmp_path, internal=tmp_path),
        config=None,  # type: ignore[arg-type]
        env={},
        parts=None,  # type: ignore[arg-type]
        loaders=SimpleNamespace(clock=lambda: now),  # type: ignore[arg-type]
    )
    runner.sources = shipper
    runner.state = live_cli._Loop(due=now + timedelta(minutes=4), next_check=now)
    runner.state.next_ship = now
    return runner


def test_in_the_loop_a_failure_is_one_line_and_the_line_holds_counts_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(tmp_path / "provenance.jsonl", [_line("SYN0000001", local_days(AT)[0])])
    api = _api()
    runner = _runner(tmp_path, _shipper(api), AT)
    runner.idle(AT)
    out = capsys.readouterr().out
    assert out.startswith("sources shipped: shipped, ")
    # counts and codes only: no id, link or time
    assert re.fullmatch(r"sources shipped: \w+(, \d+ [a-z ]+)+\n", out), out
    for word in ("synthetic", "SYN", "http", "2026"):
        assert word not in out

    class Broken:
        def ship(self, *_args: object, **_kwargs: object) -> sources.SourcesShipped:
            raise ValueError("synthetic failure")

    broken = _runner(tmp_path, Broken(), AT)
    broken.idle(AT)  # never raises
    out = capsys.readouterr().out
    assert out == "sources ship: failed: ValueError\n", out
    late = _runner(tmp_path, Broken(), AT)
    late.state.due = AT + live_cli.PUSH_MARGIN
    late.ship_sources(AT)
    assert "skipped" in capsys.readouterr().out


def test_a_large_day_goes_in_requests_of_8_with_its_head_after_every_part(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, _ = local_days(AT)
    path = tmp_path / "provenance.jsonl"
    _write(path, [_line(f"SYN{n:07d}", first) for n in range(40)])
    monkeypatch.setattr(sources, "CHUNK_BYTES", 48)
    api = _api()
    seen: list[list[tuple[str, Any]]] = []
    run = api.run

    def counted(database: str, statements: Any) -> Any:
        seen.append(list(statements))
        return run(database, statements)

    monkeypatch.setattr(api, "run", counted)
    found = _ship(_shipper(api), path)
    assert found.parts > 8
    assert all(len(batch) <= 8 for batch in seen)
    sent = [statement for batch in seen for statement in batch]
    key = first.isoformat()
    head = next(n for n, (sql, args) in enumerate(sent) if sql == sources._HEAD and args[0] == key)
    parts = [n for n, (sql, args) in enumerate(sent) if sql == sources._PART and args[0] == key]
    assert len(parts) > 8
    assert max(parts) < head
    body, meta = _decoded(api, first)
    assert len(body["closings"]) == meta["closings"] == 40


def _head(api: FakeD1, day: date) -> tuple[str, str, str | None]:
    found = api.db.execute(
        "SELECT published_at, mode, latest_at FROM lit_sources_head WHERE day = ?",
        (day.isoformat(),),
    ).fetchone()
    return found[0], found[1], found[2]


def test_a_shadow_publish_is_labelled_and_publishing_off_ships_nothing(tmp_path: Path) -> None:
    """B1: a shadow publish's statuses are not on the public map; the head says so."""
    first, _ = local_days(AT)
    path = tmp_path / "provenance.jsonl"
    _write(path, [_line("SYN0000001", first)])
    api = _api()
    off = _ship(_shipper(api, publish=lambda: ("off", AT)), path)
    assert off.outcome == "none"
    assert api.sent == []
    shipper = _shipper(api, publish=lambda: ("shadow", None))
    assert _ship(shipper, path).outcome == "shipped"
    assert _head(api, first)[1] == "shadow"
    # the same summary under another mode relabels the head (one row, no part)
    sent = len(api.sent)
    found = _ship(_shipper(api), path)
    assert (found.outcome, found.parts) == ("same", 0)
    assert sources._PART not in api.sent[sent:]
    assert _head(api, first)[1] == "on"


def test_a_later_publish_that_left_the_file_is_named_on_the_heads(tmp_path: Path) -> None:
    """S1: a blank publish (or an upload that failed after the closings file) does not
    rewrite provenance.jsonl; the heads then carry when the map was published again."""
    first, _ = local_days(AT)
    path = tmp_path / "provenance.jsonl"
    published = AT - timedelta(seconds=5)
    _write(path, [_line("SYN0000001", first)], generated=published)  # the file 18:00:05
    api = _api()
    memory: list[datetime | None] = [published]
    shipper = _shipper(api, publish=lambda: ("on", memory[0]))
    _ship(shipper, path)
    assert _head(api, first) == (published.isoformat(), "on", None)  # the publish's own stamp
    blank = AT + timedelta(minutes=10, microseconds=7)
    memory[0] = blank
    sent = len(api.sent)
    found = _ship(shipper, path)  # the file is unchanged, the memory is not: it is asked
    assert found.outcome == "later"
    assert sources._PART not in api.sent[sent:]
    later = blank.replace(microsecond=0).isoformat()
    assert _head(api, first) == (published.isoformat(), "on", later)
    sent = len(api.sent)
    assert _ship(shipper, path).outcome == "same"
    assert len(api.sent) == sent
    # the next good publish rewrites the file: no label
    again = AT + timedelta(minutes=15)
    _write(path, [_line("SYN0000002", first)], at=again, generated=again - timedelta(seconds=3))
    memory[0] = again - timedelta(seconds=3)
    _ship(shipper, path)
    assert _head(api, first) == ((again - timedelta(seconds=3)).isoformat(), "on", None)
    # lines whose generated_at is after the file's time are still the last publish's own
    ahead = again + timedelta(minutes=1)
    _write(path, [_line("SYN0000003", first)], at=ahead - timedelta(seconds=20), generated=ahead)
    memory[0] = ahead
    _ship(shipper, path)
    assert _head(api, first)[2] is None


def test_with_no_file_yet_the_stored_heads_name_the_later_publish(tmp_path: Path) -> None:
    """S1 at a run's start: its first publish was blank, so there is no provenance.jsonl; the
    heads the last run stored still say the map was published again since."""
    first, _ = local_days(AT)
    path = tmp_path / "provenance.jsonl"
    _write(path, [_line("SYN0000001", first)])
    api = _api()
    _ship(_shipper(api), path)
    old = (first - timedelta(days=3)).isoformat()
    api.db.execute(
        "INSERT INTO lit_sources_head VALUES (?, 'x', 0, 0, ?, ?, 'on', NULL)", (old, old, old)
    )
    blank = AT + timedelta(minutes=30)
    fresh = _shipper(api, publish=lambda: ("on", blank))
    found = _ship(fresh, tmp_path / "missing.jsonl")
    assert found.outcome == "none"
    assert found.rows > 0
    assert _head(api, first) == (AT.isoformat(), "on", blank.isoformat())
    assert api.db.execute(
        "SELECT latest_at FROM lit_sources_head WHERE day = ?", (old,)
    ).fetchone() == (None,)  # an old day is not this window's
    sent = len(api.sent)
    assert _ship(fresh, tmp_path / "missing.jsonl").outcome == "same"
    assert len(api.sent) == sent
    assert _ship(_shipper(api), tmp_path / "missing.jsonl").outcome == "none"  # no memory


class _Timed(FakeD1):
    """A FakeD1 with the real client's deadline (what the bill was given is kept)."""

    def __init__(self) -> None:
        super().__init__(names=[("snowlight-accounts", "0000-synthetic")])
        self.db.executescript(MIGRATION.read_text(encoding="utf-8"))
        self.deadline: float | None = None
        self.now = 100.0
        self.lost_rows = 0
        self.billed_with: list[float | None] = []
        self.lose: str | None = None

    def monotonic(self) -> float:
        return self.now

    def run(self, database: str, statements: Any) -> Any:
        if any(sql == sources._SPEND for sql, _ in statements):
            self.billed_with.append(self.deadline)
        if self.lose is not None and any(sql == self.lose for sql, _ in statements):
            self.lost_rows += 2 * len(statements)  # two tries, each may have run
            raise D1Error("query: HTTP 503")
        return super().run(database, statements)


def _budget(api: FakeD1) -> int:
    found = api.db.execute("SELECT rows FROM lit_sources_budget").fetchone()
    return 0 if found is None else int(found[0])


def test_a_shipment_that_runs_out_of_time_still_bills_what_it_wrote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S2: the bill goes after the deadline (with a short grace), so the cap stays a cap."""
    first, _ = local_days(AT)
    path = tmp_path / "provenance.jsonl"
    _write(path, [_line(f"SYN{n:07d}", first) for n in range(40)])
    monkeypatch.setattr(sources, "CHUNK_BYTES", 48)
    api = _Timed()
    ticks = [AT]

    def clock() -> datetime:
        ticks[0] += timedelta(seconds=1)
        return ticks[0]

    shipper = SourcesShipper(api, ENV, LINKS, _on, clock=clock)
    with pytest.raises(SourcesError, match="ran out of time"):
        shipper.ship(path, deadline=AT + timedelta(seconds=6))
    parts = api.db.execute("SELECT COUNT(*) FROM lit_sources").fetchone()[0]
    heads = api.db.execute("SELECT COUNT(*) FROM lit_sources_head").fetchone()[0]
    assert parts > 0
    assert _budget(api) == parts + heads + 2  # every row written, and the bill's own
    assert api.billed_with == [api.now + sources.BILL_GRACE]
    assert api.deadline is None  # the caller's deadline is back


def test_rows_whose_answer_was_lost_are_billed(tmp_path: Path) -> None:
    """S2: a write sent again after a 5xx may have run; it is billed as D1StateStore does."""
    first, _ = local_days(AT)
    path = tmp_path / "provenance.jsonl"
    _write(path, [_line("SYN0000001", first)])
    api = _Timed()
    api.lose = sources._PART
    shipper = SourcesShipper(api, ENV, LINKS, _on, clock=lambda: AT)
    with pytest.raises(D1Error):
        shipper.ship(path, deadline=AT + timedelta(minutes=1))
    assert _budget(api) == api.lost_rows + 2
    # a bill that fails is kept and sent with the next shipment
    api.lose = sources._SPEND
    api.db.execute("DELETE FROM lit_sources_budget")
    api.db.commit()
    with pytest.raises(D1Error):
        shipper.ship(path, deadline=AT + timedelta(minutes=1))
    assert _budget(api) == 0
    owed = shipper._unbilled
    assert owed > 0
    api.lose = None
    _write(path, [_line("SYN0000002", first)], at=AT + timedelta(minutes=5))
    found = shipper.ship(path, deadline=AT + timedelta(minutes=1))
    assert _budget(api) == owed + found.rows + 2


def test_the_links_come_from_registry_stations_and_the_loop_shipper_gets_them() -> None:
    """S4: real registry ``Station`` models (one with no page link), and the loop's wiring:
    the shipper reads the publisher's mode and memory at each shipment."""
    linked = station("gray-synthetic")
    bare = linked.model_copy(update={"id": "gray-bare", "page_url": None})
    # SYNTHETIC: a station with only a list file the reader GETs links that file; a POST-only
    # one does not.
    data = linked.model_copy(
        update={"id": "gray-data", "page_url": None, "data_url": "https://example.invalid/list"}
    )
    posted = data.model_copy(update={"id": "gray-post", "data_post": '{"q": 1}'})
    stations = {"gray-synthetic": linked, "gray-bare": bare, "gray-data": data, "gray-post": posted}
    assert sources.station_links(stations) == {
        "gray-synthetic": "https://example.invalid/closings",
        "gray-data": "https://example.invalid/list",
    }
    stations = {"gray-synthetic": linked, "gray-bare": bare}
    memory = Memory()
    publisher = SimpleNamespace(mode=Mode.SHADOW, memory=memory)
    ingest = SimpleNamespace(stations=stations, publisher=publisher)
    store = D1StateStore(FakeD1(), ENV, lambda: AT)
    made = live_cli.sources_shipper(store, ingest)  # type: ignore[arg-type]
    assert made.links == {"gray-synthetic": "https://example.invalid/closings"}
    assert made.api is store.api
    assert made.publish() == ("shadow", None)
    publisher.memory = Memory(last_published=AT)  # a reload: read at each shipment
    assert made.publish() == ("shadow", AT)


def test_a_hold_set_by_live_blank_in_another_process_is_named_on_the_heads(
    tmp_path: Path,
) -> None:
    """B1 (a): ``live blank`` blanks the map from another process and leaves the reader's
    last publish as it was; its first held pass records the hold's start, and the loop's
    shipper names that as a later publish. The next good publish clears it."""
    first, _ = local_days(AT)
    path = tmp_path / "provenance.jsonl"
    published = AT - timedelta(seconds=5)
    _write(path, [_line("SYN0000001", first)], generated=published)
    memory = Memory(last_published=published)
    ingest = SimpleNamespace(stations={}, publisher=SimpleNamespace(mode=Mode.ON, memory=memory))
    api = _api()
    store = D1StateStore(api, ENV, lambda: AT)
    shipper = live_cli.sources_shipper(store, ingest)  # type: ignore[arg-type]
    _ship(shipper, path)
    assert _head(api, first) == (published.isoformat(), "on", None)
    held = AT + timedelta(minutes=7)
    memory.hold_seen = held  # nothing else in the memory moves for the whole hold
    found = _ship(shipper, path)
    assert found.outcome == "later"
    assert _head(api, first) == (published.isoformat(), "on", held.isoformat())
    # an old hold (before the last publish) is not a later publish
    again = AT + timedelta(minutes=40)
    _write(path, [_line("SYN0000002", first)], at=again + timedelta(seconds=2), generated=again)
    memory.last_published = again
    _ship(shipper, path)
    assert _head(api, first) == (again.isoformat(), "on", None)


def test_a_blank_a_second_after_the_publish_is_named_although_the_file_is_newer(
    tmp_path: Path,
) -> None:
    """B1 (b): a hold set during the upload is blanked at the publish's stamp plus 1 s, while
    the file (written after the upload) is newer still: the lines' stamp decides."""
    first, _ = local_days(AT)
    stamp = AT.replace(second=0)
    path = tmp_path / "provenance.jsonl"
    _write(path, [_line("SYN0000001", first)], at=stamp + timedelta(seconds=2), generated=stamp)
    api = _api()
    blank = stamp + timedelta(seconds=1)
    found = _ship(_shipper(api, publish=lambda: ("on", blank)), path)
    assert found.outcome == "shipped"
    assert _head(api, first) == (stamp.isoformat(), "on", blank.isoformat())
    # a file with no line is judged by the file's time: a blank before it needs no note
    _write(path, [], at=stamp + timedelta(minutes=5, seconds=2), generated=stamp)
    _ship(_shipper(api, publish=lambda: ("on", stamp + timedelta(minutes=5, seconds=1))), path)
    assert _head(api, first)[2] is None


def test_an_empty_file_then_a_lit_upload_that_failed_after_the_closings_file_is_named(
    tmp_path: Path,
) -> None:
    """r3 B1: nothing lit (an empty file), then a pass lit statuses, uploaded the closings file
    and failed after it (``provenance.jsonl`` not rewritten): the page names the later publish."""
    first, _ = local_days(AT)
    path = tmp_path / "provenance.jsonl"
    g1 = AT - timedelta(seconds=5)
    _write(path, [], at=AT, generated=g1)
    api = _api()
    published = [g1]
    shipper = _shipper(api, publish=lambda: ("on", published[0]))
    _ship(shipper, path)
    assert _head(api, first)[2] is None
    published[0] = AT + timedelta(minutes=5)
    _ship(shipper, path)
    assert _head(api, first)[2] == published[0].isoformat()


class _Breaks(FakeD1):
    """A FakeD1 that fails after writing the parts request it is told to (a 5xx, a run's end)."""

    def __init__(self) -> None:
        super().__init__(names=[("snowlight-accounts", "0000-synthetic")])
        self.db.executescript(MIGRATION.read_text(encoding="utf-8"))
        self.after: int | None = None

    def run(self, database: str, statements: Any) -> Any:
        answers = super().run(database, statements)
        if self.after is not None and any(sql == sources._PART for sql, _ in statements):
            self.after -= 1
            if self.after < 0:
                self.after = None
                raise D1Error("query: HTTP 503")
        return answers


def test_a_day_whose_shipment_failed_partway_is_written_whole_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S2: some parts of a day were overwritten before its head; the next publish whose
    content is the old head's again rewrites the parts instead of touching the head."""
    monkeypatch.setattr(sources, "CHUNK_BYTES", 48)
    first, _ = local_days(AT)
    path = tmp_path / "provenance.jsonl"
    old = [_line(f"SYN{n:07d}", first) for n in range(30)]
    _write(path, old)
    api = _Breaks()
    shipper = _shipper(api)
    _ship(shipper, path)
    _decoded(api, first)  # whole
    _write(path, [_line(f"SYN{n:07d}", first) for n in range(1, 31)], at=AT + timedelta(minutes=5))
    api.after = 0  # the first parts request of the new day is written, then a 503
    with pytest.raises(D1Error):
        _ship(shipper, path)
    with pytest.raises((AssertionError, OSError, EOFError)):
        _decoded(api, first)  # half written: its parts fail the head's sha256
    _write(path, old, at=AT + timedelta(minutes=10))  # the old head's content again
    found = _ship(shipper, path)
    assert found.changed >= 1
    body, _ = _decoded(api, first)
    assert len(body["closings"]) == 30


def test_the_loop_gives_the_shipment_its_own_cap_of_the_idle_time(tmp_path: Path) -> None:
    """S3: the evidence and timer checks after it keep their time on a slow-API day."""
    given: list[datetime] = []

    class Recorded:
        def ship(self, _path: Path, *, deadline: datetime) -> sources.SourcesShipped:
            given.append(deadline)
            return sources.SourcesShipped("same")

    runner = _runner(tmp_path, Recorded(), AT)
    runner.ship_sources(AT)
    assert given == [AT + live_cli.SOURCES_SHIP_FOR]
    near = _runner(tmp_path, Recorded(), AT)
    near.state.due = AT + live_cli.PUSH_MARGIN + live_cli.MIN_PUSH_TIME
    near.ship_sources(AT)
    assert given[-1] == AT + live_cli.MIN_PUSH_TIME  # the push margin still bounds it
