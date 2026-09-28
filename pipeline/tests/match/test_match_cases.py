"""Labelled listings: the hand-written hard cases and the generated ones.

Precision and recall are measured at the configured threshold on both sets: a
listing counts as a true positive when the matcher accepts the expected records
(one, or every district of a school system NCES splits, see
:attr:`~match.synthetic.Case.targets`), a false positive when it accepts
anything else (or anything at all where the answer is "no match"; one district
of a system where the listing names all of them, or all where it names one), and
a false negative when it accepts nothing where a record was expected.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import pytest

from match import handmade
from match.synthetic import (
    ACADEMY_NOTE,
    ACROSS_NOTE,
    BORDER_NOTE,
    BRACKET_NOTE,
    CODE_NOTE,
    COUNTY_BRACKET_STATES,
    DIRECTION_NOTE,
    ENTITY_NUMBER_STATES,
    FORENAME_NEGATIVE,
    FORENAME_NOTE,
    LEADING_NEGATIVE,
    LEADING_NOTE,
    LEVEL_NEGATIVE,
    LEVEL_NOTE,
    MUNICIPAL_NOTE,
    NAMESAKE_NOTE,
    NETWORK_NOTE,
    PARISH_NOTE,
    PLACE_NOTE,
    PLURAL_NEGATIVE,
    PLURAL_NOTE,
    SECOND_NAME_STATES,
    STATE_NOTE,
    STRADDLE_NOTE,
    TOWN_PRIVATE_FORMS,
    Case,
    SyntheticRecord,
)
from snowlight.match import (
    Directory,
    DirectoryRecord,
    Matcher,
    MatchResult,
    MatchSettings,
    index,
    lexicon,
    normalize,
    states,
)
from snowlight.match import matcher as matcher_module
from snowlight.match.grades import Fit

MIN_PRECISION = 0.99
MIN_RECALL = 0.95
MIN_HARD_NEGATIVES = 20

# "<Town> Catholic Schools", "<Town> Christian School", "<Town> Lutheran": a faith
# beside a town's name.
_FAITH_BESIDE_TOWN = re.compile(
    r"(?P<town>.+?) (?:Catholic|Christian|Lutheran|Baptist|Jewish|Islamic|Episcopal"
    r"|Adventist|Mennonite|Montessori)\b",
    re.IGNORECASE,
)
_COLLEGE = re.compile(r"\b(?:College|University|Univ\.|Seminary)\b", re.IGNORECASE)
# A town's government, community places, hospitals and churches.
_CIVIC = re.compile(
    r"^(?:City|Town|Village|Borough|Township) of\b"
    r"|,\s*(?:City|Town|Village|Borough|Township) of\b"
    r"|\b(?:City|Town|Village) (?:Hall|Offices|Council|Clerk)\b"
    r"|\b(?:Senior Center|Sr\. Citizens|Community Center|Library|Hospital|Health Center|Church"
    r"|Police|Fire"
    r"|Department|Authority|YMCA|Recreation|Meals on Wheels|Municipal)\b",
    re.IGNORECASE,
)
# A district named for its town as a city, a village or a town.
_MUNICIPAL_DISTRICT = re.compile(r"(?P<town>.+?) (?:City|Exempted Village|Town)\b", re.IGNORECASE)
# A listing that begins with a district code: "RSU 13", "M.S.A.D. #17", "USD 320",
# "Regional School Unit 13", "D-3", "RE-2", "AOS 98".
_LEADING_CODE = re.compile(
    r"^(?:R\.?S\.?U\.?|M\.?S\.?A\.?D\.?|S\.?A\.?D\.?|U\.?S\.?D\.?|A\.?O\.?S\.?"
    r"|Regional School Unit|Maine School Administrative District|RE?-|D-)\s*#?\s*\d",
    re.IGNORECASE,
)

# A listing that begins with an abbreviated direction: "E. Lansing", "No. Little Rock".
_ABBREVIATED_DIRECTION = re.compile(r"^(?:N|S|E|W|NE|NW|SE|SW|No|So)\.? ", re.IGNORECASE)


def _case_id(case: Case) -> str:
    where = ",".join(case.states)
    if case.counties:
        where += ":" + ",".join(case.counties)
    if case.near:
        where += "@near"
    if case.category:
        where += f"[{case.category}]"
    return f"{case.listing}|{where}"


def _run(matcher: Matcher, case: Case) -> MatchResult:
    return matcher.match(
        case.listing,
        states=case.states,
        counties=case.counties,
        near=case.near,
        category=case.category,
    )


@dataclass(frozen=True)
class Tally:
    true_positives: int
    false_positives: int
    false_negatives: int
    positives: int

    @property
    def precision(self) -> float:
        accepted = self.true_positives + self.false_positives
        return self.true_positives / accepted if accepted else 1.0

    @property
    def recall(self) -> float:
        return self.true_positives / self.positives if self.positives else 1.0


def _targets(result: MatchResult) -> frozenset[str]:
    """The ids a result names: its target's, and the rest of a system's."""
    return frozenset(record.id for record in result.targets)


def _tally(outcomes: Iterable[tuple[Case, MatchResult]]) -> Tally:
    tp = fp = fn = positives = 0
    for case, result in outcomes:
        got = _targets(result)
        positives += case.expected is not None
        if not got:
            fn += case.expected is not None
        elif got == case.targets:
            tp += 1
        else:
            fp += 1
    return Tally(tp, fp, fn, positives)


def _district_towns(records: Iterable[DirectoryRecord]) -> dict[str, set[str]]:
    """Per state, the towns that have a public district named for them."""
    towns: dict[str, set[str]] = {}
    for record in records:
        city = record.city
        if record.kind == "district" and city and city.casefold() in record.name.casefold():
            towns.setdefault(record.state, set()).add(city.casefold())
    return towns


def _faith_negatives(cases: Iterable[Case], records: Iterable[DirectoryRecord]) -> list[Case]:
    """Hard negatives that name a faith beside the town of a public district named for it."""
    towns = _district_towns(records)
    found: list[Case] = []
    for case in cases:
        faith = _FAITH_BESIDE_TOWN.match(case.listing)
        if case.expected is None and faith is not None:
            town = faith["town"].casefold()
            if any(town in towns.get(state, ()) for state in case.states):
                found.append(case)
    return found


def _towns(case: Case) -> set[str]:
    """The words of a college listing that could be its town."""
    words = case.listing.casefold().replace(".", " ").split()
    return {w for w in words if w not in {"college", "university", "univ", "of", "state"}}


def _college_negatives(cases: Iterable[Case], records: Sequence[DirectoryRecord]) -> list[Case]:
    """Hard negatives that name a college or university for a town with a public district."""
    towns = _district_towns(records)
    return [
        case
        for case in cases
        if case.expected is None
        and _COLLEGE.search(case.listing)
        and any(
            town in case.listing.casefold()
            for state in case.states
            for town in towns.get(state, ())
        )
    ]


def _municipal_towns(records: Iterable[DirectoryRecord]) -> dict[str, set[str]]:
    """Per state, the towns a district is named for as a city, a village or a town."""
    towns: dict[str, set[str]] = {}
    for record in records:
        named = _MUNICIPAL_DISTRICT.match(record.name)
        if record.kind == "district" and named is not None:
            towns.setdefault(record.state, set()).add(named["town"].casefold())
    return towns


def _civic_negatives(cases: Iterable[Case], records: Iterable[DirectoryRecord]) -> list[Case]:
    """Hard negatives naming a civic body in a town whose district is "<town> City" and the like.

    And a town's government a list writes the way a directory sorts it
    (``"Ashfield, Town of"``), beside the district named for the town
    (:data:`~match.synthetic.MUNICIPAL_NOTE`).
    """
    towns = _municipal_towns(records)
    return [
        case
        for case in cases
        if case.expected is None
        and _CIVIC.search(case.listing)
        and (
            case.note == MUNICIPAL_NOTE
            or any(
                town in case.listing.casefold()
                for state in case.states
                for town in towns.get(state, ())
            )
        )
    ]


def _code_cases(cases: Iterable[Case]) -> tuple[list[Case], list[Case]]:
    """The listings that begin with a district code: those that name a record, those that do not."""
    coded = [case for case in cases if _LEADING_CODE.match(case.listing)]
    return (
        [case for case in coded if case.expected is not None],
        [case for case in coded if case.expected is None],
    )


def _direction_cases(cases: Iterable[Case]) -> tuple[list[Case], list[Case]]:
    """The listings that say a direction: those that name a record, those that do not."""
    said = [
        case
        for case in cases
        if case.note in {handmade.DIRECTION, DIRECTION_NOTE}
        or case.note.startswith(handmade.DIRECTION_NEGATIVE)
    ]
    return (
        [case for case in said if case.expected is not None],
        [case for case in said if case.expected is None],
    )


def _no_codes(words: list[str]) -> normalize.DistrictCodes:
    """The normalizer before it read district codes: every word is a name word."""
    return normalize.DistrictCodes(words, frozenset(), frozenset(), coded=False)


@pytest.mark.parametrize("case", handmade.CASES, ids=_case_id)
def test_handmade_case(fixture_matcher: Matcher, case: Case) -> None:
    result = _run(fixture_matcher, case)
    got = _targets(result)
    assert got == case.targets, (
        f"{case.note or 'expected'}: {result.reason} {result.confidence} {result.detail}"
    )
    if not got:
        assert result.confidence < MatchSettings().threshold
    else:
        assert result.confidence >= MatchSettings().threshold


def test_handmade_cases_cover_the_bar() -> None:
    cases = handmade.CASES
    negatives = [c for c in cases if c.expected is None]
    assert len(cases) >= 120
    assert len(negatives) >= 40
    assert len({(c.listing, c.states, c.counties, c.near, c.category) for c in cases}) == len(cases)
    listings = {(c.listing, c.states, c.counties, c.expected) for c in cases}
    # The hard negatives the bar names.
    assert ("Lancaster SD", ("OH",), None, None) in listings
    assert ("Lancaster Schools", ("SC",), None, None) in listings
    assert ("Lancaster County Schools", ("PA",), None, "SYN-PA-LANCO") in listings
    assert ("St. Mary's School", ("PA",), ("80103",), None) in listings
    assert ("St. Mary's School", ("NY",), ("80301",), None) in listings
    ids = {record.id for record in handmade.RECORDS}
    assert all(c.expected is None or c.expected in ids for c in cases)
    assert all(record.id.startswith("SYN-") for record in handmade.RECORDS)


def test_handmade_cases_name_faiths_and_colleges_beside_districts() -> None:
    """A faith or a college beside a district's town: never the public district."""
    cases = handmade.CASES
    faiths = _faith_negatives(cases, handmade.RECORDS)
    assert len(faiths) >= MIN_HARD_NEGATIVES, [c.listing for c in faiths]
    groups = [c for c in faiths if re.search(r"\bSchools\b", c.listing)]
    assert len(groups) >= MIN_HARD_NEGATIVES
    colleges = _college_negatives(cases, handmade.RECORDS)
    assert len(colleges) >= 8
    listings = {(c.listing, c.states, c.expected) for c in cases}
    # "Brackenmoor College" and "Brackenmoor University" sit beside the district
    # "Brackenmoor" and the K-12 schools named for the college and the university.
    assert ("Brackenmoor College", ("MA",), None) in listings
    assert ("Brackenmoor University", ("MA",), None) in listings
    assert ("Brackenmoor College High School", ("MA",), "SYN-MA-BRCHS") in listings
    assert ("Brackenmoor University Academy", ("MA",), "SYN-MA-BRUA") in listings
    assert ("Brackenmoor Public Schools", ("MA",), "SYN-MA-BRAK") in listings


def test_handmade_cases_name_civic_bodies_beside_districts() -> None:
    """A town's city hall or senior center beside its "<town> City": never the district."""
    cases = handmade.CASES
    civic = _civic_negatives(cases, handmade.RECORDS)
    assert len(civic) >= MIN_HARD_NEGATIVES, [c.listing for c in civic]
    listings = {(c.listing, c.states, c.expected) for c in cases}
    assert ("City of Kettleby", ("OH",), None) in listings
    assert ("Village of Farrowdale", ("OH",), None) in listings
    assert ("Town of Harlowe", ("VT",), None) in listings
    # The districts beside them still match.
    assert ("Kettleby City Schools", ("OH",), "SYN-OH-KETC") in listings
    assert ("Farrowdale Exempted Village Schools", ("OH",), "SYN-OH-FARR") in listings
    assert ("Harlowe Town School District", ("VT",), "SYN-VT-HARL") in listings
    # A district whose own name begins "City of", and a town named for a church.
    assert ("City of Marlowe", ("LA",), None) in listings
    assert ("City of Marlowe Schools", ("LA",), "SYN-LA-MARL") in listings
    assert ("Millers Church", ("VA",), "SYN-VA-MILCH") in listings


def test_handmade_cases_begin_with_district_codes() -> None:
    """Codes before the name, on both sides of the threshold."""
    named, unnamed = _code_cases(handmade.CASES)
    assert len(named) >= MIN_HARD_NEGATIVES, [c.listing for c in named]
    assert len(unnamed) >= MIN_HARD_NEGATIVES, [c.listing for c in unnamed]
    listings = {(c.listing, c.states, c.expected) for c in handmade.CASES}
    # A code alone, a code and the district's area, a code and one of its schools.
    assert ("RSU 84", ("ME",), "SYN-ME-RSU84") in listings
    assert ("RSU 84 - Seacliff", ("ME",), "SYN-ME-RSU84") in listings
    assert ("RSU 84 Seacliff High School", ("ME",), "SYN-ME-SEAHS") in listings
    assert ("USD 431 Wendham", ("KS",), "SYN-KS-WEND") in listings
    # The other series, a program, a school of a unit the code does not name.
    assert ("MSAD 84", ("ME",), "SYN-ME-RSU93") in listings
    assert ("RSU 84 - Adult Education", ("ME",), None) in listings
    assert ("RSU 84 Lincoln School", ("ME",), None) in listings


def test_generated_cases_are_mixed(generated_cases: list[Case]) -> None:
    notes = {case.note for case in generated_cases}
    assert notes >= {
        "own county",
        "own state",
        "other state",
        "other county",
        "changed level or number",
        "left something out",
        "faith and town",
        "college or university",
        "civic body",
        CODE_NOTE,
        DIRECTION_NOTE,
        PLACE_NOTE,
        NETWORK_NOTE,
        STRADDLE_NOTE,
        ACADEMY_NOTE,
        LEADING_NOTE,
        LEADING_NEGATIVE,
        FORENAME_NOTE,
        FORENAME_NEGATIVE,
        PLURAL_NOTE,
        PLURAL_NEGATIVE,
    }
    positives = sum(case.expected is not None for case in generated_cases)
    assert 0.5 * len(generated_cases) < positives < 0.9 * len(generated_cases)


def test_generated_cases_name_faiths_and_colleges_beside_districts(
    background: list[SyntheticRecord], generated_cases: list[Case]
) -> None:
    records = [item.record for item in background]
    faiths = _faith_negatives(generated_cases, records)
    assert len(faiths) >= MIN_HARD_NEGATIVES
    colleges = _college_negatives(generated_cases, records)
    assert len(colleges) >= MIN_HARD_NEGATIVES
    # Some of the colleges share their town with a "College High School".
    college_high = {
        (r.state, r.city.casefold())
        for r in records
        if r.city and "college high school" in r.name.casefold()
    }
    beside = [
        c for c in colleges if any((s, t) in college_high for s in c.states for t in _towns(c))
    ]
    assert len(beside) >= 5
    # A faith beside a town is sometimes a private school's own name: that one matches.
    assert any(c.note == "faith and town" and c.expected is not None for c in generated_cases)


def test_generated_cases_begin_with_district_codes(generated_cases: list[Case]) -> None:
    coded = [case for case in generated_cases if case.note == CODE_NOTE]
    named, unnamed = _code_cases(coded)
    assert len(named) >= MIN_HARD_NEGATIVES
    assert len(unnamed) >= MIN_HARD_NEGATIVES
    # Codes of both of Maine's series and Kansas's, before a district and a school.
    listings = " ".join(case.listing for case in coded)
    for code in ("RSU", "MSAD", "USD", "AOS"):
        assert code in listings, code


def test_generated_cases_name_civic_bodies_beside_districts(
    background: list[SyntheticRecord], generated_cases: list[Case]
) -> None:
    records = [item.record for item in background]
    civic = _civic_negatives(generated_cases, records)
    assert len(civic) >= MIN_HARD_NEGATIVES
    assert all(c.note in {"civic body", MUNICIPAL_NOTE} for c in civic)
    # Each kind of district the bar names has its government beside it.
    for government in ("City of ", "Village of ", "Town of "):
        assert sum(c.listing.startswith(government) for c in civic) >= 3, government


def test_precision_and_recall(
    fixture_matcher: Matcher, background_matcher: Matcher, generated_cases: list[Case]
) -> None:
    hand = _tally((case, _run(fixture_matcher, case)) for case in handmade.CASES)
    generated = _tally((case, _run(background_matcher, case)) for case in generated_cases)
    combined = Tally(
        hand.true_positives + generated.true_positives,
        hand.false_positives + generated.false_positives,
        hand.false_negatives + generated.false_negatives,
        hand.positives + generated.positives,
    )
    for name, tally in (("hand-written", hand), ("generated", generated), ("all", combined)):
        assert tally.precision >= MIN_PRECISION, f"{name}: {tally}"
        assert tally.recall >= MIN_RECALL, f"{name}: {tally}"


def test_the_threshold_is_what_holds_precision(
    background_matcher: Matcher, generated_cases: list[Case]
) -> None:
    """Accepting everything the matcher ranks first would cost precision."""
    loose = Matcher(background_matcher.directory, settings=MatchSettings(threshold=0.3))
    tally = _tally((case, _run(loose, case)) for case in generated_cases)
    assert tally.precision < MIN_PRECISION


def test_the_fixture_sees_an_affiliation_leak(
    monkeypatch: pytest.MonkeyPatch,
    fixture_matcher: Matcher,
    background_matcher: Matcher,
    generated_cases: list[Case],
) -> None:
    """With affiliations costing nothing, "<Town> Catholic Schools" takes the town's district.

    The fixture has to be able to fail on that bug, so turning the rule off must
    push precision under the bar on both sets.
    """
    monkeypatch.setattr(index, "AFFILIATION_NOT_SAID", 1.0)
    hand = _tally((case, _run(fixture_matcher, case)) for case in handmade.CASES)
    generated = _tally((case, _run(background_matcher, case)) for case in generated_cases)
    assert hand.precision < MIN_PRECISION
    assert generated.precision < MIN_PRECISION
    leaked = [
        case
        for case in _faith_negatives(handmade.CASES, handmade.RECORDS)
        if _run(fixture_matcher, case).target is not None
    ]
    assert len(leaked) >= MIN_HARD_NEGATIVES // 2


def test_the_fixture_sees_a_college_leak(
    monkeypatch: pytest.MonkeyPatch,
    fixture_matcher: Matcher,
    background_matcher: Matcher,
    background: list[SyntheticRecord],
    generated_cases: list[Case],
) -> None:
    """Without the college check, "<Town> College" takes "<Town> College High School"."""
    monkeypatch.setattr(matcher_module, "non_k12", lambda _clean: None)
    hand = [
        case
        for case in _college_negatives(handmade.CASES, handmade.RECORDS)
        if _run(fixture_matcher, case).target is not None
    ]
    records = [item.record for item in background]
    generated = [
        case
        for case in _college_negatives(generated_cases, records)
        if _run(background_matcher, case).target is not None
    ]
    assert hand
    assert len(generated) >= 5


def test_the_fixture_sees_a_civic_leak(
    monkeypatch: pytest.MonkeyPatch,
    fixture_matcher: Matcher,
    background_matcher: Matcher,
    background: list[SyntheticRecord],
    generated_cases: list[Case],
) -> None:
    """Without the civic check, "City of <town>" takes the district "<town> City".

    The fixture has to be able to fail on that bug: turning the check off must
    push precision under the bar on both sets.
    """
    monkeypatch.setattr(matcher_module, "not_school", lambda _clean: None)
    hand = [
        case
        for case in _civic_negatives(handmade.CASES, handmade.RECORDS)
        if _run(fixture_matcher, case).target is not None
    ]
    records = [item.record for item in background]
    generated = [
        case
        for case in _civic_negatives(generated_cases, records)
        if _run(background_matcher, case).target is not None
    ]
    assert len(hand) >= MIN_HARD_NEGATIVES // 2, [c.listing for c in hand]
    assert len(generated) >= MIN_HARD_NEGATIVES, [c.listing for c in generated]
    assert {c.listing.split()[0] for c in hand} >= {"City", "Village", "Town"}
    hand_tally = _tally((case, _run(fixture_matcher, case)) for case in handmade.CASES)
    generated_tally = _tally((case, _run(background_matcher, case)) for case in generated_cases)
    assert hand_tally.precision < MIN_PRECISION
    assert generated_tally.precision < MIN_PRECISION


def test_the_fixture_sees_leading_codes_read_as_name_words(
    monkeypatch: pytest.MonkeyPatch,
    background: list[SyntheticRecord],
    generated_cases: list[Case],
) -> None:
    """Read as name words, a leading code ("USD 320 Wamego", "RSU 13") names nothing.

    The fixture has to be able to fail on that bug: with the codes read as words,
    recall on the listings that begin with a code falls far under the bar, on
    both sets, and a code of the other series takes the wrong district.
    """
    hand_named, _ = _code_cases(handmade.CASES)
    generated_coded = [case for case in generated_cases if case.note == CODE_NOTE]
    try:
        with monkeypatch.context() as patch:
            patch.setattr(normalize, "district_codes", _no_codes)
            normalize.clear_caches()
            fixture = Matcher(Directory([*handmade.RECORDS, *(item.record for item in background)]))
            plain = Matcher(Directory(item.record for item in background))
            hand = _tally((case, _run(fixture, case)) for case in hand_named)
            generated = _tally((case, _run(plain, case)) for case in generated_coded)
            wrong = _run(fixture, handmade.case("MSAD 84", "ME", "SYN-ME-RSU93"))
    finally:
        normalize.clear_caches()
    assert hand.recall < MIN_RECALL / 2, hand
    assert generated.recall < MIN_RECALL / 2, generated
    assert wrong.target is not None
    assert wrong.target.id == "SYN-ME-RSU84"


def test_handmade_cases_say_directions() -> None:
    """A town and the town named for its direction from it, on both sides of the threshold."""
    named, unnamed = _direction_cases(handmade.CASES)
    assert len(named) >= MIN_HARD_NEGATIVES, [c.listing for c in named]
    assert len(unnamed) >= MIN_HARD_NEGATIVES, [c.listing for c in unnamed]
    abbreviated = [c for c in unnamed if _ABBREVIATED_DIRECTION.match(c.listing)]
    assert len(abbreviated) >= MIN_HARD_NEGATIVES, [c.listing for c in abbreviated]
    listings = {(c.listing, c.states, c.counties, c.expected) for c in handmade.CASES}
    # "E. <Town> Public Schools" beside "<Town>", with and without the county.
    assert ("E. Lansmere Public Schools", ("MI",), None, "SYN-MI-ELANM") in listings
    assert ("Lansmere Public Schools", ("MI",), None, "SYN-MI-LANM") in listings
    assert ("W. Lansmere Public Schools", ("MI",), None, None) in listings
    assert ("N. Lansmere Schools", ("MI",), ("83701",), None) in listings
    assert ("S. Portwick Schools", ("ME",), None, None) in listings
    assert ("W. Hartmoor PS", ("CT",), ("84201",), None) in listings
    # A middle initial is no direction.
    assert ("Harry S. Tollman Elementary", ("MI",), None, "SYN-MI-TOLES") in listings
    assert ("Joel E. Barrow Elementary", ("MI",), None, "SYN-MI-BARES") in listings


def test_generated_cases_say_directions(generated_cases: list[Case]) -> None:
    named, unnamed = _direction_cases(generated_cases)
    assert len(named) >= MIN_HARD_NEGATIVES
    assert len(unnamed) >= MIN_HARD_NEGATIVES
    abbreviated = [c for c in unnamed if _ABBREVIATED_DIRECTION.match(c.listing)]
    assert len(abbreviated) >= MIN_HARD_NEGATIVES
    # Every abbreviation a listing uses.
    starts = {c.listing.split(" ", 1)[0] for c in [*named, *unnamed]}
    assert starts >= {"N.", "S.", "E.", "W.", "No.", "So."}


def _without_direction_words(text: str) -> str:
    """The normalizer before it read directions: every letter is an initial."""
    return text


def test_the_fixture_sees_directions_read_as_initials(
    monkeypatch: pytest.MonkeyPatch,
    background: list[SyntheticRecord],
    generated_cases: list[Case],
) -> None:
    """Read as a weak initial, the "E." of "E. Lansing" leaves "Lansing".

    The fixture has to be able to fail on that bug: with abbreviated directions
    left as letters, "E. <Town> Public Schools" takes the district of "<Town>",
    and precision falls under the bar on both sets.
    """
    try:
        with monkeypatch.context() as patch:
            patch.setattr(normalize, "expand_directions", _without_direction_words)
            patch.setattr(normalize, "_part_direction", _without_direction_words)
            normalize.clear_caches()
            fixture = Matcher(Directory([*handmade.RECORDS, *(item.record for item in background)]))
            plain = Matcher(Directory(item.record for item in background))
            hand = _tally((case, _run(fixture, case)) for case in handmade.CASES)
            generated = _tally((case, _run(plain, case)) for case in generated_cases)
            _, unnamed = _direction_cases(handmade.CASES)
            leaked = [case for case in unnamed if _run(fixture, case).target is not None]
    finally:
        normalize.clear_caches()
    assert hand.precision < MIN_PRECISION, hand
    assert generated.precision < MIN_PRECISION, generated
    assert len(leaked) >= MIN_HARD_NEGATIVES // 2, [c.listing for c in leaked]


def test_the_fixture_sees_a_direction_left_out(
    monkeypatch: pytest.MonkeyPatch, fixture_matcher: Matcher
) -> None:
    """With a direction said on one side only costing nothing, long names leak.

    ``"East"`` is a word of its own once spelled out, so a town of one word
    (``"East Lansmere"`` against ``"Lansmere"``) stays under the threshold on the
    words alone. A town of two or three words (``"W. Des Pellam"``, ``"E. Grand
    Tamsel Harbor"``) does not: the rule that a direction said on one side only
    rules the record out is what keeps those out, and the hand-written set fails
    without it.
    """
    monkeypatch.setattr(index, "DIRECTION_NOT_SAID", 1.0)
    hand = _tally((case, _run(fixture_matcher, case)) for case in handmade.CASES)
    assert hand.precision < MIN_PRECISION, hand
    _, unnamed = _direction_cases(handmade.CASES)
    leaked = {case.listing for case in unnamed if _run(fixture_matcher, case).target is not None}
    assert {"E. Des Pellam Schools", "E. Grand Tamsel Harbor Public Schools"} <= leaked


def _place_cases(cases: Iterable[Case]) -> tuple[list[Case], list[Case]]:
    """The listings that are only a town's name: those that name a district, those that do not."""
    said = [
        case
        for case in cases
        if case.note == PLACE_NOTE
        or case.note.startswith((handmade.PLACE, handmade.PLACE_NEGATIVE))
    ]
    return (
        [case for case in said if case.expected is not None],
        [case for case in said if case.expected is None],
    )


def _schools_named_for(records: Iterable[DirectoryRecord]) -> dict[tuple[str, str], list[str]]:
    """Per state and town, the names of the schools there named for the town and more."""
    named: dict[tuple[str, str], list[str]] = {}
    for record in records:
        if (
            record.kind == "school"
            and record.city
            and record.city.casefold() in record.name.casefold()
        ):
            named.setdefault((record.state, record.city.casefold()), []).append(record.name)
    return named


def test_handmade_cases_name_places() -> None:
    """A town's name beside a school named for it: its district or nothing, never the school."""
    named, unnamed = _place_cases(handmade.CASES)
    assert len(named) >= MIN_HARD_NEGATIVES, [c.listing for c in named]
    assert len(unnamed) >= MIN_HARD_NEGATIVES, [c.listing for c in unnamed]
    ids = {record.id: record for record in handmade.RECORDS}
    assert all(c.expected is None or ids[c.expected].kind == "district" for c in named)
    # Every hard negative sits beside a school its words fit, which it never names.
    for case in unnamed:
        words = normalize.listing_forms(normalize.clean_listing(case.listing).text).school
        assert any(
            record.kind == "school"
            and record.state in case.states
            and words.token_set <= normalize.record_form(record.name, district=False).token_set
            for record in handmade.RECORDS
        ), case
    listings = {(c.listing, c.states, c.counties, c.expected) for c in handmade.CASES}
    # "<Town>" beside "<Town> High" of "<Town> Valley Unified": the district.
    assert ("Varenna", ("CA",), None, "SYN-CA-VARV") in listings
    assert ("Varenna High", ("CA",), None, "SYN-CA-VARHS") in listings
    # "<Town>" beside "Village School of <Town>" and "The <Town> School": nothing.
    assert ("Brackville", ("KY",), None, None) in listings
    assert ("Village School of Brackville", ("KY",), None, "SYN-KY-VSOB") in listings
    assert ("Halstead", ("NC",), None, None) in listings
    # A town's one school, a township's high school elsewhere, and a town's two
    # districts of one name, its school system, which the listing names whole.
    assert ("Effley", ("NH",), None, None) in listings
    assert ("Olden Brook", ("NJ",), None, "SYN-NJ-OLDB") in listings
    assert ("Buckmoor", ("AZ",), None, "SYN-AZ-BUCE") in listings
    buckmoor = next(c for c in handmade.CASES if (c.listing, c.states) == ("Buckmoor", ("AZ",)))
    assert buckmoor.targets == {"SYN-AZ-BUCE", "SYN-AZ-BUCH"}
    # A school named for a town in another town, statewide and in its own county.
    assert ("Pellmont", ("OH",), None, None) in listings
    assert ("Pellmont", ("OH",), ("86202",), None) in listings


def _town_of(case: Case) -> str:
    """The town a place listing names, as its records' city is written, folded."""
    return normalize.clean_listing(case.listing).text.casefold()


def test_generated_cases_name_places(
    background: list[SyntheticRecord], generated_cases: list[Case]
) -> None:
    named, unnamed = _place_cases(generated_cases)
    assert len(named) >= MIN_HARD_NEGATIVES
    assert len(unnamed) >= MIN_HARD_NEGATIVES
    records = {item.record.id: item.record for item in background}
    schools = _schools_named_for(records.values())
    places = [*named, *unnamed]
    beside = [c for c in places if any((s, _town_of(c)) in schools for s in c.states)]
    assert len(beside) >= len(places) // 2
    # Some name "<Town> Valley" districts through their "<Town> High".
    valley = [c for c in named if c.expected and " Valley " in records[c.expected].name]
    assert len(valley) >= 5, [c.listing for c in named]
    # Some sit beside a private school named for the town, and name nothing.
    private = {
        (r.state, r.city.casefold())
        for r in records.values()
        if r.city
        and any(f.format(town=r.city).casefold() == r.name.casefold() for f in TOWN_PRIVATE_FORMS)
    }
    alone = [c for c in unnamed if any((s, _town_of(c)) in private for s in c.states)]
    assert len(alone) >= 5


def _no_place(*_args: object) -> None:
    """The matcher before it read a place's name: a bare town is any record's name."""


def _no_bare_reading(*_args: object) -> None:
    """The matcher before a bare name named the district of the school that adds a level."""


def test_the_fixture_sees_a_town_read_as_a_school(
    monkeypatch: pytest.MonkeyPatch,
    fixture_matcher: Matcher,
    background_matcher: Matcher,
    generated_cases: list[Case],
) -> None:
    """Read as a name like any other, "<Town>" takes "<Town> High" or "Village School of <Town>".

    The fixture has to be able to fail on that bug: without the place reading,
    precision falls under the bar on both sets. A bare name that is a school's
    but for a level names that school's district too (``_bare_reading``), which
    guards ``"Varenna"`` a second way; the bug had neither.
    """
    monkeypatch.setattr(matcher_module.Matcher, "_place", _no_place)
    monkeypatch.setattr(matcher_module.Matcher, "_bare_reading", _no_bare_reading)
    hand = _tally((case, _run(fixture_matcher, case)) for case in handmade.CASES)
    generated = _tally((case, _run(background_matcher, case)) for case in generated_cases)
    assert hand.precision < MIN_PRECISION, hand
    assert generated.precision < MIN_PRECISION, generated
    leaked = {
        case.listing: result.target.name
        for case in _place_cases(handmade.CASES)[1]
        if (result := _run(fixture_matcher, case)).target is not None
    }
    # "Village" begins the school's name, so it is a word of the name and a bare
    # "Brackville" leaves it out: that guards "VILLAGE SCHOOL OF BRACKVILLE" a
    # second way (see normalize.qualifies).
    assert "Brackville" not in leaked
    assert leaked.get("Effley") == "Effley Elementary School"
    assert len(leaked) >= MIN_HARD_NEGATIVES // 2, leaked
    wrong = _run(fixture_matcher, handmade.case("Varenna", "CA", "SYN-CA-VARV"))
    assert wrong.target is not None
    assert wrong.target.id == "SYN-CA-VARHS"


def _network_cases(cases: Iterable[Case]) -> tuple[list[Case], list[Case]]:
    """The listings for a network or its campuses: those that name a record, those that do not."""
    said = [
        case
        for case in cases
        if case.note == NETWORK_NOTE
        or case.note.startswith((handmade.NETWORK, handmade.NETWORK_NEGATIVE))
    ]
    return (
        [case for case in said if case.expected is not None],
        [case for case in said if case.expected is None],
    )


def _whole(_self: index.Reach, _stray_share: float = index.STRAY_SHARE) -> bool:
    """The matcher before it read a market: a district is always taken whole."""
    return True


def test_handmade_cases_name_networks() -> None:
    """A network's name from one market: its campus there, or the queue; never the network."""
    named, unnamed = _network_cases(handmade.CASES)
    assert len(named) >= 10, [c.listing for c in named]
    assert len(unnamed) >= 8, [c.listing for c in unnamed]
    ids = {record.id: record for record in handmade.RECORDS}
    # Every campus a network's name is taken for lies in the listing's counties.
    for case in named:
        record = ids[case.expected or ""]
        assert record.kind == "school"
        assert case.counties is not None
        assert record.county_fips in case.counties
    listings = {(c.listing, c.counties, c.near, c.expected) for c in handmade.CASES}
    two = (handmade.TALBERT_CO, handmade.MOSSBURG_CO)
    assert ("Crestline High School", two, None, None) in listings
    # Both campuses are the market's: a point beside one says nothing of which.
    assert ("Crestline High School", two, handmade.TALBERT, None) in listings
    assert ("Crestline High School", (handmade.WYNNE_CO,), None, "SYN-TX-CRWYN") in listings
    assert ("Vantage Schools", (handmade.ODELL_CO,), None, None) in listings
    assert ("Quillon Academy", (handmade.BROOKHOLLOW_CO,), None, "SYN-TX-QUBRO") in listings
    # A district straddling the market's edge, most of its schools just outside
    # the counties, and one with a virtual school across the state: whole.
    assert ("Tiberton Area School District", (handmade.PELLSVILLE_CO,), None, "SYN-PA-TIBR") in (
        listings
    )
    assert ("Halloran County Schools", (handmade.HALLORAN_CO,), None, "SYN-FL-HALL") in listings


def test_generated_cases_name_networks(
    background: list[SyntheticRecord], generated_cases: list[Case]
) -> None:
    named, unnamed = _network_cases(generated_cases)
    assert len(named) >= MIN_HARD_NEGATIVES
    assert len(unnamed) >= MIN_HARD_NEGATIVES
    records = {item.record.id: item.record for item in background}
    assert all(records[c.expected or ""].kind == "school" for c in named)
    # Most name the network itself from a market, not a campus by its town.
    towns = {r.city.casefold() for r in records.values() if r.city}
    by_brand = [c for c in named if not any(t in c.listing.casefold() for t in towns)]
    assert len(by_brand) >= 10
    # A district from the market beside its own county, which holds one of its
    # schools: the district, unless a namesake there makes it ambiguous.
    straddling = [c for c in generated_cases if c.note == STRADDLE_NOTE and c.expected]
    assert len(straddling) >= 5
    for case in straddling:
        district = records[case.expected or ""]
        assert district.kind == "district"
        assert case.counties is not None
        assert district.county_fips not in case.counties


def test_the_fixture_sees_a_network_taken_whole(
    monkeypatch: pytest.MonkeyPatch,
    fixture_matcher: Matcher,
    background_matcher: Matcher,
    generated_cases: list[Case],
) -> None:
    """Taken whole, a network turns one market's closing into its other cities'.

    The fixture has to be able to fail on that bug: with every district taken
    whole, "Crestline High School" from one market takes the network of seven
    campuses, and precision falls under the bar on both sets.
    """
    monkeypatch.setattr(index.Reach, "whole", _whole)
    hand = _tally((case, _run(fixture_matcher, case)) for case in handmade.CASES)
    generated = _tally((case, _run(background_matcher, case)) for case in generated_cases)
    assert hand.precision < MIN_PRECISION, hand
    assert generated.precision < MIN_PRECISION, generated
    leaked = {
        (case.listing, case.counties): result.target.id
        for case in _network_cases(handmade.CASES)[1]
        if (result := _run(fixture_matcher, case)).target is not None
    }
    assert leaked[("Crestline High School", (handmade.TALBERT_CO, handmade.MOSSBURG_CO))] == (
        "SYN-TX-CRST"
    )
    assert leaked[("Vantage Schools", (handmade.ODELL_CO,))] == "SYN-TX-VANT"
    assert len(leaked) >= 8, leaked


def _by_county_lines(self: index.Reach, stray_share: float = index.STRAY_SHARE) -> bool:
    """A district whose schools lie mostly outside the counties is never whole."""
    return self.outside * 2 <= self.schools and _whole_by_reach(self, stray_share)


_whole_by_reach = index.Reach.whole


def test_the_fixture_sees_straddling_districts_cut_by_county_lines(
    monkeypatch: pytest.MonkeyPatch,
    fixture_matcher: Matcher,
    background_matcher: Matcher,
    generated_cases: list[Case],
) -> None:
    """Counting county lines alone cuts off a district that straddles its market's edge.

    Its schools lie near one another, and its closing closes them all: a
    listing from the market on either side names it whole. Were a district
    with most of its schools outside the counties turned away, those closings
    would be lost, on both sets.
    """
    monkeypatch.setattr(index.Reach, "whole", _by_county_lines)
    straddling = [case for case in generated_cases if case.note == STRADDLE_NOTE]
    generated = _tally((case, _run(background_matcher, case)) for case in straddling)
    assert generated.recall < MIN_RECALL / 2, generated
    tiberton = handmade.case(
        "Tiberton Area School District", "PA", "SYN-PA-TIBR", counties=handmade.PELLSVILLE_CO
    )
    assert _run(fixture_matcher, tiberton).target is None


_SCHOOL = frozenset({"school"})


def _own_name_cases(cases: Iterable[Case]) -> tuple[list[Case], list[Case]]:
    """The listings for a district named as one academy, or its schools: named, not named."""
    said = [
        case
        for case in cases
        if case.note == ACADEMY_NOTE
        or case.note.startswith((handmade.OWN_NAME, handmade.OWN_NAME_NEGATIVE))
    ]
    return (
        [case for case in said if case.expected is not None],
        [case for case in said if case.expected is None],
    )


def _adds_to_its_name(district: DirectoryRecord, schools: Iterable[DirectoryRecord]) -> bool:
    """True when one of ``district``'s schools is its name and a level, word for word.

    ``School`` inside a name aside: ``"Tamsin PCS - MS"`` is ``"Tamsin Public Charter
    School Middle School"``.
    """
    form = normalize.record_form(district.name, district=False)
    for school in schools:
        other = normalize.record_form(school.name, district=False)
        if other.token_set - _SCHOOL == form.token_set - _SCHOOL and other.levels - form.levels:
            return True
    return False


def test_handmade_cases_name_districts_by_their_own_name() -> None:
    """A district named as one academy: its name is the district, a school's name the school."""
    named, unnamed = _own_name_cases(handmade.CASES)
    records = {record.id: record for record in handmade.RECORDS}
    districts = [c for c in named if records[c.expected or ""].kind == "district"]
    assert len(districts) >= 15, [c.listing for c in districts]
    assert len(unnamed) >= 5, [c.listing for c in unnamed]
    for case in districts:
        district = records[case.expected or ""]
        schools = [r for r in handmade.RECORDS if r.district_id == district.id]
        assert len(schools) >= 2
        assert _adds_to_its_name(district, schools), district.name
    listings = {(c.listing, c.states, c.counties, c.expected) for c in handmade.CASES}
    # The shapes the real directory has: "X Academy" beside "X Academy Middle" and
    # "X Academy Upper El", "X Academy-Middle" beside "X Academy-Upper", "X PCS"
    # beside "X PCS - MS", and "X Academy Elementary" beside "X Academy Middle".
    county = (handmade.WYNDHAVEN_CO,)
    assert ("Wyndhaven Academy", ("TX",), county, "SYN-TX-WYND") in listings
    assert ("Wyndhaven Academy Middle", ("TX",), county, "SYN-TX-WYNMS") in listings
    assert ("Orvelle Academy", ("MO",), None, "SYN-MO-ORVA") in listings
    assert ("Tamsin PCS", ("DC",), None, "SYN-DC-TAMS") in listings
    assert ("Vespera Academy", ("UT",), None, "SYN-UT-VESP") in listings
    assert ("Vespera Academy Elementary", ("UT",), (handmade.VESPERA_CO,), "SYN-UT-VESPE") in (
        listings
    )
    # A name that is the district's, word for word, but reads as one school and
    # fits the district badly: the district or its high school, so neither.
    assert ("Aldern Village School", ("MO",), None, None) in listings


def test_generated_cases_name_districts_by_their_own_name(
    background: list[SyntheticRecord], generated_cases: list[Case]
) -> None:
    named, unnamed = _own_name_cases(generated_cases)
    records = {item.record.id: item.record for item in background}
    districts = [c for c in named if records[c.expected or ""].kind == "district"]
    schools = [c for c in named if records[c.expected or ""].kind == "school"]
    assert len(districts) >= MIN_HARD_NEGATIVES, len(districts)
    assert len(schools) >= 10, len(schools)
    assert len(unnamed) >= 5, len(unnamed)
    by_district: dict[str, list[DirectoryRecord]] = {}
    for record in records.values():
        if record.district_id is not None:
            by_district.setdefault(record.district_id, []).append(record)
    for case in districts:
        district = records[case.expected or ""]
        assert _adds_to_its_name(district, by_district[district.id]), district.name
    # Every pattern shows up: each school a level, and one a level beside others
    # that add a part.
    shapes = {
        tuple(sorted(normalize.record_form(r.name, district=False).tokens[1:] or ("",)))
        for c in districts
        for r in by_district[c.expected or ""]
    }
    assert {("academy",), ("academy", "upper")} <= shapes, shapes


def _no_exact_reading(
    _self: matcher_module.Matcher, _winner: object, _scored: object, _forms: object
) -> None:
    """The matcher before it read a district's own name: a school that adds a level wins."""


def test_the_fixture_sees_an_own_school_taken_for_its_district(
    monkeypatch: pytest.MonkeyPatch,
    fixture_matcher: Matcher,
    background_matcher: Matcher,
    generated_cases: list[Case],
) -> None:
    """Without the exact-name rule, "Wyndhaven Academy" is its middle school alone.

    A listing that says a district's name, word for word, reads as one school
    when that name is one school's, and so scores its own school that adds a
    level above it. The fixture has to be able to fail on that bug: with the
    rule off, precision falls under the bar on both sets.
    """
    monkeypatch.setattr(matcher_module.Matcher, "_exact_reading", _no_exact_reading)
    hand = _tally((case, _run(fixture_matcher, case)) for case in handmade.CASES)
    generated = _tally((case, _run(background_matcher, case)) for case in generated_cases)
    assert hand.precision < MIN_PRECISION, hand
    assert generated.precision < MIN_PRECISION, generated
    leaked = {
        (case.listing, case.counties): result.target.id
        for case in _own_name_cases(handmade.CASES)[0]
        if (result := _run(fixture_matcher, case)).target is not None
        and result.target.id != case.expected
    }
    assert leaked[("Wyndhaven Academy", (handmade.WYNDHAVEN_CO,))] == "SYN-TX-WYNMS"
    assert leaked[("Orvelle Academy", None)] == "SYN-MO-ORVMS"
    assert leaked[("Tamsin PCS", None)] == "SYN-DC-TAMMS"
    assert len(leaked) >= 10, leaked


def _namesake_cases(cases: Iterable[Case]) -> list[Case]:
    """The listings for a town beside a district of its name elsewhere, or spelled apart."""
    notes = (
        handmade.NAMESAKE,
        handmade.NAMESAKE_NEGATIVE,
        handmade.SPELLING,
        handmade.SPELLING_NEGATIVE,
    )
    return [case for case in cases if case.note == NAMESAKE_NOTE or case.note.startswith(notes)]


def test_handmade_cases_name_towns_within_reach() -> None:
    """A town's name names its district only in reach, never demoting one named so elsewhere."""
    cases = _namesake_cases(handmade.CASES)
    assert len(cases) >= 30, [c.listing for c in cases]
    negatives = [c for c in cases if c.note.startswith("hard negative")]
    assert len(negatives) >= 15, [c.listing for c in negatives]
    assert sum(1 for c in cases if c.near is not None) >= 8
    assert sum(1 for c in cases if c.counties is not None) >= 6
    listings = {(c.listing, c.counties, c.near, c.expected) for c in handmade.CASES}
    # "Edgewood" on a San Antonio list: San Antonio's "Edgewood ISD".
    assert ("Edgemere", None, handmade.SAN_ARVELLO, "SYN-TX-EDGS") in listings
    assert ("Edgemere", (handmade.SAN_ARVELLO_CO,), None, "SYN-TX-EDGS") in listings
    assert ("Edgemere", None, None, None) in listings
    # "Oak Hills" is not the town of Oak Hill, nor "Scott Valley" "Scotts Valley".
    assert ("Oakhurst Hills", None, None, "SYN-OH-OAKHS") in listings
    assert ("Oakhurst Hill Schools", None, None, "SYN-OH-OAKHU") in listings
    assert ("Tarrow Valley", None, handmade.FORT_KELLAN, "SYN-CA-TARV") in listings
    # "Kentwood", "Lee": a district whose name is the listing's, word for word.
    assert ("Kentmoor", (handmade.GRAND_MAREN_CO,), None, "SYN-MI-KENT") in listings
    assert ("Leemont", (handmade.LEEMONT_CO,), None, "SYN-FL-LEEM") in listings


def test_generated_namesake_cases_are_matched(
    background_matcher: Matcher, generated_cases: list[Case]
) -> None:
    """Every generated listing for a town and a district named for it elsewhere is right."""
    cases = [case for case in generated_cases if case.note == NAMESAKE_NOTE]
    assert len(cases) >= 40
    assert sum(1 for c in cases if c.expected is None) >= 5
    assert sum(1 for c in cases if c.expected is not None and c.counties is None) >= 5
    wrong = [
        (case.listing, case.states, case.counties, case.expected, got)
        for case in cases
        if (got := _target_id(_run(background_matcher, case))) != case.expected
    ]
    assert not wrong


def _target_id(result: MatchResult) -> str | None:
    return result.target.id if result.target is not None else None


def _statewide_stemmed_key(text: str) -> str:
    """The key towns had before: stemmed, so a plural is the same town."""
    return index.city_key(text).replace(" ", "")


def test_the_fixture_sees_towns_read_statewide(
    monkeypatch: pytest.MonkeyPatch,
    fixture_directory: Directory,
    background: list[SyntheticRecord],
    generated_cases: list[Case],
) -> None:
    """Every town of the name in the states, its plural too, and every other district ranked down.

    The fixture has to be able to fail on that reading of a town's name: it
    takes the town of Edgemere's district from a San Arvello market, and a
    district of the town's plural name for the town's.
    """
    monkeypatch.setattr(matcher_module.Matcher, "_in_reach", lambda *_args: True)
    monkeypatch.setattr(matcher_module.Matcher, "_names_exactly", lambda *_args: False)
    monkeypatch.setattr(index, "place_key", _statewide_stemmed_key)
    monkeypatch.setattr(
        matcher_module, "place_keys", lambda text: frozenset({_statewide_stemmed_key(text)})
    )
    hand = _namesake_cases(handmade.CASES)
    fixture = Matcher(fixture_directory)
    wrong = [c.listing for c in hand if _target_id(_run(fixture, c)) != c.expected]
    assert len(wrong) >= 8, wrong
    assert "Edgemere" in wrong
    assert "Oakhurst Hills" in wrong
    generated = [c for c in generated_cases if c.note == NAMESAKE_NOTE]
    background_only = Matcher(Directory(item.record for item in background))
    missed = [c for c in generated if _target_id(_run(background_only, c)) != c.expected]
    assert len(missed) >= 5, [c.listing for c in missed]


def _bracket_cases(cases: Iterable[Case]) -> list[Case]:
    """The listings for a district whose NCES name ends with a bracket."""
    notes = (handmade.BRACKET, handmade.BRACKET_NEGATIVE)
    return [case for case in cases if case.note == BRACKET_NOTE or case.note.startswith(notes)]


def test_handmade_cases_name_districts_whose_names_end_with_brackets() -> None:
    """Each kind of bracket NCES ends a name with, beside the names it tells apart."""
    cases = _bracket_cases(handmade.CASES)
    assert len(cases) >= 40, [c.listing for c in cases]
    negatives = [c for c in cases if c.expected is None]
    assert len(negatives) >= 10, [c.listing for c in negatives]
    listings = {(c.listing, c.counties, c.near, c.expected) for c in handmade.CASES}
    # "Evergreen Public Schools" in Clark County, not "Evergreen High School"
    # and not the Stevens County namesake.
    assert ("Everbrook Public Schools", (handmade.TALLIS_CO,), None, "SYN-WA-EVBT") in listings
    assert ("Everbrook", (handmade.TALLIS_CO,), None, "SYN-WA-EVBT") in listings
    assert ("Everbrook", None, None, None) in listings
    # "Madison" near Adrian is Adrian's district, whatever its bracket, when the
    # other lies beyond a market's reach; with both in the counties, neither.
    assert ("Madley", None, handmade.ADRAMOOR, "SYN-MI-MADO") in listings
    near = (handmade.ORRIN_CO, handmade.OAKMERE_CO), handmade.ADRAMOOR
    assert ("Madley", *near, None) in listings
    # "North Rockland", "Lake Shore CSD": second names.
    assert ("North Rockmere", (handmade.ROCKMERE_CO,), None, "SYN-NY-CARV") in listings
    assert ("Lake Vestry CSD", None, None, "SYN-NY-EVAN") in listings
    # Arizona's entity number is no district number.
    assert ("Flagmoor Unified School District #1", None, None, "SYN-AZ-FLAG") in listings
    assert ("USD 4192", None, None, None) in listings
    # Every kind of bracket is in the directory.
    brackets = {
        normalize.split_brackets(record.name)[1][-1:]
        for record in handmade.RECORDS
        if record.name.endswith(")")
    }
    for kind in {("Tallis",), ("NORTH ROCKMERE",), ("4192",), ("CHARTER",), ("THE",), ("3-6",)}:
        assert kind in brackets, kind
    assert ("formerly Berrow-Millan",) in brackets


def test_generated_bracket_cases_are_matched(
    background: list[SyntheticRecord], background_matcher: Matcher, generated_cases: list[Case]
) -> None:
    """The generated directory ends names with each kind of bracket, and every listing is right."""
    districts = [item.record for item in background if item.record.kind == "district"]
    numbered = [r for r in districts if r.state in ENTITY_NUMBER_STATES]
    assert numbered
    assert all(re.search(r" \(\d+\)$", r.name) for r in numbered)
    county_brackets = [
        r
        for r in districts
        if r.state in COUNTY_BRACKET_STATES
        and r.county is not None
        and r.name.endswith(f"({r.county.removesuffix(' County')})")
    ]
    assert len(county_brackets) >= 4, county_brackets
    second_named = [
        item
        for item in background
        if item.identity.aliases and item.record.state in SECOND_NAME_STATES
    ]
    assert len(second_named) >= 3
    cases = [case for case in generated_cases if case.note == BRACKET_NOTE]
    assert len(cases) >= 40, len(cases)
    assert sum(1 for c in cases if c.expected is None) >= 5
    wrong = [
        (case.listing, case.states, case.expected, got)
        for case in cases
        if (got := _target_id(_run(background_matcher, case))) != case.expected
    ]
    assert not wrong


def _no_brackets(
    name: str, *, district: bool, county: str | None = None
) -> normalize.DirectoryName:
    """The index before it read brackets: every bracket is part of the name."""
    del district, county
    return normalize.DirectoryName(name)


def test_the_fixture_sees_brackets_read_as_name_words(
    monkeypatch: pytest.MonkeyPatch,
    fixture_directory: Directory,
    background: list[SyntheticRecord],
    generated_cases: list[Case],
) -> None:
    """Without reading brackets, "Evergreen Public Schools" is nothing and "Evergreen" a school.

    NCES's county, second name or entity number read as name words keep a
    district from its own name: the fixture has to be able to fail on that bug,
    on both sets, and on the hand-written set precision falls under the bar.
    """
    monkeypatch.setattr(index, "directory_name", _no_brackets)
    fixture = Matcher(fixture_directory)
    hand = _bracket_cases(handmade.CASES)
    wrong = {c.listing for c in hand if _target_id(_run(fixture, c)) != c.expected}
    assert len(wrong) >= 20, wrong
    assert {
        "Everbrook Public Schools",
        "Madley",
        "North Rockmere CSD",
        "Flagmoor Unified School District #1",
    } <= wrong
    assert _tally((case, _run(fixture, case)) for case in handmade.CASES).precision < MIN_PRECISION
    generated = [c for c in generated_cases if c.note == BRACKET_NOTE]
    background_only = Matcher(Directory(item.record for item in background))
    missed = [c for c in generated if _target_id(_run(background_only, c)) != c.expected]
    assert len(missed) >= len(generated) // 2, [c.listing for c in missed]


def _no_second_names(
    name: str, *, district: bool, county: str | None = None
) -> normalize.DirectoryName:
    """The index before it read second names: a district's other name goes."""
    read = normalize.directory_name(name, district=district, county=county)
    return normalize.DirectoryName(read.base, read.county, read.county_kind, read.legal)


def test_the_fixture_sees_second_names_left_out(
    monkeypatch: pytest.MonkeyPatch,
    fixture_directory: Directory,
    background: list[SyntheticRecord],
    generated_cases: list[Case],
) -> None:
    """Without second names, "North Rockland" is its high school and "Lake Shore CSD" nothing."""
    monkeypatch.setattr(index, "directory_name", _no_second_names)
    fixture = Matcher(fixture_directory)
    wrong = {
        (c.listing, got)
        for c in _bracket_cases(handmade.CASES)
        if (got := _target_id(_run(fixture, c))) != c.expected
    }
    assert ("North Rockmere", "SYN-NY-CARVHS") in wrong
    assert ("Lake Vestry CSD", None) in wrong
    assert len(wrong) >= 8, wrong
    background_only = Matcher(Directory(item.record for item in background))
    missed = [
        c
        for c in generated_cases
        if c.note == BRACKET_NOTE and _target_id(_run(background_only, c)) != c.expected
    ]
    assert len(missed) >= 5, [c.listing for c in missed]


def _state_cases(cases: Iterable[Case]) -> list[Case]:
    """The listings that write a state beside the name, or hold one in it."""
    notes = (
        handmade.STATE,
        handmade.STATE_NEGATIVE,
        handmade.STATE_IN_NAME,
        handmade.STATE_IN_NAME_NEGATIVE,
    )
    return [case for case in cases if case.note == STATE_NOTE or case.note.startswith(notes)]


def _outside_market(case: Case) -> bool:
    """True when the case is a listing whose state lies outside its market."""
    return case.expected is None and case.note.endswith("another state never widens")


def test_handmade_cases_write_states_beside_names() -> None:
    """Every way a list writes a state beside a name, and the tokens that are no state."""
    cases = _state_cases(handmade.CASES)
    assert len(cases) >= 90, len(cases)
    negatives = [c for c in cases if c.expected is None]
    assert len(negatives) >= 30, [c.listing for c in negatives]
    assert sum(1 for c in cases if _outside_market(c)) >= 10
    listings = {(c.listing, c.states, c.expected) for c in handmade.CASES}
    # Bare before the designator or the level, in brackets, after a comma or a
    # hyphen, before "Schools" or "Public", abbreviated or spelled out.
    ma_nh, tn_ky, mo_ks = ("MA", "NH"), ("TN", "KY"), ("MO", "KS")
    assert ("Salmere MA Public", ma_nh, "SYN-MA-SALM") in listings
    assert ("Salmere High School NH", ma_nh, "SYN-NH-SALMH") in listings
    assert ("Collinsby (TX) ISD", ("TX", "OK"), "SYN-TX-COLL") in listings
    assert ("Knoxmere County, TN Schools", tn_ky, "SYN-TN-KNXC") in listings
    assert ("KNOXMERE COUNTY SCHOOLS-KY", tn_ky, "SYN-KY-KNXC") in listings
    assert ("WASHINGTON COUNTY SCHOOLS-KY", tn_ky, "SYN-KY-WASC") in listings
    assert ("Madmere County NC Schools", ("NC", "SC", "GA"), "SYN-NC-MADC") in listings
    assert ("Pocamere Co. WV Schools", ("VA", "WV"), "SYN-WV-POCA") in listings
    assert ("Tonganby KS Schools - USD 464", mo_ks, "SYN-KS-TONG") in listings
    assert ("Kessby City MO Public Schools", mo_ks, "SYN-MO-KESS") in listings
    assert ("Kessby City, Kansas Public Schools", mo_ks, "SYN-KS-KESS") in listings
    assert ("Oarkby, Ark.", ("MO", "AR"), "SYN-AR-OARK") in listings
    assert ("Collinsby TX I.S.D.", ("TX", "OK"), "SYN-TX-COLL") in listings
    # The Kansas City lists: "<district> R-n School <town> MO", the town its own
    # or another.
    assert ("Holdenby R-III School Holdenby MO", mo_ks, "SYN-MO-HOLD") in listings
    assert ("Ballmere R-II School Butterby MO", mo_ks, "SYN-MO-BALL") in listings
    assert ("Holdenby Casmere MO R-III School", mo_ks, "SYN-MO-HOLD") in listings
    # Tokens that are no state: Middle School, County, a doctor, School.
    assert ("Germanby MS", ("TN", "MS"), "SYN-TN-GERMS") in listings
    assert ("BRENMERE CO SCHOOLS", ("CO",), "SYN-CO-BRENC") in listings
    assert ("Tomas Cigarmoor MD Elementary", ("VA", "MD", "DC"), "SYN-VA-CIGMD") in listings
    assert ("Jonesmere Int SC", ("NC", "SC"), "SYN-NC-JONSC") in listings
    assert ("Jonmere County KS Meals on Wheels", mo_ks, None) in listings
    # A state outside the market never widens the search.
    assert ("Salmere MA Public", ("NH",), None) in listings
    assert ("WASHINGTON COUNTY SCHOOLS-KY", ("TN",), None) in listings
    assert ("Holdenby R-III School Holdenby MO", ("KS",), None) in listings
    # The state between the name and its town, before a qualifier, after "Co."
    # when it is also a word; a town joined by a hyphen; "Co." left out of a
    # numbered district's name.
    assert ("Shawby R-3 MO Chilby", mo_ks, "SYN-MO-SHAW") in listings
    assert ("Nortonby, VA City Schools", ("VA", "TN"), "SYN-VA-NORC") in listings
    assert ("Randby Co. AL Schools", ("GA", "AL"), "SYN-AL-RANC") in listings
    assert ("Harrby County MS Schools", ("MS", "AL"), "SYN-MS-HARC") in listings
    assert ("Harrby County MS", ("MS", "AL"), None) in listings
    assert ("Sacred Heart School-Troyby MO", ("MO", "IL"), "SYN-MO-SHTR") in listings
    assert ("Westmoor R-2 Schools MO", mo_ks, "SYN-MO-WESTM") in listings


def test_generated_state_cases_are_matched(
    background_matcher: Matcher, generated_cases: list[Case]
) -> None:
    """Every generated listing that writes a state beside its name is right."""
    cases = [case for case in generated_cases if case.note == STATE_NOTE]
    assert len(cases) >= 60, len(cases)
    assert sum(1 for c in cases if c.expected is None) >= 15
    assert all(len(c.states) > 1 or c.expected is None for c in cases)
    wrong = [
        (case.listing, case.states, case.expected, got)
        for case in cases
        if (got := _target_id(_run(background_matcher, case))) != case.expected
    ]
    assert not wrong


def test_the_fixture_sees_states_read_as_name_words(
    monkeypatch: pytest.MonkeyPatch,
    fixture_matcher: Matcher,
    background_matcher: Matcher,
    generated_cases: list[Case],
) -> None:
    """Without reading states, "Salem MA Public" is nothing and "Holden ... MO" too.

    A state beside the name read as a name word keeps a listing from the record
    it names: the fixture has to be able to fail on that bug, on both sets, and
    on the hand-written set recall falls under the bar.
    """
    monkeypatch.setattr(matcher_module, "state_mentions", lambda *_args: ())
    hand = _state_cases(handmade.CASES)
    hand_tally = _tally((case, _run(fixture_matcher, case)) for case in hand)
    assert hand_tally.recall < MIN_RECALL / 2, hand_tally
    wrong = {c.listing for c in hand if _target_id(_run(fixture_matcher, c)) != c.expected}
    # "KNOXMERE COUNTY SCHOOLS-KY" is right even so: its hyphen sets the state
    # apart as a part of its own, which the listing's parts read as its state.
    assert {
        "Salmere MA Public",
        "Knoxmere County, TN Schools",
        "Collinsby (TX) ISD",
        "Holdenby R-III School Holdenby MO",
        "Tonganby KS Schools - USD 464",
        "Shawby R-3 MO Chilby",
        "Randby Co. AL Schools",
    } <= wrong
    every = _tally((case, _run(fixture_matcher, case)) for case in handmade.CASES)
    assert every.recall < MIN_RECALL, every
    generated = [c for c in generated_cases if c.note == STATE_NOTE]
    generated_tally = _tally((case, _run(background_matcher, case)) for case in generated)
    assert generated_tally.recall < MIN_RECALL / 2, generated_tally


def test_the_fixture_sees_a_state_that_widens_the_search(
    monkeypatch: pytest.MonkeyPatch,
    fixture_matcher: Matcher,
    background_matcher: Matcher,
    generated_cases: list[Case],
) -> None:
    """Reading a listing in a state outside its market would name that state's record.

    ``"Salem MA Public"`` on a New Hampshire list is no record of the list's:
    the fixture has to be able to fail if the state it names widened the
    search, and precision falls under the bar on both sets.
    """
    every_state = frozenset(lexicon.STATE_NAMES)
    real = states.state_mentions
    monkeypatch.setattr(
        matcher_module, "state_mentions", lambda text, _market: real(text, every_state)
    )
    leaked = {
        (c.listing, c.states): got
        for c in _state_cases(handmade.CASES)
        if (got := _target_id(_run(fixture_matcher, c))) != c.expected
    }
    assert leaked[("Salmere MA Public", ("NH",))] == "SYN-MA-SALM"
    assert leaked[("WASHINGTON COUNTY SCHOOLS-KY", ("TN",))] == "SYN-KY-WASC"
    assert leaked[("Holdenby R-III School Holdenby MO", ("KS",))] == "SYN-MO-HOLD"
    hand = _tally((case, _run(fixture_matcher, case)) for case in handmade.CASES)
    assert hand.precision < MIN_PRECISION, hand
    generated = [c for c in generated_cases if c.note == STATE_NOTE]
    generated_tally = _tally((case, _run(background_matcher, case)) for case in generated)
    assert generated_tally.precision < MIN_PRECISION, generated_tally


def _parish_cases(cases: Iterable[Case]) -> list[Case]:
    """The listings that name a parish's church or its school."""
    notes = (handmade.PARISH, handmade.PARISH_NEGATIVE)
    return [case for case in cases if case.note.startswith((PARISH_NOTE, *notes))]


_CHURCH_ONLY = (
    "St. Peter's Parish: No Mass",
    "St. Peter's Parish",
    "Christ the King Church - services cancelled",
    "Christ the King Parish",
    "Church of the Visitation",
    "Visitation Parish",
    "Our Lady of Sorrows Parish",
    "Holy Spirit Catholic Church",
)


def test_handmade_cases_name_parishes_and_their_schools(fixture_matcher: Matcher) -> None:
    """A Kansas City-like market's churches and parish schools, named alike.

    Its parish schools are named as NCES names Kansas City's (``"ST PETER'S
    SCHOOL"``, ``"CHRIST THE KING PARISH SCHOOL"``, ``"VISITATION CATHOLIC
    SCHOOL"``): a church's listing never names the school, not even as a
    candidate the matcher is sure of; the parish's name alone goes to the
    queue unless the list files it among schools; a school's word names it.
    """
    cases = _parish_cases(handmade.CASES)
    assert len(cases) >= 50, len(cases)
    negatives = [c for c in cases if c.expected is None]
    assert len(negatives) >= 30, len(negatives)
    assert sum(1 for c in cases if c.category is not None) >= 12
    kc = ("MO", "KS")
    listings = {(c.listing, c.states, c.expected, c.category) for c in handmade.CASES}
    assert ("St. Peter's", kc, None, None) in listings
    assert ("St. Peter's", kc, "SYN-MO-KSTPE", "Schools") in listings
    assert ("Christ the King", kc, None, None) in listings
    assert ("Christ the King", kc, "SYN-KS-KCTK", "Schools") in listings
    assert ("Christ the King School", kc, "SYN-KS-KCTK", None) in listings
    assert ("St. Peter's School", kc, "SYN-MO-KSTPE", "Church") in listings
    assert ("Visitation", kc, None, "Churches") in listings
    for listing in _CHURCH_ONLY:
        result = fixture_matcher.match(listing, states=kc, counties=handmade.KC)
        assert result.target is None, listing
        assert result.reason is matcher_module.Reason.NOT_SCHOOL, (listing, result.reason)
    bare = fixture_matcher.match("Visitation", states=kc, counties=handmade.KC)
    assert bare.reason is matcher_module.Reason.PARISH
    assert bare.best is not None
    assert bare.best.record.id == "SYN-MO-KVIS"


def test_generated_parish_cases_are_matched(
    background_matcher: Matcher, generated_cases: list[Case]
) -> None:
    """Every generated listing for a saint's school or its church is right."""
    cases = [case for case in generated_cases if case.note.startswith(PARISH_NOTE)]
    assert len(cases) >= 60, len(cases)
    assert sum(1 for c in cases if c.expected is None) >= 30
    assert sum(1 for c in cases if c.expected is not None and c.category) >= 10
    wrong = [
        (case.listing, case.category, case.expected, got)
        for case in cases
        if (got := _target_id(_run(background_matcher, case))) != case.expected
    ]
    assert not wrong


def test_the_fixture_sees_a_church_taken_for_its_school(
    monkeypatch: pytest.MonkeyPatch,
    fixture_matcher: Matcher,
    background_matcher: Matcher,
    generated_cases: list[Case],
) -> None:
    """Read as a name like any other, "Visitation" takes "VISITATION CATHOLIC SCHOOL".

    A parish's name alone is its church's as much as its school's: the fixture
    has to be able to fail if the matcher took the school, on both sets.
    """
    monkeypatch.setattr(matcher_module, "church_name", lambda *_args: None)
    hand = _tally((case, _run(fixture_matcher, case)) for case in handmade.CASES)
    assert hand.precision < MIN_PRECISION, hand
    parish = _tally((c, _run(fixture_matcher, c)) for c in _parish_cases(handmade.CASES))
    assert parish.precision < MIN_PRECISION - 0.2, parish
    generated = [c for c in generated_cases if c.note.startswith(PARISH_NOTE)]
    generated_tally = _tally((case, _run(background_matcher, case)) for case in generated)
    assert generated_tally.precision < MIN_PRECISION - 0.2, generated_tally


def test_the_fixture_sees_a_parish_read_as_a_county(
    monkeypatch: pytest.MonkeyPatch, fixture_matcher: Matcher
) -> None:
    """Without reading ``Parish`` as a church, "Christ the King Parish" is no church.

    Its school still is not taken, since the name says nothing of a school;
    but the listing must be known for the church it is, which the fixture checks.
    """
    real = normalize.not_school

    def no_parish(clean: normalize.CleanListing) -> normalize.CivicBody | None:
        found = real(clean)
        return None if found is not None and found.what == lexicon.PARISH else found

    monkeypatch.setattr(matcher_module, "not_school", no_parish)
    result = fixture_matcher.match(
        "Christ the King Parish", states=("MO", "KS"), counties=handmade.KC
    )
    assert result.reason is not matcher_module.Reason.NOT_SCHOOL


def test_the_fixture_sees_a_section_left_unread(
    monkeypatch: pytest.MonkeyPatch,
    fixture_matcher: Matcher,
    background_matcher: Matcher,
    generated_cases: list[Case],
) -> None:
    """A list's section of schools lets a parish's name be its school's; one of churches, never.

    The fixture has to be able to fail if the matcher read no section: recall
    on the parish listings falls far under the bar, on both sets.
    """
    monkeypatch.setattr(matcher_module, "listing_section", lambda *_args: normalize.Section.UNKNOWN)
    parish = _tally((c, _run(fixture_matcher, c)) for c in _parish_cases(handmade.CASES))
    assert parish.recall < MIN_RECALL - 0.2, parish
    generated = [c for c in generated_cases if c.note.startswith(PARISH_NOTE)]
    generated_tally = _tally((case, _run(background_matcher, case)) for case in generated)
    assert generated_tally.recall < MIN_RECALL - 0.2, generated_tally


def test_the_fixture_sees_a_parish_school_that_needs_its_faith_said(
    monkeypatch: pytest.MonkeyPatch,
    fixture_matcher: Matcher,
    background_matcher: Matcher,
    generated_cases: list[Case],
) -> None:
    """ "St. Peter's Catholic School" is NCES's "ST PETER'S SCHOOL", whose name says no church.

    The fixture has to be able to fail if a listing's Catholic faith ruled out a
    saint's school whose name implies it: recall on the parish listings falls
    under the bar on both sets.
    """
    monkeypatch.setattr(index.NameIndex, "_implies_the_faith", lambda *_args: False)
    parish = _tally((c, _run(fixture_matcher, c)) for c in _parish_cases(handmade.CASES))
    assert parish.recall < MIN_RECALL, parish
    generated = [c for c in generated_cases if c.note.startswith(PARISH_NOTE)]
    generated_tally = _tally((case, _run(background_matcher, case)) for case in generated)
    assert generated_tally.recall < MIN_RECALL, generated_tally


def _just_past_cases(cases: Iterable[Case]) -> list[Case]:
    """The listings whose counties lie beside a namesake's, and their controls."""
    twins = {"Hanbury", "Russet", "Lyttleby", "Holy Family"}
    return [
        case
        for case in cases
        if case.note == BORDER_NOTE
        or case.note.startswith(handmade.JUST_PAST)
        or any(case.listing.title().startswith(twin) for twin in twins)
    ]


def test_handmade_cases_name_namesakes_just_past_the_counties() -> None:
    """A twin in a listed state just past the counties, the exact name outside, a shorter in."""
    cases = _just_past_cases(handmade.CASES)
    negatives = [c for c in cases if c.expected is None]
    assert len(negatives) >= MIN_HARD_NEGATIVES, len(negatives)
    assert sum(1 for c in cases if c.expected is not None) >= 10
    listings = {(c.listing, c.states, c.counties, c.expected) for c in cases}
    # WMUR's: New Hampshire's name word for word past the counties, Massachusetts's
    # shorter one in them.
    assert ("Hanbury School District", ("MA", "NH"), handmade.BOSBY, None) in listings
    assert ("Hanbury High School", ("MA", "NH"), handmade.BOSBY, None) in listings
    assert ("Russet Elementary School", ("MA", "NH"), handmade.BOSBY, None) in listings
    # Far from the counties, or in a state the list does not cover, it is none.
    assert ("Lyttleby School District", ("MA", "NH"), handmade.BOSBY, "SYN-MA-LYT") in listings
    assert ("Hanbury School District", ("MA",), handmade.BOSBY, "SYN-MA-HAN") in listings
    records = {record.id: record for record in handmade.RECORDS}
    near = records["SYN-NH-HANSD"].point
    far = records["SYN-NH-LYTSD"].point
    market = records["SYN-NH-PEMES"].point
    assert near is not None
    assert far is not None
    assert market is not None
    assert index.haversine_km(near, market) < index.REACH_KM / 1.5
    assert index.haversine_km(far, market) > index.REACH_KM * 1.5


def test_handmade_namesakes_just_past_the_counties_are_matched(fixture_matcher: Matcher) -> None:
    """Each goes to the queue with both, in-county record first; each control is accepted."""
    wrong = []
    for case in _just_past_cases(handmade.CASES):
        result = _run(fixture_matcher, case)
        if _target_id(result) != case.expected:
            wrong.append((case.listing, case.counties, result.reason, result.detail))
    assert not wrong
    queued = fixture_matcher.match(
        "Hanbury School District", states=("MA", "NH"), counties=handmade.BOSBY
    )
    assert queued.reason is matcher_module.Reason.AMBIGUOUS
    assert queued.best is not None
    assert queued.best.record.id == "SYN-MA-HAN"
    assert "SYN-NH-HANSD" in {c.record.id for c in queued.runners_up}
    assert "just past them" in queued.detail


def test_generated_border_cases_are_matched(
    background_matcher: Matcher, generated_cases: list[Case]
) -> None:
    """Every generated listing for a town whose namesake lies across a market's line is right."""
    cases = [case for case in generated_cases if case.note == BORDER_NOTE]
    assert len(cases) >= 40, len(cases)
    assert sum(1 for c in cases if c.expected is None and c.counties is not None) >= 20
    assert sum(1 for c in cases if c.expected is not None and len(c.states) == 2) >= 5
    assert sum(1 for c in cases if c.expected is not None and len(c.states) == 1) >= 5
    wrong = [
        (case.listing, case.states, case.counties, case.expected, got)
        for case in cases
        if (got := _target_id(_run(background_matcher, case))) != case.expected
    ]
    assert not wrong


def test_the_fixture_sees_counties_taken_for_proof(
    monkeypatch: pytest.MonkeyPatch,
    fixture_matcher: Matcher,
    background_matcher: Matcher,
    generated_cases: list[Case],
) -> None:
    """Without a second reading past the counties, a namesake there is never seen.

    The fixture has to be able to fail if the counties decided alone: precision
    falls under the bar on the hand-written cases and on the generated ones, and
    far under it on the listings written for namesakes across a market's line.
    """
    monkeypatch.setattr(
        matcher_module.Matcher, "_past_counties", lambda _self, result, *_args, **_kwargs: result
    )
    hand = _tally((case, _run(fixture_matcher, case)) for case in handmade.CASES)
    assert hand.precision < MIN_PRECISION, hand
    generated = _tally((case, _run(background_matcher, case)) for case in generated_cases)
    assert generated.precision < MIN_PRECISION, generated
    borders = [c for c in generated_cases if c.note == BORDER_NOTE]
    border_tally = _tally((case, _run(background_matcher, case)) for case in borders)
    assert border_tally.precision < MIN_PRECISION - 0.2, border_tally


def test_the_fixture_sees_a_district_number_taken_for_a_private_school(
    monkeypatch: pytest.MonkeyPatch, fixture_matcher: Matcher
) -> None:
    """ "St. Jarvis R-1" is the numbered district, never the private school of the saint."""
    monkeypatch.setattr(index, "NO_DISTRICT", 1.0)
    result = fixture_matcher.match(
        "St. Jarvis R-1", states=("MO",), counties=(handmade.JARVIS_PARISH_CO,)
    )
    assert result.target is not None
    assert result.target.id == "SYN-MO-JARC"


def _across_cases(cases: Iterable[Case]) -> list[Case]:
    """The listings for namesakes across a state line, and their controls."""
    return [
        case
        for case in cases
        if case.note == ACROSS_NOTE
        or case.note.startswith((handmade.ACROSS, handmade.ACROSS_NEGATIVE))
    ]


def test_handmade_cases_name_namesakes_across_a_state_line() -> None:
    """Twins each state writes its own way, told apart only by a point or a state named."""
    cases = _across_cases(handmade.CASES)
    negatives = [c for c in cases if c.expected is None]
    assert len(negatives) >= MIN_HARD_NEGATIVES, len(negatives)
    assert sum(1 for c in cases if c.expected is not None) >= 15
    assert sum(1 for c in cases if c.near is not None) >= 8
    listings = {(c.listing, c.states, c.near, c.expected) for c in cases}
    kc = handmade.MO_KS
    # Kansas City's two districts, as Missouri and Kansas write them.
    assert ("Kessby City Public Schools", kc, None, None) in listings
    assert ("Kessby City Public Schools", kc, handmade.KESSBY_MO, None) in listings
    assert ("Kessby City Kansas Public Schools", kc, None, "SYN-KS-KESS") in listings
    # Bristol's, as Tennessee and Virginia write them.
    assert ("Bristmoor", ("TN", "VA"), None, None) in listings
    assert ("Bristmoor City Schools", ("TN", "VA"), None, None) in listings
    assert ("Bristmoor Virginia Public Schools", ("TN", "VA"), None, "SYN-VA-BRIS") in listings
    # A legal form one state writes says nothing of the state.
    assert ("Covermoor Independent Schools", ("KY", "OH"), None, None) in listings
    records = {record.id: record for record in handmade.RECORDS}
    twins = [("SYN-MO-KESS", "SYN-KS-KESS"), ("SYN-TN-BRIS", "SYN-VA-BRIS")]
    for first, second in twins:
        one, two = records[first].point, records[second].point
        assert one is not None
        assert two is not None
        # So near that no point beside one tells them apart.
        assert index.haversine_km(one, two) < MatchSettings().near_slack_km


def test_generated_across_cases_are_matched(
    background_matcher: Matcher, generated_cases: list[Case]
) -> None:
    """Every generated listing for a town whose twin across a state line bears its name is right."""
    cases = [case for case in generated_cases if case.note == ACROSS_NOTE]
    assert len(cases) >= 50, len(cases)
    assert sum(1 for c in cases if c.expected is None and len(c.states) == 2) >= 25
    assert sum(1 for c in cases if c.expected is not None and c.near is not None) >= 3
    assert sum(1 for c in cases if c.expected is not None and len(c.states) == 1) >= 5
    wrong = [
        (case.listing, case.states, case.near, case.expected, got)
        for case in cases
        if (got := _target_id(_run(background_matcher, case))) != case.expected
    ]
    assert not wrong


def test_the_fixture_sees_namesakes_across_states_told_apart_by_wording(
    monkeypatch: pytest.MonkeyPatch,
    fixture_matcher: Matcher,
    background_matcher: Matcher,
    generated_cases: list[Case],
) -> None:
    """Letting wording settle a tie across a state line takes Kansas's "Kessby City".

    That is what the matcher did before it knew each state writes its names its
    own way (:meth:`~snowlight.match.matcher.Matcher._undecided_across`). The
    fixture has to be able to fail if it did so again: precision falls under
    the bar on the hand-written cases and on the generated ones, and far under
    it on the listings written for namesakes across a state line.
    """
    monkeypatch.setattr(matcher_module.Matcher, "_across_states", lambda *_args: False)
    monkeypatch.setattr(matcher_module.Matcher, "_namesakes_across", lambda *_args: [])
    # Two states' districts lie in two counties too, where wording decides no tie
    # either (:meth:`~snowlight.match.matcher.Matcher._apart`): that goes as well.
    monkeypatch.setattr(matcher_module.Matcher, "_apart", lambda *_args: False)
    hand = _tally((case, _run(fixture_matcher, case)) for case in handmade.CASES)
    assert hand.precision < MIN_PRECISION, hand
    across = _tally((c, _run(fixture_matcher, c)) for c in _across_cases(handmade.CASES))
    assert across.precision < MIN_PRECISION - 0.2, across
    generated = _tally((case, _run(background_matcher, case)) for case in generated_cases)
    assert generated.precision < MIN_PRECISION, generated
    twins = [c for c in generated_cases if c.note == ACROSS_NOTE]
    twin_tally = _tally((case, _run(background_matcher, case)) for case in twins)
    assert twin_tally.precision < MIN_PRECISION - 0.2, twin_tally


def test_the_fixture_sees_namesakes_across_states_scored_apart(
    monkeypatch: pytest.MonkeyPatch, fixture_matcher: Matcher
) -> None:
    """With ties across states left to distance but namesakes scored apart, wording still decides.

    Florida's ``"ESCAMBRY"`` implies ``County``, which Alabama's ``"Escambry
    County"`` says; ``"Escambry Schools"`` fits Florida's better only because of
    how each state writes it. The fixture has to be able to fail if a namesake
    outside the tie were no rival.
    """
    monkeypatch.setattr(matcher_module.Matcher, "_namesakes_across", lambda *_args: [])
    across = _tally((c, _run(fixture_matcher, c)) for c in _across_cases(handmade.CASES))
    assert across.precision < MIN_PRECISION - 0.05, across


def _own_school_cases(cases: Iterable[Case]) -> list[Case]:
    """The listings for a school named as the listing, beside a district whose name is not."""
    return [
        case
        for case in cases
        if case.note.startswith((handmade.OWN_SCHOOL, handmade.OWN_SCHOOL_NEGATIVE))
    ]


def _plain(name: str) -> str:
    return name.replace(".", "").casefold()


def test_handmade_cases_name_schools_their_districts_names_do_not_say() -> None:
    """A school the listing names word for word, beside a district that leaves a word out."""
    cases = _own_school_cases(handmade.CASES)
    records = {record.id: record for record in handmade.RECORDS}
    schools = [c for c in cases if c.expected and records[c.expected].kind == "school"]
    negatives = [c for c in cases if c.expected is None]
    districts = [c for c in cases if c.expected and records[c.expected].kind == "district"]
    assert len(schools) >= 6, [c.listing for c in schools]
    assert len(negatives) >= 5, [c.listing for c in negatives]
    assert len(districts) >= 10, [c.listing for c in districts]
    named = [(c, records[c.expected or ""]) for c in schools]
    for case in negatives:
        # The school the listing names word for word, which is no match only
        # because a word marks it down or a sibling school is as close.
        (school,) = [r for r in handmade.RECORDS if _plain(r.name) == _plain(case.listing)]
        named.append((case, school))
    for case, school in named:
        if case.note.endswith(("system", "the county's")):
            # A county's school named for a city whose system is two districts.
            continue
        # Each school's district runs other schools, which the district would mark.
        siblings = [r for r in handmade.RECORDS if r.district_id == school.district_id]
        assert len(siblings) >= 2, school.name
    listings = {(c.listing, c.states, c.expected) for c in cases}
    assert ("Cheddby Co Central", ("TN",), "SYN-TN-CHDCC") in listings
    assert ("Cheddby County Schools", ("TN",), "SYN-TN-CHDC") in listings
    assert ("Selmby Independent", ("CA",), None) in listings
    assert ("Minerby Wells Schools", ("TX",), "SYN-TX-MINW") in listings
    assert ("Petalby Community", ("CA",), None) in listings


@pytest.mark.parametrize(
    ("rule", "off", "leaked"),
    [
        (
            "_says_district",
            lambda *_args: True,
            {
                "Cheddby Co Central": "SYN-TN-CHDC",
                "Lakeby Central": "SYN-OH-LAKL",
                "CYPRBY-FAIRMONT J J A E P": "SYN-TX-CYFA",
                "Selmby Independent": "SYN-CA-SELU",
                "Waterby Junior": "SYN-CA-WATU",
            },
        ),
        ("_school_over_system", lambda *_args: False, {"Petalby Community": "SYN-CA-PETE"}),
        ("_named_whole", lambda *_args: False, {"District 917 - ALC - IS": "SYN-MN-I917"}),
    ],
)
def test_the_fixture_sees_a_district_taken_for_its_own_school(
    monkeypatch: pytest.MonkeyPatch,
    fixture_matcher: Matcher,
    rule: str,
    off: object,
    leaked: dict[str, str],
) -> None:
    """Without each rule a school's name marks its whole district (or its city's system).

    ``"Cheddby Co Central"`` is the county's Central High School, and the
    district ``"Cheddby County"`` says every word of it but the legal-form word
    ``Central``: read as the district, one school's closing would mark every
    school of the county. The fixture has to be able to fail on that.
    """
    monkeypatch.setattr(matcher_module.Matcher, rule, off)
    cases = _own_school_cases(handmade.CASES)
    results = {case.listing: _run(fixture_matcher, case) for case in cases}
    for listing, district in leaked.items():
        assert district in _targets(results[listing]), (listing, results[listing].detail)
    tally = _tally((case, results[case.listing]) for case in cases)
    assert tally.precision < MIN_PRECISION, tally


# -- a place word that begins or holds a school's name ------------------------------


def _leading_cases(cases: Iterable[Case]) -> tuple[list[Case], list[Case]]:
    """The listings for a school whose name holds a place word: with it, and without."""
    said = [
        case
        for case in cases
        if case.note in {LEADING_NOTE, LEADING_NEGATIVE}
        or case.note.startswith((handmade.LEADING, handmade.LEADING_NEGATIVE))
    ]
    return (
        [case for case in said if case.expected is not None],
        [case for case in said if case.expected is None],
    )


def test_handmade_cases_leave_out_a_school_s_place_word() -> None:
    """ "Christian Academy" beside "Village Christian Academy", and the bar's other shapes."""
    named, unnamed = _leading_cases(handmade.CASES)
    assert len(named) >= MIN_HARD_NEGATIVES, [c.listing for c in named]
    assert len(unnamed) >= MIN_HARD_NEGATIVES, [c.listing for c in unnamed]
    listings = {case.listing for case in unnamed}
    assert {"Christian Academy", "Country Day School", "Academy", "Kids Academy"} <= listings
    records = {record.id: record.name for record in handmade.RECORDS}
    assert records["SYN-NC-VCA"] == "VILLAGE CHRISTIAN ACADEMY"
    assert records["SYN-CA-TCD"] == "TOWN & COUNTRY DAY SCHOOL"
    assert records["SYN-MO-CA"] == "CITY ACADEMY"
    assert records["SYN-IN-KCA"] == "KID CITY ACADEMY"


def test_generated_cases_leave_out_a_school_s_place_word(
    background_matcher: Matcher, generated_cases: list[Case]
) -> None:
    named, unnamed = _leading_cases(generated_cases)
    assert len(named) >= MIN_HARD_NEGATIVES // 2, len(named)
    assert len(unnamed) >= MIN_HARD_NEGATIVES * 3, len(unnamed)
    wrong = [
        (case.listing, case.states, case.expected, got)
        for case in (*named, *unnamed)
        if (got := _target_id(_run(background_matcher, case))) != case.expected
    ]
    assert not wrong


def _anywhere(_words: Sequence[str], classes: Sequence[tuple[int, str]], i: int) -> bool:
    """The normalizer before it knew a qualifier ends a name: one is so wherever it stands.

    But for a name of nothing else (``"Village Elementary"``), as it was then.
    """
    return i > 0 or any(word_class == normalize._IS_WORD for word_class, _text in classes[1:])


def test_the_fixture_sees_a_leading_place_word_read_as_a_qualifier(
    monkeypatch: pytest.MonkeyPatch,
    background: list[SyntheticRecord],
    generated_cases: list[Case],
) -> None:
    """Read as a qualifier a list may leave out, "Village" makes "Christian Academy" its school's.

    The fixture has to be able to fail on that bug: with a place word a qualifier
    wherever it stands, and a school's that a listing leaves out costing no more
    than a district's (as both were), "Christian Academy" takes "Village Christian
    Academy", "Academy" takes "City Academy" and "Kid Academy" takes "Kid City
    Academy", and precision falls under the bar on both sets. Either rule alone
    keeps most of them out (:data:`~snowlight.match.index.PLACE_LEFT_OUT` guards a
    qualifier a school's name ends with).
    """
    try:
        with monkeypatch.context() as patch:
            patch.setattr(normalize, "qualifies", _anywhere)
            patch.setattr(index, "PLACE_LEFT_OUT", index.TOWN_LEFT_OUT)
            normalize.clear_caches()
            fixture = Matcher(Directory([*handmade.RECORDS, *(item.record for item in background)]))
            plain = Matcher(Directory(item.record for item in background))
            hand = _tally((case, _run(fixture, case)) for case in handmade.CASES)
            generated = _tally((case, _run(plain, case)) for case in generated_cases)
            _, unnamed = _leading_cases(handmade.CASES)
            leaked = {
                case.listing: result.target.name
                for case in unnamed
                if (result := _run(fixture, case)).target is not None
            }
    finally:
        normalize.clear_caches()
    assert hand.precision < MIN_PRECISION, hand
    assert generated.precision < MIN_PRECISION, generated
    assert leaked.get("Christian Academy") == "VILLAGE CHRISTIAN ACADEMY"
    assert leaked.get("Kid Academy") == "KID CITY ACADEMY"
    assert len(leaked) >= MIN_HARD_NEGATIVES // 2, leaked


def test_the_fixture_sees_a_point_pick_among_namesakes_in_the_market(
    monkeypatch: pytest.MonkeyPatch,
    fixture_matcher: Matcher,
    background_matcher: Matcher,
    generated_cases: list[Case],
) -> None:
    """Were a point to break any tie, it would pick one of two schools of one name in a market.

    That is what the matcher did before it asked where the rest lie
    (:meth:`~snowlight.match.matcher.Matcher._break_tie`): a Boston list's
    ``"St. John School"`` went to the one 1 km from its point over the one
    17 km off, both in its counties. The fixture has to be able to fail if it
    did so again: precision falls far under the bar on the listings read near
    a point, hand-written and generated.
    """
    monkeypatch.setattr(matcher_module.Matcher, "_outside_market", lambda *_args: True)
    near = _tally((c, _run(fixture_matcher, c)) for c in handmade.CASES if c.near is not None)
    assert near.precision < MIN_PRECISION - 0.1, near
    same = [c for c in handmade.CASES if c.note.startswith(handmade.SAME_NAME_NEGATIVE)]
    wrong = {c.listing for c in same if _targets(_run(fixture_matcher, c))}
    assert {
        "St. John School",
        "Walsh Elementary School",
        "Liberty Elementary School",
        "Sacred Heart",
        "St. Mary's School",
    } <= wrong, wrong
    generated = _tally(
        (case, _run(background_matcher, case)) for case in generated_cases if case.near is not None
    )
    assert generated.precision < MIN_PRECISION - 0.1, generated


def _level_cases(cases: Iterable[Case]) -> tuple[list[Case], list[Case]]:
    """The listings by a level a school's name leaves out: those that name a record, and not."""
    said = [
        case
        for case in cases
        if case.note in {LEVEL_NOTE, LEVEL_NEGATIVE}
        or case.note.startswith((handmade.LEVEL, handmade.LEVEL_NEGATIVE))
    ]
    return (
        [case for case in said if case.expected is not None],
        [case for case in said if case.expected is None],
    )


def test_handmade_cases_name_schools_by_levels_their_names_leave_out() -> None:
    """ "St. Joseph Elementary" beside PK-8 "ST JOSEPH SCHOOL"s, and the rest of the bar's shape."""
    named, unnamed = _level_cases(handmade.CASES)
    assert len(unnamed) >= MIN_HARD_NEGATIVES, [c.listing for c in unnamed]
    assert len(named) >= MIN_HARD_NEGATIVES // 2, [c.listing for c in named]
    listings = {case.listing for case in unnamed}
    assert {
        "St. Joseph Elementary",
        "Lincoln Elementary",
        "Devonmoor Elementary School",
        "St. John Lutheran Preschool",
        "Hallby Elementary",
    } <= listings
    records = {record.id: record for record in handmade.RECORDS}
    # NCES leaves the level out of these names; their grades say it.
    for record_id, name, low, high in (
        ("SYN-MA-SJND", "ST JOSEPH SCHOOL", "PK", "08"),
        ("SYN-MA-SJWK", "ST JOSEPH SCHOOL", "PK", "08"),
        ("SYN-MA-MBLN", "Lincoln", "KG", "05"),
        ("SYN-IL-ORDV", "Devonmoor School", "KG", "05"),
        ("SYN-MA-PLDV", "Devonby School", "06", "08"),
        ("SYN-MA-HLBK", "HALLBY SCHOOL", "KG", "12"),
    ):
        record = records[record_id]
        assert (record.name, record.grade_low, record.grade_high) == (name, low, high)
    # Each name that says the level has a namesake in the same market that does not.
    assert records["SYN-MA-SJMD"].name == "ST JOSEPH ELEMENTARY SCHOOL"
    assert records["SYN-MA-WBLN"].name == "Lincoln Elementary"


def test_generated_level_cases_are_matched(
    background: list[SyntheticRecord], background_matcher: Matcher, generated_cases: list[Case]
) -> None:
    named, unnamed = _level_cases(generated_cases)
    assert len(named) >= MIN_HARD_NEGATIVES, len(named)
    assert len(unnamed) >= MIN_HARD_NEGATIVES * 3, len(unnamed)
    records = {item.record.id: item.record for item in background}
    # Some name a school whose name says no level.
    assert sum(records[c.expected or ""].name.split()[-1] in {"School", "SCHOOL"} for c in named)
    wrong = [
        (case.listing, case.states, case.counties, case.expected, got)
        for case in (*named, *unnamed)
        if (got := _target_id(_run(background_matcher, case))) != case.expected
    ]
    assert not wrong


def _grades_unread(monkeypatch: pytest.MonkeyPatch) -> None:
    """The matcher before it read a school's grades: a level its name leaves out costs it."""
    monkeypatch.setattr(index, "fit", lambda _levels, _span: Fit.UNKNOWN)
    unread = (index.LEVEL_ONLY_LISTING, index.LEVEL_ONLY_LISTING)
    monkeypatch.setitem(index._GRADES_FACTORS, Fit.UNKNOWN, unread)


def test_the_fixture_sees_a_level_a_school_s_name_leaves_out(
    monkeypatch: pytest.MonkeyPatch,
    fixture_matcher: Matcher,
    background_matcher: Matcher,
    generated_cases: list[Case],
) -> None:
    """With grades unread, "St. Joseph Elementary" takes the one school whose name spells it.

    That is what the matcher did before it read a school's grades: a name that
    left out the listing's level cost 0.82, so the namesake whose name said it
    won at 1.00 over the PK-8 ``"ST JOSEPH SCHOOL"``s beside it, and
    ``"Lincoln Elementary"`` over the K-5 ``"Lincoln"``. The fixture has to be
    able to fail on that: precision falls under the bar on both sets.
    """
    _grades_unread(monkeypatch)
    hand = _tally((case, _run(fixture_matcher, case)) for case in handmade.CASES)
    generated = _tally((case, _run(background_matcher, case)) for case in generated_cases)
    assert hand.precision < MIN_PRECISION, hand
    assert generated.precision < MIN_PRECISION, generated
    _, unnamed = _level_cases(handmade.CASES)
    leaked = {
        case.listing: result.target.name
        for case in unnamed
        if (result := _run(fixture_matcher, case)).target is not None
    }
    assert leaked.get("St. Joseph Elementary") == "ST JOSEPH ELEMENTARY SCHOOL"
    assert leaked.get("Lincoln Elementary") == "Lincoln Elementary"
    assert len(leaked) >= MIN_HARD_NEGATIVES // 2, leaked


def _person_cases(cases: Iterable[Case]) -> tuple[list[Case], list[Case]]:
    """The listings for a school named for a person: those that name a record, and not."""
    said = [
        case
        for case in cases
        if case.note in {FORENAME_NOTE, FORENAME_NEGATIVE}
        or case.note.startswith((handmade.PERSON, handmade.PERSON_NEGATIVE))
    ]
    return (
        [case for case in said if case.expected is not None],
        [case for case in said if case.expected is None],
    )


def _plural_cases(cases: Iterable[Case]) -> tuple[list[Case], list[Case]]:
    """The listings by a word with a plural's s or without: those that name a record, and not."""
    said = [
        case
        for case in cases
        if case.note in {PLURAL_NOTE, PLURAL_NEGATIVE}
        or case.note.startswith((handmade.PLURAL, handmade.PLURAL_NEGATIVE))
    ]
    return (
        [case for case in said if case.expected is not None],
        [case for case in said if case.expected is None],
    )


def test_handmade_cases_name_schools_by_their_people_s_surnames() -> None:
    """Hard negatives for a surname two schools' people share, in one county, and plurals.

    One school's name gives initials, the other's a forename (and its initial): a
    listing of the surname alone names both, and so neither.
    """
    named, unnamed = _person_cases(handmade.CASES)
    assert len(named) >= MIN_HARD_NEGATIVES, [c.listing for c in named]
    assert len(unnamed) >= MIN_HARD_NEGATIVES, [c.listing for c in unnamed]
    listings = {(c.listing, c.states, c.expected) for c in handmade.CASES}
    assert ("Kennaby Middle School", ("MA",), None) in listings
    assert ("Johnby Elementary", ("TX",), None) in listings
    assert ("Garzby Middle School", ("TX",), None) in listings
    assert ("Whiteby Elementary", ("CA",), None) in listings
    assert ("Watby Elementary", ("LA",), None) in listings
    assert ("Kenby Elementary", ("CA",), None) in listings
    assert ("B L Garzby Middle School", ("TX",), "SYN-TX-BLGZ") in listings
    assert ("Burbby Elementary", ("CA",), "SYN-CA-BRBL") in listings
    records = {record.id: record.name for record in handmade.RECORDS}
    # Each hard negative's county holds one school of the surname with initials and
    # one with a forename, at one level.
    assert records["SYN-MA-JFKN"].startswith("J F ")
    assert records["SYN-MA-JFKW"].startswith("John F ")
    assert records["SYN-TX-LBJE"].startswith("L B ")
    assert records["SYN-TX-LYBJ"].startswith("LYNDON B ")
    assert records["SYN-CA-RDWH"].startswith("R. D. ")
    assert records["SYN-CA-CHWH"].startswith("Charles ")
    plural, not_plural = _plural_cases(handmade.CASES)
    assert len(plural) >= 4, [c.listing for c in plural]
    assert len(not_plural) >= 6, [c.listing for c in not_plural]


def test_generated_person_and_plural_cases_are_matched(
    background: list[SyntheticRecord], background_matcher: Matcher, generated_cases: list[Case]
) -> None:
    named, unnamed = _person_cases(generated_cases)
    assert len(named) >= MIN_HARD_NEGATIVES, len(named)
    assert len(unnamed) >= MIN_HARD_NEGATIVES, len(unnamed)
    plural, not_plural = _plural_cases(generated_cases)
    assert len(plural) >= MIN_HARD_NEGATIVES, len(plural)
    assert len(not_plural) >= MIN_HARD_NEGATIVES // 2, len(not_plural)
    records = {item.record.id: item for item in background}
    # Some name a school of a surname alone of it whose forenames are a forename and
    # an initial, and some one whose forenames NCES bracketed.
    assert any(records[c.expected or ""].identity.given[:1] != () for c in named)
    assert any(records[c.expected or ""].identity.bracketed for c in named)
    wrong = [
        (case.listing, case.states, case.counties, case.expected, got)
        for case in (*named, *unnamed, *plural, *not_plural)
        if (got := _target_id(_run(background_matcher, case))) != case.expected
    ]
    assert not wrong


def _forenames_unread(monkeypatch: pytest.MonkeyPatch) -> None:
    """The matcher before it read a person's forenames: initials weigh little, forenames much."""
    monkeypatch.setattr(index.NameIndex, "_person", lambda _self, _query, _other: None)


def test_the_fixture_sees_forenames_left_out(
    monkeypatch: pytest.MonkeyPatch,
    fixture_matcher: Matcher,
    background_matcher: Matcher,
    generated_cases: list[Case],
) -> None:
    """With forenames unread, "Kennedy Middle School" takes the school with initials.

    That is what the matcher did before: initials weighed an initial's weight and a
    spelled forename a word's, so ``"J F Kennedy Middle School"`` won at 0.96 over
    ``"John F Kennedy Middle"`` at 0.71. The fixture has to be able to fail on that:
    precision falls under the bar on both sets.
    """
    _forenames_unread(monkeypatch)
    hand = _tally((case, _run(fixture_matcher, case)) for case in handmade.CASES)
    generated = _tally((case, _run(background_matcher, case)) for case in generated_cases)
    assert hand.precision < MIN_PRECISION, hand
    assert generated.precision < MIN_PRECISION, generated
    _, unnamed = _person_cases(handmade.CASES)
    leaked = {
        case.listing: result.target.name
        for case in unnamed
        if (result := _run(fixture_matcher, case)).target is not None
    }
    assert leaked.get("Kennaby Middle School") == "J F Kennaby Middle School", leaked
    assert leaked.get("Johnby Elementary") == "L B JOHNBY EL", leaked


def test_the_fixture_sees_plurals_folded(
    monkeypatch: pytest.MonkeyPatch,
    fixture_matcher: Matcher,
    background_matcher: Matcher,
    generated_cases: list[Case],
) -> None:
    """With a plural's ``s`` folded away, "Park Elementary" takes "PARKS EL" at 1.00.

    The fixture has to be able to fail on that: precision falls under the bar on the
    listings of such words, handmade and generated.
    """
    monkeypatch.setattr(index, "plurals_differ", lambda _form, _other: False)
    said, not_said = _plural_cases(handmade.CASES)
    hand = _tally((case, _run(fixture_matcher, case)) for case in (*said, *not_said))
    plural, not_plural = _plural_cases(generated_cases)
    generated = _tally((case, _run(background_matcher, case)) for case in (*plural, *not_plural))
    assert hand.precision < MIN_PRECISION, hand
    assert generated.precision < MIN_PRECISION, generated
    leaked = {
        case.listing: result.target.name
        for case in handmade.CASES
        if case.note.startswith(handmade.PLURAL_NEGATIVE)
        and (result := _run(fixture_matcher, case)).target is not None
    }
    assert leaked.get("Park Elementary") == "PARKS EL", leaked
    assert leaked.get("Brook Elementary") == "Brooks School", leaked
