"""The automatic day bar (A1-A6; A7 is in ``test_cli``), the D+7 control, and the report."""

from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from replays.world import DAY, FakeParsed, World, ids, school, station, stub_parse, utc
from snowlight.output import dumps_json
from snowlight.replays.build import (
    MIN_LIT,
    BuildError,
    DayBuild,
    Lit,
    _check_invariants,
    build_day,
    built_for,
    day_bar,
    keep_share,
)
from snowlight.replays.control import ControlResult, control_day
from snowlight.replays.gates import Drop
from snowlight.replays.report import (
    AFTER_DIRECTORY_RISK,
    AUDIT_SIZE,
    DROPPED_SIZE,
    KNOWN_LIMITS,
    UNREAD_MIN,
    audit_sample,
    day_report,
    dropped_sample,
    report_path,
)
from snowlight.replays.seed import Quality
from snowlight.schemas.vocab import Status

MORN = utc("2024-01-16 05:26")
ON = "on=2024-01-16"
BUILT = built_for(
    rules_sha256="e" * 64,
    reader_sha256="a" * 64,
    matcher_sha256="b" * 64,
    registry_sha256="c" * 64,
    archive_sha256="d" * 64,
    zones_sha256="f" * 64,
    directory_generated_on="2026-09-24",
)
EAST, WEST = ids("0010", 130), ids("0011", 130)


def _world(*, day: date = DAY, conflicts: int = 0, east: int = 130) -> World:
    """Two SYNTHETIC stations in two markets, each lighting a district of 130 schools."""
    world = World(stations=[station("gray-a"), station("gray-b", market="SYNTHETIC market two")])
    world.add_schools(*(school(sid) for sid in (*EAST, *WEST)))
    at = utc(f"{day.isoformat()} 05:26")
    on = f"on={day.isoformat()}"
    world.row("gray-a", at, f"closed;{on}", name="east district", district=EAST[:east])
    world.row("gray-b", at, f"delayed;{on};note=unread_words", name="west district", district=WEST)
    clash = ids("0012", conflicts)
    world.add_schools(*(school(sid) for sid in clash))
    for n, sid in enumerate(clash):
        world.row("gray-a", at, f"closed;{on}", name=f"clash {n}", direct=[sid])
        world.row("gray-b", at, f"delayed;{on}", name=f"clash {n}", direct=[sid])
    return world


def _build(world: World, day: date = DAY, publish_ids: set[str] | None = None) -> DayBuild:
    return build_day(day, world.inputs(), built=BUILT, publish_ids=publish_ids)


def test_a_day_that_passes() -> None:
    made = _build(_world())
    assert made.passed, made.failures
    quality = made.seed.quality
    assert (quality.lit, quality.sources, quality.markets) == (260, 2, 2)
    assert (quality.corroborated, quality.conflicts) == (0, 0)
    assert made.control.passed
    statuses = made.seed.statuses
    assert [s[0] for s in statuses] == sorted(EAST + WEST)
    assert {s[1] for s in statuses} == {int(Status.CLOSED), int(Status.DELAYED)}
    assert {s[3] for s in statuses} == {"station_list"}


def test_a1_a_weekend_day_fails() -> None:
    saturday = date(2024, 1, 13)
    made = _build(_world(day=saturday), saturday)
    assert made.seed.quality.lit == 260
    assert made.failures == ("A1: weekend",)


def test_a2_too_few_schools_fails() -> None:
    made = _build(_world(east=MIN_LIT - 130 - 1))
    assert not made.passed
    assert made.failures[0].startswith("A2: 249 lit from 2 sources in 2 markets")


def test_a2_one_market_fails() -> None:
    world = _world()
    world.stations[1]["market"] = "SYNTHETIC market one"
    made = _build(world)
    assert made.failures == ("A2: 260 lit from 2 sources in 1 markets (at least 250, 2, 2)",)


def test_a3_too_many_conflicts_fails() -> None:
    assert _build(_world(conflicts=5)).passed  # 5 of 265 is under 2%
    made = _build(_world(conflicts=10))
    assert made.seed.quality.conflicts == 10
    assert made.failures == ("A3: 10 conflicts of 270",)


def test_a4_invariants_raise() -> None:
    world = _world()
    inputs = world.inputs()
    lit = Lit(school=EAST[0], status=Status.CLOSED, reason=None, stations=("gray-x",), evidence=())
    with pytest.raises(KeyError):
        _check_invariants({EAST[0]: lit}, inputs)
    world.stations.append(station("gray-x", states=("KS",)))
    with pytest.raises(BuildError):
        _check_invariants({EAST[0]: lit}, world.inputs())


def test_a5_a_control_that_lights_fails() -> None:
    quality = Quality(lit=300, sources=2, markets=2, corroborated=0, conflicts=0)
    lit = ControlResult(day=DAY, target=DAY + timedelta(days=7), lit=1, entries=1)
    assert day_bar(DAY, 2024, quality, lit, 1.0) == ("A5: the D+7 control lights 1",)
    ran = control_day(DAY, lambda target: (int(target == DAY + timedelta(days=7)), 0))
    assert not ran.passed


def test_a_row_of_the_days_captures_dated_a_week_on_fails_the_control() -> None:
    """The date-range gate would hide it from D; the control reads without that gate."""
    world = _world()
    (extra,) = ids("0013", 1)
    world.add_schools(school(extra))
    world.row("gray-a", MORN, "closed;on=2024-01-23", name="next week", direct=[extra])
    made = _build(world)
    assert made.control.target == date(2024, 1, 23)
    assert made.control.entries == 1
    assert made.control.lit == 1
    assert made.failures == ("A5: the D+7 control lights 1",)


def test_a_reader_that_resolves_dates_a_week_late_fails_the_control() -> None:
    def late(text: str, *, posted_at: datetime, tz: str) -> FakeParsed:
        parsed = stub_parse(text, posted_at=posted_at, tz=tz)
        week = timedelta(days=7)
        schedule = tuple(
            replace(entry, dates=tuple(when + week for when in entry.dates))
            for entry in parsed.schedule
        )
        return replace(parsed, schedule=schedule)

    made = build_day(DAY, _world().inputs(parse=late), built=BUILT)
    assert made.seed.quality.lit == 0
    assert made.control.lit == 260
    assert "A5: the D+7 control lights 260" in made.failures


def test_a_clean_day_lights_nothing_a_week_on() -> None:
    made = _build(_world())
    assert (made.control.entries, made.control.lit) == (0, 0)
    assert made.control.passed


def test_a6_a_publish_that_loses_ids_fails() -> None:
    world = _world()
    everyone = set(EAST + WEST)
    assert _build(world, publish_ids=everyone - set(EAST[:2])).passed  # under 1% missing
    made = _build(world, publish_ids=everyone - set(EAST[:8]))  # 3% missing
    assert made.failures == ("A6: a publish keeps 96.92% of ids",)
    assert keep_share([], set()) == 1.0


def test_the_builds_are_the_same_bytes() -> None:
    world = _world(conflicts=3)
    one, two = _build(world), _build(world)
    assert dumps_json(one.seed.as_json()) == dumps_json(two.seed.as_json())
    registry = world.registry()
    assert dumps_json(day_report(one, registry)) == dumps_json(day_report(two, registry))


# --- the report ---------------------------------------------------------------------------------


def test_the_report_counts_and_samples() -> None:
    world = _world(conflicts=3)
    world.row("gray-a", utc("2024-01-16 13:00"), "closed", name="late")
    world.row("gray-a", MORN, "closed;on=2024-01-16;note=hedged", name="hedge", direct=[EAST[0]])
    made = _build(world)
    report: Any = day_report(made, world.registry())
    assert report["day"] == "2024-01-16"
    assert report["lit"] == {
        "total": 259,
        "by_status": {"closed": 129, "delayed": 130, "remote": 0, "early_dismissal": 0},
    }
    assert report["conflicts"] == 3
    assert report["sources"] == ["gray-a", "gray-b"]
    assert report["drops"]["notes"] == {"hedged": 1}
    assert report["drops"]["rows"][Drop.NOTE.value] == 1
    audit = report["audit"]
    assert isinstance(audit, list)
    assert len(audit) == AUDIT_SIZE
    assert len({item["nces_id"] for item in audit}) == AUDIT_SIZE
    unread = [item for item in audit if "unread_words" in item["notes"]]
    assert len(unread) >= UNREAD_MIN
    assert {item["status"] for item in audit} == {"closed", "delayed"}
    assert {item["market"] for item in audit} == {
        "SYNTHETIC market one",
        "SYNTHETIC market two",
    }
    assert report_path(Path("out"), DAY) == Path("out/2024-01-16.report.internal.json")
    assert report["school_year"]["after_directory"] is False
    assert report["school_year"]["risk"] is None


def test_the_report_lists_special_schools_lit_through_districts_only() -> None:
    """The audit stratum facility programs fall in: alternative and special education schools
    a district's row lights with no row of their own. The facility guard holds every one of them
    to its own row, so the stratum is empty and the school with its own row is not in it."""
    world = _world()
    alone, own = ids("0013", 2)
    world.add_schools(
        school(alone, school_type="Alternative School"),
        school(own, school_type="Special Education School"),
    )
    at = utc("2024-01-16 05:26")
    world.row("gray-a", at, f"closed;{ON}", name="east district again", district=[alone, own])
    world.row("gray-a", at, f"closed;{ON}", name="its own row", direct=[own])
    report: Any = day_report(_build(world), world.registry())
    assert report["special_through_districts_only"] == []
    lit = _build(world).settled.lit
    assert alone not in lit
    assert own in lit


def test_a_storm_after_the_directorys_year_names_its_risk() -> None:
    world = _world()
    world.public_year = 2022
    report: Any = day_report(_build(world), world.registry())
    assert report["school_year"]["after_directory"] is True
    assert report["school_year"]["risk"] == AFTER_DIRECTORY_RISK
    assert report["school_year"]["lit_through_districts_only"] == sum(
        1
        for item in _build(world).settled.lit.values()
        if all(reading.level == "district" for reading in item.evidence)
    )


def test_the_audit_sample_is_smaller_when_few_are_lit() -> None:
    world = World(stations=[station("gray-a")])
    a, b = ids("0014", 2)
    world.add_schools(school(a), school(b))
    world.row("gray-a", MORN, f"closed;{ON}", direct=[a])
    world.row("gray-a", MORN, f"closed;{ON};note=unread_words", name="two", direct=[b])
    made = _build(world)
    sample: Any = audit_sample(made.settled.lit, world.registry(), day=DAY)
    assert sorted(item["nces_id"] for item in sample) == [a, b]


def test_the_dropped_sample_spreads_over_reasons() -> None:
    world = _world()
    for n in range(30):
        world.row("gray-a", MORN, "closed;note=hedged", name=f"hedge {n}", direct=[EAST[n]])
        world.row("gray-a", MORN, "closed;cause=holiday", name=f"cause {n}", direct=[EAST[n]])
    made = _build(world)
    sample: Any = dropped_sample(made.settled.dropped, day=DAY)
    assert len(sample) == DROPPED_SIZE
    assert {item["drop"] for item in sample} == {"note", "other_cause"}
    assert dropped_sample(made.settled.dropped, day=DAY) == sample


def test_the_report_names_the_known_limits() -> None:
    """Every report carries the classes the builder is known to read wrongly, so the audit and
    the live reader can learn from them."""
    world = _world()
    report: Any = day_report(_build(world), world.registry())
    assert report["known_limits"] == list(KNOWN_LIMITS)
    assert len(KNOWN_LIMITS) >= 8
    assert all(limit and limit == limit.strip() for limit in KNOWN_LIMITS)
