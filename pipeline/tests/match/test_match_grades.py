"""School levels from grades: which level words a school's NCES grade span fits.

And how the matcher reads a school whose name leaves its level out.
"""

import pytest

from snowlight.match import Directory, DirectoryRecord, Matcher, MatchResult, Reason, lexicon
from snowlight.match.grades import GRADE_CODES, LEVEL_GRADES, Fit, fit, grade, span_of
from snowlight.match.index import LEVEL_ONLY_LISTING, levels_said
from snowlight.match.normalize import listing_forms, record_form


def test_grade_codes() -> None:
    assert grade("PK") == -1
    assert grade("KG") == grade("TK") == 0
    assert grade("T1") == grade("01") == 1
    assert grade(" 12 ") == 12
    assert grade("13") == 13
    assert grade("ug") is None
    assert grade("AE") is None
    assert grade("M") is None
    assert grade(None) is None
    assert set(GRADE_CODES) >= {"PK", "KG", "UG", *(f"{g:02d}" for g in range(1, 14))}


def test_span_of() -> None:
    assert span_of("PK", "08") == (-1, 8)
    assert span_of("KG", "KG") == (0, 0)
    # The level stands in when the grades say nothing.
    assert span_of("UG", "UG", "Elementary") == (0, 5)
    assert span_of(None, None, " Secondary ") == (9, 12)
    assert span_of("09", "05", "High") == (9, 12)
    assert span_of("09", "05") is None
    assert span_of(None, None, "Other") is None
    assert span_of(None, None) is None


def test_every_level_word_has_grades() -> None:
    assert set(LEVEL_GRADES) == set(lexicon.LEVELS)
    for (core_low, core_high), (low, high) in LEVEL_GRADES.values():
        assert low <= core_low <= core_high <= high


@pytest.mark.parametrize(
    ("levels", "span", "expected"),
    [
        # An elementary school: K-5, PK-8 (a parish school), PK-K, 3-5.
        ({"elementary"}, (0, 5), Fit.FITS),
        ({"elementary"}, (-1, 8), Fit.FITS),
        ({"elementary"}, (-1, 0), Fit.FITS),
        ({"elementary"}, (3, 5), Fit.FITS),
        # A K-12 school teaches an elementary school's grades, and far more.
        ({"elementary"}, (0, 12), Fit.SPANS),
        # A middle or a high school teaches none of them.
        ({"elementary"}, (6, 8), Fit.APART),
        ({"elementary"}, (5, 8), Fit.APART),
        ({"elementary"}, (4, 6), Fit.FITS),
        ({"elementary"}, (9, 12), Fit.APART),
        ({"middle"}, (6, 8), Fit.FITS),
        ({"middle"}, (5, 8), Fit.FITS),
        ({"middle"}, (0, 8), Fit.SPANS),
        ({"middle"}, (0, 5), Fit.APART),
        ({"juniorhigh"}, (7, 12), Fit.FITS),
        ({"juniorhigh"}, (9, 12), Fit.APART),
        ({"high"}, (9, 12), Fit.FITS),
        ({"high"}, (6, 12), Fit.FITS),
        ({"high"}, (0, 12), Fit.SPANS),
        ({"high"}, (9, 9), Fit.FITS),
        ({"primary"}, (0, 2), Fit.FITS),
        ({"primary"}, (0, 5), Fit.FITS),
        ({"intermediate"}, (3, 5), Fit.FITS),
        ({"intermediate"}, (0, 5), Fit.SPANS),
        ({"prekindergarten"}, (-1, 1), Fit.FITS),
        ({"prekindergarten"}, (-1, 8), Fit.SPANS),
        ({"prekindergarten"}, (0, 5), Fit.APART),
        ({"kindergarten"}, (0, 0), Fit.FITS),
        # Two levels: a K-8 school is both; a K-5 school only one of them.
        ({"elementary", "middle"}, (0, 8), Fit.FITS),
        ({"elementary", "middle"}, (0, 5), Fit.PART),
        ({"elementary", "high"}, (0, 12), Fit.FITS),
        # A word no level's: taught by no span.
        ({"elementary", "upper"}, (0, 5), Fit.PART),
        ({"upper"}, (0, 5), Fit.APART),
        # Unknown grades, and a listing that says no level.
        ({"elementary"}, None, Fit.UNKNOWN),
        (set(), (6, 8), Fit.FITS),
    ],
)
def test_fit(levels: set[str], span: tuple[int, int] | None, expected: Fit) -> None:
    assert fit(frozenset(levels), span) is expected


# -- the matcher ----------------------------------------------------------------------
# SYNTHETIC: schools of one name in one county, some whose names leave out the
# level their grades make them, as NCES writes Massachusetts's "Lincoln".

_COUNTY = "89501"


def _school(
    record_id: str, name: str, district: str | None, city: str, grades: tuple[str, str] | None
) -> DirectoryRecord:
    low, high = grades if grades is not None else (None, None)
    return DirectoryRecord(
        record_id,
        name,
        "school",
        district,
        "MA",
        _COUNTY,
        city,
        42.4,
        -71.1,
        grade_low=low,
        grade_high=high,
    )


def _district(record_id: str, name: str) -> DirectoryRecord:
    return DirectoryRecord(record_id, name, "district", None, "MA", _COUNTY, name, 42.4, -71.1)


def _matcher(*schools: DirectoryRecord) -> Matcher:
    districts = [_district("SYN-WIN", "Winby"), _district("SYN-MEL", "Melby")]
    return Matcher(Directory([*districts, *schools]))


_SPELLED = _school("SYN-WL", "Lincoln Elementary", "SYN-WIN", "Winby", ("KG", "05"))


def _match(matcher: Matcher, listing: str) -> MatchResult:
    return matcher.match(listing, states=["MA"], counties=[_COUNTY])


def test_a_school_of_the_level_ties_with_one_whose_name_says_it() -> None:
    matcher = _matcher(_SPELLED, _school("SYN-ML", "Lincoln", "SYN-MEL", "Melby", ("KG", "05")))
    for listing in ("Lincoln Elementary", "Lincoln Elem. School", "Lincoln School"):
        result = _match(matcher, listing)
        assert result.target is None, listing
        assert result.reason is Reason.AMBIGUOUS, listing
        assert {c.record.id for c in (result.best, *result.runners_up) if c is not None} >= {
            "SYN-WL",
            "SYN-ML",
        }
    # Its town tells them apart; so does a level the one's name says.
    named = _match(matcher, "Lincoln Elementary - Melby")
    assert named.target is not None
    assert named.target.id == "SYN-ML"
    index = matcher.index
    melby = index.index_of("SYN-ML")
    assert index.says_exactly(listing_forms("Lincoln Elementary").school, melby)
    assert index.answers_to(melby, listing_forms("Lincoln Elementary Melby").school)
    assert not index.answers_to(melby, listing_forms("Lincoln Middle").school)
    assert index.levels_apart(frozenset({"middle"}), melby)
    assert not index.levels_apart(frozenset({"elementary"}), melby)
    assert not index.levels_apart(frozenset(), melby)
    assert index.levels_apart(frozenset({"middle"}), index.index_of("SYN-WL"))


def test_a_school_of_other_grades_is_none_of_the_level() -> None:
    matcher = _matcher(_SPELLED, _school("SYN-MM", "Lincoln", "SYN-MEL", "Melby", ("06", "08")))
    elementary = _match(matcher, "Lincoln Elementary")
    assert elementary.target is not None
    assert elementary.target.id == "SYN-WL"
    assert elementary.confidence == 1.0
    middle = _match(matcher, "Lincoln Middle School")
    assert middle.target is not None
    assert middle.target.id == "SYN-MM"
    assert _match(matcher, "Lincoln High School").target is None


def test_a_school_that_teaches_far_more_is_a_rival_never_the_answer() -> None:
    whole = _school("SYN-KT", "LINCOLN SCHOOL", None, "Melby", ("KG", "12"))
    matcher = _matcher(_SPELLED, whole)
    result = _match(matcher, "Lincoln Elementary")
    assert result.target is None
    assert result.reason is Reason.AMBIGUOUS
    alone = _match(_matcher(whole), "Lincoln High School")
    assert alone.target is None
    assert alone.reason is Reason.WEAK
    assert alone.best is not None
    assert alone.best.score == pytest.approx(LEVEL_ONLY_LISTING)


def test_a_school_of_unknown_grades_is_a_rival_never_the_answer() -> None:
    unknown = _school("SYN-UN", "Lincoln", "SYN-MEL", "Melby", None)
    assert _match(_matcher(_SPELLED, unknown), "Lincoln Elementary").reason is Reason.AMBIGUOUS
    alone = _match(_matcher(unknown), "Lincoln Elementary")
    assert alone.target is None
    assert alone.best is not None
    assert alone.best.score == pytest.approx(LEVEL_ONLY_LISTING)


def test_a_school_alone_of_its_name_is_named_by_its_grades_level() -> None:
    matcher = _matcher(_school("SYN-ML", "Lincoln", "SYN-MEL", "Melby", ("KG", "05")))
    for listing in ("Lincoln Elementary", "Lincoln Primary School", "LINCOLN ES"):
        result = _match(matcher, listing)
        assert result.target is not None, listing
        assert result.target.id == "SYN-ML"
    for listing in ("Lincoln Middle School", "Lincoln High School"):
        assert _match(matcher, listing).target is None, listing


def test_levels_said() -> None:
    k5 = record_form("Lincoln", district=False)._replace(grades=(0, 5))
    k12 = k5._replace(grades=(0, 12))
    assert levels_said(frozenset({"elementary"}), k5)
    assert levels_said(frozenset(), k5)
    assert not levels_said(frozenset({"middle"}), k5)
    assert not levels_said(frozenset({"elementary"}), k12)
    assert not levels_said(frozenset({"elementary"}), k5._replace(grades=None))
    spelled = record_form("Lincoln Middle School", district=False)._replace(grades=(6, 8))
    assert levels_said(frozenset({"middle"}), spelled)
    assert not levels_said(frozenset({"elementary"}), spelled)


def test_a_campus_of_other_grades_does_not_fit() -> None:
    """A network's campus whose name says no level fits a listing of the level its grades are."""
    records = [
        DirectoryRecord(
            "SYN-N", "ORVELL ACADEMY", "district", None, "TX", "89601", "Keston", 33.0, -97.0
        ),
        DirectoryRecord(
            "SYN-NE", "ORVELL ACADEMY - KESTON", "school", "SYN-N", "TX", "89601", "Keston",
            33.0, -97.0, grade_low="KG", grade_high="05",
        ),
        DirectoryRecord(
            "SYN-NH", "ORVELL ACADEMY - BRANTLEY", "school", "SYN-N", "TX", "89601", "Brantley",
            33.1, -97.1, grade_low="09", grade_high="12",
        ),
    ]  # fmt: skip
    index = Matcher(Directory(records)).index
    positions = [index.index_of("SYN-NE"), index.index_of("SYN-NH")]
    fits = index.campuses(listing_forms("Orvell Academy Elementary"), positions, ["TX"])
    assert [(index.records[s.index].id, fit) for s, fit in fits] == [
        ("SYN-NE", True),
        ("SYN-NH", False),
    ]
