"""District numbers and markets that tell same-named districts apart.

SYNTHETIC records beside the generated background: Kansas districts that share a
name and differ by the USD number their NCES names leave out
(:data:`~snowlight.match.numbers.UNSAID_NUMBERS`, patched here with the records'
ids), a Missouri district and an Illinois one that share a name and a number but
not the designator it follows (``"R-III"``, ``"CUSD 3"``), a Missouri number a
list writes in ones (``"R-111"``), a Missouri town's R-VI district beside the
county's R-VII that sits in the town, a numbered district a listing places by its
county, and the noise lists add around a name (a parochial-schools add-on, a
part that is only another's initials, ``"Acdmy"``).
"""

from collections.abc import Sequence

import pytest

from match import synthetic
from snowlight.match import Directory, DirectoryRecord, Matcher, Reason, index
from snowlight.match.normalize import clean_listing, listing_forms
from snowlight.match.numbers import UNSAID_NUMBERS

# Made-up counties and points: a Kansas market (Johby, Wyaby) whose namesake
# district lies in a county just past it (Rilby), a Missouri and Illinois market
# (Jeffby, Montby) with an Illinois county past it (Shelby), and a Missouri county
# of a numbered district (Barby).
JOHBY, WYABY, RILBY = "88971", "88972", "88973"
JEFFBY, MONTBY, SHELBY = "88974", "88975", "88976"
BARBY, HARBY, TREBY = "88977", "88978", "88979"
# Counties just past a market: Douby, past Kansas's Johby, and Madby, Illinois,
# past Missouri's Jeffby.
DOUBY, MADBY = "88980", "88981"
KC_MARKET = (JOHBY, WYABY)
STL_MARKET = (JEFFBY, MONTBY)
OVERLAND, RANDOLPH = (38.90, -94.68), (39.43, -96.76)
HILLSBORO_MO, HILLSBORO_IL = (38.23, -90.56), (39.16, -89.49)
WINDSOR_MO, WINDSOR_IL = (38.43, -90.43), (39.44, -88.60)
WASHBURN, EAGLEVILLE, WAKEFIELD = (36.59, -93.97), (40.47, -93.99), (39.02, -99.88)
LECOMB = (38.95, -95.25)
MAPLE_JEFFBY, MAPLE_MADBY = (38.30, -90.40), (38.60, -89.95)


def _district(  # noqa: PLR0913, PLR0917 - one argument per NCES column
    record_id: str, name: str, state: str, county: str, city: str, point: tuple[float, float]
) -> DirectoryRecord:
    county_name = {BARBY: "Barby County", TREBY: "Treby County", JOHBY: "Johby County"}.get(county)
    return DirectoryRecord(
        record_id, name, "district", None, state, county, city, *point, county=county_name
    )


def _school(  # noqa: PLR0913, PLR0917 - one argument per NCES column
    record_id: str, name: str, district: str, state: str, county: str, city: str
) -> DirectoryRecord:
    return DirectoryRecord(record_id, name, "school", district, state, county, city, None, None)


RECORDS: tuple[DirectoryRecord, ...] = (
    # Kansas: two districts of one name, numbered 229 and 384 by the state.
    _district("SYN-KS-BLJ", "Bluestem Vale", "KS", JOHBY, "Overland", OVERLAND),
    _school("SYN-KS-BLJHS", "Bluestem Vale High", "SYN-KS-BLJ", "KS", JOHBY, "Overland"),
    _school("SYN-KS-BLJMS", "Bluestem Vale Middle", "SYN-KS-BLJ", "KS", JOHBY, "Overland"),
    # Schools whose names share a word with districts just past the market.
    _school("SYN-KS-BLJK", "Kestrel Ridge Elementary", "SYN-KS-BLJ", "KS", JOHBY, "Overland"),
    _school("SYN-KS-BLJO", "Osby Trail Elementary", "SYN-KS-BLJ", "KS", JOHBY, "Overland"),
    _school("SYN-KS-BLJP", "Pleasby Park Elementary", "SYN-KS-BLJ", "KS", JOHBY, "Overland"),
    # Bluestem Vale's school in Olbury, the town of another district numbered 233.
    _school("SYN-KS-BLJES", "Prairie Star Elementary", "SYN-KS-BLJ", "KS", JOHBY, "Olbury"),
    _district("SYN-KS-OLB", "Olbury", "KS", JOHBY, "Olbury", OVERLAND),
    _school("SYN-KS-OLBHS", "Olbury North High", "SYN-KS-OLB", "KS", JOHBY, "Olbury"),
    _district("SYN-KS-BLR", "Bluestem Vale", "KS", RILBY, "Randolph", RANDOLPH),
    _school("SYN-KS-BLRHS", "Bluestem Vale High", "SYN-KS-BLR", "KS", RILBY, "Randolph"),
    # One of its schools lies in Douby, just past the market's counties.
    _school("SYN-KS-BLRES", "Olsby Elementary", "SYN-KS-BLR", "KS", DOUBY, "Olsby"),
    # A district the lists name by its number and its town.
    _district("SYN-KS-LAR", "Larkworth", "KS", WYABY, "Larkworth", OVERLAND),
    _school("SYN-KS-LARHS", "Larkworth Sr High", "SYN-KS-LAR", "KS", WYABY, "Larkworth"),
    _district("SYN-KS-TRE", "Treby County", "KS", TREBY, "Wakefield", WAKEFIELD),
    _school("SYN-KS-TREHS", "Treby Community High", "SYN-KS-TRE", "KS", TREBY, "Wakefield"),
    # Missouri and Illinois: one name and one number, after other designators.
    _district("SYN-MO-HIL", "HILLCREST R-III", "MO", JEFFBY, "HILLCREST", HILLSBORO_MO),
    _school("SYN-MO-HILHS", "HILLCREST HIGH", "SYN-MO-HIL", "MO", JEFFBY, "HILLCREST"),
    _district("SYN-IL-HIL", "Hillcrest CUSD 3", "IL", MONTBY, "Hillcrest", HILLSBORO_IL),
    _school("SYN-IL-HILHS", "Hillcrest High School", "SYN-IL-HIL", "IL", MONTBY, "Hillcrest"),
    _district("SYN-MO-WIN", "WINDMERE C-1", "MO", JEFFBY, "IMPERIAL", WINDSOR_MO),
    _school("SYN-MO-WINES", "WINDMERE ELEM.", "SYN-MO-WIN", "MO", JEFFBY, "IMPERIAL"),
    _district("SYN-IL-WIN", "Windmere CUSD 1", "IL", SHELBY, "Windmere", WINDSOR_IL),
    _school("SYN-IL-WINES", "Windmere Elem School", "SYN-IL-WIN", "IL", SHELBY, "Windmere"),
    # Illinois: a consolidated district a list calls a unit district.
    _district("SYN-IL-ASH", "Ashgrove-Ellis Cons SD 61", "IL", MONTBY, "Ashgrove", HILLSBORO_IL),
    # Missouri: Roman numbers a list may write in ones, and a county a listing names.
    _district("SYN-MO-NHA", "NORTH HARLAN R-III", "MO", HARBY, "EAGLEVILLE", EAGLEVILLE),
    _school("SYN-MO-NHAHS", "NORTH HARLAN HIGH", "SYN-MO-NHA", "MO", HARBY, "EAGLEVILLE"),
    _district("SYN-MO-FAI", "FAIRLOCK R-II", "MO", HARBY, "FAIRLOCK", EAGLEVILLE),
    _district("SYN-MO-ELV", "ELMVALE R-XI", "MO", HARBY, "ELMVALE", EAGLEVILLE),
    _district("SYN-MO-ELII", "ELMVALE R-II", "MO", BARBY, "ELMVALE", WASHBURN),
    _district("SYN-MO-SWI", "SOUTHWIND R-V", "MO", BARBY, "WASHBURN", WASHBURN),
    _school("SYN-MO-SWIES", "SOUTHWIND ELEM.", "SYN-MO-SWI", "MO", BARBY, "WASHBURN"),
    # Michigan: a district whose initials a list writes beside its name, a charter academy.
    _district("SYN-MI-TCA", "Tarrow City Area Public Schools", "MI", HARBY, "Tarrow", EAGLEVILLE),
    _district("SYN-MI-FLA", "Flagstone Charter Academy", "MI", HARBY, "Tarrow", EAGLEVILLE),
    _school("SYN-MI-FLAS", "Flagstone Charter Academy", "SYN-MI-FLA", "MI", HARBY, "Tarrow"),
    # A Kansas district named for its town, beside the county's.
    _district("SYN-KS-ELC", "Ellby County", "KS", TREBY, "Ellbyton", WAKEFIELD),
    _district("SYN-KS-ELT", "Ellby", "KS", TREBY, "Ellby", WAKEFIELD),
    # A Kansas district whose name holds another's.
    _district("SYN-KS-PAW", "Pawby", "KS", TREBY, "Pawby", WAKEFIELD),
    _district("SYN-KS-NPA", "Pawby-Minnby", "KS", TREBY, "Minnby", WAKEFIELD),
    # Illinois: a high school district over the town of an elementary one.
    _district("SYN-IL-DEE", "Deerwood SD 109", "IL", MONTBY, "Deerwood", HILLSBORO_IL),
    _district("SYN-IL-T113", "Twp HSD 113", "IL", MONTBY, "Highmoor", HILLSBORO_IL),
    _school("SYN-IL-T113D", "Deerwood High School", "SYN-IL-T113", "IL", MONTBY, "Deerwood"),
    _school("SYN-IL-T113H", "Highmoor High School", "SYN-IL-T113", "IL", MONTBY, "Highmoor"),
    # Illinois: districts of one town told apart by the numbers their names say.
    _district("SYN-IL-NO28", "Northmere SD 28", "IL", MONTBY, "Northmere", HILLSBORO_IL),
    _district("SYN-IL-NO30", "Northmere/Glenby SD 30", "IL", MONTBY, "Northmere", HILLSBORO_IL),
    # A Kansas district just past the market's counties, numbered 343, a school of
    # it whose name gives a number, a district whose name gives only its number,
    # and a Missouri district whose name gives none.
    _district("SYN-KS-LEC", "Lecomb Valley", "KS", DOUBY, "Lecomb", LECOMB),
    _school("SYN-KS-KES", "Kestrel 12", "SYN-KS-LEC", "KS", DOUBY, "Lecomb"),
    _district("SYN-KS-SD344", "School District 344", "KS", DOUBY, "Pleasby", LECOMB),
    _district("SYN-MO-OSB", "OSBY", "MO", DOUBY, "OSBY", LECOMB),
    # Missouri: a district named for its county, and a school of another district
    # whose name gives its number.
    _district("SYN-MO-KIR", "KIRBY CO. R-IX", "MO", HARBY, "KIRBY", EAGLEVILLE),
    _school("SYN-MO-KIRC", "KIRBY 9", "SYN-MO-FAR", "MO", HARBY, "FARMSTEAD"),
    # A district whose name says no kind of designator, and a namesake past the
    # counties, across a state line, whose designator is another than the listing's.
    _district("SYN-IL-ASB", "Ashby SD 4", "IL", MONTBY, "Ashby", HILLSBORO_IL),
    _district("SYN-MO-ASB", "ASHBY C-4", "MO", MADBY, "ASHBY", MAPLE_MADBY),
    # Namesakes in the counties and just past them, across a state line.
    _district("SYN-MO-MAP", "MAPLE RUN R-IV", "MO", JEFFBY, "MAPLE RUN", MAPLE_JEFFBY),
    _district("SYN-IL-MAP", "Maple Run CUSD 4", "IL", MADBY, "Maple Run", MAPLE_MADBY),
    # Missouri: a district whose schools carry a name its own does not.
    _district("SYN-MO-JOH", "JOHBY CO. R-VII", "MO", BARBY, "KNOB HILL", WASHBURN),
    _school("SYN-MO-JOHES", "CREST FIELD ELEM.", "SYN-MO-JOH", "MO", BARBY, "KNOB HILL"),
    _school("SYN-MO-JOHHS", "CREST FIELD HIGH", "SYN-MO-JOH", "MO", BARBY, "KNOB HILL"),
    # Missouri: a district named for its county, and a school of that name in another R-VII.
    _district("SYN-MO-JEF", "JEFFBY CO. R-VII", "MO", HARBY, "FESTON", EAGLEVILLE),
    _school("SYN-MO-JEFHS", "JEFFBY HIGH SCHOOL", "SYN-MO-JEF", "MO", HARBY, "FESTON"),
    _district("SYN-MO-FAR", "FARMSTEAD R-VII", "MO", HARBY, "FARMSTEAD", EAGLEVILLE),
    _school("SYN-MO-FARES", "JEFFBY ELEM.", "SYN-MO-FAR", "MO", HARBY, "FARMSTEAD"),
    # Missouri: the R-VI district of Feston, the town JEFFBY CO. R-VII sits in and
    # names a school after, and a district of the county's name after another
    # designator, far from both.
    _district("SYN-MO-FES", "FESTON R-VI", "MO", HARBY, "FESTON", EAGLEVILLE),
    _school("SYN-MO-FESES", "FESTON ELEM.", "SYN-MO-FES", "MO", HARBY, "FESTON"),
    _school("SYN-MO-JEFFI", "FESTON INTERMEDIATE", "SYN-MO-JEF", "MO", HARBY, "FESTON"),
    _district("SYN-MO-JEC", "JEFFBY C-123", "MO", BARBY, "CONCEPTION", WASHBURN),
    # Missouri: districts that bear their county's name, one of them with "CO.".
    _district("SYN-MO-BAR12", "BARBY R-XII", "MO", BARBY, "BARBYTON", WASHBURN),
    _district("SYN-MO-BAR14", "BARBY CO. R-XIV", "MO", BARBY, "KNOLL", WASHBURN),
    # And one that does not, though a school of it does.
    _district("SYN-MO-KNO", "KNOLL R-XV", "MO", BARBY, "KNOLL", WASHBURN),
    _school("SYN-MO-KNOES", "BARBY ELEM.", "SYN-MO-KNO", "MO", BARBY, "KNOLL"),
)
"""SYNTHETIC districts that share names, and their schools."""

UNSAID: dict[str, str] = {
    "SYN-KS-BLJ": "229",
    "SYN-KS-BLR": "384",
    "SYN-KS-LAR": "453",
    "SYN-KS-TRE": "208",
    "SYN-KS-OLB": "233",
    "SYN-KS-LEC": "343",
    "SYN-KS-ELC": "270",
    "SYN-KS-ELT": "271",
    "SYN-KS-PAW": "290",
    "SYN-KS-NPA": "239",
}
"""The USD numbers of the Kansas records, which their names leave out."""


@pytest.fixture(scope="module")
def matcher(background: list[synthetic.SyntheticRecord]) -> Matcher:
    """A matcher over the generated background and :data:`RECORDS`."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(index, "UNSAID_NUMBERS", UNSAID)
        return Matcher(Directory([*(item.record for item in background), *RECORDS]))


def _target(
    matcher: Matcher, listing: str, states: Sequence[str], counties: Sequence[str]
) -> str | None:
    result = matcher.match(listing, states=states, counties=counties)
    return result.target.id if result.target is not None else None


@pytest.mark.parametrize(
    "listing",
    [
        "Bluestem Vale USD 229",
        "Bluestem Vale USD #229",
        "Bluestem Vale USD229",
        "Bluestem Vale KS Schools - USD 229",
        "USD 229 Bluestem Vale",
        "Bluestem Vale Unified School District 229",
    ],
)
def test_a_kansas_usd_number_names_the_district_of_that_number(
    matcher: Matcher, listing: str
) -> None:
    assert _target(matcher, listing, ("KS", "MO"), KC_MARKET) == "SYN-KS-BLJ"


def test_the_number_names_the_district_wherever_it_lies(matcher: Matcher) -> None:
    assert _target(matcher, "USD 384 Bluestem Vale", ("KS",), (RILBY,)) == "SYN-KS-BLR"
    assert _target(matcher, "USD 384 Bluestem Vale", ("KS",), (*KC_MARKET, RILBY)) == "SYN-KS-BLR"
    assert _target(matcher, "USD 229 Bluestem Vale", ("KS",), (*KC_MARKET, RILBY)) == "SYN-KS-BLJ"


def test_a_number_that_contradicts_a_district_never_names_it(matcher: Matcher) -> None:
    # The market's Bluestem Vale is USD 229: a listing of USD 512 is not it, nor
    # the one numbered 384, wherever the counties reach.
    assert _target(matcher, "Bluestem Vale USD 512", ("KS",), KC_MARKET) is None
    assert _target(matcher, "Bluestem Vale USD 512", ("KS",), (*KC_MARKET, RILBY)) is None
    assert _target(matcher, "USD 999 Wakefield", ("KS",), (TREBY,)) is None


def test_a_name_and_its_number_name_the_district_just_past_the_counties(
    matcher: Matcher,
) -> None:
    # Lecomb Valley USD 343 lies in Douby, just past the market's counties: the
    # name and the number say it together.
    assert _target(matcher, "Lecomb Valley USD 343", ("KS",), KC_MARKET) == "SYN-KS-LEC"
    assert _target(matcher, "Lecomb Valley - USD #343", ("KS",), KC_MARKET) == "SYN-KS-LEC"
    # A number alone, a name alone, a town of the district with its number, or a
    # name with another's number, never.
    assert _target(matcher, "USD 343", ("KS",), KC_MARKET) is None
    assert _target(matcher, "Lecomb Valley", ("KS",), KC_MARKET) is None
    assert _target(matcher, "USD 343 Lecomb", ("KS",), KC_MARKET) is None
    assert _target(matcher, "Lecomb USD 343", ("KS",), KC_MARKET) is None
    assert _target(matcher, "Lecomb Valley USD 342", ("KS",), KC_MARKET) is None
    # Nor a district far past the market, though one of its schools lies just past
    # it, nor one of a state the list does not cover.
    assert _target(matcher, "Bluestem Vale USD 384", ("KS",), KC_MARKET) is None
    assert _target(matcher, "USD 384 Bluestem Vale", ("KS",), KC_MARKET) is None
    assert _target(matcher, "Treby County - USD 208", ("KS",), KC_MARKET) is None
    assert _target(matcher, "Lecomb Valley USD 343", ("MO",), KC_MARKET) is None


@pytest.mark.parametrize(
    "listing",
    [
        "Olbury USD 229",
        "Olbury Schools USD 229",
        "USD 229 Olbury Public Schools",
        # Words that only place the name: qualifiers, the county, the state,
        # another district's name.
        "Olbury Area USD 229",
        "City of Olbury USD 229",
        "Olbury City Schools USD 229",
        "Olbury (Johby Co.) USD 229",
        "Olbury Johby County USD 229",
        "Olbury KS USD 229",
        "Olbury & Lecomb Valley USD 229",
    ],
)
def test_a_number_that_contradicts_the_name_a_listing_gives_names_neither(
    matcher: Matcher, listing: str
) -> None:
    # Olbury is USD 233, and Bluestem Vale, USD 229, has a school in Olbury: the
    # listing names one district by its name and another by its number.
    result = matcher.match(listing, states=("KS",), counties=KC_MARKET)
    assert result.target is None
    assert all(record.id != "SYN-KS-BLJ" for record in result.targets)


def test_a_listing_that_says_the_numbered_district_s_name_names_it(matcher: Matcher) -> None:
    # Its own name beside another's, or a word of its own name beside another's.
    assert _target(matcher, "Olbury/Bluestem Vale USD 229", ("KS",), KC_MARKET) == "SYN-KS-BLJ"
    assert _target(matcher, "Olbury Bluestem USD 229", ("KS",), KC_MARKET) == "SYN-KS-BLJ"


def test_a_name_and_part_of_another_s_with_its_number_name_neither(matcher: Matcher) -> None:
    # Pawby is USD 290, and "Pawby-Minnby" USD 239: the listing says Pawby's name
    # and only part of Pawby-Minnby's.
    assert _target(matcher, "Pawby USD 239", ("KS",), (TREBY,)) is None
    assert _target(matcher, "Pawby USD 290", ("KS",), (TREBY,)) == "SYN-KS-PAW"
    assert _target(matcher, "Pawby-Minnby USD 239", ("KS",), (TREBY,)) == "SYN-KS-NPA"
    assert _target(matcher, "USD 239 Minnby", ("KS",), (TREBY,)) == "SYN-KS-NPA"


def test_where_districts_overlap_a_town_s_district_is_no_other_name(matcher: Matcher) -> None:
    # Illinois's high school district lies over the town of Deerwood SD 109.
    listing = "DIST #113 (HIGHMOOR & DEERWOOD HIGH SCHOOLS)"
    assert _target(matcher, listing, ("IL",), STL_MARKET) == "SYN-IL-T113"


def test_a_town_of_the_numbered_district_is_no_other_name(matcher: Matcher) -> None:
    assert _target(matcher, "Olbury USD 233", ("KS",), KC_MARKET) == "SYN-KS-OLB"
    # Treby County's own word, without its "County", is no other district's name.
    assert _target(matcher, "Treby USD 208", ("KS",), (TREBY,)) == "SYN-KS-TRE"
    # "County" is part of the name: Ellby County is not the town's district Ellby.
    assert _target(matcher, "Ellby County USD 270", ("KS",), (TREBY,)) == "SYN-KS-ELC"
    assert _target(matcher, "Ellby USD 271", ("KS",), (TREBY,)) == "SYN-KS-ELT"
    assert _target(matcher, "Ellby USD 270", ("KS",), (TREBY,)) is None
    # A town whose district's name says its number too is no name of that district.
    assert _target(matcher, "Northmere District 30", ("IL",), STL_MARKET) == "SYN-IL-NO30"
    assert _target(matcher, "Northmere District 28", ("IL",), STL_MARKET) == "SYN-IL-NO28"


def test_without_a_number_the_namesakes_stay_ambiguous(matcher: Matcher) -> None:
    result = matcher.match("Bluestem Vale", states=("KS",), counties=(*KC_MARKET, RILBY))
    assert result.target is None
    assert result.reason is Reason.AMBIGUOUS
    # Alone in the counties, the number the name leaves out costs it nothing.
    assert _target(matcher, "Bluestem Vale Schools", ("KS",), (RILBY,)) == "SYN-KS-BLR"


def test_a_school_listed_with_its_district_number_is_that_district_s(matcher: Matcher) -> None:
    listing = "USD 229 Bluestem Vale High"
    assert _target(matcher, listing, ("KS",), (*KC_MARKET, RILBY)) == "SYN-KS-BLJHS"
    listing = "USD 384 Bluestem Vale High"
    assert _target(matcher, listing, ("KS",), (*KC_MARKET, RILBY)) == "SYN-KS-BLRHS"


@pytest.mark.parametrize(
    "listing",
    [
        "Larkworth USD453 & Parochial Schools",
        "Larkworth 453 & Parochial Schools",
        "Larkworth USD 453 - Parochial Schools",
        "Larkworth KS Sch. USD 453-Parochial",
        "Larkworth Public and Parochial Schools",
        # A district number before the town names the district the town's is.
        "USD 453 - Larkworth & Parochial Schools",
        # Bare "Schools" joined to the add-on reads as both.
        "Larkworth Schools and Parochial",
        "Larkworth Schools/Parochial",
    ],
)
def test_the_parochial_schools_beside_a_district_leave_the_district(
    matcher: Matcher, listing: str
) -> None:
    assert _target(matcher, listing, ("KS", "MO"), KC_MARKET) == "SYN-KS-LAR"


@pytest.mark.parametrize(
    "listing",
    [
        "Larkworth - Parochial Schools",
        "Larkworth - Parochial",
        "Larkworth/Parochial",
        "Larkworth & Parochial",
        "Larkworth Parochial Schools",
        # After a dash, bare "Schools" may be the town's parochial schools alone.
        "Larkworth Schools - Parochial",
        "Larkworth Sch. - Parochial",
        "Larkworth Schools - Parochial Schools",
    ],
)
def test_a_town_s_parochial_schools_alone_are_not_its_district(
    matcher: Matcher, listing: str
) -> None:
    assert _target(matcher, listing, ("KS", "MO"), KC_MARKET) is None


@pytest.mark.parametrize(
    "listing",
    [
        "Catholic & Parochial Schools",
        "Private and Parochial Schools",
        "Public, Private and Parochial Schools",
        "Public & Parochial Schools",
    ],
)
def test_parochial_schools_beside_no_named_district_name_nothing(
    matcher: Matcher, listing: str
) -> None:
    assert "Parochial" in clean_listing(listing).text
    assert _target(matcher, listing, ("KS", "MO"), KC_MARKET) is None


def test_a_namesake_across_a_state_line_leaves_the_listing_to_the_queue(
    matcher: Matcher,
) -> None:
    # Illinois's Maple Run lies just past the Missouri market's counties: a list
    # strays across the line, and the counties cannot say which it names.
    result = matcher.match("Maple Run Schools", states=("IL", "MO"), counties=STL_MARKET)
    assert result.target is None
    assert result.reason is Reason.AMBIGUOUS
    assert "just past them" in result.detail
    # Its designator says Missouri's.
    assert _target(matcher, "Maple Run R-4", ("IL", "MO"), STL_MARKET) == "SYN-MO-MAP"


@pytest.mark.parametrize("listing", ["Crestfield R-7", "Crestfield R-VII"])
def test_a_district_number_names_the_district_its_schools_name(
    matcher: Matcher, listing: str
) -> None:
    # Every school of JOHBY CO. R-VII is Crest Field's, which the listing writes as
    # one word, and the number is its own.
    assert _target(matcher, listing, ("MO",), (BARBY,)) == "SYN-MO-JOH"
    # Another number is another district's.
    assert _target(matcher, "Crestfield R-6", ("MO",), (BARBY,)) is None


def test_a_district_number_favours_the_district_over_schools(matcher: Matcher) -> None:
    # JEFFBY ELEM. is a school of another R-VII; the listing names a district.
    assert _target(matcher, "Jeffby R-VII", ("MO",), (HARBY,)) == "SYN-MO-JEF"
    # Saying a school, it may be either.
    assert _target(matcher, "Jeffby Elem", ("MO",), (HARBY,)) == "SYN-MO-FARES"


def test_a_missouri_number_run_into_its_designator(matcher: Matcher) -> None:
    assert _target(matcher, "North Harlan RIII", ("MO",), (HARBY,)) == "SYN-MO-NHA"
    assert _target(matcher, "Fairlock RII", ("MO",), (HARBY,)) == "SYN-MO-FAI"
    assert listing_forms("Swedeborg RIII").district.district_numbers == {"3"}
    assert listing_forms("Swedeborg RIII").district.designators == {"r"}


def test_a_number_and_the_district_s_town_name_the_district(matcher: Matcher) -> None:
    assert _target(matcher, "USD 208 Wakefield", ("KS",), (TREBY,)) == "SYN-KS-TRE"
    assert _target(matcher, "Treby Community Schools - USD 208", ("KS",), (TREBY,)) == "SYN-KS-TRE"


@pytest.mark.parametrize("listing", ["Hillcrest R-3", "Hillcrest R3", "Hillcrest R 3 Schools"])
def test_a_missouri_designator_names_the_missouri_district(matcher: Matcher, listing: str) -> None:
    assert _target(matcher, listing, ("IL", "MO"), STL_MARKET) == "SYN-MO-HIL"


def test_an_illinois_designator_names_the_illinois_district(matcher: Matcher) -> None:
    assert _target(matcher, "Hillcrest CUSD 3", ("IL", "MO"), STL_MARKET) == "SYN-IL-HIL"
    # The number alone says neither state's.
    result = matcher.match("Hillcrest 3", states=("IL", "MO"), counties=STL_MARKET)
    assert result.target is None
    assert result.reason is Reason.AMBIGUOUS


def test_a_designator_tells_a_namesake_just_past_the_counties_apart(matcher: Matcher) -> None:
    for listing in ("Windmere C-1", "Windmere C 1"):
        assert _target(matcher, listing, ("IL", "MO"), STL_MARKET) == "SYN-MO-WIN"
    # Illinois's designator names Illinois's, wherever the counties reach.
    counties = (*STL_MARKET, SHELBY)
    assert _target(matcher, "Windmere CUSD 1", ("IL", "MO"), counties) == "SYN-IL-WIN"
    # A designator of another kind of district never names it alone.
    assert _target(matcher, "Windmere CUSD 1", ("MO",), STL_MARKET) is None
    assert _target(matcher, "Hillcrest R-3", ("IL",), STL_MARKET) is None


def test_designators_of_one_state_s_words_never_rule_a_district_out(matcher: Matcher) -> None:
    # Lists write "CUSD" for Illinois's consolidated districts as well.
    listing = "Ashgrove Ellis CUSD #61"
    assert _target(matcher, listing, ("IL", "MO"), STL_MARKET) == "SYN-IL-ASH"


def test_a_roman_number_written_in_ones_is_read_as_roman(matcher: Matcher) -> None:
    listing = "North Harlan R-111 Eagleville MO"
    assert _target(matcher, listing, ("MO",), (HARBY,)) == "SYN-MO-NHA"
    assert _target(matcher, "Fairlock R-11", ("MO",), (HARBY,)) == "SYN-MO-FAI"
    # A district numbered 11 keeps its number: beside a namesake numbered 2, a
    # listing of R-11 may be either, and goes to the queue.
    assert _target(matcher, "Elmvale R-11", ("MO",), (HARBY,)) == "SYN-MO-ELV"
    assert _target(matcher, "Elmvale R-11", ("MO",), (BARBY,)) == "SYN-MO-ELII"
    assert _target(matcher, "Elmvale R-11", ("MO",), (HARBY, BARBY)) is None
    assert _target(matcher, "Elmvale R-XI", ("MO",), (HARBY, BARBY)) == "SYN-MO-ELV"
    assert _target(matcher, "Elmvale R-2", ("MO",), (HARBY, BARBY)) == "SYN-MO-ELII"


def test_a_numbered_district_placed_by_its_county(matcher: Matcher) -> None:
    for listing in ("Southwind Barby County R-5", "Southwind Barby Co R-V"):
        assert _target(matcher, listing, ("MO",), (BARBY, HARBY)) == "SYN-MO-SWI"
    # Another county's name is not the district's.
    assert _target(matcher, "Southwind Harby County R-5", ("MO",), (BARBY, HARBY)) is None


def test_initials_beside_the_name_and_a_short_academy(matcher: Matcher) -> None:
    listing = "TCAPS - Tarrow City Area Public Schools"
    assert _target(matcher, listing, ("MI",), (HARBY,)) == "SYN-MI-TCA"
    assert _target(matcher, "Flagstone Charter Acdmy", ("MI",), (HARBY,)) == "SYN-MI-FLAS"


def test_listing_forms_say_the_designator_family() -> None:
    def designators(text: str) -> frozenset[str]:
        clean = clean_listing(text)
        return listing_forms(clean.text, district_hint=clean.all_schools).district.designators

    assert designators("Hillsboro R-3") == {"r"}
    assert designators("Valley RE-1") == {"r"}
    assert designators("Windsor C-1") == {"c"}
    assert designators("Hillsboro CUSD 3") == {"unit"}
    assert designators("Hillsboro Unit 3") == {"unit"}
    # A plain district's designator says no kind of district.
    assert designators("Blue Valley USD #229") == frozenset()
    assert designators("USD 320 Wamego") == frozenset()
    assert designators("Widefield D-3") == frozenset()
    assert designators("Grandview School District 4") == frozenset()
    assert designators("Primero Reorganized School District No. 2") == frozenset()
    assert designators("Lisbon CCSD 90") == frozenset()
    assert designators("Grandview CSD #4") == frozenset()
    assert listing_forms("North Harrison R-111").district.ones == {"111"}
    assert listing_forms("Fair Play R-11").district.ones == {"11"}
    assert listing_forms("Elmvale R-XI").district.ones == frozenset()
    assert listing_forms("Elmvale 111").district.ones == frozenset()
    assert designators("Lincoln Elementary") == frozenset()


def test_clean_listing_drops_parochial_add_ons_and_initials() -> None:
    assert clean_listing("Leavenworth USD453 & Parochial Schools").text == "Leavenworth USD453"
    assert clean_listing("Frankenmuth Public/Parochial Schools").text == "Frankenmuth Public"
    assert clean_listing("Chilton Public \u2013 Parochial").text == "Chilton Public"
    assert clean_listing("Hillsboro R-3 - Parochial").text == "Hillsboro R-3"
    assert clean_listing("Ft. Dodge Schools - Parochial").text == "Ft. Dodge Schools Parochial"
    assert clean_listing("Ft. Dodge 1 - Parochial").text == "Ft. Dodge 1 Parochial"
    text = "USD 453 - Leavenworth & Parochial Schools"
    assert clean_listing(text).text == "USD 453 Leavenworth"
    # A public word earlier in the listing says nothing of the part before the add-on.
    assert clean_listing("Public, Private and Parochial").text == "Public Private and Parochial"
    # A parochial school's own name stays.
    assert clean_listing("St Mary Parochial School").text == "St Mary Parochial School"
    assert clean_listing("Parochial Schools").text == "Parochial Schools"
    text = "TCAPS - Traverse City Area Public Schools"
    assert clean_listing(text).segments == ("Traverse City Area Public Schools",)
    # Capitals that are not another part's initials stay.
    assert clean_listing("SAU 16 - Exeter").segments == ("SAU 16", "Exeter")
    assert clean_listing("KIPP - KIPP Academy").segments == ("KIPP", "KIPP Academy")


def test_the_shipped_kansas_numbers_are_one_per_district() -> None:
    # Kansas's NCES district ids, each with its own three-digit USD number.
    assert len(UNSAID_NUMBERS) > 280
    assert all(len(key) == 7 and key.startswith("20") for key in UNSAID_NUMBERS)
    assert all(len(number) == 3 and number.isdigit() for number in UNSAID_NUMBERS.values())
    assert len(set(UNSAID_NUMBERS.values())) == len(UNSAID_NUMBERS)


def test_past_the_counties_only_a_district_s_own_name_and_number_name_it(
    matcher: Matcher,
) -> None:
    # A school whose name gives the number, a district whose name is only its
    # number, and a district not numbered by the listing's number (Missouri's
    # OSBY, whose name gives none).
    assert _target(matcher, "Kestrel D-12", ("KS",), KC_MARKET) is None
    assert _target(matcher, "Pleasby District 344", ("KS",), KC_MARKET) is None
    assert _target(matcher, "USD 456 Osby City", ("KS", "MO"), KC_MARKET) is None
    assert _target(matcher, "Osby USD 456", ("KS", "MO"), KC_MARKET) is None


def test_a_school_whose_name_gives_the_number_stays_a_rival(matcher: Matcher) -> None:
    # "KIRBY 9", a school of another district, bears the number as its name.
    result = matcher.match("Kirby R-IX", states=("MO",), counties=(HARBY,))
    assert result.target is None
    assert result.reason is Reason.AMBIGUOUS


def test_a_district_number_with_a_school_level_names_the_school(matcher: Matcher) -> None:
    # Saying a school, the listing is not read as the district its number names.
    assert _target(matcher, "Jeffby R-VII Elem", ("MO",), (HARBY,)) == "SYN-MO-FARES"


def test_a_designator_neither_namesake_follows_tells_neither_apart(matcher: Matcher) -> None:
    # "R-4" is neither Illinois's "Ashby SD 4" in the counties nor Missouri's
    # "ASHBY C-4" just past them: the namesake stays.
    result = matcher.match("Ashby R-4", states=("IL", "MO"), counties=STL_MARKET)
    assert result.target is None
    assert result.reason is Reason.AMBIGUOUS


@pytest.mark.parametrize(
    "listing",
    [
        "Feston R-7",
        "Feston R-VII",
        "Feston Area R-7",
        "City of Feston R-7",
        "Feston (Harby Co.) R-7",
        "Feston Schools R-7",
        # A number without a designator is no less R-VII's.
        "Feston District 7",
    ],
)
def test_a_missouri_number_that_contradicts_the_name_names_neither(
    matcher: Matcher, listing: str
) -> None:
    # Feston is R-VI by its name; JEFFBY CO. R-VII sits in Feston and has a school
    # of its name: the listing names one district by its name and another by its
    # number.
    result = matcher.match(listing, states=("MO",), counties=(HARBY,))
    assert result.target is None
    assert all(record.id not in {"SYN-MO-JEF", "SYN-MO-JEFFI"} for record in result.targets)


def test_a_missouri_name_with_its_own_number_names_its_district(matcher: Matcher) -> None:
    assert _target(matcher, "Feston R-6", ("MO",), (HARBY,)) == "SYN-MO-FES"
    assert _target(matcher, "Feston R-VI", ("MO",), (HARBY,)) == "SYN-MO-FES"
    # A level names the school of that name, whose district's number it is.
    assert _target(matcher, "Feston Intermediate R-7", ("MO",), (HARBY,)) == "SYN-MO-JEFFI"
    # The county's name is JEFFBY CO. R-VII's own, though JEFFBY C-123 bears it
    # after another designator.
    assert _target(matcher, "Jeffby R-7", ("MO",), (HARBY,)) == "SYN-MO-JEF"


def test_a_county_s_name_its_districts_share_is_no_other_district_s(matcher: Matcher) -> None:
    # Both bear Barby County's name: the number tells them apart.
    assert _target(matcher, "Barby R-14", ("MO",), (BARBY,)) == "SYN-MO-BAR14"
    assert _target(matcher, "Barby Co. R-14", ("MO",), (BARBY,)) == "SYN-MO-BAR14"
    assert _target(matcher, "Barby R-12", ("MO",), (BARBY,)) == "SYN-MO-BAR12"
    # A district that does not bear it is named by BARBY R-XII's name and its own
    # number: neither.
    assert _target(matcher, "Barby R-15", ("MO",), (BARBY,)) is None
    assert _target(matcher, "Knoll R-15", ("MO",), (BARBY,)) == "SYN-MO-KNO"
