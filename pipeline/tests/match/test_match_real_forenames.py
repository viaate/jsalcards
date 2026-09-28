"""Schools named for a person, and words with a plural's ``s``, against the real NCES directory.

A list may name a school named for a person by the surname and what follows it
(``"Kennedy Middle School"``), leaving out the forenames its name begins with. NCES
writes those forenames out (``"John F Kennedy Middle"``, Waltham and Woburn) or as
initials (``"J F Kennedy Middle School"``, Natick), and a listing of the surname
weighs them alike: where both kinds share a surname and a level in one county the
listing names none of them, and goes to the queue. A word written with a plural's
``s`` on one side only is another word (``"PARKS EL"`` is no ``"Park Elementary"``).

These tests read the directory ``snowlight directory build`` writes to
``out/internal/directory`` (never committed); they are skipped where it has not
been built.
"""

from pathlib import Path

import pytest

from snowlight.match import Matcher, Reason, load_directory

DIRECTORY = Path(__file__).resolve().parents[2] / "out" / "internal" / "directory"

pytestmark = pytest.mark.skipif(
    not (DIRECTORY / "schools.parquet").exists(), reason="the NCES directory is not built here"
)

NATICK_JFK, WALTHAM_JFK, WOBURN_JFK = "250834001297", "251200001971", "251320002186"
EDINBURG_LBJ, ELSA_LBJ = "481818005462", "481806006690"
EDINBURG_GARZA, WESLACO_GARZA = "481818008285", "484496009307"
GLENDALE_WHITE, CHARLES_WHITE = "061524001949", "062271010857"
IOWA_WATSON, PEARL_WATSON = "220033000274", "220033001677"
HOUSTON_WHITE_E, EL_LAGO_WHITE, MARK_WHITE = "482364002613", "481428000915", "482364013067"
REDDING = "100008000026"


@pytest.fixture(scope="module")
def matcher() -> Matcher:
    """A matcher over the real directory."""
    return Matcher(load_directory(DIRECTORY))


@pytest.mark.parametrize(
    ("listing", "state", "county", "tied"),
    [
        ("Kennedy Middle School", "MA", "25017", {NATICK_JFK, WALTHAM_JFK, WOBURN_JFK}),
        ("Kennedy Middle", "MA", "25017", {NATICK_JFK, WALTHAM_JFK, WOBURN_JFK}),
        ("J.F. Kennedy Middle School", "MA", "25017", {NATICK_JFK, WALTHAM_JFK, WOBURN_JFK}),
        ("John F. Kennedy Middle School", "MA", "25017", {NATICK_JFK, WALTHAM_JFK, WOBURN_JFK}),
        ("John Kennedy Middle School", "MA", "25017", {NATICK_JFK, WALTHAM_JFK, WOBURN_JFK}),
        ("Johnson Elementary", "TX", "48215", {EDINBURG_LBJ, ELSA_LBJ}),
        ("L B Johnson Elementary", "TX", "48215", {EDINBURG_LBJ, ELSA_LBJ}),
        ("Garza Middle School", "TX", "48215", {EDINBURG_GARZA, WESLACO_GARZA}),
        ("White Elementary", "CA", "06037", {GLENDALE_WHITE, CHARLES_WHITE}),
        ("Watson Elementary", "LA", "22019", {IOWA_WATSON, PEARL_WATSON}),
        ("White Elementary", "TX", "48201", {HOUSTON_WHITE_E, EL_LAGO_WHITE, MARK_WHITE}),
    ],
)
def test_a_surname_two_schools_people_share_in_a_county_names_neither(
    matcher: Matcher, listing: str, state: str, county: str, tied: set[str]
) -> None:
    result = matcher.match(listing, states=[state], counties=[county])
    assert not result.accepted, result.detail
    assert result.reason is Reason.AMBIGUOUS, result.detail
    ranked = [c for c in (result.best, *result.runners_up) if c is not None]
    assert tied <= {c.record.id for c in ranked}


def test_kennedy_middle_school_scores_initials_and_forenames_alike(matcher: Matcher) -> None:
    result = matcher.match("Kennedy Middle School", states=["MA"], counties=["25017"])
    scores = {c.record.id: c.score for c in (result.best, *result.runners_up) if c is not None}
    assert scores[NATICK_JFK] == pytest.approx(scores[WALTHAM_JFK])
    assert scores[NATICK_JFK] == pytest.approx(scores[WOBURN_JFK])


@pytest.mark.parametrize(
    ("listing", "state", "county", "expected"),
    [
        ("R. D. White Elementary", "CA", "06037", GLENDALE_WHITE),
        ("Charles White Elementary", "CA", "06037", CHARLES_WHITE),
        ("B L Garza Middle School", "TX", "48215", EDINBURG_GARZA),
        ("J. I. Watson Elementary", "LA", "22019", IOWA_WATSON),
        ("Pearl Watson Elementary", "LA", "22019", PEARL_WATSON),
        ("Redding Middle School", "DE", "10003", REDDING),
    ],
)
def test_a_person_s_name_names_that_person_s_school(
    matcher: Matcher, listing: str, state: str, county: str, expected: str
) -> None:
    result = matcher.match(listing, states=[state], counties=[county])
    assert result.accepted, result.detail
    assert result.target is not None
    assert result.target.id == expected


@pytest.mark.parametrize(
    ("listing", "state", "county", "plural"),
    [
        ("Park Elementary", "TX", "48201", "PARKS EL"),
        ("Brook Elementary", "MA", "25017", "Brooks School"),
        ("Oak Elementary", "CA", "06037", "THE OAKS SCHOOL"),
        ("Lake Elementary", "MI", "26081", "Lakes Elementary School"),
        ("Grove Elementary", "TX", "48201", "GROVES EL"),
        ("Hills Elementary", "TX", "48439", "HILL EL"),
        ("Oaks Elementary", "TN", "47157", "Oak Elementary"),
        ("Lake High School", "WA", "53053", "Lakes High School"),
    ],
)
def test_a_word_a_listing_writes_with_or_without_a_plural_s_is_another(
    matcher: Matcher, listing: str, state: str, county: str, plural: str
) -> None:
    result = matcher.match(listing, states=[state], counties=[county])
    assert not (result.accepted and result.target is not None and result.target.name == plural)
    assert not result.accepted, result.detail
