"""New Jersey's townships of one name in two counties, against the real NCES directory.

New Jersey has several townships of one name, each running its own district,
and NCES writes their names as it pleases: Union County's ``"Township of Union
School District"`` and Hunterdon County's ``"Union Township School District"``,
Monmouth's ``"Township of Ocean School District"`` and Ocean County's ``"Ocean
Township School District"``, Mercer's ``"Hamilton Township Public School
District"`` and Atlantic's ``"Hamilton Township School District"``. A closings
list writes either in either word order, with ``Public`` or without, ``Twp.``
or ``Township``. None of it says which township the list means, so a listing
of the name goes to the unmatched queue with the townships' districts, unless
the listing is read in counties that hold only one, and none just past them
holds another, or a point much nearer one of them tells. A point tells only
when every other lies outside the listing's counties, or, read in the whole
state, beyond a market's reach of the point: Mercer's and Atlantic's Hamilton
Townships lie 87 km apart, and a point beside either names it; Union County's
and Hunterdon's Union Townships lie 58 km apart, both in a New York list's
counties, and a point in Union says nothing of which one a list means.
``"Township of Union"`` alone is the township's government, unless the list
files it among schools.

These tests read the directory ``snowlight directory build`` writes to
``out/internal/directory`` (never committed); they are skipped where it has not
been built.
"""

from pathlib import Path

import pytest

from snowlight.match import DirectoryRecord, Matcher, MatchResult, Reason, load_directory
from snowlight.match.index import haversine_km

DIRECTORY = Path(__file__).resolve().parents[2] / "out" / "internal" / "directory"

pytestmark = pytest.mark.skipif(
    not (DIRECTORY / "schools.parquet").exists(), reason="the NCES directory is not built here"
)

NYC_COUNTIES = ("34039", "34019", "34023", "34025", "34029", "34035")
"""Union, Hunterdon, Middlesex, Monmouth, Ocean and Somerset: New Jersey's counties
of a New York list."""

TOWNSHIPS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "Union": (
        ("3416500", "Township of Union School District", "34039"),
        ("3416440", "Union Township School District", "34019"),
    ),
    "Ocean": (
        ("3412060", "Township of Ocean School District", "34025"),
        ("3412090", "Ocean Township School District", "34029"),
    ),
    "Hamilton": (
        ("3406540", "Hamilton Township Public School District", "34021"),
        ("3406510", "Hamilton Township School District", "34001"),
    ),
    "Lawrence": (
        ("3408400", "Lawrence Township Public School District", "34021"),
        ("3408370", "Lawrence Township School District", "34011"),
    ),
    "Monroe": (
        ("3410500", "Monroe Township School District", "34023"),
        ("3410470", "Monroe Township Public School District", "34015"),
    ),
    "Franklin": (
        ("3405490", "Franklin Township Public School District", "34035"),
        ("3405460", "Franklin Township School District", "34019"),
        ("3405520", "Franklin Township School District", "34041"),
        ("3405430", "Township of Franklin School District", "34015"),
    ),
}
"""Each township's name, and the NCES id, name and county of every district of a
New Jersey township of that name."""

WORDINGS = (
    "{town} Township Public Schools",
    "{town} Township Schools",
    "{town} Township School District",
    "Township of {town} Public Schools",
    "Township of {town} School District",
    "{town} Twp. Schools",
    "{upper} TWP PUBLIC SCHOOLS",
    "{town} Twp Board of Education",
    "{town} Township Schools - All Schools",
)
"""How a list writes a township's district: either word order, the legal form or not."""

TRENTON = (40.2206, -74.7597)
"""Trenton, Mercer County: 8 km from Hamilton Township's office in Mercer, 85 km from
Atlantic County's."""
UNION_NJ = (40.6976, -74.2632)
"""Union Center, Union County: 1 km from the Township of Union's office, 60 km from
Hunterdon's Union Township's."""
BEYOND_REACH = frozenset(
    {"3406540", "3406510", "3408400", "3408370", "3410500", "3410470", "3405430"}
)
"""The townships' districts whose every namesake lies beyond a market's reach
(:attr:`~snowlight.match.MatchSettings.reach_km`) of them: Hamilton's, Lawrence's and
Monroe's, and Gloucester County's Township of Franklin."""


@pytest.fixture(scope="module")
def matcher() -> Matcher:
    """A matcher over the real directory."""
    return Matcher(load_directory(DIRECTORY))


def _record(matcher: Matcher, record_id: str) -> DirectoryRecord:
    record = matcher.directory.get(record_id)
    assert record is not None, record_id
    return record


def _ranked(result: MatchResult) -> list[str]:
    return [c.record.id for c in (result.best, *result.runners_up) if c is not None]


def _listings(town: str) -> list[str]:
    return [wording.format(town=town, upper=town.upper()) for wording in WORDINGS]


def test_the_townships_are_in_the_directory(matcher: Matcher) -> None:
    for districts in TOWNSHIPS.values():
        for record_id, name, county in districts:
            record = _record(matcher, record_id)
            assert (record.name, record.state, record.county_fips, record.kind) == (
                name,
                "NJ",
                county,
                "district",
            )
            assert matcher.expand(record_id)
    assert len(matcher.expand("3416500")) > len(matcher.expand("3416440"))


@pytest.mark.parametrize("town", sorted(TOWNSHIPS))
def test_a_township_s_name_statewide_names_none_of_them(matcher: Matcher, town: str) -> None:
    ids = {record_id for record_id, _name, _county in TOWNSHIPS[town]}
    for listing in _listings(town):
        result = matcher.match(listing, states=("NJ",))
        assert result.target is None, (listing, result.target, result.detail)
        assert result.reason is Reason.AMBIGUOUS, (listing, result.reason, result.detail)
        assert set(_ranked(result)[:2]) <= ids, (listing, _ranked(result))


@pytest.mark.parametrize("town", sorted(TOWNSHIPS))
def test_a_township_s_name_in_their_counties_names_none_of_them(
    matcher: Matcher, town: str
) -> None:
    districts = TOWNSHIPS[town]
    ids = {record_id for record_id, _name, _county in districts}
    counties = tuple(sorted({county for _id, _name, county in districts}))
    for listing in _listings(town):
        result = matcher.match(listing, states=("NJ",), counties=counties)
        assert result.target is None, (listing, result.target, result.detail)
        assert result.reason is Reason.AMBIGUOUS, (listing, result.reason, result.detail)
        assert set(_ranked(result)[:2]) <= ids, (listing, _ranked(result))


@pytest.mark.parametrize("town", sorted(TOWNSHIPS))
def test_a_new_york_list_names_none_of_them(matcher: Matcher, town: str) -> None:
    """With a New York list's counties, the word order and legal form decide nothing.

    Union's and Franklin's townships both lie in those counties; Ocean's two
    and Monroe's Middlesex County's lie in them or just past them; Hamilton's
    and Lawrence's lie beyond them, where the list names none.
    """
    for listing in _listings(town):
        result = matcher.match(listing, states=("NJ",), counties=NYC_COUNTIES)
        assert result.target is None, (listing, result.target, result.detail)


@pytest.mark.parametrize(
    ("listing", "ids"),
    [
        ("Union Township Public Schools", {"3416500", "3416440"}),
        ("Township of Union Public Schools", {"3416500", "3416440"}),
        ("Ocean Township Schools", {"3412060", "3412090"}),
        ("Township of Ocean Schools", {"3412060", "3412090"}),
    ],
)
def test_the_word_order_goes_to_the_queue_with_both(
    matcher: Matcher, listing: str, ids: set[str]
) -> None:
    """The case that let word order decide: both townships, tied, go to the queue."""
    result = matcher.match(listing, states=("NJ",), counties=NYC_COUNTIES)
    assert result.target is None, (result.target, result.detail)
    assert result.reason is Reason.AMBIGUOUS
    assert set(_ranked(result)[:2]) == ids, _ranked(result)
    assert result.best is not None
    assert result.runners_up[0].score == pytest.approx(result.best.score)


@pytest.mark.parametrize(
    ("town", "record_id"),
    [
        (town, record_id)
        for town, districts in sorted(TOWNSHIPS.items())
        for record_id, _name, _county in districts
    ],
)
def test_a_point_beside_one_names_it_when_the_rest_lie_beyond_reach(
    matcher: Matcher, town: str, record_id: str
) -> None:
    point = _record(matcher, record_id).point
    assert point is not None
    reach = matcher.settings.reach_km
    others = [other for other, _name, _county in TOWNSHIPS[town] if other != record_id]
    beyond = all(
        haversine_km(point, where) > reach
        for where in (_record(matcher, other).point for other in others)
        if where is not None
    )
    assert beyond == (record_id in BEYOND_REACH)
    for listing in _listings(town):
        result = matcher.match(listing, states=("NJ",), near=point)
        if beyond:
            assert result.target is not None, (listing, result.detail)
            assert result.target.id == record_id, (listing, result.target.id, result.detail)
            assert result.reason is Reason.NEAREST, (listing, result.reason)
        else:
            # A namesake within the market's reach: the point says nothing.
            assert result.target is None, (listing, result.target, result.detail)
            assert result.reason is Reason.AMBIGUOUS, (listing, result.reason)


def test_a_new_york_list_s_point_in_union_names_neither(matcher: Matcher) -> None:
    """Both Union Townships lie in a New York list's counties: its point says nothing."""
    for listing in (*_listings("Union"), "Union Twp"):
        result = matcher.match(listing, states=("NJ",), counties=NYC_COUNTIES, near=UNION_NJ)
        assert result.target is None, (listing, result.target, result.detail)
        assert result.reason is Reason.AMBIGUOUS, (listing, result.reason)
        assert set(_ranked(result)[:2]) == {"3416500", "3416440"}, (listing, _ranked(result))
    result = matcher.match("Union", states=("NJ",), counties=NYC_COUNTIES, near=UNION_NJ)
    assert result.target is None, result.detail
    # Its county alone holds one; Hunterdon lies just past it, much farther away.
    result = matcher.match(
        "Union Township Public Schools", states=("NJ",), counties=("34039",), near=UNION_NJ
    )
    assert result.target is not None, result.detail
    assert result.target.id == "3416500"


def test_counties_that_hold_one_leave_the_other_just_past_them(matcher: Matcher) -> None:
    """New Jersey is small: a township's namesake lies within a list's reach of its county.

    A list whose counties hold one of them may name either (see
    :meth:`~snowlight.match.matcher.Matcher._past_counties`), unless its point is
    much nearer one: Trenton's is 8 km from Mercer County's Hamilton Township
    and 85 km from Atlantic County's.
    """
    for town, districts in sorted(TOWNSHIPS.items()):
        ids = {record_id for record_id, _name, _county in districts}
        for record_id, _name, county in districts:
            result = matcher.match(f"{town} Township Schools", states=("NJ",), counties=(county,))
            assert result.target is None, (town, county, result.target, result.detail)
            assert result.reason is Reason.AMBIGUOUS, (town, county, result.reason)
            assert set(_ranked(result)[:2]) <= ids, (town, county, _ranked(result))
            assert record_id in _ranked(result)[:2], (town, county, _ranked(result))
    for listing in ("Hamilton Township Schools", "Hamilton Twp. Public Schools"):
        result = matcher.match(listing, states=("NJ",), counties=("34021",), near=TRENTON)
        assert result.target is not None, (listing, result.detail)
        assert result.target.id == "3406540", listing


@pytest.mark.parametrize("town", ["Union", "Franklin", "Lawrence"])
def test_a_township_s_bare_name_names_none_of_them(matcher: Matcher, town: str) -> None:
    """``"Union"`` is Hunterdon's Union Township as much as the town of Union's district."""
    for counties in (None, NYC_COUNTIES):
        result = matcher.match(town, states=("NJ",), counties=counties)
        assert result.target is None, (town, counties, result.target, result.detail)
    # Hunterdon's lies 58 km from Union's: within reach of a point in Union.
    result = matcher.match("Union", states=("NJ",), near=UNION_NJ)
    assert result.target is None, result.detail


def test_the_township_s_government_is_no_school_unless_filed_among_schools(
    matcher: Matcher,
) -> None:
    for category in (None, "Government", "Closings"):
        result = matcher.match(
            "Township of Union", states=("NJ",), counties=NYC_COUNTIES, category=category
        )
        assert result.target is None
        assert result.reason is Reason.NOT_SCHOOL, (category, result.reason)
    result = matcher.match(
        "Township of Union", states=("NJ",), counties=NYC_COUNTIES, category="Public Schools"
    )
    assert result.target is None
    assert result.reason is Reason.AMBIGUOUS
    assert set(_ranked(result)[:2]) == {"3416500", "3416440"}
    result = matcher.match(
        "Township of Union",
        states=("NJ",),
        counties=("34039",),
        near=UNION_NJ,
        category="Public Schools",
    )
    assert result.target is not None
    assert result.target.id == "3416500"


def test_a_township_nces_writes_without_township(matcher: Matcher) -> None:
    """Union County's Springfield is a township too, which its NCES name leaves out.

    ``"Springfield Public Schools"`` names it no more surely than Burlington
    County's ``"Springfield Township School District"``: only a point tells, the
    other lying 81 km off, beyond a market's reach.
    """
    union, burlington = "3415630", "3415660"
    for listing in ("Springfield Public Schools", "Springfield Schools", "Springfield"):
        result = matcher.match(listing, states=("NJ",))
        assert result.target is None, (listing, result.target, result.detail)
        for record_id in (union, burlington):
            point = _record(matcher, record_id).point
            result = matcher.match(listing, states=("NJ",), near=point)
            assert result.target is not None, (listing, record_id, result.detail)
            assert result.target.id == record_id, (listing, result.target.id)
