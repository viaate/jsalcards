"""A directory name that says ``dba`` or ``aka`` gives two names, and keeps its own.

NCES names some charter schools by their legal operator and the name they go by
(``"Kenmore Preparatory Academy dba Toledo Preparatory Academy"``). The matcher
reads both, beside NCES's whole name (:func:`~snowlight.match.normalize.also_known_as`);
of a name that says ``formerly`` it reads the current name, never the old one
(``"... formerly Oak Hill"``). Every name here is the public NCES directory's, or
two or three of them joined by the word.
"""

from pathlib import Path

import pytest

from snowlight.listed.scope import station_context
from snowlight.match import Matcher
from snowlight.match.directory import Directory, DirectoryRecord
from snowlight.match.index import ALSO_NAME, _cut_off
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
        # The name a list uses follows the word; the legal name before it is the other.
        (
            "Kenmore Preparatory Academy dba Toledo Preparatory Academy",
            ("Toledo Preparatory Academy", "Kenmore Preparatory Academy"),
        ),
        (
            "KENMORE PREPARATORY ACADEMY DBA TOLEDO PREPARATORY ACADEMY",
            ("TOLEDO PREPARATORY ACADEMY", "KENMORE PREPARATORY ACADEMY"),
        ),
        ("SSDS OF GMC D/B/A THE HEBREW ACADEMY", ("THE HEBREW ACADEMY", "SSDS OF GMC")),
        (
            "the education center, inc. d/b/a education center",
            ("education center", "the education center, inc."),
        ),
        ("Edkey Inc. d.b.a. Sequoia Charter School", ("Sequoia Charter School", "Edkey Inc.")),
        (
            "Kenmore Preparatory Academy doing business as Toledo Preparatory Academy",
            ("Toledo Preparatory Academy", "Kenmore Preparatory Academy"),
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
            "Beacon Hill Community School a/k/a Beacon Hill Academy",
            ("Beacon Hill Academy", "Beacon Hill Community School"),
        ),
        (
            "Beacon Hill Community School also known as Beacon Hill Academy",
            ("Beacon Hill Academy", "Beacon Hill Community School"),
        ),
        # A bracket that opens with the word and ends the name reads the same.
        (
            "CALVIN CHRISTIAN SCHOOL (DBA: AVAIL ACADEMY)",
            ("AVAIL ACADEMY", "CALVIN CHRISTIAN SCHOOL"),
        ),
        (
            "GREATER TRINITY ACADEMY (AKA RISE UP ACADEMY)",
            ("RISE UP ACADEMY", "GREATER TRINITY ACADEMY"),
        ),
        (
            "ABC LEARNING CENTRE, INC (DBA ABC-STEWART SCHOOL)",
            ("ABC-STEWART SCHOOL", "ABC LEARNING CENTRE, INC"),
        ),
        (
            "CALVIN CHRISTIAN SCHOOL [DBA: AVAIL ACADEMY]",
            ("AVAIL ACADEMY", "CALVIN CHRISTIAN SCHOOL"),
        ),
        # A bracket closed before the word is part of the legal name.
        (
            "AVAIL ACADEMY - EDINA (DBA: CALVIN CHRISTIAN SCHOOL)",
            ("CALVIN CHRISTIAN SCHOOL", "AVAIL ACADEMY - EDINA"),
        ),
        # A name that starts with DBA is the rest.
        ("DBA ELIZABETH SETON CHILDRENS SCHOOL", ("ELIZABETH SETON CHILDRENS SCHOOL", None)),
        # A name that says formerly is the name before the word; the old one is dropped.
        (
            "Maya Angelou Academy at New Beginnings formerly Oak Hill",
            ("Maya Angelou Academy at New Beginnings", None),
        ),
        ("Star Community School fka St. Timothy School", ("Star Community School", None)),
        ("STAR COMMUNITY SCHOOL F/K/A ST. TIMOTHY SCHOOL", ("STAR COMMUNITY SCHOOL", None)),
        (
            "Edison Middle School (formerly Berlin-Milan Middle School)",
            ("Edison Middle School", None),
        ),
        # A current name that says a child care chain's brand and only what kind of
        # school it is goes by it, as a record NCES names so does; a dba side never.
        (
            "CADENCE ACADEMY PRESCHOOL FORMERLY FLANAGAN'S PRES",
            ("CADENCE ACADEMY PRESCHOOL", None),
        ),
        ("THE LEARNING EXPERIENCE formerly MITTAS DAY CARE", ("THE LEARNING EXPERIENCE", None)),
        # A side with a number is a name, not only a kind of school.
        (
            "Academy 21 dba Toledo Preparatory Academy",
            ("Toledo Preparatory Academy", "Academy 21"),
        ),
    ],
)
def test_a_name_that_says_dba_or_aka_gives_its_two_names(
    name: str, read: tuple[str, str | None]
) -> None:
    # Read as the index reads it: a name that may be cut off ends whole.
    assert also_known_as(name, district=False, cut=_cut_off(name)) == read


@pytest.mark.parametrize(
    "name",
    [
        # One side names nothing: cut off after the word, or nothing but it.
        "MCDONALDS PLAYWORLD COMMUNITY DEVELOPMENT INC DBA",
        "Mary Ellen Halvorson Educational Foundation. dba:",
        "Kenmore Preparatory Academy dba of",
        "AKA Academy",
        "DBA Academy",
        "PAIDEIA CLASSICAL CHRISTIAN SCHOOL (DBA)",
        # A side that is a child care chain's or a faith's alone.
        "MITTAS DAY CARE LLC DBA THE LEARNING EXPERIENCE",
        "THE LEARNING EXPERIENCE DBA MITTAS DAY CARE",
        "CATHOLIC DBA ELIZABETH SETON CHILDRENS SCHOOL",
        # A side that says only what kind of school it is.
        "ACADEMY SCHOOL dba Toledo Preparatory Academy",
        "Toledo Preparatory Academy dba ACADEMY SCHOOL",
        "ACADEMY SCHOOL formerly Oak Hill",
        "Oak Hill formerly CADENCE ACADEMY PRESCHOOL",
        # An old name alone names nothing.
        "FORMERLY ST. TIMOTHY SCHOOL",
        "Maya Angelou Academy at New Beginnings formerly",
        # Two words: not read, an old name's beside a dba too.
        "Kenmore Preparatory Academy dba Toledo Preparatory Academy aka Toledo Prep",
        "Beacon Hill Community School AKA Beacon Hill Academy (formerly Beacon Academy)",
        "Kenmore Preparatory Academy dba Toledo Preparatory Academy fka Western Toledo"
        " Preparatory Academy",
        "Star Community School f/k/a St. Timothy School dba Toledo Preparatory Academy",
        # The word inside a bracket it does not open, or in one NCES left open, or
        # a bracket inside the one it opens.
        "CALVIN CHRISTIAN SCHOOL (MINNEAPOLIS DBA AVAIL ACADEMY)",
        "CALVIN CHRISTIAN SCHOOL (DBA: AVAIL ACADEMY",
        "CALVIN CHRISTIAN SCHOOL (DBA: AVAIL ACADEMY) MINNEAPOLIS",
        "CALVIN CHRISTIAN SCHOOL (DBA: AVAIL ACADEMY (EDINA))",
        "CALVIN CHRISTIAN SCHOOL (DBA: AVAIL ACADEMY (EDINA)",
        # Part of another word, or of a run of them joined by a slash.
        "Mishawaka High School",
        "Sewanhaka High School",
        "Toledo Preparatory and Fitness Academy",
        "Kenmore Preparatory Academy dba/Toledo Preparatory Academy",
        # A known miss: NCES glues the word to both names, and it stays unread.
        "East Branch Preparatory AcademydbaWright Preparatory Academy",
    ],
)
def test_a_name_without_two_names_is_read_as_one(name: str) -> None:
    assert also_known_as(name, district=False, cut=_cut_off(name)) is None


KENMORE_TOLEDO = "Kenmore Preparatory Academy{}aka Toledo Preparatory Academy"
EAST_BRANCH = "East Branch Preparatory Academy{}Wright Preparatory Academy"


@pytest.mark.parametrize(
    ("name", "spaced"),
    [
        # The word ends a word, after a letter, an apostrophe or an okina.
        (EAST_BRANCH.format("dba "), EAST_BRANCH.format(" dba ")),
        (KENMORE_TOLEDO.format("'"), KENMORE_TOLEDO.format(" ")),
        (KENMORE_TOLEDO.format("\u2018"), KENMORE_TOLEDO.format(" ")),
        (KENMORE_TOLEDO.format("\u2019"), KENMORE_TOLEDO.format(" ")),
        (KENMORE_TOLEDO.format("\u02bb"), KENMORE_TOLEDO.format(" ")),
        # The word starts a word.
        (EAST_BRANCH.format(" dba"), EAST_BRANCH.format(" dba ")),
    ],
)
def test_the_word_is_read_only_whole(name: str, spaced: str) -> None:
    assert also_known_as(name, district=False) is None
    # Both sides name something: the word alone keeps the name whole.
    assert also_known_as(spaced, district=False) is not None


def test_a_name_nces_cut_off_gives_two_names_only_when_it_ends_whole() -> None:
    peoria = "American Charter Schools Foundation d.b.a. Peoria  (79875)"
    assert _cut_off(peoria)
    base = "American Charter Schools Foundation d.b.a. Peoria"
    assert also_known_as(base, district=True, cut=True) is None
    # Cut at 50 before the entity number NCES adds: the head is cut off too.
    gateway = "Maricopa County Community College District dba Gat (4314)"
    assert len(gateway) == 57
    assert _cut_off(gateway)
    gat = "Maricopa County Community College District dba Gat"
    assert also_known_as(gat, district=True, cut=True) is None
    northside = "Dublin Preparatory Academy dba Northside Preparatory Academy"
    assert _cut_off(northside)
    assert also_known_as(northside, district=False, cut=True) == (
        "Northside Preparatory Academy",
        "Dublin Preparatory Academy",
    )
    dayton = "Alliance Community Schools Inc. dba Dayton Leadership Acade"
    assert _cut_off(dayton)
    assert also_known_as(dayton, district=False, cut=True) is None
    vestwood = "VESTWOOD EDUCATION DBA:ONE SCHOOL GLOBAL REDWOOD F"
    assert _cut_off(vestwood)
    assert also_known_as(vestwood, district=False, cut=True) is None
    # 58 characters: maybe cut, but it ends whole.
    kenmore = "Kenmore Preparatory Academy dba Toledo Preparatory Academy"
    assert _cut_off(kenmore)
    assert also_known_as(kenmore, district=False, cut=True) == (
        "Toledo Preparatory Academy",
        "Kenmore Preparatory Academy",
    )
    assert not _cut_off("Riverside Community School Inc. dba Riverside Academy")
    # A bracket NCES closed is whole, however long the name: only an open one is cut.
    edina = "CALVIN CHRISTIAN SCHOOL (DBA: AVAIL ACADEMY - EDINA)"
    assert also_known_as(edina, district=False, cut=True) == (
        "AVAIL ACADEMY - EDINA",
        "CALVIN CHRISTIAN SCHOOL",
    )
    inline = "CALVIN CHRISTIAN SCHOOL DBA AVAIL ACADEMY - EDINA"
    assert also_known_as(inline, district=False, cut=True) is None


def test_a_name_a_dba_gives_is_worth_the_whole_name() -> None:
    # In the archive's replay at 0.95, WGAL's "Logos Academy Harrisburg" no longer
    # names NEW CITY SCHOOL DBA LOGOS HARRISBURG, and a Tucson list's "SUMMIT HIGH
    # SCHOOL" names Flagstaff's school over the one Kaizen's Phoenix school goes by,
    # a tie the lead ruled is the queue's.
    assert ALSO_NAME == 1.0


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


TOLEDO_STATIONS = ("gray-wtvg", "sinclair-wnwo", "tegna-wtol")
"""13abc and the two other stations of the registry's Toledo market."""


def test_the_toledo_stations_are_the_registry_s(stations: dict[str, Station]) -> None:
    lucas = (sid for sid, s in stations.items() if s.counties and "39095" in s.counties.fips)
    assert tuple(sorted(lucas)) == TOLEDO_STATIONS


@pytest.mark.parametrize("station", TOLEDO_STATIONS)
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
    matcher: Matcher, stations: dict[str, Station], station: str, listing: str, school: str
) -> None:
    assert _targets(matcher, stations[station], listing) == (school,)


def test_the_name_a_school_goes_by_names_no_school_in_another_state(
    matcher: Matcher, stations: dict[str, Station]
) -> None:
    los_angeles = stations["abc-owned-kabc"]
    assert _targets(matcher, los_angeles, "BRIDGES PREPARATORY ACADEMY") == (BRIDGES_CA,)
    assert _targets(matcher, los_angeles, "TOLEDO PREPARATORY ACADEMY") == ()
    assert _targets(matcher, los_angeles, "KENMORE PREPARATORY ACADEMY") == ()


Row = tuple[str, str, str, str | None, str, str, str, float, float, str, str | None, str | None]
NEIGHBOURS: tuple[Row, ...] = (
    # Riverside Local (De Graff, Logan County, Dayton's market) and Cincinnati's
    # charter school of one school, whose dba is Riverside Academy.
    (
        "district",
        "3904809",
        "Riverside Local",
        None,
        "OH",
        "39091",
        "De Graff",
        40.3157,
        -83.9234,
        "Logan County",
        None,
        None,
    ),
    (
        "school",
        "390480903108",
        "Riverside Elementary School",
        "3904809",
        "OH",
        "39091",
        "De Graff",
        40.3157,
        -83.9234,
        "Logan County",
        "PK",
        "06",
    ),
    (
        "school",
        "390480903109",
        "Riverside High School",
        "3904809",
        "OH",
        "39091",
        "De Graff",
        40.3157,
        -83.9234,
        "Logan County",
        "07",
        "12",
    ),
    (
        "district",
        "3900043",
        "Riverside Community School Inc. dba Riverside Academy",
        None,
        "OH",
        "39061",
        "Cincinnati",
        39.0863,
        -84.578,
        "Hamilton County",
        None,
        None,
    ),
    (
        "school",
        "390004302979",
        "Riverside Community School Inc. dba Riverside Academy",
        "3900043",
        "OH",
        "39061",
        "Cincinnati",
        39.0863,
        -84.578,
        "Hamilton County",
        "KG",
        "08",
    ),
    # A school of Dayton's market 58 km from it: Hamilton County lies just past the market.
    (
        "school",
        "390649604125",
        "College Corner Union Elementary School",
        None,
        "OH",
        "39135",
        "College Corner",
        39.572203,
        -84.814936,
        "Preble County",
        "PK",
        "12",
    ),
    # Austin's The Magnolia School and Houston's, which goes by the name; a school
    # of Austin's market and one of Harris County 74 km apart.
    (
        "school",
        "483810004259",
        "ROUND TOP-CARMINE H S",
        None,
        "TX",
        "48149",
        "CARMINE",
        30.143919,
        -96.68137,
        "Fayette County",
        "07",
        "12",
    ),
    (
        "school",
        "484443012000",
        "SCHULTZ J H",
        None,
        "TX",
        "48201",
        "WALLER",
        30.078701,
        -95.920401,
        "Harris County",
        "06",
        "08",
    ),
    (
        "school",
        "BB162879",
        "THE MAGNOLIA SCHOOL",
        None,
        "TX",
        "48453",
        "AUSTIN",
        30.322152,
        -97.95753,
        "Travis County",
        "PK",
        "08",
    ),
    (
        "school",
        "A2302944",
        "INSTITUTE FOR GIRLS EDUCATION, DBA MAGNOLIA SCHOOL",
        None,
        "TX",
        "48201",
        "HOUSTON",
        29.794968,
        -95.536508,
        "Harris County",
        "01",
        "08",
    ),
    # Anne Arundel County's Oak Hill Elementary, and a school that was Oak Hill.
    (
        "district",
        "2400060",
        "Anne Arundel County Public Schools",
        None,
        "MD",
        "24003",
        "Annapolis",
        38.97612,
        -76.559401,
        "Anne Arundel County",
        None,
        None,
    ),
    (
        "school",
        "240006000104",
        "Oak Hill Elementary",
        "2400060",
        "MD",
        "24003",
        "Severna Park",
        39.083797,
        -76.569027,
        "Anne Arundel County",
        "KG",
        "05",
    ),
    (
        "district",
        "1100087",
        "DYRS",
        None,
        "MD",
        "24003",
        "Laurel",
        39.101153,
        -76.787327,
        "Anne Arundel County",
        None,
        None,
    ),
    (
        "school",
        "110008700213",
        "Maya Angelou Academy at New Beginnings formerly Oak Hill",
        "1100087",
        "MD",
        "24003",
        "Laurel",
        39.101153,
        -76.787327,
        "Anne Arundel County",
        "07",
        "12",
    ),
    # Two campuses NCES names the other way round, and Avail Academy's high school.
    (
        "school",
        "A9502427",
        "AVAIL ACADEMY DBA CALVIN CHRISTIAN SCHOOL",
        None,
        "MN",
        "27003",
        "MINNEAPOLIS",
        45.13279,
        -93.242021,
        "Anoka County",
        "KG",
        "08",
    ),
    (
        "school",
        "BB220378",
        "CALVIN CHRISTIAN SCHOOL (DBA: AVAIL ACADEMY)",
        None,
        "MN",
        "27053",
        "MINNEAPOLIS",
        44.929152,
        -93.332484,
        "Hennepin County",
        "KG",
        "08",
    ),
    (
        "school",
        "A0701361",
        "AVAIL ACADEMY HIGH SCHOOL",
        None,
        "MN",
        "27003",
        "FRIDLEY",
        45.10127,
        -93.252731,
        "Anoka County",
        "09",
        "12",
    ),
    # Three of Kaizen Education Foundation's districts, two named as their one school.
    (
        "district",
        "0400386",
        "Kaizen Education Foundation dba Summit High School (79876)",
        None,
        "AZ",
        "04013",
        "PHOENIX",
        33.527109,
        -112.047952,
        "Maricopa County",
        None,
        None,
    ),
    (
        "school",
        "040038601894",
        "Kaizen Education Foundation dba Summit High School",
        "0400386",
        "AZ",
        "04013",
        "PHOENIX",
        33.4662,
        -112.0637,
        "Maricopa County",
        "09",
        "12",
    ),
    (
        "district",
        "0400389",
        "Kaizen Education Foundation dba Maya High School (79882)",
        None,
        "AZ",
        "04013",
        "PHOENIX",
        33.527109,
        -112.047952,
        "Maricopa County",
        None,
        None,
    ),
    (
        "district",
        "0400852",
        "Kaizen Education Foundation dba Havasu Preparatory (90535)",
        None,
        "AZ",
        "04013",
        "PHOENIX",
        33.527109,
        -112.047952,
        "Maricopa County",
        None,
        None,
    ),
    # Avail Academy's Edina campus, at the point of the one NCES names CALVIN
    # CHRISTIAN SCHOOL (DBA: AVAIL ACADEMY).
    (
        "school",
        "00704379",
        "AVAIL ACADEMY - EDINA",
        None,
        "MN",
        "27053",
        "EDINA",
        44.92952,
        -93.332481,
        "Hennepin County",
        "KG",
        "08",
    ),
    # Flagstaff's Summit High School, named as Kaizen's Phoenix school goes by.
    (
        "district",
        "0402860",
        "Flagstaff Unified District (4192)",
        None,
        "AZ",
        "04005",
        "FLAGSTAFF",
        35.198635,
        -111.606963,
        "Coconino County",
        None,
        None,
    ),
    (
        "school",
        "040286001158",
        "Summit High School",
        "0402860",
        "AZ",
        "04005",
        "FLAGSTAFF",
        35.226189,
        -111.584919,
        "Coconino County",
        "07",
        "12",
    ),
    # Two schools whose dba names say only a kind of school, word for word.
    (
        "school",
        "02044228",
        "SSDS OF GMC D/B/A THE HEBREW ACADEMY",
        None,
        "NJ",
        "34025",
        "MARLBORO",
        40.312264,
        -74.246898,
        "Monmouth County",
        "PK",
        "08",
    ),
    (
        "school",
        "00735625",
        "THE EDUCATION CENTER, INC. D/B/A EDUCATION CENTER",
        None,
        "MS",
        "28049",
        "JACKSON",
        32.345981,
        -90.158851,
        "Hinds County",
        "01",
        "12",
    ),
    # Edkey's own district, and two that carry its name as their legal name.
    (
        "district",
        "0400415",
        "Edkey Inc. (85749)",
        None,
        "AZ",
        "04013",
        "PHOENIX",
        33.387617,
        -111.817724,
        "Maricopa County",
        None,
        None,
    ),
    (
        "district",
        "0400130",
        "Edkey Inc. dba American Heritage Academy  (6365)",
        None,
        "AZ",
        "04025",
        "COTTONWOOD",
        34.732279,
        -112.004605,
        "Yavapai County",
        None,
        None,
    ),
    (
        "district",
        "0400244",
        "Edkey Inc. dba Sequoia Charter School (6446)",
        None,
        "AZ",
        "04013",
        "MESA",
        33.387587,
        -111.814937,
        "Maricopa County",
        None,
        None,
    ),
    # Logos Academy's two schools in WGAL's market, and a third of Harrisburg's name.
    (
        "school",
        "A2103316",
        "NEW CITY SCHOOL DBA LOGOS HARRISBURG",
        None,
        "PA",
        "42043",
        "HARRISBURG",
        40.269006,
        -76.889741,
        "Dauphin County",
        "PK",
        "04",
    ),
    (
        "school",
        "A0108928",
        "LOGOS ACADEMY",
        None,
        "PA",
        "42133",
        "YORK",
        39.9588,
        -76.733071,
        "York County",
        "KG",
        "12",
    ),
    (
        "school",
        "01197876",
        "HARRISBURG ACADEMY",
        None,
        "PA",
        "42041",
        "WORMLEYSBURG",
        40.252498,
        -76.912148,
        "Cumberland County",
        "PK",
        "12",
    ),
    # Intelli-School's own district, and two charter holders at its address that
    # go by its name.
    (
        "district",
        "0400061",
        "Intelli-School Inc. (4352)",
        None,
        "AZ",
        "04013",
        "PHOENIX",
        33.553719,
        -112.107124,
        "Maricopa County",
        None,
        None,
    ),
    (
        "district",
        "0400363",
        "SC Jensen Corporation Inc. dba Intelli-School (79951)",
        None,
        "AZ",
        "04013",
        "PHOENIX",
        33.553719,
        -112.107124,
        "Maricopa County",
        None,
        None,
    ),
    (
        "district",
        "0400364",
        "PAS Charter Inc. dba Intelli-School (79953)",
        None,
        "AZ",
        "04013",
        "PHOENIX",
        33.553719,
        -112.107124,
        "Maricopa County",
        None,
        None,
    ),
    # CPLC's own district in Phoenix, and two in Tucson that carry its name.
    (
        "district",
        "0400144",
        "CPLC Community Schools (4300)",
        None,
        "AZ",
        "04013",
        "Phoenix",
        33.508237,
        -112.083686,
        "Maricopa County",
        None,
        None,
    ),
    (
        "district",
        "0400382",
        "CPLC Community Schools dba Toltecalli High School (80032)",
        None,
        "AZ",
        "04019",
        "TUCSON",
        32.163,
        -110.9725,
        "Pima County",
        None,
        None,
    ),
    (
        "district",
        "0400814",
        "CPLC Community Schools dba Hiaki High School (90331)",
        None,
        "AZ",
        "04019",
        "TUCSON",
        32.115879,
        -111.067171,
        "Pima County",
        None,
        None,
    ),
    # Dublin's preschool in Columbus's market, and Cincinnati's charter school
    # whose legal name is Dublin Preparatory Academy.
    (
        "school",
        "A0502757",
        "PREP ACADEMY SCHOOLS - DUBLIN",
        None,
        "OH",
        "39049",
        "DUBLIN",
        40.084328,
        -83.157872,
        "Franklin County",
        "PK",
        "KG",
    ),
    (
        "district",
        "3901628",
        "Dublin Preparatory Academy dba Northside Preparatory Academy",
        None,
        "OH",
        "39061",
        "Cincinnati",
        39.177,
        -84.5175,
        "Hamilton County",
        None,
        None,
    ),
    (
        "school",
        "390162806028",
        "Dublin Preparatory Academy dba Northside Preparatory Academy",
        "3901628",
        "OH",
        "39061",
        "Cincinnati",
        39.177,
        -84.5175,
        "Hamilton County",
        "KG",
        "08",
    ),
    # One Winter Garden school NCES lists twice, at one address.
    (
        "school",
        "BB180785",
        "ACADEMIA PRIVATE SCHOOL",
        None,
        "FL",
        "12095",
        "WINTER GARDEN",
        28.549944,
        -81.563301,
        "Orange County",
        "KG",
        "12",
    ),
    (
        "school",
        "A2300749",
        "HOUSE OF ACADEMIA, DBA ACADEMIA PRIVATE SCHL",
        None,
        "FL",
        "12095",
        "WINTER GARDEN",
        28.549944,
        -81.563301,
        "Orange County",
        "KG",
        "12",
    ),
    # Two Edison Middle Schools of Cleveland's market: Perry Local's in Massillon,
    # and Edison Local's in Berlin Heights, which NCES says was Berlin-Milan's.
    (
        "district",
        "3904992",
        "Perry Local",
        None,
        "OH",
        "39151",
        "Massillon",
        40.788085,
        -81.454346,
        "Stark County",
        None,
        None,
    ),
    (
        "school",
        "390499203747",
        "Edison Middle School",
        "3904992",
        "OH",
        "39151",
        "Massillon",
        40.788085,
        -81.454346,
        "Stark County",
        "07",
        "08",
    ),
    (
        "district",
        "3904678",
        "Edison Local (formerly Berlin-Milan)",
        None,
        "OH",
        "39043",
        "Milan",
        41.293,
        -82.6012,
        "Erie County",
        None,
        None,
    ),
    (
        "school",
        "390467802652",
        "Edison Middle School (formerly Berlin-Milan Middle School)",
        "3904678",
        "OH",
        "39043",
        "Berlin Heights",
        41.324,
        -82.4909,
        "Erie County",
        "04",
        "08",
    ),
    # Magnolia ISD's school in the town of Magnolia, Houston's market.
    (
        "district",
        "4828740",
        "MAGNOLIA ISD",
        None,
        "TX",
        "48339",
        "MAGNOLIA",
        30.19703,
        -95.753481,
        "Montgomery County",
        None,
        None,
    ),
    (
        "school",
        "482874003253",
        "MAGNOLIA EL",
        "4828740",
        "TX",
        "48339",
        "MAGNOLIA",
        30.205834,
        -95.749012,
        "Montgomery County",
        "PK",
        "04",
    ),
    # Two centres of the Cadence Academy chain: Collegeville's, which NCES says was
    # Flanagan's, and Folsom's.
    (
        "school",
        "A0701919",
        "CADENCE ACADEMY PRESCHOOL FORMERLY FLANAGAN'S PRES",
        None,
        "PA",
        "42091",
        "COLLEGEVILLE",
        40.20707,
        -75.459451,
        "Montgomery County",
        "PK",
        "TK",
    ),
    (
        "school",
        "A1970558",
        "CADENCE ACADEMY",
        None,
        "CA",
        "06067",
        "FOLSOM",
        38.65616,
        -121.130021,
        "Sacramento County",
        "PK",
        "KG",
    ),
)
"""Records from the NCES directory: kind, id, name, district, state, county FIPS, city,
latitude, longitude, county, lowest and highest grade."""


@pytest.fixture(scope="module")
def neighbours() -> Matcher:
    """A matcher over :data:`CHARTERS` and :data:`NEIGHBOURS`."""
    records = [record for row in CHARTERS for record in _charter(row)]
    for kind, rid, name, district, state, fips, city, lat, lon, county, low, high in NEIGHBOURS:
        records.append(
            DirectoryRecord(
                rid,
                name,
                "district" if kind == "district" else "school",
                district,
                state,
                fips,
                city,
                lat,
                lon,
                county=county,
                grade_low=low,
                grade_high=high,
            )
        )
    return Matcher(Directory(records))


@pytest.mark.parametrize(
    ("station", "listing", "targets"),
    [
        # NCES's whole name names its school, as before the name was read.
        ("gray-wtvg", "Kenmore Preparatory Academy dba Toledo Preparatory Academy", (KENMORE,)),
        ("gray-wtvg", "TOLEDO PREPARATORY ACADEMY", (KENMORE,)),
        ("gray-kpho", "Kaizen Education Foundation dba Summit High School", ("040038601894",)),
        # An old name names nothing, alone or as a school beside another.
        ("cbs-owned-wjz", "Oak Hill", ("240006000104",)),
        ("cbs-owned-wjz", "Oak Hill School", ("240006000104",)),
        ("cbs-owned-wjz", "Oak Hill High School", ()),
        # A name a dba gives a record past the station's counties is no rival.
        ("cox-whio", "Riverside", ("3904809",)),
        ("cox-whio", "Riverside Schools", ("3904809",)),
        ("tegna-kvue", "Magnolia School", ("BB162879",)),
        ("tegna-kvue", "The Magnolia School", ("BB162879",)),
        # In the counties it names the record.
        ("scripps-wcpo", "Riverside Academy", ("390004302979",)),
        # Houston's market holds Magnolia ISD's schools too, as good a name: the queue.
        ("abc-owned-ktrk", "Magnolia School", ()),
        # Two campuses that go by each other's names tie for either: the queue
        # (the lead's ruling D), and so does Avail Academy, a network of campuses.
        ("hubbard-kstp", "CALVIN CHRISTIAN SCHOOL", ()),
        ("hubbard-kstp", "Calvin Christian", ()),
        ("hubbard-kstp", "AVAIL ACADEMY", ()),
        ("hubbard-kstp", "Avail Academy", ()),
        # NCES's whole name, word for word, names the campus it is.
        ("hubbard-kstp", "AVAIL ACADEMY DBA CALVIN CHRISTIAN SCHOOL", ("A9502427",)),
        ("hubbard-kstp", "CALVIN CHRISTIAN SCHOOL (DBA: AVAIL ACADEMY)", ("BB220378",)),
        # A legal name three districts share names none of them.
        ("gray-kpho", "Kaizen Education Foundation", ()),
        # A name only a kind of school's names the school whose dba name it is.
        ("abc-owned-wabc", "The Hebrew Academy", ("02044228",)),
        ("abc-owned-wabc", "THE HEBREW ACADEMY", ("02044228",)),
        ("abc-owned-wabc", "Hebrew Academy", ("02044228",)),
        ("gray-wlbt", "The Education Center", ("00735625",)),
        ("gray-wlbt", "EDUCATION CENTER", ("00735625",)),
        ("gray-wlbt", "EDUCATION CENTER SCHOOL", ("00735625",)),
        # The name before formerly is the school's name now.
        ("cbs-owned-wjz", "Maya Angelou Academy at New Beginnings", ("110008700213",)),
        # So two schools of Cleveland's market are Edison Middle School: the queue.
        ("nexstar-wjw", "Edison Middle School", ()),
        (
            "nexstar-wjw",
            "Edison Middle School (formerly Berlin-Milan Middle School)",
            ("390467802652",),
        ),
        # The other Cleveland stations' lists read it so too (the lead's ruling 1).
        ("gray-woio", "Edison Middle School", ()),
        ("scripps-wews", "Edison Middle School", ()),
        ("tegna-wkyc", "Edison Middle School", ()),
        ("sinclair-wwho", "Edison Middle School", ()),
        # The old name is no name of it.
        ("nexstar-wjw", "Berlin-Milan Middle School", ()),
        # An operator's own district over the districts whose legal name it is.
        ("gray-kpho", "Edkey", ("0400415",)),
        ("gray-kpho", "Edkey Inc.", ("0400415",)),
        ("gray-kpho", "CPLC Community Schools", ("0400144",)),
        # In Tucson's counties two schools carry the name and tie: the queue.
        ("gray-kold", "CPLC Community Schools", ()),
        # A station of no counties has no market to tell the operator's own
        # district from the schools that carry its legal name: the queue, as the
        # lead ruled for a Tucson list's CPLC (never the Phoenix district), and so
        # for Edkey, whose records Tucson's counties do not hold.
        ("allen-kvoa", "Edkey", ()),
        ("allen-kvoa", "Edkey Inc.", ()),
        ("allen-kvoa", "EDKEY INC", ()),
        ("allen-kvoa", "CPLC Community Schools", ()),
        ("allen-kvoa", "CPLC", ()),
        ("allen-kvoa", "CPLC Community Schools Inc.", ()),
        # Past Columbus's counties a legal name is no rival of a school in them.
        ("sinclair-wsyx", "Dublin Preparatory Academy", ("A0502757",)),
        ("tegna-wbns", "Dublin Preparatory Academy", ("A0502757",)),
        ("nexstar-wcmh", "Dublin Preparatory Academy", ("A0502757",)),
        ("sinclair-wtte", "Dublin Preparatory Academy", ("A0502757",)),
        # With no counties, it is: the queue.
        ("sinclair-wwho", "Dublin Preparatory Academy", ()),
        # One school NCES lists twice at one point: its own name over the dba.
        ("cox-wftv", "Academia Private School", ("BB180785",)),
        ("cox-wftv", "ACADEMIA PRIVATE SCHL", ("BB180785",)),
        ("cox-wftv", "HOUSE OF ACADEMIA", ("A2300749",)),
        # The name a dba gives is worth NCES's whole (ALSO_NAME): Harrisburg's
        # Logos school over York's LOGOS ACADEMY.
        ("hearst-wgal", "Logos Academy Harrisburg", ("A2103316",)),
        # Three charter holders at one point: the one whose own name it is, with
        # or without counties.
        ("gray-kpho", "Intelli-School Inc.", ("0400061",)),
        ("allen-kvoa", "Intelli-School Inc.", ("0400061",)),
        # Two schools of one name today, Flagstaff's and the one Kaizen's Phoenix
        # school goes by, both in Phoenix's market: the queue (the lead's ruling).
        ("gray-kpho", "Summit High School", ()),
        ("gray-kpho", "Summit High", ()),
        ("allen-kvoa", "Summit High School", ()),
        # A chain's centre whose name is its brand alone, in its market, is named
        # by the brand, as a lone Goddard School is.
        ("hearst-kcra", "Cadence Academy", ("A1970558",)),
        # So is Collegeville's, the chain's lone centre in Philadelphia's market, by
        # the current name NCES gives it before formerly (the lead's ruling 4).
        ("abc-owned-wpvi", "Cadence Academy", ("A0701919",)),
        ("abc-owned-wpvi", "Cadence Academy Preschool", ("A0701919",)),
        ("abc-owned-wpvi", "CADENCE ACADEMY PRESCHOOL", ("A0701919",)),
        ("nbc-owned-wcau", "Cadence Academy", ("A0701919",)),
        # Its whole name names it, and its old name does not.
        (
            "abc-owned-wpvi",
            "CADENCE ACADEMY PRESCHOOL FORMERLY FLANAGAN'S PRES",
            ("A0701919",),
        ),
        ("abc-owned-wpvi", "Flanagan's Preschool", ()),
    ],
)
def test_a_dba_name_names_its_record_as_its_market_reads_it(
    neighbours: Matcher,
    stations: dict[str, Station],
    station: str,
    listing: str,
    targets: tuple[str, ...],
) -> None:
    assert _targets(neighbours, stations[station], listing) == targets


def test_a_name_only_a_kind_of_school_s_is_never_its_legal_name(
    stations: dict[str, Station],
) -> None:
    # NCES's SSDS OF GMC D/B/A THE HEBREW ACADEMY, its two names the other way
    # round: THE HEBREW ACADEMY is then its legal name, which a listing that says
    # only what kind of school it names does not name it by.
    hebrew = DirectoryRecord(
        "02044228",
        "THE HEBREW ACADEMY D/B/A SSDS OF GMC",
        "school",
        None,
        "NJ",
        "34025",
        "MARLBORO",
        40.312264,
        -74.246898,
        county="Monmouth County",
        grade_low="PK",
        grade_high="08",
    )
    matcher = Matcher(Directory([hebrew]))
    assert _targets(matcher, stations["abc-owned-wabc"], "The Hebrew Academy") == ()
    assert _targets(matcher, stations["abc-owned-wabc"], "SSDS OF GMC") == ("02044228",)


def _made_up(rid: str, name: str, point: tuple[float, float] | None) -> DirectoryRecord:
    """A school made up for a test, in Phoenix (Maricopa County, AZ), at ``point``."""
    lat, lon = point if point is not None else (None, None)
    return DirectoryRecord(
        rid,
        name,
        "school",
        None,
        "AZ",
        "04013",
        "PHOENIX",
        lat,
        lon,
        county="Maricopa County",
        grade_low="KG",
        grade_high="08",
    )


HERE = (33.45, -112.07)
THERE = (33.61, -111.89)


@pytest.mark.parametrize(
    ("records", "listing", "targets"),
    [
        # An aka's first name is the school's own, not an operator's legal name, so it
        # ties with another school's whole name: the queue.
        (
            (
                ("T1", "GREATER SUNRISE ACADEMY (AKA RISE UP ACADEMY)", HERE),
                ("T2", "GREATER SUNRISE ACADEMY", THERE),
            ),
            "Greater Sunrise Academy",
            {"gray-kpho": (), "allen-kvoa": ()},
        ),
        (
            (
                ("B1", "Beacon Grove Community School AKA Beacon Grove Academy", HERE),
                ("B2", "Beacon Grove Community School", THERE),
            ),
            "Beacon Grove Community School",
            {"gray-kpho": (), "allen-kvoa": ()},
        ),
        # The same name as a dba's legal name: the operator's own record where the
        # listing has counties; with none, the queue (the lead's ruling 3).
        (
            (
                ("D1", "GREATER SUNRISE ACADEMY DBA RISE UP ACADEMY", HERE),
                ("D2", "GREATER SUNRISE ACADEMY", THERE),
            ),
            "Greater Sunrise Academy",
            {"gray-kpho": ("D2",), "allen-kvoa": ()},
        ),
        # At one point, a record that says the listing only as its legal name is not
        # one that goes by it: with no counties, the queue.
        (
            (
                ("P1", "QUAIL RUN ACADEMY", HERE),
                ("P2", "QUAIL RUN ACADEMY DBA DESERT WREN SCHOOL", HERE),
            ),
            "Quail Run Academy",
            {"gray-kpho": ("P1",), "allen-kvoa": ()},
        ),
        # A record with no point is at no one place with another: the queue.
        (
            (
                ("N1", "QUAIL RUN ACADEMY", None),
                ("N2", "QUAIL RUN HOLDINGS DBA QUAIL RUN ACADEMY", HERE),
            ),
            "Quail Run Academy",
            {"gray-kpho": (), "allen-kvoa": ()},
        ),
        # A dba name of kind words NCES says beside a legal name (as "the education
        # center, inc. d/b/a education center") is the record's, word for word, over a
        # name that only ends with those words, with counties or without.
        (
            (
                ("K1", "SMITH HOLDINGS LLC DBA LEARNING CENTER", HERE),
                ("K2", "Kent Learning Center", THERE),
            ),
            "Learning Center",
            {"gray-kpho": ("K1",), "allen-kvoa": ("K1",)},
        ),
    ],
)
def test_a_tie_a_second_name_makes_is_broken_only_by_the_record_s_own_name(
    stations: dict[str, Station],
    records: tuple[tuple[str, str, tuple[float, float] | None], ...],
    listing: str,
    targets: dict[str, tuple[str, ...]],
) -> None:
    matcher = Matcher(Directory([_made_up(*record) for record in records]))
    for station, expected in targets.items():
        assert _targets(matcher, stations[station], listing) == expected, station
