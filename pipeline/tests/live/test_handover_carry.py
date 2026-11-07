"""A reader handover never changes what the live file shows (SYNTHETIC world): the successor
serves, for every source it has not read itself, what the run before held, under the same G13
bound from that read's own time, until its own read replaces it (:mod:`snowlight.live.carry`).

Nov 5 (runs 42033507651 then 42084876453): the lit count fell 3 to 1 for 20 minutes at the
handover. A calm source's last read in the run before had failed, so the successor did not
read it early, and a new process held nothing of a source it had not read itself. Here the
same shape: a calm source A whose last read failed, a 5-minute source B, and a successor whose
first passes do not read A; each pass's shown set is compared with one process that never
stopped and saw the same reads.
"""

import io
import json
import logging
import tarfile
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from live.test_edition import OWN, Source
from live.world import ALPHA_SCHOOL, World, at, lit, row, station
from snowlight.live.carry import (
    CARRY,
    Carried,
    carry_key,
    finalize_carry,
    read_carry,
    write_carry,
)
from snowlight.live.edition import EditionWatch
from snowlight.live.guards import Rules
from snowlight.live.ingest import Ingest, SourceRead, withhold_states
from snowlight.live.ledger import Ledger, Outcome
from snowlight.live.merge import merge
from snowlight.live.publish import Exit, LivePublisher
from snowlight.live.publishers import DirPublisher, Publisher
from snowlight.live.state import check_export, export, pack
from snowlight.schemas.directory import DirectoryEdition
from snowlight.schemas.live import ClosingsFile
from snowlight.sources.stations.registry import Station

A, B = "gray-synthetic", "gray-other"
"""A: a calm (30-minute) source; B: a 5-minute one (in a window)."""
EDITION = DirectoryEdition.model_validate(
    {**OWN.model_dump(mode="json"), "schools": 11, "districts": 6}
)
EASTERN_SCHOOL = "SYNTHETIC Eastern School"
A_ROWS = (row(ALPHA_SCHOOL, "Closed due to snow"),)
B_ROWS = (row(EASTERN_SCHOOL, "Closed due to snow"),)
RULES = Rules(breaker_floor=15000)
T0 = at("2026-11-17 11:05")


def _boosted(station: Station, _now: datetime) -> bool:
    return station.id == B


def _world() -> World:
    world = World()
    world.stations[B] = station(B)
    for source in (A, B):
        world.read(T0 - timedelta(days=1), [], source=source)
        world.read(T0 - timedelta(minutes=5), [], source=source)
    return world


def _ingest(world: World, folder: Path, host: Path | None = None) -> Ingest:
    """A reader whose state is ``folder``; ``host`` (by default ``host`` beside it, which every
    run of one test shares, as the live host is shared) is where it publishes."""
    publisher = LivePublisher(
        host=DirPublisher(folder.parent / "host" if host is None else host),
        directory=world.dir,
        state_dir=folder / "state",
        internal_dir=folder / "internal",
    )
    return Ingest(
        ledger=world.ledger,
        resolver=world.resolver(),
        stations=world.stations,
        publisher=publisher,
        watch=EditionWatch(own=EDITION, source=Source([EDITION])),
        internal_dir=folder / "internal",
        due=frozenset({B}),
        boosted=_boosted,
        rules=RULES,
    )


def _published(host: Path) -> set[tuple[int, str]]:
    data = (host / "v1-shadow" / "live" / "closings.json").read_bytes()
    return {(c.school, c.status.name) for c in ClosingsFile.from_json_bytes(data).closings()}


def shown(ingest: Ingest, now: datetime) -> dict[tuple[int, str], str]:
    """What a pass at ``now`` would publish from this process's state (before the gate)."""
    merged = merge(
        ingest.resolve(),
        held=ingest.held(now),
        directory=ingest.resolver.directory,
        generated_at=now,
        rules=ingest.rules,
    )
    merged, _ = withhold_states(merged, ingest.unknown_states(now), ingest.resolver.directory)
    return lit(merged)


type Schedule = Sequence[tuple[datetime, Sequence[SourceRead]]]


def _end(path: Path) -> None:
    """The run before ended: ``live finish --record`` marks its last record final."""
    assert finalize_carry(path).startswith("carry final: ")


def _ok(source: str, when: datetime, rows: tuple[object, ...] = ()) -> SourceRead:
    found = rows or (A_ROWS if source == A else B_ROWS)
    return SourceRead(source, Outcome.OK, when, tuple(found))  # type: ignore[arg-type]


def _schedule(after: Sequence[tuple[datetime, Sequence[SourceRead]]] = ()) -> Schedule:
    """The run before: A read at T0 (calm), failing at T0+30; B read every 5 minutes. Then
    ``after``, the successor's passes."""
    before: list[tuple[datetime, Sequence[SourceRead]]] = []
    for step in range(8):  # T0 .. T0+35
        now = T0 + timedelta(minutes=5 * step)
        reads = [_ok(B, now)]
        if step == 0:
            reads.append(_ok(A, now))
        if step == 6:
            reads.append(SourceRead(A, Outcome.ERROR, now))
        before.append((now, reads))
    return [*before, *after]


def _replay(
    tmp_path: Path, schedule: Schedule, handover: int, *, carry: bool = True
) -> list[tuple[dict[tuple[int, str], str], dict[tuple[int, str], str], set[tuple[int, str]]]]:
    """Run ``schedule`` twice: in one process that never stops (the reference), and in a run
    that hands over before pass ``handover`` (the successor takes the carry record when
    ``carry``). Each pass: (reference shown, handed-over shown, handed-over published)."""
    ref_world, world = _world(), _world()
    reference = _ingest(ref_world, tmp_path / "ref", tmp_path / "ref-host")
    run = _ingest(world, tmp_path / "pred")
    path = tmp_path / "state" / CARRY
    run.start_carry(path, schedule[0][0])
    found = []
    for index, (now, reads) in enumerate(schedule):
        if index == handover:
            _end(path)
            run = _ingest(world, tmp_path / "succ")
            if carry:
                run.start_carry(path, now)
        reference.run_pass(list(reads), now)
        report = run.run_pass(list(reads), now)
        assert report.exit is Exit.OK
        found.append((shown(reference, now), shown(run, now), _published(tmp_path / "host")))
    return found


SUCCESSOR = [
    # the successor's first passes: A failed last, so it is not read early (its cadence: due
    # at T0+60); B read every pass
    (T0 + timedelta(minutes=40), [_ok(B, T0 + timedelta(minutes=40))]),
    (T0 + timedelta(minutes=45), [_ok(B, T0 + timedelta(minutes=45))]),
    (T0 + timedelta(minutes=50), [_ok(B, T0 + timedelta(minutes=50))]),
    (T0 + timedelta(minutes=55), [_ok(B, T0 + timedelta(minutes=55))]),
    (
        T0 + timedelta(minutes=60),
        [_ok(B, T0 + timedelta(minutes=60)), _ok(A, T0 + timedelta(minutes=60))],
    ),
]


def test_a_handover_keeps_every_lit_status_until_the_successors_own_read(
    tmp_path: Path,
) -> None:
    passes = _replay(tmp_path, _schedule(SUCCESSOR), handover=8)
    both = {(0, "2026-11-17"): "CLOSED", (10, "2026-11-17"): "CLOSED"}
    for reference, handed, published in passes:
        assert handed == reference == both
        assert published == {(0, "CLOSED"), (10, "CLOSED")}


def test_without_the_record_the_successor_drops_the_source_it_has_not_read(
    tmp_path: Path,
) -> None:
    # the Nov 5 drop, reproduced: A dark from the handover until its own read at T0+60
    passes = _replay(tmp_path, _schedule(SUCCESSOR), handover=8, carry=False)
    for reference, handed, _ in passes[8:12]:
        assert reference == {(0, "2026-11-17"): "CLOSED", (10, "2026-11-17"): "CLOSED"}
        assert handed == {(10, "2026-11-17"): "CLOSED"}
    assert passes[12][1] == passes[12][0]


def test_a_source_late_in_the_successors_first_pass_stays_shown(tmp_path: Path) -> None:
    # the pass budget ran out before B: a late read is no read, B's last good read holds
    after = [
        (T0 + timedelta(minutes=40), [SourceRead(B, Outcome.LATE, T0 + timedelta(minutes=40))]),
    ]
    ref_world, world = _world(), _world()
    reference, run = (
        _ingest(ref_world, tmp_path / "r", tmp_path / "r-host"),
        _ingest(world, tmp_path / "p"),
    )
    path = tmp_path / CARRY
    run.start_carry(path, T0)
    for now, reads in _schedule():
        reference.run_pass(list(reads), now)
        run.run_pass(list(reads), now)
    _end(path)
    successor = _ingest(world, tmp_path / "s")
    ((now, reads),) = after
    successor.start_carry(path, now)
    reference.run_pass(list(reads), now)
    successor.run_pass(list(reads), now)
    assert shown(successor, now) == shown(reference, now)
    assert set(shown(successor, now)) == {(0, "2026-11-17"), (10, "2026-11-17")}


@pytest.mark.parametrize(
    ("source", "bound"),
    [(A, timedelta(minutes=90)), (B, timedelta(minutes=45))],
)
def test_a_carried_status_goes_dark_at_the_same_instant_as_in_the_run_before(
    tmp_path: Path, source: str, bound: timedelta
) -> None:
    # the run before read each source once at T0 and then nothing more (every read failing)
    ref_world, world = _world(), _world()
    reference, run = (
        _ingest(ref_world, tmp_path / "r", tmp_path / "r-host"),
        _ingest(world, tmp_path / "p"),
    )
    path = tmp_path / CARRY
    run.start_carry(path, T0)
    reads = [_ok(A, T0), _ok(B, T0)]
    reference.run_pass(reads, T0)
    run.run_pass(list(reads), T0)
    failing = T0 + timedelta(minutes=5)
    errors = [SourceRead(A, Outcome.ERROR, failing), SourceRead(B, Outcome.ERROR, failing)]
    reference.run_pass(errors, failing)
    run.run_pass(list(errors), failing)
    _end(path)
    successor = _ingest(world, tmp_path / "s")
    successor.start_carry(path, T0 + timedelta(minutes=10))
    last = T0 + bound
    for moment in (T0 + timedelta(minutes=10), last, last + timedelta(seconds=1)):
        assert successor.held(moment)[source] is reference.held(moment)[source]
    assert successor.held(last)[source] is True
    assert successor.held(last + timedelta(seconds=1))[source] is False


def test_the_successors_empty_read_replaces_the_carried_rows(tmp_path: Path) -> None:
    # A read empty by the successor: from then on A is the successor's own read, as in a run
    # that never stopped (a vanished row keeps its status through its day while its source is
    # held, unless vanish_retracts: the merge's rule, unchanged)
    after = [
        (
            T0 + timedelta(minutes=40),
            [
                _ok(B, T0 + timedelta(minutes=40)),
                SourceRead(A, Outcome.EMPTY, T0 + timedelta(minutes=40)),
            ],
        ),
        (T0 + timedelta(minutes=45), [_ok(B, T0 + timedelta(minutes=45))]),
    ]
    passes = _replay(tmp_path, _schedule(after), handover=8)
    for reference, handed, _ in passes:
        assert handed == reference


def test_the_successors_retraction_darkens_at_once(tmp_path: Path) -> None:
    rescinded = (row(ALPHA_SCHOOL, "Closing rescinded"),)
    after = [
        (
            T0 + timedelta(minutes=40),
            [_ok(B, T0 + timedelta(minutes=40)), _ok(A, T0 + timedelta(minutes=40), rescinded)],
        ),
    ]
    passes = _replay(tmp_path, _schedule(after), handover=8)
    reference, handed, published = passes[-1]
    assert handed == reference == {(10, "2026-11-17"): "CLOSED"}
    assert published == {(10, "CLOSED")}


def _handed_over(tmp_path: Path) -> tuple[World, Path]:
    """A run before that held A and B at T0+35 and wrote its record."""
    world = _world()
    run = _ingest(world, tmp_path / "p")
    path = tmp_path / CARRY
    run.start_carry(path, T0)
    for now, reads in _schedule():
        run.run_pass(list(reads), now)
    assert set(json.loads(path.read_text())["sources"]) == {A, B}
    assert finalize_carry(path) == "carry final: 2 sources"
    return world, path


@pytest.mark.parametrize(
    ("damage", "code"),
    [
        (lambda _doc: None, "missing"),
        (lambda _doc: "{not json", "unreadable"),
        (lambda doc: {**doc, "version": 99}, "version"),
        (lambda doc: {**doc, "key": "0" * 16}, "key"),
        (lambda doc: {key: value for key, value in doc.items() if key != "final"}, "not final"),
        (lambda doc: {**doc, "final": "yes"}, "not final"),
        (lambda doc: {**doc, "at": "2026-11-17T13:00:00+00:00"}, "future"),
        (lambda doc: {**doc, "at": "2026-11-17T09:00:00+00:00"}, "old"),
        (lambda doc: {**doc, "sources": []}, "unreadable"),
    ],
)
def test_a_bad_record_carries_nothing_with_one_line_and_no_raise(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    damage: Callable[[dict[str, object]], object],
    code: str,
) -> None:
    world, path = _handed_over(tmp_path)
    doc = json.loads(path.read_text())
    changed = damage(doc)
    if changed is None:
        path.unlink()
    else:
        path.write_text(changed if isinstance(changed, str) else json.dumps(changed))
    successor = _ingest(world, tmp_path / "s")
    now = T0 + timedelta(minutes=40)
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="snowlight.live.carry"):
        successor.start_carry(path, now)
    carry = [r.getMessage() for r in caplog.records if r.name == "snowlight.live.carry"]
    assert carry == [f"carry: none ({code})"]
    assert successor.carried == {}
    assert successor.held(now) == {A: False, B: False}
    successor.run_pass([_ok(B, now)], now)  # today's behaviour: only what it read
    assert shown(successor, now) == {(10, "2026-11-17"): "CLOSED"}


def test_a_record_entry_the_ledger_moved_past_carries_nothing(tmp_path: Path) -> None:
    # a good read of A after the record was written (a run that did not record it): the
    # successor cannot know what that read showed, so A is dark until its own read
    world, path = _handed_over(tmp_path)
    world.read(T0 + timedelta(minutes=37), list(A_ROWS), source=A)
    successor = _ingest(world, tmp_path / "s")
    now = T0 + timedelta(minutes=40)
    successor.start_carry(path, now)
    assert successor.held(now) == {A: False, B: True}


def test_another_resolver_version_reuses_no_derivation(tmp_path: Path) -> None:
    world, path = _handed_over(tmp_path)
    world.version = "another-f5|synthetic-f6|s8c"
    successor = _ingest(world, tmp_path / "s")
    now = T0 + timedelta(minutes=40)
    successor.start_carry(path, now)
    assert successor.carried == {}
    # and were it carried, a row derived under another version only darkens
    good = world.ledger.source(A).last_good_at  # type: ignore[union-attr]
    assert good is not None
    successor.carried = {A: Carried(good, good + timedelta(minutes=90))}
    assert shown(successor, now) == {}


def test_the_record_holds_ids_and_times_only(tmp_path: Path) -> None:
    world, path = _handed_over(tmp_path)
    doc = json.loads(path.read_text())
    assert set(doc) == {"version", "key", "at", "sources", "final"}
    assert doc["final"] is True
    assert doc["at"] == "2026-11-17T11:40:00+00:00"
    # each held source's last good read and the end of the hold the pass applied: A quiet
    # (90 minutes), B in a window (45)
    assert doc["sources"] == {
        A: {"good": "2026-11-17T11:05:00+00:00", "until": "2026-11-17T12:35:00+00:00"},
        B: {"good": "2026-11-17T11:40:00+00:00", "until": "2026-11-17T12:25:00+00:00"},
    }
    assert world.ledger.source(A) is not None


def test_a_failed_write_is_logged_and_the_pass_goes_on(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    folder = tmp_path / "file"
    folder.write_text("x")
    assert write_carry(folder / CARRY, key="k", now=T0, held={A: Carried(T0, T0)}) == 0
    world = _world()
    run = _ingest(world, tmp_path / "p")
    run.carry_path, run.carry_key = folder / CARRY, "k"
    with caplog.at_level(logging.ERROR):
        report = run.run_pass([_ok(B, T0)], T0)
    assert report.exit is Exit.OK
    assert any(r.getMessage().startswith("carry write: ") for r in caplog.records)


def test_read_carry_never_raises(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    folder = tmp_path / "dir.json"
    folder.mkdir()
    key = carry_key("v", RULES)

    def served() -> datetime:
        return T0

    def broken() -> datetime:
        raise OSError

    with caplog.at_level(logging.INFO):
        assert read_carry(folder, key=key, now=T0, rules=RULES, published=served) == {}
        path = tmp_path / CARRY
        write_carry(path, key=key, now=T0, held={A: Carried(T0, T0)})
        _end(path)
        assert read_carry(path, key=key, now=T0, rules=RULES, published=broken) == {}
    carry = [r.getMessage() for r in caplog.records if r.name == "snowlight.live.carry"]
    assert carry == ["carry: none (unreadable)", "carry: none (host OSError)"]
    # a read within the pass's last second is kept (the record keeps the pass's whole time,
    # the file its whole second)
    moment = T0.replace(microsecond=500_000)
    hold = Carried(moment, moment + timedelta(minutes=45))
    write_carry(tmp_path / "s.json", key=key, now=moment, held={A: hold})
    _end(tmp_path / "s.json")
    assert read_carry(tmp_path / "s.json", key=key, now=moment, rules=RULES, published=served) == {
        A: hold
    }
    # an entry later than the record's own time, or whose hold ends before its read or runs
    # past the longest bound, is dropped
    write_carry(
        path,
        key=key,
        now=T0,
        held={
            A: Carried(T0, T0),
            B: Carried(T0 + timedelta(minutes=1), T0 + timedelta(minutes=2)),
            "c": Carried(T0, T0 - timedelta(seconds=1)),
            "d": Carried(T0, T0 + timedelta(minutes=91)),
        },
    )
    _end(path)
    assert read_carry(path, key=key, now=T0, rules=RULES, published=served) == {A: Carried(T0, T0)}


def test_the_record_is_packed_and_pushed_but_never_exported(tmp_path: Path) -> None:
    _, path = _handed_over(tmp_path)
    folder = path.parent
    (folder / "ledger.sqlite").unlink(missing_ok=True)
    Ledger(folder / "ledger.sqlite").close()
    with tarfile.open(fileobj=io.BytesIO(pack(folder)), mode="r:gz") as tar:
        assert CARRY in tar.getnames()
    assert CARRY not in check_export(export(folder))


def _snapshot(tmp_path: Path) -> tuple[World, Path, World, Ingest]:
    """The state pushed at T0+5 while the run before went on (a loop push: its record is not
    final), and that run itself: A read at T0, A's read failing at T0+5 (the Nov 5 shape)."""
    snap_world, full_world = _world(), _world()
    snap = _ingest(snap_world, tmp_path / "snap", tmp_path / "snap-host")
    full = _ingest(full_world, tmp_path / "full")
    path = tmp_path / "snap" / CARRY
    snap.start_carry(path, T0)
    full.start_carry(tmp_path / "full" / CARRY, T0)
    five = T0 + timedelta(minutes=5)
    for now, reads in (
        (T0, [_ok(A, T0), _ok(B, T0)]),
        (five, [_ok(B, five), SourceRead(A, Outcome.ERROR, five)]),
    ):
        assert snap.run_pass(list(reads), now).exit is Exit.OK
        assert full.run_pass(list(reads), now).exit is Exit.OK
    return snap_world, path, full_world, full


def _carry_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "snowlight.live.carry"]


RESCINDED = (row(ALPHA_SCHOOL, "Closing rescinded"),)


def test_a_snapshot_taken_while_the_run_went_on_carries_nothing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The run before reads A's retraction at T0+10, but its uploads at T0+10 and T0+15 fail
    # (host writes failing; a refusal for health, an owner hold or a rate limit leave the host
    # the same), and it ends with no end push. The host still serves the T0+5 pass's file, so
    # the snapshot's record is not behind it: only the missing final mark tells them apart.
    snap_world, path, _, full = _snapshot(tmp_path)

    def failing(_self: Publisher, _files: object) -> None:
        raise OSError

    ten, fifteen = T0 + timedelta(minutes=10), T0 + timedelta(minutes=15)
    with monkeypatch.context() as patch:
        patch.setattr(DirPublisher, "write", failing)
        for now, reads in (
            (ten, [_ok(B, ten), _ok(A, ten, RESCINDED)]),
            (fifteen, [_ok(B, fifteen)]),
        ):
            full.run_pass(list(reads), now)
            assert shown(full, now) == {(10, "2026-11-17"): "CLOSED"}
    assert _published(tmp_path / "host") == {(0, "CLOSED"), (10, "CLOSED")}
    successor = _ingest(snap_world, tmp_path / "succ")
    start = T0 + timedelta(minutes=20)
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="snowlight.live.carry"):
        successor.start_carry(path, start)
    assert _carry_lines(caplog) == ["carry: none (not final)"]
    assert successor.carried == {}
    # the mark is what stops it: the same snapshot marked final passes every other check
    copy = tmp_path / "marked.json"
    copy.write_bytes(path.read_bytes())
    _end(copy)
    marked = _ingest(snap_world, tmp_path / "marked")
    marked.start_carry(copy, start)
    assert A in marked.carried
    # today's behaviour: the successor publishes only what it read (A not read early)
    for step in range(3):
        now = start + timedelta(minutes=5 * step)
        assert successor.run_pass([_ok(B, now)], now).exit is Exit.OK
        assert _published(tmp_path / "host") == {(10, "CLOSED")}


def test_the_end_of_a_run_whose_uploads_failed_carries_its_retraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the same run, ended by live finish --record and its end push: the record and the
    # ledger are its last pass's, so A is carried with its retraction and stays dark
    _, _, full_world, full = _snapshot(tmp_path)

    def failing(_self: Publisher, _files: object) -> None:
        raise OSError

    ten = T0 + timedelta(minutes=10)
    with monkeypatch.context() as patch:
        patch.setattr(DirPublisher, "write", failing)
        full.run_pass([_ok(B, ten), _ok(A, ten, RESCINDED)], ten)
    _end(tmp_path / "full" / CARRY)
    successor = _ingest(full_world, tmp_path / "succ")
    now = T0 + timedelta(minutes=20)
    successor.start_carry(tmp_path / "full" / CARRY, now)
    assert set(successor.carried) == {A, B}
    assert successor.run_pass([_ok(B, now)], now).exit is Exit.OK
    assert _published(tmp_path / "host") == {(10, "CLOSED")}


def test_a_failed_write_removes_the_earlier_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a pass whose write fails leaves no earlier pass's record for the end to mark final
    _, path = _handed_over(tmp_path)

    def full(_path: Path, _data: bytes) -> None:
        raise OSError

    with monkeypatch.context() as patch:
        patch.setattr("snowlight.live.carry.write_bytes_atomic", full)
        assert write_carry(path, key="k", now=T0, held={A: Carried(T0, T0)}) == 0
        assert finalize_carry(path) == "carry final: none (missing)"
        assert not path.exists()
        path.write_text('{"sources": {}}')
        assert finalize_carry(path) == "carry final: none (OSError)"
    path.write_text("[]")
    assert finalize_carry(path) == "carry final: none (unreadable)"
    path.write_text("{not json")
    assert finalize_carry(path) == "carry final: none (unreadable)"


def test_a_final_record_older_than_the_served_file_carries_nothing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # The run before ended at T0+5 with its record marked; another writer's file since (an
    # overrides-only run, a blank: here a run that read A's retraction) stops the carry.
    snap_world, path, _, full = _snapshot(tmp_path)
    _end(path)
    ten, fifteen = T0 + timedelta(minutes=10), T0 + timedelta(minutes=15)
    full.run_pass([_ok(B, ten), _ok(A, ten, RESCINDED)], ten)
    full.run_pass([_ok(B, fifteen)], fifteen)
    assert _published(tmp_path / "host") == {(10, "CLOSED")}
    successor = _ingest(snap_world, tmp_path / "succ")
    now = T0 + timedelta(minutes=40)
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="snowlight.live.carry"):
        successor.start_carry(path, now)
    assert _carry_lines(caplog) == ["carry: none (behind)"]
    assert successor.carried == {}
    # A's early read fails: today's behaviour, A is dark until a good read of it
    report = successor.run_pass([_ok(B, now), SourceRead(A, Outcome.ERROR, now)], now)
    assert report.exit is Exit.OK
    assert _published(tmp_path / "host") == {(10, "CLOSED")}


def test_a_record_of_the_served_pass_still_carries(tmp_path: Path) -> None:
    # the record of the pass whose file the host serves (the same second) is used
    world, path = _handed_over(tmp_path)
    successor = _ingest(world, tmp_path / "s")
    served = successor.publisher.read_back()
    assert served is not None
    assert served.generated_at == T0 + timedelta(minutes=35)
    successor.start_carry(path, T0 + timedelta(minutes=40))
    assert set(successor.carried) == {A, B}


def test_a_host_that_cannot_be_read_or_holds_no_file_carries_nothing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, path = _handed_over(tmp_path)
    now = T0 + timedelta(minutes=40)
    failing = _ingest(world, tmp_path / "s")
    empty = _ingest(world, tmp_path / "e", tmp_path / "empty-host")

    def refused(_self: LivePublisher) -> None:
        raise TimeoutError

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="snowlight.live.carry"):
        with monkeypatch.context() as patch:
            patch.setattr(LivePublisher, "read_back", refused)
            failing.start_carry(path, now)
        empty.start_carry(path, now)
    carry = [r.getMessage() for r in caplog.records if r.name == "snowlight.live.carry"]
    assert carry == ["carry: none (host TimeoutError)", "carry: none (unpublished)"]
    for successor in (failing, empty):
        assert successor.carried == {}
        assert successor.held(now) == {A: False, B: False}


def test_a_carried_hold_never_outlasts_the_one_the_run_before_applied(tmp_path: Path) -> None:
    # The run before held B in a window (45 minutes); the successor's first alerts read
    # failed, so it counts B quiet (90). B stays dark from the same instant as in the run
    # before, and the successor's own record keeps that end for the run after it.
    ref_world, world = _world(), _world()
    reference = _ingest(ref_world, tmp_path / "r", tmp_path / "r-host")
    run = _ingest(world, tmp_path / "p")
    path = tmp_path / CARRY
    run.start_carry(path, T0)
    reads = [_ok(A, T0), _ok(B, T0)]
    reference.run_pass(list(reads), T0)
    run.run_pass(list(reads), T0)
    _end(path)
    successor = _ingest(world, tmp_path / "s")
    successor.boosted = lambda _station, _now: False
    start = T0 + timedelta(minutes=10)
    successor.start_carry(path, start)
    assert successor.carried[B] == Carried(T0, T0 + timedelta(minutes=45))
    last = T0 + timedelta(minutes=45)
    for moment in (start, last, last + timedelta(seconds=1), T0 + timedelta(minutes=90)):
        assert successor.held(moment)[B] is reference.held(moment)[B]
    assert successor.held(last)[B] is True
    assert successor.held(last + timedelta(seconds=1))[B] is False
    # A was quiet in both: its 90 minutes stand
    assert successor.held(T0 + timedelta(minutes=90))[A] is True
    successor.run_pass([SourceRead(A, Outcome.ERROR, start)], start)
    entries = json.loads(path.read_text())["sources"]
    assert entries[B] == {"good": "2026-11-17T11:05:00+00:00", "until": "2026-11-17T11:50:00+00:00"}
