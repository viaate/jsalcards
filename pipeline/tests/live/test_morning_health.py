"""The morning record's healthy share and per-source naming (advisory-sane L1), over the
SYNTHETIC world: both kept only from shown passes inside the read band, and a file written
before them still reads."""

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from live.test_ingest import CLOSED, A, _ingest, _warm, _world
from live.world import at
from snowlight.live.ingest import SourceRead
from snowlight.live.ledger import Outcome as ReadOutcome
from snowlight.live.morning import MorningDay, MorningLog, Slot, slot_of
from snowlight.live.publish import Exit

DAY = date(2026, 11, 17)
YESTERDAY = DAY - timedelta(days=1)


def test_the_lowest_share_and_each_source_s_districts_of_shown_band_passes_are_kept(
    tmp_path: Path,
) -> None:
    log = MorningLog(tmp_path / "morning")
    morning = at("2026-11-17 13:05")
    log.record(morning, shown="v1", reads={"tv": (4, 4, 0)}, unknown=(), named={},
               health=0.95, by={"tv": {"2900001"}, "radio": {"2900002"}})  # fmt: skip
    log.record(morning + timedelta(minutes=5), shown="v1", reads={"tv": (4, 4, 0)},
               unknown=(), named={}, health=0.9123, by={"tv": {"2900003"}})  # fmt: skip
    # A refused pass's share and naming are not kept (it was never on the map).
    log.record(morning + timedelta(minutes=10), shown=None, reads={"tv": (4, 4, 0)},
               unknown=(), named={}, health=0.1, by={"tv": {"2000004"}})  # fmt: skip
    # Outside the read band (03:10Z): neither is kept.
    night = at("2026-11-17 03:10")
    log.record(night, shown="v1", reads={"tv": (1, 1, 0)}, unknown=(), named={}, health=0.2,
               by={"tv": {"2000004"}})  # fmt: skip
    found = log.day(DAY)
    assert found is not None
    slot = found.slots[slot_of(morning)]
    assert slot.health == 912  # the lowest, in thousandths, rounded down
    # Only a source the pass read whole names districts here (radio was not read).
    assert slot.by == {"tv": {"2900001", "2900003"}}
    assert found.slots[slot_of(night)].health is None
    assert found.slots[slot_of(night)].by == {}
    assert MorningDay.from_bytes(log.path(DAY).read_bytes()) == found


def test_a_slot_written_before_the_share_reads_with_none() -> None:
    old = {"shown": ["v1"], "reads": {"tv": [[4, 4, 0]]}, "unknown": [], "named": {}}
    slot = Slot.from_json(old)
    assert slot.health is None
    assert slot.by == {}
    # And it writes back byte for byte as it was (no new keys when there is nothing to say).
    assert json.dumps(slot.to_json(), sort_keys=True) == json.dumps(old, sort_keys=True)
    for bad in (1001, -1, 0.5, True):
        try:
            Slot.from_json({**old, "health": bad})
        except ValueError:
            continue
        raise AssertionError(bad)


def test_a_pass_records_its_gate_share_and_what_each_read_source_named(tmp_path: Path) -> None:
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
    assert slot.health is not None
    assert 0 < slot.health <= 1000
    assert set(slot.by) == {A}
    assert slot.by[A] == set(slot.named)


# --- the per-day naming run, the day's own namings only, the stale empties -----------------------


def test_each_source_s_naming_is_stored_once_a_day_as_a_run(tmp_path: Path) -> None:
    log = MorningLog(tmp_path / "morning")
    start = at("2026-11-17 13:05")
    for minutes, named in ((0, {"2900001", "2900002"}), (30, {"2900001", "2900002"}),
                           (60, {"2900001", "2900003"}), (90, set())):  # fmt: skip
        log.record(start + timedelta(minutes=minutes), shown="v1", reads={"tv": (2, 2, 0)},
                   unknown=(), named={}, health=0.95, by={"tv": named})  # fmt: skip
    body = json.loads(log.path(DAY).read_bytes())
    assert body["by"] == {
        "tv": [
            ["13:00", ["2900001", "2900002"], []],
            ["14:00", ["2900003"], ["2900002"]],
            ["14:30", [], ["2900001", "2900003"]],
        ]
    }
    assert not [slot for slot in body["slots"].values() if "by" in slot]
    found = log.day(DAY)
    assert found is not None
    assert [found.slots[key].by for key in ("13:00", "13:30", "14:00", "14:30")] == [
        {"tv": {"2900001", "2900002"}},
        {"tv": {"2900001", "2900002"}},
        {"tv": {"2900001", "2900003"}},
        {"tv": set()},
    ]
    # A run that names a slot without a read of its source does not read: damaged.
    body["by"]["tv"].append(["20:00", ["2900009"], []])
    log.path(DAY).write_text(json.dumps(body))
    damaged = log.day(DAY)
    assert damaged is not None
    assert damaged.damaged


def _storm_day(
    root: Path, *, with_by: bool, districts: int = 900, sources: int = 90, flap: bool = False
) -> bytes:
    """SYNTHETIC: a storm morning where every district is named by about 2.5 lists, read by a
    shown pass in each of the read band's 24 slots, each list naming the same districts all
    day, or (``flap``) each list naming one half of its districts in even slots and the other
    half in odd ones (a feed that rotates its rows: the run encoding's worst case)."""
    import random  # noqa: PLC0415

    rng = random.Random(1)  # noqa: S311 - a fixed synthetic layout
    leaids = sorted({f"{rng.choice((17, 26, 36, 39, 42)):02d}{rng.randint(0, 40000):05d}"
                     for _ in range(districts)})  # fmt: skip
    names = [f"src-{i:03d}" for i in range(sources)]
    by: dict[str, set[str]] = {s: set() for s in names}
    for leaid in leaids:
        for source in rng.sample(names, max(1, int(rng.random() * 5))):
            by[source].add(leaid)
    named = {leaid: {DAY.isoformat(): ["closed"]} for leaid in leaids}
    reads = {s: (len(v), len(v), 0) for s, v in by.items()}
    log = MorningLog(root)
    first = at("2026-11-17 09:02")
    halves = [{s: set(sorted(v)[(i % 2) :: 2]) or v for s, v in by.items()} for i in range(2)]
    for i in range(24):
        named_by = halves[i % 2] if flap else by
        log.record(first + timedelta(minutes=30 * i), shown="v1", reads=reads, unknown=(),
                   named=named, health=0.95, by=named_by if with_by else None)  # fmt: skip
    return log.path(DAY).read_bytes()


def test_the_naming_run_adds_a_few_percent_to_a_storm_day(tmp_path: Path) -> None:
    import gzip  # noqa: PLC0415

    # Each list's districts once a day, not once a slot: at 900 districts about 2% more raw
    # and 6% more packed, falling with size (4% packed at 2,000; docs/live.md has 8,000).
    # Per slot, the same day was 30% more raw and 85% more packed.
    base = _storm_day(tmp_path / "base", with_by=False)
    with_by = _storm_day(tmp_path / "by", with_by=True)
    assert len(with_by) <= 1.03 * len(base)
    assert len(gzip.compress(with_by, 6)) <= 1.08 * len(gzip.compress(base, 6))
    # The worst case: every list rotating half its districts in and out every slot. Each
    # change is written, so the run costs about the per-slot shape: 60% more raw and 20% more
    # packed here and at 2,000 or 8,000 districts (docs/live.md gives the figures).
    flapping = _storm_day(tmp_path / "flap", with_by=True, flap=True)
    assert len(flapping) <= 1.65 * len(base)
    assert len(gzip.compress(flapping, 6)) <= 1.3 * len(gzip.compress(base, 6))


def test_only_rows_for_the_day_or_every_day_count_as_a_source_naming_a_district() -> None:
    from types import SimpleNamespace  # noqa: PLC0415

    from live.test_morning import claim  # noqa: PLC0415
    from snowlight.live.guards import Withheld  # noqa: PLC0415
    from snowlight.live.morning import named_by  # noqa: PLC0415
    from snowlight.live.resolve import Derived  # noqa: PLC0415

    def row(derived: Derived) -> SimpleNamespace:
        return SimpleNamespace(derived=derived, present=True, superseded=False)

    source = SimpleNamespace(
        source_id=A,
        rows=(
            row(Derived(withheld=None, claims=(claim(DAY),), reach=("2900001",))),
            # Yesterday's closing still on the list: not a naming for today.
            row(Derived(withheld=None, claims=(claim(YESTERDAY),), reach=("2900002",))),
            row(Derived(withheld=Withheld.WEAK, reach=("2900003",), kinds=("closed",))),
        ),
    )
    assert named_by([A], [source], DAY) == {A: {"2900001", "2900003"}}  # type: ignore[list-item]
    assert named_by([], [source], DAY) == {}  # type: ignore[list-item]


def test_an_empty_judged_from_old_rows_is_kept_apart(tmp_path: Path) -> None:
    log = MorningLog(tmp_path / "morning")
    morning = at("2026-11-17 14:05")
    log.record(morning, shown="v1", reads={"tv": (0, 0, 0), "radio": (0, 0, 0)}, unknown=(),
               named={}, health=0.95, stale={"tv", "paper"})  # fmt: skip
    # Not from a pass the map did not show, nor outside the band.
    log.record(morning + timedelta(minutes=5), shown=None, reads={"radio": (0, 0, 0)},
               unknown=(), named={}, stale={"radio"})  # fmt: skip
    found = log.day(DAY)
    assert found is not None
    assert found.slots[slot_of(morning)].stale == {"tv"}
    assert MorningDay.from_bytes(log.path(DAY).read_bytes()) == found


def test_the_reader_marks_an_empty_whose_health_gives_a_reason_stale() -> None:
    from live.test_live_reads import health  # noqa: PLC0415
    from snowlight.live.reads import source_read  # noqa: PLC0415
    from snowlight.sources.stations.fetch import RunResult  # noqa: PLC0415
    from snowlight.sources.stations.model import HealthStatus  # noqa: PLC0415
    from snowlight.sources.stations.registry import load_registry  # noqa: PLC0415

    registry = load_registry()
    station = next(s for s in registry.stations.values() if s.poll_url)
    now = at("2026-11-17 14:05")
    plain = RunResult()
    plain.health.append(health(station, HealthStatus.EMPTY, 200, now))
    old = RunResult()
    old.health.append(
        health(station, HealthStatus.EMPTY, 200, now).model_copy(
            update={"reason": "SYNTHETIC: its rows are old notes, not kept"}
        )
    )
    directory: Any = None
    fresh = source_read(station, plain, directory)
    judged = source_read(station, old, directory)
    assert fresh is not None
    assert judged is not None
    assert (fresh.outcome, fresh.stale) == (ReadOutcome.EMPTY, False)
    assert (judged.outcome, judged.stale) == (ReadOutcome.EMPTY, True)


def test_a_pass_keeps_a_stale_empty_apart_and_the_ledger_takes_it_as_any_empty(
    tmp_path: Path,
) -> None:
    world = _world()
    now = at("2026-11-17 13:05")
    _warm(world, A, now)
    ingest = _ingest(world, tmp_path)
    ingest.morning = MorningLog(tmp_path / "state" / "morning")
    report = ingest.run_pass([SourceRead(A, ReadOutcome.EMPTY, now, stale=True)], now)
    assert report.exit is Exit.OK
    assert ingest.stale == {A}
    found = ingest.morning.day(DAY)
    assert found is not None
    slot = found.slots[slot_of(now)]
    assert slot.reads == {A: {(0, 0, 0)}}
    assert slot.stale == {A}


def test_a_populated_list_naming_only_days_before_the_day_before_is_judged_old() -> None:
    # Round-4 review R4-S1: judged from the rows' own dates, never from what closed.
    from types import SimpleNamespace  # noqa: PLC0415

    from live.test_morning import claim  # noqa: PLC0415
    from snowlight.live.guards import Withheld  # noqa: PLC0415
    from snowlight.live.morning import old_lists  # noqa: PLC0415
    from snowlight.live.resolve import Derived  # noqa: PLC0415

    def row(derived: Derived, present: bool = True) -> SimpleNamespace:
        return SimpleNamespace(derived=derived, present=present, superseded=False)

    def source(name: str, *rows: SimpleNamespace) -> SimpleNamespace:
        return SimpleNamespace(source_id=name, rows=rows)

    earlier = DAY - timedelta(days=3)
    lists = [
        # Every row from an earlier storm: old.
        source("old", row(Derived(withheld=None, claims=(claim(earlier),), reach=("1",))),
               row(Derived(withheld=None, opens=(earlier,)))),
        # Yesterday's closings still up: not judged here (B1.3 judges it on a warning morning).
        source("yesterday", row(Derived(withheld=None, claims=(claim(YESTERDAY),)))),
        # One row for the day among old ones: current.
        source("mixed", row(Derived(withheld=None, claims=(claim(earlier),))),
               row(Derived(withheld=None, claims=(claim(DAY),)))),
        # Undated rows say nothing either way.
        source("undated", row(Derived(withheld=Withheld.WEAK, kinds=("closed",)))),
        # A row no longer present does not count.
        source("gone", row(Derived(withheld=None, claims=(claim(DAY),)), present=False),
               row(Derived(withheld=None, dissent=(earlier,)))),
    ]  # fmt: skip
    names = [s.source_id for s in lists]
    assert old_lists(names, lists, DAY) == {"old", "gone"}  # type: ignore[arg-type]
    assert old_lists(["mixed"], lists, DAY) == set()  # type: ignore[arg-type]
    assert old_lists([], lists, DAY) == set()  # type: ignore[arg-type]


def test_a_pass_marks_a_list_still_holding_an_earlier_storm_s_rows_stale(tmp_path: Path) -> None:
    # Round-4 review R4-S1: a row posted on the 13th (dated by its posting) still up on the
    # 16th and 17th; the day after, it is the day before's row (lead ruling B1.3's case).
    world = _world()
    posted = at("2026-11-13 13:05")
    _warm(world, A, posted)
    ingest = _ingest(world, tmp_path)
    ingest.morning = MorningLog(tmp_path / "state" / "morning")
    ingest.run_pass([SourceRead(A, ReadOutcome.OK, posted, rows=CLOSED)], posted)
    found: dict[str, set[str]] = {}
    for when in ("2026-11-14 13:05", "2026-11-16 13:05", "2026-11-17 13:05"):
        now = at(when)
        ingest.run_pass([SourceRead(A, ReadOutcome.OK, now, rows=CLOSED)], now)
        day = ingest.morning.day(now.date())
        assert day is not None
        slot = day.slots[slot_of(now)]
        assert slot.reads == {A: {(1, 1, 0)}}
        found[when[:10]] = slot.stale
    assert found == {"2026-11-14": set(), "2026-11-16": {A}, "2026-11-17": {A}}
