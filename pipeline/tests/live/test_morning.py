"""The morning record the automatic learning reads (SYNTHETIC world): shown passes only give
reads, every pass gives what its rows name and the states it withheld, a withheld row still
names its district, and a damaged file is never trusted."""

import json
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from live.test_ingest import CLOSED, RESCINDED, A, B, _ingest, _warm, _world
from live.world import at
from snowlight.live.guards import Withheld
from snowlight.live.ingest import SourceRead, shown
from snowlight.live.ledger import Outcome as ReadOutcome
from snowlight.live.morning import (
    ANY_KIND,
    EVERY_DAY,
    MorningDay,
    MorningLog,
    naming,
    slot_of,
    source_read,
)
from snowlight.live.publish import Exit, PassReport
from snowlight.live.resolve import DayClaim, Derived

DAY = date(2026, 11, 17)


def claim(day: date, kind: str = "closed") -> DayClaim:
    return DayClaim(day, kind, None, None, None, ufn=False)


def test_what_a_row_names() -> None:
    lit = Derived(withheld=None, claims=(claim(DAY),), reach=("2900001",))
    assert naming(lit) == {DAY.isoformat(): {"closed"}}
    # A lit delay names the day with the kind it lights (B1: what the map shows of it).
    delay = Derived(withheld=None, claims=(claim(DAY, "delayed"),), reach=("2900001",))
    assert naming(delay) == {DAY.isoformat(): {"delayed"}}
    # Withheld (weak, a conflict upstream, undated): it names its districts for every day,
    # with the status kinds its words name, or any kind when they are unsure or unread.
    weak = Derived(withheld=Withheld.WEAK, reach=("2900001",), kinds=("closed",))
    assert naming(weak) == {EVERY_DAY: {"closed"}}
    weak_delay = Derived(withheld=Withheld.WEAK, reach=("2900001",), kinds=("delayed", "open"))
    assert naming(weak_delay) == {EVERY_DAY: {"delayed"}}
    for kinds in ((), ("delayed", "unsure"), ("unsure",)):
        unsure = Derived(withheld=Withheld.NOT_STATUS, reach=("2900001",), kinds=kinds)
        assert naming(unsure) == {EVERY_DAY: {ANY_KIND}}
    # A dissent of named days names those days; of every day, every day; with any kind.
    days = Derived(withheld=Withheld.RETRACTED, dissent=(DAY,), reach=("2900001",))
    assert naming(days) == {DAY.isoformat(): {ANY_KIND}}
    every = Derived(withheld=Withheld.RETRACTED, dissent=(), reach=("2900001",))
    assert naming(every) == {EVERY_DAY: {ANY_KIND}}
    # A row that only says school is open names nothing; nor does one never placed.
    opens = Derived(withheld=None, opens=(DAY,), reach=("2900001",))
    assert naming(opens) == {}
    open_kept = Derived(withheld=Withheld.OPEN_UNDATED, reach=("2900001",), kinds=("open",))
    assert naming(open_kept) == {}
    assert naming(Derived(withheld=Withheld.UNMATCHED)) == {}


def result(derived: Derived, *, present: bool = True, superseded: bool = False) -> Any:
    return SimpleNamespace(derived=derived, present=present, superseded=superseded)


def test_a_read_counts_its_rows_placed_and_unread() -> None:
    source: Any = SimpleNamespace(
        source_id=A,
        rows=(
            result(Derived(withheld=None, reach=("2900001",))),
            result(Derived(withheld=Withheld.UNMATCHED)),
            result(Derived(withheld=Withheld.NOT_STATUS, reach=("2900002",))),
            result(Derived(withheld=None), present=False),
            result(Derived(withheld=None), superseded=True),
        ),
    )
    assert source_read(source) == (3, 2, 1)


def test_only_a_shown_pass_inside_the_band_gives_reads(tmp_path: Path) -> None:
    log = MorningLog(tmp_path / "morning")
    morning = at("2026-11-17 13:10")
    named = {"2900001": {DAY.isoformat(): {"delayed"}}}
    log.record(morning, shown="v1", reads={A: (4, 4, 0)}, unknown=(), named=named)
    log.record(
        morning + timedelta(minutes=5), shown=None, reads={B: (9, 9, 0)}, unknown={"KS"}, named={}
    )
    night = at("2026-11-17 03:10")
    log.record(night, shown="v1", reads={B: (2, 2, 0)}, unknown=(),
               named={"2900002": {"*": {ANY_KIND}}})  # fmt: skip
    found = log.day(DAY)
    assert found is not None
    slot = found.slots[slot_of(morning)]
    assert slot.shown == {"v1"}
    assert slot.reads == {A: {(4, 4, 0)}}  # the refused pass's read of B is not kept
    assert slot.unknown == {"KS"}
    assert slot.named == {"2900001": {DAY.isoformat(): {"delayed"}}}
    # 03:10Z is outside the read band: what it named is kept, its reads are not.
    assert found.slots["03:00"].reads == {}
    assert found.slots["03:00"].named == {"2900002": {"*": {ANY_KIND}}}
    # The file reads back as written.
    assert MorningDay.from_bytes(log.path(DAY).read_bytes()) == found
    assert log.through() == morning + timedelta(minutes=5)
    # A file that does not read is damaged, and stays so once a pass writes over it.
    log.path(DAY).write_text("{")
    damaged = log.day(DAY)
    assert damaged is not None
    assert damaged.damaged
    log.record(morning + timedelta(minutes=10), shown="v1", reads={}, unknown=(), named={})
    again = log.day(DAY)
    assert again is not None
    assert again.damaged
    assert json.loads(log.path(DAY).read_text())["damaged"] is True
    # Old days are pruned.
    later = morning + timedelta(days=11)
    log.record(later, shown=None, reads={}, unknown=(), named={})
    assert log.days() == [later.date()]


def test_a_pass_is_shown_only_when_the_map_shows_its_merge() -> None:
    now = at("2026-11-17 13:10")
    assert shown(PassReport(Exit.OK, now, uploaded=("live/closings.json",)))
    assert shown(PassReport(Exit.OK, now, note="unchanged"))
    assert not shown(PassReport(Exit.OK, now, note="publishing is off"))
    assert not shown(PassReport(Exit.REFUSED, now, refusals=("health",)))
    assert not shown(PassReport(Exit.ERROR, now, note="publish: OSError"))
    assert not shown(PassReport(Exit.OK, now, uploaded=("x",), blank=True))


def test_each_pass_adds_itself_to_the_record(tmp_path: Path) -> None:
    world = _world()
    now = at("2026-11-17 13:05")
    _warm(world, A, now)
    ingest = _ingest(world, tmp_path)
    ingest.morning = MorningLog(tmp_path / "state" / "morning")
    report = ingest.run_pass([SourceRead(A, ReadOutcome.OK, now, CLOSED)], now)
    assert report.exit is Exit.OK
    found = ingest.morning.day(DAY)
    assert found is not None
    slot = found.slots[slot_of(now)]
    assert slot.shown == {"v1-shadow"}
    assert slot.reads == {A: {(1, 1, 0)}}
    assert set(slot.named) == {leaid for leaid in slot.named if len(leaid) == 7}
    assert any(DAY.isoformat() in days for days in slot.named.values())
    assert all(kinds == {"closed"} for days in slot.named.values() for kinds in days.values())
    # A refused pass (nothing healthy) names what its rows name and gives no read.
    later = now + timedelta(minutes=40)
    refused = ingest.run_pass([SourceRead(A, ReadOutcome.ERROR, later)], later)
    assert refused.exit is Exit.REFUSED
    found = ingest.morning.day(DAY)
    assert found is not None
    assert found.slots[slot_of(later)].shown == set()
    assert found.slots[slot_of(later)].reads == {}


def test_a_pass_records_the_states_it_withheld_whole(tmp_path: Path) -> None:
    world = _world()
    morning = at("2026-11-17 13:05")
    _warm(world, A, morning)
    _warm(world, B, morning + timedelta(minutes=15))
    world.read(morning, list(CLOSED), source=A)
    # a process read B and stopped before it resolved it: B's say is unknown this pass
    world.read(morning + timedelta(minutes=15), list(RESCINDED), source=B)
    ingest = _ingest(world, tmp_path)
    ingest.morning = MorningLog(tmp_path / "state" / "morning")
    later = morning + timedelta(minutes=20)
    report = ingest.run_pass([SourceRead(A, ReadOutcome.OK, later, CLOSED)], later)
    assert report.counts["unknown_states"] == 5
    found = ingest.morning.day(DAY)
    assert found is not None
    assert len(found.slots[slot_of(later)].unknown) == 5
