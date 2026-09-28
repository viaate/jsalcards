"""Townships of one name in two counties of one state: what tells them apart, and what does not.

SYNTHETIC: the records are :mod:`match.handmade`'s ``TOWNSHIP_RECORDS`` (made-up
New Jersey townships such as ``"Township of Unionmere School District"`` and
``"Unionmere Township School District"``) and the townships
:meth:`match.synthetic._Generator.townships` generates; no real school.

New Jersey's NCES records write two townships' districts of one name as they
please: Union County's ``"Township of Union School District"`` and Hunterdon
County's ``"Union Township School District"``, Mercer's ``"Hamilton Township
Public School District"`` and Atlantic's ``"Hamilton Township School
District"``, Union County's ``"Springfield Public School District"`` (a
township's, ``Township`` left out) and Burlington's ``"Springfield Township
School District"``. A list writes either in either word order, with the legal
form or without, with ``Township`` or without. Which of them its words repeat
says nothing of which township it means: only a point much nearer one, or
counties that hold one and lie beyond a list's reach of the other, tells them
apart (:meth:`~snowlight.match.matcher.Matcher._exact_tie`). The real
directory's cases are in :mod:`match.test_match_real_townships`.
"""

from collections.abc import Iterable, Sequence

import pytest

from match import handmade
from match.synthetic import TOWNSHIP_NOTE, Case, SyntheticRecord
from snowlight.match import Directory, DirectoryRecord, Matcher, MatchResult, Reason, normalize
from snowlight.match import matcher as matcher_module
from snowlight.match.normalize import (
    clean_listing,
    listing_forms,
    name_first,
    not_school,
    record_form,
)

MIN_PRECISION = 0.99
MIN_RECALL = 0.95
MIN_HARD_NEGATIVES = 20


def _run(matcher: Matcher, case: Case) -> MatchResult:
    return matcher.match(
        case.listing,
        states=case.states,
        counties=case.counties,
        near=case.near,
        category=case.category,
    )


def _got(result: MatchResult) -> frozenset[str]:
    return frozenset(record.id for record in result.targets)


def _rates(matcher: Matcher, cases: Iterable[Case]) -> tuple[float, float]:
    """Precision and recall of ``matcher`` on ``cases``."""
    right = wrong = positives = 0
    for case in cases:
        got = _got(_run(matcher, case))
        positives += case.expected is not None
        if got and got == case.targets:
            right += 1
        elif got:
            wrong += 1
    precision = right / (right + wrong) if right + wrong else 1.0
    return precision, (right / positives if positives else 1.0)


def _hand_cases() -> list[Case]:
    return [
        case
        for case in handmade.CASES
        if case.note.startswith((handmade.TOWNSHIP, handmade.TOWNSHIP_NEGATIVE))
    ]


def _generated(cases: Sequence[Case]) -> list[Case]:
    return [case for case in cases if case.note == TOWNSHIP_NOTE]


def _clear_forms() -> None:
    """Empty the form caches, which an ablation of :func:`name_first` must not leave behind."""
    normalize.listing_forms.cache_clear()
    normalize._DISTRICT_FORMS.clear()
    normalize._SCHOOL_FORMS.clear()


# -- word order ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("words", "expected"),
    [
        (["township", "of", "union"], ["union", "township"]),
        (["city", "of", "baker"], ["baker", "city"]),
        (["county", "of", "winnebago"], ["winnebago", "county"]),
        (["town", "of", "webb", "union"], ["webb", "union", "town"]),
        (["borough", "of", "franklin"], ["franklin", "borough"]),
        (["township", "of"], ["township", "of"]),
        (["school", "of", "the", "arts"], ["school", "of", "the", "arts"]),
        (["union", "township"], ["union", "township"]),
        (["state", "of", "maine"], ["state", "of", "maine"]),
    ],
)
def test_name_first_puts_a_place_s_kind_after_its_name(
    words: list[str], expected: list[str]
) -> None:
    assert name_first(words) == expected


@pytest.mark.parametrize(
    ("one", "other"),
    [
        ("Township of Union School District", "Union Township School District"),
        ("Township of Ocean School District", "Ocean Township School District"),
        ("Township of Franklin School District", "Franklin Township Public School District"),
        ("City of Baker School District", "Baker City School District"),
        ("TOWN OF WEBB UNION FREE SCHOOL DISTRICT", "Webb Town UFSD"),
    ],
)
def test_a_government_s_name_is_the_same_name_either_way(one: str, other: str) -> None:
    first, second = record_form(one, district=True), record_form(other, district=True)
    assert (first.tokens, first.qualifiers, first.compact) == (
        second.tokens,
        second.qualifiers,
        second.compact,
    )
    assert not first.qualifier_first
    listing = listing_forms("Township of Union Public Schools").district
    assert listing.token_set == listing_forms("Union Township Public Schools").district.token_set
    assert listing.qualifiers == frozenset({"township"})


def test_a_kind_that_names_is_still_first() -> None:
    """``"City University Schools"`` names no city: its ``City`` is its name's."""
    form = record_form("City University Schools", district=True)
    assert form.qualifier_first
    assert record_form("County of Winnebago SD 320", district=True).numbers == frozenset({"320"})


@pytest.mark.parametrize(
    ("listing", "government"),
    [
        ("Township of Union", True),
        ("City of Monessen", True),
        ("Chester, Town of", True),
        ("Monessen City Hall", False),
        ("Sabine Pass Senior Center", False),
        ("First Baptist Church of Marion", False),
    ],
)
def test_a_civic_body_says_whether_it_is_a_government_s_name(
    listing: str, *, government: bool
) -> None:
    civic = not_school(clean_listing(listing))
    assert civic is not None
    assert civic.government is government


# -- the hand-written cases --------------------------------------------------------


def test_handmade_township_cases_are_labelled() -> None:
    cases = _hand_cases()
    negatives = [c for c in cases if c.expected is None]
    assert len(negatives) >= MIN_HARD_NEGATIVES, len(negatives)
    assert sum(1 for c in cases if c.expected is not None) >= 15
    assert sum(1 for c in cases if c.near is not None and c.expected is not None) >= 10
    listings = {(c.listing, c.counties, c.near, c.category, c.expected) for c in cases}
    # Both word orders, both NCES names, and the legal form alone, name neither.
    for listing in (
        "Unionmere Township Public Schools",
        "Township of Unionmere Public Schools",
        "Unionmere Township School District",
        "Township of Unionmere School District",
        "Lawrencemere Township Public Schools",
        "Hamilton Schools",
    ):
        assert (listing, None, None, None, None) in listings, listing
    # A point beside one names it; so do counties the other lies beyond reach of.
    assert (
        "Unionmere Township Public Schools",
        None,
        handmade.UNIONMERE_A,
        None,
        "SYN-NJ-UNIA",
    ) in listings
    assert (
        "Unionmere Twp Schools",
        (handmade.UNIONMERE_A_CO,),
        None,
        None,
        "SYN-NJ-UNIA",
    ) in listings
    # A government's name, among schools or not.
    civic = {(c.listing, c.near, c.category, c.expected) for c in handmade.CASES}
    assert ("Township of Unionmere", None, None, None) in civic
    assert ("Township of Unionmere", handmade.UNIONMERE_A, "Government", None) in civic
    # A place's name alone is either township's.
    assert ("Unionmere", None, None, None, None) in listings
    assert (
        "Township of Unionmere",
        None,
        handmade.UNIONMERE_A,
        "Public Schools",
        "SYN-NJ-UNIA",
    ) in listings


def test_handmade_township_cases_are_matched(fixture_matcher: Matcher) -> None:
    wrong = [
        (case.listing, case.counties, case.near, case.category, case.expected, result.detail)
        for case in _hand_cases()
        if _got(result := _run(fixture_matcher, case)) != case.targets
    ]
    assert not wrong


def test_the_word_order_goes_to_the_queue_with_both(handmade_matcher: Matcher) -> None:
    for listing in (
        "Unionmere Township Public Schools",
        "Township of Unionmere Public Schools",
        "Unionmere Township",
    ):
        result = handmade_matcher.match(listing, states=("NJ",))
        assert result.target is None, listing
        assert result.reason is Reason.AMBIGUOUS, (listing, result.reason)
        ranked = [c.record.id for c in (result.best, *result.runners_up) if c is not None]
        assert set(ranked[:2]) == {"SYN-NJ-UNIA", "SYN-NJ-UNIB"}, (listing, ranked)
        assert result.best is not None
        assert result.runners_up[0].score == result.best.score, listing


def test_a_government_s_name_among_schools_is_the_district_s(handmade_matcher: Matcher) -> None:
    """``"Township of Unionmere"`` filed among schools names a district, and else the township."""
    near = handmade.UNIONMERE_A
    for category in (None, "Government", "Closings"):
        result = handmade_matcher.match(
            "Township of Unionmere", states=("NJ",), near=near, category=category
        )
        assert result.reason is Reason.NOT_SCHOOL, (category, result.reason)
        assert result.best is not None
    result = handmade_matcher.match(
        "Township of Unionmere", states=("NJ",), near=near, category="Public Schools"
    )
    assert result.target is not None
    assert result.target.id == "SYN-NJ-UNIA"
    assert result.reason is Reason.NEAREST
    result = handmade_matcher.match("Township of Unionmere", states=("NJ",), category="Schools")
    assert result.target is None
    assert result.reason is Reason.AMBIGUOUS


def test_a_point_forgives_the_township_it_tells_apart(handmade_matcher: Matcher) -> None:
    """``"Springmere Schools"`` near the township that says ``Township`` is that township's."""
    for listing in ("Springmere Schools", "Springmere Public Schools", "Springmere"):
        result = handmade_matcher.match(listing, states=("NJ",), near=handmade.SPRINGMERE_B)
        assert result.target is not None, listing
        assert result.target.id == "SYN-NJ-SPRB", listing
        assert result.reason is Reason.NEAREST, listing
        assert result.confidence == 1.0, listing
    # A listing that says the word names only the district whose name says it.
    result = handmade_matcher.match(
        "Springmere Township Schools", states=("NJ",), near=handmade.SPRINGMERE_A
    )
    assert result.target is not None
    assert result.target.id == "SYN-NJ-SPRB"


def test_districts_with_no_county_are_apart_by_town() -> None:
    """Where the directory gives no county, a district's town says where it is."""

    def record(record_id: str, name: str, city: str | None) -> DirectoryRecord:
        return DirectoryRecord(record_id, name, "district", None, "NJ", None, city, None, None)

    matcher = Matcher(
        Directory(
            [
                record("SYN-D1", "Tollmere School District", "Tollmere"),
                record("SYN-D2", "Tollmere Township School District", "Tollmere"),
                record("SYN-D3", "Brackmere School District", "Brackmere"),
                record("SYN-D4", "Brackmere Township School District", "Pinemere"),
                record("SYN-D5", "Quimmere School District", None),
                record("SYN-D6", "Quimmere Township School District", None),
            ]
        )
    )
    result = matcher.match("Tollmere Schools", states=("NJ",))
    assert result.target is not None
    assert result.target.id == "SYN-D1"
    for listing in ("Brackmere Schools", "Quimmere Schools"):
        assert matcher.match(listing, states=("NJ",)).target is None, listing


# -- the generated cases -----------------------------------------------------------


def test_generated_township_cases_are_matched(
    background_matcher: Matcher, background: list[SyntheticRecord], generated_cases: list[Case]
) -> None:
    townships = [item for item in background if item.style == "township"]
    assert sum(1 for item in townships if item.record.kind == "district") >= 20
    assert any(item.record.name.startswith("Township of ") for item in townships)
    cases = _generated(generated_cases)
    assert len(cases) >= 100, len(cases)
    assert sum(1 for c in cases if c.expected is None) >= 40
    assert sum(1 for c in cases if c.expected is not None and c.near is not None) >= 20
    assert sum(1 for c in cases if c.expected is not None and c.counties is not None) >= 10
    wrong = [
        (case.listing, case.states, case.counties, case.near, case.expected, _got(result))
        for case in cases
        if _got(result := _run(background_matcher, case)) != case.targets
    ]
    assert not wrong


# -- what the fixture can see --------------------------------------------------------


def test_the_fixture_sees_wording_settle_townships_apart(
    monkeypatch: pytest.MonkeyPatch,
    fixture_matcher: Matcher,
    background_matcher: Matcher,
    generated_cases: list[Case],
) -> None:
    """Letting wording settle a tie between two counties' districts takes one of them.

    That is what the matcher did before it knew two townships of one name are
    two places whatever their names' wording (``"Hamilton Schools"`` to
    ``"Hamilton School District"`` over ``"Hamilton Township School
    District"``). The fixture has to be able to fail if it did so again.
    """
    monkeypatch.setattr(matcher_module.Matcher, "_apart", lambda *_args: False)
    hand_precision, _recall = _rates(fixture_matcher, _hand_cases())
    assert hand_precision < MIN_PRECISION - 0.1, hand_precision
    generated_precision, _recall = _rates(background_matcher, _generated(generated_cases))
    assert generated_precision < MIN_PRECISION - 0.1, generated_precision


def test_the_fixture_sees_word_order_read_as_a_name(
    monkeypatch: pytest.MonkeyPatch, fixture_directory: Directory
) -> None:
    """Read in its written order, ``"Township of Unionmere"`` begins with a name, not a place.

    Its ``Township`` then names rather than qualifies, so a listing that leaves
    it out (``"Unionmere Public Schools"``, in the district's own county) no longer
    names it; and with wording let settle a tie between counties besides, word
    order decides which township ``"Unionmere Township Public Schools"`` means,
    as it did for New Jersey's Union Township. The fixture has to fail on both.
    """
    monkeypatch.setattr(normalize, "name_first", list)
    _clear_forms()
    try:
        matcher = Matcher(fixture_directory)
        _precision, recall = _rates(matcher, _hand_cases())
        assert recall < MIN_RECALL, recall
        monkeypatch.setattr(matcher_module.Matcher, "_apart", lambda *_args: False)
        result = matcher.match("Unionmere Township Public Schools", states=("NJ",))
        assert result.target is not None
        assert result.target.id == "SYN-NJ-UNIB"
    finally:
        # Nothing read in the written order may outlive the test.
        monkeypatch.undo()
        _clear_forms()


def test_the_fixture_sees_a_point_leave_the_township_costing(
    monkeypatch: pytest.MonkeyPatch,
    fixture_matcher: Matcher,
    background_matcher: Matcher,
    generated_cases: list[Case],
) -> None:
    """Once a point tells two townships apart, the ``Township`` left out costs nothing.

    Without that, ``"Springmere Schools"`` beside Springmere's township goes to
    the queue at 0.82: the fixture has to be able to fail on it.
    """
    monkeypatch.setattr(matcher_module.Matcher, "_nearest_forgiven", lambda _self, tie, _f: tie)
    _precision, hand_recall = _rates(fixture_matcher, _hand_cases())
    assert hand_recall < MIN_RECALL, hand_recall
    _precision, generated_recall = _rates(background_matcher, _generated(generated_cases))
    assert generated_recall < MIN_RECALL, generated_recall
