"""False and stale states the second review found (round 3): lists re-worded overnight,
rows back on a later day, a school's own row against its district, learning and planned
words, rows taken down before their day, stated places, terms, stored payloads, versions,
directory editions, tied predecessors and provenance levels."""

import dataclasses
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from live.world import (
    ALPHA,
    ALPHA_DISTRICT,
    ALPHA_SCHOOL,
    ESCAMBIA_REGULAR,
    World,
    _school,
    accepted,
    at,
    directory,
    lit,
    reasons,
    row,
    station,
    stub_reader,
)
from snowlight.listed.located import Place
from snowlight.live.guards import Withheld
from snowlight.live.ledger import Ledger, Outcome, SeenRow, Start
from snowlight.live.resolve import Resolver, StatusReader, f5_reader
from snowlight.live.versions import (
    files_digest,
    live_version,
    matcher_version,
    reader_matcher_version,
    reader_version,
)

A = "gray-synthetic"
B = "flashalert-synthetic"
OTHERS = [row(f"SYNTHETIC Other {n}") for n in range(3)]
"""Unmatched listings, so that taking one row down is not a partial read."""
READERS: tuple[tuple[str, StatusReader], ...] = (("stub", stub_reader), ("f5", f5_reader()))


def _names(reader: StatusReader = stub_reader, count: int = 10) -> World:
    """``count`` SYNTHETIC schools, each its own listing, with reads on Friday and Monday
    03:55 CT (2026-11-16)."""
    extra = [
        _school(f"5000000000{n:02d}", 100 + n, name=f"SYNTHETIC S{n}", district=f"50000{n:02d}")
        for n in range(count)
    ]
    world = World(reader=reader, dir=directory(extra))
    for n in range(count):
        world.matcher.table[f"SYNTHETIC S{n}"] = accepted(direct=(f"5000000000{n:02d}",))
    world.read(at("2026-11-13 15:00"), [])
    world.read(at("2026-11-16 09:55"), [])
    return world


def _list(text: str, count: int = 10) -> list[SeenRow]:
    return [row(f"SYNTHETIC S{n}", text) for n in range(count)]


def _overnight(world: World, rows: list[SeenRow], until: str = "2026-11-17 10:55") -> None:
    """Read the same rows every two hours from Monday 06:00 CT until ``until``."""
    moment = at("2026-11-16 12:00")
    while moment <= at(until):
        world.read(moment, rows)
        moment += timedelta(hours=2)
    world.read(at(until), rows)


# --- R2-B1: a list re-worded overnight keeps Monday's dating ----------------------------------


def test_r2_b1_a_whole_list_re_worded_overnight_lights_nothing_on_tuesday() -> None:
    for label, reader in READERS:
        for before, after in (("Closed", "Closed due to snow"), ("Closed", "Closed - Snow")):
            world = _names(reader)
            world.read(at("2026-11-16 11:00"), _list(before))  # Monday 05:00 CT
            assert len(lit(world.publish(at("2026-11-16 11:05")))) == 10
            _overnight(world, _list(before))
            observed = world.ledger.observe(A, Outcome.OK, at("2026-11-17 11:00"), _list(after))
            world.last[A] = _list(after)
            assert observed.key_churn
            assert not observed.churn  # the names stay: every new key is a successor
            assert len(observed.successors) == 10
            merged = world.publish(at("2026-11-17 15:00"))  # Tuesday 09:00 CT
            assert lit(merged) == {}, (label, after)
            (source,) = world.resolve()
            assert source.counts.get("successor:reworded") is None  # settled on the first pass
            present = [r for r in source.rows if r.present]
            assert {(r.row.lo, r.row.start) for r in present} == {(None, Start.REWORDED)}
            assert {r.derived.withheld for r in present} == {Withheld.REWORDED}


def test_r2_b1_a_single_row_re_worded_overnight_lights_nothing_on_tuesday() -> None:
    cases = [
        ("stub", "Closed", "Closed due to snow"),
        ("f5", "Closed", "Closed - Snow"),
        ("f5", "2 Hour Delay", "2 Hour Delay - 10:00 AM start"),
        ("f5", "Closed", "Closed - weather"),
    ]
    readers = dict(READERS)
    for label, before, after in cases:
        world = _names(readers[label], count=1)
        world.read(at("2026-11-16 11:00"), [row("SYNTHETIC S0", before)])
        assert len(lit(world.publish(at("2026-11-16 11:05")))) == 1
        _overnight(world, [row("SYNTHETIC S0", before)])
        world.read(at("2026-11-17 11:00"), [row("SYNTHETIC S0", after)])
        assert lit(world.publish(at("2026-11-17 11:05"))) == {}, (label, after)
        assert lit(world.publish(at("2026-11-17 15:00"))) == {}, (label, after)


def test_r2_b1_an_overnight_batch_of_upgrades_lights_the_new_day() -> None:
    """Every row's kind changes ("2 hour delay" to "Closed"): no re-render does that, so the
    successors keep their own interval, though every key is new and every old key gone."""
    for label, reader in READERS:
        world = _names(reader)
        world.read(at("2026-11-16 11:00"), _list("2 hour delay"))
        assert set(lit(world.publish(at("2026-11-16 11:05"))).values()) == {"DELAYED"}
        _overnight(world, _list("2 hour delay"))
        world.read(at("2026-11-17 11:00"), _list("Closed"))
        shown = lit(world.publish(at("2026-11-17 11:05")))
        assert shown == {(100 + n, "2026-11-17"): "CLOSED" for n in range(10)}, label


def test_r2_b1_a_same_morning_detail_change_keeps_the_status_lit() -> None:
    world = _names(count=1)
    world.read(at("2026-11-16 11:00"), [row("SYNTHETIC S0", "Closed")])
    world.publish(at("2026-11-16 11:05"))
    world.read(at("2026-11-16 11:30"), [row("SYNTHETIC S0", "Closed due to snow")])
    merged = world.publish(at("2026-11-16 11:35"))
    assert lit(merged) == {(100, "2026-11-16"): "CLOSED"}
    assert [c.reason for c in merged.closings] != [None]  # the new words' reason shows
    (source,) = world.resolve()
    assert source.counts.get("successor:same_either_way") is None  # settled on the first pass


def test_r2_b1_until_further_notice_added_overnight_stays_dark() -> None:
    """A row that now says "until further notice" reads Tuesday if posted overnight and
    Monday if it re-words Monday's posting: nothing tells which, so it lights nothing
    (round 4: fail dark, never an inherited dating)."""
    world = _names(count=1)
    world.read(at("2026-11-16 11:00"), [row("SYNTHETIC S0", "Closed")])
    world.publish(at("2026-11-16 11:05"))
    _overnight(world, [row("SYNTHETIC S0", "Closed")])
    world.read(at("2026-11-17 11:00"), [row("SYNTHETIC S0", "Closed until further notice")])
    merged = world.publish(at("2026-11-17 11:05"))
    assert lit(merged) == {}
    (source,) = world.resolve()
    (present,) = [r for r in source.rows if r.present]
    assert present.derived.withheld is Withheld.REWORDED
    assert present.derived.claims == ()


def test_r2_b1_a_row_first_read_without_a_day_and_re_worded_overnight_stays_dark() -> None:
    """The predecessor's words gave no day ("Closed" first seen at midday): whether the
    re-worded row changed what it says cannot be told, so it is left undated."""
    world = _names(count=1)
    world.read(at("2026-11-16 18:55"), [])
    world.read(at("2026-11-16 19:00"), [row("SYNTHETIC S0", "Closed")])  # Monday 13:00 CT
    assert lit(world.publish(at("2026-11-16 19:05"))) == {}
    _overnight(world, [row("SYNTHETIC S0", "Closed")])
    world.read(at("2026-11-17 11:00"), [row("SYNTHETIC S0", "Closed due to snow")])
    assert lit(world.publish(at("2026-11-17 11:05"))) == {}
    (source,) = world.resolve()
    (present,) = [r for r in source.rows if r.present]
    assert (present.row.lo, present.row.start) == (None, Start.REWORDED)


def test_r2_b1_a_key_churn_read_leaves_new_listings_cold() -> None:
    ledger = Ledger(":memory:")
    ledger.observe(A, Outcome.OK, at("2026-11-16 10:00"), [])
    ledger.observe(A, Outcome.OK, at("2026-11-16 11:00"), _list("Closed"))
    found = ledger.observe(
        A,
        Outcome.OK,
        at("2026-11-16 11:30"),
        [*_list("Closed - Snow"), row("SYNTHETIC Newcomer", "Closed - Snow")],
    )
    assert found.key_churn
    assert not found.churn
    starts = {
        entry.key: entry.start for entry in ledger.rows(A) if entry.hi == at("2026-11-16 11:30")
    }
    newcomer = ledger.key(A, row("SYNTHETIC Newcomer", "Closed - Snow"))
    assert starts.pop(newcomer) is Start.CHURN
    assert set(starts.values()) == {Start.WARM}  # the successors keep their interval


# --- R2-B2: a row back on a later day is a new appearance; a school's row stands -------------


def _two_day_storm(world: World, *, second: str) -> None:
    world.stations[B] = station(B)
    for source in (A, B):
        world.read(at("2026-11-13 15:00"), [], source=source)
    world.read(at("2026-11-16 10:55"), [])
    world.read(at("2026-11-16 11:00"), [row(ALPHA_SCHOOL, "Closed")])  # Monday 05:00 CT
    assert lit(world.publish(at("2026-11-16 11:05"))) == {(0, "2026-11-16"): "CLOSED"}
    moment = at("2026-11-16 16:00")  # cleared at Monday 10:00 CT
    while moment <= at("2026-11-17 10:55"):
        world.read(moment, [])
        world.read(moment, [], source=B)
        moment += timedelta(minutes=30)
    tuesday = [row(ALPHA_SCHOOL, "Closed")]
    if second == A:
        tuesday.append(row(ALPHA_DISTRICT, "2 hour delay"))
    world.read(at("2026-11-17 11:00"), tuesday)
    if second == B:
        world.read(at("2026-11-17 11:00"), [row(ALPHA_DISTRICT, "2 hour delay")], source=B)


def test_r2_b2_a_two_day_storm_never_shows_the_district_status_over_the_schools_row() -> None:
    for label, reader in READERS:
        for second in (A, B):
            world = World(reader=reader)
            _two_day_storm(world, second=second)
            school = next(
                e for e in world.ledger.rows(A) if e.key == world.ledger.key(A, row(ALPHA_SCHOOL))
            )
            assert (school.hi, school.lo, school.start) == (
                at("2026-11-17 11:00"),
                None,
                Start.COLD,
            )
            merged = world.publish(at("2026-11-17 11:05"))
            assert lit(merged) == {(1, "2026-11-17"): "DELAYED"}, (label, second)
            assert merged.counts["school_row_stands"] == 1


def test_r2_b2_a_key_back_after_a_live_absence_of_three_hours_is_warm() -> None:
    """T1f: three hours or more away while the list moved on is a new appearance, also when
    the read that brings it back is the first one past the three hours."""
    world = World()
    world.read(at("2026-11-13 15:00"), [])
    world.read(at("2026-11-16 09:00"), [])
    world.read(at("2026-11-16 11:00"), [row(ALPHA_SCHOOL), *OTHERS])
    world.read(at("2026-11-16 12:00"), [*OTHERS, row("SYNTHETIC Third")])
    world.read(at("2026-11-16 15:00"), [row(ALPHA_SCHOOL), *OTHERS])
    entry = world.ledger.row(world.ledger.key(A, row(ALPHA_SCHOOL)))
    assert entry is not None
    assert (entry.hi, entry.lo, entry.start) == (
        at("2026-11-16 15:00"),
        at("2026-11-16 12:00"),
        Start.WARM,
    )


def test_r2_b2_a_school_row_naming_the_same_kind_does_not_stand() -> None:
    world = World()
    world.read(at("2026-11-13 15:00"), [])
    world.read(at("2026-11-16 10:55"), [])
    world.read(at("2026-11-16 11:00"), [row(ALPHA_SCHOOL, "Closed")])  # Monday's
    _overnight(world, [row(ALPHA_SCHOOL, "Closed")])
    world.read(at("2026-11-17 11:00"), [row(ALPHA_SCHOOL, "Closed"), row(ALPHA_DISTRICT, "Closed")])
    merged = world.publish(at("2026-11-17 11:05"))
    assert lit(merged) == {(0, "2026-11-17"): "CLOSED", (1, "2026-11-17"): "CLOSED"}


def test_r2_b2_a_stand_needs_a_present_row_of_a_held_source() -> None:
    world = World()
    world.stations[B] = station(B)
    for source in (A, B):
        world.read(at("2026-11-13 15:00"), [], source=source)
        world.read(at("2026-11-16 10:55"), [], source=source)
    world.read(at("2026-11-16 11:00"), [row(ALPHA_SCHOOL, "Closed [conf=0.75]")])
    world.read(at("2026-11-16 11:00"), [row(ALPHA_DISTRICT, "2 hour delay")], source=B)
    assert lit(world.publish(at("2026-11-16 11:05"))) == {(1, "2026-11-16"): "DELAYED"}
    shown = lit(world.publish(at("2026-11-16 11:05"), held={A: False, B: True}))
    assert shown == {(0, "2026-11-16"): "DELAYED", (1, "2026-11-16"): "DELAYED"}


# --- R2-S2: a school's own withheld row stands against its district's status -----------------


def test_r2_s2_a_withheld_school_row_stands_against_its_district() -> None:
    for label, school_text in (
        ("weak", "Closed [conf=0.75]"),
        ("hedged", "Closed possible"),
        ("midday", None),
    ):
        world = World()
        world.read(at("2026-11-13 15:00"), [])
        world.read(at("2026-11-16 09:55"), [])
        if school_text is None:
            world.read(at("2026-11-16 11:00"), [row(ALPHA_DISTRICT, "2 hour delay")])
            world.read(
                at("2026-11-16 19:00"),
                [row(ALPHA_DISTRICT, "2 hour delay"), row(ALPHA_SCHOOL, "Closed")],
            )
            merged = world.publish(at("2026-11-16 19:05"))
        else:
            world.read(
                at("2026-11-16 11:00"),
                [row(ALPHA_DISTRICT, "2 hour delay"), row(ALPHA_SCHOOL, school_text)],
            )
            merged = world.publish(at("2026-11-16 11:05"))
        assert lit(merged) == {(1, "2026-11-16"): "DELAYED"}, label


# --- R2-S1: a cold row's later change is watched and dated ------------------------------------


def test_r2_s1_a_cold_row_that_upgrades_while_warm_lights() -> None:
    world = World()
    world.read(at("2026-11-13 15:00"), [])  # Friday: the previous school day was read
    world.read(at("2026-11-16 10:00"), [row(ALPHA_SCHOOL, "2 hour delay")])  # cold: 67 h gap
    world.publish(at("2026-11-16 10:01"))
    assert reasons(world.resolve()) == [Withheld.UNKNOWN_START.value]
    world.read(at("2026-11-16 10:55"), [row(ALPHA_SCHOOL, "2 hour delay")])
    world.publish(at("2026-11-16 10:56"))
    world.read(at("2026-11-16 11:00"), [row(ALPHA_SCHOOL, "Closed")])
    assert lit(world.publish(at("2026-11-16 11:05"))) == {(0, "2026-11-16"): "CLOSED"}


def test_r2_s1_a_cold_row_re_worded_stays_cold() -> None:
    world = World()
    world.read(at("2026-11-13 15:00"), [])
    world.read(at("2026-11-16 10:00"), [row(ALPHA_SCHOOL, "Closed")])  # cold
    world.publish(at("2026-11-16 10:01"))
    world.read(at("2026-11-16 10:55"), [row(ALPHA_SCHOOL, "Closed")])
    world.read(at("2026-11-16 11:00"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    assert lit(world.publish(at("2026-11-16 11:05"))) == {}


# --- R2-S3: learning, planned and unclear words stand against older statuses -----------------


def test_r2_s3_learning_planned_and_unclear_rows_darken_an_older_closing() -> None:
    texts = (
        "Flexible Learning Day",
        "Digital Day",
        "Flex learning",
        "Snow packet day, buses resume Wednesday",
        "Teacher workday",
        "Closed for SAT testing",
        "Closed Monday, 16th & 17th",
    )
    for label, reader in READERS:
        for text in texts:
            world = World(reader=reader)
            world.stations[B] = station(B)
            for source in (A, B):
                world.read(at("2026-11-13 15:00"), [], source=source)
                world.read(at("2026-11-16 10:25"), [], source=source)
            world.read(at("2026-11-16 10:30"), [row(ALPHA_SCHOOL, "Closed")])
            assert lit(world.publish(at("2026-11-16 10:35"))) == {(0, "2026-11-16"): "CLOSED"}
            world.read(at("2026-11-16 11:00"), [row(ALPHA_SCHOOL, text)], source=B)
            merged = world.publish(at("2026-11-16 11:05"))
            assert lit(merged) == {}, (label, text)
            dissent = [r.derived.dissent for s in world.resolve() for r in s.rows if r.present]
            assert any(d is not None for d in dissent), (label, text)


# --- R2-S4: a row taken down before its day began is not kept for it -------------------------


def test_r2_s4_an_evening_closing_taken_down_before_midnight_is_not_kept() -> None:
    world = World()
    world.read(at("2026-11-13 15:00"), [])
    world.read(at("2026-11-16 20:00"), [])
    world.read(at("2026-11-17 01:55"), OTHERS)
    world.read(at("2026-11-17 02:00"), [row(ALPHA_SCHOOL), *OTHERS])  # Mon 20:00
    assert lit(world.publish(at("2026-11-17 02:05"))) == {(0, "2026-11-17"): "CLOSED"}
    world.read(at("2026-11-17 03:30"), OTHERS)  # taken down at 21:30 CT
    merged = world.publish(at("2026-11-17 15:00"))
    assert lit(merged) == {}
    assert merged.withheld[Withheld.VANISHED_BEFORE_DAY.value] == 1


def test_r2_s4_a_row_taken_down_during_its_day_is_kept_through_it() -> None:
    world = World()
    world.read(at("2026-11-13 15:00"), [])
    world.read(at("2026-11-16 20:00"), [])
    world.read(at("2026-11-17 01:55"), OTHERS)
    world.read(at("2026-11-17 02:00"), [row(ALPHA_SCHOOL), *OTHERS])
    assert lit(world.publish(at("2026-11-17 02:05"))) == {(0, "2026-11-17"): "CLOSED"}
    world.read(at("2026-11-17 13:00"), OTHERS)  # 07:00 CT on its day
    merged = world.publish(at("2026-11-17 15:00"))
    assert lit(merged) == {(0, "2026-11-17"): "CLOSED"}
    assert len(merged.held_vanishes) == 1


# --- R2-S5 and S4: places in keys, duplicate keys, tied predecessors --------------------------


def test_r2_s5_rows_of_one_name_in_different_places_are_different_rows() -> None:
    ledger = Ledger(":memory:")
    here = row("SYNTHETIC Lincoln Elementary", places=(Place(state="KS", city="Topeka"),))
    there = row("SYNTHETIC Lincoln Elementary", places=(Place(state="MO", city="Joplin"),))
    assert ledger.key(A, here) != ledger.key(A, there)
    assert ledger.ident(A, here) != ledger.ident(A, there)
    spaced = row("SYNTHETIC Lincoln Elementary", places=(Place(state="ks", city=" TOPEKA "),))
    assert ledger.key(A, here) == ledger.key(A, spaced)
    found = ledger.observe(A, Outcome.OK, at("2026-11-16 11:00"), [here, there, spaced])
    assert found.counts["duplicate_keys"] == 1
    assert len(ledger.rows(A)) == 2


def test_s4_a_successor_of_two_tied_predecessors_has_no_known_start() -> None:
    for secret_run in range(3):
        ledger = Ledger(":memory:")
        ledger.observe(A, Outcome.OK, at("2026-11-16 10:00"), [])
        twins = [row("SYNTHETIC Twin", "Closed"), row("SYNTHETIC Twin", "2 hour delay")]
        ledger.observe(A, Outcome.OK, at("2026-11-16 11:00"), [*twins, *_list("Closed", 3)])
        found = ledger.observe(
            A,
            Outcome.OK,
            at("2026-11-16 11:30"),
            [row("SYNTHETIC Twin", "Closed due to snow"), *_list("Closed", 3)],
        )
        assert found.successors == (), secret_run
        assert found.counts["ambiguous_successors"] == 1
        entry = ledger.row(ledger.key(A, row("SYNTHETIC Twin", "Closed due to snow")))
        assert entry is not None
        assert (entry.lo, entry.start, entry.pred) == (None, Start.COLD, None)


# --- B1: a kept dissent follows its school to a new directory edition ------------------------


def test_b1_a_kept_dissent_follows_its_school_across_an_edition_change() -> None:
    world = World(stations={A: station(A), "nexstar-synthetic": station("nexstar-synthetic")})
    other = "nexstar-synthetic"
    for source in world.stations:
        world.read(at("2026-11-16 08:00"), [], source=source)
        world.read(at("2026-11-17 10:00"), [], source=source)
    world.read(at("2026-11-17 10:10"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    assert lit(world.publish(at("2026-11-17 10:12"))) == {(0, "2026-11-17"): "CLOSED"}
    world.read(at("2026-11-17 10:20"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    world.read(at("2026-11-17 10:20"), [row(ALPHA_SCHOOL, "Closing rescinded")], source=other)
    assert lit(world.publish(at("2026-11-17 10:22"))) == {}
    world.read(at("2026-11-17 10:30"), [row("SYNTHETIC Pacific School")], source=other)
    world.read(at("2026-11-17 10:30"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    world.matcher.table["SYNTHETIC Escambia Regular"] = accepted(direct=(ESCAMBIA_REGULAR,))
    assert lit(world.publish(at("2026-11-17 10:32"))) == {(7, "2026-11-17"): "CLOSED"}
    swap = {0: 6, 6: 0}
    schools = {
        sid: dataclasses.replace(school, index=swap.get(school.index, school.index))
        for sid, school in world.dir.schools.items()
    }
    world.dir = dataclasses.replace(world.dir, schools=schools, edition="synthetic-edition-2")
    world.read(at("2026-11-17 10:40"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    world.read(
        at("2026-11-17 10:40"),
        [row("SYNTHETIC Pacific School"), row("SYNTHETIC Escambia Regular", "Closed due to snow")],
        source=other,
    )
    merged = world.publish(at("2026-11-17 10:42"))
    # Alpha (now 6) stays dark; the school now at index 0 lights from its own row.
    assert lit(merged) == {(7, "2026-11-17"): "CLOSED", (0, "2026-11-17"): "CLOSED"}
    kept = [
        r
        for s in world.resolve()
        for r in s.rows
        if not r.present and r.derived.withheld is Withheld.NOT_DERIVED
    ]
    assert [[v.index for v in r.derived.voters] for r in kept] == [[6]]


def test_b1_a_kept_derivation_drops_a_school_the_edition_lost() -> None:
    world = World()
    world.read(at("2026-11-17 10:00"), [])
    resolver = world.resolver()
    world.read(at("2026-11-17 10:10"), [row(ALPHA_SCHOOL, "Closing rescinded")])
    (source,) = world.resolve()
    (result,) = source.rows
    schools = {sid: s for sid, s in world.dir.schools.items() if sid != ALPHA[0]}
    moved = Resolver(
        reader=world.reader,
        match=world.matcher,
        directory=dataclasses.replace(world.dir, schools=schools, edition="e3"),
        ledger=world.ledger,
        version=world.version,
        pollable=world.pollable,
    )
    assert moved.current(result.derived).voters == ()
    assert resolver.current(result.derived).voters == result.derived.voters


# --- S1: terms are checked before any reuse ----------------------------------------------------


def test_s1_terms_that_stop_permitting_polling_darken_rows_derived_before() -> None:
    for change in ("terms", "status"):
        world = World()
        world.read(at("2026-11-16 08:00"), [])
        world.read(at("2026-11-17 10:00"), [])
        world.read(at("2026-11-17 10:10"), [row(ALPHA_SCHOOL, "Closed due to snow")])
        assert lit(world.publish(at("2026-11-17 10:12"))) == {(0, "2026-11-17"): "CLOSED"}
        original = world.stations[A]
        if change == "terms":
            world.pollable = {**world.pollable, "gray": False}
        else:
            world.stations[A] = original.model_copy(update={"status": "no_endpoint"})
        world.read(at("2026-11-17 10:20"), [row(ALPHA_SCHOOL, "Closed due to snow")])
        assert lit(world.publish(at("2026-11-17 10:22"))) == {}, change
        assert reasons(world.resolve()) == [Withheld.TERMS.value]
        world.pollable = {**world.pollable, "gray": True}
        world.stations[A] = original
        world.read(at("2026-11-17 10:30"), [row(ALPHA_SCHOOL, "Closed due to snow")])
        # TERMS is never stored, so the row lights again once the terms permit it
        assert lit(world.publish(at("2026-11-17 10:32"))) == {(0, "2026-11-17"): "CLOSED"}


# --- S2: a stored payload that is not JSON is counted, never fatal ----------------------------


def test_s2_a_stored_payload_that_is_not_json_is_counted_and_never_raises() -> None:
    world = World()
    world.read(at("2026-11-16 08:00"), [])
    world.read(at("2026-11-17 10:00"), [])
    world.read(at("2026-11-17 10:10"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    world.publish(at("2026-11-17 10:12"))
    for bad in ("{not json", "", '"just a string"', "[1, 2"):
        world.ledger._db.execute("UPDATE derived SET payload = ?", (bad,))
        world.ledger._db.commit()
        (source,) = world.resolve()
        assert source.counts["bad_derived"] == 1, bad
        assert lit(world.publish(at("2026-11-17 10:14"))) == {(0, "2026-11-17"): "CLOSED"}
        (key,) = [entry.key for entry in world.ledger.rows(A)]
        world.ledger._db.execute("UPDATE derived SET payload = ?", (bad,))
        world.ledger._db.commit()
        stored = world.ledger.last_derived(key)
        assert stored is not None
        assert stored[1] is None or bad == '"just a string"'
    with pytest.raises(sqlite3.IntegrityError):
        world.ledger._db.execute("UPDATE derived SET payload = NULL")


# --- S3: the reader's and the matcher's versions are computed --------------------------------


def test_s3_versions_are_digests_of_the_code_and_tables(tmp_path: Path) -> None:
    one, two = tmp_path / "a.py", tmp_path / "b.py"
    one.write_text("x = 1\n")
    two.write_text("y = 2\n")
    first = files_digest([two, one], root=tmp_path)
    assert first == files_digest([one, two, one], root=tmp_path)  # order and repeats aside
    one.write_text("x = 3\n")
    assert files_digest([one, two], root=tmp_path) != first
    assert reader_version().startswith("f5-")
    assert matcher_version().startswith("f6-")
    assert live_version().startswith("live-")
    assert reader_matcher_version() == f"{reader_version()}|{matcher_version()}"
    world = World()
    computed = Resolver(
        reader=world.reader,
        match=world.matcher,
        directory=world.dir,
        ledger=world.ledger,
        pollable=world.pollable,
    )
    assert computed.version.startswith(reader_matcher_version() + "|")
    assert live_version() in computed.version


# --- S6: provenance names the matcher's level and the target's ------------------------------


def test_s6_provenance_keeps_the_match_level_and_the_target_level_apart() -> None:
    world = World()
    world.read(at("2026-11-16 08:00"), [])
    world.read(at("2026-11-17 10:00"), [])
    world.read(at("2026-11-17 10:10"), [row(ALPHA_DISTRICT, "Closed due to snow")])
    merged = world.publish(at("2026-11-17 10:12"))
    assert {(line["match_level"], line["target_level"]) for line in merged.provenance} == {
        ("district", "district")
    }
    world = World()
    world.matcher.table[ALPHA_SCHOOL] = dataclasses.replace(
        world.matcher.table[ALPHA_SCHOOL], level="alias_level"
    )
    world.read(at("2026-11-16 08:00"), [])
    world.read(at("2026-11-17 10:00"), [])
    world.read(at("2026-11-17 10:10"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    merged = world.publish(at("2026-11-17 10:12"))
    assert [(line["match_level"], line["target_level"]) for line in merged.provenance] == [
        ("unknown", "school")
    ]
