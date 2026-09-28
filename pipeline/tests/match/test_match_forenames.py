"""A school named for a person, listed by its surname, and words with a plural's ``s``.

Every record here is SYNTHETIC: made-up surnames and places in NCES's shape, with
``SYN-`` ids and county codes no state uses.
"""

import pytest

from snowlight.match import Directory, DirectoryRecord, Matcher, Reason
from snowlight.match.index import FORENAMES_DIFFER, FORENAMES_LEFT_OUT, PLURAL_DIFFERS

COUNTY = "89991"
POINT = (40.0, -100.0)


def _school(
    record_id: str, name: str, *, grades: tuple[str, str, str] | None = None
) -> DirectoryRecord:
    low, high, level = grades if grades is not None else (None, None, None)
    return DirectoryRecord(
        record_id,
        name,
        "school",
        "SYN-KS-DIST",
        "KS",
        COUNTY,
        "Tamby",
        *POINT,
        grade_low=low,
        grade_high=high,
        level=level,
    )


def _matcher(*schools: DirectoryRecord) -> Matcher:
    district = DirectoryRecord(
        "SYN-KS-DIST", "Tamby USD", "district", None, "KS", COUNTY, "Tamby", *POINT
    )
    return Matcher(Directory([district, *schools]))


def _match(matcher: Matcher, listing: str) -> tuple[Reason, float, str | None]:
    result = matcher.match(listing, states=["KS"], counties=[COUNTY])
    target = result.target.id if result.accepted and result.target is not None else None
    return result.reason, result.confidence, target


@pytest.mark.parametrize(
    "name", ["J F Kennaby Middle School", "John F Kennaby Middle", "JOHN F. KENNABY MIDDLE"]
)
def test_a_surname_alone_names_a_school_whose_forenames_end_with_an_initial(name: str) -> None:
    matcher = _matcher(_school("SYN-1", name))
    reason, confidence, target = _match(matcher, "Kennaby Middle School")
    assert target == "SYN-1"
    assert reason is Reason.NAME
    assert confidence == pytest.approx(FORENAMES_LEFT_OUT)


def test_initials_and_a_spelled_forename_left_out_weigh_the_same() -> None:
    initials = _matcher(_school("SYN-1", "J F Kennaby Middle School"))
    spelled = _matcher(_school("SYN-1", "John F Kennaby Middle"))
    listing = "Kennaby Middle School"
    assert _match(initials, listing)[1] == pytest.approx(_match(spelled, listing)[1])
    both = _matcher(
        _school("SYN-1", "J F Kennaby Middle School"), _school("SYN-2", "John F Kennaby Middle")
    )
    reason, _confidence, target = _match(both, listing)
    assert target is None
    assert reason is Reason.AMBIGUOUS


def test_a_given_name_alone_is_a_rival_but_never_the_listing_s() -> None:
    alone = _matcher(_school("SYN-1", "Charles Whiteby Elementary"))
    reason, confidence, target = _match(alone, "Whiteby Elementary")
    assert target is None
    assert reason is Reason.WEAK
    assert confidence < 0.85
    beside = _matcher(
        _school("SYN-1", "R. D. Whiteby Elementary"), _school("SYN-2", "Charles Whiteby Elementary")
    )
    reason, _confidence, target = _match(beside, "Whiteby Elementary")
    assert target is None
    assert reason is Reason.AMBIGUOUS
    # Named in full, each is its own.
    assert _match(beside, "Charles Whiteby Elementary")[2] == "SYN-2"
    assert _match(beside, "R.D. Whiteby Elementary")[2] == "SYN-1"


def test_a_school_whose_name_is_the_listing_s_comes_before_one_of_a_person_s() -> None:
    for person in ("J F Kennaby Middle School", "John F Kennaby Middle", "Charles Kennaby Middle"):
        matcher = _matcher(_school("SYN-1", "Kennaby Middle School"), _school("SYN-2", person))
        reason, confidence, target = _match(matcher, "Kennaby Middle School")
        assert target == "SYN-1", person
        assert reason is Reason.NAME
        assert confidence >= 0.85


def test_an_initial_stands_for_a_forename_either_way() -> None:
    matcher = _matcher(
        _school("SYN-1", "J F Kennaby Middle School"), _school("SYN-2", "John F Kennaby Middle")
    )
    for listing in ("J.F. Kennaby Middle School", "John F. Kennaby Middle", "John Kennaby Middle"):
        reason, _confidence, target = _match(matcher, listing)
        assert target is None, listing
        assert reason is Reason.AMBIGUOUS, listing
    alone = _matcher(_school("SYN-2", "John F Kennaby Middle"))
    assert _match(alone, "J.F. Kennaby Middle School")[1] == pytest.approx(1.0)


def test_another_person_s_forenames_rule_a_school_out() -> None:
    matcher = _matcher(_school("SYN-1", "John F Kennaby Middle"))
    assert _match(matcher, "Robert Kennaby Middle School")[2] is None
    nelby = _matcher(
        _school("SYN-1", "J B Nelby Elem School"), _school("SYN-2", "V H Nelby Elem School")
    )
    reason, confidence, target = _match(nelby, "J.B. Nelby School")
    assert target == "SYN-1"
    other = nelby.match("J.B. Nelby School", states=["KS"], counties=[COUNTY]).runners_up
    assert other[0].record.id == "SYN-2"
    assert other[0].score <= FORENAMES_DIFFER
    assert reason is Reason.NAME
    assert confidence >= 0.85


def test_a_middle_initial_after_one_forename_is_no_matter() -> None:
    matcher = _matcher(_school("SYN-1", "Amelby T. Carrby Elementary"))
    assert _match(matcher, "Amelia R. Carrby Elementary")[2] is None
    amelia = _matcher(_school("SYN-1", "Amelia T. Carrby Elementary"))
    assert _match(amelia, "Amelia R. Carrby Elementary")[2] == "SYN-1"


def test_a_record_that_leaves_out_the_listing_s_initials_is_a_rival() -> None:
    matcher = _matcher(
        _school("SYN-1", "W W Walkby Elem School"),
        _school("SYN-2", "Walkby School", grades=("KG", "05", "Elementary")),
    )
    reason, _confidence, target = _match(matcher, "W.W. Walkby School")
    assert target is None
    assert reason is Reason.AMBIGUOUS
    alone = _matcher(_school("SYN-2", "Walkby School", grades=("KG", "05", "Elementary")))
    reason, confidence, target = _match(alone, "W.W. Walkby Elementary")
    assert target == "SYN-2"
    assert confidence == pytest.approx(FORENAMES_LEFT_OUT)


def test_a_surname_and_school_alone_name_no_school_of_a_person() -> None:
    """``"Pingree School"`` may be a school no directory holds, not ``"Lawrence W Pingree"``."""
    matcher = _matcher(_school("SYN-1", "Lawrence W Pingby", grades=("KG", "05", "Elementary")))
    reason, confidence, target = _match(matcher, "Pingby School")
    assert target is None
    assert reason is Reason.WEAK
    assert confidence < 0.85
    assert _match(matcher, "Pingby Elementary School")[2] == "SYN-1"
    # Still a rival for a school of the surname whose level the listing leaves out.
    beside = _matcher(
        _school("SYN-1", "Lawrence W Pingby", grades=("KG", "05", "Elementary")),
        _school("SYN-2", "Pingby Elementary School"),
    )
    reason, _confidence, target = _match(beside, "Pingby School")
    assert target is None
    assert reason is Reason.AMBIGUOUS


def test_initials_one_name_runs_together_are_one_word() -> None:
    matcher = _matcher(_school("SYN-1", "FC BOYDBY SR CHRISTIAN SCHOOL"))
    assert _match(matcher, "F.C. Boydby Christian School")[2] == "SYN-1"
    spaced = _matcher(_school("SYN-1", "F. C. Boydby Christian School"))
    assert _match(spaced, "FC Boydby Christian School")[2] == "SYN-1"


def test_forenames_nces_brackets_are_surely_a_person_s() -> None:
    matcher = _matcher(_school("SYN-1", "Burbby (Luther) Elementary"))
    _reason, confidence, target = _match(matcher, "Burbby Elementary")
    assert target == "SYN-1"
    assert confidence == pytest.approx(FORENAMES_LEFT_OUT)
    assert _match(matcher, "Luther Burbby Elementary") == (Reason.NAME, 1.0, "SYN-1")
    beside = _matcher(
        _school("SYN-1", "Kenby (John F.) Elementary"),
        _school("SYN-2", "Robert F. Kenby Elementary"),
    )
    assert _match(beside, "Kenby Elementary")[2] is None
    assert _match(beside, "John F. Kenby Elementary")[2] == "SYN-1"


def test_two_people_s_forenames_joined_by_and_are_a_rival() -> None:
    beside = _matcher(
        _school("SYN-1", "LLOYD M BENTSBY EL"), _school("SYN-2", "LLOYD & DOLLY BENTSBY EL")
    )
    reason, _confidence, target = _match(beside, "Bentsby Elementary")
    assert target is None
    assert reason is Reason.AMBIGUOUS


def test_a_grade_span_s_k_is_no_initial() -> None:
    matcher = _matcher(_school("SYN-1", "Nettie S Freedby K-8 Expeditionary School"))
    assert _match(matcher, "Expeditionary Elementary")[2] is None
    assert _match(matcher, "Freedby School")[2] is None


@pytest.mark.parametrize(
    ("record", "listing"),
    [
        ("PARKS EL", "Park Elementary"),
        ("Brooks School", "Brook School"),
        ("THE OAKS SCHOOL", "The Oak School"),
        ("Lakes Elementary School", "Lake Elementary"),
        ("Oakby Hills Elementary", "Oakby Hill Elementary"),
        ("Park Elementary", "Parks Elementary"),
    ],
)
def test_a_word_with_a_plural_s_on_one_side_only_is_another_word(record: str, listing: str) -> None:
    matcher = _matcher(_school("SYN-1", record, grades=("KG", "05", "Elementary")))
    reason, confidence, target = _match(matcher, listing)
    assert target is None
    assert reason is Reason.WEAK
    assert confidence <= PLURAL_DIFFERS + 1e-9


@pytest.mark.parametrize(
    ("record", "listing"),
    [
        ("ST MARYS SCHOOL", "St. Mary's School"),
        ("KING'S ACADEMY", "Kings Academy"),
        ("TERRY S MONTESSORI SCHOOL", "Terrys Montessori School"),
        ("SACRED HEARTS SCHOOL", "Sacred Heart School"),
        ("Clevby Arts and Social Sciences Academy", "Clevby Art & Social Science Academy"),
        ("Normby Schools Collaborative", "Normby School Collaborative"),
    ],
)
def test_possessives_devotions_and_kinds_are_no_plural(record: str, listing: str) -> None:
    matcher = _matcher(_school("SYN-1", record, grades=("KG", "05", "Elementary")))
    assert _match(matcher, listing)[2] == "SYN-1"
