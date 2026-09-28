"""Behaviour of Matcher.match beyond the labelled cases: aliases, scope, ties, results."""

import pytest

from match import handmade
from snowlight.match import (
    Aliases,
    Directory,
    DirectoryRecord,
    Level,
    Matcher,
    MatchSettings,
    Reason,
    lexicon,
)
from snowlight.match.index import (
    BARE_NAME_SCHOOL,
    CELL_DEGREES,
    CODE_ONLY,
    COUNTY_LEFT_OUT_NUMBERED,
    LEVEL_NAMED_DISTRICT,
    LEVEL_ONLY_CANDIDATE,
    NUMBER_ONLY_CANDIDATE,
    PLACE_LEFT_OUT,
    PLACE_NOT_A_SCHOOL,
    PLACE_WORD_NOT_SAID,
    PLURAL_DIFFERS,
    PUBLIC_SCHOOL_DISTRICT,
    PUBLIC_SCHOOL_OTHER,
    SECOND_NAME,
    TOWN_LEFT_OUT,
    WRONG_KIND,
    CountyGrid,
    Reach,
    Scope,
    Scored,
    Town,
    city_key,
    haversine_km,
    kind_factor,
    place_keys,
)
from snowlight.match.matcher import MIN_THRESHOLD
from snowlight.match.normalize import listing_forms, record_form


def _ids(records: tuple[DirectoryRecord, ...]) -> list[str]:
    return [record.id for record in records]


# -- aliases ------------------------------------------------------------------------


def test_an_alias_wins_over_the_name(handmade_directory: Directory) -> None:
    aliases = Aliases({"wxyz": {"lancaster schools": "SYN-PA-LANCO"}})
    matcher = Matcher(handmade_directory, aliases=aliases)
    pinned = matcher.match("Lancaster  SCHOOLS", states=["PA"], market="wxyz")
    assert pinned.reason is Reason.ALIAS
    assert pinned.target is not None
    assert pinned.target.id == "SYN-PA-LANCO"
    assert pinned.confidence == 1.0
    assert pinned.best is not None
    assert pinned.best.record.id == "SYN-PA-LANCO"
    # Without the market, or in another one, the name decides.
    for market in (None, "other"):
        named = matcher.match("Lancaster Schools", states=["PA"], market=market)
        assert named.reason is Reason.NAME
        assert named.target is not None
        assert named.target.id == "SYN-PA-LANSD"


def test_an_alias_wins_even_outside_the_states(handmade_directory: Directory) -> None:
    aliases = Aliases({"wxyz": {"fcps": "SYN-VA-FAIR"}})
    result = Matcher(handmade_directory, aliases=aliases).match(
        "FCPS", states=["MD"], market="wxyz", near=(38.8, -77.3)
    )
    assert result.reason is Reason.ALIAS
    assert result.target is not None
    assert result.target.id == "SYN-VA-FAIR"
    assert result.best is not None
    assert result.best.distance_km == pytest.approx(0.0, abs=0.01)


def test_an_alias_to_an_unknown_id_is_not_a_match(handmade_directory: Directory) -> None:
    aliases = Aliases({"wxyz": {"lancaster schools": "SYN-GONE"}})
    result = Matcher(handmade_directory, aliases=aliases).match(
        "Lancaster Schools", states=["PA"], market="wxyz"
    )
    assert result.reason is Reason.ALIAS_UNKNOWN
    assert result.target is None
    assert not result.accepted
    assert "SYN-GONE" in result.detail


# -- scope --------------------------------------------------------------------------


def test_candidates_stay_in_the_listing_states(handmade_matcher: Matcher) -> None:
    result = handmade_matcher.match("Harwick County Public Schools", states=["MD"])
    assert result.target is not None
    assert result.target.state == "MD"
    assert all(c.record.state == "MD" for c in result.runners_up)
    nothing = handmade_matcher.match("Harwick County Public Schools", states=["WY"])
    assert nothing.reason is Reason.NO_CANDIDATE
    assert nothing.best is None
    assert nothing.confidence == 0.0


def test_a_district_counts_in_every_county_its_schools_are_in() -> None:
    directory = Directory(
        [
            DirectoryRecord("SYN-D1", "Tollgate SD", "district", None, "PA", "80101", "T", 40, -76),
            DirectoryRecord(
                "SYN-S1", "Tollgate HS", "school", "SYN-D1", "PA", "80102", "T", 40, -76
            ),
        ]
    )
    matcher = Matcher(directory)
    for county in ("80101", "80102"):
        result = matcher.match("Tollgate Schools", states=["PA"], counties=[county])
        assert result.target is not None
        assert result.target.id == "SYN-D1"
    outside = matcher.match("Tollgate Schools", states=["PA"], counties=["80103"])
    assert outside.target is None
    assert outside.reason is Reason.NO_CANDIDATE


def test_states_and_counties_are_checked(handmade_matcher: Matcher) -> None:
    with pytest.raises(ValueError, match="at least one state"):
        handmade_matcher.match("Lancaster SD", states=[])
    with pytest.raises(TypeError, match="not one string"):
        handmade_matcher.match("Lancaster SD", states="PA")
    with pytest.raises(ValueError, match="not USPS state codes"):
        handmade_matcher.match("Lancaster SD", states=["Penn"])
    with pytest.raises(TypeError, match="not one string"):
        handmade_matcher.match("Lancaster SD", states=["PA"], counties="80101")
    with pytest.raises(ValueError, match="5-digit"):
        handmade_matcher.match("Lancaster SD", states=["PA"], counties=["801"])
    with pytest.raises(ValueError, match="5-digit"):
        handmade_matcher.match("Lancaster SD", states=["PA"], counties=[])
    with pytest.raises(ValueError, match="near"):
        handmade_matcher.match("Lancaster SD", states=["PA"], near=(140.0, 0.0))
    lower = handmade_matcher.match("Lancaster SD", states=[" pa "])
    assert lower.states == ("PA",)
    assert lower.target is not None


# -- ties and distance ---------------------------------------------------------------


def test_near_breaks_a_tie_and_says_so(handmade_matcher: Matcher) -> None:
    """Two ``"ST CECILIA SCHOOL"`` of one state 134 km apart: a point beside one tells."""
    result = handmade_matcher.match(
        "St. Cecilia School", states=["MA", "NH"], near=handmade.HARBOURNE
    )
    assert result.reason is Reason.NEAREST
    assert result.target is not None
    assert result.target.id == "SYN-MA-SCHA"
    assert "nearest of 2" in result.detail
    assert "the rest beyond 80 km" in result.detail
    assert result.best is not None
    assert result.best.distance_km is not None
    assert result.best.distance_km < 5
    tied = [c for c in result.runners_up if c.record.id == "SYN-MA-SCPT"]
    assert tied
    assert tied[0].distance_km is not None
    assert tied[0].distance_km > MatchSettings().reach_km


def test_a_point_says_nothing_of_namesakes_in_the_market_s_counties(
    handmade_matcher: Matcher,
) -> None:
    """A Boston-like list whose counties hold two ``"ST JOHN SCHOOL"`` 17 km apart.

    The market's point lies 1 km from one of them; that says nothing of which
    one the list means, and the listing goes to the queue with both.
    """
    for category in ("Schools", None):
        result = handmade_matcher.match(
            "St. John School",
            states=["MA", "NH"],
            counties=handmade.HARBOURNE_COUNTIES,
            near=handmade.HARBOURNE,
            category=category,
        )
        assert result.target is None, (category, result.detail)
        assert result.reason is Reason.AMBIGUOUS, (category, result.reason)
        assert "nearest" not in result.detail
        ranked = [c for c in (result.best, *result.runners_up) if c is not None]
        assert {c.record.id for c in ranked[:2]} == {"SYN-MA-SJHA", "SYN-MA-SJWM"}
        distances = sorted(c.distance_km or 0.0 for c in ranked[:2])
        assert distances[0] < 1
        assert 15 < distances[1] < MatchSettings().reach_km
    # Read in the whole states, the other lies within a market's reach of the point.
    statewide = handmade_matcher.match(
        "St. John School", states=["MA", "NH"], near=handmade.HARBOURNE
    )
    assert statewide.target is None
    assert statewide.reason is Reason.AMBIGUOUS
    # A county of the market's that holds only one: the other lies outside it,
    # and the point beside this one tells them apart.
    one = handmade_matcher.match(
        "St. John School",
        states=["MA", "NH"],
        counties=[handmade.HARBOURNE_CO],
        near=handmade.HARBOURNE,
    )
    assert one.target is not None
    assert one.target.id == "SYN-MA-SJHA"
    assert one.reason is Reason.NEAREST
    assert "the rest outside the counties" in one.detail


def test_three_districts_schools_of_one_name_in_the_market(handmade_matcher: Matcher) -> None:
    """A Chicago-like list: three districts in its counties run a ``"WALSH ELEM SCHOOL"``."""
    for near in (handmade.LAKEPORT, None):
        result = handmade_matcher.match(
            "Walsh Elementary School",
            states=["IL", "IN"],
            counties=handmade.LAKEPORT_COUNTIES,
            near=near,
        )
        assert result.target is None, (near, result.detail)
        assert result.reason is Reason.AMBIGUOUS
        ranked = {c.record.id for c in (result.best, *result.runners_up) if c is not None}
        assert {"SYN-IL-LKWA", "SYN-IL-ORWA", "SYN-IL-DWWA"} <= ranked
    # Its district or its town said beside it names one of them.
    context = handmade_matcher.match(
        "Lakeport SD 299 - Walsh Elementary",
        states=["IL", "IN"],
        counties=handmade.LAKEPORT_COUNTIES,
        near=handmade.LAKEPORT,
    )
    assert context.target is not None
    assert context.target.id == "SYN-IL-LKWA"
    assert context.reason is Reason.CONTEXT


def test_a_point_breaks_a_tie_only_with_the_rest_beyond_reach(
    handmade_matcher: Matcher, handmade_directory: Directory
) -> None:
    """Two ``St. Mary's`` 30 km apart: within a market's reach, a point says nothing.

    :attr:`MatchSettings.reach_km` decides: with a reach shorter than the
    distance between them, the point beside one tells them apart.
    """
    listing, point = "St. Mary's School", (40.03, -76.31)
    result = handmade_matcher.match(listing, states=["PA"], near=point)
    assert result.target is None
    assert result.reason is Reason.AMBIGUOUS
    short = Matcher(handmade_directory, settings=MatchSettings(reach_km=25.0))
    nearest = short.match(listing, states=["PA"], near=point)
    assert nearest.target is not None
    assert nearest.target.id == "SYN-PA-STMA"
    assert nearest.reason is Reason.NEAREST
    assert "the rest beyond 25 km" in nearest.detail


def test_near_does_not_move_an_untied_match(handmade_matcher: Matcher) -> None:
    far = handmade_matcher.match("Lancaster County Schools", states=["PA"], near=(40.0, -76.3))
    assert far.reason is Reason.NAME
    assert far.target is not None
    assert far.target.id == "SYN-PA-LANCO"


def test_a_tie_too_far_away_stays_a_tie(handmade_matcher: Matcher) -> None:
    result = handmade_matcher.match("St. Mary's School", states=["PA"], near=(41.9, -76.3))
    assert result.reason is Reason.AMBIGUOUS
    assert result.target is None
    assert result.best is not None
    assert result.best.score == 1.0


def test_distance_to_a_district_without_coordinates_uses_its_schools() -> None:
    directory = Directory(
        [
            DirectoryRecord(
                "SYN-D1", "Tollgate SD", "district", None, "PA", None, None, None, None
            ),
            DirectoryRecord("SYN-S1", "Tollgate HS", "school", "SYN-D1", "PA", None, "T", 40, -76),
            DirectoryRecord("SYN-S2", "Tollgate MS", "school", "SYN-D1", "PA", None, "T", 41, -76),
            DirectoryRecord(
                "SYN-D2", "Tollgate Area SD", "district", None, "PA", None, None, None, None
            ),
        ]
    )
    result = Matcher(directory).match("Tollgate School District", states=["PA"], near=(40.5, -76))
    assert result.best is not None
    assert result.best.record.id == "SYN-D1"
    assert result.best.distance_km == pytest.approx(0.0, abs=0.01)
    lonely = [c for c in result.runners_up if c.record.id == "SYN-D2"]
    assert lonely
    assert lonely[0].distance_km is None


# -- namesakes across a state line ---------------------------------------------------


def test_names_that_tie_across_states_go_to_the_queue(handmade_matcher: Matcher) -> None:
    """Missouri's "KESSBY CITY 33" and Kansas's "Kessby City", as Kansas City's two districts."""
    result = handmade_matcher.match("Kessby City Public Schools", states=handmade.MO_KS)
    assert result.reason is Reason.AMBIGUOUS
    assert result.targets == ()
    assert result.confidence < MatchSettings().threshold
    ranked = [c.record.id for c in (result.best, *result.runners_up) if c is not None]
    assert set(ranked[:2]) == {"SYN-MO-KESS", "SYN-KS-KESS"}
    assert "tie by name across KS, MO" in result.detail
    assert "no point near the market" in result.detail
    between = handmade_matcher.match(
        "Kessby City Public Schools", states=handmade.MO_KS, near=handmade.BETWEEN_KESSBY
    )
    assert between.reason is Reason.AMBIGUOUS
    assert "not much nearer one of them" in between.detail


def test_a_point_much_nearer_one_state_s_namesake_breaks_the_tie(
    handmade_matcher: Matcher, handmade_directory: Directory
) -> None:
    """Escambry's two county districts lie 74 km apart, within a market's reach of each other.

    A point beside one says nothing of which one a list of both states means;
    with a reach shorter than that, it tells them apart.
    """
    states = ("FL", "AL")
    short = Matcher(handmade_directory, settings=MatchSettings(reach_km=60.0))
    for point, expected in (
        (handmade.ESCAMBRY_FL, "SYN-FL-ESCA"),
        (handmade.ESCAMBRY_AL, "SYN-AL-ESCA"),
    ):
        within = handmade_matcher.match("Escambry County Schools", states=states, near=point)
        assert within.reason is Reason.AMBIGUOUS
        assert within.targets == ()
        result = short.match("Escambry County Schools", states=states, near=point)
        assert result.reason is Reason.NEAREST
        assert _ids(result.targets) == [expected]
    # Named without "County", Florida's name fits better; a point at it lets it
    # stand, a point at Alabama's leaves the listing to the queue.
    home = short.match("Escambry Schools", states=states, near=handmade.ESCAMBRY_FL)
    assert _ids(home.targets) == ["SYN-FL-ESCA"]
    away = short.match("Escambry Schools", states=states, near=handmade.ESCAMBRY_AL)
    assert away.reason is Reason.AMBIGUOUS
    assert away.targets == ()
    assert "'ESCAMBRY' (FL) and 'Escambry County' (AL) tie by name across AL, FL" in away.detail


def test_a_namesake_whose_place_is_unknown_is_not_taken_to_be_far() -> None:
    """Across a state line, a point tells namesakes apart only when it knows where both lie."""
    directory = Directory(
        [
            DirectoryRecord(
                "SYN-D1", "Tollby", "district", None, "TN", None, "Tollby", 36.5, -82.2
            ),
            DirectoryRecord(
                "SYN-D2",
                "Tollby City Public Schools",
                "district",
                None,
                "VA",
                None,
                None,
                None,
                None,
            ),
        ]
    )
    matcher = Matcher(directory)
    result = matcher.match("Tollby City Schools", states=["TN", "VA"], near=(36.5, -82.2))
    assert result.reason is Reason.AMBIGUOUS
    assert result.targets == ()
    alone = matcher.match("Tollby City Schools", states=["TN"], near=(36.5, -82.2))
    assert _ids(alone.targets) == ["SYN-D1"]


def test_a_municipal_word_across_a_state_line_is_a_state_s_habit(
    handmade_matcher: Matcher,
) -> None:
    """Tennessee's "Bristmoor" says no "City"; that tells it from no Virginia district."""
    tennessee = handmade_matcher.match("Bristmoor City Schools", states=["TN"])
    assert _ids(tennessee.targets) == ["SYN-TN-BRIS"]
    assert tennessee.best is not None
    assert tennessee.best.score == 1.0
    both = handmade_matcher.match("Bristmoor City Schools", states=["TN", "VA"])
    assert both.reason is Reason.AMBIGUOUS
    scores = {c.record.id: c.score for c in (both.best, *both.runners_up) if c is not None}
    assert scores["SYN-TN-BRIS"] == scores["SYN-VA-BRIS"] == 1.0


def test_a_county_s_district_is_no_namesake_of_a_town_s(handmade_matcher: Matcher) -> None:
    """Kentucky's "Madmoor County" and Indiana's "Madmoor Consolidated Schools" are two names."""
    result = handmade_matcher.match("Madmoor Schools", states=["KY", "IN"])
    assert result.reason is Reason.NAME
    assert _ids(result.targets) == ["SYN-IN-MADT"]


def test_a_system_that_ties_with_a_namesake_across_a_state_line_goes_to_the_queue(
    handmade_matcher: Matcher,
) -> None:
    result = handmade_matcher.match("Tamsby Public Schools", states=["MT", "OK"])
    assert result.reason is Reason.AMBIGUOUS
    assert result.targets == ()


def test_haversine_km() -> None:
    assert haversine_km((0.0, 0.0), (0.0, 1.0)) == pytest.approx(111.195, rel=1e-4)
    assert haversine_km((40.0, -76.0), (40.0, -76.0)) == 0.0


# -- results -------------------------------------------------------------------------


def test_a_result_carries_the_best_and_the_runners_up(handmade_matcher: Matcher) -> None:
    result = handmade_matcher.match("Brambleton Schools", states=["AL"])
    assert result.reason is Reason.NAME
    assert result.level is Level.DISTRICT
    assert result.target is not None
    assert result.target.id == "SYN-AL-BRAMC"
    assert result.best is not None
    assert result.best.record is result.target
    assert 0 < len(result.runners_up) <= MatchSettings().runners_up
    scores = [result.best.score, *(c.score for c in result.runners_up)]
    assert scores == sorted(scores, reverse=True)
    assert result.target.id not in _ids(tuple(c.record for c in result.runners_up))
    assert result.runners_up[0].record.id == "SYN-AL-BRACO"


def test_ambiguous_and_weak_results_keep_their_candidates(handmade_matcher: Matcher) -> None:
    ambiguous = handmade_matcher.match("Kettleby Schools", states=["OH"])
    assert ambiguous.reason is Reason.AMBIGUOUS
    assert ambiguous.best is not None
    assert {ambiguous.best.record.id, ambiguous.runners_up[0].record.id} == {
        "SYN-OH-KETC",
        "SYN-OH-KETL",
    }
    assert "Kettleby" in ambiguous.detail
    weak = handmade_matcher.match("Lancaster Schools", states=["SC"])
    assert weak.reason is Reason.WEAK
    assert weak.best is not None
    assert weak.best.record.id == "SYN-SC-LANCO"
    assert weak.confidence < MatchSettings().threshold


def test_noise_alone_is_empty(handmade_matcher: Matcher) -> None:
    for listing in ("Schools", "(Closed)", "All Schools", "   ", ""):
        result = handmade_matcher.match(listing, states=["PA"])
        assert result.reason is Reason.EMPTY
        assert result.best is None
        assert result.target is None


def test_context_parts_narrow_the_search(handmade_matcher: Matcher) -> None:
    by_city = handmade_matcher.match("Lincoln Elementary - Brambleton", states=["AL"])
    assert by_city.reason is Reason.CONTEXT
    assert by_city.target is not None
    assert by_city.target.id == "SYN-AL-LINC1"
    assert "city" in by_city.detail
    by_district = handmade_matcher.match(
        "Brambleton County Schools: Lincoln Elementary", states=["AL"]
    )
    assert by_district.reason is Reason.CONTEXT
    assert by_district.target is not None
    assert by_district.target.id == "SYN-AL-LINC2"
    assert "Brambleton County" in by_district.detail
    by_state = handmade_matcher.match("Pleasant Grove Elementary, AL", states=["AL", "GA"])
    assert by_state.target is not None
    assert by_state.target.id == "SYN-AL-PLGRV"
    wrong_state = handmade_matcher.match("Lincoln Elementary, GA", states=["AL"])
    assert wrong_state.target is None
    clash = handmade_matcher.match("Lincoln Elementary - Brambleton - Oxbow", states=["AL"])
    assert clash.target is None


def test_expand_turns_a_district_into_its_schools(handmade_matcher: Matcher) -> None:
    result = handmade_matcher.match("Wexford R-IV", states=["MO"])
    assert result.target is not None
    schools = handmade_matcher.expand(result.target)
    assert _ids(schools) == ["SYN-MO-WEXMS", "SYN-MO-WEXSM", "SYN-MO-HERPR"]
    assert all(s.kind == "school" and s.district_id == "SYN-MO-WEX" for s in schools)
    assert _ids(handmade_matcher.expand("SYN-MO-WEXMS")) == ["SYN-MO-WEXMS"]
    assert handmade_matcher.expand("SYN-MO-OAK2") == ()
    with pytest.raises(KeyError):
        handmade_matcher.expand("SYN-NOPE")


def test_the_threshold_is_configurable(handmade_directory: Directory) -> None:
    strict = Matcher(handmade_directory, settings=MatchSettings(threshold=0.97))
    result = strict.match("Brambleton Schools", states=["AL"])
    assert result.target is None
    assert result.reason is Reason.WEAK
    assert result.confidence == pytest.approx(0.96)
    assert strict.match("Brambleton City Schools", states=["AL"]).target is not None


@pytest.mark.parametrize(
    "bad",
    [
        {"threshold": 0.0},
        {"threshold": 0.05},
        {"threshold": 1.5},
        {"margin": -0.1},
        {"tie": -1.0},
        {"near_ratio": 0.5},
        {"near_max_km": 0.0},
        {"runners_up": -1},
        {"reach_km": 0.0},
        {"stray_share": -0.1},
        {"stray_share": 1.0},
    ],
)
def test_settings_are_checked(bad: dict[str, float]) -> None:
    with pytest.raises(ValueError, match="must"):
        MatchSettings(**bad)  # type: ignore[arg-type]


def test_crowded_words_still_find_every_candidate() -> None:
    # SYNTHETIC: 3,200 schools that share two words.
    records = [
        DirectoryRecord("SYN-D1", "Tollgate SD", "district", None, "PA", None, None, None, None)
    ]
    records.extend(
        DirectoryRecord(
            f"SYN-S{i}",
            f"Tollgate Unit {i} School",
            "school",
            "SYN-D1",
            "PA",
            None,
            None,
            None,
            None,
        )
        for i in range(3200)
    )
    records.append(
        DirectoryRecord(
            "SYN-SX", "Tollgate Quarry School", "school", "SYN-D1", "PA", None, None, None, None
        )
    )
    matcher = Matcher(Directory(records))
    result = matcher.match("Tollgate Quarry Unit School", states=["PA"])
    assert result.best is not None
    assert result.best.record.id == "SYN-SX"
    crowded = matcher.match("Tollgate Unit School", states=["PA"])
    assert crowded.target is None
    assert crowded.reason is Reason.AMBIGUOUS


def test_a_typo_is_looked_up_only_in_states_that_have_records(
    handmade_matcher: Matcher,
) -> None:
    result = handmade_matcher.match("Bramleton City Schools", states=["AL", "HI"])
    assert result.target is not None
    assert result.target.id == "SYN-AL-BRAMC"


def test_a_record_without_a_city_never_matches_a_city_context() -> None:
    directory = Directory(
        [
            DirectoryRecord("SYN-S1", "Quarry Academy", "school", None, "PA", None, None, 40, -76),
            DirectoryRecord(
                "SYN-S2", "Quarry Academy", "school", None, "PA", None, "Oxbow", 41, -76
            ),
        ]
    )
    result = Matcher(directory).match("Quarry Academy (Oxbow)", states=["PA"])
    assert result.target is not None
    assert result.target.id == "SYN-S2"
    assert result.reason is Reason.CONTEXT


def test_two_state_parts_that_disagree_match_nothing(handmade_matcher: Matcher) -> None:
    result = handmade_matcher.match("Lincoln Elementary, AL, GA", states=["AL", "GA"])
    assert result.target is None


def test_a_part_that_names_nothing_is_no_context(handmade_matcher: Matcher) -> None:
    result = handmade_matcher.match("Lincoln Elementary - District", states=["AL"])
    assert result.target is None
    assert result.best is not None


def test_building_leaves_a_disabled_collector_disabled(handmade_directory: Directory) -> None:
    import gc  # noqa: PLC0415 - only this test touches the collector

    gc.disable()
    try:
        Matcher(handmade_directory)
        assert not gc.isenabled()
    finally:
        gc.enable()


def test_building_leaves_the_collector_as_it_was(handmade_directory: Directory) -> None:
    import gc  # noqa: PLC0415 - only this test touches the collector

    frozen = gc.get_freeze_count()
    Matcher(handmade_directory)
    assert gc.isenabled()
    assert gc.get_freeze_count() == frozen


# -- affiliations -------------------------------------------------------------------


def test_an_affiliation_rules_out_the_public_district(handmade_matcher: Matcher) -> None:
    result = handmade_matcher.match("Tidewater Catholic Schools", states=["WA"], market="wxyz")
    assert result.target is None
    assert result.reason is Reason.WEAK
    assert result.level is Level.UNKNOWN
    assert result.confidence < 0.05
    # The ruled-out records stay as candidates for the unmatched queue.
    candidates = {c.record.id: c.score for c in (result.best, *result.runners_up) if c}
    assert "SYN-WA-TIDE" in candidates
    assert all(score <= 0.02 for score in candidates.values())


def test_an_affiliated_listing_takes_the_private_school_of_that_name(
    handmade_matcher: Matcher,
) -> None:
    result = handmade_matcher.match("Tidewater Christian Schools", states=["WA"])
    assert result.target is not None
    assert result.target.id == "SYN-WA-TIDCS"
    assert result.target.district_id is None
    # "Adventist Christian" names a further faith: never a rival.
    runner_ids = {c.record.id: c.score for c in result.runners_up}
    assert runner_ids.get("SYN-WA-TIDAD", 0.0) <= 0.02
    public = handmade_matcher.match("Tidewater Public Schools", states=["WA"])
    assert public.target is not None
    assert public.target.id == "SYN-WA-TIDE"


def test_a_group_of_schools_is_not_one_of_them(handmade_matcher: Matcher) -> None:
    group = handmade_matcher.match("Tidewater Lutheran Schools", states=["WA"])
    assert group.target is None
    assert group.best is not None
    assert group.best.record.id == "SYN-WA-TIDLU"
    assert group.best.score < MatchSettings().threshold
    # A church's faith alone may be the church: the school only among schools.
    alone = handmade_matcher.match("Tidewater Lutheran", states=["WA"])
    assert alone.target is None
    assert alone.reason is Reason.PARISH
    one = handmade_matcher.match("Tidewater Lutheran", states=["WA"], category="Schools")
    assert one.target is not None
    assert one.target.id == "SYN-WA-TIDLU"


def test_a_ruled_out_record_is_never_accepted_at_any_threshold(
    handmade_directory: Directory,
) -> None:
    loosest = Matcher(handmade_directory, settings=MatchSettings(threshold=MIN_THRESHOLD))
    for listing, state in (
        ("Tidewater Catholic Schools", "WA"),
        ("Lancaster Christian Schools", "PA"),
        ("Cornhusk Lutheran Schools", "NE"),
    ):
        assert loosest.match(listing, states=[state]).target is None, listing


# -- colleges and universities ---------------------------------------------------------


def test_a_college_is_not_k12_but_keeps_its_candidates(handmade_matcher: Matcher) -> None:
    result = handmade_matcher.match("Brackenmoor College", states=["MA"], market="wxyz")
    assert result.target is None
    assert not result.accepted
    assert result.reason is Reason.NOT_K12
    assert result.confidence == 0.0
    assert "college" in result.detail
    assert result.best is not None
    assert result.best.record.id == "SYN-MA-BRCHS"
    high_school = handmade_matcher.match("Brackenmoor College High School", states=["MA"])
    assert high_school.target is not None
    assert high_school.target.id == "SYN-MA-BRCHS"


def test_an_alias_still_wins_for_a_college_name(handmade_directory: Directory) -> None:
    aliases = Aliases({"wxyz": {"brackenmoor college": "SYN-MA-BRCHS"}})
    result = Matcher(handmade_directory, aliases=aliases).match(
        "Brackenmoor College", states=["MA"], market="wxyz"
    )
    assert result.reason is Reason.ALIAS
    assert result.target is not None


# -- civic bodies ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("listing", "state", "best"),
    [
        ("City of Kettleby", "OH", "SYN-OH-KETC"),
        ("City Of Kettleby (Closed)", "OH", "SYN-OH-KETC"),
        ("Village of Farrowdale", "OH", "SYN-OH-FARR"),
        ("Town of Harlowe", "VT", "SYN-VT-HARL"),
        ("City of Marlowe", "LA", "SYN-LA-MARL"),
        ("Sabrel Pass Senior Center", "AL", "SYN-AL-SABRS"),
    ],
)
def test_a_civic_body_is_not_a_school_but_keeps_its_candidates(
    handmade_matcher: Matcher, listing: str, state: str, best: str
) -> None:
    result = handmade_matcher.match(listing, states=[state], market="wxyz")
    assert result.target is None
    assert not result.accepted
    assert result.reason is Reason.NOT_SCHOOL
    assert result.confidence == 0.0
    assert "civic body" in result.detail
    assert result.best is not None
    assert result.best.record.id == best
    assert result.best.score > MatchSettings().threshold - MatchSettings().margin


def test_a_civic_body_stays_out_at_any_threshold(handmade_directory: Directory) -> None:
    loosest = Matcher(handmade_directory, settings=MatchSettings(threshold=MIN_THRESHOLD))
    for listing, state in (("City of Kettleby", "OH"), ("Sabrel Pass Senior Center", "AL")):
        result = loosest.match(listing, states=[state])
        assert result.target is None, listing
        assert result.reason is Reason.NOT_SCHOOL, listing


def test_an_alias_still_wins_for_a_civic_name(handmade_directory: Directory) -> None:
    aliases = Aliases({"wxyz": {"city of kettleby": "SYN-OH-KETC"}})
    result = Matcher(handmade_directory, aliases=aliases).match(
        "City of Kettleby", states=["OH"], market="wxyz"
    )
    assert result.reason is Reason.ALIAS
    assert result.target is not None
    assert result.target.id == "SYN-OH-KETC"


def test_a_town_named_for_a_civic_word_is_still_the_town(handmade_matcher: Matcher) -> None:
    for listing in ("Millers Church", "Millers Church City"):
        result = handmade_matcher.match(listing, states=["VA"])
        assert result.target is not None, listing
        assert result.target.id == "SYN-VA-MILCH"
    # "City of" names the government, never the town's name alone.
    assert handmade_matcher.match("City of Millers Church", states=["VA"]).target is None


def test_a_park_district_is_not_its_town() -> None:
    """A civic listing counts as a town's name only when it is that name and no more."""
    matcher = _one_state(
        _record("SYN-D1", "Roselle Park Public School District", state="NJ", city="Roselle Park"),
        _record("SYN-D2", "Harwick SD", state="NJ", city="Harwick"),
    )
    town = matcher.match("Roselle Park", states=["NJ"])
    assert town.target is not None
    assert town.target.id == "SYN-D1"
    for listing in ("Roselle Park District", "Roselle Parks Department", "Roselle Park 4-H"):
        result = matcher.match(listing, states=["NJ"])
        assert result.reason is Reason.NOT_SCHOOL, listing
        assert result.target is None, listing


def test_a_record_word_is_credited_once() -> None:
    """A listing word spelled close to another listing word does not match it again."""
    matcher = _one_state(
        _record("SYN-D1", "Fairport Central School District", state="NY", city="Fairport"),
        _record("SYN-D2", "Harwick SD", state="NY", city="Harwick"),
    )
    district = matcher.match("Fairport Central School District", states=["NY"])
    assert district.best is not None
    assert district.best.score == 1.0
    doubled = matcher.match("Fairport Airport", states=["NY"])
    assert doubled.target is None
    assert doubled.best is not None
    assert doubled.best.score < MatchSettings().threshold
    typo = matcher.match("Fairpot Schools", states=["NY"])
    assert typo.target is not None
    assert typo.target.id == "SYN-D1"


def test_school_of_a_town_is_not_the_town_s_school_of_those_words() -> None:
    matcher = _one_state(
        _record("SYN-D1", "Carlisle SD", state="PA", city="Carlisle"),
        _record("SYN-S1", "Carlisle Valley School", district="SYN-D1", state="PA", kind="school"),
        _record("SYN-S2", "Pressley Ridge School for Autism", state="PA", kind="school"),
    )
    assert matcher.match("Valley School of Carlisle", states=["PA"]).target is None
    same_order = matcher.match("Carlisle Valley School", states=["PA"])
    assert same_order.target is not None
    assert same_order.target.id == "SYN-S1"
    for listing in ("Pressley Ridge School of Autism", "Pressley Ridge School for Autism"):
        result = matcher.match(listing, states=["PA"])
        assert result.target is not None, listing
        assert result.target.id == "SYN-S2", listing


def test_the_district_beside_a_civic_body_still_matches(handmade_matcher: Matcher) -> None:
    for listing, state, expected in (
        ("Kettleby City Schools", "OH", "SYN-OH-KETC"),
        ("Farrowdale Exempted Village Schools", "OH", "SYN-OH-FARR"),
        ("Harlowe Town School District", "VT", "SYN-VT-HARL"),
        ("City of Marlowe Schools", "LA", "SYN-LA-MARL"),
        ("Town of Orleby UFSD", "NY", "SYN-NY-ORLE"),
        ("Ada Church Pellow", "AL", "SYN-AL-ADACP"),
    ):
        result = handmade_matcher.match(listing, states=[state])
        assert result.target is not None, listing
        assert result.target.id == expected, listing


# -- state naming habits -----------------------------------------------------------------


def _one_state(*records: DirectoryRecord) -> Matcher:
    return Matcher(Directory(records))


def test_south_carolina_county_districts_imply_county() -> None:
    matcher = _one_state(
        DirectoryRecord("SYN-D1", "Harwell 01", "district", None, "SC", None, None, None, None),
        DirectoryRecord("SYN-D2", "Tolland 01", "district", None, "SC", None, None, None, None),
        DirectoryRecord("SYN-D3", "Tolland 02", "district", None, "SC", None, None, None, None),
        DirectoryRecord("SYN-D4", "Harwell 01", "district", None, "GA", None, None, None, None),
    )
    for listing in ("Harwell County Schools", "Harwell County School District", "Harwell 01"):
        result = matcher.match(listing, states=["SC"])
        assert result.target is not None, listing
        assert result.target.id == "SYN-D1"
    assert matcher.match("Tolland County Schools", states=["SC"]).reason is Reason.AMBIGUOUS
    # Only South Carolina names its county districts this way.
    assert matcher.match("Harwell County Schools", states=["GA"]).target is None


def test_florida_and_nevada_county_districts_imply_county() -> None:
    def district(record_id: str, name: str, state: str) -> DirectoryRecord:
        return DirectoryRecord(record_id, name, "district", None, state, None, None, None, None)

    matcher = _one_state(
        district("SYN-D1", "HARWELL", "FL"),
        district("SYN-D2", "ST. TOLLAND", "FL"),
        district("SYN-D3", "PALM HARWELL", "FL"),
        district("SYN-D4", "Harwell", "NV"),
        district("SYN-D5", "Harwell", "GA"),
    )
    for listing, state, expected in (
        ("Harwell County Schools", "FL", "SYN-D1"),
        ("Harwell County Public Schools", "FL", "SYN-D1"),
        ("Harwell County School District", "FL", "SYN-D1"),
        ("St. Tolland County Schools", "FL", "SYN-D2"),
        ("Palm Harwell County Schools", "FL", "SYN-D3"),
        ("Harwell County School District", "NV", "SYN-D4"),
    ):
        result = matcher.match(listing, states=[state])
        assert result.target is not None, listing
        assert result.target.id == expected, listing
    assert matcher.match("Harwell County Schools", states=["GA"]).target is None


def test_a_district_number_its_name_leaves_out() -> None:
    matcher = _one_state(
        DirectoryRecord(
            "SYN-D1", "HALLORAN SCHOOL DISTRICT", "district", None, "MO", None, None, None, None
        ),
        DirectoryRecord(
            "SYN-S1", "Quarry School", "school", "SYN-D1", "MO", None, None, None, None
        ),
    )
    district = matcher.match("Halloran R-II", states=["MO"])
    assert district.target is not None
    assert district.target.id == "SYN-D1"
    assert district.confidence == pytest.approx(0.9)
    school = matcher.match("Quarry School 5", states=["MO"])
    assert school.target is None
    assert school.reason is Reason.WEAK


def _record(  # noqa: PLR0913 - one argument per NCES column
    record_id: str,
    name: str,
    *,
    district: str | None = None,
    state: str = "UT",
    city: str | None = None,
    kind: str = "district",
) -> DirectoryRecord:
    return DirectoryRecord(
        record_id,
        name,
        "district" if kind == "district" else "school",
        district,
        state,
        None,
        city,
        None,
        None,
    )


def test_a_name_in_a_city_named_city_implies_city() -> None:
    matcher = _one_state(
        _record("SYN-D1", "Brinewater District", city="Brinewater City"),
        _record("SYN-S1", "Brinewater High", district="SYN-D1", city="Brinewater City", kind="s"),
        _record("SYN-D2", "Brinewater Valley District", city="Brinewater City"),
        _record("SYN-D3", "Ellery District", city="Ellery"),
        _record("SYN-D4", "Harlow City District", city="Harlow City"),
    )
    implied = {
        r.id: f.implied for r, f in zip(matcher.index.records, matcher.index.forms, strict=True)
    }
    assert implied == {
        "SYN-D1": {"city"},
        "SYN-S1": {"city"},
        "SYN-D2": frozenset(),  # its words are not the city's
        "SYN-D3": frozenset(),
        "SYN-D4": frozenset(),  # says City itself
    }
    result = matcher.match("Brinewater City School District", states=["UT"])
    assert result.target is not None
    assert result.target.id == "SYN-D1"
    assert result.confidence == 1.0
    # A place that is not "<name> City" is still named so by a list, as Tennessee's
    # "Murfreesboro City Schools" names NCES's "Murfreesboro": no other district
    # bears the name, so the City a list adds costs nothing.
    result = matcher.match("Ellery City Schools", states=["UT"])
    assert result.target is not None
    assert result.target.id == "SYN-D3"
    assert result.confidence == 1.0


def test_a_municipal_word_one_side_says_costs_nothing_when_the_name_is_alone() -> None:
    matcher = _one_state(
        _record("SYN-D1", "Murrowby", city="Murrowby", state="TN"),
        _record("SYN-D2", "Tullby", city="Tullby", state="TN"),
        _record("SYN-D3", "Tullby County", city="Tullby", state="TN"),
        _record("SYN-D4", "Bensby Township SD", city="Bensby", state="PA"),
        _record("SYN-D5", "Bristow Township SD", city="Levitby", state="PA"),
        _record("SYN-D6", "Bristow Borough SD", city="Bristow", state="PA"),
        _record("SYN-D7", "Cherrow Hill School District", city="Cherrow Hill", state="NJ"),
        _record("SYN-D8", "City University Schools", city="Memby", state="TN"),
        _record("SYN-D9", "University Schools", city="Memby", state="TN"),
    )
    for listing, state, expected in (
        ("Murrowby City Schools", "TN", "SYN-D1"),
        ("Bensby School District", "PA", "SYN-D4"),
        ("Bensby Schools", "PA", "SYN-D4"),
        ("Cherrow Hill Township School District", "NJ", "SYN-D7"),
        ("Tullby County Schools", "TN", "SYN-D3"),
        ("University Schools", "TN", "SYN-D9"),
    ):
        result = matcher.match(listing, states=[state])
        assert result.target is not None, listing
        assert result.target.id == expected, listing
        assert result.confidence == 1.0, listing
    # Another district bears the rest of the name: the municipal word tells them apart.
    for listing, state in (
        ("Tullby City Schools", "TN"),
        ("Bristow School District", "PA"),
    ):
        result = matcher.match(listing, states=[state])
        assert result.target is None, (listing, result.target)
    # Without a school's word, "<town> Borough" is the borough, not its district,
    # and a City that begins a name is its name, no municipality's.
    for listing, state in (
        ("Bensby Borough", "PA"),
        ("Murrowby City", "TN"),
        ("Cherrow Hill Township", "NJ"),
    ):
        assert matcher.match(listing, states=[state]).target is None, listing
    result = matcher.match("City University Schools", states=["TN"])
    assert result.target is not None
    assert result.target.id == "SYN-D8"


def test_a_municipal_word_forgiven_is_scored_again_in_the_index() -> None:
    matcher = _one_state(
        _record("SYN-D1", "Hampby Township SD", city="Hampby", state="PA"),
        _record("SYN-S1", "Hampby HS", district="SYN-D1", city="Hampby", state="PA", kind="s"),
        _record("SYN-D2", "Mannby Township SD", city="Mannby", state="PA"),
        _record("SYN-D3", "Mannby Central SD", city="Mannby", state="PA"),
    )
    index = matcher.index
    forms = listing_forms("Hampby School District")
    scored = index.search(forms, Scope(frozenset({"PA"})))
    assert scored[0].index == index.index_of("SYN-D1")
    assert scored[0].score == 1.0
    # A township the listing leaves out costs the score when another district
    # bears the rest of the name, but not the plausibility: it is a full rival.
    forms = listing_forms("Mannby School District")
    by_id = {index.records[s.index].id: s for s in index.search(forms, Scope(frozenset({"PA"})))}
    assert by_id["SYN-D2"].score < matcher.settings.threshold
    assert by_id["SYN-D2"].plausibility == 1.0
    assert matcher.match("Mannby School District", states=["PA"]).target is None
    result = matcher.match("Mannby Central School District", states=["PA"])
    assert result.target is not None
    assert result.target.id == "SYN-D3"


def test_a_district_named_as_a_school_fits_a_school_listing() -> None:
    center = "Ravensburg County Career and Technology Center"
    matcher = _one_state(
        _record("SYN-D1", center, state="PA"),
        _record("SYN-S1", f"{center} - Millgate", district="SYN-D1", state="PA", kind="s"),
        _record("SYN-S2", f"{center} - Stonebury", district="SYN-D1", state="PA", kind="s"),
        _record("SYN-D2", "Ravensburg County SD", state="PA"),
    )
    result = matcher.match("Ravensburg County Career & Technology Center", states=["PA"])
    assert result.level is Level.SCHOOL
    assert result.target is not None
    assert result.target.id == "SYN-D1"
    assert result.confidence == pytest.approx(0.9)
    assert _ids(matcher.expand(result.target)) == ["SYN-S1", "SYN-S2"]
    # A district without the noun is still the wrong kind for a school listing.
    listing = listing_forms("Ravensburg County Career Center").district
    assert listing.hint is Level.SCHOOL
    assert kind_factor(listing, record_form(center, district=True), district=True) == (
        LEVEL_NAMED_DISTRICT
    )
    plain = record_form("Ravensburg County SD", district=True)
    assert kind_factor(listing, plain, district=True) == WRONG_KIND


def test_a_school_does_not_compete_with_its_own_district() -> None:
    """A charter district that runs one school carries its name; the school is the answer."""
    matcher = _one_state(
        _record("SYN-D1", "Harborview Montessori CS", state="PA"),
        _record("SYN-S1", "Harborview Montessori CS", district="SYN-D1", state="PA", kind="s"),
    )
    result = matcher.match("Harborview Montesori Charter School", states=["PA"])
    assert result.target is not None
    assert result.target.id == "SYN-S1"
    assert result.best is not None
    assert result.best.score < 1.0
    # The district is close behind, yet costs no confidence.
    district = result.runners_up[0]
    assert district.record.id == "SYN-D1"
    assert district.score > result.best.score - MatchSettings().margin
    assert result.confidence == result.best.score


def test_a_town_named_college_is_not_a_college() -> None:
    matcher = _one_state(
        _record("SYN-D1", "Ridgemont College Area SD", state="PA", city="Ridgemont College"),
        _record("SYN-D2", "Ellery SD", state="PA", city="Ellery"),
    )
    town = matcher.match("Ridgemont College", states=["PA"])
    assert town.target is not None
    assert town.target.id == "SYN-D1"
    assert town.reason is Reason.NAME
    for listing in ("Ridgemont University", "Ellery College", "Ridgemont College of Nursing"):
        result = matcher.match(listing, states=["PA"])
        assert result.reason is Reason.NOT_K12, listing
        assert result.target is None


# -- district codes, kinds and businesses ------------------------------------------


def _maine() -> Matcher:
    """SYNTHETIC: a unit named only by code, its schools, and a town's own district."""
    return Matcher(
        Directory(
            [
                _record("SYN-U7", "RSU 97", state="ME", city="Tollbridge"),
                _record(
                    "SYN-U7H",
                    "Seacliff High School",
                    district="SYN-U7",
                    state="ME",
                    city="Tollbridge",
                    kind="school",
                ),
                _record(
                    "SYN-U7M",
                    "Seacliff Middle School",
                    district="SYN-U7",
                    state="ME",
                    city="Kettering",
                    kind="school",
                ),
                _record("SYN-T1", "Augustine Public Schools", state="ME", city="Augustine"),
                _record(
                    "SYN-T1L",
                    "Lincoln School",
                    district="SYN-T1",
                    state="ME",
                    city="Augustine",
                    kind="school",
                ),
                _record("SYN-NOCITY", "RSU 98", state="ME"),
            ]
        )
    )


def test_a_code_names_its_district_and_its_schools() -> None:
    matcher = _maine()
    assert _target(matcher, "RSU 97") == "SYN-U7"
    assert _target(matcher, "R.S.U. #97 - Seacliff") == "SYN-U7"
    assert _target(matcher, "RSU 97 Seacliff High School") == "SYN-U7H"
    assert _target(matcher, "RSU 98") == "SYN-NOCITY"
    # A code of the other series, and a school of a district in no unit.
    assert _target(matcher, "MSAD 97") is None
    assert _target(matcher, "RSU 97 Lincoln School") is None


def test_a_code_with_words_it_cannot_place_keeps_its_district_as_a_candidate() -> None:
    result = _maine().match("RSU 97 - Adult Education", states=["ME"])
    assert result.target is None
    assert result.reason is Reason.WEAK
    assert result.best is not None
    assert result.best.record.id == "SYN-U7"
    assert result.best.score == pytest.approx(CODE_ONLY)
    # Also when the rest names a school the unit does not have.
    school = _maine().match("RSU 97 Owls Head Central School", states=["ME"])
    assert school.target is None
    assert school.best is not None
    assert school.best.record.id == "SYN-U7"


def test_a_code_and_a_list_of_towns() -> None:
    """Not every town of a unit has a school; one that does names it."""
    result = _maine().match("RSU 97 - Kettering, Pellham Plantation", states=["ME"])
    assert result.target is not None
    assert result.target.id == "SYN-U7"
    assert result.reason is Reason.CONTEXT
    assert "'RSU 97' with 'Kettering'" in result.detail
    # Two codes of one district are read together, not as a code and a town.
    assert _target(_maine(), "RSU 97 / MSAD 97 - Augustine") is None
    # A school the unit does not have, beside one of its towns: not the unit.
    assert _target(_maine(), "RSU 97 - Owls Head Central School, Kettering") is None
    assert _target(_maine(), "RSU 97 - Seacliff High School, Kettering") == "SYN-U7H"


def _target(matcher: Matcher, listing: str, state: str = "ME") -> str | None:
    result = matcher.match(listing, states=[state])
    return result.target.id if result.target is not None else None


def test_a_listing_with_words_no_record_carries_still_finds_candidates() -> None:
    """Words the directory never spells rule out every name but leave candidates.

    ``"Chagrin Falls Ex. Vil. SD"`` once found no candidate at all, because its
    unknown words were the only ones looked up; the unmatched queue then had
    nothing to offer.
    """
    matcher = _one_state(
        DirectoryRecord(
            "SYN-D1", "WEXFORD FALLS LOCAL", "district", None, "OH", None, None, None, None
        ),
    )
    for listing in ("Wexford Falls Qzv Xqr Ypt SD", "Wexforrd Falls Qzv Xqr Ypt SD"):
        result = matcher.match(listing, states=["OH"])
        assert result.reason is Reason.WEAK, listing
        assert result.best is not None
        assert result.best.record.id == "SYN-D1"
    nothing = matcher.match("Qzv Xqr", states=["OH"])
    assert nothing.reason is Reason.NO_CANDIDATE
    assert nothing.detail == "no record in the states and counties searched resembles it"


def test_a_business_is_not_a_school_but_keeps_its_candidates() -> None:
    matcher = _one_state(
        DirectoryRecord(
            "SYN-S1", "Royce Elementary School", "school", None, "GA", None, None, None, None
        ),
    )
    result = matcher.match("Royce, LLC", states=["GA"])
    assert result.target is None
    assert result.reason is Reason.NOT_SCHOOL
    assert result.detail == "says 'llc': a business, not a school"
    assert result.best is not None


_FILLERS = (
    "Alder", "Beech", "Cypress", "Dogwood", "Elm", "Fir", "Ginkgo", "Hemlock", "Ironwood",
    "Juniper", "Larch", "Magnolia", "Nutmeg", "Olive", "Poplar", "Quince", "Redbud", "Sassafras",
    "Tupelo", "Walnut", "Yew", "Zelkova", "Aspen", "Balsam", "Catalpa",
)  # fmt: skip


def test_a_type_noun_a_school_does_not_say() -> None:
    # As in the NCES directory, "Academy" is a common word, and weighs little.
    academies = [
        _record(f"SYN-A{i}", f"{word} Academy", state="MA", kind="school")
        for i, word in enumerate(_FILLERS)
    ]
    matcher = Matcher(
        Directory(
            [
                *academies,
                _record("SYN-B", "BIRCHMONT SCHOOL", state="MA", kind="school"),
                _record("SYN-G", "GLORIA TOLLIS", state="MA", kind="school"),
                _record("SYN-D", "Harwick", state="MA"),
                _record("SYN-R", "Robin Frost", district="SYN-D", state="MA", kind="school"),
                _record("SYN-R2", "Other Elementary", district="SYN-D", state="MA", kind="school"),
                _record("SYN-K", "Keystone Charter Academy", state="MA"),
                _record(
                    "SYN-K1", "Riverside Elementary", district="SYN-K", state="MA", kind="school"
                ),
                _record(
                    "SYN-K2", "Hilltop Elementary", district="SYN-K", state="MA", kind="school"
                ),
            ]
        )
    )
    assert _target(matcher, "Birchmont Academy", "MA") is None
    assert _target(matcher, "Birchmont School", "MA") == "SYN-B"
    assert _target(matcher, "Gloria Tollis Academy", "MA") == "SYN-G"
    assert _target(matcher, "Robin Frost Charter School", "MA") is None
    assert _target(matcher, "Robin Frost", "MA") == "SYN-R"
    # A school of a charter academy's district is a charter academy; a school of
    # a city district is not.
    index = matcher.index
    types = frozenset({"charter", "academy"})
    assert not index._type_mismatch(types, index.index_of("SYN-K1"))
    assert index._type_mismatch(types, index.index_of("SYN-R2"))
    assert index._type_mismatch(frozenset({"charter"}), index.index_of("SYN-R"))
    assert not index._type_mismatch(frozenset({"academy"}), index.index_of("SYN-G"))


def test_a_town_s_public_school_is_its_system_unless_a_school_has_that_name() -> None:
    matcher = Matcher(
        Directory(
            [
                _record("SYN-E", "ELBA 49", state="ND", city="Elba"),
                _record(
                    "SYN-E1", "ELBA ELEMENTARY SCHOOL", district="SYN-E", state="ND", kind="school"
                ),
                _record("SYN-E2", "ELBA HIGH SCHOOL", district="SYN-E", state="ND", kind="school"),
                _record("SYN-C", "BRISCOE COUNTY", state="ND"),
                _record(
                    "SYN-C1", "CAREW PUBLIC SCHOOL", district="SYN-C", state="ND", kind="school"
                ),
            ]
        )
    )
    elba = matcher.match("Elba Public School", states=["ND"])
    assert elba.target is not None
    assert elba.target.id == "SYN-E"
    assert elba.confidence == pytest.approx(PUBLIC_SCHOOL_DISTRICT * NUMBER_ONLY_CANDIDATE)
    assert _target(matcher, "Carew Public School", "ND") == "SYN-C1"
    forms = listing_forms("Elba Public School")
    school = record_form("ELBA HIGH SCHOOL", district=False)
    assert kind_factor(forms.school, school, district=False) == PUBLIC_SCHOOL_OTHER


def test_a_regional_district_named_without_regional() -> None:
    matcher = Matcher(
        Directory(
            [
                _record("SYN-W", "Wachbury", state="MA"),
                _record(
                    "SYN-WH", "Wachbury Regional High", district="SYN-W", state="MA", kind="school"
                ),
                _record("SYN-F", "Franlow Area SD", state="PA"),
                _record("SYN-FR", "Franlow Regional SD", state="PA"),
            ]
        )
    )
    assert _target(matcher, "Wachbury Regional", "MA") == "SYN-W"
    assert _target(matcher, "Franlow Regional School District", "PA") == "SYN-FR"
    assert _target(matcher, "Franlow Area School District", "PA") == "SYN-F"


# -- directions, split schools and generic words -----------------------------------


def test_a_direction_said_on_one_side_rules_the_record_out() -> None:
    matcher = Matcher(
        Directory(
            [
                _record("SYN-L", "Lansmere Public School District", state="MI", city="Lansmere"),
                _record("SYN-EL", "East Lansmere School District", state="MI", city="E Lansmere"),
                _record("SYN-D", "Des Pellam Independent Comm School District", state="IA"),
                _record("SYN-WD", "West Des Pellam Comm School District", state="IA"),
                _record("SYN-NW", "Northwood Public Schools", state="MI"),
            ]
        )
    )
    for listing, state, expected in (
        ("E. Lansmere Public Schools", "MI", "SYN-EL"),
        ("E Lansmere Schools", "MI", "SYN-EL"),
        ("Lansmere Public Schools", "MI", "SYN-L"),
        ("W. Lansmere Public Schools", "MI", None),
        ("W. Des Pellam Schools", "IA", "SYN-WD"),
        ("Des Pellam Public Schools", "IA", "SYN-D"),
        ("E. Des Pellam Schools", "IA", None),
        ("N. Wood Public Schools", "MI", "SYN-NW"),  # the same words run together
    ):
        assert _target(matcher, listing, state) == expected, listing
    # The ruled-out record stays a candidate for the unmatched queue.
    result = matcher.match("W. Des Pellam Public Schools", states=["IA"])
    assert result.target is not None
    ruled_out = {c.record.id: c.score for c in result.runners_up}
    assert 0 < ruled_out["SYN-D"] < MIN_THRESHOLD


def test_a_district_named_by_its_code_answers_to_its_towns_directions() -> None:
    """ "MSAD 60 - N. Berwick": the code names the district, the town one of its places."""
    matcher = Matcher(
        Directory(
            [
                _record("SYN-M60", "RSU 60/MSAD 60", state="ME", city="North Berwyn"),
                _record(
                    "SYN-M60S",
                    "Noble Middle School",
                    district="SYN-M60",
                    state="ME",
                    city="Berwyn",
                    kind="school",
                ),
                _record("SYN-M61", "MSAD 61", state="ME", city="Harwick"),
                _record("SYN-WB", "W Berwyn-Dixby SD 147", state="IL", city="Berwyn"),
            ]
        )
    )
    assert _target(matcher, "MSAD 60 - Berwyn, N. Berwyn", "ME") == "SYN-M60"
    assert _target(matcher, "MSAD 60 N. Berwyn", "ME") == "SYN-M60"
    assert _target(matcher, "MSAD 61 N. Berwyn", "ME") is None
    # A district's own direction must still be said.
    assert _target(matcher, "Berwyn-Dixby School District 147", "IL") is None
    assert _target(matcher, "West Berwyn-Dixby School District 147", "IL") == "SYN-WB"


def _split_by_level() -> Matcher:
    """SYNTHETIC: a charter school NCES splits by level, and a town district."""
    return Matcher(
        Directory(
            [
                _record("SYN-G", "Grenmoor Bay Charter School", state="NH"),
                _record(
                    "SYN-GH",
                    "Grenmoor Bay Charter School (H)",
                    district="SYN-G",
                    state="NH",
                    kind="school",
                ),
                _record(
                    "SYN-GM",
                    "Grenmoor Bay Charter School (M)",
                    district="SYN-G",
                    state="NH",
                    kind="school",
                ),
                _record("SYN-T", "Tolliver School District", state="NH"),
                _record(
                    "SYN-TE",
                    "Harwick Central School (Elem)",
                    district="SYN-T",
                    state="NH",
                    kind="school",
                ),
                _record(
                    "SYN-TM",
                    "Harwick Central School (Middle)",
                    district="SYN-T",
                    state="NH",
                    kind="school",
                ),
                _record(
                    "SYN-TH", "Tolliver High School", district="SYN-T", state="NH", kind="school"
                ),
            ]
        )
    )


def test_a_school_split_by_level_names_its_district() -> None:
    matcher = _split_by_level()
    whole = matcher.match("Grenmoor Bay Charter School", states=["NH"])
    assert whole.target is not None
    assert whole.target.id == "SYN-G"
    assert whole.reason is Reason.NAME
    assert _ids(matcher.expand(whole.target)) == ["SYN-GH", "SYN-GM"]
    # A level names one part.
    assert _target(matcher, "Grenmoor Bay Charter School (H)", "NH") == "SYN-GH"
    assert _target(matcher, "Grenmoor Bay Charter Middle School", "NH") == "SYN-GM"
    assert listing_forms("Grenmoor Bay Charter School (H)").school.levels == {"high"}
    assert record_form("Harwick Central School (Elem)", district=False).levels == {"elementary"}


def test_two_schools_of_a_larger_district_stay_rivals() -> None:
    """Their district would mark Tolliver High, which the listing never named."""
    result = _split_by_level().match("Harwick Central School", states=["NH"])
    assert result.target is None
    assert result.reason is Reason.AMBIGUOUS
    assert result.best is not None
    assert result.best.record.id in {"SYN-TE", "SYN-TM"}


def test_school_inside_a_name_weighs_little() -> None:
    matcher = Matcher(
        Directory(
            [
                _record("SYN-V", "Village Preparatory School Tamsin Hills", kind="school"),
                _record("SYN-W", "Woodmere Preparatory Academy", kind="school"),
            ]
        )
    )
    assert matcher.index.weight["school"] == lexicon.WEAK_WEIGHT
    assert _target(matcher, "Village Prep Tamsin Hills", "UT") == "SYN-V"
    assert _target(matcher, "E Prep and Village Prep Tamsin Hills", "UT") == "SYN-V"


def test_a_place_and_its_kind_names_no_school_of_a_level() -> None:
    matcher = Matcher(
        Directory(
            [
                _record("SYN-D", "Dallenby Area SD", state="PA", city="Dallenby"),
                _record("SYN-Y", "Yarwick Twp El Sch", district="SYN-D", state="PA", kind="school"),
                _record("SYN-H", "Harwick County High School", state="PA", kind="school"),
                _record("SYN-C", "CRISTO LUZ KESSEL CITY", state="PA", kind="school"),
                _record("SYN-K", "Kettleby City", state="PA", city="Kettleby"),
            ]
        )
    )
    for listing in ("Yarwick Township", "Yarwick Twp", "Harwick County"):
        result = matcher.match(listing, states=["PA"])
        assert result.target is None, listing
        assert result.best is not None
        assert result.best.score == pytest.approx(PLACE_NOT_A_SCHOOL * LEVEL_ONLY_CANDIDATE)
    assert _target(matcher, "Yarwick Township Elementary", "PA") == "SYN-Y"
    assert _target(matcher, "Harwick County High", "PA") == "SYN-H"
    # A school whose own name the listing is, and a district named so, still match.
    assert _target(matcher, "Cristo Luz Kessel City", "PA") == "SYN-C"
    assert _target(matcher, "Kettleby City", "PA") == "SYN-K"


# -- a place's name -----------------------------------------------------------------


def _town(*records: DirectoryRecord) -> Matcher:
    return Matcher(Directory(records))


def _place_record(  # noqa: PLR0913 - one argument per NCES column
    record_id: str,
    name: str,
    city: str,
    *,
    district: str | None = None,
    kind: str = "district",
    state: str = "CA",
) -> DirectoryRecord:
    return DirectoryRecord(
        record_id,
        name,
        "district" if kind == "district" else "school",
        district,
        state,
        None,
        city,
        None,
        None,
    )


def test_a_town_s_name_is_its_district_not_its_high_school() -> None:
    matcher = _town(
        _place_record("SYN-NVU", "Napford Valley Unified", "Napford"),
        _place_record("SYN-NHS", "Napford High", "Napford", district="SYN-NVU", kind="school"),
        _place_record(
            "SYN-NJE", "Napford Junction Elementary", "Calloway", district="SYN-NVU", kind="school"
        ),
    )
    for listing in (
        "Napford",
        "NAPFORD - Closed",
        "Napford (2 Hour Delay)",
        "Napford - All Schools",
    ):
        result = matcher.match(listing, states=["CA"])
        assert result.target is not None, listing
        assert result.target.id == "SYN-NVU", listing
        # The high school named for the town speaks for its district.
        assert result.confidence == pytest.approx(LEVEL_ONLY_CANDIDATE * BARE_NAME_SCHOOL)
    school = matcher.match("Napford High", states=["CA"])
    assert school.target is not None
    assert school.target.id == "SYN-NHS"


def test_a_town_s_name_is_never_one_school_at_any_threshold() -> None:
    records = (
        _place_record("SYN-CNTY", "Corwin County", "Brackford", state="KY"),
        _place_record(
            "SYN-TOL",
            "Tolland Elementary",
            "Brackford",
            district="SYN-CNTY",
            kind="school",
            state="KY",
        ),
        _place_record(
            "SYN-VIL", "VILLAGE SCHOOL OF BRACKFORD", "BRACKFORD", kind="school", state="KY"
        ),
        _place_record(
            "SYN-OSW", "Oswick High School", "Oswick", district="SYN-CU", kind="school", state="KY"
        ),
        _place_record("SYN-CU", "CUSD 309", "Oswick", state="KY"),
    )
    for settings in (MatchSettings(), MatchSettings(threshold=MIN_THRESHOLD)):
        matcher = Matcher(Directory(records), settings=settings)
        for listing, school in (("Brackford", "SYN-VIL"), ("Oswick", "SYN-OSW")):
            result = matcher.match(listing, states=["KY"])
            assert result.target is None, listing
            assert result.reason is Reason.PLACE
            assert result.confidence == 0.0
            assert result.best is not None
            assert result.best.record.id == school
            assert "one school" in result.detail
    matcher = Matcher(Directory(records))
    # Its name, or its kind, still names the school.
    assert _target(matcher, "Village School of Brackford", "KY") == "SYN-VIL"
    assert _target(matcher, "Oswick High School", "KY") == "SYN-OSW"
    # "Brackford School" is not "Village School of Brackford": its words are in another order.
    assert _target(matcher, "Brackford School", "KY") is None


def test_a_bare_name_that_is_no_place_may_be_one_school() -> None:
    matcher = _town(
        _place_record("SYN-DEO", "GLORIA DEO", "Hillcrest", kind="school"),
        _place_record(
            "SYN-LIN", "Lincoln Elementary", "Springdale", district="SYN-SPR", kind="school"
        ),
        _place_record("SYN-SPR", "Springdale Unified", "Springdale"),
        _place_record("SYN-LIV", "Lincoln Village Unified", "Lincoln"),
    )
    assert _target(matcher, "Gloria Deo", "CA") == "SYN-DEO"
    # Beside its city, a name is what lies there, whatever town it also names.
    assert _target(matcher, "Lincoln, Springdale", "CA") == "SYN-LIN"


def test_a_town_s_district_is_one_that_lies_there() -> None:
    matcher = _town(
        _place_record("SYN-NT", "Nepwood Township School District", "Nepwood", state="NJ"),
        _place_record(
            "SYN-NTH",
            "Nepwood High School",
            "Nepwood",
            district="SYN-NT",
            kind="school",
            state="NJ",
        ),
        _place_record("SYN-NC", "Nepwood City School District", "Nepwood City", state="NJ"),
        _place_record("SYN-BAY", "Bayshore Unified", "Rickford"),
        _place_record("SYN-RHS", "Rickford High", "Rickford", district="SYN-BAY", kind="school"),
        _place_record("SYN-RE", "Rickford Elementary", "Susanvale"),
        _place_record("SYN-ML", "Mt Lindwood SD", "Pittsvale", state="PA"),
        _place_record(
            "SYN-KC", "LITTLE ACORNS LEARNING CENTER", "MOUNT LINDWOOD", kind="school", state="PA"
        ),
    )
    # The township's district, whose high school is in Nepwood, not the city next door.
    assert _target(matcher, "Nepwood", "NJ") == "SYN-NT"
    assert _target(matcher, "Nepwood City", "NJ") == "SYN-NC"
    # Rickford's schools are Bayshore Unified's: "Rickford Elementary" lies elsewhere.
    rickford = matcher.match("Rickford", states=["CA"])
    assert rickford.target is None
    assert rickford.reason is Reason.PLACE
    assert rickford.best is not None
    assert rickford.best.record.id == "SYN-RHS"
    # A town known only by a preschool's address rules no district out.
    assert _target(matcher, "Mt. Lindwood", "PA") == "SYN-ML"


def test_a_town_s_city_and_township_are_rivals() -> None:
    matcher = _town(
        _place_record("SYN-BC", "Burlwood City Public School District", "Burlwood", state="NJ"),
        _place_record("SYN-BT", "Burlwood Township School District", "Burlwood", state="NJ"),
    )
    result = matcher.match("Burlwood", states=["NJ"])
    assert result.target is None
    assert result.reason is Reason.AMBIGUOUS
    assert _target(matcher, "Burlwood Township", "NJ") == "SYN-BT"
    assert _target(matcher, "Burlwood City", "NJ") == "SYN-BC"


def test_a_saint_s_town_keeps_its_parish_school_as_a_rival() -> None:
    matcher = _town(
        _place_record("SYN-SM", "St Marwood Area SD", "Saint Marwood", state="PA"),
        _place_record(
            "SYN-SMH",
            "St Marwood Area HS",
            "Saint Marwood",
            district="SYN-SM",
            kind="school",
            state="PA",
        ),
        _place_record("SYN-SMS", "ST MARWOOD'S SCHOOL", "Harwick", kind="school", state="PA"),
    )
    assert matcher.match("St. Marwood's", states=["PA"]).reason is Reason.AMBIGUOUS
    assert _target(matcher, "St Marwood Area SD", "PA") == "SYN-SM"


def test_a_school_noun_or_a_level_in_a_town_s_own_name() -> None:
    matcher = _town(
        _place_record("SYN-BY", "Byfield Center Public Schools", "Byfield Center", state="MI"),
        _place_record(
            "SYN-BYH",
            "Byfield Center High School",
            "Byfield Center",
            district="SYN-BY",
            kind="school",
            state="MI",
        ),
        _place_record("SYN-HP", "High Pointe City", "High Pointe", state="MI"),
        _place_record(
            "SYN-HPS",
            "High Pointe Central",
            "High Pointe",
            district="SYN-HP",
            kind="school",
            state="MI",
        ),
        _place_record(
            "SYN-OR", "Oakmere Elementary", "Oakmere", district="SYN-HP", kind="school", state="MI"
        ),
    )
    assert _target(matcher, "Byfield Center", "MI") == "SYN-BY"
    assert _target(matcher, "High Pointe", "MI") == "SYN-HP"
    # A level after a town's name names a school of the town.
    assert _target(matcher, "Oakmere Elementary", "MI") == "SYN-OR"


def test_town_keys_count_every_word_and_write_solid() -> None:
    assert city_key("High Point") == "point high"
    assert city_key("High Point") != city_key("Point")
    assert city_key("Oakridge Elementary") != city_key("Oakridge")
    # NCES writes a letter apart where a list writes an apostrophe.
    assert city_key("O Fallon") == city_key("O'Fallon") == city_key("OFallon") == "ofallon"
    assert city_key("D Iberville") == city_key("D'Iberville")
    assert city_key("A B Smith") == "ab smith"
    assert place_keys("Coeur D Alene") & place_keys("COEUR D'ALENE")
    assert place_keys("Oak Ridge") == place_keys("OAKRIDGE")
    assert "fallschurch" in place_keys("Falls Church City")
    # Nothing is stemmed: a plural or a possessive s is another town.
    assert place_keys("Oak Hills").isdisjoint(place_keys("Oak Hill"))
    assert place_keys("Scott Valley").isdisjoint(place_keys("Scotts Valley"))
    assert place_keys("St. Mary's") == place_keys("SAINT MARYS")


# -- districts a market holds only part of ------------------------------------------------


def _place(  # noqa: PLR0913 - one argument per NCES column
    record_id: str,
    name: str,
    county: str,
    point: tuple[float, float] | None,
    *,
    district: str | None = None,
    kind: str = "school",
    city: str | None = None,
) -> DirectoryRecord:
    lat, lon = point if point is not None else (None, None)
    return DirectoryRecord(
        record_id,
        name,
        "district" if kind == "district" else "school",
        district,
        "TX",
        county,
        city,
        lat,
        lon,
    )


# SYNTHETIC: a network of high schools in three markets hundreds of kilometres
# apart, a school system with campuses in two, and a town district straddling
# a county line.
_EAST, _WEST, _SOUTH, _HOME = (32.4, -95.3), (35.2, -101.8), (29.4, -98.5), (26.2, -98.0)


def _markets() -> Matcher:
    return Matcher(
        Directory(
            (
                _place("SYN-N1", "ORVELL HIGH SCHOOLS", "89001", (33.0, -97.0), kind="district"),
                _place("SYN-N1E", "ORVELL H S OF KESTON", "89002", _EAST, district="SYN-N1"),
                _place("SYN-N1W", "ORVELL H S - BRANTLEY", "89003", _WEST, district="SYN-N1"),
                _place(
                    "SYN-N1X", "ORVELL H S - WESTHAM", "89003", (35.0, -101.9), district="SYN-N1"
                ),
                _place("SYN-N1S", "ORVELL H S OF DALBY", "89004", _SOUTH, district="SYN-N1"),
                _place("SYN-N2", "TAVERNE PUBLIC SCHOOLS", "89005", _HOME, kind="district"),
                _place("SYN-N2A", "TAVERNE LINDEN ACADEMY", "89005", _HOME, district="SYN-N2"),
                _place("SYN-N2B", "TAVERNE MARSH ACADEMY", "89005", _HOME, district="SYN-N2"),
                _place(
                    "SYN-N2P",
                    "TAVERNE KESTON COLLEGE PREPARATORY",
                    "89002",
                    _EAST,
                    district="SYN-N2",
                    city="Keston",
                ),
                _place("SYN-D1", "ASHCOMBE ISD", "89006", (31.0, -97.0), kind="district"),
                _place("SYN-D1H", "ASHCOMBE H S", "89006", (31.0, -97.0), district="SYN-D1"),
                _place("SYN-D1M", "ASHCOMBE MIDDLE", "89006", (31.05, -97.0), district="SYN-D1"),
                _place("SYN-D1E", "PERRY EL", "89007", (30.95, -96.9), district="SYN-D1"),
                _place("SYN-D1X", "ASHCOMBE VIRTUAL", "89008", None, district="SYN-D1"),
            )
        )
    )


def test_a_district_s_reach_against_a_market() -> None:
    matcher = _markets()
    index = matcher.index
    network = index.index_of("SYN-N1")
    reach = index.reach(network, {"89002"})
    assert _ids(tuple(index.records[i] for i in reach.inside)) == ["SYN-N1E"]
    assert reach.outside == 3
    assert reach.schools == 4
    assert reach.school_named
    assert len(reach.beyond) == 3
    assert not reach.whole()
    # A market with none of its schools measures from its office.
    office = index.reach(network, {"89001"})
    assert office.inside == ()
    assert len(office.beyond) == 4
    # A wider reach keeps a system whole, never one named as a school.
    system = index.index_of("SYN-N2")
    assert not index.reach(system, {"89005"}).whole()
    assert index.reach(system, {"89005"}, reach_km=2000).whole()
    assert not index.reach(network, {"89002"}, reach_km=2000).whole()
    # A district that straddles a county line keeps its schools near: whole. A
    # school without coordinates is never beyond the reach.
    town = index.index_of("SYN-D1")
    straddle = index.reach(town, {"89007"})
    assert straddle.outside == 3
    assert straddle.beyond == ()
    assert not straddle.school_named
    assert straddle.whole()
    assert index.reach(town, {"89006", "89007", "89008"}).outside == 0


def test_a_stray_school_leaves_a_district_whole() -> None:
    def reach(beyond: int, schools: int, *, named: bool = False) -> Reach:
        return Reach((0,), beyond, tuple(range(beyond)), schools, named)

    assert reach(1, 20).whole()  # one school in twenty
    assert not reach(1, 19).whole()
    assert not reach(2, 21).whole()
    assert reach(2, 21).whole(stray_share=0.1)
    assert reach(0, 1).whole()
    # One school named as one school stays whole: the listing names it.
    assert Reach((), 1, (), 1, True).whole()
    assert not Reach((), 1, (), 2, True).whole()


def test_a_network_s_one_campus_in_the_market() -> None:
    matcher = _markets()
    result = matcher.match("Orvell High School", states=["TX"], counties=["89002"])
    assert result.reason is Reason.CAMPUS
    assert result.target is not None
    assert result.target.id == "SYN-N1E"
    assert result.confidence >= MatchSettings().threshold
    assert "'ORVELL HIGH SCHOOLS' is named as one school" in result.detail
    assert _ids(matcher.expand(result.target)) == ["SYN-N1E"]
    # The network comes next among the candidates.
    assert result.runners_up[0].record.id == "SYN-N1"
    # Without counties the whole state is the market.
    statewide = matcher.match("Orvell High School", states=["TX"])
    assert statewide.target is not None
    assert statewide.target.id == "SYN-N1"


def test_two_campuses_in_the_market_go_to_the_queue_near_one_or_not() -> None:
    matcher = _markets()
    tied = matcher.match("Orvell High School", states=["TX"], counties=["89003"])
    assert tied.reason is Reason.AMBIGUOUS
    assert tied.target is None
    assert tied.confidence < MatchSettings().threshold
    ranked = [c.record.id for c in (tied.best, *tied.runners_up) if c is not None]
    assert set(ranked[:2]) == {"SYN-N1W", "SYN-N1X"}
    assert ranked[2] == "SYN-N1"
    # Both campuses are the market's: a point beside one says nothing of which.
    near = matcher.match("Orvell High School", states=["TX"], counties=["89003"], near=_WEST)
    assert near.reason is Reason.AMBIGUOUS
    assert near.target is None
    assert "2 there fit the listing" in near.detail
    # A looser threshold still leaves a tie under it.
    loose = Matcher(matcher.directory, settings=MatchSettings(threshold=0.5))
    assert loose.match("Orvell High Schools", states=["TX"], counties=["89003"]).confidence < 0.5


def test_no_campus_in_the_market_fits() -> None:
    matcher = _markets()
    office = matcher.match("Orvell High School", states=["TX"], counties=["89001"])
    assert office.reason is Reason.NETWORK
    assert office.target is None
    assert office.confidence == 0.0
    assert office.best is not None
    assert office.best.record.id == "SYN-N1"
    # The system's campus in the east is a college preparatory school.
    prep = matcher.match("Taverne Academy", states=["TX"], counties=["89002"])
    assert prep.target is None
    system = matcher.match("Taverne Public Schools", states=["TX"], counties=["89002"])
    assert system.reason is Reason.CAMPUS
    assert system.target is not None
    assert system.target.id == "SYN-N2P"
    home = matcher.match("Taverne Schools", states=["TX"], counties=["89005"])
    assert home.reason is Reason.AMBIGUOUS
    assert "has 1 of its 3 schools beyond 80 km" in home.detail


def test_which_campuses_a_listing_fits() -> None:
    matcher = _markets()
    index = matcher.index
    campuses = [index.index_of(i) for i in ("SYN-N1E", "SYN-N1W", "SYN-N2P")]

    def fits(listing: str) -> list[str]:
        found = index.campuses(listing_forms(listing), campuses, {"TX"})
        return [index.records[s.index].id for s, fit in found if fit]

    assert fits("Orvell High School") == ["SYN-N1E", "SYN-N1W"]
    assert fits("Orvell High School Keston") == ["SYN-N1E"]
    assert fits("Orvell Middle School") == []
    assert fits("Orvell High School 2") == []
    assert fits("Orvel High School") == ["SYN-N1E", "SYN-N1W"]  # a close spelling
    assert fits("Taverne Keston") == ["SYN-N2P"]  # its town's name counts
    assert fits("Taverne Public Schools Keston") == ["SYN-N2P"]  # designators do not
    scored = index.campuses(listing_forms("Orvell High School"), campuses[:1], {"TX"})
    assert 0.0 < scored[0][0].score < 1.0


def test_a_straddling_district_is_whole() -> None:
    matcher = _markets()
    result = matcher.match("Ashcombe ISD", states=["TX"], counties=["89007"])
    assert result.reason is Reason.NAME
    assert result.target is not None
    assert result.target.id == "SYN-D1"
    assert len(matcher.expand(result.target)) == 4


# -- a district's own name ------------------------------------------------------


def test_what_a_name_says_exactly_and_beyond(handmade_matcher: Matcher) -> None:
    index = handmade_matcher.index

    def at(record_id: str) -> int:
        return index.index_of(record_id)

    academy = listing_forms("Wyndhaven Academy")
    assert index.says_exactly(academy.district, at("SYN-TX-WYND"))
    assert index.says_exactly(listing_forms("Wynd Haven Academy").district, at("SYN-TX-WYND"))
    assert not index.says_exactly(academy.school, at("SYN-TX-WYNMS"))  # a level more
    assert index.says_exactly(listing_forms("Wyndhaven Academy Middle").school, at("SYN-TX-WYNMS"))
    assert not index.says_exactly(listing_forms("Wyndhaven").district, at("SYN-TX-WYND"))
    assert not index.says_exactly(listing_forms("Tamsin PCS").school, at("SYN-DC-TAMMS"))
    # A place qualifier must be said, unless the name implies it.
    assert index.says_exactly(listing_forms("Aldern Village").district, at("SYN-MO-ALDV"))
    assert not index.says_exactly(listing_forms("Aldern").district, at("SYN-MO-ALDV"))
    # What a campus says beyond a listing: its town's words are no more.
    charter = listing_forms("Orenway Charter School").school
    assert index.says_beyond(charter, at("SYN-MN-ORENE")) == {"elementary"}
    assert index.says_beyond(charter, at("SYN-MN-ORENF")) == frozenset()
    assert index.says_beyond(charter, at("SYN-MN-ORENH")) == {"ocs", "high"}


def test_a_district_s_own_name_is_not_its_school_that_adds_a_level(
    handmade_matcher: Matcher,
) -> None:
    """ "Wyndhaven Academy" is the district, though "Wyndhaven Academy Middle" scores higher."""
    result = handmade_matcher.match("Wyndhaven Academy", states=["TX"], counties=["87701"])
    assert result.reason is Reason.NAME
    assert result.target is not None
    assert result.target.id == "SYN-TX-WYND"
    assert result.confidence >= MatchSettings().threshold
    assert "word for word" in result.detail
    runner = {c.record.id: c.score for c in result.runners_up}
    assert runner["SYN-TX-WYNMS"] > result.confidence
    assert len(handmade_matcher.expand(result.target)) == 4
    # Its schools by their own names.
    middle = handmade_matcher.match("Wyndhaven Academy Middle School", states=["TX"])
    assert middle.target is not None
    assert middle.target.id == "SYN-TX-WYNMS"
    # A district of one school named as it: the school.
    kesselby = handmade_matcher.match("Kesselby Academy", states=["MI"])
    assert kesselby.target is not None
    assert kesselby.target.id == "SYN-MI-KESAS"


def test_a_district_s_own_name_that_fits_it_badly_goes_to_the_queue(
    handmade_directory: Directory,
) -> None:
    """ "Aldern Village School" is word for word "ALDERN VILLAGE", or its high school."""
    matcher = Matcher(handmade_directory)
    result = matcher.match("Aldern Village School", states=["MO"])
    assert result.reason is Reason.AMBIGUOUS
    assert result.target is None
    assert result.confidence < MatchSettings().threshold
    assert result.best is not None
    assert result.best.record.id == "SYN-MO-ALDVH"
    assert result.runners_up[0].record.id == "SYN-MO-ALDV"
    assert "'ALDERN VILLAGE' is the listing's name, word for word" in result.detail
    # A threshold the district's score clears takes the district.
    loose = Matcher(handmade_directory, settings=MatchSettings(threshold=0.6))
    taken = loose.match("Aldern Village School", states=["MO"])
    assert taken.target is not None
    assert taken.target.id == "SYN-MO-ALDV"


def test_a_network_s_one_fitting_campus_that_says_more_goes_to_the_queue(
    handmade_matcher: Matcher,
) -> None:
    """At home the one campus "Orenway Charter School" fits says a level more than it."""
    home = handmade_matcher.match("Orenway Charter School", states=["MN"], counties=["87709"])
    assert home.reason is Reason.AMBIGUOUS
    assert home.target is None
    assert home.confidence < MatchSettings().threshold
    assert home.best is not None
    assert home.best.record.id == "SYN-MN-ORENE"
    assert "fits the listing and says more, beside 1 other schools of it there" in home.detail
    away = handmade_matcher.match("Orenway Charter School", states=["MN"], counties=["87710"])
    assert away.reason is Reason.CAMPUS
    assert away.target is not None
    assert away.target.id == "SYN-MN-ORENF"


def test_districts_of_one_town_told_apart_by_their_legal_form(handmade_matcher: Matcher) -> None:
    def match(listing: str, state: str) -> tuple[str | None, Reason, str]:
        result = handmade_matcher.match(listing, states=[state])
        return (result.target.id if result.target else None, result.reason, result.detail)

    target, reason, detail = match("Marrowgate Public Schools", "MI")
    assert (target, reason) == ("SYN-MI-MARPS", Reason.NAME)
    assert "the only one whose legal form says 'public'" in detail
    assert match("Marrowgate Community Schools", "MI")[0] == "SYN-MI-MARCS"
    assert match("Marrowgate Schools", "MI")[:2] == (None, Reason.AMBIGUOUS)
    # A school system is not a program's district of one school.
    target, reason, detail = match("Harrowby Public Schools", "CO")
    assert target == "SYN-CO-HAR1"
    assert "the only one that runs more than one school" in detail
    # Two places of one name are not told apart by their designators.
    assert match("Saltgrass Public Schools", "TX")[0] is None
    # Nor does a name that leaves out the "City" or the "Village" of two charter
    # schools' names name either: more of each name follows the word, so it is a
    # word of the name ("Capwell City PCS", "Capwell Village PCS").
    assert match("Capwell Public Charter Schools", "DC")[0] is None
    # A town's elementary and high school districts of one name are its school
    # system, which the listing names whole; a level names one.
    both = handmade_matcher.match("Kelburn Union Schools", states=["CA"])
    assert both.reason is Reason.SYSTEM
    assert [record.id for record in both.targets] == ["SYN-CA-KELE", "SYN-CA-KELH"]
    assert match("Kelburn Union High School District", "CA")[0] == "SYN-CA-KELH"


# -- towns within reach, exact names, spelling ------------------------------------


def test_a_town_is_within_reach_of_a_point_by_any_of_its_records() -> None:
    town = Town(frozenset({1}), frozenset({"80101"}), ((40.0, -80.0), (41.0, -80.0)))
    assert town.within((41.5, -80.0), 80.0)
    assert not town.within((43.0, -80.0), 80.0)
    assert not Town(frozenset(), frozenset(), ()).within((40.0, -80.0), 80.0)


def test_a_town_names_its_district_only_within_the_listing_reach(
    handmade_matcher: Matcher,
) -> None:
    def match(
        counties: list[str] | None = None, near: tuple[float, float] | None = None
    ) -> tuple[str | None, Reason, str]:
        result = handmade_matcher.match("Edgemere", states=["TX"], counties=counties, near=near)
        return (result.target.id if result.target else None, result.reason, result.detail)

    # San Arvello's EDGEMERE ISD, from a market 440 km from the town of Edgemere.
    target, reason, detail = match(near=handmade.SAN_ARVELLO)
    assert (target, reason) == ("SYN-TX-EDGS", Reason.NEAREST)
    assert "nearest of 2 tied names" in detail
    assert match(counties=[handmade.SAN_ARVELLO_CO])[:2] == ("SYN-TX-EDGS", Reason.NAME)
    # The town's own, from its county or near it.
    assert match(counties=[handmade.EDGEMERE_CO])[0] == "SYN-TX-EDGT"
    assert match(near=handmade.EDGEMERE)[0] == "SYN-TX-EDGT"
    # Counties rule over a point: the town lies outside them, however near.
    assert match(counties=[handmade.SAN_ARVELLO_CO], near=handmade.EDGEMERE)[0] == "SYN-TX-EDGS"
    # Statewide, two districts of the name.
    assert match()[:2] == (None, Reason.AMBIGUOUS)
    # A district that is not the listing's word for word still ranks below the
    # town's when the town is within reach: "Brennan" statewide is the town's.
    brennan = handmade_matcher.match("Brennan", states=["OH"])
    assert brennan.target is not None
    assert brennan.target.id == "SYN-OH-BRENC"
    far = handmade_matcher.match("Brennan", states=["OH"], near=handmade.HARWOOD_SPRINGS)
    assert far.target is not None
    assert far.target.id == "SYN-OH-BRENL"


def test_a_district_named_word_for_word_is_never_ranked_below_the_town(
    handmade_matcher: Matcher,
) -> None:
    # The one school addressed in Kentmoor is Grand Maren's, yet "Kentmoor" is
    # "Kentmoor Public Schools".
    result = handmade_matcher.match("Kentmoor", states=["MI"], counties=[handmade.GRAND_MAREN_CO])
    assert result.target is not None
    assert result.target.id == "SYN-MI-KENT"
    assert result.confidence == 1.0
    # A county's district named by the county alone, beside a town of that name.
    county = handmade_matcher.match("Leemont", states=["FL"])
    assert county.target is not None
    assert county.target.id == "SYN-FL-LEEM"
    # But a charter school's own district is one school, never a town's name.
    city = handmade_matcher.match("Yarrowstown", states=["OH"])
    assert city.target is not None
    assert city.target.id == "SYN-OH-YARC"
    ranked = [c.record.id for c in (city.best, *city.runners_up) if c is not None]
    assert "SYN-OH-YARCS" in ranked


@pytest.mark.parametrize(
    ("listing", "state", "expected", "why"),
    [
        ("Kessford ISD", "MI", "SYN-MI-KESI", "whose name is the listing's, word for word"),
        ("Genmoor ISD", "MI", "SYN-MI-GENI", "whose legal form says 'independent'"),
        ("Saltgrass ISD", "TX", "SYN-TX-SALT", "whose legal form says 'independent'"),
        ("Wexley Union School District", "CA", "SYN-CA-WEXU", "whose legal form says 'union'"),
        # One county's intermediate district and the township's: a listing that
        # does not say ISD names the township's.
        ("Genmoor Schools", "MI", "SYN-MI-GENS", "of one county whose legal form says nothing"),
        ("Genmoor School District", "MI", "SYN-MI-GENS", "of one county whose legal form"),
    ],
)
def test_districts_that_tie_by_name_go_to_the_one_the_listing_says_exactly(
    handmade_matcher: Matcher, listing: str, state: str, expected: str, why: str
) -> None:
    result = handmade_matcher.match(listing, states=[state])
    assert result.target is not None
    assert result.target.id == expected
    assert result.reason is Reason.NAME
    assert why in result.detail


@pytest.mark.parametrize(
    ("listing", "state", "expected", "twin"),
    [
        ("Oakhurst Hill Schools", "OH", "SYN-OH-OAKHU", "SYN-OH-OAKHS"),
        ("Oakhurst Hills", "OH", "SYN-OH-OAKHS", "SYN-OH-OAKHU"),
        ("Tarrow Valley", "CA", "SYN-CA-TARV", "SYN-CA-TARSV"),
    ],
)
def test_a_word_one_name_writes_as_a_plural_tells_districts_apart(
    handmade_matcher: Matcher, listing: str, state: str, expected: str, twin: str
) -> None:
    """``"Oakhurst Hill"`` is not ``"Oakhurst Hills"``: the plural's ``s`` makes another word."""
    result = handmade_matcher.match(listing, states=[state])
    assert result.target is not None
    assert result.target.id == expected
    assert result.reason is Reason.NAME
    other = next(c for c in result.runners_up if c.record.id == twin)
    assert other.score <= PLURAL_DIFFERS * result.confidence + 1e-9


@pytest.mark.parametrize(
    ("listing", "state"),
    [
        # Two districts of one name, and names whose legal form a list may leave out.
        ("Edgemere ISD", "TX"),
        ("Saltgrass Public Schools", "TX"),
        ("Quillmoor Township Public Schools", "NJ"),
        ("Wexley", "CA"),
        ("Wexley Elementary", "CA"),
    ],
)
def test_districts_that_tie_by_name_and_say_no_more_stay_tied(
    handmade_matcher: Matcher, listing: str, state: str
) -> None:
    result = handmade_matcher.match(listing, states=[state])
    assert result.target is None
    assert result.reason is Reason.AMBIGUOUS


def test_spelling_does_not_break_a_tie_with_other_words() -> None:
    # "Central CUSD": a district of other words is a rival spelling cannot rule out.
    records = (
        DirectoryRecord(
            "SYN-IL-CC133", "Central City SD 133", "district", None, "IL", "80101", None, None, None
        ),
        DirectoryRecord(
            "SYN-IL-AC262",
            "A-C Central CUSD 262",
            "district",
            None,
            "IL",
            "80102",
            None,
            None,
            None,
        ),
    )
    matcher = Matcher(Directory(records))
    tied = [Scored(0, 0.883, 1.0), Scored(1, 0.873, 0.948)]
    assert matcher._exact_tie(tied, listing_forms("Central CUSD")) is None
    # Among the same words, the spelling decides: "Central" is "Central City SD 133".
    records = (
        DirectoryRecord(
            "SYN-IL-CC133", "Central City SD 133", "district", None, "IL", "80101", None, None, None
        ),
        DirectoryRecord(
            "SYN-IL-CS133",
            "Centrals City SD 133",
            "district",
            None,
            "IL",
            "80102",
            None,
            None,
            None,
        ),
    )
    matcher = Matcher(Directory(records))
    tie = matcher._exact_tie([Scored(0, 0.96, 1.0), Scored(1, 0.96, 1.0)], listing_forms("Central"))
    assert tie is not None
    assert tie.winner.index == 0


def test_a_name_as_spelled_leaves_out_joining_words(handmade_matcher: Matcher) -> None:
    index = handmade_matcher.index
    hills = index.index_of("SYN-OH-OAKHS")
    assert index.says_as_spelled(("oakhurst", "hills"), hills)
    assert not index.says_as_spelled(("oakhurst", "hill"), hills)
    assert index.says_as_spelled(("oakhursthills",), hills)
    assert index.says_as_spelled(("oakhurst", "of", "hills"), hills)
    assert index.identifying(frozenset({"a", "of", "hill"})) == {"hill"}


# -- brackets NCES ends a name with (SYNTHETIC records of match.handmade) -------------


def test_the_index_reads_a_name_apart_from_its_brackets(handmade_matcher: Matcher) -> None:
    index = handmade_matcher.index
    county = index.index_of("SYN-WA-EVBT")
    assert index.names[county] == "Everbrook School District"
    assert index.forms[county].tokens == ("everbrook",)
    assert index.optional(county) == {"talli"}
    assert index.forms_of(county) == (index.forms[county],)
    second = index.index_of("SYN-NY-CARV")
    assert [form.tokens for form in index.forms_of(second)] == [
        ("carverton", "stony", "mill"),
        ("north", "rockmere"),
    ]
    assert frozenset({"north", "rockmere"}) in index.word_sets(second)
    assert index.says_exactly(listing_forms("North Rockmere").district, second)
    assert index.says_as_spelled(("north", "rockmere"), second)
    assert index.legal_words(second) == {"central", "school", "district"}
    # A former name keeps the district's kind: "Berrow-Millan Local".
    former = index.index_of("SYN-OH-EDVL")
    assert index.forms_of(former)[1].qualifiers == {"local"}
    # A charter district's legal form in brackets is its school's to say too.
    assert index.optional(index.index_of("SYN-OK-COMA")) == {"charter"}
    assert index.optional(index.index_of("SYN-OK-COMAS")) == {"charter"}
    assert index.district_types[index.index_of("SYN-OK-COMAS")] >= {"charter"}
    # An entity number is no number of the district's.
    assert not index.forms[index.index_of("SYN-AZ-FLAG")].numbers
    assert index.optional(index.index_of("SYN-AZ-FLAG")) == frozenset()


def test_counties_are_known_by_name(handmade_matcher: Matcher) -> None:
    index = handmade_matcher.index
    assert index.counties_named(["tallis"], ["WA"]) == {handmade.TALLIS_CO}
    assert index.counties_named(("monrow",), ["MI", "WA"]) == {handmade.MONROW_CO}
    assert index.counties_named(["tallis"], ["MI"]) == frozenset()
    assert index.counties_named(["nowhere"], ["WA", "XX"]) == frozenset()


def test_a_second_name_scores_under_a_district_s_own_name(handmade_matcher: Matcher) -> None:
    result = handmade_matcher.match("Killoway ISD", states=["TX"])
    assert result.target is not None
    assert result.target.id == "SYN-TX-KILL"
    # The charter district's second name, whose own name says a high school.
    rivals = {c.record.id: c.score for c in result.runners_up}
    assert rivals["SYN-TX-MALB"] == pytest.approx(SECOND_NAME * LEVEL_ONLY_CANDIDATE)
    named = handmade_matcher.match("North Rockmere CSD", states=["NY"])
    assert named.target is not None
    assert named.target.id == "SYN-NY-CARV"
    assert named.confidence == pytest.approx(SECOND_NAME)


def test_a_county_s_words_count_when_said_and_cost_nothing_when_not(
    handmade_matcher: Matcher,
) -> None:
    said = handmade_matcher.match("Everbrook Tallis", states=["WA"])
    assert said.target is not None
    assert said.target.id == "SYN-WA-EVBT"
    assert said.confidence == 1.0
    # "County" beside the county's words is the county's, not a "Everbrook County".
    county = handmade_matcher.match("Everbrook Tallis County Schools", states=["WA"])
    assert county.target is not None
    assert county.target.id == "SYN-WA-EVBT"
    assert handmade_matcher.match("Everbrook County Schools", states=["WA"]).target is None
    # The other county's words say the other district.
    other = handmade_matcher.match("Everbrook Quenby", states=["WA"])
    assert other.target is not None
    assert other.target.id == "SYN-WA-EVBQ"


def test_a_part_that_names_a_county_narrows_the_search(handmade_matcher: Matcher) -> None:
    for listing, expected in (
        ("Everbrook School District (Tallis)", "SYN-WA-EVBT"),
        ("Everbrook Schools - Quenby County", "SYN-WA-EVBQ"),
        ("Everbrook Schools, Quenby Co.", "SYN-WA-EVBQ"),
        ("Madley (Orrin)", "SYN-MI-MADO"),
        ("Madley Schools - Oakmere County", "SYN-MI-MADH"),
    ):
        result = handmade_matcher.match(listing, states=["WA", "MI"])
        assert result.target is not None, listing
        assert result.target.id == expected, listing
    context = handmade_matcher.match("Madley Schools - Oakmere County", states=["MI"])
    assert context.reason is Reason.CONTEXT
    assert "in the county 'Oakmere'" in context.detail
    # A bracket NCES-style: the name before it, which answers to it.
    bracket = handmade_matcher.match("Everbrook School District (Tallis)", states=["WA"])
    assert bracket.reason is Reason.CONTEXT
    assert "among those that answer to 'Tallis'" in bracket.detail
    # A county outside the listing's counties narrows it to nothing.
    outside = handmade_matcher.match(
        "Everbrook School District (Tallis)", states=["WA"], counties=[handmade.QUENBY_CO]
    )
    assert outside.target is None
    # A county no record names is none.
    nowhere = handmade_matcher.match("Everbrook Schools - Nowhere County", states=["WA"])
    assert nowhere.target is None


def test_a_town_that_shares_a_county_s_name_is_read_as_the_town() -> None:
    # SYNTHETIC: the county of Harlow holds the town of Harlow and the town of
    # Tamber; a part "Harlow" is the town, "Harlow County" the county.
    county = "80101"
    records = (
        DirectoryRecord(
            "SYN-D1", "Harlow SD", "district", None, "PA", county, "Harlow", 40.0, -76.0,
            county="Harlow County",
        ),
        DirectoryRecord(
            "SYN-S1", "Lincoln Elementary", "school", "SYN-D1", "PA", county, "Tamber", 40.1,
            -76.1, county="Harlow County",
        ),
        DirectoryRecord(
            "SYN-S2", "Harlow High School", "school", "SYN-D1", "PA", county, "Harlow", 40.0,
            -76.0, county="Harlow County",
        ),
    )  # fmt: skip
    matcher = Matcher(Directory(records))
    base = Scope(frozenset({"PA"}))
    assert matcher._county_context("Harlow", base) is None
    assert matcher._county_context("Tamber", base) is None
    for part in ("Harlow County", "Harlow Co.", "HARLOW COUNTY"):
        context = matcher._county_context(part, base)
        assert context is not None, part
        assert context.scope.counties == frozenset({county})
    elsewhere = Scope(base.states, frozenset({"80102"}))
    assert matcher._county_context("Harlow County", elsewhere) is None
    tamber = matcher.match("Lincoln Elementary - Harlow County", states=["PA"])
    assert tamber.target is not None
    assert tamber.target.id == "SYN-S1"


def test_a_district_named_as_a_company_is_that_district(handmade_matcher: Matcher) -> None:
    named = handmade_matcher.match("Friendmoor House Inc.", states=["AZ"])
    assert named.target is not None
    assert named.target.id == "SYN-AZ-FRND"
    business = handmade_matcher.match("Friendmoor Hauling Inc.", states=["AZ"])
    assert business.target is None
    assert business.reason is Reason.NOT_SCHOOL


def test_a_code_of_another_state_s_series_names_no_numbered_district(
    handmade_matcher: Matcher,
) -> None:
    result = handmade_matcher.match("MSAD 51", states=["IL"])
    assert result.target is None
    assert result.reason is Reason.NO_CANDIDATE
    numbered = handmade_matcher.match("Consolidated SD 51", states=["IL"])
    assert numbered.target is not None
    assert numbered.target.id == "SYN-IL-CSD51"


@pytest.mark.parametrize("listing", ["St.", "Mt.", "Ft.", "ST"])
def test_an_abbreviation_alone_is_empty(handmade_matcher: Matcher, listing: str) -> None:
    result = handmade_matcher.match(listing, states=["TX"])
    assert result.target is None
    assert result.reason is Reason.EMPTY


def test_a_bracket_that_says_another_level_is_not_the_record_s(handmade_matcher: Matcher) -> None:
    index = handmade_matcher.index
    school = index.index_of("SYN-NJ-HIGHTM")
    assert not index.answers_to(school, record_form("Elementary", district=False))
    assert index.answers_to(school, record_form("Middle", district=False))
    district = index.index_of("SYN-NJ-HIGHT")
    assert index.answers_to(district, record_form("Elementary", district=False))


def test_a_listing_of_a_bracket_alone_names_nothing(handmade_matcher: Matcher) -> None:
    result = handmade_matcher.match("St. (Monrow)", states=["MI"])
    assert result.target is None


def test_a_county_among_the_listing_s_counties_narrows_to_it(handmade_matcher: Matcher) -> None:
    base = Scope(frozenset({"WA"}), frozenset({handmade.TALLIS_CO, handmade.QUENBY_CO}))
    context = handmade_matcher._county_context("Quenby County", base)
    assert context is not None
    assert context.scope.counties == frozenset({handmade.QUENBY_CO})


def test_a_second_name_spelled_as_its_own_is_one_name() -> None:
    # SYNTHETIC: NCES repeats a district's name in brackets.
    record = DirectoryRecord(
        "SYN-D1", "HARROW CSD (HARROW)", "district", None, "NY", "80101", "Harrow", 42.0, -75.0
    )
    matcher = Matcher(Directory([record]))
    result = matcher.match("Harrow CSD", states=["NY"])
    assert result.target is not None
    assert result.confidence == 1.0


def test_a_district_of_several_schools_is_taken_by_its_exact_name() -> None:
    # SYNTHETIC: two districts of one town and one name; the one whose name is the
    # listing's runs two schools, so it is not set aside for the other.
    records = (
        DirectoryRecord(
            "SYN-D1", "HARLOW COMMON SCHOOL DISTRICT", "district", None, "NY", "80101",
            "Harlow", 42.0, -75.0,
        ),
        DirectoryRecord(
            "SYN-S1", "Harlow School One", "school", "SYN-D1", "NY", "80101", "Harlow", 42.0,
            -75.0,
        ),
        DirectoryRecord(
            "SYN-S2", "Harlow School Two", "school", "SYN-D1", "NY", "80101", "Harlow", 42.0,
            -75.0,
        ),
        DirectoryRecord(
            "SYN-D2", "HARLOW CITY SCHOOL DISTRICT", "district", None, "NY", "80101", "Harlow",
            42.0, -75.0,
        ),
        DirectoryRecord(
            "SYN-S3", "Tamber Middle School", "school", "SYN-D2", "NY", "80101", "Harlow",
            42.0, -75.0,
        ),
    )  # fmt: skip
    result = Matcher(Directory(records)).match("Harlow", states=["NY"])
    assert result.target is not None
    assert result.target.id == "SYN-D1"


def test_two_companies_of_one_name_go_to_the_queue() -> None:
    # SYNTHETIC: two charter holders named as one company, and a school of that name.
    records = (
        DirectoryRecord(
            "SYN-D1", "Harrowgate-School Inc. (4401)", "district", None, "AZ", "80101",
            "Harrow", 33.0, -112.0,
        ),
        DirectoryRecord(
            "SYN-D2", "Harrowgate-School Inc. (4402)", "district", None, "AZ", "80101",
            "Harrow", 33.0, -112.0,
        ),
        DirectoryRecord(
            "SYN-D3", "Tamber Holdings Inc. (4403)", "district", None, "AZ", "80101", "Harrow",
            33.0, -112.0,
        ),
        DirectoryRecord(
            "SYN-S1", "Harrowgate-School", "school", "SYN-D3", "AZ", "80101", "Tamber", 33.0,
            -112.0,
        ),
    )  # fmt: skip
    result = Matcher(Directory(records)).match("Harrowgate-School Inc.", states=["AZ"])
    assert result.target is None
    assert result.reason is Reason.AMBIGUOUS
    assert "says 'inc'" in result.detail


# -- sections and parishes -------------------------------------------------------------


def test_a_section_of_anything_but_schools_names_no_school(handmade_matcher: Matcher) -> None:
    kc = ("MO", "KS")
    for category in ("Churches", "Business", "Gov't.", "Pre-Schools/Daycare"):
        result = handmade_matcher.match(
            "Visitation", states=kc, counties=handmade.KC, category=category
        )
        assert result.target is None
        assert result.reason is Reason.NOT_SCHOOL
        assert result.detail == f"filed under {category!r}, not among schools"
        assert result.category == category
        assert result.best is not None
        assert result.best.record.id == "SYN-MO-KVIS"
        # A school's word holds wherever the list files it.
        school = handmade_matcher.match(
            "Visitation Catholic School", states=kc, counties=handmade.KC, category=category
        )
        assert school.target is not None
        assert school.target.id == "SYN-MO-KVIS"
    # A town's name filed among governments is its government.
    town = handmade_matcher.match(
        "Lancaster", states=["PA"], counties=[handmade.PA_A], category="Government"
    )
    assert town.target is None
    assert town.reason is Reason.NOT_SCHOOL
    district = handmade_matcher.match(
        "Lancaster SD", states=["PA"], counties=[handmade.PA_A], category="Government"
    )
    assert district.target is not None
    # What is no school stays what it is.
    college = handmade_matcher.match("Lancaster College", states=["PA"], category="Business")
    assert college.reason is Reason.NOT_K12


def test_a_section_of_schools_or_none_leaves_a_school_s_word_alone(
    handmade_matcher: Matcher,
) -> None:
    for category in (None, "Schools", "Closings", "School/College"):
        result = handmade_matcher.match(
            "Visitation School", states=("MO", "KS"), counties=handmade.KC, category=category
        )
        assert result.target is not None
        assert result.target.id == "SYN-MO-KVIS"
        assert result.category == category


def test_a_parish_s_name_alone_waits_for_a_section_of_schools(handmade_matcher: Matcher) -> None:
    kc = ("MO", "KS")
    queued = handmade_matcher.match("Christ the King", states=kc, counties=handmade.KC)
    assert queued.target is None
    assert queued.reason is Reason.PARISH
    assert queued.confidence < MatchSettings().threshold
    assert "christ" in queued.detail
    assert queued.best is not None
    assert queued.best.record.id == "SYN-KS-KCTK"
    taken = handmade_matcher.match(
        "Christ the King", states=kc, counties=handmade.KC, category="Schools"
    )
    assert taken.target is not None
    assert taken.target.id == "SYN-KS-KCTK"
    # A district is no parish's school: a town's name stays its district's.
    town = handmade_matcher.match("Lancaster", states=["PA"], counties=[handmade.PA_A])
    assert town.target is not None
    assert town.target.kind == "district"


def test_an_alias_keeps_the_listing_s_section(handmade_directory: Directory) -> None:
    aliases = Aliases({"wxyz": {"christ the king": "SYN-KS-KCTK"}})
    matcher = Matcher(handmade_directory, aliases=aliases)
    pinned = matcher.match("Christ the King", states=["KS"], market="wxyz", category="Churches")
    assert pinned.reason is Reason.ALIAS
    assert pinned.category == "Churches"
    assert pinned.target is not None


def test_a_louisiana_parish_is_its_district_and_a_saint_s_parish_its_church(
    handmade_matcher: Matcher,
) -> None:
    parish = handmade_matcher.match("Bayou Teche Parish", states=["LA"])
    assert parish.target is not None
    assert parish.target.id == "SYN-LA-TECHE"
    church = handmade_matcher.match(
        "Christ the King Parish", states=("MO", "KS"), counties=handmade.KC
    )
    assert church.target is None
    assert church.reason is Reason.NOT_SCHOOL
    assert church.detail == "says 'parish': a civic body, not a school"


def test_a_catholic_listing_takes_a_saint_s_school_that_says_no_faith(
    handmade_matcher: Matcher,
) -> None:
    kc = ("MO", "KS")
    implied = handmade_matcher.match("St. Peter's Catholic School", states=kc, counties=handmade.KC)
    assert implied.target is not None
    assert implied.target.id == "SYN-MO-KSTPE"
    assert implied.confidence < 1.0
    # One that says the faith wins over one that implies it.
    said = handmade_matcher.match("Holy Cross Catholic School", states=kc, counties=handmade.KC)
    assert said.target is not None
    assert said.target.id == "SYN-KS-KHCRC"
    # Another church's school, and a public school, are never a Catholic listing's.
    other = handmade_matcher.match("St. Paul's Catholic School", states=kc, counties=handmade.KC)
    assert other.target is None


def test_virtual_schools_across_the_state_leave_a_county_s_district_whole(
    handmade_matcher: Matcher,
) -> None:
    index = handmade_matcher.index
    district = index.index_of("SYN-TN-JOHC")
    reach = index.reach(district, {handmade.JOHNSMERE_CO})
    assert reach.outside == 2
    assert reach.beyond == ()
    assert reach.whole()
    result = handmade_matcher.match(
        "Johnsmere County Schools", states=["TN"], counties=[handmade.JOHNSMERE_CO]
    )
    assert result.target is not None
    assert result.target.id == "SYN-TN-JOHC"
    assert len(handmade_matcher.expand(result.target)) == 6


def test_a_county_s_numbered_district_may_be_named_without_its_county(
    handmade_matcher: Matcher,
) -> None:
    numbered = handmade_matcher.match("Westmoor R-2", states=["MO"])
    assert numbered.target is not None
    assert numbered.target.id == "SYN-MO-WESTM"
    assert numbered.confidence == pytest.approx(COUNTY_LEFT_OUT_NUMBERED)
    bare = handmade_matcher.match("Westmoor Schools", states=["MO"])
    assert bare.target is None
    assert bare.best is not None
    assert bare.best.score < MatchSettings().threshold


# -- namesakes just past the counties -------------------------------------------------


def _placed(  # noqa: PLR0913 - one argument per NCES column
    record_id: str,
    name: str,
    county: str,
    point: tuple[float, float],
    *,
    district: str | None = None,
    state: str = "MA",
    kind: str = "school",
) -> DirectoryRecord:
    return DirectoryRecord(
        record_id,
        name,
        "district" if kind == "district" else "school",
        district,
        state,
        county,
        None,
        *point,
    )


_MARKET = (42.30, -71.10)
_KM_EAST = 1 / (111.2 * 0.7396)
"""Degrees of longitude a kilometre east of the market, at its latitude."""


def _east(km: float) -> tuple[float, float]:
    return (_MARKET[0], _MARKET[1] + km * _KM_EAST)


def test_a_county_grid_finds_the_counties_near_a_market() -> None:
    records = [
        _placed("SYN-S1", "Oldham School", "88001", _MARKET),
        _placed("SYN-S2", "Wexby School", "88002", _east(40)),
        _placed("SYN-S3", "Farby School", "88003", _east(200)),
        _placed("SYN-S4", "Nearby School", "88004", _east(30), state="NH"),
        _placed("SYN-S5", "Unplaced School", "88005", _MARKET),
    ]
    records[4] = DirectoryRecord(
        "SYN-S5", "Unplaced", "school", None, "MA", "88005", None, None, None
    )
    grid = CountyGrid(records)
    around = grid.around(["88001"], ["MA"])
    # Within reach in a listed state; not far off, not in another state, not unplaced.
    assert around == frozenset({"88002"})
    assert grid.around(["88001"], ["MA", "NH"]) == frozenset({"88002", "88004"})
    assert grid.around(["88001"], ["MA"], reach_km=250.0) == frozenset({"88002", "88003"})
    # Asked again, the same answer, worked out once.
    assert grid.around(("88001",), ("MA",)) is around
    # A market county of a state the listing is not searched in still places it.
    assert grid.around(["88004"], ["MA"]) == frozenset({"88001", "88002"})
    assert grid.around(["88099"], ["MA"]) == frozenset()
    assert index_reach_km() / 3 > CELL_DEGREES * 111.2


def index_reach_km() -> float:
    from snowlight.match.index import REACH_KM  # noqa: PLC0415 - one constant

    return REACH_KM


def _twins(*, far: bool = False, stray_name: str = "Hanbury High School") -> Matcher:
    """A market county in Massachusetts and, past it, a New Hampshire namesake.

    Forty schools of other names far off give the town's name the weight a rare
    word has in a real directory.
    """
    away = 200.0 if far else 30.0
    others = [
        _placed(f"SYN-MA-O{i}", f"Otherby {i} Academy", "88009", _east(500)) for i in range(40)
    ]
    return Matcher(
        Directory(
            [
                *others,
                _placed("SYN-MA-D", "Hanbury", "88001", _MARKET, kind="district"),
                _placed("SYN-MA-HS", "Hanbury High", "88001", _MARKET, district="SYN-MA-D"),
                _placed(
                    "SYN-NH-D",
                    "Hanbury School District",
                    "88002",
                    _east(away),
                    kind="district",
                    state="NH",
                ),
                _placed(
                    "SYN-NH-HS", stray_name, "88002", _east(away), district="SYN-NH-D", state="NH"
                ),
            ]
        )
    )


def test_a_namesake_just_past_the_counties_sends_the_listing_to_the_queue() -> None:
    matcher = _twins()
    for listing in ("Hanbury High School", "Hanbury School District", "Hanbury Schools"):
        result = matcher.match(listing, states=["MA", "NH"], counties=["88001"])
        assert result.target is None, listing
        assert result.reason is Reason.AMBIGUOUS
        assert result.confidence < MatchSettings().threshold
        assert result.best is not None
        assert result.best.record.state == "MA"
        assert result.runners_up[0].record.state == "NH"
        assert "just past them" in result.detail
        # Without the second state, or with the namesake far off, the county's.
        alone = matcher.match(listing, states=["MA"], counties=["88001"])
        assert alone.target is not None
        assert alone.target.state == "MA"
        far = _twins(far=True).match(listing, states=["MA", "NH"], counties=["88001"])
        assert far.target is not None
        assert far.target.state == "MA"


def test_a_namesake_past_the_counties_is_never_taken() -> None:
    matcher = _twins()
    result = matcher.match("Hanbury School District", states=["NH"], counties=["88001"])
    assert result.target is None


def test_a_point_breaks_a_tie_with_a_namesake_just_past_the_counties() -> None:
    near = _twins().match(
        "Hanbury High School", states=["MA", "NH"], counties=["88001"], near=_MARKET
    )
    assert near.target is not None
    assert near.target.id == "SYN-MA-HS"
    assert near.reason is Reason.NEAREST
    # A point nearer the namesake does not make it the listing's.
    past = _twins().match(
        "Hanbury High School", states=["MA", "NH"], counties=["88001"], near=_east(30)
    )
    assert past.target is None
    assert past.reason is Reason.AMBIGUOUS


def test_a_weaker_namesake_just_past_the_counties_costs_confidence() -> None:
    listing = "Hanbury High School"
    plain = _twins(far=True).match(listing, states=["MA", "NH"], counties=["88001"])
    # An initial more, which weighs little: within the margin, but short of a tie.
    close = _twins(stray_name="Hanbury J High School").match(
        listing, states=["MA", "NH"], counties=["88001"]
    )
    assert plain.target is not None
    assert close.target is not None
    assert close.target.id == plain.target.id == "SYN-MA-HS"
    assert close.confidence < plain.confidence


def test_an_alias_is_never_read_past_the_counties() -> None:
    aliases = Aliases({"wmur": {"hanbury high school": "SYN-MA-HS"}})
    matcher = Matcher(_twins().directory, aliases=aliases)
    result = matcher.match(
        "Hanbury High School", states=["MA", "NH"], counties=["88001"], market="wmur"
    )
    assert result.reason is Reason.ALIAS
    assert result.target is not None


def test_a_district_s_own_school_past_the_counties_is_no_namesake() -> None:
    records = [
        _placed("SYN-MA-D", "Tollbury", "88001", _MARKET, kind="district"),
        _placed("SYN-MA-E", "Tollbury Elementary", "88001", _MARKET, district="SYN-MA-D"),
        _placed("SYN-MA-H", "Tollbury High", "88002", _east(20), district="SYN-MA-D"),
    ]
    matcher = Matcher(Directory(records))
    district = matcher.match("Tollbury Public Schools", states=["MA"], counties=["88001"])
    assert district.target is not None
    assert district.target.id == "SYN-MA-D"
    school = matcher.match("Tollbury Elementary", states=["MA"], counties=["88001"])
    assert school.target is not None
    assert school.target.id == "SYN-MA-E"


def test_a_district_number_never_names_a_private_school() -> None:
    records = [
        _placed("SYN-MO-D", "ST. JARVIS R-I", "88001", _MARKET, kind="district", state="MO"),
        _placed("SYN-MO-C", "ST JARVIS CATHOLIC SCHOOL", "88009", _east(300), state="MO"),
        _placed("SYN-MO-U", "ST JARVIS NO. 2 SCHOOL", "88009", _east(300), state="MO"),
    ]
    matcher = Matcher(Directory(records))
    private = matcher.match("St. Jarvis R-1", states=["MO"], counties=["88009"])
    assert private.target is None
    assert private.best is not None
    assert private.best.score < 0.5
    district = matcher.match("St. Jarvis R-1", states=["MO"])
    assert district.target is not None
    assert district.target.id == "SYN-MO-D"
    # One whose own name carries the number is named by it.
    numbered = matcher.index.search(
        listing_forms("St. Jarvis School District No. 2"), Scope(frozenset({"MO"}))
    )
    assert any(s.index == matcher.index.index_of("SYN-MO-U") and s.score > 0.5 for s in numbered)


def test_a_namesake_past_the_counties_that_says_more_is_a_full_rival() -> None:
    """ "Hanbury School" may mean "Hanbury Middle School 2", as it may in the counties.

    The namesake scores less, for the level and number the listing leaves out,
    but is as plausible, so the listing names neither.
    """
    others = [
        _placed(f"SYN-MA-O{i}", f"Otherby {i} Academy", "88009", _east(500)) for i in range(40)
    ]
    matcher = Matcher(
        Directory(
            [
                *others,
                _placed("SYN-MA-S", "Hanbury School", "88001", _MARKET),
                _placed("SYN-NH-S", "Hanbury Middle School 2", "88002", _east(30), state="NH"),
            ]
        )
    )
    result = matcher.match("Hanbury School", states=["MA", "NH"], counties=["88001"])
    assert result.target is None
    assert result.reason is Reason.AMBIGUOUS
    assert [c.record.id for c in result.runners_up][:1] == ["SYN-NH-S"]
    assert result.runners_up[0].score < 1.0 - MatchSettings().margin


# -- place words that begin or hold a school's name --------------------------------


def test_a_school_s_place_word_is_part_of_its_name() -> None:
    """ "Christian Academy" is not "Village Christian Academy": the word is the name's own."""
    matcher = _one_state(
        _record("SYN-S1", "VILLAGE CHRISTIAN ACADEMY", kind="school"),
        _record("SYN-S2", "TOWN & COUNTRY DAY SCHOOL", kind="school"),
        _record("SYN-S3", "CITY ACADEMY", kind="school"),
        _record("SYN-S4", "KID CITY ACADEMY", kind="school"),
        _record("SYN-D1", "Faketown City Schools"),
    )

    def match(listing: str) -> tuple[str | None, float]:
        result = matcher.match(listing, states=["UT"])
        return (result.target.id if result.target else None, result.confidence)

    for listing in ("Christian Academy", "Country Day School", "Academy", "Kids Academy"):
        target, confidence = match(listing)
        assert target is None, listing
        assert confidence < 0.8, listing
    # Said, the word names its school; the more specific listing scores higher.
    assert match("Village Christian Academy")[0] == "SYN-S1"
    assert match("Town and Country Day School")[0] == "SYN-S2"
    assert match("City Academy")[0] == "SYN-S3"
    assert match("Kid City Academy")[0] == "SYN-S4"
    assert match("Village Christian")[1] > match("Christian Academy")[1]
    # A City that ends a district's name after its town's a list may leave out.
    assert match("Faketown")[0] == "SYN-D1"
    assert match("Faketown Public Schools")[0] == "SYN-D1"


def test_a_school_s_place_kind_left_out_names_another_school() -> None:
    """ "Union High School" is not "Union City High School"; a district's City is a habit."""
    matcher = _one_state(
        _record("SYN-S1", "Brindleby City High School", kind="school"),
        _record("SYN-D1", "Brindleby City School District"),
    )
    result = matcher.match("Brindleby High School", states=["UT"])
    assert result.target is None
    assert result.confidence == pytest.approx(PLACE_LEFT_OUT)
    district = matcher.match("Brindleby Public Schools", states=["UT"])
    assert district.target is not None
    assert district.target.id == "SYN-D1"
    assert PLACE_LEFT_OUT < TOWN_LEFT_OUT


def test_a_place_word_one_name_says_and_the_other_does_not_costs_more_than_its_weight() -> None:
    matcher = _one_state(
        _record("SYN-S1", "VILLAGE CHILD DEVELOPMENT CENTER", kind="school"),
        _record("SYN-S2", "THE CHRISTIAN ACADEMY", kind="school"),
        _record("SYN-S3", "KID CITY", kind="school"),
    )
    left_out = matcher.match("Child Development Center", states=["UT"])
    assert left_out.target is None
    assert left_out.best is not None
    assert left_out.best.score < PLACE_WORD_NOT_SAID
    added = matcher.match("Village Christian Academy", states=["UT"])
    assert added.target is None
    # Said as a qualifier counts as said.
    said = matcher.match("Kid City", states=["UT"])
    assert said.target is not None
    assert said.target.id == "SYN-S3"


def test_kind_words_alone_name_only_a_school_of_that_very_name() -> None:
    """ "Christian Academy" is "The Christian Academy", never "The Academy Christian School"."""
    matcher = _one_state(
        _record("SYN-S1", "THE ACADEMY CHRISTIAN SCHOOL", kind="school"),
        _record("SYN-S2", "Montessori Elementary School", kind="school"),
        _record("SYN-S3", "CENTER FOR LEARNING INC", kind="school"),
        _record("SYN-S4", "A+ Charter Schools", kind="school"),
    )

    def match(listing: str) -> tuple[str | None, Reason, str]:
        result = matcher.match(listing, states=["UT"])
        return (result.target.id if result.target else None, result.reason, result.detail)

    for listing in ("Christian Academy", "Montessori School", "Learning Center", "Charter School"):
        target, reason, detail = match(listing)
        assert (target, reason) == (None, Reason.WEAK), listing
        assert "names only a kind of school" in detail
    assert match("Academy Christian School")[0] == "SYN-S1"
    assert match("Center for Learning")[0] == "SYN-S3"
    named = _one_state(_record("SYN-S1", "THE CHRISTIAN ACADEMY", kind="school"))
    result = named.match("Christian Academy", states=["UT"])
    assert result.target is not None
    assert result.target.id == "SYN-S1"
