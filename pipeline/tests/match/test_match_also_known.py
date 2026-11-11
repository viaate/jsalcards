"""A directory name that says ``dba``, ``aka`` or ``formerly`` gives two names.

NCES names some charter schools by their legal operator and the name they go by
(``"Kenmore Preparatory Academy dba Toledo Preparatory Academy"``), and some
schools by their name and the one they had (``"... formerly Oak Hill"``). The
matcher reads both (:func:`~snowlight.match.normalize.also_known_as`). Every name
here is the public NCES directory's.
"""

from pathlib import Path

import pytest

from snowlight.listed.scope import station_context
from snowlight.match import Matcher
from snowlight.match.directory import Directory, DirectoryRecord
from snowlight.match.index import _cut_off
from snowlight.match.normalize import also_known_as
from snowlight.sources.stations.registry import Station, load_registry

PIPELINE = Path(__file__).resolve().parents[2]

KENMORE = "390160806010"
"""Kenmore Preparatory Academy dba Toledo Preparatory Academy (Toledo, Lucas County, OH)."""
WESTERN_TOLEDO = "390163806187"
TOLEDO_FITNESS = "390057305065"
BRIDGES_OH = "390050205212"
"""Bridges Community Academy dba Bridges Preparatory Academy (Tiffin, Seneca County, OH)."""
BRIDGES_CA = "060256414577"
"""Bridges Preparatory Academy (Compton, Los Angeles County, CA)."""


@pytest.mark.parametrize(
    ("name", "read"),
    [
        # The name a list uses follows dba, d/b/a, d.b.a. or aka; the legal name is a second.
        (
            "Kenmore Preparatory Academy dba Toledo Preparatory Academy",
            ("Toledo Preparatory Academy", "Kenmore Preparatory Academy"),
        ),
        (
            "KENMORE PREPARATORY ACADEMY DBA TOLEDO PREPARATORY ACADEMY",
            ("TOLEDO PREPARATORY ACADEMY", "KENMORE PREPARATORY ACADEMY"),
        ),
        (
            "SSDS OF GMC D/B/A THE HEBREW ACADEMY",
            ("THE HEBREW ACADEMY", "SSDS OF GMC"),
        ),
        (
            "the education center, inc. d/b/a education center",
            ("education center", "the education center, inc."),
        ),
        (
            "Edkey Inc. d.b.a. Sequoia Charter School",
            ("Sequoia Charter School", "Edkey Inc."),
        ),
        (
            "Beacon Hill Community School AKA Beacon Hill Academy",
            ("Beacon Hill Academy", "Beacon Hill Community School"),
        ),
        (
            "beacon hill community school aka beacon hill academy",
            ("beacon hill academy", "beacon hill community school"),
        ),
        (
            "VESTWOOD EDUCATION DBA:ONE SCHOOL GLOBAL REDWOOD F",
            ("ONE SCHOOL GLOBAL REDWOOD F", "VESTWOOD EDUCATION"),
        ),
        # The name before formerly or fka stays; the old one after it is a second.
        (
            "Maya Angelou Academy at New Beginnings formerly Oak Hill",
            ("Maya Angelou Academy at New Beginnings", "Oak Hill"),
        ),
        (
            "WAYNE CHRISTIAN ACADEMY FORMERLY SOLID ROCK CHRIST",
            ("WAYNE CHRISTIAN ACADEMY", "SOLID ROCK CHRIST"),
        ),
        (
            "Star Community School fka St. Timothy School",
            ("Star Community School", "St. Timothy School"),
        ),
        (
            "STAR COMMUNITY SCHOOL FKA ST. TIMOTHY SCHOOL",
            ("STAR COMMUNITY SCHOOL", "ST. TIMOTHY SCHOOL"),
        ),
        # A name that starts with DBA is the rest.
        (
            "DBA ELIZABETH SETON CHILDRENS SCHOOL",
            ("ELIZABETH SETON CHILDRENS SCHOOL", None),
        ),
    ],
)
def test_a_name_with_dba_aka_or_formerly_is_two_names(
    name: str, read: tuple[str, str | None]
) -> None:
    assert also_known_as(name, district=False) == read


@pytest.mark.parametrize(
    "name",
    [
        # One side names nothing: cut off after the word, or nothing but it.
        "MCDONALDS PLAYWORLD COMMUNITY DEVELOPMENT INC DBA",
        "Mary Ellen Halvorson Educational Foundation. dba:",
        "FORMERLY ST. TIMOTHY SCHOOL",
        "Kenmore Preparatory Academy dba of",
        # The name after it is a child care chain's alone.
        "MITTAS DAY CARE LLC DBA THE LEARNING EXPERIENCE",
        # The word is in a bracket (directory_name reads those) or part of another word.
        "CALVIN CHRISTIAN SCHOOL (DBA: AVAIL ACADEMY)",
        "GREATER TRINITY ACADEMY (AKA RISE UP ACADEMY)",
        "East Branch Preparatory AcademydbaWright Preparatory Academy",
        "Mishawaka High School",
        "Sewanhaka High School",
        "Toledo Preparatory and Fitness Academy",
    ],
)
def test_a_name_without_two_names_is_read_as_one(name: str) -> None:
    assert also_known_as(name, district=False) is None


def test_a_name_nces_cut_off_gives_a_second_name_only_when_it_ends_whole() -> None:
    peoria = "American Charter Schools Foundation d.b.a. Peoria  (79875)"
    assert _cut_off(peoria)
    base = "American Charter Schools Foundation d.b.a. Peoria"
    assert also_known_as(base, district=True, cut=True) is None
    northside = "Dublin Preparatory Academy dba Northside Preparatory Academy"
    assert _cut_off(northside)
    assert also_known_as(northside, district=False, cut=True) == (
        "Northside Preparatory Academy",
        "Dublin Preparatory Academy",
    )
    dayton = "Alliance Community Schools Inc. dba Dayton Leadership Acade"
    assert _cut_off(dayton)
    assert also_known_as(dayton, district=False, cut=True) is None
    kenmore = "Kenmore Preparatory Academy dba Toledo Preparatory Academy"
    assert not _cut_off("Riverside Community School Inc. dba Riverside Academy")
    assert also_known_as(kenmore, district=False, cut=True) is not None


CHARTERS: tuple[tuple[str, str, str, str, str, float, float], ...] = (
    (
        TOLEDO_FITNESS,
        "Toledo Preparatory and Fitness Academy",
        "OH",
        "39095",
        "Toledo",
        41.637295,
        -83.613714,
    ),
    (
        KENMORE,
        "Kenmore Preparatory Academy dba Toledo Preparatory Academy",
        "OH",
        "39095",
        "Toledo",
        41.646224,
        -83.51645,
    ),
    (
        WESTERN_TOLEDO,
        "Western Toledo Preparatory Academy",
        "OH",
        "39095",
        "Toledo",
        41.637488,
        -83.688467,
    ),
    (
        BRIDGES_OH,
        "Bridges Community Academy dba Bridges Preparatory Academy",
        "OH",
        "39147",
        "Tiffin",
        41.095667,
        -83.168766,
    ),
    (BRIDGES_CA, "Bridges Preparatory Academy", "CA", "06037", "Compton", 33.893137, -118.215465),
)
"""The three Toledo preparatory academies and the two Bridges Preparatory Academies:
NCES id, name, state, county, city, latitude and longitude."""
COUNTIES = {"39095": "Lucas County", "39147": "Seneca County", "06037": "Los Angeles County"}


def _charter(row: tuple[str, str, str, str, str, float, float]) -> list[DirectoryRecord]:
    """A charter school and the district of it alone, as NCES lists them."""
    school_id, name, state, county, city, lat, lon = row
    district_id = school_id[:7]
    district_name = "Bridges Preparatory Academy District" if state == "CA" else name
    at = (state, county, city, lat, lon)
    return [
        DirectoryRecord(district_id, district_name, "district", None, *at, county=COUNTIES[county]),
        DirectoryRecord(
            school_id,
            name,
            "school",
            district_id,
            *at,
            county=COUNTIES[county],
            grade_low="06" if state == "CA" else "KG",
            grade_high="08",
            level="Middle" if state == "CA" else "Elementary",
        ),
    ]


@pytest.fixture(scope="module")
def matcher() -> Matcher:
    """A matcher over :data:`CHARTERS`."""
    return Matcher(Directory([record for row in CHARTERS for record in _charter(row)]))


@pytest.fixture(scope="module")
def stations() -> dict[str, Station]:
    return dict(load_registry(PIPELINE / "config" / "sources").stations)


def _targets(matcher: Matcher, station: Station, listing: str) -> tuple[str, ...]:
    context = station_context(station)
    result = matcher.match(
        listing, states=context.states, counties=context.counties, market=context.market
    )
    return tuple(record.id for record in result.targets)


@pytest.mark.parametrize(
    ("listing", "school"),
    [
        ("TOLEDO PREPARATORY ACADEMY", KENMORE),
        # The legal name is the school's too.
        ("KENMORE PREPARATORY ACADEMY", KENMORE),
        ("WESTERN TOLEDO PREPARATORY ACADEMY", WESTERN_TOLEDO),
        ("TOLEDO PREPARATORY AND FITNESS ACADEMY", TOLEDO_FITNESS),
        ("BRIDGES PREPARATORY ACADEMY", BRIDGES_OH),
    ],
)
def test_13abc_names_the_school_by_the_name_it_goes_by(
    matcher: Matcher, stations: dict[str, Station], listing: str, school: str
) -> None:
    assert _targets(matcher, stations["gray-wtvg"], listing) == (school,)


def test_the_name_a_school_goes_by_names_no_school_in_another_state(
    matcher: Matcher, stations: dict[str, Station]
) -> None:
    los_angeles = stations["abc-owned-kabc"]
    assert _targets(matcher, los_angeles, "BRIDGES PREPARATORY ACADEMY") == (BRIDGES_CA,)
    assert _targets(matcher, los_angeles, "TOLEDO PREPARATORY ACADEMY") == ()
    assert _targets(matcher, los_angeles, "KENMORE PREPARATORY ACADEMY") == ()
