"""The live merge's breaker floor (G9): the live run's Ingest takes a floor of 15000 until the
archived per-source limits exist, the Resolver keeps the default rules (its digest is part of
``derived_version``), and a trip is logged with its source ids only."""

import ast
import dataclasses
import logging
from pathlib import Path

import pytest

from live.test_ingest import CLOSED, _ingest, _warm, _world
from live.world import World, accepted, at, directory, district_schools, lit, row
from snowlight.live import cli
from snowlight.live.cli import LIVE_MERGE_RULES
from snowlight.live.guards import Rules, breaker_limit
from snowlight.live.ingest import SourceRead
from snowlight.live.ledger import Outcome as ReadOutcome
from snowlight.live.versions import PUBLISHING_FILES

SOURCE = "gray-synthetic"


def test_the_live_merge_rules_change_only_the_breaker_floor() -> None:
    assert dataclasses.replace(Rules(), breaker_floor=15000) == LIVE_MERGE_RULES
    assert breaker_limit("any-source", LIVE_MERGE_RULES) == 15000
    assert breaker_limit(SOURCE, LIVE_MERGE_RULES) == 15000


def _calls(name: str) -> list[ast.Call]:
    tree = ast.parse(Path(cli.__file__).read_text())
    (build,) = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "build_parts"
    ]
    return [
        node
        for node in ast.walk(build)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name
    ]


def test_build_parts_gives_the_rules_to_the_ingest_and_not_to_the_resolver() -> None:
    (ingest,) = _calls("Ingest")
    rules = [keyword.value for keyword in ingest.keywords if keyword.arg == "rules"]
    assert [ast.unparse(value) for value in rules] == ["LIVE_MERGE_RULES"]
    (resolver,) = _calls("Resolver")
    assert all(keyword.arg != "rules" for keyword in resolver.keywords)
    assert not resolver.args


def test_the_files_changed_are_not_digested() -> None:
    assert {"cli.py", "ingest.py"} <= PUBLISHING_FILES


def _storm(rules: Rules) -> World:
    """One source's storm list: district rows of 17, 14 and 10 schools for today and for
    tomorrow, and 13 neighbouring schools for today (95 claim items)."""
    sizes = {"6000001": 17, "6000002": 14, "6000003": 10}
    schools = []
    first = 100
    for district, count in sizes.items():
        schools.extend(district_schools(district, count, first))
        first += count
    neighbours = district_schools("6000004", 13, first)
    world = World(dir=directory([*schools, *neighbours]), rules=rules)
    rows = []
    for district in sizes:
        name = f"SYNTHETIC District {district}"
        world.matcher.table[name] = accepted(
            via=tuple(s.record.id for s in schools if s.record.district_id == district)
        )
        rows += [row(name, "Closed due to snow"), row(name, "Closed tomorrow due to snow")]
    for number, school in enumerate(neighbours):
        name = f"SYNTHETIC Neighbour School {number}"
        world.matcher.table[name] = accepted(direct=(school.record.id,))
        rows.append(row(name, "Closed due to snow"))
    world.read(at("2026-11-17 02:00"), [])
    world.read(at("2026-11-17 11:00"), [])
    world.read(at("2026-11-17 11:05"), rows)
    return world


def test_a_real_storm_list_trips_the_flat_floor_of_50_and_not_the_live_floor() -> None:
    old = _storm(Rules()).publish(at("2026-11-17 11:06"))
    assert old.breakers == (SOURCE,)  # the Nov 2 trip under the default floor
    assert old.withheld["breaker"] == 95
    assert lit(old) == {}
    merged = _storm(LIVE_MERGE_RULES).publish(at("2026-11-17 11:06"))
    assert merged.breakers == ()
    assert merged.withheld.get("breaker", 0) == 0
    shown = lit(merged)
    assert len(shown) == 95
    assert set(shown.values()) == {"CLOSED"}
    assert {day for _school, day in shown} == {"2026-11-17", "2026-11-18"}


def test_a_trip_is_logged_once_with_the_source_id_only(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    world = _world()
    now = at("2026-11-17 11:05")
    _warm(world, SOURCE, now)
    ingest = _ingest(world, tmp_path)
    ingest.rules = Rules(breaker_floor=0)
    with caplog.at_level(logging.INFO, logger="snowlight.live.ingest"):
        ingest.run_pass([SourceRead(SOURCE, ReadOutcome.OK, now, CLOSED)], now)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert [r.getMessage() for r in warnings] == [f"breaker: {SOURCE}"]
    for record in caplog.records:
        text = record.getMessage()
        assert "SYNTHETIC" not in text
        assert "Closed" not in text
        assert "example.invalid" not in text


def test_a_pass_under_the_live_rules_logs_no_trip(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    world = _world()
    now = at("2026-11-17 11:05")
    _warm(world, SOURCE, now)
    ingest = _ingest(world, tmp_path)
    ingest.rules = LIVE_MERGE_RULES
    with caplog.at_level(logging.WARNING, logger="snowlight.live.ingest"):
        ingest.run_pass([SourceRead(SOURCE, ReadOutcome.OK, now, CLOSED)], now)
    assert not [r for r in caplog.records if r.getMessage().startswith("breaker")]
