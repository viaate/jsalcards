"""The pre-K program in every spelling names part of a district, as "pre-K" does (SYNTHETIC)."""

import pytest

from replays.world import DAY, World, ids, school, station, utc
from snowlight.replays.build import Settled, names_part_of_district, settle_day
from snowlight.replays.gates import Drop

MORN = utc("2024-01-16 05:26")
ON = "on=2024-01-16"
S1, S2 = ids("0001", 2)
DASHES = ("-", "\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212")
SPELLINGS = (
    *(
        f"{pre}{dash}{k}"
        for dash in DASHES
        for pre, k in (("Pre", "K"), ("pre", "k"), ("PRE", "K"))
    ),
    "PK",
    "pk",
    "Pk",
    "Pre K",
    "pre k",
    "PRE K",
    "PreK",
    "prek",
    "PREK",
)
FORMS = (
    "{p} closed",
    "{p}: closed",
    "{p} - 2 hour delay",
    "Closed for {p} students",
    "2 hour delay for {p} students",
    "Closed, {p} only",
    "{p} only: early dismissal",
    "{p}\nclosed",
    "{p}\n2 hour delay",
    "No school for {p} students",
    "Closed, no {p}",
    "All {p} classes cancelled",
)
BANDS = ("{p}-5", "{p}-8", "{p}-12", "{p}\u20135", "{p}\u201312", "{p}\u20148")


@pytest.mark.parametrize("spelling", SPELLINGS)
@pytest.mark.parametrize("form", FORMS)
def test_every_spelling_reads_as_pre_k_does(spelling: str, form: str) -> None:
    assert names_part_of_district(form.format(p=spelling)) is names_part_of_district(
        form.format(p="pre-K")
    )


@pytest.mark.parametrize("spelling", SPELLINGS)
@pytest.mark.parametrize("form", FORMS[:10])
def test_a_preschool_only_row_is_a_part_row(spelling: str, form: str) -> None:
    assert names_part_of_district(form.format(p=spelling))


@pytest.mark.parametrize("spelling", SPELLINGS)
@pytest.mark.parametrize("band", BANDS)
def test_a_grade_band_reads_as_the_pre_k_12_band_does(spelling: str, band: str) -> None:
    """ "Pre-K-12 closed" names a part today (the pre-K word): every band spelling does too."""
    assert names_part_of_district("Pre-K-12 closed")
    assert names_part_of_district(f"{band.format(p=spelling)} closed")
    assert names_part_of_district(f"Closed for {band.format(p=spelling)}")


@pytest.mark.parametrize(
    "text",
    [
        "Closed",
        "2 hour delay",
        "Closed \u2013 icy roads",
        "Closed \u2014 all schools",
        "Closed - PKWY flooded",
        "Closed, Spk road",
        "PKG lot icy, closed",
        "Closed: snow, ice \u2212 wind",
        "Prekindle closed",
        "All campuses closed",
    ],
)
def test_a_whole_district_row_stays_whole(text: str) -> None:
    assert not names_part_of_district(text)


@pytest.mark.parametrize("dash", DASHES[1:])
def test_a_dash_reads_as_a_hyphen_for_every_part_word(dash: str) -> None:
    assert names_part_of_district(f"K{dash}8 closed")
    assert names_part_of_district(f"Closed at Lincoln{dash}Douglas School")


def _world() -> World:
    world = World(stations=[station("gray-a")])
    world.add_schools(school(S1), school(S2))
    return world


def _settle(world: World) -> Settled:
    return settle_day(world.inputs(), DAY)


@pytest.mark.parametrize(
    "comment", ["Pre K students", "PK", "pre k only", "Pre\u2011K", "PreK", "pk students"]
)
def test_a_preschool_only_district_row_lights_no_school(comment: str) -> None:
    world = _world()
    world.row("gray-a", MORN, f"closed;{ON}", name="district", district=[S1, S2], comment=comment)
    settled = _settle(world)
    assert settled.lit == {}
    assert settled.target_drops[Drop.PART_OF_DISTRICT.value] == 2


def test_a_whole_district_row_still_lights_its_schools() -> None:
    world = _world()
    world.row("gray-a", MORN, f"closed;{ON}", name="district", district=[S1, S2], comment="Snow")
    settled = _settle(world)
    assert set(settled.lit) == {S1, S2}
    assert Drop.PART_OF_DISTRICT.value not in settled.target_drops
