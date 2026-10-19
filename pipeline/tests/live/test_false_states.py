"""False and stale states the first review found (round 2): batch upgrades, withheld
successors, lists restored after an empty spell, cross-level order, rows removed before their
day, undatable retractions, empty and 304 reads, and versions across processes."""

import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from live.world import (
    ALPHA_DISTRICT,
    ALPHA_SCHOOL,
    VERSION,
    World,
    _school,
    accepted,
    at,
    directory,
    lit,
    reasons,
    row,
    station,
)
from snowlight.live.guards import Rules, Withheld
from snowlight.live.ledger import Ledger, Outcome, SeenRow, Start
from snowlight.live.resolve import f5_reader

PIPELINE = Path(__file__).resolve().parents[2]
OTHER = "tegna-synthetic"
OTHERS = [row(f"SYNTHETIC Other {n}") for n in range(3)]
"""Unmatched listings, so that taking one row down is not a partial read."""


def _names(count: int = 10) -> World:
    """A world with ``count`` SYNTHETIC schools, each its own listing, warm on Friday and
    at Monday 04:00 CT (2026-11-16)."""
    extra = [
        _school(f"5000000000{n:02d}", 100 + n, name=f"SYNTHETIC S{n}", district=f"50000{n:02d}")
        for n in range(count)
    ]
    world = World(dir=directory(extra))
    for n in range(count):
        world.matcher.table[f"SYNTHETIC S{n}"] = accepted(direct=(f"5000000000{n:02d}",))
    world.read(at("2026-11-13 15:00"), [])
    world.read(at("2026-11-16 10:00"), [])
    return world


def _listing(count: int, text_of: dict[int, str], default: str) -> list[SeenRow]:
    return [row(f"SYNTHETIC S{n}", text_of.get(n, default)) for n in range(count)]


# --- B1: a batch of status changes is not churn ------------------------------------------------


def test_b1_a_storm_morning_batch_of_upgrades_lights_the_new_statuses() -> None:
    for changed in (5, 6, 10):
        world = _names()
        world.read(at("2026-11-16 10:30"), _listing(10, {}, "2 hour delay"))
        assert set(lit(world.publish(at("2026-11-16 10:35"))).values()) == {"DELAYED"}
        upgraded = _listing(10, dict.fromkeys(range(changed), "Closed"), "2 hour delay")
        world.read(at("2026-11-16 11:00"), upgraded)  # 05:00 CT
        for moment in ("2026-11-16 11:05", "2026-11-16 15:00", "2026-11-16 20:00"):
            world.read(at(moment), upgraded)
            shown = lit(world.publish(at(moment) + timedelta(minutes=1)))
            expected = {
                (100 + n, "2026-11-16"): "CLOSED" if n < changed else "DELAYED" for n in range(10)
            }
            assert shown == expected, (changed, moment)
        assert Withheld.CHURN.value not in reasons(world.resolve())


def test_b1_a_batch_retraction_darkens_every_retracted_school() -> None:
    world = _names()
    world.read(at("2026-11-16 10:30"), _listing(10, {}, "Closed"))
    assert len(lit(world.publish(at("2026-11-16 10:35")))) == 10
    world.read(
        at("2026-11-16 11:00"), _listing(10, dict.fromkeys(range(6), "Closing rescinded"), "Closed")
    )
    shown = lit(world.publish(at("2026-11-16 11:05")))
    assert shown == {(100 + n, "2026-11-16"): "CLOSED" for n in range(6, 10)}


def test_b1_churn_is_counted_on_listings_not_keys() -> None:
    ledger = Ledger(":memory:")
    ledger.observe("s", Outcome.OK, at("2026-11-16 10:00"), [])
    ledger.observe("s", Outcome.OK, at("2026-11-16 10:30"), _listing(10, {}, "2 hour delay"))
    upgrade = ledger.observe("s", Outcome.OK, at("2026-11-16 11:00"), _listing(10, {}, "Closed"))
    assert not upgrade.churn
    assert len(upgrade.successors) == 10
    renamed = [row(f"SYNTHETIC Renamed {n}") for n in range(10)]
    rerender = ledger.observe("s", Outcome.OK, at("2026-11-16 11:30"), renamed)
    assert rerender.churn
    assert {entry.start for entry in ledger.rows("s") if entry.hi == at("2026-11-16 11:30")} == {
        Start.CHURN
    }


def test_b1_a_list_whose_names_all_change_is_still_churn() -> None:
    world = _names()
    world.read(at("2026-11-16 10:30"), [row(f"SYNTHETIC Old {n}") for n in range(10)])
    world.read(at("2026-11-16 11:00"), _listing(10, {}, "Closed"))
    assert set(reasons(world.resolve())) >= {Withheld.CHURN.value}
    assert lit(world.publish(at("2026-11-16 11:05"))) == {}


# --- B2: a withheld successor leaves the school dark, never on the old status ----------------


def test_b2_a_closing_replaced_by_a_withheld_row_goes_dark() -> None:
    for successor in ("See district website", "Open", "2 hour delay [conf=0.75]"):
        world = World()
        world.read(at("2026-11-13 15:00"), [])
        world.read(at("2026-11-16 10:55"), [])
        world.read(at("2026-11-16 11:00"), [row(ALPHA_SCHOOL)])
        assert lit(world.publish(at("2026-11-16 11:05"))) == {(0, "2026-11-16"): "CLOSED"}
        world.read(at("2026-11-16 18:00"), [row(ALPHA_SCHOOL, successor)])  # noon CT
        merged = world.publish(at("2026-11-16 18:05"))
        assert lit(merged) == {}, successor
        assert merged.withheld[Withheld.SUPERSEDED.value] == 1


def test_b2_real_reader_an_evening_reversal_to_open_darkens_the_next_day() -> None:
    reader = f5_reader()
    for successor in ("Open", "Open on regular schedule", "Will be open", "Open Tuesday"):
        world = World(reader=reader)
        world.read(at("2026-11-13 15:00"), [])
        world.read(at("2026-11-16 22:00"), [])
        world.read(at("2026-11-17 00:00"), [row(ALPHA_SCHOOL)])  # Monday 18:00 CT: for Tuesday
        assert lit(world.publish(at("2026-11-17 00:05"))) == {(0, "2026-11-17"): "CLOSED"}
        world.read(at("2026-11-17 03:00"), [row(ALPHA_SCHOOL, successor)])  # 21:00 CT
        assert lit(world.publish(at("2026-11-17 03:05"))) == {}, successor
        world.read(at("2026-11-17 12:55"), [row(ALPHA_SCHOOL, successor)])
        assert lit(world.publish(at("2026-11-17 13:00"))) == {}, successor  # Tuesday 07:00 CT


def test_b2_a_re_rendered_row_stays_dark() -> None:
    world = World()
    world.read(at("2026-11-13 15:00"), [])
    world.read(at("2026-11-16 10:55"), [])
    world.read(at("2026-11-16 11:00"), [row(ALPHA_SCHOOL)])
    world.resolve()
    world.read(at("2026-11-17 11:00"), [row(ALPHA_SCHOOL, "CLOSED.")])  # same words, case
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL, "Closed ")])
    assert lit(world.publish(at("2026-11-17 11:06"))) == {}  # Monday's row is not Tuesday's
    world.read(at("2026-11-17 11:10"), [row(ALPHA_SCHOOL, "School closed")])  # reworded
    resolved = world.resolve()
    counts = resolved[0].counts
    assert counts.get("successor:reworded") == 1  # Monday's or Tuesday's posting: unknown
    assert lit(world.publish(at("2026-11-17 11:11"))) == {}


# --- B3: a list restored after an empty spell is not new -------------------------------------


def test_b3_rows_back_after_hours_of_empty_reads_are_not_dated_as_new() -> None:
    world = World()
    world.read(at("2026-11-13 15:00"), [], outcome=Outcome.EMPTY)
    world.read(at("2026-11-16 09:00"), [], outcome=Outcome.EMPTY)  # Monday 03:00 CT
    world.read(at("2026-11-16 11:00"), [row(ALPHA_SCHOOL)])  # Monday 05:00 CT
    assert lit(world.publish(at("2026-11-16 11:05"))) == {(0, "2026-11-16"): "CLOSED"}
    moment = at("2026-11-16 12:00")
    while moment < at("2026-11-17 11:00"):
        world.read(moment, [], outcome=Outcome.EMPTY)
        moment += timedelta(hours=1)
    world.read(at("2026-11-17 11:00"), [row(ALPHA_SCHOOL)])  # Tuesday 05:00 CT, the same row
    (entry,) = world.ledger.rows("gray-synthetic")
    # back on a later day after a quiet spell: a new appearance whose posting is unknown
    assert (entry.hi, entry.lo, entry.start) == (at("2026-11-17 11:00"), None, Start.COLD)
    assert lit(world.publish(at("2026-11-17 11:05"))) == {}


def test_b3_a_row_taken_down_overnight_and_back_while_the_list_stayed_quiet() -> None:
    world = World()
    world.read(at("2026-11-13 15:00"), [])
    world.read(at("2026-11-16 09:00"), [])
    world.read(at("2026-11-16 11:00"), [row(ALPHA_SCHOOL)])
    world.read(at("2026-11-16 23:00"), [])  # unconfirmed
    world.read(at("2026-11-16 23:05"), [])  # the list really emptied
    world.read(at("2026-11-17 11:00"), [row(ALPHA_SCHOOL)])
    assert lit(world.publish(at("2026-11-17 11:05"))) == {}


def test_b3_a_row_that_returns_after_a_live_list_moved_on_is_new() -> None:
    world = World()
    world.read(at("2026-11-13 15:00"), [])
    world.read(at("2026-11-16 09:00"), [])
    world.read(at("2026-11-16 11:00"), [row(ALPHA_SCHOOL), row("SYNTHETIC Other")])
    world.read(at("2026-11-16 18:00"), [row("SYNTHETIC Other"), row("SYNTHETIC Third")])
    world.read(at("2026-11-17 10:55"), [row("SYNTHETIC Other"), row("SYNTHETIC Third")])
    world.read(at("2026-11-17 11:00"), [row(ALPHA_SCHOOL), row("SYNTHETIC Other")])
    entry = next(r for r in world.ledger.rows("gray-synthetic") if r.hi == at("2026-11-17 11:00"))
    assert entry.lo == at("2026-11-17 10:55")
    assert lit(world.publish(at("2026-11-17 11:05"))) == {(0, "2026-11-17"): "CLOSED"}


# --- B4: a school's status never beats a district word it may be older than ------------------


def test_b4_an_overlapping_district_retraction_darkens_a_school_closing() -> None:
    reader = f5_reader()
    world = World(reader=reader, stations={"gray-synthetic": station(), OTHER: station(OTHER)})
    for source in world.stations:
        world.read(at("2026-11-13 15:00"), [], source=source)
    world.read(at("2026-11-16 10:30"), [], source=OTHER)
    world.read(at("2026-11-16 10:50"), [])
    world.read(at("2026-11-16 10:55"), [row(ALPHA_SCHOOL)])  # 04:50 to 04:55 CT
    assert lit(world.publish(at("2026-11-16 10:56"))) == {(0, "2026-11-16"): "CLOSED"}
    world.read(at("2026-11-16 11:00"), [row(ALPHA_DISTRICT, "Closing rescinded")], source=OTHER)
    merged = world.publish(at("2026-11-16 11:05"))  # 04:30 to 05:00 CT
    assert lit(merged) == {}
    assert merged.withheld[Withheld.CONFLICT.value] == 1


def test_b4_a_school_status_inside_a_district_interval_is_a_conflict() -> None:
    world = World(stations={"gray-synthetic": station(), OTHER: station(OTHER)})
    for source in world.stations:
        world.read(at("2026-11-13 15:00"), [], source=source)
    world.read(at("2026-11-16 10:20"), [], source=OTHER)
    world.read(at("2026-11-16 10:25"), [])
    world.read(at("2026-11-16 10:30"), [row(ALPHA_SCHOOL, "2 hour delay")])
    world.read(at("2026-11-16 10:40"), [row(ALPHA_DISTRICT)], source=OTHER)
    shown = lit(world.publish(at("2026-11-16 10:45")))
    assert shown == {(1, "2026-11-16"): "CLOSED"}  # the sibling; the school itself is unsure


def test_b4_one_list_holding_both_levels_is_a_real_tie_and_the_school_wins() -> None:
    world = World()
    world.read(at("2026-11-13 15:00"), [])
    world.read(at("2026-11-16 10:25"), [])
    both = [row(ALPHA_SCHOOL, "2 hour delay"), row(ALPHA_DISTRICT)]
    world.read(at("2026-11-16 10:30"), both)
    assert lit(world.publish(at("2026-11-16 10:35"))) == {
        (0, "2026-11-16"): "DELAYED",
        (1, "2026-11-16"): "CLOSED",
    }


# --- S1: a row removed well before its day ----------------------------------------------------


def test_s1_a_row_taken_down_before_its_day_does_not_light_it() -> None:
    for removed in (False, True):
        world = World()
        world.read(at("2026-11-13 15:00"), [])
        world.read(at("2026-11-17 23:55"), [])
        listing = [row(ALPHA_SCHOOL, "Closed Thursday"), *OTHERS]
        world.read(at("2026-11-18 00:00"), listing)  # Tuesday 18:00 CT
        world.resolve()
        moment = at("2026-11-18 11:00")  # Wednesday 05:00 CT on
        while moment <= at("2026-11-19 13:00"):
            world.read(moment, OTHERS if removed else listing)
            world.resolve()
            moment += timedelta(hours=1)
        merged = world.publish(at("2026-11-19 13:00"))  # Thursday 07:00 CT
        if removed:
            assert lit(merged) == {}
            assert merged.withheld[Withheld.VANISHED_BEFORE_DAY.value] == 1
        else:
            assert lit(merged) == {(0, "2026-11-19"): "CLOSED"}


def test_s1_a_status_lit_only_by_vanished_rows_is_logged() -> None:
    world = World()
    world.read(at("2026-11-13 15:00"), [])
    world.read(at("2026-11-16 10:55"), [])
    world.read(at("2026-11-16 11:00"), [row(ALPHA_SCHOOL), *OTHERS])
    world.publish(at("2026-11-16 11:01"))
    world.read(at("2026-11-16 14:00"), OTHERS)  # a same-day removal, kept
    merged = world.publish(at("2026-11-16 14:01"))
    assert lit(merged) == {(0, "2026-11-16"): "CLOSED"}
    (held,) = merged.held_vanishes
    assert (held.school, held.gone_at) == (0, at("2026-11-16 14:00"))
    assert merged.fast_vanishes == ()  # up for three hours: not a fast vanish


# --- S2: a retraction that cannot be dated still darkens --------------------------------------


def test_s2_a_cold_source_retraction_darkens_a_warm_closing() -> None:
    world = World(stations={"gray-synthetic": station(), OTHER: station(OTHER)})
    world.read(at("2026-11-13 15:00"), [])
    world.read(at("2026-11-16 10:55"), [])
    world.read(at("2026-11-16 11:00"), [row(ALPHA_SCHOOL)])
    assert lit(world.publish(at("2026-11-16 11:05"))) == {(0, "2026-11-16"): "CLOSED"}
    world.read(at("2026-11-16 12:00"), [row(ALPHA_SCHOOL, "Closing rescinded")], source=OTHER)
    merged = world.publish(at("2026-11-16 12:05"))
    assert lit(merged) == {}
    cold = [r for source in world.resolve() for r in source.rows if r.row.source_id == OTHER]
    assert [(r.derived.withheld, r.derived.dissent) for r in cold] == [(Withheld.UNKNOWN_START, ())]


def test_s2_a_cold_open_statement_darkens_and_a_cold_status_does_not() -> None:
    world = World(stations={"gray-synthetic": station(), OTHER: station(OTHER)})
    world.read(at("2026-11-13 15:00"), [])
    world.read(at("2026-11-16 10:55"), [])
    world.read(at("2026-11-16 11:00"), [row(ALPHA_SCHOOL)])
    world.read(at("2026-11-16 12:00"), [row(ALPHA_SCHOOL, "Open")], source=OTHER)
    merged = world.publish(at("2026-11-16 12:05"))
    assert lit(merged) == {}
    assert merged.opens == ()  # an undatable open statement is no signal for S7
    warm = World(stations={"gray-synthetic": station(), OTHER: station(OTHER)})
    warm.read(at("2026-11-13 15:00"), [])
    warm.read(at("2026-11-16 10:55"), [])
    warm.read(at("2026-11-16 11:00"), [row(ALPHA_SCHOOL)])
    warm.read(at("2026-11-16 12:00"), [row(ALPHA_SCHOOL, "2 hour delay")], source=OTHER)
    assert lit(warm.publish(at("2026-11-16 12:05"))) == {(0, "2026-11-16"): "CLOSED"}


# --- S3, S4: an emptied list and a 304 without its rows ---------------------------------------


def test_s3_an_emptied_list_is_unconfirmed_until_it_repeats() -> None:
    ledger = Ledger(":memory:")
    ledger.observe("s", Outcome.OK, at("2026-11-16 10:00"), [])
    ledger.observe("s", Outcome.OK, at("2026-11-16 11:00"), [row(ALPHA_SCHOOL)])
    first = ledger.observe("s", Outcome.EMPTY, at("2026-11-16 11:05"), [])
    assert first.outcome is Outcome.PARTIAL
    state = ledger.source("s")
    assert state is not None
    assert state.last_good_at == at("2026-11-16 11:00")  # the hold is not refreshed
    assert ledger.rows("s")[0].absent_since is None
    second = ledger.observe("s", Outcome.EMPTY, at("2026-11-16 11:10"), [])
    assert second.outcome is Outcome.EMPTY
    assert second.vanished == (ledger.rows("s")[0].key,)


def test_s4_a_304_without_rows_changes_no_presence() -> None:
    ledger = Ledger(":memory:")
    ledger.observe("s", Outcome.OK, at("2026-11-16 10:00"), [])
    ledger.observe("s", Outcome.OK, at("2026-11-16 11:00"), [row(ALPHA_SCHOOL)])
    for minutes in range(5, 300, 5):
        found = ledger.observe(
            "s", Outcome.NOT_MODIFIED, at("2026-11-16 11:00") + timedelta(minutes=minutes)
        )
        assert found.outcome is Outcome.NOT_MODIFIED
    (entry,) = ledger.rows("s")
    assert (entry.absent_since, entry.gone) == (None, False)
    assert entry.last_seen == at("2026-11-16 15:55")
    state = ledger.source("s")
    assert state is not None
    assert state.last_good_at == at("2026-11-16 15:55")
    empty = Ledger(":memory:")
    try:
        empty.observe("s", Outcome.NOT_MODIFIED, at("2026-11-16 11:00"))
    except ValueError:
        pass
    else:
        raise AssertionError("a 304 before any good read cannot be placed")


# --- version B1: the derived version is the same in every process -----------------------------


_DIGEST = (
    "from snowlight.live.guards import Rules\n"
    "print(Rules(breaker_limits={'b': 2, 'a': 1}).digest(), Rules().digest())\n"
)


def test_version_the_rules_digest_does_not_depend_on_the_hash_seed() -> None:
    found = set()
    for seed in ("0", "3", "5", "7"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        done = subprocess.run(  # noqa: S603 - this interpreter, a fixed program
            [sys.executable, "-c", _DIGEST],
            cwd=PIPELINE,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        found.add(done.stdout.strip())
    assert len(found) == 1
    assert (
        Rules(breaker_limits={"a": 1, "b": 2}).digest()
        == Rules(breaker_limits={"b": 2, "a": 1}).digest()
    )
    assert Rules().digest() != Rules(min_confidence=0.85).digest()


def test_version_a_bump_never_re_lights_a_retracted_closing() -> None:
    world = World(stations={"gray-synthetic": station(), "gray-other": station("gray-other")})
    for source in world.stations:
        world.read(at("2026-11-16 15:00"), [], source=source)
        world.read(at("2026-11-17 10:55"), [], source=source)
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    world.read(at("2026-11-17 11:05"), [], source="gray-other")
    assert lit(world.publish(at("2026-11-17 11:06"))) == {(0, "2026-11-17"): "CLOSED"}
    world.read(at("2026-11-17 11:20"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    world.read(
        at("2026-11-17 11:20"), [row(ALPHA_SCHOOL, "Closing rescinded")], source="gray-other"
    )
    assert lit(world.publish(at("2026-11-17 11:21"))) == {}
    world.read(at("2026-11-17 11:40"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    world.read(at("2026-11-17 11:35"), [], source="gray-other")
    world.read(at("2026-11-17 11:40"), [], source="gray-other")  # the retraction vanished
    assert lit(world.publish(at("2026-11-17 11:41"))) == {}
    world.version = f"{VERSION}|bumped"
    merged = world.publish(at("2026-11-17 11:42"))
    assert lit(merged) == {}
    vanished = [r for source in world.resolve() for r in source.rows if not r.present]
    assert [(r.derived.withheld, r.derived.dissent) for r in vanished] == [
        (Withheld.NOT_DERIVED, ())
    ]
    assert vanished[0].version.startswith(VERSION + "|")  # it keeps the version it was made under


def test_version_a_vanished_status_is_not_kept_across_a_bump() -> None:
    world = World()
    world.read(at("2026-11-16 15:00"), [])
    world.read(at("2026-11-17 10:55"), [])
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL), *OTHERS])
    world.publish(at("2026-11-17 11:06"))
    world.read(at("2026-11-17 11:30"), OTHERS)
    assert lit(world.publish(at("2026-11-17 11:31"))) == {(0, "2026-11-17"): "CLOSED"}
    world.version = f"{VERSION}|bumped"
    assert lit(world.publish(at("2026-11-17 11:32"))) == {}  # dark, never on an unchecked status


def test_version_a_re_render_after_a_bump_stays_dark() -> None:
    world = World()
    world.read(at("2026-11-13 15:00"), [])
    world.read(at("2026-11-16 10:55"), [])
    world.read(at("2026-11-16 11:00"), [row(ALPHA_SCHOOL), *OTHERS])  # Monday 05:00 CT
    assert lit(world.publish(at("2026-11-16 11:05"))) == {(0, "2026-11-16"): "CLOSED"}
    world.version = f"{VERSION}|bumped"
    world.read(at("2026-11-17 10:55"), [row(ALPHA_SCHOOL), *OTHERS])
    world.read(at("2026-11-17 11:00"), [row(ALPHA_SCHOOL, "School closed"), *OTHERS])  # re-rendered
    resolved = world.resolve()
    assert resolved[0].counts.get("successor:reworded") == 1
    assert lit(world.publish(at("2026-11-17 11:05"))) == {}  # never Tuesday's
