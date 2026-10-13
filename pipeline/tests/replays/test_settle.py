"""Settling a SYNTHETIC day: superseding, rows that disagree, conflicts and corroboration."""

import pytest

from replays.world import DAY, World, ids, school, station, utc
from snowlight.listed.build import GUARD_REASON
from snowlight.replays.build import Settled, settle_day
from snowlight.replays.gates import Drop
from snowlight.schemas.vocab import Reason, Status

EVE = utc("2024-01-15 19:07")  # Monday evening
MID = utc("2024-01-16 00:07")  # before 04:00 on the day
MORN = utc("2024-01-16 05:26")  # the day's morning
ON = "on=2024-01-16"
S1, S2, S3 = ids("0001", 3)


def _world() -> World:
    world = World(stations=[station("gray-a"), station("gray-b", market="SYNTHETIC market two")])
    world.add_schools(school(S1), school(S2), school(S3))
    return world


def _settle(world: World) -> Settled:
    return settle_day(world.inputs(), DAY)


def test_a_dated_evening_claim_lights_the_day() -> None:
    world = _world()
    world.row("gray-a", EVE, f"closed;{ON}", direct=[S1])
    settled = _settle(world)
    assert settled.lit[S1].status is Status.CLOSED
    assert settled.lit[S1].reason is Reason.WINTER_STORM
    assert settled.lit[S1].stations == ("gray-a",)


def test_a_later_capture_that_leaves_the_school_out_voids_it() -> None:
    world = _world()
    world.row("gray-a", EVE, f"closed;{ON}", direct=[S1])
    world.row("gray-a", MORN, f"closed;{ON}", name="another", direct=[S2])
    settled = _settle(world)
    assert S1 not in settled.lit
    assert S2 in settled.lit
    assert settled.school_drops == {Drop.SUPERSEDED.value: 1}


def test_a_later_uncounted_reading_of_the_same_kind_keeps_the_claim() -> None:
    """Bare rows before 04:00 do not count, and do not void a dated claim of their kind."""
    world = _world()
    world.row("gray-a", EVE, f"remote;{ON}", direct=[S1])
    world.row("gray-a", MID, "remote", direct=[S1])
    settled = _settle(world)
    assert settled.lit[S1].status is Status.REMOTE
    assert settled.row_drops == {Drop.OUTSIDE_WINDOW.value: 1}


def test_a_later_uncounted_reading_of_another_kind_voids_the_claim() -> None:
    world = _world()
    world.row("gray-a", EVE, f"remote;{ON}", direct=[S1])
    world.row("gray-a", MID, "closed", direct=[S1])
    settled = _settle(world)
    assert S1 not in settled.lit
    assert settled.school_drops == {Drop.SUPERSEDED.value: 1}


def test_a_later_reading_of_the_same_kind_dropped_for_another_gate_voids_the_claim() -> None:
    world = _world()
    world.row("gray-a", EVE, f"closed;{ON}", direct=[S1])
    world.row("gray-a", MORN, f"closed;{ON};note=hedged", direct=[S1])
    assert S1 not in _settle(world).lit


def test_a_later_counted_claim_wins() -> None:
    world = _world()
    world.row("gray-a", EVE, f"closed;{ON}", direct=[S1])
    world.row("gray-a", MORN, f"delayed;{ON}", direct=[S1])
    assert _settle(world).lit[S1].status is Status.DELAYED


def test_a_claim_voided_then_listed_again_stands() -> None:
    world = _world()
    world.row("gray-a", utc("2024-01-15 13:00"), f"closed;{ON}", direct=[S1])
    world.row("gray-a", EVE, f"closed;{ON}", name="another", direct=[S2])
    world.row("gray-a", MORN, "closed", direct=[S1])
    settled = _settle(world)
    assert settled.lit[S1].status is Status.CLOSED
    assert S2 not in settled.lit


def test_empty_and_deferred_reads_void_nothing() -> None:
    world = _world()
    world.row("gray-a", EVE, f"closed;{ON}", direct=[S1])
    world.empty_read("gray-a", MID)
    world.empty_read("gray-a", MORN)
    assert S1 in _settle(world).lit


def test_a_populated_read_whose_rows_did_not_tie_voids() -> None:
    """A later list that holds rows nobody could read still may have dropped the school."""
    world = _world()
    world.row("gray-a", EVE, f"closed;{ON}", direct=[S1])
    world.empty_read("gray-a", MORN, rows=12)
    assert S1 not in _settle(world).lit


def test_a_later_capture_in_another_variant_that_leaves_the_school_out_voids_it() -> None:
    """A page and a feed are two forms of one station's list: the latest of either decides."""
    world = _world()
    world.row("gray-a", EVE, f"closed;{ON}", direct=[S1], variant="syn-page")
    world.row("gray-a", MORN, f"closed;{ON}", name="another", direct=[S2], variant="syn-feed")
    settled = _settle(world)
    assert set(settled.lit) == {S2}
    assert settled.school_drops == {Drop.SUPERSEDED.value: 1}


def test_a_later_uncounted_reading_of_another_kind_in_another_variant_voids() -> None:
    """The json list at 19:07 says closed; the module list at 00:07 says a bare delayed."""
    world = _world()
    world.row("gray-a", EVE, f"closed;{ON}", direct=[S1], variant="syn-json")
    world.row("gray-a", MID, "delayed", direct=[S1], variant="syn-module")
    settled = _settle(world)
    assert S1 not in settled.lit
    assert settled.school_drops == {Drop.SUPERSEDED.value: 1}


def test_a_later_uncounted_reading_of_the_same_kind_in_another_variant_keeps() -> None:
    world = _world()
    world.row("gray-a", EVE, f"remote;{ON}", direct=[S1], variant="syn-json")
    world.row("gray-a", MID, "remote", direct=[S1], variant="syn-module")
    assert _settle(world).lit[S1].status is Status.REMOTE


def test_a_later_counted_claim_in_another_variant_wins() -> None:
    world = _world()
    world.row("gray-a", EVE, f"closed;{ON}", direct=[S1], variant="syn-page")
    world.row("gray-a", MORN, f"delayed;{ON}", direct=[S1], variant="syn-feed")
    assert _settle(world).lit[S1].status is Status.DELAYED


def test_two_variants_captured_at_once_void_an_earlier_claim_as_untied_reads() -> None:
    """Two reads of one station at one second (a page and a feed): ``load_rows`` cannot tell
    their rows apart and ties none of them (``several_reads``), so they hold no rows here and
    void the station's earlier claim as reads whose rows did not tie."""
    world = _world()
    world.row("gray-a", EVE, f"closed;{ON}", direct=[S1], variant="syn-page")
    world.empty_read("gray-a", MORN, rows=40, variant="syn-page")
    world.empty_read("gray-a", MORN, rows=38, variant="syn-feed")
    settled = _settle(world)
    assert S1 not in settled.lit
    assert settled.school_drops == {Drop.SUPERSEDED.value: 1}
    assert settled.untied_voids == 1
    assert {item[0:2] for item in settled.untied} == {("gray-a", MORN)}


def test_a_school_row_that_disagrees_with_its_districts_row_drops_the_school() -> None:
    """A school row may be a wrong match (a private school of the same name): it does not win."""
    world = _world()
    world.row("gray-a", MORN, f"closed;{ON}", name="district", district=[S1, S2])
    world.row("gray-a", MORN, f"delayed;{ON}", name="school", direct=[S1])
    settled = _settle(world)
    assert S1 not in settled.lit
    assert settled.lit[S2].status is Status.CLOSED
    assert settled.school_drops == {Drop.CONFLICT_IN_LIST.value: 1}


def test_a_school_row_and_its_districts_row_that_agree_light() -> None:
    world = _world()
    world.row("gray-a", MORN, f"closed;{ON}", name="district", district=[S1, S2])
    world.row("gray-a", MORN, f"closed;{ON}", name="school", direct=[S1])
    settled = _settle(world)
    assert settled.lit[S1].status is Status.CLOSED
    assert {r.level for r in settled.lit[S1].evidence} == {"school", "district"}


def test_an_uncounted_school_row_and_a_counted_district_row_conflict() -> None:
    world = _world()
    world.row("gray-a", MORN, f"closed;{ON}", name="district", district=[S1, S2])
    world.row("gray-a", MORN, f"closed;{ON};note=partial_program", name="school", direct=[S1])
    settled = _settle(world)
    assert S1 not in settled.lit
    assert S2 in settled.lit


def test_a_conflict_in_one_list_drops_the_school() -> None:
    world = _world()
    world.row("gray-a", MORN, f"closed;{ON}", name="one", direct=[S1])
    world.row("gray-a", MORN, f"delayed;{ON}", name="two", direct=[S1])
    settled = _settle(world)
    assert S1 not in settled.lit
    assert settled.school_drops == {Drop.CONFLICT_IN_LIST.value: 1}


def test_a_counted_and_an_uncounted_row_in_one_list_conflict() -> None:
    world = _world()
    world.row("gray-a", MORN, f"closed;{ON}", name="one", direct=[S1])
    world.row("gray-a", MORN, f"delayed;{ON};conf=0.7", name="two", direct=[S1])
    settled = _settle(world)
    assert S1 not in settled.lit
    assert settled.school_drops == {Drop.CONFLICT_IN_LIST.value: 1}


@pytest.mark.parametrize(
    "other",
    [
        "closed;on=2024-01-14",  # another day's row ("All weekend activities canceled")
        "nothing",  # nothing the reader recognizes
    ],
)
def test_a_row_that_says_nothing_for_the_day_does_not_stand_in_a_claims_way(other: str) -> None:
    world = _world()
    world.row("gray-a", MORN, f"closed;{ON}", name="district", district=[S1, S2])
    world.row("gray-a", MORN, other, name="district weekend", district=[S1, S2])
    for n in range(3):  # a list mostly read, so the read gates keep it
        world.row("gray-a", MORN, f"closed;{ON}", name=f"another {n}", direct=[S3])
    settled = _settle(world)
    assert set(settled.lit) == {S1, S2, S3}
    assert settled.school_drops == {}


def test_a_row_in_the_list_that_says_open_stops_the_claim() -> None:
    world = _world()
    world.row("gray-a", MORN, f"closed;{ON}", name="district", district=[S1, S2])
    world.row("gray-a", MORN, "open", name="the school", direct=[S1])
    settled = _settle(world)
    assert set(settled.lit) == {S2}
    assert settled.school_drops == {Drop.CONFLICT_IN_LIST.value: 1}


def test_two_stations_that_agree_corroborate() -> None:
    world = _world()
    world.row("gray-a", MORN, f"closed;{ON}", direct=[S1])
    world.row("gray-b", MORN, f"closed;{ON}", direct=[S1])
    lit = _settle(world).lit[S1]
    assert lit.corroborated
    assert lit.stations == ("gray-a", "gray-b")


def test_identical_listings_at_two_stations_corroborate_the_status_not_the_match() -> None:
    world = _world()
    world.row("gray-a", MORN, f"closed;{ON}", name="Kestrel Hill School", direct=[S1])
    world.row("gray-b", MORN, f"closed;{ON}", name="KESTREL HILL  SCHOOL", direct=[S1])
    world.row("gray-a", MORN, f"closed;{ON}", name="Wrenfield R-3", district=[S2])
    world.row("gray-b", MORN, f"closed;{ON}", name="Wrenfield School District", district=[S2])
    lit = _settle(world).lit
    assert lit[S1].corroborated
    assert not lit[S1].matched_apart
    assert lit[S2].corroborated
    assert lit[S2].matched_apart


def test_two_stations_that_disagree_are_a_conflict() -> None:
    world = _world()
    world.row("gray-a", MORN, f"closed;{ON}", direct=[S1])
    world.row("gray-b", MORN, f"delayed;{ON}", direct=[S1])
    settled = _settle(world)
    assert S1 not in settled.lit
    assert settled.conflicts == (S1,)
    assert settled.school_drops == {Drop.CONFLICT.value: 1}


@pytest.mark.parametrize(
    ("status", "at"),
    [
        ("delayed", MID),  # a bare row before 04:00: outside its window
        (f"delayed;{ON};conf=0.7", MORN),  # under the confidence floor
        (f"delayed;{ON};note=hedged", MORN),  # a note off the allowlist
    ],
)
def test_another_stations_uncounted_reading_of_another_kind_is_a_conflict(
    status: str, at: str
) -> None:
    """The other list says something else for the day: it is not counted, but it is a vote."""
    world = _world()
    world.row("gray-a", EVE, f"closed;{ON}", direct=[S1])
    world.row("gray-b", at, status, direct=[S1])
    settled = _settle(world)
    assert S1 not in settled.lit
    assert settled.conflicts == (S1,)
    assert settled.school_drops[Drop.CONFLICT.value] == 1


def test_another_stations_uncounted_reading_of_the_same_kind_agrees() -> None:
    world = _world()
    world.row("gray-a", EVE, f"closed;{ON}", direct=[S1])
    world.row("gray-b", MID, "closed", direct=[S1])
    settled = _settle(world)
    assert settled.lit[S1].stations == ("gray-a",)
    assert settled.conflicts == ()


def test_another_stations_reading_the_reader_recognizes_nothing_in_is_no_vote() -> None:
    world = _world()
    world.row("gray-a", MORN, f"closed;{ON}", direct=[S1])
    world.row("gray-b", MORN, "nothing", direct=[S1])
    world.row("gray-b", MORN, "closed;on=2024-01-14", name="weekend", direct=[S1])
    assert S1 in _settle(world).lit


@pytest.mark.parametrize(
    ("status", "level"),
    [
        ("open", "school"),  # "Open", "On time", "Normal schedule"
        ("open", "district"),
        ("conflict", "school"),  # "Closed. 2 hour delay": two statuses that disagree
        ("closed;on=2024-01-16. Open on time", "school"),  # the reader misses the open comment
    ],
)
def test_another_station_that_says_open_or_disputes_drops_the_school(
    status: str, level: str
) -> None:
    """gray-b's later list says the school is open on the day: gray-a's claim does not light."""
    world = _world()
    world.row("gray-a", EVE, f"closed;{ON}", direct=[S1])
    if level == "school":
        world.row("gray-b", MORN, status, name="b", direct=[S1])
    else:
        world.row("gray-b", MORN, status, name="b", district=[S1, S2])
    settled = _settle(world)
    assert S1 not in settled.lit
    assert settled.conflicts == (S1,)
    assert settled.school_drops[Drop.CONFLICT.value] == 1


@pytest.mark.parametrize(
    "status",
    [
        f"closed;{ON};cause=Heating",  # "Closed - no heat": another cause, no non-weather word
        f"closed;{ON}. Teacher In-Service",  # a non-weather comment
        f"closed;{ON}. NTI Day",  # a learning comment beside a closed reading
        f"closed;{ON};Snow Packet Day",  # a learning word in the status itself
        "revoked",  # "Closure rescinded": no entry, note revoked
        "negated",  # "Not closed", "No delay"
        "partial",  # "Closed. Lincoln Elementary open."
        "ambiguous",  # "Closed - CANCELED" at 0.3
        f"closed;{ON};note=superseded",
    ],
)
def test_another_stations_reading_that_takes_back_or_recauses_the_status_drops_the_school(
    status: str,
) -> None:
    """gray-b's latest list says the closing is called off, narrowed, or not for the weather."""
    world = _world()
    world.row("gray-a", EVE, f"closed;{ON}", direct=[S1])
    world.row("gray-b", MORN, status, name="b", direct=[S1])
    settled = _settle(world)
    assert S1 not in settled.lit
    assert settled.conflicts == (S1,)
    assert settled.school_drops[Drop.CONFLICT.value] == 1


def test_another_stations_reading_about_another_day_does_not_dissent() -> None:
    """gray-b's latest list takes back Friday's closing ("Closed on Friday 1/19", superseded)."""
    world = _world()
    world.row("gray-a", EVE, f"closed;{ON}", direct=[S1])
    world.row(
        "gray-b", MORN, "closed;on=2024-01-19;note=superseded Friday 1/19", name="b", direct=[S1]
    )
    settled = _settle(world)
    assert settled.lit[S1].stations == ("gray-a",)
    assert settled.conflicts == ()


def test_an_earlier_retraction_at_another_station_drops_a_later_claim() -> None:
    world = _world()
    world.row("gray-b", MORN, "revoked", direct=[S1])
    world.row("gray-a", utc("2024-01-16 06:40"), f"delayed;{ON}", direct=[S1])
    assert S1 not in _settle(world).lit


@pytest.mark.parametrize("status", ["negated", "revoked", "partial"])
def test_a_schools_own_row_that_takes_back_its_districts_status_drops_it_in_the_list(
    status: str,
) -> None:
    """A district's "2 hour delay" beside the school's own "No delay": the school stays dark."""
    world = _world()
    world.row("gray-a", MORN, f"delayed;{ON}", name="district", district=[S1, S2])
    world.row("gray-a", MORN, status, name="the school", direct=[S1])
    settled = _settle(world)
    assert set(settled.lit) == {S2}
    assert settled.school_drops == {Drop.CONFLICT_IN_LIST.value: 1}


@pytest.mark.parametrize(
    "status",
    [
        f"closed;{ON};conf=0.7",  # under the confidence floor
        f"closed;{ON};note=hedged",
        f"closed;{ON};note=activities_cancelled",
    ],
)
def test_another_stations_uncounted_reading_that_names_the_same_status_does_not_dissent(
    status: str,
) -> None:
    """Low confidence, a hedge or another note is no counted claim, but it names the same status."""
    world = _world()
    world.row("gray-a", EVE, f"closed;{ON}", direct=[S1])
    world.row("gray-b", MORN, status, direct=[S1])
    settled = _settle(world)
    assert settled.lit[S1].stations == ("gray-a",)
    assert settled.conflicts == ()


def test_the_same_station_saying_open_later_voids_its_claim() -> None:
    world = _world()
    world.row("gray-a", EVE, f"closed;{ON}", direct=[S1])
    world.row("gray-a", MORN, "open", direct=[S1])
    settled = _settle(world)
    assert S1 not in settled.lit
    assert settled.school_drops == {Drop.SUPERSEDED.value: 1}


def test_a_station_that_said_open_before_its_own_later_claim_votes_the_claim() -> None:
    world = _world()
    world.row("gray-a", MORN, f"closed;{ON}", direct=[S1])
    world.row("gray-b", EVE, "open", direct=[S1])
    world.row("gray-b", MORN, f"closed;{ON}", direct=[S1])
    assert _settle(world).lit[S1].stations == ("gray-a", "gray-b")


def test_only_a_stations_latest_listing_votes() -> None:
    """gray-b said delayed in the evening and closed in the morning: its vote is closed."""
    world = _world()
    world.row("gray-a", MORN, f"closed;{ON}", direct=[S1])
    world.row("gray-b", EVE, f"delayed;{ON};conf=0.7", direct=[S1])
    world.row("gray-b", MORN, f"closed;{ON}", direct=[S1])
    assert _settle(world).lit[S1].stations == ("gray-a", "gray-b")


def test_a_station_that_withdrew_the_school_stops_anothers_claim() -> None:
    world = _world()
    world.row("gray-a", EVE, f"closed;{ON}", direct=[S1])
    world.row("gray-a", MORN, f"closed;{ON}", name="another", direct=[S2])
    world.row("gray-b", EVE, f"closed;{ON}", direct=[S1])
    settled = _settle(world)
    assert S1 not in settled.lit
    assert settled.school_drops == {Drop.SUPERSEDED.value: 1, Drop.WITHDRAWN.value: 1}


def test_a_station_whose_list_contradicts_itself_stops_anothers_claim() -> None:
    world = _world()
    world.row("gray-a", MORN, f"closed;{ON}", name="x", direct=[S1])
    world.row("gray-a", MORN, f"closed;{ON};note=hedged", name="y", direct=[S1])
    world.row("gray-b", MORN, f"closed;{ON}", direct=[S1])
    settled = _settle(world)
    assert S1 not in settled.lit
    assert settled.school_drops == {Drop.CONFLICT_IN_LIST.value: 1, Drop.WITHDRAWN.value: 1}


def test_a_void_by_a_read_whose_rows_did_not_tie_is_counted() -> None:
    world = _world()
    world.row("gray-a", EVE, f"closed;{ON}", direct=[S1])
    world.empty_read("gray-a", MORN, rows=12)
    settled = _settle(world)
    assert settled.untied_voids == 1
    assert settled.untied == (("gray-a", MORN, 12),)


def test_reasons_that_disagree_become_null() -> None:
    world = _world()
    world.row("gray-a", MORN, f"closed;{ON};reason=Ice", direct=[S1])
    world.row("gray-b", MORN, f"closed;{ON}", direct=[S1])
    world.row("gray-a", MORN, f"closed;{ON};reason=Ice", name="two", direct=[S2])
    world.row("gray-a", MORN, f"closed;{ON}", name="three", direct=[S2])
    settled = _settle(world)
    assert settled.lit[S1].reason is None
    assert settled.lit[S2].reason is None


def test_reasons_that_agree_stay() -> None:
    world = _world()
    world.row("gray-a", MORN, f"closed;{ON};reason=Ice", direct=[S1])
    world.row("gray-b", MORN, f"closed;{ON};reason=Ice", direct=[S1])
    assert _settle(world).lit[S1].reason is Reason.ICE


def test_a_capture_outside_the_schools_window_is_not_read() -> None:
    world = _world()
    world.row("gray-a", MORN, f"closed;{ON}", direct=[S1])
    world.row("gray-a", utc("2024-01-16 12:30"), "nothing", name="other", direct=[S2])
    assert S1 in _settle(world).lit


# --- a match by name alone: a public school named only by a listing's name --------------------

K1, K2 = ids("0031", 2)
"""SYNTHETIC: public Kestrel Hill Elementary (K1) and another school (K2) of one district."""


def _kestrel(**k1: object) -> World:
    world = World(stations=[station("gray-a"), station("gray-b", market="SYNTHETIC market two")])
    fields: dict[str, object] = {
        "name": "Kestrel Hill Elementary",
        "level": "Elementary",
        "district": "9900031",
    }
    fields.update(k1)
    world.add_schools(
        school(K1, **fields),  # type: ignore[arg-type]
        school(K2, district="9900031", name="Wrenfield Middle", level="Middle"),
    )
    return world


def test_a_school_named_by_its_name_alone_without_its_district_stays_dark() -> None:
    """A private "Kestrel Hill School" with no section, no place and no district row beside it."""
    world = _kestrel()
    world.row(
        "gray-a", MORN, f"delayed;{ON}", name="Kestrel Hill School", reason="name", direct=[K1]
    )
    settled = _settle(world)
    assert settled.lit == {}
    assert settled.school_drops == {Drop.UNANCHORED.value: 1}


@pytest.mark.parametrize(
    ("name", "placed", "k1", "lit"),
    [
        ("Kestrel Hill School", True, {}, True),  # its list places it by the record
        ("Kestrel Hill Elementary", False, {}, True),  # the record's level word
        ("Kestrel Hill Elem. School", False, {}, True),
        ("Kestrel Hill High School", False, {}, False),  # another level's word
        ("Kestrel Hill School", False, {"district": "9900099"}, True),  # its district's only one
        ("Kestrel Hill School", False, {"public": False}, True),  # a private record
        ("Kestrel Hill School", False, {}, False),
    ],
)
def test_what_anchors_a_match_by_name_alone(
    name: str, placed: bool, k1: dict[str, object], lit: bool
) -> None:
    world = _kestrel(**k1)
    world.row("gray-a", MORN, f"closed;{ON}", name=name, reason="name", placed=placed, direct=[K1])
    assert (K1 in _settle(world).lit) is lit


def test_a_match_by_name_alone_lights_beside_its_districts_agreeing_row() -> None:
    world = _kestrel()
    world.row(
        "gray-a", MORN, f"closed;{ON}", name="Kestrel Hill School", reason="name", direct=[K1]
    )
    world.row("gray-a", MORN, f"closed;{ON}", name="Wrenfield R-3", district=[K1, K2])
    settled = _settle(world)
    assert set(settled.lit) == {K1, K2}
    assert {r.level for r in settled.lit[K1].evidence} == {"school", "district"}


def test_a_match_by_name_alone_at_another_station_withdraws_nothing() -> None:
    """gray-b's unanchored row agrees: it neither lights the school nor stops gray-a's claim."""
    world = _kestrel()
    world.row("gray-a", MORN, f"closed;{ON}", name="Wrenfield R-3", district=[K1, K2])
    world.row(
        "gray-b", MORN, f"closed;{ON}", name="Kestrel Hill School", reason="name", direct=[K1]
    )
    settled = _settle(world)
    assert settled.lit[K1].stations == ("gray-a",)
    assert settled.school_drops == {Drop.UNANCHORED.value: 1}


def test_a_match_by_name_alone_that_disagrees_still_votes() -> None:
    world = _kestrel()
    world.row("gray-a", MORN, f"closed;{ON}", name="Wrenfield R-3", district=[K1, K2])
    world.row(
        "gray-b", MORN, f"delayed;{ON}", name="Kestrel Hill School", reason="name", direct=[K1]
    )
    settled = _settle(world)
    assert K1 not in settled.lit
    assert settled.conflicts == (K1,)


def test_a_place_guard_at_one_station_carries_to_the_same_name_in_its_market() -> None:
    """gray-b's list places "Kestrel Hill School" in another town; gray-a's same listing, with no
    place of its own, is the same organization and is not accepted either."""
    world = _kestrel()
    world.stations[1]["market"] = "SYNTHETIC market one"
    world.row(
        "gray-b",
        MORN,
        f"delayed;{ON}",
        name="The Kestrel Hill School",
        accepted=False,
        reason=GUARD_REASON,
        targets=[K1],
    )
    world.row(
        "gray-a", MORN, f"delayed;{ON}", name="KESTREL HILL SCHOOL", reason="context", direct=[K1]
    )
    settled = _settle(world)
    assert settled.lit == {}
    assert settled.row_drops == {Drop.PLACE_GUARD.value: 2}


def test_a_place_guard_carries_to_the_same_name_in_the_same_list() -> None:
    """gray-a places "Kestrel Hill School" elsewhere under one section; its row of the same
    name under no section is the same organization."""
    world = _kestrel()
    world.row(
        "gray-a",
        MORN,
        f"delayed;{ON}",
        name="Kestrel Hill School",
        section="Elsewhere County",
        accepted=False,
        reason=GUARD_REASON,
        targets=[K1],
    )
    world.row(
        "gray-a", MORN, f"delayed;{ON}", name="KESTREL HILL SCHOOL", reason="context", direct=[K1]
    )
    settled = _settle(world)
    assert settled.lit == {}
    assert settled.row_drops == {Drop.PLACE_GUARD.value: 2}


def test_a_place_guard_does_not_carry_to_another_market() -> None:
    world = _kestrel()
    world.stations[1]["counties"] = {"basis": "dma", "source": "SYNTHETIC", "fips": ["08001"]}
    world.row(
        "gray-b",
        MORN,
        f"delayed;{ON}",
        name="Kestrel Hill School",
        accepted=False,
        reason=GUARD_REASON,
        targets=[K1],
    )
    world.row(
        "gray-a", MORN, f"delayed;{ON}", name="Kestrel Hill School", reason="context", direct=[K1]
    )
    assert _settle(world).lit[K1].status is Status.DELAYED


def test_a_place_guard_does_not_carry_to_a_listing_its_own_list_places_by_the_record() -> None:
    """One name, two organizations in a market: gray-a's own list places its row by the record."""
    world = _kestrel()
    world.stations[1]["market"] = "SYNTHETIC market one"
    world.row(
        "gray-b",
        MORN,
        f"delayed;{ON}",
        name="Kestrel Hill School",
        accepted=False,
        reason=GUARD_REASON,
        targets=[K1],
    )
    world.row(
        "gray-a",
        MORN,
        f"delayed;{ON}",
        name="Kestrel Hill School",
        reason="context",
        placed=True,
        direct=[K1],
    )
    assert _settle(world).lit[K1].status is Status.DELAYED


def test_a_place_guard_does_not_carry_from_a_list_that_also_places_the_name_by_the_record() -> None:
    """gray-b lists one name in two places, one of them by the record: the name is two
    organizations there, and gray-a's match stands."""
    world = _kestrel()
    world.stations[1]["market"] = "SYNTHETIC market one"
    world.row(
        "gray-b",
        MORN,
        f"delayed;{ON}",
        name="Kestrel Hill School",
        accepted=False,
        reason=GUARD_REASON,
        placed=True,
        targets=[K1],
    )
    world.row(
        "gray-a", MORN, f"delayed;{ON}", name="KESTREL HILL SCHOOL", reason="context", direct=[K1]
    )
    assert _settle(world).lit[K1].status is Status.DELAYED


@pytest.mark.parametrize(
    ("status", "comment"),
    [
        ("open", "No AM preschool"),  # "Open; no AM preschool"
        ("open", "north campus closed"),  # "Open - north campus closed"
        (f"delayed;{ON}", "No AM Preschool"),  # "2 Hour Delay; No AM Preschool"
        (f"delayed;{ON}", "JHS"),  # "2 hr delay - JHS"
        (f"closed;{ON}", "K-8 closed"),
        (f"closed;{ON}", "Lincoln Elem only"),
        (f"closed;{ON}", "Closed at Lincoln School"),
        ("revoked", "Lincoln Elementary"),  # a status taken back for one school
    ],
)
def test_another_stations_district_row_that_names_part_of_the_district_drops_the_claim(
    status: str, comment: str
) -> None:
    """gray-b's latest list narrows the district's status to part of it, or says it is open:
    gray-a's whole-district claim lights none of its schools."""
    world = _world()
    world.row("gray-a", EVE, f"closed;{ON}", name="district", district=[S1, S2])
    world.row("gray-b", MORN, status, name="district", district=[S1, S2], comment=comment)
    settled = _settle(world)
    assert settled.lit == {}
    assert settled.conflicts == (S1, S2)
    assert settled.school_drops[Drop.CONFLICT.value] == 2
    assert settled.target_drops[Drop.PART_OF_DISTRICT.value] == 2


@pytest.mark.parametrize(
    ("status", "comment"),
    [(f"delayed;{ON}", "JHS"), (f"closed;{ON}", "K-8 closed"), ("open", "No AM preschool")],
)
def test_a_district_row_that_names_part_of_the_district_drops_the_claim_in_its_list(
    status: str, comment: str
) -> None:
    world = _world()
    world.row("gray-a", MORN, f"closed;{ON}", name="district", district=[S1, S2])
    world.row("gray-a", MORN, status, name="district part", district=[S1, S2], comment=comment)
    settled = _settle(world)
    assert settled.lit == {}
    assert settled.school_drops == {Drop.CONFLICT_IN_LIST.value: 2}


def test_a_district_row_that_names_part_of_the_district_for_another_day_says_nothing() -> None:
    """ "Lincoln Elementary closed Friday 1/19": it is about Friday."""
    world = _world()
    world.row("gray-a", EVE, f"closed;{ON}", name="district", district=[S1, S2])
    world.row(
        "gray-b",
        MORN,
        "closed;on=2024-01-19",
        name="district",
        district=[S1, S2],
        comment="Lincoln Elementary",
    )
    settled = _settle(world)
    assert set(settled.lit) == {S1, S2}
    assert settled.conflicts == ()


def test_another_stations_retraction_that_names_the_day_and_schedules_another_drops_it() -> None:
    """gray-b: "Tuesday's closure has been rescinded; closed Wednesday"."""
    world = _world()
    world.row("gray-a", EVE, f"closed;{ON}", direct=[S1])
    world.row(
        "gray-b",
        MORN,
        "closed;on=2024-01-17;note=revoked",
        name="b",
        direct=[S1],
        comment="Tuesday closure rescinded",
    )
    settled = _settle(world)
    assert S1 not in settled.lit
    assert settled.conflicts == (S1,)


def test_another_stations_listing_whose_name_is_not_weather_drops_the_claim() -> None:
    """gray-b lists the school as "Kestrel Teacher Institute Day": its name votes."""
    world = _world()
    world.row("gray-a", EVE, f"closed;{ON}", direct=[S1])
    world.row("gray-b", MORN, f"closed;{ON}", name="Kestrel Teacher Institute Day", direct=[S1])
    settled = _settle(world)
    assert S1 not in settled.lit
    assert settled.conflicts == (S1,)


def test_a_part_row_that_states_no_status_and_names_only_another_day_says_nothing() -> None:
    """ "Closed on Monday 1/15" above a long note about the middle schools, read for Tuesday."""
    world = _world()
    world.row("gray-a", EVE, f"closed;{ON}", name="district", district=[S1, S2])
    world.row(
        "gray-b",
        MORN,
        "ambiguous",
        name="district",
        district=[S1, S2],
        comment="Closed on Monday 1/15; middle school activities canceled",
    )
    settled = _settle(world)
    assert set(settled.lit) == {S1, S2}
    assert settled.conflicts == ()


# --- a retraction's own words decide the day it takes back -----------------------------------


@pytest.mark.parametrize(
    ("at", "comment"),
    [
        # its own phrase names no day, though another names one
        (MORN, "Closing rescinded. Make-up day will be Friday"),
        (MORN, "Closing rescinded - make up day Feb 19"),
        (MORN, "Closing cancelled - buses will run Wednesday"),
        (MORN, "Disregard closing - closed Wednesday only"),
        (MORN, "Closure rescinded; school in session. Wednesday 2 hr delay"),
        (MORN, "Delay cancelled. Early dismissal Friday"),
        (MORN, "Closure rescinded - closed 1/17"),
        # it names the day by an ordinal, a list or a relative word
        (MORN, "Closings for Jan 15th-17th have been rescinded"),
        (MORN, "Closings for January 15 & 16 cancelled"),
        (MORN, "Closure for Jan 15th - 17th rescinded"),
        (MORN, "Delays Jan 15 and 16 are cancelled"),
        (MORN, "Closures 1/15 & 16 rescinded"),
        (MORN, "Today's closure has been rescinded; closed tomorrow"),
        (MORN, "Closing for today cancelled. Closed tomorrow"),
        (MORN, "Delay rescinded for today; 2 hour delay tomorrow"),
        (utc("2024-01-15 20:00"), "Tomorrow's closing cancelled - closed Wednesday instead"),
    ],
)
def test_another_stations_retraction_drops_the_claim_unless_it_names_other_days_only(
    at: str, comment: str
) -> None:
    """gray-b's latest list takes a closing back ("rv": the note revoked, no status): gray-a's
    claim for the day drops, whatever other days the list also names."""
    world = _world()
    world.row("gray-a", EVE, f"closed;{ON}", direct=[S1])
    world.row("gray-b", at, "rv", name="b", direct=[S1], comment=comment)
    settled = _settle(world)
    assert S1 not in settled.lit
    assert settled.conflicts == (S1,)


@pytest.mark.parametrize(
    "comment", ["Monday's closing rescinded", "Closings for Jan 17th & 18th cancelled"]
)
def test_another_stations_retraction_of_other_days_only_says_nothing(comment: str) -> None:
    world = _world()
    world.row("gray-a", EVE, f"closed;{ON}", direct=[S1])
    world.row("gray-b", MORN, "rv", name="b", direct=[S1], comment=comment)
    settled = _settle(world)
    assert settled.lit[S1].stations == ("gray-a",)
    assert settled.conflicts == ()


@pytest.mark.parametrize(
    "status", ["closed;note=ss Monday", "closed;note=rv Monday", "closed;note=ambiguous Monday"]
)
def test_an_undated_reading_for_the_day_with_a_dissent_note_drops_the_claim(status: str) -> None:
    """gray-b's undated "Closed" carries a note that takes it back or doubts it: its entry is
    for the day, though its words name only Monday."""
    world = _world()
    world.row("gray-a", EVE, f"closed;{ON}", direct=[S1])
    world.row("gray-b", MORN, status, name="b", direct=[S1])
    settled = _settle(world)
    assert S1 not in settled.lit
    assert settled.conflicts == (S1,)


@pytest.mark.parametrize(
    "comment",
    [
        "Snow Packet Days Jan 15th-17th",
        "Snow Packet Days January 15 & 16",
        "Snow Packet Days 1/15 & 16",
        "No bus-eDay",
    ],
)
def test_a_learning_day_named_by_ordinals_or_lists_never_lights_closed(comment: str) -> None:
    world = _world()
    world.row("gray-a", MORN, f"closed;{ON}", direct=[S1], comment=comment)
    world.row("gray-b", MORN, f"closed;{ON}", name="b", direct=[S1])
    settled = _settle(world)
    assert S1 not in settled.lit
    assert settled.conflicts == (S1,)


@pytest.mark.parametrize(
    ("status", "comment"),
    [
        ("rv", "Lincoln campus Closings for Jan 15th-17th rescinded"),
        ("rv", "Lincoln campus Delays Jan 15 and 16 are cancelled"),
        ("nothing", "Lincoln campus"),
    ],
)
def test_a_part_row_that_takes_back_or_states_nothing_drops_another_stations_claim(
    status: str, comment: str
) -> None:
    """A district row naming a campus: it takes the closing back over a span that holds the day,
    or the reader recognizes nothing in it (a status it may hold for the day)."""
    world = _world()
    world.row("gray-a", EVE, f"closed;{ON}", name="district", district=[S1, S2])
    world.row("gray-b", MORN, status, name="district", district=[S1, S2], comment=comment)
    for n in range(4):  # the read stays readable
        world.row("gray-b", MORN, f"closed;{ON}", name=f"other {n}", direct=[S3])
    settled = _settle(world)
    assert set(settled.lit) == {S3}
    assert settled.conflicts == (S1, S2)


def test_a_part_row_that_finds_a_conflict_about_another_day_drops_the_claim() -> None:
    """The reader finds two statuses that disagree: it may have dated either one wrongly."""
    world = _world()
    world.row("gray-a", EVE, f"closed;{ON}", name="district", district=[S1, S2])
    world.row(
        "gray-b",
        MORN,
        "conflict",
        name="district",
        district=[S1, S2],
        comment="Lincoln Elementary closed Friday 1/19",
    )
    settled = _settle(world)
    assert settled.lit == {}
