"""Kansas City's parishes and parish schools, against the real NCES directory.

Kansas City's closings lists carry churches beside schools, and a parish shares
its name with its school: the pairs below are NCES private school survey
records in the metro's counties, each the school of a parish of that name.
A church's listing (``"St. Peter's Parish: No Mass"``, ``"Christ the King Church
- services cancelled"``) must never name the school; the parish's name alone
(``"Visitation"``) names the school only when the list files it among schools;
with a school's word it names the school. The market must leave the school the
only reading: a parish school of that name just past the market's counties
(Topeka's ``"CHRIST THE KING SCHOOL"``) may as well be the list's, and the
listing goes to the queue with both.

These tests read the directory ``snowlight directory build`` writes to
``out/internal/directory`` (never committed); they are skipped where it has not
been built. The listings are written the way the Kansas City lists write them.
"""

from pathlib import Path

import pytest

from snowlight.match import Matcher, load_directory
from snowlight.match.matcher import Reason

DIRECTORY = Path(__file__).resolve().parents[2] / "out" / "internal" / "directory"

pytestmark = pytest.mark.skipif(
    not (DIRECTORY / "schools.parquet").exists(), reason="the NCES directory is not built here"
)

STATES = ("MO", "KS")
COUNTIES = ("29095", "29047", "29165", "29037", "20091", "20209")
"""Jackson, Clay, Platte and Cass in Missouri; Johnson and Wyandotte in Kansas."""

PARISH_SCHOOLS: dict[str, tuple[str, str]] = {
    "St. Peter's": ("00753495", "ST PETER'S SCHOOL"),
    "Christ the King": ("00488516", "CHRIST THE KING PARISH SCHOOL"),
    "Visitation": ("00753542", "VISITATION CATHOLIC SCHOOL"),
    "St. Elizabeth": ("00753462", "ST ELIZABETH ELEMENTARY SCHOOL"),
    "Our Lady of Unity": ("00488946", "OUR LADY OF UNITY SCHOOL"),
    "Holy Spirit": ("02120289", "HOLY SPIRIT SCHOOL"),
    "Sacred Heart": ("00488902", "SACRED HEART SCHOOL"),
    "Nativity of Mary": ("00753757", "NATIVITY OF MARY SCHOOL"),
    "Resurrection": ("00488684", "RESURRECTION CATHOLIC SCHOOL"),
    "Holy Name": ("00488593", "HOLY NAME SCHOOL"),
    "Good Shepherd": ("A9901933", "GOOD SHEPHERD SCHOOL"),
    "Ascension": ("A9901927", "ASCENSION SCHOOL"),
}
"""A parish's name, and the NCES id and name of its school."""

JUST_PAST: dict[str, tuple[str, str, str]] = {
    "St. Peter's": ("A9303320", "ST PETER CATHOLIC SCHOOL", "29195"),
    "Christ the King": ("A9701570", "CHRIST THE KING SCHOOL", "20177"),
    "Sacred Heart": ("00488935", "SACRED HEART CATHOLIC SCHOOL", "20059"),
}
"""Parish names a school just past the six counties bears too, and its NCES id, name
and county: Marshall's (Saline County, Missouri), Topeka's (Shawnee County,
Kansas) and Ottawa's (Franklin County, Kansas). A Kansas City list may name
either, so the counties leave neither the listing's."""

TOWNS_ELSEWHERE = frozenset({"St. Peter's", "St. Elizabeth"})
"""Parish names that are also towns elsewhere in Missouri (St. Peters, St.
Elizabeth): alone, they name a place, whose district is none of the market's."""

NOT_ONLY_CATHOLIC = frozenset({"Good Shepherd"})
"""Parish names other churches' schools bear too (Lutheran ``"Good Shepherd"``
schools): a school of that name whose own name says no faith is not taken for a
listing that says Catholic."""

CHURCHES = (
    "{name} Parish",
    "{name} Parish: No Mass",
    "{name} Parish - No Masses",
    "{name} Catholic Church",
    "{name} Church - services cancelled",
    "Church of {name}",
    "{name} Religious Education",
    "{name} Sunday School",
)


@pytest.fixture(scope="module")
def matcher() -> Matcher:
    """A matcher over the real directory."""
    return Matcher(load_directory(DIRECTORY))


def test_the_pairs_are_in_the_directory(matcher: Matcher) -> None:
    for school_id, name in PARISH_SCHOOLS.values():
        record = matcher.directory.get(school_id)
        assert record is not None, school_id
        assert record.name == name
        assert record.kind == "school"
        assert record.district_id is None
        assert record.county_fips in COUNTIES
    around = matcher.index.around(COUNTIES, STATES)
    for school_id, name, county in JUST_PAST.values():
        record = matcher.directory.get(school_id)
        assert record is not None, school_id
        assert record.name == name
        assert record.district_id is None
        assert record.county_fips == county
        assert county in around


@pytest.mark.parametrize("parish", sorted(PARISH_SCHOOLS))
@pytest.mark.parametrize("church", CHURCHES)
def test_a_church_never_names_its_school(matcher: Matcher, parish: str, church: str) -> None:
    listing = church.format(name=parish)
    result = matcher.match(listing, states=STATES, counties=COUNTIES)
    assert result.target is None, (listing, result.target)
    assert result.reason is Reason.NOT_SCHOOL, (listing, result.reason, result.detail)


@pytest.mark.parametrize("parish", sorted(PARISH_SCHOOLS))
@pytest.mark.parametrize("category", [None, "Churches", "Closings"])
def test_a_parish_name_alone_goes_to_the_queue(
    matcher: Matcher, parish: str, category: str | None
) -> None:
    result = matcher.match(parish, states=STATES, counties=COUNTIES, category=category)
    assert result.target is None, (parish, result.target)
    school_id, _name = PARISH_SCHOOLS[parish]
    if category is None:
        ranked = [c.record.id for c in (result.best, *result.runners_up) if c is not None]
        assert school_id in ranked, (parish, result.reason, result.detail)


@pytest.mark.parametrize("parish", sorted(set(PARISH_SCHOOLS) - TOWNS_ELSEWHERE - set(JUST_PAST)))
@pytest.mark.parametrize("category", ["Schools", "Parochial School"])
def test_a_parish_name_filed_among_schools_names_its_school(
    matcher: Matcher, parish: str, category: str
) -> None:
    result = matcher.match(parish, states=STATES, counties=COUNTIES, category=category)
    school_id, _name = PARISH_SCHOOLS[parish]
    assert result.target is not None, (parish, result.reason, result.detail)
    assert result.target.id == school_id


@pytest.mark.parametrize("parish", sorted(TOWNS_ELSEWHERE))
def test_a_parish_name_that_is_a_town_is_never_its_school(matcher: Matcher, parish: str) -> None:
    result = matcher.match(parish, states=STATES, counties=COUNTIES, category="Schools")
    assert result.target is None, (parish, result.target)
    assert result.reason is Reason.PLACE


@pytest.mark.parametrize("parish", sorted(set(PARISH_SCHOOLS) - set(JUST_PAST)))
def test_a_school_word_names_the_school(matcher: Matcher, parish: str) -> None:
    listing = f"{parish} School"
    result = matcher.match(listing, states=STATES, counties=COUNTIES)
    school_id, _name = PARISH_SCHOOLS[parish]
    assert result.target is not None, (listing, result.reason, result.detail)
    assert result.target.id == school_id


@pytest.mark.parametrize("parish", sorted(set(PARISH_SCHOOLS) - NOT_ONLY_CATHOLIC - set(JUST_PAST)))
def test_the_catholic_faith_a_saint_school_implies_may_be_said(
    matcher: Matcher, parish: str
) -> None:
    listing = f"{parish} Catholic School"
    result = matcher.match(listing, states=STATES, counties=COUNTIES)
    school_id, _name = PARISH_SCHOOLS[parish]
    assert result.target is not None, (listing, result.reason, result.detail)
    assert result.target.id == school_id


@pytest.mark.parametrize("parish", sorted(JUST_PAST))
@pytest.mark.parametrize(
    ("form", "category"),
    [
        ("{name} School", None),
        ("{name} Catholic School", None),
        ("{name} School", "Schools"),
        ("{name}", "Schools"),
    ],
)
def test_a_school_of_the_name_just_past_the_counties_sends_it_to_the_queue(
    matcher: Matcher, parish: str, form: str, category: str | None
) -> None:
    listing = form.format(name=parish)
    result = matcher.match(listing, states=STATES, counties=COUNTIES, category=category)
    assert result.target is None, (listing, result.target)
    if parish in TOWNS_ELSEWHERE and form == "{name}":
        assert result.reason is Reason.PLACE
        return
    assert result.reason is Reason.AMBIGUOUS, (listing, result.reason, result.detail)
    ranked = [c.record.id for c in (result.best, *result.runners_up) if c is not None]
    school_id, _name = PARISH_SCHOOLS[parish]
    stray_id, stray_name, _county = JUST_PAST[parish]
    assert ranked[0] == school_id
    assert stray_id in ranked
    assert stray_name in result.detail


@pytest.mark.parametrize("parish", sorted(JUST_PAST))
def test_a_school_of_the_name_in_the_counties_too_leaves_no_answer(
    matcher: Matcher, parish: str
) -> None:
    _stray_id, _name, county = JUST_PAST[parish]
    result = matcher.match(f"{parish} School", states=STATES, counties=(*COUNTIES, county))
    assert result.target is None, (parish, result.target)


@pytest.mark.parametrize("parish", sorted(NOT_ONLY_CATHOLIC))
def test_a_name_other_churches_share_needs_its_faith_in_its_name(
    matcher: Matcher, parish: str
) -> None:
    result = matcher.match(f"{parish} Catholic School", states=STATES, counties=COUNTIES)
    assert result.target is None, (parish, result.target)


@pytest.mark.parametrize(
    ("listing", "category"),
    [
        # As the Kansas City lists wrote them, in their sections.
        ("St. Marks Catholic", "Churches"),
        ("Holy Spirit Catholic Lees Summit", "Churches"),
        ("Our Lady of the Presentation Parish", "Churches"),
        ("St. Mark's Catholic Church-Independence", None),
        ("St. Margaret of Scotland Catholic Church", None),
        ("Holy Spirit Lee's Summit", None),
        ("Our Lady of Hope KC", None),
    ],
)
def test_the_lists_church_listings_name_no_school(
    matcher: Matcher, listing: str, category: str | None
) -> None:
    result = matcher.match(listing, states=STATES, counties=COUNTIES, category=category)
    assert result.target is None, (listing, result.target)
