"""School systems NCES splits into several districts: finding them, and matching their listings.

Every record here is SYNTHETIC (see :mod:`match.handmade`, ``SYSTEM_RECORDS``):
made-up towns in NCES's naming habits, with ``SYN-`` ids.
"""

from dataclasses import replace

import pytest

from match import handmade
from match.synthetic import SYSTEM_NEGATIVE, SYSTEM_NOTE, Case
from snowlight.match import Aliases, Directory, DirectoryRecord, Matcher, MatchResult, Reason
from snowlight.match import matcher as matcher_module
from snowlight.match import systems as systems_module
from snowlight.match.index import NameIndex, Scope, Scored
from snowlight.match.normalize import clean_listing, listing_forms
from snowlight.match.systems import (
    CITY,
    LEVELS,
    OFFICE,
    SchoolSystem,
    SystemName,
    Systems,
    names_a_system,
    office_of,
)


def _ids(records: tuple[DirectoryRecord, ...]) -> list[str]:
    return [record.id for record in records]


def _system(matcher: Matcher, record_id: str) -> SchoolSystem | None:
    return matcher.systems.of(matcher.index.index_of(record_id))


def _members(matcher: Matcher, system: SchoolSystem) -> list[str]:
    return [matcher.index.records[m].id for m in system.members]


# -- finding systems ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("record_id", "kind", "members"),
    [
        ("SYN-MT-TAMSE", LEVELS, ["SYN-MT-TAMSE", "SYN-MT-TAMSH"]),
        ("SYN-MT-GLAH", OFFICE, ["SYN-MT-KELE", "SYN-MT-GLAH"]),
        ("SYN-MT-CUSH", OFFICE, ["SYN-MT-MILE", "SYN-MT-CUSH"]),
        ("SYN-AZ-PHNH", LEVELS, ["SYN-AZ-PHNE", "SYN-AZ-PHNH"]),
        ("SYN-CA-PETE", LEVELS, ["SYN-CA-PETE", "SYN-CA-PETH"]),
        ("SYN-IL-STRH", LEVELS, ["SYN-IL-STRE", "SYN-IL-STRH"]),
        (
            "SYN-NY-BC75",
            CITY,
            ["SYN-NY-BC01", "SYN-NY-BC02", "SYN-NY-BC10", "SYN-NY-BC11", "SYN-NY-BC75"],
        ),
    ],
)
def test_the_directory_s_systems(
    handmade_matcher: Matcher, record_id: str, kind: str, members: list[str]
) -> None:
    system = _system(handmade_matcher, record_id)
    assert system is not None
    assert system.kind == kind
    assert _members(handmade_matcher, system) == members


@pytest.mark.parametrize(
    "record_id",
    [
        # An office each: run apart.
        "SYN-MT-BOUE",
        "SYN-MT-JEFH",
        # Two elementary districts of one name, in two counties.
        "SYN-MT-HARA",
        # A union high school district of the name whose office is in another town.
        "SYN-CA-MERE",
        "SYN-CA-MERH",
        # Another elementary district of the town, with an office of its own.
        "SYN-MT-EVRE",
        # A charter school of the city's name.
        "SYN-NY-BCCA",
        # A district and a school of one name are no two districts.
        "SYN-MT-TAMMS",
    ],
)
def test_pairs_that_are_no_system(handmade_matcher: Matcher, record_id: str) -> None:
    assert _system(handmade_matcher, record_id) is None


def test_the_systems_are_counted_once(handmade_matcher: Matcher) -> None:
    found = list(handmade_matcher.systems)
    assert len(found) == len(handmade_matcher.systems)
    assert len({system.members for system in found}) == len(found)
    members = [member for system in found for member in system.members]
    assert len(members) == len(set(members))


def test_a_system_of_one_name_at_one_office_answers_to_each_name(
    handmade_matcher: Matcher,
) -> None:
    petalby = _system(handmade_matcher, "SYN-CA-PETE")
    assert petalby is not None
    assert {name.qualifiers for name in petalby.names} == {frozenset(), frozenset({"city"})}
    tamsby = _system(handmade_matcher, "SYN-MT-TAMSE")
    assert tamsby is not None
    assert len(tamsby.names) == 1
    phenby = _system(handmade_matcher, "SYN-AZ-PHNE")
    assert phenby is not None
    assert len(phenby.names) == 1  # an office each: only the name they share


def test_a_system_keeps_the_legal_words_every_district_says(handmade_matcher: Matcher) -> None:
    kelburn = _system(handmade_matcher, "SYN-CA-KELE")
    assert kelburn is not None
    assert kelburn.legal == {"union"}
    phenby = _system(handmade_matcher, "SYN-AZ-PHNE")
    assert phenby is not None
    assert phenby.legal == frozenset()
    assert handmade_matcher.systems.saying(phenby, frozenset({"union", "school"})) == (
        handmade_matcher.index.index_of("SYN-AZ-PHNH"),
    )
    assert handmade_matcher.systems.saying(phenby, frozenset()) == phenby.members


def test_an_office_is_a_state_and_a_point() -> None:
    record = handmade.RECORDS[0]
    assert office_of(record) == (record.state, record.lat, record.lon)
    assert office_of(replace(record, lat=None, lon=None)) is None


def test_a_directory_without_offices_has_no_office_systems() -> None:
    records = [
        replace(record, lat=None, lon=None)
        for record in handmade.SYSTEM_RECORDS
        if record.id in {"SYN-MT-KELE", "SYN-MT-GLAH"}
    ]
    systems = Systems(Matcher(Directory(records)).index)
    assert len(systems) == 0


def test_an_office_pair_whose_elementary_district_has_no_town_is_no_system() -> None:
    records = [
        replace(record, city=None) if record.id == "SYN-MT-KELE" else record
        for record in handmade.SYSTEM_RECORDS
        if record.id in {"SYN-MT-KELE", "SYN-MT-GLAH"}
    ]
    assert len(Systems(Matcher(Directory(records)).index)) == 0


def test_one_geographic_district_is_no_city_s_system() -> None:
    records = [r for r in handmade.SYSTEM_RECORDS if r.id in {"SYN-NY-BC01", "SYN-NY-PS101"}]
    assert len(Systems(Matcher(Directory(records)).index)) == 0


# -- what a listing says ----------------------------------------------------------------


def _form(listing: str) -> tuple[bool, SystemName, frozenset[str]]:
    clean = clean_listing(listing)
    forms = listing_forms(clean.text, district_hint=clean.all_schools)
    name = SystemName(frozenset({"tamsby"}), "tamsby", frozenset({"city"}))
    return names_a_system(forms.district, school=forms.hint.value == "school"), name, forms.legal


@pytest.mark.parametrize(
    "listing",
    [
        "Tamsby Public Schools",
        "Tamsby",
        "Tamsby School District",
        "TAMSBY SCHOOLS (Closed)",
        "Tamsby School District 2",  # a number: see Systems.numbered
    ],
)
def test_a_system_s_name(listing: str) -> None:
    assert _form(listing)[0]


@pytest.mark.parametrize(
    "listing",
    [
        "Tamsby Elementary",  # a level
        "RSU 13 Tamsby",  # a district code
        "Tamsby Catholic Schools",  # an affiliation
        "Tamsby School",  # one school
        "Tamsby Academy",  # one school's noun
        "School of Tamsby",  # one school's order
        "Schools",  # nothing left
    ],
)
def test_not_a_system_s_name(listing: str) -> None:
    assert not _form(listing)[0]


def test_a_system_s_name_may_leave_out_its_town_s_city() -> None:
    town = SystemName(frozenset({"mileby"}), "mileby", frozenset({"city"}))
    city = SystemName(frozenset({"bronby"}), "bronby", frozenset({"city"}), frozenset())

    def says(name: SystemName, listing: str) -> bool:
        form = listing_forms(clean_listing(listing).text).district
        return name.said_by(form, form.token_set)

    assert says(town, "Mileby City Schools")
    assert says(town, "Mileby Schools")
    assert not says(town, "Mileby County Schools")
    assert not says(town, "Tamsby City Schools")
    assert says(city, "Bronby City Schools")
    assert not says(city, "Bronby Schools")


# -- matching a system's listing --------------------------------------------------------


def test_a_system_s_listing_names_every_district(handmade_matcher: Matcher) -> None:
    result = handmade_matcher.match("Kellby Public Schools", states=["MT"])
    assert result.reason is Reason.SYSTEM
    assert result.accepted
    assert result.target is not None
    assert result.target.id == "SYN-MT-KELE"
    assert _ids(result.targets) == ["SYN-MT-KELE", "SYN-MT-GLAH"]
    assert "names the 2 districts of one system" in result.detail
    schools = handmade_matcher.expand(result)
    assert _ids(schools) == ["SYN-MT-KELMS", "SYN-MT-GLAHS", "SYN-MT-RPHS"]
    # The high school district's schools are the listing's too, the other
    # elementary district's of the town are not.
    assert "SYN-MT-EVRS" not in _ids(schools)


def test_a_city_s_listing_names_all_its_districts(handmade_matcher: Matcher) -> None:
    result = handmade_matcher.match("Bronby City DOE", states=["NY"])
    assert result.reason is Reason.SYSTEM
    assert len(result.targets) == 5
    assert "and 2 more" in result.detail
    schools = _ids(handmade_matcher.expand(result))
    assert schools == [
        "SYN-NY-PS101",
        "SYN-NY-PS102",
        "SYN-NY-IS210",
        "SYN-NY-PS211",
        "SYN-NY-P751",
        "SYN-NY-P752",
    ]
    assert "SYN-NY-BCCAS" not in schools  # the charter school of the city's name


def test_expand_covers_each_school_once_and_nothing_for_no_match(
    handmade_matcher: Matcher,
) -> None:
    result = handmade_matcher.match("Tamsby Public Schools", states=["MT"])
    doubled = replace(result, targets=(*result.targets, *result.targets))
    assert handmade_matcher.expand(doubled) == handmade_matcher.expand(result)
    none = handmade_matcher.match("Harlby Public Schools", states=["MT"])
    assert not none.accepted
    assert handmade_matcher.expand(none) == ()
    # A record or an id expands as it always has.
    assert _ids(handmade_matcher.expand("SYN-MT-TAMSH")) == ["SYN-MT-TAMHS"]


def test_a_result_s_targets_follow_its_target(handmade_matcher: Matcher) -> None:
    result = handmade_matcher.match("Tamsby Public Schools", states=["MT"])
    assert len(result.targets) == 2
    assert replace(result, target=None).targets == ()
    other = handmade_matcher.directory["SYN-OK-TAMS"]
    assert replace(result, target=other).targets == (other,)
    assert replace(result, confidence=0.9).targets == result.targets
    single = handmade_matcher.match("Tamsby Elementary", states=["MT"])
    assert single.target is not None
    assert single.targets == (single.target,)


def test_a_rival_outside_the_system_leaves_it_ambiguous(handmade_matcher: Matcher) -> None:
    result = handmade_matcher.match("Tamsby Public Schools", states=["MT", "OK"])
    assert result.reason is Reason.AMBIGUOUS
    assert result.targets == ()
    assert "'Tamsby Elem' (MT) and 'TAMSBY' (OK) tie by name across MT, OK" in result.detail
    ranked = [c.record.id for c in (result.best, *result.runners_up) if c is not None]
    assert ranked[:2] == ["SYN-MT-TAMSE", "SYN-OK-TAMS"]


def test_distance_breaks_a_tie_between_a_system_and_a_namesake(
    handmade_matcher: Matcher,
) -> None:
    """A market of two states with a town's system in one and its namesake in the other."""
    states = ["MT", "OK"]
    home = handmade_matcher.match("Tamsby Public Schools", states=states, near=handmade.TAMSBY)
    assert home.reason is Reason.SYSTEM
    assert _ids(home.targets) == ["SYN-MT-TAMSE", "SYN-MT-TAMSH"]
    assert "nearest of 2 tied names" in home.detail
    away = handmade_matcher.match("Tamsby Public Schools", states=states, near=(36.5, -97.6))
    assert away.reason is Reason.NEAREST
    assert _ids(away.targets) == ["SYN-OK-TAMS"]
    between = handmade_matcher.match("Tamsby Public Schools", states=states, near=(41.3, -104.0))
    assert between.targets == ()


def test_a_weak_system_reading_is_no_match(handmade_matcher: Matcher) -> None:
    """A system whose best district fits the listing too badly is not taken."""
    tamsby = _system(handmade_matcher, "SYN-MT-TAMSE")
    assert tamsby is not None
    member = Scored(tamsby.members[0], 0.5, 0.5)
    outcome = handmade_matcher._system_outcome(tamsby, member, [member], None, home=None)
    assert outcome is not None
    assert outcome.reason is Reason.WEAK
    assert not outcome.accepted
    assert outcome.joint == ()
    assert "names the 2 districts of one system" in outcome.detail


def test_a_number_nces_does_not_give_names_the_whole_system(handmade_matcher: Matcher) -> None:
    """Montana's districts carry no number in NCES's names: a list's number picks none."""
    result = handmade_matcher.match("Tamsby School District 2", states=["MT"])
    assert result.reason is Reason.SYSTEM
    assert _ids(result.targets) == ["SYN-MT-TAMSE", "SYN-MT-TAMSH"]
    # Where NCES numbers them, the number names one, or none.
    assert _ids(handmade_matcher.match("Strebby ESD 44", states=["IL"]).targets) == ["SYN-IL-STRE"]
    assert handmade_matcher.match("Strebby School District 45", states=["IL"]).targets == ()


def test_a_system_read_only_among_the_best(handmade_matcher: Matcher) -> None:
    """A system whose districts fit far worse than another candidate is no reading."""
    forms = listing_forms("Tamsby Public Schools")
    index = handmade_matcher.index
    other = Scored(index.index_of("SYN-OK-TAMS"), 1.0, 1.0)
    member = Scored(index.index_of("SYN-MT-TAMSE"), 0.5, 0.5)
    assert handmade_matcher._as_system([other, member], None, forms, home=None) is None
    # A listing that names two of its districts' words is none of its names.
    both = listing_forms("Tamsby Glacierby Schools")
    assert handmade_matcher._as_system([member], None, both, home=None) is None


def test_a_legal_form_word_one_district_says_names_that_one(handmade_matcher: Matcher) -> None:
    result = handmade_matcher.match("Phenby Union", states=["AZ"])
    assert result.reason is Reason.NAME
    assert _ids(result.targets) == ["SYN-AZ-PHNH"]
    assert "the only one whose legal form says 'union'" in result.detail
    ranked = [c.record.id for c in (result.best, *result.runners_up) if c is not None]
    assert "SYN-AZ-PHNE" in ranked  # for the queue, were it ever to go there


def test_a_legal_form_word_names_one_only_when_it_is_a_candidate(
    handmade_matcher: Matcher,
) -> None:
    petalby = _system(handmade_matcher, "SYN-CA-PETE")
    assert petalby is not None
    forms = listing_forms("Petalby Joint Union")
    high = handmade_matcher.index.index_of("SYN-CA-PETH")
    scored = [
        s for s in handmade_matcher.index.search(forms, Scope(frozenset({"CA"}))) if s.index != high
    ]
    assert handmade_matcher._one_of_system(petalby, high, scored, None, forms) is None


def test_a_legal_form_word_no_one_district_says_names_none_of_them(
    handmade_matcher: Matcher,
) -> None:
    index = handmade_matcher.index
    elementary = Scored(index.index_of("SYN-AZ-PHNE"), 0.95, 0.95)
    # "Independent": neither district says it, so it picks neither.
    isd = listing_forms("Phenby ISD")
    assert handmade_matcher._as_system([elementary], None, isd, home=None) is None
    # "Union": the one that says it is no candidate here.
    union = listing_forms("Phenby Union")
    assert handmade_matcher._as_system([elementary], None, union, home=None) is None


def test_a_system_in_a_listing_s_context_part(handmade_matcher: Matcher) -> None:
    """A school beside its city's name: the city's schools are all its districts'."""
    result = handmade_matcher.match("IS 210 Nell Pratt - Bronby City", states=["NY"])
    assert result.target is not None
    assert result.target.id == "SYN-NY-IS210"
    assert result.reason is Reason.CONTEXT
    assert "and 4 more" in result.detail


def test_a_system_accepted_in_its_counties_stays_so_beside_them(
    handmade_matcher: Matcher,
) -> None:
    result = handmade_matcher.match(
        "Mileby City Public Schools", states=["MT"], counties=[handmade.SYSTEM_MT_B]
    )
    assert result.reason is Reason.SYSTEM
    assert _ids(result.targets) == ["SYN-MT-MILE", "SYN-MT-CUSH"]


# -- aliases to several records ---------------------------------------------------------


def test_an_alias_may_pin_a_listing_to_several_records(handmade_directory: Directory) -> None:
    aliases = Aliases({"wxyz": {"ksd5": ("SYN-MT-KELE", "SYN-MT-GLAH")}})
    matcher = Matcher(handmade_directory, aliases=aliases)
    pinned = matcher.match("KSD5", states=["MT"], market="wxyz")
    assert pinned.reason is Reason.ALIAS
    assert _ids(pinned.targets) == ["SYN-MT-KELE", "SYN-MT-GLAH"]
    assert pinned.detail.endswith("to 2 records")
    assert _ids(matcher.expand(pinned)) == ["SYN-MT-KELMS", "SYN-MT-GLAHS", "SYN-MT-RPHS"]
    # Without the market, the initials name nothing.
    assert matcher.match("KSD5", states=["MT"]).targets == ()


def test_an_alias_with_an_unknown_id_is_not_taken_at_all(handmade_directory: Directory) -> None:
    aliases = Aliases({"wxyz": {"ksd5": ("SYN-MT-KELE", "SYN-GONE")}})
    result = Matcher(handmade_directory, aliases=aliases).match(
        "KSD5", states=["MT"], market="wxyz"
    )
    assert result.reason is Reason.ALIAS_UNKNOWN
    assert result.targets == ()
    assert "SYN-GONE" in result.detail
    assert "SYN-MT-KELE" not in result.detail


# -- the fixture sees each rule ---------------------------------------------------------

_SYSTEM_NOTES = (handmade.SYSTEM, handmade.SYSTEM_NEGATIVE)


def _system_cases() -> list[Case]:
    return [c for c in handmade.CASES if c.note.startswith(_SYSTEM_NOTES) or c.also]


def _wrong(matcher: Matcher, cases: list[Case]) -> list[str]:
    return [
        case.listing
        for case in cases
        if frozenset(
            r.id
            for r in matcher.match(
                case.listing, states=case.states, counties=case.counties, near=case.near
            ).targets
        )
        != case.targets
    ]


def test_the_fixture_holds_system_cases() -> None:
    cases = _system_cases()
    joint = [c for c in cases if c.also]
    assert len(joint) >= 25
    assert len([c for c in cases if not c.also]) >= 25
    assert {len(c.targets) for c in joint} == {2, 5}


def test_generated_system_cases_are_matched(
    background_matcher: Matcher, generated_cases: list[Case]
) -> None:
    """Every generated listing of a school system, or of one of its districts, is right."""
    cases = [c for c in generated_cases if c.note in {SYSTEM_NOTE, SYSTEM_NEGATIVE}]
    assert len(cases) >= 100
    assert sum(1 for c in cases if len(c.targets) > 1) >= 50
    assert sum(1 for c in cases if len(c.targets) == 5) >= 3  # a city's
    assert sum(1 for c in cases if len(c.targets) <= 1) >= 40
    assert _wrong(background_matcher, cases) == []


def test_the_fixture_sees_a_system_read_as_one_district(
    monkeypatch: pytest.MonkeyPatch, fixture_directory: Directory
) -> None:
    monkeypatch.setattr(Matcher, "_as_system", lambda *_args, **_kwargs: None)
    wrong = _wrong(Matcher(fixture_directory), _system_cases())
    assert "Kellby Public Schools" in wrong  # the elementary district alone
    assert "Bronby City Public Schools" in wrong  # nothing at all
    assert len(wrong) >= 25


def test_the_fixture_sees_a_level_that_names_one_district(
    monkeypatch: pytest.MonkeyPatch, fixture_directory: Directory
) -> None:
    monkeypatch.setattr(matcher_module, "names_a_system", lambda _form, **_kind: True)
    wrong = _wrong(Matcher(fixture_directory), _system_cases())
    assert {"Tamsby Elementary", "Phenby Elementary", "Kellby Elementary"} <= set(wrong)


def test_the_fixture_sees_districts_run_apart(
    monkeypatch: pytest.MonkeyPatch, fixture_directory: Directory
) -> None:
    """Were a town's two districts one system wherever their offices are."""

    def town_office(record: DirectoryRecord) -> tuple[str, float, float] | None:
        return (record.state, 0.0, 0.0) if record.city == "Boulby" else office_of(record)

    monkeypatch.setattr(systems_module, "office_of", town_office)
    wrong = _wrong(Matcher(fixture_directory), _system_cases())
    assert "Boulby Public Schools" in wrong


def test_the_fixture_sees_a_legal_form_word_one_district_says(
    monkeypatch: pytest.MonkeyPatch, fixture_directory: Directory
) -> None:
    def named_by(
        system: SchoolSystem, form: object, words: frozenset[str], _legal: frozenset[str]
    ) -> SystemName | None:
        return next((n for n in system.names if n.said_by(form, words)), None)  # type: ignore[arg-type]

    monkeypatch.setattr(SchoolSystem, "named_by", named_by)
    wrong = _wrong(Matcher(fixture_directory), _system_cases())
    assert {"Phenby Union", "Petalby Joint Union"} <= set(wrong)


def test_the_fixture_sees_a_municipal_word_no_district_says(
    monkeypatch: pytest.MonkeyPatch, fixture_directory: Directory
) -> None:
    """Were "City" to cost the districts that do not say it, a charter of the name wins."""
    monkeypatch.setattr(NameIndex, "forgiven", lambda _index, _forms, index: Scored(index, 0, 0))
    wrong = _wrong(Matcher(fixture_directory), _system_cases())
    assert "Rosaby City Schools" in wrong


def test_the_fixture_sees_a_city_left_out(
    monkeypatch: pytest.MonkeyPatch, fixture_directory: Directory
) -> None:
    monkeypatch.setattr(SystemName, "said_by", _said_by_leaving_out_anything)
    wrong = _wrong(Matcher(fixture_directory), _system_cases())
    assert {"Bronby Public Schools", "Bronby"} <= set(wrong)


def _said_by_leaving_out_anything(name: SystemName, form: object, words: frozenset[str]) -> bool:
    qualifiers: frozenset[str] = getattr(form, "qualifiers")  # noqa: B009 - a NameForm
    return words == name.words and qualifiers <= name.qualifiers


def test_every_result_s_targets_begin_with_its_target(handmade_matcher: Matcher) -> None:
    for case in handmade.CASES[-80:]:
        result: MatchResult = handmade_matcher.match(
            case.listing, states=case.states, counties=case.counties
        )
        if result.target is None:
            assert result.targets == ()
        else:
            assert result.targets[0] == result.target
