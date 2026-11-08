"""A district row about the pre-K program alone, in any spelling, lights no school (SYNTHETIC)."""

import pytest

from live.world import ALPHA_DISTRICT, World, at, lit, row
from snowlight.live.guards import names_part
from snowlight.live.resolve import f5_reader

PROBES = [
    ("Closed for Pre K students", "Closed for pre-K students"),
    ("PK\nclosed", "pre-K\nclosed"),
    ("2 hour delay for pre k students", "2 hour delay for pre-K students"),
    ("Pre K\n2 hour delay", "pre-K\n2 hour delay"),
    ("Closed for Pre\u2011K students", "Closed for pre-K students"),
    ("PreK\u2013only: 2 hour delay", "pre-K only: 2 hour delay"),
    ("No school for PK students", "No school for pre-K students"),
]


def _world(text: str) -> World:
    world = World(reader=f5_reader())
    world.read(at("2026-11-17 02:00"), [])
    world.read(at("2026-11-17 11:00"), [])
    world.read(at("2026-11-17 11:05"), [row(ALPHA_DISTRICT, text)])
    return world


@pytest.mark.parametrize(("text", "spelled"), PROBES)
def test_a_preschool_only_district_row_lights_no_school(text: str, spelled: str) -> None:
    """The critic's probes: each lit both schools of the district before. Both schools are
    part-of-district voters, as with the "pre-K" spelling (the reader may still withhold the
    "pre-K" row for its own note; that is the reader's, not the guard's)."""
    world = _world(text)
    assert names_part(text)
    assert lit(world.publish(at("2026-11-17 11:06"))) == {}
    same = _world(spelled)
    assert lit(same.publish(at("2026-11-17 11:06"))) == {}
    for resolved in (world.resolve(), same.resolve()):
        assert [source.counts["target:part_of_district"] for source in resolved] == [2]


@pytest.mark.parametrize("text", ["Closed", "2 hour delay", "Closed \u2013 icy roads"])
def test_a_whole_district_row_with_no_program_word_lights_both_schools(text: str) -> None:
    world = _world(text)
    assert not names_part(text)
    assert set(lit(world.publish(at("2026-11-17 11:06")))) == {
        (0, "2026-11-17"),
        (1, "2026-11-17"),
    }
