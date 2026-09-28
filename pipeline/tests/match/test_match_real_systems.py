"""School systems NCES splits into several districts, against the real NCES directory.

New York City's public schools are 33 NCES districts: the 32 geographic districts
and District 75's special schools (District 79's programs offer no K-12 grade
NCES reports, so the directory drops them). Montana keeps a town's elementary and
high school districts apart (``"Billings Elem"`` and ``"Billings H S"``), and in
some towns the high school district bears another name at the elementary
district's office (Kalispell's ``"Kalispell Elem"`` and ``"Flathead H S"``, which
the town calls ``"Kalispell Public Schools"``). A listing that names such a
system must name every one of its districts, so that none of its schools is
left without the listing's status; one that names one district (``"Kalispell
Elementary"``, ``"NYC District 75"``) must name that one alone, and a town whose
high school district has an office of its own (Boulder's ``"Jefferson H S"``)
has no system to name.

These tests read the directory ``snowlight directory build`` writes to
``out/internal/directory`` (never committed); they are skipped where it has not
been built.
"""

import re
from collections import defaultdict
from pathlib import Path

import pytest

from snowlight.match import DirectoryRecord, Matcher, Reason, load_directory

DIRECTORY = Path(__file__).resolve().parents[2] / "out" / "internal" / "directory"

pytestmark = pytest.mark.skipif(
    not (DIRECTORY / "schools.parquet").exists(), reason="the NCES directory is not built here"
)

NYC_DISTRICTS = 33
NYC_SCHOOLS = 1591
DISTRICT_75 = "3600135"
GEOGRAPHIC_5 = "3600081"
NYC_CHARTER_OF_THE_ARTS = "3601154"
NYC_CHARTER_OF_THE_ARTS_SCHOOL = "360115406586"
KALISPELL_ELEM, FLATHEAD_HS = "3015450", "3015420"

NYC_LISTINGS = (
    "New York City Public Schools",
    "NYC Public Schools",
    "NYC Schools",
    "New York City Schools",
    "NYC DOE",
    "NYC D.O.E.",
    "NYCDOE",
    "NYC Department of Education",
    "New York City Department of Education",
    "NYC Dept. of Ed.",
    "New York City",
    "NYC",
    "NYC Public Schools - All Schools",
)

ONE_OFFICE: dict[str, tuple[str, str]] = {
    "Kalispell": ("Kalispell Elem", "Flathead H S"),
    "Miles City": ("Miles City Elem", "Custer County H S"),
    "Lewistown": ("Lewistown Elem", "Fergus H S"),
    "Livingston": ("Livingston Elem", "Park H S"),
    "Glendive": ("Glendive Elem", "Dawson H S"),
    "Broadus": ("Broadus Elem", "Powder River Co Dist H S"),
    "Ekalaka": ("Ekalaka Elem", "Carter County H S"),
    "Jordan": ("Jordan Elem", "Garfield County H S"),
    "Pryor": ("Pryor Elem", "Plenty Coups H S"),
    "Eureka": ("Eureka Elem", "Lincoln County H S"),
}
"""Montana towns whose elementary district and high school district of another name
NCES places at one office: each town's school system is both."""

APART: dict[str, tuple[str, str]] = {
    "Boulder": ("Boulder Elem", "Jefferson H S"),
    "Dillon": ("Dillon Elem", "Beaverhead County H S"),
    "Deer Lodge": ("Deer Lodge Elem", "Powell County H S"),
    "Big Timber": ("Big Timber Elem", "Sweet Grass County H S"),
}
"""Montana towns whose high school district of another name has an office of its
own: run apart from the town's elementary district, and no part of its system."""


@pytest.fixture(scope="module")
def matcher() -> Matcher:
    """A matcher over the real directory."""
    return Matcher(load_directory(DIRECTORY))


def _district(matcher: Matcher, state: str, name: str) -> DirectoryRecord:
    found = [
        r for r in matcher.directory if r.kind == "district" and r.state == state and r.name == name
    ]
    assert len(found) == 1, (state, name, found)
    return found[0]


def _ids(records: tuple[DirectoryRecord, ...]) -> set[str]:
    return {record.id for record in records}


def _nyc(matcher: Matcher) -> set[str]:
    return {
        r.id
        for r in matcher.directory
        if r.kind == "district"
        and r.state == "NY"
        and (
            r.name.startswith("NEW YORK CITY GEOGRAPHIC DISTRICT")
            or r.name == "NYC SPECIAL SCHOOLS - DISTRICT 75"
        )
    }


def test_new_york_city_is_33_districts_of_1591_schools(matcher: Matcher) -> None:
    nyc = _nyc(matcher)
    assert len(nyc) == NYC_DISTRICTS
    assert DISTRICT_75 in nyc
    assert sum(len(matcher.expand(record_id)) for record_id in nyc) == NYC_SCHOOLS


@pytest.mark.parametrize("listing", NYC_LISTINGS)
def test_a_listing_of_new_york_city_s_schools_names_all_33_districts(
    matcher: Matcher, listing: str
) -> None:
    result = matcher.match(listing, states=["NY", "NJ", "CT"])
    assert result.reason is Reason.SYSTEM, (listing, result.reason, result.detail)
    assert _ids(result.targets) == _nyc(matcher)
    schools = matcher.expand(result)
    assert len(schools) == NYC_SCHOOLS
    # Charter schools are districts of their own, and none of the system.
    assert NYC_CHARTER_OF_THE_ARTS not in {school.district_id for school in schools}


def test_new_york_city_from_a_market_of_some_of_its_boroughs(matcher: Matcher) -> None:
    result = matcher.match("NYC Public Schools", states=["NY"], counties=["36061", "36005"])
    assert result.reason is Reason.SYSTEM
    assert _ids(result.targets) == _nyc(matcher)


@pytest.mark.parametrize(
    ("listing", "expected"),
    [
        ("NYC District 75", {DISTRICT_75}),
        ("NYC Special Schools", {DISTRICT_75}),
        ("New York City Geographic District 5", {GEOGRAPHIC_5}),
        ("NYC Geographic District 5", {GEOGRAPHIC_5}),
        # The charter school's own district's one school.
        ("New York City Charter School of the Arts", {NYC_CHARTER_OF_THE_ARTS_SCHOOL}),
        # "New York" is the state's name as well as the city's.
        ("New York", set()),
        ("New York Public Schools", set()),
    ],
)
def test_a_listing_of_one_new_york_city_district_names_it_alone(
    matcher: Matcher, listing: str, expected: set[str]
) -> None:
    result = matcher.match(listing, states=["NY"])
    assert _ids(result.targets) == expected, (listing, result.reason, result.detail)


def _montana_pairs(matcher: Matcher) -> dict[str, tuple[DirectoryRecord, DirectoryRecord]]:
    """Montana's towns with one "<town> Elem" and one "<town> H S" district, by base name."""
    found: dict[str, dict[str, list[DirectoryRecord]]] = defaultdict(lambda: defaultdict(list))
    for record in matcher.directory:
        named = re.fullmatch(r"(.+?) (Elem|H S)", record.name)
        if record.kind == "district" and record.state == "MT" and named is not None:
            found[named[1]][named[2]].append(record)
    return {
        base: (levels["Elem"][0], levels["H S"][0])
        for base, levels in found.items()
        if len(levels["Elem"]) == 1 and len(levels["H S"]) == 1
    }


def test_every_montana_town_s_two_districts_are_its_school_system(matcher: Matcher) -> None:
    pairs = _montana_pairs(matcher)
    assert len(pairs) >= 75
    wrong: list[tuple[str, str, set[str]]] = []
    for base, (elementary, high) in sorted(pairs.items()):
        for form in ("{} Public Schools", "{} Schools", "{}", "{} School District"):
            listing = form.format(base)
            result = matcher.match(listing, states=["MT"])
            if _ids(result.targets) != {elementary.id, high.id}:
                wrong.append((listing, str(result.reason), _ids(result.targets)))
            one = matcher.match(f"{base} Elementary", states=["MT"])
            if _ids(one.targets) != {elementary.id}:
                wrong.append((f"{base} Elementary", str(one.reason), _ids(one.targets)))
    assert not wrong


@pytest.mark.parametrize("town", sorted(ONE_OFFICE))
def test_a_high_school_district_at_the_town_s_office_is_its_system_s(
    matcher: Matcher, town: str
) -> None:
    elementary, high = (_district(matcher, "MT", name) for name in ONE_OFFICE[town])
    assert elementary.point == high.point
    for listing in (f"{town} Public Schools", f"{town} Schools", town):
        result = matcher.match(listing, states=["MT"])
        assert _ids(result.targets) == {elementary.id, high.id}, (listing, result.detail)
    alone = matcher.match(f"{town} Elementary", states=["MT"])
    assert _ids(alone.targets) == {elementary.id}


@pytest.mark.parametrize("town", sorted(APART))
def test_a_high_school_district_with_an_office_of_its_own_is_no_part_of_it(
    matcher: Matcher, town: str
) -> None:
    elementary, high = (_district(matcher, "MT", name) for name in APART[town])
    assert elementary.point != high.point
    result = matcher.match(f"{town} Public Schools", states=["MT"])
    assert high.id not in _ids(result.targets)


def test_kalispell_public_schools_are_its_eleven_schools(matcher: Matcher) -> None:
    result = matcher.match("Kalispell Public Schools", states=["MT"], counties=["30029"])
    assert [record.id for record in result.targets] == [KALISPELL_ELEM, FLATHEAD_HS]
    schools = matcher.expand(result)
    assert len(schools) == len(matcher.expand(KALISPELL_ELEM)) + len(matcher.expand(FLATHEAD_HS))
    assert {"Flathead High School", "Glacier High School"} <= {s.name for s in schools}


@pytest.mark.parametrize(
    ("listing", "expected"),
    [
        # The Flathead County superintendent's list, as it names its schools.
        ("KALISPELL ELEMENTARY", "Kalispell Elem"),
        ("FLATHEAD HIGH SCHOOL", "Flathead High School"),
        ("GLACIER HIGH SCHOOL", "Glacier High School"),
        ("BIGFORK ELEMENTARY", "Bigfork Elem"),
        ("WHITEFISH HIGH SCHOOL", "Whitefish High School"),
        ("EVERGREEN", "Evergreen Elem"),
    ],
)
def test_the_flathead_list_names_one_district_or_school_a_row(
    matcher: Matcher, listing: str, expected: str
) -> None:
    result = matcher.match(listing, states=["MT"], counties=["30029"], market="flathead-county")
    assert [record.name for record in result.targets] == [expected]


def test_two_elementary_districts_of_one_name_are_no_system(matcher: Matcher) -> None:
    result = matcher.match("Cottonwood Public Schools", states=["MT"])
    assert result.targets == ()
    assert result.reason is Reason.AMBIGUOUS


@pytest.mark.parametrize(
    ("listing", "state", "expected"),
    [
        (
            "Phoenix Public Schools",
            "AZ",
            {"Phoenix Elementary District (4256)", "Phoenix Union High School District (4286)"},
        ),
        ("Phoenix Union", "AZ", {"Phoenix Union High School District (4286)"}),
        ("Glendale Elementary", "AZ", {"Glendale Elementary District (4271)"}),
        ("Glendale Union", "AZ", {"Glendale Union High School District (4285)"}),
        ("Santa Rosa City Schools", "CA", {"Santa Rosa Elementary", "Santa Rosa High"}),
        ("Salinas City Schools", "CA", {"Salinas City Elementary"}),
        ("Petaluma City Schools", "CA", {"Petaluma City Elementary", "Petaluma Joint Union High"}),
        ("Merced City Schools", "CA", {"Merced City Elementary"}),
        ("Billings Public Schools", "OK", {"BILLINGS"}),
        # KOAT's listing: the Pueblo of Laguna's department of education, which
        # runs both of the pueblo's schools.
        (
            "Laguna Department of Education",
            "NM",
            {"Laguna Elementary School", "Laguna Middle School"},
        ),
    ],
)
def test_systems_of_one_name_elsewhere(
    matcher: Matcher, listing: str, state: str, expected: set[str]
) -> None:
    result = matcher.match(listing, states=[state])
    assert {record.name for record in result.targets} == expected, (listing, result.detail)
