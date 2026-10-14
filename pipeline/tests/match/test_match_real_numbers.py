"""Same-named districts in Kansas, Missouri, Maine and Michigan, against the real NCES directory.

The listings the seen audit found rejected, each read in its station's registry
context (states, DMA counties, market) with the shipped aliases: Blue Valley USD
229 (Johnson County, 22,225 students) beside Blue Valley USD 384 (Riley County),
told apart by the number NCES leaves out of both names; Missouri's ``"R-3"`` and
``"C-1"`` beside Illinois's ``"CUSD 3"`` and ``"CUSD 1"``; districts a name and
number place just past the station's counties; and the listings only an alias
places. A number that contradicts
a district never names it, nor a listing whose name and number say two.

These tests read the directory ``snowlight directory build`` writes to
``out/internal/directory`` (never committed); they are skipped where it has not
been built.
"""

from pathlib import Path

import pytest

from snowlight.listed.scope import station_context
from snowlight.match import Matcher, load_aliases, load_directory
from snowlight.match.numbers import UNSAID_NUMBERS
from snowlight.sources.stations.registry import Station, load_registry

PIPELINE = Path(__file__).resolve().parents[2]
DIRECTORY = PIPELINE / "out" / "internal" / "directory"

pytestmark = pytest.mark.skipif(
    not (DIRECTORY / "schools.parquet").exists(), reason="the NCES directory is not built here"
)

BLUE_VALLEY_229, BLUE_VALLEY_384 = "2012000", "2010980"
KANSAS_STATE_SCHOOLS = frozenset({"2000018", "2000019", "2000022", "2000024", "5900103"})
"""Kansas's state schools and agencies, and a tribal school: no USD numbers them
(the School for the Blind, the School for the Deaf, the Parsons training center,
the Department of Corrections, Kickapoo Nation School)."""


@pytest.fixture(scope="module")
def matcher() -> Matcher:
    """A matcher over the real directory, with the shipped aliases."""
    return Matcher(load_directory(DIRECTORY), aliases=load_aliases())


@pytest.fixture(scope="module")
def stations() -> dict[str, Station]:
    return dict(load_registry(PIPELINE / "config" / "sources").stations)


def _target(
    matcher: Matcher, stations: dict[str, Station], market: str, listing: str, section: str | None
) -> tuple[str | None, str]:
    context = station_context(stations[market])
    result = matcher.match(
        listing,
        states=context.states,
        counties=context.counties,
        market=context.market,
        category=section,
    )
    return (result.target.id if result.target is not None else None, result.reason.value)


@pytest.mark.parametrize(
    "case",
    [
        # Kansas: the USD number its NCES name leaves out.
        ("hearst-kmbc", "Blue Valley USD229", None, BLUE_VALLEY_229),
        ("gray-kctv", "Blue Valley KS Schools - USD 229", "Schools", BLUE_VALLEY_229),
        ("nexstar-wdaf", "Blue Valley USD #229", "Schools", BLUE_VALLEY_229),
        ("scripps-kshb", "Blue Valley USD 229", None, BLUE_VALLEY_229),
        ("gray-wibw", "USD 384 Blue Valley", "SCHOOLS", BLUE_VALLEY_384),
        ("hearst-kmbc", "Leavenworth USD453 & Parochial Schools", None, "2008430"),
        ("scripps-kshb", "Leavenworth 453 & Parochial Schools", None, "2008430"),
        ("nexstar-wdaf", "Leavenworth USD 453 - Parochial Schools", "Schools", "2008430"),
        ("gray-kctv", "Leavenworth KS Sch. USD 453-Parochial", "Schools", "2008430"),
        ("nexstar-ksnt", "USD 453 - Leavenworth & Parochial Schools", "Schools", "2008430"),
        ("hearst-kmbc", "USD 453 \u2013 Leavenworth & Parochial Schools", None, "2008430"),
        ("gray-kake", "USD 309 Nickerson/S. Hutchinson", "Schools", "2009990"),
        ("hearst-kmbc", "Olathe/Blue Valley USD 229", None, BLUE_VALLEY_229),
        ("gray-kwch", "USD 309 Nickerson/S. Hutchinson", "Schools", "2009990"),
        ("gray-kwch", "USD 300 Comanche Co.-Coldwater-Protection", "Schools", "2005040"),
        ("nexstar-ksnw", "Trego Community Schools - USD 208", "Schools", "2012630"),
        ("gray-kwch", "USD 208 WaKeeney", "Schools", "2012630"),
        ("gray-wibw", "USD 456 Marais des Cygnes", "SCHOOLS", "2009480"),
        ("gray-kake", "Chase County USD 284", "Schools", "2005250"),
        ("hearst-kmbc", "Piper USD203", None, "2010680"),
        ("hearst-kmbc", "Turner USD202", None, "2012360"),
        # Missouri: its designators, a Roman number written in ones, a county named.
        ("gray-kmov", "Hillsboro R-3", "SCHOOLS", "2914430"),
        ("tegna-ksdk", "Hillsboro R3", None, "2914430"),
        ("nexstar-ktvi", "Hillsboro R 3 Schools", "Schools", "2914430"),
        ("gray-kmov", "Windsor C-1", "SCHOOLS", "2932100"),
        ("tegna-ksdk", "Windsor C-1", None, "2932100"),
        ("nexstar-wdaf", "North Harrison R-111 Eagleville MO", "Schools", "2922770"),
        ("gray-kytv", "Southwest Barry County R-5", "Schools", "2928710"),
        # Michigan: initials beside the name, a short Academy.
        ("heritage-wwtv", "TCAPS - Traverse City Area Public Schools", "Districts", "2633870"),
        ("scripps-wxyz", "Flagship Charter Acdmy", None, "260094507818"),
        # Pinned by alias, with the evidence in config/aliases.yaml.
        ("hearst-wmtw", "Auburn Schools", "Schools", "2302610"),
        ("hearst-wmtw", "Lisbon Schools", "Schools", "2307530"),
        ("sinclair-wgme", "AUBURN SCHOOLS", "SCHOOLS", "2302610"),
        ("sinclair-wgme", "Lisbon Schools", "SCHOOLS", "2307530"),
        ("gray-wabi", "East Millinocket-Medway School Departments", "Schools", "2305280"),
        ("gray-kytv", "Mountain View-Birch Tree Liberty", "Schools", "2921540"),
        ("gray-wluc", "North Central Area Schools", "Schools", "2629220"),
        ("scripps-wxmi", "Delton Kellogg School", None, "2611910"),
        ("scripps-wxmi", "Bangor Public Schools", None, "2603870"),
        ("sinclair-ktul", "Caney Valley Public Schools", None, "4025470"),
        ("gray-kake", "Nickerson-South Hutch USD 309", "Schools", "2009990"),
        ("gray-wibw", "USD 252 S. Lyon County", "SCHOOLS", "2006930"),
        ("gray-wibw", "USD 335 Jackson Hts.", "SCHOOLS", "2004830"),
        ("nexstar-wdaf", "Gardner-Edgerton-Antioch USD #231", "Schools", "2006420"),
        ("gray-kctv", "Piper Schools - USD 203 KCK", "Schools", "2010680"),
        ("gray-kwch", "USD 470 Ark City", "Schools", "2003450"),
        # A district's name and number, past the station's counties, in its states.
        ("scripps-kshb", "Maysville R-1", None, "2920550"),
        ("nexstar-wdaf", "Maysville R-1 MO", "Schools", "2920550"),
        ("nexstar-wdaf", "Marais des Cygnes Valley - USD 456", "Schools", "2009480"),
        ("nexstar-ksnw", "Logan - USD 326", "Schools", "2008910"),
        ("nexstar-ksnw", "Phillipsburg - USD 325", "Schools", "2010650"),
        ("nexstar-ksnw", "Smith Center - USD 237", "Schools", "2000007"),
        ("scripps-kshb", "McLouth USD342", None, "2009360"),
        ("scripps-kshb", "Oskaloosa USD 341", None, "2010320"),
        ("scripps-kshb", "Jefferson County North USD 339", None, "2013020"),
        ("scripps-kshb", "Lakeland R-3", None, "2910520"),
        # Just past the counties, the only one of its name near them: the ring takes it.
        ("hearst-kmbc", "Perry Lecompton Schools USD343", None, "2010620"),
        ("scripps-kshb", "Perry-Lecompton USD 343", None, "2010620"),
        # Illinois: towns a numbered district's name says, and another district of the town.
        ("abc-owned-wls", "DIST #30 (NORTHBROOK and amp; GLENVIEW)", None, "1724420"),
        (
            "abc-owned-wls",
            "DIST #113 (HIGHLAND PARK and amp; DEERFIELD HIGH SCHOOLS)",
            None,
            "1719080",
        ),
        ("abc-owned-wls", "DIST #81 (UNION SCHOOL)", None, "1739660"),
        ("nexstar-wtwo", "JASPER COUNTY UNIT 1", "Schools", "1720380"),
        # Missouri: a district number names the district before schools of its name.
        ("gray-kytv", "Swedeborg RIII", "Schools", "2929850"),
        ("nexstar-kolr", "Swedeborg RIII", "Schools", "2929850"),
        ("scripps-kshb", "Crestridge R-7", None, "2908320"),
        ("gray-kmov", "Jefferson R-VII", "SCHOOLS", "2916230"),
    ],
)
def test_the_audit_s_rejected_listings_name_their_districts(
    matcher: Matcher, stations: dict[str, Station], case: tuple[str, str, str | None, str]
) -> None:
    market, listing, section, expected = case
    assert _target(matcher, stations, market, listing, section)[0] == expected


@pytest.mark.parametrize(
    ("market", "listing", "expected"),
    [
        # Each Blue Valley is named by its own number only.
        ("gray-wibw", "Blue Valley USD 384", BLUE_VALLEY_384),
        ("gray-wibw", "USD 384 Blue Valley", BLUE_VALLEY_384),
        ("scripps-kshb", "Blue Valley USD 512", None),
        # USD 384's own place, Riley County, lies far past KSHB's counties.
        ("scripps-kshb", "Blue Valley USD 384", None),
        ("gray-wibw", "USD 229 Blue Valley", BLUE_VALLEY_229),
        # Illinois's designator names Illinois's Windsor CUSD 1, of Shelby County,
        # past KMOV's counties, never Missouri's Windsor C-1 in them.
        ("gray-kmov", "Windsor CUSD 1", "1742690"),
        # Festus's own number names it; Jefferson's, its county's district.
        ("tegna-ksdk", "Festus R-6", "2912030"),
        ("tegna-ksdk", "Jefferson R-7", "2916230"),
        # Colorado's Weld County districts bear the county's name, some with
        # "County" and some without: the number tells them apart.
        ("scripps-kmgh", "Weld RE-5J School District", "0804830"),
        ("scripps-kmgh", "Weld RE-8", "0804020"),
    ],
)
def test_a_number_names_only_the_namesake_it_is_the_number_of(
    matcher: Matcher, stations: dict[str, Station], market: str, listing: str, expected: str | None
) -> None:
    assert _target(matcher, stations, market, listing, "Schools")[0] == expected


@pytest.mark.parametrize(
    ("market", "listing"),
    [
        # One district's name and another's number (Blue Valley is USD 229, Derby
        # USD 260, Auburn-Washburn USD 437, Nickerson USD 309): neither is named.
        ("hearst-kmbc", "Olathe USD 229"),
        ("hearst-kmbc", "Olathe Public Schools USD 229"),
        ("gray-kake", "Wichita USD 260"),
        ("gray-wibw", "Topeka USD 437"),
        ("gray-kake", "Hutchinson USD 309"),
        # Words that only place the name change nothing.
        ("hearst-kmbc", "Olathe Area USD 229"),
        ("hearst-kmbc", "City of Olathe USD 229"),
        ("hearst-kmbc", "Olathe, Johnson Co. USD 229"),
        ("hearst-kmbc", "Olathe & Spring Hill USD 229"),
        ("gray-kake", "City of Wichita USD 260"),
        ("gray-kake", "Wichita (Sedgwick Co.) USD 260"),
        ("gray-wibw", "Topeka Shawnee County USD 437"),
        ("gray-wibw", "Topeka Area USD 437"),
        ("gray-kake", "Hutchinson Area USD 309"),
        # The same on each list that carried them.
        ("gray-kctv", "Olathe Area USD 229"),
        ("scripps-kshb", "Olathe Area USD 229"),
        ("nexstar-wdaf", "Olathe Area USD 229"),
        ("gray-kwch", "City of Wichita USD 260"),
        ("nexstar-ksnw", "Wichita (Sedgwick Co.) USD 260"),
        ("nexstar-ksnt", "Topeka Area USD 437"),
        ("nexstar-ksnt", "Topeka Shawnee County USD 437"),
        # Missouri's numbers: Festus is R-VI, and JEFFERSON CO. R-VII sits in Festus.
        ("tegna-ksdk", "Festus R-7"),
        ("tegna-ksdk", "Festus R-VII"),
        ("tegna-ksdk", "Festus Area R-7"),
        # A town of a district with its number, just past the counties (Melvern is
        # Marais des Cygnes Valley's, USD 456), and a namesake whose own place lies
        # far past them, though one of its schools is near (Blue Valley USD 384, of
        # Riley County).
        ("nexstar-wdaf", "USD 456 Osage City"),
        ("nexstar-wdaf", "Melvern USD 456"),
        ("hearst-kmbc", "Blue Valley USD 384"),
        # A town's parochial schools alone are not its public district.
        ("hearst-kcci", "Ft. Dodge - Parochial Schools"),
        ("hearst-kcci", "Boone - Parochial"),
        ("nexstar-wfrv", "Kewaunee/Parochial"),
        ("hearst-kmbc", "Leavenworth - Parochial"),
        ("hearst-kcci", "Ft. Dodge Schools - Parochial"),
        ("hearst-kmbc", "Leavenworth Schools - Parochial"),
        ("nexstar-wfrv", "Green Bay Schools - Parochial"),
        ("gray-kwch", "Ft. Dodge Schools - Parochial"),
    ],
)
def test_a_listing_that_names_no_one_district_lights_none(
    matcher: Matcher, stations: dict[str, Station], market: str, listing: str
) -> None:
    assert _target(matcher, stations, market, listing, "Schools")[0] is None


@pytest.mark.parametrize(
    ("market", "listing"),
    [
        # A namesake just past the counties: the list may stray past them (WMUR
        # lists Grafton County, New Hampshire), so the counties cannot say which.
        ("hearst-wmur", "Littleton School District"),
        ("hearst-wmur", "Hanover High School"),
        ("sinclair-wgme", "Andover Elementary School"),
        ("scripps-kshb", "Blue Valley Schools"),
        ("hearst-kmbc", "Blue Valley"),
    ],
)
def test_a_namesake_just_past_the_counties_leaves_the_listing_ambiguous(
    matcher: Matcher, stations: dict[str, Station], market: str, listing: str
) -> None:
    assert _target(matcher, stations, market, listing, "Schools") == (None, "ambiguous")


def test_the_two_maine_departments_are_both_named(matcher: Matcher) -> None:
    result = matcher.match(
        "East Millinocket-Medway School Departments", states=("ME",), market="gray-wabi"
    )
    assert {record.id for record in result.targets} == {"2305280", "2308160"}


def test_every_kansas_unified_district_has_its_number() -> None:
    directory = load_directory(DIRECTORY)
    districts = {
        record.id for record in directory if record.kind == "district" and record.state == "KS"
    }
    assert set(UNSAID_NUMBERS) == districts - KANSAS_STATE_SCHOOLS
