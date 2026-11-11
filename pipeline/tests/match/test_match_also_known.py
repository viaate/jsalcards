"""A directory name that says ``dba`` or ``aka`` gives two names, and keeps its own.

NCES names some charter schools by their legal operator and the name they go by
(``"Kenmore Preparatory Academy dba Toledo Preparatory Academy"``). The matcher
reads both, beside NCES's whole name (:func:`~snowlight.match.normalize.also_known_as`);
an old name (``"... formerly Oak Hill"``) it does not read. Every name here is the
public NCES directory's, or two of them joined by the word.
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
        # A name that starts with DBA is the rest.
        ("DBA ELIZABETH SETON CHILDRENS SCHOOL", ("ELIZABETH SETON CHILDRENS SCHOOL", None)),
    ],
)
def test_a_name_that_says_dba_or_aka_gives_its_two_names(
    name: str, read: tuple[str, str | None]
) -> None:
    assert also_known_as(name, district=False) == read


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
        # An old name never names the record: formerly, fka, f/k/a.
        "Maya Angelou Academy at New Beginnings formerly Oak Hill",
        "Star Community School fka St. Timothy School",
        "STAR COMMUNITY SCHOOL F/K/A ST. TIMOTHY SCHOOL",
        "FORMERLY ST. TIMOTHY SCHOOL",
        "Edison Middle School (formerly Berlin-Milan Middle School)",
        # Two words: not read.
        "Kenmore Preparatory Academy dba Toledo Preparatory Academy aka Toledo Prep",
        "Beacon Hill Community School AKA Beacon Hill Academy (formerly Beacon Academy)",
        # The word inside a bracket it does not open, or in one NCES left open.
        "CALVIN CHRISTIAN SCHOOL (MINNEAPOLIS DBA AVAIL ACADEMY)",
        "CALVIN CHRISTIAN SCHOOL (DBA: AVAIL ACADEMY",
        "CALVIN CHRISTIAN SCHOOL (DBA: AVAIL ACADEMY) MINNEAPOLIS",
        # Part of another word.
        "Mishawaka High School",
        "Sewanhaka High School",
        "Toledo Preparatory and Fitness Academy",
        # A known miss: NCES glues the word to both names, and it stays unread.
        "East Branch Preparatory AcademydbaWright Preparatory Academy",
    ],
)
def test_a_name_without_two_names_is_read_as_one(name: str) -> None:
    assert also_known_as(name, district=False) is None


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
        ("abc-owned-ktrk", "Magnolia School", ("A2302944",)),
        # Two campuses that go by each other's names tie for either: the queue.
        ("hubbard-kstp", "CALVIN CHRISTIAN SCHOOL", ()),
        ("hubbard-kstp", "AVAIL ACADEMY", ()),
        ("hubbard-kstp", "AVAIL ACADEMY DBA CALVIN CHRISTIAN SCHOOL", ()),
        # A legal name three districts share names none of them.
        ("gray-kpho", "Kaizen Education Foundation", ()),
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
