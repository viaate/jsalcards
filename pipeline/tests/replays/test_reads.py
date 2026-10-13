"""Source and read gates on SYNTHETIC lists: platforms, district sources, broken reads."""

from typing import Any

from replays.world import DAY, World, ids, school, station, utc
from snowlight.replays.build import settle_day
from snowlight.replays.gates import Drop
from snowlight.replays.rows import populated_reads

MORN = utc("2024-01-16 05:26")
ON = "on=2024-01-16"
SCHOOLS = ids("0002", 8)


def _world(*stations: dict[str, Any]) -> World:
    world = World(stations=[station("gray-a"), *stations])
    world.add_schools(*(school(sid) for sid in SCHOOLS))
    return world


def test_excluded_board_and_district_platforms_are_out() -> None:
    world = _world(
        station("apptegy-syn"), station("gohsep-syn"), station("edlio-syn"), station("riba-syn")
    )
    for source in ("apptegy-syn", "gohsep-syn", "edlio-syn", "riba-syn"):
        world.row(source, MORN, f"closed;{ON}", direct=[SCHOOLS[0]])
    settled = settle_day(world.inputs(), DAY)
    assert settled.lit == {}
    assert settled.row_drops == {Drop.PLATFORM.value: 4}
    assert settled.reads == ()


def test_a_district_level_source_is_out() -> None:
    world = _world(station("hearst-district", leaids=["9900001"]))
    world.row("hearst-district", MORN, f"closed;{ON}", direct=[SCHOOLS[0]])
    settled = settle_day(world.inputs(), DAY)
    assert settled.lit == {}
    assert settled.row_drops == {Drop.DISTRICT_SOURCE.value: 1}


def test_an_unregistered_source_is_out() -> None:
    world = _world()
    world.row("gray-gone", MORN, f"closed;{ON}", direct=[SCHOOLS[0]])
    settled = settle_day(world.inputs(), DAY)
    assert settled.row_drops == {Drop.UNKNOWN_SOURCE.value: 1}


def test_a_read_with_many_unread_rows_drops_whole() -> None:
    world = _world()
    world.row("gray-a", MORN, f"closed;{ON}", name="a", direct=[SCHOOLS[0]])
    world.row("gray-a", MORN, f"closed;{ON}", name="b", direct=[SCHOOLS[1]])
    world.row("gray-a", MORN, "nothing", name="c", direct=[SCHOOLS[2]])
    world.row("gray-a", MORN, "nothing", name="d", direct=[SCHOOLS[3]])
    settled = settle_day(world.inputs(), DAY)
    assert settled.lit == {}
    assert settled.row_drops == {Drop.READ_UNREADABLE.value: 4}
    (check,) = settled.reads
    assert check.unread_share == 0.5
    assert check.drop is Drop.READ_UNREADABLE


def test_a_quarter_unread_is_kept() -> None:
    world = _world()
    for n, status in enumerate((f"closed;{ON}", f"closed;{ON}", f"closed;{ON}", "nothing")):
        world.row("gray-a", MORN, status, name=f"r{n}", direct=[SCHOOLS[n]])
    settled = settle_day(world.inputs(), DAY)
    assert len(settled.lit) == 3
    assert settled.reads[0].drop is None


def _history(world: World, reads: int) -> None:
    """Earlier SYNTHETIC captures of ``gray-a`` where every row matches."""
    for n in range(reads):
        at = utc(f"2023-12-{n + 1:02d} 06:00")
        world.row("gray-a", at, f"closed;on=2023-12-{n + 1:02d}", name="old", direct=[SCHOOLS[0]])


def _thin_day(world: World) -> None:
    world.row("gray-a", MORN, f"closed;{ON}", name="a", direct=[SCHOOLS[0]])
    for n in range(4):
        world.row("gray-a", MORN, f"closed;{ON}", name=f"church {n}")


def test_a_read_far_under_its_stations_median_match_share_drops() -> None:
    world = _world()
    _history(world, 3)
    _thin_day(world)
    settled = settle_day(world.inputs(), DAY)
    (check,) = settled.reads
    assert check.match_share == 0.2
    assert check.station_median == 1.0
    assert check.drop is Drop.READ_LOW_MATCH
    assert settled.lit == {}


def test_under_three_reads_there_is_no_median_gate() -> None:
    world = _world()
    _history(world, 1)
    _thin_day(world)
    settled = settle_day(world.inputs(), DAY)
    (check,) = settled.reads
    assert check.station_median is None
    assert check.drop is None
    assert set(settled.lit) == {SCHOOLS[0]}
    assert settled.row_drops == {Drop.NOT_MATCHED.value: 4}


def test_a_stations_populated_reads_in_time_order() -> None:
    world = _world()
    _history(world, 2)
    world.empty_read("gray-a", MORN)
    reads = populated_reads(world.loaded(), "gray-a")
    assert [read.fetched_at for read in reads] == sorted(read.fetched_at for read in reads)
    assert len(reads) == 2
    assert populated_reads(world.loaded(), "gray-b") == ()
