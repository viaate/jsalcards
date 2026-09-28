"""Namesakes across a state line, and Kansas City's listings, against the real NCES directory.

Each state writes its NCES district names its own way. Missouri numbers its
districts (``"KANSAS CITY 33"``, Kansas City Public Schools), Kansas writes the
town alone (``"Kansas City"``, Kansas City Kansas Public Schools), Tennessee
writes ``"Bristol"`` and Virginia ``"Bristol City Public Schools"``. On a list
that covers both states, which record's name says the listing word for word,
or its legal form, or its spelling, says only how the two states write names,
not which district the listing means. So ``"Kansas City Public Schools"`` on a
Missouri and Kansas list goes to the unmatched queue with both districts,
unless the state the listing names tells them apart; an alias pins it for good.
Their offices lie 14 km apart, within a market's reach of each other
(:attr:`MatchSettings.reach_km`), so a point beside either says nothing of which
one a list of both states means.

Kansas City's other listings the owner checks by hand are here too:
``"Shawnee Mission USD512"`` is the whole Shawnee Mission district, the
private ``"Shawnee Mission Christian School"`` is that school alone, ``"Shawnee
Mission Meals on Wheels"`` is no school, and ``"Pembroke Hill"`` is the private
Pembroke Hill School.

These tests read the directory ``snowlight directory build`` writes to
``out/internal/directory`` (never committed); they are skipped where it has not
been built.
"""

import copy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from snowlight.match import (
    DirectoryRecord,
    Matcher,
    MatchResult,
    MatchSettings,
    Reason,
    load_aliases,
    load_directory,
    update_queue,
)
from snowlight.match.index import haversine_km

DIRECTORY = Path(__file__).resolve().parents[2] / "out" / "internal" / "directory"

pytestmark = pytest.mark.skipif(
    not (DIRECTORY / "schools.parquet").exists(), reason="the NCES directory is not built here"
)

KC_STATES = ("MO", "KS")
KC_COUNTIES = ("29095", "29047", "29165", "29037", "20091", "20209")
"""Jackson, Clay, Platte and Cass in Missouri; Johnson and Wyandotte in Kansas."""
KCPS, KCK = "2916400", "2007950"
"""``"KANSAS CITY 33"`` (Missouri) and ``"Kansas City"`` (Kansas)."""
KCPS_SCHOOLS, KCK_SCHOOLS = 33, 43
DOWNTOWN_KC = (39.0997, -94.5786)
"""Downtown Kansas City, Missouri: 3 km from KCPS's office, 12 km from KCK's."""
FAIRWAY = (39.0225, -94.6319)
"""Fairway, Kansas, where a Kansas City station stands: 7 km from KCPS, 14 km from KCK."""

BRISTOL_STATES = ("TN", "VA")
BRISTOL_TN, BRISTOL_VA = "4700360", "5100450"
"""``"Bristol"`` (Tennessee) and ``"Bristol City Public Schools"`` (Virginia)."""
BRISTOL = (36.5951, -82.1887)
"""State Street, on the line between the two Bristols, 1 km from each office."""
JOHNSON_CITY = (36.3134, -82.3535)

SHAWNEE_MISSION = "2011640"
SHAWNEE_MISSION_SCHOOLS = 45
SHAWNEE_MISSION_CHRISTIAN = "A0501678"
PEMBROKE_HILL = "A1902690"


@pytest.fixture(scope="module")
def matcher() -> Matcher:
    """A matcher over the real directory."""
    return Matcher(load_directory(DIRECTORY))


def _queued_with(result: MatchResult, *ids: str) -> None:
    """``result`` goes to the queue, with ``ids`` its two best candidates."""
    assert result.target is None, (result.listing, result.target, result.detail)
    assert result.reason is Reason.AMBIGUOUS, (result.listing, result.reason, result.detail)
    ranked = [c.record.id for c in (result.best, *result.runners_up) if c is not None]
    assert set(ranked[:2]) == set(ids), (result.listing, ranked)


def _record(matcher: Matcher, record_id: str) -> DirectoryRecord:
    record = matcher.directory.get(record_id)
    assert record is not None, record_id
    return record


def test_the_namesakes_are_in_the_directory(matcher: Matcher) -> None:
    for record_id, name, state in (
        (KCPS, "KANSAS CITY 33", "MO"),
        (KCK, "Kansas City", "KS"),
        (BRISTOL_TN, "Bristol", "TN"),
        (BRISTOL_VA, "Bristol City Public Schools", "VA"),
    ):
        record = _record(matcher, record_id)
        assert (record.name, record.state, record.kind) == (name, state, "district")
    assert len(matcher.expand(KCPS)) == KCPS_SCHOOLS
    assert len(matcher.expand(KCK)) == KCK_SCHOOLS


@pytest.mark.parametrize(
    "listing",
    [
        "Kansas City Public Schools",
        "Kansas City Schools",
        "Kansas City School District",
        "KANSAS CITY PUBLIC SCHOOLS",
        "Kansas City Public Schools - All Schools",
        "Kansas City",
    ],
)
@pytest.mark.parametrize(
    ("counties", "near"),
    [
        (None, None),
        (None, DOWNTOWN_KC),
        (KC_COUNTIES, None),
        (KC_COUNTIES, DOWNTOWN_KC),
        (("29095", "20209"), DOWNTOWN_KC),
        (KC_COUNTIES, FAIRWAY),
    ],
)
def test_kansas_city_on_a_list_of_both_states_goes_to_the_queue(
    matcher: Matcher,
    listing: str,
    counties: tuple[str, ...] | None,
    near: tuple[float, float] | None,
) -> None:
    # Never Kansas's district because its name says the listing's words and
    # Missouri's adds a number; a point in the metro is not much nearer either.
    result = matcher.match(listing, states=KC_STATES, counties=counties, near=near)
    _queued_with(result, KCPS, KCK)


def test_a_point_at_one_kansas_city_says_nothing_of_the_other_within_reach(
    matcher: Matcher,
) -> None:
    settings = matcher.settings
    kcps, kck = _record(matcher, KCPS).point, _record(matcher, KCK).point
    assert kcps is not None
    assert kck is not None
    apart = haversine_km(kcps, kck)
    assert settings.near_slack_km < apart < settings.reach_km
    for expected in (KCPS, KCK):
        office = _record(matcher, expected).point
        assert office is not None
        result = matcher.match("Kansas City Public Schools", states=KC_STATES, near=office)
        _queued_with(result, KCPS, KCK)
        # The reach decides: shorter than the distance between them, the point
        # beside one tells them apart, as the ratio and slack allow.
        short = copy.copy(matcher)
        short.settings = MatchSettings(reach_km=apart - 1.0)
        nearest = short.match("Kansas City Public Schools", states=KC_STATES, near=office)
        assert nearest.target is not None, (office, nearest.detail)
        assert nearest.target.id == expected
        assert nearest.reason is Reason.NEAREST
        strict = copy.copy(short)
        strict.settings = MatchSettings(reach_km=apart - 1.0, near_slack_km=40.0)
        again = strict.match("Kansas City Public Schools", states=KC_STATES, near=office)
        _queued_with(again, KCPS, KCK)


@pytest.mark.parametrize(
    ("listing", "states", "expected"),
    [
        # One state searched: that state's district.
        ("Kansas City Public Schools", ("MO",), KCPS),
        ("Kansas City Public Schools", ("KS",), KCK),
        # The state the listing names.
        ("Kansas City MO Public Schools", KC_STATES, KCPS),
        ("Kansas City, Missouri Public Schools", KC_STATES, KCPS),
        ("Kansas City Kansas Public Schools", KC_STATES, KCK),
        ("Kansas City KS Public Schools", KC_STATES, KCK),
        ("Kansas City, Kansas Public Schools", KC_STATES, KCK),
        # Missouri's number.
        ("Kansas City 33", KC_STATES, KCPS),
    ],
)
def test_kansas_city_named_by_its_state_or_number(
    matcher: Matcher, listing: str, states: tuple[str, ...], expected: str
) -> None:
    result = matcher.match(listing, states=states, near=DOWNTOWN_KC)
    assert result.target is not None, (listing, result.reason, result.detail)
    assert [t.id for t in result.targets] == [expected], (listing, result.detail)


@pytest.mark.parametrize(
    "listing",
    ["Bristol", "Bristol City Schools", "Bristol Public Schools", "Bristol City Public Schools"],
)
@pytest.mark.parametrize("near", [None, BRISTOL, JOHNSON_CITY])
def test_bristol_on_a_list_of_both_states_goes_to_the_queue(
    matcher: Matcher, listing: str, near: tuple[float, float] | None
) -> None:
    # Never Tennessee's because its name is the town's alone, nor Virginia's
    # because its name says "City Public Schools": the two offices are 1 km apart.
    result = matcher.match(listing, states=BRISTOL_STATES, near=near)
    _queued_with(result, BRISTOL_TN, BRISTOL_VA)


@pytest.mark.parametrize(
    ("listing", "states", "expected"),
    [
        ("Bristol", ("TN",), BRISTOL_TN),
        ("Bristol City Schools", ("VA",), BRISTOL_VA),
        ("Bristol Tennessee City Schools", BRISTOL_STATES, BRISTOL_TN),
        ("Bristol TN City Schools", BRISTOL_STATES, BRISTOL_TN),
        ("Bristol Virginia Public Schools", BRISTOL_STATES, BRISTOL_VA),
        ("Bristol VA Public Schools", BRISTOL_STATES, BRISTOL_VA),
    ],
)
def test_bristol_named_by_its_state(
    matcher: Matcher, listing: str, states: tuple[str, ...], expected: str
) -> None:
    result = matcher.match(listing, states=states, near=BRISTOL)
    assert result.target is not None, (listing, result.reason, result.detail)
    assert [t.id for t in result.targets] == [expected], (listing, result.detail)


def test_the_queue_carries_both_namesakes_and_an_alias_pins_one(
    matcher: Matcher, tmp_path: Path
) -> None:
    listing = "Kansas City Public Schools"
    result = matcher.match(listing, states=KC_STATES, near=DOWNTOWN_KC, market="kmbc")
    queue = update_queue(tmp_path / "queue.json", [result], now=datetime(2026, 1, 5, tzinfo=UTC))
    (entry,) = queue.entries
    assert entry.reason == Reason.AMBIGUOUS.value
    assert {c.id for c in entry.candidates[:2]} == {KCPS, KCK}
    assert {c.state for c in entry.candidates[:2]} == {"MO", "KS"}
    aliases = tmp_path / "aliases.yaml"
    aliases.write_text(
        f'schema_version: 1\nmarkets:\n  kmbc:\n    "{listing}": "{KCPS}"\n', encoding="utf-8"
    )
    pinned = copy.copy(matcher)
    pinned.aliases = load_aliases(aliases)
    result = pinned.match(listing, states=KC_STATES, near=DOWNTOWN_KC, market="kmbc")
    assert result.reason is Reason.ALIAS
    assert [t.id for t in result.targets] == [KCPS]
    assert len(pinned.expand(result)) == KCPS_SCHOOLS


def test_shawnee_mission_usd_512_is_the_whole_district(matcher: Matcher) -> None:
    for near in (None, DOWNTOWN_KC):
        for listing in ("Shawnee Mission USD512", "Shawnee Mission USD 512"):
            result = matcher.match(listing, states=KC_STATES, counties=KC_COUNTIES, near=near)
            assert [t.id for t in result.targets] == [SHAWNEE_MISSION], (listing, result.detail)
            schools = matcher.expand(result)
            assert len(schools) == SHAWNEE_MISSION_SCHOOLS
            assert "Prairie Elem" in {school.name for school in schools}


def test_shawnee_mission_christian_school_is_that_school_alone(matcher: Matcher) -> None:
    result = matcher.match(
        "Shawnee Mission Christian School",
        states=KC_STATES,
        counties=KC_COUNTIES,
        near=DOWNTOWN_KC,
    )
    assert [t.id for t in result.targets] == [SHAWNEE_MISSION_CHRISTIAN], result.detail
    assert [s.id for s in matcher.expand(result)] == [SHAWNEE_MISSION_CHRISTIAN]


@pytest.mark.parametrize("category", [None, "Closings", "Business"])
def test_shawnee_mission_meals_on_wheels_is_no_school(
    matcher: Matcher, category: str | None
) -> None:
    result = matcher.match(
        "Shawnee Mission Meals on Wheels",
        states=KC_STATES,
        counties=KC_COUNTIES,
        near=DOWNTOWN_KC,
        category=category,
    )
    assert result.target is None, (result.target, result.detail)
    assert result.reason is Reason.NOT_SCHOOL
    assert matcher.expand(result) == ()


@pytest.mark.parametrize(
    "listing", ["Pembroke Hill", "Pembroke Hill School", "The Pembroke Hill School"]
)
def test_pembroke_hill_is_the_private_school(matcher: Matcher, listing: str) -> None:
    result = matcher.match(listing, states=KC_STATES, counties=KC_COUNTIES, near=DOWNTOWN_KC)
    assert [t.id for t in result.targets] == [PEMBROKE_HILL], (listing, result.detail)
    assert [s.id for s in matcher.expand(result)] == [PEMBROKE_HILL]
